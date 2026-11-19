import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SECRET = "Sup3rS3cretUat99"


@pytest.fixture()
def sample_run(tmp_path):
    from scribe.orchestrator import Run
    from scribe.settings import Settings
    src = tmp_path / "src"
    shutil.copytree(ROOT / "sample" / "payments-api", src / "payments-api")
    up = tmp_path / "uploads"
    shutil.copytree(ROOT / "sample" / "uploads", up)
    s = Settings(output_dir=str(tmp_path / "out"), sources=[str(src / "payments-api")], upload_dir=str(up), max_workers=3)
    return Run(s, known_secrets=[SECRET]), tmp_path
