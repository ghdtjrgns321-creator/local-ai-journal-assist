from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd

EXCEPTION_COUNTS = {
    2022: {
        "UnmatchedIntercompany": 6,
        "IntercompanyAmountMismatch": 5,
        "IntercompanyTimingMismatch": 4,
        "TransferPricingAnomaly": 4,
        "CircularTransaction": 3,
    },
    2023: {
        "UnmatchedIntercompany": 7,
        "IntercompanyAmountMismatch": 5,
        "IntercompanyTimingMismatch": 5,
        "TransferPricingAnomaly": 4,
        "CircularTransaction": 3,
    },
    2024: {
        "UnmatchedIntercompany": 8,
        "IntercompanyAmountMismatch": 6,
        "IntercompanyTimingMismatch": 5,
        "TransferPricingAnomaly": 5,
        "CircularTransaction": 4,
    },
}

NORMAL_CONTROL_COUNTS = {
    2022: 24,
    2023: 27,
    2024: 29,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build v38 small IC exception labels and controls."
    )
    parser.add_argument(
        "--source", required=True, help="Source dataset directory, normally datasynth_v37_candidate"
    )
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def read_metadata(value: object) -> dict:
    if pd.isna(value) or str(value).strip() == "":
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def dump_metadata(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_date(value: object) -> str:
    ts = pd.Timestamp(value)
    return ts.strftime("%Y-%m-%d")


def normalize_datetime(value: object) -> str:
    ts = pd.Timestamp(value)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def load_ic_pair_candidates(output: Path) -> pd.DataFrame:
    truth = pd.read_csv(output / "labels" / "intercompany_population_truth.csv")
    ic = (
        truth[
            truth["document_type"].eq("IC")
            & truth["has_trading_partner"].astype(bool)
            & truth["reference_available"].eq(True)
        ]
        if "reference_available" in truth.columns
        else truth[truth["document_type"].eq("IC") & truth["has_trading_partner"].astype(bool)]
    )
    # v37 sidecar does not store reference, so derive pairs from the journal.
    cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "reference",
        "trading_partner",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "line_number",
    ]
    je = pd.read_csv(
        output / "journal_entries.csv",
        usecols=cols,
        low_memory=False,
        parse_dates=["posting_date", "document_date"],
    )
    ic_docs = set(ic["document_id"].astype(str))
    je = je[je["document_id"].astype(str).isin(ic_docs)].copy()
    je["_amount"] = je[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    doc = (
        je.groupby("document_id")
        .agg(
            company_code=("company_code", "first"),
            fiscal_year=("fiscal_year", "first"),
            posting_date=("posting_date", "first"),
            document_date=("document_date", "first"),
            document_number=("document_number", "first"),
            document_type=("document_type", "first"),
            business_process=("business_process", "first"),
            source=("source", "first"),
            created_by=("created_by", "first"),
            reference=("reference", "first"),
            trading_partner=(
                "trading_partner",
                lambda s: next((x for x in s.dropna().astype(str) if x.strip()), ""),
            ),
            amount=("_amount", "max"),
        )
        .reset_index()
    )
    doc = doc[doc["reference"].fillna("").astype(str).str.strip().ne("")]
    pairs: list[dict] = []
    for ref, group in doc.groupby("reference"):
        if len(group) < 2:
            continue
        rows = group.sort_values(["company_code", "document_id"]).to_dict("records")
        for i in range(0, len(rows) - 1, 2):
            a, b = rows[i], rows[i + 1]
            if a["company_code"] == b["company_code"]:
                continue
            if str(a["trading_partner"]) != str(b["company_code"]) or str(
                b["trading_partner"]
            ) != str(a["company_code"]):
                continue
            pairs.append(
                {
                    "reference": ref,
                    "doc_a": a["document_id"],
                    "doc_b": b["document_id"],
                    "company_a": a["company_code"],
                    "company_b": b["company_code"],
                    "fiscal_year": int(a["fiscal_year"]),
                    "posting_date_a": a["posting_date"],
                    "posting_date_b": b["posting_date"],
                    "amount_a": float(a["amount"]),
                    "amount_b": float(b["amount"]),
                    "document_number_a": a["document_number"],
                    "document_number_b": b["document_number"],
                    "business_process": a["business_process"],
                    "source": a["source"],
                }
            )
    return pd.DataFrame(pairs)


def select_cases(pairs: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    rng = random.Random(3817)
    cases: list[dict] = []
    controls: list[dict] = []
    used_refs: set[str] = set()
    for year, counts in EXCEPTION_COUNTS.items():
        pool = pairs[pairs["fiscal_year"].eq(year)].copy()
        refs = pool["reference"].dropna().astype(str).unique().tolist()
        rng.shuffle(refs)
        for anomaly_type, count in counts.items():
            picked = 0
            for ref in refs:
                if ref in used_refs:
                    continue
                row = pool[pool["reference"].eq(ref)].iloc[0]
                case_id = f"ICEX-{year}-{len(cases) + 1:04d}"
                target_doc = row["doc_a"] if picked % 2 == 0 else row["doc_b"]
                counterpart_doc = row["doc_b"] if target_doc == row["doc_a"] else row["doc_a"]
                variant = _variant_for(anomaly_type, picked)
                cases.append(
                    {
                        "case_id": case_id,
                        "anomaly_type": anomaly_type,
                        "fiscal_year": year,
                        "reference": ref,
                        "target_document_id": target_doc,
                        "counterpart_document_id": counterpart_doc,
                        "company_a": row["company_a"],
                        "company_b": row["company_b"],
                        "posting_date_a": normalize_datetime(row["posting_date_a"]),
                        "posting_date_b": normalize_datetime(row["posting_date_b"]),
                        "amount_a": row["amount_a"],
                        "amount_b": row["amount_b"],
                        "business_process": row["business_process"],
                        "source": row["source"],
                        "scenario_variant": variant,
                        "labeling_policy": "small_synthetic_truth_not_rule_backfill",
                    }
                )
                used_refs.add(ref)
                picked += 1
                if picked >= count:
                    break
            if picked < count:
                raise RuntimeError(
                    f"Only selected {picked}/{count} {anomaly_type} cases for {year}"
                )

        control_count = NORMAL_CONTROL_COUNTS[year]
        picked_controls = 0
        for ref in refs:
            if ref in used_refs:
                continue
            row = pool[pool["reference"].eq(ref)].iloc[0]
            controls.append(
                {
                    "control_id": f"ICNC-{year}-{picked_controls + 1:04d}",
                    "fiscal_year": year,
                    "reference": ref,
                    "document_id_a": row["doc_a"],
                    "document_id_b": row["doc_b"],
                    "company_a": row["company_a"],
                    "company_b": row["company_b"],
                    "posting_date_a": normalize_datetime(row["posting_date_a"]),
                    "posting_date_b": normalize_datetime(row["posting_date_b"]),
                    "amount_a": row["amount_a"],
                    "amount_b": row["amount_b"],
                    "normal_control_type": "matched_intercompany_pair",
                    "expected_exception_label": "false",
                }
            )
            used_refs.add(ref)
            picked_controls += 1
            if picked_controls >= control_count:
                break
        if picked_controls < control_count:
            raise RuntimeError(
                f"Only selected {picked_controls}/{control_count} normal IC controls for {year}"
            )
    return cases, controls


def _variant_for(anomaly_type: str, idx: int) -> str:
    variants = {
        "UnmatchedIntercompany": ["missing_counterparty_side", "one_sided_ic_reference"],
        "IntercompanyAmountMismatch": ["fx_or_markup_mismatch", "partial_counterparty_booking"],
        "IntercompanyTimingMismatch": ["counterparty_posted_late", "period_cutoff_gap"],
        "TransferPricingAnomaly": ["price_asymmetry", "non_arm_length_markup"],
        "CircularTransaction": ["three_node_cycle_seed", "round_trip_ic_flow"],
    }
    return variants[anomaly_type][idx % len(variants[anomaly_type])]


def append_labels(output: Path, cases: list[dict]) -> pd.DataFrame:
    labels_path = output / "labels" / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, low_memory=False)
    max_num = _max_anomaly_num(labels)
    rows: list[dict] = []
    template_cols = list(labels.columns)
    for offset, case in enumerate(cases, start=1):
        anomaly_type = case["anomaly_type"]
        metadata = {
            "case_id": case["case_id"],
            "reference": case["reference"],
            "counterpart_document_id": case["counterpart_document_id"],
            "scenario_variant": case["scenario_variant"],
            "v38_label_policy": case["labeling_policy"],
        }
        row = {col: "" for col in template_cols}
        row.update(
            {
                "anomaly_id": f"ANO{max_num + offset:08d}",
                "anomaly_category": "Relational"
                if anomaly_type != "CircularTransaction"
                else "Graph",
                "anomaly_type": anomaly_type,
                "document_id": case["target_document_id"],
                "document_type": "JE",
                "company_code": case["company_a"],
                "anomaly_date": normalize_date(case["posting_date_a"]),
                "detection_timestamp": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "confidence": 0.85,
                "severity": 4
                if anomaly_type in {"CircularTransaction", "TransferPricingAnomaly"}
                else 3,
                "description": _description_for(case),
                "is_injected": True,
                "related_entities": json.dumps(
                    [case["counterpart_document_id"]], ensure_ascii=False
                ),
                "injection_strategy": anomaly_type,
                "scenario_id": case["case_id"],
                "metadata_json": dump_metadata(metadata),
            }
        )
        rows.append(row)
    labels = pd.concat([labels, pd.DataFrame(rows, columns=template_cols)], ignore_index=True)
    labels.to_csv(labels_path, index=False)
    rewrite_label_jsons(output / "labels", labels)
    return labels


def patch_journal_for_cases(output: Path, cases: list[dict]) -> tuple[list[dict], dict]:
    """Make small IC exception labels field-consistent in the CSV journal.

    The goal is not to backfill detector outputs. We start from selected normal IC
    pairs and introduce small, plausible defects so labels have real field support.
    """
    journal_path = output / "journal_entries.csv"
    je = pd.read_csv(journal_path, low_memory=False)
    je["_doc_id_str"] = je["document_id"].astype(str)
    patch_counts: Counter[str] = Counter()

    circular_targets = [c for c in cases if c["anomaly_type"] == "CircularTransaction"]
    circular_partner_by_doc = _build_circular_partner_map(circular_targets)

    for idx, case in enumerate(cases):
        doc_id = str(case["target_document_id"])
        mask = je["_doc_id_str"].eq(doc_id)
        if not mask.any():
            continue
        anomaly_type = case["anomaly_type"]
        before = _doc_snapshot(je.loc[mask])

        if anomaly_type == "UnmatchedIntercompany":
            # D065 (D055 supersede): master 외부 회사 코드로 patch.
            # 기존 `-UNMATCHED` 접미사는 detector fitting signature 였음.
            # 새 코드는 dataset distinct company_code (`C001~C003`) 와 충돌하지 않는
            # `C9NN` 형식. detector 는 partner_format 의 ic_partner_regex 매칭 + master
            # 외부 조건만으로 high evidence 부여한다.
            unmatched_partner = f"C9{(idx % 9) + 1:02d}"
            je.loc[mask, "trading_partner"] = unmatched_partner
            case["patched_trading_partner"] = unmatched_partner
            case["field_patch"] = "trading_partner_changed_to_non_master_company"

        elif anomaly_type == "IntercompanyAmountMismatch":
            factor = 1.07 + (idx % 3) * 0.015
            _scale_document_amounts(je, mask, factor)
            case["amount_mismatch_factor"] = round(factor, 4)
            case["field_patch"] = "target_document_amounts_scaled_balanced"

        elif anomaly_type == "IntercompanyTimingMismatch":
            days = 12 + (idx % 4) * 4
            new_date = _shift_within_year(je.loc[mask, "posting_date"].iloc[0], days)
            je.loc[mask, "posting_date"] = new_date.strftime("%Y-%m-%d %H:%M:%S")
            je.loc[mask, "fiscal_period"] = int(new_date.month)
            case["timing_gap_days"] = days
            case["patched_posting_date"] = new_date.strftime("%Y-%m-%d %H:%M:%S")
            case["field_patch"] = "target_document_posting_date_shifted"

        elif anomaly_type == "TransferPricingAnomaly":
            factor = 1.24 + (idx % 3) * 0.04
            _scale_document_amounts(je, mask, factor)
            case["transfer_pricing_factor"] = round(factor, 4)
            case["field_patch"] = "target_document_amounts_scaled_for_price_asymmetry"

        elif anomaly_type == "CircularTransaction":
            partner = circular_partner_by_doc.get(doc_id)
            if partner:
                je.loc[mask, "trading_partner"] = partner
                case["patched_trading_partner"] = partner
            # Keep cycles above GraphDetector's default materiality floor.
            _ensure_min_document_amount(je, mask, min_amount=15_000_000.0)
            case["field_patch"] = "trading_partner_rewired_to_small_cycle"

        after = _doc_snapshot(je.loc[mask])
        case["previous_amount"] = before["amount"]
        case["patched_amount"] = after["amount"]
        case["previous_posting_date"] = before["posting_date"]
        case["patched_document_posting_date"] = after["posting_date"]
        patch_counts[anomaly_type] += 1

    je = je.drop(columns=["_doc_id_str"])
    je.to_csv(journal_path, index=False)
    for year, year_df in je.groupby("fiscal_year"):
        year_df.to_csv(output / f"journal_entries_{int(year)}.csv", index=False)
    return cases, {str(k): int(v) for k, v in sorted(patch_counts.items())}


def patch_journal_json_for_cases(output: Path, cases: list[dict]) -> int:
    """Mirror the CSV journal patches into the large JSON journal without loading it all."""
    json_path = output / "journal_entries.json"
    if not json_path.exists():
        return 0
    case_by_doc = {str(case["target_document_id"]): case for case in cases}
    tmp_path = json_path.with_suffix(".json.tmp")
    patched = 0
    first_written = False

    with (
        json_path.open("r", encoding="utf-8") as src,
        tmp_path.open("w", encoding="utf-8", newline="\n") as dst,
    ):
        dst.write("[\n")
        buffer: list[str] = []
        depth = 0
        in_object = False
        for line in src:
            stripped = line.strip()
            if not in_object:
                if stripped in {"[", "]"}:
                    continue
                if stripped.startswith("{"):
                    in_object = True
                    buffer = [line]
                    depth = line.count("{") - line.count("}")
                continue
            buffer.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0:
                raw = "".join(buffer).rstrip()
                if raw.endswith(","):
                    raw = raw[:-1]
                record = json.loads(raw)
                doc_id = str(record.get("header", {}).get("document_id", ""))
                if doc_id in case_by_doc:
                    _patch_json_record(record, case_by_doc[doc_id])
                    patched += 1
                if first_written:
                    dst.write(",\n")
                dst.write(json.dumps(record, ensure_ascii=False, indent=2))
                first_written = True
                in_object = False
                buffer = []
        dst.write("\n]\n")
    tmp_path.replace(json_path)
    return patched


def _patch_json_record(record: dict, case: dict) -> None:
    header = record.get("header", {})
    lines = record.get("lines", [])
    anomaly_type = case["anomaly_type"]

    if anomaly_type in {"UnmatchedIntercompany", "CircularTransaction"}:
        partner = case.get("patched_trading_partner")
        if partner:
            for line in lines:
                line["trading_partner"] = partner
                line["trading_partner_name"] = partner

    if anomaly_type == "IntercompanyTimingMismatch":
        patched_date = str(case.get("patched_posting_date", ""))[:10]
        if patched_date:
            header["posting_date"] = patched_date
            header["fiscal_period"] = int(pd.Timestamp(patched_date).month)

    factor = _json_amount_factor(case)
    if factor and factor != 1.0:
        for col in ["invoice_amount", "supply_amount"]:
            if header.get(col) is not None:
                header[col] = _scale_json_amount(header[col], factor)
        for line in lines:
            for col in ["debit_amount", "credit_amount", "local_amount"]:
                if line.get(col) is not None:
                    line[col] = _scale_json_amount(line[col], factor)


def _json_amount_factor(case: dict) -> float | None:
    if "amount_mismatch_factor" in case:
        return float(case["amount_mismatch_factor"])
    if "transfer_pricing_factor" in case:
        return float(case["transfer_pricing_factor"])
    previous = float(case.get("previous_amount") or 0)
    patched = float(case.get("patched_amount") or 0)
    if previous > 0 and patched > 0 and abs(previous - patched) > 0.01:
        return patched / previous
    return None


def _scale_json_amount(value: object, factor: float) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value  # type: ignore[return-value]
    if numeric == 0:
        return str(value)
    return f"{numeric * factor:.2f}"


def _doc_snapshot(doc_rows: pd.DataFrame) -> dict:
    debit = pd.to_numeric(doc_rows["debit_amount"], errors="coerce").fillna(0)
    credit = pd.to_numeric(doc_rows["credit_amount"], errors="coerce").fillna(0)
    amount = pd.concat([debit, credit], axis=1).max(axis=1).max()
    return {
        "amount": float(amount),
        "posting_date": str(doc_rows["posting_date"].iloc[0]),
    }


def _scale_document_amounts(je: pd.DataFrame, mask: pd.Series, factor: float) -> None:
    for col in ["debit_amount", "credit_amount", "local_amount", "invoice_amount", "supply_amount"]:
        if col not in je.columns:
            continue
        numeric = pd.to_numeric(je.loc[mask, col], errors="coerce")
        scale_mask = mask.copy()
        scale_mask.loc[mask] = numeric.fillna(0).ne(0).to_numpy()
        # Pandas 2.x warns when assigning scaled floats into int-backed columns.
        # The CSV remains numeric after reload, but object assignment keeps this
        # patcher forward-compatible.
        je[col] = je[col].astype("object")
        je.loc[scale_mask, col] = (
            pd.to_numeric(je.loc[scale_mask, col], errors="coerce") * factor
        ).round(2)


def _ensure_min_document_amount(je: pd.DataFrame, mask: pd.Series, min_amount: float) -> None:
    current = pd.to_numeric(
        je.loc[mask, ["debit_amount", "credit_amount"]].max(axis=1), errors="coerce"
    ).max()
    if pd.isna(current) or current <= 0:
        return
    if current >= min_amount:
        return
    _scale_document_amounts(je, mask, min_amount / float(current))


def _shift_within_year(value: object, days: int) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    shifted = ts + pd.Timedelta(days=days)
    if shifted.year != ts.year:
        shifted = ts - pd.Timedelta(days=days)
    return shifted


def _build_circular_partner_map(cases: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for year in sorted({c["fiscal_year"] for c in cases}):
        year_cases = [c for c in cases if c["fiscal_year"] == year]
        companies = [str(c["company_a"]) for c in year_cases]
        if len(set(companies)) < 2:
            continue
        for i, case in enumerate(year_cases):
            out[str(case["target_document_id"])] = companies[(i + 1) % len(companies)]
    return out


def _description_for(case: dict) -> str:
    text = {
        "UnmatchedIntercompany": "Intercompany reference has a missing or unmatched counterparty side",
        "IntercompanyAmountMismatch": "Intercompany counterparty pair has amount mismatch beyond tolerance",
        "IntercompanyTimingMismatch": "Intercompany counterparty pair has timing gap beyond normal window",
        "TransferPricingAnomaly": "Intercompany pair shows non-arm's-length pricing asymmetry",
        "CircularTransaction": "Intercompany flow participates in a small circular transaction seed",
    }
    return f"{text[case['anomaly_type']]} ({case['scenario_variant']})"


def _max_anomaly_num(labels: pd.DataFrame) -> int:
    nums = (
        labels["anomaly_id"].fillna("").astype(str).str.extract(r"ANO(\d+)")[0].dropna().astype(int)
    )
    return int(nums.max()) if not nums.empty else 0


def rewrite_label_jsons(labels_dir: Path, labels: pd.DataFrame) -> None:
    records = []
    for _, row in labels.iterrows():
        metadata = read_metadata(row.get("metadata_json", ""))
        related = []
        raw = row.get("related_entities", "")
        if pd.notna(raw) and str(raw).strip():
            try:
                parsed = json.loads(str(raw))
                related = parsed if isinstance(parsed, list) else [str(raw)]
            except json.JSONDecodeError:
                related = [str(raw)]
        records.append(
            {
                "anomaly_id": row["anomaly_id"],
                "anomaly_type": {row["anomaly_category"]: row["anomaly_type"]},
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "company_code": row["company_code"],
                "anomaly_date": str(row["anomaly_date"]),
                "detection_timestamp": str(row["detection_timestamp"]),
                "confidence": row["confidence"],
                "severity": int(row["severity"])
                if pd.notna(row["severity"]) and str(row["severity"]) != ""
                else None,
                "description": row["description"],
                "related_entities": related,
                "metadata": metadata,
                "is_injected": bool(row["is_injected"]),
                "injection_strategy": row["injection_strategy"],
            }
        )
    (labels_dir / "anomaly_labels.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "total_labels": int(len(labels)),
        "by_category": {
            k: int(v) for k, v in labels["anomaly_category"].value_counts().to_dict().items()
        },
        "by_company": {
            k: int(v) for k, v in labels["company_code"].value_counts().to_dict().items()
        },
        "with_provenance": int(
            labels["causal_reason_json"].fillna("").astype(str).str.len().gt(0).sum()
        )
        if "causal_reason_json" in labels
        else 0,
        "in_scenarios": int(labels["scenario_id"].fillna("").astype(str).str.len().gt(0).sum())
        if "scenario_id" in labels
        else 0,
        "in_clusters": int(labels["cluster_id"].fillna("").astype(str).str.len().gt(0).sum())
        if "cluster_id" in labels
        else 0,
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for key in record}) if records else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_sidecar_family(
    labels_dir: Path, stem: str, records: list[dict], year_key: str = "fiscal_year"
) -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for year in sorted({int(r[year_key]) for r in records}):
        year_records = [r for r in records if int(r[year_key]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(
            json.dumps(year_records, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def build_summary(cases: list[dict], controls: list[dict], labels: pd.DataFrame) -> dict:
    return {
        "candidate_version": "v38_candidate",
        "source_baseline": "datasynth_v37_candidate",
        "focus": "Small IC exception labels for IC01/IC02/IC03/GR01/GR03 evaluation",
        "exception_cases": {
            "total": len(cases),
            "by_year": {
                str(k): int(v) for k, v in sorted(Counter(c["fiscal_year"] for c in cases).items())
            },
            "by_type": {
                str(k): int(v) for k, v in sorted(Counter(c["anomaly_type"] for c in cases).items())
            },
        },
        "normal_controls": {
            "total": len(controls),
            "by_year": {
                str(k): int(v)
                for k, v in sorted(Counter(c["fiscal_year"] for c in controls).items())
            },
        },
        "label_counts_after_patch": {
            k: int(v)
            for k, v in labels["anomaly_type"]
            .value_counts()
            .loc[
                lambda s: s.index.isin(
                    [
                        "UnmatchedIntercompany",
                        "IntercompanyAmountMismatch",
                        "IntercompanyTimingMismatch",
                        "TransferPricingAnomaly",
                        "CircularTransaction",
                    ]
                )
            ]
            .to_dict()
            .items()
        },
        "contract": {
            "not_test_fitting": "Labels are small scenario truth cases, not backfilled from detector outputs.",
            "l3_03_population_truth": "Keep using intercompany_population_truth for L3-03.",
            "exception_truth": "Use intercompany_exception_cases for IC01/IC02/IC03/GR01/GR03 scenario evaluation.",
            "normal_controls": "Use intercompany_normal_controls to document matched IC pairs that should not be exception labels.",
        },
    }


def write_preview(output: Path, summary: dict) -> None:
    text = f"""# DataSynth v38 Candidate

v38 is a candidate dataset that keeps the v37 L3-03 intercompany population truth and adds a small, field-supported IC exception truth set.

## Summary

- Source baseline: `datasynth_v37_candidate`
- Added anomaly labels: {summary["exception_cases"]["total"]}
- Added normal IC controls: {summary["normal_controls"]["total"]}
- Scope: IC01/IC02/IC03/GR01/GR03 scenario truth, not L3-03 population truth
- Journal CSV fields are patched for the selected exception documents:
  - `UnmatchedIntercompany`: unmatched `trading_partner`
  - `IntercompanyAmountMismatch` / `TransferPricingAnomaly`: balanced amount scaling
  - `IntercompanyTimingMismatch`: shifted `posting_date`
  - `CircularTransaction`: small cycle seed via `trading_partner` rewiring

## Exception Labels

- By year: {summary["exception_cases"]["by_year"]}
- By type: {summary["exception_cases"]["by_type"]}

## Normal Controls

- By year: {summary["normal_controls"]["by_year"]}
- Meaning: matched IC pairs that should remain unlabeled as exception cases

## Generated Files

- `labels/intercompany_exception_cases.csv/json`
- `labels/intercompany_exception_cases_2022/2023/2024.csv/json`
- `labels/intercompany_normal_controls.csv/json`
- `labels/intercompany_normal_controls_2022/2023/2024.csv/json`
- `V38_IC_EXCEPTION_LABELS.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V38_CANDIDATE.md").write_text(text, encoding="utf-8")


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--source", required=True)
    args.add_argument("--output", required=True)
    args.add_argument("--force", action="store_true")
    parsed = args.parse_args()

    source = Path(parsed.source)
    output = Path(parsed.output)
    if output.exists():
        if not parsed.force:
            raise FileExistsError(f"{output} already exists; pass --force")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    pairs = load_ic_pair_candidates(output)
    cases, controls = select_cases(pairs)
    cases, patch_counts = patch_journal_for_cases(output, cases)
    json_patch_count = patch_journal_json_for_cases(output, cases)
    labels = append_labels(output, cases)
    labels_dir = output / "labels"
    write_sidecar_family(labels_dir, "intercompany_exception_cases", cases)
    write_sidecar_family(labels_dir, "intercompany_normal_controls", controls)
    summary = build_summary(cases, controls, labels)
    summary["journal_field_patches"] = patch_counts
    summary["journal_json_patched_documents"] = json_patch_count
    (output / "V38_IC_EXCEPTION_LABELS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
