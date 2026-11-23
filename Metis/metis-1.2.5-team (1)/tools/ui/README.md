# Mētis UI

A lightweight, local-first web UI for Mētis 2.0 knowledge bases. Standard library Python + PyYAML only.

---

## Running the Server

Start the server pointing to a knowledge base directory:

```bash
python tools/ui/server.py --kb /path/to/KB --port 8791
```

Options:
- `--kb <DIR>`: Path to the Mētis knowledge base folder (defaults to `.` or `METIS_KB` environment variable).
- `--port <PORT>`: Port to listen on (default: `8791`, or `METIS_UI_PORT`).
- `--host <HOST>`: Interface to bind to (default: `127.0.0.1`, or `METIS_UI_HOST`).
- `--password <PWD>`: Password required for authentication (or `METIS_UI_PASSWORD`).

---

## Devin Cloud & Remote Access

1. **Loopback Access (Local / Dev):**
   When running on `127.0.0.1` or `localhost`, no password is required.

2. **Port Forwarding / Remote Hosting:**
   When binding to non-loopback interfaces (e.g. `--host 0.0.0.0` inside a Devin cloud sandbox with forwarded ports), `METIS_UI_PASSWORD` is required for security.
   ```bash
   export METIS_UI_PASSWORD="your-secure-password"
   python tools/ui/server.py --kb /workspace/KB --host 0.0.0.0 --port 8791
   ```
   Users will be prompted via HTTP Basic Authentication (username can be anything; password must match `METIS_UI_PASSWORD`).

3. **User Identity ("You are"):**
   Set your full name in the top right ("You are"). This identity is preserved via a `metis_user` cookie and recorded on all reviews, ratings, question answers, and lead certifications.

---

## Architecture & Worker Integration

The UI acts as an orchestrator and viewer:
- **Local Extractive Mode**: Instantly searches and extracts verified answers from KB files without model calls.
- **Devin Worker Task Queue**: Complex model work (generating KB modules, reasoning across layers, handling unstructured ask questions) is queued as tasks under `<KB>/.metis/tasks/T-xxxx.yaml`.
- **Devin Sessions**: A worker session running in Devin picks up tasks using the `metis-tasks` skill (`tools/ui/tasks.py claim <KB> --by "<name>"`), writes staged pages to `<KB>/_REGEN/`, and completes tasks.
- **Safety & Gate**: The UI verifies all evidence tags with `verify_kb.py` before bringing pages into the KB. Incremental builds after KB locking are held as review batches under **Approve** until certified by a named lead.

---

## Screens

All 17 screens use a consistent three-column desktop layout (`left_pane` list/filter, `main` workspace, and `right_pane` inspector) matching the mockup designs:

1. **Home (`/`)**: High-level readiness checklist (profile, stack, modules, database environments, build, lock), KPI cards, and work queue in the left pane.
2. **Setup (`/setup`)**: Edit `kb-profile.yaml`, run automated stack detection (`detect_stack.py`), approve stack findings, configure `db-environments.yaml`, check repository connections, and lint prompts with multi-step left pane navigation.
3. **Build (`/build`)**: Trigger KB builds, view real-time stage status and queued Devin tasks, and trigger scripted verification and output generation.
4. **KB files (`/files`)**: Browse generated markdown documents with syntax-highlighted source evidence citations and upstream/downstream graph lineage (`parsed` vs `ai-proposed`) in the right pane.
5. **Ask (`/ask`)**: Ask questions with local extractive search or Devin mode; submit like/dislike ratings with mandatory corrective feedback or direction; right pane confidence breakdown.
6. **Questions (`/questions`)**: Inspect open questions from `VALIDATE_KB.yaml`, filter by role and priority via left pane, raise new items, and supply verified answers.
7. **Approve (`/approve`)**: Lead certification hub for locking the KB, reviewing proposed batches, and approving user feedback/hints.
8. **Coverage (`/coverage`)**: Summary metrics on covered modules, entities, unparsed SQL, and gap analysis with type breakdown in the left pane.

### More screens (second nav row)

Each lives in its own `screens_*.py` module with a matching `tools/tests/test_ui_*.py`.

9. **Golden questions (`/golden`)**: Competency and golden questions; static check and lexical scoring (`golden.py`).
10. **Context pack (`/pack`)**: Build a pack for a ticket, objects or files. Kept in memory only (last 20).
11. **Glossary (`/glossary`)**: Business terms and synonyms. Ask widens its search with them.
12. **Review queue (`/review`)**: Pending files by team and risk, with trust signals. Sampling for batches over 10 files.
13. **Usage (`/usage`)**: Which KB files are used and rated; confidence bands checked against ratings.
14. **Audit log (`/audit`)**: Certifications and other recorded actions.
15. **Teams and rights (`/teams`)**: Teams from `gate.teams`; only a lead adds a certifier.
16. **Settings (`/settings`)**: Profile settings that are safe to change from the UI.
17. **Compare and promote (`/compare`)**: Compare a staged folder with the KB and promote a chosen page. A locked KB turns a promote into a proposed batch.

### Plugin screen loader

`server.py` imports every `tools/ui/screens_*.py` at start. A module defines `SCREENS` (path to handler), `ACTIONS` (path to POST handler) and `NAV` (label list). A module that fails to import is skipped and a message is printed to stderr; the other screens still run. Add a screen by adding one file.

### Ask: confidence and guidance

Confidence is computed from the KB lines found, never claimed by a model. 100 means one line states the answer in the question's own words. Caps: joined lines 92, `Inferred:` lines 80, a part not in the KB or an open question 84. 0 means nothing found. Bands: High from 85, Medium from 60, Low from 1. When there is no checked line or the band is not High, a guidance card shows the searched words, typo options, nearest pages and a clarify box. A Devin session can ask the person at most 2 questions per round, 2 rounds; a reply points where to look and is never a source.
