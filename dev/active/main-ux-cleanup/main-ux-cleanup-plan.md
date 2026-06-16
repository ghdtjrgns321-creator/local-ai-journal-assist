# Main UX Cleanup - Strategic Plan

## Executive Summary

`## 3.7 메인 UX 정리`의 목표는 현재 기능은 유지하면서도 사용자가 따라야 할 핵심 흐름을 더 분명하게 만드는 것이다. 이번 작업은 메인 화면의 정보구조를 "회사 선택 → 배치 선택/업로드 → 개요 → Phase 1 → Phase 2 → Export" 순서로 다시 정리하고, 실험성/개발성 기능은 메인 흐름 밖으로 분리하는 데 초점을 둔다.

## Current State

- `dashboard/app.py`는 실제 메인 탭을 `개요 / 데이터 탐색 / 룰 위반 / 이상 탐지` 4개로 이미 압축했지만, 사이드바에 필터, 탐지 설정, 재탐지 적용이 한꺼번에 붙어 있어 초행 사용자 관점에서는 우선순위가 흐려진다.
- `dashboard/tab_phase1.py`와 `dashboard/tab_phase2.py`는 각각 실행 버튼과 결과 화면을 가지지만, 배치 선택/재탐지/설정 적용 흐름과 시각적으로 분리되어 있지 않다.
- `dashboard/components/filters.py` 안에 `개발 모드` 토글이 다시 있고, `dashboard/app.py` 사이드바에도 같은 토글이 있어 dev 기능 노출이 중복된다.
- `dashboard/components/preset_selector.py`, `threshold_sidebar.py`, `rule_panel.py`, `_redetect.py`는 모두 핵심 탐지 설정 UX에 속하지만 현재는 느슨하게 조합되어 있어 "무엇을 바꾸고 언제 적용되는지"가 직관적이지 않다.
- `dashboard/tab_explorer.py`, `tab_eda.py`, `tab_benford.py`, `tab_summary.py` 같은 구/보조 탭 파일이 남아 있어 메인 진입점 기준 정보구조와 코드 구조가 어긋난다.
- `dashboard/components/data_uploader.py`는 업로드/리뷰/파이프라인 실행 스테이지를 잘 가지고 있지만, 메인 화면 전체 흐름 문구와 연결된 onboarding copy는 약하다.

## Proposed Solution

메인 UX를 아래 4개 영역으로 재조립한다.

1. Entry flow
   - 회사/engagement 선택과 배치 복원/파일 업로드를 메인 상단 진입 흐름으로 명확히 고정한다.
   - 현재 분석 중인 배치, 파일명, 복원 여부, 다시 업로드 액션을 한 덩어리로 보여준다.

2. Main tabs
   - 메인 탭은 핵심 사용 흐름만 남긴다.
   - 권장 구조:
     - `개요`
     - `데이터 탐색`
     - `Phase 1`
     - `Phase 2`
     - `Export`
   - Phase 1/2는 각각 "실행 전 상태"와 "실행 후 결과"를 같은 탭 안에서 자연스럽게 이어준다.

3. Control surfaces
   - 필터는 분석 탐색용, 탐지 설정은 재탐지용으로 분리한다.
   - 설정 UI는 `프리셋 -> 상세 기준 -> 룰 on/off -> 적용` 한 흐름으로 묶고, 사이드바 또는 별도 expander 안에서 역할을 명확히 나눈다.
   - 개발 모드와 실험 기능은 메인 영역이 아니라 dev 섹션에서만 보이게 한다.

4. Code structure cleanup
   - `app.py`는 orchestration만 담당하고, 헤더/배치 상태/메인 탭 조립/사이드바 조립을 별도 helper/component로 분리한다.
   - 현재 메인에서 쓰이지 않는 구 탭은 제거 또는 dev-only/legacy로 명시한다.

## Implementation Phases

### Phase 1: UX Inventory And IA Freeze (0.5 day)
**Goal**: 메인 UX의 최종 정보구조와 책임 경계를 확정한다.

- [ ] 현재 메인/구 탭 사용 현황 정리 - File: `dashboard/app.py`, `dashboard/tab_*` - Size: S
- [ ] 핵심 흐름 vs 실험/개발 기능 분류표 작성 - File: `dev/active/main-ux-cleanup/main-ux-cleanup-context.md` - Size: S
- [ ] 최종 메인 탭 구성 고정 - File: `dashboard/app.py` - Size: S

### Phase 2: App Shell Cleanup (0.5-1 day)
**Goal**: 메인 화면 조립 책임을 분리하고 배치 상태 헤더를 정리한다.

- [ ] 메인 헤더/배치 상태 블록 helper 분리 - File: `dashboard/app.py`, `dashboard/components/*` - Size: M
- [ ] 결과 복원/업로드 후 진입 문구 정리 - File: `dashboard/app.py`, `dashboard/components/data_uploader.py` - Size: M
- [ ] 메인 탭에 `Export` 포함 여부 반영 및 조립 정리 - File: `dashboard/app.py` - Size: M

### Phase 3: Sidebar And Control Flow Simplification (1 day)
**Goal**: 필터/설정/재탐지/dev 기능을 역할별로 분리한다.

- [ ] `개발 모드` 토글 단일화 - File: `dashboard/app.py`, `dashboard/components/filters.py` - Size: S
- [ ] 필터 섹션과 탐지 설정 섹션 역할 분리 - File: `dashboard/app.py`, `dashboard/components/filters.py` - Size: M
- [ ] `프리셋 -> 상세 기준 -> 룰 on/off -> 설정 적용` 순서 재배치 - File: `dashboard/components/preset_selector.py`, `dashboard/components/threshold_sidebar.py`, `dashboard/components/rule_panel.py`, `dashboard/components/_redetect.py` - Size: L
- [ ] DB 복원 배치에서 설정 수정 불가 메시지/상태 표시 개선 - File: `dashboard/app.py` - Size: S

### Phase 4: Main Tab Copy And Empty State Cleanup (0.5-1 day)
**Goal**: 메인 탭이 현재 단계와 다음 액션을 더 분명히 안내하게 한다.

- [ ] `개요` 탭의 pre-analysis 안내 문구 강화 - File: `dashboard/tab_overview.py` - Size: S
- [ ] `Phase 1` 실행 전/후 화면 톤 정리 - File: `dashboard/tab_phase1.py`, `dashboard/tab_findings.py` - Size: M
- [ ] `Phase 2`를 실험 기능이 아닌 보조 심화 분석으로 설명 정리 - File: `dashboard/tab_phase2.py` - Size: M
- [ ] `Export` 탭 진입 위치와 copy를 메인 흐름에 맞게 조정 - File: `dashboard/tab_export.py`, `dashboard/app.py` - Size: S

### Phase 5: Legacy/Dev Surface Cleanup (0.5 day)
**Goal**: 메인에서 쓰이지 않는 탭/경로를 정리해 코드 구조와 UX 구조를 맞춘다.

- [ ] `tab_explorer.py`의 역할 결정 (삭제, legacy 표시, dev-only) - File: `dashboard/tab_explorer.py` - Size: S
- [ ] `tab_eda.py`, `tab_benford.py`, `tab_summary.py` 잔존 경로 정리 - File: `dashboard/__init__.py`, 관련 탭 파일 - Size: M
- [ ] dev 전용 기능 노출 규칙 문서화 - File: `dev/active/main-ux-cleanup/main-ux-cleanup-context.md` - Size: S

### Phase 6: Verification And Docs (0.5 day)
**Goal**: 새 메인 UX 흐름을 테스트와 문서로 고정한다.

- [ ] app/tab smoke 테스트 추가 또는 갱신 - File: `tests/modules/test_dashboard/*` - Size: M
- [ ] 메인 탭 순서/노출 조건 검증 추가 - File: `tests/modules/test_dashboard/*` - Size: M
- [ ] `docs/archive/completed/개선사항.md` 상태 갱신 - File: `docs/archive/completed/개선사항.md` - Size: S

## Risk Assessment

- **High Risk**: 탭 재배치 중 기존 session_state 흐름이 깨지면 배치 복원/재탐지 UX가 회귀할 수 있다.
  - Mitigation: 탭 구성 변경 전에 현재 state key 사용처를 고정하고 smoke 테스트를 추가한다.
- **Medium Risk**: `Export`를 메인 탭에 포함하면 화면이 다시 복잡해질 수 있다.
  - Mitigation: export는 탭으로 두되 내부 UI는 2-step 생성/다운로드 구조를 유지하고 고급 옵션은 접어둔다.
- **Medium Risk**: 구 탭 파일을 바로 제거하면 의존 import가 남아 런타임 오류가 날 수 있다.
  - Mitigation: 먼저 참조 경로를 검색해 끊고, 1차는 legacy 표시만 한 뒤 제거한다.
- **Medium Risk**: 개발 모드 토글을 단일화하면서 기존 필터 UI 테스트가 깨질 수 있다.
  - Mitigation: `filters.py`는 dev 필터 노출만 담당하고 dev_mode state 소유권은 `app.py`로 고정한다.

## Success Metrics

- 메인 탭이 핵심 흐름 중심으로 고정된다.
- 개발 모드 토글이 한 곳에서만 관리된다.
- 필터와 탐지 설정의 역할 차이가 UI 구조로 드러난다.
- 배치 선택/복원/재업로드/재탐지 흐름이 한 화면에서 이해 가능하다.
- 테스트:
  - dashboard smoke/import 테스트 통과
  - 탭 노출/상태 전환 테스트 추가

## Dependencies

- Code:
  - `dashboard/app.py`
  - `dashboard/tab_overview.py`
  - `dashboard/tab_phase1.py`
  - `dashboard/tab_phase2.py`
  - `dashboard/tab_export.py`
  - `dashboard/tab_findings.py`
  - `dashboard/components/data_uploader.py`
  - `dashboard/components/filters.py`
  - `dashboard/components/preset_selector.py`
  - `dashboard/components/threshold_sidebar.py`
  - `dashboard/components/rule_panel.py`
  - `dashboard/components/_redetect.py`
- State contracts:
  - `dashboard/_state.py`
  - `KEY_*_RESULT`, `KEY_DEV_MODE`, `KEY_SELECTED_DOC`
