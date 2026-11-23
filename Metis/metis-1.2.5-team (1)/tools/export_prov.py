#!/usr/bin/env python3
"""W3C PROV-O and OpenTelemetry provenance export for Metis knowledge bases.

    python3 export_prov.py prov <kb> [--out <dir_or_file>] [--format all|turtle|json]
    python3 export_prov.py otel <kb> [--out <file>] [--post] [--endpoint <url>]

Provenance standards:
  - W3C PROV-O (Turtle .ttl and PROV-JSON .json):
      Activities = builds, certifications, task runs
      Agents     = certifiers, leads, Devin sessions, Metis build engine
      Entities   = KB files with sha256 hashes, evidence documents, batches
      Relations  = wasGeneratedBy, wasAttributedTo, wasAssociatedWith, used, actedOnBehalfOf

  - OpenTelemetry (OTLP JSON):
      Generates compliant TracesData and LogsData structures recording builds, tasks, and certifications.
      Writes locally to file by default (no network exporter required).
      Optional --post sends the OTLP JSON payload via HTTP POST to the endpoint configured in the KB profile
      (otel.endpoint) or given by --endpoint.

Plain KB fields (CERTIFICATIONS.log, certified.yaml, KNOWLEDGE-MANIFEST.yaml, kb-profile.yaml) remain the source of truth.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_gate  # noqa: E402
import kb_manifest  # noqa: E402

PROV_PREFIXES = {
    "prov": "http://www.w3.org/ns/prov#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "metis": "https://metis.metis-kb.org/schema/",
    "kb": "https://metis.metis-kb.org/resource/",
}


def clean_id(text):
    return re.sub(r"[^a-zA-Z0-9_\-\.]+", "_", str(text or "").strip()).strip("_") or "unknown"


def escape_str(s):
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


def load_certifications(kb):
    """Load certifications from certified.yaml and CERTIFICATIONS.log."""
    st = kb_gate.load_state(kb)
    log_path = os.path.join(kb, ".metis", "CERTIFICATIONS.log")
    log_entries = []
    if os.path.isfile(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s:
                    continue
                parts = s.split("\t")
                if len(parts) >= 2:
                    ts = parts[0]
                    action = parts[1]
                    by = parts[2] if len(parts) > 2 else ""
                    role = parts[3] if len(parts) > 3 else ""
                    batch = parts[4] if len(parts) > 4 else ""
                    detail = parts[5] if len(parts) > 5 else ""
                    note = parts[6] if len(parts) > 6 else ""
                    log_entries.append({
                        "timestamp": ts,
                        "action": action,
                        "by": by,
                        "role": role,
                        "batch": batch,
                        "detail": detail,
                        "note": note,
                    })
    return st, log_entries


def load_manifest_entries(kb):
    """Load file entries with hashes from KNOWLEDGE-MANIFEST.yaml or generate on the fly."""
    man_path = os.path.join(kb, "KNOWLEDGE-MANIFEST.yaml")
    if os.path.isfile(man_path):
        with open(man_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
            entries = data.get("entries") or []
            if entries:
                return entries
    return kb_manifest.collect(kb, git=False)


def collect_prov_data(kb):
    """Assemble PROV activities, agents, entities, and relations from KB plain files."""
    prof = kb_gate.profile(kb)
    kb_name = prof.get("product", {}).get("name") or os.path.basename(os.path.abspath(kb))
    state, logs = load_certifications(kb)
    files = load_manifest_entries(kb)
    cert_files = state.get("files") or {}

    activities = {}
    agents = {}
    entities = {}
    was_generated_by = []
    was_attributed_to = []
    was_associated_with = []
    used_relations = []
    acted_on_behalf_of = []

    # System Agent: Metis
    agents["agent:software:metis"] = {
        "id": "agent:software:metis",
        "name": "Metis Knowledge Builder",
        "type": "prov:SoftwareAgent",
        "version": "2.0.0",
    }
    agents["agent:software:devin"] = {
        "id": "agent:software:devin",
        "name": "Devin AI Session",
        "type": "prov:SoftwareAgent",
    }

    # Lock / Initial activity
    if state.get("locked"):
        locked_by = state.get("locked_by") or "Lead"
        locked_on = state.get("locked_on") or datetime.date.today().isoformat()
        act_id = "activity:lock:initial"
        activities[act_id] = {
            "id": act_id,
            "type": "metis:LockActivity",
            "time": locked_on,
            "label": "KB Initial Lock",
        }
        ag_id = "agent:person:" + clean_id(locked_by)
        agents[ag_id] = {
            "id": ag_id,
            "name": locked_by,
            "type": "prov:Person",
        }
        was_associated_with.append({"activity": act_id, "agent": ag_id, "role": "lead"})

    # Certification activities from logs and state
    batch_map = {}
    for entry in logs:
        b_name = entry.get("batch") or "batch"
        act_id = "activity:certify:" + clean_id(b_name)
        if act_id not in activities:
            activities[act_id] = {
                "id": act_id,
                "type": "metis:CertificationActivity",
                "time": entry.get("timestamp") or datetime.date.today().isoformat(),
                "label": "Certify batch %s" % b_name,
                "batch": b_name,
            }
        by = entry.get("by")
        if by:
            ag_id = "agent:person:" + clean_id(by)
            agents[ag_id] = {
                "id": ag_id,
                "name": by,
                "type": "prov:Person",
                "role": entry.get("role") or "certifier",
            }
            rel = {"activity": act_id, "agent": ag_id, "role": entry.get("role") or "certifier"}
            if rel not in was_associated_with:
                was_associated_with.append(rel)

    # Entities: KB files
    for f in files:
        rel = f.get("path")
        sha = f.get("sha256") or ""
        ent_id = "entity:file:" + clean_id(rel)
        entities[ent_id] = {
            "id": ent_id,
            "path": rel,
            "sha256": sha,
            "bytes": f.get("bytes", 0),
            "type": "metis:KBFile",
            "source_tags": f.get("source_tags", 0),
        }

        # Check certification state for attribution and generation
        cf = cert_files.get(rel)
        if cf:
            by = cf.get("by")
            batch = cf.get("batch") or "initial"
            act_id = "activity:certify:" + clean_id(batch) if batch != "initial" else "activity:lock:initial"
            if act_id in activities:
                was_generated_by.append({"entity": ent_id, "activity": act_id})
            if by:
                ag_id = "agent:person:" + clean_id(by)
                was_attributed_to.append({"entity": ent_id, "agent": ag_id})

    # Evidence documents as entities used by activities
    doc_src = os.path.join(kb, "_EVIDENCE", "documents", "DOC_SOURCES.yaml")
    if os.path.isfile(doc_src):
        try:
            with open(doc_src, encoding="utf-8") as fh:
                ddata = yaml.safe_load(fh) or {}
                for doc in ddata.get("documents") or []:
                    dname = doc.get("name") or doc.get("id") or "doc"
                    dent_id = "entity:document:" + clean_id(dname)
                    entities[dent_id] = {
                        "id": dent_id,
                        "name": dname,
                        "type": "metis:EvidenceDocument",
                    }
                    if doc.get("given_by"):
                        gag_id = "agent:person:" + clean_id(doc["given_by"])
                        agents[gag_id] = {"id": gag_id, "name": doc["given_by"], "type": "prov:Person"}
                        was_attributed_to.append({"entity": dent_id, "agent": gag_id})
        except Exception:
            pass

    return {
        "kb_name": kb_name,
        "activities": activities,
        "agents": agents,
        "entities": entities,
        "was_generated_by": was_generated_by,
        "was_attributed_to": was_attributed_to,
        "was_associated_with": was_associated_with,
        "used": used_relations,
        "acted_on_behalf_of": acted_on_behalf_of,
    }


# ---- W3C PROV-O Turtle Serializer ------------------------------------------------

def to_prov_turtle(kb):
    """Serialize provenance graph to W3C PROV-O Turtle format."""
    data = collect_prov_data(kb)
    lines = [
        "# W3C PROV-O Provenance Export for Metis KB: %s" % escape_str(data["kb_name"]),
        "# Generated by export_prov.py on %s" % datetime.date.today().isoformat(),
        "",
    ]
    for pfx, uri in sorted(PROV_PREFIXES.items()):
        lines.append("@prefix %s: <%s> ." % (pfx, uri))
    lines.append("")

    # Agents
    lines.append("# ---- Agents ------------------------------------------------------")
    for a in sorted(data["agents"].values(), key=lambda x: x["id"]):
        lines.append("<https://metis.metis-kb.org/resource/%s>" % a["id"])
        lines.append("    a %s ;" % (a.get("type") or "prov:Agent"))
        lines.append('    rdfs:label "%s" .' % escape_str(a.get("name", a["id"])))
        lines.append("")

    # Activities
    lines.append("# ---- Activities --------------------------------------------------")
    for act in sorted(data["activities"].values(), key=lambda x: x["id"]):
        lines.append("<https://metis.metis-kb.org/resource/%s>" % act["id"])
        lines.append("    a prov:Activity, %s ;" % (act.get("type") or "metis:Activity"))
        lines.append('    rdfs:label "%s" ;' % escape_str(act.get("label", act["id"])))
        if act.get("time"):
            lines.append('    prov:endedAtTime "%s"^^xsd:string ;' % escape_str(act["time"]))
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")

    # Entities
    lines.append("# ---- Entities ----------------------------------------------------")
    for e in sorted(data["entities"].values(), key=lambda x: x["id"]):
        lines.append("<https://metis.metis-kb.org/resource/%s>" % e["id"])
        lines.append("    a prov:Entity, %s ;" % (e.get("type") or "metis:Entity"))
        if e.get("path"):
            lines.append('    rdfs:label "%s" ;' % escape_str(e["path"]))
            lines.append('    metis:path "%s" ;' % escape_str(e["path"]))
        if e.get("sha256"):
            lines.append('    metis:sha256 "%s" ;' % escape_str(e["sha256"]))
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")

    # Relations
    lines.append("# ---- Provenance Relations ----------------------------------------")
    for rel in data["was_generated_by"]:
        lines.append("<https://metis.metis-kb.org/resource/%s> prov:wasGeneratedBy <https://metis.metis-kb.org/resource/%s> ."
                     % (rel["entity"], rel["activity"]))
    for rel in data["was_attributed_to"]:
        lines.append("<https://metis.metis-kb.org/resource/%s> prov:wasAttributedTo <https://metis.metis-kb.org/resource/%s> ."
                     % (rel["entity"], rel["agent"]))
    for rel in data["was_associated_with"]:
        lines.append("<https://metis.metis-kb.org/resource/%s> prov:wasAssociatedWith <https://metis.metis-kb.org/resource/%s> ."
                     % (rel["activity"], rel["agent"]))

    lines.append("")
    return "\n".join(lines)


# ---- W3C PROV-JSON Serializer ---------------------------------------------------

def to_prov_json(kb):
    """Serialize provenance to W3C PROV-JSON format."""
    data = collect_prov_data(kb)
    prov_doc = {
        "prefix": PROV_PREFIXES,
        "agent": {},
        "activity": {},
        "entity": {},
        "wasGeneratedBy": {},
        "wasAttributedTo": {},
        "wasAssociatedWith": {},
    }

    for a in data["agents"].values():
        prov_doc["agent"][a["id"]] = {
            "prov:type": a.get("type", "prov:Agent"),
            "rdfs:label": a.get("name", a["id"]),
        }

    for act in data["activities"].values():
        prov_doc["activity"][act["id"]] = {
            "prov:type": act.get("type", "prov:Activity"),
            "rdfs:label": act.get("label", act["id"]),
            "prov:endedAtTime": act.get("time", ""),
        }

    for e in data["entities"].values():
        prov_doc["entity"][e["id"]] = {
            "prov:type": e.get("type", "prov:Entity"),
            "metis:path": e.get("path", ""),
            "metis:sha256": e.get("sha256", ""),
        }

    for idx, rel in enumerate(data["was_generated_by"]):
        prov_doc["wasGeneratedBy"]["_:wgb_%d" % idx] = {
            "prov:entity": rel["entity"],
            "prov:activity": rel["activity"],
        }

    for idx, rel in enumerate(data["was_attributed_to"]):
        prov_doc["wasAttributedTo"]["_:wat_%d" % idx] = {
            "prov:entity": rel["entity"],
            "prov:agent": rel["agent"],
        }

    for idx, rel in enumerate(data["was_associated_with"]):
        prov_doc["wasAssociatedWith"]["_:waw_%d" % idx] = {
            "prov:activity": rel["activity"],
            "prov:agent": rel["agent"],
            "prov:role": rel.get("role", ""),
        }

    return json.dumps(prov_doc, indent=2, ensure_ascii=False)


# ---- OpenTelemetry (OTLP JSON) Exporter -----------------------------------------

def to_otlp_json(kb):
    """Generate OpenTelemetry-shaped TracesData and LogsData in JSON format."""
    data = collect_prov_data(kb)
    kb_name = data["kb_name"]
    now_nano = int(time.time() * 1e9)

    # Generate deterministic hex IDs from names
    def hex_id(s, length=16):
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]

    trace_id = hex_id("trace:" + kb_name, 32)
    spans = []
    log_records = []

    # Activity Spans
    for act in data["activities"].values():
        span_id = hex_id(act["id"], 16)
        span_attrs = [
            {"key": "metis.activity.id", "value": {"stringValue": act["id"]}},
            {"key": "metis.activity.type", "value": {"stringValue": act.get("type", "")}},
        ]
        if act.get("batch"):
            span_attrs.append({"key": "metis.batch", "value": {"stringValue": act["batch"]}})

        spans.append({
            "traceId": trace_id,
            "spanId": span_id,
            "name": act.get("label", act["id"]),
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": str(now_nano - 1000000000),
            "endTimeUnixNano": str(now_nano),
            "attributes": span_attrs,
            "status": {"code": 1},  # STATUS_CODE_OK
        })

    # Certification Log Records
    _, logs = load_certifications(kb)
    for idx, log_entry in enumerate(logs):
        log_attrs = [
            {"key": "action", "value": {"stringValue": log_entry.get("action", "")}},
            {"key": "by", "value": {"stringValue": log_entry.get("by", "")}},
            {"key": "role", "value": {"stringValue": log_entry.get("role", "")}},
            {"key": "batch", "value": {"stringValue": log_entry.get("batch", "")}},
            {"key": "detail", "value": {"stringValue": log_entry.get("detail", "")}},
        ]
        log_records.append({
            "timeUnixNano": str(now_nano - (len(logs) - idx) * 1000000),
            "severityNumber": 9,  # INFO
            "severityText": "INFO",
            "body": {"stringValue": "Certification: %s %s by %s" % (
                log_entry.get("action"), log_entry.get("detail"), log_entry.get("by"))},
            "attributes": log_attrs,
            "traceId": trace_id,
            "spanId": hex_id("log:%d" % idx, 16),
        })

    resource = {
        "attributes": [
            {"key": "service.name", "value": {"stringValue": "metis"}},
            {"key": "service.version", "value": {"stringValue": "2.0.0"}},
            {"key": "kb.name", "value": {"stringValue": kb_name}},
        ]
    }

    otlp_payload = {
        "resourceSpans": [
            {
                "resource": resource,
                "scopeSpans": [
                    {
                        "scope": {"name": "metis.export_prov", "version": "2.0.0"},
                        "spans": spans,
                    }
                ],
            }
        ],
        "resourceLogs": [
            {
                "resource": resource,
                "scopeLogs": [
                    {
                        "scope": {"name": "metis.export_prov", "version": "2.0.0"},
                        "logRecords": log_records,
                    }
                ],
            }
        ],
    }

    return json.dumps(otlp_payload, indent=2, ensure_ascii=False)


def post_otlp(payload_json, endpoint):
    """Post OTLP JSON payload to an OTLP/HTTP endpoint."""
    if not endpoint or not endpoint.strip():
        raise ValueError("OTLP endpoint URL is required for --post")
    data = payload_json.encode("utf-8")
    req = urllib.request.Request(endpoint.strip(), data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def export_all_prov(kb, out_dir=None):
    """Write PROV Turtle, PROV-JSON, and OTLP JSON files to destination."""
    out = out_dir or os.path.join(kb, ".metis", "exports", "prov")
    os.makedirs(out, exist_ok=True)

    ttl_text = to_prov_turtle(kb)
    json_text = to_prov_json(kb)
    otel_text = to_otlp_json(kb)

    files = {
        "prov-o.ttl": ttl_text,
        "prov.json": json_text,
        "otel-traces.json": otel_text,
    }

    written = []
    for fname, content in files.items():
        p = os.path.join(out, fname)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        written.append(p)

    return written


# ---- CLI -------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a_prov = sub.add_parser("prov", help="Export W3C PROV provenance")
    a_prov.add_argument("kb", help="Path to knowledge base")
    a_prov.add_argument("--out", help="Output directory or file")
    a_prov.add_argument("--format", choices=["all", "turtle", "json"], default="all")

    a_otel = sub.add_parser("otel", help="Export OpenTelemetry traces/logs JSON")
    a_otel.add_argument("kb", help="Path to knowledge base")
    a_otel.add_argument("--out", help="Output file path")
    a_otel.add_argument("--post", action="store_true", help="Post payload to OTLP/HTTP endpoint")
    a_otel.add_argument("--endpoint", help="OTLP/HTTP endpoint URL (defaults to otel.endpoint in profile)")

    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)

    if args.cmd == "prov":
        if args.format == "all":
            written = export_all_prov(kb, args.out)
            for w in written:
                print("Exported: %s" % w)
        elif args.format == "turtle":
            text = to_prov_turtle(kb)
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                print("Exported PROV-O Turtle -> %s" % args.out)
            else:
                sys.stdout.write(text)
        elif args.format == "json":
            text = to_prov_json(kb)
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                print("Exported PROV-JSON -> %s" % args.out)
            else:
                sys.stdout.write(text)
        return 0

    elif args.cmd == "otel":
        payload = to_otlp_json(kb)
        out_file = args.out or os.path.join(kb, ".metis", "exports", "prov", "otel-traces.json")
        os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
        with open(out_file, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        print("Exported OTLP JSON -> %s" % out_file)

        if args.post:
            prof = kb_gate.profile(kb)
            endpoint = args.endpoint or prof.get("otel", {}).get("endpoint")
            if not endpoint:
                print("Error: no endpoint given or configured in kb-profile.yaml (otel.endpoint)", file=sys.stderr)
                return 1
            code, resp = post_otlp(payload, endpoint)
            print("Posted to %s: HTTP %d (%s)" % (endpoint, code, resp[:100]))
            return 0 if (200 <= code < 300) else 1
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
