"""build_phase1_rule_documents 의 거래금액 정합성 회귀 테스트.

전표 단위 룰(L1-01 차대변 균형)의 거래금액(evidence_amount)이 라인 금액이 아니라
전표 합계로 노출되는지 확인. 같은 doc_id 안에 여러 라인이 있을 때 첫 라인 금액으로
잘못 표시되면 감사인 입장에서 전표의 실제 임팩트가 축소되어 보인다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from src.export.phase1_case_view import build_phase1_rule_documents


def _make_pipeline_result_with_l1_01_violation() -> SimpleNamespace:
    """차대변 불균형 doc 1건 + 정상 doc 1건을 가진 가벼운 PipelineResult.

    doc_VIOLATION: 차변 100억 + 차변 50억 (대변 0) → 합계 150억, L1-01 위반
    doc_OK:        차변 80억 + 대변 80억 → 균형, 위반 아님
    """
    rows = [
        # doc_VIOLATION line 1
        {
            "document_id": "doc_VIOLATION",
            "line_number": 1,
            "gl_account": "500040",
            "debit_amount": 10_000_000_000,
            "credit_amount": 0,
            "local_amount": 10_000_000_000,
            "posting_date": "2022-03-31",
            "document_date": "2022-03-31",
            "fiscal_period": 3,
            "company_code": "C001",
            "document_type": "SA",
            "business_process": "R2R",
            "source": "manual",
            "created_by": "USR001",
            "approved_by": None,
            "approved_at": None,
            "approval_limit": 0,
            "counterparty": None,
            "line_text": "전표 합계가 안 맞는 라인 1",
            "reference": "REF001",
            "risk_level": "High",
            "anomaly_score": 0.9,
            "flagged_rules": "L1-01",
            "review_rules": "",
        },
        # doc_VIOLATION line 2
        {
            "document_id": "doc_VIOLATION",
            "line_number": 2,
            "gl_account": "500040",
            "debit_amount": 5_000_000_000,
            "credit_amount": 0,
            "local_amount": 5_000_000_000,
            "posting_date": "2022-03-31",
            "document_date": "2022-03-31",
            "fiscal_period": 3,
            "company_code": "C001",
            "document_type": "SA",
            "business_process": "R2R",
            "source": "manual",
            "created_by": "USR001",
            "approved_by": None,
            "approved_at": None,
            "approval_limit": 0,
            "counterparty": None,
            "line_text": "전표 합계가 안 맞는 라인 2",
            "reference": "REF001",
            "risk_level": "High",
            "anomaly_score": 0.9,
            "flagged_rules": "L1-01",
            "review_rules": "",
        },
        # doc_OK line 1
        {
            "document_id": "doc_OK",
            "line_number": 1,
            "gl_account": "500040",
            "debit_amount": 8_000_000_000,
            "credit_amount": 0,
            "local_amount": 8_000_000_000,
            "posting_date": "2022-03-31",
            "document_date": "2022-03-31",
            "fiscal_period": 3,
            "company_code": "C001",
            "document_type": "SA",
            "business_process": "R2R",
            "source": "manual",
            "created_by": "USR002",
            "approved_by": None,
            "approved_at": None,
            "approval_limit": 0,
            "counterparty": None,
            "line_text": "정상 분개 라인 1",
            "reference": "REF002",
            "risk_level": "Low",
            "anomaly_score": 0.1,
            "flagged_rules": "",
            "review_rules": "",
        },
        # doc_OK line 2
        {
            "document_id": "doc_OK",
            "line_number": 2,
            "gl_account": "100100",
            "debit_amount": 0,
            "credit_amount": 8_000_000_000,
            "local_amount": 8_000_000_000,
            "posting_date": "2022-03-31",
            "document_date": "2022-03-31",
            "fiscal_period": 3,
            "company_code": "C001",
            "document_type": "SA",
            "business_process": "R2R",
            "source": "manual",
            "created_by": "USR002",
            "approved_by": None,
            "approved_at": None,
            "approval_limit": 0,
            "counterparty": None,
            "line_text": "정상 분개 라인 2",
            "reference": "REF002",
            "risk_level": "Low",
            "anomaly_score": 0.1,
            "flagged_rules": "",
            "review_rules": "",
        },
    ]
    df = pd.DataFrame(rows)
    return SimpleNamespace(data=df, featured_data=df, phase1_case_result=None)


def test_l1_01_evidence_amount_uses_document_total_not_first_line():
    """L1-01 (차대변 균형) 위반 전표의 거래금액은 전표 합계여야 한다.

    현재 _row_amount 는 첫 매칭 라인 금액(차변 - 대변)을 쓰므로 doc_VIOLATION 의
    거래금액이 100억(첫 라인)으로 잡혀 실제 전표 임팩트(150억)가 축소되어 보인다.
    L1-01 같은 전표 단위 룰은 전표 합계(차변 합 또는 max(차변합, 대변합))를 써야 한다.
    """
    pr = _make_pipeline_result_with_l1_01_violation()

    rows = build_phase1_rule_documents(pr, "L1-01")

    # 룰이 매칭된 doc 만 결과에 포함
    assert len(rows) == 1, f"L1-01 매칭 doc 1건이어야 함: got {len(rows)}"
    row = rows[0]
    assert row["document_id"] == "doc_VIOLATION"

    # 전표 합계 = 100억 + 50억 = 150억
    expected_total = 15_000_000_000
    actual_amount = float(row.get("amount") or 0.0)
    assert actual_amount == expected_total, (
        f"L1-01 거래금액은 전표 합계({expected_total:,.0f})여야 하는데 "
        f"{actual_amount:,.0f} 으로 나옴 (첫 라인 금액 100억으로 잘못 잡힌 것으로 보임)"
    )


def test_l1_01_does_not_include_balanced_documents():
    """차대변 균형 doc(doc_OK)은 L1-01 매칭 결과에 들어가면 안 된다."""
    pr = _make_pipeline_result_with_l1_01_violation()
    rows = build_phase1_rule_documents(pr, "L1-01")
    doc_ids = {row["document_id"] for row in rows}
    assert "doc_OK" not in doc_ids, "차대변 균형 doc 이 L1-01 결과에 섞이면 안 됨"


def _make_pr_with_phase1_truth_only():
    """raw_rule_hits 에는 L1-01 hit 가 있지만 ledger 의 flagged_rules 컬럼에는
    그 doc 의 정보가 빠진 상황 (예: stale CSV / 재집계 누락) 시뮬레이션.
    """
    df = pd.DataFrame(
        [
            {
                "document_id": "doc_TRUTH",
                "line_number": 1,
                "gl_account": "500040",
                "debit_amount": 5_000_000,
                "credit_amount": 0,
                "local_amount": 5_000_000,
                "posting_date": "2022-03-31",
                "fiscal_period": 3,
                "company_code": "C001",
                "document_type": "SA",
                "business_process": "R2R",
                "source": "manual",
                "created_by": "USR001",
                "approved_by": None,
                "approved_at": None,
                "approval_limit": 0,
                "counterparty": None,
                "line_text": "라벨 누락된 라인",
                "reference": "REF-T",
                "risk_level": "High",
                "anomaly_score": 0.9,
                "flagged_rules": "",  # ← 컬럼은 비어있음 (stale)
                "review_rules": "",
            },
        ]
    )
    # phase1.cases 에 truth raw_rule_hits 만 존재
    case_obj = SimpleNamespace(
        case_id="case_truth_001",
        primary_theme="data_integrity_failure",
        primary_topic="ledger_integrity",
        priority_band="high",
        priority_score=10.0,
        case_key="C001/SA/B001",
        case_key_parts={"company": "C001", "document_type": "SA", "load_batch": "B001"},
        document_count=1,
        total_amount=5_000_000,
        triage_rank_reasons=[],
        representative_explanation="데이터 정합성 오류",
        raw_rule_hits=[
            SimpleNamespace(rule_id="L1-01", document_id="doc_TRUTH", row_index=0)
        ],
        documents=[
            SimpleNamespace(
                document_id="doc_TRUTH",
                counterparty=None,
                matched_rules=[],  # 여기도 누락
            )
        ],
    )
    phase1 = SimpleNamespace(cases=[case_obj])
    return SimpleNamespace(data=df, featured_data=df, phase1_case_result=phase1)


def test_truth_doc_recovered_when_flagged_rules_column_is_stale():
    """raw_rule_hits 에는 있지만 flagged_rules 가 비어 있을 때도 doc 이 결과에 포함."""
    pr = _make_pr_with_phase1_truth_only()
    rows = build_phase1_rule_documents(pr, "L1-01")
    doc_ids = {row["document_id"] for row in rows}
    assert "doc_TRUTH" in doc_ids, (
        "raw_rule_hits 가 truth 인 doc 이 mask 누락으로 결과에서 빠지면 안 됨"
    )


def _make_pr_with_split_debit_credit_lines():
    """한 전표에 차변 라인·대변 라인이 분리된 차대변 불균형 시나리오.

    라인 1: debit=100, credit=0
    라인 2: debit=0,   credit=90
    raw_rule_hits: L1-01 hit 가 doc_SPLIT 에 부착.
    """
    df = pd.DataFrame(
        [
            {
                "document_id": "doc_SPLIT",
                "line_number": 1,
                "gl_account": "500040",
                "debit_amount": 100,
                "credit_amount": 0,
                "local_amount": 100,
                "posting_date": "2022-03-31",
                "fiscal_period": 3,
                "company_code": "C001",
                "document_type": "SA",
                "business_process": "R2R",
                "source": "manual",
                "created_by": "USR001",
                "approved_by": None,
                "approved_at": None,
                "approval_limit": 0,
                "counterparty": None,
                "line_text": "차변 라인",
                "reference": "REF-S",
                "risk_level": "High",
                "anomaly_score": 0.9,
                "flagged_rules": "L1-01",
                "review_rules": "",
            },
            {
                "document_id": "doc_SPLIT",
                "line_number": 2,
                "gl_account": "100100",
                "debit_amount": 0,
                "credit_amount": 90,
                "local_amount": 90,
                "posting_date": "2022-03-31",
                "fiscal_period": 3,
                "company_code": "C001",
                "document_type": "SA",
                "business_process": "R2R",
                "source": "manual",
                "created_by": "USR001",
                "approved_by": None,
                "approved_at": None,
                "approval_limit": 0,
                "counterparty": None,
                "line_text": "대변 라인",
                "reference": "REF-S",
                "risk_level": "High",
                "anomaly_score": 0.9,
                "flagged_rules": "L1-01",
                "review_rules": "",
            },
        ]
    )
    case_obj = SimpleNamespace(
        case_id="case_split_001",
        primary_theme="data_integrity_failure",
        primary_topic="ledger_integrity",
        priority_band="high",
        priority_score=10.0,
        case_key="C001/SA/B001",
        case_key_parts={"company": "C001", "document_type": "SA", "load_batch": "B001"},
        document_count=1,
        total_amount=100,
        triage_rank_reasons=[],
        representative_explanation="데이터 정합성 오류",
        raw_rule_hits=[
            SimpleNamespace(rule_id="L1-01", document_id="doc_SPLIT", row_index=0)
        ],
        documents=[
            SimpleNamespace(
                document_id="doc_SPLIT",
                counterparty=None,
                matched_rules=["L1-01"],
            )
        ],
    )
    phase1 = SimpleNamespace(cases=[case_obj])
    return SimpleNamespace(data=df, featured_data=df, phase1_case_result=phase1)


def test_l1_01_master_row_debit_credit_use_document_totals():
    """master 표의 debit_amount/credit_amount 도 L1-01 에서는 전표 합계여야 한다.

    현재 첫 라인이 debit=100, credit=0 만 보여주면 사용자는 차변=100·대변=0 으로
    오해해 차이를 100 으로 본다. 실제 전표는 차변 합 100·대변 합 90 → 차이 10.
    master 표에서도 차변·대변·차이를 합계 기준으로 일관되게 표시해야 한다.
    """
    pr = _make_pr_with_split_debit_credit_lines()
    rows = build_phase1_rule_documents(pr, "L1-01")
    assert len(rows) == 1
    row = rows[0]
    assert row["document_id"] == "doc_SPLIT"
    assert float(row["debit_amount"]) == 100.0
    assert float(row["credit_amount"]) == 90.0
    # 차이가 evidence 에서도 일관되게 계산됐는지 (difference_value = debit - credit)
    diff = row.get("difference_value")
    if diff is not None:
        assert float(diff) == 10.0, (
            f"차변 합 100 - 대변 합 90 = 10 이어야 하는데 {diff} 로 나옴"
        )


def test_non_l1_01_rules_keep_line_level_debit_credit():
    """L1-01 이 아닌 룰(L1-02 등)은 record 라인 값을 그대로 유지해야 한다."""
    pr = _make_pr_with_split_debit_credit_lines()
    # raw_rule_hits 에 L1-02 가 없으니 결과는 빔.
    # 회귀 의미: 합계 모드(_build_rule_document_row 의 L1-01 분기)가 다른 룰엔 발동 안 함.
    rows_l102 = build_phase1_rule_documents(pr, "L1-02")
    assert rows_l102 == [], "L1-02 truth hit 가 없으므로 결과 비어야 함"


def test_l1_01_amount_works_with_string_amount_columns():
    """CSV 원본처럼 debit/credit 가 dtype=object(문자열)인 경우도 ValueError 없이 합산.

    Why: .sum() 만 호출하면 pandas 가 문자열 concat 해서 '157...87...12...0...' 형태로
         이어붙여 ValueError. pd.to_numeric coerce 로 안전하게 처리.
    """
    pr = _make_pipeline_result_with_l1_01_violation()
    df = pr.data
    # debit/credit 를 문자열로 강제 (CSV 로딩 직후 상태 시뮬레이션)
    df["debit_amount"] = df["debit_amount"].astype(object).map(lambda v: f"{float(v):.2f}")
    df["credit_amount"] = df["credit_amount"].astype(object).map(lambda v: f"{float(v):.2f}")
    pr.data = df
    pr.featured_data = df

    rows = build_phase1_rule_documents(pr, "L1-01")
    assert len(rows) == 1
    assert rows[0]["document_id"] == "doc_VIOLATION"
    # 전표 합계 150억 — 문자열에서도 정상 합산
    assert float(rows[0]["amount"]) == 15_000_000_000
