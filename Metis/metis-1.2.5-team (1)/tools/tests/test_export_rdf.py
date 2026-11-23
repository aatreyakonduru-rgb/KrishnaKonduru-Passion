import json
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

import export_rdf  # noqa: E402


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


class SimpleTurtleParser(object):
    """A minimal Turtle parser for round-trip validation in tests."""
    def __init__(self, text):
        self.text = text
        self.prefixes = {}
        self.triples = []
        self._parse()

    def _parse(self):
        # Strip comments
        lines = []
        for line in self.text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            lines.append(s)
        full = " ".join(lines)

        # Extract @prefix
        while True:
            m = export_rdf.re.search(r"@prefix\s+([a-zA-Z0-9_\-]+):\s*<([^>]+)>\s*\.", full)
            if not m:
                break
            self.prefixes[m.group(1)] = m.group(2)
            full = full[:m.start()] + " " + full[m.end():]

        # Extract statement blocks ending in '.'
        statements = export_rdf.split_statements(full)
        for st in statements:
            # Extract subject
            tokens = export_rdf.tokenize_triple(st)
            if not tokens:
                continue
            subj = self._expand(tokens[0])
            rest = " ".join(tokens[1:])
            # Split predicate-object clauses by ';'
            clauses = self._split_clauses(rest)
            for c in clauses:
                ctoks = export_rdf.tokenize_triple(c)
                if len(ctoks) >= 2:
                    pred = self._expand(ctoks[0])
                    obj_str = " ".join(ctoks[1:]).strip()
                    obj = self._expand_obj(obj_str)
                    self.triples.append((subj, pred, obj))

    def _split_clauses(self, text):
        clauses, current = [], []
        in_angle, in_quote, quote_ch = False, False, None
        for ch in text:
            if not in_angle and not in_quote:
                if ch == '<':
                    in_angle = True
                    current.append(ch)
                elif ch in ('"', "'"):
                    in_quote = True
                    quote_ch = ch
                    current.append(ch)
                elif ch == ';':
                    c = "".join(current).strip()
                    if c:
                        clauses.append(c)
                    current = []
                else:
                    current.append(ch)
            elif in_angle:
                current.append(ch)
                if ch == '>':
                    in_angle = False
            elif in_quote:
                current.append(ch)
                if ch == quote_ch:
                    in_quote = False
        c = "".join(current).strip()
        if c:
            clauses.append(c)
        return clauses

    def _expand(self, term):
        t = term.strip()
        if t.startswith("<") and t.endswith(">"):
            return t[1:-1]
        if t == "a":
            return export_rdf.RDF_TYPE
        if ":" in t and not t.startswith("http"):
            pfx, _, name = t.partition(":")
            if pfx in self.prefixes:
                return self.prefixes[pfx] + name
        return t

    def _expand_obj(self, term):
        t = term.strip()
        if t.startswith('"') and t.endswith('"'):
            return t[1:-1]
        return self._expand(t)


class ExportRdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        os.makedirs(os.path.join(self.kb, "CROSS-LAYER"), exist_ok=True)

        self.nodes = [
            {"id": "table:CLAIMS", "type": "table", "name": "CLAIMS"},
            {"id": "endpoint:GET /claims", "type": "endpoint", "name": "GET /claims"},
            {"id": "job:PROCESS_CLAIMS", "type": "job", "name": "PROCESS_CLAIMS"},
        ]
        self.edges = [
            {
                "from": "endpoint:GET /claims",
                "rel": "reads",
                "to": "table:CLAIMS",
                "source": '[E: api/src/Claims.java:45 "SELECT FROM CLAIMS"]',
                "defined_in": "api.links.yaml",
                "origin": "parsed",
            },
            {
                "from": "job:PROCESS_CLAIMS",
                "rel": "writes",
                "to": "table:CLAIMS",
                "source": '[E: batch/job.py:10 "INSERT INTO CLAIMS"]',
                "defined_in": "batch.links.yaml",
                "origin": "catalogue",
            },
        ]
        write_file(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"),
                   yaml.safe_dump({"nodes": self.nodes, "edges": self.edges}))
        write_file(os.path.join(self.kb, "CROSS-LAYER", "ONTOLOGY.yaml"),
                   yaml.safe_dump({"node_types": {"table": 1, "endpoint": 1, "job": 1},
                                   "relations": {"endpoint -reads-> table": 1, "job -writes-> table": 1}}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_all_creates_files(self):
        out_dir = os.path.join(self.kb, ".metis", "exports", "rdf")
        written = export_rdf.export_all(self.kb, out_dir)
        self.assertTrue(any(w.endswith("graph.ttl") for w in written))
        self.assertTrue(any(w.endswith("graph.nt") for w in written))
        self.assertTrue(any(w.endswith("graph.jsonld") for w in written))
        self.assertTrue(any(w.endswith("ontology.owl") for w in written))

        for p in written:
            self.assertTrue(os.path.isfile(p))
            self.assertGreater(os.path.getsize(p), 0)

    def test_turtle_round_trip_and_content(self):
        ttl_text = export_rdf.to_turtle(self.kb)
        self.assertIn("@prefix metis:", ttl_text)
        self.assertIn("@prefix kb:", ttl_text)
        self.assertIn("Graph Origin: parsed", ttl_text)

        parser = SimpleTurtleParser(ttl_text)
        self.assertGreater(len(parser.triples), 0)

        # Check node typing in triples
        endpoint_iri = export_rdf.node_key_to_iri("endpoint:GET /claims")
        table_iri = export_rdf.node_key_to_iri("table:CLAIMS")
        type_table_iri = export_rdf.type_iri("table")

        has_table_type = any(s == table_iri and p == export_rdf.RDF_TYPE and o == type_table_iri
                             for s, p, o in parser.triples)
        self.assertTrue(has_table_type, "Table node must be typed as metis:table")

        # Check edge relationship in triples
        reads_iri = export_rdf.rel_iri("reads")
        has_edge = any(s == endpoint_iri and p == reads_iri and o == table_iri
                       for s, p, o in parser.triples)
        self.assertTrue(has_edge, "Reads relation must link endpoint to table")

    def test_n_triples_format(self):
        triples, _, _, _, _ = export_rdf.build_triples(self.kb)
        nt = export_rdf.to_n_triples(triples)
        lines = [l for l in nt.splitlines() if l.strip()]
        self.assertGreater(len(lines), 0)
        for line in lines:
            self.assertTrue(line.endswith(" ."), "Each N-Triple line must end in ' .'")
            self.assertTrue(line.startswith("<"), "Each N-Triple line must start with '<'")

    def test_jsonld_format(self):
        jsonld_str = export_rdf.to_json_ld(self.kb)
        doc = json.loads(jsonld_str)
        self.assertIn("@context", doc)
        self.assertIn("@graph", doc)
        self.assertGreater(len(doc["@graph"]), 0)
        # Verify node item
        nodes_in_ld = [item for item in doc["@graph"] if item.get("name") == "CLAIMS"]
        self.assertEqual(len(nodes_in_ld), 1)
        self.assertEqual(nodes_in_ld[0]["nodeType"], "table")

    def test_owl_ontology_export(self):
        owl_text = export_rdf.to_owl(self.kb)
        self.assertIn("owl:Ontology", owl_text)
        self.assertIn("owl:Class", owl_text)
        self.assertIn("owl:ObjectProperty", owl_text)
        self.assertIn("reads", owl_text)
        self.assertIn("table", owl_text)

    def test_sparql_subset_query_bgp(self):
        q = 'SELECT ?s ?name WHERE { ?s <http://www.w3.org/2000/01/rdf-schema#label> ?name . }'
        rows, engine = export_rdf.query_kb(self.kb, q)
        self.assertIn("built-in", engine)
        names = {r["name"] for r in rows}
        self.assertIn("CLAIMS", names)
        self.assertIn("GET /claims", names)
        self.assertIn("PROCESS_CLAIMS", names)

    def test_sparql_subset_query_filter_and_limit(self):
        q = 'SELECT ?s ?type WHERE { ?s a ?type . FILTER(?type = <https://metis.metis-kb.org/schema/table>) } LIMIT 1'
        rows, engine = export_rdf.query_kb(self.kb, q)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "https://metis.metis-kb.org/schema/table")


if __name__ == "__main__":
    unittest.main()
