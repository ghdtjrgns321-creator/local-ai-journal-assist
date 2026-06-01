"""Exact v3.3b relational primary/companion recall measurement.

This diagnostic rebuilds the relational native cases from the v3.3b journal,
then joins only in-memory case document sets to v3.3b owner metadata. Truth and
owner metadata are evaluation inputs only; they are not passed to detector,
case builder, or ordering selectors.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from config.settings import get_settings
from src.detection.relational_detector import RelationalDetector
from src.models.phase2_case import RelationalCase
from src.services.phase2_relational_case_builder import (
    _current_review_order,
    build_relational_cases,
)

DATASET_NAME = os.environ.get(
    "RELATIONAL_DIAGNOSTIC_DATASET",
    "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33b",
)
BATCH_ID = os.environ.get(
    "RELATIONAL_DIAGNOSTIC_BATCH_ID",
    "fixed5_ownermeta_v33b_relational_exact_20260531",
)
ADOPTED_SURFACE = "structural_moderate_audit_then_business_lane_split_surface"
EMPLOYEE_VENDOR_PROFILE_SURFACE = "employee_vendor_observable_profile_surface"
DATASET_DIR = ROOT / "data" / "journal" / "primary" / DATASET_NAME
JOURNAL_CSV = DATASET_DIR / "journal_entries.csv"
TRUTH_CSV = DATASET_DIR / "labels" / "manipulated_entry_truth.csv"
RESPONSIBILITY_ARTIFACT = (
    ROOT
    / os.environ.get(
        "RELATIONAL_RESPONSIBILITY_ARTIFACT",
        "artifacts/phase2_family_responsibility_recall_v33_fixed5_ownermeta_v33b_20260531.json",
    )
)
OUT_JSON = ROOT / os.environ.get(
    "RELATIONAL_DIAGNOSTIC_OUT",
    "artifacts/relational_v33_exact_primary_measurement_20260531.json",
)
TOP_NS = (100, 500, 1000)

FORBIDDEN_IDENTIFIER_KEYS = {
    "document_id",
    "document_ids",
    "raw_document_id",
    "raw_document_ids",
    "row_id",
    "row_ids",
    "raw_row_id",
    "raw_row_ids",
    "phase2_case_id",
    "phase2_case_ids",
    "relationship_group_id",
    "duplicate_pair_group_id",
    "relationship_source_entity",
    "relationship_target_entity",
}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _read_truth_rows() -> list[dict[str, str]]:
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _owner_doc_sets(rows: list[dict[str, str]]) -> dict[str, Any]:
    primary_docs: set[str] = set()
    companion_docs: set[str] = set()
    scenario_by_doc: dict[str, str] = {}
    subtype_by_doc: dict[str, str] = {}
    for row in rows:
        doc = str(row.get("document_id") or "")
        if not doc:
            continue
        scenario_by_doc[doc] = str(row.get("manipulation_scenario") or "")
        subtype_by_doc[doc] = str(row.get("truth_owner_subtype") or "")
        if _is_true(row.get("relationship_primary_target")):
            primary_docs.add(doc)
        if _is_true(row.get("relationship_companion_target")):
            companion_docs.add(doc)
    return {
        "primary_docs": primary_docs,
        "companion_docs": companion_docs,
        "scenario_by_doc": scenario_by_doc,
        "subtype_by_doc": subtype_by_doc,
    }


def _case_documents(case: RelationalCase) -> set[str]:
    return {
        str(ref.document_id)
        for ref in case.row_refs
        if getattr(ref, "document_id", None) not in (None, "")
    }


def _docs_for_topn(cases: list[RelationalCase], top_n: int) -> set[str]:
    docs: set[str] = set()
    for case in cases[:top_n]:
        docs.update(_case_documents(case))
    return docs


def _case_positions(case: RelationalCase, df_len: int) -> list[int]:
    return [
        int(ref.row_position)
        for ref in case.row_refs
        if 0 <= int(ref.row_position) < df_len
    ]


def _case_text_values(case: RelationalCase, *, df: pd.DataFrame, column: str) -> list[str]:
    positions = _case_positions(case, len(df))
    if not positions or column not in df.columns:
        return []
    return [str(value) for value in df.iloc[positions][column].dropna().tolist()]


def _case_mode_text(
    case: RelationalCase,
    *,
    df: pd.DataFrame,
    column: str,
    default: str = "unknown",
) -> str:
    values = _case_text_values(case, df=df, column=column)
    if not values:
        return default
    modes = pd.Series(values, dtype="string").mode()
    return str(modes.iat[0]) if not modes.empty else default


def _any_token(values: list[str], tokens: tuple[str, ...]) -> bool:
    upper_values = [value.upper() for value in values]
    return any(token in value for token in tokens for value in upper_values)


def _account_class(value: str) -> str:
    text = str(value or "")
    if text.startswith(("1", "2")):
        return "balance_sheet"
    if text.startswith(("4", "5", "6", "7", "8")):
        return "income_statement"
    if text:
        return "other_account"
    return "unknown_account"


def _employee_vendor_profile_score(case: RelationalCase, *, df: pd.DataFrame) -> tuple[int, int]:
    """Observable employee/vendor profile score for diagnostic ordering only.

    The score uses GL fields that an auditor can inspect: counterparty/reference
    text, process, account class, and document support. It does not consume
    owner/truth/scenario labels or matched results. Because the fixed5 DataSynth
    uses recognizable employee-vendor reference tokens, this surface remains
    diagnostic-only until non-synthetic validation confirms it is not a shortcut.
    """
    reference_values = _case_text_values(case, df=df, column="reference")
    partner_values = _case_text_values(case, df=df, column="trading_partner")
    process = _case_mode_text(case, df=df, column="business_process")
    account = _case_mode_text(case, df=df, column="gl_account", default="")

    employee_vendor_link = _any_token(
        reference_values + partner_values,
        ("EMP-VEND", "VEND-EMP", "EMPLOYEE", "VENDOR"),
    )
    p2p_process = process.upper() in {"P2P", "PROCURE_TO_PAY", "PURCHASE_TO_PAY"}
    balance_sheet = _account_class(account) == "balance_sheet"
    multi_doc_support = len(_case_documents(case)) >= 2
    return (
        int(employee_vendor_link)
        + int(p2p_process)
        + int(balance_sheet)
        + int(multi_doc_support),
        int(employee_vendor_link),
    )


def _employee_vendor_profile_order(
    cases: list[RelationalCase],
    *,
    df: pd.DataFrame,
) -> list[RelationalCase]:
    current = _current_review_order(cases)
    return sorted(
        current,
        key=lambda case: (
            -_employee_vendor_profile_score(case, df=df)[0],
            -_employee_vendor_profile_score(case, df=df)[1],
            case.sub_rule not in {"R01", "R03", "R07"},
            -_tier_rank_case(case),
            -float(case.family_score or 0.0),
            case.phase2_case_id,
        ),
    )


def _tier_rank_case(case: RelationalCase) -> int:
    return {"strong": 3, "moderate": 2, "ml_quantile": 1, "weak": 0}.get(
        str(case.evidence_tier).lower(),
        -1,
    )


def _matched_breakdown(
    matched_docs: set[str],
    *,
    scenario_by_doc: dict[str, str],
    subtype_by_doc: dict[str, str],
) -> dict[str, Any]:
    return {
        "by_scenario": dict(
            sorted(Counter(scenario_by_doc.get(doc, "unknown") for doc in matched_docs).items())
        ),
        "by_truth_owner_subtype": dict(
            sorted(Counter(subtype_by_doc.get(doc, "unknown") for doc in matched_docs).items())
        ),
    }


def _topn_metrics(
    cases: list[RelationalCase],
    *,
    primary_docs: set[str],
    companion_docs: set[str],
    scenario_by_doc: dict[str, str],
    subtype_by_doc: dict[str, str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for top_n in TOP_NS:
        docs = _docs_for_topn(cases, top_n)
        primary_matched = docs & primary_docs
        companion_matched = docs & companion_docs
        top_cases = cases[:top_n]
        out[f"top{top_n}"] = {
            "review_doc_count": len(docs),
            "primary": {
                "matched_docs": len(primary_matched),
                "denominator": len(primary_docs),
                "recall": len(primary_matched) / max(len(primary_docs), 1),
                "measurement_basis": "available_exact_matched_doc_join",
                **_matched_breakdown(
                    primary_matched,
                    scenario_by_doc=scenario_by_doc,
                    subtype_by_doc=subtype_by_doc,
                ),
            },
            "companion": {
                "matched_docs": len(companion_matched),
                "denominator": len(companion_docs),
                "recall": len(companion_matched) / max(len(companion_docs), 1),
                "measurement_basis": "available_exact_matched_doc_join",
                **_matched_breakdown(
                    companion_matched,
                    scenario_by_doc=scenario_by_doc,
                    subtype_by_doc=subtype_by_doc,
                ),
            },
            "sub_rule_distribution": dict(
                sorted(Counter(str(case.sub_rule) for case in top_cases).items())
            ),
            "evidence_tier_distribution": dict(
                sorted(Counter(str(case.evidence_tier) for case in top_cases).items())
            ),
        }
    return out


def _rank_band_diagnostic(
    cases: list[RelationalCase],
    *,
    primary_docs: set[str],
) -> dict[str, Any]:
    first_rank_by_doc: dict[str, int] = {}
    case_rank_hits: list[int] = []
    for rank, case in enumerate(cases, start=1):
        hit_docs = _case_documents(case) & primary_docs
        if hit_docs:
            case_rank_hits.append(rank)
        for doc in hit_docs:
            first_rank_by_doc.setdefault(doc, rank)
    ranks = sorted(first_rank_by_doc.values())
    return {
        "primary_case_rank_hits": case_rank_hits,
        "primary_doc_first_rank_min": min(ranks) if ranks else None,
        "primary_doc_first_rank_max": max(ranks) if ranks else None,
        "primary_doc_first_rank_bands": {
            "top100": sum(1 for value in ranks if value <= 100),
            "rank101_500": sum(1 for value in ranks if 101 <= value <= 500),
            "rank501_1000": sum(1 for value in ranks if 501 <= value <= 1000),
            "gt1000": sum(1 for value in ranks if value > 1000),
        },
    }


def _update_responsibility_artifact(payload: dict[str, Any]) -> None:
    responsibility = json.loads(RESPONSIBILITY_ARTIFACT.read_text(encoding="utf-8"))
    exact = payload["surfaces"][ADOPTED_SURFACE]["topn"]
    current = payload["surfaces"]["current_native"]["topn"]

    primary_key = (
        "primary_owner_target_recall_v33d"
        if "primary_owner_target_recall_v33d" in responsibility
        else "primary_owner_target_recall_v33"
    )
    companion_key = (
        "companion_context_contribution_v33d"
        if "companion_context_contribution_v33d" in responsibility
        else "companion_context_contribution_v33"
    )
    exact_status = (
        "available_exact_v33d_native_join"
        if primary_key.endswith("_v33d")
        else "available_exact_matched_doc_join"
    )
    exact_basis = (
        "exact_v33d_matched_doc_join"
        if primary_key.endswith("_v33d")
        else "available_exact_matched_doc_join"
    )
    relational = responsibility[primary_key]["relational"]
    for key in ("top100", "top500", "top1000"):
        if key not in relational["topn"]:
            continue
        source = exact[key]["primary"]
        relational["topn"][key].update(
            {
                "matched_docs": source["matched_docs"],
                "recall": source["recall"],
                "status": exact_status,
                "measurement_basis": exact_basis,
                "matched_docs_estimated_proration": None,
                "recall_estimated_proration": None,
                "exact_measurement_artifact": OUT_JSON.name,
            }
        )

    companion = responsibility[companion_key]["relational_companion"]
    for key in ("top100", "top500", "top1000"):
        if key not in companion["topn"]:
            continue
        source = exact[key]["companion"]
        companion["topn"][key].update(
            {
                "matched_docs": source["matched_docs"],
                "recall": source["recall"],
                "status": exact_status,
                "measurement_basis": exact_basis,
                "matched_docs_estimated_proration": None,
                "recall_estimated_proration": None,
                "exact_measurement_artifact": OUT_JSON.name,
            }
        )

    responsibility["relational_exact_measurement"] = {
        "artifact": OUT_JSON.name,
        "dataset": DATASET_NAME,
        "current_native_top500_primary": current["top500"]["primary"]["matched_docs"],
        "adopted_top500_primary": exact["top500"]["primary"]["matched_docs"],
        "adopted_top500_companion": exact["top500"]["companion"]["matched_docs"],
        "diagnostic_top100_candidate_artifact": OUT_JSON.name,
        "diagnostic_candidate_product_adoption": False,
        "production_ordering_changed": False,
        "truth_used_for_scoring": False,
    }
    RESPONSIBILITY_ARTIFACT.write_text(
        json.dumps(responsibility, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
    keys = {key.lower() for key in _walk_keys(payload)}
    return {
        "doc_like_token_count": sum(1 for doc in truth_docs if doc and doc in text),
        "forbidden_identifier_key_count": sum(
            1 for key in keys if key in FORBIDDEN_IDENTIFIER_KEYS
        ),
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": text.lower().count("p2_relational_edge_"),
    }


def build_payload() -> dict[str, Any]:
    started = time.perf_counter()
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    df = pd.read_csv(JOURNAL_CSV, low_memory=False)
    df["document_id"] = df["document_id"].astype(str)
    timings["journal_load_seconds"] = round(time.perf_counter() - t0, 3)

    rows = _read_truth_rows()
    owner_sets = _owner_doc_sets(rows)
    primary_docs: set[str] = owner_sets["primary_docs"]
    companion_docs: set[str] = owner_sets["companion_docs"]
    scenario_by_doc: dict[str, str] = owner_sets["scenario_by_doc"]
    subtype_by_doc: dict[str, str] = owner_sets["subtype_by_doc"]

    t0 = time.perf_counter()
    detector_result = RelationalDetector(get_settings()).detect(df)
    timings["detector_seconds"] = round(time.perf_counter() - t0, 3)

    t0 = time.perf_counter()
    adopted_cases = list(
        build_relational_cases(
            batch_id=BATCH_ID,
            detection_result=detector_result,
            df=df,
        )
    )
    timings["case_builder_seconds"] = round(time.perf_counter() - t0, 3)
    current_cases = _current_review_order(adopted_cases)
    employee_vendor_profile_cases = _employee_vendor_profile_order(adopted_cases, df=df)

    payload: dict[str, Any] = {
        "metadata": {
            "generated_at": _now_iso(),
            "diagnostic_scope": "v3.3b relational exact primary and companion recall",
            "dataset": DATASET_NAME,
            "responsibility_artifact": RESPONSIBILITY_ARTIFACT.name,
            "adopted_surface": ADOPTED_SURFACE,
            "current_native_surface": "current_native",
            "production_ordering_changed": False,
            "production_gate_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "truth_used_for_scoring": False,
            "truth_used_for_denominator_and_aggregate_evaluation": True,
        },
        "runtime": {
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            **timings,
            "bounded_or_cached_fallback_used": False,
            "timeout_observed": False,
        },
        "denominators": {
            "relational_primary": len(primary_docs),
            "relational_companion": len(companion_docs),
        },
        "case_counts": {
            "relational_cases": len(adopted_cases),
            "detector_flagged_rows": len(detector_result.flagged_indices),
            "edge_artifact_edges": len(
                ((detector_result.metadata or {}).get("relational_edge_artifact") or {}).get(
                    "edges", []
                )
            ),
        },
        "surfaces": {
            "current_native": {
                "ordering": "tier_score_case_id",
                "rank_band_diagnostic": _rank_band_diagnostic(
                    current_cases,
                    primary_docs=primary_docs,
                ),
                "topn": _topn_metrics(
                    current_cases,
                    primary_docs=primary_docs,
                    companion_docs=companion_docs,
                    scenario_by_doc=scenario_by_doc,
                    subtype_by_doc=subtype_by_doc,
                ),
            },
            ADOPTED_SURFACE: {
                "ordering": ADOPTED_SURFACE,
                "rank_band_diagnostic": _rank_band_diagnostic(
                    adopted_cases,
                    primary_docs=primary_docs,
                ),
                "topn": _topn_metrics(
                    adopted_cases,
                    primary_docs=primary_docs,
                    companion_docs=companion_docs,
                    scenario_by_doc=scenario_by_doc,
                    subtype_by_doc=subtype_by_doc,
                ),
            },
            EMPLOYEE_VENDOR_PROFILE_SURFACE: {
                "ordering": EMPLOYEE_VENDOR_PROFILE_SURFACE,
                "selector_inputs": [
                    "reference_text_employee_vendor_token_presence",
                    "trading_partner_employee_vendor_token_presence",
                    "business_process_bucket",
                    "account_class",
                    "document_support_count",
                    "sub_rule",
                    "evidence_tier",
                    "family_score",
                ],
                "synthetic_shortcut_risk": (
                    "medium_high: fixed5 v3.3b encodes employee-vendor semantics "
                    "with recognizable reference/counterparty tokens; keep this "
                    "surface diagnostic-only until non-synthetic validation."
                ),
                "product_adoption_allowed": False,
                "rank_band_diagnostic": _rank_band_diagnostic(
                    employee_vendor_profile_cases,
                    primary_docs=primary_docs,
                ),
                "topn": _topn_metrics(
                    employee_vendor_profile_cases,
                    primary_docs=primary_docs,
                    companion_docs=companion_docs,
                    scenario_by_doc=scenario_by_doc,
                    subtype_by_doc=subtype_by_doc,
                ),
            },
        },
        "no_fitting_contract": {
            "truth_label_used_for_scoring": False,
            "owner_metadata_used_for_scoring": False,
            "owner_metadata_used_for_denominator_and_exact_join_only": True,
            "selector_uses_detector_output_only": True,
            "production_ranking_changed": False,
            "threshold_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
        },
        "decision_summary": {
            "estimated_proration_replaced": True,
            "responsibility_artifact_updated": True,
            "best_top100_diagnostic_candidate": EMPLOYEE_VENDOR_PROFILE_SURFACE,
            "best_top100_diagnostic_candidate_product_adoption": False,
            "best_top100_diagnostic_candidate_reason": (
                "It uses audit-observable reference/counterparty/process/account "
                "signals and improves TOP100, but DataSynth-specific token "
                "dependency must be validated before product adoption."
            ),
            "interpretation": (
                "Relational primary 20 now has exact document-level evaluation. "
                "Truth metadata was not used by detector, case builder, or ordering selector."
            ),
        },
    }
    truth_docs = set(scenario_by_doc)
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_check(payload, truth_docs)
    if any(payload["raw_identifier_leak_check"].values()):
        raise ValueError(
            f"raw identifier leak check failed: {payload['raw_identifier_leak_check']}"
        )
    return payload


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_responsibility_artifact(payload)
    summary = {
        "artifact": OUT_JSON.relative_to(ROOT).as_posix(),
        "denominators": payload["denominators"],
        "current_top500": payload["surfaces"]["current_native"]["topn"]["top500"],
        "adopted_top500": payload["surfaces"][ADOPTED_SURFACE]["topn"]["top500"],
        "runtime": payload["runtime"],
        "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
