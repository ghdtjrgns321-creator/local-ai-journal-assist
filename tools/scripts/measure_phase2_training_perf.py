"""Phase 2 training latency 측정 (회귀 가드 외 일회성).

V7 fixed3 pkl fixture 를 로드해 ``run_phase2_training`` 을 직접 호출하고,
training 총 elapsed + trial별 elapsed 분포를 출력한다. inference 는 별도.

Usage:
    uv run python tools/scripts/measure_phase2_training_perf.py
"""
# ruff: noqa: E402

from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import torch  # noqa: I001
from src.services.phase2_training_service import run_phase2_training

PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"


def main() -> None:
    print(f"torch: {torch.__version__}")
    print(f"cuda available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"device: {torch.cuda.get_device_name(0)}")
    print()

    print(f"loading fixture: {PKL_PATH.name}")
    with PKL_PATH.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    print(f"  rows={len(df):,} cols={len(df.columns)}")
    print()

    print("=== run_phase2_training ===")
    t0 = time.perf_counter()
    report = run_phase2_training(df, save_report=False)
    elapsed = time.perf_counter() - t0
    print(f"total elapsed: {elapsed:.1f}s")
    print(f"trial count:   {len(report.leaderboard)}")
    print()

    by_family: dict[str, list[float]] = {}
    by_status: dict[str, int] = {}
    for trial in report.leaderboard:
        by_family.setdefault(trial.model_family, []).append(float(trial.elapsed_sec or 0))
        by_status[trial.status.value] = by_status.get(trial.status.value, 0) + 1

    print("trial elapsed by family (count, sum, mean):")
    for family, elapsed_list in sorted(by_family.items()):
        n = len(elapsed_list)
        s = sum(elapsed_list)
        m = s / n if n else 0
        print(f"  {family:14s}  n={n:2d}  sum={s:6.1f}s  mean={m:5.2f}s")
    print()

    print("trial status counts:")
    for status, count in sorted(by_status.items()):
        print(f"  {status:12s} {count}")

    print()
    print("failed trial reasons (first 3 distinct):")
    seen: set[str] = set()
    for trial in report.leaderboard:
        if trial.status.value != "failed":
            continue
        reason = str(trial.gate_reason or "unknown")
        warn_text = " | ".join(str(w) for w in (trial.warnings or [])[:2])
        key = f"{reason}::{warn_text[:80]}"
        if key in seen:
            continue
        seen.add(key)
        print(f"  family={trial.model_family:14s} variant={trial.variant}")
        print(f"    reason={reason}")
        print(f"    warning={warn_text[:200]}")
        if len(seen) >= 3:
            break


if __name__ == "__main__":
    main()
