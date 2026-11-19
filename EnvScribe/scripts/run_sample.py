"""Run the whole pipeline against the sample project (no network)."""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scribe.orchestrator import Run
from scribe.settings import Settings

root = Path(__file__).resolve().parent.parent
out = root / "envscribe-out-sample"
shutil.rmtree(out, ignore_errors=True)
s = Settings(output_dir=str(out), sources=[str(root / "sample" / "payments-api")], upload_dir=str(root / "sample" / "uploads"),
             max_workers=4, token_budget=0)
run = Run(s, known_secrets=["Sup3rS3cretUat99"])
state = run.execute()
print(json.dumps({k: state[k] for k in ("status", "stages", "counters", "gate", "zip", "as_of")}, indent=2, default=str))
print("blocking:", json.dumps(state["sweeps"]["blocking"][:5], default=str) if state.get("sweeps") else None)
