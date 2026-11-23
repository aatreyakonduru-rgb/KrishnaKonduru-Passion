"""Throwaway extractor: dbt ref()/source() calls -> Metis *.links.yaml with line-exact [E: ...] tags.

Regex based, like the Metis 1.2.5 tools. Used only to feed the Metis pipeline in the sandbox.
"""
import os
import re
import sys

import yaml

REPO = "jaffle-shop"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "repos", REPO)
REF = re.compile(r"\{\{\s*ref\('([^']+)'\)\s*\}\}")
SRC = re.compile(r"\{\{\s*source\('([^']+)',\s*'([^']+)'\)\s*\}\}")


def main(out):
    links = []
    for layer in ("staging", "marts"):
        d = os.path.join(ROOT, "models", layer)
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".sql"):
                continue
            model = fn[:-4]
            rel = "%s/models/%s/%s" % (REPO, layer, fn)
            with open(os.path.join(d, fn), encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    for m in REF.finditer(line):
                        links.append({
                            "from": {"type": "dbt_model", "name": model},
                            "rel": "reads",
                            "to": {"type": "dbt_model", "name": m.group(1)},
                            "source": '[E: %s:%d "%s"]' % (rel, n, m.group(1)),
                        })
                    for m in SRC.finditer(line):
                        links.append({
                            "from": {"type": "dbt_model", "name": model},
                            "rel": "reads",
                            "to": {"type": "source_table", "name": m.group(2)},
                            "source": '[E: %s:%d "%s"]' % (rel, n, m.group(2)),
                        })
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"links": links}, fh, sort_keys=False, width=200)
    print("wrote %d links to %s" % (len(links), out))


if __name__ == "__main__":
    main(sys.argv[1])
