#!/usr/bin/env python3
"""The certification gate: after the first KB is built, nothing enters it until a lead has certified it.

    python3 kb_gate.py lock    <kb> --by NAME                       certify the KB as it is now; the gate is closed from here on
    python3 kb_gate.py propose <kb> --batch NAME --from DIR [--remove REL ...]
                                                                    stage changed files (paths relative to the KB) for a lead
    python3 kb_gate.py digest  <kb> <batch>                         write <kb>/_PENDING/<batch>/DIGEST.md, riskiest files first
    python3 kb_gate.py certify <kb> <batch> --by NAME [--files REL ...] [--accept-review NOTE]
    python3 kb_gate.py reject  <kb> <batch> --by NAME --reason TEXT
    python3 kb_gate.py status  <kb>
    python3 kb_gate.py check   <kb>                                 exit 1 if a KB file is not certified (use it in CI)

How it works. `lock` records the hash of every governed KB file in <kb>/.metis/certified.yaml. After that, tools do not write
into the KB: they write the proposed files to <kb>/_PENDING/<batch>/<same relative path> (a removal is a file named
<path>.DELETE). Mētis answers questions only from the KB, so pending files are never used until certified. A lead reads the
digest and certifies; only then are the files copied in (the old copy goes to Archive/<batch>/), checked against their
sources, and their hash, the lead's name and role, and the date written to certified.yaml and .metis/CERTIFICATIONS.log.
`check` fails when a governed file is new, changed or gone without that record.

Who can certify: the people in `owners` of <kb>/.metis/kb-profile.yaml (kb_owner, app_owner, db_owner, etl_owner and every
role whose title has "lead"), plus any names under gate.certifiers. A person who gave a document does not certify pages made
from it when another lead exists (gate.allow_self_certify: true lifts this). A secret, key or social security number blocks
certification; personal-looking data (email, phone, date of birth, member or claim ids) needs --accept-review with a note.

A chat cannot prove who is typing. The record names the lead and role they gave; the enforcement is `check` in CI and the PR
approval by that same person. Keep certified.yaml under CODEOWNERS for the leads.

Left out of the gate because tools derive them from certified files and saved evidence: KNOWLEDGE-MANIFEST.yaml,
VISUALIZATION/, the link graph, ontology and impact matrix, the DB registry and drift files, ERD, the semantic model and
context/DOC_INDEX.md; and the folders _EVIDENCE, _QUESTIONS, _PENDING, _REGEN, Archive, .metis, .git.
"""
import argparse
import contextlib
import datetime
import difflib
import fnmatch
import functools
import hashlib
import os
import re
import shutil
import sys
import threading
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sensitive  # noqa: E402
import verify_kb  # noqa: E402

STATE = os.path.join(".metis", "certified.yaml")
LOG = os.path.join(".metis", "CERTIFICATIONS.log")
LOCK = os.path.join(".metis", "gate.lock")
LOCK_WAIT = 30.0    # seconds to wait for another certification to finish
LOCK_STALE = 300.0  # a lock file older than this belongs to a process that died
_HELD = threading.local()
PENDING = "_PENDING"
EXEMPT_DIRS = ("_EVIDENCE", "_QUESTIONS", "_FEEDBACK", PENDING, "_REGEN", "Archive", ".metis", ".git")
DERIVED = ("KNOWLEDGE-MANIFEST.yaml", "VISUALIZATION/*", "CROSS-LAYER/LINK_GRAPH.yaml", "CROSS-LAYER/ONTOLOGY.yaml",
           "CROSS-LAYER/IMPACT_MATRIX.yaml", "CROSS-LAYER/QA_COVERAGE.yaml", "context/DOC_INDEX.md",
           "*DB_TABLE_REGISTRY.yaml", "*DB_DRIFT.yaml", "*CATALOG_SNAPSHOT.yaml", "*/ERD.md", "*CORTEX_SEMANTIC_MODEL.yaml",
           "CROSS-LAYER/CONTRADICTIONS.yaml", "CROSS-LAYER/DUPLICATES.yaml", "CROSS-LAYER/LINK_CHECK.yaml")
FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)


class GateError(ValueError):
    pass


# ---- settings, people -------------------------------------------------------------------------
def load_yaml(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def profile(kb):
    return load_yaml(os.path.join(kb, ".metis", "kb-profile.yaml"))


def clean(name):
    return " ".join(str(name or "").split())


def real(name):
    n = clean(name)
    return bool(n) and not (n.startswith("<") and n.endswith(">"))


def certifiers(kb):
    """{lowercase name: (name, role)} for everyone who may certify."""
    prof = profile(kb)
    owners = prof.get("owners") or {}
    found = {}

    def add(name, role):
        if real(name):
            found.setdefault(clean(name).lower(), (clean(name), role))

    for key in ("kb_owner", "app_owner", "db_owner", "etl_owner"):
        add(owners.get(key), key.replace("_", " "))
    for role, name in (owners.get("roles") or {}).items():
        if "lead" in str(role).lower():
            add(name, str(role))
    for name in (prof.get("gate") or {}).get("certifiers") or []:
        add(name, "certifier")
    return found


def who(kb, name):
    people = certifiers(kb)
    if not people:
        raise GateError("no lead is named in %s (owners.kb_owner and the lead roles); name them first" % os.path.join(".metis", "kb-profile.yaml"))
    hit = people.get(clean(name).lower())
    if not hit:
        raise GateError("%s is not a lead named in the KB profile (leads: %s)" % (clean(name) or "(no name)", ", ".join(v[0] for v in people.values())))
    return hit


# ---- teams: who owns which files --------------------------------------------------------------
UNASSIGNED = "(no owning team)"


def teams(kb):
    """Teams from gate.teams: [{name, owns: [globs], approvers: [names]}], in the order the profile lists them."""
    out = []
    for t in (profile(kb).get("gate") or {}).get("teams") or []:
        if isinstance(t, dict) and real(t.get("name")):
            out.append({"name": clean(t["name"]), "owns": [str(g).strip() for g in (t.get("owns") or []) if str(g).strip()],
                        "approvers": [clean(a) for a in (t.get("approvers") or []) if real(a)]})
    return out


def owns(glob, rel):
    g = glob.strip().strip("/")
    return fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel, g + "/*")


def team_of(kb, rel):
    """The first team whose globs match this KB-relative path, or None."""
    for t in teams(kb):
        if any(owns(g, rel) for g in t["owns"]):
            return t
    return None


def pool_for(kb, rel):
    """(team name or None, {lowercase name: (name, role)}) for who may certify this file: the leads, plus the owning team's approvers."""
    t = team_of(kb, rel)
    pool = dict(certifiers(kb))
    for a in (t["approvers"] if t else []):
        pool.setdefault(a.lower(), (a, "%s approver" % t["name"]))
    return (t["name"] if t else None), pool


def who_any(kb, name):
    """A lead, or an approver of any team (certify checks the person against each file's owning team)."""
    key = clean(name).lower()
    for t in teams(kb):
        for a in t["approvers"]:
            if a.lower() == key:
                lead = certifiers(kb).get(key)
                return lead or (a, "%s approver" % t["name"])
    return who(kb, name)


# ---- state ------------------------------------------------------------------------------------
@contextlib.contextmanager
def gate_lock(kb, wait=None, stale=None):
    """One writer at a time across processes: the UI server, a command line run and CI can all certify the same KB. Re-entrant in
    one thread. The lock is a file made with O_EXCL (works the same on Windows and Linux); one older than `stale` seconds is taken
    to be left by a dead process and removed."""
    wait, stale = LOCK_WAIT if wait is None else wait, LOCK_STALE if stale is None else stale
    path = os.path.join(kb, LOCK)
    depth = getattr(_HELD, "depth", None)
    if depth is None:
        depth = _HELD.depth = {}
    if depth.get(path):
        depth[path] += 1
        try:
            yield
        finally:
            depth[path] -= 1
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.monotonic() + wait
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, ("pid %d\n" % os.getpid()).encode("ascii"))
            os.close(fd)
            break
        except (FileExistsError, PermissionError):  # Windows says "access denied" for a lock file that is being deleted
            try:
                if time.time() - os.path.getmtime(path) > stale:
                    os.remove(path)
                    continue
            except OSError:
                continue  # it was released between the two calls
            if time.monotonic() > deadline:
                raise GateError("another certification is in progress on this KB (%s); try again in a minute" % LOCK)
            time.sleep(0.05)
    depth[path] = 1
    try:
        yield
    finally:
        depth.pop(path, None)
        try:
            os.remove(path)
        except OSError:
            pass


def locked(fn):
    """Run a gate function that changes certified.yaml or the batches under gate_lock (its first argument is the KB folder)."""
    @functools.wraps(fn)
    def run(kb, *a, **kw):
        with gate_lock(kb):
            return fn(kb, *a, **kw)
    return run


def load_state(kb):
    return load_yaml(os.path.join(kb, STATE))


def save_state(kb, st):
    """Write certified.yaml in one step (temp file, then rename) so a reader never sees half of it."""
    p = os.path.join(kb, STATE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.%d.%d.tmp" % (p, os.getpid(), threading.get_ident())
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# Written by kb_gate.py. Each file's hash is what a lead certified. Keep this file under CODEOWNERS.\n")
            yaml.safe_dump(st, fh, sort_keys=True, allow_unicode=True, width=120)
        for attempt in range(40):  # Windows refuses the rename while a reader has certified.yaml open; the reader is quick
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.025)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def is_locked(kb):
    return bool(load_state(kb).get("locked"))


def log(kb, *cols):
    p = os.path.join(kb, LOG)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join([datetime.datetime.now().strftime("%Y-%m-%d %H:%M")] + [str(c).replace("\t", " ").replace("\n", " ") for c in cols]) + "\n")


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def sha_file(path):
    with open(path, "rb") as fh:
        return sha(fh.read())


def derived(rel):
    return any(fnmatch.fnmatch(rel, p) for p in DERIVED)


def governed(kb):
    """Relative paths of the files the gate covers."""
    out = []
    for d, dirs, fs in os.walk(kb):
        dirs[:] = sorted(x for x in dirs if x not in EXEMPT_DIRS)
        for f in sorted(fs):
            rel = os.path.relpath(os.path.join(d, f), kb).replace(os.sep, "/")
            if not derived(rel):
                out.append(rel)
    return out


# ---- lock -------------------------------------------------------------------------------------
@locked
def lock(kb, by):
    name, role = who(kb, by)
    if is_locked(kb):
        raise GateError("the gate is already closed")
    rep = verify_kb.Checker(kb).run()
    if rep["problems"]:
        raise GateError("the KB has %d source problems (first: %s:%s %s); fix them before locking" % (
            len(rep["problems"]), rep["problems"][0]["file"], rep["problems"][0]["line"], rep["problems"][0]["problem"]))
    today = datetime.date.today().isoformat()
    files = {rel: {"sha256": sha_file(os.path.join(kb, rel)), "by": name, "role": role, "on": today, "batch": "initial"}
             for rel in governed(kb)}
    save_state(kb, {"locked": True, "locked_by": name, "locked_on": today, "files": files})
    log(kb, "lock", name, role, "initial", "%d files" % len(files))
    return len(files)


@locked
def record(kb, rel, by, batch, note=None, accepted=None):
    """Write one certification (used by certify and by kb_promote)."""
    name, role = who(kb, by)
    st = load_state(kb)
    st.setdefault("files", {})[rel] = {"sha256": sha_file(os.path.join(kb, rel)), "by": name, "role": role,
                                       "on": datetime.date.today().isoformat(), "batch": batch}
    if accepted:
        st["files"][rel]["accepted_review"] = accepted
    if note:
        st["files"][rel]["note"] = note
    save_state(kb, st)
    log(kb, "certify", name, role, batch, rel)


# ---- pending ----------------------------------------------------------------------------------
def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "change"


def pending_dir(kb, batch=None):
    return os.path.join(kb, PENDING, batch) if batch else os.path.join(kb, PENDING)


def new_batch(kb, name):
    base = "%s-%s" % (datetime.date.today().isoformat(), slug(name))
    used = set()
    if os.path.isdir(pending_dir(kb)):
        used |= set(os.listdir(pending_dir(kb)))
    used |= {f.get("batch") for f in (load_state(kb).get("files") or {}).values()}
    batch, n = base, 1
    while batch in used:
        n += 1
        batch = "%s-%d" % (base, n)
    return batch


def stage_text(kb, batch, rel, text):
    dst = os.path.join(pending_dir(kb, batch), rel)
    if os.path.normpath(dst).startswith(os.path.normpath(pending_dir(kb, batch)) + os.sep) is False:
        raise GateError("path leaves the batch folder: %s" % rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return dst


def propose(kb, batch, src_dir=None, remove=()):
    if not is_locked(kb):
        raise GateError("the gate is not closed yet; write to the KB directly, then run lock")
    n = 0
    if src_dir:
        for d, _, fs in os.walk(src_dir):
            for f in fs:
                rel = os.path.relpath(os.path.join(d, f), src_dir).replace(os.sep, "/")
                if derived(rel) or rel.split("/")[0] in EXEMPT_DIRS:
                    continue
                dst = os.path.join(pending_dir(kb, batch), rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(d, f), dst)
                n += 1
    for rel in remove:
        if not os.path.isfile(os.path.join(kb, rel)):
            raise GateError("cannot remove %s: not in the KB" % rel)
        stage_text(kb, batch, rel + ".DELETE", "")
        n += 1
    if not n:
        raise GateError("nothing to propose")
    return n


def pending_files(kb, batch):
    base = pending_dir(kb, batch)
    out = []
    for d, _, fs in os.walk(base):
        for f in sorted(fs):
            rel = os.path.relpath(os.path.join(d, f), base).replace(os.sep, "/")
            if rel != "DIGEST.md":
                out.append(rel)
    return sorted(out)


def batches(kb):
    base = pending_dir(kb)
    if not os.path.isdir(base):
        return []
    return sorted(b for b in os.listdir(base) if os.path.isdir(os.path.join(base, b)) and not b.startswith("_"))


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n")


def front(text):
    m = FRONT.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[m.end():]


def source_problems(kb, rel, text, checker=None):
    checker = checker or verify_kb.Checker(kb)
    found, counts = [], {"tags": 0, "fact_lines": 0}
    if rel.endswith(".md"):
        checker.check_text(rel, text, found, counts)
    elif rel.endswith((".yaml", ".yml")):
        checker.check_yaml(rel, text, found, counts)
    return found, counts


def findings(rel, text):
    _, body = front(text)
    start = text.count("\n") - body.count("\n")
    out = []
    for f in sensitive.scan(body):
        line = body.splitlines()[f["line"] - 1] if f["line"] <= len(body.splitlines()) else ""
        if f["kind"] == "email address" and re.search(r"given by", line, re.I):
            continue
        f = dict(f, line=f["line"] + start)
        out.append(f)
    return out


def analyse(kb, batch):
    """One record per pending file, riskiest first."""
    checker = verify_kb.Checker(kb)
    rows = []
    for rel in pending_files(kb, batch):
        p = os.path.join(pending_dir(kb, batch), rel)
        if rel.endswith(".DELETE"):
            target = rel[:-7]
            rows.append({"file": target, "action": "remove", "risk": 20, "lines_added": 0, "lines_removed": 0,
                         "problems": [], "findings": [], "documents": [], "given_by": []})
            continue
        text = read_text(p)
        live = os.path.join(kb, rel)
        old = read_text(live) if os.path.isfile(live) else None
        added = removed = 0
        if old is not None:
            for ln in difflib.unified_diff(old.splitlines(), text.splitlines(), lineterm="", n=0):
                if ln.startswith("+") and not ln.startswith("+++"):
                    added += 1
                elif ln.startswith("-") and not ln.startswith("---"):
                    removed += 1
        else:
            added = len(text.splitlines())
        probs, counts = source_problems(kb, rel, text, checker)
        fnd = findings(rel, text)
        meta, _ = front(text)
        docs = [d for d in (meta.get("documents") or []) if isinstance(d, dict)]
        risk = (100 * sum(1 for f in fnd if f["level"] == sensitive.BLOCK) + 10 * sum(1 for f in fnd if f["level"] == sensitive.REVIEW)
                + 5 * len(probs) + (3 if old is not None else 1) + min(removed, 20))
        rows.append({"file": rel, "action": "change" if old is not None else "new", "risk": risk, "lines_added": added,
                     "lines_removed": removed, "tags": counts["tags"], "problems": ["%d: %s" % (n, why) for _, n, why in probs],
                     "findings": fnd, "documents": [d.get("name") for d in docs],
                     "given_by": sorted({str(d.get("given_by")) for d in docs if d.get("given_by")})})
    return sorted(rows, key=lambda r: (-r["risk"], r["file"]))


def digest(kb, batch):
    rows = analyse(kb, batch)
    if not rows:
        raise GateError("batch %s has no files" % batch)
    L = ["# Certification digest: %s" % batch, "",
         "Files are listed riskiest first. Read the top of the list closely; the rest is lower risk. "
         "Certify with the lead's name; nothing below is in the KB until then.", "",
         "- Files: %d (%d new, %d changed, %d removed)" % (len(rows), sum(r["action"] == "new" for r in rows),
                                                          sum(r["action"] == "change" for r in rows), sum(r["action"] == "remove" for r in rows)),
         "- Blocked by a secret or id number: %d" % sum(any(f["level"] == sensitive.BLOCK for f in r["findings"]) for r in rows),
         "- Needing a decision on personal-looking data: %d" % sum(any(f["level"] == sensitive.REVIEW for f in r["findings"]) for r in rows),
         "- With source problems: %d" % sum(bool(r["problems"]) for r in rows), "",
         "| Order | File | What | Lines | Risk | Why it ranks here |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        why = []
        why += ["%s (%s)" % (f["kind"], f["level"]) for f in r["findings"][:3]]
        why += ["%d source problems" % len(r["problems"])] if r["problems"] else []
        if r["action"] == "remove":
            why.append("removes a certified file")
        L.append("| %d | %s | %s | +%d -%d | %d | %s |" % (i, r["file"], r["action"], r["lines_added"], r["lines_removed"], r["risk"],
                                                          "; ".join(why) or "none found"))
    L += ["", "## Where each file came from", ""]
    for r in rows:
        if r["documents"] or r["given_by"]:
            L.append("- %s: documents %s; given by %s" % (r["file"], ", ".join(map(str, r["documents"])) or "none",
                                                         ", ".join(r["given_by"]) or "unknown"))
    detail = [r for r in rows if r["problems"] or r["findings"]]
    if detail:
        L += ["", "## Findings", ""]
        for r in detail:
            for f in r["findings"]:
                L.append("- %s line %d: %s (%s), starting %s" % (r["file"], f["line"], f["kind"], f["level"], f["sample"]))
            for p in r["problems"][:10]:
                L.append("- %s line %s" % (r["file"], p))
    path = os.path.join(pending_dir(kb, batch), "DIGEST.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return path, rows


# ---- certify, reject --------------------------------------------------------------------------
@locked
def certify(kb, batch, by, files=None, accept_review=None):
    if not is_locked(kb):
        raise GateError("the gate is not closed; nothing to certify")
    name, role = who_any(kb, by)
    rows = analyse(kb, batch)
    if files:
        want = {f.strip("/") for f in files}
        missing = want - {r["file"] for r in rows}
        if missing:
            raise GateError("not in batch %s: %s" % (batch, ", ".join(sorted(missing))))
        rows = [r for r in rows if r["file"] in want]
    if not rows:
        raise GateError("batch %s has no files" % batch)
    reasons = []
    gate_cfg = profile(kb).get("gate") or {}
    for r in rows:
        team, pool = pool_for(kb, r["file"])
        if name.lower() not in pool:
            reasons.append("%s: %s does not approve for %s; it needs %s" % (
                r["file"], name, team or "the leads", ", ".join(sorted(v[0] for v in pool.values()))))
            continue
        others = [k for k, v in pool.items() if v[0] != name]
        if r["action"] != "remove" and not gate_cfg.get("allow_self_certify") and others and name in r["given_by"]:
            reasons.append("%s: %s gave the document; another lead must certify it" % (r["file"], name))
        for f in r["findings"]:
            if f["level"] == sensitive.BLOCK:
                reasons.append("%s:%d: %s must come out before this can be certified" % (r["file"], f["line"], f["kind"]))
            elif not (accept_review or "").strip():
                reasons.append("%s:%d: %s; remove it, or certify with --accept-review and say why it may stay" % (r["file"], f["line"], f["kind"]))
        reasons += ["%s:%s" % (r["file"], p) for p in r["problems"]]
    if reasons:
        raise GateError("not certified:\n  " + "\n  ".join(reasons[:40]))
    # apply, check the result against its sources, and undo everything if it does not hold
    undo, applied = [], []
    for r in rows:
        dst = os.path.join(kb, r["file"])
        old = read_bytes(dst) if os.path.isfile(dst) else None
        undo.append((dst, old))
        if r["action"] == "remove":
            os.remove(dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(pending_dir(kb, batch), r["file"]), dst)
        applied.append(r)
    chk, bad = verify_kb.Checker(kb), []
    for r in applied:
        if r["action"] != "remove":
            probs, _ = source_problems(kb, r["file"], read_text(os.path.join(kb, r["file"])), chk)
            bad += ["%s:%d: %s" % (r["file"], n, why) for _, n, why in probs]
    if bad:
        for dst, old in undo:
            if old is None:
                if os.path.exists(dst):
                    os.remove(dst)
            else:
                with open(dst, "wb") as fh:
                    fh.write(old)
        raise GateError("not certified; the files do not hold against their sources once in the KB:\n  " + "\n  ".join(bad[:40]))
    st = load_state(kb)
    for (dst, old), r in zip(undo, applied):
        if old is not None:
            keep = os.path.join(kb, "Archive", batch, r["file"])
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            with open(keep, "wb") as fh:
                fh.write(old)
        if r["action"] == "remove":
            st.get("files", {}).pop(r["file"], None)
            os.remove(os.path.join(pending_dir(kb, batch), r["file"] + ".DELETE"))
            log(kb, "certify-removal", name, role, batch, r["file"])
            continue
        entry = {"sha256": sha_file(dst), "by": name, "role": role, "on": datetime.date.today().isoformat(), "batch": batch}
        if r["findings"]:
            entry["accepted_review"] = sorted({f["kind"] for f in r["findings"]})
            entry["note"] = accept_review.strip()
        st.setdefault("files", {})[r["file"]] = entry
        os.remove(os.path.join(pending_dir(kb, batch), r["file"]))
        log(kb, "certify", name, role, batch, r["file"], ("accepted: " + accept_review.strip()) if r["findings"] else "")
    save_state(kb, st)
    if any(front(read_text(os.path.join(kb, r["file"])))[0].get("generated_by") == "doc_kb.py" for r in applied if r["action"] != "remove"):
        import doc_kb  # imported here because doc_kb imports this module
        doc_kb.build_index(kb)
    left = pending_files(kb, batch)
    if not left:
        shutil.rmtree(pending_dir(kb, batch), ignore_errors=True)
    return len(applied)


@locked
def reject(kb, batch, by, reason):
    name, role = who(kb, by)
    if not (reason or "").strip():
        raise GateError("say why it was rejected")
    if not os.path.isdir(pending_dir(kb, batch)):
        raise GateError("no such batch: %s" % batch)
    files = pending_files(kb, batch)
    shutil.rmtree(pending_dir(kb, batch), ignore_errors=True)
    log(kb, "reject", name, role, batch, "%d files" % len(files), reason.strip())
    return len(files)


# ---- check, status ----------------------------------------------------------------------------
def check(kb):
    st = load_state(kb)
    if not st.get("locked"):
        return [], False
    certified = st.get("files") or {}
    problems = []
    present = set(governed(kb))
    for rel in sorted(present):
        c = certified.get(rel)
        if not c:
            problems.append("%s: not certified (new)" % rel)
        elif sha_file(os.path.join(kb, rel)) != c.get("sha256"):
            problems.append("%s: changed since %s certified it on %s" % (rel, c.get("by"), c.get("on")))
    for rel in sorted(set(certified) - present):
        problems.append("%s: certified but gone; a removal needs certification too" % rel)
    return problems, True


def status(kb):
    st = load_state(kb)
    out = {"locked": bool(st.get("locked")), "certified_files": len(st.get("files") or {}), "batches": []}
    for b in batches(kb):
        out["batches"].append({"batch": b, "files": len(pending_files(kb, b)), "digest": os.path.isfile(os.path.join(pending_dir(kb, b), "DIGEST.md"))})
    out["problems"], _ = check(kb)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("lock"); a.add_argument("kb"); a.add_argument("--by", required=True)
    a = sub.add_parser("propose"); a.add_argument("kb"); a.add_argument("--batch", required=True)
    a.add_argument("--from", dest="src"); a.add_argument("--remove", nargs="*", default=[])
    a = sub.add_parser("digest"); a.add_argument("kb"); a.add_argument("batch")
    a = sub.add_parser("certify"); a.add_argument("kb"); a.add_argument("batch"); a.add_argument("--by", required=True)
    a.add_argument("--files", nargs="*"); a.add_argument("--accept-review")
    a = sub.add_parser("reject"); a.add_argument("kb"); a.add_argument("batch"); a.add_argument("--by", required=True); a.add_argument("--reason", required=True)
    a = sub.add_parser("status"); a.add_argument("kb")
    a = sub.add_parser("check"); a.add_argument("kb")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "lock":
            print("gate closed: %d files certified by %s" % (lock(kb, args.by), clean(args.by)))
        elif args.cmd == "propose":
            batch = new_batch(kb, args.batch)
            n = propose(kb, batch, args.src, args.remove)
            path, _ = digest(kb, batch)
            print("batch %s: %d files staged; digest %s" % (batch, n, path))
        elif args.cmd == "digest":
            print("digest %s" % digest(kb, args.batch)[0])
        elif args.cmd == "certify":
            print("certified %d files in %s by %s" % (certify(kb, args.batch, args.by, args.files, args.accept_review), args.batch, clean(args.by)))
        elif args.cmd == "reject":
            print("rejected %d files in %s" % (reject(kb, args.batch, args.by, args.reason), args.batch))
        elif args.cmd == "status":
            s = status(kb)
            print("gate %s; %d certified files; %d pending batches" % ("closed" if s["locked"] else "open", s["certified_files"], len(s["batches"])))
            for b in s["batches"]:
                print("  %s: %d files%s" % (b["batch"], b["files"], "" if b["digest"] else " (no digest yet)"))
            for p in s["problems"]:
                print("  PROBLEM " + p)
        else:
            problems, locked = check(kb)
            for p in problems:
                print(p)
            print("gate %s: %d uncertified changes" % ("closed" if locked else "open (not locked)", len(problems)))
            return 1 if problems else 0
    except GateError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
