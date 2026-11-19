/* Argus — front end, the Automation screen (automation engineers) and the Exit button.
   The page loads console.js, console-run.js, console-pc.js, console-backlog.js, console-auto.js and console-main.js
   in that order as plain scripts sharing one scope; console-main.js wires the page and starts it. */
"use strict";
// ------------------------------------------------------------ Automation screen
// Each step starts one skill in Devin Cloud; the skills are Argus side of the automation playbooks.
var AUTO_STEPS = [
  ["acme-auto-setup", "Set up", "Repo on the base branch, Python, the app on the Cloud machine, smoke test"],
  ["acme-auto-story", "Automate this story", "Reads the ticket or your description, fills in the automation template, stops at Gate 1, then writes, runs and reports"],
  ["acme-auto-run", "Run tests", "Runs the tag on the Cloud machine, one browser or several at once"],
  ["acme-auto-fix", "Triage failures", "Finds why scenarios failed: fixes the test, or drafts a defect when the app is wrong"]
];
function autoCfg() { return (state.cfg && state.cfg.automation) || {}; }
function isAutomation() {
  var r = state.me && state.me.role; if (!r) { return false; }
  return (r.hat_ids || []).indexOf("automation_engineer") >= 0 || (r.lenses || []).indexOf("automation") >= 0;
}
function renderAutoNav() { $("navAuto").hidden = !isAutomation() || !autoCfg().repo; }
function autoBranches() {
  var c = autoCfg(), out = (c.base_branches || []).slice();
  if (c.personal_branch && state.user) {
    var mine = c.personal_branch.replace("{user}", state.user);
    if (out.indexOf(mine) < 0) { out.push(mine); }
  }
  return out;
}
function showAuto(key) {
  stopPolling(); closeMenus(); state.run = null;
  ["welcome", "storyView", "runView", "pcView", "backlogView"].forEach(function (v) { $(v).hidden = true; });
  $("autoView").hidden = false; setSide("cloud");
  document.querySelector(".c-main").classList.remove("is-run");
  navPush("#auto");
  var keep = localStorage.getItem("sdlc-auto-base") || "";
  $("autoBase").innerHTML = autoBranches().map(function (b) {
    return '<option value="' + esc(b) + '"' + (b === keep ? " selected" : "") + ">" + esc(b) + "</option>";
  }).join("");
  $("autoRepo").textContent = autoCfg().repo || "";
  var max = autoCfg().max_processes || 4, h = "";
  for (var i = 1; i <= max; i++) { h += '<option value="' + i + '">' + i + "</option>"; }
  $("autoProc").innerHTML = h;
  if (!$("autoTags").value) { $("autoTags").value = autoCfg().smoke_tag || ""; }
  $("autoTicket").value = key || (state.story ? state.story.key : $("autoTicket").value);
  $("autoErr").hidden = true; autoAcShow();
  renderAutoSteps(); renderAutoRuns();
  every("auto", 5000, function () { if (!autoOpen()) { stopJob("auto"); return; } return loadRuns().then(function () { if (autoOpen()) { renderAutoSteps(); renderAutoRuns(); } }); }, { hidden: 30000 });
}
function autoOpen() { return !$("autoView").hidden; }
// The eight steps of automating a ticket, the skill behind each, and its [SDLC] step line id.
var AUTO_FLOW = [
  ["setup", "Setup", "acme-auto-setup"],
  ["scan", "Scan & plan", "acme-auto-story"],
  ["gate1", "Gate 1", "acme-auto-story"],
  ["write", "Write", "acme-auto-story"],
  ["run", "Run", "acme-auto-run"],
  ["triage", "Triage", "acme-auto-fix"],
  ["report", "Coverage & AC matrix", "acme-auto-story"],
  ["push", "Push & PR", "acme-auto-story"]
];
var AUTO_FLOW_WORDS = { pending: "not started", running: "working", waiting: "waiting for you", done: "done", blocked: "failed" };
function isAutoRun(r) { return /^acme-auto-/.test((r && r.story && r.story.action) || ""); }
function runEnded(r) { return !!r.closed_at || r.status === "finished" || r.status === "exit" || r.status === "error" || r.status === "expired"; }
// Where each step stands across the given runs, oldest first so the latest run wins. A session that has
// not posted a step line yet shows its skill's first step as working, so the stepper moves from the start.
function autoFlowState(runs) {
  var st = {}, runOf = {};
  runs.slice().sort(function (a, b) { return a.created_at - b.created_at; }).forEach(function (r) {
    var steps = r.steps || {}, skill = r.story.action, mine = AUTO_FLOW.filter(function (f) { return f[2] === skill; });
    if (!Object.keys(steps).length && mine.length) {
      steps = {}; steps[mine[0][0]] = runEnded(r) ? (r.status === "finished" ? "done" : "blocked") : "running";
    }
    Object.keys(steps).forEach(function (k) { st[k] = steps[k]; runOf[k] = r.id; });
    if ((r.pending_gate || r.pending_questions) && skill === "acme-auto-story" && !r.closed_at) {
      if (st.scan !== "done") { st.scan = "done"; runOf.scan = r.id; }
      st.gate1 = "waiting"; runOf.gate1 = r.id;
    }
    if (runEnded(r)) {
      AUTO_FLOW.forEach(function (f) { if (st[f[0]] === "running" && runOf[f[0]] === r.id) { st[f[0]] = r.status === "finished" ? "done" : "blocked"; } });
    }
  });
  fillStoryRun(runs, runOf);
  return { st: st, runOf: runOf };
}
// Steps inside the story session open that session even before it has reached them.
function fillStoryRun(runs, runOf) {
  var story = runs.filter(function (r) { return r.story.action === "acme-auto-story"; }).sort(function (a, b) { return b.created_at - a.created_at; })[0];
  ["gate1", "write", "report", "push"].forEach(function (k) { if (!runOf[k] && story) { runOf[k] = story.id; } });
}
function renderAutoFlow(runs, clickable) {
  var f = autoFlowState(runs);
  return AUTO_FLOW.map(function (s, i) {
    var st = f.st[s[0]] || "pending", attr = "";
    if (clickable) { attr = f.runOf[s[0]] ? ' data-run="' + esc(f.runOf[s[0]]) + '"' : ' data-autostep="' + s[2] + '"'; }
    return '<li class="c-stage w-flow c-stage--' + st + (s[0] === "gate1" || s[0] === "push" ? " w-flow--gate" : "") + '"' + attr +
      ' title="' + esc(s[2] === "acme-auto-story" ? "/acme-auto-story" : "/" + s[2]) + '"><span class="c-stage__n">' + (i + 1) + "</span><b>" + esc(s[1]) + "</b>" + esc(AUTO_FLOW_WORDS[st] || st) + "</li>";
  }).join("");
}
function renderAutoSteps() {
  $("autoFlow").innerHTML = renderAutoFlow(autoRuns(), true);
  $("autoSteps").innerHTML = AUTO_STEPS.map(function (s, i) {
    return '<div class="w-auto__step"><button type="button" class="a-btn ' + (i === 1 ? "a-btn--primary" : "a-btn--outline") + '" data-autostep="' + s[0] + '">' + esc(s[1]) + "</button>" +
      '<span class="c-muted">' + esc(s[2]) + "</span></div>";
  }).join("");
}
function autoRuns() {
  var key = $("autoTicket").value.trim().replace(/\s+/g, " ").replace(/"/g, "'").toUpperCase();
  return (state.runs || []).filter(function (r) {
    var a = (r.story && r.story.action) || "", input = (r.story && r.story.input) || "";
    return /^acme-auto-/.test(a) && !r.archived && (!key || input.toUpperCase().indexOf(key) >= 0 || a === "acme-auto-setup");
  });
}
function renderAutoRuns() {
  var runs = autoRuns().slice(0, 8);
  $("autoRuns").innerHTML = runs.length ? runs.map(function (r) {
    var step = AUTO_STEPS.filter(function (s) { return s[0] === r.story.action; })[0];
    return '<button type="button" class="c-item w-today__row" data-run="' + esc(r.id) + '"><b>' + esc(step ? step[1] : r.story.action) + "</b> " + statusBadge(r) +
      '<div class="c-item__sum">' + esc(r.story.input || "") + "</div></button>";
  }).join("") : '<div class="c-empty">No automation sessions for this ticket yet.</div>';
}
// The ticket box takes a Jira key, or a short description when there is no ticket.
function autoIsKey(v) { return /^[A-Z][A-Z0-9]+-\d+$/.test(v); }
function autoAcShow() { var v = $("autoTicket").value.trim(); $("autoAcWrap").hidden = !v || autoIsKey(v.toUpperCase()); }
function autoText(skill) {
  var what = $("autoTicket").value.trim().replace(/\s+/g, " "), key = autoIsKey(what.toUpperCase()) ? what.toUpperCase() : "";
  var base = $("autoBase").value, tags = $("autoTags").value.trim(), n = $("autoProc").value;
  if (skill === "acme-auto-story") {
    if (key) { return key + " base=" + base + " processes=" + n; }
    if (!what) { return ""; }
    var ac = $("autoAc").value.trim();
    return '"' + what.replace(/"/g, "'") + '" base=' + base + " processes=" + n + (ac ? "\nAcceptance criteria:\n" + ac : "");
  }
  if (skill === "acme-auto-run") { return tags ? tags + " processes=" + n + " base=" + base : ""; }
  if (skill === "acme-auto-fix") { return tags || key; }
  return "base=" + base;
}
function autoStart(skill, btn) {
  var step = AUTO_STEPS.filter(function (s) { return s[0] === skill; })[0], text = autoText(skill);
  $("autoErr").hidden = true;
  if (!text) {
    $("autoErr").textContent = skill === "acme-auto-run" ? "Type the tag to run first." :
      skill === "acme-auto-fix" ? "Type the tags or a ticket first." : "Pick or type a ticket, or describe what to automate, first.";
    $("autoErr").hidden = false; return;
  }
  if (!$("autoBase").value) { $("autoErr").textContent = "Pick a base branch first."; $("autoErr").hidden = false; return; }
  localStorage.setItem("sdlc-auto-base", $("autoBase").value);
  askConfirm("/" + skill + " " + text.split("\n")[0] + " — starts a Devin Cloud session. Nothing is committed until you say push.",
    { title: step[1] + "?", ok: "Start" }).then(function (yes) {
    if (!yes) { return; }
    btn.disabled = true;
    api("POST", "/api/actions", asMe({ skill: skill, text: text, dry_run: $("autoDry").checked }))
      .then(function (run) { return loadRuns().then(function () { renderAutoRuns(); startedNote(run, step[1] + " started"); }); })
      .catch(function (e) { if (!e.offline) { $("autoErr").textContent = e.message; $("autoErr").hidden = false; } })
      .then(function () { btn.disabled = false; });
  });
}
$("navAuto").addEventListener("click", function () { showAuto(); });
$("autoView").addEventListener("click", function (ev) {
  var r = ev.target.closest("[data-run]");
  if (r) { ev.stopPropagation(); stopJob("auto"); openRun(r.dataset.run); return; }
  var b = ev.target.closest("[data-autostep]"); if (b) { autoStart(b.dataset.autostep, b); }
});
$("autoTicket").addEventListener("change", function () { renderAutoSteps(); renderAutoRuns(); });
$("autoTicket").addEventListener("input", autoAcShow);

// ------------------------------------------------------------ Exit
// Ends the Cloud sessions the person ticks, then stops Argus on this PC. Sessions waiting on
// the person start unticked: an ended session can't be woken again.
function liveSessions() {
  var seen = {}, out = [];
  (state.runs || []).forEach(function (r) {
    if (!r.session_id || r.archived || r.closed_at || DONE_STATES.indexOf(r.status) >= 0 || seen[r.session_id]) { return; }
    seen[r.session_id] = true;
    var waiting = !!(r.pending_questions || r.pending_gate);
    out.push({ id: r.session_id, label: runKey(r) + " · " + ((r.story && r.story.summary) || ""), waiting: waiting,
      state: waiting ? "waiting on you" : asleep(r) ? "asleep" : (r.status || "") });
  });
  return out;
}
function openExit() {
  closeMenus();
  var live = liveSessions();
  $("exitList").innerHTML = live.length ? live.map(function (s) {
    return '<label class="w-exit__row"><input type="checkbox" data-exitsid="' + esc(s.id) + '"' + (s.waiting ? "" : " checked") + "> " +
      "<span>" + esc(s.label) + '</span> <span class="c-pill">' + esc(s.state) + "</span></label>";
  }).join("") : '<div class="c-muted">No Devin Cloud session started from Argus is still open.</div>';
  $("exitEnd").textContent = live.length ? "End ticked sessions and exit" : "Exit";
  $("exitIntro").hidden = !live.length; $("exitKeep").hidden = !live.length;
  $("exitErr").hidden = true; $("exitModal").hidden = false; $("exitCancel").focus();
}
function doExit(end) {
  var ids = end ? Array.prototype.map.call(document.querySelectorAll("#exitList [data-exitsid]:checked"), function (c) { return c.dataset.exitsid; }) : [];
  $("exitEnd").disabled = $("exitKeep").disabled = true;
  api("POST", "/api/exit", { session_ids: ids }).then(function (r) {
    if (r.failed && r.failed.length) {
      $("exitErr").textContent = r.failed.length + " session(s) could not be ended, so Argus stays open: " + r.failed.map(function (f) { return f.error; }).join("; ");
      $("exitErr").hidden = false; loadRuns(); return;
    }
    $("exitModal").hidden = true;
    document.body.innerHTML = '<div class="w-closed"><h1>Argus is closed.</h1><p>' +
      (r.closed.length ? r.closed.length + " Devin Cloud session" + (r.closed.length === 1 ? "" : "s") + " ended. " : "") +
      "You can close this tab. To start again, use the desktop icon.</p></div>";
  }).catch(function (e) { $("exitErr").textContent = e.message; $("exitErr").hidden = false; })
    .then(function () { if ($("exitEnd")) { $("exitEnd").disabled = $("exitKeep").disabled = false; } });
}
$("exitBtn").addEventListener("click", openExit);
$("exitForm").addEventListener("submit", function (ev) { ev.preventDefault(); doExit(true); });
$("exitKeep").addEventListener("click", function () { doExit(false); });
$("exitCancel").addEventListener("click", function () { $("exitModal").hidden = true; });
$("exitModal").addEventListener("keydown", function (ev) { if (ev.key === "Escape") { $("exitModal").hidden = true; } });
