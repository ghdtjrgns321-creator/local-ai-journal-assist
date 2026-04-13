"""FT-Transformer Ablation Study — 7-model vs 8-model 성능 비교.

Why: phase2_ml_feasibility.md §1-3에서 FT-Transformer를 "유지하되 ablation"
     결론. Stacking에서 ML_TRANSFORMER 열을 제거한 7-model 앙상블과 기존
     8-model 앙상블의 OOF F1을 비교하여 FT-T 기여도를 정량화한다.

실행 전제:
- DataSynth 학습 데이터가 있고, EnsembleDetector.train_oof() 경로가 정상 동작
- sklearn, joblib, torch(ft_wrapper) 의존성 설치됨

사용:
    uv run python tools/scripts/ft_ablation_study.py --config <config.yaml>

출력:
    tests/datasynth_quality_gate/results/ft_ablation_report.md
    (기존 test-results 구조와 정합)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

REPORT_PATH = Path("tests/datasynth_quality_gate/results/ft_ablation_report.md")


def run_ablation(config_path: str, sample_rows: int | None = None) -> dict:
    """8-model vs 7-model OOF F1 비교를 수행.

    Returns:
        {
          "8_model_f1": float,
          "7_model_f1": float,
          "delta_f1": float,
          "delta_relative_pct": float,
          "conclusion": "keep" | "remove" | "inconclusive",
          "n_samples": int,
          "n_fraud": int,
        }

    Why: 본 스크립트는 **골격**이다. 실제 실행을 위해서는:
    1. `CompanyContext`로 파이프라인 초기화 (`ContextFactory.create(...)`)
    2. DataSynth 데이터 로드 → 피처 생성 → detection 실행
    3. label_result 구성 → `EnsembleDetector.train_oof()` 2회 실행
       (전체 base / FT-T 제외 base)
    4. 각 앙상블의 OOF F1-macro 계산
    5. 결과를 dict로 반환 + 본 스크립트에서 마크다운 리포트 생성

    실제 파이프라인 통합은 데이터 재생성 이후 단계로 분리 (플랜대로).
    """
    raise NotImplementedError(
        "run_ablation은 데이터 재생성 이후 단계에서 구현. "
        "현재는 CLI/리포트 골격만 완성되어 있음.",
    )


def write_report(result: dict, output_path: Path = REPORT_PATH) -> None:
    """결과 dict → 마크다운 리포트."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# FT-Transformer Ablation Study",
        "",
        f"- 8-model OOF F1-macro: **{result['8_model_f1']:.4f}**",
        f"- 7-model OOF F1-macro (FT-T 제거): **{result['7_model_f1']:.4f}**",
        f"- Δ F1 (절대): {result['delta_f1']:+.4f}",
        f"- Δ F1 (상대, %): {result['delta_relative_pct']:+.2f}%",
        f"- 샘플 수: {result['n_samples']:,}",
        f"- 양성 수: {result['n_fraud']:,}",
        "",
        "## 결론",
        "",
        _conclusion_text(result["conclusion"]),
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _conclusion_text(tag: str) -> str:
    mapping = {
        "keep": (
            "**유지 권장** — FT-Transformer가 8-model 앙상블에서 의미 있는 "
            "F1 기여를 보인다 (Δ ≥ +0.5%)."
        ),
        "remove": (
            "**제거 검토** — FT-Transformer 제거 시 F1 변화가 미미하거나 "
            "개선되었다. 53K 파라미터·VRAM 비용 대비 이득이 없어 Phase 3에서 "
            "제거를 검토한다."
        ),
        "inconclusive": (
            "**판정 보류** — F1 변화가 노이즈 범위 내 (|Δ| < 0.5%). "
            "추가 seed 반복 실험이 필요하다."
        ),
    }
    return mapping.get(tag, "(미분류)")


def classify_conclusion(
    f1_with: float, f1_without: float, threshold: float = 0.005,
) -> str:
    """Δ F1 기반 결론 분류."""
    delta = f1_with - f1_without
    if abs(delta) < threshold:
        return "inconclusive"
    if delta >= threshold:
        return "keep"
    return "remove"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="CompanyContext config 경로")
    parser.add_argument("--sample-rows", type=int, default=None, help="샘플 제한")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="실제 학습 없이 리포트 포맷만 검증",
    )
    args = parser.parse_args()

    if args.dry_run:
        fake = {
            "8_model_f1": 0.812,
            "7_model_f1": 0.808,
            "delta_f1": 0.004,
            "delta_relative_pct": 0.49,
            "conclusion": classify_conclusion(0.812, 0.808),
            "n_samples": 50_000,
            "n_fraud": 1_200,
        }
        write_report(fake)
        print(f"Dry-run 리포트 작성: {REPORT_PATH}")
        print(json.dumps(fake, indent=2, ensure_ascii=False))
        return

    result = run_ablation(args.config, sample_rows=args.sample_rows)
    write_report(result)
    print(f"리포트 작성: {REPORT_PATH}")


if __name__ == "__main__":
    main()
