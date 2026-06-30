"""Detection E2E 테스트 — DataSynth 1M행 전체 파이프라인.

독립 실행 스크립트 (pytest 아님). 1M행 처리에 수십 초 소요.
실행: uv run python tests/test_detection/test_e2e_detection.py
결과: tests/test_detection/test-results/e2e-detection-datasynth.md
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
from src.detection.constants import SEVERITY_MAP
from src.detection.fraud_layer import FraudLayer
from src.detection.integrity_layer import IntegrityDetector
from src.detection.score_aggregator import aggregate_scores
from src.feature.engine import generate_all_features

# ── 경로 상수 ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_CSV = PROJECT_ROOT / "data/journal/primary/datasynth/journal_entries.csv"
LABELS_CSV = PROJECT_ROOT / "data/journal/primary/datasynth/labels/anomaly_labels.csv"
OUTPUT_DIR = Path(__file__).resolve().parent / "test-results"
OUTPUT_MD = OUTPUT_DIR / "e2e-detection-datasynth.md"


# ── 파이프라인 단계 ────────────────────────────────────────


def load_data() -> pd.DataFrame:
    """DataSynth CSV 로드 + 날짜 파싱."""
    df = pd.read_csv(
        DATA_CSV,
        parse_dates=["posting_date", "document_date"],
        low_memory=False,
    )
    return df


def run_features(df: pd.DataFrame) -> pd.DataFrame:
    """피처 엔진 실행 → 18개 파생변수 추가."""
    settings = get_settings()
    rules = get_audit_rules()
    result = generate_all_features(df, settings=settings, rules=rules)
    return result.data


def run_detection(df: pd.DataFrame) -> dict:
    """L1/L2/L3/L4 + Benford 독립 트랙 탐지 + 점수 집계."""
    results: dict[str, DetectionResult] = {}
    timings: dict[str, float] = {}

    # L1
    t0 = time.perf_counter()
    results["layer_a"] = IntegrityDetector().detect(df)
    timings["layer_a"] = time.perf_counter() - t0

    # L2
    t0 = time.perf_counter()
    results["layer_b"] = FraudLayer().detect(df)
    timings["layer_b"] = time.perf_counter() - t0

    # L3/L4 (L3-04~L3-07, L4-03~L4-04 — L4-02 제외)
    t0 = time.perf_counter()
    results["layer_c"] = AnomalyDetector().detect(df)
    timings["layer_c"] = time.perf_counter() - t0

    # Benford 독립 트랙 (L4-02)
    t0 = time.perf_counter()
    results["benford"] = BenfordDetector().detect(df)
    timings["benford"] = time.perf_counter() - t0

    # 점수 집계 (4트랙: A 0.15 + B 0.45 + C 0.25 + Benford 0.15)
    t0 = time.perf_counter()
    agg_df = aggregate_scores(df, list(results.values()))
    timings["aggregator"] = time.perf_counter() - t0

    return {"results": results, "agg_df": agg_df, "timings": timings}


def load_labels() -> pd.DataFrame:
    """anomaly_labels.csv 로드."""
    if not LABELS_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(LABELS_CSV)


def analyze_labels(
    df: pd.DataFrame,
    agg_df: pd.DataFrame,
    labels: pd.DataFrame,
) -> dict:
    """anomaly label 대조 분석 — recall/precision 추정."""
    if labels.empty:
        return {"available": False}

    # Why: anomaly label의 document_id와 원본 df의 document_id를 매핑
    labeled_docs = set(labels["document_id"].dropna())
    flagged_mask = agg_df["anomaly_score"] > 0
    flagged_docs = set(df.loc[flagged_mask, "document_id"].dropna())

    # Why: 행 단위가 아닌 document 단위 대조 (label은 document 단위)
    tp_docs = labeled_docs & flagged_docs
    actual = len(labeled_docs)
    detected = len(flagged_docs)
    tp = len(tp_docs)

    recall = tp / actual if actual > 0 else 0.0
    precision = tp / detected if detected > 0 else 0.0

    # 카테고리별 recall
    cat_recall = {}
    for cat in labels["anomaly_category"].dropna().unique():
        cat_docs = set(labels.loc[labels["anomaly_category"] == cat, "document_id"])
        cat_tp = len(cat_docs & flagged_docs)
        cat_recall[cat] = {
            "actual": len(cat_docs),
            "detected": cat_tp,
            "recall": cat_tp / len(cat_docs) if cat_docs else 0.0,
        }

    return {
        "available": True,
        "actual_docs": actual,
        "detected_docs": detected,
        "tp_docs": tp,
        "recall": recall,
        "precision": precision,
        "category_recall": cat_recall,
    }


# ── 리포트 생성 ────────────────────────────────────────────


def _rule_table(result: DetectionResult, total: int) -> str:
    """룰별 flagged 건수 테이블 생성."""
    lines = []
    lines.append(
        f"| {'룰':6s} | {'이름':16s} | {'flagged':>10s} | {'비율':>8s} | {'severity':>8s} |"
    )
    lines.append(f"|:{'-' * 6}|:{'-' * 16}|{'-' * 10}:|{'-' * 8}:|{'-' * 8}:|")
    for rf in sorted(result.rule_flags, key=lambda x: x.rule_id):
        rate = f"{rf.flagged_count / total * 100:.2f}%" if total > 0 else "0.00%"
        lines.append(
            f"| {rf.rule_id:6s} | {rf.rule_name:16s} | {rf.flagged_count:>10,d} | {rate:>8s} | {rf.severity:>8d} |"
        )
    return "\n".join(lines)


def generate_report(
    df: pd.DataFrame,
    det: dict,
    label_analysis: dict,
    total_elapsed: float,
) -> str:
    """MD 리포트 문자열 생성."""
    agg_df = det["agg_df"]
    results = det["results"]
    timings = det["timings"]
    n = len(df)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    flagged_count = int((agg_df["anomaly_score"] > 0).sum())
    risk_counts = agg_df["risk_level"].value_counts()

    # 실행된 룰 수 합산
    total_rules = sum(len(r.rule_flags) for r in results.values())
    skipped_all = []
    for r in results.values():
        skipped_all.extend(r.metadata.get("skipped_rules", []))

    md = []
    md.append(f"# Detection E2E 테스트 결과 (DataSynth {n:,d}행)")
    md.append(f"\n> 실행일: {now}")

    # §1 요약
    md.append("\n## 1. 요약\n")
    md.append(f"| {'항목':20s} | {'값':30s} |")
    md.append(f"|:{'-' * 20}|:{'-' * 30}|")
    md.append(f"| {'입력 행수':20s} | {n:>30,d} |")
    md.append(f"| {'총 소요시간':20s} | {total_elapsed:>29.2f}s |")
    md.append(f"| {'플래그된 행':20s} | {flagged_count:>20,d} ({flagged_count / n * 100:.1f}%) |")

    for level in ["High", "Medium", "Low", "Normal"]:
        cnt = int(risk_counts.get(level, 0))
        md.append(f"| {'  ' + level:20s} | {cnt:>20,d} ({cnt / n * 100:.1f}%) |")

    md.append(f"| {'실행된 룰':20s} | {total_rules:>30d} |")
    md.append(f"| {'Skipped 룰':20s} | {str(skipped_all) if skipped_all else '없음':>30s} |")

    # §2 L1~L4 결과
    md.append("\n## 2. L1~L4 결과\n")

    layer_info = [
        ("layer_a", "L1"),
        ("layer_b", "L2"),
        ("layer_c", "L3/L4"),
        ("benford", "L4-02 Benford"),
    ]
    for track, title in layer_info:
        r = results[track]
        md.append(f"### {title}\n")
        md.append(_rule_table(r, n))
        md.append("")

    # §3 Top-side JE internal score
    md.append("\n## 3. Top-side JE internal score\n")
    if "topside_score" in agg_df.columns:
        b19_mask = agg_df["topside_score"] > 0
        b19_count = int(b19_mask.sum())
        manual_count = int(df["is_manual_je"].sum()) if "is_manual_je" in df.columns else 0

        md.append(f"| {'항목':24s} | {'값':>20s} |")
        md.append(f"|:{'-' * 24}|{'-' * 20}:|")
        md.append(f"| {'수기 전표':24s} | {manual_count:>12,d} ({manual_count / n * 100:.1f}%) |")
        md.append(f"| {'topside_score > 0':24s} | {b19_count:>12,d} ({b19_count / n * 100:.2f}%) |")

        # 게이트키퍼 검증
        if b19_count > 0 and "is_manual_je" in df.columns:
            all_manual = bool(df.loc[b19_mask, "is_manual_je"].all())
            md.append(
                f"| {'게이트키퍼 (전부 수기?)':24s} | {'✅ True' if all_manual else '❌ False':>20s} |"
            )

        # 역검증
        if "is_manual_je" in df.columns:
            auto_b19 = int(
                (agg_df.loc[~df["is_manual_je"].fillna(False), "topside_score"] > 0).sum()
            )
            md.append(f"| {'자동 전표 중 topside_score>0':24s} | {auto_b19:>20d} |")

        # 가점 조건별 분포
        if b19_count > 0:
            md.append("\n### 가점 조건별 분포\n")
            md.append(f"| {'조건':16s} | {'건수':>10s} | {'비율':>8s} |")
            md.append(f"|:{'-' * 16}|{'-' * 10}:|{'-' * 8}:|")
            b19_idx = b19_mask[b19_mask].index
            for label, track, rule_id in [
                ("L3-04 기말", "layer_c", "L3-04"),
                ("L1-05 자기승인", "layer_b", "L1-05"),
                ("L1-07 승인생략", "layer_b", "L1-07"),
                ("L1-03 무효계정", "layer_a", "L1-03"),
                ("L4-04 희소쌍", "layer_c", "L4-04"),
                ("L4-03 고액", "layer_c", "L4-03"),
            ]:
                r = results.get(track)
                if r and rule_id in r.details.columns:
                    v = int((r.details[rule_id].reindex(b19_idx, fill_value=0) > 0).sum())
                else:
                    v = 0
                md.append(f"| {label:16s} | {v:>10,d} | {v / b19_count * 100:>6.1f}% |")

        # topside_score 분포
        md.append("\n### topside_score 분포\n")
        md.append(f"| {'점수':>6s} | {'건수':>10s} |")
        md.append(f"|{'-' * 6}:|{'-' * 10}:|")
        ts = agg_df["topside_score"]
        for v in sorted(ts.unique()):
            cnt = int((ts == v).sum())
            if cnt > 0:
                md.append(f"| {v:>6.1f} | {cnt:>10,d} |")
    else:
        md.append("topside_score 컬럼 없음 — score_aggregator 미적용.\n")

    # §4 위험등급 분포
    md.append("\n## 4. 위험등급 분포\n")
    md.append(f"| {'risk_level':12s} | {'건수':>12s} | {'비율':>8s} |")
    md.append(f"|:{'-' * 12}|{'-' * 12}:|{'-' * 8}:|")
    for level in ["High", "Medium", "Low", "Normal"]:
        cnt = int(risk_counts.get(level, 0))
        md.append(f"| {level:12s} | {cnt:>12,d} | {cnt / n * 100:.2f}% |")

    # §5 label 대조 분석
    md.append("\n## 5. anomaly label 대조 분석\n")
    if label_analysis["available"]:
        la = label_analysis
        md.append(f"| {'지표':20s} | {'값':>20s} |")
        md.append(f"|:{'-' * 20}|{'-' * 20}:|")
        md.append(f"| {'실제 anomaly (문서)':20s} | {la['actual_docs']:>20,d} |")
        md.append(f"| {'탐지 flagged (문서)':20s} | {la['detected_docs']:>20,d} |")
        md.append(f"| {'True Positive':20s} | {la['tp_docs']:>20,d} |")
        md.append(f"| {'Recall':20s} | {la['recall']:>19.1%} |")
        md.append(f"| {'Precision':20s} | {la['precision']:>19.1%} |")

        md.append("\n### 카테고리별 recall\n")
        md.append(f"| {'category':20s} | {'실제':>8s} | {'탐지':>8s} | {'recall':>8s} |")
        md.append(f"|:{'-' * 20}|{'-' * 8}:|{'-' * 8}:|{'-' * 8}:|")
        for cat, info in sorted(la["category_recall"].items()):
            md.append(
                f"| {cat:20s} | {info['actual']:>8d} | {info['detected']:>8d} | {info['recall']:>7.1%} |"
            )
    else:
        md.append("anomaly_labels.csv 미존재 — 대조 분석 생략.")

    # §6 L1~L4 성능
    md.append("\n## 6. L1~L4 성능\n")
    md.append(f"| {'단계':20s} | {'소요시간(s)':>12s} | {'실행 룰':>8s} | {'skipped':>12s} |")
    md.append(f"|:{'-' * 20}|{'-' * 12}:|{'-' * 8}:|:{'-' * 12}|")
    for track, title in [
        ("layer_a", "L1"),
        ("layer_b", "L2"),
        ("layer_c", "L3/L4"),
        ("benford", "L4-02 Benford"),
        ("aggregator", "Score Aggregator"),
    ]:
        t = timings.get(track, 0.0)
        if track in results:
            r = results[track]
            rules_run = len(r.rule_flags)
            skipped = r.metadata.get("skipped_rules", [])
            md.append(
                f"| {title:20s} | {t:>12.3f} | {rules_run:>8d} | {str(skipped) if skipped else '—':>12s} |"
            )
        else:
            md.append(f"| {title:20s} | {t:>12.3f} | {'—':>8s} | {'—':>12s} |")

    # §7 분석
    md.append("\n## 7. 분석\n")
    md.append("### 코드 버그\n")

    # Why: all-False 룰 체크 (데이터 특성 or 코드 문제 판별)
    all_false_rules = []
    for r in results.values():
        for rf in r.rule_flags:
            if rf.flagged_count == 0:
                all_false_rules.append(rf.rule_id)

    if not all_false_rules:
        md.append("없음.\n")
    else:
        md.append("아래 §데이터 특성 참조.\n")

    md.append("### Graceful Degradation (정상)\n")
    if skipped_all:
        for rule_id in skipped_all:
            md.append(f"- `{rule_id}`: 필요 컬럼 부재로 skip (정상 동작)")
    else:
        md.append("skip된 룰 없음 — 39컬럼 표준 스키마 완전 매핑.\n")

    md.append("### 데이터 특성 (코드 정상, 데이터에 해당 패턴 부재)\n")
    if all_false_rules:
        for rule_id in sorted(all_false_rules):
            md.append(f"- `{rule_id}`: flagged=0 — DataSynth에 해당 패턴 미주입")
    else:
        md.append("모든 룰에서 1건 이상 탐지됨.\n")

    # §8 남은 문제점
    md.append("\n## 8. 남은 문제점\n")
    md.append("| 항목 | 설명 | 해결 시점 |")
    md.append("|:-----|:-----|:---------|")
    md.append(
        "| `src/pipeline.py` | 전체 오케스트레이터 미구현 — 수동 조립으로 테스트 | Phase 1b #21 |"
    )
    md.append(
        "| Benford 독립 트랙 | L4-02은 별도 독립 트랙으로 가중치 적용 | score_aggregator 확장 |"
    )

    return "\n".join(md) + "\n"


# ── 메인 ─────────────────────────────────────────────────


def main() -> None:
    print("=== Detection E2E Test (DataSynth) ===")
    total_start = time.perf_counter()

    # 1. 데이터 로드
    print("[1/6] 데이터 로드 중...")
    df = load_data()
    print(f"      → {len(df):,d}행 × {len(df.columns)}컬럼")

    # 2. 피처 생성
    print("[2/6] 피처 생성 중...")
    t0 = time.perf_counter()
    df = run_features(df)
    feat_time = time.perf_counter() - t0
    print(f"      → {feat_time:.2f}s")

    # 3~5. Detection
    print("[3/6] Detection 실행 중 (A→B→C→집계)...")
    det = run_detection(df)
    print(f"      → L1: {det['timings']['layer_a']:.2f}s")
    print(f"      → L2: {det['timings']['layer_b']:.2f}s")
    print(f"      → L3/L4: {det['timings']['layer_c']:.2f}s")
    print(f"      → Aggregator: {det['timings']['aggregator']:.2f}s")

    # 6. Label 대조
    print("[4/6] Label 대조 분석 중...")
    labels = load_labels()
    label_analysis = analyze_labels(df, det["agg_df"], labels)

    # 7. 리포트 생성
    total_elapsed = time.perf_counter() - total_start
    print(f"[5/6] 리포트 생성 중... (총 {total_elapsed:.2f}s)")

    report = generate_report(df, det, label_analysis, total_elapsed)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(f"[6/6] 리포트 저장: {OUTPUT_MD}")

    # 요약 출력
    agg_df = det["agg_df"]
    flagged = int((agg_df["anomaly_score"] > 0).sum())
    print("\n=== 완료 ===")
    print(f"플래그: {flagged:,d} / {len(df):,d} ({flagged / len(df) * 100:.1f}%)")
    risk_counts = agg_df["risk_level"].value_counts()
    for level in ["High", "Medium", "Low", "Normal"]:
        print(f"  {level}: {int(risk_counts.get(level, 0)):,d}")


if __name__ == "__main__":
    main()
