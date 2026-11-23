import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import kb_gate  # noqa: E402
import okf_bundle  # noqa: E402


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


class OkfBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        os.makedirs(os.path.join(self.kb, ".metis"), exist_ok=True)
        os.makedirs(os.path.join(self.kb, "context", "rules"), exist_ok=True)
        os.makedirs(os.path.join(self.kb, "db"), exist_ok=True)

        write_file(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "ClaimsService", "team": "Claims Team"},
                                   "owners": {"kb_owner": "Ana Lead"}}))

        write_file(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pay in 30 days\n")
        write_file(os.path.join(self.kb, "context", "rules", "claims.md"),
                   "# Claims Rules\n\n- Claims are paid within 30 days [E: file:rules.txt]\n")

        write_file(os.path.join(self.kb, "db", "orders.md"),
                   "# Orders Table\n\n- Table for storing orders [E: file:rules.txt]\n")

        kb_gate.lock(self.kb, "Ana Lead")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bundle_packager_creates_expected_layout(self):
        out_dir = os.path.join(self.kb, ".metis", "exports", "okf_bundle")
        bundle_path, count = okf_bundle.bundle(self.kb, out_dir)
        self.assertEqual(bundle_path, out_dir)
        self.assertGreater(count, 0)

        # Check root index.md and subfolder index.md
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "index.md")))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "context", "rules", "index.md")))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "db", "index.md")))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "okf-manifest.yaml")))

        # Check frontmatter in bundled page
        page_path = os.path.join(out_dir, "context", "rules", "claims.md")
        with open(page_path, encoding="utf-8") as fh:
            text = fh.read()
        meta, _ = okf_bundle.parse_frontmatter(text)
        self.assertIn("type", meta)
        self.assertEqual(meta.get("trust"), "verified")
        self.assertEqual(meta.get("owner_team"), "Claims Team")
        self.assertIn("file:rules.txt", meta.get("sources", []))

    def test_bundle_validation_passes_on_fresh_bundle(self):
        out_dir = os.path.join(self.kb, ".metis", "exports", "okf_bundle")
        okf_bundle.bundle(self.kb, out_dir)
        res = okf_bundle.validate(out_dir)
        self.assertTrue(res["valid"])
        self.assertEqual(len(res["problems"]), 0)
        self.assertIn("formal compliance needs the official validator", res["compliance_note"])

    def test_bundle_validation_fails_on_missing_type(self):
        out_dir = os.path.join(self.kb, ".metis", "exports", "okf_bundle")
        okf_bundle.bundle(self.kb, out_dir)

        # Remove type field from a page
        page_path = os.path.join(out_dir, "db", "orders.md")
        with open(page_path, "w", encoding="utf-8") as fh:
            fh.write("---\ntitle: Orders Table\n---\n# Orders\n")

        res = okf_bundle.validate(out_dir)
        self.assertFalse(res["valid"])
        self.assertTrue(any("missing required field 'type'" in p for p in res["problems"]))

    def test_bundle_validation_fails_on_broken_index_link(self):
        out_dir = os.path.join(self.kb, ".metis", "exports", "okf_bundle")
        okf_bundle.bundle(self.kb, out_dir)

        # Break a link in index.md
        idx_path = os.path.join(out_dir, "db", "index.md")
        with open(idx_path, "a", encoding="utf-8") as fh:
            fh.write("\n| [Ghost](ghost.md) | `table` | stable | verified | Ghost table |\n")

        res = okf_bundle.validate(out_dir)
        self.assertFalse(res["valid"])
        self.assertTrue(any("link 'Ghost' (ghost.md) does not resolve" in p for p in res["problems"]))

    def test_bundle_validation_fails_on_sensitive_content(self):
        out_dir = os.path.join(self.kb, ".metis", "exports", "okf_bundle")
        okf_bundle.bundle(self.kb, out_dir)

        # Inject a private key secret into a bundle page
        page_path = os.path.join(out_dir, "db", "orders.md")
        with open(page_path, "w", encoding="utf-8") as fh:
            fh.write("---\ntype: table\ntitle: Orders Table\n---\n# Orders\npassword = supersecretpassword123\n")

        res = okf_bundle.validate(out_dir)
        self.assertFalse(res["valid"])
        self.assertTrue(any("sensitive finding" in p for p in res["problems"]))


if __name__ == "__main__":
    unittest.main()
