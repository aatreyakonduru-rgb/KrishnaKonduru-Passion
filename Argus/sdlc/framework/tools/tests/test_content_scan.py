"""content_scan.py tests: no network, no real secrets (the fake values below are inside tests/)."""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import content_scan as cs  # noqa: E402


def diff(path, *added):
    body = "".join(f"+{line}\n" for line in added)
    return f"--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(added)} @@\n{body}"


class ScanLine(unittest.TestCase):
    def test_clean_line(self):
        self.assertEqual(cs.scan_line("x = compute(1, 2)"), [])

    def test_aws_key(self):
        self.assertIn("secret/aws-access-key-id", cs.scan_line("k = AKIAIOSFODNN7EXAMPLE"))

    def test_password(self):
        self.assertIn("secret/password", cs.scan_line('password = "hunter22x"'))

    def test_token(self):
        self.assertIn("secret/token", cs.scan_line("api_key: abcdefghijklmnop1234"))

    def test_ssn_dob_member(self):
        self.assertIn("pii/ssn", cs.scan_line("SSN 123-45-6789"))
        self.assertIn("pii/dob", cs.scan_line("DOB = 1990-01-01"))
        self.assertIn("pii/member-id", cs.scan_line("MBR_ID = 1234567"))

    def test_allow_marker(self):
        self.assertEqual(cs.scan_line("k = AKIAIOSFODNN7EXAMPLE  # argus:allow AWS documented example"), [])


class ScanDiff(unittest.TestCase):
    def test_reports_path_and_line_not_value(self):
        found = cs.scan_diff(diff("src/app.py", "a = 1", "k = AKIAIOSFODNN7EXAMPLE"))
        self.assertEqual(found, [("src/app.py", 2, "secret/aws-access-key-id")])

    def test_only_added_lines(self):
        text = "--- a/x.py\n+++ b/x.py\n@@ -1 +1,0 @@\n-k = AKIAIOSFODNN7EXAMPLE\n"
        self.assertEqual(cs.scan_diff(text), [])

    def test_tests_and_fixtures_exempt(self):
        self.assertEqual(cs.scan_diff(diff("sdlc/framework/tools/tests/t.py", "k = AKIAIOSFODNN7EXAMPLE")), [])
        self.assertEqual(cs.scan_diff(diff("a/fixtures/d.json", "SSN 123-45-6789")), [])

    def test_deleted_file_ignored(self):
        text = "--- a/x.py\n+++ /dev/null\n@@ -1 +0,0 @@\n"
        self.assertEqual(cs.scan_diff(text), [])


class Main(unittest.TestCase):
    def run_main(self, argv, diff_text=""):
        err = io.StringIO()
        with mock.patch.object(cs, "git_diff", return_value=diff_text), redirect_stderr(err):
            code = cs.main(argv)
        return code, err.getvalue()

    def test_staged_clean_exits_0(self):
        self.assertEqual(self.run_main(["staged"], diff("a.py", "x = 1"))[0], 0)

    def test_staged_finding_exits_2_without_value(self):
        code, err = self.run_main(["staged"], diff("a.py", "k = AKIAIOSFODNN7EXAMPLE"))
        self.assertEqual(code, 2)
        self.assertIn("a.py:1: secret/aws-access-key-id", err)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", err)

    def test_range_passes_revs_to_git(self):
        with mock.patch.object(cs, "git_diff", return_value="") as gd:
            cs.main(["range", "origin/main..HEAD"])
        gd.assert_called_once_with(["origin/main..HEAD"])


if __name__ == "__main__":
    unittest.main()
