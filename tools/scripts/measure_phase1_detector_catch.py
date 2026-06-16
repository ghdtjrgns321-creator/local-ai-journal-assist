from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import tools.scripts.profile_phase1_v126 as prof
from config.settings import get_audit_rules, get_risk_keywords, get_settings
from src.detection.prior_data_loader import PriorSummary
from src.detection.variance_rules import _normalise_key_part
from src.ingest.datasynth_labels import apply_datasynth_label_mode, set_source_path
from src.services.analysis_service import make_phase_settings


def jlist(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    t = str(v).strip()
    if not t:
        return []
    x = json.loads(t) if t.startswith("[") else t.split(chr(124))
    return [str(i) for i in x if str(i)]


def read_truth(path):
    if path is None or not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for c in ("member_document_ids", "base_document_ids"):
        df[c] = df[c].map(jlist) if c in df.columns else [[] for _ in range(len(df))]
    return df


def read_data(data_dir, limit_rows, checkpoint, summary):
    if limit_rows is None:
        return prof._read_data(data_dir, checkpoint, summary)
    source = data_dir / "journal_entries.csv"
    st = time.perf_counter()
    df = pd.read_csv(
        source, nrows=limit_rows, usecols=lambda c: c in prof.PHASE1_USECOLS, low_memory=False
    )
    for c in prof.DATE_COLUMNS:
        if c in df.columns:
            # Why: 혼합 형식(date_only+datetime) 견고화 — prof._read_data와 동일 (ISO8601)
            df[c] = pd.to_datetime(df[c], errors="coerce", format="ISO8601")
    df = set_source_path(df, source)
    summary["stages"]["read_csv"] = dict(
        elapsed_sec=round(time.perf_counter() - st, 3),
        rows=int(len(df)),
        limit_rows=int(limit_rows),
    )
    prof._write_checkpoint(checkpoint, summary)
    return prof._enrich_independent_audit_evidence(
        df, data_dir, checkpoint=checkpoint, summary=summary
    )


def run_detectors(data_dir, output_dir, limit_rows):
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "detector_checkpoint.json"
    summary = dict(
        data_dir=str(data_dir),
        started_at=datetime.now(UTC).isoformat(),
        limit_rows=limit_rows,
        stages=dict(),
    )
    prof._write_checkpoint(checkpoint, summary)
    settings = make_phase_settings(get_settings(), phase="phase1")
    rules = get_audit_rules()
    keywords = get_risk_keywords()
    source = data_dir / "journal_entries.csv"
    df = read_data(data_dir, limit_rows, checkpoint, summary)
    df = apply_datasynth_label_mode(
        df, source_path=source, mode=getattr(settings, "datasynth_label_mode", "hidden")
    )
    df = prof._run_features(
        df,
        settings=settings,
        audit_rules=rules,
        risk_keywords=keywords,
        checkpoint=checkpoint,
        summary=summary,
    )
    results = prof._run_detectors(
        df, settings=settings, audit_rules=rules, checkpoint=checkpoint, summary=summary
    )
    # Why: prof._run_detectors only runs layer_a/b/c + benford (24 rule_ids).
    #      The flow/graph/intercompany/variance/evidence tracks (IC01-03, GR01/03,
    #      D01/D02, L3-11) are NOT in that set, so their truth units would always
    #      register as missed (tooling blind, not real FN). Run them here too so
    #      every truth rule_id is measurable. Settings enable_* flags only gate the
    #      pipeline wrappers, not the detectors themselves; we call detect() directly.
    results = results + _run_extra_detectors(
        df, settings=settings, audit_rules=rules, checkpoint=checkpoint, summary=summary
    )
    summary["finished_at"] = datetime.now(UTC).isoformat()
    prof._write_checkpoint(checkpoint, summary)
    return df, results, summary


def _run_extra_detectors(df, *, settings, audit_rules, checkpoint, summary):
    from src.detection.evidence_detector import EvidenceDetector
    from src.detection.variance_layer import VarianceDetector

    # intercompany/graph(IC01-03·GR01/03) 제거 (2026-06-14): PHASE2 family 영역으로 PHASE1
    # 점수경로에서 제외. evidence(L3-11)·layer_d(D01/D02 variance)만 PHASE1 보완 트랙으로 유지.
    layer_d_df, prior_summary = _variance_inputs_from_multiyear_df(df)
    extra = [
        ("evidence", lambda: EvidenceDetector(settings, audit_rules=audit_rules)),
        ("layer_d", lambda: VarianceDetector(settings, prior_summary=prior_summary)),
    ]
    out = []
    stage = summary["stages"].setdefault("extra_detectors", {})
    for name, ctor in extra:
        t0 = time.perf_counter()
        try:
            detector_df = layer_d_df if name == "layer_d" and prior_summary is not None else df
            res = ctor().detect(detector_df)
            out.append(res)
            stage[name] = dict(
                elapsed_sec=round(time.perf_counter() - t0, 3),
                flagged_count=int(res.flagged_count),
                rules_run=int(res.total_rules_run),
                warnings=list(res.warnings or [])[:10],
            )
        except Exception as exc:
            stage[name] = dict(elapsed_sec=round(time.perf_counter() - t0, 3), error=str(exc)[:300])
        prof._write_checkpoint(checkpoint, summary)
        print("[extra] " + name + ": " + json.dumps(stage[name], ensure_ascii=True), flush=True)
    return out


def _variance_inputs_from_multiyear_df(df):
    if "fiscal_year" not in df.columns or "gl_account" not in df.columns:
        return df, None
    years = pd.to_numeric(df["fiscal_year"], errors="coerce").dropna().astype(int)
    if years.empty:
        return df, None
    current_year = int(years.max())
    prior_year = current_year - 1
    prior = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(prior_year)].copy()
    current = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(current_year)].copy()
    if prior.empty or current.empty:
        return df, None

    amount = prior[["debit_amount", "credit_amount"]].fillna(0).sum(axis=1)
    has_company = "company_code" in prior.columns
    group_cols = ["company_code", "gl_account"] if has_company else ["gl_account"]
    agg = (
        prior.assign(_amount=amount)
        .groupby(group_cols, dropna=False)["_amount"]
        .agg(total_amount="sum", count="count", avg_amount="mean")
        .reset_index()
    )
    account_aggregates = {}
    for _, row in agg.iterrows():
        acct = _normalise_key_part(row["gl_account"])
        key = f"{_normalise_key_part(row['company_code'])}::{acct}" if has_company else acct
        account_aggregates[key] = {
            "total_amount": float(row["total_amount"]),
            "count": int(row["count"]),
            "avg_amount": float(row["avg_amount"]),
        }

    monthly_patterns = {}
    if "fiscal_period" in prior.columns:
        monthly = (
            prior.assign(_amount=amount)
            .groupby(group_cols + ["fiscal_period"], dropna=False)["_amount"]
            .sum()
            .reset_index()
        )
        annual = (
            prior.assign(_amount=amount)
            .groupby(group_cols, dropna=False)["_amount"]
            .sum()
            .reset_index()
            .rename(columns={"_amount": "_annual_amount"})
        )
        merged = monthly.merge(annual, on=group_cols, how="left")
        for _, row in merged.iterrows():
            acct = _normalise_key_part(row["gl_account"])
            key = f"{_normalise_key_part(row['company_code'])}::{acct}" if has_company else acct
            annual_amount = float(row["_annual_amount"] or 0.0)
            if annual_amount <= 0:
                continue
            try:
                month = int(row["fiscal_period"])
            except (TypeError, ValueError):
                continue
            monthly_patterns.setdefault(key, {})[month] = float(row["_amount"]) / annual_amount

    return current, PriorSummary(
        account_aggregates=account_aggregates,
        monthly_patterns=monthly_patterns,
        prior_total_rows=int(len(prior)),
        prior_fiscal_year=prior_year,
    )


def detail_map(results, df):
    out = dict()
    for r in results:
        d = getattr(r, "details", None)
        if not isinstance(d, pd.DataFrame) or d.empty:
            d = pd.DataFrame()
        for rule in d.columns:
            out[str(rule)] = pd.to_numeric(d[rule], errors="coerce").fillna(0.0)
        meta = getattr(r, "metadata", None)
        if isinstance(meta, dict):
            review = meta.get("review_score_series")
            if isinstance(review, pd.DataFrame):
                for rule in review.columns:
                    series = pd.to_numeric(review[rule], errors="coerce").fillna(0.0)
                    if series.gt(0).any():
                        base = out.get(str(rule))
                        out[str(rule)] = (
                            series
                            if base is None
                            else pd.concat(
                                [base, series],
                                axis=1,
                            ).max(axis=1)
                        )
            d01_rows = meta.get("account_activity_variance")
            if d01_rows and "company_code" in df.columns and "gl_account" in df.columns:
                s = out.get("D01", pd.Series(0.0, index=df.index, dtype="float64"))
                flagged_keys = {
                    (
                        _normalise_key_part(item.get("company_code", "")),
                        _normalise_key_part(item.get("gl_account", "")),
                    )
                    for item in d01_rows
                }
                if flagged_keys:
                    current_keys = pd.Series(
                        list(
                            zip(
                                df["company_code"].map(_normalise_key_part),
                                df["gl_account"].map(_normalise_key_part),
                            )
                        ),
                        index=df.index,
                    )
                    s.loc[current_keys.isin(flagged_keys)] = 1.0
                out["D01"] = s
            d02_rows = meta.get("d02_account_diagnostics")
            if d02_rows and "company_code" in df.columns and "gl_account" in df.columns:
                s = out.get("D02", pd.Series(0.0, index=df.index, dtype="float64"))
                flagged_keys = {
                    (
                        _normalise_key_part(item.get("company_code", "")),
                        _normalise_key_part(item.get("gl_account", "")),
                    )
                    for item in d02_rows
                    if bool(item.get("flagged", False))
                }
                if flagged_keys:
                    current_keys = pd.Series(
                        list(
                            zip(
                                df["company_code"].map(_normalise_key_part),
                                df["gl_account"].map(_normalise_key_part),
                            )
                        ),
                        index=df.index,
                    )
                    s.loc[current_keys.isin(flagged_keys)] = 1.0
                out["D02"] = s
        if isinstance(meta, dict) and meta.get("benford_candidate_indices"):
            base = out.get("L4-02")
            if base is None:
                base = pd.Series(0.0, index=d.index, dtype="float64")
            candidates = [
                idx for idx in meta.get("benford_candidate_indices", []) if idx in base.index
            ]
            if candidates:
                base.loc[candidates] = 1.0
            out["L4-02"] = base
    return out


def docs_for(row):
    docs = set(str(x) for x in row.get("member_document_ids", []) if str(x))
    docs.update(str(x) for x in row.get("base_document_ids", []) if str(x))
    nat = str(row.get("natural_unit_id", "") or "")
    if str(row.get("natural_unit_type", "")) == "document" and nat:
        docs.add(nat)
    return docs


def measure_truth(truth, df, details):
    if truth.empty:
        return pd.DataFrame()
    doc_series = df.get("document_id", pd.Series("", index=df.index)).astype(str)
    rows = []
    for _, row in truth.iterrows():
        rule = str(row.get("rule_id", ""))
        docs = docs_for(row)
        s = details.get(rule)
        pos = 0
        if s is not None:
            mask = s.gt(0)
            if docs:
                mask = mask & doc_series.reindex(s.index).isin(docs)
            pos = int(mask.sum())
        rows.append(
            dict(
                rule_id=rule,
                case_kind=str(row.get("case_kind", "")),
                case_index=row.get("case_index"),
                variant_id=str(row.get("variant_id", "")),
                variant_name=str(row.get("variant_name", "")),
                variant_ordinal=row.get("variant_ordinal", ""),
                expected_measurement_unit=str(row.get("expected_measurement_unit", "")),
                raw_trigger_summary=str(row.get("raw_trigger_summary", "")),
                threshold_relation=str(row.get("threshold_relation", "")),
                is_boundary_control=str(row.get("is_boundary_control", "")).lower() == "true",
                natural_unit_type=str(row.get("natural_unit_type", "")),
                natural_unit_id=str(row.get("natural_unit_id", "")),
                member_document_count=len(docs),
                caught=bool(pos),
                positive_rows=pos,
                expected_surface=row.get("expected_surface", ""),
                evasion_vector=row.get("evasion_vector", ""),
            )
        )
    return pd.DataFrame(rows)


def rule_summary(measurement, details):
    ids = set(details.keys())
    if not measurement.empty:
        ids.update(measurement["rule_id"].astype(str).unique())
    rows = []
    for rule in sorted(ids):
        s = details.get(rule)
        emitted = int(s.gt(0).sum()) if s is not None else 0
        sub = (
            measurement[measurement["rule_id"].astype(str).eq(rule)]
            if not measurement.empty
            else pd.DataFrame()
        )
        std = sub[sub["case_kind"].eq("standard")] if not sub.empty else pd.DataFrame()
        eva = (
            sub[sub["case_kind"].isin(["evasion", "boundary_control"])]
            if not sub.empty
            else pd.DataFrame()
        )
        rows.append(
            dict(
                rule_id=rule,
                input_units=int(len(sub)),
                emitted_rows=emitted,
                caught_units=int(sub["caught"].sum()) if not sub.empty else 0,
                missed_units=int((~sub["caught"]).sum()) if not sub.empty else 0,
                standard_input=int(len(std)),
                standard_caught=int(std["caught"].sum()) if not std.empty else 0,
                standard_missed=int((~std["caught"]).sum()) if not std.empty else 0,
                evasion_input=int(len(eva)),
                evasion_caught=int(eva["caught"].sum()) if not eva.empty else 0,
                evasion_missed_phase2=int((~eva["caught"]).sum()) if not eva.empty else 0,
            )
        )
    return pd.DataFrame(rows)


def variant_summary(measurement):
    if measurement.empty:
        return pd.DataFrame()
    rows = []
    group_cols = ["rule_id", "variant_name", "case_kind"]
    for keys, sub in measurement.groupby(group_cols, dropna=False):
        rule_id, variant_name, case_kind = keys
        rows.append(
            dict(
                rule_id=rule_id,
                variant_name=variant_name,
                case_kind=case_kind,
                input_units=int(len(sub)),
                caught_units=int(sub["caught"].sum()),
                missed_units=int((~sub["caught"]).sum()),
                false_positive_units=int(sub["caught"].sum())
                if case_kind == "boundary_control"
                else 0,
            )
        )
    return pd.DataFrame(rows)


def make_summary(data_dir, df, truth, meas, details, elapsed, limit_rows):
    l304 = details.get("L3-04")
    l304_rows = int(l304.gt(0).sum()) if l304 is not None else 0
    n = int(len(df))
    return dict(
        generated_at=datetime.now(UTC).isoformat(),
        data_dir=str(data_dir),
        limit_rows=limit_rows,
        elapsed_sec=round(elapsed, 3),
        rows=n,
        truth_units=int(len(truth)),
        caught_truth_units=int(meas["caught"].sum()) if not meas.empty else 0,
        missed_truth_units=int((~meas["caught"]).sum()) if not meas.empty else 0,
        l3_04_detail_positive_rows=l304_rows,
        l3_04_detail_positive_rate=round(l304_rows / n, 6) if n else 0.0,
        scope_note="Detector details only. Ranks require case/unit build and are excluded.",
    )


def write_outputs(out, summary, rules, variants, meas):
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2) + chr(10), encoding="utf-8"
    )
    rules.to_csv(out / "rule_summary.csv", index=False, encoding="utf-8")
    variants.to_csv(out / "variant_summary.csv", index=False, encoding="utf-8")
    meas.to_csv(out / "truth_unit_measurement.csv", index=False, encoding="utf-8")
    (out / "measurement.md").write_text(rules.to_markdown(index=False) + chr(10), encoding="utf-8")


def measure(data_dir, output_dir, limit_rows):
    out = output_dir or data_dir / "reports" / "phase1_detector_catch"
    truth = read_truth(data_dir / "labels" / "p3_2_rule_truth.csv")
    start = time.perf_counter()
    df, results, _stage = run_detectors(data_dir, out, limit_rows)
    elapsed = time.perf_counter() - start
    details = detail_map(results, df)
    meas = measure_truth(truth, df, details)
    rules = rule_summary(meas, details)
    variants = variant_summary(meas)
    summary = make_summary(data_dir, df, truth, meas, details, elapsed, limit_rows)
    write_outputs(out, summary, rules, variants, meas)
    return dict(summary=summary, output_dir=str(out), rule_summary=rules)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--limit-rows", type=int, default=None)
    parser.add_argument("--expect-truth-units", type=int, default=None)
    args = parser.parse_args(argv)
    truth = read_truth(args.data_dir / "labels" / "p3_2_rule_truth.csv")
    if args.expect_truth_units is not None and len(truth) != args.expect_truth_units:
        raise SystemExit(
            "truth unit count mismatch: expected "
            + str(args.expect_truth_units)
            + ", got "
            + str(len(truth))
        )
    print("[measure] detector-only run; no case/unit build", flush=True)
    result = measure(args.data_dir, args.output_dir, args.limit_rows)
    print(json.dumps(result["summary"], ensure_ascii=True, indent=2), flush=True)
    print("[measure] outputs: " + result["output_dir"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
