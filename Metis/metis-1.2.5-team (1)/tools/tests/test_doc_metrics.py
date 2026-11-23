import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import doc_metrics as D  # noqa: E402

M = {"tests": 100, "screens": 5, "tools": 7, "skills": 3}


class DocMetrics(unittest.TestCase):
    def setUp(self):
        self.docs = tempfile.mkdtemp()
        self.path = os.path.join(self.docs, "a.md")

    def tearDown(self):
        shutil.rmtree(self.docs)

    def put(self, text):
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def get(self):
        with open(self.path, encoding="utf-8", newline="") as fh:
            return fh.read()

    def test_fresh_block_passes_and_stale_fails(self):
        self.put("x\n%s\ny\n" % D.block(M))
        stale, _ = D.check(M, self.docs)
        self.assertEqual([p for p in stale if p == self.path], [])
        stale, _ = D.check(dict(M, tests=101), self.docs)
        self.assertIn(self.path, stale)

    def test_write_updates_block_and_keeps_crlf(self):
        old = D.block(dict(M, tests=1)).replace("\n", "\r\n")
        self.put("head\r\n%s\r\ntail\r\n" % old)
        D.write(M, self.docs)
        text = self.get()
        self.assertIn("Tests discovered: 100", text)
        self.assertNotIn("\n", text.replace("\r\n", ""))
        self.assertTrue(text.startswith("head\r\n") and text.endswith("tail\r\n"))

    def test_loose_numbers_are_advice_only(self):
        self.put("Baseline 954 tests and 27 screens.\n")
        stale, advice = D.check(M, self.docs)
        self.assertEqual([p for p in stale if p == self.path], [])
        self.assertTrue(any("954 tests" in a for a in advice))
        self.assertTrue(any("27 screens" in a for a in advice))

    def test_count_reads_the_code(self):
        m = D.count()
        self.assertGreater(m["tests"], 1000)
        self.assertGreater(m["screens"], 20)
        self.assertGreater(m["skills"], 50)


if __name__ == "__main__":
    unittest.main()
