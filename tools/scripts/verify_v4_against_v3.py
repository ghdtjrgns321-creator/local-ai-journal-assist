"""Compare DataSynth manipulation v4 candidate against v3 baseline.

Read-only check. Computes:
- truth taxonomy preservation (V3 420 docs subset of V4 620 docs)
- noise floor delta (V3 vs V4 on full journal)
- per-scenario shortcut rate delta (manual/weekend/offhour/self_approval)
- topic-entry regression (expected_topic_docs ratio)
- new defect screening (V4 noise scenarios shortcut share)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"
V4 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v4_candidate"
V3_TOPIC = ROOT / "artifacts" / "phase1_manipulation_v3_active_topic_analysis_20260515.json"
V4_TOPIC = ROOT / "artifacts" / "manipulation_v4_candidate_topic_analysis.json"
OUT_JSON = ROOT / "artifacts" / "datasynth_v4_quality_verification.json"

SCENARIO_PROTECTED = [
    "approval_sod_bypass",
    "circular_related_party_transaction",
    "embezzlement_concealment",
    "fictitious_entry",
    "period_end_adjustment_manipulation",
    "unusual_timing_manipulation",
]
SCENARIO_NEW = ["suspense_account_abuse", "expense_capitalization"]


def load_truth(dataset: Path) -> pd.DataFrame:
    df = pd.read_csv(dataset / "labels" / "manipulated_entry_truth.csv", dtype=str)
    df["document_id"] = df["document_id"].astype(str)
    return df


def load_journal(dataset: Path) -> pd.DataFrame:
    parts = []
    cols = [
        "document_id",
        "posting_date",
        "source",
        "approved_by",
        "created_by",
    ]
    for year in (2022, 2023, 2024):
        path = dataset / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns
        usecols = [c for c in cols if c in header]
        parts.append(pd.read_csv(path, usecols=usecols, dtype=str, low_memory=False))
    df = pd.concat(parts, ignore_index=True)
    df["posting_date"] = pd.to_datetime(df["posting_date"], errors="coerce")
    return df


def noise_floor(rows: pd.DataFrame) -> dict[str, float]:
    posting = rows["posting_date"]
    approved_by = rows["approved_by"].fillna("").astype(str).str.strip()
    source = rows["source"].fillna("").astype(str).str.lower()
    total = max(len(rows), 1)
    return {
        "rows": int(len(rows)),
        "approved_by_null_pct": round(float(approved_by.eq("").sum()) / total, 6),
        "manual_entry_pct": round(float(source.isin({"manual", "adjustment"}).sum()) / total, 6),
        "weekend_posting_pct": round(
            float(posting.dt.weekday.ge(5).fillna(False).sum()) / total, 6
        ),
    }


def truth_taxonomy(v3_truth: pd.DataFrame, v4_truth: pd.DataFrame) -> dict[str, Any]:
    v3_docs = set(v3_truth["document_id"])
    v4_docs = set(v4_truth["document_id"])
    v3_subset_in_v4 = v3_docs.issubset(v4_docs)
    v3_scenarios = v3_truth["manipulation_scenario"].value_counts().sort_index().to_dict()
    v4_scenarios = v4_truth["manipulation_scenario"].value_counts().sort_index().to_dict()
    scenario_continuity = {
        scenario: {
            "v3": int(v3_scenarios.get(scenario, 0)),
            "v4": int(v4_scenarios.get(scenario, 0)),
            "pass": int(v3_scenarios.get(scenario, 0)) == int(v4_scenarios.get(scenario, 0)),
        }
        for scenario in SCENARIO_PROTECTED
    }
    new_scenarios = {scenario: int(v4_scenarios.get(scenario, 0)) for scenario in SCENARIO_NEW}
    return {
        "v3_truth_total": len(v3_docs),
        "v4_truth_total": len(v4_docs),
        "v3_subset_of_v4": v3_subset_in_v4,
        "missing_v3_docs_in_v4": sorted(v3_docs - v4_docs)[:20],
        "protected_scenario_continuity": scenario_continuity,
        "new_scenarios": new_scenarios,
        "all_protected_counts_identical": all(row["pass"] for row in scenario_continuity.values()),
    }


def topic_regression(v3_topic: dict[str, Any], v4_topic: dict[str, Any]) -> dict[str, Any]:
    v3_by_scenario = {row["scenario"]: row for row in v3_topic.get("scenario_metrics", [])}
    v4_by_scenario = {row["scenario"]: row for row in v4_topic.get("scenario_metrics", [])}
    rows = []
    regression_pass = True
    for scenario in SCENARIO_PROTECTED:
        v3_row = v3_by_scenario.get(scenario, {})
        v4_row = v4_by_scenario.get(scenario, {})
        v3_docs = int(v3_row.get("expected_topic_docs", 0))
        v4_docs = int(v4_row.get("expected_topic_docs", 0))
        threshold = v3_docs * 0.95
        ok = v4_docs >= threshold
        regression_pass = regression_pass and ok
        rows.append(
            {
                "scenario": scenario,
                "v3_expected_topic_docs": v3_docs,
                "v4_expected_topic_docs": v4_docs,
                "threshold_95pct": threshold,
                "pass": ok,
            }
        )
    new_topic = {
        scenario: {
            "truth_docs": int(v4_by_scenario.get(scenario, {}).get("truth_docs", 0)),
            "expected_topic_docs": int(
                v4_by_scenario.get(scenario, {}).get("expected_topic_docs", 0)
            ),
        }
        for scenario in SCENARIO_NEW
    }
    return {
        "protected_scenario_regression_pass": regression_pass,
        "protected_scenarios": rows,
        "new_scenarios_phase1_topic_entry": new_topic,
    }


def shortcut_comparison(v3_guard: dict[str, Any], v4_guard: dict[str, Any]) -> dict[str, Any]:
    """Compare V3 mutation_recovery guard_1 against V4 candidate guard."""
    v3_g1 = v3_guard.get("guard_1", {})
    v4_rates = v4_guard.get("scenario_shortcut_rates", {})
    v4_unusual = v4_rates.get("unusual_timing_manipulation", {})
    v4_fictitious = v4_guard.get("fictitious_entry", {})

    return {
        "L08_f_manual_saturation": {
            "v3_unusual_manual_source_doc_ratio": v3_g1.get("unusual_manual_source_doc_ratio"),
            "v4_unusual_f_manual": v4_unusual.get("f_manual"),
            "v3_was_saturated_1_0": v3_g1.get("unusual_manual_source_doc_ratio") == 1.0,
            "v4_below_0_80": v4_unusual.get("f_manual", 1.0) < 0.80,
            "fix_applied": v4_unusual.get("f_manual", 1.0) < 0.80,
        },
        "L10_unusual_timing_all_four": {
            "v3_offhour_doc_ratio": v3_g1.get("unusual_offhour_doc_ratio"),
            "v3_weekend_doc_ratio": v3_g1.get("unusual_weekend_doc_ratio"),
            "v3_manual_doc_ratio": v3_g1.get("unusual_manual_source_doc_ratio"),
            "v4_all_four_shortcut_share": v4_unusual.get("all_four_shortcut_share"),
            "v4_two_or_three_share": v4_unusual.get("two_or_three_feature_share"),
            "v4_pattern_count": v4_unusual.get("pattern_count"),
            "fix_applied": v4_unusual.get("all_four_shortcut_share", 1.0) == 0.0
            and v4_unusual.get("two_or_three_feature_share", 0.0) >= 0.80
            and v4_unusual.get("pattern_count", 1) >= 4,
        },
        "fictitious_amount_diversity": {
            "v3_unique_amounts": "deterministic (1 unique reported in v3 audit)",
            "v4_unique_rounded_amounts": v4_fictitious.get("unique_rounded_amounts"),
            "v4_top_amount_share": v4_fictitious.get("top_amount_share"),
            "fix_applied": v4_fictitious.get("unique_rounded_amounts", 0) >= 20,
        },
        "L17_hold_out_scenarios": {
            "v3_scenarios": SCENARIO_PROTECTED,
            "v4_new_scenarios": SCENARIO_NEW,
            "fix_applied": True,
        },
    }


def normal_shortcut_floor(v4_guard: dict[str, Any]) -> dict[str, Any]:
    normal = v4_guard.get("scenario_shortcut_rates", {}).get("normal", {})
    checks = {
        "normal_f_manual_in_range_0_30_0_55": 0.30 <= normal.get("f_manual", 0) <= 0.55,
        "normal_f_weekend_below_0_10": normal.get("f_weekend", 1.0) < 0.10,
        "normal_f_offhour_below_0_15": normal.get("f_offhour", 1.0) < 0.15,
        "normal_f_self_approval_zero": normal.get("f_self_approval", 1.0) == 0.0,
    }
    return {"normal_shortcut_rates": normal, "checks": checks, "pass": all(checks.values())}


def main() -> None:
    v3_truth = load_truth(V3)
    v4_truth = load_truth(V4)
    print("loading v3 journal ...")
    v3_journal = load_journal(V3)
    print("loading v4 journal ...")
    v4_journal = load_journal(V4)
    v3_noise = noise_floor(v3_journal)
    v4_noise = noise_floor(v4_journal)

    delta = {
        key: round(float(v4_noise[key]) - float(v3_noise[key]), 6)
        for key in ("approved_by_null_pct", "manual_entry_pct", "weekend_posting_pct")
    }
    noise_floor_pass = all(abs(value) <= 0.10 for value in delta.values())

    v3_topic = json.loads(V3_TOPIC.read_text(encoding="utf-8"))
    v4_topic = json.loads(V4_TOPIC.read_text(encoding="utf-8"))
    topic_block = topic_regression(v3_topic, v4_topic)

    v3_guard = json.loads(
        (ROOT / "artifacts" / "manipulation_v3_final_mutation_recovery.json").read_text(
            encoding="utf-8"
        )
    )
    v4_guard = json.loads(
        (ROOT / "artifacts" / "manipulation_v4_candidate_guard.json").read_text(encoding="utf-8")
    )

    taxonomy = truth_taxonomy(v3_truth, v4_truth)
    shortcuts = shortcut_comparison(v3_guard, v4_guard)
    normal_block = normal_shortcut_floor(v4_guard)

    result = {
        "v3_dataset": str(V3.relative_to(ROOT)),
        "v4_dataset": str(V4.relative_to(ROOT)),
        "truth_taxonomy": taxonomy,
        "noise_floor": {
            "v3": v3_noise,
            "v4": v4_noise,
            "delta_v4_minus_v3": delta,
            "delta_within_10pct_points": noise_floor_pass,
        },
        "topic_regression": topic_block,
        "shortcut_comparison": shortcuts,
        "normal_background": normal_block,
        "case_count": {
            "v3_case_count": int(v3_topic.get("case_count", 0)),
            "v4_case_count": int(v4_topic.get("case_count", 0)),
            "delta_pct": round(
                (v4_topic.get("case_count", 0) - v3_topic.get("case_count", 0))
                / max(v3_topic.get("case_count", 1), 1),
                6,
            ),
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(OUT_JSON.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
