"""역분개 패턴 탐지 룰 — C11.

Why: 감사기준서 240호 §32(a)(ii) 기말 재분개 중점 검사.
     SAP 환경에서 전표 수정 = 역분개(FB08) + 재전기 방식이 강제되므로,
     비정상 역분개 패턴은 부정·조작의 핵심 탐지 포인트.

5개 서브 신호를 가중 합산하여 임계값 이상이면 플래그:
  S1(0.35) 1:1 매칭 — 동일 계정·금액·반대방향 ±N일
  S2(0.25) N:M 롤링 제로아웃 — 그룹 내 순액 ≈ 0 + 금액 대칭 쌍
  S3(±0.15) 정상/수정 구분 — 월초 자동 감점, 수동 가중
  S4(0.10) 적요 키워드 매칭
  S5(×1.5) 기말 부스트 — 12/20~12/31 + 1/1~1/5
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import pandas as pd

from config.settings import get_audit_rules

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 서브 신호 가중치 ───────────────────────────────────────────
_W_S1 = 0.35   # 1:1 매칭
_W_S2 = 0.25   # N:M 롤링 제로아웃
_W_S3 = 0.15   # 정상/수정 구분 (부호 반전 가능)
_W_S4 = 0.10   # 적요 키워드
_S5_BOOST = 1.5  # 기말 배율

# Why: S2에서 순액/총액 비율이 이 값 미만이면 "비정상적으로 작은 순액"으로 판단
_NET_GROSS_RATIO_THRESHOLD = 0.05

# Why: S1 self-merge 시 보조 키가 없는 경우 그룹이 커질 수 있음
#      경고만 하고 축소 조건(exact date)으로 전환
_LARGE_GROUP_WARN = 500

_CORE_COLUMNS = ["gl_account", "debit_amount", "credit_amount", "posting_date", "document_id"]

# ── 키워드 (config 외부화 + 폴백) ─────────────────────────────
_FALLBACK_REVERSAL_KEYWORDS = [
    "수정", "정정", "오류", "역분개", "결산조정",
    "취소", "원복", "대체", "재전기", "환입",
    r"[Rr]eversal", r"[Cc]ancel", r"[Cc]orrect", r"[Aa]djust",
    r"[Rr]estate", r"[Ee]rror", r"[Vv]oid", r"[Ww]rite.off",
]


def _load_reversal_keywords() -> list[str]:
    """config/audit_rules.yaml에서 reversal_keywords 로드. 실패 시 폴백."""
    try:
        rules = get_audit_rules()
        keywords = rules.get("patterns", {}).get("reversal_keywords", [])
        return keywords if keywords else _FALLBACK_REVERSAL_KEYWORDS
    except Exception:
        return _FALLBACK_REVERSAL_KEYWORDS


# Why: 모듈 로드 시 1회만 컴파일 — 매 호출마다 YAML 읽기 + re.compile 방지
_REVERSAL_KEYWORDS: list[str] = _load_reversal_keywords()
_REVERSAL_PATTERN: re.Pattern = re.compile("|".join(_REVERSAL_KEYWORDS), re.IGNORECASE)


def _load_exclude_accounts() -> list[str]:
    """config/audit_rules.yaml에서 reversal_exclude_accounts 로드.

    Why: GR/IR 청산(2900), IC 정산(1150/2050) 등은 동일 금액 반대 전표가
         정상 프로세스이므로 S1/S2 탐지 대상에서 제외.
    """
    try:
        rules = get_audit_rules()
        return rules.get("patterns", {}).get("reversal_exclude_accounts", [])
    except Exception:
        return []


_EXCLUDE_ACCOUNTS: list[str] = _load_exclude_accounts()


# ── S1: 1:1 매칭 ──────────────────────────────────────────────

def _s1_one_to_one_match(
    df: pd.DataFrame,
    match_window_days: int = 1,
) -> pd.Series:
    """동일 gl_account + 동일 금액 + 반대 방향 + ±N일, 다른 document_id.

    Why: 가장 직접적인 역분개 증거. 세분화 키(cost_center, trading_partner)로
         Cartesian 폭발 방지. 보조 키 없으면 date 범위 축소로 대응.
    """
    net = df["debit_amount"].fillna(0) - df["credit_amount"].fillna(0)
    abs_amt = net.abs().round(2)

    # Why: net_amount == 0인 행은 매칭 대상이 아님 (차변·대변 동시 0)
    nonzero_mask = net != 0

    # Why: 정상 청산/반제 계정(GR/IR, IC 정산 등)은 동일 금액 반대 전표가
    #      업무 프로세스 자체이므로 역분개 탐지 대상에서 제외
    if _EXCLUDE_ACCOUNTS:
        gl_str = df["gl_account"].astype(str)
        exclude_mask = gl_str.apply(
            lambda g: any(g.startswith(prefix) for prefix in _EXCLUDE_ACCOUNTS)
        )
        nonzero_mask = nonzero_mask & ~exclude_mask

    if nonzero_mask.sum() < 2:
        return pd.Series(False, index=df.index)

    work = pd.DataFrame({
        "gl_account": df["gl_account"],
        "abs_amt": abs_amt,
        "net": net,
        "posting_date": df["posting_date"],
        "document_id": df["document_id"],
        "_orig_idx": df.index,  # Why: merge 후 원본 인덱스 추적용
    }, index=df.index)
    work = work.loc[nonzero_mask].reset_index(drop=True)

    # Why: 세분화 키로 그룹 크기를 줄여 self-merge 성능 확보
    merge_keys = ["gl_account", "abs_amt"]
    has_aux_key = False
    for aux_col in ("cost_center", "trading_partner"):
        if aux_col in df.columns and df[aux_col].notna().any():
            work[aux_col] = df.loc[nonzero_mask, aux_col].values
            merge_keys.append(aux_col)
            has_aux_key = True
            break  # Why: 하나만 추가 — 둘 다 추가하면 over-segmentation

    # Why: 보조 키 없이 그룹이 클 수 있으면 경고 + exact date로 축소
    group_sizes = work.groupby(merge_keys[:2]).size()
    large_groups = group_sizes[group_sizes > _LARGE_GROUP_WARN]
    use_exact_date = not has_aux_key and len(large_groups) > 0
    if use_exact_date:
        logger.warning(
            "S1: %d개 (gl_account, abs_amt) 그룹이 %d행 초과 — exact date 매칭으로 축소",
            len(large_groups), _LARGE_GROUP_WARN,
        )

    # Why: self-merge (suffixes로 좌/우 구분)
    merged = work.merge(work, on=merge_keys, suffixes=("_l", "_r"))

    # Why: 자기 자신 제거 (행 번호 기준) + 같은 document_id 제거 (정상 복합분개)
    merged = merged[merged["_orig_idx_l"] != merged["_orig_idx_r"]]
    merged = merged[merged["document_id_l"] != merged["document_id_r"]]

    # Why: 반대 방향 확인 (부호 곱 < 0)
    merged = merged[merged["net_l"] * merged["net_r"] < 0]

    # Why: 날짜 차이 확인
    date_diff = (merged["posting_date_l"] - merged["posting_date_r"]).abs()
    if use_exact_date:
        merged = merged[date_diff <= pd.Timedelta(days=0)]
    else:
        merged = merged[date_diff <= pd.Timedelta(days=match_window_days)]

    # Why: 매칭된 양쪽의 원본 인덱스를 수집
    matched_indices = set(merged["_orig_idx_l"]) | set(merged["_orig_idx_r"])
    return pd.Series(df.index.isin(matched_indices), index=df.index)


# ── S2: N:M 롤링 제로아웃 ─────────────────────────────────────

def _s2_rolling_zero_out(
    df: pd.DataFrame,
    rolling_window_days: int = 7,
    zero_threshold: float = 1000.0,
) -> pd.Series:
    """gl_account × created_by 그룹, 윈도우 내 순액 ≈ 0 + 금액 대칭 쌍 확인.

    Why: 분할 역분개 탐지. 단순 순액 0이 아닌, gross 대비 net 비율로
         일상 입출금 계정의 오탐을 방지.
    """
    if "created_by" not in df.columns:
        return pd.Series(False, index=df.index)

    net = df["debit_amount"].fillna(0) - df["credit_amount"].fillna(0)
    gross = df["debit_amount"].fillna(0) + df["credit_amount"].fillna(0)

    work = pd.DataFrame({
        "gl_account": df["gl_account"],
        "created_by": df["created_by"],
        "posting_date": df["posting_date"],
        "net": net,
        "gross": gross,
    }, index=df.index).copy()

    # Why: 정상 청산/반제 계정 제외 (S1과 동일)
    if _EXCLUDE_ACCOUNTS:
        gl_str = work["gl_account"].astype(str)
        exclude_mask = gl_str.apply(
            lambda g: any(g.startswith(prefix) for prefix in _EXCLUDE_ACCOUNTS)
        )
        work = work[~exclude_mask]

    # Why: posting_date를 datetime으로 보장 (rolling window에 필요)
    work["posting_date"] = pd.to_datetime(work["posting_date"], errors="coerce")
    work = work.dropna(subset=["posting_date", "gl_account", "created_by"])
    if len(work) < 2:
        return pd.Series(False, index=df.index)

    work = work.sort_values(["gl_account", "created_by", "posting_date"])

    window_str = f"{rolling_window_days}D"
    grouped = work.groupby(["gl_account", "created_by"])

    result = pd.Series(False, index=df.index)

    for (_gl, _cb), group in grouped:
        if len(group) < 2:
            continue

        # Why: 그룹 내 차변/대변 모두 존재해야 역분개 가능성
        has_debit = (group["net"] > 0).any()
        has_credit = (group["net"] < 0).any()
        if not (has_debit and has_credit):
            continue

        # Why: time-based rolling — posting_date를 인덱스로 설정
        g = group.set_index("posting_date").sort_index()
        rolling_net = g["net"].rolling(window_str).sum()
        rolling_gross = g["gross"].rolling(window_str).sum()

        # Why: 복합 조건 — 순액 작음 + gross 대비 비율 비정상 + 최소 2건
        #      (차변/대변 모두 존재는 위에서 사전 검증)
        rolling_count = g["net"].rolling(window_str).count()
        safe_gross = rolling_gross.replace(0, float("nan"))
        net_ratio = (rolling_net.abs() / safe_gross).fillna(1.0)

        flagged_mask = (
            (rolling_net.abs() < zero_threshold)
            & (net_ratio < _NET_GROSS_RATIO_THRESHOLD)
            & (rolling_count >= 2)
        )

        if flagged_mask.any():
            # Why: g(posting_date 인덱스)와 group(원본 인덱스)의 행 수 불일치 방어
            if len(flagged_mask) != len(group):
                logger.warning(
                    "S2: flagged_mask(%d)와 group(%d) 길이 불일치 — skip",
                    len(flagged_mask), len(group),
                )
                continue
            flagged_indices = group.index[flagged_mask.values]
            result.loc[result.index.isin(flagged_indices)] = True

    return result


# ── S3: 정상/수정 구분 ────────────────────────────────────────

def _s3_reversal_type(df: pd.DataFrame) -> pd.Series:
    """월초 자동 전표 → 감점, 수동 전표 → 가중.

    Why: 매월 초(D≤5) 자동 배치 전표는 전월 미결산 역분개로 정상.
         1월 초는 연초 이월이므로 더 큰 감점. 수동+월중 = 검토 대상.
    반환값: -0.15 ~ +0.15 float Series.
    """
    adjustment = pd.Series(0.0, index=df.index)

    if "source" not in df.columns:
        return adjustment

    posting_date = pd.to_datetime(df["posting_date"], errors="coerce")
    day_of_month = posting_date.dt.day
    month = posting_date.dt.month

    source_lower = df["source"].astype(str).str.lower()
    is_auto = source_lower.isin(["auto", "automated", "recurring"])
    is_month_start = day_of_month <= 5

    # Why: 1월 초(연초 이월) → 큰 감점, 2~12월 초(월초 배치) → 소폭 감점
    jan_auto = is_auto & is_month_start & (month == 1)
    other_auto = is_auto & is_month_start & (month != 1)
    manual_any = ~is_auto  # Why: 수동 전표는 날짜 무관하게 가중 (검토 대상)

    adjustment[jan_auto] = -_W_S3           # -0.15
    adjustment[other_auto] = -(_W_S3 * 0.67)  # -0.10
    adjustment[manual_any] = _W_S3          # +0.15

    return adjustment


# ── S4: 적요 키워드 ───────────────────────────────────────────

def _s4_keyword_match(df: pd.DataFrame) -> pd.Series:
    """line_text에서 역분개 관련 키워드 매칭.

    Why: header_text(SAP BKTXT)는 시스템이 전표 유형이나 배치 작업명을
         자동 기입하여 노이즈가 심하므로 제외. line_text(SGTXT)만 검사.
    """
    if "line_text" not in df.columns:
        return pd.Series(False, index=df.index)

    text = df["line_text"].fillna("").astype(str)
    # Why: str.contains는 apply(lambda)보다 벡터화되어 대용량에서 성능 유리
    return text.str.contains(_REVERSAL_PATTERN, na=False)


# ── S5: 기말 부스트 ───────────────────────────────────────────

def _s5_period_end_boost(df: pd.DataFrame) -> pd.Series:
    """12/20~12/31 + 1/1~1/5 범위에서 배율 1.5 적용.

    Why: 결산 조정(Top-side JE)은 기말 직전/직후에 집중.
         12월 전체가 아닌 결산 전후 15일로 축소하여 과탐 방지.
    반환값: 배율 Series (1.0 또는 _S5_BOOST).
    """
    posting_date = pd.to_datetime(df["posting_date"], errors="coerce")
    month = posting_date.dt.month
    day = posting_date.dt.day

    # Why: 12/20~12/31 또는 1/1~1/5가 부스트 대상
    is_year_end = (month == 12) & (day >= 20)
    is_year_start = (month == 1) & (day <= 5)
    is_boost = is_year_end | is_year_start

    multiplier = pd.Series(1.0, index=df.index)
    multiplier[is_boost] = _S5_BOOST
    return multiplier


# ── 공개 함수: C11 역분개 패턴 탐지 ───────────────────────────

def c11_reversal_entry(
    df: pd.DataFrame,
    *,
    match_window_days: int = 1,
    rolling_window_days: int = 7,
    zero_threshold: float = 1000.0,
    score_threshold: float = 0.3,
) -> pd.Series:
    """C11 역분개 패턴: 5개 서브 신호 가중 합산.

    Why: AS 240 §32 — 기말 조정·재분개는 부정의 핵심 수단.
         단일 조건이 아닌 복합 신호로 정밀도 확보.

    Returns:
        pd.Series[bool]: 플래그 여부 (True = 역분개 의심)
    """
    missing = [c for c in _CORE_COLUMNS if c not in df.columns]
    if missing:
        logger.warning("C11: 필수 컬럼 누락 %s — 전원 False", missing)
        return pd.Series(False, index=df.index)

    if len(df) < 2:
        return pd.Series(False, index=df.index)

    # Why: 각 서브 신호를 독립 실행 — 하나 실패해도 나머지 계속
    s1 = pd.Series(False, index=df.index)
    s2 = pd.Series(False, index=df.index)
    s3 = pd.Series(0.0, index=df.index)
    s4 = pd.Series(False, index=df.index)
    s5 = pd.Series(1.0, index=df.index)

    try:
        s1 = _s1_one_to_one_match(df, match_window_days=match_window_days)
    except Exception as exc:
        logger.warning("C11-S1 실행 실패: %s", exc)

    try:
        s2 = _s2_rolling_zero_out(
            df,
            rolling_window_days=rolling_window_days,
            zero_threshold=zero_threshold,
        )
    except Exception as exc:
        logger.warning("C11-S2 실행 실패: %s", exc)

    try:
        s3 = _s3_reversal_type(df)
    except Exception as exc:
        logger.warning("C11-S3 실행 실패: %s", exc)

    try:
        s4 = _s4_keyword_match(df)
    except Exception as exc:
        logger.warning("C11-S4 실행 실패: %s", exc)

    try:
        s5 = _s5_period_end_boost(df)
    except Exception as exc:
        logger.warning("C11-S5 실행 실패: %s", exc)

    # Why: 가중 합산 → 필수 전제 조건(S1 or S2) → 임계값 판정
    base_score = (
        s1.astype(float) * _W_S1
        + s2.astype(float) * _W_S2
        + s4.astype(float) * _W_S4
    )
    adjusted = base_score + s3
    final = (adjusted * s5).clip(0.0, 1.0)

    # Why: 역분개 탐지이므로 금액적 매칭(S1 또는 S2) 없이는 플래그 불가.
    #      S3(수동)+S4(키워드)+S5(기말)만으로 넘기면 "적요만 고쳐 쓴 수동 전표"가
    #      전부 역분개로 오탐됨 → 구조적 결함 방지.
    has_amount_match = s1.astype(bool) | s2.astype(bool)

    return (final >= score_threshold) & has_amount_match
