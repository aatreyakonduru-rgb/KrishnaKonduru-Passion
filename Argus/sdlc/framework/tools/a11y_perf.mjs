// Open one URL in the Devin machine's Chrome (CDP on port 29229), run the accessibility checks and read the page
// timings, print one JSON object. Run with: node --experimental-websocket a11y_perf.mjs <url> [cdp port]
const [url, port = "29229"] = process.argv.slice(2);
const AUDIT = `(async () => {
  const out = [];
  const snip = e => (e.outerHTML || "").slice(0, 120);
  const add = (rule, e, msg) => out.push({rule, element: typeof e === "string" ? e : snip(e), message: msg});
  if (!document.documentElement.lang) add("html-lang", "<html>", "the page has no lang attribute");
  if (!document.title.trim()) add("page-title", "<title>", "the page has no title");
  document.querySelectorAll("img").forEach(e => { if (!e.hasAttribute("alt")) add("img-alt", e, "image has no alt text"); });
  const ref = e => (e.getAttribute("aria-labelledby") || "").split(/\\s+/).map(i => (document.getElementById(i) || {}).textContent || "").join(" ");
  const name = e => (e.getAttribute("aria-label") || ref(e) || e.textContent || e.getAttribute("title") || "").trim();
  document.querySelectorAll("button, a[href], [role=button]").forEach(e => {
    if (!name(e) && !e.querySelector("img[alt]:not([alt=''])")) add("control-name", e, "button or link has no accessible name"); });
  document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea").forEach(e => {
    const label = (e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]')) || e.closest("label");
    if (!label && !e.getAttribute("aria-label") && !ref(e).trim() && !e.getAttribute("title")) add("form-label", e, "form field has no label"); });
  let last = 0;
  document.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach(h => { const n = +h.tagName[1];
    if (last && n > last + 1) add("heading-order", h, "heading jumps from h" + last + " to h" + n); last = n; });
  const ids = {};
  document.querySelectorAll("[id]").forEach(e => { ids[e.id] = (ids[e.id] || 0) + 1; });
  Object.keys(ids).filter(k => ids[k] > 1).forEach(k => add("duplicate-id", "#" + k, "id is used " + ids[k] + " times"));
  const lcp = await new Promise(done => { setTimeout(() => done(0), 1500);
    try { new PerformanceObserver(l => { const e = l.getEntries(); done(e[e.length - 1].startTime); })
      .observe({type: "largest-contentful-paint", buffered: true}); } catch (err) { done(0); } });
  const nav = performance.getEntriesByType("navigation")[0] || {};
  const res = performance.getEntriesByType("resource");
  return JSON.stringify({url: location.href, findings: out, perf: {
    dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd || 0), load_ms: Math.round(nav.loadEventEnd || 0),
    lcp_ms: Math.round(lcp), requests: res.length + 1,
    transfer_kb: Math.round(((nav.transferSize || 0) + res.reduce((a, r) => a + (r.transferSize || 0), 0)) / 1024)}});
})()`;

const base = "http://localhost:" + port;
const target = await (await fetch(base + "/json/new?about:blank", {method: "PUT"})).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
let id = 0;
const waiting = new Map();
const events = [];
ws.onmessage = m => { const d = JSON.parse(m.data);
  if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); } else events.push(d.method); };
const send = (method, params = {}) => new Promise(r => { const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
await new Promise(r => ws.onopen = r);
try {
  await send("Page.enable");
  await send("Page.navigate", {url});
  for (let t = 0; t < 300 && !events.includes("Page.loadEventFired"); t++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 500));
  const got = await send("Runtime.evaluate", {expression: AUDIT, awaitPromise: true, returnByValue: true});
  const value = got.result && got.result.result && got.result.result.value;
  console.log(value || JSON.stringify({url, error: JSON.stringify(got.result && got.result.exceptionDetails || got.error)}));
} finally {
  ws.close();
  await fetch(base + "/json/close/" + target.id).catch(() => {});
}
