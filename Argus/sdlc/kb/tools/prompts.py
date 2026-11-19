#!/usr/bin/env python3
"""Lint and render the shared knowledge-base prompt library.

    python3 prompts.py lint [--strict] [FILE ...]   check shared prompts against the standard
    python3 prompts.py render FILE [--env ENV] [--set NAME=VALUE] [--stage DIR] [--out FILE]
                                                    print a prompt with the team's values filled in
    python3 prompts.py outputs FILE [--stage DIR] [--set NAME=VALUE]
                                                    list the files a prompt writes
    python3 prompts.py status                       how many prompts are shared vs not yet migrated

A prompt is shared when its frontmatter says `shareable: true`. Shared prompts must follow
PROMPT_STANDARD.md, use only placeholders listed in placeholders.yaml, and contain nothing
from the team profile: product names, schema and table names, paths, hosts or fixed counts.

Run it from the team's repo root. Locations can be overridden:
    KB_PROMPTS_DIR   folder holding the prompts (default: ../kb-prompts next to this tool)
    KB_TEAM_ROOT     the team's repo root (default: current directory)
    KB_PROFILE       the team profile (default: <team root>/.devin/rules/kb-profile.yaml)
"""
import argparse
import datetime
import glob
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_ROOT = os.path.abspath(os.path.join(HERE, ".."))

REQUIRED_META = ("prompt_id", "title", "kind", "pipeline", "version", "shareable", "placeholders", "outputs")
SECTIONS = {
    "prompt": ("Purpose", "Before you start", "Steps", "Output", "Evidence rules", "Self-check",
               "Open questions, assumptions and unknowns"),
    "runner": ("Purpose", "Before you start", "Stages", "Self-check"),
}
LEGACY_TAGS = re.compile(r"\[CONFIRMED|\[INFERRED|REQUIRES STAKEHOLDER INPUT|\[QUERY FAILED")
PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
FIXED_COUNT = re.compile(
    r"\b(\d{2,})\s+(?:[A-Za-z-]+\s+){0,2}?"
    r"(tables|views|columns|schemas|capabilities|modules|screens|endpoints|jobs|qualifying)\b", re.I)
THRESHOLD_WORDS = {"than", "over", "least", "top", "first", "last", "to", "up", "limit", "most",
                   "under", "below", "above", "every", ">", "<", ">=", "<=", "="}
GENERIC_LEAKS = (
    # The .example top-level domain is reserved (RFC 2606), so sample rosters may use it.
    (re.compile(r"[\w.+-]+@(?![\w.-]*\.example(?![\w.-]))[\w-]+\.[A-Za-z]{2,}"), "email address"),
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "12-digit number (looks like a cloud account id)"),
    (re.compile(r"sslVerify\s*=\s*false", re.I), "turns off TLS checks"),
    (re.compile(r"\b(password|passwd|secret|token)\s*[:=]\s*['\"]?[^\s'\"{}<>]{4,}", re.I), "credential-like value"),
)
SKIP_PROFILE_KEYS = {"engine", "environments_file", "kb_environment", "code_column_suffixes", "key_column_suffixes", "label", "default"}
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
LEAK_ONLY_FILES = ("PROMPT_STANDARD.md", "placeholders.yaml")


def team_root():
    return os.environ.get("KB_TEAM_ROOT") or os.getcwd()


def prompts_dir():
    return os.environ.get("KB_PROMPTS_DIR") or os.path.join(DIST_ROOT, "kb-prompts")


def profile_path():
    return os.environ.get("KB_PROFILE") or os.path.join(team_root(), ".devin", "rules", "kb-profile.yaml")


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def split(text):
    """Return (frontmatter dict or None, body). A frontmatter YAML error comes back as {'__error__': msg}."""
    m = FRONTMATTER.match(text)
    if not m:
        return None, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        return {"__error__": str(exc).splitlines()[0]}, text[m.end():]
    return (meta if isinstance(meta, dict) else {"__error__": "frontmatter is not a mapping"}), text[m.end():]


def registry(path=None):
    return load_yaml(path or os.path.join(prompts_dir(), "placeholders.yaml")).get("placeholders", {}) or {}


def get_path(data, dotted):
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _leaves(node, out, key=None):
    if key in SKIP_PROFILE_KEYS:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            _leaves(v, out, k)
    elif isinstance(node, list):
        for v in node:
            _leaves(v, out, key)
    elif isinstance(node, str):
        out.append(node)


# Folder names any team might use; they are not team data even when upper-case in a profile path.
COMMON_WORDS = {"modules", "docs", "prompts", "shared", "validation", "decisions", "documentation"}


def _bounded(term):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])", re.I)


def leak_rules(profile, base=None):
    """Compile (regex, label) pairs for everything team-specific in the profile."""
    base = base or team_root()
    lint = profile.get("lint") or {}
    rules = [(re.compile(re.escape(t), re.I), "team term '%s'" % t) for t in lint.get("leak_terms", []) if t]
    rules += [(re.compile(p), "team pattern /%s/" % p) for p in lint.get("leak_patterns", []) if p]
    values = []
    for section in ("product", "paths", "db"):
        _leaves(profile.get(section), values)
    for rel in lint.get("value_files", []):
        path = os.path.join(base, rel)
        if os.path.exists(path):
            _leaves(load_yaml(path), values)
    seen = {str(v).lower() for v in lint.get("allow_values", [])}
    for value in values:
        candidates = [value.strip()] + re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value)
        for c in candidates:
            c = c.strip(".-")
            keep = len(c) >= 4 and c.lower() not in COMMON_WORDS and (
                c == value.strip() or "_" in c or any(ch.isdigit() for ch in c) or c.isupper())
            if keep and c.lower() not in seen:
                seen.add(c.lower())
                rules.append((_bounded(c), "profile value '%s'" % c))
    return rules


def _fixed_count(line):
    for m in FIXED_COUNT.finditer(line):
        before = line[:m.start()].split()
        if before and before[-1].lower() in THRESHOLD_WORDS:
            continue
        return m.group(0)
    return None


def _section(body, name):
    m = re.search(r"^## " + re.escape(name) + r"\s*$(.*?)(?=^## |\Z)", body, re.M | re.S)
    return m.group(1) if m else ""


def lint_text(text, rel, reg, rules, strict=False, leak_only=False, generic=True):
    """Return a list of (file, line, level, message)."""
    issues = []

    def add(line, level, msg):
        issues.append((rel, line, level, msg))

    meta, body = split(text)
    if not leak_only:
        if meta and "__error__" in meta:
            add(1, "error", "frontmatter is not valid YAML: " + meta["__error__"])
            return issues
        if not meta or not meta.get("shareable"):
            if strict:
                add(1, "error", "not marked `shareable: true` yet")
            return issues
        for key in REQUIRED_META:
            if key not in meta:
                add(1, "error", "frontmatter is missing `%s`" % key)
        kind = meta.get("kind", "prompt")
        if kind not in SECTIONS:
            add(1, "error", "unknown kind '%s' (use one of %s)" % (kind, ", ".join(SECTIONS)))
        else:
            headings = set(h.strip() for h in re.findall(r"^## (.+)$", body, re.M))
            for name in SECTIONS[kind]:
                if name not in headings:
                    add(1, "error", "missing section `## %s`" % name)
            if "Self-check" in headings and not re.search(r"^- \[ \] ", _section(body, "Self-check"), re.M):
                add(1, "error", "`## Self-check` has no `- [ ]` items")
        declared = set(meta.get("placeholders") or [])
        used = set(PLACEHOLDER.findall(text))
        for name in sorted(used - declared):
            add(1, "error", "placeholder {{%s}} is used but not declared in frontmatter" % name)
        for name in sorted(declared - set(reg)):
            add(1, "error", "placeholder {{%s}} is not in placeholders.yaml" % name)
        for name in sorted(declared - used):
            add(1, "warning", "placeholder {{%s}} is declared but never used" % name)
    for n, line in enumerate(text.splitlines(), 1):
        if not leak_only and LEGACY_TAGS.search(line):
            add(n, "error", "old evidence tag; use [E: source], [A] or [?]")
        if not leak_only:
            count = _fixed_count(line)
            if count:
                add(n, "error", "fixed count '%s'; discover it at run time or use a placeholder" % count)
        for rx, label in (GENERIC_LEAKS if generic else ()):
            if rx.search(line):
                add(n, "error", label)
        for rx, label in rules:
            if rx.search(line):
                add(n, "error", label)
    return issues


def live_files(directory=None):
    directory = directory or prompts_dir()
    out = []
    for path in sorted(glob.glob(os.path.join(directory, "**", "*.md"), recursive=True)):
        rel = os.path.relpath(path, directory)
        if rel.split(os.sep)[0] == "Archive" or os.path.basename(path) in LEAK_ONLY_FILES:
            continue
        out.append(path)
    return out


def built_copy(path):
    """A versioned shared copy (v1.1026/...): its own build checks it, against all our values."""
    return re.match(r"v\d", os.path.relpath(path, DIST_ROOT)) is not None


def other_files(directory=None):
    """Every other file shipped in the distribution: tools, docs, the standard and the registry."""
    directory = directory or prompts_dir()
    linted = set(live_files(directory))
    out = []
    for path in sorted(glob.glob(os.path.join(DIST_ROOT, "**", "*"), recursive=True)):
        if os.path.isfile(path) and path not in linted and "__pycache__" not in path and not built_copy(path):
            out.append(path)
    return out


def lint(files=None, strict=False, profile=None, reg=None, directory=None):
    directory = directory or prompts_dir()
    profile = profile if profile is not None else load_yaml(profile_path())
    reg = reg if reg is not None else registry(os.path.join(directory, "placeholders.yaml"))
    rules = leak_rules(profile)
    issues = []
    for path in files or live_files(directory):
        issues += lint_text(read(path), os.path.relpath(path), reg, rules, strict=strict)
    if not files:
        for path in other_files(directory):
            in_tests = os.sep + "tests" + os.sep in path
            issues += lint_text(read(path), os.path.relpath(path), reg, rules, leak_only=True, generic=not in_tests)
    return issues


def environment(profile, env=None, base=None):
    base = base or team_root()
    rel = get_path(profile, "db.environments_file")
    if not rel:
        return {}
    data = load_yaml(os.path.join(base, rel))
    name = env or os.environ.get("SNOWFLAKE_ENV") or get_path(profile, "db.kb_environment") or data.get("default")
    envs = data.get("environments") or {}
    if name not in envs:
        raise ValueError("unknown environment %r; known: %s" % (name, ", ".join(sorted(envs))))
    values = dict(envs[name])
    values.setdefault("schema", data.get("schema"))
    values["name"] = name
    return values


def resolve(source, profile, env_values, today, args=None):
    kind, _, key = source.partition(":")
    if kind == "profile":
        return get_path(profile, key)
    if kind == "env":
        return env_values.get(key)
    if kind == "runtime" and key == "date":
        return today
    if kind == "runtime" and key.startswith("arg."):
        return (args or {}).get(key[4:])
    raise ValueError("unknown placeholder source '%s'" % source)


def format_value(value, kind):
    empty = value in (None, "") or value == []
    if kind == "sql_list":
        if empty:
            return "NULL"
        vals = value if isinstance(value, list) else [value]
        return ", ".join("'%s'" % str(v).replace("'", "''") for v in vals)
    if kind == "sql_endswith_any":
        if empty:
            return "FALSE"
        return "(" + " OR ".join("ENDSWITH(COLUMN_NAME, '%s')" % str(v).replace("'", "''") for v in value) + ")"
    if empty:
        return "(not set)"
    if kind == "bullets":
        vals = value if isinstance(value, list) else [value]
        return "\n".join("- `%s`" % v for v in vals)
    return str(value)


def with_env_docs_dir(profile, declared, reg, env=None, base=None):
    """An environment may set `docs_dir`: its DB documents then live in that sub-folder of paths.db_docs."""
    uses = any("profile:paths.db_docs" in (reg.get(n) or {}).get("sources", []) for n in declared)
    root = get_path(profile, "paths.db_docs")
    if not uses or not root or not get_path(profile, "db.environments_file"):
        return profile
    sub = (environment(profile, env, base).get("docs_dir") or ".").strip("/")
    if sub in ("", "."):
        return profile
    paths = dict(profile.get("paths") or {})
    paths["db_docs"] = root.rstrip("/") + "/" + sub
    return dict(profile, paths=paths)


def render(text, profile, reg, env=None, today=None, base=None, args=None):
    meta, _ = split(text)
    declared = (meta or {}).get("placeholders") or []
    profile = with_env_docs_dir(profile, declared, reg, env, base)
    env_values = environment(profile, env, base) if any(
        s.startswith("env:") for n in declared for s in (reg.get(n) or {}).get("sources", [])) else {}
    today = today or datetime.date.today().isoformat()
    values, missing = {}, []
    for name in declared:
        entry = reg.get(name)
        if not entry:
            missing.append(name)
            continue
        parts = []
        for source in entry.get("sources", []):
            v = resolve(source, profile, env_values, today, args)
            if isinstance(v, list):
                parts.extend(v)
            elif v not in (None, ""):
                parts.append(v)
        kind = entry.get("type", "text")
        if not parts and entry.get("required"):
            missing.append(name)
            continue
        single = kind == "text" and len(parts) == 1
        values[name] = format_value(parts[0] if single else parts, kind)
    if missing:
        raise ValueError("no value for: " + ", ".join("{{%s}}" % m for m in missing))
    out = PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    left = sorted(set(PLACEHOLDER.findall(out)))
    if left:
        raise ValueError("undeclared placeholders left in the prompt: " + ", ".join("{{%s}}" % m for m in left))
    return out


STAGE_NOTE = """> **Staging run.** Write every output of this prompt under `{stage}`, not the live
> knowledge base under `{live}`. When an input this prompt names under `{stage}` does not
> exist yet, read the same file from `{live}` instead. Do not change any file under `{live}`.
> The staged files are compared with the live ones (`kb_compare.py`) and replace them only
> after the owner approves.

"""


def stage_profile(profile, stage):
    """Copy of the profile with every knowledge-base folder moved under the staging folder."""
    paths = dict(profile.get("paths") or {})
    root = (paths.get("kb_root") or "").rstrip("/")
    if not root:
        raise ValueError("--stage needs paths.kb_root in the profile")
    stage = stage.rstrip("/")
    for key, value in list(paths.items()):
        if isinstance(value, str) and (value == root or value.startswith(root + "/")):
            paths[key] = stage + value[len(root):]
    staged = dict(profile)
    staged["paths"] = paths
    return staged, root


def render_file(path, profile, reg, env=None, args=None, stage=None):
    text = read(path)
    if not stage:
        return render(text, profile, reg, env=env, args=args)
    staged, live = stage_profile(profile, stage)
    out = render(text, staged, reg, env=env, args=args)
    meta = FRONTMATTER.match(out)
    at = meta.end() if meta else 0
    return out[:at] + "\n" + STAGE_NOTE.format(stage=stage.rstrip("/"), live=live) + out[at:].lstrip("\n")


def outputs(rendered):
    meta, _ = split(rendered)
    return [str(o) for o in (meta or {}).get("outputs") or []]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_lint = sub.add_parser("lint")
    p_lint.add_argument("files", nargs="*")
    p_lint.add_argument("--strict", action="store_true", help="also fail prompts not yet marked shareable")
    p_render = sub.add_parser("render")
    p_render.add_argument("file")
    p_render.add_argument("--env")
    p_render.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                          help="value for a runtime:arg placeholder, e.g. --set MODULE_NAME=api")
    p_render.add_argument("--stage", metavar="DIR",
                          help="write outputs under DIR instead of the knowledge base (side-by-side rebuild)")
    p_render.add_argument("--out", metavar="FILE", help="write the rendered prompt to FILE")
    p_out = sub.add_parser("outputs")
    p_out.add_argument("file")
    p_out.add_argument("--env")
    p_out.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    p_out.add_argument("--stage", metavar="DIR")
    sub.add_parser("status")
    args = ap.parse_args(argv)

    if args.cmd == "lint":
        issues = lint(args.files or None, strict=args.strict)
        for f, line, level, msg in issues:
            print("%s:%d: %s: %s" % (f, line, level, msg))
        errors = sum(1 for i in issues if i[2] == "error")
        print("prompt lint: %d error(s), %d warning(s)" % (errors, len(issues) - errors))
        return 1 if errors else 0
    if args.cmd in ("render", "outputs"):
        path = args.file if os.path.exists(args.file) else os.path.join(prompts_dir(), args.file)
        try:
            given = dict(item.split("=", 1) for item in args.set if "=" in item)
            out = render_file(path, load_yaml(profile_path()), registry(), env=args.env, args=given,
                              stage=args.stage)
        except ValueError as exc:
            print("%s failed: %s" % (args.cmd, exc), file=sys.stderr)
            return 2
        if args.cmd == "outputs":
            print("\n".join(outputs(out)))
        elif getattr(args, "out", None):
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(out)
            print("wrote %s" % args.out)
        else:
            print(out)
        return 0
    files = live_files()
    shared = [f for f in files if (split(read(f))[0] or {}).get("shareable")]
    print("shared: %d of %d live prompts" % (len(shared), len(files)))
    for f in shared:
        print("  " + os.path.relpath(f, prompts_dir()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
