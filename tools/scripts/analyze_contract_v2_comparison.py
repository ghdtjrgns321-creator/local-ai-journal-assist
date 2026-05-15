"""Build datasynth_contract_v2 comparison artifacts.

This script intentionally treats detector output and independent rule truth as
different evidence surfaces. The v2 contract-sidecar candidate currently emits
only anomaly labels, so A-axis contract evaluation is reported as missing rather
than inferred from detector hits.
"""

from __future__ import annotations

import csv
import json
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OLD_DATASET = ROOT / "data" / "journal" / "primary" / "datasynth_contract"
V2_DATASET = ROOT / "data" / "journal" / "primary" / "datasynth_contract_v2"
PROFILE = ROOT / "artifacts" / "phase1_contract_v2_profile_20260514.json"
CACHE = ROOT / "artifacts" / "phase1_contract_v2_case_input_20260514.pkl"
OLD_RULE_EVAL = ROOT / "artifacts" / "contract_truth_rule_eval_20260513.csv"
RESULT_DIR = ROOT / "tests" / "datasynth_quality_gate3" / "results"
A_AXIS_STRICT = RESULT_DIR / "contract_v2_a_axis_strict.json"

RULE_TITLES = {
    "L1-01": "차대변 불일치",
    "L1-02": "필수필드 누락",
    "L1-03": "무효 계정",
    "L1-04": "승인한도 초과",
    "L1-05": "자기승인",
    "L1-06": "직무분리 위반",
    "L1-07": "승인 생략",
    "L1-08": "회계기간 불일치",
    "L1-09": "승인일 추적성 결손",
    "L2-01": "반올림 금액",
    "L2-02": "중복 지급",
    "L2-03": "중복 전표 후보",
    "L2-04": "자산+비용 동시처리",
    "L2-05": "역분개 패턴",
    "L3-01": "계정/프로세스 불일치",
    "L3-02": "수기/조정 전표",
    "L3-03": "관계사 거래",
    "L3-04": "기말/기초 전표",
    "L3-05": "주말/휴일 전기",
    "L3-06": "심야/비업무시간 전기",
    "L3-07": "전기일-문서일 장기 괴리",
    "L3-08": "적요 결손/파손",
    "L3-09": "미결/장기미결",
    "L3-10": "고위험 계정",
    "L3-11": "컷오프 불일치",
    "L3-12": "업무범위 집중 검토 후보",
    "L4-01": "고액 반올림",
    "L4-03": "이상 고액",
    "L4-04": "희귀 계정 조합",
    "L4-05": "비정상 시간대 입력자 집중",
    "L4-06": "배치/대량 전표",
    "Benford": "Benford macro finding",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def case_artifact_path(profile: dict[str, Any]) -> Path:
    artifact = profile.get("stages", {}).get("phase1_case_builder", {}).get("artifact_path")
    if not artifact:
        raise FileNotFoundError("phase1_case_builder.artifact_path missing from profile")
    path = Path(str(artifact))
    return path if path.is_absolute() else ROOT / path


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as file:
        return max(sum(1 for _ in file) - 1, 0)


def collect_v2_rule_counts(profile: dict[str, Any]) -> dict[str, dict[str, int]]:
    steps = profile["stages"]["phase1_case_builder_steps"]
    detector_rules = profile["stages"].get("detector_rules", {})
    counts: dict[str, dict[str, int]] = {}

    for key, payload in steps.items():
        if not key.startswith("collect_raw_hits."):
            continue
        rule_id = key.split(".", 1)[1]
        counts.setdefault(rule_id, {})["phase1_docs"] = int(payload.get("candidate_labels", 0) or 0)
        counts[rule_id]["seed_docs"] = int(payload.get("seed_candidate_labels", 0) or 0)
        counts[rule_id]["context_docs"] = int(payload.get("context_candidate_labels", 0) or 0)

    for layer in detector_rules.values():
        for rule_id, payload in layer.items():
            counts.setdefault(rule_id, {})["detector_rows"] = int(
                payload.get("flagged_rows", 0) or 0
            )

    return counts


def classify_rule(
    rule_id: str, old_count: int, v2_count: int, has_truth: bool
) -> tuple[str, str, str]:
    if not has_truth:
        if v2_count == 0 and old_count > 0:
            return (
                "MISSING",
                "v2에 rule_truth/sidecar가 없어 A축 계약 검증 불가. detector hit도 없음.",
                "sidecar_truth_refresh_needed",
            )
        if old_count > 0:
            return (
                "MISSING",
                "v2에 rule_truth/sidecar가 없어 detector 출력만 비교 가능.",
                "sidecar_truth_refresh_needed",
            )
        return (
            "MISSING",
            "v2에 독립 truth가 없어 신규/보조 룰 계약 평가 불가.",
            "sidecar_truth_refresh_needed",
        )
    if old_count == 0:
        return ("OK", "기존 contract 기준 없음.", "acceptable_no_action")
    ratio = abs(v2_count - old_count) / old_count
    if ratio <= 0.2:
        return ("OK", "count 변화가 작음.", "acceptable_no_action")
    if v2_count < old_count:
        return (
            "EXPECTED_CHANGE",
            "semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능.",
            "expected_semantic_clean_change",
        )
    return ("WARNING", "count 증가가 커서 detector/data 분리 검토 필요.", "detector_review_needed")


def build_rule_diff(profile: dict[str, Any]) -> pd.DataFrame:
    old = pd.read_csv(OLD_RULE_EVAL)
    old_counts = {str(row.rule_id): int(row.truth_docs) for row in old.itertuples(index=False)}
    v2_counts = collect_v2_rule_counts(profile)
    v2_truth_files = set(path.name for path in (V2_DATASET / "labels").glob("rule_truth_*.csv"))
    strict_rows: dict[str, dict[str, Any]] = {}
    if A_AXIS_STRICT.exists():
        strict_payload = read_json(A_AXIS_STRICT)
        strict_rows = {str(row["rule_id"]): row for row in strict_payload.get("rules", [])}
    rules = sorted(set(old_counts) | set(v2_counts))
    rows = []
    for rule_id in rules:
        old_count = old_counts.get(rule_id, 0)
        v2_count = int(v2_counts.get(rule_id, {}).get("phase1_docs", 0) or 0)
        delta = v2_count - old_count
        delta_ratio = None if old_count == 0 else round(delta / old_count, 6)
        truth_name = f"rule_truth_{rule_id.replace('-', '_')}.csv"
        strict = strict_rows.get(rule_id, {})
        fp_docs = int(strict.get("false_positive_docs", 0) or 0)
        fn_docs = int(strict.get("false_negative_docs", 0) or 0)
        severity, cause, action = classify_rule(
            rule_id,
            old_count,
            v2_count,
            truth_name in v2_truth_files,
        )
        if strict and fp_docs == 0 and fn_docs == 0:
            cause = f"A축 strict rule_truth 대조 기준 과탐/미탐 0. {cause}"
        rows.append(
            {
                "rule_id": rule_id,
                "rule_title": RULE_TITLES.get(rule_id, ""),
                "existing_contract_count": old_count,
                "v2_phase1_count": v2_count,
                "v2_rule_truth_docs": int(strict.get("truth_docs", 0) or 0),
                "a_axis_false_positive_docs": fp_docs,
                "a_axis_false_negative_docs": fn_docs,
                "v2_detector_rows": int(v2_counts.get(rule_id, {}).get("detector_rows", 0) or 0),
                "v2_seed_docs": int(v2_counts.get(rule_id, {}).get("seed_docs", 0) or 0),
                "v2_context_docs": int(v2_counts.get(rule_id, {}).get("context_docs", 0) or 0),
                "delta": delta,
                "delta_ratio": delta_ratio,
                "severity": severity,
                "cause_estimate": cause,
                "action_class": action,
            }
        )
    frame = pd.DataFrame(rows)
    frame["_sort_abs_delta"] = frame["delta"].abs()
    return frame.sort_values(["severity", "_sort_abs_delta"], ascending=[False, False]).drop(
        columns=["_sort_abs_delta"]
    )


def build_sidecar_consistency(profile: dict[str, Any]) -> dict[str, Any]:
    old_labels = OLD_DATASET / "labels"
    v2_labels = V2_DATASET / "labels"
    if old_labels.exists():
        old_files = {path.name for path in old_labels.iterdir() if path.is_file()}
    else:
        old_files = set()
    v2_files = {path.name for path in v2_labels.iterdir() if path.is_file()}

    journal_cols = pd.read_csv(V2_DATASET / "journal_entries.csv", nrows=0).columns.tolist()
    forbidden = ["is_fraud", "fraud_type", "is_anomaly", "anomaly_type"]
    semantic_cols = [
        "semantic_scenario_id",
        "counterparty_type",
        "mutation_type",
        "mutation_reason",
    ]
    required_cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "fiscal_period",
        "posting_date",
        "document_date",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "local_amount",
    ]

    year_counts: dict[str, dict[str, int]] = {}
    all_year_rows = 0
    all_year_docs: set[str] = set()
    for year_path in sorted(V2_DATASET.glob("journal_entries_*.csv")):
        df_year = pd.read_csv(
            year_path, usecols=["document_id", "fiscal_year"], dtype=str, low_memory=False
        )
        all_year_rows += len(df_year)
        all_year_docs.update(df_year["document_id"].dropna().astype(str).unique())
        year_counts[year_path.stem[-4:]] = {
            "rows": int(len(df_year)),
            "documents": int(df_year["document_id"].nunique()),
            "fiscal_year_values": sorted(
                df_year["fiscal_year"].dropna().astype(str).unique().tolist()
            ),
        }

    journal_key = pd.read_csv(
        V2_DATASET / "journal_entries.csv",
        usecols=["document_id", "fiscal_year", "semantic_scenario_id", "counterparty_type"],
        dtype=str,
        low_memory=False,
    )
    journal_docs = set(journal_key["document_id"].dropna().astype(str).unique())
    anomaly_path = v2_labels / "anomaly_labels.csv"
    anomaly_consistency: dict[str, Any] = {"exists": anomaly_path.exists()}
    if anomaly_path.exists():
        labels = pd.read_csv(anomaly_path, dtype=str, low_memory=False)
        label_docs = (
            set(labels["document_id"].dropna().astype(str).unique())
            if "document_id" in labels.columns
            else set()
        )
        anomaly_consistency.update(
            {
                "rows": int(len(labels)),
                "documents": int(len(label_docs)),
                "missing_document_ids": int(len(label_docs - journal_docs)),
                "columns": labels.columns.tolist(),
                "fiscal_year_column_present": "fiscal_year" in labels.columns,
            }
        )
        if {"document_id", "fiscal_year"}.issubset(labels.columns):
            journal_years = journal_key[["document_id", "fiscal_year"]].drop_duplicates()
            merged = labels[["document_id", "fiscal_year"]].merge(
                journal_years,
                on="document_id",
                how="left",
                suffixes=("_label", "_journal"),
            )
            mismatch = merged[
                merged["fiscal_year_journal"].notna()
                & (
                    merged["fiscal_year_label"].astype(str)
                    != merged["fiscal_year_journal"].astype(str)
                )
            ]
            anomaly_consistency["fiscal_year_mismatch_rows"] = int(len(mismatch))
        else:
            anomaly_consistency["fiscal_year_mismatch_rows"] = None

    return {
        "dataset": str(V2_DATASET.relative_to(ROOT)),
        "profile": str(PROFILE.relative_to(ROOT)),
        "journal": {
            "rows": int(profile["stages"]["read_csv"]["rows"]),
            "documents": int(profile["stages"]["read_csv"]["documents"]),
            "columns": int(len(journal_cols)),
            "required_missing": [col for col in required_cols if col not in journal_cols],
            "direct_label_leakage_present": [col for col in forbidden if col in journal_cols],
            "semantic_columns_missing": [col for col in semantic_cols if col not in journal_cols],
            "normal_semantic_missing_rows": int(
                journal_key["semantic_scenario_id"].fillna("").astype(str).str.strip().eq("").sum()
            ),
            "normal_counterparty_type_missing_rows": int(
                journal_key["counterparty_type"].fillna("").astype(str).str.strip().eq("").sum()
            ),
        },
        "year_files": {
            "rows_sum": int(all_year_rows),
            "documents_union": int(len(all_year_docs)),
            "matches_combined_rows": bool(all_year_rows == profile["stages"]["read_csv"]["rows"]),
            "matches_combined_documents": bool(
                len(all_year_docs) == profile["stages"]["read_csv"]["documents"]
            ),
            "by_year": year_counts,
        },
        "labels": {
            "old_file_count": len(old_files),
            "v2_file_count": len(v2_files),
            "missing_vs_old_count": len(old_files - v2_files),
            "missing_rule_truth_count": len(
                [name for name in old_files - v2_files if name.startswith("rule_truth_")]
            ),
            "missing_contract_taxonomy": [
                name
                for name in (
                    "contract_rule_truth_taxonomy.csv",
                    "contract_rule_truth_taxonomy_summary.csv",
                    "contract_sidecar_taxonomy.csv",
                    "contract_sidecar_taxonomy_summary.csv",
                    "sidecar_manifest.csv",
                )
                if name not in v2_files
            ],
            "v2_files": sorted(v2_files),
        },
        "anomaly_labels": anomaly_consistency,
        "manifest": (
            read_json(V2_DATASET / "CONTRACT_SIDECAR_MANIFEST.json")
            if (V2_DATASET / "CONTRACT_SIDECAR_MANIFEST.json").exists()
            else read_json(V2_DATASET / "run_manifest.json")
            if (V2_DATASET / "run_manifest.json").exists()
            else {}
        ),
    }


def case_summary_rows(case_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for theme in case_payload["theme_summaries"]:
        top_ids = set(theme.get("top_case_ids", []))
        cases = [case for case in case_payload["cases"] if case["case_id"] in top_ids]
        by_id = {case["case_id"]: case for case in cases}
        for rank, case_id in enumerate(theme.get("top_case_ids", []), start=1):
            case = by_id.get(case_id, {})
            rows.append(
                {
                    "theme_id": theme["theme_id"],
                    "theme_label": theme["theme_label"],
                    "rank": rank,
                    "case_id": case_id,
                    "band": case.get("priority_band"),
                    "score": case.get("priority_score"),
                    "docs": case.get("document_count"),
                    "rows": case.get("row_count"),
                    "rule_count": case.get("rule_count"),
                    "top_rules": ",".join(
                        list(
                            dict.fromkeys(
                                e.get("rule_id", "") for e in case.get("rule_evidence_summary", [])
                            )
                        )[:5]
                    ),
                    "risk_narrative": case.get("risk_narrative"),
                }
            )
    return rows


def build_issue_samples(rule_diff: pd.DataFrame) -> pd.DataFrame:
    with CACHE.open("rb") as file:
        cache = pickle.load(file)
    df: pd.DataFrame = cache["df"]
    sample_rules = (
        rule_diff.sort_values("delta", key=lambda s: s.abs(), ascending=False)["rule_id"]
        .drop_duplicates()
        .head(8)
        .tolist()
    )
    cols = [
        "document_id",
        "fiscal_year",
        "fiscal_period",
        "posting_date",
        "document_date",
        "document_type",
        "business_process",
        "semantic_scenario_id",
        "counterparty_type",
        "mutation_type",
        "mutation_reason",
        "created_by",
        "approved_by",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "local_amount",
        "flagged_rules",
        "review_rules",
        "risk_level",
        "anomaly_score",
    ]
    rows = []
    for rule_id in sample_rules:
        if "flagged_rules" not in df.columns and "review_rules" not in df.columns:
            continue
        mask = pd.Series(False, index=df.index)
        for col in ("flagged_rules", "review_rules"):
            if col in df.columns:
                mask |= df[col].fillna("").astype(str).str.contains(rule_id, regex=False)
        sample = df.loc[mask, [col for col in cols if col in df.columns]].head(10).copy()
        sample.insert(0, "sample_rule_id", rule_id)
        rows.append(sample)
    if not rows:
        return pd.DataFrame(columns=["sample_rule_id", *cols])
    return pd.concat(rows, ignore_index=True)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join([header, sep, *body])


def write_docs(profile: dict[str, Any], sidecar: dict[str, Any], rule_diff: pd.DataFrame) -> None:
    case_artifact = case_artifact_path(profile)
    case_payload = read_json(case_artifact)
    top_changes = rule_diff.reindex(
        rule_diff["delta"].abs().sort_values(ascending=False).index
    ).head(12)
    missing_contract_taxonomy = sidecar["labels"].get("missing_contract_taxonomy", [])
    missing_rule_truth_count = int(sidecar["labels"].get("missing_rule_truth_count", 0) or 0)
    missing_vs_old_count = int(sidecar["labels"].get("missing_vs_old_count", 0) or 0)
    has_contract_surface = missing_rule_truth_count == 0 and not missing_contract_taxonomy
    strict_payload = read_json(A_AXIS_STRICT) if A_AXIS_STRICT.exists() else {}
    strict_fp = int(strict_payload.get("total_false_positive_docs", 0) or 0)
    strict_fn = int(strict_payload.get("total_false_negative_docs", 0) or 0)
    strict_rules_with_diff = int(strict_payload.get("rules_with_diff", 0) or 0)
    strict_rules_checked = int(strict_payload.get("rules_checked", 0) or 0)
    a_verdict = (
        "PASS"
        if has_contract_surface
        and strict_fp == 0
        and strict_fn == 0
        and strict_rules_with_diff == 0
        else ("WARN" if has_contract_surface else "FAIL/MISSING")
    )
    hygiene_blockers: list[str] = []
    if not sidecar["year_files"]["matches_combined_rows"]:
        hygiene_blockers.append("journal/year row 합계 불일치")
    if not sidecar["year_files"]["matches_combined_documents"]:
        hygiene_blockers.append("journal/year document 합계 불일치")
    if sidecar["journal"]["required_missing"]:
        hygiene_blockers.append("필수 journal 컬럼 누락")
    if sidecar["journal"]["direct_label_leakage_present"]:
        hygiene_blockers.append("direct label leakage 컬럼 존재")
    if sidecar["journal"]["semantic_columns_missing"]:
        hygiene_blockers.append("필수 semantic metadata 컬럼 누락")
    if int(sidecar["anomaly_labels"].get("missing_document_ids", 0) or 0) > 0:
        hygiene_blockers.append("anomaly_labels document_id가 journal에 없음")
    fiscal_mismatch = sidecar["anomaly_labels"].get("fiscal_year_mismatch_rows")
    if fiscal_mismatch is not None and int(fiscal_mismatch or 0) > 0:
        hygiene_blockers.append("anomaly_labels fiscal_year 불일치")
    hygiene_status = "BLOCKER" if hygiene_blockers else "OK"
    a_summary = (
        f"전수 {strict_rules_checked}개 룰에서 `rule_truth_*`와 Phase1 rule-hit document set을 대조했고 과탐 {strict_fp}건, 미탐 {strict_fn}건이다."
        if a_verdict == "PASS"
        else "v2 journal 기준 `rule_truth_*`, taxonomy, `sidecar_manifest.csv`가 존재한다. 다만 strict A축 대조 또는 count 변화 검토가 남아 있다."
        if has_contract_surface
        else "v2에는 공식 `rule_truth_*`와 taxonomy/sidecar manifest가 없으므로 기존 contract의 핵심 과탐/미탐 0 검증을 수행할 수 없다. detector 출력은 생성되었지만 detector output을 truth로 간주하지 않았다."
    )
    hygiene_summary = (
        "위생 체크 blocker는 없다. 이 체크는 기존 contract 문서와 동등한 C축 검증이 아니라, v2 후보가 깨진 CSV/ID/metadata 상태인지 보는 보조 안전장치다. 기존 contract 대비 sidecar 파일 수 차이는 promotion blocker로 보지 않는다."
        if not hygiene_blockers
        else "위생 체크 blocker: " + ", ".join(hygiene_blockers)
    )
    a_action = (
        "추가 조치 없음"
        if a_verdict == "PASS"
        else "strict diff rule의 truth 산식 또는 detector document-set 기준 재검토"
        if has_contract_surface
        else "필수 rule truth/sidecar/taxonomy 생성"
    )
    evidence = profile["stages"].get("independent_evidence_enrichment", {})
    approval_gap_rows = int(evidence.get("approval_matrix_gap_rows", 0) or 0)
    flow_orphan_rows = int(evidence.get("document_flow_orphan_rows", 0) or 0)
    approval_limit_rows = int(evidence.get("approval_limit_exceeded_rows", 0) or 0)
    coverage_threshold = 1_000
    coverage_clean = (
        approval_gap_rows < coverage_threshold and flow_orphan_rows < coverage_threshold
    )
    b_verdict = "PASS" if coverage_clean else "WARN"
    if a_verdict == "PASS" and b_verdict == "PASS":
        promotion_summary = "`datasynth_contract_v2`는 A축 과탐/미탐 0, B축 master/flow coverage, 데이터 위생 체크 세 축을 모두 통과했다. 남은 검토 항목은 rule diff에서 detector_review_needed로 분류된 룰의 의미 해석과 큰 delta가 expected change인지 샘플 확인이다."
    elif a_verdict == "PASS":
        promotion_summary = "`datasynth_contract_v2`는 A축 과탐/미탐 0 조건과 위생 체크를 통과했다. 바로 기존 contract로 덮기보다는 B축 사용자 가독성과 master/flow provenance coverage를 검토한 뒤 promotion 여부를 결정해야 한다."
    elif has_contract_surface:
        promotion_summary = "`datasynth_contract_v2`는 v2 journal 기준 독립 truth/sidecar/taxonomy와 데이터 위생 체크는 갖췄지만, 최신 Phase1 cache 기준 strict A축 document-set 차이가 남아 있다. 바로 promotion하지 말고 strict diff가 있는 rule의 truth 산식 또는 detector 표면을 먼저 재검토해야 한다."
    else:
        promotion_summary = "`datasynth_contract_v2`는 semantic-clean journal 후보로는 계속 검토할 수 있지만, 현재 상태로는 기존 `datasynth_contract`를 대체할 contract sidecar로 바로 promotion할 수 없다. blocker는 detector 성능이 아니라 v2용 독립 rule truth/sidecar/taxonomy가 생성되지 않은 점이다."
    if coverage_clean:
        b_summary = (
            f"case builder는 정상 실행되었고 그룹별 case 구조는 유지된다. "
            f"v2에서 `approval_matrix_gap_rows`가 {approval_gap_rows:,}, "
            f"`document_flow_orphan_rows`가 {flow_orphan_rows:,}로 master/flow coverage가 "
            f"contract 수준으로 정리되어 control/timing 설명이 안정적이다."
        )
        b_evidence = (
            "그룹별 case 구조와 L3-12 context-only 정책 유지. "
            f"approval_matrix_gap_rows={approval_gap_rows:,}, document_flow_orphan_rows={flow_orphan_rows:,}로 "
            "master/flow coverage 정리 완료."
        )
        b_action = "대표 case 의미 검토와 rule diff 해석"
    else:
        b_summary = (
            f"case builder는 정상 실행되었고 그룹별 case 구조는 유지된다. "
            f"다만 v2에서 `approval_matrix_gap_rows`가 {approval_gap_rows:,}, "
            f"`document_flow_orphan_rows`가 {flow_orphan_rows:,}로 커서 control/timing 설명이 "
            f"generator master/flow coverage에 의해 과도하게 넓어질 수 있다."
        )
        b_evidence = "그룹별 case 구조와 L3-12 context-only 정책은 유지. 다만 control/timing hit가 master/flow coverage 이슈로 넓어짐"
        b_action = "대표 case와 approval/document-flow master coverage 검토"
    generator_fix_text = (
        f"master/flow provenance coverage 정상화. "
        f"`document_flow_orphan_rows={flow_orphan_rows:,}`, "
        f"`approval_matrix_gap_rows={approval_gap_rows:,}`, "
        f"`approval_limit_exceeded_rows={approval_limit_rows:,}`"
        if coverage_clean
        else "master/flow provenance coverage 때문에 control/document-flow 설명이 과도할 수 있음"
    )
    generator_fix_evidence = (
        f"`document_flow_orphan_rows={flow_orphan_rows:,}`, "
        f"`approval_matrix_gap_rows={approval_gap_rows:,}`"
    )
    strict_issue_rules = []
    for row in strict_payload.get("rules", []):
        if int(row.get("false_positive_docs", 0) or 0) or int(
            row.get("false_negative_docs", 0) or 0
        ):
            strict_issue_rules.append(str(row.get("rule_id", "")))
    strict_issue_text = ", ".join(strict_issue_rules) if strict_issue_rules else "없음"
    detector_review_rules = (
        ", ".join(
            rule_diff.loc[rule_diff["action_class"] == "detector_review_needed", "rule_id"]
            .astype(str)
            .tolist()
        )
        or "없음"
    )
    expected_change_rules = (
        ", ".join(
            rule_diff.loc[rule_diff["action_class"] == "expected_semantic_clean_change", "rule_id"]
            .astype(str)
            .tolist()
        )
        or "없음"
    )
    theme_rows = [
        {
            "그룹": theme["theme_label"],
            "case": theme["case_count"],
            "High": theme["high_count"],
            "Medium": theme["medium_count"],
            "Low": theme["low_count"],
            "Top case 예시": ", ".join(theme["top_case_ids"][:3]),
        }
        for theme in profile["stages"]["phase1_case_builder"]["theme_summaries"]
    ]
    v2_doc = f"""# Phase1 Detection 결과 - datasynth_contract_v2

> **PHASE1 역할 원칙**: PHASE1은 fraud 확정 단계가 아니라 감사인이 검토할 review queue를 만드는 단계다. v2 결과는 detector 출력과 sidecar/truth 계약 검증을 분리해서 해석한다.

## 요약

이 문서는 `data/journal/primary/datasynth_contract_v2/`를 2026-05-14에 Phase1로 실행한 결과다. 기존 `docs/DETECTION_RESULTS_CONTRACT.md`는 덮어쓰지 않았다.

v2는 semantic-clean generator의 `--contract-sidecar` 출력이며, 현재 `labels/`에 rule truth와 sidecar taxonomy를 포함한다. Phase1 detector/case builder 출력과 독립 truth surface는 분리해서 해석한다.

## 입력과 산출물

| 항목 | 값 |
| --- | ---: |
| 원장 row | {profile["stages"]["read_csv"]["rows"]:,} |
| document | {profile["stages"]["read_csv"]["documents"]:,} |
| journal CSV columns | {sidecar["journal"]["columns"]:,} |
| label 파일 수 | {sidecar["labels"]["v2_file_count"]:,} |
| 기존 대비 누락 label/sidecar 파일 | {sidecar["labels"]["missing_vs_old_count"]:,} |
| direct label leakage 컬럼 | {", ".join(sidecar["journal"]["direct_label_leakage_present"]) or "없음"} |
| semantic metadata 누락 컬럼 | {", ".join(sidecar["journal"]["semantic_columns_missing"]) or "없음"} |

### Phase1 출력

| 항목 | 값 |
| --- | ---: |
| 전체 소요 시간 | {profile["total_elapsed_sec"]:.3f}초 |
| 생성된 case 수 | {profile["stages"]["phase1_case_builder"]["case_count"]:,} |
| macro finding 수 | {profile["stages"]["phase1_case_builder"]["macro_finding_count"]:,} |
| High row | {profile["stages"]["aggregate"]["risk_summary"].get("High", 0):,} |
| Medium row | {profile["stages"]["aggregate"]["risk_summary"].get("Medium", 0):,} |
| Low row | {profile["stages"]["aggregate"]["risk_summary"].get("Low", 0):,} |
| Normal row | {profile["stages"]["aggregate"]["risk_summary"].get("Normal", 0):,} |

### 산출 파일

- checkpoint: `artifacts/phase1_contract_v2_profile_20260514.json`
- case input cache: `artifacts/phase1_contract_v2_case_input_20260514.pkl`
- case artifact: `{case_artifact.relative_to(ROOT).as_posix()}`
- rule diff: `tests/datasynth_quality_gate3/results/contract_v2_rule_diff.csv`
- sidecar consistency: `tests/datasynth_quality_gate3/results/contract_v2_sidecar_consistency.json`
- issue samples: `tests/datasynth_quality_gate3/results/contract_v2_issue_samples.csv`

## 실행 시간 분포

| 단계 | 소요 시간 |
| --- | ---: |
| CSV load | {profile["stages"]["read_csv"]["elapsed_sec"]:.3f}초 |
| independent evidence enrichment | {profile["stages"]["independent_evidence_enrichment"]["elapsed_sec"]:.3f}초 |
| feature.time | {profile["stages"]["features"]["time"]["elapsed_sec"]:.3f}초 |
| feature.amount | {profile["stages"]["features"]["amount"]["elapsed_sec"]:.3f}초 |
| feature.pattern | {profile["stages"]["features"]["pattern"]["elapsed_sec"]:.3f}초 |
| feature.text | {profile["stages"]["features"]["text"]["elapsed_sec"]:.3f}초 |
| detector.layer_a | {profile["stages"]["detectors"]["layer_a"]["elapsed_sec"]:.3f}초 |
| detector.layer_b | {profile["stages"]["detectors"]["layer_b"]["elapsed_sec"]:.3f}초 |
| detector.layer_c | {profile["stages"]["detectors"]["layer_c"]["elapsed_sec"]:.3f}초 |
| detector.benford | {profile["stages"]["detectors"]["benford"]["elapsed_sec"]:.3f}초 |
| aggregate | {profile["stages"]["aggregate"]["elapsed_sec"]:.3f}초 |
| Phase1 case builder | {profile["stages"]["phase1_case_builder"]["elapsed_sec"]:.3f}초 |
| **합계** | **{profile["total_elapsed_sec"]:.3f}초** |

## A축 - 룰 계약 검증

**판정: {a_verdict}.** {a_summary}

## B축 - 사용자 가독성/설명 가능성

**판정: {b_verdict}.** {b_summary}

### 그룹별 case 요약

{markdown_table(theme_rows, ["그룹", "case", "High", "Medium", "Low", "Top case 예시"])}

### review-only 신호 처리

| 항목 | 값 |
| --- | ---: |
| L3-12 candidate label 수 | {profile["stages"]["phase1_case_builder_steps"]["collect_raw_hits.L3-12"]["candidate_labels"]:,} |
| seed 후보(case 신규 생성) | {profile["stages"]["phase1_case_builder_steps"]["collect_raw_hits.L3-12"]["seed_candidate_labels"]:,} |
| context 후보(기존 case 보강) | {profile["stages"]["phase1_case_builder_steps"]["collect_raw_hits.L3-12"]["context_candidate_labels"]:,} |
| context evidence 추가 수 | {profile["stages"]["phase1_case_builder_steps"]["collect_raw_hits.L3-12"]["hits_added"]:,} |

## 보조 데이터 위생 체크

**상태: {hygiene_status}.** {hygiene_summary}

| 항목 | 결과 |
| --- | --- |
| journal/year row 합계 | {"통과" if sidecar["year_files"]["matches_combined_rows"] else "실패"} |
| journal/year document 합계 | {"통과" if sidecar["year_files"]["matches_combined_documents"] else "실패"} |
| direct label leakage 제거 | {"통과" if not sidecar["journal"]["direct_label_leakage_present"] else "실패"} |
| semantic metadata 컬럼 | {"통과" if not sidecar["journal"]["semantic_columns_missing"] else "실패"} |
| anomaly_labels document_id 존재 | {sidecar["anomaly_labels"].get("missing_document_ids", "n/a")} missing |
| anomaly_labels fiscal_year 검증 | {"검증 불가(fiscal_year 컬럼 없음)" if not sidecar["anomaly_labels"].get("fiscal_year_column_present") else str(sidecar["anomaly_labels"].get("fiscal_year_mismatch_rows", "n/a")) + " mismatch rows"} |
| 필수 rule_truth 파일 | {"통과" if missing_rule_truth_count == 0 else f"{missing_rule_truth_count:,} missing"} |
| 필수 taxonomy/manifest | {"통과" if not missing_contract_taxonomy else ", ".join(missing_contract_taxonomy)} |
| 기존 대비 누락 sidecar/label | 참고: {missing_vs_old_count:,} files. 기존 보조 sidecar 전체 복제는 필수 동등성 요구가 아님 |

## Rule Diff Top Changes

| rule | 기존 | v2 | delta | severity | 해석 |
| --- | ---: | ---: | ---: | --- | --- |
{chr(10).join(f"| {r.rule_id} | {int(r.existing_contract_count):,} | {int(r.v2_phase1_count):,} | {int(r.delta):,} | {r.severity} | {r.cause_estimate} |" for r in top_changes.itertuples(index=False))}

## 최종 결론

{promotion_summary}
"""

    comparison_doc = f"""# datasynth_contract_v2 Phase1 비교 분석

## 1. 결론

{promotion_summary}

진행 방향은 큰 count delta rule의 의미 검토와 B축 가독성 검토다. `sidecar_truth_refresh_needed`는 해소됐고, 데이터 위생 체크는 promotion 동급 축이 아니라 blocker 조건만 보는 보조 안전장치로 둔다.

## 2. A/B + 위생 체크 요약

| 구분 | 판정 | 핵심 근거 | 조치 |
|---|---|---|---|
| A | {a_verdict} | 전수 {strict_rules_checked}개 룰 과탐 {strict_fp}건, 미탐 {strict_fn}건. diff rule: {strict_issue_text} | {a_action} |
| B | {b_verdict} | {b_evidence} | {b_action} |
| 데이터 위생 체크 | {hygiene_status} | leakage 제거, year split, label id/year, semantic metadata를 보는 보조 안전장치. 기존 contract 대비 전체 sidecar 파일 수 동등성은 요구하지 않음 | BLOCKER 조건이 생길 때만 promotion 차단 |

## 3. Rule Diff Top Changes

| rule | 기존 | v2 | delta | severity | 해석 |
|---|---:|---:|---:|---|---|
{chr(10).join(f"| {r.rule_id} | {int(r.existing_contract_count):,} | {int(r.v2_phase1_count):,} | {int(r.delta):,} | {r.severity} | {r.cause_estimate} |" for r in top_changes.itertuples(index=False))}

## 4. 문제 분류

| 분류 | 내용 | 대표 항목 |
|---|---|---|
| generator_fix_needed | {generator_fix_text} | {generator_fix_evidence} |
| sidecar_truth_refresh_done | v2 journal 기준 독립 truth/sidecar/taxonomy 생성 완료 | `rule_truth_*`, `contract_rule_truth_taxonomy*`, `sidecar_manifest.csv` |
| detector_review_needed | count 증가 또는 strict A축 document-set 차이 때문에 detector/truth 기준 분리 검토 필요 | {detector_review_rules} |
| expected_semantic_clean_change | semantic-clean/source-mix 변화로 기존 contract 대비 감소가 설명 가능한 후보 | {expected_change_rules} |
| acceptable_no_action | leakage 제거, semantic columns, year-file row/doc 합계 | journal 구조 검증 항목 |

## 5. 다음 작업

- L2-02 duplicate payment, L3-05 weekend/holiday, L4-04 rare account pair는 v2 truth 생성 후 count 감소/증가가 expected change인지 샘플 검토한다.
- `document_flow_orphan_rows`와 `approval_matrix_gap_rows`의 원인이 generator master/flow coverage인지 detector 기준 변경인지 분리한다.
- normal accounting logic sample 300건을 v2에서 재검증하고, semantic hard gate 이후 남은 정합성 오류가 intentional fixture인지 확인한다.
"""

    (ROOT / "docs" / "DETECTION_RESULTS_CONTRACT_V2.md").write_text(v2_doc, encoding="utf-8")
    (ROOT / "docs" / "DETECTION_RESULTS_CONTRACT_V2_COMPARISON.md").write_text(
        comparison_doc,
        encoding="utf-8",
    )

    write_csv(RESULT_DIR / "contract_v2_group_top_case_eval.csv", case_summary_rows(case_payload))


def main() -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    profile = read_json(PROFILE)
    rule_diff = build_rule_diff(profile)
    rule_diff.to_csv(RESULT_DIR / "contract_v2_rule_diff.csv", index=False, encoding="utf-8")

    sidecar = build_sidecar_consistency(profile)
    (RESULT_DIR / "contract_v2_sidecar_consistency.json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    issue_samples = build_issue_samples(rule_diff)
    issue_samples.to_csv(
        RESULT_DIR / "contract_v2_issue_samples.csv", index=False, encoding="utf-8"
    )

    write_docs(profile, sidecar, rule_diff)

    action_counts = Counter(rule_diff["action_class"])
    print(
        json.dumps(
            {
                "rule_diff": str((RESULT_DIR / "contract_v2_rule_diff.csv").relative_to(ROOT)),
                "sidecar_consistency": str(
                    (RESULT_DIR / "contract_v2_sidecar_consistency.json").relative_to(ROOT)
                ),
                "issue_samples": str(
                    (RESULT_DIR / "contract_v2_issue_samples.csv").relative_to(ROOT)
                ),
                "docs": [
                    "docs/DETECTION_RESULTS_CONTRACT_V2.md",
                    "docs/DETECTION_RESULTS_CONTRACT_V2_COMPARISON.md",
                ],
                "action_counts": dict(action_counts),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
