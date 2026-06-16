# HITL Feedback Loop Hardening - Task Checklist

## Progress Summary

0 / 15 tasks complete (0%)

## Phase 1: Schema And Storage

- [ ] `feedback_events` 테이블 DDL을 추가한다.
  - File: `src/db/schema.py`
  - Details: document/rule/export feedback를 모두 담을 최소 컬럼을 정의한다.
  - Acceptance: schema 초기화 후 `feedback_events`가 생성된다.
  - Size: M

- [ ] feedback event query preset을 추가한다.
  - File: `src/db/queries.py`
  - Details: insert, batch/document lookup, recent events 조회를 만든다.
  - Acceptance: execute_write/execute_preset로 CRUD가 가능하다.
  - Size: M

- [ ] 공통 feedback store 헬퍼를 추가한다.
  - File: `src/hitl/feedback_store.py`
  - Details: event write/read API를 제공한다.
  - Acceptance: UI와 서비스 코드가 raw SQL 대신 store를 사용 가능하다.
  - Size: M

## Phase 2: Whitelist Integration

- [ ] whitelist add 시 normalized feedback event를 기록한다.
  - File: `dashboard/components/explorer_whitelist.py`
  - Details: `false_positive` decision과 reason, rule list를 함께 남긴다.
  - Acceptance: whitelist 저장 후 event 조회에 같은 문서가 보인다.
  - Size: M

- [ ] whitelist remove 시 취소 이벤트를 기록한다.
  - File: `dashboard/components/explorer_whitelist.py`
  - Details: 삭제 자체를 지우지 말고 reversal/cancel event로 남긴다.
  - Acceptance: add/remove 모두 이력으로 남는다.
  - Size: M

- [ ] 상세 패널에서 기존 feedback 이력을 보여준다.
  - File: `dashboard/components/explorer_detail.py`
  - Details: 최근 이벤트 3건 중심으로 표시한다.
  - Acceptance: 문서 상세에서 예외 처리 이력을 볼 수 있다.
  - Size: M

## Phase 3: Rule Feedback Integration

- [ ] 승인된 rule suggestion을 feedback event로 기록한다.
  - File: `src/llm/rule_feedback.py`
  - Details: category, proposed value, rationale, confidence를 payload에 보관한다.
  - Acceptance: apply 후 event store에 승인 이벤트가 남는다.
  - Size: M

- [ ] 거부된 rule suggestion도 feedback event로 기록한다.
  - File: `src/llm/rule_feedback.py`
  - Details: JSONL 로그와 함께 DB event도 남긴다.
  - Acceptance: reject 후 event store에 거부 이벤트가 남는다.
  - Size: M

- [ ] 회사/engagement 단위 feedback 조회 helper를 추가한다.
  - File: `src/company/repository.py`, `src/hitl/feedback_store.py`
  - Details: 이후 리포트/학습이 재사용할 수 있게 read API를 둔다.
  - Acceptance: 상위 호출부가 직접 SQL 없이 feedback를 읽는다.
  - Size: M

## Phase 4: Label Asset Builder

- [ ] feedback domain model을 추가한다.
  - File: `src/hitl/models.py`
  - Details: event, document label, rule feedback summary dataclass/model을 정의한다.
  - Acceptance: 타입이 고정된다.
  - Size: M

- [ ] document feedback label builder를 구현한다.
  - File: `src/hitl/label_builder.py`
  - Details: event stream을 false_positive/confirmed_issue/needs_followup 라벨로 변환한다.
  - Acceptance: document별 최신 decision을 계산할 수 있다.
  - Size: M

- [ ] builder 결과를 직렬화/조회 가능하게 만든다.
  - File: `src/hitl/feedback_store.py`
  - Details: DataFrame 또는 모델 리스트로 반환한다.
  - Acceptance: pipeline/metrics에서 바로 읽을 수 있다.
  - Size: S

## Phase 5: Consumption

- [ ] operational performance report가 feedback label을 반영하게 한다.
  - File: `src/metrics/operational_evaluator.py`, `src/metrics/models.py`
  - Details: whitelist_removed_docs 외 false_positive 관련 수치를 넣을 수 있게 확장한다.
  - Acceptance: phase2 report에 HITL 관련 수치가 나타난다.
  - Size: M

- [ ] findings/detail 화면에 feedback 상태를 연결한다.
  - File: `dashboard/tab_findings.py`, `dashboard/components/explorer_detail.py`
  - Details: 이미 처리된 문서, 보류 문서, 규칙 피드백 흔적을 보여준다.
  - Acceptance: UI에서 문서별 사람 판단 흔적이 보인다.
  - Size: M

- [ ] supervised label strategy와 연결 가능한 입력 포인트를 만든다.
  - File: `src/preprocessing/label_strategy.py`, `src/pipeline.py`
  - Details: 즉시 학습에 쓰지 않더라도 hook과 TODO 경계를 명확히 둔다.
  - Acceptance: HITL label asset read 경로가 코드상 존재한다.
  - Size: L

## Phase 6: Verification

- [ ] feedback store/schema 테스트를 추가한다.
  - File: `tests/modules/test_db/*`, `tests/modules/test_hitl/*`
  - Details: insert/read/reversal semantics를 검증한다.
  - Acceptance: event CRUD 테스트가 통과한다.
  - Size: M

- [ ] whitelist/rule feedback 통합 테스트를 추가한다.
  - File: `tests/modules/test_dashboard/*`, `tests/modules/test_llm/*`
  - Details: UI 액션 이후 event store 기록을 검증한다.
  - Acceptance: 두 흐름 모두 normalized event를 남긴다.
  - Size: M

- [ ] 문서 상태를 업데이트한다.
  - File: `docs/archive/completed/개선사항.md`
  - Details: 구현 범위와 남은 후속 범위를 실제 기준으로 갱신한다.
  - Acceptance: 계획 문서와 본문 상태가 맞는다.
  - Size: S

## Deployment Checklist

- [ ] `feedback_events` schema/query/store가 추가되었다.
- [ ] whitelist add/remove가 event store를 함께 기록한다.
- [ ] rule feedback approve/reject가 event store를 함께 기록한다.
- [ ] document feedback label builder가 존재한다.
- [ ] phase2/findings에서 최소 1개 이상 HITL 수치를 읽는다.
- [ ] 관련 테스트와 import smoke가 통과한다.
