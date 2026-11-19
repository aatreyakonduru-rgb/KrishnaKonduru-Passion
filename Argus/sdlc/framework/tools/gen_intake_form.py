#!/usr/bin/env python3
"""Generate a self-contained intake question form (single HTML file).

Reads a questions YAML written into the session directory by /intake and emits
one HTML file with no external assets, so it renders anywhere — the Devin chat
sidebar, a browser, or an email attachment. The form produces a SDLC-INTAKE-ANSWERS
block that /intake parses back into the SPEC.

    python3 sdlc/framework/tools/gen_intake_form.py \
        sdlc/framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-INTAKE-QUESTIONS.yaml

Writes {REQ_ID}-INTAKE-FORM.html beside the input unless -o is given.
See .devin/templates/intake-questions.yaml.template for the input schema.
"""
import argparse
import html
import json
import os
import sys

import yaml

ANSWER_BLOCK_VERSION = 1


def load_questions(path):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError("questions file must contain a YAML mapping")
    for key in ("requirement_id", "sections"):
        if not data.get(key):
            raise ValueError("questions file is missing required key: %s" % key)

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
            if not question.get("text"):
                raise ValueError("question %s has no text" % qid)
            kind = question.get("type", "textarea")
            if kind not in ("textarea", "text", "choice"):
                raise ValueError("question %s has unsupported type: %s" % (qid, kind))
            if kind == "choice" and not question.get("options"):
                raise ValueError("choice question %s has no options" % qid)
    if not seen:
        raise ValueError("questions file contains no questions")
    return data


def render_question(question):
    qid = html.escape(question["id"])
    text = html.escape(question["text"])
    kind = question.get("type", "textarea")
    required = bool(question.get("required"))
    help_text = question.get("help")

    parts = ['<div class="q" data-qid="%s">' % qid]
    parts.append(
        '<label for="f-%s">%s%s</label>'
        % (qid, text, '<span class="req" title="Required">*</span>' if required else "")
    )
    if help_text:
        parts.append('<p class="help">%s</p>' % html.escape(help_text))

    if kind == "choice":
        options = "".join(
            '<option value="%s">%s</option>' % (html.escape(str(o)), html.escape(str(o)))
            for o in question["options"]
        )
        parts.append(
            '<select id="f-%s" data-field="%s"><option value="">— select —</option>%s</select>'
            % (qid, qid, options)
        )
    elif kind == "text":
        parts.append('<input type="text" id="f-%s" data-field="%s">' % (qid, qid))
    else:
        parts.append('<textarea id="f-%s" data-field="%s" rows="4"></textarea>' % (qid, qid))

    parts.append(
        '<label class="na"><input type="checkbox" data-na="%s"> Not applicable / unknown</label>'
        % qid
    )
    parts.append("</div>")
    return "".join(parts)


def render(data):
    req_id = data["requirement_id"]
    meta = {
        "requirement_id": req_id,
        "title": data.get("title", ""),
        "mode": data.get("mode", ""),
        "owner": data.get("owner", ""),
        "version": ANSWER_BLOCK_VERSION,
    }

    questions = []
    body = []
    for section in data["sections"]:
        body.append('<section><h2>%s</h2>' % html.escape(section["name"]))
        if section.get("intro"):
            body.append('<p class="intro">%s</p>' % html.escape(section["intro"]))
        for question in section.get("questions") or []:
            body.append(render_question(question))
            questions.append(
                {
                    "id": question["id"],
                    "question": question["text"],
                    "section": section["name"],
                    "required": bool(question.get("required")),
                }
            )
        body.append("</section>")

    subtitle = html.escape(data.get("title") or "Requirement intake")
    mode_label = html.escape((data.get("mode") or "").replace("_", "-") or "unspecified mode")

    return TEMPLATE % {
        "req_id": html.escape(req_id),
        "subtitle": subtitle,
        "mode": mode_label,
        "body": "\n".join(body),
        "meta_json": json.dumps(meta),
        "questions_json": json.dumps(questions),
    }


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(req_id)s — Intake questions</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px 20px 48px;
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #16202c; background: #f4f6f9;
  }
  main { max-width: 760px; margin: 0 auto; }
  header { margin-bottom: 20px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #5b6673; font-size: 13px; margin: 0; }
  .bar {
    position: sticky; top: 0; z-index: 5; margin: 16px 0 20px; padding: 10px 14px;
    background: #fff; border: 1px solid #dce1e7; border-radius: 8px;
    display: flex; gap: 12px; align-items: center; justify-content: space-between;
    box-shadow: 0 1px 2px rgba(16,32,48,.06);
  }
  .count { font-size: 13px; color: #5b6673; }
  .count b { color: #16202c; }
  section {
    background: #fff; border: 1px solid #dce1e7; border-radius: 8px;
    padding: 4px 18px 18px; margin-bottom: 16px;
  }
  h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .04em; color: #5b6673; margin: 18px 0 4px; }
  .intro { color: #5b6673; font-size: 13px; margin: 0 0 12px; }
  .q { padding: 14px 0; border-top: 1px solid #eef1f4; }
  .q:first-of-type { border-top: 0; }
  .q.answered label:first-child::before { content: "\\2713 "; color: #1a7f4b; font-weight: 700; }
  label { display: block; font-weight: 600; margin-bottom: 4px; }
  .req { color: #c0392b; margin-left: 3px; }
  .help { color: #5b6673; font-size: 13px; margin: 0 0 8px; }
  textarea, input[type=text], select {
    width: 100%%; padding: 8px 10px; font: inherit; color: inherit;
    border: 1px solid #c3cbd4; border-radius: 6px; background: #fff;
  }
  textarea { resize: vertical; min-height: 78px; }
  textarea:focus, input:focus, select:focus { outline: 2px solid #2f6fd0; outline-offset: -1px; border-color: #2f6fd0; }
  .na { font-weight: 400; color: #5b6673; font-size: 13px; margin-top: 6px; }
  .na input { margin-right: 6px; }
  .q.skipped textarea, .q.skipped input[type=text], .q.skipped select { background: #f1f3f6; color: #8b95a1; }
  button {
    font: inherit; font-weight: 600; padding: 8px 14px; border-radius: 6px; cursor: pointer;
    border: 1px solid #2f6fd0; background: #2f6fd0; color: #fff;
  }
  button.ghost { background: #fff; color: #2f6fd0; }
  button:disabled { opacity: .5; cursor: default; }
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
  <h1>%(req_id)s — Intake questions</h1>
  <p class="sub">%(subtitle)s &middot; %(mode)s</p>
</header>

<div class="bar">
  <span class="count"><b id="done">0</b> of <b id="total">0</b> answered</span>
  <span>
    <button class="ghost" id="clear" type="button">Clear</button>
    <button id="build" type="button">Generate answers &#9662;</button>
  </span>
</div>

%(body)s

<div id="out" hidden>
  <h2>Answers</h2>
  <p class="note">Opened from Argus, Save sends this block to the intake run. Anywhere else, copy it and paste it back to Devin; nothing is sent from a saved copy.</p>
  <p class="missing" id="missing" hidden></p>
  <textarea id="yaml" readonly spellcheck="false"></textarea>
  <p>
    <button id="save" type="button" hidden>Save</button>
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
  var STORE = "sdlc-intake-" + META.requirement_id;

  var fields = {};
  QUESTIONS.forEach(function (q) {
    fields[q.id] = {
      input: document.querySelector('[data-field="' + q.id + '"]'),
      na: document.querySelector('[data-na="' + q.id + '"]'),
      wrap: document.querySelector('.q[data-qid="' + q.id + '"]')
    };
  });
  document.getElementById("total").textContent = QUESTIONS.length;

  function valueOf(id) {
    var f = fields[id];
    if (f.na.checked) return "N/A";
    return (f.input.value || "").trim();
  }

  function refresh() {
    var done = 0;
    QUESTIONS.forEach(function (q) {
      var f = fields[q.id];
      var filled = valueOf(q.id) !== "";
      if (filled) done++;
      f.wrap.classList.toggle("answered", filled);
      f.wrap.classList.toggle("skipped", f.na.checked);
      f.input.disabled = f.na.checked;
    });
    document.getElementById("done").textContent = done;
    save();
  }

  function save() {
    var state = {};
    QUESTIONS.forEach(function (q) {
      state[q.id] = { v: fields[q.id].input.value, na: fields[q.id].na.checked };
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
      fields[q.id].input.value = saved.v || "";
      fields[q.id].na.checked = !!saved.na;
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
      "# SDLC-INTAKE-ANSWERS v" + META.version,
      "requirement_id: " + JSON.stringify(META.requirement_id),
      "mode: " + JSON.stringify(META.mode || ""),
      "owner: " + JSON.stringify(META.owner || ""),
      "submitted_at: " + JSON.stringify(new Date().toISOString()),
      "answers:"
    ];
    var missing = [];
    QUESTIONS.forEach(function (q) {
      var value = valueOf(q.id);
      if (value === "") {
        if (q.required) missing.push(q.id);
        return;
      }
      lines.push("  - id: " + JSON.stringify(q.id));
      lines.push("    section: " + JSON.stringify(q.section));
      lines.push("    question: " + JSON.stringify(q.question));
      lines.push("    answer: " + yamlValue(value, 8));
    });

    document.getElementById("yaml").value = lines.join("\\n") + "\\n";
    var warn = document.getElementById("missing");
    if (missing.length) {
      warn.textContent = "Unanswered required question(s): " + missing.join(", ") +
        ". You can still send this — Devin will ask for the rest.";
      warn.hidden = false;
    } else {
      warn.hidden = true;
    }
    document.getElementById("out").hidden = false;
    document.getElementById("copystate").textContent = "";
    document.getElementById("yaml").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  document.getElementById("build").addEventListener("click", build);

  function wbSaveTarget(text){
    // Opened from Argus (PC or Devin Cloud): a run's page goes back to that run, a dashboard block starts one.
    var l;try{l=(window.top||window).location;if(!/^https?:$/.test(l.protocol))return null}catch(err){return null}
    var m=l.pathname.match(/^\\/(?:view|run)\\/([a-f0-9]+)/);
    if(m)return {url:'/api/runs/'+m[1]+'/message',body:{text:text}};
    if(l.pathname==='/dashboard'&&/^#?\\s*SDLC-[A-Z-]+ v\\d/.test(text.trim()))return {url:'/api/blocks',body:{block:text}};
    return null;
  }
  function wbSave(text,state,done){
    var t=wbSaveTarget(text);if(!t)return false;
    fetch(t.url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(t.body)})
      .then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||r.statusText);return j})})
      .then(function(j){state.textContent=j.id&&t.url==='/api/blocks'?'Saved. The run page opens; it shows the change and waits for your approval.':'Saved. The run shows the change and waits for your approval.';
        if(j.id&&t.url==='/api/blocks'){window.open('/run/'+j.id,'_blank')}if(done)done()})
      .catch(function(e){state.textContent='Could not save ('+e.message+'). Copy it and paste it into the Devin chat.'});
    return true;
  }
  var saveBtn = document.getElementById("save");
  document.getElementById("build").addEventListener("click", function () {
    saveBtn.hidden = !wbSaveTarget(document.getElementById("yaml").value || "x");
    saveBtn.disabled = false;
  });
  saveBtn.addEventListener("click", function () {
    saveBtn.disabled = true;
    if (!wbSave(document.getElementById("yaml").value, document.getElementById("copystate"))) saveBtn.disabled = false;
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
    a.download = META.requirement_id + "-INTAKE-ANSWERS.yaml";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  document.getElementById("clear").addEventListener("click", function () {
    if (!confirm("Clear every answer on this form?")) return;
    QUESTIONS.forEach(function (q) {
      fields[q.id].input.value = "";
      fields[q.id].na.checked = false;
    });
    document.getElementById("out").hidden = true;
    refresh();
  });

  Object.keys(fields).forEach(function (id) {
    fields[id].input.addEventListener("input", refresh);
    fields[id].na.addEventListener("change", refresh);
  });

  restore();
  refresh();
})();
</script>
</body>
</html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("questions", help="path to {REQ_ID}-INTAKE-QUESTIONS.yaml")
    parser.add_argument("-o", "--output", help="output HTML path (default: beside the input)")
    args = parser.parse_args(argv)

    try:
        data = load_questions(args.questions)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        sys.stderr.write("gen_intake_form: %s\n" % exc)
        return 1

    output = args.output
    if not output:
        output = os.path.join(
            os.path.dirname(os.path.abspath(args.questions)),
            "%s-INTAKE-FORM.html" % data["requirement_id"],
        )

    with open(output, "w", encoding="utf-8") as fh:
        fh.write(render(data))
    sys.stdout.write("%s\n" % output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
