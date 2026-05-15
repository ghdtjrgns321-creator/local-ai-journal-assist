# Phase1 Detection 결과 — datasynth_manipulation

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

## 0. 이 문서는 무엇인가

`data/journal/primary/datasynth_manipulation/`에 들어있는 **악의적으로 조작된 전표 420건**을 Phase1이 얼마나 잡고, 어느 주제 그룹에 분류했으며, 그 주제 안에서 몇 등에 올렸는지 보는 문서다.

`datasynth_contract`(룰 정의 ↔ 구현 일치)와는 목적이 완전히 다르다.

```
구분             Contract 점검                       Manipulation 점검 (이 문서)
---------------  ----------------------------------  ----------------------------------------
질문             정의대로 동작하나                   악의 조작을 어디서/몇 등에 잡았나
지표             과탐 0 / 미탐 0                     포착률 · 주제 분류 · 주제 내 Top N 순위
truth 성격       룰 설계서가 만든 라벨               의도적 조작 시나리오 라벨
truth 건수       1,772 + 2,130 + 14,726 + …          420 documents
포커스           룰 단위 정합성                      감사인 검토 큐 품질 (실제 운영 관점)
```

### 사용자 관점 핵심 질문 3가지

이 문서는 다음 3가지 순서로 답한다.

```
질문                                    답하는 섹션
--------------------------------------  -----------
① 일단 잡기는 했나? (포착률)            §2 A축
② 어느 주제 그룹으로 보여줬나?          §3 B축
③ 그 주제 안에서 몇 등에 올렸나?        §4 C축
```

감사인은 **주제별로 나뉜 검토 큐**에서 case를 위에서 아래로 본다. 따라서 "전체에서 잡혔는가"보다 "올바른 주제에, 위쪽 순위에 들어왔는가"가 운영상 더 중요하다.

---

## 1. 실행 기준과 산출물

### 1.1 실행 명령

```
.venv\Scripts\python.exe tools\scripts\profile_phase1_v126.py ^
    --data-dir data\journal\primary\datasynth_manipulation ^
    --checkpoint artifacts\phase1_manipulation_quality_profile.json ^
    --cache-path artifacts\phase1_manipulation_quality_case_input.pkl
```

### 1.2 입력 데이터

| 항목                     | 값         |
| ------------------------ | ---------: |
| journal rows             |  1,095,158 |
| documents                |    317,505 |
| manipulation truth docs  |        420 |

### 1.3 산출 파일

| 파일                  | 경로                                                                                                       |
| --------------------- | ---------------------------------------------------------------------------------------------------------- |
| checkpoint            | `artifacts/phase1_manipulation_quality_profile.json`                                                       |
| case input cache      | `artifacts/phase1_manipulation_quality_case_input.pkl`                                                     |
| case artifact         | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T095701Z.json` |
| 상세 산출             | `artifacts/phase1_ranking_quality_analysis.json`                                                           |
| 비교 기준 (이전 run)  | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T090512Z.json` |

### 1.4 순위 산출 기준

주제(topic)별 case를 `topic_score desc`, `triage_rank_score desc`, `total_amount desc`, `rule_count desc` 순서로 정렬한 뒤 Top10 / Top50 / Top100 / Top200의 unique `manipulated_entry_truth.document_id` 건수를 계산한다. High는 해당 topic score `>= 0.75` 기준이다.

---

## 2. A축 — 포착률 (일단 잡았는가)

> **이 축이 답하는 질문**: "악의 조작 420건 중 몇 건을 어떻게든 잡았는가?"

가장 기본적인 합격선. 점수, 룰 플래그, review 큐 중 어느 하나로도 잡히지 않으면 그 truth는 감사인이 영영 못 본다.

```
항목                              값
--------------------------------  -----
manipulation truth docs             420
score/rule/review 포착              420
미포착                                0
포착률                            100.0 %
```

**A축 결론**: 420건 **전부 포착**됐다. case 수는 4,218건이며 truth는 점수/플래그/review 어느 한 채널로도 빠짐없이 잡힌다. 즉 "감사인이 못 본다"는 상황은 없다.

---

## 3. B축 — 주제 분류 (어느 그룹으로 보여줬는가)

> **이 축이 답하는 질문**: "잡은 truth 420건을 7개 주제 큐 중 어느 그룹에 배치했고, 각 그룹에서 High로 올라간 것은 몇 건인가?"

운영 화면에서는 7개 주제로 나뉜 큐가 보이고, 감사인은 주제별 큐를 따로 검토한다. 따라서 "올바른 주제에 들어갔는가"는 단순 포착보다 중요하다.

새 8번째 topic/queue는 만들지 않았다. `fraud_scenario_tags`는 badge/context와 breakdown reason 추적에만 쓴다.

### 3.1 주제별 case · truth 분포

```
주제                          topic case   topic truth   high case   high truth   해석
----------------------------  ----------  ------------  ----------  -----------  ------------------------------
원장기록·데이터정합성                132             0           0            0   조작 시나리오 매칭 없음
승인·권한·업무분장 통제            2,732           234         157           75   조작 흡수 비중 1위
결산·기간귀속·입력시점             2,814           197           8            0   많이 들어왔으나 High 부재
계정분류·거래실질 불일치             895             4           0            0   대부분 약신호로 잔류
중복·상계·자금유출                   581             0          56            0   조작 truth 부재
관계사·내부거래·순환구조             963            35           6            0   topic은 진입, High 부재
수익·금액·모집단 통계 이상           591             9           5            0   topic 진입 자체가 적음
```

- **잘 흡수된 주제**: `승인·권한` (truth 234건 / High 75건). approval/SoD 위반은 룰이 가장 명확.
- **들어왔지만 High까지 못 간 주제**: `결산·기간귀속`(197건), `관계사`(35건), `수익`(9건). topic 분류는 됐지만 점수가 약함.
- **truth가 거의 안 들어온 주제**: `중복·자금유출`(0건), `데이터정합성`(0건). 시나리오 성격상 매핑 안 됨.

### 3.2 시나리오 → 기대 주제 매칭

manipulation 라벨에는 6개 조작 시나리오가 있다. 각 시나리오가 "어느 주제로 들어와야 하는가"는 사전에 정의돼 있다.

```
시나리오                                 기대 주제        truth docs   기대 주제 진입
---------------------------------------  --------------  -----------  --------------
approval_sod_bypass                      승인·권한                29           15
circular_related_party_transaction       관계사·내부거래          34           13
embezzlement_concealment                 중복·자금유출            76            0
fictitious_entry                         수익·금액               168            0
period_end_adjustment_manipulation       결산·기간귀속            92           49
unusual_timing_manipulation              결산·기간귀속            21            7
```

- **기대대로 들어옴**: `approval_sod_bypass` (15/29), `circular_related_party` (13/34), `period_end_adjustment` (49/92), `unusual_timing` (7/21).
- **기대 주제에 못 들어옴**: `embezzlement_concealment` (0/76), `fictitious_entry` (0/168). 즉 76+168 = **244건**이 본래 주제 큐에 없다. 다른 주제로 흩어지거나 약신호로만 남았다.

`fictitious_entry`를 `계정분류·거래실질` 기준으로도 확인했지만 High/Top100 truth는 0건이었다.

---

## 4. C축 — 주제 내 순위 (몇 등에 들어갔는가)

> **이 축이 답하는 질문**: "감사인이 주제별 큐를 위에서부터 본다면, 악의 조작이 Top 몇 안에 들어와 있는가?"

이것이 최종 사용자 관점 핵심 지표다. truth가 주제에 들어왔어도 1,000등이면 실무에서는 검토되지 못한다.

### 4.1 전체 case 기준 누적 Top N

먼저 모든 주제를 합친 전체 ranking 기준이다.

```
순위 범위    truth docs   누적 포착률
-----------  -----------  -----------
Top 10                0          0.0 %
Top 50                6          1.4 %
Top 100              39          9.3 %
Top 500             129         30.7 %
Top 1000            162         38.6 %
```

전체 Top10에는 truth 0건. Top100까지 가도 39건(420건 중 9.3%)에 불과하다. 즉 **전체 ranking은 약하다**. 다만 운영 화면은 전체 ranking이 아니라 주제별 ranking이므로, 다음 절이 더 중요하다.

### 4.2 주제별 Top N truth 진입 — 최종 사용자 관점 핵심

```
주제                          Top10   Top50   Top100   Top200
----------------------------  ------  ------  -------  -------
원장기록·데이터정합성              0       0        0        0
승인·권한·업무분장 통제            0      22       52       85
결산·기간귀속·입력시점             0       0       20       40
계정분류·거래실질 불일치           0       0        0        0
중복·상계·자금유출                 0       0        0        0
관계사·내부거래·순환구조           0       0        1       13
수익·금액·모집단 통계 이상         1       4        4        4
```

읽는 법:
- **승인·권한 주제 Top50**에는 truth 22건이 들어와 있다 → 감사인이 승인 큐 상위 50건만 검토해도 22건의 악의 조작이 검토된다.
- **수익 주제 Top10**에는 truth 1건이 있다 → 주제 자체가 작지만 상위에는 들어옴.
- **결산·기간귀속**은 Top100에 가서야 truth 20건이 들어옴 → 의미 있는 수치지만 더 상위로 끌어올려야 함.
- **중복·자금유출 / 데이터정합성 / 계정분류**는 어떤 Top에도 truth 없음 → 시나리오 매핑부터 약함.

### 4.3 시나리오별 주제 내 진입 순위 (판정 포함)

```
시나리오                                 기대 주제        truth   기대 진입   High   Top10   Top50   Top100   Top200   판정
---------------------------------------  --------------  ------  ----------  -----  ------  ------  -------  -------  -----------
approval_sod_bypass                      승인·권한           29          15     13       0       4       10       14   일부 충족
circular_related_party_transaction       관계사·내부거래     34          13      0       0       0        0        0   후순위
embezzlement_concealment                 중복·자금유출       76           0      0       0       0        0        0   미진입
fictitious_entry                         수익·금액          168           0      0       0       0        0        0   미진입
period_end_adjustment_manipulation       결산·기간귀속       92          49      0       0       0       15       20   낮은 순위
unusual_timing_manipulation              결산·기간귀속       21           7      0       0       0        0        1   낮은 순위
```

운영 관점 요약:

- **일부 충족** (1개): `approval_sod_bypass`. 승인 큐 Top100 안에 10건 포함 (truth 29건 중 34%).
- **낮은 순위** (2개): `period_end_adjustment`, `unusual_timing`. 주제에는 들어왔지만 Top100~Top200에서야 등장.
- **미진입** (2개): `embezzlement_concealment`, `fictitious_entry`. 주제 자체에 truth가 0건.
- **후순위** (1개): `circular_related_party`. 주제는 진입했지만 Top200 안에는 없음.

### 4.4 현재 score band 분포

각 주제 내부에서 truth가 어느 band에 머무는지 본다. truth가 band에 있다고 곧 Top 순위는 아니지만, band가 high면 적어도 화면 상단에 있을 가능성이 크다.

```
band                                case count   truth docs
----------------------------------  ----------  -----------
closing_timing:low                       2,805          197
approval_control:medium                  2,573          167
intercompany_cycle:medium                  957           35
account_logic:low                          894            4
duplicate_outflow:low                      518            0
revenue_statistical:low                    350            7
revenue_statistical:medium                 236            4
approval_control:high                      157           75
duplicate_outflow:high                      56            0
closing_timing:high                          8            0
intercompany_cycle:high                      6            0
revenue_statistical:high                     5            0
```

핵심: `closing_timing`, `intercompany_cycle`, `revenue_statistical` 주제에 truth가 아예 없는 것이 아니라 **대부분 low/medium에 잔류**한다. 따라서 다음 조정은 약한 rule 조합을 다시 floor로 되돌리는 방식이 아니라, 실제 조작 맥락을 설명하는 **비-rule feature를 추가**해야 한다.

### 4.5 C축 결론

```
관점                  결과                                  현재 상태
--------------------  ------------------------------------  ----------
전체 Top10            truth 0건                             약함
승인 주제 Top100      truth 52건 / High 75건                강함
결산 주제 Top100      truth 20건 (Top200까지 가야 40건)     약함
관계사 주제 Top100    truth 1건                             약함
수익 주제 Top100      truth 4건                             약함
중복자금 주제 전체    truth 0건                             진입 실패
```

승인 주제만 운영 가능 수준이고, 나머지 5개 주제는 ranking을 끌어올리기 위한 비-rule feature 보강이 필요하다.

---

## 5. 약점 진단 — 왜 Top에 못 들어오는가

A축은 통과(100% 포착)지만 C축은 약하다. 원인을 진단한다.

### 5.1 약한 floor 제거의 직접 영향

이번 quality calibration은 정상 실무에서도 흔한 약한 medium floor를 제거했다. 그 결과 topic 점수는 깨끗해졌지만, datasynth truth 중 강한 감사 근거 없이 약한 context 조합(`manual`, `closing`, `work scope`, `timing`)으로 생성된 라벨은 자연스럽게 low/medium 또는 topic 밖으로 밀려났다.

```
제거/약화된 조건                                 이전 효과                    anti-fitting 후 결과
-----------------------------------------------  --------------------------  -----------------------------
L3-02 + L3-04 + L3-12                            가공/결산 Medium floor 넓게  수익 topic case 3,079→591
approval_bypass + L3-02 + L3-12                  횡령은폐 Medium floor        중복자금 topic truth 0건으로 정리
L3-03 + L3-05 + (L3-02 or L3-12)                 관계사 High floor 넓게       관계사 High truth 16→0
approval_bypass + L3-02/L3-05                    승인우회 High 후보            승인 High truth 81→75
```

이건 성능 악화가 아니라 **fitting 제거의 직접 결과**다. 약한 조합을 다시 floor로 올리면 datasynth 점수는 좋아지지만 실제 회사 데이터에서 정상 noise까지 끌어올린다.

### 5.2 contract noise 대비 — fitting 위험 검증

같은 룰을 `datasynth_contract`에서 돌려서 정상 fixture 쪽에서 얼마나 뜨는지 비교한다.

```
주제                          manip case   contract case   manip High   contract High   noise 해석
----------------------------  ----------  --------------  ----------  --------------  ------------------------
원장기록·데이터정합성                132             387           0               0   조작 전용 issue 아님
승인·권한·업무분장 통제            2,732          12,391         157             492   정상 운영에서도 매우 넓음
결산·기간귀속·입력시점             2,814          13,875           8             907   가장 큰 noise 위험
계정분류·거래실질 불일치             895           4,764           0               0   대부분 low context
중복·상계·자금유출                   581             769          56             439   contract fixture 영향 큼
관계사·내부거래·순환구조             963           6,750           6               7   topic은 넓지만 High 제한적
수익·금액·모집단 통계 이상           591           3,793           5             700   강한 noise 위험
```

특히 **결산·수익은 manipulation보다 contract에서 High case가 훨씬 많다**. 즉 datasynth manipulation truth를 Top100에 더 넣기 위해 결산/수익 floor를 다시 올리면 contract 정상군까지 함께 폭증한다 → 운영상 무의미.

### 5.3 진단 요약

```
확인 항목                              결과
-------------------------------------  ----------------------------------------------------
못 잡은 문서가 있는가                  score/rule/review 미포착 0건
악의 조작이 각 주제 High에 들어왔는가  승인 주제만 75건. 결산·관계사·수익·중복자금은 거의 없음
왜 Top에 못 들어오는가                 약한 datasynth floor 제거 후, 강한 감사 근거가 없는 truth는 low/medium에 잔류
noise는 줄었는가                       수익 -2,488건, 중복자금 -122건 줄어 fitting noise 감소
근본 문제는 무엇인가                   포착은 됐지만 기대 주제 ranking으로 승격할 feature 부족
```

---

## 6. 후속 조정 방향

ranking 목표는 `truth fitting`이 아니라 `contract noise cap`을 같이 둬야 한다. 예를 들어 조작 truth Top100을 올릴 때 contract High case가 함께 증가하면 실패로 본다.

주제별 보강 방향:

1. **결산 주제**: 단순 `manual + closing + work scope`가 아니라 결산월 집중, 사후입력, 고액, 설명부족, 민감계정, 반복 수정 중 **최소 2개 이상 결합**해야 한다.
2. **가공전표/수익 주제**: `L4-01/L4-03` 외에 수익성 계정, 비정상 document source, customer/vendor 실재성, 계정군 amount percentile 같은 **비-rule feature**를 붙여야 한다.
3. **횡령은폐 주제**: approval context만으로 올리지 말고 **자금성 계정, 반제·상계, 중복 지급, vendor/employee 연결, 승인자-작성자 관계**가 같이 나와야 한다.
4. **순환거래 주제**: 관계사 flag만으로 High를 만들지 말고 **counterparty chain, 같은 금액의 왕복, 월말 반복, 내부거래 제거/상계 불일치** 같은 graph/relational feature가 필요하다.
5. **모든 주제 공통**: ranking 보강 시 반드시 `datasynth_contract` 정상군 High case 증가량을 함께 측정. 동시 증가 시 적용 거부.

---

## 부록 A — 실행 이력과 보강 시도

### A.1 non-rule evidence booster (2026-05-08)

`audit_evidence_score`를 추가했지만 High floor는 추가하지 않았다. 포착률과 contract noise cap은 유지됐고 전체 Top/Topic Top 지표는 거의 변하지 않았다. fitting 위험은 낮지만 품질 개선 폭도 작다.

산출물:

| 파일                         | 경로                                                                                                       |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------- |
| manipulation checkpoint      | `artifacts/phase1_manipulation_evidence_profile.json`                                                      |
| manipulation case cache      | `artifacts/phase1_manipulation_evidence_case_input.pkl`                                                    |
| manipulation case artifact   | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T105341Z.json` |
| contract checkpoint          | `artifacts/phase1_contract_evidence_profile.json`                                                          |
| contract case cache          | `artifacts/phase1_contract_evidence_case_input.pkl`                                                        |
| contract case artifact       | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T110050Z.json` |
| 비교 분석 JSON               | `artifacts/phase1_ranking_evidence_analysis.json`                                                          |

주제별 evidence 적용 영향:

```
주제                          audit evidence case   high case Δ   Top100 truth Δ   contract high Δ   판단
----------------------------  -------------------  ------------  ---------------  ----------------  ------------------------
원장기록·데이터정합성                            0           +0               +0                +0   영향 없음
승인·권한·업무분장 통제                       2,150           +0               +0                +0   안전하지만 개선 없음
결산·기간귀속·입력시점                        2,038           +0               +0                +0   흔한 context, 효과 제한
계정분류·거래실질 불일치                         28           +0               +0                +0   영향 작음
중복·상계·자금유출                                5           +0               +0                +0   evidence 희소
관계사·내부거래·순환구조                          0           +0               +0                +0   case rows만으로 cycle 부족
수익·금액·모집단 통계 이상                      209           +0               +0                +0   증빙 gap만으론 부족
```

### A.2 independent evidence join (2026-05-08)

master data, document flows, intercompany matched pairs, approval matrix를 조인했지만 High floor는 추가하지 않았다. 포착률과 Top 지표는 유지됐고, contract High 증가도 0건이다. 다만 `document_flow_orphan`과 `approval_matrix_gap`이 정상군에도 매우 넓게 붙어서 ranking 개선 효과는 없었다.

산출물:

| 파일                         | 경로                                                                                                       |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------- |
| manipulation checkpoint      | `artifacts/phase1_manipulation_independent_evidence_profile.json`                                          |
| manipulation case cache      | `artifacts/phase1_manipulation_independent_evidence_case_input.pkl`                                        |
| manipulation case artifact   | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T130507Z.json` |
| contract checkpoint          | `artifacts/phase1_contract_independent_evidence_profile.json`                                              |
| contract case cache          | `artifacts/phase1_contract_independent_evidence_case_input.pkl`                                            |
| contract case artifact       | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T131255Z.json` |
| 비교 분석 JSON               | `artifacts/phase1_ranking_independent_evidence_analysis.json`                                              |

독립 evidence 조인량:

```
evidence                      manipulation rows   contract rows   판단
----------------------------  -----------------  --------------  --------------------------------
known counterparty                      277,504         536,574   master join 정상
document flow orphan                    675,071         684,411   너무 넓음. 단독 ranking 부적합
IC unmatched reference                       17              17   희소함. High floor 근거 부족
approval matrix gap                     617,266         826,935   너무 넓음. 정상 위임과 섞임
approval limit exceeded                   1,344          10,629   contract가 더 큼. 단독 가점 금지
```

### A.3 제거된 weak medium floor reason

```
weak medium floor                                                  manip prev   manip now   contract prev   contract now   판단
-----------------------------------------------------------------  ----------  ----------  --------------  -------------  ------------------------
period_end + manual_adjustment + weak_description                            1           0             119              0   결산수정 context로 강등
reversal_or_offset + work_scope_concentration + manual_adjustment            7           0             112              0   횡령은폐 context로 강등
approval_bypass + manual_adjustment                                         20           0              14              0   승인우회 floor 금지
approval_bypass + non_business_day_timing                                    2           0              14              0   휴일 승인만으로는 금지
```

이 변경은 성능 보정이 아니라 fitting 방지 보정이다. 실제 High/Top ranking은 변하지 않았고, `topic_score_breakdown.fraud_combo_policy_ids`에서 정상 실무에서도 흔한 약한 reason이 제거됐다. 감사인에게 보여주는 점수 근거의 품질이 올라갔다.

### A.4 contract에서 많이 뜨는 fraud combo (정상군 noise)

```
combo policy                                                                                       contract case   판단
-------------------------------------------------------------------------------------------------  -------------  ------------------------------
approval_control:work_scope_combo                                                                         12,356   운영 집중도 context로만 유지
intercompany_cycle:related_party_or_ic + amount_or_timing_anomaly                                          6,640   너무 넓음
revenue_statistical:revenue_or_amount_outlier + closing_or_batch_context                                     919   정상 outlier 많음
closing_timing:period_end_or_late_posting + high_amount + weak_description_or_sensitive_account              907   결산 High noise 핵심
revenue_statistical:revenue_or_amount_outlier + manual_adjustment + rare_or_duplicate_pattern                700   수익 High noise 핵심
approval_control:approval_bypass + high_amount_or_cutoff_or_strong_abnormal_timing                           487   승인 High는 유지 가능
closing_timing:period_end + manual_adjustment + weak_description                                               0   이번 calibration에서 제거
duplicate_outflow:reversal_or_offset + work_scope_concentration + manual_adjustment                            0   이번 calibration에서 제거
```

datasynth manipulation truth를 Top100에 더 넣기 위해 위 combo를 다시 올리면 contract 정상/fixture case도 같이 폭증한다. 결산·수익은 manipulation보다 contract에서 High case가 훨씬 많아 rule 조합 floor 강화 방향은 부적합.

---

## 한 줄 결론

`manipulated_entry_truth` **420건은 모두 포착(A축 100%)** 됐다. 그러나 **주제 분류는 승인 위주로 편중**(B축)되어 있고, **주제 내 Top 순위까지 끌어올린 것은 승인 주제뿐**(C축)이다. 결산·관계사·수익·중복자금·횡령은폐 시나리오를 주제 상위로 올리려면 룰 조합 floor 보강이 아니라 master data·document flow·승인 권한·관계 chain 기반 **비-rule feature 보강**이 필요하다.
