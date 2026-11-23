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

import golden  # noqa: E402
import screens_golden as S  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class GoldenUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        write(os.path.join(self.kb, "context", "rules.md"), "Claims are paid within 30 days.\n")
        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")
        self.pat = C.Ctx(self.kb, "tok", "Pat Lee")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, **over):
        f = {"question": "How fast are claims paid?", "cite": "context/rules.md", "include": "30 days"}
        f.update(over)
        return S.act_golden_add(self.lead, f)

    def test_module_contract(self):
        self.assertIn("/golden", S.SCREENS)
        self.assertEqual(S.NAV, [("/golden", "Golden questions")])
        self.assertEqual(S.ACTIONS["/golden/add"][0], "/golden")

    def test_empty_page(self):
        html = S.golden_view(self.lead, {})
        self.assertIn("No golden questions yet", html)
        self.assertIn("no remove command", html)

    def test_add_stores_through_golden(self):
        where, msg = self.add()
        self.assertEqual(where, "/golden")
        g = golden.load(self.kb)["golden"][0]
        self.assertEqual((g["id"], g["cite"], g["include"], g["added_by"]), ("G-0001", ["context/rules.md"], ["30 days"], "Ana Lead"))
        self.assertIn("G-0001", msg)
        self.assertIn("How fast are claims paid?", S.golden_view(self.lead, {}))

    def test_name_required(self):
        with self.assertRaises(C.UiError) as e:
            S.act_golden_add(C.Ctx(self.kb, "tok", ""), {"question": "q", "cite": "context/rules.md"})
        self.assertIn("Say who you are first", str(e.exception))

    def test_non_lead_refused(self):
        with self.assertRaises(C.UiError) as e:
            S.act_golden_add(self.pat, {"question": "q", "cite": "context/rules.md"})
        self.assertIn("not a lead", str(e.exception))
        self.assertEqual(golden.load(self.kb)["golden"], [])

    def test_golden_rules_become_ui_errors(self):
        with self.assertRaises(C.UiError):
            self.add(cite="")
        with self.assertRaises(C.UiError) as e:
            self.add(cite="context/nope.md")
        self.assertIn("not in the KB", str(e.exception))
        self.add()
        with self.assertRaises(C.UiError) as e:
            self.add()
        self.assertIn("already in the set", str(e.exception))

    def test_bad_kind_refused(self):
        with self.assertRaises(C.UiError):
            self.add(kind="other")

    def test_escapes_user_text(self):
        self.add(question="<script>alert(1)</script> paid?", include="<b>x</b>")
        html = S.golden_view(self.lead, {})
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<b>x</b>", html)

    def test_static_run_pass_and_fail(self):
        self.add()
        html = S.golden_view(self.lead, {"run": "1"})
        self.assertIn("Static check only", html)
        self.assertIn("1 of 1 pass", html)
        os.remove(os.path.join(self.kb, "context", "rules.md"))
        html = S.golden_view(self.lead, {"run": "1"})
        self.assertIn("0 of 1 pass", html)
        self.assertIn("relies on context/rules.md, which is not in the KB", html)

    def test_score_run_uses_golden_reasons(self):
        self.add()
        write(os.path.join(self.kb, "ans", "G-0001.md"), "Claims are paid quickly.\n")
        html = S.golden_view(self.lead, {"run": "1", "answers": "ans"})
        self.assertIn("Scored the answers in ans", html)
        self.assertIn("does not cite context/rules.md", html)
        self.assertIn("does not say &#x27;30 days&#x27;", html)
        self.assertIn("0 of 1 pass", html)

    def test_answers_folder_must_be_inside_kb(self):
        html = S.golden_view(self.lead, {"run": "1", "answers": ".."})
        self.assertIn("inside the KB", html)


if __name__ == "__main__":
    unittest.main()
