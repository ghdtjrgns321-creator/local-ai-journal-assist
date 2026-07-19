"""PHASE1-2 거래처 자기 큐 — partner_summary → phase1 metadata 투영 검증.

Why: 첫등장/희소/휴면 거래처는 dual(자기 큐 + 배지)이다. 배지(row_badges)만 배선돼 있고
     자기 큐(partner_summary)는 계산 후 버려지고 있었다(2026-07-15).
     단위가 거래처라 계정/프로세스 단위 macro_findings 와 **별도 큐**로 유지한다
     (UNIT_MEASUREMENT_POLICY) — 합계금액(원)과 review_score(0~1)를 한 정렬에 섞으면
     거래처가 top_n 을 독식해 Benford/D01/D02 finding 이 잘린다.
"""

from __future__ import annotations

from src.detection.phase1_case_builder import _build_partner_findings


def _summary(n: int) -> list[dict[str, object]]:
    """고액순 정렬된 partner_summary 모사 (_build_partner_summary 산출 형태)."""
    return [
        {
            "partner": f"P{i:03d}",
            "signals": ["first_seen"],
            "txn_count": n - i,
            "total_amount": float((n - i) * 1_000_000),
            "content_groups": [{"gl_account": "5101", "count": n - i}],
        }
        for i in range(n)
    ]


def test_empty_summary_yields_no_findings() -> None:
    assert _build_partner_findings([]) == []


def test_partner_findings_carry_queue_contract_fields() -> None:
    findings = _build_partner_findings(_summary(1))

    assert len(findings) == 1
    item = findings[0]
    assert item["rule_id"] == "PARTNER"
    assert item["queue_type"] == "partner_macro"
    assert item["scope"] == "trading_partner"
    assert item["trading_partner"] == "P000"
    assert item["signals"] == ["first_seen"]
    assert item["txn_count"] == 1
    assert item["total_amount"] == 1_000_000.0
    assert item["content_groups"] == [{"gl_account": "5101", "count": 1}]


def test_high_amount_order_is_preserved() -> None:
    """정렬 기준은 고액/대량 — _build_partner_summary 순서를 뒤집지 않는다."""
    findings = _build_partner_findings(_summary(5))

    amounts = [item["total_amount"] for item in findings]
    assert amounts == sorted(amounts, reverse=True)
    assert findings[0]["trading_partner"] == "P000"


def test_findings_are_never_truncated() -> None:
    """백엔드는 검토 목록을 소유하지 않는다 — 신호를 잘라내면 화면이 사라진 신호를 볼 수 없다."""
    assert len(_build_partner_findings(_summary(500))) == 500


def test_finding_id_is_unique_and_ordered() -> None:
    findings = _build_partner_findings(_summary(3))

    ids = [item["finding_id"] for item in findings]
    assert ids == ["PARTNER:0001", "PARTNER:0002", "PARTNER:0003"]
    assert len(set(ids)) == len(ids)
