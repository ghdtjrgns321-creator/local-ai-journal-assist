# Detection Explanation Standardization - Context & Decisions

## Status

- Phase: B3 metadata-only complete
- Progress: 4 / 15 tasks complete, UI/export display tasks deferred
- Last Updated: 2026-05-17

## Key Files

**Target**
- `src/detection/base.py` - `DetectionResult` 공통 인터페이스
- `src/detection/constants.py` - detector/rule registry
- `src/pipeline.py` - detector metadata 주입 지점
- `src/export/audit_evidence.py` - export narrative 생성
- `dashboard/components/explorer_detail.py` - 선택 문서 상세 패널
- `dashboard/tab_findings.py` - findings 탭 진입점

**Tests**
- `tests/modules/test_detection/test_base.py`
- `tests/modules/test_detection/test_explanations.py`
- `tests/modules/test_dashboard/test_tab_findings.py`
- `tests/modules/test_export/test_audit_evidence.py`

## Current Findings

1. 설명 데이터가 결과 모델에 표준 필드로 존재하지 않는다.
   - 현재 `DetectionResult`는 운영 상태 메타를 잘 노출하지만, 설명 계층은 `metadata` 자유 dict에 맡겨져 있다.

2. 설명 근거가 여러 곳에 분산되어 있다.
   - 룰명은 `RULE_CODES`
   - 일부 기준서 근거는 `RULE_LEGAL_BASIS`
   - detector별 경고는 `warnings`
   - 부가 설명은 `RuleFlag.detail`
   - export narrative는 `audit_evidence.py` 내부 문자열 조합

3. UI가 설명 가능성 강점을 충분히 쓰지 못한다.
   - `explorer_detail`은 차트와 line item은 보여주지만, 감사자용 "확인 포인트"를 공통 포맷으로 보여주지 않는다.
   - `tab_findings`도 선택 건 설명보다 목록/필터 흐름 중심이다.

4. export와 UI의 설명 언어가 분리되어 있다.
   - `audit_evidence.py`는 직접 narrative를 만들고 있어, 나중에 UI 문구와 쉽게 어긋난다.

5. 룰 전체를 한 번에 정교하게 설명하려 들면 범위가 커진다.
   - 현재 기본 경로 룰 수가 많아 3.6은 "표준 스키마 + 우선 적용 범위"가 중요하다.

## Key Decisions

1. **설명 스키마는 `DetectionResult` 공통 인터페이스에 올린다** (2026-04-16)
   - Rationale: detector별 구현체에 설명 필드가 흩어지면 UI/export에서 일관되게 읽기 어렵다.
   - Alternatives: UI/export에서 각 detector metadata를 개별 해석
   - Trade-offs: base 모델이 약간 무거워지지만 소비 지점 단순화 효과가 더 크다.

2. **설명 조립은 별도 builder 모듈로 분리한다** (2026-04-16)
   - Rationale: narrative 조립 규칙을 `audit_evidence.py`나 dashboard 컴포넌트에 두면 다시 중복된다.
   - Alternatives: export/UI 각각 자체 포맷터 유지
   - Trade-offs: 새 모듈이 추가되지만 회귀 관리가 쉬워진다.

3. **룰 설명 registry는 fallback 가능 구조로 시작한다** (2026-04-16)
   - Rationale: 모든 룰을 한 번에 완벽히 채우는 것보다 표준 인터페이스를 먼저 고정하는 편이 안전하다.
   - Alternatives: 모든 룰의 explanation metadata를 선행 작성
   - Trade-offs: 일부 룰은 1차에서 축약 설명을 쓰지만 구현 속도와 안정성이 좋아진다.

4. **UI와 export는 같은 explanation source를 공유한다** (2026-04-16)
   - Rationale: 3.6의 핵심은 "설명 가능성의 제품화"이지 화면별 개별 문구 작성이 아니다.
   - Alternatives: UI 전용/리포트 전용 설명 세트 분리
   - Trade-offs: 포맷 옵션은 필요하지만 데이터 원천은 하나로 유지된다.

## Proposed Explanation Shape

- Track explanation
  - `summary`
  - `why_it_flagged`
  - `used_columns`
  - `false_positive_risks`
  - `auditor_checks`
  - `references`

- Rule explanation
  - `rule_id`
  - `plain_reason`
  - `used_columns`
  - `false_positive_risks`
  - `auditor_checks`
  - `references`

- Document explanation
  - `document_id`
  - `headline`
  - `triggered_rules`
  - `auditor_focus_points`
  - `narrative`

## Known Issues

- `dashboard/tab_findings.py`의 `render_detail(selected, result.data)` 호출 시그니처는 현재 `explorer_detail.render_detail()` 정의와 맞지 않는다. 3.6 구현 전에 이 호출 경로를 실제 런타임 기준으로 다시 점검해야 한다.
- `src/export/audit_evidence.py`는 현재 `RULE_LEGAL_BASIS`를 파일 내부에 들고 있어 설명 registry와 중복될 가능성이 높다.
- 일부 detector는 실제 사용 컬럼이 동적이다. 이런 경우 고정 컬럼만 registry에 두고 동적 컬럼은 metadata supplement로 보강해야 한다.

## Sprint B3-meta Results (2026-05-17)

Sprint B3는 UI 표시 영역을 후속 phase로 이관하고, detection explanation metadata 전용 범위로 완료했다. `RuleExplanation` frozen dataclass를 `src/detection/explanation_schema.py`에 추가했고, `src/detection/explanation_registry.py`가 `get_rule_explanation(rule_id)` 및 `list_rules_without_explanation()` 단일 조회 API를 제공한다.

활성 설명 범위는 canonical L1-L4 32개와 Variance macro `D01`, `D02`를 포함한 34개 룰이다. 룰별 인스턴스는 detector layer 상수에 보강했으며, `RULE_DETAIL_METADATA_V1`의 canonical/count/surface 키는 변경하지 않았다. `dashboard/` 파일과 PHASE1 결과 UI는 수정하지 않았고, 표시 영역 task는 `[DEFERRED]`로 유지한다.

검증: `uv run pytest tests/modules/test_detection/test_explanation_schema.py tests/modules/test_detection/test_explanation_registry.py tests/modules/test_detection/test_rule_detail_metadata.py tests/modules/test_detection/test_rule_scoring.py -q` 통과(81 passed), ruff targeted check 통과. `git diff --stat -- dashboard/`는 사용자 hook에 의해 차단되어 handoff에 hook 차단 사실과 대체 검증을 기록했다.

## Open Questions To Resolve During Implementation

- 설명 스키마를 dataclass로 둘지, 직렬화 친화적인 dict/TypedDict로 둘지
- `references`에 기준서 문자열만 둘지, `code + label` 구조로 둘지
- `explorer_detail`에서 문서 단위 설명을 DB query 결과만으로 만들지, `PipelineResult.data` 행 컨텍스트를 함께 쓸지
- 1차 적용 범위를 production detector까지만 제한할지, beta detector(`relational`, `evidence`, `access_audit`)까지 포함할지
