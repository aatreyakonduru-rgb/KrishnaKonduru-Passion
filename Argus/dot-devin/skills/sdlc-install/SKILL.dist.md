---
name: sdlc-install
description: Set up, change or check this repository's copy of the shared agentic SDLC. Runs sdlc/install.py, which asks for (or reads) the team's values — product name, Jira host, project and token name, Confluence host, space and token name, git host, app / deploy / test repos, working branch, Devin host and email domain — writes them into every skill, rule, playbook and setting, records them in .devin/rules/sdlc-install.yaml, and checks prerequisites, Jira / Confluence / repository connectivity, framework validation, prompt lint, the tests and that no sample values are left. Say "/sdlc-install" to check, "/sdlc-install reconfigure" to change values.
argument-hint: "[check|reconfigure] [--offline]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /sdlc-install
  - set up the sdlc
  - install the sdlc
  - change our sdlc settings
allowed-tools:
  - bash
---

# /sdlc-install — set up, change or check the SDLC in this repo

`sdlc/install.py` does the work; this skill only runs it and explains the result. It never prints a
token: it reads the Jira and Confluence tokens from the environment variables named in
`.devin/rules/sdlc-install.yaml` (`jira_token_env`, `confluence_token_env`), which in Devin Cloud are
the secrets of the same name.

## /sdlc-install (or `check`)

```bash
python3 sdlc/install.py --check
```

Add `--offline` when the machine cannot reach Jira, Confluence or the git server. Show the table it
prints. For each FAILED row say what to do:

- **values**: run `/sdlc-install reconfigure`.
- **Jira / Confluence**: the secret is missing (ask the user to add it in Devin → Settings →
  Secrets, never paste it in chat) or the host or space is wrong.
- **Repository**: no `origin` remote, or no access to it.
- **no Acme values left**: files still hold sample values; run `reconfigure` again or edit them.
- **framework validation / prompt lint / tests**: show the last lines it printed and fix the cause.

## /sdlc-install reconfigure

Ask the user for the values they want to change (the questions are the comments in
`.devin/rules/sdlc-install.yaml`), write them to a temporary YAML file with only those keys, then:

```bash
python3 sdlc/install.py --reconfigure --values /tmp/sdlc-values.yaml
```

It swaps the old values for the new ones in every framework file and runs the checks. Commit the
result through a pull request like any other framework change.

## First install

The first install is done from the shared copy, not from here (this skill is not installed yet).
In Devin Cloud, upload the zip and type "install this": Devin follows `START-HERE.md` and opens the
install window (`install_ui.py`). From a terminal:

```bash
python3 <shared copy>/install.py --target <your repo>
```

See `sdlc/README.md`. The SDLC and knowledge-base folders (`sdlc_dir`, `kb_dir`) are chosen at
install time and can't be changed with `reconfigure`.
