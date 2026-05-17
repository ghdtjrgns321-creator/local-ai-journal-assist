"""Stage 7 — PHASE1↔PHASE2 통합 review queue 생성 (Sequential).

PHASE1 priority_score 비파괴 + PHASE2 unsupervised_selection_score overlay.
composite_sort_score V1 lock 준수. Phase 3 Narrator 입력 계약 점검 포함.
"""
# ruff: noqa: E402

from __future__ import annotations

import io
import json
import pickle
import sys
import time
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
from src.services.phase2_case_contract import build_phase2_case_overlays

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
INTEGRATION_REPORT_JSON = ROOT / "artifacts" / "phase1_phase2_integration_report_2026-05-17.json"
INTEGRATION_REPORT_MD = ROOT / "artifacts" / "phase1_phase2_integration_report_2026-05-17.md"


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


def aggregate_phase2_by_document(phase2_ecdf: pd.Series, df_doc_id: pd.Series) -> pd.DataFrame:
    """document_id별 PHASE2 ECDF max + mean aggregation."""
    frame = pd.DataFrame(
        {
            "document_id": df_doc_id.loc[phase2_ecdf.index].astype(str).to_numpy(),
            "phase2_score": phase2_ecdf.to_numpy(),
        }
    )
    return frame.groupby("document_id", as_index=False).agg(
        phase2_unsupervised_selection_score=("phase2_score", "max"),
        phase2_score_mean=("phase2_score", "mean"),
        phase2_row_count=("phase2_score", "size"),
    )


def build_case_overlay_payload(
    phase1_result: Any,
    phase2_by_doc: pd.DataFrame,
    inference_contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    """case별 PHASE2 family_scores 구성 → build_phase2_case_overlays."""
    doc_to_score = dict(
        zip(
            phase2_by_doc["document_id"].astype(str),
            phase2_by_doc["phase2_unsupervised_selection_score"].astype(float),
            strict=False,
        )
    )
    family_scores_by_case: dict[str, dict[str, float]] = {}
    for case in phase1_result.cases:
        doc_ids = [str(doc.document_id) for doc in case.documents]
        case_scores = [doc_to_score.get(d) for d in doc_ids if d in doc_to_score]
        if case_scores:
            family_scores_by_case[case.case_id] = {
                "ml_unsupervised": float(max(case_scores)),
            }
    overlays = build_phase2_case_overlays(
        phase1=phase1_result,
        family_scores_by_case=family_scores_by_case,
        detector_statuses=[
            {"family": "ml_unsupervised", "status": "applied", "model_version": "v1"}
        ],
        phase2_inference_contract=inference_contract,
        phase2_training_report_id="v7_fixed3_first_training_v1",
    )
    return overlays, family_scores_by_case


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


def build_queue_rows(
    phase1_result: Any,
    phase2_by_doc: pd.DataFrame,
    overlays: list[dict[str, Any]],
    truth_docs: set[str],
) -> pd.DataFrame:
    """case-level review queue 구성. composite_sort_score V1 lock 그대로."""
    doc_to_score = dict(
        zip(
            phase2_by_doc["document_id"].astype(str),
            phase2_by_doc["phase2_unsupervised_selection_score"].astype(float),
            strict=False,
        )
    )
    overlay_by_case = {o["phase1_case_id"]: o for o in overlays}
    rows: list[dict[str, Any]] = []
    for case in phase1_result.cases:
        case_doc_ids = [str(d.document_id) for d in case.documents]
        case_phase2_scores = [doc_to_score.get(d) for d in case_doc_ids if d in doc_to_score]
        phase2_max = max(case_phase2_scores) if case_phase2_scores else None
        phase2_mean = float(np.mean(case_phase2_scores)) if case_phase2_scores else None
        truth_match = any(d in truth_docs for d in case_doc_ids)
        overlay = overlay_by_case.get(case.case_id, {})
        primary_doc_id = case_doc_ids[0] if case_doc_ids else ""
        rows.append(
            {
                # PHASE1 identifiers + sort keys (V1 lock 보존)
                "case_id": case.case_id,
                "primary_topic": case.primary_topic,
                "primary_theme": case.primary_theme,
                "primary_queue": case.primary_queue,
                "exposure_rank": case.exposure_rank,
                # Score columns (PHASE1 원본 보존)
                "phase1_priority_score": float(case.priority_score),
                "phase1_base_priority_score": float(case.base_priority_score),
                "phase1_composite_sort_score": float(case.composite_sort_score),
                "phase1_triage_rank_score": float(case.triage_rank_score),
                "phase1_priority_band": case.priority_band,
                # PHASE2 overlay (별도 컬럼, priority_score 덮어쓰기 없음)
                "phase2_unsupervised_selection_score_max": phase2_max,
                "phase2_unsupervised_selection_score_mean": phase2_mean,
                "phase2_adjusted_priority": overlay.get("phase2_adjusted_priority"),
                "phase2_precision_adjustment_reason": overlay.get("precision_adjustment_reason"),
                # Case meta
                "rule_count": int(case.rule_count),
                "document_count": int(case.document_count),
                "row_count": int(case.row_count),
                "total_amount": float(case.total_amount),
                "first_posting_date": case.first_posting_date,
                "last_posting_date": case.last_posting_date,
                "primary_document_id": primary_doc_id,
                "document_ids_joined": ";".join(case_doc_ids),
                # Eval-only (informational, truth_match 사용은 informational 보고용)
                "case_contains_truth_doc": truth_match,
            }
        )
    queue_df = pd.DataFrame(rows)
    # V1 lock 정렬: composite_sort_score 1차, triage_rank_score / total_amount / rule_count 보조.
    queue_df = queue_df.sort_values(
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


def build_narrator_candidates(
    phase1_result: Any,
    phase2_by_doc: pd.DataFrame,
    df: pd.DataFrame,
    n: int = 100,
) -> list[dict[str, Any]]:
    """Phase 3 Narrator candidate dict 리스트 빌드 + 입력 계약 점검."""
    doc_to_phase2 = dict(
        zip(
            phase2_by_doc["document_id"].astype(str),
            phase2_by_doc["phase2_unsupervised_selection_score"].astype(float),
            strict=False,
        )
    )
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
        ml_scores[rep_doc_id] = [
            {
                "model_id": "ml_unsupervised_v1",
                "score": phase2_score,
                "percentile": phase2_score,
                "top_features": [],
            }
        ]
        # peer_context: 동일 process / gl_account 분포 요약 (간단 형태).
        peer_contexts[rep_doc_id] = {
            "phase1_case_priority_band": case.priority_band,
            "phase1_topic": case.primary_topic,
            "phase2_score_median_in_topic": phase2_score,
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
        _print("running PHASE1 case_builder …")
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

    if PHASE2_CACHE.exists():
        _print(f"loading PHASE2 by-doc cache: {_rel(PHASE2_CACHE)}")
        phase2_by_doc = pd.read_parquet(PHASE2_CACHE)
    else:
        _print("scoring PHASE2 on full df …")
        _phase2_raw, phase2_ecdf = score_phase2(df, bundle)
        phase2_by_doc = aggregate_phase2_by_document(phase2_ecdf, df["document_id"])
        phase2_by_doc.to_parquet(PHASE2_CACHE, index=False)
    _print(f"  phase2 scored docs={len(phase2_by_doc):,}")

    _print("building Phase2CaseOverlay …")
    inference_contract = json.loads(INFERENCE_REPORT_PATH.read_text(encoding="utf-8"))
    overlays, family_scores_by_case = build_case_overlay_payload(
        phase1_result, phase2_by_doc, inference_contract
    )
    _print(f"  overlays={len(overlays)} cases_with_phase2={len(family_scores_by_case)}")

    # 옵션 Z lock HARD: priority_score 비파괴
    z_lock_check = assert_priority_score_preserved(phase1_result, priority_score_snapshot)
    if not z_lock_check["preserved"]:
        _print(f"  ⚠️ Z lock violation: {z_lock_check['mismatch_count']} cases differ")

    _print("building review queue rows …")
    queue_df = build_queue_rows(phase1_result, phase2_by_doc, overlays, truth_docs)
    composite_lock_check = verify_composite_sort_lock(queue_df, phase1_result)

    _print(f"writing review queue parquets to {_rel(REVIEW_QUEUE_DIR)}")
    queue_df.to_parquet(QUEUE_PATH, index=False)
    queue_df.head(500).to_parquet(QUEUE_TOP500_PATH, index=False)
    queue_df.head(100).to_parquet(QUEUE_TOP100_PATH, index=False)
    _print(f"  full queue rows={len(queue_df):,}")

    _print("building Phase 3 Narrator candidates (n=100) …")
    candidates = build_narrator_candidates(phase1_result, phase2_by_doc, df, n=100)
    narrator_check = verify_narrator_input_contract(candidates)
    _print(
        f"  candidates={narrator_check['candidate_count']} "
        f"all_required_fields_present={narrator_check['all_required_fields_present']}"
    )

    # Informational truth metrics on top-500 (NOT a gating signal — feedback_phase1_truth_recall_guard)
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
            "scoring_mode": inference_contract.get("scoring_mode"),
            "schema_hash": inference_contract.get("schema_hash"),
        },
        "review_queue": {
            "full_queue_path": _rel(QUEUE_PATH),
            "top500_path": _rel(QUEUE_TOP500_PATH),
            "top100_path": _rel(QUEUE_TOP100_PATH),
            "row_count_full": int(len(queue_df)),
            "row_count_top500": min(500, int(len(queue_df))),
            "row_count_top100": min(100, int(len(queue_df))),
        },
        "informational_truth_signal": {
            "guard_note": (
                "feedback_phase1_truth_recall_guard 준수: truth recall 은 informational only. "
                "PHASE1/PHASE2 변경의 정당화 사유로 사용하지 말 것."
            ),
            "cases_containing_truth_doc_in_top500": truth_in_top500,
            "cases_containing_truth_doc_in_top100": truth_in_top100,
            "total_cases_with_truth_doc": total_truth_cases,
        },
    }
    INTEGRATION_REPORT_JSON.write_text(
        json.dumps(integration_report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    md_lines = [
        "# Stage 7 — PHASE1↔PHASE2 통합 review queue",
        "",
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
        "## Review Queue export",
        "",
        f"- full: `{_rel(QUEUE_PATH)}` ({len(queue_df):,} rows)",
        f"- top500: `{_rel(QUEUE_TOP500_PATH)}` ({min(500, len(queue_df)):,} rows)",
        f"- top100: `{_rel(QUEUE_TOP100_PATH)}` ({min(100, len(queue_df)):,} rows)",
        "",
        "## PHASE1 + PHASE2 overlay 요약",
        "",
        f"- PHASE1 cases: `{len(phase1_result.cases):,}`",
        f"- PHASE2 scored docs: `{len(phase2_by_doc):,}`",
        f"- cases with PHASE2 score attached: `{len(family_scores_by_case):,}`",
        "",
        "## informational truth signal (NOT gating)",
        "",
        "> feedback_phase1_truth_recall_guard 준수 — truth recall 은 informational only.",
        "",
        f"- cases containing truth doc in top500: `{truth_in_top500}`",
        f"- cases containing truth doc in top100: `{truth_in_top100}`",
        f"- total cases with truth doc: `{total_truth_cases}`",
    ]
    INTEGRATION_REPORT_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    _print(f"DONE. decision={decision} elapsed={time.perf_counter() - t_start:.1f}s")
    return 0 if decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
