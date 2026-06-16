# PHASE1 Abnormal Overlay 검증 항목 카탈로그

## 목적

이 문서는 P3-2 PHASE1 부정 overlay 데이터가 실제 PHASE1 검증에 쓸 수 있는지 전수로 확인하기 위한 검사 항목 카탈로그다.
PHASE1 overlay 수정 중 새 버그가 발견되거나 재발 가능성이 있는 결함이 확인되면, 해당 검사는 본
카탈로그 또는 [phase1-rule-recall-overlay-verification.md](./phase1-rule-recall-overlay-verification.md)에
regression gate로 추가하고 이후 PHASE1 overlay 재생성의 자동 실행 대상에 포함한다.

NORMAL realism 카탈로그가 "정상 데이터가 실제 회사 GL처럼 자연스럽고 정합적인가"를 본다면, 이 문서는 "정상 baseline 위에 얹힌 부정/오류/통제위반 overlay가 39개 룰 전부에 대해 구조적으로 탐지 가능하고, truth 라벨과 자연 단위가 맞고, shortcut 없이 생성됐는가"를 본다.

이 문서는 구현 지시서가 아니라 검증 기준 문서다. PASS를 만들기 위해 detector threshold나 생성 값을 맞추는 fitting은 금지한다. 각 검사는 실제 감사/회계/통제 메커니즘과 PHASE1 rule contract를 기준으로 한다.

## 기준 문서

- `dev/active/datasynth-journal-realism-rebuild/p3-2-abnormal-overlay-contract.md`: P3-2 overlay 산출 계약과 39룰 coverage matrix.
- `dev/active/phase1-evasion-injection-spec.md`: 39룰 표준 위반 및 evasion 메커니즘.
- `docs/spec/DETECTION_RULES.md`: canonical PHASE1 룰 정의, suppress/drop/review-only 정책.
- `docs/spec/DETECTION_REFERENCE.md`: 감사기준서/FSS/실무 사례 근거.
- `dev/active/datasynth-journal-realism-rebuild/normal-data-realism-test-catalog.md`: 정상 subset 무회귀 기준.
- `src/detection/`: 실제 detector, case builder, FlowUnit/DocumentUnit 생성 경로.

## 판정 모델

| 판정 | 의미 |
| --- | --- |
| PASS | 요구 입력, truth, 구조, 오라클, 정상 무회귀가 증거와 함께 충족됨. |
| FAIL | 데이터 결함 또는 shortcut 때문에 PHASE1 검증 데이터로 부적합. |
| BLOCKED | 필수 파일/컬럼/sidecar/artifact가 없어 검사 자체가 불가능. PASS로 대체 금지. |
| MONITOR | 부적합은 아니지만 분포·볼륨·정책상 후속 관찰이 필요한 항목. |
| N/A | 해당 룰/검사에 구조적으로 적용되지 않음. 사유 필수. |

## 공통 원칙

1. truth/provenance는 sidecar 전용이다. journal/master/flow feature surface에 정답 평문을 노출하면 FAIL.
2. standard case와 evasion case를 섞어 측정하지 않는다. standard는 룰 구조 발화 검증, evasion은 suppress/drop/weak-signal 경계 검증이다.
3. 자연 단위는 `document` XOR `flow/macro group` 중 하나만 갖는다. 같은 부정을 document와 flow에 중복 count하면 FAIL.
4. 실제 PHASE1 catch/miss 성능 수치와 데이터 생성 검증을 구분한다. 이 카탈로그는 "데이터가 측정 가능하게 만들어졌는가"를 우선 검증한다.
5. detector에 맞춘 값 튜닝 금지. threshold 충족은 도메인상 명백한 표준 위반의 결과여야 한다.
6. normal subset은 P3-1 v29 realism gate와 같은 기준으로 무회귀여야 한다.

## A. 산출물·스키마 완전성

```text
검사ID  카테고리          정상 기대(무엇이 맞는가)                                      위반 예시                                      측정 방법                                      연결 산출물
------  ----------------  ------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------------------------------------
A01     산출물 존재       journal, labels, reports, manifest가 모두 존재한다.           labels나 acceptance report가 없다.             필수 파일 path 존재 확인.                     journal_entries.csv, labels/*, reports/*
A02     truth 스키마      p3_2_rule_truth 필수 컬럼이 모두 존재한다.                    rule_id/member_document_ids 누락.              헤더 set 대조.                                 labels/p3_2_rule_truth.csv
A03     provenance 스키마 p3_2_mutation_provenance 필수 컬럼이 모두 존재한다.           mutation_reason만 있고 original/mutated 없음.  헤더 set 대조.                                 labels/p3_2_mutation_provenance.csv
A04     acceptance 스키마 coverage/scan/normal regression 상태가 report에 기록된다.     acceptance가 숫자 없이 ACCEPT만 적음.          json key 존재 및 type 확인.                    reports/p3_2_overlay_acceptance.json|md
A05     UTF-8             한글 적요/문서가 mojibake 없이 UTF-8로 읽힌다.                깨진 한글, U+FFFD 다수.                       파일 read + mojibake 패턴 scan.                journal, labels, docs
```

## B. 39룰 Coverage 완전성

```text
검사ID  카테고리            정상 기대(무엇이 맞는가)                                           위반 예시                                      측정 방법                                      연결 룰
------  ------------------  -----------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------
B01     룰 목록 완전성      canonical 32 + auxiliary 7 = 39개 rule_id가 모두 truth에 존재한다.   IC03 또는 D02 누락.                            expected rule set - truth rule set = 0.        39 전체
B02     standard coverage   각 rule_id에 standard case가 최소 목표 건수 이상 존재한다.          L4-02 standard 0건.                            rule_id×case_kind count.                       39 전체
B03     evasion coverage    각 rule_id에 evasion case가 최소 목표 건수 이상 존재한다.           suppress/drop 케이스 누락.                     rule_id×case_kind count.                       39 전체
B04     rule count symmetry 표준/회피 count가 의도한 설계와 일치한다.                            일부 룰만 10건, 일부 0건.                      per-rule expected count 대조.                  39 전체
B05     synthetic 발화 가능 합성으로 발화 불가한 룰은 BLOCKED 사유가 명시된다.                  조용히 누락.                                   rule coverage status와 reason 확인.            실데이터 전용 가능 룰
B06     Benford 중복 방지   L4-02만 Benford alias를 갖고 별도 duplicate rule row를 만들지 않는다. Benford를 L4-02와 D별도 row로 중복 count.      rule alias mapping 확인.                       L4-02
```

## C. Truth·Provenance 정합

```text
검사ID  카테고리              정상 기대(무엇이 맞는가)                                               위반 예시                                      측정 방법                                      연결 룰
------  --------------------  ---------------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------
C01     자연 단위 XOR         truth row는 document_id 단위 또는 flow/group 단위 중 하나만 가진다.      document와 flow가 동시에 primary unit.          natural_unit_type별 member docs 형식 검사.      39 전체
C02     member docs 존재      truth의 member_document_ids가 journal에 모두 존재한다.                  truth doc id가 journal에 없음.                  anti-join count 0.                              39 전체
C03     base docs 추적        overlay/mutation이면 base_document_ids 또는 base selection reason이 기록된다. base가 빈데 reason 없음.                       base field와 provenance consistency 검사.       39 전체
C04     provenance sidecar    mutation field/original/mutated/reason이 sidecar에 기록된다.             provenance 없음.                                natural_unit_id별 provenance row count.          39 전체
C05     journal 비노출        mutation_reason/fraud_type/is_fraud 등 정답 평문 컬럼이 journal에 없다. journal에 employee_vendor 같은 정답 텍스트.      forbidden column scan.                          39 전체
C06     label-field sync      truth case_kind, rule_id, expected_surface가 coverage report와 일치한다. report는 39인데 truth는 38.                  truth와 coverage json groupby 대조.             39 전체
C07     중복 count 방지       같은 natural_unit_id가 여러 rule primary로 중복 계산될 경우 cross-rule intent가 명시된다. 동일 부정을 여러 룰 truth로 뻥튀기.       natural_unit_id duplicate group 분석.           39 전체
```

## D. 입력 Runnable 보강

```text
검사ID  카테고리             정상 기대(무엇이 맞는가)                                                위반 예시                                      측정 방법                                      연결 룰
------  -------------------  ----------------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------
D01     필수 컬럼 존재       해당 룰 detector가 요구하는 입력 컬럼이 journal/master/sidecar에 있다.   L1-04 approval_limit 없음.                     rule_id별 required field matrix 대조.          39 전체
D02     값 표현 가능         컬럼이 있어도 값이 전부 blank/default면 input_ready=false다.              is_period_end 컬럼만 있고 전부 blank.           nonblank/domain value count.                    L1-04/L2-01/L3-04 등
D03     정상 backfill        runnable 보강 컬럼이 부정 행에만 nonblank가 아니어야 한다.                approval_limit이 truth에만 존재.               truth vs normal nonblank rate 비교.             입력 보강 전체
D04     macro 입력           L4-01/L4-02/D01/D02는 계정·월·비교기간 모집단이 충분하다.                단일 전표만 주입하고 macro sidecar 없음.        group size, period count, baseline/current 대조. L4-01/L4-02/D01/D02
D05     IC 입력              IC01~IC03은 company pair, trading_partner, rec/pay 계정, 날짜, 금액이 있다. company_code와 partner namespace 불일치.       IC pair key completeness 검사.                  IC01~IC03
D06     graph 입력           GR01/GR03은 company graph node/edge로 구성된다.                          vendor/bank node만 있고 회사 cycle 없음.        graph node type, edge count, cycle length.       GR01/GR03
D07     approval 입력        L1-04/L1-05/L1-07/L1-09는 작성자/승인자/승인일/한도 정보가 있다.          승인자만 있고 권한 한도 없음.                  approval field completeness.                    L1-04/L1-05/L1-07/L1-09
D08     reversal 입력        L2-05/L3-09는 원전표/역분개/clearing/open-item linkage가 표현된다.        rolling amount만 있고 original link 없음.       reversal/open item link completeness.           L2-05/L3-09
```

## E. 표준 위반 구조 검증

```text
검사ID  카테고리              정상 기대(무엇이 맞는가)                                               위반 예시                                      측정 방법                                      연결 룰
------  --------------------  ---------------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------
E01     구조 발화 smoke       standard case는 sidecar 없이 rule 구조 조건을 만족한다.                 truth에는 L1-01인데 전표는 균형.               rule-specific deterministic probe.              39 standard
E02     L1 integrity          불균형/결측/무효계정/승인/기간/SoD 위반이 각 룰 정의와 일치한다.         L1-05 truth인데 created_by≠approved_by.         L1 rule probe.                                  L1-01~L1-09
E03     L2 duplicate/class    duplicate, capitalization, reversal 구조가 자연 flow로 존재한다.         L2-03이 같은 document 안 metadata만 다름.       pair/reversal/account-text probe.               L2-01~L2-05
E04     L3 context            source/time/cutoff/semantic/high-risk/context 구조가 실제 rule input에 있다. L3-07 truth인데 date_gap 0.                 date/source/text/account probe.                 L3-01~L3-12
E05     L4 analytic           macro/amount/account-pair/time/batch 구조가 모집단 단위로 존재한다.       L4-02 표본 20건으로 Benford 주입.              population-level probe.                         L4-01~L4-06
E06     IC reconciliation     unmatched/amount mismatch/date mismatch가 pair 단위로 확인된다.          self-balanced single document만 존재.           rec/pay pair reconciliation probe.              IC01~IC03
E07     Graph                 circular/price asymmetry가 회사 edge graph에서 확인된다.                 2-cycle만 있고 3-hop+ 없음.                    cycle/pricing sidecar probe.                    GR01/GR03
E08     Variance              D01/D02가 계정·월 단위 변화로 표현된다.                                  개별 row flag만 있음.                          period distribution probe.                      D01/D02
```

## F. Evasion 경계 검증

```text
검사ID  카테고리                 정상 기대(무엇이 맞는가)                                                 위반 예시                                      측정 방법                                      연결 룰
------  -----------------------  -----------------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------
F01     evasion 전수             39개 룰 각각 suppress/drop/weak 경계 케이스가 존재한다.                   L2-02만 evasion 있고 IC/D 없음.                rule_id×case_kind=evasion count.                39 evasion
F02     standard와 분리          evasion case는 standard positive 검증 분모와 분리된다.                    evasion miss를 standard recall 실패로 계산.     truth case_kind split 확인.                     39 evasion
F03     suppress/drop 재현       문서/흐름이 실제 suppress/drop 조건을 흉내 낸다.                          단순히 rule flag=false만 넣음.                 detector suppress predicates와 구조 대조.        L2-02/L2-03/L2-04/L2-05 등
F04     weak-signal 경계         review-only/context-only 룰은 confirmed로 강제 승격시키지 않는다.         L3-06 단독을 confirmed fraud로 설계.            expected outcome policy 대조.                   L3-05/L3-06/L3-08/L4-05/L4-06
F05     macro evasion            macro 룰 evasion은 개별 전표 정상성 속에 account/month 구조만 움직인다.   row에 D01_EVASION token.                       row normality + group movement 검사.            L4-02/D01/D02/GR
F06     PHASE2 인계성            PHASE1 회피 케이스는 PHASE2 타깃 owner/expected_surface가 명시된다.        miss가 그냥 unknown.                           truth expected_surface/evasion_vector 확인.     39 evasion
```

## G. Anti-Fitting·Shortcut Scan

```text
검사ID  카테고리             정상 기대(무엇이 맞는가)                                                위반 예시                                      측정 방법                                      연결 룰
------  -------------------  ----------------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------
G01     forbidden columns    journal/master에 truth/provenance/label 컬럼이 없다.                      mutation_reason이 journal에 있음.              deny-list header scan.                          39 전체
G02     all-column oracle    단일 컬럼 값이 N>=5, normal=0으로 truth를 분리하지 않는다.                header_text 하나가 truth 전용.                 value purity scan.                              39 전체
G03     exact timestamp      특정 timestamp가 truth 전용으로 반복되지 않는다.                          2024-12-30 10:05가 truth 전용 20건.            posting/approval/document date exact scan.       time/timing 전체
G04     exact amount         특정 금액이 truth 전용으로 반복되지 않는다.                               150,000,000이 truth 대부분.                   amount value purity scan.                       금액 룰 전체
G05     code namespace       회사/거래처/user/source/document_type이 truth 전용 신규 namespace를 쓰지 않는다. C004가 truth에만 있음.                 categorical namespace overlap scan.             39 전체
G06     reference prefix     reference/document_number prefix가 truth 전용이 아니다.                    P3FRAUD- prefix.                               prefix purity scan.                             duplicate/IC/reversal
G07     sidecar-only truth   truth/provenance sidecar 값은 feature surface scan에서 제외하고 별도 보존한다. sidecar를 제거해 검증 불가.              sidecar existence + journal exclusion.          39 전체
G08     threshold fitting    위반 정도가 detector threshold 직상/직하에 과도하게 몰리지 않는다.          모든 IC mismatch가 5.01%.                      distance-to-threshold distribution.             threshold 룰
G09     normal overlap       부정 feature 값은 정상 분포 안에도 충분히 존재한다.                       truth amount/user/source만 고유.               truth value normal support ratio.               39 전체
```

## H. 정상 무회귀·오버레이 격리

```text
검사ID  카테고리              정상 기대(무엇이 맞는가)                                               위반 예시                                      측정 방법                                      연결 기준
------  --------------------  ---------------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------
H01     source immutability   normal v29 원본 디렉터리는 수정되지 않는다.                             source journal timestamp/hash 변경.             source path hash/mtime 비교.                    v29
H02     normal subset gate    출력 데이터에서 truth member docs를 제외한 normal subset은 realism gate를 통과한다. 정상 subset A01/M01 FAIL.                    normal subset verifier 실행.                    normal realism 29
H03     overlay accounting    의도된 L1-01 불균형 외에는 overlay 전표가 차대변 의미 없이 깨지지 않는다. evasion 전표가 무작위 불균형.                 overlay doc balance by intended rule.           A01/L1-01
H04     financial statement   정상 subset의 M01~M07 재무제표 정합은 유지된다.                          overlay가 normal balance files를 오염.          normal subset GL/TB/subledger gate.             M01~M07
H05     master integrity      overlay가 참조하는 account/vendor/user/company가 master에 존재하거나 의도된 L1-03만 예외다. 무효 user 대량 생성.                         master anti-join with exception by rule.         L1-03 외 전체
H06     noise parity          data quality noise가 truth shortcut으로 쓰이지 않는다.                    truth만 line_text blank.                       noise rate truth vs normal 비교.                L1-02/L3-08
H07     no Python patch       생성 결함을 Python 후처리로 덮지 않는다.                                 generated CSV만 수동 수정.                     provenance/build command 확인.                  DataSynth 원칙
```

## I. PHASE1 실행·측정 준비성

```text
검사ID  카테고리                 정상 기대(무엇이 맞는가)                                               위반 예시                                      측정 방법                                      연결 경로
------  -----------------------  ---------------------------------------------------------------------  ---------------------------------------------  ---------------------------------------------  ----------------
I01     detector runnable        39개 룰 detector가 입력 부재로 skip되지 않는다.                         L4-01 required column missing.                 detector preflight skip reason 집계.            PHASE1
I02     actual fire standard     standard case가 해당 rule 또는 명시된 accepted substitute에서 발화한다.  L1-05 standard 미발화.                         rule_id별 detector hit join.                    P2-4 이후
I03     evasion outcome          evasion case는 expected outcome과 일치한다.                              suppress 기대인데 confirmed로 승격.            evasion truth vs rule output policy 대조.       P2-4 이후
I04     unit linkage             detector hit가 DocumentUnit/FlowUnit 자연 단위와 연결된다.               raw row hit만 있고 unit 없음.                  unit builder join by doc/flow.                  P2-4
I05     no duplicate counting    한 natural unit이 여러 case로 중복 review_cost를 부풀리지 않는다.        same flow가 5개 case로 분리.                  unit id aggregation check.                      P2-4
I06     macro sidecar            macro/graph/IC finding은 row-level confirmed detail이 아니라 적절한 sidecar/unit으로 표면화된다. Benford row flag로 오해.                     output artifact type check.                     L4/D/IC/GR
I07     score language           PHASE1 결과 언어가 fraud 확정이 아니라 review/exception/finding 구분을 지킨다. is_fraud=true를 확정 fraud로 출력.          export/case language smoke.                    UI/export
I08     measurement split        standard recall, evasion behavior, normal FP를 별도 표로 낸다.           한 precision/recall 숫자로 뭉침.              report schema check.                            PHASE1 report
```

## J. 룰별 Required Evidence Matrix

```text
검사ID  카테고리      정상 기대(무엇이 맞는가)                                      측정 방법
------  ------------  ------------------------------------------------------------  --------------------------------------------------
J01     L1             L1-01~L1-09 각각 integrity/control/date/schema evidence 보유. rule_id별 field/probe checklist.
J02     L2             L2-01~L2-05 각각 threshold/duplicate/capex/reversal flow 보유. pair/flow/reversal artifact checklist.
J03     L3             L3-01~L3-12 각각 semantic/source/time/cutoff/text/account/user evidence 보유. context probe checklist.
J04     L4             L4-01~L4-06 각각 macro/amount/pair/time/batch 모집단 evidence 보유. population artifact checklist.
J05     IC             IC01~IC03 각각 unmatched/amount/date reconciliation evidence 보유. IC reconciliation artifact checklist.
J06     GR             GR01/GR03 각각 company graph cycle/pricing evidence 보유. graph artifact checklist.
J07     D              D01/D02 각각 prior/current period distribution evidence 보유. variance artifact checklist.
```

## K. 리포트 요구사항

```text
검사ID  카테고리           정상 기대(무엇이 맞는가)                                      위반 예시
------  -----------------  ------------------------------------------------------------  ---------------------------------------------
K01     수치 요약          rules, truth units, overlay docs/rows, normal docs/rows를 기록. "완료"만 있고 숫자 없음.
K02     per-rule 표        rule_id별 input_ready/standard/evasion/fire/oracle/normal regression 상태 기록. 누락 룰이 숨겨짐.
K03     FAIL/BLOCKED 노출  실패와 미실행은 PASS로 숨기지 않는다.                         actual fire 미실행인데 ACCEPT.
K04     artifact path      검증에 쓴 데이터셋/리포트/명령 path를 기록한다.                어떤 버전을 썼는지 불명확.
K05     반복 이력          shortcut 발견과 수정 반복을 debugging에 남긴다.               v1 실패 이유 없음.
```

## v10 현재 적용 메모

- `data/journal/primary/datasynth_semantic_v1_p3_2_overlay_20260607_v10` 기준으로:
  - B01~B04: local truth count 기준 충족.
  - G01: forbidden journal truth/provenance columns 0.
  - G02: local all-column oracle scan 0 findings.
  - I02/I03/I04/I06/I08: P2-4 이후 PHASE1 detector 실행 단계에서 측정해야 한다.
  - H02/H04: output normal subset 전용 realism gate 재실행 필요.

## 구현 우선순위

1. Gate 0: A/B/C/G01/G02. 산출물·truth·누출 검증. 실패 시 detector 실행 금지.
2. Gate 1: D/E/F/H. 룰별 구조와 evasion, 정상 무회귀 검증.
3. Gate 2: I/J/K. PHASE1 실행 후 actual fire, unit linkage, 측정 리포트 검증.
