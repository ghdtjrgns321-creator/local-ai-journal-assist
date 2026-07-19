"""Stage 5 — Phase1 룰 ↔ manipulated truth 순환학습 정합 분석.

목적:
  PHASE1 룰 hit 결과만으로 manipulated 분류가 어디까지 가능한지 측정한다.
  결과가 강하면(>=0.85) PHASE2 ML 입력에 24-dim 룰 결과를 그대로 끼워 넣는 설계는
  순환학습 위험을 안고 있는 것으로 판정한다.

산출:
  artifacts/S5_circular_learning_overlap.json  — 룰 × 시나리오 hit-rate matrix + 분류 지표
  artifacts/S5_phase2_input_redesign.md         — 37차원 vs 42차원 권고 문서

판정 기준 (요청 prompt 그대로):
  AUPRC >= 0.85 → 룰 결과 ML 입력 = 순환학습
  AUPRC ∈ [0.6, 0.85] → partial overlap, sparse feature 한정 사용 권고
  AUPRC < 0.6 → 룰과 ML 독립 신호 → 그대로 진행 가능

실행:
  uv run python tools/analysis/s5_circular_learning.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402
from sklearn.model_selection import GroupKFold  # noqa: E402

DATA_DIR = Path(
    os.getenv(
        "DATASYNTH_MANIPULATION_DATA_DIR",
        str(ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"),
    )
)
LABELS_PATH = DATA_DIR / "labels" / "manipulated_entry_truth.csv"
OUT_JSON = Path(
    os.getenv("S5_OUT_JSON", str(ROOT / "artifacts" / "S5_circular_learning_overlap.json"))
)
OUT_MD = Path(os.getenv("S5_OUT_MD", str(ROOT / "artifacts" / "S5_phase2_input_redesign.md")))

SCENARIO_ALIAS = {
    "fictitious_entry": "fictitious_entry",
    "period_end_adjustment_manipulation": "period_end_adjustment",
    "embezzlement_concealment": "embezzlement_concealment",
    "circular_related_party_transaction": "circular_related_party",
    "approval_sod_bypass": "approval_sod_bypass",
    "unusual_timing_manipulation": "unusual_timing_manipulation",
    "suspense_account_abuse": "suspense_account_abuse",
    "expense_capitalization": "expense_capitalization",
}


def load_journal() -> pd.DataFrame:
    """v3 journal_entries 3년치 로드 + 컬럼 dtype 정리."""
    parts = []
    for year in (2022, 2023, 2024):
        path = DATA_DIR / f"journal_entries_{year}.csv"
        df_part = pd.read_csv(path, low_memory=False, dtype={"gl_account": "string"})
        parts.append(df_part)
    df = pd.concat(parts, ignore_index=True)

    # Why: 탐지기는 numeric 컬럼을 요구하고, datasynth는 NaN/공백 혼재 → 안전 캐스트
    for col in ("debit_amount", "credit_amount", "local_amount", "tax_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in ("posting_date", "document_date", "approval_date", "delivery_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "fiscal_period" in df.columns:
        df["fiscal_period"] = pd.to_numeric(df["fiscal_period"], errors="coerce")
    if "fiscal_year" in df.columns:
        df["fiscal_year"] = pd.to_numeric(df["fiscal_year"], errors="coerce").astype("Int64")
    if "sod_violation" in df.columns:
        df["sod_violation"] = (
            df["sod_violation"].astype("string").str.lower().map({"true": True, "false": False})
        )
    if "has_attachment" in df.columns:
        df["has_attachment"] = (
            df["has_attachment"].astype("string").str.lower().map({"true": True, "false": False})
        )
    return df


def load_chart_of_accounts() -> set[str]:
    """v3 dataset의 chart_of_accounts.json에서 account_number set 로드."""
    coa_path = DATA_DIR / "chart_of_accounts.json"
    coa_raw = json.loads(coa_path.read_text(encoding="utf-8"))
    return {str(acc["account_number"]).strip() for acc in coa_raw["accounts"]}


def run_phase1_detectors(df: pd.DataFrame, coa: set[str]) -> dict[str, pd.DataFrame]:
    """Phase1 4개 detector 실행 → details(rule × row) DataFrame dict.

    반환: {rule_id: bool_series indexed by df.index}
    """
    from config.settings import get_settings
    from src.detection.anomaly_layer import AnomalyDetector
    from src.detection.benford_detector import BenfordDetector
    from src.detection.fraud_layer import FraudLayer
    from src.detection.integrity_layer import IntegrityDetector

    settings = get_settings()
    detectors = [
        ("integrity", IntegrityDetector(settings, chart_of_accounts=coa)),
        ("fraud", FraudLayer(settings)),
        ("anomaly", AnomalyDetector(settings)),
        ("benford", BenfordDetector(settings)),
    ]

    rule_hit_series: dict[str, pd.Series] = {}
    detector_meta: dict[str, dict] = {}
    for name, det in detectors:
        t0 = time.monotonic()
        result = det.detect(df)
        elapsed = time.monotonic() - t0
        detector_meta[name] = {
            "elapsed_sec": round(elapsed, 2),
            "rules_run": result.total_rules_run,
            "flagged_rows": result.flagged_count,
            "warnings": list(result.warnings),
        }
        # details DataFrame: columns = rule_id, values = score (>0 = hit)
        details = result.details
        if details.shape[1] == 0:
            print(f"  [{name}] details 비어 있음 — skip")
            continue
        for rule_id in details.columns:
            hit = details[rule_id].fillna(0.0).gt(0)
            rule_hit_series[rule_id] = hit.reindex(df.index, fill_value=False).astype(bool)
        print(
            f"  [{name}] elapsed={elapsed:.1f}s, rules={result.total_rules_run}, flagged_rows={result.flagged_count}"
        )
    return rule_hit_series, detector_meta


def aggregate_to_doc_level(
    df: pd.DataFrame,
    rule_hit_series: dict[str, pd.Series],
) -> tuple[pd.DataFrame, list[str]]:
    """row → document_id 단위로 OR 집계 (any line hit → 1)."""
    rule_ids = sorted(rule_hit_series.keys())
    work = pd.DataFrame({"document_id": df["document_id"].astype(str).values})
    for rid in rule_ids:
        work[rid] = rule_hit_series[rid].astype(int).values
    doc_hits = work.groupby("document_id", sort=False)[rule_ids].max().astype(int)
    return doc_hits, rule_ids


def build_doc_matrix(
    df: pd.DataFrame,
    doc_hits: pd.DataFrame,
    truth_df: pd.DataFrame,
) -> pd.DataFrame:
    """doc_id → (rule hits, label, scenario, group key for KFold)."""
    doc_meta = (
        df.groupby("document_id", sort=False)
        .agg({"company_code": "first", "fiscal_year": "first"})
        .reset_index()
    )
    doc_meta["document_id"] = doc_meta["document_id"].astype(str)
    matrix = doc_meta.merge(doc_hits.reset_index(), on="document_id", how="left").fillna(0)
    matrix["label"] = matrix["document_id"].isin(truth_df["document_id"].astype(str)).astype(int)
    scen_lookup = (
        truth_df.set_index("document_id")["manipulation_scenario"].map(SCENARIO_ALIAS).to_dict()
    )
    matrix["scenario"] = matrix["document_id"].map(lambda d: scen_lookup.get(d, "normal"))
    matrix["group"] = matrix["company_code"].astype(str) + "::" + matrix["fiscal_year"].astype(str)
    return matrix


def compute_topk_recall(
    scores: np.ndarray,
    labels: np.ndarray,
    scenarios: np.ndarray,
    top_pct: float = 0.01,
) -> dict[str, float]:
    """전체 doc 중 score 상위 top_pct% 후보로 시나리오별 recall."""
    n = len(scores)
    k = max(int(n * top_pct), 1)
    order = np.argsort(-scores)
    flagged = np.zeros(n, dtype=bool)
    flagged[order[:k]] = True
    by_scen: dict[str, float] = {}
    overall = labels.astype(bool)
    by_scen["__overall__"] = float(flagged[overall].mean()) if overall.sum() else float("nan")
    unique_scens = sorted(set(scenarios[overall].tolist()))
    for s in unique_scens:
        mask = (scenarios == s) & overall
        by_scen[s] = float(flagged[mask].mean()) if mask.sum() else float("nan")
    return {"top_k": k, "recall": by_scen}


def fit_logreg_oof(matrix: pd.DataFrame, rule_ids: list[str], n_splits: int = 5):
    """GroupKFold (company × year) out-of-fold 확률 + 단순 sum-of-hits 베이스라인."""
    X = matrix[rule_ids].values.astype(float)
    y = matrix["label"].values.astype(int)
    groups = matrix["group"].values
    sum_score = X.sum(axis=1)

    n_groups = len(set(groups.tolist()))
    splits = min(n_splits, n_groups)
    gkf = GroupKFold(n_splits=splits)
    oof_proba = np.zeros(len(matrix), dtype=float)
    fold_aupr: list[float] = []
    for fold_idx, (tr, te) in enumerate(gkf.split(X, y, groups)):
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0, solver="lbfgs")
        if y[tr].sum() == 0:
            oof_proba[te] = 0.0
            continue
        clf.fit(X[tr], y[tr])
        proba = clf.predict_proba(X[te])[:, 1]
        oof_proba[te] = proba
        if y[te].sum() > 0:
            fold_aupr.append(float(average_precision_score(y[te], proba)))
    return {
        "oof_logreg_proba": oof_proba,
        "sum_hits_score": sum_score,
        "fold_aupr_logreg": fold_aupr,
        "n_splits_used": splits,
    }


def compute_rule_scenario_matrix(matrix: pd.DataFrame, rule_ids: list[str]) -> pd.DataFrame:
    """Rule × Scenario hit-rate matrix (manipulated docs only) + normal baseline."""
    rows = []
    normal_mask = matrix["scenario"].eq("normal")
    n_normal = int(normal_mask.sum())
    for rid in rule_ids:
        row = {"rule_id": rid}
        normal_rate = float(matrix.loc[normal_mask, rid].mean()) if n_normal else 0.0
        row["normal"] = normal_rate
        row["normal_count"] = int(matrix.loc[normal_mask, rid].sum())
        for scen in [
            "fictitious_entry",
            "period_end_adjustment",
            "embezzlement_concealment",
            "circular_related_party",
            "approval_sod_bypass",
            "unusual_timing_manipulation",
        ]:
            mask = matrix["scenario"].eq(scen)
            n = int(mask.sum())
            row[scen] = float(matrix.loc[mask, rid].mean()) if n else float("nan")
            row[f"{scen}_count"] = int(matrix.loc[mask, rid].sum())
            row[f"{scen}_n"] = n
        rows.append(row)
    return pd.DataFrame(rows)


def rank_top_predictive_rules(
    rule_scenario: pd.DataFrame,
    matrix: pd.DataFrame,
    rule_ids: list[str],
    n_top: int = 5,
) -> list[dict]:
    """단일 룰 univariate AUPRC + manipulated lift rank → top-5."""
    y = matrix["label"].values.astype(int)
    out: list[dict] = []
    for rid in rule_ids:
        x = matrix[rid].values.astype(float)
        if x.sum() == 0:
            aupr = 0.0
        else:
            aupr = float(average_precision_score(y, x))
        manipulated_hit = (
            float(matrix.loc[matrix["label"].eq(1), rid].mean()) if matrix["label"].sum() else 0.0
        )
        normal_hit = float(matrix.loc[matrix["label"].eq(0), rid].mean())
        lift = manipulated_hit / max(normal_hit, 1e-6)
        out.append(
            {
                "rule_id": rid,
                "univariate_auprc": aupr,
                "manipulated_hit_rate": manipulated_hit,
                "normal_hit_rate": normal_hit,
                "lift": lift,
            }
        )
    out.sort(key=lambda r: (-r["univariate_auprc"], -r["lift"]))
    return out[:n_top]


def evaluate_subset(
    matrix: pd.DataFrame,
    feature_cols: list[str],
    label_col: str = "label",
    group_col: str = "group",
) -> dict:
    """주어진 feature subset 으로 GroupKFold logreg AUPRC + recall@top-1% 측정."""
    X = matrix[feature_cols].values.astype(float)
    y = matrix[label_col].values.astype(int)
    groups = matrix[group_col].values
    splits = min(5, len(set(groups.tolist())))
    gkf = GroupKFold(n_splits=splits)
    oof = np.zeros(len(matrix), dtype=float)
    for tr, te in gkf.split(X, y, groups):
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", solver="lbfgs")
        if y[tr].sum() == 0:
            continue
        clf.fit(X[tr], y[tr])
        oof[te] = clf.predict_proba(X[te])[:, 1]
    aupr = float(average_precision_score(y, oof)) if y.sum() else float("nan")
    topk = compute_topk_recall(oof, y, matrix["scenario"].values)
    return {
        "auprc_oof_logreg": aupr,
        "n_features": len(feature_cols),
        "topk_recall_at_1pct": topk["recall"],
        "topk_k": topk["top_k"],
        "feature_cols": feature_cols,
    }


def write_outputs(
    detector_meta: dict,
    rule_ids: list[str],
    matrix: pd.DataFrame,
    rule_scenario: pd.DataFrame,
    metrics_24dim: dict,
    sum_metrics: dict,
    top5: list[dict],
    metrics_19dim: dict,
) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    by_scen_count = matrix.groupby("scenario")["label"].agg(["count", "sum"]).reset_index()
    payload = {
        "dataset": str(DATA_DIR.relative_to(ROOT)),
        "n_documents": int(len(matrix)),
        "n_manipulated": int(matrix["label"].sum()),
        "n_normal": int((matrix["label"] == 0).sum()),
        "rule_ids": rule_ids,
        "n_rules": len(rule_ids),
        "detector_meta": detector_meta,
        "scenario_population": by_scen_count.to_dict(orient="records"),
        "rule_x_scenario_hit_rate": rule_scenario.to_dict(orient="records"),
        "metrics_24dim_logreg": {
            "auprc_oof": metrics_24dim["auprc_oof"],
            "auprc_fold_mean": metrics_24dim["auprc_fold_mean"],
            "auprc_fold_std": metrics_24dim["auprc_fold_std"],
            "n_splits_used": metrics_24dim["n_splits_used"],
            "topk_recall_at_1pct": metrics_24dim["topk_recall"],
            "topk_k": metrics_24dim["topk_k"],
        },
        "metrics_sum_of_hits": sum_metrics,
        "top5_predictive_rules": top5,
        "metrics_remaining_after_top5_removed": metrics_19dim,
        "judgment": metrics_24dim["judgment"],
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] {OUT_JSON.relative_to(ROOT)} 작성")


def render_markdown(
    detector_meta: dict,
    rule_ids: list[str],
    matrix: pd.DataFrame,
    rule_scenario: pd.DataFrame,
    metrics_24dim: dict,
    sum_metrics: dict,
    top5: list[dict],
    metrics_19dim: dict,
) -> None:
    n_docs = len(matrix)
    n_pos = int(matrix["label"].sum())
    auprc = metrics_24dim["auprc_oof"]
    judgment = metrics_24dim["judgment"]
    topk = metrics_24dim["topk_recall"]

    lines: list[str] = []
    lines.append("# S5 — Phase1 룰 ↔ manipulated truth 순환학습 정합")
    lines.append("")
    lines.append("> 측정 일자: 2026-05-15")
    lines.append(f"> 데이터셋: `{DATA_DIR.relative_to(ROOT)}` (Rust candidate fixed, active)")
    lines.append("> 산출 스크립트: `tools/analysis/s5_circular_learning.py`")
    lines.append("> 원본 산출물: `artifacts/S5_circular_learning_overlap.json`")
    lines.append("")
    lines.append("## 1. 측정 대상")
    lines.append("")
    lines.append(f"- 문서 수: {n_docs:,}")
    lines.append(f"- manipulated truth: {n_pos:,} (positive prevalence ≈ {n_pos / n_docs:.4%})")
    lines.append(
        "- Phase1 detector: IntegrityDetector(L1) + FraudLayer(L2) + AnomalyDetector(L3) + BenfordDetector(L4)"
    )
    lines.append(
        f"- 활성 rule_id 수: **{len(rule_ids)}** "
        "(요청 prompt 의 '24개' 는 PHASE1 회복 가능 row-level 룰의 어림 수치이며, "
        "현재 v3 dataset 에서 Layer A/B/C/Benford 4 detector 가 실제로 출력한 룰은 "
        f"{len(rule_ids)}개. L4-01/L3-03/L1-04 등 데이터 컬럼 또는 통계량 부족으로 skip 된 룰은 미포함.)"
    )
    lines.append("")

    lines.append("### 1.1 detector 실행 메타")
    lines.append("")
    lines.append("```")
    for name, meta in detector_meta.items():
        lines.append(
            f"  {name:<10} elapsed={meta['elapsed_sec']:>6.1f}s  "
            f"rules={meta['rules_run']:>3}  flagged_rows={meta['flagged_rows']:>8,}"
        )
    lines.append("```")
    lines.append("")

    lines.append("### 1.2 활성 rule_id (alphabetic)")
    lines.append("")
    lines.append("`" + ", ".join(rule_ids) + "`")
    lines.append("")

    lines.append("## 2. 24-dim only 분류 결과")
    lines.append("")
    lines.append(f"- **AUPRC (GroupKFold OOF, LogReg)**: **{auprc:.4f}**")
    lines.append(
        f"  - fold mean ± std: {metrics_24dim['auprc_fold_mean']:.4f} ± {metrics_24dim['auprc_fold_std']:.4f}"
    )
    lines.append(f"  - n_splits used: {metrics_24dim['n_splits_used']}")
    lines.append(f"- **Sum-of-hits 베이스라인 AUPRC**: {sum_metrics['auprc']:.4f}")
    lines.append(
        f"- **Recall@top-1% (k={metrics_24dim['topk_k']:,})** — overall: {topk.get('__overall__', float('nan')):.4f}"
    )
    lines.append("")
    lines.append("| scenario | recall@top-1% (24-dim logreg) | recall@top-1% (sum-of-hits) |")
    lines.append("|---|---:|---:|")
    for scen in [
        "fictitious_entry",
        "period_end_adjustment",
        "embezzlement_concealment",
        "circular_related_party",
        "approval_sod_bypass",
        "unusual_timing_manipulation",
    ]:
        r1 = topk.get(scen, float("nan"))
        r2 = sum_metrics["topk_recall"].get(scen, float("nan"))
        lines.append(f"| {scen} | {r1:.4f} | {r2:.4f} |")
    lines.append("")

    lines.append("### 2.1 판정")
    lines.append("")
    lines.append(f"- AUPRC = **{auprc:.4f}** → 절대 임계 기준: **{judgment['verdict']}**")
    lines.append(f"- 권고 (절대 임계): {judgment['recommendation']}")
    lines.append(
        f"- Concentration risk (top-5 deny-list 결과 기준): **{judgment.get('concentration_risk', 'n/a')}**"
    )
    lines.append("")

    lines.append("## 3. Rule × Scenario hit-rate matrix")
    lines.append("")
    lines.append(
        "manipulated 시나리오별 hit-rate (해당 시나리오 doc 중 룰이 발화한 비율). normal 컬럼은 베이스라인."
    )
    lines.append("")
    cols = [
        "rule_id",
        "normal",
        "fictitious_entry",
        "period_end_adjustment",
        "embezzlement_concealment",
        "circular_related_party",
        "approval_sod_bypass",
        "unusual_timing_manipulation",
    ]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] + ["---:"] * (len(cols) - 1)) + " |"
    lines.append(header)
    lines.append(sep)
    for _, row in rule_scenario.iterrows():
        cells = [row["rule_id"]]
        for c in cols[1:]:
            v = row[c]
            cells.append("nan" if pd.isna(v) else f"{v:.3f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## 4. Top-5 predictive rules (univariate)")
    lines.append("")
    lines.append("| rank | rule_id | univariate AUPRC | manipulated hit | normal hit | lift |")
    lines.append("|---:|---|---:|---:|---:|---:|")
    for i, r in enumerate(top5, start=1):
        lines.append(
            f"| {i} | {r['rule_id']} | {r['univariate_auprc']:.4f} | "
            f"{r['manipulated_hit_rate']:.4f} | {r['normal_hit_rate']:.4f} | {r['lift']:.1f} |"
        )
    lines.append("")

    lines.append("## 5. Top-5 deny-list 시뮬레이션 + concentration 분석")
    lines.append("")
    lines.append(
        f"Top-5 predictive 룰을 features 에서 제거하고 나머지 {metrics_19dim['n_features']} 룰만으로 GroupKFold logreg:"
    )
    lines.append("")
    drop_ratio = judgment.get("concentration_drop_ratio") or 0.0
    residual_pct = (1 - drop_ratio) * 100
    lines.append(
        f"- AUPRC (deny-list, {metrics_19dim['n_features']}-dim): **{metrics_19dim['auprc_oof_logreg']:.4f}** "
        f"(원본 {auprc:.4f} 대비 잔존 {residual_pct:.2f}%, drop ratio {drop_ratio:.4f})"
    )
    lines.append(
        f"- Recall@top-1% (k={metrics_19dim['topk_k']:,}): overall = "
        f"{metrics_19dim['topk_recall_at_1pct'].get('__overall__', float('nan')):.4f}"
    )
    lines.append(f"- **Concentration risk: {judgment.get('concentration_risk', 'n/a')}**")
    if drop_ratio >= 0.95:
        lines.append("")
        lines.append(
            "> ⚠ Top-5 룰을 빼면 AUPRC 가 사실상 0 으로 붕괴 → manipulated 신호가 5 룰에 완전 집중. "
            "절대 AUPRC 가 0.6 미만이라도 ML 이 42-dim 입력에서 이 5 룰만 학습하는 shortcut 위험은 동일."
        )
    lines.append("")

    lines.append("## 6. PHASE2 입력 재설계 권고: 37차원 vs 42차원")
    lines.append("")
    lines.append("### 6.1 결정 행렬")
    lines.append("")
    lines.append("| 후보 입력 차원 | 근거 | 순환학습 위험 | 권고 |")
    lines.append("|---|---|---|---|")
    lines.append(
        "| 42-dim (18 raw feature + 24 rule hits) | 룰 결과를 ML 입력으로 직접 결합 | "
        f"**{judgment['risk_42dim']}** | {judgment['recommendation_42dim']} |"
    )
    lines.append(
        "| 37-dim (18 raw feature + 19 sparse rule, top-5 deny) | predictive top-5 룰을 빼서 ML 학습 자유도 확보 | "
        f"{judgment['risk_37dim']} | {judgment['recommendation_37dim']} |"
    )
    lines.append("")
    lines.append("### 6.2 권고")
    lines.append("")
    for line in judgment["redesign_notes"]:
        lines.append(f"- {line}")
    lines.append("")

    lines.append("## 7. 한계")
    lines.append("")
    lines.append(
        "- v3 dataset의 manipulated 비율(~0.13%)이 매우 낮아 fold AUPRC 분산이 크다. fold std 참고."
    )
    lines.append(
        "- BenfordDetector 는 단일 분포 검정으로 doc-level 신호가 약하다 (대부분 0). "
        "AUPRC 기여도는 작지만 컬럼은 유지해 분석 누락을 막았다."
    )
    lines.append(
        "- 분류기는 LogisticRegression class_weight='balanced' 단순 모델이다. "
        "트리 계열을 쓰면 룰 간 비선형 조합으로 AUPRC 가 더 올라갈 수 있어, 본 측정은 **하한 추정**이다."
    )
    lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] {OUT_MD.relative_to(ROOT)} 작성")


def make_judgment(
    auprc: float,
    sum_auprc: float,
    concentration_drop_ratio: float | None = None,
) -> dict:
    """판정 기준 적용 + 권고 문구 생성.

    concentration_drop_ratio: top-5 룰 제거 후 AUPRC drop 비율 (1 - residual / observed).
    값이 0.95 이상이면 신호가 5개 룰에 사실상 완전 집중 → shortcut 학습 위험 추가 경고.
    """
    if auprc >= 0.85:
        verdict = "순환학습 위험 (HIGH)"
        recommendation = (
            "PHASE2 ML 입력에 24-dim 룰 결과를 그대로 결합하는 것은 순환학습이다. "
            "05a-detection-ml.md 의 '42차원 = 18피처 + 24룰' 설계를 재검토하라."
        )
        risk_42dim = "HIGH (circular)"
        risk_37dim = "MEDIUM"
        recommendation_42dim = "사용 금지 — PHASE2 ML 입력에서 24-dim 룰 결과 제거"
        recommendation_37dim = (
            "Top-5 predictive 룰을 빼고 19개 sparse rule + 18 raw feature 로 운영"
        )
        notes = [
            "ML이 룰 출력을 그대로 학습하면 'PHASE1이 잡은 것을 PHASE2가 다시 잡는' 동어 반복이 된다.",
            "Top-5 predictive 룰은 deny-list 처리하고, 나머지는 sparse feature 로만 보조 사용한다.",
            "raw feature 18종은 (예: log_amount, line_count, dow, hour, doc_type 원-핫) 룰 hit과 직교한 신호로 유지한다.",
        ]
    elif auprc >= 0.6:
        verdict = "partial overlap (MEDIUM)"
        recommendation = "룰 결과는 sparse feature 로만 사용하고, ML 학습 셋에서 '룰 hit이 곧 라벨'이 되지 않도록 cross-validation 분리 (GroupKFold) 와 calibration 를 강제하라."
        risk_42dim = "MEDIUM"
        risk_37dim = "LOW"
        recommendation_42dim = "조건부 사용 — GroupKFold + leave-one-rule-out ablation 동반 시"
        recommendation_37dim = "권장 — Top-5 deny-list 적용 후 sparse 결합"
        notes = [
            "AUPRC 가 0.6~0.85 구간이면 룰이 manipulated 의 일부 신호를 포착하지만 단독 분류기로는 부족하다.",
            "ML 입력으로 결합 시 라벨 누수 방지를 위해 (a) GroupKFold (b) Top-5 룰 deny-list (c) sparse encoding 을 필수화한다.",
        ]
    else:
        verdict = "독립 신호 (LOW)"
        recommendation = "룰 결과는 manipulated 와 약한 상관만 가진다. 그대로 진행 가능하나, 일부 deterministic 룰만은 deny-list 권장."
        risk_42dim = "LOW"
        risk_37dim = "LOW"
        recommendation_42dim = "사용 가능 — Top-5 deny-list 만 적용해도 충분"
        recommendation_37dim = "선택 사용 — 운영 단순성 우선이면 24-dim 그대로 유지"
        notes = [
            "PHASE1 룰 출력은 manipulated 와 부분 직교 → 24-dim 그대로 사용해도 순환학습 효과 미미.",
            "단, AUPRC 가 가장 높은 deterministic 룰만은 deny-list 로 빼서 ML의 학습 여지를 확보한다.",
        ]

    # Concentration risk 추가 평가:
    # 절대 AUPRC 가 임계 미만이라도, top-5 제거 시 신호가 사실상 0 으로 떨어지면
    # ML 이 그 5개 룰을 shortcut 으로 학습하는 위험은 그대로 남는다.
    concentration_risk = "n/a"
    concentration_addendum: list[str] = []
    if concentration_drop_ratio is not None:
        if concentration_drop_ratio >= 0.95:
            concentration_risk = "HIGH (signal concentrated in <=5 rules)"
            risk_42dim = "HIGH (shortcut)" if not risk_42dim.startswith("HIGH") else risk_42dim
            recommendation_42dim = (
                "사용 금지 또는 Top-5 deny-list 필수 — Top-5 제거 시 AUPRC 가 "
                f"{(1 - concentration_drop_ratio) * 100:.2f}% 만 잔존 (shortcut 학습 명백)"
            )
            risk_37dim = "MEDIUM" if risk_37dim == "LOW" else risk_37dim
            recommendation_37dim = (
                "권장 — Top-5 deny-list 후 19개 sparse rule + 18 raw feature; "
                "Top-5 룰은 PHASE1 → PHASE3 narrator 입력으로만 노출"
            )
            concentration_addendum = [
                f"**Concentration shortcut 위험**: top-5 제거 후 AUPRC 가 원본의 "
                f"{(1 - concentration_drop_ratio) * 100:.2f}% 만 잔존. 신호가 deterministic 5 룰에 사실상 완전 집중.",
                "AUPRC 절대값은 0.6 미만이지만, ML 이 42-dim 입력에서 이 5 룰만 학습하는 shortcut 효과는 동일하다.",
                "→ 절대 AUPRC 기반 LOW 판정과 별도로, **42-dim 사용 시 Top-5 deny-list 는 필수**.",
            ]
        elif concentration_drop_ratio >= 0.80:
            concentration_risk = "MEDIUM"
            concentration_addendum = [
                f"top-5 제거 후 AUPRC 가 원본의 {(1 - concentration_drop_ratio) * 100:.2f}% 만 잔존 — 신호가 일부 룰에 집중.",
                "Top-5 deny-list 또는 sparse encoding 권장.",
            ]
        else:
            concentration_risk = "LOW"
            concentration_addendum = [
                f"top-5 제거 후 AUPRC 가 원본의 {(1 - concentration_drop_ratio) * 100:.2f}% 잔존 — 신호 분산.",
            ]
    notes = notes + concentration_addendum

    return {
        "verdict": verdict,
        "recommendation": recommendation,
        "risk_42dim": risk_42dim,
        "risk_37dim": risk_37dim,
        "recommendation_42dim": recommendation_42dim,
        "recommendation_37dim": recommendation_37dim,
        "redesign_notes": notes,
        "concentration_risk": concentration_risk,
        "concentration_drop_ratio": concentration_drop_ratio,
        "criteria": {
            "circular_threshold": 0.85,
            "partial_overlap_lower": 0.60,
            "auprc_observed": auprc,
            "sum_of_hits_auprc": sum_auprc,
            "concentration_shortcut_threshold": 0.95,
        },
    }


def main() -> None:
    print("[S5] v3 journal_entries 로드 ...")
    df = load_journal()
    print(f"  rows={len(df):,}  docs={df['document_id'].nunique():,}")

    print("[S5] manipulated truth 로드 ...")
    truth_df = pd.read_csv(LABELS_PATH)
    truth_df["document_id"] = truth_df["document_id"].astype(str)
    print(
        f"  manipulated docs={len(truth_df):,}, scenarios={truth_df['manipulation_scenario'].nunique()}"
    )

    print("[S5] chart_of_accounts 로드 ...")
    coa = load_chart_of_accounts()
    print(f"  coa accounts={len(coa):,}")

    print("[S5] Phase1 detector 실행 ...")
    rule_hit_series, detector_meta = run_phase1_detectors(df, coa)
    print(f"[S5] 활성 rule_id={len(rule_hit_series)}: {sorted(rule_hit_series.keys())}")

    print("[S5] 문서 단위 OR 집계 ...")
    doc_hits, rule_ids = aggregate_to_doc_level(df, rule_hit_series)
    print(f"  doc rows={len(doc_hits):,}  rules={len(rule_ids)}")

    print("[S5] 매트릭스 빌드 ...")
    matrix = build_doc_matrix(df, doc_hits, truth_df)
    print(f"  matrix shape={matrix.shape}  positives={matrix['label'].sum()}")

    print("[S5] 24-dim only 분류 (LogReg + sum-of-hits) ...")
    fit = fit_logreg_oof(matrix, rule_ids, n_splits=5)
    auprc_oof = float(average_precision_score(matrix["label"].values, fit["oof_logreg_proba"]))
    sum_auprc = float(average_precision_score(matrix["label"].values, fit["sum_hits_score"]))
    print(f"  AUPRC (oof logreg) = {auprc_oof:.4f}")
    print(f"  AUPRC (sum-of-hits) = {sum_auprc:.4f}")

    topk_log = compute_topk_recall(
        fit["oof_logreg_proba"],
        matrix["label"].values,
        matrix["scenario"].values,
    )
    topk_sum = compute_topk_recall(
        fit["sum_hits_score"],
        matrix["label"].values,
        matrix["scenario"].values,
    )

    # Why: judgment 에 concentration ratio 를 반영하려면 top-5 deny-list 결과가 먼저 필요.
    print("[S5] Rule × Scenario hit-rate matrix ...")
    rule_scenario = compute_rule_scenario_matrix(matrix, rule_ids)

    print("[S5] Top-5 predictive 룰 ...")
    top5 = rank_top_predictive_rules(rule_scenario, matrix, rule_ids, n_top=5)
    for r in top5:
        print(
            f"  {r['rule_id']:<8}  AUPRC={r['univariate_auprc']:.4f}  "
            f"manip_hit={r['manipulated_hit_rate']:.3f}  normal_hit={r['normal_hit_rate']:.3f}  lift={r['lift']:.1f}"
        )
    top5_ids = {r["rule_id"] for r in top5}
    deny_cols = [r for r in rule_ids if r not in top5_ids]

    print(f"[S5] {len(deny_cols)}-dim deny-list 시뮬레이션 ...")
    metrics_19dim = evaluate_subset(matrix, deny_cols)
    drop_ratio = 1.0 - (metrics_19dim["auprc_oof_logreg"] / auprc_oof) if auprc_oof > 0 else 0.0
    print(
        f"  AUPRC after deny-list = {metrics_19dim['auprc_oof_logreg']:.4f} "
        f"(원본 대비 {(1 - drop_ratio) * 100:.2f}% 잔존)"
    )

    judgment = make_judgment(auprc_oof, sum_auprc, concentration_drop_ratio=drop_ratio)
    metrics_24dim = {
        "auprc_oof": auprc_oof,
        "auprc_fold_mean": float(np.mean(fit["fold_aupr_logreg"]))
        if fit["fold_aupr_logreg"]
        else float("nan"),
        "auprc_fold_std": float(np.std(fit["fold_aupr_logreg"]))
        if fit["fold_aupr_logreg"]
        else float("nan"),
        "n_splits_used": fit["n_splits_used"],
        "topk_recall": topk_log["recall"],
        "topk_k": topk_log["top_k"],
        "judgment": judgment,
    }
    sum_metrics = {
        "auprc": sum_auprc,
        "topk_recall": topk_sum["recall"],
        "topk_k": topk_sum["top_k"],
    }

    print("[S5] 산출물 작성 ...")
    write_outputs(
        detector_meta,
        rule_ids,
        matrix,
        rule_scenario,
        metrics_24dim,
        sum_metrics,
        top5,
        metrics_19dim,
    )
    render_markdown(
        detector_meta,
        rule_ids,
        matrix,
        rule_scenario,
        metrics_24dim,
        sum_metrics,
        top5,
        metrics_19dim,
    )

    print(f"\n[S5] 판정: {judgment['verdict']}  (AUPRC={auprc_oof:.4f})")


if __name__ == "__main__":
    main()
