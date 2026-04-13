"""Semi-supervised 평가 뷰 생성 - DataSynth 원본 라벨은 보존.

Why (CLAUDE.md 원칙 준수):
    DataSynth는 **완전한 ground truth**를 생성한다. "숨겨진 fraud" 시뮬레이션은
    생성 단계가 아닌 **평가 단계**에서만 수행해야 한다. 이 스크립트는 원본 CSV를
    변경하지 않고, 파생 뷰를 만들어 일부 fraud 라벨을 마스킹한다.
    내부 ground truth (`hidden_fraud_id`)는 별도 파일에 보존하여
    Phase 2 비지도 탐지기의 실전 recall 측정에 사용한다.

출력:
    - `data/journal/primary/datasynth/journal_entries_masked.csv` - 마스킹된 뷰
    - `tests/phase2_data_analysis/results/hidden_fraud_manifest.json` - ground truth

실행:
    uv run python -m tests.phase2_data_analysis.mask_labels [--mask-ratio 0.7]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "data" / "journal" / "primary" / "datasynth"
)
_SRC_CSV = _DATA_DIR / "journal_entries.csv"
_DST_CSV = _DATA_DIR / "journal_entries_masked.csv"
_MANIFEST = Path(__file__).parent / "results" / "hidden_fraud_manifest.json"


def create_masked_view(mask_ratio: float, seed: int) -> None:
    """원본 CSV → 마스킹된 뷰 CSV + manifest.

    Args:
        mask_ratio: fraud 전표 중 라벨을 숨길 비율 (0.0 ~ 1.0).
        seed: 결정론적 샘플링용 seed (사용자별 hash로 고정).

    Why:
        mask_ratio=0.7 → fraud의 70%는 "감사에서 아직 발견 안 됨"으로 처리.
        나머지 30%는 "이미 발견된 fraud" (감사인 지식 보유 상태).
        이는 실전 Phase 2 Stacking 학습의 semi-supervised 시나리오와 정확히 같음.
    """
    print(f"[1/4] Loading {_SRC_CSV}")
    con = duckdb.connect()
    con.execute(f"""
        CREATE TABLE je AS
        SELECT * FROM read_csv_auto('{_SRC_CSV.as_posix()}', all_varchar=true)
    """)
    total = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    print(f"  -> {total:,} rows loaded")

    # 2. Fraud 전표 샘플링 (결정론적 hash 기반)
    print(f"[2/4] Sampling hidden_fraud documents (mask_ratio={mask_ratio})")
    hash_threshold = int(mask_ratio * 10_000)
    con.execute(f"""
        CREATE TABLE hidden_fraud AS
        SELECT DISTINCT document_id, fraud_type
        FROM je
        WHERE is_fraud='true'
          AND hash(document_id || CAST({seed} AS VARCHAR)) % 10000 < {hash_threshold}
    """)
    hidden_count = con.execute("SELECT COUNT(*) FROM hidden_fraud").fetchone()[0]
    total_fraud = con.execute(
        "SELECT COUNT(DISTINCT document_id) FROM je WHERE is_fraud='true'"
    ).fetchone()[0]
    print(f"  -> hidden {hidden_count:,} / total fraud {total_fraud:,}")

    # 3. 마스킹된 뷰 작성
    # Why: is_fraud/fraud_type만 마스킹. 나머지 컬럼은 원본 그대로.
    #      is_anomaly와 anomaly_type은 "감사인이 발견한 이상" 계열이라 유지.
    print(f"[3/4] Writing masked view → {_DST_CSV}")
    con.execute(f"""
        COPY (
            SELECT
                je.* EXCLUDE (is_fraud, fraud_type),
                CASE WHEN hf.document_id IS NOT NULL THEN 'false'
                     ELSE je.is_fraud END AS is_fraud,
                CASE WHEN hf.document_id IS NOT NULL THEN ''
                     ELSE je.fraud_type END AS fraud_type
            FROM je
            LEFT JOIN hidden_fraud hf ON je.document_id = hf.document_id
        ) TO '{_DST_CSV.as_posix()}'
        WITH (HEADER, DELIMITER ',')
    """)

    # 4. Ground truth manifest 저장
    print(f"[4/4] Writing ground truth → {_MANIFEST}")
    hidden_list = con.execute("""
        SELECT document_id, fraud_type FROM hidden_fraud ORDER BY document_id
    """).fetchall()
    manifest = {
        "source_csv": str(_SRC_CSV),
        "masked_csv": str(_DST_CSV),
        "mask_ratio": mask_ratio,
        "seed": seed,
        "total_rows": total,
        "total_fraud_docs": total_fraud,
        "hidden_fraud_docs": hidden_count,
        "visible_fraud_docs": total_fraud - hidden_count,
        "hidden_fraud_ids": [
            {"document_id": r[0], "fraud_type": r[1]} for r in hidden_list
        ],
    }
    _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    con.close()

    print()
    print("=" * 60)
    print("Semi-supervised view created")
    print("=" * 60)
    print(f"  visible fraud: {total_fraud - hidden_count:,} (30%) - Phase 2 학습용")
    print(f"  hidden fraud:  {hidden_count:,} (70%) - 실전 recall 측정용")
    print(f"  Manifest: {_MANIFEST}")
    print(f"  Masked CSV: {_DST_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mask-ratio",
        type=float,
        default=0.7,
        help="fraud 전표 중 라벨 마스킹 비율 (default 0.7)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="결정론적 hash seed (default 42)",
    )
    args = parser.parse_args()
    if not 0.0 < args.mask_ratio < 1.0:
        raise ValueError("mask_ratio must be between 0 and 1")
    create_masked_view(args.mask_ratio, args.seed)


if __name__ == "__main__":
    main()
