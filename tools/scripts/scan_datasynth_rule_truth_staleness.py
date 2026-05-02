"""Scan DataSynth rule-truth files for stale metadata and selected detector diffs.

This script is intentionally conservative. It does not mutate data. It gives a
fast metadata view for all `rule_truth_*` sidecars and, when requested, reruns
selected detector contracts that have historically drifted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.anomaly_rules_batch import c13_batch_anomaly  # noqa: E402
from src.detection.anomaly_rules_simple import c08_amount_outlier  # noqa: E402
from src.feature.amount_features import add_all_amount_features  # noqa: E402
from src.feature.pattern_features import add_all_pattern_features  # noqa: E402
from src.feature.time_features import add_all_time_features  # noqa: E402
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR  # noqa: E402


YEARS = (2022, 2023, 2024)
DETECTOR_RULES = {"L4-03", "L4-06"}


def _read_truth_metadata(path: Path) -> dict[str, object]:
    df = pd.read_csv(path, low_memory=False)
    item: dict[str, object] = {
        "file": str(path.name),
        "rows": int(len(df)),
        "document_count": int(df["document_id"].nunique()) if "document_id" in df.columns else None,
        "source_candidate_values": [],
        "truth_derivation_values": [],
        "evaluation_policy_values": [],
    }
    for column, key in (
        ("source_candidate", "source_candidate_values"),
        ("truth_derivation", "truth_derivation_values"),
        ("evaluation_policy", "evaluation_policy_values"),
    ):
        if column in df.columns:
            values = sorted(df[column].dropna().astype(str).unique().tolist())
            item[key] = values[:20]
            if len(values) > 20:
                item[f"{key}_truncated"] = len(values)
    return item


def _load_journal(dataset: Path) -> pd.DataFrame:
    frames = []
    for year in YEARS:
        path = dataset / f"journal_entries_{year}.csv"
        frames.append(
            pd.read_csv(
                path,
                parse_dates=["posting_date", "document_date"],
                low_memory=False,
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df.attrs[SOURCE_PATH_ATTR] = str((dataset / "journal_entries_2022.csv").resolve())
    for col in ("debit_amount", "credit_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    if "fiscal_period" in df.columns:
        df["fiscal_period"] = pd.to_numeric(df["fiscal_period"], errors="coerce")
    return df


def _feature_rows(df: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    rules = get_audit_rules()
    out = df.copy()
    out.attrs[SOURCE_PATH_ATTR] = df.attrs.get(SOURCE_PATH_ATTR)
    add_all_time_features(out, settings)
    add_all_amount_features(out, settings, rules)
    add_all_pattern_features(out, rules.get("patterns", {}))
    return out


def _detector_docs(rule_id: str, rows: pd.DataFrame) -> tuple[set[str], dict[str, object]]:
    settings = get_settings()
    if rule_id == "L4-03":
        result = c08_amount_outlier(
            rows,
            zscore_threshold=settings.zscore_threshold,
            min_amount_quantile=settings.l403_min_amount_quantile,
        )
    elif rule_id == "L4-06":
        result = c13_batch_anomaly(
            rows,
            batch_sources=settings.batch_source_values,
            period_end_ratio=settings.batch_period_end_ratio,
            simultaneous_threshold=settings.batch_simultaneous_threshold,
            amount_zscore=settings.batch_amount_zscore,
        )
    else:
        raise ValueError(f"unsupported detector diff rule: {rule_id}")
    mask = pd.Series(result, index=rows.index).fillna(False).astype(bool)
    docs = set(rows.loc[mask, "document_id"].dropna().astype(str))
    return docs, result.attrs.get("breakdown", {})


def _truth_docs(dataset: Path, rule_id: str) -> set[str]:
    path = dataset / "labels" / f"rule_truth_{rule_id.replace('-', '_')}.csv"
    df = pd.read_csv(path, usecols=lambda column: column == "document_id", low_memory=False)
    if "document_id" not in df.columns:
        return set()
    return set(df["document_id"].dropna().astype(str))


def scan(dataset: Path, detector_diff: bool) -> dict[str, object]:
    labels = dataset / "labels"
    metadata = []
    for path in sorted(labels.glob("rule_truth_*.csv")):
        if path.stem.endswith(tuple(str(year) for year in YEARS)):
            continue
        metadata.append(_read_truth_metadata(path))

    result: dict[str, object] = {
        "dataset": str(dataset),
        "metadata": metadata,
    }
    if detector_diff:
        rows = _feature_rows(_load_journal(dataset))
        diffs = {}
        for rule_id in sorted(DETECTOR_RULES):
            detector, breakdown = _detector_docs(rule_id, rows)
            truth = _truth_docs(dataset, rule_id)
            diffs[rule_id] = {
                "detector_docs": int(len(detector)),
                "truth_docs": int(len(truth)),
                "detector_minus_truth": int(len(detector - truth)),
                "truth_minus_detector": int(len(truth - detector)),
                "breakdown": breakdown,
            }
        result["detector_diffs"] = diffs
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--detector-diff", action="store_true")
    args = parser.parse_args()
    dataset = args.dataset
    if not dataset.exists():
        raise SystemExit(f"dataset not found: {dataset}")
    print(json.dumps(scan(dataset, args.detector_diff), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
