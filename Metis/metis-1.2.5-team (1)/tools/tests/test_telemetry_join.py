import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import feedback  # noqa: E402
import telemetry  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"}}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def answer(*files):
    return "# A\n\n" + "".join('- Line. [E: kb:%s "paid within 30 days"]\n' % f for f in files)


class Join(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "x\n")
        for p in ("context/a.md", "context/b.md", "context/c.md"):
            write(os.path.join(self.kb, p), "# T\n\n- Claims are paid within 30 days. [E: file:r.txt]\n")
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def rate(self, files, rating, **kw):
        self.n += 1
        p = os.path.join(self.kb, "ans%d.md" % self.n)
        write(p, answer(*files))
        return feedback.record(self.kb, p, "How fast are claims paid? %d" % self.n, "Pat Lee", rating, **kw)

    def test_no_feedback_means_empty_sections_and_unchanged_usage_shape(self):
        telemetry.record(self.kb, "answer", ["context/a.md"])
        rep = telemetry.report(self.kb)
        self.assertEqual(rep["files_used"]["context/a.md"], {"packs": 0, "answers": 1})
        self.assertEqual((rep["feedback"], rep["look_first"], rep["rated_but_not_used"]), ({}, [], []))

    def test_likes_and_dislikes_by_cited_file_beside_use(self):
        telemetry.record(self.kb, "answer", ["context/a.md"])
        telemetry.record(self.kb, "pack", ["context/a.md", "context/b.md"])
        self.rate(["context/a.md", "context/b.md"], "up")
        self.rate(["context/a.md"], "down", why="old", redirect="look at the batch job")
        self.rate(["context/a.md"], "down", why="old", redirect="look at the other job")
        fb = telemetry.report(self.kb)["feedback"]
        self.assertEqual(fb["context/a.md"], {"up": 1, "down": 2, "declined": 0, "used": 2})
        self.assertEqual(fb["context/b.md"], {"up": 1, "down": 0, "declined": 0, "used": 1})
        self.assertEqual(telemetry.report(self.kb)["look_first"], ["context/a.md"])

    def test_a_declined_dislike_is_not_a_mark_against_the_page(self):
        f = self.rate(["context/b.md"], "down", why="no", redirect="look elsewhere")
        reg = feedback.load(self.kb)
        reg["feedback"][0]["status"] = "declined"
        feedback.save(self.kb, reg)
        rep = telemetry.report(self.kb)
        self.assertEqual(rep["feedback"]["context/b.md"]["declined"], 1)
        self.assertEqual(rep["feedback"]["context/b.md"]["down"], 0)
        self.assertEqual(rep["look_first"], [])
        self.assertEqual(f["id"], "F-0001")

    def test_rated_but_never_recorded_as_used_is_listed(self):
        self.rate(["context/c.md"], "up")
        self.assertEqual(telemetry.report(self.kb)["rated_but_not_used"], ["context/c.md"])

    def test_cli_prints_the_join(self):
        self.rate(["context/a.md"], "down", why="old", redirect="look at the batch job")
        self.assertEqual(telemetry.main(["report", self.kb]), 0)


if __name__ == "__main__":
    unittest.main()
