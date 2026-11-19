"""Devin Cloud side of the dashboard's Backlog tab: turns a pasted SDLC-DASHBOARD-BACKLOG block into
Argus's Backlog calls (console/backlog.py), so Cloud and Argus plan exactly the same
Jira writes.

    python3 backlog_cli.py preview --block block.txt --by <jira-user>   # always a preview
    python3 backlog_cli.py apply   --block block.txt --by <jira-user>   # after the requester said "approved"

`apply` still writes only when SDLC_BACKLOG_WRITES=1 and every ticket is on SDLC_BACKLOG_TICKETS;
otherwise it stays a preview and says why. Every write carries the requested-by label and comment.
Planning poker in Cloud: the facilitator's session keeps the round (`poker start`), each invitee
sends their card to the facilitator (`poker vote`), then `poker reveal` and `poker agree`.
"""
import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "console"))
import backlog as bl  # noqa: E402

BLOCK = "SDLC-DASHBOARD-BACKLOG"
JIRA = (os.environ.get("SDLC_SANDBOX_URL") or "https://jira.acme.example").rstrip("/") + "/rest"
TOKEN_ENV = "ACME_JIRA_TOKEN"
STATE_DIR = os.environ.get("SDLC_CONSOLE_HOME") or os.path.expanduser("~/.sdlc/console")


class Jira:
    """Service-account Jira in the shape Backlog expects: get(), request(), token, via."""
    via = "here"

    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get(TOKEN_ENV, "")

    def _call(self, method, path, payload=None):
        if not self.token:
            raise bl.BacklogError(503, "%s is not set in this session" % TOKEN_ENV)
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(JIRA + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=120) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            raise bl.BacklogError(exc.code, "Jira %d on %s: %s" % (exc.code, path, exc.read().decode(errors="replace")[:400]))
        return json.loads(body) if body else {}

    def get(self, path, **params):
        return self._call("GET", path + ("?" + urllib.parse.urlencode(params) if params else ""))

    def request(self, method, path, payload=None):
        return self._call(method, path, payload)


def parse_block(text):
    """The key: value lines between SDLC-DASHBOARD-BACKLOG and END. Repeated `story:` lines become a
    list of stories; `  - x` / `  ac: x` lines belong to the key or story above; `notes: |` takes the
    indented lines under it."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == BLOCK)
    except StopIteration:
        raise bl.BacklogError(400, "no %s block found" % BLOCK)
    out, stories, last = {}, [], None
    for ln in lines[start + 1:]:
        if ln.strip() == "END":
            break
        if not ln.strip():
            continue
        if ln.startswith((" ", "\t")):
            item = ln.strip()
            if stories and last == "story":
                m = re.match(r"(ac|sub-tasks):\s*(.*)$", item)
                if m and m.group(1) == "ac":
                    stories[-1]["ac"].append(m.group(2))
                continue
            if last:
                cur = out.get(last)
                cur = cur if isinstance(cur, list) else ([] if cur in ("", "|", None) else [cur])
                cur.append(item[2:] if item.startswith("- ") else item)
                out[last] = cur
            continue
        key, _, value = ln.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "story":
            title, _, pts = value.partition("|")
            m = re.search(r"([\d.]+)\s*points?", pts)
            stories.append({"title": title.strip(), "points": float(m.group(1)) if m else None, "ac": []})
        else:
            out[key] = value
        last = key
    if stories:
        out["stories"] = stories
    return out


def _text(value):
    return "\n".join(value) if isinstance(value, list) else (value or "")


def _numbered(lines):
    items = [x for x in (lines if isinstance(lines, list) else [lines]) if x and x.strip()]
    return "\n".join("%d. %s" % (i + 1, re.sub(r"^\d+[.)]\s*", "", x.strip())) for i, x in enumerate(items))


def _keys(value):
    return [k.strip() for k in re.split(r"[,\s]+", value or "") if k.strip()]


def _sprint(b, name):
    if not name or name.lower().startswith("backlog"):
        return ""
    import gen_dashboard  # noqa: E402  (team board id lives in dashboard-roles.yaml)
    clean = re.sub(r"\s*\(current\)$", "", name).strip()
    for s in b.sprints(gen_dashboard.team_board()):
        if s["name"] == clean:
            return s
    raise bl.BacklogError(400, "no active or future sprint called %r on the team board" % clean)


def run(b, blk, by):
    """One block -> a list of Backlog changes (each a preview or applied)."""
    act = (blk.get("action") or "").lower()
    key = blk.get("ticket", "")
    if act == "groom":
        out = []
        if blk.get("description"):
            out.append(b.edit(key, {"description": _text(blk["description"])}, by))
        if blk.get("acceptance criteria"):
            out.append(b.set_acceptance(key, _numbered(blk["acceptance criteria"]), by, suggested=True))
        return out
    if act == "edit":
        changes = {"summary": blk.get("title"), "description": _text(blk.get("description")), "epic": blk.get("epic")}
        if blk.get("acceptance criteria"):
            changes["acceptance"] = _numbered(blk["acceptance criteria"])
        return [b.edit(key, changes, by)]
    if act == "point":
        return [b.set_points(key, blk.get("points"), by)]
    if act == "move":
        return [b.move(_keys(blk.get("tickets") or key), _sprint(b, blk.get("to", "")), by)]
    if act == "clone":
        over = {"summary": blk["title"]} if blk.get("title") else {}
        if (blk.get("copy sub-tasks") or "").lower() == "yes":
            over["subtasks"] = []
        return [b.clone(key, by, over)]
    if act == "note":
        return [b.note(key, _text(blk.get("note")), by)]
    if act == "hold":
        return [b.hold(key, blk.get("why", ""), by)]
    if act == "resume":
        return [b.resume(key, by)]
    if act == "demo scheduled":
        return [b.demo_scheduled(key, blk.get("date"), blk.get("audience"), by)]
    if act == "demo given":
        return [b.demo_given(key, blk.get("date"), blk.get("audience"), by)]
    if act == "poker start":
        rnd = b.poker_start(key, by, [v.strip() for v in (blk.get("voters") or "").split(",") if v.strip()])
        if (blk.get("my vote") or "").strip().isdigit():
            rnd = b.poker_vote(rnd["id"], by, blk["my vote"])
        return [{"kind": "poker", "round": rnd}]
    if act == "poker vote":
        return [{"kind": "poker", "round": b.poker_vote(blk.get("round"), blk.get("voter") or by, blk.get("vote"))}]
    if act == "poker reveal":
        return [{"kind": "poker", "round": b.poker_reveal(blk.get("round"))}]
    if act == "poker agree":
        return [b.poker_agree(blk.get("round"), blk.get("points"), by)]
    if act == "create":
        return create_tree(b, blk, by)
    raise bl.BacklogError(400, "unknown action %r" % act)


def create_tree(b, blk, by):
    """An epic (when the block has one) and its stories, each story with the team's standard sub-tasks.
    The stories are linked to the new epic once Jira has given it a key; in a preview they are shown
    against "<new epic>"."""
    out, epic_key = [], blk.get("parent", "")
    if blk.get("epic") and not epic_key:
        parts = [p.strip() for p in blk["epic"].split("|")]
        owner = next((p[6:] for p in parts if p.lower().startswith("owner ")), "")
        spec = parts[2] if len(parts) > 2 else ""
        desc = _text(blk.get("objective")) or parts[0]
        change = b.create({"type": "Epic", "summary": parts[0], "description": desc, "specialty": spec,
                           "labels": [spec] if spec else [], "owner": owner, "force": True}, by, source="dashboard")
        out.append(change)
        epic_key = change.get("created", "")
    for st in blk.get("stories") or []:
        draft = {"type": "Story", "summary": st["title"], "acceptance": _numbered(st["ac"]), "points": st["points"],
                 "epic": epic_key, "subtasks": [], "force": True}
        if not epic_key:
            draft.pop("epic")
        out.append(b.create(draft, by, source="dashboard"))
    return out


def report(changes):
    rows = []
    for c in changes:
        if c.get("kind") == "poker":
            r = c["round"]
            rows.append("- Poker on %s: %d voted, waiting on %s%s" % (r["key"], r["voted"], ", ".join(r["waiting"]) or "nobody",
                        (" | votes %s" % r["votes"]) if r["revealed"] else ""))
            continue
        rows.append("- **%s** %s: %s" % (c["status"], c["title"], c.get("note") or ""))
        for call in c.get("calls") or []:
            rows.append("    - %s %s" % (call["method"], call["path"]))
        for chk in c.get("checks") or []:
            rows.append("    - rule book (%s): %s" % (chk["severity"], chk["text"]))
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dashboard Backlog block -> Jira preview / write")
    ap.add_argument("mode", choices=["preview", "apply"])
    ap.add_argument("--block", required=True, help="file holding the pasted block ('-' for stdin)")
    ap.add_argument("--by", required=True, help="Jira username of the person who asked")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    text = sys.stdin.read() if args.block == "-" else open(args.block, encoding="utf-8").read()
    env = dict(os.environ)
    if args.mode == "preview":
        env.pop(bl.WRITES_ENV, None)
    b = bl.Backlog(Jira(), STATE_DIR, env=env)
    try:
        changes = run(b, parse_block(text), args.by)
    except bl.BacklogError as exc:
        print("Not done: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(changes, indent=1, default=str) if args.json else report(changes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
