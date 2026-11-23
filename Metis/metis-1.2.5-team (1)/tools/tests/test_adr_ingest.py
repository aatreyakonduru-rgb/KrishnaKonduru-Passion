import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import adr_ingest as A  # noqa: E402
import kb_gate  # noqa: E402
import read_docs  # noqa: E402
import verify_kb  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev"}}

NYGARD = """# 1. Use PostgreSQL for orders

Date: 2026-01-15

## Status

Accepted

Supersedes [ADR-0002](0002-use-mysql.md)

## Context

Order volumes need transactions. The ORDERS table is read by the claims_api service.

## Decision

We will use PostgreSQL for the ORDERS table.

## Consequences

Operations must learn Postgres tooling.
"""

MADR = """---
status: "accepted"
date: 2026-02-03
deciders: Ana Lead, Raj Dev
---
# Choose a queue for payment events

## Context and Problem Statement

Payment events must not be lost. The payments-api publishes them. PaymentsApi owns retries.

## Decision Drivers

* Durability
* Cost

## Considered Options

* Kafka
* SQS

## Decision Outcome

Chosen option: "SQS", because it is managed.

### Consequences

* Good, no brokers to run
* Bad, 256 KB message limit
"""

POSTMORTEM = """# Checkout outage 2026-03-04

Severity: SEV2

## Summary

Checkout failed for 40 minutes.

## Timeline

- 10:02 alert fires for ORDERS latency
- 10:20 rollback started
- 10:42 recovered

## Root cause

A missing index on ORDERS caused table scans.

## Action items

- Add the index
- Add a latency alert. admin password = Hunter2hunter must be rotated
"""

CONFLUENCE = """# Cache policy decision
page_id: 99
version: 3
space: ARCH
updated: 2026-04-01
path: Architecture
url: https://wiki/x

Status: Accepted
Context
We saw stale reads.
Decision
Use a 5 minute cache.
Consequences
Reads can be 5 minutes old.
"""

NOT_ADR = """# Notes

Some Context here.

## Decision

We talked about lunch.
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class AdrIngest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        self.repo = os.path.join(self.d, "app")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump(dict(PROFILE, sources={"repos": {"app": self.repo}})))
        write(os.path.join(self.repo, "docs", "adr", "0001-use-postgres.md"), NYGARD)
        write(os.path.join(self.repo, "docs", "adr", "README.md"), "# ADR index\n## Decision\n## Context\n")
        write(os.path.join(self.repo, "decisions", "2026-02-03-queue.md"), MADR)
        write(os.path.join(self.repo, "docs", "postmortems", "checkout.md"), POSTMORTEM)
        write(os.path.join(self.repo, "docs", "notes.md"), NOT_ADR)
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": [
            {"id": "table:ORDERS", "type": "table", "name": "ORDERS"},
            {"id": "component:claims_api", "type": "component", "name": "claims_api"},
            {"id": "component:payments-api", "type": "component", "name": "payments-api"},
            {"id": "component:PaymentsApi", "type": "component", "name": "PaymentsApi"}], "edges": []}))

    def tearDown(self):
        rmtree(self.d)

    def by_file(self, pages):
        return {p["src"].rel: p for p in pages}

    def test_scan_recognises_formats_and_skips_the_rest(self):
        pages, _ = A.plan_repo(self.kb, "app")
        got = {rel: (p["kind"], p["fmt"]) for rel, p in self.by_file(pages).items()}
        self.assertEqual(got, {"docs/adr/0001-use-postgres.md": ("decision", "nygard"),
                               "decisions/2026-02-03-queue.md": ("decision", "madr"),
                               "docs/postmortems/checkout.md": ("incident", "postmortem")})

    def test_extracts_fields(self):
        pages = self.by_file(A.plan_repo(self.kb, "app")[0])
        n = pages["docs/adr/0001-use-postgres.md"]
        self.assertEqual((n["title"], n["status"], n["date"], n["number"]),
                         ("ADR-0001: Use PostgreSQL for orders", "accepted", "2026-01-15", 1))
        text = A.render(n, "decisions")
        self.assertIn("- Supersedes: ADR-0002 [E: app/docs/adr/0001-use-postgres.md:", text)
        self.assertIn("## Consequences", text)
        m = pages["decisions/2026-02-03-queue.md"]
        self.assertEqual((m["status"], m["date"]), ("accepted", "2026-02-03"))
        mt = A.render(m, "decisions")
        self.assertIn("Deciders: Ana Lead, Raj Dev", mt)
        self.assertIn("## Considered options", mt)
        self.assertIn("Chosen option", mt)

    def test_incident_page_and_secret_omitted(self):
        pages = self.by_file(A.plan_repo(self.kb, "app")[0])
        p = pages["docs/postmortems/checkout.md"]
        text = A.render(p, "incidents")
        for h in ("## Timeline", "## Root cause", "## Action items", "Add the index"):
            self.assertIn(h, text)
        self.assertNotIn("Hunter2", text)
        self.assertEqual([o["kinds"] for o in p["omitted"]], [["credential"]])

    def test_every_line_has_a_tag_that_verify_kb_resolves(self):
        res = A.stage_repo(self.kb, "app")
        self.assertEqual(res["problems"], [])
        self.assertEqual(sorted(res["pages"]), [
            "context/decisions/adr-0001-use-postgresql-for-orders.md",
            "context/decisions/choose-a-queue-for-payment-events.md",
            "context/incidents/checkout-outage-2026-03-04.md"])
        rep = verify_kb.Checker(self.kb).run()
        self.assertEqual(rep["problems"], [])
        self.assertGreater(rep["tags"], 20)
        for rel in res["pages"]:
            body = read(os.path.join(self.kb, *rel.split("/"))).split("---\n", 2)[2]
            for line in body.splitlines():
                if line.startswith("- "):
                    self.assertIn("[E: app/", line)

    def test_related_objects_and_links_origin(self):
        res = A.stage_repo(self.kb, "app")
        links = yaml.safe_load(read(os.path.join(self.kb, "CROSS-LAYER", "decisions.links.yaml")))["links"]
        self.assertEqual(res["links"], len(links))
        by = {(l["from"]["name"][:8], l["to"]["name"]): l["origin"] for l in links}
        self.assertEqual(by[("ADR-0001", "ORDERS")], "named-in-text")
        self.assertEqual(by[("ADR-0001", "claims_api")], "named-in-text")
        self.assertEqual(by[("Choose a", "payments-api")], "named-in-text")
        self.assertEqual(by[("Choose a", "PaymentsApi")], "named-in-text")
        self.assertEqual(by[("Checkout", "ORDERS")], "named-in-text")
        self.assertTrue(all(l["rel"] == "references" and "[E: app/" in l["source"] for l in links))

    def test_loose_name_is_ai_proposed(self):
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": [
            {"id": "table:CLAIMS_API", "type": "table", "name": "CLAIMS_API"}], "edges": []}))
        A.stage_repo(self.kb, "app")
        links = yaml.safe_load(read(os.path.join(self.kb, "CROSS-LAYER", "decisions.links.yaml")))["links"]
        self.assertEqual([(l["to"]["name"], l["origin"], l["match"]) for l in links], [("CLAIMS_API", "ai-proposed", "loose-name")])

    def test_links_file_is_accepted_by_gen_graph(self):
        import gen_graph
        A.stage_repo(self.kb, "app")
        _, edges, rejected, _, _ = gen_graph.build(self.kb)
        self.assertEqual(rejected, [])
        self.assertTrue(edges)
        self.assertTrue(all(e["origin"] == "ai-proposed" for e in edges))  # gen_graph.py decides origin from the file name

    def test_rerun_is_stable(self):
        A.stage_repo(self.kb, "app")
        first = read(os.path.join(self.kb, "CROSS-LAYER", "decisions.links.yaml"))
        A.stage_repo(self.kb, "app")
        self.assertEqual(first, read(os.path.join(self.kb, "CROSS-LAYER", "decisions.links.yaml")))

    def test_locked_kb_is_staged_not_written(self):
        write(os.path.join(self.kb, "context", "a.md"), "# A\n")
        kb_gate.lock(self.kb, "Ana Lead")
        res = A.stage_repo(self.kb, "app")
        self.assertTrue(res["batch"])
        self.assertTrue(os.path.isfile(res["digest"]))
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "decisions")))
        self.assertFalse(os.path.exists(os.path.join(self.kb, "CROSS-LAYER", "decisions.links.yaml")))
        staged = kb_gate.pending_files(self.kb, res["batch"])
        self.assertIn("context/decisions/choose-a-queue-for-payment-events.md", staged)
        self.assertIn("CROSS-LAYER/decisions.links.yaml", staged)
        kb_gate.certify(self.kb, res["batch"], "Ana Lead", files=[f for f in staged if f.startswith("context/")])
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "context", "decisions", "choose-a-queue-for-payment-events.md")))

    def test_existing_foreign_page_is_not_replaced(self):
        mine = os.path.join(self.kb, "context", "decisions", "choose-a-queue-for-payment-events.md")
        write(mine, "# Mine\n")
        res = A.stage_repo(self.kb, "app")
        self.assertIn("context/decisions/choose-a-queue-for-payment-events.NEW.md", res["pages"])
        self.assertEqual(read(mine), "# Mine\n")

    def test_dry_run_writes_nothing(self):
        res = A.stage_repo(self.kb, "app", dry=True)
        self.assertEqual(res["problems"], [])
        self.assertTrue(res["written"])
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context")))

    def test_bad_quote_stops_everything(self):
        pages, _ = A.plan_repo(self.kb, "app")
        adr = self.by_file(pages)["docs/adr/0001-use-postgres.md"]
        txt = A.render(adr, "decisions").replace("Operations must", "Operations will")
        out = A.write_files(self.kb, {"context/decisions/x.md": txt}, "t")
        self.assertTrue(out["problems"])
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "decisions", "x.md")))

    def test_unknown_repo_and_subfolder(self):
        with self.assertRaises(ValueError):
            A.plan_repo(self.kb, "nope")
        with self.assertRaises(ValueError):
            A.plan_repo(self.kb, "app", "../elsewhere")
        pages, _ = A.plan_repo(self.kb, "app", "docs/adr")
        self.assertEqual(len(pages), 1)

    def test_categories_fall_back_to_decisions_file(self):
        cats = A.categories(self.kb)
        self.assertEqual(cats["decisions"]["folder"], "context/decisions")
        self.assertEqual(cats["incidents"]["folder"], "context/incidents")
        self.assertEqual(cats["procedures"]["folder"], "context/procedures")
        write(os.path.join(self.kb, ".metis", "doc-categories.yaml"),
              yaml.safe_dump({"categories": [{"id": "decisions", "folder": "adr", "keywords": []}]}))
        self.assertEqual(A.categories(self.kb)["decisions"]["folder"], "adr")

    def test_docs_from_intake_scratch(self):
        scratch = os.path.join(self.d, "scratch")
        os.makedirs(scratch)
        src = os.path.join(self.d, "cache-decision.txt")
        write(src, CONFLUENCE)
        read_docs.cmd_extract(scratch, [src], "Pat Analyst")
        self.assertEqual(A.main(["docs", self.kb, scratch]), 0)
        page = os.path.join(self.kb, "context", "decisions", "cache-policy-decision.md")
        self.assertTrue(os.path.isfile(page))
        text = read(page)
        self.assertIn("[E: doc:cache-decision.txt#line", text)
        self.assertIn("Use a 5 minute cache", text)
        self.assertIn("## Sources", text)
        self.assertIn("given by Pat Analyst", text)
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])

    def test_cli(self):
        self.assertEqual(A.main(["scan", self.kb, "--repo", "app"]), 0)
        self.assertEqual(A.main(["stage", self.kb, "--repo", "app", "--dry-run"]), 0)
        self.assertEqual(A.main(["stage", self.kb, "--repo", "nope"]), 2)


if __name__ == "__main__":
    unittest.main()
