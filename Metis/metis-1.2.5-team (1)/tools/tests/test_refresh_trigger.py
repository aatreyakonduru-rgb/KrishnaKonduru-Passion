import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import build_plan  # noqa: E402
import refresh_trigger as R  # noqa: E402
import tasks  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.com"] + list(args),
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


SECRET = "shared-secret-for-tests"


class Refresh(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        self.repo = os.path.join(self.d, "src", "api")
        write(os.path.join(self.repo, "A.java"), "line one\nclass Orders\nline three\n")
        write(os.path.join(self.repo, "B.java"), "other\n")
        write(os.path.join(self.repo, "C.java"), "unrelated\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "first")
        self.base = git(self.repo, "rev-parse", "HEAD")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(
            {"owners": {"kb_owner": "Ana Lead"}, "sources": {"workspace_root": os.path.join(self.d, "src"), "repos": {"api": "api"}},
             "bitbucket": {"source_repo": "api"}}))
        write(os.path.join(self.kb, "db", "ORDERS.md"), '# ORDERS\n\nHolds orders. [E: api/A.java:2 "class Orders"]\n')
        write(os.path.join(self.kb, "db", "OTHER.md"), '# OTHER\n\nOther. [E: api/B.java:1 "other"]\n')
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": [], "edges": [
            {"from": "a", "rel": "reads", "to": "b", "source": '[E: api/A.java:2 "class Orders"]'}]}))
        build_plan.record(self.kb)
        write(os.path.join(self.repo, "A.java"), "line one\nclass Orders changed\nline three\n")
        git(self.repo, "commit", "-q", "-am", "edit A")
        self.new = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        rmtree(self.d)

    def server_payload(self, old=None, new=None, branch="refs/heads/main", typ="UPDATE"):
        return {"eventKey": "repo:refs_changed", "repository": {"slug": "api", "project": {"key": "P"}},
                "changes": [{"ref": {"id": branch, "displayId": branch.split("/")[-1], "type": "BRANCH"}, "type": typ,
                             "fromHash": old or self.base, "toHash": new or self.new}]}

    def cloud_payload(self, old=None, new=None):
        return {"repository": {"full_name": "ws/api"}, "push": {"changes": [
            {"new": {"type": "branch", "name": "main", "target": {"hash": new or self.new}},
             "old": {"type": "branch", "name": "main", "target": {"hash": old or self.base}}}]}}

    # ---- sources of the change list
    def test_files_make_a_plan_and_write_it(self):
        plan = R.run_plan(self.kb, R.split_files(self.kb, ["api/A.java"]), {"kind": "files", "repo": None, "from": None, "to": None})
        self.assertEqual([p["page"] for p in plan["pages"]], ["db/ORDERS.md"])  # the link graph is derived and left out
        self.assertIn("derived file", " ".join(plan["notes"]))
        self.assertEqual(plan["pages"][0]["reasons"], ["api/A.java changed"])
        saved = R.load_plan(self.kb)
        self.assertEqual(saved["id"], plan["id"])
        self.assertTrue(os.path.isfile(os.path.join(self.kb, ".metis", "refresh_plan.json")))

    def test_plain_paths_need_repo(self):
        with self.assertRaises(R.RefreshError):
            R.split_files(self.kb, ["A.java"])
        self.assertEqual(R.split_files(self.kb, ["A.java"], "api"), {"api": {"A.java"}})

    def test_git_range(self):
        paths, note = R.git_changed(self.kb, "api", self.base, self.new)
        self.assertEqual((paths, note), ({"A.java"}, ""))
        paths, note = R.git_changed(self.kb, "api", None, self.new)  # old commit from the last build record
        self.assertEqual(paths, {"A.java"})
        paths, note = R.git_changed(self.kb, "api", "0" * 40, self.new)
        self.assertIsNone(paths)
        self.assertIn("cannot be compared", note)
        paths, note = R.git_changed(self.kb, "nope", self.base, self.new)
        self.assertIsNone(paths)
        with self.assertRaises(R.RefreshError):
            R.git_changed(self.kb, "api", "--output=/tmp/x", self.new)

    def test_cannot_compare_makes_every_citing_page_stale(self):
        plan = R.run_plan(self.kb, {"api": None}, {"kind": "git"}, ["x"])
        self.assertEqual({p["page"] for p in plan["pages"]}, {"db/ORDERS.md", "db/OTHER.md"})
        self.assertEqual(plan["changed"]["api"], "cannot compare")

    def test_server_payload(self):
        changes, trig, notes = R.from_payload(self.kb, self.server_payload())
        self.assertEqual(changes, {"api": {"A.java"}})
        self.assertEqual((trig["kind"], trig["repo"], trig["branches"]), ("payload", "api", ["main"]))
        self.assertEqual(R.from_payload(self.kb, self.server_payload(branch="refs/heads/dev"), ("main",))[0], {})

    def test_cloud_payload_and_new_branch_uses_recorded_commit(self):
        changes, trig, _ = R.from_payload(self.kb, self.cloud_payload())
        self.assertEqual(changes, {"api": {"A.java"}})
        p = self.cloud_payload()
        p["push"]["changes"][0]["old"] = None
        self.assertEqual(R.from_payload(self.kb, p)[0], {"api": {"A.java"}})  # recorded base commit

    def test_payload_rules(self):
        for bad in ({}, [], {"changes": "x"}, {"repository": {"slug": "api"}, "unknown": 1}):
            with self.assertRaises(R.RefreshError):
                R.parse_payload(bad)
        p = self.server_payload(typ="DELETE")
        self.assertEqual(R.parse_payload(p)[1], [])
        p = self.server_payload()
        p["changes"][0]["toHash"] = "abc; rm -rf /"
        with self.assertRaises(R.RefreshError):
            R.parse_payload(p)

    def test_env_mode(self):
        c, trig, _ = R.from_env(self.kb, {"METIS_CHANGED_FILES": "api/A.java,api/Z.java", })
        self.assertEqual(c, {"api": {"A.java", "Z.java"}})
        c, trig, _ = R.from_env(self.kb, {"METIS_REPO": "api", "METIS_BEFORE": self.base, "BITBUCKET_COMMIT": self.new})
        self.assertEqual(c, {"api": {"A.java"}})
        with self.assertRaises(R.RefreshError):
            R.from_env(self.kb, {})
        with self.assertRaises(R.RefreshError):
            R.from_env(self.kb, {"METIS_CHANGED_FILES": "A.java"})

    def test_since_build(self):
        plan = R.since_build(self.kb)
        self.assertEqual([p["page"] for p in plan["pages"]], ["db/ORDERS.md"])

    # ---- the task
    def test_task_uses_ui_tasks_format_and_is_not_duplicated(self):
        plan = R.run_plan(self.kb, {"api": {"A.java"}}, {"kind": "files"}, task=True, by="Ana Lead")
        self.assertEqual(plan["task"], "T-0001")
        t = tasks.get(self.kb, "T-0001")
        self.assertEqual((t["kind"], t["status"], t["created_by"], t["ref"]), ("build-stage", "queued", "Ana Lead", plan["id"]))
        self.assertIn("db/ORDERS.md", t["instructions"])
        self.assertNotIn("db/OTHER.md", t["instructions"])
        self.assertIn("kb_gate.py propose", t["instructions"])
        self.assertIn("Never write into the KB folder", t["instructions"])
        self.assertTrue(os.path.isdir(os.path.join(self.kb, "_REGEN")))
        again = R.run_plan(self.kb, {"api": {"A.java"}}, {"kind": "files"}, task=True, by="Ana Lead")
        self.assertEqual(again["task"], "T-0001")
        self.assertEqual(len(tasks.all_tasks(self.kb)), 1)
        self.assertIn("already queued", again["status"])
        claimed = tasks.claim(self.kb, "Devin")  # the normal queue accepts it
        self.assertEqual(claimed["id"], "T-0001")

    def test_no_task_when_nothing_is_stale(self):
        plan = R.run_plan(self.kb, {"api": {"C.java"}}, {"kind": "files"}, task=True)
        self.assertEqual(plan["pages"], [])
        self.assertIsNone(plan["task"])
        self.assertEqual(tasks.all_tasks(self.kb), [])
        self.assertEqual(plan["status"], "nothing is stale")

    def test_nothing_is_written_into_the_kb_pages(self):
        before = open(os.path.join(self.kb, "db", "ORDERS.md"), encoding="utf-8").read()
        R.run_plan(self.kb, {"api": {"A.java"}}, {"kind": "files"}, task=True)
        self.assertEqual(open(os.path.join(self.kb, "db", "ORDERS.md"), encoding="utf-8").read(), before)

    # ---- the webhook: signature, plan, task
    def post(self, body, secret=SECRET, headers=None):
        raw = json.dumps(body).encode("utf-8") if not isinstance(body, bytes) else body
        h = {"Content-Type": "application/json", "X-Event-Key": "repo:refs_changed"}
        if secret is not None:
            h["X-Hub-Signature"] = R.sign(secret, raw)
        h.update(headers or {})
        req = urllib.request.Request(self.url, data=raw, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def start(self, **kw):
        srv = R.make_server(self.kb, SECRET, "127.0.0.1", 0, **kw)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), t.join(5)))
        self.url = "http://127.0.0.1:%d/webhook" % srv.server_address[1]
        return srv

    def test_listener_binds_to_loopback_and_needs_a_secret(self):
        srv = self.start()
        self.assertEqual(srv.server_address[0], "127.0.0.1")
        with self.assertRaises(R.RefreshError):
            R.make_server(self.kb, None)
        with self.assertRaises(R.RefreshError):
            R.make_server(self.kb, "")

    def test_unsigned_and_wrongly_signed_requests_are_rejected(self):
        self.start()
        self.assertEqual(self.post(self.server_payload(), secret=None)[0], 401)
        self.assertEqual(self.post(self.server_payload(), secret="wrong")[0], 401)
        self.assertEqual(self.post(self.server_payload(), headers={"X-Hub-Signature": "sha256="})[0], 401)
        self.assertFalse(os.path.exists(os.path.join(self.kb, R.PLAN)))
        code, _ = self.post(b"not json at all")
        self.assertEqual(code, 400)

    def test_signed_push_writes_the_plan_only(self):
        self.start()
        code, reply = self.post(self.server_payload())
        self.assertEqual(code, 202)
        self.assertEqual((reply["pages"], reply["task"]), (1, None))
        self.assertEqual([p["page"] for p in R.load_plan(self.kb)["pages"]], ["db/ORDERS.md"])
        self.assertEqual(tasks.all_tasks(self.kb), [])
        code, reply = self.post(self.cloud_payload(), headers={"X-Event-Key": "repo:push"})
        self.assertEqual(code, 202)

    def test_signed_push_with_task_and_branch_filter(self):
        self.start(branches=("main",), task=True, by="webhook")
        self.assertEqual(self.post(self.server_payload(branch="refs/heads/feature/x"))[0], 200)  # ignored branch
        self.assertEqual(tasks.all_tasks(self.kb), [])
        code, reply = self.post(self.server_payload())
        self.assertEqual((code, reply["task"]), (202, "T-0001"))
        self.assertEqual(tasks.get(self.kb, "T-0001")["created_by"], "webhook")

    def test_other_events_and_other_paths_are_ignored(self):
        self.start()
        code, reply = self.post({"x": 1}, headers={"X-Event-Key": "pullrequest:created"})
        self.assertEqual(code, 200)
        self.assertIn("ignored", reply)
        req = urllib.request.Request(self.url.replace("/webhook", "/other"), data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(e.exception.code, 404)

    # ---- schedule
    def test_schedule_prints_and_installs_nothing(self):
        s = R.schedule_lines(self.kb, "daily", "02:30")
        self.assertTrue(s["cron"].startswith("30 2 * * * python3 "))
        self.assertIn("--since-build --task", s["cron"])
        self.assertIn("schtasks /Create /SC DAILY /ST 02:30", s["windows"])
        self.assertIn("Needs your Devin to verify", s["devin"])
        self.assertTrue(R.schedule_lines(self.kb, "weekly", "06:00", "fri")["cron"].startswith("0 6 * * 5 "))
        self.assertTrue(R.schedule_lines(self.kb, "hourly", "00:15")["cron"].startswith("15 * * * * "))
        for bad in (("daily", "25:00"), ("monthly", "02:00"), ("weekly", "02:00", "xyz")):
            with self.assertRaises(R.RefreshError):
                R.schedule_lines(self.kb, *bad)

    # ---- cli
    def test_cli(self):
        self.assertEqual(R.main(["plan", self.kb, "--files", "api/A.java"]), 0)
        self.assertEqual(R.main(["show", self.kb]), 0)
        self.assertEqual(R.main(["plan", self.kb, "--git", "api", self.base, self.new, "--task", "--by", "KK"]), 0)
        self.assertEqual(tasks.get(self.kb, "T-0001")["created_by"], "KK")
        self.assertEqual(R.main(["plan", self.kb, "--files", "A.java"]), 2)
        self.assertEqual(R.main(["schedule", self.kb, "--every", "weekly", "--day", "mon"]), 0)
        self.assertEqual(R.main(["plan", self.kb, "--since-build", "--no-write"]), 0)


if __name__ == "__main__":
    unittest.main()
