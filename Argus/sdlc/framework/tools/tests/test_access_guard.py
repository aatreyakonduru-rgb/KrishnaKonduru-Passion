"""The roster's access rules: who may change which folders, and the roster-page check behind them."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import access_guard  # noqa: E402
import roster_sync  # noqa: E402

ACCESS = {
    "default_roles": ["tech_lead"],
    "no_self_approval": ["SDLC_05_CODE_REVIEW"],
    "areas": [
        {"name": "code", "paths": ["app/", "package.json"], "roles": ["developer", "tech_lead"]},
        {"name": "knowledge base", "paths": ["app/kb/"], "roles": ["bsa", "product_owner"]},
        {"name": "decisions", "paths": ["app/kb/DECISIONS/"], "roles": ["any"]},
        {"name": "framework", "paths": [".devin/"], "roles": ["tech_lead"]},
        {"name": "own session", "paths": ["sessions/{owner}/"], "roles": ["any"]},
    ],
}


def person(n, *roles):
    return {"jira_user": "AB1000%d" % n, "name": "Resource %d" % n, "email": "resource%d@acme.example" % n,
            "roles": list(roles), "primary_role": roles[0] if roles else None, "secondary_roles": [],
            "delegate_to": None}


ROSTER = {
    "source": {"confluence_page_id": "123", "confluence_version": 1},
    "owner": {"primary": "AB10003", "backups": [], "signoff": {"status": "signed"}},
    "people": [person(1, "developer"), person(2, "bsa"), person(3, "tech_lead")],
    "default_role": "developer",
    "access": ACCESS,
}


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdlc-access-")
        self.people = os.path.join(self.tmp, "people.yaml")
        with open(self.people, "w", encoding="utf-8") as fh:
            yaml.safe_dump(ROSTER, fh)
        self._state, self._env = access_guard.STATE_DIR, dict(os.environ)
        access_guard.STATE_DIR = os.path.join(self.tmp, "state")
        self.calls = 0

    def tearDown(self):
        access_guard.STATE_DIR = self._state
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ok_verifier(self, path):
        self.calls += 1
        return True, 7, []

    def as_user(self, n):
        os.environ["SDLC_OWNER"] = "ab1000%d" % n

    def blocked(self, n, *paths, verifier=None):
        self.as_user(n)
        return access_guard.check(list(paths), ROSTER, self.people, root=self.tmp,
                                  verifier=verifier or self.ok_verifier)


class AreaTests(GuardTestCase):
    def test_developer_changes_code_but_not_the_knowledge_base(self):
        self.assertEqual(self.blocked(1, "app/src/main.ts", "package.json"), [])
        reasons = self.blocked(1, "app/kb/MODULES/a.md")
        self.assertEqual(len(reasons), 1)
        self.assertIn("knowledge base needs one of: bsa, product_owner", reasons[0])

    def test_bsa_changes_the_knowledge_base_but_not_code(self):
        self.assertEqual(self.blocked(2, "app/kb/MODULES/a.md"), [])
        self.assertTrue(self.blocked(2, "app/src/main.ts"))

    def test_longest_path_wins_and_any_means_anyone_on_the_roster(self):
        self.assertEqual(self.blocked(1, "app/kb/DECISIONS/ADR-0001.md"), [])

    def test_own_session_folder_only(self):
        self.assertEqual(self.blocked(1, "sessions/resource1/REQ-1/spec.md"), [])
        self.assertIn("unlisted path", self.blocked(1, "sessions/resource2/REQ-1/spec.md")[0])

    def test_unlisted_path_needs_a_default_role(self):
        self.assertTrue(self.blocked(1, "README.md"))
        self.assertEqual(self.blocked(3, "README.md"), [])

    def test_absolute_paths_inside_the_repo_are_checked_and_outside_ones_are_not(self):
        self.assertTrue(self.blocked(1, os.path.join(self.tmp, ".devin", "rules", "people.yaml")))
        self.assertEqual(self.blocked(1, "/tmp/elsewhere/notes.md", "../outside.md"), [])

    def test_prefix_must_end_at_a_folder_boundary(self):
        self.assertTrue(self.blocked(1, "application/x.ts"))

    def test_unknown_requester_is_blocked(self):
        os.environ["SDLC_OWNER"] = "nobody"
        roster = dict(ROSTER, people=[])
        reasons = access_guard.check(["app/x.ts"], roster, self.people, root=self.tmp, verifier=self.ok_verifier)
        self.assertIn("cannot tell who is asking", reasons[0])

    def test_roster_page_without_access_rules_blocks(self):
        roster = {k: v for k, v in ROSTER.items() if k != "access"}
        reasons = access_guard.check(["app/kb/x.md"], roster, self.people, root=self.tmp)
        self.assertIn("has no access: section", reasons[0])

    def test_roster_without_access_or_page_turns_the_guard_off(self):
        roster = {k: v for k, v in ROSTER.items() if k not in ("access", "source")}
        self.assertEqual(access_guard.check(["app/kb/x.md"], roster, self.people, root=self.tmp), [])

    def test_requester_recorded_by_identify_requester(self):
        os.environ.pop("SDLC_OWNER", None)
        access_guard.set_requester("RESOURCE2@acme.example", ROSTER)
        self.assertEqual(access_guard.current_person(ROSTER)["jira_user"], "AB10002")
        with self.assertRaises(access_guard.GuardError):
            access_guard.set_requester("stranger@acme.example", ROSTER)


class IdentityTests(GuardTestCase):
    """SDLC_OWNER may not name someone other than the requester /identify-requester recorded."""

    def recorded(self, n):
        os.environ.pop("SDLC_OWNER", None)
        access_guard.set_requester("resource%d@acme.example" % n, ROSTER)

    def test_a_bsa_cannot_claim_to_be_a_developer(self):
        self.recorded(2)
        reasons = self.blocked(1, "app/src/main.ts")
        self.assertIn("SDLC_OWNER names Resource 1, but this session's requester is Resource 2", reasons[0])

    def test_a_lead_may_act_as_someone_else(self):
        self.recorded(3)
        self.assertEqual(self.blocked(1, "app/src/main.ts"), [])
        self.assertTrue(self.blocked(1, "app/kb/a.md"))

    def test_sdlc_owner_naming_the_requester_is_fine(self):
        self.recorded(2)
        self.assertEqual(self.blocked(2, "app/kb/a.md"), [])

    def test_a_bsa_cannot_approve_as_someone_else(self):
        self.recorded(2)
        self.as_user(1)
        with self.assertRaisesRegex(access_guard.GuardError, "only a lead may act as someone else"):
            access_guard.record_approval(ROSTER, root=self.tmp, people_path=self.people, verifier=self.ok_verifier)

    def test_lead_is_any_role_with_lead_in_it(self):
        self.assertTrue(access_guard.is_lead(person(9, "developer", "tech_lead")))
        self.assertTrue(access_guard.is_lead(dict(person(9, "developer"), secondary_roles=["qa_lead"])))
        self.assertFalse(access_guard.is_lead(person(9, "product_owner", "bsa")))


class TrustedRosterTests(unittest.TestCase):
    """The rules come from the committed people.yaml, so editing the checkout cannot loosen them."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="sdlc-trusted-")
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.people = os.path.join(self.repo, ".devin", "rules", "people.yaml")
        os.makedirs(os.path.dirname(self.people))
        self.save(ROSTER)
        env = dict(os.environ, GIT_AUTHOR_NAME="svc", GIT_AUTHOR_EMAIL="svc@acme.example",
                   GIT_COMMITTER_NAME="svc", GIT_COMMITTER_EMAIL="svc@acme.example")
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "--no-verify", "-m", "start"]):
            subprocess.run(["git"] + args, cwd=self.repo, env=env, capture_output=True, check=True)

    def save(self, roster):
        with open(self.people, "w", encoding="utf-8") as fh:
            yaml.safe_dump(roster, fh)

    def test_an_uncommitted_edit_is_ignored(self):
        self.save({k: v for k, v in ROSTER.items() if k != "access"})
        self.assertEqual(access_guard.trusted_roster(self.people, root=self.repo, branch="")["access"], ACCESS)

    def test_the_target_branch_wins_over_head_and_head_over_the_file(self):
        self.assertEqual(access_guard.trusted_roster(self.people, root=self.repo, branch="no-such-branch")["access"],
                         ACCESS)
        outside = os.path.join(self.repo, "..", "elsewhere-people.yaml")
        self.addCleanup(lambda: os.path.exists(outside) and os.remove(outside))
        with open(outside, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"people": []}, fh)
        self.assertEqual(access_guard.trusted_roster(outside, root=self.repo, branch=""), {"people": []})


class ShellCheckTests(unittest.TestCase):
    def test_commands_that_skip_the_hooks_are_refused(self):
        for command in ("git commit --no-verify -m x", "git commit -nm x", "git commit -a -n -m x",
                        "git push --no-verify origin x", "git -c core.hooksPath=/dev/null commit -m x",
                        "rm .git/hooks/pre-commit", "echo {} > ~/.sdlc/requester.json",
                        "cd repo && git add . && git commit --no-verify -m x"):
            self.assertTrue(access_guard.shell_problems(command), command)

    def test_ordinary_commands_pass(self):
        for command in ('git commit -m "use -n here" -a', "git push -n origin x", "ls .git/hooks | grep -v sample",
                        "cat .git/hooks/pre-commit 2>/dev/null", "python3 x.py > out.txt",
                        "git commit -m fix && git push"):
            self.assertEqual(access_guard.shell_problems(command), [], command)


PR_ACCESS = {
    "default_roles": ["tech_lead"],
    "areas": [
        {"name": "application code", "paths": ["app/"], "roles": ["developer", "tech_lead"]},
        {"name": "knowledge base", "paths": ["app/kb/"], "roles": ["bsa", "product_owner", "tech_lead"]},
        {"name": "decisions", "paths": ["app/kb/DECISIONS/"], "roles": ["any"]},
    ],
}
PR_ROSTER = dict(ROSTER, access=PR_ACCESS,
                 people=[person(1, "developer"), person(2, "bsa"), person(3, "tech_lead"), person(4)])


class KbPullRequestTests(GuardTestCase):
    """PO and BSA: their commits need their own "approved", and their branch only the knowledge base."""

    def setUp(self):
        super().setUp()
        with open(self.people, "w", encoding="utf-8") as fh:
            yaml.safe_dump(PR_ROSTER, fh)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.git("init", "-q")
        self.write("app/kb/README.md", "kb\n")
        self.commit("start", stamp=False)
        self.git("branch", "base")

    def git(self, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="svc", GIT_AUTHOR_EMAIL="svc@acme.example",
                   GIT_COMMITTER_NAME="svc", GIT_COMMITTER_EMAIL="svc@acme.example")
        return subprocess.run(["git"] + list(args), cwd=self.repo, env=env, capture_output=True,
                              text=True, check=True).stdout

    def write(self, rel, text):
        full = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.git("add", rel)

    def commit(self, subject, stamp=True):
        message = subject + ("\n\nApproved-by: Resource 2 (bsa) <resource2@acme.example> 2026-10-13T20:40Z"
                             if stamp else "")
        self.git("commit", "-q", "--no-verify", "-m", message)

    def approve(self, n):
        self.as_user(n)
        return access_guard.record_approval(PR_ROSTER, root=self.repo, people_path=self.people,
                                            verifier=self.ok_verifier, now=0)

    def problems(self, n):
        self.as_user(n)
        return access_guard.pr_problems("base", PR_ROSTER, root=self.repo, people_path=self.people,
                                        verifier=self.ok_verifier)

    def test_only_people_who_may_change_the_kb_but_not_code_are_kb_only(self):
        people = {p["jira_user"]: p for p in PR_ROSTER["people"]}
        self.assertEqual([n for n in (1, 2, 3, 4) if access_guard.kb_only(people["AB1000%d" % n], PR_ACCESS)], [2])

    def test_approval_stamps_the_next_commit_once(self):
        self.write("app/kb/a.md", "a\n")
        self.assertEqual(self.approve(2), "Resource 2 (bsa) <resource2@acme.example> 1970-01-01T00:00Z")
        value, refused = access_guard.approval_trailer(PR_ROSTER, root=self.repo)
        self.assertEqual((value, refused), ("Resource 2 (bsa) <resource2@acme.example> 1970-01-01T00:00Z", None))
        value, refused = access_guard.approval_trailer(PR_ROSTER, root=self.repo)
        self.assertIsNone(value)
        self.assertIn("has not approved these files", refused)

    def test_files_staged_after_the_approval_are_not_covered(self):
        self.write("app/kb/a.md", "a\n")
        self.approve(2)
        self.write("app/kb/a.md", "changed after approval\n")
        value, refused = access_guard.approval_trailer(PR_ROSTER, root=self.repo)
        self.assertIsNone(value)
        self.assertIn("has not approved", refused)

    def test_approval_belongs_to_the_person_who_gave_it(self):
        self.write("app/kb/a.md", "a\n")
        self.approve(2)
        self.as_user(3)
        self.assertEqual(access_guard.approval_trailer(PR_ROSTER, root=self.repo), (None, None))

    def test_a_bsa_cannot_approve_code(self):
        self.write("app/x.py", "x\n")
        with self.assertRaisesRegex(access_guard.GuardError, "may not change app/x.py"):
            self.approve(2)

    def test_developers_need_no_approval(self):
        self.as_user(1)
        self.write("app/x.py", "x\n")
        self.assertEqual(access_guard.approval_trailer(PR_ROSTER, root=self.repo), (None, None))

    def test_approved_kb_commits_may_go_to_a_pull_request(self):
        self.write("app/kb/a.md", "a\n")
        self.write("app/kb/DECISIONS/ADR-1.md", "d\n")
        self.commit("kb change")
        self.assertEqual(self.problems(2), [])

    def test_a_bsa_branch_with_a_code_file_is_refused(self):
        self.write("app/x.py", "x\n")
        self.commit("sneaked in")
        found = self.problems(2)
        self.assertTrue(any("app/x.py is outside the knowledge base" in p for p in found), found)
        self.assertTrue(any("may not change app/x.py" in p for p in found), found)

    def test_a_bsa_commit_without_a_stamp_is_refused(self):
        self.write("app/kb/a.md", "a\n")
        self.commit("no stamp", stamp=False)
        self.assertTrue(any("has no Approved-by stamp" in p for p in self.problems(2)))

    def signed(self, n, subject, approved=False):
        p = PR_ROSTER["people"][n - 1]
        message = "%s\n\nRequested-by: %s <%s>" % (subject, p["name"], p["email"])
        if approved:
            message += "\nApproved-by: %s (bsa) <%s> 2026-10-13T20:40Z" % (p["name"], p["email"])
        self.git("commit", "-q", "--no-verify", "-m", message)

    def audit(self, opener=None):
        return access_guard.pr_audit("base", PR_ROSTER, root=self.repo, pr_requester=opener)

    def test_audit_passes_signed_commits_people_may_make(self):
        self.write("app/x.py", "x\n")
        self.signed(1, "code")
        self.write("app/kb/a.md", "a\n")
        self.signed(2, "kb", approved=True)
        self.assertEqual(self.audit(), [])

    def test_audit_flags_a_commit_made_without_the_hooks(self):
        self.write("app/x.py", "x\n")
        self.commit("no hooks", stamp=False)
        self.assertIn("has no Requested-by", self.audit()[0])

    def test_audit_flags_a_requester_off_the_roster(self):
        self.write("app/x.py", "x\n")
        self.git("commit", "-q", "--no-verify", "-m", "x\n\nRequested-by: Rahul <rahul@acme.example>")
        self.assertIn("is not on the roster", self.audit()[0])

    def test_audit_flags_files_the_requester_may_not_change(self):
        self.write("app/x.py", "x\n")
        self.signed(2, "bsa changes code", approved=True)
        self.assertTrue(any("may not change app/x.py" in p for p in self.audit()))

    def test_audit_flags_a_bsa_commit_without_approval(self):
        self.write("app/kb/a.md", "a\n")
        self.signed(2, "kb")
        self.assertTrue(any("has no Approved-by stamp" in p for p in self.audit()))

    def test_audit_checks_the_requester_against_who_opened_the_pull_request(self):
        self.write("app/x.py", "x\n")
        self.signed(1, "code")
        self.assertIn("the pull request was opened for Resource 2", self.audit("resource2@acme.example")[0])
        self.assertEqual(self.audit("resource3@acme.example"), [])
        self.assertIn("is not on the roster", self.audit("rahul@acme.example")[0])

    def test_other_requesters_are_not_checked(self):
        self.write("app/x.py", "x\n")
        self.commit("code", stamp=False)
        self.assertEqual(self.problems(1), [])
        self.assertEqual(self.problems(3), [])


class VerifyTests(GuardTestCase):
    def test_unreadable_page_blocks(self):
        def down(path):
            raise RuntimeError("srcToken is not set; cannot reach Confluence.")
        reasons = self.blocked(1, "app/x.ts", verifier=down)
        self.assertIn("cannot read the roster page", reasons[0])

    def test_roster_that_differs_from_the_page_blocks(self):
        reasons = self.blocked(1, "app/x.ts", verifier=lambda p: (False, 8, ["~ AB10001 roles: a -> b"]))
        self.assertIn("differs from the roster page (version 8)", reasons[0])

    def test_success_is_cached_until_people_yaml_changes(self):
        self.assertEqual(access_guard.verify_roster(self.people, self.ok_verifier)[0], True)
        access_guard.verify_roster(self.people, self.ok_verifier)
        self.assertEqual(self.calls, 1)
        with open(self.people, "a", encoding="utf-8") as fh:
            fh.write("# edited\n")
        access_guard.verify_roster(self.people, self.ok_verifier)
        self.assertEqual(self.calls, 2)

    def test_cache_expires(self):
        access_guard.verify_roster(self.people, self.ok_verifier, now=1000)
        access_guard.verify_roster(self.people, self.ok_verifier, now=1000 + access_guard.VERIFY_TTL + 1)
        self.assertEqual(self.calls, 2)

    def test_failure_is_not_cached(self):
        access_guard.verify_roster(self.people, lambda p: (False, 1, ["x"]))
        self.assertFalse(os.path.exists(os.path.join(access_guard.STATE_DIR, "roster-verified.json")))

    def test_access_rules_without_a_source_page_block(self):
        with open(self.people, "w", encoding="utf-8") as fh:
            yaml.safe_dump(dict(ROSTER, source={"confluence_page_id": "{{CONFLUENCE_ROSTER_PAGE_ID}}"}), fh)
        ok, why = access_guard.verify_roster(self.people, lambda p: 1 / 0)
        self.assertFalse(ok)
        self.assertIn("no roster page", why)

    def test_roster_without_access_rules_or_source_page_needs_no_verification(self):
        roster = {k: v for k, v in ROSTER.items() if k != "access"}
        with open(self.people, "w", encoding="utf-8") as fh:
            yaml.safe_dump(dict(roster, source={"confluence_page_id": "{{CONFLUENCE_ROSTER_PAGE_ID}}"}), fh)
        self.assertTrue(access_guard.verify_roster(self.people, lambda p: 1 / 0)[0])

    def test_owner_given_as_email_is_the_same_slug_as_git(self):
        os.environ["SDLC_OWNER"] = "Jane.Doe@example.com"
        self.assertEqual(access_guard.session_store.resolve_owner(), "jane-doe")


class RosterSignoffTests(GuardTestCase):
    RULE = {"dev": ["owner", "backup"], "enforced": ["manager", "reviewer"]}

    def roster(self, status, by):
        roster = json.loads(json.dumps(ROSTER))
        roster["access"]["roster_signoff"] = self.RULE
        roster["owner"] = {"primary": "AB10004", "backups": ["AB10003"],
                           "signoff": {"status": status, "signed_by": by, "signed_on": "2026-10-05"}}
        roster["people"].append(person(4, "manager"))
        return roster

    def test_pending_roster_unlocks_nothing(self):
        roster = self.roster("pending", None)
        for mode in ("dev", "enforced"):
            self.assertIn("has not signed", access_guard.signoff_problem(roster, mode))

    def test_backup_sign_off_counts_in_dev_mode_only(self):
        roster = self.roster("interim", "AB10003")
        self.assertIsNone(access_guard.signoff_problem(roster, "dev"))
        self.assertIn("needs a sign-off from: manager, reviewer", access_guard.signoff_problem(roster, "enforced"))

    def test_manager_sign_off_counts_in_enforced_mode(self):
        self.assertIsNone(access_guard.signoff_problem(self.roster("signed", "AB10004"), "enforced"))

    def test_without_a_rule_the_owner_or_a_backup_must_have_signed(self):
        roster = self.roster("interim", "AB10003")
        del roster["access"]["roster_signoff"]
        self.assertIsNone(access_guard.signoff_problem(roster, "enforced"))
        roster["owner"]["signoff"] = {"status": "pending"}
        self.assertIsNotNone(access_guard.signoff_problem(roster, "enforced"))

    def test_a_pending_people_yaml_blocks_even_when_it_matches_the_page(self):
        with open(self.people, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.roster("pending", None), fh)
        ok, why = access_guard.verify_roster(self.people, self.ok_verifier, mode="dev")
        self.assertFalse(ok)
        self.assertIn("has not signed", why)
        self.assertEqual(self.calls, 0)

    def test_the_rule_round_trips_through_the_page(self):
        roster = self.roster("signed", "AB10004")
        page = roster_sync.parse_page(roster_sync.render_page(roster))
        self.assertEqual(page["access"]["roster_signoff"], self.RULE)
        self.assertEqual(roster_sync.verify_differences(page, roster, page["owner"]["signoff"]), [])
        local = json.loads(json.dumps(roster))
        local["access"]["roster_signoff"]["enforced"] = ["backup"]
        self.assertTrue(any(line.startswith("~ access") for line in
                            roster_sync.verify_differences(page, local, page["owner"]["signoff"])))


class RosterPageAccessTests(unittest.TestCase):
    def page(self, data):
        return roster_sync.parse_page(roster_sync.render_page(data))

    def signoff(self):
        return {"status": "signed", "signed_by": "AB10003", "signed_on": None}

    def test_access_round_trips_through_the_page(self):
        page = self.page(ROSTER)
        self.assertEqual(roster_sync.norm_access(page["access"]), roster_sync.norm_access(ACCESS))
        self.assertEqual(roster_sync.verify_differences(page, ROSTER, self.signoff()), [])

    def test_page_without_access_table_does_not_verify(self):
        page = self.page({k: v for k, v in ROSTER.items() if k != "access"})
        self.assertIsNone(page["access"])
        lines = roster_sync.verify_differences(page, ROSTER, self.signoff())
        self.assertIn("no Access table", lines[0])
        self.assertEqual(roster_sync.merge(page, ROSTER)["access"], ACCESS)

    def test_a_role_added_only_in_people_yaml_does_not_verify(self):
        page = self.page(ROSTER)
        local = json.loads(json.dumps(ROSTER))
        local["people"][0]["roles"].append("tech_lead")
        self.assertTrue(any("AB10001 roles" in line for line in roster_sync.verify_differences(page, local, self.signoff())))

    def test_access_and_owner_changes_do_not_verify(self):
        page = self.page(ROSTER)
        local = json.loads(json.dumps(ROSTER))
        local["access"]["areas"][1]["roles"].append("developer")
        local["owner"]["backups"] = ["AB10001"]
        lines = roster_sync.verify_differences(page, local, self.signoff())
        self.assertTrue(any(line.startswith("~ access") for line in lines))
        self.assertTrue(any(line.startswith("~ owner backups") for line in lines))


class SampleRosterTests(unittest.TestCase):
    def test_the_distribution_sample_survives_the_roster_page_round_trip(self):
        sample = os.path.join(TOOLS, "..", "..", "..", "sdlc", "kb", "examples", "acme", "people.yaml")
        roster = access_guard.load_roster(sample)
        page = roster_sync.parse_page(roster_sync.render_page(roster))
        self.assertEqual(page["owner"]["primary"], "resource1")
        self.assertEqual(roster_sync.verify_differences(page, roster, page["owner"]["signoff"]), [])


class RealRosterTests(unittest.TestCase):
    def test_our_roster_names_the_areas_the_kb_pull_request_check_uses(self):
        names = {a.get("name") for a in (access_guard.load_roster().get("access") or {}).get("areas") or []}
        self.assertLessEqual({access_guard.KB_AREA, access_guard.CODE_AREA}, names)

    def test_our_roster_access_names_real_gate_roles(self):
        roster = access_guard.load_roster()
        held = {r for p in roster["people"] for r in p.get("roles") or []}
        for area in roster["access"]["areas"]:
            for role in area["roles"]:
                self.assertTrue(role == "any" or role in held, "%s: nobody holds %s" % (area["name"], role))


if __name__ == "__main__":
    unittest.main()
