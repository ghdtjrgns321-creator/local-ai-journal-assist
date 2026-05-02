"""Build v102 candidate by cleaning legacy L1 sidecar semantics.

This patch does not change journal rows, anomaly labels, or rule_truth. It only
clarifies sidecar meaning where older names implied a narrower/older policy.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v101_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v102_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_sidecar(df: pd.DataFrame, name: str) -> None:
    path = LABELS / name
    df.to_csv(path, index=False)
    _write_json_records(path.with_suffix(".json"), df)


def _read(name: str) -> pd.DataFrame:
    path = LABELS / name
    return pd.read_csv(path, low_memory=False) if path.exists() else pd.DataFrame()


def _patch_skipped_approval_controls() -> dict[str, int]:
    """Rename legacy normal controls as system/control-gap rule-truth context."""
    out: dict[str, int] = {}
    for suffix in ["", "_2022", "_2023", "_2024"]:
        legacy = f"skipped_approval_normal_controls{suffix}.csv"
        df = _read(legacy)
        if df.empty and not (LABELS / legacy).exists():
            continue
        df["legacy_sidecar_name"] = legacy
        df["sidecar_semantics"] = "l107_rule_truth_system_or_control_gap_context"
        df["expected_l107_rule_truth"] = True
        df["expected_l109_rule_truth"] = True
        df["not_a_normal_control_reason"] = (
            "approved_by and approval_date are missing; current L1 policy treats this as rule truth"
        )
        df["audit_issue_subset"] = False
        _write_sidecar(df, legacy)
        new_name = f"skipped_approval_system_gap_controls{suffix}.csv"
        _write_sidecar(df, new_name)
        out[new_name] = len(df)
    return out


def _patch_wrongperiod_negative_controls() -> dict[str, int]:
    """Mark legacy negative controls as non-audit L1-08 rule truth context."""
    out: dict[str, int] = {}
    for suffix in ["", "_2022", "_2023", "_2024"]:
        legacy = f"wrongperiod_negative_controls{suffix}.csv"
        df = _read(legacy)
        if df.empty and not (LABELS / legacy).exists():
            continue
        df["legacy_sidecar_name"] = legacy
        df["sidecar_semantics"] = "l108_rule_truth_but_not_injected_anomaly_label"
        df["expected_l108_rule_truth"] = True
        df["not_a_negative_control_reason"] = (
            "fiscal_period differs from posting month; current L1 policy treats this as rule truth"
        )
        if "anomaly_label_expected" not in df.columns:
            df["anomaly_label_expected"] = False
        _write_sidecar(df, legacy)
        new_name = f"wrong_period_non_audit_issue_truth{suffix}.csv"
        _write_sidecar(df, new_name)
        out[new_name] = len(df)
    return out


def _patch_sod_review_population() -> dict[str, int]:
    """Separate broad SoD review signals from direct L1-06 violation truth."""
    out: dict[str, int] = {}
    for suffix in ["", "_2022", "_2023", "_2024"]:
        name = f"sod_review_population{suffix}.csv"
        df = _read(name)
        if df.empty and not (LABELS / name).exists():
            continue
        if "was_sod_violation" in df.columns:
            df["legacy_was_sod_violation"] = df["was_sod_violation"]
            df["was_sod_violation"] = False
        df["sod_review_signal"] = True
        df["expected_l106_flag"] = False
        df["sidecar_semantics"] = "broad_sod_review_signal_not_l106_direct_truth"
        df["not_l106_reason"] = (
            "review-only SoD signal; direct conflict truth is stored in sod_confirmed_anomalies/rule_truth_L1_06"
        )
        _write_sidecar(df, name)
        out[name] = len(df)
    return out


def _write_manifest(
    skipped_counts: dict[str, int],
    wrongperiod_counts: dict[str, int],
    sod_counts: dict[str, int],
) -> None:
    manifest = {
        "version": "v102_candidate",
        "base_version": "v101_candidate",
        "patch": "l1_sidecar_semantics_cleanup",
        "journal_rows_mutated": 0,
        "rule_truth_mutated": False,
        "anomaly_labels_mutated": False,
        "changes": {
            "skipped_approval": {
                "legacy_file_kept_for_gate_compatibility": "skipped_approval_normal_controls*.csv",
                "new_semantic_alias": "skipped_approval_system_gap_controls*.csv",
                "counts": skipped_counts,
            },
            "wrong_period": {
                "legacy_file_kept_for_traceability": "wrongperiod_negative_controls*.csv",
                "new_semantic_alias": "wrong_period_non_audit_issue_truth*.csv",
                "counts": wrongperiod_counts,
            },
            "sod_review": {
                "updated": "sod_review_population*.csv",
                "counts": sod_counts,
                "semantic_change": "was_sod_violation=False; sod_review_signal=True",
            },
        },
    }
    (LABELS / "V102_L1_SIDECAR_SEMANTICS.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V102_CANDIDATE.md").write_text(
        "# DataSynth v102 Candidate\n\n"
        "Base: `datasynth_v101_candidate`.\n\n"
        "Patch: L1 sidecar semantics cleanup. No journal, anomaly-label, or rule-truth mutation.\n\n"
        f"```json\n{json.dumps(manifest, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    skipped_counts = _patch_skipped_approval_controls()
    wrongperiod_counts = _patch_wrongperiod_negative_controls()
    sod_counts = _patch_sod_review_population()
    _write_manifest(skipped_counts, wrongperiod_counts, sod_counts)
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "skipped_alias_rows": skipped_counts,
                "wrongperiod_alias_rows": wrongperiod_counts,
                "sod_review_rows": sod_counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
