import base64
import http.cookiejar
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request

import yaml

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UI_DIR = os.path.join(TOOLS_DIR, "ui")
for _p in (TOOLS_DIR, UI_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import answers  # noqa: E402
import builds  # noqa: E402
import server  # noqa: E402
import setup_ops  # noqa: E402
import tasks  # noqa: E402
import ui_common as C  # noqa: E402
import views  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class TestUiCommonAndSetup(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        os.makedirs(self.kb, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_render_md_escaping(self):
        # Plain text and html escaping
        html_out = C.render_md('<script>alert("xss")</script>')
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;", html_out)

        # Tags and code formatting
        md = "# Title\n\n- Fact line `code` **bold** [E: kb:db/x.md \"quote\"]\n"
        out = C.render_md(md)
        self.assertIn("<h2>Title</h2>", out)
        self.assertIn("<code>code</code>", out)
        self.assertIn("<b>bold</b>", out)
        self.assertIn('<span class="tag" title="source">[E: kb:db/x.md &quot;quote&quot;]</span>', out)

    def test_setup_ops_problems_and_save(self):
        # Missing required fields
        bad = setup_ops.problems_in({})
        self.assertTrue(any("product name" in b for b in bad))
        self.assertTrue(any("KB owner" in b for b in bad))
        self.assertTrue(any("source repos" in b for b in bad))

        # Invalid repo name
        bad_repo = setup_ops.problems_in({
            "name": "Demo", "kb_owner": "Ana", "workspace": "/tmp",
            "repos": "bad name|/tmp/repo"
        })
        self.assertTrue(any("must be letters, digits" in b for b in bad_repo))

        # Module referencing unlisted repo
        bad_mod = setup_ops.problems_in({
            "name": "Demo", "kb_owner": "Ana", "workspace": "/tmp",
            "repos": "repo1|repo1",
            "app_modules": "mod1|unlisted/path|java"
        })
        self.assertTrue(any("not a listed repo" in b for b in bad_mod))

        # Valid profile saves
        values = {
            "name": "Demo Shop", "short": "DEMO", "kb_owner": "Ana Lead", "workspace": "/tmp/ws",
            "repos": "shop|shop\npetclinic|petclinic",
            "app_modules": "web|petclinic/src|java",
            "etl_modules": "dbt|shop/models|dbt",
            "roles": {"dev lead": "Raj Dev", "data lead": "Dee Data"},
            "certifiers": "Ana Lead, Raj Dev"
        }
        prof = setup_ops.save_profile(self.kb, values)
        self.assertEqual(prof["product"]["name"], "Demo Shop")
        self.assertEqual(prof["owners"]["kb_owner"], "Ana Lead")
        self.assertEqual(len(prof["sources"]["repos"]), 2)
        self.assertTrue(os.path.isfile(C.profile_path(self.kb)))

    def test_builds_missing(self):
        # Empty KB -> missing profile
        miss = builds.missing(self.kb)
        self.assertTrue(any("profile is not complete" in m for m in miss))

        # Save profile -> missing stack approval
        setup_ops.save_profile(self.kb, {
            "name": "Demo Shop", "kb_owner": "Ana Lead", "workspace": "/tmp/ws",
            "repos": "shop|shop"
        })
        miss2 = builds.missing(self.kb)
        self.assertTrue(any("tech stack is not approved" in m for m in miss2))


class TestTasksLifecycle(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        os.makedirs(self.kb, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_tasks_lifecycle(self):
        # Create
        t = tasks.create(self.kb, "build-stage", "Build stage", "Run stage", "User A", ref="R-001")
        tid = t["id"]
        self.assertEqual(t["status"], "queued")
        self.assertEqual(t["kind"], "build-stage")

        # List
        all_t = tasks.all_tasks(self.kb)
        self.assertEqual(len(all_t), 1)
        self.assertEqual(all_t[0]["id"], tid)

        # Claim
        c = tasks.claim(self.kb, "Worker 1", tid=tid)
        self.assertEqual(c["status"], "running")
        self.assertEqual(c["claimed_by"], "Worker 1")

        # Requeue
        rq = tasks.requeue(self.kb, tid)
        self.assertEqual(rq["status"], "queued")
        self.assertIsNone(rq["claimed_by"])

        # Claim again and fail
        tasks.claim(self.kb, "Worker 2", tid=tid)
        f = tasks.fail(self.kb, tid, "Worker 2", note="Cannot resolve")
        self.assertEqual(f["status"], "failed")
        self.assertEqual(f["note"], "Cannot resolve")

        # Requeue and complete
        tasks.requeue(self.kb, tid)
        tasks.claim(self.kb, "Worker 3", tid=tid)
        done = tasks.complete(self.kb, tid, "Worker 3", note="Resolved")
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["note"], "Resolved")

        # Cancel
        t2 = tasks.create(self.kb, "build-stage", "Build stage 2", "Run stage 2", "User A")
        canc = tasks.cancel(self.kb, t2["id"], "User A")
        self.assertEqual(canc["status"], "cancelled")


class TestAnswersAndRatings(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\n")
        write(os.path.join(self.kb, "db", "PETS.md"), '# PETS\n\nThe pets table has a foreign key to owners. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_answers_compose_and_check(self):
        # Compose answer from search
        ans_md, num_facts, num_unknown = answers.compose(self.kb, "Which table does pets reference?")
        self.assertTrue(num_facts >= 1)
        self.assertIn("pets", ans_md.lower())
        self.assertIn("[E: kb:db/PETS.md", ans_md)

        # Check answer with verify_kb
        ans_file = os.path.join(self.d, "ans.md")
        write(ans_file, ans_md)
        res = answers.check(self.kb, ans_file)
        self.assertEqual(len(res.get("problems", [])), 0)
        self.assertTrue(res.get("lines", 0) >= 1)

    def test_answers_rating_rules(self):
        # Create local ask
        a = answers.ask(self.kb, "Which table does pets reference?", "Pat Lee", mode="local")
        aid = a["id"]
        self.assertEqual(a["status"], "answered")

        # Dislike without reason -> raises UiError
        with self.assertRaises(C.UiError):
            answers.rate(self.kb, aid, "Pat Lee", "down", why="")

        # Dislike with both correct and redirect -> raises UiError
        with self.assertRaises(C.UiError):
            answers.rate(self.kb, aid, "Pat Lee", "down", why="wrong", correct="Correct answer", redirect="Look at models")

        # Dislike with direction -> re-asks
        fb_item, a_new = answers.rate(self.kb, aid, "Pat Lee", "down", why="wrong table", redirect="look at PETS.md")
        self.assertIsNotNone(a_new)
        self.assertTrue(fb_item["id"].startswith("F-"))

        # Second rating on same ask -> raises UiError
        with self.assertRaises(C.UiError):
            answers.rate(self.kb, aid, "Pat Lee", "up")

        # Like on the new ask -> records feedback
        fb_item2, again2 = answers.rate(self.kb, a_new["id"], "Pat Lee", "up")
        self.assertTrue(fb_item2["id"].startswith("F-"))
        self.assertIsNone(again2)

    def test_confidence_is_computed_from_the_answer(self):
        q = "Which table does pets reference?"
        direct = answers.confidence(q, '# A\n\n- pets references owners [E: kb:x.md "pets references owners"]\n')
        self.assertEqual((direct["score"], direct["band"]), (100, "High"))
        joined = answers.confidence("does pets and vets reference owners",
                                    '# A\n\n- pets references owners [E: kb:x.md "a"]\n- vets reference owners [E: kb:y.md "b"]\n')
        inferred = answers.confidence(q, '# A\n\n- Inferred: pets reference owners, so each pet has one owner [E: kb:x.md "pets references owners"]\n')
        missing = answers.confidence(q, '# A\n\n- pets references owners [E: kb:x.md "pets references owners"]\n\n## Not in the KB\n\n- Which column?\n')
        none = answers.confidence(q, "# A\n\n## Not in the KB\n\n- The KB has no line about: x\n")
        self.assertTrue(joined["score"] < 100 and joined["band"] == "High")
        self.assertEqual(inferred["band"], "Medium")  # an inference is never High
        self.assertEqual(missing["band"], "Medium")
        self.assertEqual((none["score"], none["band"]), (0, "None"))
        for c in (joined, inferred, missing, none):
            self.assertTrue(c["reasons"])
        # a real local answer carries it: the KB line uses the question's own words, so it is a direct answer
        a = answers.ask(self.kb, "Which table has a foreign key to owners?", "Pat Lee", mode="local")
        self.assertEqual(a["confidence"]["score"], 100)
        self.assertNotIn("guidance", a)
        # same line, but the question says "reference" where the KB says "foreign key": related, not direct, and it says why
        b = answers.ask(self.kb, q, "Pat Lee", mode="local")
        self.assertEqual(b["confidence"]["band"], "Medium")
        self.assertTrue(any("reference" in x for x in b["confidence"]["reasons"]))

    def test_glossary_synonyms_widen_the_search(self):
        import glossary
        self.assertEqual(answers.compose(self.kb, "which clients are registered?")[1], 0)
        glossary.add(self.kb, "owner", ["client"], "A person who owns pets.", ["db/PETS.md"], "Ana Lead")
        self.assertGreaterEqual(answers.compose(self.kb, "which clients are registered?")[1], 1)  # "client" now finds the owner lines
        # a broken glossary never stops an answer
        with open(glossary.path(self.kb), "w", encoding="utf-8") as fh:
            fh.write(":\n  - [unbalanced")
        self.assertIsInstance(answers.compose(self.kb, "which clients are registered?")[1], int)


    def test_miss_gives_guidance_and_clarify_asks_again(self):
        a = answers.ask(self.kb, "how many ownrs do we have in the pets table ?", "Pat Lee", mode="local")
        g = a["guidance"]
        self.assertIn("ownrs", g["unknown"])
        self.assertTrue(any(t["word"] == "ownrs" and any(o["word"] == "owners" for o in t["options"]) for t in g["typos"]))
        self.assertTrue(g["nearest"] and g["tips"])
        self.assertNotEqual(a["confidence"]["band"], "High")  # "pets table" matched a line, so it is partial, and the help shows
        # picking the spelling the KB uses asks that question, linked to the first
        fixed = [o for t in g["typos"] for o in t["options"] if o["word"] == "owners"][0]["question"]
        b = answers.reword(self.kb, a["id"], "Pat Lee", fixed)
        self.assertEqual(b["follows"], a["id"])
        self.assertTrue(b["checked"]["lines"] >= 1)
        # saying more asks again with the words as a direction; an empty reply is refused
        c = answers.clarify(self.kb, a["id"], "Pat Lee", "the foreign key from pets to owners")
        self.assertEqual(c["direction"], "the foreign key from pets to owners")
        with self.assertRaises(C.UiError):
            answers.clarify(self.kb, a["id"], "Pat Lee", "  ")

    def test_devin_asks_the_person_and_reads_the_reply(self):
        a = answers.ask(self.kb, "which menus exist", "Pat Lee", mode="devin")
        tid = a["task"]
        with self.assertRaises(C.UiError):
            tasks.ask_user(self.kb, tid, "Devin", ["Which layer?"])  # not claimed yet
        tasks.claim(self.kb, "Devin", tid)
        with self.assertRaises(C.UiError):
            tasks.ask_user(self.kb, tid, "Devin", ["a", "b", "c"])  # at most two questions
        tasks.ask_user(self.kb, tid, "Devin", ["Do you mean screens or navigation links?"])
        self.assertEqual(tasks.get(self.kb, tid)["status"], "waiting-user")
        with self.assertRaises(C.UiError):
            tasks.ask_user(self.kb, tid, "Devin", ["again?"])  # must wait for the reply first
        with self.assertRaises(C.UiError):
            tasks.reply(self.kb, tid, "Pat Lee", [""])  # an empty reply is refused
        tasks.reply(self.kb, tid, "Pat Lee", ["screens"])
        self.assertEqual(tasks.get(self.kb, tid)["status"], "running")
        self.assertEqual(tasks.wait(self.kb, tid, timeout=1, poll=0.1)["replies"], ["screens"])
        tasks.ask_user(self.kb, tid, "Devin", ["Which module?"])
        tasks.reply(self.kb, tid, "Pat Lee", ["petclinic"])
        with self.assertRaises(C.UiError):
            tasks.ask_user(self.kb, tid, "Devin", ["a third time?"])  # two rounds at most
        self.assertIn("screens", tasks.reply_text(tasks.get(self.kb, tid)))



class TestServerAndSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.kb = os.path.join(cls.d, "kb")
        write(os.path.join(cls.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({
            "product": {"name": "Demo Shop"},
            "owners": {"kb_owner": "Ana Lead", "roles": {"dev lead": "Raj Dev"}}
        }))
        write(os.path.join(cls.kb, "db", "TEST.md"), "# Test page [E: kb:db/TEST.md]\n")
        write(os.path.join(cls.kb, "VISUALIZATION", "index.html"), "<html><body>Visuals</body></html>")
        write(os.path.join(cls.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))

        # Start unauthenticated test server on ephemeral port (port 0)
        cls.srv = server.serve(cls.kb, host="127.0.0.1", port=0, password=None)
        cls.port = cls.srv.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

        # Start password-protected test server on separate ephemeral port
        cls.pwd = "secret123"
        cls.srv_pwd = server.serve(cls.kb, host="127.0.0.1", port=0, password=cls.pwd)
        cls.port_pwd = cls.srv_pwd.server_address[1]
        cls.base_url_pwd = f"http://127.0.0.1:{cls.port_pwd}"
        cls.thread_pwd = threading.Thread(target=cls.srv_pwd.serve_forever, daemon=True)
        cls.thread_pwd.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.srv_pwd.shutdown()
        cls.srv_pwd.server_close()
        shutil.rmtree(cls.d, ignore_errors=True)

    def make_opener(self):
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar

    def get_token(self, op):
        res = op.open(self.base_url + "/").read().decode("utf-8")
        m = re.search(r'name="_t" value="([^"]+)"', res)
        return m.group(1) if m else ""

    def test_csrf_refusal(self):
        op, _ = self.make_opener()
        # POST without CSRF token -> 403 Forbidden
        data = urllib.parse.urlencode({"name": "Test User"}).encode()
        req = urllib.request.Request(self.base_url + "/whoami", data=data)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            op.open(req)
        self.assertEqual(ctx.exception.code, 403)

    def test_user_name_required(self):
        op, _ = self.make_opener()
        tok = self.get_token(op)
        # Action without user cookie set -> 400 Bad Request
        data = urllib.parse.urlencode({"_t": tok, "question": "What is x?", "mode": "local"}).encode()
        req = urllib.request.Request(self.base_url + "/ask/new", data=data)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            op.open(req)
        self.assertEqual(ctx.exception.code, 400)
        body = ctx.exception.read().decode("utf-8")
        self.assertIn("Say who you are first", body)

    def test_password_auth(self):
        op, _ = self.make_opener()

        # Request to password-protected server without auth header -> 401 Unauthorized
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            op.open(self.base_url_pwd + "/")
        self.assertEqual(ctx.exception.code, 401)

        # Request with valid basic auth header -> 200 OK
        auth = base64.b64encode(f"user:{self.pwd}".encode()).decode()
        req = urllib.request.Request(self.base_url_pwd + "/", headers={"Authorization": f"Basic {auth}"})
        r = op.open(req)
        self.assertEqual(r.status, 200)

    def test_path_traversal_prevention(self):
        op, _ = self.make_opener()

        # Path traversal on /files?page=../../secret.txt -> 400 with "not a KB file"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            op.open(self.base_url + "/files?page=../../secret.txt")
        self.assertEqual(ctx.exception.code, 400)
        body = ctx.exception.read().decode("utf-8")
        self.assertIn("not a KB file", body)

        # Path traversal on /viz/../../secret.txt -> 404
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            op.open(self.base_url + "/viz/../../secret.txt")
        self.assertEqual(ctx.exception.code, 404)

        # Valid /viz/index.html -> 200 with Content-Security-Policy sandbox
        r = op.open(self.base_url + "/viz/index.html")
        self.assertEqual(r.status, 200)
        csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("sandbox allow-scripts", csp)


if __name__ == "__main__":
    unittest.main()
