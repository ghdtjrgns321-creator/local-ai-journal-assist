# PHASE1-1 룰 발화검증 매트릭스 (전수 26룰)

룰 설명(감사 의미)이 detector 실제 조건과 DataSynth 주입에 제대로 연결됐는지 전수 점검한 결과물.

## 모집단 (population-first, §10)

- **N = 26 PHASE1-1 룰.** 권위 출처 3중:
  1. `src/detection/rule_scoring.py::RULE_SCORING_REGISTRY` (점수경로 등록 룰)
  2. `dev/active/datasynth-journal-realism-rebuild/phase1-rule-recall-overlay-verification.md` (2026-06-21 recall scope = 26)
  3. 실제 주입 truth: `data/journal/primary/datasynth_semantic_v1_recall_20260621_v46b_phase1_1_r10/labels/p3_2_rule_truth.csv` (1540행, rule_id 26종)
- **negative-space 증명** (모집단 밖 0건): 제외 14개 ID `L1-09, L3-01, L3-08, L3-12, L4-02, L4-05, L4-06, IC01, IC02, IC03, GR01, GR03, D01, D02` → r10 truth 행수 **각 0** (측정 완료). truth rule_id distinct = 26, 초과 0.
- 검증 데이터셋: r10 (`...v46b_phase1_1_r10`). 코드 기준: 현재 작업트리 `src/detection/`. recall 실측치 770/770(standard)·0/770(boundary FP)는 r9(`v45d`) 기준(overlay 검증문서). r10은 본 감사에서 구조 predicate 충족만 재현(detector 재실행 아님).

## 단위 권위

`docs/spec/UNIT_MEASUREMENT_POLICY.md`: 정당한 truth 단위는 `document`·`flow` 둘뿐. `row`는 증거포인터(단위 아님). `macro_account_group`/`user_behavior_flow` 등 집계뷰는 자기 분모·정답 없는 표시 레이어.

## 분류 체계 (축별)

단일 분류가 아니라 **3축 독립 verdict** + 파생 overall. 한 룰이 한 축은 ok, 다른 축은 깨질 수 있어서(예: 설명 ok인데 datasynth stale) 축을 합치지 않는다.

| 축                     | 값                                                                                   |
| ---------------------- | ------------------------------------------------------------------------------------ |
| `desc_vs_detector`     | ok / desc-stale / impl-owned / conflict                                              |
| `detector_vs_standard` | ok / standard-misfires                                                               |
| `detector_vs_boundary` | ok / boundary-too-loose                                                              |
| `overall`              | ok / description-needs-update / datasynth-needs-fix / detector-needs-fix / ambiguous |

`rule_role`: `primary`(단독 ranking) / `context_tag`(booster, 단독 ranking 불가) / `severity_axis`(OFF-TIME 보조축, tier 게이트 미참여) / `data_integrity`(부정 tier 아님, 정합성 트랙).

---

## 요약 표 (26/26)

```text
rule_id   role            truth_unit          desc_vs_detector  det_vs_standard   det_vs_boundary  overall
--------  --------------  ------------------  ----------------  ----------------  ---------------  ----------------------
L1-01     data_integrity  document            ok                ok                ok               ok
L1-02     data_integrity  document            ok                ok                ok               ok
L1-03     data_integrity  document            ok                ok                ok               ok
L1-04     primary         flow                ok                ok                ok               ok
L1-05     primary         document            ok                ok                ok               ok
L1-06     primary         user_behavior_flow  ok                ok                ok               datasynth-needs-fix(라벨)
L1-07     primary         flow                ok                ok                ok               ok
L1-07-02  primary         document            ok                ok                ok               ok
L1-08     primary         document            ok                ok                ok               ok
L2-01     primary         flow                ok                ok                ok               ok(변이명 cosmetic)
L2-02     primary         duplicate_flow      ok                ok                ok               ok
L2-03     primary         duplicate_flow      ok                standard-misfires ok               datasynth-needs-fix
L2-04     primary         document            ok                ok                ok               datasynth-needs-fix(라벨)
L2-05     primary         reversal_flow       ok                ok                ok               ok(변이설명 주의)
L3-02     primary         document            ok                ok                ok               ok
L3-03     context_tag     document            ok                ok                ok               ok
L3-04     primary         document            ok                ok                ok               ok(함수명 stale)
L3-05     severity_axis   document            ok                ok                ok               ok
L3-06     severity_axis   document            ok                ok                ok               ok
L3-07     primary         document            ok                ok                ok               ok
L3-09     primary         open_item_flow      ok                ok                ok               ok
L3-10     context_tag     document            ok                ok                ok               datasynth-needs-fix(라벨)
L3-11     primary         flow                ok                ok                ok               ok
L4-01     primary         macro_account_group ok                ok                ok               datasynth-needs-fix(단위)
L4-03     primary         flow                ok                ok                ok               ok(라벨 cosmetic)
L4-04     primary         document            ok                ok                ok               ok
```

### 액션 버킷 (2026-06-22 정정 반영)
- **그대로 사용 (ok / cosmetic)**: L1-01, L1-02, L1-03, L1-04, L1-05, L1-07, L1-07-02, L1-08, L2-01, L2-02, L2-05, L3-02, L3-03, L3-04, L3-05, L3-06, L3-07, L3-09, L3-11, L4-03, L4-04 (21)
- **DETECTION_RULES.md 보강 (description-needs-update)**: 0건 (구 L1-02·L2-02는 문서가 이미 맞아 ok로 정정 — 부록 B)
- **DataSynth 수정 (datasynth-needs-fix, 라벨/단위 위생)**: L1-06, L2-03, L3-10, L4-01, L2-04 (5)
- **사용자/설계 결정 (ambiguous)**: 0건 (구 L2-04는 발화 정상이라 datasynth 라벨 위생으로 강등)
- **detector 수정 (detector-needs-fix)**: 0건

> 핵심: datasynth-needs-fix 5건 중 L4-01(단위)을 빼면 전부 **발화가 깨진 게 아니라 truth 메타데이터(변이명)가 binary 재설계 이전 어휘로 남은 라벨 위생 문제**다. 실제 주입 journal은 현재 detector predicate를 구조적으로 충족함을 r10 journal 직접 확인으로 재현(§9 hollow-PASS 검사 통과). **DETECTION_RULES.md 자체와 충돌하는 룰은 0건이다.**

---

## 룰별 상세 (전수)

각 블록: detector_fn / raw_predicate(현재 코드) / injected_raw_column(r10 journal 실측) / standard_variants / boundary_controls / 3축 verdict / issue / fix.

### L1-01 차대변 불균형 — data_integrity
- detector_fn: `integrity_layer.py::_a01_unbalanced_entry`
- raw_predicate: `document_id`별 |Σdebit−Σcredit| > tolerance(기본 1.0). strict `>`.
- injected_raw_column: `debit_amount`,`credit_amount`,`document_id`
- standard: edge/small/large/missing_multiline_leg/currency_residual (전표 잔차 tolerance 초과). boundary: 동일 변이 잔차 직하(미발화).
- verdict: desc=ok / std=ok / bnd=ok → **ok**. (note: currency_residual은 코드가 통화 환산을 안 하므로 원화 합산 잔차로 주입돼야 함)

### L1-02 필수필드 누락 — data_integrity
- detector_fn: `integrity_layer.py::_a02_missing_required`
- raw_predicate: CAT1{document_id,gl_account,debit_amount,credit_amount,posting_date} ∪ CAT2{company_code,fiscal_year,fiscal_period,document_date,document_type} 중 하나라도 NULL/공백. **required 전체가 아니라 이 10개 화이트리스트만 검사.**
- injected_raw_column: document_type/posting_date/다중 blank (화이트리스트 내)
- standard: missing_document_type/posting_date/multiple. boundary: 채움(미발화).
- verdict: ok/ok/ok → **ok** (2026-06-22 정정).
- 정정 사유: 문서 카드(82~86줄)에 cat1/cat2/cat3 표가 이미 있고 코드 상수 `_L102_CAT1_FIELDS`/`_L102_CAT2_FIELDS`와 글자까지 일치. 초기 서브에이전트가 80줄만 읽고 표를 놓쳐 desc-stale로 오판한 것을 코드+문서 직접 대조로 ok 정정.

### L1-03 무효 계정 — data_integrity
- detector_fn: `integrity_layer.py::_a03_invalid_account`
- raw_predicate: `gl_account` 정규화(`.0` 접미사 제거) 비공백 AND CoA 집합에 부재. CoA 미제공 시 skip.
- injected_raw_column: `gl_account`(CoA 밖: 미등록/형식오류/placeholder)
- verdict: ok/ok/ok → **ok**. (note: placeholder가 정규화로 CoA 유효값이 되지 않게 주의)

### L1-04 승인한도 초과 — primary, unit=flow
- detector_fn: `fraud_rules_feature.py::b03_exceeds_threshold` (+ feature `amount_features.add_exceeds_threshold`)
- raw_predicate: `approved_by`→employees.json 한도조회. `candidate = has_approver & ( (resolved & 전표총액>한도) | (approver_in_master & (can_approve_je==False | ~resolved)) )`. **`approver_in_master` 게이트로 실재 직원만** 권한초과; 마스터 부재는 L1-07-02 소관(중복 없음).
- injected_raw_column: `approved_by`+전표 debit/credit합+`employees.json`(approval_limit,can_approve_je)
- standard: 소폭/대폭/authority bucket 초과. boundary: 한도 직하(미발화, strict `>`).
- verdict: ok/ok/ok → **ok**. L1-04↔L1-07-02 경계 코드상 명확 분리 확인.

### L1-05 자기 승인 — primary, unit=document
- detector_fn: `fraud_rules_access.py::b06_self_approval` (+ source_trust.lone_automated_mask)
- raw_predicate: `created_by!="" & approved_by!="" & created_by==approved_by` AND NOT allowed(persona/source/code allowlist; 단 lone_automated 위장의심이면 예외 취소).
- injected_raw_column: `created_by`,`approved_by`,`user_persona`,`source`
- standard: 동일인/거액/R2R 자기승인. boundary: 타인 승인(미발화).
- verdict: ok/ok/ok → **ok**. (거액 변이가 allowlist persona를 달면 미발화 위험 — human persona·non-allowlist source로 주입할 것)

### L1-06 직무분리 위반 — primary, unit=user_behavior_flow ★
- detector_fn: `fraud_rules_access.py::b07_segregation_of_duties`
- raw_predicate: **`sod_conflict_type` 컬럼 안 읽음.** `created_by`(person)별 회기 내 `business_process` 집합을 groupby → `config/sod_toxic_combinations.yaml` red pair `issubset` 매칭 시 발화(RED만 score 1.0, YELLOW 노트). `user_persona`는 automated_system 제외 필터일 뿐 발화원 아님(IT-admin 양성경로 없음).
- injected_raw_column(r10 실측): `sod_conflict_type`=**공백**, `sod_violation`=false. 발화는 `created_by` 10명이 연중 **9개 process 전부**(TRE,P2P,R2R,O2C…) span → toxic red쌍(TRE+P2P 등) 성립으로 발생.
- standard 변이명: direct_cash_disbursement_conflict / it_admin_financial_posting / large_sod_conflict (모두 stale 어휘). boundary: 충돌 없음.
- verdict: desc=ok / **std=ok(실제 발화)** / bnd=ok → **datasynth-needs-fix(라벨 위생)**.
- issue: ① 변이명·`raw_trigger_summary`("non-empty sod_conflict_type", "IT administrator persona")가 폐기된 메커니즘을 가리킴(실제 주입은 toxic-pair 구조라 발화는 정상). ② 주입 사용자가 9개 process 전부 span = 비현실(realism MONITOR — 어떤 toxic 정의든 발화). fix: 변이명/summary를 toxic-pair 어휘로 교체, 사용자별 process span을 red pair 2~3개로 현실화.

### L1-07 승인 생략 — primary, unit=flow
- detector_fn: `fraud_rules_access.py::b09_skipped_approval`
- raw_predicate: `approved_by.eq("")` (공란이면 무조건). 7컴포넌트(`_skipped_approval_components`)는 계산되나 최종 mask 미사용(dead).
- injected_raw_column: `approved_by`(공란)
- standard: 한도초과무승인/수기무승인/TRE. boundary: 승인 채움(미발화).
- verdict: ok/ok/ok → **ok**. L1-07(공란) vs L1-07-02(비공란+마스터부재) 상호배타 확인.

### L1-07-02 유령 승인자 — primary, unit=document
- detector_fn: `fraud_rules_access.py::b09b_unknown_approver` (+ `_compute_approver_info.approver_in_master`)
- raw_predicate: `approved_by!="" & approver_in_master==False`. approver_in_master = employees.json user_id 멤버십(공란→NA).
- injected_raw_column: `approved_by`(비공란)+`employees.json`(해당 ID 누락)
- verdict: ok/ok/ok → **ok**. (마스터 미로드 시 graceful skip — standard는 employees.json 존재+해당 ID만 누락으로 주입)

### L1-08 기간 불일치 — primary(dual), unit=document
- detector_fn: `anomaly_rules_simple.py::c05_fiscal_period_mismatch` (+ `time_features.add_fiscal_period_mismatch`)
- raw_predicate: `expected = (posting_month − fiscal_year_start)%12 + 1`; mismatch = `fiscal_period != expected`. 둘 다 non-null 필수(NaN→미발화). strict_mode(기본 True)면 raw 그대로 final.
- injected_raw_column: `fiscal_period`,`posting_date`
- verdict: ok/ok/ok → **ok**. (비표준 회계연도면 주입 월/기수가 `fiscal_year_start` 가정과 정합해야)

### L2-01 승인한도 직하 — primary, unit=flow
- detector_fn: `amount_features.add_is_near_threshold` + `fraud_rules_feature.b02_near_threshold`
- raw_predicate: 한도 조회 성공 AND `한도×0.90 ≤ 전표총액 < 한도`. binary(밴드 폐기, bucket은 표시용).
- injected_raw_column: `approved_by`+employees.json `approval_limit`+전표 debit합
- standard: lower 92%/close 96%/razor 99%(셋 다 90~100% 구간 → 발화). boundary: 88% 등 직하(미발화).
- verdict: ok/ok/ok → **ok**. (변이명 lower/close/razor는 폐기된 밴드 어휘 — cosmetic, 발화 영향 없음)

### L2-02 중복 지급 — primary, unit=duplicate_flow
- detector_fn: `fraud_rules_groupby.py::b04_duplicate_payment`
- raw_predicate: P2P scope(business_process=P2P & document_type∈{KZ,KR}). 강신호=같은 partner+정규화 reference+근사금액(±2%/10만)+다른 doc; 약신호=reference 없으면 90일+비정기 게이트. document 단위 집계.
- injected_raw_column: `business_process`,`document_type`,partner_key,`reference`,금액,`posting_date`
- standard: same_reference/near_day/ocr_variation. boundary: 윈도우 밖(미발화).
- verdict: ok/ok/ok → **ok** (2026-06-22 정정).
- 정정 사유: 카드(300~329줄)가 reference 정규화(304), 강신호 윈도우 무관(312), mixed/blank/amount_partner fallback(317~323), 정기지급 suppress(310·324)를 이미 서술. 코드가 문서를 어기지도, 문서가 코드보다 낡지도 않음. 초기 impl-owned 판정은 카드 미정독 오판. (주의: reference_match 강신호는 윈도우 무시 — boundary 설계 시 reference도 달라지게 주입)

### L2-03 중복 전표 — primary, unit=duplicate_flow ★
- detector_fn: `fraud_rules_groupby.py::b05_duplicate_entry`
- raw_predicate: 2경로 OR — (가)reference 재기표[다른 doc+같은 reference+같은 gl_account+같은 부호+±2% 금액] 또는 (나)완전복제[gl_account+금액+posting_date+entry_side(+partner+line_text) 전부 동일]. **fuzzy/split/time_shift 발화로직 없음**(시그니처 `fuzzy_threshold`/`split_window_days` 등은 dead param; fuzzy/split은 별도 트랙 `duplicate_rules.py::DuplicateDetector`로 L2-03 미연결).
- injected_raw_column(r10 실측): 4 변이 전부 reference·금액 공유(nref=1) → 전부 (가) 경로로 발화. 즉 발화 자체는 정상.
- standard 변이명: exact/fuzzy/split/time_shift (뒤 3개 stale — L2-03 재설계로 폐기/PHASE1-2 이관됨). boundary: 직하(미발화).
- verdict: desc=ok / **std=standard-misfires** / bnd=ok → **datasynth-needs-fix**.
- issue: 변이명 4종 중 fuzzy/split/time_shift는 현 L2-03이 탐지 안 하는 메커니즘인데 truth가 reference-dupe로 주입+그 이름으로 라벨 → 변이 다양성이 가짜(1 메커니즘 4중복). recall은 안 깨지나 "L2-03이 fuzzy/split도 잡는다"는 오해 유발. fix: fuzzy/split/time_shift를 L2-03 standard에서 제거(또는 PHASE1-2/별도 트랙 재라벨), exact+reference 재기표 변이만 유지.

### L2-04 비용 자산화 — primary, unit=document
- detector_fn: `fraud_rules_groupby.py::b11_expense_capitalization`
- raw_predicate: 한 전표 내 자산차변(gl 12/15) ∩ 비용대변(gl 5/6/7/8), line별 ±2% 매칭 또는 자산차변합≈비용대변합 → binary 발화. **키워드 가감 코드 없음**(재설계 반영).
- injected_raw_column: `gl_account`,`debit_amount`,`credit_amount`
- injected_raw_column(r10 실측): 두 변이 모두 자산차변합 == 비용대변합(정확 일치, 예 1500↔6300) → 둘 다 line_amount_match로 발화. "공존만(금액 불일치)" 케이스는 datasynth 미주입.
- standard: immediate_asset_expense_match / review_asset_expense_coexistence (둘 다 금액매칭=발화). boundary: 금액차 큼(미발화).
- verdict: desc=ok / std=ok(둘 다 발화) / bnd=ok → **datasynth-needs-fix(라벨)** (2026-06-22 정정, 구 ambiguous에서 강등).
- 정정 사유: 문서·코드 모두 "자산차변합≈비용대변합 binary 발화"로 일치. r10에서 `review_...` 변이도 금액 정확 일치라 발화 → recall 정상. 따라서 설계 결정 불요. 남은 건 (a) 변이명 `review_asset_expense_coexistence`가 실제론 금액매칭(immediate)을 넣어 오해 유발(라벨 위생), (b) 코드 `review_score_series`가 0초기화 후 미사용 죽은 뼈대(청소 대상, 버그 아님). fix: 변이명을 매칭 의미로 교체(또는 진짜 금액불일치 공존 케이스를 boundary로 추가). 선택 설계: 금액불일치 단순 공존을 약한 review로 띄울지는 별도 결정(현재 미주입이라 당장 무영향).

### L2-05 역분개 — primary, unit=reversal_flow
- detector_fn: `anomaly_rules_reversal.py::c11_reversal_entry`
- raw_predicate: S0(ERP 링크필드 original/reversal/reference_document_id 등) OR S1(같은 gl_account 1:1 반대부호 ±2% 90일내 다른 doc 거울쌍). **S2(N:M 순액0)·S2b(단일라인 스왑)·점수가감 폐기**.
- injected_raw_column: 구조필드 5종 / `gl_account`+부호+금액+`posting_date`+`document_id`
- standard: S0링크/1:1거울쌍/거액. boundary: 구조 미성립(미발화).
- verdict: ok/ok/ok → **ok**. (변이설명의 "수기·기말" 한정은 c11에 미구현 — S0는 ERP 링크만으로 발화. 발화 자체는 정상)

### L3-02 수기 전표 — primary(context fact), unit=document
- detector_fn: `fraud_rules_feature.py::b08_manual_override`
- raw_predicate: `is_manual_je` bool, 없으면 `source.lower() ∈ {manual,adjustment}`. 금액·기말 안 봄(annotation만).
- injected_raw_column: `source`(=Manual)
- standard: 거액/기말/단순 수기. boundary: 자동 source(미발화).
- verdict: ok/ok/ok → **ok**.

### L3-03 관계사 거래 신호 — context_tag(booster), unit=document
- detector_fn: `fraud_rules_access.py::b10_intercompany_review_signal`
- raw_predicate: `is_intercompany` OR `gl_account` startswith IC prefix(코드 기본 `["1150","2050","4500","2700"]`; config `intercompany_identifiers` 키 부재로 리터럴 기본값). 순환은 GR01 소관.
- injected_raw_column(r10 실측): `gl_account`=**1150/2050**(IC prefix) → prefix 경로 발화. is_intercompany=false라도 발화(미확인 해소).
- verdict: ok/ok/ok → **ok**. (minor: config에 `intercompany_identifiers` 명시 권장 — 현재 코드 리터럴 의존)

### L3-04 기말/기초 결산 — primary(timing), unit=document
- detector_fn: `anomaly_rules_simple.py::c01_period_end_large`
- raw_predicate: `is_period_end` OR `is_period_start`(월말 ≤5일전 또는 월초 ≤5일). 금액 안 봄.
- injected_raw_column: `posting_date`(파생 is_period_end/start)
- verdict: ok/ok/ok → **ok**. (함수명 `_period_end_large`의 `large`는 stale 잔재 — 동작 영향 없음)

### L3-05 주말/공휴일 — severity_axis, unit=document
- detector_fn: `anomaly_rules_simple.py::c02_weekend_entry`
- raw_predicate: `is_weekend` OR `is_holiday`(실제 토/일/KR공휴일). **source 안 봄** — 자동전표 주말도 발화.
- injected_raw_column: `posting_date`(파생 is_weekend/is_holiday)
- standard: 토/일/공휴일/연휴. boundary: 평일(미발화).
- verdict: ok/ok/ok → **ok**. (boundary = "발화하되 정상"이 아니라 "평일=미발화"; 자동전표 주말 정상성은 통합점수가 다운웨이트 — 재설계 의도와 정합. context-tag/severity-axis라 룰 레벨에서 source 억제 안 함이 정답)

### L3-06 심야 전기 — severity_axis, unit=document
- detector_fn: `anomaly_rules_simple.py::c03_after_hours_entry`
- raw_predicate: `is_after_hours`(22~06시). source 안 봄. 시각정보 없으면 전건 미발화.
- injected_raw_column: `posting_date`(시각 포함)
- verdict: ok/ok/ok → **ok**.

### L3-07 전기일-문서일 괴리 — primary(timing), unit=document
- detector_fn: `anomaly_rules_simple.py::c04_backdated_entry`
- raw_predicate: `abs(days_backdated) > 30`. 절댓값 → 지연(+)·선전기(−) 양방향. 폭·방향 점수 폐기(binary).
- injected_raw_column: `posting_date`,`document_date`(파생 days_backdated)
- standard: 45일/선행기표/90일초과. boundary: 30일 직하(미발화).
- verdict: ok/ok/ok → **ok**. (코드가 날짜 재계산 안 하고 days_backdated 컬럼 신뢰 — 주입 시 정확히 채울 것)

### L3-09 가수금 장기체류 — primary, unit=open_item_flow
- detector_fn: `anomaly_rules_simple.py::c10_suspense_account`
- raw_predicate: `is_suspense_account & 해소신호존재 & unresolved & aging_days≥30`. unresolved = amount_open>min / is_cleared=False / settlement_status∉{settled..} / (폴백)settlement·lettrage 결측. aging = (settlement_date or dataset_end) − posting.
- injected_raw_column(r10 실측): `gl_account`=1190, `settlement_status`=open, `settlement_date`=posting+45일, `amount_open` 채움 → 발화(미확인 해소).
- standard: settlement+45일/거액미청산. boundary: 29일(미발화, `≥30`).
- verdict: ok/ok/ok → **ok**.

### L3-10 추정계정 사용 — context_tag(booster), unit=document ★
- detector_fn: `fraud_rules_access.py::b13_estimate_account_use` (rename 완료; `b13_high_risk_account_use`는 src 0건)
- raw_predicate: 3축 OR — account_name 추정계정 키워드 / `gl_account` exact ∈ {116100,119100,169100,237100,682100} / prefix ∈ account_prefixes(현재 `[]`). config `patterns.estimate_account_use`(audit_rules.yaml).
- injected_raw_column(r10 실측): `gl_account`=**119100(대손충당금)·237100(충당부채)·682100(손상)·116100(계약자산)**, subtype=ALLOWANCE_DOUBTFUL_ACCOUNTS 등 → 현재 estimate config exact 매칭으로 **발화 정상**.
- standard 변이명: advance_account_1190 / suspense_account_2190 / cash_prefix_111 / large_priority_high_risk (전부 stale — 구 High-risk Account 어휘). boundary: 직하.
- verdict: desc=ok / **std=ok(실제 발화)** / bnd=ok → **datasynth-needs-fix(라벨 위생)**.
- issue: 변이명·`raw_trigger_summary`("gl_account 1190 used" 등)가 폐기된 가지급금/가수금/현금 어휘를 가리킴(실제 주입은 추정계정이라 발화는 정상, recall hollow 아님). fix: 변이명/summary를 추정계정 어휘(대손충당금 119100·손상 682100·충당부채 237100 등)로 교체.

### L3-11 기말 컷오프 — primary(timing), unit=flow
- detector_fn: `evidence_rules.py::ev02_cutoff_violation`
- raw_predicate: `delivery_year ≠ recognition_year`(recognition = fiscal_year, 없으면 posting.year) AND in_scope(매출 prefix 4 또는 비용 prefix 5) AND testable. **일수 임계 폐기**(day_diff는 참고값).
- injected_raw_column: `delivery_date`,`posting_date`/`fiscal_year`,`gl_account`(4/5)
- standard: 인도전인식/결산후/기말조기인식. boundary: posting≈delivery 같은 연도(미발화).
- verdict: ok/ok/ok → **ok**. (in_scope 밖 자산/부채 계정 cutoff는 미대상)

### L4-01 상대적 고액 매출 — primary(statistical), unit=macro_account_group ★
- detector_fn: `fraud_rules_feature.py::b01_revenue_manipulation` (z-score: `amount_features.add_amount_zscore`)
- raw_predicate: `is_revenue_account & amount_zscore > 3.0` binary. z-score = gl_account 그룹분포(n<30 시 상위그룹/전체 fallback). detector는 **개별 라인을 flag**.
- injected_raw_column: 매출계정 정상배경 35건 + 스파이크 1건(86억, z≫3)
- standard: single/alternate_revenue_gl_spike. boundary: z<3(미발화).
- verdict: desc=ok / std=ok / bnd=ok → **datasynth-needs-fix(단위)**.
- issue: truth `expected_measurement_unit=macro_account_group`인데 UNIT_MEASUREMENT_POLICY상 macro_account_group은 집계뷰(자기 분모·정답 없는 표시 레이어)이지 truth 단위 아님. detector는 라인(→document)을 flag. fix: `expected_measurement_unit`을 `document`로 교정(스파이크 전표/라인이 증거포인터, 계정모집단은 산출 맥락).

### L4-03 절대 이상 고액 — primary(statistical), unit=flow
- detector_fn: `anomaly_rules_simple.py::c08_amount_outlier` (+ `_compute_pbt_thresholds`)
- raw_predicate: **절대 수행중요성 임계 `max(debit,credit) ≥ thr` binary** (z-score 아님 — 코드 확정). thr = 회사×연도 NI(마감분개 우선)×pbt_pct×pm_ratio, 매출 floor. config `patterns.l403_materiality`.
- injected_raw_column: `debit_amount`/`credit_amount`,`company_code`,`fiscal_year`,`semantic_account_subtype`. 스파이크 86억 ≫ 임계(≈3.2억) → 발화(구조적).
- standard 변이명: account_q95_outlier / extreme_amount_outlier (z-score/분위 어휘 stale). boundary: 직하(미발화).
- verdict: desc=ok / std=ok / bnd=ok → **ok(cosmetic)**.
- issue(경미): 변이명·raw_trigger가 구 z-score 어휘인데 실제 의미·detector는 절대 PM 임계(주입 금액 로직은 이미 절대고액, 발화 영향 없음). `labels/rule_truth_L4_03*`도 구 z-score 기준(DETECTION_RULES 813-814). fix: 변이명/summary를 PM-임계 어휘로 정리, labels 재산출.

### L4-04 희소 차대 계정쌍 — primary, unit=document
- detector_fn: `anomaly_rules_statistical.py::c09_rare_account_pair` (+ `_engagement_rare_thresholds`)
- raw_predicate: engagement(회사×연도)별 (차변계정,대변계정) 쌍 빈도 ≤ cadence임계(`round(분기수×cadence)−1`). **percentile(0.01) 폐기**. 희소쌍 든 전표 전 라인 binary 1.0.
- injected_raw_column: `document_id`,`gl_account`,`debit/credit_amount`,`posting_date`,`company_code`,`fiscal_year`. 희소쌍(예 1590↔8010) 빈도 1.
- standard: frequency_one/abnormal_pair. boundary: 흔한쌍(미발화).
- verdict: ok/ok/ok → **ok**. 단위 document 정합.

---

## 부록 A — 문서 카운트 불일치 (description-needs-update, 별건)

canonical L1~L4 룰 수 권위 = **29** (`RULE_DETAIL_METADATA_V1_LOCK.md` Final Decisions, 2026-06-20; L3-01·L3-08·L4-02 제외). 아래는 stale:
- `DETECTION_RULES.md` §2.3 헤더(line 476) "31→30" — stale(29여야).
- `RULE_DETAIL_METADATA_V1_LOCK.md` Implementation Sequence step6·Test Gate "count is exactly 30" — 본문 Final Decisions(29)와 자기모순.
- `CLAUDE.md` 인덱스 "31 canonical" — stale.

> 주: 본 발화검증 매트릭스의 N=26은 canonical 29 중 PHASE1-1 **recall overlay 대상**(L3-12 review-only·L1-01~03 정합성 포함 여부와 별개로, 주입·발화 검증 대상 26)이다. 29(canonical 카드 수) vs 26(주입검증 대상)은 다른 분모 — 29 = 26 + L3-12(review-only, 주입검증 비대상) + L1-09는 폐기라 29에도 미포함. 정확히는 29 canonical = 26 발화룰 + L3-12 + (L1 정합성 3개는 이미 26에 포함) → 카운트 정의는 후속 정리 필요.

## 부록 B — 방법론·§9 교정 기록

서브에이전트(레이어별 detector 코드 대조)는 처음 L1-06·L2-03·L3-10을 "datasynth-needs-fix, 발화 깨짐(recall hollow 의심)"으로 보고했다. 이는 본인이 넘긴 truth 메타데이터(`variant_name`·`raw_trigger_summary`)를 신뢰한 결과였다. **§9에 따라 r10 journal 실제 주입 행을 직접 확인(member_document_ids→journal join)한 결과**:
- L3-10: 실제 gl_account = 119100/237100/682100/116100(추정계정) — 변이명(1190 등)과 다름. 발화 정상.
- L1-06: sod_conflict_type 공백, 사용자가 9개 process span → toxic쌍 발화. 발화 정상.
- L2-03: 4 변이 전부 reference 공유 → (가) 경로 발화. 발화 정상.

→ 세 건 모두 "발화 깨짐"이 아니라 "truth 메타데이터 어휘가 binary 재설계 이전으로 lag"한 **라벨 위생** 문제로 강등. 존재(변이명)≠사용(실제 주입 컬럼) 함정을 직접 측정으로 회피.

### 2026-06-22 2차 정정 — L1-02·L2-02·L2-04 과대 플래그 철회

초판은 L1-02(desc-stale), L2-02(impl-owned)를 "description-needs-update", L2-04를 "ambiguous"로 올렸다. 사용자 지적으로 **DETECTION_RULES.md 카드와 코드를 직접 재대조**한 결과 셋 다 오판이었다:
- **L1-02**: 카드 82~86줄에 cat1/cat2/cat3 표가 이미 존재, 코드 `_L102_CAT1_FIELDS`/`_L102_CAT2_FIELDS`와 글자까지 일치 → **ok**. (서브에이전트가 80줄만 보고 표를 놓침)
- **L2-02**: 카드 300~329줄이 reference 정규화·윈도우 무관·3종 fallback·정기지급 suppress를 이미 서술 → **ok**. (코드가 문서를 어기지 않음)
- **L2-04**: 문서·코드 일치(금액매칭 binary). r10에서 `review` 변이도 금액 정확 일치라 발화 → 설계 결정 불요. 변이명 오해 + 죽은 review_score_series만 남아 **datasynth-needs-fix(라벨)**로 강등.

교훈: **detector 코드만 읽고 "문서가 낡았다"고 판정하면 안 된다 — 문서 카드 본문(표 포함)을 같은 줄 범위로 직접 대조해야 한다.** 결과적으로 DETECTION_RULES.md와 실제 충돌하는 PHASE1-1 룰은 **0건**이며, 모든 잔여 수정은 DataSynth truth 메타데이터(변이명 4건 + 단위 1건) 쪽이다.
