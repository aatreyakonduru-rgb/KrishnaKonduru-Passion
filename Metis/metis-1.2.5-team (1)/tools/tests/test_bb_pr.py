import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bb_pr  # noqa: E402

TOKEN = "tok-abc-123-not-real"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


class FakeBitbucket(object):
    """Both REST routes in one fake. `files` are the PR's changed paths. Every request is recorded."""
    def __init__(self, files, flavor):
        self.files, self.flavor, self.comments, self.reqs, self.next_id = files, flavor, [], [], 100
        self.reject_token = False
        outer = self

        class H(BaseHTTPRequestHandler):
            def reply(self, code, obj):
                data = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

            def handle_any(self, method):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                body = self.body() if method in ("POST", "PUT") else None
                outer.reqs.append({"method": method, "path": u.path, "query": u.query, "auth": self.headers.get("Authorization"),
                                   "body": body})
                if outer.reject_token or self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self.reply(401, {"errors": ["no"]})
                p = u.path
                if outer.flavor == "server":
                    base = "/rest/api/1.0/projects/PROJ/repos/payments/pull-requests/7"
                    if method == "GET" and p == base + "/changes":
                        start = int((q.get("start") or ["0"])[0])
                        half = max(1, len(outer.files) // 2)
                        part = outer.files[:half] if start == 0 else outer.files[half:]
                        return self.reply(200, {"values": [{"path": {"toString": f}} for f in part], "isLastPage": start != 0 or len(outer.files) < 2,
                                                "nextPageStart": half})
                    if method == "GET" and p == base + "/activities":
                        return self.reply(200, {"values": [{"action": "COMMENTED", "comment": c} for c in outer.comments] +
                                                           [{"action": "APPROVED"}], "isLastPage": True})
                    if method == "POST" and p == base + "/comments":
                        outer.next_id += 1
                        outer.comments.append({"id": outer.next_id, "text": body["text"], "version": 0})
                        return self.reply(201, {"id": outer.next_id})
                    if method == "PUT" and p.startswith(base + "/comments/"):
                        c = next((c for c in outer.comments if str(c["id"]) == p.rsplit("/", 1)[1]), None)
                        if not c or body.get("version") != c["version"]:
                            return self.reply(409, {"errors": ["version"]})
                        c.update(text=body["text"], version=c["version"] + 1)
                        return self.reply(200, {"id": c["id"]})
                else:
                    base = "/2.0/repositories/ws/payments/pullrequests/7"
                    if method == "GET" and p == base + "/diffstat":
                        page = int((q.get("page") or ["1"])[0])
                        half = max(1, len(outer.files) // 2)
                        part = outer.files[:half] if page == 1 else outer.files[half:]
                        out = {"values": [{"new": {"path": f}, "old": {"path": f}} for f in part]}
                        if page == 1 and len(outer.files) > 1:
                            out["next"] = "http://%s%s?page=2" % (self.headers["Host"], p)
                        return self.reply(200, out)
                    if method == "GET" and p == base + "/comments":
                        return self.reply(200, {"values": [{"id": c["id"], "content": {"raw": c["text"]}} for c in outer.comments]})
                    if method == "POST" and p == base + "/comments":
                        outer.next_id += 1
                        outer.comments.append({"id": outer.next_id, "text": body["content"]["raw"]})
                        return self.reply(201, {"id": outer.next_id})
                    if method == "PUT" and p.startswith(base + "/comments/"):
                        c = next((c for c in outer.comments if str(c["id"]) == p.rsplit("/", 1)[1]), None)
                        c["text"] = body["content"]["raw"]
                        return self.reply(200, {"id": c["id"]})
                self.reply(404, {})

            def do_GET(self):
                self.handle_any("GET")

            def do_POST(self):
                self.handle_any("POST")

            def do_PUT(self):
                self.handle_any("PUT")

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def writes(self):
        return [r for r in self.reqs if r["method"] != "GET"]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.t.join(5)


def edge(a, rel, b, line, origin="parsed", f="Orders.java"):
    return {"from": a, "rel": rel, "to": b, "source": '[E: api/src/%s:%d "x"]' % (f, line), "defined_in": "m/x.links.yaml", "origin": origin}


class BbPr(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        nodes = [{"id": "endpoint:GET /orders", "type": "endpoint", "name": "GET /orders"},
                 {"id": "table:APP.ORDERS", "type": "table", "name": "APP.ORDERS"},
                 {"id": "screen:Orders", "type": "screen", "name": "Orders"},
                 {"id": "job:LOAD", "type": "job", "name": "LOAD"}]
        edges = [edge("endpoint:GET /orders", "reads", "table:APP.ORDERS", 1),
                 edge("screen:Orders", "calls", "endpoint:GET /orders", 2, "ai-proposed", "Screen.java"),
                 {"from": "job:LOAD", "rel": "writes", "to": "table:APP.ORDERS", "source": '[E: etl/load.sql:3 "x"]', "origin": "parsed"}]
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": nodes, "edges": edges}))
        write(os.path.join(self.kb, "db", "ORDERS.md"), '# ORDERS\n\nHolds orders. [E: api/src/Orders.java:1 "x"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0007", "status": "open", "priority": "P1", "type": "data", "question": "PRIVATE QUESTION WORDS", "blocks": ["db/ORDERS.md"]}]}))
        self.profile("server", "http://127.0.0.1:1")

    def tearDown(self):
        rmtree(self.d)

    def profile(self, flavor, url, **extra):
        bb = {"flavor": flavor, "base_url": url, "repo": "payments", "source_repo": "api", "token_env": "T_BB"}
        bb.update({"server": {"project": "PROJ"}, "cloud": {"workspace": "ws"}}[flavor])
        bb.update(extra)
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(
            {"product": {"name": "Pets"}, "owners": {"kb_owner": "Ana"}, "bitbucket": bb, "notify": {"base_url": "http://metis.local:8765"}}))

    ENV = {"T_BB": TOKEN}

    # ---- mapping and comment content
    def test_changed_file_maps_to_objects_and_pages(self):
        cfg = bb_pr.config(self.kb, self.ENV)
        a = bb_pr.analyse(self.kb, ["src/Orders.java", "README.md"], cfg)
        nodes = {o["node"] for o in a["objects"]}
        self.assertEqual(nodes, {"endpoint:GET /orders", "table:APP.ORDERS"})
        self.assertEqual([p["page"] for p in a["pages"]], ["db/ORDERS.md"])  # derived files such as the link graph are not pages
        self.assertEqual(a["pages"][0]["page"], "db/ORDERS.md")
        self.assertEqual(a["questions"], [{"id": "Q-0007", "priority": "P1", "pages": ["db/ORDERS.md"]}])
        moved = {r["node"]: r["origin"] for r in a["impact"]}
        self.assertEqual(moved["screen:Orders"], "ai-proposed")
        self.assertNotIn("job:LOAD", moved)  # the job writes the table; it is upstream, not moved

    def test_comment_text_origin_signals_questions_pack_and_no_question_text(self):
        r = bb_pr.comment(self.kb, "7", files=["src/Orders.java"], env=self.ENV)
        t = r["text"]
        self.assertTrue(t.startswith(bb_pr.MARKER))
        self.assertIn("ai-proposed", t)
        self.assertIn("parsed", t)
        self.assertIn("quote", t)  # trust signals
        self.assertIn("Q-0007 (P1) blocks db/ORDERS.md", t)
        self.assertNotIn("PRIVATE QUESTION WORDS", t)
        self.assertIn("Context pack for these objects: P-", t)
        self.assertIn("http://metis.local:8765/pack", t)
        self.assertIn("does not approve, merge", t)
        self.assertFalse(r["posted"])
        self.assertTrue(r["dry_run"])

    def test_no_graph_hit_says_so(self):
        r = bb_pr.comment(self.kb, "7", files=["docs/readme.md"], env=self.ENV)
        self.assertIn("No changed file is cited", r["text"])

    def test_size_limit(self):
        nodes = [{"id": "table:T%d" % i, "type": "table", "name": "T%d" % i} for i in range(120)]
        edges = [edge("table:T%d" % i, "reads", "table:T%d" % (i + 1), 1) for i in range(119)]
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": nodes, "edges": edges}))
        import graph_store
        graph_store.build(self.kb)
        big = bb_pr.comment(self.kb, "7", files=["src/Orders.java"], env=self.ENV, max_chars=100000)
        small = bb_pr.comment(self.kb, "7", files=["src/Orders.java"], env=self.ENV, max_chars=2500)
        self.assertGreater(len(big["text"]), 6000)
        self.assertLessEqual(len(small["text"]), 2500)
        self.assertTrue(small["text"].startswith(bb_pr.MARKER))
        self.assertIn("more", small["text"])
        self.assertIn("does not approve, merge", small["text"])

    def test_secret_in_a_line_is_withheld(self):
        write(os.path.join(self.kb, "db", "ORDERS.md"), '# ORDERS\n\nHolds orders. [E: api/src/Orders.java:1 "x"]\n')
        a = bb_pr.analyse(self.kb, ["src/Orders.java"], bb_pr.config(self.kb, self.ENV))
        a["pages"][0]["signals"] = "password = hunter2hunter2"
        c = bb_pr.compose(self.kb, a, "7", bb_pr.config(self.kb, self.ENV))
        self.assertNotIn("hunter2", c["text"])
        self.assertEqual(c["withheld"], ["credential"])

    # ---- the client against the fake: Server / Data Center
    def test_server_dry_run_reads_only(self):
        fake = FakeBitbucket(["src/Orders.java", "src/Other.java", "README.md"], "server")
        try:
            self.profile("server", fake.url)
            r = bb_pr.comment(self.kb, "7", env=self.ENV)
            self.assertEqual(fake.writes(), [])
            self.assertTrue(all(q["method"] == "GET" and q["auth"] == "Bearer " + TOKEN for q in fake.reqs))
            self.assertEqual(r["analysis"]["changed"], ["README.md", "src/Orders.java", "src/Other.java"])  # both pages read
            self.assertIn("would create a new comment", r["action"])
            self.assertFalse(os.path.exists(os.path.join(self.kb, bb_pr.LOG)))
        finally:
            fake.close()

    def test_server_post_creates_then_updates_its_own_comment(self):
        fake = FakeBitbucket(["src/Orders.java"], "server")
        try:
            self.profile("server", fake.url)
            first = bb_pr.comment(self.kb, "7", post=True, env=self.ENV)
            self.assertEqual((first["action"], first["posted"]), ("created", True))
            self.assertEqual(len(fake.comments), 1)
            self.assertIn(bb_pr.MARKER, fake.comments[0]["text"])
            self.assertEqual(fake.writes()[0]["path"], "/rest/api/1.0/projects/PROJ/repos/payments/pull-requests/7/comments")
            fake.comments.append({"id": 5, "text": "someone else's comment", "version": 0})
            second = bb_pr.comment(self.kb, "7", post=True, env=self.ENV)
            self.assertEqual(second["action"], "updated")
            self.assertEqual(len(fake.comments), 2)  # no new comment
            put = fake.writes()[-1]
            self.assertEqual((put["method"], put["path"].rsplit("/", 1)[1]), ("PUT", str(first["comment_id"])))
            self.assertEqual(fake.comments[0]["version"], 1)
            self.assertEqual(fake.comments[1]["text"], "someone else's comment")
            self.assertEqual({w["method"] for w in fake.writes()}, {"POST", "PUT"})
            self.assertTrue(all("comments" in w["path"] for w in fake.writes()))
            with open(os.path.join(self.kb, bb_pr.LOG), encoding="utf-8") as fh:
                log = json.load(fh)
            self.assertEqual([x["action"] for x in log], ["created", "updated"])
        finally:
            fake.close()

    # ---- Cloud
    def test_cloud_post_and_update(self):
        fake = FakeBitbucket(["src/Orders.java", "src/Other.java"], "cloud")
        try:
            self.profile("cloud", fake.url)
            r = bb_pr.comment(self.kb, "7", post=True, env=self.ENV)
            self.assertEqual(r["action"], "created")
            self.assertEqual(fake.writes()[0]["path"], "/2.0/repositories/ws/payments/pullrequests/7/comments")
            self.assertEqual(set(fake.writes()[0]["body"]), {"content"})
            self.assertIn("src/Other.java", r["analysis"]["changed"])  # second diffstat page followed
            r2 = bb_pr.comment(self.kb, "7", post=True, env=self.ENV)
            self.assertEqual(r2["action"], "updated")
            self.assertEqual(len(fake.comments), 1)
        finally:
            fake.close()

    # ---- failures
    def test_token_missing_rejected_and_never_printed(self):
        fake = FakeBitbucket(["src/Orders.java"], "server")
        try:
            self.profile("server", fake.url)
            with self.assertRaises(bb_pr.BbError) as e:
                bb_pr.comment(self.kb, "7", env={})
            self.assertIn("T_BB is not set", str(e.exception))
            with self.assertRaises(bb_pr.BbError) as e:
                bb_pr.comment(self.kb, "7", env={"T_BB": "wrong-token"})
            self.assertIn("HTTP 401", str(e.exception))
            self.assertNotIn("wrong-token", str(e.exception))
            self.assertEqual(fake.writes(), [])
        finally:
            fake.close()

    def test_profile_refuses_a_token_value_and_plain_http_to_a_remote_host(self):
        self.profile("server", "http://bitbucket.example.com", token_env="abcDEF-123.token")
        cfg = bb_pr.config(self.kb, {})
        self.assertTrue(any("never the token itself" in p for p in cfg["problems"]))
        self.assertTrue(any("must be https" in p for p in cfg["problems"]))
        with self.assertRaises(bb_pr.BbError):
            bb_pr.comment(self.kb, "7", files=["a"], post=True, env={"abcDEF-123.token": "x"})

    def test_pr_id_must_be_a_number_and_token_not_sent_elsewhere(self):
        self.profile("server", "http://127.0.0.1:1")
        c = bb_pr.Client(bb_pr.config(self.kb, self.ENV), TOKEN)
        with self.assertRaises(bb_pr.BbError):
            c.pr_url("7/../../x")
        with self.assertRaises(bb_pr.BbError):
            c.call("GET", "http://evil.example.com/x")

    # ---- CI mode and CLI
    def test_ci_mode_reads_pipeline_variables(self):
        fake = FakeBitbucket(["src/Orders.java"], "cloud")
        try:
            write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(
                {"bitbucket": {"token_env": "T_BB", "source_repo": "api", "base_url": fake.url}}))
            env = {"T_BB": TOKEN, "BITBUCKET_PR_ID": "7", "BITBUCKET_WORKSPACE": "ws", "BITBUCKET_REPO_SLUG": "payments"}
            cfg = bb_pr.config(self.kb, env, ci=True)
            self.assertEqual((cfg["flavor"], cfg["workspace"], cfg["repo"], cfg["pr"]), ("cloud", "ws", "payments", "7"))
            r = bb_pr.comment(self.kb, None, post=False, env=env, ci=True)
            self.assertEqual(r["pr"], "7")
            self.assertEqual(fake.writes(), [])
        finally:
            fake.close()

    def test_cli_dry_run(self):
        self.assertEqual(bb_pr.main(["comment", self.kb, "--pr", "7", "--files", "src/Orders.java"]), 0)
        self.assertEqual(bb_pr.main(["comment", self.kb, "--files", "src/Orders.java"]), 2)  # no pr id
        self.assertEqual(bb_pr.main(["check", self.kb]), 0)  # 127.0.0.1 is accepted for http, token_env is a name
        self.profile("server", "http://bitbucket.example.com")
        self.assertEqual(bb_pr.main(["check", self.kb]), 1)


if __name__ == "__main__":
    unittest.main()
