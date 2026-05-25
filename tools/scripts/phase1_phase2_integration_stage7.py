"""Stage 7 — PHASE1↔PHASE2 통합 review queue 생성 (Sequential).

PHASE1 priority_score 비파괴 + PHASE2 5-family score overlay.
composite_sort_score V1 lock 준수. Phase 3 Narrator 입력 계약 점검 포함.
"""
# ruff: noqa: E402

from __future__ import annotations

import io
import json
import pickle
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.phase1_case_builder import build_phase1_case_result
from src.llm.review_narrator.candidate_builder import build_candidates
from src.preprocessing.feature_quality import apply_feature_quality_policy
from src.preprocessing.vae_model import AuditVAE
from src.services.phase2_case_contract import (
    build_phase2_case_overlays,
    classify_phase12_review_band,
)
from src.services.queue_fusion import (
    K_DEFAULT as RRF_K,
)
from src.services.queue_fusion import (
    compute_phase2_internal_noisy_or,
    compute_rrf_score,
    to_ecdf,
)
from src.services.review_band_policy import rank_percentile_band

PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"
BUNDLE_PATH = (
    ROOT
    / "data"
    / "companies"
    / "_ci_baseline"
    / "engagements"
    / "2026"
    / "models"
    / "phase2_unsupervised"
    / "v1"
    / "model_bundle.pt"
)
INFERENCE_REPORT_PATH = ROOT / "artifacts" / "phase2_inference_report_v7_fixed3_2026-05-17.json"
TRAINING_REPORT_PATH = (
    ROOT
    / "data"
    / "companies"
    / "_ci_baseline"
    / "engagements"
    / "2026"
    / "models"
    / "phase2_unsupervised"
    / "v1"
    / "training_report.json"
)
TRUTH_PATH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed3"
    / "labels"
    / "manipulated_entry_truth.csv"
)
REVIEW_QUEUE_DIR = (
    ROOT / "data" / "companies" / "_ci_baseline" / "engagements" / "2026" / "review_queue" / "v1"
)
QUEUE_PATH = REVIEW_QUEUE_DIR / "queue.parquet"
QUEUE_TOP500_PATH = REVIEW_QUEUE_DIR / "queue_top500.parquet"
QUEUE_TOP100_PATH = REVIEW_QUEUE_DIR / "queue_top100.parquet"
# 3큐 분리 (TS-12 §6.1 / D058) — RRF k=60 통합 + PHASE1·PHASE2 단독.
QUEUE_PHASE1_PATH = REVIEW_QUEUE_DIR / "queue_phase1.parquet"
QUEUE_PHASE2_PATH = REVIEW_QUEUE_DIR / "queue_phase2.parquet"
QUEUE_INTEGRATED_PATH = REVIEW_QUEUE_DIR / "queue_integrated.parquet"
QUEUE_PHASE1_TOP500_PATH = REVIEW_QUEUE_DIR / "queue_phase1_top500.parquet"
QUEUE_PHASE2_TOP500_PATH = REVIEW_QUEUE_DIR / "queue_phase2_top500.parquet"
QUEUE_INTEGRATED_TOP500_PATH = REVIEW_QUEUE_DIR / "queue_integrated_top500.parquet"
INTEGRATION_REPORT_JSON = (
    ROOT / "artifacts" / "phase1_phase2_integration_report_noisy_or_20260519.json"
)
INTEGRATION_REPORT_MD = ROOT / "artifacts" / "phase1_phase2_integration_report_noisy_or_20260519.md"

PHASE2_FAMILIES = ("unsupervised", "timeseries", "relational", "duplicate", "intercompany")
PHASE2_FAMILY_SCORE_MAX_COLUMNS = {
    family: f"phase2_{family}_score_max" for family in PHASE2_FAMILIES
}
PHASE2_FAMILY_SCORE_MEAN_COLUMNS = {
    family: f"phase2_{family}_score_mean" for family in PHASE2_FAMILIES
}
PHASE2_FAMILY_CACHE = ROOT / "artifacts" / "stage7_phase2_family_by_doc.parquet"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _print(msg: str) -> None:
    print(f"[{_now_iso()}] {msg}", flush=True)


def load_inputs() -> tuple[pd.DataFrame, list[Any], pd.DataFrame, dict[str, Any]]:
    _print(f"loading PKL: {_rel(PKL_PATH)}")
    with PKL_PATH.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    detection_results = data["results"]
    _print(f"  df rows={len(df):,} results={len(detection_results)}")
    truth = pd.read_csv(TRUTH_PATH)
    _print(f"  truth docs={len(truth):,}")
    _print(f"loading PHASE2 bundle: {_rel(BUNDLE_PATH)}")
    bundle = pickle.loads(BUNDLE_PATH.read_bytes())
    return df, detection_results, truth, bundle


def score_phase2(df: pd.DataFrame, bundle: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    """PHASE2 row-level inference: raw recon + ECDF score (pd.Series indexed by df.index)."""
    builder = bundle["matrix_builder"]
    post_scaler = bundle["post_scaler"]
    ecdf_train_sorted = bundle["ecdf_train_sorted"]
    cleaned_df, _, _ = apply_feature_quality_policy(df, for_training=False)
    matrix = builder.transform(cleaned_df)
    arr_raw = np.nan_to_num(
        matrix.to_numpy(dtype=np.float32),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    arr = post_scaler.transform(arr_raw).astype(np.float32)
    arr = np.clip(
        np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0),
        -10.0,
        10.0,
    ).astype(np.float32)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AuditVAE(bundle["input_dim"], bundle["latent_dim"], bundle["hidden_dim"]).to(device)
    state = torch.load(io.BytesIO(bundle["model_state_dict"]), weights_only=True)
    model.load_state_dict(state)
    model.eval()
    raw_chunks: list[np.ndarray] = []
    with torch.no_grad():
        tensor = torch.from_numpy(arr)
        for start in range(0, len(tensor), 2048):
            chunk = tensor[start : start + 2048].to(device)
            recon, _, _ = model(chunk)
            raw_chunks.append(((recon - chunk) ** 2).mean(dim=1).cpu().numpy())
    raw_scores = np.concatenate(raw_chunks, axis=0)
    ecdf_scores = np.searchsorted(ecdf_train_sorted, raw_scores) / max(len(ecdf_train_sorted), 1)
    return (
        pd.Series(raw_scores, index=cleaned_df.index, name="phase2_recon_raw"),
        pd.Series(ecdf_scores, index=cleaned_df.index, name="phase2_unsupervised_selection_score"),
    )


def aggregate_phase2_by_document(
    phase2_scores: pd.Series | pd.DataFrame,
    df_doc_id: pd.Series,
) -> pd.DataFrame:
    """document_id별 PHASE2 5-family max + mean aggregation."""
    if isinstance(phase2_scores, pd.Series):
        score_frame = pd.DataFrame({"unsupervised": phase2_scores})
    else:
        score_frame = phase2_scores.copy()
    score_frame = score_frame.reindex(columns=list(PHASE2_FAMILIES))
    frame = score_frame.copy()
    frame["document_id"] = df_doc_id.loc[score_frame.index].astype(str).to_numpy()

    agg_spec: dict[str, tuple[str, str]] = {}
    for family in PHASE2_FAMILIES:
        agg_spec[PHASE2_FAMILY_SCORE_MAX_COLUMNS[family]] = (family, "max")
        agg_spec[PHASE2_FAMILY_SCORE_MEAN_COLUMNS[family]] = (family, "mean")
    out = frame.groupby("document_id", as_index=False).agg(**agg_spec)
    out["phase2_row_count"] = frame.groupby("document_id").size().to_numpy()
    return _ensure_phase2_family_columns(out)


def score_phase2_families_by_document(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute PHASE2 5-family row scores and aggregate to document max/mean."""
    from tools.scripts.phase2_family_correlation_audit import score_all_families

    row_scores = score_all_families(df)
    return aggregate_phase2_by_document(row_scores[list(PHASE2_FAMILIES)], df["document_id"])


def _ensure_phase2_family_columns(phase2_by_doc: pd.DataFrame) -> pd.DataFrame:
    out = phase2_by_doc.copy()
    if "phase2_unsupervised_score_max" not in out and "phase2_unsupervised_selection_score" in out:
        out["phase2_unsupervised_score_max"] = out["phase2_unsupervised_selection_score"]
    if "phase2_unsupervised_score_mean" not in out and "phase2_score_mean" in out:
        out["phase2_unsupervised_score_mean"] = out["phase2_score_mean"]
    for family in PHASE2_FAMILIES:
        max_col = PHASE2_FAMILY_SCORE_MAX_COLUMNS[family]
        mean_col = PHASE2_FAMILY_SCORE_MEAN_COLUMNS[family]
        if max_col not in out:
            out[max_col] = np.nan
        if mean_col not in out:
            out[mean_col] = np.nan
    # Backward-compatible aliases used by older dashboard/tests.
    out["phase2_unsupervised_selection_score"] = out["phase2_unsupervised_score_max"]
    out["phase2_score_mean"] = out["phase2_unsupervised_score_mean"]
    return out


def build_case_overlay_payload(
    phase1_result: Any,
    phase2_by_doc: pd.DataFrame,
    inference_contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    """case별 PHASE2 family_scores + ECDF + q95 임계 구성 → build_phase2_case_overlays.

    D062 (2026-05-21): phase2_review_band 가 의미있게 채워지도록 max_family_ecdf 와
    coverage_breadth_q95 도 함께 계산해서 overlay 에 전달한다. sub-detector 정보가 없는
    측정 스크립트 한계로 family_top_subdetectors_by_case 는 비어 있고, 그 결과
    max_evidence_tier 도 None 이다 (Stage7 측정에서는 review 분기 중 ``ml_quantile_tail_
    with_coverage`` 만 작동). dashboard/실제 파이프라인 (sub-detector 정보 보유) 에서는
    strong/moderate tier 도 채워진다.
    """

    phase2_by_doc = _ensure_phase2_family_columns(phase2_by_doc)
    family_doc_scores = _build_family_doc_score_maps(phase2_by_doc)
    family_scores_by_case: dict[str, dict[str, float]] = {}
    for case in phase1_result.cases:
        doc_ids = [str(doc.document_id) for doc in case.documents]
        case_scores: dict[str, float] = {}
        for family in PHASE2_FAMILIES:
            doc_score = family_doc_scores[family]
            values = [doc_score[d] for d in doc_ids if d in doc_score and np.isfinite(doc_score[d])]
            if values:
                key = "ml_unsupervised" if family == "unsupervised" else family
                case_scores[key] = float(max(values))
        if case_scores:
            family_scores_by_case[case.case_id] = case_scores

    family_q95_thresholds = _build_family_q95_thresholds(family_scores_by_case)
    family_ecdf_by_case = _build_family_ecdf_by_case(family_scores_by_case)
    family_roles = {
        "ml_unsupervised": "active",
        "timeseries": "active",
        "relational": "active",
        "duplicate": "active",
        "intercompany": "active",
    }

    overlays = build_phase2_case_overlays(
        phase1=phase1_result,
        family_scores_by_case=family_scores_by_case,
        family_ecdf_by_case=family_ecdf_by_case,
        family_roles=family_roles,
        family_q95_thresholds=family_q95_thresholds,
        detector_statuses=[
            {"family": "ml_unsupervised", "status": "applied", "model_version": "v1"},
            {"family": "timeseries", "status": "applied", "model_version": "rule_style"},
            {"family": "relational", "status": "applied", "model_version": "rule_style"},
            {"family": "duplicate", "status": "applied", "model_version": "rule_style"},
            {"family": "intercompany", "status": "applied", "model_version": "rule_style"},
        ],
        phase2_inference_contract=inference_contract,
        phase2_training_report_id="v7_fixed3_first_training_v1",
    )
    return overlays, family_scores_by_case


def _build_family_q95_thresholds(
    family_scores_by_case: dict[str, dict[str, float]],
) -> dict[str, float]:
    """family 별 양수 score 의 q95 임계. coverage_breadth_q95 계산용.

    무신호 (0 또는 NaN) 는 제외하고 양수 score 만으로 q95 계산. zero-preserving
    ECDF 정신 정합. case 가 없거나 양수 신호가 없으면 inf 로 (해당 family 가
    coverage_breadth 계산에서 자동 제외).
    """

    family_values: dict[str, list[float]] = {}
    for case_id, scores in family_scores_by_case.items():
        for family, score in scores.items():
            try:
                value = float(score)
            except (TypeError, ValueError):
                continue
            if value > 0 and np.isfinite(value):
                family_values.setdefault(family, []).append(value)
    thresholds: dict[str, float] = {}
    for family, values in family_values.items():
        if not values:
            thresholds[family] = float("inf")
            continue
        thresholds[family] = float(np.quantile(values, 0.95))
    return thresholds


def _build_family_ecdf_by_case(
    family_scores_by_case: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """case 별 family ECDF. 양수 분포 내 percentile (zero-preserving ECDF 정합).

    무신호 (0 또는 NaN) 인 case 의 family 는 ECDF=0. 양수 score 의 분포 내에서
    rank/N percentile 로 매핑한다.
    """

    family_positive_scores: dict[str, list[float]] = {}
    for scores in family_scores_by_case.values():
        for family, score in scores.items():
            try:
                value = float(score)
            except (TypeError, ValueError):
                continue
            if value > 0 and np.isfinite(value):
                family_positive_scores.setdefault(family, []).append(value)
    family_sorted: dict[str, np.ndarray] = {
        family: np.sort(np.array(values, dtype=np.float64))
        for family, values in family_positive_scores.items()
    }

    result: dict[str, dict[str, float]] = {}
    for case_id, scores in family_scores_by_case.items():
        case_ecdf: dict[str, float] = {}
        for family, score in scores.items():
            try:
                value = float(score)
            except (TypeError, ValueError):
                continue
            if not (value > 0 and np.isfinite(value)):
                case_ecdf[family] = 0.0
                continue
            sorted_arr = family_sorted.get(family)
            if sorted_arr is None or len(sorted_arr) == 0:
                case_ecdf[family] = 0.0
                continue
            rank = int(np.searchsorted(sorted_arr, value, side="right"))
            case_ecdf[family] = rank / len(sorted_arr)
        if case_ecdf:
            result[case_id] = case_ecdf
    return result


def assert_priority_score_preserved(
    phase1_result: Any,
    snapshot: dict[str, float],
) -> dict[str, Any]:
    """옵션 Z lock HARD: case priority_score 원본 100% 보존 (diff == 0)."""
    mismatches: list[dict[str, Any]] = []
    for case in phase1_result.cases:
        before = snapshot.get(case.case_id)
        if before is None:
            continue
        if abs(before - float(case.priority_score)) > 1e-12:
            mismatches.append(
                {
                    "case_id": case.case_id,
                    "before": before,
                    "after": float(case.priority_score),
                    "diff": float(case.priority_score) - before,
                }
            )
    return {
        "preserved": len(mismatches) == 0,
        "mismatch_count": len(mismatches),
        "mismatches_sample": mismatches[:5],
        "case_count": len(phase1_result.cases),
    }


# D062: PHASE1 priority_band → review_band 매핑. PHASE1 의 high/medium/low 는
# subdetector_tiers 의 immediate/review/candidate 와 의미가 같다.
_PHASE1_BAND_TO_REVIEW_BAND: dict[str, str] = {
    "high": "immediate",
    "medium": "review",
    "low": "candidate",
}


def _phase1_band_to_review_band(priority_band: str | None) -> str:
    """PHASE1 priority_band 를 D062 review_band 로 매핑.

    PHASE1 case 는 항상 priority_band 가 있으므로 candidate 이상이 기본이며 none 은 없다.
    빈 값이 들어오면 candidate 로 fallback.
    """

    key = (priority_band or "").strip().lower()
    return _PHASE1_BAND_TO_REVIEW_BAND.get(key, "candidate")


def _build_base_rows(
    phase1_result: Any,
    phase2_by_doc: pd.DataFrame,
    overlays: list[dict[str, Any]],
    truth_docs: set[str],
) -> pd.DataFrame:
    """case-level base DataFrame (정렬·rank 미적용)."""
    phase2_by_doc = _ensure_phase2_family_columns(phase2_by_doc)
    family_doc_scores = _build_family_doc_score_maps(phase2_by_doc)
    overlay_by_case = {o["phase1_case_id"]: o for o in overlays}
    rows: list[dict[str, Any]] = []
    for case in phase1_result.cases:
        case_doc_ids = [str(d.document_id) for d in case.documents]
        family_max: dict[str, float | None] = {}
        family_mean: dict[str, float | None] = {}
        for family in PHASE2_FAMILIES:
            doc_score = family_doc_scores[family]
            values = [
                doc_score[d] for d in case_doc_ids if d in doc_score and np.isfinite(doc_score[d])
            ]
            family_max[family] = float(max(values)) if values else None
            family_mean[family] = float(np.mean(values)) if values else None
        truth_match = any(d in truth_docs for d in case_doc_ids)
        overlay = overlay_by_case.get(case.case_id, {})
        primary_doc_id = case_doc_ids[0] if case_doc_ids else ""
        # D062: PHASE1 priority_band (high/medium/low) → review_band (immediate/review/candidate)
        phase1_review_band = _phase1_band_to_review_band(case.priority_band)
        phase2_review_band = str(overlay.get("phase2_review_band") or "none")
        phase12_review_band = classify_phase12_review_band(phase1_review_band, phase2_review_band)
        row = {
            "case_id": case.case_id,
            "primary_topic": case.primary_topic,
            "primary_theme": case.primary_theme,
            "primary_queue": case.primary_queue,
            "exposure_rank": case.exposure_rank,
            "phase1_priority_score": float(case.priority_score),
            "phase1_base_priority_score": float(case.base_priority_score),
            "phase1_composite_sort_score": float(case.composite_sort_score),
            "phase1_triage_rank_score": float(case.triage_rank_score),
            "phase1_priority_band": case.priority_band,
            "phase1_review_band": phase1_review_band,
            "phase2_review_band": phase2_review_band,
            "phase12_review_band": phase12_review_band,
            "phase2_unsupervised_selection_score_max": family_max["unsupervised"],
            "phase2_unsupervised_selection_score_mean": family_mean["unsupervised"],
            "phase2_adjusted_priority": overlay.get("phase2_adjusted_priority"),
            "phase2_precision_adjustment_reason": overlay.get("precision_adjustment_reason"),
            "rule_count": int(case.rule_count),
            "document_count": int(case.document_count),
            "row_count": int(case.row_count),
            "total_amount": float(case.total_amount),
            "first_posting_date": case.first_posting_date,
            "last_posting_date": case.last_posting_date,
            "primary_document_id": primary_doc_id,
            "document_ids_joined": ";".join(case_doc_ids),
            "case_contains_truth_doc": truth_match,
        }
        for family in PHASE2_FAMILIES:
            row[PHASE2_FAMILY_SCORE_MAX_COLUMNS[family]] = family_max[family]
            row[PHASE2_FAMILY_SCORE_MEAN_COLUMNS[family]] = family_mean[family]
        rows.append(row)
    return pd.DataFrame(rows)


def _build_family_doc_score_maps(phase2_by_doc: pd.DataFrame) -> dict[str, dict[str, float]]:
    doc_ids = phase2_by_doc["document_id"].astype(str).to_numpy()
    maps: dict[str, dict[str, float]] = {}
    for family in PHASE2_FAMILIES:
        values = pd.to_numeric(
            phase2_by_doc[PHASE2_FAMILY_SCORE_MAX_COLUMNS[family]],
            errors="coerce",
        ).to_numpy(dtype=np.float64)
        maps[family] = dict(zip(doc_ids, values, strict=False))
    return maps


def build_phase1_queue(base_df: pd.DataFrame) -> pd.DataFrame:
    """PHASE1 단독 큐 — composite_sort_score V1 lock 정렬 (기존 queue.parquet 와 동치)."""
    queue_df = base_df.sort_values(
        by=[
            "phase1_composite_sort_score",
            "phase1_triage_rank_score",
            "total_amount",
            "rule_count",
        ],
        ascending=False,
        kind="mergesort",
    ).reset_index(drop=True)
    queue_df.insert(0, "review_rank", queue_df.index + 1)
    return queue_df


def build_phase2_queue(base_df: pd.DataFrame) -> pd.DataFrame:
    """PHASE2 단독 큐 — 5-family Noisy-OR voter 정렬."""
    queue_df = (
        _attach_phase2_noisy_or_score(base_df)
        .sort_values(
            by=[
                "phase2_internal_noisy_or_score",
                "total_amount",
                "rule_count",
            ],
            ascending=False,
            kind="mergesort",
            na_position="last",
        )
        .reset_index(drop=True)
    )
    queue_df.insert(0, "phase2_review_rank", queue_df.index + 1)
    total_cases = len(queue_df)
    queue_df["phase2_review_band"] = [
        rank_percentile_band(rank, total_cases) for rank in queue_df["phase2_review_rank"]
    ]
    return queue_df


def build_phase2_family_queue(base_df: pd.DataFrame, family: str) -> pd.DataFrame:
    """PHASE2 family 단독 큐 — canonical case-level measurement.

    Why: fixed5 baseline의 ``family_single[*].phase2``는 document raw score 정렬이
    아니라 PHASE1 case 단위 base row를 family max score로 정렬한 값이다. TS/IC
    후속 측정 스크립트가 doc-level helper를 복붙하면서 같은 이름의 metric이
    바뀌었으므로, family 단독 recall은 반드시 이 함수로만 측정한다.
    """
    if family not in PHASE2_FAMILIES:
        raise ValueError(f"unknown phase2 family: {family}")
    base_df = _ensure_base_phase2_columns(base_df)
    score_col = PHASE2_FAMILY_SCORE_MAX_COLUMNS[family]
    queue_df = (
        base_df.sort_values(
            by=[score_col, "total_amount", "rule_count"],
            ascending=False,
            kind="mergesort",
            na_position="last",
        )
        .reset_index(drop=True)
        .copy()
    )
    queue_df.insert(0, "phase2_family_review_rank", queue_df.index + 1)
    queue_df["phase2_family"] = family
    return queue_df


def measure_phase2_family_single_recall(
    base_df: pd.DataFrame,
    truth_docs: set[str],
    top_ns: Iterable[int],
) -> dict[str, dict[str, dict[str, float | int]]]:
    """Canonical ``family_single`` recall table for fixed5/future reruns.

    Output shape intentionally matches
    ``artifacts/phase1_phase2_integration_fixed5_normalcal5_20260524.json``:

        family_single[family]["phase2"][str(top_n)] = {matched, recall}

    Keeping this shape prevents later scripts from mixing case-level recall with
    raw document-score recall under the same label.
    """
    out: dict[str, dict[str, dict[str, float | int]]] = {}
    for family in PHASE2_FAMILIES:
        queue = build_phase2_family_queue(base_df, family)
        phase2: dict[str, dict[str, float | int]] = {}
        for n in top_ns:
            measured = measure_doc_recall(queue, truth_docs, int(n))
            phase2[str(int(n))] = {
                "matched": int(measured["matched_truth_docs"]),
                "recall": float(measured["recall"]),
            }
        out[family] = {"phase2": phase2}
    return out


def _phase2_family_scores(base_df: pd.DataFrame) -> dict[str, pd.Series]:
    base_df = _ensure_base_phase2_columns(base_df)
    family_score_max_cols = {
        "unsupervised": "phase2_unsupervised_score_max",
        "timeseries": "phase2_timeseries_score_max",
        "relational": "phase2_relational_score_max",
        "duplicate": "phase2_duplicate_score_max",
        "intercompany": "phase2_intercompany_score_max",
    }
    return {
        family: pd.Series(
            base_df[col].astype(np.float64).reset_index(drop=True).to_numpy(),
            dtype=np.float64,
            name=family,
        )
        for family, col in family_score_max_cols.items()
    }


def _attach_phase2_noisy_or_score(base_df: pd.DataFrame) -> pd.DataFrame:
    out = _ensure_base_phase2_columns(base_df).reset_index(drop=True)
    phase2_internal = compute_phase2_internal_noisy_or(_phase2_family_scores(out))
    out["phase2_internal_noisy_or_score"] = phase2_internal.to_numpy()
    return out


def build_integrated_queue(base_df: pd.DataFrame, k: int = RRF_K) -> pd.DataFrame:
    """통합 큐 — PHASE2 5-family Noisy-OR voter + PHASE1 2-way RRF k=60.

    채택 식 (docs/PHASE2_GOVERNANCE_DESIGN.md 결정 8 / docs/TROUBLESHOOT.md TS-15):

        phase2_internal_noisy_or(case) = 1 - Π_f (1 - ecdf_f(case))
        final_rrf(case) = 1/(60+rank_phase1) + 1/(60+rank_phase2_internal)

    V7 fixed3 측정: 이전 PHASE1+VAE 2-way RRF 대비 TOP 100~5,000 전 깊이 양수
    Δ (+1.61 ~ +8.39pp). 5-way hierarchical RRF (이전 시도) 는 같은 측정에서
    평균 -6.45pp 손실로 reject 됨. RRF 적용 범위는 PHASE1 ↔ (PHASE2 Noisy-OR)
    2-way 만 사용; PHASE2 내부 결합은 RRF 가 아닌 Noisy-OR.
    """
    base_df = _attach_phase2_noisy_or_score(base_df)
    phase2_internal = pd.Series(
        base_df["phase2_internal_noisy_or_score"].astype(np.float64).to_numpy(),
        dtype=np.float64,
        name="phase2_internal_noisy_or",
    )
    rankers = {
        "phase1_composite": pd.Series(
            base_df["phase1_composite_sort_score"]
            .astype(np.float64)
            .reset_index(drop=True)
            .to_numpy(),
            dtype=np.float64,
        ),
        "phase2_internal_noisy_or": phase2_internal,
    }
    rrf = compute_rrf_score(rankers, k=k)
    merged = base_df.reset_index(drop=True).join(rrf)
    queue_df = merged.sort_values(
        by=["rrf_score", "phase1_composite_sort_score"],
        ascending=False,
        kind="mergesort",
    ).reset_index(drop=True)
    queue_df.insert(0, "review_rank", queue_df.index + 1)
    total_cases = len(queue_df)
    queue_df["phase12_review_band"] = [
        rank_percentile_band(rank, total_cases) for rank in queue_df["review_rank"]
    ]
    if "rank_phase2_internal_noisy_or" in queue_df.columns:
        queue_df["phase2_review_band"] = [
            rank_percentile_band(rank, total_cases)
            for rank in queue_df["rank_phase2_internal_noisy_or"]
        ]
    return queue_df


def build_integrated_queue_legacy_2way(base_df: pd.DataFrame, k: int = RRF_K) -> pd.DataFrame:
    """2-way RRF comparison queue for measurement only."""
    base_df = _ensure_base_phase2_columns(base_df)
    rankers = {
        "phase1_composite": base_df["phase1_composite_sort_score"]
        .astype(np.float64)
        .reset_index(drop=True),
        "phase2_unsupervised": base_df["phase2_unsupervised_score_max"]
        .astype(np.float64)
        .reset_index(drop=True),
    }
    rrf = compute_rrf_score(rankers, k=k)
    merged = base_df.reset_index(drop=True).join(rrf)
    queue_df = merged.sort_values(
        by=["rrf_score", "phase1_composite_sort_score"],
        ascending=False,
        kind="mergesort",
    ).reset_index(drop=True)
    queue_df.insert(0, "review_rank", queue_df.index + 1)
    return queue_df


def _ensure_base_phase2_columns(base_df: pd.DataFrame) -> pd.DataFrame:
    out = base_df.copy()
    if (
        "phase2_unsupervised_score_max" not in out
        and "phase2_unsupervised_selection_score_max" in out
    ):
        out["phase2_unsupervised_score_max"] = out["phase2_unsupervised_selection_score_max"]
    if (
        "phase2_unsupervised_score_mean" not in out
        and "phase2_unsupervised_selection_score_mean" in out
    ):
        out["phase2_unsupervised_score_mean"] = out["phase2_unsupervised_selection_score_mean"]
    for family in PHASE2_FAMILIES:
        max_col = PHASE2_FAMILY_SCORE_MAX_COLUMNS[family]
        mean_col = PHASE2_FAMILY_SCORE_MEAN_COLUMNS[family]
        if max_col not in out:
            out[max_col] = np.nan
        if mean_col not in out:
            out[mean_col] = np.nan
    return out


def measure_doc_recall(
    queue_df: pd.DataFrame,
    truth_docs: set[str],
    top_n: int,
    doc_ids_col: str = "document_ids_joined",
) -> dict[str, Any]:
    """TOP-N case 안에 등장한 truth document unique 수 기반 recall."""
    top = queue_df.head(top_n)
    seen: set[str] = set()
    for joined in top[doc_ids_col].astype(str):
        for d in joined.split(";"):
            if d:
                seen.add(d)
    matched = len(seen & truth_docs)
    total = len(truth_docs)
    return {
        "top_n": int(top_n),
        "matched_truth_docs": matched,
        "total_truth_docs": total,
        "recall": (matched / total) if total else 0.0,
    }


def summarize_family_rank_distribution(queue_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Summarize family raw score activity after Noisy-OR adoption."""
    summary: dict[str, dict[str, Any]] = {}
    for family in PHASE2_FAMILIES:
        score_col = PHASE2_FAMILY_SCORE_MAX_COLUMNS[family]
        if score_col not in queue_df:
            continue
        scores = pd.to_numeric(queue_df.get(score_col), errors="coerce").fillna(0.0)
        active_count = int((scores > 0).sum())
        top_tail_count = int((to_ecdf(scores) >= 0.95).sum()) if active_count else 0
        summary[family] = {
            "score_mean": float(scores.mean()),
            "score_q95": float(scores.quantile(0.95)),
            "score_max": float(scores.max()),
            "nonzero_case_count": active_count,
            "nonzero_case_rate": float(active_count / max(len(queue_df), 1)),
            "top_tail_case_count": top_tail_count,
            "status": "dead"
            if active_count == 0
            else ("near-dormant" if family == "intercompany" else "active"),
        }
    return summary


def build_narrator_candidates(
    phase1_result: Any,
    phase2_by_doc: pd.DataFrame,
    df: pd.DataFrame,
    n: int = 100,
) -> list[dict[str, Any]]:
    """Phase 3 Narrator candidate dict 리스트 빌드 + 입력 계약 점검."""
    phase2_by_doc = _attach_phase2_noisy_or_score(_ensure_phase2_family_columns(phase2_by_doc))
    doc_to_phase2 = dict(
        zip(
            phase2_by_doc["document_id"].astype(str),
            phase2_by_doc["phase2_internal_noisy_or_score"].astype(float),
            strict=False,
        )
    )
    family_doc_scores = _build_family_doc_score_maps(phase2_by_doc)
    phase1_cases_for_builder: list[dict[str, Any]] = []
    journal_metas: dict[str, dict[str, Any]] = {}
    ml_scores: dict[str, list[dict[str, Any]]] = {}
    peer_contexts: dict[str, dict[str, Any]] = {}

    # journal-level meta lookup (첫 행 기준).
    df_first_row_by_doc = df.drop_duplicates(subset=["document_id"], keep="first").set_index(
        df.drop_duplicates(subset=["document_id"], keep="first")["document_id"].astype(str)
    )

    for case in phase1_result.cases:
        if not case.documents:
            continue
        rep_doc_id = str(case.documents[0].document_id)
        rule_hits_payload = [
            {
                "rule_id": hit.rule_id,
                "severity": hit.severity,
                "score": hit.score,
                "fields_triggered": [],
                "rule_meta_ref": hit.rule_id,
            }
            for hit in case.raw_rule_hits
        ]
        phase1_cases_for_builder.append(
            {
                "case_id": case.case_id,
                "priority_score": float(case.priority_score),
                "journal_id": rep_doc_id,
                "rule_hits": rule_hits_payload,
            }
        )
        meta_source = (
            df_first_row_by_doc.loc[rep_doc_id] if rep_doc_id in df_first_row_by_doc.index else None
        )
        journal_metas[rep_doc_id] = {
            "batch_id": (
                str(meta_source["company_code"])
                if meta_source is not None and "company_code" in meta_source
                else ""
            ),
            "journal_id": rep_doc_id,
            "posting_date": (
                str(meta_source["posting_date"])
                if meta_source is not None and "posting_date" in meta_source
                else ""
            ),
            "period": (
                f"{int(meta_source['fiscal_year'])}-{int(meta_source['fiscal_period']):02d}"
                if meta_source is not None
                and "fiscal_year" in meta_source
                and "fiscal_period" in meta_source
                else ""
            ),
            "process": (
                str(meta_source["business_process"])
                if meta_source is not None and "business_process" in meta_source
                else ""
            ),
            "gl_account": (
                str(meta_source["gl_account"])
                if meta_source is not None and "gl_account" in meta_source
                else ""
            ),
            "counterparty": (
                str(meta_source["trading_partner"])
                if meta_source is not None and "trading_partner" in meta_source
                else ""
            ),
            "approver": (
                str(meta_source["approved_by"])
                if meta_source is not None and "approved_by" in meta_source
                else ""
            ),
            "amount": float(case.total_amount),
            "description": case.representative_explanation or "",
        }
        phase2_score = doc_to_phase2.get(rep_doc_id, 0.0)
        top_features = [
            {
                "feature_id": f"phase2_family_{family}",
                "value": float(family_doc_scores.get(family, {}).get(rep_doc_id, 0.0)),
                "contribution": float(family_doc_scores.get(family, {}).get(rep_doc_id, 0.0)),
            }
            for family in PHASE2_FAMILIES
            if float(family_doc_scores.get(family, {}).get(rep_doc_id, 0.0)) > 0.0
        ]
        ml_scores[rep_doc_id] = [
            {
                "model_id": "phase2_noisy_or_v1",
                "score": phase2_score,
                "percentile": phase2_score,
                "top_features": top_features,
            }
        ]
        # peer_context: 동일 process / gl_account 분포 요약 (간단 형태).
        peer_contexts[rep_doc_id] = {
            "phase1_case_priority_band": case.priority_band,
            "phase1_topic": case.primary_topic,
            "phase2_noisy_or_score": phase2_score,
        }

    candidates = build_candidates(
        phase1_cases_for_builder,
        journal_metas,
        ml_scores,
        peer_contexts,
        n=n,
        hard_limit=max(n, 100),
        ml_percentile_threshold=0.99,
    )
    return candidates


def verify_narrator_input_contract(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Phase 3 Narrator 입력 계약 점검. (스펙 §입력 계약 6개 필드)

    각 candidate 는 journal_ref / rule_hits / ml_scores / journal_meta /
    peer_context 5개 필드를 모두 비어 있지 않게 채워야 한다. journal_ref 는
    {batch_id, journal_id, posting_date, period, process} 5개 키.
    journal_meta 는 sanitizer 가 PII 비식별 후 amount_bucket/gl_account/
    counterparty_masked/approver_masked/description_masked 키를 채운다.
    """
    missing: dict[str, int] = {
        "candidate_id_empty": 0,
        "journal_ref_missing_keys": 0,
        "rule_hits_empty": 0,
        "ml_scores_empty": 0,
        "journal_meta_missing_keys": 0,
        "peer_context_missing": 0,
    }
    required_ref_keys = {"batch_id", "journal_id", "posting_date", "period", "process"}
    required_meta_keys = {
        "amount_bucket",
        "gl_account",
        "counterparty_masked",
        "approver_masked",
        "description_masked",
    }
    for c in candidates:
        if not c.get("candidate_id"):
            missing["candidate_id_empty"] += 1
        ref = c.get("journal_ref") or {}
        if not required_ref_keys.issubset(ref.keys()):
            missing["journal_ref_missing_keys"] += 1
        if not c.get("rule_hits"):
            missing["rule_hits_empty"] += 1
        if not c.get("ml_scores"):
            missing["ml_scores_empty"] += 1
        jm = c.get("journal_meta") or {}
        if not required_meta_keys.issubset(jm.keys()):
            missing["journal_meta_missing_keys"] += 1
        if not c.get("peer_context"):
            missing["peer_context_missing"] += 1
    return {
        "candidate_count": len(candidates),
        "required_journal_ref_keys": sorted(required_ref_keys),
        "required_journal_meta_keys_after_sanitize": sorted(required_meta_keys),
        "missing_counts": missing,
        "all_required_fields_present": all(v == 0 for v in missing.values()),
    }


def verify_composite_sort_lock(
    queue_df: pd.DataFrame,
    phase1_result: Any,
) -> dict[str, Any]:
    """composite_sort_score V1 lock 준수 검증.

    V1 lock 규칙: 정렬 1차=composite_sort_score, 2차=triage_rank_score, 3차=total_amount,
    4차=rule_count. PHASE2 overlay 는 정렬에 영향 주지 않음.
    """
    # phase1_result.cases 의 exposure_rank 와 queue_df.review_rank 가 일관되는지 확인.
    case_rank_phase1 = {case.case_id: case.exposure_rank for case in phase1_result.cases}
    queue_rank_map = dict(zip(queue_df["case_id"], queue_df["review_rank"], strict=False))
    deltas: list[dict[str, Any]] = []
    for case_id, p1_rank in case_rank_phase1.items():
        q_rank = queue_rank_map.get(case_id)
        if p1_rank is not None and q_rank is not None and int(p1_rank) != int(q_rank):
            deltas.append(
                {
                    "case_id": case_id,
                    "phase1_exposure_rank": p1_rank,
                    "queue_review_rank": int(q_rank),
                }
            )
    return {
        "case_count": len(queue_df),
        "rank_mismatch_count": len(deltas),
        "rank_mismatches_sample": deltas[:5],
        "v1_lock_compliant": len(deltas) == 0,
        "sort_keys_applied": [
            "phase1_composite_sort_score",
            "phase1_triage_rank_score",
            "total_amount",
            "rule_count",
        ],
        "phase2_score_in_sort_keys": False,
    }


PHASE1_CACHE = ROOT / "artifacts" / "stage7_phase1_case_result.pkl"
PHASE2_CACHE = ROOT / "artifacts" / "stage7_phase2_by_doc.parquet"


def main() -> int:
    t_start = time.perf_counter()
    REVIEW_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    df, detection_results, truth, bundle = load_inputs()
    truth_docs = set(truth["document_id"].astype(str))

    if PHASE1_CACHE.exists():
        _print(f"loading PHASE1 case cache: {_rel(PHASE1_CACHE)}")
        with PHASE1_CACHE.open("rb") as fh:
            phase1_result = pickle.load(fh)
    else:
        _print("running PHASE1 case_builder ...")
        phase1_result = build_phase1_case_result(
            df,
            detection_results,
            company_id="_ci_baseline",
            batch_id="v7_fixed3_2026-05-17",
            dataset_id="datasynth_manipulation_v7_candidate_fixed3",
        )
        with PHASE1_CACHE.open("wb") as fh:
            pickle.dump(phase1_result, fh, protocol=pickle.HIGHEST_PROTOCOL)
    _print(f"  phase1 cases={len(phase1_result.cases):,}")

    # Snapshot for diff=0 check.
    priority_score_snapshot = {
        case.case_id: float(case.priority_score) for case in phase1_result.cases
    }

    if PHASE2_FAMILY_CACHE.exists():
        _print(f"loading PHASE2 5-family by-doc cache: {_rel(PHASE2_FAMILY_CACHE)}")
        phase2_by_doc = _ensure_phase2_family_columns(pd.read_parquet(PHASE2_FAMILY_CACHE))
    else:
        _print("scoring PHASE2 5 families on full df ...")
        phase2_by_doc = score_phase2_families_by_document(df)
        phase2_by_doc.to_parquet(PHASE2_FAMILY_CACHE, index=False)
    _print(f"  phase2 scored docs={len(phase2_by_doc):,}")

    _print("building Phase2CaseOverlay ...")
    inference_contract = json.loads(INFERENCE_REPORT_PATH.read_text(encoding="utf-8"))
    overlays, family_scores_by_case = build_case_overlay_payload(
        phase1_result, phase2_by_doc, inference_contract
    )
    _print(f"  overlays={len(overlays)} cases_with_phase2={len(family_scores_by_case)}")

    # 옵션 Z lock HARD: priority_score 비파괴
    z_lock_check = assert_priority_score_preserved(phase1_result, priority_score_snapshot)
    if not z_lock_check["preserved"]:
        _print(f"  ⚠️ Z lock violation: {z_lock_check['mismatch_count']} cases differ")

    _print("building review queue rows ...")
    base_df = _build_base_rows(phase1_result, phase2_by_doc, overlays, truth_docs)
    queue_df = build_phase1_queue(base_df)
    queue_phase2_df = build_phase2_queue(base_df)
    queue_integrated_2way_df = build_integrated_queue_legacy_2way(base_df, k=RRF_K)
    queue_integrated_df = build_integrated_queue(base_df, k=RRF_K)
    composite_lock_check = verify_composite_sort_lock(queue_df, phase1_result)

    _print(f"writing 3 review queue parquets to {_rel(REVIEW_QUEUE_DIR)}")
    # PHASE1 단독 + queue.parquet 별칭 (백워드 호환).
    queue_df.to_parquet(QUEUE_PHASE1_PATH, index=False)
    queue_df.head(500).to_parquet(QUEUE_PHASE1_TOP500_PATH, index=False)
    queue_df.to_parquet(QUEUE_PATH, index=False)
    queue_df.head(500).to_parquet(QUEUE_TOP500_PATH, index=False)
    queue_df.head(100).to_parquet(QUEUE_TOP100_PATH, index=False)
    # PHASE2 단독.
    queue_phase2_df.to_parquet(QUEUE_PHASE2_PATH, index=False)
    queue_phase2_df.head(500).to_parquet(QUEUE_PHASE2_TOP500_PATH, index=False)
    # 통합 (RRF k=60).
    queue_integrated_df.to_parquet(QUEUE_INTEGRATED_PATH, index=False)
    queue_integrated_df.head(500).to_parquet(QUEUE_INTEGRATED_TOP500_PATH, index=False)
    _print(
        f"  rows phase1={len(queue_df):,} phase2={len(queue_phase2_df):,} "
        f"integrated={len(queue_integrated_df):,}"
    )

    # Document-level recall (informational, NOT a gating signal).
    doc_recall_by_queue: dict[str, list[dict[str, Any]]] = {
        "phase1": [measure_doc_recall(queue_df, truth_docs, n) for n in (100, 500, 1000, 2000)],
        "phase2": [
            measure_doc_recall(queue_phase2_df, truth_docs, n) for n in (100, 500, 1000, 2000)
        ],
        "integrated_2way": [
            measure_doc_recall(queue_integrated_2way_df, truth_docs, n)
            for n in (100, 500, 1000, 2000)
        ],
        "integrated": [
            measure_doc_recall(queue_integrated_df, truth_docs, n) for n in (100, 500, 1000, 2000)
        ],
    }
    family_rank_distribution = summarize_family_rank_distribution(queue_integrated_df)

    _print("building Phase 3 Narrator candidates (n=100) ...")
    candidates = build_narrator_candidates(phase1_result, phase2_by_doc, df, n=100)
    narrator_check = verify_narrator_input_contract(candidates)
    _print(
        f"  candidates={narrator_check['candidate_count']} "
        f"all_required_fields_present={narrator_check['all_required_fields_present']}"
    )

    # Informational truth metrics on top-500.
    # Not a gating signal; see feedback_phase1_truth_recall_guard.
    truth_in_top500 = int(queue_df.head(500)["case_contains_truth_doc"].sum())
    truth_in_top100 = int(queue_df.head(100)["case_contains_truth_doc"].sum())
    total_truth_cases = int(queue_df["case_contains_truth_doc"].sum())

    decision_hard_checks = {
        "priority_score_preserved": z_lock_check["preserved"],
        "narrator_required_fields_present": narrator_check["all_required_fields_present"],
        "composite_sort_v1_lock_compliant": composite_lock_check["v1_lock_compliant"],
    }
    decision = "GO" if all(decision_hard_checks.values()) else "NO-GO"

    integration_report = {
        "generated_at": _now_iso(),
        "stage": "Stage 7 — PHASE1↔PHASE2 통합 review queue",
        "dataset_version": "datasynth_manipulation_v7_candidate_fixed3",
        "decision": decision,
        "elapsed_sec": round(time.perf_counter() - t_start, 2),
        "hard_checks": decision_hard_checks,
        "z_lock_priority_preservation": z_lock_check,
        "composite_sort_v1_lock": composite_lock_check,
        "narrator_input_contract": narrator_check,
        "phase1": {
            "case_count": len(phase1_result.cases),
            "run_id": phase1_result.run_id,
            "company_id": phase1_result.company_id,
            "dataset_id": phase1_result.dataset_id,
        },
        "phase2": {
            "scored_docs": int(len(phase2_by_doc)),
            "cases_with_phase2_score": len(family_scores_by_case),
            "model_bundle": _rel(BUNDLE_PATH),
            "family_score_cache": _rel(PHASE2_FAMILY_CACHE),
            "active_families": list(PHASE2_FAMILIES),
            "scoring_mode": inference_contract.get("scoring_mode"),
            "schema_hash": inference_contract.get("schema_hash"),
        },
        "review_queue": {
            "rrf_k": int(RRF_K),
            "phase1": {
                "path": _rel(QUEUE_PHASE1_PATH),
                "top500_path": _rel(QUEUE_PHASE1_TOP500_PATH),
                "row_count": int(len(queue_df)),
            },
            "phase2": {
                "path": _rel(QUEUE_PHASE2_PATH),
                "top500_path": _rel(QUEUE_PHASE2_TOP500_PATH),
                "row_count": int(len(queue_phase2_df)),
            },
            "integrated": {
                "path": _rel(QUEUE_INTEGRATED_PATH),
                "top500_path": _rel(QUEUE_INTEGRATED_TOP500_PATH),
                "row_count": int(len(queue_integrated_df)),
            },
            "alias_legacy": {
                "path": _rel(QUEUE_PATH),
                "top500_path": _rel(QUEUE_TOP500_PATH),
                "top100_path": _rel(QUEUE_TOP100_PATH),
            },
        },
        "informational_truth_signal": {
            "guard_note": (
                "feedback_phase1_truth_recall_guard 준수: truth recall 은 informational only. "
                "PHASE1/PHASE2 변경의 정당화 사유로 사용하지 말 것."
            ),
            "cases_containing_truth_doc_in_top500": truth_in_top500,
            "cases_containing_truth_doc_in_top100": truth_in_top100,
            "total_cases_with_truth_doc": total_truth_cases,
            "doc_recall_by_queue": doc_recall_by_queue,
            "truth_label_use": "evaluation numerator/denominator only; no tuning",
        },
        "rrf_policy": {
            "mode": "2-way_rrf_with_phase2_noisy_or",
            "rankers": [
                "phase1_composite",
                "phase2_internal_noisy_or",
            ],
            "k": int(RRF_K),
            "phase2_internal_aggregator": "noisy_or",
            "phase2_internal_formula": (
                "1 - prod(1 - ecdf_f) for f in "
                "[unsupervised, timeseries, relational, duplicate, intercompany]"
            ),
            "adoption_evidence": "artifacts/phase2_family_ranking_alt_aggregators_20260519.md",
            "rejected_alternative": (
                "5-way hierarchical RRF — V7 fixed3 -6.45pp loss "
                "(TS-15, artifacts/phase2_family_ranking_measurement_20260519.md)"
            ),
            "ecdf_policy": (
                "zero-preserving; 0/NaN means no family signal and contributes 0 "
                "to Noisy-OR"
            ),
            "intercompany_status": "near-dormant; 0/NaN rows are preserved as no-signal",
            "family_rank_distribution": family_rank_distribution,
            "governance": (
                "docs/PHASE2_GOVERNANCE_DESIGN.md 결정 8 "
                "(Noisy-OR separated 채택, 2026-05-19)"
            ),
        },
    }
    INTEGRATION_REPORT_JSON.write_text(
        json.dumps(integration_report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    md_lines = [
        "# Stage 7 — PHASE1↔PHASE2 통합 review queue",
        "",
        (
            "- conclusion: PHASE1 ↔ PHASE2 Noisy-OR 2-way RRF doc recall "
            f"TOP-100={doc_recall_by_queue['integrated'][0]['recall']:.4f}, "
            f"TOP-500={doc_recall_by_queue['integrated'][1]['recall']:.4f}, "
            f"TOP-1000={doc_recall_by_queue['integrated'][2]['recall']:.4f}, "
            f"TOP-2000={doc_recall_by_queue['integrated'][3]['recall']:.4f} "
            f"(denominator={len(truth_docs):,})"
        ),
        f"- generated: `{integration_report['generated_at']}`",
        f"- decision: **{decision}**",
        f"- elapsed: `{integration_report['elapsed_sec']}s`",
        "",
        "## HARD checks",
        "",
        "| check | result |",
        "|---|---|",
    ]
    for k, v in decision_hard_checks.items():
        md_lines.append(f"| {k} | **{v}** |")
    md_lines += [
        "",
        "## 옵션 Z lock — PHASE1 priority_score 비파괴",
        "",
        f"- preserved: **{z_lock_check['preserved']}**",
        f"- case_count: `{z_lock_check['case_count']}`",
        f"- mismatch_count: `{z_lock_check['mismatch_count']}`",
        "",
        "## composite_sort_score V1 lock",
        "",
        f"- v1_lock_compliant: **{composite_lock_check['v1_lock_compliant']}**",
        f"- rank_mismatch_count: `{composite_lock_check['rank_mismatch_count']}`",
        f"- sort keys: `{composite_lock_check['sort_keys_applied']}`",
        f"- phase2_score_in_sort_keys: `{composite_lock_check['phase2_score_in_sort_keys']}`",
        "",
        "## Phase 3 Narrator 입력 계약",
        "",
        f"- candidate_count: `{narrator_check['candidate_count']}`",
        f"- all_required_fields_present: **{narrator_check['all_required_fields_present']}**",
        f"- missing_counts: `{narrator_check['missing_counts']}`",
        "",
        "## Review Queue export (3 큐 분리, TS-12 §6.1)",
        "",
        f"- PHASE1 단독: `{_rel(QUEUE_PHASE1_PATH)}` ({len(queue_df):,} rows)",
        f"- PHASE2 단독: `{_rel(QUEUE_PHASE2_PATH)}` ({len(queue_phase2_df):,} rows)",
        (
            f"- 통합 (PHASE1 ↔ PHASE2 Noisy-OR 2-way RRF k={RRF_K}): "
            f"`{_rel(QUEUE_INTEGRATED_PATH)}` ({len(queue_integrated_df):,} rows)"
        ),
        f"- 별칭(legacy): `{_rel(QUEUE_PATH)}` = PHASE1 단독 큐 동일 내용 (통합 큐 아님)",
        "",
        "## PHASE1 + PHASE2 overlay 요약",
        "",
        f"- PHASE1 cases: `{len(phase1_result.cases):,}`",
        f"- PHASE2 scored docs: `{len(phase2_by_doc):,}`",
        f"- cases with PHASE2 score attached: `{len(family_scores_by_case):,}`",
        f"- phase2 Noisy-OR families: `{list(PHASE2_FAMILIES)}`",
        "- correlation artifact: `artifacts/phase2_family_correlation_matrix_20260519.md`",
        "",
        "## informational truth signal (NOT gating)",
        "",
        (
            "> feedback_phase1_truth_recall_guard 준수 — truth label은 "
            "평가 분모/분자 산정에만 사용했고 튜닝에는 사용하지 않았다."
        ),
        "",
        f"- cases containing truth doc in top500 (PHASE1): `{truth_in_top500}`",
        f"- cases containing truth doc in top100 (PHASE1): `{truth_in_top100}`",
        f"- total cases with truth doc: `{total_truth_cases}`",
        "",
        "### legacy PHASE1+VAE 2-way vs Noisy-OR separated document recall (informational)",
        "",
        "| queue | TOP-N | matched truth docs | recall | enrichment vs random |",
        "|---|---:|---:|---:|---:|",
    ]
    for q in ("integrated_2way", "integrated"):
        label = (
            "legacy PHASE1+VAE 2-way RRF"
            if q == "integrated_2way"
            else "PHASE1 ↔ PHASE2 Noisy-OR 2-way RRF (채택)"
        )
        for item in doc_recall_by_queue[q]:
            expected_random = min(float(item["top_n"]) / max(len(queue_integrated_df), 1), 1.0)
            enrichment = (float(item["recall"]) / expected_random) if expected_random else 0.0
            md_lines.append(
                f"| {label} | {item['top_n']} | {item['matched_truth_docs']} | "
                f"{item['recall']:.4f} | {enrichment:.2f}x |"
            )
    md_lines += [
        "",
        "### Family signal summary",
        "",
        "| family | score mean | q95 | max | nonzero cases | top-tail cases | status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for family, item in family_rank_distribution.items():
        md_lines.append(
            f"| {family} | {item['score_mean']:.4f} | {item['score_q95']:.4f} | "
            f"{item['score_max']:.4f} | {item['nonzero_case_count']:,} | "
            f"{item['top_tail_case_count']:,} | {item['status']} |"
        )
    INTEGRATION_REPORT_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    _print(f"DONE. decision={decision} elapsed={time.perf_counter() - t_start:.1f}s")
    return 0 if decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
