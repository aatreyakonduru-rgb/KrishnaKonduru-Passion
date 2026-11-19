#!/usr/bin/env python3
"""One-click opener for Argus pages: starts Argus if it is down, then sends the tab there.

  GET /open?to=workbench                       Argus home
  GET /open?to=dashboard&user=<id>&role=<id>   rebuild that person's dashboard, then open it
  GET /health                                  200 while this opener is up

Runs on 127.0.0.1 only. Starting Argus needs the same environment as run.sh
(a Devin API key; the Jira token is optional, see run.sh).
"""
import argparse
import html
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_SH = os.path.join(HERE, "run.sh")
START_LOCK = threading.Lock()

PAGE = """<!doctype html><meta charset="utf-8"><title>Opening the %(label)s…</title>
<body style="font:16px system-ui,sans-serif;padding:48px;color:#374151">
<p id="m">%(msg)s</p>
<script>
fetch("/go?%(query)s",{cache:"no-store"}).then(function(r){return r.json();}).then(function(d){
  if(d.url){location.replace(d.url);}else{document.getElementById("m").textContent=d.error||"Could not open the page.";}
}).catch(function(){document.getElementById("m").textContent="Could not reach the opener.";});
</script>"""


def workbench_up(base):
    try:
        with urllib.request.urlopen(base + "/api/config", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def ensure_workbench(args):
    base = "http://127.0.0.1:%d" % args.workbench_port
    if workbench_up(base):
        return base, None
    with START_LOCK:
        if workbench_up(base):
            return base, None
        cmd = ["bash", RUN_SH, "start", str(args.workbench_port)]
        if args.viewer:
            cmd += ["--user", args.viewer]
        env = dict(os.environ)
        env.setdefault("SDLC_DEVIN_TRANSPORT", "api")
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if done.returncode:
            return base, "Could not start Argus: " + (done.stderr or done.stdout).strip()[-300:]
        deadline = time.time() + args.start_timeout
        while time.time() < deadline:
            if workbench_up(base):
                return base, None
            time.sleep(0.5)
    return base, "Argus did not come up within %d seconds." % args.start_timeout


def build_dashboard(base, user, role):
    body = json.dumps({"user": user, "role": role}).encode()
    req = urllib.request.Request(base + "/api/dashboard", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read() or b"{}").get("url", "/dashboard"), None
    except urllib.error.HTTPError as e:
        try:
            return None, json.loads(e.read() or b"{}").get("error", str(e))
        except ValueError:
            return None, str(e)
    except OSError as e:
        return None, "Dashboard build failed: %s" % e


class Handler(BaseHTTPRequestHandler):
    args = None

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        dash = q.get("to") == "dashboard"
        if url.path == "/health":
            return self._send(200, '{"ok": true}', "application/json")
        if url.path == "/open":
            label = "dashboard" if dash else "Argus"
            msg = "Devin is building the dashboard from Jira…" if dash else "Opening Argus…"
            return self._send(200, PAGE % {"label": label, "msg": msg, "query": html.escape(url.query)},
                              "text/html; charset=utf-8")
        if url.path == "/go":
            base, err = ensure_workbench(self.args)
            if err:
                return self._send(200, json.dumps({"error": err}), "application/json")
            path = "/"
            if dash:
                path, err = build_dashboard(base, q.get("user", ""), q.get("role", ""))
                if err:
                    return self._send(200, json.dumps({"error": err}), "application/json")
            return self._send(200, json.dumps({"url": base + path}), "application/json")
        return self._send(404, '{"error": "not found"}', "application/json")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8786)
    ap.add_argument("--workbench-port", type=int, default=int(os.environ.get("SDLC_CONSOLE_PORT", "8787")))
    ap.add_argument("--viewer", default=os.environ.get("SDLC_CONSOLE_JIRA_USER", ""),
                    help="who Argus is started for (as run.sh --user)")
    ap.add_argument("--start-timeout", type=int, default=45)
    Handler.args = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", Handler.args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
