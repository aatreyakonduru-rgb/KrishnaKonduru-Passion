#!/usr/bin/env python3
"""The one place that knows whether a gate is open.

Stage skills, the UserPromptSubmit hook, /status and /approve all call this instead of reading
approvals.yaml by hand. The gate definitions come from .devin/rules/approval-gates.yaml, the
roster from .devin/rules/people.yaml, the session directory from session_store.py.

Two modes, chosen by `gates.mode` in .devin/config.json (override: SDLC_GATE_MODE):

  dev       the framework is still being built. The session owner may sign any gate in person.
            Every record still carries the gate id, artifacts, decision items, the exact words
            and the timestamp — plus `self_signed: true` and `role_mismatch` when the owner does
            not hold the gate's required role. Nothing is skipped, only who may sign is relaxed.
  enforced  the approver must hold the gate's required role in people.yaml, be a listed approver
            name, or have "lead" in one of their roles (tech_lead, delivery_lead, solution_lead,
            lead), since a lead may sign any gate. Anything else is refused.

Only a reply whose first word is "approved" counts (gate-presentation.md). "ok", "approve",
"continue", "yes" leave the gate open — the tool says so and exits 3.

  gates.py present  GATE REQ [--story STORY-1] [--artifact PATH ...] [--item TEXT ...]
  gates.py decide   GATE REQ [--story STORY-1] --by "Name" --reply "approved ..." [--items 1,2] [--note TEXT]
  gates.py require  GATE REQ [--story STORY-1]        exit 0 open, 2 blocked
  gates.py status   REQ                                gate table for /status
  gates.py timeouts [--hours-grace N]                  pending gates past timeout_hours
  gates.py precheck "<prompt text>" [REQ]              used by the UserPromptSubmit hook

Exit codes: 0 ok · 2 gate blocked · 3 reply is not an approval · 4 approver not allowed.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import metrics  # noqa: E402
import access_guard  # noqa: E402
import session_store  # noqa: E402

ROOT = session_store.ROOT
GATES_PATH = os.path.join(ROOT, ".devin", "rules", "approval-gates.yaml")
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
CONFIG_PATH = session_store.CONFIG_PATH

# gate -> phase key in approvals.yaml (kept for the existing template layout)
PHASE_OF = {
    "SDLC_01_INTAKE_CLARIFICATION": "intake",
    "SDLC_02_GAP_ANALYSIS_REVIEW": "research",
    "SDLC_02b_STORY_CANDIDATE_REVIEW": "story_candidates",
    "SDLC_03_BACKLOG_APPROVAL": "backlog",
    "SDLC_03a_STORY_ESTIMATION_REVIEW": "estimation",
    "SDLC_04_ROUTING_APPROVAL": "routing",
    "SDLC_05_CODE_REVIEW": "code_review",
    "SDLC_06_QA_SIGNOFF": "qa",
    "SDLC_07_ENV_PROMOTION_APPROVAL": "release",
    "SDLC_08_KB_REFRESH_VALIDATION": "kb_refresh",
    "DB_02_DISCOVERY_VALIDATION": "db_discovery",
    "HOTFIX_PLAN_CODE_APPROVAL": "hotfix",
}
# a production incident's one Tech Lead gate stands in for these two (tools/hotfix.py)
HOTFIX_GATE = "HOTFIX_PLAN_CODE_APPROVAL"
HOTFIX_COVERS = ("SDLC_04_ROUTING_APPROVAL", "SDLC_05_CODE_REVIEW")
# what a stage needs before it may start (the gate that opens it)
STAGE_REQUIRES = {
    "research": "SDLC_01_INTAKE_CLARIFICATION",
    "plan": ("SDLC_03_BACKLOG_APPROVAL", "SDLC_03a_STORY_ESTIMATION_REVIEW"),
    "implement": "SDLC_04_ROUTING_APPROVAL",
    "eval": "SDLC_05_CODE_REVIEW",
    "release": "SDLC_06_QA_SIGNOFF",
    "kb-refresh": "SDLC_07_ENV_PROMOTION_APPROVAL",
}
STAGE_PROMPT_RE = {
    "research": r"\b(research|gap analysis|generate stories|export-jira)\b",
    "plan": r"(/plan\b|routing map|insertion points?)",
    "implement": r"(/implement\b|/pr-readiness\b)",
    "eval": r"/eval\b",
    "release": r"/release\b",
    "kb-refresh": r"/kb-refresh\b",
}
APPROVE_RE = re.compile(r"^\s*approved\b", re.I)
REJECT_RE = re.compile(r"^\s*rejected?\b", re.I)
ITEM_DECISION_RE = re.compile(r"\b(approved|rejected)\s+(\d+(?:\s*(?:,|&|and)\s*\d+)*)", re.I)


def item_decisions(reply):
    """Per-item decisions in a reply such as 'rejected — approved 1,2,4; rejected 3 — reason'."""
    out = {}
    for verb, nums in ITEM_DECISION_RE.findall(reply or ""):
        for n in re.findall(r"\d+", nums):
            out[int(n)] = verb.lower()
    return out


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def gate_defs(path=GATES_PATH):
    return {g["id"]: g for g in load_yaml(path).get("gates", [])}


def gate_mode():
    if os.environ.get("SDLC_GATE_MODE"):
        return os.environ["SDLC_GATE_MODE"]
    return session_store.load_config().get("gates", {}).get("mode", "enforced")


def people(path=PEOPLE_PATH):
    return load_yaml(path).get("people", []) or []


def find_person(name_or_email, roster=None):
    needle = (name_or_email or "").strip().lower()
    for p in roster if roster is not None else people():
        if needle in {str(p.get("name", "")).lower(), str(p.get("email", "")).lower(),
                      str(p.get("jira_user", "")).lower()}:
            return p
        last, _, first = str(p.get("name", "")).partition(",")
        if needle == (first.strip() + " " + last.strip()).lower():
            return p
    return None


def holds_role(person, gate):
    if not person:
        return False
    roles = set(person.get("roles") or [])
    if any("lead" in str(r) for r in roles | {person.get("primary_role")} | set(person.get("secondary_roles") or [])):
        return True
    wanted = {gate.get("required_role")} | {a.get("role") for a in gate.get("approvers", [])}
    if roles & {r for r in wanted if r}:
        return True
    names = {n.lower() for a in gate.get("approvers", []) for n in (a.get("names") or [])}
    last, _, first = str(person.get("name", "")).partition(",")
    return (last.strip() + " " + first.strip()).lower() in names


def is_owner(person):
    owner = (session_store.resolve_owner() or "").strip().lower()
    if "@" in owner:
        owner = session_store.slug(owner)
    if not owner or not person:
        return False
    return session_store.slug(person.get("email", "")) == owner or owner == str(person.get("jira_user", "")).lower()


def is_requester(person, roster):
    """The session owner, or the person /identify-requester recorded (in Devin Cloud the git author
    is a service account, so the owner alone does not say who asked)."""
    if not person:
        return False
    if is_owner(person):
        return True
    current = access_guard.current_person(roster or {})
    return bool(current) and str(current.get("email", "")).lower() == str(person.get("email", "")).lower()


def phase_key(gate_id):
    return PHASE_OF.get(gate_id, gate_id.lower())


def get_phase(data, gate_id, story_id=None):
    phases = data.setdefault("phases", {})
    key = phase_key(gate_id)
    if story_id and gate_id.startswith(STORY_GATES):
        stories = phases.setdefault("stories", {}).setdefault(story_id, {})
        return stories.setdefault(key, {"status": "pending", "gate": gate_id})
    return phases.setdefault(key, {"status": "pending", "gate": gate_id})


def flatten_records(data):
    """One flat list of gate records from an approvals.yaml in either layout.

    New layout: phases.{intake,...} and phases.stories.{STORY}.{code_review,...} (what present()
    writes). Legacy layout: a top-level `approvals:` (or `gates:`) list. Each record carries
    gate_id, status, decision, story_id, timestamp and approver_name.
    """
    if not data:
        return []
    legacy = data.get("approvals") or data.get("gates") or []
    records = [dict(r) for r in legacy if isinstance(r, dict) and r.get("gate_id")]
    phases = data.get("phases") or {}

    def add(sid, ph):
        if not isinstance(ph, dict) or not (ph.get("gate_id") or ph.get("gate")):
            return
        rec = dict(ph)
        rec.setdefault("gate_id", ph.get("gate"))
        rec.setdefault("story_id", sid)
        rec.setdefault("decision", ph.get("status"))
        rec.setdefault("timestamp", ph.get("signed_at") or ph.get("presented_at"))
        rec.setdefault("approver_name", ph.get("signed_by"))
        records.append(rec)

    for key, ph in phases.items():
        if key == "stories":
            for sid, sp in (ph or {}).items():
                for _k, sph in (sp or {}).items():
                    add(sid, sph)
        else:
            add(None, ph)
    return records


def signed(phase, gate_id):
    """What decide() writes: status approved, a time, at least one decision item with every item
    approved by someone, and a signer on the roster who holds the gate's role (or, in dev mode, a
    recorded self-sign). A hand-written `status: approved` is not enough."""
    items = phase.get("decision_items") or []
    person = find_person(phase["signed_by"]) if phase.get("signed_by") else None
    if not (phase.get("status") == "approved" and phase.get("signed_at") and items and person
            and all(item.get("state") == "approved" and item.get("by") for item in items)):
        return False
    return holds_role(person, gate_defs().get(gate_id) or {}) or \
        (phase.get("self_signed") is True and gate_mode() == "dev")


def is_open(req_id, gate_id, story_id=None, owner=None):
    """A gate is open when its record was signed through decide() (see signed())."""
    try:
        data = session_store.read_approvals(req_id, owner)
    except (RuntimeError, ValueError):
        return False
    if not data:
        return False
    def approved(gid):
        return signed(get_phase(data, gid, story_id), gid)
    return approved(gate_id) or (gate_id in HOTFIX_COVERS and approved(HOTFIX_GATE))


def claims_check(req_id, gate_id, story_id, today=None):
    """SDLC_04 rests on {STORY}-claims.yaml in the session folder (tools/confidence.py claims).
    Until warn_until in .devin/rules/confidence.yaml a missing or unverified claim only warns."""
    if not (gate_id.startswith("SDLC_04") and story_id):
        return None
    import confidence
    folder = session_store.session_dir(req_id) or ""
    path = os.path.join(folder, "%s-claims.yaml" % story_id)
    if not os.path.exists(path):
        mode, until = confidence.claim_mode(today)
        if mode == "block":
            raise SystemExit("SDLC_04 needs %s: /plan writes the claims the routing map relies on" % path)
        return {"file": path, "missing": True, "mode": mode, "warn_until": until}
    res = confidence.claims(path, today)
    if res["blocks"]:
        raise SystemExit("SDLC_04 blocked: %d unverified claims in %s" % (res["unverified"], path))
    return {"file": path, "verified": res["verified"], "unverified": res["unverified"],
            "mode": res["mode"], "warn_until": res["warn_until"]}


def evidence_line(ev):
    if not ev:
        return None
    if ev.get("missing"):
        return "Evidence: no claims file yet (%s) — warning until %s" % (ev["file"], ev.get("warn_until"))
    return "Evidence: %d claims verified, %d unverified%s" % (
        ev["verified"], ev["unverified"], (" — warning until %s" % ev.get("warn_until")) if ev["unverified"] else "")


def present(req_id, gate_id, story_id=None, artifacts=None, items=None, defs=None):
    gate = (defs or gate_defs())[gate_id]
    evidence = claims_check(req_id, gate_id, story_id)
    data = session_store.read_approvals(req_id) or {"requirement_id": req_id, "created": now(),
                                                    "owner": session_store.resolve_owner()}
    phase = get_phase(data, gate_id, story_id)
    texts = items or [item_text(x).replace("{id}", req_id.replace("REQ-", "")) for x in gate.get("decision_items") or ["The artifacts as written"]]
    phase.update({
        "status": "pending", "gate_id": gate_id, "requirement_id": req_id, "story_id": story_id,
        "presented_at": now(), "mode": gate_mode(),
        "artifacts": artifacts or [a.replace("{id}", req_id.replace("REQ-", "")) for a in gate.get("artifacts_to_review", [])],
        "decision_items": [{"n": i + 1, "text": t, "state": "pending", "by": None, "note": None} for i, t in enumerate(texts)],
        "timeout_hours": gate.get("timeout_hours"),
    })
    if evidence:
        phase["evidence"] = evidence
    path = session_store.write_approvals(req_id, data)
    metrics.record("gate_presented", req_id, gate=gate_id, story_id=story_id)
    return phase, path, render_block(gate, req_id, story_id, phase)


def item_text(item):
    if isinstance(item, dict):
        return "; ".join("%s: %s" % (k, v) for k, v in item.items())
    return str(item)


def approver_route(gate, on=None, rows=None, roster=None):
    """(names, notes): who signs `gate` on day `on`. The named approvers in order; someone away (the Time off and
    backups table) is replaced by their approval backup, else left out for the next named approver; when every named
    approver is away with no cover, the gate's backups who are not away. The planner not being readable leaves the
    names as configured, with a note."""
    named = [n for a in gate.get("approvers") or [] for n in (a.get("names") or [])]
    backups = [n for a in gate.get("approvers") or [] for n in (a.get("backups") or [])]
    try:
        import sprint_leave
        import time_off
        roster = roster if roster is not None else time_off.people()
        rows = rows if rows is not None else sprint_leave.load_time_off()
    except Exception as exc:  # noqa: BLE001 - routing is a convenience; the gate still names its approvers
        return named, ["time-off planner not read (%s)" % exc]
    on = on or datetime.date.today()
    names, notes = [], []

    def route(n):
        try:
            person = time_off.find(roster, n)
        except time_off.TimeOffError:
            return n, ""
        got = time_off.route(rows, roster, person, "approval", on)
        if not got["away"]:
            return n, ""
        return (got["to"] if got["to"] != person["name"] else None), got["why"]

    for n in named:
        to, why = route(n)
        if why:
            notes.append(why)
        if to and to not in names:
            names.append(to)
    if not names:
        for n in backups:
            to, why = route(n)
            if to and not why and to not in names:
                names.append(to)
        if names:
            notes.append("everyone named for %s is away; the gate's backup%s %s sign%s" % (
                gate.get("id", "this gate"), "s" if len(names) > 1 else "", ", ".join(names), "" if len(names) > 1 else "s"))
        else:
            names = named
            notes.append("everyone named for %s and its backups is away" % gate.get("id", "this gate"))
    return names, notes


def render_block(gate, req_id, story_id, phase):
    names, notes = approver_route(gate)
    who = ", ".join(names) or gate.get("required_role")
    lines = ["=" * 72, "GATE %s — %s" % (gate["id"], gate["name"]),
             "Requirement: %s%s" % (req_id, ("   Story: " + story_id) if story_id else ""),
             "Approver role: %s (%s)   Timeout: %sh   Mode: %s" % (gate.get("required_role"), who,
                                                                    gate.get("timeout_hours"), phase.get("mode")),
             ] + ["Routing: " + n for n in notes] + ["", "Artifacts to review:"]
    lines += ["  - " + a for a in phase.get("artifacts", [])]
    if evidence_line(phase.get("evidence")):
        lines += ["", evidence_line(phase.get("evidence"))]
    lines += ["", "Approval criteria:"] + ["  [ ] " + c for c in gate.get("approval_criteria", [])]
    lines += ["", "If rejected, this blocks: %s" % gate.get("blocks_if_failed", "-"), "", "Decision items:"]
    lines += ["  %d. %s" % (i["n"], i["text"]) for i in phase.get("decision_items", [])]
    lines += ["", "Reply with one of:",
              "  approved                      — sign every item",
              "  approved 1,3 — <note>         — sign some items, say why the rest wait",
              "  rejected — approved 1,2; rejected 3 — <reasons> — decide each item; one rejected item sends it back",
              "  rejected — <reasons>          — send it back",
              "  /send-approval %s to <person> — let someone else decide" % gate["id"], "=" * 72]
    if phase.get("mode") == "dev":
        lines.insert(-1, "Dev mode: the session owner may sign this gate in person; the record will say so.")
    return "\n".join(lines)


def decide(req_id, gate_id, by, reply, story_id=None, items=None, note=None, defs=None, roster=None):
    gate = (defs or gate_defs())[gate_id]
    data = session_store.read_approvals(req_id)
    if not data:
        raise SystemExit("no approvals.yaml for %s — present the gate first" % req_id)
    phase = get_phase(data, gate_id, story_id)
    if not phase.get("decision_items"):
        phase["decision_items"] = [{"n": 1, "text": "The artifacts as written", "state": "pending", "by": None, "note": None}]

    approved = bool(APPROVE_RE.match(reply))
    rejected = bool(REJECT_RE.match(reply))
    if not (approved or rejected):
        print("NOT AN APPROVAL: the reply must start with 'approved' or 'rejected'. Gate %s stays %s." %
              (gate_id, phase.get("status")))
        return 3

    person = find_person(by, roster)
    mode = gate_mode()
    if roster is None:
        ok, why = access_guard.verify_roster(PEOPLE_PATH)
        if not ok:
            print("NOT ALLOWED: the roster is not verified, so no gate can be signed: %s" % why)
            return 5
    roster_doc = load_yaml(PEOPLE_PATH)
    requester = is_requester(person, roster_doc)
    if gate_id in access_guard.no_self_approval(roster_doc) and requester:
        print("NOT ALLOWED: %s asked for this change, so cannot sign %s for it. Use /send-approval." %
              (by, gate_id))
        return 4
    role_ok = holds_role(person, gate)
    self_signed = False
    if not role_ok:
        if mode == "dev" and requester:
            self_signed = True
        else:
            print("NOT ALLOWED: %s does not hold %s for %s (mode=%s). Use /send-approval." %
                  (by, gate.get("required_role"), gate_id, mode))
            return 4

    per_item = {} if items else item_decisions(reply)
    chosen = set(items or [i["n"] for i in phase["decision_items"]])
    stamp = now()
    for item in phase["decision_items"]:
        state = per_item.get(item["n"]) if per_item else (("approved" if approved else "rejected") if item["n"] in chosen else None)
        if state:
            item.update({"state": state, "by": by, "note": note, "at": stamp})
    all_ok = all(i["state"] == "approved" for i in phase["decision_items"])
    any_rejected = any(i["state"] == "rejected" for i in phase["decision_items"])
    decision = "rejected" if (rejected or any_rejected) else ("approved" if all_ok else "needs_revision")
    phase.update({
        "status": "approved" if decision == "approved" else ("rejected" if decision == "rejected" else "pending"),
        "decision": decision, "approval_words": reply.strip(), "signed_by": by, "signed_at": stamp,
        "timestamp": stamp, "approver_name": by,
        "approver_role": (person or {}).get("primary_role") if person else None,
        "role_mismatch": not role_ok, "self_signed": self_signed, "mode": mode, "rationale": note,
        "artifacts_reviewed": list(phase.get("artifacts", [])),
        "next_gate": next_gate(gate_id, defs) if decision == "approved" else None,
    })
    session_store.write_approvals(req_id, data)
    metrics.record("gate_decided", req_id, gate=gate_id, story_id=story_id, decision=decision, approver=by,
                   rework=decision != "approved", extra={"self_signed": self_signed})
    print("%s %s %s by %s%s" % (gate_id, req_id, decision.upper(), by,
                                 " (self-signed, dev mode)" if self_signed else ""))
    if decision == "approved" and phase["next_gate"]:
        print("next gate: %s" % phase["next_gate"])
    return 0


def next_gate(gate_id, defs=None):
    ids = [g for g in (defs or gate_defs()) if g.startswith("SDLC_")]
    try:
        return ids[ids.index(gate_id) + 1]
    except (ValueError, IndexError):
        return None


def require(req_id, gate_id, story_id=None):
    if is_open(req_id, gate_id, story_id):
        return 0
    print("GATE-BLOCK: %s is not approved for %s%s. Present it and get an explicit 'approved' first." %
          (gate_id, req_id, (" " + story_id) if story_id else ""))
    return 2


def status_rows(req_id, defs=None):
    defs = defs or gate_defs()
    data = session_store.read_approvals(req_id)
    rows = []
    phases = data.get("phases", {}) if data else {}
    for gid in [g for g in defs if g.startswith("SDLC_")]:
        key = phase_key(gid)
        found = []
        if key in phases and isinstance(phases[key], dict):
            found.append((None, phases[key]))
        for sid, sp in (phases.get("stories") or {}).items():
            if isinstance(sp, dict) and key in sp:
                found.append((sid, sp[key]))
        if not found:
            rows.append({"gate": gid, "story": None, "status": "not reached", "by": None, "at": None})
        for sid, ph in found:
            rows.append({"gate": gid, "story": sid, "status": ph.get("status", "pending"),
                         "by": ph.get("signed_by"), "at": ph.get("signed_at") or ph.get("presented_at"),
                         "self_signed": ph.get("self_signed", False)})
    return rows


def render_status(req_id, rows):
    lines = ["%s — gate status (mode %s)" % (req_id, gate_mode())]
    for r in rows:
        tag = " (self-signed)" if r.get("self_signed") else ""
        lines.append("  %-34s %-9s %-12s %s %s%s" % (r["gate"], r["story"] or "", r["status"],
                                                      r["by"] or "", r["at"] or "", tag))
    nxt = next((r for r in rows if r["status"] in ("pending", "waiting")), None)
    if nxt:
        lines.append("Waiting on: %s%s" % (nxt["gate"], (" for " + nxt["story"]) if nxt["story"] else ""))
    return "\n".join(lines)


STAGE_ORDER = ["intake", "research", "plan", "implement", "eval", "release", "kb-refresh"]
GATE_STAGE = {
    "SDLC_01_INTAKE_CLARIFICATION": "intake", "SDLC_02_GAP_ANALYSIS_REVIEW": "research",
    "SDLC_02b_STORY_CANDIDATE_REVIEW": "research", "SDLC_03_BACKLOG_APPROVAL": "research",
    "SDLC_03a_STORY_ESTIMATION_REVIEW": "research", "SDLC_04_ROUTING_APPROVAL": "plan",
    "SDLC_05_CODE_REVIEW": "implement", "SDLC_06_QA_SIGNOFF": "eval",
    "SDLC_07_ENV_PROMOTION_APPROVAL": "release", "SDLC_08_KB_REFRESH_VALIDATION": "kb-refresh",
}


def next_action(req_id, defs=None):
    """Plain-English answer to 'where is REQ and what happens next, and who does it'."""
    defs = defs or gate_defs()
    rows = status_rows(req_id, defs)
    if not session_store.list_sessions().get(req_id):
        return {"requirement_id": req_id, "state": "unknown",
                "message": "%s is not one of your requirements on this machine. /start opens a new one; "
                           "/handover brings someone else's to you." % req_id}
    waiting = next((r for r in rows if r["status"] in ("pending", "waiting")), None)
    if waiting:
        gate = defs[waiting["gate"]]
        names = [n for a in gate.get("approvers") or [] for n in (a.get("names") or [])]
        role = gate.get("required_role") or "the named approver"
        who = ("any %s (%s)" % (role, ", ".join(names))) if len(names) <= 3 else \
              ("any %s (%d people, e.g. %s)" % (role, len(names), ", ".join(names[:2])))
        if not names:
            who = role
        if gate_mode() == "dev":
            who += " (dev mode: you may sign it yourself)"
        return {"requirement_id": req_id, "state": "waiting", "gate": waiting["gate"],
                "story": waiting["story"], "stage": GATE_STAGE.get(waiting["gate"]), "owner": who,
                "since": waiting["at"],
                "message": "%s is waiting at %s (%s)%s. %s needs to reply 'approved', 'rejected' or "
                           "'needs revision' — or type /approve %s." %
                           (req_id, gate.get("name") or waiting["gate"], waiting["gate"],
                            (" for " + waiting["story"]) if waiting["story"] else "", who, req_id)}
    approved = [r for r in rows if r["status"] == "approved"]
    rejected = [r for r in rows if r["status"] in ("rejected", "needs_revision")]
    if rejected:
        r = rejected[-1]
        return {"requirement_id": req_id, "state": "rework", "gate": r["gate"], "stage": GATE_STAGE.get(r["gate"]),
                "owner": "the person running the session",
                "message": "%s was sent back at %s (%s). Fix what the reviewer asked for, then run /%s again."
                           % (req_id, r["gate"], r["status"], GATE_STAGE.get(r["gate"]))}
    if not approved:
        return {"requirement_id": req_id, "state": "started", "stage": "intake", "owner": "the person running the session",
                "message": "%s exists but no gate has been reached. Next: /intake to write and agree the spec." % req_id}
    last = approved[-1]
    stage = GATE_STAGE.get(last["gate"])
    idx = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1
    nxt = STAGE_ORDER[idx + 1] if 0 <= idx < len(STAGE_ORDER) - 1 else None
    if not nxt:
        return {"requirement_id": req_id, "state": "done", "owner": None,
                "message": "%s has passed every gate. Nothing is waiting." % req_id}
    return {"requirement_id": req_id, "state": "ready", "stage": nxt, "owner": "the person running the session",
            "message": "%s passed %s. Next: /%s %s." % (req_id, last["gate"], nxt, req_id)}


def overdue(hours_grace=0, defs=None, owner=None):
    defs = defs or gate_defs()
    out = []
    for req_id in session_store.list_sessions(owner):
        try:
            session_store.read_approvals(req_id, owner)
        except (RuntimeError, ValueError):
            continue
        for row in status_rows(req_id, defs):
            if row["status"] not in ("pending", "waiting") or not row["at"]:
                continue
            limit = defs[row["gate"]].get("timeout_hours") or 0
            age = (datetime.datetime.now(datetime.timezone.utc) - metrics.parse_ts(row["at"])).total_seconds() / 3600
            if age > limit + hours_grace:
                out.append({"requirement_id": req_id, **row, "age_hours": round(age, 1), "timeout_hours": limit,
                            "approver_role": defs[row["gate"]].get("required_role")})
    return out


def newest_owned_session():
    """The owner's most recently touched REQ (local or repo owner dir); legacy shared dirs don't count."""
    owner = session_store.resolve_owner()
    if not owner:
        return None
    best, best_t = None, -1
    for kind, base in (("local", session_store.local_home()), ("repo", session_store.REPO_SESSION_ROOT)):
        for path in glob.glob(os.path.join(base, owner, "REQ-*", "approvals.yaml")):
            t = os.path.getmtime(path)
            if t > best_t:
                best, best_t = os.path.basename(os.path.dirname(path)), t
    return best


STORY_GATES = ("SDLC_04", "SDLC_05", "SDLC_06", "SDLC_07")


def story_in_prompt(prompt, req_id):
    """The story named right after the REQ id in a stage command ("/implement REQ-1 STORY-2" -> STORY-2)."""
    m = re.search(r"\b%s\s+([A-Z][A-Z0-9]*-\d+)\b" % re.escape(req_id or ""), prompt or "")
    return m.group(1) if m else None


def stage_gate_open(req_id, gate_id, owner=None):
    """A stage started without a story: the requirement-wide record, or for a per-story gate
    every story that has a record for it signed (at least one)."""
    if is_open(req_id, gate_id, None, owner):
        return True
    if not gate_id.startswith(STORY_GATES):
        return False
    try:
        data = session_store.read_approvals(req_id, owner)
    except (RuntimeError, ValueError):
        return False
    key = phase_key(gate_id)
    stories = [sid for sid, sp in ((data or {}).get("phases", {}).get("stories") or {}).items()
               if isinstance(sp, dict) and key in sp]
    return bool(stories) and all(is_open(req_id, gate_id, sid, owner) for sid in stories)


def precheck(prompt, req_id=None):
    """UserPromptSubmit hook body: does this prompt start a stage whose opening gate is closed?"""
    for stage, pattern in STAGE_PROMPT_RE.items():
        if re.search(pattern, prompt, re.I):
            needed = STAGE_REQUIRES[stage]
            needed = (needed,) if isinstance(needed, str) else needed
            reqs = [req_id] if req_id else [m for m in re.findall(r"\bREQ-[A-Z0-9-]+\b", prompt)]
            if not reqs:
                reqs = [newest_owned_session()] if newest_owned_session() else []
            for req in reqs:
                if not session_store.list_sessions().get(req):
                    return 2, ("GATE-BLOCK: %s is not a session of owner %s (or does not exist yet). "
                               "Start it with /start, or /handover it to yourself first." %
                               (req, session_store.resolve_owner() or "(unresolved)"))
                story = story_in_prompt(prompt, req)
                for gate in needed:
                    if not (is_open(req, gate, story) if story else stage_gate_open(req, gate)):
                        return 2, "GATE-BLOCK: %s needs %s approved for %s first. Run: /status %s" % (stage, gate, req, req)
    return 0, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("present"); p.add_argument("gate"); p.add_argument("req_id"); p.add_argument("--story")
    p.add_argument("--artifact", action="append"); p.add_argument("--item", action="append")
    p = sub.add_parser("decide"); p.add_argument("gate"); p.add_argument("req_id"); p.add_argument("--story")
    p.add_argument("--by", required=True); p.add_argument("--reply", required=True)
    p.add_argument("--items", help="comma separated item numbers, default all"); p.add_argument("--note")
    p = sub.add_parser("require"); p.add_argument("gate"); p.add_argument("req_id"); p.add_argument("--story")
    p = sub.add_parser("status"); p.add_argument("req_id"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("timeouts"); p.add_argument("--hours-grace", type=float, default=0); p.add_argument("--json", action="store_true")
    p = sub.add_parser("precheck"); p.add_argument("prompt"); p.add_argument("req_id", nargs="?")
    p = sub.add_parser("next"); p.add_argument("req_id", nargs="?"); p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "next":
        req = args.req_id or newest_owned_session()
        if not req:
            print("You have no requirements on this machine yet. /start \"<what you need>\" opens one."); return 0
        info = next_action(req)
        print(json.dumps(info, indent=1) if args.json else info["message"]); return 0

    if args.command == "present":
        _, path, block = present(args.req_id, args.gate, args.story, args.artifact, args.item)
        print(block); print("recorded in %s" % path); return 0
    if args.command == "decide":
        items = [int(x) for x in args.items.split(",")] if args.items else None
        return decide(args.req_id, args.gate, args.by, args.reply, args.story, items, args.note)
    if args.command == "require":
        return require(args.req_id, args.gate, args.story)
    if args.command == "status":
        rows = status_rows(args.req_id)
        print(json.dumps(rows, indent=1) if args.json else render_status(args.req_id, rows)); return 0
    if args.command == "timeouts":
        rows = overdue(args.hours_grace)
        if args.json:
            print(json.dumps(rows, indent=1))
        elif not rows:
            print("no overdue gates")
        else:
            for r in rows:
                print("%s %s %s: %s for %.1fh (limit %sh) — approver role %s" % (
                    r["requirement_id"], r.get("story") or "", r["gate"], r["status"], r["age_hours"],
                    r["timeout_hours"], r["approver_role"]))
        return 0
    if args.command == "precheck":
        code, msg = precheck(args.prompt, args.req_id)
        if msg:
            print(msg)
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
