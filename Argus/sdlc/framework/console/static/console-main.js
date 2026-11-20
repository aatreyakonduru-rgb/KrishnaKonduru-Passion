/* Argus — front end, page wiring, start-up and updates. Talks only to the local server's /api routes.
   The page loads console.js, console-run.js, console-pc.js, console-backlog.js and console-main.js in that
   order as plain scripts sharing one scope; console-main.js wires the page and starts it. */
"use strict";
// ------------------------------------------------------------ wiring
document.addEventListener("click", function (ev) {
  var t = ev.target.closest("[data-dlart]");
  if (t) { ev.preventDefault(); ev.stopPropagation(); var a = state.run.artefacts[+t.dataset.dlart]; download(a.name, a.body || a.detail); return; }
  t = ev.target.closest("[data-dldiff]");
  if (t) { ev.preventDefault(); ev.stopPropagation(); var d = state.run.diffs[+t.dataset.dldiff]; download(d.path + ".diff", d.body); return; }
  t = ev.target.closest("[data-menubtn]"); if (t) { toggleMenu(t.dataset.menubtn); return; }
  t = ev.target.closest("[data-setrole]"); if (t) { setRole(t.dataset.setrole); return; }
  t = ev.target.closest("[data-fold]"); if (t) { toggleSide(t.dataset.fold); return; }
  t = ev.target.closest("[data-notify]"); if (t) { toggleNotify(t); return; }
  t = ev.target.closest("[data-standup]"); if (t) { closeMenus(); standup(); return; }
  t = ev.target.closest("[data-pin]"); if (t) { ev.stopPropagation(); togglePin(t.dataset.pin); return; }
  t = ev.target.closest("[data-checkdone]"); if (t) { localStorage.setItem("sdlc-checklist-off", "1"); renderToday(); return; }
  t = ev.target.closest("[data-opendash]"); if (t) { $("navDashboard").click(); return; }
  t = ev.target.closest("[data-sessf]"); if (t) { state.sessFilter = t.dataset.sessf; renderSessions(); return; }
  t = ev.target.closest("[data-healthretry]");
  if (t) {
    t.disabled = true; t.textContent = "Checking…";
    api("GET", "/api/health?fresh=1").then(showHealth, function () {}).then(function () { loadStories(); loadWaiting(); if (!$("backlogView").hidden) { blLoad(false); } });
    return;
  }
  t = ev.target.closest("#healthDot");
  if (t) { var hb = $("healthBar"); if (hb.innerHTML) { hb.hidden = !hb.hidden; } else { api("GET", "/api/health?fresh=1").then(showHealth, function () {}); } return; }
  t = ev.target.closest("[data-qsperson]");
  if (t) { $("qsModal").hidden = true; tchat.open = true; tchat.shut = false; tchatRender(); $("tchatText").value = "@" + t.dataset.qsperson + " "; $("tchatText").focus(); return; }
  t = ev.target.closest("[data-tracefloat]");
  if (t) {
    if (t.dataset.tracefloat === "open") { openTraceFloat(); }
    else if (t.dataset.tracefloat === "min") { $("traceFloat").classList.toggle("is-min"); }
    else { $("traceFloat").hidden = true; }
    return;
  }
  t = ev.target.closest("[data-blpane]"); if (t) { closeMenus(); openBlPane(t.dataset.blpane); return; }
  t = ev.target.closest("[data-wbtask]"); if (t) { openWbTask(t.dataset.wbtask); return; }
  t = ev.target.closest("[data-gpgroom]");
  if (t) { bl.key = t.dataset.gpgroom; bl.filter = bl.key; $("blFilter").value = bl.key; openBlPane("groom"); blRenderList(); blDetail(); return; }
  t = ev.target.closest("[data-gpclone]");
  if (t) { blErr(null); api("POST", "/api/backlog/clone", { key: t.dataset.gpclone, user: blUser() }).then(function (d) { openBlPane("groom"); blDone(d); }, blErr); return; }
  t = ev.target.closest("[data-gpnew]");
  if (t) {
    openBlPane("create"); $("blSummary").value = t.dataset.gpnew;
    $("blBlockedBy").value = t.dataset.gpfrom || "";
    return;
  }
  t = ev.target.closest("[data-gpcopy]");
  if (t) {
    var box = t.parentNode.querySelector("textarea");
    if (box && navigator.clipboard) { navigator.clipboard.writeText(box.value).then(function () { t.textContent = "Copied"; }); }
    else if (box) { box.select(); document.execCommand("copy"); t.textContent = "Copied"; }
    return;
  }
  t = ev.target.closest("[data-wbmore]");
  if (t) { var more = allTasks().filter(function (x) { return x.id === t.dataset.wbmore; })[0]; if (more && more.more_action) { openActionItem(more.more_action); } return; }
  t = ev.target.closest("[data-skill]"); if (t) { openAction(t.dataset.skill); return; }
  t = ev.target.closest("[data-focusnew]"); if (t) { closeMenus(); openNewReq(true); return; }
  if (ev.target.closest("#topSearch")) { closeMenus(); openQuick(); return; }
  if (ev.target.closest("#spClose")) { closePanel(); return; }
  if (ev.target.closest("[data-openactions]")) { openActions(); return; }
  if (ev.target.closest("[data-ticketgroom]")) { $("storyHours").click(); return; }
  t = ev.target.closest("[data-alltools]"); if (t) { var mt = $("moreTools"); if (mt) { mt.dataset.open = "1"; mt.hidden = false; t.hidden = true; } return; }
  t = ev.target.closest("#customToggle"); if (t) { openNewReq($("customForm").hidden); return; }
  t = ev.target.closest("[data-lefttab]"); if (t) { localStorage.setItem("sdlc-lefttab", t.dataset.lefttab); applyLeftTab(); return; }
  t = ev.target.closest("[data-copy]");
  if (t) { if (navigator.clipboard) { navigator.clipboard.writeText(t.dataset.copy).then(function () { t.textContent = "Copied"; }); } return; }
  t = ev.target.closest("[data-pcrecheck]");
  if (t) { t.disabled = true; t.textContent = "Checking…"; api("GET", "/api/pc").then(applyPc, function () { renderPcSetup(); }); return; }
  t = ev.target.closest("[data-prcheck]"); if (t) { checkPrs(t); return; }
  t = ev.target.closest("[data-waitcheck]"); if (t) { t.disabled = true; t.textContent = "Asking Devin Cloud…"; loadWaiting(true); return; }
  t = ev.target.closest("[data-task]"); if (t) { openTask(t.dataset.task); return; }
  t = ev.target.closest("[data-nudgeanswer]"); if (t) { answerNudge(t); return; }
  t = ev.target.closest("[data-nudgedismiss]"); if (t) { dismissNudge(t.dataset.nudgedismiss); return; }
  t = ev.target.closest("[data-showarch]"); if (t) { state.showArchived = !state.showArchived; renderSessions(); return; }
  t = ev.target.closest("[data-sync]"); if (t) { t.textContent = "Reloading…"; syncRuns(); return; }
  t = ev.target.closest(".c-tab[data-right]"); if (t) { setRightTab(t.dataset.right); return; }
  t = ev.target.closest("[data-stage]"); if (t) { setStageTab(t.dataset.stage); return; }
  t = ev.target.closest("[data-key]");
  if (t && !$("pcView").hidden && t.closest("#storyList")) { $("pcTicket").value = t.dataset.key; renderPcSetup(); lookupPc(t.dataset.key); return; }
  if (t) { showStory(t.dataset.key); return; }
  t = ev.target.closest("[data-delrun]"); if (t) { deleteRun(t.dataset.delrun); return; }
  t = ev.target.closest("[data-run]"); if (t) { openRun(t.dataset.run); return; }
  if (!ev.target.closest(".w-menu")) { closeMenus(); }
});
document.addEventListener("keydown", function (ev) {
  if (ev.key === "Escape") { closeMenus(); setNav(false); $("actionModal").hidden = true; $("taskModal").hidden = true; $("qsModal").hidden = true; $("keysModal").hidden = true; $("sentModal").hidden = true; if (!$("tourBox").hidden) { endTour(); } }
  if ((ev.ctrlKey || ev.metaKey) && (ev.key === "k" || ev.key === "K")) { ev.preventDefault(); openQuick(); return; }
  if (!$("qsModal").hidden) { qsKey(ev); return; }
  var tag = (ev.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" || ev.target.isContentEditable || ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
  if (ev.key === "/") {
    var f = !$("backlogView").hidden ? $("blFilter") : $("filter");
    if (f && f.offsetParent) { ev.preventDefault(); f.focus(); }
  } else if (ev.key === "?") {
    ev.preventDefault(); closeMenus(); $("keysModal").hidden = false; $("keysModal").querySelector("button").focus();
  } else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { listMove(ev); }
});
// Up and down move between the rows of the list that has focus (tickets, Backlog, tools, menus).
function listMove(ev) {
  var item = ev.target.closest && ev.target.closest(".c-item, .w-drop__item"); if (!item) { return; }
  var box = item.closest("#storyList, #blList, #toolList, #taskList, .w-drop, #today"); if (!box) { return; }
  var rows = Array.prototype.filter.call(box.querySelectorAll(".c-item, .w-drop__item"), function (el) { return el.offsetParent && el.tabIndex >= 0; });
  var i = rows.indexOf(item) + (ev.key === "ArrowDown" ? 1 : -1);
  if (rows[i]) { ev.preventDefault(); rows[i].focus(); rows[i].scrollIntoView({ block: "nearest" }); }
}
// Quick search (Ctrl+K): tools, tickets and sessions in one box; each row keeps the data attribute its menu uses.
var qs = { rows: [], at: 0 };
function openQuick() {
  closeMenus(); setNav(false);
  $("qsModal").hidden = false; $("qsText").value = ""; qsRender(); $("qsText").focus();
}
function qsSource() {
  var out = [], keys = {};
  var tools = isBiz() ? document.querySelectorAll("#taskList [data-wbtask]") : document.querySelectorAll("#toolItems .w-drop__item");
  Array.prototype.forEach.call(tools, function (el) {
    var c = el.cloneNode(true); c.removeAttribute("hidden"); c.removeAttribute("id"); c.className = "w-drop__item";
    out.push({ group: "Tools", text: el.textContent, html: c.outerHTML });
  });
  Array.prototype.forEach.call(document.querySelectorAll("#drop-kb .w-drop__item"), function (el) {
    var c = el.cloneNode(true); c.removeAttribute("hidden"); c.removeAttribute("id"); c.className = "w-drop__item";
    out.push({ group: "Knowledge base", text: el.textContent, html: c.outerHTML });
  });
  (state.stories || []).forEach(function (st) {
    keys[st.key] = 1;
    out.push({ group: "Tickets", text: st.key + " " + st.summary, html: '<button type="button" class="w-drop__item" data-key="' + esc(st.key) + '"><b>' + esc(st.key) + " · " + esc(st.status) + "</b><span>" + esc(st.summary) + "</span></button>" });
  });
  ((bl.data || {}).stories || []).forEach(function (st) {
    if (keys[st.key]) { return; }
    out.push({ group: "Tickets", text: st.key + " " + st.summary, html: '<button type="button" class="w-drop__item" data-gpgroom="' + esc(st.key) + '"><b>' + esc(st.key) + " · Backlog</b><span>" + esc(st.summary) + "</span></button>" });
  });
  (state.runs || []).filter(function (r) { return !r.archived; }).forEach(function (r) {
    out.push({ group: "Sessions", text: runKey(r) + " " + r.story.summary + " " + (r.status || ""), html: '<button type="button" class="w-drop__item" data-run="' + esc(r.id) + '"><b>' + esc(runKey(r)) + " " + statusBadge(r) + "</b><span>" + esc(r.story.summary) + "</span></button>" });
  });
  if (!$("teamChat").hidden) {
    (state.people || []).filter(function (p) { return p.jira_user !== state.user; }).forEach(function (p) {
      var on = tchat.online.indexOf(p.jira_user) >= 0;
      out.push({ group: "People", text: p.name + " " + p.jira_user, html: '<button type="button" class="w-drop__item" data-qsperson="' + esc(tchatHandle(p)) + '"><b>' +
        (on ? '<span class="w-dot" title="Argus open now"></span>' : "") + esc(p.name) + "</b><span>Team chat" + (on ? " · Argus open now" : "") + "</span></button>" });
    });
  }
  return out;
}
function qsRender() {
  var words = $("qsText").value.trim().toLowerCase().split(/\s+/).filter(Boolean), per = {}, html = "", last = "";
  qs.rows = qsSource().filter(function (it) {
    var t = it.text.toLowerCase();
    if (!words.every(function (w) { return t.indexOf(w) >= 0; })) { return false; }
    per[it.group] = (per[it.group] || 0) + 1;
    return per[it.group] <= (words.length ? 8 : 5);
  });
  qs.at = 0;
  qs.rows.forEach(function (it) { if (it.group !== last) { html += '<div class="w-drop__head">' + it.group + "</div>"; last = it.group; } html += it.html; });
  $("qsList").innerHTML = html || '<div class="c-empty">Nothing matches.</div>';
  qsMark();
}
function qsMark() {
  var items = $("qsList").querySelectorAll(".w-drop__item");
  Array.prototype.forEach.call(items, function (el, i) { el.classList.toggle("is-active", i === qs.at); if (i === qs.at) { el.scrollIntoView({ block: "nearest" }); } });
}
function qsKey(ev) {
  var n = $("qsList").querySelectorAll(".w-drop__item").length;
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); qs.at = (qs.at + (ev.key === "ArrowDown" ? 1 : n - 1)) % Math.max(n, 1); qsMark(); }
  else if (ev.key === "Enter") { ev.preventDefault(); var el = $("qsList").querySelectorAll(".w-drop__item")[qs.at]; if (el) { el.click(); } }
}
$("qsText").addEventListener("input", qsRender);
$("qsList").addEventListener("click", function (ev) { if (ev.target.closest(".w-drop__item")) { $("qsModal").hidden = true; } });
$("qsModal").addEventListener("click", function (ev) { if (ev.target === this) { this.hidden = true; } });
// Five-step tour: shown once on first use (always for the New joiner role) and from Help → Take the tour.
var FIRST_USE = !Object.keys(window.localStorage || {}).some(function (k) { return k.indexOf("sdlc-") === 0; });
var TOUR = [
  { sel: ".w-nav, #navToggle", title: "The top bar", text: "Test on my PC, Backlog, Dashboard and the menus. My tools has what your role does, Waiting on me is your inbox and My sessions lists your runs." },
  { sel: ".c-left", title: "My work", text: "Your Jira tickets: pick one to see it and start SDLC. What I do lists your role's tools, and + New requirement starts from one or two sentences." },
  { sel: ".c-main", title: "The middle", text: "Whatever you open: a ticket, a run or Test on my PC. With nothing open it shows Today: what waits on you, what to approve, your sessions and sprint health." },
  { sel: "#right", title: "To approve and documents", text: "Approvals for the open run, with its documents, diffs, PR, skills and chat. It folds to a thin rail when it has nothing in it." },
  { sel: "#menuMe", title: "You and settings", text: "Who you are, the look and What I sent today. Help, next to it, has the manual, this tour and keyboard shortcuts. Press Ctrl+K at any time to find a tool, ticket or session." }
];
var tour = { at: -1, el: null };
function tourTarget(sel) { return Array.prototype.filter.call(document.querySelectorAll(sel), function (el) { return el.offsetParent || el.getClientRects().length; })[0]; }
function startTour() { closeMenus(); setNav(false); tourGo(0); }
function tourGo(i) {
  if (tour.el) { tour.el.classList.remove("is-tour"); }
  var step = TOUR[i], box = $("tourBox"); if (!step) { endTour(); return; }
  tour.at = i; tour.el = tourTarget(step.sel);
  $("tourStep").textContent = "Step " + (i + 1) + " of " + TOUR.length;
  $("tourTitle").textContent = step.title; $("tourText").textContent = step.text;
  $("tourBack").disabled = i === 0; $("tourNext").textContent = i === TOUR.length - 1 ? "Done" : "Next";
  box.hidden = false;
  var r = tour.el ? tour.el.getBoundingClientRect() : { top: 80, bottom: 80, left: 80, right: 80, height: 0 };
  if (tour.el) { tour.el.classList.add("is-tour"); }
  var w = box.offsetWidth, h = box.offsetHeight, top, left;
  if (r.height > window.innerHeight * 0.4) { top = r.top + 60; left = r.right + 12 + w < window.innerWidth ? r.right + 12 : r.left + 20; }
  else { top = r.bottom + 10; left = r.left; }
  box.style.top = Math.max(10, Math.min(top, window.innerHeight - h - 10)) + "px";
  box.style.left = Math.max(10, Math.min(left, window.innerWidth - w - 10)) + "px";
  $("tourNext").focus();
}
function endTour() {
  if (tour.el) { tour.el.classList.remove("is-tour"); }
  tour.at = -1; tour.el = null; $("tourBox").hidden = true;
  localStorage.setItem(tourKey(), "1");
}
// The New joiner role has its own key, so a PC that has seen the tour still shows it once to a new joiner.
function tourKey() { var role = state.me && state.me.role; return role && role.id === "new_joiner" ? "sdlc-tour-done-new_joiner" : "sdlc-tour-done"; }
function maybeTour() {
  var role = state.me && state.me.role;
  if (!localStorage.getItem(tourKey()) && (FIRST_USE || (role && role.id === "new_joiner"))) { startTour(); }
}
$("tourNext").addEventListener("click", function () { tourGo(tour.at + 1); });
$("tourBack").addEventListener("click", function () { tourGo(tour.at - 1); });
$("tourSkip").addEventListener("click", endTour);
// The ? on each screen opens the manual at that screen's chapter (a text fragment link).
var HELP_FOR_BACKLOG = { followups: "13. Scrum Master follow-ups: leave, capacity, one story at a time, stand-up gaps", plan: "12.4 New epic or story, and the sprint screens",
  calendar: "12.4 New epic or story, and the sprint screens", create: "12.4 New epic or story, and the sprint screens" };
function helpHeading(v) { return v === "backlog" ? HELP_FOR_BACKLOG[bl.pane] || "12. Backlog: groom, point, poker and sprints" : v; }
document.addEventListener("click", function (ev) {
  var t = ev.target.closest("[data-helpfor]");
  if (t) {
    var manual = (state.cfg.docs || {}).workbench_manual; if (!manual) { return; }
    window.open("/repo-file?path=" + encodeURIComponent(manual) + "#:~:text=" + encodeURIComponent(helpHeading(t.dataset.helpfor)).replace(/-/g, "%2D"), "_blank");
    return;
  }
  if (ev.target.closest("[data-seenall]")) { markAllSeen(); return; }
  if (ev.target.closest("[data-sent]")) { openSent(); return; }
  if (ev.target.closest("[data-keys]")) { closeMenus(); $("keysModal").hidden = false; $("keysModal").querySelector("button").focus(); return; }
  if (ev.target.closest("[data-tour]")) { startTour(); return; }
  t = ev.target.closest("[data-closemodal]"); if (t) { $(t.dataset.closemodal).hidden = true; }
});
document.addEventListener("input", function (ev) { if (ev.target.id === "toolSearch") { filterTools(ev.target.value); } });
document.addEventListener("click", function (ev) {
  if (ev.target.closest("#navToggle")) { setNav(!document.querySelector(".w-top").classList.contains("is-navopen")); return; }
  if (!ev.target.closest(".w-nav") || ev.target.closest(".w-nav > .w-nav__btn, .w-drop__item")) { setNav(false); }
});
$("scope").addEventListener("change", function () { localStorage.setItem("sdlc-scope-" + lensId(), $("scope").value); loadStories(); });
$("filter").addEventListener("input", renderStories);
$("whoSel").addEventListener("change", function () { setUser(this.value); });
$("themeBtn").addEventListener("click", function () {
  var r = document.documentElement; r.dataset.theme = THEMES[(THEMES.indexOf(r.dataset.theme) + 1) % THEMES.length]; localStorage.setItem("sdlc-theme", r.dataset.theme);
  themeName();
});
function themeName() {
  var cur = document.documentElement.dataset.theme, next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length], name = { acme: state.cfg.product || "default", earth: "earth", dark: "dark" };
  $("themeName").textContent = "Now " + (name[cur] || cur) + "; next " + (name[next] || next);
}
var savedTheme = localStorage.getItem("sdlc-theme");
document.documentElement.dataset.theme = THEMES.indexOf(savedTheme) >= 0 ? savedTheme : "acme";

// Configured is not the same as working: a system with a key whose last call failed is named here.
var HEALTH_NAMES = { jira: "Jira", devin: "Devin Cloud", bitbucket: "Bitbucket" };
function showHealth(h) {
  if (!h || !state.cfg) { return; }
  var me = (state.me && state.me.person) || {}, hats = [me.primary_role].concat(me.secondary_roles || []);
  if (h.dashboard_data && h.dashboard_data.stale && hats.some(function (r) { return /lead/.test(r || ""); })) {
    notify("dashdata-" + Math.floor(h.dashboard_data.saved_at), "Shared dashboard data is old",
      "The Argus maintenance job has not refreshed the nightly dashboard data for over a day and a half, so each Argus reads Jira itself. Check the job's last run.");
  }
  state.cfg.integrations = h; state.cfg.jira_ok = h.jira.connected; state.cfg.devin_ok = h.devin.connected;
  var keys = Object.keys(HEALTH_NAMES), bad = keys.filter(function (k) { return h[k] && h[k].state === "failing"; });
  var back = keys.filter(function (k) { return h[k] && h[k].state === "reconnecting"; });
  var dot = $("healthDot"), all = keys.every(function (k) { return h[k] && h[k].connected; });
  dot.dataset.state = bad.length ? "failing" : back.length ? "reconnecting" : all ? "ok" : "not_checked";
  dot.title = keys.map(function (k) { var x = h[k] || {}; return HEALTH_NAMES[k] + ": " + (x.state === "failing" ? "not working" : x.state === "reconnecting" ? "reconnecting" : x.connected ? "working" : "not checked yet"); }).join(" · ");
  var bar = $("healthBar");
  if (!bad.length && back.length) {
    bar.innerHTML = '<div class="w-healthbar__msg w-healthbar__msg--wait"><p><b>' + back.map(function (k) { return HEALTH_NAMES[k]; }).join(", ") +
      " is reconnecting.</b> Your requests wait and go through when it's back; nothing is lost.</p></div>";
    bar.hidden = false;
    if (!$("pcView").hidden) { renderPcSetup(); }
    return;
  }
  bar.innerHTML = bad.length ? '<div class="w-healthbar__msg">' + bad.map(function (k) {
    var raw = String(h[k].error || ""), p = /bridge is not running/.test(raw) ? raw : plainErr(raw).replace("Jira or Devin Cloud", HEALTH_NAMES[k]);
    return "<p><b>" + HEALTH_NAMES[k] + " isn't working.</b> " + esc(p) + (p !== raw ? ' <details class="w-errmore"><summary>Show details</summary>' + esc(raw) + "</details>" : "") + "</p>";
  }).join("") + '</div><button type="button" class="a-btn a-btn--outline w-sync" data-healthretry="1">Retry</button>' : "";
  bar.hidden = !bad.length;
  if (!$("pcView").hidden) { renderPcSetup(); }
}
// First run with nothing set up: Argus is using the made-up company. Say so on every screen, so no one mistakes it for real data.
function showSandbox(c) {
  var s = c.sandbox || {}, bar = $("sandboxBar");
  if (!bar) { return; }
  bar.hidden = !s.on;
  bar.innerHTML = s.on ? "<b>SANDBOX: made-up data.</b> " + esc(s.why || "") + ". Jira and Confluence here are a sample company at " + esc(s.url) +
    "; nothing real is read or written. To use your own, set the Jira token and a Devin key and start Argus again (or set SDLC_SANDBOX_FALLBACK=off)." : "";
}
// Build a first knowledge base from the repository Argus is in: routes, tables, dependencies, layout, with file and line.
function kbScanView(r) {
  var box = $("kbScan");
  if (!box) { return; }
  var c = r.counts || {}, stale = (r.stale || []).length, present = (r.unchanged || []).length;
  box.innerHTML = '<p><b>Knowledge base from this repository.</b> ' + (r.error ? esc(r.error) :
    (present && !stale ? "Up to date with the code (" + (c.endpoints || 0) + " endpoints, " + (c.tables || 0) + " tables, " + (c.ui_routes || 0) + " UI routes)." :
     stale && present ? esc(stale + " file(s) differ from the code now.") : "Not built yet. It reads the code in this repo; nothing leaves this PC.")) +
    ' Written to <code>' + esc(r.folder || "") + '</code>.</p><button type="button" class="a-btn a-btn--outline" id="kbScanBtn">' +
    (present ? "Rebuild from the code" : "Build from this repo") + "</button> <span id=\"kbScanMsg\" class=\"c-muted\"></span>";
  $("kbScanBtn").addEventListener("click", function () {
    $("kbScanMsg").textContent = "Reading the code…";
    api("POST", "/api/kb-scan", {}).then(function (res) {
      kbScanView(res);
      var n = (res.written || []).length;
      $("kbScanMsg").textContent = n ? "Wrote " + n + " file(s)." : "Nothing changed.";
    }, function (e) { $("kbScanMsg").textContent = e.message; });
  });
}
api("GET", "/api/config").then(function (c) {
  state.cfg = c; themeName();
  showSandbox(c);
  api("GET", "/api/kb-scan").then(kbScanView, function () {});
  applyPcMode(c);
  if (!c.devin_configured) { $("welcomeWarn").insertAdjacentHTML("beforeend", '<p class="c-err">No Devin API key yet. Open <b>Test on my PC</b> (top) and paste it once; it is kept in ' + esc((c.pc && c.pc.key_store) || "DEVIN_API_KEY") + ".</p>"); }
  showHealth(c.integrations); api("GET", "/api/health?fresh=1").then(showHealth, function () {});
  state.people = c.people || [];
  // The person picked under Me stays after a reload, until it is changed there or Argus starts as someone else.
  var start = c.default_jira_user || "", picked = localStorage.getItem("sdlc-jira-me") || "";
  var keep = picked && localStorage.getItem("sdlc-jira-me-start") === start &&
    state.people.some(function (p) { return p.jira_user === picked; });
  state.user = keep ? picked : (start || picked);
  if (!c.can_switch) { state.user = start; $("whoSel").closest("label").hidden = true; }
  state.role = localStorage.getItem("sdlc-role-preview") || "";
  var opts = state.people.map(function (p) { return '<option value="' + esc(p.jira_user) + '">' + esc(p.name) + "</option>"; }).join("");
  $("whoSel").innerHTML = '<option value="">— who are you? —</option>' + opts;
  $("whoSel").value = state.user;
  $("jiraAssignee").innerHTML = '<option value="">— pick a person —</option>' + opts;
  $("jiraAssignee").value = state.user;
  $("fwdPerson").innerHTML = '<option value="">— pick a person —</option>' + opts;
  if (!state.user) { $("scope").value = "sprint"; }
  loadMe().then(function () { loadStories(); openHashTask(); blRenderViews(); blViewFromHash(); maybeTour(); }, loadStories); syncRuns(); loadPrs(); loadWaiting();
  if (new URLSearchParams(location.search).get("open") === "dashboard") {
    history.replaceState(null, "", "/");
    if (state.user) { openDashboard(null); }
  }
});
every("status", 5000, loadStatus, { hidden: 30000, when: function () { return !!state.cfg; } });
// Re-shows the waiting list (kept on this PC; Jira is read again only on Check now) while the page is in use.
state.lastActive = Date.now();
["mousemove", "keydown", "click", "scroll", "touchstart"].forEach(function (ev) {
  document.addEventListener(ev, function () { state.lastActive = Date.now(); }, { passive: true });
});
function inUse() { return !document.hidden && Date.now() - state.lastActive < 3600000; }
every("waiting", 60000, loadWaiting, { hidden: 0, when: function () { return state.cfg && inUse(); } });
document.addEventListener("visibilitychange", function () { if (state.cfg && !document.hidden) { state.lastActive = Date.now(); loadWaiting(); } });
$("taskForm").addEventListener("submit", function (ev) { ev.preventDefault(); sendTask(taskKind(state.task) === "Approval" ? "approve" : "answer"); });
$("tmReject").addEventListener("click", function () { sendTask("reject"); });
$("tmCancel").addEventListener("click", function () { $("taskModal").hidden = true; });
// The PC test keeps running while other pages are open; the status call above keeps the badge and the
// jump back to Cloud working there.

function aboutHtml() {
  var a = state.about;
  if (!a) { return ""; }
  var when = a.commit_date ? a.commit_date.slice(0, 16).replace("T", " ") : "unknown";
  return '<div class="w-drop__head">About</div><div class="c-muted w-drop__foot">' +
    "<b>Version " + esc(a.version || "unknown") + "</b>" + (a.prompts_version ? " · shared KB prompts " + esc(a.prompts_version) : "") +
    "<br>Last commit " + esc(when) + (a.commit ? " (" + esc(a.commit) + ")" : "") + (a.branch ? " on " + esc(a.branch) : "") + "</div>";
}
function loadAbout() {
  return api("GET", "/api/about").then(function (a) {
    state.about = a;
    var el = $("helpAbout"); if (el) { el.innerHTML = aboutHtml(); }
  }).catch(function () { return null; });
}
function checkUpdate(fresh) {
  return api("GET", "/api/update" + (fresh ? "?fresh=1" : "")).then(function (u) {
    state.update = u;
    var b = $("navUpdate");
    b.hidden = !(u.ok && u.behind > 0);
    b.textContent = u.busy ? "Update ready (after your test)" : "Update Argus (" + u.behind + " new)";
    b.classList.toggle("w-upd--wait", !!u.why);
    b.title = u.why || ("Bitbucket has " + u.behind + " newer commit(s) on " + u.branch + ". Click to get them and restart.");
    if (u.ok && u.behind > 0 && !u.busy && state.updNotified !== u.remote) {
      state.updNotified = u.remote;
      notify("update", "Argus update ready", u.behind + " new commit(s) on " + u.branch + ". Click Update Argus to get them.");
    }
    return u;
  }).catch(function () { $("navUpdate").hidden = true; return null; });
}
document.addEventListener("click", function (ev) {
  if (!ev.target.closest("[data-docs]")) { return; }
  closeMenus();
  var manual = (state.cfg.docs || {}).workbench_manual;
  if (!manual) { alert("No Argus manual is set: add docs.workbench_manual to .devin/rules/sdlc-profile.json."); return; }
  var q = state.helpQuery || ""; state.helpQuery = "";
  window.open("/repo-file?path=" + encodeURIComponent(manual) + (q ? "#:~:text=" + encodeURIComponent(q) : ""), "_blank");
});
document.addEventListener("click", function (ev) {
  var el = ev.target.closest("[data-kbpage]"); if (!el) { return; }
  closeMenus();
  window.open("/page/" + encodeURIComponent(el.dataset.kbpage), "_blank");
});
function copyShow(s) {
  var note = $("copyNote"), log = $("copyLog");
  $("copyCheck").disabled = !!s.running;
  if (s.running) { note.textContent = "Checking v" + s.version + " here… it takes a few minutes."; }
  else if (s.exit === null || s.exit === undefined) { note.textContent = ""; }
  else if (s.exit === 0) { note.textContent = "v" + s.version + ": 0 leaks. Zip to try: " + s.zip; }
  else { note.textContent = "v" + s.version + ": " + (s.leaks ? s.leaks + " leak(s)" : "the build failed") + ". The log is below."; }
  log.hidden = !s.log || s.exit === 0; log.textContent = s.log || "";
  if (s.running) { setTimeout(function () { api("GET", "/api/shared-copy").then(copyShow).catch(function () { return null; }); }, 5000); }
}
document.addEventListener("click", function (ev) {
  var el = ev.target.closest("[data-sharedcopy]"); if (!el) { return; }
  closeMenus();
  api("GET", "/api/shared-copy").then(function (s) {
    $("copyVersion").value = s.running ? s.version : "";
    $("copyVersion").placeholder = s.version_now || s.version || "2.2.110126";
    $("copyNote").textContent = "";
    $("copyModal").hidden = false; $("copyVersion").focus();
    copyShow(s);
  }).catch(function (e) { alert(e.message); });
});
$("copyClose").addEventListener("click", function () { $("copyModal").hidden = true; });
$("copyCheck").addEventListener("click", function () {
  api("POST", "/api/shared-copy", { version: $("copyVersion").value.trim(), action: "check" }).then(copyShow)
    .catch(function (e) { $("copyNote").textContent = e.message; });
});
$("copyForm").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var v = $("copyVersion").value.trim();
  askConfirm("Ask Devin Cloud to build v" + v + " on a devin/ branch, show you the leak count and the checks, and open the PR after you type approved?",
    { title: "Build shared copy", ok: "Start" }).then(function (yes) {
    if (!yes) { return; }
    api("POST", "/api/shared-copy", { version: v, action: "pr" }).then(function (run) {
      $("copyModal").hidden = true;
      return loadRuns().then(function () { startedNote(run, "Shared copy build started"); });
    }).catch(function (e) { $("copyNote").textContent = e.message; });
  });
});
document.addEventListener("click", function (ev) {
  var el = ev.target.closest("[data-mkicon]"); if (!el) { return; }
  var b = el.querySelector("b");
  b.textContent = "Making the icon…";
  api("POST", "/api/desktop-icon", {}).then(function () { b.textContent = "Done: " + state.cfg.workbench_short + " is on your desktop"; },
    function (e) { b.textContent = e.message || "Could not make the icon"; });
});
document.addEventListener("click", function (ev) {
  var el = ev.target.closest("[data-checkupdate]"); if (!el) { return; }
  var b = el.querySelector("b");
  b.textContent = "Checking Bitbucket…";
  checkUpdate(true).then(function (u) {
    if (!u) { b.textContent = "Can't reach Argus program on this PC"; }
    else if (!u.ok) { b.textContent = u.why || "Could not check"; }
    else if (u.fetch_error) { b.textContent = "Could not reach Bitbucket: " + u.fetch_error; }
    else if (!u.behind) { b.textContent = "Up to date (" + u.head + ")"; }
    else if (u.why) { b.textContent = u.behind + " new, but not now: " + u.why; }
    else { b.textContent = u.behind + " new"; $("navUpdate").click(); }
  });
});
function waitForRestart(target, tries, from) {
  setTimeout(function () {
    api("GET", "/api/update").then(function (u) {
      if ((target ? u.head === target : u.head !== from) || tries <= 0) { location.reload(); } else { waitForRestart(target, tries - 1, from); }
    }).catch(function () { waitForRestart(target, tries - 1, from); });
  }, 2000);
}
$("navUpdate").addEventListener("click", function () {
  var u = state.update || {}, b = $("navUpdate");
  if (u.why) { alert(u.why); return; }
  askConfirm("Get the " + u.behind + " new commit(s) on " + u.branch + " and restart Argus? The page reloads by itself.", { title: "Update Argus", ok: "Update and restart" }).then(function (yes) {
  if (!yes) { return; }
  b.disabled = true; b.textContent = "Updating…";
  api("POST", "/api/update").then(function (r) {
    if (!r.updated) { b.disabled = false; checkUpdate(); return; }
    b.textContent = "Restarting…";
    waitForRestart(r.head, 30);
  }).catch(function (e) {
    if (e.offline) { b.textContent = "Restarting…"; return waitForRestart(null, 30, u.head); }
    b.disabled = false; alert(e.message); checkUpdate();
  });
  });
});

// ------------------------------------------------------------ screens and browser Back
// Each screen gets a history entry, so the browser's Back and Forward and the Back buttons move between screens.
function navPush(hash) {
  if (state.navPop || (location.hash || "") === hash) { return; }
  history.pushState({ wb: hash }, "", location.pathname + location.search + hash);
}
function navBack() {
  if (history.state && history.state.wb !== undefined) { history.back(); } else { goHome(); }
}
function goHome() {
  stopPolling(); closeMenus(); state.run = null; state.story = null; state.task = null;
  clearRight();
  renderStories(); renderTasks();
  ["storyView", "runView", "pcView", "backlogView", "autoView"].forEach(function (v) { $(v).hidden = true; });
  $("welcome").hidden = false; setSide("cloud");
  document.querySelector(".c-main").classList.remove("is-run");
  renderToday();
  navPush("");
}
// Back/Forward, and the first load of a link such as #story/ACME-1234 (Open in its own tab).
function routeHash() {
  var h = location.hash || "", m;
  state.navPop = true;
  try {
    if ((m = /^#story\/([A-Z]+-\d+)$/.exec(h))) {
      if (state.stories.some(function (s) { return s.key === m[1]; })) { showStory(m[1]); } else { goHome(); }
    } else if ((m = /^#run\/([a-f0-9]+)$/.exec(h))) { openRun(m[1]); }
    else if ((m = /^#backlog(?:\/([a-z]+))?$/.exec(h))) { if (m[1]) { openBlPane(m[1]); } else { showBacklog(); } }
    else if (h === "#pc") { showPc(); }
    else if (h === "#auto") { if (isAutomation()) { showAuto(); } else { goHome(); } }
    else if (!h) { goHome(); }
  } finally { state.navPop = false; }
}
window.addEventListener("popstate", routeHash);
document.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("[data-navback]")) { e.preventDefault(); navBack(); } });
$("brandHome").addEventListener("click", goHome);
$("brandHome").addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goHome(); } });
window.addEventListener("beforeunload", function (e) { if (blDraftsDirty()) { e.preventDefault(); e.returnValue = ""; } });

loadAbout();
checkUpdate();
every("update", 120000, checkUpdate, { hidden: 0 });
document.addEventListener("visibilitychange", function () { if (!document.hidden) { checkUpdate(); } });
every("ago", 30000, refreshAgo);
// Help bar at the bottom of the home page: says what the thing under the pointer (or keyboard focus) does.
var CTX_HELP = [
  ["#brandHome", "Home", "Comes back to this page from any screen."],
  ["#navUpdate", "Update", "A newer Argus is ready. Press it to update and restart."],
  ["#navPcNeed", "This PC", "Something on this PC still needs setting up before Test on my PC can run."],
  ["#navPc", "Test on my PC", "Check out a PR branch on this PC, test it with Devin Local, then hand the evidence back to the Cloud session."],
  ["#navBacklog", "Backlog", "Log hours; groom, point, play poker, move between sprints, clone, create from notes. Every change is shown as a preview first."],
  ["#navAuto", "Automation", "Set up, automate a ticket, run tags and triage failures in the test automation repo. Each step is a Devin Cloud session."],
  ["#exitBtn", "Exit", "Ends the Devin Cloud sessions you tick, then closes Argus on this PC."],
  ["#navDashboard", "Dashboard", "Your role's dashboard (/dashboard), opened in a new tab."],
  ["#menuTools", "My tools", "Starts single tasks. What it offers depends on your hat."],
  ["#drop-kb, [data-menubtn=\"kb\"]", "Knowledge base", "Starts single knowledge base tasks. What it offers depends on your hat."],
  ["#drop-approvals, [data-menubtn=\"approvals\"]", "Waiting on me", "Your inbox: questions from your runs, approvals, and the Jira Approval and Question sub-tasks assigned to you, and your Reminders (hours, one story at a time, idle stories, due dates)."],
  ["#drop-sessions, [data-menubtn=\"sessions\"]", "My sessions", "The Devin sessions you started from Argus. Pick one to see where it is."],
  ["#menuMe", "You", "Who you are, the look, What I sent today and settings. Ctrl+K finds a tool, ticket, session or person from anywhere."],
  ["#feedbackBtn", "Feedback", "Tell the leads what went wrong or what you would like. Argus adds the session details it already has, so you only say what happened."],
  ["#menuHelp, [data-menubtn=\"help\"]", "Help", "The user manual, the words used on this page, the tour and keyboard shortcuts."],
  ["#framedBar", "Its own tab", "Argus is inside the Devin page. Each run you start is a new Devin session and the Devin page switches to it. Open in its own tab keeps Argus where you are."],
  ["#healthDot", "Status", "Green: Jira and Devin Cloud both answer. Red: one is not working, and the bar under the top says which, with Retry. Grey: not checked yet."],
  ["[data-fold], .w-rail", "Fold", "Hides or shows this column."],
  ["[data-lefttab=\"tickets\"]", "My work", "Your Jira tickets. Pick one to see it and start SDLC."],
  ["[data-lefttab=\"tools\"], #toolList, #taskList", "What I do", "Your role's tasks. Each one opens a screen with buttons. Nothing changes in Jira until you read the preview and approve it."],
  ["#scope", "Which tickets", "Choose the list: yours this sprint, all yours, the team's sprint, all open, ready for QA or ready for UAT."],
  ["#filter", "Filter", "Type a key or words to narrow the list. Press / to jump here."],
  ["#storyList", "Tickets", "Pick a ticket to see its description and start SDLC on it."],
  ["#storySource", "Where the list comes from", "Read from Jira through Devin Cloud. Refresh from Jira reads it again."],
  ["#customToggle, #customForm, [data-focusnew]", "New requirement", "Type one or two sentences and press Start SDLC. Dry run makes no commits, PRs, Jira or Confluence writes. Leave Bring to local unticked: Devin Cloud tests the change after the PR."],
  ["[data-waitcheck]", "Check now", "Starts a short read-only Devin Cloud session that reads your Jira Approval and Question sub-tasks, about a minute."],
  ["[data-ctx=\"waiting\"]", "Waiting on you", "Questions from your runs, your Jira Approval and Question sub-tasks, and news from your runs. Pick one to open it; answering starts a sleeping session again."],
  ["[data-ctx=\"approve\"]", "To approve", "Gates waiting for your approval; one past its time limit is marked overdue. Documents to read, approve or forward appear on the right."],
  ["[data-ctx=\"sessions\"]", "Your sessions", "Each run is its own Devin session working in the background: intake → research → plan → implement → test → release → KB refresh. A session that goes to sleep does no harm; pressing Wake starts it again."],
  ["[data-ctx=\"tickets\"]", "Tickets", "The tickets in your list by status, and how many have no points, nobody assigned or no change for 5 days or more."],
  ["#right", "To approve · Documents", "Approvals for the open run, with its documents, diffs, PR, skills and chat. Documents to read, approve or forward appear here."]
];
function ctxHome() {
  return isBiz() ? ["Welcome to Argus", "Pick a task on the left. Each one opens a screen with buttons. Nothing changes in Jira until you read the preview and approve it, and every task your role does starts here. Point at anything to see what it does."]
    : ["Welcome to Argus", "Pick a ticket on the left, or type a new requirement and press Start SDLC. Each run is its own Devin session working in the background. Point at anything to see what it does."];
}
function ctxSet(el) {
  if (!$("ctxBar") || $("ctxBar").hidden) { return; }
  var hit = null;
  for (var n = el; n && n.nodeType === 1 && n.id !== "ctxBar" && !hit; n = n.parentElement) {
    hit = CTX_HELP.filter(function (c) { return n.matches(c[0]); })[0] || null;
  }
  if (el && el.closest && el.closest("#ctxBar")) { return; }
  var t = hit ? [hit[1], hit[2]] : ctxHome();
  if (t[0] === "Tickets" && isBiz()) { t = ["Sprint health", t[1]]; }
  $("ctxTitle").textContent = t[0]; $("ctxText").textContent = t[1];
}
function ctxSync() {
  if (!$("ctxBar") || !$("welcome")) { return; }
  var home = !$("welcome").hidden;
  $("ctxBar").hidden = !home || hintOff();
  document.querySelector(".c-main").classList.toggle("is-home", home);
  if (home) { ctxSet(null); }
}
document.addEventListener("mouseover", function (ev) { ctxSet(ev.target); });
document.addEventListener("focusin", function (ev) { ctxSet(ev.target); });
document.documentElement.addEventListener("mouseleave", function () { ctxSet(null); });
new MutationObserver(ctxSync).observe($("welcome"), { attributes: true, attributeFilter: ["hidden"] });
ctxSync();

// Team chat: "@name message" to anyone on the roster; it rides on the poker seats (no Devin agent wakes).
function alertList() { try { return JSON.parse(localStorage.getItem("sdlc-alerts") || "[]"); } catch (e) { return []; } }
function alertCount() { var el = $("nAlerts"); if (el) { var n = alertList().filter(function (a) { return !a.seen; }).length; el.hidden = !n; el.textContent = n; } }
// History at the foot of Waiting on me: what asked for you or replied earlier. Only items that need you are counted.
function alertsHtml() {
  var list = alertList();
  if (!list.length) { return ""; }
  return '<details class="w-gloss"><summary>History (' + list.length + ')</summary><button type="button" class="a-btn a-btn--outline w-sync" data-alertsclear="1">Clear</button>' +
    (list.map(function (a) { return '<div class="w-drop__item' + (a.seen ? "" : " is-new") + '"><b>' + esc(a.title) + "</b><span>" + esc(a.body) + '</span><span class="c-muted">' + esc(fmtDate(a.at)) + "</span></div>"; }).join("") ||
      "") + "</details>";
}
function alertsSeen() { localStorage.setItem("sdlc-alerts", JSON.stringify(alertList().map(function (a) { a.seen = true; return a; }))); alertCount(); }
// Reports and pages that are not Argus (the dashboard, links a tool opens) open in a panel on the right,
// so Argus stays in the same tab; the panel has its own "Open in a new tab".
function openPanel(url, title) {
  $("spTitle").textContent = title || ""; $("spNew").href = url; $("spFrame").src = url; $("sidePanel").hidden = false;
}
function closePanel() { $("sidePanel").hidden = true; $("spFrame").src = "about:blank"; }
document.addEventListener("click", function (ev) { if (ev.target.closest && ev.target.closest("[data-alertsclear]")) { localStorage.setItem("sdlc-alerts", "[]"); renderApprovals(); } });
alertCount();
// Stand-up: from the runs started since yesterday, the tickets in progress and anything waiting on you.
function standup() {
  var day = Date.now() / 1000 - 86400, runs = state.runs || [], mine = (state.stories || []).filter(function (s) { return /progress/i.test(s.status || ""); });
  var y = runs.filter(function (r) { return (r.created_at || 0) >= day; }).map(function (r) { return "- " + runKey(r) + ": " + r.story.summary + " (" + (r.status === "exit" ? "ended" : LABELS[r.stage] || r.status || "") + ")"; });
  var t = mine.map(function (s) { return "- " + s.key + ": " + s.summary; });
  var b = runs.filter(function (r) { return !r.closed_at && (r.pending_gate || r.pending_questions); }).map(function (r) { return "- " + runKey(r) + ": waiting for " + (r.pending_gate ? "approval " + r.pending_gate.id : "answers"); });
  var text = "Yesterday\n" + (y.join("\n") || "- (no Argus runs)") + "\n\nToday\n" + (t.join("\n") || "- (no tickets In Progress in this list)") + "\n\nBlockers\n" + (b.join("\n") || "- none");
  askConfirm(text, { title: "Stand-up summary", ok: "Copy", cancel: "Close" }).then(function (yes) { if (yes && navigator.clipboard) { navigator.clipboard.writeText(text); } });
}
// Pinned tickets stay at the top of My work.
function pins() { try { return JSON.parse(localStorage.getItem("sdlc-pins") || "[]"); } catch (e) { return []; } }
function togglePin(key) { var p = pins(), i = p.indexOf(key); if (i >= 0) { p.splice(i, 1); } else { p.unshift(key); } localStorage.setItem("sdlc-pins", JSON.stringify(p.slice(0, 20))); renderStories(); }
// The hint bar shows on the first five days Argus is used, until closed.
function hintOff() {
  if (localStorage.getItem("sdlc-hint-off") === "1") { return true; }
  var days = JSON.parse(localStorage.getItem("sdlc-hint-days") || "[]"), today = new Date().toISOString().slice(0, 10);
  if (days.indexOf(today) < 0) { days.push(today); localStorage.setItem("sdlc-hint-days", JSON.stringify(days.slice(-6))); }
  return days.length > 5;
}
$("ctxClose").addEventListener("click", function () { localStorage.setItem("sdlc-hint-off", "1"); if ($("ctxBar")) { $("ctxBar").hidden = true; } });
var tchat = { off: false, msgs: [], seen: null, open: false, shut: false, unread: 0, online: [] };
function tchatFirst(p) { var n = p.name || ""; return (n.indexOf(",") > 0 ? n.split(",")[1] : n.split(" ")[0]).trim().split(" ")[0]; }
function tchatHandle(p) {
  var f = tchatFirst(p), same = state.people.filter(function (x) { return tchatFirst(x).toLowerCase() === f.toLowerCase(); });
  return same.length === 1 && f ? f : p.jira_user;
}
function tchatFind(word) {
  var w = (word || "").toLowerCase();
  var hit = state.people.filter(function (p) { return p.jira_user.toLowerCase() === w; });
  return hit.length ? hit : state.people.filter(function (p) { return tchatFirst(p).toLowerCase() === w || (p.name || "").replace(/[^A-Za-z]/g, "").toLowerCase() === w; });
}
function tchatWho(u) { return u === "*" ? "everyone" : personName(u); }
function tchatRender() {
  var me = state.user, log = $("tchatLog");
  log.innerHTML = (tchat.msgs.map(function (m) {
    var mine = m.from === me, other = mine ? m.to : m.from, all = m.to === "*";
    return '<div class="w-tchat__msg' + (mine ? " w-tchat__msg--me" : "") + '" data-tchatto="' + esc(other) + '"><b>' +
      esc(mine ? "You → " + tchatWho(m.to) : personName(m.from) + (all ? " → everyone" : "")) + '</b> <span class="c-muted">' + fmtDate(m.at).slice(-5) + "</span><div>" + esc(m.text) + "</div></div>";
  }).join("") || '<div class="c-empty">No messages today. Type @ and a name, or @everyone, to start.</div>');
  log.hidden = !tchat.open; log.scrollTop = log.scrollHeight;
  if (tchat.open && !document.hidden) { tchat.unread = 0; }
  $("tchatToggle").textContent = tchat.unread ? "Chat (" + tchat.unread + ")" : "Chat";
  $("teamChat").classList.toggle("is-pill", !tchat.open && !$("tchatText").value && document.activeElement !== $("tchatText"));
  updateTitle();
}
document.addEventListener("visibilitychange", function () { if (!document.hidden && tchat.open && tchat.unread) { tchatRender(); } });
function tchatPoll() {
  if (tchat.off || !state.user) { return; }
  return api("GET", "/api/poker/chat?user=" + encodeURIComponent(state.user)).then(function (r) {
    $("teamChat").hidden = false;
    var fresh = (r.messages || []).filter(function (m) { return (m.to === state.user || (m.to === "*" && m.from !== state.user)) && tchat.seen && tchat.seen.indexOf(m.id) < 0; });
    tchat.msgs = r.messages || []; tchat.seen = tchat.msgs.map(function (m) { return m.id; });
    tchat.online = r.online || [];
    if (fresh.length) {
      if (tchat.shut || document.hidden) { tchat.unread += fresh.length; }
      if (!tchat.shut) { tchat.open = true; }
      fresh.forEach(function (m) { notify("tchat-" + m.id, "Team chat · " + personName(m.from), m.text, function () { tchat.open = true; tchat.shut = false; tchatRender(); $("tchatText").focus(); }); });
    }
    tchatRender();
  }, function (e) { if (e.status === 409) { tchat.off = true; $("teamChat").hidden = true; } });
}
function tchatSuggest() {
  var v = $("tchatText").value, m = /^@(\S*)$/.exec(v), box = $("tchatSuggest");
  if (!m) { box.hidden = true; return; }
  var w = m[1].toLowerCase(), list = state.people.filter(function (p) {
    return p.jira_user !== state.user && ((p.name || "").toLowerCase().indexOf(w) >= 0 || p.jira_user.toLowerCase().indexOf(w) === 0);
  }).sort(function (a, b) { return (tchat.online.indexOf(b.jira_user) >= 0) - (tchat.online.indexOf(a.jira_user) >= 0); }).slice(0, 8);
  var all = w && "everyone".indexOf(w) === 0, others = tchat.online.filter(function (u) { return u !== state.user; }).length;
  box.innerHTML = (all ? '<button type="button" data-tchatpick="everyone"><span class="w-dot' + (others ? "" : " w-dot--off") + '"></span>Everyone <span class="c-muted">everyone on the roster · ' + others + " online</span></button>" : "") + list.map(function (p) {
    var on = tchat.online.indexOf(p.jira_user) >= 0;
    return '<button type="button" data-tchatpick="' + esc(tchatHandle(p)) + '"><span class="w-dot' + (on ? "" : " w-dot--off") + '" title="' + (on ? "Argus open now" : "Argus not open") + '"></span>' +
      esc(p.name) + ' <span class="c-muted">' + esc(p.jira_user) + (on ? " · online" : "") + "</span></button>";
  }).join("");
  box.hidden = !list.length && !all;
}
function tchatSend() {
  var v = $("tchatText").value.trim(), m = /^@(\S+)\s+([\s\S]+)$/.exec(v), err = $("tchatErr");
  err.hidden = true;
  if (!m) { err.textContent = "Start with @ and a name, then the message."; err.hidden = false; return; }
  var who = m[1].toLowerCase() === "everyone" ? [{ jira_user: "everyone", name: "everyone" }] : tchatFind(m[1]);
  if (who.length !== 1) { err.textContent = who.length ? "More than one " + m[1] + ": " + who.map(function (p) { return p.name + " (@" + p.jira_user + ")"; }).join(", ") : "No one called " + m[1] + " on the roster."; err.hidden = false; return; }
  $("tchatSend").disabled = true;
  api("POST", "/api/poker/chat/send", { user: state.user, to: who[0].jira_user, text: m[2] }).then(function (r) {
    tchat.msgs = r.messages || []; tchat.seen = tchat.msgs.map(function (x) { return x.id; }); tchat.open = true;
    $("tchatText").value = "@" + (who[0].jira_user === "everyone" ? "everyone" : tchatHandle(who[0])) + " "; tchatRender();
  }, function (e) { err.textContent = e.message; err.hidden = false; }).then(function () { $("tchatSend").disabled = false; $("tchatText").focus(); });
}
$("tchatForm").addEventListener("submit", function (ev) { ev.preventDefault(); tchatSend(); });
$("tchatText").addEventListener("input", tchatSuggest);
$("tchatToggle").addEventListener("click", function () { tchat.open = !tchat.open; tchat.shut = !tchat.open; tchatRender(); });
$("teamChat").addEventListener("click", function (ev) {
  var t = ev.target.closest("[data-tchatpick]");
  if (t) { $("tchatText").value = "@" + t.dataset.tchatpick + " "; $("tchatSuggest").hidden = true; $("tchatText").focus(); return; }
  t = ev.target.closest("[data-tchatto]");
  if (t) { var p = state.people.filter(function (x) { return x.jira_user === t.dataset.tchatto; })[0]; $("tchatText").value = "@" + (p ? tchatHandle(p) : t.dataset.tchatto === "*" ? "everyone" : t.dataset.tchatto) + " "; $("tchatText").focus(); }
});
// The status light follows every Jira and Devin call the server makes; this only reads what it saw.
every("health", 30000, function () { return api("GET", "/api/health").then(showHealth, function () {}); }, { when: function () { return !!state.cfg; } });
every("tchat", 5000, tchatPoll, { hidden: 20000, when: function () { return !!state.cfg && !!state.user; } });
function framedRender(again) {
  if (again) { sessionStorage.removeItem("sdlc-framed-off"); }
  $("framedBar").hidden = !FRAMED || sessionStorage.getItem("sdlc-framed-off") === "1";
}
$("framedOpen").addEventListener("click", function () { this.href = location.href; });
$("framedClose").addEventListener("click", function () { sessionStorage.setItem("sdlc-framed-off", "1"); framedRender(); });
framedRender();
