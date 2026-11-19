/* Argus — front end, ticket and run screens, the right column, Trace, chat and notifications. Talks only to the local server's /api routes.
   The page loads console.js, console-run.js, console-pc.js, console-backlog.js and console-main.js in that
   order as plain scripts sharing one scope; console-main.js wires the page and starts it. */
"use strict";
// ------------------------------------------------------------ story view
// Cloud screens and the Devin Local (Test on my PC) screen share the purple, in a different tone.
function setSide(side) { document.documentElement.dataset.side = side; applyLayout(); }
function showStory(key) {
  var s = state.stories.filter(function (x) { return x.key === key; })[0];
  if (!s) { return; }
  state.story = s; state.run = null; stopPolling();
  renderStories(); clearRight();
  $("welcome").hidden = true; $("runView").hidden = true; $("pcView").hidden = true; $("backlogView").hidden = true; $("autoView").hidden = true; $("storyView").hidden = false; setSide("cloud");
  document.querySelector(".c-main").classList.remove("is-run");
  navPush("#story/" + s.key);
  $("sKey").textContent = s.key; $("sKey").href = s.url;
  $("sStatus").textContent = s.status; $("sPoints").textContent = s.points ? s.points + " pts" : ""; $("sPoints").hidden = !s.points;
  $("sSummary").textContent = s.summary;
  $("sMeta").innerHTML = "<span>Assignee: " + esc(s.assignee) + "</span><span>Reporter: " + esc(s.reporter) + "</span>" + (s.sprint ? "<span>" + esc(s.sprint) + "</span>" : "") + ((s.labels || []).length ? "<span>" + esc(s.labels.join(", ")) + "</span>" : "");
  $("startErr").hidden = true;
  $("sDesc").textContent = "Loading description…";
  api("GET", "/api/story/" + key).then(function (d) { if (state.story && state.story.key === key) { $("sDesc").textContent = d.description || "(no description on the ticket)"; } })
    .catch(function (e) { $("sDesc").textContent = jiraDown() ? "The description needs Jira, which isn't reachable right now." : "Could not load the description. " + plainErr(e.message); });
  renderStoryRuns();
}
// The ticket's runs, shown on the ticket itself: Argus stays on this screen while a run works in the background.
function renderStoryRuns() {
  if (!state.story || $("storyView").hidden) { return; }
  var key = state.story.key;
  var prior = state.runs.filter(function (r) { return r.story.key === key; });
  var waits = prior.filter(function (r) { return !r.closed && (r.pending_gate || r.pending_questions); })[0];
  var myRole = state.me && state.me.role;
  var hasLoe = !!myRole && (myRole.menus || []).some(function (m) { return m.id === "tools" && (m.items || []).some(function (it) { return it.skill === "loe"; }); });
  renderStoryRun(prior.filter(function (r) { return !r.closed_at; })[0]);
  var acts = '<div class="c-h">Everything for this ticket</div>' +
    (waits ? '<button type="button" class="a-btn a-btn--primary" data-run="' + waits.id + '">' + (waits.pending_gate ? "Approve" : "Answer questions") + "</button> " : "") +
    (prior.length && !waits ? '<button type="button" class="a-btn a-btn--outline" data-run="' + prior[0].id + '">Continue the last run</button> ' : "") +
    '<button type="button" class="a-btn a-btn--outline" data-ticketgroom="1" title="Groom, point, planning poker and hours on the Backlog screen">Groom, point or poker</button> ' +
    '<button type="button" class="a-btn a-btn--outline" data-openactions="1" title="Questions, approvals and handovers in the side panel">Hand over or answer</button> ' +
    (hasLoe ? '<button type="button" class="a-btn a-btn--outline" data-skill="loe">LOE estimate</button>' : "");
  if ($("sActs").dataset.html !== acts) { $("sActs").innerHTML = acts; $("sActs").dataset.html = acts; }
  var priorHtml = prior.length ? '<div class="c-h">Previous runs</div>' + prior.map(function (r) {
    return '<span class="c-story__run"><button class="a-btn a-btn--outline" data-run="' + r.id + '">' + esc(fmtDate(r.created_at)) + " · " + esc(LABELS[r.stage] || r.stage || "") + "</button>" +
      '<button class="a-btn a-btn--outline a-btn--icon" data-delrun="' + r.id + '" title="Delete this run" aria-label="Delete this run">\u00d7</button></span> ';
  }).join("") : "";
  var old = document.querySelector(".c-story__prior");
  if (old && old.dataset.html === priorHtml) { return; }
  if (old) { old.remove(); }
  if (priorHtml) {
    var div = document.createElement("div"); div.className = "c-story__prior";
    div.innerHTML = priorHtml; div.dataset.html = priorHtml;
    $("storyView").querySelector(".c-story").appendChild(div);
  }
}
// The open run on the ticket screen: where it is, Devin's latest message, and its questions to answer right here.
function renderStoryRun(r) {
  var box = $("sRun");
  box.hidden = !r;
  if (!r) { box.dataset.sig = ""; return; }
  var q = r.pending_questions, g = r.pending_gate, last = r.last_reply && r.last_reply.text ? r.last_reply.text : "";
  var sig = r.id + "|" + statusBadge(r) + "|" + (r.stage || "") + "|" + (q ? q.event_id : "") + "|" + (g ? g.id + (g.event_id || "") : "") + "|" + last;
  if (box.dataset.sig === sig) { return; }
  if (box.dataset.sig && box.dataset.sig.split("|")[3] === (q ? q.event_id : "") && q && typingIn(box)) { return; }
  box.dataset.sig = sig;
  var now = g ? "Waiting for your approval of <b>" + esc(g.id) + "</b>." :
    q ? "Devin has <b>" + q.items.length + " question" + (q.items.length === 1 ? "" : "s") + "</b> for you. Answer them below." :
    runFinished(r) ? "Devin has finished." :
    asleep(r) ? "The session is asleep. Your next answer or Wake starts it again." :
    r.status === "new" || r.status === "claimed" ? "Starting: Devin is cloning the repo and loading the framework." : "Devin is working in the background. Its questions and approvals show here.";
  box.innerHTML = '<div class="c-card__title">This ticket\'s run ' + statusBadge(r) + ' <span class="c-muted">' + esc(LABELS[r.stage] || r.stage || "") + " · " + (r.dry_run ? "dry run" : "real run") + " · started " + esc(fmtDate(r.created_at)) + "</span></div>" +
    progressHtml(r) + '<div class="w-srun__now">' + now + "</div>" +
    (q ? q.items.map(function (it) { return '<div class="c-q"><label><b>' + it.n + ".</b>" + esc(it.text) + '</label><textarea class="a-input" rows="2" data-sq="' + it.n + '"></textarea></div>'; }).join("")
      : last ? '<div class="w-srun__last">' + esc(last.replace(/^\s*\[SDLC\].*$/gm, "").trim()) + "</div>" : "") +
    '<div class="c-card__actions">' + (q ? '<button type="button" class="a-btn a-btn--primary" data-sqsend="' + esc(r.id) + '">Send answers</button>' : "") +
    (g ? '<button type="button" class="a-btn a-btn--primary" data-run="' + esc(r.id) + '">Review and approve</button>' : "") +
    '<button type="button" class="a-btn a-btn--outline" data-run="' + esc(r.id) + '">' + (g ? "Messages" : "Open the run") + "</button></div>" +
    '<div id="sRunErr" class="c-err" hidden></div>';
}
// Progress through the seven SDLC stages, as a bar: no step-by-step lines on the surface.
function progressHtml(r) {
  var st = r.stages || {}, done = STAGES.filter(function (s) { return st[s] === "done"; }).length;
  var ended = runFinished(r), cur = STAGES.indexOf(r.stage);
  var pct = ended ? 100 : Math.round((done + (cur >= 0 && st[r.stage] === "running" ? 0.5 : 0)) / STAGES.length * 100);
  var label = ended ? "Finished" : r.status === "new" || r.status === "claimed" ? "Starting" :
    cur >= 0 ? "Stage " + (cur + 1) + " of " + STAGES.length + " · " + esc(LABELS[r.stage] || r.stage) : "Working";
  return '<div class="w-prog__bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct + '"><span style="width:' + Math.max(pct, 3) + '%"></span></div>' +
    '<div class="w-prog__label">' + label + ' <span class="c-muted">' + done + " of " + STAGES.length + " stages done</span></div>";
}
function typingIn(el) { return Array.prototype.some.call(el.querySelectorAll("textarea"), function (t) { return !!t.value.trim(); }); }
document.addEventListener("click", function (ev) {
  var b = ev.target.closest && ev.target.closest("[data-sqsend]");
  if (!b) { return; }
  var answers = [];
  document.querySelectorAll("#sRun textarea[data-sq]").forEach(function (t) { answers.push({ n: parseInt(t.dataset.sq, 10), text: t.value }); });
  if (!answers.some(function (a) { return a.text.trim(); })) { return; }
  b.disabled = true; b.textContent = "Sending…";
  api("POST", "/api/runs/" + b.dataset.sqsend + "/answers", { answers: answers })
    .then(function () { $("sRun").dataset.sig = ""; return loadRuns(); })
    .catch(function (e) { b.disabled = false; b.textContent = "Send answers"; $("sRunErr").textContent = e.message; $("sRunErr").hidden = false; });
});
// Starting something never moves the screen: Argus stays where you are and the run works in its own session.
function startedNote(run, what, text) {
  var box = $("startedNote");
  box.innerHTML = "<b>" + esc(what) + "</b>" + '<button type="button" class="w-fold" data-startedx="1" aria-label="Dismiss">\u00d7</button>' +
    "<span>" + esc(text || "It works in its own Devin session in the background. You stay here; its questions and approvals come to you in Argus (Alerts and Approvals on the top bar" + (state.story ? ", and on this ticket" : "") + ").") + "</span>" +
    '<button type="button" class="a-btn a-btn--outline w-sync" data-run="' + esc(run.id) + '">See it</button>';
  box.hidden = false;
  if (typeof framedRender === "function") { framedRender(true); }
  clearTimeout(startedNote.timer); startedNote.timer = setTimeout(function () { box.hidden = true; }, 15000);
}
document.addEventListener("click", function (ev) {
  if (ev.target.closest && (ev.target.closest("[data-startedx]") || ev.target.closest("#startedNote [data-run]"))) { $("startedNote").hidden = true; }
});
function startLabel() { return $("dryRun").checked ? "Start SDLC (dry run)" : "Start SDLC (real run)"; }
$("dryRun").addEventListener("change", function () { $("startBtn").textContent = startLabel(); });
$("startBtn").addEventListener("click", function () {
  var btn = this; btn.disabled = true; btn.textContent = "Starting a Devin session…"; $("startErr").hidden = true;
  api("POST", "/api/runs", asMe({ key: state.story.key, dry_run: $("dryRun").checked, local_test: $("localTest").checked }))
    .then(function (run) { return loadRuns().then(function () { renderStoryRuns(); startedNote(run, "SDLC started on " + run.story.key); }); })
    .catch(function (e) { $("startErr").textContent = e.message; $("startErr").hidden = false; })
    .then(function () { btn.disabled = false; btn.textContent = startLabel(); });
});
function openNewReq(open) {
  if (open && document.querySelector(".c-left").classList.contains("is-tools")) { localStorage.setItem("sdlc-lefttab", "tickets"); applyLeftTab(); }
  if (open && document.querySelector(".w-cols").dataset.left === "rail") { toggleSide("left"); }
  $("customForm").hidden = !open; $("customToggle").setAttribute("aria-expanded", open ? "true" : "false");
  $("customToggle").textContent = open ? "\u2212 New requirement" : "+ New requirement";
  if (open) { $("customText").focus(); }
}
$("customForm").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var text = $("customText").value.trim(); if (!text) { $("customText").focus(); return; }
  var btn = $("customStart"); btn.disabled = true; btn.textContent = "Starting…"; $("customErr").hidden = true;
  api("POST", "/api/runs", asMe({ text: text, dry_run: $("customDry").checked, local_test: $("customLocal").checked }))
    .then(function (run) { $("customText").value = ""; openNewReq(false); return loadRuns().then(function () { startedNote(run, "SDLC started on your new requirement"); }); })
    .catch(function (e) { $("customErr").textContent = e.message; $("customErr").hidden = false; })
    .then(function () { btn.disabled = false; btn.textContent = "Start SDLC"; });
});

// ------------------------------------------------------------ run view
function openRun(id) {
  stopPolling(); closeMenus(); markRunSeen(id); $("rReused").hidden = true;
  state.run = { id: id }; state.story = null; renderStories(); navPush("#run/" + id);
  $("welcome").hidden = true; $("storyView").hidden = true; $("pcView").hidden = true; $("backlogView").hidden = true; $("autoView").hidden = true; $("runView").hidden = false; setSide("cloud");
  document.querySelector(".c-main").classList.add("is-run");
  state.stageTab = null; state.stageTabPinned = false;
  $("askItems").dataset.eid = ""; $("fwdForm").hidden = true;
  poll(true);
  state.timer = true; every("run", 4000, poll, { hidden: 30000 });
}
function stopPolling() { stopJob("run"); state.timer = null; }
function poll(refresh) {
  if (!state.run) { return; }
  var id = state.run.id;
  return api("GET", "/api/runs/" + id + (refresh === true ? "?refresh=1" : "")).then(function (run) {
    if (!state.run || state.run.id !== id) { return; }
    var had = state.run.messages ? state.run.messages.length : -1;
    state.run = run; renderRun(run, had !== run.messages.length);
    if (had !== run.messages.length) { loadRuns(); }
  }).catch(function (e) { $("runErr").textContent = e.message; $("runErr").hidden = false; });
}
$("refreshBtn").addEventListener("click", function () { poll(true); });
$("wakeBtn").addEventListener("click", function () {
  var btn = this; btn.disabled = true;
  api("POST", "/api/runs/" + state.run.id + "/wake", {}).then(function () { poll(true); })
    .catch(function (e) { $("runErr").textContent = e.message; $("runErr").hidden = false; }).then(function () { btn.disabled = false; });
});
$("archiveBtn").addEventListener("click", function () {
  var btn = this, on = !state.run.archived;
  closeMenus();
  (on ? askConfirm("It is hidden from Argus lists but stays in Devin, and you can resume it later (My sessions \u25be \u2192 Show archived).", { title: "Archive this session?", ok: "Archive" }) : Promise.resolve(true)).then(function (yes) {
  if (!yes) { return; }
  btn.disabled = true;
  api("POST", "/api/sessions/archive", { session: state.run.session_id, archived: on }).then(function () { poll(true); loadRuns(); })
    .catch(function (e) { if (!e.offline) { $("runErr").textContent = e.message; $("runErr").hidden = false; } }).then(function () { btn.disabled = false; });
  });
});
function deleteRun(id) {
  var r = state.runs.filter(function (x) { return x.id === id; })[0], key = r && r.story ? r.story.key : "";
  closeMenus();
  askConfirm("Its Devin session is ended if it is still running, and the run is removed from the story's Previous runs and from My sessions, on this PC and when other PCs reload from Devin. Its artefacts and trace here go with it. This can't be undone.", { title: "Delete this run" + (key ? " of " + key : "") + "?", ok: "Delete run", cancel: "Keep it", danger: true }).then(function (yes) {
  if (!yes) { return; }
  api("POST", "/api/runs/" + id + "/delete", {}).then(function () {
    return loadRuns().then(function () {
      var open = state.run && state.run.id === id, back = open ? key : (state.story && state.story.key);
      if (open) { stopPolling(); state.run = null; }
      if (back && state.stories.some(function (s) { return s.key === back; })) { showStory(back); return; }
      if (open) {
        $("runView").hidden = true; $("welcome").hidden = false;
        document.querySelector(".c-main").classList.remove("is-run");
      }
    });
  }).catch(function (e) { if (!e.offline) { alert(e.message); } });
  });
}
$("deleteBtn").addEventListener("click", function () { if (state.run) { deleteRun(state.run.id); } });
$("closeBtn").addEventListener("click", function () {
  var btn = this;
  closeMenus();
  askConfirm("It ends for good and can't be resumed. The run record, artefacts and evidence stay here.", { title: "Close this Cloud session?", ok: "Close session", cancel: "Keep it open", danger: true }).then(function (yes) {
  if (!yes) { return; }
  btn.disabled = true;
  api("POST", "/api/runs/" + state.run.id + "/close", {}).then(function () { poll(true); loadRuns(); })
    .catch(function (e) { if (!e.offline) { $("runErr").textContent = e.message; $("runErr").hidden = false; } }).then(function () { btn.disabled = false; });
  });
});

function renderRun(run, grew) {
  var body = $("runBody");
  var atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
  var isChat = run.kind === "chat", isAction = run.kind === "action" || isChat;
  $("rKey").textContent = run.story.key + (run.story.custom ? " (typed requirement)" : "");
  if (run.story.url) { $("rKey").href = run.story.url; } else { $("rKey").removeAttribute("href"); }
  var js = run.jira_story;
  $("rJira").hidden = !js;
  if (js) { $("rJira").textContent = "Jira " + js.key + " \u2192 " + (js.assignee_name || js.assignee || "unassigned"); $("rJira").href = js.url; }
  $("rMode").textContent = isChat ? "chat" : (isAction ? "menu action · " : "") + (run.dry_run ? "dry run" : "real run");
  $("rStatus").outerHTML = '<span id="rStatus">' + statusBadge(run) + "</span>";
  $("rSummary").textContent = run.story.summary;
  $("rLong").innerHTML = longNote(run); $("rLong").hidden = !$("rLong").innerHTML;
  $("rSession").href = run.session_url || "#";
  $("wakeBtn").hidden = !(asleep(run) || runFinished(run));
  $("archiveBtn").hidden = $("closeBtn").hidden = !run.session_id || !!run.closed_at;
  $("archiveBtn").textContent = run.archived ? "Unarchive" : "Archive";
  $("runErr").hidden = !run.error; $("runErr").textContent = run.error || "";

  var cur = isAction ? "all" : "intake";
  var stageOf = {};
  run.messages.forEach(function (m) {
    var re = /^\s*\[SDLC\]\s+stage\s+(.+?)(?:\s[—–:]\s|\s-{1,2}\s|:\s)\s*(.*)$/gim, mm, first = null;
    while ((mm = re.exec(m.text))) { var s = normStage(mm[1]); if (s && !/finish|done|complete|abandon/i.test(mm[2])) { cur = s; if (!first) { first = s; } } }
    m.stage = first || cur;
    if (m.event_id) { stageOf[m.event_id] = m.stage; }
  });
  if (isAction) { state.stageTab = "all"; }
  else if (!state.stageTabPinned || !state.stageTab) { state.stageTab = run.stage || cur; }
  var tab = state.stageTab;

  var isAuto = isAutoRun(run);
  $("runProg").hidden = isAction;
  if (!isAction) { $("runProg").innerHTML = progressHtml(run); }
  $("stages").hidden = isAction && !isAuto;
  if (isAuto) { $("stages").innerHTML = renderAutoFlow([run], false); }
  else if (!isAction) {
    var counts = {};
    run.messages.forEach(function (m) { counts[m.stage] = (counts[m.stage] || 0) + 1; });
    $("stages").innerHTML = STAGES.map(function (s, i) {
      var st = run.stages[s] || "pending";
      return '<li class="c-stage c-stage--' + st + (tab === s ? " is-active" : "") + '" data-stage="' + s + '" role="tab"><span class="c-stage__n">' + (i + 1) + "</span><b>" + LABELS[s] + "</b>" + esc(st) + (counts[s] ? ' <span class="c-count">' + counts[s] + "</span>" : "") + "</li>";
    }).join("") + '<li class="c-stage c-stage--all' + (tab === "all" ? " is-active" : "") + '" data-stage="all" role="tab"><b>All</b>everything</li>';
  }
  var inTab = function (m) { return tab === "all" || m.stage === tab; };

  // "Right now": the last thing that started and has not finished, in plain words.
  var last = { stage: null, step: null, agent: null, skill: null, playbook: null };
  run.events.forEach(function (e) {
    if (e.kind in last) { last[e.kind] = /finish|done|closed|approved|abandon/i.test(e.detail) ? null : e.name; }
  });
  var now = [];
  if (last.stage) { now.push("in <b>" + esc(LABELS[normStage(last.stage)] || last.stage) + "</b>"); }
  if (last.step) { var fs = AUTO_FLOW.filter(function (f) { return f[0] === last.step.toLowerCase(); })[0]; now.push("on step <b>" + esc(fs ? fs[1] : last.step) + "</b>"); }
  if (run.pending_gate) { now.push("waiting for your approval of <b>" + esc(run.pending_gate.id) + "</b> (right)"); }
  if (run.pending_questions) { now.push("<b>" + run.pending_questions.items.length + " questions</b> for you (below)"); }
  if (asleep(run) && !runFinished(run)) { now.push("the session is asleep — your next answer, approval or <b>Wake</b> starts it again"); }
  if (!now.length) { now.push(run.status === "new" || run.status === "claimed" ? "The session is starting: Devin is cloning the repo and loading the framework." : runFinished(run) ? "Devin has finished." : "Devin is working."); }
  $("now").innerHTML = "<span class=\"c-now__label\">Right now</span> " + now.join(" · ");

  var feed = [];
  run.messages.filter(inTab).forEach(function (m) {
    var body2 = [];
    m.text.split("\n").forEach(function (ln) {
      if (!TRACE_LINE.test(ln)) { body2.push(ln); }
    });
    var text = body2.join("\n").replace(/```[\s\S]*?```/g, "[document — see the right-hand column]").trim();
    if (text) { feed.push({ t: "msg", at: m.at, source: m.source, text: text }); }
  });
  // Messages only: every [SDLC] line is in Trace.
  $("feed").innerHTML = feed.map(function (f) {
    return '<div class="c-ev c-ev--msg' + (f.source !== "devin" ? " is-user" : "") + '"><span class="c-ev__who">' + (f.source === "devin" ? "Devin" : "You") + " · " + fmtTime(f.at) + "</span>" + esc(f.text) + "</div>";
  }).join("") || '<div class="c-empty">' + (tab === "all" || (run.stages[tab] || "pending") !== "pending" ? "Waiting for Devin's first update…" : "The " + esc(LABELS[tab] || tab) + " stage has not started yet.") + "</div>";

  var q = run.pending_questions;
  $("askCard").hidden = !q;
  if (q) {
    var round = run.events.filter(function (e) { return e.kind === "question round"; }).slice(-1)[0];
    $("askRound").textContent = round ? "round " + round.name : "";
    if ($("askItems").dataset.eid !== q.event_id) {
      $("askItems").dataset.eid = q.event_id;
      $("askItems").innerHTML = q.items.map(function (it) {
        return '<div class="c-q"><label><b>' + it.n + ".</b>" + esc(it.text) + '</label><textarea class="a-input" rows="2" data-q="' + it.n + '"></textarea></div>';
      }).join("");
    }
  }
  renderSign(run);
  renderRight(run, tab);
  if (grew && atBottom && !typingIn($("askCard"))) { body.scrollTop = body.scrollHeight; }
}
$("feedTrace").addEventListener("click", function () { setRightTab("trace"); });
function setStageTab(s) { state.stageTab = s; state.stageTabPinned = true; if (state.run && state.run.messages) { renderRun(state.run, true); $("runBody").scrollTop = 0; } }

// ------------------------------------------------------------ sign panel (right, top)
function renderSign(run) {
  var g = run.pending_gate;
  var was = $("gateCard").hidden; $("gateCard").hidden = !g; $("signEmpty").hidden = !!g; if (was === !!g) { applyLayout(); }
  if (g) {
    var d = gateDef(g.id) || {};
    var role = state.me && state.me.role;
    var mayWear = role && d.required_role && (role.gate_roles.indexOf(d.required_role) >= 0);
    $("gateId").textContent = g.id; $("gateName").textContent = d.name || "";
    $("gateMeta").innerHTML = (d.required_role ? "<span>Signer: <b>" + esc(d.required_role.replace(/_/g, " ")) + "</b></span>" : "") +
      (d.timeout_hours ? "<span>Reply within " + esc(d.timeout_hours) + " h</span>" : "") +
      (d.required_role && role ? (mayWear ? '<span class="w-ok">your role signs this</span>' : '<span class="w-warn">' + esc(role.label) + " does not sign this gate — forward it, or sign in dev mode</span>") : "");
    if ($("gateCriteria").dataset.gid !== g.id + (g.event_id || "")) {
      $("gateCriteria").dataset.gid = g.id + (g.event_id || "");
      $("gateCriteria").innerHTML = (d.approval_criteria || []).length ? '<div class="c-h">Check before you sign</div>' + d.approval_criteria.map(function (c) { return '<label class="c-switch"><input type="checkbox" /> ' + esc(c) + "</label>"; }).join("") : "";
    }
    if ($("gateItems").dataset.gid !== g.id + (g.event_id || "")) {
      $("gateItems").dataset.gid = g.id + (g.event_id || "");
      $("gateItems").innerHTML = '<div class="c-h">Decide each item</div>' + (g.items || [{ n: 1, text: "Approve this gate as presented" }]).map(function (it) {
        return '<div class="c-q w-gitem" data-n="' + it.n + '"><label><b>' + it.n + ".</b> " + esc(it.text) + "</label>" +
          '<span class="w-gitem__pick"><label class="c-switch"><input type="radio" name="gi-' + it.n + '" value="approve" /> Approve</label>' +
          '<label class="c-switch"><input type="radio" name="gi-' + it.n + '" value="reject" /> Reject</label></span>' +
          '<input class="a-input w-gitem__note" placeholder="Reason (needed to reject) or a note" /></div>';
      }).join("");
      gateItemsChanged();
    }
    $("gateText").textContent = g.text.replace(/^\s*\[SDLC\].*$/gm, "").trim();
    var intakeGate = /^SDLC_01\b/.test(g.id) && !run.jira_story;
    $("jiraOpt").hidden = !intakeGate;
    $("jiraDone").hidden = !run.jira_story;
    if (run.jira_story) { $("jiraDone").textContent = "Jira story " + run.jira_story.key + " already created for this run."; }
  }
  stRender(run, g);
  $("fwdList").innerHTML = (run.forwarded || []).map(function (f) {
    return '<div class="w-fwdrow"><b>' + esc(f.gate) + "</b> forwarded to " + esc(personName(f.person)) + " · " + fmtDate(f.at) + '<div class="c-muted">' + esc(f.note) + "</div></div>";
  }).join("");
}
// ------------------------------------------------------------ sub-tasks at the last gate before coding
var SUBTASK_GATE = /^(SDLC_04|HOTFIX_PLAN_CODE)/;
function runStoryKey(run) {
  var s = run.story || {}, k = s.jira_key || (run.jira_story || {}).key || (s.custom ? "" : s.key);
  return /^[A-Z][A-Z0-9]+-\d+$/.test(k || "") ? k : "";
}
function stRowHtml(r) {
  var key = r.key || "";
  return '<div class="w-subs__row"' + (key ? ' data-key="' + esc(key) + '"' : "") + '>' +
    (key ? '<label class="c-switch w-subs__upd"><input type="checkbox" data-st="update"' + (r.update ? " checked" : "") + '> <span>Update <b>' + esc(key) + "</b> in Jira</span></label>" +
      (r.change ? '<div class="c-muted w-subs__chg">Devin suggests: ' + esc(r.change) + "</div>" : "") : "") +
    '<div class="w-subs__line"><input class="a-input" data-st="summary" maxlength="250" placeholder="DEV- what this part of the work is" value="' + esc(r.summary || "") + '">' +
    '<input class="a-input" data-st="hours" inputmode="decimal" placeholder="hours" title="Original estimate in hours" value="' + (parseFloat(r.hours) > 0 ? esc(r.hours) : "") + '">' +
    (key ? "" : '<button type="button" class="a-btn a-btn--outline" data-stdel="1" title="Remove this sub-task">×</button>') + "</div>" +
    '<textarea class="a-input w-subs__desc" data-st="description" rows="2" maxlength="4000" placeholder="Technical detail: files and functions, the change, tests, AC numbers">' + esc(r.description || "") + "</textarea></div>";
}
function stTotal() {
  var t = 0;
  document.querySelectorAll("#stRows .w-subs__row").forEach(function (r) { if (stSends(r)) { t += parseFloat(r.querySelector("[data-st=hours]").value) || 0; } });
  $("stTotal").textContent = "Total " + (Math.round(t * 100) / 100) + "h";
}
function stSends(r) { var u = r.querySelector("[data-st=update]"); return u ? u.checked : true; }
function stRows() {
  var rows = [];
  document.querySelectorAll("#stRows .w-subs__row").forEach(function (r) {
    var v = function (n) { return r.querySelector("[data-st=" + n + "]").value.trim(); };
    if (!stSends(r) || !(v("summary") || v("hours"))) { return; }
    rows.push({ key: r.dataset.key || "", summary: v("summary"), hours: v("hours"), description: v("description") });
  });
  return rows;
}
function stRender(run, g) {
  var key = g && SUBTASK_GATE.test(g.id) ? runStoryKey(run) : "", box = $("stOpt");
  box.hidden = !key;
  if (!key) { return; }
  var done = run.subtasks && run.subtasks.key === key ? run.subtasks : null;
  $("stDone").hidden = !done;
  if (done) { $("stDone").textContent = (done.keys && done.keys.length ? "Created: " + done.keys.join(", ") : done.via === "dry run" ? "Dry run: sent to Devin as a list, not written to Jira" : "Sent to Devin to write to Jira") + " · " + done.rows.length + " sub-tasks · " + fmtDate(done.at); }
  var plan = run.subtask_plan || [], gid = g.id + (g.event_id || "") + ":" + plan.length;
  if (box.dataset.gid === gid) { return; }
  box.dataset.gid = gid;
  $("stKey").textContent = key; $("stCreate").checked = false; box.setAttribute("data-off", "1");
  $("stHint").textContent = (plan.length ? "Devin's suggestions from the routing map. " : "Devin has not posted its suggested sub-tasks yet, so these are the standard set. ") +
    "Each sub-task needs an original estimate in hours. Nothing is written to Jira until you approve and confirm." + (run.dry_run ? " This is a dry run: Devin lists them but does not write them." : "");
  $("stHave").textContent = ""; $("stRows").innerHTML = ""; $("stErr").hidden = true; stTotal();
  var s = run.story || {};
  Promise.all([
    api("GET", "/api/backlog/subtasks?key=" + encodeURIComponent(key)).then(function (d) { return (d.tickets || []).filter(function (t) { return t.key !== key; }); }, function () { return []; }),
    plan.length ? Promise.resolve([]) : api("POST", "/api/backlog/subtask-plan", { draft: { summary: s.summary || "", points: s.points || "", subtasks: [] } }).then(function (d) { return d.subtasks || []; }, function () { return []; })
  ]).then(function (res) {
    if (box.dataset.gid !== gid) { return; }
    var have = res[0], inPlan = {}, rows = [];
    plan.forEach(function (r) { if (r.key) { inPlan[r.key] = 1; } });
    have.forEach(function (t) { if (!inPlan[t.key]) { rows.push({ key: t.key, summary: t.summary }); } });
    if (plan.length) {
      rows = plan.filter(function (r) { return r.key; }).map(function (r) { return { key: r.key, summary: r.summary, hours: r.hours, description: r.description, change: r.change, update: !!r.change }; })
        .concat(rows, plan.filter(function (r) { return !r.key; }));
    } else {
      var names = have.map(function (t) { return (t.summary || "").trim().toLowerCase(); });
      rows = rows.concat(res[1].filter(function (r) { return names.indexOf(r.summary.trim().toLowerCase()) < 0; }));
    }
    $("stHave").textContent = have.length ? have.length + " sub-task" + (have.length > 1 ? "s" : "") + " already on the story: tick Update on any you want changed in Jira." : "No sub-tasks on the story yet.";
    $("stRows").innerHTML = (rows.length ? rows : [{}]).map(stRowHtml).join(""); stTotal();
  });
}
$("stCreate").addEventListener("change", function () { if (this.checked) { $("stOpt").removeAttribute("data-off"); } else { $("stOpt").setAttribute("data-off", "1"); } });
$("stAdd").addEventListener("click", function () { $("stRows").insertAdjacentHTML("beforeend", stRowHtml({})); stTotal(); var i = $("stRows").querySelectorAll("[data-st=summary]"); i[i.length - 1].focus(); });
$("stRows").addEventListener("input", stTotal);
$("stRows").addEventListener("change", stTotal);
$("stRows").addEventListener("click", function (ev) { var b = ev.target.closest("[data-stdel]"); if (b) { b.closest(".w-subs__row").remove(); stTotal(); } });
// The sub-tasks to send with an approval, after the developer says Jira may be updated; null = cancel the approval.
function stConfirm(decision) {
  if ($("stOpt").hidden || !$("stCreate").checked || decision === "reject") { return Promise.resolve([]); }
  $("stErr").hidden = true;
  var rows = stRows(), seen = {}, err = "";
  rows.forEach(function (r) {
    var h = parseFloat(r.hours), name = r.key || r.summary || "row without a title", t = r.summary.toLowerCase();
    if (err) { return; }
    if (!r.summary || !(h > 0)) { err = "Give every sub-task a title and an original estimate in hours (" + name + ")."; }
    else if (h > 80) { err = "The estimate for " + name + " must be 80 hours or less."; }
    else if (seen[t]) { err = "\"" + r.summary + "\" is listed twice."; }
    seen[t] = 1;
  });
  if (!rows.length) { err = "Add at least one sub-task, or untick Add sub-tasks."; }
  if (err) { $("stErr").textContent = err; $("stErr").hidden = false; return Promise.resolve(null); }
  var total = rows.reduce(function (t, r) { return t + parseFloat(r.hours); }, 0), dry = state.run && state.run.dry_run;
  var add = rows.filter(function (r) { return !r.key; }), upd = rows.filter(function (r) { return r.key; });
  var line = function (r) { return "• " + (r.key ? r.key + " ← " : "") + r.summary + " — " + r.hours + "h" + (r.description ? "" : " (no description)"); };
  return askConfirm((dry ? "Dry run: Devin lists these for " : "Write these to ") + $("stKey").textContent + (dry ? "" : " in Jira") + ", " + (Math.round(total * 100) / 100) + "h original estimate in total?" +
    (add.length ? "\n\nCreate " + add.length + ":\n" + add.map(line).join("\n") : "") + (upd.length ? "\n\nUpdate " + upd.length + ":\n" + upd.map(line).join("\n") : ""),
    { title: dry ? "Send the sub-task list?" : "Update Jira?", ok: dry ? "Yes, send the list" : "Yes, update Jira", cancel: "Not yet" })
    .then(function (ok) { return ok ? rows : null; });
}
$("fwdToggle").addEventListener("click", function () { $("fwdForm").hidden = !$("fwdForm").hidden; if (!$("fwdForm").hidden) { $("fwdNote").focus(); } });
$("fwdForm").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var person = $("fwdPerson").value, note = $("fwdNote").value.trim();
  if (!person) { $("fwdPerson").focus(); return; }
  if (!note) { $("fwdNote").focus(); return; }
  api("POST", "/api/runs/" + state.run.id + "/forward", { person: person, note: note, items: $("fwdItems").value })
    .then(function () { $("fwdNote").value = ""; $("fwdItems").value = ""; $("fwdForm").hidden = true; poll(true); loadRuns(); })
    .catch(function (e) { $("runErr").textContent = e.message; $("runErr").hidden = false; });
});
$("askSend").addEventListener("click", function () {
  var answers = [];
  document.querySelectorAll("#askItems textarea").forEach(function (t) { answers.push({ n: parseInt(t.dataset.q, 10), text: t.value }); });
  if (!answers.some(function (a) { return a.text.trim(); })) { return; }
  var btn = this; btn.disabled = true;
  api("POST", "/api/runs/" + state.run.id + "/answers", { answers: answers }).then(function () { $("askItems").dataset.eid = ""; poll(true); })
    .catch(function (e) { $("runErr").textContent = e.message; $("runErr").hidden = false; }).then(function () { btn.disabled = false; });
});
// Every decision item gets Approve or Reject; one reply goes once all are decided, and any rejected item rejects the gate.
function gateDecisions() {
  return Array.prototype.map.call(document.querySelectorAll("#gateItems .w-gitem"), function (row) {
    var pick = row.querySelector("input[type=radio]:checked");
    return { n: parseInt(row.dataset.n, 10), decision: pick ? pick.value : "", note: row.querySelector(".w-gitem__note").value.trim() };
  });
}
function gateItemsChanged() {
  var d = gateDecisions();
  var left = d.filter(function (x) { return !x.decision || (x.decision === "reject" && !x.note); }).length;
  var bad = d.filter(function (x) { return x.decision === "reject"; }).length;
  $("gateSend").disabled = !!left;
  $("gateSend").textContent = left ? "Decide every item (" + left + " left)" : bad ? "Send back as rejected (" + bad + " of " + d.length + " rejected)" : "Approve and continue";
}
$("gateItems").addEventListener("input", gateItemsChanged);
$("gateItems").addEventListener("change", gateItemsChanged);
$("gateSend").addEventListener("click", function () {
  var items = gateDecisions(), reject = items.some(function (x) { return x.decision === "reject"; });
  if (items.some(function (x) { return !x.decision || (x.decision === "reject" && !x.note); })) { return; }
  var decision = reject ? "reject" : "approve";
  var createJira = !$("jiraOpt").hidden && $("jiraCreate").checked && !reject;
  var assignee = $("jiraAssignee").value;
  if (createJira && !assignee) { $("runErr").textContent = "Pick who the Jira story should be assigned to."; $("runErr").hidden = false; return; }
  var btn = this;
  stConfirm(decision).then(function (subs) {
    if (subs === null) { return; }
    btn.disabled = true;
    return api("POST", "/api/runs/" + state.run.id + "/gate", { decision: "items", items: items, create_jira: createJira, assignee: assignee,
      subtasks: subs.length ? subs : undefined, user: state.user })
      .then(function (res) {
        $("gateItems").dataset.gid = ""; $("jiraCreate").checked = false; $("stCreate").checked = false; $("stOpt").setAttribute("data-off", "1");
        if (res && res.closed) { return loadRuns().then(goHome); }
        poll(true); loadRuns();
      })
      .catch(function (e) { var box = subs.length ? $("stErr") : $("runErr"); box.textContent = e.message; box.hidden = false; })
      .then(function () { gateItemsChanged(); });
  });
});
$("composeToggle").addEventListener("click", function () {
  var f = $("compose"); f.hidden = !f.hidden;
  this.textContent = f.hidden ? "Message the session…" : "Hide message box";
  if (!f.hidden) { $("composeText").focus(); }
});
$("compose").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var text = $("composeText").value.trim(); if (!text) { return; }
  api("POST", "/api/runs/" + state.run.id + "/message", { text: text }).then(function () { $("composeText").value = ""; poll(true); })
    .catch(function (e) { $("runErr").textContent = e.message; $("runErr").hidden = false; });
});

// ------------------------------------------------------------ right column: documents, diffs, PR
function setRightTab(t) {
  state.rightTab = t;
  document.querySelectorAll(".c-tab[data-right]").forEach(function (b) { b.classList.toggle("is-active", b.dataset.right === t); });
  document.querySelectorAll("#paneArt, #paneDiff, #panePr, #paneSkills, #paneTrace, #paneChat").forEach(function (p) { p.hidden = p.dataset.pane !== t; });
}
function clearRight() {
  $("gateCard").hidden = true; $("signEmpty").hidden = false; $("fwdList").innerHTML = "";
  $("nArt").textContent = "0"; $("nDiff").textContent = "0";
  $("paneArt").innerHTML = '<div class="c-empty">Open a run to see its documents.</div>';
  ["paneDiff", "panePr", "paneSkills", "paneTrace", "paneChat"].forEach(function (id) { $(id).innerHTML = ""; });
  if (!$("traceFloat").hidden) { $("traceFloatBody").innerHTML = '<div class="c-empty">Open a run to see what it loaded and decided.</div>'; }
}
function diffHtml(body) {
  return body.split("\n").map(function (l) {
    var c = /^\+\+\+|^---|^diff |^index /.test(l) ? "d-meta" : l[0] === "+" ? "d-add" : l[0] === "-" ? "d-del" : /^@@/.test(l) ? "d-hunk" : "";
    return c ? '<span class="' + c + '">' + esc(l) + "</span>" : esc(l) + "\n";
  }).join("");
}
function renderRight(run, tab) {
  var stageAt = {};
  run.messages.forEach(function (m) { if (m.at) { stageAt[m.at] = m.stage; } });
  var inTab = function (x) { return tab === "all" || !stageAt[x.at] || stageAt[x.at] === tab; };
  var arts = run.artefacts.filter(inTab), diffs = run.diffs.filter(inTab);
  $("nArt").textContent = arts.length + (arts.length !== run.artefacts.length ? "/" + run.artefacts.length : "");
  $("nDiff").textContent = diffs.length + (diffs.length !== run.diffs.length ? "/" + run.diffs.length : "");
  var open = {};
  document.querySelectorAll("#paneArt details[open]").forEach(function (d) { open[d.dataset.name] = true; });
  $("paneArt").innerHTML = (run.artefacts.length || run.diffs.length ? '<div class="w-bundle"><a class="a-btn a-btn--outline" href="/api/runs/' + run.id + '/bundle.zip">Download everything (.zip)</a></div>' : "") +
    (arts.slice().reverse().map(function (a, i) {
      var idx = run.artefacts.indexOf(a);
      return '<details class="c-art" data-name="' + esc(a.name) + '"' + (open[a.name] || (i === 0 && !Object.keys(open).length) ? " open" : "") + "><summary><span>" + esc(a.name) + "</span><small>" + fmtTime(a.at) +
        (/\.(md|markdown|html?)$/i.test(a.name || "") && a.body ? ' <a class="a-btn a-btn--outline w-dl" target="_blank" href="/view/' + run.id + "/" + idx + '">Open</a>' : "") +
        ' <button type="button" class="a-btn a-btn--outline w-dl" data-dlart="' + idx + '">Download</button></small></summary><pre>' + esc(a.body || a.detail) + "</pre></details>";
    }).join("") || '<div class="c-empty">Documents (spec, gap analysis, routing map, test matrix, approvals) appear here as the run produces them.</div>');
  $("paneDiff").innerHTML = diffs.map(function (d, i) {
    var idx = run.diffs.indexOf(d);
    return '<details class="c-art"' + (i === 0 ? " open" : "") + "><summary><span>" + esc(d.path) + "</span><small>" + esc(d.why) + ' <button type="button" class="a-btn a-btn--outline w-dl" data-dldiff="' + idx + '">Download</button></small></summary><pre>' + diffHtml(d.body) + "</pre></details>";
  }).join("") || '<div class="c-empty">No code changes yet — they show up during the implement stage.</div>';
  renderPrPane(run);
  var seen = { skill: {}, playbook: {}, agent: {}, gate: {} };
  run.events.forEach(function (e) { if (seen[e.kind]) { seen[e.kind][e.name] = e.detail; } });
  function pills(kind, label) {
    var names = Object.keys(seen[kind]);
    return '<div class="c-h">' + label + "</div>" + (names.length ? names.map(function (n) { return '<span class="c-pill' + (/finish|done|closed|approved/i.test(seen[kind][n]) ? "" : " c-pill--on") + '" title="' + esc(seen[kind][n]) + '">' + esc(n) + "</span>"; }).join("") : '<span class="c-muted">none yet</span>');
  }
  $("paneSkills").innerHTML = pills("agent", "Agents") + pills("skill", "Skills") + pills("playbook", "Playbooks") + pills("gate", "Gates") +
    '<div class="c-h">Prompt sent to the session</div><pre class="a-pre" style="font-size:11px;white-space:pre-wrap">' + esc(run.prompt || "(started before this machine saw it)") + "</pre>";
  $("paneChat").innerHTML = chatHtml(run.messages);
  renderTrace(run, run.trace, tab);
}
// ------------------------------------------------------------ Trace tab: evidence of what the run loaded and decided
function traceLine(prefix, text, cls) { return prefix + (cls ? '<span class="' + cls + '">' + text + "</span>" : text) + "\n"; }
function traceBranch(label, items, fmt, last) {
  if (!items.length) { return ""; }
  var out = (last ? "└─ " : "├─ ") + label + "\n", pad = last ? "   " : "│  ";
  items.forEach(function (it, i) { out += traceLine(pad + (i === items.length - 1 ? "└─ " : "├─ "), fmt(it), ""); });
  return out;
}
function renderTrace(run, trace, tab) {
  if (!trace) { $("paneTrace").innerHTML = '<div class="c-empty">Open a run to see what it loaded and decided.</div>'; return; }
  var stages = trace.stages.filter(function (s) { return tab === "all" || !tab || s.stage === tab; });
  var queued = trace.stages.filter(function (s) { return s.status === "pending"; }).map(function (s) { return s.agent; });
  var html = stages.map(function (s) {
    var head = '<div class="w-trace__head' + (s.status === "pending" ? " is-queued" : "") + '"><b>' + esc(s.stage.toUpperCase()) + "</b> · agent: " + esc(s.agent) + " · " + esc(s.status) + "</div>";
    var has = s.skills.length || s.rules.length || s.kb.length || s.chains.length || s.ontology.length || s.graph.length || s.drift.length || s.sync.length || (s.evidence || []).length || (s.tests || []).length || (s.contract || []).length || s.routes.length || s.decisions.length || s.gates.length || s.agents.length;
    if (!has) { return head + '<div class="w-trace__empty">' + (s.status === "pending" ? "queued" : "no trace lines reported for this stage") + "</div>"; }
    var agents = s.agents.length ? s.agents.map(function (a) { return esc(a.name) + (a.state === "running" ? " ← current" : " (" + a.state + ")"); }) : [esc(s.agent) + (s.status === "running" ? " ← current" : "")];
    if (s.stage === trace.current && queued.length) { agents.push("queued: " + esc(queued.join(", "))); }
    var why = function (x) { return x.why ? ' <span class="w-trace__why">why: ' + esc(x.why) + "</span>" : ""; };
    var gateOwner = function (g) {
      var w = trace.pending_gate && trace.pending_gate.id === g.id ? trace.pending_gate : null;
      return esc(g.id) + " — " + esc(g.state) + (w && w.role ? ' <span class="w-trace__why">waiting on ' + esc(w.role.replace(/_/g, " ")) + (w.timeout_hours ? ", " + esc(String(w.timeout_hours)) + "h timeout" : "") + "</span>" : "");
    };
    var checkLine = function (x) {
      var ok = /^(current|updated|passed)$/i.test(x.result || "");
      return esc(x.artifact) + " — " + esc(x.what) + why(x) +
        ' <span class="' + (ok ? "w-trace__hit" : "w-trace__skip") + '">' + esc(x.result || "?") + "</span>";
    };
    var tree = traceBranch("Agents active", agents, function (a) { return a; }) +
      traceBranch("Routing", s.routes, function (r) { return esc(r.entry) + ' <span class="w-trace__why">' + esc(r.detail) + "</span>"; }) +
      traceBranch("Skills invoked", s.skills, function (k) { return "skill:" + esc(k.name) + (k.state === "running" ? " (running)" : "") + why(k); }) +
      traceBranch("Playbooks", s.playbooks, function (k) { return esc(k.name) + why(k); }) +
      traceBranch("Rulebooks loaded", s.rules, function (r) { return esc(r.path) + ' <span class="' + (r.verdict === "loaded" ? "w-trace__hit" : "w-trace__skip") + '">' + esc(r.verdict) + "</span>" + why(r); }) +
      traceBranch("Knowledge base", s.kb, function (k) { return esc(k.path) + ' <span class="' + (k.verdict === "loaded" ? "w-trace__hit" : "w-trace__skip") + '">' + esc(k.verdict.toUpperCase()) + "</span>" + why(k); }) +
      traceBranch("Matrix chains", s.chains, function (c) { return esc(c.id) + " — " + esc(c.what); }) +
      traceBranch("Ontology", s.ontology, function (o) {
        return esc(o.command) + " " + esc(o.term) + " — " + esc(o.found) +
          (o.why ? ' <span class="w-trace__why">why: ' + esc(o.why) + "</span>" : "") +
          (o.gain ? ' <span class="w-trace__hit">gain: ' + esc(o.gain) + "</span>" : "");
      }) +
      traceBranch("Link graph", s.graph, function (o) {
        return esc(o.command) + " " + esc(o.term) + " — " + esc(o.found) +
          (o.why ? ' <span class="w-trace__why">why: ' + esc(o.why) + "</span>" : "") +
          (o.gain ? ' <span class="w-trace__hit">gain: ' + esc(o.gain) + "</span>" : "");
      }) +
      traceBranch("Drift checks", s.drift, checkLine) +
      traceBranch("KB sync", s.sync, checkLine) +
      traceBranch("QA suite", s.qa || [], checkLine) +
      traceBranch("Evidence", s.evidence, checkLine) +
      traceBranch("Tests picked", s.tests, checkLine) +
      traceBranch("Contract checks", s.contract, checkLine) +
      traceBranch("Gates", s.gates, gateOwner) +
      traceBranch("Decisions", s.decisions, function (d) { return esc(d.what) + " — " + esc(d.detail); }, true);
    return head + '<pre class="w-trace__tree">' + tree + "</pre>";
  }).join("");
  $("paneTrace").innerHTML = '<div class="w-bundle"><a class="a-btn a-btn--outline" href="/api/runs/' + run.id + '/trace.txt" download>Download trace (all stages, .txt)</a></div>' + html + '<div class="c-muted" style="font-size:11px">Only what the session reported with [SDLC] route / kb / rule / chain / ontology / graph / drift / sync / qa / evidence / tests / contract / decision lines (.devin/rules/workbench-trace.md). No token counts or similarity scores exist in this pipeline, so none are shown.</div>';
  renderTraceFloat();
}

// ------------------------------------------------------------ floating Trace window (Settings → Trace)
var floatPos = { dragging: false, dx: 0, dy: 0 };
function openTraceFloat() {
  closeMenus();
  var f = $("traceFloat");
  f.hidden = false; f.classList.remove("is-min");
  renderTraceFloat();
}
function renderTraceFloat() {
  var f = $("traceFloat");
  if (f.hidden) { return; }
  var run = state.run;
  $("traceFloatRun").textContent = run ? "· " + (run.story && run.story.key || run.id) : "";
  $("traceFloatBody").innerHTML = run ? $("paneTrace").innerHTML : '<div class="c-empty">Open a run to see what it loaded and decided.</div>';
}
$("traceFloatBar").addEventListener("mousedown", function (ev) {
  if (ev.target.closest("[data-tracefloat]")) { return; }
  var r = $("traceFloat").getBoundingClientRect();
  floatPos.dragging = true; floatPos.dx = ev.clientX - r.left; floatPos.dy = ev.clientY - r.top;
  ev.preventDefault();
});
document.addEventListener("mousemove", function (ev) {
  if (!floatPos.dragging) { return; }
  var f = $("traceFloat");
  f.style.left = Math.max(0, Math.min(window.innerWidth - 80, ev.clientX - floatPos.dx)) + "px";
  f.style.top = Math.max(0, Math.min(window.innerHeight - 40, ev.clientY - floatPos.dy)) + "px";
  f.style.right = "auto";
});
document.addEventListener("mouseup", function () { floatPos.dragging = false; });



// ------------------------------------------------------------ chat with Devin Cloud (right column on the PC screen)
// ------------------------------------------------------------ desktop notifications (only while the page is in the background)
function notifyOn() { return !!window.Notification && Notification.permission === "granted" && localStorage.getItem("wbNotify") === "1"; }
function notifyLabel() {
  if (!window.Notification) { return "Not available in this browser"; }
  if (Notification.permission === "denied") { return "Blocked: allow notifications for this page in the browser's site settings"; }
  return notifyOn() ? "On (click to turn off)" : "Off (click to turn on)";
}
function toggleNotify(el) {
  if (!window.Notification) { return; }
  var label = function () { el.querySelector("b").textContent = notifyLabel(); };
  if (notifyOn()) { localStorage.setItem("wbNotify", "0"); label(); return; }
  Notification.requestPermission().then(function (p) { if (p === "granted") { localStorage.setItem("wbNotify", "1"); } label(); });
}
// Every alert also goes in the Alerts list on the top bar, so nothing depends on a pop-up being seen.
function logAlert(tag, title, body) {
  var list = []; try { list = JSON.parse(localStorage.getItem("sdlc-alerts") || "[]"); } catch (e) { list = []; }
  if (list.some(function (a) { return a.tag === tag; })) { return; }
  list.unshift({ tag: tag, title: title, body: String(body || "").slice(0, 160), at: Date.now() / 1000, seen: false });
  localStorage.setItem("sdlc-alerts", JSON.stringify(list.slice(0, 50)));
  if (typeof alertCount === "function") { alertCount(); }
}
function notify(tag, title, body, go) {
  logAlert(tag, title, body);
  if (!notifyOn() || (!document.hidden && document.hasFocus())) { return; }
  try {
    var n = new Notification(title, { body: body || "", tag: tag });
    n.onclick = function () { window.focus(); n.close(); if (go) { go(); } };
  } catch (e) { /* the browser refused; the page still shows everything */ }
}

function typing() {
  var el = document.activeElement;
  return !!el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT") && !!(el.value || "").trim();
}
function renderPcBadge(tests) {
  var b = $("navPcNeed");
  if (state.pcBack) {
    b.hidden = false; b.textContent = "Back with Cloud: " + state.pcBack.ticket; b.title = "Open the Cloud session for " + state.pcBack.ticket;
    b.title = "The PC test is done and Cloud has control again. Click to open the Cloud session.";
    return;
  }
  var need = tests.filter(function (t) { return t.state === "testing" && t.progress && /^(Waiting for you|Ready\.)/.test(t.progress.now); })[0];
  b.hidden = !need || !$("pcView").hidden;
  var needKey = need ? need.ticket + "|" + need.progress.now : "";
  if (needKey && needKey !== state.needSeen) { notify("pc-need", "Devin Local needs you · " + need.ticket, need.progress.now, function () { $("navPc").click(); }); }
  state.needSeen = needKey;
  if (need) { b.textContent = "Devin Local needs you"; b.title = need.ticket + ": " + need.progress.now; }
}
var TRACE_LINE = /^\s*\[SDLC\]/;
function noTrace(text) { return String(text || "").split("\n").filter(function (ln) { return !TRACE_LINE.test(ln); }).join("\n").trim(); }
function chatHtml(messages) {
  return messages.filter(function (m) { return noTrace(m.text); }).map(function (m) {
    return '<div class="c-ev c-ev--msg' + (m.source !== "devin" ? " is-user" : "") + '"><span class="c-ev__who">' + (m.source === "devin" ? "Devin" : "You") + " · " + fmtTime(m.at) + "</span>" + esc(noTrace(m.text)) + "</div>";
  }).join("") || '<div class="c-empty">No messages yet.</div>';
}
function chatTargets() {
  var out = [], seen = {};
  ((state.pc && state.pc.tests) || []).forEach(function (t) {
    if (!t.session || seen[t.session]) { return; }
    seen[t.session] = 1;
    out.push({ value: "pc:" + t.session, label: t.ticket + " in Cloud" + (t.control === "pc" ? " (your PC has control)" : ""), session: t.session, ticket: t.ticket });
  });
  (state.runs || []).filter(function (r) { return r.kind === "chat"; }).forEach(function (r) {
    out.push({ value: "run:" + r.id, label: "Chat: " + r.story.summary.slice(0, 50), run: r.id });
  });
  out.push({ value: "new", label: "New chat with Devin" });
  return out;
}
function renderChatTargets() {
  var opts = chatTargets(), sel = $("chatWith");
  var html = opts.map(function (o) { return '<option value="' + esc(o.value) + '">' + esc(o.label) + "</option>"; }).join("");
  if (html !== state.chatOpts) { state.chatOpts = html; sel.innerHTML = html; }
  var pick = opts.some(function (o) { return o.value === state.chatWith; }) ? state.chatWith : opts[0].value;
  sel.value = pick;
  if (pick !== state.chatWith) { chatSelect(pick); }
}
function chatSelect(value) {
  var o = chatTargets().filter(function (x) { return x.value === value; })[0] || { value: "new" };
  state.chatWith = o.value; state.chatRun = null; state.chatHtml = null; $("chatErr").hidden = true;
  var pc = o.session && state.pc.tests.filter(function (t) { return t.session === o.session && t.control === "pc"; })[0];
  $("chatHint").textContent = o.value === "new" ? "Goes to your Argus assistant session for today: a plain chat, not an SDLC run." :
    pc ? "Cloud keeps off the branch while your PC has control." : "";
  if (o.value === "new") {
    $("chatLog").innerHTML = '<div class="c-empty">Ask Devin anything, or give it a task. Your other work keeps running.</div>';
    return;
  }
  $("chatLog").innerHTML = '<div class="c-empty">Loading the Cloud session…</div>';
  var got = o.run ? Promise.resolve({ id: o.run }) : api("POST", "/api/runs/open", { session: o.session, ticket: o.ticket });
  got.then(function (run) { if (state.chatWith === o.value) { state.chatRun = run.id; chatPoll(true); } })
    .catch(function (e) {
      if (state.chatWith === o.value) { $("chatLog").innerHTML = '<div class="c-empty">Couldn\'t open this Cloud session.</div>'; }
      $("chatErr").innerHTML = errHtml(e.message); $("chatErr").hidden = false;
    });
}
// A long chat or menu-item session: offer a new one that starts from a handover of this one.
function longNote(run) {
  if (!run.long_session || (run.kind !== "chat" && run.kind !== "action")) { return ""; }
  return '<div class="w-long">This session has ' + run.session_messages + " messages. A new session that starts from a handover summary is cheaper and easier to review. " +
    '<button type="button" class="a-btn a-btn--outline" data-freshrun="' + esc(run.id) + '">Start a new session with a handover</button></div>';
}
document.addEventListener("click", function (e) {
  var b = e.target.closest && e.target.closest("[data-freshrun]");
  if (!b) { return; }
  askConfirm("A new Devin Cloud session starts and carries on from this one with a handover summary. This one stays as it is.",
    { title: "Start a new session?", ok: "Start the new session" }).then(function (yes) {
    if (!yes) { return; }
    b.disabled = true;
    api("POST", "/api/runs/" + b.getAttribute("data-freshrun") + "/fresh", {})
      .then(function (run) { b.disabled = false; return loadRuns().then(function () { startedNote(run, "New session started with a handover"); }); })
      .catch(function (err) { alert("Could not start the new session: " + err.message); b.disabled = false; });
  });
});
function chatPoll(refresh) {
  var id = state.chatRun;
  if (!id || $("pcView").hidden) { return; }
  return api("GET", "/api/runs/" + id + (refresh === true ? "?refresh=1" : "")).then(function (run) {
    if (state.chatRun !== id) { return; }
    var html = chatHtml(run.messages) + longNote(run) + (run.sent_at || BUSY.indexOf(run.status) >= 0 ? '<div class="w-chat__busy">Devin is working on a reply…</div>' : "");
    if (html === state.chatHtml) { return; }
    var log = $("chatLog"), bottom = state.chatHtml === null || log.scrollHeight - log.scrollTop - log.clientHeight < 40, top = log.scrollTop;
    state.chatHtml = html; log.innerHTML = html;
    log.scrollTop = bottom ? log.scrollHeight : top;
  }).catch(function (e) {
    if (state.chatRun === id && state.chatHtml === null) { $("chatLog").innerHTML = '<div class="c-empty">Couldn\'t load this Cloud session.</div>'; }
    $("chatErr").innerHTML = errHtml(e.message); $("chatErr").hidden = false;
  });
}
$("chatWith").addEventListener("change", function () { chatSelect(this.value); });
$("chatText").addEventListener("keydown", function (ev) {
  if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); $("chatForm").requestSubmit(); }
});
$("chatForm").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var text = $("chatText").value.trim(), btn = $("chatSend");
  if (!text) { $("chatText").focus(); return; }
  btn.disabled = true; $("chatErr").hidden = true;
  var sent = state.chatWith === "new"
    ? api("POST", "/api/runs", { chat: text }).then(function (run) {
      return loadRuns().then(function () { state.chatOpts = null; renderChatTargets(); $("chatWith").value = "run:" + run.id; chatSelect("run:" + run.id); });
    })
    : state.chatRun ? api("POST", "/api/runs/" + state.chatRun + "/message", { text: text }).then(function () { chatPoll(true); })
      : Promise.reject(new Error("the Cloud session is still loading; try again in a moment"));
  sent.then(function () { $("chatText").value = ""; })
    .catch(function (e) { $("chatErr").textContent = e.message; $("chatErr").hidden = false; })
    .then(function () { btn.disabled = false; });
});
