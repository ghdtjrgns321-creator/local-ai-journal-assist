# 작업: stage1~3 통합 회귀 + 발화표 정합 게이트

## 1. 목표
- stage1(조합)·stage2(sort_key)·stage3(LOW coverage)가 모두 머지된 상태에서 전체 회귀를 돌리고,
  코드 동작이 `HIGH_COMBO_GROUNDING.md` §3.0 발화표와 **전수 일치**하는지 증명한다.
- 성공 기준: §6 전체 게이트가 기대 출력으로 끝나고, §3.0의 13개 조합 행마다 합성 케이스 1개씩으로
  기대 tier가 나오는 정합 테스트가 통과한다.

## 2. 컨텍스트
- 읽어야 할 파일: `docs/spec/HIGH_COMBO_GROUNDING.md` §3.0(L116~137 발화표), §6 종합표(L471~498),
  stage1~3 지시서, `tests/modules/test_detection/test_topic_tiers.py`
- 따라야 할 기존 패턴: 기존 test_topic_tiers.py의 evidence dict 구성 방식 그대로.
- 배경: 이 단계는 코드 신규 로직 추가가 아니라 **검증 자산** 작성 + 전체 회귀. 기능 변경 금지.

## 3. 설계 (이대로 구현 — 임의 변경 금지)
### 3-1. 발화표 정합 테스트 (test_topic_tiers.py에 추가)
§3.0 13행 각각에 대해 "그 조합을 만족하는 최소 룰셋 → 기대 tier" 1케이스 + "한 다리 빠진 → 강등/미발화"
1케이스. 표(코드가 아니라 §3.0 문서)를 기대값 원천으로 삼는다.
```
HIGH  fictitious_entry_high          (L4-01|L4-03)&L3-02&{L4-04|L2-03|L3-03|L1-05|L3-11}
HIGH  embezzlement_concealment_high  ((L2-02|L2-03|L2-05)&bypass) | ((L2-02|L2-03|L2-05)&L3-02&L4-03)
HIGH  suspense_concealment_high      L3-09&(L2-02|L2-03|L2-05)&L4-03
HIGH  period_end_adjustment_high     (L3-04|L3-11)&(L3-10|L4-04|L4-03)
HIGH  approval_bypass_high           bypass&(L4-03|L2-02|L2-03)
HIGH  expense_capitalization_high    L2-04&L3-02&(L4-03|L3-04|L1-06)
MEDIUM rare_account_bypass_medium    L4-04&bypass
MEDIUM embezzlement_concealment_medium L2-01&(L1-05|L1-06|L1-07|L1-07-02)
MEDIUM related_party_reversal_medium L3-03&L2-05
MEDIUM fictitious_entry_medium       (L4-01|L4-03)&L3-02  (2차정황 없음)
MEDIUM suspense_concealment_medium   L3-09&(L2-02|L2-03|L2-05)  (고액 없음)
MEDIUM expense_capitalization_medium L2-04&L3-02  (셋째다리 없음)
LOW   standalone primary 단독        조합 매치 없음 → 큐 제외·coverage
bypass = (L1-04|L1-05|L1-06|L1-07|L1-07-02)
```
### 3-2. 폐기 combo 부재 단정
폐기된 policy_id(`approval_bypass_medium`·`period_end_adjustment_medium`·`batch_combo`·
`work_scope_combo`·`related_party_reversal_high`)가 어떤 입력으로도 발화하지 않음을 단정.

## 4. 단계 체크리스트 (순서 고정)
- [ ] Step 1: stage1~3 머지 확인 + §2 읽기. 증거: `git log --oneline -5` + 변경 파일 존재 확인
- [ ] Step 2: §3-1 발화표 정합 테스트 작성(13행). 증거: 추가 테스트 함수명 목록
- [ ] Step 3: §3-2 폐기 combo 부재 테스트 작성. 증거: 함수명 + 통과
- [ ] Step 4(마지막): §6 전체 게이트 실행 후 출력 원문
※ 증거 없는 단계는 미수행 간주.

## 5. 금지 사항 (1건이라도 위반 시 실패)
- 기능 코드 수정 금지 — 이 단계는 테스트·검증만. src/ 의 로직을 바꿔 테스트를 통과시키지 말 것
  (테스트가 실패하면 stage1~3 결함이므로 BLOCKED로 되돌려 보고).
- 기대값을 코드 출력에서 베끼지 말 것 — §3.0 문서가 기대값 원천.
- 테스트 약화 금지(skip/xfail/assert 완화). hollow-PASS(빈 집합 통과) 금지.
- 하드코딩 금지: 연도·corp_code·절대 금액 임계를 테스트 픽스처에 박지 말 것(룰 발화 플래그만).
- 체크리스트 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수)
- `uv run pytest tests/modules/test_detection/test_topic_tiers.py -q` → 기대: 전부 passed
- `uv run pytest tests/ -q` → 기대: 신규 0 failed (기존 알려진 실패 baseline N "알려진 실패 N, 신규 0" 유지)
- ripple grep(폐기 policy_id src/ 0건):
  `grep -rn "approval_bypass_medium\|period_end_adjustment_medium\|batch_combo\|work_scope_combo\|related_party_reversal_high" src/`
  → 기대: 0건
- 발화표 13행 전수 커버: 정합 테스트가 §3.0 13행을 모두 포함하는지 함수 수로 확인 → 기대: 13행 이상
- 한글 깨짐(U+FFFD) 0건.
※ 하나라도 기대와 다르면 DONE 금지. stage1~3 결함이면 BLOCKED로 어느 stage·어느 행인지 명시.

## 7. 완료 보고 양식 (그대로, 생략 금지)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령+출력 원문)
변경 파일: 경로 목록(변경 안 한 파일 포함 금지)
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려: 정직하게 전부. 없으면 "없음"

> 모든 보고·주석은 한국어로 작성한다.
