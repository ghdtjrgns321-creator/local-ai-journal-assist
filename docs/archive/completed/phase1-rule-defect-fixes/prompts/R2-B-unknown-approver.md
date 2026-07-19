# 작업: 유령 승인자 탐지 — L1-07 `unknown_approver` 서브패턴 신설 (이슈 #19)

> 한국어로 응답·보고할 것. 저장소: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist`, 브랜치 `develop`.
> grep이 없으면 rg로 대체 가능 (동일 범위 검색 + 출력 원문 첨부).

## 1. 목표

- 승인자 칸에 **직원 마스터에 없는 ID**를 적으면 승인통제 룰 전체(L1-04 한도검사 제외, L1-07
  승인생략 비후보)를 회피하는 사각을 막는다: feature 층에 `approver_in_master` 컬럼을 추가하고,
  L1-07이 "비공란인데 마스터에 없는 승인자"를 `unknown_approver` 서브패턴으로 플래그한다.
- 성공 기준: §6 검증 전부 통과 + "유령 승인자 행이 score 0.55로 플래그되고, 마스터 자체가 없으면
  발화 0(기존 동작 불변)"을 단언하는 테스트 존재.

## 2. 컨텍스트

- 읽어야 할 파일 (수정 전 반드시 읽을 것):
  - `src/feature/amount_features.py` — `_compute_approver_info()`(118-148행):
    `employees.json`을 user_id 키로 로드해 `approval_limit`/`can_approve_je`를 만드는 기존 조인.
    **여기가 마스터 멤버십 판정의 단일 지점**이다. 이 함수의 호출부(approval feature를 df 컬럼으로
    부착하는 곳)를 추적해 읽을 것.
  - `src/detection/fraud_rules_access.py` — `b09_skipped_approval()`(2195행~): L1-07 본체.
    후보 정의(approved_by 공란, 1974행 부근), 버킷/score/annotation/breakdown 구조.
  - `tests/modules/test_detection/test_fraud_rules_access.py` — b09 기존 테스트 패턴.
  - `docs/spec/DETECTION_RULES.md` 599-647행 — L1-07 스펙 (문서 갱신은 설계자 몫 — 읽기만).
- 배경 (모르면 잘못 판단할 사실):
  - **v41 정상 데이터 실측: 승인자 비공란 292,505행 중 마스터(user_id) 미존재 = 0건.**
    즉 이 신호는 정상에서 절대 안 울리는 순수 회피 차단 신호다. 정상 발화가 나온다면 그건
    구현 버그다 (테스트로 잡을 것).
  - 마스터 멤버십 기준은 `_load_employee_approval_map`과 동일한 **user_id 단독**이다.
    employee_id·display_name 등 다른 키로 확장하지 말 것 (한도 조인과 기준이 갈라지면
    "한도는 미해소인데 마스터엔 있음" 같은 모순 상태가 생긴다).
  - 직원 마스터가 아예 없는 입력(실 ERP 추출 등)에서는 판정 불가 — 발화 0이 정답이다
    (#7 침묵 비활성과 같은 graceful 패턴. coverage 노출은 별도 이슈로 관리 중).
  - L1-07의 기존 후보는 "approved_by 공란"이다. 이번 서브패턴은 **비공란** 대상이라 기존
    후보·점수 경로와 교집합이 없어야 한다 (기존 경로 로직 변경 금지).

## 3. 설계 (이대로 구현 — 임의 변경 금지)

1. **feature 층** (`amount_features.py`):
   - `_compute_approver_info()`가 반환하는 DataFrame에 `approver_in_master` 컬럼 추가
     (pandas BooleanDtype): 승인자 공란 → `pd.NA`, approval_map의 user_id에 존재 → `True`,
     비공란인데 미존재 → `False`. 마스터 로드 실패/부재 시 기존처럼 None 반환 (컬럼 미생성).
   - 호출부에서 이 컬럼을 다른 approval feature와 같은 방식으로 df에 부착.
2. **detector 층** (`fraud_rules_access.py` `b09_skipped_approval`):
   - `approver_in_master` 컬럼이 df에 있을 때만:
     `unknown_approver = approved_by 비공란 ∧ approver_in_master == False` (BooleanDtype 비교 시
     `.fillna(False)` 류 NA 방어 필수).
   - 해당 행: score **0.55** 고정, reason_code/bucket `"unknown_approver"`, annotation에
     승인자 값 기록, breakdown에 `unknown_approver_rows` 카운트 추가. 기존 b09 annotation·
     breakdown dict 구조를 그대로 따른다.
   - 컬럼 부재 시: 서브패턴 완전 비활성 (기존 출력과 바이트 단위 동일).
   - 기존 공란 후보 경로(immediate/review/low_priority)의 마스크·점수 로직은 한 줄도 변경 금지.
3. score 0.55의 자리: 기존 score_series에 `unknown_approver` 행을 0.55로 set (기존 행과 겹치지
   않음 — 공란/비공란이 상호배타). 단 기존 코드가 비공란 행에 0이 아닌 값을 주는 경로가 있으면
   (예: low_priority 일부) **max 병합**으로 충돌 방지하고 그 사실을 보고에 명시.
- 설계가 현장과 안 맞으면(예: _compute_approver_info 반환 구조를 바꾸면 기존 소비처가 깨짐,
  b09가 비공란 행을 이미 다른 용도로 점수화): 임의 변경하지 말고 STATUS: NEEDS_CONTEXT로 멈출 것.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1: `_compute_approver_info` 호출부 추적 + b09의 비공란 행 처리 현황 확인 → 산출물:
      "부착 지점 파일:라인 + 비공란 행에 점수 주는 기존 경로 유무" 메모
      증거: 관련 grep/rg 출력 원문
- [ ] Step 2 (TDD RED): 신규 테스트 — feature 층 3개 + detector 층 4개 최소:
      [feature] ① 마스터 내 승인자 → True ② 유령 승인자 → False ③ 공란 → NA, 마스터 부재 → 컬럼 없음
      [detector] ④ 유령 승인자 행 → 플래그 + score 0.55 + reason unknown_approver
      ⑤ 마스터 내 승인자 → 이 서브패턴 미발화 ⑥ 공란 승인자 → 기존 L1-07 경로 결과 불변
      ⑦ approver_in_master 컬럼 부재 → b09 출력이 기존과 동일 (breakdown 포함)
      증거: pytest 실행에서 신규 테스트 FAILED 원문 (RED)
- [ ] Step 3 (GREEN): §3 구현 → 같은 명령 전부 passed 원문
- [ ] Step 4 (ripple): `approver_in_master` 이름이 기존 코드와 충돌하지 않는지 +
      `_compute_approver_info` 기존 소비처가 신규 컬럼으로 깨지지 않는지 전수 확인
      증거: `rg -n "approver_in_master|_compute_approver_info" src tests` 출력 원문
- [ ] Step 5(항상 마지막): 전체 검증(§6) 실행 후 출력 원문 확보
※ 각 단계의 증거는 완료 보고에 원문 그대로 포함한다. 증거가 없는 단계는 미수행으로 간주한다.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- 하드코딩: 마스터 멤버십을 user_id 외 키로 확장 금지. employees.json 경로를 리터럴로 박지 말 것
  (기존 `_resolve_employee_master_path` 경유). score 0.55 외 임계·점수 신설 금지.
- 기존 L1-07 공란 경로(immediate/review/low_priority)·L1-04·registry·topic_scoring 변경 금지.
- 테스트 약화 금지: skip/xfail 추가, assert 삭제·완화, 기대값을 출력에 맞춰 수정.
- 범위 밖 수정 금지: 수정 가능 파일 = `src/feature/amount_features.py`(+호출부가 다른 feature
  파일이면 그 부착 지점 1곳), `src/detection/fraud_rules_access.py`,
  `tests/modules/test_feature/`·`tests/modules/test_detection/` 하위 해당 테스트 파일.
  docs·config 변경 금지 (스펙 문서는 설계자가 갱신).
- 체크리스트 항목 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)

- 해당 feature·detector 테스트 파일 → 전부 passed
- `uv run pytest tests/modules/test_detection/ tests/modules/test_feature/ -q` → 신규 실패 0
  (사전 베이스라인 전/후 failed 목록 비교 원문. `test_duplicate_performance.py`가 1.0~1.5s로
  실패하면 3회 재실행 첨부 — 3회 모두 1.5s 초과 시에만 BLOCKED)
- `uv run ruff check src/feature/amount_features.py src/detection/fraud_rules_access.py` → All checks passed
※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED로 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 각 항목의 증거(명령 + 출력 원문 붙여넣기)
변경 파일: <경로 목록 — 변경하지 않은 파일을 포함하지 말 것>
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">

신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로이며 다음 지시로
이어진다. 거짓 DONE은 재검증에서 반드시 드러나고 작업 전체를 처음부터 재수행하게 된다.
