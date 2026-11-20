#!/usr/bin/env python3
"""Where a requirement's session state lives, and how it travels between Devin sessions.

Every stage skill, the gate library and the dashboard ask this module for the directory of a
REQ instead of building the path themselves. The answer depends on `session_state.storage_strategy`
in `.devin/config.json`:

  repo   sdlc/framework/context/session/{OWNER}/{REQ_ID}/   (committed with the code)
  local  $SDLC_SESSION_HOME/{OWNER}/{REQ_ID}/  (default ~/.sdlc/sessions — outside the repository)
  auto   local when it already holds the REQ, otherwise repo; new sessions go local

A Devin Cloud machine does not keep files between sessions, so `local` state is durable only
when it is pushed somewhere. The only durable store available today is Jira: `push` attaches
`sdlc-session-{REQ_ID}.json` (every file in the session directory, base64) to the story recorded
as `jira_key` in approvals.yaml, and `pull` restores it. Nothing is written to Jira without
`--live`; the default is a dry run that prints the request.

  python3 session_store.py owner
  python3 session_store.py path  REQ-001            # print the directory (creating it if asked)
  python3 session_store.py list                     # every REQ visible to this owner
  python3 session_store.py push  REQ-001 [--live]   # snapshot to the Jira story attachment
  python3 session_store.py pull  REQ-001 [--live]   # restore from the Jira story attachment
  python3 session_store.py migrate REQ-001          # copy a repo-stored session into the local store
"""
import argparse
import base64
import datetime
import glob
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
CONFIG_PATH = os.path.join(ROOT, ".devin", "config.json")
REPO_SESSION_ROOT = os.path.join(ROOT, "sdlc", "framework", "context", "session")
DEFAULT_LOCAL_HOME = os.path.join(os.path.expanduser("~"), ".sdlc", "sessions")
JIRA = (os.environ.get("SDLC_SANDBOX_URL") or "https://jira.acme.example").rstrip("/") + "/rest"
ATTACHMENT_PREFIX = "sdlc-session-"
REQ_RE = re.compile(r"^(REQ|TEST)-[A-Z0-9-]+$")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config():
    """config.json, plus config.cloud.json when running in Devin Cloud, plus config.local.json (runtime_env)."""
    import runtime_env
    return runtime_env.effective_config(root=ROOT)


def strategy():
    value = os.environ.get("SDLC_SESSION_STRATEGY") or (
        load_config().get("session_state", {}).get("storage_strategy", "auto")
    )
    return "repo" if value == "repository" else value  # config.cloud.json says "repository"


def local_home():
    configured = load_config().get("session_state", {}).get("local_home")
    return os.environ.get("SDLC_SESSION_HOME") or (os.path.expanduser(configured) if configured else DEFAULT_LOCAL_HOME)


def slug(email):
    local = (email or "").split("@")[0].lower()
    return re.sub(r"-+$", "", re.sub(r"^-+", "", re.sub(r"[^a-z0-9]+", "-", local)))


def resolve_owner():
    """Owner slug per .devin/rules/session-isolation.md. SDLC_OWNER wins, then git email."""
    if os.environ.get("SDLC_OWNER"):
        owner = os.environ["SDLC_OWNER"].strip()
        return slug(owner) if "@" in owner else owner
    try:
        email = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True, cwd=ROOT, check=False
        ).stdout.strip()
    except OSError:
        email = ""
    return slug(email) if "@" in email else ""


def candidate_dirs(req_id, owner=None):
    owner = owner or resolve_owner()
    dirs = []
    if owner:
        dirs.append(("local", os.path.join(local_home(), owner, req_id)))
        dirs.append(("repo", os.path.join(REPO_SESSION_ROOT, owner, req_id)))
    dirs.append(("legacy", os.path.join(REPO_SESSION_ROOT, req_id)))
    return dirs


def session_dir(req_id, owner=None, create=False):
    """The directory for REQ_ID under the configured strategy. Existing state is never moved."""
    if not REQ_RE.match(req_id):
        raise ValueError("not a requirement id: %r" % req_id)
    owner = owner or resolve_owner()
    if not owner:
        raise RuntimeError("cannot resolve session owner: set git user.email or SDLC_OWNER")
    mode = strategy()
    ordered = candidate_dirs(req_id, owner)
    if mode == "repo":
        ordered = [d for d in ordered if d[0] != "local"]
    for kind, path in ordered:
        if os.path.isdir(path):
            return path
    kind = "repo" if mode == "repo" else "local"
    path = dict(candidate_dirs(req_id, owner))[kind]
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def list_sessions(owner=None):
    owner = owner or resolve_owner()
    found = {}
    if owner:
        for base in (os.path.join(local_home(), owner), os.path.join(REPO_SESSION_ROOT, owner)):
            for p in sorted(glob.glob(os.path.join(base, "REQ-*"))):
                found.setdefault(os.path.basename(p), p)
    for p in sorted(glob.glob(os.path.join(REPO_SESSION_ROOT, "REQ-*"))):
        found.setdefault(os.path.basename(p), p)
    return found


def all_session_records():
    """Every approvals.yaml visible from this machine: (owner, req_id, path).

    Covers the local home for all owners, the repo owner-scoped dirs, and legacy unscoped dirs
    (owner 'legacy'). Used by the dashboard and the timeout sweep, which look across owners."""
    out = []
    for base in (local_home(), REPO_SESSION_ROOT):
        for path in glob.glob(os.path.join(base, "*", "REQ-*", "approvals.yaml")):
            out.append((os.path.basename(os.path.dirname(os.path.dirname(path))),
                        os.path.basename(os.path.dirname(path)), path))
    for path in glob.glob(os.path.join(REPO_SESSION_ROOT, "REQ-*", "approvals.yaml")):
        out.append(("legacy", os.path.basename(os.path.dirname(path)), path))
    return sorted(set(out))


def approvals_path(req_id, owner=None):
    return os.path.join(session_dir(req_id, owner), "approvals.yaml")


def load_yaml_file(path):
    if not (yaml and os.path.exists(path)):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def write_yaml_file(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    return path


def read_approvals(req_id, owner=None):
    return load_yaml_file(approvals_path(req_id, owner))


def write_approvals(req_id, data, owner=None):
    return write_yaml_file(os.path.join(session_dir(req_id, owner, create=True), "approvals.yaml"), data)


# ---- Jira attachment transport -------------------------------------------------------------

def _ctx():
    return ssl._create_unverified_context()


class JiraAttachments:
    """Just enough of the Jira attachment API, bearer auth, one /myself check, no 4xx retries."""

    def __init__(self, live=False):
        self.live = live
        self.token = os.environ.get("ACME_JIRA_TOKEN")
        self.validated = False
        if live and not self.token:
            raise RuntimeError("ACME_JIRA_TOKEN is not set — drop --live or configure Jira auth.")

    def _open(self, request):
        try:
            with urllib.request.urlopen(request, context=_ctx(), timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(
                    "Jira returned %d. The service account token is invalid or locked; not retrying." % exc.code
                ) from exc
            raise RuntimeError("Jira returned %d: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:300])) from exc

    def _headers(self, extra=None):
        h = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        h.update(extra or {})
        return h

    def _validate(self):
        if not self.validated:
            self._open(urllib.request.Request(JIRA + "/api/2/myself", headers=self._headers()))
            self.validated = True

    def list(self, key):
        if not self.live:
            print("DRY-RUN GET %s/api/2/issue/%s?fields=attachment" % (JIRA, key))
            return []
        self._validate()
        raw = self._open(urllib.request.Request(
            JIRA + "/api/2/issue/%s?fields=attachment" % key, headers=self._headers()))
        return json.loads(raw).get("fields", {}).get("attachment", []) or []

    def upload(self, key, filename, payload):
        boundary = uuid.uuid4().hex
        body = io.BytesIO()
        body.write(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                    "Content-Type: application/json\r\n\r\n" % (boundary, filename)).encode())
        body.write(payload)
        body.write(("\r\n--%s--\r\n" % boundary).encode())
        if not self.live:
            print("DRY-RUN POST %s/api/2/issue/%s/attachments  %s (%d bytes)" % (JIRA, key, filename, len(payload)))
            return {}
        self._validate()
        request = urllib.request.Request(
            JIRA + "/api/2/issue/%s/attachments" % key, data=body.getvalue(), method="POST",
            headers=self._headers({"X-Atlassian-Token": "no-check",
                                   "Content-Type": "multipart/form-data; boundary=" + boundary}))
        return json.loads(self._open(request) or b"[]")

    def delete(self, attachment_id):
        if not self.live:
            print("DRY-RUN DELETE %s/api/2/attachment/%s" % (JIRA, attachment_id))
            return
        self._validate()
        self._open(urllib.request.Request(JIRA + "/api/2/attachment/%s" % attachment_id,
                                          method="DELETE", headers=self._headers()))

    def download(self, url):
        if not self.live:
            print("DRY-RUN GET %s" % url)
            return b""
        self._validate()
        return self._open(urllib.request.Request(url, headers=self._headers()))


SCRUB_KEYS = {"token", "secret", "password", "passwd", "api_key", "apikey", "authorization", "bearer",
              "body", "raw_message", "message_body", "transcript", "chat", "messages"}
SCRUB_FILES = ("transcript", "messages", "chat", ".log", ".env")


def scrub(value):
    """Drop secret-ish keys and raw message bodies from a mapping before it leaves the machine."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if str(k).lower() not in SCRUB_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def snapshot(req_id, owner=None):
    """Every regular file in the session directory, base64, plus who/when.

    YAML/JSON files are scrubbed of secret-looking keys and raw message bodies; transcript, chat,
    log and .env files are left out altogether. Snapshots go to Jira, which is not a secret store."""
    base = session_dir(req_id, owner)
    files = {}
    for dirpath, _, names in os.walk(base):
        for name in sorted(names):
            if any(tag in name.lower() for tag in SCRUB_FILES):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            if name.endswith((".yaml", ".yml")):
                payload = yaml.safe_dump(scrub(load_yaml_file(full)), sort_keys=False).encode("utf-8")
            elif name.endswith(".json"):
                with open(full, encoding="utf-8") as fh:
                    payload = json.dumps(scrub(json.load(fh)), indent=1).encode("utf-8")
            else:
                with open(full, "rb") as fh:
                    payload = fh.read()
            files[rel] = base64.b64encode(payload).decode("ascii")
    return {"requirement_id": req_id, "owner": owner or resolve_owner(), "taken_at": now(),
            "source_dir": base, "files": files}


def restore(req_id, snap, owner=None):
    """Write a snapshot back. Names use / (a \\ from a Windows snapshot counts as /). Every name must
    stay inside the session directory; an absolute path, a drive or `..` stops the restore before
    anything is written."""
    base = session_dir(req_id, owner, create=True)
    root = os.path.realpath(base)
    targets = {}
    for rel in snap.get("files", {}):
        name = rel.replace("\\", "/")
        target = os.path.realpath(os.path.join(root, *name.split("/")))
        if os.path.isabs(name) or name[1:2] == ":" or os.path.commonpath([root, target]) != root \
                or target == root:
            raise ValueError("snapshot entry %r is outside the session directory; nothing restored" % rel)
        targets[rel] = target
    for rel, b64 in snap.get("files", {}).items():
        target = targets[rel]
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(base64.b64decode(b64))
    return base


def jira_key_for(req_id, explicit=None, owner=None):
    if explicit:
        return explicit
    data = read_approvals(req_id, owner)
    key = data.get("jira_key")
    if not key:
        for phase in (data.get("phases") or {}).values():
            if isinstance(phase, dict) and phase.get("jira_key"):
                key = phase["jira_key"]
                break
    if not key:
        raise RuntimeError("no jira_key recorded for %s — pass --key ACME-nnnn" % req_id)
    return key


def do_push(args):
    key = jira_key_for(args.req_id, key_explicit(args))
    snap = snapshot(args.req_id)
    payload = json.dumps(snap, indent=1).encode("utf-8")
    client = JiraAttachments(live=args.live)
    filename = ATTACHMENT_PREFIX + args.req_id + ".json"
    for existing in client.list(key):
        if existing.get("filename") == filename:
            client.delete(existing["id"])
    client.upload(key, filename, payload)
    print("pushed %s (%d files) to %s as %s%s" % (
        args.req_id, len(snap["files"]), key, filename, "" if args.live else " [dry run]"))


def do_pull(args):
    key = jira_key_for(args.req_id, key_explicit(args))
    client = JiraAttachments(live=args.live)
    filename = ATTACHMENT_PREFIX + args.req_id + ".json"
    match = [a for a in client.list(key) if a.get("filename") == filename]
    if not args.live:
        return
    if not match:
        raise SystemExit("no %s attached to %s" % (filename, key))
    newest = sorted(match, key=lambda a: a.get("created", ""))[-1]
    snap = json.loads(client.download(newest["content"]))
    base = restore(args.req_id, snap)
    print("restored %s (%d files, taken %s) into %s" % (args.req_id, len(snap["files"]), snap["taken_at"], base))


def key_explicit(args):
    return getattr(args, "key", None)


def do_migrate(args):
    owner = resolve_owner()
    src = None
    for kind, path in candidate_dirs(args.req_id, owner):
        if kind != "local" and os.path.isdir(path):
            src = path
            break
    if not src:
        raise SystemExit("no repo-stored session for %s" % args.req_id)
    dst = os.path.join(local_home(), owner, args.req_id)
    if os.path.exists(dst):
        raise SystemExit("%s already exists; refusing to overwrite" % dst)
    shutil.copytree(src, dst)
    print("copied %s -> %s (the repo copy is untouched; remove it in a PR when you are ready)" % (src, dst))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("owner")
    p = sub.add_parser("path"); p.add_argument("req_id"); p.add_argument("--create", action="store_true")
    sub.add_parser("list")
    for name in ("push", "pull"):
        p = sub.add_parser(name); p.add_argument("req_id"); p.add_argument("--key")
        p.add_argument("--live", action="store_true", help="actually talk to Jira (default: dry run)")
    p = sub.add_parser("migrate"); p.add_argument("req_id")
    args = parser.parse_args(argv)

    if args.command == "owner":
        print(resolve_owner() or "(unresolved)")
    elif args.command == "path":
        print(session_dir(args.req_id, create=args.create))
    elif args.command == "list":
        print("strategy: %s   local home: %s" % (strategy(), local_home()))
        for req, path in list_sessions().items():
            print("%-24s %s" % (req, path))
    elif args.command == "push":
        do_push(args)
    elif args.command == "pull":
        do_pull(args)
    elif args.command == "migrate":
        do_migrate(args)


if __name__ == "__main__":
    main()
