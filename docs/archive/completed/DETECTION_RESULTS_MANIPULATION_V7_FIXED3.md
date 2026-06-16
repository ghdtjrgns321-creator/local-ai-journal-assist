# Phase1 Detection 결과 - V7 fixed3 manipulation truth

> **PHASE1 역할 원칙**: PHASE1은 `fraud` 확정 단계가 아니라 감사인이 검토할 review queue를 만드는 단계다. 이 문서의 truth 기반 수치는 합성 데이터(DataSynth) 한정의 informational 측정이며, PHASE1 설정 변경이나 threshold fitting에 사용하지 않는다.

> **단위 정책 (TS-12)**: 외부 KPI는 전표(document) 단위로만 보고한다. case 수는 감사인 검토 UI의 운영 단위이며 recall/precision의 분모로 쓰지 않는다.

## 0. 한눈에 보는 결론

- Truth 전표: **620** / 전체 전표: **317,997** / 전체 row: **1,032,864**
- PHASE1 review queue case: **41,129**
- 큐 진입 truth 전표: **540** / 큐 미진입 truth 전표: **80**
- PHASE1 단독 recall ceiling: **87.10%**
- TOP 100 recall: **16.77%** / TOP 1,000 recall: **51.13%**

## 1. 데이터 / 입력 / 실행 환경

| 항목 | 값 |
| --- | --- |
| 데이터셋 | datasynth_manipulation_v7_candidate_fixed3 |
| cache | `artifacts/phase1_manipulation_v7_fixed3_case_input.pkl` |
| truth | `data/journal/primary/datasynth_manipulation_v7_candidate_fixed3/labels/manipulated_entry_truth.csv` |
| settings | `config/settings.py` default `get_phase1_case()` |
| settings hash | `c8a03293e43e5048` |
| run timestamp | `2026-05-18T14:45:32+00:00` |

Detector는 재실행하지 않았다. PHASE2 문서 작성 때 보존된 `stage7_phase1_case_result.pkl` case builder output을 우선 재사용했고, 없을 때만 기존 cache의 PHASE1 detector output으로 case builder를 재구성한다.

## 2. 시나리오별 truth 분포

| 시나리오 | truth | 큐 진입 | 큐 미진입 | 미진입률 |
| --- | --- | --- | --- | --- |
| approval_sod_bypass | 29 | 29 | 0 | 0.00% |
| circular_related_party_transaction | 34 | 33 | 1 | 2.94% |
| embezzlement_concealment | 76 | 37 | 39 | 51.32% |
| expense_capitalization | 100 | 100 | 0 | 0.00% |
| fictitious_entry | 168 | 136 | 32 | 19.05% |
| period_end_adjustment_manipulation | 92 | 84 | 8 | 8.70% |
| suspense_account_abuse | 100 | 100 | 0 | 0.00% |
| unusual_timing_manipulation | 21 | 21 | 0 | 0.00% |

## 3. 미탐(FN) 진단

TS-13 기준과 동일하게 큐 미진입 truth 전표는 **80건**이다. 다만 최초의 "어떤 룰도 hit하지 않음" 가설은 TS-13에서 정정되었다. 80건 모두 raw/review PHASE1 신호는 있었지만, row risk band 또는 case seed priority가 낮아 case builder 진입 조건을 넘지 못했다.

| 분류 | 건수 | 해석 |
| --- | --- | --- |
| (a) 룰 부재 | 0 | 80건 모두 어떤 형태로든 PHASE1 raw/review score가 있었다. |
| (b) 임계값/seed 미달 | 80 | raw 신호는 있으나 case seed 조건을 넘지 못했다. |
| (c) 데이터 결손 | 0 | 주요 입력 컬럼 전체 결손으로 평가 불가능한 패턴은 확인되지 않았다. |

TS-13 공통 특성 요약: P2P/O2C, automated/recurring source, 고액 전표에 미진입 80건이 집중된다. 특히 5억원 초과 전표가 71건(88.75%)이다. 원문 raw 분석은 `artifacts/ts13_uncovered_truth_80_analysis.json`과 `artifacts/ts13_recovery_path_evaluation.md`를 참조한다.

## 4. PHASE1 단독 큐 TOP N 회수율

| 검토 case | cover 전표 | 잡은 truth | recall/620 | recall/540 | precision | 무작위 대비 |
| --- | --- | --- | --- | --- | --- | --- |
| 100 | 4428 | 104 | 16.77% | 19.26% | 2.35% | 12.05배 |
| 500 | 9289 | 276 | 44.52% | 51.11% | 2.97% | 15.24배 |
| 1000 | 15695 | 317 | 51.13% | 58.70% | 2.02% | 10.36배 |
| 2000 | 23206 | 364 | 58.71% | 67.41% | 1.57% | 8.05배 |
| 5000 | 34708 | 449 | 72.42% | 83.15% | 1.29% | 6.64배 |
| 10000 | 44378 | 493 | 79.52% | 91.30% | 1.11% | 5.70배 |
| 41129 | 68549 | 540 | 87.10% | 100.00% | 0.79% | 4.04배 |

## 5. 시나리오별 회수 위치 분포

| 시나리오 | ranked | unranked | 평균 rank | 중앙값 | 최소 | 최대 | TOP100 | TOP500 | TOP1000 | TOP2000 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| approval_sod_bypass | 29 | 0 | 4039.0 | 2386 | 54 | 21768 | 2 | 5 | 8 | 12 |
| circular_related_party_transaction | 33 | 1 | 10182.6 | 2045 | 68 | 35274 | 4 | 10 | 11 | 16 |
| embezzlement_concealment | 37 | 39 | 1965.6 | 2333 | 941 | 4187 | 0 | 0 | 12 | 16 |
| expense_capitalization | 100 | 0 | 1049.0 | 323 | 60 | 36896 | 3 | 94 | 94 | 95 |
| fictitious_entry | 136 | 32 | 4052.2 | 1048 | 2 | 28886 | 45 | 51 | 67 | 84 |
| period_end_adjustment_manipulation | 84 | 8 | 4382.3 | 2190 | 29 | 28400 | 2 | 16 | 23 | 35 |
| suspense_account_abuse | 100 | 0 | 148.3 | 111 | 21 | 313 | 48 | 100 | 100 | 100 |
| unusual_timing_manipulation | 21 | 0 | 4351.1 | 4030 | 530 | 9310 | 0 | 0 | 2 | 6 |

상위권에 가장 잘 잡히는 축은 suspense account abuse와 expense capitalization 쪽이다. fictitious entry는 일부가 TOP 100에 강하게 잡히지만 32건이 큐 미진입이고, embezzlement concealment와 unusual timing은 큐 진입 후에도 상대적으로 하위 rank에 묻힌다.

## 6. 룰별 truth 기여도 (보조)

아래 표는 queue case 안의 `raw_rule_hits` 기준이다. detector raw detail 기준은 JSON의 `rule_contribution.detector_raw_detail_hits`에 별도 보존했다.

| 룰 | queue truth hit | recall/620 |
| --- | --- | --- |
| L3-12 | 487 | 78.55% |
| L3-04 | 437 | 70.48% |
| L3-02 | 352 | 56.77% |
| L2-03 | 239 | 38.55% |
| L3-05 | 226 | 36.45% |
| L1-03 | 200 | 32.26% |
| L1-05 | 127 | 20.48% |
| L3-06 | 127 | 20.48% |
| L1-04 | 103 | 16.61% |
| L2-04 | 100 | 16.13% |
| L3-07 | 100 | 16.13% |
| L4-05 | 96 | 15.48% |
| L3-09 | 89 | 14.35% |
| L4-03 | 68 | 10.97% |
| L3-03 | 33 | 5.32% |
| L1-09 | 29 | 4.68% |
| L2-05 | 17 | 2.74% |
| L4-01 | 17 | 2.74% |
| L4-06 | 14 | 2.26% |
| L2-02 | 7 | 1.13% |
| L2-01 | 3 | 0.48% |

Detector raw detail 기준으로는 19개 rule id가 truth 전표에 하나 이상 hit했다. 이 수치는 case seed 진입 전 raw 신호 측정이므로 운영 queue 기여도와 구분해야 한다.

## 7. 과탐 양 추정 (보조)

| 항목 | 값 |
| --- | --- |
| 큐 진입 unique 전표 | 68,549 |
| 그 중 truth 전표 | 540 |
| 잠재 과탐 전표 | 68,009 |
| 잠재 과탐률 | 99.21% |

이는 운영 부담 지표일 뿐이다. 정상 전표가 PHASE1 큐에 있다고 곧장 부정 의심이나 확정 위반을 뜻하지 않는다. 감사인은 review 후 정상 dismiss를 수행한다.

## 8. 연도별 비교

| 연도 | truth | TOP 1,000 회수 | doc recall |
| --- | --- | --- | --- |
| 2022 | 181 | 77 | 42.54% |
| 2023 | 211 | 110 | 52.13% |
| 2024 | 228 | 130 | 57.02% |

## 9. PHASE2 / RRF 와 비교

비교 기준은 `docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md` §3의 3개 큐 비교 표다. 본 문서는 PHASE1 단독 큐 detail을 전표 단위로 확장한 별도 산출물이다.

| TOP N | PHASE1 단독 | PHASE2 단독 | 통합 RRF | RRF-PHASE1 |
| --- | --- | --- | --- | --- |
| 100 | 104 (16.77%) | 55 (8.87%) | 103 (16.61%) | -0.16%p |
| 500 | 276 (44.52%) | 185 (29.84%) | 268 (43.23%) | -1.29%p |
| 1000 | 317 (51.13%) | 241 (38.87%) | 324 (52.26%) | +1.13%p |
| 2000 | 364 (58.71%) | 356 (57.42%) | 391 (63.06%) | +4.35%p |
| 5000 | 449 (72.42%) | 433 (69.84%) | 456 (73.55%) | +1.13%p |
| 10000 | 493 (79.52%) | 463 (74.68%) | 498 (80.32%) | +0.80%p |

RRF는 TOP 1,000 이후부터 PHASE1 단독보다 약간 우세하며, TOP 2,000에서 차이가 가장 크다. 다만 현재 RRF는 PHASE1 case-bound queue이므로 TS-13의 큐 미진입 80건 자체는 회수하지 못한다.

## 10. CONTRACT_V3 와의 의미 차이

`docs/guide/DETECTION_RESULTS_CONTRACT_V3.md`는 `rule_truth_*`를 기준으로 detector가 계약 spec대로 작동하는지 검증한다. 그 문서의 PASS는 룰 계약 기준의 recall 100%, FP 0, FN 0을 의미한다.

반면 본 문서는 `manipulated_entry_truth.csv`의 의도 주입 부정 전표 620건이 PHASE1 review queue에서 얼마나 회수되는지 측정한다. 이 truth는 특정 룰의 정답이 아니라 시나리오형 조작 전표이므로, 현재 PHASE1 단독 ceiling은 540/620 = 87.10%다. 두 척도는 서로 모순되지 않는다.

## 11. 한계 + 다음 단계

- 본 결과는 V7 fixed3 합성 데이터 한정 측정이다. 실데이터 일반화는 보장하지 않는다.
- truth label은 측정에만 사용했고 PHASE1 detector threshold, case builder, 32 룰 카탈로그, `config/phase1_case.yaml`은 변경하지 않았다.
- 미진입 80건 회수 경로 결정은 TS-13 별도 sprint 범위다. 본 문서는 현재 PHASE1 단독 설정의 회수 가능 ceiling을 명시하는 데 그친다.
- 다음 검증은 PHASE2 단독 document queue와 RRF 통합 큐의 운영 비용/효익 비교다.
