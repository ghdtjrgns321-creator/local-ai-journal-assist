"""S5 측정 — VAE(PHASE2) 부정 농축 성능 + PHASE1 빌더와의 상보성.

사용: uv run python tools/scripts/s5_measure_vae_performance.py <base_dir> <fraud_dir> [...]

절차 (라벨 미사용 학습 원칙 — feedback_unsupervised_no_y):
  1) base(s10 정상)에 파이프라인 실행 → featured df → phase2 피처 입력 준비 →
     50,000행 표본으로 UnsupervisedDetector 학습 (S1 vae_flagrate 측정과 동일 조건).
  2) 각 fraud 데이터셋: 파이프라인 실행 → 동일 준비 → detect → 행 점수(ECDF percentile).
  3) 문서 단위 점수 = 행 점수 max. truth(provenance) 대비:
     AUROC / recall@top1% / recall@top0.5% / scheme별 top1% 적중.
  4) 상보성: PHASE1 빌더 측정(reports/s5_fraud_overlay/builder_performance_*.json)의
     missed_docs(검토 표면 미달 부정)가 VAE top1%에 얼마나 올라오는가.

주의: base+fraud 4벌 전수 실행이라 1시간+ — nohup 분리 실행 필수.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "reports/s5_fraud_overlay"
TRAIN_SAMPLE_ROWS = 50_000
TRAIN_SAMPLE_SEED = 20260718


def _featured_df(dataset_dir: Path) -> pd.DataFrame:
    from src.pipeline import AuditPipeline

    res = AuditPipeline(skip_db=True).run(str(dataset_dir / "journal_entries.csv"))
    return res.data


def _auroc(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(scores)
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    pos = labels.astype(bool)
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main() -> int:
    from src.detection.vae_detector import UnsupervisedDetector
    from src.services.phase2_training_service import prepare_phase2_feature_inputs

    if len(sys.argv) < 3:
        print("usage: s5_measure_vae_performance.py <base_dir> <fraud_dir> [...]")
        return 2
    base_dir = Path(sys.argv[1])
    fraud_dirs = [Path(a) for a in sys.argv[2:]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from config.settings import get_settings as _gs

    settings = _gs()

    print(f"=== base 학습: {base_dir.name} ===", flush=True)
    base_df = _featured_df(base_dir)
    cleaned, groups, _payload = prepare_phase2_feature_inputs(base_df, settings=settings)
    if len(cleaned) > TRAIN_SAMPLE_ROWS:
        train_X = cleaned.sample(n=TRAIN_SAMPLE_ROWS, random_state=TRAIN_SAMPLE_SEED)
    else:
        train_X = cleaned
    det = UnsupervisedDetector(settings)
    det.train(train_X, groups)
    print(f"학습 완료: {len(train_X)}행 × {train_X.shape[1]}피처", flush=True)

    reports = []
    for fdir in fraud_dirs:
        print(f"=== 채점: {fdir.name} ===", flush=True)
        fdf = _featured_df(fdir)
        fclean, _, _ = prepare_phase2_feature_inputs(fdf, settings=settings)
        result = det.detect(fclean)
        scores = pd.to_numeric(result.scores, errors="coerce").fillna(0.0)

        doc_ids = fdf["document_id"].astype(str)
        doc_score = scores.groupby(doc_ids.to_numpy()).max()

        prov = pd.read_csv(fdir / "labels" / "phase2_scheme_provenance.csv", dtype=str)
        fraud_docs = set(prov["document_id"])
        doc_scheme = dict(zip(prov["document_id"], prov["scheme_id"], strict=False))

        labels = np.array([1 if d in fraud_docs else 0 for d in doc_score.index])
        svals = doc_score.to_numpy()
        auroc = _auroc(labels, svals)

        def topk(frac: float):
            k = max(1, int(len(doc_score) * frac))
            top_docs = set(doc_score.sort_values(ascending=False).head(k).index)
            hit = top_docs & fraud_docs
            per_scheme: dict[str, int] = {}
            for d in hit:
                per_scheme[doc_scheme[d]] = per_scheme.get(doc_scheme[d], 0) + 1
            return k, hit, per_scheme

        k1, hit1, scheme1 = topk(0.01)
        k05, hit05, _ = topk(0.005)

        # 상보성: PHASE1 빌더 미표면 부정의 VAE top1% 노출
        comp = None
        bp_path = OUT_DIR / f"builder_performance_{fdir.name}.json"
        if bp_path.exists():
            bp = json.loads(bp_path.read_text(encoding="utf-8"))
            missed = set(bp["surface_coverage"]["missed_docs"])
            top1_docs = set(doc_score.sort_values(ascending=False).head(k1).index)
            comp = {
                "phase1_missed_docs": len(missed),
                "vae_top1pct_recovers": len(missed & top1_docs),
                "recovered_schemes": sorted(
                    {doc_scheme[d] for d in (missed & top1_docs) if d in doc_scheme}
                ),
            }

        rep = {
            "dataset": fdir.name,
            "documents_total": int(len(doc_score)),
            "fraud_docs_total": len(fraud_docs),
            "auroc_document": round(auroc, 4),
            "recall_at_top1pct": round(len(hit1) / len(fraud_docs), 4),
            "recall_at_top05pct": round(len(hit05) / len(fraud_docs), 4),
            "top1pct_k": k1,
            "top1pct_per_scheme": scheme1,
            "phase1_complementarity": comp,
        }
        reports.append(rep)
        out = OUT_DIR / f"vae_performance_{fdir.name}.json"
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"AUROC(doc) {rep['auroc_document']} | recall@1% {rep['recall_at_top1pct']}"
            f" | recall@0.5% {rep['recall_at_top05pct']} | 상보성 {comp}",
            flush=True,
        )

    if len(reports) > 1:
        agg = {
            "datasets": [r["dataset"] for r in reports],
            "auroc_mean": round(float(np.mean([r["auroc_document"] for r in reports])), 4),
            "recall_at_top1pct_mean": round(
                float(np.mean([r["recall_at_top1pct"] for r in reports])), 4
            ),
            "recovered_by_vae_total": sum(
                (r["phase1_complementarity"] or {}).get("vae_top1pct_recovers", 0) for r in reports
            ),
        }
        (OUT_DIR / "vae_performance_aggregate.json").write_text(
            json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("=== seed 합산 ===", flush=True)
        print(json.dumps(agg, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
