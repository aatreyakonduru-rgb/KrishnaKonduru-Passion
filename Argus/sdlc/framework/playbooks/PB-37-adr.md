# Playbook: ADR — Record an Architecture Decision

**Playbook ID:** PB-37  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/adr` skill (`.devin/skills/adr/SKILL.md`)  
**When to use:** When the team makes a design choice that is hard to undo or that people will keep asking about.

---

## Title
```
Acme Claims: ADR — write down what we decided and why
```

## Description
```
Drafts an Architecture Decision Record in docs/knowledge-base/DECISIONS/:
context, the decision, the options turned down, consequences, sources read, and who
signed off. Devin drafts and files; a named person on the roster accepts it.
```

## Playbook Body

---

Run `/adr "{decision}" [REQ-ID STORY-ID] [ACME-nnnn]` and follow `.devin/skills/adr/SKILL.md` step by step.

1. Get the decision in one line, the deciders and the work ID. Check `adr.py list` for an existing record.
2. Read the code, KB pages and PRs the decision is about, and keep the list.
3. `python3 sdlc/framework/tools/adr.py new "{title}" --deciders "{names}"`, then fill in every section with tagged facts.
4. `adr.py check` must pass.
5. Show the draft. Only after a named decider replies `approved`, run `adr.py accept ADR-NNNN --by "{name}"`.
6. `adr.py index`, `kb_manifest.py generate`, raise the PR.

## Forbidden actions
- Marking an ADR Accepted without a named person's reply.
- Rewriting the decision of an accepted ADR (write a new one and supersede).
- Describing code, tables or endpoints that were not opened.
