# HITL Feedback Loop Hardening - Strategic Plan

## Executive Summary

`## 3.8 HITL 피드백 루프 강화`의 목표는 현재 흩어져 있는 사람 판단 데이터를 하나의 재사용 가능한 피드백 자산으로 묶는 것이다. 지금 코드베이스에는 `whitelist`, `audit_log`, `rule_feedback_log.jsonl`, 회사별 `audit_rules.yaml` override가 각각 존재하지만, 서로 다른 저장 경로와 의미 체계를 사용해서 "감사자가 무엇을 승인했고, 무엇을 오탐으로 봤고, 그것이 이후 탐지/학습/리포트에 어떻게 반영되는가"가 한 번에 연결되지 않는다.

이번 계획은 배치 단위 예외 처리와 회사 단위 규칙 승인 이력을 `feedback event -> normalized label asset -> downstream consumption` 구조로 정리하는 데 초점을 둔다. 1차 범위는 모델 재학습 자동화가 아니라, 피드백을 잃지 않고 추적 가능하게 저장하고, Phase 1/2 결과·성능 리포트·향후 supervised 학습이 같은 자산을 읽을 수 있게 만드는 것이다.

## Current State

- `dashboard/components/explorer_whitelist.py`는 선택된 `document_id`에 대해 `whitelist` 테이블을 직접 INSERT/DELETE하고, 동시에 메모리의 `PipelineResult.data`를 즉시 수정한다.
- `src/db/audit_log.py`는 `whitelist_add`, `whitelist_remove` 같은 감사 로그를 남기지만, 이 로그는 분석용 피드백 자산이라기보다 증적 로그에 가깝다.
- `dashboard/components/rule_feedback_panel.py`와 `src/llm/rule_feedback.py`는 LLM 제안의 승인/거부를 `rule_feedback_log.jsonl`에 append-only로 기록하고, 승인된 경우 회사별 `audit_rules.yaml` override까지 반영한다.
- `src/company/repository.py`는 회사별 YAML 리소스 저장에는 강하지만, 정규화된 HITL 피드백 조회 API는 제공하지 않는다.
- `src/metrics/operational_evaluator.py`는 `whitelist_removed_docs` 정도만 성능 지표에 반영하며, 화이트리스트가 어떤 규칙/어떤 오탐 클래스였는지는 잃는다.
- `src/preprocessing/label_strategy.py` 및 supervised detector 쪽에는 사람 검토 확정 라벨을 읽는 공통 store가 아직 없다.

즉, 현재의 HITL은 "예외 처리 UI", "규칙 제안 승인 UI", "감사 로그"는 존재하지만, 완전한 피드백 루프는 아니다.

## Proposed Solution

HITL 피드백 루프를 아래 3계층으로 표준화한다.

1. Feedback Event Layer
   - 사용자의 모든 판단 이벤트를 정규화된 공통 스키마로 기록한다.
   - 예: `false_positive`, `confirmed_issue`, `rule_suggestion_approved`, `rule_suggestion_rejected`, `export_feedback`
   - 기존 `audit_log`는 증적 로그로 유지하되, 학습/분석용 `feedback_events` 저장 경로를 별도로 둔다.

2. Feedback Asset Layer
   - 이벤트를 그대로 쓰지 않고, 문서/규칙/회사 수준으로 재집계 가능한 파생 자산을 만든다.
   - 예:
     - 문서 라벨 자산: `document_feedback_labels`
     - 규칙 운영 피드백 자산: `rule_feedback_summary`
     - 회사별 학습 후보 자산: `feedback_labels.jsonl` 또는 engagement DB 테이블
   - 이 계층이 향후 supervised 학습, 성능 평가, 운영 리포트의 공통 입력이 된다.

3. Consumption Layer
   - 탐지 UI: 이미 처리된 문서인지, 어떤 사유로 처리되었는지 표시
   - 성능 평가: whitelist count 수준을 넘어 false positive / confirmed issue 반영
   - supervised labeling: ground truth가 없을 때도 HITL 확정 라벨을 안전하게 읽을 수 있게 함
   - rule feedback: 단순 YAML 변경이 아니라 "승인 근거가 있는 운영 피드백"으로 연결

## Target Architecture

### A. New normalized feedback schema

- `feedback_events`
  - `id`
  - `company_id`
  - `engagement_id`
  - `batch_id`
  - `document_id`
  - `track_name`
  - `rule_code`
  - `event_type`
  - `decision`
  - `reason`
  - `payload_json`
  - `created_by`
  - `created_at`

### B. Derived feedback label model

- document-level label semantics
  - `false_positive`
  - `confirmed_issue`
  - `needs_followup`
  - `rule_accepted_as_policy`
  - `rule_rejected_as_noise`

- builder/service candidates
  - `src/hitl/feedback_store.py`
  - `src/hitl/label_builder.py`

### C. Existing flows mapped into normalized events

- Whitelist save/remove
  - whitelist row는 그대로 유지
  - 동시에 `feedback_events`에 `decision=false_positive` 기록

- Rule feedback approve/reject
  - JSONL 로그는 하위 호환으로 유지 가능
  - 동시에 `feedback_events`에 `decision=rule_approved` / `rule_rejected` 기록

- Export feedback
  - 1차에서는 최소 범위로 export 실행 메타와 선택된 필터/포맷을 연결
  - 2차 확장으로 감사자 주석/후속조치 메모까지 고려

## Implementation Phases

### Phase 1: Schema And Storage Contract (0.5-1 day)
**Goal**: 피드백 이벤트를 저장할 공통 스키마와 접근 API를 확정한다.

- [ ] `feedback_events` DDL 설계 및 쿼리 추가
  - File: `src/db/schema.py`, `src/db/queries.py`
  - Size: M
- [ ] 공통 write/read 헬퍼 추가
  - File: `src/hitl/feedback_store.py`
  - Size: M
- [ ] 기존 `audit_log`와 역할 경계 문서화
  - File: `dev/active/hitl-feedback-loop-hardening/hitl-feedback-loop-hardening-context.md`
  - Size: S

### Phase 2: Whitelist Flow Normalization (0.5-1 day)
**Goal**: 예외 처리 UI가 단순 whitelist CRUD를 넘어서 정규화된 피드백 이벤트를 남기게 한다.

- [ ] whitelist add/remove 시 `feedback_events` 동시 기록
  - File: `dashboard/components/explorer_whitelist.py`
  - Size: M
- [ ] 문서별 기존 피드백 조회 UI 추가
  - File: `dashboard/components/explorer_whitelist.py`, `dashboard/components/explorer_detail.py`
  - Size: M
- [ ] 메모리 동기화와 DB truth의 의미 차이 정리
  - File: `dashboard/components/explorer_whitelist.py`
  - Size: S

### Phase 3: Rule Feedback Event Integration (0.5-1 day)
**Goal**: rule feedback 승인/거절을 YAML 변경 로그가 아니라 통합 피드백 이벤트로 연결한다.

- [ ] `RuleFeedbackEngine.apply()` / `log_rejections()`에서 normalized event 기록
  - File: `src/llm/rule_feedback.py`
  - Size: M
- [ ] 회사별 feedback event 조회 helper 추가
  - File: `src/company/repository.py`, `src/hitl/feedback_store.py`
  - Size: M
- [ ] `rule_feedback_log.jsonl`과 `feedback_events`의 중복/보완 관계 정리
  - File: `dev/active/hitl-feedback-loop-hardening/hitl-feedback-loop-hardening-context.md`
  - Size: S

### Phase 4: Feedback Label Asset Builder (1 day)
**Goal**: 이벤트 원장을 직접 쓰지 않고 재사용 가능한 라벨 자산으로 변환한다.

- [ ] 문서 단위 feedback label builder 추가
  - File: `src/hitl/label_builder.py`
  - Size: M
- [ ] false positive / confirmed issue / policy feedback 규칙 정의
  - File: `src/hitl/models.py`, `src/hitl/label_builder.py`
  - Size: M
- [ ] 향후 supervised gating에서 읽을 수 있는 형태로 직렬화 지원
  - File: `src/hitl/feedback_store.py`
  - Size: M

### Phase 5: Downstream Consumption (1 day)
**Goal**: HITL 자산이 실제 결과/리포트/학습 경로에서 쓰이게 한다.

- [ ] 성능 평가에 whitelist count 이상 정보 반영
  - File: `src/metrics/operational_evaluator.py`, `src/metrics/models.py`, `dashboard/tab_phase2.py`
  - Size: M
- [ ] supervised label strategy가 HITL 확정 라벨을 읽도록 확장 검토
  - File: `src/preprocessing/label_strategy.py`, `src/pipeline.py`
  - Size: L
- [ ] Findings/Detail 화면에 피드백 이력 표시
  - File: `dashboard/tab_findings.py`, `dashboard/components/explorer_detail.py`
  - Size: M

### Phase 6: Verification And Docs (0.5 day)
**Goal**: 새 HITL 루프를 테스트와 문서로 고정한다.

- [ ] DB schema/store 테스트 추가
  - File: `tests/modules/test_db/*`, `tests/modules/test_hitl/*`
  - Size: M
- [ ] whitelist/rule feedback integration test 추가
  - File: `tests/modules/test_dashboard/*`, `tests/modules/test_llm/*`
  - Size: M
- [ ] `docs/archive/completed/개선사항.md`와 운영 문서 업데이트
  - File: `docs/archive/completed/개선사항.md`
  - Size: S

## Risk Assessment

- **High Risk**: whitelist와 feedback event를 이중 기록할 때 의미가 어긋날 수 있다.
  - Mitigation: whitelist는 "현재 배치 억제 상태", feedback_events는 "판단 이력"으로 역할을 분리한다.

- **High Risk**: 사람 판정을 supervised 학습에 곧바로 쓰면 라벨 품질이 섞일 수 있다.
  - Mitigation: 1차에서는 저장과 조회만 표준화하고, 학습 반영은 `decision`과 `confidence/source` 규칙이 정해진 자산만 읽게 한다.

- **Medium Risk**: `rule_feedback_log.jsonl`와 DB 이벤트가 중복 저장처럼 보일 수 있다.
  - Mitigation: JSONL은 append-only 감사 로그, DB는 앱 조회/집계용 인덱스드 저장소로 명확히 분리한다.

- **Medium Risk**: 문서 상세 UI에 이력을 많이 붙이면 과밀해질 수 있다.
  - Mitigation: 최근 이벤트 3건 + 전체 보기 expander 구조로 제한한다.

## Success Metrics

- whitelist, rule feedback 승인/거절이 모두 같은 피드백 이벤트 스키마로 기록된다.
- 문서 단위로 "이 문서가 왜 제외/확정/보류됐는지" 이력이 조회된다.
- 성능 리포트가 `whitelist_removed_docs` 이상 정보를 보여준다.
- 향후 supervised 학습이 재사용 가능한 피드백 라벨 자산 입력을 갖는다.
- 테스트:
  - feedback_events schema/store 테스트 통과
  - whitelist integration 테스트 통과
  - rule feedback integration 테스트 통과

## Dependencies

- Existing code
  - `dashboard/components/explorer_whitelist.py`
  - `dashboard/components/rule_feedback_panel.py`
  - `dashboard/components/explorer_detail.py`
  - `dashboard/tab_findings.py`
  - `src/db/schema.py`
  - `src/db/queries.py`
  - `src/db/audit_log.py`
  - `src/company/repository.py`
  - `src/llm/rule_feedback.py`
  - `src/metrics/operational_evaluator.py`
  - `src/preprocessing/label_strategy.py`

- New modules
  - `src/hitl/feedback_store.py`
  - `src/hitl/models.py`
  - `src/hitl/label_builder.py`
