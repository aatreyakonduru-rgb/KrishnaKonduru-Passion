#!/usr/bin/env python3
"""Audit evidence pack for one story at SDLC_05: one file an auditor can read without opening the session.

    evidence_pack.py build --session DIR --story REQ-X-STORY-n [--pr URL] [--out FILE]

Reads only the session folder: approvals.yaml (who signed which gate, when), {story}-claims.yaml (claims and
whether their evidence checked out), {story}-TEST-REPORT.md and {REQ}-STORY-{n}-AI-VERIFICATION.md (tests and
/pr-readiness status), checkmarx.json / wiz.json / govramp.json (scan results), {story}-verifier.yaml (independent
verifier verdict). Writes {story}-EVIDENCE.md next to them. Anything not found is listed under "Not found", never
filled in.
"""
import argparse
import datetime
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SCANS = ("checkmarx", "wiz", "govramp")
STATUS = re.compile(r"^##\s*Overall Status:\s*(.+)$", re.M)


def _yaml(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def requirement(story):
    return story.split("-STORY-")[0]


def gates(session_dir, story):
    data = _yaml(os.path.join(session_dir, "approvals.yaml"))
    if data is None:
        return None
    req = requirement(story)
    out = []
    for a in data.get("approvals") or []:
        if a.get("requirement_id") not in (None, req):
            continue
        if a.get("story_id") and a["story_id"] not in (story, story[len(req) + 1:]):
            continue
        out.append({"gate": a.get("gate_id", ""), "by": a.get("approver_name", ""),
                    "role": a.get("approver_role", ""), "decision": a.get("decision", ""),
                    "at": str(a.get("timestamp", "")), "why": a.get("rationale", "")})
    return out


def scans(session_dir):
    out = []
    for tool in SCANS:
        path = os.path.join(session_dir, tool + ".json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                r = json.load(fh)
            out.append({"tool": tool, "status": r.get("status", ""), "findings": len(r.get("findings") or []),
                        "blocking": len(r.get("blocking") or []), "note": r.get("note", "")})
    return out


def build(session_dir, story, pr="", today=None, graph=None):
    missing = []
    pack = {"story": story, "pr": pr, "built": str(today or datetime.date.today()), "missing": missing}
    pack["gates"] = gates(session_dir, story)
    if pack["gates"] is None:
        missing.append("approvals.yaml")
    elif not any(g["gate"] == "SDLC_05_CODE_REVIEW" for g in pack["gates"]):
        missing.append("SDLC_05_CODE_REVIEW sign-off (not signed yet)")
    claims_path = os.path.join(session_dir, story + "-claims.yaml")
    pack["claims"] = None
    if os.path.exists(claims_path):
        import confidence
        res = confidence.claims(claims_path, today=today, graph=graph)
        pack["claims"] = {"verified": res["verified"], "unverified": res["unverified"],
                          "rows": [{"id": r["id"], "status": r["status"], "why": r["why"]} for r in res["rows"]]}
    else:
        missing.append(story + "-claims.yaml")
    report = os.path.join(session_dir, story + "-TEST-REPORT.md")
    pack["test_report"] = os.path.basename(report) if os.path.exists(report) else ""
    if not pack["test_report"]:
        missing.append(story + "-TEST-REPORT.md")
    ver = os.path.join(session_dir, story + "-AI-VERIFICATION.md")
    pack["pr_readiness"] = ""
    if os.path.exists(ver):
        with open(ver, encoding="utf-8") as fh:
            m = STATUS.search(fh.read())
        pack["pr_readiness"] = m.group(1).strip() if m else "report found, no Overall Status line"
    else:
        missing.append(story + "-AI-VERIFICATION.md")
    pack["scans"] = scans(session_dir)
    for tool in SCANS:
        if tool not in {s["tool"] for s in pack["scans"]}:
            missing.append(tool + ".json")
    v = _yaml(os.path.join(session_dir, story + "-verifier.yaml"))
    pack["verifier"] = None if v is None else {
        "verdict": v.get("verdict", ""), "rounds": len(v.get("rounds") or []),
        "rework": sum(1 for r in v.get("rounds") or [] if r.get("verdict") == "fail")}
    if v is None:
        missing.append(story + "-verifier.yaml (needed for medium and high-risk stories only)")
    if not pr:
        missing.append("PR link")
    return pack


def render(pack):
    L = ["# Audit evidence: %s" % pack["story"], "", "Built %s from the session folder. PR: %s" % (
        pack["built"], pack["pr"] or "not given"), "", "## Gates", ""]
    if pack["gates"]:
        L += ["| Gate | Signed by | Role | Decision | When | Why |", "|---|---|---|---|---|---|"]
        L += ["| %(gate)s | %(by)s | %(role)s | %(decision)s | %(at)s | %(why)s |" % g for g in pack["gates"]]
    else:
        L.append("No gate sign-offs found.")
    L += ["", "## Claims", ""]
    c = pack["claims"]
    if c:
        L.append("%d verified, %d unverified." % (c["verified"], c["unverified"]))
        L += ["- %(id)s: %(status)s (%(why)s)" % r for r in c["rows"]]
    else:
        L.append("No claims file.")
    L += ["", "## Tests", "", "Test report: %s" % (pack["test_report"] or "not found"),
          "/pr-readiness status: %s" % (pack["pr_readiness"] or "not found"), "", "## Security scans", ""]
    if pack["scans"]:
        L += ["| Tool | Status | Findings | Blocking |", "|---|---|---|---|"]
        L += ["| %(tool)s | %(status)s | %(findings)d | %(blocking)d |" % s for s in pack["scans"]]
    else:
        L.append("No scan results.")
    v = pack["verifier"]
    L += ["", "## Independent verifier", "", ("Verdict %(verdict)s after %(rounds)d round(s), %(rework)d failed." % v)
          if v else "No verifier verdict."]
    L += ["", "## Not found", ""] + (["- " + m for m in pack["missing"]] or ["Nothing missing."])
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--session", required=True)
    b.add_argument("--story", required=True)
    b.add_argument("--pr", default="")
    b.add_argument("--out")
    a = ap.parse_args(argv)
    pack = build(a.session, a.story, a.pr)
    out = a.out or os.path.join(a.session, a.story + "-EVIDENCE.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(pack))
    print("[SDLC] evidence pack %s: %d gate(s), %d not found -> %s" % (
        a.story, len(pack["gates"] or []), len(pack["missing"]), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
