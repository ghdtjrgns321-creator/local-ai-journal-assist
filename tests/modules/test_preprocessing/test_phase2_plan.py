from __future__ import annotations

import pandas as pd
import pytest

from src.eda.profiler import profile_dataframe
from src.preprocessing.phase2_matrix import Phase2AutoencoderMatrixBuilder
from src.preprocessing.phase2_plan import build_phase2_preprocessing_plan


def _decisions_by_column(plan):
    return {decision.column: decision for decision in plan.decisions}


def test_phase2_preprocessing_plan_excludes_leakage_columns():
    df = pd.DataFrame(
        {
            "amount": [100.0, 200.0, 300.0],
            "risk_level": ["High", "Low", "Medium"],
            "risk_band_custom": ["A", "B", "C"],
            "rule_hit_count": [2, 0, 1],
            "model_score": [0.9, 0.1, 0.4],
            "export_status": ["ready", "ready", "blocked"],
            "dashboard_url": ["/a", "/b", "/c"],
            "is_fraud": [1, 0, 0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    assert decisions["amount"].action == "include"
    # risk_level 은 2026-07-28 부터 LEAKAGE_DENY_COLUMNS_PHASE1_OUTPUT 에 명시돼 있어
    # 이름 부분일치(leakage_risk)보다 먼저 잡힌다. 부분일치 경로는 risk_band_custom 이 지킨다.
    assert decisions["risk_level"].reason_code == "leakage_deny_column"
    assert decisions["risk_band_custom"].reason_code == "leakage_risk"
    assert decisions["rule_hit_count"].reason_code == "leakage_rule"
    assert decisions["model_score"].reason_code == "leakage_score"
    assert decisions["export_status"].reason_code == "leakage_export"
    assert decisions["dashboard_url"].reason_code == "leakage_dashboard"
    assert decisions["is_fraud"].reason_code == "leakage_label"
    assert all(
        decisions[column].action == "exclude"
        for column in (
            "risk_level",
            "risk_band_custom",
            "rule_hit_count",
            "model_score",
            "export_status",
            "dashboard_url",
            "is_fraud",
        )
    )


def test_identity_columns_use_frequency_regardless_of_cardinality():
    """이름 성격 칸은 값이 몇 종이든 빈도로 본다 — 임계에 맡기지 않는다.

    2026-07-29: 카디널리티 임계(50)가 경계에서 처리를 뒤집었다. 실측 r9 `approved_by` 는
    6만 행 표본에서 48종(원-핫 48칸), 전 행에서 60종(빈도 1칸)이었다. 승인자가 45명인
    회사와 55명인 회사가 서로 다른 전처리를 받는다는 뜻이다.
    감사에서 승인자·거래처는 "누가"보다 "얼마나 드문가"가 신호이므로 항상 빈도다.
    """
    few = pd.DataFrame({"approved_by": [f"u{i}" for i in range(5)]})
    many = pd.DataFrame({"approved_by": [f"u{i}" for i in range(200)]})

    for frame in (few, many):
        decisions = _decisions_by_column(build_phase2_preprocessing_plan(profile_dataframe(frame)))
        assert decisions["approved_by"].role == "categorical_high"
        assert decisions["approved_by"].reason_code == "domain_identity"


def test_structural_missing_column_survives_high_missing_cutoff():
    """결측이 "해당 없음"을 뜻하는 칸은 고결측 자동 제외에서 뺀다.

    `is_cleared` 는 가계정이 아닌 전표에서 물어볼 수 없는 질문이라 빈다(실측 r9 95%).
    "90% 넘게 비면 고장난 칸"이라는 규칙은 이 모양을 구분하지 못한다. 값이 있는 것 중
    미정리 건이 L3-09(가수금·가지급금 미정리)가 보는 항목이다.
    """
    values = [None] * 95 + [True] * 4 + [False]
    df = pd.DataFrame({"is_cleared": values, "other_flag": [None] * 95 + [True] * 5})

    decisions = _decisions_by_column(build_phase2_preprocessing_plan(profile_dataframe(df)))

    assert decisions["is_cleared"].action == "include"
    # 구조적 결측으로 지정하지 않은 칸은 그대로 제외된다.
    assert decisions["other_flag"].action == "exclude"
    assert decisions["other_flag"].reason_code == "high_missing"


def test_phase2_plan_allows_master_data_name_columns_but_blocks_judgment_labels():
    """`X_label` 이 마스터 데이터 명칭이면 통과, 판정 어휘가 붙으면 차단.

    2026-07-29: `auxiliary_account_label`(보조계정 명칭 — '기업다이렉트(유)')이
    이름에 `label` 이 있다는 이유로 정답 라벨로 오인돼 잘렸다. 짝인
    `auxiliary_account_number` 는 통과하고 있었다. 실 ERP 의 `gl_account_label` ·
    `cost_center_label` 도 같은 규칙에 걸리므로 접두어를 보고 가른다.
    """
    from src.preprocessing.phase2_plan import _leakage_reason

    for column in (
        "auxiliary_account_label",
        "gl_account_label",
        "cost_center_label",
        "vendor_label",
    ):
        assert _leakage_reason(column) is None, column

    for column in (
        "fraud_label",
        "anomaly_label",
        "risk_label",
        "target_label",
        "score_label",
        "label",
        "target",
    ):
        assert _leakage_reason(column) is not None, column


def test_phase2_preprocessing_plan_excludes_structural_deny_columns():
    """정답지·조작 메모·식별자·비식별화·기술 필드는 재측정과 무관하게 막힌다."""
    df = pd.DataFrame(
        {
            "document_id": ["D1", "D2", "D3"],
            "ip_address": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "line_number": [1, 2, 3],
            "mutation_type": ["a", "b", "c"],
            "operating_feature": [10.0, 11.0, 12.0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    for column in ("document_id", "ip_address", "line_number", "mutation_type"):
        assert decisions[column].action == "exclude"
    assert decisions["operating_feature"].action == "include"


def test_phase2_preprocessing_plan_releases_amount_columns():
    """금액 차단 해제 — v6 감사 근거가 r9 재측정에서 사라졌다.

    debit/credit 단독 AUROC 0.917(v6) → 0.71(r9). HARD(0.95)·SOFT(0.80) 어느 기준에도
    못 미친다. 차대변 금액은 원장의 핵심이라 근거 없는 차단을 남기는 것 자체가 결함이다.
    """
    df = pd.DataFrame(
        {
            "debit_amount": [100.0, 200.0, 300.0],
            "credit_amount": [0.0, 200.0, 100.0],
            "local_amount": [100.0, -200.0, 300.0],
            "tax_amount": [10.0, 20.0, 30.0],
            "amount_magnitude": [2.0, 2.3, 2.5],
            "days_backdated": [0, 3, 7],
            "is_round_number": [True, False, True],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    for column in df.columns:
        assert decisions[column].action == "include", column


def test_phase2_preprocessing_plan_keeps_measured_deny_and_releases_the_rest():
    """실측 차단만 남고 근거소멸한 칸은 통과한다 (2026-07-29 전수 재검).

    `near_threshold_gap_ratio` 만 SOFT 대역(문서 AUROC 0.8622)에 남았고,
    같은 계열의 gap_amount(0.7314)·approver_limit_amount(0.7008)는 근거소멸이다.
    `line_number` 는 측정과 무관하게 구조적 차단 — 전표 내 줄 위치는 감사 신호가 아니다.
    """
    df = pd.DataFrame(
        {
            "near_threshold_gap_ratio": [0.1, 0.2, 0.3],
            "near_threshold_gap_amount": [1.0, 2.0, 3.0],
            "approver_limit_amount": [10.0, 20.0, 30.0],
            "line_number": [1, 2, 3],
            "operating_feature": [10.0, 11.0, 12.0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    for column in ("near_threshold_gap_ratio", "line_number"):
        assert decisions[column].action == "exclude"
        assert decisions[column].reason_code == "leakage_deny_column"
    for column in ("near_threshold_gap_amount", "approver_limit_amount", "operating_feature"):
        assert decisions[column].action == "include"


def test_phase2_preprocessing_plan_excludes_synthetic_row_markers():
    df = pd.DataFrame(
        {
            "is_synthetic": [False, False, True],
            "is_mutated": [False, True, False],
            "operating_feature": [10.0, 11.0, 12.0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    for column in ("is_synthetic", "is_mutated"):
        assert decisions[column].action == "exclude"
        assert decisions[column].reason_code == "leakage_deny_column"
    assert decisions["operating_feature"].action == "include"


def test_phase2_preprocessing_plan_treats_account_codes_as_categorical():
    df = pd.DataFrame(
        {
            "gl_account": [1000, 1100, 1200, 1300],
            "account_code": [1000, 1100, 1200, 1300],
            "amount": [10.0, 20.0, 30.0, 40.0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df), high_card_threshold=3)
    decisions = _decisions_by_column(plan)

    for column in ("gl_account", "account_code"):
        assert decisions[column].action == "include"
        assert decisions[column].role == "categorical_high"
        assert decisions[column].reason_code == "domain_code_categorical"
    assert decisions["amount"].role == "numeric"


def test_phase2_preprocessing_plan_column_decision_snapshot():
    df = pd.DataFrame(
        {
            "customer_id": ["c1", "c2", "c3", "c4"],
            "posting_date": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
            ),
            "is_anomaly": [0, 1, 0, 0],
            "vendor_name": ["A", "B", "C", "D"],
            "amount": [100.0, 200.0, 300.0, 400.0],
            "approved": [True, False, True, True],
            "user_persona": ["manager", "controller", "manager", "junior_accountant"],
        }
    )

    plan = build_phase2_preprocessing_plan(
        profile_dataframe(df),
        high_card_threshold=3,
    )
    snapshot = {
        decision.column: {
            "role": decision.role,
            "action": decision.action,
            "reason_code": decision.reason_code,
        }
        for decision in plan.decisions
    }

    assert snapshot == {
        "customer_id": {
            "role": "identifier",
            "action": "exclude",
            "reason_code": "identifier",
        },
        "posting_date": {
            "role": "datetime",
            "action": "exclude",
            "reason_code": "datetime_raw",
        },
        "is_anomaly": {
            "role": "label",
            "action": "exclude",
            "reason_code": "leakage_label",
        },
        "vendor_name": {
            "role": "categorical_high",
            "action": "include",
            "reason_code": "high_cardinality",
        },
        "amount": {
            "role": "numeric",
            "action": "include",
            "reason_code": "numeric",
        },
        "approved": {
            "role": "boolean",
            "action": "include",
            "reason_code": "boolean",
        },
        "user_persona": {
            "role": "categorical_low",
            "action": "include",
            "reason_code": "domain_low_card",
        },
    }


def test_phase2_matrix_rejects_standalone_f_manual():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 200.0, 300.0],
            "f_manual": [True, False, True],
        }
    )
    plan = build_phase2_preprocessing_plan(profile_dataframe(df))

    with pytest.raises(ValueError, match="f_manual"):
        Phase2AutoencoderMatrixBuilder(plan).fit(df)


def test_phase2_standalone_contract_excludes_phase1_output_columns():
    """Phase 2 standalone contract: PHASE1 산출/PHASE2 자체 출력은 입력 deny."""
    df = pd.DataFrame(
        {
            # operating feature — 진입해야 함
            "amount": [100.0, 200.0, 300.0, 400.0],
            # PHASE1 case-level 산출
            "composite_sort_score": [0.7, 0.5, 0.9, 0.3],
            "topic_score_amount": [0.6, 0.4, 0.8, 0.2],
            "priority_score": [0.65, 0.42, 0.88, 0.21],
            "priority_band": ["high", "medium", "high", "low"],
            "priority_rank": [1, 2, 3, 4],
            "flagged_rules": ["L3-02", "", "L1-05,L2-03", ""],
            "review_rules": ["", "L4-01", "", ""],
            # PHASE1 row-level 산출
            "risk_level": ["High", "Low", "Medium", "Low"],
            # PHASE2 자체 출력 재투입 금지
            "anomaly_score": [0.9, 0.1, 0.4, 0.05],
            "ml_score": [0.8, 0.2, 0.5, 0.1],
            # PHASE3 산출
            "review_narrative_text": ["a", "b", "c", "d"],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    assert decisions["amount"].action == "include"
    for column in (
        "composite_sort_score",
        "topic_score_amount",
        "priority_score",
        "priority_band",
        "priority_rank",
        "flagged_rules",
        "review_rules",
        "risk_level",
        "anomaly_score",
        "ml_score",
        "review_narrative_text",
    ):
        assert decisions[column].action == "exclude", (
            f"Phase 2 standalone contract 위반: '{column}' 가 ML 입력으로 진입"
        )


def test_phase2_standalone_contract_keeps_raw_erp_priority_narrative_columns():
    """raw ERP 컬럼 (payment_priority / transaction_narrative 등) 은 deny 되면 안 됨.

    standalone contract 의 PHASE1/2/3 출력 차단은 exact name (priority_band /
    review_narrative_*) + phase{1,2,3}_/review_narrative_ prefix 로 한정한다.
    broad token deny (priority / narrative) 는 비즈니스 raw 컬럼을 함께
    막으므로 사용하지 않는다.
    """
    df = pd.DataFrame(
        {
            "payment_priority": [1, 2, 3, 1],
            "vendor_priority": ["high", "low", "medium", "high"],
            "transaction_narrative": ["abc", "def", "ghi", "jkl"],
            "shipment_narrative_code": ["X", "Y", "Z", "X"],
            "amount": [100.0, 200.0, 300.0, 400.0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    for column in (
        "payment_priority",
        "vendor_priority",
        "transaction_narrative",
        "shipment_narrative_code",
        "amount",
    ):
        assert decisions[column].action == "include", (
            f"raw ERP 컬럼 '{column}' 가 standalone deny 에 잘못 걸림"
        )


def test_phase2_matrix_allows_f_manual_interaction_feature():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 200.0, 300.0],
            "f_manual_x_amount_high": [True, False, True],
        }
    )
    plan = build_phase2_preprocessing_plan(profile_dataframe(df))

    matrix = Phase2AutoencoderMatrixBuilder(plan).fit_transform(df)

    assert "f_manual_x_amount_high" in matrix.columns
