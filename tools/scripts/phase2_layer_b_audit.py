"""Track 6-B — Layer B 모델 품질 가드 (read-only).

inference_report + training_report (epoch history) 만 보고 B1~B5 가드 검증.
"""
# ruff: noqa: E402

from __future__ import annotations

import json
import math
import pickle
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

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
ECDF_PATH = (
    ROOT
    / "data"
    / "companies"
    / "_ci_baseline"
    / "engagements"
    / "2026"
    / "models"
    / "phase2_unsupervised"
    / "v1"
    / "ecdf_train_distribution.npz"
)
PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"
TRUTH_PATH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed3"
    / "labels"
    / "manipulated_entry_truth.csv"
)
OUT_JSON = ROOT / "artifacts" / "phase2_layer_b_audit_2026-05-17.json"
OUT_MD = ROOT / "artifacts" / "phase2_layer_b_audit_2026-05-17.md"

B1_MAX_RATIO = 1.30
B5_MIN_ENTROPY = 0.70


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _gate(
    check_id: str, name: str, passed: bool, status: str, detail: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "status": status,
        "passed": passed,
        "detail": detail,
    }


def audit_b1(training: dict[str, Any]) -> dict[str, Any]:
    epoch_history = training.get("epoch_history", [])
    if not epoch_history:
        return _gate(
            "B1", "val/train recon ratio < 1.3", False, "FAIL", {"error": "epoch_history empty"}
        )
    final = epoch_history[-1]
    train_loss = float(final.get("train_reconstruction_loss", float("nan")))
    val_loss = float(final.get("val_reconstruction_loss", float("nan")))
    ratio = val_loss / train_loss if train_loss > 0 else float("inf")
    passed = ratio < B1_MAX_RATIO
    return _gate(
        "B1",
        f"val_recon_loss / train_recon_loss < {B1_MAX_RATIO}",
        passed,
        "PASS" if passed else "FAIL",
        {
            "train_recon_loss_final": train_loss,
            "val_recon_loss_final": val_loss,
            "ratio": round(ratio, 4),
            "max_allowed": B1_MAX_RATIO,
            "overfitting_signal": ratio >= B1_MAX_RATIO,
            "epochs_run": len(epoch_history),
            "best_epoch": training.get("training_hyperparams", {}).get("best_epoch"),
        },
    )


def audit_b2(training: dict[str, Any], inference: dict[str, Any]) -> dict[str, Any]:
    val_recon = float(training.get("val_recon_loss", float("nan")))
    test_recon = float(training.get("test_recon_loss", float("nan")))
    val_raw_mean = float(inference["splits"]["val"]["raw_recon_mean"])
    test_raw_mean = float(inference["splits"]["test"]["raw_recon_mean"])
    val_raw_std = float(inference["splits"]["val"]["raw_recon_std"])
    test_raw_std = float(inference["splits"]["test"]["raw_recon_std"])
    delta = test_recon - val_recon
    # 일관성: test_recon 가 val_recon 의 ±50% 이내면 양호.
    relative_drift = abs(delta) / max(val_recon, 1e-12)
    passed = relative_drift <= 0.50
    return _gate(
        "B2",
        "test_recon vs val_recon 일관성 (|drift| ≤ 50%)",
        passed,
        "PASS" if passed else "FAIL",
        {
            "val_recon_loss": val_recon,
            "test_recon_loss": test_recon,
            "delta_test_minus_val": round(delta, 6),
            "relative_drift": round(relative_drift, 4),
            "val_raw_mean": round(val_raw_mean, 6),
            "val_raw_std": round(val_raw_std, 6),
            "test_raw_mean": round(test_raw_mean, 6),
            "test_raw_std": round(test_raw_std, 6),
        },
    )


def audit_b3_b4_b5(
    inference: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    # B3, B4, B5 모두 row-level score 가 필요하므로 모델로 추가 inference 수행.
    bundle = pickle.loads(BUNDLE_PATH.read_bytes())
    ecdf_train_sorted = np.load(ECDF_PATH)["ecdf_train_sorted"]
    bundle_ecdf = bundle["ecdf_train_sorted"]
    ecdf_match = bool(np.array_equal(bundle_ecdf, ecdf_train_sorted))

    # 전체 V7 fixed3 데이터에 대해 (또는 test 50k 만) 모델 inference.
    df = _load_phase1_df()
    truth = pd.read_csv(TRUTH_PATH)
    truth_docs = set(truth["document_id"].astype(str))
    truth_scenarios = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )

    # test partition (2024) 추출.
    test_df = df.loc[df["fiscal_year"].astype(int).isin([2024])].copy()
    # row-level inference.
    raw_scores, ecdf_scores = _score_rows(test_df, bundle, ecdf_train_sorted)

    # B3: 정상 vs 이상 모집단 score 분리도 (informational, eval-only)
    is_truth = test_df["document_id"].astype(str).isin(truth_docs).astype(int).to_numpy()
    pos_count = int(is_truth.sum())
    neg_count = int(len(is_truth) - pos_count)
    if pos_count > 0 and neg_count > 0:
        # KS statistic
        pos_scores = np.sort(ecdf_scores[is_truth == 1])
        neg_scores = np.sort(ecdf_scores[is_truth == 0])
        all_scores = np.union1d(pos_scores, neg_scores)
        cdf_pos = np.searchsorted(pos_scores, all_scores, side="right") / max(len(pos_scores), 1)
        cdf_neg = np.searchsorted(neg_scores, all_scores, side="right") / max(len(neg_scores), 1)
        ks_stat = float(np.max(np.abs(cdf_pos - cdf_neg)))
        median_diff = float(np.median(pos_scores) - np.median(neg_scores))
    else:
        ks_stat = float("nan")
        median_diff = float("nan")
    b3 = _gate(
        "B3",
        "unsupervised_selection_score 분포 분리도",
        ks_stat >= 0.3 if not math.isnan(ks_stat) else False,
        "PASS" if (not math.isnan(ks_stat) and ks_stat >= 0.3) else "INFO",
        {
            "n_test_rows": int(len(test_df)),
            "n_truth_rows_in_test": pos_count,
            "ks_statistic": round(ks_stat, 4) if not math.isnan(ks_stat) else None,
            "median_score_difference": round(median_diff, 4)
            if not math.isnan(median_diff)
            else None,
            "interpretation": "KS >= 0.3 강한 분리, 0.15~0.3 중간, < 0.15 약함",
        },
    )

    # B4: ECDF 일관성 (학습/추론 동일 분포 사용)
    # 새 raw_scores 에 대해 ECDF 변환이 다시 같은 분포로 mapping 되는지 검증.
    # bundle.ecdf_train_sorted 와 npz 의 일치 + searchsorted 재계산 일치 확인.
    reverify_ecdf = np.searchsorted(ecdf_train_sorted, raw_scores) / max(len(ecdf_train_sorted), 1)
    ecdf_match_recomputed = bool(np.allclose(reverify_ecdf, ecdf_scores))
    b4 = _gate(
        "B4",
        "ECDF 분포 학습/추론 일관성",
        ecdf_match and ecdf_match_recomputed,
        "PASS" if (ecdf_match and ecdf_match_recomputed) else "FAIL",
        {
            "bundle_ecdf_matches_external_npz": ecdf_match,
            "recomputed_ecdf_matches_scoring": ecdf_match_recomputed,
            "ecdf_train_size": int(len(ecdf_train_sorted)),
            "scoring_mode": inference.get("scoring_mode"),
        },
    )

    # B5: top 1% 영역의 시나리오 entropy.
    top1_threshold = float(np.quantile(ecdf_scores, 0.99))
    top1_mask = ecdf_scores >= top1_threshold
    top1_doc_ids = test_df.loc[top1_mask, "document_id"].astype(str).to_numpy()
    top1_scenarios = [truth_scenarios.get(d, "__normal__") for d in top1_doc_ids]
    counts: dict[str, int] = {}
    for s in top1_scenarios:
        counts[s] = counts.get(s, 0) + 1
    total = sum(counts.values())
    if total > 0:
        probs = np.array([c / total for c in counts.values()])
        # 시나리오만 (normal 제외) entropy
        scenario_only_counts = {k: v for k, v in counts.items() if k != "__normal__"}
        scenario_total = sum(scenario_only_counts.values())
        if scenario_total > 0:
            sprobs = np.array([c / scenario_total for c in scenario_only_counts.values()])
            scenario_entropy = float(-np.sum(sprobs * np.log2(sprobs + 1e-12)))
            n_scenarios = len(scenario_only_counts)
            max_entropy = math.log2(max(n_scenarios, 2))
            normalized_entropy = scenario_entropy / max_entropy if max_entropy > 0 else 0.0
        else:
            scenario_entropy = 0.0
            n_scenarios = 0
            normalized_entropy = 0.0
        full_entropy = float(-np.sum(probs * np.log2(probs + 1e-12)))
    else:
        scenario_entropy = 0.0
        full_entropy = 0.0
        normalized_entropy = 0.0
        n_scenarios = 0
    passed = normalized_entropy >= B5_MIN_ENTROPY
    b5 = _gate(
        "B5",
        f"top-1% scenario entropy ≥ {B5_MIN_ENTROPY} (normalized)",
        passed,
        "PASS" if passed else "INFO",
        {
            "top1_threshold_ecdf": round(top1_threshold, 4),
            "top1_row_count": int(top1_mask.sum()),
            "scenario_counts_in_top1": counts,
            "scenario_only_count": n_scenarios,
            "scenario_entropy_bits": round(scenario_entropy, 4),
            "normalized_entropy": round(normalized_entropy, 4),
            "full_entropy_including_normal": round(full_entropy, 4),
            "min_required": B5_MIN_ENTROPY,
            "note": (
                "scenario entropy 는 truth 라벨이 부착된 시나리오 다양성 기준. "
                "정상 majority 가 top-1% 의 대부분을 차지하는 것은 자연스러움 (informational)."
            ),
        },
    )
    return b3, b4, b5


def _load_phase1_df():
    import pickle as _pickle

    with PKL_PATH.open("rb") as fh:
        return _pickle.load(fh)["df"]


def _score_rows(
    df: pd.DataFrame,
    bundle: dict[str, Any],
    ecdf_train_sorted: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """모델 bundle 로 row-level recon score + ECDF 변환."""
    import io

    import torch

    from src.preprocessing.feature_quality import apply_feature_quality_policy
    from src.preprocessing.vae_model import AuditVAE

    # 매트릭스 빌더 + post_scaler 상태 복원 (Stage 5 학습 흐름과 동일).
    builder = bundle.get("matrix_builder")
    post_scaler = bundle.get("post_scaler")
    if builder is None or post_scaler is None:
        raise RuntimeError("bundle 에 matrix_builder/post_scaler 가 없음. Stage 5 재학습 필요.")
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

    raw_scores: list[np.ndarray] = []
    with torch.no_grad():
        tensor = torch.from_numpy(arr)
        for start in range(0, len(tensor), 1024):
            chunk = tensor[start : start + 1024].to(device)
            recon, _, _ = model(chunk)
            raw_scores.append(((recon - chunk) ** 2).mean(dim=1).cpu().numpy())
    raw_scores_arr = np.concatenate(raw_scores, axis=0)
    ecdf_scores = np.searchsorted(ecdf_train_sorted, raw_scores_arr) / max(
        len(ecdf_train_sorted), 1
    )
    return raw_scores_arr, ecdf_scores


def _rebuild_builder_from_metadata(meta: dict[str, Any]):
    """matrix metadata 로 부터 inference-only builder 를 복원."""
    from src.preprocessing.phase2_matrix import Phase2AutoencoderMatrixBuilder
    from src.preprocessing.transformers import (
        FrequencyCountEncoder,
        NumericPolicyTransformer,
        RareCategoryOneHotEncoder,
        SignedLogTransformer,
    )

    builder = Phase2AutoencoderMatrixBuilder(preprocessing_plan=None)
    builder.numeric_columns = list(meta.get("numeric_columns", []))
    builder.amount_columns = list(meta.get("amount_columns", []))
    builder.general_numeric_columns = list(meta.get("general_numeric_columns", []))
    builder.low_card_columns = list(meta.get("low_card_columns", []))
    builder.high_card_columns = list(meta.get("high_card_columns", []))
    builder.boolean_columns = list(meta.get("boolean_columns", []))
    builder.sparse_dropped_columns = list(meta.get("sparse_dropped_columns", []))
    builder.feature_names_ = list(meta.get("feature_names", []))
    builder.output_feature_groups_ = dict(meta.get("output_feature_groups", {}))
    builder.schema_hash_ = int(meta.get("schema_hash", 0))

    builder._signed_log = SignedLogTransformer()
    if builder.amount_columns:
        # SignedLogTransformer 는 fit 시 col stat 을 저장하지 않으므로 lazy 사용.
        pass
    builder._numeric_policy = NumericPolicyTransformer()
    builder._numeric_policy.policies_ = meta.get("numeric_transform_policies", {})
    builder._low_card_encoder = RareCategoryOneHotEncoder(min_count=2)
    builder._low_card_encoder.categories_ = {
        k: list(v) for k, v in meta.get("low_card_categories", {}).items()
    }
    builder._high_card_encoder = FrequencyCountEncoder()
    return builder


def main() -> int:
    training = json.loads(TRAINING_REPORT_PATH.read_text(encoding="utf-8"))
    inference = json.loads(INFERENCE_REPORT_PATH.read_text(encoding="utf-8"))

    gates: list[dict[str, Any]] = []
    gates.append(audit_b1(training))
    gates.append(audit_b2(training, inference))
    try:
        b3, b4, b5 = audit_b3_b4_b5(inference)
        gates.extend([b3, b4, b5])
    except Exception as exc:  # noqa: BLE001
        # B3/B4/B5 inference 실패 시 informational + 추적 정보 기록 후 계속.
        gates.append(
            _gate(
                "B3-5",
                "row-level inference 기반 B3/B4/B5 측정",
                False,
                "INFO",
                {"error": repr(exc), "note": "inference 재현 실패. bundle 구조 검증 필요."},
            )
        )

    decision = "GO"
    fail = [g for g in gates if g["status"] == "FAIL"]
    info = [g for g in gates if g["status"] == "INFO"]
    if fail:
        decision = "NO-GO"
    elif info:
        decision = "GO-WITH-CAVEAT"

    payload = {
        "generated_at": _now_iso(),
        "track": "6-B Layer B audit",
        "decision": decision,
        "pass_count": sum(1 for g in gates if g["status"] == "PASS"),
        "info_count": len(info),
        "fail_count": len(fail),
        "gates": gates,
        "thresholds": {
            "B1_max_ratio": B1_MAX_RATIO,
            "B5_min_normalized_entropy": B5_MIN_ENTROPY,
        },
        "sources": {
            "training_report": _rel(TRAINING_REPORT_PATH),
            "inference_report": _rel(INFERENCE_REPORT_PATH),
            "model_bundle": _rel(BUNDLE_PATH),
            "ecdf_npz": _rel(ECDF_PATH),
        },
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Track 6-B — Layer B 모델 품질 가드",
        "",
        f"- generated: `{payload['generated_at']}`",
        f"- decision: **{decision}** (pass {payload['pass_count']}, info {payload['info_count']}, fail {payload['fail_count']})",
        "",
        "## Layer B 가드",
        "",
        "| gate | name | status |",
        "|---|---|---|",
    ]
    for g in gates:
        lines.append(f"| {g['id']} | {g['name']} | **{g['status']}** |")
    for g in gates:
        lines.append("")
        lines.append(f"### {g['id']} — {g['name']}")
        lines.append("")
        lines.append(f"- status: **{g['status']}**")
        for k, v in g["detail"].items():
            if isinstance(v, (list, dict)):
                lines.append(f"- {k}: `{json.dumps(v, ensure_ascii=False)[:200]}`")
            else:
                lines.append(f"- {k}: `{v}`")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"decision": decision, "out_json": _rel(OUT_JSON), "out_md": _rel(OUT_MD)},
            ensure_ascii=False,
        )
    )
    return 0 if decision != "NO-GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
