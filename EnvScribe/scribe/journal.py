"""Journal writer: Markdown + JSON from merged facts. Every file carries an as-of header."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .util import atomic_write, write_jsonl


def header(title: str, run_id: str, collated_at: str, as_min: str, as_max: str) -> str:
    return (f"# {title}\n\n> Run `{run_id}` · collated at **{collated_at}** · facts as of **{as_min}** → **{as_max}** (UTC)  \n"
            f"> Every statement cites its source. Classes: OBSERVED, DERIVED, DOCUMENTED, DISCUSSED, UNKNOWN. Nothing here is inferred.\n\n")


def _cite(f: dict) -> str:
    e = f["evidence"][0]
    return f"`{e['source']}` {e['location']}"


def write_journal(root: str | Path, run_id: str, coll: dict, links: list[dict], matrix: dict, pii: list[dict], lin: list[dict],
                  doc_code: list[dict], integrations: list[dict], unclassified: list[dict], coverage: dict, owners: list[dict],
                  settings: dict) -> list[str]:
    root = Path(root)
    facts = coll["facts"]
    ca, lo, hi = coll["collated_at"], coll["as_of_min"], coll["as_of_max"]
    written: list[str] = []

    def w(rel: str, text: str):
        atomic_write(root / rel, text)
        written.append(rel)

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        by_kind[f["kind"]].append(f)
    repos = sorted({f["attrs"].get("repo") for f in facts if f["attrs"].get("repo")})

    # index
    idx = [header("EnvScribe Journal", run_id, ca, lo, hi), "## Contents\n"]
    idx += [f"- [Integrations](integrations.md)\n- [Coverage](coverage.md)\n- [Environment matrix](environments/matrix.md)\n- [APIs](apis/index.md)\n"
            f"- [Registers](registers/unknowns.md) · [conflicts](registers/conflicts.md) · [skips](registers/skips.md)\n- [Databases](databases/index.md)\n"
            f"- [CI/CD & infrastructure](cicd/index.md)\n- [Documents](docs-and-tickets/index.md)\n- [Analyses](analyses/index.md)\n\n## Services / repositories\n"]
    for r in repos:
        idx.append(f"- [{r}](services/{r}.md)")
    w("index.md", "\n".join(idx) + "\n")

    # services
    for r in repos:
        rf = [f for f in facts if f["attrs"].get("repo") == r]
        k = defaultdict(list)
        for f in rf:
            k[f["kind"]].append(f)
        langs = defaultdict(int)
        for f in k["source_file"]:
            langs[f["attrs"]["language"]] += 1
        lines = [header(f"Service: {r}", run_id, ca, lo, hi), "## Overview (OBSERVED)\n",
                 f"- Source files scanned: {len(k['source_file'])}\n- Languages: " + (", ".join(f"{a} ({b})" for a, b in sorted(langs.items(), key=lambda x: -x[1])) or "none"),
                 f"- Entry points: {len(k['entry_point'])}\n- Endpoints in code: {len(k['endpoint'])}\n- Dependencies: {len(k['dependency'])}\n"]
        for title, kind, fmt in (
            ("Entry points", "entry_point", lambda f: f"{f['attrs']['label']} - {_cite(f)}"),
            ("Endpoints found in code", "endpoint", lambda f: f"`{f['subject']}` ({f['attrs']['framework']}) - {_cite(f)}"),
            ("Modules", "module", lambda f: f"`{f['subject']}` v{f['attrs'].get('version') or '?'} - {_cite(f)}"),
            ("Dependencies", "dependency", lambda f: f"`{f['subject']}` {f['attrs'].get('version') or ''} ({f['attrs'].get('scope')}) - {_cite(f)}"),
            ("Environment variables used", "env_var_use", lambda f: f"`{f['attrs']['name']}` - {_cite(f)}"),
            ("Configuration keys used in code", "config_key_use", lambda f: f"`{f['attrs']['key']}` - {_cite(f)}"),
            ("Messaging references", "messaging_reference", lambda f: f"`{f['attrs']['topic']}` - {_cite(f)}"),
            ("Tables referenced by static SQL (DERIVED)", "table_reference", lambda f: f"`{f['attrs']['table']}` - {_cite(f)}"),
            ("Pipelines and deployment", "pipeline_stage", lambda f: f"{f['attrs']['system']}: {f['attrs']['stage']} - {_cite(f)}"),
            ("Secret-leak locations (value never recorded)", "secret_leak", lambda f: f"{f['attrs']['type']} at `{f['attrs']['path']}` line {f['attrs']['line']}"),
            ("Technical debt markers", "todo", lambda f: f"{f['attrs']['text'][:100]} - {_cite(f)}")):
            items = sorted(k[kind], key=lambda f: f["subject"])
            if items:
                seen, out = set(), []
                for f in items:
                    line = fmt(f)
                    if line not in seen:
                        seen.add(line)
                        out.append(f"- {line}")
                lines.append(f"\n## {title}\n" + "\n".join(out[:300]) + (f"\n- … {len(out) - 300} more in facts/all-facts.jsonl" if len(out) > 300 else ""))
        w(f"services/{r}.md", "\n".join(lines) + "\n")

    # apis
    api = [header("APIs", run_id, ca, lo, hi)]
    for f in sorted(by_kind["api_service"], key=lambda f: f["subject"]):
        api.append(f"## {f['subject']}\n- Spec: {f['attrs'].get('spec')} · version {f['attrs'].get('version')} · {_cite(f)}")
    api.append("\n## Operations\n| Operation | Parameters | Responses | Source |\n|---|---|---|---|")
    for f in sorted(by_kind["api_operation"], key=lambda f: f["subject"]):
        a = f["attrs"]
        api.append(f"| `{f['subject']}` | {', '.join(p['name'] for p in a.get('parameters', []) if p.get('name')) or '-'} | {', '.join(a.get('responses', [])) or '-'} | {_cite(f)} |")
    w("apis/index.md", "\n".join(api) + "\n")

    # environments
    em = [header("Environment comparison matrix", run_id, ca, lo, hi),
          "Values come from config files whose path names an environment. Secret-like keys show presence only. IPs and hostnames are masked.\n"]
    if matrix["environments"]:
        em.append("| Key | " + " | ".join(matrix["environments"]) + " | Differs |\n|---|" + "---|" * (len(matrix["environments"]) + 1))
        for row in matrix["rows"]:
            em.append(f"| `{row['key']}` | " + " | ".join(f"`{row['values'].get(e, '—')}`" for e in matrix["environments"]) + f" | {'**yes**' if row['differs'] else 'no'} |")
    else:
        em.append("UNKNOWN: no environment-specific config files were found.")
    w("environments/matrix.md", "\n".join(em) + "\n")

    # databases
    db = [header("Databases", run_id, ca, lo, hi), "## Connection settings found in config (credentials and hosts removed)\n"]
    for f in sorted(by_kind["db_connection"], key=lambda f: f["subject"]):
        db.append(f"- engine `{f['attrs']['engine']}` · env {f['attrs'].get('environment') or 'n/a'} · key `{f['attrs']['key']}` - {_cite(f)}")
    if by_kind["db_table"]:
        db.append("\n## Catalog (metadata only)\n")
        for f in sorted(by_kind["db_table"], key=lambda f: f["subject"]):
            db.append(f"- `{f['subject']}` - {_cite(f)}")
    else:
        db.append("\nUNKNOWN: no live catalog was read (no approved database integration or none reachable).")
    w("databases/index.md", "\n".join(db) + "\n")

    # cicd
    ci = [header("CI/CD and infrastructure", run_id, ca, lo, hi)]
    for kind, title in (("pipeline_stage", "Pipeline stages"), ("deploy_command", "Deploy commands"), ("container_image", "Container images"),
                        ("k8s_resource", "Kubernetes resources"), ("iac_resource", "IaC resources"), ("service_definition", "Compose services"), ("helm_chart", "Helm charts")):
        if by_kind[kind]:
            ci.append(f"\n## {title}")
            ci += [f"- `{f['subject']}` - {_cite(f)}" for f in sorted(by_kind[kind], key=lambda f: f["subject"])[:300]]
    w("cicd/index.md", "\n".join(ci) + "\n")

    # docs
    dc = [header("Documents, diagrams and transcripts", run_id, ca, lo, hi),
          "DOCUMENTED = stated in a document. DISCUSSED = content from a meeting transcript; speakers were removed and it is **not** a record of decisions.\n"]
    for f in sorted(by_kind["document"], key=lambda f: f["subject"]):
        dc.append(f"## {f['attrs']['file']}\n- Type: {f['attrs']['type']} · related to: {', '.join(f['attrs']['apps']) or 'n/a'} · class OBSERVED (file) / "
                  f"{'DISCUSSED' if f['attrs']['transcript'] else 'DOCUMENTED'} (content)")
        for s in [x for x in by_kind["doc_section"] + by_kind["discussion"] if x["subject"] == f["subject"]][:25]:
            tag = "DISCUSSED" if s["kind"] == "discussion" else "DOCUMENTED"
            dc.append(f"  - [{tag}] {s['attrs']['text'][:240].replace(chr(10), ' ')} - {s['evidence'][0]['location']}")
    if by_kind["diagram_edge"]:
        dc.append("\n## Connections drawn in diagrams (DOCUMENTED, not verified against code)")
        dc += [f"- {f['attrs']['from']} → {f['attrs']['to']} {('[' + f['attrs']['label'] + ']') if f['attrs']['label'] else ''} - {_cite(f)}" for f in by_kind["diagram_edge"]]
    w("docs-and-tickets/index.md", "\n".join(dc) + "\n")

    # analyses
    an = [header("Analyses", run_id, ca, lo, hi), "## Cross-links (DERIVED, exact matches only)"]
    an += [f"- {l['attrs']['relation']}: `{l['subject']}` - rule: {l.get('rule')}" for l in links[:300]] or ["- none found"]
    an.append("\n## Ownership (as stated in CODEOWNERS)")
    an += [f"- `{o['pattern']}` → {o['owner']} ({o['repo']})" for o in owners[:200]] or ["- UNKNOWN: no CODEOWNERS found"]
    an.append("\n## Personal-data indicators (names only; for human review, not a compliance determination)")
    an += [f"- `{p['where']}` field `{p['name']}` ({p['basis']})" for p in pii[:200]] or ["- none found"]
    an.append("\n## Name-level lineage candidates (identical names only; not verified data flow)")
    an += [f"- {l['api_field']} ↔ {l['column']}" for l in lin[:200]] or ["- none found"]
    an.append("\n## Documented connections vs. code")
    an += [f"- {d['from']} → {d['to']}: {d['verification']}" for d in doc_code[:200]] or ["- none"]
    w("analyses/index.md", "\n".join(an) + "\n")

    # registers
    w("registers/unknowns.md", header("Unknowns register", run_id, ca, lo, hi) +
      "\n".join(f"- {u['subject']}: {u['reason']}" for u in coll["unknowns"]) + ("" if coll["unknowns"] else "None recorded.") + "\n")
    cf = [header("Conflicts register (reported, never resolved)", run_id, ca, lo, hi)]
    for c in coll["conflicts"]:
        cf.append(f"## {c['subject']}\n{c['note']}\n" + "\n".join(f"- `{v['value']}` ← {', '.join(v['sources'])}" for v in c["values"]))
    w("registers/conflicts.md", "\n".join(cf) + ("" if coll["conflicts"] else "No conflicts detected.") + "\n")
    w("registers/skips.md", header("Skip log", run_id, ca, lo, hi) + "\n".join(f"- {s['item']}: {s['reason']}" for s in coll["skips"][:5000]) + "\n")
    reg_counts = defaultdict(int)
    for r in coll["register"]:
        reg_counts[r["type"]] += 1
    w("registers/sensitive-content.md", header("Sensitive-content register", run_id, ca, lo, hi) +
      "Items masked on intake. Only type and location are recorded.\n\n" + "\n".join(f"- {t}: {n}" for t, n in sorted(reg_counts.items())) + "\n")

    # integrations
    it = [header("Integrations", run_id, ca, lo, hi), "| System | Category | Status | Approved | Note |\n|---|---|---|---|---|"]
    for i in integrations:
        it.append(f"| {i['system']} | {i['category']} | {i['status']} | {'yes' if i['approved'] else 'no'} | {i.get('flag') or i.get('notes') or ''} |")
    it.append("\n## Unclassified (reported only; never used)\n" + "\n".join(f"- `{u['name']}` at {u['location']}: {u['reason']}" for u in unclassified))
    w("integrations.md", "\n".join(it) + "\n")

    # coverage
    cv = [header("Coverage", run_id, ca, lo, hi)]
    for k, v in coverage.items():
        cv.append(f"- **{k}**: {v}")
    w("coverage.md", "\n".join(cv) + "\n")

    # machine-readable
    write_jsonl(root / "facts" / "all-facts.jsonl", facts + links)
    written.append("facts/all-facts.jsonl")
    for name, obj in (("integrations", integrations), ("environment-matrix", matrix), ("conflicts", coll["conflicts"]), ("unknowns", coll["unknowns"]),
                      ("pii-indicators", pii), ("lineage-candidates", lin), ("documented-connections", doc_code), ("ownership", owners)):
        atomic_write(root / "facts" / f"{name}.json", json.dumps({"collated_at": ca, "as_of_min": lo, "as_of_max": hi, "data": obj}, indent=2, default=str))
        written.append(f"facts/{name}.json")
    return written
