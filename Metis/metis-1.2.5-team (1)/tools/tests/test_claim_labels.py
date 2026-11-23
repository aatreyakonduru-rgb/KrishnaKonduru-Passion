import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import claim_labels as L  # noqa: E402
import verify_kb  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead", "roles": {"data analyst": "Dee Data", "dev": "Raj Dev"}},
           "gate": {"teams": [{"name": "Payments", "owns": ["payments/*"], "approvers": ["Pia Pay"]}]},
           "labels": {"restricted_folders": ["restricted", "payments/secure"]}}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


PAGE = """---
title: Ops
env: prod
sensitivity: internal
---
# Ops

- Pay in 30 days [E: file:ops.txt "30 days"]
- Vault path is mounted at /vault [E: file:ops.txt "vault"] {env: uat; sensitivity: confidential} {valid-from: 2026-01-01}
- Deploy key is rotated monthly [E: file:ops.txt "rotated"] {sensitivity: restricted}

## Credentials {sensitivity: restricted}

- service login is held by ops [E: file:ops.txt "login"]
- connection is set up as described [E: file:ops.txt "connection"] {sensitivity: public}

# Contacts

- Reach support at help@example.com [E: file:ops.txt "support"]
- Token: password = Hunter2hunter [E: file:ops.txt "Hunter"]
"""


class Labels(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "ops.txt"), "30 days vault rotated login connection support Hunter\n")
        write(os.path.join(self.kb, "context", "ops.md"), PAGE)
        write(os.path.join(self.kb, "context", "plain.md"), '# Plain\n\n- Hello [E: file:ops.txt "30 days"]\n')

    def tearDown(self):
        rmtree(self.d)

    def line(self, n, page="context/ops.md"):
        return L.analyse_page(self.kb, page)["lines"].get(n)

    def test_verify_kb_ignores_labels(self):
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])

    def test_own_labels_and_file_default(self):
        a = L.analyse_page(self.kb, "context/ops.md")
        self.assertEqual((a["file"]["sensitivity"], a["file"]["env"]), ("internal", "prod"))
        self.assertIsNone(a["lines"].get(8))  # plain line at the page level
        self.assertEqual((a["lines"][9]["sensitivity"], a["lines"][9]["env"]), ("confidential", "uat"))
        self.assertEqual(a["lines"][10]["sensitivity"], "restricted")

    def test_heading_label_covers_following_lines_until_next_heading(self):
        self.assertEqual(self.line(14)["sensitivity"], "restricted")
        self.assertEqual(self.line(14)["own"], {})
        self.assertIsNone(self.line(18))                         # blank line under the next heading is back at page level
        self.assertNotEqual(self.line(19)["sensitivity"], "restricted")

    def test_secret_forced_to_restricted_and_personal_to_confidential(self):
        sec = self.line(20)
        self.assertEqual((sec["sensitivity"], sec["forced_level"]), ("restricted", "restricted"))
        self.assertIn("credential", sec["forced_by"])
        self.assertEqual(self.line(19)["sensitivity"], "confidential")
        self.assertIn("email address", self.line(19)["forced_by"])

    def test_scan_and_report(self):
        rows = L.scan(self.kb)
        by_line = {r["line"]: r for r in rows}
        self.assertEqual(by_line[20]["source"], "secret")
        self.assertEqual(by_line[19]["source"], "personal data")
        self.assertEqual(by_line[9]["source"], "label")
        rep = L.report(self.kb)
        # lines with their own label or forced by sensitive.py: 9 (confidential), 10, 12, 15 (public label, but the heading above is
        # restricted), 20 (secret) -> restricted; 19 (personal data) -> confidential. Line 14 only inherits, so it is not counted.
        self.assertEqual(rep["by_sensitivity"]["restricted"], 4)
        self.assertEqual(rep["by_sensitivity"]["confidential"], 2)
        self.assertEqual(rep["lines_labelled"], 6)
        self.assertEqual(rep["by_env"], {"uat": 1})
        self.assertTrue(any(f["line"] == 20 and f["level"] == "restricted" for f in rep["forced"]))
        self.assertNotIn("Hunter2", str(rep))
        self.assertEqual(L.scan(self.kb, "context/plain.md"), [])

    def test_check_conflicts_and_restricted_outside_folder(self):
        rows = L.check(self.kb)
        kinds = {(r["path"], r["line"], r["kind"]) for r in rows}
        self.assertIn(("context/ops.md", 10, "not-in-restricted-folder"), kinds)
        self.assertIn(("context/ops.md", 20, "secret-outside-restricted"), kinds)
        self.assertIn(("context/ops.md", 9, "conflict"), kinds)       # env uat inside a prod page
        self.assertIn(("context/ops.md", 15, "conflict"), kinds)      # public under a restricted heading
        self.assertNotIn(("context/plain.md", 3, "conflict"), kinds)

    def test_check_clean_inside_restricted_folder(self):
        write(os.path.join(self.kb, "restricted", "keys.md"),
              '---\ntitle: K\nsensitivity: restricted\n---\n- Key set [E: file:ops.txt "login"] {sensitivity: restricted}\n')
        self.assertEqual([r for r in L.check(self.kb) if r["path"].startswith("restricted/")], [])

    def test_front_matter_restricted_outside_folder_flagged(self):
        write(os.path.join(self.kb, "context", "x.md"), '---\nsensitivity: restricted\n---\n- A [E: file:ops.txt "login"]\n')
        self.assertTrue(any(r["path"] == "context/x.md" and r["kind"] == "not-in-restricted-folder" and r["line"] == 0
                            for r in L.check(self.kb)))

    def test_restricted_folder_forces_page_level(self):
        write(os.path.join(self.kb, "restricted", "plain.md"), '- A [E: file:ops.txt "login"]\n')
        self.assertEqual(L.analyse_page(self.kb, "restricted/plain.md")["file"]["sensitivity"], "restricted")

    def test_invalid_label_values(self):
        write(os.path.join(self.kb, "context", "bad.md"),
              '- A [E: file:ops.txt "login"] {sensitivity: secret-ish}\n- B [E: file:ops.txt "login"] {env: two words}\n')
        probs = [r["problem"] for r in L.check(self.kb) if r["path"] == "context/bad.md"]
        self.assertTrue(any("sensitivity must be one of" in p for p in probs))
        self.assertTrue(any("env must be one short word" in p for p in probs))

    def test_clearance_by_role(self):
        c = lambda who, rel="context/ops.md": L.clearance(self.kb, who, rel)  # noqa: E731
        self.assertEqual(c("Ana Lead"), "restricted")
        self.assertEqual(c("Dee Data"), "confidential")
        self.assertEqual(c("Pia Pay", "payments/a.md"), "restricted")
        self.assertEqual(c("Pia Pay", "context/ops.md"), "confidential")
        self.assertEqual(c("Stranger"), "internal")
        self.assertEqual(c(""), "public")
        self.assertEqual(c("reader"), "public")

    def test_clearance_override_from_profile(self):
        prof = dict(PROFILE, labels=dict(PROFILE["labels"], clearance={"Stranger": "confidential"}))
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        self.assertEqual(L.clearance(self.kb, "stranger"), "confidential")

    def test_visible_lines(self):
        def got(who):
            return {n for n, _ in L.visible_lines(self.kb, "context/ops.md", who)}
        lead, member, stranger = got("Ana Lead"), got("Dee Data"), got("Stranger")
        self.assertTrue({10, 12, 14, 20} <= lead)
        self.assertEqual(member & {10, 12, 14, 20}, set())
        self.assertIn(9, member)
        self.assertNotIn(9, stranger)     # confidential
        self.assertNotIn(19, stranger)    # personal data, confidential
        self.assertIn(8, stranger)
        # numbers are the page's own, so a reader can still cite them
        self.assertEqual(dict(L.visible_lines(self.kb, "context/ops.md", "Stranger"))[8].split(" [E:")[0], "- Pay in 30 days")
        self.assertEqual(L.visible_lines(self.kb, "context/ops.md", ""), [])  # an internal page is not for the public
        self.assertEqual({n for n, _ in L.visible_lines(self.kb, "context/ops.md", "Ana Lead", max_level="internal")} & {9, 10}, set())

    def test_restricted_page_hidden_whole(self):
        write(os.path.join(self.kb, "restricted", "keys.md"), '- Key [E: file:ops.txt "login"]\n')
        self.assertEqual(L.visible_lines(self.kb, "restricted/keys.md", "Dee Data"), [])
        self.assertNotEqual(L.visible_lines(self.kb, "restricted/keys.md", "Ana Lead"), [])

    def test_visible_lines_rejects_paths_outside_kb(self):
        with self.assertRaises(L.LabelError):
            L.visible_lines(self.kb, "../x.md", "Ana Lead")

    def test_filter_one_page_and_whole_kb(self):
        write(os.path.join(self.kb, "restricted", "keys.md"), '- Key [E: file:ops.txt "login"]\n')
        out = os.path.join(self.d, "out")
        r = L.filter_kb(self.kb, out, max_level="internal", page="context/ops.md")
        self.assertEqual(r["copied"], ["context/ops.md"])
        text = open(os.path.join(out, "context", "ops.md"), encoding="utf-8").read()
        self.assertIn("Pay in 30 days", text)
        self.assertNotIn("Deploy key", text)
        self.assertNotIn("Hunter2", text)
        self.assertNotIn("help@example.com", text)
        out2 = os.path.join(self.d, "out2")
        r = L.filter_kb(self.kb, out2, role="Dee Data")
        self.assertEqual(r["dropped"], ["restricted/keys.md"])
        self.assertIn("context/plain.md", r["copied"])
        self.assertFalse(os.path.exists(os.path.join(out2, "restricted", "keys.md")))
        self.assertGreater(r["lines_removed"], 0)
        # the filtered copy no longer trips the secret scan
        text2 = open(os.path.join(out2, "context", "ops.md"), encoding="utf-8").read()
        self.assertNotIn("Hunter2", text2)

    def test_filter_guards(self):
        with self.assertRaises(L.LabelError):
            L.filter_kb(self.kb, os.path.join(self.kb, "out"), max_level="public")
        with self.assertRaises(L.LabelError):
            L.filter_kb(self.kb, os.path.join(self.d, "o"))
        with self.assertRaises(L.LabelError):
            L.filter_kb(self.kb, os.path.join(self.d, "o"), max_level="public", role="x")
        with self.assertRaises(L.LabelError):
            L.filter_kb(self.kb, os.path.join(self.d, "o"), max_level="nope")

    def test_cli(self):
        self.assertEqual(L.main(["scan", self.kb]), 0)
        self.assertEqual(L.main(["report", self.kb, "--json"]), 0)
        self.assertEqual(L.main(["check", self.kb]), 1)
        self.assertEqual(L.main(["filter", self.kb, "--out", os.path.join(self.d, "cli"), "--max", "internal"]), 0)
        self.assertEqual(L.main(["filter", self.kb, "--out", os.path.join(self.d, "cli2")]), 2)


if __name__ == "__main__":
    unittest.main()
