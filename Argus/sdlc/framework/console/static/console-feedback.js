// Feedback on the top bar, and the page's own script errors. The form sends only what the person says:
// Argus adds the session details it already has (page, ticket, runs, session links, stage, status,
// last error, what Devin last said, the status light, what it noticed), shown under "Sent with your feedback".
var fbScreenErrors = [];
var fbLastSent = {};

function fbNoteError(text) {
  text = String(text || "").slice(0, 300);
  if (!text) { return; }
  fbScreenErrors.push(text); if (fbScreenErrors.length > 5) { fbScreenErrors.shift(); }
  var now = Date.now();
  if (fbLastSent[text] && now - fbLastSent[text] < 30000) { return; }
  fbLastSent[text] = now;
  try {
    fetch("/api/observe", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ where: "screen", detail: text, page: fbPage() }) }).catch(function () {});
  } catch (e) { /* noticing must never break the page */ }
}
window.addEventListener("error", function (ev) {
  var src = ev.filename ? " at " + String(ev.filename).replace(/^.*\/static\//, "") + ":" + ev.lineno : "";
  fbNoteError((ev.message || "script error") + src);
});
window.addEventListener("unhandledrejection", function (ev) {
  var r = ev.reason; fbNoteError("unhandled: " + (r && r.message ? r.message : String(r)));
});

function fbPage() {
  var views = { storyView: "ticket", runView: "run", pcView: "test on my PC", backlogView: "backlog", autoView: "automation", welcome: "home" };
  for (var id in views) { var el = document.getElementById(id); if (el && !el.hidden) { return views[id]; } }
  return "";
}

function fbQuery() {
  return { user: state.user || "", role: state.role || "", run: state.run ? state.run.id : "",
    story: state.story ? state.story.key : "", page: fbPage(), browser: navigator.userAgent.slice(0, 160) };
}

function fbContextHtml(c) {
  var li = [];
  li.push("<li>You: " + esc(c.person || "not picked yet") + (c.role ? " (" + esc(c.role) + ")" : "") + "</li>");
  if (c.page || c.ticket) { li.push("<li>Page: " + esc(c.page || "-") + (c.ticket ? ", ticket " + esc(c.ticket) : "") + "</li>"); }
  (c.runs || []).forEach(function (r) {
    li.push("<li>" + (r.this_one ? "<strong>This run:</strong> " : "Run: ") + esc(r.what || r.kind || "") + " " + esc(r.summary || "") +
      ", stage " + esc(r.stage || "-") + ", " + esc(r.status || "-") +
      (r.session ? ' · <a href="' + esc(r.session) + '" target="_blank" rel="noopener">session</a>' : "") +
      (r.error ? '<br><span class="w-fb__bad">Error: ' + esc(r.error) + "</span>" : "") +
      (r.last_devin ? '<br><span class="c-muted">Devin last said: ' + esc(r.last_devin) + "</span>" : "") + "</li>");
  });
  var light = c.status_light || {};
  Object.keys(light).forEach(function (k) {
    li.push("<li>" + esc(k) + ": " + esc(light[k].state) + (light[k].error ? " (" + esc(light[k].error) + ")" : "") + "</li>");
  });
  (c.noticed || []).forEach(function (n) { li.push("<li>Argus noticed: " + esc(n.title) + " x" + n.count + "</li>"); });
  fbScreenErrors.forEach(function (e) { li.push("<li>Page error: " + esc(e) + "</li>"); });
  var w = c.workbench || {};
  li.push('<li class="c-muted">Argus ' + esc(w.version || "-") + ", commit " + esc(w.commit || "-") + " on " + esc(w.branch || "-") + "</li>");
  return "<ul>" + li.join("") + "</ul>";
}

function openFeedback() {
  if (typeof closeMenus === "function") { closeMenus(); }
  var box = $("fbModal"); $("fbMsg").textContent = ""; $("fbSend").disabled = false;
  $("fbContext").innerHTML = '<p class="c-muted">Reading what Argus knows…</p>';
  box.hidden = false; $("fbText").focus();
  var q = fbQuery(), qs = Object.keys(q).map(function (k) { return k + "=" + encodeURIComponent(q[k]); }).join("&");
  api("GET", "/api/feedback?" + qs).then(function (r) {
    $("fbContext").innerHTML = fbContextHtml(r.context || {});
  }, function (e) { $("fbContext").innerHTML = '<p class="c-muted">Could not read the session details: ' + esc(e.message || e) + "</p>"; });
}

function sendFeedback(ev) {
  ev.preventDefault();
  var text = $("fbText").value.trim();
  if (!text) { $("fbMsg").textContent = "Say what happened or what you would like."; $("fbText").focus(); return; }
  var body = fbQuery();
  body.kind = $("fbKind").value; body.about = $("fbAbout").value; body.text = text; body.screen_errors = fbScreenErrors.slice();
  $("fbSend").disabled = true; $("fbMsg").textContent = "Sending…";
  api("POST", "/api/feedback", body).then(function (r) {
    $("fbText").value = ""; fbScreenErrors = [];
    var msg = r.run ? "Thanks, sent. Devin is adding it to the Leads dashboard." :
      "Thanks, kept on this machine. It goes with the next send, once Argus knows who you are.";
    $("fbMsg").innerHTML = esc(msg) + (r.run ? ' <a href="#run/' + esc(r.run.id) + '" data-fbrun="' + esc(r.run.id) + '">Open the run</a>' : "");
    if (r.run && typeof loadRuns === "function") { loadRuns(); }
    var shown = $("fbMsg").innerHTML;
    setTimeout(function () { if ($("fbMsg").innerHTML === shown && !$("fbText").value) { $("fbModal").hidden = true; } }, 4000);
  }, function (e) { $("fbSend").disabled = false; $("fbMsg").textContent = "Not sent: " + (e.message || e); });
}

document.addEventListener("click", function (ev) {
  if (ev.target.closest("#feedbackBtn")) { openFeedback(); return; }
  var t = ev.target.closest("[data-fbrun]");
  if (t) { ev.preventDefault(); $("fbModal").hidden = true; openRun(t.dataset.fbrun); }
});
(function () {
  var f = $("fbForm"); if (f) { f.addEventListener("submit", sendFeedback); }
  var m = $("fbModal"); if (m) { m.addEventListener("keydown", function (ev) { if (ev.key === "Escape") { m.hidden = true; } }); }
})();
