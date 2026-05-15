"""§9.4 권고 B 적용 후 분포 측정 — phase1_score_band_audit_after 산출용.

새 RISK_THRESHOLDS(HIGH=0.50, MEDIUM=0.25, LOW=0.10) 기준으로 기존 v2 case_input
artifacts의 anomaly_score를 재분류하고 정책 floor·truth recall·HIGH 비율 등
수용 기준을 계산한다.

주의: 기존 artifact는 RISK_THRESHOLDS 변경 전에 생성된 것이라 정책 floor가 baked-in
old 값(immediate=0.70)으로 남아 있다. 그러나 anomaly_score 값 자체는 risk_level
경계 통과 여부에만 영향을 미치므로 신규 임계값으로 재분류하면 신규 RUN의 결과와
정성적으로 일치한다. 정책 floor 행은 어차피 강제 HIGH로 분류되므로 영향 없다.
"""

from __future__ import annotations

import pickle
from collections import Counter
from pathlib import Path

import pandas as pd

from src.detection.constants import RISK_THRESHOLDS, RiskLevel
from src.detection.score_aggregator import classify_risk_level

V2_PKL = Path("artifacts/phase1_contract_v2_case_input_20260514.pkl")
MANIPULATION_PKL = Path("artifacts/phase1_manipulation_v134_case_input.pkl")
MANIPULATION_TRUTH_CSV = Path("artifacts/manipulation_truth_case_placement_v134.csv")


def _load_df() -> pd.DataFrame:
    with V2_PKL.open("rb") as fh:
        bundle = pickle.load(fh)
    return bundle["df"]


def _band_counts(level: pd.Series) -> dict[str, int]:
    counts = level.value_counts()
    return {
        label: int(counts.get(label, 0))
        for label in (
            RiskLevel.HIGH,
            RiskLevel.MEDIUM,
            RiskLevel.LOW,
            RiskLevel.NORMAL,
        )
    }


def _format_pct(numerator: int, total: int) -> str:
    if total == 0:
        return "0.00%"
    return f"{numerator / total * 100:.2f}%"


def main() -> None:
    df = _load_df()
    total = len(df)
    print(f"v2 case_input rows: {total:,}")

    score = pd.to_numeric(df["anomaly_score"], errors="coerce").fillna(0.0)

    # 1) 기존 risk_level 분포 (artifact 시점 = 구 임계값 적용)
    old_level = df["risk_level"].astype("string").fillna(RiskLevel.NORMAL)
    old_counts = _band_counts(old_level)
    print("\n[OLD] risk_level distribution (artifact-baked):")
    for k, v in old_counts.items():
        print(f"  {k:8s} {v:>8,d}  {_format_pct(v, total)}")

    # 2) 신규 임계값 재분류
    new_level = classify_risk_level(score)
    new_counts = _band_counts(new_level)
    print(
        f"\n[NEW] risk_level distribution "
        f"(HIGH={RISK_THRESHOLDS[RiskLevel.HIGH]}, "
        f"MEDIUM={RISK_THRESHOLDS[RiskLevel.MEDIUM]}, "
        f"LOW={RISK_THRESHOLDS[RiskLevel.LOW]}):"
    )
    for k, v in new_counts.items():
        print(f"  {k:8s} {v:>8,d}  {_format_pct(v, total)}")

    # 3) HIGH 비율 수용 기준 (≤ 1%)
    high_ratio = new_counts[RiskLevel.HIGH] / total
    print(
        f"\nHIGH ratio acceptance criterion (<= 1%): "
        f"{_format_pct(new_counts[RiskLevel.HIGH], total)} -> "
        f"{'PASS' if high_ratio <= 0.01 else 'FAIL'}"
    )

    # 4) Truth row vs non-truth row recall
    truth_mask = df["mutation_type"].notna() & df["mutation_type"].ne("")
    truth_rows = int(truth_mask.sum())
    non_truth_rows = total - truth_rows
    print(f"\nTruth rows: {truth_rows:,}  Non-truth rows: {non_truth_rows:,}")

    truth_levels = new_level[truth_mask]
    non_truth_levels = new_level[~truth_mask]

    truth_counts = _band_counts(truth_levels)
    non_truth_counts = _band_counts(non_truth_levels)

    truth_medium_plus = truth_counts[RiskLevel.MEDIUM] + truth_counts[RiskLevel.HIGH]
    non_truth_medium_plus = non_truth_counts[RiskLevel.MEDIUM] + non_truth_counts[RiskLevel.HIGH]
    truth_medium_plus_ratio = truth_medium_plus / max(truth_rows, 1)
    print("\nTruth row band distribution:")
    for k, v in truth_counts.items():
        print(f"  {k:8s} {v:>8,d}  {_format_pct(v, truth_rows)}")
    print(
        f"  Medium+ recall: {_format_pct(truth_medium_plus, truth_rows)} "
        f"-> {'PASS' if truth_medium_plus_ratio >= 0.25 else 'FAIL'} (>= 25%)"
    )

    print("\nNon-truth row band distribution:")
    for k, v in non_truth_counts.items():
        print(f"  {k:8s} {v:>8,d}  {_format_pct(v, non_truth_rows)}")
    print(f"  Medium+ rate (FP proxy): {_format_pct(non_truth_medium_plus, non_truth_rows)}")

    # 5) 정책 floor reason 분포 (구 → 신 임계값 충돌 점검)
    reasons = df["risk_floor_reasons"].astype("string").fillna("")
    reason_counter = Counter()
    for raw in reasons:
        if not raw:
            continue
        for token in raw.split(","):
            token = token.strip()
            if token:
                reason_counter[token] += 1
    print("\nPolicy floor reason distribution (artifact-baked):")
    for label, count in sorted(reason_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {label:42s} {count:>8,d}")

    # 6) HIGH 등급 안에 정책 floor 행이 모두 포함되는지 (충돌 없음 점검)
    has_floor = reasons.ne("")
    high_mask = new_level.eq(RiskLevel.HIGH)
    floor_in_high = int((has_floor & high_mask).sum())
    floor_not_high = int((has_floor & ~high_mask).sum())
    print(
        f"\nPolicy floor rows in NEW HIGH: {floor_in_high:,} / "
        f"{int(has_floor.sum()):,}  (not-HIGH={floor_not_high})"
    )

    # 7) Manipulation v134 dataset: document-level truth row recall
    print("\n--- Manipulation v134 truth row recall ---")
    if MANIPULATION_PKL.exists() and MANIPULATION_TRUTH_CSV.exists():
        with MANIPULATION_PKL.open("rb") as fh:
            m_bundle = pickle.load(fh)
        m_df = m_bundle["df"]
        m_score = pd.to_numeric(m_df["anomaly_score"], errors="coerce").fillna(0.0)
        m_new_level = classify_risk_level(m_score)
        truth_csv = pd.read_csv(MANIPULATION_TRUTH_CSV)
        truth_doc_ids = set(truth_csv["document_id"].astype(str))
        m_truth_mask = m_df["document_id"].astype(str).isin(truth_doc_ids)
        m_truth_rows = int(m_truth_mask.sum())
        m_truth_levels = m_new_level[m_truth_mask]
        m_truth_counts = _band_counts(m_truth_levels)
        m_truth_medium_plus = m_truth_counts[RiskLevel.MEDIUM] + m_truth_counts[RiskLevel.HIGH]
        print(f"manipulation v134 rows: {len(m_df):,}")
        print(f"truth document_ids: {len(truth_doc_ids):,}  truth rows: {m_truth_rows:,}")
        print("Manipulation truth row band distribution:")
        for k, v in m_truth_counts.items():
            print(f"  {k:8s} {v:>8,d}  {_format_pct(v, m_truth_rows)}")
        m_ratio = m_truth_medium_plus / max(m_truth_rows, 1)
        print(
            f"  Medium+ recall: {_format_pct(m_truth_medium_plus, m_truth_rows)} "
            f"-> {'PASS' if m_ratio >= 0.25 else 'FAIL'} (>= 25%)"
        )
    else:
        print("[skip] manipulation pkl or truth csv not found")

    # 8) score histogram around new thresholds
    bins = [
        0,
        0.05,
        0.10,
        0.15,
        0.20,
        0.25,
        0.30,
        0.35,
        0.40,
        0.45,
        0.50,
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
        0.80,
        1.0001,
    ]
    labels = [f"[{bins[i]:.2f},{bins[i + 1]:.2f})" for i in range(len(bins) - 1)]
    cut = pd.cut(score, bins=bins, right=False, include_lowest=True, labels=labels)
    print("\nScore histogram (new bins):")
    for label, count in cut.value_counts().sort_index().items():
        print(f"  {label}  {int(count):>8,d}")


if __name__ == "__main__":
    main()
