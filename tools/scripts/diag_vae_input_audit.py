"""VAE 입력 전수 감사 — 원본 컬럼 하나하나가 어떻게 처리되는지 표로 낸다.

사용: uv run python tools/scripts/diag_vae_input_audit.py <dataset_dir> [--sample N]

배경(2026-07-28): PHASE1 출력 6칸이 VAE 입력에 섞여 있던 것을 발견한 뒤,
"입력 목록을 한 번도 눈으로 세지 않았다"가 근본 원인으로 정리됐다. 그래서 세는
도구를 만든다. 전처리 전면 재작업의 근거 자료이기도 하다.

내는 것:
  1) 원본 컬럼별 — dtype·고유값·결측률·배정 그룹·제외 사유
  2) 변환 후 컬럼별 — 실제 min/max/std (그룹 간 스케일 왜곡 확인용)
  3) 자동 지적 — 아래 규칙에 걸리는 것

**경로는 하나다.** 2026-07-28 이전에는 둘이었고 그게 사고 101이었다 — 제품은
`Phase2AutoencoderMatrixBuilder`(금액 signed-log · 수치형 robust/standard 자동선택 ·
저카디널리티 원-핫 · 고카디널리티 빈도+건수)를 태우는데, 측정 스크립트는
`det.train(cleaned, groups)` 를 직접 불러 OrdinalEncoder 무스케일 + 고카디널리티 버림
경로를 탔다. 그 경로(`_build_unsupervised_preprocessor`)는 삭제했다. 이 도구도 남은
하나만 잰다 — 없는 경로를 계속 재면 그 자체가 다음 혼선의 씨앗이다.

지적 규칙 (판단이 아니라 계측 결과):
  P1 스케일 왜곡  변환 후 std 가 수치형 기준(1.0)에서 크게 벗어난 칸.
                  VAE 는 재구성 제곱오차로 점수를 내므로 범위가 큰 칸이 손실을 지배한다.
  P3 정보 유실    매트릭스에 들어가지 못한 칸.
  P4 죽은 입력    전 행 동일값. 재구성 오차 기여가 0.
  P5 손실 점유    한 그룹이 전체 분산의 큰 몫을 차지. 재구성 손실 점유율의 대리 지표다
                  — 그룹 분산합 / 전체 분산합. 칸 수 자체로 지배하는 경우를 잡는다.

(P2 "가짜 순서" 는 폐기했다 — OrdinalEncoder 를 쓰던 경로가 없어져 해당 없음.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports/s5_fraud_overlay"


def _group_of(groups, column: str) -> str:
    for name in (
        "numeric",
        "categorical_high",
        "categorical_low",
        "boolean",
        "ordinal",
        "excluded",
    ):
        if column in getattr(groups, name, []):
            return name
    return "미배정"


def _transform_chain(group: str) -> str:
    return {
        "numeric": "중앙값대치 → Yeo-Johnson → 표준화",
        "categorical_low": "최빈값대치 → OrdinalEncoder",
        "categorical_high": "— (버림)",
        "boolean": "float변환 → 최빈값대치",
        "ordinal": "OrdinalEncoder",
        "excluded": "— (제외)",
    }.get(group, "—")


def _scale_frame(matrix: np.ndarray, names: list[str], group_of: dict[str, str]) -> pd.DataFrame:
    """변환 후 행렬 → 칸별 min/max/std + 소속 그룹."""
    scale = pd.DataFrame(
        {
            "feature": names,
            "min": matrix.min(axis=0).round(3),
            "max": matrix.max(axis=0).round(3),
            "std": matrix.std(axis=0).round(3),
        }
    )
    scale["group"] = [group_of.get(name, "미상") for name in names]
    return scale


def _group_summary(scale: pd.DataFrame) -> pd.DataFrame:
    """그룹별 칸수·std중앙·분산합·분산 점유율.

    분산 점유율이 판단 근거다 — VAE 재구성 손실은 칸별 제곱오차의 합이므로,
    한 그룹의 분산합이 전체에서 차지하는 몫이 그 그룹의 손실 지배력에 대응한다.
    칸 하나의 std 가 1이어도 칸이 40개면 그 그룹이 40을 먹는다.
    """
    frame = scale.copy()
    frame["var"] = frame["std"].astype(float) ** 2
    summary = frame.groupby("group").agg(
        칸수=("feature", "size"),
        std중앙=("std", "median"),
        std최대=("std", "max"),
        분산합=("var", "sum"),
    )
    total = float(summary["분산합"].sum())
    summary["분산점유율%"] = (summary["분산합"] / total * 100) if total else 0.0
    return summary.round(3).sort_values("분산점유율%", ascending=False)


def _model_input_matrix(plan: dict, sample: pd.DataFrame, rare_min_count: int):
    """모델이 실제로 보는 행렬 — 매트릭스 빌더 + 파이프라인 전처리기 두 단계.

    빌더 산출물이 그대로 모델에 가는 게 아니라 전 칸이 numeric 으로 재분류돼
    파이프라인 전처리기를 한 번 더 거친다. 실제 값을 재려면 둘 다 통과시켜야 한다.
    (2026-07-28 이후 그 두 번째 단계는 결측 대치만 한다 — 재스케일 없음.)
    """
    from src.preprocessing.feature_groups import FeatureGroups
    from src.preprocessing.phase2_matrix import Phase2AutoencoderMatrixBuilder
    from src.preprocessing.pipeline_builder import build_vae_pipeline

    builder = Phase2AutoencoderMatrixBuilder(plan, rare_min_count=rare_min_count).fit(sample)
    built = builder.transform(sample)
    pre = build_vae_pipeline(FeatureGroups(numeric=list(built.columns)))[:-1]
    matrix = np.asarray(pre.fit_transform(built), dtype=float)
    names = list(built.columns)
    group_of = dict(builder.output_feature_groups_)
    return matrix, names, group_of, builder


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir")
    parser.add_argument("--sample", type=int, default=50_000)
    args = parser.parse_args()

    from config.settings import get_settings
    from src.pipeline import AuditPipeline
    from src.services.phase2_training_service import prepare_phase2_feature_inputs

    dataset_dir = Path(args.dataset_dir)
    settings = get_settings()

    res = AuditPipeline(skip_db=True).run(str(dataset_dir / "journal_entries.csv"))
    featured = res.featured_data if res.featured_data is not None else res.data
    cleaned, groups, payload = prepare_phase2_feature_inputs(featured, settings=settings)

    decisions = {d["column"]: d for d in payload["preprocessing_plan"]["decisions"]}

    # --- 1) 원본 컬럼별 ---
    rows = []
    for column in featured.columns:
        series = featured[column]
        group = _group_of(groups, column) if column in cleaned.columns else "차단/제거"
        decision = decisions.get(column, {})
        rows.append(
            {
                "column": column,
                "dtype": str(series.dtype),
                "unique": int(series.nunique(dropna=True)),
                "missing_pct": round(float(series.isna().mean()) * 100, 2),
                "group": group,
                "action": decision.get("action", "—"),
                "reason_code": decision.get("reason_code", "—"),
                "transform": _transform_chain(group),
            }
        )
    table = pd.DataFrame(rows)

    # --- 2) 변환 후 스케일 ---
    sample = cleaned.sample(n=min(args.sample, len(cleaned)), random_state=20260728)

    matrix, names, group_of, builder = _model_input_matrix(
        payload["preprocessing_plan"],
        sample,
        int(getattr(settings, "phase2_low_card_rare_min_count", 2)),
    )
    scale = _scale_frame(matrix, names, group_of)

    print(f"=== 데이터셋 {dataset_dir.name} ===")
    print(
        f"원본 {featured.shape[1]}칸 → 차단·제거 후 {cleaned.shape[1]}칸"
        f" → 모델 입력 {matrix.shape[1]}칸\n"
    )

    print("=== 그룹별 컬럼 수 (원본 기준) ===")
    print(table["group"].value_counts().to_string(), "\n")

    print("=== 모델 입력 행렬 — 그룹별 스케일·분산 점유 ===")
    print(_group_summary(scale).to_string(), "\n")

    # --- 3) 자동 지적 ---
    findings: list[dict] = []

    for group, row in _group_summary(scale).iterrows():
        if float(row["분산점유율%"]) >= 40.0:
            findings.append(
                {
                    "code": "P5",
                    "feature": str(group),
                    "detail": (
                        f"분산 점유율 {row['분산점유율%']:.1f}% "
                        f"({int(row['칸수'])}칸 · std중앙 {row['std중앙']})"
                    ),
                }
            )

    numeric_std = scale.loc[scale["group"] == "numeric", "std"].median()
    baseline = float(numeric_std) if pd.notna(numeric_std) else 1.0
    for _, r in scale.iterrows():
        if r["group"] == "numeric":
            continue
        ratio = float(r["std"]) / baseline if baseline else float("inf")
        if ratio >= 2.0:
            findings.append(
                {
                    "code": "P1",
                    "feature": r["feature"],
                    "detail": (
                        f"변환 후 std {r['std']} — 수치형 기준 {baseline:.3f} 의 {ratio:.1f}배"
                    ),
                }
            )

    # P3 — 매트릭스에 들어가지 못한 칸. 빌더가 인코딩한 것은 지적 대상이 아니다.
    encoded = set(builder.high_card_columns) | set(builder.low_card_columns)
    for column in list(groups.categorical_high) + list(groups.categorical_low):
        if column in encoded:
            continue
        findings.append(
            {
                "code": "P3",
                "feature": column,
                "detail": f"고유값 {featured[column].nunique()}종 — 매트릭스에 미포함",
            }
        )

    for column in cleaned.columns:
        values = pd.to_numeric(cleaned[column], errors="coerce")
        if values.notna().any() and float(np.nanstd(values.to_numpy(dtype="float64"))) == 0:
            findings.append({"code": "P4", "feature": column, "detail": "전 행 동일값"})

    print(f"=== 자동 지적 {len(findings)}건 ===")
    for code in ("P5", "P1", "P3", "P4"):
        hits = [f for f in findings if f["code"] == code]
        if not hits:
            continue
        print(f"\n[{code}] {len(hits)}건")
        for f in hits:
            print(f"  {f['feature']:<40} {f['detail']}")

    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"vae_input_audit_{dataset_dir.name}"
    table.to_csv(OUT / f"{stem}_columns.csv", index=False, encoding="utf-8-sig")
    scale.to_csv(OUT / f"{stem}_scale.csv", index=False, encoding="utf-8-sig")
    (OUT / f"{stem}.json").write_text(
        json.dumps(
            {
                "dataset": dataset_dir.name,
                "columns_raw": int(featured.shape[1]),
                "columns_cleaned": int(cleaned.shape[1]),
                "matrix_dim": int(matrix.shape[1]),
                "group_counts": table["group"].value_counts().to_dict(),
                "group_summary": _group_summary(scale).to_dict(orient="index"),
                "findings": findings,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n산출: {OUT / stem}_columns.csv · _scale.csv · .json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
