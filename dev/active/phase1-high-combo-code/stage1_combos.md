# 작업: PHASE1 fraud combo 재정의 (topic_scoring.py를 HIGH_COMBO §3.0에 정합)

## 1. 목표
- `src/detection/topic_scoring.py`의 `_fraud_combo_floor_results()`·`DEFAULT_COMBO_FLOORS`·
  룰셋 상수 3개를 `docs/spec/HIGH_COMBO_GROUNDING.md` §3.0 발화표와 **글자 그대로** 일치시킨다.
- 성공 기준: 아래 §6 검증 명령(단위테스트 + 발화표 대조 스크립트)이 모두 기대 출력으로 끝난다.
  주관 표현으로 완료 선언 금지.

## 2. 컨텍스트
- 읽어야 할 파일 (수정 전 반드시 읽을 것):
  - `docs/spec/HIGH_COMBO_GROUNDING.md` §3.0(L112~137 발화표), §6(L471~498 종합표), §8(L515~564 변경이력)
  - `src/detection/topic_scoring.py` 전체 (특히 L14~49 상수, L450~629 `_fraud_combo_floor_results`)
  - `src/detection/rule_scoring.py` L54~60 TOPIC_REGISTRY, 각 룰 final_topic
  - `tests/modules/test_detection/test_topic_tiers.py` (현행 기대 조합)
- 따라야 할 기존 패턴: 같은 파일 안 `add(topic_id, policy_id, tag, reason)` 호출 패턴 그대로.
  새 floor 추가 시 DEFAULT_COMBO_FLOORS에 키 등록 + add() 호출. 절대 새 함수·새 모듈 만들지 말 것.
- 배경: tier는 floor 숫자값(>=0.75 HIGH, >=0.45 MEDIUM)을 `_floor_value_tier`가 분류해 결정한다.
  MEDIUM floor=0.60, HIGH floor=0.75로 통일(기존 값 그대로). combo의 host topic은 add()에 박는
  topic_id이며 룰의 final_topic과 무관하다(기존 동작).

## 3. 설계 (이대로 구현 — 임의 변경 금지)

### 3-1. 룰셋 상수 3개 변경 (L30~49)
```
_FICTITIOUS_SECONDARY_RULES : L3-10 제거. 최종 = {L4-04, L3-03, L1-05, L3-11} | _DUPLICATE_ENTRY_RULES
   (§3.0 HIGH-1 2차정황 풀 {L4-04|L2-03|L3-03|L1-05|L3-11}와 일치. L2-03=_DUPLICATE_ENTRY_RULES)
_TIMING_SEED_RULES : L3-07·L1-08 제거. 최종 = {"L3-04", "L3-11"}
   (§3.0 HIGH-4 첫 leg (L3-04|L3-11)와 일치. §8(5) "L3-07·L1-08@H4 헛다리 삭제")
_WEAK_DESCRIPTION_OR_SENSITIVE_ACCOUNT_RULES : L3-08 제거, L4-03 추가.
   상수명을 _PERIOD_END_CORROBORANT_RULES 로 개명. 최종 = {"L3-10", "L4-04", "L4-03"}
   (§3.0 HIGH-4 둘째 leg (L3-10|L4-04|L4-03)와 일치. §8(1) 고액 L4-03 복원, §8(5) L3-08 제거)
```

### 3-2. DEFAULT_COMBO_FLOORS 변경 (L14~28)
```
ADD    : "suspense_concealment_medium": 0.60
ADD    : "expense_capitalization_medium": 0.60
ADD    : "related_party_reversal_medium": 0.60
ADD    : "rare_account_bypass_medium": 0.60
REMOVE : "batch_combo", "work_scope_combo", "period_end_adjustment_medium",
         "approval_bypass_medium", "related_party_reversal_high"
KEEP(값 그대로): fictitious_entry_medium 0.60, fictitious_entry_high 0.75,
         embezzlement_concealment_medium 0.60, embezzlement_concealment_high 0.75,
         suspense_concealment_high 0.75, period_end_adjustment_high 0.75,
         expense_capitalization_high 0.75, approval_bypass_high 0.75
```

### 3-3. `_fraud_combo_floor_results()` 본문 — combo별 변경 전→후

`has_revenue_or_amount/has_timing_seed/has_outflow/has_approval_bypass`는 유지.
`has_weak_description_or_sensitive` → `has_period_end_corroborant`(개명 상수 기반)로 교체.

**(A) revenue_statistical (가공전표)**
```
유지: if has_revenue_or_amount and "L3-02" in rule_ids and (rule_ids & _FICTITIOUS_SECONDARY_RULES):
          add(... "fictitious_entry_high" ...)   # reason 문자열 유지
교체: elif has_revenue_or_amount and "L3-02" in rule_ids:                     # ← 약화형 재정의
          add("revenue_statistical","fictitious_entry_medium","fictitious_entry_risk",
              "revenue_or_amount_outlier + manual_adjustment (no_secondary)")
삭제: 기존 elif의 (L4-01 & L3-04) | (L4-03 & L4-06 & L3-02) 조건 전체 폐기(§3.0 약화형으로 대체)
```

**(B) closing_timing (결산조작 + 관계사역분개)**
```
교체: if has_timing_seed and has_period_end_corroborant:
          add(... "period_end_adjustment_high" ...)   # reason 유지
삭제: 기존 elif "L3-11" in rule_ids and has_revenue_or_amount → period_end_adjustment_high  (cutoff 분기 폐기, §8(5) H4 미수정)
삭제: period_end_adjustment_medium 분기 자체가 없으면 추가하지 말 것(폐기 확정)
교체(HIGH-7 이관): 기존 if {"L2-05","L3-03","L3-04"}.issubset(rule_ids) → related_party_reversal_high
       를 →  if {"L2-05","L3-03"}.issubset(rule_ids):                          # L3-04 기말 제거
                  add("duplicate_outflow","related_party_reversal_medium","related_party_reversal_risk",
                      "reversal + related_party (no_period_end)")
       ※ host=duplicate_outflow (closing_timing 아님). 근거: 기말 L3-04를 뺐으므로 closing_timing엔
         standalone primary seed가 없어 has_rankable_primary=False → combo가 CONTEXT로 죽는다.
         L2-05(역분개=duplicate_outflow primary)가 seed라 host를 duplicate_outflow로 둬야 MEDIUM이 산다.
         L3-03은 booster(standalone_rankable=False)라 단독 seed 불가. 테스트는 L2-05·L3-03 단독으로
         duplicate_outflow=="MEDIUM"을 단정할 것 — L3-04 같은 passenger 룰을 끼워 primary를 공급하지 말 것
         (hollow-PASS 금지).
```

**(C) duplicate_outflow (횡령은폐 + 한도분할 + 가수금)**
```
교체: has_reversal_manual_concealment 변수 삭제.
      if has_outflow and (has_approval_bypass or ("L3-02" in rule_ids and "L4-03" in rule_ids)):
          add(... "embezzlement_concealment_high" ...)   # §3.0: outflow&bypass | outflow&L3-02&L4-03
교체(M2 한도분할): elif "L2-01" in rule_ids and (rule_ids & {"L1-05","L1-06","L1-07","L1-07-02"}):
          add(... "embezzlement_concealment_medium" ... "threshold_splitting + approval_bypass(no_L1-04)")
          # 기존 {"L1-04","L1-05"} & rule_ids 조건을 위 4종으로 교체(한도초과 L1-04 제외)
유지: if "L3-09" in rule_ids and has_outflow and "L4-03" in rule_ids:
          add(... "suspense_concealment_high" ...)
추가(약화형 가수금): elif "L3-09" in rule_ids and has_outflow:                  # 고액 없음
          add("duplicate_outflow","suspense_concealment_medium","embezzlement_concealment_risk",
              "suspense_aging + outflow (no_high_amount)")
```

**(D) account_logic (비용자산화 + 희소계정쌍)**
```
교체: if {"L2-04","L3-02"}.issubset(rule_ids) and (rule_ids & {"L4-03","L3-04","L1-06"}):
          add(... "expense_capitalization_high" ...)   # §3.0: L2-04&L3-02&(L4-03|L3-04|L1-06)
          # 기존 {"L2-04","L3-02","L3-04"} 고정 셋째다리를 (L4-03|L3-04|L1-06) OR로 교체
추가(약화형 비용자산화): elif {"L2-04","L3-02"}.issubset(rule_ids):              # 셋째다리 없음
          add("account_logic","expense_capitalization_medium","expense_capitalization_risk",
              "expense_capitalization + manual (no_third_leg)")
추가(M1 희소+승인우회): if "L4-04" in rule_ids and has_approval_bypass:
          add("account_logic","rare_account_bypass_medium","rare_account_bypass_risk",
              "rare_account_pair + approval_bypass")
```

**(E) approval_control (승인우회)**
```
교체: has_strong_approval_context 변수 삭제.
      if has_approval_bypass and ("L4-03" in rule_ids or "L2-02" in rule_ids
                                  or (rule_ids & _DUPLICATE_ENTRY_RULES)):
          add(... "approval_bypass_high" ...)   # §3.0: bypass & (L4-03|L2-02|L2-03)
삭제: approval_bypass_medium 모든 elif 분기(L3-02 / L3-06 / L3-05 / L3-12+L1-05·L1-07 work_scope) 전부 폐기
```

설계가 현장과 안 맞으면(예: 어떤 floor가 다른 곳에서 참조돼 제거 시 KeyError) 임의 변경 말고
즉시 멈추고 STATUS: NEEDS_CONTEXT로 보고. 멈추는 것은 실패가 아니다.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)
- [ ] Step 1: §2 파일 전부 읽기. 증거: 읽은 파일 경로 목록 + topic_scoring.py 현재 줄 수 보고
- [ ] Step 2: 룰셋 상수 3개 변경(§3-1). 산출물: topic_scoring.py diff
      증거: `git diff src/detection/topic_scoring.py` 에 _FICTITIOUS_SECONDARY_RULES에서 "L3-10" 사라지고
      _PERIOD_END_CORROBORANT_RULES = {"L3-10","L4-04","L4-03"} 신설된 부분 출력
- [ ] Step 3: DEFAULT_COMBO_FLOORS 변경(§3-2). 증거: 위 diff에서 ADD 4개·REMOVE 5개 라인 출력
- [ ] Step 4: `_fraud_combo_floor_results` 본문 (A)~(E) 교체(§3-3). 증거: 해당 함수 diff 전체
- [ ] Step 5: 테스트 갱신 — `test_topic_tiers.py`에서 폐기 combo(approval_bypass_medium 등) 기대 제거,
      신규 약화형/M1/M2/HIGH-7이관 기대 추가. **기대값을 코드 출력에 맞춰 베끼지 말고 §3.0 발화표 기준으로 작성.**
      증거: 추가/수정한 테스트 함수명 목록 + 각 테스트가 검증하는 §3.0 행
- [ ] Step 6(마지막): §6 전체 검증 실행 후 출력 원문 확보
※ 증거 없는 단계는 미수행으로 간주.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)
- 하드코딩 금지: 연도 리터럴, corp_code, **절대 금액 임계값**을 combo 분기에 새로 박지 말 것.
  금액 기준은 이미 룰 발화(L4-03 z-score)에서 처리됨 — combo는 룰ID 집합 연산만 한다.
- 룰ID는 §3.0 발화표에 명시된 것만 사용. 표에 없는 룰ID로 분기 신설 금지(헛다리 재발 방지).
- 보조축(L3-05·L3-06·L3-08·L4-05) tier 게이트 투입 금지 — 이 단계는 OFF-TIME 미포함(stage2 담당).
- 테스트 약화 금지: skip/xfail 추가, assert 삭제·완화, 기대값을 출력에 맞춰 수정.
- 범위 밖 수정 금지: 수정 가능 = `src/detection/topic_scoring.py`,
  `tests/modules/test_detection/test_topic_tiers.py` (+ 폐기 combo를 참조하는 다른 테스트 최소 수정).
  rule_scoring.py·case_builder·export·dashboard·sort_key는 이 단계에서 건드리지 말 것.
- 체크리스트 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)
- `uv run pytest tests/modules/test_detection/test_topic_tiers.py -q` → 기대: 전부 passed, 0 failed
- `uv run pytest tests/modules/test_detection/ -q` → 기대: 신규 0 failed (기존 알려진 실패 있으면 그 N건만,
  새 실패 0). 알려진 실패 baseline을 보고에 N으로 명시.
- ripple grep (구 policy_id 잔존 확인):
  `grep -rn "approval_bypass_medium\|period_end_adjustment_medium\|batch_combo\|work_scope_combo\|related_party_reversal_high" src/ tests/`
  → 기대: src/ 에 0건. tests/ 에 남으면 그 테스트가 폐기 combo를 아직 기대하는 것이므로 Step 5 미완.
- 한글 깨짐 확인: 위 diff에 U+FFFD(replacement char) 0건.
※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 각 항목 증거(명령 + 출력 원문 붙여넣기)
변경 파일: 경로 목록 (변경 안 한 파일 포함 금지)
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려 사항: 정직하게 전부. 없으면 "없음"
신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로. 거짓 DONE은 재검증에서
반드시 드러나 작업 전체 재수행.

> 모든 보고·주석은 한국어로 작성한다.
