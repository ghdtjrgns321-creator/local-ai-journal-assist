"""Build v113 candidate by realigning L2-02 truth to duplicate-payment detector output.

L2-02 is a Phase 1 duplicate-payment screening rule. Its strict rule truth is
the raw duplicate-payment review universe produced by the detector. The
injected `DuplicatePayment` labels and `duplicate_payment_pairs` remain the
confirmed pair subset, not the exhaustive rule truth.
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

from config.settings import get_settings  # noqa: E402
from src.detection.fraud_rules_groupby import b04_duplicate_payment  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v112_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v113_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L2-02"


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(LABELS / "rule_truth_L2_02.csv")
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
    usecols = {
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "user_persona",
        "reference",
        "auxiliary_account_number",
        "trading_partner",
        "auxiliary_account_label",
        "vendor_name",
        "customer_name",
        "counterparty_code",
        "counterparty_name",
        "debit_amount",
        "credit_amount",
        "line_text",
        "header_text",
    }
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns
        cols = [column for column in header if column in usecols]
        frames.append(pd.read_csv(path, usecols=cols, parse_dates=["posting_date"], low_memory=False))
    return pd.concat(frames, ignore_index=True)


def _truth_from_detector(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    settings = get_settings()
    result = b04_duplicate_payment(
        df,
        window_days=settings.duplicate_payment_window_days,
    )
    mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=df.index).fillna(0.0)

    work = df.loc[mask].copy()
    work["_l202_score"] = scores.loc[work.index].astype(float)
    work["_reason_code"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("reason_code", "")
    )
    work["_confidence_band"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("confidence_band", "")
    )
    work["_matched_document_id"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("matched_document_id", "")
    )
    work["_partner_key"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("partner_key", "")
    )
    work["_reference_norm"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("reference_norm", "")
    )
    work["_matched_reference_norm"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("matched_reference_norm", "")
    )
    work["_amount"] = work.index.map(lambda idx: annotations.get(int(idx), {}).get("amount"))
    work["_matched_amount"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("matched_amount")
    )
    work["_day_gap"] = work.index.map(lambda idx: annotations.get(int(idx), {}).get("day_gap"))

    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            fiscal_year=("fiscal_year", _first_non_null),
            company_code=("company_code", _first_non_null),
            posting_date=("posting_date", _first_non_null),
            document_number=("document_number", _first_non_null),
            document_type=("document_type", _first_non_null),
            business_process=("business_process", _first_non_null),
            source=("source", _first_non_null),
            created_by=("created_by", _first_non_null),
            approved_by=("approved_by", _first_non_null),
            user_persona=("user_persona", _first_non_null),
            line_count=("document_id", "size"),
            l202_score=("_l202_score", "max"),
            reason_code=("_reason_code", _first_non_null),
            confidence_band=("_confidence_band", _first_non_null),
            matched_document_id=("_matched_document_id", _first_non_null),
            partner_key=("_partner_key", _first_non_null),
            reference_norm=("_reference_norm", _first_non_null),
            matched_reference_norm=("_matched_reference_norm", _first_non_null),
            amount=("_amount", _first_non_null),
            matched_amount=("_matched_amount", _first_non_null),
            day_gap=("_day_gap", _first_non_null),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["rule_id"] = RULE_ID
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "duplicate-payment review universe"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = "src.detection.fraud_rules_groupby.b04_duplicate_payment current detector output"
    grouped["source_candidate"] = "v113"
    grouped["evaluation_policy"] = (
        "Phase1 raw duplicate-payment review universe; confirmed DuplicatePayment "
        "labels and duplicate_payment_pairs are separate pair metadata"
    )
    grouped["case_id"] = [
        f"L202-{int(year)}-{idx + 1:05d}"
        for idx, year in enumerate(grouped["fiscal_year"].tolist())
    ]

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
        "user_persona",
        "line_count",
        "l202_score",
        "reason_code",
        "confidence_band",
        "matched_document_id",
        "partner_key",
        "reference_norm",
        "matched_reference_norm",
        "amount",
        "matched_amount",
        "day_gap",
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


def _write_truth_family(truth: pd.DataFrame) -> None:
    stems = ["rule_truth_L2_02", "duplicate_payment_review_population"]
    for stem in stems:
        truth.to_csv(LABELS / f"{stem}.csv", index=False)
        _write_json_records(LABELS / f"{stem}.json", truth)
        for year in YEARS:
            year_df = truth.loc[truth["fiscal_year"].eq(year)].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _replace_combined_rule_truth(truth: pd.DataFrame) -> None:
    path = LABELS / "rule_truth.csv"
    combined = pd.read_csv(path, low_memory=False)
    combined = combined.loc[combined["rule_id"].astype(str).ne(RULE_ID)].copy()
    rebuilt = pd.concat([combined, truth], ignore_index=True, sort=False)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)


def _annotate_pair_sidecars(truth_docs: set[str]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for stem in ("duplicate_payment_pairs", "duplicate_payment_negative_controls"):
        path = LABELS / f"{stem}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, low_memory=False)
        if "document_id" in df.columns:
            docs = df["document_id"].dropna().astype(str)
        elif "duplicate_document_id" in df.columns:
            docs = df["duplicate_document_id"].dropna().astype(str)
        else:
            docs = pd.Series([], dtype=str)
        df["is_rule_truth"] = False
        df["sidecar_role"] = "confirmed_pair_metadata" if stem == "duplicate_payment_pairs" else "negative_control"
        df["rule_truth_overlap"] = docs.isin(truth_docs).to_numpy() if len(docs) == len(df) else False
        df["evaluation_policy"] = (
            "Sidecar metadata only. Strict Phase1 L2-02 truth is "
            "duplicate_payment_review_population / rule_truth_L2_02."
        )
        df.to_csv(path, index=False)
        _write_json_records(LABELS / f"{stem}.json", df)
        stats[f"{stem}_rows"] = int(len(df))
        stats[f"{stem}_truth_overlap"] = int(pd.Series(df["rule_truth_overlap"]).sum())
        for year in YEARS:
            if "fiscal_year" in df.columns:
                year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
            else:
                year_df = df.iloc[0:0].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)
    return stats


def _read_docs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, usecols=lambda column: column == "document_id", low_memory=False)
    if "document_id" not in df.columns:
        return set()
    return set(df["document_id"].dropna().astype(str).unique())


def _write_manifest(
    truth: pd.DataFrame,
    breakdown: dict[str, object],
    previous_truth: set[str],
    pair_stats: dict[str, int],
) -> None:
    current_truth = set(truth["document_id"].astype(str))
    pair_docs = _read_docs(LABELS / "duplicate_payment_pairs.csv")
    label_docs = _read_docs_from_labels("DuplicatePayment")
    manifest = {
        "version": "v113_candidate",
        "base_version": "v112_candidate",
        "patch": "l202_truth_realign_to_duplicate_payment_detector_universe",
        "rule_id": RULE_ID,
        "truth_docs": int(len(current_truth)),
        "truth_by_year": {
            str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().items()
        },
        "truth_by_reason": {
            str(k): int(v) for k, v in truth["reason_code"].value_counts().items()
        },
        "truth_by_source": {
            str(k): int(v) for k, v in truth["source"].value_counts().sort_index().items()
        },
        "added_docs": int(len(current_truth - previous_truth)),
        "removed_stale_docs": int(len(previous_truth - current_truth)),
        "confirmed_pair_docs": int(len(pair_docs)),
        "confirmed_pair_docs_in_truth": int(len(pair_docs & current_truth)),
        "duplicate_payment_label_docs": int(len(label_docs)),
        "duplicate_payment_label_docs_in_truth": int(len(label_docs & current_truth)),
        "pair_sidecar_stats": pair_stats,
        "detector_breakdown": breakdown,
        "contract": {
            "rule_truth": "current L2-02 detector raw duplicate-payment review universe",
            "review_population": "same as rule_truth_L2_02",
            "confirmed_pairs": "duplicate_payment_pairs and DuplicatePayment labels are confirmed pair metadata only",
            "reason_bands": "reference_match, mixed_reference_fallback, blank_reference_fallback, amount_partner_fallback",
            "anti_fitting": (
                "Detector output is not changed. DataSynth truth is aligned to "
                "the Phase1 raw duplicate-payment screening contract."
            ),
        },
    }
    (LABELS / "V113_L202_TRUTH_REALIGNMENT.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V113_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v113 Candidate",
                "",
                "Base: `datasynth_v112_candidate`",
                "",
                "Patch: realign L2-02 rule truth to the current duplicate-payment detector universe.",
                "",
                "Contract:",
                "- `rule_truth_L2_02.csv` and `duplicate_payment_review_population.csv` are the raw L2-02 review universe.",
                "- `duplicate_payment_pairs.csv` and `DuplicatePayment` labels remain confirmed pair metadata.",
                "- Reason bands and scores decide priority; DataSynth truth does not collapse review candidates into confirmed fraud.",
                "",
                f"Truth documents: {len(current_truth):,}",
                f"Added documents: {len(current_truth - previous_truth):,}",
                f"Removed stale documents: {len(previous_truth - current_truth):,}",
                f"Confirmed pair docs in truth: {len(pair_docs & current_truth):,} / {len(pair_docs):,}",
                f"DuplicatePayment labels in truth: {len(label_docs & current_truth):,} / {len(label_docs):,}",
                "",
                "This patch does not modify journal entry rows, confirmed labels, or the detector.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _read_docs_from_labels(anomaly_type: str) -> set[str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path, usecols=["document_id", "anomaly_type"], low_memory=False)
    return set(
        df.loc[df["anomaly_type"].astype(str).eq(anomaly_type), "document_id"]
        .dropna()
        .astype(str)
        .unique()
    )


def main() -> int:
    _copy_candidate_fast()
    previous_truth = _read_docs(LABELS / "rule_truth_L2_02.csv")
    df = _load_journal()
    truth, breakdown = _truth_from_detector(df)
    _write_truth_family(truth)
    _replace_combined_rule_truth(truth)
    pair_stats = _annotate_pair_sidecars(set(truth["document_id"].astype(str)))
    _write_manifest(truth, breakdown, previous_truth, pair_stats)
    current_truth = set(truth["document_id"].astype(str))
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "truth_docs": int(len(current_truth)),
                "added_docs": int(len(current_truth - previous_truth)),
                "removed_stale_docs": int(len(previous_truth - current_truth)),
                "truth_by_year": {
                    str(k): int(v)
                    for k, v in truth["fiscal_year"].value_counts().sort_index().items()
                },
                "truth_by_reason": {
                    str(k): int(v) for k, v in truth["reason_code"].value_counts().items()
                },
                "truth_by_source": {
                    str(k): int(v) for k, v in truth["source"].value_counts().sort_index().items()
                },
                "detector_breakdown": breakdown,
                "pair_stats": pair_stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
