"""Small helpers for PHASE1 raw-rule truth use in dashboard surfaces."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from src.detection.rule_detail_metadata import canonicalize_rule_id
from src.export.phase1_case_view import build_phase1_raw_rule_truth_index


def phase1_truth_index(pr: Any | None) -> dict[str, Any]:
    """Return PHASE1 raw_rule_hits truth index, or unavailable fallback."""

    if pr is None:
        return {"available": False}
    return build_phase1_raw_rule_truth_index(pr)


def raw_truth_row_mask(
    data: pd.DataFrame,
    truth: dict[str, Any],
    selected_rules: Iterable[str],
) -> pd.Series:
    """Build a row mask from PHASE1 raw_rule_hits rule references."""

    rules = {
        canonicalize_rule_id(str(rule_id or "").strip())
        for rule_id in selected_rules
    }
    rules.discard("")
    if not rules:
        return pd.Series(False, index=data.index)

    row_indices: set[int] = set()
    document_ids: set[str] = set()
    rule_row_indices = truth.get("rule_row_indices") or {}
    rule_document_ids = truth.get("rule_document_ids") or {}
    for rule_id in rules:
        row_indices.update(int(idx) for idx in rule_row_indices.get(rule_id, set()))
        document_ids.update(str(doc_id) for doc_id in rule_document_ids.get(rule_id, set()))

    mask = pd.Series(False, index=data.index)
    valid_positions = [idx for idx in row_indices if 0 <= idx < len(data)]
    if valid_positions:
        mask.iloc[valid_positions] = True
    if document_ids and not valid_positions and "document_id" in data.columns:
        mask |= data["document_id"].astype(str).isin(document_ids)
    return mask


def raw_truth_document_ids(
    truth: dict[str, Any],
    selected_rules: Iterable[str],
) -> set[str]:
    """Return document ids hit by selected PHASE1 raw-rule truth rules."""

    rules = {
        canonicalize_rule_id(str(rule_id or "").strip())
        for rule_id in selected_rules
    }
    rules.discard("")
    rule_document_ids = truth.get("rule_document_ids") or {}
    document_ids: set[str] = set()
    for rule_id in rules:
        document_ids.update(str(doc_id) for doc_id in rule_document_ids.get(rule_id, set()))
    return document_ids
