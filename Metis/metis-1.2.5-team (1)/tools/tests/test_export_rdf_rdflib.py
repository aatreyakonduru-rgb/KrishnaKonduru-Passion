import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import export_rdf  # noqa: E402

try:
    import rdflib  # noqa: E402
except ImportError:
    rdflib = None

NODES = [
    {"id": "table:orders", "type": "table", "name": "orders"},
    {"id": 'table:odd "name"\\ with\nnewline\ttab', "type": "table", "name": 'odd "name"\\ with\nnewline\ttab'},
    {"id": "class:Ünïcode-名前", "type": "class", "name": "Ünïcode-名前"},
    {"id": "endpoint:GET /a/{id}?x=1&y=<2>#frag", "type": "endpoint", "name": "GET /a/{id}?x=1&y=<2>#frag"},
    {"id": "class:Emoji\U0001F600", "type": "class", "name": "Emoji\U0001F600"},
]
EDGES = [
    {"from": "table:orders", "rel": "reads", "to": 'table:odd "name"\\ with\nnewline\ttab', "origin": "parsed",
     "source": '[E: r/a.sql:1 "x"]', "defined_in": "db\\x.yaml"},
    {"from": "class:Ünïcode-名前", "rel": "uses", "to": "endpoint:GET /a/{id}?x=1&y=<2>#frag", "origin": "catalogue",
     "source": '[E: r/b.java:2 "e"]'},
    {"from": "class:Emoji\U0001F600", "rel": "uses", "to": "table:orders", "origin": "ai-proposed", "source": '[E: r/c.java:3 "z"]'},
]


def literal_key(o, is_lit):
    return ("L" if is_lit else "U", str(o))


@unittest.skipUnless(rdflib, "rdflib not installed")
class ExportRdfWithRdflibTest(unittest.TestCase):
    """Parses the real serialiser output with rdflib and compares with the built-in engine."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.kb = os.path.join(cls.tmp, "kb")
        os.makedirs(os.path.join(cls.kb, "CROSS-LAYER"))
        os.makedirs(os.path.join(cls.kb, ".metis"))
        with open(os.path.join(cls.kb, ".metis", "kb-profile.yaml"), "w", encoding="utf-8") as fh:
            fh.write("product: {name: Fx}\n")
        with open(os.path.join(cls.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump({"nodes": NODES, "edges": EDGES}, fh, allow_unicode=True)
        triples = export_rdf.build_triples(cls.kb)[0]
        cls.triples = triples
        cls.expected = {(s, p, literal_key(o, lit)) for s, p, o, lit, _ in triples}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    @staticmethod
    def as_set(graph):
        return {(str(s), str(p), literal_key(o, isinstance(o, rdflib.Literal))) for s, p, o in graph}

    def test_ntriples_parse_and_equal_builtin_triples(self):
        g = rdflib.Graph()
        g.parse(data=export_rdf.to_n_triples(self.triples), format="nt")
        self.assertEqual(self.as_set(g), self.expected)

    def test_turtle_parse_and_equal_builtin_triples(self):
        g = rdflib.Graph()
        g.parse(data=export_rdf.to_turtle(self.kb), format="turtle")
        self.assertEqual(self.as_set(g), self.expected)

    def test_jsonld_parses_and_carries_nodes_and_reified_statements(self):
        g = rdflib.Graph()
        g.parse(data=export_rdf.to_json_ld(self.kb), format="json-ld")
        got = self.as_set(g)
        # All expected triples (node declarations, reified statements, and direct edge triples) must be present
        self.assertTrue(self.expected <= got, sorted(self.expected - got)[:3])
        # Ensure metis:graph is present as an IRI resource, not a literal string
        graph_preds = {o for s, p, o in got if p == "https://metis.metis-kb.org/schema/graph"}
        self.assertTrue(all(k[0] == "U" for k in graph_preds), "metis:graph must be an IRI")

    def test_owl_parses_with_all_classes_and_properties(self):
        g = rdflib.Graph()
        g.parse(data=export_rdf.to_owl(self.kb), format="turtle")
        classes = {str(s) for s in g.subjects(rdflib.RDF.type, rdflib.OWL.Class)}
        props = {str(s) for s in g.subjects(rdflib.RDF.type, rdflib.OWL.ObjectProperty)}
        self.assertEqual(len(list(g.subjects(rdflib.RDF.type, rdflib.OWL.Ontology))), 1)
        self.assertEqual(classes, {export_rdf.type_iri(t) for t in ("table", "class", "endpoint")})
        self.assertEqual(props, {export_rdf.rel_iri("reads"), export_rdf.rel_iri("uses")})

    def test_owl_extracts_relation_names_with_spaces_from_ontology(self):
        onto_path = os.path.join(self.kb, "CROSS-LAYER", "ONTOLOGY.yaml")
        with open(onto_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump({
                "node_types": {"endpoint": 1, "class": 1, "table": 1},
                "relations": {
                    "endpoint -handled by-> class": 1,
                    "class -stored in-> table": 1,
                    "endpoint -reads-> table": 1,
                }
            }, fh)
        try:
            g = rdflib.Graph()
            g.parse(data=export_rdf.to_owl(self.kb), format="turtle")
            props = {str(s) for s in g.subjects(rdflib.RDF.type, rdflib.OWL.ObjectProperty)}
            self.assertIn(export_rdf.rel_iri("handled by"), props)
            self.assertIn(export_rdf.rel_iri("stored in"), props)
            self.assertIn(export_rdf.rel_iri("reads"), props)
        finally:
            if os.path.isfile(onto_path):
                os.remove(onto_path)

    def test_builtin_sparql_subset_raises_on_unsupported_constructs(self):
        unsupported = [
            "SELECT ?s WHERE { ?s a :table . OPTIONAL { ?s :x ?y } }",
            "SELECT ?s WHERE { { ?s a :table } UNION { ?s a :class } }",
            "SELECT ?s WHERE { ?s a :table } ORDER BY ?s",
            "SELECT (COUNT(?s) AS ?c) WHERE { ?s a :table }",
            "PREFIX metis: <https://metis.metis-kb.org/schema/> SELECT ?s WHERE { ?s a metis:table }",
            "ASK { ?s a :table }",
            "SELECT ?s WHERE { ?s a :table . FILTER(regex(?s, 'orders')) }",
            "SELECT ?s WHERE { ?s a ?t . FILTER(?t != :table) }",
            "SELECT ?s WHERE { ?s a :table ; rdfs:label ?l . }",
        ]
        for q in unsupported:
            with self.assertRaises(ValueError, msg="Expected ValueError for: " + q):
                export_rdf.query_triples_subset(self.triples, q)

    def test_query_kb_ask_with_rdflib(self):
        rows, engine = export_rdf.query_kb(self.kb, "ASK { ?s a <https://metis.metis-kb.org/schema/table> }", use_rdflib=True)
        self.assertIn("rdflib", engine)
        self.assertEqual(rows, [{"ask": True}])

    def rows_both(self, query):
        sub = export_rdf.query_triples_subset(self.triples, query)
        full, engine = export_rdf.query_kb(self.kb, query, use_rdflib=True)
        self.assertIn("rdflib", engine)
        key = lambda rows: sorted(json.dumps(r, sort_keys=True) for r in rows)
        return key(sub), key(full)

    def test_five_sparql_queries_agree_between_builtin_and_rdflib(self):
        queries = [
            "SELECT ?s WHERE { ?s a <%s> . }" % export_rdf.type_iri("table"),
            "SELECT ?a ?b WHERE { ?a <%s> ?b . }" % export_rdf.rel_iri("uses"),
            'SELECT ?s WHERE { ?s metis:name "orders" . }',
            'SELECT ?st ?src WHERE { ?st metis:origin "parsed" . ?st metis:source ?src . }',
            "SELECT ?st WHERE { ?st rdf:subject <%s> . ?st rdf:object ?o . }" % export_rdf.node_key_to_iri("table:orders"),
        ]
        for q in queries:
            sub, full = self.rows_both(q)
            self.assertEqual(sub, full, q)
            self.assertTrue(sub, "query returned no rows, so it proves nothing: " + q)


if __name__ == "__main__":
    unittest.main()
