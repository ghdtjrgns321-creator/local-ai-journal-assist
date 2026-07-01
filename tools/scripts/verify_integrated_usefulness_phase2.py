"""Gate for integrated-usefulness Phase2 DataSynth overlay.

This gate validates generation mechanics and leakage only. It does not run
detectors and must not tune data to detector predicates.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


EXPECTED_SEEDS = 5
EXPECTED_CASES_PER_SEED = 108
EXPECTED_TRUTH = EXPECTED_SEEDS * EXPECTED_CASES_PER_SEED
EXPECTED_PHASE2_PATTERNS = {
    "embezzlement_concealment",
    "approval_sod",
    "circular_transaction",
}
EXPECTED_SOURCE_PATTERNS = {
    "가공전표",
    "비용자산화",
    "계정분류",
    "횡령은폐",
    "승인SoD",
    "순환거래",
}
LABEL_COLUMNS = {
    "is_fraud",
    "is_anomaly",
    "fraud_type",
    "anomaly_type",
    "mutation_base_event_type",
    "mutation_type",
    "mutation_mutated_field",
    "mutation_original_value",
    "mutation_mutated_value",
    "mutation_reason",
    "detection_surface_hints",
}
ORACLE_SKIP_COLUMNS = {
    "document_id",
    "document_number",
    "reference",
    "line_number",
    "debit_amount",
    "credit_amount",
    "local_amount",
    "invoice_amount",
    "supply_amount",
    "tax_amount",
}
DISTRIBUTION_SKIP_COLUMNS = ORACLE_SKIP_COLUMNS | {
    "posting_date",
    "document_date",
    "approval_date",
    "delivery_date",
    "settlement_date",
    "lettrage_date",
    "header_text",
    "line_text",
    "auxiliary_account_label",
}
DIST_FRAUD_MODE_THRESHOLD = 0.85
DIST_NORMAL_SHARE_THRESHOLD = 0.20


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_headers(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def load_coa_accounts(dataset: Path) -> set[str]:
    root = json.loads((dataset / "chart_of_accounts.json").read_text(encoding="utf-8"))
    accounts = root.get("accounts", root if isinstance(root, list) else [])
    out: set[str] = set()
    for account in accounts:
        code = (
            account.get("account_number")
            or account.get("gl_account")
            or account.get("account_code")
        )
        if code is not None:
            out.add(str(code))
    return out


def money(value: str | None) -> int:
    if not value:
        return 0
    return int(float(value.replace(",", "")))


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--base", type=Path, default=None)
    args = parser.parse_args()

    dataset = args.dataset
    journal_path = dataset / "journal_entries.csv"
    truth_path = dataset / "labels" / "integrated_usefulness_phase2_truth.csv"
    manifest_path = dataset / "INTEGRATED_USEFULNESS_PHASE2_MANIFEST.json"
    failures: list[str] = []
    for path in (journal_path, truth_path, manifest_path):
        if not path.exists():
            failures.append(f"missing:{path}")
    if failures:
        print("\n".join(failures))
        return 1

    headers = read_headers(journal_path)
    exposed = sorted(LABEL_COLUMNS & set(headers))
    if exposed:
        failures.append(f"journal_label_columns_exposed:{exposed}")

    truth = read_csv(truth_path)
    if len(truth) != EXPECTED_TRUTH:
        failures.append(f"truth_count:{len(truth)} expected:{EXPECTED_TRUTH}")

    seed_counts = Counter(row.get("seed_id", "") for row in truth)
    if len(seed_counts) != EXPECTED_SEEDS or any(
        count != EXPECTED_CASES_PER_SEED for count in seed_counts.values()
    ):
        failures.append(f"seed_counts_bad:{dict(seed_counts)}")

    phase2_patterns = Counter(row.get("generated_pattern_name", "") for row in truth)
    for pattern in EXPECTED_PHASE2_PATTERNS:
        if phase2_patterns[pattern] == 0:
            failures.append(f"missing_phase2_pattern:{pattern}")

    source_patterns: set[str] = set()
    truth_docs: set[str] = set()
    natural_unit_bad: list[str] = []
    for row in truth:
        source_patterns.update(
            part.strip()
            for part in row.get("source_patterns", "").replace("/", ",").split(",")
            if part.strip()
        )
        if row.get("journal_label_exposed") != "false":
            failures.append(f"truth_row_label_exposed:{row.get('scheme_instance_id')}")
        try:
            docs = [str(doc) for doc in json.loads(row.get("member_document_ids", "[]"))]
        except json.JSONDecodeError:
            failures.append(f"bad_member_document_ids:{row.get('scheme_instance_id')}")
            continue
        pattern = row.get("generated_pattern_name", "")
        if pattern == "embezzlement_concealment" and len(docs) < 2:
            natural_unit_bad.append(f"{row.get('scheme_instance_id')}:embezzlement_docs={len(docs)}")
        if pattern == "circular_transaction" and len(docs) < 3:
            natural_unit_bad.append(f"{row.get('scheme_instance_id')}:circular_docs={len(docs)}")
        if pattern == "approval_sod" and not docs:
            natural_unit_bad.append(f"{row.get('scheme_instance_id')}:approval_docs=0")
        truth_docs.update(docs)
        try:
            declared = json.loads(row.get("declared_violations", "[]"))
        except json.JSONDecodeError:
            declared = []
        if not declared:
            failures.append(f"declared_violations_empty:{row.get('scheme_instance_id')}")
    missing_source = sorted(EXPECTED_SOURCE_PATTERNS - source_patterns)
    if missing_source:
        failures.append(f"missing_source_patterns:{missing_source}")
    if natural_unit_bad:
        failures.append(f"natural_unit_bad:{natural_unit_bad[:20]}")

    rows = read_csv(journal_path)
    by_doc: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_doc[row.get("document_id", "")].append(row)
    missing_docs = sorted(doc for doc in truth_docs if doc not in by_doc)
    if missing_docs:
        failures.append(f"truth_docs_missing_in_journal:{missing_docs[:5]} count={len(missing_docs)}")

    coa = load_coa_accounts(dataset)
    orphan_accounts = sorted(
        {
            row.get("gl_account", "")
            for doc in truth_docs
            for row in by_doc.get(doc, [])
            if row.get("gl_account", "") not in coa
        }
    )
    if orphan_accounts:
        failures.append(f"orphan_accounts:{orphan_accounts}")

    unbalanced: list[str] = []
    original_refs_missing: list[str] = []
    open_items = 0
    all_docs = set(by_doc)
    for doc in truth_docs:
        doc_rows = by_doc.get(doc, [])
        debit = sum(money(row.get("debit_amount")) for row in doc_rows)
        credit = sum(money(row.get("credit_amount")) for row in doc_rows)
        if debit != credit:
            unbalanced.append(f"{doc}:{debit-credit}")
        for row in doc_rows:
            original = row.get("original_document_id", "")
            if original and original not in all_docs:
                original_refs_missing.append(f"{doc}->{original}")
            if row.get("is_cleared", "").lower() == "false" and money(row.get("amount_open")) > 0:
                open_items += 1
    if unbalanced:
        failures.append(f"unbalanced_truth_docs:{unbalanced[:5]} count={len(unbalanced)}")
    if original_refs_missing:
        failures.append(f"original_refs_missing:{original_refs_missing[:20]}")
    if open_items == 0:
        failures.append("missing_long_open_amount_open_items")

    oracle_findings: list[str] = []
    for column in headers:
        if column in ORACLE_SKIP_COLUMNS:
            continue
        counts: dict[str, list[set[str]]] = defaultdict(lambda: [set(), set()])
        for row in rows:
            value = row.get(column, "")
            if value == "":
                continue
            doc_id = row.get("document_id", "")
            bucket = 0 if doc_id in truth_docs else 1
            counts[value][bucket].add(doc_id)
        for value, (truth_doc_set, normal_doc_set) in counts.items():
            if len(truth_doc_set) >= 5 and not normal_doc_set:
                oracle_findings.append(f"{column}={value!r}:{len(truth_doc_set)}/0")
                break
    if oracle_findings:
        failures.append(f"exact_value_oracle_findings:{oracle_findings[:20]}")

    distribution_findings: list[str] = []
    for column in headers:
        if column in DISTRIBUTION_SKIP_COLUMNS:
            continue
        fraud_values: Counter[str] = Counter()
        normal_values: Counter[str] = Counter()
        for row in rows:
            value = row.get(column, "")
            if row.get("document_id", "") in truth_docs:
                fraud_values[value] += 1
            else:
                normal_values[value] += 1
        fraud_total = sum(fraud_values.values())
        normal_total = sum(normal_values.values())
        if not fraud_total or not normal_total:
            continue
        value, fraud_count = fraud_values.most_common(1)[0]
        fraud_share = fraud_count / fraud_total
        normal_share = normal_values.get(value, 0) / normal_total
        if fraud_share > DIST_FRAUD_MODE_THRESHOLD and normal_share < DIST_NORMAL_SHARE_THRESHOLD:
            distribution_findings.append(
                f"{column}={value!r}:fraud_share={fraud_share:.3f},normal_share={normal_share:.3f}"
            )
    if distribution_findings:
        failures.append(f"distribution_leak_findings:{distribution_findings[:20]}")

    temporal_counts = Counter()
    for doc in truth_docs:
        for row in by_doc.get(doc, []):
            document_date = parse_date(row.get("document_date"))
            approval_date = parse_date(row.get("approval_date"))
            posting_date = parse_date(row.get("posting_date"))
            settlement_date = parse_date(row.get("settlement_date"))
            if approval_date and document_date and approval_date < document_date:
                temporal_counts["approval_before_document"] += 1
            if posting_date and document_date and posting_date < document_date:
                temporal_counts["posting_before_document"] += 1
            if settlement_date and posting_date and settlement_date < posting_date:
                temporal_counts["settlement_before_posting"] += 1
    if temporal_counts:
        failures.append(f"temporal_coherence_counts:{dict(temporal_counts)}")

    if args.base is not None:
        base_rows = read_csv(args.base / "journal_entries.csv")
        base_docs = {row.get("document_id", "") for row in base_rows}
        output_docs = {row.get("document_id", "") for row in rows}
        overlap = truth_docs & base_docs
        if overlap:
            failures.append(f"truth_reuses_base_doc_ids:{sorted(overlap)[:5]}")
        expected_docs = len(base_docs) + len(truth_docs)
        if len(output_docs) != expected_docs:
            failures.append(f"document_count_invariant:{len(output_docs)} expected:{expected_docs}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("overlay_document_count") != len(truth_docs):
        failures.append(f"manifest_overlay_count:{manifest.get('overlay_document_count')} expected:{len(truth_docs)}")
    if manifest.get("journal_label_exposed") is not False:
        failures.append("manifest_journal_label_exposed_not_false")

    summary = {
        "dataset": str(dataset),
        "truth_rows": len(truth),
        "seed_counts": dict(seed_counts),
        "phase2_patterns": dict(phase2_patterns),
        "source_patterns": sorted(source_patterns),
        "truth_documents": len(truth_docs),
        "open_items": open_items,
        "exact_value_oracle_findings": oracle_findings[:20],
        "distribution_leak_findings": distribution_findings[:20],
        "temporal_coherence_counts": dict(temporal_counts),
        "failures": failures,
    }
    reports = dataset / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "integrated_usefulness_phase2_gate.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
