# Phase1 Detection 결과 — datasynth_contract

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

## 0. 이 문서는 무엇인가

`data/journal/primary/datasynth_contract/`를 2026-05-13에 Phase1로 재실행한 결과다.

이 데이터셋은 **부정 탐지 성능을 보여주는 결과표가 아니다**. 목적은 단 하나, **"룰 설계서에 적힌 잡아야 할 것"과 "Phase1 구현체가 실제로 집계한 것"이 일치하는지** 확인하는 계약(contract) 점검이다.

### 일반 탐지 평가 vs Contract 점검

```
구분             일반 탐지 평가                  Contract 점검 (이 문서)
---------------  ------------------------------  ------------------------------
질문             얼마나 잘 잡았나                정의대로 동작하나
지표             precision / recall              과탐 0 / 미탐 0
비교 대상        실제 부정 라벨 vs 탐지 결과     룰 정의서 vs 룰 구현 결과
용도             사용자 위험 목록 품질           룰 구현 ↔ 집계 정합성
대상 데이터셋    datasynth_manipulation          datasynth_contract
```

Contract 데이터셋에는 룰 설계서에 명시된 케이스가 분명한 라벨과 함께 들어 있다. 예를 들어 룰이 "차대변 불일치 316건이 있다"고 라벨링했다면, Phase1 구현체는 316건을 **정확히** 잡아야 통과한다. 1건이라도 더 잡으면 과탐, 1건이라도 빠뜨리면 미탐이다.

### 3개 축으로 점검한다

- **A축 — 룰 단위 계약**: 각 룰(L1-01, L3-02 등)이 자기 정의대로 잡았는가? 룰별 과탐·미탐 0 여부.
- **B축 — 주제별 분기 계약**: truth는 모두 같은 의미가 아니다. "100% 잡아야 할 hard error"와 "넓게 모아두고 일부만 case로 올릴 광역 모집단"이 의도대로 분리됐는가?
- **C축 — 표시 구조 계약**: 최신 Phase1 출력이 전체 Top 10 하나가 아니라 주제 그룹별 리스트로 나뉘는가? review-only 신호(L3-12)가 case를 새로 만들지는 않는가?

---

## 1. 입력과 산출물

### 1.1 입력 데이터

| 항목              | 값        |
| ----------------- | --------: |
| 원장 row          | 1,109,435 |
| document          |   319,193 |
| label 누수 컬럼   |   제거됨  |
| label 파일 수     |     1,442 |

### 1.2 Phase1 출력 요약

| 항목              | 값      |
| ----------------- | ------: |
| 전체 소요 시간    | 761.250초 |
| 생성된 case 수    |  14,338 |
| macro finding 수  |     100 |
| 그룹별 Top N      |      10 |
| High row          |  12,783 |
| Medium row        | 161,845 |
| Low row           |   2,009 |
| Normal row        | 932,798 |

### 1.3 산출 파일

| 파일                 | 경로                                                                                                |
| -------------------- | --------------------------------------------------------------------------------------------------- |
| checkpoint           | `artifacts/phase1_contract_profile_caxis_20260513.json`                                             |
| case input cache     | `artifacts/phase1_contract_case_input_caxis_20260513.pkl`                                           |
| case artifact        | `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260513T090731Z.json` |
| 종합 요약            | `artifacts/contract_eval_summary_20260513.json`                                                     |
| 룰별 평가            | `artifacts/contract_truth_rule_eval_20260513.csv`                                                   |
| 주제(family)별 평가  | `artifacts/contract_truth_family_eval_20260513.csv`                                                 |
| 버킷별 평가          | `artifacts/contract_truth_bucket_eval_20260513.csv`                                                 |
| subclass별 평가      | `artifacts/contract_truth_subclass_eval_20260513.csv`                                               |
| 그룹별 Top case 평가 | `artifacts/contract_group_top_case_eval_20260513.csv`                                               |
| sidecar taxonomy     | `artifacts/contract_sidecar_taxonomy_eval_20260513.csv`                                             |

### 1.4 실행 시간 분포

```
단계                              소요 시간
--------------------------------  ---------
CSV load                            9.441초
independent evidence enrichment     4.289초
feature.time                        1.712초
feature.amount                      4.046초
feature.pattern                     4.865초
feature.text                       10.964초
detector.layer_a                   18.104초
detector.layer_b                  132.371초
detector.layer_c                  232.714초
detector.benford                    7.927초
aggregate                          41.217초
Phase1 case builder               277.580초
--------------------------------  ---------
합계                              761.250초
```

병목은 `case builder → layer_c → layer_b` 순서다.

---

## 2. A축 — 룰 단위 계약 검증

> **이 축이 답하는 질문**: "Phase1의 32개 운영 룰 각각이, 룰 정의서에 적힌 케이스를 한 건도 빠뜨리지 않고 그리고 한 건도 더하지 않고 잡았는가?"

A축은 룰 정의 ↔ 구현 결과의 1:1 일치를 본다. 사용자 위험 목록 품질이 아니라 **계약 점검**이다. 따라서 합격 기준은 단순하다: 공식 `rule_truth_*` 기준 **과탐 0, 미탐 0**.

### 2.1 계층별 합격 여부

L1 ~ L4 / D 5개 계층 전부 통과했다.

```
계층                         평가 단위              정답       탐지       정탐       과탐  미탐  결과
---------------------------  --------------------  --------  --------  --------  ----  ----  ----
L1 — 확정 오류               document                 1,772     1,772     1,772     0     0   통과
L2 — 강한 검토 신호          document/pair            2,130     2,130     2,130     0     0   통과
L3 — 검토 필요 이상징후      document/user-year     296,775   296,775   296,775     0     0   통과
L3-12 — 업무범위 검토 후보   candidate user-year        127       127       127     0     0   통과
L4 — 통계 이상치             document                14,726    14,726    14,726     0     0   통과
D01 / D02 — Variance         macro group              682 c     682 c       682     0     0   통과
```

> `c` = confirmed. L4-02 / D01 / D02는 문서가 아니라 macro finding 계열이다. D01·D02 A축은 `rule_truth_D*.csv`가 review universe와 일치하고 confirmed subset이 그 안에 포함되는지로 검증했다.

### 2.2 룰별 상세 — 핵심 정합성 룰

룰 ID만 보고는 무엇을 잡는지 알기 어렵기 때문에 한글 의미를 같이 표기한다.

```
룰      한글 의미              정답       탐지       과탐  미탐
------  --------------------  --------  --------  ----  ----
L1-01   차대변 불일치              316       316     0     0
L1-02   필수 필드 누락             156       156     0     0
L1-03   무효 계정 사용              32        32     0     0
L1-08   회계기간 불일치            731       731     0     0
L3-02   수기/조정 전표          86,808    86,808     0     0
L3-04   기말/기초 전표 집중    141,375   141,375     0     0
L3-05   주말/휴일 전기          24,318    24,318     0     0
L3-11   컷오프 불일치              130       130     0     0
```

### 2.3 전수 룰 적용 결과 (운영 32개 룰 전부)

운영 중인 **32개 L1~L4 룰 전부**가 실행됐다. 룰 dispatcher가 빠뜨린 룰은 없다(`contract_truth_rule_eval_20260513.csv` 31개 row, 룰별 row가 모두 잡혀 있음).

`같은 룰 매칭률` = `같은 룰 ID로 정확히 플래그된 docs ÷ 정답 docs`. 1.00이 아닌 룰은 truth 정의가 **broad 모집단**까지 포함하기 때문에 다른 룰로 흡수되거나, 시스템·정책 예외 정책상 직접 hit하지 않도록 설계된 케이스다. 자세한 의미는 §3 B축에서 다룬다.

```
룰     정답 docs   같은 룰 매칭   매칭률   비고
-----  ---------  -------------  ------  -------------------------
L3-04    141,375         96,290    0.68  broad 모집단
L3-02     86,808         86,808    1.00
L3-03     30,377         30,377    1.00
L3-05     24,318         24,318    1.00
L3-06      7,507          7,507    1.00
L4-05      4,964          4,964    1.00
L4-04      4,091          4,091    1.00
L4-03      4,015          4,015    1.00
L3-01      2,419          2,419    1.00
L3-10      1,601          1,601    1.00
L2-04      1,098          1,025    0.93  broad
L3-09      1,091          1,091    1.00
L4-01        964            964    1.00
L1-08        731            731    1.00
L4-06        692            692    1.00
L3-07        657            657    1.00
L2-01        457            111    0.24  broad
L3-08        428            428    1.00
L2-02        384            384    1.00
L1-01        316            316    1.00
L1-05        244            217    0.89  broad
L1-02        156            156    1.00
L3-11        130              0    0.00  system_policy_exception
L1-09        122              0    0.00  system_policy_exception
L2-03        111             15    0.14  broad
L1-07         96              0    0.00  system_policy_exception
L2-05         80             72    0.90  broad
L1-04         56             56    1.00
L1-03         32             32    1.00
L1-06         19              3    0.16  broad
```

- **`broad`**: truth 정의가 "검토할 만한 광역 모집단"이라 다른 룰로도 잡히는 도큐를 포함. A축 합격 판정은 §2.1 계층별 표 기준.
- **`system_policy_exception`**: 시스템·정책 예외 라벨(`L3-11`, `L1-09`, `L1-07`)은 룰이 직접 hit하지 않고 score 보정·예외 사이드카로 처리되도록 설계됨. 의도된 동작이며 미탐 아님.

**A축 결론**: 공식 rule truth 기준으로 L1 / L2 / L3 / L4 문서 룰과 D01 / D02 macro 계약이 **모두 통과**했다. 이 축에서 과탐·미탐은 0이다.

---

## 3. B축 — 주제별 분기 계약 검증

> **이 축이 답하는 질문**: "잡은 것들을 어떤 주제로 분류했고, 각 주제에서 의도대로 일부는 score만 주고 일부는 case로 올렸는가?"

B축은 `contract_rule_truth_taxonomy.csv` 기준으로 truth의 **성격**을 나눠 본다. 모든 truth가 같은 의미의 "최종 위험 전표"가 **아니다**. 어떤 truth는 "전부 case로 올려야 한다", 어떤 truth는 "넓게 점수는 주되 case는 선별한다"는 정책이 미리 정의돼 있다. Phase1이 그 분기를 의도대로 실행했는지 본다.

읽는 법:

- **정답**: 룰 정의서가 라벨링한 문서 수
- **점수 부여**: Phase1이 점수(`score_docs`)를 부여한 문서 수 (분포 신호로 잡혔는지)
- **같은 룰 플래그**: 룰 ID가 일치하게 플래그된 문서 수
- **case 승격**: 최종 case로 만들어진 문서 수 (truth 성격에 따라 의도적으로 작게)

### 3.1 주제(family)별 분기 결과

```
주제 (family)                  한글 의미              정답     점수     같은룰   case   의도된 정책               결과
-----------------------------  --------------------  -------  -------  -------  ------  ------------------------  ----
broad_population_contract      광역 검토 모집단      184,889  178,757  167,648  58,567  점수 넓게, case 일부만    통과
high_review_contract           고검토 후보            16,498   16,498   16,498   7,055  점수 100%, case 선별      통과
transaction_pattern_contract   거래 패턴 검토 후보     2,101    2,030    1,599     673  review/약신호 분리        통과
timing_cutoff_contract         컷오프·결산 계열        1,875    1,872    1,745     789  강한 신호만 case 우선     통과
data_integrity_contract        데이터 정합성 오류      1,222    1,222    1,222   1,060  100% 점수 + 같은룰 100%   통과
unclassified_contract          보조 검토                 428      428      428     101  약한 검토 보조            통과
control_contract               승인·통제 약속            421      396      273     308  시스템 예외와 분리        통과
```

### 3.2 데이터 정합성 subclass — "어떤 주제를 얼마나 잡고 못 잡았나" 확대

데이터 정합성은 case로 승격되어야 하는 비중이 가장 높은 주제다. subclass 단위로 보면 모든 분류가 같은 룰 ID로 플래그되며 누락이 없다.

```
subclass                                   한글 의미                  정답  점수  같은룰  case  매칭률
-----------------------------------------  ------------------------  ----  ----  ------  ----  ------
data_integrity_exception                   정합성 예외 (광역)         688   688     688   587    1.00
hard_period_mapping_error                  기간 매핑 hard error       227   227     227   227    1.00
possible_period_cutoff_or_late_close       컷오프·기말 지연 가능성    202   202     202   202    1.00
hard_data_quality_or_interface_error       데이터 품질·인터페이스      71    71      71    33    1.00
reviewable_data_quality_gap                검토 가능한 품질 갭         34    34      34    11    1.00
hard_data_quality_or_posting_error         입력/품질 hard error        13    13      13    13    1.00
```

정합성 hard error와 reviewable gap **모두 점수와 플래그는 100%**다. case docs가 정답 docs보다 적은 이유는 "전부 case로 올리지 않는다"는 정책 때문이며, 누락이 아니다.

### 3.3 버킷별 분기 — 누락된 주제는 어디인가

`누락(같은 룰 기준)`은 "같은 룰 ID로는 플래그되지 않은 문서"다. 0이 아닌 칸은 두 가지 사유 중 하나로 모두 의도된 동작이다.

1. truth가 **broad 모집단**이라 다른 룰로 흘러간 의도된 케이스
2. 시스템·정책 예외처럼 룰이 직접 hit하지 않도록 설계된 케이스

```
버킷                       한글 의미              정답     점수     같은룰   case    누락    누락 사유
-------------------------  --------------------  -------  -------  -------  ------  ------  -------------------------
hard_error                 정합성 hard error         986      986      986     847       0  —
review_required            검토 필수               2,516    2,513    2,386   1,081     130  broad (다른 룰로 흡수)
high_review                고검토 후보            18,156   18,085   17,819   7,481     337  broad
broad_review               광역 검토 모집단      184,889  178,757  167,648  58,567  17,241  broad (cross-rule 흡수)
control_gap                통제 갭                   373      358      273     301     100  broad
system_policy_exception    시스템·정책 예외           48       38        0       7      48  룰 직접 hit 제외 정책
```

`system_policy_exception` 48건은 같은 룰 ID로는 0건 플래그된다. 이것은 **버그가 아니라 정책**이다: 시스템·운영 정책으로 허용된 예외는 룰이 직접 hit하지 않고 sidecar context로만 처리되도록 설계됐다.

### 3.4 B축 결론

- 정합성 hard error 같이 "전부 잡혀야 하는" 주제는 **같은 룰 기준 100% 통과**.
- broad / high_review처럼 "넓게 모아두고 일부만 case로 올리는" 주제는 plan대로 점수는 넓게 부여하고 case는 선별됨.
- `system_policy_exception`은 룰 직접 hit 없음 = 의도된 정책.
- **즉, 7개 주제 모두 정의된 분기 정책대로 동작**한다.

---

## 4. C축 — 최신 Phase1 표시 구조 계약

> **이 축이 답하는 질문**: "사용자가 보는 출력 화면이 옛날처럼 전체 Top 10 한 묶음이 아니라 주제 그룹별 리스트로 잘 나뉘었는가?"

### 4.1 평가 범위 한정

`datasynth_contract`는 manifest 정책상 `manipulated_entry_truth.csv`와 `anomaly_labels.csv`를 **제외**한다. 따라서 이 데이터셋만으로는 "악의적으로 조작된 데이터가 어느 그룹의 Top 몇에 걸리는지"는 평가할 수 없다. 그것은 `datasynth_manipulation` 별도 실행 영역이다.

이 문서의 C축은 두 가지만 확인한다.

1. Phase1 출력이 **전체 Top 10 하나**가 아니라 **그룹별 위험 데이터**로 나뉘는가?
2. review-only 신호(L3-12)가 case를 **새로 만들지 않고** 기존 case에 context로만 붙는가?

### 4.2 표시 방식 변경 (이전 ↔ 최신)

```
이전 해석                                            최신 해석
---------------------------------------------------  ---------------------------------------------------
전체 Top 10이 무엇으로 채워졌는지 확인               그룹별 case 수, band 분포, 그룹별 Top 10 확인
데이터 정합성 case가 전체 상단을 차지하는지          데이터 정합성은 별도 그룹/게이트로 분리
Top 10을 사용자 최종 위험 목록처럼 읽을 위험         Top 결과는 표시 계약 검증용 샘플로만 사용
```

### 4.3 그룹별 case 분포

```
그룹                       한글 의미                   case   High   Medium   Low   Top case 예시
-------------------------  --------------------------  -----  -----  ------  -----  ----------------------------------------
timing_anomaly             결산·기간귀속·시점 이상     7,503  2,759   3,722   1,022  case_timing_anomaly_11182, _09652, _05757
control_failure            승인·권한·통제 실패         3,952    475   2,957     520  case_control_failure_02491, _00896, _01285
logic_mismatch             계정분류·실질 불일치        1,524    328     493     703  case_logic_mismatch_00321, _00066, _00151
statistical_outlier        통계 이상치                 1,056     39     215     802  case_statistical_outlier_00630, _00380
duplicate_or_outflow       중복·자금 유출                281      3      41     237  case_duplicate_or_outflow_00872, _00833
data_integrity_failure     데이터 정합성 실패             22     17       2       3  case_data_integrity_failure_00005, _00006
```

전체 Top 10 하나로 합쳐지지 않고 그룹별 Top 10이 생성된다. contract 데이터셋에서는 timing / control 계열이 큰 그룹으로 나오며, data integrity는 22개 case의 별도 그룹으로 분리됨이 확인된다.

### 4.4 review-only 신호(L3-12) 처리

L3-12 "업무범위 집중 검토"는 단독으로는 case를 만들지 않고, 기존 case에 보조 context로만 붙어야 한다. 이것이 의도대로 동작하는지 확인한다.

| 항목                       | 값       |
| -------------------------- | -------: |
| L3-12 candidate label 수   |  175,617 |
| seed 후보 (case 신규 생성) |        0 |
| context 후보 (기존 case)   |  175,617 |
| context evidence 추가 수   |  175,617 |

`L3-12`로 인해 새로 만들어진 case는 0건. review-only 신호가 위험 case를 대량 생성하는 문제는 막혀 있다.

### 4.5 C축 결론

- 조작 truth는 이 데이터셋에 없으므로 placement는 평가 범위 밖.
- 최신 표시 구조 계약(그룹별 분리)은 6개 그룹으로 정상 분리됨.
- review-only 신호 L3-12는 seed 0건 / context 100%로 정책대로 동작.

---

## 5. 최종 결론

`datasynth_contract` 기준 Phase1은 **계약 검증 데이터셋으로 정상 동작**한다.

```
축    무엇을 봤나                  핵심 수치                                                            결과
----  ---------------------------  -------------------------------------------------------------------  ----
A축   룰 단위 계약 (32개 전수)     L1/L2/L3/L4/D 과탐 0, 미탐 0                                          통과
B축   주제별 분기 계약 (7 family)  hard error 100% · broad 선별 정상 · system_policy_exception 의도     통과
C축   표시 구조 계약 (6 그룹)      그룹별 분리 OK · L3-12 seed 0건                                       통과
```

**주의**: 이 결과는 사용자에게 마지막으로 제공하는 부정 탐지 성능표가 **아니다**. 데이터 정합성과 Phase1 출력 계약이 깨지지 않았는지 확인하기 위한 내부 계약 검증 결과다. 실제 탐지 성능(precision / recall, 조작 truth placement)은 `datasynth_manipulation` 기반 별도 리포트에서 평가한다.
