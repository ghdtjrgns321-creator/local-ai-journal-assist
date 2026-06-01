# PHASE2 Unsupervised(VAE) 역할 재설계 판단 — 초안

> 상태: 설계 판단 초안 (사용자 승인 전). 구현 방법·코드 변경 미포함.
> 측정 근거: `artifacts/unsupervised_v33d_exact_owner_surface_fixed5_20260601.json`,
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
primary     document-priority soft guard     10 / 40       0.24   ← 현재 default
companion   native_row_queue                 3 / 404       0.99   ← 폐기 대상
companion   document-priority soft guard     54~64 / 404   0.18~0.20
```

native row queue는 primary·companion 양쪽에서 TOP500 거의 무신호 + 반복정상 100%
점유. document-priority surface는 같은 VAE score·gate에서 의미 있는 회수와 낮은
pressure를 보인다. 즉 "VAE가 약한 것"이 아니라 **row 단위 surface가 약한 것**이다.

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
   - 현재 default 정렬(soft guard)은 이미 document proxy로 재정렬한다. 그러나 emit
     단위는 여전히 row다. 목표는 **review 단위 자체를 document로 승격**하는 것이다.

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

---

## 5. 명확한 결론

세 선택지에 대한 판정:

| 선택지 | 판정 | 이유 |
|--------|------|------|
| (1) native row queue 계속 개선 | **기각** | primary 0/40, companion 3/404, pressure 1.0. row 단위 구조 자체가 제품 검토 단위와 불일치. 개선 여지가 fitting 외에 없음. |
| (2) document-level anomaly review surface로 재설계 | **채택** | 같은 score·gate에서 회수↑·pressure↓, 설명 부착률 1.0. review 단위(document)와 정합. evidence-bundle 원리와 일치. |
| (3) product family에서 내리고 companion context로만 | **부분만 채택(프레이밍)** | "fraud primary 아님 / broad statistical companion" 의미 프레이밍은 이미 lock되어 있고 유지. 그러나 보이지 않는 context-only로 완전 격하하지는 않음 — PHASE1 밖 추가분·설명 가치가 0이 아니므로 단일 VAE review list로 노출 가치가 있음. |

**최종: 재설계 필요 (document-level anomaly review surface로 재정의).**

- 제품 family로서 **유지**한다. 단 review 단위를 row-case → document-case로 구조
  변경한다.
- 의미 프레이밍은 **현행 유지**: companion / broad statistical review / not fraud
  primary. fraud recall은 diagnostic 보조 지표로 강등(이미 lock).
- 평가축은 review usefulness / evidence contribution / pressure / explanation으로
  전환하고, fraud primary recall을 제품 판정 기준에서 제외한다.
- 모든 anti-fitting 가드(truth/owner/scenario/PHASE1 rank 입력 금지, gate/threshold/
  weight를 recall에 맞춘 조정 금지, DataSynth를 VAE score에 맞춘 조작 금지)를 재설계
  전 구간에 유지한다.

> 다음 단계(별도 승인 후): 본 결론을 plan으로 전개. 구현 범위·단위 승격 방법·UX
> 컬럼·회귀 가드는 plan 단계에서 정의한다. 본 문서는 판정 초안까지만 다룬다.
