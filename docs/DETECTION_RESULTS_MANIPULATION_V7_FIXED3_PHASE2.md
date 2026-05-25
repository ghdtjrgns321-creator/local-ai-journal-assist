# Phase2 review queue 결과 — V7 fixed3 연도별 분석 (2022/2023/2024)

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하지 않는다. 본 문서의 truth 기반 수치는 모두 합성 데이터(DataSynth) 한정의 informational 측정이며, 실데이터에서는 다를 수 있다.

> **단위 정책 (2026-05-18 확정)**: 본 문서의 recall / precision은 모두 **document(전표) 단위**다. PCAOB AS 2401·MindBridge 등 외부 감사 표준 단위와 일치시킨다. PHASE1 case 묶음은 감사인의 검토 효율을 위한 UI 단위일 뿐 외부 보고 KPI 단위가 아니므로 본 문서에서는 사용하지 않는다. 결정 근거: `docs/TROUBLESHOOT.md` TS-12.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

> **측정 갱신 (2026-05-23)**: PHASE2/통합 큐 TOP-N·UI 등급·precision/enrichment 수치는 `tools/scripts/phase1_phase2_integration_stage7.py` 의 현재 채택 식(`mode=2-way_rrf_with_phase2_noisy_or`, k=60)으로 재집계된 값이다. 산출 보고서: `artifacts/phase1_phase2_integration_report_noisy_or_20260519.json` (key `doc_recall_by_queue.integrated`). 이전 버전 일부 수치는 legacy PHASE1+VAE 2-way RRF 정의 기반이었기에 Streamlit UI(`queue_integrated.parquet` 의 `rrf_rank` 정렬)와 일치하지 않았던 문제를 해결한 갱신이다. PHASE1 단독·VAE AUROC 수치는 변경 없음(이미 일치).

---

## 한눈에 보는 결론

```
[심어 둔 부정 거래 (truth)]           620 전표 (8 시나리오)
[전체 전표]                      317,997 전표
[부정 거래 비율 (prevalence)]       0.195%

[현재 운영 랭커]
PHASE1 단독:        PHASE1 composite_sort_score
PHASE2 단독:        5-family zero-preserving Noisy-OR
PHASE1+2 통합:      PHASE1 composite ↔ PHASE2 Noisy-OR 2-way RRF k=60

[구식 TOP-N 검증표 — 절대 case 수 기준, UI 표시 등급 기준 아님]
검토 case        PHASE1 단독             PHASE2 단독             PHASE1+2 통합
                잡은 전표  recall       잡은 전표  recall       잡은 전표  recall
────────────────────────────────────────────────────────────────────────────
TOP   100         104     16.77%          43      6.94%          139     22.42%
TOP   500         276     44.52%         215     34.68%          282     45.48%
TOP 1,000         317     51.13%         253     40.81%          308     49.68%
TOP 2,000         364     58.71%         367     59.19%          370     59.68%
TOP 5,000         449     72.42%         407     65.65%          445     71.77%
TOP 10,000        493     79.52%         481     77.58%          498     80.32%

[새 UI 표시 등급 — case 순위 상위 % 기준]
즉시검토:   상위 1.25% case  ≈ TOP   500
검토대상:   상위 5.00% case  ≈ TOP 2,000
참고후보:   상위 25.0% case  ≈ TOP 10,000
후순위:     상위 25% 밖

새 UI 등급 기준 상세: `docs/users/12_RANK_PERCENTILE_REVIEW_BANDS.md`

[VAE family 보조 성능]         AUROC 0.9300 (3년 평균, unsupervised family shadow metric)
[PHASE1 ↔ PHASE2 Noisy-OR 상관] +0.0948 (거의 독립, 보완성 강함)
[5 family 보완성]              8 시나리오 모두 최소 1 family가 90%+ 잡음
```

**한 문장 요약**: 구식 TOP-N 검증표 기준 통합 큐 TOP 500 case 안에는 synthetic truth 전표 282건이 들어 있고, 그게 전체 620건의 45.48%다. 새 UI에서는 같은 취지를 절대 TOP 500이 아니라 **case 순위 상위 1.25% 즉시검토**로 표시한다. 이 수치는 실무 부정 탐지 성능이 아니라 DataSynth 개발 검증용 review queue 농축 지표다.

> **참고 — 검토 단위 보조 정보**: 통합 큐 TOP 100 case 검토 시 실제로 보는 unique 전표는 2,890건이며 그 중 139건이 synthetic truth 전표다 (precision 4.81%, 무작위 대비 24.7배). case 단위 효율 모니터링은 내부 dashboard에서만 사용한다.

> **검토 case 의 정의**: 본 문서의 "PHASE1 단독"은 PHASE1 composite_sort_score 상위 N case, "PHASE2 단독"은 5-family zero-preserving Noisy-OR score 상위 N case, "PHASE1+2 통합"은 PHASE1 composite rank와 PHASE2 Noisy-OR rank를 RRF(k=60)로 결합한 상위 N case다.

> **왜 PHASE1 단독 지표가 이전 표에 없었나**: 이 문서의 최초 목적이 “PHASE2가 PHASE1 위에 의미 있는 보조 신호를 주는가” 검증이어서 PHASE2 단독과 PHASE1+2 통합을 전면에 뒀다. 그러나 UI 표시 등급을 rank percentile 로 바꾸면서, 기준선 비교를 위해 PHASE1 단독도 같은 표에 포함한다.

---

## 0. 이 문서는 무엇인가

`datasynth_manipulation_v7_candidate_fixed3` 데이터셋(103만 행)에 PHASE2 inference를 연도별로 따로 돌린 결과. Streamlit UI 구현 전 **PHASE2가 실제로 의미 있는 결과를 내는지** 검증.

| 항목 | 값 |
|------|---|
| 데이터셋 | V7 fixed3 (합성 데이터) |
| 전체 행 | 1,032,864 |
| 전체 document (전표) | 317,997 |
| 심은 부정 거래 (truth) | **620 전표** |
| 큐 진입 truth 전표 | 540 (80건 PHASE1 case 미진입 → `docs/TROUBLESHOOT.md` TS-13) |
| review queue 진입 case | 41,129 |
| 모델/랭커 | PHASE2 5-family zero-preserving Noisy-OR + PHASE1↔PHASE2 2-way RRF |
| 분리 기준 | 회계연도 (2022 / 2023 / 2024) |
| recall/precision 단위 | **전표(document)** — PCAOB AS 2401·MindBridge 표준 일치 |

---

## 1. 심어 둔 부정 거래 — 8 시나리오, 620건

```
시나리오                                3년 합계   비중    의미
fictitious_entry                          168    27.1%   가공 매출/비용 분개
expense_capitalization                    100    16.1%   비용을 자산으로 분류
suspense_account_abuse                    100    16.1%   가수금 계정 오남용
period_end_adjustment_manipulation         92    14.8%   결산일 조정 분개 조작
embezzlement_concealment                   76    12.3%   횡령 은폐 분개
circular_related_party_transaction         34     5.5%   특수관계자 순환 거래
approval_sod_bypass                        29     4.7%   직무분리 위반 (승인 우회)
unusual_timing_manipulation                21     3.4%   비정상 시간대 조작
─────────────────────────────────────────────────────
합계                                      620   100.0%
```

연도별 분포:

```
연도   전체 행수    문서 수    truth 건수    비율
2022    348,150    106,514         181     0.052%
2023    343,950    106,171         211     0.061%
2024    340,764    105,312         228     0.067%
```

**실제 감사에서도 부정 거래는 1% 미만이 정상. 본 데이터의 0.06%는 현실적 수준.**

---

## 2. 새 UI 표시 등급 — rank percentile 기준

기존 TOP 100 / 500 / 1,000 / 2,000 / 10,000 표는 개발 검증용 **구식 절대 case 수 기준**이다. 지금 UI의 `즉시검토 / 검토대상 / 참고후보`는 데이터 크기가 달라져도 의미가 유지되도록 **case 순위 상위 %**로 표시한다.

| UI 표시 등급 | 순위 기준 | V7 fixed3 환산 | 운영 의미 |
|--------------|-----------|----------------|-----------|
| 즉시검토 | 상위 1.25% case | 약 TOP 500 | 가장 먼저 열어볼 high-priority review queue |
| 검토대상 | 상위 5.00% case | 약 TOP 2,000 | 즉시검토 다음으로 검토할 확장 queue |
| 참고후보 | 상위 25.0% case | 약 TOP 10,000 | 신호는 있으나 기본 최우선 검토는 아닌 후보군 |
| 후순위 | 상위 25% 밖 | - | UI에서는 낮은 우선순위로 취급 |

아래 표의 recall은 **누적 기준**이다. 즉 `검토대상`은 즉시검토+검토대상을 모두 봤을 때, `참고후보`는 즉시검토+검토대상+참고후보까지 봤을 때의 회수율이다.

```
UI 표시 등급     PHASE1 단독              PHASE2 단독              PHASE1+2 통합
                잡은 전표  recall        잡은 전표  recall        잡은 전표  recall
──────────────────────────────────────────────────────────────────────────────
즉시검토          276     44.52%          215     34.68%          282     45.48%
검토대상          364     58.71%          367     59.19%          370     59.68%
참고후보          493     79.52%          481     77.58%          498     80.32%
```

배타 구간으로 보면 `검토대상` 구간은 즉시검토에서 추가로 회수되는 전표, `참고후보` 구간은 검토대상 이후 추가로 회수되는 전표다.

```
UI 배타 구간      PHASE1 단독              PHASE2 단독              PHASE1+2 통합
                추가 전표  추가 recall    추가 전표  추가 recall    추가 전표  추가 recall
──────────────────────────────────────────────────────────────────────────────
즉시검토          276     44.52%          215     34.68%          282     45.48%
검토대상           88     14.19%          152     24.52%           88     14.19%
참고후보          129     20.81%          114     18.39%          128     20.65%
```

**해석**:
- PHASE1 단독은 상단 1.25%에서 강하다. rule/composite 기반 즉시검토 회수율이 44.52%다.
- PHASE2 단독은 상단 1.25%는 PHASE1보다 낮지만, 1.25%~5% 구간에서 추가 회수율이 24.52%p로 크다. 즉 ML/anomaly family는 좁은 최상단보다 확장 검토 구간에서 보완성이 강하다.
- PHASE1+2 통합은 즉시검토 구간에서 가장 높다. 상위 1.25% case 검토 시 282/620, recall 45.48%다. 검토대상 누적 구간에서도 370/620, recall 59.68%로 PHASE2 단독(59.19%)을 근소하게 앞선다.
- 이 등급은 fraud 판정 임계값이 아니라 review queue 운영 우선순위다.

---

## 3. PHASE1 단독 — composite_sort_score 기준선

PHASE1 단독 큐는 PHASE1 rule evidence와 우선순위 신호를 결합한 `composite_sort_score` 상위 N case다. PHASE1은 fraud 판정기가 아니라 감사 검토 queue 생성 단계이므로, 아래 수치는 DataSynth synthetic truth에 대한 개발 검증 기준선이다.

### PHASE1 composite_sort_score 기준 (전표 단위, 분모 620)

```
검토 case     잡은 전표   recall    precision   무작위 대비
─────────────────────────────────────────────────────────────
TOP   100       104      16.77%      2.35%       12.05배
TOP   500       276      44.52%      2.97%       15.24배
TOP 1,000       317      51.13%      2.02%       10.36배
TOP 2,000       364      58.71%      1.57%        8.05배
TOP 5,000       449      72.42%      1.29%        6.64배
TOP 10,000      493      79.52%      1.11%        5.70배
```

**왜 PHASE1 단독 지표가 이전 문서에서 약했나**:
- 이 문서는 원래 PHASE2 inference 결과를 검증하기 위해 작성됐다.
- 그래서 PHASE2 단독과 PHASE1+2 통합의 차이를 중심으로 서술했고, PHASE1 단독은 baseline으로만 암묵적으로 취급됐다.
- UI 등급이 rank percentile 기준으로 바뀐 뒤에는 PHASE1 단독도 같은 기준선 위에 놓고 비교해야 하므로, 본 문서에 별도 섹션으로 승격한다.

---

## 4. PHASE2 단독 — 5-family Noisy-OR 랭커

PHASE2 단독 큐는 `unsupervised`, `timeseries`, `relational`, `duplicate`, `intercompany` 5개 family score를 zero-preserving ECDF로 변환한 뒤 Noisy-OR로 결합한다.

### PHASE2 Noisy-OR 점수 기준 (전표 단위, 분모 620)

이 표는 구식 TOP-N 검증표다. UI 표시 등급은 위 `rank percentile` 기준을 사용한다.

```
검토 case     잡은 전표   recall    precision   무작위 대비
─────────────────────────────────────────────────────────────
TOP   100        43       6.94%      2.11%       10.8배
TOP   500       215      34.68%      3.00%       15.4배
TOP 1,000       253      40.81%      2.28%       11.7배
TOP 2,000       367      59.19%      1.91%        9.8배
TOP 5,000       407      65.65%      1.36%        7.0배
TOP 10,000      481      77.58%      1.16%        6.0배
TOP   412       190      30.65%      2.95%       15.1배
```

### VAE family 판별 능력 (AUROC)

아래 AUROC는 PHASE2 단독 큐의 최종 랭커가 아니라 `unsupervised` family(VAE)의 보조 진단 지표다.

```
연도    AUROC
2022    0.9274
2023    0.9252
2024    0.9374
────────────────
3년 평균  0.9300  ← 우수 (1.0=완벽, 0.5=동전던지기)
```

### VAE 위험 점수 상위 N% 보조 진단 (행 단위, 3년 합산)

```
구간            진입 행수    그 중 진짜 부정    무작위 대비 농축
상위 5% (q95)     79,235          923         19.4배
상위 1% (q99)     19,721          642         54.2배
무작위 평균            -            -          1.0배 (=0.06%)
```

→ VAE family score의 상위 1% 구간은 무작위 대비 **54배** 농축된다. 현재 PHASE2 단독 큐의 최종 정렬은 5-family Noisy-OR다.

---

## 5. PHASE1+2 통합 — PHASE1 composite ↔ PHASE2 Noisy-OR RRF

통합 큐는 PHASE1 단독 큐가 아니다. 현재 운영 식은 다음과 같다.

```
phase2_internal_noisy_or(case) = 1 - Π_f (1 - ecdf_f(case))
final_rrf_score(case) =
    1/(60 + rank_phase1_composite(case))
  + 1/(60 + rank_phase2_internal_noisy_or(case))
```

### 통합 큐 결과 (전표 단위, 분모 620)

이 표도 구식 TOP-N 검증표다. UI에서는 같은 구간을 상위 1.25% / 5% / 25% rank band로 표시한다.

```
검토 case     잡은 전표   recall    precision   무작위 대비
─────────────────────────────────────────────────────────────
TOP   100       139      22.42%      4.81%       24.7배
TOP   500       282      45.48%      2.86%       14.7배
TOP 1,000       308      49.68%      2.06%       10.6배
TOP 2,000       370      59.68%      1.73%        8.9배
TOP 5,000       445      71.77%      1.32%        6.8배
TOP 10,000      498      80.32%      1.09%        5.6배
TOP   412       210      33.87%      2.71%       13.9배
```

### PHASE2 단독 vs PHASE1+2 통합

```
구간       관찰
────────────────────────────────────────────────────────────────────────
TOP 100    통합 22.42% vs PHASE2 6.94%  — PHASE1 rule 신호가 좁은 구간 크게 보강 (+15.48%p)
TOP 500    통합 45.48% vs PHASE2 34.68% — 통합 큐가 +10.80%p 높음
TOP 1,000  통합 49.68% vs PHASE2 40.81% — 통합 큐가 +8.87%p 높음
TOP 2,000  통합 59.68% vs PHASE2 59.19% — 두 큐 거의 동률, PHASE2가 깊은 구간에서 따라잡음
TOP 5,000+ 둘 다 70%대까지 올라가지만 통합 큐가 +6%p 내외로 높은 recall 유지
```

**핵심 관찰**:
- PHASE1+2 통합은 좁은 상단 구간에서 강하다. TOP 100 precision 4.81%, 무작위 대비 24.7배다.
- PHASE1+2 통합은 깊은 구간 recall도 높다. TOP 1,000에서 49.68%, TOP 10,000에서 80.32%다.
- PHASE2 단독은 중간 구간(TOP 500~2,000)에서 precision 2~3%대를 안정적으로 유지하며, 통합 큐와 함께 봤을 때 family signal 보완성을 제공한다.
- 통합 큐는 fraud 판정기가 아니라 auditor review queue다. 숫자는 DataSynth synthetic truth 기준의 개발 검증 지표다.

### PHASE1 ↔ PHASE2 상관관계

```
corr(PHASE1 composite_sort_score, PHASE2 Noisy-OR) = +0.0948  (거의 무상관)
corr(PHASE1 composite_sort_score, VAE max score)   = +0.0752  (보조 지표)
```

→ **두 신호가 거의 독립**이다. PHASE1 rule evidence와 PHASE2 5-family anomaly evidence가 다른 전표를 상위로 올리므로, 통합 큐에서 보완성이 생긴다.

---

## 6. 상위 1% 구간 — PHASE2 단독 vs PHASE1+2 통합

```
방식                                          진입 전표   잡은 truth   recall    precision   무작위 대비
────────────────────────────────────────────────────────────────────────────────────────────────────
PHASE1 단독 TOP 412 case                        8,565       269        43.39%       3.14%       16.1배
PHASE2 단독 TOP 412 case                        6,439       190        30.65%       2.95%       15.1배
PHASE1+2 통합 TOP 412 case                      7,759       210        33.87%       2.71%       13.9배
PHASE1 ∪ PHASE2 단독 합집합                    12,382       293        47.26%       2.37%       12.1배
PHASE1 ∩ PHASE2 단독 교집합                     2,622       166        26.77%       6.33%       32.5배
```

**해석**:
- PHASE1 단독 TOP 1%가 가장 강하다. recall 43.39%, precision 3.14%다.
- PHASE2 단독 TOP 1%는 PHASE1보다 좁게 진입하지만 (6,439 vs 8,565 전표) recall 30.65%, precision 2.95%로 PHASE1 대비 큰 차이는 없다.
- 통합 TOP 1%는 두 ranker의 합의를 반영해 더 균형 잡힌 위치를 잡는다. recall 33.87%, precision 2.71%.
- PHASE1 ∪ PHASE2 합집합은 두 ranker의 분리된 신호를 모두 받아 recall 47.26%까지 올라가지만 진입 전표 12,382로 검토 부담이 커진다.
- PHASE1 ∩ PHASE2 교집합은 두 ranker가 동시에 상단으로 올린 좁은 영역(2,622 전표)으로, precision 6.33%·무작위 대비 32.5배로 가장 정밀한 보조 검토 구간이다.

---

## 7. recall N% 달성하려면 case 몇 개 봐야 하나

```
목표 recall    잡아야 할 전표    PHASE2 단독              PHASE1+2 통합
────────────────────────────────────────────────────────────────────────────
recall 50%        310 / 620        TOP  1,161 case         TOP  1,079 case
recall 80%        496 / 620        TOP 14,190 case         TOP  9,740 case
recall 90%        558 / 620        달성 불가               달성 불가
recall 95%        589 / 620        달성 불가               달성 불가
recall 100%       620 / 620        달성 불가               달성 불가
```

**해석**:
- recall 50% — PHASE1+2 통합은 TOP 1,079 case, PHASE2 단독은 TOP 1,161 case가 필요하다. 두 큐 모두 비슷한 case 수가 필요하지만 통합 큐가 약간 더 효율적이다.
- recall 80% — 통합은 TOP 9,740 case, PHASE2 단독은 TOP 14,190 case가 필요하다. 깊은 구간에서 통합 큐의 우위가 분명해진다.
- recall 90% 이상은 **PHASE1 case 미진입 truth 80건 때문에 현재 case queue 자체에서 달성 불가**다. 정렬 개선만으로 회수 불가. → `docs/TROUBLESHOOT.md` TS-13 (PHASE1 룰 커버리지 갭).
- recall ceiling = (큐 진입 truth 540) / (원본 620) = **87.10%**. 출처: `docs/TROUBLESHOOT.md` TS-13, `artifacts/ts13_uncovered_truth_80_analysis.json`.

→ **포트폴리오 관점 권장 표현**: TOP 500~1,000 통합 review queue에서 synthetic truth recall 45~50%를 보이며, 이는 실데이터 운영 성능 보장이 아니라 review-worthy anomaly 농축 검증이다.

---

## 8. 5 family 보완성 — 같은 거 잡나, 다른 거 잡나

각 family가 시나리오별 truth 잡은 비율 (2024년 기준, document 단위):

```
시나리오                            truth  unsup  timeseries  relational  duplicate  intercompany
                                     (건)
─────────────────────────────────────────────────────────────────────────────────────────────────
circular_related_party                 13   92%        100%        100%        85%            0%
embezzlement_concealment               29   97%          0%        100%       100%            0%
expense_capitalization                 34  100%         85%         88%        94%            0%
fictitious_entry                       64   86%        100%         33%         9%            0%
period_end_adjustment_manipulation     35   60%         97%          0%        69%            0%
suspense_account_abuse                 34   65%         47%         41%       100%            0%
unusual_timing_manipulation             8  100%        100%        100%         0%            0%
approval_sod_bypass                    11   64%         91%         91%         0%            0%
─────────────────────────────────────────────────────────────────────────────────────────────────
8 시나리오 모두 최소 1 family가 90%+ 잡음 → 보완성 확인
```

### 각 family가 강한 시나리오

```
family          강한 시나리오                                       시나리오 적합도
unsupervised    expense_capitalization, unusual_timing (100%)         넓은 패턴 이상
timeseries      fictitious_entry, unusual_timing (100%)               시간 패턴 이상
relational      circular, embezzlement, unusual_timing (100%)         관계망 이상
duplicate       embezzlement, suspense (100%)                          중복/유사 거래
intercompany    0/8 (V7 fixed3 데이터 한계, Diag-1 후 IC01만 부분 활성) 그룹사 거래 (carry-over)
```

**핵심**:
- timeseries는 fictitious 100% 잡지만 embezzlement는 0%
- relational은 그 반대 (embezzlement 100%, fictitious 33%)
- → **단일 family로는 못 잡는 시나리오를 다른 family가 잡음** (보완성 증거)

### 5 family 동작 비율 (3년 합산, 행 단위)

```
family          hit 행수      비율
unsupervised      79,235     7.67%   상위 5% 위주, 정밀
timeseries       891,464    86.30%   대부분 hit (TS02 과민) → top-N 필터 필요
relational        46,794     4.53%   소수만 hit, 일관
duplicate        222,400    21.53%   중간 정도, fuzzy 매칭
intercompany          34    0.003%   Diag-1 후 IC01만 (carry-over)
```

### family ranking 정책 (2026-05-19 lock)

본 §8 의 family complementarity 표는 PHASE2 5 family 결합 ranking 설계의 정성 근거가 되었다. 결합 설계는 다음과 같이 lock 됐다 — 자세한 거버넌스는 `docs/PHASE2_GOVERNANCE_DESIGN.md` 결정 8 참조.

| 항목 | 결정 |
|---|---|
| PHASE2 단독 큐 | 5-family zero-preserving Noisy-OR score 정렬 |
| PHASE1+2 통합 큐 | PHASE1 composite ↔ PHASE2 Noisy-OR 2-way RRF k=60 |
| PHASE2 internal hierarchical RRF | reject — V7 fixed3 measurement-only 비교에서 TOP 100~5000 평균 -6.45pp 손실 |
| family signal 노출 | lane (`duplicate / relational / timing / intercompany`) + Phase2CaseOverlay (`family_contributions / top_family / lane_membership / coverage_gap_families`) + 6단 tie-break (primary RRF 동률 한정) + PHASE3 narrator citation |
| 격리 산출물 | `compute_phase2_internal_rrf` + `test_queue_fusion_hierarchical.py` (`pytest.mark.experimental_phase2_internal_rrf`) — supervised/transformer 활성화 시 재평가 |
| 측정 근거 | 현재 코드 `tools/scripts/phase1_phase2_integration_stage7.py::{build_phase2_queue, build_integrated_queue}` 기준 재계산 |
| 거버넌스 출처 | `docs/PHASE2_GOVERNANCE_DESIGN.md` 결정 8, `dev/active/phase2-family-ranking/` plan/context/tasks |

본 §8 의 시나리오 × family detection matrix 는 lane view 의 attribution 근거로도 사용된다 (예: `embezzlement` lane 에서 duplicate 100% / relational 100% / unsupervised 97% 신호 결합).

---

## 9. 연도별 결과가 안정적인가

VAE는 2022/2023 데이터로 학습 + 2024로 검증.

```
연도   AUROC    q95 진입 행수    q95 잡은 truth   truth/q95 비율
2022   0.9274          22,689             266          1.17%
2023   0.9252          26,172             297          1.13%
2024   0.9374          30,374             360          1.18%
```

### 관찰

- **AUROC 0.927 → 0.937** — 큰 변동 없음, 학습 안정
- **q95 진입 행수 33.9% 증가** (22,689 → 30,374) — VAE가 2024를 다소 OOD로 인식 (Layer B drift 15.8%과 정합)
- **truth 비율 1.13~1.18% 유지** — 정밀도 안정

→ 운영상 안정적이지만, 연도별 calibration이 필요할 수도 있음 (정기 재학습 권장).

---

## 10. 외부 shadow 검증 — Tritscher ERP-Fraud

V7 fixed3 DataSynth만 보면 PHASE2 VAE가 합성 데이터에만 잘 맞는지 판단하기 어렵다.
그래서 공개 Tritscher ERP-Fraud 데이터셋을 별도 외부 synthetic ERP shadow benchmark로 돌렸다.

| 항목 | DataSynth V7 fixed3 | Tritscher ERP-Fraud shadow |
|------|---------------------|----------------------------|
| 성격 | 프로젝트 합성 JE | 외부 SAP ERP simulation |
| 평가 단위 | document 중심 | row + document |
| truth 수 | 620 documents | 248 rows / 37 documents |
| VAE 평균 AUROC | 0.9300 | row 0.6521 / document 0.8670 |
| document recall@100 | 내부 큐 기준 별도 산출 | 평균 0.4375 |

해석:

- Tritscher에서도 row-level ranking은 불안정하지만 document-level ranking은 의미 있게 유지된다.
- VAE가 DataSynth V7 fixed3에만 과하게 맞춰졌다는 우려는 일부 줄었다.
- 반대로 외부 데이터에서는 성능이 낮아지므로, DataSynth 수치를 운영 성능으로 그대로 읽으면 안 된다.
- 이 결과는 active `unsupervised` family의 shadow evidence일 뿐이며, `supervised`, `transformer`, `sequence`, `stacking` dormant 해제 근거가 아니다.

관련 산출물:

- `artifacts/external_validation/tritscher_erp_fraud_20260519/tritscher_vae_shadow_benchmark.md`
- `artifacts/external_validation/tritscher_erp_fraud_20260519/tritscher_shadow_benchmark_comparison.md`
- `artifacts/external_validation/tritscher_erp_fraud_20260519/phase2_external_shadow_summary.md`

---

## 11. 한계 — 이 수치 그대로 믿을 수 있나

```
번호  한계                              중요도  설명
────  ────────────────────────────────  ──────  ────────────────────────────────────────
 1    합성 데이터 기반                  ★★★    실데이터는 패턴이 미묘해 AUROC 떨어질 가능성
 2    학습 데이터 ≒ 검증 데이터          ★★★    같은 V7 fixed3로 학습+검증, 실데이터 재검증 필수
 3    intercompany family 0건           ★★     Diag-1 후 IC01만 부분 회복 (3 sub 중 1)
 4    timeseries TS02 과민              ★★     86% 행 hit, 점수 top-N 필터 필요
 5    supervised 트랙 비활성            ★      truth 0.06%로 라벨 부족 → low_signal_fallback (정상)
 6    100% recall 비현실적              ★★     현재 case queue 미진입 truth 80건 때문에 ceiling 87.10%
```

**핵심**: 본 수치는 "PHASE2 인프라가 정상 작동하는가" 검증. 실제 운영 성능은 고객사 실데이터 유입 후 재측정 필요.

---

## 12. 다음 단계

```
우선순위  작업                                            기대 효과
즉시      Streamlit UI에서 본 결과 시각화 (UI-A4 완료,    감사인 직접 확인 가능
          사용자 실행 검증 대기)
중기      intercompany matched-pair 데이터 enrichment    IC02/IC03 활성화 (3 sub 모두 hit)
중기      실데이터 fixture 확보 후 재측정                실제 성능 검증
장기      HITL 라벨 누적 → supervised 트랙 활성화        정밀도 추가 향상
```

---

## 13. 참고

- 본 측정 산출물:
  - `artifacts/phase2_inference_v7_fixed3_year_2022.json`
  - `artifacts/phase2_inference_v7_fixed3_year_2023.json`
  - `artifacts/phase2_inference_v7_fixed3_year_2024.json`
- PHASE2 단독 review queue: `data/companies/_ci_baseline/engagements/2026/review_queue/v1/queue_phase2.parquet`
- PHASE1+2 통합 review queue: `data/companies/_ci_baseline/engagements/2026/review_queue/v1/queue_integrated.parquet`
- legacy alias: `data/companies/_ci_baseline/engagements/2026/review_queue/v1/queue.parquet` 는 PHASE1 단독 큐
- 재실행 스크립트: `tools/scripts/phase2_inference_v7_fixed3_by_year.py`
- 관련 sprint handoff:
  - Stage 5 첫 학습 산출물: `data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/v1/training_report.json`
  - smoke handoff: `artifacts/sprint_phaseA_smoke_v7_fixed3_by_year_handoff_20260518.md`
  - Diag-1 intercompany: `artifacts/sprint_phaseA_diag1_intercompany_handoff_20260518.md`
  - Diag-2 duplicate: `artifacts/sprint_phaseA_diag2_duplicate_optimization_handoff_20260518.md`
  - UI-A4: `artifacts/sprint_phaseB_a4_phase2_streamlit_handoff_20260518.md`
- V4 PHASE1 측정 비교 원본: `docs/completed/DETECTION_RESULTS_MANIPULATION_V4.md`

---

## 14. 용어 풀이

| 용어 | 풀이 |
|------|------|
| AUROC | 모델이 부정/정상을 구분하는 능력. 1.0=완벽, 0.5=동전던지기, 0.9 이상이면 우수 |
| recall | 전체 부정 거래 중 모델이 잡은 비율 (얼마나 빠짐없이 잡았나) |
| precision | 모델이 부정이라고 한 것 중 진짜 부정 비율 (잘못 부른 게 얼마나 적나) |
| enrichment | 무작위로 봤을 때 대비 몇 배 더 잘 찾았나 |
| q95 / q99 | 점수 상위 5% / 1% 의 거래만 본 결과 |
| truth | 합성 데이터에 의도적으로 심어 둔 부정 거래 (정답 라벨) |
| OOD | Out-Of-Distribution. 모델이 학습한 분포와 다른 데이터 |
| family | PHASE2에서 묶은 detector 그룹 (unsupervised + 4 룰 기반 = 5종) |
| sub-detector | family 안의 개별 detection 규칙 (총 13개) |
