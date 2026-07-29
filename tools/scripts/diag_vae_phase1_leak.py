"""VAE 입력의 PHASE1 출력 오염 정량화 — 있을 때 vs 뺐을 때.

사용: uv run python tools/scripts/diag_vae_phase1_leak.py <base_dir> <fraud_dir> [--train-rows N]

배경(2026-07-28): VAE 입력 71칸에 PHASE1 탐지 출력 6개가 섞여 있음을 확인했다.
`AuditPipeline.run()` 이 `for col in agg_df.columns: df[col] = agg_df[col].values`
(src/pipeline.py:880)로 집계 결과를 원본 DF 에 되쓰고, 그 DF 가 그대로
`prepare_phase2_feature_inputs` 에 들어가기 때문이다. deny 목록 52개는 이 컬럼들을
막지 않는다.

3-surface 비병합 원칙(PHASE1/PHASE2 독립, 9장 §9.4)의 위반이므로 영향을 잰다.
같은 학습 조건에서 해당 컬럼만 빼고 다시 학습·채점해 AUROC 차이를 본다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports/s5_fraud_overlay"
TRAIN_SEED = 20260718

# PHASE1 탐지·케이스 산출물. has_risk_keyword 는 피처엔진 텍스트 피처라 제외한다.
PHASE1_OUTPUT_COLUMNS = [
    "anomaly_score",
    "risk_level",
    "flagged_rules",
    "review_rules",
    "risk_floor_reasons",
    "topside_score",
]


def auc(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(scores)
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    pos = labels.astype(bool)
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_dir")
    parser.add_argument("fraud_dir")
    parser.add_argument("--train-rows", type=int, default=200000)
    args = parser.parse_args()

    from config.settings import get_settings
    from src.detection.vae_detector import UnsupervisedDetector
    from src.pipeline import AuditPipeline
    from src.services.phase2_training_service import prepare_phase2_feature_inputs

    settings = get_settings()
    base_dir, fraud_dir = Path(args.base_dir), Path(args.fraud_dir)

    print("=== 파이프라인 실행 ===", flush=True)
    base_df = AuditPipeline(skip_db=True).run(str(base_dir / "journal_entries.csv")).data
    fraud_res = AuditPipeline(skip_db=True).run(str(fraud_dir / "journal_entries.csv"))
    fraud_df = fraud_res.data

    base_clean, groups, _ = prepare_phase2_feature_inputs(base_df, settings=settings)
    fraud_clean, _, _ = prepare_phase2_feature_inputs(fraud_df, settings=settings)

    present = [c for c in PHASE1_OUTPUT_COLUMNS if c in base_clean.columns]
    print(
        f"VAE 입력 {base_clean.shape[1]}칸 · PHASE1 출력 {len(present)}개: {present}\n", flush=True
    )

    prov = pd.read_csv(fraud_dir / "labels/phase2_scheme_provenance.csv", dtype=str)
    fraud_docs = set(prov["document_id"])
    doc_ids = fraud_df["document_id"].astype(str)

    results = {}
    for label, drop in (("현행(PHASE1 출력 포함)", []), ("PHASE1 출력 제거", present)):
        train_src = base_clean.drop(columns=drop, errors="ignore")
        score_src = fraud_clean.drop(columns=drop, errors="ignore")
        # 그룹 정의도 같이 정리 — 제거한 컬럼이 남아 있으면 전처리가 찾다 실패한다.
        trimmed = groups
        if drop:
            import copy

            trimmed = copy.deepcopy(groups)
            for attr in vars(trimmed):
                value = getattr(trimmed, attr)
                if isinstance(value, list):
                    setattr(trimmed, attr, [c for c in value if c not in drop])

        train_x = (
            train_src.sample(n=args.train_rows, random_state=TRAIN_SEED)
            if 0 < args.train_rows < len(train_src)
            else train_src
        )
        det = UnsupervisedDetector(settings)
        det.train(train_x, trimmed)
        scores = pd.to_numeric(det.detect(score_src).scores, errors="coerce").fillna(0.0)
        doc_score = scores.groupby(doc_ids.to_numpy()).max()
        labels = np.array([1 if d in fraud_docs else 0 for d in doc_score.index])
        values = doc_score.to_numpy()
        k = max(1, int(len(doc_score) * 0.01))
        top = set(doc_score.sort_values(ascending=False).head(k).index)
        results[label] = {
            "features": int(train_x.shape[1]),
            "auroc": round(auc(labels, values), 4),
            "recall_at_top1pct": round(len(top & fraud_docs) / len(fraud_docs), 4),
        }
        print(f"{label}: {results[label]}", flush=True)

    a = results["현행(PHASE1 출력 포함)"]["auroc"]
    b = results["PHASE1 출력 제거"]["auroc"]
    print(f"\nAUROC 차이: {a} → {b} ({b - a:+.4f})")
    payload = {"dataset": fraud_dir.name, "train_rows": args.train_rows, "results": results}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"vae_phase1_leak_{fraud_dir.name}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
