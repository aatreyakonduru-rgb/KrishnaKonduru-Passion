#!/usr/bin/env python3
"""Deterministic validation of the Acme Claims agentic framework.

Run from anywhere: python3 sdlc/framework/tools/validate_framework.py
Checks skill frontmatter and triggers, agent YAML and allowed_skills, rule/template/config
parsing, playbook -> skill mapping, gate IDs, and repository-relative file references.
Exits non-zero on any failure.
"""
import glob, os, re, sys, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.chdir(ROOT)
fail, warn = [], []
def F(c, m): fail.append(f"[{c}] {m}")
def W(c, m): warn.append(f"[{c}] {m}")

# ---- skills
skills = {}
for p in sorted(glob.glob(".devin/skills/*/SKILL.md")):
    d = os.path.basename(os.path.dirname(p))
    txt = open(p, encoding="utf-8").read()
    if not txt.startswith("---"):
        F("skill", f"{p}: no frontmatter"); continue
    fm = yaml.safe_load(txt.split("---", 2)[1])
    skills[d] = fm
    if fm.get("name") != d: F("skill", f"{p}: name {fm.get('name')!r} != dir {d}")
    if not fm.get("description"): F("skill", f"{p}: no description")
    t = fm.get("triggers") or []
    if not (isinstance(t, list) and "user" in t and "model" in t):
        F("skill", f"{p}: triggers must be a list containing user and model (got {t!r})")
for p in glob.glob(".devin/skills/*/*/SKILL.md"):
    F("skill", f"{p}: nested too deep, not discoverable")

# ---- every skill named in role-routing.yaml is installed (the Skill config tab counts the rest)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skill_homes
for n in skill_homes.unknown_names():
    F("skill", f".devin/rules/role-routing.yaml names /{n}, which is not an installed skill")

# ---- gate approvers and backups are people on the roster (or listed under not_on_roster), never a role title
_roster = yaml.safe_load(open(".devin/rules/people.yaml", encoding="utf-8")) or {}
_norm = lambda n: "".join(sorted(re.findall(r"[a-z0-9]+", str(n).lower())))  # noqa: E731
_on = {_norm(p.get("name")) for p in _roster.get("people") or []}
_gdoc = yaml.safe_load(open(".devin/rules/approval-gates.yaml", encoding="utf-8")) or {}
_off = {_norm(n) for n in _gdoc.get("not_on_roster") or []}
for _g in _gdoc.get("gates") or []:
    for _a in _g.get("approvers") or []:
        for _n in (_a.get("names") or []) + (_a.get("backups") or []):
            if _norm(_n) not in _on | _off:
                F("gate", f"{_g.get('id')}: approver {_n!r} is not on the roster (people.yaml) or under not_on_roster")

# ---- agents
agents = sorted(glob.glob(".devin/agents/*.agent.yaml") + glob.glob(".devin/agents/*/*.agent.yaml"))
for p in agents:
    try: a = yaml.safe_load(open(p, encoding="utf-8"))
    except Exception as e: F("agent", f"{p}: YAML error {e}"); continue
    for s in (a or {}).get("allowed_skills", []) or []:
        n = str(s).lstrip("/")
        if n not in skills: F("agent", f"{p}: allowed_skill '{n}' has no skill dir")

# ---- rules / templates / config
gates = set()
for p in glob.glob(".devin/rules/*.yaml") + glob.glob(".devin/templates/*.yaml") + glob.glob(".devin/*.json"):
    try:
        data = yaml.safe_load(open(p, encoding="utf-8"))
    except Exception as e:
        F("config", f"{p}: parse error {e}"); continue
    if p.endswith("approval-gates.yaml"):
        for g in (data or {}).get("gates", []) or []:
            gates.add(g.get("id") or g.get("gate_id"))
gates.discard(None)

# ---- playbooks
DOCS_ONLY = {"PLAYBOOK-GUIDE.md", "PB-VALIDATION-multi-environment.md"}
cmd_re = re.compile(r"(?:^|[\s`(\"'])/([a-z][a-z0-9-]{2,})(?=[\s`)\"'.,:]|$)", re.M)
pbs = sorted(glob.glob("sdlc/framework/playbooks/*.md"))
mapped = {}
for p in pbs:
    name = os.path.basename(p)
    txt = open(p, encoding="utf-8").read()
    cmds = {c for c in cmd_re.findall(txt) if c in skills}
    unknown = {c for c in cmd_re.findall(txt) if c not in skills and not re.search(r"(api|views|urls|serializers|src|app|docs?)$", c)}
    if name in DOCS_ONLY: continue
    mapped[name] = sorted(cmds)
    if not cmds: F("playbook", f"{name}: maps to no existing skill")
    for g in set(re.findall(r"\b(SDLC_\d+[a-z]?_[A-Z_]+|[A-Z]+_[A-Z_]*REVIEW(?:_SIGNOFF)?)\b", txt)):
        if g.startswith("SDLC_") and g not in gates:
            F("playbook", f"{name}: unknown gate {g}")

# ---- file references inside skills (repo-relative, existing)
ref_re = re.compile(r"(?<![\w./-])((?:web|api|\.devin)/[\w./{}-]+\.(?:md|yaml|yml|json|py|tsx|ts)(?:\.template)?)")
for d, fm in skills.items():
    txt = open(f".devin/skills/{d}/SKILL.md", encoding="utf-8").read()
    for ref in set(ref_re.findall(txt)):
        if "{" in ref or "..." in ref: continue
        if not os.path.exists(ref): W("ref", f"{d}: missing {ref}")

# ---- visibility: every skill says whether it is part of the public front door
PUBLIC_SURFACE = {"start", "status", "approve", "ask-question", "explain-capability", "impact-radar",
                  "handover", "dashboard", "help"}
for d, fm in skills.items():
    vis = fm.get("visibility")
    if vis not in ("public", "internal"):
        F("skill", f"{d}: visibility must be public or internal (got {vis!r})")
    elif (vis == "public") != (d in PUBLIC_SURFACE):
        F("skill", f"{d}: visibility {vis} but the public surface is {sorted(PUBLIC_SURFACE)}")

# ---- count drift: the numbers documents quote must match the repository
n_prompts = len(glob.glob("docs/knowledge-base/Archive/PROMPTS/**/*", recursive=True))
n_pb_docs = len([p for p in pbs if os.path.basename(p) in DOCS_ONLY])
n_macros = len([p for p in pbs if re.match(r"PB-\d+-", os.path.basename(p))])
counts = {
    "skills": len(skills), "agents": len(agents), "gates": len(gates), "prompts": n_prompts,
    "playbooks_exec": len(mapped), "playbooks_docs": n_pb_docs, "macros": n_macros,
    "workflows": len(glob.glob("sdlc/framework/workflows/*.md")),
    "templates": len(glob.glob(".devin/templates/*")),
    "rules": len(glob.glob(".devin/rules/*")),
}
# (file, regex with one capture group per count, counts in group order)
DRIFT = [
    ("AGENTS.md", r"\| Skills \((\d+)\) \|", ["skills"]),
    ("AGENTS.md", r"\| Agents \((\d+) YAML", ["agents"]),
    ("AGENTS.md", r"\| Templates \((\d+)\) \|", ["templates"]),
    ("AGENTS.md", r"\| Playbooks \((\d+) runnable \+ (\d+) docs\) \|", ["playbooks_exec", "playbooks_docs"]),
    ("AGENTS.md", r"\| Workflows \((\d+)\) \|", ["workflows"]),
    ("sdlc/framework/ARCHITECTURE.md", r"Playbook macros<br/>!pb_01 … !pb_\d+ \((\d+)\)", ["macros"]),
    ("sdlc/framework/ARCHITECTURE.md", r"Slash commands<br/>[^\"]*? \((\d+)\)", ["skills"]),
    ("sdlc/framework/ARCHITECTURE.md", r"approval-gates\.yaml \((\d+)\)", ["gates"]),
    ("sdlc/framework/ARCHITECTURE.md", r"PROMPTS/ \((\d+)\)", ["prompts"]),
    ("sdlc/framework/ARCHITECTURE.md", r"^\| Playbooks \| `[^`]+` \| (\d+) \|", ["macros"]),
    ("sdlc/framework/ARCHITECTURE.md", r"^\| Skills \| `[^`]+` \| (\d+) \|", ["skills"]),
    ("sdlc/framework/ARCHITECTURE.md", r"^\| Agents \| `[^`]+` \| (\d+) \|", ["agents"]),
    ("sdlc/framework/ARCHITECTURE.md", r"^\| Workflows \| `[^`]+` \| (\d+) \|", ["workflows"]),
    ("sdlc/framework/ARCHITECTURE.md", r"^\| Rules \| `[^`]+` \| (\d+) \|", ["rules"]),
    ("sdlc/framework/ARCHITECTURE.md", r"^\| Templates \| `[^`]+` \| (\d+) \|", ["templates"]),
    ("sdlc/framework/ARCHITECTURE.md", r"^\| Prompts \| `[^`]+` \| (\d+) \|", ["prompts"]),
    ("sdlc/framework/CATALOGUE.md", r"^## Skills \((\d+)\)", ["skills"]),
    ("sdlc/framework/USER-MANUAL.md", r"slash commands you type in a session \S (\d+) of them", ["skills"]),
    ("sdlc/framework/CATALOGUE.md", r"^## Agents \((\d+)\)", ["agents"]),
]
FIX = "--fix" in sys.argv
for path, pattern, keys in DRIFT:
    if not os.path.exists(path):
        W("drift", f"{path}: missing, cannot check counts"); continue
    txt = open(path, encoding="utf-8").read()
    hits = list(re.finditer(pattern, txt, re.M))
    if not hits:
        W("drift", f"{path}: pattern for {keys} not found — the doc changed shape; update DRIFT in validate_framework.py")
        continue
    for m in hits:
        want = [str(counts[k]) for k in keys]
        got = list(m.groups())
        if got != want:
            if FIX:
                new = m.group(0)
                for g, w in zip(got, want):
                    new = new.replace(f"({g}", f"({w}", 1) if f"({g}" in new else new.replace(g, w, 1)
                txt = txt.replace(m.group(0), new, 1)
            else:
                F("drift", f"{path}: says {dict(zip(keys, got))}, repository has {dict(zip(keys, want))} (run with --fix)")
    if FIX:
        open(path, "w", encoding="utf-8").write(txt)

# ---- knowledge base manifest must match the files on disk
import subprocess
kbm = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb_manifest.py"), "validate"],
                     capture_output=True, text=True)
if kbm.returncode == 2:
    W("kb", "no KNOWLEDGE-MANIFEST.yaml — run tools/kb_manifest.py generate")
elif kbm.returncode != 0:
    F("kb", "knowledge base drifted from KNOWLEDGE-MANIFEST.yaml — run tools/kb_manifest.py generate in the same PR")

# ---- the ontology the SDLC skills look things up in must match its KB sources
onto = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ontology_lookup.py"), "check"],
                      capture_output=True, text=True)
if onto.returncode != 0:
    W("ontology", "ACME_ONTOLOGY.yaml is older than its KB sources — run tools/kbgen/gen_ontology.py in the same PR")

# ---- reference pages Argus menu opens must match their Markdown sources
ref = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_reference_pages.py"), "--check"],
                     capture_output=True, text=True)
if ref.returncode != 0:
    F("reference", "reference/ pages are out of date — run tools/gen_reference_pages.py in the same PR")

print(f"skills: {len(skills)}  agents: {len(agents)}  playbooks(exec): {len(mapped)}  gates: {len(gates)}")
print(f"prompts: {len(glob.glob('docs/knowledge-base/Archive/PROMPTS/**/*', recursive=True))}")
print(f"\nFAILURES ({len(fail)}):"); [print(" ", x) for x in fail]
print(f"\nWARNINGS ({len(warn)}):"); [print(" ", x) for x in warn]
sys.exit(1 if fail else 0)
