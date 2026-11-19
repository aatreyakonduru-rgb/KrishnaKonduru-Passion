import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import learn_more  # noqa: E402


def sample():
    return {
        "icebreakers": {"default": ["What do you wish Devin knew?"], "qa": ["Which areas break most?"]},
        "questions": [
            {"id": "L-001", "ask": "Resource 17", "question": "Ready statuses?", "update": "x", "status": "open",
             "asked_on": None},
            {"id": "L-002", "ask": "Resource 17", "question": "SIT link?", "update": "x", "status": "open",
             "asked_on": None},
            {"id": "L-003", "ask": "Resource 17", "question": "Old label?", "update": "x", "status": "open",
             "asked_on": None},
            {"id": "L-004", "ask": "D. Resource 2", "question": "DRE period?", "update": "y", "status": "answered",
             "asked_on": "2026-10-01"},
        ],
    }


class LearnMoreTest(unittest.TestCase):
    def test_related_finds_open_questions_and_doc_gaps_the_answer_may_settle(self):
        data = sample()
        data["questions"][0]["question"] = "Which statuses count as ready for release testing?"
        data["questions"][1]["question"] = "Do ready for release statuses close the story?"
        gaps = [{"document": "MODULES/x.md", "questions": ["[REQUIRES STAKEHOLDER INPUT] which release statuses?"]},
                {"document": "MODULES/y.md", "questions": ["[REQUIRES STAKEHOLDER INPUT] the SIT link"]}]
        rows = learn_more.related(data, "L-001", "Ready For Release and Closed", gaps)
        self.assertEqual([(r["kind"], r["id"]) for r in rows], [("question", "L-002"), ("doc gap", "MODULES/x.md")])
        self.assertIn("release", rows[0]["shared"])
        data["questions"][1]["status"] = "answered"
        self.assertEqual([r["id"] for r in learn_more.related(data, "L-001", "", gaps)], ["MODULES/x.md"])
        with self.assertRaises(KeyError):
            learn_more.related(data, "L-999")

    def test_for_person_open_only(self):
        rows = learn_more.for_person(sample(), "Resource 17".lower())
        self.assertEqual([q["id"] for q in rows], ["L-001", "L-002", "L-003"])
        self.assertEqual(learn_more.for_person(sample(), "D. Resource 2"), [])
        self.assertEqual(len(learn_more.for_person(sample(), "Resource 17")), 3)

    def test_pick_caps_per_person(self):
        data = sample()
        data["questions"][0]["asked_on"] = "2026-10-12"
        picked = learn_more.pick(data, per_person=2, today="2026-10-14")
        self.assertEqual([q["id"] for q in picked], ["L-002"])
        self.assertEqual(learn_more.pick(data, per_person=2, today="2026-10-15"), [])

    def test_answer(self):
        data = sample()
        q = learn_more.answer(data, "L-002", " linked by 'tests' ", "Resource 17", today="2026-10-14")
        self.assertEqual((q["status"], q["answer"], q["answered_on"]), ("answered", "linked by 'tests'", "2026-10-14"))
        with self.assertRaises(ValueError):
            learn_more.answer(data, "L-001", "  ", "Resource 17")
        with self.assertRaises(KeyError):
            learn_more.answer(data, "L-999", "a", "b")

    def test_add_numbers_next(self):
        q = learn_more.add(sample(), "Resource 16", "Which teams?", "z")
        self.assertEqual((q["id"], q["status"]), ("L-005", "open"))

    def test_next_question_then_icebreakers(self):
        data = sample()
        self.assertEqual(learn_more.next_question(data, "Resource 17")["id"], "L-001")
        know = {"people": {}}
        first = learn_more.next_question(data, "Ravi", "qa", know)
        self.assertEqual((first["kind"], first["question"]), ("icebreaker", "Which areas break most?"))
        learn_more.note(know, "Ravi", first["question"], "Exports", "qa", today="2026-10-14")
        self.assertEqual(learn_more.next_question(data, "Ravi", "qa", know)["question"], "What do you wish Devin knew?")
        learn_more.note(know, "Ravi", "What do you wish Devin knew?", "Nothing", "qa")
        self.assertIsNone(learn_more.next_question(data, "Ravi", "qa", know))
        with self.assertRaises(ValueError):
            learn_more.note(know, "Ravi", "q", " ")

    def test_story_question_before_icebreaker(self):
        data = dict(sample(), story_questions={"default": "On {key} ({summary}), how does it work?",
                                               "qa": "On {key}, what would you retest?"})
        know = {"people": {}}
        stories = [{"key": "ACME-1", "summary": "program year filter"}, {"key": "ACME-2", "summary": "export"}]
        q = learn_more.next_question(data, "Ravi", "developer", know, stories)
        self.assertEqual((q["kind"], q["story"]), ("story", "ACME-1"))
        self.assertEqual(q["question"], "On ACME-1 (program year filter), how does it work?")
        learn_more.note(know, "Ravi", q["question"], "Member List and Scorecard", "developer", story="ACME-1")
        self.assertEqual(learn_more.next_question(data, "Ravi", "developer", know, stories)["story"], "ACME-2")
        self.assertEqual(learn_more.next_question(data, "Ravi", "qa", {"people": {}}, stories)["question"],
                         "On ACME-1, what would you retest?")
        self.assertEqual(learn_more.next_question(data, "Resource 17", "qa", know, stories)["kind"], "question")
        self.assertEqual(learn_more.parse_story("ACME-9: a: b"), {"key": "ACME-9", "summary": "a: b"})

    def test_cli_previews_unless_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.yaml")
            with open(path, "w") as fh:
                fh.write("# head\n")
            learn_more.save(sample(), path)
            before = open(path).read()
            self.assertEqual(learn_more.main(["--file", path, "answer", "L-001", "--by", "Resource 17", "--text", "ok"]), 0)
            self.assertEqual(open(path).read(), before)
            self.assertEqual(learn_more.main(["--file", path, "answer", "L-001", "--by", "Resource 17", "--text", "ok", "--write"]), 0)
            self.assertTrue(open(path).read().startswith("# head\n"))
            self.assertEqual(learn_more.load(path)["questions"][0]["status"], "answered")

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_repo_file_loads(self):
        data = learn_more.load()
        self.assertTrue(data["questions"])
        self.assertIn("default", data["icebreakers"])
        self.assertIn("{key}", data["story_questions"]["default"])
        for q in data["questions"]:
            self.assertTrue(q["ask"] and q["question"] and q["status"] in ("open", "answered"), q)



class RosterIcebreakerTest(unittest.TestCase):
    def test_every_roster_role_has_its_own_icebreakers(self):
        import yaml
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
        with open(os.path.join(root, ".devin", "rules", "people.yaml"), encoding="utf-8") as fh:
            roles = {p.get("primary_role") for p in yaml.safe_load(fh)["people"] if p.get("primary_role")}
        with open(os.path.join(root, "docs", "knowledge-base", "SHARED", "learn-more.yaml"), encoding="utf-8") as fh:
            breakers = yaml.safe_load(fh)["icebreakers"]
        self.assertEqual(sorted(r for r in roles if not breakers.get(r)), [])

if __name__ == "__main__":
    unittest.main()
