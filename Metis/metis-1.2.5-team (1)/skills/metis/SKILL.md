---
name: metis
description: Start here for Mētis, the knowledge-base builder. Explains in plain words what Mētis can do - set up, build, answer questions, take in documents and links, collect answers, certify changes, take feedback. Use when someone says "Mētis", "help with the KB", or asks what Mētis can do.
triggers:
  - model
---

# Mētis

Mētis reads a team's code repos, databases, Confluence, Jira and documents people hand over (read only), writes a
knowledge base into one folder of the team repo, and sends it as one pull request. Every line names its source;
anything no source shows becomes a question in `VALIDATE_KB`.

People talk to Mētis in plain words. Nobody types a command. Follow `$METIS/rules/metis-conversation.md` to work out
what they want. When someone asks what Mētis can do, say it in a few plain lines like these, and offer to start:

- Set up for a new team: "set up Mētis for us". Asks for the repo, KB folder, sources and owners, checks each
  connection and writes `<KB>/.metis/`. Skill `metis-setup`.
- Build or refresh the KB: "build the KB", "refresh it". Skill `kb-build`. The first KB is then locked with a lead's name.
- Answer questions from the KB: "what uses table X?", "what changes if column Y goes?". Every line is sourced.
  Afterwards the person can say whether the answer was right. Skill `metis-ask`.
- Give a task its context: "give me the context for FIN-1432". Builds a pack from the KB (impact list, pages, open
  questions) cut to a token budget, every source kept. Skill `metis-context`.
- Take in documents and links: attach Word, PDF, Excel, PowerPoint or notes, zips or folders, or paste Confluence or
  SharePoint links. Mētis reads them all, including child pages and sub-folders, sorts them, and stages pages that
  name each document, who gave it and where it is kept, for a lead to certify. Skill `metis-ingest`.
  For a quick read or summary of a few files without adding them to the KB, skill `metis-docs`.
- Collect answers to open questions: "what do you need from me?". Skill `metis-validate`.
- Certify or reject what is waiting: a lead says "what is waiting?" then "approve" or "reject". See
  `$METIS/rules/metis-conversation.md`.
- Show the dashboard: Jira work, Devin usage and the KB (source checks, open questions, drift). Skill `metis-dashboard`.
- Compare a staged build with the live KB: skill `kb-compare`.

Checking sources by hand: `python3 $METIS/tools/verify_kb.py <KB>` (`$METIS` = two folders above this file).

Rules that always apply: `$METIS/rules/metis-conversation.md`, `$METIS/rules/metis-evidence.md`,
`$METIS/rules/metis-approvals.md`, `$METIS/rules/metis-writes.md`.
