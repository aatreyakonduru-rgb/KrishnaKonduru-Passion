"""Import smoke test: every feature module must import and expose run()."""
import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import scribe.features as f  # noqa: E402
import scribe.orchestrator  # noqa: E402,F401

for name, mod, _ in f.FEATURES:
    assert callable(getattr(mod, "run", None)), name
importlib.import_module("scribe.features.impact")
importlib.import_module("scribe.features.semantic")
print("ok", f.FEATURE_NAMES)
