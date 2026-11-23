import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import gen_graph  # noqa: E402
import graph_store  # noqa: E402
import kb_coverage  # noqa: E402
import sql_links  # noqa: E402

HAVE = sql_links.load_sqlglot()[0] is not None


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


@unittest.skipUnless(HAVE, "sqlglot is not installed")
class SqlLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({
            "product": {"name": "T"}, "sources": {"workspace_root": self.tmp, "repos": {"app": "app-repo"}}}))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def sql(self, name, text):
        write(os.path.join(self.tmp, "app-repo", name), text)

    def links(self):
        res = sql_links.build(self.kb)
        return {(l["from"]["name"], l["rel"], l["to"]["name"]) for l in res["links"]}, res

    def test_dbt_model_reads_ref_and_source(self):
        self.sql("models/stg_orders.sql", "{{ config(materialized='view') }}\nselect *\nfrom {{ source('ecom', 'raw_orders') }}\n")
        self.sql("models/orders.sql", "select o.id\nfrom {{ ref('stg_orders') }} o\n")
        got, res = self.links()
        self.assertEqual(got, {("stg_orders", "reads", "ecom.raw_orders"), ("orders", "reads", "stg_orders")})
        self.assertEqual(res["links"][0]["source"][:5], "[E: a")

    def test_a_cte_named_like_a_table_does_not_hide_the_table(self):
        self.sql("models/customers.sql",
                 "with orders as (\n  select * from {{ ref('orders') }}\n),\nfinal as (\n  select * from orders\n)\nselect * from final\n")
        got, _ = self.links()
        self.assertEqual(got, {("customers", "reads", "orders")})  # `orders` inside `final` is the CTE, not a table

    def test_insert_merge_update_and_create_as(self):
        self.sql("etl.sql",
                 "insert into dw.sales select * from stg.sales s join stg.dim d on d.id = s.id;\n"
                 "create view rpt.v as select * from dw.sales;\n"
                 "merge into dw.tgt t using stg.src s on t.id = s.id when matched then update set t.v = s.v;\n"
                 "update dw.cnt set n = (select count(*) from dw.sales);\n")
        got, _ = self.links()
        self.assertIn(("dw.sales", "reads", "stg.sales"), got)
        self.assertIn(("dw.sales", "reads", "stg.dim"), got)
        self.assertIn(("rpt.v", "reads", "dw.sales"), got)
        self.assertIn(("dw.tgt", "reads", "stg.src"), got)
        self.assertIn(("dw.cnt", "reads", "dw.sales"), got)

    def test_view_is_typed_as_a_view(self):
        self.sql("v.sql", "create view rpt.v as select * from dw.sales;\n")
        _, res = self.links()
        self.assertEqual(res["links"][0]["from"]["type"], "view")
        self.assertEqual(res["links"][0]["to"]["type"], "table")

    def test_foreign_keys_become_references(self):
        self.sql("schema.sql", "create table pet (\n  id int,\n  owner_id int,\n  foreign key (owner_id) references owner(id)\n);\n")
        got, _ = self.links()
        self.assertEqual(got, {("pet", "references", "owner")})

    def test_plain_select_outside_dbt_has_no_target(self):
        self.sql("report.sql", "select * from dw.sales;\n")
        got, res = self.links()
        self.assertEqual(got, set())
        self.assertEqual(res["no_target"], ["app/report.sql"])

    def test_unreadable_sql_is_reported_not_silent(self):
        self.sql("macros/m.sql", "{% macro f(x) %}\nselect (( from\n{% endmacro %}\n")
        self.sql("broken.sql", "insert into t select from where ((\n")
        _, res = self.links()
        self.assertIn("app/broken.sql", {u["file"] for u in res["unparsed"]})

    def test_unsupported_statement_is_listed_as_partly_read(self):
        self.sql("grants.sql", "create user bob with password 'x';\ngrant all on t to bob;\ninsert into a select * from b;\n")
        got, res = self.links()
        self.assertIn(("a", "reads", "b"), got)
        self.assertEqual([p["file"] for p in res["partial"]], ["app/grants.sql"])

    def test_every_link_source_resolves_and_has_a_line(self):
        self.sql("models/m.sql", "\n\nselect *\nfrom {{ ref('x') }}\n")
        _, res = self.links()
        self.assertEqual(res["dropped"], [])
        self.assertIn("app-repo" if False else "app/models/m.sql:4", res["links"][0]["source"])

    def test_graph_marks_parsed_links_and_a_hand_written_file_cannot_claim_it(self):
        self.sql("models/m.sql", "select * from {{ ref('x') }}\n")
        self.assertEqual(sql_links.main([self.kb]), 0)
        # a hand-written link file that tries to claim origin: parsed inside the link
        write(os.path.join(self.kb, "mod", "hand.links.yaml"), yaml.safe_dump({"links": [
            {"from": {"type": "table", "name": "a"}, "rel": "reads", "to": {"type": "table", "name": "b"},
             "source": '[E: app/models/m.sql:1 "x"]', "origin": "parsed"}]}))
        _, edges, rejected, _, _ = gen_graph.build(self.kb)
        by = {(e["from"], e["to"]): e["origin"] for e in edges}
        self.assertEqual(by[("table:m", "table:x")], "parsed")
        self.assertEqual(by[("table:a", "table:b")], "ai-proposed")
        self.assertEqual(rejected, [])

    def test_origin_reaches_the_graph_store_and_the_coverage_report(self):
        self.sql("models/m.sql", "select * from {{ ref('x') }}\n")
        sql_links.main([self.kb])
        out = os.path.join(self.kb, "CROSS-LAYER")
        gen_graph.main([self.kb])
        rows, _ = graph_store.impact(self.kb, "table:x")
        self.assertEqual(rows[0]["via"][0]["origin"], "parsed")
        rep = kb_coverage.build(self.kb)
        self.assertEqual(rep["edges_by_origin"], {"parsed": 1})
        self.assertEqual(rep["sql_read"]["parsed"], 1)
        self.assertTrue(os.path.isdir(out))

    def test_no_sql_files_removes_a_stale_output(self):
        out = os.path.join(self.kb, "CROSS-LAYER", "parsed.links.yaml")
        write(out, "links: []\n")
        os.makedirs(os.path.join(self.tmp, "app-repo"))
        self.assertEqual(sql_links.main([self.kb]), 0)
        self.assertFalse(os.path.exists(out))


class OriginWithoutSqlglot(unittest.TestCase):
    def test_origin_comes_from_the_file_name(self):
        self.assertEqual(gen_graph.origin_of("CROSS-LAYER/parsed.links.yaml"), "parsed")
        self.assertEqual(gen_graph.origin_of("db/catalog.links.yaml"), "catalogue")
        self.assertEqual(gen_graph.origin_of("app/api.links.yaml"), "ai-proposed")
        self.assertEqual(gen_graph.origin_of("app/parsed.links.yaml.bak"), "ai-proposed")


if __name__ == "__main__":
    unittest.main()
