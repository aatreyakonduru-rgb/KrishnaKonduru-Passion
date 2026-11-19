---
name: adr
description: >
  Write down an architecture decision as an ADR (Architecture Decision Record): a short dated
  note of what we decided, why, which options we turned down, what it costs us, and who signed
  off. Records go in docs/knowledge-base/DECISIONS/ as ADR-NNNN-<slug>.md, with a
  generated index. Devin drafts and files; a named person on the roster accepts.
  Invoke with: /adr "<decision>" [REQ-ID STORY-ID] [ACME-nnnn]  ·  /adr list  ·  /adr supersede ADR-n
argument-hint: "\"<decision in one line>\" [REQ-ID STORY-ID] [ACME-nnnn] | list | supersede ADR-n"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /adr
  - record this decision
  - write an ADR
  - why did we decide
allowed-tools:
  - bash
  - read
  - edit
  - git_create_pr
---

# /adr — record an architecture decision

An ADR answers, months later, "why does it work this way?" without having to find whoever
built it. Keep it to one decision and one page. The tool is
`sdlc/framework/tools/adr.py`; the template is `.devin/templates/adr.md`.

## When to write one
A choice that is hard to undo, or that people will keep asking about: a new table or view,
how two services talk, paging or caching strategy, where a rule is enforced (UI, API or ETL),
picking a library, a security trade-off. Not for a bug fix or a naming choice.

## Steps

1. **Get the decision in one line.** If the user did not give one, ask. Also ask who decides
   (names on `.devin/rules/people.yaml`), and the REQ/STORY or Jira key if there is one.
   Before anything is filed, `/adr list` and check the decision isn't already recorded. If it
   is, offer to supersede it instead.

2. **Read before you write.** Open the code, KB pages, PRs or Confluence pages the decision is
   about. Keep a list of what you actually read; it goes into *Sources read*. Do not describe
   code, tables or endpoints you have not opened.

3. **Create the file.**
   ```bash
   python3 sdlc/framework/tools/adr.py new "<title>" --req "<REQ-ID STORY-ID>" --jira <KEY> --deciders "<Name>; <Name>"
   ```

4. **Fill it in**, in plain English:
   - *Context*: what forced the decision, in two or three sentences.
   - *Decision*: what we will do, written so someone can check later whether the code still does it.
   - *Options considered*: at least two real options, with what's for and against each. Include
     "leave it as it is" when that was a real option.
   - *Consequences*: what gets easier, what gets harder, what we now have to keep doing.
   - Tag every fact `[E: source]`, `[A]` or `[?]`. Every `[A]` goes on *Assumptions* (with
     what changes if wrong) and every `[?]` on *Don't know* (with who can answer).

5. **Check it.** Fix everything it reports:
   ```bash
   python3 sdlc/framework/tools/adr.py check ADR-NNNN
   ```

6. **Show the draft.** Status stays `Proposed`. Ask the deciders to reply `approved` or
   `rejected`. Only after a named decider replies `approved`:
   ```bash
   python3 sdlc/framework/tools/adr.py accept ADR-NNNN --by "<Last, First>"
   ```
   If they reject it, set Status to `Rejected` and keep the file. A rejected option is worth
   remembering too.

7. **File it.** Regenerate the index and the KB manifest, then raise a PR (follow the work-ID
   rule for the branch and commit):
   ```bash
   python3 sdlc/framework/tools/adr.py index
   python3 sdlc/framework/tools/kb_manifest.py generate
   ```

## Changing your mind later
Never rewrite an accepted decision. Write a new ADR, then:
```bash
python3 sdlc/framework/tools/adr.py supersede ADR-0003 --by ADR-0007
```

## Don't
- Mark an ADR `Accepted` without a named person's reply.
- Fill *Options considered* with made-up alternatives nobody discussed.
- Edit the decision of an accepted ADR.
