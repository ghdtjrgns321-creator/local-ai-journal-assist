"""Build v118 candidate with an explicit sidecar manifest.

Sidecars have different semantics. Some are detector-contract snapshots, some
are independent behavioral controls, and some are rule-truth context aliases.
This patch adds `labels/sidecar_manifest.csv/json` so evaluation code can avoid
mixing them.

No journal rows, labels, rule-truth membership, or sidecar rows are modified.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v117_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v118_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V118_CANDIDATE.md", "V118_SIDECAR_MANIFEST.json"}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V118_SIDECAR_MANIFEST.json")
        if all(path.exists() for path in required):
            return
        raise SystemExit(f"destination exists but is incomplete: {DEST}")

    source_resolved = SOURCE.resolve()
    dest_resolved = DEST.resolve()
    allowed_root = (ROOT / "data" / "journal" / "primary").resolve()
    if allowed_root not in dest_resolved.parents:
        raise SystemExit(f"refusing to write outside DataSynth root: {DEST}")

    for src in SOURCE.rglob("*"):
        rel = src.relative_to(source_resolved)
        dst = dest_resolved / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel.parts and rel.parts[0] == "labels":
            shutil.copy2(src, dst)
        else:
            os.link(src, dst)


def _cleanup_copied_version_files() -> list[str]:
    removed = []
    for path in DEST.iterdir():
        if not path.is_file() or path.name in KEEP_VERSION_FILES:
            continue
        if path.name.startswith("FREEZE_V") or re.match(r"^V\d+_", path.name):
            removed.append(path.name)
            path.unlink()
    return sorted(removed)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _csv_doc_count(path: Path) -> int | None:
    try:
        df = pd.read_csv(path, usecols=lambda column: column == "document_id", low_memory=False)
    except Exception:
        return None
    if "document_id" not in df.columns:
        return None
    return int(df["document_id"].dropna().astype(str).nunique())


def _csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _manifest_entry(
    stem: str,
    *,
    owner_rule: str,
    purpose: str,
    expected_detector_positive: str,
    allowed_for_independent_sidecar_eval: bool,
    semantics: str,
    reason: str,
) -> dict[str, Any]:
    path = LABELS / f"{stem}.csv"
    return {
        "sidecar_name": stem,
        "path": f"labels/{stem}.csv",
        "exists": path.exists(),
        "row_count": _csv_row_count(path) if path.exists() else 0,
        "document_count": _csv_doc_count(path) if path.exists() else None,
        "owner_rule": owner_rule,
        "purpose": purpose,
        "expected_detector_positive": expected_detector_positive,
        "allowed_for_independent_sidecar_eval": bool(allowed_for_independent_sidecar_eval),
        "semantics": semantics,
        "reason": reason,
        "source_candidate": "v118",
    }


def _known_manifest_entries() -> list[dict[str, Any]]:
    entries = [
        _manifest_entry(
            "delegated_approval_controls",
            owner_rule="L1-07/L1-09",
            purpose="realism_control",
            expected_detector_positive="false",
            allowed_for_independent_sidecar_eval=True,
            semantics="Approval trace exists through delegation; should not be direct approval-missing truth.",
            reason="Independent L1 approval boundary control.",
        ),
        _manifest_entry(
            "late_approval_boundary_controls",
            owner_rule="L1-07/L1-09",
            purpose="realism_control",
            expected_detector_positive="false",
            allowed_for_independent_sidecar_eval=True,
            semantics="Approval exists but is late; not direct skipped-approval or approval-date-missing truth.",
            reason="Independent L1 approval timing boundary control.",
        ),
        _manifest_entry(
            "post_approval_change_controls",
            owner_rule="L1 approval downstream",
            purpose="realism_control",
            expected_detector_positive="null",
            allowed_for_independent_sidecar_eval=True,
            semantics="Post-approval change/reapproval triage context, not direct L1 field-gap truth.",
            reason="Realistic downstream approval workflow control.",
        ),
        _manifest_entry(
            "approver_master_mapping_issues",
            owner_rule="L1-04/L1-07/L1-09",
            purpose="realism_control",
            expected_detector_positive="null",
            allowed_for_independent_sidecar_eval=True,
            semantics="Approver exists in journal but master mapping is ambiguous or missing.",
            reason="Realistic master-data boundary control.",
        ),
        _manifest_entry(
            "l1_realism_normal_controls",
            owner_rule="L1",
            purpose="realism_control",
            expected_detector_positive="false",
            allowed_for_independent_sidecar_eval=True,
            semantics="Normal-looking L1 examples for realism and boundary testing.",
            reason="Broad independent L1 normal control pool.",
        ),
        _manifest_entry(
            "sod_review_population",
            owner_rule="L1-06/L3-12",
            purpose="review_population",
            expected_detector_positive="false_for_L1_06_direct",
            allowed_for_independent_sidecar_eval=True,
            semantics="Broad SoD review signal, explicitly not L1-06 direct truth.",
            reason="Useful as review-population sidecar, not as L1-06 direct truth.",
        ),
        _manifest_entry(
            "wrong_period_non_audit_issue_truth",
            owner_rule="L1-08",
            purpose="rule_truth_but_not_audit_issue",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="L1-08 rule truth but not injected audit issue.",
            reason="Contract/field semantics context; do not mix into independent realism eval.",
        ),
        _manifest_entry(
            "wrongperiod_negative_controls",
            owner_rule="L1-08",
            purpose="legacy_alias",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="Legacy alias for wrong_period_non_audit_issue_truth; not a true negative control.",
            reason="Retained for traceability only.",
        ),
        _manifest_entry(
            "skipped_approval_system_gap_controls",
            owner_rule="L1-07/L1-09",
            purpose="rule_truth_context",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="System/control-gap context that is connected to broad L1-07/L1-09 rule truth.",
            reason="Contract context, not independent normal control.",
        ),
        _manifest_entry(
            "skipped_approval_normal_controls",
            owner_rule="L1-07/L1-09",
            purpose="legacy_alias",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="Legacy alias for skipped_approval_system_gap_controls; name is misleading.",
            reason="Retained for gate compatibility only.",
        ),
        _manifest_entry(
            "system_control_gap_controls",
            owner_rule="L1-07/L1-09",
            purpose="rule_truth_context",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="System approval-flow gap context, often overlaps broad L1-07/L1-09 truth.",
            reason="Contract context, not independent normal control.",
        ),
        _manifest_entry(
            "duplicate_payment_pairs",
            owner_rule="L2-02",
            purpose="realism_control",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=True,
            semantics="Independent duplicate-payment pair metadata.",
            reason="Pair generation is not just detector output snapshot.",
        ),
        _manifest_entry(
            "duplicate_payment_negative_controls",
            owner_rule="L2-02",
            purpose="realism_control",
            expected_detector_positive="false_or_score_low",
            allowed_for_independent_sidecar_eval=True,
            semantics="Normal repeated-payment controls.",
            reason="Independent L2-02 negative control.",
        ),
        _manifest_entry(
            "duplicate_payment_review_population",
            owner_rule="L2-02",
            purpose="detector_contract_universe",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="Detector output snapshot.",
            reason="Use for contract verification only.",
        ),
        _manifest_entry(
            "duplicate_entry_confirmed_scenarios",
            owner_rule="L2-03",
            purpose="realism_control",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=True,
            semantics="Independent duplicate-entry confirmed scenario subset.",
            reason="Selected from labels and journal context, not detector output.",
        ),
        _manifest_entry(
            "duplicate_entry_negative_controls",
            owner_rule="L2-03",
            purpose="realism_control",
            expected_detector_positive="false_or_score_low",
            allowed_for_independent_sidecar_eval=True,
            semantics="Routine/system duplicate-lookalike controls.",
            reason="Independent L2-03 control sidecar.",
        ),
        _manifest_entry(
            "duplicate_entry_review_population",
            owner_rule="L2-03",
            purpose="detector_contract_universe",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="Detector output snapshot.",
            reason="Use for contract verification only.",
        ),
        _manifest_entry(
            "expense_capitalization_plausible_cases",
            owner_rule="L2-04",
            purpose="realism_control",
            expected_detector_positive="true_or_review",
            allowed_for_independent_sidecar_eval=True,
            semantics="Independent capitalization plausible cases.",
            reason="Selected from labels and journal context, not detector output.",
        ),
        _manifest_entry(
            "expense_capitalization_normal_capex_controls",
            owner_rule="L2-04",
            purpose="realism_control",
            expected_detector_positive="false_or_score_low_or_review",
            allowed_for_independent_sidecar_eval=True,
            semantics="Normal CAPEX/asset-context controls.",
            reason="Independent L2-04 control sidecar.",
        ),
        _manifest_entry(
            "expense_capitalization_review_population",
            owner_rule="L2-04",
            purpose="detector_contract_universe",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="Detector output snapshot.",
            reason="Use for contract verification only.",
        ),
        _manifest_entry(
            "reversal_pattern_plausible_cases",
            owner_rule="L2-05",
            purpose="realism_control",
            expected_detector_positive="true_or_review",
            allowed_for_independent_sidecar_eval=True,
            semantics="Independent reversal-pattern plausible cases.",
            reason="Selected from labels and journal context, not detector output.",
        ),
        _manifest_entry(
            "reversal_pattern_normal_clearing_controls",
            owner_rule="L2-05",
            purpose="realism_control",
            expected_detector_positive="false_or_score_low",
            allowed_for_independent_sidecar_eval=True,
            semantics="Normal clearing/settlement controls.",
            reason="Independent L2-05 control sidecar.",
        ),
        _manifest_entry(
            "reversal_entry_review_population",
            owner_rule="L2-05",
            purpose="detector_contract_universe",
            expected_detector_positive="true",
            allowed_for_independent_sidecar_eval=False,
            semantics="Detector output snapshot.",
            reason="Use for contract verification only.",
        ),
    ]
    return entries


def _infer_unlisted_sidecars(known_names: set[str]) -> list[dict[str, Any]]:
    inferred = []
    for path in sorted(LABELS.glob("*.csv")):
        stem = path.stem
        if YEAR_SUFFIX_RE.search(stem) or stem in known_names or stem.startswith("rule_truth_"):
            continue
        lower = stem.lower()
        if "review_population" in lower:
            purpose = "review_population"
            expected = "null"
            allowed = False
            semantics = "Unclassified review population. Treat as non-independent unless explicitly listed."
        elif "normal_control" in lower or "negative_control" in lower or "boundary" in lower:
            purpose = "realism_control"
            expected = "null"
            allowed = True
            semantics = "Inferred control sidecar. Review manually before using as independent eval."
        elif "manifest" in lower:
            purpose = "contract_manifest"
            expected = "null"
            allowed = False
            semantics = "Manifest/log file, not an evaluation sidecar."
        else:
            purpose = "contract_manifest"
            expected = "null"
            allowed = False
            semantics = "Unclassified sidecar. Do not use for independent eval until classified."
        inferred.append(
            _manifest_entry(
                stem,
                owner_rule="unclassified",
                purpose=purpose,
                expected_detector_positive=expected,
                allowed_for_independent_sidecar_eval=allowed,
                semantics=semantics,
                reason="Automatically inferred by filename pattern.",
            )
        )
    return inferred


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        if "source_candidate" in df.columns:
            df = df.drop(columns=["source_candidate"])
        if "truth_contract_version" in df.columns:
            df = df.drop(columns=["truth_contract_version"])
        df["source_candidate"] = "v118"
        df["truth_contract_version"] = "v118_active_candidate_contract"
        df.to_csv(path, index=False)
        _write_json_records(path.with_suffix(".json"), df)
        count += 1
        if "fiscal_year" in df.columns:
            for year in YEARS:
                year_path = LABELS / f"{path.stem}_{year}.csv"
                if year_path.exists():
                    year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
                    year_df.to_csv(year_path, index=False)
                    _write_json_records(year_path.with_suffix(".json"), year_df)
    return count


def _rebuild_combined_rule_truth() -> dict[str, int]:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        frames.append(pd.read_csv(path, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    _write_json_records(LABELS / "rule_truth.json", combined)
    return {
        str(rule): int(count)
        for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()
    }


def _legacy_source_count() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, usecols=lambda column: column == "source_candidate", low_memory=False)
        values = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        if values != ["v118"]:
            count += 1
    return count


def main() -> int:
    _copy_candidate_fast()
    old_manifest_files = _cleanup_copied_version_files()
    known = _known_manifest_entries()
    inferred = _infer_unlisted_sidecars({entry["sidecar_name"] for entry in known})
    manifest = pd.DataFrame(known + inferred).sort_values(["purpose", "owner_rule", "sidecar_name"])
    manifest.to_csv(LABELS / "sidecar_manifest.csv", index=False)
    _write_json_records(LABELS / "sidecar_manifest.json", manifest)

    normalized_truth_files = _normalize_rule_truth_metadata()
    rule_counts = _rebuild_combined_rule_truth()
    legacy_source_files = _legacy_source_count()
    if legacy_source_files:
        raise SystemExit(f"legacy rule_truth source metadata remains: {legacy_source_files}")

    purpose_counts = manifest["purpose"].value_counts().sort_index().to_dict()
    independent_count = int(manifest["allowed_for_independent_sidecar_eval"].astype(bool).sum())
    summary = {
        "candidate_version": "v118",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "add labels/sidecar_manifest.csv/json with sidecar purpose classification",
        "manifest_rows": int(len(manifest)),
        "purpose_counts": {str(k): int(v) for k, v in purpose_counts.items()},
        "allowed_for_independent_sidecar_eval": independent_count,
        "normalized_rule_truth_files": normalized_truth_files,
        "legacy_rule_truth_source_files": legacy_source_files,
        "removed_copied_version_manifests": old_manifest_files,
        "rule_counts": rule_counts,
        "note": (
            "Review-population files may be detector-contract snapshots. Use the manifest "
            "to decide whether a sidecar is allowed for independent behavioral evaluation."
        ),
    }
    (DEST / "V118_SIDECAR_MANIFEST.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V118_CANDIDATE.md").write_text(
        "# DataSynth v118 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: sidecar purpose manifest. No journal rows or truth membership changed.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    _cleanup_copied_version_files()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
