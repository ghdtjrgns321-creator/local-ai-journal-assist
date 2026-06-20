# 작업: dashboard(tab_phase1.py)가 unit 검토 큐·커버리지 표를 소비하도록 전환

## 1. 목표
- PHASE1 대시보드의 **주 검토 큐 화면**이 stage3a `build_phase1_transaction_queue`(전표/흐름 단위)를
  그리게 하고, LOW는 `build_phase1_rule_coverage`(룰별 전수 커버리지 표)로 별도 노출한다. case 집계뷰는
  보조 grouping 표시로 유지(주 큐 자리 아님).
- 성공 기준: §6 검증 통과 + 대시보드 import/렌더 스모크가 깨지지 않고, 주 큐가 unit 행, LOW가 커버리지
  화면에 뜸을 테스트/스모크로 증명.

## 2. 컨텍스트
- 읽어야 할 파일 (수정 전 반드시):
  - stage3a·3b 산출물(unit 큐·커버리지·집계뷰 전환 결과)
  - `dashboard/tab_phase1.py`: `render()`, 큐/그리드 렌더 함수(`_display_case_row` L1697 등),
    `build_phase1_*` 호출 체인
  - `docs/spec/HIGH_COMBO_GROUNDING.md` §5(LOW=Coverage 화면), `docs/guide/ux-flow.md`(상태 문구 기준)
- 따라야 할 기존 패턴: 기존 탭 렌더 구조·컴포넌트(st.dataframe/aggrid 등) 재사용. **신규 화면 프레임워크
  발명 금지.** 기존 큐 그리드를 unit 행 소스로 바꾸는 최소 수정 + 커버리지 표는 기존 표 컴포넌트 재사용.
- 배경: Streamlit kill·재시작·캐시정리 **자동 실행 금지**(사용자 직접 통제). import 스모크까지만.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

### Phase A — 렌더 경로 매핑 (편집 전 보고)
`render()`가 주 검토 큐를 그리는 정확한 지점(함수:줄)과, 거기 들어가는 데이터 소스(현재 case 큐 빌더)를
보고하라. 커버리지 표를 끼울 위치(기존 탭/섹션)도 지목. 구조가 예상과 다르면 NEEDS_CONTEXT.

### Phase B — 전환
1. 주 검토 큐 그리드의 데이터 소스를 `build_phase1_transaction_queue`로 교체. 행 키가 unit_id가 되도록
   컬럼 매핑 조정(unit_type·priority_band·time_severity_score·total_amount·발화룰).
2. **Coverage 화면 신설**: `build_phase1_rule_coverage` 결과를 룰별 숫자표로 표시(룰ID·전표 발화 수·tier 분해).
   숫자 클릭 drill-down은 stage3a 공통 sort_key 순서. 기존 표 컴포넌트 재사용, 신규 UI 프레임워크 금지.
3. case 집계뷰(사용자×월·계정×월·topic 요약)는 **보조 섹션**으로 유지(주 큐 자리 아님). 라벨에서
   case/document 혼용 금지(주 큐=전표/흐름, 집계뷰=묶음 표시).
4. 상태 문구: LOW를 "위험 없음"이 아니라 "전수 커버리지 집계 대상"으로(§5·ux-flow 기준).

## 4. 단계 체크리스트 (순서 고정)
- [ ] Step 1: Phase A 렌더 경로 매핑 보고. 구조 상이 → NEEDS_CONTEXT
- [ ] Step 2: 주 큐 소스 unit 큐로 교체. 증거: diff
- [ ] Step 3: Coverage 화면 신설(기존 표 컴포넌트 재사용). 증거: diff
- [ ] Step 4: case 집계뷰 보조 유지 + 라벨 단위 일관. 증거: diff
- [ ] Step 5(마지막): §6 검증(import 스모크 + 테스트)
※ 증거 없는 단계는 미수행 간주.

## 5. 금지 사항 (1건이라도 위반 시 실패)
- Streamlit 프로세스 kill·재시작·캐시클리어 자동 실행 금지(사용자 통제). import 스모크까지만.
- 신규 UI 프레임워크/컴포넌트 발명 금지 — 기존 st 컴포넌트 재사용.
- case/document 단위 라벨 혼용 금지. 3-surface(PHASE1-2·PHASE2) 점수 병합 금지.
- band 문자 리터럴 분기 금지(`_band_rank` 경유). 룰ID 화이트리스트 금지.
- stage3a·3b 함수 시그니처 변경 금지(여기선 소비만).
- 테스트 약화 금지. 범위: `dashboard/tab_phase1.py`(+ 직접 보조 모듈), 관련 테스트. export/builder는 건드리지 말 것.
- 체크리스트 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수)
- import 스모크: `uv run python -c "import dashboard.tab_phase1"` → 기대: 에러 없음(0 exit)
- `uv run pytest tests/ -q -k "phase1 or dashboard or tab"` → 신규 0 failed (기존 알려진 실패 N 명시)
- 직접 재현(2+ 케이스): 합성 PipelineResult로 render 보조 함수 호출 시 (a) 주 큐 행에 unit_id, (b) 커버리지
  표에 룰 행 ≥1 — print/test 확인
- 한글 깨짐(U+FFFD) 0건.
※ 기대와 다르면 DONE 금지. 렌더 구조 상이 NEEDS_CONTEXT.

## 7. 완료 보고 양식 (그대로, 생략 금지)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령+출력 원문)
변경 파일: 경로 목록(변경 안 한 파일 포함 금지)
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려: 정직하게 전부. 없으면 "없음"

> 모든 보고·주석은 한국어로 작성한다.
