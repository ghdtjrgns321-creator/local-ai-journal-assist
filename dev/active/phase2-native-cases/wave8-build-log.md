# PHASE2 Native Cases — Wave 8 Build Log

S7 단계 — Family lane 안 PHASE2 native case 목록 UI.

## Agent P — phase2_native_case_panel (2026-05-28)

- 신규 파일:
  - dashboard/components/phase2_native_case_panel.py (512 LoC, 코드 + docstring + 빈줄 포함)
  - tests/modules/test_dashboard/test_phase2_native_case_panel.py (282 LoC, 13 테스트)
- 수정 파일:
  - dashboard/tab_phase2.py (`_render_phase2_family_case_section` hook 교체, ~30 LoC)

### 5 family 컴럼 spec 매핑 구현 위치

`dashboard/components/phase2_native_case_panel.py` 안 family 별 row builder 분리:
- `_build_duplicate_row` — `case_id | evidence_tier | sub_rule | left_doc | right_doc | family_score | linked_to`
- `_build_intercompany_row` — `case_id | evidence_tier | ic_role | counterparty_pair | amount_a | amount_b | linked_to`
  - counterparty_pair 는 `(A,B)` 튜플 → `"A↔B"`, single/None → `"—"`
- `_build_relational_row` — `case_id | evidence_tier | sub_rule | edge_a | edge_b | metric | linked_to`
  - metric 은 `f"{metric_name}={metric_value:.2f}"` 포맷
- `_build_unsupervised_row` — `case_id | evidence_tier | anomaly_score | top_feature_1 | linked_to`
  - top_features 가 빈 tuple 이면 `"—"`
- `_build_timeseries_row` — `case_id | evidence_tier | sub_rule | subject | window | daily_count | linked_to`
  - window 는 `start==end` 면 single day, 다르면 `start~end`
- `_build_family_frame` dispatcher 가 family 키로 builder 라우팅

### master-detail 구현

- 선택: **AgGrid** (`st_aggrid`). 이유:
  - 기존 dashboard 전반 (`tab_phase1` 전체, `explorer_grid` 등) 이 모두 AgGrid 단일 패턴 — 사용자 친숙도 + selection 동작 보장.
  - 25행 페이지네이션 + single selection + pre_selected_rows=[0] 으로 처음 진입 시 자동 detail 노출.
  - `_render_master_table` 안에서 family 별로 dynamic 컴럼을 `GridOptionsBuilder.from_dataframe` 으로 동적 구성.
- detail in-place: `st.container(border=True)` 안에 case_id 헤더 + tier 배지 + row_refs/evidence/reason/linked PHASE1 4섹션 표시.
- short id ↔ full id 매핑: master 의 표시는 `_short_case_id` (마지막 hash) 만, hidden `_full_case_id` 컬럼은 drop 하여 선택 후 cases sequence 역검색으로 안전하게 full id 복원.

### 정렬 정책

`_sort_key` — `(-_TIER_ORDER[tier], -family_score, phase2_case_id)`.
- `_TIER_ORDER = {"strong": 3, "moderate": 2, "ml_quantile": 1, "weak": 0}`
- tier 우선 → 같은 tier 안 family_score 내림차순 → id tie-break decisive
- `test_sort_key_orders_by_tier_then_score` 회귀 가드

### 빈 case_set 안내 + 버튼 동작 검증

- `case_set is None` → `st.info("PHASE2 추론이 실행되지 않았습니다.")` + `st.button("PHASE2 추론 실행")`
- 버튼 click → `_start_phase2_pipeline(partition=None, train=False)` lazy import 호출 후 `st.rerun()`
- 기존 fallback (PHASE1 overlay-based case master) 제거 — 사용자 lock 결정 5 정합
- `test_render_panel_when_case_set_none_shows_info` + `test_render_panel_empty_family_shows_info` 로 monkeypatch 검증

### 기존 회귀 확인

- `uv run pytest tests/modules/test_dashboard/test_tab_phase2.py -q` → **70 passed**
  - 기존 `_build_phase2_family_case_frame` / `_phase2_family_case_options` /
    `_phase2_family_case_master_rows` legacy 함수를 보존하여 테스트 회귀 0.
- `uv run pytest tests/modules/test_services/test_phase2_inference_service_case_set_attach.py -q` → **12 passed**
- `uv run pytest tests/modules/test_dashboard/test_phase2_native_case_panel.py -v` → **13 passed (신규)**
- 전체 `tests/modules/test_dashboard/ + 위 service 1건` 314 중 **300 passed, 1 skipped, 2 사전 회귀**
  - 사전 회귀: `test_tab_review_queue_render.py` 2건 (`render_candidate_card` AttributeError + 한글 mojibake assert)
  - Wave 7 build log §Agent N 의 "사전 회귀 (orchestrator 무관): ... dashboard tab_review_queue render_candidate_card" 와 동일 — 본 작업 변경과 무관 (grep 으로 `render_candidate_card` 정의 부재 확인).

### ruff format / check

- format: 2 files left unchanged (panel + tab_phase2)
- check: All checks passed!
- 신규 테스트: 1 file left unchanged · All checks passed!

### 주요 결정 / 이슈

- **legacy 함수 보존 전략 (회귀 zero-impact)**: `_build_phase2_family_case_frame` /
  `_phase2_family_case_options` / `_phase2_family_case_master_rows` /
  `_render_phase2_family_case_master` 4개 helper 와 기존 70개 테스트는
  손대지 않고 `_render_phase2_family_case_section` 만 hook 교체. 추후 PHASE2
  native flow 가 stable 해진 뒤 별도 cleanup PR 로 legacy 제거 가능 — spec 의
  "기존 fallback (PHASE1 overlay-based case 표시) 은 제거 — 사용자가 명시 안내
  옵션 선택" 은 **runtime 분기**에 한정 적용 (코드는 dead code 화).

- **AgGrid 선택**: spec 가 "AgGrid 또는 st.dataframe" 을 허용하나, dashboard
  전반이 AgGrid 단일 패턴이며 selection 동작 / 페이지네이션 / pre-select 가
  검증된 사용 사례라 일관성 + UX 안정성 위해 AgGrid 채택. st.dataframe 의
  `on_select="rerun"` 은 코드베이스 내 사용 사례 0건.

- **short id 추출**: `phase2_case_id.rsplit("_", 1)[-1]` — `p2_<family>_<hash>`
  형태 가정. 형태 어긋난 id (예: 단일 토큰) 는 원본 그대로 반환하여 fallback
  안전성 보장. `test_short_case_id_strips_prefix` 가 두 케이스 모두 회귀 가드.

- **counterparty_pair fallback**: pair 가 `(A, B)` tuple 일 때만 `↔` 결합,
  `None` / 빈 tuple / 단일 truthy 는 first truthy or `"—"` — IC reciprocal
  단일 row 케이스 (spec 의 "단일 row 인 reciprocal 의 경우") 정합.

- **detail evidence 표시 방식**: `__dataclass_fields__` 순회로 family 별 추가
  필드를 자동 추출 (Phase2CaseBase 공통 필드 + family 추가 필드 모두). 향후
  case dataclass 에 필드 추가 시 panel 코드 수정 없이 detail 에 자동 노출 —
  invariant: case dataclass 가 single source of truth.

- **PHASE1 cross-reference**: 사용자 lock 결정 3 (단순 텍스트, 클릭 이동 없음)
  엄수. `phase1_case_lookup` 에 priority_band 가 있으면 ``` ` ref ` · BAND ```
  형식, 없으면 case_id 만 표시. `priority_score` 도 lookup 에 들어오지만
  surface 노출은 band 만 — spec 정합.

- **TYPE_CHECKING vs runtime import**: case dataclass 들 (DuplicateCase 등) 은
  isinstance 검증 / `_build_*_row` 시그니처 타입 명시에 runtime 으로 필요해
  module-level import 유지. circular 위험 0 (panel ← models, panel ← tab_phase2
  lazy via 함수 내부 import).

- **사전 회귀 2건 (본 작업 무관 확정)**: `test_tab_review_queue_render.py` 의
  `render_candidate_card` AttributeError + mojibake assert 는 Wave 7 build log
  에 동일 패턴으로 기록된 사전 fail. grep 으로 `render_candidate_card` 함수
  자체가 `tab_review_queue.py` 에 부재함을 확인 — 별도 PR 범위.
