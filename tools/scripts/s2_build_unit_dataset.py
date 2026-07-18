"""S2 룰 단위시험 데이터 빌더 — 정상 배경(FY2024) + 룰별 표적 주입 + 정답지.

설계: docs/0716/PLAN.md §3 S2 (2026-07-17 승인). 정본 base는 무변경 —
시험용 사본에만 주입한다. 주입 레시피는 s2_unit_recipes.py(룰별 함수, 코드 근거 주석).

출력 구조:
  <out>/journal_entries.csv        배경 + 주입 행
  <out>/chart_of_accounts.json     base 복사 (피처 엔진 CoA 권위)
  <out>/master_data/               base 복사 (승인자/사용자 마스터)
  <out>/labels/s2_expected.csv     정답지 (rule_id, document_id) — 본체 무흔적
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASE = ROOT / "data/journal/primary/datasynth_semantic_v1_normal_s10_c001_20260717"
DEFAULT_OUT = ROOT / "data/journal/unit/s2_unit_firing_20260717"

# 배경에서 복사할 사이드카 (원장 본체 제외 — 본체는 슬라이스+주입으로 새로 쓴다)
SIDECAR_ITEMS = ["chart_of_accounts.json", "master_data", "tax", "internal_controls"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=20260717)
    args = ap.parse_args()

    from tools.scripts.s2_unit_recipes import RECIPES, RecipeContext

    background = pd.read_csv(args.base / "journal_entries_2024.csv", dtype=str, low_memory=False)
    print(f"background FY2024: {len(background):,} rows")

    ctx = RecipeContext(base_dir=args.base, background=background, seed=args.seed)

    injected_frames: list[pd.DataFrame] = []
    expected: list[dict[str, str]] = []
    for rule_id, recipe in RECIPES.items():
        rows, doc_ids = recipe(ctx)
        if not doc_ids:
            raise SystemExit(f"{rule_id}: 레시피가 정답 문서를 내지 않음")
        injected_frames.append(rows)
        expected.extend({"rule_id": rule_id, "document_id": d} for d in doc_ids)
        print(f"  {rule_id}: +{len(rows)}행 / 정답 문서 {len(doc_ids)}")

    combined = pd.concat([background, *injected_frames], ignore_index=True)

    args.out.mkdir(parents=True, exist_ok=True)
    combined.to_csv(args.out / "journal_entries.csv", index=False)
    (args.out / "labels").mkdir(exist_ok=True)
    pd.DataFrame(expected).to_csv(args.out / "labels" / "s2_expected.csv", index=False)

    for item in SIDECAR_ITEMS:
        src = args.base / item
        dst = args.out / item
        if not src.exists() or dst.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    n_inject = sum(len(f) for f in injected_frames)
    print(
        f"built: {args.out} — 배경 {len(background):,} + 주입 {n_inject}행, "
        f"룰 {len(RECIPES)}종 / 정답 {len(expected)}건"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
