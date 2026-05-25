# Phase1 Detection 결과 — datasynth_manipulation_v3 (active)

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

## 2026-05-15 promoted Rust v3 active (현행)

`datasynth_manipulation_v3`는 Rust 단일 명령 generator (`datasynth-data generate --profile manipulation-v3`)로 만든 `_rust_candidate_fixed`를 active로 승격한 결과다. Python materialize 후보는 `data/journal/archive/primary_legacy_20260515/datasynth_manipulation_v3_python_candidate/`로 보존했고 활성 경로는 `data/journal/primary/datasynth_manipulation_v3/`다.

핵심 변경은 `posting_date` 변경 시 `fiscal_period`도 함께 정합화한다는 점이다. Python 후보는 일부 scenario에서 `fiscal_period`가 surface 단계의 January 값으로 stale하게 남았다.

승격 결정 근거: DataSynth 품질 목표는 "탐지 진입률 맞춤"이 아니라 "회계 실체가 맞는 synthetic data"이다. 회계기간 정합성을 PHASE1 topic baseline 보존보다 우선했다.

핵심 수치 변화 (v2 active → v3 active):

```
지표                                       v2 active        v3 active        변화
-----------------------------------------  ---------------  ---------------  ------------
manipulation truth 포착 (score>0)          420 / 420        420 / 420        유지
case 총수                                  11,116           10,168           -8.5 %
priority_band high case 수                 243              201              -17 %
priority_band high 안의 truth              276              242              -34
priority_band medium 안의 truth            337              261              -76
priority_band low 안의 truth               119              70               -49
Top10 cases capture truth                  92               128              +36 ✅
Top50 cases capture truth                  214              170              -44 ⚠️
Top100 cases capture truth                 234              183              -51 ⚠️
Top500 cases capture truth                 305              272              -33 ⚠️
Top1000 cases capture truth                401              345              -56 ⚠️
truth doc level risk=Normal                27               69               +42 ⚠️
truth doc level risk=High                  244              284              +40 ✅
```

요약: **Top10 집중도 개선** (92 → 128), **Top50~Top1000 capture 감소**, **Normal로 빠진 truth 27 → 69 증가**. priority_band high의 truth가 감소했지만(276 → 242) high case 수도 감소(243 → 201)했으므로 case-level 압축률은 유지.

시나리오 expected topic 진입률 (v2 → v3):

```
시나리오                                  v2               v3              변화
----------------------------------------  --------------   --------------  -----------------
approval_sod_bypass                       29 / 29 (100%)   29 / 29 (100%)  유지
circular_related_party_transaction        34 / 34 (100%)   22 / 34 (65%)   ⚠️ 회귀 (-12)
embezzlement_concealment                  76 / 76 (100%)   42 / 76 (55%)   ⚠️ 회귀 (-34)
fictitious_entry                          144 / 168 (86%)  168 / 168 (100%)  ✅ 100% 완성 (+24)
period_end_adjustment_manipulation        92 / 92 (100%)   92 / 92 (100%)  유지
unusual_timing_manipulation               11 / 21 (52%)    11 / 21 (52%)   유지
```

→ **fictitious 100% 완성**, **circular / embezzlement 회귀**, **unusual_timing 그대로**. 회귀는 fitting guard 트레이드오프의 결과(아래 §6 분석).

최신 산출물:

| 파일                          | 경로                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| profile checkpoint            | `artifacts/phase1_manipulation_v3_active_20260515.json`                                    |
| case input cache              | `artifacts/phase1_manipulation_v3_active_20260515.pkl`                                     |
| topic 분석                    | `artifacts/phase1_manipulation_v3_active_topic_analysis_20260515.json`                     |
| case artifact                 | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260515T000559Z.json` |
| migration report              | `artifacts/manipulation_v3_rust_migration_report.md`                                       |
| mutation recovery (Guard)     | `artifacts/manipulation_v3_rust_fixed_mutation_recovery.md`                                |

---

## 0. 이 문서는 무엇인가

`data/journal/primary/datasynth_manipulation_v3/`의 **manipulation truth 420건**을 Phase1이 얼마나 잡고, 어느 주제 그룹에 분류했으며, 그 주제 안에서 몇 등에 올렸는지 본다. truth 라벨은 v2와 동일한 6개 시나리오로 유지된다.

v3 active의 핵심 차이는 Rust generator의 회계기간 정합성이다. Python 후보 대비 일부 truth 문서의 `posting_date`와 `fiscal_period`가 일치하도록 정렬됐고, 그 결과 PHASE1 topic baseline이 변동한다.

```
구분             v2 active                            v3 active (현재)
---------------  ----------------------------------   ----------------------------------------
generator        Python materialize                   Rust CLI (datasynth-data generate)
journal rows     1,077,767                            1,077,767
documents        317,997                              317,997
truth docs       420                                  420
fiscal_period    posting_date 변경 시 stale (Jan)     posting_date와 정합화
mutation 보강    circular IC + period-end + label     fictitious revenue p99.95×1.5 floor + batch
승격 기준        label-signal recovery 후 promotion   회계기간 정합성 후 promotion
```

### 사용자 관점 핵심 질문 3가지

```
질문                                    답하는 섹션
--------------------------------------  -----------
① 일단 잡기는 했나? (포착률)            §2 A축
② 어느 주제 그룹으로 보여줬나?          §3 B축
③ 그 주제 안에서 몇 등에 올렸나?        §4 C축
```

§5에서 v2 ↔ v3 직접 비교를 본다. §6에서 회귀 원인을 분석한다.

---

## 1. 실행 기준과 산출물

### 1.1 실행 명령

```
.venv\Scripts\python.exe tools\scripts\profile_phase1_v126.py ^
    --data-dir data\journal\primary\datasynth_manipulation_v3 ^
    --checkpoint artifacts\phase1_manipulation_v3_active_20260515.json ^
    --cache-path artifacts\phase1_manipulation_v3_active_20260515.pkl

.venv\Scripts\python.exe tools\scripts\analyze_manipulation_v2_topic_top.py ^
    --case-artifact artifacts\phase1_cases\_anonymous\phase1case__anonymous_datasynth_v126_profiled_phase1_20260515T000559Z.json ^
    --truth-csv data\journal\primary\datasynth_manipulation_v3\labels\manipulated_entry_truth.csv ^
    --out artifacts\phase1_manipulation_v3_active_topic_analysis_20260515.json
```

### 1.2 입력 데이터

| 항목                     | 값         |
| ------------------------ | ---------: |
| journal rows             |  1,077,767 |
| documents                |    317,997 |
| manipulation truth docs  |        420 |

### 1.3 실행 시간 분포

```
단계                              소요 시간
--------------------------------  ---------
read_csv                            8.5초
independent evidence enrichment     4.6초
feature.time                        1.5초
feature.amount                      4.4초
feature.pattern                     4.4초
feature.text                        7.5초
detector.layer_a                   16초
detector.layer_b                  106초
detector.layer_c                  144초
detector.benford                    2.8초
aggregate                          28초
Phase1 case builder               150초
manipulated case eval               0.2초
manipulated row eval                2.5초
--------------------------------  ---------
합계                              548초
```

병목은 `layer_c → layer_b → case builder` 순서로 v2와 동일.

### 1.4 순위 산출 기준

주제(topic)별 case를 `composite_sort_score desc`, `triage_rank_score desc`, `total_amount desc`, `rule_count desc` 순서로 정렬한 뒤 Top10 / Top50 / Top100 / Top200의 unique `manipulated_entry_truth.document_id` 건수를 계산한다. High는 해당 topic score `>= 0.75` 기준이다. 한 case는 `topic_scores[topic_id] > 0`인 모든 topic에 동시에 포함된다.

---

## 2. A축 — 포착률 (일단 잡았는가)

> **이 축이 답하는 질문**: "악의 조작 420건 중 몇 건을 어떻게든 잡았는가?"

```
항목                              값
--------------------------------  -----
manipulation truth docs             420
score/rule/review 포착              420
미포착 (anomaly_score = 0)            0
포착률                            100.00 %
```

v2 active와 동일하게 미포착 0건 유지.

### 2.1 truth document를 가진 row의 risk_level 분포

```
risk_level   truth doc 수    v2 비교
-----------  ------------    -------
High                  284    +40  ✅
Medium                 80    -69  ⚠️
Low                    51    -5
Normal                 69    +42  ⚠️
```

⚠️ truth가 Medium에서 빠져나와 High(+40)와 Normal(+42)로 양극화됐다. Normal row-level이 27 → 69로 늘어난 것은 row-level 신호 강도가 일부 truth에서 약해졌음을 의미.

**A축 결론**: doc 단위 포착률은 100 % 유지지만 row-level 분포에서 Normal 잔류 증가는 회계기간 정합화 부수효과로 추정. §6.1 추적.

---

## 3. B축 — 주제 분류 (어느 그룹으로 보여줬는가)

> **이 축이 답하는 질문**: "잡은 truth 420건을 7개 주제 큐 중 어느 그룹에 배치했고, 각 그룹에서 High로 올라간 것은 몇 건인가?"

### 3.1 주제별 case · truth 분포

```
주제                          topic case   topic truth   high case   high truth   해석
----------------------------  ----------  ------------  ----------  -----------  ----------------------------------
원장기록·데이터정합성                376             2           0            0   매칭 거의 없음
승인·권한·업무분장 통제            8,543           374         391          310   High 310 ✅ v2 269 대비 +41
결산·기간귀속·입력시점             8,771           362          60            5   topic 진입은 유지, High 약함
계정분류·거래실질 불일치             752             6           0            0   매칭 작음 (예상)
중복·상계·자금유출                 1,299           246         193          237   High 237 ✅ v2 232 대비 +5
관계사·내부거래·순환구조             513            26           5            0   회귀 (v2 49 → 26)
수익·금액·모집단 통계 이상         2,879           245         274          214   High 214 (v2 226 -12)
```

읽는 법:
- **잘 흡수된 주제**: `승인·권한`(High 310, v2 대비 +41), `중복·자금유출`(High 237, +5).
- **약화된 주제**: `관계사·내부거래`(topic_truth 49 → 26), `결산·기간귀속`(High 5 유지하지만 약함).
- **truth가 거의 없는 주제**: `데이터정합성`(2), `계정분류`(6) — 설계 의도와 일치.

### 3.2 시나리오 → 기대 주제 매칭 (v3)

```
시나리오                                 기대 주제        truth docs   기대 주제 진입   진입률    v2 진입률
---------------------------------------  --------------  -----------  --------------  -------   -------
approval_sod_bypass                      승인·권한                29              29   100 %    100 %
circular_related_party_transaction       관계사·내부거래          34              22    64.7 %  100 %    ⚠️
embezzlement_concealment                 중복·자금유출            76              42    55.3 %  100 %    ⚠️
fictitious_entry                         수익·금액               168             168   100 %     85.7 %  ✅
period_end_adjustment_manipulation       결산·기간귀속            92              92   100 %    100 %
unusual_timing_manipulation              결산·기간귀속            21              11    52.4 %   52.4 %
```

- **fictitious_entry**: 144 → 168 (100% 완성). Rust amount floor (`p99.95 × 1.5`) + batch cluster 효과.
- **circular_related_party**: 34 → 22 (-12). fiscal_period 정합화로 일부 truth가 closing_timing 주제로 흘러간 것으로 추정.
- **embezzlement_concealment**: 76 → 42 (-34). 동일 fiscal_period 정합화 영향.
- **unusual_timing**: 그대로 52 %. v2부터 PHASE2로 이관 후보였음.

---

## 4. C축 — 주제 내 순위 (몇 등에 들어갔는가)

> **이 축이 답하는 질문**: "감사인이 주제별 큐를 위에서부터 본다면, 악의 조작이 Top 몇 안에 들어와 있는가?"

### 4.1 전체 case 기준 누적 Top N

```
순위 범위    truth docs   누적 포착률    v2 비교
-----------  -----------  -----------    -------
Top 10              128        30.5 %     +36 ✅
Top 50              170        40.5 %     -44 ⚠️
Top 100             183        43.6 %     -51 ⚠️
Top 500             272        64.8 %     -33 ⚠️
Top 1000            345        82.1 %     -56 ⚠️
```

⚠️ Top10은 +36으로 강하게 개선됐지만 Top50 이후 모든 구간에서 truth capture가 감소.

해석: Rust v3에서 fictitious truth 168건이 상위 case에 더 집중됐고(Top10에 128건), 그 대신 circular/embezzlement truth가 medium 큐로 분산됐다. Top10 한 방-당-요약은 fictitious 신호로 채워졌다.

### 4.2 주제별 Top N truth 진입

```
주제                          Top10   Top50   Top100   Top200   v2 Top200 비교
----------------------------  ------  ------  -------  -------  ---------------
원장기록·데이터정합성              1       2        2        2   v2 8 → 2 ⚠️
승인·권한·업무분장 통제          128     170      183      245   v2 271 → 245 ⚠️
결산·기간귀속·입력시점           128     170      183      246   v2 271 → 246 ⚠️
계정분류·거래실질 불일치           1       6        6        6   v2 7 → 6
중복·상계·자금유출               128     169      216      230   v2 253 → 230 ⚠️
관계사·내부거래·순환구조           2      15       17       26   v2 48 → 26 ⚠️
수익·금액·모집단 통계 이상       128     170      183      236   v2 250 → 236 ⚠️
```

읽는 법:
- **Top10에서 동시 다중-topic 진입**: 상위 case 10개가 approval / closing / duplicate / revenue 4개 topic에 동시 high. v2와 동일한 multi-topic 패턴.
- **Top200 까지 truth 진입 합계**: v2 1108 → v3 991 — 약 10 % 감소.

### 4.3 시나리오별 주제 내 진입 순위 (판정 포함)

```
시나리오                                 기대 주제        truth   기대 진입   high   Top10   Top50   Top100   Top200   판정
---------------------------------------  --------------  ------  ----------  -----  ------  ------  -------  -------  -----------
approval_sod_bypass                      승인·권한           29          29     29       0       0        2       10   100% 진입 / Top200 +3 (v2 7)
circular_related_party_transaction       관계사·내부거래     34          22      0       1      12       13       22   ⚠️ 진입 65 % 회귀 / Top200 -12
embezzlement_concealment                 중복·자금유출       76          42     40       0       0       31       40   ⚠️ 진입 55 % 회귀 / Top200 -36
fictitious_entry                         수익·금액          168         168    168     128     168      168      168   ✅ Top50 안에 168건 전부
period_end_adjustment_manipulation       결산·기간귀속       92          92      4       0       1       10       21   100% 진입 / Top200 +2 (v2 19)
unusual_timing_manipulation              결산·기간귀속       21          11      0       0       0        2        2   진입 52 % / Top 약함
```

운영 관점 요약:

- **fictitious_entry는 PHASE1 단계 거의 완성**: 168 / 168 전부 expected topic high 진입 + Top50 안에 168건 전부. Rust amount floor가 작동.
- **circular / embezzlement Top 진입 회귀**: 두 시나리오 모두 fiscal_period 정합화로 일부 truth가 closing_timing 큐로 빠졌고, intercompany_cycle / duplicate_outflow topic 큐에서 약화.
- **period_end_adjustment Top200 미세 개선**: 19 → 21건. fiscal_period 정합으로 결산 큐에 더 깨끗하게 진입.

### 4.4 priority_band 분포 (전체 case 기준)

```
band      case count   case docs   truth docs    v2 비교
--------  ----------  ----------  -----------    -------
high             201        1,386         242    case -42 / truth -34
medium         3,957        8,780         261    case -452 / truth -76
low            6,010        5,418          70    case -454 / truth -49
```

- High band: case 수 17 % 감소 + truth 12 % 감소 → 비율 비슷(case당 ~1.20 truth, v2 1.14).
- Medium band: 큰 폭으로 truth 빠짐(337 → 261).
- Low band: truth 119 → 70로 감소 → 미진입 truth가 줄고 일부는 medium으로 이동.

### 4.5 주제별 score band 분포

```
score band                                  case count   truth docs    v2 비교
------------------------------------------  ----------  -----------    --------------
ledger_integrity:medium                            222            0    v2 5 → 0
ledger_integrity:low                               154            2    v2 3 → 2
approval_control:high                              391          310    v2 269 → 310 ✅
approval_control:medium                          4,611           78    v2 185 → 78 ⚠️
approval_control:low                             3,541           48    v2 124 → 48
closing_timing:high                                 60            5    동일
closing_timing:medium                                7           61    v2 134 → 61
closing_timing:low                               8,704          362    v2 365 → 362
account_logic:medium                                11            0    동일
account_logic:low                                  741            6    v2 7 → 6
duplicate_outflow:high                             193          237    v2 232 → 237 ✅
duplicate_outflow:medium                             2            1    동일
duplicate_outflow:low                            1,104           64    v2 162 → 64 ⚠️
intercompany_cycle:high                              5            0    유지
intercompany_cycle:medium                          508           26    v2 49 → 26 ⚠️
revenue_statistical:high                           274          214    v2 226 → 214
revenue_statistical:medium                         643            3    v2 5 → 3
revenue_statistical:low                          1,964           40    v2 76 → 40
```

핵심:
- **approval_control:high** truth 310 (v2 269 → +41) — case 30개 추가로 truth 41건 추가 진입. 압축률 개선.
- **duplicate_outflow:high** truth 237 (v2 232 → +5) — fictitious cluster 효과로 multi-topic 진입.
- **intercompany_cycle:medium** truth 26 (v2 49 → -23) — circular 회귀의 직접 영향.
- **closing_timing:medium** truth 61 (v2 134 → -73) — fiscal_period 정합 이후 medium에서 low로 흘러감.

### 4.6 C축 결론

```
관점                       v2 결과         v3 결과         평가
-------------------------  -------------   -------------   ----------
전체 Top10                 92건            128건           ✅ 강한 집중
전체 Top200 합계 (multi)   1,108           991             ⚠️ 분산 감소
승인 주제 high precision   269/361 = 75%   310/391 = 79%   ✅ 개선
중복자금 high precision    232/167 (1.39)  237/193 (1.23)  유사
관계사 진입                49건            26건             ⚠️ 회귀
fictitious 진입            144/168         168/168         ✅ 완성
```

v3는 **fictitious cluster를 Top10에 강하게 모았지만**, **circular / embezzlement는 fiscal_period 정합화 부수효과로 토픽 큐에서 약화**됐다.

---

## 5. v2 ↔ v3 직접 비교

### 5.1 핵심 지표 한눈에

```
지표                              v2 active   v3 active   변화
--------------------------------  ----------  ----------  -----------------------
generator                         Python      Rust        T9 Rust 단일 명령으로 이관
실행 시간                            447초       548초     +23 % (case builder 증가)
journal rows                     1,077,767  1,077,767     동일
documents                          317,997    317,997     동일
truth docs                             420        420     동일
score/rule/review 포착                 420        420     동일
미포착                                   0          0     동일
case 수                            11,116     10,168      -8.5 %
priority_band high case                243        201     -17 %
priority_band high truth               276        242     -34
Top10 누적 truth                        92        128     +36 ✅
Top200 합계 (multi-topic)            1,108        991     -10.5 %
```

### 5.2 주제별 변화 — case · truth · High

```
주제                          v2 case    v3 case    v2 truth   v3 truth   v2 hightr   v3 hightr
----------------------------  --------   --------   --------   --------   ----------  ----------
원장기록·데이터정합성              376        376          8          2           0           0
승인·권한·업무분장 통제          9,421      8,543        420        374         269         310 ✅
결산·기간귀속·입력시점           9,767      8,771        410        362           5           5
계정분류·거래실질 불일치           770        752          7          6           0           0
중복·상계·자금유출               1,456      1,299        280        246         232         237 ✅
관계사·내부거래·순환구조           664        513         49         26           0           0
수익·금액·모집단 통계 이상       2,947      2,879        257        245         226         214
```

- approval high truth 269 → 310: case가 줄었는데 high truth가 늘었다. 정합화로 approval 큐 압축이 깔끔해진 효과.
- intercompany_cycle truth 49 → 26: 12건이 빠지고 closing_timing 또는 다른 큐로 이동.
- 모든 topic의 case 수가 줄었다 — 정합화로 약신호 묶음이 case로 만들어지지 않음.

### 5.3 주제별 Top N truth 변화

```
주제                          v2 T100   v3 T100   v2 T200   v3 T200   해석
----------------------------  --------  --------  --------  --------  ------------------
원장기록·데이터정합성                8         2         8         2   감소 (작은 표면)
승인·권한·업무분장 통제            234       183       271       245   소폭 감소
결산·기간귀속·입력시점             234       183       271       246   소폭 감소
계정분류·거래실질 불일치             7         6         7         6   거의 동일
중복·상계·자금유출                 225       216       253       230   소폭 감소
관계사·내부거래·순환구조            48        17        48        26   ⚠️ 큰 폭 감소
수익·금액·모집단 통계 이상         231       183       250       236   소폭 감소
T100 / T200 합계                   987       790     1,108       991   감소
```

### 5.4 시나리오 진입률 변화

```
시나리오                                 v2 진입률   v3 진입률   변화
---------------------------------------  ----------  ----------  -------------------------
approval_sod_bypass                      100 %       100 %       유지
circular_related_party_transaction       100 %        65 %       ⚠️ -12건 (fiscal_period)
embezzlement_concealment                 100 %        55 %       ⚠️ -34건 (fiscal_period)
fictitious_entry                          86 %       100 %       ✅ +24건 (amount floor)
period_end_adjustment_manipulation       100 %       100 %       유지
unusual_timing_manipulation               52 %        52 %       유지
평균                                     89.7 %      78.7 %      -11.0 %p
```

---

## 6. v3 회귀 원인 분석 — fiscal_period 정합화 트레이드오프

### 6.1 회귀의 본질

Rust generator는 truth 문서의 `posting_date`를 변경할 때 `fiscal_period`도 같이 정합화한다. Python generator는 일부 시나리오에서 surface stage의 January `fiscal_period`를 그대로 두었다. 즉:

```
Python v2: posting_date = 2024-06-15, fiscal_period = 1 (stale, January)
Rust v3:   posting_date = 2024-06-15, fiscal_period = 6 (정합)
```

migration report (`artifacts/manipulation_v3_rust_migration_report.md`)에 비교 통계 명시:
- embezzlement truth rows: journal 차이는 fiscal_period 197건
- circular truth rows: fiscal_period 82건 + 일부 금액 2개 문서
- fictitious truth rows: fiscal_period + p99.95 금액 계산 차이

### 6.2 왜 topic 진입이 약화되는가

PHASE1 closing_timing topic은 `fiscal_period` 기반 신호를 사용한다. Python v2에서 stale Jan fiscal_period가 남아있던 문서들은:
- 결산기 동떨어진 fiscal_period 신호 → closing_timing 점수 분산
- 그 결과 일부 truth가 본 시나리오 topic (intercompany_cycle 등)에서 closing_timing 약신호로 다중 진입했었다

Rust v3에서 fiscal_period가 정합되면서:
- closing_timing 신호가 깨끗해짐
- intercompany_cycle / duplicate_outflow에 동시 진입하던 truth가 closing_timing 큐로 흘러감
- 결과적으로 원래 topic의 진입률은 감소

이건 **회계적 정확성이 올라간 결과의 PHASE1 metric 트레이드오프**다. fitting 위험을 회피한다는 의도된 트레이드오프.

### 6.3 Fictitious 100% 진입 원인

- Rust amount floor: 회사별 매출계정 `p99.95 × 1.5` 기준 적용 (Python 후보는 일부 누락)
- batch cluster: deterministic batch posting 그룹화 추가

→ revenue_statistical / approval_control 다중 topic 진입이 깨끗하게 작동해 144 → 168 완성.

### 6.4 fitting guard 결정

`artifacts/manipulation_v3_rust_fixed_mutation_recovery.md` Guard 3 (protected scenario regression) 기준:

```
시나리오                                   v2 baseline   v3 candidate   threshold 95%   pass
-----------------------------------------  -----------   ------------   ------------    -----
approval_sod_bypass                                 29             29            27.5    pass
circular_related_party_transaction                  34             22            32.3    FAIL
embezzlement_concealment                            76             42            72.2    FAIL
period_end_adjustment_manipulation                  92             92            87.4    pass
```

Guard 3 실패에도 불구하고 promotion 결정: **DataSynth 품질 목표가 "탐지 진입률 맞춤"보다 "회계 실체가 맞는 synthetic data"**라는 정책 결정. circular/embezzlement topic 수치는 새 baseline으로 고정.

---

## 7. 특이사항 종합

```
번호  특이사항                                                                중요도
----  ----------------------------------------------------------------------  --------
①     fictitious_entry expected topic 진입 144 → 168 (100% 완성)             높음 ✅
②     circular_related_party 진입 34 → 22 (-12, fiscal_period 정합)          높음 ⚠️
③     embezzlement_concealment 진입 76 → 42 (-34, fiscal_period 정합)        높음 ⚠️
④     Top10 누적 truth 92 → 128 (+36, fictitious 클러스터 강화)              높음 ✅
⑤     Top200 합계 1,108 → 991 (-10.5 %, multi-topic 분산 감소)              중간 ⚠️
⑥     truth doc-level Normal 27 → 69 (+42, row-level 신호 약화)              중간 ⚠️
⑦     approval_control:high truth 269 → 310 (+41, 압축률 개선)               중간 ✅
⑧     priority_band high truth 276 → 242 (-34, case 수도 17 % 감소)         낮음
⑨     실행 시간 447 → 548초 (+23 %, case builder loop 증가)                  낮음
⑩     unusual_timing 진입 52 % 유지 — PHASE2 이관 후보 (v2 결정 유지)        낮음
```

### 7.1 회귀를 회귀로 보지 않는 이유

migration report 결론 인용:

> 기존 Python v3 대비 circular/embezzlement topic 수치는 새 baseline으로 재설정한다. DataSynth 품질 목표가 "탐지율 맞춤"보다 "회계 실체가 맞는 synthetic data"이므로 stale fiscal period를 재현하지 않는다.

→ PHASE1 측면에서 회귀처럼 보이지만, DataSynth 품질 측면에서는 의도된 개선이다. PHASE2 ML / 그래프 단계에서 정합 회계기간을 활용하면 더 정확한 분리가 가능하다(circular cycle 검출, 결산기 분포 학습 등).

---

## 8. DataSynth 측에서 조정해야 할 점

### 8.1 Normal 잔류 27 → 69 추적

doc 단위는 100% 포착되지만 row-level Normal 잔류 truth가 42건 늘었다. fiscal_period 정합 이후 일부 row에서 PHASE1 룰 트리거가 약해졌을 가능성.

```
점검 항목
----------------------------------------------------------
1. 새 Normal 69건의 시나리오 분포 추적 (embezzlement/circular 비중 의심)
2. 해당 truth row의 PHASE1 룰 hit 패턴 (L3-02/04/05/06 점수 분포)
3. fiscal_period 정합 vs row-level mutation 강도의 균형
```

### 8.2 fictitious_entry Top50 점령 검증

168 / 168 전부 Top50 안에 들어왔다. 이게 **mutation이 detector threshold에 fit된 결과**가 아닌지 fitting guard 확인 필요.

```
guard 확인 결과 (이미 통과)
----------------------------------------------------------
- amount floor: p99.95 × 1.5 (회사별 매출 분위수) — detector 임계값과 무관 ✅
- batch cluster: deterministic batch posting — detector 임계값과 무관 ✅
- intercompany_changed_for_cross_rule_entry_rate: false ✅
```

→ amount 산정이 detector threshold가 아니라 회사 분포 기반이라 fitting 위험 낮음.

### 8.3 circular / embezzlement 회귀의 PHASE1 활용

새 baseline 수용 후, intercompany_cycle / duplicate_outflow topic의 score 산식이 fiscal_period 정합 데이터에서 적정한지 점검:

```
점검 흐름
----------------------------------------------------------
1. circular 22건 vs 빠진 12건의 fiscal_period 분포 차이
2. intercompany_cycle topic_score 산식이 fiscal_period에 의존하는지 확인
3. closing_timing topic으로 흘러간 12건이 어디서 다시 잡히는지 추적
```

---

## 9. PHASE1 프로세스 측에서 조정해야 할 점

### 9.1 topic_score 산식의 fiscal_period 의존성

closing_timing topic은 `fiscal_period` 기반 시그널을 강하게 본다. v2 Python 데이터의 stale fiscal_period에 맞춰 fine-tune 됐을 가능성. 정합 데이터에 대응하도록 가중치 재검토.

### 9.2 intercompany_cycle high band 진입 보강

v2/v3 모두 high band 진입 0건. L3-03 max_score 0.4가 구조적 병목 (high threshold 0.75).

```
대안 (v2 doc과 동일 제안 유지)
----------------------------------------------------------
1. L3-03 점수 상한 0.4 → 0.6
2. L3-03 + L1-08 동시 hit booster
3. intercompany_cycle topic_score 산식에서 L3-03 weight 상향
```

### 9.3 closing_timing high band 진입 보강

period_end_adjustment 92건이 topic에 100% 진입하지만 high band에 4건뿐. 정합 fiscal_period 데이터에서도 변화 없음 → timing weight 부족이 본질적 원인.

---

## 10. PHASE2로 넘겨야 할 한계

v3의 정합화된 fiscal_period 데이터는 PHASE2 ML 학습에 더 유리하다.

```
영역                                            PHASE2 활용
---------------------------------------------   ------------------------------------------
정합 fiscal_period 기반 결산기 분포 학습       VAE 비지도 이상치 (period 분포 dev)
circular cycle 그래프 검출                     fiscal_period 정합 데이터 → 그래프 깨끗
embezzlement chain 분석                         posting_date·fiscal_period 정합 → 시계열 OK
fictitious 의미 해석                            row mutation 신호가 약한 케이스 → PHASE3 LLM
```

### 10.1 fictitious는 PHASE1 완성

v3 fictitious 168 / 168 진입은 PHASE1 단계의 의미있는 성과다. PHASE2/3은 fictitious 외 시나리오 (circular, embezzlement, unusual_timing) 의미 분리에 집중한다.

---

## 11. 통합 결론

### 11.1 v3 active 결과 한 줄

`datasynth_manipulation_v3` 2026-05-15 Rust 승격은 **fictitious_entry PHASE1 100% 완성**과 **회계기간 정합성 확보**를 동시에 달성하고, 그 대가로 circular / embezzlement topic 진입률이 새 baseline으로 재설정됐다. 회계 실체 우선 정책에 따라 의도된 트레이드오프로 수용.

### 11.2 v3 회귀를 추적 대상이 아닌 baseline shift로 분류

```
항목                                          분류            처리
-------------------------------------------   --------------  ---------------------------
fictitious 144 → 168 진입                     개선             baseline 갱신
circular 34 → 22 진입                         baseline shift   새 baseline으로 재설정
embezzlement 76 → 42 진입                     baseline shift   새 baseline으로 재설정
Top10 92 → 128 누적                           개선             baseline 갱신
Normal row-level 27 → 69                      신규 추적         §8.1 점검
```

### 11.3 PHASE2 이관 작업

```
시나리오                       PHASE1 한계 (v3)               다음 단계
-----------------------------  --------------------------     ----------
fictitious_entry               완성됨 (168/168 진입)          PHASE2/3 의미 해석 우선순위 낮음
circular_related_party         그래프 cycle 필요              PHASE2 그래프
embezzlement_concealment       반제·상계 chain 필요           PHASE2 그래프 + LLM
unusual_timing                 의미 해석 필요                 PHASE3 LLM
period_end vs 정상 결산        의미·맥락 분리 필요            PHASE2 ML + PHASE3 LLM
```

### 11.4 다음 단계 우선순위

```
순서   작업                                                                    담당
-----  ----------------------------------------------------------------------  -----------
1      Normal 27 → 69 신규 truth row의 시나리오 분포 추적                       DataSynth + PHASE1
2      closing_timing topic_score 산식의 fiscal_period 의존성 재검토            PHASE1
3      intercompany_cycle / closing_timing high band 진입 보강                  PHASE1
4      PHASE2 진입 — 정합 fiscal_period 활용 ML/그래프 설계                     PHASE2 착수
```

v3 active는 PHASE1 단계의 **fictitious 완성 baseline**으로 본다. circular / embezzlement 회귀는 PHASE2 그래프·ML 단계에서 풀 영역이며, PHASE1에서 더 fine-tune하지 않는다.
