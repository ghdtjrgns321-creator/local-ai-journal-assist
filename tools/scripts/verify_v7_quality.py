"""Verify DataSynth manipulation V7 candidate against the five quality gates.

Read-only against input datasets. Produces aggregate-only artifacts:
- artifacts/datasynth_v7_quality_verification.json
- artifacts/datasynth_v7_quality_verification.md
- tests/datasynth_quality_gate3/results/manipulation_v7_candidate_truth_check.json

The default V7 input is
``data/journal/primary/datasynth_manipulation_v7_candidate``. If it is absent,
the script checks the fallback candidate names used during V7 handoff.
"""

# ruff: noqa: E501,I001

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
V4 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v4_candidate"
V5_FIXED9 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v5_candidate_fixed9"
DEFAULT_V7 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v7_candidate"
FALLBACK_V7_NAMES = (
    "datasynth_manipulation_v5_candidate_fixed10",
    "datasynth_manipulation_v7_active",
    "v7_active",
)
OUT_JSON = ROOT / "artifacts" / "datasynth_v7_quality_verification.json"
OUT_MD = ROOT / "artifacts" / "datasynth_v7_quality_verification.md"
TRUTH_CHECK = (
    ROOT
    / "tests"
    / "datasynth_quality_gate3"
    / "results"
    / "manipulation_v7_candidate_truth_check.json"
)
ARTIFACT_STEM = "datasynth_v7_quality_verification"

PROVENANCE_COLUMNS = [
    "mutation_type",
    "mutation_reason",
    "mutation_base_event_type",
    "mutation_mutated_field",
    "mutation_original_value",
    "mutation_mutated_value",
]
PHASE2_DENY_DELEGATED_FEATURES = {
    "amount_magnitude",
    "supply_amount_invoice_amount",
    "approval_lag_abs",
}
GATE3_CATEGORY_A_OCCURRENCE = {
    "approval_contract_gap": (">= 5%", 0.05),
    "approval_matrix_gap": (">= 5%", 0.05),
    "near_threshold_ratio_to_limit": (">= 3%", 0.03),
    "days_backdated": (">= 2%", 0.02),
    "is_suspense_account": (">= 1%", 0.01),
    "is_intercompany": ("contract_v2 IC ratio maintained", 0.0),
    "master_counterparty_intercompany": ("contract_v2 IC ratio maintained", 0.0),
    "first_digit": ("Benford normal distribution", None),
}
GATE3_CATEGORY_B_OVERLAP = {
    "amount_magnitude": "normal distribution overlaps manipulation amount area",
    "supply_amount_invoice_amount": "normal distribution overlaps manipulation amount area",
    "approval_lag_abs": "normal distribution overlaps manipulation anachronism area",
}
BENFORD_EXPECTED = {digit: math.log10(1 + 1 / digit) for digit in range(1, 10)}
BENFORD_MAD_MARGINALLY_CONFORMING = 0.015
PROTECTED_SCENARIOS = [
    "approval_sod_bypass",
    "circular_related_party_transaction",
    "embezzlement_concealment",
    "expense_capitalization",
    "fictitious_entry",
    "period_end_adjustment_manipulation",
    "suspense_account_abuse",
    "unusual_timing_manipulation",
]
JOURNAL_USECOLS = [
    "document_id",
    "company_code",
    "fiscal_year",
    "posting_date",
    "document_date",
    "document_type",
    "source",
    "business_process",
    "semantic_scenario_id",
    "mutation_type",
    "mutation_base_event_type",
    "mutation_mutated_field",
    "mutation_original_value",
    "mutation_mutated_value",
    "mutation_reason",
    "detection_surface_hints",
    "created_by",
    "approved_by",
    "approval_date",
    "sod_violation",
    "invoice_amount",
    "supply_amount",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "local_amount",
    "line_text",
    "trading_partner",
    "is_suspense_account",
    "approval_contract_gap",
    "approval_matrix_gap",
    "near_threshold_ratio_to_limit",
    "days_backdated",
    "is_intercompany",
    "master_counterparty_intercompany",
    "approval_lag_abs",
]


def pct(numerator: float, denominator: float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def status_word(ok: bool | None) -> str:
    if ok is None:
        return "BLOCKED"
    return "PASS" if ok else "FAIL"


def table(rows: Iterable[Iterable[Any]]) -> str:
    return "\n".join("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def configure_outputs(output_stem: str | None = None, truth_check_name: str | None = None) -> None:
    global ARTIFACT_STEM, OUT_JSON, OUT_MD, TRUTH_CHECK

    if output_stem:
        ARTIFACT_STEM = output_stem
        OUT_JSON = ROOT / "artifacts" / f"{output_stem}.json"
        OUT_MD = ROOT / "artifacts" / f"{output_stem}.md"
    if truth_check_name:
        TRUTH_CHECK = (
            ROOT
            / "tests"
            / "datasynth_quality_gate3"
            / "results"
            / truth_check_name
        )


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_v7(cli_path: str | None) -> tuple[Path, list[str]]:
    candidates: list[Path] = []
    if cli_path:
        candidates.append((ROOT / cli_path).resolve() if not Path(cli_path).is_absolute() else Path(cli_path))
    candidates.append(DEFAULT_V7)
    candidates.extend(ROOT / "data" / "journal" / "primary" / name for name in FALLBACK_V7_NAMES)
    checked = [rel(path) for path in candidates]
    for path in candidates:
        if path.exists() and (path / "journal_entries.csv").exists():
            return path, checked
    return candidates[0], checked


def load_truth(dataset: Path) -> pd.DataFrame:
    truth = pd.read_csv(dataset / "labels" / "manipulated_entry_truth.csv", dtype=str, low_memory=False)
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def load_journal(dataset: Path) -> pd.DataFrame:
    header = pd.read_csv(dataset / "journal_entries.csv", nrows=0).columns
    usecols = [col for col in JOURNAL_USECOLS if col in header]
    df = pd.read_csv(dataset / "journal_entries.csv", usecols=usecols, dtype=str, low_memory=False)
    df["document_id"] = df["document_id"].astype(str)
    for amount_col in ("debit_amount", "credit_amount", "local_amount", "invoice_amount", "supply_amount"):
        if amount_col in df.columns:
            df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
    for numeric_col in (
        "approval_contract_gap",
        "approval_matrix_gap",
        "near_threshold_ratio_to_limit",
        "days_backdated",
        "approval_lag_abs",
    ):
        if numeric_col in df.columns:
            df[numeric_col] = pd.to_numeric(df[numeric_col], errors="coerce")
    for date_col in ("posting_date", "document_date", "approval_date"):
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df


def collect_account_records(obj: Any, parent_code: str | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        code = str(
            obj.get("account_code")
            or obj.get("account_number")
            or obj.get("account")
            or obj.get("code")
            or obj.get("gl_account")
            or parent_code
            or ""
        )
        if code and any(
            key in obj
            for key in ("account_type", "sub_type", "description", "long_description", "short_description", "name")
        ):
            record = dict(obj)
            record.setdefault("account_code", code)
            record.setdefault(
                "description",
                obj.get("description") or obj.get("long_description") or obj.get("short_description") or "",
            )
            records.append(record)
        for key, value in obj.items():
            next_parent = str(key) if str(key).isdigit() else code or parent_code
            records.extend(collect_account_records(value, next_parent))
    elif isinstance(obj, list):
        for value in obj:
            records.extend(collect_account_records(value, parent_code))
    return records


def load_accounts(dataset: Path) -> pd.DataFrame:
    raw = read_json(dataset / "chart_of_accounts.json")
    records = collect_account_records(raw)
    if not records:
        return pd.DataFrame(columns=["account_code", "account_type", "sub_type", "description", "name"])
    df = pd.DataFrame(records)
    df["account_code"] = df["account_code"].astype(str)
    for col in ("account_type", "sub_type", "description", "name"):
        if col not in df.columns:
            df[col] = ""
    return df.drop_duplicates(subset=["account_code", "account_type", "sub_type"], keep="first")


def grir_codes(accounts: pd.DataFrame) -> set[str]:
    text = (
        accounts.get("account_code", pd.Series(dtype=str)).fillna("").astype(str)
        + " "
        + accounts.get("sub_type", pd.Series(dtype=str)).fillna("").astype(str)
        + " "
        + accounts.get("description", pd.Series(dtype=str)).fillna("").astype(str)
        + " "
        + accounts.get("name", pd.Series(dtype=str)).fillna("").astype(str)
    ).str.lower()
    mask = (
        text.str.contains("gr/ir|gr-ir|goods receipt|invoice receipt", regex=True, na=False)
        | text.str.contains("입고|미착|검수|정산", regex=True, na=False)
    )
    codes = set(accounts.loc[mask, "account_code"].astype(str))
    codes.add("199100")
    return codes


def doc_summary(journal: pd.DataFrame, truth_docs: set[str]) -> pd.DataFrame:
    df = journal.copy()
    df["is_truth"] = df["document_id"].isin(truth_docs)
    df["is_revenue_line"] = df["gl_account"].astype(str).str.startswith("4") & df["credit_amount"].gt(0)
    df["is_suspense_bool"] = df.get("is_suspense_account", "").astype(str).str.lower().eq("true")
    df["is_intercompany_process"] = df["business_process"].fillna("").astype(str).eq("Intercompany")
    df["is_manual_source"] = df["source"].fillna("").astype(str).str.lower().isin({"manual", "adjustment"})
    df["is_weekend"] = df["posting_date"].dt.weekday.ge(5).fillna(False)
    df["is_self_approval"] = (
        df["created_by"].fillna("").astype(str).str.strip()
        == df["approved_by"].fillna("").astype(str).str.strip()
    ) & df["created_by"].fillna("").astype(str).str.strip().ne("")
    df["backdated_days_proxy"] = (df["posting_date"] - df["document_date"]).dt.days
    df["approval_lag_proxy"] = (df["approval_date"] - df["posting_date"]).dt.days.abs()
    near_masks = [df["local_amount"].abs().between(9_500_000, 10_500_000)]
    for amount_col in ("invoice_amount", "supply_amount"):
        if amount_col in df.columns:
            near_masks.append(df[amount_col].abs().between(9_500_000, 10_500_000))
    df["near_threshold_proxy"] = pd.concat(near_masks, axis=1).any(axis=1)
    first_digit = df["local_amount"].abs().round().astype("Int64").astype(str).str.extract(r"([1-9])", expand=False)
    df["first_digit_num"] = pd.to_numeric(first_digit, errors="coerce")

    grouped = df.groupby("document_id", sort=False)
    docs = grouped.agg(
        business_process=("business_process", "first"),
        document_type=("document_type", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        sod_violation=("sod_violation", "first"),
        is_truth=("is_truth", "max"),
        lines=("gl_account", "size"),
        has_revenue_line=("is_revenue_line", "max"),
        debit=("debit_amount", "sum"),
        credit=("credit_amount", "sum"),
        local_abs_max=("local_amount", lambda s: float(s.abs().max())),
        invoice_abs_max=("invoice_amount", lambda s: float(s.abs().max())) if "invoice_amount" in df.columns else ("local_amount", lambda s: 0.0),
        supply_abs_max=("supply_amount", lambda s: float(s.abs().max())) if "supply_amount" in df.columns else ("local_amount", lambda s: 0.0),
        manual=("is_manual_source", "max"),
        weekend=("is_weekend", "max"),
        self_approval=("is_self_approval", "max"),
        backdated_days=("backdated_days_proxy", "max"),
        near_threshold_proxy=("near_threshold_proxy", "max"),
        intercompany_proxy=("is_intercompany_process", "max"),
        suspense_proxy=("is_suspense_bool", "max"),
        approval_lag_abs=("approval_lag_proxy", "max"),
        first_digit=("first_digit_num", "max"),
    )
    for raw_col in (
        "approval_contract_gap",
        "approval_matrix_gap",
        "near_threshold_ratio_to_limit",
        "days_backdated",
        "approval_lag_abs",
    ):
        if raw_col in df.columns:
            docs[f"raw_{raw_col}"] = grouped[raw_col].max()
    docs["balanced"] = docs["debit"].sub(docs["credit"]).abs().le(1.0)
    return docs


def truth_taxonomy(base_truth: pd.DataFrame, cand_truth: pd.DataFrame, base_name: str, cand_name: str) -> dict[str, Any]:
    base_docs = set(base_truth["document_id"].astype(str))
    cand_docs = set(cand_truth["document_id"].astype(str))
    base_counts = base_truth["manipulation_scenario"].value_counts().sort_index().to_dict()
    cand_counts = cand_truth["manipulation_scenario"].value_counts().sort_index().to_dict()
    scenario_rows = {
        scenario: {
            base_name: int(base_counts.get(scenario, 0)),
            cand_name: int(cand_counts.get(scenario, 0)),
            "pass": int(base_counts.get(scenario, 0)) == int(cand_counts.get(scenario, 0)),
        }
        for scenario in sorted(set(base_counts) | set(cand_counts) | set(PROTECTED_SCENARIOS))
    }
    return {
        f"{base_name}_truth_docs": int(len(base_docs)),
        f"{cand_name}_truth_docs": int(len(cand_docs)),
        f"{base_name}_docs_subset_of_{cand_name}": base_docs.issubset(cand_docs),
        f"missing_{base_name}_docs_in_{cand_name}_count": int(len(base_docs - cand_docs)),
        f"new_{cand_name}_docs_count": int(len(cand_docs - base_docs)),
        "scenario_counts": scenario_rows,
        "scenario_counts_preserved": all(row["pass"] for row in scenario_rows.values()),
    }


def noise_floor(docs: pd.DataFrame) -> dict[str, Any]:
    normal = docs.loc[~docs["is_truth"]]
    return {
        "normal_docs": int(len(normal)),
        "manual_entry_pct": pct(normal["manual"].sum(), len(normal)),
        "weekend_posting_pct": pct(normal["weekend"].sum(), len(normal)),
        "self_approval_pct": pct(normal["self_approval"].sum(), len(normal)),
    }


def rank_auc(labels: pd.Series, scores: pd.Series) -> float | None:
    data = pd.DataFrame({"label": labels.astype(int), "score": pd.to_numeric(scores, errors="coerce")}).dropna()
    positives = int(data["label"].sum())
    negatives = int(len(data) - positives)
    if positives == 0 or negatives == 0:
        return None
    ranks = data["score"].rank(method="average")
    pos_rank_sum = float(ranks[data["label"].eq(1)].sum())
    auc = (pos_rank_sum - positives * (positives + 1) / 2) / (positives * negatives)
    if auc < 0.5:
        auc = 1.0 - auc
    return round(float(auc), 6)


def first_digit_benford_gap(digit: pd.Series) -> pd.Series:
    actual = digit.map(BENFORD_EXPECTED).fillna(0.0)
    return 1.0 - actual


def benford_profile(digit: pd.Series) -> dict[str, Any]:
    valid = pd.to_numeric(digit, errors="coerce").dropna().astype(int)
    valid = valid[valid.between(1, 9)]
    total = int(len(valid))
    actual = {d: 0.0 for d in range(1, 10)}
    if total:
        counts = valid.value_counts(normalize=True)
        actual = {d: round(float(counts.get(d, 0.0)), 6) for d in range(1, 10)}
    mad = round(sum(abs(actual[d] - BENFORD_EXPECTED[d]) for d in range(1, 10)) / 9, 6)
    digits_present = sorted(int(d) for d in valid.unique())
    return {
        "sample_size": total,
        "digits_present": digits_present,
        "actual_distribution": actual,
        "expected_distribution": {d: round(v, 6) for d, v in BENFORD_EXPECTED.items()},
        "mad": mad,
        "mad_target": f"<= {BENFORD_MAD_MARGINALLY_CONFORMING}",
        "pass": total > 0 and digits_present == list(range(1, 10)) and mad <= BENFORD_MAD_MARGINALLY_CONFORMING,
    }


def benford_profile_from_journal(journal: pd.DataFrame, truth_docs: set[str]) -> dict[str, Any]:
    normal_rows = journal.loc[~journal["document_id"].astype(str).isin(truth_docs)]
    amount = pd.to_numeric(normal_rows["local_amount"], errors="coerce").abs().round()
    digits = amount.astype("Int64").astype(str).str.extract(r"([1-9])", expand=False)
    return benford_profile(digits)


def distribution_overlap_profile(normal_scores: pd.Series, manipulation_scores: pd.Series) -> dict[str, Any]:
    normal_values = pd.to_numeric(normal_scores, errors="coerce").dropna()
    manipulation_values = pd.to_numeric(manipulation_scores, errors="coerce").dropna()
    if normal_values.empty or manipulation_values.empty:
        return {
            "normal_n": int(len(normal_values)),
            "manipulation_n": int(len(manipulation_values)),
            "overlap_count": 0,
            "overlap_exists": False,
            "pass": False,
        }

    manipulation_min = float(manipulation_values.min())
    manipulation_max = float(manipulation_values.max())
    overlap_mask = normal_values.between(manipulation_min, manipulation_max, inclusive="both")
    overlap_count = int(overlap_mask.sum())
    normal_quantiles = normal_values.quantile([0.5, 0.9, 0.95, 0.99, 1.0]).round(6).to_dict()
    manipulation_quantiles = manipulation_values.quantile([0.0, 0.5, 0.9, 0.95, 1.0]).round(6).to_dict()
    return {
        "normal_n": int(len(normal_values)),
        "manipulation_n": int(len(manipulation_values)),
        "normal_quantiles": {str(k): float(v) for k, v in normal_quantiles.items()},
        "manipulation_quantiles": {str(k): float(v) for k, v in manipulation_quantiles.items()},
        "manipulation_range": [round(manipulation_min, 6), round(manipulation_max, 6)],
        "normal_overlap_min": round(float(normal_values.loc[overlap_mask].min()), 6) if overlap_count else None,
        "normal_overlap_max": round(float(normal_values.loc[overlap_mask].max()), 6) if overlap_count else None,
        "overlap_count": overlap_count,
        "overlap_exists": overlap_count > 0,
        "pass": overlap_count > 0,
    }


def build_truth_check(dataset: Path, journal: pd.DataFrame, truth: pd.DataFrame, docs: pd.DataFrame) -> dict[str, Any]:
    label_dir = dataset / "labels"
    labels = pd.read_csv(label_dir / "anomaly_labels.csv", dtype=str, low_memory=False)
    forbidden = sorted(
        str(path.relative_to(dataset))
        for path in label_dir.glob("*")
        if path.name.startswith("rule_truth")
        or path.name.startswith("contract_")
        or "sidecar" in path.name
    )
    leakage_columns = [
        col
        for col in ["is_fraud", "fraud_type", "is_anomaly", "anomaly_type"]
        if col in journal.columns
    ]
    truth_docs = set(truth["document_id"].astype(str))
    label_docs = set(labels["document_id"].astype(str))
    truth_rows = journal.loc[journal["document_id"].astype(str).isin(truth_docs)]
    missing_provenance = {
        col: int(truth_rows[col].fillna("").astype(str).str.strip().eq("").sum())
        for col in PROVENANCE_COLUMNS
        if col in truth_rows.columns
    }
    failures: list[str] = []
    if truth_docs != label_docs:
        failures.append("truth/labels mismatch")
    if forbidden:
        failures.append("forbidden label files present")
    if leakage_columns:
        failures.append("leakage columns present")
    if any(value != 0 for value in missing_provenance.values()):
        failures.append("missing provenance")
    unbalanced_truth_docs = int((docs.loc[docs.index.isin(truth_docs), "balanced"] == False).sum())  # noqa: E712
    if unbalanced_truth_docs:
        failures.append("unbalanced truth docs")
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": rel(dataset),
        "status": "pass" if not failures else "fail",
        "truth_docs": int(len(truth_docs)),
        "label_docs": int(len(label_docs)),
        "forbidden_label_files": forbidden,
        "leakage_columns_present": leakage_columns,
        "missing_provenance_counts": missing_provenance,
        "unbalanced_truth_docs": unbalanced_truth_docs,
        "failures": failures,
    }
    TRUTH_CHECK.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def gate1(journal: pd.DataFrame, docs: pd.DataFrame, truth: pd.DataFrame, accounts: pd.DataFrame) -> dict[str, Any]:
    o2c_docs = docs.loc[docs["business_process"].eq("O2C") & docs["document_type"].eq("DR")]
    grir = grir_codes(accounts)
    p2p_cr = journal.loc[
        journal["business_process"].eq("P2P")
        & journal["document_type"].eq("KR")
        & journal["credit_amount"].gt(0)
    ]
    p2p_cr_grir = p2p_cr.loc[p2p_cr["gl_account"].astype(str).isin(grir)]
    self_approval_false = journal.loc[
        (
            journal["created_by"].fillna("").astype(str).str.strip()
            == journal["approved_by"].fillna("").astype(str).str.strip()
        )
        & journal["created_by"].fillna("").astype(str).str.strip().ne("")
        & journal["sod_violation"].fillna("").astype(str).str.lower().eq("false")
    ]
    zero_fillers = journal.loc[
        journal["debit_amount"].eq(0)
        & journal["credit_amount"].eq(0)
        & journal["local_amount"].eq(0)
    ]
    account_codes = set(accounts["account_code"].astype(str))
    checks = {
        "o2c_revenue_missing_docs": {
            "measured": int((~o2c_docs["has_revenue_line"]).sum()),
            "target": 0,
            "pass": int((~o2c_docs["has_revenue_line"]).sum()) == 0,
        },
        "p2p_credit_grir_rows": {
            "measured": int(len(p2p_cr_grir)),
            "target": 0,
            "pass": len(p2p_cr_grir) == 0,
        },
        "sod_self_approval_false_rows": {
            "measured": int(len(self_approval_false)),
            "target": 0,
            "pass": len(self_approval_false) == 0,
        },
        "zero_filler_rows": {
            "measured": int(len(zero_fillers)),
            "target": 0,
            "pass": len(zero_fillers) == 0,
        },
        "coa_15110_present": {"measured": "15110" in account_codes, "target": True, "pass": "15110" in account_codes},
        "coa_8030_present": {"measured": "8030" in account_codes, "target": True, "pass": "8030" in account_codes},
        "coa_8010_present": {"measured": "8010" in account_codes, "target": True, "pass": "8010" in account_codes},
        "truth_docs": {"measured": int(truth["document_id"].nunique()), "target": 620, "pass": int(truth["document_id"].nunique()) == 620},
    }
    return {"checks": checks, "pass": all(row["pass"] for row in checks.values())}


def gate2(v4_docs: pd.DataFrame, cand_docs: pd.DataFrame, v5_truth: pd.DataFrame, cand_truth: pd.DataFrame, guard: dict[str, Any] | None) -> dict[str, Any]:
    v4_noise = noise_floor(v4_docs)
    cand_noise = noise_floor(cand_docs)
    cand_truth_balance = cand_docs.loc[cand_docs["is_truth"], "balanced"]
    taxonomy = truth_taxonomy(v5_truth, cand_truth, "v5_fixed9", "v7")
    noise_delta = {
        key: round(float(cand_noise[key]) - float(v4_noise[key]), 6)
        for key in ("manual_entry_pct", "weekend_posting_pct")
    }
    block = {
        "balance": {
            "balanced_docs": int(cand_truth_balance.sum()),
            "total_docs": int(len(cand_truth_balance)),
            "balanced_pct": pct(cand_truth_balance.sum(), len(cand_truth_balance)),
            "pass": bool(cand_truth_balance.all()),
        },
        "truth_taxonomy": taxonomy,
        "noise_floor": {
            "v4": v4_noise,
            "v7": cand_noise,
            "delta_v7_minus_v4": noise_delta,
            "delta_within_10pp": all(abs(value) <= 0.10 for value in noise_delta.values()),
        },
        "accounting_substance_guard": {
            "source": "artifacts/manipulation_v5_candidate_guard_fixed9.json",
            "checks": (guard or {}).get("checks", {}),
            "pass": (guard or {}).get("status") == "pass",
        },
    }
    block["pass"] = (
        block["balance"]["pass"]
        and taxonomy["v5_fixed9_docs_subset_of_v7"]
        and taxonomy["scenario_counts_preserved"]
        and block["noise_floor"]["delta_within_10pp"]
        and block["accounting_substance_guard"]["pass"]
    )
    return block


def feature_series(docs: pd.DataFrame, feature: str) -> tuple[pd.Series, str]:
    if feature in {"approval_contract_gap", "approval_matrix_gap"}:
        raw = f"raw_{feature}"
        return (docs[raw].fillna(0), raw) if raw in docs.columns else (docs["self_approval"].astype(float), "self_approval_proxy")
    if feature == "near_threshold_ratio_to_limit":
        raw = "raw_near_threshold_ratio_to_limit"
        return (docs[raw].abs().fillna(0), raw) if raw in docs.columns else (docs["near_threshold_proxy"].astype(float), "near_threshold_proxy")
    if feature == "days_backdated":
        raw = "raw_days_backdated"
        return (docs[raw].clip(lower=0).fillna(0), raw) if raw in docs.columns else (docs["backdated_days"].clip(lower=0).fillna(0), "posting_minus_document_days")
    if feature == "is_suspense_account":
        return docs["suspense_proxy"].astype(float), "is_suspense_account"
    if feature in {"is_intercompany", "master_counterparty_intercompany"}:
        return docs["intercompany_proxy"].astype(float), "business_process_intercompany_proxy"
    if feature == "amount_magnitude":
        return docs["local_abs_max"].fillna(0), "local_abs_max"
    if feature == "supply_amount_invoice_amount":
        return docs[["supply_abs_max", "invoice_abs_max"]].max(axis=1).fillna(0), "max(supply_amount, invoice_amount)"
    if feature == "first_digit":
        return first_digit_benford_gap(docs["first_digit"]), "benford_expected_gap"
    if feature == "approval_lag_abs":
        raw = "raw_approval_lag_abs"
        return (docs[raw].abs().fillna(0), raw) if raw in docs.columns else (docs["approval_lag_abs"].fillna(0), "abs(approval_date-posting_date)")
    raise KeyError(feature)


def gate3(docs: pd.DataFrame, journal: pd.DataFrame | None = None) -> dict[str, Any]:
    labels = docs["is_truth"].astype(int)
    normal = docs.loc[~docs["is_truth"]]
    manipulation = docs.loc[docs["is_truth"]]
    checks = {}
    category_a_passes = []
    category_b_passes = []

    for feature, (occurrence_target, min_rate) in GATE3_CATEGORY_A_OCCURRENCE.items():
        scores, source = feature_series(docs, feature)
        auc = rank_auc(labels, scores)
        normal_scores = scores.loc[normal.index]
        normal_rate = None
        occurrence_pass = False
        distribution = None
        if feature == "first_digit":
            distribution = (
                benford_profile_from_journal(journal, set(manipulation.index.astype(str)))
                if journal is not None
                else benford_profile(normal["first_digit"])
            )
            occurrence_pass = bool(distribution["pass"])
        elif min_rate is not None:
            normal_rate = pct(normal_scores.gt(0).sum(), len(normal_scores))
            occurrence_pass = normal_rate >= min_rate if min_rate > 0 else normal_rate > 0
        else:
            occurrence_pass = True
        auroc_informational_pass = auc is not None and auc < 0.80
        checks[feature] = {
            "category": "A_occurrence_rate",
            "verdict_basis": "normal_occurrence_target",
            "source": source,
            "max_auroc": auc,
            "auroc_target": "< 0.80 informational only",
            "auroc_informational_pass": auroc_informational_pass,
            "normal_occurrence_rate": normal_rate,
            "normal_occurrence_target": occurrence_target,
            "normal_occurrence_pass": occurrence_pass,
            "normal_distribution": distribution,
            "pass": occurrence_pass,
        }
        category_a_passes.append(occurrence_pass)

    for feature, overlap_target in GATE3_CATEGORY_B_OVERLAP.items():
        scores, source = feature_series(docs, feature)
        auc = rank_auc(labels, scores)
        normal_scores = scores.loc[normal.index]
        manipulation_scores = scores.loc[manipulation.index]
        overlap = distribution_overlap_profile(normal_scores, manipulation_scores)
        auroc_expected_range = auc is not None and 0.80 <= auc <= 0.95
        checks[feature] = {
            "category": "B_distribution_overlap",
            "verdict_basis": "distribution_overlap",
            "source": source,
            "max_auroc": auc,
            "auroc_target": "0.80-0.95 expected/informational",
            "auroc_expected_range": auroc_expected_range,
            "delegated_to_phase2_denylist": feature in PHASE2_DENY_DELEGATED_FEATURES,
            "normal_occurrence_rate": None,
            "normal_occurrence_target": overlap_target,
            "normal_occurrence_pass": None,
            "distribution_overlap": overlap,
            "pass": bool(overlap["pass"]),
        }
        category_b_passes.append(bool(overlap["pass"]))

    category_a_pass = all(category_a_passes)
    category_b_pass = all(category_b_passes)
    return {
        "checks": checks,
        "category_verdicts": {
            "A_occurrence_rate": {
                "pass": category_a_pass,
                "basis": "Occurrence target only; AUROC is informational.",
                "columns": list(GATE3_CATEGORY_A_OCCURRENCE),
            },
            "B_distribution_overlap": {
                "pass": category_b_pass,
                "basis": "Normal tail distribution must overlap manipulation range; AUROC 0.80-0.95 is expected.",
                "columns": list(GATE3_CATEGORY_B_OVERLAP),
            },
        },
        "pass": category_a_pass and category_b_pass,
    }


def gate4(truth_check: dict[str, Any]) -> dict[str, Any]:
    missing_provenance = truth_check.get("missing_provenance_counts", {})
    block = {
        "status": truth_check.get("status"),
        "truth_docs": truth_check.get("truth_docs"),
        "label_docs": truth_check.get("label_docs"),
        "truth_docs_equal_label_docs": truth_check.get("truth_docs") == truth_check.get("label_docs"),
        "forbidden_label_files": truth_check.get("forbidden_label_files", []),
        "leakage_columns_present": truth_check.get("leakage_columns_present", []),
        "missing_provenance_counts": missing_provenance,
        "missing_provenance_all_zero": all(int(value) == 0 for value in missing_provenance.values()),
        "unbalanced_truth_docs": truth_check.get("unbalanced_truth_docs"),
    }
    block["pass"] = (
        block["status"] == "pass"
        and block["truth_docs_equal_label_docs"]
        and not block["forbidden_label_files"]
        and not block["leakage_columns_present"]
        and block["missing_provenance_all_zero"]
        and block["unbalanced_truth_docs"] == 0
    )
    return block


def gate5(v5_docs: pd.DataFrame, cand_docs: pd.DataFrame, v5_truth: pd.DataFrame, cand_truth: pd.DataFrame, journal: pd.DataFrame) -> dict[str, Any]:
    v5_noise = noise_floor(v5_docs)
    cand_noise = noise_floor(cand_docs)
    taxonomy = truth_taxonomy(v5_truth, cand_truth, "v5_fixed9", "v7")
    columns = set(journal.columns)
    mutation_cols = sorted(col for col in columns if col.startswith("mutation_"))
    scenario_cols = sorted(col for col in columns if "scenario" in col)
    block = {
        "normal_manual_entry_pct": {
            "v5_fixed9": v5_noise["manual_entry_pct"],
            "v7": cand_noise["manual_entry_pct"],
            "delta": round(cand_noise["manual_entry_pct"] - v5_noise["manual_entry_pct"], 6),
            "pass": abs(cand_noise["manual_entry_pct"] - v5_noise["manual_entry_pct"]) <= 0.10,
        },
        "normal_weekend_posting_pct": {
            "v5_fixed9": v5_noise["weekend_posting_pct"],
            "v7": cand_noise["weekend_posting_pct"],
            "delta": round(cand_noise["weekend_posting_pct"] - v5_noise["weekend_posting_pct"], 6),
            "pass": abs(cand_noise["weekend_posting_pct"] - v5_noise["weekend_posting_pct"]) <= 0.10,
        },
        "truth_docs_preserved": {
            "v5_fixed9": int(v5_truth["document_id"].nunique()),
            "v7": int(cand_truth["document_id"].nunique()),
            "pass": int(v5_truth["document_id"].nunique()) == 620 and int(cand_truth["document_id"].nunique()) == 620 and taxonomy["v5_fixed9_docs_subset_of_v7"],
        },
        "mutation_scenario_columns": {
            "mutation_columns": mutation_cols,
            "scenario_columns": scenario_cols,
            "detection_surface_hints_present": "detection_surface_hints" in columns,
            "pass": bool(mutation_cols) and bool(scenario_cols) and "detection_surface_hints" in columns,
        },
    }
    block["pass"] = all(row["pass"] for row in block.values())
    return block


def verdict(gates: dict[str, Any]) -> dict[str, Any]:
    gate_pass = {name: bool(block.get("pass", False)) for name, block in gates.items()}
    hard_failures: list[str] = []
    soft_failures: list[str] = []
    for name in ("gate_1_fixed9_generation_regression", "gate_3_enrichment_natural_occurrence"):
        if not gates[name]["pass"]:
            hard_failures.extend(key for key, row in gates[name]["checks"].items() if not row["pass"])
    for name in ("gate_2_accounting_substance", "gate_4_quality_gate3", "gate_5_no_new_defects"):
        if not gates[name]["pass"]:
            soft_failures.append(name)
    return {
        "gate_pass": gate_pass,
        "hard_failures": hard_failures,
        "soft_failures": soft_failures,
        "hard_failure_count": len(hard_failures),
        "soft_failure_count": len(soft_failures),
        "go_no_go": "GO" if all(gate_pass.values()) else "NO-GO",
    }


def blocked_result(v7: Path, checked: list[str]) -> dict[str, Any]:
    truth_check = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": rel(v7),
        "status": "blocked",
        "reason": "V7 candidate dataset not found",
        "checked_paths": checked,
    }
    TRUTH_CHECK.write_text(json.dumps(truth_check, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": rel(v7),
        "baseline": rel(V5_FIXED9),
        "mode": "read-only",
        "status": "BLOCKED",
        "blocked_reason": "No V7 candidate directory with journal_entries.csv was found.",
        "checked_paths": checked,
        "outputs": {
            "json": rel(OUT_JSON),
            "markdown": rel(OUT_MD),
            "truth_check": rel(TRUTH_CHECK),
        },
        "gates": {},
        "verdict": {
            "go_no_go": "BLOCKED",
            "hard_failures": ["v7_candidate_missing"],
            "soft_failures": [],
            "hard_failure_count": 1,
            "soft_failure_count": 0,
        },
    }
    return result


def write_markdown(result: dict[str, Any]) -> None:
    if result.get("status") == "BLOCKED":
        lines = [
            "# DataSynth V7 Candidate Quality Verification",
            "",
            f"- generated_at: `{result['generated_at']}`",
            f"- dataset: `{result['dataset']}`",
            f"- baseline: `{result['baseline']}`",
            "- mode: read-only",
            "- final verdict: **BLOCKED**",
            "",
            "## Blocker",
            "",
            result["blocked_reason"],
            "",
            "Checked paths:",
            "",
            *[f"- `{path}`" for path in result["checked_paths"]],
            "",
            "## Outputs",
            "",
            f"- `{result['outputs']['json']}`",
            f"- `{result['outputs']['markdown']}`",
            f"- `{result['outputs']['truth_check']}`",
        ]
        OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    gates = result["gates"]
    verdict_block = result["verdict"]
    g1 = gates["gate_1_fixed9_generation_regression"]["checks"]
    g2 = gates["gate_2_accounting_substance"]
    g3_block = gates["gate_3_enrichment_natural_occurrence"]
    g3 = g3_block["checks"]
    g4 = gates["gate_4_quality_gate3"]
    g5 = gates["gate_5_no_new_defects"]
    lines = [
        "# DataSynth V7 Candidate Quality Verification",
        "",
        f"- generated_at: `{result['generated_at']}`",
        f"- dataset: `{result['dataset']}`",
        f"- baseline: `{result['baseline']}`",
        "- mode: read-only",
        f"- final verdict: **{verdict_block['go_no_go']}**",
        f"- HARD failures: **{verdict_block['hard_failure_count']}**",
        f"- SOFT failures: **{verdict_block['soft_failure_count']}**",
        "",
        "## Gate Summary",
        "",
        table(
            [
                ["Gate", "Verdict"],
                ["---", "---"],
                ["Gate 1 - V5 fixed9 generation regression", status_word(gates["gate_1_fixed9_generation_regression"]["pass"])],
                ["Gate 2 - accounting substance", status_word(g2["pass"])],
                ["Gate 3 - enrichment criteria split", status_word(gates["gate_3_enrichment_natural_occurrence"]["pass"])],
                ["Gate 4 - quality_gate3", status_word(g4["pass"])],
                ["Gate 5 - no new defects", status_word(g5["pass"])],
            ]
        ),
        "",
        "## Gate 1 - V5 fixed9 Generation Regression",
        "",
        table(
            [
                ["Check", "Measured", "Target", "Verdict"],
                ["---", "---:", "---:", "---"],
                *[[key, row["measured"], row["target"], status_word(row["pass"])] for key, row in g1.items()],
            ]
        ),
        "",
        "## Gate 2 - Accounting Substance",
        "",
        table(
            [
                ["Check", "Measured", "Verdict"],
                ["---", "---:", "---"],
                ["Debit/credit balanced truth docs", f"{g2['balance']['balanced_docs']} / {g2['balance']['total_docs']} ({g2['balance']['balanced_pct']:.6f})", status_word(g2["balance"]["pass"])],
                ["V5 fixed9 truth docs subset of V7", g2["truth_taxonomy"]["v5_fixed9_docs_subset_of_v7"], status_word(g2["truth_taxonomy"]["v5_fixed9_docs_subset_of_v7"])],
                ["Truth scenario counts preserved", g2["truth_taxonomy"]["scenario_counts_preserved"], status_word(g2["truth_taxonomy"]["scenario_counts_preserved"])],
                ["Noise floor delta <= 10pp", g2["noise_floor"]["delta_v7_minus_v4"], status_word(g2["noise_floor"]["delta_within_10pp"])],
                ["Accounting substance guard", "8/8 expected from V5 fixed9 guard artifact" if g2["accounting_substance_guard"]["pass"] else "guard failed/missing", status_word(g2["accounting_substance_guard"]["pass"])],
            ]
        ),
        "",
        "## Gate 3 - Enrichment Criteria Split",
        "",
        "Category A is judged only by normal-population occurrence targets; AUROC is informational. Category B is judged by whether the normal tail overlaps the manipulation range; AUROC 0.80-0.95 is expected for these intrinsic manipulation signals.",
        "",
        table(
            [
                ["Category", "Basis", "Columns", "Verdict"],
                ["---", "---", "---", "---"],
                *[
                    [
                        key,
                        row["basis"],
                        ", ".join(row["columns"]),
                        status_word(row["pass"]),
                    ]
                    for key, row in g3_block["category_verdicts"].items()
                ],
            ]
        ),
        "",
        "### Category A - Occurrence Rate",
        "",
        table(
            [
                ["Column", "Source", "Max AUROC", "AUROC Role", "Normal Occurrence", "Occurrence Target", "Verdict"],
                ["---", "---", "---:", "---", "---:", "---", "---"],
                *[
                    [
                        key,
                        row["source"],
                        row["max_auroc"],
                        row["auroc_target"],
                        row["normal_occurrence_rate"]
                        if key != "first_digit"
                        else f"MAD={row['normal_distribution']['mad']}",
                        row["normal_occurrence_target"],
                        status_word(row["pass"]),
                    ]
                    for key, row in g3.items()
                    if row["category"] == "A_occurrence_rate"
                ],
            ]
        ),
        "",
        "### Category B - Distribution Overlap",
        "",
        table(
            [
                ["Column", "Source", "Max AUROC", "AUROC Role", "Manipulation Range", "Normal Overlap Count", "Verdict"],
                ["---", "---", "---:", "---", "---", "---:", "---"],
                *[
                    [
                        key,
                        row["source"],
                        row["max_auroc"],
                        row["auroc_target"],
                        row["distribution_overlap"]["manipulation_range"],
                        row["distribution_overlap"]["overlap_count"],
                        status_word(row["pass"]),
                    ]
                    for key, row in g3.items()
                    if row["category"] == "B_distribution_overlap"
                ],
            ]
        ),
        "",
        "## Gate 4 - quality_gate3",
        "",
        table(
            [
                ["Check", "Measured", "Verdict"],
                ["---", "---", "---"],
                ["status", g4["status"], status_word(g4["status"] == "pass")],
                ["truth_docs == label_docs", f"{g4['truth_docs']} == {g4['label_docs']}", status_word(g4["truth_docs_equal_label_docs"])],
                ["forbidden_label_files", g4["forbidden_label_files"], status_word(not g4["forbidden_label_files"])],
                ["leakage_columns_present", g4["leakage_columns_present"], status_word(not g4["leakage_columns_present"])],
                ["missing_provenance_counts all 0", g4["missing_provenance_counts"], status_word(g4["missing_provenance_all_zero"])],
                ["unbalanced_truth_docs", g4["unbalanced_truth_docs"], status_word(g4["unbalanced_truth_docs"] == 0)],
            ]
        ),
        "",
        "## Gate 5 - No New Defects",
        "",
        table(
            [
                ["Check", "Measured", "Verdict"],
                ["---", "---", "---"],
                ["normal manual_entry_pct V5 fixed9 +/- 10pp", g5["normal_manual_entry_pct"], status_word(g5["normal_manual_entry_pct"]["pass"])],
                ["normal weekend_posting_pct V5 fixed9 +/- 10pp", g5["normal_weekend_posting_pct"], status_word(g5["normal_weekend_posting_pct"]["pass"])],
                ["truth doc 620 preserved", g5["truth_docs_preserved"], status_word(g5["truth_docs_preserved"]["pass"])],
                ["mutation/scenario/detection columns", g5["mutation_scenario_columns"], status_word(g5["mutation_scenario_columns"]["pass"])],
            ]
        ),
        "",
        "## V6 to V7 Change Matrix",
        "",
        table(
            [
                ["Area", "V5 fixed9", "V7", "Classification"],
                ["---", "---", "---", "---"],
                ["Generation 8 checks", "PASS 7 + CoA 8010 unverified", status_word(gates["gate_1_fixed9_generation_regression"]["pass"]), "maintained" if gates["gate_1_fixed9_generation_regression"]["pass"] else "regression"],
                ["Accounting substance", "PASS", status_word(g2["pass"]), "maintained" if g2["pass"] else "regression"],
                ["Enrichment natural occurrence", "FAIL", status_word(gates["gate_3_enrichment_natural_occurrence"]["pass"]), "resolved" if gates["gate_3_enrichment_natural_occurrence"]["pass"] else "unresolved"],
                ["quality_gate3", "PASS", status_word(g4["pass"]), "maintained" if g4["pass"] else "regression"],
                ["No new defects", "PASS", status_word(g5["pass"]), "maintained" if g5["pass"] else "regression"],
            ]
        ),
        "",
        "## GO / NO-GO",
        "",
        f"V7 generation verification verdict: **{verdict_block['go_no_go']}**.",
        "",
        "HARD failures: "
        + (", ".join(verdict_block["hard_failures"]) if verdict_block["hard_failures"] else "none"),
        "",
        "SOFT failures: "
        + (", ".join(verdict_block["soft_failures"]) if verdict_block["soft_failures"] else "none"),
        "",
        "## Outputs",
        "",
        f"- `{result['outputs']['markdown']}`",
        f"- `{result['outputs']['json']}`",
        f"- `{result['outputs']['truth_check']}`",
        "- `tools/scripts/verify_v7_quality.py`",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(cli_path: str | None = None) -> dict[str, Any]:
    v7, checked = resolve_v7(cli_path)
    if not v7.exists() or not (v7 / "journal_entries.csv").exists():
        result = blocked_result(v7, checked)
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        write_markdown(result)
        return result

    v4_truth = load_truth(V4)
    v4_journal = load_journal(V4)
    v4_docs = doc_summary(v4_journal, set(v4_truth["document_id"]))
    v5_truth = load_truth(V5_FIXED9)
    v5_journal = load_journal(V5_FIXED9)
    v5_docs = doc_summary(v5_journal, set(v5_truth["document_id"]))
    v7_truth = load_truth(v7)
    v7_journal = load_journal(v7)
    v7_docs = doc_summary(v7_journal, set(v7_truth["document_id"]))
    v7_accounts = load_accounts(v7)
    truth_check = build_truth_check(v7, v7_journal, v7_truth, v7_docs)
    guard = read_json(ROOT / "artifacts" / "manipulation_v5_candidate_guard_fixed9.json")

    gates = {
        "gate_1_fixed9_generation_regression": gate1(v7_journal, v7_docs, v7_truth, v7_accounts),
        "gate_2_accounting_substance": gate2(v4_docs, v7_docs, v5_truth, v7_truth, guard),
        "gate_3_enrichment_natural_occurrence": gate3(v7_docs, v7_journal),
        "gate_4_quality_gate3": gate4(truth_check),
        "gate_5_no_new_defects": gate5(v5_docs, v7_docs, v5_truth, v7_truth, v7_journal),
    }
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": rel(v7),
        "baseline": rel(V5_FIXED9),
        "mode": "read-only",
        "inputs": {
            "manifest": next((rel(path) for path in v7.glob("*MANIFEST*.json")), None),
            "truth": rel(v7 / "labels" / "manipulated_entry_truth.csv"),
            "truth_check": rel(TRUTH_CHECK),
        },
        "outputs": {
            "json": rel(OUT_JSON),
            "markdown": rel(OUT_MD),
            "truth_check": rel(TRUTH_CHECK),
        },
        "gates": gates,
    }
    result["verdict"] = verdict(gates)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify DataSynth manipulation V7 candidate quality gates.")
    parser.add_argument("--dataset", default=None, help="Optional V7 dataset directory.")
    parser.add_argument("--output-stem", default=None, help="Artifact stem under artifacts/ without extension.")
    parser.add_argument("--truth-check-name", default=None, help="Truth-check JSON filename under tests/datasynth_quality_gate3/results/.")
    args = parser.parse_args()
    configure_outputs(args.output_stem, args.truth_check_name)
    result = run(args.dataset)
    print(
        json.dumps(
            {
                "out_json": rel(OUT_JSON),
                "out_md": rel(OUT_MD),
                "truth_check": rel(TRUTH_CHECK),
                "verdict": result["verdict"]["go_no_go"],
                "hard_failures": result["verdict"]["hard_failures"],
                "soft_failures": result["verdict"]["soft_failures"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
