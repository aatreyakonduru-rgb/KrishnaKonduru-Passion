#!/usr/bin/env python3
"""Install the shared SDLC into your repository, change its settings later, or check it.

    python3 install.py --target ../your-repo                    # asks for your values
    python3 install.py --target ../your-repo --values mine.yaml # takes them from a file
    python3 sdlc/install.py --reconfigure [--values mine.yaml]  # installed repo: change values
    python3 sdlc/install.py --check [--offline]                 # installed repo: run the checks
    python3 install_ui.py                                       # the install window (see START-HERE.md)

The shared copy holds made-up "Acme Claims" values. Installing copies it into your repo (with
the real names back: dot-devin/ -> .devin/, SKILL.dist.md -> SKILL.md, AGENTS.dist.md ->
AGENTS.md), swaps every Acme value for yours, records your values in
.devin/rules/sdlc-install.yaml, and runs the checks. Tokens are read from the environment
variables you name and are never printed.

The SDLC folder (`sdlc_dir`, default sdlc) and the knowledge-base folder (`kb_dir`, default
docs/knowledge-base) are your choice; every path to them is rewritten. The window
(install_ui.py) also writes the roster, Jira statuses and fields, environments, Confluence pages
and KB source folders (`settings:` in the values file).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VALUES_FILE = ".devin/rules/sdlc-install.yaml"
STORED_DIRS = {"dot-devin": ".devin"}
STORED_FILES = {"SKILL.dist.md": "SKILL.md", "AGENTS.dist.md": "AGENTS.md"}
# the Acme samples stay Acme: they are the example to copy from, and the tests of the example
# (lines between the two markers) expect them
KEEP = ("sdlc/kb/examples/",)
SAMPLE = re.compile(r"(?ms)^[ \t]*# shared-copy sample: begin.*?^[ \t]*# shared-copy sample: end[^\n]*\n?")
# run after values change, so counts, catalogue, reference pages and the KB manifest match
REGENERATE = [
    ["sdlc/framework/tools/validate_framework.py", "--fix"],
    ["sdlc/framework/tools/gen_catalogue.py"],
    ["sdlc/framework/tools/gen_reference_pages.py"],
    ["sdlc/framework/tools/kb_manifest.py", "generate"],
]

# key, value in the shared copy, question; "@" marks values only replaced right after an @
VALUES = [
    ("product_name", "Acme Claims", "Product or team name, as people write it"),
    ("company_name", "Acme Corp", "Company name"),
    ("jira_host", "jira.acme.example", "Jira host (no https://)"),
    ("jira_project", "ACME", "Jira project key"),
    ("jira_token_env", "ACME_JIRA_TOKEN", "Environment variable / Devin secret holding the Jira token"),
    ("wiki_host", "wiki.acme.example", "Confluence host (no https://)"),
    ("wiki_space", "ACMEWIKI", "Confluence space key"),
    ("confluence_token_env", "ACME_CONFLUENCE_TOKEN", "Environment variable / Devin secret holding the Confluence token"),
    ("git_host", "git.acme.example", "Git server host (no https://)"),
    ("repo_slug", "ACME/claims-web", "Application repo, PROJECT/repo"),
    ("deploy_slug", "ACME/claims-deploy", "Deployment (config) repo, PROJECT/repo"),
    ("qa_repo_slug", "ACME/claims-qa", "Test automation repo, PROJECT/repo"),
    ("work_branch", "feature/devin-sdlc", "Branch the SDLC works on"),
    ("devin_host", "acme.devinenterprise.com", "Devin host (no https://)"),
    ("email_domain", "@acme.example", "Email domain of your team (after the @)"),
]
# where the framework goes in your repo; paths are rewritten, the words are not
FOLDERS = [
    ("sdlc_dir", "sdlc", "Folder at the root of your repo for the SDLC framework (playbooks, tools, Argus, KB prompts)"),
    ("kb_dir", "docs/knowledge-base", "Folder in your repo for the knowledge base documents"),
]
FOLDER_KEYS = tuple(k for k, _, _ in FOLDERS)
SWAP_KEYS = tuple(k for k, _, _ in VALUES)
DEFAULTS = {k: v for k, v, _ in VALUES + FOLDERS}
SLUGS = ("repo_slug", "deploy_slug", "qa_repo_slug")
# the installer itself: copied from where this script is, never rewritten (it holds the Acme examples)
ENGINE_FILES = ("install.py", "install_ui.py", "install_steps.py", "START-HERE.md", "templates/values-template.yaml",
                "templates/roster-template.csv", "templates/blueprint-template.yaml",
                "templates/knowledge-note-template.md")
SDLC_TOP = r"(?:framework|kb|install\.py|install_ui\.py|README\.md|START-HERE\.md|templates)(?![\w-])"


# window-only settings that are not kept in the installed values file (the roster lives in people.yaml)
NOT_STORED = ("roster", "target", "clone_url")


def sp(values, path):
    """A path written for the default SDLC folder, in the chosen one."""
    if path.startswith("sdlc/"):
        return values.get("sdlc_dir", "sdlc") + path[4:]
    return path


def engine_paths(values):
    return {sp(values, "sdlc/" + rel) for rel in ENGINE_FILES}


def load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def dump_values(path, values, settings=None):
    lines = ["# Written by sdlc/install.py: the values this repo was set up with. Change them with",
             "#   python3 sdlc/install.py --reconfigure", ""]
    for key, _, question in VALUES + FOLDERS:
        lines += ["# " + question, "%s: %s" % (key, json.dumps(values[key].lstrip("@")))]
    if settings:
        import yaml
        lines += ["", "# What the install window set up (roster, Jira, Confluence pages, environments, KB folders)",
                  yaml.safe_dump({"settings": settings}, sort_keys=False, allow_unicode=True, width=110).rstrip()]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def normalise(values):
    out = {}
    for key, default, _ in VALUES + FOLDERS:
        v = str(values.get(key, default if key in FOLDER_KEYS else "") or "").strip()
        v = re.sub(r"^https?://", "", v).rstrip("/") if key.endswith("_host") else v
        if key in FOLDER_KEYS:
            v = v.replace("\\", "/").strip("/")
        if default.startswith("@") and v and not v.startswith("@"):
            v = "@" + v
        out[key] = v
    return out


def folder_problems(values):
    out = []
    sdlc, kb = values.get("sdlc_dir", ""), values.get("kb_dir", "")
    if not re.fullmatch(r"[A-Za-z0-9][\w.-]*", sdlc or ""):
        out.append("sdlc_dir must be one folder name at the root of your repo (letters, digits, . _ -), got %r" % sdlc)
    if not re.fullmatch(r"[A-Za-z0-9][\w.-]*(/[A-Za-z0-9][\w.-]*)*", kb or ""):
        out.append("kb_dir must be a folder path inside your repo, like docs/knowledge-base, got %r" % kb)
    for key, v in (("sdlc_dir", sdlc), ("kb_dir", kb)):
        if v and v.split("/")[0] in (".devin", ".git", "node_modules"):
            out.append("%s cannot be inside %s" % (key, v.split("/")[0]))
    if sdlc and kb and (kb == sdlc or kb.startswith(sdlc + "/")):
        out.append("kb_dir (%s) must not be inside sdlc_dir (%s)" % (kb, sdlc))
    return out


def problems(values):
    out = folder_problems(values)
    for key, default, question in VALUES:
        v = values.get(key, "")
        if not v or v == "@":
            out.append("%s is empty (%s)" % (key, question))
        elif key in SLUGS and not re.fullmatch(r"[\w.-]+/[\w.-]+", v):
            out.append("%s must look like PROJECT/repo, got %r" % (key, v))
        elif key.endswith("_env") and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v):
            out.append("%s must be an environment variable name, got %r" % (key, v))
        elif re.search(r"\s", v) and key not in ("product_name", "company_name"):
            out.append("%s must not contain spaces, got %r" % (key, v))
    return out


def ask(current, given, interactive, folders=True):
    values = dict(current)
    values.update({k: v for k, v in (given or {}).items() if k in DEFAULTS})
    if interactive:
        print("Your values (Enter keeps the one in brackets):")
        for key, _, question in VALUES + (FOLDERS if folders else []):
            answer = input("  %s [%s]: " % (question, values[key].lstrip("@"))).strip()
            if answer:
                values[key] = answer
    return normalise(values)


def pairs(old, new):
    """(old text, new text) for every value that changes, with the repo names inside slugs."""
    out = []
    for key in SWAP_KEYS:
        if old[key] != new[key]:
            out.append((old[key], new[key]))
    for key in SLUGS:
        o, n = old[key].split("/")[-1], new[key].split("/")[-1]
        if o != n:
            out.append((o, n))
    if old["jira_project"] != new["jira_project"]:
        # ticket keys inside names (after-ACME-9-fix) and lower-case ones (acme-12) as people type them
        out.append((old["jira_project"] + "-", new["jira_project"] + "-"))
        out.append((old["jira_project"].lower() + "-", new["jira_project"].lower() + "-"))
    return sorted(set(out), key=lambda p: len(p[0]), reverse=True)


def rewriter(changes):
    if not changes:
        return None
    alts = []
    for o, _ in changes:
        alt = re.escape(o)
        if re.match(r"\w", o):
            alt = (r"(?<![\w.])" if o.endswith("-") else r"(?<![\w.-])") + alt
        if re.search(r"\w$", o):
            alt += r"(?![\w])"
        elif o.endswith("-"):
            alt += r"(?=\d)"
        alts.append("(%s)" % alt)
    rx = re.compile("|".join(alts))
    to = [n for _, n in changes]

    def sub(text):
        out, pos = [], 0
        for m in SAMPLE.finditer(text):
            out += [rx.sub(lambda x: to[x.lastindex - 1], text[pos:m.start()]), m.group(0)]
            pos = m.end()
        out.append(rx.sub(lambda x: to[x.lastindex - 1], text[pos:]))
        return "".join(out)
    return sub


def outside_samples(text, fn):
    """fn applied to the text outside the shared-copy sample blocks."""
    out, pos = [], 0
    for m in SAMPLE.finditer(text):
        out += [fn(text[pos:m.start()]), m.group(0)]
        pos = m.end()
    out.append(fn(text[pos:]))
    return "".join(out)


def joined(parts, quote, sep):
    glue = ", " if sep == "," else " / "
    return glue.join(quote + p + quote for p in parts)


def folder_rewriter(old, new):
    """Rewrite paths to the SDLC and KB folders: 'sdlc/framework/...', os.path.join(ROOT, "sdlc",
    "framework"), REPO / "docs" / "knowledge-base". Words such as /sdlc or sdlc-install stay."""
    rules = []
    o, n = old.get("sdlc_dir", "sdlc"), new.get("sdlc_dir", "sdlc")
    if o != n:
        rules.append((re.compile(r"(?<![\w.-])%s/(?=%s)" % (re.escape(o), SDLC_TOP)), lambda m, n=n: n + "/"))
        rules.append((re.compile(r"([\"'])%s\1(?=\s*[,/]\s*[\"'](?:framework|kb)[\"'])" % re.escape(o)),
                      lambda m, n=n: m.group(1) + n + m.group(1)))
    o, n = old.get("kb_dir", "docs/knowledge-base"), new.get("kb_dir", "docs/knowledge-base")
    if o != n:
        rules.append((re.compile(r"(?<![\w.-])%s(?![\w-])" % re.escape(o)), lambda m, n=n: n))
        op, np_ = o.split("/"), n.split("/")
        if len(op) > 1:
            rx = r"([\"'])" + r"\1\s*([,/])\s*\1".join(re.escape(p) for p in op) + r"\1"
            rules.append((re.compile(rx), lambda m: joined(np_, m.group(1), m.group(2))))
        else:
            rules.append((re.compile(r"([\"'])%s\1(?=\s*[,/)])" % re.escape(op[0])),
                          lambda m: joined(np_, m.group(1), ",")))
    if not rules:
        return None

    def sub(text):
        for rx, fn in rules:
            text = rx.sub(fn, text)
        return text
    return lambda text: outside_samples(text, sub)


def text_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for name in files:
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            yield rel, path


def framework_files(root, values=None):
    values = values or DEFAULTS
    for top in (".devin", values["sdlc_dir"], values["kb_dir"], "AGENTS.md"):
        p = os.path.join(root, top)
        if os.path.isfile(p):
            yield top, p
        elif os.path.isdir(p):
            for rel, path in text_files(p):
                yield top + "/" + rel, path


def apply(root, old, new):
    """Swap old values for new, and the folder paths, in every framework file; returns how many
    files changed."""
    old, new = dict(DEFAULTS, **old), dict(DEFAULTS, **new)
    subs = [s for s in (rewriter(pairs(old, new)), folder_rewriter(old, new)) if s]
    changed = 0
    if not subs:
        return 0
    keep = tuple(sp(new, k) for k in KEEP)
    skip = engine_paths(new) | {VALUES_FILE}
    for rel, path in framework_files(root, new):
        if rel.startswith(keep) or rel in skip:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        out = text
        for sub in subs:
            out = sub(out)
        if out != text:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(out)
            changed += 1
    return changed


def regenerate(target, values=None):
    values = values or DEFAULTS
    for cmd in ([sp(values, c[0])] + c[1:] for c in REGENERATE):
        if not os.path.exists(os.path.join(target, cmd[0])):
            continue
        r = subprocess.run([sys.executable] + cmd, cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if r.returncode not in (0, 1) or "Traceback" in r.stderr:
            print("regenerating with %s failed:\n%s" % (cmd[0], (r.stdout + r.stderr)[-1500:]))


def installed_name(rel):
    head, base = os.path.split(rel)
    rel = os.path.join(head, STORED_FILES.get(base, base)).replace(os.sep, "/")
    for stored, name in STORED_DIRS.items():
        if rel == stored or rel.startswith(stored + "/"):
            return name + rel[len(stored):]
    return rel


def dest_for(rel, values):
    dest = installed_name(rel)
    if dest.startswith("sdlc/"):
        return sp(values, dest)
    if dest == "docs/knowledge-base" or dest.startswith("docs/knowledge-base/"):
        return values["kb_dir"] + dest[len("docs/knowledge-base"):]
    return dest


NOT_INSTALLED = ("MANUALS/",)  # read before installing; the same files are in the framework


def copy_plan(source, values):
    plan = []
    for rel, path in text_files(source):
        if rel in ENGINE_FILES or rel.startswith(NOT_INSTALLED):
            continue
        plan.append((path, sp(values, "sdlc/README.md") if rel == "README.md" else dest_for(rel, values)))
    for rel in ENGINE_FILES:
        path = os.path.join(HERE, rel)
        if os.path.exists(path):
            plan.append((path, sp(values, "sdlc/" + rel)))
    return plan


def copy_in(source, target, force, values=None):
    values = dict(DEFAULTS, **(values or {}))
    plan = copy_plan(source, values)
    clashes = [d for p, d in plan if os.path.exists(os.path.join(target, d))]
    if clashes and not force:
        print("These files already exist in %s (use --force to overwrite):" % target)
        for d in clashes[:30]:
            print("  " + d)
        if len(clashes) > 30:
            print("  ... and %d more" % (len(clashes) - 30))
        return False
    for path, dest in plan:
        out = os.path.join(target, dest)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(path, out)
    print("copied %d files into %s" % (len(plan), target))
    return True


# ---- checks

def http_check(url, bearer):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + bearer, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200, "HTTP %d" % r.status
    except urllib.error.HTTPError as e:
        return False, "HTTP %d" % e.code
    except (urllib.error.URLError, OSError) as e:
        return False, "cannot reach the host (%s)" % getattr(e, "reason", e)


def api(method, url, token, payload=None, timeout=30):
    """JSON call with a bearer token -> (status, body). The token is never printed."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8") or "{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            body = {}
        return e.code, body
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, {"error": str(getattr(e, "reason", e))}


def site(host):
    """https://<host>, or the sandbox server when SDLC_SANDBOX_URL is set."""
    return (os.environ.get("SDLC_SANDBOX_URL") or ("https://" + host)).rstrip("/")


def connectivity(target, values):
    results = []
    for label, env, url in (
        ("Jira", values["jira_token_env"], site(values["jira_host"]) + "/rest/api/2/myself"),
        ("Confluence", values["confluence_token_env"],
         site(values["wiki_host"]) + "/rest/api/space/" + values["wiki_space"]),
    ):
        bearer = os.environ.get(env)
        if not bearer:
            results.append((label, False, "secret %s is not set (add it, or run with --offline)" % env))
            continue
        ok, why = http_check(url, bearer)
        results.append((label, ok, "%s %s" % (url.split("/rest/")[0], why)))
    remote = subprocess.run(["git", "-C", target, "remote", "get-url", "origin"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if remote.returncode:
        results.append(("Repository", False, "no git remote 'origin' in %s" % target))
    else:
        try:
            r = subprocess.run(["git", "-C", target, "ls-remote", "--heads", "origin"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=30, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
            results.append(("Repository", r.returncode == 0, "origin " + ("reachable" if r.returncode == 0
                                                                          else "not reachable: " + r.stderr.strip()[-200:])))
        except subprocess.TimeoutExpired:
            results.append(("Repository", False, "origin did not answer in 30s"))
    return results


def find_bash():
    """bash for the hook checks. On Windows it is Git for Windows' bash, never the WSL launcher in System32."""
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        here = os.path.dirname(os.path.realpath(git))
        for root in (os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
            for c in (os.path.join(root, "bin", "bash.exe"), os.path.join(root, "usr", "bin", "bash.exe")):
                if os.path.isfile(c):
                    return c
    found = shutil.which("bash")
    return found if found and "system32" not in found.lower() else None


EXAMPLE_ROSTER = "sdlc/framework/tools/tests/fixtures/example-roster"
ROSTER_TESTS = ("framework unit tests", "hook tests")


def example_roster_copy(target, values):
    """A throwaway copy of the framework with the shipped example roster and gates put back.

    The framework's own tests are written against the example people; the team's roster replaces
    them at install, so those tests run in this copy."""
    fixture = os.path.join(target, sp(values, EXAMPLE_ROSTER))
    if not os.path.isdir(fixture):
        return None
    copy = os.path.join(tempfile.mkdtemp(prefix="sdlc-check-"), "repo")
    os.makedirs(copy)
    for rel in (".devin", values.get("sdlc_dir", "sdlc"), values.get("kb_dir", "docs/knowledge-base"), "AGENTS.md"):
        src = os.path.join(target, rel)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(copy, rel), symlinks=True)
        elif os.path.isfile(src):
            shutil.copyfile(src, os.path.join(copy, rel))
    for name in ("people.yaml", "approval-gates.yaml"):
        if os.path.exists(os.path.join(fixture, name)):
            shutil.copyfile(os.path.join(fixture, name), os.path.join(copy, ".devin", "rules", name))
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=sdlc-install", "-c", "user.email=sdlc-install@localhost", "commit", "-q", "-m", "check"]):
        subprocess.run(["git"] + args, cwd=copy, capture_output=True)
    return copy

CHECKS = [
    ("framework validation", [sys.executable, "sdlc/framework/tools/validate_framework.py"]),
    ("prompt lint", [sys.executable, "sdlc/kb/tools/prompts.py", "lint"]),
    ("framework unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "sdlc/framework/tools/tests", "-t", "."]),
    ("prompt kit tests", [sys.executable, "-m", "unittest", "discover", "-s", "sdlc/kb/tools/tests"]),
    ("hook tests", ["bash", ".devin/hooks/tests/run-hook-tests.sh"]),
]


def leftovers(target, values):
    """Files still holding a shared-copy (Acme) value you replaced."""
    values = dict(DEFAULTS, **values)
    sub = rewriter([(DEFAULTS[k], "") for k in SWAP_KEYS if values[k] != DEFAULTS[k]])
    hits = []
    keep = tuple(sp(values, k) for k in KEEP)
    skip = engine_paths(values) | {VALUES_FILE}
    if sub:
        for rel, path in framework_files(target, values):
            if rel.startswith(keep) or rel in skip:
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            if sub(text) != text:
                hits.append(rel)
    return hits


FRAMEWORK_PATHS = (".devin/", "sdlc/", "docs/knowledge-base/", "AGENTS.md", "SKILL.md")


def missing_paths(target, values=None):
    """Folders in the roster access rules and the KB profile that your repo does not have.

    The sample settings name the original team's folders. A developer is blocked from a code
    folder that no access rule lists, and the KB build skips a source folder that is not there.
    """
    values = dict(DEFAULTS, **(values or {}))
    ours = FRAMEWORK_PATHS + (values["sdlc_dir"] + "/", values["kb_dir"] + "/")
    found = []
    people = load_yaml(os.path.join(target, ".devin/rules/people.yaml")) or {}
    for area in (people.get("access") or {}).get("areas") or []:
        for path in area.get("paths") or []:
            if "{" in path or path.startswith(ours):
                continue
            if not os.path.exists(os.path.join(target, path.rstrip("/"))):
                found.append("people.yaml access '%s': %s" % (area.get("name"), path))
    profile = load_yaml(os.path.join(target, ".devin/rules/kb-profile.yaml")) or {}
    for path in (profile.get("app") or {}).get("source_dirs") or []:
        if not os.path.exists(os.path.join(target, str(path).rstrip("/"))):
            found.append("kb-profile.yaml app.source_dirs: %s" % path)
    return found


def check(target, values, offline):
    rows = []
    rows.append(("Python 3.8+", sys.version_info >= (3, 8), sys.version.split()[0]))
    try:
        import yaml  # noqa: F401
        rows.append(("PyYAML", True, "installed"))
    except ImportError:
        rows.append(("PyYAML", False, "missing: pip install pyyaml"))
    rows.append(("git", shutil.which("git") is not None, shutil.which("git") or "not on PATH"))
    rows.append(("git repository", os.path.isdir(os.path.join(target, ".git")), target))
    bad = problems(values)
    rows.append(("values", not bad, "; ".join(bad) or "all set (%s)" % VALUES_FILE))
    if offline:
        rows.append(("connectivity", True, "skipped (--offline)"))
    else:
        rows += connectivity(target, values)
    gone = missing_paths(target, values)
    rows.append(("folders in settings", None if gone else True,
                 ("not in your repo, edit .devin/rules/people.yaml (access) and kb-profile.yaml: "
                  + "; ".join(gone)) if gone else "all present"))
    left = leftovers(target, values)
    rows.append(("no Acme values left", not left, ", ".join(left[:5]) + (" ..." if len(left) > 5 else "") or "none"))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    for name in ("SDLC_SANDBOX", "SDLC_SANDBOX_URL"):  # the framework's tests run against their own fakes
        env.pop(name, None)
    example = None
    for label, cmd in CHECKS:
        cwd = target
        if label in ROSTER_TESTS:
            if example is None:
                example = example_roster_copy(target, values) or ""
            cwd = example or target
        cmd = [sp(values, c) for c in cmd]
        if cmd[0] == "bash":
            cmd[0] = find_bash() or "bash"
        script = cmd[cmd.index("-s") + 1] if "-s" in cmd else cmd[1]
        if not os.path.exists(os.path.join(target, script)):
            rows.append((label, False, "missing %s" % script))
            continue
        if not os.path.isabs(cmd[0]) and shutil.which(cmd[0]) is None:
            rows.append((label, False, "%s is not on PATH (on Windows, run from Git Bash or add Git's bin "
                                       "folder to PATH)" % cmd[0]))
            continue
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        tail = (r.stdout + r.stderr).strip().splitlines()[-12:]
        ok = "ok (example roster)" if cwd != target else "ok"
        rows.append((label, r.returncode == 0, ok if r.returncode == 0 else "\n      ".join([""] + tail)))
    if example:
        shutil.rmtree(os.path.dirname(example), ignore_errors=True)
    for label, ok, why in rows:
        print("%-22s %-6s %s" % (label, "warn" if ok is None else "ok" if ok else "FAILED", why))
    return all(ok is not False for _, ok, _ in rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", help="your repository (default: the repo this script is installed in)")
    ap.add_argument("--values", help="YAML file with your values (keys: %s, and settings:)" % ", ".join(DEFAULTS))
    ap.add_argument("--reconfigure", action="store_true", help="installed repo: change its values")
    ap.add_argument("--check", action="store_true", help="installed repo: only run the checks")
    ap.add_argument("--offline", action="store_true", help="skip the Jira, Confluence and repository checks")
    ap.add_argument("--force", action="store_true", help="overwrite files that already exist")
    ap.add_argument("--no-check", action="store_true", help="install without running the checks")
    ap.add_argument("--source", help="the shared copy to install from (default: the folder of this script)")
    args = ap.parse_args(argv)

    source = os.path.abspath(args.source) if args.source else HERE
    shared_copy = os.path.isdir(os.path.join(source, "dot-devin"))
    if args.target:
        target = os.path.abspath(args.target)
    elif not shared_copy and os.path.exists(os.path.join(os.path.dirname(HERE), VALUES_FILE)):
        target = os.path.dirname(HERE)
    else:
        ap.error("--target is required when running from the shared copy")
    if not os.path.isdir(target):
        ap.error("%s does not exist" % target)
    try:
        given = load_yaml(args.values) if args.values else {}
    except ImportError:
        print("PyYAML is missing: pip install pyyaml")
        return 1
    values_path = os.path.join(target, VALUES_FILE)
    stored = load_yaml(values_path) if os.path.exists(values_path) else {}
    current = normalise(stored) if stored else dict(DEFAULTS)
    settings = dict(stored.get("settings") or {})
    settings.update(given.get("settings") or {})
    interactive = not args.values and sys.stdin.isatty() and not args.check

    if args.check:
        return 0 if check(target, current, args.offline) else 1

    if not args.reconfigure:
        if not shared_copy:
            ap.error("run install.py from the shared copy (the folder with dot-devin/), or use --reconfigure")
        if not interactive and not args.values:
            ap.error("no terminal to ask on: pass --values")
        current = dict(DEFAULTS)
    new = ask(current, given, interactive, folders=not args.reconfigure)
    if args.reconfigure:
        for key in FOLDER_KEYS:
            if new[key] != current[key]:
                print("%s cannot be changed after the install (it is %s); move the folder by hand" % (key, current[key]))
                return 1
    bad = problems(new)
    if bad:
        print("Fix these values first:\n  " + "\n  ".join(bad))
        return 1
    if not args.reconfigure:
        if not copy_in(source, target, args.force, new):
            return 2
    print("updated %d files with your values" % apply(target, current, new))
    if settings:
        import install_steps
        for line in install_steps.apply_settings(target, new, settings):
            print(line)
    dump_values(values_path, new, {k: v for k, v in settings.items() if k not in NOT_STORED})
    regenerate(target, new)
    print("values saved in %s" % VALUES_FILE)
    if not args.reconfigure:
        print(("\nNext: put your people in .devin/rules/people.yaml (start from sdlc/kb/examples/acme/people.yaml),\n"
               "publish it to your roster page and sign it there (see sdlc/README.md). Until the roster is\n"
               "signed, gate sign-offs and guarded writes are blocked on purpose. Once it is signed, turn on\n"
               "the same check for commits: cp .devin/hooks/git/pre-commit .git/hooks/pre-commit\n"
               "Then register the playbooks in Devin Cloud: python3 sdlc/framework/tools/register_playbooks.py\n"
               "lists them; add --apply (with DEVIN_API_KEY set) to create them.").replace("sdlc/", new["sdlc_dir"] + "/"))
    if args.no_check:
        return 0
    print("\nChecks:")
    return 0 if check(target, new, args.offline) else 1


if __name__ == "__main__":
    sys.exit(main())
