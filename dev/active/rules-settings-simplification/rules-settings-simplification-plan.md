# Rules/Settings Simplification - Strategic Plan

## Executive Summary

`## 3.5 룰/설정 관리 단순화`의 목표는 전역 `AuditSettings`, 회사/engagement `settings_overrides`, 회사별 YAML(`audit_rules.yaml`, `keywords.yaml`, `risk_keywords.yaml`)의 책임을 다시 나눠 설정 복잡도를 줄이는 것이다. 이번 작업은 기능 추가보다 설정 체계 정리 성격이 강하므로, "무엇을 어디서 바꿀 수 있는지"를 먼저 고정하고 그 다음 키 통합, UI 정리, 마이그레이션 순서로 진행해야 한다.

## Current State

- `config/settings.py`의 `AuditSettings`가 탐지 임계값, 기능 토글, 파일/헤더 처리, ML 파라미터까지 사실상 모든 전역 설정을 단일 클래스에 담고 있다.
- `src/company/merger.py`의 `resolve_settings()`는 override 키가 실제 `AuditSettings` 필드에 없으면 경고만 남기고, 허용 범위 자체는 제한하지 않는다.
- `src/context.py`는 회사별 `audit_rules.yaml`, `keywords.yaml`, `risk_keywords.yaml`를 병합하지만, settings override와 YAML override의 책임 경계는 코드로 문서화되어 있지 않다.
- `dashboard/components/company_manager.py`는 `approval_amount_threshold` 같은 실제 `AuditSettings`에 없는 키를 저장하고 있어 문서/코드/운영 UI가 이미 어긋나 있다.
- `src/company/models.py`의 `settings_overrides: dict[str, Any]`는 자유도가 너무 높아 장기적으로 dead key, 오타 키, 책임 혼합을 누적시킨다.

## Proposed Solution

설정 체계를 아래 3층으로 단순화한다.

1. `AuditSettings`
   - 전역 기본값과 실행 환경 토글만 유지한다.
   - 회사별로 바꿀 수 있는 필드는 allowlist로 명시한다.
2. Company / Engagement override
   - 금액 임계값, 회계연도/휴일, 일부 기능 토글처럼 회사/engagement 특화 값만 허용한다.
   - 허용되지 않은 키는 경고가 아니라 검증 실패 또는 정규화 대상이 된다.
3. YAML rule resources
   - `audit_rules.yaml`: 코드/키워드/계정 prefix 같은 룰 사전
   - `keywords.yaml`: 컬럼 alias 사전
   - `risk_keywords.yaml`: 적요 위험어 사전
   - 임계값 성격의 값이 YAML과 settings 양쪽에 중복되면 한쪽으로 수렴시킨다.

핵심 원칙은 두 가지다.

- "값의 종류"로 책임을 나눈다.
  - 숫자 임계값/feature toggle = settings
  - 코드 목록/키워드 목록/계정 prefix 사전 = YAML
- "변경 주체"로 override를 제한한다.
  - 전역 팀 정책 = global settings / global YAML
  - 회사별 회계정책/ERP 차이 = company override / company YAML
  - engagement 일시 조정 = engagement override

## Implementation Phases

### Phase 1: 설정 인벤토리와 책임 표준화 (1 day)
**Goal**: 단순화 기준표를 만들고, dead key/중복 키/책임 혼합 키를 분류한다.

- [ ] `config/settings.py` 필드 인벤토리 작성 - File: `config/settings.py` - Size: M
- [ ] settings/YAML 책임 매핑표 작성 - File: `docs/개선사항.md`, `dev/active/rules-settings-simplification/rules-settings-simplification-context.md` - Size: S
- [ ] company/engagement override 실제 사용 키 수집 - File: `src/company/merger.py`, `dashboard/components/company_manager.py`, `tests/test_company/*` - Size: M
- [ ] 즉시 제거 후보와 하위호환 유지 후보 분리 - File: `config/settings.py`, `src/company/models.py` - Size: S

### Phase 2: 설정 스키마와 override 경계 정리 (1-2 days)
**Goal**: override 허용 범위와 정규화 경로를 코드로 고정한다.

- [ ] company/engagement override allowlist 정의 - File: `src/company/merger.py` - Size: M
- [ ] legacy alias 정규화 테이블 추가 (`approval_amount_threshold -> approval_thresholds` 등) - File: `src/company/merger.py` - Size: M
- [ ] unknown key 처리 정책 강화 (warn-only -> normalize or reject) - File: `src/company/merger.py`, `tests/test_company/test_merger.py` - Size: M
- [ ] `CompanyProfile`/`EngagementProfile` 저장 전 검증 보강 - File: `src/company/models.py`, `src/company/repository.py` - Size: M

### Phase 3: UI와 편집 진입점 단순화 (1 day)
**Goal**: 사용자가 잘못된 키를 저장하지 않도록 편집 UI를 재구성한다.

- [ ] `company_manager`를 실제 허용 키 기반 UI로 교체 - File: `dashboard/components/company_manager.py` - Size: L
- [ ] 승인한도 입력을 단일 숫자에서 `approval_thresholds` 편집 방식으로 수정 - File: `dashboard/components/company_manager.py` - Size: M
- [ ] 회사별 custom rules 상태 플래그 동기화 점검 - File: `dashboard/components/rule_feedback_panel.py`, `src/company/repository.py` - Size: S
- [ ] 변경 후 context invalidate와 UI 반영 경로 회귀 점검 - File: `src/context.py`, `tests/test_company/test_context.py` - Size: S

### Phase 4: 문서/마이그레이션/회귀 테스트 정리 (1 day)
**Goal**: 기존 데이터와 문서를 깨지 않고 새 체계로 수렴시킨다.

- [ ] 문서의 설정 키를 실제 코드 기준으로 정정 - File: `docs/개선사항.md`, 관련 docs - Size: S
- [ ] legacy company.yaml / engagement.yaml override 마이그레이션 함수 추가 - File: `src/company/merger.py` or `src/company/repository.py` - Size: M
- [ ] 설정 로딩/병합/저장 회귀 테스트 추가 - File: `tests/test_settings.py`, `tests/test_company/test_merger.py`, `tests/test_company/test_context.py` - Size: L
- [ ] 최소 import/smoke 검증과 UI 편집 경로 테스트 - File: `tests/modules/test_dashboard/*` - Size: M

## Risk Assessment

- **High Risk**: legacy override 키를 갑자기 차단하면 기존 회사 프로필이 로드 실패할 수 있다.
  - Mitigation: 1차는 alias normalize + warning, 2차에서만 hard reject로 전환한다.
- **High Risk**: `approval_thresholds` 같은 리스트형 설정을 UI에서 단순 숫자로 바꾸면 탐지 로직과 불일치가 생긴다.
  - Mitigation: 단일값 UI를 제거하고 리스트형 편집을 정식 지원한다.
- **Medium Risk**: 임계값을 settings에서 YAML로 옮기거나 반대로 옮길 때 호출부 누락이 생길 수 있다.
  - Mitigation: `rg` 기반 ripple search와 feature/pipeline 테스트를 함께 묶는다.
- **Medium Risk**: 회사별 YAML 수정 경로와 `has_custom_*` 플래그 동기화가 깨질 수 있다.
  - Mitigation: repository write 경로에 플래그 갱신 책임을 명시하거나 테스트로 고정한다.

## Success Metrics

- 설정 키 단순화:
  - 존재하지 않는 override 키 저장 경로 0개
  - legacy alias 100% 정규화
- 운영 안정성:
  - 회사/engagement context 로딩 회귀 0건
  - dashboard settings editor 저장 후 즉시 반영
- 테스트:
  - 설정 병합/정규화/저장 경로 테스트 추가
  - 관련 회귀 테스트 전부 통과

## Dependencies

- Code:
  - `config/settings.py`
  - `src/company/models.py`
  - `src/company/merger.py`
  - `src/context.py`
  - `dashboard/components/company_manager.py`
- Data:
  - 기존 `company.yaml`, `engagement.yaml`의 `settings_overrides`
  - 회사별 `audit_rules.yaml`, `keywords.yaml`, `risk_keywords.yaml`
