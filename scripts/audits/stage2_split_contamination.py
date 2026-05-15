"""Stage 2 — Document / User / Temporal split contamination 정량화.

v3 manipulation dataset 에서 3가지 split 전략의 누수 정도와 모델 AUC 차이를 측정한다.

판정 기준:
- Random AUC - GroupKFold AUC > 0.05 → user-level 누수 확정
- GroupKFold AUC - Time AUC > 0.03 → temporal 누수 확정
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, KFold
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
V3_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"
ARTIFACTS = ROOT / "artifacts"
OUT_JSON = ARTIFACTS / "S2_split_contamination.json"
OUT_MD = ARTIFACTS / "S2_split_recommendation.md"

RANDOM_STATE = 42


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """journal_entries (row-level) + manipulated_entry_truth (doc-level) 로드."""
    je = pd.read_csv(
        V3_DIR / "journal_entries.csv",
        usecols=[
            "document_id",
            "company_code",
            "fiscal_year",
            "fiscal_period",
            "posting_date",
            "document_type",
            "currency",
            "created_by",
            "user_persona",
            "source",
            "business_process",
            "sod_violation",
            "has_attachment",
            "debit_amount",
            "credit_amount",
            "local_amount",
            "gl_account",
            "line_number",
            "approval_date",
            "approved_by",
        ],
        low_memory=False,
        parse_dates=["posting_date", "approval_date"],
    )
    truth = pd.read_csv(V3_DIR / "labels" / "manipulated_entry_truth.csv")
    return je, truth


def build_doc_matrix(je: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """document_id 단위 feature matrix + label + 메타 (user, date, scenario)."""
    je = je.copy()
    je["debit_amount"] = pd.to_numeric(je["debit_amount"], errors="coerce").fillna(0.0)
    je["credit_amount"] = pd.to_numeric(je["credit_amount"], errors="coerce").fillna(0.0)
    je["local_amount"] = pd.to_numeric(je["local_amount"], errors="coerce").fillna(0.0)
    je["sod_violation"] = je["sod_violation"].astype(str).str.lower().eq("true").astype(int)
    je["has_attachment"] = je["has_attachment"].astype(str).str.lower().eq("true").astype(int)

    je["posting_hour"] = je["posting_date"].dt.hour
    je["posting_weekday"] = je["posting_date"].dt.weekday
    je["is_weekend"] = (je["posting_weekday"] >= 5).astype(int)
    je["is_after_hours"] = ((je["posting_hour"] < 8) | (je["posting_hour"] >= 19)).astype(int)
    je["approval_lag_days"] = (je["approval_date"] - je["posting_date"]).dt.days

    grp = je.groupby("document_id", sort=False)
    feats = pd.DataFrame(
        {
            "line_count": grp.size(),
            "debit_sum": grp["debit_amount"].sum(),
            "credit_sum": grp["credit_amount"].sum(),
            "abs_amount_max": grp["local_amount"].apply(lambda s: s.abs().max()),
            "abs_amount_mean": grp["local_amount"].apply(lambda s: s.abs().mean()),
            "gl_account_nunique": grp["gl_account"].nunique(),
            "sod_violation_max": grp["sod_violation"].max(),
            "has_attachment_min": grp["has_attachment"].min(),
            "posting_hour": grp["posting_hour"].first(),
            "posting_weekday": grp["posting_weekday"].first(),
            "is_weekend": grp["is_weekend"].max(),
            "is_after_hours": grp["is_after_hours"].max(),
            "approval_lag_days": grp["approval_lag_days"].mean(),
            "fiscal_period": grp["fiscal_period"].first(),
        }
    )

    meta = grp.agg(
        created_by=("created_by", "first"),
        posting_date=("posting_date", "first"),
        fiscal_year=("fiscal_year", "first"),
        document_type=("document_type", "first"),
        business_process=("business_process", "first"),
    )
    meta["row_count"] = grp.size()

    doc_df = feats.join(meta).reset_index()

    truth_set = set(truth["document_id"].astype(str).tolist())
    doc_df["y"] = doc_df["document_id"].astype(str).isin(truth_set).astype(int)

    scenario_map = dict(zip(truth["document_id"].astype(str), truth["manipulation_scenario"]))
    doc_df["scenario"] = doc_df["document_id"].astype(str).map(scenario_map)

    doc_df["approval_lag_days"] = doc_df["approval_lag_days"].fillna(-1.0)
    return doc_df


# --------------------------------------------------------------------------- #
# Strategy (1) Random row-level 5-fold split
# --------------------------------------------------------------------------- #
def strategy_random_rowlevel(je: pd.DataFrame, truth_ids: set[str]) -> dict:
    """row-level 5-fold 무작위 split — 같은 document_id 가 fold 간 흩어지는지 측정."""
    je = je[["document_id"]].reset_index(drop=True).copy()
    rng = np.random.default_rng(RANDOM_STATE)
    je["_fold"] = rng.integers(0, 5, size=len(je))

    docs_per_fold = je.groupby("document_id")["_fold"].nunique()
    docs_spanning = (docs_per_fold > 1).sum()
    total_docs = docs_per_fold.size

    truth_docs_spanning = (docs_per_fold[docs_per_fold.index.astype(str).isin(truth_ids)] > 1).sum()
    total_truth_docs = docs_per_fold.index.astype(str).isin(truth_ids).sum()

    return {
        "docs_spanning_folds_pct": float(docs_spanning / total_docs * 100),
        "docs_spanning_folds_count": int(docs_spanning),
        "total_documents": int(total_docs),
        "truth_docs_spanning_folds_count": int(truth_docs_spanning),
        "total_truth_documents": int(total_truth_docs),
        "interpretation": (
            "row-level 무작위 split 은 단일 document 의 row 가 train/val 양쪽에 "
            "흩어진다 — 동일 전표 메모리제이션으로 model 이 부풀려진 점수를 받는다."
        ),
    }


# --------------------------------------------------------------------------- #
# Strategy (2) GroupKFold(document_id)
# --------------------------------------------------------------------------- #
def strategy_groupkfold(doc_df: pd.DataFrame) -> dict:
    """GroupKFold(groups=document_id) — user 중첩률 + 날짜 overlap 측정."""
    groups = doc_df["document_id"].astype(str).to_numpy()
    gkf = GroupKFold(n_splits=5)

    user_overlap_ratios: list[float] = []
    date_overlap_days: list[float] = []
    date_overlap_ratios: list[float] = []

    for train_idx, val_idx in gkf.split(doc_df, groups=groups):
        train = doc_df.iloc[train_idx]
        val = doc_df.iloc[val_idx]

        train_users = set(train["created_by"].dropna().tolist())
        val_users = set(val["created_by"].dropna().tolist())
        overlap_users = train_users & val_users
        ratio = len(overlap_users) / max(len(val_users), 1)
        user_overlap_ratios.append(ratio)

        t_min, t_max = train["posting_date"].min(), train["posting_date"].max()
        v_min, v_max = val["posting_date"].min(), val["posting_date"].max()
        ov_lo, ov_hi = max(t_min, v_min), min(t_max, v_max)
        overlap = max((ov_hi - ov_lo).days, 0)
        v_span = max((v_max - v_min).days, 1)
        date_overlap_days.append(float(overlap))
        date_overlap_ratios.append(float(overlap / v_span))

    return {
        "user_overlap_ratio_mean": float(np.mean(user_overlap_ratios)),
        "user_overlap_ratio_per_fold": [float(x) for x in user_overlap_ratios],
        "date_overlap_days_mean": float(np.mean(date_overlap_days)),
        "date_overlap_ratio_mean": float(np.mean(date_overlap_ratios)),
        "interpretation": (
            "GroupKFold(document_id) 는 동일 전표 중복은 차단하나, 동일 created_by "
            "와 동일 posting_date 구간은 train/val 양쪽에 존재한다."
        ),
    }


# --------------------------------------------------------------------------- #
# Strategy (3) Time-based split
# --------------------------------------------------------------------------- #
def strategy_time_split(doc_df: pd.DataFrame) -> dict:
    """2022-2023 train / 2024 val — user 등장률 + scenario 분포 chi-square."""
    train = doc_df[doc_df["fiscal_year"].isin([2022, 2023])]
    val = doc_df[doc_df["fiscal_year"] == 2024]

    train_users = set(train["created_by"].dropna().tolist())
    val_users = set(val["created_by"].dropna().tolist())
    overlap_users = train_users & val_users
    user_overlap_ratio = len(overlap_users) / max(len(val_users), 1)

    train_scen = train[train["y"] == 1]["scenario"].value_counts().sort_index()
    val_scen = val[val["y"] == 1]["scenario"].value_counts().sort_index()
    all_scen = sorted(set(train_scen.index) | set(val_scen.index))
    contingency = np.array(
        [
            [int(train_scen.get(s, 0)) for s in all_scen],
            [int(val_scen.get(s, 0)) for s in all_scen],
        ]
    )
    # 적어도 한 셀이라도 0 이상이어야 chi-square 수행 가능
    if contingency.sum() == 0 or (contingency.sum(axis=1) == 0).any():
        chi2_p = None
        chi2_stat = None
    else:
        chi2_stat, chi2_p, _, _ = chi2_contingency(contingency)
        chi2_stat = float(chi2_stat)
        chi2_p = float(chi2_p)

    return {
        "user_overlap_ratio": float(user_overlap_ratio),
        "train_users_total": len(train_users),
        "val_users_total": len(val_users),
        "overlap_users_count": len(overlap_users),
        "scenario_chi2_stat": chi2_stat,
        "scenario_chi2_p_value": chi2_p,
        "scenario_distribution_train": {s: int(train_scen.get(s, 0)) for s in all_scen},
        "scenario_distribution_val": {s: int(val_scen.get(s, 0)) for s in all_scen},
        "train_documents": int(len(train)),
        "val_documents": int(len(val)),
        "train_truth_documents": int((train["y"] == 1).sum()),
        "val_truth_documents": int((val["y"] == 1).sum()),
        "interpretation": (
            "2024 val 의 created_by 가 2022-2023 train 에도 등장한다면, "
            "user-level 시계열 누수가 잔존한다. scenario chi-square p<0.05 면 "
            "양 split 의 분포가 통계적으로 다르다."
        ),
    }


# --------------------------------------------------------------------------- #
# Baseline AUC
# --------------------------------------------------------------------------- #
FEATURE_COLS = [
    "line_count",
    "debit_sum",
    "credit_sum",
    "abs_amount_max",
    "abs_amount_mean",
    "gl_account_nunique",
    "sod_violation_max",
    "has_attachment_min",
    "posting_hour",
    "posting_weekday",
    "is_weekend",
    "is_after_hours",
    "approval_lag_days",
    "fiscal_period",
    "row_count",
]


def _train_eval(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
) -> tuple[float, float]:
    """LR 와 XGBoost 의 val AUC 반환."""
    X_train = train_df[FEATURE_COLS].to_numpy(dtype=np.float64)
    y_train = train_df["y"].to_numpy(dtype=np.int32)
    X_val = val_df[FEATURE_COLS].to_numpy(dtype=np.float64)
    y_val = val_df["y"].to_numpy(dtype=np.int32)

    if y_train.sum() == 0 or y_val.sum() == 0 or y_train.sum() == len(y_train):
        return float("nan"), float("nan")

    scaler = StandardScaler()
    Xt_s = scaler.fit_transform(X_train)
    Xv_s = scaler.transform(X_val)
    lr = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE)
    lr.fit(Xt_s, y_train)
    lr_auc = roc_auc_score(y_val, lr.predict_proba(Xv_s)[:, 1])

    pos = max(y_train.sum(), 1)
    neg = max(len(y_train) - y_train.sum(), 1)
    xgb = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        scale_pos_weight=float(neg / pos),
        n_jobs=2,
        tree_method="hist",
        random_state=RANDOM_STATE,
        eval_metric="auc",
    )
    xgb.fit(X_train, y_train, verbose=False)
    xgb_auc = roc_auc_score(y_val, xgb.predict_proba(X_val)[:, 1])
    return float(lr_auc), float(xgb_auc)


def auc_random_doclevel(doc_df: pd.DataFrame) -> dict:
    """document-level random KFold AUC (row-level random 의 대표값)."""
    kf = KFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    lr_aucs, xgb_aucs = [], []
    for tr, va in kf.split(doc_df):
        lr_auc, xgb_auc = _train_eval(doc_df.iloc[tr], doc_df.iloc[va])
        lr_aucs.append(lr_auc)
        xgb_aucs.append(xgb_auc)
    return {
        "lr_auc_mean": float(np.nanmean(lr_aucs)),
        "xgb_auc_mean": float(np.nanmean(xgb_aucs)),
        "lr_auc_per_fold": lr_aucs,
        "xgb_auc_per_fold": xgb_aucs,
    }


def auc_groupkfold(doc_df: pd.DataFrame) -> dict:
    groups = doc_df["document_id"].astype(str).to_numpy()
    gkf = GroupKFold(n_splits=5)
    lr_aucs, xgb_aucs = [], []
    for tr, va in gkf.split(doc_df, groups=groups):
        lr_auc, xgb_auc = _train_eval(doc_df.iloc[tr], doc_df.iloc[va])
        lr_aucs.append(lr_auc)
        xgb_aucs.append(xgb_auc)
    return {
        "lr_auc_mean": float(np.nanmean(lr_aucs)),
        "xgb_auc_mean": float(np.nanmean(xgb_aucs)),
        "lr_auc_per_fold": lr_aucs,
        "xgb_auc_per_fold": xgb_aucs,
    }


def auc_time_split(doc_df: pd.DataFrame) -> dict:
    train = doc_df[doc_df["fiscal_year"].isin([2022, 2023])]
    val = doc_df[doc_df["fiscal_year"] == 2024]
    lr_auc, xgb_auc = _train_eval(train, val)
    return {"lr_auc": lr_auc, "xgb_auc": xgb_auc}


# --------------------------------------------------------------------------- #
# 판정 & 권고
# --------------------------------------------------------------------------- #
def make_verdict(auc_random: dict, auc_group: dict, auc_time: dict) -> dict:
    rand_auc = (auc_random["lr_auc_mean"] + auc_random["xgb_auc_mean"]) / 2
    group_auc = (auc_group["lr_auc_mean"] + auc_group["xgb_auc_mean"]) / 2
    time_auc = (auc_time["lr_auc"] + auc_time["xgb_auc"]) / 2

    diff_user = rand_auc - group_auc
    diff_time = group_auc - time_auc

    user_leakage = bool(diff_user > 0.05)
    temporal_leakage = bool(diff_time > 0.03)

    if user_leakage and temporal_leakage:
        recommendation = "TIME_THEN_GROUP_COMPOSITE"
        rationale = (
            "user-level + temporal 누수 동시 확정. Time holdout 후 train 내부 "
            "GroupKFold(created_by 또는 document_id) 복합 split 필수."
        )
    elif user_leakage:
        recommendation = "GROUP_KFOLD_USER"
        rationale = "user-level 누수만 확정. GroupKFold(groups=created_by) 사용."
    elif temporal_leakage:
        recommendation = "TIME_BASED_HOLDOUT"
        rationale = "temporal 누수만 확정. 연도 기반 holdout 사용."
    else:
        recommendation = "GROUP_KFOLD_DOCUMENT"
        rationale = (
            "추가 누수 없음. 기존 GroupKFold(document_id) 유지 가능 — "
            "다만 created_by 중첩률 절대치는 모니터링 필요."
        )

    return {
        "auc_random_mean": rand_auc,
        "auc_groupkfold_mean": group_auc,
        "auc_time_split_mean": time_auc,
        "diff_random_minus_group": diff_user,
        "diff_group_minus_time": diff_time,
        "user_level_leakage_confirmed": user_leakage,
        "temporal_leakage_confirmed": temporal_leakage,
        "recommendation": recommendation,
        "rationale": rationale,
    }


def main() -> None:
    print("[Stage2] loading journal_entries + truth ...")
    je, truth = load_data()
    print(f"  journal_entries rows = {len(je):,}")
    print(f"  truth docs           = {len(truth):,}")

    print("[Stage2] building doc-level matrix ...")
    doc_df = build_doc_matrix(je, truth)
    print(f"  total documents = {len(doc_df):,}")
    print(f"  positive (truth) = {(doc_df['y'] == 1).sum():,}")

    print("[Stage2] strategy (1) random row-level ...")
    truth_ids = set(truth["document_id"].astype(str).tolist())
    s1 = strategy_random_rowlevel(je, truth_ids)

    print("[Stage2] strategy (2) GroupKFold ...")
    s2 = strategy_groupkfold(doc_df)

    print("[Stage2] strategy (3) time-based ...")
    s3 = strategy_time_split(doc_df)

    print("[Stage2] baseline AUC - random doc KFold ...")
    auc_rand = auc_random_doclevel(doc_df)
    print(f"  random LR/XGB = {auc_rand['lr_auc_mean']:.4f} / {auc_rand['xgb_auc_mean']:.4f}")

    print("[Stage2] baseline AUC - GroupKFold(document_id) ...")
    auc_grp = auc_groupkfold(doc_df)
    print(f"  group  LR/XGB = {auc_grp['lr_auc_mean']:.4f} / {auc_grp['xgb_auc_mean']:.4f}")

    print("[Stage2] baseline AUC - time split (22-23 / 24) ...")
    auc_time = auc_time_split(doc_df)
    print(f"  time   LR/XGB = {auc_time['lr_auc']:.4f} / {auc_time['xgb_auc']:.4f}")

    verdict = make_verdict(auc_rand, auc_grp, auc_time)

    payload = {
        "dataset": "datasynth_manipulation_v3",
        "total_documents": int(len(doc_df)),
        "total_truth_documents": int((doc_df["y"] == 1).sum()),
        "feature_columns": FEATURE_COLS,
        "strategies": {
            "random_rowlevel_5fold": {
                "contamination": s1,
                "auc_proxy_doclevel_random": auc_rand,
            },
            "groupkfold_document_id": {
                "contamination": s2,
                "auc": auc_grp,
            },
            "time_split_2022_2023_vs_2024": {
                "contamination": s3,
                "auc": auc_time,
            },
        },
        "verdict": verdict,
        "thresholds": {
            "random_minus_groupkfold_user_leakage": 0.05,
            "groupkfold_minus_time_temporal_leakage": 0.03,
        },
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Stage2] wrote {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
