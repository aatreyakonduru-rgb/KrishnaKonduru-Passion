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

import glossary  # noqa: E402
import kb_gate  # noqa: E402
import screens_glossary  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class TestGlossaryModelAndGate(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        os.makedirs(self.kb, exist_ok=True)
        write(
            os.path.join(self.kb, ".metis", "kb-profile.yaml"),
            yaml.safe_dump({
                "product": {"name": "Demo Clinic"},
                "owners": {
                    "kb_owner": "Ana Lead",
                    "roles": {"dev lead": "Raj Dev", "business analyst": "Sam BSA"},
                },
            }),
        )
        write(os.path.join(self.kb, "db", "PETS.md"), "# PETS\nPets registered.\n")
        write(os.path.join(self.kb, "db", "OWNERS.md"), "# OWNERS\nOwners of pets.\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_load_empty_and_save(self):
        data = glossary.load(self.kb)
        self.assertEqual(data, {"entries": []})

        entry = {
            "term": "owner",
            "synonyms": ["customer", "client"],
            "meaning": "Person who owns a registered pet.",
            "where_in_kb": ["db/OWNERS.md"],
            "added_by": "Sam BSA",
            "added_on": "2025-01-01",
        }
        glossary.save(self.kb, {"entries": [entry]})
        loaded = glossary.load(self.kb)
        self.assertEqual(len(loaded["entries"]), 1)
        self.assertEqual(loaded["entries"][0]["term"], "owner")
        self.assertEqual(loaded["entries"][0]["synonyms"], ["customer", "client"])

    def test_add_and_exactness(self):
        # Adding entry before lock with a valid user
        e = glossary.add(
            self.kb,
            "Pet Owner (Active)",
            "customer, client, pet parent",
            "A registered pet owner with at least one active pet.",
            "db/OWNERS.md, db/PETS.md",
            "Sam BSA",
        )
        # Term must be exactly what was saved
        self.assertEqual(e["term"], "Pet Owner (Active)")
        self.assertEqual(e["synonyms"], ["customer", "client", "pet parent"])
        self.assertEqual(e["where_in_kb"], ["db/OWNERS.md", "db/PETS.md"])
        self.assertEqual(e["added_by"], "Sam BSA")
        self.assertTrue(bool(e["added_on"]))

        # Duplicate term should raise UiError
        with self.assertRaises(C.UiError):
            glossary.add(self.kb, "pet owner (active)", "", "duplicate", "", "Sam BSA")

        # Empty term should raise UiError
        with self.assertRaises(C.UiError):
            glossary.add(self.kb, "   ", "", "meaning", "", "Sam BSA")

    def test_update_and_remove(self):
        glossary.add(self.kb, "owner", ["customer"], "An owner", ["db/OWNERS.md"], "Sam BSA")
        glossary.add(self.kb, "vet", ["doctor"], "A veterinarian", [], "Sam BSA")

        # Update owner
        updated = glossary.update(
            self.kb,
            "owner",
            ["customer", "client"],
            "A person who owns pets.",
            ["db/OWNERS.md"],
            "Sam BSA",
        )
        self.assertEqual(updated["synonyms"], ["customer", "client"])
        self.assertEqual(updated["meaning"], "A person who owns pets.")

        # Rename vet to veterinarian
        renamed = glossary.update(
            self.kb,
            "veterinarian",
            ["vet", "doctor"],
            "Medical specialist.",
            [],
            "Sam BSA",
            old_term="vet",
        )
        self.assertEqual(renamed["term"], "veterinarian")

        # Attempt to rename to an existing term -> raises UiError
        with self.assertRaises(C.UiError):
            glossary.update(self.kb, "owner", [], "meaning", [], "Sam BSA", old_term="veterinarian")

        # Remove veterinarian
        removed = glossary.remove(self.kb, "veterinarian", "Sam BSA")
        self.assertEqual(removed, "veterinarian")

        # Removing again raises UiError
        with self.assertRaises(C.UiError):
            glossary.remove(self.kb, "veterinarian", "Sam BSA")

    def test_secrets_screening(self):
        with self.assertRaises(C.UiError):
            glossary.add(
                self.kb,
                "API Term",
                [],
                "The secret key is api_key = '" + "sk_" + "live_1234567890abcdef1234567890" + "'",  # joined so the source holds no key-shaped literal
                [],
                "Sam BSA",
            )

        with self.assertRaises(C.UiError):
            glossary.add(
                self.kb,
                "Password Field",
                ["password = testsecretpassword123"],
                "A password definition",
                [],
                "Sam BSA",
            )

    def test_kb_gate_rules(self):
        # Empty user name raises UiError
        with self.assertRaises(C.UiError):
            glossary.add(self.kb, "term1", [], "meaning", [], "")

        # Before lock: any named user can add/edit
        glossary.add(self.kb, "term1", ["syn1"], "meaning1", ["db/PETS.md"], "Any Person")
        self.assertEqual(len(glossary.load(self.kb)["entries"]), 1)

        # Lock the KB
        write(
            os.path.join(self.kb, ".metis", "certified.yaml"),
            yaml.safe_dump({"locked": True, "locked_by": "Ana Lead", "files": {}}),
        )
        self.assertTrue(kb_gate.is_locked(self.kb))

        # After lock: non-lead user (Any Person or Sam BSA who is not a lead) cannot change
        with self.assertRaises(C.UiError):
            glossary.add(self.kb, "term2", [], "meaning2", [], "Any Person")

        with self.assertRaises(C.UiError):
            glossary.update(self.kb, "term1", [], "new meaning", [], "Any Person")

        with self.assertRaises(C.UiError):
            glossary.remove(self.kb, "term1", "Any Person")

        # After lock: named lead (Ana Lead or Raj Dev) can change
        e2 = glossary.add(self.kb, "term2", ["syn2"], "meaning2", ["db/PETS.md"], "Ana Lead")
        self.assertEqual(e2["term"], "term2")

        up = glossary.update(self.kb, "term2", ["syn2_updated"], "meaning2 updated", [], "Raj Dev")
        self.assertEqual(up["synonyms"], ["syn2_updated"])

        rm = glossary.remove(self.kb, "term2", "Ana Lead")
        self.assertEqual(rm, "term2")

    def test_problems_detection(self):
        # Clean state has 0 problems
        glossary.add(self.kb, "owner", ["customer"], "Owner of pets", ["db/OWNERS.md"], "Sam BSA")
        self.assertEqual(glossary.problems(self.kb), [])

        # Add problem 1: missing KB page
        glossary.add(self.kb, "visit", ["appointment"], "A vet visit", ["db/NON_EXISTENT.md"], "Sam BSA")
        probs = glossary.problems(self.kb)
        self.assertTrue(any("page does not exist" in p for p in probs))

        # Add problem 2: empty meaning
        glossary.add(self.kb, "pet", ["animal"], "", ["db/PETS.md"], "Sam BSA")
        probs = glossary.problems(self.kb)
        self.assertTrue(any("meaning is empty" in p for p in probs))

        # Add problem 3: duplicate synonym across terms
        glossary.add(self.kb, "client", ["customer"], "Client of clinic", ["db/OWNERS.md"], "Sam BSA")
        probs = glossary.problems(self.kb)
        self.assertTrue(any("used by multiple terms" in p for p in probs))

    def test_expand(self):
        glossary.add(
            self.kb,
            "owner",
            ["customer", "client", "pet parent"],
            "Person who owns pets.",
            ["db/OWNERS.md"],
            "Sam BSA",
        )
        glossary.add(
            self.kb,
            "vet",
            ["veterinarian", "doctor"],
            "Medical specialist.",
            ["db/PETS.md"],
            "Sam BSA",
        )

        # Question mentioning synonym 'customer'
        exp1 = glossary.expand(self.kb, "Which customer has the most visits?")
        self.assertIn("owner", exp1["terms"])
        self.assertIn("customer", exp1["extra_words"])
        self.assertIn("client", exp1["extra_words"])
        self.assertIn("owner", exp1["extra_words"])

        # Question mentioning canonical term 'vet'
        exp2 = glossary.expand(self.kb, "List every vet in the database.")
        self.assertIn("vet", exp2["terms"])
        self.assertIn("veterinarian", exp2["extra_words"])
        self.assertIn("doctor", exp2["extra_words"])

        # Question with multi-word synonym
        exp3 = glossary.expand(self.kb, "Is there a pet parent registered with no pets?")
        self.assertIn("owner", exp3["terms"])
        self.assertIn("pet parent", exp3["extra_words"])

        # Question with unrelated words
        exp4 = glossary.expand(self.kb, "What is the capital of France?")
        self.assertEqual(exp4["terms"], [])
        self.assertEqual(exp4["extra_words"], [])


class TestScreensGlossary(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        os.makedirs(self.kb, exist_ok=True)
        write(
            os.path.join(self.kb, ".metis", "kb-profile.yaml"),
            yaml.safe_dump({
                "product": {"name": "Demo Clinic"},
                "owners": {"kb_owner": "Ana Lead"},
            }),
        )
        write(os.path.join(self.kb, "db", "PETS.md"), "# PETS\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_screen_render_and_escaping(self):
        glossary.add(
            self.kb,
            '<script>alert("term")</script>',
            ['<b>xss</b>'],
            'Meaning with <img src="x" onerror="alert(1)"> and markdown **bold**',
            ['db/PETS.md'],
            "Sam BSA",
        )

        ctx = C.Ctx(self.kb, "tok123", "Sam BSA")
        html = screens_glossary.glossary_view(ctx, {})

        # Should be escaped
        self.assertNotIn('<script>alert("term")</script>', html)
        self.assertIn('&lt;script&gt;alert(&quot;term&quot;)&lt;/script&gt;', html)
        self.assertIn('&lt;b&gt;xss&lt;/b&gt;', html)
        self.assertIn("<b>bold</b>", html)
        self.assertIn('href="/files?page=db/PETS.md"', html)

    def test_screen_search_filtering(self):
        glossary.add(self.kb, "owner", ["customer"], "Owner of pets", ["db/PETS.md"], "Sam BSA")
        glossary.add(self.kb, "vet", ["doctor"], "Veterinarian", ["db/PETS.md"], "Sam BSA")

        ctx = C.Ctx(self.kb, "tok123", "Sam BSA")
        # Search for vet
        html_vet = screens_glossary.glossary_view(ctx, {"q": "vet"})
        self.assertIn("vet", html_vet)
        self.assertNotIn("<h3>owner</h3>", html_vet)

        # Search for customer
        html_cust = screens_glossary.glossary_view(ctx, {"q": "customer"})
        self.assertIn("owner", html_cust)
        self.assertNotIn("<h3>vet</h3>", html_cust)

    def test_screen_actions(self):
        ctx = C.Ctx(self.kb, "tok123", "Sam BSA")

        # Add action
        f_add = {
            "term": "billing",
            "synonyms": "invoicing, payment",
            "meaning": "Financial transactions",
            "where_in_kb": "db/PETS.md",
        }
        where, msg = screens_glossary.act_glossary_add(ctx, f_add)
        self.assertEqual(where, "/glossary")
        self.assertIn("Added term 'billing'", msg)
        self.assertEqual(len(glossary.load(self.kb)["entries"]), 1)

        # Edit action
        f_edit = {
            "old_term": "billing",
            "term": "billing_account",
            "synonyms": "invoicing",
            "meaning": "Account for payments",
            "where_in_kb": "db/PETS.md",
        }
        where2, msg2 = screens_glossary.act_glossary_edit(ctx, f_edit)
        self.assertEqual(where2, "/glossary")
        self.assertIn("Updated term 'billing_account'", msg2)
        self.assertEqual(glossary.load(self.kb)["entries"][0]["term"], "billing_account")

        # Remove action
        f_rm = {"term": "billing_account"}
        where3, msg3 = screens_glossary.act_glossary_remove(ctx, f_rm)
        self.assertEqual(where3, "/glossary")
        self.assertIn("Removed term 'billing_account'", msg3)
        self.assertEqual(len(glossary.load(self.kb)["entries"]), 0)


if __name__ == "__main__":
    unittest.main()
