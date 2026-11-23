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

import kb_gate  # noqa: E402
import screens_compare as S  # noqa: E402
import ui_common as C  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"}}
OLD = "# Orders\n\n- Pay in 30 days [E: file:rules.txt]\n- Orders are shipped at once [E: file:rules.txt]\n"
NEW = "# Orders\n\n- Pay in 30 days [E: file:rules.txt]\n- Orders are shipped at once\n- Refunds take 5 days [E: file:rules.txt]\n"


class F(dict):
    def __init__(self, **kw):
        super().__init__({k: v for k, v in kw.items() if not isinstance(v, list)})
        self.multi = {k: v for k, v in kw.items() if isinstance(v, list)}

    def getall(self, k):
        return self.multi.get(k, [])


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class CompareBase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pay in 30 days\nrefunds in 5 days\n")
        write(os.path.join(self.kb, "ctx", "orders.md"), OLD)
        write(os.path.join(self.kb, "ctx", "gone.md"), "# Gone\n\n- Old fact [E: file:rules.txt]\n")
        write(os.path.join(self.kb, "ctx", "same.md"), "# Same\n\n- Same fact [E: file:rules.txt]\n")
        self.stage = os.path.join(self.kb, "_REGEN", "2026-01-01-kb")
        write(os.path.join(self.stage, "ctx", "orders.md"), NEW)
        write(os.path.join(self.stage, "ctx", "same.md"), "# Same\n\n- Same fact [E: file:rules.txt]\n")
        write(os.path.join(self.stage, "ctx", "fresh.md"), "# Fresh\n\n- New fact [E: file:rules.txt]\n")
        write(os.path.join(self.stage, "BUILD.md"), "# Build\n")
        self.key = "regen/2026-01-01-kb"
        self.ctx = C.Ctx(self.kb, "tok", "Pat Lee")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def promote(self, files, reason="Rebuild checked", user="Pat Lee", side=None):
        return S.act_promote(C.Ctx(self.kb, "tok", user), F(side=side or self.key, reason=reason, files=files))


class TestFolders(CompareBase):
    def test_only_existing_folders_are_offered(self):
        os.makedirs(os.path.join(self.kb, "_REGEN", ".hidden"))
        write(os.path.join(self.d, "Other KB", ".metis", "kb-profile.yaml"), "a: 1\n")
        os.makedirs(os.path.join(self.d, "random folder"))
        keys = [k for k, _, _ in S.sides(self.kb)]
        self.assertIn(self.key, keys)
        self.assertIn("kb/Other KB", keys)
        self.assertNotIn("kb/random folder", keys)
        self.assertNotIn("kb/KB", keys)
        self.assertFalse([k for k in keys if "hidden" in k])

    def test_traversal_and_outside_paths_are_refused(self):
        os.makedirs(os.path.join(self.d, "outside"))
        for bad in ("../outside", "regen/../..", "regen/..", "kb/../outside", self.d, os.path.join(self.d, "outside"),
                    "regen/nope", "kb/..", "", "regen/2026-01-01-kb/../..", "..\\outside"):
            with self.assertRaises(C.UiError, msg=bad):
                S.resolve(self.kb, bad)
        self.assertEqual(S.resolve(self.kb, self.key)[1], self.stage)

    def test_screen_with_bad_side_shows_error_and_no_files(self):
        html = S.compare_view(self.ctx, {"side": "../outside"})
        self.assertIn("not on the list", html)
        self.assertNotIn("Promote the ticked", html)

    def test_symlink_out_of_regen_is_refused(self):
        target = os.path.join(self.d, "elsewhere")
        write(os.path.join(target, "x.md"), "# X\n")
        link = os.path.join(self.kb, "_REGEN", "link")
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("cannot make a symlink here")
        with self.assertRaises(C.UiError):
            S.resolve(self.kb, "regen/link")


class TestCompare(CompareBase):
    def test_added_removed_changed_same(self):
        a = S.analyse(self.kb, self.key)
        self.assertEqual(a["added"], ["ctx/fresh.md"])
        self.assertEqual(a["changed"], ["ctx/orders.md"])
        self.assertEqual(a["same"], ["ctx/same.md"])
        self.assertEqual(a["removed"], ["ctx/gone.md"])
        self.assertNotIn("BUILD.md", a["rows"])

    def test_source_problem_counts_and_tag_changes(self):
        a = S.analyse(self.kb, self.key)
        row = a["rows"]["ctx/orders.md"]
        self.assertEqual(len(row["live_problems"]), 0)
        self.assertEqual(len(row["stage_problems"]), 1)  # "Orders are shipped at once" lost its tag
        self.assertEqual(a["stage_problems"], 1)
        kinds = sorted(t["what"] for t in row["tags"])
        self.assertEqual(kinds, ["loses"])
        lost = [t for t in row["tags"] if t["what"] == "loses"][0]
        self.assertIn("shipped at once", lost["before"])

    def test_screen_shows_everything_and_escapes(self):
        write(os.path.join(self.stage, "ctx", "orders.md"), NEW + "- <img src=x onerror=alert(1)> & \"q\" [E: file:rules.txt]\n")
        write(os.path.join(self.stage, "ctx", "a&b'.md"), "# <b>x</b>\n\n- t [E: file:rules.txt]\n")
        ctx = C.Ctx(self.kb, "tok", "<script>alert(1)</script>")
        html = S.compare_view(ctx, {"side": self.key})
        for want in ("ctx/fresh.md", "ctx/gone.md", "ctx/orders.md", "Added (2)", "Removed (1)", "Changed (1)"):
            self.assertIn(want, html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt; &amp; &quot;q&quot;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("ctx/a&amp;b&#x27;.md", html)
        self.assertNotIn("<b>x</b>", html)
        self.assertIn("loses a tag", html)

    def test_compare_changes_nothing(self):
        S.compare_view(self.ctx, {"side": self.key})
        self.assertEqual(read(os.path.join(self.kb, "ctx", "orders.md")), OLD)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "Archive")))

    def test_other_kb_folder(self):
        other = os.path.join(self.d, "Other")
        write(os.path.join(other, ".metis", "kb-profile.yaml"), "a: 1\n")
        write(os.path.join(other, "ctx", "orders.md"), "# Orders\n\n- Different [E: file:rules.txt]\n")
        write(os.path.join(other, "_EVIDENCE", "x.md"), "ignored\n")
        a = S.analyse(self.kb, "kb/Other")
        self.assertEqual(a["changed"], ["ctx/orders.md"])
        self.assertEqual(list(a["rows"]), ["ctx/orders.md"])


class TestPromoteOpen(CompareBase):
    def test_promote_into_open_kb_archives_and_records(self):
        self.assertFalse(kb_gate.is_locked(self.kb))
        where, msg = self.promote(["ctx/fresh.md", "ctx/orders.md"], reason="Checked <b>twice</b>")
        self.assertTrue(where.startswith("/compare?side=regen%2F"))
        self.assertIn("Promoted 2", msg)
        self.assertEqual(read(os.path.join(self.kb, "ctx", "orders.md")), NEW)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "ctx", "fresh.md")))
        self.assertEqual(read(os.path.join(self.kb, "Archive", C.today(), "ctx", "orders.md")), OLD)
        self.assertIn("Pat Lee", read(os.path.join(self.kb, "Archive", "PROMOTIONS.log")))
        log = read(os.path.join(self.kb, S.LOG))
        self.assertIn("Pat Lee", log)
        self.assertIn("Checked <b>twice</b>", log)
        html = S.compare_view(self.ctx, {})
        self.assertIn("Checked &lt;b&gt;twice&lt;/b&gt;", html)
        self.assertNotIn("<b>twice</b>", html)

    def test_needs_name_reason_and_files(self):
        with self.assertRaises(C.UiError) as e:
            self.promote(["ctx/fresh.md"], user="")
        self.assertIn("Say who you are", str(e.exception))
        with self.assertRaises(C.UiError):
            self.promote(["ctx/fresh.md"], reason="  ")
        with self.assertRaises(C.UiError):
            self.promote([])
        self.assertFalse(os.path.exists(os.path.join(self.kb, "ctx", "fresh.md")))

    def test_posted_paths_outside_the_folder_are_refused(self):
        write(os.path.join(self.d, "outside.md"), "# Out\n")
        write(os.path.join(self.d, "Escape.md"), "# E\n")
        for bad in ("../outside.md", "../../../Escape.md", "/etc/passwd", "..\\..\\outside.md", "ctx/nope.md", "ctx/same.md"):
            with self.assertRaises(C.UiError, msg=bad):
                self.promote([bad])
        self.assertFalse(os.path.exists(os.path.join(self.kb, "outside.md")))
        with self.assertRaises(C.UiError):
            self.promote(["ctx/fresh.md"], side="../outside")

    def test_keep_list_and_secrets_are_refused_in_plain_words(self):
        write(os.path.join(self.kb, ".metis", "kb-keep.yaml"), yaml.safe_dump({"keep": [{"path": "ctx/orders.md", "source": "a workbook"}]}))
        write(os.path.join(self.stage, "ctx", "secret.md"), "# S\n\n- password: Hunter2hunter [E: file:rules.txt]\n")
        a = S.analyse(self.kb, self.key)
        self.assertIn("keep list", a["rows"]["ctx/orders.md"]["refused"])
        self.assertIn("credential", a["rows"]["ctx/secret.md"]["refused"])
        self.assertIsNone(a["rows"]["ctx/fresh.md"]["refused"])
        html = S.compare_view(self.ctx, {"side": self.key})
        self.assertIn("Refused:", html)
        self.assertNotIn("Hunter2hunter", html)
        with self.assertRaises(C.UiError):
            self.promote(["ctx/orders.md"])
        with self.assertRaises(C.UiError):
            self.promote(["ctx/secret.md"])
        self.assertEqual(read(os.path.join(self.kb, "ctx", "orders.md")), OLD)

    def test_archive_clash_is_explained(self):
        write(os.path.join(self.kb, "Archive", C.today(), "ctx", "orders.md"), "older\n")
        a = S.analyse(self.kb, self.key)
        self.assertIn("will not overwrite", a["rows"]["ctx/orders.md"]["refused"])


class TestPromoteLocked(CompareBase):
    def setUp(self):
        super().setUp()
        kb_gate.lock(self.kb, "Ana Lead")

    def test_locked_kb_is_never_written(self):
        self.assertTrue(kb_gate.is_locked(self.kb))
        before = read(os.path.join(self.kb, "ctx", "orders.md"))
        where, msg = self.promote(["ctx/fresh.md", "ctx/orders.md"], reason="Rebuild after the audit")
        self.assertIn("Proposed 2", msg)
        self.assertEqual(read(os.path.join(self.kb, "ctx", "orders.md")), before)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "ctx", "fresh.md")))
        self.assertFalse(os.path.exists(os.path.join(self.kb, "Archive", C.today())))
        batches = kb_gate.batches(self.kb)
        self.assertEqual(len(batches), 1)
        self.assertEqual(kb_gate.pending_files(self.kb, batches[0]), ["ctx/fresh.md", "ctx/orders.md"])
        digest = read(os.path.join(kb_gate.pending_dir(self.kb, batches[0]), "DIGEST.md"))
        self.assertIn("Pat Lee", digest)
        self.assertIn("Rebuild after the audit", digest)
        self.assertIn("Pat Lee", read(os.path.join(self.kb, S.LOG)))
        self.assertEqual([d for d in os.listdir(os.path.join(self.kb, ".metis")) if d.startswith("compare-")], [])
        self.assertIn("KB is locked", S.compare_view(self.ctx, {"side": self.key}))

    def test_lock_still_needs_name_and_reason(self):
        with self.assertRaises(C.UiError):
            self.promote(["ctx/fresh.md"], user="")
        with self.assertRaises(C.UiError):
            self.promote(["ctx/fresh.md"], reason="")
        self.assertEqual(kb_gate.batches(self.kb), [])

    def test_locked_secret_and_traversal_still_refused(self):
        write(os.path.join(self.stage, "ctx", "secret.md"), "# S\n\n- password: Hunter2hunter [E: file:rules.txt]\n")
        with self.assertRaises(C.UiError):
            self.promote(["ctx/secret.md"])
        with self.assertRaises(C.UiError):
            self.promote(["../../x.md"])
        self.assertEqual(kb_gate.batches(self.kb), [])

    def test_same_file_ticked_twice_is_proposed_once(self):
        self.promote(["ctx/fresh.md", "ctx/fresh.md"])
        self.assertEqual(kb_gate.pending_files(self.kb, kb_gate.batches(self.kb)[0]), ["ctx/fresh.md"])
        self.assertEqual(kb_gate.check(self.kb)[0], [])


if __name__ == "__main__":
    unittest.main()
