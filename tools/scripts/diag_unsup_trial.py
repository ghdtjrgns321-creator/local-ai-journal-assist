"""Unsupervised VAE 1 trial 만 직접 실행해 GPU/AMP 호환성 진단."""
# ruff: noqa: E402

from __future__ import annotations

import pickle
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import torch  # noqa: I001
from src.services.phase2_training_service import run_phase2_training

# Why: tail pipe 회피 — 실시간 출력
import functools

print = functools.partial(print, flush=True)  # noqa: A001

PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"


def main() -> None:
    print(f"torch: {torch.__version__}  cuda: {torch.cuda.is_available()}")

    sample_n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    print(f"loading fixture (sample={sample_n})...")
    with PKL_PATH.open("rb") as fh:
        data = pickle.load(fh)
    df_full = data["df"]
    if sample_n >= len(df_full):
        df = df_full.copy()
    else:
        df = df_full.sample(n=sample_n, random_state=42).reset_index(drop=True)
    print(f"  rows={len(df):,}")
    if torch.cuda.is_available():
        print(f"  GPU mem before: alloc={torch.cuda.memory_allocated() / 1e9:.2f}GB")

    report = run_phase2_training(
        df,
        save_report=False,
        model_families=("unsupervised",),
    )
    print(f"\ntrial count: {len(report.leaderboard)}")
    for trial in report.leaderboard:
        print(f"\n  family={trial.model_family} variant={trial.variant}")
        print(f"    status={trial.status.value}  elapsed={trial.elapsed_sec:.2f}s")
        print(f"    metric={trial.metric_name}={trial.metric_value}")
        if trial.warnings:
            print("    warnings:")
            for w in trial.warnings[:3]:
                print(f"      - {str(w)[:300]}")
        if trial.gate_reason:
            print(f"    gate_reason={trial.gate_reason}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
