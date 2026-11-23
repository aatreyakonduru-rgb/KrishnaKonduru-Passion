"""The conversation rule: people talk in plain words, nobody types a command.

These tests keep slash commands and user-only triggers out of the skills, rules and templates.
"""
import os
import re
import unittest

import yaml

PLUGIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SLASH = re.compile(r"(^|[\s`\"'(])/(metis|kb-|team-kb|cvbc-kb|app-|db-|etl-)[a-z-]*")


def files(folder, exts):
    root = os.path.join(PLUGIN, folder)
    for base, _dirs, names in os.walk(root):
        for n in names:
            if n.endswith(exts):
                yield os.path.join(base, n)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


class Conversation(unittest.TestCase):
    def test_no_slash_commands(self):
        bad = []
        for folder in ("skills", "rules", "templates"):
            for p in files(folder, (".md", ".yaml")):
                for i, line in enumerate(read(p).splitlines(), 1):
                    if SLASH.search(line):
                        bad.append("%s:%d %s" % (os.path.relpath(p, PLUGIN), i, line.strip()[:80]))
        self.assertEqual(bad, [])

    def test_skills_are_model_triggered_only(self):
        n = 0
        for p in files("skills", ("SKILL.md",)):
            text = read(p)
            self.assertTrue(text.startswith("---\n"), p)
            fm = yaml.safe_load(text.split("---\n", 2)[1])
            self.assertTrue(fm.get("name") and fm.get("description"), p)
            self.assertEqual(fm.get("triggers"), ["model"], p)
            n += 1
        self.assertGreaterEqual(n, 60)

    def test_no_broken_backtick_paths(self):
        pat = re.compile(r"(\$METIS|~|/tmp|/agents|/templates)`[A-Za-z]")
        bad = []
        for folder in ("skills", "rules", "templates"):
            for p in files(folder, (".md", ".yaml")):
                if pat.search(read(p)):
                    bad.append(os.path.relpath(p, PLUGIN))
        self.assertEqual(bad, [])

    def test_conversation_rule_is_always_on_and_covers_gate_and_feedback(self):
        text = read(os.path.join(PLUGIN, "rules", "metis-conversation.md"))
        self.assertIn("trigger: always_on", text)
        for word in ("Certification", "Feedback", "dislike", "named lead", "Never tell"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
