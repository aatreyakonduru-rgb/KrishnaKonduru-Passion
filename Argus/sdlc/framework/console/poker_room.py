"""Team planning poker and team chat across Argus pages.

Each Argus has one Devin Cloud session it owns, its seat: the daily Jira reader on a PC, or in Devin Cloud
the host session Argus runs in (tagged sdlc-workbench-seat). The round, the invites and each person's
vote are kept as tags on those seats, so every Argus sees the same round without a shared server, a new
session or a Jira write. Each Argus only ever writes tags on its own seat, so two votes can never overwrite
each other. Votes are hidden on screen until the facilitator
reveals them; they are not encrypted.

Team chat works the same way: a message is a tag on the sender's own seat (msg:<id>:<to>:<epoch>:<text>), so
no Devin agent wakes and nothing is written to Jira or Teams. A tag holds 256 characters, so a message holds
CHAT_TEXT; each seat keeps its last CHAT_KEEP messages for SEAT_HOURS.

Devin sits at the table too: the facilitator's Argus plays Devin's card (scored with the complexity
matrix) as soon as Devin has one. The facilitator ends the vote by hand, or picks a timer when she starts the
round; when it runs out her Argus shows the votes. The team's agreed number is the one saved; when someone
disagrees, their reason is recorded with it.
"""
import datetime
import threading
import time
import uuid

READER_TAG = "sdlc-jira-read"
SEAT_TAG = "sdlc-workbench-seat"
SEAT_HOURS = 12
SCALE = ("1", "2", "3", "5", "8", "13", "?")
FACILITATORS = ("po_office", "bsa")
ONLINE_MINUTES = 3
DEVIN_SEAT = "devin"
ROUND_SECONDS = 30
CHAT_TEXT = 200
CHAT_KEEP = 8
EVERYONE = "*"
MAX_ROUND_SECONDS = 600


class PokerError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class TeamPoker:
    def __init__(self, devin, reader_id, clock=time.time, today=None, devin_vote=None, tag=READER_TAG,
                 missing="This Argus is not connected to Devin Cloud yet: open your ticket list once, then try again."):
        """devin_vote(key) gives Devin's card for a story ("1".."13" or "?") once it has scored it, else None.
        tag picks the seats: READER_TAG for the PC's daily Jira readers, SEAT_TAG for Devin Cloud host sessions."""
        self.devin, self.reader_id, self.clock, self.devin_vote = devin, reader_id, clock, devin_vote
        self.tag, self.missing = tag, missing
        self.today = today or (lambda: datetime.date.today().isoformat())
        self.lock = threading.Lock()
        self._cache, self._seen = (0, []), 0

    # ---- tags on reader sessions
    def _readers(self, fresh=False):
        at, rows = self._cache
        if fresh or self.clock() - at > 5:
            rows = [s for s in self.devin.list_sessions(self.tag, 100)
                    if self._current(s) and "closed" not in (s.get("tags") or [])]
            self._cache = (self.clock(), rows)
        return rows

    def _current(self, s):
        """A reader made today; a host session seen in the last SEAT_HOURS (it can be days old)."""
        made = s.get("created_at") or ""
        if isinstance(made, (int, float)):
            made = datetime.date.fromtimestamp(made).isoformat()
        if made.startswith(self.today()):
            return True
        minute = int(self.clock() // 60)
        return any(t.startswith("wb-seen:") and t.rsplit(":", 1)[-1].isdigit() and
                   minute - int(t.rsplit(":", 1)[-1]) <= SEAT_HOURS * 60 for t in s.get("tags") or [])

    def _mine(self):
        sid = self.reader_id()
        if not sid:
            raise PokerError(409, self.missing)
        return sid

    def _retag(self, drop, add):
        sid = self._mine()
        hit = [s for s in self._readers(fresh=True) if s.get("session_id") == sid]
        tags = list((hit[0] if hit else self.devin.session(sid)).get("tags") or [])
        tags = [t for t in tags if not any(p(t) if callable(p) else t.startswith(p) for p in drop)] + list(add) + [self.tag]
        self.devin.set_tags(sid, sorted(set(tags)))
        self._cache = (0, [])

    def _check_user(self, user):
        if not user or ":" in user:
            raise PokerError(400, "Pick who you are (top right) first.")
        if user.lower() == DEVIN_SEAT:
            raise PokerError(400, "Devin votes for itself.")

    @staticmethod
    def _votes_of(who):
        return lambda t: t.startswith("pkv:") and t.split(":")[2:3] == [who]

    # ---- reading
    def room(self, user, _seated=False):
        minute = int(self.clock() // 60)
        if user and ":" not in user and self.clock() - self._seen > 60:
            with self.lock:
                self._retag(["wb-seen:"], ["wb-seen:%s:%d" % (user, minute)])
                self._seen = self.clock()
        online, rounds, invites, votes, ends = set(), {}, {}, {}, {}
        for s in self._readers():
            for t in s.get("tags") or []:
                p = t.split(":")
                if p[0] == "wb-seen" and len(p) == 3 and p[2].isdigit() and minute - int(p[2]) <= ONLINE_MINUTES:
                    online.add(p[1])
                elif p[0] == "pkr" and len(p) == 5:
                    rounds[p[1]] = {"id": p[1], "key": p[2], "by": p[3], "state": p[4]}
                elif p[0] == "pki" and len(p) == 3:
                    invites.setdefault(p[1], []).append(p[2])
                elif p[0] == "pkv" and len(p) == 4:
                    votes.setdefault(p[1], {})[p[2]] = p[3]
                elif p[0] == "pkt" and len(p) == 3 and p[2].isdigit():
                    ends[p[1]] = int(p[2])
        out = []
        for rid, r in rounds.items():
            if r["state"] == "done":
                continue
            v, shown = votes.get(rid, {}), r["state"] == "shown"
            who = sorted(invites.get(rid, []))
            row = dict(r, invited=who, voted=sorted(v), waiting=[u for u in who if u not in v],
                       votes=dict(v) if shown else {u: "✓" for u in v}, mine=v.get(user, ""),
                       ends=ends.get(rid, 0), left=max(0, int(ends.get(rid, 0) - self.clock())) if rid in ends else None)
            nums = sorted(int(x) for u, x in v.items() if x.isdigit() and u != DEVIN_SEAT)
            if shown and nums:
                row["spread"] = {"low": nums[0], "high": nums[-1], "median": nums[len(nums) // 2],
                                 "agree": nums[0] == nums[-1] and all(x != "?" for u, x in v.items() if u != DEVIN_SEAT)}
            out.append(row)
        if not _seated and (self._seat_devin(user, out) | self._time_up(user, out)):
            return self.room(user, _seated=True)
        return {"online": sorted(online), "rounds": out, "scale": list(SCALE)}

    def _time_up(self, user, rounds):
        """The facilitator's Argus shows the votes when the timer runs out."""
        done = False
        for r in rounds:
            if r["by"] == user and r["state"] == "open" and r["ends"] and self.clock() >= r["ends"]:
                self._set_state(user, r, "shown")
                done = True
        return done

    def _seat_devin(self, user, rounds):
        """Devin's seat lives with the facilitator's Argus: its card goes on as soon as Devin has scored the story."""
        if not self.devin_vote:
            return False
        for r in rounds:
            if r["by"] == user and r["state"] == "open" and DEVIN_SEAT in r["invited"] and DEVIN_SEAT not in r["voted"]:
                card = self.devin_vote(r["key"])
                if card in SCALE:
                    with self.lock:
                        self._retag([self._votes_of(DEVIN_SEAT)], ["pkv:%s:%s:%s" % (r["id"], DEVIN_SEAT, card)])
                    return True
        return False

    def _round(self, user, rid):
        for r in self.room(user)["rounds"]:
            if r["id"] == rid:
                return r
        raise PokerError(404, "That poker round has finished.")

    def _facilitator(self, user, lens, rid=None):
        self._check_user(user)
        if lens not in FACILITATORS:
            raise PokerError(403, "Only the PO and BSA run team poker.")
        if rid:
            r = self._round(user, rid)
            if r["by"] != user:
                raise PokerError(403, "Only %s, who started this round, can do that." % r["by"])
            return r
        return None

    # ---- writing (each only touches this Argus's own reader)
    @staticmethod
    def _seconds(seconds):
        """0 means no timer: the vote stays open until the facilitator ends it."""
        if seconds is None or seconds == "":
            return ROUND_SECONDS
        try:
            n = int(seconds)
        except (TypeError, ValueError):
            raise PokerError(400, "Pick how long the vote runs.")
        return 0 if n <= 0 else max(10, min(MAX_ROUND_SECONDS, n))

    def start(self, user, lens, key, invite, seconds=ROUND_SECONDS):
        self._facilitator(user, lens)
        seconds = self._seconds(seconds)
        key = (key or "").strip().upper()
        people = sorted({u.strip() for u in invite or [] if u and u.strip() and ":" not in u})
        if not key or ":" in key:
            raise PokerError(400, "Pick a story first.")
        if not people:
            raise PokerError(400, "Tick at least one person to point the story.")
        rid = uuid.uuid4().hex[:6]
        timer = ["pkt:%s:%d" % (rid, int(self.clock()) + seconds)] if seconds else []
        with self.lock:
            self._retag(["pkr:", "pki:", "pkt:", self._votes_of(DEVIN_SEAT)],
                        ["pkr:%s:%s:%s:open" % (rid, key, user)] + timer +
                        ["pki:%s:%s" % (rid, u) for u in people])
        try:
            return self._round(user, rid)
        except PokerError:
            # Cloud session search can lag a few seconds behind the tags just set.
            ends = int(self.clock()) + seconds if seconds else 0
            return {"id": rid, "key": key, "by": user, "state": "open", "invited": people, "voted": [],
                    "waiting": people, "votes": {}, "mine": "", "ends": ends, "left": seconds if seconds else None}

    def vote(self, user, rid, points):
        self._check_user(user)
        points = str(points or "").strip()
        if points not in SCALE:
            raise PokerError(400, "Vote with one of %s." % ", ".join(SCALE))
        r = self._round(user, rid)
        if r["state"] != "open" or (r["ends"] and self.clock() > r["ends"] + 2):
            raise PokerError(409, "Time is up and the votes are being shown; wait for the next round.")
        if user not in r["invited"] and user != r["by"]:
            raise PokerError(403, "%s did not ask you to point this round." % r["by"])
        with self.lock:
            self._retag([self._votes_of(user)], ["pkv:%s:%s:%s" % (rid, user, points)])
        return self._round(user, rid)

    def _set_state(self, user, r, state):
        with self.lock:
            self._retag(["pkr:%s:" % r["id"]], ["pkr:%s:%s:%s:%s" % (r["id"], r["key"], user, state)])

    def reveal(self, user, lens, rid):
        r = self._facilitator(user, lens, rid)
        self._set_state(user, r, "shown")
        return self._round(user, rid)

    def again(self, user, lens, rid, seconds=None):
        r = self._facilitator(user, lens, rid)
        if seconds is None or seconds == "":
            seconds = ROUND_SECONDS if r["ends"] else 0
        return self.start(user, lens, r["key"], r["invited"], seconds)

    def finish(self, user, lens, rid, points=None, dissent=None, devin_basis=""):
        """Close the round on the team's number. Anyone who disagreed must have a reason, and the number saved
        is then one a dissenter voted. Returns the round plus the record that goes on the ticket."""
        r = self._facilitator(user, lens, rid)
        if r["state"] != "shown":
            raise PokerError(409, "Show the votes before agreeing.")
        points = str(points or "").strip()
        if points not in SCALE or points == "?":
            raise PokerError(400, "Pick the story points the team agreed.")
        rows = []
        for d in dissent or []:
            who, why = str(d.get("user") or "").strip(), " ".join(str(d.get("why") or "").split())
            if who not in r["votes"] or who == DEVIN_SEAT:
                raise PokerError(400, "%s did not vote in this round." % (who or "Someone"))
            if not why:
                raise PokerError(400, "Write down why %s disagrees before saving." % who)
            rows.append((who, r["votes"][who], why[:600]))
        if rows and points not in [v for _, v, _ in rows]:
            raise PokerError(400, "Someone disagreed, so save the number one of them voted (%s)." %
                             ", ".join("%s %s" % (w, v) for w, v, _ in rows))
        with self.lock:
            self._retag(["pkr:", "pki:", "pkt:", self._votes_of(DEVIN_SEAT)], [])
        return dict(r, points=points, record=record_text(r, points, rows, devin_basis))


def record_text(r, points, dissent, devin_basis=""):
    """The note left on the ticket: every vote, Devin's reasoning, the number saved and who disagreed and why."""
    votes = ", ".join("%s %s" % ("Devin" if u == DEVIN_SEAT else u, v) for u, v in sorted(r["votes"].items()))
    lines = ["Planning poker on %s, run by %s." % (r["key"], r["by"]), "Votes: %s." % (votes or "none")]
    if devin_basis:
        lines.append("Devin (complexity matrix): %s" % devin_basis)
    lines.append("Story points agreed: %s." % points)
    for who, v, why in dissent:
        lines.append("%s disagreed (voted %s): %s" % (who, v, why))
    return "\n".join(lines)


TAG_MAX = 256


def _chat_enc(text):
    """Session tags come back as a comma-separated list, so a message keeps no raw comma."""
    return text.replace("%", "%25").replace(",", "%2C")


def _chat_dec(text):
    return text.replace("%2C", ",").replace("%25", "%")


class TeamChat:
    """Short messages between people on the roster, to one person or to everyone (@everyone), kept on each sender's
    seat (shares TeamPoker's seats)."""

    def __init__(self, poker):
        self.p = poker

    @staticmethod
    def _owner(s):
        seen = [t.split(":") for t in s.get("tags") or [] if t.startswith("wb-seen:")]
        return seen[-1][1] if seen and len(seen[-1]) == 3 else ""

    def _alive(self, at):
        return at.isdigit() and int(at) >= self.p.clock() - SEAT_HOURS * 3600

    def inbox(self, user):
        """Every message from or to this person still kept on a seat, oldest first, and who is online."""
        online = self.p.room(user)["online"]
        out = []
        for s in self.p._readers():
            frm = self._owner(s)
            for t in s.get("tags") or []:
                parts = t.split(":", 4)
                if parts[0] != "msg" or len(parts) != 5 or not frm or not self._alive(parts[3]):
                    continue
                if user in (frm, parts[2]) or parts[2] == EVERYONE:
                    out.append({"id": parts[1], "from": frm, "to": parts[2], "at": int(parts[3]), "text": _chat_dec(parts[4])})
        out.sort(key=lambda m: (m["at"], m["id"]))
        return {"messages": out, "online": online, "max": CHAT_TEXT}

    def send(self, user, to, text):
        self.p._check_user(user)
        to = (to or "").strip()
        if to.lower() == "everyone":
            to = EVERYONE
        if not to or ":" in to or to.lower() == DEVIN_SEAT:
            raise PokerError(400, "Start with @ and the person's name.")
        if to == user:
            raise PokerError(400, "That is you.")
        text = " ".join(str(text or "").split())
        if not text:
            raise PokerError(400, "Write the message after the name.")
        if len(text) > CHAT_TEXT:
            raise PokerError(400, "Keep it to %d characters; use Teams for longer messages." % CHAT_TEXT)
        mid = uuid.uuid4().hex[:6]
        tag = "msg:%s:%s:%d:%s" % (mid, to, int(self.p.clock()), _chat_enc(text))
        if len(tag) > TAG_MAX:
            raise PokerError(400, "Keep it shorter; use Teams for longer messages.")
        sid = self.p._mine()
        mine = next((s for s in self.p._readers(fresh=True) if s.get("session_id") == sid), None)
        tags = (mine or self.p.devin.session(sid)).get("tags") or []
        kept = sorted((t for t in tags if t.startswith("msg:") and len(t.split(":", 4)) == 5 and
                       self._alive(t.split(":", 4)[3])), key=lambda t: int(t.split(":", 4)[3]))[-(CHAT_KEEP - 1):]
        with self.p.lock:
            self.p._retag([lambda t: t.startswith("msg:") and t not in kept], [tag])
        return self.inbox(user)
