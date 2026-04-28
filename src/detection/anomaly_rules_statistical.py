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
                    d for d in range(1, 10)
                    if _digit_deviation(result.observed, d) > threshold
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
                    findings.append({
                        "scope": "company_gl_account" if company_code is not None else "gl_account",
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
                    })

    meta["benford_group_results"] = group_results

    # ── 2단계: 전체 검정 summary ──
    # Why: 전체 모집단 통계는 대시보드 Benford summary용으로 남긴다. 전체 digit을
    #      전표 후보로 풀면 대량 후보가 생기므로 drill-down finding은 만들지 않는다.
    result, _warnings = analyze_benford(df["first_digit"], settings=s)
    meta["benford_result"] = result
    meta["benford_global_finding_severity"] = _benford_finding_severity(
        result.mad, threshold,
    )

    meta["benford_findings"] = findings
    meta["benford_candidate_count"] = int((scores > 0).sum())
    meta["benford_candidate_indices"] = scores[scores > 0].index.tolist()

    return scores, meta


def c09_rare_account_pair(
    df: pd.DataFrame,
    percentile: float = 0.01,
) -> pd.Series:
    """L4-04 희소 차대 계정쌍: 차변-대변 계정 쌍 빈도 하위 N%.

    Why: PCAOB AS 240 A49(a), ISA 315 — 희소한 계정 조합은 비정상 거래 의심.
         복합 분개(N:M)를 merge 기반 Cartesian Product로 처리하여
         반복문 없이 벡터화 연산으로 모든 (차변, 대변) 쌍 생성.
    """
    # Phase 1 interpretation: rare debit-credit account-pair review signal.
    # This rule does not try to maintain semantic allow/deny lists by account.
    required = ["document_id", "gl_account", "debit_amount", "credit_amount"]
    if any(c not in df.columns for c in required):
        return pd.Series(False, index=df.index)

    # 1. 차변/대변 뷰 분리
    debit_amt = df["debit_amount"].fillna(0)
    credit_amt = df["credit_amount"].fillna(0)

    debits = df.loc[debit_amt > 0, ["document_id", "gl_account"]]
    credits = df.loc[credit_amt > 0, ["document_id", "gl_account"]]

    debit_null_account_lines = int(debits["gl_account"].isna().sum())
    credit_null_account_lines = int(credits["gl_account"].isna().sum())
    null_account_docs = set(
        pd.concat([
            debits.loc[debits["gl_account"].isna(), "document_id"],
            credits.loc[credits["gl_account"].isna(), "document_id"],
        ]).dropna()
    )
    debits = debits[debits["gl_account"].notna()]
    credits = credits[credits["gl_account"].notna()]

    if debits.empty or credits.empty:
        result = pd.Series(False, index=df.index)
        result.attrs["breakdown"] = {
            "interpretation": "rare_debit_credit_pair_review_signal",
            "percentile": float(percentile),
            "threshold_count": None,
            "distinct_pair_count": 0,
            "rare_pair_count": 0,
            "candidate_document_count": 0,
            "excluded_null_account_debit_lines": debit_null_account_lines,
            "excluded_null_account_credit_lines": credit_null_account_lines,
            "excluded_null_account_document_count": int(len(null_account_docs)),
        }
        return result

    # Why: 단일 전표 내 행 수가 과다하면 Cartesian Product로 메모리 폭발 가능
    #      (차변 50 × 대변 50 = 2,500행/전표) — 임계 초과 전표는 제외
    _LARGE_DOC_LINE_THRESHOLD = 100
    doc_sizes = df.groupby("document_id").size()
    large_docs = doc_sizes[doc_sizes > _LARGE_DOC_LINE_THRESHOLD].index
    large_doc_mask_debit = debits["document_id"].isin(large_docs)
    large_doc_mask_credit = credits["document_id"].isin(large_docs)
    large_debits_before = int(large_doc_mask_debit.sum())
    large_credits_before = int(large_doc_mask_credit.sum())
    normal_debits = debits[~large_doc_mask_debit]
    normal_credits = credits[~large_doc_mask_credit]
    large_debits = debits[large_doc_mask_debit].drop_duplicates(["document_id", "gl_account"])
    large_credits = credits[large_doc_mask_credit].drop_duplicates(["document_id", "gl_account"])
    debits = pd.concat([normal_debits, large_debits], ignore_index=True)
    credits = pd.concat([normal_credits, large_credits], ignore_index=True)
    _MAX_LINES_PER_DOC = 1_000_000
    doc_sizes = df.groupby("document_id").size()
    bloated = doc_sizes[doc_sizes > _MAX_LINES_PER_DOC].index
    if not bloated.empty:
        logger.warning(
            "L4-04: %d개 전표가 %d행 초과 — Cartesian Product 제한으로 제외",
            len(bloated), _MAX_LINES_PER_DOC,
        )
        debits = debits[~debits["document_id"].isin(bloated)]
        credits = credits[~credits["document_id"].isin(bloated)]

    if normal_debits.empty or normal_credits.empty:
        return pd.Series(False, index=df.index)

    # 2. document_id 기준 inner join → N:M 복합 분개의 모든 쌍 생성
    normal_pairs = normal_debits.merge(
        normal_credits, on="document_id", suffixes=("_dr", "_cr")
    )
    large_pairs = (
        large_debits.merge(large_credits, on="document_id", suffixes=("_dr", "_cr"))
        if not large_debits.empty and not large_credits.empty
        else pd.DataFrame(columns=normal_pairs.columns)
    )
    normal_pairs["_large_doc_pair"] = False
    large_pairs["_large_doc_pair"] = True
    pairs = pd.concat([normal_pairs, large_pairs], ignore_index=True)

    if normal_pairs.empty:
        return pd.Series(False, index=df.index)

    # 3. 쌍별 빈도 계산 → 하위 percentile 임계값
    pair_counts = pairs.groupby(["gl_account_dr", "gl_account_cr"]).size()
    # Why: quantile이 0을 반환하면 모든 쌍이 희소로 분류되는 것을 방지
    pair_counts = normal_pairs.groupby(["gl_account_dr", "gl_account_cr"]).size()
    threshold = max(pair_counts.quantile(percentile), 1)

    # 4. 희소 쌍 → merge 기반 벡터화 판별 (tuple isin 대비 성능 우수)
    rare_idx = pair_counts[pair_counts <= threshold].reset_index()
    rare_idx.columns = ["gl_account_dr", "gl_account_cr", "_count"]
    rare_idx["_rare"] = True
    rare_count_lookup = {
        (row["gl_account_dr"], row["gl_account_cr"]): int(row["_count"])
        for row in rare_idx.to_dict("records")
    }
    pairs = pairs.merge(
        rare_idx[["gl_account_dr", "gl_account_cr", "_rare"]],
        on=["gl_account_dr", "gl_account_cr"],
        how="left",
    )
    pairs["_rare"] = pairs["_rare"].where(
        pairs["_rare"].notna(), pairs["_large_doc_pair"],
    ).astype(bool)
    rare_docs = set(pairs.loc[pairs["_rare"] == True, "document_id"])  # noqa: E712

    # 5. Flag every line in documents that contain at least one rare pair.
    result = df["document_id"].isin(rare_docs)
    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[result] = 0.40

    rare_pairs = pairs[pairs["_rare"] == True].copy()  # noqa: E712
    if not rare_pairs.empty:
        rare_doc_summary = rare_pairs.groupby("document_id").agg(
            rare_pair_count=("document_id", "size"),
            has_large_doc_pair=("_large_doc_pair", "max"),
        )
    else:
        rare_doc_summary = pd.DataFrame(
            columns=["rare_pair_count", "has_large_doc_pair"],
        )

    doc_annotation_inputs: dict[object, dict[str, object]] = {}
    for document_id, doc_pairs in rare_pairs.groupby("document_id", sort=False):
        sample_pairs = [
            f"{pair.gl_account_dr}->{pair.gl_account_cr}"
            for pair in doc_pairs.head(5).itertuples(index=False)
        ]
        first_pair = doc_pairs.iloc[0]
        pair_key = (first_pair["gl_account_dr"], first_pair["gl_account_cr"])
        doc_annotation_inputs[document_id] = {
            "has_large_doc_pair": bool(doc_pairs["_large_doc_pair"].any()),
            "rare_pair_count": int(len(doc_pairs)),
            "sample_pairs": sample_pairs,
            "sample_pair_count": rare_count_lookup.get(pair_key, None),
        }

    row_annotations: dict[object, dict[str, object]] = {}
    for idx in df.index[result]:
        document_id = df.at[idx, "document_id"]
        doc_input = doc_annotation_inputs.get(document_id, {})
        reason_codes = ["rare_account_pair"]
        if bool(doc_input.get("has_large_doc_pair", False)):
            reason_codes.append("large_doc_distinct_pair")
        annotation_key = int(idx) if isinstance(idx, int) else idx
        row_annotations[annotation_key] = {
            "reason_codes": reason_codes,
            "primary_reason": reason_codes[-1],
            "score": round(float(score_series.loc[idx]), 4),
            "rare_pair_count": int(doc_input.get("rare_pair_count", 0)),
            "sample_pairs": list(doc_input.get("sample_pairs", [])),
            "threshold_count": float(threshold),
        }
        if "gl_account" in df.columns:
            value = df.at[idx, "gl_account"]
            row_annotations[annotation_key]["gl_account"] = None if pd.isna(value) else value
        if "sample_pair_count" in doc_input:
            row_annotations[annotation_key]["sample_pair_count"] = doc_input[
                "sample_pair_count"
            ]

    large_doc_rare_docs = (
        set(rare_doc_summary[rare_doc_summary["has_large_doc_pair"]].index)
        if not rare_doc_summary.empty
        else set()
    )
    result.attrs["breakdown"] = {
        "interpretation": "rare_debit_credit_pair_review_signal",
        "percentile": float(percentile),
        "threshold_count": float(threshold),
        "distinct_pair_count": int(len(pair_counts)),
        "rare_pair_count": int(len(rare_idx)),
        "candidate_document_count": int(len(rare_docs)),
        "rare_pair_review_docs": int(len(rare_docs)),
        "ordinary_rare_pair_docs": int(len(rare_docs - large_doc_rare_docs)),
        "large_doc_distinct_pair_docs": int(len(large_doc_rare_docs)),
        "pair_generation_mode": "line_pairs_with_large_doc_distinct_account_pairs",
        "large_document_line_threshold": _LARGE_DOC_LINE_THRESHOLD,
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
