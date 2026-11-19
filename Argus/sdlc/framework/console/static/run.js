/* Result page for one Argus run: what Devin said, its documents, and any question or gate waiting on you. */
(function () {
  "use strict";
  var id = location.pathname.split("/").pop();
  var run = null, timer = null, askEid = "";

  function $(x) { return document.getElementById(x); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function api(method, url, body) {
    return fetch(url, { method: method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) { throw new Error(j.error || r.statusText); } return j; }); });
  }
  function showErr(e) {
    $("err").textContent = e.message || String(e); $("err").hidden = false;
    if (!run) { $("rTitle").textContent = "Couldn't load this run"; $("feed").innerHTML = '<div class="c-empty">Nothing to show until the run loads. It tries again by itself.</div>'; }
  }
  function fmtTime(t) { var d = new Date(t * 1000); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
  function asleep(r) { return /suspend/.test(r.status_detail || "") || /suspend/.test(r.status || ""); }

  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s)<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  }
  // Small Markdown reader: headings, lists, tables, code blocks, bold, code and links.
  function md(text) {
    var out = [], lines = String(text || "").replace(/\r/g, "").split("\n"), i = 0, list = null, para = [];
    function flushPara() { if (para.length) { out.push("<p>" + para.map(inline).join("<br>") + "</p>"); para = []; } }
    function flushList() { if (list) { out.push("</" + list + ">"); list = null; } }
    while (i < lines.length) {
      var l = lines[i], m;
      if (/^```/.test(l)) {
        flushPara(); flushList();
        var code = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) { code.push(lines[i]); i++; }
        out.push("<pre>" + esc(code.join("\n")) + "</pre>"); i++; continue;
      }
      if (/^\s*\|.*\|\s*$/.test(l)) {
        flushPara(); flushList();
        var rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(lines[i]); i++; }
        var cells = function (r) { return r.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); }); };
        var body = rows.filter(function (r) { return !/^\s*\|[\s:|-]+\|\s*$/.test(r); });
        out.push('<div class="a-table-scroll"><table class="a-table"><thead><tr>' + cells(body[0] || "").map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") + "</tr></thead><tbody>" +
          body.slice(1).map(function (r) { return "<tr>" + cells(r).map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div>");
        continue;
      }
      if ((m = /^(#{1,4})\s+(.*)$/.exec(l))) { flushPara(); flushList(); var n = Math.min(m[1].length + 1, 5); out.push("<h" + n + ">" + inline(m[2]) + "</h" + n + ">"); i++; continue; }
      if ((m = /^\s*([-*]|\d+[.)])\s+(.*)$/.exec(l))) {
        flushPara();
        var kind = /\d/.test(m[1]) ? "ol" : "ul";
        if (list !== kind) { flushList(); out.push("<" + kind + ">"); list = kind; }
        out.push("<li>" + inline(m[2]) + "</li>"); i++; continue;
      }
      if (!l.trim()) { flushPara(); flushList(); i++; continue; }
      flushList(); para.push(l); i++;
    }
    flushPara(); flushList();
    return out.join("");
  }

  function spoken(text) {
    // What Devin said, without the [SDLC] marker lines and with code blocks pointed at the Output section.
    return String(text || "").replace(/```[\s\S]*?```/g, "_(shown under Output)_")
      .split("\n").filter(function (l) { return !/^\s*\[SDLC\]/.test(l); }).join("\n").replace(/_\(shown under Output\)_/g, "(shown under Output)").trim();
  }

  function state(r) {
    if (r.closed_at && r.assistant) { return ["s-done", "finished · chat closed", "Done. The answer is kept on this page. Your Argus assistant session for today keeps running for your other requests. Use Run again for a fresh answer."]; }
    if (r.closed_at) { return ["s-done", "finished · session closed", "Done. The answer is kept on this page; the Devin session is closed, so it no longer uses resources. Use Run again for a fresh answer."]; }
    if (r.pending_gate) { return ["s-wait", "waiting for your sign-off", "Devin has stopped at a gate. Read it below and approve or reject."]; }
    if (r.pending_questions) { return ["s-wait", "questions for you", "Devin needs your answers before it carries on."]; }
    if (r.status === "finished" || r.status === "exit" || r.complete || (asleep(r) && r.artefacts.length)) { return ["s-done", "finished", "Done. The output is below; reply at the bottom to ask a follow-up."]; }
    if (asleep(r)) { return ["s-sleep", "asleep", "The session went to sleep. Press Wake, or reply below, to carry on."]; }
    if (r.status === "blocked") { return ["s-wait", "waiting for you", "Devin is waiting for a reply. Read its last message below."]; }
    if (r.status === "error" || r.status === "expired") { return ["s-bad", r.status, "The session stopped with an error. Open it in Devin for details."]; }
    if (r.status === "new" || r.status === "claimed" || !r.messages.length) { return ["s-run", "starting", "Starting a Devin session. This page updates by itself."]; }
    return ["s-run", "working", "Devin is working on it. This page updates by itself."];
  }

  function artHtml(a, i) {
    var name = a.name || "document", low = name.toLowerCase(), btns = [];
    if (a.repo_file) {
      btns.push('<a class="a-btn a-btn--primary" target="_blank" href="/repo-file?path=' + encodeURIComponent(name) + '">Open ' + esc(name.split("/").pop()) + "</a>");
    } else if (a.body && /\.html?$|\.md$|\.markdown$/.test(low)) {
      btns.push('<a class="a-btn a-btn--primary" target="_blank" href="/view/' + run.id + "/" + (run.artefacts.length - 1 - i) + '">Open as a page</a>');
    }
    if (/kb_open_questions\.yaml$|kb-validation-form\.html$/.test(low)) {
      btns.push('<a class="a-btn a-btn--outline" target="_blank" href="/validation">Open the question form</a>');
    }
    if (a.body) { btns.push('<button type="button" class="a-btn a-btn--outline" data-download="' + i + '">Download</button>'); }
    var body = "";
    if (a.body && /\.md$|\.markdown$/.test(low)) { body = '<div class="a-prose rp-md">' + md(a.body) + "</div>"; }
    else if (a.body && !/\.html?$/.test(low)) { body = "<pre>" + esc(a.body) + "</pre>"; }
    return '<details class="c-art rp-art"' + (i === 0 || a.repo_file ? " open" : "") + "><summary><span>" + esc(name) + "</span><small>" + esc(a.detail || "") + "</small></summary>" +
      (btns.length ? '<div class="c-card__actions rp-art__btns">' + btns.join("") + "</div>" : "") + body + "</details>";
  }

  function render(r) {
    run = r;
    var sk = r.skill || {}, st = state(r);
    document.title = (sk.command || r.story.key) + " · result";
    $("rCmd").textContent = sk.command || r.story.key;
    $("rMode").textContent = r.dry_run ? "dry run" : "real run";
    $("rStatus").innerHTML = '<span class="a-badge ' + st[0] + '">' + esc(st[1]) + "</span>";
    $("rTitle").textContent = sk.label ? sk.label + (r.story.input ? " — " + r.story.input.split("\n")[0].slice(0, 80) : "") : r.story.summary;
    $("rBlurb").textContent = sk.blurb || "";
    $("now").innerHTML = "<b>Right now:</b> " + esc(st[2]);
    $("rSession").hidden = !r.session_url; $("rSession").href = r.session_url || "#";
    $("wakeBtn").hidden = !asleep(r) || r.pending_gate || r.pending_questions || !!r.closed_at;
    $("closeBtn").hidden = !!r.closed_at || /^(exit|error|expired)$/.test(r.status || "");
    $("closeBtn").dataset.assistant = r.assistant ? "1" : "";
    $("compose").hidden = !!r.closed_at;

    var re = [];
    if (r.kind === "action" && sk.skill) { re.push('<button type="button" class="a-btn a-btn--outline" data-again="same">Run again now</button>'); }
    if (r.dry_run && r.kind === "action" && sk.skill) { re.push('<button type="button" class="a-btn a-btn--outline" data-again="live">Run it for real</button>'); }
    ((sk.input || {}).choices || []).forEach(function (c) { re.push('<button type="button" class="a-btn a-btn--ghost" data-again="' + esc(c) + '">' + esc(c) + "</button>"); });
    $("rerun").hidden = !re.length;
    var reused = /[?&]reused=1/.test(location.search) ? '<span class="c-muted">The same request was run at ' + esc(fmtTime(r.created_at)) + ", so this is that answer; nothing new was started.</span> " : "";
    $("rerun").innerHTML = re.length ? reused + '<span class="c-muted">Run again:</span> ' + re.join(" ") : "";

    var q = r.closed_at ? null : r.pending_questions;
    $("askCard").hidden = !q;
    if (q && askEid !== q.event_id) {
      askEid = q.event_id;
      $("askItems").innerHTML = q.items.map(function (it) {
        return '<div class="c-q"><label><b>' + it.n + ".</b> " + inline(it.text) + '</label><textarea class="a-input" rows="2" data-q="' + it.n + '"></textarea></div>';
      }).join("");
    }
    var g = r.closed_at ? null : r.pending_gate;
    $("gateCard").hidden = !g;
    if (g) { $("gateId").textContent = g.id; $("gateText").innerHTML = md(g.text); }
    if (g && $("gateItems").dataset.eid !== (g.event_id || g.id)) {
      $("gateItems").dataset.eid = g.event_id || g.id;
      $("gateItems").innerHTML = (g.items || [{ n: 1, text: "Approve this gate as presented" }]).map(function (it) {
        return '<div class="c-q w-gitem" data-n="' + it.n + '"><label><b>' + it.n + ".</b> " + inline(it.text) + "</label>" +
          '<span class="w-gitem__pick"><label class="c-switch"><input type="radio" name="gi-' + it.n + '" value="approve" /> Approve</label>' +
          '<label class="c-switch"><input type="radio" name="gi-' + it.n + '" value="reject" /> Reject</label></span>' +
          '<input class="a-input w-gitem__note" placeholder="Reason (needed to reject) or a note" /></div>';
      }).join("");
      gateItemsChanged();
    }

    $("outSec").hidden = !r.artefacts.length;
    $("arts").innerHTML = r.artefacts.slice().reverse().map(artHtml).join("");

    var said = r.messages.filter(function (m, i) { return !(i === 0 && /^Repository: @/.test(m.text || "")); })
      .map(function (m) { return { m: m, t: m.source === "user" ? m.text : spoken(m.text) }; })
      .filter(function (x) { return x.t; });
    $("feed").innerHTML = said.length ? said.map(function (x) {
      var mine = x.m.source === "user";
      return '<div class="rp-msg' + (mine ? " is-user" : "") + '"><div class="rp-msg__who">' + (mine ? "You" : "Devin") + " · " + fmtTime(x.m.at) + '</div><div class="a-prose rp-md">' + md(x.t) + "</div></div>";
    }).join("") : '<div class="c-empty">Nothing yet. A new session takes a minute or two to start.</div>';
  }

  function poll(force) {
    clearTimeout(timer);
    return api("GET", "/api/runs/" + id + (force ? "?refresh=1" : ""))
      .then(function (r) { $("err").hidden = true; render(r); })
      .catch(showErr)
      .then(function () {
        var quiet = run && (run.status === "finished" || run.complete || asleep(run)) && !run.pending_questions && !run.pending_gate;
        // The timer reads what the poller already holds (this page marks the run as watched, so it is read
        // every few seconds); only the first load and the person's own actions ask for a fresh read.
        timer = setTimeout(function () { poll(false); }, quiet ? 30000 : 6000);
      });
  }

  function arts() { return run ? run.artefacts.slice().reverse() : []; }
  document.addEventListener("click", function (ev) {
    var t = ev.target.closest("button"); if (!t) { return; }
    if (t.dataset.download != null) {
      var d = arts()[+t.dataset.download], link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([d.body], { type: "text/plain" })); link.download = d.name.split("/").pop(); link.click();
    } else if (t.dataset.again != null) {
      var live = t.dataset.again === "live", same = live || t.dataset.again === "same";
      var win = window.open("", "_blank");
      api("POST", "/api/actions", { skill: run.skill.skill, text: same ? (run.story.input || "") : t.dataset.again, dry_run: live ? false : run.dry_run, fresh: true })
        .then(function (nr) { if (win) { win.location = "/run/" + nr.id; } else { location = "/run/" + nr.id; } })
        .catch(function (e) { if (win) { win.close(); } showErr(e); });
    }
  });
  $("gateItems").addEventListener("input", gateItemsChanged);
  $("gateItems").addEventListener("change", gateItemsChanged);
  $("gateSend").addEventListener("click", function () {
    var items = gateDecisions();
    if (items.some(function (x) { return !x.decision || (x.decision === "reject" && !x.note); })) { return; }
    var btn = this; btn.disabled = true;
    api("POST", "/api/runs/" + id + "/gate", { decision: "items", items: items }).then(function (res) {
      $("gateItems").dataset.eid = "";
      if (res && res.closed) { location = "/"; return; }
      poll(true);
    }).catch(showErr).then(gateItemsChanged);
  });
  $("askSend").addEventListener("click", function () {
    var answers = [];
    document.querySelectorAll("#askItems textarea").forEach(function (x) { answers.push({ n: parseInt(x.dataset.q, 10), text: x.value }); });
    if (!answers.some(function (a) { return a.text.trim(); })) { return; }
    api("POST", "/api/runs/" + id + "/answers", { answers: answers }).then(function () { askEid = ""; poll(true); }).catch(showErr);
  });
  $("wakeBtn").addEventListener("click", function () { api("POST", "/api/runs/" + id + "/wake", {}).then(function () { poll(true); }).catch(showErr); });
  $("closeBtn").addEventListener("click", function () {
    var ask = $("closeBtn").dataset.assistant ? "Close this chat? Its card closes; your Argus assistant session for today keeps running for your other requests."
      : "Close this Devin session? It ends for good and cannot be woken; everything on this page stays.";
    if (!window.confirm(ask)) { return; }
    api("POST", "/api/runs/" + id + "/close", {}).then(function () { poll(true); }).catch(showErr);
  });
  $("compose").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var text = $("composeText").value.trim(); if (!text) { return; }
    api("POST", "/api/runs/" + id + "/message", { text: text }).then(function () { $("composeText").value = ""; poll(true); }).catch(showErr);
  });
  poll(true);

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
}());
