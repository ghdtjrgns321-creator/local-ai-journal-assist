
## 전체적으로 과탐 미탐 테스트 -> 임시스크립트로 돌릴때마다 결과 달라짐 실제 프로젝트에서 돌아가는 걸로 돌리라고 명시해야됨
미탐 = 0 이면 우선 FITTING 의심
L1
L2
L3
L4
D

  2022
  룰      룰 이름                정답     탐지    정탐   과탐      미탐
  -----  --------------------  -------  ------  -----  -----  --------
  L1-01✅  차대변 불균형              95      95     95      0         0
  L1-02✅  필수 필드 누락            24      24     24      0         0
  L1-03✅  무효 계정                 13      13     13      0         0
  L1-04✅  승인한도 초과             12      12     12      0         0
  L1-05✅  자기승인                  80      73     73      0         7
  L1-06  직무분리 위반         64,183       9      9      0    64,174
  L1-07  승인 생략             22,457       3      3      0    22,454
  L1-08✅  회계기간 불일치          230     230    230      0         0
  L1-09  승인일자 누락         22,463       7      7      0    22,456

  2023
  룰      룰 이름                정답     탐지    정탐   과탐      미탐
  -----  --------------------  -------  ------  -----  -----  --------
  L1-01  차대변 불균형              81      81     81      0         0
  L1-02  필수 필드 누락            26      26     26      0         0
  L1-03  무효 계정                  8       8      8      0         0
  L1-04  승인한도 초과             20      20     20      0         0
  L1-05  자기승인                  69      58     58      0        11
  L1-06  직무분리 위반         63,510      13     13      0    63,497
  L1-07  승인 생략             22,003       2      2      0    22,001
  L1-08  회계기간 불일치          244     244    244      0         0
  L1-09  승인일자 누락         22,006       8      8      0    21,998

  2024
  룰      룰 이름                정답     탐지    정탐   과탐      미탐
  -----  --------------------  -------  ------  -----  -----  --------
  L1-01  차대변 불균형             127     127    127      0         0
  L1-02  필수 필드 누락            36      36     36      0         0
  L1-03  무효 계정                 11      11     11      0         0
  L1-04  승인한도 초과             24      24     24      0         0
  L1-05  자기승인                  95      86     86      0         9
  L1-06  직무분리 위반         64,394      17     17      0    64,377
  L1-07  승인 생략             22,489      14     14      0    22,475
  L1-08  회계기간 불일치          257     257    257      0         0
  L1-09  승인일자 누락         22,492      11     11      0    22,481

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


• 그 의문이 맞습니다. 결론은 룰별 “상/중/하”, “위험 높음/낮음” 같은 표현값을 그대로 합산하면 안 됩니
  다. PHASE1 통합 점수에는 전부 먼저 공통 숫자 스케일로 바꿔서 넣어야 합니다.

  지금 가져야 하는 원칙은 이겁니다.

  룰별 출력 표현
  상/중/하, High/Medium/Low, 검토 필요, 위험 높음
  ↓
  공통 내부값으로 정규화
  signal_strength: 0.0 ~ 1.0
  ↓
  severity와 evidence type 가중치 반영
  ↓
  case_priority 합산

  예를 들면:

  | 룰별 표현 | 내부 변환값 |
  |---|---:|
  | High / 상 / 위험 높음 | 1.0 |
  | Medium / 중 / 검토 필요 높음 | 0.6 |
  | Low / 하 / 참고 | 0.3 |
  | 단순 flag True | 1.0 |
  | flag False | 0.0 |

  그 다음 룰 심각도를 곱합니다.

  normalized_score =
    signal_strength * (severity / 5) * evidence_strength_factor * scoring_role_factor

  예:

  L1-05 자기승인
  - 표현: High
  - severity: 3
  - signal_strength: 1.0
  → 1.0 * 3/5 = 0.60

  L3-08 설명 부족
  - 표현: Low
  - severity: 1
  - signal_strength: 0.3
  → 0.3 * 1/5 = 0.06

  이러면 “위험 높음”이라고 나온 약한 룰과, “검토 필요”라고 나온 강한 룰이 같은 무게로 섞이는 문제를 막
  을 수 있습니다.

  PHASE1 통합에서는 순서가 이렇게 되어야 합니다.

  1. 각 룰 결과를 공통 signal_strength로 변환
  2. severity를 곱해서 rule_score 계산
  3. evidence_type별로 묶음
  4. 같은 evidence_type 안에서는 cap 적용
  5. 서로 다른 evidence_type이 결합되면 case_priority 상승
  6. Top-side / Batch / Weak evidence 보정 적용

  핵심은 이겁니다.

  룰별 라벨은 사용자 표현일 뿐,
  합산에는 label이 아니라 정규화된 score만 쓴다.

  그래서 내부적으로는 이런 매핑 테이블이 필요합니다.

  SIGNAL_STRENGTH_MAP = {
      "critical": 1.0,
      "high": 1.0,
      "상": 1.0,
      "위험높음": 1.0,
      "medium": 0.6,
      "중": 0.6,
      "review_needed": 0.6,
      "검토필요": 0.6,
      "low": 0.3,
      "하": 0.3,
      "info": 0.2,
      "참고": 0.2,
  }

  그리고 최종적으로는 룰별 원문 표현을 이렇게 분리해야 합니다.

  display_label: "위험 높음"
  signal_strength: 1.0
  severity: 3
  normalized_score: 0.6

  즉 감사인에게 보여주는 말과, 점수 계산에 쓰는 숫자를 분리해야 합니다.

  구현 반영: 2026-04-27 기준 `src/detection/rule_scoring.py`에 룰별 라벨/표현값 표준화 layer를 추가했고,
  `phase1_case_builder`는 `severity / 5` 단순 합산 대신 `normalized_score`를 evidence type별로 합산합니다.


  • 핵심은 룰별 결과를 그대로 보여주지 말고, 룰별 결과를 “증거 조각”으로 흡수한 뒤 감사인이 읽을 수 있는
  케이스 언어로 번역하는 것입니다.

  지금처럼 룰마다 표현이 다르면 안 됩니다.

  L1-05: High
  L3-08: 검토 필요
  L4-03: 이상 고액
  L2-03: 중복 가능성

  이걸 그대로 보여주면 감사인은 “그래서 뭘 먼저 봐야 하지?”가 됩니다.

## PHASE1이후-2
