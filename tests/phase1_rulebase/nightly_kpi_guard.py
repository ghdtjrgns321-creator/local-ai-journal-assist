"""PHASE1 nightly KPI guard — Layer A/B/C 가드 (v32/r23 baseline, 2026-06-11 재정의).

PHASE1 역할 원칙 (CLAUDE.md):
PHASE1은 fraud 확정/정답 라벨 맞히기 단계가 아니다. truth recall 향상을 강제하는
가드는 절대 추가 금지. PHASE1 향상은 도메인 정합성을 통해 자연 발생시키고,
truth recall은 부수효과(회귀 방지선)로만 측정한다.

baseline 재정의 (2026-06-11): 구 baseline(manipulation_v2/contract_v2, 2026-05-14)은
raw 데이터셋 부재 + 아티팩트 노후로 현재 코드 재검증이 불가해 퇴역했다
(kpi_baseline_legacy_20260514.json 보존 — unusual_timing ceiling 등 도메인 지식 포함).
신 baseline 데이터셋:
  - normal (현행: v41, 정상 993,152행): 정상 과탐 가드 — high/medium 케이스 0건이 기대값
  - recall (현행: r24, NORMAL v41 기반 — 39룰 × 표준 1,080 + 경계 대조군 1,080): 룰 계약 + 우선순위 회귀 방지선
측정 도구: tools/scripts/measure_phase1_current_p3_2.py (full build, extra 트랙 포함)
  + tools/scripts/analyze_truth_priority_band.py (truth→band/rank 분해)

3-Layer 구조:
  - Layer A (도메인 정합성, HARD FAIL): light_seeder=0, 정상 high/medium=0,
    recall 표준 미탐=0 + 경계 대조군 과탐=0, normal sample FP ≤5%, 정책 floor 충돌 없음,
    enrichment 지표 baseline ±10%
  - Layer B (운영 부하, HARD FAIL): case 수 상한, case builder 실행 시간 상한,
    recall priority_band 분포 형태
  - Layer C (truth-based 회귀 방지선, SOFT WARN): recall 표준 포착률 ≥99%,
    high/medium band truth ≥ baseline×70%, Top500 truth ≥ baseline×70%

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


def _load_csv(rel_path: str):
    import pandas as pd

    fp = ROOT / rel_path
    if not fp.exists():
        pytest.skip(f"artifact missing: {rel_path}")
    return pd.read_csv(fp)


def _freshness_ok(rel_path: str, days: int) -> bool:
    fp = ROOT / rel_path
    if not fp.exists():
        return False
    age_sec = time.time() - fp.stat().st_mtime
    return age_sec <= days * 86400


def _case_artifact_path(checkpoint: dict[str, Any]) -> Path:
    return Path(checkpoint["stages"]["phase1_case_builder"]["artifact_path"])


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    return _load_baseline()


@pytest.fixture(scope="module")
def normal_summary(baseline: dict[str, Any]) -> dict[str, Any]:
    return _load_json(baseline["_meta"]["datasets"]["normal"]["measurement"])


@pytest.fixture(scope="module")
def normal_checkpoint(baseline: dict[str, Any]) -> dict[str, Any]:
    return _load_json(baseline["_meta"]["datasets"]["normal"]["checkpoint"])


@pytest.fixture(scope="module")
def recall_summary(baseline: dict[str, Any]) -> dict[str, Any]:
    return _load_json(baseline["_meta"]["datasets"]["recall"]["measurement"])


@pytest.fixture(scope="module")
def recall_checkpoint(baseline: dict[str, Any]) -> dict[str, Any]:
    return _load_json(baseline["_meta"]["datasets"]["recall"]["checkpoint"])


@pytest.fixture(scope="module")
def recall_truth_band(baseline: dict[str, Any]) -> dict[str, Any]:
    return _load_json(baseline["_meta"]["datasets"]["recall"]["truth_band"])


@pytest.fixture(scope="module")
def recall_truth_measurement(baseline: dict[str, Any]):
    return _load_csv(baseline["_meta"]["datasets"]["recall"]["truth_measurement"])


# ============================================================
# Layer A — 도메인 정합성 (HARD FAIL)
# ============================================================


class TestLayerADomainIntegrity:
    """Layer A HARD FAIL — 회계 도메인 정합성."""

    def test_a1_light_seeder_case_count(
        self,
        baseline: dict[str, Any],
        normal_checkpoint: dict[str, Any],
        recall_checkpoint: dict[str, Any],
    ) -> None:
        """light_seeder authority revoked. 어떤 케이스도 light_seeder 표식 가지면 안 됨."""
        spec = baseline["layer_a_domain_integrity"]["a1_light_seeder_case_count"]
        for label, checkpoint in (
            ("normal", normal_checkpoint),
            ("recall", recall_checkpoint),
        ):
            artifact_path = _case_artifact_path(checkpoint)
            if not artifact_path.exists():
                pytest.skip(f"case artifact missing: {artifact_path}")
            with artifact_path.open(encoding="utf-8") as fp:
                artifact = json.load(fp)
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
                f"(허용 0건). 예: {tagged[:5]}. 근거: §9.1 light_seeder audit 2026-05-14."
            )

    def test_a2_normal_high_medium_cases(
        self, baseline: dict[str, Any], normal_summary: dict[str, Any]
    ) -> None:
        """정상 데이터 high/medium priority case = 0 (운영 과탐 0).

        근거: PHASE1_OPEN_ISSUES 우선순위 1 — 광역 row 발화는 검토모집단이며
        priority에서 low로 차등되어야 한다. 정상이 high/medium에 오르면 과탐.
        """
        spec = baseline["layer_a_domain_integrity"]["a2_normal_high_medium_cases"]
        bands = normal_summary["priority_band_cases"]
        assert bands.get("high", 0) <= spec["max_high"], (
            f"[A2 HARD FAIL] normal high band case {bands.get('high')}건 "
            f"(허용 {spec['max_high']}건). 정상 데이터 운영 과탐."
        )
        assert bands.get("medium", 0) <= spec["max_medium"], (
            f"[A2 HARD FAIL] normal medium band case {bands.get('medium')}건 "
            f"(허용 {spec['max_medium']}건). 정상 데이터 운영 과탐."
        )

    def test_a3_recall_rule_contract(
        self, baseline: dict[str, Any], recall_truth_measurement
    ) -> None:
        """recall 룰 계약: case-레인 표준 위반 미탐 0 + 경계 대조군 detector 직접 과탐 0.

        주의 1: fixture 리콜(룰 구동 증명)이지 현실 부정 리콜이 아니다
        (PHASE1_VERIFICATION.md §1 순환 구조 경고). 회귀 방지 목적으로만 사용.
        주의 2: surface 레인이 case가 아닌 룰은 제외한다 — L4-02(macro finding 레인,
        전건 macro로 표면화 확인), D01/D02(review 신호 미표면 — OPEN_ISSUES #5 해소 전까지
        측정 불가). 제외 목록은 baseline spec(excluded_rules)으로 관리.
        주의 3: 경계 대조군은 direct_rule_hit 기준 — case '동승'(같은 룰이 다른 문서에서
        발화한 case에 경계 문서가 구성원 포함)은 detector 과탐이 아니다.
        """
        spec = baseline["layer_a_domain_integrity"]["a3_recall_rule_contract"]
        df = recall_truth_measurement
        excluded = set(spec.get("excluded_rules", []))
        standard = df[df["case_kind"].eq("standard") & ~df["rule_id"].isin(sorted(excluded))]
        boundary = df[df["case_kind"].eq("boundary_control")]
        # Why: excluded_rules 과잉 확장으로 표본이 비어 trivially pass 되는 것 차단 (hollow-PASS)
        assert len(standard) >= spec["baseline_standard_total_after_exclusion"], (
            f"[A3 HARD FAIL] 제외 후 표준 표본 {len(standard)}건 < baseline "
            f"{spec['baseline_standard_total_after_exclusion']}건 — excluded_rules 과잉 확장 의심."
        )
        missed = int((~standard["caught"]).sum())
        boundary_direct = int(boundary["direct_rule_hit"].sum())
        assert missed <= spec["max_standard_missed"], (
            f"[A3 HARD FAIL] recall 표준 위반 미탐 {missed}건 (허용 0건, 제외 룰 {sorted(excluded)}). "
            f"미탐 룰: {sorted(standard.loc[~standard['caught'], 'rule_id'].unique())}"
        )
        assert boundary_direct <= spec["max_boundary_direct_hit"], (
            f"[A3 HARD FAIL] recall 경계 대조군 detector 직접 과탐 {boundary_direct}건 (허용 0건). "
            f"과탐 룰: {sorted(boundary.loc[boundary['direct_rule_hit'], 'rule_id'].unique())}"
        )

    def test_a4_normal_sample_false_positive(
        self,
        baseline: dict[str, Any],
        normal_sample_300,
    ) -> None:
        """normal accounting 300건 sample false positive ≤ 5%."""
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
        escalated_floors = (0.75, 0.80, 0.85)
        for floor in escalated_floors:
            assert floor >= high_threshold, (
                f"[A5 HARD FAIL] escalated floor {floor} < HIGH 임계 {high_threshold}. "
                f"정책 floor 충돌."
            )
        from src.detection.score_aggregator import _POLICY_LABEL_FLOORS  # noqa: PLC0415

        immediate_floor = _POLICY_LABEL_FLOORS.get("immediate")
        actual = immediate_floor() if callable(immediate_floor) else immediate_floor
        assert actual is None or actual >= high_threshold * 0.99, (
            f"[A5 HARD FAIL] immediate floor {actual} < HIGH 임계 {high_threshold}."
        )

    def test_a6_enrichment_drift(
        self, baseline: dict[str, Any], normal_checkpoint: dict[str, Any]
    ) -> None:
        """normal 독립 evidence enrichment 지표 baseline ±10% (master/flow 회귀 방지)."""
        spec = baseline["layer_a_domain_integrity"]["a6_enrichment_drift"]
        stage = normal_checkpoint["stages"]["independent_evidence_enrichment"]
        tol = spec["tolerance_ratio"]
        for metric, base_value in spec["baselines"].items():
            actual = int(stage.get(metric, -1))
            if base_value == 0:
                assert actual == 0, f"[A6 HARD FAIL] {metric}={actual} (baseline 0, 변동 불허)."
                continue
            drift = abs(actual - base_value) / base_value
            assert drift <= tol, (
                f"[A6 HARD FAIL] {metric}={actual} vs baseline {base_value} "
                f"(drift {drift:.2%} > ±{tol:.0%})."
            )


# ============================================================
# Layer B — 운영 부하 (HARD FAIL)
# ============================================================


class TestLayerBOperationalLoad:
    """Layer B HARD FAIL — review queue 운영 부하."""

    def test_b1_case_count_within_limit(
        self,
        baseline: dict[str, Any],
        normal_summary: dict[str, Any],
        recall_summary: dict[str, Any],
    ) -> None:
        """case 수 상한 (review queue 운영 가능 규모, ~1M행 기준)."""
        spec = baseline["layer_b_operational_load"]["b1_case_count_max"]
        normal = normal_summary["phase1_case_count"]
        recall = recall_summary["phase1_case_count"]
        assert normal <= spec["max"], (
            f"[B1 HARD FAIL] normal case_count {normal} > {spec['max']}."
        )
        assert recall <= spec["max"], (
            f"[B1 HARD FAIL] recall case_count {recall} > {spec['max']}."
        )

    def test_b2_case_builder_runtime(
        self,
        baseline: dict[str, Any],
        normal_checkpoint: dict[str, Any],
        recall_checkpoint: dict[str, Any],
    ) -> None:
        """case builder 실행 시간 상한 (O(n²) 회귀 방지 — VERIFICATION_20260608 perf 수정)."""
        spec = baseline["layer_b_operational_load"]["b2_case_builder_runtime_sec"]
        for label, checkpoint in (
            ("normal", normal_checkpoint),
            ("recall", recall_checkpoint),
        ):
            elapsed = checkpoint["stages"]["phase1_case_builder"]["elapsed_sec"]
            assert elapsed <= spec["max"], (
                f"[B2 HARD FAIL] {label} case_builder {elapsed}s > {spec['max']}s."
            )

    def test_b3_priority_band_distribution(
        self,
        baseline: dict[str, Any],
        recall_summary: dict[str, Any],
    ) -> None:
        """recall priority_band 분포 형태 (high 폭증/low 소실 차단)."""
        spec = baseline["layer_b_operational_load"]["b3_priority_band_distribution"]
        tol = spec["tolerance"]
        bands = recall_summary["priority_band_cases"]
        total = sum(bands.values())
        assert total > 0, "[B3 HARD FAIL] priority_band_cases 비어 있음 (hollow)."
        high_ratio = bands.get("high", 0) / total
        low_ratio = bands.get("low", 0) / total
        assert high_ratio <= tol["high_max"], (
            f"[B3 HARD FAIL] recall high band 비율 {high_ratio:.2%} > {tol['high_max']:.0%}."
        )
        assert low_ratio >= tol["low_min"], (
            f"[B3 HARD FAIL] recall low band 비율 {low_ratio:.2%} < {tol['low_min']:.0%}."
        )


# ============================================================
# Layer C — truth-based 회귀 방지선 (SOFT WARN)
# ============================================================


class TestLayerCTruthRegressionSoftWarn:
    """Layer C SOFT WARN — truth-based 회귀 방지선.

    원칙: 절대값 임계 금지. baseline 70% 비율 하한만. 향상 강제 금지.
    """

    def test_c1_standard_capture_ratio(
        self, baseline: dict[str, Any], recall_truth_measurement
    ) -> None:
        """recall 표준 위반 포착률 ≥ 99% (절대 회귀만, case-레인 룰 한정 — a3와 동일 제외)."""
        spec = baseline["layer_c_truth_regression_softwarn"]["c1_standard_capture_ratio"]
        df = recall_truth_measurement
        excluded = set(spec.get("excluded_rules", []))
        standard = df[df["case_kind"].eq("standard") & ~df["rule_id"].isin(sorted(excluded))]
        ratio = standard["caught"].mean() if len(standard) else 0.0
        if ratio < spec["min_ratio"]:
            warnings.warn(
                f"[C1 SOFT WARN] recall 표준 포착률 {ratio:.2%} < {spec['min_ratio']:.0%} "
                f"({int(standard['caught'].sum())}/{len(standard)}). 회귀 가능성.",
                stacklevel=2,
            )

    def test_c2_high_medium_band_truth(
        self, baseline: dict[str, Any], recall_truth_band: dict[str, Any]
    ) -> None:
        """recall 표준 truth의 high+medium band 진입 ≥ baseline × 70%."""
        spec = baseline["layer_c_truth_regression_softwarn"]["c2_high_medium_band_truth"]
        dist = recall_truth_band["standard_band_distribution"]
        high_medium = int(dist.get("high", 0)) + int(dist.get("medium", 0))
        if high_medium < spec["warn_threshold"]:
            warnings.warn(
                f"[C2 SOFT WARN] recall high+medium band truth {high_medium} < "
                f"warn_threshold {spec['warn_threshold']} "
                f"(baseline {spec['baseline_high_medium_truth']} × 70%).",
                stacklevel=2,
            )

    def test_c3_top500_truth(
        self, baseline: dict[str, Any], recall_truth_band: dict[str, Any]
    ) -> None:
        """recall Top500 case rank 내 truth ≥ baseline × 70%."""
        spec = baseline["layer_c_truth_regression_softwarn"]["c3_top500_truth"]
        top500 = int(recall_truth_band["standard_top_n_truth"]["top500"])
        if top500 < spec["warn_threshold"]:
            warnings.warn(
                f"[C3 SOFT WARN] recall Top500 truth {top500} < "
                f"warn_threshold {spec['warn_threshold']} "
                f"(baseline {spec['baseline_truth_in_top500']} × 70%).",
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
            f"measure_phase1_current_p3_2.py + analyze_truth_priority_band.py 재실행 필요. "
            f"stale: {stale}"
        )

    def test_a4_fixture_integrity(self) -> None:
        """A4 fixture 무결성 — 파일 부재/스키마 결손이 skip(=hollow-PASS)으로 둔갑하는 것 차단.

        Why: conftest의 normal_sample_300 fixture는 파일/컬럼 부재 시 pytest.skip 하므로
        A4 HARD 가드가 조용히 무력화될 수 있다 (code review M1). 여기서 FAIL로 강제.
        """
        import pandas as pd

        fixture = ROOT / "data/journal/test_normal_sample/normal_sample_300.csv"
        assert fixture.exists(), (
            "[META HARD FAIL] A4 fixture 부재 — data/journal/test_normal_sample/"
            "normal_sample_300.csv. A4 정상 과탐 가드가 silent skip으로 무력화된다."
        )
        columns = pd.read_csv(fixture, nrows=1).columns
        assert "risk_level" in columns, (
            "[META HARD FAIL] A4 fixture에 risk_level 컬럼 없음 — A4 가드 무력화."
        )

    def test_extra_detectors_ran_without_error(
        self,
        normal_checkpoint: dict[str, Any],
        recall_checkpoint: dict[str, Any],
    ) -> None:
        """측정 하니스 extra 트랙(evidence/IC/graph/variance) 오류가 측정 누락으로 둔갑 차단.

        Why: _run_extra_detectors는 detector별 예외를 checkpoint의 error 키로만 기록하고
        넘어가므로, 오류 시 해당 룰들이 '발화 0'으로 측정된다 (code review M2). 가드가
        소비하는 측정 아티팩트는 extra 트랙이 전부 정상 실행된 것이어야 한다.
        """
        for label, checkpoint in (
            ("normal", normal_checkpoint),
            ("recall", recall_checkpoint),
        ):
            stage = checkpoint.get("stages", {}).get("extra_detectors", {})
            assert stage, (
                f"[META HARD FAIL] {label}: extra_detectors 스테이지 부재 — "
                f"측정 도구가 4트랙만 실행한 구버전 아티팩트."
            )
            errored = {
                name: info.get("error")
                for name, info in stage.items()
                if isinstance(info, dict) and "error" in info
            }
            assert not errored, (
                f"[META HARD FAIL] {label}: extra detector 실행 오류 — {errored}. "
                f"해당 트랙 룰들이 측정에서 조용히 누락된 상태."
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
