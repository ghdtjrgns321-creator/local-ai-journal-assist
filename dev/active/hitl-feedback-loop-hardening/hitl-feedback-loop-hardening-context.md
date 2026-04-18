# HITL Feedback Loop Hardening - Context & Decisions

## Status

- Phase: Planning complete
- Progress: 0 / 15 tasks complete
- Last Updated: 2026-04-16

## Key Files

**Current HITL flows**
- `dashboard/components/explorer_whitelist.py` - 배치 단위 예외 처리 UI
- `dashboard/components/rule_feedback_panel.py` - LLM 규칙 제안 승인/거절 UI
- `src/llm/rule_feedback.py` - 규칙 제안 생성/적용/거부 로그
- `src/db/audit_log.py` - 감사 증적용 이벤트 기록
- `src/db/schema.py`
- `src/db/queries.py`
- `src/company/repository.py`

**Current downstream consumers**
- `dashboard/tab_findings.py`
- `dashboard/components/explorer_detail.py`
- `src/metrics/operational_evaluator.py`
- `src/preprocessing/label_strategy.py`
- `src/pipeline.py`

**Planned new modules**
- `src/hitl/models.py`
- `src/hitl/feedback_store.py`
- `src/hitl/label_builder.py`

## Current Findings

1. whitelist는 현재 배치 억제 수단이지만, 오탐 판정 이력 store로는 불완전하다.
   - `whitelist`는 `batch_id + document_id + rule_code` 기준 저장이라 같은 문서가 다른 배치에서 다시 뜨면 직접 연결되지 않는다.
   - 추가 reason은 저장하지만, 구조화된 decision type이나 confidence는 없다.

2. rule feedback는 DB가 아니라 회사 디렉터리 JSONL 중심이라 앱 조회성이 약하다.
   - `rule_feedback_log.jsonl`은 append-only 감사 로그로는 좋지만, UI/리포트/학습에서 직접 조회하기 어렵다.
   - 승인/거절이 whitelist와 전혀 다른 저장 형식을 쓴다.

3. audit_log는 증적 로그이지 학습 자산으로 쓰기 어렵다.
   - action 문자열과 details JSON 중심이라 정규화된 피드백 분석에는 부적합하다.
   - 그렇다고 버리면 안 된다. 규정 준수 로그와 학습용 event store는 역할이 다르다.

4. 메모리 동기화가 DB truth를 일부 덮는다.
   - `explorer_whitelist.py`는 저장 직후 `PipelineResult.data`를 수정해 UI 즉시 반영을 만든다.
   - UX에는 유리하지만, 나중에 "원래 탐지 결과 vs 사람 판정 후 결과"를 분리해서 보기가 어렵다.

5. supervised ML과 연결 가능한 사람 확정 라벨 경로가 아직 없다.
   - 지금은 ground truth 또는 operational proxy만 있고, HITL 확정 라벨은 학습 경로에서 읽히지 않는다.

## Key Decisions

1. **`audit_log`와 `feedback_events`를 분리한다** (2026-04-16)
   - Rationale: 감사 증적과 학습/운영 집계용 저장소는 요구사항이 다르다.
   - Consequence: 동일 액션이 두 저장소에 모두 기록될 수 있다.

2. **whitelist는 유지하되, 더 이상 피드백의 유일한 원장으로 보지 않는다** (2026-04-16)
   - Rationale: 현재 탐지 억제 로직이 whitelist에 묶여 있으므로 즉시 대체 비용이 크다.
   - Consequence: 1차 구현은 `whitelist + feedback_events` 이중 구조다.

3. **rule feedback 승인/거절을 normalized event로도 남긴다** (2026-04-16)
   - Rationale: YAML 변경과 사람 승인 이력을 분리해 재사용하기 위해서다.
   - Consequence: JSONL은 하위 호환 로그로 유지하되 DB event가 추가된다.

4. **학습 반영은 저장/정규화 이후 단계로 둔다** (2026-04-16)
   - Rationale: 저장 구조와 라벨 품질 규칙 없이 supervised로 바로 연결하면 오염 가능성이 높다.
   - Consequence: 3.8 1차 완료 기준은 “재사용 가능한 피드백 자산 확보”다.

## Proposed Semantic Model

### Event types

- `document_feedback`
  - decision: `false_positive`, `confirmed_issue`, `needs_followup`

- `rule_feedback`
  - decision: `approved`, `rejected`

- `export_feedback`
  - decision: `generated`, `annotated`

### Document label rules

- `false_positive`
  - whitelist add 또는 감사자 명시적 오탐 판정
- `confirmed_issue`
  - 향후 수동 확정 UI 또는 export follow-up에서 확정
- `needs_followup`
  - 보류/추가 검토 필요

### Rule feedback rules

- `approved`
  - 회사 override에 반영된 규칙 제안
- `rejected`
  - 사람이 거부한 제안

## Known Gaps To Solve During Implementation

- `confirmed_issue`를 입력할 UI가 현재 별도로 없다.
  - 1차에서는 스키마만 열어두고 whitelist 외 추가 판단 UI는 최소 범위로 설계해야 한다.

- export feedback의 실제 사용자 주석 입력 UI는 아직 없다.
  - 1차에서는 export 실행 이벤트와 선택 메타만 연결하고, 코멘트 입력은 후속 확장으로 둘 수 있다.

- company-level JSONL과 engagement DB를 같이 쓰면 저장 위치가 두 갈래다.
  - 정규화 이벤트를 engagement DB에 두고, 회사 단위 집계는 repository helper가 여러 engagement를 읽는 방향이 현실적이다.

## Open Questions

- `feedback_events`를 engagement DB에 둘지, 회사 공용 DuckDB/파일로 둘지
  - 현재 구조상 engagement DB가 구현 비용이 낮다.

- whitelist remove를 어떻게 해석할지
  - “false_positive 취소” 이벤트로 남길지, 단순 삭제로 볼지 결정 필요

- `confirmed_issue` UI를 이번 범위에 포함할지
  - 문서에 적힌 범위상 “감사자 확정 라벨”이 필요하므로 최소 액션은 넣는 편이 좋다.

## Recommended Scope Cut

1차 구현 범위
- `feedback_events` 스키마
- whitelist add/remove event 연동
- rule feedback approve/reject event 연동
- document feedback label builder
- findings/detail/phase2 최소 조회

이번 턴에서 미루는 것
- 자동 재학습 트리거
- export 주석 기반 라벨링 고도화
- 회사 단위 cross-engagement 집계 대시보드
