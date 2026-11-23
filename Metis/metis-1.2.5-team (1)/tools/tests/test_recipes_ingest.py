import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kb_gate  # noqa: E402
import recipes_ingest as R  # noqa: E402
import verify_kb  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"}}

RUNBOOK = """# Deploy runbook

Intro text that is not a step.

## Deploy the API

1. Pull the release tag with `git pull --tags`
2. Run the migration:

```bash
./mvnw flyway:migrate
```

3. Restart the service on prod with `kubectl rollout restart deploy/api`

## Roll back

1. Delete the bad release with `helm uninstall api`
2. Set the token: export API_TOKEN=abcd1234efgh5678

## Contacts

Call the on-call person.
"""

README = """# Project

Some words.

## Build and test

```
make build
make test
```

## License

MIT, run `cat LICENSE`.
"""

MAKEFILE = """.PHONY: build clean
build: deps
\tmvn -q package

clean:
\trm -rf target
\t@echo done

VAR := 1
"""

PACKAGE = """{
  "name": "x",
  "scripts": {
    "build": "tsc -p .",
    "test": "jest --ci",
    "deploy:prod": "sh deploy.sh prod"
  }
}
"""

GITLAB = """stages: [build]
image: maven:3

build-job:
  stage: build
  script:
    - mvn -B package
    - echo "built"

deploy-job:
  script:
    - ./deploy.sh production
"""

GHA = """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: pytest -q
"""

JENKINS = """pipeline {
  stages {
    stage('Build') { steps { sh 'mvn package' } }
    stage('Clean') { steps { sh 'rm -rf build' } }
  }
}
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Recipes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        self.repo = os.path.join(self.d, "app")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump(dict(PROFILE, sources={"repos": {"app": self.repo}})))
        write(os.path.join(self.repo, "docs", "runbooks", "deploy.md"), RUNBOOK)
        write(os.path.join(self.repo, "README.md"), README)
        write(os.path.join(self.repo, "Makefile"), MAKEFILE)
        write(os.path.join(self.repo, "package.json"), PACKAGE)
        write(os.path.join(self.repo, ".gitlab-ci.yml"), GITLAB)
        write(os.path.join(self.repo, ".github", "workflows", "ci.yml"), GHA)
        write(os.path.join(self.repo, "Jenkinsfile"), JENKINS)
        write(os.path.join(self.repo, "src", "notes.md"), "# Notes\n\n1. Not a runbook `rm -rf /`\n")

    def tearDown(self):
        rmtree(self.d)

    def pages(self):
        pages, _ = R.plan_repo(self.kb, "app")
        return {p["rel"]: p for p in pages}

    def test_recognises_the_sources_and_ignores_others(self):
        got = {rel: p["kind"] for rel, p in self.pages().items()}
        self.assertEqual(got, {"docs/runbooks/deploy.md": "runbook", "README.md": "contributing", "Makefile": "make",
                               "package.json": "npm", ".gitlab-ci.yml": "ci", ".github/workflows/ci.yml": "ci",
                               "Jenkinsfile": "jenkins"})

    def test_runbook_steps_in_order_with_commands_verbatim(self):
        text = R.render(self.pages()["docs/runbooks/deploy.md"], "procedures")
        self.assertIn("## Deploy the API", text)
        a = text.index("`git pull --tags`")
        b = text.index("`./mvnw flyway:migrate`")
        c = text.index("`kubectl rollout restart deploy/api`")
        self.assertTrue(a < b < c)
        self.assertIn('1. `git pull --tags` [E: app/docs/runbooks/deploy.md:7 "', text)
        self.assertNotIn("Call the on-call person", text)

    def test_needs_confirm_flags(self):
        text = R.render(self.pages()["docs/runbooks/deploy.md"], "procedures")
        flagged = [l for l in text.splitlines() if "**needs-confirm**" in l]
        self.assertEqual(len(flagged), 2)       # kubectl ... on prod, helm uninstall (the line says "Delete")
        self.assertTrue(any("kubectl rollout restart" in l for l in flagged))
        self.assertFalse(any("git pull" in l for l in flagged))
        mk = R.render(self.pages()["Makefile"], "procedures")
        self.assertTrue(any("rm -rf target" in l and "needs-confirm" in l for l in mk.splitlines()))
        self.assertFalse(any("mvn -q package" in l and "needs-confirm" in l for l in mk.splitlines()))
        self.assertEqual(self.pages()["docs/runbooks/deploy.md"]["flagged"], 2)
        self.assertTrue(R.needs_confirm("DROP TABLE x"))
        self.assertFalse(R.needs_confirm("npm run product-list"))
        self.assertFalse(R.needs_confirm("git pull --prune"))

    def test_secret_step_left_out(self):
        text = R.render(self.pages()["docs/runbooks/deploy.md"], "procedures")
        self.assertNotIn("abcd1234efgh5678", text)
        self.assertEqual([o["kinds"] for o in self.pages()["docs/runbooks/deploy.md"]["omitted"]], [["credential"]])

    def test_readme_only_command_sections(self):
        text = R.render(self.pages()["README.md"], "procedures")
        self.assertIn("`make build`", text)
        self.assertIn("`make test`", text)
        self.assertNotIn("cat LICENSE", text)

    def test_make_npm_ci_jenkins(self):
        p = self.pages()
        mk = R.render(p["Makefile"], "procedures")
        self.assertIn("## make build", mk)
        self.assertIn("`make deps`", mk)
        self.assertIn("`mvn -q package`", mk)
        self.assertNotIn("VAR", mk)
        npm = R.render(p["package.json"], "procedures")
        self.assertIn("`npm run build`", npm)
        self.assertIn("`npm test`", npm)
        self.assertTrue(any("deploy:prod" in l and "needs-confirm" in l for l in npm.splitlines()))
        gl = R.render(p[".gitlab-ci.yml"], "procedures")
        self.assertIn("## job build-job", gl)
        self.assertIn("`mvn -B package`", gl)
        self.assertTrue(any("deploy.sh production" in l and "needs-confirm" in l for l in gl.splitlines()))
        gh = R.render(p[".github/workflows/ci.yml"], "procedures")
        self.assertIn("`pytest -q`", gh)
        self.assertNotIn("actions/checkout", gh)
        jk = R.render(p["Jenkinsfile"], "procedures")
        self.assertIn("`mvn package`", jk)
        self.assertTrue(any("rm -rf build" in l and "needs-confirm" in l for l in jk.splitlines()))

    def test_every_step_is_sourced_and_verifies(self):
        res = R.stage_repo(self.kb, "app")
        self.assertEqual(res["problems"], [])
        self.assertEqual(len(res["pages"]), 7)
        self.assertTrue(all(p.startswith("context/procedures/") for p in res["pages"]))
        rep = verify_kb.Checker(self.kb).run()
        self.assertEqual(rep["problems"], [])
        self.assertGreater(rep["tags"], 20)
        for rel in res["pages"]:
            body = read(os.path.join(self.kb, *rel.split("/"))).split("---\n", 2)[2]
            for line in body.splitlines():
                if line[:1].isdigit():
                    self.assertIn("[E: app/", line)

    def test_package_json_line_numbers_point_at_the_script(self):
        text = R.render(self.pages()["package.json"], "procedures")
        self.assertIn('[E: app/package.json:4 "', text)
        self.assertIn('[E: app/package.json:5 "', text)

    def test_locked_kb_stages_to_pending(self):
        write(os.path.join(self.kb, "context", "a.md"), "# A\n")
        kb_gate.lock(self.kb, "Ana Lead")
        res = R.stage_repo(self.kb, "app")
        self.assertTrue(res["batch"])
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "procedures")))
        self.assertEqual(len(kb_gate.pending_files(self.kb, res["batch"])), 7)
        self.assertEqual(kb_gate.certify(self.kb, res["batch"], "Ana Lead"), 7)
        self.assertTrue(os.path.isdir(os.path.join(self.kb, "context", "procedures")))

    def test_foreign_page_not_replaced_and_own_page_refreshed(self):
        rel = "context/procedures/app-makefile.md"
        write(os.path.join(self.kb, rel), "# Mine\n")
        res = R.stage_repo(self.kb, "app")
        self.assertIn("context/procedures/app-makefile.NEW.md", res["pages"])
        self.assertEqual(read(os.path.join(self.kb, rel)), "# Mine\n")
        R.stage_repo(self.kb, "app")
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "procedures", "app-makefile.NEW.NEW.md")))

    def test_dry_run_and_bad_args(self):
        res = R.stage_repo(self.kb, "app", dry=True)
        self.assertEqual(len(res["written"]), 7)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context")))
        with self.assertRaises(ValueError):
            R.plan_repo(self.kb, "nope")
        with self.assertRaises(ValueError):
            R.plan_repo(self.kb, "app", "../x")
        self.assertEqual(len(R.plan_repo(self.kb, "app", "docs")[0]), 1)

    def test_cli(self):
        self.assertEqual(R.main(["scan", self.kb, "--repo", "app"]), 0)
        self.assertEqual(R.main(["stage", self.kb, "--repo", "app", "--dry-run"]), 0)
        self.assertEqual(R.main(["stage", self.kb, "--repo", "zzz"]), 2)

    def test_invalid_package_json_is_ignored(self):
        write(os.path.join(self.repo, "package.json"), "{ not json")
        self.assertNotIn("package.json", self.pages())


if __name__ == "__main__":
    unittest.main()
