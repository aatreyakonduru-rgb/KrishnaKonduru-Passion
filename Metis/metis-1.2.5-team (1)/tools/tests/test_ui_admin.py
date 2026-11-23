import os
import shutil
import sys
import tempfile
import unittest

import yaml

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UI_DIR = os.path.join(TOOLS_DIR, "ui")
for _p in (TOOLS_DIR, UI_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import answers  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402
import screens_admin as A  # noqa: E402
import tasks  # noqa: E402
import telemetry  # noqa: E402
import ui_common as C  # noqa: E402

PROFILE = {
    "product": {"name": "Demo Shop", "short_name": "DEMO"},
    "repo": {"url": "", "base_branch": "main"},
    "paths": {"kb_root": ".", "db_docs": "db", "module_docs": "modules", "etl_docs": "etl", "context_dir": "context"},
    "sources": {"workspace_root": "/tmp/ws", "repos": {"shop": "shop"}, "repo_urls": {},
                "jira": {"enabled": True, "base_url": "https://jira.example.com", "projects": ["SHOP"], "boards": [], "jql": "", "secret": "JIRA_TOKEN"},
                "confluence": {"enabled": True, "base_url": "https://wiki.example.com", "spaces": [], "root_pages": [],
                               "secret": "not a name, a pasted value", "auth": "bearer", "verify_tls": True}},
    "app": {"source_dirs": [], "modules": []}, "etl": {"modules": []},
    "db": {"environments_file": "db-environments.yaml"},
    "owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev", "db_owner": "", "etl_owner": "",
               "roles": {"data lead": "Dee Data", "manager": "Max Boss"}},
    "gate": {"certifiers": ["Cy Cert"], "allow_self_certify": False,
             "teams": [{"name": "Payments", "owns": ["context/payments/*"], "approvers": ["Pia Pay"]}]},
    "verify": {"strict_tags": True},
    "questions": {"role_for_type": {"business": "product owner"}},
    "viz": {"title": "Demo", "password": "Hunter2hunter"},
}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(C.profile_path(self.kb), yaml.safe_dump(PROFILE))
        self.pat = C.Ctx(self.kb, "tok", "Pat Lee")
        self.ana = C.Ctx(self.kb, "tok", "Ana Lead")
        self.nobody = C.Ctx(self.kb, "tok", "")

    def tearDown(self):
        rmtree(self.d)

    def profile_now(self):
        return C.profile(self.kb)

    def refused(self, fn, ctx, form):
        with self.assertRaises(C.UiError) as cm:
            fn(ctx, form)
        return str(cm.exception)

    def seed(self):
        """One record of every kind the audit log reads."""
        write(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pets have owners\n")
        write(os.path.join(self.kb, "context", "a.md"), '# A\n\n- Pets have owners. [E: file:rules.txt "pets have owners"]\n')
        kb_gate.lock(self.kb, "Ana Lead")
        src = os.path.join(self.d, "src")
        write(os.path.join(src, "context", "b.md"), '# B\n\n- Pets have owners. [E: file:rules.txt "pets have owners"]\n')
        batch = kb_gate.new_batch(self.kb, "docs")
        kb_gate.propose(self.kb, batch, src)
        kb_gate.certify(self.kb, batch, "Raj Dev")
        src2 = os.path.join(self.d, "src2")
        write(os.path.join(src2, "context", "c.md"), "# C\n")
        batch2 = kb_gate.new_batch(self.kb, "more")
        kb_gate.propose(self.kb, batch2, src2)
        kb_gate.reject(self.kb, batch2, "Ana Lead", "not sourced")
        a = answers.ask(self.kb, "Which table do pets reference?", "Pat Lee", mode="local")
        answers.rate(self.kb, a["id"], "Pat Lee", "up")
        questions.cmd_raise(self.kb, "Who owns <b>billing</b>?", "business", "Pat Lee")
        write(os.path.join(self.d, "ans.yaml"), yaml.safe_dump({"answers": [{"id": "Q-0001", "answer": "Finance <script>x</script>", "answered_by": "Dee Data"}]}))
        questions.cmd_answer(self.kb, os.path.join(self.d, "ans.yaml"))
        t = tasks.create(self.kb, "build-stage", "Build context", "do it", "Pat Lee", ref="R-1")
        tasks.claim(self.kb, "Worker One", t["id"])
        tasks.complete(self.kb, t["id"], "Worker One", note="done")
        C.dump_yaml(os.path.join(self.kb, ".metis", "builds", "2020-01-02-kb.yaml"),
                    {"run": "2020-01-02-kb", "started": "2020-01-02T10:00:00", "started_by": "Pat Lee", "status": "done",
                     "first_build": True, "finished": "2020-01-02T11:00:00", "stages": []})
        C.dump_yaml(os.path.join(self.kb, ".metis", "stack.yaml"), {"approved_by": "Raj Dev", "approved_on": "2020-01-03", "items": [{"name": "x"}]})
        telemetry.record(self.kb, "pack", ["context/a.md"], "P-1", 10, "Pat Lee")


class TestAudit(Base):
    def test_every_record_kind_is_listed(self):
        self.seed()
        events, sources, problems, _ = A.collect(self.kb)
        self.assertEqual(problems, [])
        kinds = {e["kind"] for e in events}
        self.assertEqual(kinds, {"lock", "certification", "rejection", "rating", "question raised", "question answered", "question asked",
                                 "build started", "build finished", "task claimed", "task finished", "setup approval", "context pack"})
        by_kind = {k: [e for e in events if e["kind"] == k] for k in kinds}
        self.assertEqual(by_kind["lock"][0]["who"], "Ana Lead")
        self.assertEqual(by_kind["certification"][0]["who"], "Raj Dev")
        self.assertIn("context/b.md", by_kind["certification"][0]["text"])
        self.assertEqual(by_kind["certification"][0]["href"], "/files?page=context/b.md")
        self.assertIn("not sourced", by_kind["rejection"][0]["text"])
        self.assertEqual(by_kind["question answered"][0]["who"], "Dee Data")
        self.assertEqual(by_kind["question raised"][0]["who"], "Pat Lee")
        self.assertEqual(by_kind["task claimed"][0]["who"], "Worker One")
        self.assertEqual(by_kind["setup approval"][0]["who"], "Raj Dev")
        self.assertTrue(all(e["at"] for e in events))
        self.assertTrue(all(e["href"] for e in events if e["kind"] != "context pack"))
        self.assertEqual(len(sources), len(A.READERS))
        self.assertTrue(all(found for _, _, found, _ in sources))

    def test_page_orders_newest_first_and_names_its_records(self):
        self.seed()
        html = A.audit(self.pat, {})
        self.assertIn("Records this page reads", html)
        self.assertIn(".metis/CERTIFICATIONS.log", html)
        self.assertIn("_FEEDBACK/FEEDBACK.yaml", html)
        self.assertLess(html.index("certified context/b.md"), html.index("2020-01-02 10:00"))

    def test_filters(self):
        self.seed()
        raj = A.audit(self.pat, {"person": "Raj Dev"})
        self.assertIn("certified context/b.md", raj)
        self.assertNotIn("rejected batch", raj)
        kind = A.audit(self.pat, {"kind": "rejection"})
        self.assertIn("rejected batch", kind)
        self.assertNotIn("certified context/b.md", kind)
        old = A.audit(self.pat, {"from": "2020-01-01", "to": "2020-01-31"})
        self.assertIn("started run 2020-01-02-kb", old)
        self.assertIn("approved the tech stack", old)
        self.assertNotIn("certified context/b.md", old)
        self.assertIn("No record matches this filter.", A.audit(self.pat, {"person": "Raj Dev", "kind": "rejection"}))

    def test_bad_date_is_refused_in_words(self):
        self.seed()
        html = A.audit(self.pat, {"from": "yesterday"})
        self.assertIn("YYYY-MM-DD", html)
        self.assertIn("certified context/b.md", html)

    def test_user_text_is_escaped(self):
        self.seed()
        self.assertNotIn("<i>x</i>", A.audit(self.pat, {"person": "<i>x</i>"}))
        html = A.audit(self.pat, {})
        self.assertNotIn("<b>billing</b>", html)
        self.assertIn("&lt;b&gt;billing&lt;/b&gt;", html)
        self.assertNotIn("<script>x</script>", html)

    def test_empty_kb_and_unreadable_record(self):
        self.assertIn("No record exists yet", A.audit(self.pat, {}))
        write(os.path.join(self.kb, "_FEEDBACK", "FEEDBACK.yaml"), "feedback: [unclosed")
        self.assertIn("could not be read", A.audit(self.pat, {}))

    def test_records_without_a_date_are_counted_not_invented(self):
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump(
            {"questions": [{"id": "Q-0001", "question": "No date", "type": "business", "priority": "P2", "answer_role": "product owner", "status": "open"}]}))
        events, _, _, undated = A.collect(self.kb)
        self.assertEqual(events, [])
        self.assertEqual(undated, 1)
        self.assertIn("1 record(s) had no date", A.audit(self.pat, {}))


class TestTeams(Base):
    def test_page_shows_owner_leads_teams_and_keys(self):
        html = A.teams_view(self.pat, {})
        for text in ("Ana Lead", "Raj Dev", "Dee Data", "Cy Cert", "Payments", "context/payments/*", "Pia Pay", "owners.kb_owner",
                     "gate.teams[].name", "you are not a lead", "files of Payments", "Add a team approver"):
            self.assertIn(text, html)

    def test_rights_follow_kb_gate(self):
        self.assertEqual(A.rights(self.kb, "Ana Lead")["certify"], "any file")
        self.assertTrue(A.rights(self.kb, "Cy Cert")["approve"])
        pia = A.rights(self.kb, "Pia Pay")
        self.assertEqual((pia["approve"], pia["certify"], pia["lock"]), (False, "files of Payments", False))
        boss = A.rights(self.kb, "Max Boss")  # manager is not a lead role
        self.assertEqual((boss["approve"], boss["certify"]), (False, ""))

    def test_no_team_and_no_profile(self):
        write(C.profile_path(self.kb), yaml.safe_dump(dict(PROFILE, gate={"certifiers": []})))
        html = A.teams_view(self.pat, {})
        self.assertIn("gate.teams</code> is empty", html)
        self.assertNotIn("/teams/approver", html)
        os.remove(C.profile_path(self.kb))
        self.assertIn("There is no profile yet", A.teams_view(self.pat, {}))

    def test_add_certifier_needs_a_named_lead(self):
        form = {"name": "New Person"}
        self.assertIn("Say who you are first", self.refused(A.act_add_certifier, self.nobody, form))
        self.assertIn("not a lead", self.refused(A.act_add_certifier, self.pat, form))
        self.assertEqual(self.profile_now()["gate"]["certifiers"], ["Cy Cert"])
        where, _ = A.act_add_certifier(self.ana, form)
        self.assertEqual(where, "/teams")
        self.assertEqual(self.profile_now()["gate"]["certifiers"], ["Cy Cert", "New Person"])
        self.assertIn("new person", kb_gate.certifiers(self.kb))
        now = self.profile_now()  # nothing else moved
        self.assertEqual(now["gate"]["teams"], PROFILE["gate"]["teams"])
        self.assertEqual(now["sources"]["jira"], PROFILE["sources"]["jira"])
        self.assertEqual(now["viz"], PROFILE["viz"])
        self.assertIn("already", A.act_add_certifier(self.ana, form)[1])

    def test_a_secret_or_odd_name_is_refused(self):
        for bad in ("", "<name>", "A, B", "password: Hunter2hunter", "x" * 81):
            self.refused(A.act_add_certifier, self.ana, {"name": bad})
        self.assertEqual(self.profile_now()["gate"]["certifiers"], ["Cy Cert"])

    def test_set_role(self):
        self.assertIn("not a lead", self.refused(A.act_set_role, self.pat, {"role": "architect", "name": "Ari Arch"}))
        self.assertIn("listed roles", self.refused(A.act_set_role, self.ana, {"role": "king", "name": "Ari Arch"}))
        A.act_set_role(self.ana, {"role": "architect", "name": "Ari Arch"})
        roles = self.profile_now()["owners"]["roles"]
        self.assertEqual((roles["architect"], roles["data lead"]), ("Ari Arch", "Dee Data"))

    def test_add_team_approver(self):
        self.assertIn("not a lead", self.refused(A.act_add_approver, self.pat, {"team": "Payments", "name": "Zed"}))
        self.assertIn("listed teams", self.refused(A.act_add_approver, self.ana, {"team": "Nope", "name": "Zed"}))
        A.act_add_approver(self.ana, {"team": "Payments", "name": "Zed Zee"})
        team = self.profile_now()["gate"]["teams"][0]
        self.assertEqual(team["approvers"], ["Pia Pay", "Zed Zee"])
        self.assertEqual(team["owns"], ["context/payments/*"])
        self.assertIn("already approves", A.act_add_approver(self.ana, {"team": "Payments", "name": "zed zee"})[1])
        self.assertEqual(A.rights(self.kb, "Zed Zee")["certify"], "files of Payments")

    def test_edit_is_undone_when_setup_would_change_something_else(self):
        p = yaml.safe_load(yaml.safe_dump(PROFILE))
        p["sources"]["jira"]["enabled"] = False  # Setup's save always writes enabled: true
        write(C.profile_path(self.kb), yaml.safe_dump(p))
        before = read_bytes(C.profile_path(self.kb))
        self.assertIn("sources.jira.enabled", self.refused(A.act_add_certifier, self.ana, {"name": "New Person"}))
        self.assertEqual(read_bytes(C.profile_path(self.kb)), before)

    def test_edit_is_undone_when_setup_refuses(self):
        p = yaml.safe_load(yaml.safe_dump(PROFILE))
        p["sources"]["repos"] = {}
        write(C.profile_path(self.kb), yaml.safe_dump(p))
        before = read_bytes(C.profile_path(self.kb))
        self.refused(A.act_add_certifier, self.ana, {"name": "New Person"})
        self.assertEqual(read_bytes(C.profile_path(self.kb)), before)


class TestSettings(Base):
    def test_sections_shown_and_secrets_hidden(self):
        html = A.settings(self.pat, {})
        for text in ("product", "Demo Shop", "paths", "gate", "viz", "verify", "JIRA_TOKEN", "a lead can change repo.base_branch here"):
            self.assertIn(text, html)
        self.assertNotIn("Hunter2hunter", html)
        self.assertNotIn("a pasted value", html)
        self.assertIn(A.HIDDEN, html)
        self.assertIn("no <code>thresholds</code> section", html)

    def test_redact(self):
        r = A.redact({"a": {"secret": "MY_SECRET", "token": "abc", "note": "ok", "list": [{"api_key": "k"}]},
                      "b": "password: Hunter2hunter", "c": "Bearer " + "x" * 30})
        self.assertEqual(r["a"]["secret"], "MY_SECRET")
        self.assertEqual(r["a"]["token"], A.HIDDEN)
        self.assertEqual(r["a"]["note"], "ok")
        self.assertEqual(r["a"]["list"][0]["api_key"], A.HIDDEN)
        self.assertEqual(r["b"], A.HIDDEN)
        self.assertEqual(r["c"], A.HIDDEN)

    def test_values_are_escaped(self):
        write(C.profile_path(self.kb), yaml.safe_dump(dict(PROFILE, viz={"title": "<script>alert(1)</script>"})))
        html = A.settings(self.pat, {})
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_save_by_a_lead(self):
        form = {"branch": "release/1", "certifiers": "Cy Cert, Dan New", "role_dev_lead": "Dev Lead", "role_data_lead": "Dee Data", "role_manager": "Max Boss"}
        self.assertIn("Say who you are first", self.refused(A.act_settings_save, self.nobody, form))
        self.assertIn("not a lead", self.refused(A.act_settings_save, self.pat, form))
        self.assertEqual(self.profile_now()["repo"]["base_branch"], "main")
        where, msg = A.act_settings_save(self.ana, form)
        self.assertEqual(where, "/settings")
        self.assertIn("branch", msg)
        now = self.profile_now()
        self.assertEqual(now["repo"]["base_branch"], "release/1")
        self.assertEqual(now["gate"]["certifiers"], ["Cy Cert", "Dan New"])
        self.assertEqual(now["owners"]["roles"]["dev lead"], "Dev Lead")
        self.assertEqual(now["owners"]["kb_owner"], "Ana Lead")
        self.assertEqual(now["sources"]["jira"]["secret"], "JIRA_TOKEN")
        self.assertEqual(now["viz"], PROFILE["viz"])
        self.assertEqual(A.act_settings_save(self.ana, form)[1], "Nothing changed.")

    def test_bad_values_are_refused(self):
        base = {"branch": "main", "certifiers": "Cy Cert"}
        self.assertIn("branch name", self.refused(A.act_settings_save, self.ana, dict(base, branch="bad branch; rm")))
        self.refused(A.act_settings_save, self.ana, dict(base, certifiers="Cy Cert, token: abcd1234efgh"))
        self.assertEqual(self.profile_now()["gate"]["certifiers"], ["Cy Cert"])

    def test_no_profile(self):
        os.remove(C.profile_path(self.kb))
        self.assertIn("There is no profile yet", A.settings(self.pat, {}))


class TestContract(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(set(A.SCREENS), {"/audit", "/teams", "/settings"})
        self.assertEqual(A.NAV, [("/audit", "Audit log"), ("/teams", "Teams and rights"), ("/settings", "Settings")])
        for path, (screen, fn) in A.ACTIONS.items():
            self.assertTrue(path.startswith(screen + "/"))
            self.assertIn(screen, A.SCREENS)
            self.assertTrue(callable(fn))


if __name__ == "__main__":
    unittest.main()
