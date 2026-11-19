#!/usr/bin/env python3
"""Read one field from a hook's event data, for the guards in .devin/hooks/.

    hook_input.py paths     files the tool call will change, one per line
    hook_input.py content   the text the tool call will write
    hook_input.py prompt    the user's message (UserPromptSubmit)
    hook_input.py command   the shell command a shell tool (exec, Bash) will run

Devin passes the event as JSON on stdin ({"tool_name": ..., "tool_input": {...}} or
{"prompt": ...}); Claude Code uses the same shape. With nothing on stdin it falls back to
DEVIN_TOOL_FILE_PATH, DEVIN_TOOL_CONTENT, DEVIN_USER_PROMPT and
DEVIN_TOOL_COMMAND.

Exit 0 with the field on stdout, 3 when the event does not carry it, 1 on unreadable input.
"""
import json
import os
import re
import sys

PATH_KEYS = ("file_path", "path", "filePath", "notebook_path", "target_file")
TEXT_KEYS = ("content", "contents", "new_string", "new_str", "new_source", "text")
PATCH_KEYS = ("patch", "input", "patch_text")
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$", re.M)


def _tool_input(event):
    value = event.get("tool_input") or {}
    if isinstance(value, str):
        return {"patch": value}
    return value if isinstance(value, dict) else {}


def _patch(tool_input):
    for key in PATCH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and "*** " in value:
            return value
    return None


def paths(event):
    tool_input = _tool_input(event)
    found = [tool_input[k] for k in PATH_KEYS if isinstance(tool_input.get(k), str)]
    patch = _patch(tool_input)
    if patch:
        found += [a or b for a, b in PATCH_FILE_RE.findall(patch)]
    found = [p.strip() for p in found if p.strip()]
    return "\n".join(found) if found else None


def content(event):
    tool_input = _tool_input(event)
    parts = [tool_input[k] for k in TEXT_KEYS if isinstance(tool_input.get(k), str)]
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            parts += [edit[k] for k in TEXT_KEYS if isinstance(edit.get(k), str)]
    patch = _patch(tool_input)
    if patch:
        parts.append("\n".join(line[1:] for line in patch.splitlines()
                               if line.startswith("+") and not line.startswith("+++")))
    return "\n".join(parts) if parts else None


def command(event):
    tool_input = _tool_input(event)
    for key in ("command", "cmd"):
        if isinstance(tool_input.get(key), str):
            return tool_input[key]
    return None


def prompt(event):
    value = event.get("prompt")
    return value if isinstance(value, str) else None


FALLBACK = {"paths": "DEVIN_TOOL_FILE_PATH", "content": "DEVIN_TOOL_CONTENT", "prompt": "DEVIN_USER_PROMPT",
            "command": "DEVIN_TOOL_COMMAND"}
FIELDS = {"paths": paths, "content": content, "prompt": prompt, "command": command}


def main(argv):
    if len(argv) != 2 or argv[1] not in FIELDS:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    field = argv[1]
    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    if raw.strip():
        try:
            event = json.loads(raw)
        except ValueError as exc:
            print("hook event is not JSON: %s" % exc, file=sys.stderr)
            return 1
        value = FIELDS[field](event if isinstance(event, dict) else {})
    else:
        value = os.environ.get(FALLBACK[field])
        if field == "paths" and value == "":
            value = None
    if value is None:
        return 3
    sys.stdout.write(value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
