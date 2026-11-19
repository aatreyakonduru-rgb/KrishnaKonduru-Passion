// Syntax-checks the inline <script> of each UI page. Usage: node scripts/check_html_js.js
const fs = require("fs"), path = require("path"), vm = require("vm");
const dir = path.join(__dirname, "..", "scribe", "ui", "static");
let bad = 0;
for (const f of fs.readdirSync(dir).filter(x => x.endsWith(".html"))) {
  const html = fs.readFileSync(path.join(dir, f), "utf8");
  const m = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  m.forEach((s, i) => {
    try { new vm.Script(s[1], { filename: `${f}#${i}` }); console.log("ok  ", f, `script ${i}`); }
    catch (e) { bad++; console.log("FAIL", f, `script ${i}:`, e.message); }
  });
}
process.exit(bad ? 1 : 0);
