# Start here: install Argus

For UEP Devin Cloud, other Devin Cloud, or Devin Local. The first step of the window asks which
(it picks UEP when the session already has the Jira and Confluence secrets). In Devin Cloud the
tech lead uploads this zip into a new session and types **install this**
(or **install this with my values**, with a saved `install-draft.yaml` attached). Devin then does
the steps below. Nothing is written to the team's repo, Confluence or Devin Cloud until the tech
lead presses **Install** on the Review step of the window.

## For Devin

1. Unzip the attachment into `~/sdlc-framework/` and `cd` into the folder that holds `install.py`
   and `dot-devin/`.
2. Make sure PyYAML is there: `python3 -c "import yaml" || python3 -m pip install --user pyyaml`.
3. Start the window as a foreground process in its own shell and keep it running:

       python3 install_ui.py --target ~/repos/<app repo>          # if the app repo is already cloned
       python3 install_ui.py --draft <path to install-draft.yaml>  # if a saved draft was attached
       python3 install_ui.py --draft-repo ~/repos/<app repo>       # "my values are on devin/install-draft in <repo>"

   It listens on `127.0.0.1:8790`. Show it to the tech lead with a browser preview (name
   "SDLC install", port 8790) and tell them that nothing is written before Install.
4. Watch the window's output, and `~/sdlc-install/events.log`, for lines starting
   `SDLC-INSTALL-EVENT` and act on each:
   - `ATTACH {"path": ...}`: post that file (`install-draft.yaml`) in the chat as an attachment
     and say: "Download this to your PC. Next time attach the zip and this file to a new session
     and type *install this with my values*. Without it you start afresh."
   - `OPEN_PR {"repo", "branch", "base", "title"}`: open a pull request from `branch` into `base`
     with your git tool, and post its link. Never merge it; a person on the team does.
   - `BLUEPRINT {"path", "repo"}`: show the file and, once the tech lead agrees, apply it as the
     repo blueprint for `repo` (Devin asks for approval).
   - `KNOWLEDGE_NOTE {"path"}`: show it and, once the tech lead agrees, save it as a knowledge note.
   - `MCP_CHECK {"servers": {"jira": ..., "confluence": ..., "snowflake": ...}}`: make one read-only
     call to each named MCP server (for example list its tools, or read one issue or page) and tell
     the tech lead in the chat which ones answered. A server that doesn't answer is not set up in
     this session yet; the tech lead adds it in Devin's MCP settings before using Argus.
5. Never print, paste or save a secret. The window only checks that the secrets it names exist.
6. If the session goes to sleep the window keeps its values on this machine. In a new session
   the tech lead needs the saved draft (step 3) or starts afresh.

## UEP, other Devin Cloud and Devin Local

- **UEP Devin Cloud:** the organisation's service accounts, saved as Devin secrets, reach Jira,
  Confluence, Snowflake and the repos. Nothing else is needed.
- **Other Devin Cloud and Devin Local:** the team needs, before it can use Argus,
  - MCP servers for Jira and Confluence: Devin's chat skills use them;
  - its own Jira and Confluence API tokens (personal access tokens): Argus, the dashboard and
    the other tools call Jira and Confluence with them. In Devin Cloud they are Devin secrets, on
    Devin Local environment variables on the PC;
  - git access to the app repo: the repo connected in Devin Cloud, or the person's own git login;
  - optionally a Snowflake MCP server for the database and ETL parts of the knowledge base.
    Without it those parts can't be built; the rest of Argus works. (The sandbox uses its own
    sample database instead.)

  Getting these is up to the team. The window asks for the MCP server names, Devin checks each one
  (`MCP_CHECK` above), and Install points the skills at them and saves them in the team settings
  (`.devin/rules/sdlc-profile.json`, `mcp`).

## On Devin Local (Windows, Mac or Linux)

1. Unzip the copy on the PC and open Devin Local in the unzipped folder.
2. Set the Jira and Confluence service-account tokens as environment variables on the PC, with the
   names you will type in the window (for example `ACME_JIRA_TOKEN`). The window checks that they
   are there and never shows them.
3. Devin starts the window the same way (`python install_ui.py` on Windows, or `py -3 install_ui.py`;
   `python3 install_ui.py` on Mac and Linux) and you open http://127.0.0.1:8790 in your own browser.
   Pick **Devin Local** on the first step.
4. Windows needs Git for Windows: its Git Bash runs the hook checks. The Check step names it if it
   is missing.
5. There is no Devin Cloud machine to set up, so the install skips the blueprint and knowledge note.
   `install-draft.yaml` and the log stay in `~/sdlc-install` on the PC.

## Sandbox: try it on a made-up company

The Check step offers a sandbox on Devin Local, and on Devin Cloud when the session has no Jira or
Confluence secrets. **Make the sandbox** builds, in the folder you name (default
`~/Documents/sdlc-sandbox`):
- `jira.yaml`: the sample Jira for Acme Claims: 22 people, 3 sprints, 3 epics, 15 stories, 30 sub-tasks and 6 defects;
- `confluence/`: the sample Confluence space (open `confluence/index.html` in a browser);
- `sample.db`: a SQLite database with sample members, providers, contracts, claims, claim lines and payments;
- `sample-kb/`: the hand-kept part of the sample app's knowledge base (routing map, table and entity registries, semantic layer, lineage, curated impact chains, domain context), copied in by the install, which then builds the endpoint, component and ETL registries, the cross-layer matrix, the ontology and the link graph from the sample code;
- `claims-etl/`: the sample app's ETL repo, beside the app repo;
- `acme-claims/`: the sample app repo, with `origin.git` as its remote. The app runs: a Django API
  and a Next.js front end over a copy of `sample.db`. In `acme-claims/`, `python3 run.py setup` once
  (Python packages into `.venv`, npm packages), then `python3 run.py` starts the API on
  `http://127.0.0.1:8000/acme/api/docs` and the web app on `http://127.0.0.1:3000`, so Devin can
  change the code and test it in the browser. It needs Python 3.9+, Node.js 18+, and pip and npm
  able to reach a package registry; the Check step says whether they can.

It starts the sandbox server (`http://127.0.0.1:8799`) and fills every step. The install then runs
as usual, against the sandbox only. Later, start the server again with
`python3 sdlc/framework/tools/sandbox/sandbox_server.py --folder <folder>` and turn the sandbox on in a shell
with `python3 sdlc/framework/tools/sandbox/switch.py --folder <folder>`: it prints `SDLC_SANDBOX`,
`SDLC_SANDBOX_URL` and the token variables to set. While `SDLC_SANDBOX_URL` is set, every Jira and
Confluence call goes to the sandbox, and the database skills query `sample.db` with
`sandbox/sandbox_db.py` instead of Snowflake.

## For the tech lead

- Before you start, in UEP Devin Cloud ask your Devin admin for two secrets holding service-account
  tokens: one for Jira, one for Confluence. Outside UEP, bring your own Jira and Confluence API
  tokens and MCP servers (see "UEP, other Devin Cloud and Devin Local"). Optional: `DEVIN_API_KEY` of a service user (registers the playbooks),
  and a Snowflake connection (database and ETL parts of the knowledge base).
- Have a Confluence parent page ready that the service account can write under, and your app repo
  connected to Devin Cloud.
- Keep your roster to hand (names, emails, roles), or fill in `templates/roster-template.csv`.
- Without Devin Cloud: `python3 install.py --target <your repo> [--values mine.yaml]` asks the same
  values in the terminal (see `templates/values-template.yaml`).
