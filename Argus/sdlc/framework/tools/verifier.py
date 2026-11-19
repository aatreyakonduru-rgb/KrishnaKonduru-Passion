#!/usr/bin/env python3
"""An independent check of medium and high-risk stories before the SDLC_05 code review.

    verifier.py risk    --basis "RISK=1/2 ..." [--chain DC-001 ...]       # low, medium or high, and why
    verifier.py start   --story ID --acs FILE --claims FILE [--base REF] [--live]  # read-only Devin session
    verifier.py record  SESSION_DIR --story ID --verdict pass|fail [--finding ".."] [--by devin-<id>]
    verifier.py gate    SESSION_DIR --story ID --basis ".." [--chain DC-..]  # SDLC_05: is a pass on file?
    verifier.py metrics [--root DIR]                                       # Change confidence numbers
    verifier.py missed  ACME-n --defect ACME-m [...]                       # defect files the walk didn't predict

Risk comes from the story's estimation_basis (the RISK dimension of
.devin/templates/complexity-matrix.yaml: 1 Managed = medium, 2 High = high) or from a matrix chain
the change uses whose change_impact is HIGH or CRITICAL (high). Low-risk stories need no verifier.

The verifier is a separate Devin session that did not write the code. It gets the acceptance
criteria, the diff and the claims file, reads the repository, writes nothing, and answers pass or
fail with its findings. /pr-readiness records that answer in {STORY}-verifier.yaml in the session
folder; SDLC_05 needs a pass there for a medium or high-risk story. Nothing is sent without --live
(DEVIN_API_KEY). Every command prints [SDLC] verify lines (.devin/rules/workbench-trace.md).

A missed impact is a file changed by the fix of a defect linked to the story in Jira that the link
graph walk (2 hops) from the story's own files did not reach. A commit belongs to a story or a defect
when its message names the Acme Claims key.
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import confidence  # noqa: E402

REPO = confidence.REPO
MATRIX = os.path.join(REPO, "docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml")
SESSIONS = os.path.join(REPO, "sdlc/framework/context/session")
DEVIN_API = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai").rstrip("/")
TAG = "sdlc-verifier"
VERDICTS = ("pass", "fail")
HIGH_IMPACT = ("HIGH", "CRITICAL")
KEY_RE = re.compile(r"^ACME-\d+$")


def risk_score(basis):
    m = re.search(r"\bRISK\s*=\s*([0-2])\s*/\s*2", basis or "")
    return int(m.group(1)) if m else None


def chain_impacts(chain_ids, matrix=MATRIX):
    if not chain_ids:
        return {}
    with open(matrix) as fh:
        rows = yaml.safe_load(fh) or []
    if isinstance(rows, dict):
        rows = rows.get("documented_chains") or rows.get("chains") or []
    wanted = set(chain_ids)
    return {r["chain_id"]: str(r.get("change_impact", "")).upper()
            for r in rows if isinstance(r, dict) and r.get("chain_id") in wanted}


def risk(basis, chains=(), matrix=MATRIX):
    """(tier, why): the higher of the RISK score and the matrix chains."""
    score = risk_score(basis)
    impacts = chain_impacts(list(chains), matrix)
    high_chains = sorted(c for c, i in impacts.items() if i in HIGH_IMPACT)
    reasons = []
    tier = "low"
    if score is None:
        reasons.append("no RISK score in estimation_basis")
    else:
        reasons.append("RISK=%d/2" % score)
        tier = {0: "low", 1: "medium", 2: "high"}[score]
    if high_chains:
        reasons.append("chain %s" % ", ".join("%s %s" % (c, impacts[c]) for c in high_chains))
        tier = "high"
    return tier, "; ".join(reasons)


def needs_verifier(tier):
    return tier in ("medium", "high")


def diff_text(base):
    return subprocess.run(["git", "diff", base + "...HEAD"], cwd=REPO, capture_output=True, text=True).stdout


def prompt(story, acs, diff, claims_text):
    return "\n".join([
        "You are the independent verifier for story %s. You did not write this change." % story,
        "Read only: do not commit, push, comment on Jira or Confluence, or edit any file.",
        "Check the diff against each acceptance criterion and each claim. Open the files the claims cite.",
        "Answer with one line `VERDICT: pass` or `VERDICT: fail`, then one line per finding:",
        "`FINDING: <AC or claim id> — <file:line> — <what is wrong or missing>`.",
        "", "## Acceptance criteria", acs.strip(),
        "", "## Claims", claims_text.strip(),
        "", "## Diff", diff.strip() or "(empty diff)",
    ])


def start(story, acs, claims_text, diff, live=False, key=None):
    text = prompt(story, acs, diff, claims_text)
    body = {"prompt": text, "title": "Verifier: %s" % story, "tags": [TAG, story]}
    if not live:
        return {"dry_run": True, "prompt": text}
    req = urllib.request.Request(DEVIN_API + "/v1/sessions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def verdict_path(session_dir, story):
    return os.path.join(session_dir, "%s-verifier.yaml" % story)


def record(session_dir, story, verdict, findings=(), by="", today=None, jira=""):
    if verdict not in VERDICTS:
        raise ValueError("verdict must be pass or fail")
    path = verdict_path(session_dir, story)
    data = {"story": story, "rounds": []}
    if os.path.exists(path):
        with open(path) as fh:
            data = yaml.safe_load(fh) or data
    data.setdefault("rounds", []).append({
        "date": today or datetime.date.today().isoformat(), "verdict": verdict,
        "by": by, "findings": list(findings)})
    data["verdict"] = verdict
    if jira:
        data["jira"] = jira
    with open(path, "w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    return data


def gate(session_dir, story, tier):
    """(ok, why) for SDLC_05."""
    if not needs_verifier(tier):
        return True, "%s risk, no verifier needed" % tier
    path = verdict_path(session_dir, story)
    if not os.path.exists(path):
        return False, "%s risk, no verifier verdict yet" % tier
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    if data.get("verdict") == "pass":
        return True, "%s risk, verifier passed" % tier
    return False, "%s risk, verifier failed: %d findings" % (
        tier, len((data.get("rounds") or [{}])[-1].get("findings") or []))


def trace(story, tier, why, result):
    return "[SDLC] verify %s — %s risk (%s); why: medium and high-risk stories get a second, read-only " \
           "session that did not write the code; result: %s" % (story, tier, why, result)


def fix_files(key, repo=REPO):
    """Files changed by every commit whose message names `key`."""
    got = subprocess.run(["git", "log", "--all", "-E", "--grep=%s([^0-9]|$)" % key, "--name-only", "--format="],
                         cwd=repo, capture_output=True, text=True).stdout
    return sorted({line.strip() for line in got.splitlines() if line.strip()})


def predicted(graph, files, hops=2):
    reached = set(files)
    for f in files:
        w = graph.walk("file:" + f, hops=hops, types=["file"])
        if w.get("found"):
            reached.update(r["id"][len("file:"):] for r in w["reached"].get("file", []))
    return reached


def missed_impacts(story, defects, graph, files_of=fix_files, hops=2):
    story_files = files_of(story)
    pred = predicted(graph, story_files, hops)
    rows = []
    for d in defects:
        dfiles = files_of(d)
        rows.append({"defect": d, "files": len(dfiles), "missed": [f for f in dfiles if f not in pred]})
    return {"story": story, "story_files": len(story_files), "predicted": len(pred), "defects": rows,
            "missed": sum(len(r["missed"]) for r in rows)}


def missed_trace(res):
    found = "; ".join("%s: %s" % (r["defect"], ", ".join(r["missed"]) or "none missed") for r in res["defects"])
    return "[SDLC] verify %s — %d defects linked, %d files predicted from %d story files; missed: %s; why: a " \
           "defect fix outside the predicted files is an impact the walk missed; result: %d missed" % (
               res["story"], len(res["defects"]), res["predicted"], res["story_files"], found or "no defects",
               res["missed"])


def metrics(root=SESSIONS, today=None, graph=None, defects_for=None, files_of=fix_files):
    """Claims verified vs unverified, verifier verdicts, rework and missed impacts, from the session folders.

    defects_for(keys) returns {story key: [linked defect keys]} (Jira); without it missed impacts are not read.
    """
    out = {"claims": [], "verifier": [], "verified": 0, "unverified": 0, "impacts": [], "defects_read": False}
    claim_files = sorted(glob.glob(os.path.join(root, "**", "*-claims.yaml"), recursive=True))
    if claim_files:
        graph = graph or confidence.link_graph.Graph(confidence.link_graph.load())
    for path in claim_files:
        res = confidence.claims(path, today=today, graph=graph)
        story = os.path.basename(path)[:-len("-claims.yaml")]
        out["claims"].append({"story": story, "file": confidence.rel(path), "verified": res["verified"],
                              "unverified": res["unverified"], "blocks": res["blocks"]})
        out["verified"] += res["verified"]
        out["unverified"] += res["unverified"]
    for path in sorted(glob.glob(os.path.join(root, "**", "*-verifier.yaml"), recursive=True)):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rounds = data.get("rounds") or []
        out["verifier"].append({"story": data.get("story") or os.path.basename(path)[:-len("-verifier.yaml")],
                                "jira": data.get("jira", ""),
                                "verdict": data.get("verdict", ""), "rounds": len(rounds),
                                "rework": sum(1 for r in rounds if r.get("verdict") == "fail"),
                                "findings": len((rounds[-1].get("findings") or []) if rounds else [])})
    keys = sorted({k for k in [c["story"] for c in out["claims"]] + [v["story"] for v in out["verifier"]]
                   + [v["jira"] for v in out["verifier"]] if KEY_RE.match(k or "")})
    if defects_for and keys:
        linked = defects_for(keys) or {}
        out["defects_read"] = True
        graph = graph or confidence.link_graph.Graph(confidence.link_graph.load())
        for k in keys:
            if linked.get(k):
                out["impacts"].append(missed_impacts(k, linked[k], graph, files_of))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("risk")
    p.add_argument("--basis", default="")
    p.add_argument("--chain", action="append", default=[])
    p = sub.add_parser("start")
    p.add_argument("--story", required=True)
    p.add_argument("--acs", required=True)
    p.add_argument("--claims", required=True)
    p.add_argument("--base", default="origin/feature/devin-sdlc")
    p.add_argument("--live", action="store_true")
    p = sub.add_parser("record")
    p.add_argument("session_dir")
    p.add_argument("--story", required=True)
    p.add_argument("--verdict", required=True, choices=VERDICTS)
    p.add_argument("--finding", action="append", default=[])
    p.add_argument("--by", default="")
    p.add_argument("--jira", default="")
    p = sub.add_parser("gate")
    p.add_argument("session_dir")
    p.add_argument("--story", required=True)
    p.add_argument("--basis", default="")
    p.add_argument("--chain", action="append", default=[])
    p = sub.add_parser("metrics")
    p.add_argument("--root", default=SESSIONS)
    p = sub.add_parser("missed")
    p.add_argument("story")
    p.add_argument("--defect", action="append", default=[])
    a = ap.parse_args(argv)

    if a.cmd == "missed":
        res = missed_impacts(a.story, a.defect, confidence.link_graph.Graph(confidence.link_graph.load()))
        print(missed_trace(res))
        print(json.dumps(res, indent=2))
        return 0

    if a.cmd == "risk":
        tier, why = risk(a.basis, a.chain)
        print(json.dumps({"tier": tier, "why": why, "verifier": needs_verifier(tier)}))
        return 0
    if a.cmd == "start":
        key = os.environ.get("DEVIN_API_KEY", "")
        if a.live and not key:
            print("DEVIN_API_KEY is not set; nothing sent", file=sys.stderr)
            return 2
        with open(a.acs) as fh:
            acs = fh.read()
        with open(a.claims) as fh:
            claims_text = fh.read()
        res = start(a.story, acs, claims_text, diff_text(a.base), live=a.live, key=key)
        if res.get("dry_run"):
            print("DRY-RUN POST %s/v1/sessions\n%s" % (DEVIN_API, res["prompt"]))
            print("[SDLC] verify %s — verifier session not started: dry run; why: --live not given; result: not run"
                  % a.story)
        else:
            print("[SDLC] verify %s — verifier session %s started, read only; why: medium or high-risk story; "
                  "result: waiting" % (a.story, res.get("session_id", "")))
        return 0
    if a.cmd == "record":
        data = record(a.session_dir, a.story, a.verdict, a.finding, a.by, jira=a.jira)
        print("[SDLC] verify %s — verdict %s from %s, %d findings; why: the verifier's answer goes on SDLC_05; "
              "result: %s" % (a.story, a.verdict, a.by or "the verifier", len(a.finding),
                              "passed" if a.verdict == "pass" else "failed (round %d)" % len(data["rounds"])))
        return 0
    if a.cmd == "gate":
        tier, why = risk(a.basis, a.chain)
        ok, result = gate(a.session_dir, a.story, tier)
        print(trace(a.story, tier, why, result))
        return 0 if ok else 1
    print(json.dumps(metrics(a.root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
