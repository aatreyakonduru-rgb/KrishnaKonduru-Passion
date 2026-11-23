import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kb_gate  # noqa: E402
import screens_federation as S  # noqa: E402
import shared_index  # noqa: E402
import ui_common as C  # noqa: E402


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


class FederationUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        os.makedirs(os.path.join(self.kb, ".metis"), exist_ok=True)
        os.makedirs(os.path.join(self.kb, "CROSS-LAYER"), exist_ok=True)

        write_file(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "ClaimsService", "team": "Claims Team"},
                                   "owners": {"kb_owner": "Ana Lead"}}))

        write_file(os.path.join(self.kb, "_EVIDENCE", "files", "claim_rules.txt"), "claim rules\n")
        write_file(os.path.join(self.kb, "context", "rules.md"),
                   "# Claims Rules\n\n- Claims are processed in 30 days [E: file:claim_rules.txt]\n")

        write_file(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"),
                   yaml.safe_dump({
                       "nodes": [
                           {"id": "endpoint:GET /claims", "type": "endpoint", "name": "GET /claims"},
                           {"id": "table:CLAIMS", "type": "table", "name": "CLAIMS"},
                       ],
                       "edges": [
                           {"from": "endpoint:GET /claims", "rel": "reads", "to": "table:CLAIMS",
                            "source": "[E: file:claim_rules.txt]", "origin": "parsed"},
                       ]
                   }))

        kb_gate.lock(self.kb, "Ana Lead")

        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")
        self.anon = C.Ctx(self.kb, "tok", "")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_module_contract(self):
        self.assertIn("/federation", S.SCREENS)
        self.assertEqual(S.NAV, [("/federation", "Federation")])
        self.assertIn("/federation/register", S.ACTIONS)
        self.assertIn("/federation/export_rdf", S.ACTIONS)
        self.assertIn("/federation/export_prov", S.ACTIONS)
        self.assertIn("/federation/export_okf", S.ACTIONS)

    def test_view_kbs_tab(self):
        html = S.federation_view(self.lead, {"tab": "kbs"})
        self.assertIn("Registered Knowledge Bases", html)
        self.assertIn("Register Knowledge Base", html)

    def test_view_search_tab(self):
        # Register KB first
        db_p = S.shared_db_path(self.kb)
        shared_index.register(db_p, self.kb)

        html = S.federation_view(self.lead, {"tab": "search", "query": "claims"})
        self.assertIn("Search Knowledge Across All Teams", html)
        self.assertIn('Search Results for "claims"', html)
        self.assertIn("Claims Team", html)

    def test_view_impact_tab(self):
        db_p = S.shared_db_path(self.kb)
        shared_index.register(db_p, self.kb)

        html = S.federation_view(self.lead, {"tab": "impact", "node": "table:CLAIMS", "dir": "impact"})
        self.assertIn("Cross-Team Walk", html)
        self.assertIn('Downstream Impact for "table:CLAIMS"', html)

    def test_view_exports_tab(self):
        html = S.federation_view(self.lead, {"tab": "exports"})
        self.assertIn("One-Click Knowledge Base Exports", html)
        self.assertIn("Export RDF & OWL", html)
        self.assertIn("Export PROV & OTel", html)
        self.assertIn("Export OKF Bundle", html)

    def test_user_required_for_actions(self):
        with self.assertRaises(C.UiError) as err:
            S.act_federation_register(self.anon, {"kb_path": self.kb})
        self.assertIn("Say who you are first", str(err.exception))

    def test_act_register_and_refresh(self):
        where, msg = S.act_federation_register(self.lead, {"kb_path": self.kb})
        self.assertEqual(where, "/federation?tab=kbs")
        self.assertIn("Successfully registered", msg)

        where_ref, msg_ref = S.act_federation_refresh(self.lead, {})
        self.assertEqual(where_ref, "/federation?tab=kbs")
        self.assertIn("Refreshed", msg_ref)

    def test_act_export_rdf(self):
        where, msg = S.act_federation_export_rdf(self.lead, {})
        self.assertEqual(where, "/federation?tab=exports")
        self.assertIn("Exported", msg)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, ".metis", "exports", "rdf", "graph.ttl")))

    def test_act_export_prov(self):
        where, msg = S.act_federation_export_prov(self.lead, {})
        self.assertEqual(where, "/federation?tab=exports")
        self.assertIn("Exported", msg)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, ".metis", "exports", "prov", "prov-o.ttl")))

    def test_act_export_okf(self):
        where, msg = S.act_federation_export_okf(self.lead, {})
        self.assertEqual(where, "/federation?tab=exports")
        self.assertIn("Packaged", msg)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, ".metis", "exports", "okf_bundle", "okf-manifest.yaml")))

    def test_escapes_user_input(self):
        html = S.federation_view(self.lead, {"tab": "search", "query": "<script>alert(1)</script>"})
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)


if __name__ == "__main__":
    unittest.main()
