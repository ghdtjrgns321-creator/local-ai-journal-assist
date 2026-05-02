
## 전체적으로 과탐 미탐 테스트 -> 임시스크립트로 돌릴때마다 결과 달라짐 실제 프로젝트에서 돌아가는 걸로 돌리라고 명시해야됨
미탐 = 0 이면 우선 FITTING 의심
L1
L2
L3
L4
D

  룰       룰 이름             정답   탐지   정탐   과탐   미탐
  L2-01   승인한도 근접         83    457     83    374      0
  L2-02   중복 지급             33     33     11     22     22
  L2-03   중복 전표             67    105      0    105     67
  L2-04   비용 자본화           33    751     33    718      0
  L2-05   역분개 패턴           51     82     51     31      0



  • 2022

  | 룰 | 룰 이름 | 정답 | 탐지 | 정탐 | 과탐 | 미탐 |
  |---|---|---:|---:|---:|---:|---:|
  | L4-01 | 매출 이상 변동 | 334 | 509 | 303 | 206 | 31 |
  | L4-02 | Benford 위반 | 36 | 35 | 35 | 0 | 1 |
  | L4-03 | 이상 고액 | 1,363 | 1,916 | 1,290 | 626 | 73 |
  | L4-04 | 비정상 계정조합 | 1,145 | 3,245 | 1,113 | 2,132 | 32 |
  | L4-05 | 비정상시간 집중입력 | 8 | 1,081 | 6 | 1,075 | 2 |
  | L4-06 | 배치 전표 이상 | 190 | 219 | 69 | 150 | 121 |

  • 2023

  | 룰 | 룰 이름 | 정답 | 탐지 | 정탐 | 과탐 | 미탐 |
  |---|---|---:|---:|---:|---:|---:|
  | L4-01 | 매출 이상 변동 | 284 | 510 | 257 | 253 | 27 |
  | L4-02 | Benford 위반 | 32 | 32 | 31 | 1 | 1 |
  | L4-03 | 이상 고액 | 1,259 | 1,969 | 1,223 | 746 | 36 |
  | L4-04 | 비정상 계정조합 | 1,124 | 2,602 | 1,119 | 1,483 | 5 |
  | L4-05 | 비정상시간 집중입력 | 10 | 485 | 4 | 481 | 6 |
  | L4-06 | 배치 전표 이상 | 187 | 444 | 99 | 345 | 88 |

  • 2024

  | 룰 | 룰 이름 | 정답 | 탐지 | 정탐 | 과탐 | 미탐 |
  |---|---|---:|---:|---:|---:|---:|
  | L4-01 | 매출 이상 변동 | 347 | 481 | 306 | 175 | 41 |
  | L4-02 | Benford 위반 | 32 | 32 | 31 | 1 | 1 |
  | L4-03 | 이상 고액 | 1,392 | 1,916 | 1,288 | 628 | 104 |
  | L4-04 | 비정상 계정조합 | 1,234 | 2,759 | 1,227 | 1,532 | 7 |
  | L4-05 | 비정상시간 집중입력 | 9 | 1,095 | 4 | 1,091 | 5 |
  | L4-06 | 배치 전표 이상 | 176 | 334 | 64 | 270 | 112 |
## 실제 조작 -> SIDECAR에 어떤걸 넣을지

## 끝나고 점수 다시 검사 기준 바뀐룰들있음

상태: 2026-04-27 1차 구현 완료.

- `src/detection/rule_scoring.py` 추가 완료
- PHASE1 transaction rule registry 전수 커버리지 테스트 추가 완료
- `phase1_case_builder` evidence type score 합산을 `severity / 5` 단순 합산에서 `normalized_score` 합산으로 변경 완료
- `RawRuleHitRef` / export drill-down에 `display_label`, `signal_strength`, `normalized_score`, `evidence_strength`, `scoring_role` 노출 완료
- 관련 단위 테스트: `38 passed`

남은 확인:

- 넓은 `tests/modules/test_detection` 전체는 4분 제한에서 timeout. 첫 실패는 `L3-05 reason_code`의 `holiday` vs `weekday_holiday` 기대값 불일치로, PHASE1 점수 통합 변경과 별개 정합성 이슈다.
- 다음 사이클에서는 macro Account / Process Queue UI/데이터 모델을 별도 구현해야 한다.


# RULES 재정비 끝나고
## PHASE1이후-1


## PHASE1이후-2




## L4 점수체계 SIDECAR
## L2 점수체계 SIDECAR



  DataSynth 수정 대상
  | 영역 | 판단 | 수정 방향 |
  |---|---|---|
  | D01 review/control 구성 | 대체로 정상 | D01은 이미 truth 336 + normal_controls 504 = review 840이
  고, 미탐 0입니다. 정상 control을 제거하면 안 됩니다. |
  | D01 control metadata | 보강은 되어 있음 | tools/scripts/
  build_datasynth_v57_d01_control_metadata.py:57에서 evaluation_bucket, business_event_type,
  precision_policy를 넣고 있어 방향은 맞습니다. 추가로 expected_macro_priority_band 정도만 넣으면 코드
  점수 검증이 쉬워집니다. |
  | D02 metadata | 수정 필요 | D02에는 D01 v57 같은 evaluation_bucket/precision_policy/
  business_event_type 보강이 없습니다. normal_recurring_or_interface_batch,
  normal_project_or_bonus_expense_concentration, normal_seasonal_or_quarter_end_revenue를 명시적 score
  bucket으로 만들어야 합니다. |
  | D02 normal classifier | 수정 필요 | tools/scripts/build_datasynth_v56_monthly_pattern_shift.py:211
  는 normal reason에 “interface batch”라고 쓰지만 실제 source 판정은 automated/recurring만 봅니다.
  interface, batch, system, auto도 정상 반복/배치 패턴으로 분류해야 합니다. |
  | 정상 control 다양성 | 일부 보강 필요 | D02 과탐 151건 중 130건이 recurring/interface batch에 몰려
  있습니다. 정상 seasonal revenue, bonus/project timing, allocation/depreciation, interface cutover 같
  은 정상 원인을 더 균형 있게 넣어야 score 분리 학습/검증이 안정적입니다. |
  | Row label 변경 | 수정 대상 아님 | D01/D02는 계정 단위 sidecar가 truth입니다. journal row의
  is_anomaly를 바꿔서 맞추면 오히려 PHASE1 계약을 깨뜨립니다. |
    D01

  - 구성은 명확합니다.
      - account_activity_variance_truth.csv: 336 groups, 전부 confirmed_truth,
        is_true_positive_account=True
      - account_activity_variance_normal_controls.csv: 504 groups, 전부 is_true_positive_account=False
      - account_activity_variance_review_population.csv: 840 groups = truth 336 + control/review 504
      - rule_truth_D01.csv: 840 groups와 1:1 겹침
  - 의미는 괜찮습니다. price_increase, capex_investment_event, working_capital_timing,
    high_volume_operations, recurring_or_system_volume_shift, review_only_activity_variance처럼 실제
    있을 법한 사유가 들어 있습니다.
  - 주의점: normal_controls 504건도 전부 expected_d01_flag=True이고 rule_truth_D01.csv에 포함됩니다.
    즉 “D01이 잡으면 안 되는 negative control”이 아니라 D01 raw review hit는 맞지만 confirmed truth는
    아닌 정상 사업 변화/리뷰 큐입니다.

  수정 필요:

  - account_activity_variance_normal_controls 이름은 유지하더라도 manifest에서
    expected_detector_positive=true, confirmed_truth=false를 명시해야 합니다.
  - D01에는 진짜 음성/guardrail sidecar가 부족합니다. 추가하면 좋습니다:
      - account_activity_variance_stable_controls.csv: weighted variance <= threshold
      - account_activity_variance_near_threshold_controls.csv: threshold 바로 아래
      - account_activity_variance_exclusions.csv: blank/null gl, prior 없음 정책상 제외할 별도 케이스
        가 있다면 분리

  D02

  - 구성도 좋습니다.
      - monthly_pattern_shift_confirmed_anomalies.csv: 346 groups, 전부 true positive
      - monthly_pattern_shift_review_population.csv: 497 groups, 전부 expected_d02_flag=True
      - monthly_pattern_shift_normal_controls.csv: 194 groups
          - 151건은 expected_d02_flag=True지만 정상 계절성/배치/프로젝트성 맥락
          - 43건은 expected_d02_flag=False, skip_reason=small_top_month_delta
      - monthly_pattern_shift_exclusions.csv: 2,059 rows/groups, D02 제외 사유가 잘 분리됨
  - D02는 D01보다 더 낫습니다. 정상 control 안에 raw positive 정상 맥락과 raw negative/guardrail 케이
    스가 둘 다 있습니다. exclusions도 small_top_month_delta, insufficient_current_docs,
    blank_gl_account, no_prior_account_group_use_d01 등으로 잘 나뉩니다.

  수정 필요:

  - monthly_pattern_shift_confirmed_anomalies는 이름상 행 단위 anomaly처럼 보입니다.
    monthly_pattern_shift_truth 또는 manifest에서 macro_group_truth로 명시하는 게 좋습니다.
  - normal_controls 안의 151 positive / 43 negative가 섞여 있으므로 평가 시 분리 태그가 필요합니다:
      - normal_raw_positive_control
      - guardrail_negative_control
      - excluded_from_d02

  종합 판단

  - D01/D02 SIDECAR는 현재 기준에서 대체로 괜찮습니다.
  - 큰 문제는 데이터 자체보다 명명과 manifest 부재입니다.
  - 특히 D01의 normal_controls를 “detector가 안 잡아야 하는 세트”로 해석하면 안 됩니다. D01은 분석적
    검토 룰이라 정상 사업 변화도 raw hit가 되는 게 맞습니다.






  - L1-02 미탐 2건은 실제 전표에 fiscal_period 값이 있어 룰 실패가 아니라 truth 불일치로 판단
