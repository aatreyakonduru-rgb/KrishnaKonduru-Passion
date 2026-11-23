---
name: metis-docs
description: Read documents a person uploads (Word, Excel, PowerPoint, PDF, text, transcripts) together with the Mētis knowledge base and do what they ask - summarise, compare with the KB, answer questions, list gaps. The files are not added to the repo. Afterwards offer to update the KB from them; only on a yes, write the changes and open one PR for the KB owner to approve.
argument-hint: "[what you want done with the files]"
allowed-tools: [read, write, edit, grep, glob, exec]
triggers:
  - model
---

# Read uploaded documents with the KB

`$METIS` is the folder two levels above this SKILL.md; `<KB>` holds `.metis/kb-profile.yaml`.
Rules that apply: `$METIS/rules/metis-evidence.md`, `$METIS/rules/metis-writes.md`.

For many files, folders, zips or Confluence / SharePoint links, or when the goal is to add them to the KB, use
`metis-ingest` instead. This skill is for reading a few files you have uploaded and answering questions about them.

## 1. Get the files and the request
- The person uploads the files in chat and says what they want. If they gave no request, ask once:
  "What do you want me to do with these: a summary, a comparison with the KB, answers to questions, or something else?"
- Ask who is giving the files if it isn't clear from the chat (a name; it goes in the register if the KB is updated).
- Never copy the files into the repo. Keep them where the upload put them, or under `/tmp/metis-docs/`.
- Remind the person once not to upload files with member data (PHI/PII) or passwords unless their team allows it.

## 2. Read them
- `python3 $METIS/tools/read_docs.py extract /tmp/metis-docs/<run> <file>... --by "<name>"`
  (`<run>` = `<YYYY-MM-DD>-<short name>`). It writes one `<doc id>.txt` per file, each line starting with its
  place: `p3` (PDF page), `slide4`, `Sheet1!B7`, `para12` (Word paragraph or table row), `line40`.
- Tell the person which files were read and which were not, with the reason (a scan or picture-only file,
  a password-protected file, a type with no reader). A file that was not read is not used as a source.
- Pictures (screenshots, scans, diagrams, pictures inside files) are not text, but you can look at them:
  `python3 $METIS/tools/doc_images.py extract /tmp/metis-docs/<run>`, open each picture file, write
  `IMAGE_TEXT.yaml`, then `doc_images.py merge`. The steps and rules are in `$METIS/skills/metis-ingest/SKILL.md`,
  step 2b. Quote picture text like any other place, e.g. `#slide4/image1`. A fact you can't read clearly becomes a
  question for the person.

## 3. Read the KB
- Find the KB files that cover the same topics (`grep` the KB for the names, tables, screens and terms in
  the documents; `<KB>/KNOWLEDGE-MANIFEST.yaml` lists every file). Read them; the KB lines already carry their sources.

## 4. Do what was asked
- Answer in chat, or as a file under `/tmp/metis-docs/<run>/` when it is long (a summary document, a table).
- Every statement names its source:
  - from a document: `[E: doc:<doc id>#<place> "quoted text"]`, the quote copied exactly from that place, under 20 words
  - from the KB: the KB file, e.g. `[E: kb:app/ORDERS_FRD.md]`
- Where a document and the KB disagree, show both, each with its source, and do not pick one.
- Where nothing covers a point, say "not in the documents or the KB". Never fill the gap.
- Before showing the result, run `python3 $METIS/tools/read_docs.py check /tmp/metis-docs/<run> <result file>`
  and fix every problem it lists (for a chat answer, write it to a file first and check that).

## 5. Offer to update the KB
Ask: "Do you want me to update the KB with these documents and what I found? I'd add or change these files: <list>,
and raise these questions: <list>. Nothing changes until you say yes. Once the KB is locked, a named lead must also certify it before it enters the KB."
- If no: stop. Nothing is written anywhere; the extracted text stays only in `/tmp`.
- If yes:
  1. Branch `metis/<YYYY-MM-DD>-docs-<short name>` from `repo.base_branch`.
  2. Make the changes inside `<KB>/` only. Add new facts with their doc tags. Where a document disagrees with a KB
     line, leave the KB line as it is and raise a P1 question naming both sources
     (`python3 $METIS/tools/questions.py add <KB> <file>`). Gaps become questions too.
  3. Any KB file listed in `<KB>/.metis/kb-keep.yaml` is not edited; put the change beside it as `<name>.NEW.md`.
  4. `python3 $METIS/tools/read_docs.py record <KB> /tmp/metis-docs/<run> [--kept-at "<where the originals are kept>"]`.
     It checks every doc quote in the KB again and writes `<KB>/_EVIDENCE/documents/DOC_SOURCES.yaml`: each file's
     name, fingerprint (sha256), size, who gave it, when, and every quote that was checked. Ask the person where the
     original files are kept (a SharePoint or Confluence link) so reviewers can open them; leave `--kept-at` out if they don't say.
  5. KB locked: stage the changes with `python3 $METIS/tools/kb_gate.py propose <KB> --batch docs-<short name> --from <folder>`
     and let a named lead certify them (see `$METIS/rules/metis-approvals.md`). A document with a read restriction needs a
     lead's approval first (`doc_kb.py approve-restricted`). Then `python3 $METIS/tools/questions.py html <KB>`,
     `python3 $METIS/tools/build_outputs.py <KB>` (0 problems).
  6. Commit only `<KB>/`, open one PR to `repo.base_branch`, and ask `owners.kb_owner` to review and approve it.
     The PR description lists the documents used (name, fingerprint, who gave them), the files changed and the
     questions raised. Never merge.
