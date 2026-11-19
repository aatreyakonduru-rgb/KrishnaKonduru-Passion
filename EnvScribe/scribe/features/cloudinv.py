"""Feature 13 - Live cloud and Kubernetes inventory (read-only), compared with what the repositories say.

Uses the CLI sessions already logged in on this VM (aws, gcloud, az, kubectl) through ONE allow-listed runner: only list/describe/get verbs are
permitted and every command is audited. Nothing is created, changed or deleted. Network addresses, hostnames, endpoints, tags values and any
credential-bearing field are dropped before a fact is built. Collectors are off unless named in `cloud_inventory`; a missing CLI or login is reported as UNKNOWN.
UNVERIFIED against live accounts here: the parsers are tested with recorded-shape fixtures only.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import defaultdict
from typing import Callable

from ..facts import ev, make_fact
from .common import Ctx, Result, header, md_cell

Runner = Callable[[list[str]], str]
ALLOWED = {
    "aws": re.compile(r"^(?:describe|list|get)-[a-z0-9-]+$"),
    "gcloud": re.compile(r"^(?:list|describe)$"),
    "az": re.compile(r"^(?:list|show)$"),
    "kubectl": re.compile(r"^(?:get|api-resources|version)$"),
}
FORBIDDEN_WORDS = re.compile(r"(?i)\b(create|delete|update|put|apply|patch|replace|set|remove|start|stop|terminate|reboot|attach|detach|exec|scale|rollout|drain|cordon|taint|label|annotate|edit|import|export|invoke|get-secret-value|get-parameter|decrypt|get-password-data|get-login-password|--decrypt|get-authorization-token)\b")


class NotReadOnly(Exception):
    pass


def check_command(argv: list[str]) -> None:
    """Allow-list gate shared by the real runner and the tests."""
    if not argv or argv[0] not in ALLOWED:
        raise NotReadOnly(f"{argv[:1]} is not an allowed cloud CLI")
    tool = argv[0]
    verbs, skip = [], False
    for a in argv[1:]:                      # words that are neither flags nor flag values
        if skip:
            skip = False
        elif a in ("-o", "--output", "--format", "--query", "-n", "--namespace", "--region", "--profile", "--project", "--subscription"):
            skip = True
        elif not a.startswith("-"):
            verbs.append(a)
    if tool == "aws":
        if len(verbs) < 2 or not ALLOWED["aws"].match(verbs[1]):
            raise NotReadOnly("aws: only describe-*/list-*/get-* verbs are allowed")
    elif tool == "gcloud":
        if not verbs or verbs[-1] not in ("list", "describe"):
            raise NotReadOnly("gcloud: only list/describe are allowed")
    elif tool == "az":
        if not verbs or verbs[-1] not in ("list", "show"):
            raise NotReadOnly("az: only list/show are allowed")
    elif tool == "kubectl":
        if not verbs or not ALLOWED["kubectl"].match(verbs[0]):
            raise NotReadOnly("kubectl: only get/api-resources/version are allowed")
        if any(p.split("/")[0].startswith("secret") for r in verbs[1:] for p in r.lower().split(",")) or "--raw" in argv:
            raise NotReadOnly("kubectl: secrets and raw API access are never read")
    if FORBIDDEN_WORDS.search(" ".join(argv[1:])):
        raise NotReadOnly("command contains a mutating or secret-reading word")


def default_runner(audit=None) -> Runner:
    def run(argv: list[str]) -> str:
        check_command(argv)
        if audit:
            audit("cloud_cli", tool=argv[0], args=" ".join(a for a in argv[1:] if not a.startswith("--query"))[:120])
        if not shutil.which(argv[0]):
            raise FileNotFoundError(argv[0])
        p = subprocess.run(argv, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            raise RuntimeError(f"{argv[0]} exited {p.returncode}")
        return p.stdout
    return run


# ---- collectors: (provider, resource type, argv, extractor(json) -> [{"name", ...safe attrs}]) ----
def _g(d, *path, default=None):
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return default if d is None else d


SPECS: dict[str, list[tuple]] = {
    "aws": [
        ("rds_instance", ["aws", "rds", "describe-db-instances", "--output", "json"],
         lambda j: [{"name": x.get("DBInstanceIdentifier"), "engine": x.get("Engine"), "engine_version": x.get("EngineVersion"), "class": x.get("DBInstanceClass"), "multi_az": x.get("MultiAZ")} for x in j.get("DBInstances", [])]),
        ("ec2_instance", ["aws", "ec2", "describe-instances", "--output", "json"],
         lambda j: [{"name": i.get("InstanceId"), "type": i.get("InstanceType"), "state": _g(i, "State", "Name")} for r in j.get("Reservations", []) for i in r.get("Instances", [])]),
        ("eks_cluster", ["aws", "eks", "list-clusters", "--output", "json"], lambda j: [{"name": n} for n in j.get("clusters", [])]),
        ("lambda_function", ["aws", "lambda", "list-functions", "--output", "json"],
         lambda j: [{"name": x.get("FunctionName"), "runtime": x.get("Runtime"), "memory_mb": x.get("MemorySize")} for x in j.get("Functions", [])]),
        ("s3_bucket", ["aws", "s3api", "list-buckets", "--output", "json"], lambda j: [{"name": x.get("Name")} for x in j.get("Buckets", [])]),
        ("sqs_queue", ["aws", "sqs", "list-queues", "--output", "json"], lambda j: [{"name": (u or "").rsplit("/", 1)[-1]} for u in j.get("QueueUrls", [])]),
    ],
    "gcp": [
        ("gke_cluster", ["gcloud", "container", "clusters", "list", "--format=json"], lambda j: [{"name": x.get("name"), "version": x.get("currentMasterVersion"), "location": x.get("location")} for x in j]),
        ("cloudsql_instance", ["gcloud", "sql", "instances", "list", "--format=json"], lambda j: [{"name": x.get("name"), "engine": x.get("databaseVersion"), "tier": _g(x, "settings", "tier")} for x in j]),
        ("cloud_run_service", ["gcloud", "run", "services", "list", "--format=json"], lambda j: [{"name": _g(x, "metadata", "name")} for x in j]),
        ("gcs_bucket", ["gcloud", "storage", "buckets", "list", "--format=json"], lambda j: [{"name": x.get("name"), "location": x.get("location")} for x in j]),
        ("pubsub_topic", ["gcloud", "pubsub", "topics", "list", "--format=json"], lambda j: [{"name": (x.get("name") or "").rsplit("/", 1)[-1]} for x in j]),
    ],
    "azure": [
        ("aks_cluster", ["az", "aks", "list", "--output", "json"], lambda j: [{"name": x.get("name"), "version": x.get("kubernetesVersion"), "location": x.get("location")} for x in j]),
        ("sql_server", ["az", "sql", "server", "list", "--output", "json"], lambda j: [{"name": x.get("name"), "version": x.get("version"), "location": x.get("location")} for x in j]),
        ("webapp", ["az", "webapp", "list", "--output", "json"], lambda j: [{"name": x.get("name"), "kind": x.get("kind"), "state": x.get("state")} for x in j]),
        ("storage_account", ["az", "storage", "account", "list", "--output", "json"], lambda j: [{"name": x.get("name"), "kind": x.get("kind"), "sku": _g(x, "sku", "name")} for x in j]),
        ("acr", ["az", "acr", "list", "--output", "json"], lambda j: [{"name": x.get("name"), "sku": _g(x, "sku", "name")} for x in j]),
    ],
    "kubernetes": [
        ("k8s_namespace", ["kubectl", "get", "namespaces", "-o", "json"], lambda j: [{"name": _g(i, "metadata", "name")} for i in j.get("items", [])]),
        ("k8s_workload", ["kubectl", "get", "deployments,statefulsets,daemonsets,cronjobs", "-A", "-o", "json"],
         lambda j: [{"name": _g(i, "metadata", "name"), "kind": i.get("kind"), "namespace": _g(i, "metadata", "namespace"), "replicas": _g(i, "spec", "replicas"),
                     "images": [c.get("image") for c in (_g(i, "spec", "template", "spec", "containers", default=[]) or []) if isinstance(c, dict)]} for i in j.get("items", [])]),
        ("k8s_service", ["kubectl", "get", "services", "-A", "-o", "json"],
         lambda j: [{"name": _g(i, "metadata", "name"), "namespace": _g(i, "metadata", "namespace"), "service_type": _g(i, "spec", "type"),
                     "ports": [p.get("port") for p in (_g(i, "spec", "ports", default=[]) or []) if isinstance(p, dict)]} for i in j.get("items", [])]),
        ("k8s_ingress", ["kubectl", "get", "ingresses", "-A", "-o", "json"], lambda j: [{"name": _g(i, "metadata", "name"), "namespace": _g(i, "metadata", "namespace")} for i in j.get("items", [])]),
        ("k8s_configmap", ["kubectl", "get", "configmaps", "-A", "-o", "json"], lambda j: [{"name": _g(i, "metadata", "name"), "namespace": _g(i, "metadata", "namespace"), "keys": sorted((i.get("data") or {}).keys())[:50]} for i in j.get("items", [])]),
    ],
}


def collect(providers: list[str], run: Runner) -> tuple[list[dict], list[dict]]:
    """Return (resources, problems). resources: [{provider, type, attrs}]"""
    res, problems = [], []
    for prov in providers:
        if prov not in SPECS:
            problems.append({"provider": prov, "reason": "unknown provider"})
            continue
        for rtype, argv, extract in SPECS[prov]:
            try:
                j = json.loads(run(argv) or "null")
                for item in extract(j) if j is not None else []:
                    if item.get("name"):
                        res.append({"provider": prov, "type": rtype, "attrs": {k: v for k, v in item.items() if v is not None}})
            except NotReadOnly as exc:
                problems.append({"provider": prov, "type": rtype, "reason": f"blocked: {exc}"})
            except FileNotFoundError:
                problems.append({"provider": prov, "type": rtype, "reason": f"CLI `{argv[0]}` not installed on this VM"})
                break
            except (RuntimeError, subprocess.SubprocessError):
                problems.append({"provider": prov, "type": rtype, "reason": "command failed (not logged in, no permission, or API unavailable)"})
            except (ValueError, TypeError, AttributeError):
                problems.append({"provider": prov, "type": rtype, "reason": "output was not in the expected shape"})
    return res, problems


def compare_with_iac(resources: list[dict], facts: list[dict]) -> dict:
    live_k8s = {(r["attrs"].get("kind"), r["attrs"]["name"]) for r in resources if r["type"] == "k8s_workload"}
    iac_k8s = {(f["attrs"]["kind"], f["attrs"]["name"]): f for f in facts if f["kind"] == "k8s_resource" and f["attrs"].get("kind") in ("Deployment", "StatefulSet", "DaemonSet", "CronJob")}
    live_only = sorted(live_k8s - set(iac_k8s))
    iac_only = sorted(k for k in iac_k8s if k not in live_k8s)
    live_images = {i for r in resources if r["type"] == "k8s_workload" for i in r["attrs"].get("images", [])}
    iac_images = {i for f in iac_k8s.values() for i in f["attrs"].get("images", []) if i}
    tf = defaultdict(int)
    for f in facts:
        if f["kind"] == "iac_resource" and f["attrs"].get("block") == "resource":
            tf[f["attrs"]["type"]] += 1
    TF_MAP = {"rds_instance": "aws_db_instance", "ec2_instance": "aws_instance", "eks_cluster": "aws_eks_cluster", "lambda_function": "aws_lambda_function",
              "s3_bucket": "aws_s3_bucket", "sqs_queue": "aws_sqs_queue", "gke_cluster": "google_container_cluster", "cloudsql_instance": "google_sql_database_instance",
              "gcs_bucket": "google_storage_bucket", "pubsub_topic": "google_pubsub_topic", "aks_cluster": "azurerm_kubernetes_cluster", "storage_account": "azurerm_storage_account",
              "acr": "azurerm_container_registry"}
    live_counts = defaultdict(int)
    for r in resources:
        live_counts[r["type"]] += 1
    counts = [{"type": t, "terraform_type": TF_MAP[t], "live": n, "in_iac": tf.get(TF_MAP[t], 0)} for t, n in sorted(live_counts.items()) if t in TF_MAP]
    return {"k8s_live_only": live_only, "k8s_iac_only": iac_only, "images_live_not_in_iac": sorted(live_images - iac_images)[:100], "counts": counts}


def run(ctx: Ctx, runner: Runner | None = None) -> Result:
    provs = [p for p in ctx.settings.cloud_inventory if p]
    if not provs:
        return Result(coverage={"live cloud": "off (setting cloud_inventory is empty)"})
    runner = runner or default_runner(audit=lambda k, **kw: ctx.event(k, **kw))
    resources, problems = collect(provs, runner)
    facts = [make_fact("cloud_resource", f"{r['provider']}:{r['type']}:{r['attrs']['name']}", {"provider": r["provider"], "resource_type": r["type"], **r["attrs"]},
                       "OBSERVED", [ev(f"live:{r['provider']}", f"{r['type']} {r['attrs']['name']}", "read-only list/describe call")], "cloud_inventory") for r in resources]
    cmp = compare_with_iac(resources, ctx.facts)
    for k, n in (("live_only", len(cmp["k8s_live_only"])), ("iac_only", len(cmp["k8s_iac_only"]))):
        if n:
            facts.append(make_fact("iac_drift", f"kubernetes:{k}", {"direction": k, "count": n, "examples": [f"{a}/{b}" for a, b in cmp[f"k8s_{k}"][:10]]}, "DERIVED",
                                   [ev("live:kubernetes", k, f"{n} workload(s)")], "cloud_inventory", "exact (kind, name) comparison between live workloads and Kubernetes manifests found in the repositories"))
    by = defaultdict(list)
    for r in resources:
        by[(r["provider"], r["type"])].append(r)
    md = [header("Live cloud and Kubernetes inventory", ctx, "Read-only list/describe calls only. Addresses, hostnames and credentials are never recorded."),
          f"Providers requested: {', '.join(provs)}. {len(resources)} resource(s) read.\n"]
    if problems:
        md.append("## Could not read (UNKNOWN)\n")
        md += [f"- {p['provider']}{(' ' + p['type']) if p.get('type') else ''}: {p['reason']}" for p in problems]
    for (prov, rtype), rs in sorted(by.items()):
        md.append(f"\n## {prov}: {rtype} ({len(rs)})\n")
        md += [f"- `{md_cell(r['attrs']['name'])}`" + (" · " + ", ".join(f"{k}={md_cell(v)}" for k, v in r['attrs'].items() if k != 'name' and not isinstance(v, (list, dict)))[:150] if len(r['attrs']) > 1 else "") for r in sorted(rs, key=lambda x: x['attrs']['name'])[:200]]
    md.append("\n## Live vs repository (IaC / manifests)\n")
    md.append(f"- Kubernetes workloads running but not in any scanned manifest ({len(cmp['k8s_live_only'])}): " + (", ".join(f"`{a}/{b}`" for a, b in cmp["k8s_live_only"][:40]) or "none"))
    md.append(f"- Kubernetes workloads in manifests but not running ({len(cmp['k8s_iac_only'])}): " + (", ".join(f"`{a}/{b}`" for a, b in cmp["k8s_iac_only"][:40]) or "none"))
    md.append(f"- Running images not referenced by any scanned manifest: {len(cmp['images_live_not_in_iac'])}")
    if cmp["counts"]:
        md.append("\n| Resource | Terraform type | Live | In Terraform |\n|---|---|---|---|")
        md += [f"| {c['type']} | `{c['terraform_type']}` | {c['live']} | {c['in_iac']} |" for c in cmp["counts"]]
        md.append("\nTerraform is compared by *type count* only: resource names in code rarely equal live identifiers, so no name matching is attempted.")
    return Result(files={"live/index.md": "\n".join(md) + "\n"}, facts=facts, index=["- [Live cloud and Kubernetes inventory](live/index.md)"],
                  coverage={"live cloud": f"{len(resources)} resources from {', '.join(provs)}; {len(problems)} collector(s) could not read"})
