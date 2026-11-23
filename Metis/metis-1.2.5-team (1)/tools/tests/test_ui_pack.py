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

import graph_store  # noqa: E402
import screens_pack as S  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


GRAPH = {"as_of": "2026-01-01",
         "nodes": [{"id": "table:pets", "type": "table", "name": "pets"},
                   {"id": "class:Pet", "type": "class", "name": "Pet"}],
         "edges": [{"from": "class:Pet", "rel": "stored in", "to": "table:pets",
                    "source": "[E: Pet.java:45 \"@Table(name = pets)\"]", "defined_in": "x.yaml", "origin": "code"}]}


class PackUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump(GRAPH))
        write(os.path.join(self.kb, "db", "PETS.md"), "# pets table\n\nPets belong to owners. [E: a.sql:1 \"create table pets\"]\n\n"
              "## Columns\n\n- name, birth_date\n")
        write(os.path.join(self.kb, "db", "KEYS.md"), "# pets keys\n\nThe pets login is AKIAIOSFODNN7EXAMPLE here.\n")
        self.pat = C.Ctx(self.kb, "tok", "Pat Lee")
        S.PACKS.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, **over):
        f = {"task": "add a column to the pets table", "budget": "6000"}
        f.update(over)
        return S.act_pack_build(self.pat, f)

    def test_module_contract(self):
        self.assertIn("/pack", S.SCREENS)
        self.assertEqual(S.ACTIONS["/pack/build"][0], "/pack")
        self.assertEqual(S.NAV, [("/pack", "Context pack")])

    def test_empty_page_says_what_the_tool_cannot_do(self):
        html = S.pack_view_screen(self.pat, {})
        self.assertIn("per-page summaries", html)
        self.assertIn('name="budget" value="6000"', html)
        self.assertIn("/pack/build", html)

    def test_build_and_show(self):
        where, msg = self.build()
        self.assertTrue(where.startswith("/pack?pack=P-"))
        pid = where.split("=")[1]
        self.assertIn(pid, msg)
        html = S.pack_view_screen(self.pat, {"pack": pid})
        self.assertIn("Pack " + pid, html)
        self.assertIn("table:pets", html)
        self.assertIn("db/PETS.md", html)
        self.assertLess(html.index("Impact list"), html.index("Pages included"))
        self.assertIn("readonly", html)

    def test_citation_kept(self):
        pid = self.build()[0].split("=")[1]
        html = S.pack_view_screen(self.pat, {"pack": pid})
        self.assertIn("a.sql:1", html)

    def test_secret_page_reported(self):
        pid = self.build()[0].split("=")[1]
        html = S.pack_view_screen(self.pat, {"pack": pid})
        self.assertIn("db/KEYS.md", html)
        self.assertIn("left out", html)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", html)

    def test_small_budget_lists_left_out(self):
        pid = self.build(budget="500")[0].split("=")[1]
        info = S.PACKS[(self.kb, pid)]
        self.assertLessEqual(info["pack"]["tokens"], 500 + 100)
        html = S.pack_view_screen(self.pat, {"pack": pid})
        self.assertIn("Left out", html)

    def test_needs_a_name(self):
        with self.assertRaises(C.UiError):
            S.act_pack_build(C.Ctx(self.kb, "tok", ""), {"task": "pets"})

    def test_refusals(self):
        for f in ({"task": ""}, {"task": "pets", "budget": "lots"}, {"task": "pets", "budget": "10"},
                  {"task": "nothing matches here"}, {"task": "x", "objects": "table:nope"}):
            with self.assertRaises(C.UiError, msg=str(f)):
                S.act_pack_build(self.pat, f)

    def test_named_objects_only(self):
        where, _ = self.build(task="", objects="table:pets")
        self.assertIn(("table:pets",), [tuple(S.PACKS[(self.kb, where.split("=")[1])]["start"])])

    def test_escapes_user_text(self):
        hostile = '<script>alert(1)</script>'
        html = S.pack_view_screen(self.pat, {"pack": hostile})
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        with self.assertRaises(C.UiError) as cm:
            S.act_pack_build(self.pat, {"task": "x", "objects": hostile})
        html = S.pack_view_screen(self.pat, {}, error=str(cm.exception))
        self.assertNotIn("<script>alert", html)

    def test_writes_only_inside_kb(self):
        before = set(os.listdir(self.tmp))
        self.build()
        self.assertEqual(set(os.listdir(self.tmp)), before)


if __name__ == "__main__":
    unittest.main()
