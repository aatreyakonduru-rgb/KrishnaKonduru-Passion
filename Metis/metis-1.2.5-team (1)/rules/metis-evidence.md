# Mētis evidence rule: every KB line is verifiable

This rule overrides the evidence tags in `$METIS/kb-prompts/PROMPT_STANDARD.md` wherever they differ.

- Write only what a source shows. A fact carries `[E: <source>]` on its line, or on the nearest heading
  when the whole section comes from one source. The source forms are listed at the top of
  `$METIS/tools/verify_kb.py`: a repo line range (with an optional quote), a saved query, a saved
  Confluence page version, a saved Jira issue, a supplied file, an uploaded document with its quote, an answered question, another KB file (with an optional quote)
  or a settings key.
- Save what you read at the time you read it, so anyone can check it later without access to the system:
  - each SQL query and its result: `<KB>/_EVIDENCE/queries/<id>.sql` and `<id>.json`
  - each Confluence page: `<KB>/_EVIDENCE/confluence/<page id>-v<version>.txt`
  - each Jira issue: `<KB>/_EVIDENCE/jira/<KEY>.json`
  - each document the team hands over: `<KB>/_EVIDENCE/files/<name>`
  - a document uploaded in chat (`metis-docs`) is not saved in the repo. Its quotes are tagged
    `[E: doc:<id>#<place> "quoted text"]` and checked against the file, and `read_docs.py record` lists the file's
    fingerprint and every checked quote in `<KB>/_EVIDENCE/documents/DOC_SOURCES.yaml`
- `[A]` (assumption) is not used. If a statement has no source, do not write it as a fact: raise a
  question and write `[?: Q-0001]` where the fact would go.
- A tag that names a file (`file:` or `kb:`) carries a quote, `[E: kb:<path> "quoted text"]`, and the quote must be in
  that file. A bare file tag does not count when `verify.strict_tags` is on. An answer to a question is always checked
  this strictly.
- A correction someone gives after a disliked answer is not a source. It becomes a question for a lead; only a
  confirmed answer (`[E: answer:Q-xxxx]`) can change a line.
- Never link two things because their names look alike. A link needs an exact match in a source
  (same table name in SQL and code, an import line, an explicit mapping, a configuration entry).
- Counts, owners, schedules, volumes and business meaning are facts too. They need a source.
- Questions go in the register through `$METIS/tools/questions.py add`; the register is `<KB>/_QUESTIONS/VALIDATE_KB.yaml`. Each question names what the
  sources do say (tagged), what it blocks, its type, its priority and the role that can answer.
  Possible answers are listed only when a source gives them, each with its tag. Otherwise leave the
  list empty; the page shows "None found in sources". Never propose an answer of your own.
- Priority: P1 when sources disagree, or the gap blocks a whole document, or it touches security or
  access. P2 when one line is left not known. P3 for wording, naming or nice-to-have detail.
- Every build ends with `python3 $METIS/tools/verify_kb.py <stage folder>`. A build with problems is
  not finished: fix the line, tag it, or turn it into a question, then run the check again.
