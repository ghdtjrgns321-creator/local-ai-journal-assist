"""Stage 7 — BiLSTM 시퀀스 윈도우 누수 조사.

목적:
    src/preprocessing/sequence_builder.py 의 (created_by, posting_date)
    sliding window 가 v3 truth doc 주변에서 시계열 누수를 만드는지 검사한다.

조사 항목:
    1. truth doc 라인의 (created_by, posting_date) 좌표 추출
    2. seq_len=16, stride=1 윈도우에서 truth 라인이 위치별 0~15 어디에 분포하는지
       (윈도우 라벨 시점 vs 컨텍스트 시점 구분)
    3. GroupKFold(groups=created_by) 분할에서 truth 윈도우의 train/val 비율
    4. user-year holdout 적용 후 test truth 시점을 train 이 본 적이 있는지
       (같은 posting_date 및 ±7일 기준)

출력:
    artifacts/S7_sequence_window_leakage.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.preprocessing.split_strategy import split_user_year_holdout  # noqa: E402

DATA_ROOT = PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"
JOURNAL_CSV = DATA_ROOT / "journal_entries.csv"
TRUTH_CSV = DATA_ROOT / "labels" / "manipulated_entry_truth.csv"
OUT_JSON = PROJECT_ROOT / "artifacts" / "S7_sequence_window_leakage.json"

SEQ_LEN = 16
STRIDE = 1
N_SPLITS = 5
RANDOM_STATE = 42


def load_journal_minimal() -> pd.DataFrame:
    """라인 단위 journal 로드 — 시퀀스 인덱싱에 필요한 컬럼만."""
    cols = ["document_id", "created_by", "posting_date", "line_number"]
    df = pd.read_csv(JOURNAL_CSV, usecols=cols, dtype={"line_number": "Int64"})
    df["posting_date"] = pd.to_datetime(df["posting_date"], errors="coerce")
    df = df.dropna(subset=["created_by", "posting_date"]).reset_index(drop=True)
    return df


def load_truth_doc_ids() -> set[str]:
    truth = pd.read_csv(TRUTH_CSV, usecols=["document_id"])
    return set(truth["document_id"].astype(str).unique())


def assign_user_positions(df: pd.DataFrame) -> pd.DataFrame:
    """sequence_builder 와 동일하게 (created_by) 그룹 내 (posting_date, line_number) 안정 정렬."""
    # Why: sequence_builder.py 는 timestamps 안정정렬(np.argsort kind=stable) 사용 →
    #       pandas mergesort 와 동등.
    df = df.sort_values(
        ["created_by", "posting_date", "line_number"], kind="mergesort"
    ).reset_index(drop=True)
    df["user_pos"] = df.groupby("created_by").cumcount()
    df["user_size"] = df.groupby("created_by")["created_by"].transform("size")
    return df


def compute_window_position_histogram(
    df: pd.DataFrame, truth_doc_ids: set[str]
) -> tuple[dict, dict]:
    """truth 라인이 슬라이딩 윈도우 내 어느 position(0~15) 에 들어가는지 히스토그램.

    Returns:
        (target_step_only, all_positions): position → 카운트
        - target_step_only: 윈도우 label 이 1 인 (truth 라인이 position=15) 케이스만
        - all_positions: truth 라인이 등장하는 모든 윈도우 (position 0~15 누적)
    """
    is_truth = df["document_id"].astype(str).isin(truth_doc_ids).to_numpy()
    user_pos = df["user_pos"].to_numpy()
    user_size = df["user_size"].to_numpy()

    all_positions: Counter = Counter()
    target_step_only: Counter = Counter()

    truth_idx = np.where(is_truth)[0]
    for i in truth_idx:
        pos = int(user_pos[i])
        size = int(user_size[i])
        if size < SEQ_LEN:
            # padded 단일 윈도우: truth 가 패딩 뒤쪽 (pad_len + pos) 위치
            pad_len = SEQ_LEN - size
            position = pad_len + pos
            all_positions[position] += 1
            if position == SEQ_LEN - 1:
                target_step_only[position] += 1
            continue

        # 슬라이딩 윈도우: pos 에 truth 가 있을 때, 이 truth 를 포함하는
        # 윈도우의 시작점은 [max(0, pos-SEQ_LEN+1), min(pos, size-SEQ_LEN)] 범위.
        start_min = max(0, pos - SEQ_LEN + 1)
        start_max = min(pos, size - SEQ_LEN)
        for start in range(start_min, start_max + 1, STRIDE):
            position_in_window = pos - start
            all_positions[position_in_window] += 1
            if position_in_window == SEQ_LEN - 1:
                target_step_only[position_in_window] += 1

    return dict(target_step_only), dict(all_positions)


def compute_group_kfold_split(df: pd.DataFrame, truth_doc_ids: set[str]) -> dict:
    """GroupKFold(groups=created_by) 분할에서 truth 윈도우의 train/val 비율."""
    is_truth = df["document_id"].astype(str).isin(truth_doc_ids).to_numpy()
    user_ids = df["created_by"].to_numpy()
    user_pos = df["user_pos"].to_numpy()
    user_size = df["user_size"].to_numpy()

    # 각 user 별 윈도우 = (created_by, target_step_position) target step 만 라벨링
    # 여기서는 user 단위로만 fold 를 가르므로, user 별 truth 윈도우 수 집계.
    truth_target_window_user: list[str] = []
    truth_context_window_user: list[str] = []

    truth_idx = np.where(is_truth)[0]
    for i in truth_idx:
        pos = int(user_pos[i])
        size = int(user_size[i])
        uid = user_ids[i]
        if size < SEQ_LEN:
            truth_target_window_user.append(uid)
            continue
        start_min = max(0, pos - SEQ_LEN + 1)
        start_max = min(pos, size - SEQ_LEN)
        for start in range(start_min, start_max + 1, STRIDE):
            position_in_window = pos - start
            if position_in_window == SEQ_LEN - 1:
                truth_target_window_user.append(uid)
            else:
                truth_context_window_user.append(uid)

    # GroupKFold
    gkf = GroupKFold(n_splits=N_SPLITS)
    fold_dist: dict[int, dict] = {}

    all_user_ids = df["created_by"].to_numpy()
    # GroupKFold 는 X 길이 = groups 길이 만 만족하면 됨; dummy y
    dummy_y = np.zeros(len(df), dtype=np.int8)

    target_user_arr = np.array(truth_target_window_user)
    context_user_arr = np.array(truth_context_window_user)

    for fold_i, (train_idx, val_idx) in enumerate(
        gkf.split(np.zeros(len(df)), dummy_y, groups=all_user_ids)
    ):
        train_users = set(all_user_ids[train_idx].tolist())
        val_users = set(all_user_ids[val_idx].tolist())

        target_train = (
            int(np.isin(target_user_arr, list(train_users)).sum()) if len(target_user_arr) else 0
        )
        target_val = (
            int(np.isin(target_user_arr, list(val_users)).sum()) if len(target_user_arr) else 0
        )
        context_train = (
            int(np.isin(context_user_arr, list(train_users)).sum()) if len(context_user_arr) else 0
        )
        context_val = (
            int(np.isin(context_user_arr, list(val_users)).sum()) if len(context_user_arr) else 0
        )

        # 같은 user 가 양쪽 fold 에 노출되는지 (GroupKFold 보장: 0 이어야 함)
        overlap_users = train_users & val_users

        fold_dist[fold_i] = {
            "n_train_rows": int(len(train_idx)),
            "n_val_rows": int(len(val_idx)),
            "n_train_users": len(train_users),
            "n_val_users": len(val_users),
            "truth_target_train": target_train,
            "truth_target_val": target_val,
            "truth_context_train": context_train,
            "truth_context_val": context_val,
            "user_overlap_count": len(overlap_users),
        }

    return fold_dist


def compute_temporal_context_leakage(df: pd.DataFrame, truth_doc_ids: set[str]) -> dict:
    """User-year holdout test truth dates that overlap train posting dates."""
    is_truth = df["document_id"].astype(str).isin(truth_doc_ids).to_numpy()
    posting_dates = df["posting_date"].to_numpy()

    split = split_user_year_holdout(df)
    truth_row_idx = np.where(is_truth)[0]
    train_idx = split.train_idx
    test_idx = split.test_idx
    test_set = set(test_idx.tolist())
    train_dates = pd.Series(posting_dates[train_idx])
    train_date_set = set(train_dates.unique())
    test_truth_idx = [i for i in truth_row_idx if i in test_set]

    if not test_truth_idx:
        return {
            split.policy: {
                "val_truth_rows": 0,
                "val_unique_truth_dates": 0,
                "dates_with_train_overlap": 0,
                "dates_unique_to_val": 0,
                "ratio_overlap": None,
            }
        }

    test_truth_dates = pd.Series(posting_dates[test_truth_idx]).unique()
    overlap_dates = [d for d in test_truth_dates if d in train_date_set]
    unique_dates = [d for d in test_truth_dates if d not in train_date_set]

    return {
        split.policy: {
            "val_truth_rows": len(test_truth_idx),
            "val_unique_truth_dates": int(len(test_truth_dates)),
            "dates_with_train_overlap": int(len(overlap_dates)),
            "dates_unique_to_val": int(len(unique_dates)),
            "ratio_overlap": float(len(overlap_dates) / max(len(test_truth_dates), 1)),
        }
    }


def compute_neighbor_context_leakage(
    df: pd.DataFrame, truth_doc_ids: set[str], window_days: int = 7
) -> dict:
    """User-year holdout test truth rows with train rows within ±N days.

    sequence_builder 의 윈도우 길이 (seq_len=16) 는 user 별 순서 기준이지만,
    실제 시간 인접성은 posting_date 기준 ±N일로 측정한다. 16 스텝 윈도우는
    user 별 작업 간격에 따라 며칠~몇 주를 커버하므로 ±7일 컨텍스트를 보수적
    추정으로 사용한다.
    """
    is_truth = df["document_id"].astype(str).isin(truth_doc_ids).to_numpy()
    posting_dates = df["posting_date"].to_numpy()

    split = split_user_year_holdout(df)
    truth_row_idx = np.where(is_truth)[0]
    train_idx = split.train_idx
    test_idx = split.test_idx
    one_day = np.timedelta64(1, "D")

    train_date_set = set(pd.Series(posting_dates[train_idx]).unique())
    test_set = set(test_idx.tolist())
    test_truth_idx = [i for i in truth_row_idx if i in test_set]

    if not test_truth_idx:
        return {
            split.policy: {
                "val_truth_rows": 0,
                "rows_with_neighbor_in_train": 0,
                "ratio_neighbor_seen": None,
            }
        }

    seen = 0
    for ti in test_truth_idx:
        ts = posting_dates[ti]
        found = False
        for d in range(-window_days, window_days + 1):
            cand = ts + d * one_day
            if cand in train_date_set:
                found = True
                break
        if found:
            seen += 1

    return {
        split.policy: {
            "val_truth_rows": len(test_truth_idx),
            "rows_with_neighbor_in_train": int(seen),
            "ratio_neighbor_seen": float(seen / max(len(test_truth_idx), 1)),
        }
    }


def main() -> None:
    print("[Stage 7] loading journal data...")
    df = load_journal_minimal()
    print(f"  loaded {len(df):,} rows")

    truth_doc_ids = load_truth_doc_ids()
    print(f"  loaded {len(truth_doc_ids)} truth doc ids")

    print("[Stage 7] assigning user positions...")
    df = assign_user_positions(df)

    print("[Stage 7] truth line line-level counts...")
    is_truth = df["document_id"].astype(str).isin(truth_doc_ids).to_numpy()
    n_truth_lines = int(is_truth.sum())
    truth_user_count = int(df.loc[is_truth, "created_by"].nunique())
    print(f"  truth lines: {n_truth_lines}, truth users: {truth_user_count}")

    print("[Stage 7] window position histogram...")
    target_step_hist, all_pos_hist = compute_window_position_histogram(df, truth_doc_ids)
    print(f"  target step (pos=15): {target_step_hist}")
    print(f"  all positions: {all_pos_hist}")

    print("[Stage 7] GroupKFold split distribution...")
    gkf_dist = compute_group_kfold_split(df, truth_doc_ids)

    print("[Stage 7] temporal context leakage (date exact, user-year holdout)...")
    temporal = compute_temporal_context_leakage(df, truth_doc_ids)

    print("[Stage 7] neighbor context leakage (±7 days, user-year holdout)...")
    neighbor = compute_neighbor_context_leakage(df, truth_doc_ids, window_days=7)

    # 평균 통계 계산
    target_total = sum(target_step_hist.values())
    all_total = sum(all_pos_hist.values())
    overlap_users_total = sum(v["user_overlap_count"] for v in gkf_dist.values())

    # 같은 user 가 train/val 에 동시 노출되는 비율 (GroupKFold 면 0 이어야 함)
    same_user_cross_fold_ratio = float(overlap_users_total) / max(
        sum(v["n_train_users"] + v["n_val_users"] for v in gkf_dist.values()), 1
    )

    avg_temporal_overlap = float(
        np.mean([v["ratio_overlap"] for v in temporal.values() if v["ratio_overlap"] is not None])
    )
    avg_neighbor_seen = float(
        np.mean(
            [
                v["ratio_neighbor_seen"]
                for v in neighbor.values()
                if v["ratio_neighbor_seen"] is not None
            ]
        )
    )

    summary = {
        "metadata": {
            "seq_len": SEQ_LEN,
            "stride": STRIDE,
            "n_splits": N_SPLITS,
            "dataset": "datasynth_manipulation_v3",
            "n_journal_rows": int(len(df)),
            "n_truth_docs": len(truth_doc_ids),
            "n_truth_lines": n_truth_lines,
            "n_truth_users": truth_user_count,
        },
        "window_position_histogram": {
            "target_step_only_pos15": target_step_hist,
            "all_positions_0_to_15": all_pos_hist,
            "target_total": target_total,
            "all_total": all_total,
            "ratio_target_to_context_appearance": float(target_total) / max(all_total, 1),
        },
        "group_kfold_split": gkf_dist,
        "same_user_cross_fold_ratio_aggregate": same_user_cross_fold_ratio,
        "temporal_context_overlap_per_fold": temporal,
        "temporal_context_overlap_avg": avg_temporal_overlap,
        "neighbor_window_pm7d_per_fold": neighbor,
        "neighbor_window_pm7d_avg": avg_neighbor_seen,
        "verdicts": {
            "same_user_window_both_folds_ge_5pct": same_user_cross_fold_ratio >= 0.05,
            "temporal_date_overlap_avg_ge_5pct": avg_temporal_overlap >= 0.05,
            "neighbor_pm7d_avg_ge_20pct": avg_neighbor_seen >= 0.2,
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"[Stage 7] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
