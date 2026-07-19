"""전표 속성 기반 패턴 매칭 파생변수 5개 생성 모듈.

L4-01(매출계정), L3-02(수기전표), L3-03(관계사), L2-04(가계정), L4-02(Benford) 룰 대응.
감사 업무 룰(키워드/코드)은 config/audit_rules.yaml에서 로드 — 함수 인자로 주입.
"""

from __future__ import annotations

import functools
import json
import logging
import re
from pathlib import Path

import pandas as pd

from src.ingest.datasynth_labels import get_source_path

logger = logging.getLogger(__name__)

# 가계정 키워드 검색 대상 텍스트 컬럼
# gl_account_name: Phase 2 스키마 확장 시 자동 반영 (existing_cols 필터로 안전)
_SUSPENSE_TEXT_COLS = ["line_text", "header_text", "gl_account_name"]


@functools.lru_cache(maxsize=16)
def _load_coa_suspense_codes_cached(path_str: str, mtime_ns: int) -> frozenset[str] | None:
    """chart_of_accounts.json → is_suspense_account=True 계정 코드 집합.

    Why: 가계정 판별의 권위(authority)는 CoA의 계정별 is_suspense_account 플래그다.
    적요 키워드/코드 prefix 휴리스틱은 이 권위가 없는 실무 CoA용 폴백일 뿐이다.
    반환 의미 구분:
      - None: 플래그 키 자체가 없는 CoA(진짜 미지정) → 휴리스틱 폴백
      - frozenset (빈 것 포함): 플래그가 지정된 CoA → 권위. 빈 집합이면 "가계정
        0개"가 정답이므로 전 행 False가 맞다(휴리스틱으로 되돌리지 않는다).

    mtime_ns는 캐시 무효화 키다 — datasynth 재생성으로 같은 경로에 CoA가 다시
    써지면(장수명 대시보드 프로세스) mtime이 바뀌어 stale 캐시를 피한다.
    """
    coa_path = Path(path_str)
    if not coa_path.exists():
        return None
    raw = json.loads(coa_path.read_text(encoding="utf-8"))
    accounts = raw.get("accounts", raw if isinstance(raw, list) else [])
    # Why: "플래그 키 없음(미지정)"과 "키 있고 전부 False(가계정 0개)"를 구분해야
    #      후자를 휴리스틱으로 잘못 폴백시키지 않는다.
    has_flag_key = any(isinstance(a, dict) and "is_suspense_account" in a for a in accounts)
    if not has_flag_key:
        return None
    codes = {
        str(a.get("account_number") or a.get("account_code") or "").strip()
        for a in accounts
        if isinstance(a, dict) and a.get("is_suspense_account")
    }
    codes.discard("")
    return frozenset(codes)


def _load_coa_suspense_codes(source_path: str | Path | None) -> frozenset[str] | None:
    """source(원장 파일) 옆의 chart_of_accounts.json에서 가계정 코드 집합 해소.

    source_path는 원장 파일(journal_entries*.csv) 경로. 같은 디렉터리의
    chart_of_accounts.json을 권위로 사용한다. 미존재/빈집합이면 None.
    """
    if source_path is None:
        return None
    coa_path = Path(source_path).parent / "chart_of_accounts.json"
    try:
        mtime_ns = coa_path.stat().st_mtime_ns
    except OSError:
        return None
    return _load_coa_suspense_codes_cached(str(coa_path), mtime_ns)


# ── Public feature functions ─────────────────────────────────────


def add_is_manual_je(
    df: pd.DataFrame,
    manual_codes: list[str],
) -> pd.DataFrame:
    """L3-02: source 컬럼이 수기 전표 코드와 매칭되면 True.

    감사 관점: 수기 전표는 자동화 통제 우회 — 부정 전표 가능성.
    manual_codes는 ERP마다 다름 (SAP: SA, Oracle: Manual 등).
    """
    if "source" not in df.columns:
        logger.warning("source 컬럼 누락 — is_manual_je를 전체 False로 설정")
        df["is_manual_je"] = False
        return df

    if not manual_codes:
        logger.warning("manual_source_codes 비어있음 — is_manual_je를 전체 False로 설정")
        df["is_manual_je"] = False
        return df

    # 정규화: 대소문자·공백 무시
    normalized = df["source"].astype(str).str.strip().str.lower()
    codes_lower = [c.strip().lower() for c in manual_codes]
    df["is_manual_je"] = normalized.isin(codes_lower).where(df["source"].notna(), False)
    return df


def add_is_intercompany(
    df: pd.DataFrame,
    identifiers: list[str],
) -> pd.DataFrame:
    """L3-03: 관계사 거래 여부.

    감사 관점: 관계사 거래는 특수관계자 거래 검토, 대사, 이전가격 검토의 후보 신호.
    GL prefix를 1순위로 보되, DataSynth/ERP에서 process와 counterparty semantic이
    명확히 표시된 경우도 관계사 후보로 본다.
    """
    result = pd.Series(False, index=df.index)

    if identifiers and "gl_account" in df.columns:
        gl_str = df["gl_account"].astype(str).str.strip()
        result = result | gl_str.str.startswith(tuple(identifiers)).fillna(False)
    elif not identifiers:
        logger.warning("intercompany_identifiers 비어있음 — GL prefix 기반 식별 생략")
    elif "gl_account" not in df.columns:
        logger.warning("gl_account 컬럼 없음 — GL prefix 기반 식별 생략")

    if "business_process" in df.columns:
        process = df["business_process"].fillna("").astype(str).str.strip().str.lower()
        result = result | process.eq("intercompany")

    if "counterparty_type" in df.columns:
        counterparty_type = df["counterparty_type"].fillna("").astype(str).str.strip().str.lower()
        result = result | counterparty_type.eq("intercompanyaffiliate")

    df["is_intercompany"] = result.fillna(False)
    return df


def load_ic_pairs(audit_rules: dict) -> dict[str, str]:
    """YAML intercompany.pairs → 양방향 prefix 매핑 dict.

    Why: is_intercompany(L3-03) GL prefix 매칭용. 클라이언트별 CoA 체계가
    다르므로 코드 하드코딩 금지. (구 intercompany_rules 에서 is_intercompany
    전용 의존만 이전 — IC family 검사기 삭제와 분리.)
    """
    patterns = audit_rules.get("patterns", audit_rules)
    ic_config = patterns.get("intercompany", {})
    pairs_list = ic_config.get("pairs", [])

    pair_map: dict[str, str] = {}
    for pair in pairs_list:
        rec = str(pair.get("receivable", ""))
        pay = str(pair.get("payable", ""))
        if rec and pay:
            pair_map[rec] = pay
            pair_map[pay] = rec
    return pair_map


def extract_ic_prefixes(audit_rules: dict) -> list[str]:
    """pairs 에서 모든 고유 prefix 추출 — add_is_intercompany() 입력용."""
    pair_map = load_ic_pairs(audit_rules)
    return sorted(set(pair_map.keys()))


def add_is_revenue_account(
    df: pd.DataFrame,
    prefixes: list[str],
) -> pd.DataFrame:
    """L4-01: gl_account가 매출 계정(prefix 매칭)이면 True.

    감사 관점: 매출 계정 이상 변동 탐지의 기준 필터.
    K-IFRS 기준 4xxx가 표준이나, 회사마다 다를 수 있음.
    """
    if "gl_account" not in df.columns:
        logger.warning("gl_account 컬럼 누락 — is_revenue_account를 전체 False로 설정")
        df["is_revenue_account"] = False
        return df

    if not prefixes:
        logger.warning("revenue_account_prefixes 비어있음 — is_revenue_account를 전체 False로 설정")
        df["is_revenue_account"] = False
        return df

    gl_str = df["gl_account"].astype(str).str.strip()
    df["is_revenue_account"] = gl_str.str.startswith(tuple(prefixes)).fillna(False)
    return df


def add_first_digit(df: pd.DataFrame) -> pd.DataFrame:
    """L4-02: 금액의 첫 번째 유효숫자(1~9) 추출 — Benford 분석 입력.

    str.extract(r"([1-9])") 사용 — 과학표기법, 소수, 음수 모두 안전 처리.
    0원 → NaN (Benford 분석 대상 외).
    """
    # 금액 컬럼 부재 시 NaN fallback (다른 함수와 패턴 일관성)
    required = ["debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("%s 컬럼 누락 — first_digit를 전체 NaN으로 설정", missing)
        df["first_digit"] = pd.array([pd.NA] * len(df), dtype="Int64")
        return df

    # Why: DataSynth int64 초과 금액 → pandas가 object로 추론하는 경우 방어
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0)
    amount = pd.concat([debit.abs(), credit.abs()], axis=1).max(axis=1)

    # 0원 마스킹: Benford 분석에서 0은 의미 없음
    amount = amount.where(amount > 0)

    # 문자열 변환 후 첫 번째 1~9 숫자 추출 (과학표기법·소수 안전)
    digits = amount.astype(str).str.extract(r"([1-9])", expand=False)
    df["first_digit"] = pd.to_numeric(digits, errors="coerce").astype("Int64")
    return df


def add_is_suspense_account(
    df: pd.DataFrame,
    keywords: list[str],
    account_codes: list[str] | None = None,
    coa_suspense_codes: frozenset[str] | set[str] | None = None,
) -> pd.DataFrame:
    """L2-04: 가계정·미결산 계정 판별.

    권위 우선: `coa_suspense_codes`(CoA의 is_suspense_account 플래그에서 도출한
    가계정 코드 집합)가 주어지면 `gl_account` 정확 매칭만 사용한다. 적요 키워드/
    코드 prefix 휴리스틱은 권위가 없는 실무 CoA용 폴백이다 — 휴리스틱은 적요의
    'Clearing/임시' 등을 긁어 현금 등 비가계정을 과탐하므로, 권위가 있으면 쓰지 않는다.
    """
    # Why: CoA 권위가 있으면(빈 집합=가계정 0개 포함) 정확 매칭으로 대체 (휴리스틱 과탐 제거).
    #      None만 폴백 — 빈 frozenset은 "가계정 없음"이 정답이므로 권위로 인정한다.
    if coa_suspense_codes is not None:
        if "gl_account" in df.columns:
            # Why: isin은 startswith와 달리 표기 차이에 민감. gl_account가 NaN 섞인
            # float64로 로드되면 astype(str)이 "9000.0"이 되어 isin({"9000"}) 전멸(미탐).
            # 정확매칭 전 트레일링 ".0"을 제거해 정규화한다.
            gl_str = df["gl_account"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
            df["is_suspense_account"] = gl_str.isin(set(coa_suspense_codes))
        else:
            logger.warning("gl_account 컬럼 없음 — CoA 권위 매칭 불가, 전체 False")
            df["is_suspense_account"] = False
        return df

    # Why: keywords와 account_codes 둘 다 비어야 early return
    if not keywords and not account_codes:
        logger.warning("suspense_keywords·account_codes 모두 비어있음 — 전체 False")
        df["is_suspense_account"] = False
        return df

    result = pd.Series(False, index=df.index)

    # ── 1) 텍스트 키워드 매칭 ──
    if keywords:
        safe_patterns = []
        for kw in keywords:
            try:
                re.compile(kw)
                safe_patterns.append(kw)
            except re.error:
                escaped = re.escape(kw)
                logger.warning("정규식 컴파일 실패: '%s' → re.escape 폴백: '%s'", kw, escaped)
                safe_patterns.append(escaped)

        combined = "|".join(safe_patterns)
        existing_cols = [c for c in _SUSPENSE_TEXT_COLS if c in df.columns]
        for col in existing_cols:
            result = result | df[col].astype(str).str.contains(
                combined,
                na=False,
                regex=True,
            )

    # ── 2) GL 계정 코드 prefix 매칭 (is_intercompany 패턴 동일) ──
    if account_codes and "gl_account" in df.columns:
        gl_str = df["gl_account"].astype(str).str.strip()
        code_match = gl_str.str.startswith(tuple(account_codes)).fillna(False)
        result = result | code_match

    df["is_suspense_account"] = result
    return df


# ── Orchestrator ─────────────────────────────────────────────────


def add_all_pattern_features(
    df: pd.DataFrame,
    rules: dict | None = None,
    source_path: str | Path | None = None,
) -> pd.DataFrame:
    """패턴 파생변수 5개를 한번에 추가. engine.py 진입점.

    rules: audit_rules.yaml["patterns"] dict. None이면 자동 로드.
    source_path: 원장 파일 경로. None이면 df.attrs의 source_path로 자동 해소.
        같은 디렉터리의 chart_of_accounts.json이 가계정 판별 권위가 된다.
        Why: 병렬 thin-copy는 df.attrs를 버리므로 호출부가 명시 전달해야
        가계정 CoA 권위가 유실되지 않는다(employee_master_path와 동일 패턴).
    """
    if rules is None:
        from config.settings import get_audit_rules

        rules = get_audit_rules()["patterns"]

    add_is_manual_je(df, rules.get("manual_source_codes", []))
    # Why: intercompany.pairs 구조에서 flat prefix 리스트 추출 (WU-07 YAML 구조화).
    # extract_ic_prefixes 는 본 모듈 로컬 헬퍼 — IC family 검사기와 디커플(Inc-IC 선행).
    add_is_intercompany(df, extract_ic_prefixes(rules))
    add_is_revenue_account(df, rules.get("revenue_account_prefixes", []))
    add_first_digit(df)
    # Why: CoA is_suspense_account 플래그(권위)를 우선, 없으면 키워드/코드 휴리스틱 폴백
    coa_suspense_codes = _load_coa_suspense_codes(source_path or get_source_path(df))
    add_is_suspense_account(
        df,
        rules.get("suspense_keywords", []),
        account_codes=rules.get("suspense_account_codes", []),
        coa_suspense_codes=coa_suspense_codes,
    )

    return df
