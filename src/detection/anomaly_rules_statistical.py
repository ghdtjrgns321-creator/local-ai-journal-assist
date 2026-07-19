"""통계 기반 이상 징후 룰 — L4-02 Benford, L4-04 희소 차대 계정쌍.

L4-02: validation/benford.py의 analyze_benford() 재사용. 편차 큰 자릿수 전표를
     drill-down 후보로 선별하고, 실제 행별 적발은 BenfordDetector에서 0점으로 격하한다.
     반환값은 후보 점수 [0, 0.8] float Series + finding metadata.
L4-04: merge 기반 Cartesian Product로 복합 분개(N:M) 계정 쌍 빈도 분석.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from config.settings import AuditSettings, get_settings
from src.detection.constants import SEVERITY_MAP
from src.validation.benford import BENFORD_EXPECTED, analyze_benford

logger = logging.getLogger(__name__)


_MIN_GROUP_FOR_BENFORD = 500  # Small Benford groups are too noisy for practical review.

# Why: L4-02 deviation 비례 스코어 파라미터.
#      base = SEVERITY_MAP["L4-02"]/5 = 0.4 (3등급 / 5등급 만점).
#      위반 자릿수의 (|observed-expected| / threshold) 비율을 [0.5, 2.0]으로 클립한 후
#      base와 곱해 최종 행 점수를 [0.2, 0.8] 범위로 차등화한다.
_L4_02_BASE_SCORE = SEVERITY_MAP["L4-02"] / 5.0
_L4_02_MULT_MIN = 0.5
_L4_02_MULT_MAX = 2.0
_L4_02_STRONG_MAD = 0.015


def _digit_deviation(observed: dict[int, float], digit: int) -> float:
    """단일 자릿수의 절대 편차 — Benford 기댓값과 관측값의 차이."""
    return abs(observed.get(digit, 0.0) - BENFORD_EXPECTED[digit])


def _deviation_to_score(deviation: float, threshold: float) -> float:
    """편차 → [0.2, 0.8] 점수 변환.

    deviation == threshold (보더라인) → base(0.4) 그대로.
    deviation == 2 × threshold → base × 2.0 = 0.8 (캡).
    deviation == 0.5 × threshold → base × 0.5 = 0.2 (플로어).
    """
    if threshold <= 0:
        return _L4_02_BASE_SCORE
    multiplier = max(_L4_02_MULT_MIN, min(deviation / threshold, _L4_02_MULT_MAX))
    return _L4_02_BASE_SCORE * multiplier


def _benford_finding_severity(mad: float | None, threshold: float) -> str | None:
    """Return finding severity from MAD, or None when deviation is too small."""
    if mad is None:
        return None
    if mad <= threshold:
        return None
    if mad > _L4_02_STRONG_MAD:
        return "strong"
    return "moderate"


def c07_benford_violation(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """L4-02 Benford 위반: 계정별 분리 검정 + 전체 검정 하이브리드.

    Why: 감사기준서 520호 §5, PCAOB AS 240 A45(e).
         전체 데이터에서는 정상이지만 특정 계정(여비교통비, 접대비 등)에서만
         Benford 위반이 발생할 수 있다 — 계정별 분리 검정으로 정밀 탐지.

    전략:
      1단계: company_code+gl_account별 분리 검정 (n >= 500인 그룹만)
             → 위반 계정의 편차 큰 자릿수 행만 플래그
      2단계: 전체 데이터 검정은 metadata summary로만 보관한다.

    후보 스코어링 (deviation 비례 차등):
      - 위반 행의 점수 = 0.4 × clip(deviation/threshold, 0.5, 2.0) → [0.2, 0.8]
      - 같은 (전표·계정) 단위에서 발생한 여러 위반 자릿수 중 max deviation 사용
      - document_id 전체 전파는 하지 않고 해당 자릿수 라인만 drill-down 후보로 둔다.
      - 이 점수는 drill-down 후보 점수다. 최종 행별 L4-02 적발 점수는
        BenfordDetector에서 기본 0으로 격하하고, 집계 finding을 우선 노출한다.

    Returns:
        (float Series, metadata dict) — 각 행 후보 점수 [0.0, 0.8], 0.0이면 후보 아님.
    """
    s = settings or get_settings()
    meta: dict[str, Any] = {}

    if "first_digit" not in df.columns:
        return pd.Series(0.0, index=df.index), meta

    threshold = s.benford_mad_threshold
    # Why: 행별 스코어 누적 — 동일 행에 여러 위반이 매핑되면 max 적용
    scores = pd.Series(0.0, index=df.index)
    findings: list[dict[str, Any]] = []

    def _apply_score(row_mask: pd.Series, score: float) -> tuple[int, int | None]:
        """행 마스크에 후보 스코어 적용 (기존값 대비 max)."""
        if score <= 0:
            return 0, 0 if "document_id" in df.columns else None
        # Why: Benford는 분포 finding이다. 전표 전체로 전파하면 drill-down 후보가
        #      과도하게 커지므로 해당 digit 라인만 후보 점수로 보관한다.
        full_mask = row_mask.fillna(False)
        if "document_id" in df.columns:
            doc_ids = df.loc[full_mask, "document_id"].unique()
            doc_count: int | None = len(doc_ids)
        else:
            doc_count = None
        scores.loc[full_mask] = scores.loc[full_mask].clip(lower=score)
        return int(full_mask.sum()), doc_count

    # ── 1단계: 회사+계정별 분리 검정 ──
    # Why: 같은 GL이라도 회사별 금액 패턴이 다르므로 company_code가 있으면 함께 분리한다.
    group_results: dict[str, Any] = {}
    if "gl_account" in df.columns:
        group_cols = ["gl_account"]
        if "company_code" in df.columns:
            group_cols = ["company_code", "gl_account"]

        for group_key, group_df in df.groupby(group_cols):
            group_digits = group_df["first_digit"]
            if len(group_digits) < _MIN_GROUP_FOR_BENFORD:
                continue
            result, _ = analyze_benford(group_digits, settings=s)
            finding_severity = _benford_finding_severity(result.mad, threshold)
            if finding_severity is not None:
                # Why: 위반 계정 내에서 편차 큰 자릿수만 선별 (전체 행 플래그 방지)
                bad_digits = {
                    d for d in range(1, 10) if _digit_deviation(result.observed, d) > threshold
                }
                if bad_digits:
                    # Why: 위반 자릿수 중 최대 deviation을 대표값으로 사용
                    max_dev = max(_digit_deviation(result.observed, d) for d in bad_digits)
                    digit_score = _deviation_to_score(max_dev, threshold)

                    digit_mask = df.index.isin(group_df.index) & df["first_digit"].isin(bad_digits)
                    affected_rows, affected_docs = _apply_score(digit_mask, digit_score)
                    if isinstance(group_key, tuple):
                        if len(group_key) == 2:
                            company_code, gl_account = group_key
                        else:
                            company_code, gl_account = None, group_key[0]
                    else:
                        company_code, gl_account = None, group_key
                    group_id = (
                        f"{company_code}|{gl_account}"
                        if company_code is not None
                        else str(gl_account)
                    )
                    group_results[group_id] = {
                        "company_code": None if company_code is None else str(company_code),
                        "mad": result.mad,
                        "finding_severity": finding_severity,
                        "flagged_digits": sorted(bad_digits),
                        "max_deviation": max_dev,
                        "row_score": digit_score,
                        "sample_size": len(group_digits),
                    }
                    findings.append(
                        {
                            "scope": "company_gl_account"
                            if company_code is not None
                            else "gl_account",
                            "company_code": None if company_code is None else str(company_code),
                            "gl_account": str(gl_account),
                            "sample_size": len(group_digits),
                            "mad": result.mad,
                            "chi2_p_value": result.chi2_p_value,
                            "finding_severity": finding_severity,
                            "flagged_digits": sorted(bad_digits),
                            "max_deviation": max_dev,
                            "candidate_score": digit_score,
                            "candidate_rows": affected_rows,
                            "candidate_documents": affected_docs,
                        }
                    )

    meta["benford_group_results"] = group_results

    # ── 2단계: 전체 검정 summary ──
    # Why: 전체 모집단 통계는 대시보드 Benford summary용으로 남긴다. 전체 digit을
    #      전표 후보로 풀면 대량 후보가 생기므로 drill-down finding은 만들지 않는다.
    result, _warnings = analyze_benford(df["first_digit"], settings=s)
    meta["benford_result"] = result
    meta["benford_global_finding_severity"] = _benford_finding_severity(
        result.mad,
        threshold,
    )

    meta["benford_findings"] = findings
    meta["benford_candidate_count"] = int((scores > 0).sum())
    meta["benford_candidate_indices"] = scores[scores > 0].index.tolist()

    return scores, meta


_RARE_PAIR_QUARTER_DAYS = 91.3125  # 365.25 / 4
_RARE_PAIR_LARGE_DOC_LINE_THRESHOLD = 100
_RARE_PAIR_MAX_LINES_PER_DOC = 1_000_000


def _engagement_rare_thresholds(
    df: pd.DataFrame,
    eng_cols: list[str],
    cadence_per_quarter: float,
) -> pd.Series:
    """engagement(회사·연도)별 cadence 희소 임계 빈도를 산정한다.

    "정상 거래라면 분기 단위로 반복된다"는 cadence 판단:
    임계 = round(분기수 · cadence_per_quarter) - 1. 빈도 ≤ 임계면 희소.
    분기수는 engagement posting_date 범위로 산정(기간 비례 자동조정 — 1년→4분기→임계 3,
    반기→2분기→임계 1). posting_date·기간 불명이면 1년(4분기) 가정. 임계 최소 0.
    """
    if "posting_date" in df.columns:
        dates = pd.to_datetime(df["posting_date"], errors="coerce", format="ISO8601")
    else:
        dates = pd.Series(pd.NaT, index=df.index)
    work = pd.DataFrame({col: df[col] for col in eng_cols})
    work["_d"] = dates.to_numpy()
    grouped = work.groupby(eng_cols, sort=False)["_d"]
    span_days = (grouped.max() - grouped.min()).dt.days
    quarters = (span_days / _RARE_PAIR_QUARTER_DAYS).round()
    quarters = quarters.fillna(4.0).clip(lower=1.0)  # 기간 불명 → 1년 가정
    threshold = (quarters * float(cadence_per_quarter)).round() - 1.0
    return threshold.clip(lower=0.0).astype(int)


def c09_rare_account_pair(
    df: pd.DataFrame,
    cadence_per_quarter: float = 1.0,
) -> pd.Series:
    """L4-04 희소 차대 계정쌍: engagement(회사·연도) 기간 cadence(분기 1회) 미만 등장 쌍.

    Why: PCAOB AS2401 A45(a)/ISA315 — 희소한 계정 조합은 비정상 거래 의심.
         희소 기준은 고정 퍼센트(구 하위 1%)가 아니라 cadence(주기): "정상 거래라면
         분기 단위로 반복된다". engagement 기간을 분기수로 환산해 빈도 ≤ (분기수·cadence - 1)
         이면 희소(기간 비례 자동조정). 빈도는 회사·연도 단위로 센다(합본 금지 — 회사 간 재등장로
         희소 정의 붕괴 방지). 복합분개(N:M)는 merge 기반 Cartesian Product로 벡터화.
         발화는 전표 단위 binary(0/1) — 강도/정황/조합은 통합점수체계 소관.
    """
    required = ["document_id", "gl_account", "debit_amount", "credit_amount"]
    if any(c not in df.columns for c in required):
        return pd.Series(False, index=df.index)

    # engagement 키 — company_code·fiscal_year 가 있으면 그 단위로, 없으면 전체 1 engagement.
    eng_cols = [c for c in ("company_code", "fiscal_year") if c in df.columns]
    df_eng = df.copy()
    if not eng_cols:
        df_eng["_engagement"] = 0
        eng_cols = ["_engagement"]

    # 1. 차변/대변 뷰 분리 (engagement 키 동반) — gl_account 결측 라인은 제외(L1-02/03 소관).
    debit_amt = df_eng["debit_amount"].fillna(0)
    credit_amt = df_eng["credit_amount"].fillna(0)
    view_cols = ["document_id", "gl_account", *eng_cols]
    debits = df_eng.loc[debit_amt > 0, view_cols]
    credits = df_eng.loc[credit_amt > 0, view_cols]

    debit_null_account_lines = int(debits["gl_account"].isna().sum())
    credit_null_account_lines = int(credits["gl_account"].isna().sum())
    null_account_docs = set(
        pd.concat(
            [
                debits.loc[debits["gl_account"].isna(), "document_id"],
                credits.loc[credits["gl_account"].isna(), "document_id"],
            ]
        ).dropna()
    )
    debits = debits[debits["gl_account"].notna()]
    credits = credits[credits["gl_account"].notna()]

    threshold_by_eng = _engagement_rare_thresholds(df_eng, eng_cols, cadence_per_quarter)

    def _empty_result() -> pd.Series:
        out = pd.Series(False, index=df.index)
        out.attrs["breakdown"] = {
            "interpretation": "rare_debit_credit_pair_review_signal",
            "rarity_basis": "cadence_per_quarter",
            "cadence_per_quarter": float(cadence_per_quarter),
            "rare_pair_count": 0,
            "candidate_document_count": 0,
            "excluded_null_account_debit_lines": debit_null_account_lines,
            "excluded_null_account_credit_lines": credit_null_account_lines,
            "excluded_null_account_document_count": int(len(null_account_docs)),
        }
        out.attrs["score_series"] = pd.Series(0.0, index=df.index, dtype="float64")
        out.attrs["row_annotations"] = {}
        return out

    if debits.empty or credits.empty:
        return _empty_result()

    # 메모리 보호: 100라인 초과 대형 전표는 (document_id, gl_account) 고유 쌍으로 압축한다.
    # 구 "대형 전표면 신규 조합을 자동 희소" 정책은 폐기 — 압축된 쌍도 동일 cadence 로 판정.
    doc_sizes = df_eng.groupby("document_id").size()
    large_docs = set(doc_sizes[doc_sizes > _RARE_PAIR_LARGE_DOC_LINE_THRESHOLD].index)
    lg_d = debits["document_id"].isin(large_docs)
    lg_c = credits["document_id"].isin(large_docs)
    large_debits_before = int(lg_d.sum())
    large_credits_before = int(lg_c.sum())
    large_debits = debits[lg_d].drop_duplicates(["document_id", "gl_account"])
    large_credits = credits[lg_c].drop_duplicates(["document_id", "gl_account"])
    debits = pd.concat([debits[~lg_d], large_debits], ignore_index=True)
    credits = pd.concat([credits[~lg_c], large_credits], ignore_index=True)

    bloated = set(doc_sizes[doc_sizes > _RARE_PAIR_MAX_LINES_PER_DOC].index)
    if bloated:
        logger.warning(
            "L4-04: %d개 전표가 %d행 초과 — Cartesian Product 제한으로 제외",
            len(bloated),
            _RARE_PAIR_MAX_LINES_PER_DOC,
        )
        debits = debits[~debits["document_id"].isin(bloated)]
        credits = credits[~credits["document_id"].isin(bloated)]

    if debits.empty or credits.empty:
        return _empty_result()

    # 2. document_id 기준 inner join → N:M 복합분개 모든 쌍(차변계정→대변계정). engagement 동반.
    pairs = debits.merge(credits, on=["document_id", *eng_cols], suffixes=("_dr", "_cr"))
    if pairs.empty:
        return _empty_result()
    pairs["_large_doc_pair"] = pairs["document_id"].isin(large_docs)

    # 3. engagement·쌍별 빈도 → engagement 별 cadence 임계 적용. 빈도 ≤ 임계면 희소.
    pair_key = [*eng_cols, "gl_account_dr", "gl_account_cr"]
    pair_counts = pairs.groupby(pair_key, sort=False).size().rename("_count").reset_index()
    pair_counts = pair_counts.merge(
        threshold_by_eng.rename("_threshold").reset_index(), on=eng_cols, how="left"
    )
    pair_counts["_threshold"] = pair_counts["_threshold"].fillna(0).astype(int)
    pair_counts["_rare"] = pair_counts["_count"] <= pair_counts["_threshold"]
    rare_keys = pair_counts[pair_counts["_rare"]]

    pairs = pairs.merge(rare_keys[[*pair_key, "_count", "_threshold"]], on=pair_key, how="inner")
    if pairs.empty:
        return _empty_result()
    rare_docs = set(pairs["document_id"])

    # 4. 희소쌍이 하나라도 포함된 전표의 모든 라인을 binary 1.0 으로 플래그.
    result = df["document_id"].isin(rare_docs)
    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[result] = 1.0

    doc_inputs: dict[object, dict[str, object]] = {}
    for document_id, doc_pairs in pairs.groupby("document_id", sort=False):
        sample_pairs = [
            f"{p.gl_account_dr}->{p.gl_account_cr}"
            for p in doc_pairs.head(5).itertuples(index=False)
        ]
        doc_inputs[document_id] = {
            "has_large_doc_pair": bool(doc_pairs["_large_doc_pair"].any()),
            "rare_pair_count": int(len(doc_pairs)),
            "sample_pairs": sample_pairs,
            "threshold_count": int(doc_pairs["_threshold"].iloc[0]),
        }

    row_annotations: dict[object, dict[str, object]] = {}
    for idx in df.index[result]:
        document_id = df.at[idx, "document_id"]
        doc_input = doc_inputs.get(document_id, {})
        reason_codes = ["rare_account_pair"]
        if bool(doc_input.get("has_large_doc_pair", False)):
            reason_codes.append("large_doc_distinct_pair")  # 사실 표시(점수 가중 아님)
        annotation_key = int(idx) if isinstance(idx, int) else idx
        row_annotations[annotation_key] = {
            "reason_codes": reason_codes,
            "primary_reason": reason_codes[0],
            "score": 1.0,
            "rare_pair_count": int(doc_input.get("rare_pair_count", 0)),
            "sample_pairs": list(doc_input.get("sample_pairs", [])),
            "threshold_count": int(doc_input.get("threshold_count", 0)),
        }
        if "gl_account" in df.columns:
            value = df.at[idx, "gl_account"]
            row_annotations[annotation_key]["gl_account"] = None if pd.isna(value) else value

    large_doc_rare_docs = {
        doc for doc, inp in doc_inputs.items() if inp.get("has_large_doc_pair", False)
    }
    result.attrs["breakdown"] = {
        "interpretation": "rare_debit_credit_pair_review_signal",
        "rarity_basis": "cadence_per_quarter",
        "cadence_per_quarter": float(cadence_per_quarter),
        "engagement_count": int(len(threshold_by_eng)),
        "distinct_pair_count": int(len(pair_counts)),
        "rare_pair_count": int(len(rare_keys)),
        "candidate_document_count": int(len(rare_docs)),
        "rare_pair_review_docs": int(len(rare_docs)),
        "ordinary_rare_pair_docs": int(len(rare_docs - large_doc_rare_docs)),
        "large_doc_distinct_pair_docs": int(len(large_doc_rare_docs)),
        "large_doc_distinct_pair_rows": int(
            (result & df["document_id"].isin(large_doc_rare_docs)).sum()
        ),
        "pair_generation_mode": "engagement_cadence_line_pairs",
        "large_document_line_threshold": _RARE_PAIR_LARGE_DOC_LINE_THRESHOLD,
        "large_document_count": int(len(large_docs)),
        "deduplicated_large_debit_account_rows": int(large_debits_before - len(large_debits)),
        "deduplicated_large_credit_account_rows": int(large_credits_before - len(large_credits)),
        "excluded_null_account_debit_lines": debit_null_account_lines,
        "excluded_null_account_credit_lines": credit_null_account_lines,
        "excluded_null_account_document_count": int(len(null_account_docs)),
    }
    result.attrs["score_series"] = score_series
    result.attrs["row_annotations"] = row_annotations
    return result
