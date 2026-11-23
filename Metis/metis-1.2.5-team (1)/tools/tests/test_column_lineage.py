import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import column_lineage  # noqa: E402
import gen_graph  # noqa: E402

HAVE = column_lineage.load_sqlglot()[0] is not None


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


@unittest.skipUnless(HAVE, "sqlglot is not installed")
class ColumnLineageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({
            "product": {"name": "TestDB"},
            "sources": {"workspace_root": self.tmp, "repos": {"app": "app-repo"}}
        }))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def sql(self, name, text):
        write(os.path.join(self.tmp, "app-repo", name), text)

    def links(self):
        res = column_lineage.build(self.kb)
        return {(l["from"]["name"], l["rel"], l["to"]["name"]) for l in res["links"]}, res

    def test_dbt_staging_model_lineage(self):
        self.sql("models/stg_orders.sql",
                 "with source as (\n"
                 "    select * from {{ source('ecom', 'raw_orders') }}\n"
                 "),\n"
                 "renamed as (\n"
                 "    select\n"
                 "        id as order_id,\n"
                 "        customer as customer_id,\n"
                 "        amount as order_amount\n"
                 "    from source\n"
                 ")\n"
                 "select * from renamed\n")
        got, res = self.links()
        self.assertIn(("stg_orders.order_id", "derived from", "ecom.raw_orders.id"), got)
        self.assertIn(("stg_orders.customer_id", "derived from", "ecom.raw_orders.customer"), got)
        self.assertIn(("stg_orders.order_amount", "derived from", "ecom.raw_orders.amount"), got)
        self.assertEqual(res["dropped"], [])

    def test_dbt_marts_joins_aggregates_and_case(self):
        self.sql("models/orders.sql",
                 "with orders as (\n"
                 "    select * from {{ ref('stg_orders') }}\n"
                 "),\n"
                 "items as (\n"
                 "    select * from {{ ref('stg_items') }}\n"
                 "),\n"
                 "summary as (\n"
                 "    select\n"
                 "        order_id,\n"
                 "        sum(price) as total_price,\n"
                 "        case when sum(price) > 100 then 1 else 0 end as is_large\n"
                 "    from items\n"
                 "    group by 1\n"
                 "),\n"
                 "final as (\n"
                 "    select\n"
                 "        orders.order_id,\n"
                 "        orders.customer_id,\n"
                 "        summary.total_price,\n"
                 "        summary.is_large\n"
                 "    from orders\n"
                 "    left join summary on orders.order_id = summary.order_id\n"
                 ")\n"
                 "select * from final\n")
        got, res = self.links()
        self.assertIn(("orders.order_id", "derived from", "stg_orders.order_id"), got)
        self.assertIn(("orders.customer_id", "derived from", "stg_orders.customer_id"), got)
        self.assertIn(("orders.total_price", "derived from", "stg_items.price"), got)
        self.assertIn(("orders.is_large", "derived from", "stg_items.price"), got)

    def test_insert_select_and_create_as(self):
        self.sql("etl.sql",
                 "insert into dw.daily_sales (day_id, sales_amt)\n"
                 "select o.order_date, o.amount from raw.orders o;\n"
                 "create view rpt.customer_summary as\n"
                 "select c.id as cust_id, c.name as cust_name from dw.customers c;\n")
        got, res = self.links()
        self.assertIn(("dw.daily_sales.day_id", "derived from", "raw.orders.order_date"), got)
        self.assertIn(("dw.daily_sales.sales_amt", "derived from", "raw.orders.amount"), got)
        self.assertIn(("rpt.customer_summary.cust_id", "derived from", "dw.customers.id"), got)
        self.assertIn(("rpt.customer_summary.cust_name", "derived from", "dw.customers.name"), got)

    def test_catalogue_aware_star_expansion(self):
        # Save a catalogue column snapshot for raw.orders
        qdir = os.path.join(self.kb, "_EVIDENCE", "queries")
        write(os.path.join(qdir, "CATALOG-COLUMNS-PROD-APP.json"), json.dumps([
            {"TABLE_SCHEMA": "raw", "TABLE_NAME": "orders", "COLUMN_NAME": "id", "DATA_TYPE": "int"},
            {"TABLE_SCHEMA": "raw", "TABLE_NAME": "orders", "COLUMN_NAME": "amount", "DATA_TYPE": "numeric"}
        ]))
        self.sql("view.sql", "create view rpt.all_orders as select * from raw.orders;\n")
        got, res = self.links()
        self.assertIn(("rpt.all_orders.id", "derived from", "raw.orders.id"), got)
        self.assertIn(("rpt.all_orders.amount", "derived from", "raw.orders.amount"), got)

    def test_column_impact_walk(self):
        self.sql("models/stg_orders.sql",
                 "with source as (select * from {{ source('ecom', 'raw_orders') }}),\n"
                 "renamed as (select id as order_id, amount from source)\n"
                 "select * from renamed\n")
        self.sql("models/orders.sql",
                 "with orders as (select * from {{ ref('stg_orders') }})\n"
                 "select order_id as final_order_id, amount * 1.1 as taxed_amount from orders\n")
        self.assertEqual(column_lineage.main(["build", self.kb]), 0)

        rows, cut = column_lineage.column_impact(self.kb, "ecom.raw_orders", "id")
        moved_names = [r["moves"] for r in rows]
        self.assertIn("stg_orders.order_id", moved_names)
        self.assertIn("orders.final_order_id", moved_names)
        # Check depth
        depth_by_col = {r["moves"]: r["depth"] for r in rows}
        self.assertEqual(depth_by_col["stg_orders.order_id"], 1)
        self.assertEqual(depth_by_col["orders.final_order_id"], 2)

    def test_unresolved_star_without_schema(self):
        self.sql("star.sql", "create view rpt.unknown as select * from some_unknown_table;\n")
        _, res = self.links()
        self.assertTrue(any("SELECT *" in u["reason"] for u in res["unresolved"]))

    def test_cli_build_and_impact(self):
        self.sql("models/m.sql", "select a as col_a from tbl;\n")
        self.assertEqual(column_lineage.main(["build", self.kb]), 0)
        out_file = os.path.join(self.kb, "CROSS-LAYER", "column.links.yaml")
        self.assertTrue(os.path.isfile(out_file))
        # Test CLI impact command
        self.assertEqual(column_lineage.main(["impact", self.kb, "tbl.a"]), 0)


if __name__ == "__main__":
    unittest.main()
