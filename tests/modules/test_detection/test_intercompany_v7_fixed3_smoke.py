"""V7-style intercompany input contract regression tests.

D065 (2026-05-23, D055 supersede) 후 기준:
- IC01 high evidence 는 group matching 실패 + master 외부 partner 조건으로 부여
- `ic_unmatched_reference` sidecar 의 detector score 직접 의존 제거
- partner_format policy (`ic_partner_regex` 등) 가 evidence level 분류 결정
"""

from __future__ import annotations

import pandas as pd

from src.detection.intercompany_matcher import IntercompanyMatcher

AUDIT_RULES = {
    "patterns": {
        "intercompany": {
            "pairs": [
                {"receivable": "1150", "payable": "2050"},
                {"receivable": "4500", "payable": "2700"},
            ],
            "partner_format": {
                "ic_partner_regex": r"^C\d{3}$",
                "customer_partner_regex": r"^C-\d+$",
                "vendor_partner_regex": r"^V-\d+$",
            },
        },
    },
}


def _v7_like_rows(*, partner_external: bool) -> pd.DataFrame:
    """V7-style fixture.

    Args:
        partner_external: True 면 receivable 의 trading_partner 를 master 외부
        회사 코드 (C999) 로 설정 — IC01 high evidence 발현 시나리오.
        False 면 master 내 회사 코드 (C002) — 매칭 시도 후 금액 차이로 IC02 hit.
    """
    partner_value = "C999" if partner_external else "C002"
    # 같은 IC 거래의 양측을 의미하므로 reference 는 동일하게 설정 (group key 정합)
    ic_reference = "JE-2024-0001"
    return pd.DataFrame(
        [
            {
                "document_id": "doc-ic-unmatched",
                "fiscal_year": 2024,
                "company_code": "C001",
                "trading_partner": partner_value,
                "counterparty_type": "IntercompanyAffiliate",
                "business_process": "Intercompany",
                "reference": ic_reference,
                "gl_account": "1150",
                "debit_amount": 1_000_000.0,
                "credit_amount": 0.0,
                "posting_date": pd.Timestamp("2024-03-01"),
                "is_intercompany": True,
            },
            {
                "document_id": "doc-ic-context",
                "fiscal_year": 2024,
                "company_code": "C002",
                "trading_partner": "C001",
                "counterparty_type": "IntercompanyAffiliate",
                "business_process": "Intercompany",
                "reference": ic_reference,
                "gl_account": "2050",
                "debit_amount": 0.0,
                "credit_amount": 500_000.0,
                "posting_date": pd.Timestamp("2024-03-01"),
                "is_intercompany": True,
            },
            {
                "document_id": "doc-non-ic",
                "fiscal_year": 2024,
                "company_code": "C001",
                "trading_partner": "V-000001",
                "counterparty_type": "VendorService",
                "business_process": "P2P",
                "reference": "JE-2024-0002",
                "gl_account": "5000",
                "debit_amount": 10_000.0,
                "credit_amount": 0.0,
                "posting_date": pd.Timestamp("2024-03-01"),
                "is_intercompany": False,
            },
        ],
    )


def _evidence_level(result) -> pd.Series:
    return result.metadata["row_sidecar"]["ic01_evidence_level"]


def test_v7_master_external_partner_feeds_ic01_high() -> None:
    """D065: master 외부 partner (C999) 는 group matching 실패 시 IC01 high 발현."""
    result = IntercompanyMatcher(audit_rules=AUDIT_RULES).detect(
        _v7_like_rows(partner_external=True),
    )

    assert "IC01" in result.details.columns
    assert "row_sidecar" in result.metadata
    # doc-ic-unmatched (idx 0): master 외부 partner → IC01 high
    assert result.details["IC01"].iloc[0] > 0
    assert _evidence_level(result).iloc[0] == "high"
    # doc-non-ic (idx 2): is_intercompany=False → IC01 0
    assert result.scores.iloc[2] == 0


def test_v7_master_internal_partner_no_ic01_high() -> None:
    """D065: master 내 partner 는 IC01 high 부여하지 않음. 금액 차이는 IC02 hit."""
    result = IntercompanyMatcher(audit_rules=AUDIT_RULES).detect(
        _v7_like_rows(partner_external=False),
    )

    assert {"IC01", "IC02", "IC03"}.issubset(result.details.columns)
    # IC01 high 부여되지 않음 (master 내 partner)
    high_mask = _evidence_level(result).eq("high")
    assert int(high_mask.sum()) == 0
    # 금액 차이 (1M vs 0.5M) → IC02 hit
    assert result.details["IC02"].max() > 0
