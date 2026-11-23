# Mētis writes

- Mētis writes only inside the KB folder named in `<KB>/.metis/kb-profile.yaml` (`paths.kb_root`).
  Every source repo, database, Confluence space and Jira project is read only.
- Builds write to `<KB>/_REGEN/<run>/` first. `kb-compare` moves files into the live KB only after the
  KB owner approves, and keeps the old copy under `<KB>/Archive/<date>/`.
- Once the KB is locked (`<KB>/.metis/certified.yaml`), nothing is written into the live KB directly. Changes are
  staged under `<KB>/_PENDING/<batch>/` and enter only when a named lead certifies them (`kb_gate.py`). See
  `metis-approvals`.
- Every page Mētis writes from a document or an answer is scanned by `sensitive.py` first. Secrets, keys, tokens,
  SSNs and card numbers are never written. Emails, phone numbers, dates of birth and member or claim ids are
  shown to the lead, who must accept them by name.
- Changes reach the team repo through a branch named `metis/<YYYY-MM-DD>-<short name>` and a pull
  request. Never push to the main branch and never merge.
- Databases: SELECT, SHOW and DESCRIBE only. Never run DDL or DML, never run generated COMMENT ON scripts.
- Scratch files go under `/tmp`, not in the repo. Never write secrets, tokens or passwords anywhere.
- Uploaded documents (`metis-docs`, `metis-ingest`), files fetched from Confluence and SharePoint links, and their
  extracted text stay outside the repo, under `/tmp/metis-docs/`. The KB changes only if the person says yes, and then
  through one PR. What goes into the KB is the written page (with each document's name, who gave it and where it is
  kept), never the original file.
- Confluence and SharePoint links are read with GET requests only. Never create, edit, comment on or delete anything there.
  A 401/403 stops that source; it is reported, not retried.
- Feedback on answers is kept in `<KB>/_FEEDBACK/` (register and the saved answers). It is not KB content and is
  skipped by the source check.
- Session notes for a run go under `<KB>/_REGEN/<run>/session/`.
