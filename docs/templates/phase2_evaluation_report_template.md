# Phase 2 Evaluation Report

> 평가 대상:
> 평가 일자:
> 데이터셋:
> 모델/앙상블 버전:
> 비교 baseline: trivial baseline, Phase 1 baseline


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

## Executive Summary

- 결론:
- 운영 해석:
- 주요 제한사항:

## P1. Bootstrap Confidence Intervals

모든 recall/precision 지표는 `bootstrap_ci`를 함께 제시한다.

| Metric | Scenario | Point Estimate | Bootstrap CI | Marker |
|---|---|---:|---|---|
| recall |  |  |  |  |
| precision |  |  |  |  |

## P2. Unusual Timing Fold-Level Suppression

`unusual_timing` 시나리오는 fold-level 성능 통계를 결론 근거로 사용하지 않는다. 단, P5의 fold별 truth count 행렬은 표본 분포 확인 용도로만 제시한다.

| Scenario | Allowed Summary | Fold-Level Performance Included? | Note |
|---|---|---|---|
| unusual_timing | bootstrap CI / aggregate only | No |  |

## P3. Macro F2 Metrics

`macro_f2_unweighted`와 `macro_f2_prevalence_weighted`를 모두 제시한다.

| Metric | Value | Bootstrap CI | Note |
|---|---:|---|---|
| macro_f2_unweighted |  |  |  |
| macro_f2_prevalence_weighted |  |  |  |

## P4. Scenario Delta Recall vs Trivial

각 시나리오별 `delta_recall_vs_trivial`을 제시한다.

| Scenario | Ensemble Recall | Trivial Recall | Delta Recall vs Trivial | Bootstrap CI | Marker |
|---|---:|---:|---:|---|---|
| fictitious_entry |  |  |  |  |  |
| period_end_adjustment |  |  |  |  |  |
| embezzlement_concealment |  |  |  |  |  |
| circular_related_party |  |  |  |  |  |
| approval_sod_bypass |  |  |  |  |  |
| unusual_timing_manipulation |  |  |  |  |  |

## P5. Fold Scenario Truth Count Matrix

GroupKFold별 시나리오 truth count 행렬을 제시한다. 이 표는 표본 분포 진단용이며 P2 제한을 우회하는 성능 주장으로 사용하지 않는다.

| Fold | fictitious_entry | period_end_adjustment | embezzlement_concealment | circular_related_party | approval_sod_bypass | unusual_timing_manipulation |
|---:|---:|---:|---:|---:|---:|---:|
| 0 |  |  |  |  |  |  |
| 1 |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |

## Conclusion

`[insignificant]` 마커가 있는 경우 결론에서 통계적 유의 주장을 하지 않는다.
