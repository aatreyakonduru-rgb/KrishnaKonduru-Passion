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

import cross_impact  # noqa: E402
import kb_gate  # noqa: E402
import shared_index  # noqa: E402


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


class CrossImpactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "shared.sqlite")

        # Setup Team A KB (Claims Service)
        self.kb_a = os.path.join(self.tmp, "KB_Claims")
        os.makedirs(os.path.join(self.kb_a, ".metis"), exist_ok=True)
        os.makedirs(os.path.join(self.kb_a, "CROSS-LAYER"), exist_ok=True)
        write_file(os.path.join(self.kb_a, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "ClaimsService", "team": "Claims Team"},
                                   "owners": {"kb_owner": "Ana Lead"}}))
        write_file(os.path.join(self.kb_a, "_EVIDENCE", "files", "claim_rules.txt"), "claim rules\n")
        write_file(os.path.join(self.kb_a, "context", "rules.md"),
                   "# Rules\n\n- Claims are processed in 30 days [E: file:claim_rules.txt]\n")

        # In Team A: ETL_JOB writes table:CLAIMS
        write_file(os.path.join(self.kb_a, "CROSS-LAYER", "LINK_GRAPH.yaml"),
                   yaml.safe_dump({
                       "nodes": [
                           {"id": "job:CLAIMS_ETL", "type": "job", "name": "CLAIMS_ETL"},
                           {"id": "table:CLAIMS", "type": "table", "name": "CLAIMS"},
                       ],
                       "edges": [
                           {"from": "job:CLAIMS_ETL", "rel": "writes", "to": "table:CLAIMS",
                            "source": "[E: file:claim_rules.txt]", "origin": "parsed"},
                       ]
                   }))
        kb_gate.lock(self.kb_a, "Ana Lead")

        # Setup Team B KB (Billing Portal)
        self.kb_b = os.path.join(self.tmp, "KB_Billing")
        os.makedirs(os.path.join(self.kb_b, ".metis"), exist_ok=True)
        os.makedirs(os.path.join(self.kb_b, "CROSS-LAYER"), exist_ok=True)
        write_file(os.path.join(self.kb_b, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "BillingPortal", "team": "Billing Team"},
                                   "owners": {"kb_owner": "Bo Lead"}}))
        write_file(os.path.join(self.kb_b, "_EVIDENCE", "files", "billing_rules.txt"), "billing rules\n")
        write_file(os.path.join(self.kb_b, "context", "billing.md"),
                   "# Billing\n\n- Billing rules [E: file:billing_rules.txt]\n")

        # In Team B: screen:INVOICE_SCREEN reads table:CLAIMS
        write_file(os.path.join(self.kb_b, "CROSS-LAYER", "LINK_GRAPH.yaml"),
                   yaml.safe_dump({
                       "nodes": [
                           {"id": "table:CLAIMS", "type": "table", "name": "CLAIMS"},
                           {"id": "screen:INVOICE_SCREEN", "type": "screen", "name": "INVOICE_SCREEN"},
                       ],
                       "edges": [
                           {"from": "screen:INVOICE_SCREEN", "rel": "reads", "to": "table:CLAIMS",
                            "source": "[E: file:billing_rules.txt]", "origin": "catalogue"},
                       ]
                   }))
        kb_gate.lock(self.kb_b, "Bo Lead")

        # Register both KBs into shared.sqlite
        shared_index.register(self.db_path, self.kb_a)
        shared_index.register(self.db_path, self.kb_b)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cross_team_downstream_impact_walk(self):
        # When job:CLAIMS_ETL changes, it writes table:CLAIMS, which moves table:CLAIMS,
        # which in turn moves screen:INVOICE_SCREEN in Team B!
        rows, cut = cross_impact.impact(self.db_path, "job:CLAIMS_ETL", depth=4)
        self.assertFalse(cut)
        self.assertGreater(len(rows), 0)

        # Verify that Team B's screen:INVOICE_SCREEN is reached
        reached_nodes = {r["node"] for r in rows}
        reached_teams = {r["team"] for r in rows}
        reached_kbs = {r["kb"] for r in rows}

        self.assertIn("table:CLAIMS", reached_nodes)
        self.assertIn("screen:INVOICE_SCREEN", reached_nodes)
        self.assertIn("Billing Team", reached_teams)
        self.assertIn("BillingPortal", reached_kbs)

    def test_cross_team_upstream_dependency_walk(self):
        # What does screen:INVOICE_SCREEN depend on? It reads table:CLAIMS, written by job:CLAIMS_ETL in Team A.
        rows, cut = cross_impact.upstream(self.db_path, "screen:INVOICE_SCREEN", depth=4)
        self.assertFalse(cut)
        self.assertGreater(len(rows), 0)

        reached_nodes = {r["node"] for r in rows}
        reached_teams = {r["team"] for r in rows}

        self.assertIn("table:CLAIMS", reached_nodes)
        self.assertIn("job:CLAIMS_ETL", reached_nodes)
        self.assertIn("Claims Team", reached_teams)

    def test_depth_limiting(self):
        rows, _ = cross_impact.impact(self.db_path, "job:CLAIMS_ETL", depth=1)
        # Depth 1 only reaches immediate target (table:CLAIMS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["node"], "table:CLAIMS")


if __name__ == "__main__":
    unittest.main()
