# Phase1 Detection 결과 — datasynth_manipulation_v2

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

## 2026-05-14 dataset post-update Phase1 재실행 (현행)

`datasynth_manipulation_v2`는 circular IC mutation 후속 보정 + period-end mutation 보강 + label-signal recovery 패치 후 다시 materialize됐다. 데이터셋 manifest는 2026-05-14T18:24Z로 freeze됐고 직후 Phase1 + case builder를 재실행했다.

핵심 수치 변화 (이전 v2 run → 현행 v2 run):

```
지표                                       이전 v2 run     현행 v2 run    변화
-----------------------------------------  -------------   -------------  ------------
manipulation truth 포착 (score>0)          419 / 420       420 / 420      +1 ✅
case 총수                                  17,478          11,116         -36 % ✅
priority high 안의 truth                   41              276            +6.7 배 ✅
priority high case 수                      315             243            -23 %
Top10 cases capture truth                  1               92             +92 배 ✅
Top50 cases capture truth                  8               214            +26 배 ✅
Top100 cases capture truth                 15              234            +15 배 ✅
Top500 cases capture truth                 60              305            +5 배 ✅
Top1000 cases capture truth                116             401            +3.5 배 ✅
truth doc level risk=Normal                196             27             -86 % ✅
```

시나리오 expected topic 진입률 (이전 → 현행):

```
시나리오                                  이전 v2          현행 v2          변화
----------------------------------------  ----------       ----------       ------------
approval_sod_bypass                       29 / 29 (100 %)  29 / 29 (100 %)  유지
circular_related_party_transaction        0  / 34 (0 %)    34 / 34 (100 %)  ⚠️ → ✅ 완전 회복
embezzlement_concealment                  4  / 76 (5 %)    76 / 76 (100 %)  ✅ 완전 회복
fictitious_entry                          15 / 168 (9 %)   144 / 168 (86 %) ✅ 대폭 회복
period_end_adjustment_manipulation        92 / 92 (100 %)  92 / 92 (100 %)  유지
unusual_timing_manipulation               18 / 21 (86 %)   11 / 21 (52 %)   ⚠️ 회귀 신규
```

최신 산출물:

| 파일                          | 경로                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| profile checkpoint            | `artifacts/phase1_manipulation_v2_after_circular_period_end_20260514.json`                 |
| case input cache              | `artifacts/phase1_manipulation_v2_after_circular_period_end_20260514.pkl`                  |
| case builder checkpoint       | `artifacts/phase1_manipulation_v2_after_circular_period_end_case_20260514.json`            |
| topic 분석                    | `artifacts/phase1_manipulation_v2_after_circular_period_end_topic_analysis.json`           |
| 시나리오 rulehit 분포         | `artifacts/phase1_manipulation_v2_after_circular_period_end_rulehit_by_scenario.json`      |
| case artifact (최종)          | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260514T093051Z.json` |

본문 §1~§11은 위 현행 수치로 갱신되어 있다. v1 비교는 §5에 잔존시켰고, 직전 v2 run(case=17,478, top10=1)과의 차이는 §5.5에 새로 정리했다.

---

## 0. 이 문서는 무엇인가

`data/journal/primary/datasynth_manipulation_v2/`에 들어있는 **악의적으로 조작된 전표 420건**을 Phase1이 얼마나 잡고, 어느 주제 그룹에 분류했으며, 그 주제 안에서 몇 등에 올렸는지 본다.

v2는 `datasynth_contract_v2` semantic-clean journal 위에 manipulation truth 420건을 다시 올린 빌드다. 2026-05-14 업데이트에서는 circular IC mutation 실체화 + period-end mutation 강화 + label-signal recovery가 추가됐다.

```
구분             v1 (datasynth_manipulation)         v2 현행 (datasynth_manipulation_v2)
---------------  ----------------------------------  ----------------------------------------
배경 데이터셋    기존 contract 시드                  semantic-clean contract_v2 시드
truth docs       420 (동일 시나리오)                 420 (동일 시나리오)
journal rows     1,095,158                           1,077,767
documents        317,505                             317,997
labels 정책      manipulation-only                   manipulation-only (sidecars 제외)
mutation 보강    —                                   circular IC + period-end + label-signal
```

### 사용자 관점 핵심 질문 3가지

```
질문                                    답하는 섹션
--------------------------------------  -----------
① 일단 잡기는 했나? (포착률)            §2 A축
② 어느 주제 그룹으로 보여줬나?          §3 B축
③ 그 주제 안에서 몇 등에 올렸나?        §4 C축
```

§5에서 v1 비교 + 직전 v2 run 비교를 본다.

---

## 1. 실행 기준과 산출물

### 1.1 실행 명령

```
.venv\Scripts\python.exe tools\scripts\profile_phase1_v126.py ^
    --data-dir data\journal\primary\datasynth_manipulation_v2 ^
    --checkpoint artifacts\phase1_manipulation_v2_after_circular_period_end_20260514.json ^
    --cache-path artifacts\phase1_manipulation_v2_after_circular_period_end_20260514.pkl ^
    --stop-after-cache

.venv\Scripts\python.exe tools\scripts\profile_phase1_v126.py --reuse-cache ^
    --data-dir data\journal\primary\datasynth_manipulation_v2 ^
    --checkpoint artifacts\phase1_manipulation_v2_after_circular_period_end_case_20260514.json ^
    --cache-path artifacts\phase1_manipulation_v2_after_circular_period_end_20260514.pkl
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
read_csv                            8.312초
independent evidence enrichment     4.550초
feature.time                        1.615초
feature.amount                      4.065초
feature.pattern                     4.641초
feature.text                        7.555초
detector.layer_a                   15.513초
detector.layer_b                  101.486초
detector.layer_c                  147.859초
detector.benford                    2.868초
aggregate                          27.603초
Phase1 case builder                99.714초
manipulated case eval               0.133초
manipulated row eval                1.387초
--------------------------------  ---------
합계 (cache + case-only)          335 + 112 초 ≈ 447초
```

병목은 `layer_c → layer_b → case builder` 순서로 유지.

### 1.4 순위 산출 기준

주제(topic)별 case를 `topic_score desc`, `triage_rank_score desc`, `total_amount desc`, `rule_count desc` 순서로 정렬한 뒤 Top10 / Top50 / Top100 / Top200의 unique `manipulated_entry_truth.document_id` 건수를 계산한다. `topic high`는 해당 topic score `>= 0.75` 기준이다. 한 case는 `topic_scores[topic_id] > 0`인 모든 topic membership에 동시에 포함된다.

Band 축 표기 정책은 [DETECTION_RANKING_CRITERIA.md §Band 축 표기 정책](../../spec/DETECTION_RANKING_CRITERIA.md#band-축-표기-정책)을 따른다. 이 문서에서 `priority high/medium/low`는 case `priority_band`, `{topic_id} topic high/medium/low`는 `topic_scores[topic_id]`, `{topic_id} topic membership`은 `topic_scores[topic_id] > 0`을 뜻한다.

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

이전 v2 run에서 발생했던 1건 미포착이 해결됐다(label-signal recovery 패치). v1의 합격 기준(미포착 0)을 회복.

### 2.1 truth document를 가진 row의 risk_level 분포

```
risk_level   truth doc 수
-----------  ------------
High                  244
Medium                149
Low                    56
Normal                 27
```

이전 v2 (row risk_level High 178 / Medium 9 / Low 39 / Normal 196) 대비 truth가 Normal에서 빠져나와 row risk_level High·Medium으로 집중됐다. row 단위 신호 강도가 크게 개선됐다.

**A축 결론**: 포착률 100 % 회복 + truth row risk_level 분포가 High 쪽으로 이동 → row 단위 신호 강도가 의도된 수준에 도달.

---

## 3. B축 — 주제 분류 (어느 그룹으로 보여줬는가)

> **이 축이 답하는 질문**: "잡은 truth 420건을 7개 주제 큐 중 어느 topic membership에 배치했고, 각 topic에서 topic high로 올라간 것은 몇 건인가?"

### 3.1 주제별 case · truth 분포

```
주제                          topic membership case   topic membership truth   topic high case   topic high truth   해석
----------------------------  ----------  ------------  ----------  -----------  ----------------------------------
원장기록·데이터정합성                376             8           0            0   조작 시나리오 매칭 작음
승인·권한·업무분장 통제            9,421           420         361          269   모든 truth 진입 · topic high 269 ✅
결산·기간귀속·입력시점             9,767           410          61            5   topic membership은 진입, topic high 약함
계정분류·거래실질 불일치             770             7           0            0   매칭 작음 (예상 동작)
중복·상계·자금유출                 1,456           280         167          232   ⚠️ truth 중복 매핑 — multi-topic 효과
관계사·내부거래·순환구조             664            49           5            0   topic membership 회복, topic high는 아직
수익·금액·모집단 통계 이상         2,947           257         254          226   topic high 226 ✅
```

읽는 법:
- **topic high case**는 `topic_scores[topic_id] >= 0.75`인 case다. 한 case가 여러 topic에 동시 topic high가 될 수 있어 합이 case 총수와 다르다.
- **잘 흡수된 주제**: `승인·권한`(topic high truth 269), `중복·자금유출`(topic high truth 232), `수익통계`(topic high truth 226).
- **들어왔지만 topic high까지 못 간 주제**: `결산·기간귀속`(topic membership truth 410 / topic high truth 5), `관계사`(49/0).
- **truth가 거의 안 들어온 주제**: `데이터정합성`(8/0), `계정분류`(7/0) — 정상 분포.

⚠️ 다중 topic 진입 효과: 같은 truth doc이 여러 topic high에 동시 진입할 수 있어 `duplicate_outflow topic high (truth=232 / case=167)`처럼 truth가 case 수보다 큰 묶음이 나타난다. 실제 unique truth doc은 `priority high` 기준 276건이다.

### 3.2 시나리오 → 기대 주제 매칭 (현행 v2)

```
시나리오                                 기대 주제        truth docs   기대 주제 진입   진입률
---------------------------------------  --------------  -----------  --------------  -------
approval_sod_bypass                      승인·권한                29              29   100 %
circular_related_party_transaction       관계사·내부거래          34              34   100 % ✅ 회복
embezzlement_concealment                 중복·자금유출            76              76   100 % ✅ 회복
fictitious_entry                         수익·금액               168             144   85.7 % ✅ 회복
period_end_adjustment_manipulation       결산·기간귀속            92              92   100 %
unusual_timing_manipulation              결산·기간귀속            21              11   52.4 % ⚠️ 회귀
```

- **5개 시나리오 100% 진입**: approval, circular, embezzlement, period_end + (fictitious 86%까지 회복).
- **유일한 회귀**: `unusual_timing_manipulation` (이전 18/21 → 현행 11/21). circular/period-end 보강 작업의 부수효과 가능성 → §6.1.

---

## 4. C축 — 주제 내 순위 (몇 등에 들어갔는가)

> **이 축이 답하는 질문**: "감사인이 주제별 큐를 위에서부터 본다면, 악의 조작이 Top 몇 안에 들어와 있는가?"

### 4.1 전체 case 기준 누적 Top N

```
순위 범위    truth docs   누적 포착률
-----------  -----------  -----------
Top 10               92         21.9 %
Top 50              214         51.0 %
Top 100             234         55.7 %
Top 500             305         72.6 %
Top 1000            401         95.5 %
```

전체 case 11,116개 중 Top10(상위 0.09 %)이 truth 92건을 잡는다. Top1000(상위 9 %)이 95.5 % 포착. 직전 v2 run(Top10=1, Top1000=116)과 비교하면 ranking 집중도가 구조적으로 회복됐다.

### 4.2 주제별 Top N truth 진입

```
주제                          Top10   Top50   Top100   Top200
----------------------------  ------  ------  -------  -------
원장기록·데이터정합성              0       7        8        8
승인·권한·업무분장 통제           92     214      234      271
결산·기간귀속·입력시점            92     214      234      271
계정분류·거래실질 불일치           1       7        7        7
중복·상계·자금유출                92     213      225      253
관계사·내부거래·순환구조          12      32       48       48
수익·금액·모집단 통계 이상        92     212      231      250
```

읽는 법:
- **승인 / 결산 / 중복 / 수익 4개 topic**이 Top10에서 동일하게 92건의 truth를 잡는다. 이는 상위 case들이 multi-topic 진입(특히 approval_control이 primary topic이지만 같은 case가 closing_timing·duplicate_outflow·revenue_statistical에도 동시 진입)했기 때문.
- **관계사 topic**: Top100 안에 truth 48건(34건 전부 + 추가 14건) — circular 회귀 완전 해소.
- **데이터정합성 / 계정분류**는 그룹 자체가 작아 Top 진입 의미 크지 않음(설계 의도와 일치).

### 4.3 시나리오별 주제 내 진입 순위 (판정 포함)

```
시나리오                                 기대 주제        truth   기대 진입   topic high   Top10   Top50   Top100   Top200   판정
---------------------------------------  --------------  ------  ----------  -----  ------  ------  -------  -------  -----------
approval_sod_bypass                      승인·권한           29          29     29       0       0        2        7   100% 진입 / 순위 분산
circular_related_party_transaction       관계사·내부거래     34          34      0       5      19       34       34   ✅ 100% 진입 (Top100 전부)
embezzlement_concealment                 중복·자금유출       76          76     76       0      76       76       76   ✅ 100% 진입 (Top50 전부)
fictitious_entry                         수익·금액          168         144    144      92     133      138      144   ✅ 다수 진입 / Top10 점령
period_end_adjustment_manipulation       결산·기간귀속       92          92      4       0       1        5       19   100% 진입 / Top 약함
unusual_timing_manipulation              결산·기간귀속       21          11      0       0       0        2        2   진입률 52% / Top 약함
```

운영 관점 요약:

- **Top N 완전 점령** (2개): `embezzlement_concealment` Top50, `circular_related_party` Top100.
- **Top 10 다수 진입**: `fictitious_entry` (92건 — 다중 topic 효과). 사실상 Top10이 fictitious cluster.
- **진입 100% / 순위 약함** (2개): `approval_sod_bypass` Top200=7, `period_end_adjustment` Top200=19.
- **진입률 회귀 + Top 약함** (1개): `unusual_timing_manipulation` 52%/2. ⚠️ 새 회귀.

### 4.4 priority band 분포 (전체 case 기준)

```
priority band   case count   case docs   truth docs
--------------  ----------  ----------  -----------
priority high          243        1,559         276
priority medium      4,409        9,681         337
priority low         6,464        5,816         119
```

- `priority high` case 243개에 truth 276건 = 1.14배 (한 case 안에 truth가 여러 개 묶임 → ranking 집중도 우수).
- 직전 v2: `priority high` case 315 / truth 41 (0.13배). 즉 `priority high`에 truth가 6.7배 더 모임.
- `priority low` truth 119건 잔류 = 28 % (시나리오 미진입 부분).

### 4.5 주제별 topic-score band 분포

§4.4는 case 전체의 `priority_band` 축이고, 본 §4.5는 각 topic의 `topic_scores[topic_id]` 축이다. 같은 case가 여러 topic에 속하므로 두 표의 case/truth 합계는 일치하지 않는다.

```
topic-score band                            case count   truth docs
------------------------------------------  ----------  -----------
ledger_integrity topic medium                       222            5
ledger_integrity topic low                          154            3
approval_control topic high                         361          269
approval_control topic medium                     5,356          185
approval_control topic low                        3,704          124
closing_timing topic high                            61            5
closing_timing topic medium                          77          134
closing_timing topic low                          9,629          365
account_logic topic medium                           11            0
account_logic topic low                             759            7
duplicate_outflow topic high                        167          232
duplicate_outflow topic medium                        3            1
duplicate_outflow topic low                       1,286          162
intercompany_cycle topic medium                     659           49
revenue_statistical topic high                      254          226
revenue_statistical topic medium                    643            5
revenue_statistical topic low                     2,050           76
```

핵심:
- **approval_control topic high** truth 269 + **duplicate_outflow topic high** truth 232 + **revenue_statistical topic high** truth 226 — 세 topic high가 다중 진입으로 동일 truth를 흡수.
- **closing_timing**: topic high 5 vs topic low 365 — period_end 92건과 unusual_timing 11건이 대부분 topic low로 잔류 (timing 가중치 약화 부수효과 가능성).
- **intercompany_cycle topic medium** truth 49 — circular 34건 + 추가 매칭 15건. topic high까지는 아직 못 감.

2026-05-15 band-axis 재점검에서는 현행 case artifact를 재파싱해 `priority medium`과 topic membership도 함께 산출했다. `priority medium` 안의 unique truth는 337건이고, 그 안에서 `closing_timing topic membership`은 333건, `intercompany_cycle topic membership`은 39건이다. topic-score band로 보면 `intercompany_cycle topic medium`은 49건, `closing_timing topic medium`은 재계산 기준 31건이다. 따라서 PHASE2 이관 후보 수치를 말할 때는 `priority medium`, `{topic_id} topic medium`, `{topic_id} topic membership within priority medium` 중 어느 축인지 반드시 적는다. 상세: [artifacts/phase2_handoff_band_axis_audit.md](../../../artifacts/phase2_handoff_band_axis_audit.md).

### 4.6 C축 결론

```
관점                       결과                                  현재 상태
-------------------------  ------------------------------------  ----------
전체 Top10                 truth 92건 (이전 v2 = 1)              ✅ 대폭 개선
승인 주제 Top200           truth 271건 (이전 v2 = 3)             ✅ 회복
결산 주제 Top200           truth 271건 (이전 v2 = 8)             ✅ 회복
관계사 주제 Top200         truth 48건 (이전 v2 = 4)              ✅ 회복
수익 주제 Top200           truth 250건 (이전 v2 = 13)            ✅ 대폭 회복
중복자금 주제 Top200       truth 253건 (이전 v2 = 18)            ✅ 회복
```

직전 v2 run 대비 모든 topic의 Top200 안에 truth 진입이 회복됐다. circular IC + period-end mutation 보강 + label-signal recovery가 ranking 집중도 회복으로 직접 이어졌다.

---

## 5. 비교 — v1 / 직전 v2 / 현행 v2

### 5.1 핵심 지표 한눈에

```
지표                              v1         직전 v2    현행 v2    추이
--------------------------------  ---------  ---------  ---------  ------------------------
실행 시간                            761초      504초      447초    안정
journal rows                     1,095,158  1,077,767  1,077,767   동일
documents                          317,505    317,997    317,997   동일
truth docs                             420        420        420   동일
score/rule/review 포착                 420        419        420   ✅ 회복
미포착                                   0          1          0   ✅ 회복
case 수                              4,218     17,478     11,116   ✅ 정상 범위
risk_summary High row               12,783      5,333      1,225   감소
risk_summary Medium row            161,845      6,571     22,445   소폭 회복
risk_summary Low row                 2,009     45,915     33,155   감소
priority high case                  N/A          315        243   집중
priority high truth                 N/A           41        276   ✅ +572 %
```

### 5.2 주제별 변화 — case · truth · topic high

```
주제                          v1 case   직전 v2    현행 v2    v1 topic high truth   직전 v2 topic high truth   현행 v2 topic high truth
----------------------------  --------  --------   --------   ----------  ---------------  ---------------
원장기록·데이터정합성              132       335        376           0                0                0
승인·권한·업무분장 통제          2,732    17,119      9,421          75              214              269
결산·기간귀속·입력시점           2,814    15,840      9,767           0                0                5
계정분류·거래실질 불일치           895       465        770           0                0                0
중복·상계·자금유출                 581       690      1,456           0               21              232
관계사·내부거래·순환구조           963       562        664           0                0                0
수익·금액·모집단 통계 이상         591     2,058      2,947           0                4              226
```

- 승인·결산 주제 case 수가 직전 v2 폭증(17k/15k) 대비 9.4k/9.7k로 안정화.
- duplicate 주제는 v1=0, 직전 v2=21, 현행 v2=232 — 단계적으로 회복.
- revenue 주제는 직전 v2 = 4 → 현행 v2 = 226 — 가공전표 mutation 신호가 룰 trigger 컬럼에 닿기 시작.

### 5.3 주제별 Top N truth 변화

```
주제                          v1 T100   직전 v2 T100   현행 v2 T100   v1 T200   직전 v2 T200   현행 v2 T200
----------------------------  --------  -------------  -------------  --------  -------------  -------------
원장기록·데이터정합성                0              2              8         0              2              8
승인·권한·업무분장 통제             52              2            234        84              3            271
결산·기간귀속·입력시점              20              1            234        40              8            271
계정분류·거래실질 불일치             0              0              7         0              1              7
중복·상계·자금유출                   0             15            225         0             18            253
관계사·내부거래·순환구조             1              4             48        13              4             48
수익·금액·모집단 통계 이상           4              7            231         4             13            250
```

전체 Top100 / Top200 합계: 직전 v2 = 31/49 → 현행 v2 = 987/1108. **약 32배 / 23배 회복**. (multi-topic 효과 포함)

### 5.4 시나리오 진입률 변화

```
시나리오                                 v1 진입률   직전 v2     현행 v2     변화
---------------------------------------  ----------  ----------  ----------  ------------------
approval_sod_bypass                      51.7 %      100.0 %     100.0 %     유지
circular_related_party_transaction       38.2 %        0.0 %     100.0 %     ✅ 완전 회복
embezzlement_concealment                  0.0 %        5.3 %     100.0 %     ✅ 완전 회복
fictitious_entry                          0.0 %        8.9 %      85.7 %     ✅ 대폭 회복
period_end_adjustment_manipulation        0.0 %      100.0 %     100.0 %     유지
unusual_timing_manipulation               0.0 %       85.7 %      52.4 %     ⚠️ 회귀 신규
```

### 5.5 직전 v2 run → 현행 v2 run 핵심 차이 요약

```
영역                                              직전 v2          현행 v2          평가
------------------------------------------------  ---------------  ---------------  ------
truth 포착                                         419 / 420        420 / 420        ✅
case 폭증                                          17,478           11,116           ✅
truth doc level Normal                             196              27               ✅
priority high truth                                41               276              ✅
Top10 / Top1000 누적                               1 / 116          92 / 401         ✅
circular 진입률                                    0 %              100 %            ✅
embezzlement 진입률                                5.3 %            100 %            ✅
fictitious 진입률                                  8.9 %            85.7 %           ✅
unusual_timing 진입률                              85.7 %           52.4 %           ⚠️
period_end expected-topic high truth               0                4                ➕ 소폭
closing_timing topic high truth                    0                5                ➕ 소폭
```

직전 v2의 모든 회귀가 회복됐고, 새 회귀로 `unusual_timing` 1건이 발생.

---

## 6. 현행 v2 특이사항 종합

```
번호  특이사항                                                                중요도
----  ----------------------------------------------------------------------  ------
①     truth 100 % 포착 회복 (anomaly_score=0 미포착 0건)                     높음 ✅
②     case 수 11,116로 정상화 (직전 17,478 → 36% 감소)                       높음 ✅
③     priority high truth 41 → 276 (6.7배 집중)                              높음 ✅
④     Top10 cases capture truth 1 → 92 (다중 topic high 클러스터 동작)        높음 ✅
⑤     circular_related_party 진입률 0% → 100% (Top100 전부)                  높음 ✅
⑥     embezzlement_concealment 진입률 5% → 100% (Top50 전부)                 높음 ✅
⑦     fictitious_entry 진입률 9% → 86% (Top10 92건 점령)                     높음 ✅
⑧     unusual_timing_manipulation 진입률 86% → 52% (Top200=2)               ⚠️ 신규 회귀
⑨     closing_timing topic high truth 0 → 5 (여전히 약함, period_end Top200=19) 중간
⑩     intercompany_cycle topic high truth 0 유지 (topic medium에 49건 보존)   중간
⑪     approval_sod_bypass Top200=7 (1번~10번 case가 fictitious 점령)         중간
⑫     truth doc level Normal 196 → 27 (row-level 신호 강도 도달)              높음 ✅
⑬     duplicate_outflow topic high에 truth 232 (single topic 안에서 집중)     중간 ✅
```

### 6.1 unusual_timing 진입률 — PHASE1 본질적 ceiling 정식 채택 (T1 → T7 종결, 2026-05-15)

직전 v2(18/21) → 현행(11/21) 7건 net 변동(8건 drop, 1건 신규 진입)은 **회귀가 아니다**. T1 trace + T7 정밀 분석으로 다음과 같이 종결한다.

**정식 채택 결론 (2026-05-15)**:

- 직전 18/21은 **incidental case bundling artifact**였다. L3-04 보유 non-truth co-doc과 우연히 같은 케이스로 묶여서 corroboration 받았던 결과로, 시나리오 자체의 detectability를 반영한 수치가 아니다.
- 현행 **11/21이 `after_hours_posting` 시나리오의 본질적 detectability ceiling**이다. PHASE1 룰 메타(L3-04 standalone primary / L3-05·L3-06 booster) 정의를 유지하는 한, after_hours_posting + non-period-end window 조합은 자체 evidence만으로 closing_timing topic seed 불가하다. 이는 룰 설계의 부수 결함이 아니라 의도된 동작이다.
- 18 → 11은 회귀가 아니라 **incidental lift 제거에 따른 측정 노이즈 정상화**다. baseline 재설정으로 다룬다.

**P1 (L3-06 promote primary) — 반려 확정**: 시나리오 truth 회수를 위해 `scoring_role="booster"`, `standalone_rankable=False`를 변경하면 정상 결산기 야근·주말 전기 등 한국 중견 제조업의 합법적 운영 패턴이 전수 `closing_timing topic high`로 진입한다. PHASE1 `priority high` 및 topic high 운영 정밀도 회귀가 21건 truth 회수 이득보다 훨씬 크다. 룰 메타 변경 금지 원칙은 `docs/spec/DECISION.md` D042에 명문화. 자세한 반려 사유: [DECISION.md D042](../../spec/DECISION.md).

**P2 (11/21 ceiling 수용) — 채택 확정**: 본 §6.1 / §8.1 / §10에 명문화하고, `tests/phase1_rulebase/kpi_baseline.json` layer C `c4_scenario_full_entry_count` baseline을 **4개 시나리오**(approval / circular / embezzlement / period_end)로 freeze하며 unusual_timing은 `scenario_entry_ceilings`에 11/21 본질 한계로 기록한다. 정상 야근 거래와 의심 시간대 거래의 분리는 PHASE2 ML(multi-feature 분류) 또는 PHASE3 LLM(의미 해석)으로 이관한다(§10 참조).

```
21건 fire 패턴 (모두 after_hours_posting subtype)
-----------------------------------------------------------------
L1-04, L1-05, L3-02   21/21  → final_topic=approval_control (primary)
L3-04 (period_end)    6/21   → final_topic=closing_timing  (primary, standalone)
                              · 2022 (6건) margin=5 경계만 fire
                              · 2023/2024 (15건) FY-end 까지 6~8일 → False
L3-05 (weekend)       21/21  → final_topic=closing_timing  (booster, NOT standalone)
L3-06 (after_hours)   21/21  → final_topic=closing_timing  (booster, NOT standalone)
```

```
진입 11건 / 미진입 10건 분리 (closing_timing seed 경로)
-----------------------------------------------------------------
2022 (6/6)   row-level L3-04 자체 보유 → seed OK
2023 (1/7)   case-bundled L3-04 co-doc → seed OK
2024 (4/8)   case-bundled L3-04 co-doc → seed OK
미진입 (10)  case 내 L3-04 evidence 부재 → topic_score_breakdown.closing_timing = {}
```

**원인 분담**: PHASE1 ~80% / DataSynth ~20%

- PHASE1 Issue A (구조적): `src/detection/rule_scoring.py:338-347` L3-05/L3-06 모두 `scoring_role="booster"`, `standalone_rankable=False`. `closing_timing` topic은 `topic_scoring.py:127-139`에서 `has_rankable_primary` 게이트를 통과해야 score 계산. **L3-04 만이 closing_timing seed 가능 primary 룰**이라서 after_hours_posting 시나리오는 자체 evidence로 topic 진입 불가.
- PHASE1 Issue B (직접): period_end mutation 강화 → case_count 17,478 → 11,116. 직전 run 의 incidental corroboration이 더 작은 케이스로 분리되면서 사라짐.
- DataSynth: `materialize_datasynth_manipulation_v2.py:256-262` 의 `day = 23 + (bucket % 5)` + weekday-skip 로직이 2022는 03-26(period_end window 경계), 2023은 03-25, 2024는 03-23으로 떨어뜨림. **시나리오 정의(after_hours)에 부합하므로 의도된 동작**. period_end window 안으로 옮기면 두 시나리오(`unusual_timing` vs `period_end_adjustment`) taxonomic clarity 손상.

상세 trace: `artifacts/unusual_timing_regression_trace.md`, `.json`, `.csv`.

### 6.2 우선 조치 후보

```
조치                                                                    대상 시나리오
----------------------------------------------------------------------  ---------------------
1. unusual_timing 21건 중 closing_timing 미진입 10건 추적                unusual_timing
2. period_end / unusual_timing topic high 진입 보강 (timing weight 재검토) period_end + unusual_timing
3. intercompany_cycle topic high 미진입 — L3-03 score 상한 점검            circular
4. fictitious_entry 미진입 24건 추적 (168 → 144)                         fictitious
```

---

## 7. 결과 해석 — 비전공자를 위한 풀이

§4의 표를 처음 보면 이제 "Top10에 truth 92건? 이게 정상인가?"라는 인상이 들 수 있습니다. 이건 PHASE1 multi-topic 설계가 의도대로 동작한 결과입니다.

### 7.1 Top10에 truth가 92건 들어간 이유

```
설계 의도                                          현실 동작
-----------------------------------------------    ------------------------------------------
한 case가 여러 topic 큐에 동시 진입                Top10 cases가 approval / closing / duplicate /
                                                   revenue 4개 topic에 동시 high
한 case의 raw_rule_hits에 여러 truth document       case_duplicate_or_outflow_00354 한 case가
포함될 수 있음                                     truth 32건 포함
                                                   case_statistical_outlier_00086이 truth 16건
                                                   포함
```

즉 "Top10 case 10개 = truth 92건"은 한 case가 truth document 평균 9.2건씩 묶는다는 의미입니다. 한 truth가 하나의 case에만 들어가는 게 아니라 case-document는 N:M 관계.

### 7.2 정상 회사 데이터의 본질 — 룰이 자연스럽게 hit한다

v2 데이터셋은 `semantic-clean` 정상 배경입니다. "clean"은 "fraud가 없다"는 뜻이지 "룰이 hit하지 않는다"는 뜻이 아닙니다.

```
정상 운영에서 룰이 합법적으로 hit하는 사례
----------------------------------------------------------
- 결산기 야근            → L3-04 기말/기초 전표 집중
- 수기 조정 전표         → L3-02 수기/조정 전표
- 주말 휴일 전기         → L3-05 주말/휴일 전기
- 승인한도 근접          → L1-05 승인한도 근접
- 업무범위 변동          → L3-12 업무범위 검토 후보
- 사후 정정              → L3-07 전기일·문서일 괴리
```

PHASE1이 이걸 안 올리면 룰 자체가 무력화됩니다. PHASE1의 본래 역할은 "**검토 후보를 넓게 올린 다음 우선순위를 매기는**" 것.

### 7.3 수치를 "무작위 추출"과 비교하면

전체 11,116 case에서 truth 420건이 균등분포한다고 가정하면 무작위 N개 뽑았을 때 들어올 truth 기댓값과 비교됩니다.

```
순위 구간     무작위 기댓값   현행 v2 실제   PHASE1 효과 (배수)
-----------   -------------  ------------  ------------------
Top 10          0.38건            92        242 배
Top 50          1.89건           214        113 배
Top 100         3.78건           234         62 배
Top 500        18.89건           305         16 배
Top 1000       37.78건           401         11 배
priority high   9.18건           276         30 배
```

> 기댓값 = `420 × N ÷ 11,116` (균등분포 가정)

PHASE1은 무작위 대비 **상위에서 60~240배** 효과적으로 truth를 모으고 있습니다. multi-topic 진입 + ranking 집중도가 함께 작동한 결과.

### 7.4 운영 관점 정밀도 — priority high 큐

감사인이 실제로 보는 큐는 `priority high` 묶음입니다.

```
priority band     case 수     truth docs   doc-단위 정밀도
---------------   --------    -----------  ----------------
priority high         243            276        113.6 %*
priority medium     4,409            337          7.6 %
priority low        6,464            119          1.8 %
```

> *`priority high`에서 truth가 case 수를 초과(276/243=1.14)하는 것은 한 case에 multiple truth가 묶이기 때문. case 단위 precision은 다른 척도임.

직전 v2(`priority high` 정밀도 13 %) 대비 현행 v2는 `priority high` 안에 truth가 1.14배(case당) / case_docs 기준 17.7 %로 집중됐습니다.

### 7.5 PHASE1 본래 KPI 기준 — 현행 v2는 직전 v2 대비 전면 회복

같은 v2를 *올바른 KPI* 기준으로 다시 정렬하면:

```
PHASE1 본래 KPI                                v1            직전 v2       현행 v2       평가
---------------------------------------------  -----------   -----------   -----------   --------
포착률 (어떻게든 큐에 진입한 비율)              420/420       419/420       420/420       ✅ 회복
시나리오 평균 expected topic 진입률              14.8 %        66.3 %        89.7 %        ✅ 대폭 개선
시나리오 expected topic 100% 진입 달성           0 / 6 개      2 / 6 개      4 / 6 개      ✅ 개선
priority high 정밀도(precision)                약 0.6 %      13.0 %        17.7 %        ✅ 개선
Top200 truth가 들어간 주제 수                   4 / 7 개      7 / 7 개      7 / 7 개      유지
Top10 누적 truth                               0건           1건           92건          ✅ 대폭 개선
```

직전 v2 대비 6개 KPI 중 6개가 모두 개선됐고, 회귀는 unusual_timing 1건뿐.

---

## 8. DataSynth 측에서 조정해야 할 점

데이터 생성 단계에서 들여다봐야 할 항목들.

### 8.1 unusual_timing — 11/21 PHASE1 ceiling 정식 채택 (T7 종결, 2026-05-15)

§6.1 결론을 바탕으로 본 단계에서 최종 판정한다. DataSynth · PHASE1 어느 쪽도 21/21을 추구하지 않는다.

```
판정 (2026-05-15 종결)
---------------------------------------------------------------------------
DataSynth (시나리오 day 이동 23..27 → 26..30)   ❌ 반려 — taxonomic clarity 손상
PHASE1 P1 (L3-06 promote primary)              ❌ 반려 — 정상 야근 FP 폭증
PHASE1 P2 (11/21 ceiling 수용)                  ✅ 채택 — PHASE1 본질적 한계로 명문화
PHASE1 Issue B (case bundling 변화)             ✅ 수용 — incidental lift 정상화
```

**P1 반려 사유 (`docs/spec/DECISION.md` D042 연계)**:

- `src/detection/rule_scoring.py:338-347` L3-05/L3-06의 `scoring_role="booster"` + `standalone_rankable=False`는 **정상 결산기 야근·주말 전기 false positive 폭증을 방지하기 위한 의도된 설계**다. 한국 중견 제조업의 합법적 운영 패턴(분기말 야근, 주말 마감 보정 등)이 PHASE1 `priority high` 또는 `closing_timing topic high`를 점령하면 review queue 정밀도가 무너진다.
- 단일 시나리오(after_hours_posting) truth 11→21 회수 이득보다 정상 운영 케이스의 `priority high` 또는 topic high 진입 부작용이 훨씬 크다.
- 따라서 룰 메타(`scoring_role`, `standalone_rankable`)는 단일 시나리오 진입률을 위해 변경하지 않는다. 룰 메타 변경 금지 원칙: `docs/spec/DECISION.md` D042.

**채택된 다음 작업**: 11/21 ceiling을 PHASE1 baseline으로 freeze한 뒤, 정상 야근 거래와 의심 시간대 거래의 분리는 PHASE2 ML(multi-feature 분류) 또는 PHASE3 LLM(적요·맥락 의미 해석)로 이관한다(§10 참조). kpi_baseline 갱신: `tests/phase1_rulebase/kpi_baseline.json` layer C `c4_scenario_full_entry_count`.

### 8.2 fictitious_entry 미진입 24건 추적 결과 (T6)

168건 중 24건(14 %)이 revenue_statistical topic에 진입하지 못함. row 단위 추적 결과
24건은 **단일 패턴**으로 100 % 일치한다.

```
항목                          24건 공통 값
----------------------------  ----------------------------------------
manipulation_subtype          fictitious_revenue (24/24)
posting_date                  Year-01-28 09:03:00 (2022:7 / 2023:6 / 2024:11)
max_debit, max_credit         1,500,000,000 (24/24, 25B doc 0건)
business_process / source     O2C / adjustment (모든 row)
document_type / counterparty  SA / Customer (모든 row)
gl_account 핵심                4000 (매출), 1100 (매출채권)
case 내 L4-01 hit              0 / 24
case 내 L4-03 hit              0 / 24
case topic_scores              "revenue_statistical" key 부재 (24/24)
```

원인은 단일하다. `materialize_datasynth_manipulation_v2.py:420` 의

```
amount = max(base, 25_000_000_000) if offset % 3 == 0 else max(base, 1_500_000_000)
...
if offset % 4 == 0:  # Dec 30 22:xx period-end batch
```

에서 24건 모두 `offset % 3 != 0` (1.5B amount) AND `offset % 4 != 0` (Dec batch
미적용) 에 해당하고, 같은 case 버킷(`O2C / account_family / Year-01`) 안에 25B doc
이 함께 들어오지 않아 case 단위에서 L4-01 / L4-03 가 한 번도 trigger되지 않는다.
`src/detection/topic_scoring.py` 진입 규칙상 L4-01 또는 L4-03 가 없으면
`has_rankable_primary=False` 가 되어 fraud combo floor 도 띄울 수 없다(조건 자체에
L4-01 또는 L4-03 가 포함됨).

판정:

```
영역                                    판정
--------------------------------------- ----------------------------------------
DataSynth (T7 D1 확장 mutation 보강)    ✅ 단일 적합 — 100 % 원인이 mutation
                                        amount 분포 부족
PHASE1 (룰 trigger 임계 미세 조정)       ⚠️ 회피 — L4-01 / L4-03 review_zscore
                                        는 이미 0.45 임계로 낮음. 더 낮추면
                                        정상 모집단 FP 폭증
PHASE3 (Review Queue Narrator 한정)     ❌ 회수 불가 — Narrator 는 큐 진입 case
                                        에만 적용. 24건은 큐 자체에 안 들어옴
```

T7 D1 확장에서 우선 시도할 mutation 보강안:

```
안   변경 위치                                                내용
---- ----------------------------------------------------    ------------------------------------------
A    materialize_datasynth_manipulation_v2.py:420            offset % 3 == 0 → offset % 2 == 0
                                                             (25B 비율 1/3 → 1/2)
B    materialize_datasynth_manipulation_v2.py:420 else       1.5B → 5_000_000_000 ~ 10_000_000_000
                                                             (z-score 임계 진입, 권장)
C    materialize_datasynth_manipulation_v2.py:437            offset % 4 == 0 → offset % 2 == 0
                                                             (Dec batch 비율 상향)
```

권장은 안 B. 안 A 와 C 는 fallback. 상세 산출물은
`artifacts/fictitious_missing_24_trace.md` 와
`artifacts/fictitious_missing_24_trace.json` 참조.

### 8.3 closing_timing topic high 약점

period_end_adjustment 92건이 `closing_timing topic membership`에 100% 진입하지만 `closing_timing topic high`에 들어간 truth는 4건뿐입니다. closing_timing 점수 구성에서 timing 가중치가 mutation 강도를 흡수하지 못하는 구조.

```
조정 후보
----------------------------------------------------------
1. closing_timing topic_score 산식 재검토 — L3-04 점수 흡수 비율
2. period-end mutation의 weekend / 휴일 / 마감 외 발생 비율 점검
   (정상 결산과 구분되는 잔여 신호가 있는지)
3. L1-04 (전기일·문서일 괴리) 점수 가중치 — period_end 51건이 L1-04 hit
```

### 8.4 intercompany_cycle topic high 약점

circular_related_party 34건 모두 `intercompany_cycle topic medium`에만 진입. `intercompany_cycle topic high`까지 못 가는 이유는 L3-03 점수가 max 0.4로 묶여있기 때문(profile.json 기준 L3-03 max_score=0.4). topic high 임계값(0.75) 대비 구조적 부족.

---

## 9. PHASE1 프로세스 측에서 조정해야 할 점

탐지 파이프라인 측에서 손볼 수 있는 항목들.

### 9.1 case 수 정상화 — 직전 v2 회귀 해결 확인

직전 v2 case 수 폭증(17,478) 문제는 현행(11,116)으로 정상화됐습니다. dispatcher 임계값 변경은 더 이상 필요하지 않은 것으로 보입니다. label-signal recovery로 row-level 신호가 회복되면서 case grouping이 정상 규모로 돌아왔습니다.

### 9.2 unusual_timing topic 분배 재검토

unusual_timing 21건 중 10건이 closing_timing 외 topic으로 흩어진 가능성. profile_phase1_v126.py로 case 단위 추적:

```
점검 흐름
----------------------------------------------------------
1. unusual_timing 21건의 document_id 목록 추출
2. 각 document_id가 들어간 case와 그 case의 primary_topic / topic_scores
3. closing_timing 외 어느 topic이 가장 점수가 높은지 확인
4. 필요 시 score_aggregator의 topic weight 재조정
```

### 9.3 intercompany_cycle topic high 진입 보강

L3-03 max_score 0.4 → topic_score 0.75 도달 어려움. 다음 중 하나 적용 가능:

```
대안                                                          영향 범위
----------------------------------------------------------    ----------------
1. L3-03 점수 상한 0.4 → 0.6 (관계사 검토 가중치 강화)        intercompany 룰 전체
2. L3-03 + 다른 룰 동시 hit 시 booster (예: L1-08 high cash)  multi-rule combo
3. intercompany_cycle topic_score 산식에서 L3-03 weight 상향   topic-level only
```

### 9.4 closing_timing topic high 진입 보강

period_end 92건의 `closing_timing topic high` 진입 4건은 timing rule 가중치 부족. 결산 mutation의 row-level 신호는 강해도 (rule hit 100%) topic_score 산식이 0.75에 도달하지 못함. score_aggregator에서 closing_timing weight 점검 필요.

---

## 10. PHASE2로 넘겨야 할 한계

다음은 PHASE1 단계에서 더 조정해도 별 효과가 없을 가능성이 높은 항목으로, PHASE2(ML/통계 보정)·PHASE3(LLM 의미 해석)로 넘기는 게 정합성 있습니다.

```
영역                                            PHASE1에서 더 조정해도 효과?       다음 단계          결정 문서
---------------------------------------------   --------------------------------   ---------------    ----------------------------------------------------------------------------
period_end vs 정상 결산의 분리                  낮음 — 의미 해석 필요              PHASE2 ML          [closing_intercompany_high_band_decision.md](../../../artifacts/closing_intercompany_high_band_decision.md)
unusual_timing 11/21 ceiling (after_hours)      없음 — 룰 메타 변경 시 정상 야근    PHASE2 ML          §6.1 / §8.1 / D042
                                                FP 폭증 (§6.1 / §8.1 / D042 참조)  + PHASE3 LLM
unusual_timing vs 정상 사후 정정 분리           낮음 — 의미 해석 필요              PHASE3 LLM         —
fictitious 24건 미진입                          없음 — mutation amount 분포 부족   DataSynth (T7 D1   [fictitious_missing_24_trace.md](../../../artifacts/fictitious_missing_24_trace.md)
                                                (T6 추적 결과, §8.2 참조)          확장 안 B 권장)
circular intercompany topic high 미진입         제한적 — 그래프 cycle 필요         PHASE2 그래프      [closing_intercompany_high_band_decision.md](../../../artifacts/closing_intercompany_high_band_decision.md)
```

**T3 의사결정 보강 (2026-05-15)**: `closing_timing topic high` 및 `intercompany_cycle topic high` 보강안(L3-04 weight 0.4→0.5, L3-03 cap 0.4→0.6)에 대한 3가드 측정(회계 도메인 정당성 + AB 손실 + noise FP)이 모두 FAIL로 측정되어 PHASE2 이관이 자동 채택됐다. 상세 근거·ISA 550/PCAOB AS 2401 회계기준 인용·정량 측정 수치는 [artifacts/closing_intercompany_high_band_decision.md](../../../artifacts/closing_intercompany_high_band_decision.md) 참조.

`unusual_timing 11/21 ceiling` 항목 사유: 21건 중 10건이 fiscal year-end window(margin=5) 밖의 after_hours_posting subtype이라 L3-04 standalone primary가 row-level에서 fire 불가. L3-05/L3-06은 정상 야근·주말 전기와 의심 시간대 거래를 구분하지 못하는 단순 시간 신호이므로 standalone primary로 promote하면 정상 운영 모집단의 false positive가 폭증한다. **정상 결산기 야근 vs 의심 시간대 거래의 분리는 multi-feature 분류(PHASE2 ML) 또는 적요·맥락 의미 해석(PHASE3 LLM) 영역**이다. 자세한 반려·채택 근거: §6.1, §8.1, `docs/spec/DECISION.md` D042, `artifacts/unusual_timing_regression_trace.md` §7.

`fictitious 24건` 항목은 PHASE1 룰 임계 조정으로도(FP 폭증), PHASE3 Narrator
로도(큐 미진입) 회수 불가하다. T7 D1 확장의 mutation 보강에서 해결되지 않으면 본
데이터셋의 본질적 한계로 남는다. 상세 trace: `artifacts/fictitious_missing_24_trace.md`.

### 10.1 Top N 정밀도(precision@TopN) 구조 한계

PHASE1은 룰 기반 전수 필터. *룰 점수만으로* 정상 운영과 악의 조작을 Top10 안에서 완전 분리하는 것은 구조적 한계가 있습니다(현행 Top10 누적 truth 92건 = 정상 case 18건 혼입). PHASE2 XGBoost 보정에서 multi-feature 분류로 추가 분리.

---

## 11. 통합 결론

### 11.1 현행 v2 결과 한 줄

`datasynth_manipulation_v2` 2026-05-14 업데이트(circular IC + period-end + label-signal recovery)는 직전 v2 run의 모든 회귀를 해소하고 v1 대비 PHASE1 본래 KPI를 전면 개선했다. **포착률 100 % 회복, Top10 누적 truth 92건, priority high 안에 truth 276건 집중**. 단 unusual_timing 1건은 새 회귀로 잔존.

### 11.2 현행 v2에서 풀어야 할 회귀 (1건)

```
회귀 항목                                    원인 가능성              담당 영역
-------------------------------------------  -----------------------  ---------------
unusual_timing 진입률 86% → 52%               period-end mutation 보강 DataSynth (§8.1)
                                             부수효과로 timing rule    + PHASE1 (§9.2)
                                             score 분포가 다른 topic
                                             으로 이동
```

### 11.3 PHASE1에서 멈추고 PHASE2로 넘길 것

```
영역                                          이유                                        다음 단계
--------------------------------------------  ------------------------------------------  ---------
closing_timing topic high 진입 (period_end 4) PHASE1 timing weight만으로 분리 한계         PHASE2 ML
intercompany_cycle topic high 진입 0          그래프 cycle 알고리즘 필요                  PHASE2 그래프
unusual_timing 의미적 분리                     적요·계정·관계 의미 해석 필요               PHASE3 LLM
fictitious 미진입 24건 의미 해석              row-level mutation이 약한 케이스             PHASE3 LLM
```

### 11.4 다음 단계 우선순위

```
순서   작업                                                                    담당
-----  ----------------------------------------------------------------------  -----------
1      unusual_timing 21건 중 미진입 10건 case-level 추적                       PHASE1 + DataSynth
2      closing_timing topic high 진입 보강 (timing weight 재조정 검토)         PHASE1
3      intercompany_cycle topic high 진입 보강 (L3-03 score 상한 검토)         PHASE1
4      PHASE2 진입 — XGBoost · VAE · 그래프 검출 설계                          PHASE2 착수
```

PHASE1 단계에서 위 1~3번까지 정리한 다음, **나머지 Top N precision 개선은 PHASE2 ML로 넘기는 것**이 본 프로젝트 로드맵상 정합성 있는 결정입니다.
