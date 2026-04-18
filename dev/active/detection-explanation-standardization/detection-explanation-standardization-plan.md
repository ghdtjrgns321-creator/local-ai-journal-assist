# Detection Explanation Standardization - Strategic Plan

## Executive Summary

`## 3.6 탐지 결과 설명 계층 표준화`의 목표는 탐지 결과를 "점수와 룰 코드" 중심 구조에서 "감사자가 바로 읽을 수 있는 설명 객체" 중심 구조로 끌어올리는 것이다. 이번 작업은 `DetectionResult.metadata`에 흩어진 설명 조각을 공통 스키마로 정리하고, UI 상세 패널과 export 문구가 같은 설명 데이터를 소비하도록 맞추는 데 초점을 둔다.

## Current State

- `src/detection/base.py`의 `DetectionResult`는 운영 메타(`display_name`, `maturity`, `run_status`)는 노출하지만 설명 메타의 표준 필드는 없다.
- 룰 설명은 `RULE_CODES`, `RULE_LEGAL_BASIS`, 일부 detector별 `metadata`, `warnings`, `RuleFlag.detail`에 나뉘어 있어 소비 지점마다 조합 방식이 다르다.
- `dashboard/components/explorer_detail.py`는 문서별 rule score 차트와 라인 아이템만 보여주고, "왜 걸렸는지 / 무엇을 봐야 하는지"를 구조화해서 표시하지 않는다.
- `dashboard/tab_findings.py`는 필터 요약과 grid 중심이라 감사자 관점 설명 계층이 없다.
- `src/export/audit_evidence.py`는 narrative를 직접 문자열로 조합하는데, detector 공통 설명 스키마를 쓰지 않아 UI와 export의 어휘가 쉽게 갈라진다.
- `src/detection/constants.py`에는 detector profile과 rule name/severity는 있으나, 설명 계층에서 필요한 `사용 컬럼`, `오탐 가능성`, `감사자 확인 포인트`, `기준서 근거` 메타는 중앙 관리되지 않는다.

## Proposed Solution

설명 계층을 3단으로 표준화한다.

1. Track-level explanation
   - `DetectionResult`에 detector 공통 설명 메타를 올린다.
   - 예: `summary`, `why_it_flagged`, `used_columns`, `false_positive_risks`, `auditor_checks`, `references`.
   - detector가 별도 값을 주지 않으면 `constants.py`의 기본 profile/registry에서 채운다.

2. Rule-level explanation
   - 룰별 설명 사전을 `src/detection/constants.py`에 둔다.
   - 각 rule은 `plain_reason`, `used_columns`, `false_positive_risks`, `auditor_checks`, `references`를 가진다.
   - `RuleFlag`와 `details`를 바탕으로 "이번 문서에서 실제 발화할 룰 설명"을 조립한다.

3. Record/document-level explanation
   - `explorer_detail`와 `audit_evidence`에서 동일한 builder를 사용해 문서 단위 설명 블록을 만든다.
   - UI와 export가 같은 문장 조각과 용어를 공유하게 한다.

핵심 구현 방향:

- `DetectionResult`는 설명을 저장하는 공통 인터페이스만 가진다.
- 실제 설명 조립은 `src/detection/explanations.py` 같은 별도 builder 모듈에서 담당한다.
- detector별 특이 케이스는 builder override나 metadata supplement로만 처리하고, UI/export에서 detector별 분기문을 늘리지 않는다.

## Implementation Phases

### Phase 1: Explanation Schema Foundation (0.5-1 day)
**Goal**: 설명 메타 공통 스키마와 registry 구조를 만든다.

- [ ] 설명 dataclass 또는 typed dict 정의 - File: `src/detection/base.py` or `src/detection/explanations.py` - Size: M
- [ ] detector-level explanation profile 추가 - File: `src/detection/constants.py` - Size: M
- [ ] rule-level explanation registry 추가 - File: `src/detection/constants.py` - Size: L
- [ ] `DetectionResult` 접근자 추가 (`explanation_summary`, `used_columns`, `auditor_checks` 등) - File: `src/detection/base.py` - Size: M

### Phase 2: Explanation Builder Integration (1 day)
**Goal**: track/rule/document 단위 설명을 조합하는 공통 builder를 만든다.

- [ ] `build_track_explanation()` 구현 - File: `src/detection/explanations.py` - Size: M
- [ ] `build_document_explanation()` 구현 - File: `src/detection/explanations.py` - Size: L
- [ ] `DetectionResult`와 row context를 받아 active rule 설명만 추리는 로직 추가 - File: `src/detection/explanations.py` - Size: M
- [ ] detector 기본 metadata를 builder와 연결 - File: `src/detection/base.py`, `src/pipeline.py` - Size: M

### Phase 3: UI Standardization (0.5-1 day)
**Goal**: findings/explorer 화면이 공통 설명 블록을 사용하게 한다.

- [ ] explorer detail에 설명 패널 추가 - File: `dashboard/components/explorer_detail.py` - Size: L
- [ ] findings 탭에 선택 문서 explanation summary 노출 - File: `dashboard/tab_findings.py` - Size: M
- [ ] explanation block의 비어 있는 필드 처리 규칙 정의 - File: `dashboard/components/explorer_detail.py` - Size: S

### Phase 4: Export Standardization (0.5 day)
**Goal**: export narrative가 같은 설명 builder를 쓰도록 맞춘다.

- [ ] `audit_evidence` 직접 문자열 조립 제거 - File: `src/export/audit_evidence.py` - Size: M
- [ ] detector/rule references를 evidence narrative에 반영 - File: `src/export/audit_evidence.py` - Size: M
- [ ] export용 concise mode와 UI용 detailed mode 분리 - File: `src/detection/explanations.py`, `src/export/audit_evidence.py` - Size: M

### Phase 5: Verification And Docs (0.5-1 day)
**Goal**: 설명 계층 회귀를 테스트와 문서로 고정한다.

- [ ] builder 단위 테스트 추가 - File: `tests/modules/test_detection/test_explanations.py` - Size: L
- [ ] findings/explorer smoke 테스트 추가 - File: `tests/modules/test_dashboard/test_tab_findings.py`, `tests/modules/test_dashboard/test_explorer_detail.py` - Size: M
- [ ] audit evidence narrative 회귀 테스트 추가 - File: `tests/modules/test_export/test_audit_evidence.py` - Size: M
- [ ] `docs/개선사항.md` 상태 업데이트 - File: `docs/개선사항.md` - Size: S

## Risk Assessment

- **High Risk**: 룰 설명 registry를 한 번에 전 룰로 채우려 하면 범위가 급격히 커진다.
  - Mitigation: 1차 구현은 현재 기본 경로 detector와 대표 룰부터 채우고, 누락 룰은 graceful fallback(`RULE_CODES` 기반 축약 설명)으로 처리한다.
- **High Risk**: UI와 export가 각각 자체 포맷팅을 유지하면 다시 분기 로직이 생긴다.
  - Mitigation: narrative 조합은 builder 한 곳에서 담당하고, UI/export는 detailed/concise 렌더 옵션만 다르게 둔다.
- **Medium Risk**: detector별 metadata에 임의 키가 계속 쌓이면 표준화가 약해진다.
  - Mitigation: 허용 explanation key 집합을 고정하고, 미등록 키는 테스트에서 잡는다.
- **Medium Risk**: 사용 컬럼 목록이 실제 detector 구현과 어긋날 수 있다.
  - Mitigation: detector별 고정 컬럼은 registry에 두고, 동적 컬럼은 metadata supplement로만 추가한다.

## Success Metrics

- UI와 export가 같은 explanation source를 사용한다.
- `DetectionResult`에서 detector-level explanation 필드를 공통 접근자로 읽을 수 있다.
- 대표 detector 6종 이상(`layer_a`, `layer_b`, `layer_c`, `benford`, `duplicate`, `intercompany`)에 표준 설명이 붙는다.
- 테스트:
  - explanation builder 단위 테스트 추가
  - findings/explorer render smoke 테스트 추가
  - audit evidence narrative 회귀 테스트 추가

## Dependencies

- Code:
  - `src/detection/base.py`
  - `src/detection/constants.py`
  - `src/pipeline.py`
  - `src/export/audit_evidence.py`
  - `dashboard/components/explorer_detail.py`
  - `dashboard/tab_findings.py`
- Existing data contracts:
  - `DetectionResult.rule_flags`
  - `DetectionResult.details`
  - `flagged_rules`, `document_id`, `anomaly_score`, `risk_level`
