"""EDA 대시보드 요약 — EDAProfile → 렌더링 가능한 dict.

Phase 1c 대시보드 EDA 탭의 데이터 소스.
quality_score: 결측률·중복률 기반 0~100점 품질 지표.
warnings: 사용자 주의가 필요한 데이터 품질 이슈 목록.
"""

from __future__ import annotations

from src.eda.models import EDAProfile

# 경고 생성 기준값
_MISSING_WARN_THRESHOLD = 0.10  # 결측률 10% 이상
_HIGH_CARDINALITY_THRESHOLD = 100  # 카디널리티 100 이상
_DUPLICATE_WARN_THRESHOLD = 0.05  # 중복률 5% 이상
_OUTLIER_WARN_THRESHOLD = 0.05  # 이상치 비율 5% 이상


def summarize_for_dashboard(profile: EDAProfile) -> dict:
    """EDAProfile → 대시보드 렌더링용 요약 dict.

    Returns
    -------
    dict with keys: overview, quality_score, warnings,
                    column_summaries, missing_heatmap_data, numeric_stats_table
    """
    overview = _build_overview(profile)
    warnings = _generate_warnings(profile)
    quality_score = _calculate_quality_score(profile)
    column_summaries = _build_column_summaries(profile)
    missing_heatmap = {col: cp.missing_rate for col, cp in profile.columns.items()}
    numeric_table = _build_numeric_stats_table(profile)

    return {
        "overview": overview,
        "quality_score": round(quality_score, 1),
        "warnings": warnings,
        "column_summaries": column_summaries,
        "missing_heatmap_data": missing_heatmap,
        "numeric_stats_table": numeric_table,
    }


def _build_overview(profile: EDAProfile) -> dict:
    """전체 수준 요약."""
    return {
        "total_rows": profile.total_rows,
        "total_columns": profile.total_columns,
        "memory_mb": round(profile.memory_bytes / (1024 * 1024), 2),
        "duplicate_rows": profile.duplicate_rows,
        "sampled": profile.sampled,
    }


def _calculate_quality_score(profile: EDAProfile) -> float:
    """데이터 품질 점수 (0~100).

    감점 요소:
    - 평균 결측률 × 40점 (결측은 가장 큰 품질 저하)
    - 중복률 × 30점
    - 고결측 컬럼 비율 × 30점 (50%+ 결측 컬럼)
    """
    if profile.total_rows == 0 or not profile.columns:
        return 0.0

    # 평균 결측률
    missing_rates = [cp.missing_rate for cp in profile.columns.values()]
    avg_missing = sum(missing_rates) / len(missing_rates) if missing_rates else 0

    # 중복률
    dup_rate = profile.duplicate_rows / profile.total_rows

    # 고결측 컬럼 비율 (50% 이상 결측)
    high_missing_cols = sum(1 for r in missing_rates if r >= 0.5)
    high_missing_rate = high_missing_cols / len(missing_rates) if missing_rates else 0

    score = 100.0
    score -= avg_missing * 40
    score -= dup_rate * 30
    score -= high_missing_rate * 30

    return max(0.0, min(100.0, score))


def _generate_warnings(profile: EDAProfile) -> list[str]:
    """데이터 품질 경고 목록 생성."""
    warnings: list[str] = []

    if profile.total_rows == 0:
        warnings.append("데이터가 비어 있습니다.")
        return warnings

    # 중복행 경고
    dup_rate = profile.duplicate_rows / profile.total_rows
    if dup_rate >= _DUPLICATE_WARN_THRESHOLD:
        warnings.append(f"중복행 {profile.duplicate_rows}건 ({dup_rate:.1%}) — L1-02 룰 확인 필요")

    for col, cp in profile.columns.items():
        # 고결측 경고
        if cp.missing_rate >= _MISSING_WARN_THRESHOLD:
            warnings.append(f"'{col}' 결측률 {cp.missing_rate:.1%} — 결측치 처리 필요")
        # 고카디널리티 경고
        if cp.cardinality is not None and cp.cardinality >= _HIGH_CARDINALITY_THRESHOLD:
            warnings.append(f"'{col}' 카디널리티 {cp.cardinality} — TargetEncoder 권장")
        # 이상치 경고
        if (
            cp.outlier_count is not None
            and profile.total_rows > 0
            and cp.outlier_count / profile.total_rows >= _OUTLIER_WARN_THRESHOLD
        ):
            warnings.append(f"'{col}' 이상치 {cp.outlier_count}건 — IQR 기준 확인 필요")

    return warnings


def _build_column_summaries(profile: EDAProfile) -> list[dict]:
    """컬럼별 요약 카드 데이터."""
    summaries = []
    for col, cp in profile.columns.items():
        highlights = _column_highlights(cp)
        summaries.append(
            {
                "name": col,
                "dtype_group": cp.dtype_group,
                "missing_rate": cp.missing_rate,
                "highlights": highlights,
            }
        )
    return summaries


def _column_highlights(cp) -> str:
    """컬럼 유형별 핵심 정보 한 줄 요약."""
    if cp.dtype_group == "numeric":
        if cp.mean is not None and cp.std is not None:
            return f"mean={cp.mean:,.1f}, std={cp.std:,.1f}"
        return "전체 결측"
    if cp.dtype_group == "categorical":
        return f"카디널리티={cp.cardinality or 0}"
    if cp.dtype_group == "datetime":
        if cp.min_date:
            return f"{cp.min_date[:10]} ~ {cp.max_date[:10]}"
        return "전체 NaT"
    if cp.dtype_group == "boolean":
        if cp.true_rate is not None:
            return f"true={cp.true_rate:.1%}"
        return "전체 결측"
    return ""


def _build_numeric_stats_table(profile: EDAProfile) -> list[dict]:
    """수치형 컬럼 통계 테이블 (대시보드 테이블 렌더링용)."""
    rows = []
    for col, cp in profile.columns.items():
        if cp.dtype_group != "numeric" or cp.mean is None:
            continue
        rows.append(
            {
                "column": col,
                "mean": cp.mean,
                "median": cp.median,
                "std": cp.std,
                "min": cp.min_val,
                "max": cp.max_val,
                "q1": cp.q1,
                "q3": cp.q3,
                "outlier_count": cp.outlier_count,
            }
        )
    return rows
