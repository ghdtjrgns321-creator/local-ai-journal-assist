# Detection Rules — 전표 부정 탐지 룰 전체 목록

한국 감사기준서(240호, K-SOX, PCAOB AS 2401)를 근거로 도출한 전표 부정 탐지 룰의 단일 참조 문서.
법규·기준서 근거는 [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) 참조.

탐지 파이프라인은 **PHASE 1 (전수 필터/Recall) → PHASE 2 (스코어 보정/Precision) → PHASE 3 (의미 해석/Explainability)** 순서로 이어진다.

- **PHASE 1**은 룰 기반 전수 필터다. 이 단계의 목적은 정답을 확정하는 것이 아니라, 1차로 규칙에 어긋난 항목을 가능한 한 모두 포착하는 것이다. 이후 중요성, 증거 강도, 정상 예외 가능성, 조합 신호를 기준으로 예외 처리 대상·리뷰 대상·진짜 위험 후보로 2차 분류한다.
- **PHASE 2**는 PHASE 1을 대체하지 않고, case 단위 우선순위를 구조적·통계적 모델로 보정한다. 룰 ID 자체를 예측 feature로 쓰지 않는다.
- **PHASE 3**는 전체 원천 전표를 무차별 분석하지 않고, 선별된 case에 대해 적요·계정·관계 맥락을 해석하고 감사인이 읽을 수 있는 근거 기반 narrative를 만든다.

---

## 1. 개요

### 1.1 프로젝트 목적

ERP에서 추출한 전표 CSV 데이터에 대한 **전수 검사(CAATs)** 자동화.
감사인이 후속 수작업을 수행할 때의 우선순위 추천을 제공한다.

### 1.2 탐지 아키텍처 — L1/L2/L3/L4 + 독립 트랙

```
L1 (확정 오류/명시 위반)     ─ 전표 품질 게이트, 즉시 정정·차단 가능한 항목
L2 (강한 부정 정황)         ─ 구체적인 부정 시나리오·통제 우회 패턴
L3 (검토 필요 이상징후)     ─ 사람 검토가 필요한 운영·맥락형 수상 신호
L4 (통계적 이상치)          ─ 분포·희소성·통계 기반 이탈 신호
Benford (독립 트랙)         ─ L4-02을 별도 가중치로 분리한 분포 수준 검정
Variance (독립 트랙)        ─ 기존회사 전용, 전기 engagement 대비 급변 탐지
```

### 1.3 52개 유형 → 채택 판정

DataSynth 52개 anomaly 유형을 3축 평가(법규 근거 × 실증 빈도 × 데이터 가용성)로 선별.
판정 방법론 상세는 [DETECTION_REFERENCE.md §4](DETECTION_REFERENCE.md#4-3축-평가-방법론) 참조.
아래의 `유형 수`는 DataSynth 원천 anomaly 유형 기준이며, 실제 Phase 1 구현 룰 수와 1:1로 대응하지 않는다. Phase 1은 Must 유형을 감사 검토 가능한 세부 룰로 확장해 현재 32개 구현 룰로 운영하며, L3-12 업무범위 집중 검토는 L1-06과 분리된 review 룰로 둔다.

```
판정     유형 수   적용 단계   구현/운영 단위                  FSS 6대 패턴 커버
────────────────────────────────────────────────────────────────────────────────
Must      20개    Phase 1    32개 구현 룰                      6/6 (전부 커버)
Should    16개    Phase 2    ML/통계 확장                      가공전표·결산수정 정밀도↑
Could      5개    Phase 3    NLP/그래프 고급 탐지               순환거래 정밀도↑
Drop      11개    —          제외                              —
────────────────────────────────────────────────────────────────────────────────
합계      52개               Phase 3 누적: 41개 유형 커버
```

---

## 2. Phase 1: 룰 기반 탐지 (32개 구현 완료)

이 절의 32개는 `L1~L4` 전표 행 단위 구현 룰 기준이다. L3-12는 L1-06의 명시적 SoD 위반과 분리된 사용자 업무범위 집중 review 룰이며, 사용자 큐와 우선순위 해석은
[PHASE1_RULE_RELATIONSHIP_MAP.md](PHASE1_RULE_RELATIONSHIP_MAP.md)의 최신 관계도를 따른다.
따라서 `D01/D02` 같은 Variance macro-finding, `IC01~IC03` 관계사 대사 신호, `GR01/GR03`
그래프 신호는 32개 룰 수에는 넣지 않지만, Phase 1 결과 화면에서는 Account / Process Queue 또는
관계사·연결 구조 drill-down의 보조 finding으로 결합한다.

### 2.0 PHASE1 운영 기준

PHASE1은 **룰 기반 전수 필터**다. 개별 룰은 넓게 탐지하고, 사용자에게는 룰 결과표가 아니라 **감사 검토 큐 + 검토 이유 + 확인 절차**를 제공한다. PHASE1의 목적은 정답 라벨을 맞히거나 부정을 확정하는 것이 아니라, 규칙 위반·정책 위반·이상 징후 후보를 1차로 최대한 누락 없이 올리는 것이다.

따라서 PHASE1 raw hit에는 정상 예외, 업무상 타당한 거래, 단독으로는 약한 신호가 함께 포함될 수 있다. 운영 단계에서는 이를 그대로 최종 위험으로 보지 않고, 중요성 금액, evidence strength, case priority, 고객사 예외 정책, 다른 룰과의 조합 여부를 기준으로 2차 분류한다. 2차 분류 결과는 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보처럼 감사 행동 단위로 나뉜다. 최신 관계도 기준은 [PHASE1_RULE_RELATIONSHIP_MAP.md](PHASE1_RULE_RELATIONSHIP_MAP.md)를 따른다.

#### 2.0.1 결과 표현 계층

PHASE1 결과는 아래 4층으로 만든다.

| 층 | 대상 | 역할 | 감사인에게 노출 |
|---|---|---|---|
| Rule Hit | `L1-05`, `L3-04` 등 | 원천 탐지 근거 | drill-down에서만 노출 |
| Evidence Type | `control_failure`, `timing_anomaly` 등 | 의미 축으로 정리 | 케이스 태그와 주요 근거 |
| Case Priority | `high`, `medium`, `low` | 먼저 볼 순서 | 큐 정렬 기준 |
| Auditor Insight | 검토 초점, 위험 설명, 권장 확인 절차 | 실제 감사 행동 유도 | 메인 설명 |

룰별 `severity`는 최종 사용자 등급이 아니라 `evidence_score`와 `evidence_strength`의 입력이다. 예를 들어 `L3-08 적요 결손/파손`은 단독 `Low`로 노출하지 않고, `기말 수기 고액 전표에 적요 결손/파손이 보조 신호로 결합됨`처럼 case-level 의미로 표현한다.

#### 2.0.2 출력 큐

PHASE1 결과 큐는 탐지 단위에 따라 두 갈래로 나눈다.

1. **Transaction Queue**
   - L1~L4의 전표 행 단위 룰을 Theme Queue와 Case Group으로 묶는다.
   - 감사인이 실제 전표를 열어 승인·계정·금액·시점 맥락을 확인하는 기본 검토 큐다.
2. **Account / Process Queue**
   - Benford, D01, D02처럼 계정·월·프로세스 단위에서 의미가 생기는 macro-finding을 보여준다.
   - 이상 계정/월을 클릭하면 해당 모집단 안에서 L1~L4 룰이 함께 걸린 전표를 drill-down으로 연결한다.
   - D01/D02는 Transaction Queue의 row/document-level precision·FP·FN 성과표에 넣지 않는다. 두 룰은 전표 1건의 오류나 부정을 직접 입증하지 않고, 전기 대비 분석적 절차에 따른 계정 단위 review population을 만드는 보조 분석 트랙이다.
   - 따라서 PHASE1 메인 리포트에서는 D01/D02를 `Analytical Review Signals` 또는 `Account Review Population` 섹션으로 분리하고, 계정 group 수, truth coverage, missed account group, normal-control review group, L1~L4 겹침 전표 수를 표시한다.

#### 2.0.3 레이어와 Evidence Type

| Evidence Type | 포함 룰 | 기본 Primary Theme |
|---|---|---|
| `data_integrity_failure` | L1-01, L1-02, L1-08 | 데이터 정합성 오류 |
| `control_failure` | L1-04, L1-05, L1-06, L1-07, L1-09, L3-02 | 승인·권한 통제 검토 |
| `access_scope_review` | L3-12 | 업무범위·권한범위 검토 |
| `duplicate_or_outflow` | L2-01, L2-02, L2-03, L2-05 | 지급·중복 거래 검토 |
| `timing_anomaly` | L3-04, L3-05, L3-06, L3-07, L3-08, L3-11, L4-05 | 결산·시점 검토 |
| `logic_mismatch` | L1-03, L2-04, L3-01, L3-09, L3-10, L4-04 | 계정 사용 논리 검토 |
| `statistical_outlier` | L4-01, L4-02, L4-03, L4-06 | 수익·금액·통계 예외 |
| `intercompany_structure` | L3-03, IC01, IC02, IC03 | 관계사·연결 거래 검토 |

`IC01~IC03`은 32개 L1~L4 룰 수에 포함하지 않는 관계사 보조 finding이다. `GR01/GR03`은 Phase 3 그래프 신호지만 `L3-03` 케이스와 결합될 때 관계사·연결 구조 이상 우선순위를 높이는 보조 증거로 사용한다.

`L3-03` 단독은 관계사 거래 모집단을 넓게 잡는 약한 검토 신호다. 반면 별도 `IntercompanyMatcher` 결과로 제공되는 `IC01/IC02/IC03`은 대사 예외를 확인한 보조 finding이므로 row-level 대표 점수에서도 별도 floor를 적용한다. `IC02` 또는 `IC03` 단독 예외는 최소 Low, `IC01` 또는 2개 이상 IC 예외 결합은 최소 Medium으로 표시한다.

구현상 `L2-03a~L2-03d`가 존재하더라도 외부 기준은 `L2-03 중복 전표` 하나로 본다. 세부 rule id는 정확 중복, 유사 중복, 분할 후보, 시차 중복을 구분하기 위한 내부 reason code이며 모두 `duplicate_or_outflow`에 속한다.

L2와 L3는 신호 성격으로 구분한다.

| 축 | L2 (강한 부정 정황) | L3 (검토 필요 이상징후) |
|----|-------------------|--------------------|
| 신호 성격 | 도메인 특화 패턴, 통제 우회, 중복·자금 유출 | 시간·텍스트·운영 맥락 이상 |
| 대표 룰 | L2-01, L2-02, L2-03, L2-05 | L3-04, L3-06, L3-08 |
| 해석 | 부정 시나리오 1순위 검토 | 정상 업무 변동 가능성까지 포함한 검토 후보 |

`L2-04`는 L2에 속하지만 사용자 노출과 점수 해석은 `logic_mismatch` evidence다. 즉 비용 자산화 오류를 확정하는 룰이 아니라, 자산/비용 계정 조합이 감사 검토 대상인지 판단하는 전수 필터다. `immediate` band만 confirmed rule hit로 `flagged_rules`에 남기고, `review`와 `low_review` band는 `review_rules` 및 PHASE1 case priority로만 흐르게 한다.

#### 2.0.4 룰별 표현 Metadata

룰마다 화면 문구를 직접 쓰지 않고, 아래 metadata로 표준화한다.

```yaml
L1-05:
  evidence_type: control_failure
  evidence_strength: strong
  focus: approval_control_bypass
  action:
    - 작성자와 승인자 동일 여부 확인
    - 승인권한 정책 확인

L3-08:
  evidence_type: timing_anomaly
  evidence_strength: weak
  focus: missing_or_corrupted_description
  action:
    - 적요 필드가 원천에서 누락되었는지 또는 깨져 들어왔는지 확인

L4-03:
  evidence_type: statistical_outlier
  evidence_strength: medium
  focus: high_amount
  action:
    - 금액 산정 근거 확인
    - 수행중요성 대비 영향 확인
```

Case builder는 hit된 룰의 `evidence_type`, `evidence_strength`, `focus`, `action`을 모아 중복을 제거하고, theme별 우선순위에 따라 `primary_theme`, `secondary_tags`, `risk_narrative`, `recommended_audit_actions`를 만든다.

#### 2.0.5 Case Group 기준

Theme별 case key는 전역 공통 키를 쓰지 않고 다르게 둔다.

| Primary Theme | 기본 Case Key |
|---|---|
| 데이터 정합성 오류 | `회사 / 전표유형 / 적재배치` |
| 승인·권한 통제 검토 | `사용자 / 프로세스 / 월` |
| 지급·중복 거래 검토 | `거래처 / 금액밴드 / 근접기간` |
| 결산·시점 검토 | `사용자 / 계정군 / 월말 윈도우` |
| 계정 사용 논리 검토 | `계정군 / 문서유형 / 월` |
| 수익·금액·통계 예외 | `프로세스 / 계정군 / 월` |
| 관계사·연결 거래 검토 | `회사쌍 / 거래상대 / 월` |

주요 스키마 매핑은 `사용자=created_by`, `프로세스=business_process`, `월=posting_date YYYY-MM`, `거래처=auxiliary_account_number/vendor_name/customer_name`, `계정군=gl_account prefix/account_family`, `회사쌍=company_code + trading_partner`를 사용한다.

#### 2.0.6 점수 기준

점수는 두 층으로 나눈다.

1. **Row-level anomaly score**
   - 전표 행 단위 내부 점수다.
   - `score_aggregator` 호환, 위험 등급 분류, 개발자 검증에 사용한다.
   - 사용자 표기는 L1~L4 룰 체계로 한다.
   - 내부 실행 키(`layer_a`, `layer_b`, `layer_c`, `benford`)는 하위 호환용 이름이다.
   - 기본 row-level `anomaly_score`는 legacy layer 가중합이 아니라 `RULE_LEVEL_WEIGHTS` 기준이다: `0.40*L1 + 0.25*L2 + 0.20*L3 + 0.15*L4`.
   - row `risk_level` threshold는 `High >= 0.7`, `Medium >= 0.4`, `Low >= 0.2`다. 일부 구조 오류와 통제 위반은 점수 희석 방지를 위해 별도 floor를 적용한다.
   - `flagged_rules`는 `details > 0`인 confirmed/immediate 룰만 담는다.
   - `review_rules`는 `details == 0`이지만 `row_annotations.review_score`가 있는 review-only 후보 룰만 담는다.
   - detector가 `review_score_series`를 제공하더라도 review-only 점수는 `details`에 병합하지 않는다. row score와 case priority에는 annotation/review score를 사용할 수 있지만, confirmed 위반 참조와 DB `anomaly_flags`는 `details > 0`만 기준으로 삼는다.
   - `anomaly_score`는 confirmed와 review 후보를 모두 반영할 수 있지만, 위반 룰 집계와 `anomaly_flags` 적재 기준은 confirmed `flagged_rules`다.
   - L2-04의 `review`와 `low_review` band는 이 review-only 계약을 따른다. 따라서 비용 자산화 의심 후보는 row `anomaly_score`와 PHASE1 case `logic_score`에는 반영되지만, `immediate`가 아닌 한 확정 위반처럼 `flagged_rules`나 DB `anomaly_flags`에 적재하지 않는다.
   - L1-01은 단순 flag 1.0을 쓰지 않는다. 불균형 금액 비중으로 산출한 `score_series`가 L1 family max에 들어가므로, PHASE1 전체 row score와 case priority가 작은 차이와 큰 차이를 구분한다.
   - L1-01의 작은 차이는 낮은 참고 신호로 유지한다. 예를 들어 `rounding_scale` 0.15는 L1 가중치 0.40 적용 후 row-level `anomaly_score`에 0.06만 기여한다.
   - L3-12는 review-only access/work-scope signal이다. detector `details["L3-12"]`에는 확정 위반 점수를 넣지 않고, `review_score_series`와 `row_annotations.review_score`를 통해 row `anomaly_score`, `review_rules`, PHASE1 case priority에만 약하게 반영한다.
   - L3-12 원점수 `0.20~0.65`는 전용 단조 정규화를 사용한다. 더 높은 업무범위 review score가 PHASE1 `normalized_score`에서 낮은 점수보다 작아지면 안 된다.
   - L2-01 원점수 `0.45/0.60/0.75`는 전용 단조 정규화를 사용한다. `lower_band < close_band < razor_band` 순서가 row `anomaly_score`와 case `duplicate_or_outflow_score`에서 뒤집히면 안 된다. 자동·반복·배치 source의 `razor_band`는 `routine_razor_review`로 약하게만 반영한다.
   - L3-01은 detector raw score의 원인 순서가 PHASE1 전체 점수에서도 유지되도록 전용 정규화를 적용한다. 즉 exact denylist hit `0.65`가 category fallback `0.45`, strict allowed-category mismatch `0.40`보다 항상 더 크게 row `anomaly_score`와 case `logic_score`에 기여한다.
   - L3-07은 detector raw score `0.45/0.60/0.75`를 그대로 severity-weighted score로 재해석하지 않는다. PHASE1 정규화에서는 bucket label 기준 `moderate_gap=0.55`, `large_gap=0.75`, `extreme_gap=1.0` signal strength를 적용해 31~60일, 61~90일, 90일 초과 괴리의 우선순위가 뒤집히지 않게 한다.
   - L3-06은 weak timing signal이지만 detector raw band 순서는 PHASE1 전체 점수에서도 보존한다. 정상 시스템·배치 context `0.20`은 사람/미상 심야 입력 `0.45`보다 낮게 반영되어야 하며, L3-06 단독 hit는 row `Low/Medium/High` 승격 근거로 쓰지 않는다.
   - L3-10은 weak booster이지만 `priority_case > raw_signal > normal_control_candidate` 순서가 PHASE1 전체 점수에서도 유지되도록 전용 정규화를 적용한다. row `anomaly_score`에는 약하게만 기여하지만, `priority_case`는 case priority floor로 Medium 검토 후보에 올라간다.
   - L3-03은 관계사 거래 모집단 신호이므로 raw `0.40`, `severity=4`, `evidence_strength=weak`, L3 family weight `0.20` 적용 후 row `anomaly_score` 자연 기여도는 약 `0.036`이다. 따라서 L3-03 단독은 row Low threshold `0.20`에 도달하지 않는다.
   - IC01/IC02/IC03은 L1~L4 룰 수에 포함하지 않는 관계사 보조 finding이다. `IntercompanyMatcher` 결과가 aggregate 입력에 포함된 경우, 대사 예외가 row 대표 점수에서 숨지 않도록 `intercompany_exception_score`와 `intercompany_exception_reasons`를 별도 기록한다. `IC02` 또는 `IC03` 단독은 row `Low` floor `0.20`, `IC01` 또는 2개 이상 IC 예외 결합은 row `Medium` floor `0.40`을 적용한다.
2. **Case priority score**
   - 사용자 큐 정렬 기준이다.
   - 기본식: `0.25*control_score + 0.25*amount_score + 0.15*duplicate_or_outflow_score + 0.15*logic_score + 0.10*timing_score + 0.10*behavior_score`
   - band 기준: `high >= 0.75`, `medium >= 0.45`, 그 외 `low`
   - `amount_score`는 engagement materiality가 있으면 상대 금액 점수와 materiality 대비 점수 중 큰 값을 사용한다.
   - `duplicate_or_outflow_score`는 `L2-01/L2-02/L2-03/L2-05` 같은 지급·중복·역분개 evidence type의 정규화 점수다. L2-01 승인한도 직하, L2-05 역분개/상계 후보처럼 금액만으로는 묻히거나 반대로 단독 확정으로 과대해석될 수 있는 부정 시나리오 신호가 case priority에 직접 반영되도록 별도 축으로 둔다.
   - `timing_score`는 `timing_anomaly` evidence type의 정규화 점수다. L3-04, L3-07, L3-11 같은 결산·cutoff 검토 신호가 row-level L3 family max에서 과소 반영되지 않도록 case priority에 직접 들어간다.
   - L1-01 case의 `logic_score`는 L1-01의 나눠진 `normalized_score`를 사용하고, `amount_score`는 기존처럼 케이스 총액/materiality를 반영한다. 따라서 "불균형 비중"과 "노출 금액 크기"가 별도 축으로 함께 반영된다.
   - L1-01 단독 case에서 logic 기여도는 `0.15 * L1-01 normalized_score`다. `rounding_scale`은 priority에 0.0225만 더하고, `severe`는 0.135까지 더한다.
   - `priority_floors`는 심각한 통제 위반(`L1-05`, `L1-04`, `L1-06`, `L1-07`), 보강 맥락이 있는 민감 계정 접촉(`L3-10 priority_case`), 중대한 cutoff 후보(`L3-11`)가 단일 룰 또는 약한 family weight라는 이유로 queue에서 밀리지 않도록 최소 priority를 보장한다.
   - L1-05 immediate는 row `High` floor 0.70을 적용한다. L1-05 escalated bucket은 High 내부 정렬을 위해 더 높은 floor를 적용한다: `escalated_abnormal_time >= 0.75`, `escalated_materiality >= 0.80`, `escalated_high_risk_account >= 0.80`.
   - L1-05 case priority floor는 `config/phase1_case.yaml`에서 별도 관리한다. 기본값은 `immediate >= 0.75`, `escalated_abnormal_time >= 0.80`, `escalated_materiality/high_risk_account >= 0.85`다.
   - L1-06은 direct SoD raw score를 `0.50/0.70/0.80/0.95`로 나누고, row risk floor를 `Low/Medium/High/Critical-high`에 맞춘다. Case priority는 `0.70 -> medium floor 0.45`, `0.80 -> high floor 0.75`, `0.95 -> critical floor 0.85`를 적용한다.
   - L3-11은 raw cutoff score가 `0.60` 이상이면 최소 Medium floor `0.45`를 적용한다. raw score `0.30` 이상이면서 `L4-01` 고액/수익 이상 신호가 같은 case에 있으면 최소 High floor `0.75`를 적용한다. 이는 부정 확정이 아니라 cutoff review queue 우선순위 보정이다.
   - L3-10 `priority_case`는 `config/phase1_case.yaml`에서 `min_priority_score: 0.45`를 적용한다. 민감 계정 단독 접촉을 High로 보지는 않지만, 수기/조정, 고액, 미정리, 승인일 누락, 기말/비정상시점 같은 보강 맥락이 있으면 Medium 검토 큐에 남긴다.
   - L2-04는 별도 `priority_floors`를 두지 않는다. `logic_score` 기본 가중치 `0.15`와 금액 중요성, 수기/기말/승인 등 다른 evidence 조합으로만 case priority가 올라간다. 이 설계는 정상 CAPEX와 오류 가능 후보가 섞이는 L2-04 특성상 단독 High 승격을 피하기 위한 것이다.

Case priority에 들어가기 전, 모든 룰 hit는 먼저 공통 내부 점수로 정규화한다. 룰별 출력이 `상/중/하`, `High/Medium/Low`, `검토 필요`, `위험 높음`, detector-specific bucket처럼 달라도 그대로 합산하지 않는다.

```text
rule output label / row score
  -> signal_strength: 0.0 ~ 1.0
  -> normalized_score
     = signal_strength
       * (severity / 5)
       * evidence_strength_factor
       * scoring_role_factor
  -> evidence_type score
  -> case priority
```

공통 변환 원칙:

| 룰별 표현 | `signal_strength` |
|---|---:|
| `critical`, `high`, `상`, `위험 높음` | 1.0 |
| `medium`, `moderate`, `중`, `검토 필요` | 0.6 |
| `low`, `하` | 0.3 |
| `info`, `참고` | 0.2 |
| 단순 flag `True` | 1.0 |
| flag `False` 또는 `normal` | 0.0 |

일부 룰은 detector raw score 자체가 bucket별 우선순위를 이미 표현하므로, 공통 numeric 변환 전에 rule-specific 정규화를 적용한다. 예를 들어 `L2-01`은 `lower_band=0.60`, `close_band=0.80`, `razor_band=1.00`, `routine_razor_review=0.45` signal strength를 사용한다. 따라서 승인한도에 더 가까운 `razor_band`가 `close_band`보다 낮은 통합점수로 들어가지 않고, 자동·반복 source의 razor hit는 사람 입력 lower band보다 낮게 유지된다. `L3-09`는 `0.45/0.60/0.75/0.80` aging score를 PHASE1 `logic_score`에 단조적으로 반영하기 위해 raw score를 severity factor로 다시 접지 않고 `raw_score * evidence_strength_factor` 형태로 보존한다. 따라서 90일 초과 장기체류가 60~90일 bucket보다 낮은 통합점수로 들어가지 않는다.

`evidence_strength`는 증거 자체의 설명력이다. `strong`은 직접 증거, `medium`은 독립 검토 증거, `weak`은 단독 결론보다 결합 시 유효한 보조 증거로 본다. `scoring_role`은 `primary`, `booster`, `combo_only`, `macro_only`로 나눈다. 예를 들어 `L3-08`은 `booster`, `L4-06`은 `combo_only`, `L4-02/D01/D02`는 transaction queue에서는 `macro_only`다.

일부 룰은 detector가 이미 세분화한 numeric score를 원인 순서로 사용하므로 label 복원식 대신 룰 전용 `signal_strength`를 사용한다. 대표적으로 `L1-03`, `L1-07`, `L2-01`, `L3-01`, `L3-05`는 raw score 순서가 PHASE1 전체 점수에서 뒤집히지 않도록 별도 정규화한다.

L3-05처럼 단독 결론력이 약한 캘린더 신호는 룰별 raw score를 그대로 공통 숫자 해석에 맡기지 않고, 별도 signal-strength bucket으로 변환한다. L3-05의 PHASE1 정규화 순서는 `weekday_holiday < weekend < weekend_holiday`이며, 각각 `signal_strength 0.75 / 0.85 / 1.00`을 사용한다. `severity=2`, `evidence_strength=weak`, `L3 weight=0.20` 적용 후 row-level `anomaly_score` 기여도는 대략 `0.027 / 0.031 / 0.036`이다. 따라서 L3-05 단독 hit는 `Low >= 0.20` threshold에 도달하지 않고, 다른 고위험 신호와 결합될 때만 전체 우선순위를 의미 있게 올린다.

따라서 `L1-05 위험 높음`과 `L3-08 검토 필요`는 같은 "문자 라벨"로 더하지 않는다. 내부적으로는 각각 `display_label`, `signal_strength`, `severity`, `evidence_strength`, `scoring_role`, `normalized_score`를 분리 저장하고, 합산에는 `normalized_score`만 사용한다.

보정 신호:

| 보정값 | 반영 기준 |
|---|---|
| `topside_bonus` | 기말·승인 우회·비정상 계정 조합·고액·적요 결손/파손 결합 |
| `batch_combo_bonus` | L4-06 배치 신호에 2~3개 이상 독립 evidence 축 결합 |
| `work_scope_combo_score` | L3-12 업무범위 집중 신호에 2~3개 이상 독립 evidence group 결합. L3-12 단독은 High floor 없음 |
| `weak_evidence_bonus` | round number, weak description, rare account 같은 약한 증거가 독립 검토 신호와 결합 |

`L3-08`의 `missing_or_corrupted_description` 태그는 예외적으로 `L3-08` 단독으로는 `weak_evidence_bonus`를 만들지 않는다. `L3-04`, `L3-02`, `L1-05`, `L1-07`, `L4-03`, `L4-04`, `L2-05`, `L3-09`, `L3-10` 등 별도 보강 룰이 같은 case에 있을 때만 약한 설명 결손 보정으로 인정한다. 이는 같은 증거를 `timing_anomaly` 원천 hit와 weak description 보너스로 두 번 세는 것을 막기 위한 제약이다.

`repeat_score`는 기본 가중합에 직접 더하지 않고 band 상향과 동점 정렬에 사용한다. 같은 evidence type은 case당 최대 `1.0`까지만 반영하고, 같은 룰의 반복 발생은 `sqrt` 또는 `log` 스케일로 완화한다.

#### 2.0.7 최종 Auditor Insight 출력

최종 사용자 표현은 케이스마다 아래 4개 필드로 표준화한다.

```json
{
  "priority_band": "high",
  "review_focus": [
    "approval_control_bypass",
    "period_end_manual_adjustment",
    "high_amount"
  ],
  "risk_narrative": "기말 수기전표에서 자기승인과 고액 전표가 함께 나타났습니다. 승인 통제 적용과 금액 산정 근거를 우선 확인해야 합니다.",
  "recommended_audit_actions": [
    "작성자와 승인자 동일 여부 확인",
    "승인권한 및 승인일 로그 확인",
    "전표 금액 산정 근거와 증빙 대사",
    "결산조정 승인 문서 확인"
  ]
}
```

내부 추적과 drill-down을 위해 `primary_theme`, `secondary_tags`, `priority_score`, `rule_evidence_summary`, `raw_rule_hits`를 함께 저장한다. `raw_rule_hits`에는 `display_label`, `signal_status`, `signal_strength`, `normalized_score`, `evidence_strength`, `scoring_role`을 포함해 원문 표현, confirmed/review 후보 상태, 합산 점수를 분리해 추적한다. `representative_explanation`은 기존 export/화면 호환을 위한 legacy alias로 두고, 신규 화면과 리포트는 `risk_narrative`를 우선 사용한다.

#### 2.0.8 노출 기준

- 기본 화면: `priority_band`, `case_type`, `main_reason`, `review_focus`, `risk_narrative`, `recommended_audit_actions`
- 케이스 목록: `case_priority` 기준 상위 N개 및 Theme별 상위 케이스
- 케이스 목록의 룰 수는 단일 `Rules` 숫자로만 보지 않고 `Direct`, `Review`, `Blocker`, `Macro` 네 개 신호 수로 나누어 표시한다.
- Drill-down: 전표 목록, 증거 태그, `rule_evidence_summary`, raw rule hit를 아래 네 섹션으로 분리한다.
  - `Direct Risk Signals`: `score_series` 기반 confirmed/immediate 위험 신호
  - `Review / Context Signals`: `review_score_series`, `booster`, `combo_only`, weak/context bucket
  - `Integrity / Coverage Blockers`: L1-01, L1-02, L1-08 같은 전표 정합성·탐지 가능성 문제
  - `Macro / Account Findings`: L4-02, D01, D02처럼 계정·모집단 단위에서 의미가 생기는 finding
- 개발자/검증 모드: 원천 룰 출력, row-level score, detector detail

#### 2.0.9 실행 시간 기준

2026-04-27 기준 PHASE1 기본 실행 범위는 `L1~L4 + Benford(L4-02) + D01/D02`다.
`DuplicateDetector`, `Intercompany`, `Timeseries`, `Evidence`는 기본 PHASE1 실행 경로에서 제외한다.

측정 기준은 DataSynth 2024 합성데이터 `journal_entries_2024.csv`다.

| 항목 | 측정값 |
|---|---:|
| 입력 규모 | 369,545행 / 106,993개 전표 |
| CSV load | 3.178초 |
| 2023 prior load/build | 3.712초 |
| Feature 생성 | 6.495초 |
| `layer_a` | 3.420초 |
| `layer_b` | 69.729초 |
| `layer_c` | 54.986초 |
| `benford` | 1.308초 |
| `layer_d` D01/D02 | 5.188초 |
| Aggregate | 0.796초 |

운영 기준으로는 37만 행 규모의 PHASE1 전체 분석을 **약 2.5~3분**으로 본다.
반복 실행에서는 ingest/feature cache가 있으면 load와 feature 구간이 줄어든다.

주요 병목은 `layer_b`, `layer_c`이며, 특히 `layer_c` 내부 `L2-05`의
역분개/상계 rolling window 계산이 크다. 현재 기본값은 detector 병렬 실행을 끈다.
2024 측정에서 병렬 base detector 실행은 CPU/메모리 대역폭 경합으로 순차 실행보다 느렸고,
이 변경은 룰·임계값·후보군을 바꾸지 않으므로 품질 영향이 없다.

### 2.1 L1: 확정 오류/명시 위반 (9개)

전표테스트의 전제조건. 이 검증을 통과해야 이후 탐지가 의미있음.

#### L1-01 — 차대변 균형 (UnbalancedEntry) ✅

- **심각도**: 5
- **근거**: 240§32 복식부기 원칙. FSS 횡령은폐 수법(차대 불일치)
- **탐지 로직**: `abs(sum(debit) - sum(credit)) > tolerance` per document_id. 기본 허용 오차 1.0 (float 안전)
- **평가/라벨 기준**: L1-01은 원인 라벨이 아니라 구조 게이트다. DataSynth truth와 성능 평가는 `UnbalancedEntry` 라벨명만이 아니라 실제 전표 합계 불균형 여부를 L1-01 positive 기준으로 삼는다. 원인 라벨(`RoundingError`, `TransposedDigits`, `DecimalError`, `CurrencyError`, `ReversedAmount` 등)은 별도 audit issue로 유지할 수 있다.
- **row score**: PHASE1에서는 원인을 추정하지 않고 불균형 금액 비중으로 점수를 차등화한다.
  - `imbalance = abs(sum(debit_amount) - sum(credit_amount))`
  - `base_amount = max(abs(sum(debit_amount)), abs(sum(credit_amount)), 1.0)`
  - `imbalance_ratio = imbalance / base_amount`
  - L1-01 row score는 비율 신호만 반영한다. 절대 금액 영향은 PHASE1 case의 `amount_score`와 `materiality_amount` 축에서 별도 반영한다.

| 버킷 | 기준 | row score |
| --- | --- | ---: |
| `rounding_scale` | `ratio <= 0.001` | 0.15 |
| `minor` | `0.001 < ratio <= 0.01` | 0.30 |
| `material` | `0.01 < ratio <= 0.05` | 0.65 |
| `severe` | `ratio > 0.05` | 0.90 |

PHASE1 전체 점수에 미치는 직접 영향:

| 버킷 | L1-01 row score | row `anomaly_score` 기여 (`* 0.40`) | row `risk_level` floor | case priority logic 기여 (`* 0.20`) |
| --- | ---: | ---: | --- | ---: |
| `rounding_scale` | 0.15 | 0.06 | 없음 | 0.03 |
| `minor` | 0.30 | 0.12 | 없음 | 0.06 |
| `material` | 0.65 | 0.26 | Low | 0.13 |
| `severe` | 0.90 | 0.36 → 최소 0.40 | Medium | 0.18 |

위험도 floor:

- L1/L2/L3/L4 가중합만 적용하면 L1-01 `severe` 단독은 `0.90 * 0.40 = 0.36`으로 Low에 머문다. 차대변 severe 불균형은 구조 오류이므로 `risk_level`에서는 최소 Medium으로 승격한다.
- L1-01 `material`은 현 기본 가중치에서도 Low지만, 가중치 변경이나 다른 집계 경로에서도 최소 Low를 보장한다.
- L1-01 `rounding_scale`, `minor`는 참고 신호로 유지하고 risk floor를 적용하지 않는다.

- **구현**: `integrity_layer.py` → `_a01_unbalanced_entry()`
  - document_id별 groupby → diff 계산
  - NaN document_id는 개별 더미 키로 처리
  - `score_series`와 `row_annotations`에 `bucket`, `imbalance_amount`, `imbalance_ratio`, `debit_sum`, `credit_sum`, `base_amount`를 저장
- **필요 피처**: `debit_amount`, `credit_amount`, `document_id`

#### L1-02 — 필수필드 누락 (MissingField) ✅

- **심각도**: 2
- **근거**: 240-A45(d) 계정번호 없이 입력. K-SOX 전표기록 통제
- **탐지 로직**: `schema.yaml`에서 `required: true`로 정의된 컬럼의 행 단위 누락 검사
  - 현재 기본 스키마 필수 컬럼: document_id, company_code, fiscal_year, fiscal_period, posting_date, document_date, document_type, gl_account, debit_amount, credit_amount
  - 필수 컬럼 세트는 코드에 하드코딩하지 않고 `schema.yaml`을 기준으로 사용한다.
  - NULL뿐 아니라 공백 문자열도 누락으로 본다.
- **row score**: 누락 필드의 실무 중요도와 복수 누락을 반영한다. 단일 누락은 해당 필드 기본점수, 복수 누락은 `max(필드점수) + 0.06 * (누락개수 - 1)`이며 최대 0.90으로 제한한다.

| 누락 필드 | 기준 | 기본 row score |
| --- | --- | ---: |
| `document_id` | 전표 추적·증빙 연결 불가 | 0.80 |
| `gl_account` | 계정 분류·재무제표 라인 산정 불가 | 0.74 |
| `posting_date` | 기간귀속·마감 통제 판단 불가 | 0.72 |
| `debit_amount`, `credit_amount` | 금액 완전성·차대변 검증 불가 | 0.72 |
| `company_code` | 법인 단위 집계·권한 범위 판단 불가 | 0.62 |
| `fiscal_year`, `fiscal_period` | 회계기간 집계와 비교 분석 저하 | 0.56 |
| `document_type` | 전표 성격·업무흐름 판단 저하 | 0.48 |
| `document_date` | 증빙일 기준 분석 저하 | 0.42 |

- **PHASE1 case priority 반영**: L1-02는 부정 확정 신호가 아니라 분석·감사추적 가능성을 막는 `data_integrity_failure` 신호다. 따라서 row `anomaly_score`는 기존 L1 가중치(`0.40 * L1 max`)를 유지하되, 핵심 필드 누락은 case priority floor로 감사 검토 큐에서 묻히지 않게 한다.

| 조건 | priority floor | 해석 |
| --- | ---: | --- |
| `document_id` 누락 | 0.60 | 전표 추적·증빙 연결 blocker |
| `gl_account`, `posting_date`, `debit_amount`, `credit_amount` 중 1개 이상 누락 | 0.55 | 계정/기간/금액 분석 blocker |
| 위 핵심 필드 중 2개 이상 누락 | 0.75 | 복수 핵심 입력 결손, high 후보 |

  - floor 사유는 각각 `missing_document_id_traceability_blocker`, `missing_core_required_field_blocker`, `multiple_core_required_fields_missing`로 `priority_adjustment_reasons`에 남긴다.
  - `document_type`, `document_date` 단독 누락은 raw score와 일반 case priority 산식으로만 처리한다. 단독 high queue로 승격하지 않는다.
  - L1-02가 L1-01/L1-03/승인/수기/기말 등 다른 증거와 결합되면 해당 증거의 priority logic과 함께 최종 priority가 올라갈 수 있다.

- **구현**: `integrity_layer.py` → `_a02_missing_required()`
- **필요 피처**: `document_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_date`, `document_date`, `document_type`, `gl_account`, `debit_amount`, `credit_amount`
- **DataSynth 상태**: MCAR 2% 주입 추가됨, E2E 재검증 필요

#### L1-03 — 무효 계정 (InvalidAccount) ✅

- **심각도**: 3
- **근거**: 240-A45(a) 비경상·저사용 계정 + 315호 비정상계정. FSS 가공전표(미사용계정 악용)
- **탐지 로직**: `gl_account NOT IN chart_of_accounts`
  - CoA(계정과목표) 미제공 시 스킵
- **row score**: CoA 밖 계정을 모두 같은 위험으로 보지 않고, 계정 코드 품질과 거래 맥락을 나눠 산정한다.

| 버킷 | 기준 | 기본 row score |
| --- | --- | ---: |
| `unknown_account` | CoA에 없지만 기존 계정 family 안의 정상 형식 코드 | 0.60 |
| `unknown_account_family` | CoA의 상위 family/prefix 밖 코드 | 0.70 |
| `malformed_account` | 숫자형 CoA 환경에서 문자·파손 형식 코드 | 0.75 |
| `placeholder_or_reserved` | `9999`, `888888`, `777777`, 반복 숫자/0 계정 등 placeholder성 코드 | 0.80 |

  - 고액 전표, 수기/조정 전표, 월말 입력 맥락은 각 `0.05`씩 보정하되 총 보정은 `0.20`, 최종 점수는 `0.90`으로 cap 한다. 금액 percentile 보정은 표본이 충분할 때만 적용해 소규모 입력에서 모든 무효 계정이 고액으로 승격되는 일을 막는다.
  - 공란/NULL 계정은 L1-03이 아니라 L1-02 필수필드 누락이 소유한다.
  - 출력에는 `score_series`, `breakdown.score_bands`, `row_annotations.bucket/reason_code/context_reasons/document_amount`를 남겨 같은 L1-03 안에서도 감사인이 우선순위를 나눌 수 있게 한다.
- **구현**: `integrity_layer.py` → `_a03_invalid_account()`
- **필요 피처**: `gl_account`
- **DataSynth 상태**: `v126` 기준 CoA 밖 GL은 `InvalidAccount`가 소유한다. `MisclassifiedAccount`가 CoA 밖 GL을 사용해 L1-03을 오염시키는 케이스는 `0`건이며, `check_datasynth_required_truth.py`에서 승격 전 검증한다.

#### L1-04 — 승인한도 초과 (ExceededApprovalLimit) ✅

- **심각도**: 3
- **의미**: 전표 총액이 실제 승인자(`approved_by`)의 승인한도(`approval_limit`)를 초과한 경우를 탐지한다.
- **근거**: K-SOX 승인체계, ISA 240 §32. 승인권자가 자기 권한 범위를 넘는 금액을 승인했다면 통제 실패 또는 승인권한 위반 가능성이 있다.
- **판정 방식**
  - 같은 `document_id`의 차변 합계와 대변 합계 중 큰 값을 전표 단위 승인 대상 금액으로 계산한다.
  - 전표의 `approved_by`를 직원 마스터(`employees.json`)와 연결해 해당 승인자의 `approval_limit`를 조회한다.
  - `전표 총액 > approved_by의 approval_limit`이면 `ExceededApprovalLimit`로 판정한다.
  - `approved_by`가 비어 있거나 직원 마스터에서 승인자 한도를 찾을 수 없는 행은 L1-04 확정 탐지에서 제외한다.
  - 승인자가 없는 고액 전표는 승인한도 초과가 아니라 **L1-07 승인 생략** 후보로 분리한다.
- **결과 표현**
  - 룰 hit 자체는 확정 위반만 반영한다.
  - 승인한도 초과 후보는 초과 정도와 승인자 권한 상태에 따라 아래 버킷으로 나눈다.
  - `boundary`는 기본적으로 REVIEW다. 한도 초과율이 작으면 위임전결, 환율/반올림, 승인 matrix tolerance, 사후 승인 정책에 따라 정상일 수 있으므로 고객사 정책 확인 전까지 확정 위반으로 세지 않는다.
  - `row score`는 detector 원점수다. Phase1 case priority 집계에서는 L1-04 전용 bucket normalization을 적용해 `boundary < moderate < severe < critical/non_approver` 순서가 깨지지 않게 한다.

| 버킷 | 기준 | detector row score | Phase1 normalized score |
|---|---|---:|---:|
| `boundary` | 한도 초과율 `0% < ratio <= 10%`, 기본 REVIEW | 0.00 (`review_score` 0.40) | 0.21 |
| `moderate` | `10% < ratio <= 50%` | 0.60 | 0.39 |
| `severe` | `50% < ratio <= 100%` | 0.75 | 0.51 |
| `critical` | `ratio > 100%` | 0.90 | 0.60 |
| `non_approver` | `can_approve_je = false` 또는 승인권한 없음 | 0.90 | 0.60 |
| `none` | L1-04 미해당 | 0.00 | 0.00 |

- **Phase1 정규화 계약**
  - L1-04 bucket은 전역 label map이 아니라 `src/detection/rule_scoring.py`의 L1-04 전용 map으로 해석한다.
  - `boundary`는 review candidate로 남기되 확정 `moderate`보다 낮게 집계한다.
  - `critical`과 `non_approver`는 L1-04 단독이어도 High floor 대상이다. `severe`는 강한 확정 위반이지만 단독 High floor는 적용하지 않는다.

- **추가 파생 컬럼**
  - `document_approval_amount`: 전표 단위 승인 대상 금액. `max(SUM(debit_amount), SUM(credit_amount)) BY document_id`로 계산한다.
  - `approver_limit_amount`: 승인자의 실제 승인한도. 조회 실패 시 null
  - `approval_limit_resolved`: 승인자 한도 조회 성공 여부
  - `approver_can_approve_je`: 승인자가 JE 승인권한을 갖는지 여부
  - `approval_excess_amount`: 초과 금액
  - `approval_excess_ratio`: 초과율. `approval_excess_amount / approver_limit_amount`로 계산한다. `approval_limit_resolved=false`이면 L1-04 hit가 아니므로 null이다.
  - `approval_excess_bucket`: 위 버킷명
- **한 줄 규칙**: `max(SUM(debit_amount), SUM(credit_amount)) BY document_id > approval_limit(approved_by)`
- **구현**
  - 피처 생성: `src/feature/amount_features.py` → `add_exceeds_threshold()`
  - 룰 적용/점수 메타데이터: `src/detection/fraud_rules_feature.py` → `b03_exceeds_threshold()`
  - 직원 한도 조회: `employees.json`의 `user_id`, `approval_limit`, `can_approve_je`
- **튜닝 파라미터**: `patterns.approval_limit_exceeded_review.review_buckets`
- **필요 컬럼**: `document_id`, `debit_amount`, `credit_amount`, `approved_by`, `approval_limit`(직원 마스터), `can_approve_je`(직원 마스터), `exceeds_threshold`(파생)
- **DataSynth 상태**: `v60_candidate`에서 `created_by`/`approved_by`가 `employees.json.user_id`와 직접 조인되도록 복구했고, L1-04 라벨 문서는 모두 실제 `approved_by.approval_limit` 기준으로 재판정된다. `approval_limit_resolved=false` fallback을 L1-04에서 제외한 기준으로 L1-04는 정답 52건, 탐지 56건, 정탐 52건, 미탐 0건, 과탐 4건이다.

#### L1-05 — 자기 승인 (SelfApproval) ✅

- **심각도**: 3
- **근거**: K-SOX 직무분리(외감법 §8①5호). FSS 오스템임플란트 사례처럼 1인이 입력, 승인, 자금 집행까지 이어서 수행하는 통제 우회 패턴을 직접 포착한다.
- **탐지 로직**
  - `created_by`와 `approved_by`가 모두 있을 때만 L1-05를 판정한다.
  - `approved_by == created_by`이면 자기승인으로 탐지한다.
  - `approved_by`가 없을 때는 `source='manual'`이라는 이유만으로 자기승인으로 추정하지 않는다.
  - 승인 누락이나 승인 생략은 **L1-07**에서 별도로 탐지한다.
- **기본 예외는 명시적으로 allowlist에 들어간 시스템 자동처리만 둔다**
  - 기본 설정은 `user_persona == automated_system` 또는 `source == automated`일 때 0점 예외 bucket으로 분리하는 방식이다.
  - `batch`, `interface`, `recurring` 같은 source는 이름만으로 자동 제외하지 않는다. 고객사에서 시스템 자동처리로 확인한 경우 `patterns.self_approval_allow.sources`에 추가한다.
  - 이것은 사람이 자기 전표를 자기 승인한 경우가 아니라 시스템 자동 처리로 보기 때문이다. 다만 자기승인 사실 자체는 후보/evidence로 남겨 데이터 lineage와 allowlist 근거를 추적한다.
- **자기승인 사실은 예외까지 전부 잡고, 점수 단계에서 분리한다**
  - `approved_by == created_by`이면 시스템 예외 여부와 무관하게 L1-05 후보로 잡는다.
  - 자동처리 allowlist에 해당하는 후보는 `allowed_system`으로 남기되 `score_series=0`, `review_score_series=0`을 준다.
  - 사람이 수행한 자기승인은 아래 기준으로 즉시 위반과 검토 필요로 나눈다.
  - **즉시 위반**: 원칙적으로 바로 통제 위반으로 볼 수 있는 자기승인
  - **검토 필요**: 자기승인 자체는 맞지만, 결산 조정이나 자산 조정처럼 회사 운영 방식에 따라 예외 전결이나 책임자 직접 처리 가능성이 있어 추가 확인이 필요한 경우
- **결과 표현**
  - L1-05 반환 후보와 `row_annotations`는 관측된 자기승인 전체를 반영한다.
  - `score_series`와 detector `details`는 즉시 위반/immediate 또는 escalated만 반영한다. `allowed_system`은 후보 lineage에는 남기지만 확정 위험 점수는 0점이다.
  - `review` 자기승인은 `review_score_series`, `breakdown`, `row_annotations`에 남기되 `details`에는 병합하지 않는다. 따라서 row-level score와 case priority에는 반영될 수 있지만 `flagged_rules`에는 들어가지 않고 `review_rules=L1-05`로만 노출된다.
  - `allowed_system`은 `flagged_rules`, `review_rules`, Transaction Queue에서 제외한다. 필요하면 control sample 또는 allowlist evidence로만 별도 조회한다.
  - 화면과 점수에서는 아래 bucket을 함께 남긴다.

| 버킷 | signal status | 기준 | detector score | priority floor |
|---|---|---|---:|---:|
| `allowed_system` | `normal_control` | 자기승인이지만 자동처리 allowlist에 해당. 후보/evidence에는 남기고 queue에서는 제외 | 0.00 | 없음 |
| `review` | `review_candidate` | R2R/A2R 등 검토 필요 bucket이고 보강 신호 없음 | review 0.40 | 없음 |
| `immediate` | `confirmed` | 일반 사람 자기승인 또는 명시 통제 위반 성격 | 0.80 | 0.70 |
| `escalated_materiality` | `confirmed` | review 후보이나 수행중요성 이상 수기 전표라 즉시 위반으로 승격 | 0.80 | 0.80 |
| `escalated_abnormal_time` | `confirmed` | review 후보이나 주말·공휴일·심야 등 비정상 시점이라 즉시 위반으로 승격 | 0.80 | 0.75 |
| `escalated_high_risk_account` | `confirmed` | review 후보이나 민감 계정을 건드려 즉시 위반으로 승격 | 0.80 | 0.80 |

- **기본 분류 기준**
  - `R2R`, `A2R` 업무의 자기승인은 기본적으로 **검토 필요**로 둔다.
  - 그 외 사람 자기승인은 기본적으로 **즉시 위반**으로 둔다.
- **검토 필요라도 바로 즉시 위반으로 올리는 경우**
  - **금액이 너무 큰 수기 행**
    - 결산(R2R)이나 자산조정(A2R)이라도, 사람이 직접 처리한 자기승인 행의 대표금액이 수행중요성 금액을 넘으면 단순 검토 대상으로 두지 않는다.
    - 구현상 대표금액은 해당 행의 `max(debit_amount, credit_amount)` 기준이며, 전표 전체 합계 기준은 아니다.
    - 현재 `1,000,000,000`원은 임시 기본값이며, 실제 감사 착수 후 engagement별 수행중요성 금액으로 반드시 오버라이드한다.
  - **주말 또는 심야에 처리된 자기승인**
    - 결산조정이라도 주말, 공휴일, 심야 시간대에 자기승인이 발생하면 통제 회피 가능성이 커지므로 바로 즉시 위반으로 올린다.
    - 구현상 `is_weekend`, `is_holiday`, `is_after_hours`, `time_zone_category`, `posting_time` 중 사용 가능한 시간 신호를 함께 본다.
  - **민감한 고위험 계정을 건드린 자기승인**
    - 현금성 자산, 가지급금, 가수금처럼 자기승인이 특히 위험한 계정은 결산 프로세스 안에 있더라도 즉시 위반으로 본다.
    - 기본 예시는 `1190(가지급금)`, `2190(가수금)`, 그리고 현금/예금 계열로 자주 쓰이는 `111`, `112`, `113` 접두사다.
    - 계정체계는 회사마다 다르므로 실제 고객사 CoA에 맞게 수정한다.
- **어디서 수정하는가**
  - 시스템 자동처리 예외는 [config/audit_rules.yaml](../config/audit_rules.yaml)의 `patterns.self_approval_allow`에서 수정한다.
  - `즉시 위반`과 `검토 필요` 기본 구분은 같은 파일의 `patterns.self_approval_review`에서 수정한다.
  - 검토 대상을 다시 즉시 위반으로 승격시키는 조건은 `patterns.self_approval_immediate_override`에서 수정한다.
  - 여기서 수행중요성 금액(`materiality_amount`), 수기 소스(`manual_sources`), 고위험 계정(`high_risk_accounts`), 고위험 계정 접두사(`high_risk_account_prefixes`)를 바꿀 수 있다.
  - 회사별로 다르게 운영하려면 `data/companies/{company_id}/audit_rules.yaml`에서 같은 키를 오버라이드하면 된다.
- **구현**: `fraud_rules_access.py` → `b06_self_approval()`
  - `score_series`: immediate/escalated 0.80
  - `review_score_series`: review 0.40
  - `breakdown`: candidate/actionable/immediate/review/allowed_system 행 수, bucket count, 승격 사유 수. `observed_summary`와 queue count는 actionable rows만 사용하므로 `allowed_system`은 review queue로 세지 않는다.
  - `row_annotations`: bucket, score, 작성자, 승인자, 프로세스, source, 승격 사유
- **필요 피처**: `created_by`, `approved_by`, `source`

#### L1-06 — 직무분리 위반 (SegregationOfDutiesViolation) ✅

- **심각도**: 4
- **근거**: K-SOX 직무분리. FSS 오스템임플란트 사례처럼 입력, 승인, 자금 집행 등 상충 권한이 한 사용자에게 결합되면 통제 우회와 은폐 위험이 커진다.
- **룰 경계**
  - L1-06은 **직접 확인 가능한 SoD conflict**만 확정 위반으로 본다.
  - 단순히 한 사용자가 여러 프로세스에 등장하거나 직급별 허용 범위를 넘는다는 이유만으로 L1-06 정답 또는 확정 hit로 세지 않는다.
  - role/process breadth 기반 검토 신호는 **L3-12 업무범위 집중 검토**로 분리한다.
- **L1-06 정답 기준**
  - `sod_violation == True`
  - `sod_conflict_type`이 존재하고 비어 있지 않음
  - 구매-지급, 매출-수금, 급여-지급처럼 금지된 SoD conflict pair가 문서 또는 업무흐름에서 확인됨
  - IT/admin 권한자가 일반 업무 전표를 생성·승인·지급 처리하는 등 시스템 권한과 업무 처리 권한의 충돌이 확인됨
- **탐지 로직**
  1. `sod_violation=True`로 주입되거나 계산된 직접 SoD 위반 행을 탐지한다.
  2. `sod_conflict_type` 또는 equivalent reason code가 있는 행을 conflict type별로 분류한다.
  3. IT/admin/super-user 계정은 일반 review pair가 아니라, 실제 업무 전표 생성·승인·지급 관여가 확인될 때만 L1-06으로 승격한다.
- **점수체계와 위험도 매핑**
  - L1-06 raw score는 확정 direct SoD 증거 강도이며, L3-12 review/work-scope 신호는 여기에 섞지 않는다.
  - `direct_low = 0.50`: `sod_conflict_type` 등 직접 충돌 marker는 있지만 금액·보호 프로세스·한도초과 보강이 약한 경우. L1 가중치 0.40 적용 후 row `Low` 경계인 0.20에 닿는다.
  - `direct_medium = 0.70`: 직접 SoD marker가 보호 프로세스(`TRE/P2P/O2C/R2R/H2R`) 또는 금액 전표 맥락과 결합된 경우. 자연 row score는 Medium에 못 미치므로 `L1-06:direct_medium` floor로 row `Medium >= 0.40`, case priority `medium >= 0.45`를 보장한다.
  - `direct_high = 0.80`: 고위험 conflict type(`cash_disbursement`, `purchase_payment`, `treasury_payment`, `payroll_payment`, `revenue_collection`) 또는 `exceeds_threshold=True`가 붙은 경우. 기존 L1-06 immediate와 같은 row `High >= 0.70`, case priority `high >= 0.75` floor를 적용한다.
  - `direct_critical = 0.95`: IT/admin/super-user가 보호 프로세스에서 실제 금액 전표를 처리한 경우. 정규화상 자연 점수만으로는 `0.80`보다 높아지지 않으므로 row score floor `0.85`, case priority floor `0.85`로 High 내부 최상단에 둔다.
  - `review_score_series`는 L1-06에서 항상 0이다. L1-06은 review band가 아니라 direct evidence band만 가진다.
- **L1-06에서 제외하는 신호**
  - `sod_review_pairs`에 걸린 동일 사용자 프로세스 조합 이력
  - junior/senior/controller/manager 같은 역할별 프로세스 수 한도 초과
  - 한 사용자가 P2P/O2C/TRE/R2R/H2R 여러 프로세스에 넓게 등장하는 현상
  - 위 항목은 확정 통제 위반이 아니라 access/work-scope review signal이므로 L3-12 또는 sidecar review population에서 관리한다.
- **평가/리포트 표시 방식**
  - L1-06의 Boolean hit와 `score_series`는 확정 위반만 반영한다.
  - `SegregationOfDutiesViolation` precision/recall은 `sod_violation=True`, `sod_conflict_type` 직접 충돌, IT super-user 직접 업무 개입 같은 direct conflict만으로 계산한다.
  - role threshold 192k건처럼 업무범위가 넓은 review population은 L1-06의 FP/FN/precision/recall 분자·분모에 넣지 않는다.
  - 리포트에는 L1-06 확정 위반과 L3-12 검토 신호를 별도 섹션으로 보여준다.
  - v80 기준 `labels/rule_truth`의 L1-06은 direct SoD conflict 중심으로 좁히고, role threshold population은 `labels/work_scope_excess_review_population.csv` 같은 sidecar로 분리한다.
- **운영 예외와 보완 통제**
  - **사람(Human) 전제 필터**: L1-06은 사람의 권한 남용을 보는 룰이므로 `automated_system` persona, `automated/interface/system/batch` source, `BATCH/SYSTEM/AUTO/IF_/SVC_`류 시스템 계정명은 기본적으로 제외한다.
  - **중요성 금액 적용 범위**: 직접 SoD conflict는 금액과 무관하게 유지한다. 다만 case priority에서는 금액 중요성을 별도 가중치로 반영한다.
  - **직급 기반 보완 통제 인정**: controller/manager라도 `sod_violation=True` 또는 `sod_conflict_type` 직접 충돌이 있으면 L1-06에서 제외하지 않는다.
  - **IT Super-user 예외 처리**: IT 관리자 계정은 일반 SoD review에서 넓게 잡지 않고, 실제 금액 전표를 `TRE/P2P/O2C/H2R`에서 생성·승인·처리한 경우에만 고위험 즉시 위반으로 본다.
- **다른 통제 룰과의 경계**
  - `L1-05 SelfApproval`(`created_by == approved_by`)은 L1-05에서만 탐지한다. L1-06은 자기승인을 근거로 탐지하거나 review를 즉시 위반으로 승격하지 않는다.
  - `L1-07 SkippedApproval`(`exceeds_threshold == True` 이면서 승인 흔적 없음)은 L1-07에서만 탐지한다. L1-06은 승인누락을 근거로 탐지하거나 review를 즉시 위반으로 승격하지 않는다.
  - 수기전표/통제우회 신호는 L3-02에서만 탐지한다. L1-06은 수기전표, 승인일 누락, 비정상 시점, 기말 입력, 미결/가계정, 적요 결손/파손, 고위험 계정 사용을 근거로 탐지하거나 승격하지 않는다.
  - 업무범위 집중 검토는 L3-12에서만 탐지한다. L1-06은 `role_threshold`, `process_breadth`, `review_pair_only`를 확정 SoD 위반으로 보지 않는다.
  - 같은 문서가 L1-05/L1-07/L3-02와 L1-06에 동시에 잡히려면 L1-06 자체의 SoD 구조 조건도 독립적으로 만족해야 한다.
- **구현**: `fraud_rules_access.py` → `b07_segregation_of_duties()`
  - `score_series`: direct_low 0.50, direct_medium 0.70, direct_high 0.80, direct_critical 0.95
  - `review_score_series`: 항상 0.00
  - `row_annotations`: bucket, score, score_reason, direct evidence flags
- **필요 피처**: `created_by`, `approved_by`, `business_process`, `sod_violation`, `sod_conflict_type`, `user_persona`, `source`
- **DataSynth**: 1,365명 규모 (마스터 1,422), SOD 위반률 3.32% (10,595건, 2026-04-14 실측)

#### L1-07 — 승인 생략 (SkippedApproval) ✅

- **심각도**: 4
- **근거**: K-SOX 승인절차(외감법§8②). FSS 오스템: 한도초과+승인없음 = §8② 직접 위반
- **탐지 로직**: `approved_by`가 비어 있으면 우선 L1-07 후보로 전부 잡고, 승인 필요성·source·보강근거로 점수를 분리한다.
  - 시스템성 source 기본값은 `automated`, `batch`, `interface`, `system`이다.
  - `approved_by` 컬럼 자체가 없으면 승인 생략으로 추정하지 않고 L1-07을 skip/coverage degraded로 본다. 컬럼 부재와 실제 승인자 누락은 구분해야 한다.
  - 승인 필요 금액은 `exceeds_threshold=True` 또는 `approval_level >= 1`로 본다. 승인자가 없으면 승인자 한도 조회가 불가능하므로, L1-07에서는 금액 단계(`approval_level`)를 승인 필요성의 보조 근거로 사용한다.
  - `approval_level`의 전표 승인 대상 금액은 debit 합계만 보지 않고 `max(SUM(debit_amount), SUM(credit_amount)) BY document_id`를 사용한다. credit 쪽 금액이 더 큰 전표도 승인 필요성에서 누락하지 않는다.
  - 다만 `approval_level >= 1`만으로 모든 승인자 누락 전표를 확정하지 않는다. `manual`/`adjustment`처럼 사람이 직접 입력하거나 조정한 source이고 evidence count가 기준 이상일 때만 즉시위반으로 올린다.
  - `recurring`은 기본적으로 확정 승인 생략이 아니라 review로 둔다. 반복전표는 사전승인, 자동생성, 마스터데이터 승인, 정기 승인 정책으로 커버될 수 있으므로 전표별 승인자 공란만으로 확정 위반 처리하지 않는다.
  - 시스템 source이거나 승인 필요 금액/레벨이 아닌데 승인자가 비어 있는 행도 후보/evidence에는 남긴다. 다만 승인이 없어도 되는 맥락일 수 있으므로 낮은 review score로 분리한다.
- **판정 결과 구분**
  - **즉시위반**: 승인 필요 금액 + `source in {'manual', 'adjustment'}` + `approved_by` 없음 + evidence count가 기준 이상
    - `approval_date` 없음, 수기전표 플래그, 비정상 시점, 고위험 프로세스, 높은 승인단계 같은 보강 신호를 evidence로 합산한다.
    - 기본 정책은 수기/조정 source이면서 evidence count가 `min_evidence_count` 이상이면 즉시위반이다.
    - 해석: 사람이 직접 넣은 고액 전표인데 승인 흔적이 없어, 승인 생략으로 바로 볼 근거가 충분한 경우.
  - **검토필요**: 시스템성 source가 아니고 `approved_by`가 없지만 즉시위반 조건까지는 못 미치는 경우
    - 예: `recurring` 반복전표, `approved_by`는 없지만 `approval_date`는 있는 경우, source 의미가 애매하거나 evidence count가 낮은 경우
    - 해석: 승인 누락 가능성은 높지만 시스템 처리인지 실제 생략인지 추가 확인이 필요한 경우.
  - **낮은 우선순위**: `approved_by`는 없지만 시스템 source이거나 승인 필요 금액/레벨이 아닌 경우
    - 해석: 승인 생략 사실은 후보로 남기되, 사전승인/자동승인/승인불요 정책으로 설명될 수 있어 낮은 점수로 둔다.
- **결과 표현**
  - L1-07 반환 후보와 `row_annotations`는 `approved_by`가 비어 있는 전체 행을 반영한다.
  - 행별 점수는 고정 `0.80`이 아니라 아래 컴포넌트 가중합으로 계산한다.
    - `0.25 * approval_requirement_confidence`: `exceeds_threshold`, `approval_level >= 1` 등 승인 필요성
    - `0.25 * amount_materiality`: 전표 금액, 승인단계, 중요성
    - `0.20 * control_bypass_context`: 수기/조정 source, 승인일 누락, 고위험 프로세스, 높은 승인단계
    - `0.15 * timing_and_manual_context`: 수기전표, 비정상 시점, 기말/주말 입력
    - `0.10 * repeat_or_concentration`: 동일 작성자/프로세스 반복 승인누락
    - `0.05 * data_trace_quality`: 승인자·승인일·문서 라인 추적 결손
    - `-0.15 * mitigation_likelihood`: 시스템/인터페이스/배치/반복전표, 사전승인 가능성, 승인일 존재, 승인불요 가능성
  - 점수 밴드는 `0.85-1.00 = critical`, `0.70-0.84 = high`, `0.45-0.69 = review`, `0.10-0.44 = low`로 해석한다.
  - `immediate`는 확정 통제위반 큐로 유지하되, 실제 확정 점수는 최소 `0.70`에서 시작해 중요금액·반복·수기·추적결손 조합이면 `0.85` 이상으로 올라간다.
  - `review`는 `0.45-0.69` 범위에 둔다. 승인 필요성은 있지만 반복전표, source 애매함, 대체승인 가능성 때문에 확정 위반으로 바로 보지 않는 모집단이다.
  - `low_priority`는 `0.10-0.44` 범위에 둔다. 승인자 공란은 남기지만 시스템 처리나 승인불요 맥락으로 설명될 가능성이 큰 경우다.
  - `row_annotations`에는 `queue_label`, `score`, `review_score`, `severity_score`, `score_components`, `score_reason_summary`, `evidence_count`, `evidence_reasons`, `source_category`, `has_approval_date`, `min_evidence_count`를 저장한다.
  - `breakdown`에는 `immediate_rows`, `review_rows`, `low_priority_rows`, `confirmed_rows`, `candidate_rows`, `actionable_missing_approver_rows`, `no_approval_required_rows`, `approval_level_review_rows`, `allowed_system_rows`, `missing_approver_rows`, `no_approval_trace_rows`, `evidence_count_bands`, `evidence_reason_counts`, `score_bands`를 저장한다.
- **평가/리포트 표시 방식**
  - L1-07은 단일 precision/recall만으로 해석하지 않고 immediate/review score band를 함께 본다.
  - `immediate_docs`는 확정 승인통제 실패 후보로 우선 검토하고, `review_docs`는 승인 로그/대체통제/시스템 전표 여부를 확인하는 모집단으로 본다. `review_docs`는 정밀도/재현율의 확정 탐지 분자에는 넣지 않는다.
  - `review_queue_docs`는 L1-07에 한해 단순 FP 문서 수가 아니라 review score band 문서 수를 우선 사용한다.
  - case-level `priority_score`는 L1-07 점수에 민감한 floor를 사용한다. `L1-07 immediate + raw score >= 0.85`는 critical floor `0.85`, `raw score >= 0.70`은 high floor `0.75`로 올린다. 이보다 낮은 review/low 후보는 금액, 반복성, 다른 룰 조합이 없으면 High로 강제 승격하지 않는다.
- **운영 원칙**
  - L1-07 룰 자체는 하나로 유지하되, 결과 표시는 `즉시위반`과 `검토필요`로 나눠 확실한 승인 생략과 추가 확인이 필요한 건을 구분한다.
- **구현**: `fraud_rules_access.py` → `b09_skipped_approval()`
- **튜닝 파라미터**: `patterns.skipped_approval_immediate.manual_sources`, `system_sources`, `business_processes`, `min_evidence_count`
- **필요 피처**: `approved_by`. 점수 분리를 위해 `source`, `exceeds_threshold` 또는 `approval_level`, `debit_amount`, `credit_amount`, 선택적으로 `approval_date`, `is_manual_je`, `business_process`, `created_by`를 사용한다.

#### L1-08 — 기간 불일치 (WrongPeriod) ✅

- **심각도**: 4
- **근거**: 240§32(b) 기간귀속 적정성
- **현재 코드 기준 탐지 로직**
  - 기본 최종 룰은 `fiscal_period_mismatch == True`일 때 `WrongPeriod`로 탐지한다.
  - 이 플래그는 단순히 `month(posting_date)`와 바로 비교하지 않고, 회사 회계연도 시작월 `fiscal_year_start`를 반영해 기대 기수를 먼저 계산한 뒤 비교한다.
  - 계산식은 `expected_period = (posting_month - fiscal_year_start) % 12 + 1` 이다.
  - 즉 표준 회계연도(`fiscal_year_start=1`)에서는 사실상 `fiscal_period ≠ month(posting_date)`와 같고, 4월 시작 회계연도처럼 비표준 회계연도에서는 4월=기수1, 5월=기수2, ..., 3월=기수12로 본다.
  - `config/audit_rules.yaml`의 `patterns.fiscal_period_mismatch_policy.strict_mode`가 `true`이면 예외 없이 raw mismatch를 그대로 최종 탐지한다.
  - `strict_mode`가 `false`이면 감사인이 허용한 특수기수, source/document_type/business_process 조건, 업무유형/source별 기준일 예외를 적용한 뒤 남은 건만 최종 L1-08로 탐지한다.
- **사람이 이해할 수 있는 판정 기준**
  - 전기일이 속한 달을 회사의 회계기간 체계로 환산했을 때, 그 전표에 적힌 `fiscal_period`와 다르면 기간 불일치다.
  - 예: `fiscal_year_start=1`에서 `posting_date=2025-01-15`, `fiscal_period=5`이면 불일치다.
  - 예: `fiscal_year_start=4`에서 `posting_date=2025-04-15`, `fiscal_period=1`이면 정상이다.
- **현재 코드가 실제로 잡는 것**
  - 잘못된 회계기간 귀속, 월경 전표 처리 오류, 회계연도 시작월 설정과 맞지 않는 period 기입을 잡는다.
  - 반대로 `posting_date` 또는 `fiscal_period`가 비어 있어 비교 자체가 불가능한 건은 `pd.NA`로 두고, 최종 룰에서는 탐지하지 않는다. 즉 "비교 불가"와 "불일치"를 구분한다.
- **예외 가능성과 정책 처리**
  - 실무에서는 결산조정 전표, 특수기수(`13~16`), reopen period, closing entry처럼 `posting_date`의 일반 월과 다른 period를 의도적으로 쓰는 경우가 있다.
  - 현재 Phase 1 구현은 원칙적으로 raw mismatch를 보존하고, 고객사 정책으로 확인된 예외만 설정 기반으로 제외한다.
  - 예외 적용 시에도 raw mismatch 건수와 정책 예외 건수는 룰 결과 metadata에 남겨 감사 trail로 확인할 수 있게 한다.
- **운영 원칙**
  - Phase 1에서는 룰을 단순하고 설명 가능하게 유지하기 위해 기본 불일치 신호만 잡는다.
  - 결산/특수기수 예외는 고객사가 회계정책 또는 ERP 운영정책으로 문서화한 경우에만 `fiscal_period_mismatch_policy`에서 허용한다.
  - 예외를 조용히 삭제하지 않고 raw signal과 final signal을 분리해서 해석한다.
- **구현**: `anomaly_rules_simple.py` → `c05_fiscal_period_mismatch()`
- **피처 생성**: `time_features.py` → `add_fiscal_period_mismatch()`
- **필요 피처**: `fiscal_period`, `posting_date`
  - 피처 생성 후 최종 룰은 `fiscal_period_mismatch`를 사용한다.
  - 예외 정책을 쓰려면 선택적으로 `document_date`, `source`, `document_type`, `business_process`가 필요하다.
  - 현재 `AnomalyDetector` 레이어 실행 전제상 `debit_amount`, `credit_amount`가 없으면 레이어 전체가 실행되지 않는다. 이는 L1-08 판정 로직 자체의 입력이 아니라 레이어 공통 실행 조건이다.
- **튜닝 파라미터**: `patterns.fiscal_period_mismatch_policy`
  - `fiscal_year_start`
  - `strict_mode`
  - `allow_special_periods`, `special_periods`
  - `special_period_allowed_sources`, `special_period_allowed_document_types`, `special_period_allowed_business_processes`
  - `period_basis_by_process`, `period_basis_by_source`
- **DataSynth 계약**: `v36_candidate`부터 결산/특수기수 negative control sidecar를 별도로 관리한다.

#### L1-09 — 승인일 누락 (ApprovalDateMissing) ✅

- **심각도**: 3
- **근거**: 승인일이 없으면 승인 추적성이 훼손된다. 승인자 자체가 없는 경우는 L1-07 영역이기도 하지만, 승인일 누락 사실은 L1-09 후보/evidence로도 남긴다.
- **탐지 로직**: `approval_date`가 비어 있으면 우선 L1-09 후보로 전부 잡고, 승인자 존재 여부와 실무 맥락에 따라 점수를 분리한다.
  - **즉시위반**: 수기/조정 source, 수기전표 플래그, 고위험 업무 프로세스(`TRE`, `P2P`, `O2C`, `H2R`), 또는 한도초과 금액 신호가 있어 승인일 누락을 문서 추적성 결함으로 바로 볼 수 있는 경우
  - **REVIEW**: `automated`, `batch`, `interface`, `system`, `recurring` 같은 시스템·정기 전표 맥락. 승인일이 전표 컬럼에 없더라도 workflow log, batch approval, standing approval, master approval에 남아 있을 수 있으므로 확정 위반으로 세지 않는다.
  - **낮은 우선순위**: `approval_date`가 없고 `approved_by`도 없는 경우. 승인일 누락 후보에는 남기되, 승인자 누락 자체는 L1-07에서 주로 해석하므로 낮은 점수로 둔다.
  - `source`가 없으면 기존 호환성을 위해 수기 맥락으로 보고 즉시위반으로 처리하지만, 리포트에서는 coverage 한계를 함께 봐야 한다.
- **결과 표현**
  - L1-09 반환 후보와 `row_annotations`는 `approval_date`가 비어 있는 전체 행을 반영한다.
  - `score_series`는 즉시위반만 반영한다. REVIEW와 낮은 우선순위 후보는 `review_score_series`에만 남긴다.
  - REVIEW와 낮은 우선순위 후보는 `review_score_series`, `breakdown`, `row_annotations`에 남긴다.
  - 기본 점수는 승인자도 없는 낮은 우선순위 `0.10`, 시스템·정기 전표 REVIEW `0.25`, 보강 신호가 있는 시스템 REVIEW `0.35`, 비시스템 약한 REVIEW `0.35`, 수기/고위험 프로세스/고액 단일 즉시위반 `0.55~0.65`, 고액+수기/고위험 프로세스 `0.70`, 고액에 결산일·비정상시간·고위험계정 등 추가 보강이 붙은 경우 `0.80`이다.
  - `row_annotations`에는 `bucket`, `evidence_count`, `evidence_reasons`를 저장한다. 주요 bucket은 `missing_approver`, `system_review`, `weak_review`, `single_control_gap`, `corroborated_control_gap`, `material_control_gap`, `corroborated_material`이다.
  - row-level `anomaly_score`/`risk_level`은 PHASE1 aggregator에서 한 번 더 보정한다. `L1-09 >= 0.55`는 최소 Low, `L1-09 >= 0.70`은 최소 Medium floor를 적용한다. `L1-09 >= 0.55`가 L1-04/L1-05/L1-06/L1-07 같은 강한 통제위반과 결합되면 High floor를 적용한다. L1-09 단독 High는 만들지 않는다.
  - case-level PHASE1 통합점수(`priority_score`)도 `config/phase1_case.yaml`의 floor로 보정한다. `L1-09 >= 0.55`는 최소 `0.35`, `L1-09 >= 0.70`은 최소 Medium 기준인 `0.45`, `L1-09 >= 0.80`은 최소 `0.55`를 적용한다.
- **구현**: `fraud_rules_access.py` → `b12_missing_approval_date()`
- **튜닝 파라미터**: `patterns.missing_approval_date_immediate.manual_sources`, `system_sources`, `business_processes`
- **필요 피처**: `approval_date`. 점수 분리를 위해 `approved_by`, `source`, `is_manual_je`, `business_process`, `exceeds_threshold`, `is_period_end`, 비정상시간 플래그, `gl_account`를 사용한다.
- **DataSynth 상태**: `v58` 기준 `ApprovalDateMissing` 26건과 `labels/approval_date_missing_cases*` sidecar를 관리한다.

---

### 2.2 L2: 강한 부정 정황 (5개)

#### L2-01 — 승인한도 직하 (JustBelowThreshold) ✅

- **심각도**: 3
- **근거**: 240-A45(e) 단수/끝자리, K-SOX 승인체계
- **의미**: 승인 대상 금액이 결재권자의 승인 한도에 근접해 있을 때, 우연한 분포라기보다 승인 기준을 의식해 금액이 맞춰졌을 가능성을 살펴보는 룰이다. 이 룰 하나만으로 우회라고 단정하지 않고, 승인 정책과 업무 맥락을 함께 본다.
- **판정 방식**
  - 같은 `document_id`의 차변 금액 합계로 전표 총액을 계산한다.
  - 전표의 `approved_by`를 직원 마스터(`employees.json`)와 연결해 해당 승인자의 `approval_limit`를 조회한다.
  - 전표 총액이 그 승인자의 한도에 충분히 가깝지만 아직 넘지 않은 경우, 즉 `approval_limit × near_threshold_ratio <= 전표 총액 < approval_limit` 이면 `JustBelowThreshold`로 본다.
  - 기본 `near_threshold_ratio`는 `0.90`이다. 실무 해석으로는 "승인 한도의 90% 이상 100% 미만 구간"이다.
- **Fallback 원칙**
  - fallback은 사용하지 않는다.
  - `approved_by`가 없거나 직원 마스터 조인에 실패해 실제 `approval_limit`를 알 수 없는 행은 `L2-01`로 판정하지 않는다.
  - `document_id`, `debit_amount`, `credit_amount` 중 하나가 없어 전표 단위 승인 대상 금액을 계산할 수 없는 행도 line-level 금액으로 대체하지 않는다.
  - 이런 행은 부정 탐지 결과가 아니라 "승인한도 검증 불가"라는 커버리지/데이터 품질 이슈로 별도 관리한다.
- **결과 표현**
  - 룰 hit 자체는 기존처럼 `is_near_threshold` Boolean으로 유지한다.
  - hit된 행은 승인한도 대비 근접률에 따라 아래 bucket으로 나눈다.

| 버킷 | 기준 | row score |
|---|---|---:|
| `lower_band` | `near_threshold_ratio <= amount / approval_limit < 0.95` | 0.45 |
| `close_band` | `0.95 <= amount / approval_limit < 0.98` | 0.60 |
| `razor_band` | `0.98 <= amount / approval_limit < 1.00` | 0.75 |
| `unresolved_limit` | 승인자 한도 조회 실패. L2-01 hit 아님 | 0.00 |
| `none` | L2-01 미해당 | 0.00 |

  - PHASE1 통합 점수에서는 위 raw score를 그대로 다시 severity 비율로 접지 않고 전용 signal strength를 쓴다. `lower_band=0.60`, `close_band=0.80`, `razor_band=1.00`으로 정규화해 근접도가 높을수록 row `anomaly_score`와 case `duplicate_or_outflow_score`가 높아진다.
  - `source in ('automated','recurring','batch','interface','system')`인 자동·반복성 전표의 `lower_band/close_band`는 정상 모집단 hit로 보고 score 0으로 낮춘다. 같은 source의 `razor_band`는 `routine_razor_review`로 남기되 raw score를 최대 0.35로 제한해 사람 입력 lower band보다 낮은 검토 신호로 둔다.
  - L2-01 단독 hit는 High floor를 만들지 않는다. 다만 `duplicate_or_outflow_score` 축을 통해 PHASE1 case priority에 직접 반영되며, 동일 거래처·근접기간 반복, L2-03 분할 후보, L1 승인통제 이슈, 수기·기말·고액 신호와 결합될 때 우선순위가 올라간다.

- **추가 파생 컬럼**
  - `near_threshold_amount`: 전표 단위 승인 대상 금액. `max(SUM(debit_amount), SUM(credit_amount)) BY document_id`로 계산한다.
  - `near_threshold_limit_amount`: 승인자의 실제 승인한도. 조회 실패 시 null
  - `near_threshold_limit_resolved`: 승인자 한도 조회 성공 여부
  - `near_threshold_ratio_to_limit`: 승인 대상 금액 / 승인한도
  - `near_threshold_gap_amount`: 승인한도까지 남은 금액
  - `near_threshold_gap_ratio`: 승인한도까지 남은 비율
  - `near_threshold_bucket`: 위 버킷명
- **한 줄 규칙**: `approval_limit(approved_by) × 0.9 <= max(SUM(debit_amount), SUM(credit_amount)) BY document_id < approval_limit(approved_by)`
- **구현**
  - 피처 생성: `src/feature/amount_features.py` → `add_is_near_threshold()`
  - 룰 적용: `src/detection/fraud_rules_feature.py` → `b02_near_threshold()`
    - `score_series`: lower 0.45, close 0.60, razor 0.75
    - `breakdown`: bucket count, flagged rows, unresolved limit rows
    - `row_annotations`: amount, limit, ratio, gap, bucket
- **필요 컬럼**: `document_id`, `debit_amount`, `credit_amount`, `approved_by`, `approval_limit`(직원 마스터), `is_near_threshold`(파생)
- **DataSynth 상태**: `v24_candidate`에서 `approved_by.approval_limit` 기준 라벨로 보정했다.

#### L2-02 — 중복 지급 (DuplicatePayment) ✅

- **심각도**: 3
- **근거**: 240§32 적정성. FSS 횡령은폐: 동일건 이중지급
- **한 줄 설명**: 같은 매입처에 같은 돈을 또 보냈는지 찾는 룰
- **현재 성격**: PHASE1 recall 우선 스크리닝 룰이다. 확정 부정 판정이 아니라 "검토해야 할 지급쌍"을 올린다.
- **PHASE1 탐지 순서**
  1. 지급성 전표 범위를 좁힐 수 있는 컬럼이 있으면 사용한다. `business_process`가 있으면 `P2P`만 보고, `document_type`이 있으면 `KZ`만 본다. 둘 다 있으면 `P2P + KZ`만 본다. 둘 다 없으면 입력 coverage degraded 상태로 보고 가능한 지급 후보 모집단을 넓게 스크리닝한다.
  2. 거래처 키는 `auxiliary_account_number`를 우선 사용하고, 없으면 `trading_partner`, `vendor_name` 등 대체 컬럼으로 보완한다.
  3. 전표 라인 단위가 아니라 `document_id` 단위로 요약한다. 같은 전표 안의 차변/대변 라인은 중복 지급으로 보지 않는다.
  4. `reference`가 있으면 강한 신호로 본다.
     - 같은 회사/거래처 + 정규화한 `reference` + 거의 같은 금액 + 다른 `document_id`
     - 금액 허용오차는 `min(금액의 2%, 100,000원)`이다. 최소 허용오차는 1원이다.
     - 이 경로는 reference가 같은 청구/증빙을 다시 지급한 가능성을 잡기 위한 것이다.
  5. `reference`가 없으면 보수적으로 fallback 한다.
     - 같은 회사/거래처 + 같은 금액 + 45일 이내 재지급이면 후보로 올린다.
     - blank-reference fallback에는 2% 금액 허용오차를 적용하지 않는다.
  6. 단, 같은 거래처/같은 금액이 월 단위로 규칙적으로 3번 이상 반복되면 정기성 지급 가능성이 높다고 보고 fallback 과탐을 줄인다.
- **해석 기준**
  - `reference` 일치 케이스는 fallback 케이스보다 강한 중복 지급 신호다.
  - `reference`가 비어 있는 fallback 케이스는 근거가 약하므로 같은 금액 exact match만 후보로 올린다.
  - 따라서 결과 화면에서는 "중복 확정"이 아니라 "중복 지급 의심 후보"로 노출한다.
- **출력 방식**
  - `L2-02`는 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
  - `row_annotations`에는 `reason_code`, `confidence`, `confidence_band`, `matched_document_id`, `partner_key`, `reference_norm`, `amount`, `matched_amount`, `day_gap`을 기록한다.
  - `breakdown`에는 `reference_match_docs`, `mixed_reference_fallback_docs`, `blank_reference_fallback_docs`, `amount_partner_fallback_docs`, `recurring_suppressed_docs`, `partner_key_coverage_ratio`를 기록한다.
  - 거래처 식별자 coverage가 낮으면 `FraudLayer.metadata["coverage_issues"]`에 `partial_input_coverage`로 남기며, 결과 해석은 degraded 상태로 본다.
- **점수 기준**
  - `reference_match`: 0.90. 같은 reference와 유사 금액이 확인된 강한 중복 지급 후보.
  - `mixed_reference_fallback`: 0.70. 원 지급에는 reference가 있으나 후속 지급 reference가 비어 있는 후보.
  - `amount_partner_fallback`: 0.65. reference가 서로 다르거나 일부만 있어도 같은 회사/거래처와 유사 금액·기간 조건이 맞는 후보.
  - `blank_reference_fallback`: 0.60. reference 없이 같은 거래처·같은 금액·기간 조건만 충족한 후보.
  - `recurring_suppressed`: 0.00. 정기 반복 지급 가능성이 높아 후보에서 제외한 문서.
- **PHASE1 점수 흐름**
  - 위 점수는 최종 부정 확률이 아니라 L2-02 내부 confidence다.
  - row-level `anomaly_score`에는 `reference_match > mixed_reference_fallback > amount_partner_fallback > blank_reference_fallback` 순서가 유지되도록 L2-02 전용 정규화를 적용한다.
  - `reference_match`는 reference 기반의 강한 중복 지급 후보이므로 Transaction Queue에서 최소 Medium priority floor(`0.45`)를 적용한다.
  - fallback 계열은 단독 floor를 만들지 않는다. 금액 중요성, 반복 건수, 승인·증빙·반제·cutoff 같은 보강 신호와 결합될 때 우선순위가 올라간다.
- **구현**: `fraud_rules_groupby.py` → `b04_duplicate_payment()`
- **필수 실행 입력**: `posting_date`, `debit_amount`, `credit_amount`
- **필수 판정 키**: 거래처 식별자(`auxiliary_account_number` 우선, 없으면 거래처 대체 컬럼). 거래처 키가 전혀 없으면 hit를 만들지 않고 coverage issue로 남긴다.
- **보강 피처**: `document_id`, `business_process`, `document_type`, `reference`, `company_code`
- **DataSynth 상태**: v113 후보 기준 `rule_truth_L2_02.csv`와 `duplicate_payment_review_population.csv`는 현재 detector raw duplicate-payment review universe다. `DuplicatePayment` 라벨과 `duplicate_payment_pairs*`는 확정 중복 지급 pair subset으로 유지한다. `duplicate_payment_negative_controls*`는 정상 반복/대조군 sidecar이며 strict rule truth에 섞지 않는다.
- **평가 계약**
  - `rule_truth_L2_02`는 Phase 1 후보 모집단이다. reference match, mixed-reference fallback, blank-reference fallback, amount-partner fallback 후보를 모두 포함한다.
  - `DuplicatePayment` 라벨은 확정 중복 지급 subset이다.
  - 탐지기는 지급쌍 후보를 문서 단위로 노출하므로, `reference_match_docs`, `mixed_reference_fallback_docs`, `blank_reference_fallback_docs`를 분리해 해석한다.
  - fallback 후보는 confirmed duplicate payment가 아니라 review candidate지만, Phase 1 strict rule truth에는 포함한다.

#### L2-03 — 중복 전표 (DuplicateEntry) ✅

- **심각도**: 3
- **근거**: 240§32, FSS 가공전표: 동일 전표 반복 = 가공
- **해석**
  - 실무에서 "중복 전표"는 같은 행의 단순 중복뿐 아니라, 같은 거래의 재입력, 날짜·적요·금액을 조금 바꾼 재기표, 분할 입력 가능성까지 포함한다.
  - 따라서 L2-03은 확정 판정이 아니라 중복 가능성이 높은 전표 후보를 우선 추출하는 룰이다.
- **현재 구현**
  - `fraud_rules_groupby.py` → `b05_duplicate_entry()`
  - PHASE1의 `L2-03`은 exact-only가 아니며, 아래 reason code를 사용해 행 단위 confidence를 계산한다.
    - `document_duplicate`: 서로 다른 `document_id`의 전표 shape, reference, 거래처, 적요가 문서 단위로 유사한 후보
    - `exact_duplicate`: 같은 `gl_account + amount + posting_date`
    - `reference_duplicate`: 같은 거래처, 같은 `reference`, 같은 `gl_account`, 유사 금액, 서로 다른 `document_id`
    - `near_duplicate`: 같은 거래처와 계정에서 금액·날짜·적요가 가까운 후보
    - `split_duplicate`: 짧은 기간 내 여러 건의 합이 원래 금액과 가까운 분할 후보
  - 각 행은 가장 강한 신호 1개를 primary `reason_code`로 갖고, 함께 걸린 신호는 `matched_reason_codes`로 남긴다.
  - 최종 confidence는 행 단위로 계산되며 `high / medium / low` band로도 구분한다.
- **평가/리포트 표시 방식**
  - L2-03은 단일 precision/recall만으로 해석하지 않는다. high-confidence 중복 후보와 weak fuzzy review 후보가 섞이면 약한 후보가 모두 false positive처럼 보일 수 있기 때문이다.
  - 리포트에는 `high_confidence_docs`, `medium_confidence_docs`, `low_confidence_docs` score band와 탐지기 breakdown(`reason_counts`, `confidence_band_counts`)을 함께 표시한다.
  - `high_confidence`는 우선 검토 중복 후보로 보고, `medium_confidence`와 `low_confidence`는 다른 통제 실패·시점 이상·고위험 계정 신호와 결합해 우선순위를 정하는 review queue로 본다.
  - `review_queue_docs`는 L2-03에 한해 단순 FP 문서 수가 아니라 `medium_confidence_docs + low_confidence_docs`를 우선 사용한다.
- **PHASE1 점수 흐름**
  - L2-03은 PHASE1 정의상 확정 부정 판정이 아니라 중복 가능성 후보다. 따라서 row-level `anomaly_score`에서는 L2 family weight 안에서 보수적으로만 반영하며, L2-03 단독으로 Low/Medium/High를 만들지 않는다.
  - `high_confidence` L2-03도 단독이면 duplicate review 후보로 남긴다. 다만 통제 실패, 결산·시점 이상, 계정 논리 이상, 통계적 이상치, 데이터 정합성 오류, 업무범위 신호, 관계사 구조 신호 같은 독립 evidence type이 함께 있으면 case priority에 `l203_high_confidence_corroborated` 보정을 적용한다.
  - 보정은 `config/phase1_case.yaml`의 `priority_adjustments.duplicate_entry`에서 관리한다. 기본값은 `high_confidence_score: 0.85`, `bonus: 0.08`, `min_priority_score: 0.45`다. 즉 보강 신호가 있는 high-confidence L2-03은 최소 Medium review queue에 남기되, 단독 중복 후보를 High로 승격하지 않는다.
  - 금액 기준 보정은 engagement materiality 또는 `min_total_amount`가 설정된 경우에만 사용한다. materiality가 없을 때 상대금액 순위만으로 L2-03을 올리면 단일 케이스 실행에서 모든 후보가 큰 금액처럼 해석될 수 있기 때문이다.
- **운영 원칙**
  - 외부 노출 라벨은 계속 `L2-03 중복 전표` 하나로 유지한다.
  - UI, export, review queue에는 `reason_code`, `confidence`, `matched_reason_codes`, 핵심 근거 필드(`reference`, 거래처, 금액, 날짜, 적요)를 함께 제공한다.
  - 정상 반복 전표, 내부거래, 정산성 전표는 탐지 제거보다 confidence 조정 또는 review queue 분리로 처리한다.
  - `P2P/KZ` 지급성 전표가 함께 걸리면 `L2-02 duplicate payment`와 병합 설명을 제공한다.
- **DataSynth 상태**
  - `v26_candidate`에서 `DuplicateEntry` / `ExactDuplicateAmount` 라벨을 실제 복제 결과 문서(`duplicate_document_id`) 기준으로 보정했다.
  - 현재 기준 recall은 확보했지만, unrelated false positive가 남아 있어 confidence와 review queue 운영으로 좁혀야 한다.
- **필요 피처**
  - 최소: `document_id`, `gl_account`, `debit_amount`, `credit_amount`, `posting_date`
  - 실무형 보강: `reference`, 거래처 식별자, `line_text`, `business_process`, `document_type`, `company_code`
  - `document_id`는 같은 전표 내부 라인을 중복으로 보지 않고, 서로 다른 전표끼리만 비교하기 위한 필수 식별자다.
- **평가 계약**
  - `DuplicateEntry` / `ExactDuplicateAmount` 라벨은 confirmed duplicate subset이다.
  - `v115_candidate`부터 `rule_truth_L2_03*`와 `duplicate_entry_review_population*`은 현재 `b05_duplicate_entry()` detector output으로 재생성한 raw candidate universe다. 현재 문서 수는 `105`건이다.
  - `v118_candidate`부터 활성 `rule_truth_*`의 `source_candidate` 메타데이터는 모두 `v118`로 정리되어, 과거 후보 버전 기준이 활성 truth처럼 남지 않는다.
  - L2-03 raw candidate에는 score 0의 정상/루틴 중복 형태도 포함될 수 있다. 이들은 `queue_label=normal_duplicate_population` 또는 `routine_duplicate_review`로 구분하고, confirmed fraud label과 동일하게 해석하지 않는다.
  - `duplicate_entry_review_population*`은 detector output snapshot이다. 독립 검증 sidecar가 아니다.
  - `v117_candidate`부터 독립 행동 검증용 sidecar는 `duplicate_entry_confirmed_scenarios*`와 `duplicate_entry_negative_controls*`를 사용한다. 이 파일들은 detector output을 읽지 않고 anomaly label 또는 journal 업무 필드로만 선정한다.
  - `high_confidence_docs`는 우선 검토 후보, `medium_confidence_docs`와 `low_confidence_docs`는 review queue로 본다.
  - 따라서 L2-03 raw hit 전체를 단일 precision/recall 합불격으로 해석하지 않는다.

#### L2-04 — 비용 자산화 (ExpenseCapitalization) ✅

- **심각도**: 4
- **근거**: 240§32, FSS 분식회계: 개발비 과대자산화
- **한 줄 설명**
  - 비용으로 나가야 할 금액이 자산으로 넘어간 것처럼 보이는 전표를 찾는 룰이다.
- **현재 판정 기준**
  - 회사 설정(`audit_rules.yaml`)의 `자산 계정 prefix`와 `비용 계정 prefix`를 사용한다.
  - 같은 `document_id` 안에서 `자산 차변`과 `비용 대변`이 금액상 거의 맞으면 탐지한다.
  - 1:1 매칭이 안 되어도 자산 차변 합계와 비용 대변 합계가 거의 같으면 분할 전표로 보고 탐지한다.
  - 전표 전체가 아니라 실제로 매칭된 자산/비용 라인만 올린다.
- **우선순위 조정 로직**
  - `개발`, `구축`, `software`, `project`처럼 정상 자산화 맥락이 강하면 감점한다.
  - `수선`, `복리후생`, `지급수수료`, `office`, `repair`처럼 일반 비용성 적요가 보이면 가점한다.
  - `manual`, `adjustment` 같은 수기성 source와 `P2P`, `O2C`, `R2R`, `H2R` 같은 일반 운영 프로세스는 가점한다.
  - `AA`, `FA` 같은 자산 관련 문서유형은 감점한다.
- **출력 방식**
  - `0.75 이상`은 `즉시 검토(immediate)`, `0.45 이상`은 `검토 필요(review)`로 본다.
  - 따라서 같은 L2-04라도 전표 맥락에 따라 우선순위가 달라질 수 있다.
  - `immediate` band만 confirmed `score_series`에 들어간다.
  - `review`와 `low_review` band는 `review_score_series`와 `row_annotations.review_score`에만 들어간다. 이 후보는 row `anomaly_score`와 PHASE1 case `logic_score`에는 반영되지만, confirmed `flagged_rules`에는 들어가지 않는다.
  - 정상 자산화 문맥 때문에 `population`으로 내려간 문서는 `score_series`와 `review_score_series` 모두 0으로 남긴다.
  - `row_annotations`에는 `reason_code`, `matched_reason_codes`, `confidence`, `confidence_band`, `queue_label`을 기록하고, band에 따라 `score` 또는 `review_score`를 추가한다.
  - `breakdown`에는 `immediate_rows`, `review_rows`, `low_score_rows`, `population_rows`, `queue_counts`, `confidence_band_counts`, `immediate_docs`, `review_docs`, `low_score_docs`, `population_docs`, `reason_counts`, `reason_doc_counts`, `modifier_row_counts`, `normal_context_suppressed_docs`를 기록한다.
  - `reason_counts`는 line/subtotal 매칭 행 수, `reason_doc_counts`는 같은 기준의 문서 수다.
  - `modifier_row_counts`는 suspicious keyword/source/process 가점과 normal capex/document type 감점이 실제로 반영된 행 수를 보여준다.
  - `normal_context_suppressed_docs`는 계정/금액 모양은 맞지만 정상 자산화 문맥 때문에 review threshold 아래로 내려간 문서 수다.
- **해석**
  - 이 룰은 `비용 자산화 확정`이 아니라 `비용 자산화 가능성이 높은 전표 후보`를 먼저 보여주는 룰이다.
  - 즉 확정 판정용이 아니라 우선 검토 큐용이다.
  - PHASE1 전체 점수에서는 `logic_mismatch`의 `medium` evidence로 정규화된다. L2 family row weight `0.25`, case priority logic weight `0.15`만 적용되며, L2-04 전용 High/Medium floor는 두지 않는다.
- **평가/리포트 표시 방식**
  - L2-04는 단일 precision/recall만으로 해석하지 않고 `immediate_docs`, `review_docs`, 정상 자산화 감점 문서 수를 함께 본다.
  - `review_queue_docs`는 strict label 기준 FP 전체가 아니라 `review_docs`를 우선 사용한다.
  - strict `ImproperCapitalization` 단독 precision은 보조 참고값이다. primary 해석은 `ExpenseCapitalization + ImproperCapitalization` family coverage와 queue band 분포다.
  - `immediate`는 수기/비용성 적요/운영 프로세스가 결합된 높은 우선순위 후보이고, `review`는 정상 자산화·재분류 가능성을 추가 확인할 모집단이다.
  - 운영 리포트에서 `review` band를 `flagged_rules`나 확정 위반 건수에 합산하지 않는다. 대신 `review_rules`, `review_docs`, PHASE1 case priority 근거로 표시한다.
- **실무 해석 시 주의점**
  - 회사마다 CoA가 다르므로 prefix는 회사 기준으로 조정해야 한다.
  - 정상적인 자산 취득/자본적 지출도 비슷한 모양이 나올 수 있으므로 적요, 문서유형, 프로세스를 함께 봐야 한다.
  - 현재 감점/가점 키워드는 시작점일 뿐이고, 회사별 자산화 정책을 반영해 계속 튜닝해야 한다.
- **합성데이터 평가**: family 라벨 기준 recall은 높지만 subtype 단독 기준 precision은 낮아, `비용 자산화 family`를 넓게 잡는 우선검토 룰로 해석한다. 상세는 `tests/phase1_rulebase/test-results/l2-04-synth-2022-2024.md` 참조.
- **평가 계약**
  - `src/metrics/rule_mapping.py`의 primary label family는 `ExpenseCapitalization + ImproperCapitalization`이다.
  - `v115_candidate`부터 `rule_truth_L2_04*`와 `expense_capitalization_review_population*`은 현재 `b11_expense_capitalization()` detector output으로 재생성한 raw candidate universe다. 현재 문서 수는 `1,098`건이다.
  - L2-04 raw candidate는 `immediate`, `review`, `low_review`, `population` band를 모두 포함한다. 확정 비용 자산화처럼 강하게 볼 대상은 `immediate`와 confirmed label subset을 함께 보며, 나머지는 후단 scoring/triage 대상이다.
  - `expense_capitalization_review_population*`은 detector output snapshot이다. 독립 검증 sidecar가 아니다.
  - `v117_candidate`부터 독립 행동 검증용 sidecar는 `expense_capitalization_plausible_cases*`와 `expense_capitalization_normal_capex_controls*`를 사용한다. 이 파일들은 detector output을 읽지 않고 anomaly label 또는 journal 업무 필드로만 선정한다.
  - `v117_candidate`부터 활성 `rule_truth_*`의 `source_candidate` 메타데이터는 모두 `v117`로 정리되어, 과거 후보 버전 기준이 활성 truth처럼 남지 않는다.
  - strict `ImproperCapitalization`은 확정 subtype 참고값이며, 단독 precision을 L2-04 전체 성능으로 보지 않는다.
  - 리포트 상태는 coverage anchor로 표시하고, `immediate_docs`와 `review_docs` band를 함께 본다.
- **구현**: `fraud_rules_groupby.py` → `b11_expense_capitalization()`
- **필요 피처**: `document_id`, `gl_account`, `debit_amount`, `credit_amount`

#### L2-05 — 역분개 패턴 (ReversalEntry) ✅

- **심각도**: 4
- **근거**: 240§32(a)(ii) 기말 재분개 중점 검사, FSS 분식회계·횡령은폐
- **설계 원칙**
  - Phase 1에서는 `역분개 확정`이 아니라 `역분개/상계/재분류 후보`를 먼저 넓게 보여준다.
  - 다만 실제 결과 화면과 후속 우선순위에서는 `확실한 역분개 신호`와 `후보성 신호`를 분리해야 한다.
  - 즉, recall 우선은 유지하되 FP를 대량으로 만드는 정상 상계/정산/재분류는 최대한 줄인다.
- **탐지 로직**
  1. S0(강신호) ERP 구조 참조: `original_document_id`, `reversal_document_id`, `reference_document_id`, `reversal_reason` 등 원전표/역전표 연결 필드
  2. S2b(강신호) 단일 라인 차대변 스왑 서명: 한 라인의 방향 오류가 전표 불균형을 설명하는 경우
  3. S1(후보신호) 1:1 매칭: 동일 `gl_account` + 동일 금액 + 반대 방향(차↔대) + 짧은 시차. 구현은 line-level Python 전수 비교가 아니라 `document_id × gl_account` 집계 후 DuckDB self-join으로 후보쌍을 먼저 만들고, 그 후보에만 `created_by`, `reference`, `document_type`, 적요 유사성 등 문맥 점수를 Python 후처리로 계산한다.
  4. S2(후보신호) N:M 분할 역분개: `gl_account × created_by` 그룹, 짧은 윈도우 내 순액 ≈ 0. 단, 정상적인 단일 전표 내부 차대 균형을 피하기 위해 최소 2개 이상 `document_id`가 포함된 윈도우만 인정하고, 임시계정 정리/차입 상환/재분류처럼 FP가 많은 계정군은 별도 예외 또는 약한 신호로 처리한다.
  5. S3(보정신호) 정상/수정 구분: `auto/automated/recurring/batch/interface/system + 월초(D≤5)` = 위험점수 감점, `manual/adjustment` = 가중
  6. S4(보정신호) 적요 키워드: config/audit_rules.yaml `reversal_keywords` 18개
  7. S5(보정신호) 기말 부스트: 12/20~12/31 + 1/1~1/5 결산 전후 기간
- **판정 방향**
  - `S0` 또는 `S2b`가 있으면 `high-confidence reversal` 후보로 본다.
  - `S1`, `S2`는 단독으로는 `candidate reversal / clearing / reclass`에 가깝고, 문맥 키가 같이 맞을 때만 강하게 본다.
  - 즉 `금액 반전`만으로 바로 역분개라고 단정하지 않고, `금액 + 문맥`이 함께 맞을 때 우선순위를 높인다.
- **출력 해석 분리**
  - 내부 플래그는 계속 `L2-05` 하나로 유지한다. 즉 탐지 엔진 계약은 바꾸지 않는다.
  - 대신 row-level annotation에는 아래 해석 값을 함께 저장해서 UI, export, phase1 case builder가 같은 문장을 재사용하게 한다.
  1. `high-confidence reversal`
     - 조건: `S0` 또는 `S2b`
     - 의미: ERP 구조 참조가 있거나, 단일 라인 차대변 스왑으로 전표 불균형이 직접 설명되는 경우
  2. `candidate reversal / clearing / reclass`
     - 조건: `S1` 또는 `S2` 이고 `S0`, `S2b`는 없음
     - 의미: 금액 반전이나 순액 0 패턴은 있으나, 정상 상계/정산/재분류와 경계가 겹치는 경우
  - 따라서 화면과 리포트는 `L2-05`를 단순히 "역분개"라고만 쓰지 않고, 위 두 해석 중 하나로 풀어서 보여준다.
- **평가/리포트 표시 방식**
  - L2-05는 단일 precision/recall만으로 해석하지 않는다. `high-confidence reversal`과 `candidate clearing/reclass`를 같은 confirmed reversal 분모에 섞으면 정상 상계·정산 후보가 모두 false positive처럼 보일 수 있기 때문이다.
  - 리포트에는 `high_confidence_reversal_docs`, `candidate_clearing_reclass_docs` score band와 탐지기 breakdown(`high_confidence_count`, `candidate_count`)을 함께 표시한다.
  - `high_confidence_reversal`은 `ReversedAmount` confirmed label 평가와 우선 검토에 사용하고, `candidate_reversal_clearing_reclass`는 정상 clearing/reclass 여부를 확인하는 review population으로 본다.
  - `review_queue_docs`는 L2-05에 한해 단순 FP 문서 수가 아니라 `candidate_clearing_reclass_docs`를 우선 사용한다.
  - `c11_reversal_entry()`는 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
- **실무 해석 시 주의점**
  - `9990`, 차입금, 선수금, 자금이체성 계정, 임시계정, 재분류성 계정은 순액 0 패턴이 정상적으로 자주 나오므로 별도 관리가 필요하다.
  - DataSynth 기준 `ReversedAmount` TP는 현재 대부분 `S2b` 계열이라, `S1/S2`를 문맥 강화로 좁히는 것은 비교적 안전한 보정이다.
- **DataSynth 계약**: `ReversedAmount` 라벨은 실제 `journal_entries*.csv`에 존재하는 `document_id`만 가리켜야 한다.
- **평가 계약**
  - `ReversedAmount`는 high-confidence reversal의 confirmed subset이다.
  - `v115_candidate`부터 `rule_truth_L2_05*`와 `reversal_entry_review_population*`은 현재 `c11_reversal_entry()` detector output으로 재생성한 raw candidate universe다. 현재 문서 수는 `82`건이다.
  - L2-05 raw candidate는 high-confidence reversal뿐 아니라 정상 clearing/reclass population도 포함할 수 있다. 이 구분은 `queue_label`과 score로 판단한다.
  - `reversal_entry_review_population*`은 detector output snapshot이다. 독립 검증 sidecar가 아니다.
  - `v117_candidate`부터 독립 행동 검증용 sidecar는 `reversal_pattern_plausible_cases*`와 `reversal_pattern_normal_clearing_controls*`를 사용한다. 이 파일들은 detector output을 읽지 않고 anomaly label 또는 journal 업무 필드로만 선정한다.
  - `v117_candidate`부터 활성 `rule_truth_*`의 `source_candidate` 메타데이터는 모두 `v117`로 정리되어, 과거 후보 버전 기준이 활성 truth처럼 남지 않는다.
  - `candidate_reversal_clearing_reclass`는 정상 clearing/reclass 여부를 확인할 review population으로 남긴다.
  - 리포트 상태는 coverage anchor로 표시하고, `high_confidence_reversal_docs`와 `candidate_clearing_reclass_docs`를 분리한다.
- **ERP 구조 필드 우선 원칙**: 실제 ERP에서 별도 역분개 문서형이 많으면 `S0/S1` coverage가 중요하므로, 구조 필드가 있으면 최우선으로 활용한다.
- **구현**: `anomaly_rules_reversal.py` → `c11_reversal_entry()`
  - S1 후보 생성: DuckDB self-join
  - S1 후보 해석: Python 문맥 점수 후처리
- **필요 피처**: `gl_account`, `debit_amount`, `credit_amount`, `posting_date`, `document_id`
  - 보조: `created_by`, `source`, `reference`, `document_type`, `line_text`, `header_text`
- **성능**: S1은 `document_id × gl_account` 집계 후 `gl_account + 금액 + 시차` 기준으로 후보쌍을 먼저 만들고, reference/작성자/문서유형/적요 문맥 점수로 후보를 좁혀 Cartesian 폭발을 줄인다.

### Sidecar Evaluation Policy

- `v118_candidate`부터 `labels/sidecar_manifest.csv/json`을 sidecar 해석의 기준으로 사용한다.
- `v119_candidate`부터 L3-06 normal after-hours context는 anomaly-labeled 문서를 포함하지 않는다. labeled overlap은 `afterhours_cross_rule_labeled_context*`로 분리한다.
- `v119_candidate`부터 L3-03 IC exception sidecar는 case-level drilldown으로 본다. `ic_unmatched_cases*`, `ic_amount_mismatch_cases*`, `ic_timing_gap_cases*`, `transfer_pricing_review_cases*`는 `target_document_id`/`counterpart_document_id`로 L3-03 truth에 링크되며, `document_id` 기준 subset으로 평가하지 않는다.
- 파일명에 `control`, `negative`, `review_population`이 들어가도 의미가 같다고 보지 않는다.
- 독립 현실성 검증에는 `allowed_for_independent_sidecar_eval=True`인 sidecar만 사용한다.
- detector 계약 검증에는 `rule_truth_*` 또는 `purpose=detector_contract_universe`만 사용한다.
- `purpose=rule_truth_context`, `rule_truth_but_not_audit_issue`, `legacy_alias`, `contract_manifest`는 독립 현실성 평가 분모에 넣지 않는다.

---

### 2.3 L3: 검토 필요 이상징후 (12개 구현)

#### L3-01 — 계정 분류 불일치 (MisclassifiedAccount) ✅

- **심각도**: 3
- **근거**: 240-A45(c) 비정상 거래 특성, 315호 업무프로세스 이해와 위험평가
- **의미**
  - 특정 업무 프로세스에서 일반적으로 쓰이지 않는 계정이 사용된 경우를 검토 대상으로 올리는 룰이다.
  - 예를 들어 지급 프로세스(P2P)인데 매출성 계정이 쓰이거나, 인사/급여 프로세스(H2R)에서 무관한 자산·매출 계정이 쓰이는 식의 계정-프로세스 불일치를 본다.
- **감사인이 실제로 넣는 값**
  - `process_disallowed_categories`: "이 프로세스에서 원래 잘 안 쓰는 계정 종류"
  - `process_denied_accounts`: "이 프로세스에서 특히 위험하다고 보는 계정번호"
  - `process_allowed_keywords`: "계정은 어색해 보여도 정상 예외로 자주 나오는 적요"
- **판정 방식**
  - 내부 `IntegrityDetector` 실행 경로에서 `L1-01`, `L1-02`, `L1-03` 다음에 실행된다.
  - `process_denied_accounts`가 설정된 프로세스는 exact `gl_account` denylist를 우선 적용한다. 이 값은 회사별 CoA 기준으로 유지보수하는 것이 기본 운영 모델이다.
  - `process_denied_accounts`가 없는 프로세스만 `account_category` 또는 `account_group`을 사용한 category fallback을 적용한다. 해당 컬럼이 없으면 `gl_account` prefix를 `config/audit_rules.yaml`의 `l3_01_misclassified_account.account_category_prefixes`로 분류한다.
  - category fallback은 최소한의 금지 조합만 유지한다. 기본값은 `O2C->expense`, `P2P->revenue`, `H2R->revenue`, `TRE->inventory`, `A2R->payroll`이다.
  - 선택 옵션으로 `header_text` 또는 `line_text`에 `process_allowed_keywords`가 있으면 정상 예외로 보고 `L3-01`을 완화한다. 다만 기본값은 비워 둔다.
  - `L1-03`과 역할이 겹치지 않도록 CoA가 제공된 경우 유효 계정만 검사한다. CoA에 없는 계정은 `L1-03`이 담당한다.
  - 기본값은 `strict_allowed_categories: false`라서 명시적 금지 조합만 잡는다. 회사별 CoA/업무프로세스가 정리된 경우 `strict_allowed_categories: true`로 허용목록 방식 검사를 켤 수 있다.
- **출력 방식**
  - `L3-01`은 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
  - score 기준은 exact `process_denied_accounts` hit `0.65`, category fallback mismatch `0.45`, strict allowed-category mismatch `0.40`이다.
  - 이 score는 개별 전표 위험도 순위가 아니라 raw review population을 만들기 위한 원천 신호 점수다. exact hit가 여러 건 있어도 같은 원천 조건이면 같은 점수가 나올 수 있다.
  - PHASE1 공통 점수로 들어갈 때는 L3-01 전용 정규화를 적용해 raw 원인 순서를 보존한다. `severity=3`, `evidence_strength=medium`, L3 family weight `0.20` 기준 row `anomaly_score` 자연 기여도는 exact `0.0585`, category `0.0405`, strict `0.0360`이다. 따라서 L3-01 단독으로 row Low threshold `0.20`에 도달하지 않으며, exact denylist hit가 category fallback보다 낮게 정렬되는 현상을 방지한다.
  - `process_allowed_keywords`로 완화된 건은 score `0.00`으로 두고 `keyword_suppressed_rows/docs`에만 집계한다.
  - CoA에 없는 계정은 score `0.00`으로 두고 `invalid_account_excluded_rows`에 집계한다. 무효 계정 판단은 `L1-03` 소유다.
  - `row_annotations`에는 `reason_code`, `matched_reason_codes`, `score`, `business_process`, `gl_account`, `account_category`를 기록한다.
  - `breakdown`에는 `exact_denied_rows/docs`, `category_mismatch_rows/docs`, `strict_allowed_mismatch_rows/docs`, `keyword_suppressed_rows/docs`, `invalid_account_excluded_rows`, `missing_context_rows`, `reason_counts`를 기록한다.
- **실무 검토 큐 우선순위**
  - `L3-01` 단독 hit는 low/background population으로 취급한다. 예를 들어 P2P에서 revenue 계정이 쓰인 broad rule hit가 대량으로 발생해도, L3-01 원천 점수만으로 high priority 전표가 되지는 않는다.
  - 실무용 검토 순위는 `Phase1CaseBuilder`의 case priority에서 재산정한다. `L3-01`에 수기전표, 고액, 기말/마감일, 승인 문제, 심야/주말, 관계사, 반복 패턴, 다른 logic mismatch가 결합될 때만 priority를 올린다.
  - 기본 priority floor는 다음 해석을 따른다.
    - `L3-01` 단독: raw review population, low
    - `L3-01 + manual/adjustment`: 최소 `0.75`
    - `L3-01 + high amount` 또는 `period end`: 최소 `0.80`
    - `L3-01 + high amount + period end`: 최소 `0.85`
    - `L3-01 + approval issue/intercompany/repeat pattern`: 최소 `0.90`
    - `L3-01`에 3개 이상 주요 context가 결합: 최소 `0.95`
  - 조정 사유는 case 결과의 `priority_adjustment_reasons`에 `l301_context=...` 형식으로 남기고, 보정폭은 `l301_priority_bonus`에 기록한다.
- **평가/리포트 표시**
  - `score_bands`는 exact denylist hit를 `exact_denied_docs`, category/strict 기반 review hit를 `category_review_docs`로 분리한다.
  - `review_queue_docs`는 `L3-01` 전체 FP가 아니라 `category_review_docs`를 우선 사용한다. exact denylist hit는 회사별 CoA override가 반영된 고우선 신호로 별도 해석한다.
- **해석**
  - 이 룰은 `L1-03 무효 계정`과 다르다. L1-03은 존재하지 않거나 사용할 수 없는 계정이고, L3-01은 계정 자체는 유효하지만 업무 맥락이 어색한 경우다.
  - 실무에서는 "대분류 mismatch 단독"보다 "프로세스별 위험 계정번호"가 더 잘 작동한다. 따라서 기본 category 룰은 review seed로 두고, 고객사별 deny-account override로 정밀도를 올리는 구조가 권장된다.
  - 정상 예외 적요는 많이 넣으면 운영이 무너지고 recall도 떨어질 수 있다. 그래서 기본값은 비워 두고, 감사인이 반복 확인한 정상 예외 표현만 짧게 추가하는 것이 원칙이다.
  - `R2R`은 마감/재분류/조정 전표가 많아서 이 룰의 기본 프로세스 범위에 넣지 않는다. `R2R`의 MisclassifiedAccount 성격은 별도 룰 또는 NLP/ML 보조 신호로 다루는 편이 낫다.
- **구현 상태**
  - 구현: `src/detection/integrity_layer.py` → `_l301_misclassified_account()`
  - 설정: `config/audit_rules.yaml` → `l3_01_misclassified_account`
  - 파이프라인: 회사별 `audit_rules.yaml` override가 `AuditPipeline` → `IntegrityDetector`로 전달된다.
  - 평가 매핑: `src/metrics/rule_mapping.py`에서 내부 track은 하위 호환 키로 유지하고, 사용자 표시는 `L3 Review Needed`로 한다.
- **합성데이터 평가**: `v126` 기준 `MisclassifiedAccount`는 CoA에 존재하는 유효 계정만 사용한다. 따라서 L3-01은 "계정 자체가 틀림"이 아니라 "업무 프로세스와 계정 성격이 어색함"을 평가하며, `labels/misclassified_account_coa_fix_cases*`에는 v126에서 CoA 밖 GL을 유효한 process-mismatched 계정으로 교체한 19건이 기록된다. 과거 `v29_candidate`의 보수적 category/denylist 평가 기록은 `tests/phase1_rulebase/test-results/l3-01-synth-2022-2024.md`를 참조한다.
- **Phase 1 이후 사용 원칙**
  - `L3-01`은 단독 판정기가 아니라 "계정-프로세스 맥락이 어색하다"는 review seed로 사용한다.
  - `L1 통제 위반`, `수기 전표`, `기말 집중`, `고액`, `희소 계정쌍` 같은 다른 신호와 결합될 때 case priority를 높인다.
  - 단독 hit는 자동 결론을 내리지 않고, case grouping과 drill-down에서 적요, 문서유형, 반대 계정, 승인 흐름을 함께 확인한다.
- **필요 피처**: `business_process`, `gl_account`
  - 선택: `account_category`, `account_group`

#### L3-02 — 수기 전표 (Manual Entry Population) ✅

- **심각도**: 4
- **근거**: 240-A45(b) 비인가자 입력, K-SOX 우회금지(외감법§8②). FSS 가공전표: 자동 프로세스 우회
- **탐지 로직**: `is_manual_je == True`. `is_manual_je`가 없으면 `source`가 `manual_source_codes`에 포함되는지 본다.
- **해석 원칙**
  - L3-02 단독 hit는 부정이나 통제 우회 확정이 아니다. 수기/조정 전표 모집단을 넓게 태깅하는 review signal이다.
  - `ManualOverride` anomaly label은 일부 조작성 수기 시나리오이고, L3-02 운영 truth는 수기/조정 전표 전체 모집단이다.
  - 우선순위는 수기 전표 자체보다 승인통제 이상, 고액, 기말, 비정상 시점, 민감계정, 적요 결손과의 결합으로 정한다.
- **결과 표현**
  - `manual_population`과 `adjustment_population`은 `flagged_rules`에 넣지 않고 `review_rules`/annotation으로만 노출한다.
  - `manual_priority`와 `manual_control_bypass`만 confirmed/immediate hit로 보아 `details > 0` 및 `flagged_rules=L3-02`에 들어간다.
  - PHASE1 row-level `anomaly_score`는 population review score도 낮게 반영할 수 있지만, 위반 룰 집계와 DB `anomaly_flags`는 priority/control-bypass hit만 기준으로 삼는다.
  - 행별 점수와 bucket은 다음처럼 표시한다.

| 버킷 | 기준 | 해석 | row score |
|---|---|---|---:|
| `manual_population` | 일반 manual source 또는 `is_manual_je=True` | 수기 입력 모집단 | 0.35 |
| `adjustment_population` | `source == adjustment` | 결산/조정성 수기 모집단 | 0.35 |
| `manual_priority` | 수기 + 고액, 기말, 비정상 시점, 민감계정, 적요 취약 등 | 우선 검토 수기 전표 | 0.60 |
| `manual_control_bypass` | 수기 + 자기승인, 승인생략, 승인일 누락 등 | 승인통제 우회 후보 | 0.75 |
| `none` | L3-02 미해당 | 자동/반복/시스템 전표 | 0.00 |

- **우선순위 사유**
  - `self_approval`, `skipped_approval`, `missing_approval_date`
  - `high_amount`, `abnormal_time`, `period_end`, `weak_description`, `high_risk_account`
- **출력 메타데이터**
  - `score_series`: priority 0.60, control-bypass 0.75. 이 값만 `details`와 `flagged_rules`에 반영한다.
  - `review_score_series`: population 0.35. 단순 수기/조정 모집단은 `review_rules=L3-02`와 row annotation으로만 남긴다.
  - `row_annotations`: `bucket`, `score`, `source_bucket`, `priority_reasons`, `document_id`, `source`, `created_by`, `approved_by`, `approval_date`, `business_process`, `gl_account`, `description_quality`
  - `breakdown`: `flagged_rows`, `candidate_rows`, `review_rows`, `manual_rows`, `adjustment_rows`, `priority_rows`, `control_bypass_rows`, `source_counts`, `bucket_counts`, `priority_reason_counts`
- **평가/리포트 표시 방식**
  - 리포트에는 `manual_population_docs`, `priority_docs`, `control_bypass_docs` score band를 함께 표시한다.
  - `review_queue_docs`는 L3-02에 한해 `priority_docs + control_bypass_docs`를 우선 사용한다.
  - 단순 population coverage는 수기전표 식별 누락 여부를 보는 지표이고, priority/control-bypass band는 실제 감사 검토 우선순위 지표다.
- **구현**: `fraud_rules_feature.py` → `b08_manual_override()`
- **필요 피처**: `is_manual_je` 또는 `source`
- **처리 방식**: 수기 전표 자체는 독립 review 모집단으로 표시한다. 승인누락, 승인일 누락, 비정상 시간, 기말, 가계정/민감계정, 적요 결손/파손이 붙은 경우에만 L3-02 confirmed hit로 올리고, 나머지는 drill-down/필터용 context signal로 유지한다.
- **DataSynth truth 원칙**: `L3-02`는 수기전표 전체 모집단 coverage로 평가하고, 일부 조작성 시나리오 라벨인 `ManualOverride`와는 분리한다.

#### L3-03 — 관계사 거래 검토 신호 (RelatedPartyTransactionSignal) ✅

- **심각도**: 4
- **근거**: ISA 550 §23 특수관계자 거래의 사업상 합리성 검토. Phase 1에서는 순환 구조를 단정하지 않고 관계사 계정 사용 전표를 검토 후보로 올린다.
- **탐지 로직**: IC GL prefix 매칭
  - `intercompany_identifiers: ['1150', '2050', '4500', '2700']`
  - 관계사 채권/채무/매출/미지급 등 고객사 CoA상 IC 전용 계정 사용 여부만 판단
  - 실제 A→B→C→A N-hop 순환 탐지는 **GR01(GraphDetector)** 에서 담당 (§4.4 참조)
- **구현**: `fraud_rules_access.py` → `b10_intercompany_review_signal()`
- **필요 피처**: `is_intercompany` (`gl_account` prefix에서 생성), 보강 설명용 `company_code`, `trading_partner`, `reference`
- **출력 방식**
  - `L3-03`은 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
  - `score_series`는 관계사 거래 모집단을 `0.40`으로 표시한다. 이 점수는 순환거래 확정 점수가 아니라 후속 대사/그래프 분석 대상이라는 의미다.
  - `breakdown`에는 `ic_population_rows`, `ic_population_docs`, `ic_company_count`, `trading_partner_coverage_ratio`를 기록한다.
  - `row_annotations`에는 `signal_category=ic_population`, `company_code`, `trading_partner`를 기록한다.
- **실무 해석**: 단독 부정 적발이 아니라 특수관계자 거래 모집단/샘플링 후보. 계약서, 상대방, 정상가격, 대사 여부를 후속 확인한다.
- **PHASE1 제약**: 이 룰 계열은 recall 우선 스크리닝이다. 과탐을 줄이기 위해 IC prefix, 금액 차이, 시차, 그래프 가격 비대칭 조건을 임의로 좁혀 미탐을 늘리지 않는다. 정밀도 보정은 case priority, Phase 2 ranking, 감사인 검토 단계에서 처리한다.
- **PHASE1 점수 유입**
  - `L3-03` 단독은 모집단 신호다. PHASE1 공통 정규화 후 row `anomaly_score` 자연 기여도는 약 `0.036`이며, 단독으로 Low/Medium/High를 만들지 않는다.
  - `IC01/IC02/IC03`은 L1~L4 family 가중합에는 직접 들어가지 않지만, `IntercompanyMatcher` 결과가 제공되면 `score_aggregator`의 관계사 예외 보정에서 별도 floor를 적용한다.
  - `IC02` 또는 `IC03` 단독 예외는 row 최소 Low `0.20`으로 표시한다.
  - `IC01` 또는 2개 이상 IC 예외 결합은 row 최소 Medium `0.40`으로 표시한다.
  - 이 보정은 기존 `flagged_rules` 확정 룰 참조 생성 기준을 바꾸지 않는다. 출력에는 `intercompany_exception_score`, `intercompany_exception_reasons`로 별도 추적한다.
- **평가/리포트 표시 방식**
  - `L3-03`은 관계사 거래 모집단 룰이므로 `intercompany_population_truth`로 평가하고, 실제 비정상 순환거래 라벨인 `CircularIntercompany`/`CircularTransaction`과 혼동하지 않는다.
  - 리포트에는 `ic_population_docs`, `ic_exception_overlap_docs`, `graph_overlap_docs` score band와 탐지기 breakdown을 함께 표시한다.
  - `ic_population_docs`는 관계사 거래 review population이고, `ic_exception_overlap_docs`는 IC01/IC02/IC03 대사 예외와 결합된 문서 수다.
  - `graph_overlap_docs`는 GR01/GR03 그래프 신호와 결합된 문서 수이며, 순환 구조나 가격 비대칭 의심의 우선순위를 높이는 데 사용한다.
  - `review_queue_docs`는 L3-03에 한해 단순 FP 문서 수가 아니라 `ic_population_docs`를 우선 사용한다.
- **DataSynth 계약**: `v37_candidate`부터 IC GL prefix 기준 `intercompany_population_truth` sidecar를 별도로 관리한다.
- **DataSynth 예외 라벨**: `v38_candidate`부터 IC01/IC02/IC03/GR01/GR03 검증용 소량 truth를 `labels/intercompany_exception_cases*.csv/json`에 둔다. 이 라벨은 detector 결과를 역으로 채운 것이 아니라 정상 IC pair 일부에 거래상대 불일치, 금액 차이, 전기일 차이, 순환 seed, 가격 비대칭을 작게 주입한 scenario truth다. 정상 대조군은 `labels/intercompany_normal_controls*.csv/json`에 별도로 둔다.
- **GR01 평가 계약**: `v39_candidate`부터 GR01 hit 전체는 `labels/graph_gr01_review_population*.csv/json`에 review population으로 저장한다. 확정 이상은 기존 `CircularTransaction`/`CircularIntercompany` 라벨과 `labels/graph_gr01_confirmed_anomalies*.csv/json`만 사용하고, 정상 순환 대조군은 `labels/graph_gr01_normal_cycle_controls*.csv/json`로 분리한다. 따라서 GR01 raw hit 전체를 anomaly precision 분모로 쓰지 않는다.
- **IC01/IC02/IC03 평가 계약**: `intercompany_exception_cases` 전체를 한꺼번에 정답으로 쓰지 않는다. IC01은 `UnmatchedIntercompany`, IC02는 `IntercompanyAmountMismatch`, IC03은 `IntercompanyTimingMismatch`만 각각 평가한다. `target_document_id`가 주입 대상이며, counterpart 문서는 룰 성격에 따라 같이 flag될 수 있는 보조 문서다.
- **IC01 실무 기준**: 고객/벤더 코드(`C-000123`, `V-000123`)가 IC 계정에 들어온 경우는 DataSynth 현실성 노이즈로 보고 미대사 예외에서 제외한다. IC01은 명시적 회사 상대방 코드가 존재하지만 실제 회사코드와 대사되지 않는 고확신 케이스를 우선 flag한다.
- **표시 기준**:
  - `L3-03`: 관계사 거래 모집단
  - `IC01`: 고확신 미대사 예외 후보
  - `IC02`: 금액 불일치 검토 후보
  - `IC03`: 시차 불일치 검토 후보
  - `GR01`: 순환 구조 검토 후보. 확정 이상 평가는 `graph_gr01_confirmed_anomalies` 기준
  - `GR03`: 이전가격/금액 비대칭 검토 후보. 단독 확정 부정으로 표시하지 않음
- **실무 우선순위**
  - `L3-03` 단독: 낮음. 관계사 계정 사용 전표이므로 검토 모집단에 포함한다.
  - `L3-03 + IC01/IC02/IC03`: 미대사, 금액 차이, 기간 차이를 확인해야 하므로 우선순위를 높인다.
  - `L3-03 + GR01/GR03`: N-hop 순환 구조 또는 가격 비대칭이 확인된 경우로 매우 높은 우선순위로 본다.
- **한계**: 정상 내부거래도 많이 포함될 수 있으며, 이 룰만으로 순환거래나 부정을 단정하지 않는다. 고객사 CoA에서 관계사 계정 prefix가 다르면 `patterns.intercompany.pairs`를 먼저 보정해야 한다.

#### L3-04 — 기말/기초 결산 검토 후보군 (Period-start/end Closing Review) ✅

- **심각도**: 3
- **근거**: 240§32(a)(ii)+A44 기말검사 의무. FSS 결산수정 27건(29%)
- **탐지 로직**: 월말 전 5일 또는 월초 5일에 전기된 전표는 일단 L3-04 검토 후보로 올린다. 이 룰의 raw hit는 "기말/기초에 위치한 결산 검토 모집단"이며, 고액, 수기/조정, 민감 계정, 승인 문제, 비정상 시점은 hit 조건이 아니라 점수와 우선순위를 높이는 보강 신호다.
- **구현**: `anomaly_rules_simple.py` → `c01_period_end_large()`
- **필요 피처**: `posting_date`, `is_period_end` (파생). 점수 분리를 위해 금액, `is_manual_je`, 승인·시점·적요 피처를 함께 사용한다.
- **Phase 1 적용 방침**
  - 결산 일정은 회사별로 다르므로 감사인/사용자가 `period_end_margin_days`와 회계연도 기준을 engagement 시작 시 확정해야 한다. 기본값 5일은 제품 기본값일 뿐 회사 결산일을 대체하지 않는다.
  - 금액 기준은 L3-04 hit 여부가 아니라 우선순위 산정에 사용한다. 계정그룹별 Q3를 우선 사용하고, 계정그룹 표본이 `c01_min_group_size`보다 작으면 전체 Q3로 fallback한다.
  - 매출, 재고, 충당금, 미수/미지급, 손상 등 결산 민감 계정은 L3-04 단독 플래그를 늘리기보다 케이스 우선순위와 설명 가중치에서 상향한다.
- **결과 표현**
  - 룰 hit 자체는 `is_period_end=True` Boolean으로 유지한다.
  - 다만 L3-04 raw hit 전체를 동일 위험도로 보지 않고 아래 bucket과 row score를 함께 남긴다.
  - row-level `anomaly_score`에는 L3 family max score에 L3 가중치 `0.20`이 곱해져 반영된다. 따라서 L3-04 단독은 전체 High/Medium 판단을 만들지 않고, 다른 L1/L2/L4 또는 PHASE1 case 보강 신호와 결합될 때 우선순위가 올라간다.

| 버킷 | 기준 | 해석 | row score |
|---|---|---|---:|
| `closing_base` | 월말/월초 ±5일 전표 | 결산 시점 검토 모집단 | 0.00 |
| `closing_amount_p50` | 기말/기초 + 계정그룹 P50 초과 | 결산 금액 검토 모집단 | 0.20 |
| `closing_amount_p75` | 기말/기초 + 계정그룹 P75 초과 | 결산 고액 검토 모집단 | 0.35 |
| `closing_amount_p90` | 기말/기초 + 계정그룹 P90 초과 | 우선 검토 결산 고액 | 0.55 |
| `closing_amount_p95` | 기말/기초 + 계정그룹 P95 초과 | 최우선 검토 결산 고액 | 0.70 |
| `closing_recurring_low_priority` | L3-04 hit + 감사인이 승인한 반복 마감 패턴 | raw hit는 유지하되 낮은 우선순위로 표시 | 0.20 |
| `none` | L3-04 미해당 | 일반 시점 또는 일반 금액 | 0.00 |

- **보강 위험 신호**
  - `high_amount`, `manual_entry`, `abnormal_time`, `weak_description`, `long_day_gap`
  - `self_approval`, `skipped_approval`, `missing_approval_date`
  - 민감 계정군(`period_end_sensitive_accounts`)은 새로운 L3-04 hit를 만들지 않고, 기존 L3-04 score에 `period_end_sensitive_bonus`를 더해 우선순위만 높인다.
- **출력 메타데이터**
  - `score_series`: bucket별 row score
  - `row_annotations`: `bucket`, `score`, `priority_reasons`, `whitelist_matched`, `amount`, `threshold_amount`, `posting_date`, `source`, `created_by`, `approved_by`, `business_process`, `account_group`, `gl_account`, `description_quality`, `days_backdated`
  - `breakdown`: `flagged_rows`, `high_amount_rows`, `manual_rows`, `priority_rows`, `whitelisted_recurring_rows/docs`, `bucket_counts`, `priority_reason_counts`, `quantile`, `min_group_size`
- **평가/리포트 표시 방식**
  - 리포트에는 `closing_low_docs`, `closing_priority_docs`, `closing_high_docs` score band를 함께 표시한다.
  - `closing_low_docs`는 `0 < score < 0.60`, `closing_priority_docs`는 `0.60 <= score < 0.75`, `closing_high_docs`는 `score >= 0.75`로 계산한다. 민감 계정 보너스가 붙은 P90/P95 후보가 주로 priority/high band로 올라간다.
  - `review_queue_docs`는 L3-04에 한해 `closing_priority_docs + closing_high_docs`를 우선 사용한다. raw hit 전체 건수는 coverage 지표이며 감사 큐 건수로 직접 해석하지 않는다.
  - `RushedPeriodEnd` 확정 라벨 기준 precision/recall은 조작 시나리오 보조 참고값이다. L3-04 Phase 1 primary truth는 월말/월초 ±5일 review population coverage와 우선순위 band 분포다.
- **운영 전제**
  - L3-04는 탐지 제외 룰이 아니라 결산 검토 후보군이다. 따라서 플래그는 유지하고 화면/리포트 우선순위만 조정한다.
  - L3-04 단독은 low priority로 두고, `민감 계정`, `고액`, `주말/심야`, `전기일-문서일 장기 괴리`, `승인/중복/역분개`, `적요 부실` 신호와 결합될 때 medium/high로 올린다.
  - 자동 반복 마감전표는 사용자 whitelist를 기본 전제로 두지 않는다. 대신 같은 `company + source + document_type + business_process + gl_account + 월말/월초 구간`이 여러 달 반복되고 금액 변동이 작으면 반복 패턴으로 보고 점수만 downgrade한다. hard exclude는 하지 않는다.

#### L3-05 — 주말/공휴일 전기 (WeekendPosting) ✅

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. FSS 비정상시점 4건
- **탐지 로직**: `weekday() >= 5` 또는 한국 공휴일 플래그
- **출력 방식**
  - `L3-05`는 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
  - score 기준은 `weekday_holiday` 0.35, `weekend` 0.40, `weekend_holiday` 0.45다. 모두 단독 확정 이상이 아니라 낮은 우선순위 calendar review seed다.
  - PHASE1 전체 점수 반영 시에는 위 raw score를 `weekday_holiday=0.75`, `weekend=0.85`, `weekend_holiday=1.00` signal strength로 변환한다. 이를 통해 주말+공휴일이 주말 단독보다 낮게 집계되는 numeric normalization 불연속을 방지한다.
  - 최종 row-level `anomaly_score` 기여도는 L3 family weight 0.20 적용 후 대략 `weekday_holiday=0.027`, `weekend=0.031`, `weekend_holiday=0.036`이다. 따라서 L3-05 단독 hit는 Low threshold 0.20에 도달하지 않는다.
  - `row_annotations`에는 `reason_code`, `score`, `is_weekend`, `is_holiday`를 기록한다.
  - `breakdown`에는 `calendar_review_rows/docs`, `weekend_rows/docs`, `holiday_rows/docs`, `weekend_only_rows/docs`, `weekday_holiday_rows/docs`, `weekend_holiday_rows/docs`를 기록한다.
- **평가/리포트 표시 방식**
  - `score_bands`는 `calendar_review_docs`, `weekend_docs`, `weekday_holiday_docs`, `weekend_holiday_docs`로 나눈다.
  - `review_queue_docs`는 `L3-05` 전체 FP가 아니라 `calendar_review_docs`를 우선 사용한다. 확정 `WeekendPosting` 라벨 기준 precision은 보조 참고값이고, primary 해석은 review population coverage다.
- **구현**: `anomaly_rules_simple.py` → `c02_weekend_entry()`
- **필요 피처**: `posting_date`, `is_weekend` (파생), `is_holiday` (파생)
- **실무 해석**: 단독 부정 신호가 아니라 비근무일 처리 여부를 넓게 잡는 캘린더 기반 보조 신호다. 24/7 운영, 월마감, 자동/반복 전기, 해외·공장·물류 프로세스에서는 정상 주말 전표가 많을 수 있으므로 다른 위험 신호와 결합될 때 우선순위를 높인다.
- **운영 전제**: `is_holiday`는 한국 법정공휴일과 `custom_holidays`를 함께 본다. 감사인은 해당 회사의 창립기념일, 전사 휴무일, 공장 셧다운, 노사 합의 휴일 등 회사별 휴일을 `custom_holidays`에 입력해야 회사 실제 근무 캘린더 기준으로 탐지된다.
- **DataSynth 계약**: `v36_candidate`부터 정상 주말 처리 배경을 `normal_weekend_context` sidecar로 분리 관리한다.
- **DataSynth 평가 계약**: `v41_candidate`부터 L3-05 hit 전체(`is_weekend OR is_holiday`)는 `labels/weekend_review_population*.csv/json`에 review population으로 저장한다. 확정 이상은 기존 `WeekendPosting` 라벨과 `labels/weekend_confirmed_anomalies*.csv/json`만 사용하고, 정상 비영업일 운영 대조군은 `labels/normal_weekend_context*.csv/json`로 분리한다. 따라서 L3-05 raw hit 전체를 anomaly precision 분모로 쓰지 않는다.
- **v41 실측 결과**: `data/journal/primary/datasynth_v41_candidate` 2022~2024 기준 L3-05 raw hit는 24,307건이고, `weekend_review_population`도 24,307건으로 1:1 일치한다. 확정 `WeekendPosting` 라벨은 29건이며 모두 탐지되어 FN=0, recall=100%다. `raw hit - confirmed labels = 24,278건`은 확정 이상 오탐이 아니라 리뷰 모집단이다.
- **과탐 해석 기준**: L3-05는 넓은 캘린더 스크리닝 룰이다. `WeekendPosting` 확정 라벨만 정답으로 두면 precision이 낮아 보이지만, 이는 룰 목적과 다른 평가다. 운영 평가는 (1) 확정 라벨 recall, (2) `weekend_review_population` coverage, (3) 정상 대조군(`normal_weekend_context`)과의 분리 여부를 본다.
- **운영 사용 원칙**: L3-05 단독 hit는 low-priority review candidate로 두고, 수기 전표, 고액, 기말/기초, 승인 생략·자기승인, 중복/역분개, 적요 결손/파손, 특정 사용자 집중(L4-05)과 결합될 때 triage 우선순위를 올린다.

#### L3-06 — 심야 전기 (AfterHoursPosting) ✅

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. KLCA IT 체크리스트
- **탐지 로직**: `midnight_start`~`midnight_end` 심야 구간. 기본값은 22시~06시 (`midnight_start: 22`, `midnight_end: 6`)
- **구현**: `anomaly_rules_simple.py` → `c03_after_hours_entry()`
- **필요 피처**: `posting_date` (시간 포함), `is_after_hours` (파생)
- **출력 방식**
  - `L3-06`은 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
  - `score_series`는 사람/미상 source 심야 입력을 `0.45`, 정상 시스템·배치 context를 `0.20`으로 표시한다.
  - PHASE1 정규화는 위 raw band 순서를 그대로 보존한다. `normal_system_context=0.20`이 `confirmed_after_hours=0.45`보다 더 크게 row-level `anomaly_score`에 기여하면 안 된다.
  - `breakdown`에는 `confirmed_after_hours_rows`, `normal_system_context_rows`, `source_counts`, `time_bucket_counts`를 기록한다.
  - `row_annotations`에는 `bucket`, `score`, `source_category`, `time_bucket`, `source`, `created_by`를 기록한다.
- **평가/리포트 표시 방식**
  - L3-06은 단일 precision/recall만으로 해석하지 않는다. 정상 야간 배치와 사람의 심야 입력이 섞이면 시스템성 정상 context가 모두 false positive처럼 보일 수 있기 때문이다.
  - 리포트에는 `confirmed_after_hours_docs`, `normal_system_context_docs` score band와 탐지기 breakdown을 함께 표시한다.
  - `confirmed_after_hours_docs`는 사람 또는 source 미상 심야 입력 검토 모집단이고, `normal_system_context_docs`는 배치·인터페이스·시스템 계정의 정상 가능 context다.
  - `review_queue_docs`는 L3-06에 한해 단순 FP 문서 수가 아니라 `confirmed_after_hours_docs`를 우선 사용한다.
- **운영 전제**: 심야 시작/종료 시각은 회사 근무제, 교대근무, 해외법인 시간대, 마감 운영 정책에 맞게 조정한다. 주말/공휴일 전기는 L3-05, 사용자별 overtime·심야 집중은 L4-05에서 별도로 다룬다.
- **실무 해석**: L3-06 단독은 심야 전표 모집단 태그에 가깝다. 야간 배치, 해외/공유서비스 운영, 24시간 교대근무, 월마감 인터페이스가 있는 회사에서는 정상 심야 전표가 많으므로, `수기 전표`, `고액`, `기말/기초`, `승인 생략`, `자기승인`, `적요 결손/파손`, `특정 사용자 집중`과 결합될 때 우선순위를 올린다.
- **PHASE1 점수 유입 원칙**: L3-06은 severity 2, weak evidence로 유지한다. 따라서 단독으로 Medium/High를 만들지 않고, 전체 row score에는 낮은 timing contribution만 제공한다. 다만 사람/미상 심야 입력은 시스템·배치 context보다 높은 contribution을 유지하고, L1-05/L1-06/L1-07, L3-04, L3-08, L4-03, L4-05 등 독립 신호와 결합될 때 case priority와 triage에서 우선한다.
- **DataSynth 계약**: `AfterHoursPosting`을 L3-06 truth로 사용하고, 정상 심야 배경과 date-only/timezone 한계는 별도 sidecar로 분리 관리한다.

#### L3-07 — 전기일-문서일 장기 괴리 (Posting-Document Date Gap) ✅

- **심각도**: 3
- **근거**: 240-A45(c) 기말+설명없음. FSS 횡령은폐
- **탐지 로직**: `abs(posting_date - document_date) > N일` (기본 30일, 임계값 초과)
  - `posting_date - document_date > N`: 문서일 대비 장기 지연 전기
  - `posting_date - document_date < -N`: 선전기성 날짜 괴리 또는 미래 증빙 성격
  - 기본 30일 기준 bucket/score:
    - `*_moderate_gap`: 31~60일 괴리, score 0.45
    - `*_large_gap`: 61~90일 괴리, score 0.60
    - `*_extreme_gap`: 90일 초과 괴리, score 0.75
  - 방향 prefix는 `late_*`와 `forward_*`로 분리한다.
- **PHASE1 점수 반영**:
  - detector raw score는 리포트와 row annotation의 설명용 점수로 보존한다.
  - 전체 row-level `anomaly_score`와 case priority에서는 bucket label을 다시 정규화한다.
  - 정규화 signal strength는 `*_moderate_gap=0.55`, `*_large_gap=0.75`, `*_extreme_gap=1.0`이다.
  - `severity=3`, `evidence_strength=medium`, L3 family weight `0.20`이 적용되므로 L3-07 단독 전체점수 기여는 대략 `0.0495 / 0.0675 / 0.09`다. 단독 High/Medium 승격 신호가 아니라, 결산·통제·금액·적요 신호와 결합할 때 우선순위를 올리는 보조 신호다.
- **구현**: `anomaly_rules_simple.py` → `c04_backdated_entry()`
- **필요 피처**: `posting_date`, `document_date`, `days_backdated` (파생)
- **리포트 산출**:
  - `breakdown`: `flagged_rows`, `late_rows`, `forward_rows`, `bucket_counts`, `direction_counts`, `threshold_days`
  - `row_annotations`: `bucket`, `score`, `direction`, `days_backdated`, `abs_gap_days`, `threshold_days`, 날짜·입력경로 context
- **운영 해석**: PHASE1에서는 설명 가능한 1차 스크리닝 룰로 사용한다. 이 룰은 `BackdatedEntry`와 `LatePosting` 성격을 모두 포착하는 날짜 괴리 신호이며, 단독으로 부정이나 소급 입력을 확정하지 않는다. 실무에서 진짜 마감 후 소급 입력을 보려면 `entry_date`/`created_at`과 `posting_date`의 차이를 별도 룰로 보강해야 한다.
- **DataSynth 계약**: `v33/v34_candidate`에서 `LatePosting` 라벨 정합성과 정상 업무 지연 negative control을 분리 관리한다.

#### L3-08 — 적요 결손/파손 신호 (MissingOrCorruptedDescription) ✅

- **심각도**: 1
- **근거**: 240-A45(c) 설명없음, K-SOX§8①1호 기록방법
- **탐지 로직**: `line_text + header_text`를 합쳐 본 뒤, 설명이 사실상 없거나 문자열이 깨진 경우만 포착한다.
  - `missing`: 공백 또는 누락
  - `corrupted`: 특수문자만 있거나, 같은 문자가 반복되는 등 명백한 garbage 문자열
- **Phase 1 범위**: 의미상 설명이 충분한지까지 판단하지 않고, **기록이 비어 있거나 망가진 상태**만 좁게 본다.
- **구현**: `anomaly_rules_simple.py` → `c06_missing_or_corrupted_description()`
- **필요 피처**: `line_text`, `header_text`, `description_quality` (파생)
  - 운영 진단용 보조 피처: `description_line_missing`, `description_header_missing`, `description_both_missing`, `description_line_missing_header_present`, `description_is_missing_or_corrupted`
- **출력 방식**
  - `L3-08`은 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
  - `score_series`는 `missing=0.45`, `corrupted=0.55`, legacy `poor=0.50`으로 표시한다. 이 점수는 부정 확정도가 아니라 기록통제 품질 저하 강도다.
  - `breakdown`에는 `missing_rows`, `corrupted_rows`, `poor_legacy_rows`, `quality_counts`를 기록한다.
  - `row_annotations`에는 `description_quality`, `bucket`, `score`, `line_missing`, `header_missing`, `both_missing`을 기록한다.
- **평가/리포트 표시 방식**
  - L3-08은 단일 precision/recall만으로 해석하지 않는다. `missing`, `corrupted`, legacy `poor`가 섞이면 결손 적요와 파손 적요, 과거 호환 alias가 모두 같은 hit로 보이기 때문이다.
  - 리포트에는 `missing_description_docs`, `corrupted_description_docs`, `poor_legacy_docs` score band와 탐지기 breakdown을 함께 표시한다.
  - `missing_description_docs`와 `corrupted_description_docs`는 Phase 1 L3-08 직접 검토 모집단이고, `poor_legacy_docs`는 과거 데이터 호환 alias로 별도 해석한다.
  - `review_queue_docs`는 L3-08에 한해 단순 FP 문서 수가 아니라 위 세 band의 합계를 우선 사용한다.
- **실무 해석**: 이 룰은 강한 부정 신호가 아니라 **기록통제 품질 저하 신호**다. 자동전표, 인터페이스 전표, 레거시 적재 데이터에서는 빈 적요가 나올 수 있으므로, 단독으로는 우선순위를 높게 두지 않는다.
- **PHASE1 점수 유입**: L3-08은 `weak` evidence이자 `booster` role이다. raw `0.45/0.55`는 기록품질 강도일 뿐이고, PHASE1 normalized score에는 낮은 보조값으로만 들어간다. `weak_evidence_bonus`의 `missing_or_corrupted_description` 태그도 L3-08 단독으로는 생성하지 않고, `config/phase1_case.yaml`의 `l3_08_corroborating_rules`에 포함된 독립 보강 룰과 결합될 때만 생성한다.
- **Phase 1 운영 진단**: L3-08 룰 자체를 더 복잡하게 만들지 않고, 결손이 어디서 발생하는지 별도 coverage profile로 본다.
  - `line_text`와 `header_text`가 모두 비었는지
  - `line_text`는 비었지만 `header_text`가 있어 설명이 보완되는지
  - `source`, `business_process`, `document_type`별 결손/파손률이 특정 입력 경로에 집중되는지
  - 구현: `text_features.py` → `build_description_quality_profile()`
- **위험도가 높아지는 결합 신호**
  - `L3-02 수기 전표`: 사람이 직접 입력했는데 설명이 없음
  - `L3-04 기말/기초 결산 검토 후보군`: 결산 조정성 전표인데 설명이 없음
  - `L1-05 자기승인`, `L1-07 승인 생략`: 통제 우회와 기록 결손이 함께 나타남
  - `L2-05 역분개 패턴`: 수정·취소 성격 전표인데 설명이 없음
  - `L3-10 고위험 계정 사용`, `L3-09 가수금 장기체류`: 민감 계정을 건드리는데 설명이 없음
  - `L3-05 주말 전기`, `L3-06 심야 전기`: 비정상 시점 처리와 설명 결손이 함께 나타남
- **운영 방침**: `L3-08` 단독 hit는 low priority로 두고, 위 신호와 결합될 때만 `case_priority` 보조 가점을 허용한다. L3-08 단독 case는 화면 설명과 review context에는 남기되, `weak_evidence_bonus`를 통해 priority를 올리지 않는다.
- **추가하지 않는 것**: Phase 1에서는 키워드 기반 위험 적요 판단, 회사별 whitelist/blacklist 운영, 적요 의미 충분성 판단, 계정-적요 의미 정합성 판단을 하지 않는다. 이들은 Phase 3 NLP/LLM 영역으로 둔다.
- **한계**: 말은 길지만 실질 설명이 없는 적요, 회사 내부 은어, 계정/프로세스와 어울리지 않는 적요는 Phase 1에서 판단하지 않는다. 이런 의미 기반 평가는 Phase 3 NLP/LLM 계층에서 다룬다.
- **DataSynth 평가 계약**: `v43_candidate`부터 Phase 1 L3-08 truth는 `MissingOrCorruptedDescription`과 `labels/missing_corrupted_description_truth*.csv/json`만 사용한다. 기존 `VagueDescription`은 보존하되 `labels/vague_or_risky_description_truth*.csv/json`를 통해 Phase 3 NLP/LLM용 의미상 모호/위험 적요 truth로 분리한다. 따라서 `VagueDescription` 전체를 L3-08 precision/recall 분모로 쓰지 않는다.
- **DataSynth 경계 대조군**: `v44_candidate`부터 `labels/description_boundary_normal_controls*.csv/json`에 짧지만 정상인 적요, 정상 시스템 코드형 적요, `line_text`는 비었지만 `header_text`가 충분한 케이스, Phase 3용 의미상 vague 케이스를 정상 control로 둔다. v43의 100% 정렬은 계약 테스트이며 실무 precision/recall로 해석하지 않는다.
- **이번 코드 반영 사항**
  - `description_quality` 판정값을 `missing / corrupted / normal`로 정리하고, 과거 `poor`는 legacy alias로만 허용한다.
  - `has_risk_keyword`는 계속 생성하지만 L3-08 판정에는 사용하지 않는다.
  - `description_line_missing`, `description_header_missing`, `description_both_missing`, `description_line_missing_header_present`, `description_is_missing_or_corrupted`를 추가해 원천 필드 결손 위치를 운영 진단할 수 있게 했다.
  - `build_description_quality_profile()`로 `source`, `business_process`, `document_type`별 결손/파손률을 볼 수 있게 했다. 이 profile은 룰 hit를 늘리는 용도가 아니라 데이터 품질 원인 분석용이다.

#### L3-09 — 가수금 장기체류 (SuspenseAccountAbuse) ✅

- **심각도**: 3
- **근거**: 외감법§8①2호 오류통제. FSS 횡령은폐: 가수금을 통한 자금 유용
- **탐지 로직**:
  - 모집단: `is_suspense_account == True`
  - 미정리 상태: `amount_open > suspense_min_open_amount` 또는 `is_cleared == False` 또는 `settlement_status ∉ {settled, cleared, closed, resolved, matched}`
  - fallback: 위 정산 정보가 없을 때만 `settlement_date IS NULL`, `lettrage_date IS NULL`, `lettrage IS NULL/blank`를 보조 신호로 사용
  - 체류 기간: `posting_date`부터 정산일(`settlement_date` 또는 `lettrage_date`)까지, 정산일이 없으면 데이터셋 기준일(max `posting_date`)까지의 경과일수
  - 최종 판정: `is_suspense_account == True` 이고 `unresolved == True` 이며 `aging_days >= suspense_aging_days`
- **구현**: `anomaly_rules_simple.py` → `c10_suspense_account()`
- **필요 피처**: `is_suspense_account`, `posting_date`, 그리고 가능하면 `amount_open` 또는 `is_cleared` 또는 `settlement_status`/`settlement_date`
- **결과 제시 방식**
  - L3-09의 raw hit는 확정 `SuspenseAccountAbuse`가 아니라 장기 미정리 가계정 review population이다.
  - `aging_30_60`: `suspense_aging_days <= aging_days < suspense_aging_days * 2`, row score `0.45`
  - `aging_60_90`: `suspense_aging_days * 2 <= aging_days < suspense_aging_days * 3`, row score `0.60`
  - `aging_over_90`: `suspense_aging_days * 3 <= aging_days`, row score `0.75`
  - flagged 모집단 내 미정리 금액 상위 bucket(`open_amount_high`)은 `+0.05`를 더하되 최대 `0.80`으로 제한한다.
  - 금액 bucket은 flagged rows의 `amount_open` 절대값 기준으로 `open_amount_low / open_amount_medium / open_amount_high / unknown_amount`를 부여한다. `amount_open`이 없고 차변/대변 금액이 있으면 gross amount를 보조값으로 쓴다.
- **PHASE1 통합점수 반영**
  - L3-09는 `logic_mismatch`, `evidence_strength=medium`, `scoring_role=primary`로 정규화된다.
  - detector row score는 PHASE1에서 단조 보존된다. 기본 normalized contribution은 `row_score * 0.75`이며, 따라서 `0.45 -> 0.3375`, `0.60 -> 0.45`, `0.75 -> 0.5625`, `0.80 -> 0.60`이다.
  - 이 값은 case-level `logic_score`에 들어가고, 기본 `case_priority`에서는 `0.15 * logic_score`로만 반영된다. L3-09 단독 High floor는 두지 않는다.
  - `L3-09 + L3-08/L3-07/L3-04/L4-03`처럼 설명 부실, 날짜 괴리, 기말 조정, 고액 신호가 결합될 때 case priority가 올라가도록 해석한다.
- **리포트/평가 bucket**
  - `suspense_aging_review_docs`: `0 < score < 0.60`
  - `suspense_aging_priority_docs`: `0.60 <= score < 0.75`
  - `suspense_aging_high_docs`: `score >= 0.75`
  - `review_queue_docs`는 priority + high bucket만 합산한다. review bucket은 coverage/모집단 확인용으로 남긴다.
- **메타데이터**: `aging_bucket_counts`, `open_amount_bucket_counts`, `high_open_amount_rows`, row annotation(`aging_days`, `threshold_days`, `aging_bucket`, `open_amount`, `open_amount_bucket`, `score`)을 제공한다.
- **운영 전제**:
  - 이 룰의 핵심은 `가계정 사용`이 아니라 `장기 미정리(open)`다.
  - `lettrage` 계열은 ERP/국가별 편차가 커서 보조 입력으로만 사용한다.
  - Phase 1에서는 계정별 적응형 grace 보정 없이, 정해진 `suspense_aging_days`를 공통 기준으로 사용한다.
  - 정상 clearing 계정 구분, 계정별 grace 추천, 예외 후보 자동 제안은 Phase 2/3 보조 분석으로 넘긴다.
- **DataSynth 평가 계약**: `v42_candidate`부터 `lettrage`, `lettrage_date`, `amount_open`, `is_cleared`, `settlement_status`, `settlement_date`를 원장에 포함한다. `labels/suspense_lifecycle_population*.csv/json`은 가계정 정산 lifecycle 모집단, `labels/suspense_aging_review_population*.csv/json`은 L3-09 raw review population, `labels/suspense_confirmed_anomalies*.csv/json`은 확정 `SuspenseAccountAbuse` truth, `labels/suspense_normal_controls*.csv/json`은 정상 clearing 대조군이다. L3-09 raw hit 전체를 확정 anomaly precision 분모로 쓰지 않는다.
- **Phase 3 이관**: 적요 의미 분석은 별도다. L3-09는 Phase 1에서 `정산상태 + 체류일수`를 본다.

#### L3-10 — 고위험 계정 사용 (HighRiskAccountUse) ✅

- **심각도**: 3
- **근거**: 현금성 계정, 가계정, 가지급금/대여금/선급금 등 감사인이 지정한 **민감 계정군** 사용은 별도 검토 대상이다.
- **탐지 로직**: `gl_account`가 `patterns.high_risk_account_use.accounts`와 일치하거나 `account_prefixes`로 시작하는 경우
- **구현**: `fraud_rules_access.py` → `b13_high_risk_account_use()`
- **필요 피처**: `gl_account`
- **Phase 1 적용 방침**
  - 이 룰은 강한 단독 적발 룰이 아니라 `logic_mismatch` 계열의 **민감 계정 접촉 신호**로 사용한다.
  - 기본 제품값(`1190`, `2190`, `111*`, `112*`, `113*`)은 starter default이며, 실제 운영에서는 고객사 CoA와 감사 범위에 맞게 조정한다.
  - 현금성/가계정/가지급금/대여금/선급금/상품권/임시정산 계정 등 민감 계정군을 engagement 초기에 확정하고, `L3-02`, `L1-05`, `L1-07`, `L3-04`, `L3-08`, `L4-04` 등과 결합될 때 우선순위를 높인다.
- **결과 제시 방식**
  - `raw_signal`: 민감 계정군을 건드린 전체 모집단이다. 단독 부정 경고가 아니라 review population으로 보여준다.
  - `priority_case`: `raw_signal` 중 수기/조정, 고액, 미정리, 승인일 누락, 기말/비정상시점 같은 보강 맥락이 있는 우선 검토 건이다.
  - `normal_control_candidate`: `raw_signal` 중 자동/반복/시스템 처리 등 정상 사용 맥락이 강한 건이다. 낮은 우선순위 또는 whitelist 후보로 본다.
  - 따라서 화면과 리포트는 `L3-10 전체 건수`와 `우선 검토 건수`를 분리해서 보여준다. `HighRiskAccountUse` confirmed label과 직접 precision을 비교할 때는 `priority_case`만 별도로 본다.
- **출력 메타데이터**
  - boolean flag는 민감 계정 접촉 전체(`raw_signal + priority_case + normal_control_candidate`)를 보존한다.
  - `score_series`: `priority_case=0.65`, `raw_signal=0.35`, `normal_control_candidate=0.20`으로 구분한다. 이 점수는 확정 부정 확률이 아니라 리포트/정렬용 우선순위다.
  - `breakdown`: `reason_counts.exact/prefix/category_counts`와 함께 `raw_signal_rows`, `priority_case_rows`, `normal_control_candidate_rows`를 제공한다.
  - `row_annotations`: `match_type`, `matched_value`, `matched_group`, `signal_category`, `category_reason`을 제공한다.
- **PHASE1 통합점수 반영**
  - L3-10은 `logic_mismatch`, `evidence_strength=weak`, `scoring_role=booster`로 정규화된다.
  - detector row score는 PHASE1에서 단조 보존된다. 기본 normalized contribution은 `row_score * 0.1755`이며, 따라서 `normal_control_candidate 0.20 -> 0.0351`, `raw_signal 0.35 -> 0.061425`, `priority_case 0.65 -> 0.114075`이다.
  - row-level `anomaly_score`에는 L3 family weight `0.20`이 다시 적용되므로 단독 기여도는 각각 약 `0.007`, `0.012`, `0.023`에 그친다. 민감 계정 접촉만으로 Low/Medium/High를 만들지 않는 의도다.
  - case priority에서는 `priority_case`에 `min_priority_score: 0.45` floor를 적용한다. 단독 High는 만들지 않지만, 보강 맥락이 있는 민감 계정 접촉은 Medium 검토 큐에서 사라지지 않게 한다.
- **평가/리포트 표시 방식**
  - L3-10은 단일 precision/recall로만 해석하지 않는다. 리포트는 `raw_sensitive_touch_docs`, `priority_case_docs`, `normal_control_docs`를 range band로 표시한다.
  - `review_queue_docs`는 L3-10 전체 hit가 아니라 `priority_case_docs`를 사용한다. raw 민감 계정 접촉은 coverage, 정상 통제 후보는 false positive가 아니라 대조군/whitelist 후보로 본다.
- **운영 전제**
  - 민감 계정 정의는 시스템이 자동 확정하지 않는다. 최종 계정군 정의와 예외 범위는 감사인 또는 사용자가 승인한다.
  - 회사별 CoA가 다르므로 같은 `111*` 계열이라도 어떤 회사에서는 현금성 계정이지만, 다른 회사에서는 전혀 다른 의미일 수 있다. 따라서 prefix 기본값을 그대로 쓰는 것은 임시 초기값으로만 본다.
  - UI/설정 문서에는 이 룰을 `고위험 계정 사용`보다는 `민감 계정군 접촉 신호`에 가깝게 설명하는 편이 실무 해석에 맞다.
- **DataSynth 평가 계약**: `v45`부터 L3-10은 라벨-only precision/recall로 평가하지 않는다. `labels/high_risk_account_review_population*.csv/json`가 L3-10 raw coverage truth이며, `HighRiskAccountUse` 및 `labels/high_risk_account_confirmed_anomalies*.csv/json`는 `priority_case` 성격의 일부 의심 케이스만 담는다. `labels/high_risk_account_normal_controls*.csv/json`에는 정상적인 민감 계정 사용 대조군을 둬서 “민감 계정이면 모두 부정”이라는 shortcut 학습을 막는다.
- **DataSynth 구현 주의**: CSV에서 `gl_account`가 `1190.0`처럼 읽히는 경우가 있으므로 L3-10 계정 비교는 trailing `.0`을 제거한 계정코드로 수행한다.

#### L3-11 — 매출 컷오프 불일치 (RevenueCutoffMismatch) ✅

- **심각도**: 3
- **근거**: 240§32(b), 315호, K-IFRS 15 수익 인식 기간귀속
- **성격**: Phase 1 review-needed 룰. 단독 부정 확정이 아니라, 수익 인식 시점과 근거 이벤트 시점이 맞는지 보는 cutoff 검토 신호다.
- **현재 탐지 로직**
  - `posting_date`와 `delivery_date`가 모두 존재하는 행만 검사한다.
  - 매출 계정(`is_revenue_account` 또는 `revenue_account_prefixes`)은 `ev_revenue_cutoff_days`를 적용한다.
  - 비용 계정(`expense_account_prefixes`)은 `ev_expense_cutoff_days`를 적용한다.
  - 차이가 허용일수를 초과하면 `day_diff / ev_cutoff_max_day_diff`로 점수화하고, 기말 전표(`is_period_end`)는 `ev_cutoff_period_end_weight`를 곱한다.
- **출력 방식**
  - `L3-11`은 raw cutoff score 외에 `breakdown`, `row_annotations`를 함께 제공하고, `EvidenceDetector`에서 severity factor를 곱해 최종 `details["L3-11"]`에 반영한다.
  - raw score는 `day_diff / ev_cutoff_max_day_diff` 기반이며, `is_period_end`가 참이면 `ev_cutoff_period_end_weight`를 적용한 뒤 `1.0`에서 cap한다. 기본 severity factor는 `3/5=0.6`이다.
  - `row_annotations`에는 `reason_code`, raw `score`, `day_diff`, `cutoff_days`, `account_type`, `period_end_weighted`, `use_business_days`를 기록한다.
  - `breakdown`에는 `cutoff_review_rows/docs`, `revenue_cutoff_rows/docs`, `expense_cutoff_rows/docs`, `period_end_weighted_rows/docs`, `missing_event_date_rows/docs`, `reason_counts`, 적용 파라미터(`max_day_diff`, `revenue_cutoff_days`, `expense_cutoff_days`, `use_business_days`)를 기록한다.
  - **평가/리포트 표시 방식**
    - `score_bands`는 최종 Evidence 점수 기준 `cutoff_review_docs`, `cutoff_priority_docs(>=0.30)`, `cutoff_high_docs(>=0.60)`로 나눈다.
    - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `cutoff_review_docs`를 우선 사용한다. reasonable-delay control은 raw hit가 될 수 있으므로 case priority/Phase 2에서 정상 사유를 확인한다.
    - PHASE1 case priority에는 `timing_score`로 직접 반영한다. raw cutoff score `>=0.60`은 Medium floor, raw cutoff score `>=0.30`과 `L4-01`이 결합된 경우는 High floor를 적용한다.
- **실무 해석**
  - `delivery_date`는 모든 거래의 정답 기준일이 아니라, Phase 1에서 사용할 수 있는 **인식 기준 이벤트의 proxy**다.
  - 제품/상품/O2C 출하 매출에서는 비교적 강한 신호로 본다.
  - 용역, 구독, 공사, 검수조건부, 설치조건부 거래는 `service_confirmation_date`, `service_end_date`, `acceptance_date`, `installation_complete_date`, `billing_plan` 같은 더 적합한 기준일이 있으면 그 날짜를 우선해야 한다.
  - 기준일 후보가 없으면 정상으로 판정하지 않고, cutoff 검증 불가로 해석한다.
- **한계**
  - ERP에 반품권, 검수조건, 설치조건, 기간용역 조건이 항상 구조화 필드로 존재하지 않는다.
  - 계약서/첨부/OCR/업무 모듈에만 있는 조건은 Phase 1 단순 룰로 확정하지 않는다.
  - `delivery_date`가 없는 거래를 0점으로 두는 것은 "정상"이 아니라 "이 룰로는 미검증"이라는 의미다.
- **DataSynth 평가 계약**
  - `v46_candidate`부터 `RevenueCutoffMismatch`와 `ExpenseCutoffMismatch` confirmed label을 추가한다.
  - `labels/cutoff_confirmed_anomalies*.csv/json`는 confirmed subset이다.
  - `labels/cutoff_review_population*.csv/json`는 raw L3-11 hit coverage다.
  - `labels/cutoff_normal_controls*.csv/json`는 허용 범위 정상 대조군이다.
  - `labels/cutoff_reasonable_delay_controls*.csv/json`는 룰에는 걸리지만 정상 사유가 가능한 장기 지연 대조군이다.
  - `labels/cutoff_untestable_controls*.csv/json`는 `delivery_date` 부재로 미검증인 대조군이다.
  - 따라서 L3-11은 미탐 0만 보고 성공으로 해석하지 않고, reasonable-delay control이 raw FP로 남는지 함께 본다.
- **조합 시 위험도 해석**
  - `L3-11 단독`: 기간귀속 검토 후보. Medium.
  - `L3-11 + L4-01`: 고액 매출과 cutoff 불일치가 결합된 강한 매출 검토 후보. High.
  - `L3-11 + L4-01 + L3-04`: 기말 고액 매출 cutoff 후보. High~Critical.
  - `L3-11 + L4-01 + L3-02/L1-07/L1-05`: 수기 또는 승인통제 우회가 붙은 고액 cutoff 후보. Critical.
- **구현**
  - 오케스트레이터: `evidence_detector.py` → registry rule id `L3-11`
  - 룰 함수: `evidence_rules.py` → `ev02_cutoff_violation()`
- **필요 피처/컬럼**
  - 필수 비교: `posting_date`, `delivery_date`
  - 계정 분류: `is_revenue_account` 또는 `gl_account`
  - 보강: `is_period_end`, `business_process`, `document_type`, 기준 이벤트 날짜(`acceptance_date`, `service_end_date`, `installation_complete_date` 등)

#### L3-12 — 업무범위 집중 검토 (WorkScopeExcessReview) ✅

- **심각도**: 3
- **근거**: K-SOX 접근권한 검토, 직무분리 설계 검토, 사용자 권한의 최소권한 원칙. 한 사용자가 여러 업무영역에 넓게 관여하면 부정 확정은 아니지만 권한 과다, 직무집중, 보완통제 필요성을 검토할 근거가 된다.
- **성격**: Phase 1 review-only score rule. 과거 이력 또는 동료 baseline을 학습하지 않고, 현재 감사기간 데이터 안에서 사용자별 업무영역 폭을 숫자로 산정한다.
- **판정 단위**: 기본 판정 단위는 전표가 아니라 `created_by` 사용자다. 행별 `review_score_series`는 사용자 점수를 현재 기간 활동 행에 투영한 review/evidence 표현이며, 확정 위반 Boolean이 아니다.
- **탐지와 점수 분리**: `business_process >= 3` 또는 사용자 유형별 업무범위 기준을 넘으면 자동/시스템 계정까지 raw candidate로 보존한다. 점수는 별도 위험도이며, 정상 가능성이 높은 시스템/관리자 breadth는 `0.00` 또는 낮은 review score로 둔다.
- **L1-06과의 경계**
  - L1-06은 금지된 업무분장 조합, 명시적 SoD conflict, 승인/작성 역할 충돌처럼 **확정 가능한 통제 위반**을 잡는다.
  - L3-12는 금지 여부를 판단하지 않는다. 한 사용자가 여러 프로세스, 회사, 전표유형, 계정군, 입력방식에 과도하게 관여하는 정도를 사용자 점수로 산정하고, 수기·민감계정·고액·결산 같은 문맥은 우선순위 보강 근거로만 쓴다.
  - L3-12 hit는 L1-06의 FP/FN/precision/recall에 포함하지 않는다.
- **탐지 로직**
  - `fiscal_year`가 있으면 `fiscal_year + created_by`별로 현재 데이터의 `business_process`, `company_code`, `document_type`, `gl_account` 계정군, `source` distinct count를 집계한다. `fiscal_year`가 없을 때만 기존처럼 `created_by`별로 집계한다.
  - `user_persona`가 있으면 사용자 유형별 기준을 적용한다. 없으면 default 기준을 쓴다.
  - 자동/배치 계정도 업무범위가 넓으면 raw candidate로 남긴다. 다만 기본 score는 `0.00`이며, 수기/조정 source와 민감계정·고액·결산 맥락이 함께 있을 때만 낮은 system review score를 부여한다.
  - L3-12는 사용자-year 단위 review score다. 한 사용자가 특정 연도 안에서 업무범위 집중 기준을 충족하면 사용자-year summary에 점수와 근거를 저장하고, 해당 사용자-year의 현재 기간 활동 행에는 같은 점수를 evidence projection으로 부여한다. 자동/system-only와 admin/superuser 단순 breadth는 raw candidate로 보존하되 score `0.00`으로 둘 수 있다. 단독 L3-12는 High가 아니며 다른 룰과의 결합 여부로 우선순위를 조정한다.
  - admin/superuser는 단순 다중범위만으로 플래그하지 않고, 수기·민감·고액·결산 등 보강 신호가 2개 이상일 때만 올린다.
- **기본 기준**

| 조건 | 점수 |
|---|---:|
| 사용자 1명이 `business_process >= 3`만 해당 | `0.20` |
| `business_process >= 3` + `company_code >= 2` | `0.30` |
| `business_process >= 4` 또는 `company_code >= 3` | `0.35` |
| 위 조건 + `manual/adjustment` 포함 | `0.45` |
| 위 조건 + 민감 계정군 포함 | `0.50` |
| `business_process >= 4` + `company_code >= 3` + 수기 포함 | `0.55` |
| 위 조건 + 결산일/고액/민감계정 중 2개 이상 | `0.65` |
| L1-05/L1-06/L1-07 동반 | L3-12는 `0.65` 이하, L1이 주 신호 |

- **사용자 유형별 시작 기준**

| 사용자 유형 | L3-12 시작 기준 |
|---|---|
| `junior`, `staff`, `clerk` | process `>= 3` 또는 company `>= 2` |
| `senior`, `accountant` | process `>= 4` 또는 company `>= 3` |
| `manager`, `controller` | process `>= 5` 또는 company `>= 4` |
| `admin`, `superuser` | raw candidate로 보존하되 단순 다중업무는 score `0.00`, 수기/민감/고액/결산 중 2개 이상 결합 시 점수 부여 |
| `automated_system`, `batch_user` | raw candidate로 보존하되 기본 score `0.00`, 수기/조정 source와 보강 신호가 함께 있을 때 낮은 system review score |

- **결과 표현**
  - `score_series`: 항상 `0.00`을 유지한다. L3-12는 확정 위반이 아니므로 `flagged_rules`와 DB `anomaly_flags` 집계에 들어가지 않는다.
  - `review_score_series`: `0.00~0.65` 사용자 업무범위 집중 review score를 제공한다. 이 값은 row `anomaly_score`와 PHASE1 case priority에 weak/booster 신호로만 반영된다.
  - `row_annotations`: `user`, `persona`, `bucket`, `score=0.00`, `review_score`, `process_count`, `company_count`, `document_type_count`, `account_group_count`, `source_count`, `reasons`, `rule_boundary`를 저장한다.
  - `breakdown`: `scoring_unit=user`, `row_projection_policy`, `candidate_rows`, `candidate_users`, `scored_rows`, `review_scored_rows`, `scored_users`, `bucket_counts`, `user_summaries`, `zero_score_system_rows`, `zero_score_admin_rows`를 기록한다.
- **평가/리포트 표시 방식**
  - L3-12는 row-level 라벨-only precision/recall로 해석하지 않는다. v109 DataSynth부터 `work_scope_raw_candidate_population`은 raw candidate truth이고, `work_scope_excess_review_population` 및 `rule_truth_L3_12`는 사용자 단위 scored review truth다.
  - 후보 모집단 평가는 `raw_candidate`와 `work_scope_raw_candidate_population`을 비교한다. 위험 점수 평가는 `review_score_series > 0`과 `rule_truth_L3_12`를 비교한다. 두 지표를 섞어 score `0.00` 시스템/관리자 관찰 후보를 scored truth의 과탐으로 계산하면 안 된다.
  - 리포트의 1차 표시는 사용자 단위 `user_summaries`이며, 전표 행은 해당 사용자 점수의 근거 샘플 또는 결합 evidence로 drill-down한다.
  - Transaction Queue에서는 `review_rules=L3-12`로 노출하고, 확정 위반 목록인 `flagged_rules`에는 넣지 않는다.
  - v95 DataSynth 기준 L3-12 scored truth는 `labels/rule_truth_L3_12.csv`와 `labels/work_scope_excess_review_population.csv`에 `fiscal_year + created_by` 단위로 저장한다. v109부터 raw candidate truth는 `labels/work_scope_raw_candidate_population.csv`에 별도로 저장한다.
  - 전표 단위 결과는 `labels/work_scope_excess_document_projection.csv`에 drill-down projection으로만 저장한다. 이 파일은 strict precision/recall 정답으로 사용하지 않는다.
  - 리포트는 단독 L3-12 hit와 `L3-12 + L3-02/L3-10/L3-04/L4-03/L1-*` 결합 후보를 분리한다.
  - 단순 프로세스 폭은 낮은 우선순위, 수기·민감계정·고액·결산 맥락 결합은 높은 우선순위로 본다.
- **운영 예외와 보완 통제**
  - shared service, 결산 집중 기간, 소규모 조직, 백업 담당, migration/test user는 정상 사유가 가능하다.
  - 단순히 여러 업무를 했다는 이유만으로 부정 또는 통제 위반으로 결론내리지 않는다.
  - 권한 부여 사유, 승인 로그, 대체 승인자, 조직도, 사용자 직무기술서, 보완 검토 통제를 함께 확인한다.
- **구현**: `fraud_rules_access.py` → `b14_work_scope_excess_review()`, `fraud_layer.py` → registry rule id `L3-12`
- **필요 피처**: 필수 `created_by`, `business_process`; 권장 `user_persona`, `company_code`, `document_type`, `gl_account`, `source`, `is_period_end`, `exceeds_threshold`, `amount_zscore`

---

### 2.4 L4: 통계적 이상치 (6개, L4-02 Benford는 독립 트랙)

#### L4-01 — 매출 이상 변동 (RevenueManipulation) ✅

- **심각도**: 5
- **근거**: 240보론2, §32(c) 비경상거래. **FSS 최다유형**: 매출 허위계상
- **탐지 로직**: 매출 계정(4xxx) 금액이 Z-score 임계값 초과
  - `patterns.revenue_account_prefixes: ['4']` (`config/audit_rules.yaml`)
  - `zscore_threshold: 3.0` (`config/settings.py`, 회사/engagement override 가능)
- **구현**: `fraud_rules_feature.py` → `b01_revenue_manipulation()`
- **필요 피처**: `is_revenue_account`, `amount_zscore` (파생)
- **점수 bucket**

  | bucket | 조건 | L4-01 raw score | 해석 |
  |--------|------|-----------------|------|
  | `review_zscore` | `zscore_threshold < amount_zscore < 4.0` | 0.45 | 매출 고액 이상치 검토 후보 |
  | `strong_zscore` | `4.0 <= amount_zscore < 6.0` | 0.60 | 강한 매출 고액 이상치 anchor |
  | `extreme_zscore` | `amount_zscore >= 6.0` | 0.75 | 극단 매출 고액 이상치 anchor |

  - L4-01은 Boolean hit를 유지하되, `score_series`와 row annotation에 `bucket`, `amount_zscore`, `zscore_threshold`를 남긴다.
  - 모든 hit를 동일하게 1.0으로 보지 않는다. Phase 1에서는 단독 고위험 결론보다 조합 승격 근거로 사용한다.
- **실제 의미**
  - 현재 구현상 핵심은 **매출 계정 고액 이상치**다.
  - 매출 급감, 음수 조정, 환입, 취소, 후속 역분개를 직접 잡는 룰이 아니며, 그런 신호는 별도 reversal/cutoff/trend 룰에서 다룬다.
- **Phase 1 적용 방침**
  - `L4-01 단독 = 매출조작 확정`이 아니라 `금액적으로 튄 매출 라인`으로 보고, 다른 룰과의 동시 플래그 여부로 우선순위를 정한다.
  - Row-level `anomaly_score`에서는 L4 family 가중치가 낮아 L4-01 단독으로 High를 만들지 않는다.
  - Case-level에서는 `L4-01`이 cutoff, 기말, 수기, 승인통제, reversal 신호와 결합될 때 `priority_floor`로 High queue에 올린다.
- **평가/표시 정책**
  - `L4-01`은 `RevenueManipulation` 전체를 포괄하는 classifier가 아니라 **고액 매출 z-score 이상치 anchor**로 평가한다.
  - 결과 화면의 룰 메타데이터는 다음처럼 표시한다.
    - `Rule objective`: `High-value revenue z-score outlier`
    - `Broad fraud type`: `RevenueManipulation`
    - `Expected coverage`: `partial / anchor`
    - `Status`: `coverage_anchor`
  - 전체 `RevenueManipulation` 라벨 대비 precision/recall은 보조 참고값이다. 이 값만으로 `L4-01` 성공/실패를 판단하지 않는다.
  - 운영 지표는 다음 coverage 중심 지표를 같이 본다.
    - `overlap_docs`: `L4-01` 탐지 문서 중 다른 룰도 동시에 탐지한 문서 수
    - `standalone_docs`: `L4-01`만 단독 탐지한 고액 매출 검토 후보 수
    - `review_queue_docs`: broad label 기준 FP로 집계되지만 실무상 고액 정상거래/미라벨 검토 큐에 해당하는 문서 수
  - 합성데이터는 `RevenueManipulation` broad 라벨을 `L4-01`에 맞춰 억지로 좁히지 않는다.
  - `v47_candidate`부터 `metadata_json.revenue_subtype`과 `labels/revenue_manipulation_subtypes*`를 사용해 subtype을 분리한다.
  - L4-01 직접 정답은 `high_value_revenue_outlier` 및 `labels/revenue_manipulation_l401_direct_truth*`에 한정한다.
  - `v120_candidate`부터 `labels/revenue_outlier_detector_universe*`는 `labels/revenue_outlier_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `labels/revenue_outlier_boundary_controls*`와 `labels/revenue_outlier_boundary_contexts*`는 cutoff/z-score 경계 context이며, strict negative control로 해석하지 않는다.
  - 직접 정답 metadata/sidecar가 없는 후보 데이터에서는 broad `RevenueManipulation` 전체로 fallback하지 않는다. 이 경우 L4-01 direct recall은 계약 부재로 보고, raw hit는 고액 매출 검토 anchor 및 다른 룰과의 overlap으로 해석한다.
  - `cutoff_mismatch`, `reversal_return_credit`, `period_end_push`, `manual_revenue_entry`, `process_account_mismatch`, `composite_low_amount_dispersion`은 L4-01 단독 정답이 아니라 조합 평가 또는 Phase 2/3 coverage로 본다.
- **한계**
  - 정상적인 대형 계약, 신규 고객, 신규 사업, 계절성 매출 집중도 플래그될 수 있다.
  - 여러 건으로 쪼갠 가공매출은 개별 라인의 z-score가 낮으면 놓칠 수 있다.
  - 회사별 CoA에서 매출 계정 prefix가 `4`가 아니면 `revenue_account_prefixes`를 조정하지 않는 한 누락된다.
  - `amount_zscore > threshold`만 보므로 큰 양의 이상치 중심이다. 음수 조정, 환입, 취소, 매출 감소 분석은 이 룰의 직접 목표가 아니다.
  - z-score는 모집단 통계에 의존하므로 극단값이 평균/표준편차를 같이 흔들 수 있다. 표본이 작을 때는 CoA 상위그룹/전체 분포 fallback을 사용하므로 해석 강도가 낮아진다.
- **조합 시 위험도 해석**
  - L4-01은 단독으로 부정 결론을 내리기보다, 아래 조합에서 우선순위를 올리는 anchor로 쓴다.

  | 조합 | 해석 | 우선순위 | 확인 포인트 |
  |------|------|----------|-------------|
  | `L4-01 + L3-11` | 고액 매출 + cutoff 불일치 | High | 출하일/용역완료일/검수일과 매출인식일의 귀속기간 차이, 계약 조건, 기말 전후 반대분개 |
  | `L4-01 + L3-04` | 기말 고액 매출 | High | 월말/분기말/연말 집중, 다음 기간 취소·환입, 비경상 대형 계약 여부 |
  | `L4-01 + L3-02` | 수기 고액 매출 | High | 수기 입력 사유, 승인권자, supporting document, 반복 생성자/부서 |
  | `L4-01 + L1-05/L1-07/L1-09` | 승인통제 이상이 붙은 고액 매출 | Critical | 자기승인, 승인 누락, 승인일 결손, 권한 우회, 사후승인 여부 |
  | `L4-01 + L2-05` | 후속 취소/역분개 가능성 | High | 매출 인식 후 credit memo, return, reversal, 동일 고객·금액·계정의 반대분개 |
  | `L4-01 + L4-03` | 전체 금액 기준으로도 유의적인 고액 매출 | Medium~High | 감사 중요성 기준 초과 여부, 정상 대형계약/신규고객/일회성 거래 여부 |

  - 현재 Phase 1 floor:
    - `L3-11 >= 0.30 + L4-01` → `priority_score >= 0.75`
    - `L3-04 >= 0.45 + L4-01` → `priority_score >= 0.75`
    - `L3-02 >= 0.60 + L4-01` → `priority_score >= 0.75`
    - `L2-05 >= 0.45 + L4-01` → `priority_score >= 0.75`
    - `L1-09 >= 0.55 + L4-01` → `priority_score >= 0.75`
  - 보조 조합으로 `L4-01 + L3-03`은 관계사 매출, 순환거래, 밀어넣기 가능성을 후속 확인한다.
  - 동일 전표 내 여러 라인이 L4-01에 걸리면 라인별 합산보다 전표 단위 최대점수와 동시 플래그 수를 함께 보여준다.

#### L4-02 — Benford 위반 (BenfordViolation) — 독립 트랙 ✅

- **심각도**: 2
- **근거**: 520§5 기대값-차이 분석, 240-A45(e) 단수/끝자리
- **판정 기준**:

  | 지표       | 적합     | 한계적 적합   | 부적합       | 부적합(강)  |
  |------------|---------|--------------|-------------|------------|
  | MAD        | < 0.006 | 0.006~0.012  | 0.012~0.015 | > 0.015    |
  | KS p-value | > 0.05  | 0.01~0.05    | < 0.01      | —          |

  > MAD 근거: Mark Nigrini, *Benford's Law* (Wiley, 2012). 감사/포렌식 분야 사실상 표준.

- **역할**: 개별 전표 적발 룰이 아니라 **모집단/계정 단위 분포 이상 finding**.
  - Benford는 분포 검정이므로 “이 전표가 위반”을 직접 증명하지 않는다.
  - 행별 전표 목록은 조사 후보(drill-down)로만 사용한다.
  - PHASE1 transaction queue의 `priority_score`와 row-level `anomaly_score`에는 단독으로
    유입하지 않는다. 대신 PHASE1 artifact의 `metadata.macro_findings`에 Account / Process
    Queue 항목으로 저장한다.
- **탐지 로직**:
  1. `company_code + gl_account`별 금액 첫째 자리 분포를 Benford 기대분포와 비교한다.
     `company_code`가 없을 때만 `gl_account` 단독 그룹으로 fallback한다.
  2. 표본 500건 미만 그룹은 계정별 검정에서 제외한다. 100건 안팎의 작은 그룹은 Benford
     오차가 쉽게 커져 과탐 후보를 대량 생성하므로 Phase 1 finding에서 제외한다.
  3. finding 생성 기준은 MAD 중심이다. `MAD <= benford_mad_threshold(기본 0.012)`이면
     chi-square p-value가 낮아도 참고 통계로만 남기고 finding을 만들지 않는다.
  4. `0.012 < MAD <= 0.015`는 `moderate`, `MAD > 0.015`는 `strong` finding으로 본다.
  5. finding 그룹 안에서 `MAD threshold`를 초과한 첫째 자리 digit만 drill-down 후보로 선별한다.
  6. 전체 모집단 Benford 검정은 `benford_result` 요약 통계로만 저장한다. 전역 검정 결과만으로
     drill-down 후보나 행별 플래그를 만들지 않는다.
  7. 결과는 `benford_findings` metadata에 `scope`, `company_code`, `gl_account`, `sample_size`,
     `mad`, `chi2_p_value`, `finding_severity`, `flagged_digits`, `candidate_rows`,
     `candidate_documents`로 저장한다.
  8. 후보는 해당 digit 라인만 보관한다. 같은 `document_id` 전체로 전파하지 않으며,
     기본 행별 `L4-02` 점수와 `anomaly_flags` 반영은 0이다.
  9. PHASE1 case artifact 생성 시 `benford_findings`는 `metadata.macro_findings`로 투영된다.
     각 항목은 `rule_id=L4-02`, `queue_type=account_process_macro`, `company_code`,
     `gl_account`, `sample_size`, `review_score`, `finding_severity`, `candidate_rows/docs`,
     `flagged_digits`, `metrics.mad/chi2_p_value/max_deviation`을 포함한다.
- **구현**: `benford_detector.py` → `BenfordDetector(BaseDetector)`
  - 내부적으로 `anomaly_rules_statistical.py` → `c07_benford_violation()`을 호출한다.
  - 분포 수준 검정이므로 L3/L4 묶음과 별도 가중치를 부여하고, 단독으로 대량 행 플래그를 만들지 않는다.
- **필요 피처**: `debit_amount`, `credit_amount`, `first_digit` (금액에서 파생)
  - `first_digit`이 없으면 BenfordDetector는 graceful skip되어 행별 점수와 finding 후보가 0으로 남는다.
- **DataSynth 상태**: `BenfordViolation` 라벨은 성능 평가용으로 존재할 수 있으나,
  이 룰의 1차 산출물은 라벨 전표 적발이 아니라 분포 finding이다. 따라서 Phase 1 검증에서는
  `BenfordViolation` 라벨 precision/recall보다 finding 수, MAD 강도, 후보 라인 규모, 다른 룰과의
  결합 여부를 우선 본다.
- **DataSynth 평가 계약**:
  - `v52_candidate`부터 L4-02 정답은 전표 단위가 아니라 `fiscal_year + company_code + gl_account` 단위다.
  - `labels/benford_finding_truth*`는 Benford MAD 기준 이상 분포 group truth다.
  - `labels/benford_drilldown_candidates*`는 finding group 안에서 편차 digit에 속한 후보 라인이다.
  - `labels/benford_normal_groups*`는 충분한 표본이 있지만 Benford에 적합한 정상 group control이다.
  - `labels/benford_skipped_small_groups*`는 표본 수 미달로 평가 제외된 group이다.
  - 기존 `BenfordViolation` document label은 legacy 참고값이며, L4-02 precision/recall 분모로 쓰지 않는다.
  - `v54_candidate`부터는 contract truth와 별개로 Benford 강건성 평가용 sidecar를 추가한다.
  - `labels/benford_boundary_groups*`는 MAD 0.011~0.013 근처 경계 group이다.
  - `labels/benford_small_sample_controls*`는 표본 450~550건 근처의 최소 표본 경계 group이다.
  - `labels/benford_business_skew_normal_groups*`와 `labels/benford_company_specific_normals*`는 정상 업무상 digit 쏠림 또는 회사별 정상 차이를 나타낸다.
  - `labels/benford_weak_fraud_holdout*`, `labels/benford_high_mad_normal_controls*`, `labels/benford_broad_digit_findings*`는 룰 기준만으로 100% 맞히기 어려운 holdout/adversarial 평가용이다.
  - `labels/benford_adversarial_holdout*`는 위 sidecar를 합친 파일이며, strict pass/fail 정답이 아니라 실무형 robustness benchmark로만 사용한다.
  - `v120_candidate`부터 Benford sidecar도 `sidecar_role`로 구분한다. `benford_finding_truth*`는 contract truth, `benford_drilldown_candidates*`는 drilldown candidate, `benford_adversarial_holdout*`와 `benford_weak_fraud_holdout*`는 holdout, 정상/경계 group 파일은 normal 또는 boundary context다.
- **리포트 표시 정책**:
  - 일반 Rule Metrics의 `L4-02` 문서 라벨 precision/recall은 acceptance metric으로 사용하지 않는다. legacy `BenfordViolation` document label은 L4-02 직접 정답 분모에서 제외한다.
  - `PerformanceReport.benford_benchmarks`에 별도 Benford Population Benchmark를 표시한다.
  - PHASE1에서는 `build_phase1_case_queue()` 결과가 아니라
    `build_phase1_macro_finding_queue()` / `metadata.macro_findings` 결과로 표시한다.
    이 queue는 계정/모집단 검토 목록이며 transaction case High/Medium/Low 승격 근거가 아니다.
  - Benford sidecar가 없는 후보 데이터에서는 `sidecars_missing` benchmark를 표시한다. 이 상태는 L4-02 실패가 아니라 평가 계약 부재이며, row-level `L4-02` 점수 0으로 합불격을 판단하지 않는다.
  - 필수 지표는 `contract_findings`, `normal_group_controls`, `drilldown_candidate_rows/docs`다.
  - `v54` sidecar가 있으면 `adversarial_holdout`, `weak_fraud_holdout`, `boundary_groups`,
    `business_skew_normal_groups`, `company_specific_normals`, `high_mad_normal_controls`,
    `small_sample_controls`, `skipped_small_groups`를 함께 표시한다.
  - `high_mad_normal_controls` hit는 “오탐 확정”이 아니라 정상 사유 확인이 필요한 finding으로 해석한다.

  추가 검정 (Phase 2): Chi-square, Anderson-Darling

#### L4-03 — 이상 고액 (UnusuallyHighAmount) ✅

- **심각도**: 3
- **근거**: 240§33(b), 315호. FSS 결산수정: 개발비 과대자산화
- **Phase1 탐지 로직**: 양의 금액 Z-score와 전역 상위 금액 가드를 함께 적용한다.
  - `amount_zscore > zscore_threshold` (기본 3.0)
  - `max(debit_amount, credit_amount) >= P90` (기본 `l403_min_amount_quantile: 0.90`)
  - 저액 방향 이상치는 `UnusuallyHighAmount`의 목적이 아니므로 `abs(zscore)`를 사용하지 않는다.
- **구현**: `anomaly_rules_simple.py` → `c08_amount_outlier()`
- **필요 피처**: `debit_amount`, `credit_amount`, `amount_zscore` (파생)
- **결과 표현**
  - 룰 hit 자체는 기존처럼 `amount_zscore > zscore_threshold`와 전역 상위 금액 가드를 모두 만족한 행으로 유지한다.
  - row score와 annotation은 아래 band로 나눈다.

| 버킷 | 기준 | row score |
|---|---|---:|
| `low_zscore` / `review_zscore` | `zscore_threshold < amount_zscore < 5.0` + 금액 가드 통과 | 0.25 |
| `medium_zscore` / `strong_zscore` | `5.0 <= amount_zscore < 10.0` + 금액 가드 통과 | 0.45 |
| `high_zscore` / `extreme_zscore` | `amount_zscore >= 10.0` + 금액 가드 통과 | 0.70 |

- **PHASE1 통합점수 반영**
  - detector row score는 리포트와 row annotation의 설명용 점수로 보존한다.
  - 전체 row-level `anomaly_score`와 case priority에서는 bucket label을 다시 정규화한다.
  - 정규화 signal strength는 `low_zscore/review_zscore=0.45`, `medium_zscore/strong_zscore=0.70`, `high_zscore/extreme_zscore=1.0`이다.
  - `severity=3`, `evidence_strength=medium`, L4 family weight `0.15`가 적용되므로 L4-03 단독 row-level `anomaly_score` 기여는 대략 `0.0304 / 0.0473 / 0.0675`다.
  - L4-03 단독 row/case floor는 두지 않는다. 고액 이상치는 정상 대형거래와 혼재하므로 단독 High/Medium 승격 신호가 아니라, 결산·통제·계정논리·적요·배치 신호와 결합될 때 우선순위를 올리는 review anchor다.

- **Phase1 범위**:
  - 현재 detector 계약은 설명 가능성과 유지보수성을 위해 전역 분위수 가드를 사용한다.
  - 실무 튜닝에서는 계정군별 분위수 guard를 전역 guard보다 우선 적용하는 방향이 권장된다. 단, 표본이 작은 계정군은 CoA 상위그룹 또는 전역 guard로 fallback해야 한다.
  - 거래처별 기준, 대형거래 whitelist, 반복 정상거래 자동 감점, 거래처/프로세스별 baseline, 계정별 P99 프로파일링은 Phase2 이상 고도화 대상으로 둔다.
- **한계**:
  - 정상 대형 자금 이동, 정기 결제, 선수금·미지급비용 같은 큰 정상거래도 후보에 포함될 수 있다.
  - 라인 단위 금액 기준이므로 전표 전체의 경제적 실질이나 차대변 구조까지 판단하지 않는다.
  - GL 표본이 작아 `amount_zscore`가 CoA/전체 fallback으로 계산되면 계정 고유 특성이 희석될 수 있다.
- **사용 방식**:
  - L4-03 단독 플래그는 "고액 검토 후보"로 보고, 단독으로 부정 또는 실무상 유의미한 finding으로 결론내리지 않는다.
  - Phase1 case priority에서는 별도 `amount_score`가 수행중요성 또는 모집단 상대 금액을 반영하므로, L4-03 raw score를 materiality score처럼 해석하지 않는다.
  - 다음 룰과 결합될 때 Phase1 우선순위를 높인다.
- **DataSynth 평가 계약**:
  - `v109`부터 `labels/high_amount_review_population*`과 `labels/rule_truth_L4_03*`은 현재 L4-03 detector 계약에서 직접 재산출한다.
  - `v114` 후보에서 stale detector-contract scan 후 다시 재생성했고, `v116`에서 활성 truth metadata를 현재 후보 기준으로 정리했다. 현재 detector docs `4,015`, truth docs `4,015`, detector/truth diff `0`이다.
  - L4-03 rule truth는 `amount_zscore > zscore_threshold`와 전역 상위 금액 가드를 모두 만족한 문서 전체다.
  - 정상 대형거래, 자동/반복 고액거래, 우연한 고액 이상치도 룰이 올려야 하는 review anchor이면 L4-03 rule truth에 포함한다.
  - `UnusuallyHighAmount`와 `StatisticalOutlier`는 injected/confirmed anomaly subset이다.
  - `labels/high_amount_confirmed_anomalies*`는 주입 고액 이상치 recall 확인용이다.
  - `v120_candidate`부터 `labels/high_amount_detector_universe*`는 `labels/high_amount_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `labels/high_amount_normal_controls*`와 `labels/high_amount_legitimate_contexts*`는 정상 대형거래 context이며, raw L4-03 hit가 될 수 있어도 confirmed FP로 단정하지 않는다.
  - `labels/high_amount_boundary_controls*`와 `labels/high_amount_boundary_contexts*`는 z-score 임계값 근처 context이며, hard-threshold fitting 방지용이다.
  - 모든 고액 거래를 `UnusuallyHighAmount`로 라벨링하지 않는다.
- **평가 계약**:
  - L4-03은 strict fraud pass/fail 룰이 아니라 `coverage_anchor`다. `rule_truth_L4_03*`은 Phase1 후보 생성 계약이고, confirmed `UnusuallyHighAmount`/`StatisticalOutlier` 라벨은 조작/이상 주입 subset이다.
  - `score_bands`는 `high_amount_review_docs`, `low_zscore_docs/review_zscore_docs`, `medium_zscore_docs/strong_zscore_docs`, `high_zscore_docs/extreme_zscore_docs`로 나눈다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `high_amount_review_docs`를 우선 사용한다.
  - detector는 row annotation에 `bucket`, `amount_zscore`, `base_amount`, `amount_threshold`를 남긴다.

  | 결합 | 의미 | 우선순위 |
  |---|---|---|
  | `L4-03 + L3-04` | 기말/기초에 발생한 고액 조정 전표 | High |
  | `L4-03 + L1-05/L1-07` | 고액 전표의 자가승인 또는 승인 누락 | High |
  | `L4-03 + L4-04` | 고액이면서 드문 차변-대변 계정 조합 | High |
  | `L4-03 + L3-08` | 고액인데 적요가 비어 있거나 깨져 있음 | Medium |
  | `L4-03 + L4-01` | 매출 계정 특화 이상치이면서 전체 금액 기준으로도 고액 | High |

#### L4-04 — 희소 차대 계정쌍 (RareDebitCreditAccountPair) ✅

- **심각도**: 2
- **근거**: 240-A45(a) 비경상·저사용 계정, 315호
- **Phase 1 해석**: 비정상 확정 룰이 아니라, 해당 회사/기간 모집단에서 드물게 나타난 차변-대변 계정쌍을 검토 후보로 올리는 설명 가능한 약한 신호다.
- **탐지 로직**: 차변-대변 GL 계정쌍 빈도 하위 1%
  - Merge 기반 벡터화된 Cartesian product
  - 복합분개는 같은 전표의 모든 차변 행 × 모든 대변 행 조합을 생성
  - `gl_account`가 비어 있는 차변/대변 라인은 L4-04 계정쌍 계산에서 제외한다. 계정 누락은 L4-04가 아니라 `L1-02`/`L1-03` 계열 데이터 품질·계정 유효성 이슈로 평가한다.
  - 희소쌍이 하나라도 포함된 전표는 전표 전체 라인을 플래그
  - 100라인 초과 대형 전표는 제외하지 않는다. 일반 전표에서 계산한 희소쌍 기준선을 유지하고, 대형 전표만 `document_id + gl_account` 고유 차변/대변 계정쌍으로 압축해 대입 평가한다.
  - 대형 전표의 신규 계정쌍은 기준 모집단에 없던 조합으로 보아 review 후보로 올린다. 이는 메모리 폭발을 막으면서 coverage 제외를 만들지 않기 위한 운영 정책이다.
- **구현**: `anomaly_rules_statistical.py` → `c09_rare_account_pair()`
- **필요 피처**: `document_id`, `gl_account`, `debit_amount`, `credit_amount`
- **튜닝 파라미터**: `account_pair_rare_percentile` 기본 `0.01`
- **결과 표현**
  - 룰 hit 자체는 기존처럼 희소쌍이 하나라도 포함된 전표 전체 라인으로 유지한다.
  - detector row score는 희소쌍 강도별로 차등화한다: 단일 희소쌍 `0.25`, 대형 전표 압축 평가에서 신규 조합으로 걸린 경우 `0.35`, 복수 희소쌍 `0.45`.
  - annotation에 `reason_codes`, `score_bucket`, `rare_pair_count`, `sample_pairs`, `threshold_count`를 남긴다.
  - 대형 전표 압축 평가에서 기준 모집단에 없던 조합으로 걸린 경우 `large_doc_distinct_pair` reason을 함께 남긴다.
- **PHASE1 점수 유입**
  - L4-04는 `logic_mismatch`, `evidence_strength=medium`, `scoring_role=primary`로 정규화된다.
  - detector row score는 PHASE1에서 단조 보존된다. 기본 normalized contribution은 `row_score * 0.75`이며, 따라서 `single_rare_pair 0.25 -> 0.1875`, `large_doc_distinct_pair 0.35 -> 0.2625`, `multiple_rare_pairs 0.45 -> 0.3375`이다.
  - row-level `anomaly_score`에는 L4 family weight `0.15`가 다시 적용되므로 단독 기여도는 각각 약 `0.028`, `0.039`, `0.051`에 그친다. 희소 계정쌍만으로 Medium/High를 만들지 않는 의도다.
- **실무 사용 방식**
  - 단독으로 fraud 또는 회계처리 오류를 결론내리지 않는다.
  - `L3-04` 기말/기초, `L3-02` 수기전표, `L4-03` 고액, `L3-08` 적요 결손/파손, 승인/권한 룰과 겹칠 때 우선순위를 높인다.
  - `L4-04` 단독 케이스는 case priority에서 낮춘다. 특히 `recurring`, `automated`, `batch`, `interface`, `system` source가 대부분인 케이스는 정상 long-tail 조합 가능성이 높으므로 추가로 downgrade한다.
  - 회사·업종·ERP별 계정체계가 다르므로 Phase 1에서 범용 whitelist/blacklist 조합을 직접 유지하지 않는다.
- **Case priority 조정**
  - raw L4-04 hit는 그대로 유지한다. 탐지 coverage를 줄이지 않기 위해 희소쌍 후보 자체를 필터링하지 않는다.
  - `L4-04` 외 보강 룰이 없는 케이스는 `l404_only_penalty`를 적용한다.
  - 반복/자동 source 비중이 `recurring_source_ratio` 이상이면 `recurring_source_penalty`를 추가 적용한다.
  - 설정 위치: `config/phase1_case.yaml` → `priority_adjustments.rare_account_pair`
- **한계**
  - 도메인상 이상하지만 반복적으로 자주 등장한 조합은 희소하지 않으므로 놓칠 수 있다.
  - 정상적인 일회성 조정, 재분류, 연결조정, 시스템 전환 전표도 희소하다는 이유로 플래그될 수 있다.
  - 의미 기반 조합 이상은 Phase 2의 VAE/GNN/관계형 모델에서 보완한다.
- **DataSynth 평가 계약**
  - `UnusualAccountPair`는 confirmed anomaly subset이다.
  - confirmed `UnusualAccountPair` 라벨에는 null-side pair(`->2100`, `500060->` 등)를 넣지 않는다. 이런 문서는 `MissingField`/계정 누락 라벨로만 평가한다.
  - confirmed 라벨은 현재 L4-04 계산 기준에서 non-null 차변 GL과 non-null 대변 GL로 구성된 희소쌍을 최소 1개 포함해야 한다.
  - `v49_candidate`부터 `labels/rare_account_pair_review_population*`을 L4-04 review coverage로 사용한다.
  - `v110_candidate`부터 `labels/rule_truth_L4_04*`와 `labels/rare_account_pair_review_population*`은 현재 L4-04 detector output에서 직접 재산출한 동일한 raw review universe다.
  - `v120_candidate`부터 `labels/rare_account_pair_detector_universe*`는 `labels/rare_account_pair_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `labels/rare_account_pair_confirmed_anomalies*`는 희소 계정쌍 중 보강 정황이 있는 일부만 담는다.
  - `labels/rare_account_pair_normal_controls*`와 `labels/rare_account_pair_legitimate_contexts*`는 정상 희소 계정쌍 context이며, raw L4-04 hit가 될 수 있어도 confirmed FP로 단정하지 않는다.
  - v120 기준 `rare_account_pair_legitimate_contexts`는 258문서 중 256문서가 L4-04 detector universe와 겹친다. 이는 정상 long-tail 계정쌍도 Phase 1 review 후보가 될 수 있다는 뜻이지, detector 오탐 확정이 아니다.
  - confirmed subset이나 normal control이 현재 detector universe 밖에 있으면 raw rule truth의 과탐/미탐으로 해석하지 말고 해당 subset sidecar의 stale 여부를 별도로 점검한다.
  - `v49_candidate` 분석에서 확인된 L4-04 미탐 12건은 모두 null 계정쌍이 섞인 라벨 계약 문제였으므로 DataSynth 라벨 생성 단계에서 제외해야 한다.
  - 100라인 초과 전표도 detector 평가 대상이다. 과거 `labels/rare_account_pair_excluded_large_docs*`는 legacy 진단 산출물로만 취급하고, pass/fail 분모에서 detector 제외 계약으로 사용하지 않는다.
  - 모든 희소 계정쌍을 `UnusualAccountPair`로 라벨링하지 않는다.
- **평가 계약**:
  - L4-04는 strict pass/fail 룰이 아니라 `coverage_anchor`다. confirmed `UnusualAccountPair` 라벨은 direct subset이고, raw hit는 희소 계정쌍 검토 모집단이다.
  - `score_bands`는 `rare_pair_review_docs`, `ordinary_rare_pair_docs`, `large_doc_distinct_pair_docs`로 나눈다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `rare_pair_review_docs`를 우선 사용한다.
  - null-side 계정쌍은 L4-04 평가에서 제외하고 계정 누락/무결성 문제로 분리한다.

#### L4-05 — 비정상 시간대 집중 (AbnormalHoursConcentration) ✅

- **심각도**: 3
- **운영 성격**: 확정 부정 판정이 아니라 Phase 1 후보 선별 룰이다. 특정 사용자의 감시 취약 시간대 입력 습관, 심야 다건 입력, 심야 급속 승인을 넓게 올린 뒤 금액·계정·승인·기말 신호와 함께 triage한다.
- **근거**: KLCA IT 체크리스트 — 특정 사용자가 감시 취약 시간대에 반복 입력하는 패턴은 단건 심야/주말 플래그보다 강한 행동 징후다.
- **탐지 로직**: 사용자별 비정상 시간대 입력 비율 이상치 + 실사용자 심야 다건 + 급속 승인 신호
  1. `time_zone_category in {"midnight", "overtime"}` 또는 주말/공휴일을 비정상 시간대로 본다.
  2. 자동/시스템 계정(`auto_entry_sources`, `automated_system`, `SYSTEM`, `IC_GENERATOR`)은 사용자 행동 통계, 소표본 심야 보완, 급속 승인 보조 신호에서 제외한다. 비교는 대소문자와 공백 차이를 정규화한다.
  3. `created_by`별 비정상 시간대 비율을 계산하고, 평균 대비 `abnormal_sigma_threshold` 이상인 사용자를 찾는다. 기본값은 Phase 1 후보 탐지 목적에 맞춰 `2.5σ`로 둔다.
  4. 절대 비율이 `min_abnormal_ratio` 미만이면 제외한다.
  5. sigma 이상치가 아니어도 실사용자의 심야 입력이 `min_high_context_midnight_entries` 이상이면 해당 사용자의 `midnight` 전표만 후보로 올린다. 기본값은 `100`건이다. 이 보완은 실제로 발생 가능한 심야 다건 사용자 케이스를 잡기 위한 것이며 `overtime`에는 적용하지 않는다.
  6. 사용자 수가 적으면 sigma 대신 `min_midnight_entries`와 비율 기준으로 fallback하고, 최소 사용자 전표 수 미만이어도 심야 입력이 충분히 반복되면 해당 심야 전표만 후보로 올린다.
  7. 수기 전표가 비정상 시간대에 입력되고 `rapid_approval_minutes` 이내 승인되면 별도 플래그한다. 미탐을 줄이기 위해 금액 하한은 두지 않으며, 자동 전표 source와 `automated_system`은 과탐 방지를 위해 제외한다.
- **구현**: `anomaly_rules_simple.py` → `c12_abnormal_hours_concentration()`
- **필요 피처**: `created_by`, `posting_date`, `time_zone_category`, `is_weekend`, `is_holiday`, `approval_date`, `approved_by`, `is_manual_je` 또는 `source`
- **L3-05/L3-06과의 관계**: L3-05는 주말/공휴일 단건, L3-06은 감사인이 설정한 심야 구간 단건만 잡는다. L4-05는 사용자의 overtime·심야·비근무일 입력이 한 사람에게 집중되는지를 보는 상위 패턴 룰이다.
- **튜닝 파라미터**: `abnormal_sigma_threshold`, `rapid_approval_minutes`, `min_abnormal_ratio`, `min_midnight_entries`, `min_user_entries`, `min_high_context_midnight_entries`, `auto_entry_sources`
- **기본값**: `abnormal_sigma_threshold=2.5`, `rapid_approval_minutes=5`, `min_abnormal_ratio=0.1`, `min_midnight_entries=3`, `min_user_entries=10`, `min_high_context_midnight_entries=100`.
- **해석 주의**: `min_high_context_midnight_entries` 보완은 recall을 높이는 대신 후보 수를 크게 늘릴 수 있다. 따라서 L4-05 단독 hit는 사용자 질의·업무 배경 확인 대상으로 보고, 고액·민감 계정·기말·승인통제·수기전표 신호와 겹칠 때 우선순위를 높인다.
- **PHASE1 점수 유입 원칙**: L4-05의 내부 band 점수는 확정 부정 확률이 아니라 Phase1 `timing_anomaly` 신호 강도다. `system_context_review(0.25) < sigma_outlier(0.45) < low_volume_midnight(0.50) < high_context_midnight(0.55) < rapid_approval(0.65)` 순서가 `rule_scoring.py`의 `normalized_score`까지 보존되도록 raw band를 직접 signal strength로 사용한다. 다만 evidence strength는 `weak`, timing weight는 0.15이므로 L4-05 단독으로 High/Medium case를 만들기보다 L1 승인통제, L3 기말·cutoff, L4 고액·희소 계정쌍, 수기전표 신호와 결합될 때 triage 우선순위를 올린다.
- **DataSynth 계약**: `v53_candidate` 기준 `AbnormalHoursConcentration`은 확정 라벨 subset으로 관리한다. 자동/반복 source와 `automated_system`은 라벨 주입 대상에서 제외하며, `normal_after_hours_context`와 중복되지 않아야 한다.
- **평가 계약**:
  - L4-05는 strict pass/fail 룰이 아니라 `coverage_anchor`다. 확정 `AbnormalHoursConcentration` 라벨은 direct subset이고, raw hit는 사용자 행동 검토 큐다.
  - `v111_candidate`부터 DataSynth strict L4-05 rule truth는 2022~2024를 통합한 사용자 행동 통계 컨텍스트에서 detector를 1회 실행한 뒤 `fiscal_year`로 나눈 결과다. 연도별 단독 실행은 사용자별 abnormal ratio, midnight count, sigma 기준이 달라지므로 robustness check로만 사용하고 strict FP/FN 평가에는 쓰지 않는다.
  - `labels/rule_truth_L4_05*`와 `labels/abnormal_hours_behavior_review_population*`은 동일한 raw behavior review universe다. `labels/abnormal_hours_concentration_cases*`는 confirmed anomaly subset이다.
  - `v120_candidate`부터 `labels/abnormal_hours_behavior_detector_universe*`는 `labels/abnormal_hours_behavior_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `score_bands`는 `behavior_review_docs`, `sigma_outlier_docs`, `low_volume_midnight_docs`, `high_context_midnight_docs`, `rapid_approval_docs`로 나눈다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `behavior_review_docs`를 우선 사용한다.
  - detector는 row annotation에 `reason_codes`와 `primary_reason`을 남긴다. 동일 행이 사용자 집중과 급속 승인에 동시에 걸릴 수 있으므로 하위 band 합계는 전체 review 문서 수와 일치하지 않을 수 있다.

#### L4-06 — 배치성 자동 전표 검토 신호 (BatchAnomaly) ✅

- **심각도**: 2
- **운영 성격**: 단독 고위험 적발 룰이 아니라 Phase 1 보조 검토 신호다. 과거 Phase 2 WU-09로 설계되었으나, 최신 PHASE1 관계도에서는 `statistical_outlier` evidence와 `batch_combo_bonus` 입력으로 운영한다.
- **근거**: 배치·인터페이스·시스템 전표는 정상 대량 처리도 많으므로, 단독 hit만으로 부정 가능성을 강하게 주장하지 않는다. 다만 개별 승인/검토가 약할 수 있어 기말·대량·금액 특이 패턴은 검토 후보로 남긴다.
- **배치성 source 기본값**: `batch`, `interface`, `system`, `auto`, `automated`, `if`, `sys` 계열. 비교는 대소문자 무시.
- **탐지 로직**: 3가지 하위 패턴 OR 결합
  1. 기말 집중: 배치성 전표 중 기말 비율 > `batch_period_end_ratio` (기본 0.5)
  2. 대량 동시 생성: 동일 `posting_date` 배치성 전표의 `document_id` distinct count ≥ `batch_simultaneous_threshold` (기본 50). `document_id`가 없을 때만 row count로 fallback한다.
  3. 금액 이상: 배치성 전표 내 `abs(Z-score) > batch_amount_zscore` (기본 3.0), std=0 방어 포함. 배치 평균보다 큰 금액뿐 아니라 비정상적으로 작은 금액도 검토 후보에 포함한다.
- **위험도가 높아지는 결합 신호**

  | 결합 | 의미 | 운영 우선순위 |
  |------|------|---------------|
  | `L4-06 + L3-04/L3-07/L1-08` | 자동 배치성 전표가 결산·cutoff·전기일 괴리와 결합 | Medium 이상 |
  | `L4-06 + L1-05/L1-06/L1-07` | 자동 처리와 승인/권한 통제 실패가 결합 | Medium 이상 |
  | `L4-06 + L4-03/L4-04/L3-10` | 배치성 전표가 고액·희소 계정쌍·민감 계정과 결합 | Medium 이상 |
  | `L4-06 + L3-08` | 자동 전표인데 적요가 비어 있거나 깨져 있음 | 보조 가점 |
  | `L4-06 + L2-05/L2-02` | 배치성 처리 후 역분개·중복 징후 동반 | High 후보 |

- **PHASE1 점수 흐름**: L4-06 detector raw score는 `0.25/0.45/0.65` band로 남기되, 공통 정규화에서는 `evidence_strength=weak`, `scoring_role=combo_only`, L4 family weight `0.15`가 적용된다. 따라서 L4-06 단독 hit는 row-level `anomaly_score`와 `risk_level`을 의미 있게 끌어올리지 않는다.
- **코드 반영**: `score_aggregator.py`는 L4-06 결합 신호를 `batch_combo_score`로 계산하며, L4-06 단독은 승격하지 않는다. `phase1_case_builder.py`는 같은 원칙으로 `batch_combo_bonus`와 behavior floor를 case priority에만 반영한다.
- **구현**: `anomaly_rules_batch.py` → `c13_batch_anomaly()`
- **필요 피처**: `source`, `is_period_end`, `posting_date`, `debit_amount`, `credit_amount`
- **동일 일자 처리**: 대량 동시 생성 조건은 `posting_date`를 달력일 단위로 정규화한 뒤 집계한다. 시간이 포함된 timestamp라도 같은 날짜면 같은 배치 모집단으로 묶고, 날짜 파싱이 불가능한 값은 앞 10자 문자열로 graceful fallback한다.
- **DataSynth 상태**: DataSynth v114 후보에서 `rule_truth_L4_06.csv`와 `batch_review_population.csv`를 현재 detector raw batch review universe로 맞췄고, v116에서 활성 truth metadata를 현재 후보 기준으로 정리했다. 현재 detector docs `686`, truth docs `686`, detector/truth diff `0`이다. confirmed `BatchAnomaly` 라벨은 이 안에서 뽑은 subset이며, `batch_normal_controls.csv`와 `batch_boundary_controls.csv`는 strict rule truth에 섞지 않는다. `recurring`은 L4-06 batch source가 아니며, 실제 배치성 이상이면 원장 `source`가 `batch`/`interface`/`automated` 계열로 분류되어야 한다.
  - `v120_candidate`부터 `labels/batch_detector_universe*`는 `labels/batch_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `labels/batch_normal_controls*`와 `labels/batch_legitimate_contexts*`는 정상 batch context다.
  - `labels/batch_boundary_controls*`와 `labels/batch_boundary_contexts*`는 경계 batch context다. v120 기준 `batch_boundary_contexts`는 128문서 중 30문서가 L4-06 detector universe와 겹치므로 strict negative control로 해석하지 않는다.
- **평가 계약**:
  - L4-06은 strict pass/fail 룰이 아니라 `coverage_anchor` 보조 증거다. DataSynth strict Phase 1 truth는 confirmed label만이 아니라 raw batch review universe다.
  - `score_bands`는 `batch_review_docs`, `period_end_concentration_docs`, `simultaneous_creation_docs`, `amount_outlier_docs`로 나눈다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `batch_review_docs`를 우선 사용한다.
  - `BatchAnomaly` 라벨은 감사 이슈 subset이다. `rule_truth_L4_06`과 1:1로 같다고 가정하면 안 된다.
  - detector는 row annotation에 `reason_codes`와 `primary_reason`을 남긴다. 동일 행이 기말 집중, 동시 생성, 금액 이상에 동시에 걸릴 수 있으므로 하위 band 합계는 전체 batch review 문서 수와 일치하지 않을 수 있다.
  - L4-06 단독 hit는 정상 자동/배치 처리일 수 있으므로 case priority는 `batch_combo_score`와 독립 보강 룰 그룹 수로 판단한다.
  - PHASE1 사용자 큐는 row-level `anomaly_score`만으로 정렬하면 안 된다. L4-06처럼 단독 점수는 낮지만 결합 근거가 중요한 신호가 묻히지 않도록 `priority_score`, `priority_band`, `batch_combo_bonus`, `priority_adjustment_reasons`를 함께 사용한다.

---

### 2.5 Variance 독립 트랙: 전기 대비 변동 (2개, 기존회사 전용)

`enable_variance_detection=True`로 켠 기존회사에서만 실행한다.
신규회사(anonymous), `fiscal_year` 없음, repository 미주입, 전기 engagement 미존재, 전기 summary 로드 실패 시 자동 스킵한다.
즉, 전기(fiscal_year - 1) engagement 데이터는 필요조건이지만 충분조건은 아니며, 기본 설정은 비활성화(`False`)다.

D01/D02는 PHASE1 Transaction Queue의 row/document-level 탐지 룰이 아니라 `Analytical Review Signals`
독립 섹션으로 리포팅한다. 즉, 단일 전표 precision·FP·FN 분모에 포함하지 않고
`fiscal_year + company_code + gl_account` 계정 group 단위의 review population coverage로 평가한다.
정상 사업 변화, 계절성, 배치성 처리, 계정체계 변경도 같은 신호를 만들 수 있으므로,
D01/D02 단독 hit는 부정 또는 오류 결론이 아니라 계정 검토 큐로 본다. L1~L4 row/document-level 룰과
겹치는 전표는 drill-down 및 case priority 보강 근거로만 사용한다.

PHASE1 정책상 D01/D02는 recall 우선으로 넓게 포착한다. 정상 사업 변화나 반복 배치 패턴이 함께
올라오는 것은 detector threshold를 높여 제거할 대상이 아니라, Account / Process Queue의
`macro_priority_score`, `queue_bucket`, `normal_likelihood`로 분리할 대상이다. 따라서
`review_score`는 원 raw 측정치(`weighted_variance`, `jsd`)로 보존하고, 사용자 큐 정렬은 보정된
`macro_priority_score`를 우선 사용한다. D01/D02는 여전히 row-level `anomaly_score`에는 0으로 남긴다.

PHASE1 전체 case 결과로 흘러갈 때도 같은 원칙을 유지한다. D01/D02는 같은
`fiscal_year + company_code + gl_account`에 속한 Transaction Queue case에 `macro_contexts`로만 붙는다.
`confirmed_*` bucket은 case priority에 작은 보강값을 줄 수 있고, `corroborated_*` bucket은 더 약한 보강값만
줄 수 있다. `normal_*`, `auxiliary_non_*`, `analytical_review` bucket은 설명 context로만 표시하며
priority 보너스를 주지 않는다. 이 설계는 정상 사업 변화가 큰 계정을 row-level 고위험으로 오해하지 않으면서,
기말·고액·승인통제 등 L1~L4 신호가 같은 계정에서 발생할 때는 분석적 절차 맥락을 잃지 않기 위한 것이다.

| Rule ID | 룰 이름                    | Severity | 감사기준서                    | 구현 파일                                |
|---------|----------------------------|:--------:|-------------------------------|------------------------------------------|
| D01     | 계정과목 거래 활동량 급변 | 4        | ISA 520 §5, PCAOB AS 2305    | `src/detection/variance_rules.py`        |
| D02     | 월별 분포 패턴 변화        | 3        | ISA 520 §5                    | `src/detection/variance_rules.py`        |

#### D01 — 계정과목 거래 활동량 급변 (AccountActivityVariance)✅

- **입력**: 당기 DataFrame + `PriorSummary.account_aggregates`
- **성격**: Phase 1 분석적 검토용 스크리닝 룰. 단독 부정 판정이 아니라 계정 레벨 attention signal로 사용한다.
- **판정 로직**:
  - 당기/전기 `gl_account`별 거래 활동량 집계 비교 (`debit_amount + credit_amount` 기준 total_amount, count, avg_amount)
  - 가중평균 변동률 = `total_var × 0.5 + count_var × 0.3 + avg_var × 0.2`
  - 임계값: `variance_threshold` (기본 0.5 = 50%) 초과 시 해당 계정을 review population으로 기록
  - 신규 계정(전기 미존재): review population으로 기록 (변동률 = 1.0)
  - `company_code`가 있으면 `company_code::gl_account` prior를 우선 조회하고, 없으면 `gl_account` prior로 fallback한다.
- **잡아내는 신호**: 전기 대비 계정의 총 거래 활동량, 전표 건수, 평균 전표 금액이 급변한 경우. 신규 계정 등장도 포함한다.
- **출력 정책**: D01은 row-level anomaly score를 만들지 않는다. `details["D01"] = 0.0`으로 유지하고, `metadata.account_activity_variance`에 계정 단위 근거를 저장한다.
  - `RuleFlag.flagged_count`는 D01 review account에 속한 당기 행 수로 표시될 수 있지만, 최종 `DetectionResult.flagged_count`는 row score가 0이므로 증가하지 않는다.
- **운영 해석**: D01 단독은 `계정 검토 큐` 수준으로 보고, 고액 이상치·희귀 계정쌍·결산 전표·권한/승인 룰 등과 결합될 때 case priority와 drill-down 설명을 보강한다.
- **Account Queue 점수화**:
  - `review_score`: raw `weighted_variance`를 보존한다. 이 값은 활동량 변동의 크기이며 부정 가능성 점수가 아니다.
  - `macro_priority_score`: `evaluation_bucket`, `precision_policy`, `d01_target_document_count`, `business_event_type`을 반영한 Account Queue 정렬 점수다.
  - `queue_bucket=confirmed_account_shift`: DataSynth truth 또는 D01 target 문서로 보강된 계정. 기본 High review 후보로 정렬한다.
  - `queue_bucket=corroborated_account_shift`: runtime에서 target 문서 수 등 보강 근거가 있으나 truth sidecar 수준의 확정 metadata는 없는 계정.
  - `queue_bucket=normal_business_review`: 가격 상승, 물량 증가, capex/운전자본, 고거래량 운영, recurring/system volume shift 등 정상 사업 이벤트. raw 변동률이 커도 priority cap을 낮게 둔다.
  - `queue_bucket=auxiliary_non_d01_context`: 문서-level anomaly 문맥은 있으나 D01 계정 활동 변동 truth가 아닌 보조 문맥.
  - `queue_bucket=analytical_review`: 증거가 부족한 일반 분석 검토 큐. FP가 아니라 후속 설명/자료 확인 대상이다.
- **PHASE1 case 반영**:
  - 같은 `fiscal_year + company_code + gl_account`의 Transaction Queue case에는 D01 finding을 `macro_contexts`로 첨부한다.
  - `confirmed_account_shift`는 `macro_context=D01:confirmed_account_shift+0.06` 보강 사유를 남기고 case priority에 소폭 가산할 수 있다.
  - `corroborated_account_shift`는 더 약한 보강만 허용한다.
  - `normal_business_review`, `auxiliary_non_d01_context`, `analytical_review`는 case 설명과 evidence tag에만 남기며 priority 보너스를 주지 않는다.
- **한계**: 이 룰은 기말 잔액 변동 탐지가 아니라 총 거래 활동량 변동 탐지다. 전기에는 있었지만 당기에 사라진 계정은 당기 행이 없어 직접 플래그하지 못한다.
- **결측 계정 처리**: `gl_account`가 비어 있거나 `nan/null`류 토큰이면 D01 집계에서 제외한다. 계정 결측은 무결성 룰에서 다룬다.
- **DataSynth 평가 계약**:
  - 운영 DataSynth `v58` 기준 D01 정답은 전표 단위가 아니라 `fiscal_year + company_code + gl_account` 단위다.
  - 구현도 `company_code`가 있는 원장에서는 `company_code + gl_account` 단위로 전기 대비 활동량을 비교한다. `company_code`가 없는 단일 회사 원장은 기존처럼 `gl_account` 단위로 비교한다.
  - `labels/account_activity_variance_truth*`는 D01 true-positive 계정 group이다.
  - `labels/account_activity_variance_normal_controls*`는 D01 raw flag가 가능하지만 정상 사업 변화, 고거래량 계정 변동, 비-D01 문서 이상 등으로 해석해야 하는 normal control이다.
  - `labels/account_activity_variance_review_population*`은 D01이 검토 대상으로 올릴 수 있는 전체 계정 group 모집단이다.
  - `v121_candidate`부터 `labels/account_activity_variance_stable_controls*`는 활동량 변동이 낮은 안정 계정 group guardrail이고, `labels/account_activity_variance_near_threshold_controls*`는 D01 임계값 바로 아래의 경계 group이다.
  - `v121_candidate`부터 `labels/account_activity_variance_exclusions*`는 blank/null GL 등 입력 품질상 D01 계정 group 평가에서 제외할 row-level context다.
  - `expected_d01_flag`는 계정 활동량 기준 raw D01 flag 여부이고, `is_true_positive_account`는 D01 truth 여부다. 두 값을 분리해서 precision 해석을 왜곡하지 않는다.
  - 운영 DataSynth `v58` 기준 D01 sidecar에 `business_event_type`, `evaluation_bucket`, `precision_policy`를 포함한다. `v121_candidate`부터는 `expected_macro_priority_band`, `macro_truth_role`, `sidecar_role`도 포함한다.
  - `evaluation_bucket=confirmed_truth`는 D01 정답, `normal_business_control`은 정상 사업 이벤트, `review_queue`는 FP가 아니라 분석적 검토 큐, `auxiliary_non_d01_context`는 D01 precision 분모에서 분리할 보조 문맥이다.
  - 정상 사업 이벤트는 `price_increase`, `volume_growth`, `capex_investment_event`, `working_capital_timing`, `entity_process_expansion`, `high_volume_operations`, `recurring_or_system_volume_shift` 등으로 표준화한다.
  - `account_activity_variance_normal_controls*`는 detector negative set이 아니다. 전부 `expected_d01_flag=True`인 raw-positive normal/review context이며, confirmed D01 truth에서만 제외한다.
  - 2023은 2022와 비교하고, 2024는 2023과 비교한다. 2022는 전기 2021 baseline이 없으므로 기본 D01 평가 대상에서 제외한다.

#### D02 — 월별 분포 패턴 변화 (MonthlyPatternVariance)✅

- **입력**: 당기 DataFrame + `PriorSummary.monthly_patterns`
- **판정 로직**:
  - Jensen-Shannon Divergence(JSD)로 전기/당기 월별 금액 분포 비교
  - 평가 단위: 기본 `d02_group_keys=["company_code", "gl_account"]`. `company_code`가 있으면 회사별 계정 group을 비교하고, 없으면 기존처럼 `gl_account` 단위로 fallback한다.
  - 임계값: `monthly_pattern_threshold` (기본 0.3) 초과 시 해당 회사/계정 group의 모든 행을 review signal로 표시
  - 전기/당기 모두 `min_monthly_data_months`개월 이상 데이터 존재해야 비교 수행, 미만이면 스킵
  - 당기 계정 문서 수가 `d02_min_account_docs` 미만이면 스킵한다. `document_id`가 있으면 distinct document 수, 없으면 행 수를 사용한다.
  - 당기 계정 활동금액이 `d02_min_annual_amount` 미만이면 스킵
  - 전기/당기 최대월 비중 차이가 `d02_min_top_month_delta` 미만이면 스킵
  - 전기 또는 당기 월별 금액 합계가 0이면 분포를 계산할 수 없으므로 스킵한다.
- **출력 정책**:
  - D02는 단독 부정 결론이 아니라 account-level review signal이다.
  - D02는 row-level anomaly score를 만들지 않는다. `details["D02"] = 0.0`으로 유지하고, 계정 group 근거는 `metadata.d02_account_diagnostics`에 저장한다.
  - `RuleFlag.flagged_count`는 D02 review group에 속한 당기 행 수로 표시될 수 있지만, 최종 `DetectionResult.flagged_count`는 row score가 0이므로 증가하지 않는다.
  - group별 `d02_group_key`, `company_code`, `gl_account`, `jsd`, 비교 월수, 당기 문서 수, 당기 활동금액, 전기/당기 최대월과 비중 차이는 `d02_account_diagnostics` metadata에 보관한다.
- **Account Queue 점수화**:
  - `review_score`: raw `jsd`를 보존한다. 이 값은 월별 분포 차이의 크기이며 부정 가능성 점수가 아니다.
  - `macro_priority_score`: `scenario_type`, `d02_target_document_count`, `normal_context_document_count`, `sources`, `top_month_delta`를 반영한 Account Queue 정렬 점수다.
  - `queue_bucket=confirmed_monthly_shift`: target anomaly 월별 집중 또는 기말 수익/비용 집중 truth. 기본 High review 후보로 정렬한다.
  - `queue_bucket=corroborated_monthly_shift`: target 문서가 있으나 confirmed scenario metadata가 부족한 계정.
  - `queue_bucket=normal_pattern_review`: 정상 계절성, project/bonus timing, recurring/automated/interface/batch/system 패턴. raw JSD가 커도 priority cap을 낮게 둔다.
  - `queue_bucket=auxiliary_non_d02_context`: 문서-level 문맥은 있으나 D02 월별 패턴 truth가 아닌 보조 문맥.
  - `queue_bucket=analytical_review`: 증거가 부족한 일반 월별 패턴 검토 큐다.
- **PHASE1 case 반영**:
  - 같은 `fiscal_year + company_code + gl_account`의 Transaction Queue case에는 D02 finding을 `macro_contexts`로 첨부한다.
  - `confirmed_monthly_shift`는 `macro_context=D02:confirmed_monthly_shift+0.06` 보강 사유를 남기고 case priority에 소폭 가산할 수 있다.
  - `corroborated_monthly_shift`는 더 약한 보강만 허용한다.
  - `normal_pattern_review`, `auxiliary_non_d02_context`, `analytical_review`는 case 설명과 evidence tag에만 남기며 priority 보너스를 주지 않는다.
- **잡아내는 신호**: 전기에는 고르게 발생하던 계정이 당기에는 결산월, 특정 분기, 특정 프로젝트 월에 몰리는 경우.
- **위험도가 높아지는 결합 신호**

  | 결합 | 실무 해석 | 운영 우선순위 |
  |------|-----------|---------------|
  | `D02 + L3-04/L3-07/L1-08` | 월별 집중 변화가 기말 전표, 전기일 괴리, 회계기간 불일치와 결합 | High 후보 |
  | `D02 + L4-03/L4-04` | 패턴 변화 월에 고액 또는 희귀 계정 조합이 동반 | Medium 이상 |
  | `D02 + L3-08` | 패턴 변화 계정의 적요가 비어 있거나 깨져 있음 | 보조 가점 |
  | `D02 + L2-05` | 특정 월 집중 후 역분개·대체·정리 패턴이 동반 | High 후보 |
  | `D02 + D01` | 월별 배치뿐 아니라 계정 활동량 자체도 급변 | Medium 이상 |

- **한계**
  - 계정 단위 분석 신호이므로 특정 전표 1건을 확정 부정으로 지목하지 않는다.
  - 계절성, 사업 개편, 신규 프로젝트, ERP/계정체계 변경, 정상 결산 정책 변경도 동일한 신호를 만들 수 있다.
  - 전기 데이터 품질이 낮거나 `fiscal_period`가 누락/오류이면 비교 결과의 신뢰도가 낮다.
  - 신규 계정은 D02에서 스킵된다. 신규 계정 검토는 D01이 담당한다.
- **DataSynth 평가 계약**:
  - 운영 DataSynth `v58` 기준 D02 정답은 전표 단위가 아니라 `fiscal_year + company_code + gl_account` 단위다.
  - 구현도 `company_code`가 있는 원장에서는 `company_code::gl_account` prior pattern을 우선 사용한다. 전기 summary가 legacy `gl_account` key만 제공하면 호환을 위해 계정 key로 fallback한다.
  - `labels/monthly_pattern_shift_confirmed_anomalies*`는 D02 true-positive 계정 group이다.
  - `v121_candidate`부터 `labels/monthly_pattern_shift_truth*`는 confirmed D02 macro truth의 명시적 alias다.
  - `labels/monthly_pattern_shift_review_population*`은 D02가 raw review 대상으로 올릴 수 있는 전체 계정 group이다.
  - `labels/monthly_pattern_shift_normal_controls*`는 정상 계절성, 프로젝트성 비용, 반복/인터페이스 배치, 안정적 월별 profile control이다.
  - `v121_candidate`부터 `labels/monthly_pattern_shift_raw_positive_normal_contexts*`는 D02가 잡아야 하는 raw-positive 정상 맥락이다. confirmed anomaly가 아니므로 precision 분모에서 분리한다.
  - `v121_candidate`부터 `labels/monthly_pattern_shift_guardrail_negative_controls*`는 `expected_d02_flag=False`인 guardrail negative control이다.
  - `labels/monthly_pattern_shift_exclusions*`는 `gl_account` 결측, 전기 없음, 당기 없음, 비교 월수/문서 수 부족, 최대월 변화 미미 등으로 D02 평가에서 제외할 group이다.
  - `expected_d02_flag`는 JSD와 guardrail 기준 raw D02 flag 여부이고, `is_true_positive_account`는 D02 truth 여부다. 두 값을 분리해서 정상 계절성/배치 계정을 FP로 오해하지 않는다.
  - `v121_candidate`부터 D02 sidecar에 `evaluation_bucket`, `precision_policy`, `business_event_type`, `expected_macro_priority_band`, `macro_truth_role`, `sidecar_role`을 포함한다.
  - 반복/인터페이스/배치/시스템성 정상 패턴은 `normal_recurring_or_interface_batch` 등 정상 macro context로 분리한다. 이는 D02 raw hit일 수 있지만 confirmed anomaly는 아니다.
  - 2023은 2022와 비교하고, 2024는 2023과 비교한다. 2022는 전기 2021 baseline이 없으므로 기본 D02 평가 대상에서 제외한다.
- **DataSynth 운영본 관찰 결과**
  - `2023 vs 2022`, `2024 vs 2023`에서 기본 `JSD > 0.3`만 적용하면 문서의 대부분이 플래그되어 실무 큐로 사용할 수 없다.
  - 원인은 정상 계정의 연도별 월별 분포가 너무 독립적으로 흔들리는 합성데이터 생성 특성이다.
  - 따라서 D02 평가는 단순 `is_fraud/is_anomaly` 라벨 precision이 아니라 전용 sidecar가 필요하다.
  - 원장을 smoothing하면 D01, Benford, 고액/희소계정쌍, 계절성까지 동시에 훼손될 수 있으므로 v58은 원장 보정이 아니라 sidecar 평가 계약을 우선 적용한다.

#### Phase 1 공통 운영 한계와 조합 해석

Phase 1은 실무에서 `1차 스크리닝`과 `감사 샘플링 우선순위화`에 사용한다. 단독 부정 판정, 감사 결론 자동화, 동일 임계값의 회사 간 일괄 적용에는 사용하지 않는다.

| 한계 | 단독 해석 | 조합되면 위험해지는 신호 |
|------|-----------|--------------------------|
| 룰 임계값이 초기 설계값 중심 | false positive가 많을 수 있음 | 동일 전표/계정에 금액, 시점, 승인, 계정 논리 신호가 2개 이상 결합 |
| 입력 품질 의존 | 컬럼 누락·매핑 오류가 미탐/과탐을 만든다 | `L1-02`, `L1-08` 같은 무결성 신호와 다른 탐지 룰이 동시에 발생 |
| 계정/월/사용자 단위 룰 | 개별 전표 이상을 직접 입증하지 않는다 | 계정 단위 신호(`D01/D02`)와 행 단위 신호(`L3-04`, `L4-03`, `L2-05`) 결합 |
| 정상 반복·시즌성 구분 한계 | 정기 지급, 결산 배부, 감가상각이 걸릴 수 있음 | 반복성인데도 승인 누락, 적요 결손/파손, 역분개, 기말 집중이 같이 존재 |
| 텍스트 룰의 의미 이해 한계 | Phase 1은 의미 부족·우회 표현을 판단하지 않는다 | `L3-08`이 고액, 수기전표, 기말, D02 패턴 변화와 결합 |

운영 원칙:
- 단일 룰 hit는 `검토 후보`로 둔다.
- 다른 성격의 신호가 2개 이상 결합되면 review queue 우선순위를 올린다.
- `통제 실패(L1-05/L1-06/L1-07) + 시점 이상(L3-04/L3-07/L1-08) + 금액/계정 이상(L4-03/L4-04/L3-10)` 조합은 Phase 1에서 가장 먼저 보는 고위험 축이다.
- D01/D02는 전기 대비 분석적 절차 신호이므로, 예산·TB 변동·사업 이벤트·계정체계 변경 확인 없이 결론으로 쓰지 않는다.

#### Variance 독립 트랙 리포팅 (기존회사 전용)

기존회사에서는 Variance 트랙이 활성화되지만, D01/D02는 row-level 기본 가중치에 포함하지 않는다.
두 룰의 `severity`는 감사상 중요도와 정렬/설명 보조값일 뿐, 전표 단위 anomaly score 가중치가 아니다.

| 항목 | 운영 기준 |
|------|-----------|
| row-level score | D01/D02 모두 `0.0` |
| Rule Metrics precision/FP/FN | 포함하지 않음 |
| 별도 리포트 섹션 | `Analytical Review Signals` |
| 평가 단위 | `fiscal_year + company_code + gl_account` |
| 주요 지표 | review groups, truth coverage, missed truth groups, normal-control review groups, L1~L4 overlap docs |
| case priority 반영 | D01/D02 단독은 승격하지 않고, row/document-level 룰과 겹칠 때 설명 및 우선순위 보강 |

---

## 3. Phase 2: ML / DL 보조 분석

Phase 2는 Phase 1의 룰 기반 탐지를 대체하는 단계가 아니라, **룰만으로 놓치기 쉬운 패턴형 이상거래를 보완**하는 계층이다.
특히 금액 분포, 시계열 패턴, 신규 거래관계, 중복·유사 반복, 법인 간 상호작용처럼 단일 룰로 정의하기 어려운 신호를 구조적으로 포착한다.

Phase 2의 운영 책임은 **PHASE1 case priority를 정밀 보정하는 것**이다. PHASE1의 `L1-05`, `L2-03` 같은 룰 ID 자체를 모델 feature로 넣어 다시 예측하게 만들면 target leakage/proxy 문제가 생기고, ML이 새로운 패턴을 찾는 대신 룰 복제기로 전락할 수 있다.

구현은 두 단계로 분리한다.

- `phase2-train`: 전처리, feature variant 생성, family별 trial 실행, leaderboard 정리, promoted model 선정
- `phase2-infer`: 학습 결과에서 승격된 모델과 계약 정보를 읽어 실제 배치에 추론 적용

핵심 구현 파일:
- `src/services/phase2_training_service.py`
- `src/services/phase2_inference_service.py`
- `src/pipeline.py`
- `src/db/loader.py`, `src/db/batch_reader.py`

### 3.1 목적

Phase 2의 목적은 다음 네 가지다.

1. **룰 기반 정탐 보완**: L2/L3/L4 규칙만으로는 설명되지 않는 거래 패턴을 확장 포착
2. **구조적 이상 탐지**: 연속 발생, 군집 발생, 관계형 이상, 신규성 이상 탐지
3. **모델 계약 기반 운영**: 어떤 모델이 학습되고 승격되었는지 추적 가능하게 운영
4. **Phase 3 입력 강화**: 이후 요약·설명 단계가 어떤 모델과 어떤 계약 위에서 생성됐는지 남김

즉 Phase 2는 “DataSynth 유형을 1:1로 각각 분리 구현하는 단계”가 아니라, **여러 이상 신호를 family 단위 모델 계층으로 흡수하는 구조**를 목표로 한다.

### 3.1.1 PHASE1 Case 입력 계약과 Leakage 방어

Phase 2는 row-level raw rule output을 직접 학습 입력으로 삼지 않고, PHASE1 case를 구조화 요약한 값을 입력으로 받는다. 입력은 두 종류로 분리한다.

#### Feature Firewall 정책

PHASE2 case-level ML overlay 입력은 allowlist 기반 feature firewall을 통과해야 한다.

- 모델 `fit`/`predict` 직전 최종 입력에는 `top_rule_ids`, `raw_rule_hits`, `primary_theme`, `secondary_tags`, `phase1_case_id` 같은 식별자·provenance 컬럼이 있으면 안 된다.
- 최종 feature는 숫자형 또는 boolean engineered feature만 허용한다.
- `document_id`, `company_code`, `gl_account` 같은 원천 식별 컬럼은 detector 내부 조인·관계 분석에 쓰일 수 있지만, case-level ML overlay feature로는 쓰지 않는다.
- 단순 keyword drop(`id`, `code`, `rule` 전면 금지)은 사용하지 않는다. `rule_diversity_count`처럼 안전한 집계 피처까지 제거할 수 있기 때문이다.
- 구현 기준: `src/services/phase2_case_contract.py`의 `PHASE2_CASE_FEATURE_COLUMNS`, `enforce_phase2_case_feature_firewall()`

#### ML feature로 사용할 수 있는 값

룰 이름이나 theme 이름 자체가 아니라, 밀도·분포·행동·관계형 특징으로 변환된 값만 feature로 사용한다.

- `rule_diversity_count`: 한 case 안에 섞인 룰 종류 수
- `evidence_type_count`: evidence type 종류 수
- `theme_entropy`: case 내 evidence/theme 분산도
- `cross_process_flag`: 여러 business process가 교차되는지 여부
- `cross_user_flag`: 여러 사용자 또는 승인자가 얽히는지 여부
- `cross_counterparty_flag`: 여러 거래처가 얽히는지 여부
- `repeat_months`, `repeat_score`: 반복 개월 수와 반복 강도
- `document_count`, `row_count`, `total_amount`
- `amount_score`, `control_score`, `duplicate_or_outflow_score`, `logic_score`, `timing_score`, `behavior_score`
- `has_control_failure`, `has_high_materiality`, `has_repeat_pattern`
- `historical_anomaly_percentile`: 동일 사용자/거래처/계정군의 과거 대비 현재 case score 백분위
- `user_case_frequency_percentile`: 동일 사용자의 최근 case 발생 빈도 백분위
- `counterparty_case_frequency_percentile`: 동일 거래처의 최근 case 발생 빈도 백분위
- `amount_percentile_within_user`: 사용자별 과거 금액 분포 대비 백분위
- `amount_percentile_within_counterparty`: 거래처별 과거 금액 분포 대비 백분위

위 목록 중 `historical_anomaly_percentile`, 사용자/거래처별 percentile 계열은 목표 설계 필드다. 현재 구현된 case contract는 기본 집계·교차·점수 피처를 먼저 제공하고, 과거 분포 기반 percentile은 engagement history 연결 후 확장한다.

#### Provenance/display 전용 값

아래 값은 모델 feature가 아니라, 디버깅·감사 추적·화면 설명·export provenance에만 사용한다.

- `phase1_case_id`
- `primary_theme`, `secondary_tags`
- `top_rule_ids`
- `raw_rule_hits`
- `representative_explanation`
- `phase1_case_priority`
- `phase1_base_priority`
- `phase1_priority_adjustments`

즉 Phase 2는 `L1-05가 있으면 위험`을 학습하는 것이 아니라, `통제 신호가 다양한 사용자·프로세스·시점·금액 분포 안에서 비정상적으로 밀집했는가`를 학습한다.

### 3.1.2 PHASE2 Case Overlay 출력 계약

Phase 2는 PHASE1 결과를 덮어쓰지 않고, case에 overlay를 붙인다.

```text
phase2_case_overlay =
  phase1_case_id
  phase2_family_scores
  phase2_adjusted_priority
  precision_adjustment_reason
  detector_statuses
  phase2_inference_contract
  phase2_training_report_id
```

운영 원칙:

- PHASE1 `case_priority`는 원본으로 보존한다.
- PHASE2는 `phase2_adjusted_priority` 또는 `review_priority_adjustment`를 별도 필드로 남긴다.
- 모델 family별 score와 provenance를 함께 저장해, 어떤 모델이 어떤 이유로 case를 올리거나 내렸는지 추적 가능하게 한다.
- dashboard/export는 `PHASE1 base + PHASE2 overlay`를 조합해 보여준다.

### 3.2 전처리

Phase 2는 공통 feature frame을 만든 뒤, 여러 family가 이를 공유해서 사용한다.

#### 공통 전처리

- 금액 컬럼 정규화: 차변·대변·절대금액·로그금액 기반 수치화
- 날짜/시간 파생: 월말 여부, 주말 여부, 심야 여부, posting 간격, 문서 생성 순서
- 사용자/조직 컨텍스트: `created_by`, `approved_by`, `company_code`, `business_process`
- 텍스트/레퍼런스 보조: `line_text`, `header_text`, `reference`, 거래처·계정 관련 reference feature
- 품질 프로파일: 결측률, cardinality, usable ratio를 요약하여 family별 사용 가능 feature를 판정

#### Feature Variant

동일 데이터셋에 대해 여러 전처리 variant를 만든다.

- `baseline_core`: 금액, 계정, 날짜, 기본 사용자 정보 중심
- `plus_persona`: 사용자·승인자·프로세스·회사/부문 맥락 추가
- `plus_reference`: reference, 적요, counterparty, auxiliary 식별자 등 확장 feature 포함

이 variant들은 단순 편의 기능이 아니라, **같은 모델 family라도 어떤 feature 묶음이 실제로 더 잘 작동하는지 비교**하기 위한 탐색 단위다.

#### Rule-Style Family용 입력

일부 family는 일반 tabular embedding보다 구조화 집계 입력이 더 중요하다.

- `timeseries`: 사용자/계정/거래처 단위 빈도, burst, 간격, 직전 대비 변화량
- `relational`: 신규 거래쌍, dormant 재활성, 희귀 관계 조합
- `duplicate`: exact duplicate, near duplicate, 반복 금액/설명 패턴
- `intercompany`: 법인 간 쌍방향, unmatched pair, 비정상 offset 패턴

### 3.3 모델 Family 구성

Phase 2는 하나의 모델이 아니라 여러 family를 병렬로 비교하고, 각 family에서 가장 나은 trial만 승격 대상으로 삼는다.

#### 1. Unsupervised Family

- 목적: 라벨 부족 환경에서 전반적 이상 score 생성
- 대표 모델: VAE 계열 + Isolation Forest 조합
- 강점:
  - 금액 분포가 유난히 튀는 거래
  - 기존 군집과 멀리 떨어진 전표
  - 여러 feature가 동시에 약하게 이상한 복합 신호
- 잘 잡는 예시:
  - 비정상 고액 전표
  - 평소 거의 안 쓰던 조합으로 입력된 전표
  - 여러 약한 red flag가 겹친 전표

#### 2. Supervised Family

- 목적: 신뢰 가능한 라벨이 있을 때 명시적 fraud/anomaly 구분 성능 강화
- 대표 모델: 기존 지도학습 detector와 CV 기반 후보 선택기
- 강점:
  - 이미 관측된 부정 패턴의 재발 탐지
  - feature importance 기반 설명 가능성 확보
- 잘 잡는 예시:
  - 승인 우회 + 특정 사용자 + 특정 금액대 조합
  - 과거 확정 라벨과 유사한 분식/은폐 패턴

#### 3. Transformer Family

- 목적: tabular feature 간 비선형 상호작용 포착
- 대표 모델: FT-Transformer 계열
- 강점:
  - 계정, 사용자, 회사, 프로세스가 복합적으로 얽힌 패턴
  - 단일 룰로 표현하기 어려운 조건 결합
- 잘 잡는 예시:
  - 특정 회사·특정 사용자·특정 계정대에서만 발생하는 복합 이상
  - reference와 금액, 시점이 함께 이상한 경우

#### 4. Sequence Family

- 목적: 시간 순서와 사용자의 연속 행동 패턴 반영
- 대표 모델: sequence detector / BiLSTM 계열
- 강점:
  - 직전 거래와의 연속성, burst, reversal-like 흐름 탐지
  - 시계열 문맥이 있어야 드러나는 이상 포착
- 잘 잡는 예시:
  - 짧은 시간에 같은 사용자가 반복 입력한 전표 묶음
  - 직전 패턴과 급격히 다른 posting 흐름
  - 월말·마감 직전의 비정상 연쇄 입력

#### 5. Timeseries Family

- 목적: burst, frequency, cadence 이상을 명시적으로 포착
- 대표 탐지 축:
  - `TransactionBurst`
  - `UnusualFrequency`
- 강점:
  - 평소 드문 사용자가 특정 시점에 갑자기 몰아서 입력하는 패턴
  - 특정 계정/거래처 조합의 빈도 급등
- 잘 잡는 예시:
  - 결산 직전 이례적으로 같은 사용자가 동일 유형 전표를 집중 입력
  - 평소 월 1~2건이던 거래가 며칠 내 수십 건으로 급증

#### 6. Relational / Novelty Family

- 목적: 관계 기반 신규성, 휴면 후 재활성, 익숙하지 않은 counterpart를 탐지
- 대표 탐지 축:
  - `DormantAccountActivity`
  - `NewCounterparty`
- 강점:
  - 과거 맥락을 기준으로 새롭거나 오래 쉬었다가 다시 나타난 상대방 탐지
- 잘 잡는 예시:
  - 장기간 사용하지 않던 계정/거래처가 갑자기 큰 금액으로 재등장
  - 기존 거래 이력이 거의 없는 counterparty와의 최초 대규모 거래

#### 7. Duplicate Family

- 목적: exact/near duplicate 패턴을 ML 계약 안에서 운영
- 대표 탐지 축:
  - `ExactDuplicateAmount`
  - 반복 금액·적요·사용자 조합
- 강점:
  - 단순 룰 중복 탐지를 학습/계약 체계와 연결
  - duplicate 관련 family도 leaderboard와 promoted contract에 포함
- 잘 잡는 예시:
  - 같은 금액·같은 상대방·유사 적요로 반복된 전표
  - 약간의 시차만 두고 재발행된 동일 패턴 전표

#### 8. Intercompany Family

- 목적: 법인 간 거래의 비대칭, 미정합, 비정상 상계 흐름 탐지
- 대표 탐지 축:
  - `UnmatchedIntercompany`
- 강점:
  - 한쪽 법인엔 있는데 반대편 법인엔 정합되는 거래가 없는 경우 포착
  - 상계 타이밍과 금액 불일치 탐지
- 잘 잡는 예시:
  - C001→C002 거래는 있는데 반대 기록이 누락된 경우
  - 유사 거래가 상호 법인에 비대칭 금액으로 반복되는 경우

#### 9. Stacking Family

- 목적: 여러 family score를 다시 메타 레벨에서 결합
- 대표 모델: OOF 기반 ensemble detector
- 강점:
  - 개별 family가 놓친 약한 신호를 결합해 최종 score 안정화
  - unsupervised + supervised + transformer + sequence + rule-style family를 함께 활용

### 3.4 어떤 부정을 잡는가

Phase 2는 특정 유형 이름을 1:1로 직접 매핑하기보다, 다음과 같은 부정 패턴군을 포착한다.

#### 금액·분포 이상

- 비정상 고액
- 분포상 극단치
- 평소와 다른 금액대의 반복 입력
- 특정 digit/round pattern이 비정상적으로 몰린 거래군

#### 반복·빈도 이상

- 짧은 시간에 몰아 입력된 거래
- 비정상적 반복 빈도
- exact/near duplicate 전표
- reversal 또는 cancel-repost처럼 보이는 연쇄 흐름

#### 관계·신규성 이상

- 처음 등장한 counterparty와의 큰 거래
- 장기간 휴면 후 재활성된 계정 또는 관계
- 평소 쓰지 않던 관계 조합
- 회사 간 비정상 상호작용 또는 미정합

#### 복합 조건형 이상

- 특정 사용자 + 특정 계정 + 특정 시점이 겹칠 때만 드러나는 패턴
- 룰 단독으론 약하지만 여러 신호가 겹치며 강해지는 거래
- Phase 1에서 약하게 표시된 전표 중, ML score가 추가로 높게 나오는 경우

### 3.5 하이퍼파라미터와 탐색 방식

Phase 2는 “모든 모델 × 모든 하이퍼파라미터의 exhaustive search”를 수행하지 않는다.
대신 **family별 preset search + variant 비교 + 승격 정책**으로 운영 가능한 탐색 구조를 만든다.

#### 탐색 단위

- feature variant
- search preset
- model family

즉 하나의 trial은 대략 다음 조합으로 정의된다.

- `family × feature_variant × search_preset`

#### Family별 조정 예시

- `unsupervised`
  - contamination
  - latent dimension
  - hidden width
  - epoch / learning rate
- `supervised`
  - class weight
  - sampling 정책(SMOTE 여부 등)
  - estimator 후보와 CV 설정
- `transformer`
  - hidden size
  - head 수
  - dropout
  - epoch / batch size
- `sequence`
  - sequence length
  - hidden size
  - recurrent depth
  - stride / context column 사용 여부
- `timeseries / relational / duplicate / intercompany`
  - window size
  - min frequency
  - tolerance
  - matching threshold
  - proxy scoring weight
- `stacking`
  - base family selection
  - OOF 사용 여부
  - meta learner 입력 조합

#### 승격 정책

각 family의 최고 점수 trial을 무조건 승격하지 않고, 다음 조건을 함께 본다.

- 최소 completed trial 수
- 최소 metric 기준
- 최소 search 다양성
- 최대 failed trial 비율
- registry version 또는 artifact 존재 여부

즉 “한 번 우연히 잘 나온 trial”은 승격에서 제외될 수 있다.

Rule-style family는 일반 AUC 대신 `rule_proxy_score` 성격의 정규화 점수를 사용해 leaderboard에 올린다.

### 3.6 Train / Infer 계약

#### Train (`phase2-train`)

1. 라벨 가용성 판정
2. feature frame 생성
3. feature variant 생성
4. family별 trial queue 구성
5. trial 실행
6. leaderboard 정렬
7. promoted model 선정
8. training report / promotion policy / inference contract 저장

#### Infer (`phase2-infer`)

1. 최신 또는 지정된 training report 확인
2. promoted model 및 required family 확인
3. family별 detector 실행
4. detector status, registry version, sub detector 정보 기록
5. 최종 phase2 score 생성

이 구조 덕분에 추론 시점에는 “그때그때 가장 최근 모델을 대충 불러오는 방식”이 아니라, **학습 리포트에서 승격된 정확한 버전**을 기준으로 운영할 수 있다.

### 3.7 Provenance

Phase 2는 결과만 남기지 않고, 어떤 계약으로 돌았는지까지 남긴다.

핵심 메타데이터:
- `phase2_training_report_id`
- `phase2_inference_contract`
- `phase2_promotion_policy`
- `phase2_inference_mode`
- `detector_statuses_json`

추론 모드 예시:
- `training_contract`: 승격 모델 기반 정상 운영
- `cold_start_bootstrap`: 초기 모델 부재 시 예외적 cold-start 실행
- `untrained_contract_only`: 학습 계약은 있으나 실제 추론 승격 모델이 없는 상태

이 provenance는 DB 저장, 복원, export, Phase 3 insight prompt까지 연결된다.

### 3.8 해석 기준

Phase 2 결과는 “유형 A detector가 유형 A만 잡는다”는 의미로 해석하지 않는다.
대신 다음처럼 해석한다.

- 특정 family가 높다: 그 family가 잘 포착하는 구조적 이상 신호가 강하다
- 여러 family가 동시에 높다: 단일 룰보다 더 강한 복합 이상 정황일 수 있다
- stacking이 높다: 개별 family 신호가 메타 레벨에서 일관되게 위험하다고 본 경우다

즉 Phase 2는 **룰 기반 판단을 보완하는 모델 계층**이며, 감사인의 후속 검토 우선순위를 정밀화하는 역할을 한다.

### 3.9 후속 고도화

향후 확장 방향은 다음과 같다.

- family 내부 탐색 공간 확대
- feature variant 세분화
- promotion policy 추가 강화
- 도메인 특화 reference / counterparty feature 확장
- 실제 운영 데이터 기준 재학습 정책 고도화

현재 구현의 목표는 “완전 탐색 AutoML”이 아니라, **설명 가능하고 추적 가능한 Phase 2 운영 구조**를 만드는 데 있다.

## 4. Phase 3: NLP + 그래프 (5개 유형, 미구현)

| DataSynth 유형          | 카테고리     | Sev | 방법               | 상태 |
|-------------------------|-------------|-----|--------------------|------|
| LatePosting             | ProcessIssue | 2  | 시계열 NLP 복합     | ⬜   |
| MissingDocumentation    | ProcessIssue | 3  | NLP (설명 실질성 분석) | ⬜   |
| CircularTransaction     | Graph(GR01)  | 4  | Johnson N-hop 순환 (length_bound=5) | ✅ WU-22 |
| TransferPricingAnomaly  | Graph(GR03)  | 4  | 양방향 IC 엣지 price asymmetry      | ✅ WU-22 |
| TrendBreak (TL4-01/TL2-01)  | Statistical  | 4/3| 설정vs상각 분리     | ✅   |

### Phase 3 점수 체계 (7트랙)

```
rule(0.15) + xgboost(0.20) + vae(0.15) + benford(0.10) + duplicate(0.15) + nlp(0.10) + graph(0.15)
```

**Phase 3 누적: Tier 1(20) + Tier 2(16) + Tier 3(5) = 41개 유형 커버**

### 4.1 PHASE3 입력 계약 — Selected Case 중심

Phase 3는 전체 전표 raw row를 일괄 LLM/NLP에 투입하지 않는다. PHASE1/2가 선별한 case 단위 입력만 사용한다.

Context limitation 정책:

- 자동 생성 기본값은 상위 `top_n=10` case다.
- `top_n`은 하드 리밋 `100`을 넘기지 않는다.
- `max_documents_per_case` 기본값은 `10`, 하드 리밋은 `20`이다.
- 전표는 랜덤 샘플링하지 않는다. 금액이 큰 전표 3건을 먼저 고르고, 그 다음 rule/evidence가 많이 붙은 대표 전표를 보강한다.
- warning/medium case는 기본 자동 생성 대상이 아니라 UI의 명시적 "설명 생성" 같은 on-demand 경로로 생성한다.
- 구현 기준: `src/llm/phase3_case_prompt.py`, `src/llm/case_narrative_generator.py`, `src/services/phase3_case_narrative_service.py`

기본 입력:

- `case_id`
- `primary_theme`
- `representative_explanation`
- `evidence_tags`
- `top_documents` 기본 10건, 최대 20건
- `top_rule_ids`와 rule 설명 metadata
- `phase1_case_priority`
- `phase2_family_scores`
- `phase2_inference_contract`
- `phase2_training_report_id`
- 사용 가능한 `line_text`, `header_text`, `gl_account`, `document_type`, `business_process`, `created_by`, `approved_by`, `counterparty`, `amount`, `posting_date`

`top_rule_ids`는 LLM 설명의 근거 표시와 provenance 연결용이며, 새로운 사실을 추론하는 재료가 아니다.

### 4.2 관계망 Context 주입 원칙

Graph/network context는 모든 case에 넣지 않고, 필요한 case에만 요약 형태로 넣는다.

주입 조건:

- `primary_theme`가 `duplicate_or_outflow`, `intercompany_structure`, `statistical_outlier` 중 하나
- `secondary_tags`에 `duplicate_or_outflow`, `intercompany_structure`, `statistical_outlier` 중 하나가 포함됨
- Phase 2의 `intercompany`, `relational`, `graph` family score가 높음
- `related_entity_risk.degree`, `graph_degree`, `distinct_process_count`, `department_count` 등 관계망 degree 요약값이 1보다 큼
- 동일 사용자·거래처·회사쌍 주변 case가 최근 기간에 반복 발생

권장 입력 필드:

```text
related_entity_risk:
  user_recent_case_count
  counterparty_recent_case_count
  company_pair_recent_case_count
  shared_counterparty_count
  degree
  distinct_process_count
  department_count
  graph_hop_summary
  related_high_priority_case_ids
```

운영 원칙:

- LLM에 raw graph edge 전체를 넘기지 않는다.
- graph detector나 relational detector가 계산한 요약값만 전달한다.
- LLM은 그래프 분석을 직접 수행하지 않고, 이미 계산된 관계망 신호를 감사 설명문으로 번역한다.

### 4.3 환각 방지와 표현 제약

Phase 3는 회계·법률 결론 생성기가 아니라 **근거 기반 감사 narrative generator**다. 제공된 PHASE1 evidence, PHASE2 provenance, case input 안에서만 서술한다.

프롬프트 제약:

- 제공된 입력에 없는 사실을 쓰지 않는다.
- 회계기준, 법규 조항, 회사 정책을 새로 추론해 덧붙이지 않는다.
- 부정, 위반, 조작을 단정하지 않는다.
- `가능성`, `검토 필요`, `확인 필요` 수준으로 표현한다.
- 근거가 부족하면 부족하다고 명시한다.
- 각 핵심 문장은 어떤 evidence 또는 model provenance에 기반했는지 추적 가능해야 한다.
- PHASE1의 `적요 결손/파손 신호`와 PHASE3의 `의미 기반 설명 부족 판단`을 구분해 표시한다.

### 4.4 Phase 3 적요/설명 분석 역할 정의

Phase 3는 Phase 1의 `L3-08`을 대체하기 위해 존재하는 것이 아니라, Phase 1이 의도적으로 단순화한 텍스트 판정을 **의미 이해 기반으로 보강**하기 위한 계층이다.

- **Phase 1 L3-08이 하는 일**
  - 공백/누락, 노이즈성 문자열처럼 원천 기록이 없거나 깨진 형식 신호만 수집
  - 설명 가능성과 재현성을 우선하는 저비용 스크리닝
- **Phase 1 L3-08이 하지 않는 일**
  - 지나치게 짧지만 정상일 수 있는 적요를 길이만으로 부실 판정
  - 명시 위험 키워드나 회사별 blacklist/whitelist 기반 위험 적요 판정
  - 말은 길지만 실질 설명이 없는 적요 판정
  - 회사 내부 은어, 완곡어, 우회 표현 해석
  - 계정/프로세스/금액/시점 대비 적요의 의미상 부자연스러움 판단

따라서 Phase 3 NLP 계층은 아래 역할을 담당한다.

1. **설명 실질성 부족 판정**
   - 예: `결산 반영`, `정리분`, `조정사항 반영`, `기타 대체`처럼 문장은 존재하지만 실질 설명이 부족한 경우
2. **계정-적요 의미 정합성 점검**
   - 계정, 업무 프로세스, 금액, 시점에 비해 적요가 부자연스럽거나 설명 책임을 회피하는 경우
3. **은어/우회 표현 탐지**
   - 회사 내부 표현, 완곡어, 책임 회피성 표현처럼 키워드 사전에 없는 문구 탐지

운영 원칙은 다음과 같다.

- Phase 1은 recall 우선 스크리닝을 유지한다.
- Phase 3는 LLM/NLP를 전체 전표에 일괄 적용하기보다, `L3-08`, `L3-02`, `L3-04`, `L3-11`, `L1-05`, `L1-07`, `L2-05`, `L3-10` 등과 결합된 고위험 후보 또는 애매한 후보에 우선 적용한다.
- 사용자 설명에서는 Phase 1의 `적요 결손/파손 신호`와 Phase 3의 `의미 기반 설명 부족 판단`을 구분해 보여준다.

---

### 4.5 Graph Detector (WU-22) — networkx 기반 순환·이전가격

> **근거**: ISA 550 §23 특수관계자 사업상 합리성 · FSS 순환거래 페이퍼컴퍼니 패턴.
> **차별화**: L3-03(관계사 거래 검토 후보) 및 R03(그룹 편차 통계)의 한계를 그래프 토폴로지로 보완.

#### GR01 — CircularTransaction (N-hop 순환)

- **심각도**: 4
- **알고리즘**: networkx `simple_cycles(G, length_bound=max_cycle_length)` (Johnson)
- **그래프 구성**:
  - 노드: `(company_code, trading_partner)` 튜플
  - 엣지: `credit > 0` → `company → partner`, `debit > 0` → `partner → company`
  - 자료구조: `MultiDiGraph` (다중 엣지 보존 → 원본 행 인덱스 역매핑)
- **`trading_partner` NULL fallback**: 동일 `document_id` 그룹의 다른 `company_code`로 implicit IC pair 추론 (DataSynth 640건 NULL 복구 목적)
- **점수화**: binary 1.0 × `severity_factor(0.8)` (연속 점수화는 튜닝 단계로 이연)
- **L3-03과의 관계**: L3-03은 `is_intercompany` 기반 관계사 거래 후보만 반환한다. GR01이 실제 N-hop 순환 탐지를 담당한다.
- **DataSynth truth 해석**: v39 기준 GR01은 두 층으로 평가한다. `graph_gr01_review_population`은 룰이 구조적 순환 후보를 올리는지 보는 coverage truth이고, `CircularTransaction`/`graph_gr01_confirmed_anomalies`는 확정 이상 truth다. `graph_gr01_normal_cycle_controls`는 정상 내부거래 순환도 존재한다는 negative-control이므로 raw GR01 hit를 전부 FP로 계산하지 않는다.

#### GR03 — TransferPricingAnomaly (양방향 price asymmetry)

- **심각도**: 4
- **알고리즘**: pandas groupby 기반 양방향 쌍 식별 + 차이율 계산
  1. IC 행만 필터
  2. `reference`가 있는 경우 같은 reference의 상호 회사쌍 문서를 먼저 비교한다. IC 채권/채무 GL이 서로 달라도 문서 최대금액 기준 비대칭을 계산한다.
  3. reference-pair 비교 후, 보조 신호로 `(src_company, dst_company, gl_account)` 그룹 평균 amount와 역방향 그룹을 비교한다.
  4. `deviation = |amount_fwd - amount_rev| / min(amount_fwd, amount_rev) > threshold(20%)`
  5. 점수 = `min(1.0, deviation / (threshold × 3))`
- **V39 보정**: `TransferPricingAnomaly` 라벨은 한쪽 문서의 전체 거래금액을 scaling하므로, IC 라인 금액만 비교하면 세금/손익 라인 때문에 미탐이 생긴다. GR03 reference-pair 경로는 문서 최대금액을 사용해 이 라벨 구조와 실제 대사 관점을 맞춘다.
- **R03과의 차별화**:

| 항목       | R03 (Relational)                      | GR03 (Graph)                         |
|-----------|---------------------------------------|--------------------------------------|
| 접근       | `(partner, account)` 그룹 편차 통계   | **방향성 + 양방향성** 엣지 분석      |
| 수식       | `\|x - μ\| / μ > 15%`                 | `\|mean_fwd - mean_rev\| / min > 20%`|
| 포착 대상  | 단일 그룹 내 outlier 금액             | 매출/매입 가격 **비대칭** 패턴       |
| 중복 플래그 | MAX 패턴으로 severity 동일(4) 흡수    | 동일                                 |

#### OOM 방어 3중 장치 ⚠️

회계 장부 100만+ 행에서 `iterrows() + add_edge` 루프는 **수십 분 지연 + RAM OOM**. 필수 방어:

1. **사전 필터 (pandas 벡터화)**: `is_intercompany == True AND max(debit, credit) ≥ min_amount(1천만원)` → 목표 ≤ 50,000 행
2. **`nx.from_pandas_edgelist`로 C-레벨 변환**: `np.where`로 `src`/`dst` 컬럼을 먼저 생성. `for ... add_edge()` 루프/`apply`/`iterrows` 금지
3. **엣지 수 안전장치**: `len(edges_df) > graph_gr01_max_edges(50,000)` 시 `quantile` 기반 `min_amount` 자동 상향 + warning. 추가로 `weakly_connected_components`로 분리 후 컴포넌트별 `simple_cycles` 호출. 컴포넌트는 노드 수와 엣지 수가 모두 임계값을 넘을 때만 skip한다.

**벤치마크**: 100k 행 DataFrame에서 실행 시간 1.3초 (목표 15초 이내).

#### Settings 파라미터 (`config/settings.py`)

```python
graph_gr01_max_cycle_length: int = 5          # Johnson length_bound
graph_gr01_min_amount: float = 10_000_000.0   # 엣지 최소 금액 (materiality, 1천만원)
graph_gr01_max_edges: int = 50_000            # 엣지 수 상한 (초과 시 자동 상향)
graph_gr01_max_component_size: int = 500      # component 노드 임계
graph_gr01_max_component_edges: int = 5_000   # component 엣지 임계
graph_gr03_min_path_length: int = 2           # 경로 최소 노드 수
graph_gr03_price_deviation_threshold: float = 0.20  # 양방향 가격 편차 허용
```

#### Metadata 출력

`DetectionResult.metadata`에 관측 지표 누적:
- `gr01_edges_prefiltered`, `gr01_edges_built`, `gr01_min_amount_effective`, `gr01_max_edges_raised`
- `gr01_implicit_edges` (document_id fallback 복구 건수)
- `gr01_cycles_found`, `gr01_skipped_components`
- `gr03_bidirectional_pairs`, `gr03_flagged_pairs`

#### 제외된 룰

**GR02 (CentralityAnomaly)**: DataSynth 그래프 규모(회사 3개, 거래처 수십 개)에서 betweenness centrality 분석이 통계적으로 무의미. 실데이터 유입 후 재검토.

---

## 5. 제외 유형

### 5.1 Drop — 11개 DataSynth 유형

| 유형                     | 합계 | 제외 사유                                         |
|--------------------------|------|---------------------------------------------------|
| RoundingError            | 3    | 실무 중요성 sev1, false positive 과다              |
| WrongCostCenter          | 0    | 코스트센터 마스터 없이 정합성 판단 불가             |
| DecimalError             | 0    | 소수점 오류는 시스템 레벨에서 방지                  |
| LateApproval             | 1    | 승인 로그 데이터 없음                              |
| IncompleteApprovalChain  | 1    | 승인 체인 데이터 없음                              |
| UnusualTiming            | 7    | L3-05/L3-06과 완전 중복 → 별도 유형 불필요             |
| RepeatingAmount          | 5    | ExactDuplicateAmount와 중복                        |
| UnusuallyLowAmount       | 3    | false positive 과다                                |
| MissingRelationship      | 1    | document_flows 데이터 의존                         |
| CentralityAnomaly        | 0    | 그래프 분석 범위 초과                              |
| AnomalousRatio           | 2    | StatisticalOutlier에 포섭                          |

> **제외 원칙**: ① 한국 법규 매핑 불가(축1=0), ② 현재 스키마로 탐지 불가(축3=0),
> ③ 기채택 유형과 완전 중복 중 하나 이상 해당.

### 5.2 불필요 5건 + 범위 밖 2건

상세 사유는 [DETECTION_REFERENCE.md §7](DETECTION_REFERENCE.md#7-프로젝트-범위와-한계) 참조.

---

## 6. DataSynth 갭 현황

> 갱신일: 2026-04-02 | DataSynth v21 확정 | 1,106,056행 | Phase 1 Recall 91.4% | Normal 85.2%

### 의존 관계

```
DETECTION_RULES.md (이 문서, 뿌리)
  ↓ 도출
settings.py + audit_rules.yaml (설정)
  ↓ 참조
detection 코드 (구현)
  ↓ 테스트
DataSynth 데이터 (검증)
```

### 갭 대조표

| 항목           | 이 문서 정의              | settings.py 현재값                                                          | DataSynth v1.2.0 실태                         | 해결 상태 |
|:---------------|:-------------------------|:---------------------------------------------------------------------------|:----------------------------------------------|:----------|
| 매출 계정      | "4xxx" (K-IFRS 기준)     | `revenue_account_prefixes: ['4']`                                          | gl_account 4xxx 존재 (20%)                     | ✅ 해결   |
| 승인 한도      | 명시 없음 (회사별)        | `approval_thresholds: [10M, 100M, 1B, 5B, 10B, 50B]` (6단계)              | lognormal mu=14.0 (중앙값 ~120만, 최대 1,000억) | ✅ 해결   |
| 거래처 식별    | `auxiliary_account_number` | L2-02에서 사용                                                               | 59% 유효 (652K건)                               | ✅ 해결   |
| 심야 기준      | 22시~06시                | `midnight_start: 22`                                                       | posting_date datetime (시분초 포함)             | ✅ 해결   |
| 관계사 식별    | GL 계정 prefix 매칭       | `intercompany_identifiers: ['1150', '2050', '4500', '2700']`               | IC GL 1150/2050/4500/2700 존재                  | ✅ 해결   |
| 직무분리 임계  | L1-06 direct SoD + L3-12 review 분리 | `sod_conflict_type` + `work_scope_excess_review_population`                 | direct conflict는 L1-06, role/process breadth는 L3-12 sidecar | v80 정리 |
| Benford 위반   | MAD > 0.012              | `benford_mad_threshold: 0.012`                                              | BenfordViolation 157건 라벨 주입                | ✅ 해결   |
| 필수필드 누락  | `schema.yaml` required 컬럼 NULL 검사 | schema.yaml 참조                                                           | MCAR 2% (gl_account, document_type)             | ✅ 해결   |

### 해결 완료 (v1.2.0)

| 항목 | 원인 | 조치 | 파일 |
|:-----|:-----|:-----|:-----|
| L2-01/L3-02 승인한도 불일치 | 단일 한도 + USD 금액 범위 | KRW 6단계 승인한도 + lognormal mu=14.0 | `settings.py`, `datasynth.yaml` |
| L1-06 SOD 과탐 | 41명 소규모 시뮬레이션 | 1,365명 확대, SOD 위반률 3.32% (2026-04-14 실측) | `datasynth.yaml` |
| L3-03 관계사 미식별 | `intercompany_identifiers: []` | IC GL prefix 4개 등록 | `audit_rules.yaml` |
| L3-06 심야 미탐지 | posting_date 시간정보 없음 | datetime 전환 | `schema.yaml`, DataSynth |
| `is_suspense_account` all-False | 한글 키워드만 매칭 | 하이브리드: 텍스트 키워드 OR GL 코드 prefix | `pattern_features.py`, `audit_rules.yaml` |
| `is_round_number` all-False | float 소수점 꼬리 | `base.round(0) % unit` 허용 | `amount_features.py` |

### v21 확정 결과 (2026-04-02)

| 항목 | 값 |
|:-----|:---|
| Phase 1 Recall | 91.4% (2,408 / 2,636) |
| 전체 Recall | 92.0% (7,197 / 7,827) |
| 100% Recall 룰 | 10개 (L1-01, L1-02, L1-03, L4-01, L2-02, L3-05, L3-06, L1-08, L3-08, L2-05) |
| L1-06 flagged | 1.9% (정상) |
| Normal 등급 | 85.2% |
| 구조적 한계 (ML 필요) | L2-03(10%), L3-03(4%), L4-04(9%), L4-02(29%) — Phase 2 대상 |

상세: [test-results/rule-label-gap-analysis.md](../tests/phase1_rulebase/test-results/rule-label-gap-analysis.md)

### 미해결 (경미 — Phase 2 이후)

| 항목 | 원인 | 현재 상태 | 대상 |
|:-----|:-----|:---------|:-----|
| L3-09 적요 키워드 부족 | 확률 체인(0.5%×5%×30%)으로 키워드 주입 건수 극소 — 정상 동작 | GL prefix 기반 탐지 정상 작동. 적요 의미 분석은 Phase 3 LLM 영역(#71, #84, #88) | Phase 3 이관 |
| trading_partner | 99.9% NULL (784건) | L3-03 IC GL prefix 매칭으로 대체 | DataSynth Rust |
| cost_center | 81.2% NULL | L2-05 세분화 키 활용도 제한 | DataSynth Rust |

---

## 7. 성능 평가 지표 체계

| 계층           | 지표            | 용도                                          |
|:---------------|:----------------|:----------------------------------------------|
| 1차 (메인)     | AUPRC (PR-AUC)  | threshold-free, 불균형에 강건. 지도/비지도 공통 |
| 1차 (메인)     | F2-score        | Recall 가중 (부정 놓치는 비용 > 오탐 비용)     |
| 2차 (보조)     | MCC             | 불균형에서도 신뢰할 수 있는 단일 지표           |
| 2차 (보조)     | DR@FAR=5%       | "오탐 5% 허용 시 탐지율" — 실무 의사결정용      |
| 3차 (참고)     | ROC-AUC         | 모델 간 비교용 (불균형 caveat 명시)             |
| 보고용         | Precision/Recall/F1 | 대시보드 표시 + 감사인 소통용               |

> F2를 사용하는 이유: 감사에서 부정을 놓치는 비용(FN)이 오탐 비용(FP)보다 크므로
> Recall에 2배 가중하는 F2가 F1보다 적합.

---

## 부록 A: 52개 유형 3축 평가 전체 목록

### Tier 1 — Must: Phase 1 (20개)

```
DataSynth 유형                   법규  실증  데이터  합계  레이어  룰 ID
─────────────────────────────────────────────────────────────────────────
UnbalancedEntry                   3     2     3      8    A       L1-01
MissingField                      3     1     3      7    A       L1-02
InvalidAccount                    3     1     3      7    A       L1-03
RevenueManipulation               3     3     3      9    B       L4-01
JustBelowThreshold                3     2     3      8    B       L2-01
ExceededApprovalLimit             1     2     3      6    B       L1-04
DuplicatePayment                  2     3     3      8    B       L2-02
DuplicateEntry                    2     3     3      8    B       L2-03
SelfApproval                      1     3     3      7    B       L1-05
SegregationOfDutiesViolation      1     3     3      7    B       L1-06
ManualOverride                    3     3     3      9    B       L3-02
SkippedApproval                   1     3     3      7    B       L1-07
RelatedPartyTransactionSignal     3     2     3      8    B       L3-03
ExpenseCapitalization              —     —     —      —    B       L2-04  *
RushedPeriodEnd                   3     3     3      9    C       L3-04
WeekendPosting                    3     1     3      7    C       L3-05
AfterHoursPosting                 3     1     3      7    C       L3-06
AbnormalHoursConcentration        2     2     3      7    C       L4-05
BackdatedEntry                    3     2     3      8    C       L3-07
WrongPeriod                       2     2     3      7    C       L1-08
VagueDescription                  3     3     3      9    C       L3-08
BenfordViolation                  3     2     2      7    Benford L4-02
UnusuallyHighAmount               2     3     3      8    C       L4-03
UnusualAccountPair                3     1     2      6    C       L4-04
SuspenseAccountAbuse              —     —     —      —    C       L3-09  *
```

운영 주의:
- 위 표의 `ManualOverride -> L3-02`는 원래 DataSynth anomaly taxonomy 기준 매핑이다.
- 실제 `L3-02` 운영/평가 truth는 `source in ('manual','adjustment')`인 수기전표 모집단 sidecar를 우선 사용한다.

> \* L2-04, L3-09은 DataSynth 52개 유형 외 프로젝트 자체 도출 룰이므로 3축 평가 대상 외.

### Tier 2 — Should: Phase 2 (16개)

```
DataSynth 유형              법규  실증  데이터  합계
────────────────────────────────────────────────────
ImproperCapitalization       2     3     2      7
FictitiousEntry              2     3     2      7
FictitiousVendor             2     3     1      6
RoundDollarManipulation      3     1     2      6
MisclassifiedAccount         2     2     2      6
ReversedAmount               2     1     2      5
TransposedDigits             2     0     2      4
FutureDatedEntry             2     1     2      5
CurrencyError                2     1     1      4
StatisticalOutlier           2     1     2      5
ExactDuplicateAmount         2     2     2      6
TransactionBurst             2     2     2      6
UnusualFrequency             2     1     2      5
DormantAccountActivity       3     2     2      7
NewCounterparty              1     2     1      4
UnmatchedIntercompany        2     2     1      5
```

### Tier 3 — Could: Phase 3 (5개)

```
DataSynth 유형             법규  실증  데이터  합계
───────────────────────────────────────────────────
LatePosting                 1     1     1      3
MissingDocumentation        2     2     1      5
CircularTransaction         3     2     1      6
TransferPricingAnomaly      2     2     1      5
TrendBreak                  2     1     1      4
```

### Drop — 제외 (11개)

```
DataSynth 유형              법규  실증  데이터  합계  제외 사유
──────────────────────────────────────────────────────────────────────
RoundingError                0     0     3      3    실무 중요성 sev1
WrongCostCenter              0     0     0      0    마스터 부재
DecimalError                 0     0     0      0    시스템 레벨 방지
LateApproval                 1     0     0      1    데이터 없음
IncompleteApprovalChain      1     0     0      1    데이터 없음
UnusualTiming                3     1     3      7    L3-05/L3-06 중복
RepeatingAmount              2     1     2      5    ExactDuplicateAmount 중복
UnusuallyLowAmount           1     0     2      3    false positive 과다
MissingRelationship          1     0     0      1    스키마 외
CentralityAnomaly            0     0     0      0    ROI 낮음
AnomalousRatio               1     0     1      2    StatisticalOutlier 포섭
```

---

## 부록 B: 표준 컬럼 스키마

DataSynth `journal_entries.csv` 39개 컬럼 기준.

### 필수 컬럼 (10개)

| 컬럼명           | 타입   | ACDOCA  | 설명             | 탐지 활용              |
|------------------|--------|---------|------------------|------------------------|
| `document_id`    | str    | `belnr` | 전표 ID (UUID)    | L1-01, L2-02, L2-03(실무형 보강 시 중요)          |
| `company_code`   | str    | `rbukrs`| 회사코드          | L3-03                    |
| `fiscal_year`    | int    | `gjahr` | 회계연도          | L1-08                    |
| `fiscal_period`  | int    | `monat` | 회계기간          | L1-08                    |
| `posting_date`   | date   | `budat` | 전기일            | L3-04~L1-08                |
| `document_date`  | date   | `bldat` | 전표일            | L3-07                    |
| `gl_account`     | int    | `racct` | G/L 계정코드      | L1-03, L4-01, L4-04          |
| `debit_amount`   | float  | `wsl(S)`| 차변 금액         | L1-01, L2-01~L2-03, L4-02~L4-03  |
| `credit_amount`  | float  | `wsl(H)`| 대변 금액         | L1-01, L2-01~L2-03, L4-02~L4-03  |
| `document_type`  | str    | `blart` | 전표유형          | L4-01                    |

### 권장 컬럼 (10개)

| 컬럼명             | 타입   | ACDOCA  | 설명              | 탐지 활용   |
|--------------------|--------|---------|--------------------|------------|
| `created_by`       | str    | `usnam` | 입력자             | L1-05~L1-07    |
| `source`           | str    | —       | 입력소스           | L3-02, L1-07   |
| `business_process` | str    | —       | 비즈니스 프로세스   | L1-06        |
| `line_number`      | int    | `docln` | 라인번호           | L1-01        |
| `local_amount`     | float  | `hsl`   | 현지통화 금액      | 환율 검증   |
| `currency`         | str    | `rwcur` | 통화               | 환율 검증   |
| `cost_center`      | str    | `rcntr` | 코스트센터         | —          |
| `profit_center`    | str    | `prctr` | 손익센터           | —          |
| `line_text`        | str    | `sgtxt` | 적요               | L3-08        |
| `header_text`      | str    | `bktxt` | 헤더 텍스트        | L3-08        |

### 레이블 컬럼 (2개)

| 컬럼명       | 타입 | 설명          | 분포                    |
|-------------|------|---------------|-------------------------|
| `is_fraud`  | bool | fraud 여부     | True 1.9%, False 98.1%  |
| `is_anomaly`| bool | anomaly 여부   | True 7.5%, False 92.5%  |

### DataSynth 확장 예정 컬럼

| 컬럼명              | 타입     | 용도                      |
|---------------------|----------|---------------------------|
| `has_attachment`     | bool     | 증빙 첨부 여부             |
| `supporting_doc_type`| str     | 세금계산서/카드/현금영수증 등 |
| `delivery_date`      | date    | 납품일 (컷오프 검증)       |
| `invoice_amount`     | float   | 세금계산서 금액            |
| `tax_amount`         | float   | 부가세 금액               |
| `supply_amount`      | float   | 공급가액                  |
| `changed_by`         | str     | 변경자                    |
| `change_date`        | datetime| 변경 일시                  |
| `changed_field`      | str     | 변경 필드명               |
| `ip_address`         | str     | 접속 IP                   |
| `document_number`    | int     | 순차 전표번호 (UUID 별도)  |
| `approval_level`     | int     | 승인 레벨                  |

---

## 부록 C: 도메인 용어 ↔ 코드 매핑

| 감사 용어      | 영문              | DataSynth 컬럼         | 코드 변수              |
|---------------|-------------------|------------------------|------------------------|
| 전표          | Journal Entry      | `document_id`          | `journal_entry`, `je`  |
| 전기일        | Posting Date       | `posting_date`         | `posting_date`         |
| 전표일        | Document Date      | `document_date`        | `document_date`        |
| 적요          | Line Text          | `line_text`            | `line_text`            |
| 차변          | Debit              | `debit_amount`         | `debit_amount`         |
| 대변          | Credit             | `credit_amount`        | `credit_amount`        |
| 역분개        | Reversal           | `xstov` flag           | `is_reversal`          |
| 수기전표      | Manual JE          | `source='manual'`      | `is_manual_je`         |
| 관계사 거래   | Intercompany       | `company_code` 쌍      | `is_intercompany`      |
| 총계정원장    | General Ledger     | `gl_account`           | `gl_account`           |
| 이상징후      | Anomaly            | `is_anomaly`           | `anomaly`              |
| 입력자        | Created By         | `created_by`           | `created_by`           |
| 전표유형      | Document Type      | `document_type`        | `document_type`        |

---

## 부록 D: Fraud Red Flags (참고)

정상 전표에 부여된 의심 징후 (211건, 전부 is_fraudulent=False).
Phase 2 ML에서 **False Positive 내성 훈련**에 활용.

| pattern_name                      | 건수 | category    | strength | confidence |
|-----------------------------------|------|-------------|----------|------------|
| month_end_timing                  | 32   | Timing      | Weak     | 0.10       |
| round_dollar_amount               | 31   | Transaction | Weak     | 0.15       |
| vague_description                 | 20   | Document    | Weak     | 0.15       |
| after_hours_posting               | 18   | Timing      | Weak     | 0.15       |
| repeat_amount_pattern             | 15   | Transaction | Weak     | 0.18       |
| benford_first_digit_deviation     | 12   | Transaction | Weak     | 0.12       |
| weekend_transaction               | 12   | Timing      | Weak     | 0.12       |
| unusual_account_combination       | 11   | Account     | Weak     | 0.20       |
| invoice_without_purchase_order    | 11   | Document    | Moderate | 0.30       |
| employee_vacation_fraud_pattern   | 10   | Employee    | Moderate | 0.45       |
| amount_just_below_threshold       | 10   | Transaction | Moderate | 0.35       |
| missing_supporting_documentation  | 9    | Document    | Moderate | 0.30       |
| dormant_vendor_reactivation       | 7    | Vendor      | Moderate | 0.35       |
| new_vendor_large_first_payment    | 5    | Vendor      | Moderate | 0.40       |
| unusual_vendor_payment_pattern    | 4    | Vendor      | Moderate | 0.30       |
| vendor_no_physical_address        | 2    | Vendor      | Strong   | 0.15       |
| po_box_only_vendor                | 2    | Vendor      | Strong   | —          |

---

## 관련 문서

- [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) — 법규·기준서·도메인 지식 근거
- [pre-plan/05-detection.md](pre-plan/05-detection.md) — detection 구현 가이드
- [pre-plan/05a-detection-ml.md](pre-plan/05a-detection-ml.md) — Phase 2b ML 탐지기 설계
- [debugging.md](debugging.md) — engine.py rules 버그 기록
- [E2E 테스트 결과](../tests/test_detection/test-results/e2e-detection-datasynth.md)


