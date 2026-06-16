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
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from src.services.duplicate_pair_tier import classify_pair_evidence_tier, pair_tier_weight

_RULE_EXACT = "L2-03a"
_RULE_FUZZY = "L2-03b"
_RULE_SPLIT = "L2-03c"
_RULE_TIMESHIFT = "L2-03d"
_RULE_PROFILE = "L2-03e"

_RULE_TO_SOURCE = {
    _RULE_EXACT: "exact_duplicate_amount",
    _RULE_FUZZY: "fuzzy_duplicate",
    _RULE_SPLIT: "split_transaction",
    _RULE_TIMESHIFT: "time_shifted_duplicate",
    _RULE_PROFILE: "document_profile_duplicate",
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
    *,
    candidate_scores: pd.Series | None = None,
    candidate_details: pd.DataFrame | None = None,
) -> DuplicatePairArtifact:
    """Build bounded pair similarity artifact from input frame.

    df에서 직접 후보 pair를 만든다. row-level scoring 함수(`duplicate_rules`)와
    독립적으로 동작하며, blocking은 동일한 도메인 규칙을 따른다. 대용량 입력은
    전체 artifact skip 대신 row-score 후보 subset에서 pair evidence를 재계산한다.
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
    max_pairs_per_document = max(
        int(getattr(settings, "duplicate_pair_artifact_max_pairs_per_document", 5)),
        0,
    )
    max_pairs_per_document_pair = max(
        int(getattr(settings, "duplicate_pair_artifact_max_pairs_per_document_pair", 1)),
        0,
    )
    recurring_suppress_enabled = bool(
        getattr(settings, "duplicate_recurring_suppress_enabled", True)
    )

    coverage = _summarize_coverage(df)
    artifact.coverage = coverage
    if coverage["skip_all"]:
        return artifact

    max_input_rows = int(getattr(settings, "duplicate_pair_artifact_max_rows", 50_000))
    if max_input_rows > 0 and len(df) > max_input_rows:
        candidate_df, candidate_coverage = _select_large_input_candidate_frame(
            df,
            max_rows=max_input_rows,
            candidate_scores=candidate_scores,
            candidate_details=candidate_details,
            candidate_supplement_strategy=str(
                getattr(
                    settings,
                    "duplicate_pair_artifact_candidate_supplement_strategy",
                    "none",
                )
            ),
            candidate_supplement_max_docs=int(
                getattr(settings, "duplicate_pair_artifact_candidate_supplement_max_docs", 0)
            ),
        )
        artifact.coverage = {
            **coverage,
            **candidate_coverage,
            "input_rows": int(len(df)),
            "max_input_rows": int(max_input_rows),
        }
        if candidate_df is None:
            # Why: 100k+ 행에서 row-score 후보 없이 fuzzy/split blocking sweep 를
            #      전체 실행하면 row scoring SLA 를 깨므로 artifact 만 graceful skip 한다.
            artifact.truncated = True
            artifact.truncation_reason = "input_too_large_no_candidate_subset"
            return artifact
        df = candidate_df
        coverage = artifact.coverage

    context = _PairContext(
        df=df,
        max_group_size=max_group_size,
        max_pairs_per_row=max_pairs_per_row,
        max_total_pairs=max_total_pairs,
    )

    builders = [
        (
            _RULE_PROFILE,
            _document_profile_pairs,
            {
                "window_days": time_window_days,
                "amount_tolerance": amount_tolerance,
            },
        ),
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

    suppress_diagnostics: dict[str, Any] = {}
    if recurring_suppress_enabled and candidate_records:
        candidate_records, suppress_diagnostics = _suppress_recurring_duplicate_records(
            candidate_records,
            context,
            settings,
        )
        rule_counts = dict(Counter(record.get("rule_id", "") for record in candidate_records))

    artifact.rule_pair_counts = rule_counts
    # total_candidate_pairs = suppress 후 measurement candidate pair 총수.
    # retained_pairs = metadata 에 보존되는 pair 수.
    # P2-3 measurement 에서는 임의 top-N cap 을 쓰지 않는다.
    artifact.total_candidate_pairs = len(candidate_records)
    artifact.candidate_pairs_after_caps = len(candidate_records)
    artifact.truncated = context.truncated
    artifact.truncation_reason = context.truncation_reason
    if suppress_diagnostics:
        artifact.coverage = {
            **artifact.coverage,
            **suppress_diagnostics,
        }

    if not candidate_records:
        artifact.retained_pairs = 0
        return artifact

    candidate_records.sort(key=lambda record: record.get("pair_score", 0.0), reverse=True)
    selected_records = candidate_records
    selection_diagnostics = {
        "strategy": "complete_measurement_population",
        "configured_top_n": int(top_n),
        "top_n_cap_applied": False,
        "max_pairs_per_document": int(max_pairs_per_document),
        "max_pairs_per_document_pair": int(max_pairs_per_document_pair),
    }
    artifact.coverage = {
        **artifact.coverage,
        "top_pair_selection": selection_diagnostics,
    }
    sanitized_top = [_sanitize_pair(record, df, coverage) for record in selected_records]
    artifact.top_pairs = sanitized_top
    artifact.retained_pairs = len(sanitized_top)
    return artifact


# ── Pair context ───────────────────────────────────────────────


def _select_large_input_candidate_frame(
    df: pd.DataFrame,
    *,
    max_rows: int,
    candidate_scores: pd.Series | None,
    candidate_details: pd.DataFrame | None,
    candidate_supplement_strategy: str = "none",
    candidate_supplement_max_docs: int = 0,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """Return bounded row-score candidate frame for large-input pair evidence.

    This does not convert row hits into cases. It only narrows expensive pair
    generation to rows where the duplicate detector already found nonzero review
    candidate scores, then the normal pair builders must still produce left/right
    evidence.
    """
    strength = pd.Series(0.0, index=df.index, dtype=float)
    if candidate_scores is not None:
        strength = strength.combine(
            pd.to_numeric(candidate_scores.reindex(df.index), errors="coerce").fillna(0.0),
            max,
        )
    if candidate_details is not None and not candidate_details.empty:
        aligned = candidate_details.reindex(df.index)
        numeric = aligned.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        if not numeric.empty:
            strength = strength.combine(numeric.max(axis=1), max)

    hit_strength = strength[strength > 0]
    coverage = {
        "large_input_candidate_mode": "row_score_subset",
        "row_score_hit_count": int(len(hit_strength)),
        "selected_candidate_rows": 0,
        "dropped_candidate_rows_for_artifact_cap": 0,
        "candidate_supplement_strategy": str(candidate_supplement_strategy or "none"),
        "candidate_supplement_selected_rows": 0,
        "candidate_supplement_selected_docs": 0,
    }
    if hit_strength.empty:
        coverage["large_input_candidate_mode"] = "unavailable"
        return None, coverage

    first_positions: dict[Any, int] = {}
    for pos, label in enumerate(df.index):
        first_positions.setdefault(label, pos)
    selector = pd.DataFrame(
        {
            "_strength": hit_strength.astype(float),
            "_pos": [first_positions.get(label, 0) for label in hit_strength.index],
        },
        index=hit_strength.index,
    )
    selector = selector.sort_values(
        ["_strength", "_pos"],
        ascending=[False, True],
        kind="mergesort",
    )
    supplement_positions: list[int] = []
    if candidate_supplement_strategy == "observable_profile" and candidate_supplement_max_docs > 0:
        supplement_positions, supplement_docs = _observable_profile_supplement_positions(
            df,
            max_docs=candidate_supplement_max_docs,
        )
        coverage["candidate_supplement_selected_rows"] = int(len(supplement_positions))
        coverage["candidate_supplement_selected_docs"] = int(supplement_docs)

    if len(selector) > max_rows:
        reserved_rows = min(len(supplement_positions), max_rows)
        score_budget = max(max_rows - reserved_rows, 0)
        coverage["dropped_candidate_rows_for_artifact_cap"] = int(len(selector) - score_budget)
        selector = selector.head(score_budget)
    selected_positions = list(selector["_pos"].to_numpy(dtype=int))
    if supplement_positions:
        selected_position_set = set(selected_positions)
        for position in supplement_positions:
            if position in selected_position_set:
                continue
            selected_positions.append(position)
            selected_position_set.add(position)
            if len(selected_positions) >= max_rows:
                break
    coverage["selected_score_candidate_rows"] = int(len(selector))
    coverage["selected_candidate_rows"] = int(len(selected_positions))
    coverage["selected_candidate_rows_with_supplement"] = int(len(selected_positions))
    coverage["skipped_for_size"] = False
    coverage["bounded_from_large_input"] = True
    return df.iloc[np.asarray(selected_positions, dtype=int)], coverage


def _observable_profile_supplement_positions(
    df: pd.DataFrame,
    *,
    max_docs: int,
) -> tuple[list[int], int]:
    """Return bounded row positions for duplicate-shaped document evidence.

    Selector inputs are GL-observable fields only: document row count, P2P
    process, reference presence, partner presence, and document amount profile.
    The helper does not read truth labels, owner metadata, PHASE1 rank, or
    matched results. It only gives lower-score duplicate-like documents a small
    route into pair generation on large inputs.
    """
    required = {"document_id", "debit_amount", "credit_amount"}
    if max_docs <= 0 or not required.issubset(df.columns):
        return [], 0

    work = pd.DataFrame(index=df.index)
    work["_pos"] = np.arange(len(df), dtype=np.int64)
    work["document_id"] = df["document_id"].astype("string")
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0).abs()
    work["_abs_amount"] = debit + credit
    work["_has_reference"] = (
        df["reference"].fillna("").astype(str).str.len() > 0
        if "reference" in df.columns
        else False
    )
    work["_has_partner"] = (
        df["trading_partner"].fillna("").astype(str).str.len() > 0
        if "trading_partner" in df.columns
        else False
    )
    process = (
        df["business_process"].fillna("").astype(str).str.upper()
        if "business_process" in df.columns
        else pd.Series("", index=df.index)
    )
    work["_is_p2p"] = process.eq("P2P")
    grouped = work.groupby("document_id", sort=False, dropna=True).agg(
        row_count=("_pos", "size"),
        max_amount=("_abs_amount", "max"),
        total_amount=("_abs_amount", "sum"),
        has_reference=("_has_reference", "max"),
        has_partner=("_has_partner", "max"),
        is_p2p=("_is_p2p", "max"),
    )
    eligible = grouped[
        grouped["is_p2p"]
        & grouped["has_reference"]
        & grouped["has_partner"]
        & grouped["row_count"].between(2, 3)
    ].copy()
    if eligible.empty:
        return [], 0

    eligible["doc_score"] = (
        eligible["max_amount"].rank(method="first", pct=True)
        + eligible["total_amount"].rank(method="first", pct=True)
        + eligible["has_reference"].astype(float)
        + eligible["has_partner"].astype(float)
        + eligible["is_p2p"].astype(float)
        + eligible["row_count"].between(2, 3).astype(float)
    )
    selected_docs = set(
        eligible.sort_values(
            ["doc_score", "max_amount", "total_amount"],
            ascending=[False, False, False],
            kind="mergesort",
        )
        .head(max_docs)
        .index.astype(str)
    )
    if not selected_docs:
        return [], 0

    selected = work[work["document_id"].astype(str).isin(selected_docs)].copy()
    selected["_doc_pos"] = selected.groupby("document_id").cumcount()
    positions = selected.loc[selected["_doc_pos"] < 3, "_pos"].astype(int).tolist()
    return positions, len(selected_docs)


def _suppress_recurring_duplicate_records(
    records: list[dict[str, Any]],
    context: _PairContext,
    settings: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    min_len = max(int(getattr(settings, "duplicate_recurring_min_series_length", 3)), 3)
    min_interval = max(int(getattr(settings, "duplicate_recurring_min_interval_days", 21)), 1)
    max_interval = max(
        int(getattr(settings, "duplicate_recurring_max_interval_days", 100)),
        min_interval,
    )
    cv_threshold = max(
        float(getattr(settings, "duplicate_recurring_interval_cv_threshold", 0.20)),
        0.0,
    )
    near_ratio = max(float(getattr(settings, "duplicate_recurring_near_extra_ratio", 0.50)), 0.0)
    amount_band_ratio = max(
        float(getattr(settings, "duplicate_recurring_amount_band_ratio", 0.01)),
        0.0,
    )
    amount_band_min = max(
        float(getattr(settings, "duplicate_recurring_amount_band_min", 1000.0)),
        1.0,
    )
    near_extra_allowed_sources = _normalized_config_values(
        getattr(
            settings,
            "duplicate_recurring_near_extra_allowed_sources",
            ["manual", "adjustment"],
        )
    )
    near_extra_suppressed_sources = _normalized_config_values(
        getattr(
            settings,
            "duplicate_recurring_near_extra_suppressed_sources",
            ["automated", "auto", "recurring", "batch", "interface", "system"],
        )
    )
    near_extra_suppressed_processes = _normalized_config_values(
        getattr(
            settings,
            "duplicate_recurring_near_extra_suppressed_processes",
            ["R2R", "Intercompany"],
        )
    )
    near_extra_suppressed_process_tokens = _normalized_config_values(
        getattr(
            settings,
            "duplicate_recurring_near_extra_suppressed_process_tokens",
            ["closing", "close", "accrual", "period_end", "period end", "month_end", "month end"],
        )
    )

    profiles = _recurring_group_profiles(
        context,
        min_len=min_len,
        min_interval=min_interval,
        max_interval=max_interval,
        cv_threshold=cv_threshold,
        amount_band_ratio=amount_band_ratio,
        amount_band_min=amount_band_min,
    )
    kept: list[dict[str, Any]] = []
    suppressed = 0
    same_reference_kept = 0
    near_extra_kept = 0
    near_extra_context_suppressed = 0
    ambiguous_dropped = 0
    for record in records:
        features = dict(record.get("features", {}))
        left_pos = int(record["left_pos"])
        right_pos = int(record["right_pos"])
        if _same_reference_or_document_number(context, left_pos, right_pos):
            features["same_reference"] = True
            features["recurring_suppress_decision"] = "same_reference_kept"
            record["features"] = features
            kept.append(record)
            same_reference_kept += 1
            continue
        features["same_reference"] = False
        profile = profiles.get(
            _recurring_group_key(context, left_pos, amount_band_ratio, amount_band_min)
        )
        day_diff = _date_distance_days(context.dates.iat[left_pos], context.dates.iat[right_pos])
        if profile is not None and day_diff is not None:
            near_threshold = max(1.0, float(profile["median_interval_days"]) * near_ratio)
            if day_diff <= near_threshold:
                features["recurring_series_median_interval_days"] = float(
                    profile["median_interval_days"]
                )
                if _near_extra_is_manual_off_cycle(
                    context,
                    left_pos,
                    right_pos,
                    allowed_sources=near_extra_allowed_sources,
                    suppressed_sources=near_extra_suppressed_sources,
                    suppressed_processes=near_extra_suppressed_processes,
                    suppressed_process_tokens=near_extra_suppressed_process_tokens,
                ):
                    features["recurring_suppress_decision"] = "near_extra_kept"
                    record["features"] = features
                    kept.append(record)
                    near_extra_kept += 1
                    continue
                features["recurring_suppress_decision"] = "near_extra_context_suppressed"
                record["features"] = features
                near_extra_context_suppressed += 1
                continue
            features["recurring_suppress_decision"] = "periodic_series_suppressed"
            suppressed += 1
            continue
        features["recurring_suppress_decision"] = "ambiguous_different_reference_dropped"
        ambiguous_dropped += 1

    return kept, {
        "recurring_suppressed_pairs": int(suppressed),
        "recurring_same_reference_kept_pairs": int(same_reference_kept),
        "recurring_near_extra_kept_pairs": int(near_extra_kept),
        "recurring_near_extra_context_suppressed_pairs": int(near_extra_context_suppressed),
        "recurring_ambiguous_dropped_pairs": int(ambiguous_dropped),
        "recurring_profile_group_count": int(len(profiles)),
    }


def _normalized_config_values(values: Any) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = list(values)
    return {_normalize_text(str(value)) for value in raw_values if _normalize_text(str(value))}


def _near_extra_is_manual_off_cycle(
    context: _PairContext,
    left_pos: int,
    right_pos: int,
    *,
    allowed_sources: set[str],
    suppressed_sources: set[str],
    suppressed_processes: set[str],
    suppressed_process_tokens: set[str],
) -> bool:
    source_values = _pair_column_values(context, "source", left_pos, right_pos)
    normalized_sources = {_normalize_text(value) for value in source_values if value}
    if normalized_sources & suppressed_sources:
        return False
    if allowed_sources and not normalized_sources:
        return False
    if allowed_sources and not normalized_sources.issubset(allowed_sources):
        return False

    process_values = _pair_column_values(context, "business_process", left_pos, right_pos)
    normalized_processes = {_normalize_text(value) for value in process_values if value}
    if normalized_processes & suppressed_processes:
        return False

    text_values: list[str] = []
    for column in (
        "business_process",
        "line_text",
        "source",
        "document_type",
        "scenario_id",
        "event_type",
    ):
        text_values.extend(_pair_column_values(context, column, left_pos, right_pos))
    context_text = " ".join(text_values)
    normalized_context = _normalize_text(context_text)
    return not any(token in normalized_context for token in suppressed_process_tokens)


def _pair_column_values(
    context: _PairContext,
    column: str,
    left_pos: int,
    right_pos: int,
) -> list[str]:
    if column not in context.df.columns:
        return []
    return [
        "" if pd.isna(value) else str(value)
        for value in (context.df[column].iat[left_pos], context.df[column].iat[right_pos])
    ]


def _recurring_group_profiles(
    context: _PairContext,
    *,
    min_len: int,
    min_interval: int,
    max_interval: int,
    cv_threshold: float,
    amount_band_ratio: float,
    amount_band_min: float,
) -> dict[tuple[str, str, int], dict[str, float]]:
    work = pd.DataFrame(
        {
            "key": [
                _recurring_group_key(context, pos, amount_band_ratio, amount_band_min)
                for pos in range(len(context.df))
            ],
            "date": context.dates,
        },
        index=context.df.index,
    ).dropna(subset=["date"])
    profiles: dict[tuple[str, str, int], dict[str, float]] = {}
    for key, group in work.groupby("key", sort=False):
        if len(group) < min_len:
            continue
        dates = pd.to_datetime(group["date"], errors="coerce").dropna().sort_values()
        if len(dates) < min_len:
            continue
        intervals = dates.diff().dropna().dt.days.astype(float)
        intervals = intervals[intervals > 0]
        regular_intervals = intervals[intervals >= min_interval]
        if len(regular_intervals) < max(min_len - 2, 1):
            continue
        median = float(regular_intervals.median())
        if median < min_interval or median > max_interval:
            continue
        cv = float(regular_intervals.std(ddof=0) / median) if median > 0 else float("inf")
        if cv <= cv_threshold:
            profiles[key] = {
                "median_interval_days": median,
                "interval_cv": cv,
                "series_length": float(len(dates)),
            }
    return profiles


def _recurring_group_key(
    context: _PairContext,
    pos: int,
    amount_band_ratio: float,
    amount_band_min: float,
) -> tuple[str, str, int]:
    partner = ""
    if context.partner is not None:
        value = context.partner.iat[pos]
        partner = "" if pd.isna(value) else str(value).strip()
    gl_value = context.gl.iat[pos]
    gl = "" if pd.isna(gl_value) else str(gl_value).strip()
    amount = abs(float(context.amount.iat[pos] or 0.0))
    band_size = max(amount * amount_band_ratio, amount_band_min)
    amount_band = int(round(amount / band_size)) if band_size > 0 else int(round(amount))
    return (partner, gl, amount_band)


def _same_reference_or_document_number(
    context: _PairContext,
    left_pos: int,
    right_pos: int,
) -> bool:
    for column in ("reference", "document_number"):
        if column not in context.df.columns:
            continue
        left = _safe_str(context.df[column].iat[left_pos])
        right = _safe_str(context.df[column].iat[right_pos])
        if left and right and left == right:
            return True
    return False


def _select_diverse_top_records(
    records: list[dict[str, Any]],
    df: pd.DataFrame,
    *,
    top_n: int,
    max_pairs_per_document: int,
    max_pairs_per_document_pair: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select metadata top records while preventing repeated document monopolies.

    Candidate generation and scoring are unchanged. This only bounds the retained
    metadata artifact so a dense routine repeated document group cannot consume
    the whole auditor review surface.
    """
    if top_n <= 0 or not records:
        return [], {
            "strategy": "document_diversity",
            "max_pairs_per_document": int(max_pairs_per_document),
            "max_pairs_per_document_pair": int(max_pairs_per_document_pair),
            "selected_by_diversity": 0,
            "selected_by_fill": 0,
        }

    if max_pairs_per_document == 0 and max_pairs_per_document_pair == 0:
        selected = records[:top_n]
        return selected, {
            "strategy": "score_only",
            "max_pairs_per_document": 0,
            "max_pairs_per_document_pair": 0,
            "selected_by_diversity": 0,
            "selected_by_fill": len(selected),
        }

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    doc_counts: Counter[Any] = Counter()
    doc_pair_counts: Counter[tuple[Any, Any]] = Counter()

    for record in records:
        if len(selected) >= top_n:
            break
        left_key, right_key = _record_document_keys(record, df)
        pair_key = tuple(sorted((left_key, right_key), key=lambda value: str(value)))
        if max_pairs_per_document_pair and doc_pair_counts[pair_key] >= max_pairs_per_document_pair:
            continue
        if max_pairs_per_document and (
            doc_counts[left_key] >= max_pairs_per_document
            or doc_counts[right_key] >= max_pairs_per_document
        ):
            continue
        selected.append(record)
        selected_ids.add(id(record))
        doc_counts[left_key] += 1
        doc_counts[right_key] += 1
        doc_pair_counts[pair_key] += 1

    selected_by_diversity = len(selected)
    if len(selected) < top_n:
        for record in records:
            if len(selected) >= top_n:
                break
            if id(record) in selected_ids:
                continue
            selected.append(record)
            selected_ids.add(id(record))

    return selected, {
        "strategy": "document_diversity",
        "max_pairs_per_document": int(max_pairs_per_document),
        "max_pairs_per_document_pair": int(max_pairs_per_document_pair),
        "selected_by_diversity": int(selected_by_diversity),
        "selected_by_fill": int(len(selected) - selected_by_diversity),
        "unique_document_keys_in_diverse_selection": int(len(doc_counts)),
        "unique_document_pair_keys_in_diverse_selection": int(len(doc_pair_counts)),
    }


def _select_top_pairs_with_evidence_diversity(
    records: list[dict[str, Any]],
    df: pd.DataFrame,
    *,
    top_n: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select review candidate pair evidence with audit-observable diversity.

    The ordering uses only generated pair evidence: pair score, evidence tier,
    same-partner/reference/text support, and repeated document/document-pair
    concentration. It does not read truth labels, scenarios, thresholds, PHASE1
    priority, or PHASE2 family fusion. Weak pairs are not promoted; they are
    ranked behind strong/moderate evidence units when comparable evidence exists.
    """
    if top_n <= 0 or not records:
        return [], {
            "strategy": "evidence_diversity",
            "selected_by_evidence_diversity": 0,
            "truth_label_used": False,
        }

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    doc_counts: Counter[Any] = Counter()
    doc_pair_counts: Counter[tuple[Any, Any]] = Counter()
    pool_size = min(len(records), max(top_n * 100, 50_000))
    remaining = list(enumerate(records[:pool_size]))
    while remaining and len(selected) < top_n:
        best_pos = 0
        best_key: tuple[float, float, float] | None = None
        for pos, (idx, record) in enumerate(remaining):
            left_key, right_key = _record_document_keys(record, df)
            pair_key = tuple(sorted((left_key, right_key), key=lambda value: str(value)))
            novelty = int(doc_counts[left_key] == 0) + int(doc_counts[right_key] == 0)
            repeat_penalty = doc_counts[left_key] + doc_counts[right_key] + (
                doc_pair_counts[pair_key] * 2
            )
            score = (
                float(record.get("pair_score") or 0.0)
                + 0.05 * _record_evidence_similarity_score(record)
                + 0.03 * novelty
                - 0.01 * repeat_penalty
                - (0.10 if _pair_evidence_tier_weight(record) <= 1 else 0.0)
            )
            key = (score, -float(idx), -float(pos))
            if best_key is None or key > best_key:
                best_key = key
                best_pos = pos

        _idx, record = remaining.pop(best_pos)
        if id(record) in selected_ids:
            continue
        selected.append(record)
        selected_ids.add(id(record))
        left_key, right_key = _record_document_keys(record, df)
        pair_key = tuple(sorted((left_key, right_key), key=lambda value: str(value)))
        doc_counts[left_key] += 1
        doc_counts[right_key] += 1
        doc_pair_counts[pair_key] += 1

    if len(selected) < top_n:
        for record in records[pool_size:]:
            if len(selected) >= top_n:
                break
            if id(record) in selected_ids:
                continue
            selected.append(record)
            selected_ids.add(id(record))

    weak_count = sum(1 for record in selected if _pair_evidence_tier_weight(record) <= 1)
    return selected, {
        "strategy": "evidence_diversity",
        "selected_by_evidence_diversity": int(len(selected)),
        "truth_label_used": False,
        "weak_pair_count": int(weak_count),
        "unique_document_keys_in_selection": int(len(doc_counts)),
        "unique_document_pair_keys_in_selection": int(len(doc_pair_counts)),
    }


def _select_top_pairs_with_rule_balanced_evidence(
    records: list[dict[str, Any]],
    df: pd.DataFrame,
    *,
    top_n: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select top pairs while preserving observable duplicate sub-rule lanes.

    Score-only pair ranking lets abundant exact pairs monopolize the metadata
    artifact. This selector gives each generated L2-03 sub-rule a bounded pass,
    prioritizing case-grade evidence inside each rule, then fills the remaining
    budget with the evidence-diversity selector. It does not read truth labels,
    scenarios, owner metadata, PHASE1 rank, or matched results.
    """
    if top_n <= 0 or not records:
        return [], {
            "strategy": "rule_balanced_evidence",
            "truth_label_used": False,
            "selected_by_rule_balance": 0,
            "selected_by_fill": 0,
        }

    by_rule: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_rule.setdefault(str(record.get("rule_id") or ""), []).append(record)

    active_rules = [
        rule
        for rule in (_RULE_EXACT, _RULE_FUZZY, _RULE_SPLIT, _RULE_TIMESHIFT, _RULE_PROFILE)
        if by_rule.get(rule)
    ]
    if not active_rules:
        return _select_top_pairs_with_evidence_diversity(records, df, top_n=top_n)

    quota = max(top_n // len(active_rules), 1)
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    selected_by_rule: dict[str, int] = {}
    for rule in active_rules:
        ordered = sorted(by_rule[rule], key=_rule_balanced_record_key, reverse=True)
        take = min(quota, len(ordered), top_n - len(selected))
        if take <= 0:
            break
        for record in ordered[:take]:
            selected.append(record)
            selected_ids.add(id(record))
        selected_by_rule[rule] = int(take)

    selected_by_rule_balance = len(selected)
    if len(selected) < top_n:
        remaining = [record for record in records if id(record) not in selected_ids]
        fill, _diagnostics = _select_top_pairs_with_evidence_diversity(
            remaining,
            df,
            top_n=top_n - len(selected),
        )
        selected.extend(fill)
        selected_ids.update(id(record) for record in fill)

    weak_count = sum(1 for record in selected if _pair_evidence_tier_weight(record) <= 1)
    return selected[:top_n], {
        "strategy": "rule_balanced_evidence",
        "truth_label_used": False,
        "selected_by_rule_balance": int(selected_by_rule_balance),
        "selected_by_fill": int(max(len(selected[:top_n]) - selected_by_rule_balance, 0)),
        "selected_by_rule": selected_by_rule,
        "weak_pair_count": int(weak_count),
        "active_rules": active_rules,
    }


def _rule_balanced_record_key(record: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(_pair_evidence_tier_weight(record)),
        float(_record_evidence_similarity_score(record)),
        float(record.get("pair_score") or 0.0),
        -float(_as_float(record.get("left_pos"))),
    )


def _pair_evidence_tier_weight(record: dict[str, Any]) -> int:
    features = record.get("features")
    tier = classify_pair_evidence_tier(features if isinstance(features, dict) else None)
    return pair_tier_weight(tier)


def _record_evidence_similarity_score(record: dict[str, Any]) -> float:
    features = record.get("features")
    if not isinstance(features, dict):
        return 0.0
    ref = _as_float(features.get("reference_similarity"))
    text = _as_float(features.get("text_similarity"))
    partner = 1.0 if features.get("same_partner") is True else 0.0
    return float(0.4 * ref + 0.3 * text + 0.3 * partner)


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if num != num:
        return 0.0
    return num


def _record_document_keys(record: dict[str, Any], df: pd.DataFrame) -> tuple[Any, Any]:
    left_pos = int(record["left_pos"])
    right_pos = int(record["right_pos"])
    if "document_id" in df.columns:
        left_doc = _safe_str(df["document_id"].iat[left_pos])
        right_doc = _safe_str(df["document_id"].iat[right_pos])
        if left_doc is not None and right_doc is not None:
            return left_doc, right_doc
    return _json_safe(df.index[left_pos]), _json_safe(df.index[right_pos])


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
        self._repeat_key_counts = self._build_repeat_key_counts()
        self._same_day_key_counts = self._build_same_day_key_counts()
        self.max_group_size = max_group_size
        self.max_pairs_per_row = max_pairs_per_row
        self.max_total_pairs = max_total_pairs
        self.total_pairs = 0
        self.truncated = False
        self.truncation_reason: str | None = None
        # per-row counter via numpy array for speed.
        self._row_counts = np.zeros(len(df), dtype=np.int32)
        self._index = df.index

    def _repeat_key(self, pos: int) -> tuple[str, float, str]:
        partner = ""
        if self.partner is not None:
            value = self.partner.iat[pos]
            partner = "" if pd.isna(value) else str(value).strip()
        gl_value = self.gl.iat[pos]
        gl = "" if pd.isna(gl_value) else str(gl_value).strip()
        return (gl, round(float(self.amount.iat[pos]), 2), partner)

    def _same_day_key(self, pos: int) -> tuple[str, float, str]:
        date_value = self.dates.iat[pos]
        date_text = "" if pd.isna(date_value) else str(pd.Timestamp(date_value).date())
        gl_value = self.gl.iat[pos]
        gl = "" if pd.isna(gl_value) else str(gl_value).strip()
        return (gl, round(float(self.amount.iat[pos]), 2), date_text)

    def _build_repeat_key_counts(self) -> Counter[tuple[str, float, str]]:
        counts: Counter[tuple[str, float, str]] = Counter()
        for pos in range(len(self.df)):
            counts[self._repeat_key(pos)] += 1
        return counts

    def _build_same_day_key_counts(self) -> Counter[tuple[str, float, str]]:
        counts: Counter[tuple[str, float, str]] = Counter()
        for pos in range(len(self.df)):
            counts[self._same_day_key(pos)] += 1
        return counts

    def repeat_group_size(self, pos: int) -> int:
        return int(self._repeat_key_counts[self._repeat_key(pos)])

    def same_day_burst_size(self, pos: int) -> int:
        return int(self._same_day_key_counts[self._same_day_key(pos)])

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
        if self.same_document_pair(left_pos, right_pos):
            return None
        if self.known_flow_link_pair(left_pos, right_pos):
            return None
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

    def same_document_pair(self, left_pos: int, right_pos: int) -> bool:
        if self.document_id is None:
            return False
        left = self.document_id.iat[left_pos]
        right = self.document_id.iat[right_pos]
        if pd.isna(left) or pd.isna(right):
            return False
        left_text = str(left).strip()
        right_text = str(right).strip()
        return bool(left_text and right_text and left_text == right_text)

    def known_flow_link_pair(self, left_pos: int, right_pos: int) -> bool:
        """Return true for pairs that are explicit non-duplicate flow links."""

        left_doc = self._document_id_at(left_pos)
        right_doc = self._document_id_at(right_pos)
        if not left_doc or not right_doc:
            return False
        if self._structural_reversal_link(left_pos, right_pos, left_doc, right_doc):
            return True
        return self._invoice_payment_cross_role_link(left_pos, right_pos)

    def _document_id_at(self, pos: int) -> str:
        if self.document_id is None:
            return ""
        value = self.document_id.iat[pos]
        if pd.isna(value):
            return ""
        return str(value).strip()

    def _structural_reversal_link(
        self,
        left_pos: int,
        right_pos: int,
        left_doc: str,
        right_doc: str,
    ) -> bool:
        for column in ("reversal_document_id", "original_document_id"):
            if column not in self.df.columns:
                continue
            left_link = _safe_str(self.df[column].iat[left_pos])
            right_link = _safe_str(self.df[column].iat[right_pos])
            if left_link == right_doc or right_link == left_doc:
                return True
        return False

    def _invoice_payment_cross_role_link(self, left_pos: int, right_pos: int) -> bool:
        if "document_type" not in self.df.columns:
            return False
        if not _same_reference_or_document_number(self, left_pos, right_pos):
            return False
        left_type = _normalize_text(_safe_str(self.df["document_type"].iat[left_pos]) or "")
        right_type = _normalize_text(_safe_str(self.df["document_type"].iat[right_pos]) or "")
        invoice_types = {"kr", "dr", "re", "invoice", "vendorinvoice", "customerinvoice"}
        payment_types = {"kz", "dz", "bk", "tr", "payment", "receipt", "bank"}
        return (left_type in invoice_types and right_type in payment_types) or (
            right_type in invoice_types and left_type in payment_types
        )


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


# ── L2-03e: document-profile duplicate pairs ──────────────────


def _document_profile_pairs(
    context: _PairContext,
    *,
    window_days: int,
    amount_tolerance: float,
) -> list[dict[str, Any]]:
    """Build document-level duplicate pair evidence from observable GL fields.

    This complements row-level L2-03a~d for large inputs where the duplicate
    shape is primarily document-to-document: same partner/process, close posting
    dates, similar reference, similar document amount, and 2-3 row support.
    """
    df = context.df
    required = {"document_id", "business_process", "trading_partner", "reference"}
    if not required.issubset(df.columns):
        return []

    work = pd.DataFrame(
        {
            "document_id": df["document_id"].astype("string"),
            "business_process": df["business_process"].fillna("").astype(str),
            "trading_partner": df["trading_partner"].fillna("").astype(str),
            "reference": df["reference"].fillna("").astype(str),
            "posting_date": context.dates,
            "amount": context.amount,
            "_pos": np.arange(len(df), dtype=np.int64),
        },
        index=df.index,
    )
    if work.empty:
        return []

    def _first_nonempty(values: pd.Series) -> str:
        cleaned = values.dropna().astype(str)
        cleaned = cleaned[cleaned.str.len() > 0]
        return "" if cleaned.empty else str(cleaned.iat[0])

    docs = work.groupby("document_id", sort=False, dropna=True).agg(
        row_count=("_pos", "size"),
        first_pos=("_pos", "first"),
        max_amount=("amount", "max"),
        posting_date=("posting_date", "min"),
        reference=("reference", _first_nonempty),
        trading_partner=("trading_partner", _first_nonempty),
        business_process=("business_process", _first_nonempty),
    )
    eligible = docs[
        docs["row_count"].between(2, 3)
        & docs["business_process"].astype(str).str.upper().eq("P2P")
        & docs["trading_partner"].astype(str).str.len().gt(0)
        & docs["reference"].astype(str).str.len().gt(0)
        & docs["posting_date"].notna()
        & docs["max_amount"].gt(0)
    ].copy()
    if eligible.empty:
        return []

    tolerance = max(float(amount_tolerance), 0.0)
    records: list[dict[str, Any]] = []
    for _key, group in eligible.groupby(["trading_partner", "business_process"], sort=False):
        if context.exhausted:
            return records
        if len(group) < 2:
            continue
        ordered = group.sort_values("posting_date", kind="mergesort")
        rows = list(
            ordered[
                ["first_pos", "max_amount", "posting_date", "reference"]
            ].itertuples(index=False, name=None)
        )
        n = len(rows)
        for left_idx, (left_pos, left_amount, left_date, left_ref) in enumerate(rows):
            if context.exhausted:
                return records
            for right_pos, right_amount, right_date, right_ref in rows[
                left_idx + 1 : min(n, left_idx + 200)
            ]:
                if context.exhausted:
                    return records
                day_diff = int((right_date - left_date).days)
                if day_diff > window_days:
                    break
                if day_diff < 1:
                    continue
                amount_similarity = float(
                    max(0.0, 1.0 - _amount_diff_ratio(float(left_amount), float(right_amount)))
                )
                if amount_similarity < 1.0 - tolerance:
                    continue
                reference_similarity = float(
                    fuzz.token_sort_ratio(str(left_ref), str(right_ref)) / 100.0
                )
                if reference_similarity < 0.70:
                    continue
                date_similarity = float(max(0.0, 1.0 - day_diff / max(window_days, 1)))
                features = _common_features(
                    context,
                    left_pos=int(left_pos),
                    right_pos=int(right_pos),
                    amount_left=float(left_amount),
                    amount_right=float(right_amount),
                )
                features["same_partner"] = True
                features["amount_similarity"] = amount_similarity
                features["reference_similarity"] = reference_similarity
                features["date_similarity"] = date_similarity
                features["date_distance_days"] = day_diff
                score = float(
                    0.50 * reference_similarity
                    + 0.35 * amount_similarity
                    + 0.15 * date_similarity
                )
                record = context.try_add(
                    left_pos=int(left_pos),
                    right_pos=int(right_pos),
                    score=score,
                    rule_id=_RULE_PROFILE,
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
    same_reference = _same_reference_or_document_number(context, left_pos, right_pos)
    same_account = (
        bool(context.gl.iat[left_pos] == context.gl.iat[right_pos])
        if not (pd.isna(context.gl.iat[left_pos]) or pd.isna(context.gl.iat[right_pos]))
        else False
    )
    left_period_end_distance = _days_to_month_end(context.dates.iat[left_pos])
    right_period_end_distance = _days_to_month_end(context.dates.iat[right_pos])
    period_distances = [
        value
        for value in (left_period_end_distance, right_period_end_distance)
        if value is not None
    ]
    min_period_end_distance = min(period_distances) if period_distances else None
    left_repeat_size = context.repeat_group_size(left_pos)
    right_repeat_size = context.repeat_group_size(right_pos)
    left_burst_size = context.same_day_burst_size(left_pos)
    right_burst_size = context.same_day_burst_size(right_pos)
    return {
        "amount_diff_ratio": float(diff_ratio),
        "date_distance_days": date_distance,
        "same_account": same_account,
        "same_partner": same_partner,
        "same_reference": same_reference,
        "reference_similarity": reference_similarity,
        "min_period_end_distance_days": min_period_end_distance,
        "both_period_end_window_3d": (
            left_period_end_distance is not None
            and right_period_end_distance is not None
            and left_period_end_distance <= 3
            and right_period_end_distance <= 3
        ),
        "repeat_key_group_size_max": int(max(left_repeat_size, right_repeat_size)),
        "same_day_burst_group_size_max": int(max(left_burst_size, right_burst_size)),
        "routine_repeat_candidate": bool(max(left_repeat_size, right_repeat_size) >= 12),
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


def _days_to_month_end(value: Any) -> int | None:
    if pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    month_end = timestamp + pd.offsets.MonthEnd(0)
    return int((month_end.normalize() - timestamp.normalize()).days)


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
