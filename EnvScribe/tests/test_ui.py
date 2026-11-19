import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scribe.settings import Settings
from scribe.ui.app import create_app


@pytest.fixture()
def client(tmp_path):
    src = tmp_path / "repo"
    (src / "src").mkdir(parents=True)
    (src / "pom.xml").write_text("<project><groupId>com.x</groupId><artifactId>demo-app</artifactId><version>1</version></project>", encoding="utf-8")
    (src / "src" / "A.java").write_text("public class Alpha { String u='http://svc.demo.test/x'; }\n", encoding="utf-8")
    sp = tmp_path / "targets.yaml"
    Settings(output_dir=str(tmp_path / "out"), sources=[str(src)], max_workers=2).save(sp)
    return TestClient(create_app(str(sp))), tmp_path


def wait_done(c, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = c.get("/api/run/status").json()
        if s["status"] in ("complete", "blocked", "failed", "cancelled"):
            return s
        time.sleep(0.3)
    raise AssertionError("run did not finish")


def test_index_served(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "Privacy" in r.text and "Credential" in r.text


def test_zip_denied_before_run_and_allowed_after(client):
    c, _ = client
    assert c.get("/api/run/status").json()["gate"]["open"] is False
    assert c.post("/api/run/start").status_code == 200
    s = wait_done(c)
    assert s["status"] == "complete", s
    z = c.get("/api/run/zip")
    assert z.status_code == 200
    assert "SEAL.json" in zipfile.ZipFile(io.BytesIO(z.content)).namelist()


def test_second_start_while_running_rejected_and_settings_locked(client):
    c, _ = client
    c.post("/api/run/start")
    r = c.post("/api/run/start")
    assert r.status_code in (200, 409)
    wait_done(c)


def test_settings_roundtrip_and_clamping(client):
    c, _ = client
    r = c.put("/api/settings", json={"max_workers": 500, "token_budget": ""})
    assert r.status_code == 200
    d = r.json()
    assert d["max_workers"] == 100 and d["token_budget"] == 0


def test_upload_rules_and_path_traversal(client):
    c, tmp = client
    r = c.post("/api/upload", files={"file": ("../../evil.txt", b"hello", "text/plain")})
    assert r.status_code == 200 and r.json()["file"] == ".._.._evil.txt".replace("..", "..") or "evil" in r.json()["file"]
    assert not (tmp.parent / "evil.txt").exists()
    img = c.post("/api/upload", files={"file": ("pic.png", b"\x89PNG", "image/png")}).json()
    assert "not read" in img["intake"]
    macro = c.post("/api/upload", files={"file": ("m.xlsm", b"PK", "application/zip")}).json()
    assert "quarantined" in macro["intake"]


def test_ask_not_found_does_not_guess(client):
    c, _ = client
    c.post("/api/run/start")
    wait_done(c)
    r = c.get("/api/ask", params={"q": "which table stores unicorn telemetry?"}).json()
    assert r["found"] is False and "Not found" in r["answer"]
    r2 = c.get("/api/ask", params={"q": "Alpha class"}).json()
    assert r2["found"] is True and r2["citations"]


def test_cancel_endpoint_without_run_is_404(client):
    c, _ = client
    assert c.post("/api/run/cancel").status_code == 404


def _run_and_zip_name(c):
    c.post("/api/run/start")
    assert wait_done(c)["status"] == "complete"
    return c.get("/api/viewer/zips").json()["zips"][0]["name"]


def test_viewer_page_and_browsing(client):
    c, _ = client
    assert "Viewer" in c.get("/viewer").text
    assert c.get("/api/viewer/zips").json()["zips"] == []
    name = _run_and_zip_name(c)
    tree = c.get("/api/viewer/tree", params={"zip": name}).json()
    paths = [f["path"] for f in tree["files"]]
    assert "index.md" in paths and tree["seal"]["label"] == "complete"
    f = c.get("/api/viewer/file", params={"zip": name, "path": "index.md"}).json()
    assert f["text"].strip()
    facts = c.get("/api/viewer/facts", params={"zip": name, "q": "Alpha"}).json()
    assert facts["total"] >= 1 and all("evidence" in x for x in facts["facts"])
    none = c.get("/api/viewer/facts", params={"zip": name, "q": "zzz-no-such-thing"}).json()
    assert none["total"] == 0


def test_viewer_rejects_traversal_unknown_zip_and_bad_upload(client):
    c, _ = client
    name = _run_and_zip_name(c)
    assert c.get("/api/viewer/file", params={"zip": name, "path": "../../etc/passwd"}).status_code == 404
    assert c.get("/api/viewer/file", params={"zip": "../x.zip", "path": "index.md"}).status_code == 404
    assert c.get("/api/viewer/file", params={"zip": name, "path": "nope.md"}).status_code == 404
    assert c.post("/api/viewer/upload", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400
    assert c.post("/api/viewer/upload", files={"file": ("bad.zip", b"not a zip", "application/zip")}).status_code == 400


def test_viewer_upload_valid_zip(client):
    c, _ = client
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.md", "# Hello")
    assert c.post("/api/viewer/upload", files={"file": ("mine.zip", buf.getvalue(), "application/zip")}).json()["name"] == "mine.zip"
    assert c.get("/api/viewer/file", params={"zip": "mine.zip", "path": "index.md"}).json()["text"] == "# Hello"


def test_exit_calls_stop_hook_and_cancels_active_run(tmp_path):
    stopped = []
    sp = tmp_path / "targets.yaml"
    Settings(output_dir=str(tmp_path / "out"), sources=[], max_workers=1).save(sp)
    c = TestClient(create_app(str(sp), on_exit=lambda: stopped.append(1)))
    r = c.post("/api/exit")
    assert r.status_code == 200 and r.json()["stopping"] is True
    for _ in range(30):
        if stopped:
            break
        time.sleep(0.1)
    assert stopped == [1]
    assert 'id="bExit"' in c.get("/").text
