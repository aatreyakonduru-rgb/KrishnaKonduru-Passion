# Mētis approvals: build to the end, then a named lead certifies

A Mētis build runs every step to the end without waiting. What changes is how the result reaches the KB.

## Before the first KB is locked
- The first build runs straight through. Every step, its files and its review criteria go in
  `<KB>/_REGEN/<run>/REVIEW.md` under "For review in the KB PR". The whole KB goes to the team in one pull request.
- Wherever a skill or agent says "Stop here", "gate", "must approve" or "wait for approval", do not wait.
  Write it in REVIEW.md and carry on.
- When the first KB is accepted, lock it: `python3 $METIS/tools/kb_gate.py lock <KB> --by "<lead's name>"`.

## After the lock: nothing enters the KB without a named lead
- Every later change is staged, not written: a rebuild, ingested documents, a saved answer, a promoted page.
  `python3 $METIS/tools/kb_gate.py propose <KB> --batch <name> --from <folder>` copies it to `<KB>/_PENDING/<batch>/`,
  and `kb_gate.py digest <KB> <batch>` writes the plain-language summary for the lead.
- A lead certifies with `kb_gate.py certify <KB> <batch> --by "<name>"`, or rejects with `kb_gate.py reject ... --reason`.
  Leads are the people in `owners` (`kb_owner`, `app_owner`, `db_owner`, `etl_owner`, any role with "lead" in its name)
  and `gate.certifiers`. Someone who is not a lead cannot certify. The giver of a document cannot certify it
  when another lead exists.
- If the profile lists `gate.teams`, each file belongs to the first team whose `owns` path matches it. That team's approvers
  and the leads may certify it; nobody else. `python3 $METIS/tools/review_queue.py queue <KB>` shows what is waiting by
  team, riskiest first. `review_queue.py plan <KB>` writes one PR body per team and names its branch
  `metis/<YYYY-MM-DD>-review-<team>`: open one PR per team and ask that team's approvers. `review_queue.py certify <KB>
  --team <team> --by "<name>"` certifies that team's files in every batch. Files no team owns go to the leads.
- Sources are checked again after certification; if they fail, the change is undone.
- Findings of secrets, keys, tokens, SSNs or card numbers block certification. Emails, phone numbers, dates of birth
  and member or claim ids need the lead to accept them by name.
- Documents with a read restriction in Confluence or SharePoint need a lead's approval first
  (`doc_kb.py approve-restricted`).
- Changes still reach the team repo through a branch `metis/<YYYY-MM-DD>-<short name>` and one PR. Mētis never merges.
  CI runs `kb_gate.py check <KB>` so a change that skipped the gate fails.
- Chat cannot prove who a person is. The name is recorded as given; CODEOWNERS on `<KB>/.metis/certified.yaml`
  and PR approval are the checks that hold.

## Always
- Open questions never block a PR. Source problems do: `verify_kb.py` must report zero problems.
  A line that cannot be sourced becomes a question.
- People are named in the `owners` block of `<KB>/.metis/kb-profile.yaml`: `kb_owner`, optional `app_owner`, `db_owner`,
  `etl_owner`, and `roles` (dev lead, ETL lead, data lead, architect, manager, product owner, business analyst,
  security lead, operations, and any role the team adds). When a step names a reviewer, list the matching person from
  `owners.roles` in REVIEW.md. Never approve on anyone's behalf.
- Answers come back through VALIDATE_KB: the person fills `answer` and `answered_by` (in the PR or in chat). The next
  build uses each answer as a source (`[E: answer:Q-0001]`).
