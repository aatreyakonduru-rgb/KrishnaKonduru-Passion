"""The sample SDLC roster in examples/acme must be placeholders only and hang together."""
# shared-copy sample: begin (install.py leaves these lines as Acme: they test the Acme example)
import os
import re
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
PEOPLE = os.path.join(os.path.dirname(os.path.dirname(HERE)), "examples", "acme", "people.yaml")


class SampleRosterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PEOPLE, encoding="utf-8") as fh:
            cls.roster = yaml.safe_load(fh)
        cls.people = cls.roster["people"]
        cls.users = {p["jira_user"] for p in cls.people}

    def test_every_person_is_a_numbered_resource(self):
        for n, person in enumerate(self.people, start=1):
            self.assertEqual(person["name"], "Resource %d" % n)
            self.assertEqual(person["jira_user"], "resource%d" % n)
            self.assertEqual(person["email"], "resource%d@acme.example" % n)
            self.assertIsNone(person.get("devin_user_id"))

    def test_owner_backups_and_delegates_are_people_on_the_roster(self):
        owner = self.roster["owner"]
        for user in [owner["primary"]] + list(owner.get("backups") or []):
            self.assertIn(user, self.users)
        for person in self.people:
            if person.get("delegate_to"):
                self.assertIn(person["delegate_to"], self.users, person["name"])

    def test_every_person_has_roles(self):
        for person in self.people:
            self.assertTrue(person.get("roles"), person["name"])
            self.assertTrue(person.get("primary_role"), person["name"])

    def test_source_page_and_signoff_are_placeholders(self):
        source = self.roster["source"]
        self.assertEqual(source["confluence_page_id"], "{{CONFLUENCE_ROSTER_PAGE_ID}}")
        self.assertEqual(source["confluence_title"], "{{PRODUCT}} Team Roster")
        self.assertEqual(self.roster["owner"]["signoff"]["status"], "pending")
        self.assertIsNone(self.roster["owner"]["signoff"]["signed_by"])

    def test_access_rules_name_roles_someone_holds(self):
        access = self.roster["access"]
        held = {r for p in self.people for r in p.get("roles") or []}
        self.assertTrue(set(access["default_roles"]) <= held)
        self.assertEqual(access["no_self_approval"], ["SDLC_05_CODE_REVIEW"])
        for area in access["areas"]:
            self.assertTrue(area["paths"], area["name"])
            for role in area["roles"]:
                self.assertTrue(role == "any" or role in held, "%s: nobody holds %s" % (area["name"], role))

    def test_no_real_user_ids_or_work_emails(self):
        with open(PEOPLE, encoding="utf-8") as fh:
            text = fh.read()
        self.assertFalse(re.search(r"\b[A-Z]{2}\d{5}\b", text))
        emails = re.findall(r"[\w.+-]+@[\w.-]+", text)
        self.assertTrue(emails)
        self.assertTrue(all(e.endswith("@acme.example") for e in emails), emails)


if __name__ == "__main__":
    unittest.main()
# shared-copy sample: end
