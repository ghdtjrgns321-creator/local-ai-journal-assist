"""TB01(부호 편향), TB02(범위 극단) 순수 함수.

Why: ISA 540 소급 검토에 따른 회계추정치 편의(bias) 탐지.
     두 룰 모두 다기간 시계열 데이터(MultiYearEstimates)를 입력받아
     계정 단위로 편향 여부를 판정한다. df와 무관한 순수 함수로 테스트 용이.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Why: estimation error가 이 값 이하이면 "변동 없음"으로 간주.
#      원 단위 기준. float 연산 오차 방어.
_EPSILON = 1.0


def tb01_sign_bias(
    estimation_errors: dict[str, list[float]],
    *,
    min_periods: int = 2,
    bias_ratio_threshold: float = 0.8,
) -> dict[str, dict[str, Any]]:
    """TB01 부호 편향: estimation error의 부호가 일관되게 한 방향이면 bias 의심.

    Why: ISA 540 소급 검토 — "추정치 오차가 이익을 증가시키는 방향으로 편향"
         estimation_error[t] = total_credit[t-1] - total_debit[t]
         음수 지속 = 전기 설정(추정치)이 당기 사용보다 부족 = 이익 방향 과소 추정

    Args:
        estimation_errors: {gl_account: [error_y1, error_y2, ...]} 연도순.
        min_periods: 판정에 필요한 최소 nonzero error 수.
        bias_ratio_threshold: 동일 부호 비율 임계값 (0.8 = 5개 중 4개).

    Returns:
        {gl_account: {"flagged": bool, "sign_ratio": float,
                       "dominant_sign": str, "n_periods": int, ...}}
    """
    results: dict[str, dict[str, Any]] = {}

    for account, errors in estimation_errors.items():
        # Why: error=0은 변동 없음 → 편향 판단 불가. abs(e) <= _EPSILON 제외.
        nonzero = [e for e in errors if abs(e) > _EPSILON]

        if len(nonzero) < min_periods:
            results[account] = {
                "flagged": False,
                "reason": "insufficient_data",
                "n_periods": len(nonzero),
            }
            continue

        positive_count = sum(1 for e in nonzero if e > 0)
        negative_count = len(nonzero) - positive_count

        if positive_count >= negative_count:
            dominant_sign = "positive"
            sign_ratio = positive_count / len(nonzero)
        else:
            dominant_sign = "negative"
            sign_ratio = negative_count / len(nonzero)

        flagged = sign_ratio >= bias_ratio_threshold

        results[account] = {
            "flagged": flagged,
            "sign_ratio": round(sign_ratio, 4),
            "dominant_sign": dominant_sign,
            "n_periods": len(nonzero),
            "positive_count": positive_count,
            "negative_count": negative_count,
        }

    return results


def tb02_range_extremity(
    provision_amounts: dict[str, list[float]],
    *,
    min_periods: int = 3,
    extremity_quantile: float = 0.1,
) -> dict[str, dict[str, Any]]:
    """TB02 범위 극단: 경영진 추정치(설정액)의 증감 방향이 단조적으로 일관.

    Why: ISA 540 — "경영진의 포인트 추정치가 합리적 범위의 극단에 일관 위치"
         provision_amounts는 total_credit[t] 시계열로, 상각(debit)으로
         오염되지 않은 순수 경영진 의사결정 추세만 분석한다.
         연도간 증감(diff)의 방향 일관성으로 단조 추세를 탐지.
         매년 설정액이 줄어드는 패턴 → 이익 편향 의심.

    Args:
        provision_amounts: {gl_account: [amount_y1, amount_y2, ...]} 연도순.
        min_periods: 최소 기간 수 (diff 산출에 최소 2개 필요).
        extremity_quantile: 같은 방향 비율 판정 임계 보정값 (0.1 → 90%).

    Returns:
        {gl_account: {"flagged": bool, "trend_ratio": float,
                       "direction": str, ...}}
    """
    results: dict[str, dict[str, Any]] = {}

    for account, amounts in provision_amounts.items():
        if len(amounts) < min_periods:
            results[account] = {
                "flagged": False,
                "reason": "insufficient_data",
                "n_periods": len(amounts),
            }
            continue

        # Why: 연도간 증감(diff) 산출. diff > 0 = 설정 증가, diff < 0 = 설정 감소.
        diffs = [amounts[i] - amounts[i - 1] for i in range(1, len(amounts))]

        # Why: _EPSILON 이하 변동은 무시 (float 오차 + 실질적 무변동)
        positive_diffs = sum(1 for d in diffs if d > _EPSILON)
        negative_diffs = sum(1 for d in diffs if d < -_EPSILON)
        total_nonzero = positive_diffs + negative_diffs

        if total_nonzero == 0:
            results[account] = {
                "flagged": False,
                "reason": "no_variation",
                "n_periods": len(amounts),
            }
            continue

        # Why: 같은 방향 비율이 높으면 단조 추세 → 편향 의심.
        #      예: 설정액이 4년 연속 감소 → negative 4/4 = 1.0 → 플래그.
        dominant_count = max(positive_diffs, negative_diffs)
        trend_ratio = dominant_count / total_nonzero

        if positive_diffs > negative_diffs:
            direction = "upper"  # 보수적: 매년 설정액 증가
        elif negative_diffs > positive_diffs:
            direction = "lower"  # 공격적: 매년 설정액 감소 = 이익 편향
        else:
            direction = "mixed"

        flagged = trend_ratio >= (1.0 - extremity_quantile)

        results[account] = {
            "flagged": flagged,
            "trend_ratio": round(trend_ratio, 4),
            "direction": direction,
            "positive_diffs": positive_diffs,
            "negative_diffs": negative_diffs,
            "n_periods": len(amounts),
        }

    return results
