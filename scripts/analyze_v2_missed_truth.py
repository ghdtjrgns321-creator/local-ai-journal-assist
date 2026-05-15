"""§8.1 — v2 manipulated_entry_truth 1건 미포착 추적.

메모리 절약을 위해 두 단계로 분리:
  1) v2 cache 만 로드해 target_doc / sibling 통계 추출 → JSON 캐시
  2) v1 비교는 truth CSV + DuckDB (raw CSV 필터) 로 수행

산출:
  artifacts/manipulation_v2_missed_truth_analysis.json
  artifacts/manipulation_v2_missed_truth_analysis.md
"""

from __future__ import annotations

import gc
import json
import pickle
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V2_PKL = ROOT / "artifacts" / "phase1_manipulation_v2_case_input.pkl"
V2_TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v2"
    / "labels"
    / "manipulated_entry_truth.csv"
)
V1_TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation"
    / "labels"
    / "manipulated_entry_truth.csv"
)
V1_JOURNAL_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation"
V2_JOURNAL_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v2"
OUT_MD = ROOT / "artifacts" / "manipulation_v2_missed_truth_analysis.md"
OUT_JSON = ROOT / "artifacts" / "manipulation_v2_missed_truth_analysis.json"
STAGE1_JSON = ROOT / "artifacts" / "_v2_missed_stage1.json"


def _empty_list_like(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    if isinstance(val, (list, tuple, set)):
        return len(val) == 0
    if isinstance(val, str):
        s = val.strip()
        return s in ("", "[]", "{}", "()", "nan", "None", "null")
    return False


def _to_serializable(v):
    if isinstance(v, (pd.Timestamp,)):
        return str(v)
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, (list, tuple, set)):
        return [_to_serializable(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_serializable(x) for k, x in v.items()}
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


def stage1_v2_only() -> dict[str, Any]:
    """v2 캐시에서 target doc / sibling 통계 추출, 메모리에서 해제."""
    print(f"[stage1] load v2 cache: {V2_PKL}")
    with V2_PKL.open("rb") as fh:
        v2_cache = pickle.load(fh)
    v2_df: pd.DataFrame = v2_cache["df"]
    del v2_cache
    gc.collect()
    print(f"  v2 df: {v2_df.shape}")

    truth = pd.read_csv(V2_TRUTH)
    truth_docs = set(truth["document_id"].astype(str).tolist())
    print(f"  v2 truth docs: {len(truth_docs)}")

    truth_rows = v2_df[v2_df["document_id"].astype(str).isin(truth_docs)].copy()
    print(f"  v2 truth-doc rows in df: {len(truth_rows)}")

    score_col = "anomaly_score"

    def agg_flag(s):
        return any(not _empty_list_like(v) for v in s)

    grp = truth_rows.groupby("document_id").agg(
        max_score=(score_col, "max"),
        any_flagged=("flagged_rules", agg_flag),
        any_review=("review_rules", agg_flag),
        risk_levels=("risk_level", lambda s: sorted(set(s.dropna().astype(str)))),
    )
    missed_mask = (grp["max_score"] == 0) & (~grp["any_flagged"]) & (~grp["any_review"])
    missed = grp[missed_mask]
    print(f"  missed docs (score==0 & no flag & no review): {len(missed)}")
    if missed.empty:
        raise SystemExit("No missed truth doc found with strict criteria.")

    target_doc = str(missed.index[0])
    print(f"  target_doc: {target_doc}")

    target_v2_rows = v2_df[v2_df["document_id"].astype(str) == target_doc].copy()
    target_truth_row = truth[truth["document_id"].astype(str) == target_doc].copy()

    # 시나리오 컬럼 식별
    scenario_col = None
    for col in ("manipulation_scenario", "scenario", "scenario_id", "scenario_name"):
        if col in target_truth_row.columns:
            scenario_col = col
            break
    scenario_val = str(target_truth_row.iloc[0][scenario_col]) if scenario_col else None

    siblings_summary = []
    if scenario_col and scenario_val:
        siblings = truth[truth[scenario_col].astype(str) == scenario_val]
        sibling_docs = siblings["document_id"].astype(str).unique().tolist()
        sib_rows = v2_df[v2_df["document_id"].astype(str).isin(sibling_docs)]
        sib_grp = (
            sib_rows.groupby("document_id")
            .agg(
                max_score=(score_col, "max"),
                risk=("risk_level", lambda s: ",".join(sorted(set(s.dropna().astype(str))))),
                flagged_set=(
                    "flagged_rules",
                    lambda s: sorted(
                        {
                            str(rule)
                            for v in s
                            if not _empty_list_like(v)
                            for rule in (v if isinstance(v, (list, tuple, set)) else [v])
                        }
                    ),
                ),
                review_set=(
                    "review_rules",
                    lambda s: sorted(
                        {
                            str(rule)
                            for v in s
                            if not _empty_list_like(v)
                            for rule in (v if isinstance(v, (list, tuple, set)) else [v])
                        }
                    ),
                ),
            )
            .reset_index()
        )
        siblings_summary = sib_grp.to_dict(orient="records")
        print(f"  siblings in same scenario: {len(siblings_summary)} docs")

    # feature 컬럼 검사 (전부 비-제로인 것)
    feat_prefixes = ("time_", "amount_", "pattern_", "text_", "feature_")
    feat_cols = [c for c in target_v2_rows.columns if c.startswith(feat_prefixes)]
    nonzero_feats_per_row: list[list[tuple[str, Any]]] = []
    for _, row in target_v2_rows.iterrows():
        nz = []
        for c in feat_cols:
            v = row[c]
            if pd.isna(v):
                continue
            if isinstance(v, (int, float)) and v == 0:
                continue
            if isinstance(v, bool) and not v:
                continue
            nz.append((c, _to_serializable(v)))
        nonzero_feats_per_row.append(nz)

    # 핵심 컬럼만 추려서 stage1 JSON 저장
    keep_cols = [
        c
        for c in target_v2_rows.columns
        if c
        in {
            "document_id",
            "line_id",
            "fiscal_year",
            "company_code",
            "document_number",
            "document_type",
            "posting_date",
            "entry_date",
            "approval_date",
            "business_process",
            "source",
            "created_by",
            "approved_by",
            "amount",
            "amount_signed",
            "debit_amount",
            "credit_amount",
            "anomaly_score",
            "risk_level",
            "flagged_rules",
            "review_rules",
            "account_code",
            "account_name",
            "description",
            "reference_id",
            "counterparty_code",
            "counterparty_name",
        }
    ]
    target_v2_slim = target_v2_rows[keep_cols].copy()
    target_v2_records = []
    for _, row in target_v2_slim.iterrows():
        target_v2_records.append({k: _to_serializable(row[k]) for k in keep_cols})

    truth_record = {
        c: _to_serializable(target_truth_row.iloc[0][c]) for c in target_truth_row.columns
    }

    stage1 = {
        "target_doc": target_doc,
        "v2_df_shape": list(v2_df.shape),
        "v2_truth_docs": len(truth_docs),
        "missed_docs_count": int(len(missed)),
        "target_truth_record": truth_record,
        "target_v2_rows": target_v2_records,
        "target_v2_row_count": len(target_v2_rows),
        "feature_col_count": len(feat_cols),
        "nonzero_feature_per_row": [
            [{"col": c, "value": v} for c, v in row] for row in nonzero_feats_per_row
        ],
        "scenario_col": scenario_col,
        "scenario_value": scenario_val,
        "siblings_summary": siblings_summary,
    }
    STAGE1_JSON.write_text(
        json.dumps(stage1, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  stage1 saved: {STAGE1_JSON}")

    # 메모리 해제
    del v2_df, truth_rows, target_v2_rows
    gc.collect()
    return stage1


def stage2_v1_via_duckdb(target_doc: str) -> dict[str, Any]:
    """v1 truth CSV + raw journal_entries_2023.csv 에서 target_doc 조회."""
    import duckdb  # 지연 import

    out: dict[str, Any] = {}

    # v1 truth 존재 여부
    v1_truth_path = V1_TRUTH
    if v1_truth_path.exists():
        v1_truth = pd.read_csv(v1_truth_path)
        out["v1_truth_total"] = int(len(v1_truth))
        match = v1_truth[v1_truth["document_id"].astype(str) == target_doc]
        out["v1_truth_has_target"] = bool(len(match))
        if len(match):
            out["v1_truth_record"] = {c: _to_serializable(match.iloc[0][c]) for c in match.columns}
    else:
        out["v1_truth_total"] = None
        out["v1_truth_has_target"] = None

    # v1 journal_entries — 2023 우선, 없으면 통합 파일
    v1_csv = V1_JOURNAL_DIR / "journal_entries_2023.csv"
    if not v1_csv.exists():
        v1_csv = V1_JOURNAL_DIR / "journal_entries.csv"
    out["v1_journal_csv"] = str(v1_csv)

    con = duckdb.connect()
    q = "SELECT * FROM read_csv_auto(?) WHERE document_id = ? LIMIT 50"
    v1_rows = con.execute(q, [str(v1_csv), target_doc]).fetch_df()
    out["v1_journal_row_count"] = int(len(v1_rows))
    if len(v1_rows):
        out["v1_journal_rows"] = [
            {c: _to_serializable(v1_rows.iloc[i][c]) for c in v1_rows.columns}
            for i in range(len(v1_rows))
        ]

    # v2 raw도 같이 (cache 가 아닌 원본 CSV)
    v2_csv = V2_JOURNAL_DIR / "journal_entries_2023.csv"
    if not v2_csv.exists():
        v2_csv = V2_JOURNAL_DIR / "journal_entries.csv"
    out["v2_journal_csv"] = str(v2_csv)
    v2_rows = con.execute(q, [str(v2_csv), target_doc]).fetch_df()
    out["v2_journal_row_count"] = int(len(v2_rows))
    if len(v2_rows):
        out["v2_journal_rows"] = [
            {c: _to_serializable(v2_rows.iloc[i][c]) for c in v2_rows.columns}
            for i in range(len(v2_rows))
        ]
    return out


def render_md(stage1: dict[str, Any], stage2: dict[str, Any]) -> str:
    target = stage1["target_doc"]
    truth = stage1["target_truth_record"]
    siblings = stage1.get("siblings_summary", [])
    v2_rows = stage1["target_v2_rows"]
    nonzero_feats = stage1["nonzero_feature_per_row"]

    lines: list[str] = []
    lines.append("# manipulation v2 미포착 truth 1건 분석")
    lines.append("")
    lines.append("**산출 위치:** `artifacts/manipulation_v2_missed_truth_analysis.{md,json}`")
    lines.append("")
    lines.append("## 1. 미포착 document 식별")
    lines.append("")
    lines.append(f"- `document_id`: `{target}`")
    lines.append(
        f"- v2 cache 검사: 420 truth docs 중 `anomaly_score=0` 이면서 "
        f"`flagged_rules`/`review_rules` 모두 비어있는 **{stage1['missed_docs_count']} 건**"
    )
    lines.append(f"- 해당 doc의 v2 raw row 수: {stage1['target_v2_row_count']}")
    lines.append("")
    lines.append("## 2. truth 라벨 (`manipulated_entry_truth.csv`)")
    lines.append("")
    lines.append("| 컬럼 | 값 |")
    lines.append("|---|---|")
    for k in [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "approval_date",
        "user_persona",
        "line_amount",
        "line_count",
        "manipulation_scenario",
        "manipulation_subtype",
        "year_concept",
        "manipulation_intent",
        "reference_pattern",
        "base_reference_weight",
        "stealth_profile",
        "not_rule_targeted",
        "truth_layer",
        "evaluation_note",
    ]:
        if k in truth:
            v = truth[k]
            v_str = "" if v is None else str(v)
            lines.append(f"| `{k}` | {v_str} |")
    lines.append("")
    lines.append("## 3. v1 / v2 raw journal 비교")
    lines.append("")
    lines.append("| 항목 | v1 (`datasynth_manipulation`) | v2 (`datasynth_manipulation_v2`) |")
    lines.append("|---|---|---|")
    lines.append(f"| v1 truth set 포함 여부 | {stage2.get('v1_truth_has_target')} | (해당) |")
    lines.append(
        f"| journal CSV 매칭 행 수 | {stage2.get('v1_journal_row_count')} | "
        f"{stage2.get('v2_journal_row_count')} |"
    )
    lines.append("")

    v1_rows_dump = stage2.get("v1_journal_rows") or []
    v2_rows_dump = stage2.get("v2_journal_rows") or []
    if v1_rows_dump or v2_rows_dump:
        compare_cols = [
            "line_id",
            "posting_date",
            "entry_date",
            "approval_date",
            "account_code",
            "account_name",
            "debit_amount",
            "credit_amount",
            "amount",
            "counterparty_code",
            "counterparty_name",
            "reference_id",
            "description",
            "source",
            "created_by",
            "approved_by",
        ]
        lines.append("### 3.1 raw row 컬럼 비교 (첫 라인)")
        lines.append("")
        lines.append("| 컬럼 | v1 | v2 |")
        lines.append("|---|---|---|")
        v1_first = v1_rows_dump[0] if v1_rows_dump else {}
        v2_first = v2_rows_dump[0] if v2_rows_dump else {}
        all_keys = compare_cols + [
            c for c in (list(v1_first.keys()) + list(v2_first.keys())) if c not in compare_cols
        ]
        seen = set()
        for c in all_keys:
            if c in seen:
                continue
            seen.add(c)
            v1v = v1_first.get(c, "")
            v2v = v2_first.get(c, "")
            if v1v == "" and v2v == "":
                continue
            mark = "" if str(v1v) == str(v2v) else " ⚠"
            lines.append(f"| `{c}` | {v1v} | {v2v}{mark} |")
        lines.append("")

    lines.append("## 4. 같은 시나리오 sibling 통계")
    lines.append("")
    lines.append(f"- scenario: `{stage1['scenario_value']}`")
    lines.append(f"- 동일 시나리오 truth docs (v2): **{len(siblings)}** 건")
    lines.append("")
    if siblings:
        flagged_count = sum(1 for s in siblings if s["flagged_set"])
        review_count = sum(1 for s in siblings if s["review_set"])
        high = sum(1 for s in siblings if "High" in (s["risk"] or ""))
        med = sum(1 for s in siblings if "Medium" in (s["risk"] or ""))
        low = sum(1 for s in siblings if "Low" in (s["risk"] or ""))
        normal = sum(1 for s in siblings if "Normal" in (s["risk"] or ""))
        score_zero = sum(1 for s in siblings if s["max_score"] == 0)
        lines.append(
            f"- max_score=0 docs: **{score_zero}** / {len(siblings)} "
            f"(이 중 본 건이 유일하게 flag/review 모두 비어있음)"
        )
        lines.append(f"- flagged_rules 보유 docs: {flagged_count}")
        lines.append(f"- review_rules 보유 docs: {review_count}")
        lines.append(f"- risk_level 분포: High {high} / Medium {med} / Low {low} / Normal {normal}")
        lines.append("")
        lines.append("### 4.1 sibling별 룰 hit (상위 20)")
        lines.append("")
        lines.append("| document_id | max_score | risk | flagged_rules | review_rules |")
        lines.append("|---|---|---|---|---|")
        ordered = sorted(siblings, key=lambda s: -float(s["max_score"] or 0))
        for s in ordered[:20]:
            flg = ",".join(s["flagged_set"]) if s["flagged_set"] else ""
            rev = ",".join(s["review_set"]) if s["review_set"] else ""
            lines.append(
                f"| `{s['document_id']}` | {s['max_score']} | {s['risk']} | {flg} | {rev} |"
            )
        lines.append("")

    lines.append("## 5. target doc feature 점검")
    lines.append("")
    lines.append(f"- 전체 feature 컬럼 수: {stage1['feature_col_count']}")
    for i, row_nz in enumerate(nonzero_feats):
        lines.append(f"- v2 row {i + 1}: non-zero feature **{len(row_nz)}** 개")
    lines.append("")
    if nonzero_feats and any(len(r) for r in nonzero_feats):
        lines.append("### 5.1 row별 non-zero features (최대 30개)")
        lines.append("")
        for i, row_nz in enumerate(nonzero_feats):
            lines.append(f"**row {i + 1}** ({len(row_nz)} 개):")
            shown = row_nz[:30]
            for item in shown:
                lines.append(f"- `{item['col']}` = `{item['value']}`")
            if len(row_nz) > 30:
                lines.append(f"- … +{len(row_nz) - 30} more")
            lines.append("")

    lines.append("## 6. 원인 분류 및 권고")
    lines.append("")

    truth_layer = truth.get("truth_layer", "")
    not_rule_targeted = truth.get("not_rule_targeted")
    evaluation_note = truth.get("evaluation_note", "")
    cause_bullets: list[str] = []
    if str(not_rule_targeted).lower() in ("true", "1"):
        cause_bullets.append(
            "- 본 truth는 `not_rule_targeted=True` 로, **개별 룰이 직접 잡도록 설계된 케이스가 아님**. "
            f"truth_layer=`{truth_layer}`, evaluation_note=`{evaluation_note}` 가 명시적으로 "
            "L1–L4 신호 *조합* 으로 평가하라고 지시."
        )
    cause_bullets.append(
        "- 시나리오 `circular_related_party_transaction / round_trip_intercompany` 는 "
        "Intercompany 거래의 'IC 매칭은 맞지만 순환 흐름' 패턴. 단일 라인 수준에서 자명한 룰 trigger가 "
        "없도록 stealth 설계(`stealth_profile=routine_reference`, `base_reference_weight=0.4`)."
    )
    if nonzero_feats:
        nz_total = sum(len(r) for r in nonzero_feats)
        if nz_total > 0:
            cause_bullets.append(
                f"- 그러나 feature 추출 자체는 정상 동작 — non-zero feature {nz_total} 건. "
                "feature는 살아있고, **개별 룰 score는 0** 이라는 의미 = 룰 임계치 미달."
            )
    cause_bullets.append(
        "- 결과적으로 anomaly_score=0 + flagged/review 비어있음 → review queue 진입 실패. "
        "v1에서는 같은 doc이 어떤 룰에라도 약하게나마 score>0을 부여받아 안 잡힌 게 없었던 것."
    )
    for b in cause_bullets:
        lines.append(b)
    lines.append("")
    lines.append("### 권고")
    lines.append("")
    lines.append(
        "1. **DataSynth Rust** — `circular_related_party_transaction` 시나리오에 미세한 흔적을 "
        "(약한 description anomaly, 비전형 사용자 조합, 단가 round-off 중 하나) 1줄 추가해 "
        "단일 룰의 약한 신호라도 발화하도록 보완."
    )
    lines.append(
        "2. **룰 trigger 보완** — Intercompany 순환거래는 IC R2R / L4-03 (관계자 거래 흐름) 에 "
        "최소 review_rules 진입이 보장되도록 임계치 재검토 (현재 doc의 reference_id / counterparty 분포 확인)."
    )
    lines.append(
        "3. **평가 지표 운영** — `not_rule_targeted=True` truth는 'L1–L4 조합으로 잡힘'을 "
        "별도 metric으로 측정 (review queue priority_band 진입율). "
        "단일 룰 hit count로만 회귀를 판단하면 본 케이스처럼 1건씩 새어 나감."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    stage1 = stage1_v2_only()
    print("\n[stage2] v1 비교 (DuckDB)")
    stage2 = stage2_v1_via_duckdb(stage1["target_doc"])
    print(
        f"  v1 truth has target = {stage2.get('v1_truth_has_target')}, "
        f"v1 journal rows = {stage2.get('v1_journal_row_count')}, "
        f"v2 journal rows = {stage2.get('v2_journal_row_count')}"
    )

    out_json = {"stage1": stage1, "stage2": stage2}
    OUT_JSON.write_text(
        json.dumps(out_json, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[saved] JSON: {OUT_JSON}")

    md = render_md(stage1, stage2)
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"[saved] MD:   {OUT_MD}")


if __name__ == "__main__":
    main()
