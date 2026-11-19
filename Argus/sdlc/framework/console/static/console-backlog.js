/* Argus — front end, the Backlog screens. Talks only to the local server's /api routes.
   The page loads console.js, console-run.js, console-pc.js, console-backlog.js and console-main.js in that
   order as plain scripts sharing one scope; console-main.js wires the page and starts it. */
"use strict";
// ---------------------------------------------------------------- Backlog tab (console/backlog.py)
var bl = { data: null, sel: {}, key: null, round: null, pts: null, filter: "", flag: "", pane: "groom", group: (window.localStorage && localStorage.getItem("blGroup")) || "", collapsed: {}, drafts: {} };
// PO, BSA and lead roles use the Backlog to groom; Raise and Log hours stay for QA, UAT and developers.
// Unsaved Backlog edits, kept in this browser until Save to Jira or Discard.
function blDraftsSave() { if (window.localStorage) { localStorage.setItem("blDrafts", JSON.stringify(bl.drafts)); } }
function blDraftsDirty() { return Object.keys(bl.drafts).some(function (k) { return Object.keys(bl.drafts[k] || {}).length; }); }
try { bl.drafts = JSON.parse((window.localStorage && localStorage.getItem("blDrafts")) || "{}") || {}; } catch (e) { bl.drafts = {}; }
function blGrooming() { var r = state.me && state.me.role; return !!r && BACKLOG_ROLES.indexOf(r.id) >= 0; }
function blUser() { return state.user || ""; }
function blErr(e) {
  var msg = e ? e.message || String(e) : "", outage = !!e && jiraDown() && /reach Jira/.test(plainErr(msg));
  $("blErr").hidden = !e || outage; $("blErr").innerHTML = e && !outage ? errHtml(msg) : "";
  if (e && !((bl.data || {}).stories || []).length) { $("blList").innerHTML = '<div class="c-empty">' + (outage ? "Jira isn't reachable right now." : "Couldn't read Jira for this list.") + " Press Refresh to try again.</div>"; }
}
function showBacklog(quiet) {
  state.wideOpen = {};
  stopPolling(); closeMenus(); state.run = null; state.story = null; renderStories();
  $("welcome").hidden = true; $("storyView").hidden = true; $("runView").hidden = true; $("pcView").hidden = true; $("autoView").hidden = true;
  $("backlogView").hidden = false; setSide("cloud");
  bl.pane = "groom"; renderBlPane();
  document.querySelector(".c-main").classList.remove("is-run");
  blErr(null);
  blLoad(false);
  blPreviews();
  if (quiet !== true) { navPush("#backlog"); }
}
function blLoad(refresh) {
  if (refresh || !bl.data) { $("blList").innerHTML = '<div class="c-empty">Reading Jira…</div>'; }
  return api("GET", "/api/backlog?user=" + encodeURIComponent(blUser()) + (refresh ? "&refresh=1" : "")).then(function (d) {
    var same = !refresh && bl.data && (bl.data.stories || []).length && bl.data.fetched_at === d.fetched_at;
    if (same) {
      if (d.pending) { setTimeout(function () { if (!$("backlogView").hidden) { blLoad(false); } }, 8000); }
      return;
    }
    bl.data = d;
    var m = d.mode || {};
    $("blMode").textContent = m.writes ? "writes on for " + (m.allowed.length ? m.allowed.join(", ") : "no tickets") : "previews only";
    $("blMode").classList.toggle("c-pill--on", !!m.writes);
    var sp = $("blSprintTo"); sp.innerHTML = '<option value="">Move to…</option><option value="backlog">Backlog (no sprint)</option>' +
      (d.sprints || []).map(function (s) { return '<option value="' + esc(s.id) + '">' + esc(s.name) + " (" + esc(s.state) + ")</option>"; }).join("");
    if (!(d.sprints || []).length) { sp.innerHTML += '<option value="" disabled>Sprint list needs the Jira service account on this box</option>'; }
    $("blEpic").innerHTML = '<option value="">Epic…</option>' + (d.epics || []).map(function (e) { return '<option value="' + esc(e.key) + '">' + esc(e.key + " · " + e.summary) + "</option>"; }).join("");
    $("blPhase").innerHTML = '<option value="">Phase…</option>' + (m.phases || []).map(function (ph) { return "<option>" + esc(ph) + "</option>"; }).join("");
    $("blAge").innerHTML = agoSpan(d.fetched_at || Date.now() / 1000);
    if ($("blBulkField").value) { blBulkValue(); }
    if (d.error) { blErr(new Error(d.error)); }
    if (d.pending) { setTimeout(function () { if (!$("backlogView").hidden) { blLoad(false); } }, 8000); }
    blRenderList();
    if (bl.key && !blStory(bl.key) && state.story && state.story.key === bl.key) { bl.data.stories.unshift(state.story); blRenderList(); }
    if (bl.key) { blDetail(); }
    if (bl.pane === "calendar") { blCalendar(); }
    if (bl.pane === "plan") { blPlan(); }
  }, blErr);
}
function blRenderList() {
  var d = bl.data || {}, f = bl.filter.toLowerCase();
  var flag = BL_FLAGS.filter(function (x) { return x.id === bl.flag; })[0];
  blChips();
  var rows = (d.stories || []).filter(function (s) {
    return (!flag || flag.test(s)) && (!f || (s.key + " " + s.summary + " " + (s.sprint || "backlog") + " " + s.parent + " " + s.status + " " + s.assignee).toLowerCase().indexOf(f) >= 0);
  });
  if (bl.sort === "points") { rows = rows.slice().sort(function (a, b) { return blNum(b) - blNum(a); }); }
  if (bl.sort === "stale") { rows = rows.slice().sort(function (a, b) { return (a.updated ? new Date(a.updated).getTime() : 0) - (b.updated ? new Date(b.updated).getTime() : 0); }); }
  var all = (d.stories || []).length;
  if (!rows.length) {
    paint($("blList"), (all && (f || flag) ? '<div class="c-muted bl-count">0 of ' + all + " stories</div>" : "") +
      '<div class="c-empty">' + (d.pending ? "Devin is reading the backlog for you…" : "No groomable tickets" + (f || flag ? " match" : "") + ".") + "</div>");
    return;
  }
  paint($("blList"), '<div class="c-muted bl-count">' + (f || flag ? rows.length + " of " : "") + all + " stories" +
    (d.truncated ? " — Jira has " + esc(d.total) + "; only the first " + all + " are read. Narrow the filter in Jira." : "") + "</div>" +
    blGrouped(rows, function (s) {
    return '<div class="c-item bl-item' + (bl.key === s.key ? " is-active" : "") + '" data-blkey="' + esc(s.key) + '" tabindex="0" role="button" aria-pressed="' + (bl.key === s.key) + '">' +
      '<input type="checkbox" data-blsel="' + esc(s.key) + '"' + (bl.sel[s.key] ? " checked" : "") + '>' +
      "<div><span class=\"k\">" + esc(s.key) + "</span> " + esc(s.summary) + '<div class="m">' + esc(s.status) + " · " + esc(s.sprint || "backlog") + (s.parent ? " · " + esc(s.parent) : "") + (s.specialty ? " · " + esc(s.specialty) : "") + " · " + esc(s.assignee) + "</div></div>" +
      '<span class="bl-pts">' + esc(s.points || "–") + "</span></div>";
  }), "data-blkey");
  blSelCount();
}
// Group the list by specialty (specialty, else Foundational, else Misc — set by backlog.py) or by epic.
// Foundational sorts after the specialties; "No epic" and Misc go last.
function blGrouped(rows, row) {
  if (!bl.group) { return rows.map(row).join(""); }
  var names = Object.assign({}, (bl.data || {}).parents || {}), groups = {}, order = [];
  ((bl.data || {}).epics || []).forEach(function (e) { names[e.key] = e.summary; });
  rows.forEach(function (s) {
    var g = bl.group === "epic" ? (s.parent ? s.parent + (names[s.parent] ? " · " + names[s.parent] : "") : "No epic")
      : bl.group === "sprint" ? (s.sprint || "Backlog") : bl.group === "assignee" ? (s.assignee || "Unassigned") : (s.specialty || "Misc");
    if (!groups[g]) { groups[g] = []; order.push(g); }
    groups[g].push(s);
  });
  function rank(g) { return /^No |^Misc$|^Backlog$|^Unassigned$/.test(g) ? 2 : g === "Foundational" ? 1 : 0; }
  order.sort(function (a, b) { return rank(a) - rank(b) || a.localeCompare(b); });
  bl.groupNames = order;
  return '<div class="bl-grp-bar"><button type="button" class="bl-grp-btn" data-blgrpall="open">+ Expand all</button>' +
    '<button type="button" class="bl-grp-btn" data-blgrpall="close">\u2212 Collapse all</button></div>' + order.map(function (g) {
    var xs = groups[g], pts = xs.reduce(function (n, s) { return n + blNum(s); }, 0), shut = !!bl.collapsed[bl.group + "|" + g];
    return '<div class="bl-grp"><button type="button" class="bl-grp__tog" data-blgrptog="' + esc(g) + '" aria-expanded="' + !shut + '" title="' +
      (shut ? "Expand" : "Collapse") + '">' + (shut ? "+" : "\u2212") + "</button> <b>" + esc(g) + '</b> <span class="c-muted">' + xs.length + (xs.length === 1 ? " story" : " stories") +
      (pts ? " · " + pts + " pts" : "") + "</span></div>" + (shut ? "" : xs.map(row).join(""));
  }).join("");
}
var AC_PLACEHOLDER = /please enter acceptance criteria/i, DAY = 864e5;
function blNum(s) { return parseFloat(s.points) || 0; }
function blHasAc(s) { return s.acceptance === undefined || (String(s.acceptance).trim() && !AC_PLACEHOLDER.test(s.acceptance)); }
function blReady(s) { return blHasAc(s) && blNum(s) > 0 && blNum(s) <= 13; }
var BL_FLAGS = [
  { id: "groom", tip: "Missing real acceptance criteria, not sized, or over 13 points", label: "Needs grooming", test: function (s) { return !blReady(s); } },
  { id: "unassigned", tip: "Nobody assigned in Jira", label: "Unassigned", test: function (s) { return !s.assignee || s.assignee === "Unassigned"; } },
  { id: "noac", tip: "No acceptance criteria, or only the Jira placeholder text", label: "No AC", test: function (s) { return !blHasAc(s); } },
  { id: "nopts", tip: "No story points yet", label: "No points", test: function (s) { return !blNum(s); } },
  { id: "split", tip: "Over 13 points: split before planning", label: "Over 13 points", test: function (s) { return blNum(s) > 13; } },
  { id: "noepic", tip: "Not under an epic", label: "No epic", test: function (s) { return !s.parent; } },
  { id: "norelease", tip: "No fix version (release) set", label: "No release", test: function (s) { return !(s.releases || []).length; } },
  { id: "nospecialty", tip: "No specialty found in the title or the epic, so the backlog files it under Misc", label: "Misc", test: function (s) { return !s.specialty || s.specialty === "Misc"; } },
  { id: "stale", tip: "Nothing changed on the ticket in 30 days", label: "No update 30 days", test: function (s) { return s.updated && Date.now() - new Date(s.updated).getTime() > 30 * DAY; } }
];
function blChips() {
  var all = (bl.data || {}).stories || [];
  $("blChips").innerHTML = all.length ? BL_FLAGS.map(function (x) {
    var n = all.filter(x.test).length;
    return '<button type="button" class="bl-chip' + (bl.flag === x.id ? " is-on" : "") + (n ? "" : " is-zero") + '" data-blflag="' + x.id + '" title="' + esc(x.tip) + '" aria-pressed="' + (bl.flag === x.id) + '">' + esc(x.label) + "<b>" + n + "</b></button>";
  }).join("") + (bl.flag ? '<button type="button" class="bl-chip bl-chip--clear" data-blflag="">Clear</button>' : "") : "";
}
function blSprints() {
  var d = bl.data || {}, by = {}, today = new Date();
  function tokKey(tok) { return tok.split(".").reduce(function (n, x) { return n * 100 + +x; }, 0); }
  (d.stories || []).forEach(function (s) {
    var sp = sprintOf(s.sprint); if (!sp) { return; }
    var r = by[sp.token] || (by[sp.token] = { token: sp.token, start: sp.start, end: sp.end, stories: [], pts: 0 });
    r.stories.push(s); r.pts += blNum(s);
  });
  (d.sprints || []).forEach(function (j) {
    var sp = sprintOf(j.name); if (!sp) { return; }
    var r = by[sp.token] || (by[sp.token] = { token: sp.token, start: sp.start, end: sp.end, stories: [], pts: 0 });
    r.id = j.id; r.active = j.state === "active";
  });
  var list = Object.keys(by).map(function (k) { return by[k]; }).sort(function (a, b) { return tokKey(a.token) - tokKey(b.token); });
  list.forEach(function (r) { if (!r.active && r.start && r.end && today >= r.start && today < new Date(r.end.getTime() + DAY)) { r.active = !list.some(function (o) { return o.active && o !== r; }); } });
  return list;
}
function blPlan() {
  var d = bl.data || {}, vel = (d.mode || {}).velocity, list = blSprints(), i = 0;
  while (i < list.length && !list[i].active) { i += 1; }
  if (i === list.length) { i = 0; }
  var cur = list[i], next = list[i + 1], all = d.stories || [];
  function rowsOf(xs) {
    return xs.length ? xs.map(function (s) {
      return '<div class="c-item" data-blkey="' + esc(s.key) + '"><span class="k">' + esc(s.key) + "</span> " + esc(s.summary) +
        ' <span class="c-muted">' + esc(s.points || "–") + " pts · " + esc(s.status) + " · " + esc(s.assignee || "Unassigned") + "</span></div>";
    }).join("") : '<div class="c-muted">None.</div>';
  }
  function pick(xs, target) {
    return '<button type="button" class="a-btn a-btn--outline" data-blpick="' + esc(xs.map(function (s) { return s.key; }).join(",")) + '" data-blto="' + esc(target || "") + '"' + (xs.length ? "" : " disabled") + ">Select these to move</button>";
  }
  function capacity(r) {
    if (!r) { return ""; }
    var over = vel ? r.pts - vel : 0;
    return '<section><h3>' + esc(r.token) + (r.active ? " (active)" : " (next)") + "</h3>" +
      '<div class="bl-bar"><span style="width:' + (vel ? Math.min(100, Math.round(100 * r.pts / vel)) : 0) + '%"' + (over > 0 ? ' class="is-over"' : "") + "></span></div>" +
      "<div>" + r.pts + (vel ? " / " + vel + " points · " + (over > 0 ? '<span class="bl-over">over by ' + over + "</span>" : (vel - r.pts) + " free") : " points (no velocity in the year plan)") + "</div>" +
      '<div class="c-muted">' + r.stories.length + " stories, " + r.stories.filter(function (s) { return !blNum(s); }).length + " unsized</div></section>";
  }
  // Push out: not-started stories from the bottom of the rank, the not-ready ones first, until the sprint fits.
  var push = [];
  if (cur && vel && cur.pts > vel) {
    var cand = cur.stories.filter(function (s) { return /^(open|to do|new|ready)$/i.test(s.status || ""); }).reverse();
    cand.sort(function (a, b) { return (blReady(a) ? 1 : 0) - (blReady(b) ? 1 : 0); });
    var left = cur.pts;
    cand.forEach(function (s) { if (left > vel && blNum(s) > 0) { push.push(s); left -= blNum(s); } });
  }
  // Pull in: ready backlog stories in rank order that fit the space left in the target sprint.
  var target = cur && vel && cur.pts < vel ? cur : next, pull = [];
  if (target && vel) {
    var room = vel - target.pts;
    all.filter(function (s) { return !s.sprint && blReady(s); }).forEach(function (s) { if (blNum(s) <= room) { pull.push(s); room -= blNum(s); } });
  }
  var load = {};
  (cur ? cur.stories : []).forEach(function (s) { var a = s.assignee || "Unassigned"; load[a] = (load[a] || 0) + blNum(s); });
  var people = Object.keys(load).sort(function (a, b) { return load[b] - load[a]; });
  var named = people.filter(function (a) { return a !== "Unassigned"; }), avg = named.length ? named.reduce(function (n, a) { return n + load[a]; }, 0) / named.length : 0;
  var split = all.filter(function (s) { return blNum(s) > 13; });
  var cloud = !(d.sprints || []).length;
  function sum(xs) { return xs.reduce(function (n, s) { return n + blNum(s); }, 0); }
  var after = cur && vel && (push.length || pull.length) ? '<p class="bl-after"><b>After the suggested moves:</b> ' + esc(cur.token) + " " + (cur.pts - sum(push) + (target === cur ? sum(pull) : 0)) + " / " + vel +
    (next ? " · " + esc(next.token) + " " + (next.pts + sum(push) + (target === next ? sum(pull) : 0)) + " / " + vel : "") + " points.</p>" : "";
  $("blPlan").innerHTML = '<div class="bl-head"><b>Plan the sprint</b> <button type="button" class="a-btn a-btn--outline" data-navback>Back</button></div>' +
    '<p class="c-muted">From the tickets on this screen, in Jira rank order. ' + (vel ? "Capacity is the velocity of " + vel + " points a sprint from the roadmap year plan; it does not take leave into account (Scrum Master follow-ups shows capacity after leave). " : "") +
    "\"Select these to move\" ticks the stories and picks the sprint under the list; press Preview move to see exactly what would change in Jira." +
    (cloud ? " Moving needs the sprint list, which this Argus only has with the Jira service account on this box." : "") + "</p>" +
    (cur ? '<div class="bl-plan">' + capacity(cur) + capacity(next) + "</div>" + after : '<div class="c-empty">' + (d.pending ? "Devin is reading the backlog for you…" : (d.error || jiraDown()) && !(d.stories || []).length ? "Jira isn't reachable right now, so there are no sprints to show." : "No sprints found on these tickets.") + "</div>") +
    '<div class="bl-plan" style="margin-top:12px">' +
    "<section><h3>Push out of " + esc(cur ? cur.token : "the sprint") + " (" + push.length + ")</h3>" +
      (push.length ? '<p class="c-muted">Not started, lowest rank first, not-ready ones before ready ones, until the sprint fits.</p>' : "") + rowsOf(push) + pick(push, next && next.id) + "</section>" +
    "<section><h3>Pull in to " + esc(target ? target.token : "the sprint") + " (" + pull.length + ")</h3>" +
      '<p class="c-muted">Backlog stories that are ready (real AC, sized, 13 points or less), in rank order, that fit the space left.</p>' + rowsOf(pull) + pick(pull, target && target.id) + "</section>" +
    "<section><h3>Load per person in " + esc(cur ? cur.token : "the sprint") + "</h3>" +
      (people.length ? people.map(function (a) {
        return '<div class="c-item" data-blfilter="' + esc(a) + '">' + esc(a) + " · " + (load[a] > 1.5 * avg && a !== "Unassigned" ? '<span class="bl-over">' + load[a] + " pts</span>" : load[a] + " pts") + "</div>";
      }).join("") + '<p class="c-muted">Red is more than 1.5 times the team average (' + Math.round(avg) + " pts). Click a name to filter the list.</p>" : '<div class="c-muted">None.</div>') + "</section>" +
    "<section><h3>Split before planning (" + split.length + ")</h3>" + rowsOf(split) + "</section></div>";
}
function blSelCount() {
  var n = Object.keys(bl.sel).filter(function (k) { return bl.sel[k]; }).length;
  $("blSelCount").textContent = n + " selected";
  $("blBulkRow1").hidden = $("blBulkRow2").hidden = !n; $("blSelHint").hidden = !!n;
  $("blMove").disabled = !n || !$("blSprintTo").value;
  $("blBulkPreview").disabled = !n || !$("blBulkField").value;
  $("blBulkPreview").textContent = n ? "Preview for " + n : "Preview";
}
// Bulk change: one field on every selected ticket, shown as one combined preview before anything is sent.
// The list skips redraws when its HTML is unchanged, so ticked boxes are cleared in the page too.
function blClearSel() {
  bl.sel = {};
  document.querySelectorAll("#blList [data-blsel]").forEach(function (b) { b.checked = false; });
  blRenderList();
}
function blSelected() { return Object.keys(bl.sel).filter(function (k) { return bl.sel[k]; }); }
function blBulkValue() {
  var f = $("blBulkField").value, d = bl.data || {}, box = $("blBulkValueBox");
  $("blBulkBox").hidden = true;
  if (f === "points") { box.innerHTML = '<input id="blBulkVal" class="a-input" type="number" min="0.5" step="0.5" style="width:6em" aria-label="Points">'; }
  else if (f === "sprint") { box.innerHTML = '<select id="blBulkVal" class="a-select" aria-label="Sprint"><option value="backlog">Backlog (no sprint)</option>' + (d.sprints || []).map(function (sp) { return '<option value="' + esc(sp.id) + '">' + esc(sp.name) + " (" + esc(sp.state) + ")</option>"; }).join("") + "</select>"; }
  else if (f === "epic") { box.innerHTML = '<select id="blBulkVal" class="a-select" aria-label="Epic">' + (d.epics || []).map(function (e) { return '<option value="' + esc(e.key) + '">' + esc(e.key + " · " + e.summary) + "</option>"; }).join("") + "</select>"; }
  else if (f === "assignee") { box.innerHTML = '<select id="blBulkVal" class="a-select" aria-label="Assignee">' + (state.people || []).filter(function (p) { return p.jira_user; }).map(function (p) { return '<option value="' + esc(p.jira_user) + '">' + esc(p.name || p.jira_user) + "</option>"; }).join("") + "</select>"; }
  else { box.innerHTML = ""; }
  blSelCount();
}
function blBulkBody(send) {
  var f = $("blBulkField").value, v = $("blBulkVal") ? $("blBulkVal").value : "";
  if (f === "sprint" && v !== "backlog") { v = ((bl.data || {}).sprints || []).filter(function (sp) { return String(sp.id) === v; })[0] || v; }
  return { keys: blSelected(), field: f, value: v, send: !!send, user: blUser() };
}
function blBulkShow(d) {
  var writes = ((bl.data || {}).mode || {}).writes;
  $("blBulkBox").innerHTML = "<b>" + esc(d.title) + "</b><ul>" + (d.lines || []).map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ul>" +
    '<div class="c-muted">Each ticket also gets a comment saying who changed it. ' + (writes ? "Send writes to Jira for the tickets on the allow-list; the rest stay previews." : "Backlog writes are off on this Argus, so Send only records a preview.") + "</div>" +
    '<div class="c-card__actions"><button type="button" class="a-btn a-btn--primary" id="blBulkSend">' + (writes ? "Send to Jira" : "Record preview") + '</button> <button type="button" class="a-btn a-btn--outline" id="blBulkCancel">Cancel</button></div>';
  $("blBulkBox").hidden = false;
}
// Saved views: a named filter (words, chip, grouping, sort) kept on this PC and shared as a link.
function blViewsAll() { try { return JSON.parse(localStorage.getItem("sdlc-blviews") || "[]"); } catch (e) { return []; } }
function blViewNow(name) { return { name: name, filter: bl.filter || "", flag: bl.flag || "", group: bl.group || "", sort: bl.sort || "" }; }
function blRenderViews(pick) {
  var all = blViewsAll();
  $("blViews").innerHTML = '<option value="">Saved views…</option>' + all.map(function (v, i) { return '<option value="' + i + '"' + (pick === v.name ? " selected" : "") + ">" + esc(v.name) + "</option>"; }).join("");
  $("blViewDel").hidden = !$("blViews").value;
}
function blApplyView(v) {
  bl.filter = v.filter || ""; $("blFilter").value = bl.filter;
  bl.flag = v.flag || ""; bl.group = v.group || ""; bl.sort = v.sort || "";
  $("blGroupBy").value = bl.group; $("blSort").value = bl.sort;
  if (window.localStorage) { localStorage.setItem("blGroup", bl.group); }
  blRenderList();
}
function blViewFromHash() {
  var m = /(?:^|[#&])blview=([^&]+)/.exec(location.hash || ""); if (!m) { return; }
  var v; try { v = JSON.parse(decodeURIComponent(m[1])); } catch (e) { return; }
  openBlPane("groom"); blApplyView(v);
  if (v.name) { $("blViewName").value = v.name; }
}
// What I sent today: this user's Backlog changes since midnight, from the same log as the previews list.
function openSent() {
  closeMenus(); $("sentModal").hidden = false; $("sentList").innerHTML = '<div class="c-muted">Reading…</div>';
  var midnight = new Date(); midnight.setHours(0, 0, 0, 0);
  api("GET", "/api/backlog/previews").then(function (d) {
    var mine = (d.previews || []).filter(function (c) { return c.by === state.user && c.at * 1000 >= midnight.getTime(); });
    $("sentList").innerHTML = mine.map(function (c) {
      return '<div class="w-sent__row"><span class="c-muted">' + esc(fmtDate(c.at).slice(-5)) + "</span><span>" + esc(c.title) + "<br>" +
        (c.keys || []).map(function (k) { return '<a target="_blank" rel="noopener" href="' + esc((d.browse || "") + k) + '">' + esc(k) + "</a>"; }).join(" ") + "</span>" +
        '<span class="c-pill' + (c.status === "applied" ? " c-pill--on" : "") + '">' + (c.status === "applied" ? "written to Jira" : "preview only") + "</span></div>";
    }).join("") || '<div class="c-empty">Nothing sent from this page today.</div>';
  }, function (e) { $("sentList").innerHTML = '<div class="c-err">' + esc(e.message) + "</div>"; });
}
function blStory(key) { return ((bl.data || {}).stories || []).filter(function (s) { return s.key === key; })[0]; }
// Team poker: one round shared by every Argus on the call; the PO or BSA starts and reveals it.
var tp = { room: null, off: "", told: {}, at: 0, popped: {}, dis: {}, err: "" };
var TP_DEVIN = "devin";
function tpName(u) { return u === TP_DEVIN ? "Devin" : u; }
var TP_LEADS = ["po_office", "bsa"];
function tpLead() { return TP_LEADS.indexOf(lensId()) >= 0; }
function tpPoll() {
  if (!blUser() || tp.off || document.hidden) { return; }
  return api("GET", "/api/poker/room?user=" + encodeURIComponent(blUser())).then(function (r) { tp.room = r; tp.at = Date.now(); tpBanner(); tpRender(); tpModal(); },
    function (e) { if (e.status === 409 && /Devin Cloud/.test(e.message)) { tp.off = e.message; tpRender(); } });
}
function tpLive() {
  var me = blUser();
  return ((tp.room || {}).rounds || []).some(function (r) { return r.state === "open" && (r.by === me || r.invited.indexOf(me) >= 0); });
}
var TP_TIMERS = [["0", "No timer — I end the vote"], ["30", "30 s"], ["60", "1 min"], ["90", "1 min 30 s"], ["120", "2 min"], ["180", "3 min"], ["300", "5 min"], ["600", "10 min"]];
function tpSecs() { var v = localStorage.getItem("sdlc-poker-seconds"); return TP_TIMERS.some(function (t) { return t[0] === v; }) ? v : "0"; }
function tpTimerLabel(v) { return (TP_TIMERS.filter(function (t) { return t[0] === v; })[0] || TP_TIMERS[0])[1]; }
function tpMinSec(n) { return Math.floor(n / 60) + ":" + ("0" + (n % 60)).slice(-2); }
function tpTick(n) { return n ? tpMinSec(n) + " left" : "time's up, showing the votes…"; }
function tpLeft(r) { return r && r.left !== null && r.left !== undefined ? Math.max(0, Math.round(r.left - (Date.now() - tp.at) / 1000)) : null; }
function tpClock(r) {
  var n = tpLeft(r);
  return n === null ? "" : ' <b class="tp-clock" data-tpleft="' + esc(r.id) + '">' + tpTick(n) + "</b>";
}
function tpAsked() {
  var me = blUser();
  return ((tp.room || {}).rounds || []).filter(function (r) { return r.state === "open" && r.by !== me && r.invited.indexOf(me) >= 0 && !r.mine; });
}
function tpBanner() {
  var asked = tpAsked()[0], el = $("tpBanner");
  el.hidden = !asked;
  if (!asked) { return; }
  el.innerHTML = "<b>" + esc(asked.by) + "</b> asks you to point <b>" + esc(asked.key) + "</b>" + tpClock(asked) + ' <button type="button" class="a-btn a-btn--primary" data-tpgo="' + esc(asked.key) + '">Point now</button>';
  if (!tp.told[asked.id] && window.Notification) {
    tp.told[asked.id] = true;
    if (Notification.permission === "granted") { new Notification("Planning poker", { body: asked.by + " asks you to point " + asked.key }); }
    else if (Notification.permission === "default") { Notification.requestPermission(); }
  }
}
function tpRound() { return ((tp.room || {}).rounds || []).filter(function (r) { return r.key === bl.key; })[0] || null; }
var ins = {}, insTimer = null;
function insGet(key) {
  return api("GET", "/api/backlog/insight?key=" + encodeURIComponent(key)).then(function (r) {
    ins[key] = r || {}; insRender(); tpRender(); blChallengeLocal();
    clearTimeout(insTimer);
    if (r && r.state === "working" && bl.key === key) { insTimer = setTimeout(function () { insGet(key); }, 15000); }
  }, function () {});
}
function insRender() {
  var box = $("insBox"), s = blStory(bl.key); if (!box || !s) { return; }
  var r = ins[s.key], noAc = !blHasAc(s), what = noAc ? "suggest acceptance criteria and its own estimate" : "give its own estimate";
  if (r === undefined) { box.innerHTML = ""; insGet(s.key); return; }
  if (r.state === "working") {
    box.innerHTML = '<span class="c-muted">Devin is reading ' + esc(s.key) + ' and the code it touches…' + (r.url ? ' <a href="' + esc(r.url) + '" target="_blank" rel="noopener">session</a>' : "") + "</span>";
    return;
  }
  if (r.state === "done") {
    box.innerHTML = noAc && r.acceptance ? '<div class="ins-ac"><b>Suggested acceptance criteria</b> <span class="c-pill">suggested · not in Jira yet</span>' +
      '<textarea id="insAc" class="a-input" rows="7">' + esc(r.acceptance) + "</textarea>" +
      '<div class="bl-row"><button type="button" class="a-btn a-btn--primary" id="insUse">Use as AC</button>' +
      '<span class="c-muted">It goes into the acceptance criteria box; Save to Jira sends it.</span></div></div>' +
      '<div class="c-muted">Devin has its card; it plays it in team poker and shows it with the votes.</div>' :
      '<span class="c-muted">Devin has its card; it plays it in team poker and shows it with the votes.</span>';
    return;
  }
  box.innerHTML = (r.state === "failed" ? '<span class="bl-over">Devin could not ' + what + ": " + esc(r.error || "no answer") + "</span> " : "") +
    '<button type="button" class="a-btn a-btn--outline" id="insAsk">' + (noAc ? "Suggest acceptance criteria" : "Ask Devin for its estimate") + "</button>" +
    '<span class="c-muted"> one read-only Devin session that reads the ticket and the code; ' + (noAc ? "the PO edits the suggestion, " : "") + "the estimate stays hidden until the votes are revealed.</span>";
}
function insValue(r) { return !r || r.state !== "done" || !r.points ? "" : r.needs_grooming ? "?" : r.needs_split ? "13" : String(r.points); }
function insBasis(r) {
  if (r.rule) { return "<li>" + esc(r.rule) + "</li>"; }
  var dims = ["SCOPE", "RISK", "UNKNOWNS", "DEPENDENCY", "TESTABILITY"], sc = r.scores || {}, why = r.reasons || {};
  if (dims.some(function (d) { return sc[d] === null || sc[d] === undefined; })) { return ""; }
  return dims.map(function (d) { return "<li><b>" + d + " " + esc(sc[d]) + "</b>" + (why[d] ? " — " + esc(why[d]) : "") + "</li>"; }).join("") +
    "<li>Total " + esc(r.total) + "/10 → " + esc(r.base) + " points" + ((r.modifiers || []).length ? ", + " + r.modifiers.map(esc).join(", ") + " → " + esc(r.points) : "") + "</li>" +
    (r.needs_grooming ? '<li class="bl-over">UNKNOWNS is 2 with another 2: the matrix says groom it before pointing, so Devin plays ?.</li>' : "") +
    (r.needs_split ? '<li class="bl-over">Over the matrix limit: split it, so Devin plays 13.</li>' : "");
}
var insWhy = {};
function insCard(key, votes) {
  var r = ins[key], mine = insValue(r) || (votes || {})[TP_DEVIN] || "";
  var open = !!insWhy[key], btn = ' <button type="button" class="a-btn a-btn--ghost" data-inswhy="' + esc(key) + '" aria-expanded="' + open + '">' +
    (open ? "Hide Devin's reasoning" : "Show Devin's reasoning") + "</button>";
  if (!r || r.state !== "done" || !r.points) {
    if (!mine || mine === "✓") { return ""; }
    return '<div class="ins-ch"><b class="tp-devin-card">Devin played ' + esc(mine) + "</b>" + btn + (!open ? "" : '<div class="c-muted">' +
      (r === undefined || r.state === "working" ? "Fetching Devin's reasoning…" : "Devin's reasoning isn't on this Argus: it is kept on Argus that asked Devin for its estimate.") + "</div>") + "</div>";
  }
  var h = '<div class="ins-ch"><b class="tp-devin-card">Devin says ' + esc(mine) + "</b>" + btn;
  if (!open) { return h + '<div class="c-muted">The team decides: the number Resource 17 saves is the story points.</div></div>'; }
  h += '<div class="c-muted">Scored with the complexity matrix</div><ul class="ins-basis">' + insBasis(r) + "</ul>" +
    (r.why ? "<div>" + esc(r.why) + "</div>" : "") + (r.files && r.files.length ? '<div class="c-muted">' + r.files.map(esc).join(" · ") + "</div>" : "");
  var same = [], talk = [];
  Object.keys(votes || {}).forEach(function (u) {
    var v = votes[u]; if (u === TP_DEVIN || v === "✓") { return; }
    if (v === mine) { same.push(u); return; }
    if (v === "?") { talk.push("<li><b>To " + esc(u) + " (?):</b> say what you need to know. " + (r.reasons && r.reasons.UNKNOWNS ? "The unknown I saw: " + esc(r.reasons.UNKNOWNS) + "." : "") + "</li>"); return; }
    if (mine === "?" || isNaN(+v)) { return; }
    talk.push(+v > +mine ? "<li><b>To " + esc(u) + " (" + esc(v) + "):</b> I scored " + esc(mine) + ". I'd only go up to " + esc(v) + " if " + esc(r.bigger_if || "there is work I did not find in the code") + ". What do you see that I don't?</li>" :
      "<li><b>To " + esc(u) + " (" + esc(v) + "):</b> I scored " + esc(mine) + (r.why ? " because " + esc(r.why) : "") + ". I'd only go down to " + esc(v) + " if " + esc(r.smaller_if || "most of that is already in place") + ".</li>");
  });
  if (talk.length) { h += '<div class="ins-talk"><b>Devin challenges</b><ul>' + talk.join("") + "</ul></div>"; }
  if (same.length) { h += '<div class="c-muted">Same as Devin: ' + same.map(esc).join(", ") + ".</div>"; }
  return h + '<div class="c-muted">The team decides: the number Resource 17 saves is the story points.</div></div>';
}
function blChallengeLocal() {
  var box = $("blChallenge"), r = bl.round;
  if (box && r && r.revealed) { box.innerHTML = insCard(r.key, r.votes || {}); }
}
function tpMatch(r) {
  var vals = Object.keys(r.votes).map(function (u) { return r.votes[u]; });
  return vals.length && vals.every(function (v) { return v === vals[0] && v !== "?"; }) ? vals[0] : "";
}
function tpRender() {
  var box = $("tpBox"); if (!box) { return; }
  var me = blUser(), r = tpRound(), scale = (tp.room || {}).scale || ["1", "2", "3", "5", "8", "13", "?"], h = "<b>Team poker</b> ";
  if (tp.off) { box.innerHTML = h + '<span class="c-muted">' + esc(tp.off) + "</span>"; return; }
  if (!me) { box.innerHTML = h + '<span class="c-muted">Pick who you are (top right) to join team poker.</span>'; return; }
  if (!tp.room) { box.innerHTML = h + '<span class="c-muted">Looking for who is on Argus…</span>'; return; }
  if (!r) {
    if (!tpLead()) { box.innerHTML = h + '<span class="c-muted">No team round on this story. The PO or BSA starts one.</span>'; return; }
    var people = tp.room.online.filter(function (u) { return u !== me; }), di = ins[bl.key] || {}, dv = insValue(di);
    var devin = dv ? "has its card" : di.state === "working" ? "is still scoring with the complexity matrix" : di.state === "failed" ? "could not score it" : "has not scored it";
    box.innerHTML = h + '<span class="c-muted">On Argus now — untick anyone not on the call:</span><div class="tp-people">' +
      '<label><input type="checkbox" data-tpwho="' + TP_DEVIN + '"' + (di.state === "failed" ? "" : " checked") + "> Devin <span class=\"c-muted\">(" + devin + ")</span></label>" +
      (people.length ? people.map(function (u) { return '<label><input type="checkbox" data-tpwho="' + esc(u) + '" checked> ' + esc(u) + "</label>"; }).join("") : '<span class="c-muted">nobody else yet</span>') +
      '</div><div class="bl-row"><input id="tpExtra" class="a-input" style="flex:1" placeholder="add people not listed (jira users, comma-separated)">' +
      '<label class="c-muted">Timer <select id="tpSecs" class="a-select">' + TP_TIMERS.map(function (t) { return '<option value="' + t[0] + '"' + (t[0] === tpSecs() ? " selected" : "") + ">" + esc(t[1]) + "</option>"; }).join("") + "</select></label>" +
      '<button type="button" class="a-btn a-btn--primary" data-tp="start">' +
      (dv || di.state !== "working" ? "Notify &amp; start" + (tpSecs() === "0" ? "" : " " + esc(tpTimerLabel(tpSecs())) + " timer") : "Devin is still scoring — start anyway") + "</button></div>";
    return;
  }
  var mine = r.by === me, invited = r.invited.indexOf(me) >= 0;
  h += '<span class="c-muted">started by ' + esc(r.by) + " · " + r.voted.length + " of " + r.invited.length + " voted" +
    (r.waiting.length && r.state === "open" ? " · waiting for " + esc(r.waiting.map(tpName).join(", ")) : "") + "</span>";
  if (r.state === "open") {
    h += tpClock(r);
    h += '<div class="tp-votes">' + r.invited.map(function (u) { return '<span class="bl-vote' + (u === TP_DEVIN ? " tp-devin" : "") + '">' + esc(tpName(u)) + ": <b>" + (r.votes[u] ? "✓" : "…") + "</b></span>"; }).join("") + "</div>";
    if (invited && tpLeft(r) !== 0) { h += '<div class="bl-row bl-scale">Your vote: ' + scale.map(function (p) { return '<button type="button" class="a-btn a-btn--outline' + (r.mine === p ? " is-on" : "") + '" data-tpvote="' + p + '">' + p + "</button>"; }).join("") + "</div>"; }
    if (invited && tp.voteErr) { h += '<div class="bl-over" role="alert">' + esc(tp.voteErr) + "</div>"; }
    if (mine) { h += '<div class="bl-row"><button type="button" class="a-btn a-btn--primary" data-tp="reveal">End vote</button><span class="c-muted">' + (tpLeft(r) === null ? "Votes stay hidden until you end the vote." : "Ends the vote and shows the votes now; otherwise they show when the timer ends.") + "</span></div>"; }
  } else {
    var sp = r.spread || {}, vals = Object.keys(r.votes).map(function (u) { return r.votes[u]; }), same = tpMatch(r);
    h += '<div class="tp-votes">' + Object.keys(r.votes).map(function (u) {
      var v = r.votes[u], edge = !same && u !== TP_DEVIN && (String(sp.low) === v || String(sp.high) === v);
      return '<span class="bl-vote' + (edge ? " tp-edge" : "") + (u === TP_DEVIN ? " tp-devin" : "") + '">' + esc(tpName(u)) + ": <b>" + esc(v) + "</b></span>";
    }).join("") + (r.waiting.length ? r.waiting.map(function (u) { return '<span class="bl-vote c-muted">' + esc(tpName(u)) + ": no vote</span>"; }).join("") : "") + "</div>";
    h += '<div class="c-muted">' + (!vals.length ? "No votes." : same ? "Everyone said " + esc(same) + "." :
      (sp.low !== undefined ? "Team: low " + sp.low + " · median " + sp.median + " · high " + sp.high + "." : "")) +
      (vals.indexOf("?") >= 0 ? " Someone needs more information." : "") + "</div>";
    if (vals.indexOf("13") >= 0) { h += '<div class="bl-over">A 13 was voted: consider splitting this story.</div>'; }
    if (!same) { h += insCard(r.key, r.votes); }
    if (mine) {
      h += '<div class="bl-row">' + (same ? '<button type="button" class="a-btn a-btn--primary" data-tpsave="' + esc(same) + '">Save ' + esc(same) + " as story points</button>" :
        '<button type="button" class="a-btn a-btn--primary" data-tp="talk">Open discussion</button>') +
        '<button type="button" class="a-btn a-btn--outline" data-tp="again">Re-vote</button></div>';
    }
  }
  box.innerHTML = h;
}
function tpModal() {
  var r = tpRound(), m = $("tpModal");
  if (!r || r.state !== "shown" || r.by !== blUser() || tpMatch(r)) { if (m) { m.hidden = true; } return; }
  if (!tp.popped[r.id]) { tp.popped[r.id] = "open"; tp.dis = {}; }
  if (tp.popped[r.id] !== "open") { return; }
  if (!m) { m = document.createElement("div"); m.id = "tpModal"; m.className = "w-modal w-modal--float"; document.body.appendChild(m); }
  if (m.contains(document.activeElement) && document.activeElement.tagName === "TEXTAREA") { return; }
  var dv = insValue(ins[r.key]) || r.votes[TP_DEVIN] || "", people = Object.keys(r.votes).filter(function (u) { return u !== TP_DEVIN; });
  var dis = people.filter(function (u) { return tp.dis[u] !== undefined; });
  var picks = dis.map(function (u) { return r.votes[u]; }).filter(function (v, i, a) { return v !== "?" && a.indexOf(v) === i; });
  var h = '<div class="w-modal__box tp-talk"><h2 class="tp-drag" title="Drag to move">' + esc(r.key) + " — votes differ</h2>" + insCard(r.key, r.votes) +
    "<div><b>Does everyone agree with Devin" + (dv && dv !== "?" ? "'s " + esc(dv) : "") + "?</b> Tick anyone who disagrees and write their reason.</div>" +
    people.map(function (u) {
      var on = tp.dis[u] !== undefined;
      return '<div class="tp-who"><label><input type="checkbox" data-tpdis="' + esc(u) + '"' + (on ? " checked" : "") + "> " + esc(u) + " voted <b>" + esc(r.votes[u]) + "</b> — disagrees</label>" +
        (on ? '<textarea class="a-input" rows="2" data-tpwhy="' + esc(u) + '" placeholder="Why ' + esc(u) + ' thinks it is ' + esc(r.votes[u]) + '">' + esc(tp.dis[u]) + "</textarea>" : "") + "</div>";
    }).join("") + '<div class="bl-row">';
  if (dis.length) {
    h += picks.length ? '<select id="tpPick" class="a-select">' + picks.map(function (v) { return "<option value=\"" + esc(v) + "\">" + esc(v) + " (" + dis.filter(function (u) { return r.votes[u] === v; }).map(esc).join(", ") + ")</option>"; }).join("") +
      '</select><button type="button" class="a-btn a-btn--primary" data-tp="savedis">Save with the reasons</button>' : '<span class="bl-over">Those who disagree voted ?: re-vote once they have what they need.</span>';
  } else if (dv && dv !== "?") {
    h += '<button type="button" class="a-btn a-btn--primary" data-tpsave="' + esc(dv) + '">Everyone agrees — save ' + esc(dv) + "</button>";
  } else {
    h += '<span class="c-muted">Devin has no number to agree with: tick who disagrees, or re-vote.</span>';
  }
  m.innerHTML = h + '<button type="button" class="a-btn a-btn--outline" data-tp="again">Re-vote</button><button type="button" class="a-btn a-btn--ghost" data-tp="close">Close</button></div>' +
    (tp.err ? '<div class="bl-over" role="alert" id="tpErr">' + esc(tp.err) + "</div>" : "") + "</div>";
  m.hidden = false;
  tpPlace();
}
var tpDrag = null;
function tpPlace() {
  var b = document.querySelector("#tpModal .tp-talk");
  if (b && tp.pos) { b.style.position = "fixed"; b.style.margin = "0"; b.style.left = tp.pos.x + "px"; b.style.top = tp.pos.y + "px"; }
}
document.addEventListener("mousedown", function (ev) {
  var h = ev.target.closest("#tpModal .tp-drag");
  if (!h) { return; }
  var r = h.parentNode.getBoundingClientRect();
  tpDrag = { dx: ev.clientX - r.left, dy: ev.clientY - r.top };
  ev.preventDefault();
});
document.addEventListener("mousemove", function (ev) {
  if (!tpDrag) { return; }
  tp.pos = { x: Math.max(0, Math.min(window.innerWidth - 120, ev.clientX - tpDrag.dx)), y: Math.max(0, Math.min(window.innerHeight - 40, ev.clientY - tpDrag.dy)) };
  tpPlace();
});
document.addEventListener("mouseup", function () { tpDrag = null; });
every("pokerclock", 1000, function () {
  var rs = (tp.room || {}).rounds || [];
  document.querySelectorAll("[data-tpleft]").forEach(function (el) {
    var r = rs.filter(function (x) { return x.id === el.getAttribute("data-tpleft"); })[0], n = tpLeft(r);
    if (n !== null) { el.textContent = tpTick(n); }
  });
}, { hidden: 0 });
function tpPost(path, body) {
  return api("POST", path, Object.assign({ user: blUser(), lens: lensId() }, body));
}
document.addEventListener("click", function (e) {
  var why = e.target.closest("[data-inswhy]");
  if (why) {
    var wk = why.getAttribute("data-inswhy"); insWhy[wk] = !insWhy[wk];
    if (insWhy[wk] && !(ins[wk] && ins[wk].state === "done")) { insGet(wk); }
    tpRender(); tpModal(); blChallengeLocal(); return;
  }
  var go = e.target.closest("[data-tpgo]");
  if (go) {
    showBacklog(); bl.key = go.getAttribute("data-tpgo"); bl.pts = null; bl.pane = "groom"; renderBlPane(); blRenderList(); return;
  }
  var v = e.target.closest("[data-tpvote]"), a = e.target.closest("[data-tp]"), r = tpRound();
  var done = function (x) { if (x && x.change) { blDone(x.change); } if (x && x.note) { blDone(x.note); } tp.room = null; tpPoll(); };
  var tpErr = function (err) {
    var m = $("tpModal");
    if (!m || m.hidden) { return blErr(err); }
    tp.err = err.message || String(err); tpModal();
  };
  var save = function (pts, dissent) { tp.err = ""; return tpPost("/api/poker/agree", { round: r.id, points: pts, dissent: dissent || [] }).then(function (x) { $("tpModal") && ($("tpModal").hidden = true); done(x); }, tpErr); };
  if (v && r) {
    tp.voteErr = "";
    return tpPost("/api/poker/vote", { round: r.id, points: v.getAttribute("data-tpvote") }).then(done, function (err) { tp.voteErr = err.message || String(err); tpRender(); });
  }
  var dc = e.target.closest("[data-tpdis]");
  if (dc) { var du = dc.getAttribute("data-tpdis"); if (dc.checked) { tp.dis[du] = tp.dis[du] || ""; } else { delete tp.dis[du]; } tp.err = ""; return tpModal(); }
  var sv = e.target.closest("[data-tpsave]");
  if (sv && r) { return save(sv.getAttribute("data-tpsave")); }
  if (!a) { return; }
  var act = a.getAttribute("data-tp");
  if (act === "start") {
    var st = blStory(bl.key) || {};
    var who = [].slice.call(document.querySelectorAll("[data-tpwho]:checked")).map(function (c) { return c.getAttribute("data-tpwho"); })
      .concat($("tpExtra").value.split(",").map(function (u) { return u.trim(); }).filter(Boolean));
    return tpPost("/api/poker/start", { key: bl.key, invite: who, seconds: +tpSecs(), story: { summary: st.summary, description: st.description, acceptance: st.acceptance } }).then(done, blErr);
  }
  if (!r) { return; }
  if (act === "close") { tp.popped[r.id] = "closed"; $("tpModal") && ($("tpModal").hidden = true); return; }
  if (act === "talk") { tp.popped[r.id] = "open"; return tpModal(); }
  if (act === "savedis") {
    var dissent = Object.keys(tp.dis).map(function (u) { return { user: u, why: tp.dis[u] }; });
    if (dissent.some(function (d) { return !d.why.trim(); })) { return tpErr(new Error("Write down why each person disagrees before saving.")); }
    return save($("tpPick").value, dissent);
  }
  if (act === "reveal" && r.waiting.length) {
    return askConfirm("Still waiting for " + r.waiting.map(tpName).join(", ") + ". End the vote now?", { title: "Reveal the votes", ok: "End the vote" })
      .then(function (yes) { if (yes) { return tpPost("/api/poker/reveal", { round: r.id }).then(done, blErr); } });
  }
  if (act === "again") { tp.dis = {}; tp.err = ""; $("tpModal") && ($("tpModal").hidden = true); }
  return tpPost("/api/poker/" + act, act === "again" ? { round: r.id, seconds: +tpSecs() } : { round: r.id }).then(done, blErr);
});
document.addEventListener("change", function (e) {
  if (e.target.id === "tpSecs") { localStorage.setItem("sdlc-poker-seconds", e.target.value); tpRender(); }
});
document.addEventListener("input", function (e) {
  var w = e.target.getAttribute && e.target.getAttribute("data-tpwhy");
  if (w !== null && w !== undefined && tp.dis[w] !== undefined) { tp.dis[w] = e.target.value; }
});
var tpLast = 0;
every("poker", 2000, function () { if (tpLive() || Date.now() - tpLast >= 10000) { tpLast = Date.now(); return tpPoll(); } }, { hidden: 0 });

function blDetail() {
  var s = blStory(bl.key), scale = ((bl.data || {}).mode || {}).scale || [1, 2, 3, 5, 8, 13];
  if (!s) { $("blDetail").innerHTML = '<div class="c-empty">Pick a ticket on the left to groom it.</div>'; return; }
  var r = bl.round, dr = bl.drafts[s.key] || {};
  var poker = "";
  if (r && r.key === s.key) {
    poker = '<div class="bl-votes">' + Object.keys(r.votes).map(function (v) { return '<span class="bl-vote">' + esc(v) + ": <b>" + esc(r.votes[v]) + "</b></span>"; }).join("") +
      (r.waiting.length ? '<span class="c-muted">waiting: ' + esc(r.waiting.join(", ")) + "</span>" : "") + "</div>" +
      (r.revealed ? '<div class="c-muted">' + (r.spread ? (r.spread.agree ? "Everyone said " + r.spread.high : "Low " + r.spread.low + " · median " + r.spread.median + " · high " + r.spread.high) : "no votes") + "</div>" : "") +
      '<div class="bl-row bl-scale">' + (r.revealed ? "" : scale.map(function (p) { return '<button type="button" class="a-btn a-btn--outline" data-blvote="' + p + '">' + p + "</button>"; }).join("")) +
      (r.revealed ? '<select id="blAgree" class="a-select">' + scale.map(function (p) { return '<option' + (r.spread && p === r.spread.median ? " selected" : "") + ">" + p + "</option>"; }).join("") + '</select><button type="button" class="a-btn a-btn--primary" id="blAgreeBtn">Agree &amp; preview points</button>' : '<button type="button" class="a-btn a-btn--outline" id="blReveal">Show votes</button>') +
      (r.agreed != null ? '<span class="c-pill c-pill--on">agreed ' + esc(r.agreed) + "</span>" : "") + "</div>" + '<div id="blChallenge"></div>';
  }
  $("blDetail").innerHTML = '<div class="bl-head"><b><a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.key) + "</a></b>" +
    '<span class="c-muted">' + esc(s.status) + " · " + esc(s.sprint || "backlog") + " · " + esc(s.type) + (s.parent ? " · epic " + esc(s.parent) : "") + " · " + esc(s.assignee || "Unassigned") + "</span></div>" +
    '<h3 class="bl-title">' + esc(s.summary) + "</h3>" +
    '<div class="bl-sec"><b>Description</b>' + blEdit("blEdDesc", s.description, dr.description, null, 5) + "</div>" +
    '<div class="bl-sec"><div class="bl-sec__head"><b>Acceptance criteria</b><button type="button" class="a-btn a-btn--outline" id="acrAsk" ' +
    'title="Devin rewrites the AC as numbered business outcomes and asks you what the ticket does not say">Rewrite AC</button></div>' +
    blEdit("blEdAc", s.acceptance, dr.acceptance, AC_PLACEHOLDER, 8) + '<div id="acrBox" class="ins-box"></div><div id="insBox" class="ins-box"></div></div>' +
    '<div class="bl-sec bl-sec--groom"><b>Grooming</b></div>' +
    '<div class="bl-row"><b>Points</b> <span class="bl-scale">' + scale.map(function (p) { return '<button type="button" class="a-btn a-btn--outline' + (String(bl.pts || s.points) === String(p) ? " is-on" : "") + '" data-blpts="' + p + '">' + p + "</button>"; }).join("") + "</span>" +
    '<input id="blPtsOther" class="a-input" style="width:70px" placeholder="other"></div>' + blSprintFix(s, dr) +
    '<div id="tpBox" class="bl-sec"></div>' +
    '<div class="bl-row"><b>Planning poker</b> <input id="blVoters" class="a-input" style="flex:1" placeholder="voters, comma-separated (jira users) — leave blank for anyone"><button type="button" class="a-btn a-btn--outline" id="blPokerStart">' + (r && r.key === s.key ? "New round" : "Start round") + "</button></div>" + poker +
    '<div class="bl-sec bl-save"><b>Save this story</b><div class="c-muted">The description, acceptance criteria, points, sprint and Fix Version you changed go to Jira together, with your name on the comment.</div>' +
    '<div id="blSaveSum"></div><div class="bl-row"><button type="button" class="a-btn a-btn--outline" id="blSavePrev">Preview changes</button>' +
    '<button type="button" class="a-btn a-btn--primary" id="blSave" disabled' + (blLive(s.key) ? "" : ' title="Practice mode: Backlog writes are off for this story"') + '>Save to Jira</button>' +
    '<button type="button" class="a-btn a-btn--ghost" id="blDiscard" title="Throw away the changes to this story that are not in Jira yet">Discard changes</button>' +
    '<span class="c-muted" id="blSaveNote">' + (blLive(s.key) ? "" : "Practice mode: Save to Jira turns on when Backlog writes are on for this story.") + "</span></div></div>" +
    '<div class="bl-row"><b>Notes</b></div><textarea id="blNote" class="a-input" rows="2" placeholder="Meeting notes or a decision for this ticket (becomes a comment; drop a file to attach)"></textarea>' +
    '<div class="bl-row"><input id="blNoteFile" type="file"><button type="button" class="a-btn a-btn--outline" id="blNoteBtn">Preview note</button>' +
    '<button type="button" class="a-btn a-btn--outline" id="blClone">Preview clone</button></div>' +
    (blGrooming() ? "" :
    '<div class="bl-row"><b>Raise</b> <span class="c-muted">a question or clarification (sub-task under this story), an observation, a defect (linked to this story) or a risk — QA and UAT too</span></div>' +
    '<div class="bl-row"><select id="blRaiseKind" class="a-select">' + groomTools().raise.map(function (k) { return '<option value="' + k + '">' + k.charAt(0).toUpperCase() + k.slice(1) + "</option>"; }).join("") + "</select>" +
    '<input id="blRaiseTitle" class="a-input" style="flex:1" placeholder="one line: what is it"><input id="blRaiseTo" class="a-input" style="width:160px" placeholder="to (jira user)">' +
    '<select id="blRaiseSev" class="a-select"><option value="">severity…</option></select><select id="blRaiseEnv" class="a-select"><option value="">seen in…</option></select>' +
    '<select id="blRaiseSpec" class="a-select"><option value="">specialty…</option></select><input id="blRaiseEpisode" class="a-input" list="blEpisodes" style="width:140px" placeholder="episode (EoC)"><datalist id="blEpisodes"></datalist>' +
    '<button type="button" class="a-btn a-btn--primary" id="blRaiseBtn">Preview</button></div>' +
    '<div class="c-muted" id="blRaiseHint">Defects: TennCare SIT/UAT titles become "SIT-TC-PCMH: …", "UAT-TC-EoC: &lt;Episode&gt; - …" on preview; the episode list is read from Jira.</div>' +
    '<textarea id="blRaiseDetail" class="a-input" rows="2" placeholder="Steps / expected / actual, or the question in full"></textarea>') +
    (groomTools().hours && !blGrooming() ?
    '<div class="bl-row"><b>Log hours</b> <span class="c-muted">hours go on the sub-task, not the story</span></div>' +
      '<div class="bl-row"><select id="blHoursOn" class="a-select"><option value="' + esc(s.key) + '">' + esc(s.key) + ' (loading sub-tasks…)</option></select>' +
      '<input id="blHours" class="a-input" style="width:70px" placeholder="1.5"><input id="blHoursDate" class="a-input" type="date" style="width:150px">' +
      '<input id="blHoursNote" class="a-input" style="flex:1" placeholder="what you did"><button type="button" class="a-btn a-btn--primary" id="blHoursBtn">Preview hours</button></div>' : "");
  api("GET", "/api/backlog/raise/options").then(function (o) {
    var sev = $("blRaiseSev"), env = $("blRaiseEnv"); if (!sev || !env) { return; }
    (o.severities || []).forEach(function (v) { var x = document.createElement("option"); x.value = x.textContent = v; sev.appendChild(x); });
    (o.environments || []).forEach(function (v) { var x = document.createElement("option"); x.value = x.textContent = v; env.appendChild(x); });
    var sp = $("blRaiseSpec"); if (sp) { (o.specialties || []).forEach(function (v) { var x = document.createElement("option"); x.value = x.textContent = v; sp.appendChild(x); }); }
  }, function () {});
  api("GET", "/api/backlog/episodes").then(function (d) {
    var dl = $("blEpisodes"); if (!dl) { return; }
    dl.innerHTML = (d.episodes || []).map(function (v) { return '<option value="' + esc(v) + '">'; }).join("");
  }, function () {});
  api("GET", "/api/backlog/subtasks?key=" + encodeURIComponent(s.key)).then(function (d) {
    var sel = $("blHoursOn"); if (!sel) { return; }
    sel.innerHTML = (d.tickets || []).map(function (t) { return '<option value="' + esc(t.key) + '"' + (t.hours_ok ? "" : ' data-warn="1"') + ">" + esc(t.key + " · " + t.type + " · " + t.summary) + (t.hours_ok ? "" : " (story — hours belong on a sub-task)") + "</option>"; }).join("");
    var first = sel.querySelector("option:not([data-warn])"); if (first) { sel.value = first.value; }
  }, function () {});
  $("blNoteFile").addEventListener("change", function () {
    var f = this.files && this.files[0]; if (!f) { return; }
    var rd = new FileReader(); rd.onload = function () { $("blNote").value = String(rd.result || "").slice(0, 20000); $("blNote").dataset.filename = f.name; }; rd.readAsText(f);
  });
  tpRender();
  insRender(); acrRender(); blChallengeLocal();
}
// Description and AC are edited in place; drafts survive a list refresh until Save to Jira writes them.
function blEdit(id, v, draft, placeholder, rows) {
  if ((v === undefined || v === null) && draft === undefined) { return blText(v); }
  var jira = String(v || ""), cur = draft !== undefined ? draft : placeholder && placeholder.test(jira) ? "" : jira;
  var warn = !jira.trim() ? '<div class="bl-warn">Empty in Jira.</div>' : placeholder && placeholder.test(jira) ? '<div class="bl-warn">Still the Jira placeholder text.</div>' : "";
  return warn + '<textarea id="' + id + '" class="a-input bl-edit" rows="' + rows + '">' + esc(cur) + "</textarea>";
}
function blUseAc(key, text) {
  var box = $("blEdAc"); if (!box || !text) { return; }
  box.value = text;
  var d = bl.drafts[key] = bl.drafts[key] || {}; d.acceptance = text; d.suggested = true; blDraftsSave();
  blSaveReset(); box.focus();
}
function blLive(key) { var m = (bl.data || {}).mode || {}; return !!m.writes && (m.allowed || []).indexOf(key) >= 0; }
var BL_PRACTICE = "Practice mode: Save to Jira turns on when Backlog writes are on for this story.";
function blSaveReset() { if ($("blSave")) { $("blSave").disabled = true; $("blSaveSum").innerHTML = ""; $("blSaveNote").textContent = blLive(bl.key) ? "" : BL_PRACTICE; } }
// Sprint and Fix Version for this one story; the Fix Version list is every release already on the team's stories.
function blSprintFix(s, dr) {
  var d = bl.data || {}, rel = {}, cur = (s.releases || []).map(function (r) { return r.name; }).filter(Boolean).join(", ");
  (d.stories || []).forEach(function (x) { (x.releases || []).forEach(function (r) { if (r.name) { rel[r.name] = 1; } }); });
  var pick = dr.sprint || "";
  return '<div class="bl-row"><b>Sprint</b> <select id="blEdSprint" class="a-select"><option value="">Keep: ' + esc(s.sprint || "backlog") + "</option>" +
    '<option value="backlog"' + (pick === "backlog" ? " selected" : "") + ">Backlog (no sprint)</option>" +
    (d.sprints || []).map(function (x) { return '<option value="' + esc(x.id) + '"' + (String(pick) === String(x.id) ? " selected" : "") + ">" + esc(x.name) + " (" + esc(x.state) + ")</option>"; }).join("") +
    ((d.sprints || []).length ? "" : '<option value="" disabled>Sprint list needs the Jira service account on this box</option>') + "</select>" +
    ' <b>Fix Version</b> <input id="blEdFix" class="a-input" style="width:200px" list="blFixList" placeholder="' + esc(cur ? "now: " + cur : "none yet") + '" value="' + esc(dr.fix || "") + '">' +
    '<datalist id="blFixList">' + Object.keys(rel).sort().map(function (n) { return '<option value="' + esc(n) + '">'; }).join("") + "</datalist></div>";
}
function blChanges(s) {
  var out = {}, lines = [], d = $("blEdDesc"), a = $("blEdAc"), other = $("blPtsOther"), pts = (other && other.value.trim()) || bl.pts;
  function n(t) { return String(t || "").split(/\r?\n/).filter(function (l) { return l.trim(); }).length; }
  if (s && d && d.value.trim() !== String(s.description || "").trim()) { out.description = d.value; lines.push(["Description", n(s.description) + " lines \u2192 " + n(d.value) + " lines", d.value]); }
  if (s && a && a.value.trim() !== String(s.acceptance || "").trim()) { out.acceptance = a.value; lines.push(["Acceptance criteria", n(s.acceptance) + " lines \u2192 " + n(a.value) + " lines", a.value]); }
  if (s && pts && String(pts) !== String(s.points || "")) { out.points = pts; lines.push(["Points", (s.points || "none") + " \u2192 " + pts, ""]); }
  var sp = $("blEdSprint"), fx = $("blEdFix"), now = s ? (s.releases || []).map(function (r) { return r.name; }) : [];
  if (s && sp && sp.value) {
    var j = sp.value === "backlog" ? null : ((bl.data || {}).sprints || []).filter(function (x) { return String(x.id) === sp.value; })[0];
    out.sprint = j ? { id: j.id, name: j.name } : "backlog";
    lines.push(["Sprint", (s.sprint || "backlog") + " \u2192 " + (j ? j.name : "backlog"), ""]);
  }
  if (s && fx && fx.value.trim() && now.indexOf(fx.value.trim()) < 0) { out.fix_version = fx.value.trim(); lines.push(["Fix Version", (now.join(", ") || "none") + " \u2192 " + out.fix_version, ""]); }
  return { changes: out, lines: lines };
}
function blSavePreview() {
  var s = blStory(bl.key), c = blChanges(s);
  if (!c.lines.length) { $("blSaveSum").innerHTML = '<div class="c-muted">Nothing changed on this story yet.</div>'; $("blSave").disabled = true; return; }
  if (c.changes.acceptance !== undefined && (!c.changes.acceptance.trim() || AC_PLACEHOLDER.test(c.changes.acceptance))) { blErr(new Error("Write the acceptance criteria first.")); return; }
  $("blSaveSum").innerHTML = '<ul class="bl-save__list">' + c.lines.map(function (l) {
    return "<li><b>" + esc(l[0]) + "</b>: " + esc(l[1]) + (l[2] ? '<details><summary>show</summary><pre class="bl-text">' + esc(l[2]) + "</pre></details>" : "") + "</li>";
  }).join("") + "</ul>";
  var live = blLive(s.key);
  $("blSaveNote").textContent = live ? "Save to Jira writes these now." : BL_PRACTICE;
  $("blSave").disabled = !live;
}
$("blDetail").addEventListener("input", function (e) {
  var id = e.target.id, field = { blEdDesc: "description", blEdAc: "acceptance", blEdSprint: "sprint", blEdFix: "fix" }[id];
  if (!bl.key || (!field && id !== "blPtsOther")) { return; }
  if (field) { var d = bl.drafts[bl.key] = bl.drafts[bl.key] || {}; d[field] = e.target.value; blDraftsSave(); }
  blSaveReset();
});
$("blDetail").addEventListener("change", function (e) { if (e.target.id === "blEdSprint" && bl.key) { (bl.drafts[bl.key] = bl.drafts[bl.key] || {}).sprint = e.target.value; blDraftsSave(); blSaveReset(); } });
// Rewrite AC: one read-only Devin session; its questions open in a window, the answers go back for the final AC.
var acr = {}, acrTimer = null, acrAsked = {};
function acrStory(key) {
  var st = blStory(key) || {}, d = bl.key === key ? $("blEdDesc") : null, a = bl.key === key ? $("blEdAc") : null;
  return { key: key, summary: st.summary, description: d ? d.value : st.description, acceptance: a ? a.value : st.acceptance };
}
function acrGet(key) {
  return api("GET", "/api/backlog/ac-rewrite?key=" + encodeURIComponent(key)).then(function (r) {
    acr[key] = r || {}; acrRender();
    clearTimeout(acrTimer);
    if (r && r.state === "working" && bl.key === key) { acrTimer = setTimeout(function () { acrGet(key); }, 15000); }
  }, function () {});
}
function acrRender() {
  var box = $("acrBox"), s = blStory(bl.key); if (!box || !s) { return; }
  var r = acr[s.key];
  if (r === undefined) { box.innerHTML = ""; acrGet(s.key); return; }
  var link = r.url ? ' <a href="' + esc(r.url) + '" target="_blank" rel="noopener">session</a>' : "";
  if (r.state === "working") { box.innerHTML = '<span class="c-muted">Devin is rewriting the acceptance criteria' + (r.answers && r.answers.length ? " with your answers" : "") + "\u2026" + link + "</span>"; return; }
  if (r.state === "questions") {
    var qs = r.questions || [];
    box.innerHTML = '<div class="ins-ac"><b>Devin has ' + qs.length + (qs.length === 1 ? " question" : " questions") + " before it rewrites the AC</b> " +
      '<button type="button" class="a-btn a-btn--primary" id="acrAnswer">Answer questions</button></div>';
    if (!acrAsked[r.session_id]) { acrAsked[r.session_id] = true; acrDialog(s.key); }
    return;
  }
  if (r.state === "done") {
    box.innerHTML = '<div class="ins-ac"><b>New writing style</b> <span class="c-pill">suggested · not in Jira yet</span><pre class="bl-text">' + esc(r.acceptance) + "</pre>" +
      (r.notes ? '<div class="c-muted">' + esc(r.notes) + "</div>" : "") +
      ((r.moved || []).length ? "<div><b>Moves out of the AC</b><ul>" + r.moved.map(function (m) { return "<li>" + esc(m) + "</li>"; }).join("") + "</ul></div>" : "") +
      '<div class="bl-row"><button type="button" class="a-btn a-btn--primary" id="acrUse">Use this AC</button>' +
      '<span class="c-muted">It replaces the text in the box above; edit it there, then Save to Jira.</span></div></div>';
    return;
  }
  box.innerHTML = r.state === "failed" ? '<span class="bl-over">Devin could not rewrite the AC: ' + esc(r.error || "no answer") + "</span>" : "";
}
function acrDialog(key) {
  var r = acr[key] || {}, qs = r.questions || [], dlg = $("acrDlg");
  if (!qs.length) { return; }
  if (!dlg) {
    dlg = document.createElement("dialog"); dlg.id = "acrDlg"; dlg.className = "acr-dlg"; document.body.appendChild(dlg);
    dlg.addEventListener("click", acrDialogClick);
  }
  dlg.dataset.key = key;
  dlg.innerHTML = "<h3>Questions on " + esc(key) + '</h3><p class="c-muted">Devin needs these to write the acceptance criteria without guessing. Leave one blank if nobody knows yet.</p>' +
    qs.map(function (q, i) { return '<label class="acr-q"><b>' + (i + 1) + ". " + esc(q) + '</b><textarea class="a-input" rows="2" data-acrq="' + i + '"></textarea></label>'; }).join("") +
    '<div class="bl-row"><button type="button" class="a-btn a-btn--primary" id="acrSend">Send answers</button><button type="button" class="a-btn a-btn--outline" id="acrLater">Later</button></div>';
  if (dlg.showModal) { dlg.showModal(); } else { dlg.setAttribute("open", ""); }
}
function acrDialogClick(e) {
  var dlg = $("acrDlg"), key = dlg.dataset.key, r = acr[key] || {};
  if (e.target.id === "acrLater") { dlg.close(); return; }
  if (e.target.id !== "acrSend") { return; }
  var answers = (r.questions || []).map(function (q, i) { var t = dlg.querySelector('[data-acrq="' + i + '"]'); return { question: q, answer: t ? t.value.trim() : "" }; });
  dlg.close();
  api("POST", "/api/backlog/ac-rewrite", { user: blUser(), answers: answers, story: acrStory(key) }).then(function (x) { acr[key] = x; acrRender(); acrGet(key); }, blErr);
}
var GROOM_TOOLS = {
  po_office: { raise: ["question", "risk"], hours: false },
  bsa: { raise: ["question", "clarification"], hours: false }
};
function groomTools() {
  return GROOM_TOOLS[lensId()] || { raise: ["question", "clarification", "observation", "defect", "risk"], hours: true };
}
function blText(v, placeholder) {
  if (v === undefined || v === null) { return '<div class="c-muted">Not read yet. Press Refresh to read it from Jira.</div>'; }
  if (!String(v).trim()) { return '<div class="bl-warn">Empty in Jira.</div>'; }
  return (placeholder && placeholder.test(v) ? '<div class="bl-warn">Still the Jira placeholder text.</div>' : "") + '<div class="bl-text">' + esc(v) + "</div>";
}
function renderBlPane() {
  document.querySelectorAll("#backlogView [data-blview]").forEach(function (el) { el.hidden = el.dataset.blview !== bl.pane; });
}
// Grooming prep: Resource 17's routine before a grooming call (tools/grooming_prep.py), with a button per row.
function blGroomPrep() {
  var el = $("blGroomPrep");
  el.innerHTML = '<div class="bl-head"><b>Grooming prep</b></div><div class="c-muted">Reading the backlog, the roadmap and the teams…</div>';
  api("GET", "/api/backlog/grooming-prep?user=" + encodeURIComponent(blUser())).then(function (d) {
    el.innerHTML = '<div class="bl-head"><b>Grooming prep</b> <button type="button" class="a-btn a-btn--outline" data-blpane="groomprep">Refresh</button>' +
      ' <button type="button" class="a-btn a-btn--outline" data-navback>Back</button></div>' +
      (d.error ? '<div class="c-err">' + esc(d.error) + "</div>" : "") +
      (d.pending ? '<div class="c-muted">Devin Cloud is still reading the backlog; press Refresh in a minute.</div>' : "") + d.html;
  }, function (e) { el.innerHTML = '<div class="c-err">' + esc(e.message) + "</div>"; });
}
// Scrum Master follow-ups: the leave grid (the Confluence sprint leave page) and the one-story-at-a-time list.
var fu = { leave: null, flow: null };
function blFollow(token) {
  var el = $("blFollow");
  el.innerHTML = '<h2 class="c-card__title">Scrum Master follow-ups</h2><div class="c-muted">Loading…</div>';
  api("GET", "/api/backlog/leave" + (token ? "?sprint=" + encodeURIComponent(token) : "")).then(function (v) { fu.leave = v; fuRender(); }, function (e) { fu.leave = { error: e.message, sprints: [] }; fuRender(); });
  api("GET", "/api/backlog/followups").then(function (f) { fu.flow = f; fuRender(); }, function (e) { fu.flow = { error: e.message }; fuRender(); });
}
function fuPrevSprint(v) {
  function n(t) { return String(t).split(".").reduce(function (a, x) { return a * 100 + (+x || 0); }, 0); }
  var older = (v.sprints || []).map(function (s) { return s.token; }).filter(function (t) { return n(t) < n(v.token); }).sort(function (a, b) { return n(b) - n(a); });
  return older[0] || "";
}
function fuHours(v, p) { return (v.days.length - (p.off || []).length) * (+v.sprint.productive_hours || 6) * (+p.allocation || 0) / 100; }
function fuStickHead(ev) {
  var wrap = document.querySelector("#blFollow .fu-scroll"), src = ev && ev.target && ev.target.nodeType === 1 ? ev.target : null;
  if (!wrap || !wrap.offsetParent || src === wrap || (src && !src.contains(wrap))) { return; }
  fu.pane = src;
  var top = src ? Math.max(0, src.getBoundingClientRect().top) : 0, box = wrap.getBoundingClientRect(), head = wrap.querySelector("thead");
  var shift = Math.max(0, Math.min(top - box.top, box.height - (head ? head.offsetHeight : 0)));
  wrap.querySelectorAll("thead th").forEach(function (th) { th.style.transform = shift ? "translateY(" + shift + "px)" : ""; });
}
document.addEventListener("scroll", fuStickHead, true);
function fuRender() {
  var v = fu.leave || {}, f = fu.flow, part = bl.part || "";
  var h = '<h2 class="c-card__title">' + ({ leave: "Time off", standup: "Stand-up check" }[part] || "Scrum Master follow-ups") + "</h2>";
  if (part === "leave") {
    h += '<p class="c-muted">Longer time off, and who covers your stories, questions and approvals while you are away: <button type="button" class="a-btn a-btn--outline" data-wbmore="' + esc(state.task || "") + '">Vacation planner</button></p>';
  }
  if (part !== "standup") {
  h += '<p class="c-muted">Leave is kept on the Confluence page' + (v.page ? ' <a href="' + esc(v.page) + '" target="_blank" rel="noopener">' + esc(v.page_title || "Sprint Leave") + "</a>" : " " + esc(v.page_title || "Sprint Leave")) +
    ". Click a day to mark it off; tick No leave when someone has said they take none. Capacity is days in × productive hours × % on project, and hours ÷ 8 are the points.</p>";
  if (v.error) { h += '<div class="c-banner c-banner--warn">' + esc(v.error) + "</div>"; }
  if (v.sprints && v.sprints.length) {
    h += '<label>Sprint <select id="fuSprint">' + v.sprints.map(function (s) { return '<option value="' + esc(s.token) + '"' + (s.token === v.token ? " selected" : "") + ">" + esc(s.token + (s.state === "active" ? " (active)" : "") + " · " + (s.start || "?") + " to " + (s.end || "?")) + "</option>"; }).join("") + "</select></label> ";
  }
  if (v.sprint) {
    var total = 0, quiet = [];
    h += (v.saved ? "" : ' <span class="c-muted">Not on the page yet: this is the roster, nobody has answered.</span>') +
      '<div class="bl-scroll fu-scroll"><table class="c-table fu-grid"><thead><tr><th>Team member</th><th>% on project</th>' +
      v.days.map(function (d, j) { var x = new Date(d + "T00:00:00"); return '<th title="' + esc(d) + '"' + (j && x.getDay() === 1 ? ' class="fu-wk"' : "") + ">" + "SMTWTFS".charAt(x.getDay()) + "<br>" + x.getDate() + "</th>"; }).join("") +
      "<th>No leave</th><th>Note</th><th>Days in</th><th>Hours</th></tr></thead><tbody>";
    v.sprint.people.forEach(function (p, i) {
      var hrs = fuHours(v, p); total += hrs;
      if (!(p.off || []).length && !p.no_leave) { quiet.push(p.name); }
      h += "<tr><td>" + esc(p.name) + '</td><td><input type="number" min="0" max="100" class="fu-alloc" data-fu="' + i + '" value="' + esc(p.allocation) + '" style="width:4.5em"></td>' +
        v.days.map(function (d, j) { var off = (p.off || []).indexOf(d) >= 0; return "<td" + (j && new Date(d + "T00:00:00").getDay() === 1 ? ' class="fu-wk"' : "") + '><button type="button" class="fu-day' + (off ? " is-off" : "") + '" data-fu="' + i + '" data-day="' + esc(d) + '" title="' + esc(d) + (off ? " off" : " in") + '">' + (off ? "0" : "1") + "</button></td>"; }).join("") +
        '<td><input type="checkbox" class="fu-none" data-fu="' + i + '"' + (p.no_leave ? " checked" : "") + ((p.off || []).length ? " disabled" : "") + '></td><td><input class="fu-note" data-fu="' + i + '" value="' + esc(p.note || "") + '" placeholder="half day, public holiday…"></td><td>' +
        (v.days.length - (p.off || []).length) + "</td><td>" + Math.round(hrs * 10) / 10 + "</td></tr>";
    });
    h += "</tbody></table></div>";
    h += "<p><b>Team: " + Math.round(total * 10) / 10 + " hours = " + Math.round(total / 8 * 10) / 10 + " story points</b> over " + v.days.length + " working days.</p>";
    h += quiet.length ? '<p class="c-muted">Not answered yet (' + quiet.length + "): " + esc(quiet.join(", ")) + "</p>" : '<p class="c-muted">Everyone has answered.</p>';
    var prev = fuPrevSprint(v);
    h += (prev ? '<button type="button" class="a-btn a-btn--outline" id="fuCopy" data-from="' + esc(prev) + '" title="Takes each person\'s % on project from ' + esc(prev) + '; leave days are not copied">Copy % on project from ' + esc(prev) + "</button> " : "") +
      '<button type="button" class="a-btn" id="fuSave">Save to Confluence</button> <a class="a-btn a-btn--outline" href="/api/backlog/sprint-sheet.html?sprint=' + encodeURIComponent(v.token) + '" target="_blank" rel="noopener">Sprint planning sheet</a> <a class="a-btn a-btn--outline" href="/api/backlog/leave.xlsx?sprint=' + encodeURIComponent(v.token) + '">Download capacity sheet</a> <span id="fuSaved" class="c-muted">' + esc(fu.msg || "") + "</span>";
  }
  }
  if (part !== "leave") {
  h += '<h3>In progress: one story at a time</h3>';
  if (!f) { h += '<div class="c-muted">Loading…</div>'; }
  else if (f.error) { h += '<div class="c-banner c-banner--warn">' + esc(f.error) + "</div>"; }
  else {
    function row(r, extra) { return '<div class="c-item"><span class="k">' + esc(r.key) + "</span> " + esc(r.summary) + ' <span class="c-muted">' + esc(r.owner) + " · " + esc(r.status) + " · last change " + esc(r.last || "?") + "</span> " + (extra || "") + "</div>"; }
    function nudge(key, text) { return '<button type="button" class="a-btn a-btn--outline fu-nudge" data-key="' + esc(key) + '" data-text="' + esc(text) + '">Draft nudge</button>'; }
    h += "<h4>More than one story In Progress</h4>" + (f.parallel.length ? f.parallel.map(function (g) {
      var first = g.stories[0], rest = g.stories.slice(1).map(function (r) { return r.key; });
      return "<div><b>" + esc(g.owner) + "</b>" + g.stories.map(function (r) { return row(r); }).join("") +
        nudge(first.key, "You have " + g.stories.map(function (r) { return r.key; }).join(", ") + " In Progress. Please finish " + first.key + " first and move " + rest.join(", ") + " back to To Do until then; if one is waiting on someone, raise a Question sub-task so it goes On Hold.") + "</div>";
    }).join("") : '<div class="c-muted">Nobody.</div>');
    h += "<h4>In Progress, nothing changed for " + f.idle_days + " working days or more</h4>" + (f.idle.length ? f.idle.map(function (r) {
      return row(r, nudge(r.key, r.key + " has been In Progress with no change for " + r.quiet + " working days. If you are waiting on someone, raise a Question sub-task so it goes On Hold; if not, please log today's work."));
    }).join("") : '<div class="c-muted">None.</div>');
    h += "<h4>Waiting on a question or approval, should be On Hold</h4>" + (f.hold.length ? f.hold.map(function (r) {
      var why = "waiting on " + r.waits.map(function (w) { return w.on + " — " + w.key + " (" + w.kind + ")"; }).join("; ");
      return row(r, '<span class="c-muted">' + esc(why) + '</span> <button type="button" class="a-btn a-btn--outline fu-hold" data-key="' + esc(r.key) + '" data-why="' + esc(why) + '">Put on hold</button>');
    }).join("") : '<div class="c-muted">None.</div>');
    h += "<h4>On Hold, nothing left to wait on</h4>" + (f.resume.length ? f.resume.map(function (r) {
      return row(r, '<button type="button" class="a-btn a-btn--outline fu-resume" data-key="' + esc(r.key) + '">Back to In Progress</button>');
    }).join("") : '<div class="c-muted">None.</div>');
    h += "<h4>On Hold</h4>" + (f.on_hold.length ? f.on_hold.map(function (r) { return row(r, '<span class="c-muted">waiting on ' + esc(r.waits.map(function (w) { return w.on + " (" + w.key + ")"; }).join(", ")) + "</span>"); }).join("") : '<div class="c-muted">None.</div>');
    var nudges = {
      subtasks: function (r) { return r.key + " has no sub-tasks. Please add them, each with an original estimate and the AI label (AI-Used or AI-NA)."; },
      story_label: function (r) { return "Please add the AI label to " + r.key + ": AI-Used or AI-NA, in exactly that case."; },
      label: function (r) { return "Please add the AI label to " + r.key + ": AI-Used or AI-NA, in exactly that case."; },
      estimate: function (r) { return r.key + " is AI-Used but has no original estimate. Please set it so the hours can count towards AI efficiency."; },
      over: function (r) { return r.key + " has more hours logged than its original estimate, so it is left out of AI efficiency (exempted). Please add a note on why it took longer."; },
      closed_no_time: function (r) { return r.key + " is closed with no hours logged. Please log the time you spent on it."; },
      no_time: function (r) { return r.key + " is In Progress with no time logged. Please log your hours on its sub-tasks each day you work on it."; },
      close_story: function (r) { return "Every sub-task on " + r.key + " is closed. If the work is done, please move the story on; if not, add the sub-task that is left."; },
      open_subtasks: function (r) { return r.check + ". Please close them or say what is left."; }
    };
    function gapRow(r) {
      var fix = "";
      if (r.code === "story_label" || r.code === "label") {
        fix = ["AI-Used", "AI-NA"].map(function (l) { return '<button type="button" class="a-btn a-btn--outline fu-label" data-key="' + esc(r.key) + '" data-label="' + l + '">Add ' + l + "</button>"; }).join(" ");
      } else if (r.code === "estimate") {
        fix = '<input type="number" min="0.5" max="200" step="0.5" class="fu-est-h" data-key="' + esc(r.key) + '" placeholder="hours" style="width:5em"> <button type="button" class="a-btn a-btn--outline fu-est" data-key="' + esc(r.key) + '">Set estimate</button>';
      }
      return '<div class="c-item"><span class="k">' + esc(r.key) + "</span> " + esc(r.summary) + ' <span class="c-muted">' + esc(r.owner) + " · " + esc(r.status) + "</span> <b>" + esc(r.check) + "</b> " + fix + " " + (nudges[r.code] ? nudge(r.key, nudges[r.code](r)) : "") + "</div>";
    }
    h += "<h3>Before stand-up: what is missing in the sprint</h3>" + (f.checks_error ? '<div class="c-banner c-banner--warn">' + esc(f.checks_error) + "</div>" : "") +
      ((f.gaps || []).length ? f.gaps.map(gapRow).join("") : '<div class="c-muted">Nothing missing: every story has sub-tasks, its AI label and time logged, and every sub-task has its AI label, estimate and hours.</div>');
    var over = (f.load || []).filter(function (r) { return r.over > 0; });
    h += "<h4>More points than their capacity after leave</h4>" + (over.length ? over.map(function (r) {
      return '<div class="c-item"><b>' + esc(r.owner) + "</b> " + esc(r.points) + " points against " + esc(r.capacity) + ' of capacity <span class="c-muted">(' + esc(r.days_off) + " days off; " + esc(r.keys.join(", ")) + ")</span> " +
        (r.keys.length ? nudge(r.keys[0], "You have " + r.points + " story points in " + (f.sprint || "this sprint") + " (" + r.keys.join(", ") + ") against " + r.capacity + " points of capacity after leave. How do you plan to handle it: move a story out, pair with someone, or split one?") : "") + "</div>";
    }).join("") : '<div class="c-muted">Nobody.</div>');
    var waiting = f.unanswered || [];
    h += "<h4>Not answered about leave yet</h4>" + (waiting.length ? '<div class="c-item">' + esc(waiting.join(", ")) + '</div><textarea readonly rows="2" style="width:100%">' +
      esc("Please mark your leave for " + (f.sprint || "the next sprint") + " on the " + (v.page_title || "Sprint Leave") + " page" + (v.page ? " (" + v.page + ")" : "") + ", or tell me you are taking none, so the capacity is right before planning.") +
      '</textarea><span class="c-muted">Send this in Teams; leave is not a Jira ticket.</span>' : '<div class="c-muted">Everyone has answered.</div>');
    h += '<div id="fuNudge" hidden><textarea id="fuNudgeText" rows="3" style="width:100%"></textarea><button type="button" class="a-btn" id="fuNudgeSend">Add as a comment</button> <span class="c-muted">Shown as a preview first; written to Jira only when Backlog writes are on.</span></div>';
  }
  }
  $("blFollow").innerHTML = h;
  fuStickHead({ target: fu.pane });
}
document.addEventListener("click", function (ev) {
  var t = ev.target, v = fu.leave;
  if (!t.closest || !t.closest("#blFollow")) { return; }
  if (t.classList.contains("fu-day") && v) {
    var p = v.sprint.people[+t.dataset.fu], d = t.dataset.day, off = p.off || [];
    p.off = off.indexOf(d) >= 0 ? off.filter(function (x) { return x !== d; }) : off.concat([d]).sort();
    if (p.off.length) { p.no_leave = false; }
    fuRender();
  } else if (t.id === "fuCopy" && v) {
    t.disabled = true;
    api("GET", "/api/backlog/leave?sprint=" + encodeURIComponent(t.dataset.from)).then(function (old) {
      var by = {}; ((old.sprint || {}).people || []).forEach(function (p) { by[p.name] = p.allocation; });
      var n = 0; v.sprint.people.forEach(function (p) { if (by[p.name] !== undefined && by[p.name] !== null) { p.allocation = by[p.name]; n += 1; } });
      fu.msg = "Copied % on project for " + n + " people from " + t.dataset.from + ". Press Save to Confluence to keep it.";
      fuRender(); fu.msg = "";
    }, function (e) { fu.msg = e.message; fuRender(); fu.msg = ""; });
  } else if (t.id === "fuSave" && v) {
    $("fuSaved").textContent = "Saving…";
    api("POST", "/api/backlog/leave", { token: v.token, sprint: v.sprint, user: blUser() }).then(function (r) { v.saved = true; $("fuSaved").textContent = "Saved, page version " + r.version + "."; }, function (e) { $("fuSaved").textContent = e.message; });
  } else if (t.classList.contains("fu-nudge")) {
    $("fuNudge").hidden = false; $("fuNudge").dataset.key = t.dataset.key; $("fuNudgeText").value = t.dataset.text; $("fuNudgeText").focus();
  } else if (t.id === "fuNudgeSend") {
    api("POST", "/api/backlog/note", { key: $("fuNudge").dataset.key, text: $("fuNudgeText").value, user: blUser() }).then(function (c) { $("fuNudge") && ($("fuNudge").hidden = true); blDone(c); }, blErr);
  } else if (t.classList.contains("fu-label")) {
    api("POST", "/api/backlog/ai-label", { key: t.dataset.key, label: t.dataset.label, user: blUser() }).then(function (c) { blDone(c); }, blErr);
  } else if (t.classList.contains("fu-est")) {
    var hrs = document.querySelector('.fu-est-h[data-key="' + t.dataset.key + '"]');
    api("POST", "/api/backlog/estimate", { key: t.dataset.key, hours: hrs && hrs.value, user: blUser() }).then(function (c) { blDone(c); }, blErr);
  } else if (t.classList.contains("fu-hold")) {
    api("POST", "/api/backlog/hold", { key: t.dataset.key, why: t.dataset.why, user: blUser() }).then(function (c) { blDone(c); blFollow(v && v.token); }, blErr);
  } else if (t.classList.contains("fu-resume")) {
    api("POST", "/api/backlog/resume", { key: t.dataset.key, user: blUser() }).then(function (c) { blDone(c); blFollow(v && v.token); }, blErr);
  }
});
document.addEventListener("change", function (ev) {
  var t = ev.target, v = fu.leave;
  if (!t.closest || !t.closest("#blFollow")) { return; }
  if (t.id === "fuSprint") { blFollow(t.value); return; }
  if (!v || !v.sprint) { return; }
  var p = v.sprint.people[+t.dataset.fu];
  if (t.classList.contains("fu-none")) { p.no_leave = t.checked; fuRender(); }
  if (t.classList.contains("fu-alloc")) { p.allocation = Math.max(0, Math.min(100, +t.value || 0)); fuRender(); }
  if (t.classList.contains("fu-note")) { p.note = t.value; }
});
function openBlPane(pane, part) {
  if ($("backlogView").hidden) { showBacklog(true); }
  bl.pane = pane; bl.part = part || ""; renderBlPane();
  navPush(pane === "groom" ? "#backlog" : "#backlog/" + pane);
  if (pane === "calendar") { blCalendar(); }
  if (pane === "plan") { blPlan(); }
  if (pane === "followups") { blFollow(); }
  if (pane === "groomprep") { blGroomPrep(); }
  if (pane === "create") { ciRender(); $("ciText").focus(); }
}
// "26.4.2(10/1-10/21)" → {token, start, end}; Jira spells the same sprint several ways.
function sprintOf(name) {
  var m = /(\d{2})\.(\d)\.(\d+)\s*\(\s*(\d{1,2})\/(\d{1,2})\s*-\s*(\d{1,2})\/(\d{1,2})\s*\)/.exec(name || "");
  if (!m) { var t = /(\d{2})\.(\d)\.(\d+)/.exec(name || ""); return t ? { token: t[0], start: null, end: null } : null; }
  var y = 2000 + +m[1];
  return { token: m[1] + "." + m[2] + "." + m[3], start: new Date(y, +m[4] - 1, +m[5]), end: new Date(+m[6] < +m[4] ? y + 1 : y, +m[6] - 1, +m[7]) };
}
function blCalendar() {
  var d = bl.data || {}, rows = {}, loose = { n: 0, pts: 0 }, today = new Date(), day = 864e5;
  var vel = (d.mode || {}).velocity;
  function row(name) {
    var sp = sprintOf(name); if (!sp) { return null; }
    return rows[sp.token] || (rows[sp.token] = { token: sp.token, start: sp.start, end: sp.end, n: 0, pts: 0, open: 0, releases: {} });
  }
  (d.sprints || []).forEach(function (s) {
    var r = row(s.name); if (!r) { return; }
    if (s.start) { r.start = new Date(s.start + "T00:00:00"); }
    if (s.end) { r.end = new Date(s.end + "T00:00:00"); }
    r.active = s.state === "active";
  });
  (d.stories || []).forEach(function (s) {
    var r = s.sprint ? row(s.sprint) : null, pts = parseFloat(s.points) || 0;
    if (!r) { loose.n += 1; loose.pts += pts; return; }
    r.n += 1; r.pts += pts; if (!pts) { r.open += 1; }
  });
  function key(tok) { return tok.split(".").reduce(function (n, x) { return n * 100 + +x; }, 0); }
  var list = Object.keys(rows).map(function (k) { return rows[k]; }).sort(function (a, b) { return key(a.token) - key(b.token); });
  list.forEach(function (r, i) {
    var prev = list[i - 1];
    if (!r.start && prev && prev.end) { r.start = new Date(prev.end.getTime() + day); r.end = new Date(r.start.getTime() + 20 * day); r.guessed = true; }
  });
  (d.stories || []).forEach(function (s) {
    (s.releases || []).forEach(function (v) {
      if (!v.date) { return; }
      var at = new Date(v.date + "T00:00:00");
      list.forEach(function (r) { if (r.start && r.end && at >= r.start && at <= r.end) { r.releases[(v.name && v.name !== v.date ? v.name + " · " : "") + fmtDay(at)] = 1; } });
    });
  });
  var last = list[list.length - 1];
  for (var i = 0; last && last.end && i < 3; i += 1) {
    var st = new Date(last.end.getTime() + day), en = new Date(st.getTime() + 20 * day);
    last = { token: "projected", start: st, end: en, n: 0, pts: 0, open: 0, releases: {}, projected: true };
    list.push(last);
  }
  var body = list.map(function (r) {
    var active = r.active || (r.start && r.end && today >= r.start && today < new Date(r.end.getTime() + day));
    var left = active ? Math.max(0, Math.ceil((r.end - today) / day)) : null;
    var pct = vel ? Math.min(100, Math.round(100 * r.pts / vel)) : 0;
    return '<tr class="' + (active ? "is-active" : "") + (r.projected ? " is-projected" : "") + '"' + (r.projected ? "" : ' data-blsprint="' + esc(r.token) + '"') + ">" +
      "<td><b>" + esc(r.projected ? "next (projected)" : r.token) + "</b>" + (active ? ' <span class="c-pill c-pill--on">active · ' + left + " days left</span>" : "") + "</td>" +
      "<td>" + (r.start ? fmtDay(r.start) + " – " + fmtDay(r.end) + (r.guessed ? ' <span class="c-muted">(21-day cadence)</span>' : "") : "dates not in Jira") + "</td>" +
      "<td>" + (r.projected ? "" : r.n + (r.open ? ' <span class="c-muted">(' + r.open + " unsized)</span>" : "")) + "</td>" +
      "<td>" + (r.projected ? "" : '<div class="bl-bar"><span style="width:' + pct + '%"' + (vel && r.pts > vel ? ' class="is-over"' : "") + "></span></div>" + r.pts + (vel ? " / " + vel : "")) + "</td>" +
      "<td>" + esc(Object.keys(r.releases).join(", ")) + "</td></tr>";
  }).join("");
  $("blCalendar").innerHTML = '<div class="bl-head"><b>Sprint calendar</b> <button type="button" class="a-btn a-btn--outline" data-navback>Back</button></div>' +
    '<p class="c-muted">From the tickets on this screen: the backlog plus the open and future sprints. ' +
    (vel ? "Velocity " + vel + " points a sprint, from the roadmap year plan." : "No velocity set in the roadmap year plan.") + " Click a sprint to filter the list to it.</p>" +
    (list.length ? '<table class="bl-cal"><thead><tr><th>Sprint</th><th>Dates</th><th>Stories</th><th>Points</th><th>Releases</th></tr></thead><tbody>' + body +
      '<tr data-blsprint="backlog"><td><b>Backlog</b></td><td>no sprint</td><td>' + loose.n + "</td><td>" + loose.pts + "</td><td></td></tr></tbody></table>"
      : '<div class="c-empty">' + (d.pending ? "Devin is reading the backlog for you…" : (d.error || jiraDown()) && !(d.stories || []).length ? "Jira isn't reachable right now, so there are no sprints to show." : "No sprints found on these tickets.") + "</div>");
}
function fmtDay(dt) { return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
function blDone(change) {
  blPreviews();
  if (change && change.status === "applied") { blLoad(true); }
}
$("blIntro").title = "Click to read all of it";
$("blIntro").addEventListener("click", function () { this.classList.toggle("is-open"); });
function blPreviews() {
  return api("GET", "/api/backlog/previews").then(function (d) {
    var rows = d.previews || [];
    $("blPrevCard").hidden = !rows.length;
    $("blPreviews").innerHTML = rows.length ? rows.map(function (c) {
      return '<details class="bl-prev"><summary><span class="s-' + esc(c.status) + '">' + esc(c.status) + "</span> · " + esc(c.kind) + " · " + esc(c.title) + ' <span class="c-muted">' + esc(c.by || "?") + " · " + fmtDate(c.at) + "</span></summary>" +
        (c.note ? '<div class="c-muted">' + esc(c.note) + "</div>" : "") +
        ((c.checks || []).length ? '<div>' + c.checks.map(function (k) { return '<div class="bl-check ' + esc(k.severity) + '">' + esc(k.text) + "</div>"; }).join("") + "</div>" : "") +
        "<pre>" + esc(JSON.stringify(c.calls, null, 1)) + "</pre></details>";
    }).join("") : '<div class="c-empty">Nothing previewed yet.</div>';
  }, blErr);
}
function blDraftFromNotes() {
  var notes = $("blNotes").value.trim(); if (!notes) { return; }
  var lines = notes.split(/\r?\n/).map(function (l) { return l.trim(); }).filter(Boolean);
  var title = (lines[0] || "").replace(/^[#*\-\s]+/, "").slice(0, 120);
  var acs = lines.filter(function (l) { return /^(\d+[.)]|[-*•]|\[ ?\]|AC[: ]|should|must|when |given )/i.test(l); }).map(function (l) { return l.replace(/^(\d+[.)]|[-*•]|\[ ?\]|AC[: ])\s*/i, ""); });
  var body = lines.slice(1).filter(function (l) { return acs.indexOf(l.replace(/^(\d+[.)]|[-*•]|\[ ?\]|AC[: ])\s*/i, "")) < 0; }).join("\n");
  var ph = $("blPhase").value;
  $("blSummary").value = title + ($("blType").value === "Story" && ph && !/\s-\s*[A-Za-z]+\s*$/.test(title) ? " - " + ph : "");
  $("blDesc").value = body;
  $("blAc").value = acs.map(function (a, i) { return (i + 1) + ". " + a; }).join("\n");
  blCheckDraft();
}
api("GET", "/api/backlog/specialties").then(function (r) {
  (r.specialties || []).forEach(function (n) { var o = document.createElement("option"); o.value = o.textContent = n; $("blSpecialty").appendChild(o); });
}, function () {});
$("blSpecialty").addEventListener("change", function () {
  var sp = $("blSpecialty").value, t = $("blSummary").value.replace(/^[A-Za-z]+\s+-\s+/, "");
  if (sp) { $("blSummary").value = sp + " - " + t; }
});
function blDraft() {
  var labels = [$("blAiUsed").checked ? "AI-Used" : "AI-NA", "sdlc-workbench"];
  var subs = $("blSubtasks").value.split(/\r?\n/).map(function (l) { return l.trim(); }).filter(Boolean).map(function (l) {
    var m = l.match(/^(.*?)\s*\|\s*([\d.]+)\s*h?\s*$/); return m ? { summary: m[1], hours: parseFloat(m[2]) } : { summary: l };
  });
  return { type: $("blType").value, summary: $("blSummary").value.trim(), description: $("blDesc").value, acceptance: $("blAc").value,
    blocked_by: $("blBlockedBy").value.split(",").map(function (k) { return k.trim(); }).filter(Boolean), order_why: $("blOrderWhy").value,
    epic: $("blEpic").value, priority: $("blPriority").value, labels: labels, points: $("blPoints").value ? Number($("blPoints").value) : null,
    subtasks: subs.length ? subs : null };
}
function blSubPlan(useDefault) {
  var d = blDraft(); if (useDefault) { d.subtasks = []; }
  if (d.type === "Epic") { return; }
  return api("POST", "/api/backlog/subtask-plan", { draft: d }).then(function (r) {
    $("blHoursTotal").textContent = r.hours ? r.hours + "h" : "?";
    if (useDefault || (d.subtasks && d.subtasks.length)) {
      $("blSubtasks").value = (r.subtasks || []).map(function (t) { return t.summary + " | " + t.hours + "h"; }).join("\n");
    }
  }, function () {});
}
$("blPoints").addEventListener("change", function () { blSubPlan(false); });
$("blSubDefault").addEventListener("click", function () { blSubPlan(true); });
function blRenderChecks(checks) {
  $("blChecks").innerHTML = checks.length ? checks.map(function (k) { return '<div class="bl-check ' + esc(k.severity) + '">' + esc(k.text) + "</div>"; }).join("") : '<div class="c-muted">The rule book is happy with this draft.</div>';
}
function blCheckDraft() { return api("POST", "/api/backlog/precheck", { draft: blDraft() }).then(function (d) { blRenderChecks(d.checks || []); }, blErr); }
$("navBacklog").addEventListener("click", function () {
  state.task = null; renderTasks();
  if (bl.taskFilter && bl.filter === bl.taskFilter) { bl.filter = ""; $("blFilter").value = ""; if (bl.data) { blRenderList(); } }
  bl.taskFilter = null;
  showBacklog();
});
$("storyHours").addEventListener("click", function () {
  var key = state.story && state.story.key; showBacklog();
  if (key) { bl.key = key; bl.filter = key; $("blFilter").value = key; }
});
$("blRefresh").addEventListener("click", function () { blLoad(true); });
bl.sort = (window.localStorage && localStorage.getItem("blSort")) || "";
$("blSort").value = bl.sort;
$("blSort").addEventListener("change", function () { bl.sort = this.value; if (window.localStorage) { localStorage.setItem("blSort", bl.sort); } blRenderList(); });
$("blList").addEventListener("keydown", function (e) {
  var it = e.target.classList && e.target.classList.contains("bl-item") ? e.target : null;
  if (it && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); it.click(); }
});
$("blBack").addEventListener("click", function () { navBack(); });
$("blGroupBy").value = bl.group;
$("blGroupBy").addEventListener("change", function () {
  bl.group = this.value;
  if (window.localStorage) { localStorage.setItem("blGroup", bl.group); }
  blRenderList();
});
$("blChips").addEventListener("click", function (e) {
  var t = e.target.closest("[data-blflag]"); if (!t) { return; }
  bl.flag = bl.flag === t.dataset.blflag ? "" : t.dataset.blflag;
  blRenderList();
});
$("blPlan").addEventListener("click", function (e) {
  var t = e.target.closest("[data-blpick]");
  if (t) {
    bl.sel = {};
    t.dataset.blpick.split(",").filter(Boolean).forEach(function (k) { bl.sel[k] = true; });
    if (t.dataset.blto) { $("blSprintTo").value = t.dataset.blto; }
    bl.flag = ""; bl.filter = ""; $("blFilter").value = "";
    blRenderList(); openBlPane("groom");
    return;
  }
  t = e.target.closest("[data-blfilter]");
  if (t) { bl.filter = t.dataset.blfilter; $("blFilter").value = bl.filter; blRenderList(); openBlPane("groom"); return; }
  t = e.target.closest("[data-blkey]");
  if (t) { bl.key = t.dataset.blkey; blRenderList(); openBlPane("groom"); blDetail(); }
});
$("blCalendar").addEventListener("click", function (e) {
  var t = e.target.closest("[data-blsprint]"); if (!t) { return; }
  bl.filter = t.getAttribute("data-blsprint"); $("blFilter").value = bl.filter; blRenderList();
  openBlPane("groom");
});
$("blFilter").addEventListener("input", function () { bl.filter = this.value; blRenderList(); });
$("blSprintTo").addEventListener("change", blSelCount);
$("blBulkField").addEventListener("change", blBulkValue);
$("blBulkPreview").addEventListener("click", function () {
  blErr(null);
  api("POST", "/api/backlog/bulk", blBulkBody(false)).then(blBulkShow, blErr);
});
$("blBulkBox").addEventListener("click", function (e) {
  if (e.target.id === "blBulkCancel") { $("blBulkBox").hidden = true; return; }
  if (e.target.id !== "blBulkSend") { return; }
  e.target.disabled = true;
  api("POST", "/api/backlog/bulk", blBulkBody(true)).then(function (c) { $("blBulkBox").hidden = true; blClearSel(); blDone(c); }, function (err) { e.target.disabled = false; blErr(err); });
});
$("blViews").addEventListener("change", function () {
  var v = blViewsAll()[+this.value]; $("blViewDel").hidden = !v;
  if (v) { blApplyView(v); $("blViewName").value = v.name; }
});
$("blViewSave").addEventListener("click", function () {
  var name = $("blViewName").value.trim(); if (!name) { $("blViewName").focus(); return; }
  var all = blViewsAll().filter(function (v) { return v.name !== name; });
  all.push(blViewNow(name)); localStorage.setItem("sdlc-blviews", JSON.stringify(all)); blRenderViews(name);
});
$("blViewDel").addEventListener("click", function () {
  var all = blViewsAll(), i = +$("blViews").value; if (!all[i]) { return; }
  all.splice(i, 1); localStorage.setItem("sdlc-blviews", JSON.stringify(all)); $("blViewName").value = ""; blRenderViews();
});
$("blViewLink").addEventListener("click", function () {
  var btn = this, url = location.origin + "/#blview=" + encodeURIComponent(JSON.stringify(blViewNow($("blViewName").value.trim())));
  if (navigator.clipboard) { navigator.clipboard.writeText(url).then(function () { btn.textContent = "Link copied"; setTimeout(function () { btn.textContent = "Copy link"; }, 2000); }); }
});
$("blList").addEventListener("change", function (e) { var k = e.target.getAttribute("data-blsel"); if (k) { bl.sel[k] = e.target.checked; blSelCount(); } });
$("blList").addEventListener("click", function (e) {
  var tog = e.target.closest("[data-blgrptog],[data-blgrpall]");
  if (tog) {
    var all = tog.getAttribute("data-blgrpall"), one = bl.group + "|" + tog.getAttribute("data-blgrptog");
    if (all) { (bl.groupNames || []).forEach(function (g) { if (all === "close") { bl.collapsed[bl.group + "|" + g] = true; } else { delete bl.collapsed[bl.group + "|" + g]; } }); }
    else if (bl.collapsed[one]) { delete bl.collapsed[one]; } else { bl.collapsed[one] = true; }
    blRenderList(); return;
  }
  if (e.target.getAttribute("data-blsel")) { return; }
  var it = e.target.closest("[data-blkey]"); if (!it) { return; }
  bl.key = it.getAttribute("data-blkey"); bl.pts = null; bl.pane = "groom"; renderBlPane(); blRenderList();
  api("GET", "/api/backlog/poker?key=" + encodeURIComponent(bl.key)).then(function (d) { bl.round = (d.rounds || []).filter(function (r) { return !r.closed; })[0] || null; blDetail(); }, function () { bl.round = null; blDetail(); });
});
$("blOrder").addEventListener("click", function () {
  var keys = Object.keys(bl.sel).filter(function (k) { return bl.sel[k]; });
  if (keys.length < 2) { blErr({ message: "Select two or more tickets, in the order they must ship." }); return; }
  var why = window.prompt("Order: " + keys.join(" \u2192 ") + "\nWhy this order? (one line, goes on each ticket)", "");
  if (why === null) { return; }
  api("POST", "/api/backlog/order", { keys: keys, why: why, user: blUser() }).then(function (c) { blClearSel(); blDone(c); }, blErr);
});
$("blMove").addEventListener("click", function () {
  var keys = Object.keys(bl.sel).filter(function (k) { return bl.sel[k]; }), v = $("blSprintTo").value;
  var sp = v === "backlog" ? "backlog" : (((bl.data || {}).sprints || []).filter(function (s) { return String(s.id) === v; })[0] || v);
  api("POST", "/api/backlog/move", { keys: keys, sprint: sp, user: blUser() }).then(function (c) { blClearSel(); blDone(c); }, blErr);
});
$("blDetail").addEventListener("click", function (e) {
  var t = e.target, key = bl.key; if (!key) { return; }
  if (t.getAttribute("data-blpts")) { bl.pts = t.getAttribute("data-blpts"); $("blDetail").querySelectorAll("[data-blpts]").forEach(function (b) { b.classList.toggle("is-on", b === t); }); $("blPtsOther").value = ""; blSaveReset(); return; }

  if (t.id === "insAsk") {
    var st = blStory(key);
    return api("POST", "/api/backlog/insight", { user: blUser(), story: { key: key, summary: st.summary, description: st.description, acceptance: st.acceptance } })
      .then(function (r) { ins[key] = r; insRender(); insGet(key); }, blErr);
  }
  if (t.id === "blDiscard") { delete bl.drafts[key]; blDraftsSave(); bl.pts = null; blDetail(); return; }
  if (t.id === "insUse") { return blUseAc(key, $("insAc").value); }
  if (t.id === "acrUse") { return blUseAc(key, (acr[key] || {}).acceptance || ""); }
  if (t.id === "acrAsk") {
    return api("POST", "/api/backlog/ac-rewrite", { user: blUser(), story: acrStory(key) }).then(function (r) { acr[key] = r; acrRender(); acrGet(key); }, blErr);
  }
  if (t.id === "acrAnswer") { return acrDialog(key); }
  if (t.id === "blSavePrev") { return blSavePreview(); }
  if (t.id === "blSave") {
    var ch = blChanges(blStory(key)).changes; if (!Object.keys(ch).length || !blLive(key)) { return blSavePreview(); }
    ch.key = key; ch.user = blUser(); ch.suggested = !!(bl.drafts[key] || {}).suggested;
    return api("POST", "/api/backlog/groom", ch).then(function (c) {
      var ok = c && c.status === "applied";
      if (ok) { delete bl.drafts[key]; blDraftsSave(); bl.pts = null; }
      $("blSave").disabled = true;
      $("blSaveNote").textContent = ok ? "Written to Jira." : "Not written: " + ((c && c.note) || "writes are off") + " It is listed under Previews.";
      blDone(c);
    }, blErr);
  }
  if (t.id === "blPokerStart") {
    var voters = $("blVoters").value.split(",").map(function (v) { return v.trim(); }).filter(Boolean);
    return api("POST", "/api/backlog/poker/start", { key: key, voters: voters, user: blUser() }).then(function (r) { bl.round = r; blDetail(); }, blErr);
  }
  if (t.getAttribute("data-blvote") && bl.round) {
    return api("POST", "/api/backlog/poker/vote", { round: bl.round.id, voter: blUser(), points: t.getAttribute("data-blvote"), user: blUser() }).then(function (r) { bl.round = r; blDetail(); }, blErr);
  }
  if (t.id === "blReveal" && bl.round) { return api("POST", "/api/backlog/poker/reveal", { round: bl.round.id }).then(function (r) { bl.round = r; blDetail(); }, blErr); }
  if (t.id === "blAgreeBtn" && bl.round) {
    return api("POST", "/api/backlog/poker/agree", { round: bl.round.id, points: $("blAgree").value, user: blUser() }).then(function (r) { bl.round = r; blDetail(); blDone(r.change); }, blErr);
  }
  if (t.id === "blNoteBtn") {
    var txt = $("blNote").value, fn = $("blNote").dataset.filename || "";
    return api("POST", "/api/backlog/note", { key: key, text: txt, filename: fn, user: blUser() }).then(function (c) { $("blNote").value = ""; delete $("blNote").dataset.filename; blDone(c); }, blErr);
  }
  if (t.id === "blRaiseBtn") {
    return api("POST", "/api/backlog/raise", { story: key, kind: $("blRaiseKind").value, title: $("blRaiseTitle").value, detail: $("blRaiseDetail").value,
      assignee: $("blRaiseTo").value.trim(), severity: $("blRaiseSev").value, environment: $("blRaiseEnv").value,
      specialty: $("blRaiseSpec").value, episode: $("blRaiseEpisode").value.trim(), user: blUser() })
      .then(function (c) { $("blRaiseTitle").value = ""; $("blRaiseDetail").value = ""; blDone(c); }, blErr);
  }
  if (t.id === "blHoursBtn") {
    var on = $("blHoursOn").value, opt = $("blHoursOn").selectedOptions[0];
    var logHours = function () {
      return api("POST", "/api/backlog/hours", { key: on, hours: $("blHours").value, note: $("blHoursNote").value, started: $("blHoursDate").value, user: blUser() })
        .then(function (c) { $("blHours").value = ""; $("blHoursNote").value = ""; blDone(c); }, blErr);
    };
    if (opt && opt.dataset.warn) {
      return askConfirm("The rule book puts hours on a sub-task, not the story. Log on " + on + " anyway?", { title: "Log hours on the story", ok: "Log on " + on }).then(function (yes) { if (yes) { return logHours(); } });
    }
    return logHours();
  }
  if (t.id === "blClone") { return api("POST", "/api/backlog/clone", { key: key, user: blUser() }).then(blDone, blErr); }
});
function ciRender() {
  var writes = ((bl.data || {}).mode || {}).writes;
  $("ciDry").disabled = !writes; if (!writes) { $("ciDry").checked = true; }
  $("ciDryNote").textContent = !writes
    ? "Dry run only: Backlog writes are off on this Argus, so you get the epic and stories as a Markdown file and nothing is written to Jira."
    : $("ciDry").checked ? "Dry run: you get the epic and stories as a Markdown file; nothing is written to Jira."
      : "Live run: after the PO approves, the tickets are created in Jira and the uploaded files attached.";
  $("ciStart").textContent = $("ciDry").checked ? "Start intake (dry run)" : "Start intake (live run)";
}
function ciFile(f) {
  return new Promise(function (ok, fail) {
    var rd = new FileReader();
    rd.onload = function () { ok({ name: f.name, data: String(rd.result || "").split(",")[1] || "" }); };
    rd.onerror = function () { fail(new Error(f.name + " could not be read")); };
    rd.readAsDataURL(f);
  });
}
$("ciDry").addEventListener("change", ciRender);
$("ciStart").addEventListener("click", function () {
  var btn = this, text = $("ciText").value.trim(), picked = Array.prototype.slice.call($("ciFiles").files || []);
  $("ciErr").hidden = true;
  if (text.length < 15 && !picked.length) { $("ciErr").textContent = "Describe the need in a sentence or upload a file."; $("ciErr").hidden = false; return; }
  btn.disabled = true; btn.textContent = "Uploading and starting a Devin session…";
  keepArgus();
  Promise.all(picked.map(ciFile)).then(function (files) {
    return api("POST", "/api/runs", { create: { kind: $("ciKind").value, text: text, files: files, dry_run: $("ciDry").checked }, user: blUser() });
  }).then(function (run) {
    $("ciText").value = ""; $("ciFiles").value = "";
    return loadRuns().then(function () { startedNote(run, "Intake started"); });
  }).catch(function (e) { $("ciErr").textContent = e.message || String(e); $("ciErr").hidden = false; })
    .then(function () { btn.disabled = false; ciRender(); });
});
$("blDraft").addEventListener("click", blDraftFromNotes);
$("blCheck").addEventListener("click", blCheckDraft);
$("blCreate").addEventListener("click", function () {
  api("POST", "/api/backlog/create", { draft: blDraft(), user: blUser(), source: $("blNotes").value.trim() ? "notes" : "form" }).then(function (c) { blRenderChecks(c.checks || []); blDone(c); }, function (e) {
    blErr(e); blCheckDraft();
  });
});
$("blNotes").addEventListener("dragover", function (e) { e.preventDefault(); this.classList.add("bl-drop"); });
$("blNotes").addEventListener("dragleave", function () { this.classList.remove("bl-drop"); });
$("blNotes").addEventListener("drop", function (e) {
  e.preventDefault(); this.classList.remove("bl-drop");
  var f = e.dataTransfer.files && e.dataTransfer.files[0]; if (!f) { return; }
  var rd = new FileReader(); rd.onload = function () { $("blNotes").value = String(rd.result || "").slice(0, 20000); blDraftFromNotes(); }; rd.readAsText(f);
});
