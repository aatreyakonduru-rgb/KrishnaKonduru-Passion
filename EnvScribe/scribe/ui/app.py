"""Control API + single-page UI (Option C2: mission control with sweeps). Single user.

The UI never holds credentials. Setup fields are non-secret. Uploads are untrusted: size/type checks, quarantine, redaction on read.
"""
from __future__ import annotations

import json
import os
import re
import threading
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import knowledge
from ..connectors.discovery import discover, verify_all
from ..docs.extractors import classify_type
from ..orchestrator import Run
from ..settings import Settings
from ..util import atomic_write, safe_join

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 100 * 1024 * 1024
SAFE_NAME = re.compile(r"[^A-Za-z0-9._\- ]")


MAX_VIEW_BYTES = 5 * 1024 * 1024
VIEW_TEXT_EXT = {".md", ".json", ".jsonl", ".txt", ".yaml", ".yml", ".csv", ".log", ".xml", ""}


def create_app(settings_path: str = "targets.yaml", on_exit=None) -> FastAPI:
    """on_exit: callable that stops the server process. Default: hard-exit the process after the response is sent."""
    app = FastAPI(title="EnvScribe", docs_url=None, redoc_url=None)
    holder: dict = {"settings": Settings.load(settings_path), "run": None, "thread": None}
    lock = threading.Lock()

    def S() -> Settings:
        return holder["settings"]

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/settings")
    def get_settings():
        return S().to_dict()

    @app.put("/api/settings")
    def put_settings(body: dict):
        with lock:
            if holder["thread"] and holder["thread"].is_alive():
                raise HTTPException(409, "settings changes take effect on the next run; a run is active")
            body = {k: v for k, v in body.items() if k in Settings.__dataclass_fields__}
            holder["settings"] = Settings.from_dict({**S().to_dict(), **body})
            holder["settings"].save(settings_path)
        return holder["settings"].to_dict()

    @app.get("/api/integrations")
    def integrations():
        d = discover()
        rows = verify_all(d, S().approved_integrations, S().integration_mode)
        return {"integrations": rows, "unclassified": d["unclassified"], "mode": S().integration_mode}

    @app.post("/api/integrations/approve")
    def approve(body: dict):
        names = [n for n in body.get("approved", []) if isinstance(n, str)]
        with lock:
            holder["settings"].approved_integrations = names
            holder["settings"].save(settings_path)
        return {"approved": names}

    @app.get("/api/estimate")
    def estimate():
        return Run(S()).estimate()

    @app.post("/api/run/start")
    def start():
        with lock:
            if holder["thread"] and holder["thread"].is_alive():
                raise HTTPException(409, "a run is already active")
            run = Run(S())
            holder["run"] = run
            t = threading.Thread(target=run.execute, name="envscribe-run", daemon=True)
            holder["thread"] = t
            t.start()
        return {"run_id": run.run_id}

    def current() -> Run:
        if not holder["run"]:
            raise HTTPException(404, "no run yet")
        return holder["run"]

    @app.post("/api/run/pause")
    def pause():
        current().pause()
        return {"ok": True}

    @app.post("/api/run/resume")
    def resume():
        r = current()
        if holder["thread"] and holder["thread"].is_alive():
            r.resume_flag()
        else:  # resume from progress file after a stop/crash: same folder, same config
            run = Run(S())
            holder["run"] = run
            t = threading.Thread(target=run.execute, name="envscribe-run", daemon=True)
            holder["thread"] = t
            t.start()
        return {"ok": True}

    @app.post("/api/run/cancel")
    def cancel():
        current().cancel()
        return {"ok": True}

    @app.get("/api/run/status")
    def status():
        if not holder["run"]:
            return {"status": "idle", "stages": {}, "counters": {}, "workers": [], "events": [], "gate": {"open": False, "reason": "no run yet"}}
        r = holder["run"]
        with r._lk:
            return JSONResponse(json.loads(json.dumps(r.state, default=str)))

    @app.get("/api/run/zip")
    def download():
        r = current()
        gate = r.state.get("gate", {})
        if not gate.get("open") or not r.state.get("zip"):
            raise HTTPException(403, f"zip is not available: {gate.get('reason', 'run not complete')}")
        p = Path(r.state["zip"]["zip"])
        if not p.exists():
            raise HTTPException(404, "zip file missing")
        return FileResponse(p, filename=p.name, media_type="application/zip")

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        name = SAFE_NAME.sub("_", Path(file.filename or "file").name)[:150] or "file"
        kind = classify_type(name)
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "file too large")
        dest = safe_join(S().uploads, name)
        Path(S().uploads).mkdir(parents=True, exist_ok=True)
        status = {"not_read": "not read (images/video/audio are out of scope)", "quarantine": "quarantined (legacy or macro format)",
                  "unknown": "type not understood; listed only"}.get(kind, "accepted")
        atomic_write(dest, data)
        return {"file": name, "intake": status, "type": kind}

    @app.get("/api/uploads")
    def uploads():
        up = Path(S().uploads)
        dec = {}
        dp = up / ".decisions.json"
        if dp.exists():
            try:
                dec = json.loads(dp.read_text(encoding="utf-8"))
            except ValueError:
                pass
        intake = []
        ip = Path(S().output_dir) / "intake.jsonl"
        if ip.exists():
            from ..util import read_jsonl
            intake = read_jsonl(ip)
        files = [{"file": str(p.relative_to(up)).replace("\\", "/"), "size": p.stat().st_size, "type": classify_type(p.name),
                  "decision": dec.get(str(p.relative_to(up)).replace("\\", "/"))} for p in sorted(up.glob("**/*")) if p.is_file() and not p.name.startswith(".")] if up.exists() else []
        return {"files": files, "intake": intake}

    @app.post("/api/uploads/decision")
    def decision(body: dict):
        up = Path(S().uploads)
        up.mkdir(parents=True, exist_ok=True)
        dp = up / ".decisions.json"
        cur = json.loads(dp.read_text(encoding="utf-8")) if dp.exists() else {}
        name = SAFE_NAME.sub("_", Path(str(body.get("file", ""))).name)
        cur[name] = {"apps": body.get("apps") or None, "read_anyway": bool(body.get("read_anyway"))}
        atomic_write(dp, json.dumps(cur, indent=2))
        return cur[name]

    def journal_index() -> knowledge.Index:
        jd = Path(S().output_dir) / "journal"
        if not jd.exists():
            raise HTTPException(404, "no journal yet")
        if S().semantic_search:
            try:
                from ..features.semantic import HybridIndex
                return HybridIndex.from_journal(jd)
            except Exception:   # hybrid search is an enhancement; plain BM25 still answers
                pass
        return knowledge.Index.from_journal(jd)

    @app.get("/api/ask")
    def ask(q: str):
        return knowledge.ask(journal_index(), q)

    @app.get("/api/impact")
    def impact_route(q: str):
        """Suggest-only change impact + PR draft text for a requirement. Reads the journal; writes nothing; no LLM is called here."""
        if not q.strip():
            raise HTTPException(400, "empty requirement")
        from ..features import impact
        return impact.propose(journal_index(), q)

    @app.get("/api/advise")
    def advise_route(q: str):
        """Suggest-only Advise: grounded, cited context from the hybrid index plus a PROPOSAL. Writes nothing; no LLM is called here."""
        if not q.strip():
            raise HTTPException(400, "empty requirement")
        from .. import knowledge
        return knowledge.advise(journal_index(), q)

    # ---- Viewer: read-only browsing of sealed output zips (the run's own, or one uploaded) ----
    def viewer_zips() -> dict[str, Path]:
        out = Path(S().output_dir).resolve()
        found: dict[str, Path] = {}
        for d in (out, out / "_viewer"):
            if d.is_dir():
                for p in sorted(d.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
                    found.setdefault(p.name, p)
        return found

    def open_zip(name: str) -> zipfile.ZipFile:
        p = viewer_zips().get(name)
        if not p:
            raise HTTPException(404, "zip not found")
        try:
            return zipfile.ZipFile(p)
        except zipfile.BadZipFile:
            raise HTTPException(400, "not a valid zip file")

    def read_member(z: zipfile.ZipFile, path: str) -> bytes:
        try:
            info = z.getinfo(path)
        except KeyError:
            raise HTTPException(404, "file not in zip")
        if info.file_size > MAX_VIEW_BYTES:
            raise HTTPException(413, f"file is {info.file_size} bytes; viewer limit is {MAX_VIEW_BYTES}")
        return z.read(info)

    @app.get("/viewer", response_class=HTMLResponse)
    def viewer_page():
        return (STATIC / "viewer.html").read_text(encoding="utf-8")

    @app.get("/api/viewer/zips")
    def v_zips():
        cur = (holder["run"].state.get("zip") or {}).get("zip") if holder["run"] else None
        return {"zips": [{"name": n, "size": p.stat().st_size, "current": bool(cur and Path(cur).name == n)}
                         for n, p in viewer_zips().items()]}

    @app.post("/api/viewer/upload")
    async def v_upload(file: UploadFile = File(...)):
        name = SAFE_NAME.sub("_", Path(file.filename or "journal.zip").name)[:150]
        if not name.lower().endswith(".zip"):
            raise HTTPException(400, "only .zip files can be opened in the viewer")
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "file too large")
        dest = Path(S().output_dir).resolve() / "_viewer" / name
        atomic_write(dest, data)
        try:
            with zipfile.ZipFile(dest) as z:
                if z.testzip() is not None:
                    raise zipfile.BadZipFile()
        except zipfile.BadZipFile:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "not a valid zip file")
        return {"name": name}

    @app.get("/api/viewer/tree")
    def v_tree(zip: str):
        with open_zip(zip) as z:
            files = [{"path": i.filename, "size": i.file_size} for i in z.infolist() if not i.is_dir()]
            seal = None
            if "SEAL.json" in z.namelist():
                try:
                    s = json.loads(z.read("SEAL.json"))
                    seal = {"label": s.get("label"), "sealed_at": s.get("sealed_at"), "files": s.get("files")}
                except ValueError:
                    pass
        return {"files": sorted(files, key=lambda f: (f["path"].count("/"), f["path"])), "seal": seal}

    @app.get("/api/viewer/file")
    def v_file(zip: str, path: str):
        if Path(path).suffix.lower() not in VIEW_TEXT_EXT:
            raise HTTPException(415, "not a text file; the viewer only shows text content")
        with open_zip(zip) as z:
            raw = read_member(z, path)
        return {"path": path, "text": raw.decode("utf-8", errors="replace")}

    @app.get("/api/viewer/facts")
    def v_facts(zip: str, q: str = "", kind: str = "", cls: str = "", limit: int = 200):
        limit = max(1, min(limit, 1000))
        with open_zip(zip) as z:
            if "facts/all-facts.jsonl" not in z.namelist():
                raise HTTPException(404, "this zip has no facts/all-facts.jsonl")
            raw = read_member(z, "facts/all-facts.jsonl").decode("utf-8", errors="replace")
        kinds: dict[str, int] = {}
        classes: dict[str, int] = {}
        hits, total = [], 0
        ql = q.lower().strip()
        for line in raw.splitlines():
            try:
                f = json.loads(line)
            except ValueError:
                continue
            kinds[f.get("kind", "?")] = kinds.get(f.get("kind", "?"), 0) + 1
            classes[f.get("class", "?")] = classes.get(f.get("class", "?"), 0) + 1
            if kind and f.get("kind") != kind:
                continue
            if cls and f.get("class") != cls:
                continue
            if ql and ql not in line.lower():
                continue
            total += 1
            if len(hits) < limit:
                hits.append(f)
        return {"total": total, "shown": len(hits), "facts": hits, "kinds": kinds, "classes": classes}

    # ---- Exit ----
    @app.post("/api/exit")
    def exit_app():
        """Cancel any active run (a partial zip is produced), wait briefly for it, then stop the server."""
        t = holder["thread"]
        was_running = bool(t and t.is_alive())
        if was_running and holder["run"]:
            holder["run"].cancel()

        def _stop():
            if t and t.is_alive():
                t.join(timeout=30)
            if on_exit:
                on_exit()
            else:
                os._exit(0)

        threading.Timer(0.5, _stop).start()
        return {"stopping": True, "cancelled_active_run": was_running}

    return app


app = create_app()
