import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kb_gate  # noqa: E402
import kb_promote  # noqa: E402
import sensitive  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev", "db_owner": "", "roles": {"data lead": "Dee Data", "manager": "Max Boss"}}}


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class Sensitive(unittest.TestCase):
    def kinds(self, text, level=None):
        return {f["kind"] for f in sensitive.scan(text) if level in (None, f["level"])}

    def test_blocks(self):
        self.assertIn("credential", self.kinds("password: Hunter2hunter", "block"))
        self.assertIn("social security number", self.kinds("ssn 123-45-6789", "block"))
        self.assertIn("private key", self.kinds("-----BEGIN RSA PRIVATE KEY-----", "block"))
        self.assertIn("connection string with password", self.kinds("jdbc url postgres://app:s3cretpw@db.local/x", "block"))
        self.assertIn("card number", self.kinds("card 4111 1111 1111 1111", "block"))
        self.assertIn("cloud key", self.kinds("AKIAABCDEFGHIJKLMNOP", "block"))

    def test_review(self):
        k = self.kinds("Contact jane.doe@example.com or 555-123-4567. Member ID: 123456789. DOB 01/02/1980", "review")
        self.assertTrue({"email address", "phone number", "personal or health id", "date of birth"} <= k)

    def test_clean_and_placeholders(self):
        self.assertEqual(sensitive.scan("Claims are paid within 30 days. password: <set in vault>"), [])
        self.assertEqual(sensitive.scan("order 1234 5678 9012 3456"), [])  # fails Luhn

    def test_samples_are_masked(self):
        f = sensitive.scan("password: Hunter2hunter")[0]
        self.assertNotIn("Hunter2", f["sample"])


class Gate(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pay in 30 days\n")
        write(os.path.join(self.kb, "context", "a.md"), "# A\n\n- Pay in 30 days [E: file:rules.txt]\n")
        write(os.path.join(self.kb, "KNOWLEDGE-MANIFEST.yaml"), "x: 1\n")

    def tearDown(self):
        rmtree(self.d)

    def page(self, text="- Pay in 30 days [E: file:rules.txt]\n", given_by="Pat Analyst"):
        return "---\ntitle: B\ndocuments:\n- {id: d1, name: rules.docx, given_by: %s}\n---\n# B\n\n%s" % (given_by, text)

    def stage(self, rel, text, name="docs"):
        src = os.path.join(self.d, "src-" + name)
        write(os.path.join(src, rel), text)
        batch = kb_gate.new_batch(self.kb, name)
        kb_gate.propose(self.kb, batch, src)
        return batch

    def test_open_until_locked(self):
        self.assertEqual(kb_gate.check(self.kb), ([], False))
        with self.assertRaises(kb_gate.GateError):
            kb_gate.propose(self.kb, "b", self.d)

    def test_lock_needs_a_named_lead(self):
        with self.assertRaises(kb_gate.GateError):
            kb_gate.lock(self.kb, "Pat Analyst")
        with self.assertRaises(kb_gate.GateError):
            kb_gate.lock(self.kb, "")
        self.assertEqual(kb_gate.lock(self.kb, "ana lead"), 1)
        self.assertEqual(kb_gate.check(self.kb), ([], True))
        with self.assertRaises(kb_gate.GateError):
            kb_gate.lock(self.kb, "Ana Lead")

    def test_lock_refuses_unsourced_kb(self):
        write(os.path.join(self.kb, "context", "bad.md"), "- no source here\n")
        with self.assertRaises(kb_gate.GateError):
            kb_gate.lock(self.kb, "Ana Lead")

    def test_direct_edit_is_caught(self):
        kb_gate.lock(self.kb, "Ana Lead")
        write(os.path.join(self.kb, "context", "a.md"), "# A\n\n- Pay in 60 days [E: file:rules.txt]\n")
        write(os.path.join(self.kb, "context", "new.md"), "# N\n\n- x [E: file:rules.txt]\n")
        os.remove(os.path.join(self.kb, "KNOWLEDGE-MANIFEST.yaml"))
        probs, _ = kb_gate.check(self.kb)
        self.assertEqual(len(probs), 2)
        self.assertTrue(any("a.md: changed" in p for p in probs))
        self.assertTrue(any("new.md: not certified" in p for p in probs))

    def test_crlf_does_not_count_as_change(self):
        kb_gate.lock(self.kb, "Ana Lead")
        p = os.path.join(self.kb, "context", "a.md")
        with open(p, "rb") as fh:
            data = fh.read().replace(b"\n", b"\r\n")
        with open(p, "wb") as fh:
            fh.write(data)
        self.assertEqual(kb_gate.check(self.kb)[0], [])

    def test_staged_page_is_not_in_the_kb_until_certified(self):
        kb_gate.lock(self.kb, "Ana Lead")
        batch = self.stage("context/b.md", self.page())
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "b.md")))
        self.assertEqual(kb_gate.check(self.kb)[0], [])
        path, rows = kb_gate.digest(self.kb, batch)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(rows[0]["file"], "context/b.md")
        self.assertEqual(rows[0]["given_by"], ["Pat Analyst"])
        self.assertEqual(kb_gate.certify(self.kb, batch, "Raj Dev"), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "context", "b.md")))
        self.assertEqual(kb_gate.check(self.kb)[0], [])
        c = kb_gate.load_state(self.kb)["files"]["context/b.md"]
        self.assertEqual((c["by"], c["role"], c["batch"]), ("Raj Dev", "app owner", batch))
        self.assertFalse(os.path.exists(kb_gate.pending_dir(self.kb, batch)))
        with open(os.path.join(self.kb, ".metis", "CERTIFICATIONS.log"), encoding="utf-8") as fh:
            self.assertIn("Raj Dev", fh.read())

    def test_only_a_lead_certifies(self):
        kb_gate.lock(self.kb, "Ana Lead")
        batch = self.stage("context/b.md", self.page())
        for who in ("Pat Analyst", "", "Max Boss"):  # Max Boss is "manager": not a lead role
            with self.assertRaises(kb_gate.GateError):
                kb_gate.certify(self.kb, batch, who)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "b.md")))
        self.assertEqual(kb_gate.certify(self.kb, batch, "Dee Data"), 1)  # "data lead" role

    def test_giver_does_not_certify_own_document(self):
        kb_gate.lock(self.kb, "Ana Lead")
        batch = self.stage("context/b.md", self.page(given_by="Raj Dev"))
        with self.assertRaises(kb_gate.GateError) as cm:
            kb_gate.certify(self.kb, batch, "Raj Dev")
        self.assertIn("gave the document", str(cm.exception))
        self.assertEqual(kb_gate.certify(self.kb, batch, "Ana Lead"), 1)

    def test_secret_blocks_and_review_needs_a_note(self):
        kb_gate.lock(self.kb, "Ana Lead")
        bad = self.stage("context/b.md", self.page("- Login password: Hunter2hunter [E: file:rules.txt]\n"), "bad")
        with self.assertRaises(kb_gate.GateError):
            kb_gate.certify(self.kb, bad, "Ana Lead", accept_review="fine")
        pii = self.stage("context/c.md", self.page("- Ask jane.doe@example.com [E: file:rules.txt]\n"), "pii")
        with self.assertRaises(kb_gate.GateError):
            kb_gate.certify(self.kb, pii, "Ana Lead")
        self.assertEqual(kb_gate.certify(self.kb, pii, "Ana Lead", accept_review="work mailbox of the process owner"), 1)
        c = kb_gate.load_state(self.kb)["files"]["context/c.md"]
        self.assertEqual(c["accepted_review"], ["email address"])

    def test_source_problem_blocks_and_nothing_is_written(self):
        kb_gate.lock(self.kb, "Ana Lead")
        batch = self.stage("context/b.md", self.page("- Pay in 90 days [E: file:missing.txt]\n"))
        with self.assertRaises(kb_gate.GateError):
            kb_gate.certify(self.kb, batch, "Ana Lead")
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "b.md")))

    def test_change_archives_old_copy_and_removal_is_certified(self):
        kb_gate.lock(self.kb, "Ana Lead")
        batch = self.stage("context/a.md", "# A\n\n- Pay in 45 days [E: file:rules.txt]\n", "edit")
        rows = kb_gate.analyse(self.kb, batch)
        self.assertEqual((rows[0]["action"], rows[0]["lines_added"], rows[0]["lines_removed"]), ("change", 1, 1))
        kb_gate.certify(self.kb, batch, "Ana Lead")
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "Archive", batch, "context", "a.md")))
        rm = kb_gate.new_batch(self.kb, "drop")
        kb_gate.propose(self.kb, rm, None, ["context/a.md"])
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "context", "a.md")))
        kb_gate.certify(self.kb, rm, "Ana Lead")
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "a.md")))
        self.assertEqual(kb_gate.check(self.kb)[0], [])

    def test_reject_discards(self):
        kb_gate.lock(self.kb, "Ana Lead")
        batch = self.stage("context/b.md", self.page())
        with self.assertRaises(kb_gate.GateError):
            kb_gate.reject(self.kb, batch, "Ana Lead", "")
        self.assertEqual(kb_gate.reject(self.kb, batch, "Ana Lead", "out of date"), 2 - 1)
        self.assertEqual(kb_gate.batches(self.kb), [])

    def test_batch_names_do_not_collide(self):
        kb_gate.lock(self.kb, "Ana Lead")
        a = self.stage("context/b.md", self.page(), "docs")
        b = self.stage("context/c.md", self.page(), "docs")
        self.assertNotEqual(a, b)

    def test_pending_is_not_verified_or_walked(self):
        import verify_kb
        kb_gate.lock(self.kb, "Ana Lead")
        self.stage("context/b.md", "- unsourced line\n")
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])

    def test_promote_needs_a_lead_when_gated(self):
        kb_gate.lock(self.kb, "Ana Lead")
        stage = os.path.join(self.d, "stage")
        write(os.path.join(stage, "context", "p.md"), "# P\n\n- x [E: file:rules.txt]\n")
        with self.assertRaises(ValueError) as cm:
            kb_promote.promote(self.kb, stage, ["context/p.md"], "Pat Analyst")
        self.assertIn("not a lead", str(cm.exception))
        write(os.path.join(stage, "context", "q.md"), "# Q\n\n- key: AKIAABCDEFGHIJKLMNOP [E: file:rules.txt]\n")
        with self.assertRaises(ValueError):
            kb_promote.promote(self.kb, stage, ["context/q.md"], "Ana Lead")
        kb_promote.promote(self.kb, stage, ["context/p.md"], "Ana Lead")
        self.assertEqual(kb_gate.check(self.kb)[0], [])
        self.assertEqual(kb_gate.load_state(self.kb)["files"]["context/p.md"]["by"], "Ana Lead")

    def test_cli(self):
        self.assertEqual(kb_gate.main(["lock", self.kb, "--by", "Ana Lead"]), 0)
        self.assertEqual(kb_gate.main(["check", self.kb]), 0)
        write(os.path.join(self.kb, "context", "z.md"), "x\n")
        self.assertEqual(kb_gate.main(["check", self.kb]), 1)
        self.assertEqual(kb_gate.main(["status", self.kb]), 0)


if __name__ == "__main__":
    unittest.main()
