---
name: metis-tasks
description: Pick up, run and finish tasks queued by the Mētis UI (ask tasks and build-stage tasks). A Devin session claims the task, does the model work using the relevant Mētis skill, and marks the task done with its note or answer.
argument-hint: "<claim|list|show|complete> <KB> [--by <name>]"
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
triggers:
  - model
---

# Metis Task Queue (Devin Worker)

`$METIS` is the Mētis plugin folder: the folder two levels above this `SKILL.md`. `<KB>` is the KB folder holding `.metis/kb-profile.yaml`.

The Metis UI delegates reasoning and model work (deep Q&A answers, KB page generation) to Devin sessions through a file-backed task queue located in `<KB>/.metis/tasks/`.

Follow `$METIS/rules/metis-evidence.md`, `$METIS/rules/metis-approvals.md`, and `$METIS/rules/metis-writes.md` throughout.

---

## 1. List and Claim Tasks

To inspect queued work:
```bash
python3 $METIS/tools/ui/tasks.py list <KB> --status queued
```

To claim the next queued task (or a specific task by ID):
```bash
python3 $METIS/tools/ui/tasks.py claim <KB> [TASK-ID] --by "Devin Session"
```

To display task instructions and details:
```bash
python3 $METIS/tools/ui/tasks.py show <KB> <TASK-ID>
```

---

## 2. Handling `ask` Tasks

When the task kind is `ask`:
1. Read the user's question and any context/instructions in the task definition.
2. Use the `metis-ask` skill workflow:
   - Check feedback hints: `python3 $METIS/tools/feedback.py hints <KB> "<question>"`
   - Search the KB (`grep`, manifest, impact matrix).
   - If nothing matches, find the path before you give up: try the person's words, near spellings, and the names in
     `KNOWLEDGE-MANIFEST.yaml` and `CROSS-LAYER/LINK_GRAPH.yaml`. Follow links to related pages.
   - If two or more readings of the question remain, ask the person (see "Asking the person" below). Do not ask when the KB
     already answers it, and never ask to be told a fact the KB should hold.
   - Formulate the answer in markdown. Every line with a claim must cite a KB file: `[E: kb:<path> "quote"]`.
   - Unknown information goes under `## Not in the KB` as questions (`[?: Q-xxxx]`). When the KB has nothing, still say what you
     searched for, what is nearby (with its pages), and how to ask it so the KB can answer. Never fill the gap in.
3. Save the answer to a temporary file (e.g. `/tmp/answer.md` or outside the KB).
4. Verify the answer has 0 source problems:
   ```bash
   python3 $METIS/tools/verify_kb.py <KB> --answer /tmp/answer.md
   ```
5. Complete the task:
   ```bash
   python3 $METIS/tools/ui/tasks.py complete <KB> <TASK-ID> --by "Devin Session" --file /tmp/answer.md
   ```
   *Note: `complete` calls `answers.attach_model_answer`, which validates the answer and attaches it to the user's ask record. If source verification fails, the completion is rejected.*

### Confidence

The UI computes a confidence score (0-100) from your answer; you never write one. 100 means one KB line states the answer. Any
line that combines KB lines or draws a conclusion the KB does not state must start with `Inferred:` and still cite the lines it
comes from. A hidden inference is a wrong answer: the score is only honest if inferences are marked.

### Asking the person

The Ask page shows your questions to whoever asked, in their own words, and sends their reply back to you.
```bash
python3 $METIS/tools/ui/tasks.py ask-user <KB> <TASK-ID> --by "Devin Session" --question "<question 1>" [--question "<question 2>"]
python3 $METIS/tools/ui/tasks.py wait <KB> <TASK-ID>      # prints "question -> reply"; if it says no reply yet, run it again
```
- At most 2 questions per round and 2 rounds per task. After that, answer with what the KB has.
- Offer the readings you found, in the KB's own words: "By menus, do you mean the screens (Owners, Vets), the navigation links
  in the layout, or menu rows in the database?" A short question beats an open one.
- Use the reply only to decide where to look. A fact still needs a KB line with its `[E: kb:...]` tag; the reply is not a source.
- If `wait` keeps returning no reply, finish with the best KB answer and a `## Not in the KB` section instead of holding the task.

---

## 3. Handling `build-stage` Tasks

When the task kind is `build-stage`:
1. Read the instructions in the task. Note the staging folder (`<run_dir>`, typically `<KB>/_REGEN/<run>`) and stage name.
2. Run the stage skill according to the stage:
   - **context**: `kb-context-build --stage <run_dir> --rebuild`
   - **app:<name>**: `app-run-pipeline <name> <source_dir> --stage <run_dir> --rebuild`
   - **etl:<name>**: `etl-run-pipeline <name> --stage <run_dir> --rebuild`
   - **db**: `db-run-pipeline --env <ref_env> --db <label> --stage <run_dir> --rebuild`
   - **cross-layer**: `db-cross-module --stage <run_dir> --rebuild`, then `app-cross-pipeline <run_dir>`
3. Ensure all generated pages cite evidence (`[E: ...]`) and write all outputs strictly inside `<run_dir>`. Never write directly into the live `<KB>`.
4. Record the finished stage in the build plan and complete the task:
   ```bash
   python3 $METIS/tools/build_plan.py done <run_dir> "<stage_name>"
   python3 $METIS/tools/ui/tasks.py complete <KB> <TASK-ID> --by "Devin Session" --note "Built <stage_name>: <summary>"
   ```

---

## 4. Failure or Blockers

If a task cannot be completed due to missing sources or errors:
```bash
python3 $METIS/tools/ui/tasks.py fail <KB> <TASK-ID> --by "Devin Session" --note "Detailed reason for failure"
```
A lead can queue a failed task again from the Build screen.
