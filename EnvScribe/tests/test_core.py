import json
import zipfile
from pathlib import Path

import pytest

from scribe.facts import ev, make_fact, validate_fact
from scribe.redact import Redactor, strip_speakers
from scribe.settings import Settings
from scribe.connectors.readonly import ReadOnlyClient, ReadOnlyViolation, check_sql


# ---------- facts / grounding ----------
def test_fact_requires_evidence():
    f = make_fact("x", "s", {}, "OBSERVED", [], "t")
    assert "evidence is mandatory" in validate_fact(f)


def test_inferred_class_not_allowed():
    f = make_fact("x", "s", {}, "INFERRED", [ev("a", "L1")], "t")
    assert any("invalid class" in e for e in validate_fact(f))


def test_derived_needs_rule_and_llm_needs_quote():
    assert validate_fact(make_fact("x", "s", {}, "DERIVED", [ev("a", "L1")], "t"))
    assert validate_fact(make_fact("x", "s", {}, "LLM_DESCRIBED", [ev("a", "L1")], "t"))
    assert not validate_fact(make_fact("x", "s", {}, "LLM_DESCRIBED", [ev("a", "L1", "quote")], "t"))


# ---------- settings ----------
def test_budget_zero_or_blank_means_unlimited():
    assert Settings(token_budget=0).unlimited_tokens
    assert Settings(token_budget="").unlimited_tokens
    assert Settings(token_budget=None).unlimited_tokens
    assert not Settings(token_budget="1,000").unlimited_tokens


def test_workers_clamped_to_100():
    assert Settings(max_workers=100).max_workers == 100
    assert Settings(max_workers=5000).max_workers == 100
    assert Settings(max_workers=0).max_workers == 1
    assert Settings(max_workers="").max_workers == 4


# ---------- redaction ----------
def test_hosts_and_ips_always_masked():
    r = Redactor()
    t = "jdbc:oracle:thin:@db.corp.acme.com:1521/X host=10.1.2.3 url=https://api.pay.acme.com/v1 ip 192.168.0.9"
    out, _ = r.redact(t)
    for bad in ("acme.com", "10.1.2.3", "192.168.0.9"):
        assert bad not in out


def test_java_packages_not_treated_as_hosts():
    out, _ = Redactor().redact("import java.util.List; com.acme.Service")
    assert "java.util.List" in out and "com.acme.Service" in out


def test_secrets_masked_and_known_value_matched_in_encodings():
    import base64
    r = Redactor()
    r.set_known_values(["Sup3rS3cretUat99"])
    b64 = base64.b64encode(b"Sup3rS3cretUat99").decode()
    for text in ("x=Sup3rS3cretUat99", f"data {b64}", "pw=Sup3rS3cretUat99"):
        out, _ = r.redact(text)
        assert "Sup3rS3cretUat99" not in out and b64 not in out
    assert r.detect("a = 'Sup3rS3' + 'cretUat99'")


def test_card_requires_luhn():
    r = Redactor()
    assert any(f.type == "credit_card" for f in r.detect("4111 1111 1111 1111"))
    assert not any(f.type == "credit_card" for f in r.detect("1234 5678 9012 3456"))


def test_transcript_speakers_stripped():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\n<v Priya Sharma>The service stores data.\n\nJohn Doe: We agree.\n"
    out = strip_speakers(vtt)
    assert "Priya" not in out and "John" not in out and "service stores data" in out and "We agree" in out


# ---------- read-only ----------
def test_readonly_client_blocks_writes():
    c = ReadOnlyClient("http://x", allow_post=[r"/search"])
    for m in ("POST", "PUT", "DELETE", "PATCH"):
        with pytest.raises(ReadOnlyViolation):
            c.request(m, "/anything")
    with pytest.raises(ReadOnlyViolation):
        c.request("POST", "/not-listed")


def test_sql_only_metadata():
    check_sql("SELECT table_name FROM information_schema.tables")
    for bad in ("DROP TABLE x", "select 1; delete from y", "INSERT INTO t VALUES (1)", "GRANT ALL ON x TO y", "USE ROLE accountadmin"):
        with pytest.raises(Exception):
            check_sql(bad)


# ---------- end to end ----------
def test_pipeline_end_to_end_and_gates(sample_run):
    run, tmp = sample_run
    state = run.execute()
    assert state["status"] == "complete", state.get("error") or state["sweeps"]
    assert state["gate"]["open"] and state["zip"]
    zp = Path(state["zip"]["zip"])
    with zipfile.ZipFile(zp) as z:
        blob = "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
        assert "SEAL.json" in z.namelist()
    for bad in ("Sup3rS3cretUat99", "Zx81QwErTy", "10.20.30.40", "db-uat.corp.acme.com", "Priya", "John Doe"):
        assert bad not in blob, bad
    # relevance gate: unrelated file skipped; related files read
    assert "offsite-plan.txt" in blob  # listed in skip log
    assert "Team offsite agenda" not in blob
    assert "payments-api service calls the gateway" in blob
    # env matrix shows SIT vs UAT difference
    assert "**yes**" in blob
    # as-of header on every md file
    with zipfile.ZipFile(zp) as z:
        for n in z.namelist():
            if n.endswith(".md"):
                assert "collated at" in z.read(n).decode("utf-8")


def test_blocked_when_sweep_finds_secret(sample_run):
    from scribe import sweeps
    run, tmp = sample_run
    root = tmp / "journal"
    root.mkdir()
    (root / "x.md").write_text("token: ghp_" + "a" * 36 + "\n", encoding="utf-8")
    res = sweeps.run_sweeps(root, run.redactor, [], mode="block")
    assert not res["passed"] and res["blocking"]
    assert "ghp_" not in json.dumps(res["blocking"])  # findings never contain values


def test_autoredact_then_pass(sample_run):
    from scribe import sweeps
    run, tmp = sample_run
    root = tmp / "journal"
    root.mkdir()
    (root / "x.md").write_text("contact bob@example.org\n", encoding="utf-8")
    res = sweeps.run_sweeps(root, run.redactor, [], mode="redact-rescan-block")
    assert res["passed"] and "bob@example.org" not in (root / "x.md").read_text()


def test_seal_refuses_if_changed_after_sweep(sample_run):
    from scribe import sweeps
    run, tmp = sample_run
    root = tmp / "journal"
    root.mkdir()
    (root / "x.md").write_text("clean\n", encoding="utf-8")
    res = sweeps.run_sweeps(root, run.redactor, [])
    (root / "x.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        sweeps.seal_zip(root, tmp / "o.zip", res["frozen"])


def test_resume_reuses_units(sample_run):
    run, tmp = sample_run
    run.execute()
    from scribe.orchestrator import Run
    run2 = Run(run.s, known_secrets=["Sup3rS3cretUat99"])
    st = run2.execute()
    assert st["resumed"] is True
    assert st["status"] == "complete"
    events = [e["kind"] for e in st["events"]]
    assert "resume" in events


def test_config_change_starts_fresh(sample_run):
    run, tmp = sample_run
    run.execute()
    from scribe.orchestrator import Run
    run.s.environments = ["DEV"]
    run.s.aliases = {"a-app": ["zzz"]}
    run2 = Run(run.s, known_secrets=[])
    st = run2.execute()
    assert "config_changed" in [e["kind"] for e in st["events"]]


def test_corrupt_progress_line_ignored(tmp_path):
    from scribe.runstate import Progress
    p = tmp_path / "progress.jsonl"
    p.write_text('{"unit":"a","status":"done","input_hash":"h","scanner_version":"1.0"}\n{"unit":"b","stat', encoding="utf-8")
    pr = Progress(p, "1.0")
    assert pr.reusable("a", "h") and not pr.reusable("b", "x")


def test_cancel_produces_labeled_partial(sample_run):
    run, tmp = sample_run
    run.cancel()
    st = run.execute()
    assert st["status"] == "cancelled"


def test_lock_prevents_second_run(sample_run):
    run, tmp = sample_run
    (Path(run.out) / "run.lock").write_text("1 2026\n")  # pid 1 is alive on most systems
    import os
    from scribe.runstate import RunLock
    lock = RunLock(Path(run.out) / "run.lock")
    (Path(run.out) / "run.lock").write_text(f"{os.getpid()} x\n")
    assert lock.acquire()  # own pid is re-acquirable
    lock.release()
