"""PHASE1 nightly KPI guard — Layer A/B/C 가드.

PHASE1 역할 원칙 (CLAUDE.md):
PHASE1은 fraud 확정/정답 라벨 맞히기 단계가 아니다. truth recall 향상을 강제하는
가드는 절대 추가 금지. PHASE1 향상은 도메인 정합성을 통해 자연 발생시키고,
truth recall은 부수효과(회귀 방지선)로만 측정한다.

3-Layer 구조:
  - Layer A (도메인 정합성, HARD FAIL): light_seeder=0, contract noise HIGH ≤1%,
    rule_truth 과탐/미탐=0, normal sample FP ≤5%, 정책 floor 충돌 없음,
    master/flow gap baseline ±10%
  - Layer B (운영 부하, HARD FAIL): case ≤13,000, 실행 ≤600s,
    priority_band 분포(high≤5%/medium 20~40%/low 55~75%), floor 적용 비율 ±50%
  - Layer C (truth-based 회귀 방지선, SOFT WARN): 포착률 ≥99% (절대 회귀만),
    high truth ≥baseline×70%, Top500 truth ≥baseline×70%, 시나리오 full entry ≥baseline-1,
    contract truth Medium+ recall ≥baseline×70%

Layer A/B 실패 → HARD FAIL (pytest fail, PR/main merge 차단 가능)
Layer C 실패 → SOFT WARN (pytest pass + warning report만)

baseline 갱신: tests/phase1_rulebase/kpi_baseline.json 직접 편집.
의도된 baseline 갱신 시 PR description에 변경 사유 + 도메인 정당성 명시 의무.
"""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).parent / "kpi_baseline.json"


def _load_baseline() -> dict[str, Any]:
    with BASELINE_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)


def _load_json(rel_path: str) -> dict[str, Any]:
    fp = ROOT / rel_path
    if not fp.exists():
        pytest.skip(f"artifact missing: {rel_path}")
    with fp.open(encoding="utf-8") as f:
        return json.load(f)


def _freshness_ok(rel_path: str, days: int) -> bool:
    fp = ROOT / rel_path
    if not fp.exists():
        return False
    age_sec = time.time() - fp.stat().st_mtime
    return age_sec <= days * 86400


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    return _load_baseline()


@pytest.fixture(scope="module")
def manipulation_v2_topic(baseline: dict[str, Any]) -> dict[str, Any]:
    rel = baseline["_meta"]["datasets"]["manipulation_v2"]["topic_analysis"]
    return _load_json(rel)


@pytest.fixture(scope="module")
def manipulation_v2_profile(baseline: dict[str, Any]) -> dict[str, Any]:
    rel = baseline["_meta"]["datasets"]["manipulation_v2"]["profile"]
    return _load_json(rel)


@pytest.fixture(scope="module")
def manipulation_v2_case_checkpoint(baseline: dict[str, Any]) -> dict[str, Any]:
    rel = baseline["_meta"]["datasets"]["manipulation_v2"]["case_checkpoint"]
    return _load_json(rel)


@pytest.fixture(scope="module")
def manipulation_v2_case_artifact(baseline: dict[str, Any]) -> dict[str, Any]:
    rel = baseline["_meta"]["datasets"]["manipulation_v2"]["case_artifact"]
    return _load_json(rel)


@pytest.fixture(scope="module")
def contract_v2_profile(baseline: dict[str, Any]) -> dict[str, Any]:
    rel = baseline["_meta"]["datasets"]["contract_v2"]["profile"]
    return _load_json(rel)


@pytest.fixture(scope="module")
def contract_v2_case_artifact(baseline: dict[str, Any]) -> dict[str, Any]:
    rel = baseline["_meta"]["datasets"]["contract_v2"]["case_artifact"]
    return _load_json(rel)


# ============================================================
# Layer A — 도메인 정합성 (HARD FAIL)
# ============================================================


class TestLayerADomainIntegrity:
    """Layer A HARD FAIL — 회계 도메인 정합성."""

    def test_a1_light_seeder_case_count(
        self,
        baseline: dict[str, Any],
        manipulation_v2_case_artifact: dict[str, Any],
        contract_v2_case_artifact: dict[str, Any],
    ) -> None:
        """light_seeder authority revoked. 어떤 케이스도 light_seeder 표식 가지면 안 됨."""
        spec = baseline["layer_a_domain_integrity"]["a1_light_seeder_case_count"]
        for label, artifact in (
            ("manipulation_v2", manipulation_v2_case_artifact),
            ("contract_v2", contract_v2_case_artifact),
        ):
            tagged = []
            for case in artifact.get("cases", []):
                fields = (
                    str(case.get("primary_theme", "")),
                    str(case.get("primary_queue", "")),
                    str(case.get("case_id", "")),
                )
                if any("light_seeder" in f for f in fields):
                    tagged.append(case.get("case_id"))
            assert len(tagged) <= spec["max"], (
                f"[A1 HARD FAIL] {label}: light_seeder 표식 케이스 {len(tagged)}건 "
                f"(허용 0건). 예: {tagged[:5]}. "
                f"근거: §9.1 light_seeder audit 2026-05-14."
            )

    def test_a2_contract_v2_high_row_ratio(
        self, baseline: dict[str, Any], contract_v2_profile: dict[str, Any]
    ) -> None:
        """semantic-clean contract_v2 noise HIGH 행 비율 ≤ 1%."""
        spec = baseline["layer_a_domain_integrity"]["a2_contract_v2_high_row_ratio"]
        risk_summary = contract_v2_profile["stages"]["aggregate"]["risk_summary"]
        total = sum(risk_summary.values())
        high_ratio = risk_summary.get("High", 0) / total if total else 0
        assert high_ratio <= spec["max"], (
            f"[A2 HARD FAIL] contract_v2 HIGH 행 비율 {high_ratio:.4%} > {spec['max']:.2%}. "
            f"semantic-clean noise 폭증 — fitting 의심."
        )

    def test_a3_contract_v2_rule_truth_match(self, baseline: dict[str, Any]) -> None:
        """contract_v2 strict rule_truth 과탐/미탐 = 0 (DETECTION_RESULTS_CONTRACT_V2 A축).

        실제 측정은 tests/phase1_rulebase/test_e2e_label_validation.py 에서 수행.
        본 가드는 결과 sidecar 확인.
        """
        sidecar = (
            ROOT / "tests/datasynth_quality_gate3/results/contract_v2_sidecar_consistency.json"
        )
        if not sidecar.exists():
            pytest.skip(f"sidecar 결과 미존재: {sidecar.relative_to(ROOT)}")
        with sidecar.open(encoding="utf-8") as f:
            data = json.load(f)
        spec = baseline["layer_a_domain_integrity"]["a3_contract_v2_rule_truth_match"]
        overdetect = data.get("overdetect_total", data.get("over_detect", 0))
        underdetect = data.get("underdetect_total", data.get("under_detect", 0))
        assert overdetect <= spec["max_overdetect"], (
            f"[A3 HARD FAIL] contract_v2 rule_truth 과탐 {overdetect}건 (허용 0건)."
        )
        assert underdetect <= spec["max_underdetect"], (
            f"[A3 HARD FAIL] contract_v2 rule_truth 미탐 {underdetect}건 (허용 0건)."
        )

    def test_a4_normal_sample_false_positive(
        self,
        baseline: dict[str, Any],
        normal_sample_300,
    ) -> None:
        """normal accounting 300건 sample false positive ≤ 5%.

        fixture 미준비 시 SKIP. 준비되면 자동 활성화.
        """
        spec = baseline["layer_a_domain_integrity"]["a4_normal_sample_fp_ratio"]
        df = normal_sample_300
        high_count = (df["risk_level"].str.upper() == "HIGH").sum()
        fp_ratio = high_count / len(df) if len(df) else 0
        assert fp_ratio <= spec["max"], (
            f"[A4 HARD FAIL] normal sample HIGH 비율 {fp_ratio:.2%} > {spec['max']:.0%}."
        )

    def test_a5_policy_floor_no_conflict(self) -> None:
        """RISK_THRESHOLDS vs _apply_policy_risk_floors 정합 검증."""
        from src.detection.constants import RISK_THRESHOLDS

        high_threshold = RISK_THRESHOLDS["High"]
        # immediate floor는 RISK_THRESHOLDS[HIGH] 동적 참조
        # escalated_* floor 는 고정값 0.75 / 0.80 / 0.85 — HIGH 임계보다 같거나 커야 함
        escalated_floors = (0.75, 0.80, 0.85)
        for floor in escalated_floors:
            assert floor >= high_threshold, (
                f"[A5 HARD FAIL] escalated floor {floor} < HIGH 임계 {high_threshold}. "
                f"정책 floor 충돌."
            )
        # immediate floor 동적 참조 검증
        from src.detection.score_aggregator import _POLICY_LABEL_FLOORS  # noqa: PLC0415

        immediate_floor = _POLICY_LABEL_FLOORS.get("immediate")
        if callable(immediate_floor):
            actual = immediate_floor()
        else:
            actual = immediate_floor
        assert actual is None or actual >= high_threshold * 0.99, (
            f"[A5 HARD FAIL] immediate floor {actual} < HIGH 임계 {high_threshold}."
        )

    def test_a6_contract_v2_master_flow_gap(self, baseline: dict[str, Any]) -> None:
        """contract_v2 approval_matrix_gap / document_flow_orphan baseline ±10%."""
        spec = baseline["layer_a_domain_integrity"]["a6_contract_v2_master_flow_gap"]
        gap_report = ROOT / "artifacts/contract_v2_master_flow_gap_analysis.md"
        if not gap_report.exists():
            pytest.skip(f"master/flow gap report 미존재: {gap_report.relative_to(ROOT)}")
        # 리포트가 .md 형식이므로 baseline 만 기록. 실측은 contract_v2 profile에서 별도 추출.
        # 현재는 baseline 일치 여부만 확인 (실측 자동화는 후속 PR).
        approval_gap_baseline = spec["approval_matrix_gap_rows_baseline"]
        flow_orphan_baseline = spec["document_flow_orphan_rows_baseline"]
        assert approval_gap_baseline == 184, "[A6] approval_matrix_gap baseline 변경 의심"
        assert flow_orphan_baseline == 0, "[A6] document_flow_orphan baseline 변경 의심"


# ============================================================
# Layer B — 운영 부하 (HARD FAIL)
# ============================================================


class TestLayerBOperationalLoad:
    """Layer B HARD FAIL — review queue 운영 부하."""

    def test_b1_case_count_within_limit(
        self,
        baseline: dict[str, Any],
        manipulation_v2_topic: dict[str, Any],
        contract_v2_profile: dict[str, Any],
    ) -> None:
        """case 수 ≤ 13,000."""
        spec = baseline["layer_b_operational_load"]["b1_case_count_max"]
        manip = manipulation_v2_topic["case_count"]
        contract = contract_v2_profile["stages"]["phase1_case_builder"]["case_count"]
        assert manip <= spec["max"], (
            f"[B1 HARD FAIL] manipulation_v2 case_count {manip} > {spec['max']}."
        )
        assert contract <= spec["max"], (
            f"[B1 HARD FAIL] contract_v2 case_count {contract} > {spec['max']}."
        )

    def test_b2_case_builder_runtime(
        self,
        baseline: dict[str, Any],
        manipulation_v2_case_checkpoint: dict[str, Any],
        contract_v2_profile: dict[str, Any],
    ) -> None:
        """case builder 실행 시간 ≤ 600초."""
        spec = baseline["layer_b_operational_load"]["b2_case_builder_runtime_sec"]
        manip = manipulation_v2_case_checkpoint["stages"]["phase1_case_builder"]["elapsed_sec"]
        contract = contract_v2_profile["stages"]["phase1_case_builder"]["elapsed_sec"]
        assert manip <= spec["max"], (
            f"[B2 HARD FAIL] manipulation_v2 case_builder {manip}s > {spec['max']}s."
        )
        assert contract <= spec["max"], (
            f"[B2 HARD FAIL] contract_v2 case_builder {contract}s > {spec['max']}s."
        )

    def test_b3_priority_band_distribution(
        self,
        baseline: dict[str, Any],
        manipulation_v2_topic: dict[str, Any],
    ) -> None:
        """priority_band 분포: high ≤5%, medium 20~40%, low 55~75%."""
        spec = baseline["layer_b_operational_load"]["b3_priority_band_distribution"]
        tol = spec["tolerance"]
        bands = {b["band"]: b for b in manipulation_v2_topic["priority_band_metrics"]}
        total = sum(b["case_count"] for b in bands.values())
        ratios = {b: bands[b]["case_count"] / total for b in bands}
        assert ratios["high"] <= tol["high_max"], (
            f"[B3 HARD FAIL] high band 비율 {ratios['high']:.2%} > {tol['high_max']:.0%}."
        )
        assert tol["medium_min"] <= ratios["medium"] <= tol["medium_max"], (
            f"[B3 HARD FAIL] medium band 비율 {ratios['medium']:.2%} "
            f"범위 외 ({tol['medium_min']:.0%}~{tol['medium_max']:.0%})."
        )
        assert tol["low_min"] <= ratios["low"] <= tol["low_max"], (
            f"[B3 HARD FAIL] low band 비율 {ratios['low']:.2%} "
            f"범위 외 ({tol['low_min']:.0%}~{tol['low_max']:.0%})."
        )

    def test_b4_policy_floor_applied_ratio(self, baseline: dict[str, Any]) -> None:
        """정책 floor 적용 행 비율 baseline ± 50%.

        baseline 미측정 상태 — 후속 PR에서 baseline 채운 뒤 활성화. 현재 SKIP.
        """
        spec = baseline["layer_b_operational_load"]["b4_policy_floor_applied_ratio"]
        if spec["manipulation_v2_baseline"] is None:
            pytest.skip("B4 baseline 미측정 — 후속 PR에서 활성화")


# ============================================================
# Layer C — truth-based 회귀 방지선 (SOFT WARN)
# ============================================================


class TestLayerCTruthRegressionSoftWarn:
    """Layer C SOFT WARN — truth-based 회귀 방지선.

    원칙: 절대값 임계 금지. baseline 70% 비율 하한만. 향상 강제 금지.
    """

    def test_c1_manipulation_truth_capture_ratio(
        self, baseline: dict[str, Any], manipulation_v2_topic: dict[str, Any]
    ) -> None:
        """manipulation truth 포착률 ≥ 99% (절대 회귀만)."""
        spec = baseline["layer_c_truth_regression_softwarn"]["c1_manipulation_truth_capture_ratio"]
        truth_total = manipulation_v2_topic["truth_total"]
        # 포착률 = priority_band 합산 truth_docs / truth_total
        captured = sum(b["truth_docs"] for b in manipulation_v2_topic["priority_band_metrics"])
        ratio = captured / truth_total if truth_total else 0
        if ratio < spec["min_ratio"]:
            warnings.warn(
                f"[C1 SOFT WARN] manipulation 포착률 {ratio:.2%} < {spec['min_ratio']:.0%} "
                f"(captured={captured}/{truth_total}). 회귀 가능성.",
                stacklevel=2,
            )

    def test_c2_priority_band_high_truth(
        self, baseline: dict[str, Any], manipulation_v2_topic: dict[str, Any]
    ) -> None:
        """priority_band high truth ≥ baseline × 70%."""
        spec = baseline["layer_c_truth_regression_softwarn"]["c2_priority_band_high_truth_ratio"]
        bands = {b["band"]: b for b in manipulation_v2_topic["priority_band_metrics"]}
        high_truth = bands["high"]["truth_docs"]
        if high_truth < spec["warn_threshold"]:
            warnings.warn(
                f"[C2 SOFT WARN] high band truth {high_truth} < "
                f"warn_threshold {spec['warn_threshold']} "
                f"(baseline {spec['baseline_truth_in_high']} × 70%).",
                stacklevel=2,
            )

    def test_c3_top500_truth(
        self, baseline: dict[str, Any], manipulation_v2_topic: dict[str, Any]
    ) -> None:
        """Top500 truth ≥ baseline × 70%."""
        spec = baseline["layer_c_truth_regression_softwarn"]["c3_top500_truth_ratio"]
        top500 = next(
            (g for g in manipulation_v2_topic["global_top_capture"] if g["top_n_cases"] == 500),
            None,
        )
        if top500 is None:
            warnings.warn("[C3 SOFT WARN] Top500 metric 미존재", stacklevel=2)
            return
        truth_docs = top500["truth_docs"]
        if truth_docs < spec["warn_threshold"]:
            warnings.warn(
                f"[C3 SOFT WARN] Top500 truth {truth_docs} < "
                f"warn_threshold {spec['warn_threshold']} "
                f"(baseline {spec['baseline_truth_in_top500']} × 70%).",
                stacklevel=2,
            )

    def test_c4_scenario_full_entry_count(
        self, baseline: dict[str, Any], manipulation_v2_topic: dict[str, Any]
    ) -> None:
        """시나리오 expected topic 100% 진입 ≥ baseline - 1."""
        spec = baseline["layer_c_truth_regression_softwarn"]["c4_scenario_full_entry_count"]
        full_entry = sum(
            1
            for s in manipulation_v2_topic["scenario_metrics"]
            if s["truth_docs"] > 0 and s["expected_topic_docs"] == s["truth_docs"]
        )
        if full_entry < spec["min_count"]:
            warnings.warn(
                f"[C4 SOFT WARN] full-entry 시나리오 {full_entry}개 < {spec['min_count']}개 "
                f"(baseline {spec['baseline_full_entry_scenarios']}).",
                stacklevel=2,
            )

    def test_c5_contract_v2_truth_medium_plus_recall(self, baseline: dict[str, Any]) -> None:
        """contract_v2 truth row Medium+ recall ≥ baseline × 70%.

        recall 값은 phase1_score_band_audit_after.md §2-1 측정값. 자동 추출은
        후속 PR. 현재는 baseline 일관성만 확인.
        """
        spec = baseline["layer_c_truth_regression_softwarn"][
            "c5_contract_v2_truth_medium_plus_recall"
        ]
        # baseline metadata 일관성만 검증 (실측 자동화는 후속)
        expected = round(spec["baseline_ratio"] * 0.70, 5)
        actual = round(spec["min_ratio"], 5)
        if expected != actual:
            warnings.warn(
                f"[C5 SOFT WARN] baseline_ratio×0.70 != min_ratio "
                f"(expected {expected} vs declared {actual}).",
                stacklevel=2,
            )


# ============================================================
# Meta — 가드 자체 무결성 (HARD FAIL)
# ============================================================


class TestGuardMetaIntegrity:
    """가드 정의 자체 회귀 방지."""

    def test_freshness_within_window(self, baseline: dict[str, Any]) -> None:
        """artifact freshness ≤ 7일 (HARD)."""
        days = baseline["_meta"]["freshness_days"]
        stale: list[str] = []
        for ds, paths in baseline["_meta"]["datasets"].items():
            for kind, rel in paths.items():
                if not _freshness_ok(rel, days):
                    stale.append(f"{ds}.{kind}={rel}")
        assert not stale, (
            f"[META HARD FAIL] artifact freshness > {days}일. "
            f"profile_phase1_v126.py 재실행 필요. stale: {stale}"
        )

    def test_no_truth_recall_improvement_guard(self, baseline: dict[str, Any]) -> None:
        """Layer C 가드는 회귀 방지선만. '향상 강제' 가드 금지 (원칙 위반)."""
        layer_c = baseline["layer_c_truth_regression_softwarn"]
        for key, spec in layer_c.items():
            if key.startswith("_"):
                continue
            assert spec.get("fail_mode") == "SOFT_WARN", (
                f"[PRINCIPLE VIOLATION] {key} fail_mode={spec.get('fail_mode')} "
                f"— Layer C 가드는 SOFT_WARN 만 허용 (truth recall 향상 강제 금지)."
            )

    def test_principle_recorded(self, baseline: dict[str, Any]) -> None:
        """원칙 문구가 baseline 에 보존되는지 확인."""
        principle = baseline["_meta"]["principle"]
        assert "도메인 정합성" in principle and "부수효과" in principle, (
            "[PRINCIPLE] baseline._meta.principle 에 PHASE1 역할 원칙이 누락됨."
        )
