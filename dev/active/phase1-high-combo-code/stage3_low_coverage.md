# 작업: LOW = Coverage Queue 전환 (review queue tier 줄은 HIGH/MEDIUM만)

## 1. 목표
- PHASE1 출력에서 **LOW를 review queue tier 줄에서 빼고**, "룰별 전수 커버리지 숫자표 +
  공통 sort_key drill-down"(HIGH_COMBO_GROUNDING §5 A안)으로 surface 한다.
- 불변식: 한 전표(document)는 HIGH/MEDIUM/LOW 중 **하나의 줄에만** 뜬다(tier 비중첩). 단
  **커버리지 숫자표는 룰 발화를 전수**로 세므로 HIGH/MEDIUM 전표의 룰 발화도 카운트된다(단위가 다른 두 표).
- 성공 기준: §6 검증이 기대 출력으로 끝나고, "LOW 전표가 transaction queue tier 줄에 안 뜨고
  coverage 표에 뜬다 / HIGH 전표는 tier 줄 1번 + 그 전표의 고액 발화가 coverage에도 1번"이 테스트로 증명된다.

## 2. 컨텍스트
- 읽어야 할 파일 (수정 전 반드시):
  - `docs/spec/HIGH_COMBO_GROUNDING.md` §5 전체(L437~469: §5.1 운영정의·§5.2 전수·§5.3 LOW/CONTEXT 경계)
  - `docs/spec/UNIT_MEASUREMENT_POLICY.md` (전표=정답단위, case=집계뷰 정의)
  - `docs/spec/DETECTION_RULES.md` §2.0.2·§2.0.6·§2.0.8 (이미 A안으로 문서 반영됨 — 코드가 따라가야 할 명세)
  - `src/detection/phase1_case_builder.py`, `src/export/phase1_case_view.py`,
    `src/models/phase1_case.py` (queue/tier 조립·노출 지점)
  - dashboard에서 PHASE1 큐를 그리는 파일 (위 export 함수 호출처)
- 따라야 할 기존 패턴: 기존 queue 빌더·case_row 직렬화 함수 형식 그대로. 새 surface는 기존
  build_* 함수와 동일 시그니처·반환형으로.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

### Phase A — 현행 구조 매핑 (편집 전, 보고 후 멈춤 가능)
- 현재 LOW가 어디서 어떻게 큐에 들어가는지 추적: `case_tier`/`primary_queue`/tier 필터가
  LOW를 transaction queue에 포함시키는 코드 경로를 찾아 **파일·함수·줄로 보고**한다.
- 현행 구조가 아래 B 설계와 충돌하면(예: tier 줄과 커버리지가 한 컬렉션에 섞여 분리 불가) 임의
  개조 말고 STATUS: NEEDS_CONTEXT로 그 지점을 보고하고 멈춘다.

### Phase B — 전환 (A 보고가 설계와 정합할 때만)
1. **Transaction(review) queue tier 줄**: `tier in {HIGH, MEDIUM}`인 case만 포함. LOW·CONTEXT 제외.
   기존 tier 필터에서 LOW를 빼는 최소 수정. (case_tier 자체는 유지 — LOW 라벨은 남되 큐 줄에서만 제외.)
2. **Coverage 숫자표(신규 surface)**: 룰ID별 발화 전표 수를 전수로 집계하는 build 함수 추가.
   - 분모/분자 단위 = **전표 발화**(룰이 켜진 전표 수). tier 무관 — HIGH/MEDIUM 전표의 발화도 센다.
   - standalone_rankable=True 인 primary 룰만 행으로 노출(§5.3: CONTEXT=standalone=False는 커버리지
     단독행 제외). booster/macro/combo_only 제외.
3. **drill-down**: 각 룰 숫자 클릭 시 그 룰이 켜진 전표 목록. 정렬은 **HIGH/MEDIUM과 동일한 공통
   sort_key**(stage2 결과 포함: independent_primary → time_severity → 금액 → rule_count). 표시 컬럼은
   각 룰의 기존 근거 필드(`row_annotations`) 재사용 — 신규 컬럼 발명 금지.
4. **비중첩 보장**: transaction queue와 coverage는 다른 표. 같은 전표가 양쪽에 나타나도(HIGH 줄 1번 +
   coverage 발화 1번) 모순 아님(§5.2). 단 transaction queue **내부에서** HIGH/MEDIUM/LOW가 같은 전표를
   중복 노출하지 않을 것(전표당 최고 tier 1줄).

## 4. 단계 체크리스트 (순서 고정)
- [ ] Step 1: Phase A 매핑 보고(LOW 큐 포함 경로 파일·함수·줄). 충돌 시 NEEDS_CONTEXT로 멈춤
- [ ] Step 2: transaction queue tier 필터에서 LOW 제외(최소 수정). 증거: diff + 단위테스트(LOW case가 큐에 없음)
- [ ] Step 3: coverage build 함수 추가(룰별 전수 전표 발화 수, standalone primary만). 증거: diff + 테스트(HIGH 전표의 고액 발화가 coverage에 카운트됨)
- [ ] Step 4: drill-down 정렬 = 공통 sort_key 재사용. 증거: diff + 테스트(정렬 일치)
- [ ] Step 5: dashboard 노출 — coverage 표/HIGH·MEDIUM만 큐. 신규 화면 발명 말고 기존 컴포넌트 재사용. 증거: diff
- [ ] Step 6(마지막): §6 전체 검증
※ 증거 없는 단계는 미수행 간주.

## 5. 금지 사항 (1건이라도 위반 시 실패)
- 하드코딩 금지: 연도·corp_code·룰ID 화이트리스트를 코드에 박지 말 것. coverage 행 대상은
  `standalone_rankable`·`scoring_role` 메타데이터로 판별(rule_scoring.py), 룰ID 나열 금지.
- case/document 혼용 금지: tier는 전표 단위, case는 집계뷰. 라벨·주석에서 둘을 섞지 말 것
  (UNIT_MEASUREMENT_POLICY 준수).
- 3-surface 비병합: PHASE1-2 family·PHASE2 점수와 합치지 말 것. coverage는 PHASE1-1 룰 발화만.
- 테스트 약화 금지(skip/xfail/assert 완화/기대값 출력맞춤). 빈 coverage를 PASS로 두지 말 것
  (hollow-PASS) — coverage 표 최소 1행 이상 기대치를 테스트에 박을 것.
- 범위 밖 수정 금지: 수정 가능 = case_builder·phase1_case_view·models/phase1_case·dashboard PHASE1 큐
  컴포넌트·관련 테스트. topic_scoring.py(stage1)·sort 산식(stage2)은 건드리지 말 것.
- 체크리스트 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수)
- `uv run pytest tests/modules/test_detection/test_phase1_case_builder.py tests/modules/test_export -q`
  → 기대: 0 failed (기존 알려진 실패 N 명시)
- `uv run pytest tests/ -q` → 기대: 신규 0 failed
- 비중첩 회귀: transaction queue의 tier 집합이 {HIGH, MEDIUM} ⊆ 임을 단정하는 테스트 통과
- 한글 깨짐(U+FFFD) 0건.
※ 기대와 다르면 DONE 금지. 원인 미상 BLOCKED.

## 7. 완료 보고 양식 (그대로, 생략 금지)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령+출력 원문)
변경 파일: 경로 목록(변경 안 한 파일 포함 금지)
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려: 정직하게 전부. 없으면 "없음"

> 모든 보고·주석은 한국어로 작성한다.
