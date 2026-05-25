"""Review queue fusion helpers.

PHASE1 composite ranker 와 PHASE2 internal ranker 를 2-way RRF 로 합성한다.
PHASE2 내부 5-family score 는 zero-preserving ECDF 기반 Noisy-OR 로 단일
PHASE2 voter 를 만든다. k 는 Cormack 2009 SIGIR default 60 으로 고정한다.

수식
    RRF_score(case) = sum(1 / (k + rank_i) for i in rankers)

설계 메모
    - rank 는 method="min" 내림차순: 동률은 같은 rank.
    - phase1_composite NaN → ValueError (PHASE1 점수는 모든 case 에 필수).
    - PHASE2 family score 0/NaN → Noisy-OR 내부에서 무신호(0 contribution) 처리.
    - 5-way/hierarchical RRF 는 V7 fixed3 측정에서 reject 되어 experimental 로 보존.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

K_DEFAULT = 60


def compute_rrf_score(
    rankers: dict[str, pd.Series] | pd.Series,
    phase2_score: pd.Series | None = None,
    k: int = K_DEFAULT,
) -> pd.DataFrame:
    """Reciprocal Rank Fusion score / rank 계산.

    Args:
        rankers: ``{"phase1_composite": Series, "phase2_unsupervised": Series, ...}``
            형태의 ranker score dict. 모든 Series 는 float64 이어야 한다.
            하위 호환을 위해 첫 번째 positional Series 도 허용한다.
        phase2_score: 하위 호환용 두 번째 positional Series. 새 호출처는 dict API 사용.
        k: RRF k. 기본 60. 호출처는 60 고정 정책.

    Returns:
        DataFrame[index=rankers 공통 index, columns=(rank_<name>..., rrf_score, rrf_rank)].
    """
    if k <= 0:
        raise ValueError(f"k must be positive: {k}")

    normalized = _normalize_rankers(rankers, phase2_score)
    _validate_rankers(normalized)

    rank_columns: dict[str, np.ndarray] = {}
    rrf_values = np.zeros(len(next(iter(normalized.values()))), dtype=np.float64)
    index = next(iter(normalized.values())).index
    for name, score in normalized.items():
        rank = score.rank(method="min", ascending=False, na_option="bottom").astype(np.int64)
        rank_columns[f"rank_{name}"] = rank.to_numpy()
        rrf_values += 1.0 / (k + rank.to_numpy(dtype=np.float64))

    rrf_score = pd.Series(rrf_values, index=index, dtype=np.float64)
    rrf_rank: pd.Series = rrf_score.rank(method="min", ascending=False).astype(np.int64)
    return pd.DataFrame(
        {**rank_columns, "rrf_score": rrf_score.to_numpy(), "rrf_rank": rrf_rank.to_numpy()},
        index=index,
    )


def _normalize_rankers(
    rankers: dict[str, pd.Series] | pd.Series,
    phase2_score: pd.Series | None,
) -> dict[str, pd.Series]:
    if isinstance(rankers, dict):
        if phase2_score is not None:
            raise TypeError("phase2_score is only valid with legacy 2-Series calls")
        return dict(rankers)
    if phase2_score is None:
        raise TypeError("compute_rrf_score requires a ranker dict or two Series")
    return {
        "phase1": rankers,
        "phase2": phase2_score,
    }


def _validate_rankers(rankers: dict[str, pd.Series]) -> None:
    if not rankers:
        raise ValueError("rankers must not be empty")
    first_name, first_series = next(iter(rankers.items()))
    if not isinstance(first_series, pd.Series):
        raise TypeError(f"ranker {first_name} must be pandas Series")
    for name, score in rankers.items():
        if not isinstance(score, pd.Series):
            raise TypeError(f"ranker {name} must be pandas Series")
        if len(score) != len(first_series):
            if {first_name, name} == {"phase1", "phase2"}:
                raise ValueError(
                    f"phase1/phase2 length mismatch: {len(first_series)} vs {len(score)}"
                )
            raise ValueError(f"ranker length mismatch: {first_name} vs {name}")
        if not score.index.equals(first_series.index):
            raise ValueError(f"ranker index mismatch: {first_name} vs {name}")
        if score.dtype != np.float64:
            legacy_name = "phase1_score" if name == "phase1" else f"{name}_score"
            raise TypeError(f"{legacy_name} must be float64: got {score.dtype}")
    if "phase1_composite" in rankers and rankers["phase1_composite"].isna().any():
        raise ValueError("phase1_composite contains NaN — PHASE1 점수는 모든 case 에 필수")
    if "phase1" in rankers and rankers["phase1"].isna().any():
        raise ValueError("phase1_score contains NaN — PHASE1 점수는 모든 case 에 필수")


# ──────────────────────────────────────────────────────────────────────────────
# PHASE2 internal Noisy-OR — 채택된 family 결합식 (2026-05-19)
#
# 식:
#   phase2_internal_noisy_or(doc) = 1 - Π_{f ∈ families} (1 - ecdf_f(doc))
#
# 의미:
#   각 family ECDF score 를 독립 anomaly 확률로 해석한 OR 결합. 0/NaN 은
#   무신호로 보존한다. 한 family 라도
#   강하게 신호 보내면 결합 점수가 높아지고, 여러 family 가 약하게 합의해도
#   누적된다. voter 형식 통일이 필요 없어 hit rate 차이가 큰 5 family 에 안전.
#
# 채택 근거:
#   V7 fixed3 alt aggregator measurement (2026-05-19) 에서 8 결합식 × 3 적용
#   비교 결과, Noisy-OR separated 만 두 baseline (VAE 단독 / PHASE1+VAE 2-way RRF)
#   모두에서 전 깊이 (TOP 100~5,000) 양수 Δ. PHASE1+VAE 대비 +1.61 ~ +8.39pp.
#
# 정합:
#   - parameter 0개, weight 0개, truth 미사용 → fitting 위험 0
#   - PHASE1 truth-recall-guard / 옵션 R / 옵션 Z 무충돌
#   - 거버넌스: docs/PHASE2_GOVERNANCE_DESIGN.md 결정 8 (Noisy-OR separated 채택)
#   - 정정 기록: docs/TROUBLESHOOT.md TS-15
#   - 측정 산출물: artifacts/phase2_family_ranking_alt_aggregators_20260519.{json,md}
# ──────────────────────────────────────────────────────────────────────────────


def to_ecdf(scores: pd.Series) -> pd.Series:
    """**Zero-preserving batch-local ECDF 변환** — Stage7 full-batch 전용.

    PHASE2 rule-style family 에서 0/NaN 은 "신호 없음"이므로 percentile 중간값으로
    올리지 않는다. 양수 score 만 positive tail 안에서 ECDF percentile 로 변환한다.

    ## ⚠ Batch-local 재현성 한계

    이 helper 는 **입력 batch 안에서** `rank(method="average", pct=True)` 를 계산한다.
    즉 동일 score 라도 batch 구성이 바뀌면 ECDF 값이 달라진다.

    | 사용 컨텍스트 | 안전한가? |
    |---|---|
    | Stage7 full-batch (V7 fixed3 41,129 case 전체) | ✅ 측정 재현 가능 |
    | filtered subset / 증분 inference | ❌ 같은 case 가 다른 점수 받음 |
    | engagement 간 비교 | ❌ 분포가 다름 |

    ## Production 권장 정책

    운영 inference 에서 재현성을 보장하려면 **학습 시 저장된 분포 ECDF** 를 사용해
    `compute_phase2_internal_noisy_or(..., already_ecdf=True)` 경로로 호출하라.
    학습 시 family ECDF 저장 위치 (예정):
    `{model_dir}/phase2_unsupervised/v{N}/family_ecdf_train_sorted.parquet`.

    현 Stage7 은 V7 fixed3 fixed-batch 측정 전용 — 매 호출 동일 41,129 case 가
    입력이므로 batch-local ECDF 라도 측정값이 변하지 않는다.

    ## 거버넌스 출처

    - `docs/PHASE2_GOVERNANCE_DESIGN.md` 결정 8 §8.3 Noisy-OR 식
    - `docs/TROUBLESHOOT.md` TS-15
    """
    numeric = pd.to_numeric(scores, errors="coerce").fillna(0.0).astype(float)
    out = pd.Series(0.0, index=scores.index, dtype=np.float64)
    positive_mask = numeric > 0.0
    if positive_mask.any():
        out.loc[positive_mask] = numeric.loc[positive_mask].rank(method="average", pct=True)
    return out


# Backwards-compatible alias — 명시적으로 batch-local ECDF 임을 호출처에서 부각시키고 싶을 때 사용.
to_batch_ecdf = to_ecdf


def compute_phase2_internal_noisy_or(
    family_scores: dict[str, pd.Series],
    *,
    already_ecdf: bool = False,
    epsilon: float = 1e-12,
) -> pd.Series:
    """5 family score 를 Noisy-OR 로 결합 — PHASE2 단일 voter.

    Args:
        family_scores: ``{family_name: row-level score Series}``. 모든 Series
            동일 index 필요. raw score 면 내부에서 ECDF 변환.
        already_ecdf: True 면 입력이 이미 [0,1] ECDF 라고 가정하고 변환 skip.
            production inference 시 학습 분포 ECDF 가 따로 저장돼 있으면 True.
        epsilon: log-space 안정성 위해 (1 - ecdf) 의 하한값.

    Returns:
        Noisy-OR 결합 점수 Series [0, 1]. 더 큰 값 = anomaly 가능성 높음.

    수식:
        result = 1 - Π_f (1 - ecdf_f)
    """
    if not family_scores:
        raise ValueError("family_scores must not be empty")
    if not 0.0 < epsilon < 1.0:
        raise ValueError(f"epsilon must be between 0 and 1: {epsilon}")

    iterator = iter(family_scores.items())
    first_name, first_series = next(iterator)
    if not isinstance(first_series, pd.Series):
        raise TypeError(f"family {first_name} score must be pandas Series")
    base_index = first_series.index

    for name, series in family_scores.items():
        if not isinstance(series, pd.Series):
            raise TypeError(f"family {name} score must be pandas Series")
        if not series.index.equals(base_index):
            raise ValueError(f"family index mismatch with first entry: {name}")

    survival = pd.Series(1.0, index=base_index, dtype=np.float64)
    for series in family_scores.values():
        ecdf = series if already_ecdf else to_ecdf(series)
        clipped = (
            pd.to_numeric(ecdf, errors="coerce")
            .fillna(0.0)
            .clip(lower=0.0, upper=1.0 - epsilon)
            .astype(np.float64)
        )
        survival = survival * (1.0 - clipped)
    survival_arr = np.asarray(survival.to_numpy(), dtype=np.float64)
    return pd.Series(1.0 - survival_arr, index=base_index, name="phase2_noisy_or")


# ──────────────────────────────────────────────────────────────────────────────
# [EXPERIMENTAL — V7 FIXED3 PRODUCTION REJECT (2026-05-19)]
#
# PHASE2 internal hierarchical RRF — Layer 2
#
# 설계 의도:
#   - active-ranker family 만 voter, coarse-booster 는 conditional 가산.
#   - parameter 0 개, fitting 위험 0 의 ranking 결합.
#
# Production reject 사유:
#   V7 fixed3 Phase C measurement-only 비교에서 TOP 100/500/1000/2000/5000
#   document recall 이 2-way (PHASE1+VAE) baseline 대비 평균 -6.45pp 손실.
#   원인: 5 family 가 동등 voter 가 아님(연속 vs 이산 vs 희소). voter 형식 통일
#   시 unsupervised 의 연속 분해능이 duplicate(binary cap) / timeseries(2값 이산)
#   / intercompany(99.997% 0) 에 의해 dilute 됨.
#
# 측정 산출물:
#   - artifacts/phase2_family_ranking_measurement_20260519.md
#   - tools/scripts/phase2_family_ranking_dry_run.py
#
# 거버넌스 결정:
#   docs/PHASE2_GOVERNANCE_DESIGN.md 결정 8 — RRF 적용 범위를 PHASE1↔VAE 같은
#   전역 연속 ranker 결합으로 제한. PHASE2 family signal 은 lane/overlay/tie-break
#   으로만 사용.
#
# 재평가 조건:
#   supervised / transformer 등 family 가 추가 활성화되어 모든 active family 가
#   연속·전역 ranker 가 될 때 본 helper 의 production 도입을 재검토.
#
# 본 helper 와 관련 tests 는 미래 재평가를 위해 보존하며,
# tests/modules/test_services/test_queue_fusion_hierarchical.py 에는
# `pytest.mark.experimental_phase2_internal_rrf` marker 가 부착되어 있다.
# ──────────────────────────────────────────────────────────────────────────────


def compute_phase2_internal_rrf(
    family_scores: dict[str, pd.Series],
    *,
    active_rankers: list[str],
    coarse_boosters: list[str] | None = None,
    phase1_scores: pd.Series | None = None,
    k: int = K_DEFAULT,
    q: float = 0.95,
) -> pd.DataFrame:
    """PHASE2 active family + coarse-booster 결합 RRF score.

    Args:
        family_scores: ``{family_name: score Series}``. 모든 Series 동일 index 필요.
        active_rankers: voter 로 사용할 family 이름들 (analysis-role active-ranker).
        coarse_boosters: booster 로만 가산할 family 이름들 (analysis-role coarse-booster).
        phase1_scores: PHASE1 composite score Series. eligible doc 판정에 사용.
            None 인 경우 active_rankers 의 q95+ 진입만 eligible 조건.
        k: RRF k. 기본 60 (Cormack 2009).
        q: booster eligibility 기준 quantile. 기본 0.95.

    Returns:
        DataFrame[index=공통 index, columns=(rank_<family>..., booster_<family>...,
        phase2_internal_rrf_score, phase2_internal_rrf_rank, coverage_breadth_q95)].

    eligible(doc) ≡ ∃ f' ∈ ACTIVE_RANKERS ∪ {phase1_composite}: score_f'(doc) ≥ q_f'.
    """
    if k <= 0:
        raise ValueError(f"k must be positive: {k}")
    if not active_rankers:
        raise ValueError("active_rankers must not be empty")
    coarse_boosters = list(coarse_boosters or [])
    _validate_family_scores(family_scores, active_rankers, coarse_boosters)

    index = next(iter(family_scores.values())).index
    n = len(index)
    if n == 0:
        return pd.DataFrame(index=index)

    eligible_mask = _compute_booster_eligibility(
        family_scores=family_scores,
        active_rankers=active_rankers,
        phase1_scores=phase1_scores,
        q=q,
    )

    columns: dict[str, np.ndarray] = {}
    rrf_values = np.zeros(n, dtype=np.float64)

    for family in active_rankers:
        rank = (
            family_scores[family]
            .rank(method="min", ascending=False, na_option="bottom")
            .astype(np.int64)
        )
        columns[f"rank_{family}"] = rank.to_numpy()
        rrf_values += 1.0 / (k + rank.to_numpy(dtype=np.float64))

    coverage_breadth = np.zeros(n, dtype=np.int64)
    for family in active_rankers:
        threshold = float(family_scores[family].quantile(q))
        coverage_breadth += (family_scores[family].to_numpy() >= threshold).astype(np.int64)

    for family in coarse_boosters:
        rank_tail = _compute_tail_rank(family_scores[family], q=q)
        columns[f"booster_{family}"] = rank_tail.to_numpy()
        contribution = np.where(
            eligible_mask & rank_tail.notna().to_numpy(),
            1.0 / (k + rank_tail.fillna(0).to_numpy(dtype=np.float64)),
            0.0,
        )
        rrf_values += contribution

    rrf_series = pd.Series(rrf_values, index=index, dtype=np.float64)
    rrf_rank = rrf_series.rank(method="min", ascending=False).astype(np.int64)
    return pd.DataFrame(
        {
            **columns,
            "phase2_internal_rrf_score": rrf_series.to_numpy(),
            "phase2_internal_rrf_rank": rrf_rank.to_numpy(),
            "coverage_breadth_q95": coverage_breadth,
        },
        index=index,
    )


def _validate_family_scores(
    family_scores: dict[str, pd.Series],
    active_rankers: list[str],
    coarse_boosters: list[str],
) -> None:
    """family_scores dict 의 형태 + family 이름 누락 검증."""
    if not family_scores:
        raise ValueError("family_scores must not be empty")
    first_name, first_series = next(iter(family_scores.items()))
    for name, score in family_scores.items():
        if not isinstance(score, pd.Series):
            raise TypeError(f"family {name} score must be pandas Series")
        if not score.index.equals(first_series.index):
            raise ValueError(f"family index mismatch: {first_name} vs {name}")
    overlap = set(active_rankers) & set(coarse_boosters)
    if overlap:
        raise ValueError(f"family appears in both active and booster sets: {overlap}")
    missing = (set(active_rankers) | set(coarse_boosters)) - set(family_scores)
    if missing:
        raise ValueError(f"unknown families in active/booster sets: {missing}")


def _compute_booster_eligibility(
    *,
    family_scores: dict[str, pd.Series],
    active_rankers: list[str],
    phase1_scores: pd.Series | None,
    q: float,
) -> np.ndarray:
    """eligible(doc) — active-ranker 또는 PHASE1 의 q95+ 진입 mask."""
    index = next(iter(family_scores.values())).index
    mask = np.zeros(len(index), dtype=bool)
    for family in active_rankers:
        threshold = float(family_scores[family].quantile(q))
        mask = mask | (family_scores[family].to_numpy() >= threshold)
    if phase1_scores is not None:
        if not phase1_scores.index.equals(index):
            raise ValueError("phase1_scores index mismatch with family scores")
        phase1_threshold = float(phase1_scores.quantile(q))
        mask = mask | (phase1_scores.to_numpy() >= phase1_threshold)
    return mask


def _compute_tail_rank(scores: pd.Series, *, q: float) -> pd.Series:
    """q+ tail 내부 rank — tail 외부는 NaN.

    booster 기여를 q95+ 진입 doc 에 한정하기 위해 tail 외부는 NaN 으로 둔다.
    """
    threshold = float(scores.quantile(q))
    if threshold <= 0.0:
        # tail 임계가 0 이면 positive 만 tail 로
        in_tail = scores > 0
    else:
        in_tail = scores >= threshold
    tail_scores = scores.where(in_tail)
    return tail_scores.rank(method="min", ascending=False, na_option="keep").astype("Float64")
