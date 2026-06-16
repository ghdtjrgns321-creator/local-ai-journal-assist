"""내부거래 매칭 룰 함수 — IC 그룹 대사 + 3개 서브룰 (WU-07).

Why: L3-03(MVP)은 is_intercompany bool만 flag. 양측 거래 대사 없이 recall 7%.
     그룹 단위 집계 비교로 N:M 다대다 매칭 대응 + 이종 통화 방어.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.detection.boolean_utils import bool_column

logger = logging.getLogger(__name__)

_COUNTERPARTY_KEY_COLUMNS: tuple[str, ...] = (
    "trading_partner",
    "affiliate",
    "counterparty",
    "counterparty_code",
    "counterparty_id",
)


# ── YAML 설정 헬퍼 ─────────────────────────────────────────────


def load_ic_pairs(audit_rules: dict) -> dict[str, str]:
    """YAML intercompany.pairs → 양방향 매핑 dict.

    Why: 클라이언트별 CoA 체계가 다르므로 코드 하드코딩 금지.
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
    """pairs에서 모든 고유 prefix 추출 — add_is_intercompany() 호환용."""
    pair_map = load_ic_pairs(audit_rules)
    return sorted(set(pair_map.keys()))


def load_related_party_master(audit_rules: dict) -> set[str] | None:
    """YAML patterns.intercompany.related_party_master → set.

    None 반환 시 detector 가 dataset distinct company_code 로 폴백한다.
    """
    patterns = audit_rules.get("patterns", audit_rules)
    ic_config = patterns.get("intercompany", {})
    master_list = ic_config.get("related_party_master")
    if not master_list:
        return None
    cleaned = {str(c).strip() for c in master_list if str(c).strip()}
    return cleaned or None


def load_partner_format_policy(audit_rules: dict) -> dict:
    """YAML patterns.intercompany.partner_format → dict.

    keys: ic_partner_regex, customer_partner_regex, vendor_partner_regex
    """
    patterns = audit_rules.get("patterns", audit_rules)
    ic_config = patterns.get("intercompany", {})
    policy = ic_config.get("partner_format", {})
    return dict(policy) if policy else {}


# ── IC 계정 유형 분류 ──────────────────────────────────────────


def _classify_ic_type(
    gl_account: pd.Series,
    pair_map: dict[str, str],
) -> pd.Series:
    """GL 계정 prefix로 IC 유형(receivable/payable) 분류.

    Why: pair_map은 양방향이므로 YAML pairs 순서(receivable 먼저)를 기준으로
         첫 등장 키를 receivable로 분류. Python 3.7+ dict 삽입 순서 보장.
    """
    gl_str = gl_account.astype(str).str.strip()
    receivable_prefixes: set[str] = set()
    payable_prefixes: set[str] = set()
    seen: set[str] = set()
    for k, v in pair_map.items():
        if k not in seen and v not in seen:
            receivable_prefixes.add(k)
            payable_prefixes.add(v)
            seen.update([k, v])

    def _get_type(gl: str) -> str | None:
        for p in receivable_prefixes:
            if gl.startswith(p):
                return "receivable"
        for p in payable_prefixes:
            if gl.startswith(p):
                return "payable"
        return None

    return gl_str.map(_get_type)


def _first_nonempty_counterparty(side: pd.DataFrame) -> pd.Series:
    """Return first populated related-party key from accepted counterparty columns."""
    out = pd.Series("", index=side.index, dtype="object")
    for col in _COUNTERPARTY_KEY_COLUMNS:
        if col not in side.columns:
            continue
        values = side[col].fillna("").astype(str).str.strip()
        out = out.where(out.ne(""), values)
    return out


# ── 그룹 매칭 엔진 ─────────────────────────────────────────────


def match_ic_groups(
    df: pd.DataFrame,
    pair_map: dict[str, str],
    amount_tolerance: float,
    cross_currency_ratio_threshold: float = 20.0,
) -> pd.DataFrame:
    """IC 전표를 그룹 단위로 매칭 — N:M 다대다 대응.

    Why: A법인 10건 소액 vs B법인 1건 통합 기표 → 행 단위 비교 실패.
         그룹별 sum(debit)/sum(credit) 집계 비교가 핵심.

    Returns: 원본 인덱스 기준 매칭 결과 DataFrame
        columns: [has_counterpart, matched, diff_ratio,
                  match_level, date_diff_days, cross_currency]
    """
    if not pair_map:
        return pd.DataFrame(index=df.index)

    ic_mask = df.get(
        "is_intercompany",
        pd.Series(False, index=df.index),
    ).fillna(False)
    if not ic_mask.any():
        return pd.DataFrame(index=df.index)

    ic_df = df.loc[ic_mask].copy()
    ic_df["_ic_type"] = _classify_ic_type(ic_df["gl_account"], pair_map)
    ic_df = ic_df.dropna(subset=["_ic_type"])
    if ic_df.empty:
        return pd.DataFrame(index=df.index)

    # Why: receivable → sum(debit), payable → sum(credit)
    ic_df["_amount"] = ic_df.apply(
        lambda r: r["debit_amount"] if r["_ic_type"] == "receivable" else r["credit_amount"],
        axis=1,
    ).fillna(0.0)

    # Why: groupby lambda가 반환하는 x.index는 그룹 내 상대 위치일 수 있음
    #      원본 인덱스를 컬럼으로 보존하여 안전하게 추적
    ic_df["_orig_idx"] = ic_df.index

    ic_df["_ic_partner_key"] = _first_nonempty_counterparty(ic_df)

    # ── 집계 키 결정 (graceful degradation) ──
    # match_level 매트릭스:
    #   company_code multi + trading_partner 있음 → "exact"     (Level 1)
    #   company_code multi, trading_partner 없음  → "aggregate" (Level 2)
    #   그 외                                    → "fallback"  (Level 3)
    has_tp = ic_df["_ic_partner_key"].ne("").any()
    has_cc = "company_code" in ic_df.columns and ic_df["company_code"].nunique() > 1
    has_ref = (
        "reference" in ic_df.columns
        and ic_df["reference"].fillna("").astype(str).str.strip().ne("").any()
    )
    has_cur = "currency" in ic_df.columns and ic_df["currency"].notna().any()

    group_cols: list[str] = []
    if has_ref:
        group_cols.append("reference")
    if has_cc:
        group_cols.append("company_code")
    if has_tp:
        group_cols.append("_ic_partner_key")
    if not group_cols:
        match_level = "fallback"
    elif has_tp:
        match_level = "exact"
    else:
        match_level = "aggregate"

    # ── 그룹별 집계 ──
    agg_key = (group_cols + ["_ic_type"]) if group_cols else ["_ic_type"]

    # Why: agg 딕셔너리를 사전 구성하여 조건부 컬럼 참조 버그 방지
    agg_spec: dict = {
        "sum_amount": ("_amount", "sum"),
        "row_indices": ("_orig_idx", list),
    }
    if "posting_date" in ic_df.columns:
        ic_df["_posting_date_ts"] = pd.to_datetime(ic_df["posting_date"], errors="coerce")
        agg_spec["median_date"] = ("_posting_date_ts", "median")
    if has_cur:
        agg_spec["currency_values"] = ("currency", _unique_nonempty_values)

    group_agg = ic_df.groupby(agg_key, dropna=False).agg(**agg_spec).reset_index()

    # ── 대응 그룹 매칭 ──
    result_rows: list[dict] = []
    rec_groups = group_agg[group_agg["_ic_type"] == "receivable"]
    pay_groups = group_agg[group_agg["_ic_type"] == "payable"]

    for _, rec_row in rec_groups.iterrows():
        match_mask = pd.Series(True, index=pay_groups.index)
        for col in group_cols:
            match_mask = _apply_group_filter(
                match_mask,
                pay_groups,
                rec_row,
                col,
                has_cc=has_cc,
                has_tp=has_tp,
            )
        matched_pays = pay_groups[match_mask]

        if matched_pays.empty:
            _append_unmatched(result_rows, rec_row, match_level)
        else:
            _append_matched(
                result_rows,
                rec_row,
                matched_pays,
                amount_tolerance,
                cross_currency_ratio_threshold,
                match_level,
                ic_df,
            )

    # Why: _append_matched()가 매칭된 payable 행도 result_rows에 삽입하므로
    #      seen_indices에 이미 포함됨. 아래 루프는 매칭 안 된 payable만 처리.
    seen_indices = {r["orig_idx"] for r in result_rows}
    for _, pay_row in pay_groups.iterrows():
        for idx in pay_row["row_indices"]:
            if idx not in seen_indices:
                result_rows.append(
                    {
                        "orig_idx": idx,
                        "has_counterpart": False,
                        "matched": False,
                        "diff_ratio": 1.0,
                        "match_level": match_level,
                        "date_diff_days": None,
                    }
                )

    if not result_rows:
        return pd.DataFrame(index=df.index)

    result_df = pd.DataFrame(result_rows).set_index("orig_idx")
    result_df = result_df[~result_df.index.duplicated(keep="first")]
    return result_df.reindex(df.index)


def _apply_group_filter(
    mask: pd.Series,
    pay_groups: pd.DataFrame,
    rec_row: pd.Series,
    col: str,
    *,
    has_cc: bool,
    has_tp: bool,
) -> pd.Series:
    """그룹 매칭 필터 적용 — 교차 매칭 포함."""
    if col == "_ic_partner_key" and has_cc:
        # Why: rec의 trading_partner → pay의 company_code 교차 매칭
        return mask & (pay_groups["company_code"] == rec_row.get("_ic_partner_key", ""))
    if col == "company_code" and has_tp:
        # Why: rec의 company_code → pay의 trading_partner 교차 매칭
        if "_ic_partner_key" in pay_groups.columns:
            return mask & (pay_groups["_ic_partner_key"] == rec_row.get("company_code", ""))
        return mask
    if col in pay_groups.columns:
        return mask & (pay_groups[col] == rec_row[col])
    return mask


def _append_unmatched(
    rows: list[dict],
    rec_row: pd.Series,
    match_level: str,
) -> None:
    """미매칭 결과 추가."""
    for idx in rec_row["row_indices"]:
        rows.append(
            {
                "orig_idx": idx,
                "has_counterpart": False,
                "matched": False,
                "diff_ratio": 1.0,
                "match_level": match_level,
                "date_diff_days": None,
            }
        )


def _append_matched(
    rows: list[dict],
    rec_row: pd.Series,
    matched_pays: pd.DataFrame,
    amount_tolerance: float,
    cross_currency_ratio_threshold: float,
    match_level: str,
    ic_df: pd.DataFrame,
) -> None:
    """매칭 결과 계산 + 추가."""
    counterpart_sum = matched_pays["sum_amount"].sum()
    rec_sum = rec_row["sum_amount"]
    max_val = max(abs(rec_sum), abs(counterpart_sum), 1e-10)
    diff_ratio = abs(rec_sum - counterpart_sum) / max_val
    matched = diff_ratio <= amount_tolerance

    currency_mismatch = _has_currency_mismatch(rec_row, matched_pays)

    # Why: 이종 통화 방어 — 명시 통화 불일치 또는 극단적 금액비면 비교 무의미
    ratio_a = abs(rec_sum) / max(abs(counterpart_sum), 1e-10)
    ratio_b = abs(counterpart_sum) / max(abs(rec_sum), 1e-10)
    cross_currency = currency_mismatch or (
        max_val > 0
        and (ratio_a > cross_currency_ratio_threshold or ratio_b > cross_currency_ratio_threshold)
    )

    date_diff = _calc_date_diff(rec_row, matched_pays, ic_df)

    row_data = {
        "has_counterpart": True,
        "matched": matched,
        "diff_ratio": diff_ratio,
        "match_level": match_level,
        "date_diff_days": date_diff,
        "cross_currency": cross_currency,
    }
    for idx in rec_row["row_indices"]:
        rows.append({"orig_idx": idx, **row_data})
    for _, pay_row in matched_pays.iterrows():
        for idx in pay_row["row_indices"]:
            rows.append({"orig_idx": idx, **row_data})


def _calc_date_diff(
    rec_row: pd.Series,
    matched_pays: pd.DataFrame,
    ic_df: pd.DataFrame,
) -> float | None:
    """매칭 쌍의 전기일 차이(일) 계산."""
    if "posting_date" not in ic_df.columns:
        return None
    if "median_date" not in rec_row.index:
        return None
    if "median_date" not in matched_pays.columns:
        return None
    try:
        rec_date = pd.Timestamp(rec_row["median_date"])
        pay_date = pd.Timestamp(matched_pays["median_date"].iloc[0])
        if pd.notna(rec_date) and pd.notna(pay_date):
            return abs((rec_date - pay_date).days)
    except Exception:
        pass
    return None


def _unique_nonempty_values(values: pd.Series) -> tuple[str, ...]:
    """Group-level distinct non-empty string values."""
    cleaned = values.dropna().astype(str).str.strip()
    return tuple(sorted(v for v in cleaned.unique().tolist() if v))


def _has_currency_mismatch(rec_row: pd.Series, matched_pays: pd.DataFrame) -> bool:
    """Return True when matched IC groups contain incompatible currencies."""
    if "currency_values" not in rec_row.index or "currency_values" not in matched_pays.columns:
        return False

    rec_currencies = set(rec_row.get("currency_values") or ())
    pay_currencies: set[str] = set()
    for values in matched_pays["currency_values"]:
        pay_currencies.update(values or ())

    combined = rec_currencies | pay_currencies
    if len(combined) > 1:
        return True
    if rec_currencies and pay_currencies and rec_currencies != pay_currencies:
        return True
    return False


# ── 서브룰 함수 ────────────────────────────────────────────────


def ic01_unmatched_intercompany(
    df: pd.DataFrame,
    *,
    match_df: pd.DataFrame,
    related_party_master: set[str] | None = None,
    partner_format_policy: dict | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """IC01: 미대사 내부거래 — evidence level (high / review) 분리 탐지.

    근거: IFRS 10 §B86 (그룹 내 거래 제거), K-IFRS 1110 (연결 작성 시 내부거래 제거),
          K-IFRS 1024 (특수관계자 공시), KICPA Issue Paper 46, ISA 600 (그룹감사).
          보조: ISA 550 §23 (특수관계자 거래의 사업상 합리성).

    Returns:
        (score, evidence_level, review_reason)
        - score: 0.0 또는 1.0 (high + review 합산 단일 series)
        - evidence_level: "high" / "review_stale" / "review" / ""
        - review_reason: "missing_partner" / "nonstandard_format" / "mapping_uncertain" / ""
    """
    index = df.index
    score = pd.Series(0.0, index=index)
    evidence_level = pd.Series("", index=index, dtype="object")
    review_reason = pd.Series("", index=index, dtype="object")

    ic_rows = bool_column(df, "is_intercompany")

    if match_df.empty or "has_counterpart" not in match_df.columns:
        return score, evidence_level, review_reason

    has_cp = match_df["has_counterpart"].astype("boolean").fillna(False).astype(bool)
    no_counterpart = ~has_cp
    candidate_base = ic_rows & no_counterpart

    if not candidate_base.any():
        return score, evidence_level, review_reason

    # company_code 부재 시 — partner 검증 불가능, 전체 review 로 분류
    if "trading_partner" not in df.columns or "company_code" not in df.columns:
        score.loc[candidate_base] = 1.0
        evidence_level.loc[candidate_base] = "review"
        review_reason.loc[candidate_base] = "mapping_uncertain"
        return score, evidence_level, review_reason

    policy = partner_format_policy or {}
    ic_regex = policy.get("ic_partner_regex")
    customer_regex = policy.get("customer_partner_regex")
    vendor_regex = policy.get("vendor_partner_regex")

    partner = df["trading_partner"].fillna("").astype(str).str.strip()
    has_partner = partner.ne("")

    # Customer/Vendor 코드 — IC 모집단에서 제외 (도메인적으로 IC 상대방이 아님)
    excluded = pd.Series(False, index=index)
    if customer_regex:
        excluded |= partner.str.match(customer_regex, na=False)
    if vendor_regex:
        excluded |= partner.str.match(vendor_regex, na=False)

    candidate = candidate_base & ~excluded

    # related_party_master 부재 시 — dataset 의 distinct company_code 로 폴백
    if related_party_master is None:
        master = set(df["company_code"].dropna().astype(str).str.strip().loc[lambda s: s.ne("")])
    else:
        master = {str(c).strip() for c in related_party_master if str(c).strip()}

    # 형식 검증 — ic_partner_regex 가 명시된 경우만 수행
    if ic_regex:
        valid_format = partner.str.match(ic_regex, na=False)
    else:
        valid_format = has_partner  # 형식 미지정 시 partner 존재만 확인

    # ── evidence 분류 ────────────────────────────────────────────
    missing_partner_mask = candidate & ~has_partner
    nonstandard_format_mask = candidate & has_partner & ~valid_format
    valid_partner_mask = candidate & has_partner & valid_format
    in_master = valid_partner_mask & partner.isin(master)
    high_mask = valid_partner_mask & ~partner.isin(master)
    mapping_uncertain_mask = in_master  # master 에 있는데 no_counterpart

    # review_reason 우선순위: missing_partner → nonstandard_format → mapping_uncertain
    review_reason.loc[mapping_uncertain_mask] = "mapping_uncertain"
    review_reason.loc[nonstandard_format_mask] = "nonstandard_format"
    review_reason.loc[missing_partner_mask] = "missing_partner"

    review_mask = missing_partner_mask | nonstandard_format_mask | mapping_uncertain_mask
    evidence_level.loc[review_mask] = "review"
    evidence_level.loc[high_mask] = "high"

    # 옵션3(timing 조건부): 결산기에서 벗어난 미대사는 타이밍(cutoff lag)으로 설명되지
    # 않으므로 review_stale 로 상향한다. is_period_end(결산 ±margin) 행은 양측 결산 시점
    # 차이로 짝이 늦게 올라올 수 있어 review(Low) 유지. is_period_end 컬럼 부재 시에는
    # 보수적으로 상향하지 않는다(전부 review 유지). 근거: ISA 600 그룹감사 — 결산 한참
    # 지난 그룹 내 미대사는 우선순위를 높여야 한다.
    if "is_period_end" in df.columns:
        near_period_end = bool_column(df, "is_period_end")
    else:
        near_period_end = pd.Series(True, index=index)
    stale_mask = review_mask & ~near_period_end
    evidence_level.loc[stale_mask] = "review_stale"

    # D065: review-only 신호는 flagged_rules / case seed / GT 평가에 confirmed
    # violation 으로 흐르면 안 된다. score 는 high 만 1.0, review 는 0.0 으로 유지하고
    # review 분기는 score_aggregator 가 evidence_level sidecar 만 보고 Low floor 부여한다.
    # 근거: AGENTS.md "review-only signals must not become confirmed violations"
    score.loc[high_mask] = 1.0

    return score, evidence_level, review_reason


def ic02_amount_mismatch(
    df: pd.DataFrame,
    *,
    match_df: pd.DataFrame,
    amount_tolerance: float = 0.05,
    max_diff_ratio: float = 0.10,
) -> pd.Series:
    """IC02: 금액 불일치 — 매칭됐으나 합계 차이 초과.

    Why: IC 거래는 양측 금액 일치가 원칙. 차이는 부정/오류 징후.
    """
    if match_df.empty or "has_counterpart" not in match_df.columns:
        return pd.Series(0.0, index=df.index)

    scores = pd.Series(0.0, index=df.index)
    has_cp = match_df["has_counterpart"].astype("boolean").fillna(False).astype(bool)
    over_tol = match_df["diff_ratio"].fillna(0.0) > amount_tolerance

    # Why: 이종 통화 추정 시 점수 억제
    if "cross_currency" in match_df.columns:
        xc = match_df["cross_currency"].astype("boolean").fillna(False).astype(bool)
    else:
        xc = pd.Series(False, index=match_df.index)
    target = has_cp & over_tol & ~xc

    if target.any():
        valid = scores.index.intersection(target.index[target])
        diff = match_df.loc[valid, "diff_ratio"].fillna(0.0)
        scores.loc[valid] = (diff / max_diff_ratio).clip(upper=1.0)

    return scores


def ic03_timing_gap(
    df: pd.DataFrame,
    *,
    match_df: pd.DataFrame,
    date_window_days: int = 5,
    max_day_diff: int = 30,
) -> pd.Series:
    """IC03: 시차 이상 — 매칭됐으나 전기일 차이 과대.

    Why: 동시 기표가 원칙인 IC 거래에서 시차는 기간귀속 오류 징후.
    """
    if "posting_date" not in df.columns:
        return pd.Series(0.0, index=df.index)
    if match_df.empty or "date_diff_days" not in match_df.columns:
        return pd.Series(0.0, index=df.index)

    scores = pd.Series(0.0, index=df.index)
    if "has_counterpart" in match_df.columns:
        has_cp = match_df["has_counterpart"].astype("boolean").fillna(False).astype(bool)
    else:
        has_cp = pd.Series(False, index=match_df.index)
    date_diff = pd.to_numeric(match_df["date_diff_days"], errors="coerce")
    has_date = date_diff.notna()
    over_window = date_diff.fillna(0) > date_window_days
    target = has_cp & has_date & over_window

    if target.any():
        valid = scores.index.intersection(target.index[target])
        days = date_diff.loc[valid].fillna(0)
        scores.loc[valid] = (days / max_day_diff).clip(upper=1.0)

    return scores


# ── PHASE2 internal probabilistic reconciliation (IC01~03 보강) ──
#
# Why: IC01/02/03 은 group key (reference/company_code/trading_partner) 동치 + amount tolerance
#      hard threshold 만 본다. 부분 일치 후보 pair (금액 근사 / 일자 근접 / 참조번호 유사 / 거래처
#      mapping cross) 를 확률적으로 점수화해 row-level anomaly probability 로 노출한다.
#      신규 점수는 canonical rule id 가 아닌 PHASE2 internal probability column 으로만 합류한다.
#      Phase 1 rule hit / DataSynth truth 라벨 / document_id 식별자는 입력으로 쓰지 않는다.


def load_matching_weights(audit_rules: dict, settings) -> dict[str, float]:
    """Return 4-term matching weights normalized to sum=1.

    Settings fields provide a fallback when YAML keys are missing. The four terms are
    ``amount``, ``date``, ``reference``, ``counterparty``.
    """
    patterns = audit_rules.get("patterns", audit_rules) if isinstance(audit_rules, dict) else {}
    ic_config = patterns.get("intercompany", {}) if isinstance(patterns, dict) else {}
    yaml_weights = ic_config.get("matching_weights", {}) if isinstance(ic_config, dict) else {}

    raw = {
        "amount": float(
            yaml_weights.get("amount", getattr(settings, "ic_prob_weight_amount", 0.40))
        ),
        "date": float(yaml_weights.get("date", getattr(settings, "ic_prob_weight_date", 0.25))),
        "reference": float(
            yaml_weights.get("reference", getattr(settings, "ic_prob_weight_reference", 0.20))
        ),
        "counterparty": float(
            yaml_weights.get("counterparty", getattr(settings, "ic_prob_weight_counterparty", 0.15))
        ),
    }
    total = sum(max(value, 0.0) for value in raw.values())
    if total <= 0:
        return {"amount": 0.40, "date": 0.25, "reference": 0.20, "counterparty": 0.15}
    return {key: max(value, 0.0) / total for key, value in raw.items()}


def load_candidate_blocking(audit_rules: dict, settings) -> dict[str, float | int]:
    """Return candidate-pair blocking parameters with settings fallback."""
    patterns = audit_rules.get("patterns", audit_rules) if isinstance(audit_rules, dict) else {}
    ic_config = patterns.get("intercompany", {}) if isinstance(patterns, dict) else {}
    blocking = ic_config.get("candidate_blocking", {}) if isinstance(ic_config, dict) else {}

    return {
        "amount_bucket_factor": float(
            blocking.get(
                "amount_bucket_factor", getattr(settings, "ic_prob_amount_bucket_factor", 1.5)
            )
        ),
        "max_candidates_per_row": int(
            blocking.get(
                "max_candidates_per_row",
                getattr(settings, "ic_prob_max_candidates_per_row", 50),
            )
        ),
        "reference_min_length": int(
            blocking.get(
                "reference_min_length",
                getattr(settings, "ic_prob_reference_min_length", 3),
            )
        ),
    }


def _ic_sides(df: pd.DataFrame, pair_map: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (receivable_rows, payable_rows) restricted to IC entries with positive amounts."""
    if "is_intercompany" not in df.columns or "gl_account" not in df.columns:
        empty = pd.DataFrame(index=pd.Index([], dtype=df.index.dtype))
        return empty, empty

    ic_mask = bool_column(df, "is_intercompany")
    if not ic_mask.any():
        empty = pd.DataFrame(index=pd.Index([], dtype=df.index.dtype))
        return empty, empty

    ic_df = df.loc[ic_mask].copy()
    ic_df["_ic_type"] = _classify_ic_type(ic_df["gl_account"], pair_map)
    ic_df = ic_df.dropna(subset=["_ic_type"])
    if ic_df.empty:
        empty = pd.DataFrame(index=pd.Index([], dtype=df.index.dtype))
        return empty, empty

    # Why: receivable → debit, payable → credit (match_ic_groups 와 동일 규약)
    debit_src = (
        ic_df["debit_amount"]
        if "debit_amount" in ic_df.columns
        else pd.Series(0.0, index=ic_df.index)
    )
    credit_src = (
        ic_df["credit_amount"]
        if "credit_amount" in ic_df.columns
        else pd.Series(0.0, index=ic_df.index)
    )
    debit = pd.to_numeric(debit_src, errors="coerce").fillna(0.0)
    credit = pd.to_numeric(credit_src, errors="coerce").fillna(0.0)
    ic_df["_amount"] = debit.where(ic_df["_ic_type"] == "receivable", credit).abs()
    ic_df = ic_df[ic_df["_amount"] > 0]
    ic_df["_ic_partner_key"] = _first_nonempty_counterparty(ic_df)

    rec = ic_df[ic_df["_ic_type"] == "receivable"].copy()
    pay = ic_df[ic_df["_ic_type"] == "payable"].copy()
    # Why: merge 후 suffix 분리(_orig_idx_rec / _orig_idx_pay)로 best-per-row 집계 키 보존.
    rec["_orig_idx"] = rec.index
    pay["_orig_idx"] = pay.index
    return rec, pay


def _bucket_series(amounts: pd.Series, factor: float) -> pd.Series:
    """Return log-spaced bucket id for each amount (integer)."""
    import math

    factor = max(float(factor), 1.0001)
    log_factor = math.log(factor)
    safe = amounts.clip(lower=1e-6).astype(float)
    return safe.map(lambda v: int(math.floor(math.log(v) / log_factor))).astype(int)


def _reference_similarity(rec_ref: str, pay_ref: str, *, min_length: int) -> float:
    """rapidfuzz token_set_ratio / 100 with min-length guard."""
    a = (rec_ref or "").strip()
    b = (pay_ref or "").strip()
    if len(a) < min_length or len(b) < min_length:
        return 0.0
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return 0.0
    return float(fuzz.token_set_ratio(a, b)) / 100.0


def _counterparty_mapping_score(rec_cc: str, rec_tp: str, pay_cc: str, pay_tp: str) -> float:
    """company_code ↔ trading_partner cross 일치 점수.

    - 양방향 cross (rec.tp == pay.cc AND rec.cc == pay.tp): 1.0
    - 한 방향만 cross: 0.5
    - 그 외 (양측 모두 비어 있거나 불일치): 0.0
    """
    rec_cc = (rec_cc or "").strip()
    rec_tp = (rec_tp or "").strip()
    pay_cc = (pay_cc or "").strip()
    pay_tp = (pay_tp or "").strip()
    forward = bool(rec_tp) and bool(pay_cc) and rec_tp == pay_cc
    reverse = bool(rec_cc) and bool(pay_tp) and rec_cc == pay_tp
    if forward and reverse:
        return 1.0
    if forward or reverse:
        return 0.5
    return 0.0


def _is_cross_currency(rec_cur: str, pay_cur: str) -> bool:
    rec = (rec_cur or "").strip().upper()
    pay = (pay_cur or "").strip().upper()
    if not rec or not pay:
        return False
    return rec != pay


def _classify_contract_tier(
    df: pd.DataFrame, *, reference_min_length: int = 3
) -> tuple[str, list[str]]:
    """Return (tier, missing_reasons) for the probabilistic surface.

    L1_exact     — company_code multi + trading_partner (any non-empty) + reference
                   (at least one row with stripped length ≥ reference_min_length)
    L2_aggregate — reference 부재 또는 모든 row 가 min_length 미만 (effective empty)
    L3_insufficient — company_code 단일/부재 (probabilistic 점수 0)

    Why reference_min_length: 짧은 reference ("x" 같은 1글자) 는 fuzz 매칭에 의미
        있는 신호가 없어 reference_similarity 가 항상 0 이 된다. 그런 데이터를
        L1 로 분류하면 reference weight 0.20 짜리 term 이 항상 0 인 채로 살아남아
        완전 매칭도 match_score 최대 0.80 으로 묶이고 정상 IC row 의
        ic_unmatched_prob 가 0.20 floor 로 남는 false positive 가 생긴다.
        effective empty 로 강등해서 L2 weight 재정규화 경로를 타게 한다.
    """
    reasons: list[str] = []
    if "company_code" not in df.columns:
        reasons.append("missing_company_code")
        return "L3_insufficient", reasons
    cc_distinct = (
        df["company_code"].fillna("").astype(str).str.strip().loc[lambda s: s.ne("")].nunique()
    )
    if cc_distinct < 2:
        reasons.append("single_company_code")
        return "L3_insufficient", reasons

    has_tp = (
        "trading_partner" in df.columns
        and df["trading_partner"].fillna("").astype(str).str.strip().ne("").any()
    )
    if not has_tp:
        reasons.append("missing_trading_partner")

    has_effective_ref = False
    if "reference" in df.columns:
        ref_lengths = df["reference"].fillna("").astype(str).str.strip().str.len()
        has_effective_ref = bool((ref_lengths >= int(reference_min_length)).any())
    if has_effective_ref:
        return "L1_exact", reasons
    reasons.append("missing_reference")
    return "L2_aggregate", reasons


def compute_probabilistic_pair_scores(
    df: pd.DataFrame,
    pair_map: dict[str, str],
    *,
    weights: dict[str, float],
    blocking: dict[str, float | int],
    max_day_diff: int,
    caps: dict[str, float] | None = None,
    timing_domain: dict[str, float | int] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Return (prob_scores, summary) for IC rows.

    The returned DataFrame is reindexed to ``df.index`` with three float columns:
    ``ic_unmatched_prob`` / ``ic_amount_prob`` / ``ic_timing_prob`` (all 0~1).

    Score semantics (no_candidate vs candidate mismatch 분리, 2026-05-24):

    - candidate mismatch: best matching candidate 가 존재하지만 amount/date/reference/
      counterparty 가 일치하지 않는 row. 실제 reconciliation gap 측정값으로 contract
      tier 별 mismatch cap 까지 강하게 반영한다 (L1 = 1.0, L2 = 0.7 default).
    - no_candidate: bucket × cp_block 일치하는 후보가 0 인 row. 정상 단방향 거래 또는
      matching evidence 부족과 양립하므로 weak review signal 로 cap 한다. weak cp_block
      (cc/tp 모두 비어 anchor 가 unique tag 인 row) 은 더 낮은 cap 으로 강등.
    - amount/timing_prob 는 candidate 가 있는 row 에서만 측정 (no_candidate 면 0).

    caps 인자가 None 이면 cap 미적용 (=레거시 동작, 모든 cap 1.0). 호출자는 보통
    ``load_contract_score_caps(audit_rules, settings)`` 를 넘긴다.
    """
    effective_caps = _resolve_caps(caps)
    summary: dict = {
        "contract_tier": "L3_insufficient",
        "missing_reasons": [],
        "pair_candidate_count": 0,
        "capped": False,
        "warnings": [],
        "weights": dict(weights),
        "params": {
            "amount_bucket_factor": float(blocking.get("amount_bucket_factor", 1.5)),
            "max_candidates_per_row": int(blocking.get("max_candidates_per_row", 50)),
            "reference_min_length": int(blocking.get("reference_min_length", 3)),
            "max_day_diff": int(max_day_diff),
        },
        "caps": dict(effective_caps),
        "no_candidate_count": 0,
        "weak_contract_count": 0,
        "capped_by_contract_count": 0,
    }

    empty_scores = pd.DataFrame(
        {
            "ic_unmatched_prob": pd.Series(0.0, index=df.index, dtype=float),
            "ic_amount_prob": pd.Series(0.0, index=df.index, dtype=float),
            "ic_timing_prob": pd.Series(0.0, index=df.index, dtype=float),
        },
        index=df.index,
    )

    if not pair_map:
        summary["warnings"].append("empty_pair_map")
        return empty_scores, summary

    ref_min_len_for_tier = int(blocking.get("reference_min_length", 3))
    tier, reasons = _classify_contract_tier(df, reference_min_length=ref_min_len_for_tier)
    summary["contract_tier"] = tier
    summary["missing_reasons"] = reasons
    if tier == "L3_insufficient":
        summary["warnings"].append("insufficient_matching_contract")
        return empty_scores, summary

    # L2_aggregate 면 reference weight 0 + 나머지 합 1 재정규화 (계약 보존)
    effective_weights = _renormalize_weights_for_tier(weights, tier)
    summary["weights_effective"] = dict(effective_weights)

    rec, pay = _ic_sides(df, pair_map)
    if rec.empty and pay.empty:
        summary["warnings"].append("no_ic_rows")
        return empty_scores, summary

    factor = float(blocking.get("amount_bucket_factor", 1.5))
    max_cand = int(blocking.get("max_candidates_per_row", 50))
    ref_min_len = int(blocking.get("reference_min_length", 3))

    rec = rec.assign(_bucket=_bucket_series(rec["_amount"], factor))
    pay = pay.assign(_bucket=_bucket_series(pay["_amount"], factor))
    # cp block key: pre-merge selectivity (rec.trading_partner ↔ pay.company_code)
    rec = rec.assign(_cp_block=_build_cp_block_key(rec, kind="rec"))
    pay = pay.assign(_cp_block=_build_cp_block_key(pay, kind="pay"))

    # blocking join: (bucket, cp_block) × bucket ±1 offset
    # Why: amount bucket 만으로 merge 하면 같은 bucket 에 IC row 가 몰릴 때 O(n²)
    #      DataFrame 이 cap 전에 만들어진다. cp_block 을 join key 에 포함해 selectivity
    #      를 먼저 좁히고, merge 직후 date window 로 추가 prune + per-rec cap 으로
    #      메모리/시간 폭증을 방어한다.
    pair_frames: list[pd.DataFrame] = []
    candidates_before_cap = 0
    for offset in (-1, 0, 1):
        rec_left = rec.assign(_join_bucket=rec["_bucket"] + offset)
        merged = rec_left.merge(
            pay,
            left_on=["_join_bucket", "_cp_block"],
            right_on=["_bucket", "_cp_block"],
            how="inner",
            suffixes=("_rec", "_pay"),
        )
        if merged.empty:
            continue
        # early date-window prune (range join은 pandas 기본 미지원 → merge 직후 필터)
        if "posting_date_rec" in merged.columns and "posting_date_pay" in merged.columns:
            d_rec_e = pd.to_datetime(merged["posting_date_rec"], errors="coerce")
            d_pay_e = pd.to_datetime(merged["posting_date_pay"], errors="coerce")
            day_diff_e = (d_rec_e - d_pay_e).abs().dt.days.fillna(max_day_diff)
            merged = merged[day_diff_e.le(float(max_day_diff))]
            if merged.empty:
                continue
        candidates_before_cap += int(len(merged))
        # per-merge per-rec cap (offset 별 amount 가까운 top-K 만 유지)
        merged = _apply_candidate_cap(merged, rec_index_col="_amount_rec", max_per_row=max_cand)
        if not merged.empty:
            pair_frames.append(merged)

    if not pair_frames:
        # IC rows 존재하지만 후보 0건 — 전체 no_candidate review signal.
        # cap 분기와 동일한 contract tier × cp_block 기반 cap 적용.
        summary["pair_candidate_count"] = 0
        no_cand_cap_value = float(
            effective_caps["no_candidate_l1" if tier == "L1_exact" else "no_candidate_l2"]
        )
        weak_cap_value = float(effective_caps["weak_contract"])
        unmatched = empty_scores.copy()

        rec_weak_zero = _is_weak_cp_block(rec["_cp_block"]) if not rec.empty else pd.Series([])
        pay_weak_zero = _is_weak_cp_block(pay["_cp_block"]) if not pay.empty else pd.Series([])
        summary["weak_contract_count"] = int(rec_weak_zero.sum() + pay_weak_zero.sum())
        summary["no_candidate_count"] = int(len(rec.index) + len(pay.index))

        if not rec.empty:
            rec_cap_series = pd.Series(no_cand_cap_value, index=rec.index, dtype=float).where(
                ~rec_weak_zero.astype(bool), weak_cap_value
            )
            unmatched.loc[rec.index, "ic_unmatched_prob"] = rec_cap_series
        if not pay.empty:
            pay_cap_series = pd.Series(no_cand_cap_value, index=pay.index, dtype=float).where(
                ~pay_weak_zero.astype(bool), weak_cap_value
            )
            unmatched.loc[pay.index, "ic_unmatched_prob"] = pay_cap_series
        return unmatched, summary

    pairs = pd.concat(pair_frames, ignore_index=False, sort=False)
    # final per-rec cap across all offsets
    pairs = _apply_candidate_cap(pairs, rec_index_col="_amount_rec", max_per_row=max_cand)
    summary["pair_candidate_count"] = int(len(pairs))
    if candidates_before_cap > len(pairs):
        summary["capped"] = True
        summary["warnings"].append(
            f"candidate_capped: {candidates_before_cap} → {len(pairs)} pairs"
        )

    # score components (vectorized)
    rec_amt = pairs["_amount_rec"].astype(float)
    pay_amt = pairs["_amount_pay"].astype(float)
    cur_rec = pairs.get("currency_rec")
    cur_pay = pairs.get("currency_pay")
    if cur_rec is None or cur_pay is None:
        cross_currency = pd.Series(False, index=pairs.index)
    else:
        cross_currency = pd.Series(
            [
                _is_cross_currency(str(a) if pd.notna(a) else "", str(b) if pd.notna(b) else "")
                for a, b in zip(cur_rec, cur_pay)
            ],
            index=pairs.index,
        )

    max_amt = pd.concat([rec_amt.abs(), pay_amt.abs()], axis=1).max(axis=1).clip(lower=1e-10)
    amount_sim = (1.0 - (rec_amt - pay_amt).abs() / max_amt).clip(lower=0.0, upper=1.0)
    amount_sim = amount_sim.where(~cross_currency, 0.0)

    if "posting_date_rec" in pairs.columns and "posting_date_pay" in pairs.columns:
        d_rec = pd.to_datetime(pairs["posting_date_rec"], errors="coerce")
        d_pay = pd.to_datetime(pairs["posting_date_pay"], errors="coerce")
        day_diff = (d_rec - d_pay).abs().dt.days.fillna(max_day_diff).astype(float)
    else:
        day_diff = pd.Series(float(max_day_diff), index=pairs.index)
    date_prox = (1.0 - day_diff.clip(upper=float(max_day_diff)) / float(max(max_day_diff, 1))).clip(
        lower=0.0, upper=1.0
    )

    ref_rec = pairs.get("reference_rec", pd.Series("", index=pairs.index)).fillna("").astype(str)
    ref_pay = pairs.get("reference_pay", pd.Series("", index=pairs.index)).fillna("").astype(str)
    ref_rec_clean = ref_rec.str.strip()
    ref_pay_clean = ref_pay.str.strip()
    # pair-level effective reference: 양측 모두 stripped len ≥ min_length 인 pair 한정.
    # Why: tier 가 L1 이어도 mixed reference 배치 (일부 row 만 reference 보유) 에서는
    #      reference 없는 pair 가 reference_sim=0 + 고정 reference weight 0.20 으로
    #      match_score 최대 0.80 floor 에 묶이는 false positive 가 발생. 그 pair 에는
    #      reference weight 를 끄고 amount/date/counterparty 만으로 재정규화한다.
    pair_ref_active = (ref_rec_clean.str.len() >= int(ref_min_len)) & (
        ref_pay_clean.str.len() >= int(ref_min_len)
    )
    reference_sim = pd.Series(
        [
            _reference_similarity(a, b, min_length=ref_min_len)
            for a, b in zip(ref_rec_clean, ref_pay_clean)
        ],
        index=pairs.index,
    )

    cc_rec = pairs.get("company_code_rec", pd.Series("", index=pairs.index)).fillna("").astype(str)
    cc_pay = pairs.get("company_code_pay", pd.Series("", index=pairs.index)).fillna("").astype(str)
    tp_rec = pairs.get("_ic_partner_key_rec")
    if tp_rec is None:
        tp_rec = pairs.get("trading_partner_rec", pd.Series("", index=pairs.index))
    tp_rec = tp_rec.fillna("").astype(str)
    tp_pay = pairs.get("_ic_partner_key_pay")
    if tp_pay is None:
        tp_pay = pairs.get("trading_partner_pay", pd.Series("", index=pairs.index))
    tp_pay = tp_pay.fillna("").astype(str)
    cp_score = pd.Series(
        [
            _counterparty_mapping_score(rcc, rtp, pcc, ptp)
            for rcc, rtp, pcc, ptp in zip(cc_rec, tp_rec, cc_pay, tp_pay)
        ],
        index=pairs.index,
    )

    # pair-level effective weight: tier baseline 위에 pair_ref_active 로 한 단계 더 조정.
    # tier 가 L2 면 effective_weights["reference"]=0 이라 pair_ref_active 와 무관하게 항상 0.
    # tier 가 L1 이면 active pair 는 baseline 그대로, inactive pair 는 reference weight 를
    # amount/date/counterparty 비율로 자동 재분배 (sum=1 보장).
    w_amt_base = float(effective_weights["amount"])
    w_date_base = float(effective_weights["date"])
    w_cp_base = float(effective_weights["counterparty"])
    w_ref_base = float(effective_weights["reference"])

    active_mask = pair_ref_active.astype(float)
    pair_total = w_amt_base + w_date_base + w_cp_base + w_ref_base * active_mask
    pair_total = pair_total.where(pair_total > 0, 1.0)
    pair_w_amt = w_amt_base / pair_total
    pair_w_date = w_date_base / pair_total
    pair_w_cp = w_cp_base / pair_total
    pair_w_ref = (w_ref_base * active_mask) / pair_total

    match_score = (
        pair_w_amt * amount_sim
        + pair_w_date * date_prox
        + pair_w_ref * reference_sim
        + pair_w_cp * cp_score
    ).clip(lower=0.0, upper=1.0)

    # row aggregation: rec/pay 각각 best pair 기준
    rec_idx_col = "_orig_idx_rec" if "_orig_idx_rec" in pairs.columns else None
    pay_idx_col = "_orig_idx_pay" if "_orig_idx_pay" in pairs.columns else None
    if rec_idx_col is None or pay_idx_col is None:
        # merge suffix 가 다른 컬럼명을 만들었을 때 안전 폴백
        return empty_scores, summary

    # carry counterparty / reference / posting_date 도 함께 — timing 도메인 분리에 사용.
    best_per_row = pd.DataFrame(
        {
            "rec_idx": pairs[rec_idx_col].values,
            "pay_idx": pairs[pay_idx_col].values,
            "match_score": match_score.values,
            "amount_sim": amount_sim.values,
            "date_prox": date_prox.values,
            "cp_score": cp_score.values,
            "reference_sim": reference_sim.values,
            "pair_ref_active": pair_ref_active.astype(bool).values,
            "posting_date_rec": d_rec.values
            if "posting_date_rec" in pairs.columns
            else pd.Series(pd.NaT, index=pairs.index).values,
            "posting_date_pay": d_pay.values
            if "posting_date_pay" in pairs.columns
            else pd.Series(pd.NaT, index=pairs.index).values,
        }
    )

    # match_score 가 가장 큰 단일 후보 row 의 component 를 사용 (가짜 best 방지)
    rec_best = _pick_best_match_per_group(best_per_row, group_col="rec_idx")
    pay_best = _pick_best_match_per_group(best_per_row, group_col="pay_idx")

    effective_timing = _resolve_timing_domain(timing_domain)
    summary["timing_domain"] = dict(effective_timing)
    summary["timing_grace_hits"] = 0
    summary["timing_weak_cap_hits"] = 0

    out = empty_scores.copy()

    # contract tier 별 cap 결정
    if tier == "L1_exact":
        no_cand_cap = float(effective_caps["no_candidate_l1"])
        mismatch_cap = float(effective_caps["l1_mismatch"])
    else:  # L2_aggregate
        no_cand_cap = float(effective_caps["no_candidate_l2"])
        mismatch_cap = float(effective_caps["l2_mismatch"])
    weak_cap = float(effective_caps["weak_contract"])

    # weak cp_block 마스크 (cc/tp 모두 비어 unique tag 처리된 row)
    rec_weak_cp = _is_weak_cp_block(rec["_cp_block"])
    pay_weak_cp = _is_weak_cp_block(pay["_cp_block"])
    summary["weak_contract_count"] = int(rec_weak_cp.sum() + pay_weak_cp.sum())

    # no_candidate row 분리
    rec_with_cand = set(rec_best.index)
    pay_with_cand = set(pay_best.index)
    rec_no_cand = rec.index.difference(rec_with_cand)
    pay_no_cand = pay.index.difference(pay_with_cand)
    summary["no_candidate_count"] = int(len(rec_no_cand) + len(pay_no_cand))

    # no_candidate: contract tier cap (weak cp_block 이면 weak_cap 으로 강등).
    # ic_amount_prob / ic_timing_prob 는 candidate 가 없어 mismatch evidence 자체가 없으므로 0 유지.
    if len(rec_no_cand) > 0:
        rec_caps = pd.Series(no_cand_cap, index=rec_no_cand, dtype=float)
        rec_weak_for_no_cand = rec_weak_cp.reindex(rec_no_cand).fillna(False).astype(bool)
        rec_caps = rec_caps.where(~rec_weak_for_no_cand, weak_cap)
        out.loc[rec_no_cand, "ic_unmatched_prob"] = rec_caps
    if len(pay_no_cand) > 0:
        pay_caps = pd.Series(no_cand_cap, index=pay_no_cand, dtype=float)
        pay_weak_for_no_cand = pay_weak_cp.reindex(pay_no_cand).fillna(False).astype(bool)
        pay_caps = pay_caps.where(~pay_weak_for_no_cand, weak_cap)
        # 양측 모두에서 no_cand 일 가능성은 인덱스 다름 (rec/pay disjoint) 이라 max 불필요
        out.loc[pay_no_cand, "ic_unmatched_prob"] = pay_caps

    # candidate mismatch: ic_unmatched_prob 만 mismatch_cap 적용, amount/timing 은 원본.
    # ic_timing_prob 는 도메인 분리 (month-end grace + amount/cp/ref strong → weak_cap).
    capped_hits = 0
    timing_grace_hits = 0
    timing_weak_hits = 0
    for idx, row in rec_best.iterrows():
        raw_unmatched = float(1.0 - row["match_score"])
        if raw_unmatched > mismatch_cap:
            capped_hits += 1
        out.at[idx, "ic_unmatched_prob"] = min(raw_unmatched, mismatch_cap)
        out.at[idx, "ic_amount_prob"] = float(1.0 - row["amount_sim"])
        raw_timing = float(1.0 - row["date_prox"])
        domain_timing = _domain_timing_prob(
            raw_timing,
            amount_sim=float(row.get("amount_sim", 0.0)),
            cp_score=float(row.get("cp_score", 0.0)),
            reference_sim=float(row.get("reference_sim", 0.0)),
            pair_ref_active=bool(row.get("pair_ref_active", False)),
            rec_date=row.get("posting_date_rec"),
            pay_date=row.get("posting_date_pay"),
            timing_params=effective_timing,
        )
        if raw_timing > 0 and domain_timing == 0.0:
            timing_grace_hits += 1
        elif raw_timing > 0 and domain_timing < raw_timing:
            timing_weak_hits += 1
        out.at[idx, "ic_timing_prob"] = domain_timing
    for idx, row in pay_best.iterrows():
        raw_unmatched = float(1.0 - row["match_score"])
        if raw_unmatched > mismatch_cap:
            capped_hits += 1
        capped_unmatched = min(raw_unmatched, mismatch_cap)
        out.at[idx, "ic_unmatched_prob"] = float(
            max(out.at[idx, "ic_unmatched_prob"], capped_unmatched)
        )
        out.at[idx, "ic_amount_prob"] = float(
            max(out.at[idx, "ic_amount_prob"], 1.0 - row["amount_sim"])
        )
        raw_timing = float(1.0 - row["date_prox"])
        domain_timing = _domain_timing_prob(
            raw_timing,
            amount_sim=float(row.get("amount_sim", 0.0)),
            cp_score=float(row.get("cp_score", 0.0)),
            reference_sim=float(row.get("reference_sim", 0.0)),
            pair_ref_active=bool(row.get("pair_ref_active", False)),
            rec_date=row.get("posting_date_rec"),
            pay_date=row.get("posting_date_pay"),
            timing_params=effective_timing,
        )
        if raw_timing > 0 and domain_timing == 0.0:
            timing_grace_hits += 1
        elif raw_timing > 0 and domain_timing < raw_timing:
            timing_weak_hits += 1
        out.at[idx, "ic_timing_prob"] = float(max(out.at[idx, "ic_timing_prob"], domain_timing))
    summary["capped_by_contract_count"] = int(capped_hits)
    summary["timing_grace_hits"] = int(timing_grace_hits)
    summary["timing_weak_cap_hits"] = int(timing_weak_hits)

    return out, summary


def _apply_candidate_cap(
    pairs: pd.DataFrame, *, rec_index_col: str, max_per_row: int
) -> pd.DataFrame:
    """row 당 amount 가까운 순으로 max_per_row 후보만 유지.

    Why: per-merge 단계와 final concat 단계 모두에서 호출. 같은 bucket × cp_block
         에 IC row 가 몰리면 O(n²) DataFrame 이 생기기 전에 amount distance 가까운
         top-K 만 유지해서 메모리/시간 폭증을 방어한다.
    """
    if pairs.empty or max_per_row <= 0:
        return pairs
    if "_orig_idx_rec" not in pairs.columns:
        return pairs
    rec_amt = pairs[rec_index_col].astype(float)
    pay_amt = pairs["_amount_pay"].astype(float)
    amt_dist = (rec_amt - pay_amt).abs()
    pairs = pairs.assign(_amt_dist=amt_dist)
    # rec_idx 별 nsmallest. groupby+head 가 효율적.
    pairs = pairs.sort_values("_amt_dist", kind="mergesort")
    pairs = pairs.groupby("_orig_idx_rec", group_keys=False, sort=False).head(max_per_row)
    return pairs.drop(columns=["_amt_dist"])


def _build_cp_block_key(side: pd.DataFrame, *, kind: str) -> pd.Series:
    """Return counterparty blocking key for pre-merge selectivity.

    rec 측 anchor = trading_partner (있으면, 없으면 company_code)
    pay 측 anchor = company_code   (있으면, 없으면 trading_partner)

    rec.trading_partner == pay.company_code 가 cross-mapping 의 본 매칭 조건이므로
    이걸 join key 에 포함해 merge 가 같은 anchor 의 후보로만 좁혀지게 한다.
    빈 키는 unique tag 로 치환해 cross-empty merge (모든 빈 row 끼리 매칭) 폭증을
    차단한다.
    """
    if kind == "rec":
        primary = _first_nonempty_counterparty(side)
        secondary = side.get("company_code")
        empty_tag = "__rec_NA_"
    else:
        primary = side.get("company_code")
        secondary = _first_nonempty_counterparty(side)
        empty_tag = "__pay_NA_"

    def _clean(value: pd.Series | None) -> pd.Series:
        if value is None:
            return pd.Series("", index=side.index)
        return value.fillna("").astype(str).str.strip()

    p = _clean(primary)
    s = _clean(secondary)
    block = p.where(p.ne(""), s)
    empty_mask = block.eq("")
    if empty_mask.any():
        unique_tags = pd.Series([f"{empty_tag}{idx}" for idx in side.index], index=side.index)
        block = block.where(~empty_mask, unique_tags)
    return block


_BEST_PER_ROW_CARRY_COLS: tuple[str, ...] = (
    "match_score",
    "amount_sim",
    "date_prox",
    "cp_score",
    "reference_sim",
    "pair_ref_active",
    "posting_date_rec",
    "posting_date_pay",
)


def _pick_best_match_per_group(best_per_row: pd.DataFrame, *, group_col: str) -> pd.DataFrame:
    """Pick the row with maximum match_score per group; return its components.

    Why: amount_sim, date_prox 를 각각 따로 max 집계하면 "A 후보는 금액만 좋고
         B 후보는 날짜만 좋다" 같은 case 에서 가짜 best score 가 만들어진다.
         match_score 가 가장 큰 단일 후보 row 를 골라 그 component 를 그대로
         쓰면 의미가 일관된다 (best pair = primary score 최대 pair).
         timing 도메인 분리를 위해 cp_score / reference_sim / pair_ref_active /
         posting_date_rec/pay 도 함께 carry.
    """
    available = [c for c in _BEST_PER_ROW_CARRY_COLS if c in best_per_row.columns]
    if best_per_row.empty:
        return best_per_row.set_index(group_col)[available]
    best_positions = best_per_row.groupby(group_col, sort=False)["match_score"].idxmax()
    selected = best_per_row.loc[best_positions.values, [group_col] + available]
    return selected.set_index(group_col)


_WEAK_CP_BLOCK_TAGS: tuple[str, ...] = ("__rec_NA_", "__pay_NA_")

_DEFAULT_CONTRACT_CAPS: dict[str, float] = {
    "l1_mismatch": 1.0,
    "l2_mismatch": 1.0,
    "no_candidate_l1": 1.0,
    "no_candidate_l2": 1.0,
    "weak_contract": 1.0,
    "l3": 0.0,
}

# timing domain default — None → legacy raw timing (grace 0, cap 1.0).
# 호출자가 dict 으로 넘기면 month-end grace + amount/cp/ref strong → weak_cap 적용.
_DEFAULT_TIMING_DOMAIN: dict[str, float | int] = {
    "grace_window_days": 0,  # 0 = grace 비활성 (legacy 동작)
    "month_end_window_days": 0,
    "amount_strong_min": 1.0,  # 1.0 이면 amount strong 절대 만족 안 함 → raw 유지
    "cp_strong_min": 1.0,
    "ref_strong_min": 1.0,
    "only_weak_cap": 1.0,  # 1.0 = cap 없음
}


def load_timing_domain(audit_rules: dict, settings) -> dict[str, float | int]:
    """Return timing domain params from settings (fallback) or YAML override.

    Why: ic_timing_prob 가 candidate 가 있는 row 의 day_diff 만 보고 단독 1.0 박는
         legacy 동작은 정상 결산 close lag 를 의심 timing gap 과 동일 점수로 올린다.
         settings 또는 audit_rules 에서 도메인 임계값을 받아 month-end grace +
         amount/cp/ref 강한 매칭 시 weak_cap 적용.
    """
    patterns = audit_rules.get("patterns", audit_rules) if isinstance(audit_rules, dict) else {}
    ic_config = patterns.get("intercompany", {}) if isinstance(patterns, dict) else {}
    yaml_timing = ic_config.get("timing_domain", {}) if isinstance(ic_config, dict) else {}

    def _read_int(yaml_key: str, settings_key: str, default: int) -> int:
        value = yaml_timing.get(yaml_key, getattr(settings, settings_key, default))
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _read_float(yaml_key: str, settings_key: str, default: float) -> float:
        value = yaml_timing.get(yaml_key, getattr(settings, settings_key, default))
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    return {
        "grace_window_days": _read_int("grace_window_days", "ic_timing_grace_window_days", 14),
        "month_end_window_days": _read_int(
            "month_end_window_days", "ic_timing_month_end_window_days", 7
        ),
        "amount_strong_min": _read_float("amount_strong_min", "ic_timing_amount_strong_min", 0.95),
        "cp_strong_min": _read_float("cp_strong_min", "ic_timing_cp_strong_min", 0.5),
        "ref_strong_min": _read_float("ref_strong_min", "ic_timing_ref_strong_min", 0.7),
        "only_weak_cap": _read_float("only_weak_cap", "ic_timing_only_weak_cap", 0.3),
    }


def _resolve_timing_domain(
    timing_domain: dict[str, float | int] | None,
) -> dict[str, float | int]:
    """timing_domain None → legacy raw timing 동작. 누락 키는 default 폴백."""
    if timing_domain is None:
        return dict(_DEFAULT_TIMING_DOMAIN)
    out = dict(_DEFAULT_TIMING_DOMAIN)
    for key in _DEFAULT_TIMING_DOMAIN:
        if key in timing_domain:
            try:
                if isinstance(_DEFAULT_TIMING_DOMAIN[key], int):
                    out[key] = int(timing_domain[key])
                else:
                    out[key] = float(timing_domain[key])
            except (TypeError, ValueError):
                continue
    return out


def _is_month_close_lag(
    rec_date,
    pay_date,
    *,
    grace_window_days: int,
    month_end_window_days: int,
) -> bool:
    """receivable / payable date 가 월말±N일 + 다음달 월초±N일 close lag 패턴인가.

    Why: K-IFRS / KICPA cutoff 부근 정상 결산 lag (rec 월말 인식 → pay 다음달 인식)
         은 day_diff ≥ 30 일 이어도 audit 의심 신호 아님. 두 dates 모두 NaN 이면 False.
    """
    if grace_window_days <= 0 or month_end_window_days <= 0:
        return False
    if pd.isna(rec_date) or pd.isna(pay_date):
        return False
    try:
        rec_ts = pd.Timestamp(rec_date)
        pay_ts = pd.Timestamp(pay_date)
    except (TypeError, ValueError):
        return False
    delta = abs((rec_ts - pay_ts).days)
    if delta > grace_window_days:
        return False
    rec_dom, pay_dom = rec_ts.day, pay_ts.day
    rec_dim, pay_dim = rec_ts.daysinmonth, pay_ts.daysinmonth
    rec_is_eom = rec_dom >= (rec_dim - month_end_window_days + 1)
    pay_is_bom = pay_dom <= month_end_window_days
    pay_is_eom = pay_dom >= (pay_dim - month_end_window_days + 1)
    rec_is_bom = rec_dom <= month_end_window_days
    return (rec_is_eom and pay_is_bom) or (pay_is_eom and rec_is_bom)


def _domain_timing_prob(
    raw_timing: float,
    *,
    amount_sim: float,
    cp_score: float,
    reference_sim: float,
    pair_ref_active: bool,
    rec_date,
    pay_date,
    timing_params: dict[str, float | int],
) -> float:
    """raw_timing 에 도메인 grace / weak_cap 적용.

    Returns 0 if month-end close lag, weak_cap 이하 if 모든 evidence strong, 그 외 raw.
    """
    if raw_timing <= 0.0:
        return 0.0
    if _is_month_close_lag(
        rec_date,
        pay_date,
        grace_window_days=int(timing_params["grace_window_days"]),
        month_end_window_days=int(timing_params["month_end_window_days"]),
    ):
        return 0.0
    amount_strong = amount_sim >= float(timing_params["amount_strong_min"])
    cp_strong = cp_score >= float(timing_params["cp_strong_min"])
    # reference 가 active 일 때만 reference_sim 기준 적용. inactive (pair 한쪽 ref 없음)
    # 면 reference 강도 판단 불가하므로 strong 으로 간주하지 않음.
    ref_strong = bool(pair_ref_active) and (reference_sim >= float(timing_params["ref_strong_min"]))
    weak_cap = float(timing_params["only_weak_cap"])
    if amount_strong and cp_strong and ref_strong:
        return min(raw_timing, weak_cap)
    return raw_timing


def _resolve_caps(caps: dict[str, float] | None) -> dict[str, float]:
    """caps 인자가 없으면 cap 미적용 (legacy 호환), 있으면 누락 키만 1.0 폴백."""
    if caps is None:
        return dict(_DEFAULT_CONTRACT_CAPS)
    out = dict(_DEFAULT_CONTRACT_CAPS)
    for key, value in caps.items():
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def load_contract_score_caps(audit_rules: dict, settings) -> dict[str, float]:
    """Return contract-tier score caps with settings fallback.

    각 key 는 audit evidence strength 기준 cap (truth recall 튜닝 금지).
    keys: l1_mismatch / l2_mismatch / no_candidate_l1 / no_candidate_l2 /
          weak_contract / l3.
    """
    patterns = audit_rules.get("patterns", audit_rules) if isinstance(audit_rules, dict) else {}
    ic_config = patterns.get("intercompany", {}) if isinstance(patterns, dict) else {}
    yaml_caps = ic_config.get("contract_score_caps", {}) if isinstance(ic_config, dict) else {}

    def _read(key: str, fallback: str, default: float) -> float:
        value = yaml_caps.get(key, getattr(settings, fallback, default))
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    return {
        "l1_mismatch": _read("l1_mismatch", "ic_prob_l1_mismatch_cap", 1.0),
        "l2_mismatch": _read("l2_mismatch", "ic_prob_l2_mismatch_cap", 0.7),
        "no_candidate_l1": _read("no_candidate_l1", "ic_prob_no_candidate_cap_l1", 0.5),
        "no_candidate_l2": _read("no_candidate_l2", "ic_prob_no_candidate_cap_l2", 0.3),
        "weak_contract": _read("weak_contract", "ic_prob_weak_contract_cap", 0.3),
        "l3": _read("l3", "ic_prob_l3_cap", 0.0),
    }


def _is_weak_cp_block(block_series: pd.Series) -> pd.Series:
    """Return boolean mask of rows whose cp_block is a unique tag (no real anchor).

    `_build_cp_block_key` 가 cc/tp 모두 비어있는 row 를 `__rec_NA_{idx}` /
    `__pay_NA_{idx}` unique tag 로 치환하므로 그 prefix 로 weak contract 를 식별한다.
    """
    if block_series.empty:
        return pd.Series(False, index=block_series.index, dtype=bool)
    as_str = block_series.fillna("").astype(str)
    mask = pd.Series(False, index=block_series.index, dtype=bool)
    for tag in _WEAK_CP_BLOCK_TAGS:
        mask = mask | as_str.str.startswith(tag)
    return mask


def _renormalize_weights_for_tier(weights: dict[str, float], tier: str) -> dict[str, float]:
    """L2_aggregate 면 reference weight 0 + 나머지 합 1 재정규화.

    Why: docs/spec/phase2_reorgani.md §5 L2 계약은 "reference term 0 + 나머지 weight
         재정규화". 재정규화 없이 weight 0.20 짜리 reference 만 잃으면 완전 매칭
         row 도 match_score 최대 0.80 → ic_unmatched_prob 최소 0.20 으로 남아
         정상 IC row 가 모두 nonzero family score 를 받는 false positive 가 생긴다.
    """
    if tier != "L2_aggregate":
        return dict(weights)
    effective = dict(weights)
    effective["reference"] = 0.0
    total = sum(max(value, 0.0) for value in effective.values())
    if total <= 0:
        return dict(weights)
    return {key: max(value, 0.0) / total for key, value in effective.items()}


# ── PHASE2 internal: single-document reciprocal IC flow (additive surface) ──
#
# Why: probabilistic reconciliation (ic_*_prob) 은 N:M 양측 doc 매칭이 전제. 정상 IC 는
#      receivable 또는 payable 한 쪽 GL 만 단일 doc 에 기록 → 다른 doc 의 counterpart 와
#      reconciliation 필요. 같은 doc 안에 receivable + payable GL pair 가 self-balanced 로
#      동시 존재하면 양측 검증을 우회한 단일-회사 임의 양변 기표.
#      ISA 550 §23 (related-party 사업상 합리성), PCAOB AS 2401 (management override).
#
# 입력은 raw df + pair_map + settings + audit_rules 만. is_fraud / is_anomaly / mutation_* /
# manipulation_scenario / flagged_rules / priority_score / review_rules 는 받지 않는다.


def _classify_rec_pay_prefixes(pair_map: dict[str, str]) -> tuple[set[str], set[str]]:
    """pair_map 양방향 dict 에서 receivable / payable prefix set 추출.

    Why: load_ic_pairs 는 양방향이라 prefix 순서를 잃는다. YAML pairs 의 receivable 키가
         먼저 들어온 순서를 보존하기 위해 seen 으로 첫 등장만 receivable 로 분류한다.
    """
    receivable: set[str] = set()
    payable: set[str] = set()
    seen: set[str] = set()
    for k, v in pair_map.items():
        if k in seen or v in seen:
            continue
        receivable.add(str(k))
        payable.add(str(v))
        seen.update([k, v])
    return receivable, payable


def _gl_starts_with_any(gl_series: pd.Series, prefixes: set[str]) -> pd.Series:
    """Vectorized prefix match — 빈 prefix set 이면 전부 False."""
    if not prefixes:
        return pd.Series(False, index=gl_series.index, dtype=bool)
    gl = gl_series.fillna("").astype(str)
    mask = pd.Series(False, index=gl.index, dtype=bool)
    for p in prefixes:
        mask = mask | gl.str.startswith(p)
    return mask


def _first_matching_prefix(value: object, prefixes: set[str]) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    for prefix in sorted(prefixes, key=len, reverse=True):
        if text.startswith(prefix):
            return prefix
    return ""


def _doc_amount_symmetry(
    rec_sum_by_doc: pd.Series,
    pay_sum_by_doc: pd.Series,
) -> pd.Series:
    """doc 별 1 - |rec - pay| / max(rec, pay) — 양쪽 모두 양수일 때만 의미.

    Why: 정상 IC 는 한 doc 에 한 쪽만 있어 rec_sum 또는 pay_sum 이 0. circular 는 양쪽 다
         존재하며 self-balanced 라 대칭. 분모는 1e-6 floor 로 0 division 방어.
    """
    docs = rec_sum_by_doc.index.union(pay_sum_by_doc.index)
    rec = rec_sum_by_doc.reindex(docs, fill_value=0.0).abs()
    pay = pay_sum_by_doc.reindex(docs, fill_value=0.0).abs()
    denom = pd.concat([rec, pay], axis=1).max(axis=1).clip(lower=1e-6)
    return (1.0 - (rec - pay).abs() / denom).clip(lower=0.0, upper=1.0)


def _doc_context_scores(
    df: pd.DataFrame,
    ic_mask: pd.Series,
    settings,
) -> pd.DataFrame:
    """doc 단위 context boost components — period_end / after_hours / round_amount.

    Why: context 는 boost only. structural 미달이면 호출자가 차단한다. component 별
         0~1 점수로 반환 → 호출자가 weight 로 가중평균.
    """
    docs = df.loc[ic_mask, "document_id"].dropna().astype(str).unique()
    if len(docs) == 0:
        return pd.DataFrame(
            columns=["period_end", "after_hours", "round_amount"],
            index=pd.Index([], dtype="object"),
        )

    period_end_days = int(getattr(settings, "ic_reciprocal_context_period_end_days", 5))
    round_unit = float(getattr(settings, "ic_reciprocal_context_round_amount_unit", 1_000_000.0))
    normal_start = float(getattr(settings, "normal_hours_start", 8.5))
    normal_end = float(getattr(settings, "normal_hours_end", 18.5))

    sub = df.loc[ic_mask].copy()
    sub["_doc"] = sub["document_id"].astype(str)

    # period_end: posting_date day ≤ N 또는 ≥ (월 마지막 N일)
    if "posting_date" in sub.columns:
        pd_dt = pd.to_datetime(sub["posting_date"], errors="coerce")
        dom = pd_dt.dt.day
        days_in_month = pd_dt.dt.daysinmonth
        is_period_end = (dom <= period_end_days) | (dom >= (days_in_month - period_end_days + 1))
        sub["_period_end"] = is_period_end.fillna(False).astype(float)
    else:
        sub["_period_end"] = 0.0

    # after_hours: posting_date hour 가 정상 업무시간 밖 (있는 경우만)
    if "posting_date" in sub.columns:
        pd_dt = pd.to_datetime(sub["posting_date"], errors="coerce")
        hour = pd_dt.dt.hour + pd_dt.dt.minute / 60.0
        after = (hour < normal_start) | (hour > normal_end)
        sub["_after_hours"] = after.fillna(False).astype(float)
    else:
        sub["_after_hours"] = 0.0

    # round_amount: |amount| 가 round_unit 의 배수
    debit = pd.to_numeric(sub.get("debit_amount", 0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(sub.get("credit_amount", 0), errors="coerce").fillna(0.0).abs()
    amt = debit.where(debit > 0, credit)
    if round_unit > 0:
        is_round = (amt > 0) & ((amt % round_unit).abs() < 1e-6)
    else:
        is_round = pd.Series(False, index=sub.index, dtype=bool)
    sub["_round"] = is_round.astype(float)

    grouped = sub.groupby("_doc")
    return pd.DataFrame(
        {
            "period_end": grouped["_period_end"].max(),
            "after_hours": grouped["_after_hours"].max(),
            "round_amount": grouped["_round"].max(),
        }
    )


def _cross_company_reciprocal_entries(
    df: pd.DataFrame,
    pair_map: dict[str, str],
    *,
    rec_prefixes: set[str],
    pay_prefixes: set[str],
    amount_similarity_min: float,
    date_window_days: int,
) -> tuple[list[dict[str, object]], int]:
    required = {
        "document_id",
        "company_code",
        "trading_partner",
        "reference",
        "gl_account",
        "posting_date",
        "debit_amount",
        "credit_amount",
    }
    if not required.issubset(df.columns):
        return [], 0

    positions = pd.Series(range(len(df)), index=df.index, dtype="int64")
    gl = df["gl_account"].fillna("").astype(str).str.strip()
    is_rec = _gl_starts_with_any(gl, rec_prefixes)
    is_pay = _gl_starts_with_any(gl, pay_prefixes)
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0).abs()

    work = pd.DataFrame(
        {
            "_position": positions,
            "document_id": df["document_id"].fillna("").astype(str).str.strip(),
            "company_code": df["company_code"].fillna("").astype(str).str.strip(),
            "trading_partner": df["trading_partner"].fillna("").astype(str).str.strip(),
            "reference": df["reference"].fillna("").astype(str).str.strip(),
            "gl_account": gl,
            "posting_date": pd.to_datetime(df["posting_date"], errors="coerce"),
            "debit_amount": debit,
            "credit_amount": credit,
            "_is_rec": is_rec,
            "_is_pay": is_pay,
        },
        index=df.index,
    )
    rec = work[
        work["_is_rec"]
        & work["debit_amount"].gt(0)
        & work["document_id"].ne("")
        & work["company_code"].ne("")
        & work["trading_partner"].ne("")
        & work["reference"].ne("")
        & work["posting_date"].notna()
    ].copy()
    pay = work[
        work["_is_pay"]
        & work["credit_amount"].gt(0)
        & work["document_id"].ne("")
        & work["company_code"].ne("")
        & work["trading_partner"].ne("")
        & work["reference"].ne("")
        & work["posting_date"].notna()
    ].copy()
    if rec.empty or pay.empty:
        return [], 0

    rec["_rec_prefix"] = rec["gl_account"].map(
        lambda value: _first_matching_prefix(value, rec_prefixes)
    )
    rec["_pay_prefix"] = rec["_rec_prefix"].map(lambda value: str(pair_map.get(value, "")))
    pay["_pay_prefix"] = pay["gl_account"].map(
        lambda value: _first_matching_prefix(value, pay_prefixes)
    )
    pay["_rec_prefix"] = pay["_pay_prefix"].map(lambda value: str(pair_map.get(value, "")))
    rec = rec[rec["_rec_prefix"].ne("") & rec["_pay_prefix"].ne("")]
    pay = pay[pay["_pay_prefix"].ne("") & pay["_rec_prefix"].ne("")]
    if rec.empty or pay.empty:
        return [], 0

    def _list_int(values: pd.Series) -> list[int]:
        return [int(value) for value in values.tolist()]

    def _list_str(values: pd.Series) -> list[str]:
        return sorted({str(value) for value in values.tolist() if str(value)})

    rec_g = (
        rec.groupby(
            ["reference", "company_code", "trading_partner", "_rec_prefix", "_pay_prefix"],
            dropna=False,
            sort=False,
        )
        .agg(
            receivable_amount=("debit_amount", "sum"),
            receivable_date=("posting_date", "min"),
            receivable_positions=("_position", _list_int),
            receivable_document_ids=("document_id", _list_str),
        )
        .reset_index()
    )
    pay_g = (
        pay.groupby(
            ["reference", "company_code", "trading_partner", "_pay_prefix", "_rec_prefix"],
            dropna=False,
            sort=False,
        )
        .agg(
            payable_amount=("credit_amount", "sum"),
            payable_date=("posting_date", "min"),
            payable_positions=("_position", _list_int),
            payable_document_ids=("document_id", _list_str),
        )
        .reset_index()
    )
    merged = rec_g.merge(
        pay_g,
        left_on=["reference", "company_code", "trading_partner", "_rec_prefix", "_pay_prefix"],
        right_on=["reference", "trading_partner", "company_code", "_rec_prefix", "_pay_prefix"],
        how="inner",
        suffixes=("_rec", "_pay"),
    )
    candidate_count = int(len(merged))
    if merged.empty:
        return [], candidate_count

    denom = merged[["receivable_amount", "payable_amount"]].max(axis=1).clip(lower=1e-6)
    amount_symmetry = (
        1.0 - (merged["receivable_amount"] - merged["payable_amount"]).abs() / denom
    ).clip(lower=0.0, upper=1.0)
    date_diff = (
        (
            pd.to_datetime(merged["receivable_date"], errors="coerce")
            - pd.to_datetime(merged["payable_date"], errors="coerce")
        )
        .abs()
        .dt.days.fillna(9999)
    )
    matched = merged[(amount_symmetry >= amount_similarity_min) & (date_diff <= date_window_days)]
    if matched.empty:
        return [], candidate_count

    entries: list[dict[str, object]] = []
    for idx, row in matched.iterrows():
        entries.append(
            {
                "document_id": "",
                "flow_scope": "cross_company_reference",
                "receivable_document_ids": list(row["receivable_document_ids"]),
                "payable_document_ids": list(row["payable_document_ids"]),
                "receivable_positions": list(row["receivable_positions"]),
                "payable_positions": list(row["payable_positions"]),
                "receivable_amount": float(row["receivable_amount"]),
                "payable_amount": float(row["payable_amount"]),
                "amount_symmetry": float(amount_symmetry.loc[idx]),
                "date_diff_days": int(date_diff.loc[idx]),
                "company_pair": [str(row["company_code_rec"]), str(row["company_code_pay"])],
                "account_pair": [str(row["_rec_prefix"]), str(row["_pay_prefix"])],
                "row_index": int(row["receivable_positions"][0]),
                "row_position": int(row["receivable_positions"][0]),
            }
        )
    return entries, candidate_count


def compute_reciprocal_flow_scores(
    df: pd.DataFrame,
    pair_map: dict[str, str],
    *,
    settings,
    audit_rules: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    """single-document reciprocal IC flow probability (ic_reciprocal_flow_prob).

    Score semantics:
        structural_score: doc 안에 receivable prefix + payable prefix GL 동시 존재 AND
                          rec_amount_sum ≈ pay_amount_sum (similarity ≥ threshold)
                          만족 시 1.0, 그 외 0.0.
        context_score:    period_end / after_hours / round_amount 가중 평균 (0~1).
        final per doc:
            if structural_score < min_structural: 0
            else: clip(structural_weight * structural + context_weight * context, 0, 1)
        row-level broadcast: 같은 document_id 의 IC row 만 점수 받음.

    임계값/가중치는 audit evidence 강도 기준이며 fixed5 truth recall 기준으로 튜닝
    하지 않는다.

    Returns:
        (DataFrame[ic_reciprocal_flow_prob], summary dict)
    """
    audit_rules = audit_rules or {}
    summary: dict = {
        "evaluated_ic_rows": 0,
        "structural_candidate_docs": 0,
        "context_boost_docs": 0,
        "score_q95": 0.0,
        "score_q99": 0.0,
        "score_max": 0.0,
        "cross_company_candidate_pairs": 0,
        "cross_company_reciprocal_pairs": 0,
        "cross_company_reciprocal_entries": [],
        "warnings": [],
        "params": {
            "structural_weight": float(getattr(settings, "ic_reciprocal_structural_weight", 0.7)),
            "context_weight": float(getattr(settings, "ic_reciprocal_context_weight", 0.3)),
            "amount_similarity_min": float(
                getattr(settings, "ic_reciprocal_amount_similarity_min", 0.95)
            ),
            "min_structural_score": float(
                getattr(settings, "ic_reciprocal_min_structural_score", 0.5)
            ),
            "period_end_days": int(getattr(settings, "ic_reciprocal_context_period_end_days", 5)),
            "round_amount_unit": float(
                getattr(settings, "ic_reciprocal_context_round_amount_unit", 1_000_000.0)
            ),
            "cross_company_date_window_days": int(
                getattr(
                    settings,
                    "ic_reciprocal_cross_company_date_window_days",
                    getattr(settings, "ic_date_window_days", 5),
                )
            ),
        },
    }

    empty = pd.DataFrame(
        {"ic_reciprocal_flow_prob": pd.Series(0.0, index=df.index, dtype=float)},
        index=df.index,
    )

    required = ("document_id", "gl_account", "debit_amount", "credit_amount")
    missing = [c for c in required if c not in df.columns]
    if missing:
        summary["warnings"].append(f"missing_required_columns: {missing}")
        return empty, summary

    if not pair_map:
        summary["warnings"].append("empty_pair_map")
        return empty, summary

    receivable_prefixes, payable_prefixes = _classify_rec_pay_prefixes(pair_map)
    if not receivable_prefixes or not payable_prefixes:
        summary["warnings"].append("incomplete_pair_map")
        return empty, summary

    is_rec = _gl_starts_with_any(df["gl_account"], receivable_prefixes)
    is_pay = _gl_starts_with_any(df["gl_account"], payable_prefixes)
    ic_mask = is_rec | is_pay
    summary["evaluated_ic_rows"] = int(ic_mask.sum())
    if not ic_mask.any():
        return empty, summary

    sub = df.loc[ic_mask, ["document_id", "gl_account", "debit_amount", "credit_amount"]].copy()
    sub["_doc"] = sub["document_id"].astype(str)
    sub["_is_rec"] = is_rec.loc[sub.index]
    sub["_is_pay"] = is_pay.loc[sub.index]
    debit = pd.to_numeric(sub["debit_amount"], errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(sub["credit_amount"], errors="coerce").fillna(0.0).abs()
    # receivable 라인은 debit, payable 라인은 credit 을 본다 (match_ic_groups 규약).
    sub["_amt"] = debit.where(sub["_is_rec"], 0.0) + credit.where(sub["_is_pay"], 0.0)

    rec_rows = sub[sub["_is_rec"]]
    pay_rows = sub[sub["_is_pay"]]
    rec_sum_by_doc = (
        rec_rows.groupby("_doc")["_amt"].sum() if len(rec_rows) else pd.Series(dtype=float)
    )
    pay_sum_by_doc = (
        pay_rows.groupby("_doc")["_amt"].sum() if len(pay_rows) else pd.Series(dtype=float)
    )

    # structural: 양쪽 모두 존재 (sum > 0) + amount 대칭
    docs = rec_sum_by_doc.index.union(pay_sum_by_doc.index)
    has_both = pd.Series(False, index=docs, dtype=bool)
    if not rec_sum_by_doc.empty and not pay_sum_by_doc.empty:
        rec_pos = rec_sum_by_doc.reindex(docs, fill_value=0.0) > 0
        pay_pos = pay_sum_by_doc.reindex(docs, fill_value=0.0) > 0
        has_both = rec_pos & pay_pos
    sim = _doc_amount_symmetry(rec_sum_by_doc, pay_sum_by_doc).reindex(docs, fill_value=0.0)
    sim_threshold = float(getattr(settings, "ic_reciprocal_amount_similarity_min", 0.95))
    is_symmetric = sim >= sim_threshold
    structural_doc = (has_both & is_symmetric).astype(float)
    summary["structural_candidate_docs"] = int(structural_doc.sum())

    cross_entries, cross_candidate_count = _cross_company_reciprocal_entries(
        df,
        pair_map,
        rec_prefixes=receivable_prefixes,
        pay_prefixes=payable_prefixes,
        amount_similarity_min=sim_threshold,
        date_window_days=int(summary["params"]["cross_company_date_window_days"]),
    )
    summary["cross_company_candidate_pairs"] = int(cross_candidate_count)
    summary["cross_company_reciprocal_pairs"] = int(len(cross_entries))
    summary["cross_company_reciprocal_entries"] = cross_entries

    if structural_doc.sum() == 0 and not cross_entries:
        return empty, summary

    # context boost — period_end / after_hours / round_amount
    context_df = _doc_context_scores(df, ic_mask, settings)
    context_df = context_df.reindex(docs).fillna(0.0)
    w_pe = float(getattr(settings, "ic_reciprocal_context_period_end_weight", 0.4))
    w_ah = float(getattr(settings, "ic_reciprocal_context_after_hours_weight", 0.3))
    w_rd = float(getattr(settings, "ic_reciprocal_context_round_weight", 0.3))
    w_sum = max(w_pe + w_ah + w_rd, 1e-6)
    context_doc = (
        w_pe / w_sum * context_df["period_end"]
        + w_ah / w_sum * context_df["after_hours"]
        + w_rd / w_sum * context_df["round_amount"]
    ).clip(lower=0.0, upper=1.0)
    summary["context_boost_docs"] = int((context_doc > 0).sum())

    # final per-doc score (structural min 미달이면 0)
    min_structural = float(getattr(settings, "ic_reciprocal_min_structural_score", 0.5))
    structural_pass = structural_doc >= min_structural
    s_weight = float(getattr(settings, "ic_reciprocal_structural_weight", 0.7))
    c_weight = float(getattr(settings, "ic_reciprocal_context_weight", 0.3))
    raw_combined = s_weight * structural_doc + c_weight * context_doc
    final_doc = raw_combined.where(structural_pass, 0.0).clip(lower=0.0, upper=1.0)

    # row-level broadcast — IC row 만 점수 받음, 같은 doc 안에서는 모두 동일.
    doc_score_map = final_doc.to_dict()
    row_scores = pd.Series(0.0, index=df.index, dtype=float)
    ic_doc = df.loc[ic_mask, "document_id"].astype(str)
    row_scores.loc[ic_mask] = ic_doc.map(doc_score_map).fillna(0.0).values
    cross_score = float(max(min(s_weight, 1.0), 0.0))
    for entry in cross_entries:
        positions = [
            int(pos)
            for pos in [
                *(entry.get("receivable_positions") or []),
                *(entry.get("payable_positions") or []),
            ]
            if 0 <= int(pos) < len(df)
        ]
        if positions:
            row_scores.iloc[positions] = row_scores.iloc[positions].clip(lower=cross_score)

    summary["score_q95"] = float(row_scores.quantile(0.95))
    summary["score_q99"] = float(row_scores.quantile(0.99))
    summary["score_max"] = float(row_scores.max())

    return pd.DataFrame({"ic_reciprocal_flow_prob": row_scores}, index=df.index), summary
