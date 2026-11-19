"""Language-agnostic code crawler. Plain code, no LLM. Unknown languages fall back to text-only facts."""
from __future__ import annotations

import re

from ..facts import ev, make_fact

LANG = {
    ".py": "python", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala", ".groovy": "groovy",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php", ".cs": "csharp", ".vb": "vb",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".swift": "swift", ".m": "objc",
    ".sql": "sql", ".sh": "shell", ".bash": "shell", ".ps1": "powershell", ".bat": "batch", ".pl": "perl",
    ".r": "r", ".lua": "lua", ".dart": "dart", ".cbl": "cobol", ".cob": "cobol", ".cpy": "cobol", ".jcl": "jcl",
    ".tf": "terraform", ".proto": "proto", ".graphql": "graphql", ".gql": "graphql", ".xml": "xml",
    ".html": "html", ".css": "css", ".vue": "vue", ".ex": "elixir", ".erl": "erlang", ".hs": "haskell",
    ".clj": "clojure", ".f90": "fortran", ".pas": "pascal", ".abap": "abap", ".pls": "plsql", ".pkb": "plsql",
}

_SYM = {
    "python": [("class", re.compile(r"^\s*class\s+(\w+)")), ("function", re.compile(r"^\s*(?:async\s+)?def\s+(\w+)"))],
    "java": [("class", re.compile(r"^\s*(?:public|protected|private|abstract|final|static|\s)*\b(?:class|interface|enum|record)\s+(\w+)")),
             ("function", re.compile(r"^\s*(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?[\w<>\[\],.? ]+\s+(\w+)\s*\([^;{]*\)?\s*(?:throws [\w, .]+)?\s*\{?\s*$"))],
    "kotlin": [("class", re.compile(r"^\s*(?:data\s+|sealed\s+|open\s+|abstract\s+)*(?:class|interface|object)\s+(\w+)")),
               ("function", re.compile(r"^\s*(?:override\s+|private\s+|public\s+|internal\s+|suspend\s+)*fun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?(\w+)"))],
    "csharp": [("class", re.compile(r"^\s*(?:public|internal|private|protected|abstract|sealed|static|partial|\s)*\b(?:class|interface|struct|enum|record)\s+(\w+)")),
               ("function", re.compile(r"^\s*(?:public|private|protected|internal)\s+(?:static\s+|async\s+|virtual\s+|override\s+)*[\w<>\[\],.? ]+\s+(\w+)\s*\([^;]*\)\s*\{?\s*$"))],
    "javascript": [("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)")),
                   ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)")),
                   ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"))],
    "go": [("class", re.compile(r"^\s*type\s+(\w+)\s+(?:struct|interface)")), ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)"))],
    "rust": [("class", re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)")), ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"))],
    "ruby": [("class", re.compile(r"^\s*(?:class|module)\s+(\w+)")), ("function", re.compile(r"^\s*def\s+(?:self\.)?(\w+)"))],
    "php": [("class", re.compile(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+(\w+)")), ("function", re.compile(r"^\s*(?:public|private|protected|static|\s)*function\s+(\w+)"))],
    "scala": [("class", re.compile(r"^\s*(?:case\s+)?(?:class|object|trait)\s+(\w+)")), ("function", re.compile(r"^\s*(?:override\s+|private\s+)?def\s+(\w+)"))],
    "swift": [("class", re.compile(r"^\s*(?:public\s+|final\s+)*(?:class|struct|enum|protocol)\s+(\w+)")), ("function", re.compile(r"^\s*(?:public\s+|private\s+|static\s+)*func\s+(\w+)"))],
    "c": [("function", re.compile(r"^[A-Za-z_][\w\s\*]*\s+\**(\w+)\s*\([^;]*\)\s*\{?\s*$"))],
    "shell": [("function", re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{"))],
    "cobol": [("function", re.compile(r"^\s{6,}([A-Z0-9-]+)\s+SECTION\.|^\s{6,}PROGRAM-ID\.\s+([A-Z0-9-]+)", re.I))],
    "plsql": [("function", re.compile(r"(?i)^\s*create\s+(?:or\s+replace\s+)?(?:procedure|function|package(?:\s+body)?)\s+([\w.\"]+)"))],
}
_SYM["typescript"] = _SYM["javascript"]
_SYM["groovy"] = _SYM["java"]
_SYM["cpp"] = _SYM["c"]
_SYM["vue"] = _SYM["javascript"]
_SYM["perl"] = [("function", re.compile(r"^\s*sub\s+(\w+)"))]
_SYM["lua"] = [("function", re.compile(r"^\s*(?:local\s+)?function\s+([\w.:]+)"))]
_SYM["dart"] = _SYM["java"]

_IMPORT = {
    "python": re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))"),
    "java": re.compile(r"^\s*import\s+(?:static\s+)?([\w.*]+);"),
    "kotlin": re.compile(r"^\s*import\s+([\w.*]+)"),
    "scala": re.compile(r"^\s*import\s+([\w.{}_, ]+)"),
    "javascript": re.compile(r"""(?:^\s*import\s+(?:.+?\s+from\s+)?['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))"""),
    "go": re.compile(r'^\s*(?:import\s+)?(?:\w+\s+)?"([\w./-]+)"\s*$'),
    "csharp": re.compile(r"^\s*using\s+(?:static\s+)?([\w.]+);"),
    "rust": re.compile(r"^\s*use\s+([\w:]+)"),
    "ruby": re.compile(r"^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]"),
    "php": re.compile(r"^\s*use\s+([\w\\]+)"),
}
_IMPORT["typescript"] = _IMPORT["javascript"]
_IMPORT["vue"] = _IMPORT["javascript"]

_ENTRY = [
    (re.compile(r"""if\s+__name__\s*==\s*['"]__main__['"]"""), "python main guard"),
    (re.compile(r"public\s+static\s+void\s+main\s*\("), "java main()"),
    (re.compile(r"@SpringBootApplication"), "spring boot application"),
    (re.compile(r"^\s*func\s+main\s*\(\s*\)"), "go main()"),
    (re.compile(r"static\s+(?:async\s+)?(?:void|Task|int)\s+Main\s*\("), "c# Main()"),
    (re.compile(r"^\s*fun\s+main\s*\("), "kotlin main()"),
    (re.compile(r"(?i)\bFastAPI\s*\("), "fastapi app"),
    (re.compile(r"(?i)\bFlask\s*\(\s*__name__"), "flask app"),
    (re.compile(r"""\bexpress\s*\(\s*\)"""), "express app"),
    (re.compile(r"PROGRAM-ID\.", re.I), "cobol program"),
]

_ENDPOINT = [
    (re.compile(r"""@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?\{?\s*['"]([^'"]+)['"]"""), "spring"),
    (re.compile(r"""@Path\s*\(\s*['"]([^'"]+)['"]\s*\)"""), "jax-rs"),
    (re.compile(r"""@(?:\w+\.)?(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""", re.I), "decorator"),
    (re.compile(r"""@\w+\.route\s*\(\s*['"]([^'"]+)['"]"""), "flask"),
    (re.compile(r"""\b(?:app|router|server)\.(get|post|put|delete|patch)\s*\(\s*['"`]([^'"`]+)['"`]"""), "express"),
    (re.compile(r"""\[Http(Get|Post|Put|Delete|Patch)\(?\s*(?:"([^"]*)")?"""), "aspnet"),
    (re.compile(r"""\.(Get|Post|Put|Delete|Patch)\(\s*"(/[^"]*)"\s*,""", re.I), "go-router"),
]

_ENV_USE = [
    re.compile(r"""os\.environ(?:\.get)?\s*[\[(]\s*['"](\w+)['"]"""),
    re.compile(r"""os\.getenv\s*\(\s*['"](\w+)['"]"""),
    re.compile(r"""System\.getenv\s*\(\s*['"](\w+)['"]"""),
    re.compile(r"""process\.env\.(\w+)|process\.env\[\s*['"](\w+)['"]"""),
    re.compile(r"""Environment\.GetEnvironmentVariable\s*\(\s*"(\w+)"\)"""),
    re.compile(r"""os\.Getenv\s*\(\s*"(\w+)"\)"""),
    re.compile(r"""\$\{(\w+)(?::[^}]*)?\}"""),
]
_PROP_USE = [
    re.compile(r"""@Value\s*\(\s*["']\$\{([\w.\-]+)(?::[^}]*)?\}"""),
    re.compile(r"""@ConfigurationProperties\s*\(\s*(?:prefix\s*=\s*)?["']([\w.\-]+)["']"""),
    re.compile(r"""getProperty\s*\(\s*["']([\w.\-]+)["']"""),
]
_URL = re.compile(r"""https?://[A-Za-z0-9_.\-]+(?::\d+)?(?:/[^\s'"`<>)\\]*)?""")
_SQL = re.compile(r"""(?i)\b(?:from|join|into|update|delete\s+from|truncate\s+table|table)\s+(?:if\s+(?:not\s+)?exists\s+)?([A-Za-z_][\w$.]*)""")
_SQL_HINT = re.compile(r"""(?i)\b(select\b.+\bfrom\b|insert\s+into|update\s+\w+\s+set|delete\s+from|create\s+table|alter\s+table)""")
_MESSAGING = re.compile(r"""(?i)(?:@KafkaListener\s*\(\s*topics\s*=\s*["']([\w.\-]+)["']|\.subscribe\(\s*["']([\w.\-]+)["']|@RabbitListener\s*\(\s*queues\s*=\s*["']([\w.\-]+)["']|\.send\(\s*["']([\w.\-]+)["'])""")
_TEST = re.compile(r"(?i)(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec|Test|Tests|IT)\.\w+$")
_SQL_KEYWORDS = {"select", "where", "set", "values", "table", "the", "a", "an", "dual", "lateral", "unnest", "only"}

MAX_FACTS_PER_KIND = 400


def language_of(rel: str) -> str | None:
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    if name in ("dockerfile", "jenkinsfile", "makefile") or name.endswith(".dockerfile"):
        return {"dockerfile": "docker", "jenkinsfile": "groovy", "makefile": "make"}.get(name.split(".")[0], None) or "docker"
    for ext, lang in LANG.items():
        if low.endswith(ext):
            return lang
    return None


def scan_code(repo: str, rel: str, text: str, lang: str) -> list[dict]:
    src = f"{repo}/{rel}"
    facts: list[dict] = []
    lines = text.splitlines()
    syms = _SYM.get(lang, [])
    imp = _IMPORT.get(lang)
    counts: dict[str, int] = {}

    def add(kind, subject, attrs, lineno, quote, cls="OBSERVED", rule=None):
        if counts.get(kind, 0) >= MAX_FACTS_PER_KIND:
            return
        counts[kind] = counts.get(kind, 0) + 1
        facts.append(make_fact(kind, subject, attrs, cls, [ev(src, f"L{lineno}", quote)], "code", rule))

    facts.append(make_fact(
        "source_file", src, {"repo": repo, "path": rel, "language": lang, "lines": len(lines), "is_test": bool(_TEST.search(rel))},
        "OBSERVED", [ev(src, f"L1-{max(len(lines), 1)}")], "code"))

    for i, line in enumerate(lines, 1):
        if len(line) > 1000:
            continue
        s = line.strip()
        if not s:
            continue
        for kind, rx in syms:
            m = rx.search(line)
            if m:
                name = next((g for g in m.groups() if g), None)
                if name and name not in ("if", "for", "while", "switch", "return", "catch", "else"):
                    add("symbol", f"{src}#{name}", {"symbol_kind": kind, "name": name, "language": lang, "repo": repo, "path": rel}, i, s)
                break
        if imp:
            m = imp.search(line)
            if m:
                target = next((g for g in m.groups() if g), None)
                if target:
                    add("import", f"{src}->{target.strip()}", {"target": target.strip(), "repo": repo, "path": rel}, i, s)
        for rx, label in _ENTRY:
            if rx.search(line):
                add("entry_point", src, {"label": label, "repo": repo, "path": rel}, i, s)
        for rx, fw in _ENDPOINT:
            m = rx.search(line)
            if m:
                groups = [g for g in m.groups() if g is not None]
                path = next((g for g in reversed(groups) if g.startswith("/") or g == ""), groups[-1] if groups else "")
                verb = next((g for g in groups if g.lower() in ("get", "post", "put", "delete", "patch", "request")), "ANY")
                add("endpoint", f"{verb.upper()} {path}", {"verb": verb.upper(), "path": path, "framework": fw, "repo": repo, "file": rel}, i, s)
                break
        for rx in _ENV_USE:
            for m in rx.finditer(line):
                name = next((g for g in m.groups() if g), None)
                if name and len(name) > 2 and name.upper() == name:
                    add("env_var_use", name, {"name": name, "repo": repo, "path": rel}, i, s)
        for rx in _PROP_USE:
            for m in rx.finditer(line):
                add("config_key_use", m.group(1), {"key": m.group(1), "repo": repo, "path": rel}, i, s)
        for m in _URL.finditer(line):
            url = m.group(0).rstrip(".,;")
            if "localhost" in url or "example.com" in url or "w3.org" in url or "schemas.xml" in url:
                continue
            add("url_reference", url, {"url": url, "repo": repo, "path": rel}, i, s)
        m = _MESSAGING.search(line)
        if m:
            topic = next((g for g in m.groups() if g), None)
            if topic:
                add("messaging_reference", topic, {"topic": topic, "repo": repo, "path": rel}, i, s)
        if lang == "sql" or _SQL_HINT.search(line):
            for m in _SQL.finditer(line):
                t = m.group(1).strip(".")
                if t.lower() not in _SQL_KEYWORDS and not t.isdigit() and len(t) > 1:
                    add("table_reference", t.lower(), {"table": t.lower(), "repo": repo, "path": rel},
                        i, s, "DERIVED", "sql-keyword-regex (static SQL text only; dynamic SQL is not resolved)")
        if re.search(r"(?i)\b(TODO|FIXME|HACK|XXX)\b", s) and len(s) < 300 and counts.get("todo", 0) < 50:
            add("todo", f"{src}", {"text": s[:160]}, i, s)
    return facts
