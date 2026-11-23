#!/usr/bin/env python3
"""Ingest procedural context (how to build, test, run, deploy) as staged KB pages of ordered steps.

    python3 recipes_ingest.py scan  <kb> --repo NAME [--path SUBFOLDER]
    python3 recipes_ingest.py stage <kb> --repo NAME [--path SUBFOLDER] [--dry-run]

`--repo` is a repo named under sources.repos in <kb>/.metis/kb-profile.yaml. Read, and nothing else is touched:
    runbooks      markdown under runbooks/, docs/runbooks/, playbooks/, ops/, or named *runbook* / *playbook*: numbered steps and fenced
                  command blocks under each heading
    contributing  CONTRIBUTING.md and README sections with commands (build, test, run, install, deploy, setup)
    make          Makefile targets: each target's recipe lines are the steps
    npm           package.json "scripts": one step per script
    ci            pipeline files: .gitlab-ci.yml, bitbucket-pipelines.yml, azure-pipelines.yml, Jenkinsfile, .github/workflows/*.yml,
                  .circleci/config.yml: each job's script lines in order
Everything else in the repo is ignored.

A page is written per source file to context/procedures/<slug>.md (folder from <kb>/.metis/doc-categories.yaml, else
templates/doc-categories.decisions.yaml). Each step is a numbered line with [E: <repo>/<path>:<line> "quote"]; the command is
shown verbatim in backticks, and the quote is taken from the same source line. A step that contains rm, drop, delete, truncate,
format or prod is flagged `needs-confirm`: a person must confirm it before anyone runs it. A step is documentation, never
something Metis runs. Lines that contain a password, key or token are left out and listed.

Staging, the "never replace a page this tool did not make" rule and the _PENDING batch for a locked KB are the same as in adr_ingest.py.
"""
import argparse
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adr_ingest as A  # noqa: E402
import kb_gate  # noqa: E402
import sensitive  # noqa: E402

GENERATOR = "recipes_ingest.py"
RUNBOOK_DIR = re.compile(r"(^|/)(runbooks?|playbooks?|ops|operations|procedures)(/|$)", re.I)
RUNBOOK_NAME = re.compile(r"runbook|playbook|how-?to|deploy|release", re.I)
CI_FILES = {".gitlab-ci.yml", "bitbucket-pipelines.yml", "azure-pipelines.yml", "azure-pipelines.yaml", "Jenkinsfile", "buildspec.yml",
            "cloudbuild.yaml", ".travis.yml"}
CI_DIRS = (".github/workflows/", ".circleci/")
COMMAND_HEADS = re.compile(r"build|test|run|install|setup|set up|deploy|start|getting started|usage|develop|release|migrat|lint|"
                           r"quick ?start|local|docker|compile|package", re.I)
SHELL_START = re.compile(r"^(\$\s*)?(sudo\s+)?(make|npm|npx|yarn|pnpm|pip3?|python3?|poetry|mvn|mvnw|\./mvnw|gradle|\./gradlew|docker|docker-compose|"
                         r"kubectl|helm|terraform|ansible|git|cd|curl|bash|sh|\./[\w./-]+|flyway|liquibase|dbt|aws|az|gcloud|go|cargo|dotnet|"
                         r"java|node|psql|mysql|sqlcmd|export|source|cp|mv|mkdir|chmod|rm|ls|cat|echo|pytest|tox|nox|bundle|rake|php|composer)\b")
RISKY = re.compile(r"(?<![\w-])(rm|rmdir|del|drop|delete|truncate|format|destroy|purge|wipe|prod|production)(?![\w-])", re.I)
FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+-]*)")
STEP = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)\s*$")
BULLET = re.compile(r"^\s*[-*+]\s+(.*\S)\s*$")
MAX_STEPS = 80
MAX_FILES = 2000
SKIP_SECTIONS = re.compile(r"licen[sc]e|acknowledg|credits|code of conduct|table of contents|contributors|badges?", re.I)


def needs_confirm(text):
    return bool(RISKY.search(text))


# ---- source files -> procedures -------------------------------------------------------------------
def md_procedures(rows):
    """[{title, ref, text, steps: [(ref, raw, command or None)]}] from markdown rows (ref, text)."""
    out, cur, fence = [], None, None
    for ref, t in rows:
        f = FENCE.match(t)
        if f:
            fence = None if fence is not None else (f.group(2) or "").lower()
            continue
        if fence is not None:
            if cur is not None and t.strip() and not t.strip().startswith("#") and fence in ("", "sh", "bash", "shell", "console", "zsh", "cmd", "powershell", "ps1", "bat", "text", "yaml", "yml", "sql"):
                cur["steps"].append((ref, t.rstrip(), t.strip().lstrip("$ ").strip()))
            continue
        h = A.HEAD.match(t)
        if h:
            cur = {"title": A.squash(h.group(2).strip("*_ ")), "ref": ref, "text": t, "steps": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = STEP.match(t)
        if m:
            body = m.group(2)
            cmd = re.search(r"`([^`]+)`", body)
            cur["steps"].append((ref, t, cmd.group(1) if cmd and SHELL_START.match(cmd.group(1).strip()) else None))
        elif BULLET.match(t) and re.search(r"`[^`]+`", t) and RUNBOOK_HEAD_OK(cur["title"]):
            cmd = re.search(r"`([^`]+)`", t)
            cur["steps"].append((ref, t, cmd.group(1) if SHELL_START.match(cmd.group(1).strip()) else None))
    return [p for p in out if p["steps"]]


def RUNBOOK_HEAD_OK(title):
    return bool(COMMAND_HEADS.search(title)) or bool(RUNBOOK_NAME.search(title))


def read_section_filter(rows, kind):
    """Drop sections that are not procedures. A runbook keeps every section that has steps; a README or CONTRIBUTING keeps those
    whose heading is about commands, or that hold a fenced command."""
    procs = md_procedures(rows)
    if kind == "runbook":
        return procs
    keep = []
    for p in procs:
        if SKIP_SECTIONS.search(p["title"]):
            continue
        has_cmd = any(c for _, _, c in p["steps"])
        if COMMAND_HEADS.search(p["title"]) or has_cmd:
            keep.append(p)
    return keep


def make_procedures(rows):
    out, cur = [], None
    for ref, t in rows:
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?!=)\s*([^=#]*)", t)
        if m and not t.startswith(("\t", " ")) and not m.group(1).startswith((".", "$")):
            cur = {"title": "make %s" % m.group(1), "ref": ref, "text": t, "steps": []}
            deps = m.group(2).split("#")[0].split()
            if deps:
                cur["steps"].append((ref, t, "make %s" % " ".join(deps)))
            out.append(cur)
        elif cur is not None and t.startswith("\t") and t.strip() and not t.strip().startswith("#"):
            cur["steps"].append((ref, t, t.strip().lstrip("@-+").strip()))
        elif cur is not None and t.strip() and not t.startswith(("\t", " ", "#")):
            cur = None
    return [p for p in out if p["steps"]]


def npm_procedures(text, rows):
    try:
        scripts = (json.loads(text).get("scripts") or {})
    except ValueError:
        return []
    steps = []
    for name, cmd in scripts.items():
        if not isinstance(cmd, str):
            continue
        for ref, t in rows:
            if re.search(r'"%s"\s*:' % re.escape(name), t) and cmd.split("\\")[0][:20] in t.replace("\\\\", "\\"):
                steps.append((ref, t, "npm run %s" % name if name not in ("test", "start") else "npm %s" % name))
                break
    return [{"title": "npm scripts", "ref": steps[0][0], "text": steps[0][1], "steps": steps}] if steps else []


def ci_procedures(rows):
    """Job script lines of a CI yaml, in order. Reads the file as text (no YAML anchors or includes are resolved)."""
    out, job, in_script, base = [], None, False, 0
    for ref, t in rows:
        if not t.strip() or t.strip().startswith("#"):
            continue
        indent = len(t) - len(t.lstrip(" "))
        m = re.match(r"^(\s*)([\w.-]+):\s*(.*)$", t)
        dash = re.match(r"^(\s*)-\s+(?:name|run|script):?\s*(.*)$", t)
        if indent == 0 and m and not m.group(3).strip().startswith(("[", "{")) and m.group(2) not in ("stages", "variables", "image", "on", "env", "include", "default", "cache", "before_script", "after_script"):
            job = {"title": "job %s" % m.group(2), "ref": ref, "text": t, "steps": []}
            out.append(job)
            in_script = False
            continue
        if job is None:
            continue
        key = re.match(r"^(\s*)(script|run|commands|steps|before_script|after_script)\s*:\s*(.*)$", t)
        if key:
            in_script, base = True, len(key.group(1))
            rest = key.group(3).strip()
            if rest and not rest.startswith(("|", ">")):
                job["steps"].append((ref, t, rest.strip("'\"")))
            continue
        run = re.match(r"^\s*-?\s*run:\s*(.+)$", t)
        if run and not run.group(1).strip().startswith(("|", ">")):
            job["steps"].append((ref, t, run.group(1).strip().strip("'\"")))
            continue
        if in_script:
            if indent <= base and not t.lstrip().startswith("-"):
                in_script = False
                continue
            item = re.match(r"^\s*-\s+(.*\S)\s*$", t)
            raw = item.group(1) if item else t.strip()
            if dash and dash.group(2) and not re.match(r"^(run|script)", raw):
                pass
            if raw and not re.match(r"^(name|uses|with|env|if|id|shell|working-directory)\s*:", raw):
                job["steps"].append((ref, t, raw.strip("'\"")))
    return [j for j in out if j["steps"]]


def jenkins_procedures(rows):
    out = []
    steps = []
    for ref, t in rows:
        m = re.search(r"\b(sh|bat|powershell)\s*(?:script:\s*)?['\"]([^'\"]+)['\"]", t)
        if m:
            steps.append((ref, t, m.group(2)))
    if steps:
        out.append({"title": "Jenkins pipeline", "ref": steps[0][0], "text": steps[0][1], "steps": steps})
    return out


def kind_of(rel):
    base = os.path.basename(rel)
    low = rel.lower()
    if base in ("Makefile", "makefile", "GNUmakefile") or low.endswith(".mk"):
        return "make"
    if base == "package.json":
        return "npm"
    if base == "Jenkinsfile":
        return "jenkins"
    if base in CI_FILES or any(low.startswith(d) or ("/" + d) in "/" + low for d in CI_DIRS) and low.endswith((".yml", ".yaml")):
        return "ci"
    if low.endswith((".md", ".markdown", ".rst", ".txt")):
        if RUNBOOK_DIR.search(low) or RUNBOOK_NAME.search(base):
            return "runbook"
        if re.match(r"^(contributing|readme|development|dev|install|setup|building|hacking)[^/]*$", base, re.I):
            return "contributing"
    return None


def plan_source(rel, rows, text):
    k = kind_of(rel)
    if k == "make":
        procs = make_procedures(rows)
    elif k == "npm":
        procs = npm_procedures(text, rows)
    elif k == "ci":
        procs = ci_procedures(rows)
    elif k == "jenkins":
        procs = jenkins_procedures(rows)
    elif k in ("runbook", "contributing"):
        procs = read_section_filter(rows, k)
    else:
        return None, []
    return k, procs


# ---- building a page -----------------------------------------------------------------------------
def build_page(repo, rel, kind, procs):
    src = A.Source("repo", rel, [], repo=repo, rel=rel)
    omitted, sections, flagged = [], [], 0
    seen_steps = 0
    for p in procs:
        steps = []
        for ref, raw, cmd in p["steps"]:
            if seen_steps >= MAX_STEPS:
                break
            blocked = sorted({k for lvl, k, _ in sensitive.scan_line(raw) if lvl == sensitive.BLOCK})
            if blocked:
                omitted.append({"ref": ref, "kinds": blocked})
                continue
            tag = src.tag(ref, raw, around=cmd if cmd and A.clean_quote(raw, around=cmd) else None)
            if not tag:
                continue
            body = A.bullet_text(raw) or ""
            shown = A.bare_safe(cmd) if cmd else None
            if shown and "`" in shown:
                shown = None
            confirm = needs_confirm("%s %s" % (cmd or "", raw))
            flagged += 1 if confirm else 0
            steps.append({"text": ("`%s`" % shown) if shown else body, "context": body if shown and body and body != shown and shown not in body else None,
                          "confirm": confirm, "tag": tag})
            seen_steps += 1
        if steps:
            sections.append({"title": p["title"], "steps": steps})
    return {"rel": rel, "kind": kind, "sections": sections, "omitted": omitted, "flagged": flagged,
            "steps": sum(len(s["steps"]) for s in sections), "src": src}


def title_for(page):
    names = {"make": "Makefile targets", "npm": "npm scripts", "ci": "CI pipeline", "jenkins": "Jenkins pipeline",
             "runbook": "Runbook", "contributing": "How to build and run"}
    stem = os.path.splitext(os.path.basename(page["rel"]))[0]
    where = page["rel"] if page["kind"] in ("make", "npm", "ci", "jenkins") else stem.replace("-", " ").replace("_", " ")
    return "%s: %s" % (names[page["kind"]], where)


def render(page, category, today=None):
    import datetime
    title = title_for(page)
    front = {"title": title, "category": category, "generated_by": GENERATOR, "updated": today or datetime.date.today().isoformat(),
             "format": page["kind"], "source": "%s/%s" % (page["src"].repo, page["rel"]), "needs_confirm_steps": page["flagged"]}
    L = ["# %s" % title, "",
         "> Steps are listed as the source file gives them, in order. They are documentation: Metis does not run them. "
         "A step flagged needs-confirm (it contains rm, drop, delete, truncate, format or prod) must be confirmed by a person first.", ""]
    for s in page["sections"]:
        L += ["## %s" % A.bare_safe(s["title"]), ""]
        for i, st in enumerate(s["steps"], 1):
            flag = " **needs-confirm**" if st["confirm"] else ""
            L.append("%d. %s%s %s" % (i, st["text"], flag, st["tag"]))
            if st["context"]:
                L.append("   - Source line: %s %s" % (st["context"], st["tag"]))
        L.append("")
    return "---\n%s---\n\n%s\n" % (yaml.safe_dump(front, sort_keys=False, allow_unicode=True), "\n".join(L).rstrip("\n"))


# ---- reading a repo ---------------------------------------------------------------------------
def candidate_files(base, sub=None):
    top = os.path.normpath(os.path.join(base, sub)) if sub else base
    if not (top == base or top.startswith(base + os.sep)) or not os.path.isdir(top):
        raise ValueError("folder not found inside the repo: %s" % sub)
    n = 0
    for d, dirs, files in os.walk(top):
        dirs[:] = sorted(x for x in dirs if x not in A.SKIP_DIRS and (not x.startswith(".") or x in (".github", ".circleci")))
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(d, f), base).replace(os.sep, "/")
            if kind_of(rel):
                n += 1
                if n > MAX_FILES:
                    return
                yield rel


def plan_repo(kb, repo, sub=None):
    base, pages, notes = A.repo_base(kb, repo), [], []
    for rel in candidate_files(base, sub):
        full = os.path.join(base, *rel.split("/"))
        if os.path.getsize(full) > A.MAX_BYTES:
            continue
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        rows = [(i, t) for i, t in enumerate(text.splitlines(), 1)]
        kind, procs = plan_source(rel, rows, text)
        if not procs:
            continue
        if re.search(r"[:\s]", rel + repo):
            notes.append("%s: left out; a path with a space or colon cannot be written in an evidence tag" % rel)
            continue
        pg = build_page(repo, rel, kind, procs)
        if pg["steps"]:
            pages.append(pg)
    return pages, notes


def stage_repo(kb, repo, sub=None, dry=False):
    kb = os.path.abspath(kb)
    pages, notes = plan_repo(kb, repo, sub)
    cats = A.categories(kb)
    folder = cats["procedures"]["folder"].strip("/")
    files, used = {}, {}
    for pg in pages:
        rel = "%s/%s.md" % (folder, A.slug_of("%s %s" % (repo, pg["rel"])))
        if rel in used:
            notes.append("%s: same page name as %s; left out" % (pg["rel"], used[rel]))
            continue
        used[rel] = pg["rel"]
        files[A.target(kb, rel, (GENERATOR,))] = render(pg, "procedures")
        notes += ["%s line %s: left out (%s)" % (pg["rel"], om["ref"], ", ".join(om["kinds"])) for om in pg["omitted"]]
    res = {"pages": sorted(files), "notes": notes, "steps": sum(p["steps"] for p in pages), "flagged": sum(p["flagged"] for p in pages),
           "written": [], "batch": None, "digest": None, "problems": []}
    if files:
        out = A.write_files(kb, files, "procedures", dry)
        res.update({k: out[k] for k in ("written", "batch", "digest", "problems")})
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "stage"):
        a = sub.add_parser(name); a.add_argument("kb"); a.add_argument("--repo", required=True); a.add_argument("--path")
        if name == "stage":
            a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "scan":
            pages, notes = plan_repo(kb, args.repo, args.path)
            for pg in pages:
                print("%s\t%s\t%d steps, %d need confirmation" % (pg["rel"], pg["kind"], pg["steps"], pg["flagged"]))
            for n in notes:
                print(n)
            print("%d procedure files recognised" % len(pages))
            return 0
        res = stage_repo(kb, args.repo, args.path, args.dry_run)
    except (ValueError, kb_gate.GateError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    for n in res["notes"]:
        print(n)
    if res["problems"]:
        print("\n".join(res["problems"]))
        print("stage: %d problems, nothing written" % len(res["problems"]))
        return 1
    for rel in res["written"]:
        print("%s%s" % ("would write " if args.dry_run else "", rel))
    if res["batch"]:
        print("staged in batch %s, not in the KB yet; a lead must certify it. Digest: %s" % (res["batch"], res["digest"]))
    print("%d pages, %d steps, %d need confirmation%s" % (len(res["pages"]), res["steps"], res["flagged"], " (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
