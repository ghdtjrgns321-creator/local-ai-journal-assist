"""Detection E2E 라벨 검증 — DataSynth 탐지 결과 vs anomaly_labels 교차 대조.

독립 실행 스크립트 (pytest 아님). 1M행 처리에 수십 초 소요.
실행: PYTHONPATH=. uv run python tests/phase1_rulebase/test_e2e_label_validation.py
결과: tests/phase1_rulebase/test-results/e2e-label-validation.md
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.settings import get_audit_rules, get_settings
from src.detection.anomaly_layer import AnomalyDetector
from src.detection.base import DetectionResult
from src.detection.benford_detector import BenfordDetector
from src.detection.fraud_layer import FraudLayer
from src.detection.integrity_layer import IntegrityDetector
from src.detection.score_aggregator import aggregate_scores
from src.feature.engine import generate_all_features
from src.metrics import ground_truth_evaluator as gt_eval
from src.metrics.rule_mapping import (
    covered_label_types,
    get_evaluation_note,
    get_truth_basis,
    get_truth_display,
)

# ── 경로 상수 ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_CSV = PROJECT_ROOT / "data/journal/primary/datasynth/journal_entries.csv"
LABELS_CSV = PROJECT_ROOT / "data/journal/primary/datasynth/labels/anomaly_labels.csv"
OUTPUT_DIR = Path(__file__).resolve().parent / "test-results"
OUTPUT_MD = OUTPUT_DIR / "e2e-label-validation.md"


# ── 룰 ↔ 라벨 매핑 ────────────────────────────────────────
# Why: anomaly_labels.csv의 anomaly_type과 탐지 룰 ID 간 1:1 매핑.
#      라벨에만 존재하는 타입(Phase 2/3)은 coverage_only로 분류.

RULE_TO_LABEL: dict[str, list[str]] = {
    "L1-01": ["UnbalancedEntry"],
    "L1-02": ["MissingField"],
    "L1-03": ["InvalidAccount"],
    "L4-01": ["RevenueManipulation"],
    "L2-01": ["JustBelowThreshold"],
    "L1-04": ["ExceededApprovalLimit"],
    "L2-02": ["DuplicatePayment"],
    "L2-03": ["DuplicateEntry", "ExactDuplicateAmount"],
    "L1-05": ["SelfApproval"],
    "L1-06": ["SegregationOfDutiesViolation"],
    "L3-02": ["ManualOverride"],
    "L1-07": ["SkippedApproval"],
    "L3-03": ["CircularIntercompany"],
    "L2-04": ["ImproperCapitalization"],
    "L3-04": ["RushedPeriodEnd"],
    "L3-05": ["WeekendPosting"],
    "L3-06": ["AfterHoursPosting"],
    "L3-07": ["BackdatedEntry", "LatePosting"],
    "L1-08": ["WrongPeriod"],
    "L3-08": ["MissingOrCorruptedDescription"],
    "L4-02": ["BenfordViolation"],
    "L4-03": ["UnusuallyHighAmount", "StatisticalOutlier"],
    "L4-04": ["UnusualAccountPair"],
    "L3-09": [],  # SuspenseAccount — 라벨에 대응 타입 없음
    "L2-05": ["ReversedAmount"],
    "L4-05": ["AbnormalHoursConcentration"],
}

# Why: 룰이 속한 레이어 (details 컬럼에서 조회할 트랙명)
RULE_TO_LAYER: dict[str, str] = {
    "L1-01": "layer_a", "L1-02": "layer_a", "L1-03": "layer_a",
    "L4-01": "layer_b", "L2-01": "layer_b", "L1-04": "layer_b",
    "L2-02": "layer_b", "L2-03": "layer_b", "L1-05": "layer_b",
    "L1-06": "layer_b", "L3-02": "layer_b", "L1-07": "layer_b",
    "L3-03": "layer_b", "L2-04": "layer_b",
    "L3-04": "layer_c", "L3-05": "layer_c", "L3-06": "layer_c",
    "L3-07": "layer_c", "L1-08": "layer_c", "L3-08": "layer_c",
    "L4-02": "benford", "L4-03": "layer_c", "L4-04": "layer_c",
    "L3-09": "layer_c", "L2-05": "layer_c", "L4-05": "layer_c",
}


# ── 파이프라인 단계 ────────────────────────────────────────


def load_data() -> pd.DataFrame:
    """DataSynth CSV 로드 + 날짜 파싱.

    Why: DataSynth가 int64 범위 초과 금액을 생성하면 pandas가
    debit/credit을 object로 추론. dtype 명시로 float64 보장.
    """
    df = pd.read_csv(
        DATA_CSV,
        parse_dates=["posting_date", "document_date"],
        dtype={"debit_amount": float, "credit_amount": float},
        low_memory=False,
    )
    return df


def run_features(df: pd.DataFrame) -> pd.DataFrame:
    """피처 엔진 실행 → 18개 파생변수 추가."""
    settings = get_settings()
    rules = get_audit_rules()
    return generate_all_features(df, settings=settings, rules=rules).data


def run_detection(df: pd.DataFrame) -> dict:
    """L1/L2/L3/L4 + Benford 독립 트랙 탐지 + 점수 집계."""
    results: dict[str, DetectionResult] = {}
    timings: dict[str, float] = {}

    for name, detector_cls in [
        ("layer_a", IntegrityDetector),
        ("layer_b", FraudLayer),
        ("layer_c", AnomalyDetector),
        ("benford", BenfordDetector),
    ]:
        t0 = time.perf_counter()
        results[name] = detector_cls().detect(df)
        timings[name] = time.perf_counter() - t0

    t0 = time.perf_counter()
    agg_df = aggregate_scores(df, list(results.values()))
    timings["aggregator"] = time.perf_counter() - t0

    return {"results": results, "agg_df": agg_df, "timings": timings}


def load_labels() -> pd.DataFrame:
    """anomaly_labels.csv 로드."""
    if not LABELS_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(LABELS_CSV)


# ── 룰별 라벨 교차 대조 ───────────────────────────────────


def per_rule_label_analysis(
    df: pd.DataFrame,
    results: dict[str, DetectionResult],
    agg_df: pd.DataFrame,
    labels: pd.DataFrame,
) -> list[dict]:
    """각 룰별로 flagged 문서 vs 라벨 문서를 대조하여 recall/precision 계산."""
    analysis = []

    for rule_id, label_types in RULE_TO_LABEL.items():
        layer_name = RULE_TO_LAYER[rule_id]
        result = results.get(layer_name)

        # Why: 해당 레이어 결과가 없거나 룰이 details에 없으면 skip 처리
        if result is None or rule_id not in result.details.columns:
            analysis.append({
                "rule_id": rule_id,
                "label_types": label_types,
                "truth_display": get_truth_display(rule_id),
                "truth_basis": get_truth_basis(rule_id),
                "status": "skipped",
                "reason": f"룰 미실행 (레이어: {layer_name})",
                "label_docs": 0,
                "flagged_rows": 0,
                "flagged_docs": 0,
                "tp_docs": 0,
                "fp_docs": 0,
                "fn_docs": 0,
                "recall": 0.0,
                "precision": 0.0,
                "sample_fn": [],
                "sample_fp": [],
            })
            continue

        # Why: details에서 해당 룰 컬럼 > 0인 행 인덱스 추출
        rule_mask = result.details[rule_id].reindex(df.index, fill_value=0.0) > 0
        flagged_rows = int(rule_mask.sum())
        flagged_doc_set = set(df.loc[rule_mask, "document_id"].dropna().unique())

        # Why: 라벨에서 해당 anomaly_type에 매칭되는 문서 추출
        label_doc_set = gt_eval._label_doc_set_for_rule(rule_id, df, labels)

        # Why: TP/FP/FN 계산 (문서 단위)
        tp_docs = flagged_doc_set & label_doc_set
        fp_docs = flagged_doc_set - label_doc_set
        fn_docs = label_doc_set - flagged_doc_set

        tp = len(tp_docs)
        fp = len(fp_docs)
        fn = len(fn_docs)
        label_count = len(label_doc_set)

        recall = tp / label_count if label_count > 0 else None
        precision = tp / (tp + fp) if (tp + fp) > 0 else None

        # Why: 미탐지/오탐 샘플 (최대 5개) — 디버깅용
        sample_fn = sorted(fn_docs)[:5]
        sample_fp = sorted(fp_docs)[:5]

        status = "no_label" if not label_types else "ok"
        analysis.append({
            "rule_id": rule_id,
            "label_types": label_types,
            "truth_display": get_truth_display(rule_id),
            "truth_basis": get_truth_basis(rule_id),
            "status": status,
            "reason": get_evaluation_note(rule_id),
            "label_docs": label_count,
            "flagged_rows": flagged_rows,
            "flagged_docs": len(flagged_doc_set),
            "tp_docs": tp,
            "fp_docs": fp,
            "fn_docs": fn,
            "recall": recall,
            "precision": precision,
            "sample_fn": sample_fn,
            "sample_fp": sample_fp,
        })

    return analysis


def overall_label_analysis(
    df: pd.DataFrame,
    agg_df: pd.DataFrame,
    labels: pd.DataFrame,
) -> dict:
    """전체 anomaly_score > 0 기준 문서 단위 recall/precision."""
    labeled_docs = set(labels["document_id"].dropna().unique())
    labeled_docs.update(gt_eval._label_doc_set_for_rule("L1-01", df, labels))
    labeled_docs.update(gt_eval._label_doc_set_for_rule("L3-02", df, labels))
    labeled_docs.update(gt_eval._label_doc_set_for_rule("L3-03", df, labels))
    flagged_mask = agg_df["anomaly_score"] > 0
    flagged_docs = set(df.loc[flagged_mask, "document_id"].dropna().unique())

    tp = len(labeled_docs & flagged_docs)
    actual = len(labeled_docs)
    detected = len(flagged_docs)

    # Why: 라벨 중 Phase 1 룰에 매핑되는 것만 분리
    phase1_types = covered_label_types()
    p1_mask = labels["anomaly_type"].isin(phase1_types)
    p1_docs = set(labels.loc[p1_mask, "document_id"].dropna().unique())
    p1_docs.update(gt_eval._label_doc_set_for_rule("L1-01", df, labels))
    p1_docs.update(gt_eval._label_doc_set_for_rule("L3-02", df, labels))
    p1_docs.update(gt_eval._label_doc_set_for_rule("L3-03", df, labels))
    p1_tp = len(p1_docs & flagged_docs)

    # Why: Phase 2/3 전용 라벨 (현재 탐지 대상 아님)
    p23_docs = labeled_docs - p1_docs
    p23_tp = len(p23_docs & flagged_docs)

    return {
        "total_labeled": actual,
        "total_flagged_docs": detected,
        "total_tp": tp,
        "total_recall": tp / actual if actual > 0 else 0.0,
        "total_precision": tp / detected if detected > 0 else 0.0,
        "phase1_labeled": len(p1_docs),
        "phase1_tp": p1_tp,
        "phase1_recall": p1_tp / len(p1_docs) if p1_docs else 0.0,
        "phase23_labeled": len(p23_docs),
        "phase23_tp": p23_tp,
        "phase23_recall": p23_tp / len(p23_docs) if p23_docs else 0.0,
    }


def uncovered_label_analysis(labels: pd.DataFrame) -> list[dict]:
    """Phase 1 룰에 매핑되지 않는 라벨 타입 목록."""
    covered_types = covered_label_types()

    all_types = labels["anomaly_type"].value_counts()
    uncovered = []
    for atype, count in all_types.items():
        if atype not in covered_types:
            uncovered.append({"anomaly_type": atype, "count": count})
    return sorted(uncovered, key=lambda x: -x["count"])


# ── 리포트 생성 ────────────────────────────────────────────


def generate_report(
    df: pd.DataFrame,
    det: dict,
    per_rule: list[dict],
    overall: dict,
    uncovered: list[dict],
    total_elapsed: float,
) -> str:
    """MD 리포트 문자열 생성."""
    n = len(df)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    results = det["results"]
    agg_df = det["agg_df"]
    timings = det["timings"]

    md = []
    md.append(f"# Detection E2E 라벨 검증 결과 (DataSynth {n:,d}행)")
    md.append(f"\n> 실행일: {now}  |  소요시간: {total_elapsed:.1f}s")

    # ── §1 전체 요약 ──
    md.append("\n## 1. 전체 요약\n")
    flagged_count = int((agg_df["anomaly_score"] > 0).sum())
    risk_counts = agg_df["risk_level"].value_counts()
    total_rules = sum(len(r.rule_flags) for r in results.values())

    md.append(f"| {'항목':24s} | {'값':>30s} |")
    md.append(f"|:{'-'*24}|{'-'*30}:|")
    md.append(f"| {'입력 행수':24s} | {n:>30,d} |")
    md.append(f"| {'플래그된 행':24s} | {flagged_count:>20,d} ({flagged_count/n*100:.1f}%) |")
    md.append(f"| {'실행된 룰 수':24s} | {total_rules:>30d} |")
    md.append(f"| {'라벨 문서 수 (전체)':24s} | {overall['total_labeled']:>30,d} |")
    md.append(f"| {'라벨 문서 수 (Phase 1)':24s} | {overall['phase1_labeled']:>30,d} |")
    md.append(f"| {'라벨 문서 수 (Phase 2/3)':24s} | {overall['phase23_labeled']:>30,d} |")
    for level in ["High", "Medium", "Low", "Normal"]:
        cnt = int(risk_counts.get(level, 0))
        md.append(f"| {'  ' + level:24s} | {cnt:>20,d} ({cnt/n*100:.1f}%) |")

    # ── §2 전체 recall/precision ──
    md.append("\n## 2. 전체 Recall / Precision (문서 단위)\n")
    md.append(f"| {'구분':24s} | {'라벨':>8s} | {'탐지':>8s} | {'TP':>6s} | {'Recall':>8s} | {'Precision':>10s} |")
    md.append(f"|:{'-'*24}|{'-'*8}:|{'-'*8}:|{'-'*6}:|{'-'*8}:|{'-'*10}:|")
    md.append(
        f"| {'전체 (all labels)':24s} "
        f"| {overall['total_labeled']:>8d} "
        f"| {overall['total_flagged_docs']:>8d} "
        f"| {overall['total_tp']:>6d} "
        f"| {overall['total_recall']:>7.1%} "
        f"| {overall['total_precision']:>9.1%} |"
    )
    md.append(
        f"| {'Phase 1 룰 매핑 라벨':24s} "
        f"| {overall['phase1_labeled']:>8d} "
        f"| {'—':>8s} "
        f"| {overall['phase1_tp']:>6d} "
        f"| {overall['phase1_recall']:>7.1%} "
        f"| {'—':>10s} |"
    )
    md.append(
        f"| {'Phase 2/3 (미구현)':24s} "
        f"| {overall['phase23_labeled']:>8d} "
        f"| {'—':>8s} "
        f"| {overall['phase23_tp']:>6d} "
        f"| {overall['phase23_recall']:>7.1%} "
        f"| {'—':>10s} |"
    )

    # ── §3 룰별 상세 ──
    md.append("\n## 3. 룰별 Recall / Precision\n")
    md.append(
        f"| {'룰':5s} | {'라벨타입':28s} | {'라벨':>5s} | {'탐지행':>8s} | {'탐지문서':>6s} "
        f"| {'TP':>4s} | {'FP':>5s} | {'FN':>4s} | {'Recall':>7s} | {'Prec':>6s} |"
    )
    md.append(
        f"|:{'-'*5}|:{'-'*28}|{'-'*5}:|{'-'*8}:|{'-'*6}:"
        f"|{'-'*4}:|{'-'*5}:|{'-'*4}:|{'-'*7}:|{'-'*6}:|"
    )

    for r in per_rule:
        label_str = r.get("truth_display") or (",".join(r["label_types"]) if r["label_types"] else "(없음)")
        if len(label_str) > 28:
            label_str = label_str[:25] + "..."
        recall_str = f"{r['recall']:.0%}" if r["recall"] is not None else "—"
        prec_str = f"{r['precision']:.0%}" if r["precision"] is not None else "—"

        if r["status"] == "skipped":
            md.append(
                f"| {r['rule_id']:5s} | {label_str:28s} | {'—':>5s} | {'SKIP':>8s} | {'—':>6s} "
                f"| {'—':>4s} | {'—':>5s} | {'—':>4s} | {'—':>7s} | {'—':>6s} |"
            )
        else:
            md.append(
                f"| {r['rule_id']:5s} | {label_str:28s} | {r['label_docs']:>5d} | {r['flagged_rows']:>8,d} | {r['flagged_docs']:>6d} "
                f"| {r['tp_docs']:>4d} | {r['fp_docs']:>5d} | {r['fn_docs']:>4d} | {recall_str:>7s} | {prec_str:>6s} |"
            )

    # ── §4 미탐지 상세 (FN 분석) ──
    md.append("\n## 4. 미탐지(FN) 샘플 분석\n")
    fn_rules = [r for r in per_rule if r["fn_docs"] > 0]
    if fn_rules:
        for r in fn_rules:
            md.append(f"### {r['rule_id']} — FN {r['fn_docs']}건 (Recall {r['recall']:.0%})\n")
            if r["sample_fn"]:
                md.append(f"샘플 document_id: `{'`, `'.join(r['sample_fn'][:5])}`\n")
    else:
        md.append("미탐지 건 없음.\n")

    # ── §5 오탐 분석 ──
    md.append("\n## 5. 오탐(FP) 분석\n")
    md.append(
        "FP = 탐지 룰이 플래그했지만 해당 anomaly_type 라벨이 없는 문서.\n"
        "단, 라벨에 다른 anomaly_type이 있거나 is_fraud/is_anomaly=True일 수 있음 (교차 탐지).\n"
    )
    high_fp = [r for r in per_rule if r["fp_docs"] > 100]
    if high_fp:
        md.append(f"| {'룰':5s} | {'FP 문서':>8s} | {'비고':40s} |")
        md.append(f"|:{'-'*5}|{'-'*8}:|:{'-'*40}|")
        for r in sorted(high_fp, key=lambda x: -x["fp_docs"]):
            md.append(f"| {r['rule_id']:5s} | {r['fp_docs']:>8,d} | 교차 탐지 또는 과탐 확인 필요 |")
    else:
        md.append("FP > 100건인 룰 없음.\n")

    # ── §6 Phase 2/3 미커버 라벨 ──
    md.append("\n## 6. Phase 1 미커버 라벨 타입 (Phase 2/3 대상)\n")
    if uncovered:
        md.append(f"| {'anomaly_type':30s} | {'건수':>6s} | {'대상 Phase':>12s} |")
        md.append(f"|:{'-'*30}|{'-'*6}:|:{'-'*12}|")
        for u in uncovered:
            md.append(f"| {u['anomaly_type']:30s} | {u['count']:>6d} | Phase 2/3 |")
    else:
        md.append("모든 라벨 타입이 Phase 1 룰에 매핑됨.\n")

    # ── §7 L1~L4 성능 ──
    md.append("\n## 7. L1~L4 실행 성능\n")
    md.append(f"| {'단계':20s} | {'소요(s)':>10s} | {'룰 수':>6s} |")
    md.append(f"|:{'-'*20}|{'-'*10}:|{'-'*6}:|")
    for track, title in [
        ("layer_a", "L1"),
        ("layer_b", "L2"),
        ("layer_c", "L3/L4"),
        ("benford", "L4-02 Benford"),
        ("aggregator", "Score Aggregator"),
    ]:
        t = timings.get(track, 0.0)
        rules_run = len(results[track].rule_flags) if track in results else 0
        md.append(f"| {title:20s} | {t:>10.3f} | {rules_run:>6d} |")

    # ── §8 L1~L4 룰 상세 ──
    md.append("\n## 8. L1~L4 룰 탐지 결과\n")
    for track, title in [
        ("layer_a", "L1"),
        ("layer_b", "L2"),
        ("layer_c", "L3/L4"),
        ("benford", "L4-02 Benford"),
    ]:
        r = results[track]
        md.append(f"### {title}\n")
        md.append(f"| {'룰':6s} | {'이름':16s} | {'flagged':>10s} | {'비율':>8s} | {'severity':>8s} |")
        md.append(f"|:{'-'*6}|:{'-'*16}|{'-'*10}:|{'-'*8}:|{'-'*8}:|")
        for rf in sorted(r.rule_flags, key=lambda x: x.rule_id):
            rate = f"{rf.flagged_count / n * 100:.2f}%" if n > 0 else "0.00%"
            md.append(
                f"| {rf.rule_id:6s} | {rf.rule_name:16s} | {rf.flagged_count:>10,d} | {rate:>8s} | {rf.severity:>8d} |"
            )
        md.append("")

    # ── §9 판정 ──
    md.append("\n## 9. 종합 판정\n")

    # 코드 버그 판별
    all_false = [r for r in per_rule if r["status"] == "ok" and r["flagged_rows"] == 0 and r["label_docs"] > 0]
    zero_recall = [r for r in per_rule if r["status"] == "ok" and r["recall"] == 0.0 and r["label_docs"] > 0]
    low_recall = [r for r in per_rule if r["status"] == "ok" and r["recall"] is not None and 0 < r["recall"] < 0.3 and r["label_docs"] >= 5]

    md.append("### 코드 버그 의심\n")
    if all_false:
        for r in all_false:
            md.append(f"- **{r['rule_id']}**: 라벨 {r['label_docs']}건 존재하나 탐지 0건 → 코드 또는 데이터 불일치 확인 필요")
    elif zero_recall:
        for r in zero_recall:
            md.append(f"- **{r['rule_id']}**: recall=0% (라벨 {r['label_docs']}건) → 탐지 로직 점검 필요")
    else:
        md.append("없음.\n")

    md.append("\n### 낮은 recall (< 30%)\n")
    if low_recall:
        for r in low_recall:
            md.append(f"- **{r['rule_id']}**: recall={r['recall']:.0%} (라벨 {r['label_docs']}건, TP {r['tp_docs']}건)")
    else:
        md.append("없음.\n")

    md.append("\n### Graceful Degradation (정상)\n")
    skipped = [r for r in per_rule if r["status"] == "skipped"]
    no_label = [r for r in per_rule if r["status"] == "no_label"]
    if skipped:
        for r in skipped:
            md.append(f"- `{r['rule_id']}`: {r['reason']}")
    if no_label:
        for r in no_label:
            md.append(f"- `{r['rule_id']}`: 대응 라벨 없음 (라벨 매핑 불가, 탐지 자체는 정상 작동)")
    if not skipped and not no_label:
        md.append("없음.\n")

    return "\n".join(md) + "\n"


# ── 메인 ─────────────────────────────────────────────────


def main() -> None:
    print("=== Detection E2E Label Validation ===")
    total_start = time.perf_counter()

    # 1. 데이터 로드
    print("[1/5] 데이터 로드 중...")
    df = load_data()
    print(f"      → {len(df):,d}행 × {len(df.columns)}컬럼")

    # 2. 피처 생성
    print("[2/5] 피처 생성 중...")
    t0 = time.perf_counter()
    df = run_features(df)
    print(f"      → {time.perf_counter() - t0:.2f}s")

    # 3. Detection
    print("[3/5] Detection 실행 중 (A→B→C→Benford→집계)...")
    det = run_detection(df)
    for track in ["layer_a", "layer_b", "layer_c", "benford", "aggregator"]:
        print(f"      → {track}: {det['timings'][track]:.2f}s")

    # 4. 라벨 교차 대조
    print("[4/5] 라벨 교차 대조 중...")
    labels = load_labels()
    if labels.empty:
        print("      → anomaly_labels.csv 없음 — 중단")
        return

    per_rule = gt_eval.per_rule_label_analysis(df, det["results"], labels)
    overall = gt_eval.overall_label_analysis(df, det["agg_df"], labels)
    uncovered = gt_eval.uncovered_label_analysis(labels)

    # 요약 출력
    print(f"      → Phase 1 Recall: {overall['phase1_recall']:.1%} ({overall['phase1_tp']}/{overall['phase1_labeled']})")
    print(f"      → 전체 Recall: {overall['total_recall']:.1%} ({overall['total_tp']}/{overall['total_labeled']})")

    # 5. 리포트 생성
    total_elapsed = time.perf_counter() - total_start
    print(f"[5/5] 리포트 생성 중... (총 {total_elapsed:.1f}s)")

    report = generate_report(df, det, per_rule, overall, uncovered, total_elapsed)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(f"      → 저장: {OUTPUT_MD}")

    # 룰별 요약
    print("\n=== 룰별 요약 ===")
    print(f"{'룰':5s} {'라벨':>5s} {'탐지행':>8s} {'TP':>5s} {'FN':>4s} {'Recall':>7s} {'Prec':>6s}")
    print("-" * 50)
    for r in per_rule:
        if r["status"] == "skipped":
            print(f"{r['rule_id']:5s} {'N/A':>5s} {'SKIP':>8s}")
            continue
        recall_str = f"{r['recall']:.0%}" if r["recall"] is not None else "-"
        prec_str = f"{r['precision']:.0%}" if r["precision"] is not None else "-"
        print(
            f"{r['rule_id']:5s} {r['label_docs']:>5d} {r['flagged_rows']:>8,d} "
            f"{r['tp_docs']:>5d} {r['fn_docs']:>4d} {recall_str:>7s} {prec_str:>6s}"
        )

    print(f"\n=== 완료 ({total_elapsed:.1f}s) ===")


if __name__ == "__main__":
    main()
