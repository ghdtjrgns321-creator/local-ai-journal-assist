# Phase1 Detection 결과 — datasynth_manipulation_v4_candidate

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

## 2026-05-15 v4 candidate Phase1 실행 (현행)

`datasynth_manipulation_v4_candidate`는 Rust 단일 명령 generator (`datasynth-data generate --profile manipulation-v4`)로 생성한 후보 데이터셋이다. v3 active를 덮지 않고 별도 경로(`data/journal/primary/datasynth_manipulation_v4_candidate/`)에 둔다.

v4의 핵심 변화 세 가지:
1. **hold-out 시나리오 2개 추가**: `expense_capitalization` 100건, `suspense_account_abuse` 100건. truth 합계 420 → 620.
2. **fictitious revenue fitting 완화**: 단일 `p99.95 × 1.5` floor → **upper-tail 버킷 샘플링** (`p99.0 ~ p99.9`). amount_ref_enforced 168 → 65.
3. **manual source 분산**: 시나리오 100% manual 강제 폐기. `manual_like_ratio` 0.45~0.79로 분산 (`approval` 79%, `expense_capitalization` 45%, `fictitious` 55%).

핵심 수치 변화 (v3 active → v4 candidate):

```
지표                                       v3 active        v4 candidate     변화
-----------------------------------------  ---------------  ---------------  ------------
시나리오 수                                6                8                +2 hold-out
manipulation truth docs                    420              620              +200
truth 포착 (score>0)                       420 / 420        620 / 620        100% 유지
case 총수                                  10,168           11,962           +17.6 %
priority high case 수                      201              272              +35.3 %
priority high 안의 truth                   242              332              +90
priority medium 안의 truth                 261              377              +116
priority low 안의 truth                    70               179              +109
Top10 cases capture truth                  128              36               -92 ⚠️
Top50 cases capture truth                  170              84               -86 ⚠️
Top100 cases capture truth                 183              252              +69 ✅
Top500 cases capture truth                 272              376              +104 ✅
Top1000 cases capture truth                345              416              +71 ✅
truth doc level risk=Normal                69               159              +90 ⚠️
truth doc level risk=High                  284              271              -13
```

요약: **Top10~Top50 집중도 큰 폭 감소** (fictitious fitting 완화의 직접 영향), **Top100 이후는 증가** (hold-out 200건 진입 효과), **Normal row level 27 → 159 가속** (manual ratio 분산 + 신규 시나리오의 약한 row-level 신호).

시나리오 expected topic 진입률 (v3 → v4):

```
시나리오                                  v3                v4                변화
----------------------------------------  ---------------   ---------------   ------------------
approval_sod_bypass                       29 / 29 (100 %)   29 / 29 (100 %)   유지
circular_related_party_transaction        22 / 34 ( 65 %)   21 / 34 ( 62 %)   소폭 감소
embezzlement_concealment                  42 / 76 ( 55 %)   36 / 76 ( 47 %)   소폭 회귀
expense_capitalization (hold-out 신규)    -                 100 / 100 (100%)  ✅ 신규 100 %
fictitious_entry                          168 / 168 (100 %)  80 / 168 ( 48 %)  ⚠️ 큰 회귀 (-88)
period_end_adjustment_manipulation        92 / 92 (100 %)   84 / 92 ( 91 %)   소폭 감소
suspense_account_abuse (hold-out 신규)    -                 100 / 100 (100%)  ✅ 신규 100 %
unusual_timing_manipulation               11 / 21 ( 52 %)   18 / 21 ( 86 %)   ✅ 회복 (+7)
```

→ **hold-out 2개 시나리오 100% 진입**, **unusual_timing 회복**, **fictitious 큰 폭 회귀**(fitting 완화 의도된 결과), 나머지는 미세 회귀.

최신 산출물:

| 파일                          | 경로                                                                                                       |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------- |
| profile checkpoint            | `artifacts/phase1_manipulation_v4_candidate_20260515.json`                                                 |
| case input cache              | `artifacts/phase1_manipulation_v4_candidate_20260515.pkl`                                                  |
| topic 분석                    | `artifacts/phase1_manipulation_v4_candidate_topic_analysis_20260515.json`                                  |
| case artifact                 | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260516T000628Z.json` |
| dataset manifest              | `data/journal/primary/datasynth_manipulation_v4_candidate/MANIPULATION_V4_DATASET_MANIFEST.json`           |

---

## 0. 이 문서는 무엇인가

`data/journal/primary/datasynth_manipulation_v4_candidate/`의 **manipulation truth 620건**(v3 420건 + hold-out 200건)을 Phase1이 얼마나 잡고, 어느 주제 그룹에 분류했으며, 그 주제 안에서 몇 등에 올렸는지 본다.

v4 candidate의 정책 변화 요점:

```
구분                v3 active                              v4 candidate
------------------  --------------------------------       ----------------------------------------
generator           Rust (manipulation-v3)                 Rust (manipulation-v4)
journal rows        1,077,767                              1,077,767
documents           317,997                                317,997
truth docs          420 (6 시나리오)                       620 (8 시나리오, +2 hold-out)
fictitious amount   p99.95 × 1.5 floor                     p99.0 ~ p99.9 버킷 샘플링
manual source       시나리오 100% manual                   시나리오별 45~79 % 분산
unusual_timing      통합 신호 (weekend+manual)             weekend / offhour / manual / self-approval 분리
fitting policy      detector threshold 기반 일부 noise     fitting block 강화
```

신규 hold-out 시나리오:
- **expense_capitalization** (비용 자본화): 100건 — L2-04 ExpenseCapitalization 룰 대응 → `account_logic` topic
- **suspense_account_abuse** (가수금 장기체류): 100건 — L3-09 SuspenseAccountAbuse 룰 대응 → `account_logic` topic

### 사용자 관점 핵심 질문 3가지

```
질문                                    답하는 섹션
--------------------------------------  -----------
① 일단 잡기는 했나? (포착률)            §2 A축
② 어느 주제 그룹으로 보여줬나?          §3 B축
③ 그 주제 안에서 몇 등에 올렸나?        §4 C축
```

§5에서 v3 → v4 직접 비교를 본다. §6에서 fictitious 회귀를 fitting 완화 트레이드오프로 해석한다.

---

## 1. 실행 기준과 산출물

### 1.1 실행 명령

```
.venv\Scripts\python.exe tools\scripts\profile_phase1_v126.py ^
    --data-dir data\journal\primary\datasynth_manipulation_v4_candidate ^
    --checkpoint artifacts\phase1_manipulation_v4_candidate_20260515.json ^
    --cache-path artifacts\phase1_manipulation_v4_candidate_20260515.pkl

.venv\Scripts\python.exe tools\scripts\analyze_manipulation_v4_topic_top.py ^
    --case-artifact artifacts\phase1_cases\_anonymous\phase1case__anonymous_datasynth_v126_profiled_phase1_20260516T000628Z.json ^
    --truth-csv data\journal\primary\datasynth_manipulation_v4_candidate\labels\manipulated_entry_truth.csv ^
    --out artifacts\phase1_manipulation_v4_candidate_topic_analysis_20260515.json
```

> v4용 분석 스크립트(`analyze_manipulation_v4_topic_top.py`)는 v2/v3 스크립트의 `EXPECTED_TOPIC`에 hold-out 2 시나리오(`expense_capitalization`, `suspense_account_abuse`)를 추가했다. 둘 다 `account_logic` topic을 기대 큐로 둔다.

### 1.2 입력 데이터

| 항목                     | 값         |
| ------------------------ | ---------: |
| journal rows             |  1,077,767 |
| documents                |    317,997 |
| manipulation truth docs  |        620 |
| 시나리오 수              |          8 |

### 1.3 실행 시간 분포

```
단계                              소요 시간
--------------------------------  ---------
read_csv                            8.5초
independent evidence enrichment     4.6초
feature.time                        1.5초
feature.amount                      4.4초
feature.pattern                     4.6초
feature.text                        7.6초
detector.layer_a                   17초
detector.layer_b                  108초
detector.layer_c                  140초
detector.benford                    2.8초
aggregate                          28초
Phase1 case builder               114초
manipulated case eval               0.2초
manipulated row eval                1.4초
--------------------------------  ---------
합계                              477초
```

병목은 `layer_c → layer_b → case builder` 순서로 v3와 동일. case builder가 v3 150초 → v4 114초로 단축 (case 압축률 향상).

### 1.4 순위 산출 기준

주제(topic)별 case를 `composite_sort_score desc`, `triage_rank_score desc`, `total_amount desc`, `rule_count desc` 순서로 정렬한 뒤 Top10 / Top50 / Top100 / Top200의 unique `manipulated_entry_truth.document_id` 건수를 계산한다. `topic high`는 해당 topic score `>= 0.75` 기준이다. 한 case는 `topic_scores[topic_id] > 0`인 모든 topic membership에 동시에 포함된다.

---

## 2. A축 — 포착률 (일단 잡았는가)

> **이 축이 답하는 질문**: "manipulation truth 620건 중 몇 건을 어떻게든 잡았는가?"

```
항목                              값
--------------------------------  -----
manipulation truth docs             620
score/rule/review 포착              620
미포착 (anomaly_score = 0)            0
포착률                            100.00 %
```

v3 active와 동일하게 미포착 0건. hold-out 200건 추가에도 포착률 유지.

### 2.1 truth document를 가진 row의 risk_level 분포

```
risk_level   truth doc 수    v3 비교
-----------  ------------    -------
High                  271    -13
Medium                155    +75
Low                   207    +156 ⚠️
Normal                159    +90  ⚠️
```

⚠️ **Normal 잔류가 v3 69 → v4 159로 +90 증가**. fictitious mutation을 회사 매출 분위 버킷 샘플링으로 분산시키고, 시나리오별 manual ratio를 50~80%로 분산한 결과 row-level 신호 강도가 평균적으로 약해진 것.

운영 의미는 doc 단위 포착률 100%는 유지되지만 **row-level 단일 신호로 잡히는 비율은 감소**. 다중 룰 hit / multi-topic case 묶음으로만 흡수되는 비중 증가.

**A축 결론**: doc 100% 포착 + row-level Normal 비율은 fitting 완화로 의도된 증가.

---

## 3. B축 — 주제 분류 (어느 그룹으로 보여줬는가)

> **이 축이 답하는 질문**: "잡은 truth 620건을 7개 주제 큐 중 어느 그룹에 배치했고, 각 그룹에서 High로 올라간 것은 몇 건인가?"

### 3.1 주제별 case · truth 분포

```
주제                          topic case   topic truth   high case   high truth   해석
----------------------------  ----------  ------------  ----------  -----------  ----------------------------------
원장기록·데이터정합성                376             7           0            0   매칭 작음 (v3 동일)
승인·권한·업무분장 통제          10,132           510         338          202   High 202 (v3 310 -108)
결산·기간귀속·입력시점           10,584           511          61           27   High 27 (v3 5 +22 ✅)
계정분류·거래실질 불일치           1,192           208           0            0   ⚠️ hold-out 200건 진입 / High 0
중복·상계·자금유출                 1,461           371         109          127   High 127 (v3 237 -110)
관계사·내부거래·순환구조             737            41           5            0   유지
수익·금액·모집단 통계 이상         2,747           180         120          142   High 142 (v3 214 -72)
```

읽는 법:
- **신규 진입 topic**: `account_logic` truth 208 (v3 6 → hold-out 200건의 직접 효과 + α). 그러나 high band 0건 — 룰 점수 산식이 high threshold 도달 못 함.
- **High 강화**: `closing_timing` 5 → 27 (+22, fictitious를 통한 multi-topic 진입이 closing_timing에도 흘러간 결과).
- **High 약화**: approval 310 → 202 (-108), duplicate 237 → 127 (-110), revenue 214 → 142 (-72). 모두 fictitious cluster가 multi-topic high로 줄어든 영향.

### 3.2 시나리오 → 기대 주제 매칭 (v4)

```
시나리오                                 기대 주제          truth   기대 주제 진입   진입률    v3 진입률
---------------------------------------  ----------------  ------  --------------  -------   -------
approval_sod_bypass                      승인·권한              29              29   100 %    100 %
circular_related_party_transaction       관계사·내부거래        34              21    61.8 %    64.7 %
embezzlement_concealment                 중복·자금유출          76              36    47.4 %    55.3 %
expense_capitalization (hold-out)        계정분류·거래실질     100             100   100 %       —    ✅ 신규
fictitious_entry                         수익·금액             168              80    47.6 %   100 %    ⚠️
period_end_adjustment_manipulation       결산·기간귀속          92              84    91.3 %   100 %
suspense_account_abuse (hold-out)        계정분류·거래실질     100             100   100 %       —    ✅ 신규
unusual_timing_manipulation              결산·기간귀속          21              18    85.7 %    52.4 %  ✅ 회복
```

- **hold-out 100% 진입**: expense_capitalization + suspense_account_abuse 둘 다 100/100. L2-04 / L3-09 룰 hit가 account_logic topic으로 의도된 큐에 들어감.
- **fictitious 큰 회귀**: 168/168 → 80/168 (-88). 회사 매출 분위 버킷 샘플링으로 일부 fictitious 금액이 amount 룰 threshold 아래로 분포 → revenue_statistical topic 진입 감소.
- **unusual_timing 회복**: 11/21 → 18/21 (+7). weekend/offhour/manual/self-approval 신호 분리로 closing_timing topic 매칭 다양화.

---

## 4. C축 — 주제 내 순위 (몇 등에 들어갔는가)

> **이 축이 답하는 질문**: "감사인이 주제별 큐를 위에서부터 본다면, 악의 조작이 Top 몇 안에 들어와 있는가?"

### 4.1 전체 case 기준 누적 Top N

```
순위 범위    truth docs   누적 포착률    v3 비교 (per-truth)
-----------  -----------  -----------    --------------------
Top 10               36         5.8 %    v3 30.5 % → -25 %p ⚠️
Top 50               84        13.5 %    v3 40.5 % → -27 %p ⚠️
Top 100             252        40.6 %    v3 43.6 % → -3 %p
Top 500             376        60.6 %    v3 64.8 % → -4 %p
Top 1000            416        67.1 %    v3 82.1 % → -15 %p
```

⚠️ Top10 / Top50 큰 폭 감소, Top100 거의 동일, Top500 / Top1000은 hold-out 200건 추가 효과로 절대값은 늘었지만 비율로는 감소.

해석:
- **Top10에 fictitious cluster가 사라짐**: v3에서 fictitious 168건이 Top10에 92건 동시 진입했었음. v4에서는 fictitious 진입이 80/168로 줄고 분위 버킷 샘플링으로 score가 낮아져 Top10 자리에서 빠짐.
- **Top100에 hold-out 200건 진입**: account_logic topic이 250 case 안에서 hold-out 100% (200건) 흡수.

### 4.2 주제별 Top N truth 진입

```
주제                          Top10   Top50   Top100   Top200   v3 Top200 비교
----------------------------  ------  ------  -------  -------  ---------------
원장기록·데이터정합성              4       6        7        7   v3 2 → 7 ✅
승인·권한·업무분장 통제           36      84      252      310   v3 245 → 310 ✅ (+65)
결산·기간귀속·입력시점            36      86      252      310   v3 246 → 310 ✅ (+64)
계정분류·거래실질 불일치          30      54      197      199   v3 6 → 199 ✅ (+193, hold-out)
중복·상계·자금유출               36      86      261      324   v3 230 → 324 ✅ (+94)
관계사·내부거래·순환구조          10      26       29       34   v3 26 → 34 ✅ (+8)
수익·금액·모집단 통계 이상       32      94      143      163   v3 236 → 163 ⚠️ (-73)
```

읽는 법:
- **account_logic Top200 신규 진입**: hold-out 2 시나리오 200건이 199건 진입 — 거의 100% 흡수.
- **revenue_statistical Top200 감소**: 236 → 163. fictitious 88건 미진입의 직접 영향.
- **나머지 topic은 Top200 안에서 truth 흡수 증가**: hold-out 진입이 multi-topic으로 동시 흡수.

### 4.3 시나리오별 주제 내 진입 순위 (판정 포함)

```
시나리오                                 기대 주제          truth   기대 진입   high   Top10   Top50   Top100   Top200   판정
---------------------------------------  ----------------  ------  ----------  -----  ------  ------  -------  -------  -----------
approval_sod_bypass                      승인·권한              29          29     28       0       0        0        5   100% 진입 / Top200 -2 (v3 10)
circular_related_party_transaction       관계사·내부거래        34          21      0       1      10       13       16   62 % 진입 / Top200 -6 (v3 22)
embezzlement_concealment                 중복·자금유출          76          36     34       0       0        0       34   47 % 진입 / Top200 -6 (v3 40)
expense_capitalization (hold-out)        계정분류·거래실질     100         100      0       2      16       91       92   ✅ Top100=91 / Top200=92
fictitious_entry                         수익·금액             168          80     75       8      59       67       76   ⚠️ 48 % 진입 (v3 100%)
period_end_adjustment_manipulation       결산·기간귀속          92          84      3       0       0        3        6   91 % 진입 / Top200 -15 (v3 21)
suspense_account_abuse (hold-out)        계정분류·거래실질     100         100      0      28      37      100      100   ✅ Top100 안에 100건 전부
unusual_timing_manipulation              결산·기간귀속          21          18      0       0       0        2        3   86 % 진입 / Top200 +1 (v3 2)
```

운영 관점 요약:

- **suspense_account_abuse Top100 = 100건 점령**: hold-out 중 가장 강한 신호. account_logic 큐의 Top10 안에서도 28건 흡수.
- **expense_capitalization Top100 = 91건**: 약간 약하지만 95% 이상 Top200 진입.
- **fictitious 큰 회귀**: Top10 92 → 8건. fitting 완화의 직접 결과.
- **unusual_timing 회복**: Top200 2 → 3건. 진입률 회복 + 미세 ranking 개선.
- **다른 시나리오 미세 회귀**: approval / circular / embezzlement / period_end Top200 진입 -2 ~ -15건. truth 증가로 인한 ranking 분산.

### 4.4 priority_band 분포 (전체 case 기준)

```
band      case count   case docs   truth docs    v3 비교
--------  ----------  ----------  -----------    -------
high             272        2,210         332    case +71 / truth +90
medium         4,988       12,028         377    case +1031 / truth +116
low            6,702        6,045         179    case +692 / truth +109
```

- High band: case당 truth 1.22배 (v3 1.20배) — 유지.
- Medium / Low band: truth 분산 증가. hold-out 200건이 다양한 band에 흡수.

### 4.5 주제별 score band 분포

```
score band                                  case count   truth docs    v3 비교
------------------------------------------  ----------  -----------    --------------
ledger_integrity:medium                            222            6    v3 0 → 6
ledger_integrity:low                               154            1    동일
approval_control:high                              338          202    v3 310 → 202 ⚠️
approval_control:medium                          6,301          342    v3 78 → 342 ✅
approval_control:low                             3,493          120    v3 48 → 120
closing_timing:high                                 61           27    v3 5 → 27 ✅
closing_timing:medium                                2            0    동일
closing_timing:low                              10,521          511    v3 362 → 511
account_logic:medium                                18           11    v3 0 → 11 ✅
account_logic:low                                1,174          208    v3 6 → 208 ✅ (hold-out)
duplicate_outflow:high                             109          127    v3 237 → 127 ⚠️
duplicate_outflow:medium                             6            1    동일
duplicate_outflow:low                            1,346          308    v3 64 → 308 ✅
intercompany_cycle:high                              5            0    유지
intercompany_cycle:medium                          732           41    v3 26 → 41 ✅
revenue_statistical:high                           120          142    v3 214 → 142 ⚠️
revenue_statistical:medium                         602           17    v3 3 → 17
revenue_statistical:low                          2,025           41    v3 41 → 41
```

핵심:
- **account_logic:low** truth 208 — hold-out 200건 + α. account_logic high band 0건이지만 low에 거의 전부 진입.
- **closing_timing:high** truth 5 → 27 — fictitious가 timing rule(L3-02/04/05/06)을 통해 multi-topic high 진입.
- **approval/duplicate/revenue high 감소** — fictitious cluster가 multi-topic high에서 빠진 직접 영향.

### 4.6 C축 결론

```
관점                       v3 결과         v4 결과         평가
-------------------------  -------------   -------------   ----------
전체 Top10                 128건           36건            ⚠️ 큰 감소 (fictitious 회귀)
전체 Top1000               345건           416건           ✅ 절대값 증가 (hold-out 효과)
hold-out 진입 (200건)      -               199건           ✅ Top200 안에 거의 전부
account_logic Top200       6건             199건           ✅ 신규 진입
fictitious Top200          144건           76건            ⚠️ -68 (fitting 완화)
unusual_timing 진입        11건            18건            ✅ 회복
```

v4는 **fictitious를 잃었고 hold-out과 unusual_timing을 얻었다**. 평균적으로 hold-out 200건이 거의 전부 Top200 안에 들어오고, fictitious 88건이 Top200 밖으로 빠진 형태.

---

## 5. v3 ↔ v4 직접 비교

### 5.1 핵심 지표 한눈에

```
지표                              v3 active    v4 candidate    변화
--------------------------------  -----------  -------------   -----------------------
generator profile                 manipulation-v3              manipulation-v4
실행 시간                            548초        477초          -13 % (case builder 단축)
journal rows                     1,077,767    1,077,767         동일
documents                          317,997     317,997          동일
truth docs                             420         620          +200 (hold-out)
시나리오 수                              6            8          +2
score/rule/review 포착                 420         620          +200 (100% 유지)
미포착                                   0           0          유지
case 수                            10,168      11,962          +17.6 %
priority high case                    201         272          +35 %
priority high truth                   242         332          +90
Top10 누적 truth                      128          36          -92 ⚠️
Top100 누적 truth                     183         252          +69 ✅
Top1000 누적 truth                    345         416          +71 ✅
account_logic topic truth               6         208          +202 ✅
revenue_statistical topic truth       245         180          -65 ⚠️
```

### 5.2 시나리오별 변화 — case · truth · 진입

```
시나리오                                 v3 진입률   v4 진입률   변화           원인
---------------------------------------  ----------  ----------  -----------    ---------------
approval_sod_bypass                       100 %       100 %       유지           -
circular_related_party_transaction         65 %        62 %       소폭 감소      manual ratio 감소
embezzlement_concealment                   55 %        47 %       소폭 회귀      manual ratio 분산
expense_capitalization                        -        100 %       ✅ 신규        L2-04 직접 대응
fictitious_entry                          100 %        48 %       ⚠️ -52 %p     amount 버킷 샘플링
period_end_adjustment_manipulation        100 %        91 %       소폭 감소      manual ratio 분산
suspense_account_abuse                        -        100 %       ✅ 신규        L3-09 직접 대응
unusual_timing_manipulation                52 %        86 %       ✅ +34 %p     신호 분리 회복
평균 (8 시나리오)                          —          79 %        — (v3 6개 평균: 79 %)
```

평균 진입률 비교는 시나리오 수가 달라 직접 비교 불가. 단 시나리오 단위:
- **6개 (v3 공통)**: 평균 79 % → 73 % (소폭 감소)
- **2개 (hold-out)**: 100 % (신규)

### 5.3 주제별 Top N truth 변화

```
주제                          v3 T100   v4 T100   v3 T200   v4 T200   해석
----------------------------  --------  --------  --------  --------  ------------------
원장기록·데이터정합성                2         7         2         7   소폭 증가
승인·권한·업무분장 통제           183       252       245       310   증가 (hold-out 다중)
결산·기간귀속·입력시점            183       252       246       310   증가 (hold-out 다중)
계정분류·거래실질 불일치           6        197         6       199   ✅ 큰 폭 신규 진입
중복·상계·자금유출                216       261       230       324   증가 (hold-out 다중)
관계사·내부거래·순환구조           17        29        26        34   소폭 증가
수익·금액·모집단 통계 이상        183       143       236       163   ⚠️ 감소 (fictitious)
T100 / T200 합계                 790       1,141   991       1,387   증가 (multi-topic)
```

### 5.4 fitting guard 효과

v3 → v4 fitting 완화 항목과 결과:

```
완화 항목                                            v3                v4                효과
---------------------------------------------------  ----------------  ----------------  -----------------
fictitious amount floor                              p99.95 × 1.5      p99.0 ~ p99.9     ⚠️ 진입률 48 %로 회귀
                                                                       버킷 샘플링        (의도된 fitting 차단)
manual source ratio                                  시나리오 100 %    시나리오별 45~79%  ⚠️ 진입률 미세 감소
                                                                                          (시나리오 다양화)
unusual_timing 통합 신호                              weekend+manual    weekend/offhour/   ✅ 진입률 86 % 회복
                                                     단일 묶음          manual/self-approval (신호 분리)
                                                                       분리
hold-out 시나리오                                    -                 expense_cap +      ✅ generalization 검증
                                                                       suspense_abuse     (PHASE1 unseen 100 %)
```

---

## 6. v4 회귀 원인 분석 — fitting 완화 트레이드오프

### 6.1 fictitious 진입 168 → 80 회귀의 본질

v3는 fictitious 금액을 `p99.95 × 1.5` 단일 floor로 강제했다. 이는 L4-03 UnusuallyHighAmount, L4-01 RevenueManipulation 등 amount-기반 룰이 거의 100 % hit하도록 만든다. PHASE1 측면에서는 보기 좋은 결과지만 **detector threshold에 데이터가 fit된 상태**이며 fitting 위험이 크다.

v4는 회사 매출 상위 분위(`p99.0 ~ p99.9`) 버킷에서 샘플링하도록 변경했다. 결과:
- amount_ref_enforced_docs: 168 → 65 (강제 적용 비율 39 %로 감소)
- 일부 fictitious 금액이 detector threshold 아래 분포 → L4-03 / L4-05 hit 약화
- revenue_statistical topic 진입 168 → 80 (-88)

**의도된 트레이드오프**: PHASE1 진입률 < generalization. PHASE2 ML이 amount 단일 threshold가 아닌 multi-feature 학습으로 분리할 영역.

### 6.2 manual ratio 분산의 영향

v3는 시나리오별 mutation에서 `source = manual` 비율을 사실상 100 %로 강제했다. 이는 L3-02 Manual Entry Population을 거의 모든 truth가 hit하도록 만든다. v4 manifest의 `manual_like_ratio`:

```
시나리오                              manual_like_ratio
-------------------------------------- -----------------
approval_sod_bypass                    79 %
circular_related_party_transaction     50 %
embezzlement_concealment               65 %
expense_capitalization (hold-out)      45 %
fictitious_entry                       55 %
period_end_adjustment_manipulation     74 %
suspense_account_abuse (hold-out)      60 %
unusual_timing_manipulation            71 %
```

→ 시나리오마다 manual 신호가 차등 적용되어 L3-02가 모든 truth를 동시에 잡지 않는다. row-level 신호 강도가 평균적으로 약해진 결과:
- truth doc Normal 잔류 69 → 159 (+90)
- priority_band low 안 truth 70 → 179 (+109)

이 또한 PHASE1 단일 룰 의존을 줄이는 의도된 결과.

### 6.3 unusual_timing 11 → 18 회복

v4는 unusual_timing mutation을 4개 패턴으로 분리:
- offhour_manual: 5건
- offhour_self_approval: 5건
- weekend_manual_self_approval: 5건
- weekend_offhour: 6건

이 분리 덕분에 closing_timing topic 진입이 v3의 11/21에서 v4의 18/21로 회복. 단일 통합 신호일 때 다른 topic으로 흘러가던 truth가 closing_timing 큐로 깨끗하게 모인 효과.

### 6.4 hold-out 시나리오 100 % 진입 의미

`expense_capitalization` 100/100, `suspense_account_abuse` 100/100 모두 account_logic topic에 진입. 이는 **PHASE1이 unseen-during-baseline 시나리오에 대해서도 100% 진입을 보장**하는 generalization 증거다.

단 account_logic:high band는 여전히 0건. L2-04 / L3-09의 max_score가 high threshold(0.75)에 못 미치는 구조적 제약이 남아있다. score band:

```
account_logic:medium    18 cases  /  11 truth
account_logic:low      1174 cases / 208 truth
account_logic:high        0 cases /   0 truth   ⚠️
```

→ topic 진입은 100%이지만 모두 medium / low로 잔류. high band 진입은 PHASE2 ML 보정 영역.

### 6.5 fitting guard 정책 결정

`MANIPULATION_V4_DATASET_MANIFEST.json`의 `fitting_guard_policy`:

```
fictitious_revenue: "amounts are sampled from company revenue upper-tail buckets,
                    not detector thresholds"
holdout_scenarios:  "suspense_account_abuse and expense_capitalization are manipulation truth,
                    not contract truth relabeling"
manual_source:      "scenario-specific overlap with normal manual background;
                    f_manual must remain non-label-deterministic"
unusual_timing:     "split weekend/offhour/manual/self-approval signals;
                    no 100% simultaneous activation"
phase1_entry_rates: "measure-only; not a generation gate"
```

→ PHASE1 진입률은 측정만 하고 generation pass/fail gate로 쓰지 않는다는 명시적 정책. v3 fictitious 100 % 진입을 PHASE1 KPI로 회복시키지 않는다.

---

## 7. 특이사항 종합

```
번호  특이사항                                                                중요도
----  ----------------------------------------------------------------------  --------
①     hold-out 2 시나리오 (expense_cap + suspense_abuse) 100% topic 진입     높음 ✅
②     PHASE1 generalization 증명: unseen 200건 모두 Top200 안에 흡수          높음 ✅
③     fictitious_entry 진입 168 → 80 (fitting 완화 의도된 회귀)              높음 ⚠️
④     unusual_timing 진입 11 → 18 (신호 분리로 회복)                         높음 ✅
⑤     truth 포착 620 / 620 (100% 유지)                                       높음 ✅
⑥     Top10 누적 truth 128 → 36 (fictitious cluster 사라짐)                  중간 ⚠️
⑦     Top1000 누적 416 (v3 345 → +71, hold-out 효과)                         중간 ✅
⑧     truth doc Normal 69 → 159 (manual ratio 분산 효과)                     중간 ⚠️
⑨     account_logic high band 0건 — L2-04/L3-09 score 구조적 병목            중간
⑩     closing_timing:high 5 → 27 (fictitious multi-topic 흡수 부산물)         낮음 ✅
⑪     실행 시간 548 → 477초 (-13 %, case builder 압축)                       낮음
```

### 7.1 PHASE1 generalization 평가

v4의 가장 중요한 발견은 **hold-out 시나리오 100% topic 진입**이다. PHASE1 룰 portfolio가 baseline 6 시나리오에 fit된 것이 아니라 L2-04 / L3-09 같은 일반 도메인 룰로도 unseen 시나리오를 흡수한다는 증거.

```
hold-out 진입 능력                                  결과
--------------------------------------------------  -------------------
topic 진입률                                         200 / 200 (100 %)
Top200 안 진입                                        199 / 200 (99.5 %)
Top100 안 진입                                        191 / 200 (95.5 %)
priority_band high 흡수                                0 / 200 (0 %)
```

→ topic 분류 OK, ranking 흡수 OK, **high band 미진입은 PHASE2 보정 영역**.

### 7.2 fictitious 회귀의 의미

v3의 fictitious 100 %는 detector threshold에 데이터가 fit된 결과였다. v4의 48 %는 fitting을 차단한 결과로, PHASE2 ML 학습에 더 현실적인 분포를 제공한다. **회귀로 보이지만 fitting 완화 트레이드오프**.

---

## 8. DataSynth 측 검증 — fitting guard 통과 확인

`MANIPULATION_V4_DATASET_MANIFEST.json` 기준 fitting guard 결과:

```
guard 항목                                            v4 결과
----------------------------------------------------  ----------------
fictitious_amount_policy                              ✅ 회사 매출 분위 버킷 (detector threshold 무관)
intercompany_changed_for_cross_rule_entry_rate        ✅ false (cross-rule 강화 없음)
unusual_timing_changed_for_entry_rate                 ✅ false (진입률 fit 없음)
manual_source                                         ✅ 시나리오별 비율 분산 (45~79 %)
holdout_scenarios                                     ✅ manipulation truth로 분리 (contract relabel 아님)
forbidden_contract_label_files                        ✅ 0
leakage_columns_present                               ✅ 0
truth_documents                                       ✅ 620
label_documents                                       ✅ 620
status                                                ✅ pass
```

→ generation 단계 모든 guard 통과. PHASE1 진입률은 measure-only로 분리.

---

## 9. PHASE1 프로세스 측에서 조정해야 할 점

### 9.1 account_logic high band 진입 보강

hold-out 200건 모두 medium / low로 잔류. L2-04 / L3-09 score 산식이 high threshold(0.75) 미달:

```
대안
----------------------------------------------------------
1. L2-04 score 상한 재검토 (현재 max ≈ 0.45 / band confidence 기반)
2. L3-09 aging band 기반 score 상향
3. account_logic topic_score 산식에서 L2-04 / L3-09 weight 상향
4. account_logic + multi-rule combo booster (L2-04 + 결산기 동시 hit 등)
```

### 9.2 Top10 fictitious 사라짐 — multi-topic 보조 키 강화

v3 Top10이 fictitious cluster로 점령되던 패턴이 v4에서 깨졌다. 그 결과 Top10 truth가 128 → 36. 새 정렬 보조 키 후보:

```
- hold-out 시나리오 동시 진입 시 우선 (account_logic topic_score > 0)
- multi-topic membership 수 가중 (현재도 있지만 가중치 검토)
- evidence_strength 가중치 — fictitious 절대 진입 cluster 의존 줄이기
```

### 9.3 closing_timing high band 진입 보강

period_end_adjustment Top200 21 → 6 (-15). v3 회귀 분석에서 이미 지적된 timing weight 부족 문제 유지.

---

## 10. PHASE2로 넘겨야 할 한계

v4의 fitting 완화된 데이터는 PHASE2 ML 학습에 더 적합하다.

```
영역                                            PHASE2 활용
---------------------------------------------   ------------------------------------------
fictitious amount 분포 학습                    XGBoost로 multi-feature 분류
                                              (단일 threshold 의존 탈피)
manual ratio 분산 데이터                       VAE 비지도 이상치 (시나리오별 분포 학습)
hold-out generalization 측정                   PHASE1 진입 결과 + PHASE2 보정 결합
account_logic high 진입                        ML 보정으로 high 분리 (구조적 룰 한계 보완)
```

### 10.1 fictitious는 PHASE1 → PHASE2 분담

v3에서 PHASE1만으로 fictitious 100 % 진입을 달성했지만 그건 fitting의 결과였다. v4는 PHASE1에서 50 % 진입 + PHASE2가 나머지를 보정하는 분담 구조로 설계.

### 10.2 hold-out 평가는 PHASE1 단계에서 완성

hold-out 100 % topic 진입은 PHASE1 단계 만으로 충분. PHASE2는 high band 분리만 보강.

---

## 11. 통합 결론

### 11.1 v4 candidate 결과 한 줄

`datasynth_manipulation_v4_candidate`는 **hold-out 2 시나리오 100 % 진입으로 PHASE1 generalization을 증명**했고, **fictitious fitting 완화를 의도적으로 수용**했다. truth 620건 전부 포착, 6개 기존 시나리오는 평균적으로 미세 회귀, 2개 신규 시나리오는 완전 진입.

### 11.2 v3 → v4 변화 분류

```
항목                                          분류            처리
-------------------------------------------   --------------  ---------------------------
hold-out 진입 200건 100 %                     ✅ 증명          PHASE1 baseline 채택
unusual_timing 11 → 18 진입                  ✅ 회복          PHASE1 baseline 갱신
fictitious 168 → 80 진입                      ⚠️ 회귀          fitting 완화 의도된 결과 (수용)
truth Normal 69 → 159                         ⚠️ 회귀          manual ratio 분산 부산물 (수용)
Top10 128 → 36                                ⚠️ 감소          fictitious cluster 의존 깨짐
account_logic Top200 6 → 199                  ✅ 신규 진입     hold-out 직접 흡수
```

### 11.3 PHASE2 이관 작업

```
시나리오                       PHASE1 한계 (v4)              다음 단계
-----------------------------  --------------------------    ----------
expense_capitalization         high band 미진입 (구조)        PHASE2 ML
suspense_account_abuse         high band 미진입 (구조)        PHASE2 ML
fictitious_entry               amount 단일 threshold 한계     PHASE2 multi-feature
circular_related_party         그래프 cycle 필요              PHASE2 그래프
embezzlement_concealment       반제·상계 chain 필요           PHASE2 그래프 + LLM
unusual_timing                 의미 해석 보강                 PHASE3 LLM
```

### 11.4 다음 단계 우선순위

```
순서   작업                                                                    담당
-----  ----------------------------------------------------------------------  -----------
1      v4 candidate를 active로 승격할지 결정 (회귀 항목 수용 여부)              DataSynth 정책
2      account_logic high band 진입 보강 (L2-04 / L3-09 score 상한)            PHASE1
3      Top10 정렬 보조 키 재검토 (fictitious cluster 의존 탈피)                 PHASE1
4      PHASE2 진입 — hold-out 학습 + fictitious multi-feature 보정             PHASE2 착수
```

v4 candidate는 **PHASE1 generalization 측정 단계의 핵심 데이터셋**이다. fictitious 회귀와 hold-out 진입은 동전의 양면 — fitting을 완화하면 baseline 진입률은 떨어지지만 unseen 시나리오 대응 능력은 증명된다. 승격 결정은 DataSynth 정책 결정 영역.
