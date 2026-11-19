#!/usr/bin/env python3
"""Hand a Devin session and its work to a teammate on the Acme Claims roster.

Writes the handover note into the giver's own session directory (never into anyone else's),
appends to provenance.log, and reassigns the named Jira issues through the same delegate path
the dashboard uses. The Devin-side steps (tagging the session, posting the note into it) need
the Devin session tools, so this prints them for /handover to carry out and does not attempt
them itself. Every write supports --dry-run.
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

import yaml

import question_subtask

ROOT = question_subtask.ROOT
SESSION_ROOT = os.path.join(ROOT, "sdlc", "framework", "context", "session")
HOST = "acme.devinenterprise.com"
GATE_ORDER = (
    "intake", "story_candidates", "research", "backlog", "estimation", "routing",
    "code_review", "qa", "release", "kb_refresh",
)


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def owner_slug(email):
    """The {OWNER} slug from .devin/rules/session-isolation.md."""
    local = (email or "").split("@")[0].lower()
    return re.sub(r"[^a-z0-9]+", "-", local).strip("-")


def roster_person(value):
    """Exactly one roster entry by Jira username, or by a unique name fragment."""
    people = question_subtask.load_people()
    exact = [p for p in people if p.get("jira_user") == value]
    if exact:
        return exact[0]
    lowered = value.lower()
    named = [p for p in people if lowered in (p.get("name") or "").lower()]
    if len(named) == 1:
        return named[0]
    if named:
        raise RuntimeError(
            "%r matches more than one person on the roster: %s"
            % (value, ", ".join("%s (%s)" % (p.get("name"), p.get("jira_user")) for p in named))
        )
    raise RuntimeError(
        "%r is not on the roster (.devin/rules/people.yaml). Handover is roster-only; "
        "add the person through /roster-check first." % value
    )


def git_branch():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def find_requirement(req_id):
    """Every directory holding this requirement, with its recorded owner if approvals.yaml says."""
    found = []
    if not os.path.isdir(SESSION_ROOT):
        return found
    candidates = [os.path.join(SESSION_ROOT, req_id)]
    for entry in sorted(os.listdir(SESSION_ROOT)):
        candidates.append(os.path.join(SESSION_ROOT, entry, req_id))
    for path in candidates:
        if not os.path.isdir(path):
            continue
        approvals = {}
        approvals_path = os.path.join(path, "approvals.yaml")
        if os.path.exists(approvals_path):
            with open(approvals_path, encoding="utf-8") as fh:
                approvals = yaml.safe_load(fh) or {}
        parent = os.path.basename(os.path.dirname(path))
        found.append({
            "path": path,
            "rel": os.path.relpath(path, ROOT).replace(os.sep, "/"),
            "dir_owner": None if parent == "session" else parent,
            "approvals": approvals,
            "files": sorted(f for f in os.listdir(path) if not f.startswith(".")),
        })
    return found


def gate_lines(approvals):
    """One line per gate: signed (by whom, when) or still open."""
    lines = []
    for entry in approvals.get("approvals") or []:  # legacy list shape
        lines.append("- %s: %s by %s (%s) on %s [E: approvals.yaml]" % (
            entry.get("gate_id") or "gate", entry.get("decision") or "recorded",
            entry.get("approver_name") or "unrecorded", entry.get("approver_role") or "role unrecorded",
            entry.get("timestamp") or "unrecorded"))
    phases = approvals.get("phases") or {}
    for name in GATE_ORDER:
        phase = phases.get(name)
        if not phase:
            continue
        status = str(phase.get("status") or "pending")
        gate = phase.get("gate") or phase.get("gate_id") or name
        if status == "approved":
            lines.append("- %s: approved by %s on %s [E: approvals.yaml]" % (
                gate, phase.get("signed_by") or "unrecorded", phase.get("signed_at") or "unrecorded"))
        else:
            lines.append("- %s: %s [E: approvals.yaml]" % (gate, status))
    return lines


def note_text(args, giver, taker, record, jira_keys):
    session_url = "https://%s/sessions/%s" % (HOST, args.session)
    lines = [
        "# Handover — %s" % (args.session_title or args.session),
        "",
        "- From: %s (%s) [E: people.yaml]" % (giver.get("name"), giver.get("jira_user")),
        "- To: %s (%s), roles: %s [E: people.yaml]" % (
            taker.get("name"), taker.get("jira_user"), ", ".join(taker.get("roles") or []) or "none listed"),
        "- When: %s" % now(),
        "- Devin session: %s" % session_url,
        "- Requirement: %s" % (args.requirement or "none named"),
        "- Jira reassigned: %s" % (", ".join(jira_keys) if jira_keys else "none"),
        "- Branch when handed over: %s [E: git]" % git_branch(),
        "",
        "## Where the work is",
        "",
        args.note.strip() if args.note else "[?] No note was written by the giver — ask %s." % giver.get("name"),
        "",
    ]
    if record:
        approvals = record["approvals"]
        lines += [
            "## Gates for %s" % args.requirement,
            "",
            "- Session directory: %s" % record["rel"],
            "- Directory owner: %s; approvals.yaml owner: %s (%s)" % (
                record["dir_owner"] or "legacy, unowned", approvals.get("owner") or "unrecorded",
                approvals.get("owner_email") or "no email"),
            "- Mode: %s" % (approvals.get("mode") or "unrecorded"),
        ]
        lines += gate_lines(approvals) or ["- No gate recorded in approvals.yaml [E: directory listing]"]
        lines += ["", "## Files in the directory", ""]
        lines += ["- %s" % f for f in record["files"]]
        lines += [""]
    elif args.requirement:
        lines += ["## Gates", "", "- [?] %s was not found under context/session/ on this branch." % args.requirement, ""]
    lines += [
        "## What %s does next" % (taker.get("name") or "the taker"),
        "",
        "1. Open the Devin session link above to read the full history. Access is not granted by",
        "   this note; if the link does not open, ask %s to share it. [?]" % giver.get("name"),
        "2. In a new Devin session run `/resume-session %s`. It will show this note and offer to"
        % (args.requirement or "<REQ-ID>"),
        "   copy the artefacts into your own session directory — say yes; nothing is written into",
        "   the giver's directory.",
        "3. `/dashboard` — the reassigned Jira items are now in your queue.",
        "",
        "## Don't know",
        "",
        "- Whether the taker can open the original Devin session: Devin Cloud org admins can say. [?]",
        "- Session ownership in Devin Cloud does not move with this note; it stays with the giver. [A]",
        "  If that is wrong, nothing here changes except that step 1 becomes unnecessary.",
        "",
    ]
    return "\n".join(lines)


def handover_dir(giver, args, record):
    """Where the note goes: the giver's own REQ directory, or their handovers folder."""
    giver_slug = owner_slug(giver.get("email"))
    if not giver_slug:
        raise RuntimeError("%s has no email on the roster, so no owner slug for the note." % giver.get("name"))
    if record and record["dir_owner"] == giver_slug:
        return record["path"], giver_slug
    return os.path.join(SESSION_ROOT, giver_slug, "handovers"), giver_slug


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--session", required=True, help="Devin session id, with or without the devin- prefix")
    parser.add_argument("--session-title", default="")
    parser.add_argument("--from", dest="giver", required=True, help="Jira username of the person handing over")
    parser.add_argument("--to", required=True, help="Jira username or unique roster name fragment")
    parser.add_argument("--requirement", help="REQ id whose session directory this hands over")
    parser.add_argument("--jira", action="append", default=[], help="Acme Claims key to reassign; repeatable")
    parser.add_argument("--note", default="", help="where the work is and what comes next")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    args.session = args.session.replace("devin-", "")

    try:
        giver = roster_person(args.giver)
        taker = roster_person(args.to)
        if giver.get("jira_user") == taker.get("jira_user"):
            raise RuntimeError("giver and taker are the same person.")
        record = None
        if args.requirement:
            records = find_requirement(args.requirement)
            if len(records) > 1:
                raise RuntimeError(
                    "%s exists in more than one place: %s — pass the one you mean by fixing the tree first."
                    % (args.requirement, ", ".join(r["rel"] for r in records)))
            record = records[0] if records else None
            if record and record["dir_owner"] and record["dir_owner"] != owner_slug(giver.get("email")):
                raise RuntimeError(
                    "%s belongs to %s, not to %s. Only the owner can hand a session directory over."
                    % (args.requirement, record["dir_owner"], giver.get("name")))
        for key in args.jira:
            if not re.fullmatch(r"ACME-\d+", key):
                raise RuntimeError("%r is not a Acme Claims key." % key)

        target_dir, giver_slug = handover_dir(giver, args, record)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M")
        note_path = os.path.join(target_dir, "HANDOVER-%s-%s.md" % (stamp, taker.get("jira_user")))
        text = note_text(args, giver, taker, record, args.jira)
        rel_note = os.path.relpath(note_path, ROOT).replace(os.sep, "/")

        if args.dry_run:
            print("--- would write %s ---" % rel_note)
            print(text)
        else:
            os.makedirs(target_dir, exist_ok=True)
            with open(note_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            with open(os.path.join(target_dir, "provenance.log"), "a", encoding="utf-8") as fh:
                fh.write("%s handover session=%s from=%s to=%s jira=%s note=%s\n" % (
                    now(), args.session, giver.get("jira_user"), taker.get("jira_user"),
                    ",".join(args.jira) or "-", os.path.basename(note_path)))
            print("Wrote %s" % rel_note)

        for key in args.jira:
            question_subtask.do_delegate(argparse.Namespace(
                key=key, to=taker["jira_user"], by=giver["jira_user"], dry_run=args.dry_run,
                note="Session handover: https://%s/sessions/%s\n%s" % (HOST, args.session, args.note or ""),
            ))

        print("\nStill to do in the session (needs the Devin session tools):")
        print("  1. set_tags on devin-%s to add handed-to:%s" % (args.session, taker["jira_user"]))
        print("  2. post the note above as a message into devin-%s so it is in the history" % args.session)
        print("  3. commit %s (and provenance.log) by explicit path" % rel_note)
        print("  4. tell %s: open https://%s/sessions/%s, then /resume-session %s in a new session" % (
            taker.get("name"), HOST, args.session, args.requirement or "<REQ-ID>"))
        return 0
    except (RuntimeError, OSError, yaml.YAMLError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
