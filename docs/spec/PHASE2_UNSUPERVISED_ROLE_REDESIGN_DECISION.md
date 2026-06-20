# PHASE2 Unsupervised(VAE) 역할 재설계 판단

> **C안 3-surface 정합 (2026-06-14, SoT [PHASE1_TIER_EVIDENCE_BASIS.md §7](PHASE1_TIER_EVIDENCE_BASIS.md))**: VAE 는 **PHASE2 단독 surface** 로 확정한다. graph·relational·시계열 family 는 PHASE2 가 아니라 **PHASE1-2 family** 에 귀속한다(결정론·근거·명명 탐지). 본 문서의 joint-rarity companion 결론(§6)은 유지하되, 과거에 family 와 VAE 를 같은 PHASE2 로 묶거나 한 점수·한 리스트로 병합하던 framing 은 **폐기**한다. 3 surface(PHASE1-1 룰 / PHASE1-2 family / PHASE2 VAE)는 절대 비병합 — 독립 탭/뷰/큐로 표시하고 단일 점수로 합치지 않는다. VAE 는 "정상 분포 밖 비정형 companion surface"이며 detector·부정 확정이 아니다("이상치=부정" 표현 금지).

> 상태: §6 target 재정의 확정 (2026-06-02). semantic-clean 데이터 대기(BLOCKED).
> §0~§5는 row→document 단위 + "broad statistical review" 프레이밍 전제의 경위 기록이며,
> §6이 VAE target·역할을 확정하고 §5의 "broad statistical review" 프레이밍을 대체한다.
> 측정 근거: `artifacts/unsupervised_v33d_exact_owner_surface_fixed5_20260601.json`,
> `artifacts/unsupervised_document_review_surface_20260601.json`,
> `tests/modules/test_services/test_unsupervised_companion_readiness.py` (locked 값),
> `dev/active/doc-level-ranking/doc-level-ranking-context.md` (Phase A 단위 측정).
> 데이터셋: `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d` (truth doc 620,
> fictitious statistical primary 40, statistical/broad companion 404).

---

## 0. 한 줄 결론 (먼저)

**재설계 필요.** 단, 삭제도 아니고 완전 격하도 아니다.

VAE/Unsupervised를 **row anomaly queue에서 document-level anomaly review surface로
재정의**한다. 이미 lock된 "companion / broad statistical review / not fraud primary"
의미 프레이밍은 유지하고, **review 단위만 row-case → document-case로 구조 변경**한다.
세 선택지 중 **(2) document-level anomaly review surface로 재설계**를 선택한다.
(3) "보이지 않는 context-only로 완전 격하"는 선택하지 않는다 — 측정상 PHASE1 밖
추가분과 설명 가능성이 0이 아니므로, 단일 VAE review list로서의 제품 가치가 남아 있다.

근거 요약(측정):

```
역할        surface                          TOP500 매칭   repeated_normal_pressure
primary     native_row_queue                 0 / 40        1.00   ← 폐기 대상
primary     row soft-guard baseline          10 / 40       0.24   ← historical diagnostic
companion   native_row_queue                 3 / 404       0.99   ← 폐기 대상
companion   row soft-guard baseline          54 / 404      0.18
```

native row queue는 primary·companion 양쪽에서 TOP500 거의 무신호 + 반복정상 100%
점유. row soft-guard baseline은 같은 VAE score·gate에서 의미 있는 회수와 낮은
pressure를 보였지만, P5 document-case default 측정은 pressure spike를 보였다. 즉
"VAE가 약한 것"이라기보다 **row 단위 surface와 정당화되지 않은 context ranking 양쪽을
분리해 재설계해야 하는 것**이다.

---

## 1. 현재 VAE 설계가 제품 목표와 어긋나는 지점

### 1-1. row-level anomaly와 document/case-level review의 단위 불일치

- VAE detector는 row 단위 reconstruction error → row anomaly score를 만든다.
  현재 case builder도 `unit_type="row"`, 즉 **1 UnsupervisedCase = 1 row**다.
- 제품에서 감사인이 검토하는 단위는 document(전표)다. 한 document의 여러 row가
  각각 독립 case로 분리되어 큐에 올라간다.
- 결과: row는 많이 뜨지만, 동일 document의 신호가 **하나의 review 단위로 응축되지
  않는다.** 같은 전표가 row마다 흩어지고, 반복되는 정상 패턴 row(분개 라인 수가
  많은 정상 전표)가 상단을 점유한다.
- doc-level-ranking Phase A에서 이미 정량 확인된 원리와 같은 구조다: case grouping은
  단순 UI 묶음이 아니라 **evidence bundle**이며, 단위가 풀리면 corroboration 신호가
  사라진다. VAE는 이 묶음 자체가 없는 상태로 row를 흘려보내고 있다.

### 1-2. fraud recall로 해석할 때 생기는 문제

- v33d native_row_queue primary recall은 TOP100/500/1000/10000 **전 구간 0/40**이다.
  responsibility native exact join도 0/40. fraud primary recall 관점에서는 사실상 0.
- 이 수치를 "VAE가 fraud를 못 잡는다"로 해석하면 안 된다. fictitious statistical
  primary 40건은 **금액 p95 비율이 정상 대비 약 306배**인, 통계적으로는 극단이지만
  의미상 "통계 이상치"일 뿐 fraud 확정 대상이 아니다. 동시에 정상 모집단에도
  통계 극단(결산 대규모 전표 등)이 다수 존재해 row 큐 상단을 정상이 점유한다.
- 따라서 fraud recall을 VAE의 1차 평가축으로 쓰면 (a) 실패로 오판하거나 (b) 회수율을
  올리려 gate/threshold/weight를 truth에 맞추는 **fitting 유혹**이 생긴다. 둘 다
  정책 위반이다("이상치=부정" 금지, truth fitting 금지).

### 1-3. PHASE1 blind-spot 보완 가치가 현재 수치상 약한 이유

- companion readiness 테스트가 lock한 권장 surface(soft guard, fixed5) 기준
  **PHASE1 후보(candidate) 이상 밖 신규 추가**는 TOP100 5건 / TOP500 11건 /
  TOP10000 47건이다(`top*_phase1_candidate_or_above_outside_truth_docs`).
- 즉 TOP500에서 VAE가 "PHASE1이 후보로조차 올리지 못한" 전표를 새로 들어 올리는 양은
  11건 수준이다. native_row_queue로 보면 이 값은 거의 0에 수렴한다(companion TOP500
  candidate-outside 2건).
- 이 수치로는 VAE를 **강한 blind-spot 보완 family**나 **fraud primary recall family**로
  주장할 수 없다. 다만 0은 아니다 — document-priority surface에서는 PHASE1 즉시검토
  밖 95건 / 후보 밖 11건(TOP500)을 deterministic하게 제공한다. **약하지만 존재하는
  보완**이며, 이것이 격하가 아니라 재설계를 선택하는 근거다.

---

## 2. VAE를 없애지 않고 재설계할 이유

### 2-1. 포트폴리오에서 full-population ML anomaly surface가 주는 제품 가치

- 본 제품의 포지셔닝은 "MindBridge/KPMG Clara 핵심 로직의 오픈소스 재현"이다.
  rule family만으로는 "전수 모집단에 대한 ML 기반 이상거래 탐지"라는 제품 서사가
  비어 버린다. VAE는 이 서사를 채우는 **유일한 비지도 full-population 신호원**이다.
- 평가 정책상으로도 PHASE2 자체 목표는 truth recall이 아니라
  `unsupervised_selection_score`(reconstruction/KL 기반)이다. 즉 VAE의 존재 정당성은
  recall이 아니라 "전수 모집단 이상 신호 + 설명"에 있다.

### 2-2. rule family가 설명하지 못하는 unusual document를 보조로 드러내는 가치

- rule family는 사전 정의된 위반 패턴만 본다. VAE는 규칙으로 명명되지 않은
  "분포상 드문 전표 형상"을 드러낸다. 측정상 그 양은 작지만(TOP500 후보 밖 11건),
  이는 rule이 구조적으로 못 보는 영역이다. 보조(companion) 신호로서 의미가 있다.

### 2-3. 감사인이 "왜 봐야 하는지"를 설명으로 볼 수 있는 가치

- 이미 explainability surface 작업(완료)으로 top contributing feature → reason tag
  (`unusual_timing` / `amount_outlier` / `vendor_frequency_anomaly` 등)와 한국어
  라벨이 case에 부착된다. v33d 측정에서 `top_features_availability = 1.0`로 전 surface
  에서 설명이 항상 붙는다.
- 즉 VAE는 "점수만 있고 설명 없는 블랙박스"가 아니라, **document마다 왜 이상한지의
  context(top feature / 금액 tail / 결산 근접 / 계정·프로세스 희소성)를 제시할 수
  있는** 상태다. 이 설명 자산을 버리는 것은 손실이다.

---

## 3. 재설계의 목표 방향

> 아래는 "무엇을 목표로 하는가"이며 구현 방법이 아니다.

1. **row anomaly queue가 아니라 document-level anomaly review surface.**
   - 과거 soft-guard diagnostic은 document proxy 재정렬의 가능성을 보였지만, P5 결과상
     이를 product default ranking으로 확정하지 않는다. 목표는 **review 단위 자체를
     document로 승격**하되 context 필드는 표시 전용으로 유지하는 것이다.

2. **하나의 document = 하나의 review case.**
   - 동일 document의 여러 anomalous row를 분리 case로 흩지 않고, 하나의 review case로
     묶는다. row는 그 case 내부의 evidence row로 표시한다(doc-level-ranking이 확인한
     evidence-bundle 원리와 정합).

3. **VAE score는 raw signal, 제품 surface는 document-level evidence/context로 해석.**
   - score는 정렬·gate의 원천 신호로만 쓰고, 사용자에게 보이는 것은 document 단위의
     top feature / reason tag / 금액 tail / 결산 근접 / 계정·프로세스 희소성이다.
   - score를 truth/owner/scenario/PHASE1 rank/matched result로 보정하지 않는다.

4. **repeated-normal pressure를 낮추고 reviewer burden을 통제.**
   - native row queue의 pressure 1.0(반복 정상 100% 점유)을 surface에서 구조적으로
     억제한다. 단, pressure 억제를 recall fitting의 우회로로 쓰지 않는다(가드 유지).

5. **평가축 재정의.**
   - 평가는 fraud primary recall이 아니라 **review usefulness / anomaly evidence
     contribution**으로 한다. 주요 축:
     - PHASE1 즉시검토 밖 / 후보 밖 신규 document 추가량(deterministic)
     - explanation quality(top feature/reason tag 부착률)
     - repeated_normal_pressure (낮을수록 좋음)
     - account/process concentration, amount-tail, period-end 같은 설명 가능 context
   - fraud recall은 진단(diagnostic) 보조 지표로만 남기고, 제품 판정 기준에서 제외.

---

## 4. 성공 기준 (재설계가 옳았는지 판정하는 조건)

| # | 기준 | 측정 방법 | 현재(v33d) 베이스라인 |
|---|------|-----------|----------------------|
| S1 | PHASE1 즉시검토 밖/후보 밖에 의미 있는 신규 review document 제공 | candidate-outside / immediate-outside doc 수 | TOP500 후보 밖 11 / 즉시검토 밖 95 (soft guard) |
| S2 | 정상 반복 문서가 상단을 과점하지 않음 | repeated_normal_pressure (낮을수록 우수) | native 1.00 → soft guard 0.18~0.24 |
| S3 | 설명 가능 context가 항상 붙음 | top_features_availability, reason tag 부착률 | 1.0 (전 surface) |
| S4 | 단일 VAE review list UX로 감사인이 이해 가능 | 단일 list + document 단위 + 설명 컬럼 | 정렬은 document-priority, 단위는 아직 row |
| S5 | truth fitting 없이 DataSynth 재생성에도 방향성 유지 | 가드 플래그 전부 false 유지 | `anti_fitting_guardrails` 전 항목 false |

판정 규칙:
- 재설계 후에도 S1(신규 추가분)이 native 수준(≈0)으로 회귀하면 → 그때는 (3) 완전
  격하를 재검토.
- S2 pressure가 추가분과 trade되어 다시 0.5 이상으로 오르면 → surface 설계 실패로
  보고, recall fitting으로 pressure를 깎는 우회는 금지.
- S5 가드(`truth_or_owner_metadata_used_as_selector`,
  `datasynth_changed_to_match_vae_score`, `vae_score_threshold_recall_fitting` 등)가
  하나라도 true가 되면 재설계 자체를 무효로 간주.

### 4-1. P5 document-case surface 측정 결과 (2026-06-02)

측정 산출물: `artifacts/unsupervised_document_review_surface_20260601.json`
누적 기록: `artifacts/unsupervised_document_review_surface_history.json`

측정 범위는 `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d` controlled data에서의
detector 거동이다. production recall/precision 또는 운영 성능 주장이 아니며, truth/owner/
scenario/PHASE1 rank는 selector/order 입력으로 쓰지 않았다. q95 gate, VAE score, threshold,
DataSynth 입력도 변경하지 않았다.

| 기준 | row soft-guard baseline | document-case default 측정 | 판정 |
|---|---:|---:|---|
| S1 primary TOP500 후보 밖 추가 | 5 | 0 | row 대비 -5 |
| S1 companion TOP500 후보 밖 추가 | 31 | 3 | row 대비 -28 |
| S2 TOP500 repeated_normal_pressure | 0.18~0.24 | 1.00 | spike |
| S3 top feature / reason tag attach | 1.0 | 1.0 / 1.0 | 충족 |
| S4 review unit | row-like | document | 충족 |
| S5 guard flags | false 유지 | false 유지 | 충족 |

P5 pressure watchpoint 결론: **penalty 0.0 유지 가능으로 확정하지 않는다.** 단순
document-grouping만으로 repeated-normal pressure가 soft-guard 범위에 들어간다는 가설은
이번 측정에서 기각됐다. 다음 단계는 recall fitting 없이, 정당화 가능한 document-level
pressure 신호를 먼저 설계·측정하는 것이다. 현재 product default는 context ranking이 아닌
`document_case_max_score_order`이며, amount-tail / period-end / account-process rarity는
display-only context로만 사용한다.

Testability class 해석:
- Class A: amount-tail, period-end, posting time/manual, reversal, related-party rarity.
- Class B: account/process rarity, document/text mismatch, counterparty mismatch. 특히
  `account_process_rarity`는 synthetic mixing artifact 가능성이 있어 Class B로만 해석한다.
- T4-14 기말일평균 WARNING(2.60x < 3x)은 under-shoot footnote이며 본 P5 판정의
  blocking 사유가 아니다.

---

## 5. 명확한 결론

세 선택지에 대한 판정:

| 선택지 | 판정 | 이유 |
|--------|------|------|
| (1) native row queue 계속 개선 | **기각** | primary 0/40, companion 3/404, pressure 1.0. row 단위 구조 자체가 제품 검토 단위와 불일치. 개선 여지가 fitting 외에 없음. |
| (2) document-level anomaly review surface로 재설계 | **조건부 채택** | review 단위(document)와 설명 부착률 1.0은 충족. 단 P5에서 pressure spike가 확인되어 context ranking/penalty 0.0 default는 확정하지 않음. |
| (3) product family에서 내리고 companion context로만 | **부분만 채택(프레이밍)** | "fraud primary 아님 / broad statistical companion" 의미 프레이밍은 이미 lock되어 있고 유지. 그러나 보이지 않는 context-only로 완전 격하하지는 않음 — PHASE1 밖 추가분·설명 가치가 0이 아니므로 단일 VAE review list로 노출 가치가 있음. |

**최종: 재설계 필요 (document-level anomaly review surface로 재정의).**

- 제품 family로서 **유지**한다. 단 review 단위를 row-case → document-case로 구조
  변경하고, 기본 정렬은 context-free document max-score order로 둔다.
- 의미 프레이밍은 **현행 유지**: companion / broad statistical review / not fraud
  primary. fraud recall은 diagnostic 보조 지표로 강등(이미 lock).
- 평가축은 review usefulness / evidence contribution / pressure / explanation으로
  전환하고, fraud primary recall을 제품 판정 기준에서 제외한다. P5 결과 기준으로
  penalty 0.0 유지 가능은 확정하지 않았으며, P6 전 정당화 가능한 document-level
  pressure 신호가 필요하다.
- 모든 anti-fitting 가드(truth/owner/scenario/PHASE1 rank 입력 금지, gate/threshold/
  weight를 recall에 맞춘 조정 금지, DataSynth를 VAE score에 맞춘 조작 금지)를 재설계
  전 구간에 유지한다.

> 다음 단계(P6): P5 pressure spike 결론을 기준으로 문서·검증 결과를 정리하고,
> recall fitting 없이 정당화 가능한 document-level pressure 신호 설계 여부를 별도 판단한다.

---

## 6. 확정 — VAE target 재정의 (2026-06-02, §5 supersede)

§0~§5는 review 단위(row→document)와 "broad statistical review companion" 프레이밍을
전제로 진행됐다. P4/P5 측정 + 후속 설계 분석에서 더 근본적인 결함이 확인되어, 본 §6이
VAE의 target·역할을 확정하고 §5의 "broad statistical review" 프레이밍을 대체한다.

### 6-1. 근본 결함 (왜 바꾸는가)

1. **target 미정의.** VAE 입력은 설계된 탐지 대상이 아니라 anti-leakage 잔여 컬럼이다.
   `src/preprocessing/phase2_plan.py::_decide_column`은 label/leakage/identifier/datetime
   제외 후 numeric·boolean·categorical을 include-by-default 한다. "VAE가 무엇을 탐지한다"가
   설계된 적이 없다.
2. **leakage deny가 고신호 축을 제거.** `src/preprocessing/constants.py::LEAKAGE_DENY_COLUMNS`
   가 금액(amount_zscore 등)·승인·라운드(is_round_number)·임계·IC·suspense·first_digit를
   학습 입력에서 제거. VAE는 이 축을 타깃할 수도 없다.
3. **잔여 해석 feature가 PHASE1·family와 7/7 중첩** (`config/unsupervised_reason_tags.yaml`):
   amount_z→L4-01/03, round_amount→L2-01/is_round_number, posting_weekend→L3-05,
   posting_after_hours→L3-06, posting_lag_days→L3-07, manual_entry→L3-02,
   trading_partner_frequency→L3-03/relational. DETECTION_RULES.md 줄 2596이 이미
   "UnusualTiming → L3-05/06 완전 중복 → 별도 유형 불필요"로 동일 판정.
4. **"broad statistical review" 프레이밍 자체가 PHASE1 L4와 충돌.** statistical_outlier
   (L4-01/02/03/06)는 이미 PHASE1 topic이다. VAE를 "통계 이상치 surface"로 부르면 L4 재발견.

결과: 현재 VAE는 PHASE1·타 family와 차별점이 0이고, 이것이 PHASE1 밖 추가분 ~0
(P5: primary 0, companion 3)의 직접 원인이다.

### 6-2. 확정 target — 다변량 조합 비정형성 (multivariate joint-combination atypicality)

개별 축은 어떤 PHASE1 룰 임계도 안 넘고 어떤 family 관계도 안 울리지만, **구조 범주형의
조합**(`account_subtype × business_process × counterparty_type × document_type ×
line_text_family`, 보조적으로 timing/source/manual을 joint context로)이 **jointly 희소·
부정합**한 전표를 감사인 주의로 올린다.

- 비중첩 근거: 모든 PHASE1 룰·PHASE2 family는 단일 축/관계를 본다. "축들 사이의 정합성
  (joint coherence)"은 누구도 안 본다. autoencoder만이 multivariate joint distribution을
  모델링한다 — 이것이 VAE의 유일한 존재 근거.
- testability matrix(`dev/active/datasynth-journal-realism-rebuild/phase2-vae-testability-matrix.md`)
  Class B(account-process-counterparty / document-account / text-family mismatch)와 일치.

### 6-3. 구현 방향 (확정 후 따라오는 것)

1. **"statistical / 통계 이상치" 프레이밍 폐기.** VAE = "조합 비정형성 / 형상이 드문 문서
   주의 surface". (fraud 아님·companion 성격은 유지.)
2. **단일 축 신호를 VAE 입력·score에서 명시 배제**: 금액 크기·라운드·duplicate identity·
   reciprocal matching·단일축 timing burst·엔티티 신규성. 이들은 PHASE1/family 소유.
3. **입력 feature 재설계 = semantic 구조 범주형 중심**(matrix "Training Feature Candidates").
   잔여-컬럼 include-by-default 폐기.
4. **score/gate를 joint-rarity 기준으로** 재정의. q95/threshold/weight를 recall에 맞춰 튜닝 금지.
5. P1~P3 산출(document-case 모델·집계·계약)은 **evidence carrier로 유지** — 단위 구조는
   맞았다. 바뀌는 것은 target·feature·framing.

### 6-4. 상태 — semantic-clean 데이터 대기 (BLOCKED)

- 확정 target은 Class B라 **정상 모집단이 semantic-clean이어야 유효**하다
  (account×process×counterparty×text 정합). 현재 합성 정상 데이터는 이 정합이 깨져 있고,
  semantic-clean 데이터는 **별도 트랙(datasynth journal realism)에서 생성 중**이다.
- 그 데이터가 오기 전까지 VAE는 **차별화된 product surface가 아니라 diagnostic/companion으로만
  유지**한다. 입력 feature 재설계·평가는 데이터 도착 후 착수.
- 합성 데이터 평가는 **mutation-type 분리 mechanism 증거**까지로 한정(Class B). production
  recall/precision 주장 금지. 산업·정책(Class C)·사용자/네트워크 행동(Class D)은 합성 검증
  불가 → 실데이터 영역으로 명시 제외.

### 6-5. anti-fitting 가드 (전 구간 유지)

truth/owner/scenario/PHASE1 rank/matched result를 model·selector·ranking 입력 금지.
q95/score/threshold/weight를 recall에 맞춰 조정 금지. DataSynth를 VAE score에 맞춰 조작
금지. "이상치=부정" 표현 금지.

---

## 7. VAE Frozen Design Spec (2026-06-02, 데이터 생성 전 동결)

> **목적**: "데이터 보고 설계 = fitting"을 원천 차단한다. 본 spec은 datasynth realism
> **contract 스키마 계약**(`dev/active/datasynth-journal-realism-rebuild/`)에만 의존하며,
> 완성된 데이터의 내용·truth·평가 metric을 보지 않고 동결한다. 데이터 도착 시 수행은
> **비지도 학습 + 1회 검증**이고, metric을 보며 설계를 수정하지 않는다.

### 7-0. Fitting을 가르는 선 (동결 근거)

| 설계를 무엇에 맞추는가 | 판정 |
|---|---|
| data contract / schema (컬럼 의미·cardinality) | OK — truth 아님 |
| audit 원칙 / 비중첩 분석 (§6) | OK |
| 정상 데이터 분포 (라벨 없는 비지도 학습) | OK — 학습 자체 |
| truth/owner/scenario 라벨, eval metric(S1·recall) | ✗ FITTING — 금지 |

### 7-1. Input feature set — v1 (FROZEN, 구조 조합 정합성 전용)

`dataset-regeneration-contract.md` §Required Metadata Columns의 semantic 구조 범주형만
입력으로 동결한다 (normal/abnormal 모두 채워짐이 계약):

- `event_type`, `business_process`
- `debit_account_subtype`, `credit_account_subtype`
- `counterparty_type`, `document_type`, `line_text_family`

VAE는 이 7개 범주형의 **joint reconstruction**만 학습한다. 어떤 단일 feature 임계도 아니다.

### 7-2. 명시 배제 입력 (역할 분리, §6 비중첩)

- 금액 크기/zscore, `is_round_number`, threshold → PHASE1 L4 / L2-01
- 단일축 timing(weekend/after_hours), posting_lag → L3-05/06/07
- manual 단일 flag → L3-02 / duplicate identity → duplicate / reciprocal → IC /
  entity novelty·frequency → relational
- 모든 label·provenance: `scenario_id`, `is_anomaly`, `rule_*`, `mutation_type`,
  `base_event_type`, `mutated_field`, `original_value`, `mutated_value`, `reason`,
  `detection_surface_hints` (← scoring 이후 평가 슬라이싱에만 사용)
- **v2 후보(동결 아님)**: 구조 × 행동맥락(source/manual, posting_hour bucket) joint 확장은
  별도 audit 정당화 + held-out generator config 검증을 거쳐야 하며 v1에 포함하지 않는다.

### 7-3. Scoring (FROZEN)

- autoencoder reconstruction error를 구조 조합 joint에 대해 산출 → zero-preserving ECDF
  (기존 패턴 유지). document 집계 = gated row max (§ approved B3, document-case는 evidence
  carrier로 유지).
- score는 joint-rarity 신호. q95 gate·threshold·weight는 recall로 튜닝 금지.

### 7-4. Acceptance criteria (측정 전 FROZEN, Class B mechanism evidence 한정)

데이터 도착 후 **1회** 측정:

- **A1 mechanism**: 주입된 semantic-mismatch `mutation_type`(account-process-counterparty /
  document-account / text-family mismatch) row가 clean peer 대비 reconstruction-error가
  유의하게 높게 랭크되는가 (mutation_type별 score 분포 분리, scoring **이후** 슬라이싱).
- **A2 비중첩**: VAE 상위가 단일축 룰(L3-05/06, L4, L2-01)·타 family로 환원되지 않고
  top contributing가 **구조 조합**인가. PHASE1 밖 contribution은 보조 관찰 지표(타깃 아님).
- **A3 pressure**: repeated_normal_pressure 통제(낮을수록).
- **A4 explanation**: top contributing 구조 feature/조합이 case에 부착.
- **A5 guard**: 7-0 금지 항목 전부 미사용.

판정: 동결 spec 1회 측정. 실패 시 재설계는 **audit 재정당화 + 다른 generator config(held-out)
검증**으로만, eval metric을 보며 수정하지 않는다.

### 7-5. Data track 요구사항 (전달)

VAE는 위 7개 metadata column이 normal/abnormal 모두에 채워지고, abnormal은 mutation
provenance가 100% 기록될 것을 요구한다(dataset-regeneration-contract acceptance criteria와
동일). 이 요구는 데이터 트랙에 입력 요건으로 전달한다.

> **상태**: §7 동결. 데이터 트랙 완료 시 → 비지도 학습 + A1~A5 1회 검증. 그 전 착수 없음.

## 8. Known issue — PHASE1 priority machinery의 근거없는 magic-number feature 유입 (2026-06-17, 재설계 시 처리)

PHASE1 가중합 topic 점수는 tier(순서형)로 폐기됐다(D071, `PHASE1_TIER_SCORING_SPEC.md` §5). 그러나 PHASE1 case builder의 **legacy priority machinery**가 산출하는 일부 case 필드가 **근거 없는 magic number**인데, 그대로 **PHASE2 case-level feature(`phase2_case_contract.PHASE2_CASE_FEATURE_COLUMNS`)로 유입**된다. PHASE2가 학습되면 근거 없는 입력으로 학습하게 되므로, PHASE2 재설계 시 함께 정리한다.

| feature | 산출 식 (근거 없음) | 코드 위치 |
|---------|---------------------|-----------|
| `behavior_score` | `max(min(len(rows)/10, 1.0), access_scope_score)` — **전표 줄 수 ÷ 10** (임의 제수 10) | `phase1_case_builder.py:1636/2151` (`_apply_timing_priority_adjustments` 보정) |
| `repeat_score` | `min(max(repeat_months-1, 0)/2.0, 1.0)` — **(반복월수−1) ÷ 2** (임의 −1·÷2) | `phase1_case_builder.py:1638` |
| (보정 계수) | L3-04 case 우선순위 ±0.10~0.20 손튜닝(`l304_*_bonus/penalty`) | `_apply_timing_priority_adjustments` |

- 이 값들은 **가중합 0.62/0.08과 같은 종류의 임의 숫자**이며, 도메인·기준서 근거가 없다.
- 현재 PHASE1 운영(tier) 경로의 **band·정렬에는 영향이 없다**(tier가 결정). 이 필드들은 export 표시 + PHASE2 feature/overlay로만 흐른다.
- **2026-06-17 결정(사용자)**: PHASE1 가중합 topic 점수 제거 + 죽은 legacy band 경로 제거는 즉시 수행하되, 위 `behavior_score`/`repeat_score`/L3-04 보정은 **PHASE2가 이 feature를 실제 학습 입력으로 쓰는 시점에 통합 제거/근거화**한다. PHASE2 재설계(본 문서 §6~§7) 작업 시 `PHASE2_CASE_FEATURE_COLUMNS`에서 근거 없는 feature를 빼거나, 근거 있는 정의로 대체한다.
- 관련: `PHASE2_INTERFACE_DESIGN.md`(feature contract), `PHASE1_TIER_SCORING_SPEC.md` §5, `TROUBLESHOOT.md` TS-15.
