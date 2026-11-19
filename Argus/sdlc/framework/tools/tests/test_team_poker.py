"""Team poker across Argus pages: rounds, invites and votes kept as tags on each reader session."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "console"))
import poker_room as pr  # noqa: E402


class FakeDevin:
    def __init__(self):
        self.sessions = {}

    def add(self, sid):
        self.sessions[sid] = {"session_id": sid, "created_at": "2026-10-08T09:00:00Z", "tags": ["sdlc-jira-read"]}

    def list_sessions(self, tag, limit):
        return [dict(s, tags=list(s["tags"])) for s in self.sessions.values() if tag in s["tags"]]

    def session(self, sid):
        return self.sessions[sid]

    def set_tags(self, sid, tags):
        self.sessions[sid]["tags"] = list(tags)


def workbench(devin, sid, clock):
    devin.add(sid)
    return pr.TeamPoker(devin, lambda: sid, clock=clock, today=lambda: "2026-10-08")


class HostSeatTests(unittest.TestCase):
    """In Devin Cloud each Argus's seat is its host session, which can be days old."""

    def test_host_sessions_from_other_days_sit_at_the_table_while_seen(self):
        now = [1000000.0]
        clock = lambda: now[0]  # noqa: E731
        devin = FakeDevin()
        for sid in ("h-po", "h-dev", "h-old"):
            devin.sessions[sid] = {"session_id": sid, "created_at": "2026-10-01T09:00:00Z", "tags": ["other"]}
        devin.sessions["h-old"]["tags"] = ["sdlc-workbench-seat", "wb-seen:GONE:%d" % (now[0] // 60 - 13 * 60)]
        devin.sessions["h-old"]["created_at"] = 1759000000
        seat = lambda sid: pr.TeamPoker(devin, lambda: sid, clock=clock, today=lambda: "2026-10-08",  # noqa: E731
                                        tag=pr.SEAT_TAG, missing="start the bridge")
        po, dev = seat("h-po"), seat("h-dev")
        po.room("Resource 17")
        dev.room("AM1")
        self.assertIn("other", devin.sessions["h-po"]["tags"])
        self.assertIn("sdlc-workbench-seat", devin.sessions["h-dev"]["tags"])
        now[0] += 6
        self.assertEqual(po.room("Resource 17")["online"], ["AM1", "Resource 17"])
        rid = po.start("Resource 17", "po_office", "ACME-1", ["AM1"])["id"]
        now[0] += 6
        dev.vote("AM1", rid, "3")
        now[0] += 6
        self.assertEqual(po.room("Resource 17")["rounds"][0]["voted"], ["AM1"])
        with self.assertRaises(pr.PokerError) as e:
            seat("").room("AM9")
        self.assertEqual(str(e.exception), "start the bridge")


class TeamChatTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000000.0]
        clock = lambda: self.now[0]  # noqa: E731
        self.devin = FakeDevin()
        self.me = pr.TeamChat(workbench(self.devin, "s-me", clock))
        self.you = pr.TeamChat(workbench(self.devin, "s-you", clock))
        self.other = pr.TeamChat(workbench(self.devin, "s-other", clock))
        for c, u in ((self.me, "AM1"), (self.you, "AM2"), (self.other, "AM3")):
            c.inbox(u)

    def test_message_and_reply_reach_only_the_two_people(self):
        self.me.send("AM1", "AM2", "can you  look at\n ACME-1?")
        self.now[0] += 6
        got = self.you.inbox("AM2")["messages"]
        self.assertEqual([(m["from"], m["to"], m["text"]) for m in got], [("AM1", "AM2", "can you look at ACME-1?")])
        self.you.send("AM2", "AM1", "on it")
        self.now[0] += 6
        self.assertEqual([m["text"] for m in self.me.inbox("AM1")["messages"]], ["can you look at ACME-1?", "on it"])
        self.assertEqual(self.other.inbox("AM3")["messages"], [])
        self.assertTrue(all(len(t) <= 256 for s in self.devin.sessions.values() for t in s["tags"]))

    def test_everyone_reaches_every_seat(self):
        self.me.send("AM1", "Everyone", "standup moved to 10")
        self.now[0] += 6
        for chat, user in ((self.me, "AM1"), (self.you, "AM2"), (self.other, "AM3")):
            got = chat.inbox(user)["messages"]
            self.assertEqual([(m["from"], m["to"], m["text"]) for m in got], [("AM1", pr.EVERYONE, "standup moved to 10")])

    def test_commas_survive_the_comma_separated_tag_list(self):
        self.me.send("AM1", "AM2", "yes, at 3, ok? 100%")
        self.assertFalse(any("," in t for t in self.devin.sessions["s-me"]["tags"]))
        self.now[0] += 6
        self.assertEqual(self.you.inbox("AM2")["messages"][0]["text"], "yes, at 3, ok? 100%")
        with self.assertRaises(pr.PokerError):
            self.me.send("AM1", "AM2", "," * pr.CHAT_TEXT)

    def test_keeps_the_last_few_and_checks_the_text(self):
        for i in range(pr.CHAT_KEEP + 3):
            self.now[0] += 1
            self.me.send("AM1", "AM2", "m%d" % i)
        msgs = [t for t in self.devin.sessions["s-me"]["tags"] if t.startswith("msg:")]
        self.assertEqual(len(msgs), pr.CHAT_KEEP)
        self.assertIn("sdlc-jira-read", self.devin.sessions["s-me"]["tags"])
        for to, text in (("AM2", ""), ("AM2", "x" * (pr.CHAT_TEXT + 1)), ("AM1", "hi"), ("", "hi")):
            with self.assertRaises(pr.PokerError):
                self.me.send("AM1", to, text)
        self.now[0] += pr.SEAT_HOURS * 3600 + 60
        self.assertEqual(self.me.inbox("AM1")["messages"], [])


class TeamPokerTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000000.0]
        clock = lambda: self.now[0]  # noqa: E731
        self.devin = FakeDevin()
        self.po = workbench(self.devin, "s-po", clock)
        self.dev = workbench(self.devin, "s-dev", clock)
        self.qa = workbench(self.devin, "s-qa", clock)

    def test_round_reaches_every_invited_workbench_and_hides_votes_until_shown(self):
        for wb, user in ((self.po, "Resource 17"), (self.dev, "AM1"), (self.qa, "AM2")):
            wb.room(user)
        self.now[0] += 6
        self.assertEqual(self.po.room("Resource 17")["online"], ["AM1", "AM2", "Resource 17"])
        rid = self.po.start("Resource 17", "po_office", "acme-9192", ["AM1", "AM2"])["id"]
        self.now[0] += 6
        mine = self.dev.room("AM1")["rounds"][0]
        self.assertEqual((mine["key"], mine["by"], mine["invited"]), ("ACME-9192", "Resource 17", ["AM1", "AM2"]))
        self.dev.vote("AM1", rid, "5")
        self.qa.vote("AM2", rid, "13")
        self.now[0] += 6
        before = self.po.room("Resource 17")["rounds"][0]
        self.assertEqual((before["votes"], before["waiting"]), ({"AM1": "✓", "AM2": "✓"}, []))
        self.po.reveal("Resource 17", "po_office", rid)
        self.now[0] += 6
        after = self.dev.room("AM1")["rounds"][0]
        self.assertEqual(after["votes"], {"AM1": "5", "AM2": "13"})
        self.assertEqual(after["spread"], {"low": 5, "high": 13, "median": 13, "agree": False})

    def test_only_po_and_bsa_start_and_only_the_starter_reveals(self):
        with self.assertRaises(pr.PokerError):
            self.dev.start("AM1", "developer", "ACME-1", ["AM2"])
        rid = self.po.start("Resource 17", "bsa", "ACME-1", ["AM1"])["id"]
        with self.assertRaises(pr.PokerError):
            self.qa.reveal("AM2", "po_office", rid)

    def test_uninvited_and_off_scale_votes_are_refused(self):
        rid = self.po.start("Resource 17", "po_office", "ACME-1", ["AM1"])["id"]
        with self.assertRaises(pr.PokerError):
            self.qa.vote("AM2", rid, "5")
        with self.assertRaises(pr.PokerError):
            self.dev.vote("AM1", rid, "4")
        self.dev.vote("AM1", rid, "?")

    def test_agree_closes_the_round_and_offline_people_drop_out(self):
        self.dev.room("AM1")
        rid = self.po.start("Resource 17", "po_office", "ACME-1", ["AM1"])["id"]
        with self.assertRaises(pr.PokerError):
            self.po.finish("Resource 17", "po_office", rid)
        self.po.reveal("Resource 17", "po_office", rid)
        self.po.finish("Resource 17", "po_office", rid, "3")
        self.now[0] += 10 * 60
        room = self.po.room("Resource 17")
        self.assertEqual((room["rounds"], room["online"]), ([], ["Resource 17"]))


    def test_start_answers_even_when_search_has_not_caught_up(self):
        self.po.room("Resource 17")
        real = self.devin.list_sessions
        self.devin.list_sessions = lambda tag, limit: [dict(s, tags=["sdlc-jira-read"]) for s in real(tag, limit)]
        r = self.po.start("Resource 17", "po_office", "acme-9192", ["AM1"])
        self.devin.list_sessions = real
        self.now[0] += 6
        self.assertEqual((r["key"], r["state"], r["waiting"]), ("ACME-9192", "open", ["AM1"]))
        self.assertEqual(self.dev.room("AM1")["rounds"][0]["id"], r["id"])


class DevinSeatAndTimerTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000000.0]
        clock = lambda: self.now[0]  # noqa: E731
        self.card = {}
        self.devin = FakeDevin()
        self.devin.add("s-po")
        self.po = pr.TeamPoker(self.devin, lambda: "s-po", clock=clock, today=lambda: "2026-10-08",
                               devin_vote=lambda key: self.card.get(key))
        self.dev = workbench(self.devin, "s-dev", clock)
        self.qa = workbench(self.devin, "s-qa", clock)

    def test_devin_votes_privately_and_stays_out_of_the_team_spread(self):
        rid = self.po.start("Resource 17", "po_office", "ACME-7", ["AM1", "AM2", pr.DEVIN_SEAT])["id"]
        self.assertIn(pr.DEVIN_SEAT, self.po.room("Resource 17")["rounds"][0]["waiting"])
        self.card["ACME-7"] = "3"
        self.now[0] += 6
        r = self.po.room("Resource 17")["rounds"][0]
        self.assertEqual(r["votes"], {pr.DEVIN_SEAT: "✓"}, "Devin's card is hidden like everyone's")
        self.dev.vote("AM1", rid, "8")
        self.qa.vote("AM2", rid, "8")
        self.po.reveal("Resource 17", "po_office", rid)
        self.now[0] += 6
        r = self.dev.room("AM1")["rounds"][0]
        self.assertEqual(r["votes"], {"AM1": "8", "AM2": "8", pr.DEVIN_SEAT: "3"})
        self.assertEqual(r["spread"], {"low": 8, "high": 8, "median": 8, "agree": True})
        with self.assertRaises(pr.PokerError):
            self.dev.vote(pr.DEVIN_SEAT, rid, "1")

    def test_timer_shows_the_votes_and_late_votes_are_refused(self):
        rid = self.po.start("Resource 17", "bsa", "ACME-8", ["AM1", "AM2"])["id"]
        self.now[0] += 6
        self.assertEqual(self.dev.room("AM1")["rounds"][0]["left"], 24)
        self.dev.vote("AM1", rid, "5")
        self.now[0] += 30
        with self.assertRaises(pr.PokerError):
            self.qa.vote("AM2", rid, "2")
        self.assertEqual(self.dev.room("AM1")["rounds"][0]["state"], "open", "only the facilitator's Argus shows them")
        r = self.po.room("Resource 17")["rounds"][0]
        self.assertEqual((r["state"], r["votes"], r["waiting"]), ("shown", {"AM1": "5"}, ["AM2"]))

    def test_no_timer_keeps_the_vote_open_until_the_facilitator_ends_it(self):
        rid = self.po.start("Resource 17", "po_office", "ACME-10", ["AM1", "AM2"], seconds=0)["id"]
        self.assertIsNone(self.dev.room("AM1")["rounds"][0]["left"])
        self.now[0] += 3600
        self.dev.vote("AM1", rid, "3")
        self.qa.vote("AM2", rid, "5")
        self.assertEqual(self.po.room("Resource 17")["rounds"][0]["state"], "open")
        with self.assertRaises(pr.PokerError):
            self.dev.reveal("AM1", "developer", rid)
        r = self.po.reveal("Resource 17", "po_office", rid)
        self.assertEqual((r["state"], r["votes"]), ("shown", {"AM1": "3", "AM2": "5"}))
        again = self.po.again("Resource 17", "po_office", rid)
        self.assertNotEqual(again["id"], rid)
        self.assertIsNone(again["left"], "a re-vote keeps the round without a timer")

    def test_timer_length_is_picked_by_the_facilitator(self):
        self.assertEqual(self.po.start("Resource 17", "bsa", "ACME-11", ["AM1"], seconds=120)["left"], 120)
        self.assertEqual(self.po.start("Resource 17", "bsa", "ACME-11", ["AM1"], seconds=5)["left"], 10)
        self.assertEqual(self.po.start("Resource 17", "bsa", "ACME-11", ["AM1"], seconds=9999)["left"], pr.MAX_ROUND_SECONDS)
        self.assertEqual(self.po.start("Resource 17", "bsa", "ACME-11", ["AM1"], seconds=None)["left"], pr.ROUND_SECONDS)
        with self.assertRaises(pr.PokerError):
            self.po.start("Resource 17", "bsa", "ACME-11", ["AM1"], seconds="soon")

    def test_dissent_needs_a_reason_and_the_dissenters_number(self):
        rid = self.po.start("Resource 17", "po_office", "ACME-9", ["AM1", "AM2", pr.DEVIN_SEAT])["id"]
        self.card["ACME-9"] = "3"
        self.dev.vote("AM1", rid, "3")
        self.qa.vote("AM2", rid, "8")
        self.now[0] += 31
        self.po.room("Resource 17")
        with self.assertRaises(pr.PokerError):
            self.po.finish("Resource 17", "po_office", rid, "8", [{"user": "AM2", "why": " "}])
        with self.assertRaises(pr.PokerError):
            self.po.finish("Resource 17", "po_office", rid, "3", [{"user": "AM2", "why": "batch job too"}])
        with self.assertRaises(pr.PokerError):
            self.po.finish("Resource 17", "po_office", rid, "?")
        r = self.po.finish("Resource 17", "po_office", rid, "8", [{"user": "AM2", "why": "the nightly batch also changes"}],
                           devin_basis="SCOPE 1 · RISK 0 = 3/10 → 2.")
        self.assertEqual(r["points"], "8")
        for bit in ("Votes: AM1 3, AM2 8, Devin 3.", "Devin (complexity matrix): SCOPE 1", "Story points agreed: 8.",
                    "AM2 disagreed (voted 8): the nightly batch also changes"):
            self.assertIn(bit, r["record"])
        self.assertEqual(self.po.room("Resource 17")["rounds"], [])


if __name__ == "__main__":
    unittest.main()
