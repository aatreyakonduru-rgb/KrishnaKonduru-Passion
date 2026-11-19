#!/usr/bin/env python3
"""Who may change which folders, read from the `access:` section of .devin/rules/people.yaml.

The roster says which roles each person holds; `access:` says which roles may change which paths.
Devin's write hook, the git pre-commit check and the approval gates all ask this module.

    access_guard.py check PATH ...       exit 0 when the session owner may change every PATH, 2 when not
    access_guard.py staged               the same for the files staged in git (the pre-commit check)
    access_guard.py whoami [--set EMAIL] who the guard thinks is asking; --set records the requester
                                         that /identify-requester matched from the chat identity
    access_guard.py verify               is people.yaml the same as the Confluence roster page?
    access_guard.py approve              a knowledge-base-only requester (PO, BSA) typed "approved":
                                         record it against exactly the staged files
    access_guard.py approval-trailer     the Approved-by value for this commit (the commit-msg hook);
                                         exit 2 when a knowledge-base-only requester has not approved
    access_guard.py pr-check [--base REF] [--head REF]
                                         a knowledge-base-only requester's branch may change only the
                                         knowledge base and every commit needs Approved-by (pre-push)
    access_guard.py pr-audit [--base REF] [--head REF] [--pr-requester EMAIL]
                                         every commit on the branch: has Requested-by, that person
                                         may change its files, PO/BSA commits are approved, and the
                                         person matches who opened the pull request (for a PR build)
    access_guard.py shell-check          a shell command (on stdin) that would skip or switch off the
                                         git hooks or forge the requester: exit 2 (the exec hook)

Rules: the longest matching path wins; `{owner}` in a path is the person's own session folder;
`any` means anyone on the roster; a path no area lists needs one of `default_roles`.
Before allowing a change it checks people.yaml against the Confluence roster page (roster_sync.py
verify), caching a success for VERIFY_TTL seconds per people.yaml content. If the page cannot be
read the change is blocked. The roster sign-off must also be one that `access.roster_signoff` accepts
for the current gates.mode (default: the owner's or a backup's); a pending roster blocks too.
The roster and its `access:` rules are read from people.yaml as committed on origin/<repo.kb_branch>
(else HEAD), never from the checkout's edited copy, so a change to people.yaml cannot loosen the
check that judges it. A roster that names a roster page but has no `access:` blocks every change;
only a roster with neither (a fresh install) turns the guard off.
SDLC_OWNER may name someone other than the requester /identify-requester recorded only when that
requester holds a lead role (`su - <name>`).

This is a guard against mistakes inside Devin, not access control: anyone can edit their own
checkout. The hard control is Bitbucket (branch permissions and required approvers).
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import session_store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
PROFILE_PATH = os.path.join(ROOT, ".devin", "rules", "sdlc-profile.json")
STATE_DIR = os.path.join(os.path.expanduser("~"), ".sdlc")
VERIFY_TTL = 15 * 60
ANY = "any"
KB_AREA = "knowledge base"
CODE_AREA = "application code"


class GuardError(Exception):
    pass


def load_roster(path=PEOPLE_PATH):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def trusted_roster(path=PEOPLE_PATH, root=ROOT, branch=None):
    """people.yaml as committed on origin/<repo.kb_branch>, else at HEAD; the file on disk only when
    git has neither. The rules never come from an uncommitted edit."""
    rel = relpath(path, root)
    if rel:
        branch = branch if branch is not None else kb_branch()
        for ref in (["origin/" + branch] if branch else []) + ["HEAD"]:
            try:
                text = _git(root, "show", "%s:%s" % (ref, rel))
            except (subprocess.CalledProcessError, OSError):
                continue
            return yaml.safe_load(text) or {}
    return load_roster(path)


def has_source(roster):
    page = str((roster.get("source") or {}).get("confluence_page_id") or "")
    return bool(page) and not page.startswith("{{")


# ---- is people.yaml the roster page? --------------------------------------------------------

def _cache_path():
    return os.path.join(STATE_DIR, "roster-verified.json")


def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


DEFAULT_SIGNOFF = ["owner", "backup"]


def gate_mode():
    return os.environ.get("SDLC_GATE_MODE") or session_store.load_config().get("gates", {}).get("mode", "enforced")


def signoff_problem(roster, mode=None):
    """None when the roster's sign-off is one `access.roster_signoff` accepts in this gates mode,
    else why not. `owner` accepts the owner's sign-off, `backup` a backup's (interim), and any other
    word a signer who holds that gate role."""
    mode = mode or gate_mode()
    accepted = ((roster.get("access") or {}).get("roster_signoff") or {}).get(mode) or DEFAULT_SIGNOFF
    signoff = (roster.get("owner") or {}).get("signoff") or {}
    status, by = signoff.get("status") or "pending", signoff.get("signed_by")
    if status == "pending":
        return "the roster owner has not signed the roster page yet (%s mode needs: %s)" % (mode, ", ".join(accepted))
    signer = next((p for p in roster.get("people") or [] if by and p.get("jira_user") == by), None)
    held = set((signer or {}).get("roles") or [])
    if status == "signed":
        held.add("owner")
    if status == "interim":
        held.add("backup")
    if held & set(accepted):
        return None
    return "the roster is %s by %s, but %s mode needs a sign-off from: %s" % (status, by or "nobody", mode,
                                                                            ", ".join(accepted))


def verify_roster(path=PEOPLE_PATH, verifier=None, now=None, mode=None):
    """-> (ok, message). A roster with no Confluence source has nothing to verify against."""
    now = now if now is not None else time.time()
    roster = load_roster(path)
    if not has_source(roster):
        if roster.get("access"):
            return False, ("people.yaml has access rules but no roster page under source: "
                           "set source.confluence_page_id, publish the roster and sign it")
        return True, "roster has no source page; nothing to verify"
    if roster.get("access"):
        problem = signoff_problem(roster, mode)
        if problem:
            return False, problem
    digest = _digest(path)
    try:
        with open(_cache_path(), encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("sha256") == digest and now - float(cached.get("at", 0)) < VERIFY_TTL:
            return True, "roster verified %d s ago" % int(now - float(cached["at"]))
    except (OSError, ValueError):
        pass
    if verifier is None:
        import roster_sync
        verifier = roster_sync.verify_file
    try:
        ok, version, lines = verifier(path)
    except Exception as exc:  # no token, network, 401/403, page changed shape: fail closed
        return False, "cannot read the roster page to verify people.yaml (%s)" % str(exc).splitlines()[0]
    if not ok:
        return False, "people.yaml differs from the roster page (version %s): %s" % (version, "; ".join(lines))
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_cache_path(), "w", encoding="utf-8") as fh:
            json.dump({"sha256": digest, "at": now, "page_version": version}, fh)
    except OSError:
        pass
    return True, "roster verified against page version %s" % version


# ---- who is asking ---------------------------------------------------------------------------

def _requester_path():
    return os.path.join(STATE_DIR, "requester.json")


def person_for(key, roster):
    key = (key or "").strip().lower()
    if not key:
        return None
    for p in roster.get("people") or []:
        email = str(p.get("email") or "").lower()
        if key in (email, session_store.slug(email), str(p.get("jira_user") or "").lower()):
            return p
    return None


def current_person(roster):
    """SDLC_OWNER, then the requester /identify-requester recorded, then the git author email."""
    candidates = [os.environ.get("SDLC_OWNER")]
    try:
        with open(_requester_path(), encoding="utf-8") as fh:
            candidates.append(json.load(fh).get("email"))
    except (OSError, ValueError):
        pass
    candidates.append(session_store.resolve_owner())
    for key in candidates:
        person = person_for(key, roster)
        if person:
            return person
    return None


def _recorded_email():
    try:
        with open(_requester_path(), encoding="utf-8") as fh:
            return json.load(fh).get("email")
    except (OSError, ValueError, AttributeError):
        return None


def is_lead(person):
    """His rule: anyone with "lead" in any of their roles."""
    roles = list((person or {}).get("roles") or []) + list((person or {}).get("secondary_roles") or [])
    roles.append((person or {}).get("primary_role") or "")
    return any("lead" in str(r) for r in roles)


def _same(a, b):
    return bool(a and b) and str(a.get("email") or "").lower() == str(b.get("email") or "").lower()


def identity_problem(roster):
    """None, or why SDLC_OWNER may not be used: it names someone other than the requester
    /identify-requester recorded from the chat identity, and that requester is not a lead."""
    claimed = person_for(os.environ.get("SDLC_OWNER"), roster)
    recorded = person_for(_recorded_email(), roster)
    if not claimed or not recorded or _same(claimed, recorded) or is_lead(recorded):
        return None
    return ("SDLC_OWNER names %s, but this session's requester is %s; only a lead may act as someone "
            "else, so set SDLC_OWNER to the requester or leave it unset" % (claimed.get("name"), recorded.get("name")))


def set_requester(email, roster):
    person = person_for(email, roster)
    if not person:
        raise GuardError("%s is not on the roster" % email)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_requester_path(), "w", encoding="utf-8") as fh:
        json.dump({"email": person.get("email"), "jira_user": person.get("jira_user"), "at": time.time()}, fh)
    return person


# ---- which area a path is in -----------------------------------------------------------------

def relpath(path, root=ROOT):
    """Repository-relative path with forward slashes, or None when the path is outside the repo."""
    full = os.path.abspath(os.path.join(root, path))
    rel = os.path.relpath(full, root)
    if rel == os.curdir or rel.startswith(os.pardir + os.sep) or rel == os.pardir:
        return None
    return rel.replace(os.sep, "/")


def area_for(rel, access, person):
    """The area whose path is the longest prefix of rel, or None for an unlisted path."""
    owner = session_store.slug((person or {}).get("email") or "") or "\0"
    best, best_len = None, -1
    for area in access.get("areas") or []:
        for prefix in area.get("paths") or []:
            prefix = prefix.replace("{owner}", owner).rstrip("/")
            if (rel == prefix or rel.startswith(prefix + "/")) and len(prefix) > best_len:
                best, best_len = area, len(prefix)
    return best


def may_change(person, roles):
    if not person:
        return False
    return ANY in roles or bool(set(person.get("roles") or []) & set(roles))


def path_problems(person, rels, access):
    blocked = []
    for rel in rels:
        area = area_for(rel, access, person)
        roles = (area or {}).get("roles") or access.get("default_roles") or []
        if not may_change(person, roles):
            blocked.append("%s (%s) may not change %s — %s needs one of: %s" % (
                person.get("name"), ", ".join(person.get("roles") or []) or "no roles", rel,
                (area or {}).get("name") or "an unlisted path", ", ".join(roles) or "nobody"))
    return blocked


def check(paths, roster=None, people_path=PEOPLE_PATH, root=ROOT, verifier=None):
    """-> list of reasons the change is blocked; empty means allowed."""
    roster = roster if roster is not None else load_roster(people_path)
    access = roster.get("access")
    rels = [r for r in (relpath(p, root) for p in paths) if r]
    if not access:
        if rels and has_source(roster):
            return ["people.yaml names a roster page but has no access: section, so changes are blocked: "
                    "restore the access rules from the roster page (/roster-sync)"]
        return []
    if not rels:
        return []
    problem = identity_problem(roster)
    if problem:
        return [problem]
    person = current_person(roster)
    if not person:
        return ["cannot tell who is asking: run /identify-requester (or set SDLC_OWNER) so the session "
                "owner is matched to someone on the roster"]
    ok, why = verify_roster(people_path, verifier=verifier)
    if not ok:
        return ["roster not verified, so changes to the repository are blocked: " + why]
    return path_problems(person, rels, access)


def no_self_approval(roster):
    return set((roster.get("access") or {}).get("no_self_approval") or [])


def staged_paths(root=ROOT):
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


# ---- knowledge-base-only requesters: approval stamp and pull-request check ------------------

def _area_named(access, name):
    for area in access.get("areas") or []:
        if area.get("name") == name:
            return area
    return None


def kb_only(person, access):
    """True for someone who may change the knowledge base but not application code (PO, BSA)."""
    kb, code = _area_named(access or {}, KB_AREA), _area_named(access or {}, CODE_AREA)
    if not (person and kb and code):
        return False
    return may_change(person, kb.get("roles") or []) and not may_change(person, code.get("roles") or [])


def in_kb(rel, access):
    prefixes = [p.rstrip("/") for p in (_area_named(access, KB_AREA) or {}).get("paths") or []]
    return any(rel == p or rel.startswith(p + "/") for p in prefixes)


def _git(root, *args):
    return subprocess.run(["git"] + list(args), cwd=root, capture_output=True, text=True, check=True).stdout


def _approval_path():
    return os.path.join(STATE_DIR, "approval.json")


def _approval_value(record):
    return "%s (%s) <%s> %s" % (record.get("name"), ", ".join(record.get("roles") or []) or "no roles",
                                record.get("email"), record.get("at"))


def record_approval(roster, root=ROOT, people_path=PEOPLE_PATH, verifier=None, now=None):
    """The requester approved what is staged: record it against the staged tree, return Approved-by."""
    problem = identity_problem(roster)
    if problem:
        raise GuardError(problem)
    person = current_person(roster)
    if not person:
        raise GuardError("cannot tell who is approving: run /identify-requester (or set SDLC_OWNER)")
    paths = staged_paths(root)
    if not paths:
        raise GuardError("nothing is staged, so there is nothing to approve")
    blocked = check(paths, roster, people_path, root=root, verifier=verifier)
    if blocked:
        raise GuardError("; ".join(blocked))
    record = {"email": person.get("email"), "name": person.get("name"), "roles": person.get("roles") or [],
              "tree": _git(root, "write-tree").strip(),
              "at": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(now if now is not None else time.time()))}
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_approval_path(), "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    return _approval_value(record)


def approval_trailer(roster, root=ROOT):
    """-> (Approved-by value or None, reason to refuse the commit or None). Uses the approval up.

    The approval counts only for the requester who gave it and for exactly the staged files it was
    given on; anything staged afterwards needs a new one."""
    person = current_person(roster)
    try:
        with open(_approval_path(), encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        record = None
    if record and person and str(record.get("email")).lower() == str(person.get("email")).lower() \
            and record.get("tree") == _git(root, "write-tree").strip():
        os.remove(_approval_path())
        return _approval_value(record), None
    if kb_only(person, roster.get("access")):
        return None, ("%s (%s) has not approved these files: show them the change and, when they type "
                      "\"approved\", run access_guard.py approve, then commit" % (
                          person.get("name"), ", ".join(person.get("roles") or [])))
    return None, None


def kb_branch(profile_path=PROFILE_PATH):
    try:
        with open(profile_path, encoding="utf-8") as fh:
            return (json.load(fh).get("repo") or {}).get("kb_branch")
    except (OSError, ValueError):
        return None


def pr_problems(base, roster, head="HEAD", root=ROOT, people_path=PEOPLE_PATH, verifier=None):
    """-> reasons a knowledge-base-only requester's branch may not go to a pull request."""
    access = roster.get("access")
    person = current_person(roster)
    if not access or not kb_only(person, access):
        return []
    files = [p for p in _git(root, "diff", "--name-only", "-z", "%s...%s" % (base, head)).split("\0") if p]
    problems = ["%s is outside the knowledge base: a %s pull request may change only %s" % (
        rel, ", ".join(person.get("roles") or []), ", ".join((_area_named(access, KB_AREA) or {}).get("paths") or []))
        for rel in files if not in_kb(rel, access)]
    problems += check(files, roster, people_path, root=root, verifier=verifier) if files else []
    for sha in _git(root, "rev-list", "--no-merges", "%s..%s" % (base, head)).split():
        stamp = _git(root, "log", "-1", "--format=%(trailers:key=Approved-by,valueonly)", sha).strip()
        if not stamp:
            problems.append("commit %s has no Approved-by stamp" % sha[:8])
    return problems


def _trailer_email(value):
    match = re.search(r"<([^>]+)>", value or "")
    return match.group(1) if match else (value or "").strip()


def pr_audit(base, roster, head="HEAD", root=ROOT, pr_requester=None):
    """-> problems with the branch's commits, read from git alone (no local state), so a pull-request
    build can run it: a commit with no Requested-by (made with --no-verify or without the hooks),
    a requester off the roster or not allowed the commit's files, a PO/BSA commit with no
    Approved-by, and a requester who is not the person who opened the pull request (unless a lead)."""
    access = roster.get("access") or {}
    opener = person_for(pr_requester, roster) if pr_requester else None
    problems = []
    if pr_requester and not opener:
        problems.append("the pull request was opened for %s, who is not on the roster" % pr_requester)
    for sha in _git(root, "rev-list", "--no-merges", "%s..%s" % (base, head)).split():
        short = sha[:8]
        asked = _git(root, "log", "-1", "--format=%(trailers:key=Requested-by,valueonly)", sha).strip()
        if not asked:
            problems.append("commit %s has no Requested-by: it was made with --no-verify or without the hooks" % short)
            continue
        person = person_for(_trailer_email(asked.splitlines()[0]), roster)
        if not person:
            problems.append("commit %s: Requested-by %s is not on the roster" % (short, asked.splitlines()[0]))
            continue
        files = [f for f in _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha).split("\0") if f]
        problems += ["commit %s: %s" % (short, why) for why in path_problems(person, files, access)] if access else []
        if access and kb_only(person, access):
            if not _git(root, "log", "-1", "--format=%(trailers:key=Approved-by,valueonly)", sha).strip():
                problems.append("commit %s by %s has no Approved-by stamp" % (short, person.get("name")))
        if opener and not _same(opener, person) and not is_lead(opener):
            problems.append("commit %s says %s asked for it, but the pull request was opened for %s" % (
                short, person.get("name"), opener.get("name")))
    return problems


SKIP_HOOKS = re.compile(r"--no-verify\b|core\.hooksPath|\bHUSKY=0\b")
PROTECTED = re.compile(r"\.git/hooks|\.sdlc/(requester|approval|roster-verified)\.json")
WRITES = re.compile(r"(^|[\s;&|(])(rm|mv|cp|ln|tee|truncate|chmod|install|dd|sed\s+-i\S*|perl\s+-\S*i)\b"
                    r"|(?<![0-9&>])>>?(?!\s*/dev/null)")


def shell_problems(command):
    """-> why a shell command is refused: it skips or switches off the git hooks, or writes the
    hook files or the guard's own records (the requester, approvals) by hand."""
    problems = []
    if SKIP_HOOKS.search(command):
        problems.append("the command skips or redirects the git hooks (--no-verify, core.hooksPath)")
    for segment in re.split(r"&&|\|\||;|\|", command):
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        if "git" in words and "commit" in words[words.index("git"):]:
            flags = [w for w in words[words.index("commit") + 1:] if re.fullmatch(r"-[A-Za-z]+", w)]
            if any("n" in f and "m" not in f[:f.index("n")] for f in flags):
                problems.append("git commit -n skips the git hooks")
        if PROTECTED.search(segment) and WRITES.search(segment):
            problems.append("the command changes the git hooks or the access guard's records by hand; "
                            "use access_guard.py whoami --set / approve instead")
    return list(dict.fromkeys(problems))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--people", default=PEOPLE_PATH)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").add_argument("paths", nargs="+")
    sub.add_parser("staged")
    sub.add_parser("whoami").add_argument("--set", dest="email")
    sub.add_parser("verify")
    sub.add_parser("trailer", help="print 'Name <email>' of the requester for the Requested-by commit trailer")
    sub.add_parser("approve", help="record that the requester approved exactly the staged files")
    sub.add_parser("approval-trailer", help="print the Approved-by value for this commit (commit-msg hook)")
    pr = sub.add_parser("pr-check", help="may this branch go to a pull request? (pre-push hook)")
    pr.add_argument("--base", help="default: origin/<repo.kb_branch in sdlc-profile.json>")
    pr.add_argument("--head", default="HEAD")
    audit = sub.add_parser("pr-audit", help="check every commit on the branch (a pull-request build)")
    audit.add_argument("--base", help="default: origin/<repo.kb_branch in sdlc-profile.json>")
    audit.add_argument("--head", default="HEAD")
    audit.add_argument("--pr-requester", help="email of the person the pull request was opened for")
    sub.add_parser("shell-check", help="refuse a shell command (on stdin) that skips the git hooks")
    args = parser.parse_args(argv)
    if args.command == "shell-check":
        problems = shell_problems(sys.stdin.read())
        if problems:
            print("ACCESS-BLOCK: " + "\nACCESS-BLOCK: ".join(problems))
            return 2
        return 0
    try:
        roster = trusted_roster(args.people)
        if args.command == "whoami":
            person = set_requester(args.email, roster) if args.email else current_person(roster)
            if not person:
                print("not matched to anyone on the roster")
                return 1
            print("%s (%s): %s" % (person.get("name"), person.get("jira_user"), ", ".join(person.get("roles") or [])))
            return 0
        if args.command == "trailer":
            problem = identity_problem(roster)
            if problem:
                print(problem)
                return 1
            person = current_person(roster)
            if not person:
                print("not matched to anyone on the roster")
                return 1
            print("%s <%s>" % (person.get("name"), person.get("email")))
            return 0
        if args.command == "approve":
            print(record_approval(roster, people_path=args.people))
            return 0
        if args.command == "approval-trailer":
            value, refused = approval_trailer(roster)
            if refused:
                print(refused)
                return 2
            if value:
                print(value)
            return 0
        if args.command == "pr-audit":
            base = args.base or ("origin/" + kb_branch() if kb_branch() else None)
            if not base:
                raise GuardError("no --base and no repo.kb_branch in sdlc-profile.json")
            problems = pr_audit(base, roster, head=args.head, pr_requester=args.pr_requester)
            if problems:
                print("ACCESS-AUDIT: " + "\nACCESS-AUDIT: ".join(problems))
                return 2
            print("every commit names a requester on the roster who may change its files")
            return 0
        if args.command == "pr-check":
            base = args.base or ("origin/" + kb_branch() if kb_branch() else None)
            if not base:
                raise GuardError("no --base and no repo.kb_branch in sdlc-profile.json")
            problems = pr_problems(base, roster, head=args.head, people_path=args.people)
            if problems:
                print("ACCESS-BLOCK: " + "\nACCESS-BLOCK: ".join(problems))
                return 2
            return 0
        if args.command == "verify":
            ok, why = verify_roster(args.people)
            print(why)
            return 0 if ok else 1
        paths = args.paths if args.command == "check" else staged_paths()
        blocked = check(paths, roster, args.people)
    except (GuardError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("ACCESS-BLOCK: the access check could not run: %s" % exc)
        return 1
    if blocked:
        print("ACCESS-BLOCK: " + "\nACCESS-BLOCK: ".join(blocked))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
