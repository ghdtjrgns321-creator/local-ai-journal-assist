"""접근통제 기반 부정 탐지 룰 — B06, B07, B09, B10.

권장 컬럼(created_by, business_process, source, company_code) 의존.
해당 컬럼 미존재 시 Series(False) 반환 → 오케스트레이터가 warning 기록.
"""

from __future__ import annotations

import pandas as pd

from config.settings import get_audit_rules


def _get_manual_codes(audit_rules: dict | None = None) -> tuple[str, ...]:
    """수기 전표 소스 코드 목록 (소문자 정규화).

    Why: @lru_cache 제거 — dict 파라미터는 해시 불가.
         상위 get_audit_rules() 자체가 lru_cache이므로 이중 캐시 불필요.
         호출자(FraudLayer)가 __init__에서 1회 호출 후 인스턴스 변수로 보관.
    """
    rules = audit_rules or get_audit_rules()
    raw = rules.get("patterns", {}).get("manual_source_codes", ["SA", "Manual", "수기"])
    return tuple(c.lower() for c in raw)


def b06_self_approval(
    df: pd.DataFrame,
    min_amount: int = 0,
    audit_rules: dict | None = None,
) -> pd.Series:
    """B06 자기 승인: 인간 사용자의 고액 자기 승인만 플래그.

    Why: 외감법 §8①5호 — 업무 분장 위반.
         오스템임플란트(2021) 사례: 1인이 입력·승인·이체 전부 수행 → 2,215억 횡령.

    정밀화 (이전 111K건 10.08% 과탐 → ~5K건 예상):
      1. automated_system 제외 — ERP 자동 전기는 인간 SoD 대상 아님
      2. 소액 제외 — approval_thresholds Level 1 이하는 전결규정상 자동승인 범위
      3. Case A: approved_by 존재 → created_by == approved_by
      4. Case B: approved_by 부재 → 수기 소스 + created_by 존재 = 자기 승인 추정
    """
    if "created_by" not in df.columns:
        return pd.Series(False, index=df.index)

    # ── 자기 승인 판정 ──
    if "approved_by" in df.columns:
        same_person = (df["created_by"] == df["approved_by"]) & df["created_by"].notna()
    elif "source" in df.columns:
        is_manual = df["source"].astype(str).str.lower().isin(_get_manual_codes(audit_rules))
        same_person = is_manual & df["created_by"].notna()
    else:
        return pd.Series(False, index=df.index)

    # ── automated_system 제외 ──
    # Why: 시스템이 시스템을 자동 승인하는 건 정상 ERP 동작 (71% 과탐 원인)
    if "user_persona" in df.columns:
        same_person = same_person & (df["user_persona"].fillna("") != "automated_system")

    # ── 소액 제외 ──
    # Why: max(debit, credit)로 대표 금액 산출 — 대변 전용/역분개 전표 대응
    #      Level 1(1천만) 이하는 전결규정상 자동승인 범위 (23% 과탐 원인)
    if min_amount > 0 and "debit_amount" in df.columns and "credit_amount" in df.columns:
        base = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
        same_person = same_person & (base > min_amount)

    return same_person


def _get_sod_config(audit_rules: dict | None = None) -> tuple[list[frozenset[str]], dict[str, int]]:
    """SoD 설정 로드: toxic_pairs + role_thresholds.

    Why: @lru_cache 제거 — dict 파라미터 해시 불가. 호출자가 캐싱 담당.
    """
    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})

    raw_pairs = patterns.get("sod_toxic_pairs", [
        ["TRE", "P2P"], ["TRE", "O2C"], ["O2C", "P2P"],
        ["H2R", "O2C"], ["H2R", "P2P"],
    ])
    toxic_pairs = [frozenset(p) for p in raw_pairs]

    role_thresholds = patterns.get("sod_role_thresholds", {
        "junior_accountant": 1,
        "senior_accountant": 3,
    })

    return toxic_pairs, role_thresholds


def b07_segregation_of_duties(
    df: pd.DataFrame,
    sod_threshold: int = 3,
    audit_rules: dict | None = None,
) -> pd.Series:
    """B07 직무분리 위반 — 하이브리드 3단계 로직.

    Why: K-SOX COSO 2013 — 직무분리는 내부통제의 핵심 원칙.
         단순 프로세스 수 세기는 74% 과탐 유발 → 3단계 정밀 판정.

    판정 순서 (OR 결합):
      1. Toxic Pair: 사용자가 위험 프로세스 쌍에 동시 관여 → 직급 불문 즉시 위반
      2. In-Process: sod_conflict_type 컬럼에 충돌 유형 기록 → 해당 행 위반
      3. Role-based: 직급별 허용 프로세스 수 초과 → 위반 (controller/manager 제외)
    """
    required = ["created_by", "business_process"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    toxic_pairs, role_thresholds = _get_sod_config(audit_rules)
    result = pd.Series(False, index=df.index)

    # Why: automated_system은 ERP 자동 전기 — 인간 SoD 판정 대상 아님
    if "user_persona" in df.columns:
        human_mask = df["user_persona"] != "automated_system"
    else:
        human_mask = pd.Series(True, index=df.index)

    # ── 1단계: Toxic Pair (프로세스 간 상충) ──
    # Why: 2개만 겸직해도 횡령 루트가 열리는 치명적 조합
    human_df = df[human_mask]
    if human_df.empty:
        return result
    user_processes = human_df.groupby("created_by")["business_process"].apply(
        lambda x: frozenset(x.dropna().unique())
    )
    toxic_violators: set[str] = set()
    for user, procs in user_processes.items():
        for pair in toxic_pairs:
            if pair.issubset(procs):
                toxic_violators.add(user)
                break
    if toxic_violators:
        result = result | df["created_by"].isin(toxic_violators)

    # ── 2단계: In-Process Conflict (sod_conflict_type) ──
    # Why: 자기승인·마스터변경 등 동일 프로세스 내 통제 무력화
    if "sod_conflict_type" in df.columns:
        has_conflict = human_mask & df["sod_conflict_type"].notna() & (df["sod_conflict_type"] != "")
        result = result | has_conflict

    # ── 3단계: Role-based 프로세스 수 초과 ──
    # Why: junior는 1프로세스 전담, senior는 3개까지 허용
    #       controller/manager/automated는 수량 제한 없음 (toxic pair만 감시)
    if "user_persona" in df.columns and role_thresholds:
        counts = human_df.groupby("created_by")["business_process"].nunique()
        persona_map = human_df.drop_duplicates("created_by").set_index("created_by")["user_persona"]

        role_violators: set[str] = set()
        for user, count in counts.items():
            persona = persona_map.get(user)
            if persona and persona in role_thresholds:
                if count > role_thresholds[persona]:
                    role_violators.add(user)
        if role_violators:
            result = result | df["created_by"].isin(role_violators)
    else:
        # Why: user_persona 없으면 기존 단순 임계값 fallback (human only)
        counts = human_df.groupby("created_by")["business_process"].nunique()
        violators = counts[counts >= sod_threshold].index
        result = result | df["created_by"].isin(violators)

    return result


def b09_skipped_approval(df: pd.DataFrame) -> pd.Series:
    """B09 승인 생략: 한도 초과 + 비자동 소스 + 승인자 부재.

    Why: 외감법 §8② — 승인 절차 없이 처리된 한도 초과 전표는 내부통제 우회.
         approved_by IS NULL이어야 실제 '승인 생략'. 승인이 존재하면 정상.
    """
    if "exceeds_threshold" not in df.columns or "source" not in df.columns:
        return pd.Series(False, index=df.index)

    exceeds = df["exceeds_threshold"].fillna(False)
    # Why: 자동 처리(automated)는 시스템 통제 하에 있으므로 제외
    not_automated = df["source"].astype(str).str.lower() != "automated"
    # Why: approved_by가 비어있어야 '승인 생략'. 값이 있으면 승인 절차 이행됨
    no_approval = pd.Series(True, index=df.index)
    if "approved_by" in df.columns:
        no_approval = df["approved_by"].isna() | (df["approved_by"].astype(str).str.strip() == "")
    return exceeds & not_automated & no_approval


def b10_circular_intercompany(df: pd.DataFrame) -> pd.Series:
    """B10 관계사 거래 탐지 (MVP: GL prefix로 식별된 IC 전표를 flag).

    Why: 감사기준서 550호 §23 — 합리적 사업 근거 없는 특수관계자 거래.
    MVP 한계: IC 전용 GL 계정(채권/채무)에 해당하는 전표를 flag.
              실제 순환 탐지(n-hop)는 Phase 2 GraphDetector에서 수행.
    """
    if "is_intercompany" not in df.columns:
        return pd.Series(False, index=df.index)

    ic_mask = df["is_intercompany"].fillna(False)
    if not ic_mask.any():
        return pd.Series(False, index=df.index)

    # Why: company_code가 있으면 복수 회사 관여 여부로 추가 검증
    #      없어도 GL 기반 IC 전표는 flag (Phase 2 GraphDetector로 대체 예정)
    if "company_code" in df.columns:
        ic_companies = set(df.loc[ic_mask, "company_code"].dropna().unique())
        if len(ic_companies) < 2:
            return ic_mask

    return ic_mask
