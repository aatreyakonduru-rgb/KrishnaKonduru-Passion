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

import screens_viz as V  # noqa: E402
import ui_common as C  # noqa: E402


class VisualizationsUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        os.makedirs(os.path.join(self.kb, ".metis"), exist_ok=True)
        os.makedirs(os.path.join(self.kb, "CROSS-LAYER"), exist_ok=True)
        os.makedirs(os.path.join(self.kb, "VISUALIZATION"), exist_ok=True)

        with open(os.path.join(self.kb, ".metis", "kb-profile.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump({"product": {"name": "Test KB"}}, f)

        with open(os.path.join(self.kb, "CROSS-LAYER", "ONTOLOGY.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump({"node_types": {"table": 10, "endpoint": 5}, "relations": {"endpoint -handled by-> class": 5}}, f)

        with open(os.path.join(self.kb, "CROSS-LAYER", "IMPACT_MATRIX.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump({"directions": {"reads": "from"}, "entries": {"table:ORDERS": {"type": "table", "moves_by_type": {"endpoint": ["endpoint:GET /orders"]}}}}, f)

        with open(os.path.join(self.kb, "VISUALIZATION", "ONTOLOGY.html"), "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html><body>Ontology Viz</body></html>")

        self.ctx = C.Ctx(self.kb, "tok", "Test Lead")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_routes_registered(self):
        self.assertIn("/visualizations", V.SCREENS)
        self.assertEqual(V.NAV, [("/visualizations", "Visuals")])

    def test_all_views_render(self):
        for key, title, _ in V.VIEWS:
            html = V.visualizations_view(self.ctx, {"view": key})
            self.assertIn("Visualizations", html)
            self.assertIn(C.esc(title), html)

    def test_brand_in_top_bar(self):
        html = V.visualizations_view(self.ctx, {})
        self.assertIn("M&#275;tis", html)
        self.assertIn("brand", html)
        self.assertIn("<img", html)


if __name__ == "__main__":
    unittest.main()
