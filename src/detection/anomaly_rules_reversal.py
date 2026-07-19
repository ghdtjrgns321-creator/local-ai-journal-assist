"""Reversal-pattern rule helpers for L2-05."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config.settings import get_audit_rules

logger = logging.getLogger(__name__)

_CORE_COLUMNS = ["gl_account", "debit_amount", "credit_amount", "posting_date", "document_id"]
_STRUCTURAL_REFERENCE_COLUMNS = [
    "original_document_id",
    "reversal_document_id",
    "reference_document_id",
    "reversed_document_id",
    "reverse_document_id",
]
_REVERSAL_REASON_COLUMNS = ["reversal_reason", "reversal_reason_code"]
_FALLBACK_EXCLUDE_ACCOUNTS = ["2900", "1150", "2050"]
_LARGE_GROUP_WARN = 500


def _load_exclude_accounts() -> list[str]:
    """Load GL-account prefixes excluded from reversal mirror-pair logic."""

    try:
        rules = get_audit_rules()
        prefixes = rules.get("patterns", {}).get("reversal_exclude_accounts", [])
        return [str(prefix) for prefix in prefixes] or _FALLBACK_EXCLUDE_ACCOUNTS
    except Exception:
        return _FALLBACK_EXCLUDE_ACCOUNTS


_EXCLUDE_ACCOUNTS = _load_exclude_accounts()


def _has_value(series: pd.Series) -> pd.Series:
    """Return True for meaningful non-empty ERP reference values."""

    normalized = series.fillna("").astype(str).str.strip().str.lower()
    return normalized.ne("") & ~normalized.isin(["nan", "none", "null"])


# 부동소수 합산 오차 흡수용 절대 epsilon. tolerance=0.0(정확일치) 의도를 해치지 않으면서
# 다중 라인 전표 groupby-sum의 float 결합법칙 오차(예: 7×0.07 vs 0.49 = 5.5e-17)를 흡수한다.
# 회계 최소단위(원/센트) 미만이라 정수 KRW·센트 통화의 실제 금액 차이는 그대로 구분한다.
_AMOUNT_FLOOR_EPSILON = 0.005

# 거울쌍 후보 블로킹용 금액 키 그리드(0.01=센트). 역분개는 금액이 정확일치해야 하므로
# gl_account 뿐 아니라 금액 키로도 블로킹해 same-account·same-amount 후보끼리만 매칭한다.
# epsilon(0.005) 이하 float 오차는 같은 키로 흡수된다. 한 계정에 역분개가 집중돼도 gl_account
# 단독 merge 의 O(n^2) 카테시안(대량 same-account 그룹에서 OOM)을 피한다.
_AMOUNT_KEY_QUANTUM = 0.01


def _is_amount_close(left: float, right: float, tolerance: float) -> bool:
    """Return True when amounts are equal within a relative tolerance.

    tolerance=0.0(정확일치)이라도 _AMOUNT_FLOOR_EPSILON(0.005) 이하의 부동소수 합산 오차는
    흡수한다 — 역분개 exact reverse 의도를 유지하면서 다중라인 float 오차로 인한 미탐을 막는다.
    """

    left_abs = abs(float(left))
    right_abs = abs(float(right))
    if left_abs == 0 or right_abs == 0:
        return abs(left_abs - right_abs) <= _AMOUNT_FLOOR_EPSILON
    return abs(left_abs - right_abs) <= max(
        max(left_abs, right_abs) * tolerance, _AMOUNT_FLOOR_EPSILON
    )


def _s0_structural_reversal_reference(df: pd.DataFrame) -> pd.Series:
    """Return True when ERP fields explicitly link original/reversal documents."""

    if "document_id" not in df.columns:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)
    doc_ids = df["document_id"].fillna("").astype(str).str.strip()
    referenced_ids: set[str] = set()

    for column in _STRUCTURAL_REFERENCE_COLUMNS:
        if column not in df.columns:
            continue
        values = df[column].fillna("").astype(str).str.strip()
        value_mask = _has_value(values)
        result |= value_mask
        referenced_ids.update(values[value_mask].tolist())

    for column in _REVERSAL_REASON_COLUMNS:
        if column in df.columns:
            result |= _has_value(df[column])

    referenced_ids.discard("")
    if referenced_ids:
        result |= doc_ids.isin(referenced_ids)

    return result


def _s0_reference_details(df: pd.DataFrame, s0: pd.Series) -> dict[object, dict[str, object]]:
    """Build row-level ERP reversal-reference details."""

    details: dict[object, dict[str, object]] = {}
    if "document_id" not in df.columns:
        return details

    doc_ids = df["document_id"].fillna("").astype(str).str.strip()
    doc_to_indices: dict[str, list[object]] = {}
    for index, doc_id in doc_ids.items():
        if doc_id:
            doc_to_indices.setdefault(doc_id, []).append(index)

    linked_counterparts: dict[object, set[str]] = {}
    structural_fields: dict[object, set[str]] = {}
    for column in _STRUCTURAL_REFERENCE_COLUMNS:
        if column not in df.columns:
            continue
        values = df[column].fillna("").astype(str).str.strip()
        for index, value in values[_has_value(values)].items():
            structural_fields.setdefault(index, set()).add(column)
            if value:
                linked_counterparts.setdefault(index, set()).add(value)
                current_doc = str(doc_ids.loc[index])
                for referenced_index in doc_to_indices.get(value, []):
                    linked_counterparts.setdefault(referenced_index, set()).add(current_doc)
                    structural_fields.setdefault(referenced_index, set()).add(column)

    reason_fields: dict[object, set[str]] = {}
    for column in _REVERSAL_REASON_COLUMNS:
        if column not in df.columns:
            continue
        values = df[column]
        for index in values[_has_value(values)].index:
            reason_fields.setdefault(index, set()).add(column)

    for index in s0[s0].index:
        details[index] = {
            "path": "A",
            "trigger": "erp_reversal_reference",
            "counterpart_document_ids": sorted(linked_counterparts.get(index, set())),
            "reference_fields": sorted(structural_fields.get(index, set())),
            "reason_fields": sorted(reason_fields.get(index, set())),
        }
    return details


def _amount_band_candidate_pairs(
    positives: pd.DataFrame,
    negatives: pd.DataFrame,
    amount_tolerance: float,
) -> pd.DataFrame:
    """tolerance>0 거울쌍 후보를 gl_account 별 정렬 + searchsorted 밴드 조인으로 생성한다.

    각 양수 doc-net 은 [|net|-band, |net|+band] 범위의 음수 doc-net 과만 매칭한다
    (band = max(|net|*tolerance, epsilon)). gl_account 단독 merge 와 동일한 후보 집합을 내되
    실제 매칭 수에 비례해 O(n^2) 카테시안 폭발을 피한다. 정확일치(tolerance=0)는 상위에서 금액
    키 merge 로 처리하므로 이 경로는 tolerance>0 전용이다.
    """
    pos = positives.reset_index(drop=True)
    neg = negatives.reset_index(drop=True)
    neg_groups = {account: subset for account, subset in neg.groupby("gl_account", sort=False)}
    pos_row_ids: list[np.ndarray] = []
    neg_row_ids: list[np.ndarray] = []
    for account, pos_sub in pos.groupby("gl_account", sort=False):
        neg_sub = neg_groups.get(account)
        if neg_sub is None:
            continue
        neg_abs = neg_sub["_abs"].to_numpy()
        order = np.argsort(neg_abs, kind="stable")
        neg_abs_sorted = neg_abs[order]
        neg_index_sorted = neg_sub.index.to_numpy()[order]
        pos_abs = pos_sub["_abs"].to_numpy()
        pos_index = pos_sub.index.to_numpy()
        band = np.maximum(pos_abs * float(amount_tolerance), _AMOUNT_FLOOR_EPSILON)
        lo = np.searchsorted(neg_abs_sorted, pos_abs - band, side="left")
        hi = np.searchsorted(neg_abs_sorted, pos_abs + band, side="right")
        for k in np.nonzero(hi - lo)[0]:
            matched = neg_index_sorted[lo[k] : hi[k]]
            pos_row_ids.append(np.full(matched.shape, pos_index[k], dtype="int64"))
            neg_row_ids.append(matched)
    if not pos_row_ids:
        return pd.DataFrame()
    left = pos.iloc[np.concatenate(pos_row_ids)].reset_index(drop=True)
    right = neg.iloc[np.concatenate(neg_row_ids)].reset_index(drop=True)
    return pd.DataFrame(
        {
            "gl_account": left["gl_account"],
            "net_pos": left["net"],
            "net_neg": right["net"],
            "posting_date_pos": left["posting_date"],
            "posting_date_neg": right["posting_date"],
            "document_id_pos": left["document_id"],
            "document_id_neg": right["document_id"],
            "row_indices_pos": left["row_indices"],
            "row_indices_neg": right["row_indices"],
        }
    )


def _s1_one_to_one_match(
    df: pd.DataFrame,
    match_window_days: int = 45,
    amount_tolerance: float = 0.0,
) -> pd.Series:
    """Return True for same-account, opposite-side, one-to-one reversal mirror pairs.

    amount_tolerance 기본 0.0(정확일치): 역분개는 ERP 표준상 exact reverse이므로 원전표와
    금액이 정확히 같다. 구 0.02는 정상 순환거래를 우연 동액으로 대량 오탐했다.
    """

    required = ["document_id", "gl_account", "debit_amount", "credit_amount", "posting_date"]
    if any(column not in df.columns for column in required):
        result = pd.Series(False, index=df.index)
        result.attrs["pair_details"] = {}
        return result

    work = pd.DataFrame(index=df.index)
    work["document_id"] = df["document_id"].fillna("").astype(str).str.strip()
    work["gl_account"] = df["gl_account"].fillna("").astype(str).str.strip()
    work["posting_date"] = pd.to_datetime(df["posting_date"], errors="coerce")
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    work["net"] = debit - credit
    work["_row_index"] = work.index

    candidate_mask = (
        work["document_id"].ne("")
        & work["gl_account"].ne("")
        & work["posting_date"].notna()
        & work["net"].ne(0.0)
    )
    if _EXCLUDE_ACCOUNTS:
        candidate_mask &= ~work["gl_account"].apply(
            lambda value: any(value.startswith(prefix) for prefix in _EXCLUDE_ACCOUNTS),
        )
    work = work.loc[candidate_mask]
    if len(work) < 2:
        result = pd.Series(False, index=df.index)
        result.attrs["pair_details"] = {}
        return result

    doc_work = (
        work.groupby(["document_id", "gl_account"], sort=False)
        .agg(
            posting_date=("posting_date", "min"),
            net=("net", "sum"),
            row_indices=("_row_index", list),
        )
        .reset_index()
    )
    doc_work = doc_work.loc[doc_work["net"].ne(0.0)]
    positives = doc_work.loc[doc_work["net"] > 0]
    negatives = doc_work.loc[doc_work["net"] < 0]
    if positives.empty or negatives.empty:
        result = pd.Series(False, index=df.index)
        result.attrs["pair_details"] = {}
        return result

    group_sizes = doc_work.groupby("gl_account").size()
    large_groups = int((group_sizes > _LARGE_GROUP_WARN).sum())
    if large_groups:
        logger.warning(
            "L2-05 S1 found %d large groups above %d rows",
            large_groups,
            _LARGE_GROUP_WARN,
        )

    # 카테시안 폭발 방지: 거울쌍은 |net_pos| == |net_neg|(tolerance 내)이므로 금액으로도 블로킹한다.
    # gl_account 단독 merge 의 O(n^2)(대량 same-account 역분개 집중 시 OOM)을 무손실로 제거.
    positives = positives.assign(_abs=positives["net"].abs())
    negatives = negatives.assign(_abs=negatives["net"].abs())

    if amount_tolerance > 0:
        # 상대 tolerance: 계정별 정렬 밴드 조인(이웃 금액 키 복제는 큰 금액에서 폭발하므로 회피).
        candidate_pairs = _amount_band_candidate_pairs(positives, negatives, amount_tolerance)
    else:
        # 정확일치(운영 기본): 금액 키(센트) merge. epsilon 이하 float 오차는 같은 키로 흡수된다.
        positives = positives.assign(
            _amt_key=np.rint(positives["_abs"].to_numpy() / _AMOUNT_KEY_QUANTUM).astype("int64")
        )
        negatives = negatives.assign(
            _amt_key=np.rint(negatives["_abs"].to_numpy() / _AMOUNT_KEY_QUANTUM).astype("int64")
        )
        candidate_pairs = positives.merge(
            negatives, on=["gl_account", "_amt_key"], suffixes=("_pos", "_neg")
        )
    if candidate_pairs.empty:
        result = pd.Series(False, index=df.index)
        result.attrs["pair_details"] = {}
        return result

    day_gap = (
        (candidate_pairs["posting_date_pos"] - candidate_pairs["posting_date_neg"]).abs().dt.days
    )
    different_docs = candidate_pairs["document_id_pos"].ne(candidate_pairs["document_id_neg"])
    in_window = day_gap.le(int(match_window_days))
    amount_close = [
        _is_amount_close(pos_amount, neg_amount, amount_tolerance)
        for pos_amount, neg_amount in zip(
            candidate_pairs["net_pos"],
            candidate_pairs["net_neg"],
            strict=False,
        )
    ]
    amount_close_mask = pd.Series(amount_close, index=candidate_pairs.index)
    candidate_pairs = candidate_pairs.loc[different_docs & in_window & amount_close_mask]
    if candidate_pairs.empty:
        result = pd.Series(False, index=df.index)
        result.attrs["pair_details"] = {}
        return result

    matched_indices: set[object] = set()
    pair_details: dict[object, dict[str, object]] = {}
    for pair in candidate_pairs.itertuples(index=False):
        amount_difference = abs(abs(float(pair.net_pos)) - abs(float(pair.net_neg)))
        day_difference = abs((pair.posting_date_pos - pair.posting_date_neg).days)
        amount = max(abs(float(pair.net_pos)), abs(float(pair.net_neg)))
        pos_indices = list(pair.row_indices_pos)
        neg_indices = list(pair.row_indices_neg)
        matched_indices.update(pos_indices)
        matched_indices.update(neg_indices)
        for index in pos_indices:
            pair_details[index] = {
                "path": "B",
                "trigger": "one_to_one_mirror_pair",
                "counterpart_document_id": str(pair.document_id_neg),
                "gl_account": str(pair.gl_account),
                "amount": amount,
                "amount_difference": amount_difference,
                "day_gap": int(day_difference),
                "match_window_days": int(match_window_days),
            }
        for index in neg_indices:
            pair_details[index] = {
                "path": "B",
                "trigger": "one_to_one_mirror_pair",
                "counterpart_document_id": str(pair.document_id_pos),
                "gl_account": str(pair.gl_account),
                "amount": amount,
                "amount_difference": amount_difference,
                "day_gap": int(day_difference),
                "match_window_days": int(match_window_days),
            }

    result = pd.Series(df.index.isin(matched_indices), index=df.index)
    result.attrs["pair_details"] = pair_details
    return result


def _build_row_annotations(
    flagged: pd.Series,
    *,
    s0_details: dict[object, dict[str, object]],
    s1_details: dict[object, dict[str, object]],
) -> dict[object, dict[str, object]]:
    """Build row-level interpretation metadata for surfaced L2-05 hits."""

    annotations: dict[object, dict[str, object]] = {}
    for index in flagged[flagged].index.tolist():
        paths: list[str] = []
        annotation: dict[str, object] = {"score": 1.0}
        if index in s0_details:
            paths.append("A")
            annotation.update(s0_details[index])
        if index in s1_details:
            paths.append("B")
            annotation.update(s1_details[index])
        annotation["paths"] = paths
        annotations[index] = annotation
    return annotations


def c11_reversal_entry(
    df: pd.DataFrame,
    *,
    match_window_days: int = 45,
    amount_tolerance: float = 0.0,
) -> pd.Series:
    """Binary L2-05 reversal detector: ERP link or same-account mirror pair.

    amount_tolerance 기본 0.0(정확일치): 역분개=exact reverse 도메인 원리. 운영 값은
    config `reversal_amount_tolerance`로 주입(anomaly_layer). 근거:
    docs/spec/results/normal/L2-05_REVERSAL_TOLERANCE_DECISION.md
    """

    missing = [column for column in _CORE_COLUMNS if column not in df.columns]
    if missing or len(df) < 2:
        if missing:
            logger.warning("L2-05 missing required columns: %s", missing)
        result = pd.Series(False, index=df.index)
        result.attrs["score_series"] = pd.Series(0.0, index=df.index)
        result.attrs["breakdown"] = {"flagged_rows": 0, "erp_rows": 0, "mirror_pair_rows": 0}
        result.attrs["row_annotations"] = {}
        return result

    s0 = _s0_structural_reversal_reference(df)
    s1 = _s1_one_to_one_match(
        df,
        match_window_days=match_window_days,
        amount_tolerance=amount_tolerance,
    )

    flagged = s0.astype(bool) | s1.astype(bool)
    score_series = flagged.astype(float)
    s0_details = _s0_reference_details(df, s0)
    s1_details = s1.attrs.get("pair_details", {})
    flagged.attrs["breakdown"] = {
        "flagged_rows": int(flagged.sum()),
        "erp_rows": int(s0.sum()),
        "mirror_pair_rows": int(s1.sum()),
        "matched_docs": int(df.loc[flagged, "document_id"].fillna("").astype(str).nunique()),
    }
    flagged.attrs["score_series"] = score_series
    flagged.attrs["row_annotations"] = _build_row_annotations(
        flagged,
        s0_details=s0_details,
        s1_details=s1_details,
    )
    return flagged
