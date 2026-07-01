"""Gate for integrated-usefulness Phase1 DataSynth overlay.

This gate validates generation mechanics only. It does not run PHASE1/PHASE2
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
EXPECTED_CASES_PER_SEED = 119
EXPECTED_TRUTH = EXPECTED_SEEDS * EXPECTED_CASES_PER_SEED
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


def money(value: str) -> int:
    if value is None or value == "":
        return 0
    return int(float(value.replace(",", "")))


def parse_date(value: str) -> date | None:
    if value is None or value == "":
        return None
    return date.fromisoformat(value[:10])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--base", type=Path, default=None)
    args = parser.parse_args()

    dataset = args.dataset
    base = args.base
    journal_path = dataset / "journal_entries.csv"
    truth_path = dataset / "labels" / "integrated_usefulness_phase1_truth.csv"
    manifest_path = dataset / "INTEGRATED_USEFULNESS_PHASE1_MANIFEST.json"

    failures: list[str] = []
    if not journal_path.exists():
        failures.append(f"missing journal: {journal_path}")
    if not truth_path.exists():
        failures.append(f"missing truth sidecar: {truth_path}")
    if not manifest_path.exists():
        failures.append(f"missing manifest: {manifest_path}")
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
    bad_seed_counts = {
        seed: count for seed, count in seed_counts.items() if count != EXPECTED_CASES_PER_SEED
    }
    if len(seed_counts) != EXPECTED_SEEDS or bad_seed_counts:
        failures.append(f"seed_counts_bad:{dict(seed_counts)}")

    patterns = Counter(row.get("generated_pattern_name", "") for row in truth)
    for pattern in (
        "fabricated_revenue",
        "expense_capitalization",
        "account_misclassification",
    ):
        if patterns[pattern] == 0:
            failures.append(f"missing_pattern:{pattern}")

    truth_docs: set[str] = set()
    for row in truth:
        if row.get("journal_label_exposed") != "false":
            failures.append(f"truth_row_label_exposed:{row.get('scheme_instance_id')}")
        try:
            docs = json.loads(row.get("member_document_ids", "[]"))
        except json.JSONDecodeError:
            failures.append(f"bad_member_document_ids:{row.get('scheme_instance_id')}")
            continue
        if len(docs) != 1:
            failures.append(f"bad_member_count:{row.get('scheme_instance_id')}:{docs}")
        truth_docs.update(str(doc) for doc in docs)
        try:
            declared = json.loads(row.get("declared_violations", "[]"))
        except json.JSONDecodeError:
            declared = []
        if not declared:
            failures.append(f"declared_violations_empty:{row.get('scheme_instance_id')}")

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
    same_gl_drcr: list[str] = []
    for doc in truth_docs:
        doc_rows = by_doc.get(doc, [])
        debit = sum(money(row.get("debit_amount", "")) for row in doc_rows)
        credit = sum(money(row.get("credit_amount", "")) for row in doc_rows)
        if debit != credit:
            unbalanced.append(f"{doc}:{debit-credit}")
        gl_sides: dict[str, set[str]] = defaultdict(set)
        for row in doc_rows:
            if money(row.get("debit_amount", "")) > 0:
                gl_sides[row.get("gl_account", "")].add("D")
            if money(row.get("credit_amount", "")) > 0:
                gl_sides[row.get("gl_account", "")].add("C")
        if any(sides == {"D", "C"} for sides in gl_sides.values()):
            same_gl_drcr.append(doc)
    if unbalanced:
        failures.append(f"unbalanced_truth_docs:{unbalanced[:5]} count={len(unbalanced)}")
    if same_gl_drcr:
        failures.append(f"same_gl_debit_credit_truth_docs:{same_gl_drcr[:5]} count={len(same_gl_drcr)}")

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
            if row.get("document_id", "") in truth_docs:
                counts[value][0].add(doc_id)
            else:
                counts[value][1].add(doc_id)
        for value, (truth_doc_set, normal_doc_set) in counts.items():
            truth_count = len(truth_doc_set)
            normal_count = len(normal_doc_set)
            if truth_count >= 5 and normal_count == 0:
                oracle_findings.append(f"{column}={value!r}:{truth_count}/0")
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
        if fraud_total == 0 or normal_total == 0 or not fraud_values:
            continue
        value, fraud_count = fraud_values.most_common(1)[0]
        fraud_share = fraud_count / fraud_total
        normal_share = normal_values.get(value, 0) / normal_total
        if (
            fraud_share > DIST_FRAUD_MODE_THRESHOLD
            and normal_share < DIST_NORMAL_SHARE_THRESHOLD
        ):
            distribution_findings.append(
                f"{column}={value!r}:fraud_share={fraud_share:.3f},normal_share={normal_share:.3f}"
            )
    if distribution_findings:
        failures.append(f"distribution_leak_findings:{distribution_findings[:20]}")

    temporal_findings: list[str] = []
    temporal_counts = Counter()
    for doc in truth_docs:
        for row in by_doc.get(doc, []):
            document_date = parse_date(row.get("document_date", ""))
            approval_date = parse_date(row.get("approval_date", ""))
            posting_date = parse_date(row.get("posting_date", ""))
            settlement_date = parse_date(row.get("settlement_date", ""))
            if approval_date and document_date and approval_date < document_date:
                temporal_counts["approval_before_document"] += 1
                if len(temporal_findings) < 20:
                    temporal_findings.append(
                        f"{doc}:approval {approval_date} < document {document_date}"
                    )
            if posting_date and document_date and posting_date < document_date:
                temporal_counts["posting_before_document"] += 1
                if len(temporal_findings) < 20:
                    temporal_findings.append(
                        f"{doc}:posting {posting_date} < document {document_date}"
                    )
            if settlement_date and posting_date and settlement_date < posting_date:
                temporal_counts["settlement_before_posting"] += 1
                if len(temporal_findings) < 20:
                    temporal_findings.append(
                        f"{doc}:settlement {settlement_date} < posting {posting_date}"
                    )
    if temporal_findings:
        failures.append(f"temporal_coherence_findings:{temporal_findings}")

    if base is not None:
        base_rows = read_csv(base / "journal_entries.csv")
        base_docs = {row.get("document_id", "") for row in base_rows}
        output_docs = {row.get("document_id", "") for row in rows}
        modified_overlap = truth_docs & base_docs
        if modified_overlap:
            failures.append(f"truth_reuses_base_doc_ids:{sorted(modified_overlap)[:5]}")
        expected_docs = len(base_docs) + len(truth_docs)
        if len(output_docs) != expected_docs:
            failures.append(
                f"document_count_invariant:{len(output_docs)} expected:{expected_docs}"
            )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("overlay_document_count") != EXPECTED_TRUTH:
        failures.append(f"manifest_overlay_count:{manifest.get('overlay_document_count')}")
    if manifest.get("journal_label_exposed") is not False:
        failures.append("manifest_journal_label_exposed_not_false")

    summary = {
        "dataset": str(dataset),
        "truth_rows": len(truth),
        "seed_counts": dict(seed_counts),
        "patterns": dict(patterns),
        "truth_documents": len(truth_docs),
        "journal_rows": len(rows),
        "exact_value_oracle_findings": oracle_findings[:20],
        "distribution_leak_findings": distribution_findings[:20],
        "temporal_coherence_counts": dict(temporal_counts),
        "temporal_coherence_findings": temporal_findings[:20],
        "failures": failures,
    }
    reports = dataset / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "integrated_usefulness_phase1_gate.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
