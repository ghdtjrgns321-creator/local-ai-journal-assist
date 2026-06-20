# 작업: case를 집계뷰로 강등 — case.priority_band를 truth 정렬축에서 제거

## 1. 목표
- 기존 case 기반 검토 큐 빌더들이 `case.priority_band`를 **주 정렬·필터 truth 축**으로 쓰던 것을 멈춘다.
  주 검토 큐는 stage3a의 `build_phase1_transaction_queue`(unit 단위)가 담당한다. 남는 case 뷰는
  **집계뷰**(GROUP BY 표시 레이어)로서, 자기 band가 아니라 **소속 unit 등급의 카운트/합**을 보여준다.
- 근거 SoT: `UNIT_MEASUREMENT_POLICY.md` §5(집계뷰는 자기 점수·분모 없음)·§8(집계뷰를 정답 분모로 쓰지 않음).
- 성공 기준: §6 검증 통과 + "주 검토 큐가 unit 기반이고, case 집계뷰의 숫자는 소속 unit 등급 카운트"가
  테스트로 증명. case.priority_band가 어떤 **주 검토 큐**의 정렬 truth 축으로도 안 쓰임.

## 2. 컨텍스트
- 읽어야 할 파일 (수정 전 반드시):
  - `docs/spec/UNIT_MEASUREMENT_POLICY.md` §5·§8
  - stage3a 산출물(`build_phase1_transaction_queue`·`build_phase1_rule_coverage`·`_unit_sort_key`·`_unit_row`)
  - `src/export/phase1_case_view.py`의 case 큐 빌더: `build_phase1_case_queue`(L314), `build_phase1_audit_risk_queue`(L1964),
    `build_phase1_audit_risk_by_queue`(L2040), `build_phase1_topic_top_n`(L2026 부근), `build_phase1_review_candidate_summary`(L2085),
    `_topic_summaries`(L2602)
  - `_band_rank`(L2890), `_case_row`(L2291)
- 따라야 할 기존 패턴: 집계뷰 카운트는 stage3a의 unit 집계(`build_phase1_rule_coverage`)와 동일 단위 기준.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

### Phase A — 분류 (편집 전 보고)
위 case 큐 빌더 각각을 **둘 중 하나로 분류**해 보고하라(파일:줄 + 분류 근거):
- **(가) 주 검토 큐 역할** → stage3a unit 큐로 대체/위임. 호출부가 unit 큐를 쓰도록 전환(또는 deprecated).
- **(나) 집계뷰 역할**(사용자×월·계정×월·topic 요약 등) → 유지하되 표시 숫자를 **소속 unit 등급 카운트**로
  바꾼다(case.priority_band를 정렬 truth 축으로 쓰지 않음. 표시용 파생값으로만, max(member unit band) 허용).
분류가 모호하거나 (가)인데 unit 큐로 대체 시 호출부 영향이 큰 함수가 있으면 STATUS: NEEDS_CONTEXT로 멈춰 보고.

### Phase B — 전환 (분류 확정 후)
0. **resolver 게이트 정비(stage3a 인계)**: `resolve_phase1_case_result`가 `cases`가 비면 None을 반환해
   `build_phase1_transaction_queue`(축은 units)가 cases 유무에 묶인다. units가 있으면 큐가 동작하도록
   resolver 또는 큐 진입 조건을 units 기준으로 보정한다(cases 빔 + units 있음 → 큐 동작). 단 기존 case
   소비처가 None 가정에 의존하면 깨지 않게 최소 수정. 영향 크면 NEEDS_CONTEXT.
1. (가) 함수: 주 검토 큐 경로를 `build_phase1_transaction_queue`로 위임. 기존 함수는 제거하지 말고
   내부에서 unit 큐를 호출하거나, 호출부를 unit 큐로 바꾸고 기존 함수를 deprecate 주석 처리.
2. (나) 함수: case.priority_band 정렬을 **소속 unit 등급 집계**로 교체. 예: topic 요약의 high/medium/low
   카운트는 그 topic에 걸린 **unit**들의 priority_band를 센다(case가 아니라). `_band_rank(case.priority_band)`
   정렬은 집계뷰 표시 정렬이면 유지 가능하나, **정답/우선순위 truth 축으로 문서화하지 말 것**.
3. `_case_row`가 내보내는 "priority_band"는 집계뷰 파생 표시값임을 주석으로 명시.

## 4. 단계 체크리스트 (순서 고정)
- [ ] Step 1: Phase A 분류표 보고(각 빌더 (가)/(나) + 근거). 모호·대체영향 큼 → NEEDS_CONTEXT
- [ ] Step 2: (가) 함수 unit 큐 위임. 증거: diff + 테스트(주 큐가 unit 단위 반환)
- [ ] Step 3: (나) 함수 집계 숫자를 unit 등급 카운트로 교체. 증거: diff + 테스트(카운트=소속 unit 등급 수)
- [ ] Step 4: case.priority_band가 주 검토 큐 truth 축으로 안 쓰임을 grep로 확인. 증거: grep 결과
- [ ] Step 5(마지막): §6 전체 검증
※ 증거 없는 단계는 미수행 간주.

## 5. 금지 사항 (1건이라도 위반 시 실패)
- case에 새 truth 점수를 부여하지 말 것(정책 §5 위반). 집계뷰 숫자는 unit 카운트/합만.
- band 문자 리터럴 분기 금지(`_band_rank` 경유). 룰ID 화이트리스트 금지.
- stage3a 신설 함수의 시그니처·동작 변경 금지(여기선 소비만).
- 테스트 약화 금지(skip/xfail/assert 완화/기대값 출력맞춤).
- 범위: `phase1_case_view.py`, 관련 테스트. dashboard는 stage3c, topic_scoring·unit 산식은 건드리지 말 것.
- 체크리스트 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수)
- `uv run pytest tests/modules/test_export -q` → 신규 0 failed (기존 알려진 실패 N 명시)
- 직접 재현(2+ 케이스): (a) 주 검토 큐 반환 행이 unit_id를 가짐(case_id 아님), (b) topic 집계 카운트가
  소속 unit 등급 수와 일치 — print 확인
- ripple grep: `grep -rn "case.priority_band\|_band_rank(case" src/export/phase1_case_view.py` → 남은 사용처가
  전부 집계뷰 표시용(주 검토 큐 truth 축 아님)임을 보고
- 한글 깨짐(U+FFFD) 0건.
※ 기대와 다르면 DONE 금지. 구조 충돌 NEEDS_CONTEXT.

## 7. 완료 보고 양식 (그대로, 생략 금지)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령+출력 원문)
변경 파일: 경로 목록(변경 안 한 파일 포함 금지)
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려: 정직하게 전부. 없으면 "없음"

> 모든 보고·주석은 한국어로 작성한다.
