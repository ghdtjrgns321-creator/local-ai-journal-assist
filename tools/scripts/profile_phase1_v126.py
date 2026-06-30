"""Profile PHASE1 execution on DataSynth v126 in explicit stages.

This runner is intentionally verbose and checkpointed. It avoids calling the
full pipeline as one opaque block so long-running stages can be identified.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_audit_rules, get_risk_keywords, get_settings
from src.detection.anomaly_layer import AnomalyDetector
from src.detection.benford_detector import BenfordDetector
from src.detection.fraud_layer import FraudLayer
from src.detection.fraud_rules_access import build_access_rule_cache
from src.detection.fraud_rules_groupby import (
    _flag_exact_duplicate_entries,
    _flag_o2c_offset_duplicate_entries,
    _flag_reference_duplicate_entries,
    _prepare_duplicate_entry_work,
    _score_l203_duplicate_entries,
)
from src.detection.integrity_layer import IntegrityDetector
from src.detection.phase1_case_builder import (
    SCHEMA_VERSION,
    _build_cases,
    _build_macro_findings,
    _build_theme_summaries,
    _collect_raw_hits_profiled,
    build_phase1_case_run_id,
    save_phase1_case_result,
)
from src.detection.score_aggregator import aggregate_scores
from src.feature.engine import FeatureCategory, _run_category
from src.ingest.datasynth_labels import apply_datasynth_label_mode, set_source_path
from src.models.phase1_case import Phase1CaseResult
from src.services.analysis_service import make_phase_settings

DATE_COLUMNS = ("posting_date", "document_date", "entry_date", "approval_date", "created_at")
PHASE1_USECOLS = {
    "document_id",
    "company_code",
    "fiscal_year",
    "fiscal_period",
    "posting_date",
    "document_date",
    "document_type",
    "currency",
    "reference",
    "header_text",
    "created_by",
    "user_persona",
    "source",
    # Why: L4-06 lone_batch_identity(source 위장 의심)가 배치 정체성 검증에 사용 (2026-06-12)
    "batch_id",
    "job_id",
    "business_process",
    "semantic_scenario_id",
    "semantic_account_subtype",
    "counterparty_type",
    "approved_by",
    "approval_date",
    "base_event_type",
    "mutation_type",
    "mutated_field",
    "mutation_reason",
    "detection_surface_hints",
    "sod_violation",
    "sod_conflict_type",
    "has_attachment",
    "supporting_doc_type",
    "delivery_date",
    "invoice_amount",
    "supply_amount",
    "document_number",
    "line_number",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "local_amount",
    "cost_center",
    "profit_center",
    "line_text",
    "trading_partner",
    "auxiliary_account_number",
    "auxiliary_account_label",
    "lettrage",
    "lettrage_date",
    "amount_open",
    "is_cleared",
    "settlement_status",
    "settlement_date",
    "description_quality",
    "exceeds_threshold",
}
PHASE1_CATEGORIES = (
    FeatureCategory.TIME,
    FeatureCategory.AMOUNT,
    FeatureCategory.PATTERN,
    FeatureCategory.TEXT,
)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(message: str) -> None:
    print(f"[{_now()}] {message}", flush=True)


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 3)


def _read_data(data_dir: Path, checkpoint: Path, summary: dict[str, Any]) -> pd.DataFrame:
    source = data_dir / "journal_entries.csv"
    t0 = time.perf_counter()
    _log(f"read_csv start: {source}")
    df = pd.read_csv(source, usecols=lambda column: column in PHASE1_USECOLS, low_memory=False)
    for column in DATE_COLUMNS:
        if column in df.columns:
            # Why: 한 컬럼에 date_only("2024-12-31")와 datetime("2024-12-31 18:10:00")이
            #      섞이면 format 미지정 to_datetime이 다수 형식으로 추론해 소수를 NaT로 만든다
            #      (예: document_date 시각 포함 행 → 거짓 L1-02 필수필드 누락). ISO8601은
            #      시각 유무 모두 파싱하므로 혼합 형식에 견고하다.
            df[column] = pd.to_datetime(df[column], errors="coerce", format="ISO8601")
    df = set_source_path(df, source)
    summary["stages"]["read_csv"] = {
        "elapsed_sec": _elapsed(t0),
        "rows": int(len(df)),
        "documents": int(df["document_id"].nunique()) if "document_id" in df.columns else None,
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"read_csv done: {summary['stages']['read_csv']}")
    df = _enrich_independent_audit_evidence(df, data_dir, checkpoint=checkpoint, summary=summary)
    return df


def _enrich_independent_audit_evidence(
    df: pd.DataFrame,
    data_dir: Path,
    *,
    checkpoint: Path,
    summary: dict[str, Any],
) -> pd.DataFrame:
    t0 = time.perf_counter()
    _log("independent evidence enrichment start")
    vendor_master = _load_partner_master(data_dir / "master_data" / "vendors.json", "vendor_id")
    customer_master = _load_partner_master(
        data_dir / "master_data" / "customers.json",
        "customer_id",
    )
    flow_doc_ids = _load_document_flow_ids(data_dir / "document_flows")
    ic_refs, ic_docs = _load_intercompany_reference_sets(data_dir / "intercompany")
    employee_master = _load_employee_master(data_dir / "master_data" / "employees.json")

    partner = _first_nonblank_series(df, ["auxiliary_account_number", "trading_partner"])
    partner_upper = partner.str.upper()
    vendor_known = partner_upper.isin(vendor_master["ids"])
    customer_known = partner_upper.isin(customer_master["ids"])
    df["master_counterparty_known"] = vendor_known | customer_known
    df["master_counterparty_inactive"] = partner_upper.isin(
        vendor_master["inactive"] | customer_master["inactive"]
    )
    df["master_counterparty_intercompany"] = partner_upper.isin(
        vendor_master["intercompany"] | customer_master["intercompany"]
    )

    reference_doc = _reference_document_id(df.get("reference"))
    reference_upper = reference_doc.str.upper()
    df["document_flow_linked"] = reference_upper.isin(flow_doc_ids)
    has_flow_prefix = reference_upper.str.match(r"^(PO|GR|VI|PAY|SO|CI|DLV)-", na=False)
    df["document_flow_orphan"] = has_flow_prefix & ~df["document_flow_linked"]

    raw_reference = _string_series(df.get("reference")).str.upper()
    df["ic_matched_pair_found"] = raw_reference.isin(ic_refs) | reference_upper.isin(ic_docs)
    has_ic_reference = raw_reference.str.match(r"^IC\d+", na=False) | reference_upper.str.match(
        r"^(ICS|ICB)\d+",
        na=False,
    )
    df["ic_unmatched_reference"] = has_ic_reference & ~df["ic_matched_pair_found"]

    approver = _string_series(df.get("approved_by")).str.upper()
    creator = _string_series(df.get("created_by")).str.upper()
    company = _string_series(df.get("company_code")).str.upper()
    doc_amount = (
        pd.to_numeric(df.get("local_amount", pd.Series(0.0, index=df.index)), errors="coerce")
        .fillna(0.0)
        .abs()
    )
    if "document_id" in df.columns:
        doc_amount = doc_amount.groupby(df["document_id"].astype(str)).transform("sum")
    approver_known = approver.isin(employee_master["ids"])
    creator_known = creator.isin(employee_master["ids"])
    can_approve_je = approver.map(employee_master["can_approve_je"]).fillna(False).astype(bool)
    approval_limit = pd.to_numeric(
        approver.map(employee_master["approval_limit"]),
        errors="coerce",
    ).fillna(0.0)
    authorized_companies = approver.map(employee_master["authorized_companies"]).fillna("")
    company_authorized = [
        bool(comp) and (comp in str(auth).split("|"))
        for comp, auth in zip(company.to_numpy(), authorized_companies.to_numpy(), strict=False)
    ]
    manual_creator = ~creator.str.startswith("SYSTEM", na=False)
    missing_approver = approver.eq("") | approver.isin({"NAN", "NONE", "NULL"})
    self_approval = creator.ne("") & creator.eq(approver)
    manual_creator_present = (
        manual_creator & creator.ne("") & ~creator.isin({"NAN", "NONE", "NULL"})
    )
    approver_present = ~missing_approver
    creator_join_rows = int(manual_creator_present.sum())
    creator_known_rows = int((manual_creator_present & creator_known).sum())
    approver_present_rows = int(approver_present.sum())
    approver_known_rows = int((approver_present & approver_known).sum())
    creator_join_rate = creator_known_rows / creator_join_rows if creator_join_rows else 1.0
    approver_join_rate = (
        approver_known_rows / approver_present_rows if approver_present_rows else 1.0
    )
    approval_contract_degraded = (
        not employee_master["ids"]
        or creator_join_rate < 0.95
        or (approver_present_rows > 0 and approver_join_rate < 0.95)
    )
    raw_approval_matrix_gap = manual_creator & (
        missing_approver
        | self_approval
        | (~approver_known & ~missing_approver)
        | (~can_approve_je & ~missing_approver)
        | (~pd.Series(company_authorized, index=df.index) & ~missing_approver)
    )
    df["approval_contract_degraded"] = approval_contract_degraded
    df["approval_contract_gap"] = raw_approval_matrix_gap
    df["employee_creator_join_gap"] = manual_creator_present & ~creator_known
    df["employee_approver_join_gap"] = approver_present & ~approver_known
    df["approval_matrix_gap"] = (
        pd.Series(False, index=df.index, dtype=bool)
        if approval_contract_degraded
        else raw_approval_matrix_gap
    )
    df["approval_limit_exceeded_independent"] = (
        manual_creator
        & ~missing_approver
        & approval_limit.gt(0)
        & doc_amount.gt(approval_limit)
        & ~approval_contract_degraded
    )

    summary["stages"]["independent_evidence_enrichment"] = {
        "elapsed_sec": _elapsed(t0),
        "known_counterparty_rows": int(df["master_counterparty_known"].sum()),
        "document_flow_orphan_rows": int(df["document_flow_orphan"].sum()),
        "ic_unmatched_rows": int(df["ic_unmatched_reference"].sum()),
        "approval_matrix_gap_rows": int(df["approval_matrix_gap"].sum()),
        "approval_contract_gap_rows": int(df["approval_contract_gap"].sum()),
        "employee_creator_join_gap_rows": int(df["employee_creator_join_gap"].sum()),
        "employee_approver_join_gap_rows": int(df["employee_approver_join_gap"].sum()),
        "employee_creator_join_rate": round(float(creator_join_rate), 6),
        "employee_approver_join_rate": round(float(approver_join_rate), 6),
        "approval_contract_degraded": bool(approval_contract_degraded),
        "approval_contract_degraded_reason": (
            "employee/user approval master join coverage below 95%"
            if approval_contract_degraded
            else ""
        ),
        "approval_limit_exceeded_rows": int(df["approval_limit_exceeded_independent"].sum()),
    }
    _write_checkpoint(checkpoint, summary)
    _log(
        "independent evidence enrichment done: "
        f"{summary['stages']['independent_evidence_enrichment']}"
    )
    return df


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _load_partner_master(path: Path, id_field: str) -> dict[str, set[str]]:
    ids: set[str] = set()
    inactive: set[str] = set()
    intercompany: set[str] = set()
    for row in _load_json_list(path):
        partner_id = str(row.get(id_field) or "").strip().upper()
        intercompany_code = str(row.get("intercompany_code") or "").strip().upper()
        if not partner_id and not intercompany_code:
            continue
        if partner_id:
            ids.add(partner_id)
        if intercompany_code:
            ids.add(intercompany_code)
        if not bool(row.get("is_active", True)):
            if partner_id:
                inactive.add(partner_id)
            if intercompany_code:
                inactive.add(intercompany_code)
        if bool(row.get("is_intercompany", False)):
            if partner_id:
                intercompany.add(partner_id)
            if intercompany_code:
                intercompany.add(intercompany_code)
    return {"ids": ids, "inactive": inactive, "intercompany": intercompany}


def _load_document_flow_ids(flow_dir: Path) -> set[str]:
    ids: set[str] = set()
    for path in flow_dir.glob("*.json"):
        for row in _load_json_list(path):
            header = row.get("header") if isinstance(row.get("header"), dict) else {}
            document_id = str(header.get("document_id") or "").strip().upper()
            if document_id:
                ids.add(document_id)
            for ref in header.get("document_references") or []:
                if not isinstance(ref, dict):
                    continue
                for key in ("source_doc_id", "target_doc_id"):
                    ref_id = str(ref.get(key) or "").strip().upper()
                    if ref_id:
                        ids.add(ref_id)
    return ids


def _load_intercompany_reference_sets(ic_dir: Path) -> tuple[set[str], set[str]]:
    refs: set[str] = set()
    docs: set[str] = set()
    matched_pairs = _load_json_list(ic_dir / "ic_matched_pairs.json")
    for row in matched_pairs:
        ref = str(row.get("ic_reference") or "").strip().upper()
        if ref:
            refs.add(ref)
        for key in ("seller_document", "buyer_document"):
            doc_id = str(row.get(key) or "").strip().upper()
            if doc_id:
                docs.add(doc_id)
    for path in (
        ic_dir / "ic_seller_journal_entries.json",
        ic_dir / "ic_buyer_journal_entries.json",
    ):
        for row in _load_json_list(path):
            header = row.get("header") if isinstance(row.get("header"), dict) else {}
            doc_id = str(header.get("document_id") or "").strip().upper()
            ref = str(header.get("reference") or "").strip().upper()
            if doc_id:
                docs.add(doc_id)
            if ref:
                refs.add(ref)
    return refs, docs


def _load_employee_master(path: Path) -> dict[str, Any]:
    ids: set[str] = set()
    can_approve_je: dict[str, bool] = {}
    approval_limit: dict[str, float] = {}
    authorized_companies: dict[str, str] = {}
    for row in _load_json_list(path):
        user_id = str(row.get("user_id") or "").strip().upper()
        if not user_id:
            continue
        ids.add(user_id)
        can_approve_je[user_id] = bool(row.get("can_approve_je", False))
        try:
            approval_limit[user_id] = float(row.get("approval_limit") or 0.0)
        except (TypeError, ValueError):
            approval_limit[user_id] = 0.0
        companies = [
            str(value).strip().upper() for value in row.get("authorized_company_codes") or []
        ]
        authorized_companies[user_id] = "|".join(company for company in companies if company)
    return {
        "ids": ids,
        "can_approve_je": can_approve_je,
        "approval_limit": approval_limit,
        "authorized_companies": authorized_companies,
    }


def _first_nonblank_series(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    result = pd.Series("", index=df.index, dtype="string")
    for column in columns:
        if column not in df.columns:
            continue
        candidate = _string_series(df[column])
        result = result.mask(result.str.strip().eq(""), candidate)
    return result.fillna("").astype(str)


def _string_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="string")
    return series.fillna("").astype(str).str.strip()


def _reference_document_id(series: pd.Series | None) -> pd.Series:
    reference = _string_series(series).str.upper()
    return reference.str.replace(r"^[A-Z0-9_]+:", "", regex=True).str.strip()


def _run_features(
    df: pd.DataFrame,
    *,
    settings,
    audit_rules: dict,
    risk_keywords: dict,
    checkpoint: Path,
    summary: dict[str, Any],
) -> pd.DataFrame:
    raw_rules = audit_rules
    pattern_rules = audit_rules.get("patterns", audit_rules)
    summary["stages"].setdefault("features", {})

    for category in PHASE1_CATEGORIES:
        warnings: list[str] = []
        t0 = time.perf_counter()
        _log(f"feature start: {category.value}")
        success = _run_category(
            df,
            category,
            settings=settings,
            rules=pattern_rules,
            raw_rules=raw_rules,
            risk_keywords=risk_keywords,
            include_morpheme_tokens=False,
            warnings_out=warnings,
        )
        summary["stages"]["features"][category.value] = {
            "elapsed_sec": _elapsed(t0),
            "success": bool(success),
            "warnings": warnings[:20],
            "columns": int(len(df.columns)),
        }
        _write_checkpoint(checkpoint, summary)
        _log(f"feature done: {category.value} {summary['stages']['features'][category.value]}")
    return df


def _run_detectors(
    df: pd.DataFrame,
    *,
    settings,
    audit_rules: dict,
    checkpoint: Path,
    summary: dict[str, Any],
):
    detectors = [
        IntegrityDetector(settings, audit_rules=audit_rules),
        FraudLayer(settings, audit_rules=audit_rules),
        AnomalyDetector(settings, audit_rules=audit_rules),
        BenfordDetector(settings),
    ]
    results = []
    summary["stages"].setdefault("detectors", {})
    for detector in detectors:
        t0 = time.perf_counter()
        _log(f"detector start: {detector.track_name}")
        if isinstance(detector, FraudLayer):
            result = _run_fraud_layer_rule_by_rule(
                detector,
                df,
                checkpoint=checkpoint,
                summary=summary,
            )
        elif isinstance(detector, AnomalyDetector):
            result = _run_anomaly_layer_rule_by_rule(
                detector,
                df,
                checkpoint=checkpoint,
                summary=summary,
            )
        else:
            result = detector.detect(df)
        results.append(result)
        summary["stages"]["detectors"][detector.track_name] = {
            "elapsed_sec": _elapsed(t0),
            "flagged_count": int(result.flagged_count),
            "rules_run": int(result.total_rules_run),
            "warnings": list(result.warnings or [])[:20],
        }
        _write_checkpoint(checkpoint, summary)
        _log(
            f"detector done: {detector.track_name} {summary['stages']['detectors'][detector.track_name]}"
        )
    return results


def _run_anomaly_layer_rule_by_rule(
    detector: AnomalyDetector,
    df: pd.DataFrame,
    *,
    checkpoint: Path,
    summary: dict[str, Any],
):
    warnings: list[str] = []
    skipped: list[str] = []
    rule_results: dict[str, pd.Series] = {}
    layer_start = time.perf_counter()

    summary["stages"].setdefault("detector_rules", {}).setdefault("layer_c", {})
    for rule_id, func, kwargs in detector._build_registry():  # noqa: SLF001 - profiler only
        t0 = time.perf_counter()
        _log(f"layer_c rule start: {rule_id}")
        try:
            flagged = func(df, **kwargs)
            rule_results[rule_id] = flagged
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            max_score = float(pd.Series(score_series).max()) if score_series is not None else None
            summary["stages"]["detector_rules"]["layer_c"][rule_id] = {
                "elapsed_sec": _elapsed(t0),
                "status": "ok",
                "flagged_rows": int(pd.Series(flagged).fillna(False).astype(bool).sum()),
                "max_score": max_score,
            }
        except Exception as exc:
            skipped.append(rule_id)
            warnings.append(f"{rule_id} failed: {exc}")
            summary["stages"]["detector_rules"]["layer_c"][rule_id] = {
                "elapsed_sec": _elapsed(t0),
                "status": "failed",
                "error": repr(exc),
            }
        _write_checkpoint(checkpoint, summary)
        _log(
            f"layer_c rule done: {rule_id} {summary['stages']['detector_rules']['layer_c'][rule_id]}"
        )

    elapsed = time.perf_counter() - layer_start
    return detector._build_result(df, rule_results, skipped, warnings, elapsed)  # noqa: SLF001


def _run_fraud_layer_rule_by_rule(
    detector: FraudLayer,
    df: pd.DataFrame,
    *,
    checkpoint: Path,
    summary: dict[str, Any],
):
    """Run FraudLayer internals one rule at a time for bottleneck isolation."""

    warnings: list[str] = []
    skipped: list[str] = []
    coverage_issues: list[dict[str, Any]] = []
    rule_results: dict[str, pd.Series] = {}
    access_cache = build_access_rule_cache(df)
    layer_start = time.perf_counter()

    summary["stages"].setdefault("detector_rules", {}).setdefault("layer_b", {})
    for rule_id, func, kwargs in detector._build_registry():  # noqa: SLF001 - profiler only
        missing_inputs = detector._missing_inputs(rule_id, df)  # noqa: SLF001 - profiler only
        if missing_inputs:
            skipped.append(rule_id)
            warnings.append(f"{rule_id} skipped: missing inputs {missing_inputs}")
            summary["stages"]["detector_rules"]["layer_b"][rule_id] = {
                "elapsed_sec": 0.0,
                "status": "skipped",
                "missing_inputs": missing_inputs,
            }
            _write_checkpoint(checkpoint, summary)
            continue

        t0 = time.perf_counter()
        _log(f"layer_b rule start: {rule_id}")
        try:
            if rule_id in {"L1-05", "L1-06", "L1-07", "L1-09"}:
                kwargs = {**kwargs, "cache": access_cache}
            if rule_id == "L2-03":
                flagged = _profile_l203_duplicate_entry(
                    df,
                    checkpoint=checkpoint,
                    summary=summary,
                    **kwargs,
                )
            else:
                flagged = func(df, **kwargs)
            rule_results[rule_id] = flagged
            coverage_issues.extend(detector._coverage_issues(rule_id, df))  # noqa: SLF001
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            max_score = float(pd.Series(score_series).max()) if score_series is not None else None
            summary["stages"]["detector_rules"]["layer_b"][rule_id] = {
                "elapsed_sec": _elapsed(t0),
                "status": "ok",
                "flagged_rows": int(pd.Series(flagged).fillna(False).astype(bool).sum()),
                "max_score": max_score,
            }
        except Exception as exc:
            skipped.append(rule_id)
            warnings.append(f"{rule_id} failed: {exc}")
            summary["stages"]["detector_rules"]["layer_b"][rule_id] = {
                "elapsed_sec": _elapsed(t0),
                "status": "failed",
                "error": repr(exc),
            }
        _write_checkpoint(checkpoint, summary)
        _log(
            f"layer_b rule done: {rule_id} {summary['stages']['detector_rules']['layer_b'][rule_id]}"
        )

    elapsed = time.perf_counter() - layer_start
    return detector._build_result(  # noqa: SLF001 - profiler only
        df=df,
        rule_results=rule_results,
        skipped=skipped,
        warnings=warnings,
        elapsed=elapsed,
        coverage_issues=coverage_issues,
    )


def _profile_l203_duplicate_entry(
    df: pd.DataFrame,
    *,
    checkpoint: Path,
    summary: dict[str, Any],
    amount_tolerance: float = 0.02,
    fuzzy_threshold: int = 80,
    window_days: int = 7,
    split_window_days: int = 3,
    max_group_size: int = 1000,
    reference_max_frequency_ratio: float = 0.10,
    reference_min_unique_ratio: float = 0.40,
    reference_nonunique_min_count: int = 2,
) -> pd.Series:
    """Profile L2-03 duplicate-entry substeps and return a compatible Series."""

    summary["stages"].setdefault("detector_rule_steps", {}).setdefault("L2-03", {})

    def run_step(name: str, fn):
        t0 = time.perf_counter()
        _log(f"L2-03 step start: {name}")
        value = fn()
        if isinstance(value, pd.DataFrame):
            nonzero_rows = len(value)
            extra = {"columns": int(len(value.columns))}
        else:
            series = pd.Series(value, index=df.index)
            nonzero_rows = int(pd.to_numeric(series, errors="coerce").fillna(0.0).gt(0).sum())
            extra = {}
        summary["stages"]["detector_rule_steps"]["L2-03"][name] = {
            "elapsed_sec": _elapsed(t0),
            "nonzero_rows": nonzero_rows,
            **extra,
        }
        _write_checkpoint(checkpoint, summary)
        _log(f"L2-03 step done: {name} {summary['stages']['detector_rule_steps']['L2-03'][name]}")
        return value

    work = run_step("prepare_work", lambda: _prepare_duplicate_entry_work(df))
    # 2026-06-21: fraud_rules_groupby no longer exposes the legacy
    # document/near/split/IC helper functions. Keep profiler output compatible
    # with historical reports by recording those retired paths as empty, while
    # measuring the active L2-03 exact/reference/O2C-offset paths from the
    # production module.
    empty_scores = pd.Series(0.0, index=df.index)
    document_scores = run_step("document_duplicate_retired", lambda: empty_scores)
    exact_scores = run_step("exact_duplicate", lambda: _flag_exact_duplicate_entries(work))
    reference_scores = run_step(
        "reference_duplicate",
        lambda: _flag_reference_duplicate_entries(
            work,
            amount_tolerance=amount_tolerance,
            reference_max_frequency_ratio=reference_max_frequency_ratio,
            reference_min_unique_ratio=reference_min_unique_ratio,
            reference_nonunique_min_count=reference_nonunique_min_count,
        ),
    )
    near_scores = run_step("near_duplicate_retired", lambda: empty_scores)
    split_scores = run_step("split_duplicate_retired", lambda: empty_scores)
    o2c_offset_scores = run_step(
        "o2c_offset_duplicate",
        lambda: _flag_o2c_offset_duplicate_entries(work, df),
    )
    ic_split_scores = run_step("ic_split_duplicate_retired", lambda: empty_scores)

    t0 = time.perf_counter()
    _log("L2-03 step start: combine")
    score_frame = pd.DataFrame(
        {
            "document_duplicate": document_scores,
            "exact_duplicate": exact_scores,
            "reference_duplicate": reference_scores,
            "near_duplicate": near_scores,
            "split_duplicate": split_scores,
            "o2c_offset_duplicate": o2c_offset_scores,
            "ic_split_duplicate": ic_split_scores,
        },
        index=df.index,
    )
    confidence = score_frame.max(axis=1).fillna(0.0)
    result = confidence > 0
    score_series = _score_l203_duplicate_entries(df, result, confidence, score_frame)

    reason_counts: dict[str, int] = {}
    confidence_band_counts = {"high": 0, "medium": 0, "low": 0, "population": 0}
    row_annotations: dict[object, dict[str, object]] = {}
    for idx in confidence[confidence > 0].index:
        row_scores = score_frame.loc[idx]
        matched = row_scores[row_scores > 0].sort_values(ascending=False)
        primary_reason = str(matched.index[0])
        primary_confidence = float(matched.iloc[0])
        score = float(score_series.loc[idx])
        if score >= 0.85:
            confidence_band = "high"
        elif score >= 0.35:
            confidence_band = "medium"
        elif score > 0:
            confidence_band = "low"
        else:
            confidence_band = "population"
        reason_counts[primary_reason] = reason_counts.get(primary_reason, 0) + 1
        confidence_band_counts[confidence_band] += 1
        row_annotations[idx] = {
            "reason_code": primary_reason,
            "matched_reason_codes": matched.index.tolist(),
            "raw_confidence": round(primary_confidence, 4),
            "confidence": round(score, 4),
            "confidence_band": confidence_band,
        }

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "flagged_rows": int(result.sum()),
        "scored_rows": int(score_series.gt(0).sum()),
        "zero_score_rows": int((result & score_series.eq(0)).sum()),
        "reason_counts": reason_counts,
        "confidence_band_counts": confidence_band_counts,
    }
    result.attrs["row_annotations"] = row_annotations
    summary["stages"]["detector_rule_steps"]["L2-03"]["combine"] = {
        "elapsed_sec": _elapsed(t0),
        "nonzero_rows": int(result.sum()),
        "scored_rows": int(score_series.gt(0).sum()),
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"L2-03 step done: combine {summary['stages']['detector_rule_steps']['L2-03']['combine']}")
    return result


def _aggregate_and_case(
    df: pd.DataFrame,
    results,
    *,
    settings,
    data_dir: Path,
    checkpoint: Path,
    summary: dict[str, Any],
    cache_path: Path | None = None,
    stop_after_cache: bool = False,
    batch_id: str = "datasynth_v126_profiled_phase1",
) -> pd.DataFrame:
    t0 = time.perf_counter()
    _log("aggregate start")
    agg_df = aggregate_scores(df, results, settings=settings)
    for col in agg_df.columns:
        df[col] = agg_df[col].values
    summary["stages"]["aggregate"] = {
        "elapsed_sec": _elapsed(t0),
        "risk_summary": {
            str(k): int(v) for k, v in df["risk_level"].value_counts().to_dict().items()
        }
        if "risk_level" in df.columns
        else {},
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"aggregate done: {summary['stages']['aggregate']}")

    if cache_path is not None:
        _save_case_input_cache(
            cache_path,
            df=df,
            results=results,
            data_dir=data_dir,
            summary=summary,
        )
        summary["stages"]["case_input_cache"] = {
            "path": str(cache_path),
            "rows": int(len(df)),
            "results": int(len(results)),
        }
        _write_checkpoint(checkpoint, summary)
        _log(f"case input cache saved: {summary['stages']['case_input_cache']}")
    if stop_after_cache:
        return df

    _run_case_builder_only(
        df,
        results,
        data_dir=data_dir,
        checkpoint=checkpoint,
        summary=summary,
        batch_id=batch_id,
    )
    return df


def _run_case_builder_only(
    df: pd.DataFrame,
    results,
    *,
    data_dir: Path,
    checkpoint: Path,
    summary: dict[str, Any],
    batch_id: str = "datasynth_v126_profiled_phase1",
) -> Phase1CaseResult:
    t0 = time.perf_counter()
    _log("phase1 case builder start")
    phase1_result = _profile_phase1_case_builder(
        df,
        results,
        company_id="_anonymous",
        batch_id=batch_id,
        dataset_id=str(data_dir),
        phase1_case_config={"phase1_case": {}},
        checkpoint=checkpoint,
        summary=summary,
    )
    artifact_path = save_phase1_case_result(phase1_result)
    summary["stages"]["phase1_case_builder"] = {
        "elapsed_sec": _elapsed(t0),
        "case_count": len(phase1_result.cases),
        "macro_finding_count": int(phase1_result.metadata.get("macro_finding_count", 0) or 0),
        "artifact_path": str(artifact_path),
        "theme_summaries": [theme.model_dump() for theme in phase1_result.theme_summaries],
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"phase1 case builder done: {summary['stages']['phase1_case_builder']}")
    _evaluate_manipulated_cases(
        phase1_result,
        data_dir=data_dir,
        checkpoint=checkpoint,
        summary=summary,
    )
    return phase1_result


def _save_case_input_cache(
    path: Path,
    *,
    df: pd.DataFrame,
    results,
    data_dir: Path,
    summary: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        pickle.dump(
            {
                "df": df,
                "results": results,
                "data_dir": str(data_dir),
                "source_summary": summary,
                "created_at": _now(),
            },
            file,
            protocol=pickle.HIGHEST_PROTOCOL,
        )


def _load_case_input_cache(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        payload = pickle.load(file)
    if not isinstance(payload, dict) or "df" not in payload or "results" not in payload:
        raise ValueError(f"Invalid case input cache: {path}")
    return payload


def _profile_phase1_case_builder(
    df: pd.DataFrame,
    results,
    *,
    company_id: str,
    batch_id: str | None,
    dataset_id: str | None,
    phase1_case_config: dict[str, Any] | None,
    checkpoint: Path,
    summary: dict[str, Any],
) -> Phase1CaseResult:
    config = (phase1_case_config or {}).get("phase1_case", {})
    generated_at = datetime.now(UTC)
    run_id = build_phase1_case_run_id(
        company_id=company_id,
        batch_id=batch_id,
        dataset_id=dataset_id,
        generated_at=generated_at,
    )
    summary["stages"].setdefault("phase1_case_builder_steps", {})

    t0 = time.perf_counter()
    macro_findings = _build_macro_findings(
        results,
        df=df,
        top_n=int(config.get("top_n_macro_findings", 100)),
    )
    summary["stages"]["phase1_case_builder_steps"]["macro_findings"] = {
        "elapsed_sec": _elapsed(t0),
        "count": len(macro_findings),
    }
    _write_checkpoint(checkpoint, summary)
    _log(
        "phase1 case step done: macro_findings "
        f"{summary['stages']['phase1_case_builder_steps']['macro_findings']}"
    )

    t0 = time.perf_counter()

    def _raw_hit_step(step_name: str, payload: dict[str, Any]) -> None:
        summary["stages"]["phase1_case_builder_steps"][step_name] = payload
        _write_checkpoint(checkpoint, summary)
        _log(f"phase1 case step done: {step_name} {payload}")

    raw_hits = _collect_raw_hits_profiled(
        df,
        results,
        profile_callback=_raw_hit_step,
    )
    summary["stages"]["phase1_case_builder_steps"]["collect_raw_hits"] = {
        "elapsed_sec": _elapsed(t0),
        "count": len(raw_hits),
    }
    _write_checkpoint(checkpoint, summary)
    _log(
        "phase1 case step done: collect_raw_hits "
        f"{summary['stages']['phase1_case_builder_steps']['collect_raw_hits']}"
    )

    t0 = time.perf_counter()

    def _case_step(step_name: str, payload: dict[str, Any]) -> None:
        summary["stages"]["phase1_case_builder_steps"][step_name] = payload
        _write_checkpoint(checkpoint, summary)
        _log(f"phase1 case step done: {step_name} {payload}")

    cases = _build_cases(
        df,
        raw_hits,
        config,
        macro_findings,
        profile_callback=_case_step,
    )
    summary["stages"]["phase1_case_builder_steps"]["build_cases"] = {
        "elapsed_sec": _elapsed(t0),
        "count": len(cases),
    }
    _write_checkpoint(checkpoint, summary)
    _log(
        "phase1 case step done: build_cases "
        f"{summary['stages']['phase1_case_builder_steps']['build_cases']}"
    )

    t0 = time.perf_counter()
    theme_summaries = _build_theme_summaries(cases, int(config.get("top_n_per_theme", 10)))
    summary["stages"]["phase1_case_builder_steps"]["theme_summaries"] = {
        "elapsed_sec": _elapsed(t0),
        "count": len(theme_summaries),
    }
    _write_checkpoint(checkpoint, summary)
    _log(
        "phase1 case step done: theme_summaries "
        f"{summary['stages']['phase1_case_builder_steps']['theme_summaries']}"
    )

    return Phase1CaseResult(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        company_id=company_id,
        dataset_id=dataset_id,
        batch_id=batch_id,
        generated_at=generated_at,
        top_n_cases=int(config.get("top_n_cases", 50)),
        top_n_per_theme=int(config.get("top_n_per_theme", 10)),
        theme_summaries=theme_summaries,
        cases=cases,
        raw_rule_reference={
            "source": "detection_results",
            "track_names": [result.track_name for result in results],
        },
        metadata={
            "phase1_case_config_version": SCHEMA_VERSION,
            "score_cutoff": {
                "high": float(config.get("priority_band", {}).get("high", 0.75)),
                "medium": float(config.get("priority_band", {}).get("medium", 0.45)),
            },
            "grouping_window": {
                "near_period_days": int(config.get("near_period_days", 7)),
                "period_end_window_days": int(config.get("period_end_window_days", 5)),
            },
            "macro_findings": macro_findings,
            "macro_finding_count": len(macro_findings),
            "macro_finding_policy": (
                "L4-02/D01/D02/GR01/GR03 are Account/Process Queue findings. They do not create "
                "transaction queue priority_score or row-level anomaly_score by themselves."
            ),
        },
    )


def _evaluate_manipulated(
    df: pd.DataFrame,
    *,
    data_dir: Path,
    checkpoint: Path,
    summary: dict[str, Any],
) -> None:
    truth_path = data_dir / "labels" / "manipulated_entry_truth.csv"
    if not truth_path.exists():
        summary["stages"]["manipulated_eval"] = {"error": f"missing {truth_path}"}
        _write_checkpoint(checkpoint, summary)
        return

    t0 = time.perf_counter()
    _log("manipulated eval start")
    truth = pd.read_csv(truth_path, dtype=str, low_memory=False)
    truth_docs = set(truth["document_id"].dropna().astype(str).unique())
    score = pd.to_numeric(
        df.get("anomaly_score", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    score_docs = set(df.loc[score.gt(0), "document_id"].dropna().astype(str).unique())
    risk_doc_counts: dict[str, int] = {}
    risk_truth_counts: dict[str, int] = {}
    if "risk_level" in df.columns:
        for risk_level, group in df.groupby("risk_level"):
            docs = set(group["document_id"].dropna().astype(str).unique())
            risk_doc_counts[str(risk_level)] = len(docs)
            risk_truth_counts[str(risk_level)] = len(docs & truth_docs)
    rule_docs: set[str] = set()
    for column in ("flagged_rules", "review_rules"):
        if column in df.columns:
            rule_docs |= set(
                df.loc[df[column].fillna("").astype(str).str.len().gt(0), "document_id"]
                .dropna()
                .astype(str)
                .unique()
            )

    scenario_col = "scenario" if "scenario" in truth.columns else "fraud_scenario"
    scenarios = []
    if scenario_col in truth.columns:
        for scenario, group in truth.groupby(scenario_col):
            docs = set(group["document_id"].dropna().astype(str).unique())
            scenarios.append(
                {
                    "scenario": str(scenario),
                    "total": len(docs),
                    "score_gt0": len(docs & score_docs),
                    "rule_or_review_hit": len(docs & rule_docs),
                    "miss_score_gt0": len(docs - score_docs),
                }
            )

    summary["stages"]["manipulated_eval"] = {
        "elapsed_sec": _elapsed(t0),
        "total_docs": len(truth_docs),
        "score_gt0_docs": len(truth_docs & score_docs),
        "rule_or_review_hit_docs": len(truth_docs & rule_docs),
        "miss_score_gt0_docs": len(truth_docs - score_docs),
        "risk_doc_counts": risk_doc_counts,
        "risk_truth_doc_counts": risk_truth_counts,
        "scenarios": scenarios,
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"manipulated eval done: {summary['stages']['manipulated_eval']}")


def _evaluate_manipulated_cases(
    phase1_result: Phase1CaseResult,
    *,
    data_dir: Path,
    checkpoint: Path,
    summary: dict[str, Any],
) -> None:
    truth_path = data_dir / "labels" / "manipulated_entry_truth.csv"
    if not truth_path.exists():
        return

    t0 = time.perf_counter()
    truth = pd.read_csv(truth_path, dtype=str, low_memory=False)
    truth_docs = set(truth["document_id"].dropna().astype(str).unique())

    top_ns = (10, 50, 100, 500, 1000)
    top_case_capture = []
    for top_n in top_ns:
        docs = _case_documents(phase1_result.cases[:top_n])
        top_case_capture.append(
            {
                "top_n_cases": top_n,
                "case_docs": len(docs),
                "truth_docs": len(docs & truth_docs),
            }
        )

    band_capture = []
    for band in ("high", "medium", "low"):
        band_cases = [case for case in phase1_result.cases if case.priority_band == band]
        docs = _case_documents(band_cases)
        band_capture.append(
            {
                "priority_band": band,
                "case_count": len(band_cases),
                "case_docs": len(docs),
                "truth_docs": len(docs & truth_docs),
            }
        )

    top_truth_cases = []
    for case in phase1_result.cases:
        docs = {hit.document_id for hit in case.raw_rule_hits if hit.document_id in truth_docs}
        if not docs:
            continue
        top_truth_cases.append(
            {
                "rank": int(case.exposure_rank or 0),
                "case_id": case.case_id,
                "priority_band": case.priority_band,
                "priority_score": float(case.priority_score),
                "primary_theme": case.primary_theme,
                "truth_docs": len(docs),
                "documents": sorted(docs)[:10],
            }
        )
        if len(top_truth_cases) >= 20:
            break

    summary["stages"]["manipulated_case_eval"] = {
        "elapsed_sec": _elapsed(t0),
        "total_truth_docs": len(truth_docs),
        "top_case_capture": top_case_capture,
        "priority_band_capture": band_capture,
        "top_truth_cases": top_truth_cases,
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"manipulated case eval done: {summary['stages']['manipulated_case_eval']}")


def _case_documents(cases) -> set[str]:
    docs: set[str] = set()
    for case in cases:
        docs.update(hit.document_id for hit in case.raw_rule_hits if hit.document_id)
    return docs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth_v126_candidate",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "phase1_v126_profile.json",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "phase1_v126_case_input.pkl",
    )
    parser.add_argument(
        "--stop-after-cache",
        action="store_true",
        help="Run through aggregate, save case-builder input cache, then stop.",
    )
    parser.add_argument(
        "--reuse-cache",
        action="store_true",
        help="Skip ingest/features/detectors/aggregate and profile only the case builder.",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        default="datasynth_v126_profiled_phase1",
        help="batch_id embedded in case artifact filename (distinguishes datasets in multi-dataset audits)",
    )
    args = parser.parse_args()

    total_start = time.perf_counter()
    summary: dict[str, Any] = {
        "data_dir": str(args.data_dir),
        "started_at": _now(),
        "stages": {},
    }
    _write_checkpoint(args.checkpoint, summary)

    if args.reuse_cache:
        payload = _load_case_input_cache(args.cache_path)
        df = payload["df"]
        results = payload["results"]
        data_dir = Path(str(payload.get("data_dir") or args.data_dir))
        summary["cache_reused"] = {
            "path": str(args.cache_path),
            "created_at": payload.get("created_at"),
            "rows": int(len(df)),
            "results": int(len(results)),
        }
        _write_checkpoint(args.checkpoint, summary)
        _log(f"case input cache loaded: {summary['cache_reused']}")
        _run_case_builder_only(
            df,
            results,
            data_dir=data_dir,
            checkpoint=args.checkpoint,
            summary=summary,
            batch_id=args.batch_id,
        )
        _evaluate_manipulated(df, data_dir=data_dir, checkpoint=args.checkpoint, summary=summary)
        summary["total_elapsed_sec"] = _elapsed(total_start)
        summary["finished_at"] = _now()
        _write_checkpoint(args.checkpoint, summary)
        _log(f"case-only done: {summary['total_elapsed_sec']}s checkpoint={args.checkpoint}")
        return 0

    settings = make_phase_settings(get_settings(), phase="phase1")
    audit_rules = get_audit_rules()
    risk_keywords = get_risk_keywords()

    df = _read_data(args.data_dir, args.checkpoint, summary)
    source = args.data_dir / "journal_entries.csv"
    df = apply_datasynth_label_mode(
        df,
        source_path=source,
        mode=getattr(settings, "datasynth_label_mode", "hidden"),
    )
    df = _run_features(
        df,
        settings=settings,
        audit_rules=audit_rules,
        risk_keywords=risk_keywords,
        checkpoint=args.checkpoint,
        summary=summary,
    )
    results = _run_detectors(
        df,
        settings=settings,
        audit_rules=audit_rules,
        checkpoint=args.checkpoint,
        summary=summary,
    )
    df = _aggregate_and_case(
        df,
        results,
        settings=settings,
        data_dir=args.data_dir,
        checkpoint=args.checkpoint,
        summary=summary,
        cache_path=args.cache_path,
        stop_after_cache=args.stop_after_cache,
        batch_id=args.batch_id,
    )
    if args.stop_after_cache:
        summary["total_elapsed_sec"] = _elapsed(total_start)
        summary["finished_at"] = _now()
        _write_checkpoint(args.checkpoint, summary)
        _log(f"stopped after cache: {summary['total_elapsed_sec']}s checkpoint={args.checkpoint}")
        return 0
    _evaluate_manipulated(df, data_dir=args.data_dir, checkpoint=args.checkpoint, summary=summary)
    summary["total_elapsed_sec"] = _elapsed(total_start)
    summary["finished_at"] = _now()
    _write_checkpoint(args.checkpoint, summary)
    _log(f"all done: {summary['total_elapsed_sec']}s checkpoint={args.checkpoint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
