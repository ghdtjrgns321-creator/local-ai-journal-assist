# DataSynth 전수 품질검사 리포트
> 실행일: 2026-03-28 23:25 | 소요: 8.4s | 판정: **FAIL**

## 요약
| Tier | 이름 | Pass | Fail | Warning | Skip | 판정 |
|------|------|------|------|---------|------|------|
| T1 | 구조적 무결성 | 10 | 4 | 0 | 0 | FAIL |
| T2 | 값 도메인 + 비즈니스 논리 | 19 | 2 | 7 | 0 | FAIL |
| T3 | 교차검증 | 19 | 2 | 9 | 0 | FAIL |
| T4 | 분포 + config 정합 | 12 | 0 | 9 | 0 | WARNING |
| T5 | 라벨 + Silent Failure + 메타데이터 | 16 | 0 | 5 | 1 | WARNING |

## Tier 1: 구조적 무결성
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T1-01 | 행수/컬럼수 | PASS | rows=1,104,914; cols=39 | rows=1,105,110; cols=39 |
| T1-02 | 필수컬럼 존재+dtype | PASS | 필수 10컬럼 존재 + 올바른 dtype | OK |
| T1-03 | 보호필드 NOT NULL | PASS | document_id/company_code/posting_date NULL=0 | null_doc=0, null_cc=0, null_pd=0 |
| T1-04 | 금액 음수 | FAIL | 음수 금액=0 (ReversedAmount 등 제외) | neg_count=1 |
| T1-05 | 전표 대차일치 | FAIL | 대차불일치 전표=0 (금액변형 anomaly 제외) | unbalanced_docs=14 |
| T1-06 | company_code 도메인 | PASS | company_code IN (C001,C002,C003) | out_of_domain=0 |
| T1-07 | 기간 범위 | FAIL | fiscal_year=2022, period=1~12, posting_date≈2022 | bad_fy=286, bad_fp=0, date_out_of_range=3,705 |
| T1-08 | 라벨 orphan | PASS | orphan labels=0 | orphan_count=0 |
| T1-09 | 단일행 전표 | PASS | 단일행 전표=0 (UnbalancedEntry+MissingField 제외) | single_line_docs=0 |
| T1-10 | KRW 소수점 | PASS | 소수점 금액=0 (KRW) | fractional_count=0 |
| T1-11 | 문서 내 일관성 | FAIL | 문서 내 company_code/posting_date 불일치=0 | inconsistent_docs=1 |
| T1-12 | gl_account 형식 | PASS | gl_account 형식 불일치=0 (InvalidAccount+DormantAccount... | bad_format=0 |
| T1-13 | document_type MCAR 비율 | PASS | MCAR 빈값 비율 0.5~4% (전역 2% 적용) | null_or_empty=27,932 (2.53%) |
| T1-14 | gl_account MCAR 비율 | PASS | MCAR 빈값 비율 0.5~4% (전역 2% 적용) | null_or_empty=22,036 (1.99%) |

## Tier 2: 값 도메인 + 비즈니스 논리
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T2-01 | 39컬럼 프로파일링 | PASS | 정보 제공용 | 39컬럼 프로파일 완료 |
| T2-02 | debit/credit 상호배타 | PASS | 동시 양수=0 | both_positive=0 |
| T2-03 | debit=0 AND credit=0 | WARNING | 비율 ≤ 1% | zero_both=50,488 (4.57%) |
| T2-04 | fiscal_period==month | PASS | 불일치=0 (timing anomaly 제외) | mismatch=0 |
| T2-05 | fiscal_year==year | PASS | 불일치=0 (timing anomaly 제외) | mismatch=0 |
| T2-06 | doc_date<=posting_date | PASS | 역전=0 (FutureDated+Backdated 제외) | reversed=0 |
| T2-07 | CoA 미등록 GL | PASS | 미등록 GL=0 (InvalidAccount 등 제외) | unregistered=0 |
| T2-08 | document_type 도메인 | PASS | 허용값: ('SA', 'KR', 'KG', 'DZ', 'DR', 'WE', 'RE', 'A... | OK |
| T2-09 | user_persona 도메인 | PASS | 허용값: ('automated_system', 'junior_accountant', 'se... | OK |
| T2-10 | business_process 도메인 | PASS | 허용값: ('P2P', 'O2C', 'R2R', 'H2R', 'TRE', 'A2R') | OK |
| T2-11 | source 도메인 | PASS | 허용값: ('automated', 'manual', 'recurring', 'adjustm... | OK |
| T2-12 | currency 단일 | PASS | KRW만 | distinct=['KRW'] |
| T2-13 | exchange_rate 단일 | PASS | exchange_rate=1만 | distinct=[1] |
| T2-14 | trading_partner NULL 비율 | WARNING | NULL ≤ 95% (IC 라벨 제외) | null=1,092,360 (98.8%) |
| T2-15 | is_fraud↔fraud_type 정합 | PASS | 불일치=0 | fraud_no_type=0, type_no_fraud=0 |
| T2-16 | approved_by↔approval_date 쌍 | PASS | approved_by 있는데 approval_date 없음=0 | orphan_approval=0 |
| T2-17 | line_number 순차 | FAIL | 갭 있는 문서=0 | gap_docs=196 |
| T2-18 | junior 1억 초과 | WARNING | junior 1억 초과=0 (전결규정은 승인 한도, 작성 한도 아님. 승인 한도 검증은 B... | violations=1,132 |
| T2-19 | approval_date>=posting_date | PASS | 사전승인 위반=0 (LateApproval+SkippedApproval+LatePostin... | pre_post_violations=0 |
| T2-20 | automated 제3자승인 | WARNING | automated+제3자승인=0 (ManualOverride 등 제외) | anomalies=688,449 |
| T2-21 | GL prefix↔process | WARNING | P2P+GL불일치 ≤ 20% | P2P total=266,976, bad_prefix=181,432 (68.0%) |
| T2-22 | doctype↔process 매핑 | PASS | 매핑 위반=0 | violations=0 |
| T2-23 | Self-offsetting | WARNING | self-offset 쌍=0 (GL 2900/1150/2050+ReversedAmount ... | self_offset_pairs=71 |
| T2-24 | 수익계정 차변 비율 | PASS | 4xxx debit ≤ 10% | 4xxx total=218,286, debit=1,354 (0.6%) |
| T2-25 | tax_code 100% NULL | WARNING | 설계상 tax_code 미사용 (WARNING=정상) | non_null=0 |
| T2-26 | cost_center 형식 | PASS | cost_center LIKE 'CC%' | bad_format=0 |
| T2-27 | profit_center 형식 | PASS | profit_center LIKE 'PC-%' | bad_format=0 |
| T2-28 | sod↔conflict_type 정합 | FAIL | sod=true+type없음=0 | orphan_sod=6 |

## Tier 3: 교차검증
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T3-01 | vendor FK | PASS | orphan=0 | orphan=0 |
| T3-02 | customer FK | PASS | orphan=0 | orphan=0 |
| T3-03 | employee FK | FAIL | orphan=0 | orphan=152 |
| T3-04 | persona 일치 | PASS | mismatch=0 | mismatch=0 |
| T3-05 | employee company 일치 | PASS | mismatch=0 | mismatch=0 |
| T3-06 | vendor 커버리지 | PASS | >=50% | 60/60 (100.0%) |
| T3-07 | customer 커버리지 | PASS | >=50% | 90/90 (100.0%) |
| T3-08 | employee 커버리지 | PASS | >=50% | 152/204 (74.5%) |
| T3-09 | junior TRE 금지 | PASS | 0건 (SoD 제외) | 0건 |
| T3-10 | junior 단일 프로세스 | PASS | multi-process junior=0 (SoD 제외) | 0명 |
| T3-11 | controller R2R 집중 | PASS | R2R >= 80% | 89.0% (32444/36446) |
| T3-12 | approval_limit | PASS | 초과=0 (ExceededApprovalLimit 제외) | 0건 |
| T3-13 | can_approve_je | PASS | 무권한 승인=0 (SelfApproval/SkippedApproval 제외) | 0건 |
| T3-14 | reference FK | PASS | orphan=0 | orphan=0/364 |
| T3-15 | P2P 순서 | PASS | PO<=GR<=VI (DuplicatePayment 제외) | 역전=0건 |
| T3-16 | P2P 금액 매칭 | WARNING | PO≈VI (±5%) | 불일치=1건 |
| T3-17 | O2C 순서 | PASS | SO<=DLV<=CI | 역전=0건 |
| T3-18 | 지급기한 분포 | PASS | 합리적 지급기한(0~120일) | avg=37.2, min=0, max=60 |
| T3-19 | GR/IR 청산 | WARNING | WE 전표에 GL 2900 라인 | 미포함=1/61 |
| T3-20 | delivery COGS | PASS | WL 전표에 GL 5000 라인 | 미포함=0/24 |
| T3-21 | cross_process_links 순서 | WARNING | source_date <= target_date | 역전=15/15 |
| T3-22 | AP 대사 | WARNING | AP≈GL2000 (±5%) | AP=25,237,107, GL=350,609,737,992, diff=1389162.8% |
| T3-23 | AR 대사 | WARNING | AR≈GL1100 (±5%) | AR=5,487,267, GL=17,307,303,414, diff=315308.4% |
| T3-24 | FA 대사 | WARNING | NBV≈GL1500-GL1510 (±5%) | NBV=2,752,060, GL=59,321,735,597, diff=2155439.5% |
| T3-25 | Inventory 대사 | WARNING | INV≈GL1200 (±5%) | INV=182,094,422, GL=7,961,788,463, diff=4272.3% |
| T3-26 | reconciliation 대조 | WARNING | 전건 Reconciled | unreconciled=5/5 |
| T3-27 | IC 쌍 존재 | FAIL | orphan=0 | orphan=196/196 |
| T3-28 | IC 금액 일치 | PASS | seller금액==pairs.amount (±1) | 불일치=0/98 |
| T3-29 | IC GL 사용 | WARNING | seller 1150/4500>=80%, buyer 2050>=80% | seller=50.0%, buyer=50.0% |
| T3-30 | IC type 분포 | PASS | >=5개 유형 | 7개 유형 |

## Tier 4: 분포 + config 정합
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T4-01 | Benford MAD | PASS | MAD<0.006(PASS), <0.012(WARN) | MAD=0.004005 |
| T4-02 | 금액 LogNormal | WARNING | μ≈14.0, σ≈2.5 | μ=9.77, σ=3.84 |
| T4-03 | 월별 변동성(12월 스파이크) | WARNING | 12월/평월 비율 ≥ 3 | ratio=1.31 (12월=106,946, 평월평균=81,516) |
| T4-04 | 요일별 분포(월>금) | PASS | 월요일 비율 ≥ 금요일 | 월=0.350, 금=0.127 |
| T4-05 | 주말 비율 | PASS | 3% ~ 15% | 9.60% (96,327/1,003,624) |
| T4-06 | 시간대(오전 스파이크) | PASS | 오전(9~12시) ≥ 25% | 34.0% (340,853/1,003,624) |
| T4-07 | 법인별 비중(C001) | PASS | C001 ≥ 50% | C001=61.3% |
| T4-08 | process 비중 | PASS | 단일 process ≤ 60% | {'O2C': 26.557555419160963, 'A2R': 6.3021609686496... |
| T4-09 | persona 분포(automated) | PASS | automated ≥ 60% | automated=76.6% |
| T4-10 | IC 비율 | WARNING | 5% ~ 20% | 1.33% (13,370/1,003,624) |
| T4-11 | round_number 비율 | WARNING | 15% ~ 35% | 1.60% (16,043/1,003,624) |
| T4-12 | nice_number 비율 | WARNING | 10% ~ 25% | 2.82% (28,268/1,003,624) |
| T4-13 | GL HHI 집중도 | PASS | HHI < 0.1 (분산됨) | HHI=0.0028 (계정수=393) |
| T4-14 | 기말 스파이크(12/26~31) | WARNING | 기말 일평균 / 연평균 ≥ 3 | ratio=2.40 (기말일평균=9632, 연일평균=4014) |
| T4-15 | 공휴일 비율 | PASS | 공휴일 전표 ≤ 10% | 5.10% (51,143/1,003,624) |
| T4-16 | 결측률 MCAR | WARNING | 비보호 필드 null ≤ 5% | 위반 11건 |
| T4-17 | SoD 위반률 | WARNING | ≤ 2.0% (config×2) | 10.223% (102,596/1,003,624) |
| T4-18 | 시간 다양성 | PASS | DISTINCT(hh:mm) ≥ 50 | distinct_minutes=1403 |
| T4-19 | line_item 분포 | PASS | 정보 제공용 | 총96,871건, 2행=61.1% |
| T4-20 | source 분포 | PASS | automated ≥ 50% | automated=68.9% |
| T4-21 | SA 집중도(12월) | WARNING | 12월 SA비율 / 평월 ≥ 1.5 | ratio=0.78 (12월=19.5%, 평월=25.1%) |

## Tier 5: 라벨 + Silent Failure + 메타데이터
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T5-01 | 53개 anomaly_type 전수대조 | PASS | 핵심 15개 타입 라벨-데이터 일치 | 52개 타입, OK=10, MISMATCH=0 |
| T5-02 | OK 타입 수 >= 12 | WARNING | OK >= 12 | OK=10 |
| T5-03 | ALL_MISMATCH 개수 | PASS | 0 | 0개: [] |
| T5-04 | PARTIAL 타입 수 | PASS | 정보 제공 | 4개 |
| T5-05 | anomaly 주입률 | PASS | ~5% | 7.44% (7929/106519) |
| T5-06 | fraud_type 분포 | PASS | 8개 타입 | 16개 타입, total=2014 |
| T5-07 | sod_conflict_type 분포 | PASS | 7개 타입 | 7개, total=12423 |
| T5-08 | fraud+anomaly 동시 문서 | PASS | 정보 제공 | 280건 |
| T5-09 | structured_strategy_type 비율 | PASS | 정보 제공 | 0.0% (0/7899) |
| T5-10 | fiscal_period NULL (C05 위험) | PASS | 0 | 0건 |
| T5-11 | 대형 전표 line>100 (C09 제외 위험) | WARNING | 0 | 763건 |
| T5-12 | reference 공백 (B04 오탐 위험) | PASS | 0 | 0건 |
| T5-13 | posting_date 시간=00:00 비율 (C03 위험) | PASS | <99% | 0.0% (14/1105110) |
| T5-14 | manual_source_codes 설정 | PASS | 비어있지 않음 | ['Manual', 'Adjustment'] |
| T5-15 | debit_amount NULL 문서 (집계 NaN 위험) | PASS | 0 | 0건 |
| T5-16 | debit=0 AND credit=0 (first_digit NaN) | WARNING | 0 | 50488건 |
| T5-17 | is_round_number 재계산 (%1M=0) | PASS | 정보 제공 | 1.60% (16838/1054613) |
| T5-18 | lettrage 사용 | WARNING | >0 | 0건 (미구현) |
| T5-19 | run_manifest 행수 정합 | SKIP | records 키 필요 | keys: ['manifest_version', 'run_id', 'started_at',... |
| T5-20 | generation_statistics 정합 | PASS | injected=7899 | labels=7899 |
| T5-21 | local_amount 정합 | WARNING | 불일치 0건 | 불일치 12568건 / 1,105,110행 |
| T5-22 | aux_account label 정합 | PASS | 0건 | 0건 |

## 실패/경고 항목 상세
### T1-04 금액 음수 [FAIL]
- 기대: 음수 금액=0 (ReversedAmount 등 제외)
- 실측: neg_count=1

### T1-05 전표 대차일치 [FAIL]
- 기대: 대차불일치 전표=0 (금액변형 anomaly 제외)
- 실측: unbalanced_docs=14

### T1-07 기간 범위 [FAIL]
- 기대: fiscal_year=2022, period=1~12, posting_date≈2022
- 실측: bad_fy=286, bad_fp=0, date_out_of_range=3,705
- 상세:
```json
{
  "bad_fiscal_year": 286,
  "bad_fiscal_period": 0,
  "date_out_of_range": 3705
}
```

### T1-11 문서 내 일관성 [FAIL]
- 기대: 문서 내 company_code/posting_date 불일치=0
- 실측: inconsistent_docs=1

### T2-03 debit=0 AND credit=0 [WARNING]
- 기대: 비율 ≤ 1%
- 실측: zero_both=50,488 (4.57%)

### T2-14 trading_partner NULL 비율 [WARNING]
- 기대: NULL ≤ 95% (IC 라벨 제외)
- 실측: null=1,092,360 (98.8%)

### T2-17 line_number 순차 [FAIL]
- 기대: 갭 있는 문서=0
- 실측: gap_docs=196

### T2-18 junior 1억 초과 [WARNING]
- 기대: junior 1억 초과=0 (전결규정은 승인 한도, 작성 한도 아님. 승인 한도 검증은 B02/B03에서 수행)
- 실측: violations=1,132

### T2-20 automated 제3자승인 [WARNING]
- 기대: automated+제3자승인=0 (ManualOverride 등 제외)
- 실측: anomalies=688,449

### T2-21 GL prefix↔process [WARNING]
- 기대: P2P+GL불일치 ≤ 20%
- 실측: P2P total=266,976, bad_prefix=181,432 (68.0%)

### T2-23 Self-offsetting [WARNING]
- 기대: self-offset 쌍=0 (GL 2900/1150/2050+ReversedAmount 제외)
- 실측: self_offset_pairs=71

### T2-25 tax_code 100% NULL [WARNING]
- 기대: 설계상 tax_code 미사용 (WARNING=정상)
- 실측: non_null=0

### T2-28 sod↔conflict_type 정합 [FAIL]
- 기대: sod=true+type없음=0
- 실측: orphan_sod=6

### T3-03 employee FK [FAIL]
- 기대: orphan=0
- 실측: orphan=152

### T3-16 P2P 금액 매칭 [WARNING]
- 기대: PO≈VI (±5%)
- 실측: 불일치=1건

### T3-19 GR/IR 청산 [WARNING]
- 기대: WE 전표에 GL 2900 라인
- 실측: 미포함=1/61

### T3-21 cross_process_links 순서 [WARNING]
- 기대: source_date <= target_date
- 실측: 역전=15/15

### T3-22 AP 대사 [WARNING]
- 기대: AP≈GL2000 (±5%)
- 실측: AP=25,237,107, GL=350,609,737,992, diff=1389162.8%

### T3-23 AR 대사 [WARNING]
- 기대: AR≈GL1100 (±5%)
- 실측: AR=5,487,267, GL=17,307,303,414, diff=315308.4%

### T3-24 FA 대사 [WARNING]
- 기대: NBV≈GL1500-GL1510 (±5%)
- 실측: NBV=2,752,060, GL=59,321,735,597, diff=2155439.5%

### T3-25 Inventory 대사 [WARNING]
- 기대: INV≈GL1200 (±5%)
- 실측: INV=182,094,422, GL=7,961,788,463, diff=4272.3%

### T3-26 reconciliation 대조 [WARNING]
- 기대: 전건 Reconciled
- 실측: unreconciled=5/5
- 상세:
```json
{
  "unreconciled": [
    {
      "type": "AR",
      "diff": 8387946503.383763
    },
    {
      "type": "AP",
      "diff": 10712803758.341627
    },
    {
      "type": "FA",
      "diff": 17592532957.18606
    },
    {
      "type": "FA",
      "diff": 28650172018.343704
    },
    {
      "type": "Inventory",
      "diff": 3032668840.822413
    }
  ]
}
```

### T3-27 IC 쌍 존재 [FAIL]
- 기대: orphan=0
- 실측: orphan=196/196

### T3-29 IC GL 사용 [WARNING]
- 기대: seller 1150/4500>=80%, buyer 2050>=80%
- 실측: seller=50.0%, buyer=50.0%

### T4-02 금액 LogNormal [WARNING]
- 기대: μ≈14.0, σ≈2.5
- 실측: μ=9.77, σ=3.84
- 상세:
```json
{
  "issues": [
    "|μ-14.0|=4.23>1",
    "|σ-2.5|=1.34>0.5"
  ]
}
```

### T4-03 월별 변동성(12월 스파이크) [WARNING]
- 기대: 12월/평월 비율 ≥ 3
- 실측: ratio=1.31 (12월=106,946, 평월평균=81,516)

### T4-10 IC 비율 [WARNING]
- 기대: 5% ~ 20%
- 실측: 1.33% (13,370/1,003,624)

### T4-11 round_number 비율 [WARNING]
- 기대: 15% ~ 35%
- 실측: 1.60% (16,043/1,003,624)

### T4-12 nice_number 비율 [WARNING]
- 기대: 10% ~ 25%
- 실측: 2.82% (28,268/1,003,624)

### T4-14 기말 스파이크(12/26~31) [WARNING]
- 기대: 기말 일평균 / 연평균 ≥ 3
- 실측: ratio=2.40 (기말일평균=9632, 연일평균=4014)

### T4-16 결측률 MCAR [WARNING]
- 기대: 비보호 필드 null ≤ 5%
- 실측: 위반 11건
- 상세:
```json
{
  "high_null_pct": {
    "fraud_type": 100.0,
    "anomaly_type": 100.0,
    "sod_conflict_type": 89.78,
    "cost_center": 81.22,
    "tax_code": 100.0,
    "tax_amount": 100.0,
    "trading_partner": 99.92,
    "auxiliary_account_number": 41.44,
    "auxiliary_account_label": 41.44,
    "lettrage": 100.0,
    "lettrage_date": 100.0
  }
}
```

### T4-17 SoD 위반률 [WARNING]
- 기대: ≤ 2.0% (config×2)
- 실측: 10.223% (102,596/1,003,624)

### T4-21 SA 집중도(12월) [WARNING]
- 기대: 12월 SA비율 / 평월 ≥ 1.5
- 실측: ratio=0.78 (12월=19.5%, 평월=25.1%)

### T5-02 OK 타입 수 >= 12 [WARNING]
- 기대: OK >= 12
- 실측: OK=10

### T5-11 대형 전표 line>100 (C09 제외 위험) [WARNING]
- 기대: 0
- 실측: 763건

### T5-16 debit=0 AND credit=0 (first_digit NaN) [WARNING]
- 기대: 0
- 실측: 50488건

### T5-18 lettrage 사용 [WARNING]
- 기대: >0
- 실측: 0건 (미구현)

### T5-21 local_amount 정합 [WARNING]
- 기대: 불일치 0건
- 실측: 불일치 12568건 / 1,105,110행
