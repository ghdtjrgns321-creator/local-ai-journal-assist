"""Project-wide pytest fixtures."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import pytest

_SAFE_TMP_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
ROOT = Path(__file__).resolve().parents[1]
NORMAL_SAMPLE_300_PATH = ROOT / "data/journal/test_normal_sample/normal_sample_300.csv"


def _safe_tmp_name(nodeid: str) -> str:
    safe = _SAFE_TMP_NAME.sub("_", nodeid).strip("._")
    digest = hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:8]
    return f"{safe[:80]}_{digest}"


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    """Use a workspace-local temp path without pytest's Windows 0o700 basetemp."""
    configured = getattr(request.config.option, "basetemp", None)
    base = Path(configured) if configured else Path(".tmp_pytest_workspace")
    if not base.is_absolute():
        base = Path(request.config.rootpath) / base
    try:
        (base / "tmp_path").mkdir(parents=True, exist_ok=True)
    except PermissionError:
        base = base.with_name(f"{base.name}_local")
    path = base / "tmp_path" / _safe_tmp_name(request.node.nodeid)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def normal_sample_300_path() -> Path:
    """Fixed normal-operation sample used by the PHASE1 A4 false-positive guard."""
    if not NORMAL_SAMPLE_300_PATH.exists():
        pytest.skip(f"normal sample fixture missing: {NORMAL_SAMPLE_300_PATH.relative_to(ROOT)}")
    return NORMAL_SAMPLE_300_PATH


@pytest.fixture(scope="session")
def normal_sample_300(normal_sample_300_path: Path):
    """Load the fixed A4 sample and require PHASE1 risk annotations."""
    import pandas as pd

    df = pd.read_csv(normal_sample_300_path)
    if "risk_level" not in df.columns:
        pytest.skip("normal sample fixture has no risk_level column")
    return df
