#!/usr/bin/env python3
"""Export the Metis knowledge base graph to RDF standards: Turtle, N-Triples, JSON-LD, and OWL ontology.

    python3 export_rdf.py export <kb> [--out <dir>] [--format all|turtle|ntriples|jsonld|owl]
    python3 export_rdf.py query  <kb> "<sparql_subset_query>" [--rdflib]

Formats supported:
  - Turtle (.ttl): Readable RDF syntax with prefixes, typed nodes, and RDF-star-free edge provenance via
    origin-partitioned graphs and reified statements.
  - N-Triples (.nt): Strict line-by-line triple format with complete IRI/literal escaping.
  - JSON-LD (.jsonld): Structured JSON Linked Data with @context and @graph.
  - OWL Ontology (.owl / .ttl): OWL 2 ontology defining classes for node types and object properties for relations.

Edge Provenance:
  Kept as RDF-star-free named graphs per origin (<https://metis.metis-kb.org/origin/{parsed|catalogue|ai-proposed}>)
  and reified rdf:Statement instances recording metis:origin, metis:source [E: ...], and metis:definedIn.

Claim labels (claim_labels.py): when the KB uses `{env: ...; sensitivity: ...}` labels, a link whose source cites a line above the sharing
level, or whose file is in a restricted folder, is left out of every format, with the objects only it named. The level is
`--max-sensitivity` (export) or `max_level=` in code, default `labels.share_max_sensitivity` in the profile, else `public`. With labels in
use the node and relation lists are rebuilt from what is left, not copied from ONTOLOGY.yaml. A KB with no labels exports as before.

SPARQL Query Engine:
  Includes a built-in lightweight SPARQL subset query engine supporting SELECT with Basic Graph Patterns (BGP),
  FILTER (=), and LIMIT. Note: this is a lightweight subset, NOT full SPARQL 1.1. If the optional rdflib package is
  installed, pass --rdflib for full SPARQL 1.1 query execution.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse

import yaml

# Optional guarded import of rdflib for full SPARQL 1.1 execution
try:
    import rdflib  # type: ignore
    HAVE_RDFLIB = True
except ImportError:
    HAVE_RDFLIB = False

# Base namespaces
BASE_METIS = "https://metis.metis-kb.org/schema/"
BASE_RES = "https://metis.metis-kb.org/resource/"
BASE_ORIGIN = "https://metis.metis-kb.org/origin/"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDF_STATEMENT = "http://www.w3.org/1999/02/22-rdf-syntax-ns#Statement"
RDF_SUBJECT = "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject"
RDF_PREDICATE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate"
RDF_OBJECT = "http://www.w3.org/1999/02/22-rdf-syntax-ns#object"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
OWL_ONTOLOGY = "http://www.w3.org/2002/07/owl#Ontology"
OWL_CLASS = "http://www.w3.org/2002/07/owl#Class"
OWL_OBJ_PROP = "http://www.w3.org/2002/07/owl#ObjectProperty"
OWL_VERSION = "http://www.w3.org/2002/07/owl#versionInfo"

PREFIXES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "metis": BASE_METIS,
    "kb": BASE_RES,
    "origin": BASE_ORIGIN,
}


def sanitize_id(text):
    return urllib.parse.quote(str(text or "").strip(), safe="~-._")


def node_iri(node_type, name):
    return "%s%s/%s" % (BASE_RES, sanitize_id(node_type), sanitize_id(name))


def node_key_to_iri(key):
    if ":" in str(key):
        ntype, _, name = str(key).partition(":")
        return node_iri(ntype, name)
    return "%snode/%s" % (BASE_RES, sanitize_id(key))


def type_iri(node_type):
    return "%s%s" % (BASE_METIS, sanitize_id(node_type))


def rel_iri(rel):
    return "%s%s" % (BASE_METIS, sanitize_id(rel))


def origin_graph_iri(origin):
    norm = str(origin or "unknown").strip().lower()
    return "%s%s" % (BASE_ORIGIN, sanitize_id(norm))


def escape_nt(s):
    """Escape a literal string for N-Triples according to W3C specification."""
    if s is None:
        return ""
    out = []
    for ch in str(s):
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        else:
            out.append(ch)
    return "".join(out)


def load_graph_data(kb, max_level=None):
    """Load nodes, edges, types and relations from LINK_GRAPH.yaml / ONTOLOGY.yaml or rebuild on demand. When the KB uses claim
    labels, links that cite lines above `max_level` (default: the profile's share level, else public) are left out."""
    nodes, edges, node_types, relations = _load_graph_data(kb)
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import claim_labels
    viewer = claim_labels.Viewer(kb, level=max_level or claim_labels.share_level(kb))
    if viewer.active:
        nodes, edges = claim_labels.filter_graph(viewer, nodes, edges)
        node_types, relations = {}, {}
    return nodes, edges, node_types, relations


def _load_graph_data(kb):
    link_path = os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")
    onto_path = os.path.join(kb, "CROSS-LAYER", "ONTOLOGY.yaml")
    nodes, edges, node_types, relations = [], [], {}, {}

    if os.path.isfile(link_path):
        with open(link_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
            nodes = data.get("nodes") or []
            edges = data.get("edges") or []
    if os.path.isfile(onto_path):
        with open(onto_path, encoding="utf-8") as fh:
            odata = yaml.safe_load(fh) or {}
            node_types = odata.get("node_types") or {}
            relations = odata.get("relations") or {}

    if not nodes and not edges:
        # Generate on the fly if gen_graph is available
        try:
            tools_dir = os.path.dirname(os.path.abspath(__file__))
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            import gen_graph
            n_list, e_list, _, types, rels = gen_graph.build(kb)
            nodes, edges, node_types, relations = n_list, e_list, types, rels
        except Exception:
            pass

    return nodes, edges, node_types, relations


def build_triples(kb, max_level=None):
    """Extract standard (subject, predicate, object, is_literal, graph_iri) tuples."""
    nodes, edges, node_types, relations = load_graph_data(kb, max_level)
    triples = []

    # Node declarations
    for n in nodes:
        nid = n.get("id") or ("%s:%s" % (n.get("type"), n.get("name")))
        ntype = n.get("type") or "node"
        name = n.get("name") or nid
        s_iri = node_key_to_iri(nid)
        t_iri = type_iri(ntype)

        triples.append((s_iri, RDF_TYPE, t_iri, False, None))
        triples.append((s_iri, RDFS_LABEL, name, True, None))
        triples.append((s_iri, "%sname" % BASE_METIS, name, True, None))
        triples.append((s_iri, "%snodeType" % BASE_METIS, ntype, True, None))

    # Edges & provenance
    for idx, e in enumerate(edges):
        src_iri = node_key_to_iri(e.get("from"))
        p_iri = rel_iri(e.get("rel") or "relatedTo")
        dst_iri = node_key_to_iri(e.get("to"))
        origin = e.get("origin") or "unknown"
        source = e.get("source") or ""
        defined_in = e.get("defined_in") or ""
        g_iri = origin_graph_iri(origin)

        # Primary relationship triple (in default graph and in origin named graph)
        triples.append((src_iri, p_iri, dst_iri, False, g_iri))

        # Reified statement for standard RDF provenance
        stmt_iri = "%sstatement/%d" % (BASE_RES, idx)
        triples.append((stmt_iri, RDF_TYPE, RDF_STATEMENT, False, g_iri))
        triples.append((stmt_iri, RDF_SUBJECT, src_iri, False, g_iri))
        triples.append((stmt_iri, RDF_PREDICATE, p_iri, False, g_iri))
        triples.append((stmt_iri, RDF_OBJECT, dst_iri, False, g_iri))
        triples.append((stmt_iri, "%sorigin" % BASE_METIS, origin, True, g_iri))
        if source:
            triples.append((stmt_iri, "%ssource" % BASE_METIS, source, True, g_iri))
        if defined_in:
            triples.append((stmt_iri, "%sdefinedIn" % BASE_METIS, defined_in, True, g_iri))

    return triples, nodes, edges, node_types, relations


# ---- Serializers -----------------------------------------------------------------

def to_n_triples(triples):
    """Serialize triples to strict W3C N-Triples."""
    lines = []
    for s, p, o, is_lit, _ in triples:
        if is_lit:
            lines.append('<%s> <%s> "%s" .' % (s, p, escape_nt(o)))
        else:
            lines.append('<%s> <%s> <%s> .' % (s, p, o))
    return "\n".join(lines) + ("\n" if lines else "")


def to_turtle(kb, max_level=None):
    """Serialize KB graph to W3C Turtle syntax with named graph documentation and reification."""
    nodes, edges, node_types, relations = load_graph_data(kb, max_level)
    lines = [
        "# Exported by Metis export_rdf.py on %s" % datetime.date.today().isoformat(),
        "# Edge provenance is kept as RDF-star-free named graphs per origin and reified statements.",
        "",
    ]
    for pfx, uri in sorted(PREFIXES.items()):
        lines.append("@prefix %s: <%s> ." % (pfx, uri))
    lines.append("")

    # Node resources
    lines.append("# ---- Nodes -------------------------------------------------------")
    for n in nodes:
        nid = n.get("id") or ("%s:%s" % (n.get("type"), n.get("name")))
        ntype = n.get("type") or "node"
        name = n.get("name") or nid
        s_iri = node_key_to_iri(nid)
        t_iri = type_iri(ntype)
        lines.append("<%s>" % s_iri)
        lines.append('    a <%s> ;' % t_iri)
        lines.append('    rdfs:label "%s" ;' % escape_nt(name))
        lines.append('    metis:name "%s" ;' % escape_nt(name))
        lines.append('    metis:nodeType "%s" .' % escape_nt(ntype))
        lines.append("")

    # Edges grouped by origin
    lines.append("# ---- Edges and Provenance ---------------------------------------")
    by_origin = {}
    for idx, e in enumerate(edges):
        o = e.get("origin") or "unknown"
        by_origin.setdefault(o, []).append((idx, e))

    for origin, elist in sorted(by_origin.items()):
        lines.append("# Graph Origin: %s (<%s%s>)" % (origin, BASE_ORIGIN, origin))
        for idx, e in elist:
            src_iri = node_key_to_iri(e.get("from"))
            p_iri = rel_iri(e.get("rel") or "relatedTo")
            dst_iri = node_key_to_iri(e.get("to"))
            source = e.get("source") or ""
            def_in = e.get("defined_in") or ""
            stmt_iri = "%sstatement/%d" % (BASE_RES, idx)

            lines.append("<%s> <%s> <%s> ." % (src_iri, p_iri, dst_iri))
            lines.append("<%s>" % stmt_iri)
            lines.append("    a rdf:Statement ;")
            lines.append("    rdf:subject <%s> ;" % src_iri)
            lines.append("    rdf:predicate <%s> ;" % p_iri)
            lines.append("    rdf:object <%s> ;" % dst_iri)
            lines.append('    metis:origin "%s" ;' % escape_nt(origin))
            if source:
                lines.append('    metis:source "%s" ;' % escape_nt(source))
            if def_in:
                lines.append('    metis:definedIn "%s" ;' % escape_nt(def_in))
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            lines.append("")

    return "\n".join(lines) + "\n"


def to_json_ld(kb, max_level=None):
    """Serialize KB graph to JSON-LD."""
    nodes, edges, node_types, relations = load_graph_data(kb, max_level)
    ctx = {
        "rdf": PREFIXES["rdf"],
        "rdfs": PREFIXES["rdfs"],
        "owl": PREFIXES["owl"],
        "xsd": PREFIXES["xsd"],
        "metis": PREFIXES["metis"],
        "kb": PREFIXES["kb"],
        "origin": PREFIXES["origin"],
        "label": "rdfs:label",
        "name": "metis:name",
        "nodeType": "metis:nodeType",
        "source": "metis:source",
        "definedIn": "metis:definedIn",
        "edgeOrigin": "metis:origin",
    }
    graph = []

    for n in nodes:
        nid = n.get("id") or ("%s:%s" % (n.get("type"), n.get("name")))
        ntype = n.get("type") or "node"
        name = n.get("name") or nid
        graph.append({
            "@id": node_key_to_iri(nid),
            "@type": type_iri(ntype),
            "label": name,
            "name": name,
            "nodeType": ntype,
        })

    for idx, e in enumerate(edges):
        src_iri = node_key_to_iri(e.get("from"))
        p_iri = rel_iri(e.get("rel") or "relatedTo")
        dst_iri = node_key_to_iri(e.get("to"))
        origin = e.get("origin") or "unknown"
        stmt_iri = "%sstatement/%d" % (BASE_RES, idx)

        # Primary relationship triple
        graph.append({
            "@id": src_iri,
            p_iri: {"@id": dst_iri},
        })

        item = {
            "@id": stmt_iri,
            "@type": "rdf:Statement",
            "rdf:subject": {"@id": src_iri},
            "rdf:predicate": {"@id": p_iri},
            "rdf:object": {"@id": dst_iri},
            "edgeOrigin": origin,
            "metis:graph": {"@id": origin_graph_iri(origin)},
        }
        if e.get("source"):
            item["source"] = e.get("source")
        if e.get("defined_in"):
            item["definedIn"] = e.get("defined_in")
        graph.append(item)

    doc = {"@context": ctx, "@graph": graph}
    return json.dumps(doc, indent=2, ensure_ascii=False)


def to_owl(kb, max_level=None):
    """Serialize the KB Ontology to OWL 2 (in Turtle syntax)."""
    nodes, edges, node_types, relations = load_graph_data(kb, max_level)

    lines = [
        "# Metis Knowledge Base OWL 2 Ontology",
        "# Generated by export_rdf.py on %s" % datetime.date.today().isoformat(),
        "",
        "@prefix rdf: <%s> ." % PREFIXES["rdf"],
        "@prefix rdfs: <%s> ." % PREFIXES["rdfs"],
        "@prefix owl: <%s> ." % PREFIXES["owl"],
        "@prefix xsd: <%s> ." % PREFIXES["xsd"],
        "@prefix metis: <%s> ." % PREFIXES["metis"],
        "",
        "<https://metis.metis-kb.org/schema/Ontology>",
        "    a owl:Ontology ;",
        '    rdfs:label "Metis Knowledge Base Ontology" ;',
        '    rdfs:comment "OWL 2 Ontology of node classes and relation object properties extracted from Metis graph." ;',
        '    owl:versionInfo "2.0.0" .',
        "",
        "# ---- Node Classes -------------------------------------------------",
    ]

    all_types = set(node_types.keys()) if node_types else {n.get("type") for n in nodes if n.get("type")}
    for t in sorted(all_types):
        lines.append("<%s>" % type_iri(t))
        lines.append("    a owl:Class ;")
        lines.append('    rdfs:label "%s" ;' % escape_nt(t))
        lines.append('    rdfs:comment "Node class for %s objects in the Metis knowledge base." .' % escape_nt(t))
        lines.append("")

    lines.append("# ---- Object Properties (Relations) --------------------------------")
    all_rels = set()
    if relations:
        for k in relations.keys():
            # relation key format: "type -rel-> type"
            m = re.search(r"-(.+?)->", k)
            if m:
                all_rels.add(m.group(1).strip())
    all_rels.update(e.get("rel") for e in edges if e.get("rel"))

    for r in sorted(all_rels):
        lines.append("<%s>" % rel_iri(r))
        lines.append("    a owl:ObjectProperty ;")
        lines.append('    rdfs:label "%s" ;' % escape_nt(r))
        lines.append('    rdfs:comment "Relationship %s connecting Metis graph nodes." .' % escape_nt(r))
        lines.append("")

    return "\n".join(lines) + "\n"


def export_all(kb, out_dir=None, max_level=None):
    """Export all RDF representations to destination directory."""
    out = out_dir or os.path.join(kb, ".metis", "exports", "rdf")
    os.makedirs(out, exist_ok=True)

    ttl_text = to_turtle(kb, max_level)
    triples, _, _, _, _ = build_triples(kb, max_level)
    nt_text = to_n_triples(triples)
    jsonld_text = to_json_ld(kb, max_level)
    owl_text = to_owl(kb, max_level)

    files = {
        "graph.ttl": ttl_text,
        "graph.nt": nt_text,
        "graph.jsonld": jsonld_text,
        "ontology.owl": owl_text,
        "ontology.ttl": owl_text,
    }

    written = []
    for fname, content in files.items():
        p = os.path.join(out, fname)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        written.append(p)

    return written


# ---- Tiny Built-in SPARQL-Subset Query Engine -----------------------------------

def expand_term(term):
    """Expand a prefixed term like metis:table or <http...> to full IRI, or literal."""
    t = term.strip()
    if t.startswith("<") and t.endswith(">"):
        return t[1:-1]
    if t.startswith('"') and t.endswith('"'):
        return t[1:-1]
    if t.startswith("'") and t.endswith("'"):
        return t[1:-1]
    if ":" in t and not t.startswith("?"):
        pfx, _, name = t.partition(":")
        if pfx in PREFIXES:
            return PREFIXES[pfx] + name
        if pfx == "a":
            return RDF_TYPE
    if t == "a":
        return RDF_TYPE
    return t


def parse_sparql_subset(query_str):
    """Parse SPARQL subset: SELECT ?v1 ?v2 WHERE { ?s ?p ?o . ... FILTER(?x = "val") } LIMIT N."""
    q = query_str.strip()

    # Reject unsupported SPARQL constructs so callers can fall back to rdflib
    unsupported_patterns = [
        (r"(?i)\bOPTIONAL\b", "OPTIONAL"),
        (r"(?i)\bUNION\b", "UNION"),
        (r"(?i)\bORDER\b", "ORDER"),
        (r"(?i)\bGROUP\b", "GROUP"),
        (r"(?i)\bCOUNT\b", "COUNT"),
        (r"(?i)\bPREFIX\b", "PREFIX"),
        (r"(?i)\bASK\b", "ASK"),
        (r"(?i)\bregex\b", "regex"),
        (r"!=", "!="),
        (r";", ";"),
    ]
    for pat, name in unsupported_patterns:
        if re.search(pat, q):
            raise ValueError("Unsupported SPARQL construct '%s' in built-in subset engine; use --rdflib for full SPARQL 1.1" % name)

    m = re.match(r"(?i)\s*SELECT\s+(.*?)\s+WHERE\s*\{(.*?)\}(?:\s*LIMIT\s+(\d+))?\s*$", q, re.S)
    if not m:
        raise ValueError("Invalid SPARQL subset query. Supported format: SELECT ?v1 ... WHERE { ?s ?p ?o . } [LIMIT N]")

    var_part = m.group(1).strip()
    where_part = m.group(2).strip()
    limit_part = m.group(3)

    if var_part == "*":
        select_vars = None
    else:
        select_vars = [v.lstrip("?").strip() for v in re.findall(r"\?([a-zA-Z0-9_]+)", var_part)]

    limit = int(limit_part) if limit_part else None

    # Parse triples and filters inside WHERE
    patterns = []
    filters = []

    # Extract FILTER clauses
    filter_matches = re.finditer(r"(?i)FILTER\s*\(\s*\?([a-zA-Z0-9_]+)\s*=\s*([^)]+)\)", where_part)
    for fm in filter_matches:
        f_var = fm.group(1)
        f_val = expand_term(fm.group(2).strip())
        filters.append((f_var, f_val))

    where_no_filters = re.sub(r"(?i)FILTER\s*\([^)]+\)", "", where_part)

    # Split triples by '.' outside IRIs and literals
    raw_triples = split_statements(where_no_filters)
    for rt in raw_triples:
        tokens = tokenize_triple(rt)
        if len(tokens) >= 3:
            s_tok = tokens[0]
            p_tok = tokens[1]
            o_tok = " ".join(tokens[2:])
            patterns.append((s_tok, p_tok, o_tok))

    return select_vars, patterns, filters, limit


def split_statements(text):
    """Split text on '.' delimiter, ignoring dots inside <...> or quotes."""
    statements, current = [], []
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
            elif ch == '.':
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
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
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements


def tokenize_triple(text):
    """Tokenize a single triple statement into terms preserving <...> and quotes."""
    tokens = []
    current = []
    in_angle, in_quote, quote_ch = False, False, None
    for ch in text:
        if not in_angle and not in_quote:
            if ch.isspace():
                tok = "".join(current).strip()
                if tok:
                    tokens.append(tok)
                current = []
            elif ch == '<':
                in_angle = True
                current.append(ch)
            elif ch in ('"', "'"):
                in_quote = True
                quote_ch = ch
                current.append(ch)
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
    tok = "".join(current).strip()
    if tok:
        tokens.append(tok)
    return tokens


def query_triples_subset(triples, query_str):
    """Execute a SPARQL subset query over triples list in pure Python."""
    select_vars, patterns, filters, limit = parse_sparql_subset(query_str)

    # Match Basic Graph Patterns
    # State is a list of variable bindings: [ {var_name: value}, ... ]
    bindings = [{}]

    for s_pat, p_pat, o_pat in patterns:
        next_bindings = []
        for current_env in bindings:
            # For each triple, test match against pattern given current_env
            for s, p, o, is_lit, _ in triples:
                new_env = dict(current_env)
                match = True

                # Match subject
                if s_pat.startswith("?"):
                    v = s_pat[1:]
                    if v in new_env:
                        if new_env[v] != s:
                            match = False
                    else:
                        new_env[v] = s
                else:
                    if expand_term(s_pat) != s:
                        match = False

                if not match:
                    continue

                # Match predicate
                if p_pat.startswith("?"):
                    v = p_pat[1:]
                    if v in new_env:
                        if new_env[v] != p:
                            match = False
                    else:
                        new_env[v] = p
                else:
                    if expand_term(p_pat) != p:
                        match = False

                if not match:
                    continue

                # Match object
                if o_pat.startswith("?"):
                    v = o_pat[1:]
                    if v in new_env:
                        if new_env[v] != o:
                            match = False
                    else:
                        new_env[v] = o
                else:
                    exp_o = expand_term(o_pat)
                    if exp_o != o:
                        match = False

                if match:
                    next_bindings.append(new_env)
        bindings = next_bindings

    # Apply filters
    filtered = []
    for env in bindings:
        keep = True
        for f_var, f_val in filters:
            if env.get(f_var) != f_val:
                keep = False
                break
        if keep:
            filtered.append(env)

    # Project variables
    results = []
    for env in filtered:
        if select_vars:
            res_row = {v: env.get(v) for v in select_vars}
        else:
            res_row = env
        if res_row not in results:
            results.append(res_row)

    if limit is not None:
        results = results[:limit]

    return results


def query_kb(kb, query_str, use_rdflib=False, max_level=None):
    """Execute SPARQL query over KB graph. State plainly that built-in engine is a subset."""
    if use_rdflib and HAVE_RDFLIB:
        g = rdflib.Graph()
        ttl = to_turtle(kb, max_level)
        g.parse(data=ttl, format="turtle")
        qres = g.query(query_str)
        if getattr(qres, "type", None) == "ASK":
            ans = bool(getattr(qres, "askAnswer", qres))
            return [{"ask": ans}], "rdflib (full SPARQL 1.1)"
        if getattr(qres, "type", None) != "SELECT" and getattr(qres, "vars", None) is None:
            return [{"result": bool(qres)}], "rdflib (full SPARQL 1.1)"
        results = []
        for row in qres:
            row_dict = {}
            for var, val in zip(qres.vars, row):
                row_dict[str(var)] = str(val)
            results.append(row_dict)
        return results, "rdflib (full SPARQL 1.1)"

    triples, _, _, _, _ = build_triples(kb, max_level)
    results = query_triples_subset(triples, query_str)
    return results, "built-in SPARQL-subset engine (BGP, FILTER =, LIMIT)"


# ---- CLI -------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a_exp = sub.add_parser("export", help="Export KB graph to RDF")
    a_exp.add_argument("kb", help="Path to knowledge base")
    a_exp.add_argument("--out", help="Output directory or file")
    a_exp.add_argument("--format", choices=["all", "turtle", "ntriples", "jsonld", "owl"], default="all")
    a_exp.add_argument("--max-sensitivity", help="highest claim-label level to export (default: profile labels.share_max_sensitivity, else public)")

    a_qry = sub.add_parser("query", help="Query KB with SPARQL subset")
    a_qry.add_argument("kb", help="Path to knowledge base")
    a_qry.add_argument("query", help="SPARQL SELECT query")
    a_qry.add_argument("--rdflib", action="store_true", help="Use rdflib if installed for full SPARQL 1.1")
    a_qry.add_argument("--max-sensitivity", help="highest claim-label level to query (default: profile labels.share_max_sensitivity, else public)")

    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)

    if args.cmd == "export":
        fmt = args.format
        if fmt == "all":
            written = export_all(kb, args.out, args.max_sensitivity)
            for w in written:
                print("Exported: %s" % w)
        elif fmt == "turtle":
            text = to_turtle(kb, args.max_sensitivity)
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                print("Exported Turtle -> %s" % args.out)
            else:
                sys.stdout.write(text)
        elif fmt == "ntriples":
            triples, _, _, _, _ = build_triples(kb, args.max_sensitivity)
            text = to_n_triples(triples)
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                print("Exported N-Triples -> %s" % args.out)
            else:
                sys.stdout.write(text)
        elif fmt == "jsonld":
            text = to_json_ld(kb, args.max_sensitivity)
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                print("Exported JSON-LD -> %s" % args.out)
            else:
                sys.stdout.write(text)
        elif fmt == "owl":
            text = to_owl(kb, args.max_sensitivity)
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                print("Exported OWL Ontology -> %s" % args.out)
            else:
                sys.stdout.write(text)
        return 0

    elif args.cmd == "query":
        rows, engine_name = query_kb(kb, args.query, use_rdflib=args.rdflib, max_level=args.max_sensitivity)
        print("# Engine: %s" % engine_name)
        print("# Results: %d rows" % len(rows))
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
