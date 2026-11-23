import os
import re
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import answers  # noqa: E402
import feedback  # noqa: E402
import screens_chat as S  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class ChatUiTests(unittest.TestCase):
    def setUp(self):
        S.THREADS.clear()
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\nvisit dates\n")
        write(os.path.join(self.kb, "db", "PETS.md"),
              '# PETS\n\nThe pets table has a foreign key to owners. [E: file:r.txt "pets have owners"]\n'
              'The pets table is owned by the clinic team. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "db", "VISITS.md"), '# VISITS\n\nThe visits table stores visit dates. [E: file:r.txt "visit dates"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))
        self.pat = C.Ctx(self.kb, "tok", "Pat Lee")
        self.sam = C.Ctx(self.kb, "tok", "Sam Roe")

    def tearDown(self):
        S.THREADS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_module_contract(self):
        self.assertIn("/chat", S.SCREENS)
        self.assertEqual(S.NAV, [("/chat", "Chat")])
        self.assertEqual({k: v[0] for k, v in S.ACTIONS.items()}, {"/chat/ask": "/chat", "/chat/rate": "/chat", "/chat/clear": "/chat"})

    def test_needs_a_name(self):
        self.assertIn("Say who you are first", S.chat_view(C.Ctx(self.kb, "tok", ""), {}))
        with self.assertRaises(C.UiError):
            S.act_chat_ask(C.Ctx(self.kb, "tok", ""), {"question": "x"})

    def test_empty_message_refused(self):
        with self.assertRaises(C.UiError):
            S.act_chat_ask(self.pat, {"question": "   "})

    def test_turn_uses_same_answerer_as_ask(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        aid = S.thread(self.pat)[0]
        chat = answers.get(self.kb, aid)
        again = answers.compose(self.kb, "Which table does pets reference?")[0]
        self.assertEqual(answers.answer_text(self.kb, chat), again)
        self.assertEqual(chat["mode"], "local")
        html = S.chat_view(self.pat, {})
        self.assertIn("Which table does pets reference?", html)
        self.assertIn("Confidence:", html)
        self.assertIn('href="/files?page=db/PETS.md"', html)
        self.assertIn("lines checked against the KB", html)

    def test_follow_up_carries_previous_key_terms(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        self.assertEqual(S.follow_direction(self.pat, "and who owns it?"), "pets reference")
        _, msg = S.act_chat_ask(self.pat, {"question": "and who owns it?"})
        self.assertIn("topic of your last question", msg)
        second = answers.get(self.kb, S.thread(self.pat)[-1])
        self.assertEqual(second["direction"], "pets reference")
        # without the carried topic "who owns it" matches nothing; with it the pets lines are found
        self.assertEqual(answers.compose(self.kb, "and who owns it?")[1], 0)
        self.assertGreaterEqual(answers.compose(self.kb, "and who owns it?", "pets reference")[1], 1)
        self.assertGreaterEqual(second["checked"]["lines"], 1)
        self.assertIn("topic carried from the last question", S.chat_view(self.pat, {}))

    def test_standalone_question_is_not_changed(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        self.assertIsNone(S.follow_direction(self.pat, "How are the visit dates stored in the visits table?"))
        S.act_chat_ask(self.pat, {"question": "How are the visit dates stored in the visits table?"})
        self.assertIsNone(answers.get(self.kb, S.thread(self.pat)[-1])["direction"])

    def test_first_question_has_no_direction(self):
        self.assertIsNone(S.follow_direction(self.pat, "and its owner?"))

    def test_key_terms(self):
        self.assertEqual(S.key_terms("Which table does pets reference?"), ["pets", "reference"])
        self.assertLessEqual(len(S.key_terms("alpha beta gamma delta epsilon zeta eta theta")), S.KEY_TERMS)

    def test_threads_are_per_user_and_kept_in_memory(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        self.assertEqual(S.thread(self.sam), [])
        self.assertNotIn("Which table does pets reference?", S.chat_view(self.sam, {}))
        self.assertEqual(len(S.thread(C.Ctx(self.kb, "tok", "pat lee"))), 1)  # same person, any case

    def test_last_twenty_turns_only(self):
        for i in range(S.MAX_TURNS + 5):
            S.add_turn(self.pat, "A-%04d" % i)
        t = S.thread(self.pat)
        self.assertEqual((len(t), t[0], t[-1]), (20, "A-0005", "A-0024"))

    def test_clear(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        S.act_chat_clear(self.pat, {})
        self.assertEqual(S.thread(self.pat), [])
        self.assertEqual(len(answers.all_asks(self.kb)), 1)  # the record stays in Ask

    def test_like_goes_through_feedback(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        aid = S.thread(self.pat)[0]
        where, msg = S.act_chat_rate(self.pat, {"id": aid, "rating": "up"})
        self.assertTrue(where.startswith("/chat#t-"))
        fb = feedback.load(self.kb)["feedback"]
        self.assertEqual([(f["rating"], f["by"], f["question"]) for f in fb], [("up", "Pat Lee", "Which table does pets reference?")])
        self.assertEqual(answers.get(self.kb, aid)["feedback"], fb[0]["id"])
        self.assertIn("Rated %s" % fb[0]["id"], S.chat_view(self.pat, {}))
        with self.assertRaises(C.UiError):  # the second rating is refused by answers.rate
            S.act_chat_rate(self.pat, {"id": aid, "rating": "up"})

    def test_dislike_rules_are_the_ask_rules(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        aid = S.thread(self.pat)[0]
        with self.assertRaises(C.UiError):
            S.act_chat_rate(self.pat, {"id": aid, "rating": "down", "why": ""})
        with self.assertRaises(C.UiError):
            S.act_chat_rate(self.pat, {"id": aid, "rating": "down", "why": "wrong", "correct": "x", "redirect": "y"})
        where, msg = S.act_chat_rate(self.pat, {"id": aid, "rating": "down", "why": "wrong table", "redirect": "look at VISITS.md"})
        self.assertIn("Asked again", msg)
        self.assertEqual(len(S.thread(self.pat)), 2)  # the re-ask joins the conversation
        self.assertEqual(S.thread(self.pat)[-1], where.split("#t-")[1])

    def test_cannot_rate_someone_elses_turn(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        with self.assertRaises(C.UiError):
            S.act_chat_rate(self.sam, {"id": S.thread(self.pat)[0], "rating": "up"})

    def test_page_has_no_javascript_and_form_per_turn(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        html = S.chat_view(self.pat, {})
        self.assertNotIn("<script", html.lower())
        self.assertNotRegex(html, r"\son(click|change|submit|load)=")
        self.assertIn('action="/chat/ask"', html)
        self.assertIn('action="/chat/rate"', html)

    def test_user_text_is_escaped(self):
        S.act_chat_ask(self.pat, {"question": "<script>alert(1)</script> pets"})
        html = S.chat_view(self.pat, {})
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_unanswered_question_shows_none_confidence_and_stays_honest(self):
        S.act_chat_ask(self.pat, {"question": "who manages the zebra ledger"})
        html = S.chat_view(self.pat, {})
        self.assertIn("Confidence: None", html)
        self.assertIn("The KB has no line about", html)

    def test_server_wiring(self):
        import server
        self.assertIn("/chat", server.SCREENS)
        self.assertIn("/chat/ask", server.ACTIONS)


if __name__ == "__main__":
    unittest.main()
