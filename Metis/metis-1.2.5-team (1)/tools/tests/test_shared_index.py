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
import shared_index  # noqa: E402


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


class SharedIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "shared.sqlite")

        # Setup Team A KB (Claims)
        self.kb_a = os.path.join(self.tmp, "KB_Claims")
        os.makedirs(os.path.join(self.kb_a, ".metis"), exist_ok=True)
        os.makedirs(os.path.join(self.kb_a, "CROSS-LAYER"), exist_ok=True)
        write_file(os.path.join(self.kb_a, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "ClaimsKB", "team": "Claims Team"},
                                   "owners": {"kb_owner": "Ana Lead"}}))
        write_file(os.path.join(self.kb_a, "_EVIDENCE", "files", "claim_rules.txt"), "claim rules\n")
        write_file(os.path.join(self.kb_a, "context", "rules.md"),
                   "# Claims Rules\n\n- Claims are processed in 30 days [E: file:claim_rules.txt]\n")
        write_file(os.path.join(self.kb_a, "CROSS-LAYER", "LINK_GRAPH.yaml"),
                   yaml.safe_dump({
                       "nodes": [{"id": "table:CLAIMS", "type": "table", "name": "CLAIMS"},
                                 {"id": "endpoint:GET /claims", "type": "endpoint", "name": "GET /claims"}],
                       "edges": [{"from": "endpoint:GET /claims", "rel": "reads", "to": "table:CLAIMS",
                                  "source": "[E: file:claim_rules.txt]", "origin": "parsed"}]
                   }))
        kb_gate.lock(self.kb_a, "Ana Lead")

        # Setup Team B KB (Billing)
        self.kb_b = os.path.join(self.tmp, "KB_Billing")
        os.makedirs(os.path.join(self.kb_b, ".metis"), exist_ok=True)
        os.makedirs(os.path.join(self.kb_b, "CROSS-LAYER"), exist_ok=True)
        write_file(os.path.join(self.kb_b, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "BillingKB", "team": "Billing Team"},
                                   "owners": {"kb_owner": "Bo Lead"}}))
        write_file(os.path.join(self.kb_b, "_EVIDENCE", "files", "billing_rules.txt"), "invoice rules\n")
        write_file(os.path.join(self.kb_b, "context", "invoices.md"),
                   "# Invoicing\n\n- Invoices generated upon claim approval [E: file:billing_rules.txt]\n")
        write_file(os.path.join(self.kb_b, "CROSS-LAYER", "LINK_GRAPH.yaml"),
                   yaml.safe_dump({
                       "nodes": [{"id": "job:BILLING_JOB", "type": "job", "name": "BILLING_JOB"},
                                 {"id": "table:CLAIMS", "type": "table", "name": "CLAIMS"}],
                       "edges": [{"from": "job:BILLING_JOB", "rel": "reads", "to": "table:CLAIMS",
                                  "source": "[E: file:billing_rules.txt]", "origin": "catalogue"}]
                   }))
        kb_gate.lock(self.kb_b, "Bo Lead")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_and_stats(self):
        res_a = shared_index.register(self.db_path, self.kb_a)
        res_b = shared_index.register(self.db_path, self.kb_b)

        self.assertEqual(res_a["name"], "ClaimsKB")
        self.assertEqual(res_b["name"], "BillingKB")

        st = shared_index.stats(self.db_path)
        self.assertEqual(st["total_kbs"], 2)
        self.assertGreater(st["total_pages"], 0)
        self.assertGreater(st["total_objects"], 0)

    def test_search_and_helper(self):
        shared_index.register(self.db_path, self.kb_a)
        shared_index.register(self.db_path, self.kb_b)

        hits = shared_index.search(self.db_path, "claim")
        self.assertGreater(len(hits), 0)
        kb_names = {h["kb_name"] for h in hits}
        self.assertTrue("ClaimsKB" in kb_names or "BillingKB" in kb_names)

        helper_text = shared_index.cross_kb_pages(self.db_path, "claim")
        self.assertIn("Facts from", helper_text)
        self.assertIn("[", helper_text)

    def test_objects_query(self):
        shared_index.register(self.db_path, self.kb_a)
        shared_index.register(self.db_path, self.kb_b)

        tables = shared_index.objects(self.db_path, ntype="table")
        self.assertGreater(len(tables), 0)
        self.assertTrue(all(t["type"] == "table" for t in tables))

    def test_rejection_of_unlocked_kb(self):
        kb_unlocked = os.path.join(self.tmp, "KB_Unlocked")
        os.makedirs(os.path.join(kb_unlocked, ".metis"), exist_ok=True)
        write_file(os.path.join(kb_unlocked, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "UnlockedKB"}, "owners": {"kb_owner": "Ana Lead"}}))

        with self.assertRaises(ValueError) as ctx:
            shared_index.register(self.db_path, kb_unlocked)
        self.assertIn("not certified", str(ctx.exception))

    def test_rejection_of_share_false_kb(self):
        kb_private = os.path.join(self.tmp, "KB_Private")
        os.makedirs(os.path.join(kb_private, ".metis"), exist_ok=True)
        write_file(os.path.join(kb_private, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "PrivateKB"}, "share": False, "owners": {"kb_owner": "Ana Lead"}}))
        write_file(os.path.join(kb_private, "_EVIDENCE", "files", "r.txt"), "rule\n")
        write_file(os.path.join(kb_private, "context", "r.md"), "# R\n\n- rule [E: file:r.txt]\n")
        kb_gate.lock(kb_private, "Ana Lead")

        with self.assertRaises(ValueError) as ctx:
            shared_index.register(self.db_path, kb_private)
        self.assertIn("share: false", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
