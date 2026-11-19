"""Feature 12 - Git-history secret scan.

Reads `git log -p` (read-only) of every crawled repo that has a .git directory and runs the same secret detectors used on source files over ADDED lines.
Reported per finding: secret type, file path, short commit id, and whether the same fingerprint is still present at HEAD. Never recorded: the value,
the matched line, the author, the committer, the commit message. Also lists sensitive file *names* that were ever committed (keys, keystores, .env, dumps).
"""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from ..facts import ev, make_fact
from ..redact import Redactor
from .common import Ctx, Result, header, md_cell

SENSITIVE_NAME = re.compile(r"(?i)(\.pem|\.key|\.p12|\.pfx|\.jks|\.keystore|\.kdbx|(^|/)\.env(\..*)?|id_rsa|id_dsa|id_ed25519|\.dump|\.bak|\.sql\.gz|\.tfstate(\.backup)?)$")
GIT = ["git", "-c", "safe.directory=*", "-c", "core.quotepath=off", "-c", "core.pager=cat"]
MAX_LINE = 2000
MAX_FINDINGS_PER_REPO = 500
Runner = Callable[[list[str], str], Iterable[str]]


def git_lines(args: list[str], cwd: str) -> Iterable[str]:
    """Stream stdout lines of a read-only git command."""
    if args[0] not in ("log", "rev-parse", "ls-files"):
        raise ValueError("only read-only git commands are allowed")
    p = subprocess.Popen(GIT + args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    try:
        assert p.stdout is not None
        for line in p.stdout:
            yield line.rstrip("\n")
    finally:
        p.stdout.close() if p.stdout else None
        p.wait(timeout=60)


def scan_repo(repo: str, root: str, red: Redactor, max_commits: int, run: Runner = git_lines, exclude: list[str] | None = None) -> dict:
    """Return {"findings": [...], "sensitive_files": [...], "commits": n, "present": n}"""
    exclude = exclude or []
    findings: dict[tuple, dict] = {}
    sensitive: dict[tuple, dict] = {}
    commit, path, commits = "", "", 0
    for line in run(["log", "--all", "-p", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=AM", f"--max-count={max_commits}", "--pretty=format:@@C %h"], root):
        if line.startswith("@@C "):
            commit, path = line[4:].strip(), ""
            commits += 1
            continue
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
            if path and SENSITIVE_NAME.search(path) and not any(x and x in path for x in exclude):
                sensitive.setdefault((path, commit), {"path": path, "commit": commit})
            continue
        if line.startswith("--- ") or not line.startswith("+") or not path or len(line) > MAX_LINE:
            continue
        if any(x and x in path for x in exclude):
            continue
        for f in red.detect(line[1:]):
            if f.category == "secret" and len(findings) < MAX_FINDINGS_PER_REPO:
                findings.setdefault((path, f.type, f.fingerprint), {"repo": repo, "path": path, "type": f.type, "commit": commit, "fingerprint": f.fingerprint})
    # still present at HEAD? re-run the same detector on current file text for files that had findings
    head_fp: set[str] = set()
    for path in sorted({k[0] for k in findings}):
        p = Path(root) / path
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ln in text.splitlines():
                if len(ln) <= MAX_LINE:
                    head_fp.update(f.fingerprint for f in red.detect(ln) if f.category == "secret")
    out = []
    for fnd in findings.values():
        fnd["present_at_head"] = fnd["fingerprint"] in head_fp
        out.append(fnd)
    return {"findings": sorted(out, key=lambda x: (x["path"], x["type"])), "sensitive_files": sorted(sensitive.values(), key=lambda x: x["path"]), "commits": commits}


def run(ctx: Ctx, runner: Runner | None = None) -> Result:
    if not ctx.settings.scan_git_history:
        return Result(coverage={"git history": "off (setting scan_git_history)"})
    facts, md_rows = [], []
    scanned, commits, nogit = [], 0, []
    for repo, root in sorted(ctx.repos.items()):
        if not (Path(root) / ".git").exists():
            nogit.append(repo)
            continue
        try:
            res = scan_repo(repo, root, ctx.redactor, ctx.settings.git_history_max_commits, runner or git_lines, ctx.settings.exclude_sources)
        except (OSError, ValueError, subprocess.SubprocessError):
            nogit.append(repo)
            continue
        scanned.append(repo)
        commits += res["commits"]
        for f in res["findings"]:
            facts.append(make_fact("history_secret", f"{repo}:{f['commit']}:{f['path']}:{f['type']}:{f['fingerprint']}",
                                   {"repo": repo, "path": f["path"], "type": f["type"], "commit": f["commit"], "present_at_head": f["present_at_head"], "fingerprint": f["fingerprint"]},
                                   "DERIVED", [ev(f"{repo}/{f['path']}", f"commit {f['commit']}", f"[{f['type']} detected in history; value not recorded]")], "gitscan",
                                   "secret detectors applied to lines added in `git log -p`; value, author and message are not recorded"))
            md_rows.append(f)
        for s in res["sensitive_files"]:
            facts.append(make_fact("history_sensitive_file", f"{repo}:{s['commit']}:{s['path']}", {"repo": repo, "path": s["path"], "commit": s["commit"]},
                                   "OBSERVED", [ev(f"{repo}/{s['path']}", f"commit {s['commit']}", "sensitive file name committed")], "gitscan"))
    sens = [f for f in facts if f["kind"] == "history_sensitive_file"]
    md = [header("Git-history secret scan", ctx, "Type, file and commit id only. Values, authors and messages are never recorded. Rotate every credential listed here, even if it is gone from HEAD."),
          f"Scanned {len(scanned)} repository(ies), {commits} commit(s) (limit {ctx.settings.git_history_max_commits} per repo, all branches).\n"]
    if nogit:
        md.append(f"UNKNOWN: no git history available for {', '.join(f'`{r}`' for r in nogit)} (no `.git` directory in the crawled copy, or git not usable).\n")
    md.append(f"## Secrets found in history ({len(md_rows)})\n\n| Service | Type | File | Commit | Still at HEAD |\n|---|---|---|---|---|")
    md += [f"| `{r['repo']}` | {r['type']} | `{md_cell(r['path'])}` | `{r['commit']}` | {'**yes**' if r['present_at_head'] else 'no (removed)'} |" for r in md_rows[:1000]] or ["| _none_ | | | | |"]
    md.append(f"\n## Sensitive file names ever committed ({len(sens)})\n")
    md += [f"- `{f['attrs']['repo']}` `{md_cell(f['attrs']['path'])}` in commit `{f['attrs']['commit']}`" for f in sens[:500]] or ["- none"]
    md.append("\n## Limits\n\nOnly added or modified lines in the last N commits are scanned, only commits reachable from the cloned refs, and only text. Secrets that are split, encoded or encrypted are not detected. "
              "Shallow clones hide older history.")
    return Result(files={"git-history/index.md": "\n".join(md) + "\n"}, facts=facts, index=["- [Git-history secret scan](git-history/index.md)"],
                  coverage={"git history": f"{len(scanned)} repos, {commits} commits, {len(md_rows)} secret(s) in history, {len(sens)} sensitive file(s); {len(nogit)} repo(s) without git history"})
