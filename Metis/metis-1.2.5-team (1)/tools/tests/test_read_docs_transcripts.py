"""Transcript (.vtt/.srt) and chat (Slack/Teams .json) readers in read_docs.py. Built from small hand-written fixtures, not real exports."""
import json
import os
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import read_docs  # noqa: E402
import verify_kb  # noqa: E402

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
<v Asha>Claims are paid within 30 days.</v>

00:00:01.500 --> 00:00:05.000
Second cue in the same second.

1
01:02:03.456 --> 01:02:06.000
<v Ben>Refunds need approval.
"""

SRT = """1
00:00:10,200 --> 00:00:12,000
Hello there.

2
00:01:23,456 --> 00:01:25,000
Limit is <i>500</i>.
"""

SLACK = [
    {"user": "U1", "ts": "1700000000.000100", "text": "deploy at noon", "user_profile": {"real_name": "Asha"}},
    {"user": "U2", "ts": "1700000100.000200", "text": ""},
    {"user": "U2", "ts": "1700000200.000300", "text": "ok"},
]

TEAMS = {"value": [
    {"createdDateTime": "2026-01-02T10:00:00Z", "from": {"user": {"displayName": "Ben"}},
     "body": {"contentType": "html", "content": "<p>Use the <b>new</b> queue</p>"}},
]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Transcripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def p(self, name, text):
        path = os.path.join(self.tmp, name)
        write(path, text)
        return path

    def test_cue_place(self):
        self.assertEqual(read_docs.cue_place("00:01:23.456"), "t00:01:23")
        self.assertEqual(read_docs.cue_place("00:01:23,456"), "t00:01:23")
        self.assertEqual(read_docs.cue_place("01:23.456"), "t00:01:23")
        self.assertIsNone(read_docs.cue_place("nonsense"))

    def test_vtt_places_speakers_and_duplicates(self):
        got = list(read_docs.transcript(self.p("a.vtt", VTT)))
        self.assertEqual(got[0], ("t00:00:01", "Asha: Claims are paid within 30 days."))
        self.assertEqual(got[1][0], "t00:00:01-2")
        self.assertEqual(got[2], ("t01:02:03", "Ben: Refunds need approval."))
        self.assertEqual(len({g[0] for g in got}), 3)

    def test_srt_strips_markup(self):
        got = dict(read_docs.transcript(self.p("a.srt", SRT)))
        self.assertEqual(got["t00:00:10"], "Hello there.")
        self.assertEqual(got["t00:01:23"], "Limit is 500.")

    def test_kind(self):
        self.assertEqual(read_docs.kind(self.p("a.vtt", VTT)), "transcript")
        self.assertEqual(read_docs.kind(self.p("a.srt", SRT)), "transcript")
        self.assertEqual(read_docs.kind(self.p("s.json", json.dumps(SLACK))), "chat")
        self.assertEqual(read_docs.kind(self.p("t.json", json.dumps(TEAMS))), "chat")
        self.assertEqual(read_docs.kind(self.p("cfg.json", json.dumps({"a": 1}))), "text")
        self.assertEqual(read_docs.kind(self.p("list.json", json.dumps([1, 2]))), "text")
        self.assertEqual(read_docs.kind(self.p("bad.json", "{not json")), "text")

    def test_slack_messages(self):
        got = list(read_docs.chat(self.p("s.json", json.dumps(SLACK))))
        self.assertEqual([g[0] for g in got], ["msg1", "msg3"])
        self.assertTrue(got[0][1].endswith("Asha: deploy at noon"))
        self.assertIn("2023-11-14", got[0][1])
        self.assertTrue(got[1][1].endswith("U2: ok"))

    def test_teams_messages_strip_html(self):
        got = list(read_docs.chat(self.p("t.json", json.dumps(TEAMS))))
        self.assertEqual(got, [("msg1", "2026-01-02T10:00:00Z Ben: Use the new queue")])

    def test_extract_and_verify_quote(self):
        scratch = os.path.join(self.tmp, "scratch")
        kb = os.path.join(self.tmp, "repo", "kb")
        write(os.path.join(kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"product": {"name": "S"}}))
        vtt = self.p("Standup.vtt", VTT)
        read_docs.cmd_extract(scratch, [vtt], "tester")
        txt = [f for f in os.listdir(scratch) if f.endswith(".txt")]
        self.assertEqual(len(txt), 1)
        with open(os.path.join(scratch, txt[0]), encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("[t00:00:01] Asha: Claims are paid within 30 days.", body)
        self.assertTrue(read_docs.DOC_TAG.search('[E: doc:standup.vtt#t00:00:01 "Claims are paid within 30 days."]')
                        or read_docs.DOC_TAG.search('[E: doc:Standup.vtt#t00:00:01 "Claims are paid within 30 days."]'))


if __name__ == "__main__":
    unittest.main()
