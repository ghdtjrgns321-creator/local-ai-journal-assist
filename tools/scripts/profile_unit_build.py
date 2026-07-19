"""build_phase1_case_result (단위/흐름 빌드) perf 프로파일러.

전수(984k) 빌드가 16GB RAM에서 스왑 스톨하므로, 부분셋으로 (1) 행수 스케일링 측정해
super-linear(O(n^2)) 구간을 입증하고 (2) cProfile로 핫스팟 함수를 특정한다.
detector 결과는 한 번 계산 후 build 만 반복 측정한다(빌드 단계 격리).
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
import time
import tracemalloc
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.scripts.measure_phase1_detector_catch as mc  # noqa: E402
import tools.scripts.profile_phase1_v126 as prof  # noqa: E402
from config.settings import get_audit_rules, get_risk_keywords, get_settings  # noqa: E402
from src.detection.phase1_case_builder import build_phase1_case_result  # noqa: E402
from src.ingest.datasynth_labels import apply_datasynth_label_mode, set_source_path  # noqa: E402
from src.services.analysis_service import make_phase_settings  # noqa: E402


def _prep(data_dir: Path, limit_rows: int):
    """limit_rows 행으로 features+detectors 까지 1회 — build 입력 준비."""
    settings = make_phase_settings(get_settings(), phase="phase1")
    rules = get_audit_rules()
    keywords = get_risk_keywords()
    source = data_dir / "journal_entries.csv"
    df = pd.read_csv(source, nrows=limit_rows, low_memory=False)
    for c in prof.DATE_COLUMNS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    df = set_source_path(df, source)
    df = apply_datasynth_label_mode(
        df, source_path=source, mode=getattr(settings, "datasynth_label_mode", "hidden")
    )
    ck = data_dir / "reports" / "_profile_unit_build" / "ck.json"
    ck.parent.mkdir(parents=True, exist_ok=True)
    summary: dict = {"stages": {}}
    df = prof._run_features(
        df,
        settings=settings,
        audit_rules=rules,
        risk_keywords=keywords,
        checkpoint=ck,
        summary=summary,
    )
    results = prof._run_detectors(
        df, settings=settings, audit_rules=rules, checkpoint=ck, summary=summary
    )
    results = results + mc._run_extra_detectors(
        df, settings=settings, audit_rules=rules, checkpoint=ck, summary=summary
    )
    return df, results


def _build(df, results):
    return build_phase1_case_result(
        df,
        results,
        company_id="_anonymous",
        batch_id="profile",
        dataset_id="profile_unit_build",
        phase1_case_config=dict(phase1_case=dict()),
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", type=Path)
    ap.add_argument("--rows", type=str, default="10000,50000,100000", help="콤마구분 행수")
    ap.add_argument("--profile-at", type=int, default=50000, help="cProfile 돌릴 행수")
    args = ap.parse_args(argv)

    row_list = [int(x) for x in args.rows.split(",") if x.strip()]
    print("[scaling] rows -> build_sec (unit/case count)")
    prev = None
    for n in row_list:
        df, results = _prep(args.data_dir, n)
        tracemalloc.start()
        t0 = time.perf_counter()
        res = _build(df, results)
        elapsed = time.perf_counter() - t0
        _cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        units = len(getattr(res, "units", []) or [])
        cases = len(getattr(res, "cases", []) or [])
        ratio = ""
        if prev:
            pn, pe = prev
            growth = (elapsed / pe) / (n / pn) if pe > 0 and pn > 0 else 0
            ratio = f"  per-row배율 x{growth:.2f} (선형=1.0, >1=super-linear)"
        print(
            f"  rows={n:>7} build={elapsed:7.2f}s peakMem={peak / 1e6:7.1f}MB units={units} cases={cases}{ratio}"
        )
        prev = (n, elapsed)

    print(f"\n[cProfile] rows={args.profile_at} — build 내부 핫스팟 top 20 (cumtime)")
    df, results = _prep(args.data_dir, args.profile_at)
    pr = cProfile.Profile()
    pr.enable()
    _build(df, results)
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(25)
    # src/detection 내부 프레임만 추려 출력
    for line in s.getvalue().splitlines():
        if (
            "phase1_case_builder" in line
            or "intercompany" in line
            or "flow" in line
            or "detection" in line
            or "ncalls" in line.lower()
        ):
            print("  " + line.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
