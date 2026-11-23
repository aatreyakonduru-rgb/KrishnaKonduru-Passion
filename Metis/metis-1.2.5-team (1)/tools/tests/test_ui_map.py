import os
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import screens_map as S  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def edge(a, rel, b, line, origin="parsed"):
    return {"from": a, "rel": rel, "to": b, "source": '[E: api/A.java:%d "x"]' % line, "defined_in": "m/x.links.yaml", "origin": origin}


def node(nid):
    typ, _, name = nid.partition(":")
    return {"id": nid, "type": typ, "name": name}


def make_kb(nodes, edges):
    kb = tempfile.mkdtemp()
    write(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": nodes, "edges": edges}))
    return kb


class MapTests(unittest.TestCase):
    def setUp(self):
        ids = ["screen:Claims", "endpoint:GET /claims", "table:APP.CLAIM_HDR", "job:LOAD_CLAIMS", "table:APP.CLAIM_LINE", "class:api/Repo.java"]
        edges = [edge("screen:Claims", "calls", "endpoint:GET /claims", 1),
                 edge("endpoint:GET /claims", "reads", "table:APP.CLAIM_HDR", 2),
                 edge("job:LOAD_CLAIMS", "writes", "table:APP.CLAIM_HDR", 3, "catalogue"),
                 edge("table:APP.CLAIM_LINE", "references", "table:APP.CLAIM_HDR", 4, "ai-proposed"),
                 edge("class:api/Repo.java", "uses", "table:APP.CLAIM_LINE", 5)]
        self.kb = make_kb([node(i) for i in ids], edges)
        self.ctx = C.Ctx(self.kb, "tok", "Pat Lee")

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def svg_of(self, html):
        m = re.search(r"<svg.*?</svg>", html, re.S)
        self.assertTrue(m, "no svg in page")
        ET.fromstring(m.group(0))  # well-formed XML
        return m.group(0)

    def test_module_contract(self):
        self.assertEqual(set(S.SCREENS), {"/map", "/impact"})
        self.assertEqual(S.NAV, [("/map", "Map")])
        self.assertEqual(S.ACTIONS, {})

    def test_layers_follow_node_types(self):
        self.assertEqual([S.layer_of(t) for t in ("table", "view", "column", "job", "endpoint", "screen", "component", "class", "weird")],
                         ["tables", "tables", "tables", "jobs", "apis", "screens", "screens", "sources", "other"])

    def test_overview_has_layer_tabs_blocks_and_counts(self):
        html = S.map_view(self.ctx, {})
        for label in ("Sources", "Tables", "Jobs", "APIs", "Screens"):
            self.assertIn(label, html)
        self.assertIn("6 objects", html)
        svg = self.svg_of(html)
        self.assertIn("layer=tables", svg)
        self.assertIn("folder=APP", svg)
        self.assertNotIn("<script", html.lower())

    def test_layer_and_folder_drill_down(self):
        html = S.map_view(self.ctx, {"layer": "tables"})
        self.assertIn("Tables", html)
        self.assertIn("Links to other layers", html)
        html = S.map_view(self.ctx, {"layer": "tables", "folder": "APP"})
        self.assertIn("APP.CLAIM_HDR", html)
        self.assertIn("Showing all 2 objects", html)
        self.assertIn("center=table%3AAPP.CLAIM_HDR", html)

    def test_neighbourhood_svg_edge_styles_by_origin_and_click_to_recentre(self):
        html = S.map_view(self.ctx, {"center": "table:APP.CLAIM_HDR", "hops": "1"})
        svg = self.svg_of(html)
        self.assertIn("Showing 4 of 4 objects within 1 hop", html)
        self.assertNotIn("class:api/Repo.java", svg)  # two hops away
        self.assertIn("stroke-dasharray=\"7 4\"", svg)  # catalogue
        self.assertIn("stroke-dasharray=\"2 3\"", svg)  # ai-proposed
        self.assertIn('href="/map?center=endpoint%3AGET+%2Fclaims&amp;hops=1"', svg)  # a plain link recentres
        html2 = S.map_view(self.ctx, {"center": "table:APP.CLAIM_HDR", "hops": "2"})
        self.assertIn("Showing 6 of 6 objects within 2 hops", html2)
        self.assertIn("class:api/Repo.java", self.svg_of(html2))
        self.assertIn("what changes if it changes", html)

    def test_solid_line_is_parsed(self):
        svg = self.svg_of(S.map_view(self.ctx, {"center": "screen:Claims"}))
        paths = re.findall(r"<path d=\"M[^\"]*\" style=\"[^\"]*\" ([^/]*)/>", svg)
        self.assertTrue(paths)
        self.assertNotIn("stroke-dasharray", paths[0])

    def test_hops_are_clamped_and_depth_comes_from_graph_store(self):
        html = S.map_view(self.ctx, {"center": "table:APP.CLAIM_HDR", "hops": "99"})
        self.assertIn("within 3 hops", html)
        self.assertIn("within 1 hop", S.map_view(self.ctx, {"center": "table:APP.CLAIM_HDR", "hops": "x"}))

    def test_list_view_is_the_fallback(self):
        html = S.map_view(self.ctx, {"center": "table:APP.CLAIM_HDR", "view": "list"})
        self.assertNotIn('role="img"', html)  # no drawing (the legend's line samples are not the graph)
        self.assertIn("Links between them", html)
        self.assertIn("ai-proposed", html)
        self.assertIn("catalogue", html)

    def test_search_finds_an_object_and_says_when_none(self):
        html = S.map_view(self.ctx, {"q": "claim_hdr"})
        self.assertIn("center=table%3AAPP.CLAIM_HDR", html)
        self.assertIn("No object has", S.map_view(self.ctx, {"q": "nothing-like-this"}))
        self.assertIn("%", S.like("100%"))
        self.assertIn("No object has", S.map_view(self.ctx, {"q": "%"}))  # a wildcard is a literal, not "everything"

    def test_unknown_center_shows_a_message_and_search(self):
        html = S.map_view(self.ctx, {"center": "table:NOPE"})
        self.assertIn("There is no object", html)

    def test_object_with_no_links(self):
        kb = make_kb([node("table:APP.LONELY")], [])
        try:
            html = S.map_view(C.Ctx(kb, "t", ""), {"center": "table:APP.LONELY"})
            self.assertIn("No link touches this object", html)
            self.assertIn("Showing 1 of 1 objects", html)
        finally:
            shutil.rmtree(kb, ignore_errors=True)

    def test_no_graph_gives_a_plain_message(self):
        kb = tempfile.mkdtemp()
        try:
            html = S.map_view(C.Ctx(kb, "t", ""), {})
            self.assertIn("There is no link graph yet", html)
            self.assertIn("There is no link graph yet", S.impact_view(C.Ctx(kb, "t", ""), {"node": "x"}))
        finally:
            shutil.rmtree(kb, ignore_errors=True)

    def test_impact_lists_moves_and_dependencies_with_signals(self):
        html = S.impact_view(self.ctx, {"node": "table:APP.CLAIM_HDR", "depth": "3"})
        self.assertIn("If APP.CLAIM_HDR changes", html)
        self.assertIn("job:LOAD_CLAIMS", html)
        self.assertIn("screen:Claims", html)  # two steps away through the endpoint
        self.assertIn("What moves (4)", html)
        self.assertIn("quote", html)  # trust signals are shown
        self.assertIn('[E: api/A.java:3 &quot;x&quot;]', html)
        self.assertIn("catalogue", html)
        up = S.impact_view(self.ctx, {"node": "endpoint:GET /claims", "depth": "1"})
        self.assertIn("What it depends on (1)", up)

    def test_impact_without_object_offers_search(self):
        html = S.impact_view(self.ctx, {})
        self.assertIn("Pick an object", html)
        self.assertIn("LOAD_CLAIMS", S.impact_view(self.ctx, {"q": "LOAD"}))
        self.assertIn("There is no object", S.impact_view(self.ctx, {"node": "table:NOPE"}))

    def test_object_names_are_escaped(self):
        kb = make_kb([node("table:APP.<script>alert(1)</script>"), node("table:APP.B")],
                     [edge("table:APP.<script>alert(1)</script>", "references", "table:APP.B", 1)])
        try:
            c = C.Ctx(kb, "t", "")
            for html in (S.map_view(c, {"center": "table:APP.B", "view": "list"}), S.map_view(c, {"center": "table:APP.B"}),
                         S.impact_view(c, {"node": "table:APP.B"}), S.map_view(c, {"q": "script"})):
                self.assertNotIn("<script>", html)
        finally:
            shutil.rmtree(kb, ignore_errors=True)

    def test_graph_is_rebuilt_when_the_yaml_changes(self):
        S.map_view(self.ctx, {})
        g = yaml.safe_load(open(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), encoding="utf-8"))
        g["nodes"].append(node("table:APP.NEWER"))
        path = os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml")
        write(path, yaml.safe_dump(g))
        os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
        self.assertIn("7 objects", S.map_view(self.ctx, {}))


class ScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1 hub with 500 tables around it, in 40 folders, plus 400 jobs that each read 2 tables
        nodes = [node("table:HUB.CENTRAL")]
        edges = []
        for i in range(500):
            nodes.append(node("table:S%02d.T%03d" % (i % 40, i)))
            edges.append(edge("table:S%02d.T%03d" % (i % 40, i), "references", "table:HUB.CENTRAL", i + 1))
        for j in range(400):
            nodes.append(node("job:J%03d" % j))
            edges.append(edge("job:J%03d" % j, "reads", "table:S%02d.T%03d" % (j % 40, j % 500), j + 1))
        cls.kb = make_kb(nodes, edges)
        cls.ctx = C.Ctx(cls.kb, "t", "")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.kb, ignore_errors=True)

    def test_overview_never_draws_every_object(self):
        html = S.map_view(self.ctx, {})
        self.assertIn("901 objects", html)
        svg = re.search(r"<svg.*?</svg>", html, re.S).group(0)
        self.assertLess(svg.count("<rect"), 200)  # blocks, not nodes
        self.assertIn("Showing 15 of 42 folders", html)  # capped per layer, said out loud

    def test_neighbourhood_is_capped_at_300_and_says_so(self):
        html = S.map_view(self.ctx, {"center": "table:HUB.CENTRAL", "hops": "1"})
        self.assertIn("Showing 300 of 501 objects within 1 hop", html)
        svg = re.search(r"<svg.*?</svg>", html, re.S).group(0)
        ET.fromstring(svg)
        self.assertEqual(svg.count("(table)</title>"), 300)
        self.assertIn("one column per hop", html)

    def test_layout_is_deterministic(self):
        a = S.map_view(self.ctx, {"center": "table:S01.T001", "hops": "2"})
        b = S.map_view(self.ctx, {"center": "table:S01.T001", "hops": "2"})
        self.assertEqual(a, b)

    def test_list_view_is_capped_too(self):
        html = S.map_view(self.ctx, {"center": "table:HUB.CENTRAL", "view": "list"})
        self.assertIn("Showing 300 of 501 objects", html)
        self.assertLess(html.count("<tr>"), 700)

    def test_folder_listing_is_capped(self):
        html = S.map_view(self.ctx, {"layer": "tables", "folder": "S05"})
        self.assertIn("Showing all 13 objects", html)


if __name__ == "__main__":
    unittest.main()
