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
import page_owners  # noqa: E402
import screens_owners as S  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class OwnersUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        prof = {
            "owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev"},
            "gate": {"teams": [
                {"name": "Claims Team", "owns": ["claims/*"], "approvers": ["Cleo Claims"]},
            ]},
        }
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "f.txt"), "sample rules\n")
        write(os.path.join(self.kb, "claims", "p1.md"), "# P1\n\n- Claim line [E: file:f.txt]\n")
        write(os.path.join(self.kb, "context", "p2.md"), "# P2\n\n- Context line [E: file:f.txt]\n")

        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")
        self.member = C.Ctx(self.kb, "tok", "Pat Lee")
        self.anon = C.Ctx(self.kb, "tok", "")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_module_contract(self):
        self.assertIn("/owners", S.SCREENS)
        self.assertEqual(S.NAV, [("/owners", "Owners & Reviews")])
        self.assertIn("/owners/set", S.ACTIONS)
        self.assertIn("/owners/mark", S.ACTIONS)
        self.assertIn("/owners/recalibrate", S.ACTIONS)

    def test_default_view_renders(self):
        html = S.owners_view(self.lead, {})
        self.assertIn("Page Ownership &amp; Governance", html)
        self.assertIn("claims/p1.md", html)
        self.assertIn("Claims Team", html)
        self.assertIn("context/p2.md", html)

    def test_act_set_owner_by_lead(self):
        where, msg = S.act_set_owner(self.lead, {"page": "context/p2.md", "owner": "Raj Dev", "days": "45"})
        self.assertEqual(where, "/owners")
        self.assertIn("Updated ownership", msg)

        info = page_owners.page_info(self.kb, "context/p2.md")
        self.assertEqual(info["owner"], "Raj Dev")
        self.assertEqual(info["review_every_days"], 45)

    def test_act_set_owner_refused_for_non_lead(self):
        with self.assertRaises(C.UiError) as cm:
            S.act_set_owner(self.member, {"page": "context/p2.md", "owner": "Pat Lee"})
        self.assertIn("Only a named lead", str(cm.exception))

    def test_act_set_owner_refused_for_anonymous(self):
        with self.assertRaises(C.UiError) as cm:
            S.act_set_owner(self.anon, {"page": "context/p2.md", "owner": "Pat Lee"})
        self.assertIn("Say who you are first", str(cm.exception))

    def test_act_mark_reviewed(self):
        where, msg = S.act_mark_reviewed(self.lead, {"page": "claims/p1.md", "note": "Checked rule"})
        self.assertEqual(where, "/owners")
        self.assertIn("Marked claims/p1.md reviewed", msg)

        info = page_owners.page_info(self.kb, "claims/p1.md")
        self.assertIsNotNone(info["last_reviewed"])

    def test_views_render(self):
        # Stats view
        kb_gate.log(self.kb, "certify", "Ana Lead", "kb owner", "b1", "claims/p1.md")
        html_stats = S.owners_view(self.lead, {"view": "stats"})
        self.assertIn("Reviewer Track Record", html_stats)
        self.assertIn("Ana Lead", html_stats)

        # Recalibrate view
        html_rec = S.owners_view(self.lead, {"view": "recalibrate"})
        self.assertIn("Confidence Recalibration Loop", html_rec)

        # Overdue view
        html_due = S.owners_view(self.lead, {"view": "overdue"})
        self.assertIn("Overdue Reviews", html_due)

        # Stale view
        html_stale = S.owners_view(self.lead, {"view": "stale"})
        self.assertIn("Pages with Stale Cited Sources", html_stale)

        # Unowned view
        html_unowned = S.owners_view(self.lead, {"view": "unowned"})
        self.assertIn("Unassigned Pages", html_unowned)

    def test_act_recalibrate_action(self):
        # Run recalibration with force=True
        where, msg = S.act_recalibrate(self.lead, {"min_volume": "30", "force": "1"})
        self.assertEqual(where, "/owners?view=recalibrate")
        self.assertIn("generated successfully", msg)

        # Now view recalibrate should show proposal
        html_rec = S.owners_view(self.lead, {"view": "recalibrate"})
        self.assertIn("Active Proposal", html_rec)

    def test_act_recalibrate_refused_for_non_lead(self):
        with self.assertRaises(C.UiError) as cm:
            S.act_recalibrate(self.member, {"min_volume": "30"})
        self.assertIn("Only a named lead", str(cm.exception))

    def test_escapes_xss(self):
        S.act_set_owner(self.lead, {"page": "context/p2.md", "owner": "<script>alert(1)</script>"})
        html = S.owners_view(self.lead, {})
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)


if __name__ == "__main__":
    unittest.main()
