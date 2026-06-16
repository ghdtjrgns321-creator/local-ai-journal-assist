from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.json"
)


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_duplicate_s0_operating_kpi_reports_normal_fp_and_recall_band():
    kpi = _payload()["duplicate_s0_operating_kpi"]

    assert kpi["measurement_policy"] == "normal_fp_first_recall_as_confidence_band"
    assert kpi["truth_used_for_selector_or_gate"] is False
    assert kpi["normal_false_positive_rate"]["dataset"] == "normal_sample_300"
    assert kpi["normal_false_positive_rate"]["case_unit"] == "native_duplicate_case"
    assert kpi["normal_false_positive_rate"]["normal_documents"] == 300
    assert kpi["normal_false_positive_rate"]["false_positive_cases"] >= 0
    assert 0.0 <= kpi["normal_false_positive_rate"]["false_positive_rate"] <= 1.0

    band = kpi["recall_confidence_band"]
    assert band["family"] == "duplicate"
    assert band["topn"] == 500
    assert band["matched_docs"] == 8
    assert band["denominator_docs"] == 19
    assert band["one_doc_pct_points"] == 5.263158
    assert band["minus_one_doc"]["matched_docs"] == 7
    assert band["plus_one_doc"]["matched_docs"] == 9
    assert band["interpretation"] == (
        "n=19 small denominator; do not optimize single recall point estimates"
    )
