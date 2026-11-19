---
name: catalogue
description: The one internal inventory command. Lists the skills (slash commands), the Devin Cloud playbooks (!pb_ macros) or the agent role profiles installed in this repository, each with a one-line summary, read from the generated CATALOGUE.md. Use when someone types /catalogue, /skills, /slashcommands, /playbooks or /agents, asks which commands, macros or agents exist, or wants a flat A–Z list of everything they can type. For the everyday menu use /help instead.
argument-hint: "[skills | playbooks | agents | all] [optional filter, e.g. db, bsa, security, PB-12]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /catalogue
  - /skills
  - /slashcommands
  - /commands
  - /playbooks
  - /agents
  - list skills
  - list playbooks
  - list macros
  - list agents
  - what commands do we have
allowed-tools:
  - read
  - glob
  - grep
---

# /catalogue — What is installed

Read-only. Print the list; never run, start or adopt anything you list.

## STEP 1 — Pick the section

`/catalogue skills` (also `/skills`, `/slashcommands`, `/commands`) → the **Skills** section.
`/catalogue playbooks` (also `/playbooks`) → **Playbooks**.
`/catalogue agents` (also `/agents`) → **Agents**.
`/catalogue` or `/catalogue all` → all three, skills first.

Everything comes from `sdlc/framework/CATALOGUE.md`, generated from the
frontmatter by `sdlc/framework/tools/gen_catalogue.py`.

## STEP 2 — Confirm it is current

Glob `.devin/skills/*/SKILL.md`, `sdlc/framework/playbooks/PB-*.md` and
`.devin/agents/*.agent.yaml`; compare the counts with the catalogue headings. If they differ,
say so, tell the user to run `python3 sdlc/framework/tools/gen_catalogue.py` and then
`python3 sdlc/framework/tools/gen_reference_pages.py` (Argus's catalogue page), and
list from the glob in the meantime (skill `description`, playbook title, agent `role`).

## STEP 3 — Print

Skills: grouped as the user manual groups them (business & product · intake · SDLC pipeline ·
investigation & change safety · documentation pipeline · database), one row `/<name>` + summary;
mark the nine `visibility: public` ones so the reader knows which are the front door. With
`/slashcommands` print the same rows flat and alphabetical instead.

Playbooks: macro (`!pb_nn_name`), title, summary, and the slash command it runs.

Agents: name, role, purpose, and the skills it may use.

With a filter, print only matching rows and say how many of the total that is.

Close with: `/help` for the everyday menu, `/help <command>` for one command in detail.

## HARD RULES

- Never invent an entry — only what exists on disk.
- Listing is not invoking.
- One line per entry; no skill bodies.
