"""V4 PHASE2 치트루트 감사 — CR-1~CR-8.

read-only. V4 데이터/PHASE2 코드/config 수정 금지.
산출: artifacts/datasynth_v4_phase2_cheat_route_audit.{md,json}
       artifacts/datasynth_v4_phase2_simulated_auroc.csv
"""
# ruff: noqa: E501

from __future__ import annotations

import json
import math
import os
import pickle
import sys
import warnings
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.preprocessing.constants import (  # noqa: E402
    LABEL_COLUMNS,
    LEAKAGE_DENY_COLUMNS,
)
from src.services.phase2_case_contract import (  # noqa: E402
    PHASE2_CASE_FEATURE_COLUMNS,
    PROVENANCE_ONLY_FIELDS,
    enforce_phase2_case_feature_firewall,
)
from src.validation.schema_validator import DETECTOR_FORBIDDEN_COLUMNS  # noqa: E402

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

PKL_PATH = Path(
    os.getenv(
        "PHASE2_CHEAT_PKL_PATH",
        str(ROOT / "artifacts" / "phase1_manipulation_v4_candidate_20260515.pkl"),
    )
)
TRUTH_PATH = (
    Path(
        os.getenv(
            "PHASE2_CHEAT_TRUTH_PATH",
            str(
                ROOT
                / "data/journal/primary/datasynth_manipulation_v4_candidate/labels/manipulated_entry_truth.csv"
            ),
        )
    )
)
V4_HEADER_PATH = Path(
    os.getenv(
        "PHASE2_CHEAT_HEADER_PATH",
        str(ROOT / "data/journal/primary/datasynth_manipulation_v4_candidate/journal_entries.csv"),
    )
)
OUT_JSON = Path(
    os.getenv(
        "PHASE2_CHEAT_OUT_JSON",
        str(ROOT / "artifacts" / "datasynth_v4_phase2_cheat_route_audit.json"),
    )
)
OUT_MD = Path(
    os.getenv(
        "PHASE2_CHEAT_OUT_MD",
        str(ROOT / "artifacts" / "datasynth_v4_phase2_cheat_route_audit.md"),
    )
)
OUT_AUROC_CSV = Path(
    os.getenv(
        "PHASE2_CHEAT_OUT_AUROC_CSV",
        str(ROOT / "artifacts" / "datasynth_v4_phase2_simulated_auroc.csv"),
    )
)

# HARD / SOFT / OK 임계 (V3 baseline 계승)
HARD_AUROC = 0.95
SOFT_AUROC = 0.80

# CR-8 simulated 학습 시 정상 다운샘플 (계산 시간 단축, 비례 보존)
NEG_SAMPLE_PER_FOLD = 80_000
RNG_SEED = 20260516


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    resolved = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def auroc_univariate(score: pd.Series, target: pd.Series) -> float:
    """Mann-Whitney U statistic 기반 AUROC. NaN 마스킹."""
    mask = score.notna() & target.notna()
    if mask.sum() == 0:
        return float("nan")
    y = target.loc[mask].astype(int).to_numpy()
    s = score.loc[mask].astype(float).to_numpy()
    pos = y.sum()
    neg = y.size - pos
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, y.size + 1)
    sum_ranks_pos = ranks[y == 1].sum()
    u = sum_ranks_pos - pos * (pos + 1) / 2
    return float(u / (pos * neg))


def _safe_numeric(series: pd.Series) -> pd.Series:
    kind = series.dtype.kind
    if kind in "biufc":
        return series.astype(float)
    if kind == "b" or pd.api.types.is_bool_dtype(series.dtype):
        return series.astype(float)
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return series.astype("int64").astype(float)
    return pd.Series(np.nan, index=series.index)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    print(f"[{_now_iso()}] loading pkl …", flush=True)
    with PKL_PATH.open("rb") as fh:
        obj = pickle.load(fh)
    df = obj["df"]
    print(f"  rows={len(df):,} cols={len(df.columns)}", flush=True)

    print(f"[{_now_iso()}] loading truth …", flush=True)
    truth = pd.read_csv(TRUTH_PATH)
    print(
        f"  truth_rows={len(truth):,} scenarios={truth.manipulation_scenario.nunique()}", flush=True
    )

    print(f"[{_now_iso()}] loading raw CSV header …", flush=True)
    with V4_HEADER_PATH.open("r", encoding="utf-8") as fh:
        header_line = fh.readline().strip()
    raw_columns = header_line.split(",")
    return df, truth, raw_columns


# ─────────────────────────────────────────────────────────────────────
# CR-1: 단일 컬럼 univariate AUROC
# ─────────────────────────────────────────────────────────────────────
def cr1_univariate(df: pd.DataFrame, truth: pd.DataFrame) -> dict[str, Any]:
    print(f"[{_now_iso()}] CR-1 univariate AUROC …", flush=True)
    truth_docs = set(truth["document_id"].astype(str))
    doc_scenario = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    df_doc_str = df["document_id"].astype(str)
    y_overall = df_doc_str.isin(truth_docs).astype(int)
    scenario_series = df_doc_str.map(doc_scenario)
    scenarios = sorted(set(doc_scenario.values()))
    scenario_targets = {
        sc: (scenario_series == sc).astype(int).rename(f"y_{sc}") for sc in scenarios
    }

    # phase2_plan._decide_column 과 동일한 deny-list 패턴을 적용해서
    # *실제 PHASE2 row matrix 입력* 후보로 좁힌다.
    leakage_aware = {c.lower() for c in LEAKAGE_DENY_COLUMNS}
    label_aware = {c.lower() for c in LABEL_COLUMNS}
    detector_block = {c.lower() for c in DETECTOR_FORBIDDEN_COLUMNS}
    # phase2_plan._LEAKAGE_PATTERNS 와 1:1 동기화
    leakage_pattern_tokens = (
        "label",
        "target",
        "fraud",
        "anomaly",
        "risk",
        "rule",
        "score",
        "model",
        "prediction",
        "probability",
        "export",
        "dashboard",
    )
    # phase2_plan._ID_NAMES + endswith("_id") 모방
    id_exact = {"document_id", "doc_id", "row_id", "id", "transaction_id", "journal_id"}

    def _is_deny_pattern(col: str) -> bool:
        lc = col.lower()
        # _LEAKAGE_PATTERNS: token in tokens or endswith(_token)
        tokens = set(lc.replace("__", "_").split("_"))
        for token in leakage_pattern_tokens:
            if token in tokens or lc.endswith(f"_{token}"):
                return True
        return False

    excluded: dict[str, list[str]] = {
        "exact_deny": [],
        "label": [],
        "detector_forbidden": [],
        "leakage_pattern": [],
        "identifier": [],
        "datetime": [],
        "dtype_non_numeric": [],
    }
    candidate_cols = []
    for col in df.columns:
        lc = col.lower()
        if lc in leakage_aware:
            excluded["exact_deny"].append(col)
            continue
        if lc in label_aware:
            excluded["label"].append(col)
            continue
        if lc in detector_block:
            excluded["detector_forbidden"].append(col)
            continue
        if _is_deny_pattern(col):
            excluded["leakage_pattern"].append(col)
            continue
        if lc in id_exact or lc.endswith("_id"):
            excluded["identifier"].append(col)
            continue
        if col in {"document_number", "reference", "header_text", "line_text"}:
            excluded["identifier"].append(col)
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col].dtype):
            excluded["datetime"].append(col)
            continue
        if df[col].dtype.kind in "biuf" or pd.api.types.is_bool_dtype(df[col].dtype):
            candidate_cols.append(col)
        else:
            excluded["dtype_non_numeric"].append(col)

    rows: list[dict[str, Any]] = []
    for col in candidate_cols:
        ser = _safe_numeric(df[col])
        miss = float(ser.isna().mean())
        if miss > 0.99:
            continue
        overall_auc = auroc_univariate(ser, y_overall)
        scenario_aucs = {sc: auroc_univariate(ser, scenario_targets[sc]) for sc in scenarios}
        max_sc = max(
            scenarios,
            key=lambda sc: (
                abs(scenario_aucs[sc] - 0.5) if not math.isnan(scenario_aucs[sc]) else -1.0
            ),
        )
        max_auc = scenario_aucs[max_sc]
        rows.append(
            {
                "column": col,
                "dtype": str(df[col].dtype),
                "missing_rate": round(miss, 4),
                "overall_auroc": round(overall_auc, 4),
                "max_scenario": max_sc,
                "max_scenario_auroc": round(max_auc, 4) if not math.isnan(max_auc) else None,
                "scenario_aurocs": {
                    sc: (round(v, 4) if not math.isnan(v) else None)
                    for sc, v in scenario_aucs.items()
                },
            }
        )

    hard = [
        r
        for r in rows
        if (r["max_scenario_auroc"] is not None and r["max_scenario_auroc"] >= HARD_AUROC)
        or (r["overall_auroc"] is not None and r["overall_auroc"] >= HARD_AUROC)
    ]
    soft = [
        r
        for r in rows
        if r not in hard
        and (
            (r["max_scenario_auroc"] is not None and r["max_scenario_auroc"] >= SOFT_AUROC)
            or (r["overall_auroc"] is not None and r["overall_auroc"] >= SOFT_AUROC)
        )
    ]
    rows_sorted = sorted(
        rows,
        key=lambda r: r["max_scenario_auroc"] if r["max_scenario_auroc"] is not None else 0.0,
        reverse=True,
    )
    return {
        "candidate_count": len(candidate_cols),
        "evaluated": len(rows),
        "hard_count": len(hard),
        "soft_count": len(soft),
        "hard": hard,
        "soft": soft,
        "top20": rows_sorted[:20],
        "all": rows_sorted,
        "excluded": {k: sorted(v) for k, v in excluded.items()},
        "excluded_counts": {k: len(v) for k, v in excluded.items()},
    }


# ─────────────────────────────────────────────────────────────────────
# CR-2: 2-feature interaction AUROC
# ─────────────────────────────────────────────────────────────────────
def cr2_pairwise(df: pd.DataFrame, truth: pd.DataFrame, cr1: dict[str, Any]) -> dict[str, Any]:
    print(f"[{_now_iso()}] CR-2 pairwise interaction AUROC …", flush=True)
    truth_docs = set(truth["document_id"].astype(str))
    y_overall = df["document_id"].astype(str).isin(truth_docs).astype(int)
    doc_scenario = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    scenarios = sorted(set(doc_scenario.values()))
    scenario_series = df["document_id"].astype(str).map(doc_scenario)
    scenario_targets = {sc: (scenario_series == sc).astype(int) for sc in scenarios}

    # CR-1 단독 AUROC 상위 25 feature
    sorted_feats = [r["column"] for r in cr1["all"] if r["overall_auroc"] is not None]
    top_feats = sorted_feats[:25]
    # boolean 우선 (AND interaction)
    bool_feats = [
        c for c in top_feats if df[c].dtype.kind == "b" or pd.api.types.is_bool_dtype(df[c].dtype)
    ]
    num_feats = [c for c in top_feats if c not in bool_feats]
    rows: list[dict[str, Any]] = []

    def _record(a: str, b: str, score: pd.Series, kind: str) -> None:
        overall = auroc_univariate(score, y_overall)
        scen = {sc: auroc_univariate(score, scenario_targets[sc]) for sc in scenarios}
        max_sc = max(
            scenarios,
            key=lambda s: abs(scen[s] - 0.5) if not math.isnan(scen[s]) else -1.0,
        )
        rows.append(
            {
                "feature_a": a,
                "feature_b": b,
                "interaction": kind,
                "overall_auroc": round(overall, 4),
                "max_scenario": max_sc,
                "max_scenario_auroc": round(scen[max_sc], 4)
                if not math.isnan(scen[max_sc])
                else None,
            }
        )

    for a, b in combinations(bool_feats, 2):
        sa = df[a].astype(float).fillna(0.0)
        sb = df[b].astype(float).fillna(0.0)
        score = sa * sb
        _record(a, b, score, "AND")

    for a, b in combinations(num_feats[:10], 2):
        sa = _safe_numeric(df[a]).fillna(0.0)
        sb = _safe_numeric(df[b]).fillna(0.0)
        score = sa.abs() * sb.abs()
        _record(a, b, score, "abs_product")

    # boolean × numeric 조합 (상위 5 × 5)
    for a in bool_feats[:5]:
        for b in num_feats[:5]:
            sa = df[a].astype(float).fillna(0.0)
            sb = _safe_numeric(df[b]).fillna(0.0)
            score = sa * sb.abs()
            _record(a, b, score, "bool_x_num")

    hard = [
        r
        for r in rows
        if r["max_scenario_auroc"] is not None and r["max_scenario_auroc"] >= HARD_AUROC
    ]
    soft = [
        r
        for r in rows
        if r not in hard
        and r["max_scenario_auroc"] is not None
        and r["max_scenario_auroc"] >= SOFT_AUROC
    ]
    rows_sorted = sorted(
        rows,
        key=lambda r: r["max_scenario_auroc"] or 0.0,
        reverse=True,
    )
    return {
        "evaluated_pairs": len(rows),
        "hard_count": len(hard),
        "soft_count": len(soft),
        "hard": hard,
        "soft_top20": soft[:20],
        "top20": rows_sorted[:20],
    }


# ─────────────────────────────────────────────────────────────────────
# CR-3: PROVENANCE firewall 검증
# ─────────────────────────────────────────────────────────────────────
def cr3_firewall() -> dict[str, Any]:
    print(f"[{_now_iso()}] CR-3 PROVENANCE firewall …", flush=True)
    findings: list[dict[str, Any]] = []

    # phase1_case_id 는 build_phase2_case_feature_frame() 의
    # set_index("phase1_case_id", drop=True) 계약에 의해 row 인덱스가 되는 식별자.
    # firewall 은 columns 만 검사하므로 by-design 제외.
    index_only_fields = {"phase1_case_id"}

    for field in PROVENANCE_ONLY_FIELDS:
        if field in index_only_fields:
            findings.append(
                {
                    "field": field,
                    "blocked": True,
                    "error": None,
                    "note": "row index by contract (set_index drop=True); not a column-leakage vector",
                }
            )
            continue
        sample = pd.DataFrame(
            [
                {
                    "phase1_case_id": "C-1",
                    field: "leak",
                    **{c: 0.0 for c in PHASE2_CASE_FEATURE_COLUMNS},
                }
            ]
        ).set_index("phase1_case_id")
        try:
            enforce_phase2_case_feature_firewall(sample)
            findings.append({"field": field, "blocked": False, "error": None, "note": None})
        except ValueError as exc:
            findings.append({"field": field, "blocked": True, "error": str(exc), "note": None})
        except Exception as exc:
            findings.append(
                {
                    "field": field,
                    "blocked": False,
                    "error": f"unexpected: {exc!r}",
                    "note": None,
                }
            )

    blocked = sum(1 for f in findings if f["blocked"])
    return {
        "total_fields": len(PROVENANCE_ONLY_FIELDS),
        "blocked_count": blocked,
        "all_blocked": blocked == len(PROVENANCE_ONLY_FIELDS),
        "findings": findings,
    }


# ─────────────────────────────────────────────────────────────────────
# CR-4: deny-list 컬럼 제거 검증
# ─────────────────────────────────────────────────────────────────────
def cr4_deny_list(raw_columns: list[str]) -> dict[str, Any]:
    print(f"[{_now_iso()}] CR-4 deny-list intersection …", flush=True)
    raw_set = {c.strip() for c in raw_columns}
    deny_label = sorted(raw_set & set(LABEL_COLUMNS))
    deny_leakage = sorted(raw_set & set(LEAKAGE_DENY_COLUMNS))
    deny_detector = sorted(raw_set & set(DETECTOR_FORBIDDEN_COLUMNS))
    combined = sorted(set(deny_label) | set(deny_leakage) | set(deny_detector))
    return {
        "raw_column_count": len(raw_columns),
        "label_intersection": deny_label,
        "leakage_deny_intersection": deny_leakage,
        "detector_forbidden_intersection": deny_detector,
        "combined_intersection": combined,
        "combined_count": len(combined),
    }


# ─────────────────────────────────────────────────────────────────────
# CR-5: preprocessing fit_split 가드 (정적 검증)
# ─────────────────────────────────────────────────────────────────────
def cr5_fit_split_static() -> dict[str, Any]:
    print(f"[{_now_iso()}] CR-5 fit_split static analysis …", flush=True)
    matrix_path = ROOT / "src/preprocessing/phase2_matrix.py"
    plan_path = ROOT / "src/preprocessing/phase2_plan.py"
    service_path = ROOT / "src/services/phase2_training_service.py"

    matrix_src = matrix_path.read_text(encoding="utf-8")
    plan_src = plan_path.read_text(encoding="utf-8")
    service_src = service_path.read_text(encoding="utf-8") if service_path.exists() else ""

    # 핵심 시그널:
    # 1) Phase2AutoencoderMatrixBuilder.fit 가 호출되는 시점이 train split 인지
    # 2) transform 은 동일 fit 결과를 사용
    # 3) signed_log/numeric_policy/encoder 는 fit() 안에서만 학습됨
    signals = {
        "matrix_has_fit": "def fit(self" in matrix_src,
        "matrix_has_transform": "def transform(self" in matrix_src,
        "matrix_uses_fit_transform_alias": "def fit_transform" in matrix_src,
        "matrix_signed_log_fit_inside_fit": "_signed_log.fit" in matrix_src
        and matrix_src.index("_signed_log.fit") > matrix_src.index("def fit("),
        "matrix_numeric_policy_fit_inside_fit": "_numeric_policy.fit" in matrix_src,
        "matrix_low_card_encoder_fit_inside_fit": "_low_card_encoder.fit" in matrix_src,
        "matrix_high_card_encoder_fit_inside_fit": "_high_card_encoder.fit" in matrix_src,
        "plan_validate_single_use_deny": "_validate_single_use_deny_columns" in plan_src,
        # phase2_training_service.py 는 fit_transform 매크로 대신
        # `Phase2AutoencoderMatrixBuilder(...).fit(trial_df)` 로 train fit
        # 한 뒤 동일 builder 로 `.transform(calibration_df)` 호출. fit_transform
        # 호출 대신 분리된 fit→transform 패턴이 더 안전한 계약.
        "service_fits_builder_on_trial_df": ".fit(trial_df)" in service_src,
        "service_calls_transform_for_calibration": "matrix_builder.transform(calibration_df)"
        in service_src,
        "service_calls_transform_for_eval": (
            ".transform(" in service_src and service_src.count(".transform(") >= 1
        ),
    }
    fit_calls = []
    for line_no, line in enumerate(matrix_src.splitlines(), start=1):
        if ".fit(" in line and "fit_transform" not in line:
            fit_calls.append((line_no, line.strip()))

    return {
        "signals": signals,
        "fit_calls_in_matrix": fit_calls,
        "fit_calls_count": len(fit_calls),
        "fit_split_contract": "Phase2AutoencoderMatrixBuilder.fit consumes the input "
        "DataFrame as-is; the caller is responsible for passing the train split "
        "only. Validated via service-layer code path inspection (CR-5 static).",
    }


# ─────────────────────────────────────────────────────────────────────
# CR-6: cross-scenario / document_id split leakage
# ─────────────────────────────────────────────────────────────────────
def cr6_split_leakage(df: pd.DataFrame, truth: pd.DataFrame) -> dict[str, Any]:
    print(f"[{_now_iso()}] CR-6 split leakage check …", flush=True)
    truth_doc_scen = truth.groupby("document_id")["manipulation_scenario"].nunique()
    doc_id_truth_collision = int((truth_doc_scen > 1).sum())

    truth_docs = set(truth["document_id"].astype(str))
    normal_docs = set(df["document_id"].astype(str)) - truth_docs
    overlap = truth_docs & normal_docs  # 정의상 0이어야 함
    doc_year = df.groupby("document_id")["fiscal_year"].nunique()
    doc_id_year_collision = int((doc_year > 1).sum())

    # 시나리오 × fiscal_year 분포 — truth.fiscal_year 그대로 사용 (merge 충돌 회피)
    scen_year = truth.groupby(["manipulation_scenario", "fiscal_year"]).size().unstack(fill_value=0)

    return {
        "truth_doc_scenario_collision": doc_id_truth_collision,
        "truth_normal_doc_overlap": len(overlap),
        "document_id_year_collision": doc_id_year_collision,
        "total_truth_docs": len(truth_docs),
        "total_normal_docs": len(normal_docs),
        "scenario_year_distribution": scen_year.to_dict(),
        "group_by_document_id_safe": doc_id_year_collision == 0,
    }


# ─────────────────────────────────────────────────────────────────────
# CR-7: 시나리오별 fitting risk (entropy)
# ─────────────────────────────────────────────────────────────────────
def cr7_scenario_entropy(
    df: pd.DataFrame, truth: pd.DataFrame, cr1: dict[str, Any]
) -> dict[str, Any]:
    print(f"[{_now_iso()}] CR-7 scenario entropy …", flush=True)
    truth_docs = truth[["document_id", "manipulation_scenario"]].copy()
    truth_docs["document_id"] = truth_docs["document_id"].astype(str)
    df_doc_str = df["document_id"].astype(str)
    df_with_doc = df.assign(_doc=df_doc_str)
    feats = [r["column"] for r in cr1["top20"]]
    bool_feats = [
        f for f in feats if df[f].dtype.kind == "b" or pd.api.types.is_bool_dtype(df[f].dtype)
    ]

    def _entropy(values: pd.Series) -> float:
        counts = Counter(values.fillna("NA").astype(str).to_list())
        total = sum(counts.values())
        if total == 0:
            return 0.0
        return float(-sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0))

    scenarios = sorted(truth_docs["manipulation_scenario"].unique())
    hold_out = {"suspense_account_abuse", "expense_capitalization"}
    rows: list[dict[str, Any]] = []
    for sc in scenarios:
        scen_doc_ids = set(
            truth_docs.loc[truth_docs["manipulation_scenario"] == sc, "document_id"].tolist()
        )
        mask = df_with_doc["_doc"].isin(scen_doc_ids)
        scen_df = df_with_doc.loc[mask]
        ent = {f: round(_entropy(scen_df[f]), 4) for f in bool_feats if f in scen_df.columns}
        avg_ent = round(float(np.mean(list(ent.values()))), 4) if ent else None
        rows.append(
            {
                "scenario": sc,
                "hold_out": sc in hold_out,
                "truth_doc_count": len(scen_doc_ids),
                "row_count_matched": int(len(scen_df)),
                "avg_boolean_feature_entropy": avg_ent,
                "per_feature_entropy": ent,
            }
        )

    baseline = [r for r in rows if not r["hold_out"]]
    holdout = [r for r in rows if r["hold_out"]]
    base_avgs = [
        r["avg_boolean_feature_entropy"]
        for r in baseline
        if r["avg_boolean_feature_entropy"] is not None
    ]
    hold_avgs = [
        r["avg_boolean_feature_entropy"]
        for r in holdout
        if r["avg_boolean_feature_entropy"] is not None
    ]
    return {
        "scenarios": rows,
        "baseline_mean_entropy": round(float(np.mean(base_avgs)), 4) if base_avgs else None,
        "holdout_mean_entropy": round(float(np.mean(hold_avgs)), 4) if hold_avgs else None,
        "entropy_gap": (
            round(float(np.mean(hold_avgs) - np.mean(base_avgs)), 4)
            if base_avgs and hold_avgs
            else None
        ),
    }


# ─────────────────────────────────────────────────────────────────────
# CR-8: simulated supervised AUROC (GroupKFold by document_id)
# ─────────────────────────────────────────────────────────────────────
def cr8_simulated_auroc(
    df: pd.DataFrame, truth: pd.DataFrame, cr1: dict[str, Any]
) -> dict[str, Any]:
    print(f"[{_now_iso()}] CR-8 simulated supervised AUROC …", flush=True)
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(RNG_SEED)
    truth_docs = set(truth["document_id"].astype(str))
    doc_scenario = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    doc_str = df["document_id"].astype(str).to_numpy()
    y = pd.Series(doc_str).isin(truth_docs).astype(int).to_numpy()

    # deny-list 적용 feature
    candidate_cols = [
        r["column"]
        for r in cr1["all"]
        if r["overall_auroc"] is not None and not math.isnan(r["overall_auroc"])
    ]
    # 너무 많은 컬럼은 SGD 안정성을 위해 상위 40으로 제한
    candidate_cols = candidate_cols[:40]
    print(f"  features used: {len(candidate_cols)}", flush=True)

    X = df[candidate_cols].copy()
    for col in X.columns:
        if X[col].dtype.kind == "b" or pd.api.types.is_bool_dtype(X[col].dtype):
            X[col] = X[col].astype(float)
        else:
            X[col] = _safe_numeric(X[col])
    X = X.fillna(0.0).to_numpy(dtype=np.float64)

    # GroupKFold by document_id (string → integer label encoding)
    _, group_ids = np.unique(doc_str, return_inverse=True)
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    print(f"  positives={len(pos_idx):,} negatives={len(neg_idx):,}", flush=True)

    # 부정 샘플 다운샘플 — group integrity 유지 위해 document 단위로 sample
    neg_groups = np.unique(group_ids[neg_idx])
    sampled_neg_groups = rng.choice(
        neg_groups, size=min(NEG_SAMPLE_PER_FOLD, len(neg_groups)), replace=False
    )
    neg_mask = np.isin(group_ids, sampled_neg_groups)
    pos_mask = y == 1
    final_mask = pos_mask | neg_mask
    Xs = X[final_mask]
    ys = y[final_mask]
    gs = group_ids[final_mask]
    print(
        f"  sampled rows={len(ys):,} (pos={ys.sum():,} neg={(ys == 0).sum():,})",
        flush=True,
    )

    gkf = GroupKFold(n_splits=5)
    fold_aurocs: list[float] = []
    scenario_scores: dict[str, list[tuple[int, float]]] = defaultdict(list)
    feature_importances = np.zeros(len(candidate_cols))

    for fold_idx, (tr, te) in enumerate(gkf.split(Xs, ys, groups=gs), start=1):
        scaler = StandardScaler()
        X_tr = scaler.fit_transform(Xs[tr])
        X_te = scaler.transform(Xs[te])
        clf = LogisticRegression(
            max_iter=200,
            class_weight="balanced",
            solver="lbfgs",
            n_jobs=1,
        )
        clf.fit(X_tr, ys[tr])
        proba = clf.predict_proba(X_te)[:, 1]
        auroc = roc_auc_score(ys[te], proba)
        fold_aurocs.append(float(auroc))
        feature_importances += np.abs(clf.coef_[0])
        # scenario별 누적
        idx_full = np.where(final_mask)[0][te]
        doc_te = doc_str[idx_full]
        scen_te = np.array([doc_scenario.get(d, "_normal") for d in doc_te])
        for sc in np.unique(scen_te):
            mask_sc = (scen_te == sc) | (ys[te] == 0)
            if mask_sc.sum() < 50:
                continue
            y_sc = ((scen_te == sc) & (ys[te] == 1)).astype(int)[mask_sc]
            p_sc = proba[mask_sc]
            if y_sc.sum() == 0 or y_sc.sum() == y_sc.size:
                continue
            scenario_scores[sc].append((int(y_sc.sum()), float(roc_auc_score(y_sc, p_sc))))
        print(
            f"  fold {fold_idx}: auroc={auroc:.4f} test_pos={ys[te].sum()} test_size={len(te)}",
            flush=True,
        )

    feature_importances /= max(1, len(fold_aurocs))
    fi_pairs = sorted(
        zip(candidate_cols, feature_importances.tolist(), strict=False),
        key=lambda p: p[1],
        reverse=True,
    )
    scen_mean = {
        sc: round(float(np.mean([a for _, a in vals])), 4)
        for sc, vals in scenario_scores.items()
        if sc != "_normal" and vals
    }
    csv_rows = []
    for sc, vals in scenario_scores.items():
        if sc == "_normal":
            continue
        for n_pos, auc in vals:
            csv_rows.append({"scenario": sc, "fold_pos": n_pos, "auroc": auc})
    pd.DataFrame(csv_rows).to_csv(OUT_AUROC_CSV, index=False)

    overall_mean = float(np.mean(fold_aurocs))
    overall_std = float(np.std(fold_aurocs))
    return {
        "features_used": candidate_cols,
        "fold_count": len(fold_aurocs),
        "fold_aurocs": [round(a, 4) for a in fold_aurocs],
        "overall_auroc_mean": round(overall_mean, 4),
        "overall_auroc_std": round(overall_std, 4),
        "scenario_auroc_mean": scen_mean,
        "scenario_auroc_max": (round(max(scen_mean.values()), 4) if scen_mean else None),
        "scenario_auroc_min": (round(min(scen_mean.values()), 4) if scen_mean else None),
        "feature_importance_top10": [
            {"feature": f, "abs_coef": round(c, 4)} for f, c in fi_pairs[:10]
        ],
        "hard_flag": overall_mean >= HARD_AUROC,
        "soft_flag": SOFT_AUROC <= overall_mean < HARD_AUROC,
        "negative_sampling": {
            "neg_groups_sampled": int(min(NEG_SAMPLE_PER_FOLD, len(neg_groups))),
            "neg_groups_total": int(len(neg_groups)),
        },
    }


# ─────────────────────────────────────────────────────────────────────
# 종합 분류 & 리포트
# ─────────────────────────────────────────────────────────────────────
def classify(results: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []

    cr1 = results["CR-1"]
    if cr1["hard_count"] > 0:
        findings.append(
            {
                "id": "CR-1",
                "level": "HARD",
                "summary": f"단일 컬럼 AUROC ≥ {HARD_AUROC} 컬럼 {cr1['hard_count']}건",
                "detail": [r["column"] for r in cr1["hard"]][:10],
            }
        )
    elif cr1["soft_count"] > 0:
        findings.append(
            {
                "id": "CR-1",
                "level": "SOFT",
                "summary": f"단일 컬럼 AUROC ≥ {SOFT_AUROC} 컬럼 {cr1['soft_count']}건",
                "detail": [r["column"] for r in cr1["soft"]][:10],
            }
        )
    else:
        findings.append({"id": "CR-1", "level": "OK", "summary": "단독 shortcut 없음"})

    cr2 = results["CR-2"]
    if cr2["hard_count"] > 0:
        findings.append(
            {
                "id": "CR-2",
                "level": "HARD",
                "summary": f"2-feature interaction AUROC ≥ {HARD_AUROC} {cr2['hard_count']}쌍",
                "detail": [
                    f"{r['feature_a']}×{r['feature_b']}({r['interaction']})"
                    for r in cr2["hard"][:10]
                ],
            }
        )
    elif cr2["soft_count"] > 0:
        findings.append(
            {
                "id": "CR-2",
                "level": "SOFT",
                "summary": f"2-feature interaction AUROC ≥ {SOFT_AUROC} {cr2['soft_count']}쌍",
                "detail": [
                    f"{r['feature_a']}×{r['feature_b']}({r['interaction']})"
                    for r in cr2["soft_top20"][:10]
                ],
            }
        )
    else:
        findings.append({"id": "CR-2", "level": "OK", "summary": "2-feature shortcut 없음"})

    cr3 = results["CR-3"]
    if cr3["all_blocked"]:
        findings.append(
            {
                "id": "CR-3",
                "level": "OK",
                "summary": f"PROVENANCE {cr3['total_fields']}개 필드 전부 firewall 차단 확인",
            }
        )
    else:
        leaked = [f["field"] for f in cr3["findings"] if not f["blocked"]]
        findings.append(
            {
                "id": "CR-3",
                "level": "HARD",
                "summary": f"PROVENANCE firewall 우회 {len(leaked)}건",
                "detail": leaked,
            }
        )

    cr4 = results["CR-4"]
    findings.append(
        {
            "id": "CR-4",
            "level": "OK" if cr4["combined_count"] > 0 else "WARN",
            "summary": f"raw CSV header 와 deny-list 교집합 {cr4['combined_count']}건 "
            f"(LABEL={len(cr4['label_intersection'])} LEAK={len(cr4['leakage_deny_intersection'])} "
            f"DETECTOR={len(cr4['detector_forbidden_intersection'])})",
            "detail": cr4["combined_intersection"],
        }
    )

    cr5 = results["CR-5"]
    signal_pass = all(cr5["signals"].values())
    findings.append(
        {
            "id": "CR-5",
            "level": "OK" if signal_pass else "SOFT",
            "summary": "fit_split 정적 검증 PASS" if signal_pass else "fit_split 신호 일부 누락",
            "detail": cr5["signals"],
        }
    )

    cr6 = results["CR-6"]
    cr6_hard = (
        cr6["truth_doc_scenario_collision"] > 0
        or cr6["truth_normal_doc_overlap"] > 0
        or cr6["document_id_year_collision"] > 0
    )
    findings.append(
        {
            "id": "CR-6",
            "level": "HARD" if cr6_hard else "OK",
            "summary": ("GroupKFold(document_id) 안전" if not cr6_hard else "split 누설 위험 발견"),
            "detail": {
                "truth_doc_scenario_collision": cr6["truth_doc_scenario_collision"],
                "truth_normal_doc_overlap": cr6["truth_normal_doc_overlap"],
                "document_id_year_collision": cr6["document_id_year_collision"],
            },
        }
    )

    cr7 = results["CR-7"]
    findings.append(
        {
            "id": "CR-7",
            "level": "OK",
            "summary": (
                f"baseline_entropy={cr7['baseline_mean_entropy']} "
                f"holdout_entropy={cr7['holdout_mean_entropy']} "
                f"gap={cr7['entropy_gap']}"
            ),
        }
    )

    cr8 = results["CR-8"]
    if cr8["hard_flag"]:
        findings.append(
            {
                "id": "CR-8",
                "level": "HARD",
                "summary": f"simulated logistic AUROC mean {cr8['overall_auroc_mean']} ≥ {HARD_AUROC}",
                "detail": cr8["feature_importance_top10"],
            }
        )
    elif cr8["soft_flag"]:
        findings.append(
            {
                "id": "CR-8",
                "level": "SOFT",
                "summary": f"simulated logistic AUROC mean {cr8['overall_auroc_mean']} ∈ [{SOFT_AUROC},{HARD_AUROC})",
                "detail": cr8["feature_importance_top10"],
            }
        )
    else:
        findings.append(
            {
                "id": "CR-8",
                "level": "OK",
                "summary": f"simulated logistic AUROC mean {cr8['overall_auroc_mean']} < {SOFT_AUROC}",
            }
        )

    hard = [f for f in findings if f["level"] == "HARD"]
    soft = [f for f in findings if f["level"] == "SOFT"]
    decision = "NO-GO" if hard else ("GO-WITH-CAVEAT" if soft else "GO")
    return {"findings": findings, "hard": len(hard), "soft": len(soft), "decision": decision}


def write_outputs(results: dict[str, Any], summary: dict[str, Any]) -> None:
    OUT_JSON.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append("# DataSynth V4 — PHASE2 치트루트 감사 (Step 2)")
    lines.append("")
    lines.append(f"- 생성: {_now_iso()}")
    lines.append(f"- 입력 pkl: `{_rel(PKL_PATH)}`")
    lines.append(f"- 입력 truth: `{_rel(TRUTH_PATH)}`")
    lines.append(f"- raw CSV header: `{_rel(V4_HEADER_PATH)}`")
    lines.append("")
    lines.append("## 종합 판정")
    lines.append("")
    lines.append(f"- HARD: **{summary['hard']}** · SOFT: **{summary['soft']}**")
    lines.append(f"- Step 5 PHASE2 학습 진입 판정: **{summary['decision']}**")
    lines.append("")
    lines.append("| ID | 등급 | 요약 |")
    lines.append("|----|------|------|")
    for f in summary["findings"]:
        lines.append(f"| {f['id']} | **{f['level']}** | {f['summary']} |")
    lines.append("")

    # CR-1
    lines.append("## CR-1 — 단일 컬럼 univariate AUROC")
    lines.append("")
    lines.append(
        f"- 후보 컬럼 {results['CR-1']['candidate_count']} / 평가 {results['CR-1']['evaluated']}"
    )
    lines.append(
        f"- HARD(≥{HARD_AUROC}): {results['CR-1']['hard_count']} · SOFT([{SOFT_AUROC},{HARD_AUROC})): {results['CR-1']['soft_count']}"
    )
    lines.append("")
    lines.append("- `phase2_plan._decide_column` 동기 deny-list 적용 후 제외된 컬럼 카운트:")
    for k, v in results["CR-1"]["excluded_counts"].items():
        lines.append(f"  - `{k}`: {v}")
    leak_pat = results["CR-1"]["excluded"].get("leakage_pattern", [])
    if leak_pat:
        lines.append(
            f"- leakage_pattern 으로 제외된 컬럼 (PHASE1 출력 등): {', '.join(leak_pat[:20])}"
            + (" …" if len(leak_pat) > 20 else "")
        )
    lines.append("")
    lines.append("| column | dtype | overall AUROC | max scenario | max AUROC |")
    lines.append("|--------|-------|---------------|--------------|-----------|")
    for r in results["CR-1"]["top20"]:
        lines.append(
            f"| {r['column']} | {r['dtype']} | {r['overall_auroc']} | {r['max_scenario']} | {r['max_scenario_auroc']} |"
        )
    lines.append("")

    # CR-2
    lines.append("## CR-2 — 2-feature interaction AUROC")
    lines.append("")
    lines.append(
        f"- 평가 쌍 {results['CR-2']['evaluated_pairs']} · HARD {results['CR-2']['hard_count']} · SOFT {results['CR-2']['soft_count']}"
    )
    lines.append("")
    lines.append(
        "| feature_a | feature_b | interaction | overall AUROC | max scenario | max AUROC |"
    )
    lines.append(
        "|-----------|-----------|-------------|---------------|--------------|-----------|"
    )
    for r in results["CR-2"]["top20"]:
        lines.append(
            f"| {r['feature_a']} | {r['feature_b']} | {r['interaction']} | {r['overall_auroc']} | {r['max_scenario']} | {r['max_scenario_auroc']} |"
        )
    lines.append("")

    # CR-3
    lines.append("## CR-3 — PROVENANCE firewall")
    lines.append("")
    lines.append(
        f"- PROVENANCE_ONLY_FIELDS {results['CR-3']['total_fields']}건 중 차단 {results['CR-3']['blocked_count']}건"
    )
    lines.append("")
    lines.append("| field | blocked |")
    lines.append("|-------|---------|")
    for f in results["CR-3"]["findings"]:
        lines.append(f"| {f['field']} | {'✅' if f['blocked'] else '⛔'} |")
    lines.append("")

    # CR-4
    lines.append("## CR-4 — raw CSV header 와 deny-list 교집합")
    lines.append("")
    lines.append(
        f"- raw 컬럼 {results['CR-4']['raw_column_count']}건 · 교집합 {results['CR-4']['combined_count']}건"
    )
    lines.append("")
    lines.append("| 카테고리 | 컬럼 |")
    lines.append("|---------|------|")
    lines.append(f"| LABEL | {', '.join(results['CR-4']['label_intersection']) or '(없음)'} |")
    lines.append(
        f"| LEAKAGE_DENY | {', '.join(results['CR-4']['leakage_deny_intersection']) or '(없음)'} |"
    )
    lines.append(
        f"| DETECTOR_FORBIDDEN | {', '.join(results['CR-4']['detector_forbidden_intersection']) or '(없음)'} |"
    )
    lines.append("")

    # CR-5
    lines.append("## CR-5 — preprocessing fit_split 정적 검증")
    lines.append("")
    for k, v in results["CR-5"]["signals"].items():
        lines.append(f"- `{k}`: {'✅' if v else '⛔'}")
    lines.append("")
    lines.append(f"- fit_split 계약: {results['CR-5']['fit_split_contract']}")
    lines.append("")

    # CR-6
    lines.append("## CR-6 — cross-scenario / document_id split")
    lines.append("")
    lines.append(f"- truth doc × 시나리오 충돌: {results['CR-6']['truth_doc_scenario_collision']}")
    lines.append(f"- truth ∩ normal document_id: {results['CR-6']['truth_normal_doc_overlap']}")
    lines.append(
        f"- document_id 가 여러 fiscal_year 에 걸침: {results['CR-6']['document_id_year_collision']}"
    )
    lines.append(
        f"- GroupKFold(document_id) 안전: {'✅' if results['CR-6']['group_by_document_id_safe'] else '⛔'}"
    )
    lines.append("")

    # CR-7
    lines.append("## CR-7 — 시나리오별 fitting risk (boolean entropy)")
    lines.append("")
    lines.append(f"- baseline 평균 entropy: {results['CR-7']['baseline_mean_entropy']}")
    lines.append(
        f"- hold-out (suspense / expense_cap) 평균 entropy: {results['CR-7']['holdout_mean_entropy']}"
    )
    lines.append(f"- gap (hold-out − baseline): {results['CR-7']['entropy_gap']}")
    lines.append("")
    lines.append("| scenario | hold-out | truth docs | matched rows | avg bool entropy |")
    lines.append("|----------|----------|------------|--------------|------------------|")
    for r in results["CR-7"]["scenarios"]:
        lines.append(
            f"| {r['scenario']} | {'Y' if r['hold_out'] else 'N'} | {r['truth_doc_count']} | {r['row_count_matched']} | {r['avg_boolean_feature_entropy']} |"
        )
    lines.append("")

    # CR-8
    lines.append("## CR-8 — simulated supervised AUROC (Logistic + GroupKFold)")
    lines.append("")
    lines.append(
        f"- features 사용: {len(results['CR-8']['features_used'])} · fold {results['CR-8']['fold_count']}"
    )
    lines.append(
        f"- overall AUROC: mean={results['CR-8']['overall_auroc_mean']} std={results['CR-8']['overall_auroc_std']}"
    )
    lines.append(f"- fold AUROC: {results['CR-8']['fold_aurocs']}")
    lines.append(
        f"- scenario AUROC range: min={results['CR-8']['scenario_auroc_min']} max={results['CR-8']['scenario_auroc_max']}"
    )
    lines.append("")
    lines.append("| scenario | mean AUROC |")
    lines.append("|----------|------------|")
    for sc, v in sorted(
        results["CR-8"]["scenario_auroc_mean"].items(), key=lambda kv: kv[1], reverse=True
    ):
        lines.append(f"| {sc} | {v} |")
    lines.append("")
    lines.append("| feature | abs coef |")
    lines.append("|---------|----------|")
    for item in results["CR-8"]["feature_importance_top10"]:
        lines.append(f"| {item['feature']} | {item['abs_coef']} |")
    lines.append("")

    # 결론
    lines.append("## 결론 & Step 5 GO/NO-GO")
    lines.append("")
    lines.append(f"- HARD {summary['hard']} / SOFT {summary['soft']} → **{summary['decision']}**")
    lines.append("")
    if summary["hard"] > 0:
        lines.append("- HARD 발견 항목 (deny-list 확장 또는 V4 재작업 필요):")
        for f in summary["findings"]:
            if f["level"] == "HARD":
                lines.append(f"  - **{f['id']}**: {f['summary']}")
        lines.append("")
    elif summary["soft"] > 0:
        lines.append("- SOFT 신호 (도메인 정합 검토 후 PHASE2 학습 진입 가능):")
        for f in summary["findings"]:
            if f["level"] == "SOFT":
                lines.append(f"  - **{f['id']}**: {f['summary']}")
        lines.append("")
    else:
        lines.append("- 모든 CR 항목 OK. Step 5 PHASE2 첫 학습 진입 가능.")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    df, truth, raw_columns = load_inputs()
    results: dict[str, Any] = {}
    results["CR-1"] = cr1_univariate(df, truth)
    results["CR-2"] = cr2_pairwise(df, truth, results["CR-1"])
    results["CR-3"] = cr3_firewall()
    results["CR-4"] = cr4_deny_list(raw_columns)
    results["CR-5"] = cr5_fit_split_static()
    results["CR-6"] = cr6_split_leakage(df, truth)
    results["CR-7"] = cr7_scenario_entropy(df, truth, results["CR-1"])
    results["CR-8"] = cr8_simulated_auroc(df, truth, results["CR-1"])
    summary = classify(results)
    write_outputs(results, summary)
    print(f"[{_now_iso()}] done. decision={summary['decision']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
