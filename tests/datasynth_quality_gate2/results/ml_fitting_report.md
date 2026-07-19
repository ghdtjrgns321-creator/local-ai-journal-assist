# ML Fitting 방지 품질 리포트
> 실행일: 2026-04-04 23:21 | 소요: 10.4s | 판정: **PASS**

## 요약
| Tier | 이름 | Pass | Fail | Warning | 판정 |
|------|------|------|------|---------|------|
| 1 | Feature Leakage | 6 | 0 | 0 | PASS |
| 2 | Distribution Realism | 4 | 0 | 0 | PASS |
| 3 | Cross-field Consistency | 4 | 0 | 0 | PASS |
| 4 | Reverse Leakage (Normal Perfection) | 4 | 0 | 0 | PASS |
| 5 | Compound Feature Leakage | 2 | 0 | 0 | PASS |
| 6 | Line-level GL Pair Structure | 2 | 0 | 0 | PASS |

## Tier 1: Feature Leakage
| ID | 체크 | 상태 | 기대 | 실측 |
|-----|------|------|------|------|
| L1-01 | categorical leakage scan | PASS | 비정상 전용 카테고리 값 = 0 | leakage 0건 |
| L1-02 | GL account prefix leakage | PASS | 비정상 전용 GL prefix = 0 | leakage 0건 |
| L1-03 | keyword leakage | PASS | 비정상 전용 키워드 = 0 | leakage 0건 |
| L1-04 | amount range separation | PASS | 금액 구간별 비정상 비율 < 평균의 7배 | 과집중 구간 0건 |
| L1-05 | time separation | PASS | 시간대별 비정상 비율 < 평균의 3배 (3개 초과 시 WARNING) | 과집중 시간대 1건 |
| L1-06 | extreme values | PASS | 1조원 초과 금액 = 0 | 0건 (max_dr=0e+00, max_cr=0e+00) |

## Tier 2: Distribution Realism
| ID | 체크 | 상태 | 기대 | 실측 |
|-----|------|------|------|------|
| L2-01 | amount overlap | PASS | IQR 겹침 > 30% | 겹침 100.0% (normal=[1,657,249,624], abnormal=[1,329,381,078]) |
| L2-02 | fraud rate temporal variation | PASS | 월별 fraud율 변동계수(CV) > 0.1 | CV=0.381, mean=0.0117, std=0.0045 |
| L2-03 | GL-amount joint distribution | PASS | GL그룹별 중앙값 최대/최소 비율 >= 2 | 비율=2.7x (max=32,461, min=12,162) |
| L2-04 | has_attachment fraud bias | PASS | fraud false비율 < normal의 3배 | fraud=18.3%, normal=18.0%, ratio=1.0x |

## Tier 3: Cross-field Consistency
| ID | 체크 | 상태 | 기대 | 실측 |
|-----|------|------|------|------|
| L3-01 | persona-GL correlation | PASS | persona별 GL 집중도 차이 존재 | 저집중도 persona 0개 |
| L3-02 | process-time correlation | PASS | 프로세스별 시간대 분포 차이 > 5%p | morning 비율 spread=5.4% |
| L3-03 | recurring pattern | PASS | 3개월+ 반복 GL+금액 쌍 > 0 | recurring 패턴 1862건 (total recurring=0) |
| L3-04 | normal data completeness | PASS | 필수 시나리오 누락 0 | 모두 존재 |

## Tier 4: Reverse Leakage (Normal Perfection)
| ID | 체크 | 상태 | 기대 | 실측 |
|-----|------|------|------|------|
| L4-01 | normal text missing rate | PASS | 정상 line_text 결측 2~30% | 4.3% (119,026/2,752,788) |
| L4-02 | normal approval delay | PASS | approval 지연(>0일) >= 3% | 4.9% (4,210/86,098) |
| L4-03 | normal recurring amounts | PASS | 동일 GL+금액 3회+ 반복 > 0 | 반복 패턴 16,265건 |
| L4-04 | normal description diversity | PASS | 고유 적요 비율 >= 20% | 23.5% (618,477/2,633,762) |

## Tier 5: Compound Feature Leakage
| ID | 체크 | 상태 | 기대 | 실측 |
|-----|------|------|------|------|
| L5-01 | 2-feature combo leakage | PASS | 90%+ fraud 조합 = 0 | 고위험 조합 0건 |
| L5-02 | GL x amount separation | PASS | 정상=0 GL+금액 조합 = 0 | 분리 조합 0건 |

## Tier 6: Line-level GL Pair Structure
| ID | 체크 | 상태 | 기대 | 실측 |
|-----|------|------|------|------|
| L6-01 | GL pair leakage | PASS | fraud 전용 GL쌍 (15건+) = 0 | leakage GL쌍 0건 |
| L6-02 | process GL pair realism | PASS | 프로세스별 예상 GL쌍 >= 50% | 모두 충족 |