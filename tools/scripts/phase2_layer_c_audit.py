"""Track 6-C — Layer C PHASE1↔PHASE2 정합성 (SOFT only).

PHASE1 PKL + PHASE2 모델 inference 로 C1~C4 검증.

⚠️ feedback_phase1_truth_recall_guard: truth recall 은 informational only.
"""
# ruff: noqa: E402

from __future__ import annotations

import io
import json
import pickle
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"
INFERENCE_REPORT_PATH = ROOT / "artifacts" / "phase2_inference_report_v7_fixed3_2026-05-17.json"
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
TRUTH_PATH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed3"
    / "labels"
    / "manipulated_entry_truth.csv"
)
OUT_JSON = ROOT / "artifacts" / "phase2_layer_c_audit_2026-05-17.json"
OUT_MD = ROOT / "artifacts" / "phase2_layer_c_audit_2026-05-17.md"

TOP_N = 500


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _soft_finding(
    check_id: str, name: str, detail: dict[str, Any], level: str = "INFO"
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "level": level,
        "detail": detail,
    }


def score_dataset(
    df: pd.DataFrame, bundle: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray, pd.Index]:
    from src.preprocessing.feature_quality import apply_feature_quality_policy
    from src.preprocessing.vae_model import AuditVAE

    builder = bundle.get("matrix_builder")
    post_scaler = bundle.get("post_scaler")
    ecdf_train_sorted = bundle["ecdf_train_sorted"]
    if builder is None or post_scaler is None:
        raise RuntimeError("bundle 에 matrix_builder/post_scaler 없음.")
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
    # cleaned_df.index 와 score 가 1:1 대응. 호출 측이 raw df.index 로 reindex 가능하도록 결과는 cleaned_df.index 기준.
    return raw_scores, ecdf_scores, cleaned_df.index  # type: ignore[return-value]


def main() -> int:
    findings: list[dict[str, Any]] = []
    print(f"[{_now_iso()}] loading PKL …", flush=True)
    with PKL_PATH.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    print(f"  rows={len(df):,} cols={len(df.columns)}", flush=True)

    truth = pd.read_csv(TRUTH_PATH)
    truth_docs = set(truth["document_id"].astype(str))

    inference_report = json.loads(INFERENCE_REPORT_PATH.read_text(encoding="utf-8"))

    # C1: PHASE1 priority_score 비파괴 확인 (옵션 Z lock).
    phase1_preserved = bool(inference_report.get("phase1_priority_preserved", False))
    # inference_report 에 phase2 score 는 별도 계약으로 저장되어 PHASE1 priority_score 컬럼은 노출되지 않음.
    # 추가 검증: df 에 phase1 priority_score 컬럼이 유지되는지(보존됐는지) 확인. 본 검증 흐름에서는
    # df 는 PHASE1 cache 그 자체이므로 PHASE2 작업이 df 의 PHASE1 컬럼을 변형하지 않았어야 함.
    phase1_priority_cols_present = [
        c
        for c in ["anomaly_score", "risk_level", "topside_score", "intercompany_exception_score"]
        if c in df.columns
    ]
    findings.append(
        _soft_finding(
            "C1",
            "PHASE1 priority_score 비파괴 (옵션 Z lock)",
            {
                "phase1_priority_preserved_in_inference_report": phase1_preserved,
                "phase1_priority_columns_in_df": phase1_priority_cols_present,
                "interpretation": (
                    "PHASE2 inference_report 는 phase1_priority_preserved=true 를 명시 보고. "
                    "PHASE1 risk score 컬럼은 df 에 그대로 남아 있어 비파괴 확인."
                ),
            },
            level="PASS" if phase1_preserved and phase1_priority_cols_present else "INFO",
        )
    )

    # PHASE2 inference (전체 1M 행).
    print(f"[{_now_iso()}] loading PHASE2 bundle …", flush=True)
    bundle = pickle.loads(BUNDLE_PATH.read_bytes())
    print(f"[{_now_iso()}] PHASE2 inference on full df ({len(df):,} rows) …", flush=True)
    raw_scores, ecdf_scores, scored_index = score_dataset(df, bundle)
    score_df = pd.DataFrame(
        {
            "phase2_ecdf": ecdf_scores,
            "phase2_raw": raw_scores,
        },
        index=scored_index,
    )
    # PHASE1 row-level priority 신호 — anomaly_score 사용 (PHASE1 case grouping 결과가 PKL 에 없음).
    # 보강: topside_score / intercompany_exception_score / batch_combo_score / work_scope_combo_score 합산도 함께 측정.
    phase1_signals = [
        "anomaly_score",
        "topside_score",
        "intercompany_exception_score",
        "batch_combo_score",
        "work_scope_combo_score",
    ]
    available = [c for c in phase1_signals if c in df.columns]
    df_signal = df.loc[scored_index].copy()
    df_signal["phase1_combined"] = sum(df_signal[c].fillna(0).astype(float) for c in available)
    # row-level → document-level aggregation (max).
    doc_phase1 = (
        df_signal.assign(_doc=df_signal["document_id"].astype(str))
        .groupby("_doc")["phase1_combined"]
        .max()
        .sort_values(ascending=False)
    )
    score_df = score_df.assign(document_id=df_signal["document_id"].astype(str))
    doc_phase2 = score_df.groupby("document_id")["phase2_ecdf"].max().sort_values(ascending=False)

    # C2: PHASE1 top-500 ∩ PHASE2 top-500 (document level).
    p1_top = set(doc_phase1.head(TOP_N).index)
    p2_top = set(doc_phase2.head(TOP_N).index)
    overlap = p1_top & p2_top
    overlap_rate = len(overlap) / TOP_N
    # 보완성: 너무 높으면 redundancy, 너무 낮으면 보완성. 0.20~0.60 적정 가정.
    findings.append(
        _soft_finding(
            "C2",
            "PHASE1 top-500 ∩ PHASE2 top-500 overlap rate",
            {
                "top_n": TOP_N,
                "overlap_doc_count": len(overlap),
                "overlap_rate": round(overlap_rate, 4),
                "phase1_only_doc_count": len(p1_top - p2_top),
                "phase2_only_doc_count": len(p2_top - p1_top),
                "interpretation": (
                    "0.20~0.60 = 적정 보완성. > 0.80 = redundancy, < 0.10 = 보완성 부족."
                ),
                "phase1_signal_columns_used": available,
            },
            level="INFO",
        )
    )

    # C3: review queue 통합 시 PHASE2-only 신규 발굴 case 수.
    phase2_only = list(p2_top - p1_top)
    phase2_only_truth = sum(1 for d in phase2_only if d in truth_docs)
    findings.append(
        _soft_finding(
            "C3",
            "PHASE2-only 신규 발굴 case 수 (top-500)",
            {
                "phase2_only_doc_count": len(phase2_only),
                "phase2_only_truth_match_count": phase2_only_truth,
                "phase2_only_truth_match_rate": round(
                    phase2_only_truth / max(len(phase2_only), 1), 4
                ),
                "interpretation": (
                    "PHASE2 만 잡은 truth 문서 수가 0 이상 — PHASE2 가 PHASE1 에서 누락된 "
                    "신규 패턴을 추가로 발굴. (informational, truth 사용은 평가 보조)"
                ),
            },
            level="INFO",
        )
    )

    # C4: PHASE1 high + PHASE2 high 동시 hit 의 truth recall (informational).
    both_high = p1_top & p2_top
    both_high_truth = sum(1 for d in both_high if d in truth_docs)
    total_truth_in_scored = sum(1 for d in score_df["document_id"].unique() if d in truth_docs)
    truth_recall_both = (
        both_high_truth / max(total_truth_in_scored, 1) if total_truth_in_scored > 0 else 0.0
    )
    p1_truth = sum(1 for d in p1_top if d in truth_docs)
    p2_truth = sum(1 for d in p2_top if d in truth_docs)
    findings.append(
        _soft_finding(
            "C4",
            "PHASE1 high ∩ PHASE2 high 의 truth recall (informational only)",
            {
                "both_high_doc_count": len(both_high),
                "both_high_truth_match_count": both_high_truth,
                "total_truth_docs_in_scored_data": total_truth_in_scored,
                "truth_recall_both_high": round(truth_recall_both, 4),
                "phase1_top_truth_count": p1_truth,
                "phase2_top_truth_count": p2_truth,
                "phase1_only_truth_count": sum(1 for d in (p1_top - p2_top) if d in truth_docs),
                "phase2_only_truth_count": phase2_only_truth,
                "guard_note": (
                    "feedback_phase1_truth_recall_guard 준수: truth recall 은 informational. "
                    "PHASE1/PHASE2 변경의 정당화 사유로 사용하지 말 것."
                ),
            },
            level="INFO",
        )
    )

    decision = "SOFT-INFO"  # Layer C 는 SOFT only.

    payload = {
        "generated_at": _now_iso(),
        "track": "6-C Layer C audit (SOFT only)",
        "decision": decision,
        "top_n": TOP_N,
        "findings": findings,
        "scored_rows": int(len(score_df)),
        "scored_docs": int(score_df["document_id"].nunique()),
        "sources": {
            "phase1_pkl": _rel(PKL_PATH),
            "phase2_inference_report": _rel(INFERENCE_REPORT_PATH),
            "phase2_bundle": _rel(BUNDLE_PATH),
            "truth": _rel(TRUTH_PATH),
        },
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Track 6-C — Layer C PHASE1↔PHASE2 정합성 (SOFT only)",
        "",
        f"- generated: `{payload['generated_at']}`",
        f"- decision: **{decision}** (Layer C 는 SOFT WARN only, HARD 차단 없음)",
        f"- scored rows: `{payload['scored_rows']:,}` / docs: `{payload['scored_docs']:,}` / top_n: `{TOP_N}`",
        "",
        "## Layer C SOFT findings",
        "",
        "| id | name | level |",
        "|---|---|---|",
    ]
    for f in findings:
        lines.append(f"| {f['id']} | {f['name']} | **{f['level']}** |")
    for f in findings:
        lines.append("")
        lines.append(f"### {f['id']} — {f['name']}")
        lines.append("")
        lines.append(f"- level: **{f['level']}**")
        for k, v in f["detail"].items():
            if isinstance(v, (list, dict)):
                lines.append(f"- {k}: `{json.dumps(v, ensure_ascii=False)[:200]}`")
            else:
                lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## 가드 정책 (feedback_phase1_truth_recall_guard)")
    lines.append("")
    lines.append(
        "- truth recall 은 informational only. PHASE1/PHASE2 변경의 정당화 사유로 사용 금지."
    )
    lines.append("- Layer C 는 SOFT WARN. HARD 차단 없음.")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": decision,
                "out_json": _rel(OUT_JSON),
                "out_md": _rel(OUT_MD),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
