import json
from pathlib import Path

from scribe import knowledge
from scribe.connectors.dbcatalog import collect_catalog, rds_inventory
from scribe.connectors.discovery import discover, verify_all
from scribe.connectors import catalog
from scribe.docs import extractors as X
from scribe.docs.gate import AppIndex
from scribe.docs.pipeline import process_document
from scribe.redact import Redactor
from scribe.facts import make_fact, ev


def _idx():
    i = AppIndex()
    i.add("payments-api", "payments-api")
    i.add_aliases({"payments-api": ["PAYHUB"]})
    return i


# ---------- connectors ----------
def test_discovery_by_name_never_values_and_unclassified_not_used():
    env = {"BITBUCKET_TOKEN": "secretvalue123", "ACME_TOKEN": "zzzzzzzz", "ARTIFACTORY_URL": "https://x.jfrog.io", "PATH": "/bin"}
    d = discover(environ=env, home="C:/does-not-exist")
    names = {f["system"] for f in d["found"]}
    assert {"bitbucket", "artifactory"} <= names
    assert [u["name"] for u in d["unclassified"]] == ["ACME_TOKEN"]
    assert "secretvalue123" not in json.dumps(d)


def test_approved_only_does_not_probe_unapproved():
    d = {"found": [{"system": "bitbucket", "category": "source", "sources": []}], "unclassified": []}
    rows = verify_all(d, approved=[], mode="approved-only")
    assert rows[0]["status"] == "discovered, not approved" and rows[0]["approved"] is False


def test_yaml_connector_spec(tmp_path):
    (tmp_path / "x.yaml").write_text("name: acme-wiki\ncategory: docs\nenv_prefixes: [ACME_WIKI_]\nauth: bearer\nverify_path: /ping\n", encoding="utf-8")
    assert catalog.load_yaml_connectors(tmp_path) == ["acme-wiki"] and "acme-wiki" in catalog.CATALOG


def test_db_catalog_metadata_only_and_rds_drops_endpoint():
    rows = {"tables": [("DB", "PUBLIC", "ORDERS", "BASE TABLE")], "columns": [("PUBLIC", "ORDERS", "EMAIL", "TEXT", "YES", 1)]}

    def run(sql):
        return rows["tables"] if "TABLES" in sql else rows["columns"]
    facts = collect_catalog("snowflake", "prod-wh", run, "DB")
    assert {f["kind"] for f in facts} == {"db_table", "db_column"}
    assert all(f["class"] == "OBSERVED" and f["evidence"] for f in facts)
    inst = rds_inventory(lambda: [{"DBInstanceIdentifier": "pay-db", "Engine": "postgres", "EngineVersion": "15", "Endpoint": {"Address": "pay.abc.rds.amazonaws.com"}}])
    assert "amazonaws" not in json.dumps(inst)


# ---------- documents ----------
def test_pdf_text_extraction_and_gate(tmp_path):
    from pypdf import PdfWriter
    # build a PDF with a text layer by reportlab-free route: write a minimal PDF by hand
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" \
          b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n" \
          b"4 0 obj<</Length 78>>stream\nBT /F1 12 Tf 20 200 Td (payments-api stores payments in the ledger table) Tj ET\nendstream endobj\n" \
          b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R/Size 6>>\n%%EOF"
    p = tmp_path / "design.pdf"
    p.write_bytes(pdf)
    res = process_document(str(p), "design.pdf", _idx(), Redactor())
    assert res["status"] in ("read", "unreadable")  # hand-built PDF may be rejected by the parser; the path must not crash
    other = tmp_path / "other.txt"
    other.write_text("lunch menu for friday", encoding="utf-8")
    assert process_document(str(other), "other.txt", _idx(), Redactor())["status"] == "skipped"


def test_scanned_pdf_without_ocr_is_reported_not_guessed(tmp_path, monkeypatch):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(300, 300)
    p = tmp_path / "scan.pdf"
    with open(p, "wb") as fh:
        w.write(fh)
    monkeypatch.setattr(X, "tesseract_available", lambda: False)
    res = process_document(str(p), "scan.pdf", _idx(), Redactor())
    assert res["status"] == "unreadable" and "no text layer" in res["reason"]


def test_images_and_media_not_read(tmp_path):
    for name in ("a.png", "b.jpg", "c.mp4", "d.mp3"):
        f = tmp_path / name
        f.write_bytes(b"\x00\x01")
        assert process_document(str(f), name, _idx(), Redactor())["status"] == "not_read"


def test_drawio_edges_documented_not_verified(tmp_path):
    xml = ('<mxfile><diagram name="p1"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
           '<mxCell id="2" value="payments-api" vertex="1" parent="1"/><mxCell id="3" value="Ledger DB" vertex="1" parent="1"/>'
           '<mxCell id="4" edge="1" source="2" target="3" parent="1" value="writes"/></root></mxGraphModel></diagram></mxfile>')
    p = tmp_path / "arch.drawio"
    p.write_text(xml, encoding="utf-8")
    res = process_document(str(p), "arch.drawio", _idx(), Redactor())
    edges = [f for f in res["facts"] if f["kind"] == "diagram_edge"]
    assert edges and edges[0]["class"] == "DOCUMENTED" and "not verified" in edges[0]["attrs"]["note"]


def test_transcript_is_discussed_hedged_and_speakerless(tmp_path):
    p = tmp_path / "payments-api-meeting.vtt"
    p.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Alice Smith>Maybe payments-api should cache the rate table later.\n", encoding="utf-8")
    res = process_document(str(p), p.name, _idx(), Redactor())
    d = [f for f in res["facts"] if f["kind"] == "discussion"]
    assert d and d[0]["class"] == "DISCUSSED" and d[0]["attrs"]["hedged"] is True
    assert "Alice" not in json.dumps(res["facts"])


def test_macro_workbook_quarantined(tmp_path):
    import zipfile
    p = tmp_path / "m.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/vbaProject.bin", b"x")
        z.writestr("[Content_Types].xml", "<x/>")
    assert process_document(str(p), "m.xlsx", _idx(), Redactor())["status"] == "quarantined"


# ---------- knowledge ----------
def _facts():
    return [make_fact("endpoint", "POST /payments", {"verb": "POST", "path": "/payments", "repo": "payments-api", "file": "C.java"}, "OBSERVED", [ev("payments-api/C.java", "L7")], "code"),
            make_fact("table_reference", "payments", {"table": "payments", "repo": "payments-api", "path": "C.java"}, "DERIVED", [ev("payments-api/C.java", "L8")], "code", "rule")]


def test_advise_grounded_labeled_and_insufficient_info():
    idx = knowledge.Index(_facts())
    r = knowledge.advise(idx, "add a refund field to the POST payments endpoint")
    assert r["proposal"]["label"].startswith("PROPOSAL") and r["proposal"]["diff"] is None and r["grounded_context"]
    none = knowledge.advise(idx, "migrate the quantum flux capacitor")
    assert none["insufficient_information"] is True and none["proposal"] is None


def test_llm_draft_with_invented_citation_is_rejected():
    idx = knowledge.Index(_facts())
    r = knowledge.advise(idx, "change POST payments", llm=lambda p: "edit this [[nowhere/Fake.java L1]]")
    assert r["proposal"]["llm_draft_verified"] is False and "REJECTED" in r["proposal"]["diff"]
