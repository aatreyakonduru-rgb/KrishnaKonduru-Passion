"""Argus (console/server.py) tests — stdlib only, fake Devin and Jira, no network.

    python3 -m unittest discover -s sdlc/framework/tools/tests -v
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

HOME = tempfile.mkdtemp(prefix="sdlc-workbench-test-")
os.environ["SDLC_CONSOLE_HOME"] = HOME
os.environ["SDLC_WORKBENCH_READ_REMOTE"] = "0"
os.environ["SDLC_SHARED_ASSISTANT"] = "0"
CONSOLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "console")

JS_PARTS = ("console.js", "console-run.js", "console-pc.js", "console-backlog.js", "console-auto.js", "console-main.js", "console-feedback.js")


def workbench_js():
    """Argus page script: its parts, in the order index.html loads them."""
    out = []
    for name in JS_PARTS:
        with open(os.path.join(CONSOLE, "static", name), encoding="utf-8") as fh:
            out.append(fh.read())
    return "\n".join(out)
sys.path.insert(0, CONSOLE)

import pctest  # noqa: E402
import server as wb  # noqa: E402
wb.SHARED_ASSISTANT = False

ME = "resource3"   # Resource 3 — solution_lead on people.yaml
SECRET = "not-a-real-token-123"


class FakeDevin:
    key = SECRET

    def __init__(self):
        self.created, self.sent, self.listed = [], [], []
        self.terminated, self.tagged = [], {}

    def create_session(self, prompt, title, tags):
        self.created.append({"prompt": prompt, "title": title, "tags": tags})
        return {"session_id": "devin-%d" % len(self.created), "url": "https://example.invalid/s", "status": "new"}

    def session(self, devin_id):
        return {"status_enum": "blocked", "status": "blocked", "messages": [], "title": "t"}

    @staticmethod
    def messages(info):
        return []

    def send(self, devin_id, text):
        self.sent.append((devin_id, text))

    def list_sessions(self, tag, limit=50):
        return list(self.listed) if tag == wb.WORKBENCH_TAG else []

    def terminate(self, devin_id):
        self.terminated.append(devin_id)

    def set_tags(self, devin_id, tags):
        self.tagged[devin_id] = tags


class FakeJira:
    token = SECRET

    def stories(self, scope, jira_user=""):
        if scope == "waiting" and jira_user:
            return {"jql": "", "stories": []}
        if scope == "mine" and not jira_user:
            raise wb.ApiError(400, "Pick who you are (top right) to list the tickets assigned to you.")
        raise wb.ApiError(503, "Jira returned 401 for the service account; not retrying (token may be locked).")


class RepoReaderTests(unittest.TestCase):
    def test_roster_person_and_roles(self):
        p = wb.find_person(ME)
        self.assertEqual(p["name"], "Resource 3")
        self.assertEqual(p["primary_role"], "solution_lead")
        self.assertEqual(wb.find_person(p["email"].upper())["jira_user"], ME)
        self.assertIsNone(wb.find_person("nobody-here"))

    def test_menus_come_from_the_roles_ticked_skills(self):
        roles = wb.load_roles()
        for role_id in ("solution_lead", "bsa"):
            view = wb.role_view(role_id, roles)
            req = [i["skill"] for i in view["menus"][0]["items"]]
            in_kb = {a[0] for a in wb.KB_ACTIONS}
            names = roles[role_id]["default_skills"] + roles[role_id]["more_skills"] + roles[role_id]["everyone_skills"]
            names = [s for i, s in enumerate(names) if s not in names[:i]]
            want = [s for s in names if s not in wb.NOT_IN_TOOLS and s not in in_kb and wb.skill_info(s)]
            self.assertEqual(req, want)
            self.assertTrue(all(os.path.isfile(os.path.join(wb.SKILLS_DIR, s, "SKILL.md")) for s in req))
        self.assertEqual(wb.role_view("solution_lead", roles)["menus"][0]["label"], "My tools")
        self.assertEqual(wb.role_view("solution_lead", roles)["lens"], "tech_lead")
        kb = [i["label"] for i in wb.role_view("bsa", roles)["menus"][1]["items"]]
        self.assertEqual(kb, ["Ask a question", "Explain a capability"])
        kb = [i["label"] for i in wb.role_view("qa_staff", roles)["menus"][1]["items"]]
        self.assertNotIn("Find drift", kb)
        kb = [i["label"] for i in wb.role_view("architect", roles)["menus"][1]["items"]]
        self.assertIn("Find drift", kb)
        self.assertNotIn("Generate new knowledge", kb)
        for role_id in ("solution_lead", "manager"):
            kb = [i["label"] for i in wb.role_view(role_id, roles)["menus"][1]["items"]]
            self.assertIn("Generate new knowledge", kb)
        self.assertTrue(all(r in roles for r in wb.KB_AUTHOR_ROLES))

    def test_business_roles_get_what_i_do_tasks(self):
        roles = wb.load_roles()
        for role_id in ("product_owner", "bsa", "scrum_master"):
            view = wb.role_view(role_id, roles)
            self.assertTrue(view["business"], role_id)
            tasks = [t for g in view["tasks"] for t in g["tasks"]]
            self.assertTrue(tasks, role_id)
            for t in tasks:
                self.assertEqual(sum(1 for k in ("pane", "action", "menu") if t.get(k)), 1, t["id"])
                if t.get("skill"):
                    self.assertEqual(t["action"]["skill"], t["skill"])
        self.assertIn("grooming-prep", [t["id"] for g in wb.role_view("product_owner", roles)["tasks"] for t in g["tasks"]])
        for role_id in ("ui_developer", "solution_lead"):
            self.assertFalse(wb.role_view(role_id, roles)["business"], role_id)

    def test_scrum_master_has_one_time_off_task(self):
        sm = {t["id"]: t for g in wb.business_tasks("scrum_master") for t in g["tasks"]}
        self.assertNotIn("leave", sm)
        self.assertNotIn("vacation", sm)
        self.assertEqual((sm["time-off"]["pane"], sm["time-off"]["part"]), ("followups", "leave"))
        self.assertEqual(sm["time-off"]["more_action"]["skill"], "vacation")
        self.assertEqual(sm["standup"]["part"], "standup")

    def test_business_skills_and_panels_exist(self):
        data = wb.load_business()
        import yaml
        with open(os.path.join(wb.ROOT, ".devin", "rules", "dashboard-roles.yaml"), encoding="utf-8") as fh:
            lenses = yaml.safe_load(fh)["lenses"]
        for lens, groups in data["lenses"].items():
            panels = set(lenses[lens]["panels"])
            for g in groups:
                for t in g["tasks"]:
                    if t.get("skill"):
                        self.assertTrue(wb.skill_info(t["skill"]), t["skill"])
                    self.assertFalse(set(t.get("panels") or []) - panels, (lens, t["id"]))
                    if t.get("pane"):
                        self.assertIn(t["pane"], ("groom", "groomprep", "plan", "calendar", "followups", "create"))

    def test_several_hats_merge_into_one_list(self):
        po = wb.business_tasks("po_office")
        merged = wb.merge_tasks([po, wb.business_tasks("bsa")])
        ids = [t["id"] for g in merged for t in g["tasks"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("intake", ids)
        self.assertEqual([g["group"] for g in merged][:len(po)], [g["group"] for g in po])

    def test_several_hats_see_every_hats_buttons(self):
        roles = wb.load_roles()
        hats = ["product_owner", "bsa_lead", "uat_lead", "release_manager"]
        views = [wb.role_view(h, roles) for h in hats]
        both = wb.all_hats_view(views)
        self.assertEqual(both["hat_ids"], hats)
        self.assertTrue(both["business"] and both["delivery"])
        for v in views:
            self.assertFalse(set(v["gate_roles"]) - set(both["gate_roles"]), v["id"])
            for mine, theirs in zip(both["menus"], v["menus"]):
                self.assertFalse({i["skill"] for i in theirs["items"]} - {i["skill"] for i in mine["items"]}, v["id"])
        for m in both["menus"]:
            skills = [i["skill"] for i in m["items"]]
            self.assertEqual(len(skills), len(set(skills)), m["id"])
        only_biz = wb.all_hats_view([wb.role_view(h, roles) for h in ("product_owner", "bsa")])
        self.assertTrue(only_biz["business"])
        self.assertFalse(only_biz["delivery"])
        dev = wb.all_hats_view([wb.role_view(h, roles) for h in ("solution_lead", "developer", "reviewer")])
        self.assertFalse(dev["business"])
        self.assertTrue(dev["delivery"])

    def test_every_lens_has_a_screen_layout(self):
        roles, layouts = wb.load_roles(), wb.load_layouts()
        for role_id, role in roles.items():
            self.assertIn(role["dashboard_lens"], layouts, role_id)
        for lens, lay in layouts.items():
            self.assertIn(lay["list"], wb.LAYOUT_LISTS, lens)
            self.assertIn(lay["left"], ("open", "rail"), lens)
            self.assertIn(lay["right"], wb.LAYOUT_SIDES, lens)
        self.assertEqual(wb.role_view("bsa", roles, layouts)["layout"]["list"], "open")
        self.assertEqual(wb.role_view("bsa", roles, layouts)["layout"]["right"], "auto")
        self.assertEqual(wb.role_view("ui_developer", roles, layouts)["layout"]["list"], "mine_sprint")
        self.assertEqual(wb.role_view("solution_lead", roles, layouts)["layout"]["list"], "sprint")
        auto = wb.role_view("automation_engineer", roles, layouts)
        self.assertEqual(auto["layout"]["list"], "automation")
        self.assertEqual([i["skill"] for i in auto["menus"][0]["items"]][:4],
                         ["acme-auto-story", "acme-auto-run", "acme-auto-fix", "acme-auto-setup"])

    def test_layout_ignores_bad_values(self):
        folder = tempfile.mkdtemp(prefix="sdlc-layout-")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "routing-bad.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("roles:\n  bsa:\n    dashboard_lens: bsa\nworkbench_layouts:\n  bsa:\n    list: everything\n"
                     "    left: auto\n    right: rail\n    right_width: 9000\nrole_aliases:\n  po: bsa\n")
        with mock.patch.object(wb, "ROUTING_PATH", path):
            self.assertEqual(wb.load_layouts(), {"bsa": dict(wb.LAYOUT_DEFAULT, right="rail")})
            self.assertEqual(wb.role_view("nobody", {}, {})["layout"], wb.LAYOUT_DEFAULT)

    def test_backlog_roles_in_the_page_are_real_roles(self):
        js = workbench_js()
        listed = re.findall(r'"([a-z_]+)"', re.search(r"BACKLOG_ROLES = \[([^\]]*)\]", js).group(1))
        self.assertTrue(listed)
        self.assertEqual([r for r in listed if r not in wb.load_roles()], [])

    def test_gates_and_stages(self):
        g = wb.gate_info("SDLC_04")
        self.assertEqual(g["id"], "SDLC_04_ROUTING_APPROVAL")
        self.assertTrue(g["approval_criteria"])
        self.assertEqual(len(wb.STAGES), 7)
        self.assertEqual(wb.norm_stage("KB  refresh"), "kb-refresh")
        self.assertEqual(wb.norm_stage("pr"), "implement")
        self.assertEqual(wb.norm_stage("eval"), "test")

    def test_skill_info_rejects_paths(self):
        self.assertIsNone(wb.skill_info("../rules"))
        self.assertIsNone(wb.skill_info("no-such-skill-xyz"))

    def test_tools_menu_uses_plain_names_and_skips_the_top_bar_buttons(self):
        roles = wb.load_roles()
        for role_id in roles:
            for it in wb.role_view(role_id, roles)["menus"][0]["items"]:
                self.assertNotIn(it["skill"], wb.NOT_IN_TOOLS, role_id)
                self.assertIn(it["skill"], wb.MENU_TEXT, "%s has no plain menu name" % it["skill"])
        self.assertTrue(all(wb.skill_info(n) for n in wb.MENU_TEXT), "MENU_TEXT names a skill that does not exist")

    def test_no_menu_item_appears_twice(self):
        roles = wb.load_roles()
        for role_id in roles:
            skills = [i["skill"] for m in wb.role_view(role_id, roles)["menus"] for i in m["items"]]
            self.assertEqual(len(skills), len(set(skills)), role_id)

    def test_skill_input_from_argument_hint(self):
        self.assertEqual(wb.skill_input(""), {"required": False, "hint": "", "choices": []})
        p = wb.skill_input("[optional: architecture | sdlc | bsa-po | kb | all]")
        self.assertFalse(p["required"])
        self.assertEqual(p["choices"], ["architecture", "sdlc", "bsa-po", "kb", "all"])
        p = wb.skill_input("<role: BSA | PO | finance-user | developer>")
        self.assertTrue(p["required"])
        self.assertEqual(p["choices"], ["BSA", "PO", "finance-user", "developer"])
        self.assertEqual(wb.skill_input("[compliance standard: HIPAA | SOX | all (default: all)]")["choices"], ["HIPAA", "SOX", "all"])
        p = wb.skill_input("<REQ-ID> <STORY-ID>  e.g. REQ-TIN-001 STORY-003")
        self.assertTrue(p["required"])
        self.assertEqual(p["choices"], [])
        self.assertFalse(wb.skill_info("presentation")["input"]["required"])
        self.assertTrue(wb.skill_info("investigate")["input"]["required"])

    def test_repo_file_artefact_keeps_the_next_code_block(self):
        text = ("[SDLC] artefact sdlc/framework/ARCHITECTURE.html — repo file\n"
                "[SDLC] artefact NOTES.md — ready\n```markdown\n# Notes\n```")
        arts = wb.parse_devin_message(text)[3]
        self.assertTrue(arts[0]["repo_file"])
        self.assertEqual(arts[0]["body"], "")
        self.assertEqual(arts[1]["body"].strip(), "# Notes")

    def test_settings_documentation_opens_the_workbench_manual(self):
        js = workbench_js()
        self.assertIn("(state.cfg.docs || {}).workbench_manual", js)
        path = wb.team.DOCS["workbench_manual"]
        self.assertEqual(wb.repo_rel(path), path)
        self.assertTrue(os.path.isfile(os.path.join(wb.ROOT, path)), path)

    def test_jira_check_only_runs_while_the_page_is_in_use(self):
        js = workbench_js()
        self.assertIn('every("waiting", 60000, loadWaiting, { hidden: 0, when: function () { return state.cfg && inUse(); } });', js)
        self.assertIn("return !document.hidden && Date.now() - state.lastActive < 3600000;", js)

    def test_repo_rel_only_opens_readable_repo_files(self):
        self.assertEqual(wb.repo_rel("/sdlc/framework/ARCHITECTURE.html"), "sdlc/framework/ARCHITECTURE.html")
        for bad in ("../etc/passwd.txt", ".devin/secrets.yaml", "a/.git/config.txt", "web/x.py", ""):
            self.assertIsNone(wb.repo_rel(bad), bad)


class LastGoodStoriesTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(wb.LAST_STORIES_DIR, ignore_errors=True)

    tearDown = setUp

    def jira(self, result):
        j = mock.Mock()
        j.stories.side_effect = [result] if not isinstance(result, Exception) else result
        return j

    def test_jira_down_returns_last_good_list_marked_stale(self):
        good = {"jql": "q", "stories": [{"key": "ACME-1"}], "total": 1, "truncated": False}
        first = wb.stories_or_last_good(self.jira(good), "mine", ME)
        self.assertNotIn("stale", first)
        down = wb.ApiError(503, "Jira could not be reached (TimeoutError: The read operation timed out)")
        later = wb.stories_or_last_good(self.jira(down), "mine", ME)
        self.assertEqual(later["stories"], good["stories"])
        self.assertTrue(later["stale"])
        self.assertEqual(later["fetched_at"], first["fetched_at"])
        self.assertIn("could not be reached", later["error"])

    def test_saved_lists_are_per_scope_and_person(self):
        good = {"stories": [{"key": "ACME-1"}]}
        wb.stories_or_last_good(self.jira(good), "mine", ME)
        down = wb.ApiError(503, "Jira could not be reached")
        with self.assertRaises(wb.ApiError):
            wb.stories_or_last_good(self.jira(down), "mine", "resource5")
        with self.assertRaises(wb.ApiError):
            wb.stories_or_last_good(self.jira(down), "sprint")

    def test_bad_request_is_not_hidden_by_saved_list(self):
        wb.stories_or_last_good(self.jira({"stories": [{"key": "ACME-1"}]}), "mine", ME)
        with self.assertRaises(wb.ApiError) as err:
            wb.stories_or_last_good(self.jira(wb.ApiError(400, "pick who you are")), "mine", ME)
        self.assertEqual(err.exception.status, 400)

    def test_page_shows_stale_list_age_and_splits_jira_from_devin_wording(self):
        js = workbench_js()
        self.assertIn("j.stale ? j.fetched_at : 0", js)
        self.assertIn("function agoFrom(", js)
        plain = js[js.index("var ERR_PLAIN"):js.index("];", js.index("var ERR_PLAIN"))]
        for text in ("bridge is not running", "Devin session tools:", "Devin did not return a session id",
                     "Cannot reach api\\.devin\\.ai", "Devin Cloud is reconnecting"):
            self.assertIn(text, plain)
        self.assertLess(plain.index("Cannot reach api"), plain.index("Jira could not be reached"))
        self.assertLess(plain.index("Jira could not be reached"), plain.index("RemoteDisconnected"))
        # a stale list from the server is kept, not replaced by an empty browser copy
        self.assertIn("state.storiesErr && !state.stories.length) { storiesFromCache(scope)", js)
        self.assertIn('plainErr(raw).replace("Jira or Devin Cloud", HEALTH_NAMES[k])', js)


class NightlyDashboardAndSavedFirstTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(wb.LAST_STORIES_DIR, ignore_errors=True)
        shutil.rmtree(wb.NIGHTLY_DIR, ignore_errors=True)
        wb._STORY_REFRESH.clear()

    tearDown = setUp

    @staticmethod
    def tools():
        sys.path.insert(0, os.path.join(os.path.dirname(CONSOLE), "tools"))
        import gen_dashboard
        import scrum_metrics
        return gen_dashboard, scrum_metrics

    def test_saved_list_comes_back_at_once_and_old_one_refreshes_in_background(self):
        good = {"stories": [{"key": "ACME-1"}], "total": 1}
        jira = mock.Mock()
        jira.stories.return_value = good
        wb.stories_or_last_good(jira, "sprint")
        jira.stories.reset_mock()
        fresh = wb.stories_saved_first(jira, "sprint")
        self.assertEqual(fresh["stories"], good["stories"])
        self.assertNotIn("refreshing", fresh)
        jira.stories.assert_not_called()
        jobs = []
        with mock.patch.object(wb, "STORIES_FRESH_FOR", -1):
            old = wb.stories_saved_first(jira, "sprint", start=jobs.append)
            self.assertTrue(old["refreshing"])
            self.assertTrue(wb.stories_saved_first(jira, "sprint", start=jobs.append)["refreshing"])
            self.assertEqual(len(jobs), 1)
            jira.stories.side_effect = wb.ApiError(502, "Jira could not be reached (RemoteDisconnected: x)")
            jobs[0]()
            down = wb.stories_saved_first(jira, "sprint", start=jobs.append)
        self.assertTrue(down["stale"])
        self.assertIn("could not be reached", down["error"])
        self.assertEqual(len(jobs), 1)
        jira.stories.side_effect = None
        wb.stories_saved_first(jira, "sprint", refresh=True)
        jira.stories.assert_called()

    def test_dashboard_button_opens_nightly_copy_with_built_at_and_rebuild(self):
        os.makedirs(wb.NIGHTLY_DIR)
        with open(os.path.join(wb.NIGHTLY_DIR, "resource3.solution_lead.html"), "w") as fh:
            fh.write("<html><body class=x><h1>dash</h1></body></html>")
        self.assertIsNone(wb.nightly_page("resource3", "developer"))
        saved = wb.nightly_page("resource3", "solution_lead")
        self.assertEqual(saved, wb.nightly_page("resource3"))
        out = os.path.join(wb.NIGHTLY_DIR, "out.html")
        wb.open_nightly_page(saved, out)
        with open(out) as fh:
            page = fh.read()
        self.assertIn("<body class=x><div id=\"argusBuilt\"", page)
        self.assertIn("Built at ", page)
        self.assertIn("rebuild:true", page)

    def test_nightly_runs_once_after_nine_pm_eastern_even_after_a_sleep(self):
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
        at = wb.datetime.datetime(2026, 10, 26, 8, 0, tzinfo=tz).timestamp()
        self.assertEqual(wb.last_nightly_due(at), wb.datetime.datetime(2026, 10, 25, 21, 0, tzinfo=tz).timestamp())
        late = wb.datetime.datetime(2026, 10, 26, 21, 5, tzinfo=tz).timestamp()
        self.assertEqual(wb.last_nightly_due(late), wb.datetime.datetime(2026, 10, 26, 21, 0, tzinfo=tz).timestamp())
        runs = []

        class Stop(Exception):
            pass

        def run(cmd, **kw):
            runs.append(cmd)
            return mock.Mock(returncode=0)
        sleeps = iter([None, None, Stop()])

        def sleep(_):
            nxt = next(sleeps)
            if nxt:
                raise nxt
        with mock.patch.object(wb.time, "sleep", sleep), self.assertRaises(Stop):
            wb.nightly_dashboards(run=run)
        self.assertEqual(len(runs), 1)
        self.assertIn("--all", runs[0])

    def test_one_unanswered_tab_does_not_stop_the_dashboard(self):
        gd, _ = self.tools()
        cell = gd.jira_unanswered_panel({"id": "x", "title": "Defects"}, RuntimeError("Jira could not be reached (T: t)"))
        self.assertIn("Jira didn't answer", json.dumps(cell))
        self.assertTrue(gd.jira_unanswered(RuntimeError("Jira could not be reached (T)")))
        self.assertFalse(gd.jira_unanswered(RuntimeError("Jira returned 403.")))
        with open(os.path.join(os.path.dirname(CONSOLE), "tools", "gen_dashboard.py")) as fh:
            src = fh.read()
        self.assertIn("panels.append(jira_unanswered_panel(spec, exc))", src)

    def test_shared_reads_and_one_query_for_links_and_history(self):
        gd, sm = self.tools()
        with mock.patch.dict(os.environ, {"ACME_JIRA_TOKEN": SECRET}):
            client = gd.JiraClient()
        calls = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def answer(req, **kw):
            calls.append(req.full_url)
            return Resp(json.dumps({"issues": [{"key": "ACME-1", "fields": {"issuelinks": []}}]}).encode())
        gd.JiraClient.shared = {}
        try:
            with mock.patch("urllib.request.urlopen", answer):
                client.get("/api/2/search", jql="a")
                client.get("/api/2/search", jql="a")
                links = gd.linked_defects(mock.Mock(client=client), ["ACME-1", "ACME-2"])
        finally:
            gd.JiraClient.shared = None
        self.assertEqual(len(calls), 3)   # "a" once, /myself once, one search for both links
        self.assertEqual(links, {"ACME-1": [], "ACME-2": []})
        stories = [{"key": "ACME-%d" % n} for n in range(30)]
        got = []

        def get(path, **kw):
            got.append(kw)
            return {"issues": [{"key": k, "changelog": {"histories": []}} for k in kw["jql"][8:-1].split(", ")]}
        self.assertEqual(sm.add_history(get, stories), "")
        self.assertEqual(len(got), 2)
        self.assertTrue(all(s.get("changelog") == {"histories": []} for s in stories))

        def down(path, **kw):
            raise RuntimeError("Jira could not be reached (TimeoutError: t)")
        self.assertIn("Day counts", sm.add_history(down, [{"key": "ACME-1"}]))


class IntegrationHealthTests(unittest.TestCase):
    def setUp(self):
        wb.HEALTH.forget("jira")
        wb.HEALTH.forget("devin")

    tearDown = setUp

    def refused(self, *a, **kw):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    def test_unreachable_jira_is_failing_not_ok(self):
        j = wb.Jira()
        j.token = SECRET
        with mock.patch("urllib.request.urlopen", self.refused):
            with self.assertRaises(wb.ApiError) as err:
                j.get("/api/2/search", jql="x")
        self.assertEqual(err.exception.status, 502)
        h = wb.integrations(FakeDevin(), j)["jira"]
        self.assertEqual((h["configured"], h["connected"], h["state"]), (True, False, "failing"))

    def test_devin_key_alone_is_not_connected(self):
        d = wb.Devin()
        d.key = "k" * 30
        self.assertEqual(wb.integrations(d, FakeJira())["devin"]["state"], "not_checked")
        with mock.patch("urllib.request.urlopen", self.refused):
            wb.check_integrations(d, wb.CloudJira(d))
        h = wb.integrations(d, wb.CloudJira(d))
        self.assertEqual(h["devin"]["state"], "failing")
        self.assertEqual(h["jira"]["state"], "failing")
        self.assertIn("through Devin Cloud", h["jira"]["error"])

    def test_no_key_is_not_configured(self):
        d = wb.Devin()
        d.key = None
        h = wb.integrations(d, wb.CloudJira(d))
        self.assertEqual(h["devin"]["state"], "not_configured")
        self.assertEqual(h["jira"]["state"], "not_configured")

    def test_jira_timeout_is_tried_once_more(self):
        j = wb.Jira()
        j.token = SECRET
        j.validated = True
        calls = []

        def flaky(req, *a, **kw):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise TimeoutError("The read operation timed out")
            return io.BytesIO(b'{"ok": 1}')
        with mock.patch("urllib.request.urlopen", flaky), mock.patch.object(wb, "JIRA_RETRY_PAUSE", 0):
            self.assertEqual(j.get("/api/2/search", jql="x"), {"ok": 1})
        self.assertEqual(len(calls), 2)
        self.assertEqual(wb.HEALTH.report("jira", True)["state"], "connected")

    def test_jira_refused_twice_gives_up_after_two_tries(self):
        j = wb.Jira()
        j.token = SECRET
        j.validated = True
        calls = []

        def refused(*a, **kw):
            calls.append(1)
            self.refused()
        with mock.patch("urllib.request.urlopen", refused), mock.patch.object(wb, "JIRA_RETRY_PAUSE", 0):
            with self.assertRaises(wb.ApiError) as err:
                j.get("/api/2/search", jql="x")
        self.assertEqual((len(calls), err.exception.status), (2, 502))

    def test_jira_401_403_are_not_retried(self):
        for code in (401, 403):
            j = wb.Jira()
            j.token = SECRET
            j.validated = True
            calls = []

            def locked(*a, **kw):
                calls.append(1)
                raise urllib.error.HTTPError("u", code, "no", {}, None)
            with mock.patch("urllib.request.urlopen", locked), mock.patch.object(wb, "JIRA_RETRY_PAUSE", 0):
                with self.assertRaises(wb.ApiError):
                    j.get("/api/2/search", jql="x")
                with self.assertRaises(wb.ApiError):
                    j.get("/api/2/search", jql="x")
            self.assertEqual(len(calls), 1, code)
            self.assertIn("not retrying", j.dead)

    def test_dashboard_retries_a_dropped_connection_not_a_timeout_and_says_jira(self):
        sys.path.insert(0, os.path.join(os.path.dirname(CONSOLE), "tools"))
        import gen_dashboard
        with mock.patch.dict(os.environ, {"ACME_JIRA_TOKEN": SECRET}):
            client = gen_dashboard.JiraClient()
        calls = []

        def slow(*a, **kw):
            calls.append(1)
            raise TimeoutError("The read operation timed out")
        with mock.patch("urllib.request.urlopen", slow), mock.patch.object(gen_dashboard, "JIRA_RETRY_PAUSE", 0):
            with self.assertRaises(RuntimeError) as err:
                client.get("/api/2/search", jql="x")
        self.assertEqual(len(calls), 1)
        self.assertTrue(str(err.exception).startswith("Jira could not be reached (TimeoutError"), err.exception)

        def dropped(*a, **kw):
            calls.append(1)
            raise ConnectionResetError("reset")
        calls.clear()
        with mock.patch("urllib.request.urlopen", dropped), mock.patch.object(gen_dashboard, "JIRA_RETRY_PAUSE", 0):
            with self.assertRaises(RuntimeError) as err:
                client.get("/api/2/search", jql="x")
        self.assertEqual(len(calls), 2)
        self.assertIn("tried 2 times", str(err.exception))

        def locked(*a, **kw):
            calls.append(1)
            raise urllib.error.HTTPError("u", 403, "no", {}, None)
        calls.clear()
        with mock.patch("urllib.request.urlopen", locked):
            with self.assertRaises(RuntimeError) as err:
                client.get("/api/2/search", jql="x")
        self.assertEqual(len(calls), 1)
        self.assertIn("Not retrying", str(err.exception))

    def test_a_4xx_answer_still_counts_as_reachable(self):
        wb.HEALTH.record("devin", urllib.error.HTTPError("u", 404, "nf", {}, None))
        self.assertTrue(wb.HEALTH.report("devin", True)["connected"])
        wb.HEALTH.record("devin", urllib.error.HTTPError("u", 401, "no", {}, None))
        self.assertEqual(wb.HEALTH.report("devin", True)["state"], "failing")

    def test_refused_local_address_names_the_setting(self):
        with mock.patch.dict(os.environ, {"SDLC_SANDBOX_URL": "http://127.0.0.1:9911"}):
            msg = wb.local_unreachable("http://127.0.0.1:9911/rest/api/2/search", "refused")
        self.assertIn("SDLC_SANDBOX_URL", msg)
        self.assertIn("http://127.0.0.1:9911", msg)

    def test_devin_and_jira_on_one_local_address_each_name_their_own_setting(self):
        local = {"SDLC_JIRA_BASE": "http://127.0.0.1:9", "DEVIN_API_BASE": "http://127.0.0.1:9"}
        d = wb.Devin()
        d.key = "k" * 30
        j = wb.Jira()
        j.token = SECRET
        with mock.patch.dict(os.environ, local), mock.patch("urllib.request.urlopen", self.refused), \
                mock.patch.object(wb, "DEVIN_API", "http://127.0.0.1:9"), mock.patch.object(wb, "JIRA", "http://127.0.0.1:9/rest"):
            with self.assertRaises(wb.ApiError) as dv:
                d.list_sessions(wb.WORKBENCH_TAG, limit=1)
            with self.assertRaises(wb.ApiError) as jr:
                j.get("/api/2/search", jql="x")
        self.assertIn("DEVIN_API_BASE", str(dv.exception))
        self.assertNotIn("SDLC_JIRA_BASE", str(dv.exception))
        self.assertIn("SDLC_JIRA_BASE", str(jr.exception))
        self.assertNotIn("DEVIN_API_BASE", str(jr.exception))


class RunModelTests(unittest.TestCase):
    def test_old_five_stage_run_migrates(self):
        old = {"intake": "done", "research": "done", "plan": "done", "implement": "done", "pr": "running"}
        run = {"stage": "pr", "stages": old}
        wb.migrate_run(run)
        self.assertNotIn("pr", run["stages"])
        self.assertEqual(run["stage"], "implement")
        self.assertEqual(run["stages"]["implement"], "running")
        self.assertEqual(run["stages"]["kb-refresh"], "pending")

    def test_seven_stage_progress(self):
        run = wb.migrate_run({"stage": "intake", "stages": {}, "events": [], "messages": [], "pending_gate": None,
                              "pending_questions": None, "artefacts": [], "diffs": [], "pr": None})
        wb.apply_message(run, {"event_id": "e1", "created_at": "t", "source": "devin",
                               "message": "[SDLC] stage release — finished\n[SDLC] stage kb-refresh — started"})
        self.assertEqual(run["stages"]["release"], "done")
        self.assertEqual(run["stage"], "kb-refresh")

    def test_run_is_complete_once_kb_refresh_is_done_and_nothing_waits(self):
        run = wb.migrate_run({"stage": "kb-refresh", "stages": {}, "events": [], "messages": [], "pending_gate": None,
                              "pending_questions": None, "artefacts": [], "diffs": [], "pr": None, "status": "blocked"})
        self.assertFalse(wb.sdlc_complete(run))
        wb.apply_message(run, {"event_id": "e1", "created_at": "t", "source": "devin",
                               "message": "[SDLC] stage kb-refresh — finished"})
        self.assertTrue(wb.sdlc_complete(run))
        self.assertFalse(wb.sdlc_complete(dict(run, status="working")))
        self.assertFalse(wb.sdlc_complete(dict(run, sent_at=1)))
        self.assertFalse(wb.sdlc_complete(dict(run, pending_gate={"id": "SDLC_08_KB_REFRESH_VALIDATION"})))
        self.assertFalse(wb.sdlc_complete(dict(run, kind="action")))

    def test_run_is_not_complete_after_its_last_gate_is_rejected(self):
        run = wb.migrate_run({"stage": "kb-refresh", "stages": {}, "events": [], "messages": [], "pending_gate": None,
                              "pending_questions": None, "artefacts": [], "diffs": [], "pr": None, "status": "blocked"})
        wb.apply_message(run, {"event_id": "e1", "created_at": "t", "source": "devin",
                               "message": "[SDLC] stage kb-refresh — finished"})
        run["pending_gate"] = {"id": "SDLC_08_KB_REFRESH_VALIDATION"}
        wb.apply_message(run, {"event_id": "e2", "created_at": "t", "source": "user",
                               "message": "rejected SDLC_08_KB_REFRESH_VALIDATION — provenance log missing"})
        self.assertIsNone(run["pending_gate"])
        self.assertFalse(wb.sdlc_complete(run))
        run["pending_gate"] = {"id": "SDLC_08_KB_REFRESH_VALIDATION"}
        wb.apply_message(run, {"event_id": "e3", "created_at": "t", "source": "user",
                               "message": "approved SDLC_08_KB_REFRESH_VALIDATION"})
        self.assertTrue(wb.sdlc_complete(run))

    def test_sent_message_is_shown_once_after_devin_echoes_it(self):
        run = wb.migrate_run({"stage": "intake", "stages": {}, "events": [], "pending_gate": None,
                              "pending_questions": None, "artefacts": [], "diffs": [], "pr": None,
                              "messages": [{"event_id": "local-1", "at": 1, "source": "user", "text": "1. yes", "local": True}]})
        wb.apply_message(run, {"event_id": "e1", "created_at": "t", "source": "user", "message": "1. yes"})
        self.assertEqual(run["messages"], [{"event_id": "e1", "at": "t", "source": "user", "text": "1. yes"}])
        wb.apply_message(run, {"event_id": "e2", "created_at": "t", "source": "user", "message": "1. yes"})
        self.assertEqual([m["event_id"] for m in run["messages"]], ["e1", "e2"])

    def test_rebuild_from_tags(self):
        kind, story = wb.run_from_tags([wb.WORKBENCH_TAG, "ACME-18698", "dry-run"], "SDLC dry run ACME-18698 — Approved date")
        self.assertEqual((kind, story["key"], story["summary"]), ("sdlc", "ACME-18698", "Approved date"))
        kind, story = wb.run_from_tags([wb.WORKBENCH_TAG, "action", "kb-refresh", "live"], "Argus /kb-refresh — after 26.4")
        self.assertEqual((kind, story["action"]), ("action", "kb-refresh"))

    def test_poll_cadence(self):
        self.assertTrue(wb.due({"session_id": "d", "status": "working", "polled_at": 0}, 100))
        self.assertFalse(wb.due({"session_id": "d", "status": "blocked", "polled_at": 90}, 100))
        self.assertFalse(wb.due({"session_id": "d", "status": "finished", "polled_at": 1}, 100))
        self.assertFalse(wb.due({"session_id": "d", "status": "exit", "polled_at": 1}, 10 ** 9))
        # a page watching it, or a message waiting for Devin's answer, reads it as often as a busy one
        self.assertTrue(wb.due({"session_id": "d", "status": "blocked", "polled_at": 90, "watched_at": 95}, 100))
        self.assertTrue(wb.due({"session_id": "d", "status": "finished", "polled_at": 90, "sent_at": 50}, 100))
        self.assertFalse(wb.due({"session_id": "d", "status": "blocked", "polled_at": 90, "watched_at": 10}, 100))
        self.assertFalse(wb.due({"session_id": "d", "status": "exit", "polled_at": 90, "watched_at": 99}, 100))

    def test_forward_text_is_send_approval(self):
        t = wb.forward_text("SDLC_01_INTAKE_CLARIFICATION", "AB12345", 'check "scope"', "2, 4; rm")
        self.assertEqual(t, "/send-approval SDLC_01_INTAKE_CLARIFICATION to AB12345 items 2, 4 \"check 'scope'\"")

    def test_action_prompt_keeps_dry_run_rules(self):
        p = wb.build_action_prompt("kb-refresh", "", True)
        self.assertIn("/kb-refresh", p)
        self.assertIn("do not commit, push, open pull requests", p)
        p = wb.build_prompt({"key": "ACME-1", "custom": False, "summary": "s", "description": ""}, True)
        self.assertIn("kb-refresh", p)
        self.assertIn("do not commit, push, open pull requests", p)
        self.assertIn("Testing in Devin Cloud", p)

    def test_ticket_prompt_asks_the_hotfix_question_first(self):
        p = wb.build_prompt({"key": "ACME-7", "custom": False, "summary": "s", "description": ""}, True)
        self.assertIn("hotfix.py check --key ACME-7", p)
        self.assertIn("HOTFIX_PLAN_CODE_APPROVAL", p)
        self.assertIn("No other gate is skipped", p)
        typed = wb.build_prompt(wb.custom_story("Add a filter"), True)
        self.assertNotIn("hotfix.py check", typed)

    def test_only_act_as_people_build_the_shared_copy(self):
        allowed = sorted(wb.team.ACT_AS)[0]
        with mock.patch.object(wb, "DEFAULT_JIRA_USER", allowed):
            self.assertTrue(wb.can_build_copy())
        for who in ("", "NOT-ON-THE-LIST"):
            with mock.patch.object(wb, "DEFAULT_JIRA_USER", who):
                self.assertFalse(wb.can_build_copy())
        self.assertRegex(wb.current_copy_version(), r"^\d+(\.\d+)*$")
        p = wb.shared_copy_prompt("9.9.010199")
        self.assertIn("build_distribution.py --version 9.9.010199", p)
        self.assertIn("approved", p)

    def test_prompt_bring_to_local(self):
        story = {"key": "ACME-1", "custom": False, "summary": "s", "description": ""}
        p = wb.build_prompt(story, True, local_test=True)
        self.assertIn("Test on my PC", p)
        self.assertNotIn("Testing in Devin Cloud", p)


class ReminderTests(unittest.TestCase):
    def test_only_the_persons_own_gaps_become_reminders(self):
        gaps = [
            {"key": "ACME-1", "summary": "a", "owner": "Resource 3", "code": "no_time", "check": "In Progress with no time logged"},
            {"key": "ACME-2", "summary": "b", "owner": "Resource 3", "code": "no_due_date", "check": "In Progress 10 days with no due date"},
            {"key": "ACME-3", "summary": "c", "owner": "Someone, Else", "code": "no_time", "check": "x"},
            {"key": "ACME-4", "summary": "d", "owner": "Resource 3", "code": "story_label", "check": "label"},
        ]
        follow = {"parallel": [{"owner": "Resource 3", "stories": [{"key": "ACME-5"}, {"key": "ACME-6"}]},
                               {"owner": "Someone, Else", "stories": [{"key": "ACME-7"}, {"key": "ACME-8"}]}],
                  "idle": [{"key": "ACME-5", "summary": "e", "owner": "Resource 3", "quiet": 3, "last": "2026-10-20"}]}
        rows = wb.nudge_rows(follow, gaps, "Resource 3")
        self.assertEqual([r["id"] for r in rows],
                         ["no_time:ACME-1", "no_due_date:ACME-2", "parallel:ACME-5,ACME-6", "idle:ACME-5"])
        self.assertEqual(rows[0]["text"], "Log your hours on ACME-1")
        self.assertEqual(rows[1]["answer"], "due")
        self.assertIn("2 stories In Progress", rows[2]["text"])
        self.assertIn("3 working days", rows[3]["text"])
        self.assertEqual(wb.nudge_rows(follow, gaps, ""), [])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wb.Handler.store = wb.Store()
        wb.Handler.devin = cls.devin = FakeDevin()
        wb.Handler.jira = FakeJira()
        wb.Handler.backlog = wb.backlog.Backlog(wb.Handler.jira, tempfile.mkdtemp(prefix="sdlc-backlog-"), env={})
        wb.Handler.poller = wb.Poller(wb.Handler.store, cls.devin)
        wb.Handler.pc = pctest.PcTests(key_source=lambda: "", threaded=False)
        wb.Handler.prs = wb.CloudPrs(cls.devin, path=os.path.join(tempfile.mkdtemp(prefix="sdlc-prs-"), "prs.json"))
        wb.Handler.replies = wb.CloudReplies(cls.devin, path=os.path.join(tempfile.mkdtemp(prefix="sdlc-replies-"), "r.json"))
        wb.Handler.log_message = lambda *a: None
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), wb.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(HOME, ignore_errors=True)

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, method=method, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def jcall(self, method, path, body=None):
        code, data, _ = self.call(method, path, body)
        return code, json.loads(data)

    def test_about_gives_the_version_and_the_last_commit(self):
        code, out = self.jcall("GET", "/api/about")
        self.assertEqual(code, 200)
        self.assertRegex(out["version"], r"^\d+\.\d+")
        self.assertTrue(out["commit"] and out["commit_date"])

    def test_desktop_icon_needs_windows(self):
        with mock.patch.object(wb, "ON_WINDOWS", False):
            code, out = self.jcall("POST", "/api/desktop-icon", {})
        self.assertEqual(code, 400)
        self.assertIn("Windows", out["error"])

    def test_desktop_icon_runs_the_shortcut_script(self):
        made = mock.Mock(returncode=0, stdout="Made C:\\Users\\me\\Desktop\\Argus.lnk\n", stderr="")
        with mock.patch.object(wb, "ON_WINDOWS", True), mock.patch.object(wb.subprocess, "run", return_value=made) as run:
            code, out = self.jcall("POST", "/api/desktop-icon", {})
        self.assertEqual(code, 200)
        self.assertTrue(out["path"].endswith("Argus.lnk"))
        cmd, env = run.call_args[0][0], run.call_args[1]["env"]
        self.assertEqual(cmd[0], "powershell")
        self.assertTrue(env["TARGET"].endswith("start-workbench.cmd"))
        self.assertEqual(env["WB_ARG"], "")

    def test_desktop_icon_reports_a_powershell_failure(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="Access is denied.")
        with mock.patch.object(wb, "ON_WINDOWS", True), mock.patch.object(wb.subprocess, "run", return_value=failed):
            code, out = self.jcall("POST", "/api/desktop-icon", {})
        self.assertEqual(code, 502)
        self.assertIn("Access is denied", out["error"])

    def test_pr_state_is_checked_for_the_prs_on_sessions(self):
        url = "https://git.acme.example/projects/ACME/repos/claims-web/pull-requests/2777"
        store = wb.Handler.store
        with store.lock:
            store.runs["prpanel"] = {"id": "prpanel", "pull_requests": [{"pr_url": url}], "created_at": 0}
        try:
            code, out = self.jcall("POST", "/api/prs/refresh", {})
            self.assertEqual(code, 202)
            self.assertTrue(out["pending"])
            self.assertIn("#2777", self.devin.created[-1]["prompt"])
            self.assertEqual(self.devin.created[-1]["tags"], [wb.CLOUD_PR_TAG])
            code, out = self.jcall("POST", "/api/prs/refresh", {})
            self.assertEqual(code, 409)
            code, out = self.jcall("GET", "/api/prs")
            self.assertEqual(code, 200)
            self.assertTrue(out["pending"])
        finally:
            with store.lock:
                store.runs.pop("prpanel", None)
            wb.Handler.prs.job = None

    def test_chat_starts_a_plain_cloud_session(self):
        code, _ = self.jcall("POST", "/api/runs", {"chat": " "})
        self.assertEqual(code, 400)
        ask = "What does the TIN/NPI substitution screen check?"
        code, run = self.jcall("POST", "/api/runs", {"chat": ask})
        self.assertEqual(code, 201)
        self.assertEqual((run["kind"], run["dry_run"], run["stage"]), ("chat", False, None))
        made = self.devin.created[-1]
        self.assertEqual(made["tags"], [wb.WORKBENCH_TAG, wb.CHAT_TAG, "live"])
        self.assertIn(ask, made["prompt"])
        self.assertIn("not an SDLC run", made["prompt"])
        kind, story = wb.run_from_tags(made["tags"], made["title"])
        self.assertEqual((kind, story["summary"]), ("chat", ask))
        code, html, _ = self.call("GET", "/")
        self.assertIn(b'id="pcChat"', html)
        self.assertIn(b'id="navPcNeed"', html)

    def test_page_and_config(self):
        code, html, _ = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Argus", html)
        self.assertIn(b"drop-settings", html)
        code, cfg = self.jcall("GET", "/api/config")
        self.assertEqual(cfg["stages"], wb.STAGES)
        self.assertNotIn(SECRET, json.dumps(cfg))
        self.assertEqual(cfg["jira_via"], "here")
        self.assertIn("work_root", cfg["pc"])
        self.assertIn(b'id="navPc"', html)
        self.assertIn(b'data-fold="left"', html)
        self.assertIn(b'data-fold="right"', html)

    def test_status_is_one_call_for_runs_and_pc_tests(self):
        code, st = self.jcall("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(st["runs"], self.jcall("GET", "/api/runs")[1])
        self.assertEqual(st["pc"]["tests"], [])
        self.assertIn("devin_cli", st["pc"])

    def test_page_loads_every_script_part_in_order(self):
        code, html, _ = self.call("GET", "/")
        self.assertEqual(code, 200)
        at = [html.index(("/static/%s" % name).encode()) for name in JS_PARTS]
        self.assertEqual(at, sorted(at))
        for name in JS_PARTS:
            self.assertEqual(self.call("GET", "/static/" + name)[0], 200, name)

    def test_background_refreshes_share_one_clock_and_read_only_this_pc(self):
        js = workbench_js()
        self.assertNotIn("setInterval(loadRuns", js)
        self.assertIn('every("status", 5000, loadStatus', js)
        self.assertEqual(js.count("setInterval("), 2, "the scheduler's clock and the dashboard wait page's timer")
        self.assertNotIn("confirm(", js.replace("askConfirm(", ""))

    def test_bulk_preview_route_lists_every_ticket_and_sends_nothing(self):
        code, d = self.jcall("POST", "/api/backlog/bulk", {"keys": ["ACME-90201", "ACME-90202"], "field": "points", "value": "3", "user": "dev.user"})
        self.assertEqual(code, 200)
        self.assertEqual(d["status"], "draft")
        self.assertEqual(len(d["lines"]), 2)
        code, p = self.jcall("GET", "/api/backlog/previews")
        self.assertEqual(p["previews"], [])
        self.assertTrue(p["browse"].endswith("/browse/"))

    def test_quick_search_shortcuts_tour_help_and_saved_views_are_wired(self):
        js = workbench_js()
        code, html, _ = self.call("GET", "/")
        for name in ("openQuick", "listMove", "maybeTour", "refreshAgo", "runUpdates", "gateOverdue", "openSent", "sdlc-blviews", "/api/backlog/bulk"):
            self.assertIn(name, js)
        for el in (b'id="qsModal"', b'id="keysModal"', b'id="sentModal"', b'id="tourBox"', b'id="blBulkField"', b'id="blViews"', b"data-helpfor="):
            self.assertIn(el, html)

    def test_page_items_ask_first_and_the_picked_person_stays_after_a_reload(self):
        js = workbench_js()
        self.assertIn("openPanel(it.opens, it.label)", js)
        self.assertIn("sdlc-jira-me-start", js)
        self.assertIn("state.user = keep ? picked : (start || picked);", js)

    def test_only_act_as_people_can_switch_the_workbench_user(self):
        js = workbench_js()
        self.assertIn('if (!c.can_switch) { state.user = start; $("whoSel").closest("label").hidden = true; }', js)
        saved = wb.DEFAULT_JIRA_USER
        try:
            wb.DEFAULT_JIRA_USER = ""
            self.assertTrue(wb.can_switch_user())
            wb.DEFAULT_JIRA_USER = "NOBODY1"
            self.assertFalse(wb.can_switch_user())
            wb.DEFAULT_JIRA_USER = (wb.team.ACT_AS or ["X"])[0].lower()
            self.assertEqual(wb.can_switch_user(), bool(wb.team.ACT_AS))
        finally:
            wb.DEFAULT_JIRA_USER = saved

    def test_pc_routes(self):
        code, pc = self.jcall("GET", "/api/pc")
        self.assertEqual(code, 200)
        self.assertEqual(pc["tests"], [])
        code, err = self.jcall("POST", "/api/pc", {"ticket": "ACME-1", "branch": "devin/x",
                                                   "session": "https://x/sessions/" + "ab" * 16})
        self.assertEqual(code, 400)
        self.assertIn("API key", err["error"])
        code, err = self.jcall("GET", "/api/pc/0123456789ab")
        self.assertEqual(code, 404)
        code, err = self.jcall("GET", "/api/pc/lookup?ticket=nope")
        self.assertEqual(code, 400)
        code, err = self.jcall("POST", "/api/key", {"key": "short"})
        self.assertEqual(code, 400)
        self.assertNotIn("short", err["error"])

    def test_me_and_role_preview(self):
        _, me = self.jcall("GET", "/api/me?user=" + ME)
        self.assertEqual(me["role"]["id"], "solution_lead")
        self.assertFalse(me["previewing"])
        self.assertEqual(me["role"]["layout"]["list"], "sprint")
        _, me = self.jcall("GET", "/api/me?user=%s&role=bsa" % ME)
        self.assertEqual(me["role"]["id"], "bsa")
        self.assertEqual(me["role"]["layout"], wb.load_layouts()["bsa"])
        self.assertTrue(me["previewing"])
        self.assertEqual(len(me["all_roles"]), len(wb.load_roles()))
        _, me = self.jcall("GET", "/api/me?user=&role=not_a_role")
        self.assertIsNone(me["role"])

    def test_jira_errors_are_reported_not_fatal(self):
        code, body = self.jcall("GET", "/api/stories?scope=mine")
        self.assertEqual(code, 400)
        self.assertIn("Pick who you are", body["error"])
        code, body = self.jcall("GET", "/api/stories?scope=sprint")
        self.assertEqual(code, 503)
        self.assertIn("not retrying", body["error"])
        self.assertEqual(self.call("GET", "/")[0], 200)

    def test_a_direct_jira_read_says_when_it_was_read(self):
        code, body = self.jcall("GET", "/api/stories?scope=waiting&user=AM1")
        self.assertEqual((code, body["stories"]), (200, []))
        self.assertGreater(body["fetched_at"], 0)

    def test_menu_action_forward_wake_and_bundle(self):
        code, _ = self.jcall("POST", "/api/actions", {"skill": "../../etc"})
        self.assertEqual(code, 400)
        code, run = self.jcall("POST", "/api/actions", {"skill": "kb-refresh", "text": "after 26.4"})
        self.assertEqual(code, 201)
        tags = self.devin.created[-1]["tags"]
        self.assertEqual(tags, [wb.WORKBENCH_TAG, "action", "kb-refresh", "dry-run"])
        self.assertIn("attachments do not reach it", self.devin.created[-1]["prompt"])
        rid = run["id"]
        code, body = self.jcall("GET", "/api/runs/" + rid)
        self.assertEqual(body["skill"]["skill"], "kb-refresh")
        self.assertEqual(body["story"]["input"], "after 26.4")
        code, body = self.jcall("POST", "/api/runs/%s/forward" % rid, {"person": ME, "note": "x"})
        self.assertEqual(code, 400)   # no open gate
        stored = wb.Handler.store.runs[rid]
        stored["pending_gate"] = {"id": "SDLC_04_ROUTING_APPROVAL", "text": "..."}
        wb.Handler.backlog.subtasks = lambda k: [{"key": k}, {"key": "ACME-90210"}]
        code, body = self.jcall("POST", "/api/runs/%s/forward" % rid, {"person": "someone-else", "note": "x"})
        self.assertEqual(code, 400)   # not on the roster
        code, body = self.jcall("POST", "/api/runs/%s/forward" % rid, {"person": ME, "note": ""})
        self.assertEqual(code, 400)   # note required
        code, body = self.jcall("POST", "/api/runs/%s/forward" % rid, {"person": ME, "note": "routing check"})
        self.assertEqual(code, 200)
        self.assertTrue(self.devin.sent[-1][1].startswith("/send-approval SDLC_04_ROUTING_APPROVAL to " + ME))
        self.assertEqual(stored["forwarded"][-1]["person"], ME)
        self.assertIsNotNone(stored["pending_gate"])   # still waiting for the real sign-off
        stored["status"] = "suspended"
        code, _ = self.jcall("POST", "/api/runs/%s/wake" % rid, {})
        self.assertEqual(code, 200)
        self.assertEqual(stored["status"], "resume_requested")
        stored["artefacts"] = [{"name": "REQ-1-SPEC.md", "detail": "ready", "body": "# Spec", "at": "t"}]
        stored["diffs"] = [{"path": "a/b.py", "why": "w", "body": "+x", "at": "t"}]
        code, data, headers = self.call("GET", "/api/runs/%s/bundle.zip" % rid)
        self.assertEqual(code, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertIn("artefacts/REQ-1-SPEC.md", names)
        self.assertIn("diffs/a_b.py.diff", names)
        code, data, headers = self.call("GET", "/api/runs/%s/trace.txt" % rid)
        self.assertEqual(code, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("-trace.txt", headers["Content-Disposition"])
        self.assertIn(b"INTAKE \xc2\xb7 agent: intake (BSA)", data)
        self.assertEqual(self.call("GET", "/api/runs/ffffffffffff/trace.txt")[0], 404)

    def test_required_input_and_result_pages(self):
        code, body = self.jcall("POST", "/api/actions", {"skill": "investigate", "text": ""})
        self.assertEqual(code, 400)
        self.assertIn("your question", body["error"])
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation"})
        self.assertEqual(code, 201)
        code, html, _ = self.call("GET", "/run/" + run["id"])
        self.assertEqual(code, 200)
        self.assertIn(b"/static/run.js", html)
        code, html, headers = self.call("GET", "/repo-file?path=sdlc/framework/ARCHITECTURE.html")
        self.assertEqual(code, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(self.call("GET", "/repo-file?path=../../etc/passwd")[0], 400)

    def test_onboarding_page_loads_when_the_folder_is_missing(self):
        gone = "web/no-such-folder/onboarding"
        with mock.patch.object(wb.gen_reference_pages, "KB_DIR", gone), mock.patch.object(wb, "_git_branch", return_value=None):
            self.assertEqual(wb.repo_list(gone), [])
            code, html, _ = self.call("GET", "/page/onboarding")
        self.assertEqual(code, 200)
        self.assertIn(b"No onboarding guides are written yet", html)
        self.assertIn(b"/onboarding-guide", html)

    def test_config_keeps_configured_apart_from_connected(self):
        wb.HEALTH.forget("jira")
        wb.HEALTH.forget("devin")
        _, cfg = self.jcall("GET", "/api/config")
        self.assertTrue(cfg["jira_configured"])
        self.assertTrue(cfg["devin_configured"])
        self.assertFalse(cfg["jira_ok"])
        self.assertEqual(cfg["integrations"]["jira"]["state"], "not_checked")
        wb.HEALTH.fail("jira", "Cannot reach jira.example from this box")
        wb.HEALTH.ok("devin")
        _, h = self.jcall("GET", "/api/health")
        self.assertEqual(h["jira"]["state"], "failing")
        self.assertIn("Cannot reach", h["jira"]["error"])
        self.assertTrue(h["devin"]["connected"])
        self.assertNotIn(SECRET, json.dumps(h))
        wb.HEALTH.forget("jira")
        wb.HEALTH.forget("devin")

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_reference_pages_open_without_a_session(self):
        started = len(self.devin.created)
        for name, needle in (("help", b"User Manual"), ("catalogue", b"Catalogue"),
                             ("onboarding", b"onboarding guides"), ("presentation", b"Architecture"),
                             ("delivery-teams", b"TechNinjas")):
            code, html, headers = self.call("GET", "/page/" + name)
            self.assertEqual(code, 200, name)
            self.assertIn("text/html", headers["Content-Type"])
            self.assertIn(needle, html)
            self.assertIn(b"no Devin session", html)
        self.assertIn(b'data-wb-skill="onboarding-guide"', self.call("GET", "/page/onboarding")[1])
        onboarding = wb.gen_reference_pages.render("onboarding", wb.gen_reference_pages.Checkout())
        access = onboarding.split('id="tab-access"')[1].split("</section>")[0]
        self.assertIn("Raise your access requests", access)
        self.assertNotIn("data-wb-skill", access)
        self.assertEqual(self.call("GET", "/page/nope")[0], 404)
        self.assertEqual(len(self.devin.created), started)
        code, html, headers = self.call("GET", "/repo-file?path=sdlc/framework/USER-MANUAL.md")
        self.assertEqual(code, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"<table", html)
        self.assertNotIn(b"| Command |", html)

    def test_team_insights_decks_page(self):
        started = len(self.devin.created)
        self.assertEqual(wb.skill_info("team-insights")["opens"], "/page/team-insights")
        code, html, _ = self.call("GET", "/page/team-insights")
        self.assertEqual(code, 200)
        self.assertIn(b"Team Insights decks", html)
        self.assertIn(b'data-wb-skill="team-insights"', html)
        self.assertIn(b"no Devin session", html)
        self.assertEqual(len(self.devin.created), started)

    def test_menu_items_say_what_a_click_does(self):
        self.assertEqual(wb.skill_info("presentation")["opens"], "/page/presentation")
        self.assertEqual(wb.skill_info("onboarding-guide")["opens"], "/page/onboarding")
        self.assertEqual(wb.skill_info("document-validation")["opens"], "/validation")
        self.assertEqual(wb.skill_info("investigate")["opens"], "")
        self.assertTrue(wb.skill_info("help")["read_only"])
        self.assertFalse(wb.skill_info("kb-refresh")["read_only"])

    def test_same_request_reopens_the_recent_answer(self):
        code, first = self.jcall("POST", "/api/actions", {"skill": "impact-radar", "text": "ACME-1", "dry_run": False})
        self.assertEqual(code, 201)
        started = len(self.devin.created)
        code, again = self.jcall("POST", "/api/actions", {"skill": "impact-radar", "text": "ACME-1", "dry_run": False})
        self.assertEqual((code, again["id"], again["reused"]), (200, first["id"], True))
        self.assertEqual(len(self.devin.created), started)
        code, fresh = self.jcall("POST", "/api/actions",
                                 {"skill": "impact-radar", "text": "ACME-1", "dry_run": False, "fresh": True})
        self.assertEqual(code, 201)
        self.assertNotEqual(fresh["id"], first["id"])

    def test_sessions_are_told_the_person_and_role_picked(self):
        def prompts():
            return [c["prompt"] for c in self.devin.created] + [m[1] for m in self.devin.sent]
        code, own = self.jcall("POST", "/api/actions", {"skill": "impact-radar", "text": "ACME-2", "user": ME})
        self.assertEqual(code, 201)
        self.assertTrue(any("Requester: " in t and "(%s)" % ME in t and "Solution lead" in t for t in prompts()))
        code, auto = self.jcall("POST", "/api/actions",
                                {"skill": "impact-radar", "text": "ACME-2", "user": ME, "role": "automation_engineer"})
        self.assertEqual(code, 201)
        self.assertNotEqual(auto["id"], own["id"])
        self.assertTrue(any("in the role Automation engineer (picked under View Argus as)" in t for t in prompts()))
        code, run = self.jcall("POST", "/api/runs", {"text": "Add a contract export button to the grid", "user": ME,
                                                     "role": "qa_staff"})
        self.assertEqual(code, 201)
        self.assertIn("in the role %s" % wb.load_roles()["qa_staff"]["label"], self.devin.created[-1]["prompt"])

    def test_automation_role_lists_its_own_tickets(self):
        self.assertIn("automation", wb.PERSONAL_SCOPES)
        self.assertEqual(wb.list_name("automation", ME), "automation-" + ME)
        self.assertEqual(wb.list_name("automation_open", ME), "automation_open")
        with open(os.path.join(wb.ROOT, ".devin", "rules", "dashboard-roles.yaml"), encoding="utf-8") as fh:
            m = re.search(r"\n  automation_queue:\n(?:    .*\n)*?    jql: >-\n((?:      .*\n)+)", fh.read())
        self.assertEqual(" ".join(m.group(1).split()).replace('"{user}"', '"%s"'), wb.JQL["automation"])

    def test_generated_documents_open_as_pages(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "what-if", "text": "drop PMC", "fresh": True})
        stored = wb.Handler.store.runs[run["id"]]
        stored["artefacts"] = [{"name": "NOTES.md", "body": "# Notes\n\n| a | b |\n|---|---|\n| <x> | 2 |", "at": "t"}]
        code, html, headers = self.call("GET", "/view/%s/0" % run["id"])
        self.assertEqual(code, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"<td>&lt;x&gt;</td>", html)
        self.assertEqual(self.call("GET", "/view/%s/5" % run["id"])[0], 404)

    def test_committed_reference_pages_match_their_sources(self):
        self.assertEqual(wb.gen_reference_pages.main(["--check"]), 0,
                         "run sdlc/framework/tools/gen_reference_pages.py and commit reference/")

    def test_validation_form_and_answers(self):
        code, html, _ = self.call("GET", "/validation")
        self.assertEqual(code, 200)
        self.assertIn(b'id="wb-send"', html)
        self.assertIn(b'id="build"', html)
        code, _ = self.jcall("POST", "/api/validation/answers", {"answers": "hello"})
        self.assertEqual(code, 400)
        block = "# SDLC-KB-VALIDATION-ANSWERS v1\nanswers:\n  - id: Q-1\n    decision: accept\n"
        code, run = self.jcall("POST", "/api/validation/answers", {"answers": block})
        self.assertEqual(code, 201)
        made = self.devin.created[-1]
        self.assertIn("/document-validation apply these answers", made["prompt"])
        self.assertIn("decision: accept", made["prompt"])
        self.assertIn("dry-run", made["tags"])

    def test_page_ids_are_unique(self):
        html = open(os.path.join(os.path.dirname(wb.__file__), "static", "index.html"), encoding="utf-8").read()
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(sorted({i for i in ids if ids.count(i) > 1}), [])

    def test_team_chat_needs_devin_cloud(self):
        old, wb.Handler.poker = wb.Handler.poker, None
        try:
            code, out = self.jcall("GET", "/api/poker/chat?user=resource3")
            self.assertEqual(code, 409)
            code, out = self.jcall("POST", "/api/poker/chat/send", {"user": "resource3", "to": "resource3", "text": "hi"})
            self.assertEqual(code, 409)
        finally:
            wb.Handler.poker = old

    def test_reminders_need_the_service_account_read(self):
        code, out = self.jcall("GET", "/api/waiting/nudges?user=resource3")
        self.assertEqual(code, 200)
        self.assertIn("could not be read", out["note"])
        live = wb.Handler.backlog
        cloud = type("CloudRead", (), {"via": "cloud", "token": ""})()
        wb.Handler.backlog = wb.backlog.Backlog(cloud, tempfile.mkdtemp(prefix="sdlc-backlog-"), env={})
        try:
            code, out = self.jcall("GET", "/api/waiting/nudges?user=resource3")
        finally:
            wb.Handler.backlog = live
        self.assertEqual(code, 200)
        self.assertFalse(out["available"])
        self.assertIn("service account", out["note"])
        code, out = self.jcall("POST", "/api/waiting/nudge-answer", {"user": "resource3", "key": "ACME-1", "due": "2026-11-01"})
        self.assertEqual(code, 404)

    def test_save_is_a_dry_run_unless_the_tick_is_off(self):
        block = "SDLC-DASHBOARD-WORKBENCH-CONFIG v1\n- person: resource3 | test_on_pc: off\nEND"
        code, _ = self.jcall("POST", "/api/blocks", {"block": block, "user": "resource3"})
        self.assertEqual(code, 201)
        self.assertIn("dry-run", self.devin.created[-1]["tags"])
        code, _ = self.jcall("POST", "/api/blocks", {"block": block, "user": "resource3", "dry_run": False, "fresh": True})
        self.assertEqual(code, 201)
        self.assertIn("live", self.devin.created[-1]["tags"])

    def test_a_solution_leads_real_save_is_the_approval(self):
        block = "SDLC-DASHBOARD-GATE-CONFIG v1\n- gate: DB_02_DISCOVERY_VALIDATION | resource3: none\nEND"
        code, _ = self.jcall("POST", "/api/blocks", {"block": block, "user": "resource3", "dry_run": False, "fresh": True})
        self.assertEqual(code, 201)
        self.assertIn("pressing Save is their approval", self.devin.created[-1]["prompt"])
        code, _ = self.jcall("POST", "/api/blocks", {"block": block, "user": "resource3", "dry_run": True, "fresh": True})
        self.assertNotIn("pressing Save is their approval", self.devin.created[-1]["prompt"])
        self.assertIn("Wait for the requester's `approved`", self.devin.created[-1]["prompt"])

    def test_feedback_form_sends_the_session_details_the_workbench_has(self):
        run = wb.Handler.store.new_run({"key": "ACME-77", "summary": "Contract dates"}, True,
                                       {"session_id": "devin-fb", "url": "https://example.invalid/fb"})
        run.update(stage="design", status="blocked", error="Jira could not be reached",
                   messages=[{"event_id": "e1", "source": "devin", "text": "Waiting on the design gate"}])
        code, out = self.jcall("GET", "/api/feedback?user=resource3&run=%s&story=ACME-77&page=run" % run["id"])
        self.assertEqual(code, 200)
        ctx = out["context"]
        self.assertEqual((ctx["page"], ctx["ticket"]), ("run", "ACME-77"))
        mine = [r for r in ctx["runs"] if r["this_one"]][0]
        self.assertEqual((mine["session"], mine["stage"], mine["error"]),
                         ("https://example.invalid/fb", "design", "Jira could not be reached"))
        self.assertEqual(mine["last_devin"], "Waiting on the design gate")
        self.assertIn("jira", ctx["status_light"])
        code, out = self.jcall("POST", "/api/feedback", {"user": "resource3", "run": run["id"], "kind": "problem",
                                                         "about": "Argus page", "text": "It stopped after design"})
        self.assertEqual(code, 201)
        self.assertTrue(out["run"])
        prompt = self.devin.created[-1]["prompt"]
        self.assertIn(wb.observer.BLOCK + " v1", prompt)
        self.assertIn("It stopped after design", prompt)
        self.assertIn("https://example.invalid/fb", prompt)
        self.assertIn("no approval or review", prompt)
        self.assertIn("git merge --no-ff", prompt)
        self.assertEqual(wb.OBSERVER.pending, [])
        code, out = self.jcall("POST", "/api/feedback", {"user": "resource3", "text": "  "})
        self.assertEqual(code, 400)

    def test_the_workbench_notes_its_own_errors(self):
        self.jcall("POST", "/api/observe", {"detail": "TypeError: x is undefined at console.js:12", "page": "run"})
        self.jcall("GET", "/api/runs/nosuchrun")
        seen = {n["where"]: n for n in wb.OBSERVER.recent(1)}
        self.assertEqual(seen["screen"]["title"], "The page broke (a script error)")
        self.assertIn("api", seen)

    def test_sync_adopts_only_my_tagged_sessions(self):
        me = wb.find_person(ME)
        self.devin.listed = [
            {"session_id": "devin-a", "tags": [wb.WORKBENCH_TAG, "ACME-7", "dry-run"], "title": "SDLC dry run ACME-7 — x",
             "requesting_user_email": me["email"], "created_at": "2026-09-01T10:00:00Z", "status_enum": "finished"},
            {"session_id": "devin-b", "tags": [wb.WORKBENCH_TAG, "ACME-8", "live"], "title": "SDLC run ACME-8 — y",
             "requesting_user_email": "someone.else@example.invalid", "created_at": "2026-09-01T10:00:00Z"},
            {"session_id": "devin-c", "tags": ["unrelated"], "requesting_user_email": me["email"]},
        ]
        code, _ = self.jcall("POST", "/api/sync", {})
        self.assertEqual(code, 200)
        code, body = self.jcall("POST", "/api/sync", {"user": ME})
        self.assertEqual(body["added"], 1)
        code, body = self.jcall("POST", "/api/sync", {"user": ME})
        self.assertEqual(body["added"], 0)
        adopted = [r for r in wb.Handler.store.runs.values() if r["session_id"] == "devin-a"][0]
        self.assertEqual(adopted["story"]["key"], "ACME-7")
        self.assertTrue(adopted["dry_run"])

    def test_return_to_cloud_opens_the_cloud_session_as_a_run(self):
        sid = "devin-" + "cd" * 16
        code, _ = self.jcall("POST", "/api/runs/open", {"session": "not a session"})
        self.assertEqual(code, 400)
        code, run = self.jcall("POST", "/api/runs/open",
                               {"session": "https://x.invalid/sessions/" + "cd" * 16, "ticket": "acme-17735"})
        self.assertEqual(code, 200, run)
        self.assertEqual((run["session_id"], run["story"]["key"]), (sid, "ACME-17735"))
        code, again = self.jcall("POST", "/api/runs/open", {"session": sid})
        self.assertEqual(again["id"], run["id"])
        code, body = self.jcall("GET", "/api/runs/" + run["id"])
        self.assertEqual(code, 200)

    def test_reply_wait_starts_on_send_and_ends_with_devins_answer(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "explain-capability", "text": "x", "fresh": True})
        self.assertEqual(code, 201)
        stored = wb.Handler.store.runs[run["id"]]
        code, _ = self.jcall("POST", "/api/runs/%s/message" % run["id"], {"text": "and the PR?"})
        self.assertEqual(code, 200)
        self.assertTrue(stored.get("sent_at"))
        self.jcall("GET", "/api/runs/" + run["id"])
        self.assertTrue(stored.get("watched_at"))
        reply = [{"event_id": "r-live", "created_at": "t", "source": "devin", "message": "PR is open."}]
        with mock.patch.object(self.devin, "messages", return_value=reply):
            wb.Handler.poller.refresh(run["id"])
        self.assertNotIn("sent_at", stored)

    def test_runs_list_carries_devins_latest_reply_for_notifications(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "explain-capability", "text": "x", "fresh": True})
        self.assertEqual(code, 201)
        stored = wb.Handler.store.runs[run["id"]]
        wb.apply_message(stored, {"event_id": "n1", "created_at": "t", "source": "devin", "message": "First\n  answer"})
        wb.apply_message(stored, {"event_id": "n2", "created_at": "t", "source": "user", "message": "thanks"})
        code, runs = self.jcall("GET", "/api/runs")
        self.assertEqual(code, 200)
        row = next(r for r in runs if r["id"] == run["id"])
        self.assertEqual(row["last_reply"], {"event_id": "n1", "text": "First answer"})
        self.assertNotIn("messages", row)
        self.assertFalse(row["complete"])

    def test_runs_list_marks_a_finished_sdlc_run_complete(self):
        wb.Handler.store.runs["c0mp1e7e"] = wb.migrate_run({
            "id": "c0mp1e7e", "kind": "sdlc", "created_at": 1, "status": "blocked", "stage": "kb-refresh",
            "stages": {s: "done" for s in wb.STAGES}, "events": [], "messages": [], "pending_gate": None,
            "pending_questions": None, "artefacts": [], "diffs": [], "pr": None, "session_id": None})
        self.addCleanup(wb.Handler.store.runs.pop, "c0mp1e7e", None)
        code, runs = self.jcall("GET", "/api/runs")
        self.assertEqual(code, 200)
        self.assertTrue(next(r for r in runs if r["id"] == "c0mp1e7e")["complete"])

    def test_pc_history_lists_the_evidence_each_pc_sent_to_the_cloud_session(self):
        sent = ("[SDLC] evidence REQ-TRIAL STORY-2 97b9c16940a5 passed=%d failed=%d not_run=0\n"
                "Tested on LD8X3VV3 by k@example.invalid, %s. PR head matched at %s.\n"
                "Verify with: python3 sdlc/framework/tools/evidence.py verify x.zip --commit <PR head>\n"
                "https://app.example/attachments/a1/evidence-REQ-TRIAL-STORY-2-97b9c16940a5.zip")
        msgs = [
            {"event_id": "e1", "created_at": "c1", "source": "user", "message": sent % (4, 1, "2026-10-02T20:00:00Z", "x")},
            {"event_id": "e2", "created_at": "c2", "source": "user", "message": sent % (5, 0, "2026-10-03T01:43:55Z", "x")},
            {"event_id": "e3", "created_at": "c3", "source": "devin",
             "message": "Run 3 is back: [SDLC] evidence REQ-TRIAL STORY-2 97b9c16940a5 passed=5 failed=0 not_run=0"},
            {"event_id": "e4", "created_at": "c4", "source": "user", "message": "[SDLC] control cloud"},
            {"event_id": "e5", "created_at": "c5", "source": "user",
             "message": (sent % (5, 0, "2026-10-03T01:43:55Z", "x")).rsplit("\n", 1)[0]},
        ]
        with mock.patch.object(self.devin, "session", return_value={}) as got, \
                mock.patch.object(self.devin, "messages", return_value=msgs):
            code, body = self.jcall("GET", "/api/pc/history?session=https://app.example/sessions/" + "a" * 32)
        self.assertEqual(code, 200)
        got.assert_called_once_with("devin-" + "a" * 32)
        self.assertEqual([(r["event_id"], r["passed"], r["failed"]) for r in body["runs"]], [("e2", 5, 0), ("e1", 4, 1)])
        run = body["runs"][0]
        self.assertEqual((run["machine"], run["tested_by"], run["tested_at"], run["commit"]),
                         ("LD8X3VV3", "k@example.invalid", "2026-10-03T01:43:55Z", "97b9c16940a5"))
        self.assertTrue(run["zip"].endswith("97b9c16940a5.zip"))
        code, _ = self.jcall("GET", "/api/pc/history?session=nope")
        self.assertEqual(code, 400)

    def test_post_to_jira_asks_the_cloud_session_once(self):
        sent = ("[SDLC] evidence REQ-TRIAL STORY-2 97b9c16940a5 passed=5 failed=0 not_run=0\n"
                "Tested on LD8X3VV3 by k@example.invalid, 2026-10-03T01:43:55Z. PR head matched.\n"
                "https://app.example/attachments/a1/e.zip")
        msgs = [{"event_id": "e1", "created_at": "c1", "source": "user", "message": sent}]
        sid = "a" * 32
        url = "https://jira.example/browse/ACME-17735?focusedCommentId=9"
        with mock.patch.object(self.devin, "session", return_value={}), \
                mock.patch.object(self.devin, "messages", return_value=msgs), \
                mock.patch.object(self.devin, "send") as send:
            code, _ = self.jcall("POST", "/api/pc/history/jira", {"session": sid, "event_id": "e1", "ticket": "REQ-1-STORY-1"})
            self.assertEqual(code, 400)
            code, _ = self.jcall("POST", "/api/pc/history/jira", {"session": sid, "event_id": "nope", "ticket": "ACME-17735"})
            self.assertEqual(code, 404)
            code, body = self.jcall("POST", "/api/pc/history/jira", {"session": sid, "event_id": "e1", "ticket": "acme-17735"})
            self.assertEqual((code, body["ticket"]), (200, "ACME-17735"))
            self.assertEqual(send.call_args[0][0], "devin-" + sid)
            ask = send.call_args[0][1]
        self.assertTrue(ask.startswith("[SDLC] post-to-jira e1 ACME-17735\n"))
        self.assertIn("5 passed, 0 failed, 0 not run", ask)
        self.assertIn("https://app.example/attachments/a1/e.zip", ask)
        self.assertNotIn("[SDLC] evidence", ask)
        msgs += [{"event_id": "e2", "created_at": "c2", "source": "user", "message": ask},
                 {"event_id": "e3", "created_at": "c3", "source": "devin", "message": "Added.\n[SDLC] jira-comment e1 " + url}]
        with mock.patch.object(self.devin, "session", return_value={}), \
                mock.patch.object(self.devin, "messages", return_value=msgs), \
                mock.patch.object(self.devin, "send") as send:
            code, body = self.jcall("GET", "/api/pc/history?session=" + sid)
            self.assertEqual([r["event_id"] for r in body["runs"]], ["e1"])
            self.assertEqual(body["runs"][0]["jira"], {"ticket": "ACME-17735", "url": url})
            code, _ = self.jcall("POST", "/api/pc/history/jira", {"session": sid, "event_id": "e1", "ticket": "ACME-17735"})
            self.assertEqual(code, 409)
            send.assert_not_called()

    def test_menu_action_closes_itself_once_answered(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "explain-capability", "text": "attribution", "fresh": True})
        self.assertEqual(code, 201)
        self.assertIn("closes this session", self.devin.created[-1]["prompt"])
        stored = wb.Handler.store.runs[run["id"]]
        sid = stored["session_id"]
        wb.apply_message(stored, {"event_id": "q", "created_at": "t", "source": "devin",
                                  "message": "[SDLC] skill explain-capability — started\n[SDLC] question round 1 — started\n"
                                             "1. Which program?"})
        wb.Handler.poller.refresh(run["id"])
        self.assertNotIn(sid, self.devin.terminated)   # still waiting on an answer
        stored["pending_questions"] = None
        wb.apply_message(stored, {"event_id": "f", "created_at": "t", "source": "devin",
                                  "message": "Attribution is ...\n[SDLC] skill explain-capability — finished"})
        wb.Handler.poller.refresh(run["id"])
        self.assertIn(sid, self.devin.terminated)
        self.assertIn("closed", self.devin.tagged[sid])
        self.assertIn("action", self.devin.tagged[sid])
        _, body = self.jcall("GET", "/api/runs/" + run["id"])
        self.assertTrue(body["closed_at"])
        self.assertFalse(wb.due(stored, stored["closed_at"] + 10 ** 6))

    def test_menu_items_and_chats_share_one_assistant_session_a_day(self):
        store, devin = wb.Handler.store, self.devin
        with mock.patch.object(wb, "SHARED_ASSISTANT", True), mock.patch.object(wb, "DEFAULT_JIRA_USER", "user4"):
            made = len(devin.created)
            code, a = self.jcall("POST", "/api/actions", {"skill": "explain-capability", "text": "one", "fresh": True})
            self.assertEqual(code, 201)
            self.assertEqual(len(devin.created), made + 1)
            first = devin.created[-1]
            self.assertIn(wb.ASSISTANT_TAG, first["tags"])
            self.assertIn("[SDLC] request %s" % a["id"], first["prompt"])
            code, b = self.jcall("POST", "/api/runs", {"chat": "what is attribution?"})
            self.assertEqual(code, 201)
            self.assertEqual(len(devin.created), made + 1)
            self.assertEqual(b["session_id"], a["session_id"])
            self.assertTrue(devin.sent[-1][1].startswith("[SDLC] request %s\n" % b["id"]))
            msgs = [{"event_id": "1", "source": "user", "message": first["prompt"]},
                    {"event_id": "2", "source": "devin", "message": "[SDLC] reply %s\nAnswer one" % a["id"]},
                    {"event_id": "3", "source": "user", "message": devin.sent[-1][1]},
                    {"event_id": "4", "source": "devin", "message": "[SDLC] reply %s\nAnswer two" % b["id"]}]
            self.assertEqual([m["event_id"] for m in wb.own_messages(msgs, a["id"])], ["1", "2"])
            self.assertEqual([m["event_id"] for m in wb.own_messages(msgs, b["id"])], ["3", "4"])
            run = store.runs[a["id"]]
            wb.apply_message(run, msgs[1])
            self.assertEqual(run["messages"][-1]["text"], "Answer one")
            run["events"].append({"kind": "skill", "name": "x", "detail": "finished"})
            run["status"] = "blocked"
            wb.Handler.poller.close(a["id"])
            self.assertNotIn(a["session_id"], devin.terminated)
            self.jcall("POST", "/api/runs/%s/delete" % b["id"], {})
            self.assertNotIn(b["session_id"], devin.terminated)
            self.assertNotIn(b["id"], store.runs)

    def test_long_assistant_session_moves_to_a_new_one_with_a_handover(self):
        store, devin = wb.Handler.store, self.devin
        with mock.patch.object(wb, "SHARED_ASSISTANT", True), mock.patch.object(wb, "DEFAULT_JIRA_USER", "user5"), \
                mock.patch.object(wb, "LONG_SESSION", 3):
            code, a = self.jcall("POST", "/api/runs", {"chat": "first question"})
            self.assertEqual(code, 201)
            self.assertFalse(a["long_session"])
            run = store.runs[a["id"]]
            for i in range(3):
                run["messages"].append({"event_id": "m%d" % i, "source": "devin", "text": "answer %d" % i})
            code, got = self.jcall("GET", "/api/runs/%s" % a["id"])
            self.assertTrue(got["long_session"])
            made = len(devin.created)
            code, b = self.jcall("POST", "/api/runs", {"chat": "second question"})
            self.assertEqual(len(devin.created), made + 1)
            self.assertNotEqual(b["session_id"], a["session_id"])
            self.assertIn("Handover: this carries on from the earlier session", devin.created[-1]["prompt"])
            self.assertIn("answer 2", devin.created[-1]["prompt"])
            code, c = self.jcall("POST", "/api/runs/%s/fresh" % b["id"], {"text": "carry on"})
            self.assertEqual(code, 201)
            self.assertEqual(len(devin.created), made + 2)
            self.assertNotEqual(c["session_id"], b["session_id"])
            self.assertEqual(c["fresh_from"], b["id"])
            code, d = self.jcall("POST", "/api/actions", {"skill": "sdlc", "text": "REQ-001", "fresh": True})
            self.assertEqual(code, 201)
            self.assertEqual(len(devin.created), made + 3)
            self.assertFalse(store.runs[d["id"]].get("assistant"))

    def test_reject_at_a_gate_closes_the_run(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation", "text": "reject", "fresh": True})
        rid = run["id"]
        stored = wb.Handler.store.runs[rid]
        stored["pending_gate"] = {"id": "SDLC_01_INTAKE_CLARIFICATION", "text": "..."}
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid, {"decision": "reject", "note": "scope too wide"})
        self.assertEqual(code, 200)
        self.assertTrue(body["closed"])
        self.assertEqual(body["sent"], "rejected SDLC_01_INTAKE_CLARIFICATION — scope too wide")
        self.assertTrue(stored.get("closed_at"))
        self.assertIsNone(stored["pending_gate"])

    def test_approve_at_a_gate_keeps_the_run_open(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation", "text": "approve", "fresh": True})
        rid = run["id"]
        stored = wb.Handler.store.runs[rid]
        stored["pending_gate"] = {"id": "SDLC_01_INTAKE_CLARIFICATION", "text": "..."}
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid, {"decision": "approve"})
        self.assertEqual(code, 200)
        self.assertNotIn("closed", body)
        self.assertFalse(stored.get("closed_at"))

    def test_items_one_rejected_item_rejects_and_closes(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation", "text": "items", "fresh": True})
        rid = run["id"]
        stored = wb.Handler.store.runs[rid]
        stored["pending_gate"] = {"id": "SDLC_02_GAP_ANALYSIS_REVIEW", "text": "...",
                                  "items": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}, {"n": 3, "text": "c"}, {"n": 4, "text": "d"}]}
        url = "/api/runs/%s/gate" % rid
        code, body = self.jcall("POST", url, {"decision": "items", "items": [
            {"n": 1, "decision": "approve"}, {"n": 2, "decision": "approve"}, {"n": 3, "decision": "reject", "note": "gap missing"}]})
        self.assertEqual(code, 400)   # item 4 not decided yet
        code, body = self.jcall("POST", url, {"decision": "items", "items": [
            {"n": 1, "decision": "approve"}, {"n": 2, "decision": "approve"}, {"n": 3, "decision": "reject"}, {"n": 4, "decision": "approve"}]})
        self.assertEqual(code, 400)   # a rejected item needs reasons
        self.assertFalse(stored.get("closed_at"))
        code, body = self.jcall("POST", url, {"decision": "items", "items": [
            {"n": 1, "decision": "approve"}, {"n": 2, "decision": "approve"},
            {"n": 3, "decision": "reject", "note": "gap missing"}, {"n": 4, "decision": "approve"}]})
        self.assertEqual(code, 200)
        self.assertEqual(body["sent"], "rejected SDLC_02_GAP_ANALYSIS_REVIEW — approved 1,2,4; rejected 3 — gap missing")
        self.assertTrue(body["closed"])
        self.assertTrue(stored.get("closed_at"))

    def test_items_all_approved_moves_on(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation", "text": "items ok", "fresh": True})
        rid = run["id"]
        stored = wb.Handler.store.runs[rid]
        stored["pending_gate"] = {"id": "SDLC_02_GAP_ANALYSIS_REVIEW", "text": "...",
                                  "items": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}]}
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid, {"decision": "items", "items": [
            {"n": 1, "decision": "approve"}, {"n": 2, "decision": "approve", "note": "fine"}]})
        self.assertEqual(code, 200)
        self.assertEqual(body["sent"], "approved SDLC_02_GAP_ANALYSIS_REVIEW — approved 1,2; notes: 2: fine")
        self.assertNotIn("closed", body)
        self.assertIsNone(stored["pending_gate"])

    def test_subtasks_at_the_gate_before_coding(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation", "text": "subs", "fresh": True})
        rid = run["id"]
        stored = wb.Handler.store.runs[rid]
        stored["story"] = {"key": "ACME-90201", "custom": False, "summary": "s"}
        rows = [{"summary": "DEV- Backend implementation", "hours": "4"}, {"summary": "DEV- Unit tests", "hours": 1}]
        stored["pending_gate"] = {"id": "SDLC_02_SPEC_SIGNOFF", "text": "..."}
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid, {"decision": "approve", "subtasks": rows})
        self.assertEqual(code, 400)   # only at the gate before coding
        stored["pending_gate"] = {"id": "SDLC_04_ROUTING_APPROVAL", "text": "..."}
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid,
                                {"decision": "approve", "subtasks": [{"summary": "DEV- Backend", "hours": ""}]})
        self.assertEqual(code, 400)   # every sub-task needs an original estimate
        self.assertIsNotNone(stored["pending_gate"])
        stored["dry_run"] = False
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid,
                                {"decision": "approve", "subtasks": rows, "assignee": ME, "user": ME})
        self.assertEqual(code, 200)
        sent = self.devin.sent[-1][1]
        self.assertTrue(sent.startswith("approved SDLC_04_ROUTING_APPROVAL"))
        self.assertIn("confirmed this Jira write", sent)
        self.assertIn("- DEV- Backend implementation | 4h", sent)
        self.assertIn("(5h in total)", sent)
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid, {"decision": "approve", "subtasks": [
            {"key": "ACME-90210", "summary": "DEV- Backend", "hours": 2, "description": "server.py: add route"}]})
        self.assertEqual(code, 400)   # gate already answered above
        stored["pending_gate"] = {"id": "SDLC_04_ROUTING_APPROVAL", "text": "..."}
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid, {"decision": "approve", "subtasks": [
            {"key": "ACME-90210", "summary": "DEV- Backend", "hours": 2, "description": "server.py: add route"}]})
        self.assertEqual(code, 200, body)
        self.assertIn("- ACME-90210 ← DEV- Backend | 2h\n  server.py: add route", self.devin.sent[-1][1])
        stored["artefacts"] = [{"name": "ACME-90201-SUBTASK-PLAN.json", "detail": "ready", "body": json.dumps({
            "story": "ACME-90201", "subtasks": [{"key": "", "summary": "DEV- Backend", "hours": 4, "description": "d"},
                                                {"summary": " "}]})}]
        code, body = self.jcall("GET", "/api/runs/" + rid)
        self.assertEqual(body["subtask_plan"], [{"key": "", "summary": "DEV- Backend", "hours": "4", "description": "d",
                                                 "change": ""}])
        stored["artefacts"][0]["body"] = "not json"
        self.assertEqual(wb.subtask_plan(stored), [])
        self.assertEqual((stored["subtasks"]["key"], stored["subtasks"]["via"]), ("ACME-90201", "session"))
        stored["dry_run"] = True
        stored["pending_gate"] = {"id": "HOTFIX_PLAN_CODE", "text": "..."}
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid, {"decision": "approve", "subtasks": rows})
        self.assertEqual(code, 200)
        self.assertIn("Do not write them to Jira", self.devin.sent[-1][1])
        stored["story"] = {"key": "REQ-1", "custom": True, "summary": "s"}
        stored["pending_gate"] = {"id": "SDLC_04_ROUTING_APPROVAL", "text": "..."}
        code, body = self.jcall("POST", "/api/runs/%s/gate" % rid, {"decision": "approve", "subtasks": rows})
        self.assertEqual(code, 400)   # no Jira story yet

    def test_jira_reader_says_it_is_machine_only(self):
        prompt = wb.cloud_reader_prompt(["sprint"], "user4", "abcd1234")
        self.assertIn("machine-only", prompt)
        self.assertIn("RESERVED", wb.CLOUD_READER_TITLE)

    def test_automation_step_lines_set_the_stepper(self):
        run = {"kind": "action", "story": {"action": "acme-auto-story"}, "events": [], "messages": [], "seen": [],
               "stages": {}, "pending_questions": None, "pending_gate": None, "artefacts": [], "diffs": [], "pr": None}
        text = "\n".join(["[SDLC] step scan — done", "[SDLC] step gate1 — waiting for you",
                          "[SDLC] step write — started", "[SDLC] step run — done: 3/4 passed",
                          "[SDLC] step setup — failed: app did not start"])
        wb.apply_message(run, {"event_id": "s1", "created_at": "t", "source": "devin", "message": text})
        self.assertEqual(run["steps"], {"scan": "done", "gate1": "waiting", "write": "running",
                                        "run": "done", "setup": "blocked"})

    def test_sdlc_runs_are_not_closed_automatically(self):
        run = {"kind": "sdlc", "status": "blocked", "events": [{"kind": "skill", "name": "x", "detail": "finished"}]}
        self.assertFalse(wb.answered(run))
        run["kind"] = "action"
        self.assertTrue(wb.answered(run))
        run["status"] = "working"
        self.assertFalse(wb.answered(run))
        run["status"], run["pending_gate"] = "blocked", {"id": "SDLC_01"}
        self.assertFalse(wb.answered(run))

    def test_close_buttons(self):
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation", "text": "kb", "fresh": True})
        sid = wb.Handler.store.runs[run["id"]]["session_id"]
        code, body = self.jcall("POST", "/api/runs/%s/close" % run["id"], {})
        self.assertEqual(code, 200)
        self.assertTrue(body["closed_at"])
        self.assertIn(sid, self.devin.terminated)
        self.assertEqual(self.jcall("POST", "/api/sessions/close", {"session_ids": ["../x"]})[0], 400)
        code, body = self.jcall("POST", "/api/sessions/close", {"session_ids": ["a" * 32]})
        self.assertEqual(code, 200)
        self.assertEqual(body["closed"], ["devin-" + "a" * 32])

    def test_delete_ends_the_session_and_the_run_never_comes_back(self):
        store = wb.Handler.store
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation", "text": "delete me", "fresh": True})
        sid = store.runs[run["id"]]["session_id"]
        code, body = self.jcall("POST", "/api/runs/%s/delete" % run["id"], {})
        self.assertEqual((code, body["session_id"]), (200, sid))
        self.assertNotIn(run["id"], store.runs)
        self.assertIn(sid, self.devin.terminated)
        self.assertIn(wb.DELETED_TAG, self.devin.tagged[sid])
        self.assertNotIn(run["id"], [r["id"] for r in self.jcall("GET", "/api/runs")[1]])
        self.assertEqual(store.adopt([{"session_id": sid, "tags": [wb.WORKBENCH_TAG, "live"], "title": "x"}]), 0)
        self.assertEqual(store.adopt([{"session_id": "devin-" + "e" * 32, "title": "x",
                                       "tags": [wb.WORKBENCH_TAG, wb.DELETED_TAG, "live"]}]), 0)
        self.assertIn(sid, wb.Store().deleted)
        self.assertEqual(self.jcall("POST", "/api/runs/%s/delete" % run["id"], {})[0], 404)

    def test_delete_keeps_the_run_when_the_session_cannot_be_ended(self):
        store = wb.Handler.store
        code, run = self.jcall("POST", "/api/actions", {"skill": "presentation", "text": "keep me", "fresh": True})
        with mock.patch.object(self.devin, "terminate", side_effect=wb.ApiError(500, "Devin is down")):
            code, body = self.jcall("POST", "/api/runs/%s/delete" % run["id"], {})
        self.assertEqual(code, 502)
        self.assertIn("nothing was deleted", body["error"])
        self.assertIn(run["id"], store.runs)

    def test_roster_page_lists_everyone(self):
        started = len(self.devin.created)
        code, html, _ = self.call("GET", "/page/roster")
        self.assertEqual(code, 200)
        for person in wb.load_roster():
            self.assertIn(wb.artifact_kit.esc(person["name"]).encode(), html)
        self.assertIn(b'data-wb-skill="roster-check"', html)
        self.assertEqual(len(self.devin.created), started)
        self.assertEqual(wb.skill_info("roster-check")["opens"], "/page/roster")


    def test_wrap_up_asks_cloud_then_moves_jira_only_to_an_offered_transition(self):
        sid, t, msgs = "b" * 32, "ACME-17735", []
        q = "/api/pc/wrapup?session=%s&ticket=%s" % (sid, t)
        with mock.patch.object(self.devin, "session", return_value={}), \
                mock.patch.object(self.devin, "messages", side_effect=lambda info: list(msgs)), \
                mock.patch.object(self.devin, "send") as send:
            self.assertEqual(self.jcall("GET", "/api/pc/wrapup?session=%s&ticket=REQ-1" % sid)[0], 400)
            code, body = self.jcall("GET", q)
            self.assertEqual((code, body["asked"], body["session"]), (200, False, "devin-" + sid))
            self.assertEqual(self.jcall("POST", "/api/pc/wrapup/jira", {"session": sid, "ticket": t, "transition": "41"})[0], 409)
            code, _ = self.jcall("POST", "/api/pc/wrapup", {"session": sid, "ticket": "acme-17735"})
            self.assertEqual(code, 200)
            ask = send.call_args[0][1]
            self.assertTrue(ask.startswith("[SDLC] wrap-up-check ACME-17735\n"))
            self.assertIn("/rest/api/2/issue/ACME-17735/transitions", ask)
            self.assertNotIn("[SDLC] evidence", ask)
            msgs.append({"event_id": "w1", "source": "user", "message": ask})
            self.assertEqual(self.jcall("POST", "/api/pc/wrapup", {"session": sid, "ticket": t})[0], 409)
            self.assertEqual(self.jcall("GET", q)[1]["verdict"], "")
            msgs.append({"event_id": "w2", "source": "devin", "message":
                         "Evidence 5/0/0, PR #2779 open, nothing waiting.\n[SDLC] wrap-up ACME-17735 ready all checks passed\n"
                         "[SDLC] jira-next ACME-17735 41=Ready for Review|51=Ready for Testing"})
            body = self.jcall("GET", q)[1]
            self.assertEqual((body["verdict"], body["reason"]), ("ready", "all checks passed"))
            self.assertEqual(body["transitions"], [{"id": "41", "name": "Ready for Review"}, {"id": "51", "name": "Ready for Testing"}])
            self.assertEqual(self.jcall("POST", "/api/pc/wrapup/jira", {"session": sid, "ticket": t, "transition": "99"})[0], 400)
            code, body = self.jcall("POST", "/api/pc/wrapup/jira", {"session": sid, "ticket": t, "transition": "41"})
            self.assertEqual((code, body["transition"]["name"]), (200, "Ready for Review"))
            move = send.call_args[0][1]
            self.assertTrue(move.startswith("[SDLC] jira-move ACME-17735 41\n"))
            self.assertIn('{"transition": {"id": "41"}}', move)
            msgs.append({"event_id": "w3", "source": "user", "message": move})
            self.assertEqual(self.jcall("POST", "/api/pc/wrapup/jira", {"session": sid, "ticket": t, "transition": "51"})[0], 409)
            self.assertEqual(self.jcall("GET", q)[1]["move"], {"id": "41", "name": "Ready for Review", "status": ""})
            msgs.append({"event_id": "w4", "source": "devin", "message": "Done.\n[SDLC] jira-moved ACME-17735 Ready for Review"})
            self.assertEqual(self.jcall("GET", q)[1]["move"]["status"], "Ready for Review")
            self.assertEqual(send.call_count, 2)

    def test_archive_hides_a_session_keeps_its_tags_and_never_ends_it(self):
        store, sid = wb.Handler.store, "devin-" + "c" * 32
        with store.lock:
            store.runs["archme"] = {"id": "archme", "session_id": sid, "created_at": 0}
        try:
            with mock.patch.object(self.devin, "session", return_value={"tags": [wb.WORKBENCH_TAG, "live"]}):
                code, body = self.jcall("POST", "/api/sessions/archive", {"session": sid})
            self.assertEqual((code, body["archived"]), (200, True))
            self.assertEqual(self.devin.tagged[sid], sorted([wb.WORKBENCH_TAG, "live", wb.ARCHIVED_TAG]))
            self.assertTrue(store.runs["archme"]["archived"])
            with mock.patch.object(self.devin, "session", return_value={"tags": self.devin.tagged[sid]}):
                self.jcall("POST", "/api/sessions/archive", {"session": sid, "archived": False})
            self.assertEqual(self.devin.tagged[sid], sorted([wb.WORKBENCH_TAG, "live"]))
            self.assertFalse(store.runs["archme"]["archived"])
            self.assertNotIn(sid, self.devin.terminated)
            self.assertEqual(self.jcall("POST", "/api/sessions/archive", {"session": "x"})[0], 400)
            with mock.patch.object(self.devin, "session", return_value={"tags": [wb.WORKBENCH_TAG]}):
                self.jcall("POST", "/api/sessions/close", {"session_ids": [sid]})
            self.assertEqual(self.devin.tagged[sid], sorted([wb.CLOSED_TAG, wb.WORKBENCH_TAG]))
            other = "devin-" + "d" * 32
            store.adopt([{"session_id": other, "tags": [wb.WORKBENCH_TAG, wb.ARCHIVED_TAG, "live", "ACME-1"],
                          "title": "ACME-1", "created_at": "2026-10-01T00:00:00Z"}])
            self.assertTrue(next(r for r in store.runs.values() if r.get("session_id") == other)["archived"])
        finally:
            with store.lock:
                for k in [k for k, r in store.runs.items() if r.get("session_id") in (sid, "devin-" + "d" * 32)]:
                    del store.runs[k]


class WrapUpStateTests(unittest.TestCase):
    def test_only_cloud_answers_after_the_newest_check_count(self):
        t = "ACME-1"
        ask = {"source": "user", "message": pctest.wrapup_request(t, "https://jira.example")}
        early = {"source": "devin", "message": "[SDLC] wrap-up ACME-1 ready too early"}
        other = {"source": "devin", "message": "[SDLC] wrap-up ACME-2 ready\n[SDLC] jira-next ACME-2 1=Done"}
        no = {"source": "devin", "message": "[SDLC] wrap-up ACME-1 not-ready SDLC_06 is not signed"}
        self.assertEqual(pctest.wrapup_state([early], t)["verdict"], "")
        st = pctest.wrapup_state([early, ask, other, no], t)
        self.assertEqual((st["asked"], st["verdict"], st["reason"], st["transitions"]), (True, "not-ready", "SDLC_06 is not signed", []))
        move = {"source": "user", "message": "[SDLC] jira-move ACME-1 5"}
        self.assertEqual(pctest.wrapup_state([ask, no, move], t)["move"], {})
        self.assertEqual(pctest.wrapup_state([ask, no, ask], t)["verdict"], "")

class FakeCloudDevin(FakeDevin):
    def __init__(self, reply="", status="blocked", payload=None):
        super().__init__()
        self.reply, self.status, self.payload, self.downloads = reply, status, payload, []

    def session(self, devin_id):
        msgs = [{"type": "devin_message", "message": self.reply, "event_id": "e1"}] if self.reply else []
        return {"status_enum": self.status, "messages": msgs}

    messages = staticmethod(wb.Devin.messages)

    def download(self, attachment_id, name):
        self.downloads.append((attachment_id, name))
        return json.dumps(self.payload).encode()


PR_URL = "https://git.acme.example/projects/ACME/repos/claims-web/pull-requests/%d"


class WaitingTasksTests(unittest.TestCase):
    Q = {"key": "ACME-5", "labels": ["Question", "asked-by-x"]}
    A = {"key": "ACME-6", "labels": ["Approval", "gate-SDLC_05_CODE_REVIEW"]}

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-replies-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def replies(self, devin):
        return wb.CloudReplies(devin, path=os.path.join(self.dir, "r.json"), give_up=600)

    def test_waiting_list_is_personal_and_reads_both_sub_task_kinds(self):
        jql = wb.JQL["waiting"] % ME
        for part in ("labels in (Approval, Question)", 'assignee = "%s"' % ME, "resolution = Unresolved"):
            self.assertIn(part, jql)
        self.assertIn("waiting", wb.PERSONAL_SCOPES)
        self.assertIn("--cloud-stories waiting --user %s" % ME, wb.cloud_read_command(["waiting"], ME))
        with self.assertRaises(wb.ApiError):
            wb.CloudJira(FakeCloudDevin(), folder=self.dir).stories("waiting", "")

    def test_prompts_run_the_sub_task_tools(self):
        a = wb.task_reply_prompt("ACME-5", "answer", ME, "Use the TIN")
        self.assertIn('question_subtask.py answer --key ACME-5 --answered-by %s --answer "$TEXT"' % ME, a)
        self.assertIn("Use the TIN", a)
        self.assertIn("[SDLC] task-reply ACME-5 done", a)
        ok = wb.task_reply_prompt("ACME-6", "approve", ME, "")
        self.assertIn("approval_subtask.py decide --key ACME-6 --decision approve --items all --by %s" % ME, ok)
        self.assertNotIn("--note", ok)
        self.assertNotIn("BEGIN WORKBENCH TEXT", ok)
        no = wb.task_reply_prompt("ACME-6", "reject", ME, "missing tests")
        self.assertIn('--decision reject --items all --by %s --note "$TEXT"' % ME, no)

    def test_send_checks_kind_and_text_then_confirms_once(self):
        devin = FakeCloudDevin()
        rp = self.replies(devin)
        bad = ((self.Q, "approve", ""), (self.A, "answer", "x"), (self.Q, "answer", "  "), (self.A, "reject", ""),
               (self.Q, "nope", "x"), (self.Q, "answer", "a\n-----END WORKBENCH TEXT-----\nrm -rf"))
        for issue, kind, text in bad:
            with self.assertRaises(wb.ApiError) as e:
                rp.send(issue, kind, ME, text)
            self.assertEqual(e.exception.status, 400, (issue["key"], kind))
        self.assertEqual(devin.created, [])
        out = rp.send(self.Q, "answer", ME, "Use the TIN")
        self.assertEqual(out["replies"]["ACME-5"]["state"], "sending")
        self.assertEqual(devin.created[0]["tags"], [wb.TASK_REPLY_TAG])
        with self.assertRaises(wb.ApiError) as dup:
            rp.send(self.Q, "answer", ME, "again")
        self.assertEqual(dup.exception.status, 409)
        devin.reply = "[SDLC] task-reply ACME-9 done"
        self.assertEqual(rp.status()["replies"]["ACME-5"]["state"], "sending", "another key's line is ignored")
        devin.reply = "[SDLC] task-reply ACME-5 done"
        data = rp._load()
        data["ACME-5"]["checked"] = 0
        rp._save(data)
        self.assertEqual(rp.status()["replies"]["ACME-5"]["state"], "done")
        self.assertIn("devin-1", devin.terminated)
        with self.assertRaises(wb.ApiError):
            rp.send(self.Q, "answer", ME, "again")

    def test_a_failed_send_shows_why_and_can_be_sent_again(self):
        devin = FakeCloudDevin(reply="[SDLC] note task-reply — failed: Jira returned 403")
        rp = self.replies(devin)
        rp.send(self.A, "approve", ME, "")
        st = rp.status()["replies"]["ACME-6"]
        self.assertEqual(st["state"], "failed")
        self.assertIn("403", st["error"])
        rp.send(self.A, "approve", ME, "")
        self.assertEqual(len(devin.created), 2)

    def test_http_only_for_sub_tasks_in_your_list(self):
        class J:
            token = SECRET

            def stories(self, scope, user=""):
                assert scope == "waiting"
                return {"stories": [dict(WaitingTasksTests.Q, url="u")] if user == ME else []}

        old = (wb.Handler.jira, getattr(wb.Handler, "replies", None))
        wb.Handler.jira = J()
        wb.Handler.replies = self.replies(FakeCloudDevin())
        wb.Handler.log_message = lambda *a: None
        srv = ThreadingHTTPServer(("127.0.0.1", 0), wb.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]

        def call(method, path, body=None):
            req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                         data=json.dumps(body).encode() if body is not None else None)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            self.assertEqual(call("POST", "/api/waiting/reply", {"user": "a b", "key": "ACME-5", "kind": "answer", "text": "x"})[0], 400)
            self.assertEqual(call("POST", "/api/waiting/reply", {"user": "someone", "key": "ACME-5", "kind": "answer", "text": "x"})[0], 404)
            self.assertEqual(call("POST", "/api/waiting/reply", {"user": ME, "key": "ACME-5", "kind": "approve"})[0], 400)
            code, out = call("POST", "/api/waiting/reply", {"user": ME, "key": "ACME-5", "kind": "answer", "text": "Use the TIN"})
            self.assertEqual((code, out["replies"]["ACME-5"]["state"]), (200, "sending"))
            code, out = call("GET", "/api/waiting/replies")
            self.assertEqual((code, out["replies"]["ACME-5"]["kind"]), (200, "answer"))
        finally:
            srv.shutdown()
            wb.Handler.jira, wb.Handler.replies = old


class CloudPrsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-cloudprs-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def prs(self, devin):
        return wb.CloudPrs(devin, path=os.path.join(self.dir, "prs.json"), give_up=600)

    def test_pr_links_from_the_devin_api(self):
        self.assertEqual(wb.pr_link({"url": PR_URL % 2776}), {"pr_url": PR_URL % 2776})
        self.assertEqual(wb.pr_link({"pr_url": PR_URL % 1}), {"pr_url": PR_URL % 1})
        self.assertEqual(wb.pr_number(PR_URL % 2776), 2776)
        self.assertIsNone(wb.pr_number("https://example.invalid/x"))

    def test_states_arrive_from_cloud_and_session_is_closed(self):
        devin = FakeCloudDevin()
        cp = self.prs(devin)
        with self.assertRaises(wb.ApiError) as no_prs:
            cp.refresh([])
        self.assertEqual(no_prs.exception.status, 400)
        out = cp.refresh([2776, 2775, 2776])
        self.assertTrue(out["pending"])
        prompt = devin.created[0]["prompt"]
        self.assertIn("#2775, #2776", prompt)
        self.assertIn("git_view_pr", prompt)
        self.assertIn("don't merge, approve, decline", prompt)
        with self.assertRaises(wb.ApiError) as busy:
            cp.refresh([2776])
        self.assertEqual(busy.exception.status, 409)
        devin.reply = ("[SDLC] pr-state 2775 merged devin/a -> feature/devin-sdlc\n"
                       "[SDLC] pr-state 2776 open devin/b -> feature/devin-sdlc\n"
                       "[SDLC] pr-state 9 declined x -> y")
        cp.job["checked"] = 0
        out = cp.status()
        self.assertFalse(out["pending"])
        self.assertEqual(out["error"], "")
        self.assertEqual(out["prs"]["2775"]["state"], "merged")
        self.assertEqual(out["prs"]["2776"]["from"], "devin/b")
        self.assertNotIn("9", out["prs"], "only the PRs that were asked about")
        self.assertIn("devin-1", devin.terminated)
        self.assertEqual(self.prs(devin).status()["prs"]["2776"]["state"], "open", "cached across restarts")

    def test_partial_answer_waits_while_cloud_works_then_names_the_missing(self):
        devin = FakeCloudDevin(status="working")
        cp = self.prs(devin)
        cp.refresh([1, 2])
        devin.reply = "[SDLC] pr-state 1 declined"
        cp.job["checked"] = 0
        self.assertTrue(cp.status()["pending"])
        devin.status = "blocked"
        cp.job["checked"] = 0
        out = cp.status()
        self.assertFalse(out["pending"])
        self.assertEqual(out["prs"]["1"]["state"], "declined")
        self.assertIn("#2", out["error"])

    def test_session_ending_without_answer_is_an_error(self):
        devin = FakeCloudDevin(status="exit")
        cp = self.prs(devin)
        out = cp.refresh([5])
        self.assertFalse(out["pending"])
        self.assertIn("stopped without an answer", out["error"])
        self.assertEqual(out["prs"], {})


class CloudJiraTests(unittest.TestCase):
    ATT = "https://example.invalid/attachments/0123abcd-0123-4567-89ab-0123456789ab/"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-cloudjira-")
        self.day = "2026-10-04"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def jira(self, devin):
        return wb.CloudJira(devin, folder=self.dir, ttl=600, today=lambda: self.day)

    def reply(self, cj, devin, *names):
        devin.reply = "\n".join("[SDLC] attachment stories-%s.%s.json — %sstories-%s.%s.json" % (
            n, cj.pending[n], self.ATT, n, cj.pending[n]) for n in names)
        cj.checked = 0

    def test_no_token_and_list_arrives_from_cloud(self):
        story = {"key": "ACME-7", "summary": "Seven", "description": "d7"}
        devin = FakeCloudDevin(payload={"jql": "q", "stories": [story]})
        cj = self.jira(devin)
        self.assertIsNone(cj.token)
        first = cj.stories("sprint")
        self.assertTrue(first["pending"])
        self.assertEqual(first["stories"], [])
        self.assertEqual(len(devin.created), 1)
        self.assertIn("--cloud-stories sprint --req %s" % cj.pending["sprint"], devin.created[0]["prompt"])
        self.assertIn("Never retry", devin.created[0]["prompt"])
        self.assertIn("Jira reader for today", devin.created[0]["prompt"])
        self.assertEqual(devin.created[0]["title"], "RESERVED – do not type · Argus Jira reader · team lists · 2026-10-04")
        self.assertEqual(devin.created[0]["tags"], [wb.CLOUD_JIRA_TAG])
        cj.stories("sprint")
        self.assertEqual(len(devin.created), 1, "one Cloud read at a time per list")
        self.reply(cj, devin, "sprint")
        out = cj.stories("sprint")
        self.assertFalse(out["pending"])
        self.assertEqual(out["source"], "cloud")
        self.assertEqual(out["stories"][0]["key"], "ACME-7")
        self.assertTrue(devin.downloads[0][1].startswith("stories-sprint."))
        self.assertEqual(devin.terminated, [], "the reader stays open for the next read today")
        self.assertEqual(cj.story("ACME-7")["description"], "d7")
        self.assertEqual(cj.story("ACME-99")["key"], "ACME-99")
        cj.stories("sprint")
        self.assertEqual(len(devin.created), 1, "a fresh cached list is not fetched again")
        cj.stories("sprint", refresh=True)
        self.assertEqual(len(devin.created), 1, "Check now asks the same session")
        self.assertEqual(devin.sent[0][0], "devin-1")
        self.assertIn("--cloud-stories sprint --req %s" % cj.pending["sprint"], devin.sent[0][1])

    def test_new_day_closes_yesterdays_reader_and_opens_one(self):
        devin = FakeCloudDevin(payload={"jql": "q", "stories": []})
        cj = self.jira(devin)
        cj.stories("sprint")
        self.reply(cj, devin, "sprint")
        cj.stories("sprint")
        self.day = "2026-10-05"
        cj.stories("sprint")
        self.assertIn("devin-1", devin.terminated, "yesterday's reader is closed")
        self.assertIn(wb.CLOSED_TAG, devin.tagged["devin-1"])
        self.assertEqual(len(devin.created), 1, "the cached list is still fresh, so no new reader yet")
        cj.stories("sprint", refresh=True)
        self.assertEqual(len(devin.created), 2)
        self.assertIn("2026-10-05", devin.created[1]["title"])
        self.assertEqual(cj.reader()["session_id"], "devin-2")

    def test_list_is_kept_until_refresh(self):
        devin = FakeCloudDevin(payload={"jql": "q", "stories": [{"key": "ACME-8"}]})
        cj = wb.CloudJira(devin, folder=self.dir, today=lambda: self.day)
        self.assertEqual(cj.ttl, 0)
        cj.stories("backlog")
        self.reply(cj, devin, "backlog")
        cj.stories("backlog")
        with open(cj._path("backlog"), encoding="utf-8") as fh:
            data = json.load(fh)
        data["fetched_at"] -= 86400 * 3
        with open(cj._path("backlog"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        out = cj.stories("backlog")
        self.assertFalse(out["pending"], "an old list is not read again by itself")
        self.assertEqual(out["stories"][0]["key"], "ACME-8")
        self.assertEqual(len(devin.created) + len(devin.sent), 1)
        self.assertTrue(cj.stories("backlog", refresh=True)["pending"])
        self.assertEqual(len(devin.created) + len(devin.sent), 2)

    def test_personal_lists_come_in_one_read(self):
        devin = FakeCloudDevin(payload={"jql": "q", "stories": [{"key": "ACME-5"}]})
        cj = self.jira(devin)
        cj.stories("waiting", ME)
        self.assertIn("--cloud-stories waiting,%s --user %s --req" % (",".join(s for s in wb.PERSONAL_SCOPES if s != "waiting"), ME), devin.created[0]["prompt"])
        self.assertIn(ME, devin.created[0]["title"])
        self.assertTrue(cj.stories("mine", ME)["pending"])
        self.assertEqual(len(devin.created) + len(devin.sent), 1)
        self.reply(cj, devin, *[wb.list_name(s, ME) for s in wb.PERSONAL_SCOPES])
        for scope in wb.PERSONAL_SCOPES:
            out = cj.stories(scope, ME)
            self.assertFalse(out["pending"])
            self.assertEqual(out["stories"][0]["key"], "ACME-5")
        self.assertEqual(len(devin.created) + len(devin.sent), 1)

    def test_an_old_reads_attachment_is_not_taken_for_a_new_read(self):
        devin = FakeCloudDevin(payload={"jql": "q", "stories": []})
        cj = self.jira(devin)
        cj.stories("sprint")
        devin.reply = "[SDLC] attachment stories-sprint.0000aaaa.json — %sstories-sprint.0000aaaa.json" % self.ATT
        cj.checked = 0
        self.assertTrue(cj.stories("sprint")["pending"])
        self.assertEqual(devin.downloads, [])

    def test_cloud_failure_is_shown_and_not_retried(self):
        devin = FakeCloudDevin()
        cj = self.jira(devin)
        cj.stories("open")
        devin.reply = "[SDLC] note jira-read %s — failed: Jira returned 401" % cj.pending["open"]
        cj.checked = 0
        out = cj.stories("open")
        self.assertIn("401", out["error"])
        cj.stories("open")
        self.assertEqual(len(devin.created) + len(devin.sent), 1, "a failed read waits for an explicit refresh")

    def test_an_ended_reader_is_replaced(self):
        devin = FakeCloudDevin()
        cj = self.jira(devin)
        cj.stories("open")
        devin.status = "exit"
        cj.checked = 0
        self.assertIn("stopped", cj.stories("open")["error"])
        devin.status = "blocked"
        cj.stories("open", refresh=True)
        self.assertEqual(len(devin.created), 2)
        self.assertEqual(devin.sent, [])

    def test_mine_needs_a_user(self):
        with self.assertRaises(wb.ApiError):
            self.jira(FakeCloudDevin()).stories("mine", "")
        with self.assertRaises(wb.ApiError):
            self.jira(FakeCloudDevin()).stories("mine", "a b")

    def test_mine_this_sprint(self):
        jql = wb.JQL["mine_sprint"] % ME
        self.assertIn('assignee = "%s"' % ME, jql)
        self.assertIn("sprint in openSprints()", jql)
        self.assertIn("--cloud-stories mine_sprint --user %s" % ME, wb.cloud_read_command(["mine_sprint"], ME))
        with self.assertRaises(wb.ApiError):
            self.jira(FakeCloudDevin()).stories("mine_sprint", "")

    def test_qa_and_uat_lists_match_the_dashboard_queues(self):
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(wb.__file__)), "..", "..", "..", ".devin", "rules", "dashboard-roles.yaml")
        rules = open(path).read()
        for scope, queue in (("qa", "test_queue"), ("uat", "uat_queue")):
            block = rules.split("\n  %s:\n" % queue, 1)[1]
            panel = " ".join(block.split("jql: >-", 1)[1].split("columns:", 1)[0].split())
            self.assertEqual(wb.JQL[scope], wb.team.fill_statuses(panel, wb.team.PROFILE))
            self.assertNotIn("--user", wb.cloud_read_command([scope]))

    def test_cloud_stories_uploads_the_lists(self):
        class J:
            def __init__(self):
                self.args = []

            def stories(self, scope, user, with_description=False):
                self.args.append((scope, user, with_description))
                return {"jql": "q", "stories": []}

        class D:
            def upload(self, path, name):
                with open(path) as fh:
                    self.body = json.load(fh)
                return "https://example.invalid/attachments/x/" + name

        j, d = J(), D()
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            self.assertEqual(wb.cloud_stories("waiting,mine", ME, "0123abcd", jira=j, devin=d, out_dir=self.dir), 0)
        self.assertEqual(j.args, [("waiting", ME, True), ("mine", ME, True)])
        lines = buf.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("[SDLC] attachment stories-waiting-%s.0123abcd.json" % ME))
        self.assertTrue(lines[1].startswith("[SDLC] attachment stories-mine-%s.0123abcd.json" % ME))
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(wb.cloud_stories("nope", ME, jira=j, devin=d, out_dir=self.dir), 1)
            self.assertEqual(wb.cloud_stories("sprint", "", "x; rm", jira=j, devin=d, out_dir=self.dir), 1)

    def test_story_create_goes_to_the_session(self):
        handler = wb.Handler.__new__(wb.Handler)
        note = handler._cloud_story_request({"assignee": ME})
        self.assertIn("[SDLC] note jira-create", note)
        self.assertIn(ME, note)
        with self.assertRaises(wb.ApiError):
            wb.CloudJira(FakeDevin(), folder=self.dir).create_story("s", "d", "a", ME, [])


class CloudDashboardTests(unittest.TestCase):
    ATT = "https://example.invalid/attachments/0123abcd-0123-4567-89ab-0123456789ab/dashboard-%s.html" % ME

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-clouddash-")
        self.out = os.path.join(self.dir, "dashboard.html")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_dashboard_arrives_from_cloud_and_the_session_is_closed(self):
        class D(FakeCloudDevin):
            def download(self, attachment_id, name):
                self.downloads.append((attachment_id, name))
                return b"<html>dash</html>"

        devin = D(reply="[SDLC] attachment dashboard-%s.html — %s" % (ME, self.ATT))
        wb.dashboard_through_cloud(devin, ME, "solution_lead", self.out, sleep=lambda s: None)
        prompt = devin.created[0]["prompt"]
        self.assertIn("--cloud-dashboard --user %s --lens solution_lead" % ME, prompt)
        self.assertIn("Never retry Jira", prompt)
        self.assertEqual(devin.created[0]["tags"], [wb.CLOUD_DASHBOARD_TAG])
        with open(self.out) as fh:
            self.assertEqual(fh.read(), "<html>dash</html>")
        self.assertIn("devin-1", devin.terminated)
        self.assertFalse(wb.DASHBOARD_BUILD.locked())

    def test_cloud_failure_is_reported_and_the_session_is_closed(self):
        devin = FakeCloudDevin(reply="[SDLC] note dashboard — failed: Jira returned 401")
        with self.assertRaises(wb.ApiError) as ctx:
            wb.dashboard_through_cloud(devin, ME, "", self.out, sleep=lambda s: None)
        self.assertIn("401", str(ctx.exception))
        self.assertIn("devin-1", devin.terminated)
        self.assertFalse(os.path.exists(self.out))

    def test_a_session_that_ends_without_the_page_is_an_error(self):
        devin = FakeCloudDevin(status="exit")
        with self.assertRaises(wb.ApiError):
            wb.dashboard_through_cloud(devin, ME, "", self.out, sleep=lambda s: None)
        self.assertFalse(wb.DASHBOARD_BUILD.locked())

    def test_one_build_at_a_time(self):
        with wb.DASHBOARD_BUILD:
            with self.assertRaises(wb.ApiError) as ctx:
                wb.dashboard_through_cloud(FakeCloudDevin(), ME, "", self.out, sleep=lambda s: None)
        self.assertEqual(ctx.exception.status, 409)

    def test_cloud_side_builds_and_uploads_the_page(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            with open(cmd[cmd.index("-o") + 1], "w") as fh:
                fh.write("<html></html>")
            return mock.Mock(returncode=0, stdout="", stderr="")

        class D:
            def upload(self, path, name):
                self.name = name
                return "https://example.invalid/attachments/x/" + name

        d, buf = D(), io.StringIO()
        with mock.patch("sys.stdout", buf):
            self.assertEqual(wb.cloud_dashboard(ME, "developer", devin=d, out_dir=self.dir, run=run), 0)
        self.assertEqual(calls[0][calls[0].index("--user") + 1], ME)
        self.assertEqual(calls[0][-2:], ["--lens", "developer"])
        self.assertTrue(buf.getvalue().startswith("[SDLC] attachment dashboard-%s.html" % ME))

        failed = mock.Mock(return_value=mock.Mock(returncode=1, stdout="", stderr="Jira returned 401"))
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            self.assertEqual(wb.cloud_dashboard(ME, "", devin=d, out_dir=self.dir, run=failed), 1)
            self.assertEqual(wb.cloud_dashboard("a b", "", devin=d, out_dir=self.dir, run=failed), 1)
        self.assertIn("401", err.getvalue())


if __name__ == "__main__":
    unittest.main()


class TraceTreeTests(unittest.TestCase):
    """The Trace tab is built only from the [SDLC] lines the session printed."""

    def test_only_a_presented_gate_opens_the_gate_card(self):
        presented = ("[SDLC] gate SDLC_01_INTAKE_CLARIFICATION — presented\n**Gate SDLC_01**\n"
                     "Reply starting with `approved` or `rejected`.")
        self.assertEqual(wb.parse_devin_message(presented)[2]["id"], "SDLC_01_INTAKE_CLARIFICATION")
        for detail in ("rejected", "approved", "signed"):
            text = ("[SDLC] gate SDLC_01_INTAKE_CLARIFICATION — %s\nTo move on, reply "
                    "`approved SDLC_01_INTAKE_CLARIFICATION`, or say what to change." % detail)
            self.assertIsNone(wb.parse_devin_message(text)[2], detail)
        plain = "Gate SDLC_02_GAP_ANALYSIS_REVIEW is ready. Reply approved or rejected."
        self.assertEqual(wb.parse_devin_message(plain)[2]["id"], "SDLC_02_GAP_ANALYSIS_REVIEW")

    def test_gate_items_come_from_the_presented_gate(self):
        text = ("[SDLC] gate SDLC_02_GAP_ANALYSIS_REVIEW — presented\nApproval criteria:\n1. Gaps listed\n\n"
                "Decision items:\n[1] The gap analysis\n[2] The estimate\n[3] Update ACME-1 points in Jira: 5 → 8\n"
                "Options: Approve or Reject with reasons")
        self.assertEqual([(i["n"], i["text"]) for i in wb.parse_devin_message(text)[2]["items"]],
                         [(1, "The gap analysis"), (2, "The estimate"), (3, "Update ACME-1 points in Jira: 5 → 8")])
        bare = "[SDLC] gate SDLC_02_GAP_ANALYSIS_REVIEW — presented\nReply approved or rejected."
        self.assertEqual(len(wb.parse_devin_message(bare)[2]["items"]), 1)

    def _run(self):
        run = wb.migrate_run({"stage": "intake", "stages": {}, "events": [], "messages": [], "pending_gate": None,
                              "pending_questions": None, "artefacts": [], "diffs": [], "story": {"key": "REQ-1", "summary": "s"}})
        run["stages"]["intake"] = "running"
        text = "\n".join([
            "[SDLC] stage intake — started",
            "[SDLC] agent intake (BSA) — started: read the requirement",
            "[SDLC] skill jira-read — started: fetch ticket context",
            "[SDLC] route contract_approval — module Contract; layers db_schema, api_endpoints",
            "[SDLC] kb docs/knowledge-base/SHARED/DOMAIN_CONTEXT.md — loaded: business vocabulary",
            "[SDLC] kb docs/knowledge-base/ETL/13_ETL_TABLE_IO_CONTRACT.yaml — skipped: no ETL layer in the routing match",
            "[SDLC] rule .devin/rules/secure-coding.md — deferred: not needed before implement",
            "[SDLC] chain DC-003 — VBC_UI_CNTRCT_PARM → /api/contract/approved → Approved grid",
            '[SDLC] ontology find "TIN group" — Provider Group → CL_PG, 7 screens; why: the requirement says "TIN group"; gain: one lookup instead of four registries',
            "[SDLC] decision questions — 3 to the BSA (missing: environment, owner, date)",
            "[SDLC] skill jira-read — finished",
        ])
        events = wb.parse_devin_message(text)[0]
        run["messages"].append({"at": 1.0, "stage": "intake", "text": text, "source": "devin"})
        run["events"] = [dict(e, at=1.0) for e in events]
        return run

    def test_graph_drift_and_sync_lines_land_in_their_branches(self):
        run = self._run()
        text = "\n".join([
            "[SDLC] graph walk CL_PG_LOB — 2 jobs, 2 screens; why: the story adds a column; gain: PG_syncup.sql added to the scope",
            "[SDLC] drift ACME_LINK_GRAPH.yaml — re-read 8 cited lines; why: the plan relies on them; result: current",
            "[SDLC] sync ACME_ONTOLOGY.yaml — regenerated: rebuilt the YAML; why: the PR moved code; result: updated",
        ])
        run["events"] += [dict(e, at=2.0) for e in wb.parse_devin_message(text)[0]]
        intake = wb.trace_tree(run)["stages"][0]
        self.assertEqual(intake["graph"], [{"command": "walk", "term": "CL_PG_LOB", "found": "2 jobs, 2 screens",
                                            "why": "the story adds a column", "gain": "PG_syncup.sql added to the scope"}])
        self.assertEqual(intake["drift"], [{"artifact": "ACME_LINK_GRAPH.yaml", "what": "re-read 8 cited lines",
                                            "why": "the plan relies on them", "result": "current"}])
        self.assertEqual(intake["sync"][0]["result"], "updated")
        text = wb.trace_text(run)
        for label in ("Link graph", "Drift checks", "KB sync"):
            self.assertIn(label, text)
        self.assertIn("result: updated", text)

    def test_qa_lines_land_in_the_qa_suite_branch(self):
        run = self._run()
        text = ("[SDLC] qa 03_QA_SUITE_COVERAGE.yaml — read ACME/claims-qa ACME_Automation_092025@4c82c06d: 85 scenarios; "
                "why: new scenarios reuse the suite's steps; result: updated")
        run["events"] += [dict(e, at=2.0) for e in wb.parse_devin_message(text)[0]]
        intake = wb.trace_tree(run)["stages"][0]
        self.assertEqual(intake["qa"], [{"artifact": "03_QA_SUITE_COVERAGE.yaml",
                                         "what": "read ACME/claims-qa ACME_Automation_092025@4c82c06d: 85 scenarios",
                                         "why": "new scenarios reuse the suite's steps", "result": "updated"}])
        self.assertIn("QA suite", wb.trace_text(run))

    def test_evidence_tests_and_contract_lines_land_in_their_branches(self):
        run = self._run()
        text = "\n".join([
            "[SDLC] evidence STORY-1-claims.yaml — 4 claims: 3 verified, 1 unverified (C4: no evidence given); why: every claim needs a source; result: unverified, warning until 2026-11-25",
            "[SDLC] tests REQ-1-STORY-1.yaml — 2 test files from 3 changed files: a.test.tsx, test_b.py; why: the graph links them; result: selected",
            "[SDLC] contract Snowflake — live column types; why: the registry can lag the database; result: not run",
        ])
        run["events"] += [dict(e, at=2.0) for e in wb.parse_devin_message(text)[0]]
        intake = wb.trace_tree(run)["stages"][0]
        self.assertEqual(intake["evidence"][0]["result"], "unverified, warning until 2026-11-25")
        self.assertEqual(intake["tests"][0]["artifact"], "REQ-1-STORY-1.yaml")
        self.assertEqual(intake["contract"], [{"artifact": "Snowflake", "what": "live column types",
                                               "why": "the registry can lag the database", "result": "not run"}])
        text = wb.trace_text(run)
        for label in ("Evidence", "Tests picked", "Contract checks"):
            self.assertIn(label, text)
        self.assertIn("result: not run", text)

    def test_new_kinds_parse_as_events(self):
        kinds = sorted(set(e["kind"] for e in self._run()["events"]))
        self.assertEqual(kinds, ["agent", "chain", "decision", "kb", "ontology", "route", "rule", "skill", "stage"])

    def test_tree_groups_evidence_by_stage_with_verdicts_and_reasons(self):
        t = wb.trace_tree(self._run())
        self.assertEqual([s["stage"] for s in t["stages"]], wb.STAGES)
        intake = t["stages"][0]
        self.assertEqual(intake["status"], "running")
        self.assertEqual(intake["agents"], [{"name": "intake (BSA)", "state": "running", "why": "read the requirement"}])
        self.assertEqual(intake["skills"], [{"name": "jira-read", "state": "finished", "why": "fetch ticket context"}])
        self.assertEqual([(k["verdict"], k["why"]) for k in intake["kb"]],
                         [("loaded", "business vocabulary"), ("skipped", "no ETL layer in the routing match")])
        self.assertEqual(intake["rules"], [{"path": ".devin/rules/secure-coding.md", "verdict": "deferred", "why": "not needed before implement"}])
        self.assertEqual(intake["chains"][0]["id"], "DC-003")
        self.assertEqual(intake["ontology"], [{"command": "find", "term": "TIN group", "found": "Provider Group → CL_PG, 7 screens",
                                               "why": 'the requirement says "TIN group"', "gain": "one lookup instead of four registries"}])
        self.assertIn("├─ Ontology", wb.trace_text(self._run()))
        self.assertIn("gain: one lookup instead of four registries", wb.trace_text(self._run()))
        self.assertEqual(intake["routes"][0]["entry"], "contract_approval")
        self.assertEqual(intake["decisions"], [{"what": "questions", "detail": "3 to the BSA (missing: environment, owner, date)"}])
        self.assertEqual(t["stages"][1]["status"], "pending")
        self.assertEqual(t["stages"][1]["kb"], [])
        self.assertIsNone(t["pending_gate"])

    def test_lines_stay_with_the_stage_that_printed_them(self):
        run = wb.migrate_run({"stage": "intake", "stages": {}, "events": [], "messages": [], "pending_gate": None,
                              "pending_questions": None, "artefacts": [], "diffs": [], "story": {"key": "ACME-1", "summary": "s"}})
        for at, text in [("2026-10-09T10:00:00Z", "[SDLC] stage intake — started\n[SDLC] kb a.md — loaded: vocabulary\n"
                                                  "[SDLC] decision questions — 3 to the BSA"),
                         ("2026-10-09T11:00:00Z", "[SDLC] stage intake — finished\n[SDLC] stage research — started\n"
                                                  "[SDLC] kb b.yaml — skipped: no ETL layer")]:
            wb.apply_message(run, {"event_id": at, "created_at": at, "source": "devin", "message": text})
        self.assertEqual(run["stage"], "research")
        t = wb.trace_tree(run)
        intake, research = t["stages"][0], t["stages"][1]
        self.assertEqual([k["path"] for k in intake["kb"]], ["a.md"])
        self.assertEqual(intake["decisions"], [{"what": "questions", "detail": "3 to the BSA"}])
        self.assertEqual([(k["path"], k["verdict"]) for k in research["kb"]], [("b.yaml", "skipped")])
        text = wb.trace_text(run)
        self.assertIn("INTAKE · agent: intake (BSA) · done", text)
        self.assertIn("a.md LOADED  why: vocabulary", text)
        self.assertIn("b.yaml SKIPPED  why: no ETL layer", text)
        self.assertIn("PLAN · agent: plan (Tech Lead) · pending\n   queued", text)

    def test_waiting_gate_names_its_owner_from_approval_gates(self):
        run = self._run()
        run["pending_gate"] = {"id": "SDLC_01_INTAKE_CLARIFICATION", "text": "..."}
        t = wb.trace_tree(run)
        self.assertEqual(t["pending_gate"]["id"], "SDLC_01_INTAKE_CLARIFICATION")
        self.assertTrue(t["pending_gate"]["role"])

    def test_no_invented_metrics(self):
        t = wb.trace_tree(self._run())
        flat = json.dumps(t).lower()
        for word in ("token", "score", "similarity", "chunk"):
            self.assertNotIn(word, flat)
        with open(os.path.join(wb.STATIC, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-right="trace"', html)
        self.assertIn('id="traceFloat"', html)
        for action in ("min", "close"):
            self.assertIn('data-tracefloat="%s"' % action, html)
        self.assertIn('data-tracefloat="open"', workbench_js())
        self.assertTrue(os.path.isfile(os.path.join(wb.ROOT, ".devin", "rules", "workbench-trace.md")))


class SaveBlockTests(unittest.TestCase):
    """Save on dashboard tabs, review and intake pages (/api/blocks): which blocks it takes and what the run is told."""

    def test_only_known_blocks(self):
        self.assertEqual(wb.saved_block_kind("SDLC-DASHBOARD-GATE-CONFIG v1\n- gate: G | A: none\nEND"),
                         "SDLC-DASHBOARD-GATE-CONFIG")
        self.assertEqual(wb.saved_block_kind("# SDLC-INTAKE-ANSWERS v1\nrequirement_id: R"), "SDLC-INTAKE-ANSWERS")
        self.assertEqual(wb.saved_block_kind("rm -rf /"), "")
        self.assertEqual(wb.saved_block_kind("SDLC-SOMETHING-ELSE v1"), "")

    def test_every_saved_block_has_a_real_skill(self):
        for kind, (skill, label) in wb.SAVED_BLOCKS.items():
            self.assertTrue(wb.skill_info(skill), "%s -> /%s" % (kind, skill))

    def test_repo_blocks_go_through_a_pr_on_the_working_branch(self):
        text = wb.save_prompt("SDLC-DASHBOARD-ROLE-CONFIG", "SDLC-DASHBOARD-ROLE-CONFIG v1\nEND", "who")
        self.assertIn(".devin/rules/people.yaml", text)
        self.assertIn("devin/ branch", text)
        self.assertIn(wb.SAVE_BRANCH, text)
        self.assertIn("approved", text)
        jira = wb.save_prompt("SDLC-DASHBOARD-ANSWERS", "SDLC-DASHBOARD-ANSWERS v1\nEND", "who")
        self.assertIn("SDLC_BACKLOG_WRITES=1", jira)
        self.assertNotIn("pull request", jira)

    def test_a_tech_leads_real_save_on_a_config_tab_is_the_approval(self):
        lead = {"primary_role": "developer", "secondary_roles": ["solution_lead"]}
        self.assertTrue(wb.save_is_approval(lead, "SDLC-DASHBOARD-GATE-CONFIG", False))
        self.assertFalse(wb.save_is_approval(lead, "SDLC-DASHBOARD-GATE-CONFIG", True))
        self.assertFalse(wb.save_is_approval(lead, "SDLC-DASHBOARD-ANSWERS", False))
        self.assertFalse(wb.save_is_approval({"primary_role": "developer", "secondary_roles": []},
                                             "SDLC-DASHBOARD-GATE-CONFIG", False))
        self.assertFalse(wb.save_is_approval(None, "SDLC-DASHBOARD-GATE-CONFIG", False))
        text = wb.save_prompt("SDLC-DASHBOARD-GATE-CONFIG", "SDLC-DASHBOARD-GATE-CONFIG v1\nEND", "who", approved=True)
        self.assertIn("do not wait for `approved`", text)
        self.assertIn("reviewed and merged in Bitbucket", text)
        self.assertIn(wb.SAVE_BRANCH, text)

    def test_every_dashboard_marker_is_saveable(self):
        import re as _re
        src = open(os.path.join(wb.ROOT, "sdlc", "framework", "tools", "gen_dashboard.py")).read()
        for marker in set(_re.findall(r"SDLC-DASHBOARD-[A-Z-]+(?= v1)", src)):
            self.assertIn(marker, wb.SAVED_BLOCKS)

    def test_dashboard_save_sends_its_dry_run_tick(self):
        import gen_dashboard
        js = gen_dashboard.SAVE_JS
        self.assertIn('dry_run: dryOf(b).querySelector("input").checked', js)
        self.assertIn('<input type="checkbox" checked> Dry run', js)

    def test_bridge_client_has_every_call_the_api_client_has(self):
        for name in ("create_session", "session", "messages", "send", "list_sessions", "sessions_of", "terminate",
                     "set_tags", "upload", "download"):
            self.assertTrue(callable(getattr(wb.BridgedDevin, name, None)), name)


class SessionTimeTests(unittest.TestCase):
    def test_epoch_numbers_from_session_search_keep_their_time(self):
        self.assertEqual(wb.iso_epoch(1792799703), 1792799703.0)
        self.assertEqual(wb.iso_epoch("2026-10-22T17:16:29Z"), 1792689389.0)




class ThreadSafetyTests(unittest.TestCase):
    """One Argus: page requests, the poller's readers and the background jobs share runs.json and the run list."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-safety-")
        paths = mock.patch.multiple(wb, STATE_PATH=os.path.join(self.dir, "runs.json"),
                                    DELETED_PATH=os.path.join(self.dir, "deleted.json"))
        paths.start()
        self.addCleanup(paths.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)

    @staticmethod
    def new(store, sid, status="working"):
        return store.new_run({"key": "ACME-1", "summary": "s"}, True,
                             {"session_id": sid, "url": "https://example.invalid/s", "status": status})

    def test_saves_from_many_threads_leave_one_whole_file(self):
        store, errors = wb.Store(), []

        def work(n):
            try:
                for i in range(40):
                    with store.lock:
                        store.runs["r%d-%d" % (n, i)] = {"id": "r", "created_at": i, "messages": [{"text": "m" * 80}]}
                    store.save()
                    store.session_messages("devin-x")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        with open(wb.STATE_PATH, encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)), 240)

    def test_a_damaged_runs_file_is_kept_aside_and_argus_still_starts(self):
        with open(wb.STATE_PATH, "w", encoding="utf-8") as fh:
            fh.write('{"half": ')
        with mock.patch.object(wb.OBSERVER, "note") as note:
            store = wb.Store()
        self.assertEqual(store.runs, {})
        self.assertFalse(os.path.exists(wb.STATE_PATH))
        self.assertTrue([n for n in os.listdir(self.dir) if n.startswith("runs.json.bad-")])
        self.assertIn("could not be read", note.call_args[0][1])

    def test_a_read_that_changed_nothing_is_not_written_at_once(self):
        store, devin = wb.Store(), FakeDevin()
        run = self.new(store, "devin-a", "blocked")
        poller = wb.Poller(store, devin)
        poller.refresh(run["id"])
        with mock.patch.object(store, "save", wraps=store.save) as save:
            poller.refresh(run["id"])
            save.assert_not_called()
            self.assertTrue(store.dirty)
            reply = [{"event_id": "e1", "created_at": 1, "source": "devin", "message": "hi"}]
            with mock.patch.object(devin, "messages", return_value=reply):
                poller.refresh(run["id"])
            save.assert_called_once()

    def test_a_message_first_read_cut_short_is_parsed_again_in_full(self):
        store, devin = wb.Store(), FakeDevin()
        run = self.new(store, "devin-t", "blocked")
        poller = wb.Poller(store, devin)
        head = "[SDLC] stage intake — started\nWhat I read on the ticket..."
        cut = [{"event_id": "e1", "created_at": 1, "source": "devin", "message": head + " [truncated]"}]
        full = [{"event_id": "e1", "created_at": 1, "source": "devin",
                 "message": head + "\n1. Which scope?\n2. Drop the counts?\n3. Keep 8 points?"}]
        with mock.patch.object(devin, "messages", return_value=cut):
            poller.refresh(run["id"])
            poller.refresh(run["id"])
        self.assertIsNone(run["pending_questions"])
        with mock.patch.object(devin, "messages", return_value=full):
            poller.refresh(run["id"])
            poller.refresh(run["id"])
        self.assertEqual(len(run["messages"]), 1)
        self.assertTrue(run["messages"][0]["text"].endswith("Keep 8 points?"))
        self.assertEqual(len(run["pending_questions"]["items"]), 3)
        self.assertEqual(len([e for e in run["events"] if e["kind"] == "stage"]), 1)

    def test_a_cut_message_already_answered_does_not_ask_again(self):
        store, devin = wb.Store(), FakeDevin()
        run = self.new(store, "devin-u", "blocked")
        poller = wb.Poller(store, devin)
        cut = [{"event_id": "e1", "created_at": 1, "source": "devin", "message": "Intake... [truncated]"},
               {"event_id": "e2", "created_at": 2, "source": "user", "message": "1. a\n2. b"}]
        with mock.patch.object(devin, "messages", return_value=cut):
            poller.refresh(run["id"])
        full = [dict(cut[0], message="Intake\n1. Scope?\n2. Counts?"), cut[1]]
        with mock.patch.object(devin, "messages", return_value=full):
            poller.refresh(run["id"])
        self.assertEqual([m["event_id"] for m in run["messages"]], ["e1", "e2"])
        self.assertTrue(run["messages"][0]["text"].endswith("Counts?"))
        self.assertIsNone(run["pending_questions"])

    def test_only_sessions_that_moved_are_read_and_a_run_has_one_reader(self):
        store, devin = wb.Store(), FakeDevin()
        a, b, c = (self.new(store, "devin-" + ch * 32) for ch in "abc")
        for r in (a, b, c):
            r.update(polled_at=1000, session_updated=500)
        devin.list_sessions = lambda tag, limit=50: [{"session_id": "a" * 32, "updated_at": 500},
                                                     {"session_id": "devin-" + "b" * 32, "updated_at": 900}]
        poller = wb.Poller(store, devin)
        picked = dict(poller.changed([a["id"], b["id"], c["id"]], 1010))
        self.assertEqual(picked, {b["id"]: 900, c["id"]: None})
        self.assertIn(a["id"], dict(poller.changed([a["id"], b["id"]], 1000 + wb.UNCHANGED_RECHECK)))
        devin.list_sessions = mock.Mock(side_effect=wb.ApiError(502, "down"))
        self.assertEqual(len(poller.changed([a["id"], b["id"]], 1010)), 2)
        self.assertTrue(poller._claim(b["id"]))
        self.assertFalse(poller._claim(b["id"]))
        poller.busy.discard(b["id"])
        poller._poll_one(b["id"], 900)
        self.assertEqual(store.runs[b["id"]]["session_updated"], 900)
        self.assertTrue(poller._claim(b["id"]))

    def test_a_waiting_session_that_moved_is_read_in_the_same_round(self):
        store, devin = wb.Store(), FakeDevin()
        a, b = (self.new(store, "devin-" + ch * 32, "blocked") for ch in "ab")
        for r in (a, b):
            r.update(polled_at=1000, session_updated=500)
        asked = []
        devin.updated_of = lambda sids: asked.append(sorted(sids)) or [
            {"session_id": "devin-" + "a" * 32, "updated_at": 900}, {"session_id": "devin-" + "b" * 32, "updated_at": 500}]
        poller = wb.Poller(store, devin)
        self.assertEqual(poller.changed([a["id"], b["id"]], 1002), [(a["id"], 900)])
        self.assertEqual(asked, [sorted(["devin-" + "a" * 32, "devin-" + "b" * 32])])
        self.assertEqual(poller.changed([a["id"], b["id"]], 1000 + wb.UNCHANGED_RECHECK),
                         [(a["id"], 900), (b["id"], 500)])
        a["status"] = "exit"
        self.assertFalse(wb.watchable(a))
        self.assertEqual(poller.changed([], 1002), [])

    def test_a_failed_read_is_recorded_and_the_run_is_free_again(self):
        store, devin = wb.Store(), FakeDevin()
        run = self.new(store, "devin-f")
        devin.session = mock.Mock(side_effect=wb.ApiError(504, "bridge timed out"))
        poller = wb.Poller(store, devin)
        with mock.patch.object(wb.OBSERVER, "note"):
            self.assertTrue(poller._claim(run["id"]))
            poller._poll_one(run["id"])
        self.assertEqual(store.runs[run["id"]]["error"], "bridge timed out")
        self.assertNotIn(run["id"], poller.busy)

    def test_closing_a_run_that_was_just_deleted_is_quiet(self):
        wb.Poller(wb.Store(), FakeDevin()).close("gone")

    def test_run_notices_are_handed_back_to_note_outside_the_lock(self):
        notes = wb.notice_run({"status": "error", "kind": "action", "story": {"action": "intake"}}, 0)
        self.assertEqual(notes[0][0], "run_error")

    def test_a_session_the_bridge_started_late_joins_the_run_list(self):
        store, devin = wb.Store(), FakeDevin()
        spec = {"title": "Argus /explain-capability", "tags": [wb.WORKBENCH_TAG, "action", "explain-capability", "live"]}
        devin.collect_late = lambda: [([("devin_session_create", {"sessions": [spec]})],
                                       ["Created session devin-" + "d" * 32])]
        with mock.patch.object(wb.OBSERVER, "note"):
            wb.Poller(store, devin)._adopt_late()
        self.assertEqual([r["session_id"] for r in store.runs.values()], ["devin-" + "d" * 32])

    def test_check_now_turns_jira_back_on_after_a_refusal(self):
        with mock.patch.dict(os.environ, {wb.JIRA_TOKEN_ENV: "t"}):
            jira = wb.Jira()
        jira.dead = "Jira returned 401 for the service account; not retrying (token may be locked)."
        with mock.patch.object(jira, "_get_retrying", return_value={"name": "svc"}) as got:
            with self.assertRaises(wb.ApiError):
                jira.get("/api/2/issue/ACME-1")
            got.assert_not_called()
            wb.check_integrations(object(), jira)
        self.assertEqual(got.call_count, 1)
        self.assertIsNone(jira.dead)

    def test_one_git_fetch_at_a_time_and_a_failed_one_waits_its_turn(self):
        cmds = []

        def run(cmd, **kw):
            cmds.append(cmd)
            if "fetch" in cmd:
                raise wb.subprocess.TimeoutExpired(cmd, 60)
            return mock.Mock(returncode=0, stdout=b"data")

        with mock.patch.object(wb, "READ_REMOTE", True), mock.patch.object(wb.subprocess, "run", side_effect=run), \
                mock.patch.object(wb, "_last_fetch", [0.0]), mock.patch.object(wb, "_fetched", [False]):
            self.assertEqual(wb._git_branch("show", "x"), b"data")
            self.assertEqual(wb._git_branch("show", "y"), b"data")
        self.assertEqual(sum(1 for c in cmds if "fetch" in c), 1)
        self.assertFalse(wb._FETCH_LOCK.locked())

    def test_a_closed_tab_does_not_raise(self):
        class Gone:
            def write(self, data):
                raise BrokenPipeError()

            def flush(self):
                pass

        h = wb.Handler.__new__(wb.Handler)
        h.path, h.command, h.request_version = "/api/x", "GET", "HTTP/1.1"
        h.requestline, h.client_address, h.close_connection = "GET /api/x HTTP/1.1", ("127.0.0.1", 1), False
        h.wfile, h.log_message = Gone(), lambda *a: None
        h._send(200, {"ok": True})
        self.assertTrue(h.close_connection)


class RequestBodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wb.Handler.log_message = lambda *a: None
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), wb.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def post(self, data):
        req = urllib.request.Request(self.base + "/api/actions", method="POST", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_a_bad_body_gets_a_400_not_a_server_error(self):
        with mock.patch.object(wb.OBSERVER, "note"):
            self.assertEqual(self.post(b'{"skill": '), (400, {"error": "the request was not valid JSON"}))
            self.assertEqual(self.post(b"[1, 2]")[0], 400)

    def test_a_body_too_big_is_refused_before_it_is_read(self):
        with mock.patch.object(wb, "MAX_BODY_BYTES", 10), mock.patch.object(wb.OBSERVER, "note"):
            self.assertEqual(self.post(b'{"skill": "explain-capability"}')[0], 413)




class SharedNightlyDataTests(unittest.TestCase):
    """The Argus maintenance job reads Jira once a night for everyone; each Argus builds its pages from that."""

    def test_fresh_shared_answers_are_used_for_this_person_only(self):
        out = os.path.join(tempfile.mkdtemp(prefix="sdlc-reads-"), "r.json")
        fresh = json.dumps({"saved_at": 1000, "reads": {"u": {"x": 1}}}).encode()
        with mock.patch.object(wb, "repo_file", return_value=(fresh, "origin")):
            self.assertTrue(wb.shared_reads(out, now=1000 + 3600))
            self.assertFalse(wb.shared_reads(out, now=1000 + wb.SHARED_READS_MAX_AGE + 1))
        with mock.patch.object(wb, "repo_file", side_effect=FileNotFoundError()):
            self.assertFalse(wb.shared_reads(out))
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(), fresh)

    def test_the_nightly_build_passes_the_shared_answers_and_the_person(self):
        runs = []

        class Stop(Exception):
            pass

        sleeps = iter([None, Stop()])

        def sleep(_):
            nxt = next(sleeps)
            if nxt:
                raise nxt
        with mock.patch.object(wb.time, "sleep", sleep), mock.patch.object(wb, "nightly_attempted", return_value=0), \
                mock.patch.object(wb, "DEFAULT_JIRA_USER", "user6"), \
                mock.patch.object(wb, "shared_reads", return_value=True), self.assertRaises(Stop):
            wb.nightly_dashboards(run=lambda cmd, **kw: runs.append(cmd) or mock.Mock(returncode=0))
        self.assertIn("--reads", runs[0])
        self.assertEqual(runs[0][runs[0].index("--user") + 1], "user6")

    def test_old_shared_data_is_flagged_for_the_leads(self):
        with mock.patch.object(wb, "repo_file", return_value=(b'{"saved_at": 10, "reads": {}}', "origin")), \
                mock.patch.dict(wb._DATA_AGE, {"at": 0.0, "value": None}):
            self.assertTrue(wb.shared_data_age(now=10 + wb.SHARED_READS_MAX_AGE + 1)["stale"])

    def test_the_dashboard_builds_from_saved_answers_and_saves_its_own(self):
        sys.path.insert(0, os.path.join(os.path.dirname(CONSOLE), "tools"))
        import gen_dashboard as gd
        folder = tempfile.mkdtemp(prefix="sdlc-gd-")
        path = os.path.join(folder, "reads.json")
        gd.save_reads(path, {"https://jira/x": {"ok": 1}})
        self.assertEqual(gd.load_reads(path), {"https://jira/x": {"ok": 1}})
        self.assertEqual(gd.load_reads(os.path.join(folder, "none.json")), {})
        seen = {}

        def build(ns):
            seen.update(gd.JiraClient.shared)
            gd.JiraClient.shared["https://jira/y"] = {"ok": 2}
            return {"username": ns.user, "lens_id": "developer"}
        with mock.patch.object(gd, "build", build), mock.patch.object(gd, "render", return_value="<html>"):
            done = gd.build_all(folder, ["user6"], reads={"https://jira/x": {"ok": 1}},
                                save_to=os.path.join(folder, "out.json"))
        self.assertEqual(done["built"], ["user6.developer.html"])
        self.assertIn("https://jira/x", seen)
        self.assertEqual(sorted(gd.load_reads(os.path.join(folder, "out.json"))), ["https://jira/x", "https://jira/y"])
