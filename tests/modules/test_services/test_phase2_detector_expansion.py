from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.detection.base import DetectionResult
from src.services.phase2_leaderboard import build_leaderboard_payload
from src.services.phase2_promotion_policy import build_promotion_decision_payload
from src.services.phase2_training_models import Phase2TrainingStatus
from src.services.phase2_training_service import (
    _DEFAULT_DETECTOR_FACTORIES,
    _DEFAULT_MODEL_FAMILIES,
    _DEFAULT_SEARCH_PRESETS,
    _FAMILY_TO_CANONICAL_MODEL,
    _PROMOTED_TRACK_MAP,
    run_phase2_training,
)

RULE_FAMILIES = ("timeseries", "relational", "duplicate", "intercompany")
ACTIVE_FAMILIES = ("unsupervised", *RULE_FAMILIES)
RULE_METRICS = {
    "timeseries": "burst_detection_rate",
    "relational": "new_counterparty_precision",
    "duplicate": "fuzzy_match_f1",
    "intercompany": "ic_match_completeness",
}


def _make_local_temp_dir() -> Path:
    root = Path("tests") / ".tmp_phase2_detector_expansion"
    root.mkdir(parents=True, exist_ok=True)
    target = root / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=True)
    return target


class _FakeRuleDetector:
    track = "rule"

    def __init__(self, *, settings=None, model_registry=None, **kwargs):
        self._settings = settings
        self._registry = model_registry

    @property
    def track_name(self) -> str:
        return self.track

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        scores = pd.Series([0.9, 0.0, 0.7, 0.0][: len(df)], index=df.index)
        return DetectionResult(
            track_name=self.track_name,
            flagged_indices=scores[scores > 0].index.tolist(),
            scores=scores,
            rule_flags=[],
            details=pd.DataFrame({self.track_name: scores}, index=df.index),
            metadata={"elapsed": 0.01},
            warnings=[],
        )


class _FakeTimeseries(_FakeRuleDetector):
    track = "timeseries"


class _FakeRelational(_FakeRuleDetector):
    track = "relational"


class _FakeDuplicate(_FakeRuleDetector):
    track = "duplicate"


class _FakeIntercompany(_FakeRuleDetector):
    track = "intercompany"


def _training_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["D1", "D2", "D3", "D4"],
            "created_by": ["u1", "u2", "u1", "u3"],
            "posting_date": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]
            ),
            "posting_time": ["09:00", "10:00", "11:00", "12:00"],
            "auxiliary_account_number": ["A1", "A1", "A2", "A2"],
            "trading_partner": ["TP1", "TP2", "TP1", "TP3"],
            "gl_account": ["4000", "5000", "1150", "2050"],
            "debit_amount": [100.0, 0.0, 300.0, 0.0],
            "credit_amount": [0.0, 100.0, 0.0, 300.0],
            "line_text": ["invoice a", "invoice b", "invoice a copy", "settlement"],
            "is_intercompany": [False, False, True, True],
            "amount": [100.0, 100.0, 300.0, 300.0],
        }
    )


def test_a3_family_registration_maps_include_nine_families_and_five_active_defaults():
    all_families = {
        "unsupervised",
        "supervised",
        "transformer",
        "sequence",
        "timeseries",
        "relational",
        "duplicate",
        "intercompany",
        "stacking",
    }

    assert set(_DEFAULT_DETECTOR_FACTORIES) == all_families
    assert set(_FAMILY_TO_CANONICAL_MODEL) == all_families
    assert set(_DEFAULT_SEARCH_PRESETS) == all_families
    assert set(_DEFAULT_MODEL_FAMILIES) == set(ACTIVE_FAMILIES)
    assert _PROMOTED_TRACK_MAP["timeseries"] == "timeseries"
    assert _PROMOTED_TRACK_MAP["relational"] == "relational"
    assert _PROMOTED_TRACK_MAP["duplicate"] == "duplicate"
    assert _PROMOTED_TRACK_MAP["intercompany"] == "intercompany"


def test_rule_based_families_end_to_end_leaderboard_promotion_and_inference_contract():
    root = _make_local_temp_dir()
    try:
        ctx = SimpleNamespace(
            company_id="acme",
            engagement_id="2026",
            model_dir=root / "companies" / "acme" / "engagements" / "2026" / "models",
        )

        report = run_phase2_training(
            _training_df(),
            ctx=ctx,
            model_families=RULE_FAMILIES,
            detector_factories={
                "timeseries": _FakeTimeseries,
                "relational": _FakeRelational,
                "duplicate": _FakeDuplicate,
                "intercompany": _FakeIntercompany,
            },
            base_dir=root / "phase2_train",
        )

        leaderboard = build_leaderboard_payload(report)
        promotion = build_promotion_decision_payload(report)
        contract = report.metadata["inference_contract"]

        assert report.status == Phase2TrainingStatus.COMPLETED
        assert {row["family"] for row in leaderboard["rows"]} == set(RULE_FAMILIES)
        for family in RULE_FAMILIES:
            rows = [row for row in leaderboard["rows"] if row["family"] == family]
            assert len(rows) == 2
            assert {row["variant"].split("__", maxsplit=1)[0] for row in rows} == {"baseline_core"}
            assert {row["schema_hash"] for row in rows} == {None}
            assert {row["metric"]["name"] for row in rows} == {RULE_METRICS[family]}
            assert {row["metadata"]["metric_interpretation"] for row in rows} == {
                "rule_proxy_score"
            }
            assert promotion["family_decisions"][family]["eligible_for_promotion"] is True
            assert family in contract["required_models"]
            assert contract["model_versions"][family]["schema_hash"] is None
            assert contract["model_versions"][family]["model_version"] is None
            assert contract["track_map"][family] == family

            artifact_path = Path(contract["model_versions"][family]["registry_path"])
            assert artifact_path.name == "calibration_metadata.json"
            assert artifact_path.parent.name == "v0001"
            assert artifact_path.parent.parent.name == f"phase2_{family}"
            metadata = json.loads(artifact_path.read_text(encoding="utf-8"))
            assert metadata["family"] == family
            assert metadata["schema_hash"] is None
            assert metadata["model_bundle"] is None
    finally:
        shutil.rmtree(root, ignore_errors=True)
