"""Phase 2 Fitting Audit — Stage 1: Label Leakage Deny-list & Iterative Audit.

Stage 0 (`S0_column_catalog.json`) 산출을 기반으로 다음을 수행한다:
1. 명시 deny-list (mutation_* / semantic_scenario_id / detection_surface_hints)
   + Stage 0 의 AUROC ≥ 0.95 컬럼 union 으로 초기 deny-list 를 만든다.
2. 데이터에서 deny-list 컬럼을 제거한 `X_clean` 을 만들고 잔여 컬럼의 단일-컬럼 AUROC
   를 재계산한다.
3. AUROC ≥ 0.99 컬럼이 남아 있으면 deny-list 에 추가하고 1~2 를 반복 (최대 3회).
4. 최종 deny-list / iteration trace / 잔여 의심 컬럼 / enforce 코드 위치 제안을 출력한다.

산출:
- `tests/datasynth_quality_gate/results/phase2_fitting_audit/S1_leakage_columns_audit.json`
- `tests/datasynth_quality_gate/results/phase2_fitting_audit/S1_leakage_enforcement_plan.md`
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[3]
DATASET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"
JE_PATH = DATASET_DIR / "journal_entries.csv"
TRUTH_PATH = DATASET_DIR / "labels" / "manipulated_entry_truth.csv"
OUT_DIR = ROOT / "tests" / "datasynth_quality_gate" / "results" / "phase2_fitting_audit"
S0_JSON = OUT_DIR / "S0_column_catalog.json"

# 사용자 명시 deny-list (Stage 1 prompt) — 항상 포함된다.
EXPLICIT_DENY_LIST = frozenset(
    {
        "mutation_base_event_type",
        "mutation_type",
        "mutation_mutated_field",
        "mutation_original_value",
        "mutation_mutated_value",
        "mutation_reason",
        "semantic_scenario_id",
        "detection_surface_hints",
    }
)

# Stage 0 자동 분류 임계값: AUROC ≥ AUROC_LEAK_THRESHOLD 컬럼은 초기 deny-list 합류.
AUROC_LEAK_THRESHOLD = 0.95
# 잔여 검증 임계값: X_clean 에서 ≥ AUROC_RESIDUAL_THRESHOLD 인 컬럼은 추가 deny.
AUROC_RESIDUAL_THRESHOLD = 0.99
# 반복 한도.
MAX_ITERATIONS = 3

# 라벨/타겟 컬럼 — feature 후보에서 항상 제외 (deny-list 와 별개의 라벨 컬럼).
TARGET_LABEL_COLUMNS = frozenset(
    {
        "is_fraud",
        "fraud_type",
        "is_anomaly",
        "anomaly_type",
        "sod_violation",
        "sod_conflict_type",
    }
)


def _column_auroc(series: pd.Series, y: np.ndarray) -> float | None:
    """단일 컬럼 AUROC — Stage 0 와 동일 인코딩 규약 (대칭화)."""
    if series.isna().all():
        return None
    s = series.copy()
    if s.dtype == bool or pd.api.types.is_bool_dtype(s):
        score = s.fillna(False).astype(int).to_numpy()
    elif pd.api.types.is_numeric_dtype(s):
        score = s.fillna(s.median()).astype(float).to_numpy()
    elif pd.api.types.is_datetime64_any_dtype(s):
        score = (
            s.view("int64")
            .where(~s.isna(), other=pd.Series(s.view("int64")).median())
            .astype(float)
            .to_numpy()
        )
    else:
        s = s.astype("object").where(~s.isna(), other="__NA__")
        target_map = pd.Series(y, index=s.index).groupby(s).mean()
        score = s.map(target_map).astype(float).to_numpy()
    if np.unique(y).size < 2:
        return None
    try:
        auroc = roc_auc_score(y, score)
    except ValueError:
        return None
    return float(max(auroc, 1.0 - auroc))


def _build_initial_deny_list(s0_payload: dict) -> tuple[set[str], dict[str, str]]:
    """Stage 0 catalog → 초기 deny-list 와 각 컬럼의 분류 사유."""
    deny: set[str] = set(EXPLICIT_DENY_LIST)
    reason_map: dict[str, str] = {col: "explicit_user_denylist" for col in EXPLICIT_DENY_LIST}
    for entry in s0_payload["columns"]:
        col = entry["column"]
        auroc = entry.get("auroc_vs_manipulated")
        if auroc is not None and auroc >= AUROC_LEAK_THRESHOLD:
            deny.add(col)
            reason_map.setdefault(col, f"s0_auroc>={AUROC_LEAK_THRESHOLD:.2f}")
    return deny, reason_map


def _residual_audit(
    df: pd.DataFrame,
    y: np.ndarray,
    deny: set[str],
) -> list[dict]:
    """X_clean = df.drop(deny) 에서 잔여 컬럼의 단일-컬럼 AUROC 계산."""
    feature_cols = [
        col for col in df.columns if col not in deny and col not in TARGET_LABEL_COLUMNS
    ]
    audit: list[dict] = []
    for col in feature_cols:
        auroc = _column_auroc(df[col], y)
        audit.append(
            {
                "column": col,
                "auroc_vs_manipulated": auroc,
            }
        )
    audit.sort(key=lambda x: -(x["auroc_vs_manipulated"] or -1.0))
    return audit


def _iterate_until_clean(
    df: pd.DataFrame,
    y: np.ndarray,
    initial_deny: set[str],
    initial_reason: dict[str, str],
) -> dict:
    """반복 deny-list 확장 — 최대 MAX_ITERATIONS 회."""
    deny = set(initial_deny)
    reason_map = dict(initial_reason)
    iterations: list[dict] = []
    final_audit: list[dict] = []

    for round_idx in range(1, MAX_ITERATIONS + 1):
        audit = _residual_audit(df, y, deny)
        residual_above = [
            r
            for r in audit
            if r["auroc_vs_manipulated"] is not None
            and r["auroc_vs_manipulated"] >= AUROC_RESIDUAL_THRESHOLD
        ]
        iteration_record = {
            "round": round_idx,
            "denylist_size_before": len(deny),
            "residual_columns_audited": len(audit),
            "residual_above_threshold": [
                {
                    "column": r["column"],
                    "auroc_vs_manipulated": r["auroc_vs_manipulated"],
                }
                for r in residual_above
            ],
            "top_residual_auroc": [
                {
                    "column": r["column"],
                    "auroc_vs_manipulated": r["auroc_vs_manipulated"],
                }
                for r in audit[:5]
            ],
        }
        iterations.append(iteration_record)
        if not residual_above:
            final_audit = audit
            break
        for r in residual_above:
            col = r["column"]
            deny.add(col)
            reason_map.setdefault(
                col,
                f"residual_auroc>={AUROC_RESIDUAL_THRESHOLD:.2f}_round{round_idx}",
            )
        final_audit = audit
    else:
        # 반복 한도 도달 — 마지막 audit 한 번 더 기록.
        final_audit = _residual_audit(df, y, deny)

    return {
        "deny_list": sorted(deny),
        "deny_reason": reason_map,
        "iterations": iterations,
        "final_residual_audit": final_audit,
    }


def _build_audit_json(
    df: pd.DataFrame,
    y: np.ndarray,
    s0_payload: dict,
    audit_result: dict,
) -> dict:
    """JSON 산출 — deny-list, 각 컬럼 AUROC, iteration trace, 잔여 컬럼 등."""
    s0_auroc_map = {
        entry["column"]: entry.get("auroc_vs_manipulated") for entry in s0_payload["columns"]
    }
    deny_detail = []
    for col in audit_result["deny_list"]:
        deny_detail.append(
            {
                "column": col,
                "s0_auroc": s0_auroc_map.get(col),
                "reason": audit_result["deny_reason"].get(col, "unknown"),
            }
        )

    residual_top = [
        r for r in audit_result["final_residual_audit"] if r["auroc_vs_manipulated"] is not None
    ][:25]

    return {
        "dataset": s0_payload["dataset"],
        "truth_path": s0_payload["truth_path"],
        "n_rows": s0_payload["n_rows"],
        "n_columns_total": s0_payload["n_columns"],
        "manipulated_row_count": s0_payload["manipulated_row_count"],
        "manipulated_row_prevalence": s0_payload["manipulated_row_prevalence"],
        "policy": {
            "initial_auroc_leak_threshold": AUROC_LEAK_THRESHOLD,
            "residual_auroc_threshold": AUROC_RESIDUAL_THRESHOLD,
            "max_iterations": MAX_ITERATIONS,
            "explicit_user_denylist": sorted(EXPLICIT_DENY_LIST),
            "target_label_columns_excluded_from_features": sorted(TARGET_LABEL_COLUMNS),
        },
        "deny_list_final": audit_result["deny_list"],
        "deny_list_size": len(audit_result["deny_list"]),
        "deny_list_detail": deny_detail,
        "iterations": audit_result["iterations"],
        "final_residual_top_auroc": residual_top,
    }


def _enforcement_plan_markdown(
    audit_payload: dict,
) -> str:
    deny_list = audit_payload["deny_list_final"]
    iterations = audit_payload["iterations"]
    residual = audit_payload["final_residual_top_auroc"]

    lines: list[str] = []
    lines.append("# Stage 1 — Label Leakage Deny-list Enforcement Plan\n")
    lines.append("- dataset: `" + audit_payload["dataset"] + "`")
    lines.append(
        f"- 총 행수: **{audit_payload['n_rows']:,}**, 컬럼수 (Stage 0): **{audit_payload['n_columns_total']}**"
    )
    lines.append(
        f"- manipulated 행: **{audit_payload['manipulated_row_count']:,}** "
        f"({audit_payload['manipulated_row_prevalence'] * 100:.2f}%)"
    )
    lines.append("")
    lines.append("## 정책")
    lines.append("")
    lines.append(
        f"- 초기 deny: 사용자 명시 deny-list ∪ Stage 0 AUROC ≥ "
        f"**{audit_payload['policy']['initial_auroc_leak_threshold']:.2f}**"
    )
    lines.append(
        "- 잔여 검증: X_clean 에서 단일 컬럼 AUROC ≥ "
        f"**{audit_payload['policy']['residual_auroc_threshold']:.2f}** 인 컬럼은 deny 추가"
    )
    lines.append(f"- 반복 한도: **{audit_payload['policy']['max_iterations']} 회**")
    lines.append(
        "- 타겟 라벨 컬럼 (피처 후보 자체에서 제외): "
        + ", ".join(
            f"`{c}`" for c in audit_payload["policy"]["target_label_columns_excluded_from_features"]
        )
    )
    lines.append("")

    lines.append(f"## 최종 deny-list ({len(deny_list)} 컬럼)")
    lines.append("")
    lines.append("| column | s0_auroc | 분류 사유 |")
    lines.append("|---|---:|---|")
    for entry in audit_payload["deny_list_detail"]:
        auroc = entry["s0_auroc"]
        auroc_str = "NA" if auroc is None else f"{auroc:.4f}"
        lines.append(f"| `{entry['column']}` | {auroc_str} | {entry['reason']} |")
    lines.append("")

    lines.append("## 반복 audit")
    lines.append("")
    for it in iterations:
        lines.append(f"### Round {it['round']} — deny size {it['denylist_size_before']}")
        lines.append("")
        lines.append(f"- 잔여 컬럼 수: **{it['residual_columns_audited']}**")
        lines.append(
            f"- AUROC ≥ {audit_payload['policy']['residual_auroc_threshold']:.2f} 잔여: "
            f"**{len(it['residual_above_threshold'])}**"
        )
        if it["residual_above_threshold"]:
            lines.append("")
            lines.append("| column | AUROC |")
            lines.append("|---|---:|")
            for r in it["residual_above_threshold"]:
                auroc = r["auroc_vs_manipulated"]
                lines.append(f"| `{r['column']}` | {auroc:.4f} |")
        lines.append("")
        lines.append("Top 5 잔여 AUROC:")
        lines.append("")
        lines.append("| column | AUROC |")
        lines.append("|---|---:|")
        for r in it["top_residual_auroc"]:
            auroc = r["auroc_vs_manipulated"]
            auroc_str = "NA" if auroc is None else f"{auroc:.4f}"
            lines.append(f"| `{r['column']}` | {auroc_str} |")
        lines.append("")

    lines.append("## 최종 잔여 컬럼 Top AUROC")
    lines.append("")
    lines.append("| column | AUROC |")
    lines.append("|---|---:|")
    for r in residual:
        auroc = r["auroc_vs_manipulated"]
        auroc_str = "NA" if auroc is None else f"{auroc:.4f}"
        lines.append(f"| `{r['column']}` | {auroc_str} |")
    lines.append("")
    lines.append(
        f"잔여 AUROC ≥ {audit_payload['policy']['residual_auroc_threshold']:.2f} 컬럼 수: "
        f"**{sum(1 for r in residual if (r['auroc_vs_manipulated'] or 0) >= AUROC_RESIDUAL_THRESHOLD)}**"
    )
    lines.append("")

    # ── Enforce 위치 제안
    lines.append("## Enforce 위치 제안 (src/preprocessing/)")
    lines.append("")
    lines.append(
        "현재 라벨 컬럼 deny 는 `src/preprocessing/constants.py:LABEL_COLUMNS` 에 정의되어 있고,"
        " `src/preprocessing/feature_quality.py::_drop_label_columns` 가 학습/추론 양측에서 호출한다."
        " Stage 1 누수 컬럼은 라벨 컬럼과 분리된 *데이터 사이드카* 이므로 별도 상수로 관리하고"
        " 같은 drop 경로를 통해 일괄 제거한다."
    )
    lines.append("")

    lines.append("### Patch 1 — `src/preprocessing/constants.py`")
    lines.append("")
    lines.append(
        "- LABEL_COLUMNS 는 그대로 유지하고, Stage 1 검증된 deny-list 를 신규 상수로 추가."
    )
    lines.append("")
    lines.append("```diff")
    lines.append("--- a/src/preprocessing/constants.py")
    lines.append("+++ b/src/preprocessing/constants.py")
    lines.append("@@")
    lines.append(" LABEL_COLUMNS = frozenset({")
    lines.append('     "is_fraud",')
    lines.append('     "fraud_type",')
    lines.append('     "is_anomaly",')
    lines.append('     "anomaly_type",')
    lines.append('     "sod_violation",')
    lines.append('     "sod_conflict_type",')
    lines.append('     "label",')
    lines.append('     "target",')
    lines.append(" })")
    lines.append("+")
    lines.append(
        "+# Stage 1 누수 컬럼 deny-list — DataSynth truth sidecar / 식별자 단독 누수 컬럼."
    )
    lines.append(
        "+# Why: Stage 0 AUROC ≥ 0.95 + 명시 mutation_* 메타 + 반복 잔여 audit (AUROC ≥ 0.99)"
    )
    lines.append("+# 으로 확정. 학습/추론 양 경로에서 일괄 제거하여 라벨 누수를 차단한다.")
    lines.append("+LEAKAGE_DENY_COLUMNS = frozenset({")
    for col in deny_list:
        lines.append(f'+    "{col}",')
    lines.append("+})")
    lines.append("```")
    lines.append("")

    lines.append("### Patch 2 — `src/preprocessing/feature_quality.py`")
    lines.append("")
    lines.append(
        "- `_drop_label_columns` 는 LABEL_COLUMNS 만 처리한다."
        " LEAKAGE_DENY_COLUMNS 도 동일 함수에서 일괄 제거하도록 확장."
    )
    lines.append(
        "- `apply_feature_quality_policy` 진입점은 `pipeline_builder.drop_label_columns`,"
        " `prepare_training_features` 양측에서 호출되므로 enforce 가 자동 전파됨."
    )
    lines.append("")
    lines.append("```diff")
    lines.append("--- a/src/preprocessing/feature_quality.py")
    lines.append("+++ b/src/preprocessing/feature_quality.py")
    lines.append("@@")
    lines.append("-from src.preprocessing.constants import LABEL_COLUMNS")
    lines.append("+from src.preprocessing.constants import LABEL_COLUMNS, LEAKAGE_DENY_COLUMNS")
    lines.append("@@")
    lines.append(" def _drop_label_columns(df: pd.DataFrame) -> pd.DataFrame:")
    lines.append("-    cols_to_drop = [col for col in df.columns if col.lower() in LABEL_COLUMNS]")
    lines.append("+    deny = LABEL_COLUMNS | LEAKAGE_DENY_COLUMNS")
    lines.append("+    cols_to_drop = [col for col in df.columns if col.lower() in deny]")
    lines.append("     if not cols_to_drop:")
    lines.append("         return df")
    lines.append('     return df.drop(columns=cols_to_drop, errors="ignore")')
    lines.append("```")
    lines.append("")

    lines.append("### Patch 3 — `src/preprocessing/feature_groups.py` (방어층)")
    lines.append("")
    lines.append(
        "- `classify_features` 의 `_EXCLUDE_NAMES` 는 식별자만 다룬다. 누수 deny-list 도 자동 제외."
    )
    lines.append("")
    lines.append("```diff")
    lines.append("--- a/src/preprocessing/feature_groups.py")
    lines.append("+++ b/src/preprocessing/feature_groups.py")
    lines.append("@@")
    lines.append("-from src.preprocessing.constants import LABEL_COLUMNS")
    lines.append("+from src.preprocessing.constants import LABEL_COLUMNS, LEAKAGE_DENY_COLUMNS")
    lines.append("@@")
    lines.append("-        if col_name.lower() in _EXCLUDE_NAMES | LABEL_COLUMNS:")
    lines.append(
        "+        if col_name.lower() in _EXCLUDE_NAMES | LABEL_COLUMNS | LEAKAGE_DENY_COLUMNS:"
    )
    lines.append('             _assign_to_group(groups, col_name, "excluded")')
    lines.append("             continue")
    lines.append("```")
    lines.append("")

    lines.append("### Patch 4 — 회귀 테스트")
    lines.append("")
    lines.append(
        "- `tests/preprocessing/test_feature_quality.py` (또는 동등 위치) 에 deny-list enforce"
        " 검증 케이스를 추가: deny 컬럼이 포함된 df → `apply_feature_quality_policy` 후 모두 제거되는지 확인."
    )
    lines.append("")
    lines.append("```python")
    lines.append("def test_leakage_deny_columns_dropped() -> None:")
    lines.append("    from src.preprocessing.constants import LEAKAGE_DENY_COLUMNS")
    lines.append("    from src.preprocessing.feature_quality import apply_feature_quality_policy")
    lines.append("")
    lines.append("    df = pd.DataFrame({col: [1] for col in LEAKAGE_DENY_COLUMNS})")
    lines.append("    df['debit_amount'] = [100]")
    lines.append("    cleaned, _, _ = apply_feature_quality_policy(df, None, for_training=False)")
    lines.append("    assert set(cleaned.columns).isdisjoint(LEAKAGE_DENY_COLUMNS)")
    lines.append("    assert 'debit_amount' in cleaned.columns")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    if not S0_JSON.exists():
        raise FileNotFoundError(f"Stage 0 catalog not found: {S0_JSON}")
    s0_payload = json.loads(S0_JSON.read_text(encoding="utf-8"))

    con = duckdb.connect()
    je = con.execute(f"SELECT * FROM read_csv_auto('{JE_PATH.as_posix()}')").df()
    truth = con.execute(f"SELECT document_id FROM read_csv_auto('{TRUTH_PATH.as_posix()}')").df()
    manipulated_docs = set(truth["document_id"].unique())
    y = je["document_id"].isin(manipulated_docs).astype(int).to_numpy()
    print(f"[info] rows={len(je)} manipulated_rows={int(y.sum())} prevalence={y.mean():.4f}")

    initial_deny, initial_reason = _build_initial_deny_list(s0_payload)
    print(f"[info] initial deny-list size = {len(initial_deny)}")

    audit_result = _iterate_until_clean(je, y, initial_deny, initial_reason)
    print(f"[info] final deny-list size = {len(audit_result['deny_list'])}")
    for it in audit_result["iterations"]:
        print(
            f"[info] round {it['round']}: deny_before={it['denylist_size_before']},"
            f" residual_above_threshold={len(it['residual_above_threshold'])}"
        )

    audit_payload = _build_audit_json(je, y, s0_payload, audit_result)

    out_json = OUT_DIR / "S1_leakage_columns_audit.json"
    out_json.write_text(
        json.dumps(audit_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[ok] wrote {out_json}")

    plan_md = _enforcement_plan_markdown(audit_payload)
    out_md = OUT_DIR / "S1_leakage_enforcement_plan.md"
    out_md.write_text(plan_md, encoding="utf-8")
    print(f"[ok] wrote {out_md}")


if __name__ == "__main__":
    main()
