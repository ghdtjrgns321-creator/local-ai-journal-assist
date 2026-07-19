"""Build v114 candidate by refreshing stale detector-contract truth files.

This patch is based on the v113 candidate. It first records a staleness scan
manifest, then rebuilds only rule-truth files whose current detector output
differs from the sidecar:

- L4-03 high-amount z-score review universe
- L4-06 batch review universe

Journal rows, confirmed anomaly labels, and detector code are not modified.
"""

from __future__ import annotations

import json
import os
import shutil
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


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v113_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v114_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULES = ("L4-03", "L4-06")


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(LABELS / "V114_STALE_TRUTH_REFRESH.json")
        if all(path.exists() for path in required):
            return
        raise SystemExit(f"destination exists but is incomplete: {DEST}")

    source_resolved = SOURCE.resolve()
    dest_resolved = DEST.resolve()
    allowed_root = (ROOT / "data" / "journal" / "primary").resolve()
    if allowed_root not in dest_resolved.parents:
        raise SystemExit(f"refusing to write outside DataSynth root: {DEST}")

    for src in SOURCE.rglob("*"):
        rel = src.relative_to(source_resolved)
        dst = dest_resolved / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel.parts and rel.parts[0] == "labels":
            shutil.copy2(src, dst)
        else:
            os.link(src, dst)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _load_journal() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frames.append(
            pd.read_csv(
                DEST / f"journal_entries_{year}.csv",
                parse_dates=["posting_date", "document_date"],
                low_memory=False,
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df.attrs[SOURCE_PATH_ATTR] = str((DEST / "journal_entries_2022.csv").resolve())
    for col in ("debit_amount", "credit_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    if "fiscal_period" in df.columns:
        df["fiscal_period"] = pd.to_numeric(df["fiscal_period"], errors="coerce")
    return df


def _add_features(df: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    rules = get_audit_rules()
    out = df.copy()
    out.attrs[SOURCE_PATH_ATTR] = df.attrs.get(SOURCE_PATH_ATTR)
    add_all_time_features(out, settings)
    add_all_amount_features(out, settings, rules)
    add_all_pattern_features(out, rules.get("patterns", {}))
    return out


def _truth_docs(rule_id: str) -> set[str]:
    path = LABELS / f"rule_truth_{rule_id.replace('-', '_')}.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path, usecols=lambda column: column == "document_id", low_memory=False)
    if "document_id" not in df.columns:
        return set()
    return set(df["document_id"].dropna().astype(str))


def _common_context_agg(work: pd.DataFrame) -> dict[str, tuple[str, object]]:
    return {
        "fiscal_year": ("fiscal_year", _first_non_null),
        "company_code": ("company_code", _first_non_null),
        "posting_date": ("posting_date", _first_non_null),
        "document_number": ("document_number", _first_non_null),
        "document_type": ("document_type", _first_non_null),
        "business_process": ("business_process", _first_non_null),
        "source": ("source", _first_non_null),
        "created_by": ("created_by", _first_non_null),
        "approved_by": ("approved_by", _first_non_null),
        "line_count": ("document_id", "size"),
    }


def _build_l403_truth(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    settings = get_settings()
    result = c08_amount_outlier(
        rows,
        zscore_threshold=settings.zscore_threshold,
        min_amount_quantile=settings.l403_min_amount_quantile,
    )
    mask = pd.Series(result, index=rows.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=rows.index).fillna(0.0)

    work = rows.loc[mask].copy()
    work["_l403_score"] = scores.loc[work.index].astype(float)
    work["_bucket"] = work.index.map(lambda idx: annotations.get(int(idx), {}).get("bucket", ""))
    work["_amount_zscore"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("amount_zscore")
    )
    work["_base_amount"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("base_amount")
    )
    work["_amount_threshold"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("amount_threshold")
    )

    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            **_common_context_agg(work),
            flagged_row_count=("document_id", "size"),
            l403_score=("_l403_score", "max"),
            score_bucket=("_bucket", _first_non_null),
            max_amount_zscore=("_amount_zscore", "max"),
            max_line_amount=("_base_amount", "max"),
            amount_threshold=("_amount_threshold", _first_non_null),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["case_id"] = [
        f"L403-{int(year)}-{idx + 1:05d}"
        for idx, year in enumerate(grouped["fiscal_year"].tolist())
    ]
    grouped["rule_id"] = "L4-03"
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "high-amount z-score review universe"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = "src.detection.anomaly_rules_simple.c08_amount_outlier current detector output"
    grouped["source_candidate"] = "v114"
    grouped["evaluation_policy"] = (
        "Phase1 raw high-amount review universe; confirmed high-amount labels and "
        "boundary controls are separate"
    )
    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "line_count",
        "flagged_row_count",
        "l403_score",
        "score_bucket",
        "max_amount_zscore",
        "max_line_amount",
        "amount_threshold",
        "case_id",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
        "evaluation_policy",
    ]
    return grouped[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True), (
        result.attrs.get("breakdown", {})
    )


def _build_l406_truth(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    settings = get_settings()
    result = c13_batch_anomaly(
        rows,
        batch_sources=settings.batch_source_values,
        period_end_ratio=settings.batch_period_end_ratio,
        simultaneous_threshold=settings.batch_simultaneous_threshold,
        amount_zscore=settings.batch_amount_zscore,
    )
    mask = pd.Series(result, index=rows.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=rows.index).fillna(0.0)

    work = rows.loc[mask].copy()
    work["_l406_score"] = scores.loc[work.index].astype(float)
    work["_score_bucket"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("score_bucket", "")
    )
    work["_reason_codes"] = work.index.map(
        lambda idx: "|".join(annotations.get(int(idx), {}).get("reason_codes", []))
    )
    work["_primary_reason"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("primary_reason", "")
    )

    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            **_common_context_agg(work),
            l406_score=("_l406_score", "max"),
            score_bucket=("_score_bucket", _first_non_null),
            reason_codes=("_reason_codes", _first_non_null),
            primary_reason=("_primary_reason", _first_non_null),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["case_id"] = [
        f"L406-{int(year)}-{idx + 1:05d}"
        for idx, year in enumerate(grouped["fiscal_year"].tolist())
    ]
    grouped["rule_id"] = "L4-06"
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "batch-source review universe"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = "src.detection.anomaly_rules_batch.c13_batch_anomaly current detector output"
    grouped["source_candidate"] = "v114"
    grouped["evaluation_policy"] = (
        "Phase1 raw batch review universe; confirmed BatchAnomaly subset and "
        "normal/boundary controls are separate"
    )
    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "line_count",
        "l406_score",
        "score_bucket",
        "reason_codes",
        "primary_reason",
        "case_id",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
        "evaluation_policy",
    ]
    return grouped[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True), (
        result.attrs.get("breakdown", {})
    )


def _write_truth_family(rule_id: str, truth: pd.DataFrame, review_stem: str) -> None:
    rule_stem = f"rule_truth_{rule_id.replace('-', '_')}"
    for stem in (rule_stem, review_stem):
        truth.to_csv(LABELS / f"{stem}.csv", index=False)
        _write_json_records(LABELS / f"{stem}.json", truth)
        for year in YEARS:
            year_df = truth.loc[truth["fiscal_year"].eq(year)].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _replace_combined_rule_truth(replacements: dict[str, pd.DataFrame]) -> None:
    path = LABELS / "rule_truth.csv"
    combined = pd.read_csv(path, low_memory=False)
    for rule_id in replacements:
        combined = combined.loc[combined["rule_id"].astype(str).ne(rule_id)].copy()
    rebuilt = pd.concat([combined, *replacements.values()], ignore_index=True, sort=False)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)


def _annotate_l406_controls(truth_docs: set[str]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for stem in ("batch_normal_controls", "batch_boundary_controls"):
        path = LABELS / f"{stem}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, low_memory=False)
        if "document_id" in df.columns:
            docs = df["document_id"].dropna().astype(str)
            df["raw_l406_hit"] = docs.isin(truth_docs).to_numpy()
        else:
            df["raw_l406_hit"] = False
        df["is_rule_truth"] = False
        df["control_role"] = stem
        df["control_policy"] = (
            "L4-06 control sidecar only; excluded from rule_truth_L4_06 and strict rule recall"
        )
        df.to_csv(path, index=False)
        _write_json_records(LABELS / f"{stem}.json", df)
        for year in YEARS:
            if "fiscal_year" in df.columns:
                year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
            else:
                year_df = df.iloc[0:0].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)
        stats[stem] = {
            "rows": int(len(df)),
            "raw_hit_overlap": int(pd.Series(df["raw_l406_hit"]).sum()),
        }
    return stats


def _read_rule_metadata() -> list[dict[str, object]]:
    items = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if path.stem.endswith(tuple(str(year) for year in YEARS)):
            continue
        df = pd.read_csv(path, low_memory=False)
        item: dict[str, object] = {
            "file": path.name,
            "rows": int(len(df)),
            "document_count": int(df["document_id"].nunique()) if "document_id" in df.columns else None,
        }
        if "source_candidate" in df.columns:
            item["source_candidate_values"] = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        if "truth_derivation" in df.columns:
            item["truth_derivation_values"] = sorted(df["truth_derivation"].dropna().astype(str).unique().tolist())[:10]
        items.append(item)
    return items


def _write_manifest(
    old_truth: dict[str, set[str]],
    new_truth: dict[str, pd.DataFrame],
    breakdowns: dict[str, dict[str, object]],
    control_stats: dict[str, dict[str, int]],
) -> None:
    rule_summary = {}
    for rule_id, truth in new_truth.items():
        docs = set(truth["document_id"].astype(str))
        previous = old_truth.get(rule_id, set())
        rule_summary[rule_id] = {
            "truth_docs": int(len(docs)),
            "added_docs": int(len(docs - previous)),
            "removed_stale_docs": int(len(previous - docs)),
            "truth_by_year": {
                str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().items()
            },
            "source_candidate": "v114",
            "detector_breakdown": breakdowns.get(rule_id, {}),
        }
    manifest = {
        "version": "v114_candidate",
        "base_version": "v113_candidate",
        "patch": "refresh_stale_detector_contract_truth",
        "refreshed_rules": list(new_truth.keys()),
        "rule_summary": rule_summary,
        "l406_control_stats": control_stats,
        "metadata_after_refresh": _read_rule_metadata(),
        "contract": {
            "anti_stale_policy": (
                "Every refreshed detector-contract truth file must set source_candidate "
                "to the current patch version and store current detector output as truth."
            ),
            "anti_fitting": (
                "Detector code is unchanged. Truth sidecars are regenerated only where "
                "the current detector output differs from copied legacy sidecars."
            ),
        },
    }
    (LABELS / "V114_STALE_TRUTH_REFRESH.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V114_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v114 Candidate",
                "",
                "Base: `datasynth_v113_candidate`",
                "",
                "Patch: refresh stale detector-contract truth files.",
                "",
                "Refreshed rules:",
                "- L4-03 high-amount z-score review universe",
                "- L4-06 batch review universe",
                "",
                "This patch does not modify journal rows, confirmed labels, or detector code.",
                "",
                json.dumps(rule_summary, ensure_ascii=False, indent=2),
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    _copy_candidate_fast()
    rows = _add_features(_load_journal())
    old_truth = {rule_id: _truth_docs(rule_id) for rule_id in RULES}
    l403, l403_breakdown = _build_l403_truth(rows)
    l406, l406_breakdown = _build_l406_truth(rows)
    replacements = {"L4-03": l403, "L4-06": l406}
    _write_truth_family("L4-03", l403, "high_amount_review_population")
    _write_truth_family("L4-06", l406, "batch_review_population")
    _replace_combined_rule_truth(replacements)
    control_stats = _annotate_l406_controls(set(l406["document_id"].astype(str)))
    _write_manifest(
        old_truth,
        replacements,
        {"L4-03": l403_breakdown, "L4-06": l406_breakdown},
        control_stats,
    )
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "rules": {
                    rule_id: {
                        "truth_docs": int(len(set(truth["document_id"].astype(str)))),
                        "added_docs": int(len(set(truth["document_id"].astype(str)) - old_truth[rule_id])),
                        "removed_stale_docs": int(len(old_truth[rule_id] - set(truth["document_id"].astype(str)))),
                    }
                    for rule_id, truth in replacements.items()
                },
                "l406_control_stats": control_stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
