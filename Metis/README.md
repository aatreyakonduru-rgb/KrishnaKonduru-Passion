# Metis (Mētis) 2.0

Builds a verifiable knowledge base (KB) from a team's code repos, databases, Confluence and Jira (all read only). Every line of the KB names its source with an `[E: ...]` tag; anything no source shows becomes a question for a named person. A lead certifies changes before they enter the KB, and a local web UI and an MCP server let people and agents ask it questions, get a token-budgeted context pack for a task, and rate the answers.

## Layout

| Path | What it is |
|---|---|
| `metis-1.2.5-team (1)/` | The plugin: `tools/` (Python tools and the web UI in `tools/ui/`), `skills/`, `rules/`, `kb-prompts/`, `templates/`, `tools/tests/`. The folder keeps its old name; the version in `.devin-plugin/plugin.json` and `pyproject.toml` is 2.0.0 (see TD-2 in `documentation/TECH-DEBT.md`). |
| `documentation/` | Manual (`Metis-2.0.0-manual.md`), gap analysis, implementation plan, technical-debt register, progress notes |
| `Metis-2.0.0-Release-Record.md` | What ships, what was built after, what is deferred and why |
| `Metis-2.0.0-Strategy.html` | Strategy overview |
| `mockups/`, `Metis-2.0.0-screens/` | UI mockups and screen designs |
| `sandbox/` | `DEMO-KB/` (a small KB built from the two repos below) and helper scripts |

## Run the tests

Python 3.10 or later. The only required package is PyYAML; everything else is optional (see `pyproject.toml`).

```
cd "metis-1.2.5-team (1)"
pip install -r requirements.txt
cd tools
python -W ignore -m unittest discover -s tests -p "test_*.py"
```

The last full run: 1180 tests, OK, 9 skipped. `tests/test_smoke_sandbox.py` is skipped unless the two sample repos are present. To enable it, from this folder:

```
mkdir sandbox/repos
git clone https://github.com/dbt-labs/jaffle-shop sandbox/repos/jaffle-shop
git clone https://github.com/spring-projects/spring-petclinic sandbox/repos/spring-petclinic
```

(The smoke test checks the `DEMO-KB` source tags against those repos' files, so use the same commits it was built from if a tag no longer matches.)

## Start the UI

```
cd "metis-1.2.5-team (1)/tools/ui"
python server.py --kb <path to a KB folder>
```

Details, the screen-by-screen guide, the safety model and the concurrency model are in `documentation/Metis-2.0.0-manual.md`.

## Honest status

Built and tested against local fakes and the sample repos. Not yet tried against real Bitbucket, Slack, SMTP, an OIDC provider, an OTLP collector, sentence-transformers or a live MCP client. Authentication is a shared password or OIDC: claim labels are a filter, not access control. Confidence bands are rule-based and uncalibrated until enough answers are rated. See `documentation/TECH-DEBT.md` and the Release Record.
