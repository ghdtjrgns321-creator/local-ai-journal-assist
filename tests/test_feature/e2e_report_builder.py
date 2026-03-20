"""E2E 테스트 결과 MD 리포트 생성기."""

from __future__ import annotations

import pandas as pd

from src.feature.engine import EXPECTED_COLUMNS, FeatureResult

ALL_FEATURES = [col for cols in EXPECTED_COLUMNS.values() for col in cols]

# 금액 컬럼 의존 피처 — debit/credit 미매핑 시 미생성이 정상
_AMOUNT_DEPENDENT = {
    *EXPECTED_COLUMNS["amount"],
    "first_digit",  # pattern이지만 내부적으로 금액 사용
}


def build_report(
    df: pd.DataFrame,
    result: FeatureResult,
    row_count: int,
    elapsed: float,
    *,
    title: str = "DataSynth",
    missing_required: list[str] | None = None,
) -> str:
    """E2E 결과를 MD 문자열로 생성."""
    L: list[str] = []  # noqa: N806
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    missing_req = missing_required or []

    # Why: debit/credit 미매핑이면 amount 계열 미생성은 "의도된 동작"
    amount_unavailable = (
        "debit_amount" in missing_req or "credit_amount" in missing_req
    )

    # ── 1. 요약 ──
    L.append(f"# {title} E2E 테스트 결과 (ingest → feature)\n")
    L.append(f"> 실행일: {now}\n")
    L.append("## 1. 요약\n")
    L.append("| 항목           | 값                          |")
    L.append("|:---------------|:----------------------------|")
    L.append(f"| 입력 행수      | {row_count:,}               |")
    L.append(f"| 소요시간       | {elapsed:.2f}s              |")
    L.append(f"| 생성 피처      | {len(result.added_columns)}/18 |")
    if result.failed_categories:
        L.append(f"| 성공 카테고리  | {', '.join(result.categories_run)} |")
        L.append(f"| 실패 카테고리  | {', '.join(result.failed_categories)} |")
    else:
        L.append(f"| 카테고리 실행  | {', '.join(result.categories_run)} |")
    if missing_req:
        L.append(f"| 필수 미매핑    | {', '.join(missing_req)} |")

    # ── 2. 피처별 분포 ──
    L.append("\n## 2. 피처별 분포\n")
    L.append("| 피처                    | dtype   | null율(%) | unique | 비고          |")
    L.append("|:------------------------|:--------|----------:|-------:|:--------------|")
    for col in ALL_FEATURES:
        if col not in df.columns:
            # 의도된 미생성 vs 예상 밖 미생성 구분
            if amount_unavailable and col in _AMOUNT_DEPENDENT:
                L.append(f"| {col:<23} | —       |       — |    — | 의도된 스킵   |")
            else:
                L.append(f"| {col:<23} | —       |       — |    — | **미생성**    |")
            continue
        s = df[col]
        dtype = str(s.dtype)
        null_pct = s.isna().mean() * 100
        unique = s.nunique()
        if s.dtype == "bool":
            true_pct = s.mean() * 100
            note = f"True {true_pct:.1f}%"
        elif "float" in dtype or "int" in dtype.lower():
            note = f"[{s.min()}, {s.max()}]" if not s.isna().all() else "전체 NaN"
        else:
            note = ""
        L.append(f"| {col:<23} | {dtype:<7} | {null_pct:>8.1f} | {unique:>6} | {note:<13} |")

    # ── 미생성/NaN 피처를 원인별로 분류 ──
    # 의도된 미생성: 입력 컬럼 부재로 인한 정상 스킵
    expected_missing = [
        c for c in result.missing_columns
        if amount_unavailable and c in _AMOUNT_DEPENDENT
    ]
    # 예상 밖 미생성: 코드 버그 의심
    unexpected_missing = [
        c for c in result.missing_columns
        if c not in expected_missing
    ]
    # 전체 NaN: 생성은 됐지만 값이 전부 결측
    all_null = [c for c in result.added_columns if df[c].isna().all()]
    # 의도된 전체 NaN (입력 컬럼 부재)
    expected_null = [
        c for c in all_null
        if amount_unavailable and c in _AMOUNT_DEPENDENT
    ]
    # 입력 컬럼 의존이 아닌 전체 NaN — 원인 분석 필요
    unexpected_null = [c for c in all_null if c not in expected_null]

    # ── 3. 분석 ──
    L.append("\n## 3. 분석\n")

    # 3-1. 코드 버그 (예상 밖)
    bugs = unexpected_missing + unexpected_null
    if bugs:
        L.append("### 코드 버그 (조사 필요)\n")
        for col in unexpected_missing:
            L.append(f"- **{col}**: 미생성 — 원인 불명")
        for col in unexpected_null:
            L.append(f"- **{col}**: 전체 NaN — 입력 데이터 또는 로직 확인 필요")
    else:
        L.append("### 코드 버그\n\n없음.")

    # 3-2. 의도된 degradation
    if expected_missing or expected_null:
        L.append(f"\n### Graceful Degradation (정상 — 필수 컬럼 미매핑)\n")
        L.append(f"원인: `{', '.join(missing_req)}` 미매핑 → 의존 피처 생성 불가\n")
        for col in expected_missing:
            L.append(f"- `{col}`: 미생성 (amount 카테고리 스킵)")
        for col in expected_null:
            L.append(f"- `{col}`: 전체 NaN (금액 컬럼 부재)")
        L.append(f"\n> Phase 1c 매핑 리뷰 UI에서 수동 조정 시 해결됩니다.")

    # 3-3. 데이터 특성 (코드 정상)
    no_var_bool = [
        c for c in result.added_columns
        if str(df[c].dtype) in ("bool", "boolean") and df[c].nunique() < 2
        and c not in all_null
    ]
    if no_var_bool:
        L.append("\n### 데이터 특성 (코드 정상, 데이터에 해당 패턴 부재)\n")
        for col in no_var_bool:
            val = df[col].iloc[0]
            L.append(f"- `{col}`: all-{val}")

    # ── 4. 카테고리별 성능 ──
    L.append("\n## 4. 카테고리별 성능\n")
    L.append("| 카테고리 | 상태   | 소요시간(s) | 피처 수 |")
    L.append("|:---------|:------:|------------:|--------:|")
    for cat, t in result.execution_times.items():
        feat_count = len(EXPECTED_COLUMNS.get(cat, []))
        status = "성공" if cat in result.categories_run else "스킵"
        L.append(f"| {cat:<8} | {status:<4}   | {t:>10.3f} | {feat_count:>7} |")
    L.append(f"| **합계** |        | {elapsed:>10.3f} | {len(result.added_columns):>7} |")

    return "\n".join(L)
