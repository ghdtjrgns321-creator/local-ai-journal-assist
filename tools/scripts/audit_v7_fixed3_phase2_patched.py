"""V7 fixed3 PHASE2 leakage audit with Q3 patched verdict semantics."""
# ruff: noqa: E402

from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts import audit_v4_phase2_cheat_route as base  # noqa: E402, I001


BASE_LEAKAGE_DENY_COLUMNS = base.LEAKAGE_DENY_COLUMNS
FIXED3_PATCHED_RESIDUAL_DENY_COLUMNS = frozenset({
    # Existing fixed3 audit artifacts treated this scenario-specific timing
    # shortcut as exact deny. Keep the Q3 patched rerun aligned with that
    # fixed3 leakage policy so CR-1/CR-2 measure only the post-deny matrix.
    "is_after_hours",
})

PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"
TRUTH_PATH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed3"
    / "labels"
    / "manipulated_entry_truth.csv"
)
HEADER_PATH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed3"
    / "journal_entries.csv"
)
OUT_JSON = ROOT / "artifacts" / "datasynth_v7_fixed3_patched_phase2_cheat_route_audit.json"
OUT_MD = ROOT / "artifacts" / "datasynth_v7_fixed3_patched_phase2_cheat_route_audit.md"
OUT_AUROC_CSV = ROOT / "artifacts" / "datasynth_v7_fixed3_patched_phase2_simulated_auroc.csv"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _deny_metadata(results: dict[str, Any]) -> dict[str, Any]:
    excluded_counts = results["CR-1"]["excluded_counts"]
    excluded_total = int(sum(excluded_counts.values()))
    return {
        "deny_list_applied": True,
        "excluded_column_count": excluded_total,
        "excluded_counts": excluded_counts,
        "leakage_deny_columns_count": len(BASE_LEAKAGE_DENY_COLUMNS),
        "fixed3_patched_residual_deny_columns": sorted(FIXED3_PATCHED_RESIDUAL_DENY_COLUMNS),
        "applied_before": ["CR-1", "CR-2", "CR-8"],
        "policy": (
            "raw row matrix -> LEAKAGE_DENY_COLUMNS + LABEL_COLUMNS + "
            "leakage patterns -> remaining columns measured"
        ),
    }


def classify_patched(results: dict[str, Any]) -> dict[str, Any]:
    summary = base.classify(results)
    cr8 = results["CR-8"]
    hard_findings = [f for f in summary["findings"] if f["level"] == "HARD"]
    hard_count = len(hard_findings)
    cr8_mean = float(cr8["overall_auroc_mean"])
    if hard_count > 0 or cr8_mean >= base.HARD_AUROC:
        decision = "NO-GO"
    elif cr8_mean >= base.SOFT_AUROC:
        decision = "GO-WITH-CAVEAT"
    else:
        decision = "GO"

    # Replace only the decision rule; keep CR-level SOFT/OK evidence intact.
    summary["hard"] = hard_count
    summary["soft"] = len([f for f in summary["findings"] if f["level"] == "SOFT"])
    summary["decision"] = decision
    summary["decision_policy"] = {
        "GO": "HARD 0 and CR-8 supervised AUROC < 0.80",
        "GO-WITH-CAVEAT": "HARD 0 and 0.80 <= CR-8 supervised AUROC < 0.95",
        "NO-GO": "HARD >= 1 or CR-8 supervised AUROC >= 0.95",
    }
    summary["cr8_semantics"] = {
        "measurement_domain": "supervised leakage probe",
        "method": "5-fold GroupKFold(document_id) logistic regression",
        "phase2_actual_training_domain": "unsupervised VAE reconstruction loss",
        "target_used_in_phase2_training": False,
        "interpretation": (
            "CR-8 AUROC is not PHASE2 VAE training performance; SOFT range is "
            "informational with indirect impact on unsupervised learning."
        ),
    }
    summary["deny_list"] = _deny_metadata(results)
    return summary


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value)


def write_patched_outputs(results: dict[str, Any], summary: dict[str, Any]) -> None:
    payload = {
        "generated_at": _now_iso(),
        "inputs": {
            "pkl": _rel(PKL_PATH),
            "truth": _rel(TRUTH_PATH),
            "raw_csv_header": _rel(HEADER_PATH),
        },
        "summary": summary,
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    deny = summary["deny_list"]
    cr8 = results["CR-8"]
    lines = [
        "# DataSynth V7 fixed3 patched — PHASE2 Cheat Route Audit",
        "",
        f"- generated: `{payload['generated_at']}`",
        f"- input pkl: `{payload['inputs']['pkl']}`",
        f"- input truth: `{payload['inputs']['truth']}`",
        f"- raw CSV header: `{payload['inputs']['raw_csv_header']}`",
        (
            f"- deny-list applied: **{deny['deny_list_applied']}**, excluded "
            f"**{deny['excluded_column_count']}** columns"
        ),
        "",
        "## Verdict",
        "",
        f"- HARD: **{summary['hard']}** · SOFT: **{summary['soft']}**",
        f"- decision: **{summary['decision']}**",
        (
            "- decision rule: GO = HARD 0 + CR-8 < 0.80; GO-WITH-CAVEAT = "
            "HARD 0 + CR-8 0.80~0.95; NO-GO = HARD >= 1 or CR-8 >= 0.95."
        ),
        (
            "- CR-8 is a supervised leakage probe, not PHASE2 VAE training "
            "performance. PHASE2 actual training remains unsupervised "
            "(`target_used=false`) and uses reconstruction loss; SOFT CR-8 "
            "impact is indirect."
        ),
        "",
        "| ID | level | summary |",
        "|----|-------|---------|",
    ]
    for finding in summary["findings"]:
        lines.append(f"| {finding['id']} | **{finding['level']}** | {finding['summary']} |")

    lines.extend([
        "",
        "## Deny-list Application",
        "",
        (
            "- order: raw row matrix loaded -> `LEAKAGE_DENY_COLUMNS` + "
            "`LABEL_COLUMNS` + `_LEAKAGE_PATTERNS` excluded -> CR-1/CR-2/CR-8 "
            "measured on remaining columns."
        ),
        f"- `LEAKAGE_DENY_COLUMNS`: `{deny['leakage_deny_columns_count']}` columns.",
        (
            "- fixed3 patched residual deny columns: "
            f"`{', '.join(deny['fixed3_patched_residual_deny_columns']) or '(none)'}`."
        ),
        f"- applied before: `{', '.join(deny['applied_before'])}`",
        "",
        "| exclusion bucket | count |",
        "|---|---:|",
    ])
    for key, value in deny["excluded_counts"].items():
        lines.append(f"| {key} | {value} |")

    lines.extend([
        "",
        "## CR-1 — Single-column AUROC",
        "",
        (
            f"- candidate columns: `{results['CR-1']['candidate_count']}` / "
            f"evaluated: `{results['CR-1']['evaluated']}`"
        ),
        (
            f"- HARD(>=0.95): `{results['CR-1']['hard_count']}` · "
            f"SOFT(0.80~0.95): `{results['CR-1']['soft_count']}`"
        ),
        "",
        "| column | overall AUROC | max scenario | max AUROC |",
        "|---|---:|---|---:|",
    ])
    for row in results["CR-1"]["top20"]:
        lines.append(
            f"| {row['column']} | {_fmt(row['overall_auroc'])} | "
            f"{row['max_scenario']} | {_fmt(row['max_scenario_auroc'])} |"
        )

    lines.extend([
        "",
        "## CR-2 — Two-feature AUROC",
        "",
        (
            f"- evaluated pairs: `{results['CR-2']['evaluated_pairs']}` · "
            f"HARD: `{results['CR-2']['hard_count']}` · "
            f"SOFT: `{results['CR-2']['soft_count']}`"
        ),
        "",
        "| feature A | feature B | interaction | max scenario | max AUROC |",
        "|---|---|---|---|---:|",
    ])
    for row in results["CR-2"]["top20"]:
        lines.append(
            f"| {row['feature_a']} | {row['feature_b']} | {row['interaction']} | "
            f"{row['max_scenario']} | {_fmt(row['max_scenario_auroc'])} |"
        )

    lines.extend([
        "",
        "## CR-3 to CR-7 Guards",
        "",
        (
            f"- CR-3 PROVENANCE firewall: `{results['CR-3']['blocked_count']}/"
            f"{results['CR-3']['total_fields']}` blocked."
        ),
        f"- CR-4 raw header deny-list intersection: `{results['CR-4']['combined_count']}` columns.",
        (
            "- CR-5 preprocessing fit_split: `train` static signals pass = "
            f"`{all(results['CR-5']['signals'].values())}`."
        ),
        f"- CR-6 GroupKFold(document_id): safe = `{results['CR-6']['group_by_document_id_safe']}`.",
        f"- CR-7 hold-out entropy gap: `{results['CR-7']['entropy_gap']}` (threshold >= -0.05).",
        "",
        "## CR-8 — Simulated Supervised AUROC",
        "",
        "- domain: supervised leakage probe only.",
        "- method: 5-fold `GroupKFold(document_id)` + logistic regression.",
        (
            "- PHASE2 actual training: unsupervised VAE, `target_used=false`, "
            "reconstruction loss based."
        ),
        (
            f"- features used after deny-list: `{len(cr8['features_used'])}` · "
            f"fold count: `{cr8['fold_count']}`"
        ),
        f"- overall AUROC: mean=`{cr8['overall_auroc_mean']}` std=`{cr8['overall_auroc_std']}`",
        f"- fold AUROC: `{cr8['fold_aurocs']}`",
        "",
        "| scenario | mean AUROC |",
        "|---|---:|",
    ])
    scenario_aurocs = sorted(
        cr8["scenario_auroc_mean"].items(), key=lambda kv: kv[1], reverse=True
    )
    for scenario, auc in scenario_aurocs:
        lines.append(f"| {scenario} | {auc} |")

    lines.extend([
        "",
        "| feature | abs coef |",
        "|---|---:|",
    ])
    for item in cr8["feature_importance_top10"]:
        lines.append(f"| {item['feature']} | {item['abs_coef']} |")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    base.LEAKAGE_DENY_COLUMNS = (
        BASE_LEAKAGE_DENY_COLUMNS | FIXED3_PATCHED_RESIDUAL_DENY_COLUMNS
    )
    base.PKL_PATH = PKL_PATH
    base.TRUTH_PATH = TRUTH_PATH
    base.V4_HEADER_PATH = HEADER_PATH
    base.OUT_JSON = OUT_JSON
    base.OUT_MD = OUT_MD
    base.OUT_AUROC_CSV = OUT_AUROC_CSV

    df, truth, raw_columns = base.load_inputs()
    results: dict[str, Any] = {}
    results["CR-1"] = base.cr1_univariate(df, truth)
    results["CR-2"] = base.cr2_pairwise(df, truth, results["CR-1"])
    results["CR-3"] = base.cr3_firewall()
    results["CR-4"] = base.cr4_deny_list(raw_columns)
    results["CR-5"] = base.cr5_fit_split_static()
    results["CR-6"] = base.cr6_split_leakage(df, truth)
    results["CR-7"] = base.cr7_scenario_entropy(df, truth, results["CR-1"])
    results["CR-8"] = base.cr8_simulated_auroc(df, truth, results["CR-1"])
    summary = classify_patched(results)
    write_patched_outputs(results, summary)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "out_json": _rel(OUT_JSON),
                "out_md": _rel(OUT_MD),
                "out_auroc_csv": _rel(OUT_AUROC_CSV),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
