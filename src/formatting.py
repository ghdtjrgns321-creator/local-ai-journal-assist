"""Shared presentation formatters."""

from __future__ import annotations

from typing import Any

KRW_MAN = 10_000
KRW_EOK = 100_000_000
KRW_JO = 1_000_000_000_000


def format_krw_compact(
    value: Any,
    *,
    prefix: str = "",
    zero: str | None = None,
    won_suffix: bool = False,
    grouped: bool = True,
    jo_digits: int = 1,
    eok_digits: int = 1,
    man_digits: int = 0,
) -> str:
    """Format KRW-like numeric amounts using Korean compact units."""
    amount = float(value or 0)
    if amount == 0 and zero is not None:
        return zero

    sign = "-" if amount < 0 else ""
    abs_amount = abs(amount)
    group_spec = "," if grouped else ""
    if abs_amount >= KRW_JO:
        return f"{sign}{prefix}{abs_amount / KRW_JO:{group_spec}.{jo_digits}f}조"
    if abs_amount >= KRW_EOK:
        return f"{sign}{prefix}{abs_amount / KRW_EOK:{group_spec}.{eok_digits}f}억"
    if abs_amount >= KRW_MAN:
        return f"{sign}{prefix}{abs_amount / KRW_MAN:{group_spec}.{man_digits}f}만"

    suffix = "원" if won_suffix else ""
    return f"{sign}{prefix}{abs_amount:,.0f}{suffix}"
