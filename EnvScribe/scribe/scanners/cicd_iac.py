"""CI/CD and IaC scanner: Jenkinsfile, Bitbucket Pipelines, GitHub Actions, GitLab CI, Bamboo specs, Dockerfile,
docker-compose, Kubernetes manifests, Helm, Kustomize, Terraform, CloudFormation."""
from __future__ import annotations

import re

import yaml

from ..facts import ev, make_fact


def classify(rel: str) -> str | None:
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    if name == "jenkinsfile" or name.startswith("jenkinsfile."):
        return "jenkins"
    if name == "bitbucket-pipelines.yml":
        return "bitbucket-pipelines"
    if "/.github/workflows/" in "/" + low and low.endswith((".yml", ".yaml")):
        return "github-actions"
    if name == ".gitlab-ci.yml":
        return "gitlab-ci"
    if name in ("bamboo.yml", "bamboo.yaml") or "bamboo-specs" in low:
        return "bamboo"
    if name == "dockerfile" or name.endswith(".dockerfile") or name.startswith("dockerfile."):
        return "dockerfile"
    if name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        return "compose"
    if name in ("chart.yaml",):
        return "helm-chart"
    if name == "kustomization.yaml" or name == "kustomization.yml":
        return "kustomize"
    if low.endswith(".tf"):
        return "terraform"
    if low.endswith((".yml", ".yaml", ".json")) and any(k in low for k in ("k8s", "kubernetes", "manifests", "deploy", "helm", "charts/", "templates/", "cloudformation", "cfn")):
        return "k8s-or-cfn"
    return None


def _ln(text: str, needle: str) -> int:
    i = text.find(needle)
    return text.count("\n", 0, i) + 1 if i >= 0 else 1


def scan_cicd_iac(repo: str, rel: str, text: str) -> list[dict]:
    kind = classify(rel)
    if not kind:
        return []
    src = f"{repo}/{rel}"
    out: list[dict] = []

    def add(k, subject, attrs, needle):
        attrs = {**attrs, "repo": repo, "path": rel}
        out.append(make_fact(k, subject, attrs, "OBSERVED", [ev(src, f"L{_ln(text, needle)}", needle[:120])], "cicd_iac"))

    try:
        if kind == "jenkins":
            for m in re.finditer(r"""stage\s*\(\s*['"]([^'"]+)['"]""", text):
                add("pipeline_stage", f"jenkins:{rel}:{m.group(1)}", {"system": "jenkins", "stage": m.group(1)}, m.group(0))
            for m in re.finditer(r"""(?:deploy|kubectl|helm|terraform|ansible-playbook)[^\n]{0,120}""", text):
                add("deploy_command", f"jenkins:{rel}", {"system": "jenkins", "command": m.group(0)[:120]}, m.group(0))
        elif kind in ("bitbucket-pipelines", "github-actions", "gitlab-ci", "bamboo"):
            doc = yaml.safe_load(text) or {}
            if kind == "bitbucket-pipelines":
                def walk(node, path):
                    if isinstance(node, dict):
                        if "step" in node and isinstance(node["step"], dict):
                            st = node["step"]
                            add("pipeline_stage", f"bitbucket:{rel}:{path}:{st.get('name', 'step')}", {
                                "system": "bitbucket-pipelines", "stage": st.get("name", "step"), "trigger": path,
                                "deployment": st.get("deployment"), "image": st.get("image")}, str(st.get("name", "step")))
                        for k, v in node.items():
                            walk(v, f"{path}/{k}" if path else str(k))
                    elif isinstance(node, list):
                        for v in node:
                            walk(v, path)
                walk(doc.get("pipelines") or {}, "")
            elif kind == "github-actions":
                for jid, job in (doc.get("jobs") or {}).items():
                    add("pipeline_stage", f"github:{rel}:{jid}", {"system": "github-actions", "stage": jid, "environment": (job or {}).get("environment"),
                                                                 "runs_on": (job or {}).get("runs-on")}, jid)
            elif kind == "gitlab-ci":
                for k, v in doc.items():
                    if isinstance(v, dict) and ("script" in v or "stage" in v):
                        env = v.get("environment")
                        add("pipeline_stage", f"gitlab:{rel}:{k}", {"system": "gitlab-ci", "stage": v.get("stage", k),
                                                                   "environment": env.get("name") if isinstance(env, dict) else env}, k)
            else:
                add("pipeline_stage", f"bamboo:{rel}", {"system": "bamboo", "keys": sorted(map(str, doc.keys()))[:20]}, next(iter(map(str, doc.keys())), ""))
        elif kind == "dockerfile":
            for m in re.finditer(r"(?im)^\s*FROM\s+(\S+)(?:\s+AS\s+(\S+))?", text):
                add("container_image", f"docker:{m.group(1)}", {"image": m.group(1), "stage_alias": m.group(2)}, m.group(0).strip())
            for m in re.finditer(r"(?im)^\s*(EXPOSE)\s+(.+)$", text):
                add("container_port", f"{repo}:{rel}", {"ports": m.group(2).split()}, m.group(0).strip())
            for m in re.finditer(r"(?im)^\s*(ENTRYPOINT|CMD)\s+(.+)$", text):
                add("container_command", f"{repo}:{rel}", {"instruction": m.group(1).upper(), "command": m.group(2)[:150]}, m.group(0).strip())
        elif kind == "compose":
            doc = yaml.safe_load(text) or {}
            for name, svc in (doc.get("services") or {}).items():
                svc = svc or {}
                add("service_definition", f"compose:{rel}:{name}", {"service": name, "image": svc.get("image"), "ports": svc.get("ports"),
                                                                  "depends_on": list(svc.get("depends_on") or []) if not isinstance(svc.get("depends_on"), dict) else list(svc["depends_on"])}, f"{name}:")
        elif kind == "terraform":
            for m in re.finditer(r'(?m)^\s*(resource|data|module|variable|provider)\s+"([^"]+)"(?:\s+"([^"]+)")?', text):
                add("iac_resource", f"terraform:{m.group(1)}:{m.group(2)}:{m.group(3) or ''}", {"block": m.group(1), "type": m.group(2), "name": m.group(3)}, m.group(0).strip())
        elif kind in ("helm-chart", "kustomize", "k8s-or-cfn"):
            if "{{" in text and kind == "k8s-or-cfn":
                text_for_yaml = re.sub(r"\{\{[^}]*\}\}", "TEMPLATE", text)
            else:
                text_for_yaml = text
            for doc in yaml.safe_load_all(text_for_yaml):
                if not isinstance(doc, dict):
                    continue
                if kind == "helm-chart":
                    add("helm_chart", f"helm:{doc.get('name')}", {"name": doc.get("name"), "version": doc.get("version"),
                                                                 "dependencies": [d.get("name") for d in doc.get("dependencies", []) if isinstance(d, dict)]}, "name:")
                elif "kind" in doc and "apiVersion" in doc:
                    meta = doc.get("metadata") or {}
                    spec = doc.get("spec") or {}
                    attrs = {"kind": doc["kind"], "name": meta.get("name"), "namespace": meta.get("namespace"), "replicas": spec.get("replicas")}
                    containers = (((spec.get("template") or {}).get("spec") or {}).get("containers")) or []
                    attrs["images"] = [c.get("image") for c in containers if isinstance(c, dict)]
                    attrs["ports"] = [p.get("containerPort") for c in containers if isinstance(c, dict) for p in (c.get("ports") or []) if isinstance(p, dict)]
                    add("k8s_resource", f"k8s:{doc['kind']}:{meta.get('name')}", attrs, f"kind: {doc['kind']}")
                elif "Resources" in doc:
                    for rname, r in (doc["Resources"] or {}).items():
                        add("iac_resource", f"cfn:{rname}", {"type": (r or {}).get("Type"), "name": rname}, rname)
    except yaml.YAMLError:
        out.append(make_fact("unparsed", src, {"reason": "yaml did not parse", "repo": repo, "path": rel}, "UNKNOWN", [ev(src, "L1")], "cicd_iac"))
    return out
