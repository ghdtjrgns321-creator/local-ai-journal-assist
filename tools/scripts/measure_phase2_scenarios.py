"""Phase 2 training: baseline / epochs_half / preset_balanced_only 시나리오 비교.

3개 시나리오 순차 실행하고 시간 + 품질 metric 비교 표 출력.

Usage:
    uv run python tools/scripts/measure_phase2_scenarios.py [sample_n]

sample_n: 측정용 sample 행 수 (기본 100000). phase2_train_max_rows=50000 cap
적용되므로 실제 학습 시간은 sample 크기 무관 (EDA/aggregate 만 영향).
"""
# ruff: noqa: E402

from __future__ import annotations

import copy
import pickle
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import torch  # noqa: I001
import src.services.phase2_training_service as ts
from src.services.phase2_training_service import run_phase2_training

PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"


# 원본 preset 백업
_ORIG_PRESETS = copy.deepcopy(ts._DEFAULT_SEARCH_PRESETS)


def restore_presets() -> None:
    ts._DEFAULT_SEARCH_PRESETS = copy.deepcopy(_ORIG_PRESETS)


def apply_scenario(scenario: str) -> None:
    """시나리오별 _DEFAULT_SEARCH_PRESETS monkey patch."""
    restore_presets()
    if scenario == "baseline":
        return
    if scenario == "epochs_half":
        # compact(20→10) / balanced(40→20) / strict_capacity(50→30)
        epoch_map = {"compact": 10, "balanced": 20, "strict_capacity": 30}
        new_presets = []
        for preset in _ORIG_PRESETS["unsupervised"]:
            np_preset = copy.deepcopy(preset)
            if preset["name"] in epoch_map:
                np_preset["settings_updates"]["vae_epochs"] = epoch_map[preset["name"]]
            new_presets.append(np_preset)
        ts._DEFAULT_SEARCH_PRESETS["unsupervised"] = tuple(new_presets)
    elif scenario == "preset_balanced_only":
        balanced_only = tuple(p for p in _ORIG_PRESETS["unsupervised"] if p["name"] == "balanced")
        ts._DEFAULT_SEARCH_PRESETS["unsupervised"] = balanced_only
    else:
        raise ValueError(f"unknown scenario: {scenario}")


def summarize_report(report) -> dict:
    """trial elapsed + best metric per family + promoted 정리."""
    by_family_metric: dict[str, float] = {}
    by_family_elapsed: dict[str, float] = {}
    by_family_count: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for trial in report.leaderboard:
        family = trial.model_family
        elapsed = float(trial.elapsed_sec or 0.0)
        metric = float(trial.metric_value or 0.0)
        by_family_elapsed[family] = by_family_elapsed.get(family, 0.0) + elapsed
        by_family_count[family] = by_family_count.get(family, 0) + 1
        if trial.status.value == "completed":
            by_family_metric[family] = max(by_family_metric.get(family, -1.0), metric)
        by_status[trial.status.value] = by_status.get(trial.status.value, 0) + 1
    promoted = [(m.model_name, float(m.metric_value)) for m in report.promoted_models]
    return {
        "by_family_elapsed": by_family_elapsed,
        "by_family_count": by_family_count,
        "by_family_best_metric": by_family_metric,
        "by_status": by_status,
        "promoted_models": promoted,
    }


def run_scenario(scenario: str, df) -> dict:
    print(f"\n========== scenario: {scenario} ==========")
    apply_scenario(scenario)
    t0 = time.perf_counter()
    try:
        report = run_phase2_training(df, save_report=False)
    except Exception:
        traceback.print_exc()
        return {"scenario": scenario, "error": True}
    elapsed = time.perf_counter() - t0
    summary = summarize_report(report)
    summary.update(
        {
            "scenario": scenario,
            "total_elapsed": elapsed,
            "trial_count": len(report.leaderboard),
        },
    )
    print(f"total_elapsed: {elapsed:.1f}s | trial_count: {summary['trial_count']}")
    print(f"status: {summary['by_status']}")
    print(f"family elapsed: {summary['by_family_elapsed']}")
    print(f"family best metric: {summary['by_family_best_metric']}")
    print(f"promoted: {summary['promoted_models']}")
    return summary


def print_comparison_table(summaries: list[dict]) -> None:
    print("\n" + "=" * 80)
    print("SCENARIO COMPARISON")
    print("=" * 80)
    headers = ["scenario", "total", "trials", "unsup_metric", "unsup_elapsed"]
    print(
        f"{'scenario':28s} {'total':>10s} {'trials':>7s} {'unsup_metric':>14s} {'unsup_elapsed':>14s}"
    )
    print("-" * 80)
    for s in summaries:
        if s.get("error"):
            print(f"{s['scenario']:28s} ERROR")
            continue
        unsup_metric = s["by_family_best_metric"].get("unsupervised", 0.0)
        unsup_elapsed = s["by_family_elapsed"].get("unsupervised", 0.0)
        print(
            f"{s['scenario']:28s} "
            f"{s['total_elapsed']:>9.1f}s "
            f"{s['trial_count']:>7d} "
            f"{unsup_metric:>14.4f} "
            f"{unsup_elapsed:>13.1f}s",
        )
    print("=" * 80)
    if len(summaries) >= 2 and not summaries[0].get("error"):
        baseline_total = summaries[0]["total_elapsed"]
        baseline_metric = summaries[0]["by_family_best_metric"].get("unsupervised", 0.0)
        print("\nbaseline 대비 비교:")
        for s in summaries[1:]:
            if s.get("error"):
                continue
            delta_t = s["total_elapsed"] - baseline_total
            pct_t = (delta_t / baseline_total * 100) if baseline_total else 0
            m = s["by_family_best_metric"].get("unsupervised", 0.0)
            delta_m = m - baseline_metric
            print(
                f"  {s['scenario']:28s} "
                f"time {delta_t:+.1f}s ({pct_t:+.1f}%) | "
                f"unsup_metric {delta_m:+.4f}"
            )


def main() -> None:
    print(f"torch: {torch.__version__}  cuda: {torch.cuda.is_available()}")
    sample_n = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
    print(f"loading fixture (sample={sample_n})...")
    with PKL_PATH.open("rb") as fh:
        data = pickle.load(fh)
    df_full = data["df"]
    if sample_n >= len(df_full):
        df = df_full.copy()
    else:
        df = df_full.sample(n=sample_n, random_state=42).reset_index(drop=True)
    print(f"  rows={len(df):,}")

    scenarios = ["baseline", "epochs_half", "preset_balanced_only"]
    summaries: list[dict] = []
    for scenario in scenarios:
        s = run_scenario(scenario, df)
        summaries.append(s)
    restore_presets()
    print_comparison_table(summaries)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
