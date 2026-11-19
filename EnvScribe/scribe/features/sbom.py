"""Feature 3 - SBOM and license report (CycloneDX 1.5 JSON and SPDX 2.3 JSON) with optional vulnerability lookup.

Components are the *declared* dependencies from build files (no transitive resolution is performed; that is stated in the report).
Dependency licenses are UNKNOWN unless a manifest states them; this feature never guesses a license from a package name.
Project licenses come from LICENSE files and manifest fields. Vulnerability lookup (OSV) is off by default because it sends
package names and versions to a public service; only advisory ids are written back, never URLs.
"""
from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Callable

from ..facts import ev, make_fact
from ..util import read_text
from .common import Ctx, Result, cite, header, md_cell, slug

_PURL_TYPE = {"maven": "maven", "npm": "npm", "pypi": "pypi", "nuget": "nuget", "go": "golang", "cargo": "cargo", "composer": "composer", "rubygems": "gem"}
_OSV_ECO = {"maven": "Maven", "npm": "npm", "pypi": "PyPI", "nuget": "NuGet", "go": "Go", "cargo": "crates.io", "composer": "Packagist", "rubygems": "RubyGems"}
_COPYLEFT = re.compile(r"(?i)\b(AGPL|GPL|LGPL|SSPL|EUPL|MPL|CDDL|EPL|OSL|CPAL|CC-BY-SA)")
_STRONG = re.compile(r"(?i)\b(AGPL|SSPL|GPL(?!.*classpath)|EUPL|OSL|CPAL)")
_LICENSE_SIGNS = [("Apache-2.0", r"Apache License,? Version 2\.0|apache\.org/licenses/LICENSE-2\.0"), ("MIT", r"Permission is hereby granted, free of charge"),
                  ("BSD-3-Clause", r"Redistribution and use in source and binary forms.*neither the name"), ("BSD-2-Clause", r"Redistribution and use in source and binary forms"),
                  ("AGPL-3.0", r"GNU AFFERO GENERAL PUBLIC LICENSE"), ("LGPL-3.0", r"GNU LESSER GENERAL PUBLIC LICENSE\s+Version 3"),
                  ("GPL-3.0", r"GNU GENERAL PUBLIC LICENSE\s+Version 3"), ("GPL-2.0", r"GNU GENERAL PUBLIC LICENSE\s+Version 2"),
                  ("MPL-2.0", r"Mozilla Public License,? (?:Version |v\.? ?)2\.0"), ("ISC", r"Permission to use, copy, modify, and/or distribute"),
                  ("Unlicense", r"This is free and unencumbered software")]


def purl(a: dict) -> str:
    eco = a["ecosystem"]
    t = _PURL_TYPE.get(eco, eco)
    name = a["artifact"]
    ns = a.get("group") or ""
    v = a.get("version") or ""
    base = f"pkg:{t}/{ns}/{name}" if ns and t == "maven" else f"pkg:{t}/{name}"
    return base + (f"@{v}" if v and not v.startswith("$") else "")


def project_license(root: str, exclude: list[str]) -> tuple[str | None, str | None]:
    """(spdx id or free text, source file) from LICENSE files and manifest license fields."""
    r = Path(root)
    for nm in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING"):
        p = r / nm
        if p.is_file() and not any(x and x in nm for x in exclude):
            text, _ = read_text(str(p), 200_000)
            for spdx, rx in _LICENSE_SIGNS:
                if text and re.search(rx, text, re.S | re.I):
                    return spdx, nm
            return "UNRECOGNIZED", nm
    p = r / "package.json"
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            lic = d.get("license")
            if isinstance(lic, str) and lic:
                return lic, "package.json"
        except ValueError:
            pass
    p = r / "pom.xml"
    if p.is_file():
        m = re.search(r"<licenses>.*?<name>([^<]+)</name>", p.read_text(encoding="utf-8", errors="replace"), re.S)
        if m:
            return m.group(1).strip(), "pom.xml"
    return None, None


def osv_lookup(components: list[dict], fetch: Callable[[list[dict]], list[list[str]]] | None = None) -> dict[int, list[str]]:
    """Advisory ids per component index. `fetch` is injectable; the default sends names+versions to the OSV batch endpoint."""
    queries, idx = [], []
    for i, c in enumerate(components):
        eco = _OSV_ECO.get(c["ecosystem"])
        if eco and c.get("version") and not str(c["version"]).startswith(("$", "[", "(")):
            name = f"{c['group']}:{c['artifact']}" if c.get("group") and c["ecosystem"] == "maven" else c["artifact"]
            queries.append({"package": {"name": name, "ecosystem": eco}, "version": re.sub(r"^[v=^~]+", "", str(c["version"]))})
            idx.append(i)
    if not queries:
        return {}
    if fetch is None:
        import httpx

        def fetch(qs):
            out = []
            with httpx.Client(timeout=30) as cl:
                for k in range(0, len(qs), 500):
                    r = cl.post("https://api.osv.dev/v1/querybatch", json={"queries": qs[k:k + 500]})
                    r.raise_for_status()
                    out += [[v["id"] for v in (x.get("vulns") or [])] for x in r.json().get("results", [])]
            return out
    res = fetch(queries)
    return {idx[j]: ids for j, ids in enumerate(res) if ids}


def components(ctx: Ctx) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for f in ctx.k("dependency"):
        a = f["attrs"]
        if a.get("scope") in ("test",):
            continue
        key = (a["repo"], a["ecosystem"], a.get("group") or "", a["artifact"], a.get("version") or "")
        if key not in seen:
            seen[key] = {"repo": a["repo"], "ecosystem": a["ecosystem"], "group": a.get("group") or "", "artifact": a["artifact"],
                         "version": a.get("version"), "scope": a.get("scope"), "cite": cite(f), "fact": f}
    return sorted(seen.values(), key=lambda c: (c["repo"], c["ecosystem"], c["group"], c["artifact"]))


def run(ctx: Ctx, vuln_fetch=None) -> Result:
    comps = components(ctx)
    lic = {r: project_license(root, ctx.settings.exclude_sources) for r, root in ctx.repos.items()}
    vulns: dict[int, list[str]] = {}
    vuln_note = "Vulnerability lookup is off (setting `vuln_lookup`). Nothing was sent to any external service."
    if ctx.settings.vuln_lookup:
        try:
            vulns = osv_lookup(comps, vuln_fetch)
            vuln_note = f"Vulnerability lookup ran against the OSV database; {len(vulns)} component(s) have advisories. Only package names and versions were sent."
        except Exception as exc:
            vuln_note = f"UNKNOWN: vulnerability lookup failed ({type(exc).__name__}); no advisory data is included."
    facts: list[dict] = []
    for i, c in enumerate(comps):
        if i in vulns:
            facts.append(make_fact("vulnerability", f"{c['repo']}:{purl(c)}", {"repo": c["repo"], "component": purl(c), "advisories": sorted(vulns[i])[:30]},
                                   "DERIVED", c["fact"]["evidence"], "sbom", "OSV advisory ids returned for this exact package name and version"))
    for r, (l, src) in lic.items():
        if l:
            facts.append(make_fact("project_license", f"{r}:license", {"repo": r, "license": l, "source": src, "copyleft": bool(_COPYLEFT.search(l)),
                                                                          "strong_copyleft": bool(_STRONG.search(l))},
                                   "OBSERVED", [ev(f"{r}/{src}", "L1")], "sbom"))
    # ---- CycloneDX
    ns = str(uuid.uuid5(uuid.NAMESPACE_URL, ctx.run_id))
    cdx_components = []
    for i, c in enumerate(comps):
        e = {"type": "library", "bom-ref": f"c{i}", "name": c["artifact"], "purl": purl(c), "properties": [{"name": "envscribe:service", "value": c["repo"]},
                                                                                                          {"name": "envscribe:scope", "value": str(c["scope"])}]}
        if c["group"]:
            e["group"] = c["group"]
        if c["version"]:
            e["version"] = str(c["version"])
        cdx_components.append(e)
    cdx = {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{ns}", "version": 1,
           "metadata": {"timestamp": ctx.collated_at, "tools": {"components": [{"type": "application", "name": "EnvScribe"}]},
                        "properties": [{"name": "envscribe:note", "value": "declared dependencies only; transitive dependencies not resolved"}]},
           "components": cdx_components,
           "vulnerabilities": [{"id": adv, "affects": [{"ref": f"c{i}"}]} for i, ids in sorted(vulns.items()) for adv in ids[:30]]}
    # ---- SPDX 2.3
    pk = []
    for i, c in enumerate(comps):
        pk.append({"SPDXID": f"SPDXRef-Package-{i}", "name": c["artifact"], "versionInfo": str(c["version"] or "NOASSERTION"),
                   "downloadLocation": "NOASSERTION", "filesAnalyzed": False, "licenseConcluded": "NOASSERTION", "licenseDeclared": "NOASSERTION",
                   "copyrightText": "NOASSERTION", "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": purl(c)}]})
    spdx = {"spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT", "name": f"envscribe-{ctx.run_id}",
            "documentNamespace": f"urn:envscribe:{ctx.run_id}:{ns}",
            "creationInfo": {"created": ctx.collated_at.replace("+00:00", "Z") if "T" in ctx.collated_at else ctx.collated_at, "creators": ["Tool: EnvScribe"]},
            "packages": pk}
    # ---- report
    by_repo: dict[str, list] = defaultdict(list)
    for c in comps:
        by_repo[c["repo"]].append(c)
    md = [header("SBOM and license report", ctx, "Declared dependencies only; transitive dependencies are not resolved."), vuln_note + "\n",
          "## Project licenses (OBSERVED from LICENSE files and manifests)\n\n| Service | License | Source | Flag |\n|---|---|---|---|"]
    for r in ctx.repo_names:
        l, src = lic.get(r, (None, None))
        flag = "strong copyleft: legal review" if l and _STRONG.search(l) else "copyleft: review obligations" if l and _COPYLEFT.search(l) else "UNRECOGNIZED text: review" if l == "UNRECOGNIZED" else ""
        md.append(f"| `{r}` | {md_cell(l) if l else 'UNKNOWN: none found'} | {md_cell(src) or '-'} | {flag or '-'} |")
    md.append(f"\n## Dependency licenses\n\nUNKNOWN for all {len(comps)} declared component(s): manifests in the scanned repositories do not state dependency licenses and this tool does not guess them. "
              "Feed `sbom/cyclonedx.json` to a license scanner for resolved data.\n\n## Components by service\n")
    for r, cs in sorted(by_repo.items()):
        md.append(f"### {r} ({len(cs)})\n")
        md += [f"- `{purl(c)}` ({c['scope']})" + (f" **advisories: {', '.join(vulns[comps.index(c)][:5])}**" if comps.index(c) in vulns else "") for c in cs[:400]]
        if len(cs) > 400:
            md.append(f"- … {len(cs) - 400} more in cyclonedx.json")
    unpinned = [c for c in comps if not c["version"] or str(c["version"]).startswith(("$", "[", "(", "*", "latest"))]
    md.append(f"\n## Unpinned or unresolved versions ({len(unpinned)})\n")
    md += [f"- `{c['repo']}` `{c['artifact']}` {c['version'] or '(no version)'} - {c['cite']}" for c in unpinned[:200]] or ["- none"]
    return Result(files={"sbom/index.md": "\n".join(md) + "\n", "sbom/cyclonedx.json": json.dumps(cdx, indent=1), "sbom/spdx.json": json.dumps(spdx, indent=1)},
                  facts=facts, index=["- [SBOM and licenses](sbom/index.md) · `sbom/cyclonedx.json` · `sbom/spdx.json`"],
                  coverage={"sbom": f"{len(comps)} declared components; vulnerability lookup {'on' if ctx.settings.vuln_lookup else 'off'}"})
