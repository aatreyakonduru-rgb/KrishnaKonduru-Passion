#!/usr/bin/env python3
"""Pass 1 of document ingest: collect everything a person hands over and turn it into text in a scratch folder.

    python3 doc_intake.py <kb> <scratch> --by "<name>" <source>...

A source is a file, a folder (read recursively), a .zip (opened and read recursively), a Confluence page link
(the page, its child pages and their attachments) or a SharePoint / OneDrive link (a file or a folder, recursively).
Everything is read only. Nothing is written to the repo; <scratch> must be outside it (for example
/tmp/metis-docs/<run>).

Tokens come from the environment variables named in <kb>/.metis/kb-profile.yaml:
    sources.confluence: base_url, secret, auth (bearer | basic; basic needs "email:token"), verify_tls
    sources.sharepoint: secret (a Microsoft Graph bearer token), verify_tls
A token is never printed or written. On 401/403 that source stops and is listed as not read; it is not retried.

Writes <scratch>/raw/ (the files as received, or Confluence pages as text), <scratch>/<doc id>.txt and manifest.yaml
(through read_docs.py, so every line has a place such as p3, slide4, Sheet1!B7, para12, line40) and
<scratch>/INTAKE.yaml (one entry per source and per file: read or not read, and why).
"""
import argparse
import base64
import datetime
import email
import email.policy
import html
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_docs  # noqa: E402

MAX_FILES = 300
MAX_DEPTH = 6
MAX_BYTES = 50 * 1024 * 1024
LEGACY = {".doc": "docx", ".rtf": "docx", ".odt": "docx", ".xls": "xlsx", ".ods": "xlsx", ".ppt": "pptx", ".odp": "pptx"}
GRAPH = "https://graph.microsoft.com/v1.0"
CONF_EXPAND = "body.storage,version,ancestors,space,restrictions.read.restrictions.user,restrictions.read.restrictions.group"
META_KEYS = ("version", "access", "restricted_to", "changed_from")


class Denied(Exception):
    """401/403: the token is invalid or has no access. Not retried."""


class Missing(Exception):
    """404: the page or file is not there (or not visible to this token)."""


class Http:
    def __init__(self, headers=None, verify=True):
        self.headers = headers or {}
        self.ctx = None if verify else ssl._create_unverified_context()

    def _open(self, url, auth=True):
        h = dict(self.headers) if auth else {}
        last = None
        for _ in range(3):
            try:
                return urllib.request.urlopen(urllib.request.Request(url, headers=h), context=self.ctx, timeout=120)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise Denied("HTTP %d: the token is invalid or has no access" % e.code)
                if e.code == 404:
                    raise Missing("HTTP 404: not found, or not visible to this token")
                if e.code < 500:
                    raise
                last = e
            except urllib.error.URLError as e:
                last = e
        raise RuntimeError("could not reach %s (%s)" % (urllib.parse.urlsplit(url).netloc, last))

    def json(self, url):
        with self._open(url) as r:
            return json.load(r)

    def bytes(self, url, auth=True, limit=MAX_BYTES):
        with self._open(url, auth) as r:
            data = r.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError("file is over %d MB; not downloaded" % (limit // 1024 // 1024))
        return data


def load_yaml(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def safe(name, keep_dot=True):
    name = re.sub(r"[^\w.\- ()]+", "_", str(name)).strip(" ._")
    return (name or "document")[:120]


def host(url):
    return urllib.parse.urlsplit(url).netloc.lower()


def link_kind(url, profile):
    """confluence | sharepoint | None."""
    src = (profile.get("sources") or {})
    h, path = host(url), urllib.parse.urlsplit(url).path
    cb = (src.get("confluence") or {}).get("base_url") or ""
    sb = (src.get("sharepoint") or {}).get("base_url") or ""
    if cb and h == host(cb):
        return "confluence"
    if sb and h == host(sb):
        return "sharepoint"
    if h.endswith((".sharepoint.com", "-my.sharepoint.com", "1drv.ms", "onedrive.live.com")):
        return "sharepoint"
    if re.search(r"/(display|pages|spaces)/|pageId=|/wiki/", url) or "confluence" in h:
        return "confluence"
    return None


class Intake:
    def __init__(self, kb, scratch, by, profile=None, http_factory=None, max_files=MAX_FILES):
        self.kb, self.scratch, self.by = kb, scratch, by
        self.profile = profile if profile is not None else load_yaml(os.path.join(kb, ".metis", "kb-profile.yaml"))
        self.raw = os.path.join(scratch, "raw")
        self.http_factory = http_factory or self._http
        self.max_files = max_files
        self.files, self.origins, self.log = [], {}, []
        self.meta = {}      # queued file -> version and access facts about the document
        self.known = {}     # origin -> {id, version} for documents already in the KB register
        self.sources = []
        os.makedirs(self.raw, exist_ok=True)

    # ---- bookkeeping -------------------------------------------------------------------------
    def note(self, source, item, status, reason=None, **extra):
        e = {"source": source, "item": item, "status": status}
        if reason:
            e["reason"] = reason
        e.update({k: v for k, v in extra.items() if v})
        self.log.append(e)
        print("%s: %s%s" % (item, status, " - " + reason if reason else ""))

    def room(self):
        return len(self.files) < self.max_files

    def store(self, name, data, origin, source, **extra):
        """Save received bytes under raw/, convert legacy types, and queue the file for reading."""
        if not self.room():
            self.note(source, name, "not read", "over the limit of %d files per run" % self.max_files)
            return
        base = safe(name)
        path, n = os.path.join(self.raw, base), 1
        while os.path.exists(path):
            n += 1
            stem, ext = os.path.splitext(base)
            path = os.path.join(self.raw, "%s-%d%s" % (stem, n, ext))
        with open(path, "wb") as fh:
            fh.write(data)
        self.add_path(path, origin, source, name, **extra)

    def add_path(self, path, origin, source, shown, **extra):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".zip":
            return self.open_zip(path, origin, source)
        if ext == ".eml":
            path = self.eml_to_text(path)
        elif ext in LEGACY:
            conv, why = self.convert(path, LEGACY[ext])
            if not conv:
                self.note(source, shown, "not read", why, **extra)
                return
            path = conv
        self.files.append(path)
        self.origins[path] = origin
        facts = {k: v for k, v in extra.items() if k in META_KEYS and v not in (None, "", [])}
        if facts:
            self.meta[path] = facts
        self.note(source, shown, "queued", **extra)

    def eml_to_text(self, path):
        with open(path, "rb") as fh:
            msg = email.message_from_binary_file(fh, policy=email.policy.default)
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""
        if body is not None and body.get_content_type() == "text/html":
            text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
        head = "From: %s\nTo: %s\nDate: %s\nSubject: %s\n\n" % (msg["from"], msg["to"], msg["date"], msg["subject"])
        out = path + ".txt"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(head + text)
        return out

    def convert(self, path, to):
        exe = shutil.which("soffice") or shutil.which("libreoffice")
        if not exe:
            return None, "old %s format and no LibreOffice on this machine to convert it (save it as .%s and upload again)" % (
                os.path.splitext(path)[1], to)
        out = os.path.join(self.raw, "converted")
        os.makedirs(out, exist_ok=True)
        try:
            subprocess.run([exe, "--headless", "--convert-to", to, "--outdir", out, path],
                           capture_output=True, text=True, timeout=180, check=True)
        except (OSError, subprocess.SubprocessError) as e:
            return None, "conversion to .%s failed (%s)" % (to, str(e)[:80])
        conv = os.path.join(out, os.path.splitext(os.path.basename(path))[0] + "." + to)
        return (conv, None) if os.path.isfile(conv) else (None, "conversion to .%s produced no file" % to)

    def open_zip(self, path, origin, source, depth=0):
        out = os.path.join(self.raw, "zip-" + safe(os.path.splitext(os.path.basename(path))[0]))
        try:
            with zipfile.ZipFile(path) as z:
                total = 0
                for info in z.infolist():
                    if info.is_dir() or info.filename.startswith("__MACOSX"):
                        continue
                    total += info.file_size
                    if total > 4 * MAX_BYTES:
                        self.note(source, os.path.basename(path), "not read", "zip is larger than allowed when opened")
                        return
                    dest = os.path.normpath(os.path.join(out, info.filename))
                    if not dest.startswith(os.path.normpath(out) + os.sep):
                        continue  # path traversal
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(info) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    inner = "%s!%s" % (origin, info.filename)
                    if os.path.splitext(dest)[1].lower() == ".zip" and depth < 2:
                        self.open_zip(dest, inner, source, depth + 1)
                    elif self.room():
                        self.add_path(dest, inner, source, info.filename)
        except zipfile.BadZipFile:
            self.note(source, os.path.basename(path), "not read", "not a valid zip file")

    # ---- local files and folders -------------------------------------------------------------
    def local(self, src):
        src = os.path.abspath(src)
        if os.path.isdir(src):
            for d, dirs, fs in os.walk(src):
                dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in ("node_modules", "__pycache__"))
                for f in sorted(fs):
                    if f.startswith((".", "~$")):
                        continue
                    p = os.path.join(d, f)
                    rel = os.path.relpath(p, src).replace(os.sep, "/")
                    if not self.room():
                        self.note(src, rel, "not read", "over the limit of %d files per run" % self.max_files)
                        continue
                    flat = os.path.join(self.raw, safe(rel.replace("/", "__")))
                    shutil.copyfile(p, flat)
                    self.add_path(flat, "%s/%s" % (os.path.basename(src), rel), src, rel)
        elif os.path.isfile(src):
            flat = os.path.join(self.raw, safe(os.path.basename(src)))
            if os.path.exists(flat):
                flat = os.path.join(self.raw, safe("%d-%s" % (len(self.files), os.path.basename(src))))
            shutil.copyfile(src, flat)
            self.add_path(flat, os.path.basename(src), src, os.path.basename(src))
        else:
            self.note(src, src, "not read", "no such file or folder")

    # ---- Confluence --------------------------------------------------------------------------
    def _http(self, kind):
        cfg = (self.profile.get("sources") or {}).get(kind) or {}
        name = cfg.get("secret")
        token = os.environ.get(name) if name else None
        if not token:
            raise Denied("%s secret %s is not set in this session (sources.%s.secret in kb-profile.yaml)" % (
                kind, name or "(none named)", kind))
        if kind == "confluence" and cfg.get("auth") == "basic":
            auth = "Basic " + base64.b64encode(token.encode()).decode()
        else:
            auth = "Bearer " + token
        return Http({"Authorization": auth, "Accept": "application/json"}, cfg.get("verify_tls", True) is not False)

    @staticmethod
    def conf_ref(url):
        sp = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qs(sp.query)
        if q.get("pageId"):
            return ("id", q["pageId"][0])
        m = re.search(r"/pages/(\d+)", sp.path)
        if m:
            return ("id", m.group(1))
        m = re.search(r"/display/([^/]+)/([^/?#]+)", sp.path)
        if m:
            return ("title", urllib.parse.unquote_plus(m.group(1)), urllib.parse.unquote_plus(m.group(2)))
        return None

    @staticmethod
    def conf_base(url):
        sp = urllib.parse.urlsplit(url)
        return "%s://%s%s" % (sp.scheme, sp.netloc, "/wiki" if sp.path.startswith("/wiki") else "")

    @staticmethod
    def storage_text(s):
        s = re.sub(r"<ac:structured-macro[^>]*ac:name=\"code\"[^>]*>", "\n", s)
        s = re.sub(r"<(br|/p|/tr|/h\d|/li|/div)[^>]*>", "\n", s)
        s = re.sub(r"<(td|th)[^>]*>", " | ", s)
        s = html.unescape(re.sub(r"<[^>]+>", "", s))
        return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()

    def confluence(self, url):
        ref = self.conf_ref(url)
        if not ref:
            return self.note(url, url, "not read", "not a page link (open the page itself and copy its address; "
                                                   "space home links are not supported)")
        http = self.http_factory("confluence")
        cfg = (self.profile.get("sources") or {}).get("confluence") or {}
        base = (cfg.get("base_url") or self.conf_base(url)).rstrip("/")
        exp = CONF_EXPAND
        if ref[0] == "id":
            page = http.json("%s/rest/api/content/%s?expand=%s" % (base, ref[1], exp))
        else:
            r = http.json("%s/rest/api/content?spaceKey=%s&title=%s&expand=%s" % (
                base, urllib.parse.quote(ref[1]), urllib.parse.quote(ref[2]), exp))
            if not r.get("results"):
                raise Missing("no page titled '%s' in space %s" % (ref[2], ref[1]))
            page = r["results"][0]
        self.conf_page(http, base, page, url, 0, set())

    def conf_page(self, http, base, page, root, depth, seen):
        pid = str(page["id"])
        if pid in seen:
            return
        seen.add(pid)
        if not self.room():
            return self.note(root, page.get("title", pid), "not read", "over the limit of %d files per run" % self.max_files)
        title, ver = page.get("title", pid), (page.get("version") or {}).get("number")
        web = base + ((page.get("_links") or {}).get("webui") or "/pages/viewpage.action?pageId=" + pid)
        trail = " > ".join(a.get("title", "") for a in page.get("ancestors") or [])
        access = self.conf_access(page)
        prev = self.known.get(web)
        if prev and prev.get("version") is not None and str(prev["version"]) == str(ver):
            self.note(root, title, "unchanged", "version %s is already in the KB as %s" % (ver, prev["id"]))
        else:
            text = self.storage_text(((page.get("body") or {}).get("storage") or {}).get("value", ""))
            head = "# %s\npage_id: %s\nversion: %s\nspace: %s\nupdated: %s\npath: %s\nurl: %s\n\n" % (
                title, pid, ver, (page.get("space") or {}).get("key", ""), (page.get("version") or {}).get("when", ""), trail, web)
            self.store("%s (confluence %s).txt" % (title, pid), (head + text + "\n").encode("utf-8"), web, root,
                       version=ver, folder=trail, changed_from=(prev or {}).get("id"), **access)
            self.conf_attachments(http, base, pid, web, root, access)
        try:
            if depth < MAX_DEPTH:
                start = 0
                while True:
                    kids = http.json("%s/rest/api/content/%s/child/page?limit=50&start=%d&expand=%s" % (
                        base, pid, start, CONF_EXPAND))
                    for k in kids.get("results") or []:
                        self.conf_page(http, base, k, root, depth + 1, seen)
                    start += len(kids.get("results") or [])
                    if len(kids.get("results") or []) < 50:
                        break
        except Missing as e:
            self.note(root, title + " (children)", "not read", str(e))

    @staticmethod
    def conf_access(page):
        """Who the page is restricted to for reading, from its own read restrictions. A page can also inherit a restriction
        from an ancestor; the API only shows the person reading it whether they can see it, so that is noted, not decided."""
        r = (((page.get("restrictions") or {}).get("read") or {}).get("restrictions")) or {}
        users = [u.get("displayName") or u.get("username") or u.get("accountId") or "a user" for u in (r.get("user") or {}).get("results") or []]
        groups = [g.get("name") or "a group" for g in (r.get("group") or {}).get("results") or []]
        if users or groups:
            return {"access": "restricted", "restricted_to": users + ["group " + g for g in groups]}
        return {}

    def conf_attachments(self, http, base, pid, web, root, access=None):
        start = 0
        while True:
            r = http.json("%s/rest/api/content/%s/child/attachment?limit=50&start=%d" % (base, pid, start))
            for a in r.get("results") or []:
                link = (a.get("_links") or {}).get("download")
                if not link:
                    continue
                size = ((a.get("extensions") or {}).get("fileSize")) or 0
                if size > MAX_BYTES:
                    self.note(root, a.get("title"), "not read", "attachment is over %d MB" % (MAX_BYTES // 1024 // 1024))
                    continue
                if not self.room():
                    return self.note(root, a.get("title"), "not read", "over the limit of %d files per run" % self.max_files)
                try:
                    self.store(a.get("title") or "attachment", http.bytes(base + link), web + " (attachment %s)" % a.get("title"), root,
                               **(access or {}))
                except (Missing, RuntimeError) as e:
                    self.note(root, a.get("title"), "not read", str(e))
            start += len(r.get("results") or [])
            if len(r.get("results") or []) < 50:
                break

    # ---- SharePoint / OneDrive (Microsoft Graph) ---------------------------------------------
    def sharepoint(self, url):
        http = self.http_factory("sharepoint")
        sid = "u!" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        item = http.json("%s/shares/%s/driveItem" % (GRAPH, sid))
        self.sp_item(http, item, url, 0, "")

    def sp_item(self, http, item, root, depth, rel):
        name = item.get("name") or "item"
        shown = (rel + "/" + name).lstrip("/")
        if "folder" in item:
            if depth >= MAX_DEPTH:
                return self.note(root, shown, "not read", "folder is nested deeper than %d levels" % MAX_DEPTH)
            drive = (item.get("parentReference") or {}).get("driveId")
            nxt = "%s/drives/%s/items/%s/children?$top=200" % (GRAPH, drive, item["id"])
            while nxt:
                page = http.json(nxt)
                for c in page.get("value") or []:
                    if not self.room():
                        return self.note(root, shown, "not read", "over the limit of %d files per run" % self.max_files)
                    self.sp_item(http, c, root, depth + 1, shown)
                nxt = page.get("@odata.nextLink")
            return
        if (item.get("size") or 0) > MAX_BYTES:
            return self.note(root, shown, "not read", "file is over %d MB" % (MAX_BYTES // 1024 // 1024))
        if name.lower().endswith(".aspx"):
            return self.note(root, shown, "not read", "a SharePoint site page, not a file; export it or copy the text into a document")
        try:
            dl = item.get("@microsoft.graph.downloadUrl")
            data = http.bytes(dl, auth=False) if dl else http.bytes(
                "%s/drives/%s/items/%s/content" % (GRAPH, (item.get("parentReference") or {}).get("driveId"), item["id"]))
        except (Missing, RuntimeError) as e:
            return self.note(root, shown, "not read", str(e))
        who = ((item.get("lastModifiedBy") or {}).get("user") or {}).get("displayName")
        modified = item.get("lastModifiedDateTime") or ""
        web = item.get("webUrl") or root
        prev = self.known.get(web)
        if prev and modified and str(prev.get("version")) == modified:
            return self.note(root, shown, "unchanged", "last modified %s is already in the KB as %s" % (modified[:10], prev["id"]))
        scope = (item.get("shared") or {}).get("scope")
        access = {"access": "restricted", "restricted_to": ["specific people (SharePoint sharing scope: users)"]} if scope == "users" else {}
        self.store(name, data, web, root, modified=modified[:10], modified_by=who, folder=rel, version=modified or None,
                   changed_from=(prev or {}).get("id"), **access)

    # ---- run ---------------------------------------------------------------------------------
    def run(self, sources):
        register = read_docs.load_register(self.kb)
        registered = {k: v.get("sha256") for k, v in register.items()}
        self.known = {v["origin"]: {"id": k, "version": v.get("version")} for k, v in register.items() if v.get("origin")}
        for s in sources:
            self.sources.append(s)
            try:
                if re.match(r"^https?://", s):
                    kind = link_kind(s, self.profile)
                    if kind == "confluence":
                        self.confluence(s)
                    elif kind == "sharepoint":
                        self.sharepoint(s)
                    else:
                        self.note(s, s, "not read", "link type not recognised (Confluence and SharePoint/OneDrive links are supported)")
                else:
                    self.local(s)
            except Denied as e:
                self.note(s, s, "not read", str(e))
            except Missing as e:
                self.note(s, s, "not read", str(e))
            except (RuntimeError, urllib.error.HTTPError) as e:
                self.note(s, s, "not read", str(e)[:200])
        read_docs.cmd_extract(self.scratch, self.files, self.by, origins=self.origins, registered=registered, extra=self.meta)
        self.finish()

    def finish(self):
        mp = read_docs.manifest_path(self.scratch)
        man = read_docs.load_manifest(self.scratch).get("documents", {}) if os.path.isfile(mp) else {}
        summary = {"by": self.by, "on": datetime.date.today().isoformat(), "sources": self.sources,
                   "files": self.log,
                   "documents": {k: {"name": d["name"], "status": d.get("status"), "reason": d.get("reason"),
                                     "origin": d.get("origin")} for k, d in man.items()}}
        with open(os.path.join(self.scratch, "INTAKE.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(summary, fh, sort_keys=False, allow_unicode=True)
        read = sum(1 for d in man.values() if d.get("status") == "read")
        skipped = sum(1 for e in self.log if e["status"] == "not read")
        print("intake: %d documents read, %d not read -> %s" % (
            read, len(man) - read + skipped, os.path.join(self.scratch, "INTAKE.yaml")))
        return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kb")
    ap.add_argument("scratch")
    ap.add_argument("--by", required=True, help="who is giving the documents")
    ap.add_argument("--max-files", type=int, default=MAX_FILES)
    ap.add_argument("sources", nargs="+")
    a = ap.parse_args(argv)
    kb, scratch = os.path.abspath(a.kb), os.path.abspath(a.scratch)
    if scratch == kb or scratch.startswith(kb + os.sep):
        raise SystemExit("the scratch folder must be outside the KB folder, e.g. /tmp/metis-docs/<run>")
    Intake(kb, scratch, a.by, max_files=a.max_files).run(a.sources)
    return 0


if __name__ == "__main__":
    sys.exit(main())
