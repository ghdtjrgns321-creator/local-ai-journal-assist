"""부정 overlay 평가 원장 병합 — 정상 정본 1벌 + overlay N벌의 부정 문서만.

배경: overlay 4벌은 동일한 정상 원장을 그대로 공유하고 각자 부정 문서만 덧붙인
구조다. 그대로 concat 하면 정상 문서가 N중복돼 중복탐지(L2-02/03)·희소성(L4-04)
룰이 붕괴한다. 따라서 정상은 1벌만 싣고 부정만 전 seed에서 모은다.

사용: uv run python tools/scripts/build_merged_fraud_eval.py <out_dir> [seed ...]
      seed 를 주면 그 overlay 만 싣는다 (예: r1 하나만 → 원본 재구성 대조군).

부속 데이터를 반드시 함께 실어야 한다. 파이프라인은 CSV 옆의
`master_data/employees.json` 으로 승인한도를 해소하는데
(src/feature/amount_features.py:106), 이게 없으면 한도가 전부 미해소가 되고
L1-04 는 "한도 미해소 + 승인자 있음"에 발화하므로
(src/detection/fraud_rules_feature.py:174) 승인자를 100% 보유한 부정 문서가
전부 발화해 커버리지가 100% 로 날조된다. 2026-07-26 실측으로 확인한 함정이다.

검증(assert)으로 전제를 강제한다:
  1) overlay의 비부정 행이 정상 정본과 완전히 동일한가 (append-only 구조)
  2) 부정 document_id 가 seed 간 서로소인가
전제가 깨지면 병합 결과가 무의미하므로 실패시킨다.

출력 디렉토리가 이미 있으면 거부한다 — data/ 는 git 추적 대상이 아니라
덮어쓰면 복구가 불가능하다.

한계: document_flows/·subledger/ 등 흐름 사이드카는 정본 것만 싣고 overlay 의
부정 흐름은 병합하지 않는다. 측정 경로(피처→탐지→빌더)가 이들을 읽지 않고
DB 적재는 skip_db 로 꺼져 있기 때문이며, 대조군 재구성으로 이를 확인한다.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PRIMARY = ROOT / "data/journal/primary"

BASELINE = PRIMARY / "datasynth_semantic_v1_normal_s10_c001_20260717"
OVERLAYS = [
    PRIMARY / "datasynth_semantic_v1_phase2_fraud_s10_20260718_r1",
    PRIMARY / "datasynth_semantic_v1_phase2_fraud_s10_20260718_r1_seed1",
    PRIMARY / "datasynth_semantic_v1_phase2_fraud_s10_20260718_r1_seed2",
    PRIMARY / "datasynth_semantic_v1_phase2_fraud_s10_20260718_r1_seed3",
]
# 정본에서 그대로 물려받는 부속 데이터에서 제외할 것 —
# 원장 본체는 병합본으로 대체하고, labels/ 는 병합 provenance 로 새로 쓴다.
CARRY_SKIP_PREFIXES = ("journal_entries",)
CARRY_SKIP_NAMES = {"labels"}

PROV_REL = Path("labels/phase2_scheme_provenance.csv")


def seed_tag(overlay: Path) -> str:
    """overlay 디렉토리명 꼬리에서 seed 식별자를 뽑는다 (r1 / seed1 ...)."""
    name = overlay.name
    return name.rsplit("_", 1)[-1] if name.rsplit("_", 1)[-1].startswith("seed") else "r1"


def carry_sidecars(out_dir: Path) -> list[str]:
    """정본의 부속 데이터를 병합 디렉토리로 복사한다 (원장 본체·labels 제외)."""
    carried: list[str] = []
    for src in sorted(BASELINE.iterdir()):
        if src.name.startswith(CARRY_SKIP_PREFIXES) or src.name in CARRY_SKIP_NAMES:
            continue
        dst = out_dir / src.name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        carried.append(src.name)
    return carried


def build(out_dir: Path, overlays: list[Path]) -> int:
    if out_dir.exists():
        print(f"ERROR: 출력 디렉토리가 이미 존재한다 — 덮어쓰지 않는다: {out_dir}")
        return 1

    base = pd.read_csv(BASELINE / "journal_entries.csv", dtype=str)
    print(f"정상 정본: {len(base):,}행 / {base['document_id'].nunique():,}문서")

    fraud_frames: list[pd.DataFrame] = []
    prov_frames: list[pd.DataFrame] = []
    seen_fraud_docs: set[str] = set()

    for overlay in overlays:
        tag = seed_tag(overlay)
        prov = pd.read_csv(overlay / PROV_REL, dtype=str)
        fraud_docs = set(prov["document_id"])

        entries = pd.read_csv(overlay / "journal_entries.csv", dtype=str)
        assert list(entries.columns) == list(base.columns), f"{tag}: 컬럼 구성 불일치"

        is_fraud = entries["document_id"].isin(sorted(fraud_docs))
        normal_part = entries.loc[~is_fraud]

        # 전제 1 — overlay 의 정상 부분이 정본과 동일해야 병합이 성립한다.
        key = ["document_id", "line_number"] if "line_number" in base.columns else ["document_id"]
        left = base.sort_values(by=key).reset_index(drop=True)
        right = normal_part.sort_values(by=key).reset_index(drop=True)
        assert left.equals(right), f"{tag}: 정상 부분이 정본과 다르다 — append-only 전제 위반"

        # 전제 2 — 부정 문서 ID 가 seed 간 서로소여야 한다.
        collide = seen_fraud_docs & fraud_docs
        assert not collide, f"{tag}: 부정 document_id 충돌 {len(collide)}건"
        seen_fraud_docs |= fraud_docs

        # scheme_instance_id 는 seed 간 같은 값이 재사용되므로 seed 를 붙여 분리한다.
        prov = prov.assign(
            scheme_instance_id=prov["scheme_instance_id"] + f"@{tag}",
            source_dataset=overlay.name,
        )

        fraud_frames.append(entries.loc[is_fraud])
        prov_frames.append(prov)
        print(f"{overlay.name}: 부정 {len(fraud_docs)}문서 / {int(is_fraud.sum())}행")

    merged = pd.concat([base, *fraud_frames], ignore_index=True)
    merged_prov = pd.concat(prov_frames, ignore_index=True)

    assert merged["document_id"].nunique() == base["document_id"].nunique() + len(seen_fraud_docs)

    out_dir.mkdir(parents=True)
    (out_dir / "labels").mkdir()
    merged.to_csv(out_dir / "journal_entries.csv", index=False, encoding="utf-8")
    merged_prov.to_csv(out_dir / PROV_REL, index=False, encoding="utf-8")
    carried = carry_sidecars(out_dir)
    print(f"부속 데이터 {len(carried)}개 반입 (master_data 포함: {'master_data' in carried})")
    assert (out_dir / "master_data/employees.json").exists(), (
        "master_data/employees.json 부재 — 승인한도가 미해소되어 L1-04 가 날조 발화한다"
    )

    density = len(seen_fraud_docs) / merged["document_id"].nunique()
    print(
        f"\n병합 완료: {len(merged):,}행 / {merged['document_id'].nunique():,}문서"
        f" / 부정 {len(seen_fraud_docs):,}문서 (밀도 {density:.4%})"
    )
    print(f"-> {out_dir}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: build_merged_fraud_eval.py <out_dir> [seed ...]")
        return 2
    wanted = set(sys.argv[2:])
    overlays = [o for o in OVERLAYS if not wanted or seed_tag(o) in wanted]
    if not overlays:
        print(f"ERROR: 지정한 seed 에 해당하는 overlay 가 없다: {sorted(wanted)}")
        return 2
    print(f"싣는 overlay: {[seed_tag(o) for o in overlays]}")
    return build(Path(sys.argv[1]), overlays)


if __name__ == "__main__":
    raise SystemExit(main())
