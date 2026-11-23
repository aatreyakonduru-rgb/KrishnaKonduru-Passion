#!/usr/bin/env python3
"""Open Knowledge Format (OKF) bundle packager and validator for Metis knowledge bases.

    python3 okf_bundle.py bundle   <kb> [--out <dir>] [--max-sensitivity LEVEL]
    python3 okf_bundle.py validate <bundle_dir_or_kb>

Layout and Standards:
  - Produces an OKF-shaped bundle: Markdown files with YAML frontmatter (type, title, description, sources, trust, status)
    and per-folder `index.md` indices so agents and tools can browse the knowledge graph step-by-step.
  - Manifest (`okf-manifest.yaml`) with sha256 hashes of all bundled files.
  - Cross-bundle links represented as relative manifest references.
  - Validation checks:
      1. Frontmatter fields: valid YAML, non-empty `type` present on every content page.
      2. Index resolution: all links in `index.md` resolve to existing bundle files.
      3. Hash integrity: bundle files match `okf-manifest.yaml`.
      4. Sensitive data check: no secrets, keys, or cards (sensitive.py).

Claim labels (claim_labels.py): when the KB uses `{env: ...; sensitivity: ...}` labels, the bundle holds only lines at or below the sharing
level (`--max-sensitivity`, default `labels.share_max_sensitivity` in the profile, else `public`); a page with nothing left is not
bundled, and non-Markdown files inside a `labels.restricted_folders` folder are not copied. CROSS-LAYER/LINK_GRAPH.yaml is filtered
(links citing withheld lines are removed). Every other non-Markdown file is copied as it is and is NOT label-filtered. A KB with no
labels is bundled as before.

Compliance Note:
  "OKF-shaped, validated against Metis's own rules; formal compliance needs the official validator."
  (Do not claim OKF v0.2 formal compliance until the official validator is standard).
"""
import argparse
import datetime
import hashlib
import os
import re
import shutil
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claim_labels  # noqa: E402
import kb_gate  # noqa: E402
import sensitive  # noqa: E402

SKIP_DIRS = (".git", "Archive", "_EVIDENCE", "_PENDING", "_FEEDBACK", "_REGEN", ".metis")
FRONT_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
TAG_RE = re.compile(r"\[E:\s*([^\]]+)\]")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def sha_bytes(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def sha_file(path):
    with open(path, "rb") as fh:
        return sha_bytes(fh.read())


def parse_frontmatter(text):
    m = FRONT_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[m.end():]


def extract_title(body, fallback=""):
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return fallback


def extract_description(body):
    lines = []
    seen_heading = False
    for line in body.splitlines():
        s = line.strip()
        if not s:
            if lines:
                break
            continue
        if s.startswith("#"):
            seen_heading = True
            continue
        lines.append(s)
        if len(" ".join(lines)) > 200:
            break
    desc = " ".join(lines).strip()
    return desc[:250] if desc else "Knowledge base documentation page."


def guess_type(rel_path, meta):
    if meta.get("type"):
        return str(meta["type"])
    p_low = rel_path.lower()
    if "table" in p_low or "db" in p_low:
        return "table"
    if "endpoint" in p_low or "api" in p_low:
        return "endpoint"
    if "job" in p_low or "etl" in p_low:
        return "job"
    if "process" in p_low or "flow" in p_low:
        return "process"
    if "requirement" in p_low or "brd" in p_low:
        return "requirement"
    if "architecture" in p_low or "trd" in p_low:
        return "architecture"
    return "concept"


# ---- Bundle Packager -------------------------------------------------------------

def bundle(kb, out_dir=None, max_level=None):
    """Package KB into an OKF-shaped bundle with frontmatter, index.md in every folder, and manifest. `max_level`: the highest
    claim-label sensitivity to include (default: the profile's labels.share_max_sensitivity, else public)."""
    kb = os.path.abspath(kb)
    viewer = claim_labels.Viewer(kb, level=max_level or claim_labels.share_level(kb))
    prof = kb_gate.profile(kb)
    kb_name = prof.get("product", {}).get("name") or os.path.basename(kb)
    owner_team = prof.get("product", {}).get("team") or "Knowledge Engineering"
    state = kb_gate.load_state(kb) if kb_gate.is_locked(kb) else {}
    cert_files = state.get("files") or {}

    out = out_dir or os.path.join(kb, ".metis", "exports", "okf_bundle")
    if os.path.exists(out):
        shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)

    bundled_files = []
    folder_entries = {}  # rel_dir -> [ {path, title, type, desc, status} ]

    # Collect and transform content files
    for dirpath, dirnames, filenames in os.walk(kb):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            src_p = os.path.join(dirpath, fname)
            rel = os.path.relpath(src_p, kb).replace(os.sep, "/")
            if rel.startswith(".metis/") or rel == "KNOWLEDGE-MANIFEST.yaml":
                continue

            if viewer.file_hidden(rel):
                continue
            if fname.endswith((".md", ".markdown")):
                with open(src_p, encoding="utf-8", errors="replace") as fh:
                    raw_text = fh.read()
                raw_text, hidden = viewer.filter(rel, raw_text)
                if hidden and not raw_text.strip():
                    continue
                dst_p = os.path.join(out, rel)
                os.makedirs(os.path.dirname(dst_p), exist_ok=True)
                meta, body = parse_frontmatter(raw_text)

                ctype = guess_type(rel, meta)
                title = meta.get("title") or extract_title(body, os.path.splitext(fname)[0].replace("-", " ").title())
                desc = meta.get("description") or extract_description(body)
                status = meta.get("status") or "stable"

                # Sources extracted from tags and frontmatter
                sources = list(meta.get("sources") or [])
                for tag in TAG_RE.findall(body):
                    if tag not in sources:
                        sources.append(tag)

                # Trust and Certification status
                is_cert = rel in cert_files
                trust_val = "verified" if is_cert else "unverified"
                cert_info = cert_files.get(rel)

                # Construct OKF frontmatter
                okf_meta = {
                    "type": ctype,
                    "title": title,
                    "description": desc,
                    "status": status,
                    "trust": trust_val,
                    "owner_team": owner_team,
                    "sources": sources,
                }
                if cert_info:
                    okf_meta["certified_by"] = cert_info.get("by")
                    okf_meta["certified_on"] = str(cert_info.get("on"))
                    okf_meta["batch"] = cert_info.get("batch")

                # Preserve any extra custom fields
                for k, v in meta.items():
                    if k not in okf_meta:
                        okf_meta[k] = v

                # Write out file with updated frontmatter
                new_content = "---\n%s---\n\n%s" % (
                    yaml.safe_dump(okf_meta, sort_keys=False, allow_unicode=True),
                    body.lstrip(),
                )
                with open(dst_p, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(new_content)

                rel_dir = os.path.dirname(rel)
                folder_entries.setdefault(rel_dir, []).append({
                    "rel_path": rel,
                    "name": fname,
                    "title": title,
                    "type": ctype,
                    "description": desc,
                    "status": status,
                    "trust": trust_val,
                })
            else:
                # Copy other assets / yaml / txt files verbatim
                dst_p = os.path.join(out, rel)
                os.makedirs(os.path.dirname(dst_p), exist_ok=True)
                if viewer.active and rel == "CROSS-LAYER/LINK_GRAPH.yaml":
                    with open(src_p, encoding="utf-8") as fh:
                        graph_text = claim_labels.filter_graph_text(viewer, fh.read())
                    with open(dst_p, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(graph_text)
                else:
                    shutil.copy2(src_p, dst_p)

    # Generate index.md for each directory
    all_dirs = set(folder_entries.keys())
    for dirpath, dirnames, _ in os.walk(out):
        r_dir = os.path.relpath(dirpath, out).replace(os.sep, "/")
        if r_dir == ".":
            r_dir = ""
        all_dirs.add(r_dir)

    for r_dir in sorted(all_dirs):
        idx_path = os.path.join(out, r_dir, "index.md") if r_dir else os.path.join(out, "index.md")
        sub_items = folder_entries.get(r_dir, [])
        dir_title = os.path.basename(r_dir).replace("-", " ").title() if r_dir else (kb_name + " Knowledge Bundle")

        lines = [
            "---",
            "type: index",
            "title: %s Index" % dir_title,
            "description: Index of knowledge concepts and pages in %s" % (r_dir or "root"),
            "---",
            "",
            "# %s" % dir_title,
            "",
            "Knowledge concepts in this section:",
            "",
            "| Concept | Type | Status | Trust | Description |",
            "|---|---|---|---|---|",
        ]
        for it in sub_items:
            if it["name"] == "index.md":
                continue
            lines.append("| [%s](%s) | `%s` | %s | %s | %s |" % (
                it["title"], it["name"], it["type"], it["status"], it["trust"], it["description"][:100]))

        # Subfolders navigation
        curr_disk_dir = os.path.join(out, r_dir) if r_dir else out
        subdirs = sorted(d for d in os.listdir(curr_disk_dir) if os.path.isdir(os.path.join(curr_disk_dir, d)))
        if subdirs:
            lines += ["", "## Sub-sections", ""]
            for sd in subdirs:
                lines.append("- [%s/](%s/index.md)" % (sd, sd))

        lines.append("")
        with open(idx_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines))

    # Generate bundle manifest
    manifest_entries = []
    for dirpath, _, filenames in os.walk(out):
        for fname in sorted(filenames):
            if fname == "okf-manifest.yaml":
                continue
            fp = os.path.join(dirpath, fname)
            rel_b = os.path.relpath(fp, out).replace(os.sep, "/")
            sz = os.path.getsize(fp)
            h = sha_file(fp)
            manifest_entries.append({
                "path": rel_b,
                "bytes": sz,
                "sha256": h,
            })

    manifest_doc = {
        "okf_version": "0.2-metis-preview",
        "bundle_name": kb_name,
        "owner_team": owner_team,
        "generated_on": datetime.date.today().isoformat(),
        "files_count": len(manifest_entries),
        "manifest": manifest_entries,
    }
    with open(os.path.join(out, "okf-manifest.yaml"), "w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump(manifest_doc, fh, sort_keys=False, width=120)

    return out, len(manifest_entries)


# ---- Validator -------------------------------------------------------------------

def validate(target_path):
    """Validate an OKF bundle or KB according to Metis derived rules."""
    bundle_dir = os.path.abspath(target_path)
    man_path = os.path.join(bundle_dir, "okf-manifest.yaml")
    if not os.path.isfile(man_path):
        # If target is KB root without export, bundle it in temporary path first or look for exported bundle
        exp_bundle = os.path.join(bundle_dir, ".metis", "exports", "okf_bundle")
        if os.path.isfile(os.path.join(exp_bundle, "okf-manifest.yaml")):
            bundle_dir = exp_bundle
            man_path = os.path.join(bundle_dir, "okf-manifest.yaml")
        else:
            return {
                "valid": False,
                "problems": ["No okf-manifest.yaml found in %s; run okf_bundle.py bundle first" % target_path],
                "files_checked": 0,
                "compliance_note": "OKF-shaped, validated against Metis's own rules; formal compliance needs the official validator.",
            }

    with open(man_path, encoding="utf-8") as fh:
        mdata = yaml.safe_load(fh) or {}

    manifest_files = {e["path"]: e.get("sha256") for e in mdata.get("manifest") or []}
    problems = []
    checked_count = 0

    # Rule 3: Hash matching
    for rel, exp_sha in manifest_files.items():
        fp = os.path.join(bundle_dir, rel)
        if not os.path.isfile(fp):
            problems.append("%s: missing file listed in manifest" % rel)
            continue
        checked_count += 1
        act_sha = sha_file(fp)
        if exp_sha and act_sha != exp_sha:
            problems.append("%s: sha256 mismatch (expected %s, got %s)" % (rel, exp_sha[:8], act_sha[:8]))

    # Rule 1: Frontmatter & non-empty type on markdown pages
    # Rule 2: Index resolution
    # Rule 4: Sensitivity check
    for dirpath, _, filenames in os.walk(bundle_dir):
        for fname in filenames:
            if not fname.endswith((".md", ".markdown")):
                continue
            fp = os.path.join(dirpath, fname)
            rel = os.path.relpath(fp, bundle_dir).replace(os.sep, "/")
            with open(fp, encoding="utf-8", errors="replace") as fh:
                text = fh.read()

            meta, body = parse_frontmatter(text)

            # Rule 1
            if not meta:
                problems.append("%s: missing or invalid YAML frontmatter" % rel)
            elif not meta.get("type"):
                problems.append("%s: frontmatter is missing required field 'type'" % rel)

            # Rule 4: Sensitive scanning
            findings = sensitive.scan(body)
            blocking = sensitive.blocking(findings)
            if blocking:
                problems.append("%s: sensitive finding (%s on line %d)" % (
                    rel, blocking[0]["kind"], blocking[0]["line"]))

            # Rule 2: Index link resolution
            if fname == "index.md":
                for text_lbl, link_target in LINK_RE.findall(body):
                    if link_target.startswith("http://") or link_target.startswith("https://"):
                        continue
                    # Cross-bundle relative manifest links are allowed
                    target_fp = os.path.normpath(os.path.join(dirpath, link_target))
                    if not os.path.exists(target_fp) and not link_target.startswith("../"):
                        problems.append("%s: link '%s' (%s) does not resolve" % (rel, text_lbl, link_target))

    is_valid = len(problems) == 0
    return {
        "valid": is_valid,
        "problems": problems,
        "files_checked": checked_count,
        "compliance_note": "OKF-shaped, validated against Metis's own rules; formal compliance needs the official validator.",
    }


# ---- CLI -------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a_bnd = sub.add_parser("bundle", help="Package KB into OKF bundle")
    a_bnd.add_argument("kb", help="Path to knowledge base")
    a_bnd.add_argument("--out", help="Output directory")
    a_bnd.add_argument("--max-sensitivity", help="highest claim-label level to bundle (default: profile labels.share_max_sensitivity, else public)")

    a_val = sub.add_parser("validate", help="Validate OKF bundle against Metis rules")
    a_val.add_argument("target", help="Bundle directory or KB path")

    args = ap.parse_args(argv)

    if args.cmd == "bundle":
        out_dir, count = bundle(args.kb, args.out, args.max_sensitivity)
        print("Bundled %d files -> %s" % (count, out_dir))
        return 0

    elif args.cmd == "validate":
        res = validate(args.target)
        print("Checked %d files: %s" % (res["files_checked"], "PASS (0 problems)" if res["valid"] else "FAIL"))
        print("Note: %s" % res["compliance_note"])
        if res["problems"]:
            for p in res["problems"]:
                print("  PROBLEM: " + p)
            return 1
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
