

# RULES 재정비 끝나고
## PHASE1이후-1


## PHASE1이후-2






 A 세트에서 물어볼 것:

  룰 계약을 지켰나?
  정합성 오류를 빠짐없이 잡았나?
  sidecar가 점수로 오염되지 않았나?
  룰별 expected truth와 actual hit이 맞나?

  B 세트에서 물어볼 것:

  정상 데이터 속에 소량 조작이 섞였을 때,
  PHASE1 case queue 상단에 실제 조작이 얼마나 올라오나?
  감사인이 Top 10/50/100 case를 보면 몇 개를 잡나?
  몇 document를 봐야 조작 몇 개가 나오나?
  어떤 조작 유형이 PHASE1에서 안 보이나?

    그래서 평가 보고서도 두 개로 나눠야 합니다.

  1. PHASE1 Contract Evaluation
     - 데이터 정합성
     - 룰 계약
     - sidecar 격리
     - expected truth 통과 여부

  2. PHASE1 Fraud Realism Evaluation
     - 정상 데이터 + 소량 조작
     - case ranking
     - Top N capture
     - 검토량 대비 조작 포착률
     - 미탐 유형
