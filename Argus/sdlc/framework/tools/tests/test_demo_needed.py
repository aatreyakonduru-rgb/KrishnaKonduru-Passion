"""DEMO-NEEDED demos: which stories, file names, captions, the story page and the dry-run publish."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import demo_needed as D  # noqa: E402


def issue(key="ACME-1", links=(), ac="* Shows the total\n* Saves the change"):
    return {"key": key, "id": "1", "fields": {
        "summary": "Funding chart", "status": {"name": "In Review"}, D.EPIC_FIELD: "ACME-100", D.AC_FIELD: ac,
        "issuelinks": list(links)}}


def defect(key, status, link="Blocks"):
    return {"type": {"name": link}, "outwardIssue": {"key": key, "fields": {
        "issuetype": {"name": "Defect"}, "status": {"name": status}, "summary": "bug"}}}


class FindTest(unittest.TestCase):
    def test_released_stories_are_not_searched(self):
        jql = D.search_jql()
        self.assertIn('labels = "DEMO-NEEDED"', jql)
        for s in ("Ready For Release", "Closed", "Abandoned"):
            self.assertIn('"%s"' % s, jql)

    def test_acceptance_criteria_split_per_bullet_number_or_ac_line(self):
        self.assertEqual([a["text"] for a in D.split_acs("* One\n* Two\n  more")], ["One", "Two more"])
        self.assertEqual([a["id"] for a in D.split_acs("1. A\n2) B\nAC-3: C")], ["AC-1", "AC-2", "AC-3"])
        self.assertEqual(D.split_acs(""), [])

    def test_only_blocks_and_linked_cnr_defects_count(self):
        s = D.story_from(issue(links=[defect("ACME-9", "Closed"), defect("ACME-8", "Open", "Linked CNR"),
                                      defect("ACME-7", "Closed", "Cloners")]))
        self.assertEqual([d["key"] for d in s["defects"]], ["ACME-9", "ACME-8"])

    def test_actions(self):
        s = D.story_from(issue(links=[defect("ACME-9", "Closed"), defect("ACME-8", "Open")]))
        self.assertEqual(D.decide(s, {"open": 0}, [])["action"], "skip")
        self.assertEqual(D.decide(s, {"error": "x"}, [])["action"], "skip")
        self.assertEqual(D.decide(s, {"open": 1}, []), {"action": "v1", "version": 1, "defects": []})
        self.assertEqual(D.decide(s, {"open": 1}, [{"version": 1, "defects_fixed": []}]),
                         {"action": "v2", "version": 2, "defects": ["ACME-9"]})
        done = [{"version": 1, "defects_fixed": []}, {"version": 2, "defects_fixed": ["ACME-9"]}]
        self.assertEqual(D.decide(s, {"open": 1}, done)["action"], "skip")

    def test_file_and_page_names(self):
        self.assertEqual(D.ac_file("ACME-1", "AC-1", 1), "ACME-1_AC1_demo_v1.mp4")
        self.assertEqual(D.ac_file("ACME-1", "AC-2", 2, ["ACME-9", "ACME-8"]), "ACME-1_AC2_demo_v2_after-ACME-9-ACME-8-fix.mp4")
        self.assertEqual(D.full_file("ACME-1", 1), "ACME-1_demo_v1_full.mp4")
        self.assertEqual((D.epic_title("ACME-100"), D.story_title("ACME-1"), D.ac_title("ACME-1", "AC-3")),
                         ("ACME-100", "ACME-1", "ACME-1_AC3_demo"))

    def test_a_title_used_elsewhere_gets_demos_added(self):
        conf = D.Http("https://conf", "X", True)
        elsewhere = {"id": "9", "title": "ACME-1", "ancestors": [{"id": "1"}]}
        with mock.patch.object(D, "find_page", side_effect=lambda c, t: elsewhere if t == "ACME-1" else None), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            page = D.place(conf, "ACME-1", "55", "<p/>")
        self.assertEqual(page["title"], "ACME-1 (demos)")
        self.assertIn("create page 'ACME-1 (demos)' under 55", out.getvalue())
        mine = {"id": "7", "title": "ACME-1", "ancestors": [{"id": "55"}]}
        with mock.patch.object(D, "find_page", return_value=mine):
            self.assertIs(D.place(conf, "ACME-1", "55", "<p/>"), mine)


class CaptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = mock.patch.object(D, "HOME", self.tmp.name)
        self.home.start()
        d = D.run_dir("ACME-1", 1)
        os.makedirs(d)
        self.top, self.bottom = os.path.join(d, "t.txt"), os.path.join(d, "b.txt")
        D.save_run({"key": "ACME-1", "version": 1, "t0": 0, "captions": [self.top, self.bottom], "results": [],
                    "defects_fixed": [], "video": os.path.join(d, "v.mp4")})

    def tearDown(self):
        self.home.stop()
        self.tmp.cleanup()

    def caption(self, *argv):
        self.assertEqual(D.main(["caption"] + list(argv) + ["--key", "ACME-1", "--version", "1", "--hold", "0"]), 0)

    def test_step_then_result_shows_and_logs_each_ac(self):
        self.caption("step", "--ac", "AC-1", "--title", "Shows the total", "--doing", "open Funding", "--checking", "total")
        self.assertIn("AC-1: Shows the total", open(self.top).read())
        self.assertIn("Checking: total", open(self.bottom).read())
        self.caption("result", "--ac", "AC-1", "--result", "failed", "--note", "total missing")
        self.assertIn("AC-1 FAILED: total missing", open(self.bottom).read())
        run = D.load_run("ACME-1", 1)
        self.assertEqual([(r["id"], r["result"], r["text"]) for r in run["results"]], [("AC-1", "failed", "Shows the total")])

    def test_ffmpeg_draws_both_caption_files_and_does_not_expand_text(self):
        cmd = D.ffmpeg_command(":0", "3200x2400", "/t", "/b", "/o.mp4")
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("textfile=/t:reload=1:expansion=none", vf)
        self.assertIn("textfile=/b:reload=1:expansion=none", vf)
        self.assertEqual(cmd[-1], "/o.mp4")


class PageTest(unittest.TestCase):
    V1 = {"version": 1, "finished": "2026-10-14T10:00:00Z", "commit": "abc", "pr": "PR 1", "defects_fixed": [],
          "results": [{"id": "AC-1", "text": "Shows <total>", "result": "failed", "note": "no total"},
                      {"id": "AC-2", "text": "Saves", "result": "passed", "note": ""}],
          "videos": {"AC-1": "ACME-1_AC1_demo_v1.mp4", "AC-2": "ACME-1_AC2_demo_v1.mp4"}, "full": "ACME-1_demo_v1_full.mp4",
          "pages": {"AC-1": "ACME-1_AC1_demo", "AC-2": "ACME-1_AC2_demo"}}
    V2 = {"version": 2, "finished": "2026-10-20T10:00:00Z", "commit": "def", "pr": "PR 1", "defects_fixed": ["ACME-9"],
          "results": [{"id": "AC-1", "text": "Shows <total>", "result": "passed", "note": ""},
                      {"id": "AC-2", "text": "Saves", "result": "passed", "note": ""}],
          "videos": {"AC-1": "ACME-1_AC1_demo_v2_after-ACME-9-fix.mp4", "AC-2": "ACME-1_AC2_demo_v2_after-ACME-9-fix.mp4"},
          "full": "ACME-1_demo_v2_full_after-ACME-9-fix.mp4", "pages": {"AC-1": "ACME-1_AC1_demo", "AC-2": "ACME-1_AC2_demo"}}
    STORY = {"key": "ACME-1", "summary": "S"}

    def test_ac_page_has_a_row_per_version_and_its_videos_newest_first(self):
        body = D.ac_body(self.STORY, "AC-1", [self.V1, self.V2])
        self.assertIn("Shows &lt;total&gt;", body)
        self.assertIn("failed → passed", body)
        self.assertLess(body.index("ACME-1_AC1_demo_v2_after-ACME-9-fix.mp4"), body.index("ACME-1_AC1_demo_v1.mp4"))
        self.assertNotIn("AC2_demo", body)

    def test_story_page_links_each_criterion_page(self):
        body = D.story_body(self.STORY, [self.V1, self.V2])
        self.assertIn('ri:content-title="ACME-1_AC1_demo"', body)
        self.assertIn('ri:content-title="ACME-1_AC2_demo"', body)
        self.assertIn("Change since v1", body)
        self.assertIn("failed → passed", body)
        self.assertEqual(body.count('ac:name="multimedia"'), 2)
        self.assertNotIn("Change since v1", D.story_body(self.STORY, [self.V1]))

    def test_jira_comment_links_and_counts(self):
        text = D.jira_comment({"key": "ACME-1"}, dict(self.V2, commit="def0123456789"), "https://x/page")
        self.assertIn("Demo v2", text)
        self.assertIn("after the fix for ACME-9", text)
        self.assertIn("2 passed, 0 failed, 0 not run", text)


class PublishDryRunTest(unittest.TestCase):
    def test_dry_run_writes_nothing_and_never_touches_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "ACME-1_demo_v1_full.mp4")
            part = os.path.join(tmp, "ACME-1_AC1_demo_v1.mp4")
            for f in (video, part):
                with open(f, "wb") as fh:
                    fh.write(b"0" * 10)
            run = {"key": "ACME-1", "version": 1, "video": video, "defects_fixed": [], "commit": "abc",
                   "results": [{"id": "AC-1", "text": "A", "result": "passed", "note": "", "at_s": 3}]}
            conf, jira = D.Http("https://conf", "X", True), D.Http("https://jira", "Y", True)
            conf.token = jira.token = "t"
            sent = []
            with mock.patch.object(D.Http, "call", side_effect=lambda *a, **k: sent.append(a) or {"results": []}), \
                    mock.patch.object(D, "split_by_ac", return_value={"AC-1": part}):
                out_buf = io.StringIO()
                with contextlib.redirect_stdout(out_buf):
                    D.publish(D.story_from(issue()), run, conf, jira)
            printed = out_buf.getvalue()
            self.assertTrue(all(a[0] == "GET" for a in sent), sent)
            for text in ("create page 'ACME-100'", "create page 'ACME-1' under", "create page 'ACME-1_AC1_demo'",
                         "attach ACME-1_AC1_demo_v1.mp4", "attach ACME-1_demo_v1_full.mp4", "attach ACME-1_demo_v1.json",
                         "update ACME-1_AC1_demo with v1", "update ACME-1 with v1", "/rest/api/2/issue/ACME-1/comment"):
                self.assertIn(text, printed)
            self.assertNotIn("labels", printed)
            saved = json.load(open(os.path.join(tmp, "ACME-1_demo_v1.json")))
            self.assertEqual(saved["videos"], {"AC-1": "ACME-1_AC1_demo_v1.mp4"})

    def test_unfinished_ac_blocks_publish(self):
        run = {"key": "ACME-1", "version": 1, "video": "/nope", "results": [{"id": "AC-1", "result": "running"}]}
        with self.assertRaises(D.DemoError):
            D.publish({"key": "ACME-1"}, run, None, None)


if __name__ == "__main__":
    unittest.main()
