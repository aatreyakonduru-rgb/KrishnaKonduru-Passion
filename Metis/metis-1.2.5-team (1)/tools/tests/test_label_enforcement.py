"""Claim labels are enforced when content is served: one test per surface, each proving that a restricted line is withheld from an
uncleared role, shown to a cleared one, and that a KB with no labels behaves as it did before."""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import answers  # noqa: E402
import claim_labels  # noqa: E402
import context_pack  # noqa: E402
import export_rdf  # noqa: E402
import gen_graph  # noqa: E402
import kb_gate  # noqa: E402
import kb_search  # noqa: E402
import mcp_server  # noqa: E402
import okf_bundle  # noqa: E402
import screens_chat as SC  # noqa: E402
import screens_search as SS  # noqa: E402
import shared_index  # noqa: E402
import ui_common as C  # noqa: E402

SECRET = "sealed cabinet"          # the text of the restricted line that must never reach an uncleared role
NODE = "SEALED_CABINET"            # a graph object named only by a link that cites the restricted line
PASSWORD = "Hunter2hunter"         # a line sensitive.py forces to restricted without any label
PUBLIC = "settled within 30 days"
LOW, HIGH = "Pat Lee", "Ana Lead"

LABELLED = """---
title: Ops
sensitivity: public
---
# Ops

- Invoices are %s of receipt. [E: file:ops.txt "30 days"]
- The zebra vault rotation key is stored in the %s. [E: file:ops.txt "vault"]%s
""" % (PUBLIC, SECRET, " {sensitivity: restricted}")

# a page sensitive.py would also keep out of packs and search whole; kept apart so the labelled page above stays servable
CREDS = """---
title: Creds
sensitivity: public
---
# Creds

- Admin login: password = %s [E: file:ops.txt "Hunter"]
""" % PASSWORD


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def make_kb(root, labelled=True, lock=False):
    kb = os.path.join(root, "KB" if labelled else "PLAIN")
    prof = {"product": {"name": "Ops KB" if labelled else "Plain KB"}, "owners": {"kb_owner": HIGH}}
    if labelled:
        prof["labels"] = {"restricted_folders": ["restricted"]}
    write(os.path.join(kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
    write(os.path.join(kb, "_EVIDENCE", "files", "ops.txt"), "30 days vault Hunter\n")
    def strip(t):
        return t.replace(" {sensitivity: restricted}", "").replace("sensitivity: public\n", "status: stable\n")
    write(os.path.join(kb, "context", "ops.md"), LABELLED if labelled else strip(LABELLED))
    write(os.path.join(kb, "context", "creds.md"), CREDS if labelled else strip(CREDS))
    write(os.path.join(kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))
    nodes = [{"id": "job:NIGHTLY", "type": "job", "name": "NIGHTLY"}, {"id": "table:" + NODE, "type": "table", "name": NODE},
             {"id": "table:INVOICES", "type": "table", "name": "INVOICES"}]
    edges = [{"from": "job:NIGHTLY", "rel": "writes", "to": "table:" + NODE, "source": '[E: kb:context/ops.md:8 "zebra vault"]',
              "defined_in": "context/x.links.yaml", "origin": "ai-proposed"},
             {"from": "job:NIGHTLY", "rel": "reads", "to": "table:INVOICES", "source": '[E: file:ops.txt "30 days"]',
              "defined_in": "context/x.links.yaml", "origin": "ai-proposed"}]
    write(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": nodes, "edges": edges}))
    if lock:
        kb_gate.lock(kb, HIGH)
    return kb


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = make_kb(self.tmp)
        self.plain = make_kb(self.tmp, labelled=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assertHidden(self, text, what=SECRET):
        self.assertNotIn(what.lower(), str(text).lower())

    def assertShown(self, text, what=SECRET):
        self.assertIn(what.lower(), str(text).lower())


class Pack(Base):
    def test_withheld_for_low_shown_for_high_and_counted(self):
        low = context_pack.build(self.kb, files=["context/ops.md"], role=LOW)
        self.assertHidden(low["text"])
        self.assertHidden(low["text"], PASSWORD)
        self.assertShown(low["text"], PUBLIC)
        self.assertIn("withheld (reason: label)", low["text"])
        self.assertGreaterEqual(low["withheld"], 2)
        high = context_pack.build(self.kb, files=["context/ops.md"], role=HIGH)
        self.assertShown(high["text"])
        self.assertNotIn("reason: label", high["text"])

    def test_default_role_is_the_lowest(self):
        self.assertHidden(context_pack.build(self.kb, files=["context/ops.md"])["text"])

    def test_links_that_cite_withheld_lines_are_left_out(self):
        low = context_pack.build(self.kb, seeds=["job:NIGHTLY"], role=LOW)["text"]
        self.assertHidden(low, NODE)
        self.assertShown(context_pack.build(self.kb, seeds=["job:NIGHTLY"], role=HIGH)["text"], NODE)

    def test_no_labels_means_nothing_changes(self):
        base = context_pack.build(self.plain, files=["context/ops.md"], stale_marks=False)
        for role in (None, "", LOW, HIGH):
            p = context_pack.build(self.plain, files=["context/ops.md"], role=role, stale_marks=False)
            self.assertEqual(p["text"], base["text"])
            self.assertEqual(p["withheld"], 0)
        self.assertShown(base["text"])
        self.assertNotIn("reason: label", base["text"])


class Answers(Base):
    Q = "What is stored for the zebra vault rotation?"

    def test_local_answer_withholds_and_says_so(self):
        text = answers.compose(self.kb, self.Q, who=LOW)[0]
        self.assertHidden(text)
        self.assertIn("withheld by label", text)
        high = answers.compose(self.kb, self.Q, who=HIGH)[0]
        self.assertShown(high)
        self.assertNotIn("withheld by label", high)

    def test_ask_uses_the_asking_users_clearance(self):
        low = answers.ask(self.kb, self.Q, LOW)
        high = answers.ask(self.kb, self.Q, HIGH)
        self.assertHidden(answers.answer_text(self.kb, low))
        self.assertShown(answers.answer_text(self.kb, high))

    def test_profile_clearance_can_raise_a_name(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(
            {"owners": {"kb_owner": HIGH}, "labels": {"restricted_folders": ["restricted"], "clearance": {LOW: "restricted"}}}))
        self.assertShown(answers.compose(self.kb, self.Q, who=LOW)[0])

    def test_no_labels_means_nothing_changes(self):
        base = answers.compose(self.plain, self.Q)[0]
        self.assertShown(base)
        for who in ("", LOW, HIGH):
            self.assertEqual(answers.compose(self.plain, self.Q, who=who)[0], base)
        self.assertNotIn("withheld by label", base)


class Search(Base):
    def hits(self, who, kb=None):
        r = kb_search.search(kb or self.kb, "zebra vault rotation key", who=who)["results"]
        return json.dumps(r)

    def test_kb_search(self):
        self.assertHidden(self.hits(LOW))
        self.assertHidden(self.hits(""))
        self.assertShown(self.hits(HIGH))

    def test_kb_search_keeps_visible_lines_of_a_partly_withheld_page(self):
        r = kb_search.search(self.kb, "invoices settled", who=LOW)["results"]
        self.assertEqual([x["path"] for x in r], ["context/ops.md"])
        self.assertHidden(json.dumps(r))

    def test_kb_search_no_labels_means_nothing_changes(self):
        base = self.hits(None, self.plain)
        self.assertShown(base)
        self.assertEqual(self.hits(LOW, self.plain), base)

    def test_search_screen(self):
        low = SS.search_view(C.Ctx(self.kb, "tok", LOW), {"q": "zebra vault rotation key"})
        high = SS.search_view(C.Ctx(self.kb, "tok", HIGH), {"q": "zebra vault rotation key"})
        self.assertHidden(low)
        self.assertShown(high)
        plain = SS.search_view(C.Ctx(self.plain, "tok", LOW), {"q": "zebra vault rotation key"})
        self.assertShown(plain)


class Chat(Base):
    def setUp(self):
        super().setUp()
        SC.THREADS.clear()

    def tearDown(self):
        SC.THREADS.clear()
        super().tearDown()

    def chat(self, kb, user):
        ctx = C.Ctx(kb, "tok", user)
        SC.act_chat_ask(ctx, {"question": "What is stored for the zebra vault rotation?"})
        return SC.chat_view(ctx, {})

    def test_chat_withholds_for_low_and_shows_for_high(self):
        self.assertHidden(self.chat(self.kb, LOW))
        SC.THREADS.clear()
        self.assertShown(self.chat(self.kb, HIGH))

    def test_chat_no_labels_means_nothing_changes(self):
        self.assertShown(self.chat(self.plain, LOW))


class Mcp(Base):
    def setUp(self):
        super().setUp()
        self._env = {k: os.environ.pop(k, None) for k in ("METIS_USER", "METIS_ROLE")}

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        super().tearDown()

    def call(self, kb, name, **args):
        args.setdefault("no_telemetry", True)
        r = mcp_server.handle(kb, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]
        return r["content"][0]["text"]

    def test_default_identity_is_the_lowest(self):
        self.assertEqual(mcp_server.identity(), "")
        self.assertHidden(self.call(self.kb, "metis_context_pack", files=["context/ops.md"]))

    def test_identity_comes_from_the_environment(self):
        os.environ["METIS_USER"] = LOW
        self.assertHidden(self.call(self.kb, "metis_context_pack", files=["context/ops.md"]))
        os.environ["METIS_USER"] = HIGH
        self.assertShown(self.call(self.kb, "metis_context_pack", files=["context/ops.md"]))
        del os.environ["METIS_USER"]
        os.environ["METIS_ROLE"] = "lead"
        self.assertShown(self.call(self.kb, "metis_context_pack", files=["context/ops.md"]))

    def test_no_tool_argument_can_raise_clearance(self):
        os.environ["METIS_USER"] = LOW
        out = self.call(self.kb, "metis_context_pack", files=["context/ops.md"], by=HIGH, role="lead", user=HIGH, who=HIGH,
                        max_sensitivity="restricted")
        self.assertHidden(out)

    def test_find_nodes_hides_objects_named_only_by_withheld_links(self):
        os.environ["METIS_USER"] = LOW
        self.assertHidden(self.call(self.kb, "metis_find_nodes", query="sealed"), NODE)
        os.environ["METIS_USER"] = HIGH
        self.assertShown(self.call(self.kb, "metis_find_nodes", query="sealed"), NODE)

    def test_no_labels_means_nothing_changes(self):
        base = self.call(self.plain, "metis_context_pack", files=["context/ops.md"], no_signals=True)
        self.assertShown(base)
        os.environ["METIS_USER"] = LOW
        self.assertShown(self.call(self.plain, "metis_context_pack", files=["context/ops.md"], no_signals=True))
        self.assertShown(self.call(self.plain, "metis_find_nodes", query="sealed"), NODE)


class Sharing(Base):
    def dump(self, db):
        con = sqlite3.connect(db)
        try:
            return "\n".join(con.iterdump())
        finally:
            con.close()

    def test_shared_index_defaults_to_public(self):
        kb = make_kb(os.path.join(self.tmp, "locked"), lock=True)
        db = os.path.join(self.tmp, "a.sqlite")
        shared_index.register(db, kb)
        text = self.dump(db)
        self.assertHidden(text)
        self.assertHidden(text, PASSWORD)
        self.assertHidden(text, NODE)
        self.assertShown(text, PUBLIC)
        db2 = os.path.join(self.tmp, "b.sqlite")
        shared_index.register(db2, kb, max_level="restricted")
        self.assertShown(self.dump(db2))
        self.assertShown(self.dump(db2), NODE)

    def test_shared_index_cli_option_and_profile_default(self):
        kb = make_kb(os.path.join(self.tmp, "locked"), lock=True)
        db = os.path.join(self.tmp, "c.sqlite")
        with contextlib.redirect_stdout(io.StringIO()):
            shared_index.main(["register", db, kb])
        self.assertHidden(self.dump(db))
        db2 = os.path.join(self.tmp, "c2.sqlite")
        with contextlib.redirect_stdout(io.StringIO()):
            shared_index.main(["register", db2, kb, "--max-sensitivity", "restricted"])
        self.assertShown(self.dump(db2))

    def test_shared_index_no_labels_means_nothing_changes(self):
        kb = make_kb(os.path.join(self.tmp, "locked"), labelled=False, lock=True)
        db = os.path.join(self.tmp, "d.sqlite")
        shared_index.register(db, kb)
        self.assertShown(self.dump(db))
        self.assertShown(self.dump(db), NODE)

    def test_export_rdf(self):
        for text in (export_rdf.to_turtle(self.kb), export_rdf.to_json_ld(self.kb)):
            self.assertHidden(text, NODE)
            self.assertHidden(text, SECRET)
        self.assertShown(export_rdf.to_turtle(self.kb, max_level="restricted"), NODE)
        self.assertShown(export_rdf.to_json_ld(self.kb, max_level="restricted"), NODE)

    def test_export_rdf_no_labels_means_nothing_changes(self):
        self.assertShown(export_rdf.to_turtle(self.plain), NODE)
        self.assertEqual(export_rdf.to_turtle(self.plain), export_rdf.to_turtle(self.plain, max_level="restricted"))

    def blob(self, out):
        parts = []
        for d, _, fs in os.walk(out):
            for f in fs:
                with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                    parts.append(fh.read())
        return "\n".join(parts)

    def test_okf_bundle(self):
        out, _ = okf_bundle.bundle(self.kb, os.path.join(self.tmp, "o1"))
        text = self.blob(out)
        self.assertHidden(text)
        self.assertHidden(text, PASSWORD)
        self.assertHidden(text, NODE)
        self.assertShown(text, PUBLIC)
        out, _ = okf_bundle.bundle(self.kb, os.path.join(self.tmp, "o2"), max_level="restricted")
        self.assertShown(self.blob(out))

    def test_okf_bundle_no_labels_means_nothing_changes(self):
        out, _ = okf_bundle.bundle(self.plain, os.path.join(self.tmp, "o3"))
        self.assertShown(self.blob(out))
        self.assertShown(self.blob(out), NODE)

    def test_profile_can_raise_the_sharing_level(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(
            {"owners": {"kb_owner": HIGH}, "labels": {"restricted_folders": ["restricted"], "share_max_sensitivity": "restricted"}}))
        self.assertShown(export_rdf.to_turtle(self.kb), NODE)


class GraphOrigin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def link(self, **extra):
        d = {"from": {"type": "job", "name": "A"}, "rel": "writes", "to": {"type": "table", "name": "B"},
             "source": '[E: file:r.txt "pets have owners"]'}
        d.update(extra)
        return d

    def origins(self, name, **extra):
        write(os.path.join(self.kb, "m", name), yaml.safe_dump({"links": [self.link(**extra)]}))
        edges = gen_graph.build(self.kb)[1]
        os.remove(os.path.join(self.kb, "m", name))
        return [e["origin"] for e in edges]

    def test_a_hand_written_link_cannot_claim_parsed_or_catalogue(self):
        self.assertEqual(self.origins("x.links.yaml", origin="parsed"), ["ai-proposed"])
        self.assertEqual(self.origins("x.links.yaml", origin="catalogue"), ["ai-proposed"])
        self.assertEqual(self.origins("x.links.yaml"), ["ai-proposed"])

    def test_file_name_rule_stays_and_a_link_may_only_lower_itself(self):
        self.assertEqual(self.origins("parsed.links.yaml"), ["parsed"])
        self.assertEqual(self.origins("catalog.links.yaml"), ["catalogue"])
        self.assertEqual(self.origins("parsed.links.yaml", origin="ai-proposed"), ["ai-proposed"])
        self.assertEqual(self.origins("parsed.links.yaml", origin="catalogue"), ["parsed"])


class Audit(Base):
    def test_clean_kb_passes_and_checks_something(self):
        res = claim_labels.audit(self.kb)
        self.assertTrue(res["active"])
        self.assertEqual(res["leaks"], [])
        self.assertGreater(res["checked"], 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(claim_labels.main(["audit", self.kb]), 0)
        self.assertNotIn("LEAK", out.getvalue())

    def test_audit_exits_1_on_a_leak_and_never_prints_the_text(self):
        line = "- The zebra vault rotation key is stored in the %s." % SECRET
        with mock.patch.object(context_pack, "build", return_value={"text": line}):
            res = claim_labels.audit(self.kb)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = claim_labels.main(["audit", self.kb])
        self.assertTrue(any(l["surface"] == "context_pack" for l in res["leaks"]))
        self.assertEqual(code, 1)
        self.assertIn("LEAK context_pack", out.getvalue())
        self.assertHidden(out.getvalue())

    def test_audit_catches_a_leaking_export(self):
        with mock.patch.object(export_rdf, "to_turtle", return_value="- The zebra vault rotation key is stored in the %s." % SECRET), \
                mock.patch.object(export_rdf, "to_json_ld", return_value="{}"):
            res = claim_labels.audit(self.kb)
        self.assertTrue(any(l["surface"] == "export_rdf" for l in res["leaks"]))

    def test_no_labels_nothing_to_audit(self):
        self.assertFalse(claim_labels.audit(self.plain)["active"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(claim_labels.main(["audit", self.plain]), 0)

    def test_a_line_sensitive_py_forces_to_restricted_stays_withheld(self):
        a = claim_labels.analyse_page(self.kb, "context/creds.md")
        forced = [r for r in a["lines"].values() if r["forced_level"] == "restricted"]
        self.assertTrue(forced)
        self.assertHidden(context_pack.build(self.kb, files=["context/ops.md", "context/creds.md"], role=LOW)["text"], PASSWORD)


if __name__ == "__main__":
    unittest.main()
