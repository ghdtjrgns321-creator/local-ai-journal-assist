# Local AI Audit Assistant 설명

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> 최신 설명 기준: Phase 1은 "정답을 잡는 모델"이 아니라 규칙 위반·정책 위반·이상 징후 후보를 전체 모집단에서 먼저 올리는 설명 가능한 1차 필터다. Phase 1 결과는 곧바로 부정 또는 오류 결론이 아니며, 이후 중요성·증거 강도·업무상 정상 예외·다른 룰과의 조합을 기준으로 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보로 2차 분류한다.

> **포트폴리오 포지셔닝 기준 (2026-05-19)**: 이 프로젝트는 실제 부정을 확정하는 fraud detector가 아니라, 전수 원장/지급 데이터에서 감사인이 검토해야 할 후보를 설명 가능한 review queue로 정렬하고 근거와 다음 절차를 제공하는 로컬 감사 분석 보조 도구다. DataSynth는 메인 데모와 개발 검증용, OpenDataPhilly/Tritscher는 portability와 외부 shadow 검증용으로 구분한다.

> 작성 기준: 2026-04-16  
> 이 문서는 현재 프로젝트를 설명할 때 무엇을 메인으로 말해야 하는지 정리한 기준 문서다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

---

## 1. 한 줄 설명

> 이 프로젝트는 회계 전표 데이터를 대상으로, **Phase 1 룰 기반 전수 필터**로 설명 가능한 규칙 위반·이상 징후 후보를 먼저 올리고, **Phase 2 비지도 탐지**로 룰 밖 패턴과 우선순위를 보완한 뒤, 감사인이 검토할 후보를 **review queue**로 정렬하는 로컬 감사 분석 시스템이다.

핵심은 "할 수 있는 탐지기 나열"이 아니라 "지금 가장 잘 설명되고 가장 현실적으로 운영 가능한 탐지 축"을 분명히 두는 것이다.

이 문서에서 말하는 "탐지"는 부정 확정이 아니라 감사인이 확인해야 할 후보 선별을 뜻한다.

---

## 2. 핵심 탐지 축

### 2.1 Core: Phase 1 룰 기반 탐지

- 감사 룰로 설명 가능한 이상을 먼저 식별한다.
- 무결성, 부정, 이상징후 레이어를 통해 감사인이 바로 이유를 이해할 수 있다.
- 면접이나 제품 설명에서도 가장 먼저 말해야 하는 축이다.

### 2.2 Core: Phase 2 비지도 탐지

- 룰로 미리 정의하지 못한 패턴을 보완한다.
- 정상 거래 분포를 학습한 뒤 이탈 거래를 찾는다.
- 현재 프로젝트에서 Phase 2의 메인 확장 축은 `VAE + Isolation Forest` 계열이다.

### 2.3 왜 이 두 축이 메인인가

- 룰 기반은 설명 가능성이 높다.
- 비지도 탐지는 라벨이 부족한 감사 환경에 맞다.
- 두 축을 합치면 "설명 가능한 탐지"와 "룰 밖 패턴 보완"을 동시에 가져갈 수 있다.

---

## 3. 메인이 아닌 것들

### 3.1 Optional

- 지도학습 분류기
- 반복 수행과 HITL 라벨 축적 이후 선택적으로 붙일 수 있는 모델

### 3.2 Experimental

- 스태킹 메타러너
- 고급 딥러닝 분류기
- 일부 구현은 있어도 아직 기본 경로로 소개할 수준은 아닌 모델

### 3.3 Future / Dormant

- NLP 적요 해석
- 그래프 기반 관계형 탐지
- local-only NLP 또는 local model inference

여기서 중요한 점은, 이 기능들이 "없다"가 아니라 "지금 메인 가치 제안이 아니다"라는 것이다.

지도학습 XGBoost, FT-Transformer, BiLSTM, stacking은 신뢰 가능한 실데이터/golden label이 생기기 전까지 dormant로 둔다. DataSynth 성능만으로 active에 넣으면 생성기 shortcut을 학습하는 fitting 위험이 크다.

---

## 4. Local Evidence Brief

이 프로젝트는 외부 LLM/API 없이 로컬에서 원장 데이터를 분석하는 감사 검토 지원 도구다.

- PHASE1: review queue와 rule-level 근거를 만든다.
- PHASE2: family-specific lane과 보조 anomaly signal을 만든다.
- Local Evidence Brief: 이미 계산된 rule evidence, review_focus, recommended_audit_actions, PHASE2 family signal, case metadata에서 deterministic template으로 구성한다.
- PHASE3 LLM Narrator, LLM reranking, AI review memo, Text-to-SQL, 룰 피드백은 active product에서 제거되었다.

단일 출처: [LOCAL_FIRST_EVIDENCE_POLICY.md](../spec/LOCAL_FIRST_EVIDENCE_POLICY.md), deprecated spec [PHASE3_REVIEW_NARRATOR_SPEC.md](../archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md).

---

## 5. 사용자 설명 순서

사용자나 면접관에게는 아래 순서로 설명하는 것이 가장 명확하다.

1. 데이터를 업로드하고 정리한다.
2. 감사 룰로 설명 가능한 이상을 먼저 찾는다.
3. 비지도 탐지로 룰 밖 패턴을 보완한다.
4. 결과를 부정 확정이 아니라 review queue 우선순위로 대시보드에서 검토한다.
5. 선택한 case의 근거와 다음 확인 절차는 로컬 evidence 기반 요약으로 확인한다.

---

## 6. UI 원칙

Streamlit UI도 같은 구조를 따라야 한다.

- 첫 화면 메시지는 `룰 기반 -> 비지도 보완` 순서를 보여준다.
- 메인 탭은 핵심 탐지 결과를 먼저 보여준다.
- Phase 2 탭은 `비지도`를 메인 확장 축으로 설명한다.
- 지도학습과 스태킹은 기본 탭 구조의 중심에 두지 않는다.
- 외부 LLM/API 기능은 active UI capability로 노출하지 않는다.

---

## 7. 면접용 짧은 버전

> 저는 이 프로젝트를 "룰 기반 감사 탐지를 기본으로 두고, 비지도 이상 탐지로 룰 밖 패턴을 보완해 감사인이 볼 후보를 설명 가능한 review queue로 정렬하는 로컬 감사 분석 시스템"으로 설명합니다.  
> 외부 LLM/API 없이 로컬에서 원장 데이터를 분석하며, 실제 부정을 확정하는 모델이 아니라 감사인이 검토할 근거와 우선순위를 구조화하는 도구입니다.
