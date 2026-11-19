"""Build and dependency scanner: pom.xml, gradle, npm, pip, go.mod, csproj, Cargo, Gemfile, composer."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from ..facts import ev, make_fact

BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "package.json",
               "requirements.txt", "pyproject.toml", "go.mod", "cargo.toml", "gemfile", "composer.json", "setup.py", "pipfile")


def is_build_file(rel: str) -> bool:
    name = rel.lower().rsplit("/", 1)[-1]
    return name in BUILD_FILES or name.endswith((".csproj", ".vbproj", ".fsproj")) or re.fullmatch(r"requirements[-\w]*\.txt", name) is not None


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _line_of(text: str, needle: str) -> int:
    idx = text.find(needle)
    return text.count("\n", 0, idx) + 1 if idx >= 0 else 1


def scan_build(repo: str, rel: str, text: str) -> list[dict]:
    name = rel.lower().rsplit("/", 1)[-1]
    src = f"{repo}/{rel}"
    out: list[dict] = []

    def dep(group, artifact, version, scope, ecosystem, quote_key):
        out.append(make_fact(
            "dependency", f"{ecosystem}:{group + ':' if group else ''}{artifact}",
            {"ecosystem": ecosystem, "group": group, "artifact": artifact, "version": version, "scope": scope, "repo": repo, "path": rel},
            "OBSERVED", [ev(src, f"L{_line_of(text, quote_key)}", quote_key)], "build"))

    try:
        if name == "pom.xml":
            root = _strip_ns(ET.fromstring(text))
            g = (root.findtext("groupId") or (root.findtext("parent/groupId") or "")).strip()
            a = (root.findtext("artifactId") or "").strip()
            v = (root.findtext("version") or root.findtext("parent/version") or "").strip()
            props_el = root.find("properties")
            props = {p.tag: (p.text or "").strip() for p in (props_el if props_el is not None else [])}
            out.append(make_fact("module", f"maven:{g}:{a}", {
                "ecosystem": "maven", "group": g, "artifact": a, "version": v, "packaging": (root.findtext("packaging") or "jar").strip(),
                "parent": (root.findtext("parent/artifactId") or "").strip() or None,
                "modules": [m.text.strip() for m in root.findall("modules/module") if m.text],
                "java_version": props.get("java.version") or props.get("maven.compiler.source") or props.get("maven.compiler.release"),
                "repo": repo, "path": rel}, "OBSERVED", [ev(src, "L1", f"<artifactId>{a}</artifactId>")], "build"))
            for d in root.findall("dependencies/dependency") + root.findall("dependencyManagement/dependencies/dependency"):
                dg, da = (d.findtext("groupId") or "").strip(), (d.findtext("artifactId") or "").strip()
                dv = (d.findtext("version") or "").strip()
                dv = props.get(dv[2:-1], dv) if dv.startswith("${") else dv
                dep(dg, da, dv or None, (d.findtext("scope") or "compile").strip(), "maven", f"<artifactId>{da}</artifactId>")
            for pr in root.findall("profiles/profile"):
                pid = (pr.findtext("id") or "").strip()
                out.append(make_fact("build_profile", f"maven-profile:{pid}", {"id": pid, "repo": repo, "path": rel},
                                     "OBSERVED", [ev(src, f"L{_line_of(text, '<id>' + pid)}", f"<id>{pid}</id>")], "build"))
            for pl in root.findall("build/plugins/plugin"):
                pa = (pl.findtext("artifactId") or "").strip()
                out.append(make_fact("build_plugin", f"maven-plugin:{pa}", {"artifact": pa, "version": (pl.findtext("version") or "").strip() or None,
                                                                         "repo": repo, "path": rel},
                                     "OBSERVED", [ev(src, f"L{_line_of(text, pa)}", pa)], "build"))
        elif name.endswith((".csproj", ".vbproj", ".fsproj")):
            root = _strip_ns(ET.fromstring(text))
            tf = root.findtext(".//TargetFramework") or root.findtext(".//TargetFrameworks")
            out.append(make_fact("module", f"dotnet:{name}", {"ecosystem": "nuget", "target_framework": tf, "repo": repo, "path": rel},
                                 "OBSERVED", [ev(src, "L1")], "build"))
            for pr in root.iter("PackageReference"):
                dep("", pr.get("Include", ""), pr.get("Version"), "compile", "nuget", pr.get("Include", ""))
        elif name == "package.json":
            d = json.loads(text)
            out.append(make_fact("module", f"npm:{d.get('name', rel)}", {
                "ecosystem": "npm", "name": d.get("name"), "version": d.get("version"), "main": d.get("main"),
                "scripts": sorted((d.get("scripts") or {}).keys()), "engines": d.get("engines"), "repo": repo, "path": rel},
                "OBSERVED", [ev(src, "L1", '"name"')], "build"))
            for sect, scope in (("dependencies", "compile"), ("devDependencies", "dev"), ("peerDependencies", "peer")):
                for k, v in (d.get(sect) or {}).items():
                    dep("", k, str(v), scope, "npm", f'"{k}"')
        elif name.startswith("requirements") and name.endswith(".txt"):
            for i, line in enumerate(text.splitlines(), 1):
                s = line.split("#")[0].strip()
                if not s or s.startswith(("-", "git+", "http")):
                    continue
                m = re.match(r"([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*((?:==|>=|<=|~=|!=|>|<).+)?", s)
                if m:
                    out.append(make_fact("dependency", f"pypi:{m.group(1).lower()}", {
                        "ecosystem": "pypi", "artifact": m.group(1), "version": (m.group(2) or "").strip() or None, "scope": "compile",
                        "repo": repo, "path": rel}, "OBSERVED", [ev(src, f"L{i}", s)], "build"))
        elif name == "pyproject.toml":
            for m in re.finditer(r'"([A-Za-z0-9_.\-]+)\s*((?:==|>=|<=|~=|>|<)[^"]*)?"', _toml_section(text, "dependencies")):
                dep("", m.group(1), (m.group(2) or "").strip() or None, "compile", "pypi", m.group(1))
        elif name == "go.mod":
            mod = re.search(r"^module\s+(\S+)", text, re.M)
            gov = re.search(r"^go\s+(\S+)", text, re.M)
            out.append(make_fact("module", f"go:{mod.group(1) if mod else rel}", {"ecosystem": "go", "go_version": gov.group(1) if gov else None,
                                                                                 "repo": repo, "path": rel}, "OBSERVED", [ev(src, "L1")], "build"))
            for m in re.finditer(r"^\s*(?:require\s+)?([\w.\-/]+\.[\w.\-/]+)\s+(v[\w.\-+]+)", text, re.M):
                dep("", m.group(1), m.group(2), "compile", "go", m.group(1))
        elif name in ("build.gradle", "build.gradle.kts"):
            out.append(make_fact("module", f"gradle:{rel}", {"ecosystem": "gradle", "repo": repo, "path": rel}, "OBSERVED", [ev(src, "L1")], "build"))
            for m in re.finditer(r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation|annotationProcessor|kapt)\s*\(?\s*['"]([\w.\-]+):([\w.\-]+)(?::([\w.\-${}]+))?['"]""", text):
                dep(m.group(1), m.group(2), m.group(3), "compile", "maven", m.group(0))
        elif name in ("settings.gradle", "settings.gradle.kts"):
            for m in re.finditer(r"""include\s*\(?\s*['"]:?([\w\-:]+)['"]""", text):
                out.append(make_fact("module", f"gradle-module:{m.group(1)}", {"ecosystem": "gradle", "repo": repo, "path": rel},
                                     "OBSERVED", [ev(src, f"L{_line_of(text, m.group(0))}", m.group(0))], "build"))
        elif name == "cargo.toml":
            for m in re.finditer(r'^([A-Za-z0-9_\-]+)\s*=\s*(?:"([^"]+)"|\{[^}]*version\s*=\s*"([^"]+)")', _toml_section(text, "dependencies"), re.M):
                dep("", m.group(1), m.group(2) or m.group(3), "compile", "cargo", m.group(1))
        elif name == "composer.json":
            d = json.loads(text)
            for k, v in (d.get("require") or {}).items():
                dep("", k, str(v), "compile", "composer", f'"{k}"')
        elif name == "gemfile":
            for m in re.finditer(r"""^\s*gem\s+['"]([\w\-]+)['"](?:\s*,\s*['"]([^'"]+)['"])?""", text, re.M):
                dep("", m.group(1), m.group(2), "compile", "rubygems", m.group(1))
    except (ET.ParseError, json.JSONDecodeError, ValueError) as exc:
        out.append(make_fact("unparsed", src, {"reason": f"build file did not parse: {type(exc).__name__}", "repo": repo, "path": rel},
                             "UNKNOWN", [ev(src, "L1")], "build"))
    return out


def _toml_section(text: str, section: str) -> str:
    m = re.search(rf"(?ms)^\[(?:[\w.\-]*\.)?{section}\]\s*(.*?)(?=^\[|\Z)|^{section}\s*=\s*\[(.*?)\]", text)
    return (m.group(1) or m.group(2) or "") if m else ""
