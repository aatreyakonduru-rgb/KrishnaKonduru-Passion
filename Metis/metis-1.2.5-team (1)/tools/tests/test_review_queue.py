import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kb_gate  # noqa: E402
import review_queue  # noqa: E402

PROFILE = {
    "owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev"},
    "gate": {"teams": [
        {"name": "Claims Team", "owns": ["claims/*"], "approvers": ["Cleo Claims"]},
        {"name": "Billing Team", "owns": ["billing"], "approvers": ["Bo Billing"]},
    ]},
}


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class ReviewQueue(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        self.profile(PROFILE)
        write(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pay in 30 days\n")
        write(os.path.join(self.kb, "context", "a.md"), "# A\n\n- Pay in 30 days [E: file:rules.txt]\n")

    def tearDown(self):
        rmtree(self.d)

    def profile(self, prof):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))

    def page(self, given_by="Pat Analyst"):
        return "---\ntitle: B\ndocuments:\n- {id: d1, name: r.docx, given_by: %s}\n---\n# B\n\n- Pay in 30 days [E: file:rules.txt]\n" % given_by

    def stage(self, files, name="docs"):
        src = os.path.join(self.d, "src-" + name)
        for rel, text in files.items():
            write(os.path.join(src, rel), text)
        batch = kb_gate.new_batch(self.kb, name)
        kb_gate.propose(self.kb, batch, src)
        return batch

    def locked_with_pending(self, **kw):
        kb_gate.lock(self.kb, "Ana Lead")
        return self.stage({"claims/x.md": self.page(**kw), "billing/y.md": self.page(**kw), "context/z.md": self.page(**kw)})

    def test_ownership_first_match_and_default(self):
        self.assertEqual(kb_gate.team_of(self.kb, "claims/x.md")["name"], "Claims Team")
        self.assertEqual(kb_gate.team_of(self.kb, "billing/deep/y.md")["name"], "Billing Team")
        self.assertIsNone(kb_gate.team_of(self.kb, "context/z.md"))

    def test_queue_groups_by_team(self):
        self.locked_with_pending()
        groups = {g["team"]: g for g in review_queue.queue(self.kb)["teams"]}
        self.assertEqual(set(groups), {"Claims Team", "Billing Team", kb_gate.UNASSIGNED})
        self.assertEqual([r["file"] for r in groups["Claims Team"]["files"]], ["claims/x.md"])
        self.assertIn("Cleo Claims", groups["Claims Team"]["approvers"])
        self.assertIn("Ana Lead", groups["Claims Team"]["approvers"])
        self.assertEqual(groups[kb_gate.UNASSIGNED]["approvers"], ["Ana Lead", "Raj Dev"])

    def test_queue_riskiest_first(self):
        kb_gate.lock(self.kb, "Ana Lead")
        self.stage({"claims/a.md": self.page(), "claims/b.md": self.page() + "\n- Claim 1 [E: file:missing.txt]\n"})
        files = review_queue.queue(self.kb)["teams"][0]["files"]
        self.assertEqual(files[0]["file"], "claims/b.md")

    def test_team_approver_certifies_only_own_files(self):
        batch = self.locked_with_pending()
        with self.assertRaises(kb_gate.GateError) as cm:
            kb_gate.certify(self.kb, batch, "Cleo Claims", ["billing/y.md"])
        self.assertIn("Billing Team", str(cm.exception))
        with self.assertRaises(kb_gate.GateError):
            kb_gate.certify(self.kb, batch, "Cleo Claims", ["context/z.md"])
        self.assertEqual(kb_gate.certify(self.kb, batch, "Cleo Claims", ["claims/x.md"]), 1)
        self.assertEqual(kb_gate.load_state(self.kb)["files"]["claims/x.md"]["by"], "Cleo Claims")
        self.assertIn("Claims Team", kb_gate.load_state(self.kb)["files"]["claims/x.md"]["role"])

    def test_lead_certifies_anything(self):
        batch = self.locked_with_pending()
        self.assertEqual(kb_gate.certify(self.kb, batch, "Raj Dev"), 3)
        self.assertEqual(kb_gate.check(self.kb)[0], [])

    def test_stranger_still_refused(self):
        batch = self.locked_with_pending()
        with self.assertRaises(kb_gate.GateError):
            kb_gate.certify(self.kb, batch, "Pat Analyst")

    def test_giver_cannot_certify_own_document(self):
        batch = self.locked_with_pending(given_by="Cleo Claims")
        with self.assertRaises(kb_gate.GateError) as cm:
            kb_gate.certify(self.kb, batch, "Cleo Claims", ["claims/x.md"])
        self.assertIn("gave the document", str(cm.exception))
        self.assertEqual(kb_gate.certify(self.kb, batch, "Ana Lead", ["claims/x.md"]), 1)

    def test_plan_writes_one_body_per_team(self):
        self.locked_with_pending()
        rows = {p["team"]: p for p in review_queue.plan(self.kb, "2026-01-02")}
        self.assertEqual(rows["Claims Team"]["branch"], "metis/2026-01-02-review-claims-team")
        with open(rows["Claims Team"]["body_file"], encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("claims/x.md", body)
        self.assertNotIn("billing/y.md", body)
        self.assertIn("Cleo Claims", body)
        self.assertNotIn(review_queue.QUEUE_DIR, kb_gate.batches(self.kb))

    def test_certify_team_across_batches(self):
        kb_gate.lock(self.kb, "Ana Lead")
        self.stage({"claims/x.md": self.page()}, "one")
        self.stage({"claims/w.md": self.page(), "billing/y.md": self.page()}, "two")
        self.assertEqual(review_queue.certify_team(self.kb, "claims team", "Cleo Claims"), 2)
        left = [g["team"] for g in review_queue.queue(self.kb)["teams"]]
        self.assertEqual(left, ["Billing Team"])
        with self.assertRaises(kb_gate.GateError):
            review_queue.certify_team(self.kb, "Claims Team", "Cleo Claims")

    def test_no_teams_keeps_old_behaviour(self):
        self.profile({"owners": PROFILE["owners"]})
        kb_gate.lock(self.kb, "Ana Lead")
        batch = self.stage({"claims/x.md": self.page()})
        groups = review_queue.queue(self.kb)["teams"]
        self.assertEqual([g["team"] for g in groups], [kb_gate.UNASSIGNED])
        self.assertEqual(kb_gate.certify(self.kb, batch, "Raj Dev"), 1)

    def test_certify_area_by_folder_and_glob(self):
        kb_gate.lock(self.kb, "Ana Lead")
        self.stage({"claims/x.md": self.page(), "claims/sub/w.md": self.page()}, "one")
        self.stage({"billing/y.md": self.page()}, "two")
        # Certify by folder prefix "claims"
        self.assertEqual(review_queue.certify_area(self.kb, "claims", "Ana Lead"), 2)
        # Billing remains
        left = [g["team"] for g in review_queue.queue(self.kb)["teams"]]
        self.assertEqual(left, ["Billing Team"])
        # Certify billing by glob "billing/*"
        self.assertEqual(review_queue.certify_area(self.kb, "billing/*", "Ana Lead"), 1)
        self.assertEqual(len(review_queue.queue(self.kb)["teams"]), 0)

    def test_certify_area_nothing_waiting(self):
        kb_gate.lock(self.kb, "Ana Lead")
        with self.assertRaises(kb_gate.GateError) as cm:
            review_queue.certify_area(self.kb, "nonexistent", "Ana Lead")
        self.assertIn("nothing is waiting for area", str(cm.exception))

    def test_cli(self):
        self.locked_with_pending()
        self.assertEqual(review_queue.main(["queue", self.kb]), 0)
        self.assertEqual(review_queue.main(["plan", self.kb, "--date", "2026-01-02"]), 0)
        self.assertEqual(review_queue.main(["certify", self.kb, "--team", "Nobody", "--by", "Ana Lead"]), 2)
        self.assertEqual(review_queue.main(["certify", self.kb, "--area", "claims", "--by", "Cleo Claims"]), 0)


if __name__ == "__main__":
    unittest.main()
