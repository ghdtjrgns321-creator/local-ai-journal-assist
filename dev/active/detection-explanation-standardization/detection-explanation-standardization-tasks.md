# Detection Explanation Standardization - Task Checklist

## Progress Summary

0 / 15 tasks complete (0%)

## Phase 1: Schema Foundation

- [ ] explanation 공통 필드 집합을 확정한다.
  - File: `src/detection/base.py`, `src/detection/constants.py`
  - Details: `summary`, `why_it_flagged`, `used_columns`, `false_positive_risks`, `auditor_checks`, `references`를 표준 필드로 정의한다.
  - Acceptance: `DetectionResult`에서 공통 접근자로 읽을 수 있고 필드 이름이 문서/코드/UI에서 일치한다.
  - Size: M

- [ ] detector explanation profile을 추가한다.
  - File: `src/detection/constants.py`
  - Details: detector별 기본 설명 템플릿과 기본 사용 컬럼/감사자 확인 포인트를 registry로 둔다.
  - Acceptance: 기본 경로 detector 6종 이상이 profile 조회만으로 설명 기본값을 가진다.
  - Size: M

- [ ] rule explanation registry를 추가한다.
  - File: `src/detection/constants.py`
  - Details: 대표 룰부터 `plain_reason`, `used_columns`, `false_positive_risks`, `auditor_checks`, `references`를 등록한다.
  - Acceptance: 미등록 룰은 fallback 설명으로 내려가고, 등록된 룰은 구조화 explanation을 반환한다.
  - Size: L

## Phase 2: Builder Integration

- [ ] explanation builder 모듈을 만든다.
  - File: `src/detection/explanations.py`
  - Details: track/rule/document explanation을 조합하는 순수 함수를 정의한다.
  - Acceptance: UI/export 어느 쪽에서도 이 builder만 호출하면 필요한 설명 객체를 받을 수 있다.
  - Size: M

- [ ] track explanation builder를 구현한다.
  - File: `src/detection/explanations.py`
  - Details: `DetectionResult`와 detector profile을 입력받아 track-level 설명을 조립한다.
  - Acceptance: detector metadata가 비어도 registry fallback으로 설명이 생성된다.
  - Size: M

- [ ] document explanation builder를 구현한다.
  - File: `src/detection/explanations.py`
  - Details: 선택 문서의 active rule만 추려 headline, triggered_rules, auditor_focus_points, narrative를 만든다.
  - Acceptance: flagged rule이 있는 문서에서 규칙별 설명과 감사자 확인 포인트가 함께 생성된다.
  - Size: L

- [ ] `DetectionResult` explanation 접근자를 연결한다.
  - File: `src/detection/base.py`
  - Details: metadata 자유 dict를 직접 읽지 않고도 summary/used_columns/auditor_checks를 조회할 수 있게 한다.
  - Acceptance: 소비 지점에서 `metadata["..."]` 직접 접근을 줄일 수 있다.
  - Size: M

## Phase 3: UI Standardization

- [ ] explorer detail에 explanation summary 섹션을 추가한다.
  - File: `dashboard/components/explorer_detail.py`
  - Details: 차트/라인아이템 외에 문서 단위 설명, 오탐 가능성, 감사자 확인 포인트를 보여준다.
  - Acceptance: 선택 문서 상세에서 "왜 걸렸는지"를 표준 필드 기반으로 읽을 수 있다.
  - Size: L

- [ ] findings 탭 선택 건 상세 흐름을 explanation builder와 연결한다.
  - File: `dashboard/tab_findings.py`
  - Details: 선택 row 전달 방식과 `render_detail()` 시그니처를 정리하고 explanation block이 같이 노출되게 한다.
  - Acceptance: findings 탭에서 선택한 건에 대해 explanation 패널이 정상 렌더된다.
  - Size: M

- [ ] explanation empty-state 규칙을 추가한다.
  - File: `dashboard/components/explorer_detail.py`
  - Details: references나 false-positive 항목이 없을 때 숨길지, 기본 문구를 보여줄지 결정한다.
  - Acceptance: 빈 리스트나 None이 그대로 UI에 노출되지 않는다.
  - Size: S

## Phase 4: Export Standardization

- [ ] audit evidence가 explanation builder를 사용하게 바꾼다.
  - File: `src/export/audit_evidence.py`
  - Details: 직접 문자열 조립 대신 공통 explanation source를 사용해 narrative를 만든다.
  - Acceptance: UI와 export가 같은 룰 이유와 기준서 근거를 사용한다.
  - Size: M

- [ ] 기준서/도메인 근거 표기를 표준화한다.
  - File: `src/detection/constants.py`, `src/export/audit_evidence.py`
  - Details: `RULE_LEGAL_BASIS` 성격 데이터를 explanation registry로 흡수하거나 공용 참조로 이동한다.
  - Acceptance: 기준서 근거가 한 소스에서 관리된다.
  - Size: M

- [ ] concise export mode를 추가한다.
  - File: `src/detection/explanations.py`, `src/export/audit_evidence.py`
  - Details: UI용 자세한 설명과 export용 압축 문장을 분리하되 같은 데이터 원천을 사용한다.
  - Acceptance: narrative 길이만 달라지고 핵심 근거는 일치한다.
  - Size: M

## Phase 5: Verification

- [ ] explanation builder 단위 테스트를 추가한다.
  - File: `tests/modules/test_detection/test_explanations.py`
  - Details: registry lookup, fallback, document narrative, empty-field 처리를 검증한다.
  - Acceptance: 대표 detector/rule 케이스가 모두 테스트된다.
  - Size: L

- [ ] dashboard smoke 테스트를 추가한다.
  - File: `tests/modules/test_dashboard/test_tab_findings.py`, `tests/modules/test_dashboard/test_explorer_detail.py`
  - Details: explanation block이 선택 건에서 렌더되는지와 빈 상태를 확인한다.
  - Acceptance: 시그니처 mismatch와 렌더 회귀를 잡는 테스트가 생긴다.
  - Size: M

- [ ] export narrative 회귀 테스트를 추가한다.
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
