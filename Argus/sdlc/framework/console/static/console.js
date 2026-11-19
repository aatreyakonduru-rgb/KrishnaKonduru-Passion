/* Argus — front end, helpers, menus, layout and the ticket list. Talks only to the local server's /api routes.
   The page loads console.js, console-run.js, console-pc.js, console-backlog.js and console-main.js in that
   order as plain scripts sharing one scope; console-main.js wires the page and starts it. */
"use strict";
var $ = function (id) { return document.getElementById(id); };
var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
var state = { cfg: {}, me: null, user: "", role: "", stories: [], runs: [], story: null, run: null, timer: null, rightTab: "artefacts", stageTab: null, stageTabPinned: false, people: [], prState: { prs: {}, pending: false, error: "", session_url: "" }, prTimer: null };
var THEMES = ["acme", "earth", "dark"];
var STAGES = ["intake", "research", "plan", "implement", "test", "release", "kb-refresh"];
var LABELS = { intake: "Intake", research: "Research", plan: "Plan", implement: "Implement", test: "Test", release: "Release", "kb-refresh": "KB refresh" };
var ALIASES = { pr: "implement", "pr-readiness": "implement", implementation: "implement", planning: "plan", eval: "test", testing: "test", qa: "test", kb: "kb-refresh", "kb refresh": "kb-refresh", kb_refresh: "kb-refresh", knowledge: "kb-refresh" };
// Roles whose Argus shows the Backlog tab (previews of Jira grooming writes). Routing, not permission.
var BACKLOG_ROLES = ["product_owner", "solution_lead", "lead", "bsa", "bsa_lead", "manager"];
// Screens that take the full width: both side columns fold to rails while they are open.
var WIDE_VIEWS = ["backlog"];
var CALENDAR_LENSES = ["po_office", "tech_lead", "scrum_master"];
var LAYOUT_DEFAULT = { list: "mine_sprint", left: "open", right: "open", right_width: 420 };
// Everyone logs hours from Argus, so the tab itself shows for every role; the grooming
// controls are still aimed at the roles above.
var BUSY = ["new", "claimed", "working", "running", "resumed", "resume_requested", "resume_requested_frontend", ""];
// A Jira ticket of this team's project (sdlc-profile.json jira.project, served in /api/config).
function isTicket(t) { var p = state.cfg.project; return !!p && new RegExp("^" + p + "-\\d+$").test(t || ""); }
function normStage(n) { n = String(n || "").toLowerCase().trim().replace(/\s+/g, " "); n = ALIASES[n] || n; return STAGES.indexOf(n) >= 0 ? n : null; }

// Inside the Devin page's Preview tab Argus is a frame, and that page switches to every new session Argus starts.
// Starting a run from there first opens Argus in its own tab, so the user stays on Argus.
var FRAMED = (function () { try { return window.self !== window.top; } catch (e) { return true; } })();
function keepArgus() {
  if (!FRAMED || keepArgus.done) { return; }
  keepArgus.done = !!window.open(location.href, "sdlc-argus");
}
function offline(on) { var b = $("offline"); if (b) { b.hidden = !on; } }
function api(method, url, body) {
  if (method === "POST" && /^\/api\/(runs|actions)$/.test(url)) { keepArgus(); }
  return fetch(url, { method: method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined })
    .then(function (r) { offline(false); return r; }, function () { offline(true); var e = new Error("Can't reach Argus program on this PC."); e.offline = true; throw e; })
    .then(function (r) { return r.json().then(function (j) { if (!r.ok) { var e = new Error(j.error || r.statusText); e.status = r.status; throw e; } return j; }); });
}
// Plain words for the errors seen most; the raw text stays one click away under Show details.
var ERR_PLAIN = [
  [/bridge is not running|the bridge does not run/i, "Devin Cloud isn't connected. The bar at the top says how to start it again."],
  [/Devin Cloud is reconnecting/, "Devin Cloud is reconnecting. Argus carries on when it is back."],
  [/Devin session tools:|Devin did not return a session id/, "Devin Cloud didn't finish that request. Try again in a minute."],
  [/Cannot reach api\.devin\.ai/, "Couldn't reach Devin Cloud just now. It usually comes back by itself."],
  [/\b403\b/, "Jira refused Argus's service account. Its token may be locked; ask whoever looks after the service account."],
  [/Jira (returned )?401/, "Jira did not accept Argus's service account sign-in."],
  [/\b401\b/, "The sign-in for Jira or Devin Cloud was not accepted."],
  [/Jira could not be reached|Cannot reach \S*jira/i, "Couldn't reach Jira just now. It is slow or down; it usually comes back by itself."],
  [/RemoteDisconnected|Remote end closed|timed out|Connection (refused|reset|aborted)|URLError|Name or service not known/i, "Couldn't reach Jira or Devin Cloud just now. It usually comes back by itself."]
];
function plainErr(msg) { msg = String(msg || ""); var hit = ERR_PLAIN.filter(function (x) { return x[0].test(msg); })[0]; return hit ? hit[1] : msg; }
function errHtml(msg, cls) {
  msg = String(msg || ""); var p = plainErr(msg);
  return '<div class="c-err' + (cls ? " " + cls : "") + '">' + esc(p) + (p !== msg ? '<details class="w-errmore"><summary>Show details</summary>' + esc(msg) + "</details>" : "") + "</div>";
}
function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
// The tab title carries what needs you and unread team chat, so a background tab still shows it.
var BASE_TITLE = document.title;
function updateTitle() {
  var n = (state.titleN || 0) + ((typeof tchat !== "undefined" && tchat.unread) || 0);
  document.title = (n ? "(" + n + ") " : "") + BASE_TITLE;
}
// One in-page dialog for every "are you sure": a title, one line, and buttons named after the action.
function askConfirm(text, opt) {
  opt = opt || {};
  return new Promise(function (resolve) {
    var box = $("askModal"), ok = $("askOk"), back = $("askCancel"), form = $("askForm"), prev = document.activeElement;
    $("askTitle").textContent = opt.title || "Are you sure?";
    $("askText").textContent = text;
    ok.textContent = opt.ok || "OK"; back.textContent = opt.cancel || "Cancel";
    ok.classList.toggle("a-btn--danger", !!opt.danger);
    function done(v) {
      box.hidden = true; form.onsubmit = null; back.onclick = null; box.onkeydown = null;
      if (prev && prev.focus) { prev.focus(); }
      resolve(v);
    }
    form.onsubmit = function (ev) { ev.preventDefault(); done(true); };
    back.onclick = function () { done(false); };
    box.onkeydown = function (ev) { if (ev.key === "Escape") { ev.stopPropagation(); done(false); } };
    box.hidden = false; (opt.danger ? back : ok).focus();
  });
}
// One clock for every background refresh. A job runs every `ms` while the page is in use, every
// `hidden` ms while the tab is in the background (0: not at all), and three times slower after ten
// minutes without a click or key. None of them reads Jira or starts a Devin Cloud session: they read
// what this PC already has. Jira lists are read only on first use, Refresh and Check now. A job that
// returns a promise is not run again until it settles (or two minutes pass), so slow answers never pile up.
var jobs = {};
function every(name, ms, fn, opt) {
  opt = opt || {};
  jobs[name] = { ms: ms, hidden: opt.hidden === undefined ? ms * 4 : opt.hidden, fn: fn, when: opt.when, last: Date.now() };
}
function stopJob(name) { delete jobs[name]; }
setInterval(function () {
  var now = Date.now(), idle = now - (state.lastActive || now) > 600000;
  Object.keys(jobs).forEach(function (k) {
    var j = jobs[k], gap = document.hidden ? j.hidden : j.ms * (idle ? 3 : 1);
    if (!gap || now - j.last < gap || (j.busy && now - j.busy < 120000) || (j.when && !j.when())) { return; }
    j.last = now;
    try {
      var r = j.fn();
      if (r && typeof r.then === "function") { j.busy = now; var done = function () { j.busy = 0; }; r.then(done, done); }
    } catch (e) { j.busy = 0; /* the next tick tries again */ }
  });
}, 1000);
// Replaces an element's HTML only when it changed, keeping its scroll position and the focused row.
function paint(el, html, keyAttr) {
  if (el._html === html) { return false; }
  var top = el.scrollTop, act = document.activeElement, key = keyAttr && act && el.contains(act) ? act.getAttribute(keyAttr) : null;
  el.innerHTML = html; el._html = html; el.scrollTop = top;
  if (key) { var again = el.querySelector("[" + keyAttr + '="' + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]'); if (again) { again.focus(); } }
  return true;
}
function fmtTime(t) { if (!t) { return ""; } var d = new Date(typeof t === "number" ? t * 1000 : t); return isNaN(d) ? "" : d.toTimeString().slice(0, 5); }
function fmtDate(t) { var d = new Date(t * 1000); return d.toLocaleDateString() + " " + d.toTimeString().slice(0, 5); }
// "updated 2 min ago" on lists that refresh in the background; [data-ago] spans are kept current by the "ago" job.
function ago(t) {
  var ms = typeof t === "number" ? (t < 1e12 ? t * 1000 : t) : Date.parse(t);
  if (!ms) { return ""; }
  var s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) { return "updated just now"; }
  if (s < 3600) { return "updated " + Math.floor(s / 60) + " min ago"; }
  if (s < 86400) { return "updated " + Math.floor(s / 3600) + " h ago"; }
  return "updated " + fmtDate(ms / 1000);
}
function agoFrom(t) { var s = Date.now() / 1000 - t; return s < 60 ? "from under a minute ago" : s < 86400 ? ago(t).replace(/^updated /, "from ") : "from " + fmtDate(t); }
function agoSpan(t) { return t ? '<span data-ago="' + esc(t) + '" title="' + esc(fmtTime(t)) + '">' + esc(ago(t)) + "</span>" : ""; }
function refreshAgo() {
  document.querySelectorAll("[data-ago]").forEach(function (el) { var v = el.dataset.ago; el.textContent = ago(isNaN(+v) ? v : +v); });
}
function runKey(r) { return r.jira_story ? r.jira_story.key : r.story.key; }
function asleep(run) { return /suspend/.test(run.status_detail || "") || /suspend/.test(run.status || ""); }
function runFinished(run) { return run.status === "finished" || run.status === "exit" || !!run.complete; }
function statusBadge(run) {
  var d = run.status_detail || run.status || "";
  var cls = "s-run";
  if (run.closed_at) { cls = "s-done"; d = "closed"; }
  else if (run.pending_gate) { cls = "s-wait"; d = "waiting for approval"; }
  else if (run.pending_questions) { cls = "s-wait"; d = "questions for you"; }
  else if (runFinished(run)) { cls = "s-done"; d = "finished"; }
  else if (asleep(run)) { cls = "s-sleep"; d = "asleep"; }
  else if (run.status === "blocked" || d === "blocked") { cls = "s-wait"; d = "waiting for you"; }
  else if (run.status === "error" || run.status === "expired") { cls = "s-bad"; d = run.status; }
  else if (/resume/.test(run.status || "")) { d = "waking up"; }
  else if (run.status === "new" || run.status === "claimed") { d = "starting"; }
  else { d = "working"; }
  return '<span class="a-badge ' + cls + '">' + esc(d) + "</span>";
}
function download(name, text) {
  var a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text || ""], { type: "text/plain;charset=utf-8" }));
  a.download = String(name || "artefact.txt").replace(/[^A-Za-z0-9._-]+/g, "_");
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
}
function gateDef(id) {
  var gates = state.cfg.gates || {};
  if (gates[id]) { return gates[id]; }
  var hit = null;
  Object.keys(gates).forEach(function (g) { if (!hit && id && (g.indexOf(id + "_") === 0 || id.indexOf(g) === 0)) { hit = gates[g]; } });
  return hit;
}

// ------------------------------------------------------------ who am I, menus, settings
function loadMe() {
  var q = "/api/me?user=" + encodeURIComponent(state.user) + (state.role ? "&role=" + encodeURIComponent(state.role) : "");
  return api("GET", q).then(function (me) { state.me = me; renderMe(); });
}
function renderMe() {
  var me = state.me, role = me.role;
  $("roleChip").textContent = role ? role.label : "no role";
  $("whoName").textContent = state.user ? personName(state.user) : "Who are you?";
  $("roleChip").classList.toggle("is-preview", !!me.previewing);
  renderAutoNav();
  var biz = isBiz();
  document.body.classList.toggle("is-business", biz);
  $("leftHead").textContent = biz ? "What I do" : "My work";
  $("leftHead").title = biz ? "Jira tickets and SDLC runs are not listed for this role; open a ticket from its Jira link." : "";
  if (hasTasks() && state.task && !allTasks().some(function (t) { return t.id === state.task; })) {
    state.task = null;
    if (bl) { bl.pane = "groom"; bl.part = ""; renderBlPane(); }
  }
  if (hasTasks()) { renderTasks(); }
  applyLeftTab();
  $("previewBar").hidden = !me.previewing;
  $("navBacklog").hidden = !role;
  $("navDashboard").hidden = !biz;  // the business layout hides My tools, where everyone else finds Dashboard
  $("navBacklog").textContent = wears(BACKLOG_ROLES) ? "Backlog" : "Log hours";
  $("scope").value = listFor(layoutOf());
  applyLayout();
  if (bl && bl.key && !$("backlogView").hidden) { blDetail(); }
  if (me.previewing) {
    $("previewBar").innerHTML = "Working as <b>" + esc(role.label) + "</b>. The ticket list, screens, menus, dashboard, gate checks and the Devin sessions you start follow this role. " +
      '<button type="button" class="a-btn a-btn--outline" data-setrole="">Back to my role</button>';
  }
  var TOP_TOOLS = 6;  // the first of the role's tools (role-routing default_skills order) shown before "All tools"
  function menuItem(it, id) {
    return '<button type="button" class="w-drop__item" data-skill="' + esc(it.skill) + '" data-menu="' + id + '" data-command="' + esc(it.command) + '"><b>' + esc(it.label) + "</b><span>" + esc(it.blurb) + "</span></button>";
  }
  function menuOf(id) { return role ? role.menus.filter(function (m) { return m.id === id; })[0] : null; }
  var tools = (menuOf("tools") || {}).items || [], screens = [];
  if (wears(BACKLOG_ROLES)) {
    screens.push('<button type="button" class="w-drop__item" data-blpane="create"><b>New epic or story</b><span>Paste or drop notes; the title, description and numbered acceptance criteria are drafted and checked against the rule book</span></button>');
  }
  if (role && (role.lenses || [role.lens]).some(function (l) { return CALENDAR_LENSES.indexOf(l) >= 0; })) {
    screens.push('<button type="button" class="w-drop__item" data-blpane="plan"><b>Plan the sprint</b><span>Capacity against velocity, what to pull in from the backlog, what to push out, load per person, stories to split</span></button>');
    screens.push('<button type="button" class="w-drop__item" data-blpane="calendar"><b>Sprint calendar</b><span>Sprint dates, the active sprint, points committed against velocity, and release dates</span></button>');
    screens.push('<button type="button" class="w-drop__item" data-blpane="followups"><b>Scrum Master follow-ups</b><span>Who is off which day (saved to the Sprint Leave page) and the capacity it leaves; stories in progress side by side, not moving, or waiting on a question; missing AI labels, estimates, sub-tasks and hours; anyone over their capacity</span></button>');
  }
  var mainTools = tools.filter(function (it) { return SELF_HELP.indexOf(it.skill) < 0; }), helpTools = tools.filter(function (it) { return SELF_HELP.indexOf(it.skill) >= 0; });
  var rest = mainTools.slice(TOP_TOOLS).map(function (it) { return menuItem(it, "tools"); }).join("") +
    (screens.length ? '<div class="w-drop__head">On the Backlog screen</div>' + screens.join("") : "") +
    (helpTools.length ? '<div class="w-drop__head">About you and this Argus</div>' + helpTools.map(function (it) { return menuItem(it, "tools"); }).join("") : "");
  var restCount = Math.max(0, mainTools.length - TOP_TOOLS) + screens.length + helpTools.length;
  var toolsHtml = '<div class="w-drop__head">Start</div>' +
    '<button type="button" class="w-drop__item" data-focusnew="1"><b>Start SDLC on a new requirement</b><span>Type one or two sentences and start the full SDLC</span></button>' +
    (role ? '<button type="button" class="w-drop__item" data-openactions="1"><b>Answer, approve, hand over, change config</b><span>Every action in one panel on the right: questions, approvals, Jira and session handovers, observations, skill, role, gate and Argus config</span></button>' : "") +
    (mainTools.length ? '<div class="w-drop__head">' + ((role.hat_ids || []).length > 1 ? "For your roles" : "For a " + esc(role.label)) + "</div>" + mainTools.slice(0, TOP_TOOLS).map(function (it) { return menuItem(it, "tools"); }).join("") +
      (restCount ? '<button type="button" class="w-drop__item w-drop__all" data-alltools="1"><b>All tools (' + restCount + ' more)</b><span>Or type in the box above to find any tool</span></button><div id="moreTools" hidden>' + rest + "</div>" : "") :
      (!role ? '<div class="c-empty">Pick who you are (top right) to see your tools.</div>' : ""));
  $("drop-tools").innerHTML = '<div class="w-drop__search"><input type="search" id="toolSearch" class="a-input" placeholder="Find a tool (Ctrl+K)…" aria-label="Find a tool" autocomplete="off"></div>' +
    '<div id="toolItems">' + toolsHtml + '</div><div class="c-empty" id="toolNone" hidden>No tool matches.</div>';
  $("toolList").innerHTML = toolsHtml.replace(/<button[^>]*data-alltools[^>]*>[\s\S]*?<\/button>/, "").replace(' id="moreTools" hidden', "");
  var kb = (menuOf("kb") || {}).items || [], groups = [];
  kb.forEach(function (it) { if (groups.indexOf(it.group) < 0) { groups.push(it.group); } });
  $("drop-kb").innerHTML = groups.map(function (g) {
    return '<div class="w-drop__head">' + esc(g) + "</div>" + kb.filter(function (it) { return it.group === g; }).map(function (it) { return menuItem(it, "kb"); }).join("");
  }).join("") || '<div class="c-empty">Pick who you are (top right) to see your menu.</div>';
  $("drop-kb").innerHTML += '<div class="w-drop__head">Reference</div><button type="button" class="w-drop__item" data-kbpage="delivery-teams"><b>Delivery teams</b>' +
    "<span>The other delivery teams in the programme: what each one builds, its Jira IT Team and board, sprint cycle and contacts</span></button>";
  $("drop-help").innerHTML = '<div class="w-drop__head">Help</div><form class="w-drop__search" id="helpSearch"><input type="search" class="a-input" id="helpQ" placeholder="Search the manual…" aria-label="Search the manual"></form><button type="button" class="w-drop__item" data-docs="1"><b>Documentation</b>' +
    "<span>Argus user manual: setup, Test on my PC, Return to Cloud, wrap-up, approvals and troubleshooting</span></button>" +
    '<details class="w-gloss"><summary>Words used on this page</summary><dl>' + GLOSSARY.map(function (g) { return "<dt>" + esc(g[0]) + "</dt><dd>" + esc(g[1]) + "</dd>"; }).join("") + "</dl></details>" +
    '<button type="button" class="w-drop__item" data-tour="1"><b>Take the tour</b><span>Five steps around this page</span></button>' +
    '<button type="button" class="w-drop__item" data-keys="1"><b>Keyboard shortcuts</b><span>Ctrl+K quick search, / to filter, arrows and Enter in lists, ? for the list</span></button>' +
    '<div id="helpAbout">' + aboutHtml() + "</div>";
  var mine = me.hats.map(function (h) { return h.id; });
  $("drop-settings").innerHTML = (state.cfg.pc && state.cfg.pc.windows ? '<div class="w-drop__head">This PC</div><button type="button" class="w-drop__item" data-mkicon="1"><b>Create desktop icon</b>' +
    "<span>Puts a " + esc(state.cfg.workbench_short) + " icon on your desktop. It starts Argus as you and opens this page</span></button>" : "") +
    '<div class="w-drop__head w-dev-only">Trace</div><button type="button" class="w-drop__item w-dev-only" data-tracefloat="open"><b>Open the trace window</b>' +
    "<span>What the open run loaded and decided — agents, skills, rules, knowledge-base files hit or skipped, matrix chains, ontology and link-graph lookups, drift checks, KB sync, evidence, tests picked, contract checks, gates — in a window you can move aside, minimise or close</span></button>" +
    '<div class="w-drop__head">Argus updates</div><button type="button" class="w-drop__item" data-checkupdate="1"><b>Check for updates now</b>' +
    "<span>Ask Bitbucket now instead of waiting for the next check, and update if there is something new</span></button>" +
    (state.cfg.can_build_copy ? '<button type="button" class="w-drop__item" data-sharedcopy="1"><b>Build shared copy</b>' +
      "<span>The framework copy for other teams: check it here, then have Devin Cloud build it and open the PR</span></button>" : "") +
    '<div class="w-drop__head">Desktop notifications</div><button type="button" class="w-drop__item" data-notify="1"><b>' + notifyLabel() +
    "</b><span>A pop-up from Windows when Devin Local needs you, Devin Cloud replies, or an Argus update is ready, while this page is in the background</span></button>" +
    '<details class="w-gloss w-viewas"><summary>View Argus as another role</summary>' +
    '<button type="button" class="w-drop__item' + (!me.previewing ? " is-on" : "") + '" data-setrole=""><b>My own role</b><span>' + esc(me.hats.length ? me.hats.map(function (h) { return h.label; }).join(", ") : "not on the roster yet") + "</span></button>" +
    me.all_roles.map(function (r) {
      var on = role && role.id === r.id && me.previewing;
      return '<button type="button" class="w-drop__item w-drop__item--row' + (on ? " is-on" : "") + '" data-setrole="' + esc(r.id) + '"><b>' + esc(r.label) + "</b>" + (mine.indexOf(r.id) >= 0 ? '<span class="a-chip">yours</span>' : "") + "</button>";
    }).join("") + '<div class="c-muted w-drop__foot">The whole Argus works as the role you pick: ticket list, screens, menus, dashboard, gate checks and the sessions you start.</div></details>';
}
// Tools about the person and Argus itself go last in My tools, under their own heading.
var SELF_HELP = ["identify-requester", "help", "catalogue", "onboarding-guide", "roster-sync", "roster-check", "learn-more"];
var GLOSSARY = [
  ["Run", "One piece of work Devin Cloud does for you in its own session: an SDLC run on a ticket or requirement, or one tool from a menu."],
  ["Start SDLC", "Starts a run that goes intake, research, plan, implement, test, release and KB refresh, stopping at each approval."],
  ["Approval (gate)", "A check between stages that a named person approves, approves with notes or rejects. Shown under To approve."],
  ["Waiting on me", "Approvals and questions for you: the ones from your runs, and the Jira Approval and Question sub-tasks assigned to you."],
  ["Dry run", "Devin Cloud does the work but writes nothing: no commits, PRs, Jira or Confluence changes."],
  ["Bring to local", "Leave it unticked: Devin Cloud tests the change after the PR."],
  ["Preview", "Exactly what would be sent to Jira, shown before anything is written."]
];
// Everyone except PO, BSA and Scrum Master: the left column switches between tickets and the role's tools.
function applyLeftTab() {
  var tab = isBiz() ? "tickets" : (localStorage.getItem("sdlc-lefttab") || "tickets");
  document.querySelector(".c-left").classList.toggle("is-tools", tab === "tools");
  $("toolList").hidden = tab !== "tools";
  $("taskList").hidden = !(isBiz() || (hasTasks() && tab === "tools"));
  document.querySelectorAll("[data-lefttab]").forEach(function (b) { var on = b.dataset.lefttab === tab; b.classList.toggle("is-active", on); b.setAttribute("aria-selected", on ? "true" : "false"); });
}
function filterTools(q) {
  q = String(q || "").trim().toLowerCase();
  var box = $("toolItems"), shown = 0, head = null, headHas = false;
  if (!box) { return; }
  var more = $("moreTools"), items = [];
  Array.prototype.forEach.call(box.children, function (el) {
    if (el === more) { Array.prototype.forEach.call(more.children, function (m) { items.push(m); }); } else { items.push(el); }
  });
  if (more) { more.hidden = !q && !more.dataset.open; }
  items.forEach(function (el) {
    if (el.classList.contains("w-drop__head")) { if (head) { head.hidden = !headHas; } head = el; headHas = false; return; }
    if (el.dataset.alltools) { el.hidden = !!q || !!(more && more.dataset.open); return; }
    var hay = (el.textContent + " " + (el.dataset.command || "")).toLowerCase();
    var hit = !q || hay.indexOf(q) >= 0;
    el.hidden = !hit; if (hit) { shown += 1; headHas = true; }
  });
  if (head) { head.hidden = !headHas; }
  if ($("toolNone")) { $("toolNone").hidden = shown > 0; }
}
// PO, BSA and Scrum Master: the "What I do" list from business-screens.json instead of tickets and SDLC runs.
// Someone who also wears a delivery hat keeps the tickets and SDLC controls and gets the list under What I do.
function isBiz() { var r = state.me && state.me.role; return !!(r && r.business && !r.delivery); }
function hasTasks() { var r = state.me && state.me.role; return !!(r && r.business); }
function wears(ids) { var r = state.me && state.me.role; return !!r && (r.hat_ids || [r.id]).some(function (h) { return ids.indexOf(h) >= 0; }); }
function allTasks() {
  var out = []; ((state.me && state.me.role && state.me.role.tasks) || []).forEach(function (g) { out = out.concat(g.tasks); });
  return out;
}
function renderTasks() {
  $("taskList").innerHTML = ((state.me && state.me.role && state.me.role.tasks) || []).map(function (g) {
    return '<div class="w-taskgroup">' + esc(g.group) + "</div>" + g.tasks.map(function (t) {
      return '<button type="button" class="c-item w-task' + (state.task === t.id ? " is-active" : "") + '" data-wbtask="' + esc(t.id) + '">' +
        '<div class="c-item__sum">' + esc(t.label) + '</div><div class="c-item__sub"><span>' + esc(t.what || "") + "</span></div></button>";
    }).join("");
  }).join("");
}
function openWbTask(id) {
  var t = allTasks().filter(function (x) { return x.id === id; })[0]; if (!t) { return; }
  state.task = id; renderTasks(); closeMenus();
  if (t.pane) {
    openBlPane(t.pane, t.part);
    bl.taskFilter = t.filter || null;
    if (t.filter) { bl.filter = t.filter; $("blFilter").value = t.filter; if (bl.data) { blRenderList(); } }
  } else if (t.action) { openActionItem(t.action); }
  else if (t.menu) { toggleMenu(t.menu); }
}
function openHashTask() {
  var m = /(?:^|[#&])task=([a-z0-9-]+)/.exec(location.hash || "");
  if (m && hasTasks()) { openWbTask(m[1]); }
}
// Who the page acts as: the person picked under Me and the role picked under View Argus as.
function asMe(body) { body.user = state.user; if (state.role) { body.role = state.role; } return body; }
// A new role opens on that role's ticket list and screens, as if its owner had opened Argus.
function setRole(id) {
  state.role = id; localStorage.setItem("sdlc-role-preview", id);
  var scope = $("scope").value, view = currentView();
  closeMenus(); loadMe().then(function () {
    localStorage.removeItem("sdlc-scope-" + lensId());
    $("scope").value = listFor(layoutOf());
    leaveScreensNotForRole(view);
    if ($("scope").value !== scope) { loadStories(); }
    if (state.run && state.run.messages) { renderRun(state.run, false); }
  });
}
// A new person brings their own roles with them.
function setUser(u) {
  state.user = u; localStorage.setItem("sdlc-jira-me", u); localStorage.setItem("sdlc-jira-me-start", state.cfg.default_jira_user || "");
  state.role = ""; localStorage.removeItem("sdlc-role-preview");
  var view = currentView();
  loadMe().then(function () { $("scope").value = listFor(layoutOf()); leaveScreensNotForRole(view); loadStories(); }, loadStories); syncRuns(); loadWaiting();
}
// Screens the new person or role does not have go back to Home.
function leaveScreensNotForRole(view) {
  if ((view === "auto" && !isAutomation()) || (view === "backlog" && !state.me.role)) { goHome(); }
}

// ------------------------------------------------------------ screen layout per role (role-routing.yaml workbench_layouts)
function layoutOf() { return (state.me && state.me.role && state.me.role.layout) || LAYOUT_DEFAULT; }
function lensId() { return (state.me && state.me.role && state.me.role.lens) || "none"; }
// The ticket list a role opens on, unless this person picked another one for that role on this PC.
function listFor(lay) {
  var want = localStorage.getItem("sdlc-scope-" + lensId()) || lay.list || LAYOUT_DEFAULT.list;
  return !state.user && /^(mine|automation$)/.test(want) ? "sprint" : want;
}
function currentView() { return ["backlog", "pc", "run", "story", "auto"].filter(function (v) { var el = $(v + "View"); return el && !el.hidden; })[0] || "welcome"; }
function sideState(side, lay, view) {
  if (side === "left" && isBiz()) { return "open"; }
  if (view === "pc" && side === "right") { return "open"; }
  if (WIDE_VIEWS.indexOf(view) >= 0) { return state.wideOpen && state.wideOpen[side] ? "open" : "rail"; }
  // The work in the middle gets the room: To approve and the documents fold to a rail when there is
  // nothing in them, and on screens up to 1200 px wide, unless a gate is waiting or you opened them.
  if (side === "right") {
    if (state.rightOpen === true || state.rightOpen === false) { return state.rightOpen ? "open" : "rail"; }
    if (!$("gateCard").hidden) { return "open"; }
    if (NARROW.matches || view === "welcome" || view === "story") { return "rail"; }
  }
  var saved = localStorage.getItem("sdlc-layout-" + lensId() + "-" + side);
  if (saved === "open" || saved === "rail") { return saved; }
  if (lay[side] === "auto") { return view === "run" ? "open" : "rail"; }
  return lay[side] === "rail" ? "rail" : "open";
}
function applyLayout() {
  var lay = layoutOf(), view = currentView(), cols = document.querySelector(".w-cols");
  cols.dataset.view = view;
  cols.dataset.left = sideState("left", lay, view);
  cols.dataset.right = sideState("right", lay, view);
  cols.style.setProperty("--w-right-open", (lay.right_width || LAYOUT_DEFAULT.right_width) + "px");
}
function toggleSide(side) {
  var cols = document.querySelector(".w-cols"), next = cols.dataset[side] === "rail" ? "open" : "rail";
  if (WIDE_VIEWS.indexOf(cols.dataset.view) >= 0) { state.wideOpen = state.wideOpen || {}; state.wideOpen[side] = next === "open"; }
  else { localStorage.setItem("sdlc-layout-" + lensId() + "-" + side, next); if (side === "right") { state.rightOpen = next === "open"; } }
  applyLayout();
}
var NARROW = window.matchMedia ? window.matchMedia("(max-width: 1200px)") : { matches: false };
if (NARROW.addEventListener) { NARROW.addEventListener("change", function () { applyLayout(); }); }
function closeMenus() {
  document.querySelectorAll(".w-drop").forEach(function (d) { d.hidden = true; });
  document.querySelectorAll("[data-menubtn]").forEach(function (b) { b.classList.remove("is-open"); b.setAttribute("aria-expanded", "false"); });
}
function setNav(open) {
  document.querySelector(".w-top").classList.toggle("is-navopen", open);
  $("navToggle").setAttribute("aria-expanded", open ? "true" : "false");
}
function toggleMenu(id) {
  var d = $("drop-" + id), open = d.hidden;
  closeMenus();
  if (open) {
    d.hidden = false;
    var mb = document.querySelector('[data-menubtn="' + id + '"]'); mb.classList.add("is-open"); mb.setAttribute("aria-expanded", "true");
    if (id === "tools" && !$("toolDash") && $("toolItems")) {
      $("toolItems").insertAdjacentHTML("afterbegin", '<div class="w-drop__head">See</div><button type="button" class="w-drop__item" id="toolDash" data-opendash="1"><b>Dashboard</b><span>Your role\'s dashboard, read only, in the panel on the right</span></button>' +
        '<button type="button" class="w-drop__item" data-standup="1"><b>Stand-up summary</b><span>Yesterday, today and blockers from your tickets and runs, ready to copy</span></button>');
    }
    if (id === "tools" && $("toolSearch")) { $("toolSearch").value = ""; filterTools(""); $("toolSearch").focus(); }
  }
  if (id === "approvals") { renderApprovals(); }
  if (id === "sessions") { renderSessions(); loadPrs(); }
  if (id === "approvals") { alertsSeen(); }
}

// ------------------------------------------------------------ menu actions
var pendingSkill = null;
// Every menu item asks first (Start / Cancel), then opens its run in this page.
// Menu items and chats go into the person's assistant session for the day; SDLC runs get their own.
function openAction(skill) {
  var all = [];
  (state.me.role ? state.me.role.menus : []).forEach(function (m) { all = all.concat(m.items); });
  var it = all.filter(function (x) { return x.skill === skill; })[0]; if (!it) { return; }
  openActionItem(it);
}
function openActionItem(it) {
  closeMenus();
  if (it.opens) {
    openPanel(it.opens, it.label);
    return;
  }
  var need = it.input || { required: false, hint: "", choices: [] };
  pendingSkill = it;
  $("amTitle").textContent = it.label; $("amBlurb").textContent = it.blurb; $("amCmd").textContent = it.command;
  $("amNeed").textContent = need.hint; $("amDry").checked = !it.read_only;
  $("amAsk").hidden = !need.required && !need.hint; $("amText").hidden = $("amAsk").hidden;
  $("amOptional").hidden = need.required;
  $("amChoices").hidden = !need.choices.length;
  $("amChoices").innerHTML = need.choices.map(function (c) { return '<button type="button" class="a-btn a-btn--outline" data-choice="' + esc(c) + '">' + esc(c) + "</button>"; }).join("");
  $("amText").value = need.choices.length ? "" : (state.story ? state.story.key : "");
  $("amErr").hidden = true; $("actionModal").hidden = false;
  if ($("amText").hidden) { $("amStart").focus(); } else { $("amText").focus(); }
}
function startAction(it, text, dryRun, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Starting…"; }
  return api("POST", "/api/actions", asMe({ skill: it.skill, text: text, dry_run: dryRun }))
    .then(function (run) {
      $("actionModal").hidden = true;
      return loadRuns().then(function () {
        if (run.reused) { startedNote(run, it.label + ": already answered", "The same request was run at " + fmtTime(run.created_at) + ", so nothing new was started. See it shows that answer."); }
        else { startedNote(run, it.label + " started", "It works in its own Devin session in the background. You stay here; its answer comes to you in Argus (Alerts on the top bar, and My sessions)."); }
      });
    })
    .catch(function (e) {
      if ($("actionModal").hidden) { if (!e.offline) { alert(it.command + ": " + e.message); } } else { $("amErr").textContent = e.message; $("amErr").hidden = false; }
    })
    .then(function () { if (btn) { btn.disabled = false; btn.textContent = "Start"; } });
}
$("amChoices").addEventListener("click", function (ev) {
  var b = ev.target.closest("[data-choice]"); if (!b) { return; }
  $("amText").value = b.dataset.choice;
  this.querySelectorAll(".a-btn").forEach(function (x) { x.classList.toggle("is-on", x === b); });
});
$("amCancel").addEventListener("click", function () { $("actionModal").hidden = true; });
$("actionForm").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var text = $("amText").value.trim();
  if (!text && !(pendingSkill.input || {}).required) { startAction(pendingSkill, "", $("amDry").checked, $("amStart")); return; }
  if (!text) { $("amErr").textContent = "This one needs " + ($("amNeed").textContent || "some input") + "."; $("amErr").hidden = false; $("amText").focus(); return; }
  startAction(pendingSkill, text, $("amDry").checked, $("amStart"));
});

// ------------------------------------------------------------ dashboard
var DASH_WAIT = "<!doctype html><title>Dashboard</title><style>" +
  "body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;color:#3b2a63;background:#f6f4fb}" +
  ".s{width:22px;height:22px;border:3px solid #d9d2ec;border-top-color:#5b3fa0;border-radius:50%;animation:r 0.9s linear infinite;margin-right:12px}" +
  "@keyframes r{to{transform:rotate(360deg)}}div{display:flex;align-items:center;font-size:16px}#t{color:#8a80a3;margin-left:8px;font-variant-numeric:tabular-nums}" +
  "</style><div><span class='s'></span>Building dashboard<span id='t'></span></div>" +
  "<script>var t0=Date.now();setInterval(function(){var s=Math.round((Date.now()-t0)/1000);" +
  "document.getElementById('t').textContent=s<60?s+'s':Math.floor(s/60)+'m '+(s%60)+'s';},1000);<\/script>";
$("navDashboard").addEventListener("click", function () {
  closeMenus();
  openPanel("about:blank", "Dashboard (read only)");
  $("spFrame").srcdoc = DASH_WAIT;
  openDashboard(null, true);
});
// Links from outside (the Beyond the ticket deck) open <Argus address>/?open=dashboard: http://127.0.0.1:8787 on a PC,
// the session's preview link in Devin Cloud.
document.addEventListener("submit", function (ev) {
  if (ev.target.id !== "helpSearch") { return; }
  ev.preventDefault(); var q = $("helpQ").value.trim(); if (!q) { return; }
  var docs = document.querySelector("[data-docs]"); state.helpQuery = q; if (docs) { docs.click(); }
});
// The actions page: the dashboard's tabs with Generate and Save, in the side panel. The dashboard itself only reads.
function openActions() {
  closeMenus();
  openPanel("about:blank", "Answer, approve, hand over, config"); $("spFrame").srcdoc = DASH_WAIT.replace("Building dashboard", "Loading your actions");
  api("POST", "/api/dashboard", { user: state.user, role: state.role, actions: true })
    .then(function (j) { $("spFrame").removeAttribute("srcdoc"); openPanel(j.url + "?t=" + Date.now(), "Answer, approve, hand over, config"); })
    .catch(function (e) { $("spFrame").srcdoc = "<pre style='padding:24px;white-space:pre-wrap'>" + esc(e.message) + "</pre>"; });
}
function openDashboard(win, inPanel) {
  localStorage.setItem("sdlc-dash-opened", "1");
  var btn = $("navDashboard");
  btn.disabled = true; btn.textContent = "Dashboard…";
  api("POST", "/api/dashboard", { user: state.user, role: state.role })
    .then(function (j) { var u = j.url + "?t=" + Date.now(); if (inPanel) { $("spFrame").removeAttribute("srcdoc"); openPanel(u, "Dashboard (read only)"); } else if (win) { win.location = u; } else { window.location = j.url; } })
    .catch(function (e) { if (inPanel) { $("spFrame").srcdoc = "<pre style='padding:24px;white-space:pre-wrap'>" + esc(e.message) + "</pre>"; } else if (win) { win.document.body.innerHTML = "<pre style='padding:24px;white-space:pre-wrap'>" + esc(e.message) + "</pre>"; } else if (!e.offline) { alert(e.message); } })
    .then(function () { btn.disabled = false; btn.textContent = "Dashboard"; });
}

// ------------------------------------------------------------ left column
function loadStories(refresh) {
  if (!state.stories.length) { $("storyList").innerHTML = '<div class="c-empty">Loading tickets…</div>'; }
  state.storiesErr = "";
  clearTimeout(state.storiesTimer);
  var scope = $("scope").value;
  api("GET", "/api/stories?scope=" + scope + "&user=" + encodeURIComponent(state.user) + (refresh === true ? "&refresh=1" : "")).then(function (j) {
    if ($("scope").value !== scope) { return; }
    state.stories = j.stories || []; state.storiesErr = j.error || ""; state.storiesAsOf = j.stale ? j.fetched_at : 0;
    if (state.stories.length && !j.stale) { try { localStorage.setItem("sdlc-stories-" + scope, JSON.stringify({ at: j.fetched_at || Date.now() / 1000, stories: state.stories })); } catch (e) { /* full */ } }
    else if (state.storiesErr && !state.stories.length) { storiesFromCache(scope); } if (!$("pcView").hidden) { pcTicketChoices(); }
    renderStories(); renderStorySource(j);
    if (!state.hashRouted && (state.stories.length || !j.pending)) { state.hashRouted = true; if (location.hash && !$("welcome").hidden) { routeHash(); } }
    if (j.pending || j.refreshing) { state.storiesTimer = setTimeout(loadStories, 10000); }
  }).catch(function (e) { state.storiesErr = e.message; storiesFromCache(scope); renderStories(); $("storySource").textContent = ""; });
}
// When Jira can't be read, the list keeps the last copy this browser saw, marked with its time.
function storiesFromCache(scope) {
  var c = null; try { c = JSON.parse(localStorage.getItem("sdlc-stories-" + scope) || "null"); } catch (e) { c = null; }
  if (c && (c.stories || []).length) { state.stories = c.stories; state.storiesAsOf = c.at; } else { state.stories = []; state.storiesAsOf = 0; }
}
// The bar under the top bar carries an outage; a panel only says it in grey.
function jiraDown() { var bar = $("healthBar"); return !!bar && !bar.hidden && /Jira/.test(bar.textContent); }
function outageHtml(msg) {
  return jiraDown() ? '<div class="c-empty">Jira isn\'t reachable right now.</div>' : errHtml(msg, "c-empty");
}
function renderStorySource(j) {
  if (j.stale) { $("storySource").innerHTML = "Jira didn't answer, so this is the last list read from it, " + agoFrom(j.fetched_at) + '. <a href="#" data-storyrefresh="1">Try Jira again</a>'; return; }
  if (j.source !== "cloud") { $("storySource").innerHTML = "Read from Jira, " + agoSpan(j.fetched_at || Date.now() / 1000) + "." + (j.refreshing ? " Checking Jira for changes\u2026" : ""); return; }
  var when = j.fetched_at ? "From Jira through Devin Cloud, " + agoSpan(j.fetched_at) + ". " : "";
  $("storySource").innerHTML = when + (j.pending ? "Devin Cloud is reading Jira for this list (about a minute)… " +
    (j.session_url ? '<a href="' + esc(j.session_url) + '" target="_blank">session</a>' : "") :
    '<a href="#" data-storyrefresh="1">Refresh from Jira</a>');
}
function renderStories() {
  var f = $("filter").value.trim().toLowerCase();
  var runsByKey = {};
  state.runs.forEach(function (r) { if (!runsByKey[r.story.key]) { runsByKey[r.story.key] = r; } });
  var pinned = (typeof pins === "function") ? pins() : [];
  var html = state.stories.slice().sort(function (a, b) { return (pinned.indexOf(b.key) >= 0) - (pinned.indexOf(a.key) >= 0); }).filter(function (s) { return !f || (s.key + " " + s.summary + " " + s.assignee).toLowerCase().indexOf(f) >= 0; })
    .map(function (s) {
      var r = runsByKey[s.key];
      return '<button class="c-item' + (state.story && state.story.key === s.key ? " is-active" : "") + '" data-key="' + esc(s.key) + '">' +
        '<div class="c-item__top"><span class="c-item__key">' + esc(s.key) + "</span><span>" + esc(s.status) + ' <span class="w-pin' + (pinned.indexOf(s.key) >= 0 ? " is-on" : "") + '" data-pin="' + esc(s.key) + '" title="Pin to the top of My work" role="button" tabindex="0">\u2605</span></span></div>' +
        '<div class="c-item__sum">' + esc(s.summary) + "</div>" +
        '<div class="c-item__sub"><span>' + esc(s.type) + "</span>" + (s.points ? "<span>" + esc(s.points) + " pts</span>" : "") + (s.sprint ? "<span>" + esc(s.sprint) + "</span>" : "") + "</div>" +
        (r ? '<div class="c-item__run">' + statusBadge(r) + ' <span class="c-muted">' + esc(LABELS[r.stage] || r.stage || "") + " · " + (r.dry_run ? "dry run" : "live") + "</span></div>" : "") +
        "</button>";
    }).join("");
  if (html && state.storiesAsOf) { html = '<div class="w-asof">Jira not reachable. Showing the list ' + esc(agoFrom(state.storiesAsOf)) + "</div>" + html; }
  paint($("storyList"), html || (state.storiesErr ? outageHtml(state.storiesErr) : '<div class="c-empty">No tickets match.</div>'), "data-key");
  renderToday();
}
function loadRuns() { return api("GET", "/api/runs").then(applyRuns); }
// One call for the background refresh: the runs list and, while Test on my PC is not open, the PC tests.
function loadStatus() {
  return api("GET", "/api/status").then(function (j) { applyRuns(j.runs); if ($("pcView").hidden) { applyPc(j.pc); } }).catch(function () {});
}
function applyRuns(j) {
  {
    state.runs = j; state.runsLoaded = true; state.runsAt = Date.now() / 1000;
    if (state.run && !$("runView").hidden) { markRunSeen(state.run.id, true); }
    var seen = state.replySeen;
    state.replySeen = {};
    j.forEach(function (r) {
      var ev = r.last_reply && r.last_reply.event_id;
      state.replySeen[r.id] = ev;
      if (seen && ev && seen[r.id] !== ev) {
        var why = r.closed ? "" : r.pending_gate ? "Approval needed · " : r.pending_questions ? "Question for you · " : "";
        if (why) { notify("reply-" + r.id + "-" + ev, why + runKey(r), noTrace(r.last_reply.text), function () { openRun(r.id); }); }
        else { logAlert("reply-" + r.id + "-" + ev, "Devin Cloud replied · " + runKey(r), noTrace(r.last_reply.text)); }
      }
    });
    $("nSessions").textContent = j.filter(function (r) { return !r.archived; }).length;
    setApprovalCount();
    renderStories(); renderStoryRuns();
    if (!$("drop-sessions").hidden) { renderSessions(); }
    if (!$("drop-approvals").hidden) { renderApprovals(); }
  }
}
function syncRuns() {
  return api("POST", "/api/sync", { user: state.user }).then(loadRuns).catch(function () { return loadRuns(); });
}
function runRow(r, extra) {
  return '<button type="button" class="w-drop__item w-run" data-run="' + r.id + '"><b>' + esc(runKey(r)) + " " + statusBadge(r) + (r.archived ? ' <span class="c-pill">archived</span>' : "") + "</b>" +
    "<span>" + esc(r.story.summary) + prBadges(r) + "</span><span class=\"c-muted\">" + (extra || ((r.kind === "chat" ? "chat" : (r.kind === "action" ? "menu action" : "SDLC · " + esc(LABELS[r.stage] || r.stage || "")) + " · " + (r.dry_run ? "dry run" : "live")) + " · " + fmtDate(r.created_at)) + (r.acus ? " · " + r.acus + " ACU" : "")) + "</span></button>";
}
// PR state comes from a short Devin Cloud session (no Bitbucket token on the PC), only when asked for.
function prNum(url) { var m = /\/pull-requests\/(\d+)/.exec(url || ""); return m ? m[1] : ""; }
function prBadge(url) {
  var n = prNum(url); if (!n) { return ""; }
  var s = state.prState.prs[n], st = s ? s.state : "not checked";
  return ' <span class="c-pill w-prs w-prs--' + esc(st.replace(/ /g, "-")) + '" title="' + esc(s ? (s.from ? s.from + " → " + s.to + ", " : "") + "checked " + fmtDate(s.checked_at) : "Click Check PR state to ask Devin Cloud") + '">PR #' + esc(n) + " " + esc(st) + "</span>";
}
function prBadges(r) { return (r.pull_requests || []).map(function (p) { return prBadge(p.pr_url); }).join(""); }
function prHead() {
  var ps = state.prState, has = state.runs.some(function (r) { return (r.pull_requests || []).some(function (p) { return prNum(p.pr_url); }); });
  if (!has) { return ""; }
  return '<div class="w-prs__head">' + (ps.pending
    ? '<span class="c-muted">Devin Cloud is checking the pull requests' + (ps.session_url ? ' (<a target="_blank" href="' + esc(ps.session_url) + '">session</a>)' : "") + "…</span>"
    : '<button type="button" class="a-btn a-btn--outline w-sync" data-prcheck="1" title="Starts a short read-only Devin Cloud session that looks up each PR in Bitbucket, about a minute">Check PR state</button>') +
    (ps.error ? ' <span class="c-err">' + esc(ps.error) + "</span>" : "") + "</div>";
}
function loadPrs() {
  return api("GET", "/api/prs").then(function (j) {
    state.prState = j;
    if (j.pending && !state.prTimer) { state.prTimer = setTimeout(function () { state.prTimer = null; loadPrs(); }, 8000); }
    if (!$("drop-sessions").hidden) { renderSessions(); }
    if (state.run && !$("runView").hidden) { renderPrPane(state.run); }
  }).catch(function () {});
}
function checkPrs(btn) {
  btn.disabled = true; btn.textContent = "Asking Devin Cloud…";
  api("POST", "/api/prs/refresh", {}).then(function (j) { state.prState = j; loadPrs(); })
    .catch(function (e) { if (!e.offline) { state.prState.error = e.message; } if (!$("drop-sessions").hidden) { renderSessions(); } });
}
var SESS_FILTERS = [["", "All"], ["needs", "Needs you"], ["running", "Running"], ["finished", "Finished"]];
function sessMatch(r) {
  var f = state.sessFilter || "", q = (state.sessQ || "").toLowerCase(), done = DONE_STATES.indexOf(r.status) >= 0;
  var ok = !f || (f === "needs" ? !r.closed_at && !!(r.pending_gate || r.pending_questions) : f === "running" ? !done && !r.closed_at : done || !!r.closed_at);
  return ok && (!q || (runKey(r) + " " + r.story.summary + " " + (r.status || "")).toLowerCase().indexOf(q) >= 0);
}
// Cost this week, and the sessions that could be ended: finished, or asleep for more than a day.
function sessCost() {
  var week = Date.now() / 1000 - 7 * 86400, acu = 0, ended = [], idle = 0;
  state.runs.forEach(function (r) {
    if ((r.created_at || 0) >= week) { acu += +r.acus || 0; }
    if (r.closed_at || r.archived) { return; }
    if (DONE_STATES.indexOf(r.status) >= 0) { ended.push(r.id); }
    else if (asleep(r) && Date.now() / 1000 - (r.created_at || 0) > 86400 && !r.pending_gate && !r.pending_questions) { idle += 1; ended.push(r.id); }
  });
  return '<div class="w-sessf"><span class="c-muted">This week: ' + (Math.round(acu * 10) / 10) + " ACU</span>" +
    (ended.length ? ' <button type="button" class="a-btn a-btn--outline w-sync" data-closeruns="' + ended.join(",") + '">Close ' + plural(ended.length, "finished or idle session") + "</button>" : "") +
    (idle ? ' <span class="c-muted">' + plural(idle, "session") + " asleep for over a day</span>" : "") + "</div>";
}
document.addEventListener("click", function (ev) {
  var b = ev.target.closest && ev.target.closest("[data-closeruns]"); if (!b) { return; }
  var ids = b.dataset.closeruns.split(",");
  askConfirm("These Devin sessions end for good; their run records stay in Argus.", { title: "Close " + plural(ids.length, "session") + "?", ok: "Close them" }).then(function (yes) {
    if (!yes) { return; }
    b.disabled = true;
    Promise.all(ids.map(function (id) { return api("POST", "/api/runs/" + id + "/close", {}).catch(function () { return null; }); })).then(loadRuns).then(renderSessions);
  });
});
function sessFilters() {
  return sessCost() + '<div class="w-sessf">' + SESS_FILTERS.map(function (x) { return '<button type="button" class="c-pill' + ((state.sessFilter || "") === x[0] ? " is-on" : "") + '" data-sessf="' + x[0] + '">' + x[1] + "</button>"; }).join("") +
    '<input id="sessQ" class="a-input" type="search" placeholder="Find a run…" value="' + esc(state.sessQ || "") + '" aria-label="Find a run"></div>';
}
document.addEventListener("input", function (ev) { if (ev.target.id === "sessQ") { state.sessQ = ev.target.value; state.sessQFocus = true; renderSessions(); state.sessQFocus = false; } });
function renderSessions() {
  var arch = state.runs.filter(function (r) { return r.archived; }).length;
  $("drop-sessions").innerHTML = '<div class="w-drop__head"><span>Your runs ' + agoSpan(state.runsAt) + '</span><span class="w-drop__btns"><button type="button" class="a-btn a-btn--outline w-sync" data-sync="1">Reload from Devin</button>' +
    (arch ? ' <button type="button" class="a-btn a-btn--outline w-sync" data-showarch="1">' + (state.showArchived ? "Hide archived" : "Show archived (" + arch + ")") + "</button>" : "") + "</span></div>" + prHead() +
    sessFilters() +
    (state.runs.filter(function (r) { return (state.showArchived || !r.archived) && sessMatch(r); }).map(function (r) { return runRow(r); }).join("") || '<div class="c-empty">No runs match.</div>');
  var q = $("sessQ"); if (q && state.sessQFocus) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
function renderPrPane(run) {
  var pr = run.pr, prs = run.pull_requests || [];
  $("panePr").innerHTML = (pr ? '<dl class="c-kv"><dt>Branch</dt><dd>' + esc(pr.branch) + "</dd><dt>Status</dt><dd>" + esc(pr.detail) + '</dd></dl><pre class="a-pre">' + esc(pr.body) + "</pre>" : "") +
    (prs.length ? '<div class="c-h">Pull requests on the session</div>' + prs.map(function (p) { return '<div><a target="_blank" href="' + esc(p.pr_url) + '">' + esc(p.pr_url) + "</a>" + prBadge(p.pr_url) + "</div>"; }).join("") : "") ||
    '<div class="c-empty">' + (run.dry_run ? "Dry run: the PR title, description and branch will be shown here as text instead of a real PR." : "PR details appear here once the implement stage opens one.") + "</div>";
}
// Session updates for the inbox: a run that finished, failed, fell asleep or got a Cloud reply since you last opened it.
var DONE_STATES = ["finished", "exit", "error", "expired"];
function runSig(r) { return (r.status || "") + "|" + (asleep(r) ? "asleep" : "") + "|" + ((r.last_reply && r.last_reply.event_id) || ""); }
function seenRuns() {
  if (state.seenRuns || !state.runsLoaded) { return state.seenRuns; }
  var seen = null;
  try { seen = JSON.parse(localStorage.getItem("sdlc-seen-runs") || "null"); } catch (e) { seen = null; }
  if (!seen) { seen = {}; state.runs.forEach(function (r) { seen[r.id] = runSig(r); }); localStorage.setItem("sdlc-seen-runs", JSON.stringify(seen)); }
  state.seenRuns = seen;
  return seen;
}
function runNews(r) {
  if (DONE_STATES.indexOf(r.status) >= 0) { return r.status === "finished" ? "session finished" : "session ended: " + r.status; }
  if (asleep(r)) { return "session asleep: answer, approve or Wake to start it again"; }
  var said = r.last_reply ? noTrace(r.last_reply.text) : "";
  return r.last_reply && r.last_reply.event_id ? "Devin Cloud replied" + (said ? ": " + said.slice(0, 90) : "") : "";
}
function runUpdates() {
  var seen = seenRuns(); if (!seen) { return []; }
  return state.runs.filter(function (r) { return !r.archived && runNews(r) && seen[r.id] !== runSig(r); });
}
function markRunSeen(id, quiet) {
  var seen = seenRuns(), r = state.runs.filter(function (x) { return x.id === id; })[0];
  if (!seen || !r || seen[id] === runSig(r)) { return; }
  seen[id] = runSig(r); localStorage.setItem("sdlc-seen-runs", JSON.stringify(seen));
  if (!quiet) { setApprovalCount(); }
}
function markAllSeen() {
  var seen = seenRuns(); if (!seen) { return; }
  state.runs.forEach(function (r) { seen[r.id] = runSig(r); });
  localStorage.setItem("sdlc-seen-runs", JSON.stringify(seen)); setApprovalCount();
  if (!$("drop-approvals").hidden) { renderApprovals(); }
}
function updatesHtml() {
  var ups = runUpdates();
  return '<div class="w-drop__head">Session updates' + (ups.length ? ' <button type="button" class="a-btn a-btn--outline w-sync" data-seenall="1">Mark all read</button>' : "") + "</div>" +
    (ups.map(function (r) { return runRow(r, esc(runNews(r))); }).join("") || '<div class="c-empty">No new session updates.</div>');
}
// Hours a gate has waited past its timeout_hours in approval-gates.yaml; 0 while it is still in time.
function gateOverdue(r) {
  var g = r.pending_gate, d = g ? gateDef(g.id) : null, h = +(d && d.timeout_hours) || 0;
  if (!g || !h || !g.at) { return 0; }
  var t = typeof g.at === "number" ? g.at * 1000 : Date.parse(g.at), over = (Date.now() - t) / 3600000 - h;
  return t && over > 0 ? Math.ceil(over) : 0;
}
function renderApprovals() {
  var waiting = state.runs.filter(function (r) { return !r.closed_at && (r.pending_gate || r.pending_questions); });
  var fwd = [];
  state.runs.forEach(function (r) { (r.forwarded || []).forEach(function (f) { fwd.push({ r: r, f: f }); }); });
  $("drop-approvals").innerHTML = '<div class="w-drop__head">Waiting on you</div>' + '<button type="button" class="w-drop__item" data-openactions="1"><b>Answer, approve, hand over, change config</b><span>Every action in one panel on the right: questions, approvals, Jira and session handovers, observations, skill, role, gate and Argus config</span></button>' +
    (waiting.map(function (r) {
      var g = r.pending_gate, d = g ? gateDef(g.id) : null;
      return runRow(r, g ? "sign " + esc(g.id) + (d ? " — " + esc(d.name) : "") : plural(r.pending_questions.items.length, "question") + " to answer");
    }).join("") || '<div class="c-empty">Nothing waiting on you.</div>') +
    (fwd.length ? '<div class="w-drop__head">Forwarded</div>' + fwd.map(function (x) { return runRow(x.r, esc(x.f.gate) + " → " + esc(personName(x.f.person)) + " · " + fmtDate(x.f.at)); }).join("") : "") +
    waitingHtml() + nudgesHtml() + updatesHtml() + alertsHtml();
}
// Approval and Question sub-tasks assigned to me in Jira. Devin Cloud reads them once and keeps
// the list until Check now; answers and decisions go back through Cloud too.
function taskKind(s) { return (s.labels || []).indexOf("Approval") >= 0 ? "Approval" : "Question"; }
function waitingOpen() {
  var rp = state.replies || {};
  return ((state.waiting || {}).stories || []).filter(function (s) { return !rp[s.key] || rp[s.key].state !== "done"; });
}
// A dash until Jira has been read once, so an unchecked list never reads as "nothing to do".
function setApprovalCount() {
  var w = state.waiting || {}, el = $("nApprovals");
  var n = (state.runs || []).filter(function (r) { return !r.closed_at && (r.pending_gate || r.pending_questions); }).length + waitingOpen().length + nudgesOpen().length;
  if (w.pending && !n) { el.textContent = "…"; el.title = "Devin Cloud is reading Jira"; }
  else if (!w.fetched_at && !n) { el.textContent = "–"; el.title = "Jira not checked yet: open Waiting on me and press Check now"; }
  else { el.textContent = n; el.title = w.fetched_at ? "Jira checked " + fmtDate(w.fetched_at) : ""; }
  state.titleN = n; updateTitle();
  var gates = (state.runs || []).filter(function (r) { return !r.closed_at && r.pending_gate; }).length, rail = $("railApprove");
  if (rail) { rail.hidden = !gates; rail.textContent = gates; }
  renderToday();
}
// The landing screen per role: what is waiting on you, what to approve, your sessions and sprint health.
function renderToday() {
  var el = $("today"); if (!el || $("welcome").hidden) { return; }
  var act = document.activeElement; if (act && act.closest && act.closest(".w-quickans")) { return; }
  var runs = state.runs || [], w = state.waiting || {}, biz = isBiz();
  var asks = runs.filter(function (r) { return !r.closed_at && r.pending_questions; }), gates = runs.filter(function (r) { return !r.closed_at && r.pending_gate; });
  var jira = waitingOpen(), ups = runUpdates(), nudges = nudgesOpen();
  var live = runs.filter(function (r) { return !r.archived && !r.closed_at && DONE_STATES.indexOf(r.status) < 0; });
  function row(r, note, extra) {
    return '<button type="button" class="c-item w-today__row" data-run="' + esc(r.id) + '"><span class="c-item__key">' + esc(runKey(r)) + "</span> " + statusBadge(r) + (extra || "") +
      '<div class="c-item__sum">' + esc(note || r.story.summary) + "</div></button>";
  }
  var wait = asks.slice(0, 4).map(function (r) { return row(r, plural(r.pending_questions.items.length, "question") + " to answer") + quickAnswer(r); }).join("") +
    (jira.length ? '<button type="button" class="c-item w-today__row" data-menubtn="approvals"><b>' + jira.length + " in Jira</b><div class=\"c-item__sum\">Approval and Question sub-tasks assigned to you</div></button>" : "") +
    (nudges.length ? '<button type="button" class="c-item w-today__row" data-menubtn="approvals"><b>' + nudges.length + (nudges.length === 1 ? " reminder" : " reminders") + '</b><div class="c-item__sum">' + esc(nudges[0].text) + "</div></button>" : "") +
    (!w.fetched_at && state.user ? '<div class="c-muted">Jira approvals and questions: not checked yet. <button type="button" class="a-btn a-btn--outline w-sync" data-waitcheck="1" title="Starts a short read-only Devin Cloud session, about a minute">Check now</button></div>' : "");
  var nWait = asks.length + jira.length + nudges.length, over = gates.filter(gateOverdue).length;
  var cards = [
    '<section class="w-today__card" data-ctx="waiting"><h2>Waiting on you <span class="c-count">' + (nWait || (w.fetched_at ? 0 : "–")) + "</span></h2>" + (wait || '<div class="c-muted">Nothing waiting on you.</div>') + "</section>",
    '<section class="w-today__card" data-ctx="approve"><h2>To approve <span class="c-count">' + gates.length + "</span>" + (over ? ' <span class="w-today__over">' + over + " overdue</span>" : "") + "</h2>" +
      (gates.slice(0, 5).map(function (r) {
        var g = r.pending_gate, d = gateDef(g.id), late = gateOverdue(r);
        return row(r, "approve " + g.id + (d && d.name ? " — " + d.name : ""), late ? ' <span class="w-today__over">overdue ' + late + " h</span>" : "");
      }).join("") || '<div class="c-muted">No approval waiting.</div>') + "</section>",
    '<section class="w-today__card" data-ctx="sessions"><h2>Your sessions <span class="c-count">' + live.length + "</span></h2>" +
      (live.slice(0, 5).map(function (r) { return row(r); }).join("") || '<div class="c-muted">No sessions running.</div>') +
      (live.length > 5 ? '<button type="button" class="a-btn a-btn--outline w-sync" data-menubtn="sessions">All ' + live.length + "</button>" : "") +
      (ups.length ? '<div class="w-today__sub">Since you last looked <button type="button" class="a-btn a-btn--outline w-sync" data-seenall="1">Mark all read</button></div>' + ups.slice(0, 4).map(function (r) { return row(r, runNews(r)); }).join("") : "") + "</section>"
  ];
  var list = (state.stories || []).length ? state.stories : ((bl.data || {}).stories || []);
  if (list.length || !biz) {
    var counts = {}, noPts = 0, idle = 0, nobody = 0, week = Date.now() - 5 * 86400000;
    list.forEach(function (s) {
      counts[s.status] = (counts[s.status] || 0) + 1;
      if (!parseFloat(s.points)) { noPts += 1; }
      if (!s.assignee || s.assignee === "Unassigned") { nobody += 1; }
      if (s.updated && Date.parse(s.updated) < week) { idle += 1; }
    });
    var scopeOpt = $("scope").selectedOptions[0];
    var health = [[noPts, "with no points"], [nobody, "with nobody assigned"], [idle, "with no change for 5 days or more"]]
      .filter(function (x) { return x[0]; }).map(function (x) { return "<li><b>" + x[0] + "</b> " + x[1] + "</li>"; }).join("");
    cards.push('<section class="w-today__card" data-ctx="tickets"><h2>' + esc(biz ? "Sprint health" : (scopeOpt ? scopeOpt.text : "Tickets")) + ' <span class="c-count">' + list.length + "</span></h2>" +
      (Object.keys(counts).length ? '<div class="w-today__counts">' + Object.keys(counts).sort().map(function (k) { return '<span class="c-pill">' + esc(k) + " " + counts[k] + "</span>"; }).join("") + "</div>" : (state.storiesErr ? '<div class="c-muted">Jira isn\'t reachable right now.</div>' : '<div class="c-muted">No tickets in this list.</div>')) +
      (health ? '<ul class="w-today__health">' + health + "</ul>" : "") +
      (biz ? "" : '<div class="c-muted">Pick one on the left to see it and start SDLC.</div><button type="button" class="a-btn a-btn--outline" data-focusnew="1">+ New requirement</button>') + "</section>");
  }
  var need = nWait + gates.length, oldest = 0;
  gates.forEach(function (r) { var a = r.pending_gate.at, t = typeof a === "number" ? a : Date.parse(a) / 1000; if (t && (!oldest || t < oldest)) { oldest = t; } });
  var sum = '<p class="w-today__sum">' + (need ? "<b>" + plural(need, "thing") + " need" + (need === 1 ? "s" : "") + " you</b>" : "Nothing needs you right now") +
    (oldest ? " · oldest approval asked " + esc(ago(oldest).replace(/^updated /, "")) : "") + (!w.fetched_at && state.user ? " · Jira not checked yet" : "") + "</p>";
  var h = (state.cfg && state.cfg.integrations) || {}, ran = runs.some(function (r) { return r.dry_run; });
  var steps = [[!!state.user, "Pick who you are (menu under your name)"], [!!(h.jira && h.jira.connected), "Jira answers (green status light)"], [ran, "Start one dry run on a ticket"], [!!localStorage.getItem("sdlc-dash-opened"), "Open your Dashboard (My tools)"]];
  var check = localStorage.getItem("sdlc-checklist-off") === "1" || steps.every(function (x) { return x[0]; }) ? "" :
    '<section class="w-today__card w-firstday" data-ctx="checklist"><h2>Getting started</h2><ul class="w-check">' + steps.map(function (x) { return '<li class="' + (x[0] ? "is-done" : "") + '">' + (x[0] ? "\u2713 " : "\u25cb ") + esc(x[1]) + "</li>"; }).join("") +
      '</ul><button type="button" class="a-btn a-btn--outline w-sync" data-checkdone="1">Hide this</button></section>';
  paint(el, sum + check + cards.join(""));
}
// Answer a run's questions on its card; the draft survives the page refreshing the card.
function quickAnswer(r) {
  var q = r.pending_questions, open = state.quickOpen === r.id, draft = (state.quickDraft || {})[r.id] || {};
  return '<button type="button" class="a-btn a-btn--outline w-sync" data-quickans="' + esc(r.id) + '">' + (open ? "Hide" : "Answer here") + "</button>" +
    (open ? '<div class="w-quickans" data-quickform="' + esc(r.id) + '">' + q.items.map(function (it) {
      return "<label><b>" + esc(it.n) + ".</b> " + esc(it.text) + '</label><textarea class="a-input" rows="2" data-qn="' + esc(it.n) + '">' + esc(draft[it.n] || "") + "</textarea>";
    }).join("") + '<div><button type="button" class="a-btn a-btn--primary w-sync" data-quicksend="' + esc(r.id) + '">Send answers</button></div><div data-quickerr="' + esc(r.id) + '"></div></div>' : "");
}
document.addEventListener("input", function (ev) {
  var t = ev.target, box = t.closest && t.closest("[data-quickform]"); if (!box || !t.dataset.qn) { return; }
  state.quickDraft = state.quickDraft || {}; (state.quickDraft[box.dataset.quickform] = state.quickDraft[box.dataset.quickform] || {})[t.dataset.qn] = t.value;
});
document.addEventListener("click", function (ev) {
  var b = ev.target.closest && ev.target.closest("[data-quickans]");
  if (b) {
    state.quickOpen = state.quickOpen === b.dataset.quickans ? "" : b.dataset.quickans; renderToday();
    var first = document.querySelector('[data-quickform="' + b.dataset.quickans + '"] textarea'); if (first) { first.focus(); }
    return;
  }
  b = ev.target.closest && ev.target.closest("[data-quicksend]"); if (!b) { return; }
  var id = b.dataset.quicksend, draft = (state.quickDraft || {})[id] || {};
  var answers = Object.keys(draft).filter(function (n) { return draft[n].trim(); }).map(function (n) { return { n: parseInt(n, 10), text: draft[n] }; });
  if (!answers.length) { return; }
  b.disabled = true; b.textContent = "Sending…";
  api("POST", "/api/runs/" + id + "/answers", { answers: answers }).then(function () {
    delete state.quickDraft[id]; state.quickOpen = ""; return loadRuns();
  }).catch(function (e) {
    b.disabled = false; b.textContent = "Send answers";
    var err = document.querySelector('[data-quickerr="' + id + '"]'); if (err) { err.innerHTML = errHtml(e.message); }
  });
});
function loadWaiting(refresh) {
  var user = state.user;
  loadNudges(refresh === true);
  if (!user) { state.waiting = { stories: [] }; setApprovalCount(); return Promise.resolve(); }
  return Promise.all([
    api("GET", "/api/stories?scope=waiting&user=" + encodeURIComponent(user) + (refresh === true ? "&refresh=1" : "")),
    api("GET", "/api/waiting/replies")
  ]).then(function (res) {
    if (user !== state.user) { return; }
    var w = res[0], seenKey = "sdlc-waiting-seen-" + user, seen = JSON.parse(localStorage.getItem(seenKey) || "[]");
    state.waiting = w; state.replies = res[1].replies || {};
    if (w.fetched_at) {
      (w.stories || []).forEach(function (s) {
        if (seen.indexOf(s.key) < 0) { notify("task-" + s.key, (taskKind(s) === "Approval" ? "Approval waiting on you · " : "Question for you · ") + s.key, s.summary, function () { toggleMenu("approvals"); }); }
      });
      localStorage.setItem(seenKey, JSON.stringify((w.stories || []).map(function (s) { return s.key; })));
    }
    setApprovalCount();
    if (!$("drop-approvals").hidden) { renderApprovals(); }
    var rp = state.replies, busy = w.pending || Object.keys(rp).some(function (k) { return rp[k].state === "sending"; });
    if (busy && !state.waitTimer) { state.waitTimer = setTimeout(function () { state.waitTimer = null; loadWaiting(); }, 8000); }
  }).catch(function () {});
}
// Reminders: this person's gaps in the active sprint (hours, one story at a time, idle, due date), read with the
// Jira service account once a day. Dismiss hides one until tomorrow.
function nudgeDismissKey() { return "sdlc-nudge-dismissed-" + state.user + "-" + new Date().toISOString().slice(0, 10); }
function nudgesOpen() {
  var n = state.nudges || {}, gone = JSON.parse(localStorage.getItem(nudgeDismissKey()) || "[]");
  return (n.items || []).filter(function (i) { return gone.indexOf(i.id) < 0; });
}
function loadNudges(refresh) {
  var user = state.user;
  if (!user) { state.nudges = { items: [] }; return; }
  api("GET", "/api/waiting/nudges?user=" + encodeURIComponent(user) + (refresh ? "&refresh=1" : "")).then(function (n) {
    if (user !== state.user) { return; }
    state.nudges = n; setApprovalCount();
    if (!$("drop-approvals").hidden) { renderApprovals(); }
  }).catch(function () {});
}
function dismissNudge(id) {
  var k = nudgeDismissKey(), gone = JSON.parse(localStorage.getItem(k) || "[]");
  if (gone.indexOf(id) < 0) { gone.push(id); }
  localStorage.setItem(k, JSON.stringify(gone));
  setApprovalCount(); renderApprovals();
}
function nudgesHtml() {
  var n = state.nudges || {};
  if (!state.user || (!n.available && !n.note)) { return ""; }
  var head = '<div class="w-drop__head">Reminders' + (n.sprint ? " · " + esc(n.sprint) : "") + "</div>";
  if (!n.available) { return head + (/could not be read/.test(n.note || "") ? errHtml(n.note) : '<div class="c-muted">' + esc(n.note) + "</div>"); }
  var items = nudgesOpen().map(function (i) {
    var url = (n.browse || "") + encodeURIComponent(i.key), field = "";
    if (i.answer === "due") { field = '<input type="date" data-nudgeval="' + esc(i.id) + '" aria-label="Due date for ' + esc(i.key) + '">'; }
    else if (i.answer === "note") { field = '<input type="text" data-nudgeval="' + esc(i.id) + '" placeholder="Close it, or what is left" aria-label="Answer for ' + esc(i.key) + '">'; }
    return '<div class="w-drop__item w-task" data-nudge="' + esc(i.id) + '"><b>' + esc(i.text) + "</b>" +
      (i.summary ? "<span>" + esc(i.summary) + "</span>" : "") + '<span class="c-muted">' + esc(i.detail || "") + "</span>" +
      "<span>" + field + (field ? ' <button type="button" class="a-btn a-btn--outline w-sync" data-nudgeanswer="' + esc(i.id) + '" data-key="' + esc(i.key) + '" data-kind="' + esc(i.answer) + '" title="' + (n.writes ? "Writes the answer on the ticket in Jira" : "Shows the Jira change; Backlog writes are off on this Argus") + '">Send</button>' : "") +
      ' <a class="a-btn a-btn--outline w-sync" target="_blank" href="' + esc(url) + '">Open in Jira</a>' +
      ' <button type="button" class="a-btn a-btn--outline w-sync" data-nudgedismiss="' + esc(i.id) + '">Dismiss for today</button></span>' +
      '<span class="c-muted" data-nudgenote="' + esc(i.id) + '"></span></div>';
  }).join("");
  var failed = /could not be read/.test(n.note || "");
  return head + (items || (failed ? "" : '<div class="c-empty">No reminders: your sprint tickets are up to date.</div>')) + (n.note ? (failed ? errHtml(n.note) : '<div class="c-muted">' + esc(n.note) + "</div>") : "");
}
function answerNudge(b) {
  var id = b.dataset.nudgeanswer, box = document.querySelector('[data-nudgeval="' + id + '"]'), note = document.querySelector('[data-nudgenote="' + id + '"]');
  var v = box ? box.value.trim() : "", body = { user: state.user, key: b.dataset.key };
  if (!v) { note.textContent = b.dataset.kind === "due" ? "Pick the due date first." : "Write the answer first."; return; }
  body[b.dataset.kind] = v; b.disabled = true;
  api("POST", "/api/waiting/nudge-answer", body).then(function (c) {
    note.textContent = c.status === "applied" ? "Written on " + b.dataset.key + " in Jira." : "Preview only: " + (c.note || "not written to Jira.");
    if (c.status === "applied") { dismissNudge(id); }
  }).catch(function (e) { note.textContent = e.message || "Not sent."; }).then(function () { b.disabled = false; });
}
function waitingHtml() {
  if (!state.user) { return ""; }
  var w = state.waiting || {}, rp = state.replies || {};
  var head = '<div class="w-drop__head">Assigned to you in Jira <span class="w-task__tools">' + (w.pending
    ? "Devin Cloud is reading Jira" + (w.session_url ? ' (<a target="_blank" href="' + esc(w.session_url) + '">session</a>)' : "") + "…"
    : (w.fetched_at ? agoSpan(w.fetched_at) + " " : "") +
      '<button type="button" class="a-btn a-btn--outline w-sync" data-waitcheck="1" title="Starts a short read-only Devin Cloud session that reads your Approval and Question sub-tasks, about a minute. Otherwise the list is read once and kept.">Check now</button>') +
    "</span></div>" + (w.error ? '<div class="c-err w-task__err">' + esc(w.error) + "</div>" : "");
  var done = { answer: "answered", approve: "approved", reject: "rejected" };
  var items = (w.stories || []).map(function (s) {
    var r = rp[s.key], k = taskKind(s);
    var st = !r ? "" : r.state === "sending" ? ' <span class="c-pill">sending…</span>'
      : r.state === "done" ? ' <span class="c-pill w-task--done">' + done[r.kind] + "</span>"
      : ' <span class="c-err">not sent: ' + esc(r.error) + "</span>";
    return '<div class="w-drop__item w-task"><b><a target="_blank" href="' + esc(s.url) + '">' + esc(s.key) + '</a> <span class="c-pill">' + k + "</span>" + st + "</b>" +
      "<span>" + esc(s.summary) + "</span>" +
      '<span class="c-muted">' + (s.parent ? "under " + esc(s.parent) + " · " : "") + "from " + esc(s.reporter || "?") + " · " + esc(s.status) + "</span>" +
      (!r || r.state === "failed" ? '<span><button type="button" class="a-btn a-btn--outline w-sync" data-task="' + esc(s.key) + '">' + (k === "Approval" ? "Approve or reject…" : "Answer…") + "</button></span>" : "") + "</div>";
  }).join("");
  return head + (items || '<div class="c-empty">' + (w.fetched_at ? "No approvals or questions assigned to you." : "Not checked yet.") + "</div>");
}
function openTask(key) {
  var s = ((state.waiting || {}).stories || []).filter(function (x) { return x.key === key; })[0];
  if (!s) { return; }
  closeMenus(); state.task = s;
  var appr = taskKind(s) === "Approval";
  $("tmTitle").textContent = (appr ? "Approval · " : "Question · ") + s.key;
  $("tmSummary").textContent = s.summary;
  $("tmDesc").textContent = s.description || ""; $("tmDesc").hidden = !s.description;
  $("tmLink").href = s.url;
  $("tmLabel").textContent = appr ? "Note (needed to reject)" : "Your answer";
  $("tmText").value = ""; $("tmErr").hidden = true;
  $("tmSend").textContent = appr ? "Approve" : "Send answer";
  $("tmReject").hidden = !appr;
  $("tmNote").textContent = "Devin Cloud writes this on " + s.key + " as " + personName(state.user) + ", through the Jira service account.";
  $("taskModal").hidden = false; $("tmText").focus();
}
function sendTask(kind) {
  var s = state.task, text = $("tmText").value.trim();
  if (kind !== "approve" && !text) { $("tmErr").textContent = kind === "answer" ? "Write the answer first." : "Say why you reject it."; $("tmErr").hidden = false; return; }
  var verb = { answer: "Send this answer to", approve: "Approve", reject: "Reject" }[kind];
  askConfirm(verb + " " + s.key + " in Jira as " + personName(state.user) + "?", { title: { answer: "Send the answer", approve: "Approve", reject: "Reject" }[kind], ok: { answer: "Send answer", approve: "Approve", reject: "Reject" }[kind], danger: kind === "reject" }).then(function (yes) {
  if (!yes) { return; }
  $("tmSend").disabled = true; $("tmReject").disabled = true;
  api("POST", "/api/waiting/reply", { user: state.user, key: s.key, kind: kind, text: text })
    .then(function (j) { state.replies = j.replies || {}; $("taskModal").hidden = true; setApprovalCount(); loadWaiting(); })
    .catch(function (e) { if (!e.offline) { $("tmErr").textContent = e.message; $("tmErr").hidden = false; } })
    .then(function () { $("tmSend").disabled = false; $("tmReject").disabled = false; });
  });
}
function personName(u) { var p = state.people.filter(function (x) { return x.jira_user === u; })[0]; return p ? p.name : u; }
