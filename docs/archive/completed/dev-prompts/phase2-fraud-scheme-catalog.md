# PHASE2 현실 부정 Scheme 카탈로그 (v1, 2026-06-10)

PHASE2 DataSynth 주입 설계의 SoT. 현실에서 실제 발생한 분식회계·횡령 수법을 scheme 단위로 정리하고,
각 scheme이 여러 문서·계정·기간에 **조정된 형태(woven)** 로 어떻게 주입되어야 하는지 정의한다.

## 0. 설계 원칙 (anti-fitting)

- 본 카탈로그는 **탐지 룰 정의를 입력으로 사용하지 않았다.** 룰에서 부정을 역설계하면
  "룰 사각을 노린 인공 부정"이 되어 측정이 순환·오염되기 때문이다.
- 따라서 본 문서에는 **룰별 탐지/미탐 매핑이 없다.** 어떤 scheme이 탐지되는지는 데이터 생성 후
  탐지기를 돌려 **사후 관찰**하는 측정 대상이지 설계 입력이 아니다.
- 모든 scheme은 "회계적으로·실무적으로 실제 일어난 분식/횡령"에서 출발하며, 출처를 명시한다.
  확인되지 않은 내용은 (불확실) 로 표기한다.
- 단발 fixture와 구분: 본 카탈로그의 scheme은 전부 **다문서·다계정·다기간 묶음**이다.

### 입력 근거

| 구분        | 근거                                                                              |
|-------------|-----------------------------------------------------------------------------------|
| 외부 실제 사례 | 모뉴엘, 대우조선해양, 오스템임플란트, 계양전기, SK글로벌, 부산저축은행, 제약·바이오 테마감리 등 (각 scheme에 출처) |
| 금감원 실증    | DETECTION_REFERENCE.md §3 — FSS 감리지적사례 189건 본문 분석 (전표 관련 94건, 6대 패턴 분포) |
| 기준서 원문    | ISA 240 A45 부정분개 식별 특성 (a)~(e), ISA 550 §23 특수관계자 거래의 사업상 합리성, ISA 520 §5 기대값-차이 분석 |
| 데이터 형식    | 정상 데이터 v29 (`datasynth_semantic_v1_normal_20260607_v29`) 의 스키마·계정·문서흐름 — "어디에 심을 수 있나"의 형식만 사용 |

### 금감원 감리지적 189건 전표 조작 패턴 분포 (prevalence 가중의 1차 근거)

```
패턴            건수   94건 대비   본 카탈로그 대응 scheme
─────────────────────────────────────────────────────────
가공 전표        50     53%       FS01, FS06, FS07 (+FS04 일부)
결산 수정        27     29%       FS02, FS08, FS10, FS13
횡령 은폐        24     26%       FS03, FS04, FS14
순환거래         10     11%       FS05, FS11
승인/SoD 위반     5      5%       FS03·FS04의 전제 조건 (독립 scheme 아님)
비정상 시점       4      4%       FS09
─────────────────────────────────────────────────────────
```

> 출처: DETECTION_REFERENCE.md §3.3. "횡령 은폐"는 제목 기준 6건이었으나 본문 분석 결과 24건 —
> 선급금/대여금/유형자산 "허위계상"의 상당수가 횡령 은폐 목적이었다 (§3.3 핵심 발견).
> K-IFRS 시행 후 2011~2023년 지적사례 155건 중 매출·매출원가 비중 25%로 최다
> ([비즈니스포스트](https://www.businesspost.co.kr/BP?command=article_view&num=352968)).

### ISA 240 A45 — 부정한 분개의 식별 특성 (한국 감사기준서 원문)

> 부적절한 분개기입 또는 기타 수정사항은 고유한 식별 특성을 가지는 경우가 많다.
> (a) 관련 없는, 비경상적이거나 거의 사용되지 않는 계정에 대한 기입
> (b) 통상적으로 분개기입을 하지 않는 개인에 의한 기입
> (c) 보고기간 말 또는 마감후 수정분개로 기록되며 설명이 거의 없거나 전혀 없는 기입
> (d) 재무제표 작성 전이나 작성 중에 기록되며 계정번호가 없는 기입
> (e) 단수(round number) 또는 일관된 끝자리 숫자를 포함하는 기입

이 특성들은 "현실 부정이 데이터에 어떤 흔적을 남기는가"의 기준서 차원 근거다. 단, 주입 시 이 특성을
**일부러 모두 충족시키지도, 일부러 모두 지우지도 않는다** — scheme의 회계 메커니즘이 자연스럽게
만들어내는 만큼만 나타나야 한다 (§0 anti-fitting).

---

## 1. 공통 라벨 스키마

v29 journal_entries 스키마에 이미 존재하는 truth 컬럼(`is_fraud`, `fraud_type`, `is_anomaly`)과
정합하게, scheme 구성 문서에는 아래 라벨을 부여한다. 라벨은 truth/sidecar 전용이며
**모델 입력 피처로 사용 금지** (기존 프로젝트 규약과 동일).

```
scheme_id          : FS01 ~ FS14
scheme_instance_id : {scheme_id}-{company_code}-{연도}-{seq}   예: FS01-C001-2023-01
component_role     : scheme별 enum — 묶음 내 이 문서의 역할 (각 scheme (d) 참조)
is_fraud           : true  (scheme 구성 문서 전체)
fraud_type         : scheme별 대표 유형 (각 scheme (d) 참조)
severity           : high | medium | low — 재무제표 영향 금액·은폐 정교성 기준
```

원칙:
- 한 scheme instance 의 모든 구성 문서는 같은 `scheme_instance_id` 를 공유한다.
  ML/평가의 truth 단위는 문서 단위가 아니라 **scheme instance 단위**까지 집계 가능해야 한다.
- 정교한 scheme일수록 구성 문서 일부는 표면상 완전히 정상이다(예: 가공매출의 대금 일부 회수 위장).
  그래도 scheme 구성요소이므로 `is_fraud=true` + `component_role` 로 추적한다.
- r23 교훈 적용: woven 주입은 **실제 P2P/O2C/IC flow 파일 멤버십**으로 구현한다.
  가짜 sidecar flow 파일 생성 금지 — 진짜 `document_flows/`·`relationships/`·`intercompany/` 에 들어가야 한다.

## 2. v29 주입 표면 (형식 참고)

```
표면                     파일                                          주입 관련 필드
────────────────────────────────────────────────────────────────────────────────────────────
분개(GL)                 journal_entries.csv                          gl_account, debit/credit, posting_date,
                                                                      document_date, created_by, approved_by,
                                                                      reference, reversal_document_id, trading_partner
P2P 흐름                 document_flows/{purchase_orders,goods_       PO→GR→송장→지급 체인, quantity_received,
                         receipts,vendor_invoices,payments}.json      is_fully_invoiced, vendor_id
O2C 흐름                 document_flows/{sales_orders,deliveries,     SO→납품→청구 체인, quantity_delivered,
                         customer_invoices}.json                      credit_status, customer_id
IC                       intercompany/{ic_matched_pairs,ic_seller_    seller/buyer 양측 분개, amount, settlement_status
                         journal_entries,ic_buyer_journal_entries}
보조원장                  subledger/{ar_invoices,ap_invoices,          AR aging, 인보이스-분개 대사
                         inventory_positions,fa_records}.json
마스터                    master_data/{vendors,customers,              bank_accounts, address, tax_id, approval_limit,
                         employees}.json                              직원 bank_account (횡령 수취계좌 대조용)
결산/보고                 period_close/trial_balances.json,            기말 잔액, 은행 대사
                         financial_reporting/bank_reconciliations.json
프로세스 링크             relationships/cross_process_links.json       재고 이동 등 프로세스 간 연결
────────────────────────────────────────────────────────────────────────────────────────────
주요 계정(요약): 매출 4000/4100/400000번대, AR 1100/100120~, 재고 1200/100280~, 선급 100400~,
유형자산 1500/100480~, AP 2000/200000번대, 선수수익 2300/200500~, 대손상각비 6900,
suspense 9000/199000, IC 채권·채무 115001~/205001~, IC 매출 4500.
```

### 2.1 COA 확장 요구 계정 (확장 작업은 별도 진행 — 본 카탈로그는 확장 완료를 전제)

v29 COA에 없는 아래 계정을 추가한다. **전제 조건: 신규 계정은 정상 데이터에서도 일상 거래로
사용되어야 한다.** 부정 scheme 에서만 쓰이는 계정이면 계정 번호 자체가 shortcut 이 된다 (§5-3).

```
필요 계정 (sub_type 제안)                         사용 scheme        정상 쌍둥이 사용처(필수)
──────────────────────────────────────────────────────────────────────────────────────────
무형자산-개발비 (asset/intangible_assets)          FS08              적법 자본화(소프트웨어·라이선스)
무형자산상각비 (expense/amortization_expense)      FS08              정상 무형자산 상각
건설중자산 CIP (asset/construction_in_progress)    FS04, FS08        정상 설비 투자 진행분
계약자산·미청구공사 (asset/contract_assets)         FS02              정상 진행기준 용역(청구 전 수익)
계약부채·초과청구 (liability/contract_liabilities)  FS02, FS09        정상 선수 청구
재공품 WIP (asset/inventory_wip)                  FS02, FS07        정상 생산 재공
단기대여금 (asset/loans_receivable)                FS04, FS11        정상 임직원·관계사 대여
가지급금 (asset/employee_advances)                FS03, FS04        정상 출장비 가지급·정산
단기금융상품 (asset/short_term_investments)        FS03              정상 여유자금 운용
대손충당금 — AR contra
  (asset/allowance_for_doubtful_accounts)         FS10              정상 기말 충당금 설정·환입
대손충당금환입 (revenue/allowance_reversal
  또는 6900 차감)                                  FS10              정상 회수 시 환입
충당부채 (liability/provisions)                    FS12              정상 보증·소송 충당 설정·환입
투자자산 (asset/investments)                       FS13              정상 취득·처분
손상차손 (expense/impairment_loss)                 FS13, FS08        정상 자산 손상 인식
──────────────────────────────────────────────────────────────────────────────────────────
```

(잔여 한계) FS02의 공사계약·진행률 **개체 구조**(계약 마스터, 진행률 측정)는 COA가 아니라
document_flows 차원의 확장이므로 별도 — 계정만으로는 분개·잔액 표현까지 가능하다.

---

## 3. Scheme 카탈로그

### 목록

```
ID    scheme                                     실제 근거(대표)            기본 fraud_type
──────────────────────────────────────────────────────────────────────────────────────────
FS01  가공매출·허위 수출채권 돌려막기              모뉴엘                    fictitious_revenue
FS02  진행기준 수익 조작 (원가 축소·미청구 누적)    대우조선해양               percentage_completion_manipulation
FS03  자금 횡령 — 이체·잔액증명 위조·장부 맞추기    오스템임플란트, 계양전기    embezzlement_cash
FS04  횡령 은폐 — 선급금·가공자산 둔갑             금감원 24건 패턴           embezzlement_concealment
FS05  순환거래 (A→B→C→A 가공매출 순환)            금감원 10건 패턴           circular_trading
FS06  부채 누락·가공 외화채권                     SK글로벌                  liability_omission
FS07  재고자산 과대계상 (실재성 조작)              금감원 허위보관 사례        inventory_overstatement
FS08  비용 부당 자본화·이연                       제약바이오 테마감리         improper_capitalization
FS09  기말 cutoff 조작 — 조기인식+익기 역분개      금감원 비정상시점 패턴      cutoff_manipulation
FS10  대손 회피 — 부실채권 정상 위장               부산저축은행              bad_debt_avoidance
FS11  특수관계자 부당지원·IC 불균형 거래           ISA 550 §23, 금감원 중점심사  related_party_abuse
FS12  우발부채·충당부채 미인식                    금감원 전표무관 영역, ISA 240 §32(b)  provision_omission
FS13  금융자산 손상 미인식 (투자자산 과대)          SK글로벌 (2,501억)         impairment_avoidance
FS14  유령직원·급여 횡령                          ACFE 자산유용 유형         payroll_ghost_employee
──────────────────────────────────────────────────────────────────────────────────────────
```

### 커버리지 매트릭스 — 검사 대상 부정 유형 전수 확인

본 데이터는 **검증용 합성물**이므로, 전표 테스트가 검사해야 하는 부정 유형이 빠짐없이
들어가야 한다. 요구 유형 → scheme 매핑 (미커버 0건):

```
검사 대상 부정 유형              커버 scheme           비고
─────────────────────────────────────────────────────────────────────────
가공매출                       FS01, FS05
매출 조기인식 (cutoff)          FS09
매출 과대인식                   FS01, FS02
비용 이연·부당 자본화            FS08, FS02
재고자산 과대계상               FS07
매출채권 과대계상               FS01, FS06, FS10
특수관계자 부당지원              FS11, FS04
순환거래                       FS05, FS11
자금 횡령·유용 은닉              FS03, FS04, FS14
대손 회피                      FS10
부채 누락                      FS06
우발부채·충당부채 미인식         FS12                  low-trace stratum (아래)
금융자산 손상 미인식             FS13
─────────────────────────────────────────────────────────────────────────
금감원 6대 전표조작 패턴          6/6 — 가공(FS01·06·07), 결산수정(FS02·08·10·13),
                               횡령은폐(FS03·04·14), 순환(FS05·11),
                               SoD위반(FS03·04의 구성요소), 비정상시점(FS09)
─────────────────────────────────────────────────────────────────────────
```

**low-trace stratum**: FS12 전체와 FS10·FS13의 부작위 구성요소는 전표 흔적이 본질적으로
희박하다(분개를 "안 하는" 부정). 이들은 평가 시 별도 stratum 으로 분리해 측정한다 —
미탐이 모델 결함인지 정보 부재(데이터 원리적 한계)인지 구분하기 위함이며, 탐지율 목표를
일반 scheme 과 합산하지 않는다.

---

### FS01. 가공매출·허위 수출채권 돌려막기 (모뉴엘형)

**(a) 실제 사례/근거**
모뉴엘(2014 적발): 페이퍼컴퍼니를 이용한 가공 해외매출 누적 약 2조 7,397억 원(전체 매출의 약 90%).
가공 수출채권을 은행에 할인 매각해 자금을 조달하고, 만기가 돌아오면 다시 허위 매출을 만들어
돌려막기. 해외 유통사 관계자와 짜고 그 회사가 대출은행에 직접 상환하는 모양을 만들어 신뢰도를
위장. 7년간 사기대출 약 3조 4,000억 원.
출처: [사이다경제](https://cidermics.com/contents/detail/1010),
[리걸타임즈](https://www.legaltimes.co.kr/news/articleView.html?idxno=89660),
[KCI 모뉴엘 회계부정 사례연구](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002005240).
금감원 189건 중 "가공 전표" 50건(53%)의 대표 형태 (DETECTION_REFERENCE.md §3.3).

**(b) 회계 메커니즘**
- 매출 인식: 차) AR / 대) 매출 — 실물 납품 없음. 증빙(주문서·선적서류·세금계산서) 위조.
- AR은 회수되지 않으므로 누적·노후화. 이를 감추려고 ① 신규 가공매출 대금으로 구 채권을 회수한
  것처럼 입금 처리(돌려막기), ② 채권 할인(차입)으로 현금화: 차) 현금 / 대) 단기차입금.
- 손익: 매출 과대 + (재고를 출고 처리하면) 원가도 일부 계상 — 매출총이익률이 비정상으로 높아지는
  것을 피하려고 실제 사례들은 원가율을 그럴듯하게 유지한다.

**(c) 다문서/다계정/다기간 조정**
1. 가공 SO → 가공 납품(DLV) → 가공 customer_invoice → 매출 분개 (O2C 전 체인 위조)
2. AR 누적: 일부 인보이스는 미회수로 방치 (aging 증가)
3. 돌려막기 입금: 신규 가공매출 직후 구 인보이스에 입금 분개 (차. 현금 / 대. AR)
4. 채권 할인 차입: 차) 현금 / 대) 단기차입금 (200300번대) — 분기 단위 반복
5. 기말 cutoff: 분기말·연말에 가공매출 집중 (실적 목표 마감)
6. (적발 회피 행태) 익기 초 일부 가공매출 반품/역분개 처리 — 실제 부정 기업이 감사 대응으로
   수행한 행태이며, 데이터에는 reversal_document_id 체인으로 나타난다

**(d) woven 주입 시그니처**
- 가공 고객 2~4개를 customers.json에 정상 형식으로 등록 (해외 국가, 정상 명명 규칙).
  같은 가공 고객에게 다수 인보이스가 수년간 반복.
- O2C flow 파일에 실제 멤버십으로 삽입 (SO·DLV·INV 모두 생성, journal_entry_id 연결).
- 금액: 정상 매출 분포 범위 내, 단 동일 고객 누적액이 매출 상위권으로 성장하는 시계열.
- 기간: 최소 2개 연도에 걸침 (누적·돌려막기 구조 표현).
- component_role: `fictitious_sale | fake_collection | receivable_discount_loan | next_period_reversal`
- fraud_type=`fictitious_revenue`, severity: 누적액 기준 high.

**(e) 정상과의 분리자 / anti-shortcut**
- 가공 고객의 마스터 필드(국가·은행·명명·tax_id 형식)는 정상 고객 풀과 동일 분포. `is_shell_company`
  같은 마스터 플래그를 truth와 상관시키지 않는다 (정상에도 false 균일 → 필드 자체가 신호 불가).
- 정상 데이터에도 분기말 매출 스파이크, 미회수 장기 AR, 반품/역분개가 존재해야 한다 (v29 확인:
  reversal 필드·credit_status 존재). 부정은 표면값이 아니라 **체인 구조(같은 고객 반복 + 회수율 +
  돌려막기 타이밍 상관)** 로만 분리 가능해야 한다.
- 가공 인보이스의 line_text·header_text는 정상 템플릿 풀에서 추출 (전용 문구 금지).

**(f) prevalence**
회사-연도당 0~1 instance. instance당 구성 문서 30~80건 (가공매출 15~40 + 회수위장 5~15 +
차입 4~8 + 역분개 2~5). 모뉴엘처럼 매출 90%가 가공인 극단은 비현실적 기본값 — 매출 대비
누적 1~5% 수준을 기본, 극단 시나리오는 별도 옵션.

---

### FS02. 진행기준 수익 조작 (대우조선해양형)

**(a) 실제 사례/근거**
대우조선해양(2015 적발): 2012~2014 회계연도에 해양플랜트·선박 사업의 **총예정원가를 축소**하거나
매출액·영업이익을 과다 계상하는 수법으로 약 5조 원대 분식. 2013년 당기순이익 약 1조 347억 원,
2014년 약 8,001억 원 과대계상. 금융위 과징금 45억 원, 감사인 안진회계법인 1년 업무정지.
출처: [한국경제](https://www.hankyung.com/article/202407258027i),
[법률신문](https://www.lawtimes.co.kr/news/200144),
[나무위키 — 대우조선해양 분식회계 사건](https://namu.wiki/w/%EB%8C%80%EC%9A%B0%EC%A1%B0%EC%84%A0%ED%95%B4%EC%96%91%20%EB%B6%84%EC%8B%9D%ED%9A%8C%EA%B3%84%20%EC%82%AC%EA%B1%B4).
KAI(2017)도 진행매출 과대·미청구공사 회수가능성 의혹으로 수사
([나무위키 — 한국항공우주산업](https://namu.wiki/w/%ED%95%9C%EA%B5%AD%ED%95%AD%EA%B3%B5%EC%9A%B0%EC%A3%BC%EC%82%B0%EC%97%85)).
금감원 §3.3: 2016~2017년 "공사진행률 조작" 사례 급증 — 조선·건설업 구조조정기와 일치.

**(b) 회계 메커니즘**
- 진행률 = 누적발생원가 ÷ 총예정원가. **분모(총예정원가)를 줄이면** 진행률·누적수익이 커진다.
- 분개: 차) 미청구공사(미청구 AR) / 대) 진행매출. 고객 청구 없이 수익만 먼저 쌓인다.
- 발생원가 이연: 당기 원가를 선급·재공으로 미루면 진행률 왜곡 + 당기 손익 개선 이중 효과.
- 결국 미청구공사 잔액이 비정상 누적 → 후속 연도에 대규모 손실(빅배스)로 터진다.

**(c) 다문서/다계정/다기간 조정**
1. 분기말마다 진행매출 수정분개 (차. 미청구 AR / 대. 용역매출) — 설명 빈약한 결산 수정 형태
2. 원가 이연 분개 (차. 선급비용/재공 / 대. 원가) — 같은 분기말에 짝으로 발생
3. 미청구 AR은 청구 전환 없이 다년 누적 (subledger aging)
4. 차기 이후 일부를 손실 전환 (대손 또는 매출 차감) — 다년 시계열의 끝
5. 외주비 PO·송장 입력 지연/분할 (P2P 측 원가 인식 지연)

**(d) woven 주입 시그니처**
- 계정: 계약자산·미청구공사(차변 누적) ↔ 용역매출(4100/400320~), 원가 이연은 재공품 WIP·
  선급비용, 후속 손실은 대손충당금 또는 매출 차감 (§2.1 확장 COA 전제).
- 분기말·연말 GL 수정분개 (business_process=GL, 결산 persona) + P2P 원가 이연 짝.
- (잔여 한계) 공사계약 개체·진행률 마스터는 document_flows 차원 확장 필요 — 계정·분개·잔액
  수준 표현은 확장 COA로 충분.
- component_role: `unbilled_revenue_booking | cost_deferral | delayed_vendor_invoice | subsequent_loss_recognition`
- fraud_type=`percentage_completion_manipulation`, severity high (금액 대형).

**(e) anti-shortcut**
- 정상에도 분기말 결산 수정분개·발생액(accrual) 분개가 충분히 존재해야 한다 (v29 GL lane).
- 정상 용역매출에도 청구 전 수익(선수수익 2300 반대 방향) 패턴 존재 — 부정은 "수정분개+이연원가
  짝 + 미청구 누적 + 후속 손실"의 **다기간 묶음**으로만 구분.
- 금액 round number 강제 금지 — 진행률 계산 결과처럼 비정형 끝자리.

**(f) prevalence**
회사-연도당 0~1 instance (조선·건설·수주산업 성격 회사에만). instance당 분기 4회 × (수정분개
2~4건 + 이연 1~3건) × 2~3개 연도 = 25~80건. 손실 전환은 마지막 연도 1~5건.

---

### FS03. 자금 횡령 — 이체·잔액증명 위조·장부 맞추기 (오스템임플란트·계양전기형)

**(a) 실제 사례/근거**
오스템임플란트(2022 적발): 재무팀장이 2020.11~2021.10 동안 15차례에 걸쳐 회사 계좌에서 본인
증권계좌로 2,215억 원 이체. 징역 35년 확정.
출처: [법률신문](https://www.lawtimes.co.kr/news/197550),
[한국경제](https://www.hankyung.com/article/202404149544i).
계양전기(2022 적발): 재무팀 대리가 2016.4~2022.2 동안 195회에 걸쳐 약 246억 원 이체.
**은행 잔액증명서에 맞춰 재무제표·장부를 155회 조작**해 은폐. 징역 12년 확정.
출처: [경향신문](https://www.khan.co.kr/article/202209061047001),
[머니투데이](https://news.mt.co.kr/mtview.php?no=2023060815122188688).

**(b) 회계 메커니즘**
- 실제 출금: 차) ??? / 대) 현금(은행). 횡령자는 차변을 정상처럼 보이는 계정으로 위장 —
  단기금융상품, 다른 은행 계좌 간 이체(bank clearing), suspense, 가지급금 등.
- 은행 실잔액과 장부 잔액의 차이가 핵심 흔적. 이를 가리려 ① 잔액증명서 위조, ② 은행대사
  (bank reconciliation) 조정항목 조작, ③ 기말 직전 일시 반환 후 재인출.
- 승인 측면: 본인 입력·본인 처리(권한 집중), 또는 승인 한도 이하로 쪼개기.

**(c) 다문서/다계정/다기간 조정**
1. 인출 분개 다수 회: 차) bank_clearing(1030/9200)·단기금융상품·suspense(9000) / 대) 현금(1010)
   — 수년간 반복 (계양전기 195회)
2. 잔액 맞추기 분개: 기말마다 clearing → 다른 자산 계정으로 재분류 (장부-증명서 차이 은폐)
3. bank_reconciliations.json의 조정항목(미달예금·기발행미인출 등)에 허위 항목 추가
4. (선택) 기말 직전 일부 반환 입금 + 기초 재인출 — 잔액 시점 조작
5. 수취 계좌 흔적: 이체 상대가 employees.json의 직원 bank_account와 일치 (마스터 교차)

**(d) woven 주입 시그니처**
- GL lane (business_process=GL) 중심 + bank_reconciliations 표면 동시 조작.
- created_by는 재무 부서 실무자 1인 고정, 승인 필드는 자기승인 또는 한도 이하 분할.
- 금액: 초기 소액 → 점증 (실제 사례 공통 패턴). 끝자리 비정형.
- component_role: `cash_withdrawal | balance_patching | recon_item_fabrication | temporary_return`
- fraud_type=`embezzlement_cash`, severity: 누적액 기준 high (단건은 medium).

**(e) anti-shortcut**
- 정상에도 bank clearing·suspense 경유 분개, 계좌 간 이체, 은행대사 조정항목이 일상적으로 존재
  (v29 계정 1030/9000/9200 존재). 부정은 "동일 작성자 반복 + 잔액 패칭 주기성 + 직원 계좌 일치"
  구조로만 분리.
- 직원 마스터의 bank_account는 정상 직원 전원이 보유 — 필드 존재 자체는 신호 아님.

**(f) prevalence**
회사당 0~1 instance (다년). instance당 인출 20~60건 + 패칭 분개 8~24건(기말마다) + 대사 조작
4~12건. 전체 모집단 대비 0.05% 미만 문서 수.

---

### FS04. 횡령 은폐 — 선급금·대여금·가공자산 둔갑 (금감원 24건 패턴)

**(a) 실제 사례/근거**
금감원 감리지적 189건 분석 결과, 전표 관련 94건 중 **횡령 은폐 24건(26%)** — 선급금/대여금/
매출채권/유형자산 "허위계상"의 상당수가 실제로는 횡령액 은폐 목적 (DETECTION_REFERENCE.md §3.3,
본문 직접 분석). 부산저축은행도 허위 SPC 대출로 자금을 유출한 동형 구조
([KCI — 부산저축은행의 회계부정 사례](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001771759)).

**(b) 회계 메커니즘**
- FS03이 "현금 잔액을 직접 가린다"면 FS04는 **유출액을 자산으로 둔갑**시킨다:
  차) 선급금·대여금·선급공사비·유형자산(건설중) / 대) 현금.
- 상대처는 페이퍼컴퍼니·친인척 업체·실재하지만 공모한 거래처.
- 자산은 회수·정산되지 않으므로 장기 체류 → 기말마다 재분류(선급금→선급비용→다른 가지급)로
  aging을 리셋하거나, 소액씩 비용화해 서서히 소각.

**(c) 다문서/다계정/다기간 조정**
1. 가공 PO + (허위 검수) + 선급금 지급: 차) 선급(100400~) / 대) 현금 — P2P 외형
2. 후속 정산 없음: GR 미발생 또는 형식적 GR, vendor_invoice 미도래 상태 장기화
3. 기말 재분류 분개: 선급 ↔ 단기대여금 ↔ 가지급금 ↔ 건설중자산(CIP) — aging 리셋
4. 서서히 소각: 분기마다 소액 비용화 (차. OPEX / 대. 선급)
5. 가공 유형자산 변형: 차) FA(100480~) / 대) 현금 + fa_records 등재, 감가상각 개시 —
   상각비로 수년에 걸쳐 자연 소각되는 정교형

**(d) woven 주입 시그니처**
- P2P flow 멤버십 필수 (PO·지급 실재, GR/송장 체인만 비정상적으로 미완결).
- 공모 거래처 1~3개: vendors.json 정상 형식 등록, 다만 거래 이력이 이 scheme에 편중되는
  구조적 특성 (마스터 필드로는 정상).
- component_role: `advance_payment_out | aging_reset_reclass | gradual_expense_writeoff | fake_asset_capitalization`
- fraud_type=`embezzlement_concealment`, severity medium~high.

**(e) anti-shortcut**
- 정상에도 선급금 지급·장기 미정산 PO·재분류 분개가 존재해야 한다 (v29 P2P에 is_fully_invoiced
  false 상태 존재 확인). 부정은 "정산 부재 + 주기적 재분류 + 동일 거래처 편중"의 결합으로만 분리.
- 신규 계정(대여금·가지급금·CIP)은 정상 거래(임직원 대여·출장 가지급 정산·설비 투자)에서도
  일상 사용 — §2.1 정상 쌍둥이 전제.

**(f) prevalence**
회사-연도당 0~2 instance. instance당 10~30건 (지급 3~8 + 재분류 4~12 + 소각 3~10).
금감원 분포상 FS03보다 흔한 형태이므로 FS03보다 발생 가중 높게.

---

### FS05. 순환거래 — 특수관계자/페이퍼컴퍼니 A→B→C→A

**(a) 실제 사례/근거**
금감원 감리지적 94건 중 순환거래 10건(11%): 페이퍼컴퍼니·특수관계자 간 A→B→C→A 가공매출 순환
(DETECTION_REFERENCE.md §3.3). 전형 구조: 회사 A가 자회사 a와 계약을 반복 체결해 가공매출을
만들고 B·C·D 기업들과 유사 계약을 지속하다 부도
([나무위키 — 분식회계](https://namu.wiki/w/%EB%B6%84%EC%8B%9D%ED%9A%8C%EA%B3%84),
[비즈니스포스트](https://www.businesspost.co.kr/BP?command=article_view&num=352968)).

**(b) 회계 메커니즘**
- A가 B에 매출 → B가 C에 매출 → C가 A에 매출(또는 용역). 실물·용역 이동 없음. 각 사 매출이
  동시에 부풀고, 그룹 합산으로는 상쇄.
- 대금도 같은 돈이 돈다: A→C 지급 → C→B → B→A 입금. 회수율은 표면상 정상.
- 단가·마진이 거래마다 자의적 (실물 원가 없음), 기말 실적 마감 직전 집중.

**(c) 다문서/다계정/다기간 조정**
1. 3사 이상에서 동시 발생하는 O2C(매출 측) + P2P(매입 측) 전 체인 — 한 회사 안에서는
   "매출도 매입도 정상"으로 보인다
2. 결제 체인: payments가 짧은 간격으로 원환을 이룬다 (금액 거의 동일, 수수료성 차액)
3. 분기말 집중 + 매 분기 반복 (실적 평탄화)
4. IC 변형: 연결 대상 계열사 간이면 intercompany lane(115001~/205001~/4500)에 양측 분개 +
   ic_matched_pairs 생성 — 연결 제거 대상인데 별도 FS에서 잔존시키는 변형은 FS11로 분리

**(d) woven 주입 시그니처**
- v29 멀티컴퍼니(C001~C003) + 외부 공모처 1~2개로 원환 구성.
- 같은 material/용역 description이 원환을 따라 재등장하되 단가가 단계마다 상승 (마진 자의성).
- cross_process_links 에 재고 이동 없는 매출-매입 짝 (실물 부재의 구조적 흔적).
- component_role: `circular_sale_leg | circular_purchase_leg | circular_payment_leg | quarter_end_burst`
- fraud_type=`circular_trading`, severity high.

**(e) anti-shortcut**
- 정상에도 계열사 양방향 거래·짧은 결제 주기 거래가 존재 (v29 IC lane 실재). 부정은
  **닫힌 원환(cycle) + 금액 보존 + 시점 동기화**라는 그래프 구조로만 분리.
- 공모처 마스터는 정상 분포. 원환 구성 문서의 표면 필드는 전부 정상 범위.

**(f) prevalence**
멀티컴퍼니 그룹당 0~1 instance. instance당 분기 1~2회전 × 3~4 leg × (SO+DLV+INV+분개+지급)
≈ 연 40~100건. 금감원 11% 비중 반영해 FS01보다 낮은 빈도.

---

### FS06. 부채 누락·가공 외화채권 (SK글로벌형)

**(a) 실제 사례/근거**
SK글로벌(2003 적발): 은행 명의 **채무잔액증명서를 위조**해 외화외상매입금(유전스) 1조 1,881억 원을
없는 것처럼 처리. 가공 외화외상매출채권 1,498억 원, 부실자산 대손충당금 미계상 447억 원,
투자유가증권 과대계상 2,501억 원 등으로 이익잉여금 1조 5,587억 원 과대계상.
출처: [디지털타임스](http://www.dt.co.kr/contents.html?article_no=2003121802011866618004),
[제주일보](http://www.jejunews.com/news/articleView.html?idxno=21177).

**(b) 회계 메커니즘**
- 부채 누락: 실제 차입·매입채무를 장부에서 제거 — 기말에 차) AP/차입금 / 대) ??? 의 상대를
  가공 채권·suspense로 받거나, 아예 인보이스 자체를 미기록.
- 가공 외화 AR: 차) AR(외화) / 대) 매출 또는 기타수익 — 환율 필드가 얽혀 검증이 어렵다는 점 악용.
- 잔액증명·조회서 대응 위조가 본질이므로, 데이터에는 **보조원장-GL-은행대사 3면 불일치**가 남는다.

**(c) 다문서/다계정/다기간 조정**
1. 기말 직전 AP 제거 분개 (차. AP 200000번대 / 대. suspense·가공 AR) + 기초 원복 분개 —
   보고시점만 부채 축소
2. vendor_invoice는 존재하는데 대응 AP 잔액이 기말 TB에서 사라지는 대사 불일치
3. 가공 외화 AR: currency≠KRW, exchange_rate 정상 범위, 상대 고객은 해외 가공처
4. 다년 반복: 매 기말 같은 패턴, 규모 점증

**(d) woven 주입 시그니처**
- period_close/trial_balances + subledger/ap_invoices 와 journal_entries 간 의도적 불일치 생성
  (balance/subledger_reconciliation 표면에 잔존 차이).
- 기말 D-5~D0 에 제거 분개, 익기 D+1~D+10 에 원복 분개 (reversal 체인).
- component_role: `liability_removal | period_start_rebooking | fictitious_fx_receivable`
- fraud_type=`liability_omission`, severity high.

**(e) anti-shortcut**
- 정상에도 기말 재분류·미착/미달 조정·외화 AR이 존재. 부정은 "기말 제거↔기초 원복 대칭 +
  보조원장 불일치 잔존"의 묶음으로만 분리.
- suspense 경유 자체는 정상에도 흔함 (v29 suspense 계정 존재) — 경유 후 미해소 장기화가 구조적 차이.

**(f) prevalence**
회사-연도당 0~1 instance. instance당 8~20건 (제거·원복 짝 3~6쌍 + 가공 AR 2~8건).

---

### FS07. 재고자산 과대계상 — 실재성 조작

**(a) 실제 사례/근거**
금감원 적발사례: 상장사 A는 재고(고철) 장부수량과 실수량 불일치를 감추려 **종속회사로 재고를
이동·보관 중인 것처럼 위장** — 운송계약서·물품입고확인서를 위조. 운송비 원장에서 운송비 발생이
없음이 확인되어 적발.
출처: [비즈니스포스트](https://www.businesspost.co.kr/BP?command=print&idxno=81259),
[일요경제](http://www.ilyoeconomy.com/news/articleView.html?idxno=36824),
[한울회계법인 — 2018년도 주요 감리 지적 사례](https://www.crowe.com/kr/news/news20190828_kr).

**(b) 회계 메커니즘**
- 기말 재고 과대 → 매출원가 과소 → 이익 과대 (COGS = 기초 + 매입 − 기말).
- 수법: ① 출고된 재고를 미출고로 유지(원가 미인식), ② 멸실·진부화 재고 평가손 미인식,
  ③ 외부/관계사 보관 위장(실사 회피), ④ 기말 직전 허위 입고 + 기초 취소.
- 위장 보관은 **이동 서류는 있는데 부수 비용(운송비)·반대편 기록이 없다**는 불일치를 남긴다.

**(c) 다문서/다계정/다기간 조정**
1. 기말 직전 재고 증가 분개 (차. 재고 1200 / 대. COGS 또는 GR/IR) + 익기 초 반대 분개
2. inventory_positions.json 의 기말 수량·금액 과대 (분개와 정합하게)
3. 위장 이동: cross_process_links 에 이동 link 는 있으나 대응 운송비용 분개 부재 (관계사 보관형)
4. 출고 미인식: O2C delivery 는 발생했는데 COGS 분개 누락 — 납품-원가 짝 깨짐
5. 다년: 과대분이 누적되다 일시 평가손/폐기로 터짐 (후속 연도)

**(d) woven 주입 시그니처**
- 재고 계정(1200/100280~)·COGS(5000/500000번대)·GR/IR(2900/199100) 3각 + inventory_positions 표면.
- component_role: `period_end_inventory_inflation | cogs_suppression | fake_storage_transfer | subsequent_writeoff`
- fraud_type=`inventory_overstatement`, severity medium~high.

**(e) anti-shortcut**
- 정상에도 기말 재고 실사 조정·평가손·관계사 재고 이동이 존재해야 한다. 부정은 "조정 방향의
  일관성(항상 증가) + 부수 기록 부재 + 익기 반전"으로만 분리.
- 수량·단가는 materials.json 정상 범위 내.

**(f) prevalence**
제조·유통 성격 회사-연도당 0~1 instance. instance당 6~18건 + inventory_positions 레코드 조작
4~12건.

---

### FS08. 비용 부당 자본화·이연 (개발비 테마감리형)

**(a) 실제 사례/근거**
금감원 2018 제약·바이오 연구개발비 테마감리: 22개사 점검, 개발단계 자본화 6요건 미충족 비용의
무형자산 계상이 쟁점. 감독지침 발표로 자본화 가능 단계 기준 제시
([금융위 보도자료](https://www.fsc.go.kr/po010106/73325)).
테마감리 이후 제약·바이오 기업의 연구개발비 자본화율이 유의하게 하락 — 그만큼 과대 자본화가
존재했음을 시사
([KCI — 연구개발비 회계처리에 대한 테마감리의 효과](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002769859)).
금감원 §3.3 "결산 수정" 27건(29%)의 대표 하위 유형: 원가 이연, 개발비 과대 자산화.

**(b) 회계 메커니즘**
- 당기 비용(인건비·외주용역비·재료비)을 자산으로 둔갑: 차) 무형자산(개발비)·선급비용·건설중자산 /
  대) 비용(또는 비용 분개를 처음부터 자산 계정으로 기표).
- 자본화 후에는 상각으로 수년에 걸쳐 비용화 — 당기 이익 즉시 개선, 부담은 미래로 이전.
- 결산기에 소급 재분류(비용→자산) 수정분개가 전형 흔적.

**(c) 다문서/다계정/다기간 조정**
1. 연중: 정상 비용 분개로 들어온 인건비·외주비를 분기말 일괄 재분류 (차. 자산 / 대. 비용)
2. P2P 외주용역 송장의 계정 지정을 처음부터 자산으로 기표하는 변형
3. 자본화 자산의 상각 개시 (소액·장기) — fa_records 등재
4. 후속 연도: 회수가능성 상실 → 일시 손상 인식 (빅배스)

**(d) woven 주입 시그니처**
- 계정: 무형자산-개발비(자본화 차변), 무형자산상각비(소각), 건설중자산 CIP(설비 변형) —
  §2.1 확장 COA 전제.
- 분기말 재분류 GL 분개 + P2P 송장 계정 지정 + fa_records 3표면.
- component_role: `expense_reclass_to_asset | direct_asset_booking | amortization_stream | subsequent_impairment`
- fraud_type=`improper_capitalization`, severity medium.

**(e) anti-shortcut**
- 정상에도 적법한 자본화(설비·선급)와 분기말 재분류가 존재. 부정은 "재분류 빈도·방향 편향 +
  자본화 비율의 손익 목표 연동(이익이 부족한 분기에 집중)"으로만 분리.
- 계정·금액·작성자는 정상 결산 분개 풀과 동일 분포.

**(f) prevalence**
회사-연도당 0~1 instance. instance당 분기 2~4회 × 1~3건 + 상각 4~12건 ≈ 10~30건.

---

### FS09. 기말 cutoff 조작 — 매출 조기인식 + 익기 역분개

**(a) 실제 사례/근거**
금감원 §3.3 "비정상 시점" 4건: 연말 밀어내기, 납품 전 조기인식. ISA 240 A45(c) "보고기간 말 또는
마감후 수정분개로 기록되며 설명이 거의 없는 기입"이 기준서 차원 근거. K-IFRS 지적사례 155건 중
매출 관련 최다(25%) — 인식 시점 왜곡이 흔한 하위 유형
([비즈니스포스트](https://www.businesspost.co.kr/BP?command=article_view&num=352968)).

**(b) 회계 메커니즘**
- 차기 매출을 당기로 끌어오기: 납품 전 인보이스 발행/매출 분개 (document_date·delivery_date 와
  posting_date 의 역전), 또는 12월 말 대량 출하 후 1월 반품.
- 익기 초 반품·취소·역분개로 원상복구 — 연간 합계는 비슷하지만 **연도 경계의 배분**이 왜곡.

**(c) 다문서/다계정/다기간 조정**
1. 12월 마지막 주 매출 분개 폭증 (같은 고객·비슷한 단가)
2. 대응 delivery 의 실제 일자/수량은 1월 (O2C 체인 내 일자 역전)
3. 1월 반품/역분개 (4020 Sales Returns, reversal_document_id 체인)
4. 2개 연도 경계 필수 — 단년 데이터로는 표현 불가

**(d) woven 주입 시그니처**
- O2C 체인의 일자 필드 조정 (SO 정상 → INV 12월 → DLV 1월) + 1월 reversal.
- component_role: `pulled_forward_sale | post_period_delivery | next_period_return`
- fraud_type=`cutoff_manipulation`, severity low~medium (단독으로는 소형, FS01·FS02와 결합 가능).

**(e) anti-shortcut**
- 정상에도 연말 성수기 매출 증가·1월 정상 반품이 존재해야 한다. 부정은 "12월 매출-1월 반품의
  **고객·문서 단위 짝 맞음** + 납품일자 역전"으로만 분리. 단순 '연말 매출 많음'은 신호가 아니어야
  한다.

**(f) prevalence**
회사-연도 경계당 0~2 instance. instance당 8~25건 (매출 5~15 + 반품/역분개 3~10).

---

### FS10. 대손 회피 — 부실채권 정상 위장 (부산저축은행형)

**(a) 실제 사례/근거**
부산저축은행(2011): 부실화된 SPC 사업장 대출을 정상 대출로 위장하고 대손충당금을 적정 수준으로
반영하지 않아 BIS 비율을 과대 보고, 분식 기반으로 후순위채 발행. 수조 원대 분식으로 보도.
출처: [KCI — 부산저축은행의 회계부정 사례](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001771759),
[나무위키 — 부산저축은행](https://namu.wiki/w/%EB%B6%80%EC%82%B0%EC%A0%80%EC%B6%95%EC%9D%80%ED%96%89).
SK글로벌도 부실자산 대손충당금 447억 미계상 (FS06 출처와 동일).

**(b) 회계 메커니즘**
- 회수불능 채권에 대손상각비(6900)·충당금을 인식하지 않음 — "분개를 안 하는" 부작위형 분식.
- 부작위를 가리는 작위: ① aging 리셋 — 기존 채권 회수 위장 + 신규 채권 재계상 (차환),
  ② 이자/일부 회수 위장 입금 (자기 자금 순환), ③ 채권 재분류 (AR → other_assets).
- 결과: AR aging 이 실제보다 젊고, 회수율이 표면상 정상.

**(c) 다문서/다계정/다기간 조정**
1. 부실 고객군의 구 인보이스에 위장 입금 (차. 현금 / 대. AR) + 직후 동액 신규 인보이스 (차환 짝)
2. 위장 입금의 자금원이 회사 자신 또는 관계처 (FS05·FS11과 연결 가능)
3. 재분류 분개로 aging 통계에서 이탈
4. 다년 누적 후 일시 대손 인식 (후속 빅배스)
5. 대손상각비(6900)가 동종 규모 대비 비정상 과소 — "없는 것"이 신호인 부작위 흔적

**(d) woven 주입 시그니처**
- subledger/ar_invoices aging + journal_entries 입금·차환 짝 + customers 부실군.
- 계정: 대손충당금(AR contra) 설정 과소 + 부당 환입(충당금환입) — §2.1 확장 COA 전제.
  부작위형(설정 과소)에 더해 **기존 충당금을 환입해 이익을 만드는 작위형**도 표현 가능
  (금감원 §3.3 "충당금 환입" 실증 패턴).
- component_role: `fake_collection_refinance | receivable_reclass | suppressed_writeoff_population | subsequent_bigbath`
- fraud_type=`bad_debt_avoidance`, severity medium~high.

**(e) anti-shortcut**
- 정상에도 장기 미회수 AR·재분류·연체 후 회수가 존재. 부정은 "입금↔재계상 짝 + 자금원 순환 +
  상각 부재의 모집단 수준 편향"으로만 분리. 부작위형이므로 문서 단위 라벨은 차환·위장입금 등
  **작위 구성요소**에 부여하고, 부작위(미인식)는 scheme_instance 메타에 금액으로 기록.

**(f) prevalence**
회사-연도당 0~1 instance. 작위 문서 10~30건 + 부실 고객 3~8개 군. 부작위 금액은 instance 메타.

---

### FS11. 특수관계자 부당지원·IC 불균형 거래

**(a) 실제 사례/근거**
ISA 550 §23 원문: "정상적인 영업과정을 벗어나는 유의적 특수관계자 거래에 대해 … 그 거래가
**부정한 재무보고에 관여하거나 자산의 유용을 은폐**하기 위하여 이루어졌을 수 있음을 시사하는지
평가하여야 한다" (DETECTION_REFERENCE.md §2.5). 금감원 2024년 중점심사 4대 이슈 중 하나가
"특수관계자거래 회계처리" (같은 문서). 특수관계자 거래를 이용한 이익조정은 실증 연구로도 확인
([KISS — 특수관계자 거래와 발생액 및 실제이익조정](https://kiss.kstudy.com/Detail/Ar?key=3659997)).
부산저축은행 SPC 부당대출, 모뉴엘 페이퍼컴퍼니도 본질적으로 특수관계자 구조.

**(b) 회계 메커니즘**
- 이전가격 조작: 모회사가 부실 계열사에 고가 매입(지원) 또는 저가 매출 — 손익 이전.
- 일방향 자금 지원: 대여·선급 명목 송금, 회수 없음 (FS04와 연속선).
- IC 양측 비대칭: 한쪽만 기록(매출은 있는데 상대 매입 없음), 금액·시점 불일치, 미정산 잔액
  장기 누적 — 연결 제거 시 잔존 차이.

**(c) 다문서/다계정/다기간 조정**
1. IC 거래 양측 분개 (ic_seller/ic_buyer) 중 한쪽 금액 과대 또는 한쪽 누락 — ic_matched_pairs
   불일치
2. IC 채권(115001~)·채무(205001~) 잔액의 일방향 누적, settlement_status=open 장기화
3. 분기말 IC 용역매출(4500) 몰아넣기 — 부실 계열사 실적 보전
4. 모회사 측 지원 분개 + 계열사 측 수익 분개의 시점·금액 비대칭
5. 다년: 지원 누적 → 손상/대손 일시 인식

**(d) woven 주입 시그니처**
- v29 IC lane (C001~C003) 전용 — ic_matched_pairs에 의도적 mismatch/단측 레코드 삽입.
- 이전가격형은 동일 용역 description의 IC 단가가 외부 거래 대비 체계적 편차.
- component_role: `transfer_price_distortion | one_sided_ic_booking | unsettled_ic_accumulation | quarter_end_ic_burst`
- fraud_type=`related_party_abuse`, severity medium~high.

**(e) anti-shortcut**
- 정상 IC 거래(매칭 양측·정산 완료)가 충분히 존재하는 위에 주입 (v29 IC lane 실재).
  IC라는 사실 자체가 신호가 되면 안 된다 — 분리자는 **비대칭·미정산 누적·단가 편차**다.
- 정상에도 환율·시점 차이로 인한 소액 IC 차이가 존재해야 함 (완전 매칭만 정상이면 shortcut).

**(f) prevalence**
멀티컴퍼니 그룹-연도당 0~1 instance. instance당 12~40건 (IC 양측 분개 + pairs 레코드).

---

### FS12. 우발부채·충당부채 미인식 (low-trace stratum)

**(a) 실제 사례/근거**
금감원 189건 분석에서 "전표 무관" 95건(50%)의 주요 영역이 회계기준 해석 오류·추정치 판단 착오·
주석 공시 누락이다 (DETECTION_REFERENCE.md §3.2 방법론). 충당부채·우발부채 미인식은 이 추정·공시
영역의 대표 유형이며, ISA 240 §32(b) 원문 "회계추정치에 경영진의 편의(bias)가 개입되어 있는지를
검토한다"가 기준서 차원 근거 (DETECTION_REFERENCE.md §2.1).
(불확실) 개별 기업 확정 사례 인용은 보강 필요 — 소송충당부채·보증충당부채 미계상은 감리지적의
상시 유형이나 본 조사에서 특정 기업 1차 출처를 확보하지 못했다.

**(b) 회계 메커니즘**
- 인식해야 할 충당부채 설정 분개 — 차) 비용 / 대) 충당부채 — 를 **하지 않는** 부작위형 분식.
  대상: 소송 패소 가능성, 제품보증·반품 의무, 관계사 지급보증 부실화.
- 부채·비용 동시 과소 → 이익·자본 과대. 전표에는 "없는 분개"만 남는다.
- 단, 의무의 존재를 시사하는 **컨텍스트 거래는 정상 표면으로 존재**한다: 소송 수임료 반복 지급,
  보증수수료 수취/지급, 반품 증가 추세.

**(c) 다문서/다계정/다기간 조정**
1. 컨텍스트 분개 (정상 표면): 전문가수수료(6700) 반복 지급 — 동일 로펌, 분기 반복
2. 보증 컨텍스트: 관계사 보증수수료 수취 (other_income) + 해당 관계사의 IC 연체 누적 (FS11 연계 가능)
3. 충당부채 설정 분개 부재 — 동종 규모·동종 컨텍스트의 정상 회사는 기말마다 설정·환입
4. 후속 연도: 패소·대위변제 확정 시 일시 손실 인식 (차. 비용/손실 / 대. 현금·충당부채)

**(d) woven 주입 시그니처**
- 계정: 충당부채(liability/provisions, §2.1 확장) — 정상 쌍둥이로 정상 회사·정상 연도의
  기말 충당부채 설정·환입 분개가 반드시 존재해야 함.
- 라벨은 컨텍스트 작위 문서에 부여. **미인식 금액은 scheme instance 메타에 기록** (문서 라벨 불가).
- component_role: `litigation_context_fees | guarantee_fee_flow | subsequent_loss_recognition`
- fraud_type=`provision_omission`, severity medium (금액 기준 상향 가능).

**(e) 정상과의 분리자 / anti-shortcut**
- 소송 수임료·보증수수료는 정상에도 흔하다. 분리자는 "컨텍스트 강도 대비 충당부채 설정 부재"라는
  **모집단 수준 비교**뿐이며, 단일 분개로는 원리적으로 식별 불가.
- 따라서 본 scheme 은 탐지 목표가 아니라 **blind spot 측정용** — 평가 시 low-trace stratum 으로
  분리하고, 미탐을 모델 결함으로 집계하지 않는다.

**(f) prevalence**
회사-연도당 0~1 instance. 작위(컨텍스트) 문서 4~10건 + instance 메타 미인식 금액.

---

### FS13. 금융자산 손상 미인식 — 투자자산 과대계상 (SK글로벌형)

**(a) 실제 사례/근거**
SK글로벌(2003): 투자유가증권 과대계상 2,501억 원 — 부실 투자자산의 손상 미인식
([디지털타임스](http://www.dt.co.kr/contents.html?article_no=2003121802011866618004),
[제주일보](http://www.jejunews.com/news/articleView.html?idxno=21177)).
금감원 §3.3 "결산 수정" 27건의 명시 하위 유형: **손상 미인식, 충당금 환입**
(DETECTION_REFERENCE.md §3.3). 부실 계열사 지분을 원가로 유지하는 형태가 전형.

**(b) 회계 메커니즘**
- 피투자사(주로 관계사)가 부실화됐는데 손상차손 분개 — 차) 손상차손 / 대) 투자자산 — 를 하지 않음.
- 작위 변형: 근거 없는 평가이익 인식, 부실 직전 추가 출자(차. 투자자산 / 대. 현금)로
  지원과 과대계상을 동시 수행 (FS11 부당지원과 연속선).
- 후속 연도 일시 손상(빅배스)으로 종결되는 다년 구조.

**(c) 다문서/다계정/다기간 조정**
1. 취득·추가 출자 분개: 차) 투자자산 / 대) 현금 — 피투자사 부실 진행 중에도 반복
2. 부실 컨텍스트: 해당 관계사와의 IC 거래 축소·IC 채권 연체 (intercompany 표면, FS11 연계)
3. 기말 손상 분개 부재 — 정상 회사·정상 연도는 적정 손상 인식
4. (작위 변형) 평가이익 분개: 차) 투자자산 / 대) other_income — 기말 집중, 근거 빈약
5. 후속 연도 일시 손상: 차) 손상차손 / 대) 투자자산 (대형 단건)

**(d) woven 주입 시그니처**
- 계정: 투자자산(asset/investments)·손상차손(expense/impairment_loss) — §2.1 확장.
  정상 쌍둥이: 정상 취득·처분·적정 손상 분개.
- IC lane 컨텍스트(연체·거래 축소)와 결합해 멀티컴퍼니 구조 활용.
- 부작위(손상 부재) 금액은 instance 메타, 작위(출자·평가익) 문서에 라벨.
- component_role: `investment_acquisition | propping_injection | unjustified_revaluation | subsequent_impairment`
- fraud_type=`impairment_avoidance`, severity medium~high.

**(e) anti-shortcut**
- 정상에도 투자 취득·처분·손상·평가가 존재해야 함. 분리자는 "부실 컨텍스트(IC 연체·거래 축소)와
  손상 부재의 결합 + 기말 평가익 타이밍". 투자자산 계정 사용 자체는 신호 아님.
- 부작위 구성요소는 FS12와 같이 low-trace stratum 으로 평가 분리. 작위 구성요소(출자·평가익)는
  일반 stratum.

**(f) prevalence**
회사-연도당 0~1 instance. 작위 문서 5~15건 + instance 메타 미인식 손상 금액.

---

### FS14. 유령직원·급여 횡령

**(a) 실제 사례/근거**
ACFE(공인부정조사사협회) Report to the Nations 가 급여 부정(payroll scheme — 유령직원, 급여
부풀리기)을 자산유용(asset misappropriation)의 주요 하위 유형으로 분류한다
([ACFE Report to the Nations](https://acfepublic.s3.us-west-2.amazonaws.com/2024-report-to-the-nations.pdf)).
(불확실) 한국 상장사 금감원 감리 사례에서는 드문 유형 — 비상장·중소기업과 내부감사 적발 영역에서
주로 보고된다. 한국 확정 판례 1차 출처는 보강 필요.

**(b) 회계 메커니즘**
- 퇴사자를 마스터에서 말소하지 않거나 허위 직원을 등록 → 매월 급여 지급 지속.
- 분개: 차) 급여비용(6100) / 대) 현금 — payroll clearing(9100) 경유. 표면상 완전 정상.
- 수취 계좌가 공모자·횡령자 본인 계좌. 원천세·4대보험 처리에서 미세 불일치가 남는다.

**(c) 다문서/다계정/다기간 조정**
1. 마스터 조작: employees.json 에 퇴사 후 termination_date 미기록 직원 또는 허위 직원 1~3명
2. 매월 반복 급여 분개 (12~24개월) — 금액·주기 정상 분포
3. 수취 계좌 교차: 유령직원의 bank_account 가 다른 재직 직원·공모자와 중복
4. 원천세 표면: 해당 직원의 원천징수 납부 흐름 불일치 (tax 표면, 선택적)
5. cost_center 부유: 유령직원의 부서·승인 라인이 형식적 (관리 공백 부서)

**(d) woven 주입 시그니처**
- 표면: employees.json 마스터 + 월별 GL 급여 분개 + payroll clearing(9100). COA 확장 불필요.
- component_role: `ghost_employee_master | recurring_payroll_payment | shared_bank_account`
- fraud_type=`payroll_ghost_employee`, severity low~medium (누적 시 medium).

**(e) anti-shortcut**
- 정상 급여 분개가 대량 존재 (v29 직원 204명). 분리자는 **마스터-거래 교차**(퇴사 후 지급 지속,
  계좌 중복, 승인 라인 공백)뿐 — 분개 단독으로는 완전 정상.
- 유령직원 마스터 레코드의 모든 필드 형식은 정상 직원과 동일 분포 (이름·주소·계좌 형식 누수 금지).

**(f) prevalence**
회사당 0~1 instance (다년). 유령직원 1~3명 × 월 1건 × 12~24개월 ≈ 12~50건.

---

## 4. Prevalence 종합 — 주입 배분 기본값

금감원 §3.3 분포(53/29/26/11/5/4%)와 사례 규모를 근거로 한 **회사-연도 단위 기대 instance 수**.
부정은 희소해야 한다 — 연평균 감리지적 약 13건(전체 상장사 대비)이라는 현실 베이스레이트를
존중하되, 학습·평가가 가능한 최소 밀도로 조정한 값이다.

```
scheme  기대 instance/회사-연도   instance당 문서수   문서 기준 비중(320k 모집단 가정)
─────────────────────────────────────────────────────────────────────────
FS01        0~1                 30~80              ~0.02%
FS02        0~1 (수주산업만)      25~80              ~0.02%
FS03        0~1 (다년 1개)        30~100             ~0.02%
FS04        0~2                 10~30              ~0.02%
FS05        0~1 (그룹당)          40~100             ~0.02%
FS06        0~1                  8~20              ~0.005%
FS07        0~1 (제조·유통)        6~18              ~0.005%
FS08        0~1                 10~30              ~0.01%
FS09        0~2                  8~25              ~0.01%
FS10        0~1                 10~30              ~0.01%
FS11        0~1 (그룹당)         12~40              ~0.01%
FS12        0~1                  4~10              ~0.002% (low-trace)
FS13        0~1                  5~15              ~0.003%
FS14        0~1 (다년 1개)       12~50              ~0.01%
─────────────────────────────────────────────────────────────────────────
합계 가이드: 전체 문서의 0.1~0.25% 이내. 모든 scheme 동시 주입 금지(한 데이터셋에 5~8개 권장,
조합을 데이터셋 버전별로 회전) — "모든 부정이 다 있는 회사"는 비현실적이며 과밀 학습을 유발.
단, **데이터셋 버전 회전을 한 바퀴 돌면 14개 scheme 전부가 최소 1회 이상 주입**되어야 한다
(검증 커버리지 요건 — §3 커버리지 매트릭스).
```

상대 가중(금감원 분포 근거): 가공·매출계열(FS01·FS05·FS09) > 결산수정계열(FS02·FS08·FS10·FS13) ≈
횡령계열(FS03·FS04·FS14) > 부채·재고(FS06·FS07) ≈ 특관(FS11) > low-trace(FS12).

### 4.1 전체 모집단 대비 부정 문서 비중 (v29 규모 320,312 documents 기준)

```
시나리오                          instance 수    부정 문서 수      모집단 대비
──────────────────────────────────────────────────────────────────────────
권장 기본 (scheme 5~8개 조합)       6~11          약 120~450        0.04~0.14%
전체 14개 최대 주입 (비권장)         15~19         약 230~680        0.07~0.21%
──────────────────────────────────────────────────────────────────────────
```

- 산출 방법: §4 표의 instance당 문서수 범위 합산. 부정 "문서 수" = `is_fraud=true` 라벨 문서
  (작위 구성요소) 기준이며, FS10·FS12·FS13의 부작위(미인식 금액)는 문서 수에 포함되지 않는다.
- 재무제표 **금액 영향**은 문서 수 비중보다 훨씬 크다 — scheme 이 자산·수익 잔액을 누적시키는
  구조이기 때문 (예: FS01 매출 1~5%, FS02 이익 단위 왜곡).
- truth 평가 단위는 문서가 아니라 **scheme instance** (데이터셋당 5~12개)이므로, instance 수준
  통계가 필요하면 단일 데이터셋 밀도를 올리지 말고 **시드·조합을 바꾼 복수 데이터셋**으로
  instance 표본을 늘린다 (한 회사에 부정 과밀 금지 원칙 유지).

## 5. 공통 anti-shortcut 규약 (전 scheme)

1. **표면값 누수 금지**: 부정 전용 토큰·문구·금액대·시간대·작성자명·거래처 명명 패턴 금지.
   모든 표면 필드는 정상 분포에서 추출.
2. **데이터 품질 동일 적용**: MCAR 결측·오타·서식 변동을 정상/부정 동일 비율로 (프로젝트 규약).
3. **정상 쌍둥이 필수**: 각 scheme의 개별 구성요소(기말 수정분개, suspense 경유, IC 차이,
   연말 매출 증가, 반품, 재분류 등)는 정상 데이터에도 충분량 존재해야 한다. 부정은 **구성요소의
   조합·시계열·관계 구조**로만 정상과 분리된다.
4. **라벨 비입력**: is_fraud/fraud_type/scheme_* 는 truth 전용. 학습 피처 사용 금지.
5. **실제 flow 멤버십**: woven 구성요소는 진짜 document_flows/intercompany/relationships 파일에
   들어간다. 라벨 전용 가짜 sidecar flow 금지 (r23 교훈).
6. **식별자 규약 준수**: document_id/UUID·document_number 채번이 정상과 같은 generator를 통과해야
   한다 (식별자 stride·범위로 구분되면 shortcut).

## 6. 한계·불확실 사항

- COA 확장(§2.1)은 별도 작업으로 진행 — 본 카탈로그의 FS02·FS03·FS04·FS08·FS10·FS11·FS12·FS13 (d)는
  확장 완료를 전제로 기술되어 있다. 확장 시 신규 계정의 **정상 쌍둥이 거래**(§2.1 우측 열)를
  정상 데이터에 반드시 함께 생성해야 한다.
- FS02의 공사계약 개체·진행률 마스터는 COA 범위 밖(document_flows 차원) — 계정·분개 수준
  표현은 가능하나 계약 단위 진행률 추적은 추가 확장 필요.
- 부산저축은행 분식 총액은 보도별 편차가 있어 본 문서는 "수조 원대"로만 기재 (불확실).
- KAI 사례는 검찰 수사·의혹 단계 보도가 주 출처로, 확정 감리조치 세부는 본 문서에서 미인용 (불확실).
- FS12(충당부채 미인식)·FS14(유령직원)는 메커니즘·분류 근거는 확보했으나 한국 확정 사례의
  1차 출처가 미비 — 사례 보강 전까지 (불확실) 유지. FS12는 low-trace stratum 으로 평가 분리.
- 금감원 189건 분류는 본 프로젝트의 자체 본문 분석(DETECTION_REFERENCE.md §3)에 의존 — 원 사례
  본문은 `data/finding/` 에 있다.
- 본 카탈로그는 주입 **설계** SoT다. 실제 주입 파라미터(금액 분포, 회사 배정, 연도 배치)는
  구현 단계에서 별도 spec으로 분리한다.

## 7. 출처 목록

- 모뉴엘: [사이다경제](https://cidermics.com/contents/detail/1010) · [리걸타임즈](https://www.legaltimes.co.kr/news/articleView.html?idxno=89660) · [위키백과](https://ko.wikipedia.org/wiki/%EB%AA%A8%EB%89%B4%EC%97%98) · [KCI 사례연구](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002005240)
- 대우조선해양: [한국경제](https://www.hankyung.com/article/202407258027i) · [법률신문](https://www.lawtimes.co.kr/news/200144) · [나무위키](https://namu.wiki/w/%EB%8C%80%EC%9A%B0%EC%A1%B0%EC%84%A0%ED%95%B4%EC%96%91%20%EB%B6%84%EC%8B%9D%ED%9A%8C%EA%B3%84%20%EC%82%AC%EA%B1%B4)
- 오스템임플란트: [법률신문](https://www.lawtimes.co.kr/news/197550) · [한국경제](https://www.hankyung.com/article/202404149544i) · [파이낸셜뉴스](https://www.fnnews.com/news/202404140959541193)
- 계양전기: [경향신문](https://www.khan.co.kr/article/202209061047001) · [머니투데이](https://news.mt.co.kr/mtview.php?no=2023060815122188688)
- SK글로벌: [디지털타임스](http://www.dt.co.kr/contents.html?article_no=2003121802011866618004) · [제주일보](http://www.jejunews.com/news/articleView.html?idxno=21177)
- 부산저축은행: [KCI](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001771759) · [나무위키](https://namu.wiki/w/%EB%B6%80%EC%82%B0%EC%A0%80%EC%B6%95%EC%9D%80%ED%96%89)
- 개발비 테마감리: [금융위 감독지침](https://www.fsc.go.kr/po010106/73325) · [KCI 테마감리 효과](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002769859) · [데일리팜](https://m.dailypharm.com/News/236175)
- 재고 허위보관·유형별 적발사례: [비즈니스포스트](https://www.businesspost.co.kr/BP?command=print&idxno=81259) · [일요경제](http://www.ilyoeconomy.com/news/articleView.html?idxno=36824) · [한울회계법인](https://www.crowe.com/kr/news/news20190828_kr)
- 매출 분식 최다 통계: [비즈니스포스트 컴퍼니 백브리핑](https://www.businesspost.co.kr/BP?command=article_view&num=352968)
- 특수관계자 이익조정: [KISS](https://kiss.kstudy.com/Detail/Ar?key=3659997)
- 급여 부정 유형 분류: [ACFE Report to the Nations 2024](https://acfepublic.s3.us-west-2.amazonaws.com/2024-report-to-the-nations.pdf)
- 내부 실증: docs/spec/DETECTION_REFERENCE.md §2.1(ISA 240 A45 원문)·§2.4(ISA 520)·§2.5(ISA 550 §23)·§3(금감원 189건)
- 데이터 형식: `data/journal/primary/datasynth_semantic_v1_normal_20260607_v29` (스키마 직접 확인)
