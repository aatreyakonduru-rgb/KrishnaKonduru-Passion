"""Tests for the 15-feature pack. Each test pins a policy rule (grounding, privacy, read-only), not just the happy path."""
import csv
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scribe import knowledge
from scribe.facts import make_fact, ev, validate_fact
from scribe.features import (FEATURES, cloudinv, common, contract_diff, drift, gitscan, graph, history, impact, lineage, ownership,
                             readiness, runtime, sbom, scorecards, semantic)
from scribe.redact import Redactor
from scribe.settings import Settings

SECRET = "Sup3rS3cretUat99"


# ---------- helpers ----------
def F(kind, subject, attrs, repo="svc-a", path="a/B.java", cls="OBSERVED", rule=None):
    attrs = {"repo": repo, "path": path, **attrs}
    return make_fact(kind, subject, attrs, cls, [ev(f"{repo}/{path}", "L1", subject)], "t", rule)


def ctx_for(facts, tmp_path, repos=None, **settings):
    s = Settings(output_dir=str(tmp_path / "out"), **settings)
    return common.Ctx(settings=s, run_id="run-20260101-000000-aaaa", out=tmp_path / "out", journal=tmp_path / "j", facts=list(facts),
                      repos=repos or {}, redactor=Redactor(), collated_at="2026-01-01T00:00:00Z")


def all_text(res):
    return "\n".join(res.files.values())


# ---------- 15 ownership: teams only ----------
@pytest.mark.parametrize("tok,expected", [("@payments-team", "payments-team"), ("@acme/platform-squad", "platform-squad"), ("jane.doe@acme.com", None),
                                          ("@jdoe", None), ("@priya", None), ("@acme/jdoe", "jdoe")])
def test_team_of(tok, expected):
    assert common.team_of(tok) == expected


def test_ownership_never_reports_individuals(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "CODEOWNERS").write_text("/a/ @payments-team @jdoe\n/b/ jane.doe@acme.com\n*.md @acme/docs-group\n")
    ctx = ctx_for([], tmp_path, {"r": str(repo)})
    res = ownership.run(ctx)
    text = all_text(res)
    assert "payments-team" in text and "docs-group" in text
    assert "jdoe" not in text and "jane" not in text and "acme.com" not in text
    assert "2 owner entries omitted" in text
    assert all(f["attrs"]["team"] in ("payments-team", "docs-group") for f in res.facts)


# ---------- 7 lineage ----------
def test_lineage_parses_sql_from_code_and_flags_unknown_catalog(tmp_path):
    repo = tmp_path / "svc-a"
    (repo / "a").mkdir(parents=True)
    (repo / "a" / "B.java").write_text('class B { String q = "select o.id, c.name from orders o join customers c on o.cid = c.id where o.id = ?";\n'
                                       ' String w = "insert into audit_log (event, at) values (?, ?)"; String d = "UPDATE orders SET status = ${s} WHERE id = 1"; }\n')
    facts = [F("source_file", "svc-a/a/B.java", {"language": "java", "lines": 2, "is_test": False})]
    ctx = ctx_for(facts, tmp_path, {"svc-a": str(repo)})
    res = lineage.run(ctx)
    ops = {(f["attrs"]["table"], f["attrs"]["operation"]) for f in res.facts}
    assert {("orders", "read"), ("customers", "read"), ("audit_log", "write"), ("orders", "write")} <= ops
    cols = {f["attrs"]["table"]: f["attrs"]["columns"] for f in res.facts if f["attrs"]["operation"] == "read"}
    assert "id" in cols["orders"] and "name" in cols["customers"]
    assert all(f["class"] == "DERIVED" and f.get("rule") and not validate_fact(f) for f in res.facts)
    assert "UNKNOWN: no live catalog" in all_text(res)


def test_lineage_joins_catalog_and_reports_missing(tmp_path):
    repo = tmp_path / "svc-a"
    (repo / "a").mkdir(parents=True)
    (repo / "a" / "B.java").write_text('class B { String q = "select id, ghost_col from orders"; String r = "select x from nowhere"; }\n')
    facts = [F("source_file", "svc-a/a/B.java", {"language": "java", "lines": 1, "is_test": False}),
             F("db_table", "snow.public.orders", {"table": "orders", "schema": "public"}, repo="", path=""),
             F("db_column", "snow.public.orders.id", {"table": "orders", "column": "id"}, repo="", path="")]
    res = lineage.run(ctx_for(facts, tmp_path, {"svc-a": str(repo)}))
    t = all_text(res)
    assert "**not found**" in t and "columns not in catalog: ghost_col" in t


def test_lineage_counts_unparseable_sql_instead_of_guessing(tmp_path):
    repo = tmp_path / "svc-a"
    repo.mkdir()
    (repo / "B.java").write_text('class B { String q = "select from where"; }\n')
    res = lineage.run(ctx_for([F("source_file", "svc-a/B.java", {"language": "java", "lines": 1, "is_test": False}, path="B.java")], tmp_path, {"svc-a": str(repo)}))
    assert not res.facts


# ---------- 1 graph ----------
def _two_services():
    return [
        F("endpoint", "GET /payments/{id}", {"verb": "GET", "path": "/payments/{id}", "framework": "spring", "file": "P.java"}, repo="pay", path="P.java"),
        F("url_reference", "https://gateway.invalid/payments/42", {"url": "https://gateway.invalid/payments/42"}, repo="orders", path="O.java"),
        F("url_reference", "https://other.invalid/unknown/thing", {"url": "https://other.invalid/unknown/thing"}, repo="orders", path="O.java"),
        F("table_reference", "orders", {"table": "orders"}, repo="orders", path="O.java", cls="DERIVED", rule="r"),
        F("table_reference", "orders", {"table": "orders"}, repo="pay", path="P.java", cls="DERIVED", rule="r"),
        F("db_connection", "k", {"engine": "postgres", "key": "k", "environment": "UAT"}, repo="pay", path="c.yml"),
    ]


def test_graph_links_services_by_path_only_and_marks_derived(tmp_path):
    ctx = ctx_for(_two_services(), tmp_path)
    g = graph.compute(ctx)
    calls = [e for e in g["edges"] if e["type"] == "calls"]
    assert len(calls) == 1 and calls[0]["from"] == "svc:orders" and calls[0]["to"] == "svc:pay" and calls[0]["class"] == "DERIVED" and calls[0]["rule"]
    assert any(n["type"] == "external" for n in g["nodes"])
    res = graph.run(ctx)
    md = res.files["graph/architecture.md"]
    assert "```mermaid" in md and "flowchart LR" in md and "gateway.invalid" not in md and "other.invalid" not in md
    assert "C4Container" in res.files["graph/c4-containers.md"]
    json.loads(res.files["graph/graph.json"])


# ---------- 3 sbom ----------
def test_sbom_formats_and_no_guessed_licenses(tmp_path):
    facts = [F("dependency", "maven:org.x:lib", {"ecosystem": "maven", "group": "org.x", "artifact": "lib", "version": "1.0", "scope": "compile"}),
             F("dependency", "npm:left", {"ecosystem": "npm", "group": "", "artifact": "left", "version": "^1.2.0", "scope": "compile"}, path="package.json")]
    repo = tmp_path / "svc-a"
    repo.mkdir()
    (repo / "LICENSE").write_text("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3")
    res = sbom.run(ctx_for(facts, tmp_path, {"svc-a": str(repo)}))
    cdx = json.loads(res.files["sbom/cyclonedx.json"])
    assert cdx["bomFormat"] == "CycloneDX" and {c["purl"] for c in cdx["components"]} == {"pkg:maven/org.x/lib@1.0", "pkg:npm/left@^1.2.0"}
    assert json.loads(res.files["sbom/spdx.json"])["spdxVersion"] == "SPDX-2.3"
    md = res.files["sbom/index.md"]
    assert "AGPL-3.0" in md and "strong copyleft" in md and "UNKNOWN for all 2" in md and "Nothing was sent" in md


def test_sbom_vulnerability_lookup_is_opt_in_and_stores_ids_only(tmp_path):
    facts = [F("dependency", "maven:org.x:lib", {"ecosystem": "maven", "group": "org.x", "artifact": "lib", "version": "1.0", "scope": "compile"})]
    off = sbom.run(ctx_for(facts, tmp_path), vuln_fetch=lambda q: pytest.fail("must not be called when vuln_lookup is off"))
    assert not off.facts
    on = sbom.run(ctx_for(facts, tmp_path, vuln_lookup=True), vuln_fetch=lambda q: [["GHSA-aaaa-bbbb-cccc"]])
    v = [f for f in on.facts if f["kind"] == "vulnerability"]
    assert v and v[0]["attrs"]["advisories"] == ["GHSA-aaaa-bbbb-cccc"] and "http" not in json.dumps(v[0])


# ---------- 5 scorecards ----------
def test_scorecard_rules_and_absence_labels(tmp_path):
    repo = tmp_path / "svc-a"
    repo.mkdir()
    (repo / "x.txt").write_text("x")
    facts = [F("endpoint", "GET /x", {"verb": "GET", "path": "/x", "framework": "s", "file": "a/B.java"}),
             F("module", "maven:g:a", {"ecosystem": "maven", "java_version": "8", "version": "1"}, path="pom.xml"),
             F("container_image", "docker:app:latest", {"image": "app:latest"}, path="Dockerfile"),
             F("secret_leak", "k", {"type": "aws_access_key", "line": 3}, path="a/B.java"),
             F("secret_leak", "k2", {"type": "high_entropy", "line": 3}, path="a/B.java"),
             F("source_file", "svc-a/a/B.java", {"language": "java", "lines": 5, "is_test": False})]
    ctx = ctx_for(facts, tmp_path, {"svc-a": str(repo)})
    flags = {f["rule"]: f for f in scorecards.evaluate(ctx, "svc-a")}
    assert {"no_readme", "no_ci", "no_health", "hardcoded_secret", "no_tests", "no_owner", "no_contract", "unpinned_image", "eol_runtime"} <= set(flags)
    assert "1 location" in flags["hardcoded_secret"]["detail"]          # two detectors on one line count once
    res = scorecards.run(ctx)
    risk = [f for f in res.facts if f["kind"] == "risk_flag"]
    assert all(f["class"] == "DERIVED" and f["rule"] and not validate_fact(f) for f in res.facts)
    assert all("absence" in f["rule"] for f in risk if f["attrs"]["absence_finding"])
    assert 0 <= scorecards.score(list(flags.values())) < 50


# ---------- 4 catalog ----------
def test_catalog_has_owner_team_or_unknown_and_no_links(tmp_path):
    from scribe.features import catalog
    facts = [F("source_file", "svc-a/a/B.java", {"language": "java", "lines": 5, "is_test": False}),
             make_fact("ownership", "svc-a:/:team", {"repo": "svc-a", "pattern": "/", "team": "payments-team"}, "OBSERVED", [ev("svc-a/CODEOWNERS", "L1")], "o")]
    res = catalog.run(ctx_for(facts, tmp_path))
    y = res.files["catalog/backstage/svc-a/catalog-info.yaml"]
    assert "group:default/payments-team" in y and "links:" not in y and "http" not in y
    rows = list(csv.reader(io.StringIO(res.files["catalog/cmdb.csv"])))
    assert rows[0][0] == "service" and rows[1][1] == "payments-team"
    none = catalog.run(ctx_for([F("source_file", "svc-b/x", {"language": "go", "lines": 1, "is_test": False}, repo="svc-b")], tmp_path))
    assert "owner: unknown" in none.files["catalog/backstage/svc-b/catalog-info.yaml"]


def test_csv_cells_neutralise_formulas():
    assert common.csv_cell("=1+1").startswith("'") and common.csv_cell("ok") == "ok"


# ---------- 2 drift and run diff ----------
def test_env_drift_and_run_diff(tmp_path):
    cfg = lambda env, key, val: F("config_entry", f"{env}:{key}", {"key": key, "value": val, "environment": env, "secret_like": False, "is_placeholder": False}, path=f"app-{env.lower()}.yml")
    facts = [cfg("SIT", "timeout", "10"), cfg("UAT", "timeout", "30"), cfg("SIT", "only.sit", "1"), cfg("UAT", "same", "z"), cfg("SIT", "same", "z")]
    ctx = ctx_for(facts, tmp_path)
    d = drift.env_drift(ctx)
    p = d["pairs"]["SIT vs UAT"]
    assert [x["key"] for x in p["differ"]] == ["svc-a::timeout"] and p["only_a"] == ["svc-a::only.sit"] and p["same"] == 1
    first = drift.run(ctx)
    assert "UNKNOWN: this is the first run" in first.files["drift/since-last-run.md"]
    history.save(ctx.out, ctx.run_id, {"facts": ctx.cache["snapshot_facts"]})
    facts2 = [cfg("SIT", "timeout", "10"), cfg("UAT", "timeout", "99"), cfg("UAT", "new.key", "1")]
    ctx2 = ctx_for(facts2, tmp_path)
    ctx2.run_id = "run-20260102-000000-bbbb"
    rd = drift.run_diff(ctx2, history.load_previous(ctx2.out, ctx2.run_id))
    assert rd["has_previous"] and len(rd["added"]) == 1 and len(rd["changed"]) == 1 and len(rd["removed"]) == 3   # only.sit and both `same` entries


# ---------- 10 contract diff ----------
def _op(verb, path, params, responses, body=False):
    return F("api_operation", f"{verb} {path}", {"protocol": "rest", "verb": verb, "path": path, "parameters": params, "responses": responses,
                                                 "has_request_body": body, "path_file": "openapi.yaml"}, path="openapi.yaml")


def test_contract_diff_detects_breaking_changes_between_runs(tmp_path):
    old = contract_diff.extract(ctx_for([F("api_service", "openapi:P", {"protocol": "rest", "title": "P", "version": "1", "path": "openapi.yaml"}, path="openapi.yaml"),
                                         _op("GET", "/a", [{"name": "id", "in": "query", "required": False}], ["200", "404"]), _op("GET", "/gone", [], ["200"]),
                                         F("api_schema", "schema:X", {"name": "X", "properties": ["a", "b"], "types": {"a": "string", "b": "integer"}, "required": []}, path="openapi.yaml")], tmp_path))
    ctx = ctx_for([F("api_service", "openapi:P", {"protocol": "rest", "title": "P", "version": "2", "path": "openapi.yaml"}, path="openapi.yaml"),
                   _op("GET", "/a", [{"name": "id", "in": "query", "required": True}, {"name": "tenant", "in": "header", "required": True}], ["404"]), _op("POST", "/new", [], ["201"]),
                   F("api_schema", "schema:X", {"name": "X", "properties": ["a", "c"], "types": {"a": "integer", "c": "string"}, "required": ["c"]}, path="openapi.yaml")], tmp_path)
    ctx.run_id = "run-2"
    history.save(tmp_path / "out", "run-1", {"facts": {"keys": {}, "counts": {}}, "contracts": old})
    res = contract_diff.run(ctx)
    t = res.files["contracts/changes.md"]
    for needle in ("operation removed", "parameter now required: query:id", "required parameter added: header:tenant", "success response 200 removed",
                   "property removed: b", "type changed string -> integer", "required property added: c", "operation added"):
        assert needle in t, needle
    assert any(f["attrs"]["level"] == "breaking" for f in res.facts) and all(f["class"] == "DERIVED" and not validate_fact(f) for f in res.facts)


# ---------- 11 readiness ----------
def test_readiness_rule_and_shared_table_blockers(tmp_path):
    facts = [F("container_image", "docker:x:17", {"image": "eclipse-temurin:17"}, repo="a", path="Dockerfile"), F("pipeline_stage", "s", {"system": "g", "stage": "b"}, repo="a"),
             F("config_key_use", "k", {"key": "k"}, repo="a"),
             F("table_reference", "t1", {"table": "t1"}, repo="a", cls="DERIVED", rule="r"), F("table_reference", "t2", {"table": "t2"}, repo="a", cls="DERIVED", rule="r"),
             F("table_reference", "t1", {"table": "t1"}, repo="b", cls="DERIVED", rule="r"), F("table_reference", "t2", {"table": "t2"}, repo="b", cls="DERIVED", rule="r"),
             F("source_file", "a/x", {"language": "java", "lines": 3, "is_test": False}, repo="a"), F("source_file", "b/x", {"language": "java", "lines": 3, "is_test": False}, repo="b")]
    res = readiness.run(ctx_for(facts, tmp_path))
    byrepo = {f["attrs"]["repo"]: f["attrs"] for f in res.facts}
    assert byrepo["a"]["suggested_path"] == "refactor" and any("shares 2 table" in b for b in byrepo["a"]["blockers"])
    assert "Not assessed" in res.files["readiness/index.md"] and all(f["class"] == "DERIVED" and f["rule"] for f in res.facts)


# ---------- 6 living docs ----------
def test_living_docs_cite_evidence_and_mark_gaps(tmp_path):
    from scribe.features import livedocs
    facts = [F("container_image", "docker:x", {"image": "eclipse-temurin:17"}, path="Dockerfile"), F("source_file", "svc-a/x", {"language": "java", "lines": 3, "is_test": False})]
    res = livedocs.run(ctx_for(facts, tmp_path))
    rb = res.files["docs-generated/svc-a/runbook.md"]
    assert "TO CONFIRM" in rb and "UNKNOWN" in rb
    adr = next(v for k, v in res.files.items() if "/adr/" in k)
    assert "Proposed" in adr and "TO CONFIRM" in adr and "svc-a/Dockerfile" in adr


# ---------- 12 git history ----------
def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.t", *args], cwd=repo, check=True, capture_output=True)


def test_git_history_finds_removed_secret_without_recording_value(tmp_path):
    repo = tmp_path / "svc-a"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "app.properties").write_text("password=Zx81QwErTyUiOp09AsDfGhJkLmNb4V\n")
    (repo / ".env").write_text("A=1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add config for jane.doe@acme.com")
    (repo / "app.properties").write_text("password=${DB_PASSWORD}\n")
    _git(repo, "commit", "-qam", "remove it")
    ctx = ctx_for([], tmp_path, {"svc-a": str(repo)})
    res = gitscan.run(ctx)
    blob = all_text(res) + json.dumps(res.facts)
    assert "Zx81QwErTy" not in blob and "jane" not in blob and "acme.com" not in blob and "add config" not in blob and "t@t.t" not in blob
    hs = [f for f in res.facts if f["kind"] == "history_secret"]
    assert hs and hs[0]["attrs"]["present_at_head"] is False and hs[0]["attrs"]["path"] == "app.properties"
    assert any(f["kind"] == "history_sensitive_file" and f["attrs"]["path"] == ".env" for f in res.facts)


def test_git_history_off_and_missing_git(tmp_path):
    assert "off" in gitscan.run(ctx_for([], tmp_path, scan_git_history=False)).coverage["git history"]
    (tmp_path / "plain").mkdir()
    assert "UNKNOWN" in gitscan.run(ctx_for([], tmp_path, {"plain": str(tmp_path / "plain")})).files["git-history/index.md"]
    with pytest.raises(ValueError):
        list(gitscan.git_lines(["push"], str(tmp_path)))


# ---------- 13 cloud inventory ----------
@pytest.mark.parametrize("argv", [["aws", "ec2", "terminate-instances"], ["aws", "s3api", "put-object"], ["aws", "secretsmanager", "get-secret-value"],
                                  ["kubectl", "delete", "pod", "x"], ["kubectl", "get", "secrets", "-A"], ["kubectl", "get", "deployments,secrets"],
                                  ["kubectl", "get", "--raw", "/api"], ["gcloud", "compute", "instances", "delete"], ["az", "vm", "delete"], ["rm", "-rf", "/"],
                                  ["aws", "ssm", "get-parameter", "--with-decryption"], ["aws", "ecr", "get-login-password"]])
def test_cloud_cli_is_read_only(argv):
    with pytest.raises(cloudinv.NotReadOnly):
        cloudinv.check_command(argv)


def test_cloud_cli_allows_listing():
    for a in (["aws", "rds", "describe-db-instances", "--output", "json"], ["kubectl", "get", "deployments,statefulsets", "-A", "-o", "json"],
              ["gcloud", "container", "clusters", "list", "--format=json"], ["az", "aks", "list", "--output", "json"]):
        cloudinv.check_command(a)


def test_cloud_inventory_compares_with_manifests_and_drops_hosts(tmp_path):
    live = {"kubectl get namespaces": {"items": [{"metadata": {"name": "prod"}}]},
            "kubectl get deployments,statefulsets,daemonsets,cronjobs": {"items": [
                {"kind": "Deployment", "metadata": {"name": "pay", "namespace": "prod"}, "spec": {"replicas": 2, "template": {"spec": {"containers": [{"image": "reg/pay:1"}]}}}},
                {"kind": "Deployment", "metadata": {"name": "rogue", "namespace": "prod"}, "spec": {"replicas": 1, "template": {"spec": {"containers": [{"image": "reg/rogue:9"}]}}}}]},
            "aws rds describe-db-instances": {"DBInstances": [{"DBInstanceIdentifier": "pay-db", "Engine": "postgres", "EngineVersion": "15", "DBInstanceClass": "db.m5.large",
                                                                 "Endpoint": {"Address": "pay-db.abc.us-east-1.rds.amazonaws.com"}, "MasterUsername": "admin"}]}}

    def runner(argv):
        cloudinv.check_command(argv)
        key = " ".join(a for a in argv[:4] if not a.startswith("-"))
        for k, v in live.items():
            if key.startswith(k) or " ".join(argv).startswith(k):
                return json.dumps(v)
        return json.dumps({})
    facts = [F("k8s_resource", "k8s:Deployment:pay", {"kind": "Deployment", "name": "pay", "images": ["reg/pay:1"]}, path="k8s/pay.yaml"),
             F("k8s_resource", "k8s:Deployment:old", {"kind": "Deployment", "name": "old", "images": ["reg/old:1"]}, path="k8s/old.yaml")]
    res = cloudinv.run(ctx_for(facts, tmp_path, cloud_inventory=["kubernetes", "aws"]), runner=runner)
    blob = all_text(res) + json.dumps(res.facts)
    assert "amazonaws" not in blob and "admin" not in blob and "Endpoint" not in blob
    d = {f["attrs"]["direction"]: f for f in res.facts if f["kind"] == "iac_drift"}
    assert "rogue" in json.dumps(d["live_only"]) and "old" in json.dumps(d["iac_only"])
    assert any(f["kind"] == "cloud_resource" and f["attrs"].get("engine") == "postgres" for f in res.facts)


def test_cloud_inventory_off_by_default_and_missing_cli_is_unknown(tmp_path):
    assert "off" in cloudinv.run(ctx_for([], tmp_path)).coverage["live cloud"]

    def nocli(argv):
        raise FileNotFoundError(argv[0])
    res = cloudinv.run(ctx_for([], tmp_path, cloud_inventory=["azure"]), runner=nocli)
    assert "not installed" in all_text(res)


# ---------- 14 runtime ----------
def test_runtime_correlation_finds_gaps_both_ways(tmp_path):
    rt = tmp_path / "out" / "runtime-maps"
    rt.mkdir(parents=True)
    (rt / "map.json").write_text(json.dumps({"window": "7d", "edges": [{"from": "orders", "to": "pay", "calls": 50, "errors": 1}, {"from": "pay", "to": "ledger", "calls": 9}, {"from": "mystery", "to": "pay", "calls": 1}],
                                              "endpoints": [{"service": "pay", "method": "GET", "path": "/payments/42", "calls": 50}]}))
    facts = [F("endpoint", "GET /payments/{id}", {"verb": "GET", "path": "/payments/{id}", "framework": "s", "file": "P.java"}, repo="pay", path="P.java"),
             F("endpoint", "POST /refunds", {"verb": "POST", "path": "/refunds", "framework": "s", "file": "P.java"}, repo="pay", path="P.java"),
             F("url_reference", "https://x.invalid/payments/1", {"url": "https://x.invalid/payments/1"}, repo="orders", path="O.java"),
             F("url_reference", "https://x.invalid/refunds", {"url": "https://x.invalid/refunds"}, repo="ledger", path="L.java"),
             F("source_file", "ledger/L.java", {"language": "java", "lines": 1, "is_test": False}, repo="ledger", path="L.java")]
    res = runtime.run(ctx_for(facts, tmp_path))
    md = res.files["runtime/index.md"]
    assert "`pay` → `ledger`" in md                                 # runtime-only edge
    assert "`ledger` → `pay`" in md and "does not prove" in md      # code path without traffic (ledger calls /refunds on pay)
    assert "`mystery`" in md                                        # unmatched name listed, never guessed
    gaps = {f["attrs"]["kind"] for f in res.facts if f["kind"] == "runtime_gap"}
    assert {"runtime_call_not_in_code", "code_path_without_traffic", "endpoint_without_traffic"} <= gaps
    assert "UNKNOWN" in runtime.run(ctx_for([], tmp_path / "empty")).files["runtime/index.md"]


# ---------- 8 semantic ----------
def test_hybrid_search_finds_variants_and_still_says_not_found(tmp_path):
    facts = [F("endpoint", "POST /customer-refunds", {"verb": "POST", "path": "/customer-refunds", "framework": "s", "file": "R.java"}),
             F("table_reference", "customer_accounts", {"table": "customer_accounts"}, cls="DERIVED", rule="r"),
             F("source_file", "svc-a/LedgerPostingService.java", {"language": "java", "lines": 9, "is_test": False})]
    idx = semantic.HybridIndex(facts)
    assert knowledge.ask(idx, "which endpoints handle refunding customers?")["found"]
    assert knowledge.ask(idx, "ledgers posting")["found"]                       # plural / partial match BM25 alone would miss
    assert not knowledge.ask(idx, "quantum flux capacitor calibration")["found"]
    # toy embedder: axis 0 = refund, axis 1 = ledger, anything else is the zero vector (so it has no similarity to anything)
    embed = lambda texts: [[1.0 if "refund" in t.lower() else 0.0, 1.0 if "ledger" in t.lower() else 0.0] for t in texts]
    emb = semantic.HybridIndex(facts, embedder=embed)
    hits = emb.search("money back refund", 3)
    assert hits and "refund" in hits[0][1]["subject"]                          # dense path ranks the matching fact
    assert not knowledge.ask(emb, "completely unrelated zebra")["found"]


# ---------- 9 impact ----------
def test_impact_ranks_files_consumers_config_and_stays_suggest_only(tmp_path):
    facts = [F("endpoint", "POST /refunds", {"verb": "POST", "path": "/refunds", "framework": "s", "file": "Refund.java"}, repo="pay", path="Refund.java"),
             F("api_operation", "POST /refunds", {"protocol": "rest", "verb": "POST", "path": "/refunds", "parameters": [], "responses": ["200"], "has_request_body": True, "path_file": "openapi.yaml"}, repo="pay", path="openapi.yaml"),
             F("url_reference", "https://x.invalid/refunds", {"url": "https://x.invalid/refunds"}, repo="orders", path="Client.java"),
             F("config_key_use", "refund.limit", {"key": "refund.limit"}, repo="pay", path="Refund.java"),
             F("config_entry", "uat", {"key": "refund.limit", "value": "5", "environment": "UAT", "secret_like": False}, repo="pay", path="app-uat.yml"),
             F("source_file", "pay/RefundTest.java", {"language": "java", "lines": 4, "is_test": True}, repo="pay", path="RefundTest.java"),
             F("source_file", "pay/Refund.java", {"language": "java", "lines": 4, "is_test": False}, repo="pay", path="Refund.java"),
             make_fact("ownership", "o", {"repo": "orders", "pattern": "/", "team": "orders-team"}, "OBSERVED", [ev("orders/CODEOWNERS", "L1")], "o")]
    idx = semantic.HybridIndex(facts)
    r = impact.propose(idx, "add a refund reason to POST /refunds", llm=lambda p: "patch [[nowhere/X.java L1]]", verify=knowledge.verify_citations)
    assert r["found"] and r["label"].startswith("PROPOSAL")
    paths = [f"{e['repo']}/{e['path']}" for e in r["impact"]["files"]]
    assert {"pay/Refund.java", "pay/openapi.yaml", "orders/Client.java", "pay/app-uat.yml", "pay/RefundTest.java"} <= set(paths)
    assert "orders" in r["impact"]["consumers"] and "UAT" in r["impact"]["environments"] and "orders-team" in r["impact"]["teams_to_notify"]
    assert r["pr_draft"]["patch"].startswith("[REJECTED by verifier")
    assert not impact.propose(idx, "migrate the quantum flux capacitor")["found"]


# ---------- runner contract ----------
def test_runner_masks_output_and_drops_invalid_facts(tmp_path):
    import scribe.features as fx

    class Bad:
        @staticmethod
        def run(ctx):
            good = make_fact("risk_flag", "x", {"repo": "r", "note": "reach db-uat.corp.acme.com or 10.1.2.3"}, "DERIVED", [ev("r/a", "L1")], "t", "rule")
            bad = {**good, "evidence": []}
            return common.Result(files={"x/y.md": "contact jane.doe@acme.com at 10.9.8.7 token=Zx81QwErTyUiOp09AsDfGhJkLmNb4V\n"}, facts=[good, bad])

    class Boom:
        @staticmethod
        def run(ctx):
            raise RuntimeError("x")
    old = fx.FEATURES
    fx.FEATURES = [("bad", Bad, "bad"), ("boom", Boom, "boom")]
    try:
        out = fx.run_all(ctx_for([], tmp_path))
    finally:
        fx.FEATURES = old
    blob = out["files"]["x/y.md"] + json.dumps(out["facts"])
    assert "acme.com" not in blob and "10.9.8.7" not in blob and "10.1.2.3" not in blob and "Zx81Qw" not in blob
    assert out["dropped_facts"] == 1 and len(out["facts"]) == 1 and out["coverage"]["boom"].startswith("FAILED")


def test_disabled_features_are_skipped(tmp_path):
    import scribe.features as fx
    out = fx.run_all(ctx_for([], tmp_path, disabled_features="graph, sbom"))
    assert out["coverage"]["graph"] == "disabled in settings" and out["coverage"]["sbom"] == "disabled in settings"


# ---------- end to end: the feature pack inside a real run ----------
def test_pipeline_runs_feature_pack_and_second_run_produces_real_diff(sample_run):
    from scribe.orchestrator import Run
    run, tmp = sample_run
    st = run.execute()
    assert st["status"] == "complete" and st["gate"]["open"], st.get("error") or st.get("sweeps")
    zp = Path(st["zip"]["zip"])
    with zipfile.ZipFile(zp) as z:
        names = set(z.namelist())
        assert {"graph/graph.json", "sbom/cyclonedx.json", "scorecards/index.md", "drift/since-last-run.md", "catalog/cmdb.csv"} <= names
        first = z.read("drift/since-last-run.md").decode("utf-8")
        # every journal file is valid UTF-8 and free of the seeded sensitive values
        blob = "\n".join(z.read(n).decode("utf-8") for n in names)
    assert "UNKNOWN: this is the first run" in first
    for bad in ("Sup3rS3cretUat99", "Zx81QwErTy", "10.20.30.40", "db-uat.corp.acme.com", "Priya", "John Doe"):
        assert bad not in blob, bad
    assert (tmp / "out" / "history").is_dir() and not any(n.startswith("history/") for n in names)   # history stays outside the zip
    # change one config value, run again in the same output folder
    cfg = next((tmp / "src" / "payments-api").rglob("application-uat.*"))
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("20", "77", 1), encoding="utf-8")
    run2 = Run(run.s, known_secrets=["Sup3rS3cretUat99"])
    st2 = run2.execute()
    assert st2["status"] == "complete" and st2["gate"]["open"], st2.get("error") or st2.get("sweeps")
    with zipfile.ZipFile(st2["zip"]["zip"]) as z:
        second = z.read("drift/since-last-run.md").decode("utf-8")
    assert "UNKNOWN: this is the first run" not in second and "Compared with `run-" in second
    assert "1 changed" in second or "config_entry" in second          # the edited UAT value shows up as a real difference


# ---------- UI routes for features 8 and 9 ----------
def test_ui_impact_route_is_suggest_only_and_ask_uses_hybrid(tmp_path):
    from fastapi.testclient import TestClient
    from scribe.ui.app import create_app
    j = tmp_path / "out" / "journal" / "facts"
    j.mkdir(parents=True)
    facts = [F("endpoint", "POST /refunds", {"verb": "POST", "path": "/refunds", "framework": "s", "file": "Refund.java"}, repo="pay", path="Refund.java"),
             F("source_file", "pay/Refund.java", {"language": "java", "lines": 4, "is_test": False}, repo="pay", path="Refund.java")]
    (j / "all-facts.jsonl").write_text("\n".join(json.dumps(f) for f in facts) + "\n", encoding="utf-8")
    sp = tmp_path / "targets.yaml"
    Settings(output_dir=str(tmp_path / "out")).save(sp)
    c = TestClient(create_app(str(sp)))
    r = c.get("/api/impact", params={"q": "add a reason to POST /refunds"}).json()
    assert r["found"] and r["label"].startswith("PROPOSAL") and r["pr_draft"]["patch"] is None
    assert any(f["path"] == "Refund.java" for f in r["impact"]["files"])
    assert c.get("/api/impact", params={"q": "quantum flux capacitor"}).json()["found"] is False
    assert c.get("/api/impact", params={"q": "  "}).status_code == 400
    assert c.get("/api/ask", params={"q": "refunding"}).json()["found"]          # plural/stem match comes from the hybrid index
    assert c.put("/api/settings", json={"semantic_search": "false"}).json()["semantic_search"] is False
    assert not c.get("/api/ask", params={"q": "refunding"}).json()["found"]       # plain BM25 has no stemming
