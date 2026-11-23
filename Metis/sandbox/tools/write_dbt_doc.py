"""Writes the dbt lineage doc from the model files (so every line carries a real line number)."""
import os
import re
import sys

R = "jaffle-shop"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "repos", R)
REF = re.compile(r"\{\{\s*(ref|source)\(([^)]*)\)\s*\}\}")
out = sys.argv[1]
lines = ["# Jaffle Shop dbt models", "", "## Model dependencies", ""]
for layer in ("staging", "marts"):
    d = os.path.join(ROOT, "models", layer)
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".sql"):
            continue
        rel = "%s/models/%s/%s" % (R, layer, fn)
        with open(os.path.join(d, fn), encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                for m in REF.finditer(line):
                    arg = m.group(2).replace("'", "").replace(" ", "")
                    target = arg.split(",")[-1]
                    lines.append('%s model `%s` reads `%s`. [E: %s:%d "%s"]' % (layer, fn[:-4], target, rel, n, target))
                    lines.append("")
lines += ["## Materialization", "",
          'Staging models are built as views. [E: jaffle-shop/dbt_project.yml:33 "+materialized: view"]', "",
          'Marts models are built as tables. [E: jaffle-shop/dbt_project.yml:35 "+materialized: table"]', "",
          "## Open questions", "",
          "Who owns the raw schema that feeds the source tables? [?: Q-0002]", ""]
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))
print("ok")
