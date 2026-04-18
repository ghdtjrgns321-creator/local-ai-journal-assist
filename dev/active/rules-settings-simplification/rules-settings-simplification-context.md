# Rules/Settings Simplification - Context & Decisions

## Status

- Phase: Planning complete
- Progress: 0 / 16 tasks complete
- Last Updated: 2026-04-16

## Key Files

**Target**
- `config/settings.py` - 전역 설정 단일 소스
- `src/company/merger.py` - settings override 병합과 YAML merge 진입점
- `src/context.py` - 최종 `CompanyContext` 조립 경로
- `src/company/models.py` - `settings_overrides` 저장 스키마
- `src/company/repository.py` - company/engagement YAML 저장소
- `dashboard/components/company_manager.py` - 회사별 설정 편집 UI
- `dashboard/components/rule_feedback_panel.py` - 회사별 rules YAML 갱신 UI

**Tests**
- `tests/test_settings.py`
- `tests/test_company/test_merger.py`
- `tests/test_company/test_context.py`
- `tests/test_company/test_repository.py`

## Current Findings

1. `AuditSettings`가 너무 넓다.
   - 파일/헤더 처리, 탐지 임계값, 통계 기준, ML 하이퍼파라미터, feature toggle이 한 클래스에 혼재돼 있다.

2. override 허용 범위가 정의돼 있지 않다.
   - `resolve_settings()`는 키 존재 여부만 경고할 뿐, "회사에서 바꾸면 안 되는 키"를 막지 않는다.

3. UI와 실제 키가 어긋난다.
   - `dashboard/components/company_manager.py`는 `approval_amount_threshold`를 저장하지만 실제 설정은 `approval_thresholds`를 사용한다.

4. YAML 책임은 비교적 명확하지만 코드상 계약이 느슨하다.
   - `audit_rules.yaml`은 코드/키워드/prefix 사전, `keywords.yaml`은 alias 사전, `risk_keywords.yaml`은 위험어 사전 역할을 이미 하고 있다.
   - 다만 문서와 편집 UI에 이 계약이 드러나 있지 않다.

5. `settings_overrides`가 자유 dict라서 dead key 누적에 취약하다.
   - `src/company/models.py`는 저장 시점 검증을 거의 하지 않고 `dict[str, Any]`를 그대로 허용한다.

## Key Decisions

1. **override allowlist를 코드 상수로 도입한다** (2026-04-16)
   - Rationale: 현재 가장 큰 문제는 필드 수 자체보다 "아무 키나 들어갈 수 있음"이다.
   - Alternatives: `CompanyProfile`에 전체 settings 하위모델 도입
   - Trade-offs: 상수 관리 비용은 늘지만, 저장/검증/문서/UI를 같은 표로 묶기 쉬워진다.

2. **legacy alias는 바로 삭제하지 않고 정규화한다** (2026-04-16)
   - Rationale: 기존 회사 YAML을 한 번에 깨면 운영 데이터 호환성이 떨어진다.
   - Alternatives: 즉시 hard reject
   - Trade-offs: 한동안 normalize 코드가 남지만, 마이그레이션 안전성이 높다.

3. **리스트형/사전형 설정은 UI에서 구조 그대로 편집한다** (2026-04-16)
   - Rationale: `approval_thresholds`를 단일 숫자로 축약하면 의미가 변한다.
   - Alternatives: 대표값 하나만 노출
   - Trade-offs: UI는 조금 복잡해지지만 코드/운영 의미가 일치한다.

4. **YAML과 settings의 책임을 값 타입으로 고정한다** (2026-04-16)
   - Rationale: 중복 키 제거의 기준이 있어야 정리가 가능하다.
   - Alternatives: 파일 단위로 임의 분리
   - Trade-offs: 예외 케이스가 일부 생길 수 있지만 장기 유지보수성이 높다.

## Proposed Responsibility Matrix

- `AuditSettings`
  - 수치형 임계값
  - feature toggle
  - 실행/학습 파라미터
  - 회사별 허용 override 대상의 기본값

- `company.settings_overrides`
  - 회사 정책 차이
  - 승인한도, 회계연도 시작월, 휴일, 일부 탐지 활성화 여부

- `engagement.settings_overrides`
  - 특정 연도/감사 건에서만 바뀌는 값
  - materiality 주변값, 일시적 runtime 성격의 조정

- `audit_rules.yaml`
  - source code 목록
  - account prefix / mapping
  - rule keyword / identifier 사전

- `keywords.yaml`
  - 컬럼 alias dictionary

- `risk_keywords.yaml`
  - 위험 적요 dictionary

## Known Issues

- `dev/README.md`는 현재 저장소에 없어 planner skill의 권장 컨텍스트를 전부 읽을 수는 없었다.
- `company_manager.py`의 승인한도 UI는 현재 구현 그대로 두면 잘못된 키를 계속 축적한다.
- 테스트는 settings 병합 성공 케이스는 있으나, alias 정규화/허용 키 제한/legacy 마이그레이션 테스트는 아직 없다.

## Open Questions To Resolve During Implementation

- 회사별 override 허용 키를 코드 상수만으로 둘지, 문서화된 YAML/JSON 메타로 외부화할지
- engagement override에서 feature toggle까지 허용할지, 회사 레벨만 허용할지
- `has_custom_rules` 같은 플래그를 repository write 시 자동 갱신할지, UI 호출자가 책임질지
