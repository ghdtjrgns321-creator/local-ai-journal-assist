# Main UX Cleanup - Context & Decisions

## Status

- Phase: Planning complete
- Progress: 0 / 16 tasks complete
- Last Updated: 2026-04-16

## Key Files

**Target**
- `dashboard/app.py` - 메인 진입점과 탭 조립
- `dashboard/tab_overview.py` - 개요 탭
- `dashboard/tab_phase1.py` - Phase 1 진입/결과
- `dashboard/tab_phase2.py` - Phase 2 진입/결과
- `dashboard/tab_export.py` - 내보내기
- `dashboard/tab_findings.py` - Phase 1 상세 탐색
- `dashboard/components/data_uploader.py` - 업로드/리뷰/파이프라인 스테이지
- `dashboard/components/filters.py` - 공통 필터
- `dashboard/components/preset_selector.py` - 프리셋 선택
- `dashboard/components/threshold_sidebar.py` - 상세 임계값 설정
- `dashboard/components/rule_panel.py` - 룰 on/off
- `dashboard/components/_redetect.py` - 재탐지 적용

**Legacy / Candidate Cleanup**
- `dashboard/tab_explorer.py`
- `dashboard/tab_eda.py`
- `dashboard/tab_benford.py`
- `dashboard/tab_summary.py`
- `dashboard/__init__.py`

**Tests**
- `tests/modules/test_dashboard/*`

## Current Findings

1. 메인 탭은 이미 4개로 줄었지만, 메인 흐름과 제어 흐름이 분리되지 않았다.
   - 현재 `dashboard/app.py`는 `개요 / 데이터 탐색 / 룰 위반 / 이상 탐지`로 구성되어 있다.
   - 하지만 사이드바의 필터/설정/재탐지와 메인 탭의 실행 버튼 관계가 약해 초행 사용자 기준 다음 행동이 분명하지 않다.

2. 개발 모드가 중복 관리된다.
   - `dashboard/app.py`에 `개발 모드` 토글이 있고, `dashboard/components/filters.py`에도 다시 체크박스가 있다.
   - 상태 충돌 가능성은 낮지만 UX와 책임 경계가 흐려진다.

3. 설정 UX는 기능은 많지만 흐름이 약하다.
   - `preset_selector`, `threshold_sidebar`, `rule_panel`, `_redetect`가 모두 탐지 설정의 일부인데 별도 컴포넌트로만 존재한다.
   - 지금은 "무엇을 바꾸는지 / 언제 반영되는지"가 UI 구조만 보고는 직관적이지 않다.

4. 구 탭과 현재 메인 구조가 공존한다.
   - `tab_explorer.py`는 구 explorer 오케스트레이터 역할을 아직 갖고 있고, `tab_eda.py`, `tab_benford.py`, `tab_summary.py`도 잔존한다.
   - 현재 메인 경로는 `tab_data_quality.py`, `tab_overview.py`, `tab_findings.py`, `tab_phase2.py`인데 코드 구조는 과거 탭 체계 흔적이 남아 있다.

5. 배치 복원 UX는 강력하지만 메인 온보딩 메시지가 약하다.
   - `dashboard/app.py`는 이전 배치를 자동 복원하고, 없으면 업로드로 보낸다.
   - 하지만 사용자에게 "지금 보고 있는 것이 복원 결과인지, 새 업로드인지, 무엇을 다음에 해야 하는지"를 더 분명히 말해줄 여지가 있다.

## Key Decisions

1. **메인 탭은 핵심 흐름 중심으로 유지한다** (2026-04-16)
   - Rationale: 3.7의 핵심은 기능 제거가 아니라 진입 흐름 명확화다.
   - Alternatives: 새 multipage 구조로 크게 전환
   - Trade-offs: 변경량은 줄지만 기존 탭 안에서 카피와 구조를 더 신중히 정리해야 한다.

2. **개발/실험 기능은 메인 탐색 흐름에서 분리한다** (2026-04-16)
   - Rationale: 사용자가 먼저 봐야 하는 것은 분석 결과와 다음 행동이지 개발용 필터가 아니다.
   - Alternatives: 모든 기능을 항상 노출
   - Trade-offs: 내부 디버깅에는 클릭이 하나 늘지만 메인 UX는 훨씬 선명해진다.

3. **사이드바는 “필터”와 “설정”을 분리된 책임으로 보이게 한다** (2026-04-16)
   - Rationale: 현재 둘 다 같은 레벨에 섞여 있어 탐색용 조작과 재탐지용 조작의 차이가 흐려진다.
   - Alternatives: 현 구조 유지
   - Trade-offs: 일부 컴포넌트 래핑이 늘지만 사용자는 더 쉽게 이해한다.

4. **구 탭은 1차로 legacy 표시 후 정리한다** (2026-04-16)
   - Rationale: 바로 삭제하면 참조 경로 누락 리스크가 있다.
   - Alternatives: 즉시 삭제
   - Trade-offs: 코드 정리는 한 단계 늦지만 회귀 위험이 줄어든다.

## Proposed UX Boundary

- Main flow
  - 회사/engagement 선택
  - 배치 복원 또는 파일 업로드
  - 개요 확인
  - Phase 1 실행/검토
  - Phase 2 실행/검토
  - Export

- Supporting controls
  - 데이터 필터
  - 탐지 설정
  - 설정 적용

- Dev / experimental
  - 개발 모드 토글
  - 개발 전용 필터
  - legacy/실험 탭 또는 보조 화면

## Known Issues

- `dashboard/tab_findings.py`는 최근 `tab_explorer.py`의 일부 흐름을 흡수했지만, legacy 탐색 경로가 아직 코드로 남아 있다.
- `dashboard/components/filters.py`는 필터 렌더 외에 dev_mode 상태 변경까지 맡고 있어 SRP가 약하다.
- `dashboard/app.py`는 현재도 orchestration 이상 역할을 하고 있다. 회사 선택, 배치 복원, 헤더 렌더, 탭 구성, 사이드바 구성까지 한 파일에 몰려 있다.

## Open Questions To Resolve During Implementation

- 메인 탭에 `Export`를 직접 넣을지, 결과가 있을 때만 보이는 보조 탭으로 둘지
- `탐지 설정`을 사이드바에 유지할지, 메인 상단의 별도 panel로 옮길지
- `tab_explorer.py`를 완전 제거할지, dev-only fallback으로 남길지
- `데이터 탐색` 탭 명칭을 유지할지, `데이터 품질` 또는 `데이터 이해`로 바꿀지
