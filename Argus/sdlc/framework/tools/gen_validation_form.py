#!/usr/bin/env python3
"""Generate the knowledge-base validation form (single self-contained HTML file).

Reads the open-question registry maintained under the knowledge base and emits one
HTML file with no external assets, so it renders anywhere — the Devin chat sidebar,
a browser, or an email attachment. Each question is shown with the KB context that
raised it, why it is being asked, Devin's current understanding and a proposed
answer the reviewer can accept, correct or defer. The form produces a
SDLC-KB-VALIDATION-ANSWERS block that /document-validation parses back and applies
to the KB documents.

    python3 sdlc/framework/tools/gen_validation_form.py \
        docs/knowledge-base/VALIDATION/KB_OPEN_QUESTIONS.yaml

Writes KB-VALIDATION-FORM.html beside the input unless -o is given.
See the header of that registry for the input schema.
"""
import argparse
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifact_kit  # noqa: E402

import yaml

ANSWER_BLOCK_VERSION = 1
DECISIONS = ("accept", "correct", "defer")
PRIORITIES = ("P1", "P2", "P3")
REQUIRED_FIELDS = ("question", "context", "why", "understanding", "proposed_answer")


def load_registry(path):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError("registry must contain a YAML mapping")
    if not data.get("sections"):
        raise ValueError("registry is missing required key: sections")

    seen = set()
    for section in data["sections"]:
        if not section.get("name"):
            raise ValueError("every section needs a name")
        for question in section.get("questions") or []:
            qid = question.get("id")
            if not qid:
                raise ValueError("every question needs an id (section %s)" % section["name"])
            if qid in seen:
                raise ValueError("duplicate question id: %s" % qid)
            seen.add(qid)
            for field in REQUIRED_FIELDS:
                if not question.get(field):
                    raise ValueError("question %s is missing %s" % (qid, field))
            priority = question.get("priority", "P2")
            if priority not in PRIORITIES:
                raise ValueError("question %s has unsupported priority: %s" % (qid, priority))
            if not question.get("kb_doc"):
                raise ValueError("question %s does not say which KB document it affects" % qid)
    if not seen:
        raise ValueError("registry contains no questions")
    return data


def render_question(question):
    qid = html.escape(question["id"])
    priority = question.get("priority", "P2")
    parts = ['<div class="q" data-qid="%s" data-priority="%s">' % (qid, priority)]
    parts.append(
        '<div class="qhead"><span class="pri p%s">%s</span>'
        '<h3>%s</h3></div>' % (priority[-1], priority, html.escape(question["question"]))
    )

    docs = question["kb_doc"]
    if isinstance(docs, str):
        docs = [docs]
    parts.append(
        '<p class="doc">Affects %s</p>'
        % ", ".join("<code>%s</code>" % html.escape(d) for d in docs)
    )

    for label, key in (
        ("Context", "context"),
        ("Why we are asking", "why"),
        ("Our current understanding", "understanding"),
        ("What we think the answer is", "proposed_answer"),
    ):
        css = "prop" if key == "proposed_answer" else "ctx"
        parts.append(
            '<div class="%s"><span class="lbl">%s</span><p>%s</p></div>'
            % (css, label, html.escape(question[key]))
        )

    if question.get("options"):
        parts.append('<div class="ctx"><span class="lbl">Known candidate answers</span><ul>')
        for option in question["options"]:
            parts.append("<li>%s</li>" % html.escape(str(option)))
        parts.append("</ul></div>")

    if question.get("kb_effect"):
        parts.append(
            '<div class="ctx"><span class="lbl">What changes in the KB</span><p>%s</p></div>'
            % html.escape(question["kb_effect"])
        )

    parts.append('<div class="decide">')
    for value, label in (
        ("accept", "Proposed answer is correct"),
        ("correct", "Different answer &mdash; mine below"),
        ("defer", "Still genuinely open &mdash; leave unresolved"),
    ):
        parts.append(
            '<label class="opt"><input type="radio" name="d-%s" data-decision="%s" '
            'value="%s"> %s</label>' % (qid, qid, value, label)
        )
    parts.append("</div>")
    parts.append(
        '<label class="alabel" for="a-%s">Your answer, correction or note'
        '<span class="hint"> — required when you pick "different answer"</span></label>' % qid
    )
    parts.append('<textarea id="a-%s" data-answer="%s" rows="3"></textarea>' % (qid, qid))
    parts.append("</div>")
    return "".join(parts)


def render(data):
    questions = []
    body = []
    toc = [
        '<nav class="toc"><span class="lbl">Jump to your area</span><ol>',
    ]
    for index, section in enumerate(data["sections"]):
        section_questions = section.get("questions") or []
        name = html.escape(section["name"])
        toc.append(
            '<li><a href="#sec-%d">%s</a>'
            '<span class="tn" data-toc="%d">0/%d</span></li>'
            % (index, name, index, len(section_questions))
        )
        body.append(
            '<section id="sec-%d" data-section="%s"><h2>%s <span class="n">%d</span></h2>'
            % (index, name, name, len(section_questions))
        )
        if section.get("intro"):
            body.append('<p class="intro">%s</p>' % html.escape(section["intro"]))
        for question in section_questions:
            body.append(render_question(question))
            questions.append(
                {
                    "id": question["id"],
                    "question": question["question"],
                    "section": section["name"],
                    "section_index": index,
                    "priority": question.get("priority", "P2"),
                    "proposed": question["proposed_answer"],
                }
            )
        body.append("</section>")
    toc.append("</ol></nav>")

    meta = {
        "registry": data.get("registry_id", "KB_OPEN_QUESTIONS"),
        "generated": str(data.get("generated", "")),
        "version": ANSWER_BLOCK_VERSION,
    }

    page = TEMPLATE % {
        "title": html.escape(data.get("title") or "Knowledge base validation"),
        "subtitle": html.escape(data.get("subtitle") or ""),
        "generated": html.escape(str(data.get("generated", ""))),
        "toc": "\n".join(toc),
        "body": "\n".join(body),
        "meta_json": json.dumps(meta),
        "questions_json": json.dumps(questions),
    }
    return to_kit(page, data.get("title") or "Knowledge base validation", data.get("subtitle") or "")


SHELL_RULES = (":root", "*", "body", "main", "header", "h1", ".sub")
COLOURS = [
    ("background: #2f6fd0", "background: rgb(var(--bg-accent))"),
    ("solid #2f6fd0", "solid rgb(var(--bg-accent))"),
    ("color: #fff;", "color: #ffffff;"),
    (re.compile(r"#fff\b"), "rgb(var(--bg-elevated))"),
    (re.compile(r"#(16202c)\b"), "rgb(var(--text-primary))"),
    (re.compile(r"#(5b6673|96a0ac)\b"), "rgb(var(--text-secondary))"),
    (re.compile(r"#(dce1e7|eef1f4|e3e8ee|c3cbd4)\b"), "rgb(var(--border-primary))"),
    (re.compile(r"#(f1f3f6|fbfcfd|f7faff|fbfefc|f4f6f9)\b"), "rgb(var(--tint-secondary))"),
    (re.compile(r"#2f6fd0\b"), "rgb(var(--text-accent))"),
]


def to_kit(page, title, subtitle):
    """The same form inside the Acme Claims page shell: purple header, light and dark, print."""
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    body = page.split("</header>", 1)[1].split("</main>", 1)[0]
    js = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    rules = []
    for sel, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sel = sel.strip()
        if sel in SHELL_RULES:
            continue
        rules.append("%s {%s}" % (", ".join(".kbv " + part.strip() for part in sel.split(",")), decl))
    css = "\n".join(rules)
    for old, new in COLOURS:
        css = old.sub(new, css) if hasattr(old, "sub") else css.replace(old, new)
    css += "\n@media print { .kbv .bar, .kbv #out { display: none; } }"
    return artifact_kit.render_page(title, '<div class="kbv">%s</div>' % body,
                                    subtitle=html.escape(subtitle), extra_css=css, extra_js=js)


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px 20px 48px;
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #16202c; background: #f4f6f9;
  }
  main { margin: 0 auto; }
  header { margin-bottom: 16px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #5b6673; font-size: 13px; margin: 0; }
  .bar {
    position: sticky; top: 0; z-index: 5; margin: 16px 0 20px; padding: 10px 14px;
    background: #fff; border: 1px solid #dce1e7; border-radius: 8px;
    display: flex; gap: 12px; align-items: center; justify-content: space-between;
    flex-wrap: wrap; box-shadow: 0 1px 2px rgba(16,32,48,.06);
  }
  .count { font-size: 13px; color: #5b6673; }
  .count b { color: #16202c; }
  .filters { font-size: 13px; color: #5b6673; }
  .filters label { margin-right: 10px; font-weight: 400; }
  .toc {
    background: #fff; border: 1px solid #dce1e7; border-radius: 8px;
    padding: 12px 18px 14px; margin-bottom: 16px;
  }
  .toc ol {
    margin: 6px 0 0; padding: 0; list-style: none;
    display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 2px 18px;
  }
  .toc li { display: flex; align-items: baseline; gap: 8px; font-size: 14px; padding: 3px 0; }
  .toc a { color: #2f6fd0; text-decoration: none; }
  .toc a:hover { text-decoration: underline; }
  .toc .tn {
    margin-left: auto; font-size: 12px; color: #5b6673; font-variant-numeric: tabular-nums;
    background: #f1f3f6; border-radius: 10px; padding: 1px 7px; flex: none;
  }
  .toc .tn.alldone { background: #e6f5ec; color: #1a7f4b; }
  .toc li.off { opacity: .4; }
  section {
    background: #fff; border: 1px solid #dce1e7; border-radius: 8px;
    padding: 4px 18px 18px; margin-bottom: 16px; scroll-margin-top: 84px;
  }
  section[hidden] { display: none; }
  h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .04em; color: #5b6673; margin: 18px 0 4px; }
  h2 .n { color: #96a0ac; font-weight: 400; }
  h3 { font-size: 15px; margin: 0; }
  .intro { color: #5b6673; font-size: 13px; margin: 0 0 12px; }
  .q { padding: 16px 0; border-top: 1px solid #eef1f4; }
  .q:first-of-type { border-top: 0; }
  .q[hidden] { display: none; }
  .qhead { display: flex; gap: 8px; align-items: baseline; }
  .pri {
    font-size: 11px; font-weight: 700; letter-spacing: .04em; padding: 2px 6px;
    border-radius: 4px; background: #eef1f4; color: #5b6673; flex: none;
  }
  .pri.p1 { background: #fdecea; color: #b02a1e; }
  .pri.p2 { background: #fdf3e2; color: #8a5a00; }
  .doc { font-size: 12px; color: #5b6673; margin: 6px 0 10px; }
  .doc code { font-size: 12px; background: #f1f3f6; padding: 1px 4px; border-radius: 3px; }
  .ctx, .prop { margin: 0 0 8px; padding-left: 10px; border-left: 2px solid #e3e8ee; }
  .prop { border-left-color: #2f6fd0; background: #f7faff; padding: 6px 10px; border-radius: 0 4px 4px 0; }
  .lbl {
    display: block; font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .04em; color: #5b6673; margin-bottom: 2px;
  }
  .ctx p, .prop p { margin: 0; }
  .ctx ul { margin: 2px 0 0; padding-left: 20px; }
  .decide { margin: 12px 0 8px; display: flex; gap: 14px; flex-wrap: wrap; }
  .opt { font-size: 13px; font-weight: 500; }
  .opt input { margin-right: 5px; }
  .alabel { display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .hint { font-weight: 400; color: #5b6673; }
  textarea, input[type=text] {
    width: 100%%; padding: 8px 10px; font: inherit; color: inherit;
    border: 1px solid #c3cbd4; border-radius: 6px; background: #fff; resize: vertical;
  }
  textarea:focus, input:focus { outline: 2px solid #2f6fd0; outline-offset: -1px; border-color: #2f6fd0; }
  .q.done { background: #fbfefc; }
  .q.done h3::before { content: "\\2713 "; color: #1a7f4b; font-weight: 700; }
  .q.needtext textarea { border-color: #c0392b; }
  button {
    font: inherit; font-weight: 600; padding: 8px 14px; border-radius: 6px; cursor: pointer;
    border: 1px solid #2f6fd0; background: #2f6fd0; color: #fff;
  }
  button.ghost { background: #fff; color: #2f6fd0; }
  #out { margin-top: 18px; }
  #out textarea {
    font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    min-height: 220px; background: #fbfcfd;
  }
  .note { font-size: 13px; color: #5b6673; }
  .missing { color: #c0392b; font-size: 13px; margin: 8px 0 0; }
</style>
</head>
<body>
<main>
<header>
  <h1>%(title)s</h1>
  <p class="sub">%(subtitle)s</p>
</header>

<div class="bar">
  <span class="count"><b id="done">0</b> of <b id="total">0</b> reviewed</span>
  <span class="filters">
    Show:
    <label><input type="checkbox" class="pf" value="P1" checked> P1</label>
    <label><input type="checkbox" class="pf" value="P2" checked> P2</label>
    <label><input type="checkbox" class="pf" value="P3" checked> P3</label>
    <label><input type="checkbox" id="hidedone"> hide reviewed</label>
  </span>
  <span>
    <button class="ghost" id="acceptall" type="button">Accept all remaining</button>
    <button class="ghost" id="clear" type="button">Clear</button>
    <button id="build" type="button">Generate answers &#9662;</button>
  </span>
</div>

%(toc)s

%(body)s

<div id="out" hidden>
  <h2>Answers</h2>
  <p class="note">Copy this block and paste it back to Devin, or download it and attach it. It is plain text &mdash; nothing is sent anywhere from this page.</p>
  <p class="missing" id="missing" hidden></p>
  <textarea id="yaml" readonly spellcheck="false"></textarea>
  <p>
    <button id="copy" type="button">Copy to clipboard</button>
    <button class="ghost" id="download" type="button">Download .yaml</button>
    <span class="note" id="copystate"></span>
  </p>
</div>
</main>

<script>
(function () {
  "use strict";
  var META = %(meta_json)s;
  var QUESTIONS = %(questions_json)s;
  var STORE = "sdlc-kb-validation-" + META.registry;

  var fields = {};
  QUESTIONS.forEach(function (q) {
    fields[q.id] = {
      radios: Array.prototype.slice.call(document.querySelectorAll('[data-decision="' + q.id + '"]')),
      answer: document.querySelector('[data-answer="' + q.id + '"]'),
      wrap: document.querySelector('.q[data-qid="' + q.id + '"]')
    };
  });
  document.getElementById("total").textContent = QUESTIONS.length;

  function decisionOf(id) {
    var checked = fields[id].radios.filter(function (r) { return r.checked; })[0];
    return checked ? checked.value : "";
  }

  function answerOf(id) {
    return (fields[id].answer.value || "").trim();
  }

  function activePriorities() {
    return Array.prototype.slice.call(document.querySelectorAll(".pf"))
      .filter(function (c) { return c.checked; })
      .map(function (c) { return c.value; });
  }

  function refresh() {
    var pri = activePriorities();
    var hideDone = document.getElementById("hidedone").checked;
    var done = 0;
    var perSection = {};
    QUESTIONS.forEach(function (q) {
      var f = fields[q.id];
      var decision = decisionOf(q.id);
      var complete = decision !== "" && !(decision === "correct" && answerOf(q.id) === "");
      if (complete) done++;
      var tally = perSection[q.section_index] ||
        (perSection[q.section_index] = { done: 0, total: 0 });
      tally.total++;
      if (complete) tally.done++;
      f.wrap.classList.toggle("done", complete);
      f.wrap.classList.toggle("needtext", decision === "correct" && answerOf(q.id) === "");
      var visible = pri.indexOf(q.priority) !== -1 && !(hideDone && complete);
      f.wrap.hidden = !visible;
    });
    document.querySelectorAll("section").forEach(function (s) {
      var any = Array.prototype.slice.call(s.querySelectorAll(".q"))
        .some(function (q) { return !q.hidden; });
      s.hidden = !any;
    });
    document.querySelectorAll("[data-toc]").forEach(function (badge) {
      var tally = perSection[badge.getAttribute("data-toc")] || { done: 0, total: 0 };
      badge.textContent = tally.done + "/" + tally.total;
      badge.classList.toggle("alldone", tally.total > 0 && tally.done === tally.total);
      var section = document.getElementById("sec-" + badge.getAttribute("data-toc"));
      badge.parentNode.classList.toggle("off", !!(section && section.hidden));
    });
    document.getElementById("done").textContent = done;
    save();
  }

  function save() {
    var state = {};
    QUESTIONS.forEach(function (q) {
      state[q.id] = { d: decisionOf(q.id), a: fields[q.id].answer.value };
    });
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* private mode */ }
  }

  function restore() {
    var raw;
    try { raw = localStorage.getItem(STORE); } catch (e) { return; }
    if (!raw) return;
    var state;
    try { state = JSON.parse(raw); } catch (e) { return; }
    QUESTIONS.forEach(function (q) {
      var saved = state[q.id];
      if (!saved) return;
      fields[q.id].radios.forEach(function (r) { r.checked = r.value === saved.d; });
      fields[q.id].answer.value = saved.a || "";
    });
  }

  // Block scalars keep multi-line answers readable and need no escaping, but a
  // literal block cannot express a trailing-newline-free empty string, so short
  // single-line answers are emitted as JSON strings instead.
  function yamlValue(text, indent) {
    var pad = new Array(indent + 1).join(" ");
    if (text.indexOf("\\n") === -1) return JSON.stringify(text);
    var body = text.replace(/\\r/g, "").split("\\n").map(function (line) {
      return line ? pad + line : "";
    }).join("\\n");
    return "|-\\n" + body;
  }

  function build() {
    var lines = [
      "# SDLC-KB-VALIDATION-ANSWERS v" + META.version,
      "registry: " + JSON.stringify(META.registry),
      "form_generated: " + JSON.stringify(META.generated),
      "submitted_at: " + JSON.stringify(new Date().toISOString()),
      "reviewer: \\"\\"   # optional — fill in if you want it recorded in the KB",
      "answers:"
    ];
    var untouched = [];
    var needtext = [];
    QUESTIONS.forEach(function (q) {
      var decision = decisionOf(q.id);
      var answer = answerOf(q.id);
      if (decision === "") {
        untouched.push(q.id);
        return;
      }
      if (decision === "correct" && answer === "") needtext.push(q.id);
      lines.push("  - id: " + JSON.stringify(q.id));
      lines.push("    section: " + JSON.stringify(q.section));
      lines.push("    question: " + JSON.stringify(q.question));
      lines.push("    decision: " + JSON.stringify(decision));
      if (decision === "accept") {
        lines.push("    answer: " + yamlValue(q.proposed, 8));
      }
      if (answer !== "") {
        lines.push("    " + (decision === "accept" ? "note" : "answer") + ": " +
          yamlValue(answer, 8));
      }
    });

    document.getElementById("yaml").value = lines.join("\\n") + "\\n";
    var warn = document.getElementById("missing");
    var msg = [];
    if (needtext.length) {
      msg.push("Marked \\u201cdifferent answer\\u201d with nothing typed: " + needtext.join(", ") + ".");
    }
    if (untouched.length) {
      msg.push(untouched.length + " question(s) not reviewed — they stay unresolved in the KB.");
    }
    warn.textContent = msg.join(" ");
    warn.hidden = msg.length === 0;
    document.getElementById("out").hidden = false;
    document.getElementById("copystate").textContent = "";
    document.getElementById("yaml").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  document.getElementById("build").addEventListener("click", build);

  document.getElementById("acceptall").addEventListener("click", function () {
    if (!confirm("Mark every question you have not reviewed as \\u201cproposed answer is correct\\u201d?")) return;
    QUESTIONS.forEach(function (q) {
      if (decisionOf(q.id) !== "") return;
      fields[q.id].radios.forEach(function (r) { r.checked = r.value === "accept"; });
    });
    refresh();
  });

  document.getElementById("copy").addEventListener("click", function () {
    var box = document.getElementById("yaml");
    var state = document.getElementById("copystate");
    box.select();
    // Clipboard access is often denied in a sandboxed iframe; select-then-copy
    // by hand always works, so failure just tells the user to do that.
    function ok() { state.textContent = "Copied."; }
    function fail() { state.textContent = "Copy blocked here — the text is selected, press Ctrl/Cmd+C."; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(box.value).then(ok, fail);
    } else {
      try { document.execCommand("copy") ? ok() : fail(); } catch (e) { fail(); }
    }
  });

  document.getElementById("download").addEventListener("click", function () {
    var blob = new Blob([document.getElementById("yaml").value], { type: "text/yaml" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "KB-VALIDATION-ANSWERS.yaml";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  document.getElementById("clear").addEventListener("click", function () {
    if (!confirm("Clear every answer on this form?")) return;
    QUESTIONS.forEach(function (q) {
      fields[q.id].radios.forEach(function (r) { r.checked = false; });
      fields[q.id].answer.value = "";
    });
    document.getElementById("out").hidden = true;
    refresh();
  });

  Object.keys(fields).forEach(function (id) {
    fields[id].radios.forEach(function (r) { r.addEventListener("change", refresh); });
    fields[id].answer.addEventListener("input", refresh);
  });
  document.querySelectorAll(".pf").forEach(function (c) { c.addEventListener("change", refresh); });
  document.getElementById("hidedone").addEventListener("change", refresh);

  restore();
  refresh();
})();
</script>
</body>
</html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("registry", help="path to KB_OPEN_QUESTIONS.yaml")
    parser.add_argument("-o", "--output", help="output HTML path (default: beside the input)")
    args = parser.parse_args(argv)

    try:
        data = load_registry(args.registry)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        sys.stderr.write("gen_validation_form: %s\n" % exc)
        return 1

    output = args.output
    if not output:
        output = os.path.join(
            os.path.dirname(os.path.abspath(args.registry)), "KB-VALIDATION-FORM.html"
        )

    with open(output, "w", encoding="utf-8") as fh:
        fh.write(render(data))
    sys.stdout.write("%s\n" % output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
