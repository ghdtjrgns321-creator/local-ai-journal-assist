# DataSynth 전수 품질검사 리포트
> 실행일: 2026-04-04 23:24 | 소요: 27.1s | 판정: **WARNING**

## 요약
| Tier | 이름 | Pass | Fail | Warning | Skip | 판정 |
|------|------|------|------|---------|------|------|
| T1 | 구조적 무결성 | 16 | 0 | 0 | 0 | PASS |
| T2 | 값 도메인 + 비즈니스 논리 | 36 | 0 | 2 | 0 | WARNING |
| T3 | 교차검증 | 27 | 0 | 9 | 0 | WARNING |
| T4 | 분포 + config 정합 | 24 | 0 | 1 | 0 | WARNING |
| T5 | 라벨 + Silent Failure + 메타데이터 | 26 | 0 | 6 | 1 | WARNING |
| T6 | 메타데이터 교차검증 | 5 | 0 | 0 | 0 | PASS |

## Tier 1: 구조적 무결성
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T1-01 | 행수/컬럼수 | PASS | rows>0; cols∈{39,46} | rows=3,255,597; cols=46 |
| T1-02 | 필수컬럼 존재+dtype | PASS | 필수 10컬럼 존재 + 올바른 dtype | OK |
| T1-03 | 보호필드 NOT NULL | PASS | document_id/company_code/posting_date NULL=0 | null_doc=0, null_cc=0, null_pd=0 |
| T1-04 | 금액 음수 | PASS | 음수 금액=0 (ReversedAmount 등 제외) | neg_count=0 |
| T1-05 | 전표 대차일치 | PASS | 대차불일치 전표=0 (금액변형 anomaly 제외) | unbalanced_docs=0 |
| T1-06 | company_code 도메인 | PASS | company_code IN (C001,C002,C003) | out_of_domain=0 |
| T1-07 | 기간 범위 | PASS | fiscal_year∈[2022, 2023, 2024], period=1~12, posti... | bad_fy=0, bad_fp=0, date_out_of_range=0 |
| T1-08 | 라벨 orphan | PASS | orphan labels=0 | orphan_count=0 |
| T1-09 | 단일행 전표 | PASS | 단일행 전표=0 (UnbalancedEntry+MissingField 제외) | single_line_docs=0 |
| T1-10 | KRW 소수점 | PASS | 소수점 금액=0 (KRW) | fractional_count=0 |
| T1-11 | 문서 내 일관성 | PASS | 문서 내 company_code/posting_date 불일치=0 | inconsistent_docs=0 |
| T1-12 | gl_account 형식 | PASS | gl_account 형식 불일치=0 (InvalidAccount+DormantAccount... | bad_format=0 |
| T1-13 | document_type MCAR 비율 | PASS | MCAR 빈값 비율 0.5~4% (전역 2% 적용) | null_or_empty=62,696 (1.93%) |
| T1-14 | gl_account MCAR 비율 | PASS | MCAR 빈값 비율 0.5~4% (전역 2% 적용) | null_or_empty=64,914 (1.99%) |
| T1-15 | change_log 구조 | PASS | 필수 6컬럼 존재 | OK (6컬럼) |
| T1-16 | change_log NOT NULL | PASS | 보호필드 NULL=0 | null_rows=0 |

## Tier 2: 값 도메인 + 비즈니스 논리
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T2-01 | 39컬럼 프로파일링 | PASS | 정보 제공용 | 46컬럼 프로파일 완료 |
| T2-02 | debit/credit 상호배타 | PASS | 동시 양수=0 (CircularIntercompany 등 제외) | both_positive=0 |
| T2-03 | debit=0 AND credit=0 | PASS | 비율 ≤ 1% | zero_both=143 (0.00%) |
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
| T2-14 | trading_partner NULL 비율 | PASS | NULL ≤ 60% (IC 라벨 제외 / Stage 3-3 기준) | null=1,585,514 (48.7%) |
| T2-15 | is_fraud↔fraud_type 정합 | PASS | 불일치=0 | fraud_no_type=0, type_no_fraud=0 |
| T2-16 | approved_by↔approval_date 쌍 | PASS | approved_by 있는데 approval_date 없음=0 | orphan_approval=0 |
| T2-17 | line_number 순차 | PASS | 갭 있는 문서=0 | gap_docs=0 |
| T2-18 | junior 1억 초과 | PASS | junior 1억 초과=0 (전결규정은 승인 한도, 작성 한도 아님. 승인 한도 검증은 B... | violations=0 |
| T2-19 | approval_date>=posting_date | PASS | 사전승인 위반=0 (LateApproval+SkippedApproval+LatePostin... | pre_post_violations=0 |
| T2-20 | automated 제3자승인 | PASS | automated+제3자승인=0 (ManualOverride 등 제외) | anomalies=0 |
| T2-21 | GL prefix↔process | PASS | P2P+GL불일치 ≤ 5% | P2P total=609,936, bad_prefix=4,838 (0.8%) |
| T2-22 | doctype↔process 매핑 | PASS | 매핑 위반=0 | violations=0 |
| T2-23 | Self-offsetting | WARNING | self-offset 쌍=0 (GL 2900/1150/2050+ReversedAmount ... | self_offset_pairs=135,593 |
| T2-24 | 수익계정 차변 비율 | PASS | 4xxx debit ≤ 10% | 4xxx total=350,581, debit=8,732 (2.5%) |
| T2-25 | tax_code 100% NULL | WARNING | 설계상 tax_code 미사용 (WARNING=정상) | non_null=0 |
| T2-26 | cost_center 형식 | PASS | cost_center LIKE 'CC%' | bad_format=0 |
| T2-27 | profit_center 형식 | PASS | profit_center LIKE 'PC-%' | bad_format=0 |
| T2-28 | sod↔conflict_type 정합 | PASS | sod=true+type없음=0 | orphan_sod=0 |
| T2-29 | has_attachment 도메인 | PASS | NULL=0, true/false만 | null=0/3,255,597 |
| T2-30 | supporting_doc_type 도메인 | PASS | 허용=8개 | OK (8개) |
| T2-31 | delivery_date 범위 | PASS | WE만 + posting_date-10d~posting_date | non_WE=0, out_of_range=0 |
| T2-32 | invoice_amount 양수 | PASS | 음수=0 | 음수=0 |
| T2-33 | supply↔invoice 정합 | PASS | invoice≈supply×1.1 (±10원) | 불일치=0/3,255,597 |
| T2-34 | ip_address 형식 | PASS | IPv4 형식 | invalid=0 |
| T2-35 | document_number 순차성 | PASS | company+year+type별 cross-doc 중복=0 (GAP 제외) | 중복그룹=0 |
| T2-36 | change_log 필드 형식 | PASS | 금액→숫자, 날짜→날짜 | bad_amount=0, bad_date=0 |
| T2-37 | has_attachment completeness | PASS | ≥ 80% | 81.5% (2,654,198/3,255,597) |
| T2-38 | ip_address completeness | PASS | ≥ 95% | 100.0% (3,255,597/3,255,597) |

## Tier 3: 교차검증
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T3-01 | vendor FK | PASS | orphan=0 | orphan=0 |
| T3-02 | customer FK | PASS | orphan=0 | orphan=0 |
| T3-03 | employee FK | PASS | orphan=0 | orphan=0 |
| T3-04 | persona 일치 | PASS | mismatch=0 | mismatch=0 |
| T3-05 | employee company 일치 | PASS | mismatch=0 (IC 전표 + authorized 회사 제외) | mismatch=0 |
| T3-06 | vendor 커버리지 | PASS | >=50% | 60/60 (100.0%) |
| T3-07 | customer 커버리지 | PASS | >=50% | 90/90 (100.0%) |
| T3-08 | employee 커버리지 | PASS | >=50% | 259/268 (96.6%) |
| T3-09 | junior TRE 금지 | PASS | 0건 (SoD 제외) | 0건 |
| T3-10 | junior 단일 프로세스 | PASS | multi-process junior=0 (SoD 제외) | 0명 |
| T3-11 | controller R2R 집중 | PASS | R2R >= 80% | 95.7% (99613/104045) |
| T3-12 | approval_limit | PASS | 초과=0 (금액변형 anomaly 제외) | 0건 |
| T3-13 | can_approve_je | PASS | 무권한 승인=0 (SelfApproval/SkippedApproval 제외) | 0건 |
| T3-14 | reference FK | PASS | orphan=0 | orphan=0/370 |
| T3-15 | P2P 순서 | PASS | PO<=GR<=VI (DuplicatePayment 제외) | 역전=0건 |
| T3-16 | P2P 금액 매칭 | WARNING | PO≈VI (±5%) | 불일치=1건 |
| T3-17 | O2C 순서 | PASS | SO<=DLV<=CI | 역전=0건 |
| T3-18 | 지급기한 분포 | PASS | 합리적 지급기한(0~120일) | avg=33.9, min=0, max=60 |
| T3-19 | GR/IR 청산 | WARNING | WE 전표에 GL 2900 라인 | 미포함=2/58 |
| T3-20 | delivery COGS | PASS | WL 전표에 GL 5000 라인 | 미포함=0/23 |
| T3-21 | cross_process_links 순서 | PASS | source_date <= target_date | 역전=0/15 |
| T3-22 | AP 대사 | WARNING | AP≈GL2000 (±5%) | AP=25,237,107, GL=916,687,028,016, diff=3632198.3% |
| T3-23 | AR 대사 | WARNING | AR≈GL1100 (±5%) | AR=5,487,267, GL=65,147,927,650, diff=1187156.3% |
| T3-24 | FA 대사 | WARNING | NBV≈GL1500-GL1510 (±5%) | NBV=2,752,060, GL=1,206,687,739,668, diff=43846612... |
| T3-25 | Inventory 대사 | WARNING | INV≈GL1200 (±5%) | INV=182,094,422, GL=1,767,818,714, diff=870.8% |
| T3-26 | reconciliation 대조 | WARNING | 전건 Reconciled | unreconciled=5/5 |
| T3-27 | IC 쌍 존재 | PASS | orphan=0 | orphan=0/656 |
| T3-28 | IC 금액 일치 | WARNING | seller금액==pairs.amount (±1) | 불일치=17/328 |
| T3-29 | IC GL 사용 | WARNING | seller 1150/4500>=80%, buyer 2050>=80% | seller=48.8%, buyer=47.4% |
| T3-30 | IC type 분포 | PASS | >=5개 유형 | 7개 유형 |
| T3-31 | ip↔company 대역 매핑 | PASS | 대역 불일치 ≤ 1% | 불일치=0/3,214,114 (0.0%) |
| T3-32 | change_log FK 정합 | PASS | orphan=0 | orphan=0 |
| T3-33 | change_log field 도메인 | PASS | JE 컬럼명만 허용 | OK (4개 필드) |
| T3-34 | change_log 비율 | PASS | 변경 전표 1~10% | 5.06% (16,157/319,102) |
| T3-35 | delivery_date cutoff 정합 | PASS | 연도 경계 교차 < 1% | 교차=0/122 (0.00%) |
| T3-36 | change_log→JE 현재값 정합 | PASS | gl_account old_value ∈ JE 현재 GL | 불일치=0/5,906 |

## Tier 4: 분포 + config 정합
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T4-01 | Benford MAD | PASS | MAD<0.006(PASS), <0.012(WARN) | MAD=0.006697 |
| T4-02 | 금액 LogNormal | PASS | μ≈14.0, σ≈2.5 | μ=10.00, σ=3.49 |
| T4-03 | 월별 변동성(12월 스파이크) | PASS | 각 연도 12월/평월 비율 ≥ 3 | min_ratio=4.24, years=3 |
| T4-04 | 요일별 분포(월>금) | PASS | 월요일 비율 ≥ 금요일 | 월=0.344, 금=0.118 |
| T4-05 | 주말 비율 | PASS | 3% ~ 15% | 9.29% (255,655/2,752,788) |
| T4-06 | 시간대(오전 스파이크) | PASS | 오전(9~12시) ≥ 25% | 33.0% (909,546/2,752,788) |
| T4-07 | 법인별 비중(C001) | PASS | C001 ≥ 50% | C001=62.7% |
| T4-08 | process 비중 | PASS | 단일 process ≤ 60% | {'A2R': 6.748176757527277, 'R2R': 32.1213620518543... |
| T4-09 | persona 분포(automated) | PASS | automated ≥ 60% | automated=77.3% |
| T4-10 | IC 비율 | PASS | 5% ~ 20% | 1.11% (30,473/2,752,788) |
| T4-11 | round_number 비율 | PASS | 15% ~ 35% | 20.98% (56,466/269,123) |
| T4-12 | nice_number 비율 | PASS | 10% ~ 25% | 32.14% (86,500/269,123) |
| T4-13 | GL HHI 집중도 | PASS | HHI < 0.1 (분산됨) | HHI=0.0038 (계정수=403) |
| T4-14 | 기말 스파이크(12/26~31) | PASS | 각 연도 기말 일평균 / 연평균 ≥ 3 | min_ratio=3.80, years=3 |
| T4-15 | 공휴일 비율 | PASS | 공휴일 전표 ≤ 10% | 7.30% (200,833/2,752,788) |
| T4-16 | 결측률 MCAR | WARNING | 비보호 필드 null ≤ 5% | 위반 5건 |
| T4-17 | SoD 위반률 | PASS | ≤ 2.0% (config×2) | 1.415% (38,947/2,752,788) |
| T4-18 | 시간 다양성 | PASS | DISTINCT(hh:mm) ≥ 50 | distinct_minutes=1439 |
| T4-19 | line_item 분포 | PASS | 정보 제공용 | 총269,123건, 2행=61.2% |
| T4-20 | source 분포 | PASS | automated ≥ 50% | automated=70.4% |
| T4-21 | SA 집중도(12월) | PASS | 각 연도 12월 SA비율 / 평월 ≥ 1.5 | min_ratio=1.67, years=3 |
| T4-22 | has_attachment process별 비율 | PASS | P2P≥90%, O2C≥85%, R2R≥20% | OK |
| T4-23 | 연도별 전표 분포 | PASS | 각 연도 15~50% | OK (3개년) |
| T4-24 | VPN IP 비율 | PASS | 172.16.x.x ≤ 10% | 1.3% (34,619/2,752,788) |
| T4-25 | 계정그룹 YoY 변동률 | PASS | 각 그룹 YoY < 50% | OK |

## Tier 5: 라벨 + Silent Failure + 메타데이터
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T5-01 | 52개 anomaly_type 전수대조 | PASS | 52개 타입 라벨-데이터 일치 | 53개 타입, OK=48, MISMATCH=0 |
| T5-02 | OK 타입 수 >= 12 | PASS | OK >= 12 | OK=48 |
| T5-03 | ALL_MISMATCH 개수 | PASS | 0 | 0개: [] |
| T5-04 | PARTIAL 타입 수 | PASS | 정보 제공 | 5개 |
| T5-05 | anomaly 주입률 | WARNING | ~5% | 14.64% (46706/319102) |
| T5-06 | fraud_type 분포 | PASS | 8개 타입 | 16개 타입, total=4638 |
| T5-07 | sod_conflict_type 분포 | PASS | 7개 타입 | 8개, total=6300 |
| T5-08 | fraud+anomaly 동시 문서 | PASS | 정보 제공 | 1365건 |
| T5-09 | structured_strategy_type 비율 | PASS | 정보 제공 | 0.0% (0/49304) |
| T5-10 | fiscal_period NULL (C05 위험) | PASS | 0 | 0건 |
| T5-11 | 대형 전표 line>100 (C09 제외 위험) | WARNING | 0 | 2189건 |
| T5-12 | reference 공백 (B04 오탐 위험) | PASS | 0 | 0건 |
| T5-13 | posting_date 시간=00:00 비율 (C03 위험) | PASS | <99% | 0.0% (48/3255597) |
| T5-14 | manual_source_codes 설정 | PASS | 비어있지 않음 | ['Manual', 'Adjustment'] |
| T5-15 | debit_amount NULL 문서 (집계 NaN 위험) | PASS | 0 | 0건 |
| T5-16 | debit=0 AND credit=0 (first_digit NaN) | WARNING | 0 | 143건 |
| T5-17 | is_round_number 재계산 (%1M=0) | PASS | 정보 제공 | 0.05% (1556/3255454) |
| T5-18 | lettrage 사용 | WARNING | >0 | 0건 (미구현) |
| T5-19 | run_manifest 행수 정합 | SKIP | records 키 필요 | keys: ['manifest_version', 'run_id', 'started_at',... |
| T5-20 | generation_statistics 정합 | WARNING | injected=46605 | labels=49304 |
| T5-21 | local_amount 정합 | WARNING | 불일치 0건 | 불일치 99651건 / 3,255,597행 |
| T5-22 | aux_account label 정합 | PASS | 0건 | 0건 |
| T5-23a | IP 대역 라벨 역검증 | PASS | 라벨 전표 = 실제 대역 불일치 | labeled=0, false_positive=0 |
| T5-23b | 해외 IP 라벨 역검증 | PASS | 정보 제공 | public_ip_labels=0 |
| T5-23c | VPN 오탐 방지 | PASS | VPN IP + anomaly 라벨 = 0 | vpn_labeled=0 |
| T5-24 | docnum GAP 라벨 정합 | PASS | 정보 제공 | DocumentNumberGap 라벨=0 |
| T5-25 | change_log 라벨 정합 | PASS | 정보 제공 | 금액/GL 수정 문서=10087, 라벨 매칭=0 |
| T5-26 | TrendBreak 라벨 역검증 | PASS | 정보 제공 | TrendBreak 라벨=356 |
| T5-27 | 역방향: 차대변 불균형 라벨 누락 | PASS | ≥100원 불균형 unlabeled=0 | 불균형=281, unlabeled=0 |
| T5-28 | 역방향: 심야 전기 라벨 누락 | PASS | 정보 제공 | 심야=5865, unlabeled=4659 |
| T5-29 | 역방향: 휴면계정 라벨 누락 | PASS | unlabeled=0 | 휴면계정=5098, unlabeled=0 |
| T5-30 | 역방향: 무효 GL 라벨 누락 | PASS | config 무효코드 unlabeled=0 | 무효GL=44, unlabeled=0 |
| T5-31 | 역방향: 자기승인 라벨 누락 | PASS | 수작업 자기승인 unlabeled=0 | 수작업 자기승인=2442, unlabeled=0 |

## Tier 6: 메타데이터 교차검증
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T6-01 | gen_stats 전표수 | PASS | stats.total_entries=318,949 | csv_distinct_docs=319,102 (diff=153) |
| T6-02 | gen_stats 행수 | PASS | stats.total_line_items=3,254,764 | csv_rows=3,255,597 (diff=833) |
| T6-03 | balance_validation | PASS | coverage≥90% | processed=318,082/319,102 (99.7%), errors=418 |
| T6-04 | run_manifest | PASS | 필수 5키 + seed | OK (seed=2024) |
| T6-05 | change_log 행수 | PASS | 3,191~63,820건 | 24,205건 |

## 실패/경고 항목 상세
### T2-23 Self-offsetting [WARNING]
- 기대: self-offset 쌍=0 (GL 2900/1150/2050+ReversedAmount 제외)
- 실측: self_offset_pairs=135,593

### T2-25 tax_code 100% NULL [WARNING]
- 기대: 설계상 tax_code 미사용 (WARNING=정상)
- 실측: non_null=0

### T3-16 P2P 금액 매칭 [WARNING]
- 기대: PO≈VI (±5%)
- 실측: 불일치=1건

### T3-19 GR/IR 청산 [WARNING]
- 기대: WE 전표에 GL 2900 라인
- 실측: 미포함=2/58

### T3-22 AP 대사 [WARNING]
- 기대: AP≈GL2000 (±5%)
- 실측: AP=25,237,107, GL=916,687,028,016, diff=3632198.3%

### T3-23 AR 대사 [WARNING]
- 기대: AR≈GL1100 (±5%)
- 실측: AR=5,487,267, GL=65,147,927,650, diff=1187156.3%

### T3-24 FA 대사 [WARNING]
- 기대: NBV≈GL1500-GL1510 (±5%)
- 실측: NBV=2,752,060, GL=1,206,687,739,668, diff=43846612.0%

### T3-25 Inventory 대사 [WARNING]
- 기대: INV≈GL1200 (±5%)
- 실측: INV=182,094,422, GL=1,767,818,714, diff=870.8%

### T3-26 reconciliation 대조 [WARNING]
- 기대: 전건 Reconciled
- 실측: unreconciled=5/5
- 상세:
```json
{
  "unreconciled": [
    {
      "type": "AR",
      "diff": -29022391348.29307
    },
    {
      "type": "AP",
      "diff": -1502941805.6176462
    },
    {
      "type": "FA",
      "diff": 387805664696.88226
    },
    {
      "type": "FA",
      "diff": 510175619449.54376
    },
    {
      "type": "Inventory",
      "diff": 9293526169.798716
    }
  ]
}
```

### T3-28 IC 금액 일치 [WARNING]
- 기대: seller금액==pairs.amount (±1)
- 실측: 불일치=17/328

### T3-29 IC GL 사용 [WARNING]
- 기대: seller 1150/4500>=80%, buyer 2050>=80%
- 실측: seller=48.8%, buyer=47.4%

### T4-16 결측률 MCAR [WARNING]
- 기대: 비보호 필드 null ≤ 5%
- 실측: 위반 5건
- 상세:
```json
{
  "high_null_pct": {
    "supporting_doc_type": 18.03,
    "cost_center": 82.7,
    "trading_partner": 48.68,
    "auxiliary_account_number": 48.71,
    "auxiliary_account_label": 48.71
  }
}
```

### T5-05 anomaly 주입률 [WARNING]
- 기대: ~5%
- 실측: 14.64% (46706/319102)

### T5-11 대형 전표 line>100 (C09 제외 위험) [WARNING]
- 기대: 0
- 실측: 2189건

### T5-16 debit=0 AND credit=0 (first_digit NaN) [WARNING]
- 기대: 0
- 실측: 143건

### T5-18 lettrage 사용 [WARNING]
- 기대: >0
- 실측: 0건 (미구현)

### T5-20 generation_statistics 정합 [WARNING]
- 기대: injected=46605
- 실측: labels=49304

### T5-21 local_amount 정합 [WARNING]
- 기대: 불일치 0건
- 실측: 불일치 99651건 / 3,255,597행
