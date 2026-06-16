# Synthetic NORMAL 전표 현실성 검사 항목 카탈로그

## 목적

이 문서는 synthetic NORMAL 전표 데이터가 실제 회사 GL과 닮았는지 전수로 검증하기 위한 검사 항목 카탈로그다.
이 문서는 이후 P3-1 정상 데이터 검증기의 입력 기준이며, 데이터 생성기 또는 검증기 구현 지시서가 아니다.
NORMAL 생성 또는 재생성 중 새 버그가 발견되거나 재발 가능성이 있는 결함이 확인되면, 해당 검사는 본
카탈로그에 regression gate로 추가하고 이후 NORMAL 재생성의 자동 실행 대상에 포함한다.

정상 데이터 검사는 truth 라벨 또는 탐지기 성능에 맞추는 fitting 작업이 아니다.
검사 항목은 회계, ERP, 감사, 세무, 업무통제 도메인 현실을 기준으로 한다.
각 항목은 전수 모집단에서 결정적으로 계산 가능한 측정 방법을 우선한다.

v2 실패 항목 중 다수는 거래처, 계정, 적요, 금액, 승인, user/source를 독립적으로 샘플링한 증상이다.
해당 항목의 수정 방향은 개별 증상 패치가 아니라 거래 아키타입 단위 joint draw로 필드를 함께 생성하는 것이다.

## 발굴 소스

- `docs/spec/DETECTION_RULES.md`: PHASE1 32개 canonical 룰과 보조 finding의 정상 기대 역산.
- `docs/spec/DETECTION_REFERENCE.md`: 감사기준서 도출, 한국 실무 보조 지식, 전결규정, 결산 일정, 근무시간, 적격증빙, K-IFRS/SAP 실무.
- `src/detection/`: 실제 detector 구현. 특히 `integrity_layer.py`, `fraud_layer.py`, `fraud_rules_*`, `anomaly_rules_*`, `benford_detector.py`, `intercompany_rules.py`, `graph_rules.py`, `variance_rules.py`.
- `dev/active/datasynth-journal-realism-rebuild/`: 기존 semantic validator, account subtype taxonomy, counterparty master, text/document family, regeneration contract.
- 웹 리서치:
  - PCAOB Audit Focus: Journal Entries: <https://pcaobus.org/resources/staff-publications/audit-focus/audit-focus-journal-entries>
  - SAP Help Portal Journal Entries: <https://help.sap.com/docs/SAP_BUSINESS_BYDESIGN/2754875d2d2a403f95e58a41a9c7d6de/2bcba772722d10148cd1eb9d1f1441a0.html>
  - SAP Help Portal Journal Entry Reverse: <https://help.sap.com/docs/SAP_S4HANA_CLOUD/b978f98fc5884ff2aeb10c8fdeb8a43b/57b40036b71f4825adad70a0a5b91573.html>
  - PwC Korea Corporate Deductions: <https://taxsummaries.pwc.com/republic-of-korea/corporate/deductions>
  - Journal of Accountancy Benford JE analytics: <https://www.journalofaccountancy.com/issues/2022/sep/using-benfords-law-reveal-journal-entry-irregularities/>
  - ISACA Benford accounting data testing: <https://www.isaca.org/resources/isaca-journal/past-issues/2010/using-spreadsheets-and-benfords-law-to-test-accounting-data>

## 출처 표기

- `[기존]`: realism-rebuild 설계 문서 또는 기존 PHASE1 룰/코드에 이미 직접 정의된 검사 항목.
- `[기존+신규]`: 기존 항목을 정상 GL 현실성 검사로 확장한 항목.
- `[신규]`: 이번 발굴에서 추가한 항목. 근거는 rule 역산, standard, web, domain 중 하나 이상이다.

## A. 복식부기 정합

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                      위반 예시                                      측정 방법(전수 계산 가능하게)                                      출처(rule/standard/web/design)                         연결된 phase1 룰        전수 적용
------  ----------------  ----------------------------------------------------------------  ---------------------------------------------  --------------------------------------------------------------------  ------------------------------------------------------  --------------------  --------
A01     복식부기 정합     document_id별 차변 합계와 대변 합계가 허용 오차 안에서 일치한다.  정상 전표에서 차변합과 대변합 차이가 발생한다.  document_id별 sum(debit_amount)-sum(credit_amount)의 절대값과 비율 계산.  [기존] rule/code: L1-01, integrity_layer.py          L1-01                 예
A02     복식부기 정합     한 row는 차변 또는 대변 중 한쪽 금액만 양수로 가진다.             같은 row에 차변·대변이 모두 양수이거나 모두 0이다.     row별 debit_amount>0, credit_amount>0, 둘 다 0, 둘 다 양수 비율 계산.       [신규] rule 역산: L1-01, ERP GL 구조                  L1-01                 예
A03     복식부기 정합     금액은 계정 방향과 별도 정규화된 부호 체계를 사용한다.            정상 row에 음수 차변/대변이 무작위로 섞인다.          debit_amount, credit_amount의 음수 비율과 document_type별 허용 예외 비율 계산. [신규] rule 역산: L1-01/L2-05, SAP reversal          L1-01, L2-05          예
A04     복식부기 정합     통화는 document 또는 명시 환산 그룹 안에서 일관된다.              같은 전표 안 KRW와 USD가 섞이나 환산근거가 없다.      document_id별 distinct currency 수, exchange_rate 존재 여부, 원화 환산 합계 검증. [신규] rule/code: IC cross-currency 방어, domain     L1-01, IC02           부분
A05     복식부기 정합     정상 원장에는 material한 불균형 전표가 0건이어야 한다.             정상 baseline에 material/severe imbalance가 존재한다. L1-01 bucket별 row/doc count를 normal subset에서 0 또는 rounding-only로 집계. [기존] rule/code: L1-01 score bucket                 L1-01                 예
A06     복식부기 정합     document line 수는 업무유형별 자연 범위 안에 있다.                단순 매입 전표가 수백 라인으로 생성된다.             document_id별 row_count 분포를 document_type/business_process별 quantile로 계산. [신규] ERP GL 현실성, L4-06 역산                     L4-06                 예
A07     복식부기 정합     세금 라인은 공급가액/부가세 구조와 연결된다.                       매입세금계산서에 VAT 라인이 없거나 비율이 비현실적이다. tax_account 또는 tax_amount가 있는 document의 공급가액 대비 세액 비율 계산. [신규] Korean tax/domain, PwC Korea                  L1-02, L3-01          부분
```

## B. 분개 의미·계정조합 정합

```text
검사ID  카테고리              정상 기대(무엇이 정상인가)                                                위반 예시                                                     측정 방법(전수 계산 가능하게)                                         출처(rule/standard/web/design)                                  연결된 phase1 룰        전수 적용
------  --------------------  --------------------------------------------------------------------------  ------------------------------------------------------------  -----------------------------------------------------------------------  ---------------------------------------------------------------  --------------------  --------
B01     계정조합 정합         차변계정×대변계정 조합은 scenario의 허용 계정쌍 안에 있다.                  매입채무와 차입원가가 무의미하게 조합된다.                    document_id별 debit semantic subtype × credit semantic subtype pair 허용표 대조. [기존+신규] design: semantic validator, rule L4-04         L4-04                 예
B02     계정조합 정합         business_process와 계정분류가 일치한다.                                      O2C 전표가 원재료 매입 계정을 사용한다.                       row별 business_process × account_category/semantic_subtype 허용표 대조.       [기존] design/rule/code: L3-01, semantic validator       L3-01                 예
B03     계정조합 정합         document_type과 계정 조합이 일치한다.                                        매출 세금계산서 document_type에 급여비 계정이 붙는다.          row/doc별 document_type × semantic_subtype 허용표 대조.                      [기존] design: text-document-family, SAP JE type          L3-01, L4-04          예
B04     계정조합 정합         자산 취득·CAPEX 전표와 비용 전표는 account/text/process가 구분된다.          수선비 적요의 P2P 비용 전표가 유형자산 취득으로 기표된다.      asset account와 expense text/process 동시 출현률, 정상 키워드 suppress 비율 계산. [기존] rule/code: L2-04, account-subtype-taxonomy          L2-04                 예
B05     계정조합 정합         매출 계정은 O2C 또는 명시 IC 매출 시나리오에서만 사용된다.                  매출 계정이 vendor payment나 payroll process에 사용된다.       revenue account row의 business_process, counterparty_type, document_type 대조. [기존] design: SEM007/SEM008, rule L4-01/L3-11            L4-01, L3-11          예
B06     계정조합 정합         가수금·가지급금·미결 계정은 clearing lifecycle을 가진다.                   suspense 계정이 장기간 미정리 상태로 방치된다.                 suspense account별 open_item_id/clearing_reference/age bucket 집계.           [기존+신규] rule: L3-09, design backlog                 L3-09                 부분
B07     계정조합 정합         high-risk 계정 사용은 정상 데이터에서도 희소하고 맥락이 설명 가능하다.       임의 정상 전표 다수가 현금성·미정리·민감 계정에 접촉한다.     high-risk account row 비율을 process/source/period별 집계하고 상위 concentration 산출. [기존] rule/code: L3-10                              L3-10                 예
B08     계정조합 정합         COGS 하위 subtype은 원재료·노무·외주·운반·조정 의미가 분리된다.            COGS_MATERIAL에 급여 적요와 직원 거래처가 붙는다.              COGS semantic_subtype × counterparty_type × line_text_family 허용표 대조.      [기존] design: account-subtype-taxonomy                 L3-01, L4-04          예
B09     계정조합 정합         OPEX 하위 subtype은 급여·임차·수도광열·소모품·상각·세금 의미가 분리된다.   OPEX_DEPRECIATION에 일반 AP vendor invoice가 붙는다.           OPEX semantic_subtype × process × document_type × counterparty_type 대조.      [기존] design: account-subtype-taxonomy                 L3-01, L2-04          예
B10     계정조합 정합         은행·차입·이자 전표는 BANK counterparty와 treasury process를 가진다.        차입금 실행 전표가 사무용품 vendor를 상대방으로 가진다.       treasury GL row의 process/document_type/counterparty_type 대조.              [기존] design: counterparty-master-design               L3-01, L4-04          예
B11     계정조합 정합         감가상각 전표는 A2R/R2R 시나리오와 내부/무거래 상대방을 사용한다.          감가상각비가 매입세금계산서 document_type으로 생성된다.       depreciation account/text row의 process, source_document, counterparty_type 대조. [기존] design: SEM006, text-document-family             L3-01, L2-04          예
B12     계정조합 정합         고객 채권·매출·수금 전표는 CUSTOMER counterparty와 O2C 흐름 안에 있다.      고객 청구 적요가 vendor payment process에 붙는다.             AR/revenue/cash receipt row의 counterparty_type, process, document_type 대조. [기존] design: SEM007/SEM008, counterparty master        L3-01, L3-11          예
B13     계정조합 정합         account×process×counterparty×document_type×text 5축 조합은 정상 빈도 분포를 가진다. 희소 5축 조합이 정상 데이터 대부분을 차지한다. 5축 tuple별 frequency, support, train/test split 안정성, low-support tuple share 계산. [신규] PHASE2 VAE 타깃, 고차 co-occurrence 현실성       L3-01, L4-04, PHASE2  예
B14     계정조합 정합         고차 조합의 신규성은 정상 업무 확장 또는 master 변화로 설명 가능해야 한다. 신규 counterparty×계정×문서유형 조합이 무작위로 대량 발생한다. 전기 대비 신규 5축 tuple 비율, 신규 tuple의 account/process/amount 분포와 master effective date 대조. [신규] PHASE2 VAE 타깃, D01/D02 정상 사업 이벤트       D01, D02, PHASE2      예
B15     계정조합 정합         같은 P2P라도 원재료 vendor, utility vendor, office supplier, service vendor는 서로 다른 계정·적요 domain을 가진다. VendorUtilities인데 원재료 구매/RAW_MATERIALS, VendorOfficeSupplies인데 전력요금, VendorRawMaterial인데 자문수수료가 나온다. counterparty_subtype × semantic_account_subtype × line_text_family × raw_keyword hard allowlist 대조. controlled multi-domain/vendor-general/misc exception label은 별도 허용 슬롯으로 관리한다. [기존+신규] counterparty master/text family 확장, v2 failure  L3-01, L4-04          예
B16     계정조합 정합         한 document 안의 라인들은 동일 구매·지급·정산 실체를 설명한다.              vendor invoice 안에 원재료, 사무용품, 자문수수료, 수도광열비가 무작위 혼합된다. document_id별 debit-side dominant line_text_family와 AP/GRIR/clearing line text family 일치 여부, distinct family count, batch/summary invoice exception label 확인. [신규] document coherence, v2 failure                 L2-03, L4-04          예
B17     계정조합 정합         정상 전표는 거래 아키타입별 account/text/counterparty/document/source/amount range joint contract를 가진다. P2P raw material purchase, utility bill, office supplies, service fee, capex invoice가 같은 필드 분포로 생성된다. archetype_id별 row/doc count, archetype_id 없는 normal document 비율, archetype별 allowed field tuple violation, archetype별 amount range coverage 계산. [신규] transaction archetype coverage, v2 root cause  L3-01, L4-04, PHASE2  예
```

## C. 분포·통계 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                            측정 방법(전수 계산 가능하게)                                             출처(rule/standard/web/design)                                연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  ---------------------------------------------------  ---------------------------------------------------------------------------  -------------------------------------------------------------  --------------------  --------
C01     분포·통계         Benford 적용 가능 모집단은 1자리 선행숫자 분포가 Benford 기대에 근접한다.  자연 매입·매출 금액의 선행숫자가 균등분포에 가깝다.  계정/프로세스별 eligible population 선별 후 MAD, chi-square, digit frequency 계산.  [기존+신규] rule L4-02, JofA/ISACA Benford       L4-02                 예
C02     분포·통계         Benford 부적합 모집단은 Benford 검사에서 제외 가능해야 한다.               급여, 정액 임차료, 한도성 금액을 Benford 위반으로 오해한다. account/process별 structured amount flag, population size, range span 계산.      [신규] web: Benford 적용 조건, rule 역산             L4-02                 예
C03     분포·통계         금액 분포는 계정·프로세스별 heavy-tail 또는 lognormal에 가까운 자연 변동을 가진다. 모든 금액이 좁은 균등분포로 생성된다.                 account/process별 log(amount) 분포, skew, kurtosis, tail quantile, zero share 계산. [신규] rule 역산: L4-03, domain                    L4-03                 예
C04     분포·통계         매출 금액 이상치는 희소하며 계정·기간별 정상 tail 안에 위치한다.          정상 매출의 z-score extreme row가 과다하다.          revenue population별 robust z-score, top percentile count, period tail ratio 계산. [기존] rule/code: L4-01                             L4-01                 예
C05     분포·통계         거래처·계정 빈도는 파레토형 집중을 보이되 단일 객체 과집중은 제한된다.      한 vendor 또는 한 계정이 비현실적으로 대부분을 차지한다. vendor/account/user별 count 및 amount share, HHI, top-1/top-10 share 계산.       [신규] ERP GL/domain, L4-05/L3-12 역산             L3-12, L4-05          예
C06     분포·통계         계정쌍 빈도는 자주 쓰는 자연쌍과 희소쌍이 함께 존재한다.                  정상 데이터의 대부분이 희소 계정쌍으로 구성된다.       debit-credit pair별 frequency, lower-percentile rare-pair ratio 계산.          [기존+신규] rule/code: L4-04, semantic design       L4-04                 예
C07     분포·통계         전기 대비 계정 활동량 변화는 정상 사업 이벤트와 안정 계정 guardrail을 가진다. 안정 계정 활동량이 매년 무작위로 급변한다.                 fiscal_year/company/account별 row_count, amount_sum 전기 대비 변화율 계산.    [기존] rule/doc: D01 variance contract             D01                   예
C08     분포·통계         월별 계정 분포는 업무 계절성과 결산 집중을 반영하되 무작위 요동하지 않는다. 월별 계정 비율이 매년 독립 난수처럼 바뀐다.               account/company별 월별 비율 벡터 거리, KL/JS distance, peak month stability 계산. [기존] rule/doc: D02 variance contract             D02                   예
C09     분포·통계         round amount는 특정 업무에서 자연 발생하되 전체 금액을 지배하지 않는다.     정상 전표 대부분이 1,000,000원 단위 정액이다.         amount modulo unit별 round-number ratio를 account/process/source별 계산.       [신규] rule 역산: L2-01/L4-03/GR01 context          L2-01, L4-03, GR01    예
C10     분포·통계         정액 거래는 존재하지만 특정 exact amount가 normal GL 전체 또는 특정 계정·프로세스를 과도하게 지배하지 않는다. amount=100 같은 동일 금액이 1만 행 이상 반복된다. account/process/source/scenario별 top exact amount share, small fixed amount cluster 비율, amount generator bucket/source trace 계산. [신규] exact amount cluster, v2 failure               L4-03, L4-06, PHASE2  예
```

## D. 시간 패턴 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                             위반 예시                                                측정 방법(전수 계산 가능하게)                                               출처(rule/standard/web/design)                               연결된 phase1 룰        전수 적용
------  ----------------  -----------------------------------------------------------------------  -------------------------------------------------------  -----------------------------------------------------------------------------  ------------------------------------------------------------  --------------------  --------
D01     시간 패턴         posting_date는 회계기간과 열린 fiscal calendar 안에 있다.                 폐쇄 기간 또는 미래 기간에 정상 전표가 다수 게시된다.    posting_date, fiscal_year, fiscal_period, period_open flag 대조.              [기존] rule/code: L1-08, SAP posting date            L1-08                 예
D02     시간 패턴         fiscal_period는 posting_date에서 유도되는 기간과 일치한다.                 3월 전기일이 fiscal_period=12로 기록된다.                posting_date month/fiscal calendar와 fiscal_period 불일치율 계산.             [기존] rule/code: L1-08                              L1-08                 예
D03     시간 패턴         document_date와 posting_date의 lag는 document_type별 자연 범위 안에 있다.  정상 vendor invoice가 180일 후 전기된다.                 abs(posting_date-document_date) bucket을 document_type/process별 집계.         [기존] rule/code: L3-07, SAP document/posting date    L3-07                 예
D04     시간 패턴         결산기 전표 집중은 월말·월초·연말에 증가하되 모든 전표가 결산일에 몰리지 않는다. 모든 정상 전표가 월말 2일에 생성된다.              posting_date day-of-month, period_end window, source별 count/amount share 계산. [기존+신규] rule L3-04, reference §6.7              L3-04, D02            예
D05     시간 패턴         주말·공휴일 전기는 소수이며 자동/배치 또는 결산기 맥락이 있어야 한다.       정상 수기 전표가 주말에 대량 입력된다.                  weekend/holiday flag 비율을 source, user, period_end별 계산.                 [기존] rule/code: L3-05, reference §6.5              L3-05                 예
D06     시간 패턴         업무시간 외 입력은 소수이며 결산기·자동배치·특정 role에 집중된다.          정상 사람이 새벽에 대량 수기 전표를 입력한다.            created_at/posting timestamp hour 분포와 normal_hours 밖 비율 계산.           [기존] rule/code: L3-06/L4-05, PCAOB JE focus        L3-06, L4-05          예
D07     시간 패턴         사용자별 비정상 시간 집중은 평균 주변에 분산되고 극단 user cluster는 드물다. 한 사용자가 대부분의 야간 전표를 생성한다.           user별 abnormal-hour ratio, z-score, top-user share 계산.                    [기존] rule/code: L4-05                              L4-05                 예
D08     시간 패턴         manual/adjustment entry는 결산기와 특정 계정군에 자연 집중하되 전체를 지배하지 않는다. 정상 원장 대부분이 수기 조정 전표다.       source 또는 is_manual_je 비율을 account/process/period별 계산.               [기존+신규] rule L3-02, PCAOB JE focus              L3-02                 예
D09     시간 패턴         자동·배치 전표는 일정한 job window와 반복 주기를 가진다.                   batch source가 임의 시각·임의 user로 산발 생성된다.       source=batch rows의 created_at hour, recurrence interval, job_id 분포 계산.   [신규] SAP/ERP batch domain, L4-06 역산             L4-06                 부분
D10     시간 패턴         한국 12월 결산 회사는 1~3월 결산조정·법인세 신고 준비 흐름이 존재한다.     1~3월 조정·역분개·세무 전표가 전혀 없다.                Jan-Mar adjustment/reversal/tax document 비율과 12월 결산 여부 대조.          [신규] reference §6.7, Korean domain                 L3-04, L2-05          예
```

## E. 권한·통제·직급 승인 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                               측정 방법(전수 계산 가능하게)                                           출처(rule/standard/web/design)                              연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  ------------------------------------------------------  -------------------------------------------------------------------------  -----------------------------------------------------------  --------------------  --------
E01     권한·통제         승인 필요 금액 이상 전표에는 승인자와 승인일이 존재한다.                고액 수기 전표에 approved_by와 approval_date가 없다.    approval_required 조건 산출 후 approved_by/approval_date 결측률 계산.      [기존] rule/code: L1-07/L1-09, ISA 330              L1-07, L1-09          예
E02     권한·통제         승인자는 금액과 업무유형에 맞는 승인한도 안에서 승인한다.               대리급 사용자가 임원 한도 전표를 승인한다.              approver limit master와 document_amount 비교, 초과 승인 비율 계산.          [기존] rule/code: L1-04, reference §6.1             L1-04                 예
E03     권한·통제         승인한도 직하 금액은 존재하지만 한도별 razor band에 과집중하지 않는다.  99,900,000원 같은 금액이 한도 직하에 반복된다.          amount/limit ratio, gap_ratio bucket, threshold별 count/amount share 계산.  [기존] rule/code: L2-01                              L2-01                 예
E04     권한·통제         작성자와 승인자는 원칙적으로 분리된다.                                  created_by와 approved_by가 같은 정상 전표가 대량 존재한다. created_by=approved_by 비율을 source/system allowlist별 분리 계산.          [기존] rule/code: L1-05, PCAOB/ISA JE control       L1-05                 예
E05     권한·통제         정상 baseline에는 confirmed SoD 위반 마커가 없다. 현실적 업무 겸직은 direct marker 없이 role/process 분포로만 존재한다.  정상 원장에 sod_violation=true 또는 sod_conflict_type이 대량 주입된다.       user_role/process matrix와 sod_toxic_pairs 대조, sod_violation=true document count, sod_conflict_type nonblank count, L1-06 confirmed count 계산. [기존] rule/code: L1-06                           L1-06                 예
E06     권한·통제         system/automation approval 예외는 allowlist와 source type으로 설명된다. 시스템 전표가 사람 승인 누락으로 무작위 표시된다.       source/system_user allowlist별 approval exception count 계산.               [기존+신규] rule L1-05/L1-07 allow config            L1-05, L1-07          예
E07     권한·통제         승인 lag는 업무유형별 자연 범위 안에 있고 음수 lag가 없어야 한다.       승인일이 작성일보다 이전이거나 90일 뒤 승인된다.        approval_date-created_at/posting_date lag bucket을 process/source별 계산.   [신규] rule 역산: L1-09, workflow domain             L1-09                 예
E08     권한·통제         사용자별 업무범위는 role/persona에 맞는 회사·프로세스·계정 수 안에 있다. 한 사용자가 모든 회사와 모든 프로세스 전표를 생성한다. user별 distinct company/process/account counts와 persona threshold 대조.     [기존] rule/code: L3-12                              L3-12                 예
E09     권한·통제         직급별 승인 건수와 승인 금액 분포는 조직 구조와 일관된다.              하위 직급 사용자가 대부분의 고액 승인권을 행사한다.     approver_level별 approval_count, amount_quantile, limit utilization 계산.    [신규] reference §6.1, rule L1-04 역산              L1-04                 예
E10     권한·통제         IT admin 또는 privileged user의 일반 전표 작성은 제한적이다.           IT 관리자 persona가 고액 결산 전표를 대량 작성한다.     user_persona=IT/admin rows의 amount/source/process/account 비율 계산.        [기존+신규] rule/code: L1-06 IT admin config          L1-06, L3-12          예
E11     권한·통제         source별 승인 presence, approval_lag, approver_type 분포는 workflow 정책과 일치한다. manual 승인 누락 0%, automated 승인자 0건, approval blank 73%처럼 이분법적 패턴이 발생한다. source × approval_required × approved_by 존재 × approval_lag × approver_type 분포 계산. manual 고액/민감 전표 승인 존재, automated system/job approval, recurring 사전승인 master 또는 batch approval link를 함께 확인한다. [신규] source별 approval 현실성, v2 failure          L1-04, L1-07, L1-09   예
E12     권한·통제         created_by user_type은 source와 business_process에 맞아야 한다.        automated 전표 대부분을 일반 사람이 만들거나 manual 전표를 system user가 만든다. source별 human/system user 비율, top system job user concentration, user role allowed process 대조. system-user 전표의 human approval 불필요 조건과 recurring batch approval link는 E11과 상호 일관되어야 한다. [신규] system/human user 정합, v2 failure          L1-06, L3-02, L3-12   예
```

## F. 마스터 참조 무결성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                      위반 예시                                         측정 방법(전수 계산 가능하게)                                         출처(rule/standard/web/design)                         연결된 phase1 룰        전수 적용
------  ----------------  ----------------------------------------------------------------  ------------------------------------------------  -----------------------------------------------------------------------  ------------------------------------------------------  --------------------  --------
F01     마스터 무결성     gl_account는 CoA master에 존재하고 postable 상태다.               존재하지 않거나 placeholder 계정이 정상 row에 있다. gl_account 정규화 후 CoA/postable/reserved flag 대조.                 [기존] rule/code: L1-03                              L1-03                 예
F02     마스터 무결성     company_code는 회사 master에 존재한다.                            원장에 master 없는 회사코드가 나타난다.           company_code distinct set과 company master 대조.                         [신규] ERP master integrity, Company-Centric          L1-02, L3-03          예
F03     마스터 무결성     counterparty_id와 counterparty_type은 typed master에 존재한다.     vendor ID가 customer type으로 기록된다.           counterparty_id/type/name을 unified counterparty master와 대조.             [기존] design: counterparty-master-design             L2-02, L3-03          예
F04     마스터 무결성     counterparty name signal은 counterparty_type과 일치한다.            은행 이름이 VENDOR_OFFICE_SUPPLIES로 분류된다.    name signal rule로 inferred_type 산출 후 stored counterparty_type과 비교.    [기존] design: counterparty name classification       L3-01, L3-03          예
F05     마스터 무결성     created_by, approved_by는 사용자 master에 존재하고 active 상태다.   퇴사자 또는 미등록 사용자가 전표를 작성·승인한다. user_id별 employee/user master existence, active_from/to validity 계산.     [기존+신규] rule L1-04~L1-07, access domain           L1-04~L1-07           예
F06     마스터 무결성     trading_partner는 관련 회사 또는 외부 거래처 식별체계와 일관된다.  관계사 코드 자리에 고객코드 형식이 들어간다.       trading_partner format regex, related_party_master, company_code 대조.      [기존] rule/code: IC01, intercompany_rules.py         L3-03, IC01           예
F07     마스터 무결성     계정코드 형식은 프로젝트 CoA 체계와 일관된다.                      숫자 CoA에서 문자/소수점 계정코드가 생성된다.     account code regex, length, prefix family, malformed ratio 계산.            [기존] rule/code: L1-03 bucket                        L1-03                 예
F08     마스터 무결성     document_type, source, business_process 값은 허용 enum 안에 있다. 임의 문자열 document_type이 정상 row에 섞인다.      distinct value set을 schema/scenario allowed enum과 대조.                   [기존+신규] design: scenario metadata, SAP JE type    L1-02, L3-01          예
```

## G. 자연 noise·데이터 품질 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                          위반 예시                                                측정 방법(전수 계산 가능하게)                                          출처(rule/standard/web/design)                              연결된 phase1 룰        전수 적용
------  ----------------  --------------------------------------------------------------------  -------------------------------------------------------  ------------------------------------------------------------------------  -----------------------------------------------------------  --------------------  --------
G01     자연 noise        필수 필드는 정상 데이터에서 결측 0 또는 극소여야 한다.                 document_id, gl_account, amount가 정상 row에서 결측된다. required columns별 null/blank count와 L1-02 field score bucket 계산.      [기존] rule/code: L1-02                              L1-02                 예
G02     자연 noise        선택 필드 결측은 존재할 수 있으나 특정 라벨·그룹에 shortcut으로 쏠리지 않는다. 특정 anomaly-like group만 cost_center가 결측이다. optional columns별 missing rate를 company/process/account/source별 비교.     [기존+신규] design: regeneration contract, anti-fitting L1-02, PHASE2          예
G03     자연 noise        오타·서식 변동은 낮은 비율로 존재하되 의미 모순을 만들지 않는다.       정상 payroll text가 office supplier 전표에 들어간다.     text corruption/typo flag 비율과 semantic fail condition 동시 발생률 계산.  [기존] design: semantic validator, L3-08              L3-08, L3-01          예
G04     자연 noise        날짜·금액·코드 서식 변동은 parser가 복구 가능한 수준이어야 한다.      날짜가 여러 포맷으로 무작위 혼합되어 period 계산이 깨진다. parse failure rate, normalized value equality, invalid format count 계산.     [신규] data quality/web, L1-02/L1-08 역산             L1-02, L1-08          예
G05     자연 noise        중복 row나 redundant tuple은 source-specific 자연 중복과 오류 중복을 구분할 수 있어야 한다. 같은 전표 line이 복제되어 row count가 늘어난다. exact row duplicate count, same document line_number duplicate count 계산.      [신규] data quality catalog, L2-03 역산              L2-03                 예
G06     자연 noise        정상 데이터 품질 noise는 VAE/ML shortcut feature가 되지 않아야 한다.    결측 여부만으로 synthetic label이 구분된다.          normal subset에서 missing/typo/format flag의 process/account/source 균등성 검정. [기존+신규] AGENTS/DataSynth guard, phase2 profile     PHASE2                예
G07     자연 noise        encoding corruption은 소수여야 하며 한글 mojibake가 대량 발생하지 않는다. 적요 대부분이 깨진 문자로 구성된다.                line_text/header_text의 replacement char, control char, mojibake pattern count 계산. [기존+신규] rule L3-08, Korean encoding guard         L3-08                 예
G08     자연 noise        semantic mismatch가 발생했을 때 원인이 MCAR/typo/format noise인지 generator domain mismatch인지 분해 가능해야 한다. 노이즈 때문인지 생성 로직 때문인지 구분되지 않는다. noise_flag/quality_issue_id가 있는 row와 semantic fail row overlap, noise 없는 row의 semantic mismatch rate, mismatch source attribution coverage 계산. [신규] diagnostic provenance, v2 failure             L3-01, L3-08          예
G09     자연 noise        정상 데이터는 hard invariant를 깨지 않으면서 낮은 비율의 운영상 예외와 보완 흐름을 포함한다. 모든 정상 전표가 승인 지연, reference typo, 사후 첨부, cost center 보완, 정상 duplicate-shaped control 없이 지나치게 깨끗하다. approval delay, low-value approval blank, parseable reference typo, late attachment, corrected cost center, duplicate-shaped controlled document 비율을 cleanliness index로 집계. cleanliness 예외는 parser 복구 가능하거나 correction/provenance로 설명 가능한 필드에만 허용하고, 회계균형·master key·semantic contract는 깨지 않는다. [신규] operational imperfection realism               L1-09, L2-03, L3-08   예
```

## H. 텍스트·적요 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                      위반 예시                                             측정 방법(전수 계산 가능하게)                                         출처(rule/standard/web/design)                         연결된 phase1 룰        전수 적용
------  ----------------  ----------------------------------------------------------------  ----------------------------------------------------  -----------------------------------------------------------------------  ------------------------------------------------------  --------------------  --------
H01     텍스트·적요       header_family는 selected scenario의 allowed_header_families 안에 있다. payroll header가 purchase invoice scenario에 붙는다. scenario_id/event_type별 header_family allowed set 대조.              [기존] design: text-document-family                  L3-01, L3-08          예
H02     텍스트·적요       line_text_family는 semantic account subtype과 호환된다.              직접노무비 적요가 사무용품 vendor invoice에 붙는다. line_text_family × semantic_subtype × counterparty_type 허용표 대조.       [기존] design: text-document-family, SEM009          L3-01, L3-08          예
H03     텍스트·적요       line_text/header_text는 정상 전표에서 비어 있거나 파손되지 않는다.   고액 수기 결산 전표의 적요가 공란이다.              blank, whitespace-only, corrupted text count를 amount/source/period별 계산. [기존] rule/code: L3-08                              L3-08                 예
H04     텍스트·적요       적요 토큰은 document_type, source_document, counterparty domain과 모순되지 않는다. 세금계산서 전표에 급여 원천세 적요가 붙는다. raw keyword detector로 labor/depreciation/revenue/customer tokens와 scenario 비교. [기존] design: semantic-validator-design              L3-01, L3-08          예
H05     텍스트·적요       반복 템플릿은 존재하되 모든 적요가 동일하지 않다.                   정상 데이터의 line_text가 전부 같은 문장이다.       text family별 unique ratio, entropy, top-template share 계산.              [신규] ERP text realism, L2-03/L4-06 역산             L2-03, L4-06          예
H06     텍스트·적요       reversal/accrual/payment 텍스트는 실제 reversal/accrual/payment 구조와 연결된다. 역분개 적요가 있으나 반대 전표가 없다.          reversal/accrual keyword rows의 reference/reversal_id/counter-document 존재율 계산. [기존+신규] design text family, SAP reversal          L2-05                 부분
```

## I. 전표 구조·번호·참조 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                      측정 방법(전수 계산 가능하게)                                      출처(rule/standard/web/design)                         연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  ---------------------------------------------  --------------------------------------------------------------------  ------------------------------------------------------  --------------------  --------
I01     전표 구조         document_id는 회사·연도 범위에서 고유하고 row는 같은 document_id로 묶인다. 서로 다른 전표가 같은 document_id를 공유한다. document_id별 company/year/document_type consistency, duplicate doc id count 계산. [신규] ERP document integrity, SAP JE structure       L1-01, L2-03          예
I02     전표 구조         line_number는 document 안에서 유일하고 순차적이다.                     한 전표에 line_number=1이 두 번 나온다.       document_id별 line_number duplicate, gap, nonpositive count 계산.         [신규] ERP line structure, L1-01 역산                L1-01                 예
I03     전표 구조         reference/invoice/payment key는 업무 흐름과 연결된다.                  payment 전표에 invoice reference가 없다.       document_type/process별 required reference populated rate 계산.           [기존+신규] L2-02/L2-03 prerequisite, SAP domain      L2-02, L2-03          부분
I04     전표 구조         전표번호 체계는 company/year/document_type별 번호 범위와 증가 패턴을 가진다. 전표번호가 완전 난수로 생성된다.           document_id/accounting_document_number prefix, sequence gap, monotonicity 계산. [신규] SAP number range/domain                      L2-03                 부분
I05     전표 구조         source_document와 GL document는 합리적 N:1 또는 1:N 관계를 가진다.      하나의 invoice가 수백 개 무관 전표에 연결된다. source_document_id별 linked document count, amount consistency, process consistency 계산. [신규] ERP subledger-to-GL reality                  L2-02, L2-05          부분
```

## J. 반복·중복·역분개·배치 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                                측정 방법(전수 계산 가능하게)                                      출처(rule/standard/web/design)                              연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  -------------------------------------------------------  --------------------------------------------------------------------  -----------------------------------------------------------  --------------------  --------
J01     반복·중복         같은 counterparty·amount·reference의 중복 지급은 정상에서 희소하다.    동일 vendor invoice가 두 번 지급된다.                 partner/amount/reference/date window별 duplicate payment group count 계산. [기존] rule/code: L2-02                              L2-02                 예
J02     반복·중복         exact/fuzzy/split duplicate document는 정상에서 희소하고 routine source로 설명된다. 같은 금액·계정·텍스트 전표가 여러 번 생성된다. duplicate signature, fuzzy text, split window, serial duplicate count 계산. [기존] rule/code: L2-03                              L2-03                 예
J03     반복·중복         반복 지급·정기 비용은 periodicity와 vendor/contract 맥락을 가진다.     매일 같은 금액이 무작위 vendor로 지급된다.           counterparty/account/amount recurring interval, coefficient of variation 계산. [신규] ERP realism, L2-03 normal duplicate population L2-03                 예
J04     반복·중복         역분개는 원전표, 반대 금액, 계정쌍, reversal reason/date와 연결된다.    역분개 전표가 있으나 원전표 참조가 없다.             original_document_id/reversal_document_id 보유율, 원전표 존재, GL별 pair net, date order 계산. [기존+신규] rule/code L2-05, SAP reversal             L2-05                 예
J05     반복·중복         batch posting은 job/user/source/time window 단위로 설명된다.           배치 전표가 임의 user·임의 시간으로 과다 생성된다.    source=batch rows의 batch_id/job_id/time cluster/row_count distribution 계산. [기존+신규] rule/code: L4-06, SAP automation          L4-06                 부분
J06     반복·중복         O2C invoice/receipt offset은 정상 중복 후보로 구분 가능해야 한다.      정상 수금 offset이 duplicate fraud처럼 보인다.       O2C receipt/invoice offset signature와 zero-score population ratio 계산.    [기존] code: fraud_rules_groupby O2C suppress          L2-03                 부분
J07     반복·중복         accrual과 reversal은 월말 설정·익월 취소 같은 정상 pair pattern을 가진다. 발생액 설정은 있으나 취소 전표가 없다.            R2R_ACCRUAL↔R2R_REVERSAL linked pair의 shared reference, 반대 계정/금액, 익월 posting, unlinked reversal 0건 계산. [기존+신규] text family/SAP auto-reverse             L2-05, L3-04          예
J08     반복·중복         2~10라인 일반 전표와 100+라인 batch 전표는 생성 원인, source, job_id, batch_type이 다르다. 1,000라인 일반 vendor invoice가 batch 설명 없이 생성된다. line_count p95/p99/max by scenario/source/document_type, line_count threshold 초과 문서의 batch_id/job_id/source/process/batch_type 존재율 계산. 500+라인은 payroll allocation, depreciation run, payment batch 등 허용 batch type이어야 한다. [신규] high-line-count explainability, v2 failure   L4-06                 예
J09     반복·중복         정상 baseline에도 원전표 링크가 있는 정상 역분개가 충분히 존재해 original_document_id/reversal_document_id non-null 표면이 부정 전용이 아니어야 한다. 정상에는 원전표 링크가 거의 없고 PHASE2 overlay에만 original_document_id가 채워진다. linked normal reversal 문서 수, original_document_id/reversal_document_id non-null 정상 비율, reversal_type/reason/source 분포, 원전표 존재·이후 전기·pair net 0 여부를 계산한다. 정상 linked reversal이 0 또는 설정 floor 미만이면 FAIL/BLOCKED. [신규] phase2_full_leak_scan_r4l_b L6 original_document_id 누수 회귀 가드 L2-05, PHASE2          예
```

## K. 관계사·내부거래·그래프 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                                   측정 방법(전수 계산 가능하게)                                       출처(rule/standard/web/design)                              연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  ----------------------------------------------------------  ---------------------------------------------------------------------  -----------------------------------------------------------  --------------------  --------
K01     관계사·내부거래   related-party row는 RELATED_PARTY counterparty와 IC scenario를 가진다.  일반 고객 거래가 is_intercompany=true로 표시된다.           is_intercompany rows의 counterparty_type, company_code, trading_partner 대조. [기존] design/rule: L3-03, counterparty master        L3-03                 예
K02     관계사·내부거래   IC receivable/payable 계정은 pair_map에서 대응 prefix를 가진다.         관계사 채권 계정만 있고 대응 채무 계정 체계가 없다.        IC GL prefix별 pair_map coverage, unpaired prefix count 계산.              [기존] rule/code: intercompany_rules.py               L3-03, IC01           예
K03     관계사·내부거래   양방향 내부거래는 금액 대사가 허용오차 안에 있다.                       A법인 채권 100, B법인 채무 70으로 남는다.                 match_ic_groups 결과의 diff_ratio, amount_tolerance 초과 count 계산.       [기존] rule/code: IC02, IFRS 10/K-IFRS 1110           IC02                  예
K04     관계사·내부거래   양방향 내부거래의 전기일 차이는 정상 결산 grace window 안에 있다.       대응 내부거래가 수개월 뒤 전기된다.                       match_ic_groups date_diff_days와 month-end close lag 예외 적용 후 초과 count 계산. [기존] rule/code: IC03                          IC03                  예
K05     관계사·내부거래   trading_partner format은 회사코드/관계사 master와 일치한다.            IC partner 필드에 vendor/customer 코드가 입력된다.         partner_format regex, related_party_master, company_code cross-match 계산. [기존] rule/code: IC01                               IC01                  예
K06     관계사·내부거래   정상 내부거래 순환은 업무상 물류·정산 flow로 설명 가능해야 한다.       A→B→C→A 순환이 매출·채권 계정으로만 구성된다.             graph cycle rows의 scenario_id, event_type, account subtype, source_document linkage 계산. [기존+신규] rule/doc: GR01 normal controls          GR01                  부분
K07     관계사·내부거래   양방향 IC 가격·금액 비대칭은 정상 데이터에서 희소하다.                 A→B 평균가와 B→A 평균가가 큰 차이를 보인다.               GR03 direction pair별 mean amount deviation, reference pair deviation 계산. [기존] rule/code: GR03                                GR03                  예
```

### K01~K07 v20 NORMAL acceptance 기준

v20부터 NORMAL baseline은 PHASE1 `IntercompanyMatcher`와 `GraphDetector`가 0건/skip으로 끝나지 않도록
정상 관계사·내부거래·회사 그래프 배경을 포함해야 한다. 이 배경은 fraud/anomaly가 아니며, detector recall에
맞춘 토큰 샘플이 아니라 실제 그룹회사 운영에서 발생하는 정상 모집단이어야 한다.

```text
검사ID      Required fields / 원천                         PASS 기준(초기 v20)                                                                                  FAIL / BLOCKED 기준
----------  ----------------------------------------------  -----------------------------------------------------------------------------------------------------  ------------------------------------------------------------
K01         is_intercompany, counterparty_type, company_code, trading_partner, semantic_scenario_id  is_intercompany=true document가 충분히 존재하고, trading_partner가 자기 자신이 아닌 그룹 회사코드(C001/C002/C003 등)를 가리키며, counterparty_type/scenario가 RELATED_PARTY/Intercompany 계열이다. 일반 고객/벤더 코드가 IC로 표시되면 FAIL. is_intercompany 컬럼이 없으면 BLOCKED.
K02         gl_account, debit_amount, credit_amount, config/audit_rules.yaml intercompany.pairs      IC row의 GL prefix가 pair_map(1150↔2050, 4500↔2700 등)에 의해 receivable/payable 역할로 분류 가능하다. rec/pay prefix coverage가 모두 존재해야 한다. 한쪽 prefix만 있거나 pair_map 밖 계정이 IC 대부분을 차지하면 FAIL.
K03         document_id/reference/company_code/trading_partner/posting_date/amount/GL                 정상 IC 대사쌍 수가 0이 아니며, shared reference 또는 deterministic pair key로 회사 A 채권/수익과 회사 B 채무/미지급이 허용오차 내에서 매칭된다. 정상 baseline의 diff_ratio p95는 낮아야 하며 tolerance 초과 pair는 희소해야 한다. 대사쌍 0건이면 FAIL.
K04         posting_date, document_date, fiscal_period, reference/pair key                            정상 IC 대사쌍의 date_diff_days가 결산 grace window 안에 분포한다. p95가 정상 close lag 안에 있어야 하며 수개월 lag가 대량이면 FAIL.
K05         trading_partner, company master, partner_format regex                                     trading_partner namespace는 company_code와 동일하게 폐합 가능해야 한다. `IC-C001`처럼 detector/company graph가 별도 노드로 읽는 namespace는 금지한다. vendor/customer regex가 IC row에 섞이면 FAIL.
K06         company_code, trading_partner, is_intercompany, amount, scenario_id/event_type/account_subtype, reference/source_document/batch/job 설명 필드  정상 3-hop+ cycle이 소량 존재하되 회사 노드 기반이어야 한다. unique topology 수만 보지 말고 반복 거래 인스턴스 수(cycle_instance_count)를 함께 센다. cycle은 업무상 물류·정산·shared service recharge 등으로 설명 가능한 scenario/account mix를 가져야 하며, 매출/채권 계정만 반복되는 무근거 round-trip이면 FAIL. cycle instance 0건은 GraphDetector smoke 목적상 FAIL 또는 BLOCKED.
K07         company_code/trading_partner 방향 pair, amount, unit/quantity 가능 시, reference          정상 양방향 IC의 금액·건수 비대칭은 일방향 지배 수준이면 안 된다. 완전 대칭을 요구하지 않고 direction pair별 total amount/count asymmetry를 보고한다. 대량 비대칭은 FAIL, 소량의 FX/rounding/month-end 차이는 MONITOR로 보고 가능하다.
```

운영 기준:

- `is_intercompany`는 생성기가 아는 authoritative feature지만 fraud/anomaly label이 아니다. 정상 row에서 true가
  되는 것이 정상이며, 이 컬럼만으로 이상 여부를 뜻하면 안 된다.
- `trading_partner`는 회사 그래프 노드로 직접 쓰이므로 그룹 회사코드와 같은 namespace를 사용한다.
  `C001`, `C002`, `C003`처럼 detector의 `partner_format.ic_partner_regex`와 company master가 동일하게
  해석할 수 있어야 한다.
- O02 synthetic marker scan은 `is_intercompany=true`와 회사코드 `trading_partner`처럼 K01~K07의 정상
  구조 필드를 fraud/provenance token으로 오탐하지 않는다. 해당 구조 필드의 적정성은 K01~K07에서
  별도 검증한다.
- 정상 IC 볼륨은 토큰 샘플 금지. v20 초기 목표는 36개월×3개 법인에 분산된 정상 IC document
  1,000~3,000건, 정상 대사 pair 500~1,500건, 정상 3-hop cycle 12~36개 수준을 권장한다.
  실제 생성 결과는 수치로 보고하고, detector threshold에 맞춘 사후 튜닝은 금지한다.
- 정상 IC 매칭률은 높아야 한다. `K03`은 matched pair rate가 95% 이상인지, diff_ratio p95/max,
  tolerance 초과 pair 수를 보고한다. 100% exact만 강제하면 합성티가 나므로 정상 rounding/FX/close lag
  tail은 소량 허용하되 anomaly로 라벨하지 않는다.
- `K06` 정상 순환은 PHASE1 GR01 smoke에서 일부 review candidate로 surface될 수 있다. 이는 정상 배경이
  detector 입력 경로에 들어왔다는 의미이지 fraud 성공/실패 지표가 아니다. 수락 기준은 "회사 노드 기반,
  설명 가능한 flow, 비오라클 분산"이다.
- 기존 Gate 0/1 항목(A01, B15/B16, L06, G08/G09, O02, J08)은 v20에서도 무회귀 PASS가 필수다.

## L. 증빙·세무·원천문서 현실성

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                                  측정 방법(전수 계산 가능하게)                                         출처(rule/standard/web/design)                              연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  ---------------------------------------------------------  -----------------------------------------------------------------------  -----------------------------------------------------------  --------------------  --------
L01     증빙·세무         3만원 초과 지출은 세금계산서·카드·현금영수증 등 적격증빙을 가진다.     고액 비용 전표에 receipt_type이 없거나 부적격이다.       amount>30000 and expense/P2P rows의 qualified_receipt_type populated/allowed rate 계산. [신규] docs reference §6.2, PwC Korea               L1-02, L3-08          부분
L02     증빙·세무         purchase tax invoice는 vendor, VAT, AP/GRIR, P2P 의미와 일치한다.       세금계산서 전표가 payroll text 또는 employee counterparty를 가진다. document_type/source_document=tax_invoice rows의 counterparty/process/account/text 대조. [기존] design: SEM005, PwC Korea                  L3-01, L2-04          예
L03     증빙·세무         customer invoice는 customer counterparty, revenue/AR 계정, O2C 흐름과 연결된다. 매출 세금계산서가 vendor에게 발행된다.             customer invoice rows의 CUSTOMER type, revenue/AR account, O2C process 대조. [기존] design: SEM007/SEM008, L3-11                 L3-11, L4-01          예
L04     증빙·세무         증빙일, 문서일, 전기일은 source document lifecycle과 자연 순서를 가진다. 증빙일보다 훨씬 전의 posting_date가 생성된다.          evidence_date/document_date/posting_date lag direction과 bucket 계산.       [신규] SAP document/posting date, audit evidence      L3-07, L3-11          부분
L05     증빙·세무         원천세·4대보험·급여세 항목은 payroll/tax authority/payment 흐름에 속한다. 원천세 적요가 office supplier invoice에 붙는다.          tax/payroll keywords와 counterparty_type, process, semantic_subtype 허용표 대조. [기존+신규] design text family, Korean tax domain      L3-01, L3-08          예
L06     증빙·세무         부가세 처리는 거래 아키타입과 증빙에 따라 과세(10%)·영세율·면세·비과세/대상외·수입부가세로 구분된다. reference suffix나 난수로 영세/면세가 정해진다. tax_treatment × supporting_doc_type × business_process × account_subtype × tax_code × VAT GL line 정합 대조. 과세/수입부가세는 세금계산서/수입장과 VAT GL line이 있고, 영세율은 수출신고필증 등 수출 근거와 0% code, 면세는 계산서와 면세 code, 비과세/대상외는 급여·감가상각·내부대체·차입상환 등 VAT code 없음이어야 한다. [신규] Korean VAT domain, NTS VAT guide                  L1-02, L3-01          예
```

## M. 재무제표·잔액 정합

```text
검사ID  카테고리              정상 기대(무엇이 정상인가)                                           위반 예시                                               측정 방법(전수 계산 가능하게)                                             출처(rule/standard/web/design)                         연결된 phase1 룰        전수 적용
------  --------------------  ---------------------------------------------------------------------  ------------------------------------------------------  ---------------------------------------------------------------------------  ------------------------------------------------------  --------------------  --------
M01     재무제표·잔액 정합    GL 계정별 당기 합계는 시산표(TB)의 계정별 당기 변동과 일치한다.        전표 합계와 TB 금액이 계정별로 다르다.                 GL을 company/year/period/gl_account별 집계해 TB debit/credit 또는 ending movement와 대조. [신규] 회계 전수 정합, ISA 330/500 evidence       L1-01, D01            부분
M02     재무제표·잔액 정합    기말 재무상태표는 자산 = 부채 + 자본 + 당기누적손익을 만족한다. 월별 soft-close에서는 P&L이 아직 이익잉여금으로 닫히지 않았으므로 당기누적손익을 자본에 포함한다. 연말 closing 후에는 손익계정이 0으로 닫힌다. 기말 자산 총액이 부채+자본+당기손익과 맞지 않는다. TB ending balance를 계정분류별 집계해 assets - liabilities - equity - current_ytd_income 차이 계산. KRW는 원 단위 정수로 비교한다. [신규] 복식부기/재무제표 기본 등식                  L1-01                 부분
M03     재무제표·잔액 정합    계정별 기초잔액 + 당기차변 - 당기대변 = 기말잔액이 성립한다.          계정 roll-forward가 끊긴다.                            account/company/period별 opening, debit, credit, closing roll-forward 차이 계산. [신규] 회계 roll-forward 정합                       D01, D02              부분
M04     재무제표·잔액 정합    이전 기간 기말잔액은 다음 기간 기초잔액과 연속된다.                   3월 기말잔액과 4월 기초잔액이 불일치한다.              account/company별 prior closing과 current opening difference 계산.            [신규] 기간 간 roll-forward 연속성                   D01, D02              부분
M05     재무제표·잔액 정합    당기손익은 이익잉여금 변동 또는 closing entry 흐름과 연결된다.        손익계정이 닫히지 않거나 이익잉여금 변동과 불일치한다. P&L account net income과 retained earnings movement/closing document 대조.    [신규] 재무제표 연결 정합                            D01, D02              부분
M06     재무제표·잔액 정합    계정분류별 정상 잔액 방향이 대체로 유지된다. 감가상각누계액 같은 contra 계정, 이익잉여금 누적결손, 손익계정의 기간 중 역방향 누계는 별도 diagnostic으로 분리한다. BS hard 반대잔액은 소수 overdraft/debit-balance 실무를 허용하되 2% 초과 또는 특정 계정 과집중이면 MONITOR/FAIL이다. 매출채권 계정이 장기간 대변잔액으로 과다 누적된다. account_category별 debit/credit normal balance direction 위반 계정 수와 rate 계산. contra/retained deficit/P&L reverse balance는 별도 metric. [신규] CoA/TB 현실성, L1-03 역산                   L1-03, L3-01          부분
M07     재무제표·잔액 정합    보조원장 합계는 GL control account와 일치한다. NORMAL baseline에서는 AR/AP/Inventory/FA 보조원장을 최종 GL control-account 라인의 거래처/auxiliary 상세에서 파생해 구조적으로 일치시킨다. 보조원장≠GL은 정상 오류가 아니라 P3-3 부정/오류 주입 대상이다. AP subledger 합계와 매입채무 GL 잔액이 다르다. AR/AP/inventory/fixed asset subledger ending balance와 GL control account 대조. [신규] ERP subledger-to-GL 정합                    L2-02, L3-11          부분
M08     재무제표·잔액 정합    TB는 JE, 기초이월, closing/carry-forward 규칙에서 파생된 단일 진실이어야 한다. TB가 JE와 독립 산출되어 어떤 월 차대합·월 net·YTD 정의로도 맞지 않는다. `audit_balance_integrity.py <dataset>`로 전 TB 라인을 기초이월+당기 JE 누적과 1원 내 대조하고, 마감·이월 규칙을 리포트에 남긴다. [신규] v42 N10 TB-JE 단절 회귀 가드               L1-01, D01, PHASE2    예
M09     재무제표·잔액 정합    연도별 opening balance는 전년 기말에서 이월되어야 하며 P&L은 연말 closing 후 이익잉여금으로 닫힌다. opening_balances.json이 3레코드·소수 dummy 계정만 있어 2023/2024 기초가 전년 기말과 무관하다. `audit_balance_integrity.py <dataset>`로 current FY FP1 inferred opening = prior FY final TB를 전 계정 1원 내 대조한다. [신규] v42 N11 연도 이월 미구현 회귀 가드        D01, D02, PHASE2      예
M10     재무제표·잔액 정합    subledger_reconciliation.json은 실제 AR/AP/Inventory/FA 보조원장 합계와 GL control 잔액의 실측 차이를 기록하고 normal에서는 차이가 0이어야 한다. recon 파일은 difference 0이라고 쓰지만 실제 AR 합계와 GL 1100 잔액이 크게 다르다. `audit_balance_integrity.py <dataset>`로 recon difference≠0, AR/AP 등 보조원장 합계 vs GL control 실측 불일치, recon 기록값과 실측값 불일치를 hard fail로 계산한다. [신규] v42 N12 hollow subledger recon 회귀 가드   L2-02, L3-11, PHASE2  예
```

## N. 경제적 타당성·보조원장 한계

이 카테고리는 synthetic 데이터의 경제적 현실성을 기록하기 위한 후보 항목이다.
강제 pass/fail 기준으로 쓰지 않는다.
전수 계산은 가능하더라도 정상 범위는 산업, 회사 규모, 경기, 가격 변동, 회계정책에 의존하므로 실데이터 또는 명시된 생성기 설계 가정이 필요하다.

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                             측정 방법(전수 계산 가능하게)                                          출처(rule/standard/web/design)                            연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  ----------------------------------------------------  ------------------------------------------------------------------------  ---------------------------------------------------------  --------------------  --------
N01     경제적 타당성     매출총이익률은 산업·회사·기간별 생성기 가정 안에서 안정적 변동을 보인다. 매출과 매출원가가 독립 난수처럼 움직인다.        revenue, COGS 계정 집계로 gross margin ratio와 기간별 변동률 계산.         [신규] economic realism, 실데이터 한계                 L4-01, D01, PHASE2    예
N02     경제적 타당성     판관비율·인건비율·감가상각비율은 회사 규모와 기간 흐름에 맞는 범위에 있다. 비용비율이 매월 비현실적으로 급변한다.       expense category별 revenue 대비 ratio, rolling volatility, 계절성 계산.     [신규] economic realism, 실데이터 한계                 D01, D02, PHASE2      예
N03     경제적 타당성     AR/AP 회전과 회수·지급 기간은 O2C/P2P 흐름과 연결된다.                 매출은 증가하지만 AR 회수 흐름이 전혀 없다.             AR/AP ending balance, sales/purchases, cash receipt/payment로 turnover/DSO/DPO 계산. [신규] economic realism, 실데이터 한계             L2-02, L3-11          부분
N04     경제적 타당성     재고·COGS·매입 흐름은 제조/유통 시나리오와 연결된다.                   COGS가 발생하지만 재고 입출고나 매입 흐름이 없다.      inventory balance, purchases, COGS, production/issue subledger의 roll-forward 계산. [신규] economic realism, 실데이터 한계             L3-01, D01            부분
N05     경제적 타당성     가격상승·물량증가 등 정상 사업 이벤트는 계정 활동량 변화와 일관된다.     매출 증가는 있으나 가격/수량/거래처 증가 근거가 없다.  D01 normal_business_control reason과 price/volume/customer count 변화 대조. [기존+신규] D01 normal business event, economic realism  D01, D02              부분
N06     경제적 타당성     수량·단가 필드가 있는 보조원장에서는 amount = quantity × unit_price 정합이 성립한다. 금액이 수량×단가와 맞지 않는다. quantity, unit_price, amount 또는 net_amount의 차이와 허용오차 계산. [신규] supplementary schema, three-way match domain       L2-02, L3-01          부분
N07     신규계정 자연화   PHASE2 확장 신규계정은 회사·연도·월 셀별 발생 건수가 완벽히 균일하면 안 된다. 모든 회사·연도·월에 정확히 4건씩 생성된다. 14개 신규계정별 company×year×month row/doc count std와 empty-cell count 계산. std=0 또는 empty=0이면 FAIL. [신규] v30 hollow PASS, new account realism PHASE2 예
N08     신규계정 자연화   PHASE2 확장 신규계정은 계정 성격상 가능한 복수 거래처/상대 유형에 분산된다. 신규 대여금 전표가 전부 Bank, 무형자산 전표가 전부 None이다. 신규계정별 trading_partner 및 counterparty_type top share, unique count 계산. 단일값 100%면 FAIL. [신규] v30 counterparty shortcut PHASE2 예
N09     신규계정 자연화   PHASE2 확장 신규계정 금액은 기존 유사 정상계정처럼 heavy-tail 또는 넓은 자연 변동을 가진다. 신규계정 금액이 좁은 선형 범위에만 놓인다. 신규계정별 max/p50, p95/p50, unique amount share를 기존 control 계정 2개 이상과 비교. max/p50이 지나치게 낮으면 FAIL. [신규] v30 amount linearity shortcut PHASE2 예
N10     신규계정 자연화   PHASE2 확장 A계정군은 전용 scenario에 격리되지 않고 기존 정상 흐름 archetype에 woven되어야 한다. 신규계정이 R2R_ESTIMATE_AND_CLOSE 같은 전용 scenario 1개에만 존재한다. A계정군별 allowed existing archetype membership docs/rows와 scenario diversity 계산. woven membership 0이면 FAIL. [신규] v30 scenario isolation shortcut PHASE2 예
N11     신규계정 자연화   PHASE2 확장 신규계정 row에는 fraud/anomaly/provenance 라벨이 없어야 한다. 신규계정 정상 배경에 fraud_type 또는 mutation provenance가 남아 있다. 신규 14계정 subset에서 is_fraud/is_anomaly/fraud_type/mutation_* nonblank count 계산. 0이 아니면 FAIL. [신규] new account normal-only guard PHASE2 예
N12     세금·통화 정합   taxable_10 거래는 tax_amount=round(supply_amount*10%)이고 invoice_amount=supply_amount+tax_amount 여야 한다. taxable_10 행의 세액이 1% 수준으로 저산정되거나 invoice 합계가 깨진다. `audit_amounts_tax.py <dataset>`로 taxable_10 세액 오차>1원 건수와 invoice=supply+tax 불일치 건수를 계산. 둘 다 0이 아니면 FAIL. [신규] v42 tax calculation bug, Korean VAT        L1-02, L3-01, PHASE2 예
N13     세금·통화 정합   KRW 거래의 exchange_rate는 1이어야 한다. KRW 정상 주입행에 exchange_rate가 1이 아닌 값으로 들어가 synthetic marker가 된다. `audit_amounts_tax.py <dataset>`로 currency='KRW' AND exchange_rate != 1 또는 NULL 건수 계산. 0이 아니면 FAIL. [신규] v42 KRW FX marker PHASE2 예
N14     정상 주입행 표면   정상 보강/주입행은 본 생성행과 동일 스키마·결측률 표면을 가져야 한다. 정상 주입행만 is_synthetic/is_mutated/ledger/line_number/user_persona가 비거나 다르게 채워진다. 주입행 식별 기준(예: 확장계정 twin/normal control provenance)과 본 생성행을 나눠 컬럼별 missing rate 차이를 계산. 차이 >1%p면 FAIL, 식별 기준이 없으면 BLOCKED. [신규] v42 normal injection NULL marker PHASE2 예
N15     통제 플래그 정합   정상 baseline의 드문 자기승인 행은 sod_violation 플래그와 정합되어야 하며 true 비율은 극소여야 한다. created_by=approved_by인데 sod_violation=false이거나 true 비율이 0.1%를 초과한다. `audit_masterdata.py <dataset>`로 자기승인 행의 sod flag mismatch와 전체 true rate 계산. mismatch 0, true rate <0.1%가 아니면 FAIL. [신규] v42 SoD flag consistency L1-06 예
N16     cost center master 정합   journal cost_center는 master cost center 체계에 100% 존재해야 한다. 직원 master는 CC-C00X-DEPT 체계인데 journal은 CC1000 체계를 사용해 전부 고아가 된다. `audit_masterdata.py <dataset>`로 journal cost_center unique/value rows의 master 존재율 계산. 100% 미만이면 FAIL. [신규] v42 cost center master integrity PHASE2 예
N17     연도 drift       multi-year normal baseline은 거래량·계정 사용이 연도별로 완전 복제되면 안 된다. 2022/2023/2024 문서수 편차가 1.2%이고 계정 집합이 완전 동일하다. `audit_temporal.py <dataset>`로 연도별 문서수 편차와 GL 계정 집합 차이를 계산. 문서수 편차 <3% 또는 연도별 계정 집합 완전 동일이면 FAIL. [신규] v42 yearly clone marker D01, D02, PHASE2 예
N18     timestamp 분산   정상 journal timestamp는 초 단위에 비현실적으로 대량 몰리면 안 된다. 동일 timestamp에 50행 이상 또는 수백 행이 몰려 생성기 batch marker가 된다. `audit_temporal.py <dataset>`로 동일 posting timestamp 최대 중복 수 계산. max duplicate >=50이면 FAIL. [신규] v42 timestamp marker L3-06, L4-05, PHASE2 예
N19     trading partner master 정합   journal의 V-* trading_partner는 vendors.json에 등록되어야 한다. V-* 28개가 master에 없어 2,202행 orphan이 된다. `audit_masterdata.py <dataset>`로 V-* orphan trading_partner row/value count 계산. 0이 아니면 FAIL. [신규] v42 vendor orphan F06/K05 예
N20     optional timing distribution   월말·심야·posting lag 분포는 정상 회사 운영상 설명 가능한 범위여야 한다. 월말/심야/lag가 generator artifact처럼 대칭 또는 과도 집중된다. `audit_temporal.py <dataset>`의 월말 집중, 시간대, lag 분포를 MONITOR로 보고하고 v42에서 반영하지 못하면 사유를 debugging에 남긴다. [신규] v42 temporal realism optional PHASE2 부분
```

## O. Normal-only 오염 방지

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                             측정 방법(전수 계산 가능하게)                                          출처(rule/standard/web/design)                            연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  ----------------------------------------------------  ------------------------------------------------------------------------  ---------------------------------------------------------  --------------------  --------
O01     Normal-only 오염  normal-only row에는 fraud/anomaly/mutation/truth provenance가 섞이지 않는다. is_fraud=false row에 fraud_type, anomaly_type, mutation_type, answer token이 남아 있다. is_fraud/is_anomaly=false, fraud_type/anomaly_type/mutation_* 공란, truth sidecar 미연결 또는 normal-only 명시, scenario/answer token 누출 여부 계산. [신규] leakage guard, DataSynth anti-fitting           PHASE2, reports       예
O02     Normal-only 오염  fraud label이 없어도 합성 생성기 지문이 단일 컬럼 값으로 과도하게 드러나지 않는다. 특정 reference prefix, timestamp second, amount bucket, user 값이 특정 scenario/source/archetype을 거의 완벽히 분리한다. all-column value concentration scan으로 value_count >= N, single scenario/source/archetype purity, top value share, unique marker ratio 계산. document_type, business_process처럼 domain-determined enum purity는 단독 FAIL 근거에서 제외하고, reference suffix, exact timestamp, exact amount, free-text token, user/source cluster처럼 생성기 임의성이 큰 값에 purity scan을 적용한다. [신규] synthetic marker scan, anti-fitting             PHASE2                예
```

## P. 전문가·LLM 샘플 진단

이 카테고리는 전수 deterministic 검사의 대체물이 아니다.
LLM 또는 전문가 샘플 리뷰 결과는 pass/fail 최종 근거가 아니라 전수 규칙 누락을 찾는 diagnostic 신호로만 쓴다.

```text
검사ID  카테고리          정상 기대(무엇이 정상인가)                                           위반 예시                                             측정 방법(전수 계산 가능하게)                                          출처(rule/standard/web/design)                            연결된 phase1 룰        전수 적용
------  ----------------  ---------------------------------------------------------------------  ----------------------------------------------------  ------------------------------------------------------------------------  ---------------------------------------------------------  --------------------  --------
P01     전문가·LLM 진단   scenario/process/document_type/source별 샘플이 회계·ERP 관점에서 자연스럽다. 규칙 위반은 없지만 회사 전표처럼 보이지 않는 조합이 반복된다. fixed seed와 strata별 sample size로 scenario/process/document_type/source별 stratified sample n건을 추출하고 document_id를 저장한다. 차대변 의미, 거래처, 적요, 승인 흐름, 금액 크기, 문서유형을 자연어 rubric으로 판정하되 output schema는 plausible/questionable/impossible/rule_gap_candidate로 고정한다. [신규] expert/LLM diagnostic review                  L3-01, L4-04, PHASE2  부분
```

## 검사 성격 태그

검증기는 항목별 검사 성격을 분리해서 처리한다.

- `hard`: 위반 수가 0이어야 하는 구조·마스터·회계 불변 조건이다. 허용오차가 필요한 경우에도 기준은 명시 금액 또는 설정값이다.
- `distribution`: 정상 범위, 분포 거리, 집중도, 변동성으로 판정하는 현실성 조건이다.
- `diagnostic`: pass/fail 또는 범위 판정 자체보다 failure source attribution과 provenance 분해 가능성을 검증하는 항목이다.
- `limit-note`: synthetic 전수 계산은 가능하지만 정상 범위 확정에는 실데이터 또는 명시된 생성기 경제 가정이 필요하다.

태그는 구현 시 복수 적용할 수 있다.
예를 들어 E11은 승인 존재 여부에 대한 hard 조건과 source별 승인 분포에 대한 distribution 조건을 함께 가진다.

```text
태그           검사ID
-------------  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
hard           A01, A02, A04, A05, A07, B01, B02, B03, B04, B05, B06, B08, B09, B10, B11, B12, B15, B16, B17, D01, D02, E01, E02, E04, E05, E06, E07, E11, E12, F01, F02, F03, F04, F05, F06, F07, F08, G01, H01, H02, H03, H04, H06, I01, I02, I03, I04, I05, J04, J08, J09, K01, K02, K03, K04, K05, L01, L02, L03, L04, L05, M01, M02, M03, M04, M05, M06, M07, M08, M09, M10, N11, N12, N13, N14, N15, N16, N17, N18, N19, O01
distribution   A03, A06, B07, B13, B14, B17, C01, C02, C03, C04, C05, C06, C07, C08, C09, C10, D03, D04, D05, D06, D07, D08, D09, D10, E03, E08, E09, E10, E11, E12, G02, G03, G04, G05, G06, G07, G09, H05, J01, J02, J03, J05, J06, J07, J08, J09, K06, K07, N07, N08, N09, N10, N17, N18, N20
diagnostic     G08, N20, O02, P01
limit-note     N01, N02, N03, N04, N05, N06
```

## 필드 존재성 원칙

각 검사 항목은 구현 시 required fields 목록을 가진다.
필수 필드가 없으면 검증기는 PASS로 처리하지 않고 `BLOCKED` 또는 해당 항목 정의에 따른 `FAIL`로 처리한다.
예를 들어 J08은 `batch_id`, `job_id`, `batch_type`, `source`가 없으면 대형 전표 설명 가능성을 입증할 수 없고, G08은 `noise_flag` 또는 `quality_issue_id`가 없으면 source attribution이 불가능하다.
Gate, verdict, required fields matrix 운영 기준은 [normal-data-realism-verifier-design.md](./normal-data-realism-verifier-design.md)를 따른다.

## 정상 범위 임계 출처 원칙

분포형 항목의 정상 범위는 detector 통과율, recall, precision, VAE score, dashboard hit count를 맞추기 위해 역산하지 않는다.
임계값과 허용 범위는 아래 출처 순서로 정한다.

```text
우선순위  출처                         사용 원칙
--------  ---------------------------  ------------------------------------------------------------
1         회계·ERP hard rule            회계등식, roll-forward, master existence처럼 위반 0 조건
2         회사/시나리오 생성기 계약     산업, 회사 규모, fiscal calendar, batch schedule, approval matrix
3         감사·회계·세무 기준           ISA/PCAOB/K-IFRS/세법/SAP 문서에서 직접 도출되는 조건
4         외부 벤치마크·웹 리서치       Benford 적용 조건, 적격증빙 기준, 근무시간·결산 실무
5         실데이터 calibration          운영 성능 주장 없이 정상 범위 추정에만 사용
금지      detector 결과 역산             룰 hit count, VAE anomaly score, recall/precision 목표에 맞춘 조정
```

## 요약

```text
구분                    항목 수
----------------------  -------
총 검사 항목            129
A. 복식부기 정합        7
B. 분개 의미·계정조합   17
C. 분포·통계 현실성     10
D. 시간 패턴 현실성     10
E. 권한·통제 현실성     12
F. 마스터 참조 무결성   8
G. 자연 noise           9
H. 텍스트·적요 현실성   6
I. 전표 구조·번호·참조  5
J. 반복·중복·역분개     9
K. 관계사·내부거래      7
L. 증빙·세무            5
M. 재무제표·잔액 정합   10
N. 경제적 타당성        11
O. Normal-only 오염     2
P. 전문가·LLM 진단      1
```

```text
기존 설계와의 관계   항목 수   해석
-------------------  -------  ------------------------------------------------------------
[기존]               49       기존 realism-rebuild 설계 또는 PHASE1 룰/코드에 이미 명시된 항목
[기존+신규]          22       기존 항목을 정상 GL 현실성 측정 기준으로 확장한 항목
[신규]               52       이번 발굴에서 추가한 rule 역산·standard·web·domain 기반 항목
```

## 후속 리뷰 포인트

- P3-1 검증기 구현 전 각 항목의 required fields를 [normal-data-realism-verifier-design.md](./normal-data-realism-verifier-design.md)의 matrix로 분해해야 한다.
- `부분` 항목은 source document, receipt, batch_id, reversal_id, open item, IC reciprocal id 같은 추가 메타데이터가 있어야 완전 전수 검사가 가능하다.
- 정상성 기준은 detector hit count 목표가 아니라 회계·ERP·감사 도메인 현실로만 보정해야 한다. 상세 임계 출처는 `정상 범위 임계 출처 원칙`을 따른다.
