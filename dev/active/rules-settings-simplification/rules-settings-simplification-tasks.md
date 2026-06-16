# Rules/Settings Simplification - Task Checklist

## Progress Summary

0 / 16 tasks complete (0%)

## Phase 1: Inventory

- [ ] `AuditSettings` 필드를 기능군별로 분류한다.
  - File: `config/settings.py`
  - Details: 파일/헤더, feature engineering, detection threshold, ML, feature toggle로 그룹을 나눈다.
  - Acceptance: 각 필드가 정확히 한 그룹에 속하는 표가 있다.
  - Size: S

- [ ] override 실사용 키를 수집한다.
  - File: `src/company/merger.py`, `dashboard/components/company_manager.py`, `tests/test_company/*`
  - Details: 회사/engagement/UI/테스트에서 실제로 쓰는 override 키 목록을 뽑는다.
  - Acceptance: 허용 유지, alias 정규화, 제거 후보 3분류 목록이 있다.
  - Size: S

- [ ] YAML 리소스 책임표를 정리한다.
  - File: `config/audit_rules.yaml`, `config/keywords.yaml`, `config/risk_keywords.yaml`
  - Details: 각 파일이 어떤 종류의 값만 가져야 하는지 정의한다.
  - Acceptance: `settings vs YAML` 경계 문장이 문서에 반영된다.
  - Size: S

- [ ] 문서와 코드가 어긋난 키를 기록한다.
  - File: `docs/archive/completed/개선사항.md`, `dashboard/components/company_manager.py`
  - Details: `approval_amount_threshold` 같은 잘못된 키를 목록화한다.
  - Acceptance: 수정 대상 키 목록과 치환 규칙이 있다.
  - Size: S

## Phase 2: Settings Boundary

- [ ] company override allowlist를 추가한다.
  - File: `src/company/merger.py`
  - Details: 회사 레벨에서 허용하는 settings 키 집합을 상수로 만든다.
  - Acceptance: allowlist 밖의 키는 normalize 또는 reject 경로를 탄다.
  - Size: M

- [ ] engagement override allowlist를 추가한다.
  - File: `src/company/merger.py`
  - Details: engagement 레벨 허용 키를 분리한다.
  - Acceptance: company/engagement 허용 범위 차이가 테스트로 고정된다.
  - Size: M

- [ ] legacy alias 정규화를 구현한다.
  - File: `src/company/merger.py`
  - Details: `approval_amount_threshold`를 `approval_thresholds`로 변환하는 등 하위호환 alias를 처리한다.
  - Acceptance: legacy 입력을 넣어도 최종 `AuditSettings`가 올바른 필드를 가진다.
  - Size: M

- [ ] unknown key 정책을 강화한다.
  - File: `src/company/merger.py`, `tests/test_company/test_merger.py`
  - Details: warn-only에서 normalize-or-reject 구조로 바꾼다.
  - Acceptance: 허용되지 않은 키 테스트가 실패/경고 정책대로 동작한다.
  - Size: M

## Phase 3: Persistence And UI

- [ ] `settings_overrides` 저장 전 정규화 경로를 만든다.
  - File: `src/company/models.py`, `src/company/repository.py`
  - Details: 저장 직전 alias/허용 키 검증을 통과시키는 함수 또는 validator를 추가한다.
  - Acceptance: 저장된 YAML에 dead key가 남지 않는다.
  - Size: M

- [ ] 회사 설정 편집 UI를 허용 키 기준으로 재구성한다.
  - File: `dashboard/components/company_manager.py`
  - Details: 현재 하드코딩된 잘못된 키를 제거하고 허용된 실제 설정만 편집하게 한다.
  - Acceptance: UI 저장 후 `company.yaml`에 실제 설정 키만 남는다.
  - Size: L

- [ ] 승인한도 편집 UX를 리스트형에 맞게 바꾼다.
  - File: `dashboard/components/company_manager.py`
  - Details: `approval_thresholds`를 단계별 입력으로 수정한다.
  - Acceptance: 저장 후 `ctx.settings.approval_thresholds`가 즉시 반영된다.
  - Size: M

- [ ] rules 변경 플래그 동기화 책임을 고정한다.
  - File: `dashboard/components/rule_feedback_panel.py`, `src/company/repository.py`
  - Details: `audit_rules.yaml` 저장 시 `has_custom_rules` 반영 주체를 정한다.
  - Acceptance: rules 저장 후 회사 프로필 플래그와 실제 파일 상태가 일치한다.
  - Size: S

## Phase 4: Verification

- [ ] settings 병합 테스트를 보강한다.
  - File: `tests/test_company/test_merger.py`
  - Details: allowlist, alias normalize, reject 정책 케이스를 추가한다.
  - Acceptance: 정상/legacy/invalid override 케이스가 모두 테스트된다.
  - Size: M

- [ ] context 로딩 회귀 테스트를 추가한다.
  - File: `tests/test_company/test_context.py`
  - Details: 정규화된 override가 `CompanyContext.settings`에 정확히 반영되는지 확인한다.
  - Acceptance: 회사/engagement 우선순위와 alias 변환이 검증된다.
  - Size: M

- [ ] repository 저장 테스트를 추가한다.
  - File: `tests/test_company/test_repository.py`
  - Details: 저장 시 dead key가 남지 않는지 확인한다.
  - Acceptance: company/engagement YAML 저장 후 예상 키만 존재한다.
  - Size: M

- [ ] 문서와 UI smoke 검증을 수행한다.
  - File: `docs/archive/completed/개선사항.md`, dashboard 관련 테스트 또는 import 검증
  - Details: 사용자에게 노출되는 설정 키 이름을 실제 코드와 맞춘다.
  - Acceptance: 문서와 UI 캡션에서 제거된 키명이 사라진다.
  - Size: S

## Deployment Checklist

- [ ] legacy override alias 목록 문서화
- [ ] `company.yaml` / `engagement.yaml` 하위호환 확인
- [ ] settings editor 수동 저장 검증
- [ ] 관련 pytest 통과
- [ ] `docs/archive/completed/개선사항.md` 상태 갱신
