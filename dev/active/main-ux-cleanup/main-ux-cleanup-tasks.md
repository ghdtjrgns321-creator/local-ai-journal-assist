# Main UX Cleanup - Task Checklist

## Progress Summary

0 / 16 tasks complete (0%)

## Phase 1: Information Architecture

- [ ] 현재 메인 탭과 잔존 탭의 사용 경로를 정리한다.
  - File: `dashboard/app.py`, `dashboard/tab_*`
  - Details: 현재 메인에서 실제 렌더되는 탭과 legacy 탭을 구분해 목록화한다.
  - Acceptance: 유지/legacy/dev-only 대상 파일이 구분된다.
  - Size: S

- [ ] 핵심 흐름과 보조/실험 기능을 분류한다.
  - File: `dev/active/main-ux-cleanup/main-ux-cleanup-context.md`
  - Details: 회사 선택, 업로드, Phase 1/2, export와 dev 기능의 경계를 명시한다.
  - Acceptance: 메인에 남길 기능 목록이 고정된다.
  - Size: S

- [ ] 최종 메인 탭 순서를 확정한다.
  - File: `dashboard/app.py`
  - Details: 메인 흐름 기준 탭 목록과 표시 조건을 확정한다.
  - Acceptance: 탭 구조 변경안이 코드 수준 경로로 정리된다.
  - Size: S

## Phase 2: App Shell Cleanup

- [ ] 배치 상태 헤더 렌더링을 helper로 분리한다.
  - File: `dashboard/app.py`, `dashboard/components/*`
  - Details: 파일명, 행 수, 복원 상태, "다른 파일 분석" 액션을 한 블록으로 분리한다.
  - Acceptance: `app.py`에서 헤더 조립 코드가 줄고 책임이 분리된다.
  - Size: M

- [ ] 결과 복원/업로드 진입 문구를 정리한다.
  - File: `dashboard/app.py`, `dashboard/components/data_uploader.py`
  - Details: DB 복원 상태와 새 업로드 상태를 사용자 문구로 구분해 보여준다.
  - Acceptance: 사용자가 현재 데이터 출처와 다음 행동을 이해할 수 있다.
  - Size: M

- [ ] 메인 탭 조립부를 단순화한다.
  - File: `dashboard/app.py`
  - Details: tab import와 tab render를 핵심 흐름 순서로 정리한다.
  - Acceptance: 메인 렌더 블록이 읽기 쉬운 순서로 재배치된다.
  - Size: M

## Phase 3: Sidebar Responsibilities

- [ ] 개발 모드 토글 소유권을 `app.py`로 고정한다.
  - File: `dashboard/app.py`, `dashboard/components/filters.py`
  - Details: 필터 컴포넌트 안의 dev mode 체크박스를 제거하고 읽기 전용으로 바꾼다.
  - Acceptance: dev_mode 상태를 쓰는 곳은 하나만 남는다.
  - Size: S

- [ ] 필터 섹션을 탐색 전용으로 정리한다.
  - File: `dashboard/app.py`, `dashboard/components/filters.py`
  - Details: 데이터 필터는 현재 결과를 좁히는 용도만 담당하게 한다.
  - Acceptance: 필터 섹션 안에 설정/재탐지 조작이 남아 있지 않다.
  - Size: M

- [ ] 탐지 설정 섹션 순서를 정리한다.
  - File: `dashboard/components/preset_selector.py`, `dashboard/components/threshold_sidebar.py`, `dashboard/components/rule_panel.py`
  - Details: 프리셋, 상세 임계값, 룰 토글이 사용자 관점 순서로 나타나게 래핑한다.
  - Acceptance: 설정 UI가 위에서 아래로 읽을 때 자연스럽다.
  - Size: L

- [ ] 설정 적용 CTA를 설정 섹션의 끝으로 고정한다.
  - File: `dashboard/components/_redetect.py`, `dashboard/app.py`
  - Details: "무엇을 바꿨는지"와 "언제 적용되는지"가 한 흐름으로 보이게 한다.
  - Acceptance: 설정 섹션 끝에서 바로 재탐지 적용 버튼이 보인다.
  - Size: M

- [ ] DB 복원 상태에서 설정 비활성 안내를 개선한다.
  - File: `dashboard/app.py`
  - Details: 원본 파일 재업로드가 필요한 이유를 더 구체적으로 보여준다.
  - Acceptance: 복원 배치에서 설정 불가 상태가 혼동 없이 표시된다.
  - Size: S

## Phase 4: Tab Copy And Empty States

- [ ] 개요 탭의 pre-analysis 안내를 보강한다.
  - File: `dashboard/tab_overview.py`
  - Details: 준비 완료 후 다음 행동이 `Phase 1` 또는 `Phase 2` 실행임을 더 분명히 쓴다.
  - Acceptance: 분석 전 상태에서 다음 액션이 바로 읽힌다.
  - Size: S

- [ ] Phase 1 실행 전/후 카피를 정리한다.
  - File: `dashboard/tab_phase1.py`, `dashboard/tab_findings.py`
  - Details: 실행 전에는 룰 기반 분석 가치와 버튼 의미를, 실행 후에는 탐색 중심 흐름을 강조한다.
  - Acceptance: 같은 탭 안에서 상태 전환이 자연스럽다.
  - Size: M

- [ ] Phase 2 설명 톤을 조정한다.
  - File: `dashboard/tab_phase2.py`
  - Details: 실험성은 숨기지 않되 메인 흐름을 방해하지 않도록 보조 심화 분석으로 설명한다.
  - Acceptance: 사용자가 Phase 2를 "별도 실험 탭"이 아니라 후속 분석 단계로 이해한다.
  - Size: M

- [ ] Export 탭의 메인 흐름 문구를 정리한다.
  - File: `dashboard/tab_export.py`
  - Details: 결과 전달 단계라는 역할이 분명하게 드러나도록 상단 문구를 정리한다.
  - Acceptance: export 진입 목적이 한눈에 보인다.
  - Size: S

## Phase 5: Legacy Cleanup

- [ ] `tab_explorer.py` 처리 방침을 적용한다.
  - File: `dashboard/tab_explorer.py`
  - Details: legacy 유지, dev-only 표시, 삭제 중 하나로 정리한다.
  - Acceptance: 메인 경로와 중복 역할이 남아 있지 않다.
  - Size: S

- [ ] 잔존 구 탭 참조를 정리한다.
  - File: `dashboard/__init__.py`, 관련 `dashboard/tab_*.py`
  - Details: 현재 메인 UX와 맞지 않는 탭 참조를 정리한다.
  - Acceptance: 코드 구조가 실제 UI 구조와 맞는다.
  - Size: M

## Phase 6: Verification

- [ ] 메인 탭 노출/상태 전환 테스트를 추가한다.
  - File: `tests/modules/test_dashboard/*`
  - Details: 결과 없음, 준비 완료, Phase 1 실행 후, Phase 2 실행 후 상태를 검증한다.
  - Acceptance: 주요 state 전환이 테스트로 고정된다.
  - Size: M

- [ ] import/smoke 검증을 추가한다.
  - File: `tests/modules/test_dashboard/*` 또는 수동 smoke 명령
  - Details: `dashboard.app`와 핵심 탭/컴포넌트 import가 유지되는지 확인한다.
  - Acceptance: UX 정리 후 런타임 import 오류가 없다.
  - Size: S

- [ ] 문서 상태를 갱신한다.
  - File: `docs/개선사항.md`
  - Details: 구현 기준으로 3.7 상태와 핵심 변경 내용을 반영한다.
  - Acceptance: 문서와 실제 UI 구조가 어긋나지 않는다.
  - Size: S

## Deployment Checklist

- [ ] 메인 탭 순서가 고정되었다.
- [ ] 개발 모드 토글이 한 곳으로 정리되었다.
- [ ] 설정 적용 흐름이 한 섹션으로 묶였다.
- [ ] legacy 탭 처리 방침이 반영되었다.
- [ ] dashboard 관련 테스트와 import smoke가 통과했다.
