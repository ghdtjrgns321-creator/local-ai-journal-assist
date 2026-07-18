"""라운드넘버 밀집도 — 계정·월·작성자 축별 모집단의 둥근 금액 집중을 이항검정으로 판정.

Why: PHASE1-2 자기 큐(Benford 동렬, 2026-07-15 신설). 단건 `is_round_number` 는 전표 배지이고,
     본 모듈은 "이 계정/이 달/이 사람이 통째로 둥근 금액에 쏠렸나"를 모집단 단위로 본다.
     근거 PCAOB AS2401 §61(e)(둥근 금액 명문). 점수 비병합 — row anomaly_score 무기여.

판정: baseline p = 원장 전체 round 비율. 각 그룹의 round 건수 k 를 Binomial(n, p) 단측 검정.
     baseline 을 데이터에서 뽑으므로 산업·회사별 정상 둥근 금액률 차이를 흡수한다(§3 데이터주도).
     표본이 크면 사소한 차이도 유의해지므로 effect size(excess) 하한을 함께 건다.
축별 독립: 계정/월/작성자를 복합키로 묶지 않는다 — 묶으면 그룹당 표본이 급감해 검정력이 죽는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from scipy import stats

_NULL_TOKENS: frozenset[str] = frozenset({"", "nan", "none", "null", "<na>", "nat"})


@dataclass
class RoundDensityResult:
    """축별 finding + baseline. findings 는 신호 강도(excess) 내림차순."""

    findings: list[dict[str, Any]] = field(default_factory=list)
    baseline_ratio: float = 0.0
    warnings: list[str] = field(default_factory=list)


def compute_round_density_findings(
    df: pd.DataFrame | None,
    settings: Any,
) -> RoundDensityResult:
    """GL df 에서 계정·월·작성자 축별 둥근 금액 밀집 finding 을 산출."""
    result = RoundDensityResult()
    if df is None or df.empty or "is_round_number" not in df.columns:
        result.warnings.append("is_round_number 컬럼 부재 — 라운드넘버 밀집도 스킵")
        return result

    is_round = df["is_round_number"].fillna(False).astype(bool)
    baseline = float(is_round.mean())
    result.baseline_ratio = baseline
    if not 0.0 < baseline < 1.0:
        result.warnings.append(
            f"baseline round 비율 {baseline:.4f} — 전부 둥글거나 전부 아니면 비교 기준이 없어 스킵"
        )
        return result

    min_sample = int(settings.round_density_min_sample)
    alpha = float(settings.round_density_alpha)
    strong_alpha = float(settings.round_density_strong_alpha)
    min_excess = float(settings.round_density_min_excess)

    for axis, keys in _axis_keys(df).items():
        result.findings.extend(
            _axis_findings(
                axis=axis,
                keys=keys,
                is_round=is_round,
                baseline=baseline,
                min_sample=min_sample,
                alpha=alpha,
                strong_alpha=strong_alpha,
                min_excess=min_excess,
            )
        )
    result.findings.sort(key=lambda item: (-item["excess"], -item["sample_size"]))
    return result


def _axis_keys(df: pd.DataFrame) -> dict[str, pd.Series]:
    """축별 그룹 키. 월은 posting_date 에서 파생(연-월) — 연도를 넘어 같은 달을 합치지 않는다."""
    keys: dict[str, pd.Series] = {}
    if "gl_account" in df.columns:
        keys["gl_account"] = df["gl_account"].astype(str).str.strip()
    if "posting_date" in df.columns:
        month = pd.to_datetime(df["posting_date"], errors="coerce").dt.to_period("M")
        keys["posting_month"] = month.astype(str)
    if "created_by" in df.columns:
        keys["created_by"] = df["created_by"].astype(str).str.strip()
    return keys


def _axis_findings(
    *,
    axis: str,
    keys: pd.Series,
    is_round: pd.Series,
    baseline: float,
    min_sample: int,
    alpha: float,
    strong_alpha: float,
    min_excess: float,
) -> list[dict[str, Any]]:
    valid = ~keys.str.lower().isin(_NULL_TOKENS)
    if not valid.any():
        return []
    grouped = pd.DataFrame({"key": keys[valid], "round": is_round[valid]}).groupby("key")["round"]
    stats_frame = grouped.agg(["size", "sum"])
    stats_frame = stats_frame[stats_frame["size"] >= min_sample]

    findings: list[dict[str, Any]] = []
    for key, row in stats_frame.iterrows():
        sample_size = int(row["size"])
        round_count = int(row["sum"])
        excess = round_count / sample_size - baseline
        # Why: effect size 하한을 p-value 앞에 둔다 — 표본이 크면 1%p 차이도 유의해진다.
        if excess < min_excess:
            continue
        p_value = float(
            stats.binomtest(round_count, sample_size, baseline, alternative="greater").pvalue
        )
        if p_value > alpha:
            continue
        findings.append(
            {
                "axis": axis,
                "group_key": str(key),
                "sample_size": sample_size,
                "round_count": round_count,
                "round_ratio": round_count / sample_size,
                "baseline_ratio": baseline,
                "excess": excess,
                "p_value": p_value,
                "finding_severity": "strong" if p_value <= strong_alpha else "moderate",
            }
        )
    return findings
