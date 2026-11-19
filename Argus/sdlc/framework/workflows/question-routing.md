# Question routing through Jira sub-tasks

## Flow

Ask a question with `/ask` → a Jira sub-task is created with label `Question`, assignee set
to the target, and parent set to the story → Jira sends its assignment notification → the
target answers through `/dashboard` → the answer is posted, the sub-task is reassigned to the
asker, and the question and answer are mirrored to the parent story → the asker closes the
sub-task.

## State machine

| State | Jira assignment | Resolution |
|---|---|---|
| open | target | unresolved |
| answered | asker | unresolved |
| follow-up | target | unresolved |
| closed | asker | resolved |

## Agreed assumptions

- **A1.** Question sub-tasks are excluded from sprint and estimation reporting. They carry no
  story points, and reporting queries filter them out with `labels != Question`, because Acme Claims
  sub-tasks are otherwise delivery tasks and conversation would distort velocity and burndown.
- **A2.** An unanswered question does not hard-block the story's gates. It surfaces as a flag on
  the dashboard and to the approver at gate time; the lead keeps the judgement call.
- **A3.** The asker closes the sub-task, not the answerer. Answering only returns it; only the
  asker knows whether the answer was sufficient.
- **A4.** Q&A is mirrored as a comment on the parent story so the story reads as a complete record
  without opening sub-tasks.
- **A5.** The label is exactly `Question`, reserved for this purpose. Targets come from
  `user/assignable/search`, so only people who can hold Acme Claims work can be asked.
- **A6.** The Jira assignment notification is the only notification in v1; there is no Teams or
  email fan-out.

## Verified Jira facts

- Acme Claims sub-task issue types are `Sub-task` id `10112` and `Technical task` id `10109`.
- People picker must use `/rest/api/2/user/assignable/search?project=ACME&username=<fragment>`;
  plain `/rest/api/2/user/search` returns empty for this service account.
- Jira DC 11.3.10 uses a self-signed certificate in the chain; tooling uses
  `ssl._create_unverified_context()`.
- The service account token is validated once against `/rest/api/2/myself`. A 401 or 403 stops
  immediately without retrying because three failed attempts can lock the account.

## Open items

- Nudge policy for unanswered questions.
- Whether intake clarification questions should use this flow.
- How to route questions raised before a Jira story exists.
