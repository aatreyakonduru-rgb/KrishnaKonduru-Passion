"""Chat threads survive a server restart: stored as JSON lines in a local, git-ignored file, per user, capped, written atomically."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import answers  # noqa: E402
import chat_store  # noqa: E402
import kb_gate  # noqa: E402
import kb_manifest  # noqa: E402
import screens_chat as S  # noqa: E402
import ui_common as C  # noqa: E402

LOW, HIGH = "Pat Lee", "Ana Lead"
SECRET = "sealed cabinet"
Q = "What is stored for the zebra vault rotation?"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Persist(unittest.TestCase):
    def setUp(self):
        S.THREADS.clear()
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": HIGH}}))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\nvisit dates\n")
        write(os.path.join(self.kb, "db", "PETS.md"),
              '# PETS\n\nThe pets table has a foreign key to owners. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))
        self.pat = C.Ctx(self.kb, "tok", LOW)
        self.sam = C.Ctx(self.kb, "tok", "Sam Roe")

    def tearDown(self):
        S.THREADS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def restart(self):
        S.THREADS.clear()               # what a new server process starts with

    def file_of(self, user):
        return chat_store.path(self.kb, user)

    # ---- survives a restart ----------------------------------------------------------------------
    def test_thread_survives_a_restart(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        aid = S.thread(self.pat)[0]
        self.restart()
        self.assertEqual(S.thread(self.pat), [aid])
        html = S.chat_view(self.pat, {})
        self.assertIn("Which table does pets reference?", html)
        self.assertIn("Confidence:", html)

    def test_follow_up_still_works_after_a_restart(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        self.restart()
        self.assertEqual(S.follow_direction(self.pat, "and who owns it?"), "pets reference")

    def test_clear_removes_the_stored_thread_too(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        S.act_chat_clear(self.pat, {})
        self.restart()
        self.assertEqual(S.thread(self.pat), [])
        self.assertEqual(len(answers.all_asks(self.kb)), 1)         # the ask record stays in Ask

    def test_rating_reask_joins_the_stored_thread(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        aid = S.thread(self.pat)[0]
        S.act_chat_rate(self.pat, {"id": aid, "rating": "down", "why": "wrong", "redirect": "look at PETS.md"})
        self.restart()
        self.assertEqual(len(S.thread(self.pat)), 2)

    # ---- per user ---------------------------------------------------------------------------------
    def test_users_are_kept_apart_on_disk_and_in_view(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        S.act_chat_ask(self.sam, {"question": "Which table does visits reference?"})
        self.assertNotEqual(self.file_of(LOW), self.file_of("Sam Roe"))
        self.restart()
        self.assertEqual(len(S.thread(self.pat)), 1)
        self.assertNotIn("visits reference", S.chat_view(self.pat, {}))
        self.assertNotIn("pets reference", S.chat_view(self.sam, {}))
        self.assertEqual(S.thread(C.Ctx(self.kb, "tok", "pat  LEE")), S.thread(self.pat))   # same person, any case or spacing

    def test_a_record_for_another_user_in_the_file_is_ignored(self):
        S.act_chat_ask(self.sam, {"question": "Which table does visits reference?"})
        sam_id = S.thread(self.sam)[0]
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        with open(self.file_of(LOW), "a", encoding="utf-8", newline="\n") as fh:      # a hand-edited / copied file
            fh.write(json.dumps({"v": 1, "user": "sam roe", "thread": "main", "id": sam_id, "at": "x"}) + "\n")
        self.restart()
        self.assertNotIn(sam_id, S.thread(self.pat))
        # and an ask id that belongs to someone else is never shown, even if it got into the file under the right name
        with open(self.file_of(LOW), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"v": 1, "user": "pat lee", "thread": "main", "id": sam_id, "at": "x"}) + "\n")
        self.restart()
        self.assertNotIn("visits reference", S.chat_view(self.pat, {}))

    # ---- what is stored ---------------------------------------------------------------------------
    def test_only_ids_are_stored_never_text(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference? password hunter2"})
        raw = slurp(self.file_of(LOW))
        rec = json.loads(raw.splitlines()[0])
        self.assertEqual(sorted(rec), ["at", "id", "thread", "user", "v"])
        for word in ("Which table", "pets", "hunter2", "foreign key", "owners"):
            self.assertNotIn(word, raw)

    def test_file_is_local_git_ignored_and_not_kb_content(self):
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        folder = os.path.dirname(self.file_of(LOW))
        self.assertEqual(os.path.relpath(folder, self.kb).replace(os.sep, "/"), ".metis/chat")
        self.assertEqual(slurp(os.path.join(folder, ".gitignore")).strip(), "*")
        self.assertTrue(any(p.startswith(".metis/chat/") for p in kb_manifest.LOCAL))
        kb_manifest.main(["generate", self.kb])
        self.assertNotIn(".metis/chat", slurp(os.path.join(self.kb, "KNOWLEDGE-MANIFEST.yaml")))
        self.assertEqual(kb_manifest.main(["validate", self.kb]), 0)

    def test_lock_does_not_govern_the_chat_file(self):
        kb_gate.lock(self.kb, HIGH)
        S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        self.assertEqual(kb_gate.status(self.kb)["problems"], [])
        self.restart()
        self.assertEqual(len(S.thread(self.pat)), 1)

    # ---- caps and atomic write --------------------------------------------------------------------
    def test_caps_messages_per_thread_and_threads_per_user(self):
        for i in range(chat_store.MAX_MESSAGES + 30):
            chat_store.add(self.kb, LOW, "A-%04d" % i)
        got = chat_store.load(self.kb, LOW)
        self.assertEqual((len(got), got[0], got[-1]), (200, "A-0030", "A-0229"))
        self.assertEqual(len(slurp(self.file_of(LOW)).splitlines()), 200)
        for n in range(chat_store.MAX_THREADS + 5):
            chat_store.add(self.kb, "Many Threads", "A-%04d" % n, thread="t%d" % n)
        t = chat_store.threads(self.kb, "Many Threads")
        self.assertEqual(len(t), 50)
        self.assertNotIn("t0", t)
        self.assertIn("t54", t)

    def test_write_is_atomic(self):
        chat_store.add(self.kb, LOW, "A-0001")
        before = slurp(self.file_of(LOW))
        with mock.patch("chat_store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                chat_store.add(self.kb, LOW, "A-0002")
        self.assertEqual(slurp(self.file_of(LOW)), before)                    # the old file is intact
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.file_of(LOW))) if n.endswith(".tmp")], [])
        chat_store.add(self.kb, LOW, "A-0003")
        self.assertEqual(chat_store.load(self.kb, LOW), ["A-0001", "A-0003"])

    def test_damaged_lines_are_skipped_and_bad_values_refused(self):
        chat_store.add(self.kb, LOW, "A-0001")
        with open(self.file_of(LOW), "a", encoding="utf-8", newline="\n") as fh:
            fh.write("not json\n" + json.dumps({"v": 1, "user": "pat lee", "thread": "main", "id": "../x", "at": ""}) + "\n")
        self.assertEqual(chat_store.load(self.kb, LOW), ["A-0001"])
        for bad in ("x", "A-", "A-1/../2"):
            with self.assertRaises(ValueError):
                chat_store.add(self.kb, LOW, bad)
        with self.assertRaises(ValueError):
            chat_store.add(self.kb, "   ", "A-0001")

    def test_chat_still_works_when_the_file_cannot_be_written(self):
        with mock.patch("chat_store.os.replace", side_effect=OSError("read-only")):
            S.act_chat_ask(self.pat, {"question": "Which table does pets reference?"})
        self.assertEqual(len(S.thread(self.pat)), 1)

    def test_show_limit_is_still_twenty(self):
        for i in range(S.MAX_TURNS + 5):
            S.add_turn(self.pat, "A-%04d" % i)
        self.restart()
        t = S.thread(self.pat)
        self.assertEqual((len(t), t[0], t[-1]), (20, "A-0005", "A-0024"))
        self.assertEqual(len(chat_store.load(self.kb, LOW)), 25)               # more is kept than shown


class Labels(unittest.TestCase):
    """Claim-label enforcement stays in force for restored turns."""

    def setUp(self):
        S.THREADS.clear()
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": HIGH}}))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "ops.txt"), "30 days vault\n")
        write(os.path.join(self.kb, "context", "ops.md"),
              '# Ops\n\n- Invoices are settled within 30 days of receipt. [E: file:ops.txt "30 days"]\n'
              '- The zebra vault rotation key is stored in the %s. [E: file:ops.txt "vault"]\n' % SECRET)
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))

    def tearDown(self):
        S.THREADS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def label_the_line(self):
        p = os.path.join(self.kb, "context", "ops.md")
        write(p, slurp(p).replace('"vault"]', '"vault"] {sensitivity: restricted}'))
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"owners": {"kb_owner": HIGH}, "labels": {"default_sensitivity": "public"}}))

    def test_a_turn_stored_before_a_label_existed_is_filtered_when_restored(self):
        low = C.Ctx(self.kb, "tok", LOW)
        S.act_chat_ask(low, {"question": Q})
        self.assertIn(SECRET, S.chat_view(low, {}))                  # no labels yet: the old answer quoted it
        self.label_the_line()
        S.THREADS.clear()
        html = S.chat_view(low, {})
        self.assertNotIn(SECRET, html)
        self.assertIn("withheld by label", html)
        high = C.Ctx(self.kb, "tok", HIGH)
        S.act_chat_ask(high, {"question": Q})
        self.assertIn(SECRET, S.chat_view(high, {}))                 # a cleared reader still sees it

    def test_no_labels_means_text_unchanged(self):
        low = C.Ctx(self.kb, "tok", LOW)
        S.act_chat_ask(low, {"question": Q})
        text = answers.answer_text(self.kb, answers.get(self.kb, S.thread(low)[0]))
        self.assertEqual(S.visible_answer(low, text), (text, 0))

    def test_files_page_view_withholds_labelled_lines(self):
        import views
        self.label_the_line()
        low = views.files(C.Ctx(self.kb, "tok", LOW), {"page": "context/ops.md"})
        self.assertNotIn(SECRET, low)
        self.assertIn("settled within 30 days", low)
        self.assertIn("1 line withheld by label", low)
        self.assertIn(SECRET, views.files(C.Ctx(self.kb, "tok", HIGH), {"page": "context/ops.md"}))

    def test_files_page_view_unchanged_without_labels(self):
        import views
        for who in ("", LOW, HIGH):
            html = views.files(C.Ctx(self.kb, "tok", who), {"page": "context/ops.md"})
            self.assertIn(SECRET, html)
            self.assertNotIn("withheld by label", html)

    def test_visible_answer_fails_closed(self):
        with mock.patch("claim_labels.Viewer", side_effect=RuntimeError("boom")):
            self.assertEqual(S.visible_answer(C.Ctx(self.kb, "tok", LOW), "- x [E: kb:context/ops.md:3]\n"), ("", 1))


if __name__ == "__main__":
    unittest.main()
