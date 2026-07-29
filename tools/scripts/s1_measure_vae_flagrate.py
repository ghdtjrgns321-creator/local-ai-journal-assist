"""S1 측정 — VAE 정상 플래그율(1차 관문) 재현 스크립트.

사용: uv run python tools/scripts/s1_measure_vae_flagrate.py <base_dir>
      [--train-rows N] [--calibration-rows N] [--out PATH]

  --train-rows        학습 표본 상한(기본 50,000 = 2026-07 기록 회차 조건). 0 이하면 전 행.
  --calibration-rows  확인용 표본 상한(기본 50,000). 학습에 쓰지 않은 전표에서만 뽑는다.

배경: `reports/s1_normal_s10/vae_flagrate.json` 은 1회성 실행으로 만들어졌고 생성
      스크립트가 리포에 없었다. 학습 표본 상한을 바꿔 재측정하려면 같은 조건을 재현할
      코드가 있어야 하므로 본 스크립트로 고정한다(2026-07-26).

절차 (라벨 미사용 학습 원칙 — feedback_unsupervised_no_y):
  1) base 정상 원장에 파이프라인 실행 → phase2 피처 입력 준비.
  2) 전표(document_id) 단위로 학습용 / 확인용을 겹치지 않게 분할.
     행 단위로 나누면 한 전표의 행이 양쪽에 걸려 누수가 된다.
  3) 학습용만으로 UnsupervisedDetector 학습 → 임계는 학습 분포 상위 1%.
  4) 학습용·확인용 각각의 플래그율을 재고, 확인용 ÷ 오염설정 비율을 판정값으로 낸다.
     사전 선언 대역 [0.3배, 3배] 안이면 PASS.

주의: 학습 표본을 20만 행으로 올리면 학습만 30분 안팎 — 분리 실행 권장.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TRAIN_ROWS = 50_000
DEFAULT_CALIBRATION_ROWS = 50_000
SPLIT_SEED = 20260718
GROUP_COLUMN = "document_id"
DECLARED_BAND = (0.3, 3.0)


def _featured_df(dataset_dir: Path) -> pd.DataFrame:
    from src.pipeline import AuditPipeline

    res = AuditPipeline(skip_db=True).run(str(dataset_dir / "journal_entries.csv"))
    # Why: s5_measure_vae_performance 와 동일 이유 — 탐지 전 스냅샷을 쓴다.
    return res.featured_data if res.featured_data is not None else res.data


def _take_groups_until(
    groups_order: list,
    rows_by_group: dict,
    row_budget: int,
) -> list:
    """전표를 순서대로 담아 행 예산을 채운다. 예산 0 이하면 전부 담는다."""
    if row_budget <= 0:
        return list(groups_order)
    taken, total = [], 0
    for gid in groups_order:
        if total >= row_budget:
            break
        taken.append(gid)
        total += rows_by_group[gid]
    return taken


def _split_by_document(
    frame: pd.DataFrame,
    doc_ids: pd.Series,
    train_rows: int,
    calibration_rows: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rows_by_group = doc_ids.value_counts().to_dict()
    order = list(rows_by_group.keys())
    rng = np.random.default_rng(SPLIT_SEED)
    rng.shuffle(order)

    train_groups = _take_groups_until(order, rows_by_group, train_rows)
    train_set = set(train_groups)
    remaining = [gid for gid in order if gid not in train_set]
    calib_groups = set(_take_groups_until(remaining, rows_by_group, calibration_rows))

    train_mask = doc_ids.isin(train_set).to_numpy()
    calib_mask = doc_ids.isin(calib_groups).to_numpy()
    meta = {
        "documents_total": len(order),
        "documents_train": len(train_set),
        "documents_calibration": len(calib_groups),
        "documents_unused": len(order) - len(train_set) - len(calib_groups),
    }
    return frame.loc[train_mask], frame.loc[calib_mask], meta


def main() -> int:
    from config.settings import get_settings
    from src.detection.vae_detector import UnsupervisedDetector
    from src.services.phase2_training_service import (
        apply_unsupervised_matrix,
        fit_unsupervised_matrix_builder,
        matrix_feature_groups,
        prepare_phase2_feature_inputs,
    )

    parser = argparse.ArgumentParser(prog="s1_measure_vae_flagrate.py")
    parser.add_argument("base_dir")
    parser.add_argument("--train-rows", type=int, default=DEFAULT_TRAIN_ROWS)
    parser.add_argument("--calibration-rows", type=int, default=DEFAULT_CALIBRATION_ROWS)
    parser.add_argument(
        "--out", default="", help="출력 JSON 경로(기본: reports/<base>/vae_flagrate.json)"
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    settings = get_settings()

    print(f"=== base 준비: {base_dir.name} ===", flush=True)
    base_df = _featured_df(base_dir)
    print(f"[진행] 파이프라인 완료 {len(base_df)}행 × {base_df.shape[1]}컬럼", flush=True)
    cleaned, _groups, payload = prepare_phase2_feature_inputs(base_df, settings=settings)
    print(f"[진행] 피처 입력 준비 완료 {len(cleaned)}행 × {cleaned.shape[1]}컬럼", flush=True)

    if GROUP_COLUMN not in base_df.columns:
        print(f"오류: {GROUP_COLUMN} 컬럼이 없어 전표 단위 분할을 할 수 없다", flush=True)
        return 1
    doc_ids = base_df.loc[cleaned.index, GROUP_COLUMN].astype(str)

    train_X, calib_X, split_meta = _split_by_document(
        cleaned, doc_ids, args.train_rows, args.calibration_rows
    )
    print(
        f"분할: 학습 {len(train_X)}행 / 확인용 {len(calib_X)}행"
        f" (모집단 {len(cleaned)}행 · 전표 {split_meta['documents_total']})",
        flush=True,
    )
    if len(calib_X) == 0:
        print("오류: 확인용 표본이 0행 — 학습 상한이 모집단 전부를 먹었다", flush=True)
        return 1

    # Why: 제품 학습과 같은 매트릭스 빌더를 태운다 (2026-07-28 경로 통합).
    #      상세는 s5_measure_vae_performance.py 의 같은 구간 주석 참조.
    builder = fit_unsupervised_matrix_builder(
        train_X,
        payload["preprocessing_plan"],
        settings=settings,
    )
    train_matrix = apply_unsupervised_matrix(builder, train_X)

    start = time.perf_counter()
    det = UnsupervisedDetector(settings)
    train_info = det.train(train_matrix, matrix_feature_groups(train_matrix))
    det.set_phase2_matrix_state(builder)
    elapsed = time.perf_counter() - start

    threshold = float(train_info["ensemble_threshold"])
    train_scores = pd.to_numeric(det.detect(train_X).scores, errors="coerce").fillna(0.0)
    calib_scores = pd.to_numeric(det.detect(calib_X).scores, errors="coerce").fillna(0.0)
    flag_train = float((train_scores > threshold).mean())
    flag_calib = float((calib_scores > threshold).mean())

    contamination = float(settings.if_contamination)
    ratio = flag_calib / contamination if contamination else float("nan")
    verdict = "PASS" if DECLARED_BAND[0] <= ratio <= DECLARED_BAND[1] else "FAIL"

    report = {
        "dataset": base_dir.name,
        "train_rows": int(len(train_X)),
        "calibration_rows": int(len(calib_X)),
        "train_population_rows": int(len(cleaned)),
        "split": split_meta,
        "n_features_source": int(train_X.shape[1]),
        "n_features": int(train_matrix.shape[1]),
        "threshold": threshold,
        "if_contamination_setting": contamination,
        "flag_rate_train": round(flag_train, 5),
        "flag_rate_calibration": round(flag_calib, 5),
        "calib_over_contamination_ratio": round(ratio, 3),
        "declared_band": list(DECLARED_BAND),
        "verdict": verdict,
        "vae_diagnostics": train_info.get("vae_diagnostics", {}),
        "elapsed_sec": round(elapsed, 1),
    }

    out_path = (
        Path(args.out)
        if args.out
        else ROOT / "reports" / f"s1_vae_flagrate_{base_dir.name}" / "vae_flagrate.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    print(f"저장: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
