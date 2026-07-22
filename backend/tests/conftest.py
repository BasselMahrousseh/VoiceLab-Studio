"""Test env must be configured before app modules are imported."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="voicelab_test_"))
os.environ["DATA_DIR"] = str(_tmp / "data")
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
# Ignore any real .env so tests don't pick up live LLM/ASR credentials.
os.environ["LAHJA_ENV_FILE"] = str(_tmp / "nonexistent.env")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
