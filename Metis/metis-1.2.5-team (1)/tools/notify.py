#!/usr/bin/env python3
"""Notifications: tell a team channel (Slack, Microsoft Teams, a generic webhook, or email) that something in the KB needs a person.

    python3 notify.py channels <kb>                          the channels in the profile, and whether each env var is set (never its value)
    python3 notify.py events   <kb> [--channel NAME] [--json]  events not yet sent to that channel (everything when no channel is named)
    python3 notify.py run      <kb> [--channel NAME] [--digest] [--send]   build the messages; DRY RUN unless --send
    python3 notify.py test     <kb> --channel NAME [--send]    one test message; DRY RUN unless --send

Configuration is the `notify:` section of <kb>/.metis/kb-profile.yaml:

    notify:
      base_url: "http://metis.example:8765"      # optional; messages link to <base_url>/approve and so on
      channels:
        - name: team-slack
          kind: slack                              # slack | teams | webhook | email
          url_env: METIS_SLACK_WEBHOOK             # the NAME of an environment variable that holds the webhook URL
          events: [pending_certification, open_question_raised]
          min_interval: 300                        # seconds between two sends on this channel (default 300)
          digest: true                             # one message per run instead of one per event
        - name: leads-mail
          kind: email
          url_env: METIS_SMTP_PASSWORD             # the NAME of the env var that holds the SMTP password (empty: no login)
          host: smtp.example.com
          port: 587
          security: starttls                       # starttls (default) | ssl | none
          user: metis@example.com
          from: metis@example.com
          to: [leads@example.com]

The profile never holds a secret: a `url_env` that looks like a URL is refused and its value is never printed. Webhook URLs must be
https (http is accepted for localhost only, for tests).

Events (computed from files that already exist; nothing is asked of a model):
  pending_certification  a batch under _PENDING has files waiting for a lead (kb_gate)
  open_question_raised   an open question in _QUESTIONS/VALIDATE_KB.yaml (id, priority, type and the files it blocks; never its text)
  devin_task_queued      a task waiting in .metis/tasks
  review_overdue         pages past their review date in .metis/page_meta.yaml, if that file exists
  stale_pages            pages that cite source files changed since the build (build_plan.stale)
  build_failed           a build run with a failed stage, or a failed build-stage task
  pr_impact_posted       a PR impact comment posted by bb_pr.py (.metis/bb_pr_log.json)

Each event has a key. <kb>/.metis/notify_state.json remembers which keys went to which channel, so the same event is not sent twice,
and when the last message left each channel (min_interval). Dry runs never change the state.

A message holds file names, counts, ids and links only. Every message is passed through sensitive.py first; a line that matches
any rule (secret, key, personal id) is replaced by a note that it was withheld. Sending is OFF by default: nothing leaves the
machine without --send.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_plan  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402
import sensitive  # noqa: E402

EVENTS = ("pending_certification", "open_question_raised", "devin_task_queued", "review_overdue", "stale_pages", "build_failed",
          "pr_impact_posted")
KINDS = ("slack", "teams", "webhook", "email")
STATE = os.path.join(".metis", "notify_state.json")
PAGE_META = (os.path.join(".metis", "page_meta.yaml"), os.path.join(".metis", "page_meta.json"))
PR_LOG = os.path.join(".metis", "bb_pr_log.json")
DEFAULT_MIN_INTERVAL = 300
MAX_INDIVIDUAL = 20   # more events than this on one channel are sent as one digest
MAX_NAMES = 5         # file names listed in one line
MAX_DIGEST_LINES = 8  # lines per event type in a digest
LOOPBACK = ("127.0.0.1", "localhost", "::1")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LINKS = {"pending_certification": "/approve", "open_question_raised": "/questions", "devin_task_queued": "/build",
         "review_overdue": "/", "stale_pages": "/notify", "build_failed": "/build", "pr_impact_posted": "/notify"}
TITLES = {"pending_certification": "Waiting for certification", "open_question_raised": "Open questions",
          "devin_task_queued": "Devin tasks queued", "review_overdue": "Reviews overdue", "stale_pages": "Stale pages",
          "build_failed": "Build failed", "pr_impact_posted": "PR impact comments posted"}


class NotifyError(ValueError):
    pass


def clean(x):
    return " ".join(str(x or "").split())


def short(*parts):
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]


def names(items, limit=MAX_NAMES):
    items = list(items)
    more = len(items) - limit
    return ", ".join(items[:limit]) + (" (+%d more)" % more if more > 0 else "")


# ---- channels ---------------------------------------------------------------------------------
def settings(kb):
    s = kb_gate.profile(kb).get("notify")
    return s if isinstance(s, dict) else {}


def as_list(v):
    if v is None or v == "":
        return []
    return [clean(x) for x in (v if isinstance(v, (list, tuple)) else [v]) if clean(x)]


def channels(kb, env=None):
    """Normalised channels from the profile: [{name, kind, url_env, events, min_interval, digest, env_set, problems, ...}].
    `env_set` says whether the named variable has a value. The value itself is never returned."""
    env = os.environ if env is None else env
    out, seen = [], set()
    for i, c in enumerate(settings(kb).get("channels") or []):
        if not isinstance(c, dict):
            continue
        problems = []
        name = clean(c.get("name")) or "channel-%d" % (i + 1)
        if name in seen:
            problems.append("duplicate channel name")
        seen.add(name)
        kind = clean(c.get("kind")).lower()
        if kind not in KINDS:
            problems.append("kind must be one of %s" % ", ".join(KINDS))
        url_env = clean(c.get("url_env"))
        if url_env and not ENV_NAME.match(url_env):
            problems.append("url_env must be the NAME of an environment variable, never the URL or password itself")
            url_env = ""
        elif not url_env and kind != "email":
            problems.append("url_env is required: the name of the environment variable that holds the webhook URL")
        wanted = as_list(c.get("events")) or list(EVENTS)
        bad = [e for e in wanted if e not in EVENTS]
        if bad:
            problems.append("unknown event(s): %s" % ", ".join(bad))
        try:
            interval = int(c.get("min_interval", DEFAULT_MIN_INTERVAL))
            if interval < 0:
                raise ValueError
        except (TypeError, ValueError):
            problems.append("min_interval must be a number of seconds")
            interval = DEFAULT_MIN_INTERVAL
        ch = {"name": name, "kind": kind, "url_env": url_env, "events": [e for e in wanted if e in EVENTS],
              "min_interval": interval, "digest": bool(c.get("digest")), "env_set": bool(url_env and env.get(url_env)),
              "problems": problems}
        if kind == "email":
            try:
                port = int(c.get("port") or 587)
            except (TypeError, ValueError):
                port, _ = 587, problems.append("port must be a number")
            security = clean(c.get("security") or "starttls").lower()
            if security not in ("starttls", "ssl", "none"):
                problems.append("security must be starttls, ssl or none")
            to = as_list(c.get("to"))
            if not clean(c.get("host")):
                problems.append("host is required for email")
            if not to:
                problems.append("to is required for email")
            ch.update(host=clean(c.get("host")), port=port, security=security, user=clean(c.get("user")),
                      sender=clean(c.get("from")) or clean(c.get("user")), to=to)
            if not ch["sender"]:
                problems.append("from is required for email")
        out.append(ch)
    return out


def base_url(kb):
    return clean(settings(kb).get("base_url")).rstrip("/")


# ---- state ------------------------------------------------------------------------------------
def load_state(kb):
    p = os.path.join(kb, STATE)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as fh:
                st = json.load(fh)
            if isinstance(st, dict):
                st.setdefault("sent", {})
                st.setdefault("last_sent", {})
                return st
        except (OSError, ValueError):
            pass
    return {"sent": {}, "last_sent": {}}


def save_state(kb, st):
    p = os.path.join(kb, STATE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(st, fh, indent=2, sort_keys=True)
        fh.write("\n")


# ---- events -----------------------------------------------------------------------------------
def ev(event, key, text, files=()):
    return {"event": event, "key": key, "text": text, "files": list(files), "link": LINKS[event]}


def _pending(kb):
    out = []
    for batch in kb_gate.batches(kb):
        rel = [f[:-7] if f.endswith(".DELETE") else f for f in kb_gate.pending_files(kb, batch)]
        if not rel:
            continue
        by_team = {}
        for f in rel:
            t = kb_gate.team_of(kb, f)
            by_team[t["name"] if t else kb_gate.UNASSIGNED] = by_team.get(t["name"] if t else kb_gate.UNASSIGNED, 0) + 1
        teams = "; ".join("%s %d" % kv for kv in sorted(by_team.items())) if len(by_team) > 1 or kb_gate.teams(kb) else ""
        out.append(ev("pending_certification", "pending:%s:%s" % (batch, short(*sorted(rel))),
                      "Batch %s: %d file%s waiting for a lead (%s)%s" % (batch, len(rel), "" if len(rel) == 1 else "s", names(sorted(rel)),
                                                                          "; by team: " + teams if teams else ""), rel))
    return out


def _questions(kb):
    out = []
    for q in questions.load(questions.reg_path(kb)).get("questions") or []:
        if q.get("status") != "open" or not q.get("id"):
            continue
        blocks = q.get("blocks") or []
        blocks = [clean(b) for b in (blocks if isinstance(blocks, list) else [blocks]) if clean(b)]
        out.append(ev("open_question_raised", "question:%s" % q["id"],
                      "%s (%s, %s) is open%s%s" % (q["id"], q.get("priority") or "?", q.get("type") or "?",
                                                  "; blocks " + names(blocks, 3) if blocks else "",
                                                  "; for the %s" % clean(q.get("answer_role")) if q.get("answer_role") else ""), blocks))
    return out


def _tasks(kb):
    out, d = [], os.path.join(kb, ".metis", "tasks")
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".yaml"):
            continue
        t = kb_gate.load_yaml(os.path.join(d, name))
        if t.get("id") and t.get("status") == "queued":
            out.append(ev("devin_task_queued", "task:%s" % t["id"], "%s (%s) is queued for a Devin session" % (t["id"], t.get("kind") or "task")))
    return out


def _failed(kb):
    out = []
    d = os.path.join(kb, ".metis", "builds")
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if not name.endswith(".yaml"):
                continue
            r = kb_gate.load_yaml(os.path.join(d, name))
            bad = [s.get("name") for s in r.get("stages") or [] if isinstance(s, dict) and s.get("status") == "failed"]
            if r.get("run") and (bad or r.get("status") == "failed"):
                out.append(ev("build_failed", "build:%s:%s" % (r["run"], short(*bad)),
                              "Build %s has %s" % (r["run"], ("failed stage%s: %s" % ("" if len(bad) == 1 else "s", names(map(str, bad)))) if bad else "failed")))
    d = os.path.join(kb, ".metis", "tasks")
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.endswith(".yaml"):
                t = kb_gate.load_yaml(os.path.join(d, name))
                if t.get("id") and t.get("status") == "failed" and t.get("kind") == "build-stage":
                    out.append(ev("build_failed", "task:%s:failed" % t["id"], "Task %s (build-stage) failed" % t["id"]))
    return out


def _to_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def overdue_pages(kb, today):
    """[(page, due date)] from .metis/page_meta.yaml (or .json) for pages whose review date is before today.
    Accepts `pages: {rel: {review_due: DATE}}` or a list of {page|path: rel, review_due: DATE}; review_by, next_review and due also count."""
    data = {}
    for rel in PAGE_META:
        if os.path.isfile(os.path.join(kb, rel)):
            data = kb_gate.load_yaml(os.path.join(kb, rel))
            break
    rows = data.get("pages", data) if isinstance(data, dict) else data
    items = list(rows.items()) if isinstance(rows, dict) else [((m or {}).get("page") or (m or {}).get("path"), m) for m in rows or []
                                                              if isinstance(m, dict)]
    out = []
    for page, meta in items:
        if not page or not isinstance(meta, dict):
            continue
        due = next((_to_date(meta[k]) for k in ("review_due", "review_by", "next_review", "due") if meta.get(k)), None)
        if due and due < today:
            out.append((str(page), due))
    return sorted(out)


def _overdue(kb, today):
    rows = overdue_pages(kb, today)
    if not rows:
        return []
    pages = [p for p, _ in rows]
    return [ev("review_overdue", "overdue:%s" % short(*pages),
               "%d page%s past the review date (oldest due %s): %s" % (len(rows), "" if len(rows) == 1 else "s",
                                                                       min(d for _, d in rows).isoformat(), names(pages)), pages)]


def _stale(kb):
    try:
        pages, _ = build_plan.stale(kb)
    except Exception:  # no profile, no clone, no git: the event simply is not available
        return []
    if not pages:
        return []
    rel = [p["page"] for p in pages]
    return [ev("stale_pages", "stale:%s" % short(*rel),
               "%d KB page%s cite source files that changed since the build: %s" % (len(rel), "" if len(rel) == 1 else "s", names(rel)), rel)]


def _prs(kb):
    p = os.path.join(kb, PR_LOG)
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            rows = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("pr"):
            out.append(ev("pr_impact_posted", "pr:%s:%s" % (r["pr"], r.get("at") or short(json.dumps(r, sort_keys=True))),
                          "Impact comment %s on PR %s: %s changed file%s, %s object%s affected" % (
                              r.get("action") or "posted", r["pr"], r.get("files", 0), "" if r.get("files") == 1 else "s",
                              r.get("objects", 0), "" if r.get("objects") == 1 else "s")))
    return out


def all_events(kb, today=None):
    """Every event the existing files show right now, in a fixed order. Not filtered by what was already sent."""
    today = today or datetime.date.today()
    out = []
    for fn in (_pending, _questions, _tasks, _overdue, _stale, _failed, _prs):
        out += fn(kb, today) if fn is _overdue else fn(kb)
    return out


def events_since(kb, state=None, channel="", events=None, wanted=None, today=None):
    """Events this channel has not been sent yet: all_events minus the keys state records for `channel`.
    `wanted` limits the event names (a channel's `events`). `events` lets a caller reuse one all_events() result."""
    state = state if state is not None else load_state(kb)
    seen = (state.get("sent") or {}).get(channel or "", {})
    pool = events if events is not None else all_events(kb, today)
    return [e for e in pool if e["key"] not in seen and (wanted is None or e["event"] in wanted)]


# ---- messages ---------------------------------------------------------------------------------
def product(kb):
    return clean((kb_gate.profile(kb).get("product") or {}).get("name")) or "KB"


def link(kb, e):
    b = base_url(kb)
    return "%s%s" % (b, e["link"]) if b else ""


def event_message(kb, e):
    lnk = link(kb, e)
    return "[Metis %s] %s%s" % (product(kb), e["text"], "\nOpen: " + lnk if lnk else "")


def digest_message(kb, evs):
    """One message that sums up many events: counts per type, then a few lines each."""
    L = ["[Metis %s] %d thing%s need attention" % (product(kb), len(evs), "" if len(evs) == 1 else "s")]
    for name in EVENTS:
        rows = [e for e in evs if e["event"] == name]
        if not rows:
            continue
        L.append("%s: %d" % (TITLES[name], len(rows)))
        L += ["- " + e["text"] for e in rows[:MAX_DIGEST_LINES]]
        if len(rows) > MAX_DIGEST_LINES:
            L.append("- (+%d more)" % (len(rows) - MAX_DIGEST_LINES))
        lnk = link(kb, rows[0])
        if lnk:
            L.append("Open: " + lnk)
    return "\n".join(L)


def clean_message(text):
    """(text, withheld kinds). A line that matches a sensitive.py rule is replaced by a note; the match is never repeated."""
    kept, withheld = [], []
    lines = str(text).splitlines()
    bad = {f["line"]: f["kind"] for f in sensitive.scan(str(text))}
    for n, line in enumerate(lines, 1):
        if n in bad:
            withheld.append(bad[n])
            kept.append("(line withheld: it matched the %s check)" % bad[n])
        else:
            kept.append(line)
    return "\n".join(kept), sorted(set(withheld))


# ---- sending ----------------------------------------------------------------------------------
def check_url(url):
    p = urllib.parse.urlparse(url)
    if not p.hostname or not (p.scheme == "https" or (p.scheme == "http" and p.hostname in LOOPBACK)):
        raise NotifyError("the webhook URL in the environment variable must be https (http is accepted for localhost only)")
    return p


def payload(channel, text, evs=None):
    if channel["kind"] == "slack":
        return {"text": text}
    if channel["kind"] == "teams":
        # Workflows webhooks take a message with an Adaptive Card attachment. Needs your Teams to verify.
        return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
                "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
                            "body": [{"type": "TextBlock", "text": text, "wrap": True}]}}]}
    return {"source": "metis", "message": text, "events": [{"event": e["event"], "key": e["key"], "files": e["files"]} for e in evs or []]}


def _smtp(host, port, security, timeout):
    return smtplib.SMTP_SSL(host, port, timeout=timeout) if security == "ssl" else smtplib.SMTP(host, port, timeout=timeout)


def post_json(url, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "metis-notify"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read(4096)
        return r.status


def send(channel, message, dry_run=True, env=None, smtp_factory=None, timeout=15, events=None, subject=None):
    """Send one message on one channel. Dry run (the default) sends nothing and says where it would go.
    Returns {channel, kind, dry_run, sent, ok, status, message, withheld}; it does not raise."""
    env = os.environ if env is None else env
    text, withheld = clean_message(message)
    res = {"channel": channel["name"], "kind": channel["kind"], "dry_run": bool(dry_run), "sent": False, "ok": False, "status": "",
           "message": text, "withheld": withheld}
    if channel.get("problems"):
        res["status"] = "not sent: the channel settings have problems (%s)" % "; ".join(channel["problems"])
        return res
    value = env.get(channel["url_env"]) if channel.get("url_env") else None
    try:
        if channel["kind"] == "email":
            where = "%d recipient%s via %s:%s" % (len(channel["to"]), "" if len(channel["to"]) == 1 else "s", channel["host"], channel["port"])
            if dry_run:
                res.update(ok=True, status="dry run: would email %s" % where)
                return res
            if channel["user"] and not value:
                raise NotifyError("environment variable %s (the SMTP password) is not set" % (channel["url_env"] or "(none named)"))
            msg = EmailMessage()
            msg["Subject"] = subject or "Metis: %s" % product_from_text(text)
            msg["From"], msg["To"] = channel["sender"], ", ".join(channel["to"])
            msg.set_content(text)
            smtp = (smtp_factory or _smtp)(channel["host"], channel["port"], channel["security"], timeout)
            try:
                if channel["security"] == "starttls":
                    smtp.starttls()
                if channel["user"]:
                    smtp.login(channel["user"], value)
                smtp.send_message(msg)
            finally:
                try:
                    smtp.quit()
                except Exception:
                    pass
            res.update(sent=True, ok=True, status="sent: email to %s" % where)
            return res
        if dry_run:
            if not value:
                res.update(ok=True, status="dry run: would POST to the webhook, but environment variable %s is not set here" % channel["url_env"])
            else:
                res.update(ok=True, status="dry run: would POST to %s (%s)" % (check_url(value).hostname, channel["kind"]))
            return res
        if not value:
            raise NotifyError("environment variable %s is not set" % channel["url_env"])
        check_url(value)
        code = post_json(value, payload(channel, text, events), timeout)
        if not 200 <= code < 300:
            raise NotifyError("the webhook answered HTTP %s" % code)
        res.update(sent=True, ok=True, status="sent: HTTP %s" % code)
    except NotifyError as err:
        res["status"] = "not sent: %s" % err
    except urllib.error.HTTPError as err:
        res["status"] = "not sent: the webhook answered HTTP %s" % err.code
    except (urllib.error.URLError, OSError, smtplib.SMTPException) as err:
        # keep the reason, never the URL: a webhook URL is a secret
        reason = re.sub(r"\S*://\S+", "(url)", str(getattr(err, "reason", err)))
        res["status"] = "not sent: %s: %s" % (type(err).__name__, reason)
    return res


def product_from_text(text):
    m = re.match(r"\[Metis ([^\]]*)\]", text)
    return m.group(1) if m else "notification"


def run(kb, send_for_real=False, digest=None, only=None, env=None, now=None, smtp_factory=None, timeout=15, today=None):
    """Work out and (with send_for_real) send what each channel has not had yet.
    Returns [{channel, events: n, held, results: [send result]}]. Dry run leaves notify_state.json alone."""
    now = time.time() if now is None else now
    state = load_state(kb)
    pool = all_events(kb, today)
    live = {e["key"] for e in pool}
    out = []
    for ch in channels(kb, env):
        if only and ch["name"] != only:
            continue
        row = {"channel": ch["name"], "events": 0, "held": "", "results": []}
        out.append(row)
        if ch["problems"]:
            row["results"].append(send(ch, "", True, env))
            continue
        evs = events_since(kb, state, ch["name"], pool, set(ch["events"]))
        row["events"] = len(evs)
        if not evs:
            continue
        last = state["last_sent"].get(ch["name"])
        if last is not None and now - last < ch["min_interval"]:
            row["held"] = "min_interval: %d of %d seconds since the last message" % (now - last, ch["min_interval"])
            continue
        as_digest = bool(digest) if digest is not None else ch["digest"]
        if len(evs) > MAX_INDIVIDUAL:
            as_digest = True
        batches = [(digest_message(kb, evs), evs)] if as_digest else [(event_message(kb, e), [e]) for e in evs]
        done = []
        for msg, group in batches:
            r = send(ch, msg, not send_for_real, env, smtp_factory, timeout, group)
            row["results"].append(r)
            if r["sent"]:
                done += group
        if send_for_real and done:
            sent = {k: v for k, v in (state["sent"].get(ch["name"]) or {}).items() if k in live}
            stamp = datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds")
            sent.update({e["key"]: stamp for e in done})
            state["sent"][ch["name"]] = sent
            state["last_sent"][ch["name"]] = now
    if send_for_real:
        save_state(kb, state)
    return out


def test_message(kb, channel):
    return "[Metis %s] Test message from channel %s. Nothing is wrong; this only checks that the channel works.%s" % (
        product(kb), channel["name"], ("\nOpen: %s/notify" % base_url(kb)) if base_url(kb) else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("channels"); a.add_argument("kb")
    a = sub.add_parser("events"); a.add_argument("kb"); a.add_argument("--channel"); a.add_argument("--json", action="store_true")
    a = sub.add_parser("run"); a.add_argument("kb"); a.add_argument("--channel"); a.add_argument("--digest", action="store_true")
    a.add_argument("--send", action="store_true", help="really send (the default is a dry run)")
    a = sub.add_parser("test"); a.add_argument("kb"); a.add_argument("--channel", required=True); a.add_argument("--send", action="store_true")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    if args.cmd == "channels":
        rows = channels(kb)
        for c in rows:
            print("%s\t%s\tenv %s %s\tevents %s\t%s" % (c["name"], c["kind"] or "?", c["url_env"] or "(none)",
                                                     "SET" if c["env_set"] else "not set", ",".join(c["events"]),
                                                     "PROBLEMS: " + "; ".join(c["problems"]) if c["problems"] else "ok"))
        print("%d channels" % len(rows))
        return 0
    if args.cmd == "events":
        state = load_state(kb)
        evs = events_since(kb, state, args.channel or "")
        if args.json:
            print(json.dumps(evs, indent=2))
        else:
            for e in evs:
                print("%s\t%s" % (e["event"], e["text"]))
            print("%d events" % len(evs))
        return 0
    if args.cmd == "test":
        ch = next((c for c in channels(kb) if c["name"] == args.channel), None)
        if not ch:
            print("error: no channel called %s in the profile" % args.channel, file=sys.stderr)
            return 2
        r = send(ch, test_message(kb, ch), not args.send)
        print("%s: %s\n%s" % (r["channel"], r["status"], r["message"]))
        return 0 if r["ok"] else 1
    rows = run(kb, args.send, True if args.digest else None, args.channel)
    bad = 0
    for row in rows:
        print("%s: %d new event%s%s" % (row["channel"], row["events"], "" if row["events"] == 1 else "s",
                                         " (held, %s)" % row["held"] if row["held"] else ""))
        for r in row["results"]:
            print("  %s" % r["status"])
            if r["message"]:
                print("  | " + r["message"].replace("\n", "\n  | "))
            bad += not r["ok"]
    if not rows:
        print("no channels in the profile (notify.channels)")
    if not args.send:
        print("dry run: nothing was sent. Add --send to send.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
