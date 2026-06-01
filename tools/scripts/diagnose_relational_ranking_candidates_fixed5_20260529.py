"""Compare diagnostic-only relational ranking candidates for fixed5.

This script does not change PHASE2 production gate, family fusion, or PHASE1
ranking. It rebuilds relational native edge review candidates and evaluates
alternative top-surface orderings as aggregate diagnostics only.

Raw document IDs and raw edge identifiers stay in memory and are not emitted.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import math
import pickle
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.phase2_case import RelationalCase
from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from src.services.phase2_family_policy import (
    RELATIONAL_PRIMARY_DENOMINATOR_STATUS,
    RELATIONAL_PRODUCT_ROLE,
    build_relational_policy_summary,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID,
    CASE_INPUT_PKL,
    DATASET_NAME,
    _case_documents,
    _load_case_input,
    _load_truth,
    _run_rule_detector,
    _sorted_cases,
)

OUT_JSON = ROOT / "artifacts" / "relational_ranking_candidates_fixed5_20260529.json"
FIXED4_DATASET_NAME = "datasynth_manipulation_v7_candidate_fixed4"
FIXED4_CASE_INPUT_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl"
FIXED4_TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / FIXED4_DATASET_NAME
    / "labels"
    / "manipulated_entry_truth.csv"
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _numeric_distribution(values: list[float | int]) -> dict[str, Any]:
    clean = [float(value) for value in values if np.isfinite(float(value))]
    if not clean:
        return {"count": 0, "min": None, "p50": None, "p90": None, "p95": None, "max": None}
    arr = np.asarray(clean, dtype=float)
    return {
        "count": int(len(arr)),
        "min": float(arr.min()),
        "p50": float(np.quantile(arr, 0.50)),
        "p90": float(np.quantile(arr, 0.90)),
        "p95": float(np.quantile(arr, 0.95)),
        "max": float(arr.max()),
    }


def _concentration(values: list[str]) -> dict[str, Any]:
    counts = Counter(value for value in values if value)
    total = sum(counts.values())
    if total == 0:
        return {
            "count": 0,
            "unique_count": 0,
            "top1_count": 0,
            "top5_count": 0,
            "top10_count": 0,
            "top1_share": 0.0,
            "top5_share": 0.0,
            "top10_share": 0.0,
            "hhi": 0.0,
        }
    top = counts.most_common(10)
    hhi = sum((count / total) ** 2 for count in counts.values())
    return {
        "count": int(total),
        "unique_count": len(counts),
        "top1_count": int(top[0][1]) if top else 0,
        "top5_count": int(sum(count for _value, count in top[:5])),
        "top10_count": int(sum(count for _value, count in top[:10])),
        "top1_share": (top[0][1] / total) if top else 0.0,
        "top5_share": sum(count for _value, count in top[:5]) / total,
        "top10_share": sum(count for _value, count in top[:10]) / total,
        "hhi": float(hhi),
    }


FORBIDDEN_IDENTIFIER_KEYS = {
    "document_id",
    "document_ids",
    "raw_document_id",
    "raw_document_ids",
    "row_id",
    "row_ids",
    "raw_row_id",
    "raw_row_ids",
    "index_label",
    "raw_index_label",
    "edge_a",
    "edge_b",
    "raw_edge_a",
    "raw_edge_b",
    "phase2_case_id",
    "phase2_case_ids",
}


def _account_class(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return "blank"
    first = value[0]
    if first.isdigit():
        return f"class_{first}xxx"
    return "non_numeric"


def _age_bucket(days: float | int | None) -> str:
    if days is None or not np.isfinite(float(days)):
        return "unknown"
    value = float(days)
    if value <= 7:
        return "0_7"
    if value <= 30:
        return "8_30"
    if value <= 90:
        return "31_90"
    if value <= 180:
        return "91_180"
    return "181_plus"


def _gap_bucket(days: float | int | None) -> str:
    if days is None or not np.isfinite(float(days)):
        return "unknown"
    value = float(days)
    if value <= 180:
        return "0_180"
    if value <= 365:
        return "181_365"
    if value <= 730:
        return "366_730"
    return "731_plus"


def _context_series(df: pd.DataFrame | None) -> dict[str, pd.Series]:
    if df is None or df.empty:
        return {}
    out: dict[str, pd.Series] = {}
    if {"trading_partner", "posting_date"}.issubset(df.columns):
        posting = pd.to_datetime(df["posting_date"], errors="coerce")
        partner = df["trading_partner"].fillna("").astype(str)
        first_seen = posting.groupby(partner).transform("min")
        out["days_since_partner_first_seen"] = (posting - first_seen).dt.days
    if {"gl_account", "posting_date"}.issubset(df.columns):
        work = df[["gl_account", "posting_date"]].copy()
        work["posting_date"] = pd.to_datetime(work["posting_date"], errors="coerce")
        work["_position"] = np.arange(len(df), dtype=int)
        work = work.sort_values(["gl_account", "posting_date", "_position"])
        work["dormant_gap_days"] = work.groupby("gl_account")["posting_date"].diff().dt.days
        gap = pd.Series(np.nan, index=np.arange(len(df), dtype=int), dtype=float)
        gap.loc[work["_position"].to_numpy()] = work["dormant_gap_days"].to_numpy()
        out["dormant_gap_days"] = gap
    return out


def _case_feature_rows(
    cases: list[RelationalCase],
    df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    context_series = _context_series(df)
    for idx, case in enumerate(_sorted_cases(cases), start=1):
        docs = _case_documents(case)
        edge_key = f"{case.sub_rule}|{case.edge_a}|{case.edge_b}"
        row_positions = (
            [
                ref.row_position
                for ref in case.row_refs
                if 0 <= ref.row_position < len(df)
            ]
            if df is not None
            else []
        )
        row_slice = df.iloc[row_positions] if df is not None and row_positions else None
        bool_context: dict[str, int] = {}
        categorical_context: dict[str, str] = {}
        numeric_context: dict[str, float | None] = {}
        if row_slice is not None:
            for column in ("is_manual_je", "is_period_end", "is_after_hours", "is_round_number"):
                if column in row_slice.columns:
                    bool_context[column] = int(row_slice[column].fillna(False).astype(bool).sum())
            for column in ("business_process", "counterparty_type", "risk_level"):
                if column in row_slice.columns:
                    mode = row_slice[column].fillna("blank").astype(str).mode()
                    categorical_context[column] = str(mode.iat[0]) if not mode.empty else "blank"
            if "fiscal_year" in row_slice.columns:
                mode = row_slice["fiscal_year"].fillna("unknown").astype(str).mode()
                categorical_context["fiscal_year"] = (
                    str(mode.iat[0]) if not mode.empty else "unknown"
                )
            if "days_since_partner_first_seen" in context_series:
                values = context_series["days_since_partner_first_seen"].iloc[row_positions]
                numeric_context["min_days_since_partner_first_seen"] = (
                    float(values.min()) if values.notna().any() else None
                )
            if "dormant_gap_days" in context_series:
                values = context_series["dormant_gap_days"].iloc[row_positions]
                numeric_context["max_dormant_gap_days"] = (
                    float(values.max()) if values.notna().any() else None
                )
        rows.append(
            {
                "ordinal": idx,
                "case": case,
                "sub_rule": case.sub_rule,
                "tier": case.evidence_tier,
                "family_score": float(case.family_score or 0.0),
                "family_ecdf": float(case.family_ecdf or 0.0),
                "rows_per_edge": len(case.row_refs),
                "documents_per_edge": len(docs),
                "edge_key": edge_key,
                "subject_key": str(case.edge_a or ""),
                "account_key": str(case.edge_b or ""),
                "account_class": _account_class(str(case.edge_b or "")),
                "row_count_bucket": _count_bucket(len(case.row_refs)),
                "document_count_bucket": _count_bucket(len(docs)),
                "bool_context": bool_context,
                "categorical_context": categorical_context,
                "fiscal_year": categorical_context.get("fiscal_year", "unknown"),
                "numeric_context": numeric_context,
                "new_counterparty_age_bucket": _age_bucket(
                    numeric_context.get("min_days_since_partner_first_seen")
                ),
                "dormant_gap_bucket": _gap_bucket(numeric_context.get("max_dormant_gap_days")),
                "positive_metric_count": int(
                    case.case_generation_reason.get("positive_metric_count", 0)
                    if isinstance(case.case_generation_reason, dict)
                    else 0
                ),
            }
        )
    return rows


def _count_bucket(value: int) -> str:
    if value <= 1:
        return "1"
    if value <= 3:
        return "2_3"
    if value <= 10:
        return "4_10"
    if value <= 50:
        return "11_50"
    return "51_plus"


def _tier_rank(row: dict[str, Any]) -> int:
    return {"strong": 3, "moderate": 2, "ml_quantile": 1, "weak": 0}.get(
        str(row["tier"]).lower(),
        -1,
    )


def _current_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -_tier_rank(row),
            -float(row["family_score"]),
            row["case"].phase2_case_id,
        ),
    )


def _edge_support_penalty_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -_tier_rank(row),
            -(float(row["family_score"]) / math.sqrt(max(int(row["rows_per_edge"]), 1))),
            row["case"].phase2_case_id,
        ),
    )


def _document_diversity_penalty_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -_tier_rank(row),
            -(float(row["family_score"]) / math.sqrt(max(int(row["documents_per_edge"]), 1))),
            row["case"].phase2_case_id,
        ),
    )


def _balanced_sub_rule_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _current_sort(rows):
        by_rule[str(row["sub_rule"])].append(row)
    order = sorted(by_rule)
    out: list[dict[str, Any]] = []
    cursor = 0
    while len(out) < len(rows):
        moved = False
        for rule in order:
            bucket = by_rule[rule]
            if cursor < len(bucket):
                out.append(bucket[cursor])
                moved = True
        if not moved:
            break
        cursor += 1
    return out


def _r03_r07_priority_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    priority = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    rest = [row for row in current if row["sub_rule"] not in {"R03", "R07"}]
    return priority + rest


def _volume_capped_by_edge_support_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    counts = Counter(str(row["edge_key"]) for row in current)
    support_values = list(counts.values())
    cap_floor = int(np.quantile(support_values, 0.90)) if support_values else 1
    display_counts: Counter[str] = Counter()
    primary: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    for row in current:
        if row["sub_rule"] not in {"R05", "R06"}:
            primary.append(row)
            continue
        key = str(row["edge_key"])
        edge_cap = max(1, min(counts[key], cap_floor))
        if display_counts[key] < edge_cap:
            primary.append(row)
            display_counts[key] += 1
        else:
            overflow.append(row)
    return primary + overflow


def _moderate_tail_surface(rows: list[dict[str, Any]], *, q: float) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    selected = [
        row
        for row in current
        if row["tier"] == "moderate"
        and int(row["positive_metric_count"]) >= 20
        and float(row["family_ecdf"]) >= q
    ]
    selected_ids = {id(row) for row in selected}
    rest = [row for row in current if id(row) not in selected_ids]
    return selected + rest


def _moderate_tail_low_burden_rows(
    rows: list[dict[str, Any]],
    *,
    q: float = 0.95,
) -> list[dict[str, Any]]:
    moderate_tail = [
        row
        for row in _current_sort(rows)
        if row["tier"] == "moderate"
        and int(row["positive_metric_count"]) >= 20
        and float(row["family_ecdf"]) >= q
    ]
    if not moderate_tail:
        return []
    row_cap = float(np.quantile([int(row["rows_per_edge"]) for row in moderate_tail], 0.95))
    doc_cap = float(
        np.quantile([int(row["documents_per_edge"]) for row in moderate_tail], 0.95)
    )
    return [
        row
        for row in moderate_tail
        if int(row["rows_per_edge"]) <= row_cap
        and int(row["documents_per_edge"]) <= doc_cap
    ]


def _moderate_tail_business_balanced_rows(
    rows: list[dict[str, Any]],
    *,
    q: float = 0.95,
) -> list[dict[str, Any]]:
    moderate_tail = [
        row
        for row in _current_sort(rows)
        if row["tier"] == "moderate"
        and int(row["positive_metric_count"]) >= 20
        and float(row["family_ecdf"]) >= q
    ]
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in moderate_tail:
        bucket = str(row["categorical_context"].get("business_process", "unknown"))
        by_bucket[bucket].append(row)
    out: list[dict[str, Any]] = []
    cursor = 0
    order = sorted(by_bucket)
    while len(out) < len(moderate_tail):
        moved = False
        for bucket in order:
            bucket_rows = by_bucket[bucket]
            if cursor < len(bucket_rows):
                out.append(bucket_rows[cursor])
                moved = True
        if not moved:
            break
        cursor += 1
    return out


def _moderate_tail_audit_context_balanced_rows(
    rows: list[dict[str, Any]],
    *,
    q: float = 0.95,
) -> list[dict[str, Any]]:
    moderate_tail = [
        row
        for row in _current_sort(rows)
        if row["tier"] == "moderate"
        and int(row["positive_metric_count"]) >= 20
        and float(row["family_ecdf"]) >= q
    ]
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in moderate_tail:
        if row["sub_rule"] == "R01":
            timing_bucket = str(row["new_counterparty_age_bucket"])
        elif row["sub_rule"] == "R02":
            timing_bucket = str(row["dormant_gap_bucket"])
        else:
            timing_bucket = "other"
        bucket = "|".join(
            [
                str(row["categorical_context"].get("business_process", "unknown")),
                str(row["sub_rule"]),
                timing_bucket,
                str(row["account_class"]),
                str(row["document_count_bucket"]),
            ]
        )
        by_bucket[bucket].append(row)
    out: list[dict[str, Any]] = []
    cursor = 0
    order = sorted(by_bucket)
    while len(out) < len(moderate_tail):
        moved = False
        for bucket in order:
            bucket_rows = by_bucket[bucket]
            if cursor < len(bucket_rows):
                out.append(bucket_rows[cursor])
                moved = True
        if not moved:
            break
        cursor += 1
    return out


def _moderate_tail_low_burden_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = _moderate_tail_low_burden_rows(rows)
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in _current_sort(rows) if id(row) not in selected_ids]


def _moderate_tail_business_balanced_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = _moderate_tail_business_balanced_rows(rows)
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in _current_sort(rows) if id(row) not in selected_ids]


def _moderate_tail_audit_context_balanced_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = _moderate_tail_audit_context_balanced_rows(rows)
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in _current_sort(rows) if id(row) not in selected_ids]


def _moderate_tail_audit_then_business_balanced_rows(
    rows: list[dict[str, Any]],
    *,
    audit_prefix: int = 50,
) -> list[dict[str, Any]]:
    audit_rows = _moderate_tail_audit_context_balanced_rows(rows)
    business_rows = _moderate_tail_business_balanced_rows(rows)
    selected = audit_rows[:audit_prefix]
    selected_ids = {id(row) for row in selected}
    selected.extend(row for row in business_rows if id(row) not in selected_ids)
    selected_ids = {id(row) for row in selected}
    selected.extend(row for row in audit_rows if id(row) not in selected_ids)
    return selected


def _moderate_tail_capped_context_rows(
    rows: list[dict[str, Any]],
    *,
    max_per_business_process: int = 90,
    max_per_document_bucket: int = 220,
) -> list[dict[str, Any]]:
    source = _moderate_tail_audit_then_business_balanced_rows(rows)
    business_counts: Counter[str] = Counter()
    document_bucket_counts: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    for row in source:
        business = str(row["categorical_context"].get("business_process", "unknown"))
        document_bucket = str(row["document_count_bucket"])
        if (
            business_counts[business] < max_per_business_process
            and document_bucket_counts[document_bucket] < max_per_document_bucket
        ):
            selected.append(row)
            business_counts[business] += 1
            document_bucket_counts[document_bucket] += 1
        else:
            overflow.append(row)
    return selected + overflow


def _moderate_tail_audit_then_business_balanced_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = _moderate_tail_audit_then_business_balanced_rows(rows)
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in _current_sort(rows) if id(row) not in selected_ids]


def _moderate_tail_capped_context_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = _moderate_tail_capped_context_rows(rows)
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in _current_sort(rows) if id(row) not in selected_ids]


def _sub_rule_balanced_review_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_rules = ("R03", "R07", "R05", "R06")
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    current = _current_sort(rows)
    for row in current:
        by_rule[str(row["sub_rule"])].append(row)
    out: list[dict[str, Any]] = []
    cursor = 0
    while len(out) < sum(len(by_rule[rule]) for rule in priority_rules):
        moved = False
        for rule in priority_rules:
            bucket = by_rule[rule]
            if cursor < len(bucket):
                out.append(bucket[cursor])
                moved = True
        if not moved:
            break
        cursor += 1
    selected_ids = {id(row) for row in out}
    return out + [row for row in current if id(row) not in selected_ids]


def _edge_novelty_with_tier_guard_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in _current_sort(rows)
        if row["tier"] == "strong"
        or (
            row["tier"] == "moderate"
            and int(row["positive_metric_count"]) >= 20
            and float(row["family_ecdf"]) >= 0.95
        )
    ]
    by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        by_edge[str(row["edge_key"])].append(row)
    ordered: list[dict[str, Any]] = []
    edge_order = sorted(
        by_edge,
        key=lambda key: (
            -_tier_rank(by_edge[key][0]),
            -float(by_edge[key][0]["family_ecdf"]),
            -float(by_edge[key][0]["family_score"]),
        ),
    )
    cursor = 0
    while len(ordered) < len(eligible):
        moved = False
        for key in edge_order:
            bucket = by_edge[key]
            if cursor < len(bucket):
                ordered.append(bucket[cursor])
                moved = True
        if not moved:
            break
        cursor += 1
    selected_ids = {id(row) for row in ordered}
    return ordered + [row for row in _current_sort(rows) if id(row) not in selected_ids]


def _account_partner_context_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    partner_account = [row for row in current if row["sub_rule"] in {"R03", "R05"}]
    user_account = [row for row in current if row["sub_rule"] == "R06"]
    other = [row for row in current if row["sub_rule"] not in {"R03", "R05", "R06"}]
    out: list[dict[str, Any]] = []
    cursor = 0
    while len(out) < len(partner_account) + len(user_account):
        moved = False
        if cursor < len(partner_account):
            out.append(partner_account[cursor])
            moved = True
        if cursor < len(user_account):
            out.append(user_account[cursor])
            moved = True
        if not moved:
            break
        cursor += 1
    return out + other


def _r03_r07_structural_only_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in _current_sort(rows)
        if row["sub_rule"] in {"R03", "R07"}
    ]


def _r01_r02_moderate_tail_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in _current_sort(rows)
        if row["sub_rule"] in {"R01", "R02"}
        and row["tier"] == "moderate"
        and int(row["positive_metric_count"]) >= 20
        and float(row["family_ecdf"]) >= 0.95
    ]


def _r05_r06_context_lane_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    return [row for row in current if row["sub_rule"] in {"R05", "R06"}]


def _take_quota_round(
    buckets: list[list[dict[str, Any]]],
    quotas: list[int],
    *,
    total: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursors = [0 for _bucket in buckets]
    while len(out) < total:
        moved = False
        for bucket_idx, bucket in enumerate(buckets):
            quota = quotas[bucket_idx]
            for _ in range(quota):
                cursor = cursors[bucket_idx]
                if cursor < len(bucket):
                    out.append(bucket[cursor])
                    cursors[bucket_idx] += 1
                    moved = True
                    if len(out) >= total:
                        break
            if len(out) >= total:
                break
        if not moved:
            break
    return out


def _structural_moderate_tail_lane_split_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    strong_structural = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    moderate_tail = [
        row
        for row in current
        if row["tier"] == "moderate"
        and int(row["positive_metric_count"]) >= 20
        and float(row["family_ecdf"]) >= 0.95
    ]
    selected = _take_quota_round(
        [strong_structural, moderate_tail],
        [1, 1],
        total=len(rows),
    )
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in current if id(row) not in selected_ids]


def _structural_moderate_low_burden_lane_split_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    strong_structural = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    moderate_tail = _moderate_tail_low_burden_rows(rows)
    selected = _take_quota_round(
        [strong_structural, moderate_tail],
        [1, 1],
        total=len(rows),
    )
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in current if id(row) not in selected_ids]


def _structural_moderate_business_balanced_lane_split_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    strong_structural = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    moderate_tail = _moderate_tail_business_balanced_rows(rows)
    selected = _take_quota_round(
        [strong_structural, moderate_tail],
        [1, 1],
        total=len(rows),
    )
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in current if id(row) not in selected_ids]


def _structural_moderate_audit_context_balanced_lane_split_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    strong_structural = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    moderate_tail = _moderate_tail_audit_context_balanced_rows(rows)
    selected = _take_quota_round(
        [strong_structural, moderate_tail],
        [1, 1],
        total=len(rows),
    )
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in current if id(row) not in selected_ids]


def _structural_moderate_audit_then_business_lane_split_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    strong_structural = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    moderate_tail = _moderate_tail_audit_then_business_balanced_rows(rows)
    selected = _take_quota_round(
        [strong_structural, moderate_tail],
        [1, 1],
        total=len(rows),
    )
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in current if id(row) not in selected_ids]


def _structural_moderate_capped_context_lane_split_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    strong_structural = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    moderate_tail = _moderate_tail_capped_context_rows(rows)
    selected = _take_quota_round(
        [strong_structural, moderate_tail],
        [1, 1],
        total=len(rows),
    )
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in current if id(row) not in selected_ids]


def _structural_anchor_moderate_audit_business_surface(
    rows: list[dict[str, Any]],
    *,
    moderate_quota: int,
) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    strong_structural = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    moderate_tail = _moderate_tail_audit_then_business_balanced_rows(rows)
    selected = _take_quota_round(
        [strong_structural, moderate_tail],
        [1, moderate_quota],
        total=len(rows),
    )
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in current if id(row) not in selected_ids]


def _structural_anchor_moderate_1_to_2_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _structural_anchor_moderate_audit_business_surface(rows, moderate_quota=2)


def _structural_anchor_moderate_1_to_3_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _structural_anchor_moderate_audit_business_surface(rows, moderate_quota=3)


def _structural_anchor_moderate_1_to_4_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _structural_anchor_moderate_audit_business_surface(rows, moderate_quota=4)


def _three_lane_structural_moderate_context_surface(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = _current_sort(rows)
    strong_structural = [row for row in current if row["sub_rule"] in {"R03", "R07"}]
    moderate_tail = [
        row
        for row in current
        if row["tier"] == "moderate"
        and int(row["positive_metric_count"]) >= 20
        and float(row["family_ecdf"]) >= 0.95
    ]
    context = [row for row in current if row["sub_rule"] in {"R05", "R06"}]
    selected = _take_quota_round(
        [strong_structural, moderate_tail, context],
        [2, 2, 1],
        total=len(rows),
    )
    selected_ids = {id(row) for row in selected}
    return selected + [row for row in current if id(row) not in selected_ids]


def _ranking_candidates(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "current": _current_sort(rows),
        "edge_support_penalty": _edge_support_penalty_sort(rows),
        "document_diversity_penalty": _document_diversity_penalty_sort(rows),
        "rare_edge_balanced_sampling_per_sub_rule": _balanced_sub_rule_sort(rows),
        "r03_r07_priority_first_surface": _r03_r07_priority_surface(rows),
        "r05_r06_volume_capped_by_edge_support": _volume_capped_by_edge_support_surface(rows),
        "moderate_tail_only_surface_q95": _moderate_tail_surface(rows, q=0.95),
        "moderate_tail_only_surface_q99": _moderate_tail_surface(rows, q=0.99),
        "moderate_tail_low_burden_surface": _moderate_tail_low_burden_surface(rows),
        "moderate_tail_business_balanced_surface": (
            _moderate_tail_business_balanced_surface(rows)
        ),
        "moderate_tail_audit_context_balanced_surface": (
            _moderate_tail_audit_context_balanced_surface(rows)
        ),
        "moderate_tail_audit_then_business_balanced_surface": (
            _moderate_tail_audit_then_business_balanced_surface(rows)
        ),
        "moderate_tail_capped_context_surface": _moderate_tail_capped_context_surface(rows),
        "sub_rule_balanced_review_surface": _sub_rule_balanced_review_surface(rows),
        "edge_novelty_with_tier_guard": _edge_novelty_with_tier_guard_surface(rows),
        "account_partner_context_surface": _account_partner_context_surface(rows),
        "r03_r07_structural_only_surface": _r03_r07_structural_only_surface(rows),
        "r01_r02_moderate_tail_surface": _r01_r02_moderate_tail_surface(rows),
        "r05_r06_context_lane_surface": _r05_r06_context_lane_surface(rows),
        "structural_moderate_tail_lane_split_surface": (
            _structural_moderate_tail_lane_split_surface(rows)
        ),
        "structural_moderate_low_burden_lane_split_surface": (
            _structural_moderate_low_burden_lane_split_surface(rows)
        ),
        "structural_moderate_business_balanced_lane_split_surface": (
            _structural_moderate_business_balanced_lane_split_surface(rows)
        ),
        "structural_moderate_audit_context_balanced_lane_split_surface": (
            _structural_moderate_audit_context_balanced_lane_split_surface(rows)
        ),
        "structural_moderate_audit_then_business_lane_split_surface": (
            _structural_moderate_audit_then_business_lane_split_surface(rows)
        ),
        "structural_moderate_capped_context_lane_split_surface": (
            _structural_moderate_capped_context_lane_split_surface(rows)
        ),
        "structural_anchor_moderate_1_to_2_surface": (
            _structural_anchor_moderate_1_to_2_surface(rows)
        ),
        "structural_anchor_moderate_1_to_3_surface": (
            _structural_anchor_moderate_1_to_3_surface(rows)
        ),
        "structural_anchor_moderate_1_to_4_surface": (
            _structural_anchor_moderate_1_to_4_surface(rows)
        ),
        "three_lane_structural_moderate_context_surface": (
            _three_lane_structural_moderate_context_surface(rows)
        ),
    }


def _scenario_matrix_for_topn(
    rows: list[dict[str, Any]],
    truth_scenario_by_doc: dict[str, str],
    *,
    top_n: int,
) -> dict[str, int]:
    docs: set[str] = set()
    for row in rows[:top_n]:
        docs.update(_case_documents(row["case"]))
    counts = Counter(
        truth_scenario_by_doc[doc]
        for doc in docs
        if doc in truth_scenario_by_doc
    )
    return dict(sorted(counts.items()))


def _high_volume_nontruth_proxy(
    rows: list[dict[str, Any]],
    truth_docs: set[str],
) -> dict[str, Any]:
    row_counts = [int(row["rows_per_edge"]) for row in rows]
    p90 = float(np.quantile(row_counts, 0.90)) if row_counts else 0.0
    high_volume_normal = [
        row
        for row in rows
        if int(row["rows_per_edge"]) >= p90
        and not (_case_documents(row["case"]) & truth_docs)
    ]
    return {
        "rows_per_edge_p90": p90,
        "high_volume_nontruth_case_count": len(high_volume_normal),
        "high_volume_nontruth_share": len(high_volume_normal) / max(len(rows), 1),
    }


def _edge_concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["edge_key"]) for row in rows)
    values = list(counts.values())
    dist = _numeric_distribution(values)
    total = sum(values)
    top1 = max(values) if values else 0
    return {
        "edge_count": len(counts),
        "max_cases_per_edge": int(top1),
        "top_edge_share": top1 / max(total, 1),
        "p50_cases_per_edge": dist["p50"],
        "p90_cases_per_edge": dist["p90"],
    }


def _document_concentration(
    rows: list[dict[str, Any]],
    *,
    raw_key_name: str = "document",
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(_case_documents(row["case"]))
    total = sum(counts.values())
    top1 = max(counts.values()) if counts else 0
    return {
        f"{raw_key_name}_count": len(counts),
        f"max_cases_per_{raw_key_name}": int(top1),
        f"top_{raw_key_name}_share": top1 / max(total, 1),
    }


def _first_truth_rank(rows: list[dict[str, Any]], truth_docs: set[str]) -> int | None:
    for idx, row in enumerate(rows, start=1):
        if _case_documents(row["case"]) & truth_docs:
            return idx
    return None


def _small_sample_pressure(rows: list[dict[str, Any]]) -> dict[str, Any]:
    moderate = [row for row in rows if row["tier"] == "moderate"]
    low_support = [
        row
        for row in moderate
        if int(row["positive_metric_count"]) < 20 or float(row["family_ecdf"]) < 0.95
    ]
    small_sample = [
        row for row in moderate if int(row["positive_metric_count"]) < 20
    ]
    return {
        "low_support_moderate_count": len(low_support),
        "small_sample_moderate_count": len(small_sample),
    }


def _review_burden(rows: list[dict[str, Any]], truth_docs: set[str]) -> dict[str, Any]:
    matched_cases = sum(1 for row in rows if _case_documents(row["case"]) & truth_docs)
    return {
        "case_count": len(rows),
        "truth_case_count": matched_cases,
        "nontruth_case_count": len(rows) - matched_cases,
        "cases_per_matched_case": len(rows) / max(matched_cases, 1),
    }


def _phase1_baseline_document_sets(
    *,
    df: pd.DataFrame,
    results: list[Any],
    truth_docs: set[str],
) -> dict[str, Any]:
    flagged_positions: set[int] = set()
    best_score_by_position: dict[int, float] = {}
    for result in results:
        raw_positions = getattr(result, "flagged_indices", None) or []
        valid_positions: list[int] = []
        for raw_pos in raw_positions:
            try:
                pos = int(raw_pos)
            except (TypeError, ValueError):
                continue
            if 0 <= pos < len(df):
                valid_positions.append(pos)
                flagged_positions.add(pos)
        scores = getattr(result, "scores", None)
        if scores is None:
            for pos in valid_positions:
                best_score_by_position[pos] = max(best_score_by_position.get(pos, 0.0), 1.0)
            continue
        for pos in valid_positions:
            try:
                score = float(scores.iloc[pos])
            except (AttributeError, IndexError, TypeError, ValueError):
                score = 0.0
            best_score_by_position[pos] = max(best_score_by_position.get(pos, 0.0), score)

    all_docs = {
        str(value)
        for value in df.iloc[sorted(flagged_positions)]["document_id"].dropna().astype(str)
        if value
    }
    ordered_positions = sorted(
        flagged_positions,
        key=lambda pos: (-best_score_by_position.get(pos, 0.0), pos),
    )
    topn_docs: dict[str, set[str]] = {}
    for top_n in (100, 500, 1000, 10000):
        docs = {
            str(value)
            for value in df.iloc[ordered_positions[:top_n]]["document_id"].dropna().astype(str)
            if value
        }
        topn_docs[str(top_n)] = docs

    all_truth_docs = all_docs & truth_docs
    topn_truth_docs = {
        top_n: docs & truth_docs
        for top_n, docs in topn_docs.items()
    }
    return {
        "source": (
            "PHASE1 detector flagged row document_id aggregate; TOP-N uses "
            "read-only detector score proxy."
        ),
        "flagged_row_count": len(flagged_positions),
        "document_count": len(all_docs),
        "truth_document_count": len(all_truth_docs),
        "topn": {
            top_n: {
                "review_document_count": len(docs),
                "truth_document_count": len(topn_truth_docs[top_n]),
            }
            for top_n, docs in topn_docs.items()
        },
        "_all_truth_docs": all_truth_docs,
        "_topn_truth_docs": topn_truth_docs,
        "_truth_document_total": len(truth_docs),
    }


def _public_phase1_baseline(phase1_baseline: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in phase1_baseline.items()
        if not key.startswith("_")
    }
    truth_total = int(phase1_baseline.get("_truth_document_total", 0))
    public["phase1_all_document_inclusion"] = {
        "truth_document_coverage": public["truth_document_count"],
        "truth_document_total": truth_total,
        "coverage_ratio": public["truth_document_count"] / max(truth_total, 1),
        "interpretation": (
            "Broad PHASE1 review universe inclusion only; this does not prove "
            "relational evidence or scenario explanation coverage."
        ),
    }
    public["phase1_topn_truth_document_coverage"] = {
        top_n: metrics["truth_document_count"]
        for top_n, metrics in public["topn"].items()
    }
    return public


def _topn_review_docs(rows: list[dict[str, Any]], top_n: int) -> set[str]:
    docs: set[str] = set()
    for row in rows[:top_n]:
        docs.update(_case_documents(row["case"]))
    return docs


def _incremental_topn_metrics(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any],
    top_n: int,
) -> dict[str, Any]:
    review_docs = _topn_review_docs(rows, top_n)
    matched_truth = review_docs & truth_docs
    phase1_all_truth = phase1_baseline["_all_truth_docs"]
    phase1_overlap = matched_truth & phase1_all_truth
    phase1_missed = matched_truth - phase1_all_truth
    by_topn = {
        phase1_top_n: matched_truth - docs
        for phase1_top_n, docs in phase1_baseline["_topn_truth_docs"].items()
    }
    return {
        "matched_truth_docs": len(matched_truth),
        "phase1_overlap_truth_docs": len(phase1_overlap),
        "phase1_missed_truth_docs": len(phase1_missed),
        "incremental_truth_docs_vs_phase1_all": len(phase1_missed),
        "incremental_truth_docs_vs_phase1_top100": len(by_topn["100"]),
        "incremental_truth_docs_vs_phase1_top500": len(by_topn["500"]),
        "incremental_truth_docs_vs_phase1_top1000": len(by_topn["1000"]),
        "overlap_ratio": len(phase1_overlap) / max(len(matched_truth), 1),
        "incremental_ratio": len(phase1_missed) / max(len(matched_truth), 1),
        "nontruth_document_count": len(review_docs - truth_docs),
        "incremental_truth_per_100_review_docs": (
            len(phase1_missed) / max(len(review_docs), 1) * 100
        ),
        "sub_rule_incremental_breakdown": _incremental_sub_rule_breakdown(
            rows[:top_n],
            truth_docs=truth_docs,
            phase1_all_truth_docs=phase1_all_truth,
        ),
        "scenario_incremental_counts": dict(
            sorted(
                Counter(
                    truth_scenario_by_doc[doc]
                    for doc in phase1_missed
                    if doc in truth_scenario_by_doc
                ).items()
            )
        ),
    }


def _incremental_sub_rule_breakdown(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    phase1_all_truth_docs: set[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rule in sorted({str(row["sub_rule"]) for row in rows}):
        rule_docs: set[str] = set()
        for row in rows:
            if str(row["sub_rule"]) == rule:
                rule_docs.update(_case_documents(row["case"]))
        matched = rule_docs & truth_docs
        missed = matched - phase1_all_truth_docs
        overlap = matched & phase1_all_truth_docs
        out[rule] = {
            "matched_truth_docs": len(matched),
            "phase1_overlap_truth_docs": len(overlap),
            "phase1_missed_truth_docs": len(missed),
            "incremental_truth_docs_vs_phase1_all": len(missed),
            "overlap_ratio": len(overlap) / max(len(matched), 1),
            "incremental_ratio": len(missed) / max(len(matched), 1),
        }
    return out


def _incremental_coverage_metrics(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any],
) -> dict[str, Any]:
    return {
        str(top_n): _incremental_topn_metrics(
            rows,
            truth_docs=truth_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
            phase1_baseline=phase1_baseline,
            top_n=top_n,
        )
        for top_n in (100, 500, 1000, 10000)
    }


def _phase1_topn_uplift_metrics(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    phase1_baseline: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "phase1_all_truth_document_coverage": len(phase1_baseline["_all_truth_docs"]),
        "phase1_top100_truth_document_coverage": len(
            phase1_baseline["_topn_truth_docs"]["100"]
        ),
        "phase1_top500_truth_document_coverage": len(
            phase1_baseline["_topn_truth_docs"]["500"]
        ),
        "phase1_top1000_truth_document_coverage": len(
            phase1_baseline["_topn_truth_docs"]["1000"]
        ),
    }
    for top_n in (100, 500, 1000):
        matched = _topn_review_docs(rows, top_n) & truth_docs
        phase1_truth = phase1_baseline["_topn_truth_docs"][str(top_n)]
        out[f"phase2_top{top_n}_truth_not_in_phase1_top{top_n}"] = len(
            matched - phase1_truth
        )
        out[f"net_truth_uplift_vs_phase1_top{top_n}"] = len(matched) - len(phase1_truth)
    return out


def _truth_docs_by_sub_rule(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    rules: set[str],
) -> set[str]:
    docs: set[str] = set()
    for row in rows:
        if str(row["sub_rule"]) in rules:
            docs.update(_case_documents(row["case"]) & truth_docs)
    return docs


def _truth_case_count(rows: list[dict[str, Any]], truth_docs: set[str]) -> int:
    return sum(1 for row in rows if _case_documents(row["case"]) & truth_docs)


def _scenario_explanation_gap(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any],
    top_n: int,
) -> dict[str, Any]:
    top_rows = rows[:top_n]
    matched = _topn_review_docs(rows, top_n) & truth_docs
    phase1_top_truth = phase1_baseline["_topn_truth_docs"][str(top_n)]
    scenario_counts = Counter(
        truth_scenario_by_doc[doc]
        for doc in matched
        if doc in truth_scenario_by_doc
    )
    by_scenario_and_rule: dict[str, Counter[str]] = defaultdict(Counter)
    for row in top_rows:
        rule = str(row["sub_rule"])
        for doc in _case_documents(row["case"]) & truth_docs:
            scenario = truth_scenario_by_doc.get(doc)
            if scenario:
                by_scenario_and_rule[scenario][rule] += 1
    return {
        "phase1_topn_truth_docs_without_relational_surface": len(phase1_top_truth - matched),
        "phase2_relational_truth_docs_not_in_phase1_topn": len(matched - phase1_top_truth),
        "phase2_specific_relational_reason_truth_docs": len(matched),
        "phase1_only_generic_reason_truth_docs": len(phase1_top_truth - matched),
        "truth_scenario_counts": dict(sorted(scenario_counts.items())),
        "relational_rule_explanation_by_scenario": {
            scenario: dict(sorted(counts.items()))
            for scenario, counts in sorted(by_scenario_and_rule.items())
        },
    }


def _relational_evidence_incremental_metrics(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for top_n in (100, 500, 1000):
        top_rows = rows[:top_n]
        matched = _topn_review_docs(rows, top_n) & truth_docs
        structural = _truth_docs_by_sub_rule(
            top_rows,
            truth_docs=truth_docs,
            rules={"R03", "R07"},
        )
        moderate = _truth_docs_by_sub_rule(
            top_rows,
            truth_docs=truth_docs,
            rules={"R01", "R02"},
        )
        context = _truth_docs_by_sub_rule(
            top_rows,
            truth_docs=truth_docs,
            rules={"R05", "R06"},
        )
        out[str(top_n)] = {
            "relational_evidence_added_truth_docs": len(matched),
            "relational_evidence_added_case_count": _truth_case_count(top_rows, truth_docs),
            "structural_evidence_added_truth_docs": len(structural),
            "moderate_tail_evidence_added_truth_docs": len(moderate),
            "r05_r06_context_evidence_added_truth_docs": len(context),
            "phase1_only_generic_reason_truth_docs": len(
                phase1_baseline["_topn_truth_docs"][str(top_n)] - matched
            ),
            "phase2_specific_relational_reason_truth_docs": len(matched),
            "evidence_unit_distribution": dict(
                sorted(Counter(str(row["sub_rule"]) for row in top_rows).items())
            ),
            "scenario_explanation_gap": _scenario_explanation_gap(
                rows,
                truth_docs=truth_docs,
                truth_scenario_by_doc=truth_scenario_by_doc,
                phase1_baseline=phase1_baseline,
                top_n=top_n,
            ),
        }
    return out


def _incremental_decision_payload(candidate_metrics: dict[str, Any]) -> dict[str, Any]:
    adopted_name = "structural_moderate_audit_then_business_lane_split_surface"
    adopted = candidate_metrics.get(adopted_name, {})
    uplift = adopted.get("phase1_topn_uplift", {})
    evidence = adopted.get("relational_evidence_incremental", {}).get("500", {})
    top100_uplift = int(uplift.get("net_truth_uplift_vs_phase1_top100", 0))
    top500_uplift = int(uplift.get("net_truth_uplift_vs_phase1_top500", 0))
    evidence_docs = int(evidence.get("relational_evidence_added_truth_docs", 0))
    structural_docs = int(evidence.get("structural_evidence_added_truth_docs", 0))
    moderate_docs = int(evidence.get("moderate_tail_evidence_added_truth_docs", 0))
    explanation_docs = int(
        evidence.get("phase2_specific_relational_reason_truth_docs", 0)
    )
    topn_value = "high" if top500_uplift >= 50 and top100_uplift >= 20 else "medium"
    evidence_value = "high" if evidence_docs >= 50 and (structural_docs + moderate_docs) else "low"
    explanation_value = "high" if explanation_docs >= 50 else "low"
    allowed = topn_value == "high" and evidence_value == "high" and explanation_value == "high"
    return {
        "document_inclusion_incremental_value": (
            "broad_inclusion_only_not_decision_basis"
        ),
        "topn_uplift_value": topn_value,
        "evidence_incremental_value": evidence_value,
        "explanation_incremental_value": explanation_value,
        "primary_product_role": RELATIONAL_PRODUCT_ROLE,
        "product_role": RELATIONAL_PRODUCT_ROLE,
        "role_scope": "relationship_review_surface_primary_pending",
        "primary_denominator_status": RELATIONAL_PRIMARY_DENOMINATOR_STATUS,
        "primary_target_recall_applicable": False,
        "primary_recall_pending_reason": (
            "relationship-primary denominator is unavailable in fixed5 v3.2d; "
            "audit_then_business remains the product review surface until "
            "relationship-primary/co-primary metadata is regenerated"
        ),
        "recommended_default_surface_if_datasynth_incomplete": adopted_name,
        "adopted_default_allowed": allowed,
        "reason": (
            "audit_then_business is evaluated as PHASE1 TOP-N uplift plus structural "
            "evidence/explanation incremental, not as broad PHASE1 document-inclusion "
            f"blind-spot recovery. TOP100 uplift={top100_uplift}, TOP500 uplift="
            f"{top500_uplift}, TOP500 relational evidence truth docs={evidence_docs}, "
            f"structural={structural_docs}, moderate_tail={moderate_docs}. "
            "1:4 anchor remains diagnostic upper-bound only."
        ),
    }


def _top_surface_metrics(
    rows: list[dict[str, Any]],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topn: dict[str, Any] = {}
    for top_n in (100, 500, 1000, 10000):
        docs: set[str] = set()
        for row in rows[:top_n]:
            docs.update(_case_documents(row["case"]))
        matched = len(docs & truth_docs)
        top_rows = rows[:top_n]
        topn[str(top_n)] = {
            "matched": matched,
            "recall": matched / max(len(truth_docs), 1),
            "sub_rule_distribution": dict(
                sorted(Counter(str(row["sub_rule"]) for row in top_rows).items())
            ),
            "evidence_tier_distribution": dict(
                sorted(Counter(str(row["tier"]) for row in top_rows).items())
            ),
            "scenario_counts": _scenario_matrix_for_topn(
                rows,
                truth_scenario_by_doc,
                top_n=top_n,
            ),
            "r05_r06_share": (
                sum(1 for row in top_rows if row["sub_rule"] in {"R05", "R06"})
                / max(len(top_rows), 1)
            ),
            "strong_moderate_ratio": (
                sum(1 for row in top_rows if row["tier"] == "strong")
                / max(sum(1 for row in top_rows if row["tier"] == "moderate"), 1)
            ),
            "edge_concentration": _edge_concentration(top_rows),
            "document_concentration": _document_concentration(top_rows),
            "false_positive_pressure_proxy": {
                **_high_volume_nontruth_proxy(top_rows, truth_docs),
                "repeated_edge_concentration": _edge_concentration(top_rows)[
                    "top_edge_share"
                ],
                **_small_sample_pressure(top_rows),
                **_review_burden(top_rows, truth_docs),
            },
        }
    return {
        "case_count_in_candidate_surface": len(rows),
        "first_truth_rank": _first_truth_rank(rows, truth_docs),
        "sub_rule_distribution": dict(
            sorted(Counter(str(row["sub_rule"]) for row in rows).items())
        ),
        "evidence_tier_distribution": dict(
            sorted(Counter(str(row["tier"]) for row in rows).items())
        ),
        "candidate_weight_provenance": {
            "source": "fixed5 exploratory diagnostic weights",
            "calibrated": False,
            "production_ranking_policy": False,
            "requires_cross_batch_fixture_validation_before_adoption": True,
        },
        "no_fitting_contract": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_ranking_changed": False,
            "threshold_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "relational_case_gate_changed": False,
        },
        "topn": topn,
        "phase1_topn_uplift": (
            _phase1_topn_uplift_metrics(
                rows,
                truth_docs=truth_docs,
                phase1_baseline=phase1_baseline,
            )
            if phase1_baseline is not None
            else {}
        ),
        "relational_evidence_incremental": (
            _relational_evidence_incremental_metrics(
                rows,
                truth_docs=truth_docs,
                truth_scenario_by_doc=truth_scenario_by_doc,
                phase1_baseline=phase1_baseline,
            )
            if phase1_baseline is not None
            else {}
        ),
        "incremental_coverage": (
            _incremental_coverage_metrics(
                rows,
                truth_docs=truth_docs,
                truth_scenario_by_doc=truth_scenario_by_doc,
                phase1_baseline=phase1_baseline,
            )
            if phase1_baseline is not None
            else {}
        ),
    }


def _rule_volume_decomposition(
    rows: list[dict[str, Any]],
    truth_docs: set[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rule in ("R05", "R06"):
        rule_rows = [row for row in rows if row["sub_rule"] == rule]
        out[rule] = {
            "case_count": len(rule_rows),
            "edge_concentration": _edge_concentration(rule_rows),
            "top_subject_share": _concentration(
                [row["subject_key"] for row in rule_rows]
            )["top1_share"],
            "top_account_share": _concentration(
                [row["account_key"] for row in rule_rows]
            )["top1_share"],
            "rows_per_edge_distribution": _numeric_distribution(
                [int(row["rows_per_edge"]) for row in rule_rows]
            ),
            "documents_per_edge_distribution": _numeric_distribution(
                [int(row["documents_per_edge"]) for row in rule_rows]
            ),
            "metric_value_quantiles": _numeric_distribution(
                [float(row["family_score"]) for row in rule_rows]
            ),
            "family_ecdf_distribution": _numeric_distribution(
                [float(row["family_ecdf"]) for row in rule_rows]
            ),
            "positive_metric_count_distribution": _numeric_distribution(
                [int(row["positive_metric_count"]) for row in rule_rows]
            ),
            "truth_case_share": (
                sum(
                    1
                    for row in rule_rows
                    if _case_documents(row["case"]) & truth_docs
                )
                / max(len(rule_rows), 1)
            ),
            "high_volume_nontruth_edge_dominance": _high_volume_nontruth_proxy(
                rule_rows,
                truth_docs,
            ),
        }
    return out


def _moderate_tail_decomposition(
    rows: list[dict[str, Any]],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, q in (("q95", 0.95), ("q99", 0.99)):
        tail = [
            row
            for row in _current_sort(rows)
            if row["tier"] == "moderate"
            and int(row["positive_metric_count"]) >= 20
            and float(row["family_ecdf"]) >= q
        ]
        top500 = tail[:500]
        docs: set[str] = set()
        for row in top500:
            docs.update(_case_documents(row["case"]))
        matched_docs = docs & truth_docs
        scenario_counts = Counter(
            truth_scenario_by_doc[doc]
            for doc in matched_docs
            if doc in truth_scenario_by_doc
        )
        out[label] = {
            "tail_case_count": len(tail),
            "sub_rule_distribution": dict(
                sorted(Counter(str(row["sub_rule"]) for row in tail).items())
            ),
            "top500_sub_rule_distribution": dict(
                sorted(Counter(str(row["sub_rule"]) for row in top500).items())
            ),
            "top500_matched": len(matched_docs),
            "top500_scenario_counts": dict(sorted(scenario_counts.items())),
            "top500_review_burden": _review_burden(top500, truth_docs),
            "top500_edge_concentration": _edge_concentration(top500),
            "top500_document_concentration": _document_concentration(top500),
            "top500_context_buckets": {
                "account_class": dict(
                    sorted(Counter(str(row["account_class"]) for row in top500).items())
                ),
                "row_count_bucket": dict(
                    sorted(Counter(str(row["row_count_bucket"]) for row in top500).items())
                ),
                "document_count_bucket": dict(
                    sorted(
                        Counter(str(row["document_count_bucket"]) for row in top500).items()
                    )
                ),
                "business_process": dict(
                    sorted(
                        Counter(
                            str(row["categorical_context"].get("business_process", "unknown"))
                            for row in top500
                        ).items()
                    )
                ),
                "counterparty_type": dict(
                    sorted(
                        Counter(
                            str(row["categorical_context"].get("counterparty_type", "unknown"))
                            for row in top500
                        ).items()
                    )
                ),
                "new_counterparty_age_bucket": dict(
                    sorted(
                        Counter(str(row["new_counterparty_age_bucket"]) for row in top500).items()
                    )
                ),
                "dormant_gap_bucket": dict(
                    sorted(Counter(str(row["dormant_gap_bucket"]) for row in top500).items())
                ),
            },
            "rows_per_edge_distribution": _numeric_distribution(
                [int(row["rows_per_edge"]) for row in tail]
            ),
            "documents_per_edge_distribution": _numeric_distribution(
                [int(row["documents_per_edge"]) for row in tail]
            ),
            "metric_value_distribution": _numeric_distribution(
                [float(row["family_score"]) for row in tail]
            ),
            "family_ecdf_distribution": _numeric_distribution(
                [float(row["family_ecdf"]) for row in tail]
            ),
            "positive_metric_count_distribution": _numeric_distribution(
                [int(row["positive_metric_count"]) for row in tail]
            ),
        }
    return out


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for child in value.values():
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value:
            keys.extend(_walk_keys(child))
        return keys
    return []


def _raw_identifier_leak_check(payload: dict[str, Any], truth_docs: set[str]) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False)
    keys = _walk_keys(payload)
    return {
        "doc_like_token_count": sum(1 for doc in truth_docs if doc and doc in text),
        "forbidden_identifier_key_count": sum(
            1 for key in keys if key in FORBIDDEN_IDENTIFIER_KEYS
        ),
        "phase2_case_id_like_token_count": text.count("p2_relational_edge_"),
        "raw_edge_like_token_count": text.count("raw_edge_"),
    }


def _candidate_metrics(
    rows: list[dict[str, Any]],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        name: _top_surface_metrics(
            candidate_rows,
            truth_docs,
            truth_scenario_by_doc,
            phase1_baseline,
        )
        for name, candidate_rows in _ranking_candidates(rows).items()
    }


def _load_case_input_from_pickle(path: Path) -> pd.DataFrame:
    _print(f"loading cross-batch case input: {path.relative_to(ROOT).as_posix()}")
    with path.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    _print(f"  rows={len(df):,} documents={df['document_id'].nunique():,}")
    return df


def _load_phase1_detection_results(path: Path) -> list[Any]:
    with path.open("rb") as fh:
        payload = pickle.load(fh)
    results = payload.get("results", []) if isinstance(payload, dict) else []
    return list(results) if isinstance(results, list) else []


def _load_truth_csv(path: Path) -> tuple[set[str], dict[str, str]]:
    truth = pd.read_csv(path)
    truth["document_id"] = truth["document_id"].astype(str)
    truth["manipulation_scenario"] = truth["manipulation_scenario"].astype(str)
    truth_docs = set(truth["document_id"])
    scenario_by_doc = dict(
        zip(
            truth["document_id"],
            truth["manipulation_scenario"],
            strict=False,
        )
    )
    _print(f"  cross-batch truth documents={len(truth_docs):,}")
    return truth_docs, scenario_by_doc


def _summarize_selected_candidates(
    candidate_metrics: dict[str, Any],
) -> dict[str, Any]:
    selected = (
        "current",
        "r03_r07_priority_first_surface",
        "moderate_tail_only_surface_q95",
        "moderate_tail_low_burden_surface",
        "moderate_tail_business_balanced_surface",
        "moderate_tail_audit_context_balanced_surface",
        "moderate_tail_audit_then_business_balanced_surface",
        "moderate_tail_capped_context_surface",
        "structural_moderate_tail_lane_split_surface",
        "structural_moderate_low_burden_lane_split_surface",
        "structural_moderate_business_balanced_lane_split_surface",
        "structural_moderate_audit_context_balanced_lane_split_surface",
        "structural_moderate_audit_then_business_lane_split_surface",
        "structural_moderate_capped_context_lane_split_surface",
        "structural_anchor_moderate_1_to_2_surface",
        "structural_anchor_moderate_1_to_3_surface",
        "structural_anchor_moderate_1_to_4_surface",
        "three_lane_structural_moderate_context_surface",
    )
    return {
        name: {
            "first_truth_rank": candidate_metrics[name]["first_truth_rank"],
            "topn": {
                top_n: {
                    "matched": candidate_metrics[name]["topn"][top_n]["matched"],
                    "sub_rule_distribution": candidate_metrics[name]["topn"][top_n][
                        "sub_rule_distribution"
                    ],
                    "r05_r06_share": candidate_metrics[name]["topn"][top_n][
                        "r05_r06_share"
                    ],
                    "false_positive_pressure_proxy": candidate_metrics[name]["topn"][top_n][
                        "false_positive_pressure_proxy"
                    ],
                }
                for top_n in ("100", "500", "1000")
            },
            "no_fitting_contract": candidate_metrics[name]["no_fitting_contract"],
        }
        for name in selected
    }


def _doc_split_map(df: pd.DataFrame, split_column: str) -> dict[str, str]:
    if {"document_id", split_column}.issubset(df.columns):
        work = df[["document_id", split_column]].dropna().copy()
        work["document_id"] = work["document_id"].astype(str)
        work[split_column] = work[split_column].astype(str)
        return (
            work.groupby("document_id")[split_column]
            .agg(lambda values: values.mode().iat[0] if not values.mode().empty else values.iat[0])
            .to_dict()
        )
    return {}


def _split_validation_snapshot(
    rows: list[dict[str, Any]],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    doc_split_by_doc: dict[str, str],
    *,
    split_name: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    split_values = sorted({str(row.get(split_name, "unknown")) for row in rows})
    for split_value in split_values:
        split_rows = [row for row in rows if str(row.get(split_name, "unknown")) == split_value]
        split_truth_docs = {
            doc for doc in truth_docs if doc_split_by_doc.get(doc, "unknown") == split_value
        }
        if not split_rows or not split_truth_docs:
            continue
        metrics = _candidate_metrics(split_rows, split_truth_docs, truth_scenario_by_doc)
        out[split_value] = {
            "case_count": len(split_rows),
            "truth_document_count": len(split_truth_docs),
            "sub_rule_case_counts": dict(
                sorted(Counter(str(row["sub_rule"]) for row in split_rows).items())
            ),
            "candidate_rankings": _summarize_selected_candidates(metrics),
        }
    return out


def _cross_batch_validation_snapshot() -> tuple[dict[str, Any], set[str]]:
    if not FIXED4_CASE_INPUT_PKL.exists() or not FIXED4_TRUTH_CSV.exists():
        return (
            {
                "fixed4": {
                    "available": False,
                    "reason": "fixed4 case input or truth CSV not found",
                }
            },
            set(),
        )

    df = _load_case_input_from_pickle(FIXED4_CASE_INPUT_PKL)
    truth_docs, truth_scenario_by_doc = _load_truth_csv(FIXED4_TRUTH_CSV)
    relational_result = _run_rule_detector("relational", df)
    case_set = build_phase2_case_set(
        batch_id="fixed4_relational_cross_batch_20260529",
        detection_results=[relational_result],
        df=df,
    )
    rows = _case_feature_rows(
        [
            case
            for case in case_set.relational_cases
            if isinstance(case, RelationalCase)
        ],
        df,
    )
    doc_split_by_doc = _doc_split_map(df, "fiscal_year")
    candidate_metrics = _candidate_metrics(rows, truth_docs, truth_scenario_by_doc)
    return (
        {
            "fixed4": {
                "available": True,
                "dataset": FIXED4_DATASET_NAME,
                "case_count": len(rows),
                "truth_document_count": len(truth_docs),
                "sub_rule_case_counts": dict(
                    sorted(Counter(str(row["sub_rule"]) for row in rows).items())
                ),
                "moderate_tail_decomposition": _moderate_tail_decomposition(
                    rows,
                    truth_docs,
                    truth_scenario_by_doc,
                ),
                "candidate_rankings": _summarize_selected_candidates(candidate_metrics),
                "split_validation": {
                    "fiscal_year": _split_validation_snapshot(
                        rows,
                        truth_docs,
                        truth_scenario_by_doc,
                        doc_split_by_doc,
                        split_name="fiscal_year",
                    )
                },
                "interpretation": (
                    "Cross-batch diagnostic only; candidate selectors did not receive "
                    "truth labels."
                ),
            }
        },
        truth_docs,
    )


def main() -> int:
    started = time.perf_counter()
    df = _load_case_input()
    truth = _load_truth()
    truth_docs = set(truth["document_id"].astype(str))
    truth_scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )

    relational_result = _run_rule_detector("relational", df)
    case_set = build_phase2_case_set(
        batch_id=BATCH_ID,
        detection_results=[relational_result],
        df=df,
    )
    cases = [
        case
        for case in case_set.relational_cases
        if isinstance(case, RelationalCase)
    ]
    rows = _case_feature_rows(cases, df)
    phase1_baseline = _phase1_baseline_document_sets(
        df=df,
        results=_load_phase1_detection_results(CASE_INPUT_PKL),
        truth_docs=truth_docs,
    )
    doc_split_by_doc = _doc_split_map(df, "fiscal_year")
    cross_batch_validation, cross_batch_truth_docs = _cross_batch_validation_snapshot()
    artifact_edges = (
        (relational_result.metadata or {})
        .get("relational_edge_artifact", {})
        .get("edges", [])
        if isinstance(relational_result.metadata, dict)
        else []
    )
    candidate_metrics = _candidate_metrics(
        rows,
        truth_docs,
        truth_scenario_by_doc,
        phase1_baseline,
    )

    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "diagnostic_scope": "relational ranking candidate comparison only",
        "non_scope": [
            "No production gate change.",
            "No PHASE1 priority_score/composite_sort_score/ranking change.",
            "No PHASE2 family fusion change.",
            "No truth-label boosting; truth labels are evaluation-only aggregates.",
        ],
        "incremental_value_definition": {
            "phase1_all_document_inclusion": (
                "Broad review-universe inclusion only; not interpreted as relational "
                "evidence or scenario explanation coverage."
            ),
            "phase1_topn_uplift": (
                "Truth documents surfaced by relational TOP-N that were outside the "
                "PHASE1 TOP-N score-proxy set."
            ),
            "relational_evidence_incremental": (
                "Relationship-specific evidence units added by relational native cases "
                "after candidate ordering."
            ),
            "scenario_explanation_gap": (
                "Aggregate scenario counts and relational sub_rule explanation counts; "
                "raw identifiers are not emitted."
            ),
        },
        "privacy_contract": "Aggregate-only counts, quantiles, and shares are emitted.",
        "adopted_relational_product_policy": build_relational_policy_summary(tuple(rows)),
        "truth_label_use_contract": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_ranking_changed": False,
            "threshold_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "relational_case_gate_changed": False,
        },
        "case_count": len(rows),
        "artifact_edge_count": len(artifact_edges),
        "sub_rule_case_counts": dict(
            sorted(Counter(str(row["sub_rule"]) for row in rows).items())
        ),
        "phase1_baseline": _public_phase1_baseline(phase1_baseline),
        "volume_decomposition": _rule_volume_decomposition(rows, truth_docs),
        "moderate_tail_decomposition": _moderate_tail_decomposition(
            rows,
            truth_docs,
            truth_scenario_by_doc,
        ),
        "candidate_rankings": candidate_metrics,
        "incremental_decision": _incremental_decision_payload(candidate_metrics),
        "split_validation": {
            "fiscal_year": _split_validation_snapshot(
                rows,
                truth_docs,
                truth_scenario_by_doc,
                doc_split_by_doc,
                split_name="fiscal_year",
            )
        },
        "cross_batch_validation": cross_batch_validation,
        "output_notes": [
            "Candidate rankings are diagnostic-only top surfaces.",
            "TOP-N truth counts use DataSynth truth labels only after candidate ordering.",
            "Concentration metrics report counts/shares only, not raw edge identifiers.",
        ],
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_check(
        payload,
        truth_docs | cross_batch_truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
