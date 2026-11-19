# Playbook: BSA Dashboard

**Playbook ID:** PB-18  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/dashboard --lens bsa` skill (`.devin/skills/dashboard/SKILL.md`)  
**When to use:** Every morning standup, before stakeholder meetings, or any time you need one view of everything waiting on you as a BSA.

The standalone `/bsa-dashboard` skill has been retired; this playbook now opens the BSA lens of the
role-aware `/dashboard`, which shows the same things (gates waiting on you, unrouted and open
questions, stories not ready to estimate, stale knowledge-base documents) as colour-coded tabs, with
the answer / hand-over / observation forms the other lenses have.

---

## Title
```
Acme Claims: BSA Dashboard — All Pending Items at a Glance
```

## Description
```
Opens the BSA lens of the role-aware /dashboard: gate approvals waiting on
you, questions with nobody to answer them, documents waiting on a business
answer, stories not ready to estimate, and knowledge-base documents that
have fallen behind the code. One tabbed page, urgent tabs first.
```

## Playbook Body

---

Run `/identify-requester` to confirm who is asking, then run

```
/dashboard --lens bsa
```

and attach the generated HTML. Summarise in plain language what the red tabs are asking of the
person, and mention the amber tabs (things they are waiting on others for). Say nothing about tabs
that are empty.

Approval decisions stay in chat: if a gate is waiting on the person, present it per
`.devin/rules/gate-presentation.md` rather than linking to the dashboard.
