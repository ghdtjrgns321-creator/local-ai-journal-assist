# Phase 2 Evaluation Report

> 평가 대상:
> 평가 일자:
> 데이터셋:
> 모델/앙상블 버전:
> 비교 baseline: trivial baseline, Phase 1 baseline

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
