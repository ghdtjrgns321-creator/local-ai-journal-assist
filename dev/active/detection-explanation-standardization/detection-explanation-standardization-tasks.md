# Detection Explanation Standardization - Task Checklist

## Progress Summary

4 / 15 tasks complete (27%); Sprint B3-meta metadata/schema complete, UI/export display tasks deferred

## Phase 1: Schema Foundation

- [x] explanation 공통 필드 집합을 확정한다. (Sprint B3-meta)
  - File: `src/detection/explanation_schema.py`
  - Details: `principle`, `violation_reason`, `audit_next_action`, `reference` 4필드 `RuleExplanation` frozen dataclass로 확정했다.
  - Acceptance: JSON serialize/deserialize round-trip 및 필드 결측/blank 검출 테스트 통과.
  - Size: M

- [x] detector explanation profile을 추가한다. (Sprint B3-meta)
  - File: `src/detection/integrity_layer.py`, `src/detection/fraud_layer.py`, `src/detection/anomaly_layer.py`, `src/detection/evidence_detector.py`, `src/detection/benford_detector.py`, `src/detection/variance_layer.py`
  - Details: 활성 룰 34개에 대해 `RuleExplanation` 인스턴스를 detector 소유 상수로 배치했다.
  - Acceptance: `ACTIVE_RULE_IDS` 전수 설명 보유 테스트 통과.
  - Size: M

- [x] rule explanation registry를 추가한다. (Sprint B3-meta)
  - File: `src/detection/explanation_registry.py`
  - Details: `get_rule_explanation(rule_id)` 및 `list_rules_without_explanation()` 조회 API를 추가했다.
  - Acceptance: known/unknown lookup, custom scope missing-list, dashboard/rule_panel 비의존 테스트 통과.
  - Size: L

## Phase 2: Builder Integration

- [DEFERRED] explanation builder 모듈을 만든다.
  - File: `src/detection/explanations.py`
  - Details: track/rule/document explanation을 조합하는 순수 함수를 정의한다.
  - Acceptance: UI/export 어느 쪽에서도 이 builder만 호출하면 필요한 설명 객체를 받을 수 있다.
  - Size: M

- [DEFERRED] track explanation builder를 구현한다.
  - File: `src/detection/explanations.py`
  - Details: `DetectionResult`와 detector profile을 입력받아 track-level 설명을 조립한다.
  - Acceptance: detector metadata가 비어도 registry fallback으로 설명이 생성된다.
  - Size: M

- [DEFERRED] document explanation builder를 구현한다.
  - File: `src/detection/explanations.py`
  - Details: 선택 문서의 active rule만 추려 headline, triggered_rules, auditor_focus_points, narrative를 만든다.
  - Acceptance: flagged rule이 있는 문서에서 규칙별 설명과 감사자 확인 포인트가 함께 생성된다.
  - Size: L

- [DEFERRED] `DetectionResult` explanation 접근자를 연결한다.
  - File: `src/detection/base.py`
  - Details: metadata 자유 dict를 직접 읽지 않고도 summary/used_columns/auditor_checks를 조회할 수 있게 한다.
  - Acceptance: 소비 지점에서 `metadata["..."]` 직접 접근을 줄일 수 있다.
  - Size: M

## Phase 3: UI Standardization

- [DEFERRED] explorer detail에 explanation summary 섹션을 추가한다.
  - File: `dashboard/components/explorer_detail.py`
  - Details: 차트/라인아이템 외에 문서 단위 설명, 오탐 가능성, 감사자 확인 포인트를 보여준다.
  - Acceptance: 선택 문서 상세에서 "왜 걸렸는지"를 표준 필드 기반으로 읽을 수 있다.
  - Size: L

- [DEFERRED] findings 탭 선택 건 상세 흐름을 explanation builder와 연결한다.
  - File: `dashboard/tab_findings.py`
  - Details: 선택 row 전달 방식과 `render_detail()` 시그니처를 정리하고 explanation block이 같이 노출되게 한다.
  - Acceptance: findings 탭에서 선택한 건에 대해 explanation 패널이 정상 렌더된다.
  - Size: M

- [DEFERRED] explanation empty-state 규칙을 추가한다.
  - File: `dashboard/components/explorer_detail.py`
  - Details: references나 false-positive 항목이 없을 때 숨길지, 기본 문구를 보여줄지 결정한다.
  - Acceptance: 빈 리스트나 None이 그대로 UI에 노출되지 않는다.
  - Size: S

## Phase 4: Export Standardization

- [DEFERRED] audit evidence가 explanation builder를 사용하게 바꾼다.
  - File: `src/export/audit_evidence.py`
  - Details: 직접 문자열 조립 대신 공통 explanation source를 사용해 narrative를 만든다.
  - Acceptance: UI와 export가 같은 룰 이유와 기준서 근거를 사용한다.
  - Size: M

- [x] 기준서/도메인 근거 표기를 표준화한다. (Sprint B3-meta metadata scope)
  - File: `src/detection/constants.py`, `src/export/audit_evidence.py`
  - Details: `RULE_LEGAL_BASIS` 성격 데이터를 explanation registry로 흡수하거나 공용 참조로 이동한다.
  - Acceptance: 기준서 근거가 한 소스에서 관리된다.
  - Size: M

- [DEFERRED] concise export mode를 추가한다.
  - File: `src/detection/explanations.py`, `src/export/audit_evidence.py`
  - Details: UI용 자세한 설명과 export용 압축 문장을 분리하되 같은 데이터 원천을 사용한다.
  - Acceptance: narrative 길이만 달라지고 핵심 근거는 일치한다.
  - Size: M

## Phase 5: Verification

- [x] explanation schema/registry 단위 테스트를 추가한다. (Sprint B3-meta)
  - File: `tests/modules/test_detection/test_explanations.py`
  - Details: registry lookup, fallback, document narrative, empty-field 처리를 검증한다.
  - Acceptance: 대표 detector/rule 케이스가 모두 테스트된다.
  - Size: L

- [DEFERRED] dashboard smoke 테스트를 추가한다.
  - File: `tests/modules/test_dashboard/test_tab_findings.py`, `tests/modules/test_dashboard/test_explorer_detail.py`
  - Details: explanation block이 선택 건에서 렌더되는지와 빈 상태를 확인한다.
  - Acceptance: 시그니처 mismatch와 렌더 회귀를 잡는 테스트가 생긴다.
  - Size: M

- [DEFERRED] export narrative 회귀 테스트를 추가한다.
  - File: `tests/modules/test_export/test_audit_evidence.py`
  - Details: 같은 입력에서 기준서 근거와 감사자 확인 포인트가 narrative에 반영되는지 검증한다.
  - Acceptance: narrative 포맷 회귀를 자동으로 잡을 수 있다.
  - Size: M

## Deployment Checklist

- [ ] explanation field 이름이 `DetectionResult`, builder, UI, export에서 일치한다.
- [ ] 기본 경로 detector 설명 registry가 채워졌다.
- [ ] findings/explorer import smoke 검증을 통과했다.
- [ ] 관련 pytest를 통과했다.
- [ ] `docs/개선사항.md` 상태를 구현 기준으로 갱신했다.
