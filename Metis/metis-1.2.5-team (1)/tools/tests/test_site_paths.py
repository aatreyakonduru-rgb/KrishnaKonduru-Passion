import os
import re
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import site_paths  # noqa: E402

SCANNED = ["viz", "index", "etl_layer_lineage.py", "site_paths.py"]
# one team's names that must never be in the shared scripts: they belong in that team's profile
FORBIDDEN = re.compile(r"PCMS|MAGNOLIA|Magnolia|magnolia|elevance|bitbucket|ncr_dna1|ncr_aedleks|pcms-|PROVIDER CARE|CVBC", re.I)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class SiteSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "kb")
        self.env = {}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def profile(self, data):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(data))

    def test_scripts_hold_no_one_teams_names(self):
        hits = []
        for item in SCANNED:
            base = os.path.join(TOOLS, item)
            paths = [base] if os.path.isfile(base) else [os.path.join(d, f) for d, _, fs in os.walk(base) for f in fs]
            for p in paths:
                if not p.endswith((".py", ".js", ".html")):
                    continue
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh, 1):
                        if FORBIDDEN.search(line):
                            hits.append("%s:%d %s" % (os.path.relpath(p, TOOLS), n, line.strip()[:80]))
        self.assertEqual(hits, [], "team-specific names in shared scripts; move them to the profile (viz:)")

    def test_a_profile_with_no_viz_section_gives_neutral_defaults(self):
        self.profile({"product": {"name": "Orders Platform", "short_name": "ORD"}})
        s = site_paths.load(self.kb, self.env)
        self.assertEqual((s.name, s.short, s.org, s.logo), ("Orders Platform", "ORD", "", None))
        self.assertEqual(s.list_of("areas"), [])
        self.assertEqual(s.source_link(), (None, None))
        self.assertEqual(s.projects(), {})
        self.assertEqual(s.link("api", "a.py", "3", {}), "")
        self.assertEqual(s.recolor("color:#7c3aed"), "color:#7c3aed")

    def test_values_come_from_the_profile(self):
        write(os.path.join(self.kb, "brand", "logo.png"), "x")
        self.profile({"product": {"name": "N", "short_name": "S"}, "sources": {"workspace_root": os.path.join(self.tmp, "r")},
                      "viz": {"org_name": "Acme Corp", "title": "Acme KB", "primary_color": "#112233", "logo": "brand/logo.png",
                              "palette": {"#7C3AED": "#445566"},
                              "source_link": {"remote_regex": "git\\.acme\\.test/([^/]+)/", "url": "https://git.acme.test/{project}/{repo}/{path}#{line}"}}})
        s = site_paths.load(self.kb, self.env)
        self.assertEqual((s.org, s.title, s.primary), ("Acme Corp", "Acme KB", "#112233"))
        self.assertTrue(s.logo.endswith("logo.png"))
        self.assertEqual(s.repos, os.path.join(self.tmp, "r"))
        self.assertEqual(s.recolor("a{color:#7c3aed}"), "a{color:#445566}")
        self.assertEqual(s.link("api", "src/A.java", "7", {"api": "PAY"}), "https://git.acme.test/PAY/api/src/A.java#7")
        self.assertEqual(s.link("other", "x", "1", {"api": "PAY"}), "")

    def test_environment_overrides_the_folders(self):
        self.profile({"sources": {"workspace_root": "/from/profile"}})
        s = site_paths.load(self.kb, {"METIS_WORK": "/w", "METIS_REPOS": "/r"})
        self.assertEqual((s.work, s.repos), ("/w", "/r"))

    def test_no_kb_named_is_an_error_not_a_guess(self):
        with self.assertRaises(SystemExit):
            site_paths.load(None, {})


if __name__ == "__main__":
    unittest.main()
