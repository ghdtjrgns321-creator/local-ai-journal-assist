# 성능 평가 지표

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

## 구분

- `phase1_rule_truth`: PHASE1 룰이 잡아야 하는 규칙 위반 또는 리뷰 후보 모집단. 확정 부정 라벨이 아니라 PHASE1 계약 테스트용 기준이다.
- `audit_issue_truth`: DataSynth 주입 라벨이나 사람이 확정한 감사 이슈. 최종 부정·오류 검증에 가깝지만, 모든 PHASE1 룰의 정답 분모로 쓰면 안 된다.
- `operational_proxy`: 정답이 없을 때 보는 운영 지표. whitelist, review queue 규모, high-risk 비율, 정상 예외 비율, macro finding coverage 같은 근사 지표다.

## PHASE1 해석 원칙

PHASE1은 정답 라벨을 맞히는 최종 분류기가 아니라 1차 전수 스크리닝 계층이다. 따라서 PHASE1 raw hit에는 정상 예외, 업무상 타당한 거래, 단독으로 약한 신호가 포함될 수 있다.

PHASE1 평가는 먼저 규칙 위반 후보를 누락 없이 올렸는지 본다. 그 다음 materiality, evidence strength, case priority, 고객사 예외 정책, 다른 룰과의 조합 여부로 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 2차 분류한다.

## 지표

- `precision`: 탐지한 항목 중 기준 truth에 해당하는 비율. 어떤 truth를 분모로 썼는지 반드시 함께 표기한다.
- `recall`: 기준 truth 항목 중 탐지한 비율. PHASE1에서는 confirmed audit issue recall과 review population coverage를 구분한다.
- `f1`: precision과 recall의 조화 평균. PHASE1 운영 가치 판단에는 단독 사용하지 않는다.
- `candidate_coverage`: PHASE1이 리뷰 후보 모집단을 얼마나 포착했는지 보는 지표.
- `high_risk_ratio`: 전체 문서 또는 case 중 `priority_band=high` 또는 `risk_level=High` 비율.
- `exception_rate`: 감사인 또는 정책으로 정상 예외 처리된 후보 비율.
- `whitelist_removed_docs`: whitelist나 예외 정책으로 제외된 문서 수.

## 주의사항

- DataSynth `is_fraud` / `is_anomaly`만 PHASE1 정답으로 쓰지 않는다.
- broad review rule, Benford, D01/D02, 사용자 행동·계정군 단위 룰은 문서 단위 precision/recall만으로 평가하지 않는다.
- whitelist는 사람이 false positive라고 본 사례의 근사치이지 precision의 정답 대체물이 아니다.
- historical batch는 레이블 또는 설정이 불완전할 수 있으므로 `metric_confidence=partial`로 표시할 수 있다.
