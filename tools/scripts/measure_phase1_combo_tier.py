from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.scripts.measure_phase1_detector_catch as detector_measure  # noqa: E402
import tools.scripts.profile_phase1_v126 as prof  # noqa: E402
from config.settings import get_settings  # noqa: E402
from src.detection.score_aggregator import aggregate_scores  # noqa: E402
from src.services.analysis_service import make_phase_settings  # noqa: E402


def _json_list(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        payload = json.loads(text)
        return [str(item) for item in payload if str(item)]
    return [part.strip() for part in text.replace("|", ",").split(",") if part.strip()]


def _read_truth(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "labels" / "phase1_combo_tier_truth.csv"
    if not path.exists():
        raise SystemExit(f"missing truth file: {path}")
    truth = pd.read_csv(path, dtype=str, low_memory=False)
    for column in ("member_document_ids", "expected_rule_ids"):
        if column in truth.columns:
            truth[column] = truth[column].map(_json_list)
        else:
            truth[column] = [[]] * len(truth)
    return truth


def _case_doc_set(case: Any) -> set[str]:
    docs = {str(hit.document_id) for hit in case.raw_rule_hits if str(hit.document_id)}
    docs.update(str(doc.document_id) for doc in case.documents if str(doc.document_id))
    return docs


def _case_rule_set(case: Any) -> set[str]:
    return {str(hit.rule_id) for hit in case.raw_rule_hits if str(hit.rule_id)}


def _truth_hit_rules(
    case: Any,
    expected_docs: set[str],
    detail_doc_rules: dict[str, set[str]] | None = None,
) -> set[str]:
    direct_rules = {
        str(hit.rule_id)
        for hit in case.raw_rule_hits
        if str(hit.rule_id) and str(hit.document_id) in expected_docs
    }
    if detail_doc_rules:
        for doc in expected_docs:
            direct_rules.update(detail_doc_rules.get(doc, set()))
    if _case_doc_set(case) & expected_docs:
        return direct_rules | _case_rule_set(case)
    return direct_rules


def _breakdown(case: Any, topic: str) -> dict[str, Any]:
    payload = (case.topic_score_breakdown or {}).get(topic, {})
    return payload if isinstance(payload, dict) else {}


def _breakdown_policy_ids(payload: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("fraud_combo_policy_ids", "combo_policy_ids"):
        value = payload.get(key, ())
        if isinstance(value, str):
            out.add(value)
        else:
            try:
                out.update(str(item) for item in value if str(item))
            except TypeError:
                continue
    return out


def _matches_standard(
    row: pd.Series,
    case: Any,
    detail_doc_rules: dict[str, set[str]] | None = None,
) -> tuple[bool, str]:
    expected_docs = set(row["member_document_ids"])
    expected_rules = set(row["expected_rule_ids"])
    expected_topic = str(row.get("expected_topic", "") or "")
    expected_tier = str(row.get("expected_case_tier", "") or "").upper()
    if not (_case_doc_set(case) & expected_docs):
        return False, "no_truth_doc_in_case"
    case_rules = _truth_hit_rules(case, expected_docs, detail_doc_rules)
    if not expected_rules.issubset(case_rules):
        missing = sorted(expected_rules - case_rules)
        return False, "expected_truth_doc_rules_missing:" + ",".join(missing)
    topic_breakdown = _breakdown(case, expected_topic)
    if not topic_breakdown:
        return False, f"topic_breakdown_missing:{expected_topic}"
    try:
        score = float(topic_breakdown.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    minimum = 0.75 if expected_tier == "HIGH" else 0.45 if expected_tier == "MEDIUM" else 0.0
    if score < minimum:
        return False, f"topic_score_low:{score}<{minimum}"
    return True, "matched"


def _matches_low_control(
    row: pd.Series,
    case: Any,
    detail_doc_rules: dict[str, set[str]] | None = None,
) -> tuple[bool, str]:
    expected_docs = set(row["member_document_ids"])
    if not (_case_doc_set(case) & expected_docs):
        return False, "no_truth_doc_in_case"
    expected_rules = set(row["expected_rule_ids"])
    case_rules = _truth_hit_rules(case, expected_docs, detail_doc_rules)
    if not expected_rules.issubset(case_rules):
        missing = sorted(expected_rules - case_rules)
        return False, "expected_truth_doc_rules_missing:" + ",".join(missing)
    if str(case.priority_band).lower() != "low":
        return False, f"tier_bad:{case.priority_band}!=LOW"
    topic_breakdown = _breakdown(case, str(row.get("expected_topic", "") or ""))
    has_combo = bool(topic_breakdown.get("has_combo_floor")) if topic_breakdown else False
    if has_combo:
        return False, "unexpected_combo_floor"
    return True, "matched_low_control"


def _detail_doc_rules(
    truth: pd.DataFrame,
    df: pd.DataFrame,
    details: dict[str, pd.Series],
) -> dict[str, set[str]]:
    truth_docs: set[str] = set()
    expected_rules: set[str] = set()
    for _, row in truth.iterrows():
        truth_docs.update(str(doc) for doc in row["member_document_ids"] if str(doc))
        expected_rules.update(str(rule) for rule in row["expected_rule_ids"] if str(rule))
    if not truth_docs or "document_id" not in df.columns:
        return {}
    doc_series = df["document_id"].astype(str)
    out: dict[str, set[str]] = {doc: set() for doc in truth_docs}
    for rule in expected_rules:
        series = details.get(rule)
        if series is None:
            continue
        positive = pd.to_numeric(series, errors="coerce").fillna(0.0).gt(0)
        positive_docs = set(doc_series.reindex(series.index)[positive].astype(str)) & truth_docs
        for doc in positive_docs:
            out.setdefault(doc, set()).add(rule)
    return out


def _measure_rows(
    truth: pd.DataFrame,
    cases: list[Any],
    detail_doc_rules: dict[str, set[str]] | None = None,
) -> pd.DataFrame:
    case_docs = [(_case_doc_set(case), case) for case in cases]
    rows: list[dict[str, Any]] = []
    for _, row in truth.iterrows():
        scheme = str(row.get("combo_scheme_id", "") or "")
        case_kind = str(row.get("case_kind", "") or "")
        expected_docs = set(row["member_document_ids"])
        candidates = [case for docs, case in case_docs if expected_docs and docs & expected_docs]
        matched_case = None
        status = "not_evaluated"

        if scheme == "CONTEXT":
            matched_case = candidates[0] if candidates else None
            if not candidates:
                status = "matched_context_no_rankable_case"
            else:
                status = "context_unexpected_rankable_case"
        elif scheme == "LOW":
            for case in candidates:
                ok, reason = _matches_low_control(row, case, detail_doc_rules)
                if ok:
                    matched_case = case
                    status = reason
                    break
                status = reason
        elif case_kind == "standard":
            for case in candidates:
                ok, reason = _matches_standard(row, case, detail_doc_rules)
                if ok:
                    matched_case = case
                    status = reason
                    break
                status = reason
        else:
            status = "unsupported_case_kind"

        observed_case = matched_case or (candidates[0] if candidates else None)
        rows.append(
            {
                "combo_scheme_id": scheme,
                "case_kind": case_kind,
                "expected_case_tier": row.get("expected_case_tier", ""),
                "expected_policy_id": row.get("expected_policy_id", ""),
                "expected_topic": row.get("expected_topic", ""),
                "expected_rule_ids": "|".join(row["expected_rule_ids"]),
                "member_document_count": len(expected_docs),
                "candidate_case_count": len(candidates),
                "observed_case_id": getattr(observed_case, "case_id", "") if observed_case else "",
                "observed_priority_band": getattr(observed_case, "priority_band", "")
                if observed_case
                else "",
                "observed_primary_topic": getattr(observed_case, "primary_topic", "")
                if observed_case
                else "",
                "observed_rule_ids": "|".join(sorted(_case_rule_set(observed_case)))
                if observed_case
                else "",
                "passed": status.startswith("matched"),
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def run(
    data_dir: Path,
    output_dir: Path | None = None,
    limit_rows: int | None = None,
) -> dict[str, Any]:
    out = output_dir or data_dir / "reports" / "phase1_combo_tier_case_measurement"
    out.mkdir(parents=True, exist_ok=True)
    checkpoint = out / "case_measurement_checkpoint.json"
    summary: dict[str, Any] = {
        "data_dir": str(data_dir),
        "started_at": datetime.now(UTC).isoformat(),
        "limit_rows": limit_rows,
        "stages": {},
    }
    checkpoint.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
    start = time.perf_counter()
    truth = _read_truth(data_dir)
    df, results, stage_summary = detector_measure.run_detectors(data_dir, out, limit_rows)
    summary["stages"].update(stage_summary.get("stages", {}))
    details = detector_measure.detail_map(results, df)
    detail_doc_rules = _detail_doc_rules(truth, df, details)

    settings = make_phase_settings(get_settings(), phase="phase1")
    aggregate = aggregate_scores(df, results, settings=settings)
    for column in aggregate.columns:
        df[column] = aggregate[column].values

    phase1_result = prof._profile_phase1_case_builder(  # noqa: SLF001 - measurement harness
        df,
        results,
        company_id="_anonymous",
        batch_id="phase1_combo_tier_measure",
        dataset_id=str(data_dir),
        phase1_case_config={"phase1_case": {}},
        checkpoint=checkpoint,
        summary=summary,
    )
    measurement = _measure_rows(truth, list(phase1_result.cases), detail_doc_rules)
    failures = measurement.loc[~measurement["passed"]].to_dict("records")
    summary.update(
        {
            "finished_at": datetime.now(UTC).isoformat(),
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "truth_rows": int(len(truth)),
            "case_count": int(len(phase1_result.cases)),
            "passed_rows": int(measurement["passed"].sum()),
            "failed_rows": int((~measurement["passed"]).sum()),
            "status": "PASS" if not failures else "FAIL",
            "failures": failures[:50],
        }
    )
    measurement.to_csv(out / "combo_tier_case_measurement.csv", index=False, encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "measurement.md").write_text(
        measurement.to_markdown(index=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--limit-rows", type=int, default=None)
    parser.add_argument("--expect-truth-rows", type=int, default=None)
    args = parser.parse_args()
    truth = _read_truth(args.data_dir)
    if args.expect_truth_rows is not None and len(truth) != args.expect_truth_rows:
        raise SystemExit(
            f"truth row count mismatch: expected {args.expect_truth_rows}, got {len(truth)}"
        )
    summary = run(args.data_dir, args.output_dir, args.limit_rows)
    print(json.dumps(summary, ensure_ascii=True, indent=2, default=str))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
