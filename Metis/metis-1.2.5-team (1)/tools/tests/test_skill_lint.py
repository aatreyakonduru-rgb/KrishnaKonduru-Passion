import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import skill_lint as S  # noqa: E402


def put(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def skill(desc="Do a thing.", tools="[read]", body="Body text that is long enough to count as a line.\n"):
    return "---\nname: x\ndescription: %s\nallowed-tools: %s\n---\n%s" % (desc, tools, body)


class SkillLint(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def msgs(self, **kw):
        return [(f["level"], f["name"], f["message"]) for f in S.lint(self.root, **kw)["findings"]]

    def test_long_description_flagged(self):
        put(self.root, "skills/a/SKILL.md", skill(desc="word " * 200))
        put(self.root, "skills/b/SKILL.md", skill())
        f = self.msgs()
        self.assertTrue(any(n == "a" and "description" in m for _l, n, m in f))
        self.assertFalse(any(n == "b" for _l, n, _m in f))

    def test_missing_description_is_error(self):
        put(self.root, "skills/a/SKILL.md", "---\nname: a\n---\nbody\n")
        self.assertIn("error", [l for l, _n, _m in self.msgs()])
        self.assertEqual(S.main(["--root", self.root]), 1)

    def test_writer_without_evidence_rule(self):
        put(self.root, "skills/w/SKILL.md", skill(tools="[read, write]"))
        put(self.root, "skills/ok/SKILL.md", skill(tools="[read, write]", body="See metis-evidence rule for tags.\n"))
        f = self.msgs()
        self.assertTrue(any(n == "w" and "evidence" in m for _l, n, m in f))
        self.assertFalse(any(n == "ok" for _l, n, _m in f))

    def test_near_duplicates(self):
        shared = "".join("Shared instruction line number %d is the same here.\n" % i for i in range(10))
        put(self.root, "kb-prompts/P1.md", "# one\n" + shared)
        put(self.root, "kb-prompts/P2.md", "# two\n" + shared + "Only in two, a different line altogether.\n")
        put(self.root, "kb-prompts/P3.md", "# three\n" + "".join("Unrelated text %d with nothing in common.\n" % i for i in range(10)))
        f = self.msgs()
        self.assertTrue(any("P1.md ~ P2.md" == n for _l, n, _m in f))
        self.assertFalse(any("P3.md" in n for _l, n, _m in f))

    def test_strict_exit(self):
        put(self.root, "skills/a/SKILL.md", skill(desc="word " * 200))
        self.assertEqual(S.main(["--root", self.root]), 0)
        self.assertEqual(S.main(["--root", self.root, "--strict"]), 1)

    def test_shipped_skills_have_no_errors_or_cost_warnings(self):
        rep = S.lint()
        bad = [f for f in rep["findings"]
               if f["level"] == "error" or "description is" in f["message"] or "evidence" in f["message"]]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
