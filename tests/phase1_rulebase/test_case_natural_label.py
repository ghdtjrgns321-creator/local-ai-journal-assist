"""case_natural_label — theme별 라벨이 자연어로 나오는지 검증."""

from src.export.phase1_case_label import case_natural_label


def test_logic_mismatch_label_includes_period_doctype_account():
    label = case_natural_label(
        "logic_mismatch",
        {"period_month": "2022-03", "document_type": "SA", "account_family": "500"},
        doc_count=30,
        total_amount=8_420_000_000,
    )
    assert "2022년 3월" in label
    assert "수기조정(SA)" in label
    assert "비용/원가 계정(500)" in label
    assert "30건" in label
    assert "84.2억" in label


def test_control_failure_label_uses_user_and_process():
    label = case_natural_label(
        "control_failure",
        {
            "created_by": "USR042",
            "period_month": "2022-04",
            "business_process": "Sales",
        },
        doc_count=5,
        total_amount=12_400_000,
    )
    assert "USR042" in label
    assert "2022년 4월" in label
    assert "Sales" in label
    assert "통제 위반" in label
    assert "5건" in label


def test_access_scope_review_label_includes_persona():
    label = case_natural_label(
        "access_scope_review",
        {
            "created_by": "USR077",
            "user_persona": "JUNIOR_CLERK",
            "period_month": "2022-12",
        },
        doc_count=3,
    )
    assert "USR077" in label
    assert "주니어 직원" in label
    assert "권한범위 위반" in label


def test_timing_anomaly_label_uses_window_and_account():
    label = case_natural_label(
        "timing_anomaly",
        {
            "created_by": "USR001",
            "account_family": "5",
            "period_window": "PE-5d-IN",
        },
        doc_count=8,
        total_amount=300_000_000,
    )
    assert "USR001" in label
    assert "기말 근접" in label
    assert "비용/원가" in label


def test_duplicate_or_outflow_label_includes_counterparty_and_band():
    label = case_natural_label(
        "duplicate_or_outflow",
        {
            "counterparty": "ACME Corp",
            "amount_band": "1B+",
            "near_period": "PE-7d-IN",
        },
        doc_count=4,
        total_amount=4_500_000_000,
    )
    assert "ACME Corp" in label
    assert "10억 이상" in label
    assert "중복·유출" in label
    assert "기말 근접" in label


def test_intercompany_structure_label_uses_company_pair_arrow():
    label = case_natural_label(
        "intercompany_structure",
        {
            "company_pair": "C001+C002",
            "counterparty": "C002",
            "period_month": "2022-06",
        },
        doc_count=10,
    )
    assert "C001 → C002" in label
    assert "2022년 6월" in label


def test_statistical_outlier_label_combines_process_family_period():
    label = case_natural_label(
        "statistical_outlier",
        {
            "business_process": "매출처리",
            "account_family": "4",
            "period_month": "2022-03",
        },
        doc_count=12,
    )
    assert "매출처리" in label
    assert "수익 계정(4)" in label
    assert "2022년 3월" in label
    assert "통계 이상" in label


def test_business_process_abbreviation_is_translated_to_korean():
    label = case_natural_label(
        "statistical_outlier",
        {
            "business_process": "P2P",
            "account_family": "5",
            "period_month": "2022-10",
        },
    )
    assert "구매·지급(P2P)" in label
    assert "비용/원가 계정(5)" in label
    # Why: 통계 이상 라벨은 process-family 사이를 ' · '가 아닌 공백으로 분리해
    #      "P2P-자산" 같은 어색한 하이픈을 피한다.
    assert "P2P) 비용/원가" in label


def test_label_does_not_append_count_or_amount_when_omitted():
    """case master 표는 별도 컬럼이 있으니 라벨 끝에 N건·합계가 붙으면 중복."""
    label = case_natural_label(
        "logic_mismatch",
        {"period_month": "2022-03", "document_type": "SA", "account_family": "5"},
    )
    # 끝에 ' · 30건 / 84.2억' 같은 metric suffix가 붙지 않아야 함
    assert " · " not in label.split("위반")[-1]
    assert not label.endswith("억") and not label.endswith("건")


def test_data_integrity_failure_label_falls_back_to_company_doctype():
    label = case_natural_label(
        "data_integrity_failure",
        {"company": "C001", "document_type": "SA", "load_batch": "B001"},
        doc_count=15,
    )
    assert "C001" in label
    assert "수기조정(SA)" in label
    assert "데이터 정합성 오류" in label


def test_unknown_values_are_softened_to_korean():
    label = case_natural_label(
        "control_failure",
        {
            "created_by": "UNKNOWN_USER",
            "period_month": "2022-05",
            "business_process": "UNKNOWN_PROCESS",
        },
        doc_count=2,
    )
    assert "작성자 미상" in label
    assert "프로세스 미상" in label


def test_unknown_theme_falls_back_to_joined_parts():
    label = case_natural_label(
        "totally_new_theme",
        {"a": "alpha", "b": "beta"},
        doc_count=1,
    )
    assert "alpha" in label
    assert "beta" in label


def test_amount_short_formatter_units():
    label = case_natural_label(
        "logic_mismatch",
        {"period_month": "2022-01"},
        doc_count=1,
        total_amount=1_500_000_000_000,
    )
    assert "1.5조" in label

    label2 = case_natural_label(
        "logic_mismatch",
        {"period_month": "2022-01"},
        doc_count=1,
        total_amount=12_300_000,
    )
    assert "1230만" in label2

    label3 = case_natural_label(
        "logic_mismatch",
        {"period_month": "2022-01"},
        doc_count=1,
        total_amount=4_500,
    )
    assert "4,500원" in label3
