"""capture.py: a pasted note becomes a sourced page; secrets and unquotable lines are refused; a closed gate stages the page."""
import os
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import capture  # noqa: E402
import kb_gate  # noqa: E402
import verify_kb  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Capture(unittest.TestCase):
    def setUp(self):
        self.kb = os.path.join(tempfile.mkdtemp(), "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"product": {"name": "S"}, "owners": {"kb_owner": "Lena Lead"}}))

    def run_add(self, text="Refunds over 500 need approval.\nThe batch runs at 02:00 UTC.", **kw):
        args = dict(title="Refund notes", by="Asha", source="Slack #payments, 2026-01-02")
        args.update(kw)
        return capture.add(self.kb, args["title"], args["by"], args["source"], text)

    def test_writes_page_and_evidence_that_verify(self):
        r = self.run_add()
        self.assertEqual(r["lines"], 2)
        self.assertIsNone(r["staged_in"])
        self.assertTrue(os.path.isfile(os.path.join(self.kb, r["evidence"])))
        with open(os.path.join(self.kb, r["page"]), encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn('- Refunds over 500 need approval. [E: file:', page)
        self.assertIn("given by Asha", page)
        self.assertIn("Slack #payments", page)
        rep = verify_kb.Checker(self.kb).run()
        self.assertEqual(rep["problems"], [])

    def test_quote_with_unquotable_characters(self):
        r = self.run_add(text='He said "yes"; then left [ok] for now')
        with open(os.path.join(self.kb, r["page"]), encoding="utf-8") as fh:
            page = fh.read()
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])
        self.assertNotIn('""', page)

    def test_second_capture_with_same_title_does_not_overwrite(self):
        a = self.run_add()
        b = self.run_add()
        self.assertNotEqual(a["page"], b["page"])
        self.assertNotEqual(a["evidence"], b["evidence"])
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])

    def test_secret_is_refused_and_nothing_written(self):
        with self.assertRaises(capture.CaptureError) as cm:
            self.run_add(text="ok line\npassword = hunter2hunter2")
        self.assertIn("line 2", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context")))
        self.assertFalse(os.path.exists(os.path.join(self.kb, "_EVIDENCE")))

    def test_missing_fields_and_empty_text(self):
        for kw in ({"title": " "}, {"by": ""}, {"source": ""}):
            with self.assertRaises(capture.CaptureError):
                self.run_add(**kw)
        with self.assertRaises(capture.CaptureError):
            self.run_add(text="  \n\n")

    def test_unquotable_line_refused(self):
        with self.assertRaises(capture.CaptureError):
            self.run_add(text='";;]"')

    def test_closed_gate_stages_the_page(self):
        write(os.path.join(self.kb, "context", "a.md"), "# A\n\n- fact [E: file:x.txt]\n")
        write(os.path.join(self.kb, "_EVIDENCE", "files", "x.txt"), "fact\n")
        kb_gate.lock(self.kb, "Lena Lead")
        r = self.run_add()
        self.assertTrue(r["staged_in"])
        self.assertFalse(os.path.exists(os.path.join(self.kb, r["page"])))
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "_PENDING", r["staged_in"], r["page"])))
        self.assertTrue(os.path.isfile(os.path.join(self.kb, r["evidence"])))

    def test_cli(self):
        self.assertEqual(capture.main(["add", self.kb, "--title", "T", "--by", "A", "--source", "mail", "--text", "Hello world line"]), 0)
        self.assertEqual(capture.main(["add", self.kb, "--title", "T", "--by", "A", "--source", "mail", "--text", "key=AKIAABCDEFGHIJKLMNOP"]), 1)


if __name__ == "__main__":
    unittest.main()
