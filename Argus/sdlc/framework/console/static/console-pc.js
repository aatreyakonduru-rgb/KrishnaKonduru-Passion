/* Argus — front end, Test on my PC. Talks only to the local server's /api routes.
   The page loads console.js, console-run.js, console-pc.js, console-backlog.js and console-main.js in that
   order as plain scripts sharing one scope; console-main.js wires the page and starts it. */
"use strict";
// ------------------------------------------------------------ Test on my PC
function showPc(prefill) {
  stopPolling(); closeMenus(); state.run = null; state.story = null; renderStories();
  $("welcome").hidden = true; $("storyView").hidden = true; $("runView").hidden = true; $("backlogView").hidden = true; $("autoView").hidden = true; $("pcView").hidden = false; setSide("pc");
  document.querySelector(".c-main").classList.remove("is-run");
  navPush("#pc");
  if (prefill) {
    $("pcTicket").value = prefill.ticket || ""; $("pcBranch").value = prefill.branch || "";
    $("pcSession").value = prefill.session || ""; $("pcPack").value = "";
    if (prefill.ticket && (!prefill.branch || !prefill.session)) { lookupPc(prefill.ticket, true); }
  }
  pcTicketChoices();
  $("pcErr").hidden = true;
  loadPc();
  every("pc", 2500, loadPc, { hidden: 10000, when: pcOpen });
  state.chatHtml = null; if (state.chatWith) { chatSelect(state.chatWith); }
  every("chat", 4000, chatPoll, { hidden: 20000, when: pcOpen });
}
function pcOpen() { return !$("pcView").hidden; }
function loadPc() {
  return api("GET", "/api/pc").then(applyPc)
    .catch(function (e) { $("pcSetupErr").textContent = e.message; $("pcSetupErr").hidden = false; });
}
function applyPc(j) {
  {
    var was = state.pcStates || {}, back = null;
    state.pcStates = {};
    (j.tests || []).forEach(function (t) {
      state.pcStates[t.id] = t.state;
      if (t.state === "returned" && was[t.id] && was[t.id] !== "returned") { back = t; }
    });
    state.pc = j; renderPcSetup(); renderPcTests();
    if (!$("pcView").hidden) { renderChatTargets(); }
    // The PC test is done: the top bar offers Back with Cloud; the page you are on stays as it is.
    if (back) {
      checkUpdate(true);
      if (isTicket(back.ticket)) { askWrap(back.session, back.ticket); }
      state.pcBack = back;
      notify("pc-back-" + back.id, "Back with Cloud · " + back.ticket, "The PC test is done. Back with Cloud on the top bar opens the Cloud session.", function () { $("navPcNeed").click(); });
    }
    renderPcBadge(j.tests || []);
  }
}
function openCloudSession(session, ticket) {
  return api("POST", "/api/runs/open", { session: session, ticket: ticket })
    .then(function (run) { return loadRuns().then(function () { openRun(run.id); }); })
    .catch(function (e) {
      $("pcErr").textContent = "Could not open the Cloud session: " + e.message; $("pcErr").hidden = false;
      if ($("pcView").hidden && !e.offline) { alert($("pcErr").textContent); }
    });
}
var PC_MODE_NOTE = {
  local_hands: "Test on my PC runs from your Devin Cloud Argus through Local Hands: the session asks for your PC (a devin connect code), then runs the test pack there and you approve each step on the PC.",
  cloud_vm: "Test on my PC runs the test pack on the Devin Cloud VM; nothing runs on your PC.",
  devin_local: "", off: ""
};
// Argus config tab (workbench-settings.yaml): how Test on my PC runs for this person.
function applyPcMode(c) {
  var mode = (c.pc && c.pc.test_on_pc) || "devin_local";
  ["navPc", "runPcBtn"].forEach(function (id) { var b = $(id); if (b && (mode === "off" || mode === "cloud_vm")) { b.hidden = true; } });
}
function renderPcSetup() {
  var c = state.cfg || {}, pc = state.pc || {}, h = c.integrations || {}, dv = h.devin || {}, jr = h.jira || {};
  var mode = (c.pc && c.pc.test_on_pc) || "devin_local";
  if (c.transport === "bridge" || mode === "local_hands" || mode === "cloud_vm") {
    var down = dv.state === "failing";
    $("pcSetupBody").innerHTML = '<ol class="w-pc__check"><li class="' + (down ? "is-bad" : "is-ok") + '"><span class="w-pc__tick" aria-hidden="true">' + (down ? "\u2715" : "\u2713") + "</span><div><b>Devin</b> " +
      (down ? "isn't connected right now. " + (/bridge is not running/.test(dv.error || "") ? "The bar at the top says how to start it again." : errHtml(dv.error)) :
        c.transport === "bridge" ? "reached through your Devin Cloud session; no API key is needed." : "API key saved.") + "</div></li>" +
      (PC_MODE_NOTE[mode] ? '<li class="is-ok"><span class="w-pc__tick" aria-hidden="true">\u2713</span><div>' + esc(PC_MODE_NOTE[mode]) + "</div></li>" : "") + "</ol>";
    $("pcKeyForm").hidden = true;
    $("pcWhere").textContent = "";
    return;
  }
  var key = c.devin_configured ? "<b>Devin API key</b> saved" + (pc.key_store ? " in " + esc(pc.key_store) : "") + "." +
    (dv.state === "failing" ? ' <span class="c-err">Devin Cloud did not answer: ' + esc(dv.error) + "</span>" : dv.state === "not_checked" ? " Not checked yet." : "") :
    "<b>Devin API key</b> not added yet. Paste it once below" + (pc.key_store ? "; it is kept in " + esc(pc.key_store) + ", never in a file" : "") + ".";
  var cli = pc.devin_cli ? '<b>Devin Local (CLI)</b> installed. <button type="button" class="a-btn a-btn--outline" data-pclogin="1">Sign in to Devin Local</button> <span class="c-muted">only needed the first time; it opens your browser</span>' :
    '<b>Devin Local (CLI)</b> not found. Download and run the installer from <a href="https://docs.devin.ai/cli" target="_blank" rel="noopener">docs.devin.ai/cli</a> (most PCs need x86_64; ARM64 only for Windows on ARM), then press Check again.' +
    '<div class="w-pc__fix"><button type="button" class="a-btn a-btn--outline" data-copy="https://docs.devin.ai/cli">Copy the download link</button> <button type="button" class="a-btn a-btn--primary" data-pcrecheck="1">Check again</button></div>';
  function step(ok, html) { return '<li class="' + (ok ? "is-ok" : "is-bad") + '"><span class="w-pc__tick" aria-hidden="true">' + (ok ? "\u2713" : "\u2717") + "</span><div>" + html + "</div></li>"; }
  $("pcSetupBody").innerHTML = '<ol class="w-pc__check">' + step(c.devin_configured && dv.state !== "failing", key) + step(pc.devin_cli, cli) +
    step(jr.state !== "failing", "<b>Jira</b> read " + (c.jira_via === "cloud" ? "through Devin Cloud. No Jira key is needed on this PC." : "with the Jira key on this PC.") +
      (jr.state === "failing" ? ' <span class="c-err">Ticket lists are not loading: ' + esc(jr.error) + "</span>" : "")) + "</ol>";
  $("pcKeyForm").hidden = !!c.devin_configured;
  $("pcWhere").textContent = pc.work_root ? "Folder: " + pc.work_root + (pc.work_root.indexOf("\\") >= 0 ? "\\" : "/") + ($("pcTicket").value.trim().toUpperCase() || "<ticket>") : "";
}
$("pcCheck").addEventListener("click", function () {
  var btn = this, out = $("pcCheckOut");
  btn.disabled = true; out.hidden = false; out.innerHTML = '<li class="c-muted">Checking this PC…</li>';
  api("GET", "/api/doctor").then(function (j) {
    out.innerHTML = j.checks.map(function (c) {
      return '<li class="' + (c.ok ? "is-ok" : "is-bad") + '"><b>' + (c.ok ? "✓ " : "✗ ") + esc(c.name) + "</b> " + esc(c.detail) +
        (c.fix ? '<div class="w-doc__fix">Fix: ' + esc(c.fix) + "</div>" : "") + "</li>";
    }).join("");
  }).catch(function (e) { out.innerHTML = '<li class="is-bad">' + esc(e.message) + "</li>"; })
    .then(function () { btn.disabled = false; });
});
function histWhen(x) {
  var d = new Date(x);
  return isNaN(d) ? x || "" : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
function histJira(r, ticket, session) {
  var j = r.jira || {};
  if (j.url) { return '<a target="_blank" href="' + esc(j.url) + '">in ' + esc(j.ticket || "Jira") + "</a>"; }
  if (j.ticket) { return '<span class="c-muted">asked Cloud to post to ' + esc(j.ticket) + "</span>"; }
  if (!isTicket(ticket)) { return ""; }
  return '<button type="button" class="a-btn a-btn--outline w-hist__btn" data-histjira="' + esc(r.event_id) + '" data-session="' + esc(session) +
    '" data-ticket="' + esc(ticket) + '">Post to Jira</button>';
}
function histHtml(h, ticket) {
  if (!h) { return ""; }
  if (h.loading) { return '<div class="c-muted w-hist__note">Reading the evidence sent to the Cloud session…</div>'; }
  if (h.error) { return '<div class="c-err w-hist__note">Evidence history: ' + esc(h.error) + "</div>"; }
  if (!h.runs.length) { return '<div class="c-muted w-hist__note">No evidence has been sent to this Cloud session yet.</div>'; }
  return '<div class="w-hist__wrap"><table class="w-hist"><thead><tr><th>Tested</th><th>Passed</th><th>Failed</th><th>Not run</th><th>Story</th><th>Commit</th><th>By</th><th>PC</th><th></th><th>Jira</th></tr></thead><tbody>' +
    h.runs.map(function (r) {
      return '<tr class="' + (r.failed ? "is-bad" : r.not_run ? "is-warn" : "is-ok") + '"><td>' + esc(histWhen(r.tested_at || r.sent_at)) + "</td><td>" + r.passed +
        "</td><td>" + r.failed + "</td><td>" + r.not_run + "</td><td>" + esc(r.req + " " + r.story) + "</td><td><code>" + esc(r.commit.slice(0, 8)) +
        '</code></td><td title="' + esc(r.tested_by) + '">' + esc(r.tested_by.split("@")[0]) + "</td><td>" + esc(r.machine) + "</td><td>" +
        (r.zip ? '<a target="_blank" href="' + esc(r.zip) + '">zip</a>' : "") + "</td><td>" + histJira(r, ticket, h.session) + "</td></tr>";
    }).join("") + "</tbody></table></div>";
}
function loadHist(session, render) {
  state.pcHist = state.pcHist || {};
  if (!(state.pcHist[session] && state.pcHist[session].runs)) { state.pcHist[session] = { loading: true }; }
  render();
  return api("GET", "/api/pc/history?session=" + encodeURIComponent(session))
    .then(function (j) { state.pcHist[session] = j; })
    .catch(function (e) { state.pcHist[session] = { error: e.message }; })
    .then(render);
}
function renderLookupHist() {
  var s = state.pcHistLookup;
  $("pcHist").innerHTML = s ? '<div class="w-hist__head">Evidence sent to this ticket\'s Cloud session</div>' + histHtml((state.pcHist || {})[s], $("pcTicket").value.trim().toUpperCase()) : "";
}
document.addEventListener("click", function (ev) {
  var b = ev.target.closest("[data-pchist]");
  if (b) { loadHist(b.dataset.pchist, renderPcTests); }
  var j = ev.target.closest("[data-histjira]");
  if (!j) { return; }
  askConfirm("Ask the Cloud session to add one comment to " + j.dataset.ticket + " with this run's results?", { title: "Post to Jira", ok: "Post the comment" }).then(function (yes) {
  if (!yes) { return; }
  var s = j.dataset.session, both = function () { renderLookupHist(); renderPcTests(); };
  j.disabled = true;
  api("POST", "/api/pc/history/jira", { session: s, event_id: j.dataset.histjira, ticket: j.dataset.ticket }).then(function () {
    loadHist(s, both);
    [30000, 90000, 180000].forEach(function (ms) { setTimeout(function () { loadHist(s, both); }, ms); });
  }).catch(function (e) { j.disabled = false; if (!e.offline) { alert(e.message); } });
  });
});
// After Return to Cloud: Cloud checks nothing is left, then the tester picks the Jira move and what
// happens to the session. Nothing moves or closes without a click.
function wrapKey(s, k) { return s + "|" + k; }
function wrapPick(s, k, v) {
  var key = "sdlcWrap:" + wrapKey(s, k), cur = {};
  try { cur = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { cur = {}; }
  if (v) { Object.keys(v).forEach(function (x) { cur[x] = v[x]; }); localStorage.setItem(key, JSON.stringify(cur)); }
  return cur;
}
function loadWrap(s, k) {
  var key = wrapKey(s, k);
  state.pcWrap = state.pcWrap || {}; state.wrapTimers = state.wrapTimers || {};
  if (!state.pcWrap[key]) { state.pcWrap[key] = { loading: true }; }
  return api("GET", "/api/pc/wrapup?session=" + encodeURIComponent(s) + "&ticket=" + encodeURIComponent(k))
    .then(function (j) { state.pcWrap[key] = j; })
    .catch(function (e) { if (!e.offline || state.pcWrap[key].loading) { state.pcWrap[key] = { error: e.message }; } })
    .then(function () {
      var w = state.pcWrap[key];
      clearTimeout(state.wrapTimers[key]);
      if ((w.asked && !w.verdict) || (w.move && w.move.id && !w.move.status)) { state.wrapTimers[key] = setTimeout(function () { loadWrap(s, k); }, 15000); }
      renderPcTests();
    });
}
function askWrap(s, k) {
  wrapPick(s, k, { jira: "", session: "" });
  return api("POST", "/api/pc/wrapup", { session: s, ticket: k })
    .catch(function (e) { if (!e.offline && e.status !== 409) { alert(e.message); } })
    .then(function () { loadWrap(s, k); });
}
function wrapHtml(t) {
  if (!isTicket(t.ticket)) { return ""; }
  var w = (state.pcWrap || {})[wrapKey(t.session, t.ticket)], mine = wrapPick(t.session, t.ticket);
  var d = ' data-session="' + esc(t.session) + '" data-ticket="' + esc(t.ticket) + '"';
  var html = '<div class="w-wrap"><div class="w-wrap__head">Wrap-up for ' + esc(t.ticket) + "</div>";
  if (!w || w.loading) { return html + '<div class="c-muted">Reading the Cloud session\u2026</div></div>'; }
  if (w.error) { return html + '<div class="c-err">' + esc(w.error) + '</div><button type="button" class="a-btn a-btn--outline" data-wrapload="1"' + d + ">Try again</button></div>"; }
  if (!w.asked) {
    return html + '<div class="w-start__row"><span class="c-muted">Ask Devin Cloud whether anything is left to do on this ticket.</span>' +
      '<button type="button" class="a-btn a-btn--primary" data-wrapask="1"' + d + ">Check everything is done</button></div></div>";
  }
  if (!w.verdict) { return html + '<div class="c-muted">Devin Cloud is checking that everything is in place\u2026</div></div>'; }
  var again = '<button type="button" class="a-btn a-btn--outline" data-wrapask="1"' + d + ">Check again</button>", mv = w.move || {};
  if (w.verdict !== "ready") {
    html += '<div class="c-err">Not ready yet: ' + esc(w.reason || "Cloud did not say why") + "</div>" + again;
  } else {
    html += '<div class="w-wrap__ok">\u2713 Ready' + (w.reason ? ": " + esc(w.reason) : "") + '</div><div class="w-wrap__row"><b>Jira</b> ';
    if (mv.id) {
      html += mv.status ? "moved to <b>" + esc(mv.status) + "</b>" : '<span class="c-muted">asked Cloud to move it to ' + esc(mv.name || mv.id) + "\u2026</span>";
    } else if (mine.jira === "left") {
      html += '<span class="c-muted">left as it is</span> ' + again;
    } else {
      html += (w.transitions || []).map(function (x) {
        return '<button type="button" class="a-btn a-btn--outline" data-wrapmove="' + esc(x.id) + '" data-name="' + esc(x.name) + '"' + d + ">" + esc(x.name) + "</button>";
      }).join(" ") + ' <button type="button" class="a-btn a-btn--outline" data-wrapleave="1"' + d + ">Leave as is</button>" +
        ((w.transitions || []).length ? "" : ' <span class="c-muted">Cloud found no Jira transitions to offer.</span>');
    }
    html += "</div>";
  }
  if (w.verdict !== "ready" || mv.id || mine.jira === "left") {
    html += '<div class="w-wrap__row"><b>Session</b> ' + (mine.session
      ? '<span class="c-muted">' + esc({ "continue": "kept going", closed: "closed", archived: "archived (My sessions \u25be \u2192 Show archived)" }[mine.session] || mine.session) + "</span>"
      : '<button type="button" class="a-btn a-btn--outline" data-wrapsess="continue"' + d + ' title="Keep the session as it is; reply to it from Cloud or the run page">Continue</button> ' +
        '<button type="button" class="a-btn a-btn--outline" data-wrapsess="archive"' + d + ' title="Hide it from Argus lists; it stays in Devin and can be resumed">Archive</button> ' +
        '<button type="button" class="a-btn a-btn--outline" data-wrapsess="close"' + d + ' title="End the Cloud session for good; the run record and evidence stay here">End Cloud session</button>') + "</div>";
  }
  return html + "</div>";
}
function wrapMove(b) {
  var s = b.dataset.session, k = b.dataset.ticket;
  askConfirm("Ask Devin Cloud to move " + k + " to \"" + b.dataset.name + "\" in Jira?", { title: "Move the ticket", ok: "Move to " + b.dataset.name }).then(function (yes) {
  if (!yes) { return; }
  b.disabled = true;
  api("POST", "/api/pc/wrapup/jira", { session: s, ticket: k, transition: b.dataset.wrapmove })
    .catch(function (e) { if (!e.offline) { alert(e.message); } }).then(function () { loadWrap(s, k); });
  });
}
function wrapSession(b) {
  var s = b.dataset.session, k = b.dataset.ticket, v = b.dataset.wrapsess;
  if (v === "continue") { wrapPick(s, k, { session: "continue" }); renderPcTests(); return; }
  var msg = v === "close" ? "Close the Cloud session for " + k + "? It ends for good and can't be resumed. Its run record and evidence stay in Argus."
    : "Archive the Cloud session for " + k + "? It is hidden from Argus lists but stays in Devin, and you can resume it later.";
  askConfirm(msg, { title: v === "close" ? "Close the Cloud session?" : "Archive the Cloud session?", ok: v === "close" ? "Close session" : "Archive", danger: v === "close" }).then(function (yes) {
  if (!yes) { return; }
  b.disabled = true;
  (v === "close" ? api("POST", "/api/sessions/close", { session_ids: [s] }).then(function (j) { if (j.failed.length) { throw new Error(j.failed[0].error); } })
    : api("POST", "/api/sessions/archive", { session: s, archived: true }))
    .then(function () { wrapPick(s, k, { session: v === "close" ? "closed" : "archived" }); loadRuns(); renderPcTests(); })
    .catch(function (e) { b.disabled = false; if (!e.offline) { alert(e.message); } });
  });
}
var PC_STATE = { preparing: "Getting ready", testing: "PC has control: testing", returning: "Returning to Cloud", returned: "Back with Cloud", failed: "Stopped" };
function pcStrip(p) {
  if (!p) { return ""; }
  var at = p.phases.map(function (x) { return x.key; }).indexOf(p.phase);
  return '<ol class="w-pc__strip">' + p.phases.map(function (x, i) {
    var label = x.label, c = x.key === "checks" ? p.checks : x.key === "answers" ? p.answers : null;
    if (c && c.total) { label += " (" + c.done + " of " + c.total + ")"; }
    var cls = i < at || p.phase === "back" ? "is-done" : i === at ? (p.failed ? "is-failed" : "is-now") : "";
    return '<li class="' + cls + '">' + esc(label) + "</li>";
  }).join("") + '</ol><div class="w-pc__now' + (p.failed ? " c-err" : "") + '">' + esc(p.now) + "</div>";
}
function renderPcTests() {
  var tests = (state.pc && state.pc.tests) || [];
  var open = document.activeElement && document.activeElement.closest && document.activeElement.closest("[data-pcsay]");
  if (open) { return; }
  var html = tests.map(function (t) {
    var a = t.agent, html = '<div class="c-card" data-pctest="' + esc(t.id) + '">';
    html += '<div class="c-card__title">' + esc(t.ticket) + " · " + esc(t.branch) + ' <span class="a-badge">' + esc(PC_STATE[t.state] || t.state) + "</span>" +
      ' <a class="c-muted" target="_blank" href="' + esc((state.cfg.session_link || "") + "/sessions/" + t.session.replace("devin-", "")) + '">Cloud session</a>' +
      ' <button type="button" class="a-btn a-btn--outline" data-pchist="' + esc(t.session) + '">Evidence history</button></div>';
    html += pcStrip(t.progress);
    html += histHtml((state.pcHist || {})[t.session], t.ticket);
    html += '<ol class="w-pc__steps">' + t.steps.map(function (s) {
      return '<li class="is-' + esc(s.status) + '">' + (s.status === "done" ? "✓ " : s.status === "failed" ? "✗ " : "… ") + esc(s.name) + (s.detail ? ' <span class="c-muted">— ' + esc(s.detail.split("\n").slice(-3).join(" ")) + "</span>" : "") + "</li>";
    }).join("") + "</ol>";
    if (t.error) { html += '<div class="c-err">' + esc(t.error) + "</div>"; }
    if (a) {
      html += '<div class="w-pc__log">' + a.transcript.map(function (m) {
        if (m.role === "tool") { return '<div class="w-pc__tool">▸ ' + esc(m.text) + " · " + esc(m.status) + "</div>"; }
        if (m.role === "ask") { return ""; }
        var who = m.role === "devin" ? "Devin Local" : m.role === "workbench" ? "Argus" : m.role === "answer" ? "You answered" : m.role === "error" ? "Error" : "You";
        return '<div class="c-ev c-ev--msg' + (m.role === "devin" ? "" : " is-user") + '"><span class="c-ev__who">' + esc(who) + "</span>" + esc(m.text) + "</div>";
      }).join("") + "</div>";
      a.permissions.forEach(function (p) {
        html += '<div class="w-pc__ask"><b>Devin Local asks:</b> ' + esc(p.title) + "<div>" + p.options.map(function (o) {
          return '<button type="button" class="a-btn ' + (o.kind.indexOf("allow") === 0 ? "a-btn--primary" : "a-btn--outline") + '" data-pcperm="' + esc(t.id) + '" data-req="' + esc(p.id) + '" data-opt="' + esc(o.optionId) + '">' + esc(o.name) + "</button>";
        }).join("") + "</div></div>";
      });
      if (a.error && !a.alive) { html += '<div class="c-err">' + esc(a.error) + "</div>"; }
      if (t.state === "testing") {
        html += '<form class="w-pc__row" data-pcsay="' + esc(t.id) + '"><input class="a-input" placeholder="' + (a.busy ? "Devin Local is working…" : "Answer Devin Local (passed / failed / not run, and a note)") + '" />' +
          '<button class="a-btn a-btn--outline" type="submit">Send</button>' + (a.busy ? '<button type="button" class="a-btn a-btn--outline" data-pcstop="' + esc(t.id) + '">Stop</button>' : "") + "</form>";
      }
    }
    if (t.control === "pc" && (t.state === "testing" || t.state === "failed")) {
      html += '<div class="w-start__row"><span class="c-muted">' + (a && a.ready ? "Devin Local says the run is ready." : "Press when every check and acceptance item has a result.") + "</span>" +
        '<button type="button" class="a-btn a-btn--outline" data-pcrelease="' + esc(t.id) + '" title="Hand control back without sending evidence">Hand back only</button> ' +
        '<button type="button" class="a-btn a-btn--primary" data-pcreturn="' + esc(t.id) + '">Return to Cloud</button></div>';
    }
    if (t.state === "returned") {
      html += '<div class="w-start__row"><span class="c-muted">Cloud has control again.</span>' +
        '<button type="button" class="a-btn a-btn--primary" data-pccloud="' + esc(t.session) + '" data-ticket="' + esc(t.ticket) + '">Back to the Cloud session</button></div>';
      html += wrapHtml(t);
    }
    if (t.result) { html += '<pre class="c-muted" style="white-space:pre-wrap">' + esc(t.result) + "</pre>"; }
    return html + "</div>";
  }).join("");
  state.pcWrap = state.pcWrap || {};
  tests.forEach(function (t) {
    var key = wrapKey(t.session, t.ticket);
    if (t.state === "returned" && isTicket(t.ticket) && !state.pcWrap[key]) {
      state.pcWrap[key] = { loading: true }; setTimeout(function () { loadWrap(t.session, t.ticket); }, 0);
    }
  });
  if (html === state.pcTestsHtml) { return; }
  // The page refreshes every few seconds; keep each log where the reader left it.
  var main = document.querySelector(".c-main"), mainTop = main ? main.scrollTop : 0, logs = {};
  document.querySelectorAll("#pcTests [data-pctest]").forEach(function (card) {
    var log = card.querySelector(".w-pc__log");
    if (log) { logs[card.dataset.pctest] = { top: log.scrollTop, bottom: log.scrollHeight - log.scrollTop - log.clientHeight < 40 }; }
  });
  state.pcTestsHtml = html;
  $("pcTests").innerHTML = html;
  document.querySelectorAll("#pcTests [data-pctest]").forEach(function (card) {
    var log = card.querySelector(".w-pc__log"), was = logs[card.dataset.pctest];
    if (log) { log.scrollTop = !was || was.bottom ? log.scrollHeight : was.top; }
  });
  if (main) { main.scrollTop = mainTop; }
}
function pcPost(url, body) {
  return api("POST", url, body || {}).then(loadPc).catch(function (e) { if (!e.offline) { alert(e.message); } });
}
$("navPc").addEventListener("click", function () {
  var r = state.run && state.run.story ? state.run : null;
  showPc(r ? runPrefill(r) : null);
});
$("navPcNeed").addEventListener("click", function () {
  var back = state.pcBack;
  if (back) { state.pcBack = null; this.hidden = true; openCloudSession(back.session, back.ticket); } else { showPc(); }
});
function runPrefill(r) {
  return { ticket: (r.jira_story && r.jira_story.key) || (isTicket(r.story.key) ? r.story.key : ""), branch: r.pr ? r.pr.branch : "", session: r.session_url || "" };
}
$("runPcBtn").addEventListener("click", function () { showPc(runPrefill(state.run)); });
$("pcTicket").addEventListener("input", renderPcSetup);
$("pcTicket").addEventListener("change", function () { lookupPc($("pcTicket").value); });
$("pcBranch").addEventListener("change", function () { pcUseBranch($("pcBranch").value, true); });
function pcTicketChoices() {
  var seen = {}, opts = [];
  state.stories.concat(state.runs.map(function (r) { return r.story; })).forEach(function (s) {
    if (s && s.key && !s.custom && !seen[s.key]) { seen[s.key] = 1; opts.push('<option value="' + esc(s.key) + '">' + esc(s.summary || "") + "</option>"); }
  });
  $("pcTicketList").innerHTML = opts.join("");
}
function pcSessionText(found) {
  return (found.session_from === "test pack" ? "the test pack" : found.session_from || "");
}
function pcUseBranch(name, fromUser) {
  var f = state.pcFound; if (!f) { return; }
  var b = (f.branches || []).filter(function (x) { return x.branch === name; })[0];
  if (!b) { return; }
  var session = "", from = "";
  if (b.packs.length === 1 && b.packs[0].session) { session = b.packs[0].session; from = "the test pack"; }
  else if (fromUser && f.sessions.length === 1) { session = f.sessions[0].url; from = "Devin Cloud"; }
  $("pcSession").value = session;
  $("pcPack").value = "";
  $("pcFound").textContent = name + (b.packs.length ? " has test pack " + b.packs.map(function (p) { return p.name; }).join(", ") + "." : " has no test pack yet. Ask the Cloud session to run /eval.") +
    (session ? " Cloud session from " + from + "." : " No Cloud session found for it; paste the link.");
}
function lookupPc(ticket, keep) {
  ticket = (ticket || "").trim().toUpperCase();
  if (!ticket) { return Promise.resolve(); }
  if (state.pcAsked === ticket && state.pcLookup) { return state.pcLookup; }
  var asked = state.pcAsked = ticket;
  state.pcFound = null;
  if (!keep) { $("pcBranch").value = ""; $("pcSession").value = ""; $("pcPack").value = ""; }
  $("pcFound").textContent = "Looking up " + ticket + " on Bitbucket and in Devin Cloud…";
  state.pcHistLookup = null;
  renderLookupHist();
  return state.pcLookup = api("GET", "/api/pc/lookup?ticket=" + encodeURIComponent(ticket)).then(function (f) {
    if (state.pcAsked !== asked) { return; }
    state.pcFound = f;
    $("pcBranchList").innerHTML = f.branches.map(function (b) { return '<option value="' + esc(b.branch) + '">' + (b.packs.length ? "has a test pack" : "no test pack") + "</option>"; }).join("");
    var p = f.pick;
    if (p.branch && !$("pcBranch").value) { $("pcBranch").value = p.branch; }
    if (p.session && !$("pcSession").value) { $("pcSession").value = p.session; }
    var msg;
    if (!f.branches.length) { msg = "No branch on Bitbucket has " + ticket + " in its name yet."; }
    else if (!p.branch) { msg = f.branches.length + " branches have " + ticket + " in their name. Pick one under PR branch."; }
    else {
      var b = f.branches.filter(function (x) { return x.branch === p.branch; })[0];
      msg = "Found " + p.branch + (b.packs.length ? " with test pack " + b.packs.map(function (x) { return x.name; }).join(", ") : ", which has no test pack yet") + ".";
      msg += p.session ? " Cloud session from " + pcSessionText(p) + "." : " No Cloud session found; paste the link.";
    }
    $("pcFound").textContent = msg;
    state.pcHistLookup = p.session || null;
    if (p.session) { loadHist(p.session, renderLookupHist); } else { renderLookupHist(); }
  }).catch(function (e) {
    if (state.pcAsked === asked) { state.pcLookup = null; $("pcFound").textContent = "Could not look up " + ticket + ": " + e.message; }
  });
}
$("pcForm").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var btn = $("pcStart"); btn.disabled = true; $("pcErr").hidden = true;
  function fail(msg) { $("pcErr").textContent = msg; $("pcErr").hidden = false; }
  lookupPc($("pcTicket").value).then(function () {
    if (!$("pcBranch").value.trim()) { return fail("No PR branch yet. Pick one under PR branch (see the note under Ticket)."); }
    if (!$("pcSession").value.trim()) { return fail("No Cloud session yet. Paste the session link."); }
    return api("POST", "/api/pc", { ticket: $("pcTicket").value, branch: $("pcBranch").value.trim(), session: $("pcSession").value.trim(), pack: $("pcPack").value.trim() })
      .then(loadPc).catch(function (e) { fail(e.message); });
  }).then(function () { btn.disabled = false; });
});
$("pcKeyForm").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var v = $("pcKey").value.trim(); if (!v) { return; }
  $("pcSetupErr").hidden = true;
  api("POST", "/api/key", { key: v }).then(function () { $("pcKey").value = ""; state.cfg.devin_configured = true; $("welcomeWarn").innerHTML = ""; api("GET", "/api/health?fresh=1").then(showHealth, function () {}); renderPcSetup(); syncRuns(); })
    .catch(function (e) { $("pcSetupErr").textContent = e.message; $("pcSetupErr").hidden = false; });
});
document.addEventListener("submit", function (ev) {
  var f = ev.target.closest("[data-pcsay]"); if (!f) { return; }
  ev.preventDefault();
  var input = f.querySelector("input"), text = input.value.trim(); if (!text) { return; }
  input.value = ""; input.blur();
  pcPost("/api/pc/" + f.dataset.pcsay + "/prompt", { text: text });
});
document.addEventListener("click", function (ev) {
  var t = ev.target.closest("[data-pcperm]");
  if (t) { t.disabled = true; pcPost("/api/pc/" + t.dataset.pcperm + "/permission", { request: t.dataset.req, option: t.dataset.opt }); return; }
  t = ev.target.closest("[data-pcreturn]");
  if (t) { askConfirm("Send the evidence to the Cloud session and hand control back?", { title: "Return to Cloud", ok: "Send and return" }).then(function (yes) { if (yes) { t.disabled = true; pcPost("/api/pc/" + t.dataset.pcreturn + "/return"); } }); return; }
  t = ev.target.closest("[data-pcrelease]");
  if (t) { askConfirm("Hand control back to Cloud without sending any evidence?", { title: "Return without evidence", ok: "Return without evidence", danger: true }).then(function (yes) { if (yes) { t.disabled = true; pcPost("/api/pc/" + t.dataset.pcrelease + "/release"); } }); return; }
  t = ev.target.closest("[data-pcstop]"); if (t) { pcPost("/api/pc/" + t.dataset.pcstop + "/stop"); return; }
  t = ev.target.closest("[data-pclogin]"); if (t) { pcPost("/api/pc/login"); return; }
  t = ev.target.closest("[data-pccloud]"); if (t) { openCloudSession(t.dataset.pccloud, t.dataset.ticket); return; }
  t = ev.target.closest("[data-wrapask]"); if (t) { t.disabled = true; askWrap(t.dataset.session, t.dataset.ticket); return; }
  t = ev.target.closest("[data-wrapload]"); if (t) { loadWrap(t.dataset.session, t.dataset.ticket); return; }
  t = ev.target.closest("[data-wrapleave]"); if (t) { wrapPick(t.dataset.session, t.dataset.ticket, { jira: "left" }); renderPcTests(); return; }
  t = ev.target.closest("[data-wrapmove]"); if (t) { wrapMove(t); return; }
  t = ev.target.closest("[data-wrapsess]"); if (t) { wrapSession(t); return; }
  t = ev.target.closest("[data-storyrefresh]"); if (t) { ev.preventDefault(); loadStories(true); }
});
