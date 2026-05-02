"""Evaluate DataSynth L3 A/B/C axes in one L3-only pass.

This is intentionally a thin wrapper around eval_datasynth_l3_only.py so the
expensive L3 feature/rule execution is not repeated for A, B, and C summaries.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.scripts.eval_datasynth_l3_only import (
    L3_RULE_IDS,
    RuleMetric,
    add_l3_features,
    detected_doc_set,
    detected_user_year_set,
    load_candidate,
    metric,
    run_l3_only,
    truth_doc_set,
    truth_l312_candidate_user_year_set,
    truth_user_year_set,
)

YEARS = (2022, 2023, 2024)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--years", nargs="+", type=int, default=list(YEARS))
    parser.add_argument("--timings", action="store_true")
    return parser.parse_args()


def _score_docs(df: pd.DataFrame, result: pd.Series, detected: set[str]) -> set[str]:
    if hasattr(result, "attrs") and result.attrs.get("score_series") is not None:
        scores = pd.Series(result.attrs["score_series"], index=df.index).fillna(0.0).astype(float)
        return set(df.loc[scores.gt(0), "document_id"].dropna().astype(str).unique()) & detected
    if pd.api.types.is_numeric_dtype(result):
        scores = pd.Series(result, index=df.index).fillna(0.0).astype(float)
        return set(df.loc[scores.gt(0), "document_id"].dropna().astype(str).unique()) & detected
    return set(detected)


def _review_docs(df: pd.DataFrame, result: pd.Series, universe: set[str]) -> set[str]:
    if not hasattr(result, "attrs") or result.attrs.get("review_score_series") is None:
        return set()
    scores = pd.Series(result.attrs["review_score_series"], index=df.index).fillna(0.0).astype(float)
    return set(df.loc[scores.gt(0), "document_id"].dropna().astype(str).unique()) & universe


def build_rule_sets(data_dir: Path, df: pd.DataFrame, results: dict[str, pd.Series], years: list[int]):
    year_set = set(years)
    rule_sets: dict[str, dict[str, set]] = {}
    for rule_id in L3_RULE_IDS:
        result = results[rule_id]
        if rule_id == "L3-12":
            truth = truth_user_year_set(data_dir, year_set)
            detected: set[tuple[int, str]] = set()
            candidate_truth = truth_l312_candidate_user_year_set(data_dir, year_set)
            candidate_detected: set[tuple[int, str]] = set()
            for year in years:
                detected.update(detected_user_year_set(df, result, year, mode="scored"))
                candidate_detected.update(
                    detected_user_year_set(df, result, year, mode="candidate")
                )
            rule_sets["L3-12"] = {"truth": truth, "detected": detected}
            rule_sets["L3-12-CAND"] = {
                "truth": candidate_truth,
                "detected": candidate_detected,
                "scored_detected": detected,
            }
            continue

        truth = truth_doc_set(data_dir, rule_id, year_set)
        detected: set[str] = set()
        for year in years:
            detected.update(detected_doc_set(df, result, year))
        rule_sets[rule_id] = {"truth": truth, "detected": detected}
    return rule_sets


def print_a_axis(totals: list[RuleMetric]) -> None:
    print("\nA_AXIS_TOTAL")
    print("rule\ttruth\tdetected\ttp\tfp\tfn")
    for item in totals:
        print(
            f"{item.rule_id}\t{item.truth_count}\t{item.detected_count}\t"
            f"{item.tp_count}\t{item.fp_count}\t{item.fn_count}"
        )


def b_axis(df: pd.DataFrame, results: dict[str, pd.Series], rule_sets: dict[str, dict[str, set]]):
    rows: list[tuple[str, str, int, int, int, int, int]] = []
    for rule_id in L3_RULE_IDS:
        result = results[rule_id]
        if rule_id == "L3-12":
            truth = rule_sets["L3-12"]["truth"]
            detected = rule_sets["L3-12"]["detected"]
            candidate_truth = rule_sets["L3-12-CAND"]["truth"]
            candidate_detected = rule_sets["L3-12-CAND"]["detected"]
            rows.append(("L3-12", "예", len(truth), len(detected), len(detected), 0, len(truth - detected)))
            rows.append((
                "L3-12-CAND",
                "별도",
                len(candidate_truth),
                len(candidate_detected),
                len(detected),
                len(candidate_detected - detected),
                len(candidate_truth - candidate_detected),
            ))
            continue

        truth = rule_sets[rule_id]["truth"]
        detected = rule_sets[rule_id]["detected"]
        scored = _score_docs(df, result, detected)
        review = detected - scored
        rows.append((rule_id, "예", len(truth), len(detected), len(scored), len(review), len(truth - detected)))
    return rows


def print_b_axis(rows) -> None:
    print("\nB_AXIS")
    print("rule\tresponsibility\tunit\thit\tscore\treview\tmiss")
    for row in rows:
        print("\t".join(map(str, row)))
    summary = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    for _rule, responsibility, unit, hit, score, review, miss in rows:
        agg = summary[responsibility]
        agg[0] += 1
        agg[1] += unit
        agg[2] += hit
        agg[3] += score
        agg[4] += review
        agg[5] += miss
    print("B_AXIS_SUMMARY")
    print("responsibility\tfiles\tunit\thit\tscore\treview\tmiss")
    for responsibility, values in summary.items():
        print(f"{responsibility}\t" + "\t".join(map(str, values)))


def c_axis(data_dir: Path, df: pd.DataFrame, results: dict[str, pd.Series], rule_sets: dict[str, dict[str, set]]):
    truth_path = data_dir / "labels" / "manipulated_entry_truth.csv"
    manipulated = pd.read_csv(truth_path, dtype=str, low_memory=False)
    manipulated_docs = set(manipulated["document_id"].dropna().astype(str).unique())

    caught: set[str] = set()
    direct: set[str] = set()
    review: set[str] = set()
    rule_rows: list[tuple[str, int, int, int]] = []

    for rule_id in L3_RULE_IDS:
        result = results[rule_id]
        if rule_id == "L3-12":
            candidate_mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
            rule_caught = (
                set(df.loc[candidate_mask, "document_id"].dropna().astype(str).unique())
                & manipulated_docs
            )
            rule_direct: set[str] = set()
            rule_review = _review_docs(df, result, manipulated_docs)
        else:
            detected = rule_sets[rule_id]["detected"]
            rule_caught = detected & manipulated_docs
            rule_direct = _score_docs(df, result, detected) & manipulated_docs
            rule_review = _review_docs(df, result, manipulated_docs)
        caught.update(rule_caught)
        direct.update(rule_direct)
        review.update(rule_review)
        rule_rows.append((rule_id, len(rule_caught), len(rule_direct), len(rule_review)))

    scenario_rows = []
    scenario_col = "scenario" if "scenario" in manipulated.columns else None
    if scenario_col is None and "fraud_scenario" in manipulated.columns:
        scenario_col = "fraud_scenario"
    if scenario_col:
        for scenario, group in manipulated.groupby(scenario_col):
            docs = set(group["document_id"].dropna().astype(str).unique())
            scenario_rows.append((
                scenario,
                len(docs),
                len(docs & caught),
                len(docs & direct),
                len(docs & review),
                len(docs - caught),
            ))

    return {
        "overall": (
            len(manipulated_docs),
            len(caught),
            len(direct),
            len(review),
            len(manipulated_docs - caught),
        ),
        "rules": rule_rows,
        "scenarios": scenario_rows,
    }


def print_c_axis(result) -> None:
    print("\nC_AXIS_OVERALL")
    print("total\tcaught\tdirect_score\treview\tmiss")
    print("\t".join(map(str, result["overall"])))
    print("C_AXIS_RULES")
    print("rule\tcaught\tdirect_score\treview")
    for row in result["rules"]:
        print("\t".join(map(str, row)))
    if result["scenarios"]:
        print("C_AXIS_SCENARIOS")
        print("scenario\ttotal\tcaught\tdirect_score\treview\tmiss")
        for row in result["scenarios"]:
            print("\t".join(map(str, row)))


def main() -> int:
    args = parse_args()
    timings: dict[str, float] = {}

    start = time.perf_counter()
    df = load_candidate(args.data_dir, args.years)
    timings["load"] = time.perf_counter() - start

    start = time.perf_counter()
    add_l3_features(df)
    timings["features"] = time.perf_counter() - start

    start = time.perf_counter()
    results = run_l3_only(df, set(L3_RULE_IDS))
    timings["rules"] = time.perf_counter() - start

    start = time.perf_counter()
    rule_sets = build_rule_sets(args.data_dir, df, results, args.years)
    totals = [
        metric(rule_id, None, sets["truth"], sets["detected"])
        for rule_id, sets in rule_sets.items()
    ]
    b_rows = b_axis(df, results, rule_sets)
    c_result = c_axis(args.data_dir, df, results, rule_sets)
    timings["abc_evaluation"] = time.perf_counter() - start

    print_a_axis(totals)
    print_b_axis(b_rows)
    print_c_axis(c_result)

    if args.timings:
        print("\nTIMINGS")
        for name, elapsed in timings.items():
            print(f"{name}: {elapsed:.2f}s")
        print(f"total: {sum(timings.values()):.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
