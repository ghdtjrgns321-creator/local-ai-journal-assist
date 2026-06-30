# 작업: L3-10 "추정계정 사용" binary 재설계 — 코드 반영 (룰 + 소비자 6 + config + 테스트)

> **설계자 노트(구현 전 반드시 읽기)** — 매칭 방식 결정: 추정계정은 회사 CoA마다 코드가 달라 코드 리터럴로 발화를 구동하면 §3 위반이다.
> 그래서 **1차 = `account_name`/`gl_account_name` 키워드 매칭(CoA 무관·robust, 기존 가계정 L3-09가 쓰는 방식)**, **2차 = engagement가 확정한 코드/prefix(옵션)**로 OR 매칭한다.
> 둘 다 미설정이면 발화 0건(전 계정 정상 아님 = 미검증). 이 방식대로 구현한다. 임의로 코드-only로 바꾸지 말 것.

## 1. 목표
- L3-10을 "고위험계정(가지급금·가수금·현금)" → **"추정계정 사용(EstimateAccountUse)"** binary flag 룰로 재설계하고, 그 변경을 모든 소비자·테스트에 ripple 반영한다.
- 발화 = 추정계정(회계추정치, ISA 540) 접촉 시 `score=1.0`, 아니면 `0.0`. 3등급 차등(priority_case/raw_signal/normal_control_candidate)과 정황 분류 전면 폐기.
- **성공 기준**: §6 검증 3개가 전부 기대 출력으로 통과. toy 호출 score 고유값이 `{0.0, 1.0}`의 부분집합. 폐기물 grep 0. `uv run pytest tests/modules/test_detection tests/modules/test_metrics -q`가 baseline 유지(신규 실패 0).

## 2. 컨텍스트
- **수정 전 반드시 읽을 파일**:
  - `src/detection/fraud_rules_access.py` (룰 본체 — 함수 304~512, 841~880)
  - `src/detection/fraud_layer.py` (import·dispatch·explanation 19/137/293/317)
  - `src/detection/phase1_case_builder.py` (라벨·detail 385/487/5615/5821/5986~6003)
  - `src/detection/rule_detail_metadata.py` (메타 616~632)
  - `src/detection/score_aggregator.py` (586/670 — 단 70/76은 L1-04라 건드리지 말 것)
  - `src/metrics/ground_truth_evaluator.py` (L3-10 branch 734~778, 930~931, 1193, 1253/1267)
  - `config/audit_rules.yaml` (`patterns.high_risk_account_use` 블록 + `patterns.self_approval_immediate_override` 블록)
  - `docs/spec/DETECTION_RULES.md` L3-10 카드(941~) — **설계 SoT, 이미 갱신됨. 이 카드대로 코드를 맞춘다.**
- **따라야 할 기존 패턴**:
  - binary 룰 선례: `anomaly_rules_simple.py::c04_backdated_entry`(L3-07), `c10_suspense_account`(L3-09) — `score_series`가 `1.0/0.0`, `row_annotations`는 사실값만.
  - 키워드 매칭 선례: `src/feature/pattern_features.py`의 `add_is_suspense_account`(가계정 키워드 매칭, `_SUSPENSE_TEXT_COLS = ["line_text","header_text","gl_account_name"]`).
  - ground_truth_evaluator binary branch 선례: 같은 파일 L3-07(733행 `flagged_docs = scores>0 nunique`).
- **배경(모르면 오판할 사실)**:
  - L3-10이 잡는 계정은 **추정계정 A+B+C+D**(아래 §3 config). 가지급금·가수금은 L3-09(가계정 장기체류)가, 현금은 노이즈라 L3-10에서 **제외**한다. 퇴직급여·이연법인세(C)는 추정계정이므로 **포함**한다.
  - `_is_high_risk_account`(304행)와 `patterns.self_approval_immediate_override.high_risk_accounts`는 **L1-05 자기승인 escalation 전용**이다. L3-10과 무관 — **건드리지 말 것**(별도 config 키).
  - `score_aggregator.py` 70/76 `escalated_high_risk_account` 가중치는 **L1-04 한도초과 escalation**이다. L3-10 아님 — **건드리지 말 것**.
  - DataSynth 라벨(`labels/high_risk_account_*`)과 `src/metrics/rule_mapping.py`의 라벨 경로는 **DataSynth 재생성 단계(별도, 보류)** 소관이라 **이번 범위 밖**이다. 단 코드가 그 라벨 부재로 crash하면 안 된다.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

### 3-1. config 재구조화 (`config/audit_rules.yaml`)
`patterns.high_risk_account_use` 블록을 아래로 **rename + 교체**한다(기존 가계정/현금 코드 삭제):
```yaml
  estimate_account_use:
    # L3-10 회계추정치(ISA 540) 계정 — 결산 이익조정 단골(cookie jar). binary flag.
    # 1차 account_name 키워드(CoA 무관), 2차 클라이언트 확정 코드. 둘 다 비면 발화 0.
    account_name_keywords:
      - 대손충당금
      - 평가충당금          # 재고자산평가충당금 등
      - 손상차손
      - 손상누계            # 손상차손누계액
      - 충당부채            # 판매보증·복구·소송·구조조정 등
      - 환불부채
      - 반품충당
      - 미청구공사
      - 계약자산
      - 퇴직급여
      - 확정급여
      - 이연법인세
    accounts: []            # 클라이언트 확정 정확 코드(옵션)
    account_prefixes: []    # 클라이언트 확정 prefix(옵션)
    estimate_account_groups:   # annotation matched_group 표시용 카테고리(발화 로직 아님)
      allowance_impairment:    # A 평가성 충당금·손상
        keywords: [대손충당금, 재고자산평가충당금, 평가충당금, 손상차손, 손상누계]
      provision:               # B 충당부채
        keywords: [판매보증충당부채, 하자보수충당부채, 복구충당부채, 소송충당부채, 구조조정충당부채, 충당부채]
      revenue_estimate:        # D 수익 추정
        keywords: [환불부채, 반품충당, 미청구공사, 계약자산]
      actuarial_tax:           # C 보험수리·세무 추정
        keywords: [퇴직급여, 확정급여, 이연법인세]
```
> generic `충당부채`가 `퇴직급여충당부채`를 잡고, C(퇴직급여·이연법인세)도 추정계정으로 **포함**한다(A+B+C+D). 제외 키워드(exclude) 로직 없음.
**주의**: `patterns.self_approval_immediate_override` 블록(아래쪽 `high_risk_accounts`/`high_risk_account_prefixes`)은 L1-05 전용이므로 **그대로 둔다**.

### 3-2. 룰 본체 (`fraud_rules_access.py`)
- `_get_high_risk_account_config` → **`_get_estimate_account_config`**: `patterns.estimate_account_use`를 읽어 `{account_name_keywords: tuple, accounts: tuple, account_prefixes: tuple, estimate_account_groups: {name: {keywords: tuple}}}` 반환. 미설정 시 빈 tuple(legacy fallback 제거).
- 매칭 헬퍼(현 `_high_risk_account_match_annotations` 자리): 행별 발화 = `(account_name/gl_account_name 텍스트에 keyword 포함)` **OR** `(gl_account ∈ accounts)` **OR** `(gl_account가 account_prefixes로 시작)`.
  - `account_name`/`gl_account_name` 컬럼이 둘 다 없으면 키워드 매칭은 건너뛰고 코드 매칭만(graceful). 둘 다·코드도 없으면 전부 0.
  - `gl_account` 비교 시 trailing `.0` 제거(기존 주의사항 유지).
- `row_annotations[int(idx)]`는 **사실값만**: `match_type`("keyword"|"exact"|"prefix"), `matched_value`(매칭된 키워드 또는 코드/prefix), `matched_group`(아래 group 해소 결과). **`signal_category`·`category_reason` 키 삭제.**
- `matched_group` 해소(현 `_matched_high_risk_group` 자리, keyword 기반으로 교체): `estimate_account_groups`를 순회해 account_name에 그 group의 keyword가 substring으로 있으면 그 group명 반환, 없으면 `""`.
- `b13_high_risk_account_use` → **`b13_estimate_account_use`**: `score_series`는 발화 행 **전부 `1.0`**, 아니면 `0.0`. 3등급 분기(0.65/0.35/0.20) 삭제.
  - `breakdown`: `{"flagged_rows": int, "reason_counts": {"keyword": n, "exact": n, "prefix": n}}`. `category_counts`/`raw_signal_rows`/`priority_case_rows`/`normal_control_candidate_rows` 삭제.
- **삭제**: `_high_risk_account_signal_category`(396~443), 그것만 쓰던 `_row_approval_date_absent`(446~453, 다른 사용처 grep으로 확인 후 없으면 삭제).
- **건드리지 말 것**: `_is_high_risk_account`(304), `_get_self_approval_immediate_override_config`(166), `_self_approval_immediate_override_mask`(903), `b14_work_scope_excess_review`(574~) — L1-05/L3-12 소관. (단 `b14`가 `_get_high_risk_account_config`를 호출하면(521행 부근 `high_risk = _get_high_risk_account_config`) 새 이름으로 갱신하되 L3-12 동작은 불변 유지.)

### 3-3. dispatch·explanation (`fraud_layer.py`)
- 19행 import: `b13_high_risk_account_use` → `b13_estimate_account_use`.
- 293행 dispatch: 함수 참조 교체. `"L3-10"` id·`{"audit_rules": ...}` 인자·317행 `["gl_account"]`는 유지.
- 137행 `RuleExplanation("L3-10", ...)`: 설명 문구를 추정계정 기준으로 갱신(고위험/가계정/현금 표현 제거).

### 3-4. case builder (`phase1_case_builder.py`)
- 487행 `"L3-10": "고위험 계정 사용"` → `"추정계정 사용"`.
- 385행 action dict: focus/action 문구를 추정계정 기준으로(가계정 표현 제거). `focus` 키 값은 `"estimate_account_use"`류로.
- 5986~6003 detail builder: `signal_category`(5992)·`category_reason`(5993)·`result=`(6000~6001)·`reason=`(6002~6003) 블록 **삭제**. `match_type`/`matched_value`/`matched_group` 표시만 유지.
- 5615행 필드 목록의 `"signal_category"` 제거.
- 164행 리스트의 `"L3-10"`은 유지.

### 3-5. 메타 (`rule_detail_metadata.py`)
- 632행 `derived=("account_family", "sensitive_account_touch", "priority_case")` → `derived=("match_type", "matched_value", "matched_group")`. 110/113/138 집합의 L3-10 유지.

### 3-6. score_aggregator (`score_aggregator.py`)
- 586행 `annotation.get("signal_category")` 참조: signal_category가 더는 없으므로 해당 조건을 제거하거나, annotation에 없을 때 안전하게 빠지도록 정리. **70/76행은 손대지 말 것.**
- 670행 `if rule_id in {"L3-10", ...}` 분기는 유지(L3-10이 review-only 그룹에 남음).

### 3-7. ground_truth_evaluator (`ground_truth_evaluator.py`)
- 734~778 L3-10 branch 전체를 **binary로 교체**(L3-07 733행 형식):
  `return {"flagged_docs": int(df.loc[scores > 0, "document_id"].dropna().nunique())}`.
  raw_sensitive_touch_docs/priority_case_docs/normal_control_docs·signal_category 의존·score-band(0.30/0.60) fallback **전부 삭제**.
- 930~931 `if rule_id == "L3-10" and "priority_case_docs" in score_bands: return priority_case_docs` → review_queue는 `flagged_docs`를 쓰도록 변경(또는 L3-10 특례 제거하고 공통 flagged 경로 사용).
- 1193/1253/1267 label-doc-set 분기: 라벨 파일 경로는 DataSynth 보류라 그대로 두되, 코드가 라벨 부재로 crash하지 않게(기존 graceful) 유지. 동작 변경 불필요하면 손대지 말 것.

### 설계가 현장과 안 맞으면
구현을 임의 변경하지 말고 즉시 멈추고 **STATUS: NEEDS_CONTEXT**로 보고. 특히: `account_name`/`gl_account_name` 컬럼이 파이프라인에 없거나, ground_truth_evaluator의 L3-10 라벨 파일 의존이 binary 전환과 충돌하면 멈추고 보고.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)
- [ ] Step 1: §2 파일 전부 읽기. 증거: 읽은 파일 경로 목록을 보고에 나열.
- [ ] Step 2: `config/audit_rules.yaml` §3-1대로 `estimate_account_use` 교체(+ `self_approval_immediate_override` 불변 확인). 증거: `grep -n "estimate_account_use\|high_risk_account_use" config/audit_rules.yaml` 출력(estimate_account_use 존재, high_risk_account_use는 self_approval 블록 내 high_risk_accounts만 잔존).
- [ ] Step 3: `fraud_rules_access.py` §3-2 구현(rename·binary·키워드매칭·annotation 정리·signal_category 삭제). 증거: `grep -n "_high_risk_account_signal_category\|signal_category\|priority_case\|0.65\|0.35\|0.20" src/detection/fraud_rules_access.py` 가 **0줄**(추정계정 점수 분기 잔존 0).
- [ ] Step 4: §3-3~3-6 소비자(fraud_layer·phase1_case_builder·rule_detail_metadata·score_aggregator) 반영. 증거: `grep -rn "b13_high_risk_account_use" src/` 가 **0줄**.
- [ ] Step 5: §3-7 ground_truth_evaluator binary 교체. 증거: `grep -n "raw_sensitive_touch_docs\|normal_control_docs\|priority_case_docs" src/metrics/ground_truth_evaluator.py` 가 **0줄**.
- [ ] Step 6: toy 검증 스크립트 실행(§6 ①). 증거: 출력 원문(score 고유값).
- [ ] Step 7: 영향 테스트 4종을 새 binary+키워드 기대로 갱신(assert 삭제·skip 금지, 기대값을 binary로 *교체*). 대상: `test_fraud_rules_access.py`, `test_phase1_case_builder.py`(+`_stage1.py`), `test_score_aggregator.py`, `test_ground_truth_evaluator.py`(+`test_report_builder.py` 영향 시). 증거: 각 파일 변경 diff 요약.
- [ ] Step 8(마지막): §6 전체 검증 실행 후 출력 원문 확보.
※ 증거 없는 단계는 미수행으로 간주.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)
- **하드코딩 금지**: 추정계정 키워드·코드·prefix를 함수 본문 리터럴로 박지 말 것 — 전부 `config/audit_rules.yaml`의 `estimate_account_use`에서 입력받는다. 발화를 구동하는 리터럴 계정코드/키워드를 코드에 두면 실패.
- **scope-out 파일·심볼 수정 금지**: `_is_high_risk_account`, `self_approval_immediate_override`(config·함수), `score_aggregator.py` 70/76 `escalated_high_risk_account`, `rule_mapping.py` 라벨 경로, DataSynth 라벨 파일 — 전부 손대지 말 것.
- **테스트 약화 금지**: skip/xfail 추가, assert 삭제·완화, 기대값을 출력에 맞춰 무근거 수정. binary 전환에 따른 기대값 *교체*는 허용(가계정/현금→추정계정, 0.65/0.35/0.20→1.0).
- **DataSynth·외부 문서 count 수정 금지**: 이번 범위 밖(별도 일괄). 라벨 재생성·문서 이름 정합 손대지 말 것.
- 체크리스트 항목 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)
① toy binary 확인:
```bash
uv run python -c "
import pandas as pd
from src.detection.fraud_rules_access import b13_estimate_account_use
df = pd.DataFrame({
  'gl_account': ['109','101','401','295','135'],
  'account_name': ['대손충당금','현금','상품매출','퇴직급여충당부채','이연법인세자산'],
  'document_id': ['d1','d2','d3','d4','d5'],
})
r = b13_estimate_account_use(df)
s = r.attrs['score_series']
print('unique:', sorted(set(s.round(4).tolist())))
print('per_row:', s.tolist())
"
```
→ 기대: `unique: [0.0, 1.0]`, 대손충당금·퇴직급여충당부채·이연법인세자산 행=1.0 / 현금·상품매출 행=0.0. `per_row: [1.0, 0.0, 0.0, 1.0, 1.0]`.
② 폐기물 grep:
```bash
grep -rn "b13_high_risk_account_use\|_high_risk_account_signal_category\|normal_control_candidate\|raw_sensitive_touch_docs" src/ ; echo "exit=$?"
```
→ 기대: 출력 0줄(`exit=1`).
③ 회귀:
```bash
uv run pytest tests/modules/test_detection tests/modules/test_metrics -q
```
→ 기대: 신규 실패 0. 알려진 flaky(`composite_sort_score_v126 MemoryError`, `test_vae_detector::TestTrain`, `duplicate_detector_100k_under_1s`)만 실패 허용. 그 외 1건이라도 실패면 DONE 금지.
※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED로 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지 — **한국어로 보고**)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 각 항목 증거(명령 + 출력 원문 붙여넣기)
변경 파일: 실제 변경한 경로만
최종 검증 결과: §6 ①②③ 출력 원문
미완·우회·우려: 정직하게 전부(없으면 "없음"). 특히 §3-7 라벨 의존·synth 데이터에 추정계정 명칭 부재로 인한 count 변화가 있으면 반드시 명시.

신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로다. 거짓 DONE은 재검증에서 드러나 작업 전체를 재수행하게 된다.
