"""Orchestrator: inventory -> packages -> parallel workers -> collate -> docs -> analyses -> journal -> sweeps -> seal -> verify.

Holds only pointers (package ids, statuses, counters). File contents live in worker chunks on disk, never in a shared context.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import SCANNER_VERSION, analyses, collate as collator, journal, sweeps
from .connectors.catalog import CATALOG, collect as connector_collect
from .connectors.discovery import discover, verify_all
from .docs.extractors import classify_type
from .docs.gate import AppIndex
from .docs.pipeline import process_document
from .facts import ev, make_fact
from .redact import Redactor
from .runstate import Audit, Progress, RunLock, read_manifest, write_manifest, config_fingerprint
from .settings import Settings
from .util import append_jsonl, atomic_write, now_iso, read_jsonl, write_jsonl
from .worker import make_packages, run_package

STAGES = ["inventory", "code-build-config", "documents", "connectors", "collate", "journal", "privacy-sweep", "secret-sweep", "seal-zip", "verify-zip"]


class Cancelled(Exception):
    pass


class Run:
    def __init__(self, settings: Settings, run_id: str | None = None, known_secrets: list[str] | None = None):
        self.s = settings
        self.out = Path(settings.output_dir).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or "run-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.audit = Audit(self.out / "audit.jsonl")
        self.progress = Progress(self.out / "progress.jsonl", SCANNER_VERSION)
        self.lock = RunLock(self.out / "run.lock")
        self.redactor = Redactor(custom_terms=settings.custom_terms)
        self.redactor.set_known_values(known_secrets if known_secrets is not None else collect_env_secret_values())
        self.state: dict = {"run_id": self.run_id, "status": "idle", "stage": None, "stages": {s: "pending" for s in STAGES},
                            "counters": {"packages": 0, "packages_done": 0, "units_done": 0, "skipped": 0, "failed": 0, "tokens": 0},
                            "workers": [], "events": [], "sweeps": None, "gate": {"open": False, "reason": "run not complete"},
                            "as_of": None, "zip": None, "resumed": False}
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._lk = threading.Lock()

    # ---------- controls ----------
    def cancel(self):
        self._cancel.set()

    def pause(self):
        self._pause.set()
        self.event("paused")

    def resume_flag(self):
        self._pause.clear()
        self.event("resumed")

    def _check(self):
        while self._pause.is_set() and not self._cancel.is_set():
            time.sleep(0.2)
        if self._cancel.is_set():
            raise Cancelled()

    def event(self, kind: str, **kw):
        e = {"ts": now_iso(), "kind": kind, **kw}
        with self._lk:
            self.state["events"].append(e)
            self.state["events"] = self.state["events"][-300:]
        self.audit(kind, **kw)

    def _stage(self, name: str, status: str):
        with self._lk:
            self.state["stages"][name] = status
            if status == "running":
                self.state["stage"] = name
        self.event("stage", stage=name, status=status)

    # ---------- estimate ----------
    def estimate(self) -> dict:
        pkgs, skips, units = 0, 0, 0
        for name, root in self._repos():
            p, sk = make_packages(name, root, self.s, "estimate")
            pkgs += len(p)
            skips += len(sk)
            units += sum(len(x["units"]) for x in p)
        uploads = [f for f in Path(self.s.uploads).glob("*") if f.is_file()] if Path(self.s.uploads).exists() else []
        return {"repos": len(self._repos()), "packages": pkgs, "units": units, "ignored": skips, "uploads": len(uploads),
                "workers": min(self.s.max_workers, max(pkgs, 1)),
                "token_budget": "unlimited" if self.s.unlimited_tokens else self.s.token_budget,
                "llm_tokens_expected": 0 if self.s.llm_provider == "none" else "depends on summaries"}

    def _repos(self) -> list[tuple[str, str]]:
        out = []
        for src in self.s.sources:
            p = Path(src)
            if p.is_dir():
                out.append((p.name, str(p.resolve())))
        return out

    # ---------- main ----------
    def execute(self) -> dict:
        if not self.lock.acquire():
            raise RuntimeError("another run is using this output folder (run.lock)")
        try:
            prior = read_manifest(self.out / "manifest.json")
            fp = config_fingerprint(self.s.to_dict())
            if prior and prior.get("config_fingerprint") == fp and self.progress.done_count():
                self.state["resumed"] = True
                self.event("resume", reused_units=self.progress.done_count())
            elif prior and prior.get("config_fingerprint") != fp:
                # materially different configuration: never mix old and new facts silently
                self.event("config_changed", note="starting fresh; prior progress not reused")
                for f in ("progress.jsonl",):
                    (self.out / f).unlink(missing_ok=True)
                shutil.rmtree(self.out / "units", ignore_errors=True)
                shutil.rmtree(self.out / "chunks", ignore_errors=True)
                self.progress = Progress(self.out / "progress.jsonl", SCANNER_VERSION)
            write_manifest(self.out / "manifest.json", self.run_id, self.s.to_dict(), SCANNER_VERSION)
            self.state["status"] = "running"
            self._pipeline()
        except Cancelled:
            self.state["status"] = "cancelled"
            self.event("cancelled")
            self._partial_zip()
        except Exception as exc:
            self.state["status"] = "failed"
            self.event("failed", error=type(exc).__name__)
            self.state["error"] = type(exc).__name__ + ": " + str(exc)[:200]
        finally:
            self.lock.release()
            self._write_state()
        return self.state

    def _pipeline(self):
        s = self.s
        # ---- inventory
        self._stage("inventory", "running")
        all_pkgs, skips = [], []
        for name, root in self._repos():
            p, sk = make_packages(name, root, s, self.run_id)
            all_pkgs += p
            skips += sk
        self.state["counters"]["packages"] = len(all_pkgs)
        self.state["counters"]["skipped"] += len(skips)
        write_jsonl(self.out / "inventory-skips.jsonl", skips)
        self._stage("inventory", "done")
        # ---- scan
        self._stage("code-build-config", "running")
        self._run_packages(all_pkgs)
        self._stage("code-build-config", "done")
        self._check()
        # ---- documents (needs the application index from the code crawl)
        self._stage("documents", "running")
        doc_facts, doc_register, doc_skips, intake = self._documents()
        self._stage("documents", "done")
        # ---- connectors
        self._stage("connectors", "running")
        conn_facts, integrations, unclassified = self._connectors()
        self._stage("connectors", "done")
        self._check()
        # ---- collate
        self._stage("collate", "running")
        extra = self.out / "extra-facts.jsonl"
        write_jsonl(extra, doc_facts + conn_facts)
        coll = collator.collate(self.out, self.redactor, [extra])
        coll["register"] += doc_register
        coll["skips"] += doc_skips + [{**x} for x in skips]
        self._stage("collate", "done")
        # ---- journal
        self._stage("journal", "running")
        facts = coll["facts"]
        links = analyses.link_facts(facts)
        matrix = analyses.env_matrix(facts, s.normalize_env)
        owners = self._ownership()
        pii = analyses.pii_candidates(facts)
        lin = analyses.lineage(facts)
        doc_code = analyses.doc_vs_code(facts)
        cov = self._coverage(coll, intake, integrations)
        journal_root = self.out / "journal"
        shutil.rmtree(journal_root, ignore_errors=True)
        journal.write_journal(journal_root, self.run_id, coll, links, matrix, pii, lin, doc_code, integrations, unclassified, cov, owners, s.to_dict())
        atomic_write(journal_root / "run-manifest.json", (self.out / "manifest.json").read_text(encoding="utf-8"))
        self.state["as_of"] = {"min": coll["as_of_min"], "max": coll["as_of_max"], "collated_at": coll["collated_at"]}
        self._stage("journal", "done")
        self._check()
        # ---- sweeps -> seal -> verify
        self._finish_output(journal_root, label="complete")
        self.state["status"] = "complete" if self.state["gate"]["open"] else "blocked"

    def _finish_output(self, journal_root: Path, label: str):
        s = self.s
        self._stage("privacy-sweep", "running")
        self.state["sweeps"] = {"privacy": "running", "secret": "queued"}
        res = sweeps.run_sweeps(journal_root, self.redactor, s.exclude_sources, s.sweep_mode, events=lambda *a, **k: self.event(*a, **k))
        self._stage("privacy-sweep", "done" if not res["privacy"]["findings"] else "findings")
        self._stage("secret-sweep", "done" if not res["secret"]["findings"] else "findings")
        self.state["sweeps"] = {
            "privacy": {"checks": res["privacy"]["checks"], "findings": len(res["privacy"]["findings"])},
            "secret": {"checks": res["secret"]["checks"], "findings": len(res["secret"]["findings"])},
            "blocking": res["blocking"][:200], "attempts": res["attempts"], "completed_at": res["completed_at"]}
        if not res["passed"]:
            self.state["gate"] = {"open": False, "reason": f"{len(res['blocking'])} blocking finding(s); zip not created"}
            self._stage("seal-zip", "blocked")
            self._frozen = res["frozen"]
            return
        self._stage("seal-zip", "running")
        zip_path = self.out / f"{self.run_id}-journal.zip"
        sealed = sweeps.seal_zip(journal_root, zip_path, res["frozen"], label)
        self._stage("seal-zip", "done")
        self._stage("verify-zip", "running")
        ver = sweeps.verify_zip(zip_path, self.redactor, s.exclude_sources)
        if not ver["passed"]:
            zip_path.unlink(missing_ok=True)
            self.state["gate"] = {"open": False, "reason": f"final rescan of sealed zip found {len(ver['findings'])} finding(s); zip withheld"}
            self.state["sweeps"]["blocking"] = ver["findings"][:200]
            self._stage("verify-zip", "blocked")
            return
        self._stage("verify-zip", "done")
        self.state["zip"] = {**sealed, "label": label}
        self.state["gate"] = {"open": True, "reason": "both sweeps passed and sealed zip rescanned clean"}
        self.event("zip_ready", file=zip_path.name)

    def _partial_zip(self):
        """On cancel: build a partial journal from chunks finished so far, label it partial, and pass it through the same gates."""
        try:
            extra = self.out / "extra-facts.jsonl"
            coll = collator.collate(self.out, self.redactor, [extra] if extra.exists() else [])
            if not coll["facts"]:
                return
            jr = self.out / "journal-partial"
            shutil.rmtree(jr, ignore_errors=True)
            facts = coll["facts"]
            journal.write_journal(jr, self.run_id, coll, [], {"environments": [], "rows": []}, [], [], [], [], [],
                                  {"status": "PARTIAL - run was cancelled; many sections are incomplete"}, [], self.s.to_dict())
            self._finish_output(jr, label="partial")
        except Exception as exc:
            self.event("partial_zip_failed", error=type(exc).__name__)

    # ---------- parallel scan ----------
    def _run_packages(self, pkgs: list[dict]):
        s = self.s
        workers = max(1, min(s.max_workers, len(pkgs) or 1))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="worker") as ex:
            futs = {}
            for pkg in pkgs:
                self._check()
                futs[ex.submit(self._one_package, pkg)] = pkg["package_id"]
            for fut in as_completed(futs):
                pid = futs[fut]
                try:
                    meta = fut.result()
                    with self._lk:
                        c = self.state["counters"]
                        c["packages_done"] += 1
                        c["units_done"] += sum(1 for u in meta["units"] if u["status"] == "done")
                        c["failed"] += sum(1 for u in meta["units"] if u["status"] == "failed")
                        c["skipped"] += meta["counts"]["skips"]
                except Cancelled:
                    for f in futs:
                        f.cancel()
                    raise
                except Exception as exc:
                    with self._lk:
                        self.state["counters"]["failed"] += 1
                    self.event("package_failed", package=pid, error=type(exc).__name__)

    def _one_package(self, pkg: dict) -> dict:
        self._check()
        row = {"package": pkg["package_id"], "scope": pkg["repo"], "status": "running", "units": f"0/{len(pkg['units'])}", "started": now_iso()}
        with self._lk:
            self.state["workers"].append(row)
        try:
            meta = run_package(pkg, self.s, self.out, self.redactor, self.progress, self.audit)
            row["status"] = "chunk merged"
            row["units"] = f"{len(pkg['units'])}/{len(pkg['units'])}"
            return meta
        except Exception:
            row["status"] = "failed"
            raise

    # ---------- documents ----------
    def _documents(self):
        facts_for_index = [f for d in sorted((self.out / "chunks").glob("*")) for f in read_jsonl(d / "chunk.jsonl")] if (self.out / "chunks").exists() else []
        index = AppIndex.from_facts(facts_for_index, self.s.aliases)
        facts, register, skips, intake = [], [], [], []
        up = Path(self.s.uploads)
        files = [p for p in sorted(up.glob("**/*")) if p.is_file() and not p.name.endswith(".meta.json")] if up.exists() else []
        decisions = _load_decisions(up)
        for p in files:
            self._check()
            rel = str(p.relative_to(up)).replace("\\", "/")
            if any(x and x in rel for x in self.s.exclude_sources):
                intake.append({"file": rel, "status": "skipped", "reason": "excluded source (never opened)"})
                continue
            tags = decisions.get(rel, {}).get("apps")
            force = decisions.get(rel, {}).get("read_anyway", False)
            res = process_document(str(p), rel, index, self.redactor, tags, force)
            facts += res["facts"]
            register += res["register"]
            intake.append({k: v for k, v in res.items() if k not in ("facts", "register")})
            if res["status"] != "read":
                skips.append({"item": f"upload:{rel}", "reason": f"{res['status']}: {res['reason']}"})
            self.event("document", file=rel, status=res["status"])
        write_jsonl(self.out / "intake.jsonl", intake)
        return facts, register, skips, intake

    # ---------- connectors ----------
    def _connectors(self):
        d = discover()
        rows = verify_all(d, self.s.approved_integrations, self.s.integration_mode, audit=self.audit)
        facts = []
        for r in rows:
            if r["status"] == "verified" and r["system"] in CATALOG and CATALOG[r["system"]].collectors:
                facts += connector_collect(CATALOG[r["system"]], {}, audit=self.audit)
        return facts, rows, d["unclassified"]

    def _ownership(self):
        out = []
        for name, root in self._repos():
            for rel in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS", ".bitbucket/CODEOWNERS"):
                p = Path(root) / rel
                if p.is_file():
                    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                        parts = line.split("#")[0].split()
                        if len(parts) >= 2:
                            out += [(name, parts[0], o) for o in parts[1:]]
        return analyses.ownership([], out)

    def _coverage(self, coll, intake, integrations) -> dict:
        by = {}
        for i in intake:
            by[i["status"]] = by.get(i["status"], 0) + 1
        return {"packages merged": f"{self.state['counters']['packages_done']} of {self.state['counters']['packages']}",
                "facts": len(coll["facts"]), "skipped items": len(coll["skips"]), "rejected chunks/facts": len(coll["rejected"]),
                "documents by outcome": by or "none supplied", "integrations": f"{sum(1 for i in integrations if i['status'] == 'verified')} verified of {len(integrations)} discovered",
                "OCR available": __import__("scribe.docs.extractors", fromlist=["x"]).tesseract_available(),
                "images/video/audio": "not read by design", "token budget": "unlimited" if self.s.unlimited_tokens else self.s.token_budget}

    def _write_state(self):
        try:
            atomic_write(self.out / "state.json", __import__("json").dumps({k: v for k, v in self.state.items() if k != "events"}, indent=2, default=str))
        except Exception:
            pass


def collect_env_secret_values() -> list[str]:
    """Values of credential-like environment variables, used ONLY as hashes for the known-value sweep."""
    import re
    rx = re.compile(r"(?i)(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PAT|CREDENTIAL)")
    return [v for k, v in os.environ.items() if rx.search(k) and v and len(v) >= 6]


def _load_decisions(upload_dir: Path) -> dict:
    p = upload_dir / ".decisions.json"
    if p.exists():
        try:
            import json
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}
