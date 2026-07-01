from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.detection.topic_scoring import DEFAULT_COMBO_FLOORS  # noqa: E402
from tools.scripts import profile_phase1_v126 as phase1_profile  # noqa: E402

MATRIX_PATH = Path("dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md")
R11_RULES = {
    "L1-01",
    "L1-02",
    "L1-03",
    "L1-04",
    "L1-05",
    "L1-06",
    "L1-07",
    "L1-07-02",
    "L1-08",
    "L2-01",
    "L2-02",
    "L2-03",
    "L2-04",
    "L2-05",
    "L3-02",
    "L3-03",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-07",
    "L3-09",
    "L3-10",
    "L3-11",
    "L4-01",
    "L4-03",
    "L4-04",
}

EXPECTED_POLICIES = {
    "fictitious_entry_high": {
        "tier": "HIGH",
        "topic": "revenue_statistical",
        "rules_any": ({"L4-01", "L4-03"}, {"L3-02"}, {"L4-04", "L3-03", "L1-05", "L3-11", "L2-03"}),
    },
    "fictitious_entry_medium": {
        "tier": "MEDIUM",
        "topic": "revenue_statistical",
        "rules_any": ({"L4-01", "L4-03"}, {"L3-02"}),
    },
    "period_end_adjustment_high": {
        "tier": "HIGH",
        "topic": "closing_timing",
        "rules_any": ({"L3-04", "L3-11"}, {"L3-10", "L4-04", "L4-03"}),
    },
    "embezzlement_concealment_high": {
        "tier": "HIGH",
        "topic": "duplicate_outflow",
        "rules_any": (
            {"L2-02", "L2-03", "L2-05"},
            {"L1-04", "L1-05", "L1-06", "L1-07", "L1-07-02", "L3-02"},
        ),
    },
    "embezzlement_concealment_medium": {
        "tier": "MEDIUM",
        "topic": "duplicate_outflow",
        "rules_any": ({"L2-01"}, {"L1-05", "L1-06", "L1-07", "L1-07-02"}),
    },
    "suspense_concealment_high": {
        "tier": "HIGH",
        "topic": "duplicate_outflow",
        "rules_all": {"L3-09", "L4-03"},
        "rules_any": ({"L2-02", "L2-03", "L2-05"},),
    },
    "suspense_concealment_medium": {
        "tier": "MEDIUM",
        "topic": "duplicate_outflow",
        "rules_all": {"L3-09"},
        "rules_any": ({"L2-02", "L2-03", "L2-05"},),
    },
    "related_party_reversal_medium": {
        "tier": "MEDIUM",
        "topic": "duplicate_outflow",
        "rules_all": {"L2-05", "L3-03"},
    },
    "expense_capitalization_high": {
        "tier": "HIGH",
        "topic": "account_logic",
        "rules_all": {"L2-04", "L3-02"},
        "rules_any": ({"L4-03", "L3-04", "L1-06"},),
    },
    "expense_capitalization_medium": {
        "tier": "MEDIUM",
        "topic": "account_logic",
        "rules_all": {"L2-04", "L3-02"},
    },
    "rare_account_bypass_medium": {
        "tier": "MEDIUM",
        "topic": "account_logic",
        "rules_all": {"L4-04"},
        "rules_any": ({"L1-04", "L1-05", "L1-06", "L1-07", "L1-07-02"},),
    },
    "approval_bypass_high": {
        "tier": "HIGH",
        "topic": "approval_control",
        "rules_any": (
            {"L1-04", "L1-05", "L1-06", "L1-07", "L1-07-02"},
            {"L4-03", "L2-02", "L2-03"},
        ),
    },
}

BUILDABLE_SCHEMES = {
    "HIGH-1": "fictitious_entry_high",
    "HIGH-2": "embezzlement_concealment_high",
    "HIGH-3": "suspense_concealment_high",
    "HIGH-4": "period_end_adjustment_high",
    "HIGH-5": "approval_bypass_high",
    "HIGH-7": "related_party_reversal_medium",
    "HIGH-9": "expense_capitalization_high",
    "M-4A-1": "rare_account_bypass_medium",
    "M-4A-2": "embezzlement_concealment_medium",
    "M-4A-4": "related_party_reversal_medium",
    "M-4B-1": "fictitious_entry_medium",
    "M-4B-2": "suspense_concealment_medium",
    "M-4B-3": "expense_capitalization_medium",
}

OUT_OF_SCOPE_SCHEMES = {"HIGH-6", "HIGH-8", "HIGH-10", "M-4A-3"}
CONTROL_SCHEMES = {"LOW", "CONTEXT"}
REQUIRED_TRUTH_COLUMNS = {
    "combo_scheme_id",
    "case_kind",
    "expected_case_tier",
    "expected_policy_id",
    "expected_topic",
    "expected_rule_ids",
    "expected_detector_outcome",
    "natural_unit_id",
    "member_document_ids",
    "source_contract",
}
L205_STRUCTURAL_COLUMNS = {
    "original_document_id",
    "reversal_document_id",
    "reference_document_id",
    "reversed_document_id",
    "reverse_document_id",
    "reversal_reason",
    "reversal_reason_code",
}
L205_JOURNAL_REQUIRED_COLUMNS = {
    "original_document_id",
    "reversal_document_id",
    "reversal_reason",
    "reversal_reason_code",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", nargs="?", type=Path)
    parser.add_argument("--matrix-only", action="store_true")
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _split_rules(value: str) -> set[str]:
    if not value:
        return set()
    text = value.strip()
    if text.startswith("["):
        return {str(v) for v in json.loads(text)}
    return {part.strip() for part in text.replace("|", ",").split(",") if part.strip()}


def _truth_path(dataset: Path) -> Path | None:
    candidates = [
        dataset / "labels" / "phase1_combo_tier_truth.csv",
        dataset / "labels" / "p3_2_rule_truth.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _journal_columns(dataset: Path) -> set[str]:
    path = dataset / "journal_entries.csv"
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        return {str(column) for column in next(reader, [])}


def _validate_l205_structural_preflight(dataset: Path) -> list[str]:
    failures: list[str] = []
    profile_missing = sorted(L205_STRUCTURAL_COLUMNS - set(phase1_profile.PHASE1_USECOLS))
    if profile_missing:
        failures.append(f"phase1_usecols_l205_structural_missing:{profile_missing}")
    journal_cols = _journal_columns(dataset)
    if not journal_cols:
        failures.append("journal_entries_missing_or_empty")
        return failures
    journal_missing = sorted(L205_JOURNAL_REQUIRED_COLUMNS - journal_cols)
    if journal_missing:
        failures.append(f"journal_l205_structural_columns_missing:{journal_missing}")
    return failures


def _validate_matrix() -> list[str]:
    failures: list[str] = []
    if not MATRIX_PATH.exists():
        failures.append(f"matrix_missing:{MATRIX_PATH}")
    policies = set(DEFAULT_COMBO_FLOORS)
    expected = set(EXPECTED_POLICIES)
    if policies != expected:
        failures.append(
            f"combo_policy_mismatch code={sorted(policies)} expected={sorted(expected)}"
        )
    bad_floors = {
        policy_id: value
        for policy_id, value in DEFAULT_COMBO_FLOORS.items()
        if (policy_id.endswith("_high") and value < 0.75)
        or (policy_id.endswith("_medium") and not (0.45 <= value < 0.75))
    }
    if bad_floors:
        failures.append(f"combo_floor_bad:{bad_floors}")
    used_rules: set[str] = set()
    for spec in EXPECTED_POLICIES.values():
        used_rules.update(spec.get("rules_all", set()))
        for group in spec.get("rules_any", ()):
            used_rules.update(group)
    missing_from_r11 = used_rules - R11_RULES
    if missing_from_r11:
        failures.append(f"combo_member_not_in_r11:{sorted(missing_from_r11)}")
    return failures


def _validate_truth(dataset: Path) -> list[str]:
    failures: list[str] = []
    path = _truth_path(dataset)
    if path is None:
        return ["truth_missing: labels/phase1_combo_tier_truth.csv or labels/p3_2_rule_truth.csv"]
    rows = _csv_rows(path)
    if path.name == "p3_2_rule_truth.csv":
        rows = [r for r in rows if r.get("truth_layer") == "phase1_combo_tier_overlay"]
    if not rows:
        return [f"truth_empty:{path}"]
    missing_columns = REQUIRED_TRUTH_COLUMNS - set(rows[0])
    if missing_columns:
        failures.append(f"truth_required_columns_missing:{sorted(missing_columns)}")
        return failures

    schemes = {r.get("combo_scheme_id", "") for r in rows}
    required = set(BUILDABLE_SCHEMES) | CONTROL_SCHEMES
    missing_schemes = required - schemes
    forbidden = (schemes & OUT_OF_SCOPE_SCHEMES) | {s for s in schemes if not s}
    if missing_schemes:
        failures.append(f"buildable_scheme_missing:{sorted(missing_schemes)}")
    if forbidden:
        failures.append(f"forbidden_or_blank_scheme_present:{sorted(forbidden)}")

    standards = [r for r in rows if r.get("case_kind") == "standard"]
    controls = [r for r in rows if r.get("case_kind") in {"boundary_control", "negative_control"}]
    if not standards:
        failures.append("standard_cases_missing")
    if not controls:
        failures.append("control_cases_missing")

    for row in rows:
        scheme = row.get("combo_scheme_id", "")
        policy = row.get("expected_policy_id", "")
        expected_policy = BUILDABLE_SCHEMES.get(scheme)
        if expected_policy and policy != expected_policy:
            failures.append(f"{scheme}:expected_policy_bad:{policy}!={expected_policy}")
        if scheme in CONTROL_SCHEMES and policy:
            failures.append(f"{scheme}:control_policy_must_be_blank:{policy}")
        if policy in EXPECTED_POLICIES:
            spec = EXPECTED_POLICIES[policy]
            if row.get("expected_case_tier") != spec["tier"]:
                failures.append(f"{scheme}:tier_bad:{row.get('expected_case_tier')}!={spec['tier']}")
            if row.get("expected_topic") != spec["topic"]:
                failures.append(f"{scheme}:topic_bad:{row.get('expected_topic')}!={spec['topic']}")
            rules = _split_rules(row.get("expected_rule_ids", ""))
            if not spec.get("rules_all", set()).issubset(rules):
                missing = sorted(spec.get("rules_all", set()) - rules)
                failures.append(f"{scheme}:rules_all_missing:{missing}")
            for group in spec.get("rules_any", ()):
                if not (rules & group):
                    failures.append(f"{scheme}:rules_any_missing_one_of:{sorted(group)}")
            if rules - R11_RULES:
                failures.append(f"{scheme}:rules_not_in_r11:{sorted(rules - R11_RULES)}")
    return failures[:100]


def main() -> int:
    args = _parse_args()
    failures = _validate_matrix()
    if not args.matrix_only:
        if args.dataset is None:
            failures.append("dataset_required_without_matrix_only")
        else:
            failures.extend(_validate_l205_structural_preflight(args.dataset))
            failures.extend(_validate_truth(args.dataset))
    report = {
        "status": "PASS" if not failures else "FAIL",
        "matrix": str(MATRIX_PATH),
        "expected_code_combo_policies": sorted(EXPECTED_POLICIES),
        "buildable_schemes": sorted(BUILDABLE_SCHEMES),
        "control_schemes": sorted(CONTROL_SCHEMES),
        "out_of_scope_schemes": sorted(OUT_OF_SCOPE_SCHEMES),
        "failures": failures,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
