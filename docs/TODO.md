


## datasynth 오류, 정답지 없는거 찾기

## 전체적으로 과탐 미탐 테스트

## 시간테스트 병목 검사


# RULES 재정비 끝나고
## PHASE1이후-1


• 그 의문이 맞습니다. 결론은 룰별 “상/중/하”, “위험 높음/낮음” 같은 표현값을 그대로 합산하면 안 됩니
  다. PHASE1 통합 점수에는 전부 먼저 공통 숫자 스케일로 바꿔서 넣어야 합니다.

  지금 가져야 하는 원칙은 이겁니다.

  룰별 출력 표현
  상/중/하, High/Medium/Low, 검토 필요, 위험 높음
  ↓
  공통 내부값으로 정규화
  rule_signal_strength: 0.0 ~ 1.0
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

  normalized_rule_score =
    signal_strength * (severity / 5)

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
  rule_score: 0.6

  즉 감사인에게 보여주는 말과, 점수 계산에 쓰는 숫자를 분리해야 합니다.

  지금 구현은 기본적으로 hit.score와 severity를 쓰고 있어서 방향은 맞지만, 룰별 라벨/표현값을 표준화하
  는 layer는 아직 명시적으로 충분하지 않습니다. 이걸 추가해야 진짜로 일관된 PHASE1 통합 점수가 됩니다


  • 핵심은 룰별 결과를 그대로 보여주지 말고, 룰별 결과를 “증거 조각”으로 흡수한 뒤 감사인이 읽을 수 있는
  케이스 언어로 번역하는 것입니다.

  지금처럼 룰마다 표현이 다르면 안 됩니다.

  L1-05: High
  L3-08: 검토 필요
  L4-03: 이상 고액
  L2-03: 중복 가능성

  이걸 그대로 보여주면 감사인은 “그래서 뭘 먼저 봐야 하지?”가 됩니다.

## PHASE1이후-2


