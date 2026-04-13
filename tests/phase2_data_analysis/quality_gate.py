"""Phase 1/2/3 공통 데이터 품질 게이트 — 자동 pass/fail 판정.

Why: 재설계·재생성을 반복하려면 "목표 기준"이 기계적으로 판정 가능해야 한다.
     independent_profile.json을 로드하여 8축 × 기준별 pass/fail + 개선 필요 항목을
     리스트로 반환한다.

실행:
    uv run python -m tests.phase2_data_analysis.quality_gate
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_PROFILE_PATH = Path(__file__).parent / "results" / "independent_profile.json"
_GATE_REPORT_PATH = Path(__file__).parent / "results" / "quality_gate_report.md"


@dataclass
class GateCheck:
    """단일 기준 체크 결과."""
    phase: str                  # "P1" | "P2" | "P3" | "COMMON"
    name: str
    target: str                 # 사람이 읽는 목표
    actual: str
    passed: bool
    severity: str = "normal"    # "normal" | "critical"
    why: str = ""               # 실패 시 설명


@dataclass
class GateReport:
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def critical_failures(self) -> list[GateCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "critical"]

    @property
    def warnings(self) -> list[GateCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "normal"]

    def summary(self) -> dict:
        return {
            "total": len(self.checks),
            "passed": sum(1 for c in self.checks if c.passed),
            "failed": sum(1 for c in self.checks if not c.passed),
            "critical": len(self.critical_failures),
            "overall": "PASS" if self.passed else "FAIL",
        }


# ── 기준 정의 ────────────────────────────────────────────────
# Phase 1: 룰 기반 탐지 (recall ≥ 80%)
# Phase 2: ML/시퀀스/드리프트 (GroupKFold/BiLSTM/PSI 작동)
# Phase 3: LLM + 감사조서 생성 (텍스트 다양성, 거래처 현실성)


def check_all(profile: dict) -> GateReport:
    report = GateReport()

    # ── COMMON: 기본 구조 건전성 ────────────────────────────
    dq = profile.get("axis_7_data_quality", {})
    report.checks.append(GateCheck(
        phase="COMMON",
        name="full_duplicate_rows",
        target="중복 행 = 0",
        actual=str(dq.get("full_duplicate_rows", -1)),
        passed=dq.get("full_duplicate_rows", -1) == 0,
        severity="critical",
    ))
    report.checks.append(GateCheck(
        phase="COMMON",
        name="line_number_gap",
        target="line_number gap = 0",
        actual=str(dq.get("docs_with_gap_in_line_number", -1)),
        passed=dq.get("docs_with_gap_in_line_number", -1) == 0,
        severity="critical",
    ))
    null_rate = dq.get("null_rate_by_col", {})
    critical_nulls = {
        "document_id", "posting_date", "created_by", "debit_amount", "credit_amount",
    }
    for col in critical_nulls:
        rate = null_rate.get(col, 1.0)
        report.checks.append(GateCheck(
            phase="COMMON",
            name=f"null_rate_{col}",
            target=f"{col} null < 1%",
            actual=f"{rate*100:.2f}%",
            passed=rate < 0.01,
            severity="critical",
        ))

    # ── Phase 1: 룰 기반 탐지 현실성 ────────────────────────

    # P1-1: Benford 적합성 — MAD < 0.015 (Nigrini "적합")
    ag = profile.get("axis_4_amount_geometry", {})
    benford_mad = ag.get("benford_mad", 1.0)
    report.checks.append(GateCheck(
        phase="P1",
        name="benford_mad",
        target="MAD < 0.015 (Nigrini 적합)",
        actual=f"{benford_mad:.5f}",
        passed=benford_mad < 0.015,
    ))

    # P1-2: 12월 편향 완화 — 모든 fraud_type이 12월 1순위인 경우 편향
    fsig = profile.get("axis_8_fraud_signature", {})
    fraud_month = fsig.get("fraud_month_concentration", {})
    dec_first_count = 0
    for ft, months in fraud_month.items():
        if months:
            top_month = max(months.items(), key=lambda kv: kv[1])[0]
            if str(top_month) == "12":
                dec_first_count += 1
    total_types = len(fraud_month)
    dec_dominance = dec_first_count / total_types if total_types else 0
    report.checks.append(GateCheck(
        phase="P1",
        name="december_dominance",
        target="12월 1순위 fraud_type ≤ 60% (현실적 분산)",
        actual=f"{dec_dominance*100:.0f}% ({dec_first_count}/{total_types})",
        passed=dec_dominance <= 0.6,
        why="모든 fraud_type이 12월에 몰리면 C01(기말 대규모) 룰 과적합 유발",
    ))

    # P1-3: 심야 fraud 존재 — 실사용자 기반
    temporal = profile.get("axis_1_temporal_granularity", {})
    top_after_hours = temporal.get("top_after_hours_users", {})
    non_system_ahs = sum(v for k, v in top_after_hours.items() if not k.startswith("SYSTEM-"))
    report.checks.append(GateCheck(
        phase="P1",
        name="after_hours_real_users",
        target="실사용자 심야 전표 ≥ 200건 (C03/C12 탐지 타겟)",
        actual=f"{non_system_ahs}건",
        passed=non_system_ahs >= 200,
        why="SYSTEM 계정 제외한 실사용자 심야 입력이 없으면 C03(심야 전기) 룰 미작동",
    ))

    # P1-4: ExceededApprovalLimit 금액 현실성 — 중견기업 상한 30억 이내
    fraud_median = fsig.get("fraud_median_amount", {})
    excess_median = fraud_median.get("ExceededApprovalLimit", 0)
    report.checks.append(GateCheck(
        phase="P1",
        name="exceeded_approval_realistic",
        target="ExceededApprovalLimit 중앙값 ≤ 3,000,000,000 (30억, 중견기업 상한)",
        actual=f"{excess_median:,.0f}원",
        passed=excess_median <= 3_000_000_000,
        why="28.6억 이상은 한국 중견기업 전결규정과 괴리",
    ))

    # P1-5: RoundDollarManipulation 금액 — 극소액 방지
    round_median = fraud_median.get("RoundDollarManipulation", 0)
    report.checks.append(GateCheck(
        phase="P1",
        name="round_dollar_realistic",
        target="RoundDollarManipulation 중앙값 ≥ 100,000 (10만원)",
        actual=f"{round_median:,.0f}원",
        passed=round_median >= 100_000,
        why="극소액(227원) 조작은 의미 없음 — 최소 10만원 수준 필요",
    ))

    # ── Phase 2: ML/시퀀스/드리프트 ──────────────────────────

    # P2-1: 사용자 수 ≥ 1000 (GroupKFold 안정성)
    us = profile.get("axis_2_user_sequence", {})
    total_users = us.get("total_unique_users", 0)
    report.checks.append(GateCheck(
        phase="P2",
        name="total_users",
        target="사용자 수 ≥ 1,000 (대규모 시나리오)",
        actual=f"{total_users:,}명",
        passed=total_users >= 1000,
        severity="critical",
        why="BiLSTM 사용자 패턴 학습의 실전 일반화를 위해 1,000+ 필요",
    ))

    # P2-2: Fraud 사용자 집중 — 양성 보유 사용자가 전체의 20% 이내
    lq = profile.get("axis_3_label_quality", {})
    fraud_overlap = lq.get("fraud_user_overlap_rate", 1.0)
    report.checks.append(GateCheck(
        phase="P2",
        name="fraud_user_concentration",
        target="Fraud 보유 사용자 비율 ≤ 20% (횡령범 집중형)",
        actual=f"{fraud_overlap*100:.1f}%",
        passed=fraud_overlap <= 0.2,
        severity="critical",
        why="전체 사용자가 fraud를 보유하면 GroupKFold user-leakage 방어 무의미",
    ))

    # P2-3: 양성 비율 라벨 품질 — 5~25% 구간 외에 0~5% 구간 사용자 존재
    pos_bins = lq.get("user_positive_rate_bins", {})
    clean_users = pos_bins.get("0_clean", 0) + pos_bins.get("1_low_<=5%", 0)
    clean_ratio = clean_users / total_users if total_users else 0
    report.checks.append(GateCheck(
        phase="P2",
        name="clean_user_ratio",
        target="Clean/low 사용자 ≥ 70% (정상 사용자 다수)",
        actual=f"{clean_ratio*100:.1f}%",
        passed=clean_ratio >= 0.7,
        severity="critical",
    ))

    # P2-4: 연간 fraud_rate 안정성 — PSI 베이스라인
    drift = profile.get("axis_5_drift_baseline", {})
    yearly = drift.get("yearly_fraud_rate", {})
    if len(yearly) >= 2:
        rates = list(yearly.values())
        yearly_spread = max(rates) - min(rates)
    else:
        yearly_spread = 1.0
    report.checks.append(GateCheck(
        phase="P2",
        name="yearly_fraud_stability",
        target="연간 fraud_rate 변동 ≤ 0.5%p (PSI stable)",
        actual=f"±{yearly_spread*100:.2f}%p",
        passed=yearly_spread <= 0.005,
    ))

    # P2-5: 사용자당 평균 전표 수 — BiLSTM seq_len 충족
    pcts = us.get("docs_per_user_percentiles", {})
    p25 = pcts.get("P25", 0)
    report.checks.append(GateCheck(
        phase="P2",
        name="user_docs_p25",
        target="사용자 P25 전표 수 ≥ 16 (BiLSTM seq_len 충족)",
        actual=f"{p25:.0f}건",
        passed=p25 >= 16,
    ))

    # P2-6: 양성 vs 음성 금액 중앙값 비율 — ML 분리가능성
    label_median = ag.get("amount_median_by_label", {})
    pos_med = label_median.get("positive", 0)
    neg_med = label_median.get("negative", 1)
    ratio = pos_med / neg_med if neg_med else 0
    report.checks.append(GateCheck(
        phase="P2",
        name="positive_negative_amount_ratio",
        target="양성/음성 금액 비율 ∈ [1.3, 5.0] (ML 분리가능)",
        actual=f"{ratio:.2f}x",
        passed=1.3 <= ratio <= 5.0,
    ))

    # ── Phase 3: LLM + 감사조서 생성 ─────────────────────────

    # P3-1: 승인자 집중도 — Top 3가 전체의 10~50%
    sod = profile.get("axis_6_sod_persona", {})
    top3_share = sod.get("top3_approver_share", 0)
    report.checks.append(GateCheck(
        phase="P3",
        name="top3_approver_share",
        target="Top 3 승인자 비중 ∈ [20%, 50%] (실무 승인 체계)",
        actual=f"{top3_share*100:.1f}%",
        passed=0.20 <= top3_share <= 0.50,
        why="너무 평평하면 비현실적, 너무 집중되면 단일 장애점",
    ))

    # P3-2: fraud_type 다양성 — 최소 8개 이상
    fraud_types = len(fraud_month)
    report.checks.append(GateCheck(
        phase="P3",
        name="fraud_type_diversity",
        target="Fraud 타입 ≥ 8종",
        actual=f"{fraud_types}종",
        passed=fraud_types >= 8,
    ))

    # P3-3: business process 균형 — automated_system 50% 미만
    persona_avg = us.get("avg_docs_per_persona", {})
    auto_docs = persona_avg.get("automated_system", 0)
    total_avg = sum(persona_avg.values()) or 1
    auto_share = auto_docs / total_avg
    report.checks.append(GateCheck(
        phase="P3",
        name="automated_system_share",
        target="automated_system 평균 전표 비중 ≤ 50%",
        actual=f"{auto_share*100:.1f}%",
        passed=auto_share <= 0.5,
        why="자동 전표가 과도하면 LLM 감사보고서에 쓸 실제 인간 맥락 부족",
    ))

    return report


def format_report(report: GateReport) -> str:
    lines = ["# Data Quality Gate Report\n"]
    summary = report.summary()
    lines.append(f"**Overall**: {'✅ PASS' if report.passed else '❌ FAIL'}")
    lines.append(f"- 총 {summary['total']}개 체크 / 통과 {summary['passed']} / 실패 {summary['failed']}")
    lines.append(f"- Critical 실패: {summary['critical']}")
    lines.append("")

    # Phase별 그룹화
    for phase in ["COMMON", "P1", "P2", "P3"]:
        phase_checks = [c for c in report.checks if c.phase == phase]
        if not phase_checks:
            continue
        p = sum(1 for c in phase_checks if c.passed)
        lines.append(f"## {phase} ({p}/{len(phase_checks)})")
        lines.append("")
        for c in phase_checks:
            icon = "✅" if c.passed else ("🚨" if c.severity == "critical" else "⚠️")
            lines.append(f"- {icon} **{c.name}**")
            lines.append(f"  - 목표: {c.target}")
            lines.append(f"  - 실제: {c.actual}")
            if not c.passed and c.why:
                lines.append(f"  - 이유: {c.why}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    with open(_PROFILE_PATH, encoding="utf-8") as f:
        profile = json.load(f)
    report = check_all(profile)

    _GATE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GATE_REPORT_PATH.write_text(format_report(report), encoding="utf-8")

    summary = report.summary()
    print("=" * 60)
    print(f"Quality Gate: {summary['overall']}")
    print(f"  통과: {summary['passed']}/{summary['total']}")
    print(f"  Critical 실패: {summary['critical']}")
    print("=" * 60)
    if not report.passed:
        print("\n실패 항목:")
        for c in report.checks:
            if not c.passed:
                tag = "[CRIT]" if c.severity == "critical" else "[WARN]"
                print(f"  {tag} [{c.phase}] {c.name}: {c.actual} (목표: {c.target})")
    print(f"\n리포트: {_GATE_REPORT_PATH}")


if __name__ == "__main__":
    main()
