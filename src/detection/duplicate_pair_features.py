"""Duplicate family pair similarity artifact.

Why: row-level duplicate scores(L2-03a/b/c/d)는 후보 pair를 만든 뒤 max로 접는
     구조다. 그 중간의 pair 정보를 별도 helper에서 재계산해 metadata로 노출하면
     "pair similarity / anomaly ranking family"로 설명 가능하다. row score 식과
     기존 4개 함수의 반환 타입은 건드리지 않아서 KPI/contract 회귀 위험 0.

도메인 한계: pair는 단순 후보다. 정상 반복 거래(월세, 주차료, 정기 카드결제)도
            동일 blocking에 들어오므로, pair_artifact는 evidence 보강용이며
            row score를 끌어올리는 추가 가중치로 쓰지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

_RULE_EXACT = "L2-03a"
_RULE_FUZZY = "L2-03b"
_RULE_SPLIT = "L2-03c"
_RULE_TIMESHIFT = "L2-03d"

_RULE_TO_SOURCE = {
    _RULE_EXACT: "exact_duplicate_amount",
    _RULE_FUZZY: "fuzzy_duplicate",
    _RULE_SPLIT: "split_transaction",
    _RULE_TIMESHIFT: "time_shifted_duplicate",
}

_RE_SPECIAL = re.compile(r"[^\w\s]", re.UNICODE)


@dataclass
class DuplicatePairArtifact:
    """Bounded pair similarity artifact attached to DuplicateDetector.metadata.

    payload는 JSON 직렬화 가능하다. 원문 적요/reference는 노출하지 않고,
    수치 feature와 sub-rule source, document_id만 남긴다.
    """

    schema_version: int = 1
    total_candidate_pairs: int = 0
    candidate_pairs_after_caps: int = 0
    retained_pairs: int = 0
    truncated: bool = False
    truncation_reason: str | None = None
    rule_pair_counts: dict[str, int] = field(default_factory=dict)
    top_pairs: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "total_candidate_pairs": int(self.total_candidate_pairs),
            "candidate_pairs_after_caps": int(self.candidate_pairs_after_caps),
            "retained_pairs": int(self.retained_pairs),
            "truncated": bool(self.truncated),
            "truncation_reason": self.truncation_reason,
            "rule_pair_counts": {str(k): int(v) for k, v in self.rule_pair_counts.items()},
            "top_pairs": list(self.top_pairs),
            "coverage": dict(self.coverage),
        }


def build_duplicate_pair_artifact(
    df: pd.DataFrame,
    settings: Any,
) -> DuplicatePairArtifact:
    """Build bounded pair similarity artifact from input frame.

    df에서 직접 후보 pair를 만든다. row-level scoring 함수(`duplicate_rules`)와
    독립적으로 동작하며, blocking은 동일한 도메인 규칙을 따른다.
    """
    artifact = DuplicatePairArtifact()
    if df is None or df.empty:
        return artifact

    fuzzy_threshold = int(getattr(settings, "duplicate_fuzzy_threshold", 80))
    amount_tolerance = float(getattr(settings, "duplicate_amount_tolerance", 0.02))
    split_window_days = int(getattr(settings, "duplicate_split_window_days", 3))
    time_window_days = int(getattr(settings, "duplicate_time_window_days", 7))
    max_group_size = int(getattr(settings, "duplicate_max_group_size", 1000))
    max_pairs_per_row = max(int(getattr(settings, "duplicate_max_pairs_per_row", 200)), 1)
    max_total_pairs = max(int(getattr(settings, "duplicate_max_total_pairs", 200_000)), 1)
    top_n = max(int(getattr(settings, "duplicate_pair_artifact_top_n", 500)), 1)

    coverage = _summarize_coverage(df)
    artifact.coverage = coverage
    if coverage["skip_all"]:
        return artifact

    max_input_rows = int(getattr(settings, "duplicate_pair_artifact_max_rows", 50_000))
    if max_input_rows > 0 and len(df) > max_input_rows:
        # Why: 100k+ 행에서 fuzzy/split blocking sweep 비용이 row scoring SLA 를 깨므로
        #      artifact 만 graceful skip 한다. row score/details 는 영향 없음.
        artifact.coverage = {
            **coverage,
            "skipped_for_size": True,
            "input_rows": int(len(df)),
            "max_input_rows": int(max_input_rows),
        }
        artifact.truncated = True
        artifact.truncation_reason = "input_too_large"
        return artifact

    context = _PairContext(
        df=df,
        max_group_size=max_group_size,
        max_pairs_per_row=max_pairs_per_row,
        max_total_pairs=max_total_pairs,
    )

    builders = [
        (_RULE_EXACT, _exact_pairs, {}),
        (
            _RULE_FUZZY,
            _fuzzy_pairs,
            {
                "fuzzy_threshold": fuzzy_threshold,
                "amount_tolerance": amount_tolerance,
            },
        ),
        (
            _RULE_SPLIT,
            _split_pairs,
            {
                "window_days": split_window_days,
                "amount_tolerance": amount_tolerance,
            },
        ),
        (
            _RULE_TIMESHIFT,
            _timeshift_pairs,
            {"window_days": time_window_days},
        ),
    ]

    candidate_records: list[dict[str, Any]] = []
    rule_counts: dict[str, int] = {}
    for rule_id, builder, kwargs in builders:
        if context.exhausted:
            break
        if rule_id == _RULE_FUZZY and not coverage["has_line_text"]:
            rule_counts[rule_id] = 0
            continue
        if (
            rule_id in {_RULE_EXACT, _RULE_SPLIT, _RULE_TIMESHIFT}
            and not coverage["has_posting_date"]
        ):
            rule_counts[rule_id] = 0
            continue
        rule_records = builder(context, **kwargs)
        rule_counts[rule_id] = len(rule_records)
        candidate_records.extend(rule_records)

    artifact.rule_pair_counts = rule_counts
    # total_candidate_pairs = cap 적용 후 helper 가 실제 생성한 pair 총수
    # candidate_pairs_after_caps = candidate_records (sort 전 모집단, total_candidate_pairs 와 동일)
    # retained_pairs = sanitize 후 metadata 에 보존되는 top pair 수 (top_n 적용)
    artifact.total_candidate_pairs = context.total_pairs
    artifact.candidate_pairs_after_caps = len(candidate_records)
    artifact.truncated = context.truncated
    artifact.truncation_reason = context.truncation_reason

    if not candidate_records:
        artifact.retained_pairs = 0
        return artifact

    candidate_records.sort(key=lambda record: record.get("pair_score", 0.0), reverse=True)
    sanitized_top = [_sanitize_pair(record, df, coverage) for record in candidate_records[:top_n]]
    artifact.top_pairs = sanitized_top
    artifact.retained_pairs = len(sanitized_top)
    return artifact


# ── Pair context ───────────────────────────────────────────────


class _PairContext:
    """Mutable helper to enforce per-row and global pair caps."""

    def __init__(
        self,
        *,
        df: pd.DataFrame,
        max_group_size: int,
        max_pairs_per_row: int,
        max_total_pairs: int,
    ) -> None:
        self.df = df
        self.amount = _base_amount(df)
        self.dates = (
            pd.to_datetime(df["posting_date"], errors="coerce")
            if "posting_date" in df.columns
            else pd.Series(pd.NaT, index=df.index)
        )
        self.text = _normalize_text_series(df["line_text"]) if "line_text" in df.columns else None
        self.gl = (
            df["gl_account"].astype("string")
            if "gl_account" in df.columns
            else pd.Series([pd.NA] * len(df), index=df.index, dtype="string")
        )
        self.partner = (
            df["trading_partner"].astype("string") if "trading_partner" in df.columns else None
        )
        self.reference = df["reference"].astype("string") if "reference" in df.columns else None
        self.document_id = (
            df["document_id"].astype("string") if "document_id" in df.columns else None
        )
        self.max_group_size = max_group_size
        self.max_pairs_per_row = max_pairs_per_row
        self.max_total_pairs = max_total_pairs
        self.total_pairs = 0
        self.truncated = False
        self.truncation_reason: str | None = None
        # per-row counter via numpy array for speed.
        self._row_counts = np.zeros(len(df), dtype=np.int32)
        self._index = df.index

    @property
    def exhausted(self) -> bool:
        # Why: 후속 후보가 존재하는 상태에서 cap에 닿았으면 truncation 이다.
        if self.total_pairs >= self.max_total_pairs:
            self.truncated = True
            self.truncation_reason = self.truncation_reason or "max_total_pairs"
            return True
        return False

    def try_add(
        self,
        *,
        left_pos: int,
        right_pos: int,
        score: float,
        rule_id: str,
        features: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.exhausted:
            self.truncated = True
            self.truncation_reason = self.truncation_reason or "max_total_pairs"
            return None
        if (
            self._row_counts[left_pos] >= self.max_pairs_per_row
            or self._row_counts[right_pos] >= self.max_pairs_per_row
        ):
            self.truncated = True
            self.truncation_reason = self.truncation_reason or "max_pairs_per_row"
            return None
        self._row_counts[left_pos] += 1
        self._row_counts[right_pos] += 1
        self.total_pairs += 1
        return {
            "left_pos": int(left_pos),
            "right_pos": int(right_pos),
            "pair_score": float(score),
            "rule_id": rule_id,
            "features": features,
        }


# ── helpers ────────────────────────────────────────────────────


def _base_amount(df: pd.DataFrame) -> pd.Series:
    if not {"debit_amount", "credit_amount"}.issubset(df.columns):
        return pd.Series(0.0, index=df.index)
    return df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)


def _normalize_text(s: str) -> str:
    cleaned = _RE_SPECIAL.sub("", str(s).lower())
    return " ".join(cleaned.split())


def _normalize_text_series(series: pd.Series) -> pd.Series:
    raw = series.fillna("").astype(str)
    unique_values = raw.unique()
    mapping = {value: _normalize_text(value) for value in unique_values}
    return raw.map(mapping)


def _summarize_coverage(df: pd.DataFrame) -> dict[str, Any]:
    has_gl = "gl_account" in df.columns
    has_amount = {"debit_amount", "credit_amount"}.issubset(df.columns)
    has_date = "posting_date" in df.columns
    has_text = "line_text" in df.columns
    has_partner = "trading_partner" in df.columns
    has_reference = "reference" in df.columns
    has_doc_id = "document_id" in df.columns
    skip_all = not (has_gl and has_amount)
    missing: list[str] = []
    if not has_gl:
        missing.append("gl_account")
    if not has_amount:
        missing.append("debit_amount/credit_amount")
    return {
        "has_gl_account": has_gl,
        "has_amount": has_amount,
        "has_posting_date": has_date,
        "has_line_text": has_text,
        "has_trading_partner": has_partner,
        "has_reference": has_reference,
        "has_document_id": has_doc_id,
        "missing_required": missing,
        "skip_all": skip_all,
    }


def _amount_diff_ratio(a: float, b: float) -> float:
    larger = max(abs(a), abs(b))
    if larger <= 0:
        return 0.0
    return float(abs(a - b) / larger)


def _date_distance_days(left: np.datetime64, right: np.datetime64) -> int | None:
    if pd.isna(left) or pd.isna(right):
        return None
    delta = np.datetime64(right) - np.datetime64(left)
    return int(abs(delta / np.timedelta64(1, "D")))


def _same_partner(context: _PairContext, left_pos: int, right_pos: int) -> bool | None:
    if context.partner is None:
        return None
    left_value = context.partner.iat[left_pos]
    right_value = context.partner.iat[right_pos]
    if pd.isna(left_value) or pd.isna(right_value):
        return None
    return bool(str(left_value).strip() == str(right_value).strip() and str(left_value).strip())


def _reference_similarity(context: _PairContext, left_pos: int, right_pos: int) -> float | None:
    if context.reference is None:
        return None
    left_value = context.reference.iat[left_pos]
    right_value = context.reference.iat[right_pos]
    if pd.isna(left_value) or pd.isna(right_value):
        return None
    left_clean = str(left_value).strip()
    right_clean = str(right_value).strip()
    if not left_clean or not right_clean:
        return None
    return float(fuzz.token_sort_ratio(left_clean, right_clean) / 100.0)


def _text_similarity(context: _PairContext, left_pos: int, right_pos: int) -> float | None:
    if context.text is None:
        return None
    left_value = context.text.iat[left_pos]
    right_value = context.text.iat[right_pos]
    if not left_value or not right_value:
        return None
    return float(fuzz.token_sort_ratio(left_value, right_value) / 100.0)


# ── L2-03a: exact pairs ────────────────────────────────────────


def _exact_pairs(context: _PairContext) -> list[dict[str, Any]]:
    df = context.df
    work = pd.DataFrame(
        {
            "gl_account": df["gl_account"].astype("string"),
            "posting_date": context.dates,
            "_amt": context.amount,
            "_pos": np.arange(len(df), dtype=np.int64),
        },
        index=df.index,
    )
    work = work.dropna(subset=["gl_account", "posting_date", "_amt"])
    grouped = work.groupby(["gl_account", "_amt", "posting_date"], sort=False, dropna=False)
    records: list[dict[str, Any]] = []
    for _key, group in grouped:
        if len(group) < 2:
            continue
        if len(group) > context.max_group_size:
            context.truncated = True
            context.truncation_reason = context.truncation_reason or "max_group_size"
            continue
        positions = group["_pos"].to_numpy(dtype=np.int64)
        amounts = group["_amt"].to_numpy(dtype=float)
        for left_idx in range(len(positions)):
            if context.exhausted:
                return records
            for right_idx in range(left_idx + 1, len(positions)):
                if context.exhausted:
                    return records
                left_pos = int(positions[left_idx])
                right_pos = int(positions[right_idx])
                features = _common_features(
                    context,
                    left_pos=left_pos,
                    right_pos=right_pos,
                    amount_left=amounts[left_idx],
                    amount_right=amounts[right_idx],
                )
                features["amount_similarity"] = 1.0
                features["date_similarity"] = 1.0
                features["text_similarity"] = _text_similarity(context, left_pos, right_pos)
                record = context.try_add(
                    left_pos=left_pos,
                    right_pos=right_pos,
                    score=1.0,
                    rule_id=_RULE_EXACT,
                    features=features,
                )
                if record is not None:
                    records.append(record)
    return records


# ── L2-03b: fuzzy pairs ────────────────────────────────────────


def _fuzzy_pairs(
    context: _PairContext,
    *,
    fuzzy_threshold: int,
    amount_tolerance: float,
) -> list[dict[str, Any]]:
    df = context.df
    threshold = fuzzy_threshold / 100.0
    tolerance = max(amount_tolerance, 0.0)
    work = pd.DataFrame(
        {
            "gl_account": df["gl_account"].astype("string"),
            "amount": context.amount,
            "text": context.text,
            "_pos": np.arange(len(df), dtype=np.int64),
        },
        index=df.index,
    ).dropna(subset=["gl_account"])
    work = work[work["amount"] > 0]
    records: list[dict[str, Any]] = []
    for _gl, group in work.groupby("gl_account", sort=False, dropna=False):
        if len(group) < 2:
            continue
        if len(group) > context.max_group_size:
            context.truncated = True
            context.truncation_reason = context.truncation_reason or "max_group_size"
            continue
        ordered = group.sort_values("amount", kind="mergesort")
        amounts = ordered["amount"].to_numpy(dtype=float)
        texts = ordered["text"].to_numpy(dtype=object)
        positions = ordered["_pos"].to_numpy(dtype=np.int64)
        n = len(ordered)
        upper = 1
        for i in range(n):
            if context.exhausted:
                return records
            base_amt = amounts[i]
            if base_amt <= 0:
                continue
            if upper < i + 1:
                upper = i + 1
            max_candidate_amt = base_amt / max(1.0 - tolerance, 1e-12)
            while upper < n and amounts[upper] <= max_candidate_amt:
                upper += 1
            if upper <= i + 1:
                continue
            for j in range(i + 1, upper):
                if context.exhausted:
                    return records
                rel_diff = _amount_diff_ratio(base_amt, amounts[j])
                if rel_diff > tolerance:
                    continue
                text_sim = (
                    float(fuzz.token_sort_ratio(texts[i], texts[j]) / 100.0)
                    if texts[i] and texts[j]
                    else 0.0
                )
                if text_sim < threshold:
                    continue
                left_pos = int(positions[i])
                right_pos = int(positions[j])
                score = float(text_sim * (1.0 - rel_diff))
                amount_similarity = float(max(0.0, 1.0 - rel_diff))
                features = _common_features(
                    context,
                    left_pos=left_pos,
                    right_pos=right_pos,
                    amount_left=base_amt,
                    amount_right=amounts[j],
                )
                features["amount_similarity"] = amount_similarity
                features["text_similarity"] = text_sim
                # Why: fuzzy 는 amount + text 유사도가 본질이고 날짜 window 가 정의되어 있지
                #      않다. date_similarity 를 임의 분모로 정규화하면 artifact 가 왜곡되므로
                #      거리 자체(date_distance_days)만 남기고 similarity 는 기록하지 않는다.
                features["date_similarity"] = None
                record = context.try_add(
                    left_pos=left_pos,
                    right_pos=right_pos,
                    score=score,
                    rule_id=_RULE_FUZZY,
                    features=features,
                )
                if record is not None:
                    records.append(record)
    return records


# ── L2-03c: split pairs ────────────────────────────────────────


def _split_pairs(
    context: _PairContext,
    *,
    window_days: int,
    amount_tolerance: float,
) -> list[dict[str, Any]]:
    df = context.df
    tolerance = max(amount_tolerance, 0.0)
    day_ns = np.timedelta64(1, "D").astype("timedelta64[ns]").astype(np.int64)
    window_ns = int(window_days * day_ns)
    work = pd.DataFrame(
        {
            "gl_account": df["gl_account"].astype("string"),
            "posting_date": context.dates,
            "amount": context.amount,
            "_pos": np.arange(len(df), dtype=np.int64),
        },
        index=df.index,
    ).dropna(subset=["gl_account", "posting_date"])
    work = work[work["amount"] > 0]
    records: list[dict[str, Any]] = []
    for _gl, group in work.groupby("gl_account", sort=False, dropna=False):
        if len(group) < 3:
            continue
        if len(group) > context.max_group_size:
            context.truncated = True
            context.truncation_reason = context.truncation_reason or "max_group_size"
            continue
        ordered = group.sort_values("posting_date", kind="mergesort")
        amounts = ordered["amount"].to_numpy(dtype=float)
        dates_ns = ordered["posting_date"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
        positions = ordered["_pos"].to_numpy(dtype=np.int64)
        n = len(ordered)
        for t_pos in range(n):
            if context.exhausted:
                return records
            target = amounts[t_pos]
            if target <= 0:
                continue
            left = np.searchsorted(dates_ns, dates_ns[t_pos] - window_ns, side="left")
            right = np.searchsorted(dates_ns, dates_ns[t_pos] + window_ns, side="right")
            if right - left < 3:
                continue
            window_idx = np.arange(left, right)
            mask = (
                (window_idx != t_pos) & (amounts[window_idx] > 0) & (amounts[window_idx] < target)
            )
            candidate_idx = window_idx[mask]
            if len(candidate_idx) < 2:
                continue
            candidate_amounts = amounts[candidate_idx]
            order = np.argsort(candidate_amounts, kind="mergesort")
            sorted_amounts = candidate_amounts[order]
            sorted_idx = candidate_idx[order]
            low = target * (1.0 - tolerance)
            high = target * (1.0 + tolerance)
            for left_offset, left_amount in enumerate(sorted_amounts[:-1]):
                if context.exhausted:
                    return records
                lo = np.searchsorted(sorted_amounts, low - left_amount, side="left")
                hi = np.searchsorted(sorted_amounts, high - left_amount, side="right")
                lo = max(lo, left_offset + 1)
                if hi <= lo:
                    continue
                left_pos = int(positions[sorted_idx[left_offset]])
                for right_offset in range(lo, hi):
                    if context.exhausted:
                        return records
                    right_pos = int(positions[sorted_idx[right_offset]])
                    pair_sum = float(left_amount + sorted_amounts[right_offset])
                    sum_diff_ratio = _amount_diff_ratio(target, pair_sum)
                    amount_similarity = float(max(0.0, 1.0 - sum_diff_ratio))
                    score = float(0.7 * amount_similarity)
                    features = _common_features(
                        context,
                        left_pos=left_pos,
                        right_pos=right_pos,
                        amount_left=float(left_amount),
                        amount_right=float(sorted_amounts[right_offset]),
                    )
                    features["amount_similarity"] = amount_similarity
                    features["pair_sum"] = pair_sum
                    features["target_amount"] = float(target)
                    features["target_pos"] = int(positions[t_pos])
                    features["date_similarity"] = _date_similarity(
                        context,
                        left_pos,
                        right_pos,
                        window_days=window_days,
                    )
                    features["text_similarity"] = _text_similarity(context, left_pos, right_pos)
                    record = context.try_add(
                        left_pos=left_pos,
                        right_pos=right_pos,
                        score=score,
                        rule_id=_RULE_SPLIT,
                        features=features,
                    )
                    if record is not None:
                        records.append(record)
    return records


# ── L2-03d: time-shifted pairs ────────────────────────────────


def _timeshift_pairs(
    context: _PairContext,
    *,
    window_days: int,
) -> list[dict[str, Any]]:
    df = context.df
    day_ns = np.timedelta64(1, "D").astype("timedelta64[ns]").astype(np.int64)
    window_ns = int(window_days * day_ns)
    dates_arr = context.dates.to_numpy(dtype="datetime64[ns]")
    valid_mask = ~pd.isna(context.dates).to_numpy()
    if not valid_mask.any():
        return []
    positions_all = np.arange(len(df), dtype=np.int64)
    gl_codes_full, _ = pd.factorize(df["gl_account"], sort=False)
    gl_codes = gl_codes_full[valid_mask]
    amounts = context.amount.to_numpy(dtype=float)[valid_mask]
    floors = np.floor(amounts).astype(np.int64)
    dates_ns = dates_arr.astype(np.int64)[valid_mask]
    positions = positions_all[valid_mask]

    order = np.lexsort((floors, gl_codes))
    gl_codes = gl_codes[order]
    floors = floors[order]
    amounts = amounts[order]
    dates_ns = dates_ns[order]
    positions = positions[order]

    breaks = np.flatnonzero((gl_codes[1:] != gl_codes[:-1]) | (floors[1:] != floors[:-1])) + 1
    starts = np.r_[0, breaks]
    ends = np.r_[breaks, len(order)]
    records: list[dict[str, Any]] = []
    for start, end in zip(starts, ends, strict=True):
        if context.exhausted:
            return records
        group_size = end - start
        if group_size < 2:
            continue
        if group_size > context.max_group_size:
            context.truncated = True
            context.truncation_reason = context.truncation_reason or "max_group_size"
            continue
        group_dates = dates_ns[start:end]
        group_positions = positions[start:end]
        group_amounts = amounts[start:end]
        date_order = np.argsort(group_dates, kind="mergesort")
        grp_dates = group_dates[date_order]
        grp_positions = group_positions[date_order]
        grp_amounts = group_amounts[date_order]
        n = len(grp_dates)
        upper = 1
        for i in range(n):
            if context.exhausted:
                return records
            if upper < i + 1:
                upper = i + 1
            while upper < n and grp_dates[upper] - grp_dates[i] <= window_ns:
                upper += 1
            for j in range(i + 1, upper):
                if context.exhausted:
                    return records
                day_diff = (grp_dates[j] - grp_dates[i]) / day_ns
                if day_diff <= 0:
                    continue
                pair_score = float(1.0 - (day_diff / window_days))
                left_pos = int(grp_positions[i])
                right_pos = int(grp_positions[j])
                date_similarity = float(max(0.0, 1.0 - day_diff / window_days))
                features = _common_features(
                    context,
                    left_pos=left_pos,
                    right_pos=right_pos,
                    amount_left=float(grp_amounts[i]),
                    amount_right=float(grp_amounts[j]),
                )
                features["amount_similarity"] = float(
                    max(
                        0.0,
                        1.0 - _amount_diff_ratio(float(grp_amounts[i]), float(grp_amounts[j])),
                    )
                )
                features["date_similarity"] = date_similarity
                features["date_distance_days"] = int(day_diff)
                features["text_similarity"] = _text_similarity(context, left_pos, right_pos)
                record = context.try_add(
                    left_pos=left_pos,
                    right_pos=right_pos,
                    score=pair_score,
                    rule_id=_RULE_TIMESHIFT,
                    features=features,
                )
                if record is not None:
                    records.append(record)
    return records


# ── feature helpers ───────────────────────────────────────────


def _common_features(
    context: _PairContext,
    *,
    left_pos: int,
    right_pos: int,
    amount_left: float,
    amount_right: float,
) -> dict[str, Any]:
    diff_ratio = _amount_diff_ratio(amount_left, amount_right)
    date_distance = _date_distance_days(context.dates.iat[left_pos], context.dates.iat[right_pos])
    same_partner = _same_partner(context, left_pos, right_pos)
    reference_similarity = _reference_similarity(context, left_pos, right_pos)
    same_account = (
        bool(context.gl.iat[left_pos] == context.gl.iat[right_pos])
        if not (pd.isna(context.gl.iat[left_pos]) or pd.isna(context.gl.iat[right_pos]))
        else False
    )
    return {
        "amount_diff_ratio": float(diff_ratio),
        "date_distance_days": date_distance,
        "same_account": same_account,
        "same_partner": same_partner,
        "reference_similarity": reference_similarity,
    }


def _date_similarity(
    context: _PairContext,
    left_pos: int,
    right_pos: int,
    *,
    window_days: int,
) -> float | None:
    distance = _date_distance_days(context.dates.iat[left_pos], context.dates.iat[right_pos])
    if distance is None:
        return None
    if window_days <= 0:
        return 0.0
    return float(max(0.0, 1.0 - distance / window_days))


def _sanitize_pair(
    record: dict[str, Any],
    df: pd.DataFrame,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    left_pos = record["left_pos"]
    right_pos = record["right_pos"]
    rule_id = record["rule_id"]
    features = dict(record.get("features", {}))
    left_label = df.index[left_pos]
    right_label = df.index[right_pos]
    payload: dict[str, Any] = {
        "rule_id": rule_id,
        "rule_source": _RULE_TO_SOURCE.get(rule_id, rule_id),
        "pair_score": float(record["pair_score"]),
        "left_index": _json_safe(left_label),
        "right_index": _json_safe(right_label),
        "features": _sanitize_features(features),
    }
    if coverage["has_document_id"]:
        payload["left_document_id"] = _safe_str(df["document_id"].iat[left_pos])
        payload["right_document_id"] = _safe_str(df["document_id"].iat[right_pos])
    return payload


def _sanitize_features(features: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in features.items():
        if isinstance(value, bool) or value is None:
            cleaned[key] = value
        elif isinstance(value, (int, np.integer)):
            cleaned[key] = int(value)
        elif isinstance(value, (float, np.floating)):
            cleaned[key] = None if np.isnan(value) else float(value)
        else:
            cleaned[key] = _safe_str(value)
    return cleaned


def _safe_str(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return str(value)
