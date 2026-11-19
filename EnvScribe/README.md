# EnvScribe

A read-only agent that crawls an engineering environment, journals what it finds, and packages the result as a sanitized zip. It can also answer questions about the journal, and in Advise mode it proposes code changes for a requirement.

> Status: built and unit-tested locally (40 tests) and run against the bundled `sample/` project only. **Nothing has been run against real systems.** See [Unverified assumptions](#unverified-assumptions).

## What it does

- **Source code, any language** – symbols, imports, endpoints, DB/connection usage (`scribe/scanners/code.py`).
- **Build and dependencies** – pom.xml, Gradle, npm, pip, etc. (`scanners/build.py`).
- **API contracts** – OpenAPI, protobuf, GraphQL, WSDL and similar (`scanners/contracts.py`).
- **Configs and per-environment parameters** – sit/dev/uat/prod (`scanners/config.py`).
- **CI/CD and IaC** – pipelines, Kubernetes, Terraform, cloud (`scanners/cicd_iac.py`).
- **Secret and leak detection** – `scanners/leaks.py`.
- **Documents** – PDF (OCR fallback if tesseract exists), DOCX, XLSX, PPTX, drawio/vsdx/BPMN/SVG/PlantUML/Mermaid, transcripts with speakers and names removed (`scribe/docs/`).
- **Service connectors** (read-only): Bitbucket, Jira, Confluence, Artifactory, Bamboo, SonarQube, Snowflake, RDS and more (`scribe/connectors/`). DB catalogs are metadata only (`dbcatalog.py`).
- **Relevance gate** – only reads documents related to applications found in the code. Uploads can be tagged or read anyway.
- **Viewer** (`/viewer`) – read-only browser for the output zip: file tree, rendered Markdown with working links, and a searchable facts table. Open the current run's zip or any journal zip from disk.
- **Exit button** – in the UI header; cancels any active run (a partial zip is still produced) and stops the server.
- **Q&A and Advise** – BM25 over the journal (`knowledge.py`). Advise output is labeled PROPOSAL and is suggest-only.

Images, video and audio are not read.

## Grounding policy

Fact classes: OBSERVED, DERIVED (records its rule), DOCUMENTED, DISCUSSED, LLM_DESCRIBED (must quote evidence), UNKNOWN. Every fact carries evidence. Conflicts are reported, never resolved. When nothing matches, answers say "not found". Everything is read-only.

## Output safety

- IPs and hostnames are **always masked**; there is no setting to allow them.
- Two blocking sweeps run before zipping: **Privacy & security** and **Credential & secret**. If one finds something, EnvScribe auto-redacts, rescans, then blocks if anything remains. The sealed zip is rescanned and verified.
- `progress.jsonl` lets an interrupted run resume. Cancelling produces a partial zip.
- Download the zip right away; the VM is ephemeral.

## Settings

- Token budget: `0` or blank = unlimited.
- Max workers: 1–100 (local thread pool; the worker/package design is backend-agnostic).

## Setup

```powershell
git submodule add https://github.ibm.com/AI-CoE/aicoe-agent-utils.git   # needs credentials
git submodule update --init --recursive
python -m venv venv; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # fill in credentials; auth flags stay false by default
```

Optional: `pip install aicoe-agent-utils[agentops]`, `pytesseract` for OCR.

## Run

```powershell
python main.py --ui-only      # web UI only, no LLM/A2A needed; http://127.0.0.1:8090
python main.py                # A2A server + UI (needs aicoe-agent-utils and LLM config)
python test_client.py         # A2A test client
python scripts/run_sample.py  # end-to-end run on sample/
python -m pytest tests -q
```

Copy `targets.example.yaml` to `targets.yaml` to describe sources and environments.

## Layout

```
main.py, config.py, envscribe_agent.py, a2a_factory.py, test_client.py
scribe/            engine (scanners, docs, connectors, sweeps, orchestrator, knowledge, ui)
sample/            demo project with seeded secret/host/IP/speaker names
tests/  scripts/  mockups/ (UI options; Option C2 was chosen)
PROMPT.md          consolidated build prompt
```

## Unverified assumptions

1. **aicoe-agent-utils API names.** The repo could not be cloned (no credentials). `envscribe_agent.py`, `a2a_factory.py`, `main.py` and `test_client.py` use guessed imports (`aicoe_agent_utils.agent.BaseLangGraphAgent`, `aicoe_agent_utils.a2a.A2AAgentFactory`, `aicoe_agent_utils.utils.start_a2a_server`) with stand-in classes. Compare with `aicoe-agent-utils/examples/agents_with_mcp/weather_agent/` once cloned.
2. Whether the Devin VM can serve the UI, and how Devin sub-sessions return chunks (currently left to Devin).
3. Snowflake headless auth: use OAuth token or key-pair, not `externalbrowser`.
4. The DB catalog collector and YAML connector directory are unit-tested but not yet invoked from the orchestrator (`Run._connectors`).
5. OCR, `snowflake-connector` and `pymupdf` are optional and not installed here; OCR degrades to "no text layer, not read".
