---
name: metis-ingest
description: Add documents to the Mētis knowledge base. People hand over files (Word, PDF, Excel, PowerPoint, notes, text, zips, folders) and Confluence or SharePoint/OneDrive links. Mētis reads them all, links recursively, into text outside the repo (pass 1), then writes sourced pages, sorts them into KB categories and publishes them with the document name, who gave it and where it is kept (pass 2), through a lead's certification and one PR.
argument-hint: "[files, folders or links] [who is giving them]"
allowed-tools: [read, write, edit, grep, glob, exec]
triggers:
  - model
---

# Ingest documents into the KB

`$METIS` is the folder two levels above this SKILL.md; `<KB>` holds `.metis/kb-profile.yaml`.
Rules that apply: `$METIS/rules/metis-evidence.md`, `$METIS/rules/metis-writes.md`, `$METIS/rules/metis-approvals.md`.
Nothing in the repo changes until step 6, and step 6 only runs on a yes. Once the KB is locked, nothing enters the KB until a named lead certifies it (see `$METIS/rules/metis-approvals.md`).
`<run>` = `<YYYY-MM-DD>-<short name>`, `<scratch>` = `/tmp/metis-docs/<run>` (outside the repo).

## 1. Get the material and the name
- Take the files, folders, zips and links from the message. A link is a Confluence page address or a SharePoint /
  OneDrive file or folder link. If there is nothing, ask: "Send the documents or links you want added to the KB."
- Ask who is giving them, once, if the chat doesn't say (a name). It is written next to every page they feed.
- Ask where the originals are kept if they are only uploaded (a SharePoint folder or Confluence page), so reviewers can
  open them. Links already say where they are; those need no answer.
- Remind the person once: no member data (PHI/PII) or passwords unless their team allows it. Documents are scanned for
  secrets and member data before anything is written.

## 2. Pass 1: read everything into text
```bash
python3 $METIS/tools/doc_intake.py <KB> <scratch> --by "<name>" <file|folder|zip|link>...
```
- Folders and zips are read recursively. A Confluence link reads the page, all its child pages and their attachments.
  A SharePoint/OneDrive folder link reads every sub-folder. Old formats (.doc, .xls, .ppt) are converted when
  LibreOffice is installed. Limits: 300 files per run, 50 MB per file, 6 levels deep.
- Tokens come from the secrets named in `kb-profile.yaml` (`sources.confluence.secret`, `sources.sharepoint.secret`).
  GET requests only. A 401/403 or a missing secret stops that source; say so in plain words and carry on with the rest.
  Never print a token.
- Read `<scratch>/INTAKE.yaml` and tell the person what was read and what was not, each with the reason (scanned or
  picture-only file, password-protected file, a type with no reader, a link the token can't see, over a limit). A file
  that was not read is not a source. A scanned or picture-only file is read in step 2b.
- Re-running with the same files is safe: an identical file keeps its id; a changed file gets a new one. A Confluence
  or SharePoint item whose version has not changed since the last run is skipped; a changed one is read again and
  noted as a new version of the earlier document.
- A page or file with a read restriction (Confluence restrictions, SharePoint items not open to everyone) is marked
  restricted in `INTAKE.yaml`. Tell the person which ones, and that no page is written from them until a lead approves:
  `python3 $METIS/tools/doc_kb.py approve-restricted <scratch> <doc id> --kb <KB> --by "<lead>" --note "<why it may be added>"`.

## 2b. Pictures: you look at them
Screenshots, scanned PDFs, picture files, and pictures inside Word, PowerPoint, Excel and PDF files carry no text, so
a program can't read them. You (the model) can. No OCR tool is needed.
```bash
python3 $METIS/tools/doc_images.py extract <scratch>
```
- It saves each picture under `<scratch>/images/<doc id>/` and lists them in `<scratch>/IMAGES.yaml` (id, document,
  place such as `slide4/image2`, file). Icons under 4 KB, repeated pictures and formats you can't view (emf, wmf) are
  skipped with a reason. At most 200 pictures per run.
- Open each `pending` picture file with the read tool, so you see it, and write `<scratch>/IMAGE_TEXT.yaml`:
  `kind: text` for words in the picture (a screenshot, a scan, a table): copy them exactly, one line per line of text,
  keep table rows as `a | b | c`; `kind: description` for a diagram or photo: say plainly what it shows (boxes, labels,
  arrows, who points to whom), no guesses; `kind: decorative` for a logo or background.
- Never invent text you can't read. A blurred or cut-off part is left out or written as `[unreadable]`, and a fact
  that depends on it becomes a question.
- `python3 $METIS/tools/doc_images.py merge <scratch>` puts those lines into each document's text at the place of the
  picture (`slide4/image1`). It lists any picture not looked at. Repeat until it reports 0 problems.
- A scanned or picture-only file now counts as read. Tell the person which pictures were read as text, which were only
  described, and which were skipped.
- Facts that come from pictures are quotable like any other: `[E: doc:deck.pptx#slide4/image1 "Open | 30"]`.
  They are marked in the register and on the page as read from a picture by a model, so reviewers know to check the
  original. Description lines start with `(model description)`; prefer quoting `text` lines for facts, and treat a
  description as a pointer, not as proof of numbers or names.

## 3. Pass 2a: sort
```bash
python3 $METIS/tools/doc_kb.py classify <KB> <scratch>
```
- `<scratch>/PLAN.yaml` suggests a category per document from `<KB>/.metis/doc-categories.yaml`
  (else `$METIS/templates/doc-categories.yaml`), and flags documents already in the KB or replacing an older version.
- Show the person a table: document, suggested category, folder. Ask them to correct any. The suggestion is only
  a keyword guess; the person's answer wins. To add a category or move a folder, copy the template to
  `<KB>/.metis/doc-categories.yaml` and edit it there.

## 4. Pass 2b: write the pages
Read `<scratch>/<doc id>.txt` (each line starts with its place: `p3`, `slide4`, `Sheet1!B7`, `para12`, `line40`).
Write one or more pages per document or topic to `<scratch>/pages/<name>.md`:
```
---
title: Claims payment rules
category: requirements
---
- Claims are paid within 30 days [E: doc:Claims-Rules.docx#para1 "paid within 30 days"]
```
- Group by topic, not by file order. Several documents may feed one page; one long document may feed several.
- Every fact line carries `[E: doc:<doc id>#<place> "quote"]`: the quote copied exactly from that place, under 20
  words, with no `;` in it. Only write what the document says. Never add knowledge from memory.
- No `## Sources` section: the publisher adds it from the documents' details (name, who gave it, when, link).
- Where a document disagrees with a page already in the KB, don't edit that page. Raise a P1 question naming both
  sources (`python3 $METIS/tools/questions.py add <KB> <file>`, as `$METIS/skills/metis-docs/SKILL.md` step 5 shows).
- Anything the documents leave unclear becomes a question, not a fact.
- Leave out passwords, tokens, SSNs and member data. The publisher refuses pages that look like they contain them.

## 5. Check, then ask
```bash
python3 $METIS/tools/doc_kb.py publish <KB> <scratch> --dry-run
```
- Fix every problem it lists (bad category, quote not at that place, line with no source, credential-looking text,
  restricted document not yet approved) and run it again until it says 0 problems and shows the target file for each page.
- Show the person, in plain words: the pages and where each will go, the documents behind them (name, who gave them,
  link), the questions raised, and any sensitive-data findings. Ask: "Do you want me to send these for certification?
  Nothing enters the KB until <the lead> approves."
- If no: stop. The extracted text stays only under `/tmp`.

## 6. Only on a yes: stage for the lead, then one PR
1. `python3 $METIS/tools/doc_kb.py publish <KB> <scratch> [--kept-at "<where the originals are kept>"]`.
   - KB not locked yet (first build): it writes each page to its category folder with front matter and a Sources
     section, rewrites `<KB>/context/DOC_INDEX.md` and records every document and checked quote in
     `<KB>/_EVIDENCE/documents/DOC_SOURCES.yaml`.
   - KB locked: it writes the same pages to `<KB>/_PENDING/<batch>/` and a digest. Nothing is in the KB yet.
   A page that already exists and was not made by this tool, or is on `kb-keep.yaml`, is not replaced; the new text goes
   beside it as `<name>.NEW.md`.
2. Locked KB: tell the lead in chat what is waiting (`python3 $METIS/tools/kb_gate.py digest <KB> <batch>`): pages,
   documents, who gave them, findings. When the lead says approve, ask who is approving, then
   `python3 $METIS/tools/kb_gate.py certify <KB> <batch> --by "<name>" [--accept-review "<why>"]`. On reject:
   `kb_gate.py reject <KB> <batch> --by "<name>" --reason "<why>"` and tell the person who gave the documents.
3. `python3 $METIS/tools/questions.py html <KB>`, then `python3 $METIS/tools/build_outputs.py <KB>` (0 problems).
4. Branch `metis/<YYYY-MM-DD>-ingest-<short name>` from `repo.base_branch`, commit only `<KB>/`, open one PR and ask
   `owners.kb_owner` to review and approve it. The PR description lists each document (name, fingerprint, who gave it,
   link), the pages added or changed, the questions raised and who certified. Never merge.

## When done
Report in plain words: documents read and not read (with reasons), pages by category, what is waiting for a lead or
was certified and by whom, files left beside existing ones (`.NEW.md`), questions raised, and the PR link.
