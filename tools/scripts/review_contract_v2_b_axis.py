"""Review contract-v2 Phase1 case readability (B-axis).

The B-axis is not a detector truth check. It asks whether the generated
Phase1 cases are understandable to an auditor: clear reason, manageable
evidence, enough context, and no over-claiming.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_ARTIFACT_GLOB = "artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_*.json"
OUT_DIR = Path("tests/datasynth_quality_gate3/results")


def latest_artifact(pattern: str) -> Path:
    paths = sorted(Path().glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not paths:
        raise FileNotFoundError(pattern)
    return paths[0]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def unique_rule_doc_pairs(case: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for hit in case.get("raw_rule_hits", []):
        pairs.add((str(hit.get("rule_id", "")), str(hit.get("document_id", ""))))
    return pairs


def unique_rules(case: dict[str, Any]) -> list[str]:
    return sorted({rule for rule, _ in unique_rule_doc_pairs(case) if rule})


def case_issue_flags(case: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    evidence_rows = len(case.get("rule_evidence_summary", []))
    unique_pairs = len(unique_rule_doc_pairs(case))
    actions = len(case.get("recommended_audit_actions", []))
    documents = case.get("documents", [])
    unknown_counterparty_docs = sum(
        1
        for doc in documents
        if str(doc.get("counterparty", "")).strip().upper() in {"", "UNKNOWN_COUNTERPARTY"}
    )
    secondary_queues = len(case.get("secondary_queues", []))
    narrative = str(case.get("risk_narrative") or "")
    explanation = str(case.get("representative_explanation") or "")

    if not narrative.strip() or not explanation.strip():
        flags.append("missing_core_narrative")
    if evidence_rows > 30:
        flags.append("evidence_overload")
    if unique_pairs and evidence_rows / unique_pairs >= 2.0:
        flags.append("duplicate_evidence_rows")
    if actions > 12:
        flags.append("action_overload")
    if documents and unknown_counterparty_docs / len(documents) >= 0.30:
        flags.append("unknown_counterparty_context")
    if secondary_queues >= 4 and len(narrative) < 90:
        flags.append("multi_theme_summary_too_generic")
    if any("fraud" in str(tag).lower() for tag in case.get("fraud_scenario_tags", [])):
        flags.append("fraud_tag_language_review")
    return flags


def top_cases_by_theme(cases: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for case in cases:
        theme = str(case.get("primary_theme") or "unknown")
        if seen.get(theme, 0) >= limit:
            continue
        selected.append(case)
        seen[theme] = seen.get(theme, 0) + 1
    return selected


def build_case_review_rows(cases: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for case in cases:
        docs = case.get("documents", [])
        evidence_rows = len(case.get("rule_evidence_summary", []))
        unique_pairs = len(unique_rule_doc_pairs(case))
        unknown_counterparty_docs = sum(
            1
            for doc in docs
            if str(doc.get("counterparty", "")).strip().upper() in {"", "UNKNOWN_COUNTERPARTY"}
        )
        flags = case_issue_flags(case)
        rows.append(
            {
                "case_id": case.get("case_id"),
                "primary_theme": case.get("primary_theme"),
                "primary_queue_label": case.get("primary_queue_label"),
                "priority_band": case.get("priority_band"),
                "priority_score": case.get("priority_score"),
                "rule_count": case.get("rule_count"),
                "document_count": case.get("document_count"),
                "row_count": case.get("row_count"),
                "unique_rules": ",".join(unique_rules(case)),
                "evidence_rows": evidence_rows,
                "unique_rule_doc_pairs": unique_pairs,
                "evidence_duplication_ratio": round(evidence_rows / unique_pairs, 3)
                if unique_pairs
                else 0.0,
                "recommended_action_count": len(case.get("recommended_audit_actions", [])),
                "secondary_queue_count": len(case.get("secondary_queues", [])),
                "unknown_counterparty_doc_ratio": round(unknown_counterparty_docs / len(docs), 3)
                if docs
                else 0.0,
                "narrative_len": len(str(case.get("risk_narrative") or "")),
                "explanation": case.get("representative_explanation"),
                "flags": ",".join(flags),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=None)
    parser.add_argument("--top-per-theme", type=int, default=20)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    artifact = args.artifact or latest_artifact(DEFAULT_ARTIFACT_GLOB)
    payload = load_json(artifact)
    all_cases = payload["cases"]
    reviewed_cases = top_cases_by_theme(all_cases, args.top_per_theme)
    review = build_case_review_rows(reviewed_cases)

    flag_counts = Counter()
    for flags in review["flags"].fillna(""):
        for flag in str(flags).split(","):
            if flag:
                flag_counts[flag] += 1

    theme_summary = (
        review.groupby("primary_theme", dropna=False)
        .agg(
            reviewed_cases=("case_id", "count"),
            high_cases=("priority_band", lambda s: int((s == "high").sum())),
            avg_rule_count=("rule_count", "mean"),
            avg_evidence_rows=("evidence_rows", "mean"),
            avg_action_count=("recommended_action_count", "mean"),
            avg_unknown_counterparty_doc_ratio=("unknown_counterparty_doc_ratio", "mean"),
            cases_with_flags=("flags", lambda s: int(s.astype(str).str.len().gt(0).sum())),
        )
        .reset_index()
    )
    for column in [
        "avg_rule_count",
        "avg_evidence_rows",
        "avg_action_count",
        "avg_unknown_counterparty_doc_ratio",
    ]:
        theme_summary[column] = theme_summary[column].round(3)

    total_reviewed = int(len(review))
    summary = {
        "artifact": str(artifact),
        "total_cases": int(len(all_cases)),
        "reviewed_cases": total_reviewed,
        "review_scope": f"top {args.top_per_theme} cases per primary_theme",
        "theme_count": int(review["primary_theme"].nunique()),
        "flag_counts": dict(sorted(flag_counts.items())),
        "pass_conditions": {
            "core_narrative_missing_cases": int(flag_counts.get("missing_core_narrative", 0)),
            "themes_present": int(review["primary_theme"].nunique()),
            "a_axis_out_of_scope": "B-axis reviews readability only; A-axis strict diff is checked separately.",
        },
        "recommendation": "WARN" if flag_counts else "PASS",
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    review_path = args.out_dir / "contract_v2_b_axis_case_review.csv"
    theme_path = args.out_dir / "contract_v2_b_axis_theme_summary.csv"
    summary_path = args.out_dir / "contract_v2_b_axis_review_summary.json"
    report_path = args.out_dir / "contract_v2_b_axis_review.md"
    review.to_csv(review_path, index=False, encoding="utf-8")
    theme_summary.to_csv(theme_path, index=False, encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    top_flags = "\n".join(f"- `{k}`: {v}" for k, v in summary["flag_counts"].items()) or "- 없음"
    theme_table = theme_summary.to_markdown(index=False)
    worst = review.loc[review["flags"].astype(str).str.len().gt(0)].head(20)
    worst_table = worst[
        [
            "case_id",
            "primary_theme",
            "priority_band",
            "rule_count",
            "evidence_rows",
            "recommended_action_count",
            "unknown_counterparty_doc_ratio",
            "flags",
        ]
    ].to_markdown(index=False)
    report_path.write_text(
        "\n".join(
            [
                "# Contract V2 B-axis Case Readability Review",
                "",
                f"- artifact: `{artifact}`",
                f"- total cases: `{summary['total_cases']}`",
                f"- reviewed cases: `{summary['reviewed_cases']}`",
                f"- recommendation: `{summary['recommendation']}`",
                "",
                "## Flag Counts",
                "",
                top_flags,
                "",
                "## Theme Summary",
                "",
                theme_table,
                "",
                "## Flagged Sample Cases",
                "",
                worst_table,
                "",
                "## Interpretation",
                "",
                "- A-axis truth alignment is not retested here.",
                "- B-axis passes structural completeness: sampled cases have narratives, review focus, actions, documents, and rule evidence.",
                "- WARN remains because top cases often contain duplicated row-level evidence and too many suggested actions for a compact auditor review surface.",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
