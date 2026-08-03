"""S5 측정 — VAE(PHASE2) 부정 농축 성능 + PHASE1 빌더와의 상보성.

사용: uv run python tools/scripts/s5_measure_vae_performance.py <base_dir> <fraud_dir> [...]
      [--train-rows N] [--tag SUFFIX]

  --train-rows  학습 표본 상한(기본 200,000). 0 이하면 전 행 사용.
  --tag         출력 파일명 접미어. reports/ 는 git 미추적이라 접미어 없이 재실행하면
                기존 산출물을 복원 불가하게 덮어쓴다.

절차 (라벨 미사용 학습 원칙 — feedback_unsupervised_no_y):
  1) base(s10 정상)에 파이프라인 실행 → featured df → phase2 피처 입력 준비 →
     **제품과 같은 매트릭스 빌더**로 변환 → --train-rows 표본으로 UnsupervisedDetector
     학습 (S1 vae_flagrate 측정과 동일 조건).
  2) 각 fraud 데이터셋: 파이프라인 실행 → 동일 준비 → detect(적합된 빌더가 자동 변환)
     → 행 점수(ECDF percentile).
  3) 문서 단위 점수 = 행 점수 max. truth(provenance) 대비:
     AUROC / recall@top1% / recall@top0.5% / scheme별 top1% 적중.
  4) 상보성: PHASE1 빌더 측정(reports/s5_fraud_overlay/builder_performance_*.json)의
     missed_docs(검토 표면 미달 부정)가 VAE top1%에 얼마나 올라오는가.

주의: base+fraud 4벌 전수 실행이라 1시간+ — nohup 분리 실행 필수.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "reports/s5_fraud_overlay"
# 5만 행은 근거 없이 굳어 있던 값이고 그 조건의 수치는 전부 인용 불가로 철회됐다
# (2026-07-26: 차단 설정을 그대로 두고 표본만 20만으로 올리자 결과가 뒤집혔다).
# 20만 행이 현행 기준이다.
DEFAULT_TRAIN_SAMPLE_ROWS = 200_000
TRAIN_SAMPLE_SEED = 20260718


def _featured_df(dataset_dir: Path) -> pd.DataFrame:
    from src.pipeline import AuditPipeline
    from src.preprocessing.phase2_features import PHASE2_INPUT_COLUMNS

    res = AuditPipeline(skip_db=True).run(str(dataset_dir / "journal_entries.csv"))
    # Why: res.data 는 aggregate 결과가 되쓰인 프레임이라 PHASE1 산출물(anomaly_score 등)이
    #      섞여 있다. featured_data 는 탐지 전 스냅샷 — 운영 PHASE2 학습이 받는 것과 같다.
    #      (2026-07-28 발견: 이 차이로 VAE 입력 71칸에 PHASE1 출력 6개가 들어와 있었다)
    featured = res.featured_data if res.featured_data is not None else res.data
    # Why: 16GB 장비에서 학습·프로파일링 중 프로세스가 조용히 죽는다(2026-07-29, 4회).
    #      파이프라인이 내는 98칸 중 PHASE2 가 쓰는 것은 허용 목록 + 파생 재료뿐이고,
    #      나머지 48칸은 PHASE1 룰용 파생이라 355,786행만큼 들고 다닐 이유가 없다.
    #      허용 목록 전환 뒤로는 결과에 영향이 없으면서 메모리만 먹는 짐이다.
    keep = [c for c in featured.columns if c in PHASE2_INPUT_COLUMNS or c == "document_id"]
    trimmed = featured.loc[:, keep].copy()
    del featured, res
    gc.collect()
    return trimmed


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
    from src.services.phase2_training_service import (
        apply_unsupervised_matrix,
        fit_unsupervised_matrix_builder,
        matrix_feature_groups,
        prepare_phase2_feature_inputs,
    )

    parser = argparse.ArgumentParser(prog="s5_measure_vae_performance.py")
    parser.add_argument("base_dir")
    parser.add_argument("fraud_dirs", nargs="+")
    parser.add_argument(
        "--train-rows",
        type=int,
        default=DEFAULT_TRAIN_SAMPLE_ROWS,
        help="학습 표본 상한. 0 이하면 전 행 사용",
    )
    parser.add_argument("--tag", default="", help="출력 파일명 접미어(기존 산출물 보존용)")
    parser.add_argument(
        "--model-cache",
        default="",
        help=(
            "학습 모델 캐시 경로. 있으면 불러 쓰고 없으면 학습 후 저장한다. "
            "base 학습은 벌마다 완전히 같은 작업이라 반복할 이유가 없다"
        ),
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    fraud_dirs = [Path(a) for a in args.fraud_dirs]
    train_rows = int(args.train_rows)
    tag = f"_{args.tag}" if args.tag else ""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from config.settings import get_settings as _gs

    settings = _gs()

    # Why: base 학습은 벌마다 완전히 같은 작업인데, 그 구간이 메모리 최대 점유 지점이라
    #      16GB 장비에서 간헐적으로 프로세스가 죽는다(2026-07-29, 5회). 4벌을 재려고
    #      같은 학습을 4번 반복하면 위험 구간을 4번 지난다. 한 번 학습해 저장하고
    #      채점만 따로 돌리면 각 실행이 짧아지고, 4벌이 같은 모델로 채점됨도 보장된다.
    cache_path = Path(args.model_cache) if args.model_cache else None
    if cache_path is not None and cache_path.exists():
        import pickle

        print(f"=== 학습 모델 재사용: {cache_path.name} ===", flush=True)
        with cache_path.open("rb") as fh:
            bundle = pickle.load(fh)
        det = bundle["detector"]
        n_train = int(bundle["n_train"])
        population_rows = int(bundle["population_rows"])
        return _score_all(
            det,
            fraud_dirs,
            settings=settings,
            n_train=n_train,
            population_rows=population_rows,
            train_rows=train_rows,
            tag=tag,
            prepare=prepare_phase2_feature_inputs,
        )

    print(f"=== base 학습: {base_dir.name} ===", flush=True)
    base_df = _featured_df(base_dir)
    cleaned, _groups, payload = prepare_phase2_feature_inputs(base_df, settings=settings)
    # Why: prepare 구간에 355,786행 프레임이 셋 겹친다(입력·허용 사본·정제 사본).
    #      base_df 는 여기서 역할이 끝나므로 표본 추출 전에 놓는다.
    del base_df
    gc.collect()
    population_rows = int(len(cleaned))
    if 0 < train_rows < len(cleaned):
        train_X = cleaned.sample(n=train_rows, random_state=TRAIN_SAMPLE_SEED)
    else:
        train_X = cleaned
    n_train = int(len(train_X))

    # Why: 16GB 장비에서 학습 중 프로세스가 조용히 죽는다(2026-07-29, 같은 지점 3회).
    #      학습 시점에 base 파이프라인 프레임(355,786행 × 98칸)과 허용 프레임,
    #      매트릭스(200,000 × 385 float64 ≈ 616MB), torch 텐서 사본이 동시에 살아 있다.
    #      cleaned 는 표본을 뽑은 뒤로는 쓰지 않으므로 여기서 놓는다.
    del cleaned
    gc.collect()

    # Why: 제품 학습(phase2_training_service._execute_model_trial)이 쓰는 것과 같은
    #      매트릭스를 만든다. 2026-07-28 이전에는 여기서 detector.train(cleaned, groups)를
    #      직접 불러 OrdinalEncoder 무스케일·고카디널리티 버림 경로를 탔고, 그 결과
    #      측정값이 제품 동작을 설명하지 못했다.
    builder = fit_unsupervised_matrix_builder(
        train_X,
        payload["preprocessing_plan"],
        settings=settings,
    )
    train_matrix = apply_unsupervised_matrix(builder, train_X)
    det = UnsupervisedDetector(settings)
    det.train(train_matrix, matrix_feature_groups(train_matrix))
    det.set_phase2_matrix_state(builder)
    print(
        f"학습 완료: {n_train}행 × 원본 {train_X.shape[1]}칸"
        f" → 매트릭스 {train_matrix.shape[1]}칸"
        f" (모집단 {population_rows}행 · 상한 인자 {train_rows})",
        flush=True,
    )
    del train_X, train_matrix, payload, builder
    gc.collect()

    if cache_path is not None:
        import pickle

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("wb") as fh:
            pickle.dump(
                {"detector": det, "n_train": n_train, "population_rows": population_rows},
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        print(f"학습 모델 저장: {cache_path}", flush=True)

    return _score_all(
        det,
        fraud_dirs,
        settings=settings,
        n_train=n_train,
        population_rows=population_rows,
        train_rows=train_rows,
        tag=tag,
        prepare=prepare_phase2_feature_inputs,
    )


def _score_all(
    det,
    fraud_dirs,
    *,
    settings,
    n_train: int,
    population_rows: int,
    train_rows: int,
    tag: str,
    prepare,
) -> int:
    """적합된 탐지기로 각 부정 데이터셋을 채점한다."""
    prepare_phase2_feature_inputs = prepare
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

        # 상보성: PHASE1 빌더 미표면 부정의 VAE top1% 노출.
        # 분모는 무정보 룰(lift <= 1.0)을 뺀 미표면을 쓴다 — 전체 룰 기준 미표면은 r9 에서
        # 0~2건이라 지표가 죽는다. 무정보 룰만으로 오른 문서는 감사인이 그 룰을 골라도
        # 정상이 같은 비율로 딸려오므로 실제로는 표면화된 것이 아니다(2026-07-28).
        comp = None
        bp_path = OUT_DIR / f"builder_performance_{fdir.name}.json"
        if bp_path.exists():
            bp = json.loads(bp_path.read_text(encoding="utf-8"))
            informative = bp.get("surface_coverage_informative", {})
            basis = "informative" if "missed_docs" in informative else "all_rules"
            missed = set(
                informative["missed_docs"]
                if basis == "informative"
                else bp["surface_coverage"]["missed_docs"]
            )
            top1_docs = set(doc_score.sort_values(ascending=False).head(k1).index)
            comp = {
                "basis": basis,
                "phase1_missed_docs": len(missed),
                "vae_top1pct_recovers": len(missed & top1_docs),
                "recovered_schemes": sorted(
                    {doc_scheme[d] for d in (missed & top1_docs) if d in doc_scheme}
                ),
            }
            # Why: 재측정 없이 다른 분모로 다시 계산할 수 있도록 상위 1% 문서를 남긴다.
            #      지금까지는 점수를 저장하지 않아 분모를 바꿀 때마다 1시간짜리 재실행이 필요했다.
            rep_top1_path = OUT_DIR / f"vae_top1pct_docs_{fdir.name}{tag}.json"
            rep_top1_path.write_text(
                json.dumps(sorted(top1_docs), indent=0, ensure_ascii=False), encoding="utf-8"
            )

        rep = {
            "dataset": fdir.name,
            "train_rows": n_train,
            "train_population_rows": population_rows,
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
        out = OUT_DIR / f"vae_performance_{fdir.name}{tag}.json"
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"AUROC(doc) {rep['auroc_document']} | recall@1% {rep['recall_at_top1pct']}"
            f" | recall@0.5% {rep['recall_at_top05pct']} | 상보성 {comp}",
            flush=True,
        )

    if len(reports) > 1:
        agg = {
            "datasets": [r["dataset"] for r in reports],
            "train_rows": n_train,
            "train_population_rows": population_rows,
            "auroc_mean": round(float(np.mean([r["auroc_document"] for r in reports])), 4),
            "recall_at_top1pct_mean": round(
                float(np.mean([r["recall_at_top1pct"] for r in reports])), 4
            ),
            "recovered_by_vae_total": sum(
                (r["phase1_complementarity"] or {}).get("vae_top1pct_recovers", 0) for r in reports
            ),
        }
        (OUT_DIR / f"vae_performance_aggregate{tag}.json").write_text(
            json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("=== seed 합산 ===", flush=True)
        print(json.dumps(agg, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
