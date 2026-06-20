# Detection Rules — 감사 검토 후보 선별 룰 전체 목록

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

한국 감사기준서(240호, K-SOX, PCAOB AS 2401)를 근거로 도출한 전표 검토 후보 선별 룰의 단일 참조 문서.
법규·기준서 근거는 [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) 참조.

탐지 파이프라인은 **PHASE 1 (전수 필터/Recall) → PHASE 2 (family-specific 보조 lane)** 중심으로 운영한다.

- **PHASE 1**은 룰 기반 전수 필터다. 이 단계의 목적은 정답을 확정하는 것이 아니라, 1차로 규칙에 어긋난 항목을 가능한 한 모두 포착하는 것이다. 이후 중요성, 증거 강도, 정상 예외 가능성, 조합 신호를 기준으로 예외 처리 대상·리뷰 대상·진짜 위험 후보로 2차 분류한다.
- **PHASE 2**는 PHASE 1을 대체하지 않고, case 단위 우선순위를 구조적·통계적 모델로 보정한다. 룰 ID 자체를 예측 feature로 쓰지 않는다.
- **PHASE3 LLM Narrator**는 active detector layer가 아니다. Detection rules are PHASE1/PHASE2 only. Any future semantic description analysis must be local-first and must not transmit ledger evidence to external APIs. 단일 출처: [LOCAL_FIRST_EVIDENCE_POLICY.md](LOCAL_FIRST_EVIDENCE_POLICY.md), deprecated spec [PHASE3_REVIEW_NARRATOR_SPEC.md](../archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md).

---

## 1. 개요

### 1.1 프로젝트 목적

ERP에서 추출한 전표 CSV 데이터에 대한 **전수 검사(CAATs)** 자동화.
감사인이 후속 수작업을 수행할 때의 우선순위 추천을 제공한다.

### 1.2 탐지 아키텍처 — L1/L2/L3/L4 + 독립 트랙

```
L1 (확정 오류/명시 위반)     ─ 전표 품질 게이트, 즉시 정정·차단 가능한 항목
L2 (강한 검토 신호)         ─ 구체적인 통제 우회·중복·자금 유출 검토 패턴
L3 (검토 필요 이상징후)     ─ 사람 검토가 필요한 운영·맥락형 수상 신호
L4 (통계적 이상치)          ─ 분포·희소성·통계 기반 이탈 신호
Benford (독립 트랙)         ─ L4-02을 별도 가중치로 분리한 분포 수준 검정
Variance (독립 트랙)        ─ 기존회사 전용, 전기 engagement 대비 급변 탐지
```

### 1.3 52개 유형 → 채택 판정

DataSynth 52개 anomaly 유형을 3축 평가(법규 근거 × 실증 빈도 × 데이터 가용성)로 선별.
판정 방법론 상세는 [DETECTION_REFERENCE.md §4](DETECTION_REFERENCE.md#4-3축-평가-방법론) 참조.
아래의 `유형 수`는 DataSynth 원천 anomaly 유형 기준이며, 실제 Phase 1 구현 룰 수와 1:1로 대응하지 않는다. PHASE1-1은 Must 유형을 감사 검토 가능한 세부 룰로 확장해 현재 **30개 transaction/review row 카드**로 운영한다. L4-02 Benford macro와 L4-05 비정상시간 집중은 PHASE1-2 family로 이관되어 PHASE1-1 카드 수에서 제외된다. L3-12 업무범위 집중 검토는 L1-06과 분리된 review 룰로 둔다. 카운트 단일 출처는 [RULE_DETAIL_METADATA_V1_LOCK.md §Rule Count Policy](RULE_DETAIL_METADATA_V1_LOCK.md#rule-count-policy)다.

```
판정     유형 수   적용 단계   구현/운영 단위                       FSS 6대 패턴 커버
────────────────────────────────────────────────────────────────────────────────────
Must      20개    Phase 1    PHASE1-1 30 row 카드 + PHASE1-2 family/macro  6/6 (전부 커버)
Should    16개    Phase 2    ML/통계 확장                      가공전표·결산수정 정밀도↑
Could      5개    Future     local-only NLP/graph 검토 후보     순환거래 정밀도↑
Drop      11개    —          제외                              —
────────────────────────────────────────────────────────────────────────────────
합계      52개               Active PHASE1/PHASE2 중심 운영
```

---

## 2. Phase 1: 룰 기반 탐지 (PHASE1-1 30개 transaction/review row 카드)

이 절은 **30개 transaction/review row 카드**로 구성된다. row 카드는 `L1~L4` 전표 행 단위 구현 룰이다. L4-02 Benford macro(계정·월 단위 분포 검정)와 L4-05 비정상시간 집중은 2026-06-17 PHASE1-2 family로 이관되어 PHASE1-1 카드 수에서 제외된다. L3-12는 L1-06의 명시적 SoD 위반과 분리된 사용자 업무범위 집중 review 룰이며, 사용자 큐와 우선순위 해석은
[PHASE1_RULE_RELATIONSHIP_MAP.md](PHASE1_RULE_RELATIONSHIP_MAP.md)의 최신 관계도를 따른다.
따라서 `D01/D02` 같은 Variance macro-finding, `IC01~IC03` 관계사 대사 신호, `GR01/GR03`
그래프 신호는 위 30개 카드 수에는 넣지 않지만, Phase 1 결과 화면에서는 Account / Process Queue 또는
관계사·연결 구조 drill-down의 보조 finding으로 결합한다. 카운트 단일 출처는 [RULE_DETAIL_METADATA_V1_LOCK.md §Rule Count Policy](RULE_DETAIL_METADATA_V1_LOCK.md#rule-count-policy)이며, 레거시 문서의 "31/32/33 rules" 표현은 `PHASE1-1 30 row cards + PHASE1-2 family/macro` 로 normalize한다.

### 2.0 PHASE1 운영 기준

PHASE1은 **룰 기반 전수 필터**다. 개별 룰은 넓게 탐지하고, 사용자에게는 룰 결과표가 아니라 **감사 검토 큐 + 검토 이유 + 확인 절차**를 제공한다. PHASE1의 목적은 정답 라벨을 맞히거나 부정을 확정하는 것이 아니라, 규칙 위반·정책 위반·이상 징후 후보를 1차로 최대한 누락 없이 올리는 것이다.

따라서 PHASE1 raw hit에는 정상 예외, 업무상 타당한 거래, 단독으로는 약한 신호가 함께 포함될 수 있다. 운영 단계에서는 이를 그대로 최종 위험으로 보지 않고, 중요성 금액, evidence strength, case priority, 고객사 예외 정책, 다른 룰과의 조합 여부를 기준으로 2차 분류한다. 2차 분류 결과는 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보처럼 감사 행동 단위로 나뉜다. 최신 관계도 기준은 [PHASE1_RULE_RELATIONSHIP_MAP.md](PHASE1_RULE_RELATIONSHIP_MAP.md)를 따른다.

#### 2.0.1 결과 표현 계층

PHASE1 결과는 아래 4층으로 만든다.

| 층              | 대상                                   | 역할                | 감사인에게 노출         |
| --------------- | -------------------------------------- | ------------------- | ----------------------- |
| Rule Hit        | `L1-05`, `L3-04` 등                    | 원천 탐지 근거      | drill-down에서만 노출   |
| Evidence Type   | `control_failure`, `timing_anomaly` 등 | 의미 축으로 정리    | 케이스 태그와 주요 근거 |
| Case Priority   | `high`, `medium`, `low`                | 먼저 볼 순서        | 큐 정렬 기준            |
| Auditor Insight | 검토 초점, 위험 설명, 권장 확인 절차   | 실제 감사 행동 유도 | 메인 설명               |

룰별 `severity`는 최종 사용자 등급이 아니라 `evidence_score`와 `evidence_strength`의 입력이다. 예를 들어 `L3-08 적요 결손/파손`은 단독 `Low`로 노출하지 않고, `기말 수기 고액 전표에 적요 결손/파손이 보조 신호로 결합됨`처럼 case-level 의미로 표현한다.

#### 2.0.2 출력 큐

PHASE1 결과 큐는 탐지 단위에 따라 세 갈래로 나눈다.

1. **Transaction Queue**
   - L1~L4의 전표 행 단위 룰을 Theme Queue와 Case Group으로 묶는다.
   - 감사인이 실제 전표를 열어 승인·계정·금액·시점 맥락을 확인하는 기본 검토 큐다.
   - **tier 줄에는 HIGH/MEDIUM 전표만 세운다(A안, 2026-06-20).** 조합이 안 된 단일신호 전표(옛 LOW)는 review queue 줄에서 빼고 아래 3번 Coverage 큐로 보낸다. "고액·기말 단독" 같은 신호가 줄을 도배하는 노이즈를 막는다. 단위는 전표(document) — 한 전표 = 한 tier, 겹치지 않음. SoT: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §5.
2. **Account / Process Queue**
   - Benford, D01, D02처럼 계정·월·프로세스 단위에서 의미가 생기는 macro-finding을 보여준다.
   - 이상 계정/월을 클릭하면 해당 모집단 안에서 L1~L4 룰이 함께 걸린 전표를 drill-down으로 연결한다.
   - D01/D02는 Transaction Queue의 row/document-level precision·FP·FN 성과표에 넣지 않는다. 두 룰은 전표 1건의 오류나 부정을 직접 입증하지 않고, 전기 대비 분석적 절차에 따른 계정 단위 review population을 만드는 보조 분석 트랙이다.
   - 따라서 PHASE1 메인 리포트에서는 D01/D02를 `Analytical Review Signals` 또는 `Account Review Population` 섹션으로 분리하고, 계정 group 수, truth coverage, missed account group, normal-control review group, L1~L4 겹침 전표 수를 표시한다.
3. **Coverage Queue (룰별 전수 커버리지 — A안, 2026-06-20)**
   - HIGH/MEDIUM 조합에 안 엮인 단일신호 전표(옛 LOW)를 review queue 줄 대신 여기서 본다.
   - **룰별 커버리지 숫자표**: 각 룰이 전수에서 몇 건 떴는지 집계해 보여준다(예: 자기승인 320건 · 무효계정 45건 · 고액 1,200건). "전수 검사 했다"는 커버리지 증빙이자 어느 룰을 볼지 고르는 진입점이다. **카운트는 tier와 무관한 전수** — HIGH/MEDIUM 전표에 걸린 룰도 포함한다(전표는 한 tier에만 서지만 룰 발화는 전수 집계, "고액 거래 다 봤나"에 답하려면 HIGH로 간 고액도 세야 함).
   - **drill-down**: 숫자를 클릭하면 그 룰이 걸린 전표 목록이 나온다. 정렬은 Transaction Queue와 **동일한 공통 sort_key**(independent_primary_count → time_severity → rule_count → materiality, [PHASE1_TIER_SCORING_SPEC.md](PHASE1_TIER_SCORING_SPEC.md) §4)를 쓴다. 표시 컬럼은 각 룰의 `row_annotations` 근거 필드.
   - 자의적 "LOW 룰 선별"을 하지 않는다 — 룰별 건수(사실)와 공통 정렬(사실)만 제공하고, 어느 룰이 중요한지는 감사인이 정한다. SoT: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §5.
   - 보조축·booster·macro 단독(OFF-TIME·적요부실·라운드넘버·L3-03·D01/D02)은 CONTEXT라 Coverage Queue 단독 집계 대상도 아니다. 다른 primary가 떴을 때만 정렬·UI로 거든다.

사용자에게 노출하는 primary queue는 `Audit Risk`, `추가검토사항`, `조작 후보`, `맥락 검토대상` 같은 상태 표현을 쓰지 않는다. 공식 queue는 [TROUBLESHOOT.md TS-9](TROUBLESHOOT.md#ts-9-phase1-review-queue를-확실한-감사-주제로-재정렬)의 6개 감사 주제를 따른다(옛 7번째 `관계사·내부거래·순환구조`는 PHASE1-2 family로 이관, SoT [PHASE1_TIER_EVIDENCE_BASIS.md](PHASE1_TIER_EVIDENCE_BASIS.md) §7.3).

#### 2.0.3 레이어와 Evidence Type

| Evidence Type            | 포함 룰                                         | 기본 Primary Theme         |
| ------------------------ | ----------------------------------------------- | -------------------------- |
| `data_integrity_failure` | L1-01, L1-02, L1-08                             | 원장기록·데이터정합성      |
| `control_failure`        | L1-04, L1-05, L1-06, L1-07, L1-07-02, L3-02     | 승인·권한·업무분장 통제    |
| `access_scope_review`    | L3-12                                           | 승인·권한·업무분장 통제    |
| `duplicate_or_outflow`   | L2-01, L2-02, L2-03, L2-05                      | 중복·상계·자금유출         |
| `timing_anomaly`         | L3-04, L3-05, L3-06, L3-07, L3-08, L3-11, L4-05 | 결산·기간귀속·입력시점     |
| `logic_mismatch`         | L1-03, L2-04, L3-09, L3-10, L4-04               | 계정분류·거래실질 불일치   |
| `statistical_outlier`    | L4-01, L4-02, L4-03, L4-06                      | 수익·금액·모집단 통계 이상 |
| `intercompany_structure` | L3-03, IC01, IC02, IC03                         | → PHASE1-2 family (이관)   |

> `intercompany_structure` evidence type과 IC01~03·GR01/03은 PHASE1-1 6주제 점수경로에서 제거됐고, 관계사·내부거래·순환거래 구조 탐지는 PHASE1-2 family(graph/relational)가 담당한다(SoT §7.3). `L3-03`만 PHASE1-1 `logic_mismatch`(계정분류·거래실질 불일치) topic의 account_logic booster로 잔존한다. 아래 IC01~03·GR 서술은 family 탐지기의 동작 기준으로 읽는다.

`IC01~IC03`은 31개 L1~L4 룰 수에 포함하지 않는 관계사 보조 finding이다. `GR01/GR03`은 local graph 보조 신호이며 `L3-03` 케이스와 결합될 때 관계사·연결 구조 이상 우선순위를 높이는 보조 증거로 사용한다.

`L3-03` 단독은 관계사 거래 모집단을 넓게 잡는 약한 검토 신호다. 반면 별도 `IntercompanyMatcher` 결과로 제공되는 `IC01/IC02/IC03`은 대사 예외를 확인한 보조 finding이므로 row-level 대표 점수에서도 별도 floor를 적용한다. `IC02` 또는 `IC03` 단독 예외는 최소 Low, `IC01` 단독 예외는 `ic01_evidence_level`에 따라 Low/Medium을 나누며, 2개 이상 IC 예외 결합은 최소 Medium으로 표시한다.

구현상 `L2-03a~L2-03d`가 존재하더라도 외부 기준은 `L2-03 중복 전표` 하나로 본다. 세부 rule id는 정확 중복, 유사 중복, 분할 후보, 시차 중복을 구분하기 위한 내부 reason code이며 모두 `duplicate_or_outflow`에 속한다.

L2와 L3는 신호 성격으로 구분한다.

| 축        | L2 (강한 검토 신호)                         | L3 (검토 필요 이상징후)                    |
| --------- | ------------------------------------------- | ------------------------------------------ |
| 신호 성격 | 도메인 특화 패턴, 통제 우회, 중복·자금 유출 | 시간·텍스트·운영 맥락 이상                 |
| 대표 룰   | L2-01, L2-02, L2-03, L2-05                  | L3-04, L3-06, L3-08                        |
| 해석      | 부정 시나리오 1순위 검토                    | 정상 업무 변동 가능성까지 포함한 검토 후보 |

`L2-04`는 L2에 속하지만 사용자 노출과 점수 해석은 `logic_mismatch` evidence다. 즉 비용 자산화 오류를 확정하는 룰이 아니라, 자산/비용 계정 조합이 감사 검토 대상인지 판단하는 전수 필터다. `immediate` band만 confirmed rule hit로 `flagged_rules`에 남기고, `review`와 `low_review` band는 `review_rules` 및 PHASE1 case priority로만 흐르게 한다.

#### 2.0.3.5 룰 묶음 (Rule Sets)

여러 룰을 **하나의 의미 덩어리**로 묶어 조합·정렬·표시에 함께 쓰는 단위다. 개별 룰(L1~L4)과 별개로, 묶음은 "이 신호들이 같은 일을 한다"는 그룹이다. 현재 6개를 운영한다(조합 게이트 묶음 2: 승인우회·자금유출 / 보조축 묶음 3: OFF-TIME·적요부실·라운드넘버 / 품질 게이트 1: 데이터정합성). 묶음별 tier 참여 방식 SoT는 [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §2.

| 묶음                       | 멤버 룰                                                                                 | 하는 일 (역할)                                                                                                                                      | tier 참여                                                                                                                            |
| -------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **데이터정합성**           | L1-01 차대불균형 · L1-02 필수필드 누락 · L1-03 무효계정                                 | "데이터가 분석 가능한 상태인가"를 보는 품질 게이트. 부정 위험이 아니라 원장 신뢰성 문제.                                                            | **미산입** — case tier/queue 안 만들고 `data_integrity_findings`로만 노출                                                            |
| **승인우회 (bypass)**      | L1-04 한도초과 · L1-05 자기승인 · L1-06 직무분리 · L1-07 승인생략 · L1-07-02 유령승인자 | "승인 통제를 어떤 형태로든 회피했나"를 한 덩어리로 본다(AS2401 §61(b) 비인가자 기입). 회피의 구체적 형태(자기승인·생략·직무분리 등)를 OR로 묶음.    | **조합 게이트 leg** — HIGH-2(횡령은폐)·HIGH-5(승인우회)·MEDIUM-1(희소+승인우회)·MEDIUM-2(한도분할, L1-04 제외)의 통제 leg로 참여     |
| **자금유출 (outflow)**     | L2-02 중복지급 · L2-03 중복전표 · L2-05 역분개                                          | "돈이 빠져나가거나 되돌려지는 통로"를 한 덩어리로 본다(FSS 횡령은폐의 정의축). 승인우회(통제 회피)와 대칭되는 leg.                                  | **조합 게이트 leg** — HIGH-2(횡령은폐 `자금유출 & (승인우회\|수기+고액)`)·HIGH-3(가수금 `L3-09 & 자금유출 & 고액`)의 유출 leg로 참여 |
| **OFF-TIME**               | L3-05 주말·공휴일 · L3-06 심야 · L4-05 비정상시간 집중                                  | "사람이 근무시간 외에 입력했나"를 본다. 포렌식 실무상 high-severity 정황이나 수법의 정의는 아님.                                                    | **게이트 제외** — tier 발화 안 함. within-tier 정렬(`time_severity_score`)과 UI 배지 전용. L4-05는 작성자 맥락 연결(점수 병합 금지)  |
| **적요부실 (weak-desc)**   | L3-08 적요 결손/파손                                                                    | "전표 설명이 비었거나 깨졌나"를 본다(AS2401 §61(c) "little/no explanation"). 그 자체로 의심 정황이나 정상 전표도 적요가 흔히 비어 수법 정의는 아님. | **게이트 제외** — tier 발화 안 함. within-tier 정렬과 UI 배지 전용(OFF-TIME 보조축과 대칭). 점수 병합 금지                           |
| **라운드넘버 (round-num)** | PHASE1-2 라운드넘버 밀집도 macro (신규룰 예정)                                          | "둥근 금액(끝자리 0 다수)이 계정·월·작성자 모집단에서 비정상 집중인가"를 본다(AS2401 §61(e) round number). 단건 아닌 분포 신호.                     | **게이트 제외** — tier 발화 안 함. L4-05식으로 밀집 모집단 소속 case에 맥락 연결 → within-tier 랭킹·UI 배지. 점수 병합 금지          |

> 묶음 ≠ evidence_type(§2.0.3): evidence_type은 화면 의미 축이고, 묶음은 조합·정렬에 쓰는 룰 그룹이다. 승인우회 묶음은 evidence_type `control_failure`의 부분집합(L3-02 수기는 control_failure이나 승인우회 묶음 아님), OFF-TIME은 `timing_anomaly`의 부분집합(L3-04 기말·L3-11 컷오프·L3-07 소급은 timing이나 "거래 시점 귀속"이라 OFF-TIME 아님)이다.

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

| Primary Theme              | 기본 Case Key                   |
| -------------------------- | ------------------------------- |
| 원장기록·데이터정합성      | `회사 / 전표유형 / 적재배치`    |
| 승인·권한·업무분장 통제    | `사용자 / 프로세스 / 월`        |
| 중복·상계·자금유출         | `거래처 / 금액밴드 / 근접기간`  |
| 결산·기간귀속·입력시점     | `사용자 / 계정군 / 월말 윈도우` |
| 계정분류·거래실질 불일치   | `계정군 / 문서유형 / 월`        |
| 수익·금액·모집단 통계 이상 | `프로세스 / 계정군 / 월`        |

> 옛 `관계사·내부거래·순환구조` case group(`회사쌍 / 거래상대 / 월`)은 PHASE1-1에서 제거됨 → PHASE1-2 family(graph/relational)로 이관(SoT §7.3).

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
   - L1-01/L1-02/L1-03은 데이터 정합성 트랙이다. detector `score_series`는 발화/표시/정렬용 uniform flag `1.0`이며, row `HIGH/MEDIUM/LOW` tier와 case priority 산식에는 병합하지 않는다.
   - L3-12는 review-only access/work-scope signal이다. detector `details["L3-12"]`에는 확정 위반 점수를 넣지 않고, `review_score_series`와 `row_annotations.review_score`를 통해 row `anomaly_score`, `review_rules`, PHASE1 case priority에만 약하게 반영한다.
   - L3-12 원점수 `0.20~0.65`는 전용 단조 정규화를 사용한다. 더 높은 업무범위 review score가 PHASE1 `normalized_score`에서 낮은 점수보다 작아지면 안 된다.
   - L2-01은 binary flag 룰이다. 한도의 90~100% 구간이면 bucket과 무관하게 `1.0`이며, 자동·반복·배치 source도 제외하지 않는다. 구 `0.45/0.60/0.75` 밴드 점수와 전용 단조 정규화는 폐기됐다.
   - L3-07은 detector raw score `0.45/0.60/0.75`를 그대로 severity-weighted score로 재해석하지 않는다. PHASE1 정규화에서는 bucket label 기준 `moderate_gap=0.55`, `large_gap=0.75`, `extreme_gap=1.0` signal strength를 적용해 31~60일, 61~90일, 90일 초과 괴리의 우선순위가 뒤집히지 않게 한다.
   - L3-06은 weak timing signal이지만 detector raw band 순서는 PHASE1 전체 점수에서도 보존한다. 정상 시스템·배치 context `0.20`은 사람/미상 심야 입력 `0.45`보다 낮게 반영되어야 하며, L3-06 단독 hit는 row `Low/Medium/High` 승격 근거로 쓰지 않는다.
   - L3-10은 weak booster이지만 `priority_case > raw_signal > normal_control_candidate` 순서가 PHASE1 전체 점수에서도 유지되도록 전용 정규화를 적용한다. row `anomaly_score`에는 약하게만 기여하지만, `priority_case`는 case priority floor로 Medium 검토 후보에 올라간다.
   - L3-03은 관계사 계정 사용 binary context 태그(1/0)다. `evidence_strength=weak`, `standalone_rankable=False`로 단독 tier를 만들지 않으며, 조합 가중은 통합점수체계가 한다(구 raw `0.40` 정규화 폐기).
   - IC01/IC02/IC03은 L1~L4 룰 수에 포함하지 않는 관계사 보조 finding(PHASE1-2 family)이다. 대사 예외 점수·floor·`ic01_evidence_level` 정책은 [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD) §4.4 IC Matcher 소관이다.
2. **Case tier (순서형 — 가중합·band컷·priority_floor 폐기)**

   - 사용자 큐 정렬 기준이다. 구 가중합 priority_score(`0.25*control_score + …`)·band컷(`high≥0.90/medium≥0.75`)·룰별 priority_floor는 **폐기**됐다.
   - case tier는 켜진 red-flag 룰 **조합** + `has_rankable_primary` 게이트로 **HIGH/MEDIUM/LOW/CONTEXT** 순서형 등급을 직접 결정한다. primary+standalone 신호가 그 topic에 있어야 HIGH/MEDIUM이 발화하고, booster/combo_only/macro_only만 있으면 CONTEXT(큐 제외)다. 연속 점수는 같은 tier 내부 tiebreak로만 쓴다.
   - **LOW(A안, 2026-06-20)**: standalone primary 1개가 단독으로 떠 어느 HIGH/MEDIUM 조합에도 안 엮인 전표는 LOW다. LOW는 Transaction Queue tier 줄에 세우지 않고 **Coverage Queue(룰별 전수 커버리지 집계 + 공통 sort_key drill-down, §2.0.2 3번)**로만 본다. 등급 단위는 전표(document) — 한 전표 = 한 tier(겹치지 않음), `case`는 전표를 묶은 집계 뷰다. SoT: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §5 · [UNIT_MEASUREMENT_POLICY.md](UNIT_MEASUREMENT_POLICY.md).
   - 어떤 조합이 어떤 tier로 발화하는지(3축 근거 포함)의 SoT: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §3.0 발화표 · [PHASE1_TIER_SCORING_SPEC.md](PHASE1_TIER_SCORING_SPEC.md) · [PHASE1_TIER_EVIDENCE_BASIS.md](PHASE1_TIER_EVIDENCE_BASIS.md).
   - L1-01/L1-02/L1-03은 데이터정합성 트랙이라 case tier/queue를 만들지 않고 `data_integrity_findings`로만 노출한다(부정 tier 미산입).
   - L2-04 등 단독 High를 피해야 하는 룰은 booster/조합 경로로만 tier에 기여한다(룰별 floor 대신 scoring_role로 제어).

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

| 룰별 표현                               | `signal_strength` |
| --------------------------------------- | ----------------: |
| `critical`, `high`, `상`, `위험 높음`   |               1.0 |
| `medium`, `moderate`, `중`, `검토 필요` |               0.6 |
| `low`, `하`                             |               0.3 |
| `info`, `참고`                          |               0.2 |
| 단순 flag `True`                        |               1.0 |
| flag `False` 또는 `normal`              |               0.0 |

일부 룰은 detector raw score 자체가 bucket별 우선순위를 이미 표현하므로, 공통 numeric 변환 전에 rule-specific 정규화를 적용한다. `L2-01`은 더 이상 이 예외에 속하지 않으며, detector raw score가 `1.0/0.0`인 binary flag로 PHASE1 정규화에 들어간다. `L3-09`는 `0.45/0.60/0.75/0.80` aging score를 PHASE1 `logic_score`에 단조적으로 반영하기 위해 raw score를 severity factor로 다시 접지 않고 `raw_score * evidence_strength_factor` 형태로 보존한다. 따라서 90일 초과 장기체류가 60~90일 bucket보다 낮은 통합점수로 들어가지 않는다.

`evidence_strength`는 증거 자체의 설명력이다. `strong`은 직접 증거, `medium`은 독립 검토 증거, `weak`은 단독 결론보다 결합 시 유효한 보조 증거로 본다. `scoring_role`은 `primary`, `booster`, `combo_only`, `macro_only`로 나눈다. 예를 들어 `L3-08`은 `booster`, `L4-06`은 `combo_only`, `L4-02/D01/D02`는 transaction queue에서는 `macro_only`다.

일부 룰은 detector가 이미 세분화한 numeric score를 원인 순서로 사용하므로, label 복원식 대신 룰 전용 `signal_strength`를 사용한다. 예를 들어 `L3-07`·`L3-09`는 bucket 순서가 PHASE1 전체 점수에서 뒤집히지 않도록 별도 정규화한다. `L3-05`는 이 예외에 속하지 않으며, 주말/공휴일이면 `1.0`, 아니면 `0.0`인 binary flag로 PHASE1 정규화에 들어간다.

따라서 `L1-05 위험 높음`과 `L3-08 검토 필요`는 같은 "문자 라벨"로 더하지 않는다. 내부적으로는 각각 `display_label`, `signal_strength`, `severity`, `evidence_strength`, `scoring_role`, `normalized_score`를 분리 저장하고, 합산에는 `normalized_score`만 사용한다.

보정 신호:

| 보정값                   | 반영 기준                                                                                    |
| ------------------------ | -------------------------------------------------------------------------------------------- |
| `topside_bonus`          | 기말·승인 우회·비정상 계정 조합·고액·적요 결손/파손 결합                                     |
| `batch_combo_bonus`      | L4-06 배치 신호에 2~3개 이상 독립 evidence 축 결합                                           |
| `work_scope_combo_score` | L3-12 업무범위 집중 신호에 2~3개 이상 독립 evidence group 결합. L3-12 단독은 High floor 없음 |
| `weak_evidence_bonus`    | round number, weak description, rare account 같은 약한 증거가 독립 검토 신호와 결합          |

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

- 기본 화면: `priority_band`, `case_type`, `main_reason`, `review_focus`, `risk_narrative`, `recommended_audit_actions`. **tier 줄에는 HIGH/MEDIUM 전표만 노출(A안)** — LOW 단일신호 전표는 줄에서 빼고 Coverage 화면으로.
- **Coverage 화면(A안, 2026-06-20)**: 룰별 전수 커버리지 숫자표(룰마다 발화 건수, **tier 무관 전수** — HIGH/MEDIUM 전표에 걸린 룰도 카운트). 숫자 클릭 시 drill-down 전표 목록을 Transaction Queue와 **동일 공통 sort_key**로 정렬. "전수 검사 커버리지" 증빙. SoT [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §5.
- 케이스 목록: `case_priority` 기준 상위 N개 및 Theme별 상위 케이스
- 케이스 목록의 룰 수는 단일 `Rules` 숫자로만 보지 않고 `Direct`, `Review`, `Blocker`, `Macro` 네 개 신호 수로 나누어 표시한다.
- Drill-down: 전표 목록, 증거 태그, `rule_evidence_summary`, raw rule hit를 아래 네 섹션으로 분리한다.
  - `Direct Risk Signals`: `score_series` 기반 confirmed/immediate 위험 신호
  - `Review / Context Signals`: `review_score_series`, `booster`, `combo_only`, weak/context bucket
  - `Integrity / Coverage Blockers`: L1-01, L1-02, L1-08 같은 전표 정합성·탐지 가능성 문제
  - `Macro / Account Findings`: L4-02, D01, D02처럼 계정·모집단 단위에서 의미가 생기는 finding
- 개발자/검증 모드: 원천 룰 출력, row-level score, detector detail

#### 2.0.9 실행 시간 기준

2026-05-05 기준 PHASE1 기본 실행 범위는 `L1~L4 + L3-11 + Benford(L4-02) + D01/D02`다.
`L3-11`은 구현 위치가 `EvidenceDetector`지만, 기본 실행에서는 `EvidenceDetector(rule_ids=("L3-11",))`로 cutoff 룰만 실행한다.
`DuplicateDetector`, `Intercompany`, `Timeseries`, `Evidence`의 EV01/EV03 확장 룰은 기본 PHASE1 실행 경로에서 제외한다.

측정 기준은 DataSynth 2024 합성데이터 `journal_entries_2024.csv`다.

| 항목                  |                     측정값 |
| --------------------- | -------------------------: |
| 입력 규모             | 369,545행 / 106,993개 전표 |
| CSV load              |                    3.178초 |
| 2023 prior load/build |                    3.712초 |
| Feature 생성          |                    6.495초 |
| `layer_a`             |                    3.420초 |
| `layer_b`             |                   69.729초 |
| `layer_c`             |                   54.986초 |
| `benford`             |                    1.308초 |
| `layer_d` D01/D02     |                    5.188초 |
| Aggregate             |                    0.796초 |

운영 기준으로는 37만 행 규모의 PHASE1 전체 분석을 **약 2.5~3분**으로 본다.
반복 실행에서는 ingest/feature cache가 있으면 load와 feature 구간이 줄어든다.

주요 병목은 `layer_b`, `layer_c`이며, 특히 `layer_c` 내부 `L2-05`의
역분개/상계 rolling window 계산이 크다. 현재 기본값은 detector 병렬 실행을 끈다.
2024 측정에서 병렬 base detector 실행은 CPU/메모리 대역폭 경합으로 순차 실행보다 느렸고,
이 변경은 룰·임계값·후보군을 바꾸지 않으므로 품질 영향이 없다.

### 2.0.1 PHASE1-1 코드 정합 메타 (30개)

이 표는 PHASE1-1 카드의 구현 경로, severity, scoring 메타, 필요 컬럼을 현재 코드 기준으로 고정한다. 아래 개별 카드의 점수·운영 설명은 이 표의 코드 사실값을 전제로 읽는다. 점수 공식과 normalized 수치 재서술은 이 표의 범위가 아니다.

| 룰         | 구현                                                                                                                   | severity | scoring 메타                                                                                                                       | column_sources required/derived                                                                                                                                                                                                            |
| ---------- | ---------------------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `L1-01`    | `integrity_layer.py::_a01_unbalanced_entry`                                                                            | 5        | role=primary; topic=ledger_integrity; evidence=data_integrity_failure/strong; standalone=True                                      | required=document_id, company_code, posting_date, gl_account, debit_amount, credit_amount; derived=amount, evidence_summary, violation_details, imbalance_amount, debit_sum, credit_sum                                                    |
| `L1-02`    | `integrity_layer.py::_a02_missing_required`                                                                            | 2        | role=primary; topic=ledger_integrity; evidence=data_integrity_failure/medium; standalone=True                                      | required=document_id, company_code, posting_date, fiscal_year, fiscal_period, document_date, document_type, gl_account, debit_amount, credit_amount; derived=amount, evidence_summary, violation_details, missing_fields, missing_category |
| `L1-03`    | `integrity_layer.py::_a03_invalid_account`                                                                             | 3        | role=primary; topic=account_logic; evidence=logic_mismatch/medium; standalone=True                                                 | required=document_id, company_code, posting_date, document_type, gl_account; derived=amount, evidence_summary, violation_details                                                                                                           |
| `L1-04`    | `amount_features.py::add_exceeds_threshold`; `fraud_rules_feature.py::b03_exceeds_threshold`                           | 3        | role=primary; topic=approval_control; evidence=control_failure/strong; standalone=True                                             | required=document_id, company_code, posting_date, created_by, approved_by, business_process; derived=amount, evidence_summary, violation_details, approval_limit, difference_value, display_label                                          |
| `L1-05`    | `fraud_rules_access.py::b06_self_approval`                                                                             | 3        | role=primary; topic=approval_control; evidence=control_failure/strong; standalone=True; secondary=duplicate_outflow                | required=document_id, company_code, posting_date, created_by, approved_by, source, business_process; derived=amount, evidence_summary, violation_details, display_label, signal_strength                                                   |
| `L1-06`    | `fraud_rules_access.py::b07_segregation_of_duties`                                                                     | 4        | role=primary; topic=approval_control; evidence=control_failure/strong; standalone=True                                             | required=document_id, company_code, posting_date, created_by, approved_by, business_process; derived=amount, evidence_summary, violation_details, display_label, signal_class, toxic_pair                                                  |
| `L1-07`    | `fraud_rules_access.py::b09_skipped_approval`                                                                          | 4        | role=primary; topic=approval_control; evidence=control_failure/strong; standalone=True; secondary=duplicate_outflow                | required=document_id, company_code, posting_date, approved_by; derived=amount, evidence_summary, violation_details, display_label, signal_status                                                                                           |
| `L1-07-02` | `fraud_rules_access.py` (unknown_approver, b09에서 분리)                                                               | 4        | role=primary; topic=approval_control; evidence=control_failure/strong; standalone=True                                             | required=document_id, company_code, posting_date, approved_by; derived=approver_in_master, amount, evidence_summary, violation_details, display_label                                                                                      |
| `L1-08`    | `time_features.py::add_fiscal_period_mismatch`; `anomaly_rules_simple.py::c05_fiscal_period_mismatch`                  | 4        | role=primary; topic=closing_timing; evidence=data_integrity_failure/medium; standalone=True; secondary=ledger_integrity            | required=document_id, company_code, posting_date, fiscal_year, fiscal_period, document_date; derived=amount, evidence_summary, violation_details, expected_value, actual_value, difference_value                                           |
| `L2-01`    | `amount_features.py::add_is_near_threshold`; `fraud_rules_feature.py::b02_near_threshold`                              | 3        | role=primary; topic=duplicate_outflow; evidence=duplicate_or_outflow/medium; standalone=True; secondary=approval_control           | required=document_id, company_code, posting_date, created_by, approved_by, business_process; derived=amount, evidence_summary, violation_details, approval_limit, difference_value, anomaly_score                                          |
| `L2-02`    | `fraud_rules_groupby.py::b04_duplicate_payment`                                                                        | 3        | role=primary; topic=duplicate_outflow; evidence=duplicate_or_outflow/strong; standalone=True; floor=duplicate_reference_match      | required=document_id, company_code, posting_date, reference, auxiliary_account_number, auxiliary_account_label, debit_amount, credit_amount; derived=amount, evidence_summary, violation_details, counterparty, duplicate_group_id         |
| `L2-03`    | `fraud_rules_groupby.py::b05_duplicate_entry`                                                                          | 3        | role=primary; topic=duplicate_outflow; evidence=duplicate_or_outflow/medium; standalone=True                                       | required=document_id, company_code, posting_date, document_number, reference, gl_account, source; derived=amount, evidence_summary, violation_details, counterparty, duplicate_signature, duplicate_group_id                               |
| `L2-04`    | `fraud_rules_groupby.py::b11_expense_capitalization`                                                                   | 4        | role=primary; topic=account_logic; evidence=logic_mismatch/medium; standalone=True                                                 | required=document_id, company_code, posting_date, document_type, gl_account, business_process; derived=amount, evidence_summary, violation_details, amount, account_family, display_label, signal_status                                   |
| `L2-05`    | `anomaly_rules_reversal.py::c11_reversal_entry`                                                                        | 4        | role=primary; topic=duplicate_outflow; evidence=duplicate_or_outflow/medium; standalone=True                                       | required=document_id, company_code, posting_date, reference, lettrage, lettrage_date, gl_account; derived=amount, evidence_summary, violation_details, counterparty, reversal_pair_id, difference_value                                    |
| `L3-02`    | `fraud_rules_feature.py::b08_manual_override`                                                                          | 4        | role=primary; topic=approval_control; evidence=control_failure/medium; standalone=True                                             | required=document_id, company_code, posting_date, source, created_by, business_process, document_type; derived=amount, evidence_summary, violation_details, display_label, signal_status                                                   |
| `L3-03`    | `fraud_rules_access.py::b10_intercompany_review_signal`                                                                | 4        | role=booster; topic=account_logic; evidence=logic_mismatch/weak; standalone=False                                                  | required=document_id, company_code, posting_date, trading_partner, auxiliary_account_number, gl_account; derived=amount, evidence_summary, violation_details, counterparty, intercompany_pair, signal_status                               |
| `L3-04`    | `anomaly_rules_simple.py::c01_period_end_large`                                                                        | 3        | role=primary; topic=closing_timing; evidence=timing_anomaly/medium; standalone=True                                                | required=document_id, company_code, posting_date, fiscal_period, source, created_by, gl_account; derived=amount, evidence_summary, violation_details, is_period_end, display_label                                                         |
| `L3-05`    | `anomaly_rules_simple.py::c02_weekend_entry`                                                                           | 2        | role=booster; topic=closing_timing; evidence=timing_anomaly/weak; standalone=False; secondary=approval_control                     | required=document_id, company_code, posting_date, created_by, source, business_process; derived=amount, evidence_summary, violation_details, is_non_workday, holiday_flag, signal_status                                                   |
| `L3-06`    | `anomaly_rules_simple.py::c03_after_hours_entry`                                                                       | 2        | role=booster; topic=closing_timing; evidence=timing_anomaly/weak; standalone=False; secondary=approval_control                     | required=document_id, company_code, posting_date, created_by, source, business_process; derived=amount, evidence_summary, violation_details, posting_hour, after_hours_flag, signal_status                                                 |
| `L3-07`    | `anomaly_rules_simple.py::c04_backdated_entry`                                                                         | 3        | role=primary; topic=closing_timing; evidence=timing_anomaly/medium; standalone=True                                                | required=document_id, company_code, posting_date, document_date, created_by, reference; derived=amount, evidence_summary, violation_details, date_gap_days, difference_value, display_label                                                |
| `L3-08`    | `anomaly_rules_simple.py::c06_missing_or_corrupted_description`; `text_features.py::build_description_quality_profile` | 1        | role=booster; topic=ledger_integrity; evidence=timing_anomaly/weak; standalone=False; secondary=closing_timing                     | required=document_id, company_code, posting_date, line_text, header_text, gl_account, source; derived=amount, evidence_summary, violation_details, text_quality_flag, signal_status                                                        |
| `L3-09`    | `anomaly_rules_simple.py::c10_suspense_account`                                                                        | 3        | role=primary; topic=account_logic; evidence=logic_mismatch/medium; standalone=True                                                 | required=document_id, company_code, posting_date, gl_account, lettrage, lettrage_date; derived=amount, evidence_summary, violation_details, account_family, aging_days, unresolved_flag                                                    |
| `L3-10`    | `fraud_rules_access.py::b13_high_risk_account_use`                                                                     | 3        | role=booster; topic=account_logic; evidence=logic_mismatch/weak; standalone=False; secondary=approval_control, revenue_statistical | required=document_id, company_code, posting_date, gl_account, created_by, approved_by, source; derived=amount, evidence_summary, violation_details, account_family, sensitive_account_touch, priority_case                                 |
| `L3-11`    | `evidence_detector.py::registry L3-11`; `evidence_rules.py::ev02_cutoff_violation`                                     | 3        | role=primary; topic=closing_timing; evidence=timing_anomaly/medium; standalone=True                                                | required=document_id, company_code, posting_date, document_date, delivery_date, gl_account, reference; derived=amount, evidence_summary, violation_details, date_gap_days, cutoff_window, difference_value                                 |
| `L3-12`    | `fraud_rules_access.py::b14_work_scope_excess_review`; `fraud_layer.py::registry L3-12`                                | 3        | role=combo_only; topic=approval_control; evidence=access_scope_review/weak; standalone=False; secondary=duplicate_outflow          | required=document_id, company_code, posting_date, created_by, business_process, gl_account; derived=amount, evidence_summary, violation_details, work_scope_score, company_count, process_count                                            |
| `L4-01`    | `fraud_rules_feature.py::b01_revenue_manipulation`                                                                     | 5        | role=primary; topic=revenue_statistical; evidence=statistical_outlier/medium; standalone=True                                      | required=document_id, company_code, posting_date, document_type, gl_account; derived=amount, evidence_summary, violation_details, anomaly_score, z_score, percentile, population_key                                                       |
| `L4-03`    | `anomaly_rules_simple.py::c08_amount_outlier`                                                                          | 3        | role=primary; topic=revenue_statistical; evidence=statistical_outlier/medium; standalone=True                                      | required=document_id, company_code, posting_date, gl_account, source, local_amount; derived=amount, evidence_summary, violation_details, anomaly_score, z_score, percentile                                                                |
| `L4-04`    | `anomaly_rules_statistical.py::c09_rare_account_pair`                                                                  | 2        | role=primary; topic=account_logic; evidence=logic_mismatch/medium; standalone=True                                                 | required=document_id, company_code, posting_date, gl_account, business_process, source; derived=amount, evidence_summary, violation_details, account_pair, rarity_score, anomaly_score, account_family                                     |
| `L4-06`    | `anomaly_rules_batch.py::c13_batch_anomaly`                                                                            | 2        | role=combo_only; topic=revenue_statistical; evidence=statistical_outlier/weak; standalone=False                                    | required=document_id, company_code, posting_date, source, created_by, gl_account; derived=amount, evidence_summary, violation_details, upload_batch_id, batch_anomaly_score, anomaly_score                                                 |

### 2.1 L1: 확정 오류/명시 위반 (9개)

전표테스트의 전제조건. 이 검증을 통과해야 이후 탐지가 의미있음.

> **번호 ≠ 분류**: `L1~L4`는 탐지 레이어의 **내부 안정 키**(코드·DB·DataSynth 라벨에서 불변)일 뿐, 감사인에게 보이는 분류가 아니다. 의미 분류는 `evidence_type/topic/theme`와 트랙(§2.0.3·§2.0.5)이 담당한다. 따라서 같은 `L1` 안에도 성격이 다른 두 묶음이 있다:
> - **L1-01·L1-02·L1-03 = 데이터정합성 트랙** — 부정 tier가 아니라 데이터 품질 게이트. case queue/priority 미산입, `data_integrity_findings`로만 노출.
> - **L1-04~L1-08 = 통제·시점 신호** — 승인우회(L1-04/05/06/07/07-02)는 `control_failure`, 기간불일치(L1-08)는 `closing_timing`(+정합성 dual) topic으로 흐른다.
> rule_id 자체를 재명명하지 않는 이유: 키 변경은 15개 모듈·config·테스트·DataSynth 라벨·DB를 깨뜨리고 탐지상 이득이 없다(분류는 theme/track 레이어가 이미 수행).

#### L1-01 — 차대변 균형 (UnbalancedEntry) ✅ 【데이터정합성 트랙】

- **심각도**: 5
- **근거**: 240§32 복식부기 원칙. FSS 횡령은폐 수법(차대 불일치)
- **탐지 로직**: `abs(sum(debit) - sum(credit)) > tolerance` per document_id. 기본 허용 오차 1.0 (float 안전)
- **평가/라벨 기준**: L1-01은 원인 라벨이 아니라 구조 게이트다. DataSynth truth와 성능 평가는 `UnbalancedEntry` 라벨명만이 아니라 실제 전표 합계 불균형 여부를 L1-01 positive 기준으로 삼는다. 원인 라벨(`RoundingError`, `TransposedDigits`, `DecimalError`, `CurrencyError`, `ReversedAmount` 등)은 별도 audit issue로 유지할 수 있다.
- **row score**: flagged 행은 모두 `score_series = 1.0`이다. L1-01은 부정 tier 세기차등이 아니라 데이터 정합성 트랙이므로 이 값은 발화/표시용 uniform flag이며 row `HIGH/MEDIUM/LOW` tier와 case priority에는 병합하지 않는다.
- **정렬/표시 메타**:
  - `imbalance_amount = abs(sum(debit_amount) - sum(credit_amount))`
  - `debit_sum = sum(debit_amount)`
  - `credit_sum = sum(credit_amount)`
  - `_build_data_integrity_findings`는 L1-01을 `imbalance_amount` 내림차순 기준으로 노출한다.

- **구현**: `integrity_layer.py` → `_a01_unbalanced_entry()`
  - document_id별 groupby → diff 계산
  - NaN document_id는 개별 더미 키로 처리
  - `score_series`는 uniform `1.0`
  - `row_annotations`에는 `imbalance_amount`, `debit_sum`, `credit_sum`만 저장한다.
- **필요 피처**: `debit_amount`, `credit_amount`, `document_id`

#### L1-02 — 필수필드 누락 (MissingField) ✅ 【데이터정합성 트랙】

- **심각도**: 2
- **근거**: 240-A45(d) 계정번호 없이 입력. K-SOX 전표기록 통제
- **탐지 로직**: 필수(cat1∪cat2) 컬럼 중 하나라도 NULL 또는 공백 문자열이면 행 단위로 플래그한다.

| 카테고리 | 의미                     | 컬럼                                                                             | L1-02 플래그 |
| -------- | ------------------------ | -------------------------------------------------------------------------------- | ------------ |
| `cat1`   | 없으면 저널 성립 불가    | `document_id`, `gl_account`, `debit_amount`, `credit_amount`, `posting_date`     | 예           |
| `cat2`   | 없으면 일부 룰 실행 불가 | `company_code`, `fiscal_year`, `fiscal_period`, `document_date`, `document_type` | 예           |
| `cat3`   | 없어도 무방              | 위 10개 외 모든 컬럼                                                             | 아니오       |

- **row score**: flagged 행은 모두 `score_series = 1.0`이다. 누락 필드 수나 필드별 가중치로 세기차등하지 않는다.
- **row annotation**:
  - `missing_fields`: 누락된 cat1/cat2 필드 리스트
  - `missing_category`: cat1 누락이 하나라도 있으면 `1`, 아니면 `2`
- **PHASE1 case priority 반영**: L1-02는 데이터 정합성 트랙이다. 단독 hit는 위험 큐/floor 대상이 아니며, `_build_data_integrity_findings`에서 `missing_category` 오름차순(cat1 먼저)으로 노출한다.

- **구현**: `integrity_layer.py` → `_a02_missing_required()`
- **필요 피처**: `document_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_date`, `document_date`, `document_type`, `gl_account`, `debit_amount`, `credit_amount`
- **DataSynth 상태**: MCAR 2% 주입 추가됨, E2E 재검증 필요

#### L1-03 — 무효 계정 (InvalidAccount) ✅ 【데이터정합성 트랙】

- **심각도**: 3
- **근거**: 240-A45(a) 비경상·저사용 계정 + 315호 비정상계정. FSS 가공전표(미사용계정 악용)
- **탐지 로직**: `gl_account NOT IN chart_of_accounts`
  - CoA(계정과목표) 미제공 시 스킵
  - 공란/NULL 계정은 L1-03이 아니라 L1-02 필수필드 누락이 소유한다.
- **row score**: CoA에 없으면 flagged 행 모두 `score_series = 1.0`이다. 계정 코드 형태, placeholder 여부, 금액, 수기/기말 맥락으로 세기차등하지 않는다.
- **출력**: `row_annotations`에는 `gl_account`만 남긴다. `bucket`, `reason_code`, `context_reasons`, `document_amount`, `score_bands`는 사용하지 않는다.
- **구현**: `integrity_layer.py` → `_a03_invalid_account()`
- **필요 피처**: `gl_account`
- **DataSynth 상태**: `v126` 기준 CoA 밖 GL은 `InvalidAccount`가 소유한다. `MisclassifiedAccount`가 CoA 밖 GL을 사용해 L1-03을 오염시키는 케이스는 `0`건이며, `check_datasynth_required_truth.py`에서 승격 전 검증한다.

#### L1-04 — 승인한도 초과 (ExceededApprovalLimit) ✅ 【승인우회 트랙】

- **심각도**: 3
- **의미**: 승인자가 **자기 권한을 벗어나 승인**한 전표를 잡는다. 두 경우를 **모두** 본다:
  1. **한도 초과** — 승인자에게 한도가 있는데 전표 총액이 그 한도를 넘음
  2. **비승인권자 승인** — 직원 마스터에 **있는 실재 직원**인데 승인 권한이 없거나(`can_approve_je=false`) 한도가 설정되지 않은 사람이 승인함
  > 즉 "한도를 넘긴 승인"뿐 아니라 **"애초에 승인할 자격(한도)이 없는 실재 직원이 승인한 경우"도 L1-04가 잡는다.**
  > 단, **승인자 ID가 직원 마스터에 아예 없는(가짜·유령) 경우는 L1-04 아님 → L1-07-02 유령 승인자** 소관(실재 직원의 권한초과와 존재하지 않는 ID는 구분, 2026-06-19).
- **근거**: K-SOX 승인체계, ISA 240 §32. 승인권자가 권한 범위를 벗어나 승인하면 통제 실패·승인권한 위반.
- **판정 (binary flag — 점수 단계 없음)**
  - 전표 총액 = `max(SUM(debit_amount), SUM(credit_amount)) BY document_id`.
  - `approved_by`를 직원 마스터(`employees.json`)에 연결해 `approval_limit`·`can_approve_je`를 조회.
  - 아래 중 하나면 flag(균일):
    - ① 승인자 한도 존재 **AND** 전표 총액 > 한도
    - ② **명부에 있는 실재 직원**인데 승인 권한 없음(`can_approve_je=false`) **또는** 한도가 설정되지 않음 (= **한도 없는 사람의 승인**)
  - **`approved_by` 공란**이면 L1-04 아님 → **L1-07 승인 생략** 소관(승인자 부재와 권한초과는 구분).
  - **승인자 ID가 직원 마스터에 없음**(`approver_in_master=false`)이면 L1-04 아님 → **L1-07-02 유령 승인자** 소관. (구 L1-04 `approver_in_master` 가지는 L1-07-02로 이관 — 2026-06-19)
- **tier로 흐르는 길**: L1-04 단독은 통합점수에서 **LOW**(검토). 다른 행위신호(고액·역분개·수기·결산 등)와 **조합될 때만 HIGH**. (구 버킷 점수·단독 HIGH floor `approval_control_high` 폐기 — 2026-06-17)
- **파생 컬럼**: `document_approval_amount`(전표 총액), `approver_limit_amount`(한도, 미조회 시 null), `approval_limit_resolved`(조회 성공 여부), `approver_can_approve_je`(승인권한 여부), `approval_excess_amount`(초과액)
- **구현**: `src/feature/amount_features.py::add_exceeds_threshold` + `src/detection/fraud_rules_feature.py::b03_exceeds_threshold`. 직원 한도: `employees.json`의 `user_id`/`approval_limit`/`can_approve_je`.
- **필요 컬럼**: `document_id`, `debit_amount`, `credit_amount`, `approved_by`, `approval_limit`(마스터), `can_approve_je`(마스터)

#### L1-05 — 자기 승인 (SelfApproval) ✅ 【승인우회 트랙】

- **심각도**: 3
- **근거**: K-SOX 직무분리(외감법 §8①5호). 1인이 입력+승인을 모두 수행하면 통제가 뚫린다(FSS 오스템임플란트 사례).
- **판정 (binary flag — 점수 단계 없음)**
  - `created_by`·`approved_by`가 모두 있고 `created_by == approved_by`이면 자기승인 → flag(균일).
  - `approved_by` 공란이면 자기승인으로 추정하지 않음(승인 누락은 → **L1-07**).
  - 시스템 자동처리는 제외하되 **위장 의심 행은 제외하지 않는다**(아래 특별룰).
- **tier로 흐르는 길**: L1-05 단독은 통합점수에서 **LOW**(검토). 다른 행위신호와 **조합될 때만 HIGH**. (구 review/immediate/escalated 점수 분리·금액/시점/민감계정 승격 로직 폐기 — 그 신호들은 통합점수체계에서 각자의 룰 L4-03·L3-05/06·L3-10이 담당하므로 L1-05 안에서 중복 판단하지 않음)

- **특별룰 — 위장 시스템 전표 잡아내기 (`source_trust.lone_automated_mask`)**
  - 누군가 `source`를 'system/automated'로 적어 자기승인을 빠져나가려는 **위장**을 막는 안전장치. 다음이면 **위장 의심**으로 보고, 시스템 자동 예외(allowlist)를 적용하지 않고 일반 사람 자기승인으로 평가한다:
    - **자동 계열**(`automated`/`batch`/`interface`/`system`) **AND** [ `batch_id` **또는** `job_id`가 비어 있음 **OR** 같은 날 같은 부류(자동+식별자 없음) 전표가 **10건 이하로 외톨이** ]
  - 발상: **정상 자동 전표는 항상 무리지어 다닌다** — 시스템 배치는 `batch_id`/`job_id`를 달고 한 번에 대량으로 쏟아진다. 식별자도 없고 무리도 없는 외톨이 자동 전표 = 사람이 손으로 'system'이라 적은 위장 의심.
- **시스템 제외 (위장이 아닐 때만)**: `user_persona==automated_system` 또는 `source` allowlist(`patterns.self_approval_allow.sources`)면 점수 0(큐 제외). 위 위장 의심이면 이 제외가 취소된다.
- **구현**: `src/detection/fraud_rules_access.py::b06_self_approval` (+ `src/detection/source_trust.py::lone_automated_mask`)
- **필요 컬럼**: `created_by`, `approved_by`, `source`, (위장 판정용 `batch_id`/`job_id`/`posting_date`)

#### L1-06 — 직무분리 위반 (SegregationOfDutiesViolation) ✅ 【승인우회 트랙】

- **심각도**: 4
- **근거**: K-SOX 직무분리 / COSO·내부회계관리제도 원칙10. 양립불가능한 통제 기능이 한 사람에게 모이면 부정 기회·은폐 위험이 커진다.
- **무엇을 잡나 — 주입 라벨 폐기, 데이터에서 도출 (2026-06-17 재설계)**
  - **(구) 폐기**: `sod_violation`·`sod_conflict_type` 주입 컬럼을 그대로 읽던 방식. 실데이터엔 그 컬럼이 없어 0건, 합성데이터엔 정답 베끼기(순환)였다.
  - **(신)**: 전표 본래 3컬럼 — `created_by`(기표자)·`approved_by`(승인자)·`business_process`(업무) — 만으로 도출한다. 한 사람이 한 회기 내에 손댄 업무 집합이 **toxic 업무쌍**을 포함하면 발화.
  - 어떤 쌍이 toxic이고 왜인지(3축 근거 포함)는 **단일 출처** → [SOD_TOXIC_COMBINATIONS_GROUNDING.md](SOD_TOXIC_COMBINATIONS_GROUNDING.md). 데이터(SoT) = `config/sod_toxic_combinations.yaml`.
- **무엇이 RED인가 — 빼돌리기 + 숨기기**
  - 부정이 완성되려면 두 능력이 동시에 필요하다: **빼돌리기(custody — 현금·자산을 직접 만짐)** + **숨기기(recording/reconciliation — 그걸 장부에서 가림)**.
  - **RED = 한 사람이 빼돌리기 + 숨기기를 둘 다 가짐.** 가져가고 동시에 덮을 수 있어 통제 결함이 중대 → L1-06 **정식 발화(primary)**. 단독은 통합점수 **LOW**(검토), 행위신호와 **조합 시 HIGH**.
  - **YELLOW = 둘 중 하나만**(자산 못 만짐 / 못 숨김 / 저유동 자산). 반쪽 결함이라 **점수 미참여 — 리뷰 노트로만 기록**(단독으로 큐에 안 뜸).
  - 분류: **RED 8** (TRE+P2P·TRE+R2R·TRE+O2C·O2C+R2R·H2R+TRE·A2R+R2R·P2P단독·TRE단독), **YELLOW 4** (P2P+R2R·H2R+R2R·A2R+TRE·MFG+R2R). 각 쌍의 빼돌리기/숨기기 분해는 SOD doc의 RED/YELLOW 절.
  - ⚠️ **추정 단정 금지**: toxic 쌍 발화는 "이 사람이 가짜 거래를 만들었다"는 부정 확정이 아니라 **"빼돌리고 숨길 수 있는 통제 결함이 있다 → 감사인이 봐야 한다"** 는 신호다.
- **탐지 단위**: person = `created_by`(자기승인 `created_by==approved_by`면 승인자도 동일인 집합). 회기 내 `business_process` 집합이 toxic 쌍 포함 시 해당 프로세스 행 flag.
- **자동/시스템 계정 제외 (사람 행위만 SoD 대상)**
  - 직무분리는 **사람**에 대한 통제다. 자동 배치·인터페이스는 분리할 직무 자체가 없으므로(프로그래밍된 전기일 뿐) SoD 모집단에서 제외한다. 시스템 계정을 포함하면 "한 배치 계정이 모든 업무를 찍음 → 전 프로세스 toxic"으로 **전수 오탐**이 난다.
  - 제외 기준(`patterns.sod_human_filter`): ① `user_persona == automated_system`, ② `source`가 시스템 계열(`automated`/`interface`/`system`/`batch`), ③ `created_by`가 시스템 actor 토큰 포함(`batch`/`system`/`auto`/`interface`/`if_`/`svc_`/`_svc`). 셋 중 하나라도 해당하면 toxic 쌍 판정에서 빠진다.
  - 사람 식별 컬럼(`user_persona`/`source`)이 없으면 보수적으로 사람 행위로 본다(필터는 있는 신호로만 좁힌다). 식별자 표기 정규화·예외는 향후 과제.
- **경계 (다른 룰과 중복 금지)**
  - 단순히 한 사람이 여러 업무를 본다(업무범위 넓음)는 것은 L1-06 아님 → **L3-12 업무범위 집중**.
  - 자기승인(L1-05)·승인생략(L1-07)·수기(L3-02)를 근거로 L1-06을 발화하지 않는다(각자 소관). L1-06은 독립적 toxic 쌍 구조만 본다.
- **구현**: `src/detection/fraud_rules_access.py::b07_segregation_of_duties` — YAML toxic pair를 데이터에서 도출. RED → `score_series=1.0`(primary). YELLOW → `score_series=0.0` + `row_annotation`에 `toxic_pair`·`signal_class` 기록(노트).
- **필요 컬럼**: `created_by`, `approved_by`, `business_process` (+ `config/sod_toxic_combinations.yaml`)

#### L1-07 — 승인 생략 (SkippedApproval) ✅ 【승인우회 트랙】

- **심각도**: 4
- **근거**: K-SOX 승인절차(외감법 §8②). FSS 오스템임플란트: 한도초과+승인없음 = §8② 직접 위반.
- **판정 (binary flag — 점수 단계 없음)**
  - `approved_by`가 **공란**이면 flag(균일). 승인 도장 없이 장부에 들어온 전표.
  - `approved_by` 컬럼 자체가 없으면 승인 생략으로 추정하지 않고 skip/coverage degraded로 본다(컬럼 부재 ≠ 승인자 누락).
  - 공란이면 **무조건** flag한다 — 시스템·반복 전표의 공란까지 포함. 승인불요·사전승인·대체승인 가능성으로 룰 안에서 점수를 차등하지 않고, 단독은 통합점수 LOW로 흡수되게 둔다(구 7컴포넌트 가중합·즉시/검토/낮음 밴드·critical/high/review/low score band·case floor 전부 폐기 — 2026-06-19).
- **tier로 흐르는 길**: L1-07 단독은 통합점수에서 **LOW**(검토). 승인우회 그룹의 primary로서 다른 행위신호와 **조합될 때만 HIGH** — `approval_bypass_high`·`embezzlement_concealment_high`의 bypass seed `(L1-04|L1-05|L1-06|L1-07|L1-07-02)`에 속한다.
- **구현**: `src/detection/fraud_rules_access.py::b09_skipped_approval`
- **필요 컬럼**: `approved_by`

#### L1-07-02 — 유령 승인자 (UnknownApprover) ✅ 【승인우회 트랙】

- **심각도**: 4
- **무엇을 잡나**: `approved_by`가 **비공란인데 그 ID가 직원 마스터(`employees.json`)에 없는** 행. 존재하지 않거나 퇴사한, 또는 가짜로 적힌 ID를 승인자로 기입해 승인통제를 회피한 전표.
- **L1-07과의 차이**: L1-07(공란)은 승인을 **빠뜨린 것**(omission), L1-07-02(가짜 ID)는 없는 이름을 **적어 넣은 것**(fabrication) — "숨기기" 성격이 강한 위조 신호다. 그래서 별도 rule_id로 분리해 위조 전용 조합에 쓸 수 있게 한다(2026-06-19 신설, 구 L1-07 `unknown_approver` 서브패턴 승격).
- **판정 (binary flag — 점수 단계 없음)**: feature `approver_in_master`(`amount_features._compute_approver_info` — `employees.json`의 `user_id` 멤버십; 공란→NA, 비공란인데 미존재→False)가 False **∧** `approved_by` 비공란이면 flag(균일). 구 고정 `0.55` 검토점수 폐기. 직원 마스터가 없으면 컬럼 미생성으로 graceful 비활성(L1-07 공란 경로는 불변).
- **tier로 흐르는 길**: 단독은 통합점수 **LOW**(검토). 승인우회 그룹의 primary로 `(L1-04|L1-05|L1-06|L1-07|L1-07-02)`에 합류 → 다른 행위신호와 **조합 시 HIGH**. 위조 성격상 역분개(L2-05)·가공거래·기말조정과 결합될 때 우선한다.
- **L1-04와의 경계 (중복 발화 방지)**: 한도검사(L1-04)는 **명부에 있는 실재 직원**의 권한/한도 위반만 본다. **명부에 아예 없는** 가짜 ID는 L1-04가 아니라 L1-07-02 소관이다. L1-04의 `approver_in_master` 가지는 L1-07-02로 이관한다(2026-06-19).
- **운영 해석**: 부정 확정이 아니라 승인권자 명부와 대조할 검토 후보다. 퇴사자·외부 컨설턴트·표기 차이(대소문자)·마스터 부분추출로 정상일 수 있으므로 annotation에 승인자 값을 노출해 감사인이 대조·종결하게 한다(합성데이터에선 0건). 시점 정합(마스터 유효기간)·표기 정규화는 향후 과제(OPEN_ISSUES #19).
- **구현**: `src/detection/fraud_rules_access.py` — `unknown_approver` 전용 판정(L1-07 `b09_skipped_approval`에서 분리). 파생: `src/feature/amount_features.py::_compute_approver_info`의 `approver_in_master`.
- **필요 컬럼**: `approved_by`, 파생 `approver_in_master`(`employees.json` 필요)

#### L1-08 — 기간 불일치 (WrongPeriod) ✅

- **심각도**: 4
- **근거**: 240§32(b) 기간귀속 적정성
- **이중 트랙 (정합성 + 부정)** — L1-08만 양 트랙에 싣는다
  - 같은 표면신호(`fiscal_period_mismatch=True`)가 두 원인을 가린다: ① 오타·ERP 매핑 오류(의도 없음) ② 의도적 기간 조작(cutoff). 플래그만으로는 구분 불가하므로 한 플래그를 두 surface가 다르게 소비한다. L1-01(차대불일치)·L1-02(필수필드)는 부정 조합 의미가 약해 정합성 단독이지만, 기간불일치는 cutoff fraud의 정통 수법이라 L1-08만 dual이 정당하다.
  - **정합성 트랙 (raw 전수)**: 결산조정·특수기수 포함 **raw mismatch 전부**를 데이터 품질·coverage 지표로 집계한다. "기간 귀속 점검 필요" 경고이며 **부정 priority_score에는 합산하지 않는다**(별도 surface·집계). `Integrity / Coverage Blockers`(L1-01·L1-02와 동일 묶음)로 표시.
  - **부정 트랙 (정책예외 제외 final)**: 결산조정·특수기수(`13~16`)처럼 정책으로 확인된 합법 예외를 제외한 **final mismatch만** `closing_timing` topic의 seed로 쓴다. `period_end_adjustment_high (L3-04|L3-07|L3-11|L1-08) & (L3-08|L3-10|L4-04)`의 seed이며, **단독으로는 HIGH/MEDIUM을 만들지 못하고**(조합 없으면 부정 LOW), 반드시 2차신호(`L3-08|L3-10|L4-04`) 동반 시에만 HIGH로 발화한다.
  - **이중계산 아님**: 정합성=전수 행 집계(품질지표, priority_score 미유입), 부정=per-case 조합 기여. 플래그는 한 번 켜지고 소비자 둘이 다른 입도로 읽을 뿐 같은 점수를 두 번 더하지 않는다.
  - **라벨 분리 가드**: "데이터 품질: 기간귀속 점검"(정합성)과 "부정후보: cutoff 조작"(부정)을 같은 화면에서 섞지 않는다. 감사인이 오타를 조작으로 오인하지 않도록 surface·큐 라벨을 분리한다.
  - **binary 정합**: L1-08은 이미 `True/False` 단일 플래그라 점수 버킷이 없다. dual-track은 "점수를 나눈다"가 아니라 "같은 binary 플래그를 두 surface가 다르게 소비한다"이므로 binary 원칙과 충돌하지 않는다. raw/final의 차이는 점수 차등이 아니라 **정책예외 필터 적용 여부**다.
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

---

### 2.2 L2: 강한 통제우회·자금유출 검토 신호 (5개)

#### L2-01 — 승인한도 직하 (JustBelowThreshold) ✅

- **심각도**: 3
- **근거**: 240-A45(e) 단수/끝자리, K-SOX 승인체계
- **의미**: 승인 대상 금액이 결재권자의 승인 한도에 근접해 있을 때, 우연한 분포라기보다 승인 기준을 의식해 금액이 맞춰졌을 가능성을 살펴보는 룰이다. 이 룰 하나만으로 우회라고 단정하지 않고, 승인 정책과 업무 맥락을 함께 본다.
- **임계값 성격 (정직 표기)**: `near_threshold_ratio` 기본값 `0.90`은 **감사기준이 정한 회귀 기준이 아니라 튜닝 가능한 스크리닝 휴리스틱**이다. 원리(한도 직전 금액 맞춤 = 구조화 회피)는 ISA 240 A45(e)·ACFE 패턴에 근거하지만 "90%"라는 컷 자체는 임의값이며, engagement 승인한도 구조에 맞춰 조정한다. 더 통계적인 **"한도 직하 거래 밀집도(density spike) 검정"**(기대 분포 대비 한도 직하 구간 건수 스파이크)은 전표 단위 flag가 아니라 모집단 단위 분석이므로 **PHASE1-2 MACRO에 추후 반영 예정**이다(SoT [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD)).
- **판정 방식**
  - 같은 `document_id`의 `max(SUM(debit_amount), SUM(credit_amount))`로 전표 승인 대상 금액을 계산한다.
  - 전표의 `approved_by`를 직원 마스터(`employees.json`)와 연결해 해당 승인자의 `approval_limit`를 조회한다.
  - 전표 총액이 그 승인자의 한도에 충분히 가깝지만 아직 넘지 않은 경우, 즉 `approval_limit × near_threshold_ratio <= 전표 총액 < approval_limit` 이면 `JustBelowThreshold`로 본다.
  - 기본 `near_threshold_ratio`는 `0.90`이다. 실무 해석으로는 "승인 한도의 90% 이상 100% 미만 구간"이다.
- **Fallback 원칙**
  - fallback은 사용하지 않는다.
  - `approved_by`가 없거나 직원 마스터 조인에 실패해 실제 `approval_limit`를 알 수 없는 행은 `L2-01`로 판정하지 않는다.
  - `document_id`, `debit_amount`, `credit_amount` 중 하나가 없어 전표 단위 승인 대상 금액을 계산할 수 없는 행도 line-level 금액으로 대체하지 않는다.
  - 이런 행은 부정 판정 결과가 아니라 "승인한도 검증 불가"라는 커버리지/데이터 품질 이슈로 별도 관리한다.
- **판정 (binary flag — 점수 단계 없음)**
  - `한도 × near_threshold_ratio ≤ 전표총액 < 한도`이면 **flag 1.0**(균일). 구 3밴드(`lower_band 0.45`/`close_band 0.60`/`razor_band 0.75`)와 전용 정규화(`0.60/0.80/1.00`)는 **폐기**한다 — 한도의 90%든 99%든 "한도 의식해 맞춤"이라는 신호는 동질이고, 근접도 차이는 같은 tier 내부 tiebreak(연속 점수)로만 본다.
  - **자동/배치 전표도 한도 직하면 flag 1.0으로 발화한다.** "source가 automated/batch라서 정상"이라는 정상성 판단은 룰이 하지 않는다 — source/수기 차원은 `L3-02`(수기 전용 룰)와 통합점수체계 소관이고, 통합점수가 `한도직하 + 자동 source`를 정상으로 다운웨이트한다(룰은 멍청하게).
  - 한도 조회 실패 행은 hit 아님(아래 Fallback 원칙).
  - 단독은 통합점수 **LOW**(검토). 동일 거래처·근접기간 반복, L2-03 분할 후보, L1 승인통제 이슈, 수기·기말 신호와 **조합 시 HIGH**.

- **추가 파생 컬럼**
  - `near_threshold_amount`: 전표 단위 승인 대상 금액. `max(SUM(debit_amount), SUM(credit_amount)) BY document_id`로 계산한다.
  - `near_threshold_limit_amount`: 승인자의 실제 승인한도. 조회 실패 시 null
  - `near_threshold_limit_resolved`: 승인자 한도 조회 성공 여부
  - `near_threshold_ratio_to_limit`: 승인 대상 금액 / 승인한도
  - `near_threshold_gap_amount`: 승인한도까지 남은 금액
  - `near_threshold_gap_ratio`: 승인한도까지 남은 비율
- **한 줄 규칙**: `approval_limit(approved_by) × 0.9 <= max(SUM(debit_amount), SUM(credit_amount)) BY document_id < approval_limit(approved_by)`
- **구현**
  - 피처 생성: `src/feature/amount_features.py` → `add_is_near_threshold()`
  - 룰 적용: `src/detection/fraud_rules_feature.py` → `b02_near_threshold()`
    - `score_series`: flag 1.0 (binary, 밴드 점수 폐기)
    - `breakdown`: flagged rows, unresolved limit rows
    - `row_annotations`: amount, limit, ratio, gap
- **필요 컬럼**
  - 피처 생성: `document_id`, `debit_amount`, `credit_amount`, `approved_by`, 직원 마스터 `approval_limit`
  - 룰 적용: `is_near_threshold`
  - 설명 출력: `near_threshold_amount`, `near_threshold_limit_amount`, `near_threshold_ratio_to_limit`, `near_threshold_gap_amount`, `near_threshold_gap_ratio`
- **DataSynth 상태**: `v24_candidate`에서 `approved_by.approval_limit` 기준 라벨로 보정했다.

#### L2-02 — 중복 지급 (DuplicatePayment) ✅

- **심각도**: 3
- **근거**: 240§32 적정성. FSS 횡령은폐: 동일건 이중지급
- **한 줄 설명**: 같은 매입처에 같은 돈을 또 보냈는지 찾는 룰
- **현재 성격**: PHASE1 recall 우선 스크리닝 룰이다. 확정 부정 판정이 아니라 "검토해야 할 지급쌍"을 올린다.
- **PHASE1 탐지 순서**
  1. 지급성 전표 범위를 좁힐 수 있는 컬럼이 있으면 사용한다. `business_process`가 있으면 `P2P`만 보고, `document_type`이 있으면 `KZ` 또는 `KR`만 본다. 둘 다 있으면 `P2P + (KZ/KR)`만 본다. 둘 다 없으면 입력 coverage degraded 상태로 보고 가능한 지급 후보 모집단을 넓게 스크리닝한다.
  2. 거래처 키는 `auxiliary_account_number`를 우선 사용하고, 없으면 `trading_partner`, `vendor_name` 등 대체 컬럼으로 보완한다.
  3. 전표 라인 단위가 아니라 `document_id` 단위로 요약한다. 같은 전표 안의 차변/대변 라인은 중복 지급으로 보지 않는다.
  4. `reference`가 있으면 강한 신호로 본다.
     - 같은 회사/거래처 + 정규화한 `reference` + 거의 같은 금액 + 다른 `document_id`
     - 금액 허용오차는 `min(금액의 2%, 100,000원)`이다. 최소 허용오차는 1원이다.
     - 이 경로는 reference가 같은 청구/증빙을 다시 지급한 가능성을 잡기 위한 것이다.
  5. `reference`가 없으면 게이트를 걸어 fallback 한다.
     - 같은 회사/거래처 + 유사 금액(`min(2%, 100,000원)` 허용오차) + 다른 `document_id` + **90일 이내** 재지급이면 후보로 올린다.
     - (구) blank fallback의 정확 금액(±0) 제약은 **폐기** — 부분지급·수수료 차이로 살짝 다른 재지급도 잡기 위해 강신호와 동일한 ±2% 허용오차를 쓴다.
  6. 단, 같은 거래처/유사 금액이 월 단위로 규칙적으로 3번 이상 반복되면 정기성 지급(균등 분할 시리즈 포함) 가능성이 높다고 보고 fallback에서 제외한다.
- **해석 기준 (강/약 — 점수는 동일 1.0, 게이트만 다름)**
  - **강신호**(`reference` 연결): 같은 청구서를 다시 지급한 가능성에 가까운 강한 중복 신호. **같은 송장 재지급은 시점과 무관하므로 윈도우를 적용하지 않는다.**
  - **약신호**(`reference` 연결 없음): 우연 동액·정기지급 가능성이 있어 90일 윈도우 + 비정기 게이트로 좁힌다.
  - 결과 화면에서는 "중복 확정"이 아니라 "중복 지급 의심 후보"로 노출한다.
- **출력 방식**
  - `L2-02`는 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
  - `row_annotations`에는 `reason_code`, `confidence`, `confidence_band`, `matched_document_id`, `partner_key`, `reference_norm`, `amount`, `matched_amount`, `day_gap`을 기록한다.
  - `breakdown`에는 `reference_match_docs`, `mixed_reference_fallback_docs`, `blank_reference_fallback_docs`, `amount_partner_fallback_docs`, `recurring_suppressed_docs`, `partner_key_coverage_ratio`를 기록한다.
  - 거래처 식별자 coverage가 낮으면 `FraudLayer.metadata["coverage_issues"]`에 `partial_input_coverage`로 남기며, 결과 해석은 degraded 상태로 본다.
- **판정 (binary flag — confidence band 폐기)**
  - 아래 경로 중 하나면 모두 **flag 1.0**(균일). 구 5단계 confidence(`reference_match 0.90`/`mixed 0.70`/`amount_partner 0.65`/`blank 0.60`)는 **폐기**한다.
  - **강신호 (송장번호 연결, 윈도우 무관)**: `reference_match`(양쪽 같은 reference + 유사금액 + 다른 전표) 또는 `mixed`(원지급 reference 有 + 재지급 비움).
  - **약신호 (송장번호 연결 없음, 게이트 적용)**: `amount_partner`(reference 서로 다름) 또는 `blank`(둘 다 없음). 같은 회사/거래처 + 유사금액(±2%) + 다른 전표 + **90일 이내** + **비정기**(recurring 아님) 를 모두 충족할 때만 발화.
  - `recurring_suppressed`: 월 3회+ 규칙 반복(균등 분할 포함)은 정기지급으로 보고 **제외(flag 0)**.
  - reason code(reference_match/mixed/amount_partner/blank)는 내부 근거·화면 표시용으로 유지하되 **점수는 1.0 단일**(단일 primary, 역할 충돌 없음).
- **tier로 흐르는 길**
  - L2-02 단독은 통합점수 **LOW**(중복지급 검토 후보). 구 confidence 정규화·`reference_match` Medium floor(`0.45`)는 **폐기** — band별 점수 차등 대신 binary flag 후 **조합으로 tier 결정**.
  - 다른 신호(L1 승인통제·수기·역분개·동일 거래처 근접기간 반복)와 **조합 시 HIGH**(`duplicate_or_outflow`/`embezzlement_concealment` 경로).
  - **구현 반영**: fallback 발화 경로는 통합 루프(`b04_duplicate_payment` 내). 같은 (회사·거래처)에서 document_id가 다르고 **90일 이내**인 후행 문서를 선행 reference 상태로 분기 — 선행 ref 有+후행 공백=`mixed`, 두 ref 다름=`amount_partner`, 둘 다 공백=`blank`(모두 `min(2%,10만원)` 허용오차). 정기 반복(`_l202_recurring_profile`)은 `recurring_suppressed`로 제외. 모든 발화 경로 score 1.0.
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
- **해석 (재정의 2026-06-19 — 명백한 재기표만)**
  - L2-03은 "같은 거래가 두 번 장부에 들어온 **명백한 재기표**"만 잡는다. 정상 영업에서 **드문** 패턴만 남기고, fuzzy 유사·분할처럼 정상이 흔한 패턴은 제외한다(아래).
  - 판별 원칙: 정상에서 흔한 신호(near/분할)는 부정도 쓰지만 정상이 압도적이라 단독 primary 불가 → 폐기/이관. 정상에서 드문 신호(증빙 재기표·완전 복제)만 단독 발화한다.
- **판정 (binary flag — confidence band 폐기)**
  - `fraud_rules_groupby.py` → `b05_duplicate_entry()`. 아래 둘 중 하나면 **flag 1.0**. 구 5종 reason code 중 near/document/split 제거.
    - **(가) 증빙 재기표**: 다른 `document_id` + 같은 `reference` + 같은 `gl_account` + **같은 부호** + 유사 금액(±2%). = 같은 송장을 두 번 기표.
    - **(나) 완전 복제**: 다른 `document_id` + `gl_account`·금액·`posting_date`·거래처·적요·**부호**가 **전부 동일**. = 전표 행을 통째로 복제.
  - **가드(reference 비고유 데이터)**: `reference`가 송장번호가 아니라 배치ID·거래일 등 비고유 값이면 같은 번호가 대량 반복돼 (가)가 폭발한다. reference 반복률이 비정상으로 높으면 (가) 경로를 비활성한다.
  - **폐기**: `near_duplicate`(fuzzy "비슷함" — 정상 거래가 천지라 단독 불가), `document_duplicate`(구조 유사 — 정형 반복 전표와 혼동; reference 일치 시 (가)에 흡수되므로 별도 불필요).
  - **PHASE1-2 이관**: `split_duplicate`(분할 회피)는 한 건만 보면 정상이고 **여러 전표를 묶어 합산해야** 패턴이 드러나는 **구조 단위** 신호다. PHASE1-1 행 단위 결정론 룰이 아니므로 **PHASE1-2 구조화(structuring) 후보로 이관**한다 — 한도 직하 밀집도 macro와 같은 계열(SoT [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD)).
- **tier로 흐르는 길**
  - L2-03 단독은 통합점수 **LOW**(재기표 검토 후보). 구 high/medium/low confidence band, `l203_high_confidence_corroborated` 보정, `priority_adjustments.duplicate_entry` floor(`0.85`/`0.08`/`0.45`)는 **폐기** — band별 점수 차등 대신 binary flag 후 **조합으로 tier 결정**.
  - 통제 실패(L1)·결산/시점 이상(L3)·계정 논리 이상·관계사 구조 같은 독립 신호와 **조합 시 HIGH**(`duplicate_or_outflow`/`embezzlement_concealment` 경로).
- **운영 원칙**
  - 외부 노출 라벨은 계속 `L2-03 중복 전표` 하나로 유지한다.
  - UI, export, review queue에는 `reason_code`((가)/(나)), 핵심 근거 필드(`reference`, 거래처, 금액, 날짜, 적요)를 함께 제공한다(구 confidence 표기 폐기).
  - 정상 반복 전표·내부거래·정산성 전표는 (가)(나) 정의(같은 부호·전부 동일·증빙 일치)상 대부분 자연 배제된다.
  - `P2P/KZ` 지급성 전표가 함께 걸리면 `L2-02 duplicate payment`와 병합 설명을 제공한다.
- **Phase 2 pair similarity artifact**
  - `DuplicateDetector.detect()`는 row scoring 후 [`build_duplicate_pair_artifact`](../../src/detection/duplicate_pair_features.py)를 호출해 `result.metadata["pair_artifact"]`에 bounded·sanitized pair payload를 주입한다. row score 식과 `details`/`rule_flags`/`scores` contract는 변동 없음 (KPI baseline 회귀 0).
  - 대용량 입력이 `duplicate_pair_artifact_max_rows`를 초과하면 artifact를 전부 비우지 않고, duplicate row score가 실제로 발생한 review candidate row를 bounded subset으로 잡아 동일 pair generator를 다시 실행한다. 이 경로도 left/right pair evidence가 생성된 경우에만 native DuplicateCase 후보가 된다.
  - metadata top-N 보존은 document diversity cap을 적용한다. 동일 문서 또는 동일 문서쌍의 반복 pair가 감사인 review surface를 독점하지 않게 하기 위한 artifact-only 정책이며, row score, PHASE1 priority, PHASE2 family ranking은 변경하지 않는다.
  - `duplicate_pair_artifact_selection_strategy` 기본값은 `document_diversity`다. Phase 4 후보 `evidence_diversity`와 retention candidate script의 추가 selector들은 pair score, strong/moderate evidence tier, same-partner/reference/text support, 반복 document/document-pair 완화를 사용해 artifact retention만 비교한다. truth label, scenario, PHASE1 priority/composite/ranking, PHASE2 family fusion은 입력으로 쓰지 않는다.
  - Phase 4 후보들은 diagnostic-only이며 production default selector가 아니다. candidate weight는 fixed exploratory diagnostic weight로 기록하고, cross-batch/fixture validation 전까지 product ranking policy로 적용하지 않는다.
  - case-order companion surface 후보도 diagnostic/export sidecar 비교에 한정한다. fixed4/fixed5 cross-batch 진단에서 UI TOP100 안정성과 broader pair evidence export를 분리하는 방향은 유지됐지만, 별도 승인 전 production case ordering이나 family fusion으로 적용하지 않는다. schema 후보는 raw document_id/row_id/index_label/phase2_case_id를 저장하지 않고 tier/rule 분포와 coverage count만 저장한다.
  - export sidecar burden 진단상 개별 case 필터보다 rule/tier 또는 rule/tier/similarity grouped summary가 더 안정적인 후보다. grouped summary는 raw pair/document id를 저장하지 않고 aggregate group count와 coverage count만 저장하며, drilldown 대표 evidence unit은 별도 bounded contract가 필요하다.
  - raw row score hit가 있으나 `top_pairs`가 비거나 case-grade pair가 없으면 `pair_artifact.coverage`와 `duplicate_case_builder_diagnostics`에 원인을 남긴다. 예: 후보 subset 부재, size cap, weak pair evidence tier, df index join 실패.
  - 한계는 [`phase2_reorgani.md` §3 duplicate](phase2_reorgani.md) 참조. pair_artifact는 evidence/attribution 보강용이며 row score 가중치로 사용하지 않는다.
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
  - (구) high/medium/low confidence band 해석은 binary 재정의(2026-06-19)로 폐기. raw candidate는 (가)증빙 재기표·(나)완전 복제 발화 여부로만 본다.
  - 따라서 L2-03 raw hit 전체를 단일 precision/recall 합불격으로 해석하지 않는다.

#### L2-04 — 비용 자산화 (ExpenseCapitalization) ✅

- **심각도**: 4
- **근거**: 240§32, FSS 분식회계: 개발비 과대자산화
- **한 줄 설명**
  - 비용으로 나가야 할 금액이 자산으로 넘어간 것처럼 보이는 전표를 찾는 룰이다.
- **판정 (binary flag — 점수 단계·자동 제외 폐기, 2026-06-19 재정의)**
  - 회사 설정(`audit_rules.yaml`)의 `자산 계정 prefix`·`비용 계정 prefix`로, 같은 `document_id` 안에서 **자산 차변 합 ≈ 비용 대변 합**(1:1 또는 분할 합계, ±오차)이면 **flag 1.0**. 매칭된 자산/비용 라인만 올린다.
  - = 비용을 자산으로 옮긴(재분류) 모양. 정상 자산 취득(`자산 차변 / 현금 대변`)은 비용 대변이 아니라 안 걸린다.
- **자동 제외·가감 폐기 (핵심)**
  - 구 적요 키워드 가감(개발/구축/software 감점, 수선/복리후생/수수료 가점, 수기 source 가점, AA/FA 문서유형 감점)과 `immediate/review/low/population` 밴드를 **전부 폐기**한다.
  - 이유 ①: 적요·계정·문서유형은 **회사마다 제멋대로** 써서 거를 근거가 못 된다(L2-01 90% 휴리스틱과 같은 한계).
  - 이유 ②(중요): "개발/구축 감점"은 이 룰의 **핵심 부정 타깃인 개발비 과대자산화(근거: FSS 분식회계)를 단어 보고 자동으로 숨기던 역설**이었다. 거르려다 진짜 부정을 가렸다.
  - 따라서 매칭이면 무조건 띄우고(검토 트리거), **자본화가 옳은지는 감사인이 증빙으로 판단**한다. 룰은 자동 분류를 시도하지 않는다.
- **성격·tier**
  - 검토 트리거(부정 확정 아님). 감사인은 외부인이라 전표만으로 자본화 정당성을 확정 못 한다 → "이거 봐라"까지만.
  - 단독이 LOW냐, 다른 신호와 조합해 HIGH냐는 **통합점수체계가 결정**한다(룰은 binary flag만 내고 조합에 관여하지 않는다).
  - `row_annotations`에는 매칭된 자산/비용 라인·금액 근거를 남긴다.
- **합성데이터 평가**: family 라벨 기준 recall은 높지만 subtype 단독 기준 precision은 낮아, `비용 자산화 family`를 넓게 잡는 우선검토 룰로 해석한다. 상세는 `tests/phase1_rulebase/test-results/l2-04-synth-2022-2024.md` 참조.
- **평가 계약**
  - `src/metrics/rule_mapping.py`의 primary label family는 `ExpenseCapitalization + ImproperCapitalization`이다.
  - `v115_candidate`부터 `rule_truth_L2_04*`와 `expense_capitalization_review_population*`은 현재 `b11_expense_capitalization()` detector output으로 재생성한 raw candidate universe다. 현재 문서 수는 `1,098`건이다.
  - (구) `immediate/review/low/population` band 분류는 binary 재정의(2026-06-19)로 폐기. raw candidate는 자산↔비용 매칭 발화 여부로만 본다. 확정 비용 자산화처럼 강하게 볼 대상은 confirmed label subset과 함께 본다.
  - `expense_capitalization_review_population*`은 detector output snapshot이다. 독립 검증 sidecar가 아니다.
  - `v117_candidate`부터 독립 행동 검증용 sidecar는 `expense_capitalization_plausible_cases*`와 `expense_capitalization_normal_capex_controls*`를 사용한다. 이 파일들은 detector output을 읽지 않고 anomaly label 또는 journal 업무 필드로만 선정한다.
  - `v117_candidate`부터 활성 `rule_truth_*`의 `source_candidate` 메타데이터는 모두 `v117`로 정리되어, 과거 후보 버전 기준이 활성 truth처럼 남지 않는다.
  - strict `ImproperCapitalization`은 확정 subtype 참고값이며, 단독 precision을 L2-04 전체 성능으로 보지 않는다.
  - 리포트 상태는 coverage anchor로 표시한다(band 분류 폐기).
- **구현**: `fraud_rules_groupby.py` → `b11_expense_capitalization()`
- **필요 피처**: `document_id`, `gl_account`, `debit_amount`, `credit_amount`

#### L2-05 — 역분개 패턴 (ReversalEntry) ✅

- **심각도**: 4
- **근거**: 240§32(a)(ii) 기말 재분개 중점 검사, FSS 분식회계·횡령은폐
- **설계 원칙 (백지 재정의 2026-06-19)**
  - 역분개 = 원래 전표를 거꾸로 되받아 무효화하는 것. 같은 계정이 차변↔대변으로 뒤집혀 상쇄되는 **거울 쌍**.
  - 정상 영업에 역분개가 압도적으로 많다(자동 결산 역분개·실수 정정). 구조만으로는 부정/정상이 구별되지 않으므로 **부정 확정이 아니라 검토 트리거**다. 기말·수기·관계사 같은 정황 판단은 룰이 하지 않고 통합점수체계 조합이 한다.
- **판정 (binary flag — 점수 가감·밴드 폐기)**
  - 아래 둘 중 하나면 **flag 1.0**.
    - **(A) ERP 연결**: `original_document_id`/`reversal_document_id`/`reference_document_id`/`reversal_reason` 등 원전표↔역전표 연결 필드로 역분개임이 명시됨. (확정 식별, 시점 무관)
    - **(B) 1:1 거울 쌍**: 같은 `gl_account` + 반대 방향(한쪽 차변 X / 다른쪽 대변 X) + 금액 일치(±오차) + 다른 `document_id`. generous 시간 윈도우(config, 기본 90일) 내.
  - **"같은 계정"이 정상 상계를 거른다**: 역분개는 **같은 계정**을 되돌리고, 정상 상계/정산은 **다른 계정** 간(받을 돈↔줄 돈, AR↔AP)이다. 같은 계정 거울 쌍이면 상계가 아니라 되돌림이다. 이 조건의 **미탐 위험은 작다** — 진짜 역분개는 수학적으로 같은 계정을 뒤집으므로 정의상 매칭된다(놓치는 건 다른 계정으로 우회한 "가짜전표+커버"로, 역분개가 아닌 별개 패턴).
- **자동 source도 발화 (정상성 판단은 통합점수)**
  - 자동/시스템/배치 source의 정기 결산 역분개(발생주의 미수·미지급 자동 역분개 등)도 거울 쌍/ERP 연결이면 **flag 1.0으로 발화한다.** "자동 정기 역분개라 정상"은 source/수기 차원의 정상성 판단이므로 룰이 하지 않고, `L3-02`(수기 전용 룰)와 통합점수체계가 `역분개 + 자동 source`를 정상으로 다운웨이트한다(룰은 멍청하게). 단 "같은 계정 되돌림"·"다른 document_id"는 역분개 정의 자체라 유지(intrinsic).
- **폐기 (구 신호 정리)**
  - **S2b(단일 라인 차대변 스왑) 폐기**: 전표 하나가 불균형(차변≠대변)인 **입력 오류**이지 역분개(균형 전표 두 개로 되돌림)가 아니다. 불균형은 이미 **L1-01(차대불일치)**이 잡는다.
  - **S2(N:M 순액 ≈ 0) 폐기**: 가수금·가지급금·미결제 같은 청산계정은 본질적으로 윈도우 내 0으로 수렴 = 정상이라 **과탐이 압도적**이고 거를 내재 기준이 없다. 분할·우회 역분개는 niche이며 L3-09(가수금 장기체류)·조합이 보완한다.
  - **점수 가감(구 S3 가점·S4 키워드·S5 기말 부스트)과 high-confidence/candidate 밴드 폐기.** 모든 발화 경로 score 1.0.
- **tier로 흐르는 길**
  - L2-05 단독은 통합점수 **LOW**(역분개 검토 후보). 기말(L3-04)·수기(L3-02)·관계사(L3-03)·가수금(L3-09)과 **조합 시 HIGH**(`related_party_reversal_high`·`embezzlement_concealment` 등). 정황 가중은 룰이 아니라 통합점수체계가 한다.
- **평가/리포트 표시 방식**
  - (구) `high-confidence reversal`/`candidate clearing-reclass` 밴드 분리는 binary 재정의(2026-06-19)로 폐기. 발화는 (A)ERP 연결·(B)1:1 거울 쌍 여부로만 본다.
  - `c11_reversal_entry()`는 Boolean hit 외에 행 단위 `score_series`(1.0/0.0), `breakdown`, `row_annotations`(거울 쌍 상대 전표·금액 근거)를 제공한다.
- **실무 해석 시 주의점**
  - N:M 순액 0을 폐기했으므로 청산계정(`9990`·차입금·선수금·자금이체성·임시계정) 과탐은 구조적으로 제거된다(1:1 거울 쌍은 같은 계정 되돌림만 보므로).
  - S2b 제거로 단일 전표 불균형(입력 오류)은 L2-05에서 빠지고 L1-01이 담당한다.
- **DataSynth 계약**: `ReversedAmount` 라벨은 실제 `journal_entries*.csv`에 존재하는 `document_id`만 가리켜야 한다.
- **평가 계약**
  - `ReversedAmount`는 confirmed reversal subset이다. binary 재정의 후 (A)ERP 연결·(B)1:1 거울 쌍 발화와 대조한다.
  - `v115_candidate`부터 `rule_truth_L2_05*`와 `reversal_entry_review_population*`은 현재 `c11_reversal_entry()` detector output으로 재생성한 raw candidate universe다. (현행 82건은 구 신호 기준 — S2b/N:M 폐기 반영 후 재생성 대상. 자동 source 제외 폐기로 자동 역분개도 모집단에 포함.)
  - (구) high_confidence/candidate band 구분은 폐기. raw candidate는 거울 쌍/ERP 연결 발화 여부로만 본다.
  - `reversal_entry_review_population*`은 detector output snapshot이다. 독립 검증 sidecar가 아니다.
  - `v117_candidate`부터 독립 행동 검증용 sidecar는 `reversal_pattern_plausible_cases*`와 `reversal_pattern_normal_clearing_controls*`를 사용한다. 이 파일들은 detector output을 읽지 않고 anomaly label 또는 journal 업무 필드로만 선정한다.
  - `v117_candidate`부터 활성 `rule_truth_*`의 `source_candidate` 메타데이터는 모두 `v117`로 정리되어, 과거 후보 버전 기준이 활성 truth처럼 남지 않는다.
- **ERP 구조 필드 우선 원칙**: 실제 ERP에서 별도 역분개 문서형이 많으면 `(A)` ERP 연결 coverage가 중요하므로, 구조 필드가 있으면 최우선으로 활용한다.
- **구현**: `anomaly_rules_reversal.py` → `c11_reversal_entry()`
  - (B) 1:1 거울 쌍 후보 생성: DuckDB self-join (`document_id × gl_account` 집계 후)
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

### 2.3 L3: 검토 필요 이상징후 (11개 구현, L3-01 폐기)

> **L3-01 폐기 (2026-06-20, 구 계정 분류 불일치)**: 업무프로세스-계정 부조화는 사람이 유지하는 정답 조합표(denylist/category)에 의존하는데 그 기준이 애매하고, 통합점수체계 조합에서도 참조되지 않았다. 도메인상 이상한 계정 조합 중 실제로 드문 것은 **L4-04(희소 차대 계정쌍)** 가 데이터 기반으로 자연 포착하므로 별도 룰로 두지 않는다. 정답표 휴리스틱 룰을 제거하고 통계 룰(L4-04)에 역할을 넘긴다. canonical rule 수에서 제외(31→30).

#### L3-02 — 수기 전표 (Manual Entry Population) ✅

- **심각도**: 4
- **근거**: 240-A45(b) 비인가자 입력, K-SOX 우회금지(외감법§8②). FSS 가공전표: 자동 프로세스 우회
- **탐지 로직 (binary)**: `is_manual_je == True`이면 flag `1.0`, 아니면 `0`. `is_manual_je`가 없으면 `source`가 `manual_source_codes`에 포함되는지로 판정한다. 그 외 가공·완화·점수 차등 없음.
- **해석 원칙**
  - L3-02는 "이 전표가 수기/조정 입력이다"라는 사실 하나만 표시한다. 부정·통제우회 확정이 아니고, 수기 자체가 위반도 아니다.
  - 수기전표는 정상적으로도 흔하므로(결산 조정 등), L3-02 단독으로 검토 우선순위를 만들지 않는다. **고액·기말·자기승인·승인생략·심야·민감계정 등 다른 신호와의 조합 가중은 전부 통합점수체계가 한다.** 룰은 수기 여부만 본다.
  - `ManualOverride` anomaly label은 일부 조작성 수기 시나리오이고, L3-02 운영 truth는 수기/조정 전표 전체 모집단이다(평가 보조 지표).
- **source-trust 일원화 (자동/수기 판별의 단일 출처)**: 전표가 사람 수기냐 자동/배치냐를 판별하는 책임은 L3-02(+`source_trust`)에 모은다. 자동인 척 위장한 전표(`lone_automated_mask` — 자동 주장 ∧ batch_id/job_id 결측 ∧ 같은 날 동류 ≤10건)는 수기로 되살려 L3-02가 잡는다(위장으로 수기 탐지를 빠져나가면 모든 HIGH 조합이 무너지므로). 다른 룰(L2-01 한도직하·L2-05 역분개·L3-05 주말·L3-06 심야 등)은 source를 보지 않고 신호만 올리며, "자동이라 정상"의 다운웨이트는 통합점수체계가 L3-02 수기 leg로 한 번만 처리한다.
- **출력 메타데이터**
  - `score_series`: 수기 `1.0` / 비수기 `0`.
  - `row_annotations`: `document_id`, `source`, `created_by`, `approved_by`, `approval_date`, `business_process`, `gl_account`, `description_quality` 등 사실값만 기록한다(버킷·우선순위 사유 계산 없음).
  - `breakdown`: `flagged_rows`, `manual_rows`, `adjustment_rows`, `source_counts`.
- **구현**: `fraud_rules_feature.py` → `b08_manual_override()`
- **필요 피처**: `is_manual_je` 또는 `source`
- **DataSynth truth 원칙**: `L3-02`는 수기전표 전체 모집단 coverage로 평가하고, 일부 조작성 시나리오 라벨인 `ManualOverride`와는 분리한다.

#### L3-03 — 관계사 거래 검토 신호 (RelatedPartyTransactionSignal) ✅

- **심각도**: 4
- **근거 (1차)**: IFRS 10 §B86 연결 내부거래 제거, K-IFRS 1110 연결재무제표 작성 시 내부거래 제거 절차, K-IFRS 1024 특수관계자 공시, KICPA Issue Paper 46 (JET 완전성), ISA 600 그룹감사 구성단위 잔액 대사. IC 양측 대사 룰의 회계적 필연성은 이 근거에서 도출된다.
- **근거 (보조)**: ISA 550 §23 특수관계자 거래의 사업상 합리성 검토. Phase 1에서는 순환 구조를 단정하지 않고 관계사 계정 사용 전표를 검토 후보로 올린다.
- **탐지 로직**: IC GL prefix 매칭
  - `intercompany_identifiers: ['1150', '2050', '4500', '2700']`
  - 관계사 채권/채무/매출/미지급 등 고객사 CoA상 IC 전용 계정 사용 여부만 판단
  - 실제 A→B→C→A N-hop 순환 탐지는 **GR01(GraphDetector)** 에서 담당 ([DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD) §4.5)
- **구현**: `fraud_rules_access.py` → `b10_intercompany_review_signal()`
- **필요 피처**: `is_intercompany` (`gl_account` prefix에서 생성), 보강 설명용 `company_code`, `trading_partner`, `reference`
- **PHASE1-1 경계 (binary)**: 함수는 `is_intercompany=True` 모집단을 flag `1.0`(아니면 `0`)으로 표시하는 context 태그다. `RULE_SCORING_REGISTRY` 기준 scoring은 `logic_mismatch/weak/booster`, `final_topic=account_logic`, `standalone_rankable=False`이며 단독 floor는 없다.
- **해석 원칙**
  - L3-03은 "이 전표가 관계사 전용 계정을 썼다"는 사실 하나만 표시하는 **context 태그**다. 부정·순환거래 확정이 아니다.
  - 관계사 거래는 정상적으로도 많으므로 L3-03 단독으로 검토 우선순위를 만들지 않는다. **관계사+역분개·관계사+미대사 등 조합 가중은 전부 통합점수체계가 한다.** 룰은 관계사 계정 사용 여부만 본다.
- **출력 메타데이터**
  - `score_series`: 관계사 계정 사용 `1.0` / 아니면 `0`.
  - `breakdown`: `ic_population_rows`, `ic_population_docs`, `ic_company_count`, `trading_partner_coverage_ratio`.
  - `row_annotations`: `signal_category=ic_population`, `company_code`, `trading_partner`.
- **실무 해석**: 단독 부정 후보가 아니라 특수관계자 거래 모집단/샘플링 후보. 계약서·상대방·정상가격·대사 여부는 후속 확인한다. recall 우선 스크리닝이므로 IC prefix·금액·시차 조건을 임의로 좁혀 미탐을 늘리지 않는다.
- **DataSynth 계약**: `v37_candidate`부터 IC GL prefix 기준 `intercompany_population_truth` sidecar를 별도 관리하고, 실제 비정상 순환거래 라벨(`CircularIntercompany`/`CircularTransaction`)과 혼동하지 않는다.
- **PHASE1-2 family 이관 (2026-06-20)**: 관계사 쌍 대사 예외(IC01/IC02/IC03)·그 evidence_level/floor/PHASE2 확률컬럼, N-hop 순환(GR01)·이전가격 비대칭(GR03)과 평가계약은 [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD) §4.4 IC Matcher / §4.5 Graph Detector 소관이다. L3-03 카드는 관계사 계정 사용 binary 태그만 정의한다.
- **한계**: 정상 내부거래도 많이 포함될 수 있으며, 이 룰만으로 순환거래나 부정을 단정하지 않는다. 고객사 CoA에서 관계사 계정 prefix가 다르면 `patterns.intercompany.pairs`를 먼저 보정해야 한다.

#### L3-04 — 기말/기초 결산 검토 후보군 (Period-start/end Closing Review) ✅

- **심각도**: 3
- **근거**: 240§32(a)(ii)+A44 기말검사 의무. FSS 결산수정 27건(29%)
- **탐지 로직 (binary)**: `posting_date`가 월말 직전 5일 또는 월초 5일 구간(기말/기초)이면 flag `1.0`, 아니면 `0`. 구간 폭은 `period_end_margin_days`(기본 5)로 정한다. 기말/기초 여부만 본다 — 금액·수기·민감계정·승인·시점은 hit 조건도 점수 차등도 아니며, 그 조합 가중은 통합점수체계가 한다.
- **구현**: `anomaly_rules_simple.py` → `c01_period_end_large()`
- **필요 피처**: `posting_date`, `is_period_end` (파생)
- **Phase 1 적용 방침**
  - 결산 일정은 회사별로 다르므로 감사인/사용자가 `period_end_margin_days`와 회계연도 기준을 engagement 시작 시 확정해야 한다. 기본값 5일은 제품 기본값일 뿐 회사 결산일을 대체하지 않는다.
  - **기말+기초 둘 다 잡는다.** 한국 월차결산이 익월 초까지 이어져 전월 조정이 월초에 입력되므로 기초(월초 5일)도 결산 검토 신호다. 정상 이월 노이즈는 통합점수체계 조합이 거른다(룰에서 좁히지 않는다).
- **해석 원칙**
  - L3-04는 "이 전표가 기말/기초 결산 구간에 전기됐다"는 사실 하나만 표시하는 **timing context 태그**다. 부정·조작 확정이 아니다.
  - 결산 구간 전표는 정상적으로도 많으므로 L3-04 단독으로 검토 우선순위를 만들지 않는다. **고액·수기·민감계정·승인문제·심야·역분개 등 조합 가중은 전부 통합점수체계가 한다.** 룰은 기말/기초 여부만 본다.
- **출력 메타데이터**
  - `score_series`: 기말/기초 `1.0` / 아니면 `0`.
  - `row_annotations`: `period_phase`(기말=`end` / 기초=`start` 구분), `posting_date`, `source`, `created_by`, `approved_by`, `business_process`, `account_group`, `gl_account` 등 사실값만 기록한다(버킷·금액 임계·우선순위 사유 계산 없음).
  - `breakdown`: `flagged_rows`, `period_end_rows`, `period_start_rows`, `source_counts`.
- **평가/리포트 표시 방식**: `RushedPeriodEnd` 확정 라벨 기준 precision/recall은 조작 시나리오 보조 참고값이다. L3-04 Phase 1 primary truth는 월말/월초 ±5일 review population coverage다.
- **운영 전제**: L3-04는 탐지 제외 룰이 아니라 결산 검토 후보 모집단이다. 플래그(1/0)는 유지하고, 검토 우선순위는 통합점수체계 조합이 정한다. 반복 마감전표 downgrade·민감계정 가중 같은 정황 보정도 룰이 아니라 통합점수체계 소관이다.

#### L3-05 — 주말/공휴일 전기 (WeekendPosting) ✅ 【OFF-HOUR 트랙】

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. FSS 비정상시점 4건
- **탐지 로직 (binary)**: `weekday() >= 5`(토·일) 또는 공휴일(한국 법정공휴일+`custom_holidays`)이면 flag `1.0`, 아니면 `0`. **source는 보지 않는다.** 구 3단 점수(`weekday_holiday/weekend/weekend_holiday`)·PHASE1 signal_strength 변환 폐기.
- **자동 전표도 발화 (정상성은 통합점수)**: 시스템·배치가 주말/공휴일에 도는 것도 flag `1.0`으로 올린다. "자동이라 정상"은 source/수기 차원이라 룰이 판단하지 않고, `L3-02`(수기 전용 룰)와 통합점수체계가 `비근무일 + 자동 source`를 정상으로 다운웨이트한다. 자동인 척 위장한 전표(batch_id 결측 등) 판별(source-trust)도 통합점수의 L3-02/source_trust leg 소관이다(룰은 비근무일 사실만 본다).
- **해석 원칙**: L3-05는 "비근무일(주말/공휴일)에 전기됐다"는 사실만 표시하는 **OFF-TIME context 태그**다. tier 게이트에 직접 참여하지 않고 severity 보조축으로 쓰인다. 부정 확정이 아니며, 수기·고액·기말/기초·승인우회·중복/역분개·적요결손·사용자집중(L4-05) 조합 가중은 전부 통합점수체계가 한다.
- **출력 메타데이터**
  - `score_series`: 비근무일 `1.0` / 아니면 `0`.
  - `row_annotations`: `is_weekend`, `is_holiday`, `source`, `posting_date` 등 사실값만.
  - `breakdown`: `flagged_rows`, `weekend_rows`, `holiday_rows`, `source_counts`.
- **구현**: `anomaly_rules_simple.py` → `c02_weekend_entry()`
- **필요 피처**: `posting_date`, `is_weekend`(파생), `is_holiday`(파생)
- **운영 전제**: `is_holiday`는 한국 법정공휴일과 `custom_holidays`를 함께 본다. 감사인은 회사 창립기념일·전사 휴무일·공장 셧다운·노사 합의 휴일을 `custom_holidays`에 입력해야 회사 실제 근무 캘린더 기준으로 탐지된다.
- **DataSynth 계약**: `v36_candidate`부터 정상 주말 처리 배경을 `normal_weekend_context` sidecar로 분리한다. `v41_candidate`부터 L3-05 hit는 `labels/weekend_review_population*`에 review population으로 저장하고, 확정 이상은 `WeekendPosting`/`labels/weekend_confirmed_anomalies*`만 사용한다(raw hit 전체를 anomaly precision 분모로 쓰지 않음). 넓은 캘린더 스크리닝이라 확정 라벨 기준 precision이 낮아 보이는 것은 룰 목적과 다른 평가이며, 운영 평가는 확정 라벨 recall·review population coverage·정상 대조군 분리로 본다.

#### L3-06 — 심야 전기 (AfterHoursPosting) ✅ 【OFF-HOUR 트랙】

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. KLCA IT 체크리스트
- **탐지 로직 (binary)**: `is_after_hours`(심야 `midnight_start`~`midnight_end`, 기본 22~06시)이면 flag `1.0`, 아니면 `0`. **source는 보지 않는다.** 구 2단 점수(`confirmed_after_hours=0.45`/`normal_system_context=0.20`) 폐기.
- **구현**: `anomaly_rules_simple.py` → `c03_after_hours_entry()`
- **필요 피처**: `posting_date`(시간 포함), `is_after_hours`(파생)
- **자동 전표도 발화 (정상성은 통합점수)**: 야간 배치·인터페이스가 심야에 도는 것도 flag `1.0`으로 올린다. "자동이라 정상"은 source/수기 차원이라 룰이 판단하지 않고, `L3-02`(수기 전용 룰)와 통합점수체계가 `심야 + 자동 source`를 정상으로 다운웨이트한다. 자동인 척 위장한 전표(batch_id 결측 등) 판별(source-trust)도 통합점수의 L3-02/source_trust leg 소관이다(룰은 심야 사실만 본다).
- **해석 원칙**: L3-06은 "심야에 전기됐다"는 사실만 표시하는 **OFF-TIME context 태그**다. tier 게이트 미참여, severity 보조축. 단독 Medium/High를 만들지 않고, 수기·고액·기말/기초·승인생략·자기승인·적요결손·사용자집중(L4-05) 조합 가중은 전부 통합점수체계가 한다.
- **출력 메타데이터**
  - `score_series`: 심야 `1.0` / 아니면 `0`.
  - `row_annotations`: `source`, `created_by`, `posting_date`, `time_bucket` 등 사실값만.
  - `breakdown`: `flagged_rows`, `after_hours_rows`, `source_counts`, `time_bucket_counts`.
- **운영 전제**: 심야 시작/종료 시각은 회사 근무제·교대근무·해외법인 시간대·마감 운영 정책에 맞게 조정한다. 주말/공휴일은 L3-05, 사용자별 overtime·심야 집중은 L4-05에서 별도로 다룬다.
- **DataSynth 계약**: `AfterHoursPosting`을 L3-06 truth로 사용하고, 정상 심야 배경과 date-only/timezone 한계는 별도 sidecar로 분리한다.

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

#### L3-08 — 적요 결손/파손 신호 (MissingOrCorruptedDescription) ✅ 【WEAK-DESC 트랙】

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
  - `score_series`는 `missing=0.45`, `corrupted=0.55`, legacy `poor=0.50`으로 표시한다. 이 점수는 부정 확률이 아니라 기록통제 품질 저하 강도다.
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
- **추가하지 않는 것**: Phase 1에서는 키워드 기반 위험 적요 판단, 회사별 whitelist/blacklist 운영, 적요 의미 충분성 판단, 계정-적요 의미 정합성 판단을 하지 않는다. 의미 기반 평가는 active 범위 밖이며, 향후 local-only NLP로만 검토할 수 있다.
- **한계**: 말은 길지만 실질 설명이 없는 적요, 회사 내부 은어, 계정/프로세스와 어울리지 않는 적요는 Phase 1에서 판단하지 않는다.
- **DataSynth 평가 계약**: `v43_candidate`부터 Phase 1 L3-08 truth는 `MissingOrCorruptedDescription`과 `labels/missing_corrupted_description_truth*.csv/json`만 사용한다. 기존 `VagueDescription`은 보존하되 `labels/vague_or_risky_description_truth*.csv/json`를 통해 future local-only semantic analysis용 의미상 모호/위험 적요 truth로 분리한다. 따라서 `VagueDescription` 전체를 L3-08 precision/recall 분모로 쓰지 않는다.
- **DataSynth 경계 대조군**: `v44_candidate`부터 `labels/description_boundary_normal_controls*.csv/json`에 짧지만 정상인 적요, 정상 시스템 코드형 적요, `line_text`는 비었지만 `header_text`가 충분한 케이스, future semantic analysis용 의미상 vague 케이스를 정상 control로 둔다. v43의 100% 정렬은 계약 테스트이며 실무 precision/recall로 해석하지 않는다.
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
- **Future local-only 이관**: 적요 의미 분석은 별도다. L3-09는 Phase 1에서 `정산상태 + 체류일수`를 본다.

#### L3-10 — 고위험 계정 사용 (HighRiskAccountUse) ✅

- **심각도**: 3
- **근거**: 현금성 계정, 가계정, 가지급금/대여금/선급금 등 감사인이 지정한 **민감 계정군** 사용은 별도 검토 대상이다.
- **탐지 로직**: `gl_account`가 `patterns.high_risk_account_use.accounts`와 일치하거나 `account_prefixes`로 시작하는 경우
- **구현**: `fraud_rules_access.py` → `b13_high_risk_account_use()`
- **필요 피처**: 판정에는 `gl_account`가 필수다. 상세 표시와 우선순위 분리에는 `created_by`, `approved_by`, `source`, `business_process` 같은 문맥 컬럼을 함께 사용한다.
- **Phase 1 적용 방침**
  - 이 룰은 강한 단독 적발 룰이 아니라 `logic_mismatch` 계열의 **민감 계정 접촉 신호**로 사용한다.
  - 기본 제품값(`1190`, `2190`, `111*`, `112*`, `113*`)은 starter default이며, 실제 운영에서는 고객사 CoA와 감사 범위에 맞게 조정한다.
  - 현금성/가계정/가지급금/대여금/선급금/상품권/임시정산 계정 등 민감 계정군을 engagement 초기에 확정하고, `L3-02`, `L1-05`, `L1-07`, `L3-04`, `L3-08`, `L4-04` 등과 결합될 때 우선순위를 높인다.
- **결과 제시 방식**
  - `raw_signal`: 민감 계정군을 건드린 전체 모집단이다. 단독 부정 경고가 아니라 review population으로 보여준다.
  - `priority_case`: `raw_signal` 중 수기/조정, 고액, 미정리, 기말/비정상시점 같은 보강 맥락이 있는 우선 검토 건이다.
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
- **탐지와 점수 분리**: 사용자 유형별 process/company 기준 (단일 출처: `config/audit_rules.yaml` → `patterns.work_scope_excess_review.persona_thresholds`) 을 넘으면 자동/시스템 계정까지 raw candidate로 보존한다. 점수는 별도 위험도이며, 정상 가능성이 높은 시스템/관리자 breadth는 `0.00` 또는 낮은 review score로 둔다.
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
- **사용자 유형별 시작 기준 (단일 출처: `config/audit_rules.yaml` → `patterns.work_scope_excess_review.persona_thresholds`)**

| 사용자 유형 (`user_persona`)                     |                                                                                                     process 기준 | company 기준 |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------: | -----------: |
| `junior`, `staff`, `clerk`                       |                                                                                                           `>= 3` |       `>= 2` |
| `senior`, `accountant`, `default` (미지정/그 외) |                                                                                                           `>= 4` |       `>= 3` |
| `manager`, `controller`                          |                                                                                                           `>= 5` |       `>= 4` |
| `admin`, `superuser`                             |         raw candidate로 보존하되 단순 다중업무는 score `0.00`, 수기/민감/고액/결산 중 2개 이상 결합 시 점수 부여 |         좌동 |
| `automated_system`, `batch_user`                 | raw candidate로 보존하되 기본 score `0.00`, 수기/조정 source와 보강 신호가 함께 있을 때 낮은 system review score |         좌동 |

위 표의 process/company 정수 임계값은 yaml에서 사용자 정의로 변경 가능하며, 카드는 yaml의 현재 값을 단일 출처로 본다. 아래 score bucket 표의 "process 기준 충족", "company 기준 충족" 표현은 위 persona 임계값을 가리킨다.

- **점수 bucket**

| 조건                                                    |                              점수 |
| ------------------------------------------------------- | --------------------------------: |
| 사용자 유형별 process 기준 충족                         |                            `0.20` |
| process 기준 + company 기준 동시 충족                   |                            `0.30` |
| process 또는 company 기준을 한 단계 (해당 유형 +1) 상회 |                            `0.35` |
| 위 조건 + `manual/adjustment` source 포함               |                            `0.45` |
| 위 조건 + 민감 계정군 포함                              |                            `0.50` |
| process/company 기준을 모두 한 단계 상회 + 수기 포함    |                            `0.55` |
| 위 조건 + 결산일/고액/민감계정 중 2개 이상 결합         |                            `0.65` |
| L1-05/L1-06/L1-07 동반                                  | L3-12는 `0.65` 이하, L1이 주 신호 |

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

### 2.4 L4: 통계적 이상치 (PHASE1-1 4개: L4-01·L4-03·L4-04·L4-06)

> 2026-06-17 분리: **L4-02(Benford)는 PHASE1-2로 이관** → [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD).
> **L4-05(비정상시간 집중)는 양쪽 소속(2026-06-20)**: PHASE1-2 family(사용자 행동 집계 단위)에 두되, PHASE1-1 **OFF-TIME set**(L3-05·L3-06과 함께 시간 보조축)에도 등록한다. 제거가 아니라 dual-membership이다. OFF-TIME set에서의 역할은 case 보조축(게이트 제외, 정렬·UI 전용, 점수 병합 금지 — 작성자 맥락 연결)이며 정의는 [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) OFF-TIME 보조축 절. 코드 registry는 PHASE1-1에 잔존(이관 미수행 상태가 dual-membership과 정합).

#### L4-01 — 매출 이상 변동 (RevenueManipulation) ✅

- **심각도**: 5
- **근거**: 240보론2, §32(c) 비경상거래. **FSS 최다유형**: 매출 허위계상
- **탐지 로직**: 매출 계정(4xxx) 금액이 Z-score 임계값 초과
  - `patterns.revenue_account_prefixes: ['4']` (`config/audit_rules.yaml`)
  - `zscore_threshold: 3.0` (`config/settings.py`, 회사/engagement override 가능)
- **구현**: `fraud_rules_feature.py` → `b01_revenue_manipulation()`
- **필요 피처**: `is_revenue_account`, `amount_zscore` (파생)
- **점수 bucket**

  | bucket           | 조건                                     | L4-01 raw score | 해석                         |
  | ---------------- | ---------------------------------------- | --------------- | ---------------------------- |
  | `review_zscore`  | `zscore_threshold < amount_zscore < 4.0` | 0.45            | 매출 고액 이상치 검토 후보   |
  | `strong_zscore`  | `4.0 <= amount_zscore < 6.0`             | 0.60            | 강한 매출 고액 이상치 anchor |
  | `extreme_zscore` | `amount_zscore >= 6.0`                   | 0.75            | 극단 매출 고액 이상치 anchor |

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

  | 조합                           | 해석                                    | 우선순위    | 확인 포인트                                                                          |
  | ------------------------------ | --------------------------------------- | ----------- | ------------------------------------------------------------------------------------ |
  | `L4-01 + L3-11`                | 고액 매출 + cutoff 불일치               | High        | 출하일/용역완료일/검수일과 매출인식일의 귀속기간 차이, 계약 조건, 기말 전후 반대분개 |
  | `L4-01 + L3-04`                | 기말 고액 매출                          | High        | 월말/분기말/연말 집중, 다음 기간 취소·환입, 비경상 대형 계약 여부                    |
  | `L4-01 + L3-02`                | 수기 고액 매출                          | High        | 수기 입력 사유, 승인권자, supporting document, 반복 생성자/부서                      |
  | `L4-01 + L1-05/L1-07/L1-07-02` | 승인통제 이상이 붙은 고액 매출          | Critical    | 자기승인, 승인 누락, 유령 승인자, 권한 우회 여부                                     |
  | `L4-01 + L2-05`                | 후속 취소/역분개 가능성                 | High        | 매출 인식 후 credit memo, return, reversal, 동일 고객·금액·계정의 반대분개           |
  | `L4-01 + L4-03`                | 전체 금액 기준으로도 유의적인 고액 매출 | Medium~High | 감사 중요성 기준 초과 여부, 정상 대형계약/신규고객/일회성 거래 여부                  |

  - 현재 Phase 1 floor:
    - `L3-11 >= 0.30 + L4-01` → `priority_score >= 0.75` (Medium 검토 후보)
    - `L3-04 >= 0.45 + L4-01` → `priority_score >= 0.75` (Medium 검토 후보)
    - `L3-02 >= 0.60 + L4-01` → `priority_score >= 0.75` (Medium 검토 후보)
    - `L2-05 >= 0.45 + L4-01` → `priority_score >= 0.75` (Medium 검토 후보)
  - 보조 조합으로 `L4-01 + L3-03`은 관계사 매출, 순환거래, 밀어넣기 가능성을 후속 확인한다.
  - 동일 전표 내 여러 라인이 L4-01에 걸리면 라인별 합산보다 전표 단위 최대점수와 동시 플래그 수를 함께 보여준다.

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

| 버킷                              | 기준                                                      | row score |
| --------------------------------- | --------------------------------------------------------- | --------: |
| `low_zscore` / `review_zscore`    | `zscore_threshold < amount_zscore < 5.0` + 금액 가드 통과 |      0.25 |
| `medium_zscore` / `strong_zscore` | `5.0 <= amount_zscore < 10.0` + 금액 가드 통과            |      0.45 |
| `high_zscore` / `extreme_zscore`  | `amount_zscore >= 10.0` + 금액 가드 통과                  |      0.70 |

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

  | 결합                  | 의미                                                  | 우선순위 |
  | --------------------- | ----------------------------------------------------- | -------- |
  | `L4-03 + L3-04`       | 기말/기초에 발생한 고액 조정 전표                     | High     |
  | `L4-03 + L1-05/L1-07` | 고액 전표의 자가승인 또는 승인 누락                   | High     |
  | `L4-03 + L4-04`       | 고액이면서 드문 차변-대변 계정 조합                   | High     |
  | `L4-03 + L3-08`       | 고액인데 적요가 비어 있거나 깨져 있음                 | Medium   |
  | `L4-03 + L4-01`       | 매출 계정 특화 이상치이면서 전체 금액 기준으로도 고액 | High     |

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

#### L4-06 — 배치성 자동 전표 검토 신호 (BatchAnomaly) ✅

- **심각도**: 2
- **운영 성격**: 단독 고위험 적발 룰이 아니라 Phase 1 보조 검토 신호다. 과거 Phase 2 WU-09로 설계되었으나, 최신 PHASE1 관계도에서는 `statistical_outlier` evidence와 `batch_combo_bonus` 입력으로 운영한다.
- **근거**: 배치·인터페이스·시스템 전표는 정상 대량 처리도 많으므로, 단독 hit만으로 부정 가능성을 강하게 주장하지 않는다. 다만 개별 승인/검토가 약할 수 있어 기말·대량·금액 특이 패턴은 검토 후보로 남긴다.
- **배치성 source 기본값**: `batch`, `interface`, `system`, `auto`, `automated`, `if`, `sys` 계열. 비교는 대소문자 무시.
- **탐지 로직**: 4가지 하위 패턴 OR 결합
  1. 기말 집중: 배치성 전표 중 기말 비율 > `batch_period_end_ratio` (기본 0.5)
  2. 대량 동시 생성: 동일 `posting_date` 배치성 전표의 `document_id` distinct count ≥ `batch_simultaneous_threshold` (기본 50). `document_id`가 없을 때만 row count로 fallback한다.
  3. 금액 이상: 배치성 전표 내 `abs(Z-score) > batch_amount_zscore` (기본 3.0), std=0 방어 포함. 배치 평균보다 큰 금액뿐 아니라 비정상적으로 작은 금액도 검토 후보에 포함한다.
  4. 단독 배치 정체성 결손 (`lone_batch_identity`, 2026-06-12 신설): 배치성 source를 주장하는데 `batch_id`·`job_id`가 모두 결측이고 같은 날 동류(배치성+정체성 결손) 전표 수 ≤ 10건. **source 위조(자동 위장) 의심** — 정상 자동 전표는 무리지어 다닌다(v41 정상 실측: 자동 202,102 문서 중 82건만 해당). 두 정체성 컬럼이 모두 없으면 검증 불가로 미발동. 구현: `source_trust.lone_automated_mask()`. score 0.45 (단독), 타 패턴 결합 시 0.65.
- **위험도가 높아지는 결합 신호**

  | 결합                        | 의미                                              | 운영 우선순위 |
  | --------------------------- | ------------------------------------------------- | ------------- |
  | `L4-06 + L3-04/L3-07/L1-08` | 자동 배치성 전표가 결산·cutoff·전기일 괴리와 결합 | Medium 이상   |
  | `L4-06 + L1-05/L1-06/L1-07` | 자동 처리와 승인/권한 통제 실패가 결합            | Medium 이상   |
  | `L4-06 + L4-03/L4-04/L3-10` | 배치성 전표가 고액·희소 계정쌍·민감 계정과 결합   | Medium 이상   |
  | `L4-06 + L3-08`             | 자동 전표인데 적요가 비어 있거나 깨져 있음        | 보조 가점     |
  | `L4-06 + L2-05/L2-02`       | 배치성 처리 후 역분개·중복 징후 동반              | High 후보     |

- **PHASE1 점수 흐름**: L4-06 detector raw score는 `0.25/0.45/0.65` band로 남기되, 공통 정규화에서는 `evidence_strength=weak`, `scoring_role=combo_only`, L4 family weight `0.15`가 적용된다. 따라서 L4-06 단독 hit는 row-level `anomaly_score`와 `risk_level`을 의미 있게 끌어올리지 않는다.
- **코드 반영**: `score_aggregator.py`는 L4-06 결합 신호를 `batch_combo_score`로 계산하며, L4-06 단독은 승격하지 않는다. `phase1_case_builder.py`는 같은 원칙으로 `batch_combo_bonus`와 behavior floor를 case priority에만 반영한다.
- **fraud-combo floor 신뢰 게이트 (2026-06-12)**: 사람 행위를 전제하는 fraud-combo floor(가공전표·결산조정·횡령은닉 등 0.75 승격)는 **신뢰 가능한 자동 전표**(자동 계열 source ∧ `lone_batch_identity` 아님, recurring 포함 — `source_trust.trusted_automated_mask()`)에서만 발화한 룰을 콤보 트리거로 인정하지 않는다. 근거: 자동 결산 배치의 승인 부재·결산기 집중은 정상이며, 이를 콤보로 승격하면 정상 medium 노이즈가 생긴다(v41 실측 3,516건 — OPEN_ISSUES #14). 위장 의심(단독 자동) 행의 발화는 신뢰하지 않으므로 콤보 트리거로 유지된다. 구현: `phase1_case_builder._fraud_combo_rule_scope()` → `compute_topic_scores(fraud_combo_rule_scope=...)`.
- **구현**: `anomaly_rules_batch.py` → `c13_batch_anomaly()`
- **필요 피처**: `source`, `is_period_end`, `posting_date`, `debit_amount`, `credit_amount`
- **동일 일자 처리**: 대량 동시 생성 조건은 `posting_date`를 달력일 단위로 정규화한 뒤 집계한다. 시간이 포함된 timestamp라도 같은 날짜면 같은 배치 모집단으로 묶고, 날짜 파싱이 불가능한 값은 앞 10자 문자열로 graceful fallback한다.
- **DataSynth 상태**: DataSynth v114 후보에서 `rule_truth_L4_06.csv`와 `batch_review_population.csv`를 현재 detector raw batch review universe로 맞췄고, v116에서 활성 truth metadata를 현재 후보 기준으로 정리했다. 현재 detector docs `686`, truth docs `686`, detector/truth diff `0`이다. confirmed `BatchAnomaly` 라벨은 이 안에서 뽑은 subset이며, `batch_normal_controls.csv`와 `batch_boundary_controls.csv`는 strict rule truth에 섞지 않는다. `recurring`은 L4-06 batch source가 아니며, 실제 배치성 이상이면 원장 `source`가 `batch`/`interface`/`automated` 계열로 분류되어야 한다.
  - `v120_candidate`부터 `labels/batch_detector_universe*`는 `labels/batch_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `labels/batch_normal_controls*`와 `labels/batch_legitimate_contexts*`는 정상 batch context다.
  - `labels/batch_boundary_controls*`와 `labels/batch_boundary_contexts*`는 경계 batch context다. v120 기준 `batch_boundary_contexts`는 128문서 중 30문서가 L4-06 detector universe와 겹치므로 strict negative control로 해석하지 않는다.
- **평가 계약**:
  - L4-06은 strict pass/fail 룰이 아니라 `coverage_anchor` 보조 증거다. DataSynth strict Phase 1 truth는 confirmed label만이 아니라 raw batch review universe다.
  - breakdown은 `batch_review_docs`, `period_end_concentration_docs`, `simultaneous_creation_docs`, `amount_outlier_docs`와 row-level `lone_batch_identity_rows`/`lone_identity_only_rows`를 남기고, `score_bands`는 `amount_outlier_only`, `period_end_concentration`, `simultaneous_creation`, `lone_batch_identity`, `multi_signal_batch`로 나눈다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `batch_review_docs`를 우선 사용한다.
  - `BatchAnomaly` 라벨은 감사 이슈 subset이다. `rule_truth_L4_06`과 1:1로 같다고 가정하면 안 된다.
  - detector는 row annotation에 `reason_codes`와 `primary_reason`을 남긴다. 동일 행이 기말 집중, 동시 생성, 금액 이상에 동시에 걸릴 수 있으므로 하위 band 합계는 전체 batch review 문서 수와 일치하지 않을 수 있다.
  - L4-06 단독 hit는 정상 자동/배치 처리일 수 있으므로 case priority는 `batch_combo_score`와 독립 보강 룰 그룹 수로 판단한다.
  - PHASE1 사용자 큐는 row-level `anomaly_score`만으로 정렬하면 안 된다. L4-06처럼 단독 점수는 낮지만 결합 근거가 중요한 신호가 묻히지 않도록 `priority_score`, `priority_band`, `batch_combo_bonus`, `priority_adjustment_reasons`를 함께 사용한다.

---

#### Phase 1 공통 운영 한계와 조합 해석

Phase 1은 실무에서 `1차 스크리닝`과 `감사 샘플링 우선순위화`에 사용한다. 단독 부정 판정, 감사 결론 자동화, 동일 임계값의 회사 간 일괄 적용에는 사용하지 않는다.

| 한계                         | 단독 해석                                       | 조합되면 위험해지는 신호                                                 |
| ---------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------ |
| 룰 임계값이 초기 설계값 중심 | false positive가 많을 수 있음                   | 동일 전표/계정에 금액, 시점, 승인, 계정 논리 신호가 2개 이상 결합        |
| 입력 품질 의존               | 컬럼 누락·매핑 오류가 미탐/과탐을 만든다        | `L1-02`, `L1-08` 같은 무결성 신호와 다른 탐지 룰이 동시에 발생           |
| 계정/월/사용자 단위 룰       | 개별 전표 이상을 직접 입증하지 않는다           | 계정 단위 신호(`D01/D02`)와 행 단위 신호(`L3-04`, `L4-03`, `L2-05`) 결합 |
| 정상 반복·시즌성 구분 한계   | 정기 지급, 결산 배부, 감가상각이 걸릴 수 있음   | 반복성인데도 승인 누락, 적요 결손/파손, 역분개, 기말 집중이 같이 존재    |
| 텍스트 룰의 의미 이해 한계   | Phase 1은 의미 부족·우회 표현을 판단하지 않는다 | `L3-08`이 고액, 수기전표, 기말, D02 패턴 변화와 결합                     |

운영 원칙:
- 단일 룰 hit는 `검토 후보`로 둔다.
- 다른 성격의 신호가 2개 이상 결합되면 review queue 우선순위를 올린다.
- `통제 실패(L1-05/L1-06/L1-07) + 시점 이상(L3-04/L3-07/L1-08) + 금액/계정 이상(L4-03/L4-04/L3-10)` 조합은 Phase 1에서 가장 먼저 보는 고위험 축이다.
- D01/D02는 전기 대비 분석적 절차 신호이므로, 예산·TB 변동·사업 이벤트·계정체계 변경 확인 없이 결론으로 쓰지 않는다.

#### Variance 독립 트랙 리포팅 (기존회사 전용)

> D01·D02 룰 카드는 PHASE1-2로 이관됨 → [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD). 아래는 리포팅 운영 노트만 잔존.

기존회사에서는 Variance 트랙이 활성화되지만, D01/D02는 row-level 기본 가중치에 포함하지 않는다.
두 룰의 `severity`는 감사상 중요도와 정렬/설명 보조값일 뿐, 전표 단위 anomaly score 가중치가 아니다.

| 항목                         | 운영 기준                                                                                            |
| ---------------------------- | ---------------------------------------------------------------------------------------------------- |
| row-level score              | D01/D02 모두 `0.0`                                                                                   |
| Rule Metrics precision/FP/FN | 포함하지 않음                                                                                        |
| 별도 리포트 섹션             | `Analytical Review Signals`                                                                          |
| 평가 단위                    | `fiscal_year + company_code + gl_account`                                                            |
| 주요 지표                    | review groups, truth coverage, missed truth groups, normal-control review groups, L1~L4 overlap docs |
| case priority 반영           | D01/D02 단독은 승격하지 않고, row/document-level 룰과 겹칠 때 설명 및 우선순위 보강                  |

---

## 3. Phase 2 / PHASE1-2 (이관 — 별도 문서)

> 2026-06-17 분리. 본 DETECTION_RULES.md는 **PHASE1-1 룰(L1~L4 행 단위)** 의 SoT다.
> - **Phase 2 ML/DL 보조 분석**(구 §3 전체) → [DETECTION_RULES_PHASE2_ML.md](DETECTION_RULES_PHASE2_ML.md)
> - **PHASE1-2 family·macro**(L4-02 Benford·L4-05·D01·D02·GR01·GR03) → [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD)
> - 구 §2.5 Variance(D01·D02)·§4.5 Graph Detector(GR) 카드는 DETECTION_RULES_PHASE1-2.MD로 이동.

## 4. Future Local-Only Semantic / Graph Signals

> GR01/GR03 graph detector 카드는 PHASE1-2로 이관됨([DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD) §GR). 아래 표의 Graph 항목은 커버리지 참조용으로만 유지.

> PHASE3 LLM Narrator is removed from the active product path. This section is retained as historical/future design context only. Any future semantic description analysis must be local-first, must not call external LLM/API services, and must not change PHASE1/PHASE2 queue ordering unless a separate local deterministic contract is approved.

| DataSynth 유형             | 카테고리     | Sev | 방법                                | 상태     |
| -------------------------- | ------------ | --- | ----------------------------------- | -------- |
| LatePosting                | ProcessIssue | 2   | 시계열 NLP 복합                     | ⬜       |
| MissingDocumentation       | ProcessIssue | 3   | NLP (설명 실질성 분석)              | ⬜       |
| CircularTransaction        | Graph(GR01)  | 4   | Johnson N-hop 순환 (length_bound=5) | ✅ WU-22 |
| TransferPricingAnomaly     | Graph(GR03)  | 4   | 양방향 IC 엣지 price asymmetry      | ✅ WU-22 |
| TrendBreak (TL4-01/TL2-01) | Statistical  | 4/3 | 설정vs상각 분리                     | ✅       |

### Historical 7-track score idea (deprecated v1)

```
rule(0.15) + xgboost(0.20) + vae(0.15) + benford(0.10) + duplicate(0.15) + nlp(0.10) + graph(0.15)
```

**Phase 3 누적: Tier 1(20) + Tier 2(16) + Tier 3(5) = 41개 유형 커버** *(historical, deprecated v1)*

### Local-only semantic analysis boundary

Phase 1 L3-08 continues to collect missing, blank, or corrupted description signals. It does not attempt semantic adequacy judgment.

Future semantic description analysis may be considered only as local-only NLP or local model inference. It must:

- keep raw ledger data within the workspace;
- avoid external LLM/API calls;
- remain review-supporting rather than fraud-determining;
- expose deterministic fallback behavior;
- keep PHASE1/PHASE2 scoring unchanged unless separately approved.

---

## 5. 제외 유형

### 5.1 Drop — 11개 DataSynth 유형

| 유형                    | 합계 | 제외 사유                                  |
| ----------------------- | ---- | ------------------------------------------ |
| RoundingError           | 3    | 실무 중요성 sev1, false positive 과다      |
| WrongCostCenter         | 0    | 코스트센터 마스터 없이 정합성 판단 불가    |
| DecimalError            | 0    | 소수점 오류는 시스템 레벨에서 방지         |
| LateApproval            | 1    | 승인 로그 데이터 없음                      |
| IncompleteApprovalChain | 1    | 승인 체인 데이터 없음                      |
| UnusualTiming           | 7    | L3-05/L3-06과 완전 중복 → 별도 유형 불필요 |
| RepeatingAmount         | 5    | ExactDuplicateAmount와 중복                |
| UnusuallyLowAmount      | 3    | false positive 과다                        |
| MissingRelationship     | 1    | document_flows 데이터 의존                 |
| CentralityAnomaly       | 0    | 그래프 분석 범위 초과                      |
| AnomalousRatio          | 2    | StatisticalOutlier에 포섭                  |

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

| 항목          | 이 문서 정의                          | settings.py 현재값                                           | DataSynth v1.2.0 실태                                         | 해결 상태 |
| :------------ | :------------------------------------ | :----------------------------------------------------------- | :------------------------------------------------------------ | :-------- |
| 매출 계정     | "4xxx" (K-IFRS 기준)                  | `revenue_account_prefixes: ['4']`                            | gl_account 4xxx 존재 (20%)                                    | ✅ 해결   |
| 승인 한도     | 명시 없음 (회사별)                    | `approval_thresholds: [10M, 100M, 1B, 5B, 10B, 50B]` (6단계) | lognormal mu=14.0 (중앙값 ~120만, 최대 1,000억)               | ✅ 해결   |
| 거래처 식별   | `auxiliary_account_number`            | L2-02에서 사용                                               | 59% 유효 (652K건)                                             | ✅ 해결   |
| 심야 기준     | 22시~06시                             | `midnight_start: 22`                                         | posting_date datetime (시분초 포함)                           | ✅ 해결   |
| 관계사 식별   | GL 계정 prefix 매칭                   | `intercompany_identifiers: ['1150', '2050', '4500', '2700']` | IC GL 1150/2050/4500/2700 존재                                | ✅ 해결   |
| 직무분리 임계 | L1-06 direct SoD + L3-12 review 분리  | `sod_conflict_type` + `work_scope_excess_review_population`  | direct conflict는 L1-06, role/process breadth는 L3-12 sidecar | v80 정리  |
| Benford 위반  | MAD > 0.012                           | `benford_mad_threshold: 0.012`                               | BenfordViolation 157건 라벨 주입                              | ✅ 해결   |
| 필수필드 누락 | `schema.yaml` required 컬럼 NULL 검사 | schema.yaml 참조                                             | MCAR 2% (gl_account, document_type)                           | ✅ 해결   |

### 해결 완료 (v1.2.0)

| 항목                            | 원인                           | 조치                                             | 파일                                      |
| :------------------------------ | :----------------------------- | :----------------------------------------------- | :---------------------------------------- |
| L2-01/L3-02 승인한도 불일치     | 단일 한도 + USD 금액 범위      | KRW 6단계 승인한도 + lognormal mu=14.0           | `settings.py`, `datasynth.yaml`           |
| L1-06 SOD 과탐                  | 41명 소규모 시뮬레이션         | 1,365명 확대, SOD 위반률 3.32% (2026-04-14 실측) | `datasynth.yaml`                          |
| L3-03 관계사 미식별             | `intercompany_identifiers: []` | IC GL prefix 4개 등록                            | `audit_rules.yaml`                        |
| L3-06 심야 미탐지               | posting_date 시간정보 없음     | datetime 전환                                    | `schema.yaml`, DataSynth                  |
| `is_suspense_account` all-False | 한글 키워드만 매칭             | 하이브리드: 텍스트 키워드 OR GL 코드 prefix      | `pattern_features.py`, `audit_rules.yaml` |
| `is_round_number` all-False     | float 소수점 꼬리              | `base.round(0) % unit` 허용                      | `amount_features.py`                      |

### v21 확정 결과 (2026-04-02)

| 항목                  | 값                                                                          |
| :-------------------- | :-------------------------------------------------------------------------- |
| Phase 1 Recall        | 91.4% (2,408 / 2,636)                                                       |
| 전체 Recall           | 92.0% (7,197 / 7,827)                                                       |
| 100% Recall 룰        | 10개 (L1-01, L1-02, L1-03, L4-01, L2-02, L3-05, L3-06, L1-08, L3-08, L2-05) |
| L1-06 flagged         | 1.9% (정상)                                                                 |
| Normal 등급           | 85.2%                                                                       |
| 구조적 한계 (ML 필요) | L2-03(10%), L3-03(4%), L4-04(9%), L4-02(29%) — Phase 2 대상                 |

상세: [test-results/rule-label-gap-analysis.md](../../tests/phase1_rulebase/test-results/rule-label-gap-analysis.md)

### 미해결 (경미 — Phase 2 이후)

| 항목                   | 원인                                                         | 현재 상태                                                                                     | 대상              |
| :--------------------- | :----------------------------------------------------------- | :-------------------------------------------------------------------------------------------- | :---------------- |
| L3-09 적요 키워드 부족 | 확률 체인(0.5%×5%×30%)으로 키워드 주입 건수 극소 — 정상 동작 | GL prefix 기반 탐지 정상 작동. 적요 의미 분석은 active 범위 밖이며 future local-only NLP 후보 | Future local-only |
| trading_partner        | 99.9% NULL (784건)                                           | L3-03 IC GL prefix 매칭으로 대체                                                              | DataSynth Rust    |
| cost_center            | 81.2% NULL                                                   | L2-05 세분화 키 활용도 제한                                                                   | DataSynth Rust    |

### V7 fixed3 patched 갱신 (2026-05-17)

`datasynth_manipulation_v7_candidate_fixed3` patched 빌드 기준 품질 게이트 5종 전부 PASS (final verdict GO, HARD failures 0, SOFT failures 0).

| 게이트                                   | 결과 |
| :--------------------------------------- | :--- |
| Gate 1 — V5 fixed9 generation regression | PASS |
| Gate 2 — accounting substance            | PASS |
| Gate 3 — enrichment criteria split (A/B) | PASS |
| Gate 4 — quality_gate3                   | PASS |
| Gate 5 — no new defects                  | PASS |

Gate 3은 enrichment 컬럼을 두 카테고리로 분리해 판정한다. Category A(occurrence rate)는 정상 모집단 발생률 목표만 검증하고 AUROC는 informational이며, Category B(distribution overlap)는 정상 분포가 manipulation 범위와 겹치는지(AUROC 0.80~0.95 기대)를 검증한다. 상세 산출물은 `artifacts/datasynth_v7_fixed3_patched_quality_verification.md`.

V7 fixed3는 PHASE2 첫 학습의 dataset_version으로 채택되었다 (Stage 5). 갭 단위 결손은 보고되지 않는다.

---

## 7. 성능 평가 지표 체계

| 계층       | 지표                | 용도                                            |
| :--------- | :------------------ | :---------------------------------------------- |
| 1차 (메인) | AUPRC (PR-AUC)      | threshold-free, 불균형에 강건. 지도/비지도 공통 |
| 1차 (메인) | F2-score            | Recall 가중 (부정 놓치는 비용 > 오탐 비용)      |
| 2차 (보조) | MCC                 | 불균형에서도 신뢰할 수 있는 단일 지표           |
| 2차 (보조) | DR@FAR=5%           | "오탐 5% 허용 시 탐지율" — 실무 의사결정용      |
| 3차 (참고) | ROC-AUC             | 모델 간 비교용 (불균형 caveat 명시)             |
| 보고용     | Precision/Recall/F1 | 대시보드 표시 + 감사인 소통용                   |

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

### Tier 3 — Could: Future local-only candidates (5개)

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

| 컬럼명          | 타입  | ACDOCA   | 설명           | 탐지 활용                                |
| --------------- | ----- | -------- | -------------- | ---------------------------------------- |
| `document_id`   | str   | `belnr`  | 전표 ID (UUID) | L1-01, L2-02, L2-03(실무형 보강 시 중요) |
| `company_code`  | str   | `rbukrs` | 회사코드       | L3-03                                    |
| `fiscal_year`   | int   | `gjahr`  | 회계연도       | L1-08                                    |
| `fiscal_period` | int   | `monat`  | 회계기간       | L1-08                                    |
| `posting_date`  | date  | `budat`  | 전기일         | L3-04~L1-08                              |
| `document_date` | date  | `bldat`  | 전표일         | L3-07                                    |
| `gl_account`    | int   | `racct`  | G/L 계정코드   | L1-03, L4-01, L4-04                      |
| `debit_amount`  | float | `wsl(S)` | 차변 금액      | L1-01, L2-01~L2-03, L4-02~L4-03          |
| `credit_amount` | float | `wsl(H)` | 대변 금액      | L1-01, L2-01~L2-03, L4-02~L4-03          |
| `document_type` | str   | `blart`  | 전표유형       | L4-01                                    |

### 권장 컬럼 (10개)

| 컬럼명             | 타입  | ACDOCA  | 설명              | 탐지 활용    |
| ------------------ | ----- | ------- | ----------------- | ------------ |
| `created_by`       | str   | `usnam` | 입력자            | L1-05~L1-07  |
| `source`           | str   | —       | 입력소스          | L3-02, L1-07 |
| `business_process` | str   | —       | 비즈니스 프로세스 | L1-06        |
| `line_number`      | int   | `docln` | 라인번호          | L1-01        |
| `local_amount`     | float | `hsl`   | 현지통화 금액     | 환율 검증    |
| `currency`         | str   | `rwcur` | 통화              | 환율 검증    |
| `cost_center`      | str   | `rcntr` | 코스트센터        | —            |
| `profit_center`    | str   | `prctr` | 손익센터          | —            |
| `line_text`        | str   | `sgtxt` | 적요              | L3-08        |
| `header_text`      | str   | `bktxt` | 헤더 텍스트       | L3-08        |

### 레이블 컬럼 (2개)

| 컬럼명       | 타입 | 설명                        | 분포                   |
| ------------ | ---- | --------------------------- | ---------------------- |
| `is_fraud`   | bool | 개발 검증용 fraud 라벨 여부 | True 1.9%, False 98.1% |
| `is_anomaly` | bool | anomaly 여부                | True 7.5%, False 92.5% |

### DataSynth 확장 예정 컬럼

| 컬럼명                | 타입     | 용도                          |
| --------------------- | -------- | ----------------------------- |
| `has_attachment`      | bool     | 증빙 첨부 여부                |
| `supporting_doc_type` | str      | 세금계산서/카드/현금영수증 등 |
| `delivery_date`       | date     | 납품일 (컷오프 검증)          |
| `invoice_amount`      | float    | 세금계산서 금액               |
| `tax_amount`          | float    | 부가세 금액                   |
| `supply_amount`       | float    | 공급가액                      |
| `changed_by`          | str      | 변경자                        |
| `change_date`         | datetime | 변경 일시                     |
| `changed_field`       | str      | 변경 필드명                   |
| `ip_address`          | str      | 접속 IP                       |
| `document_number`     | int      | 순차 전표번호 (UUID 별도)     |
| `approval_level`      | int      | 승인 레벨                     |

---

## 부록 C: 도메인 용어 ↔ 코드 매핑

| 감사 용어   | 영문           | DataSynth 컬럼    | 코드 변수             |
| ----------- | -------------- | ----------------- | --------------------- |
| 전표        | Journal Entry  | `document_id`     | `journal_entry`, `je` |
| 전기일      | Posting Date   | `posting_date`    | `posting_date`        |
| 전표일      | Document Date  | `document_date`   | `document_date`       |
| 적요        | Line Text      | `line_text`       | `line_text`           |
| 차변        | Debit          | `debit_amount`    | `debit_amount`        |
| 대변        | Credit         | `credit_amount`   | `credit_amount`       |
| 역분개      | Reversal       | `xstov` flag      | `is_reversal`         |
| 수기전표    | Manual JE      | `source='manual'` | `is_manual_je`        |
| 관계사 거래 | Intercompany   | `company_code` 쌍 | `is_intercompany`     |
| 총계정원장  | General Ledger | `gl_account`      | `gl_account`          |
| 이상징후    | Anomaly        | `is_anomaly`      | `anomaly`             |
| 입력자      | Created By     | `created_by`      | `created_by`          |
| 전표유형    | Document Type  | `document_type`   | `document_type`       |

---

## 부록 D: Fraud Red Flags (참고)

정상 전표에 부여된 의심 징후 (211건, 전부 is_fraudulent=False).
Phase 2 ML에서 **False Positive 내성 훈련**에 활용.

| pattern_name                     | 건수 | category    | strength | confidence |
| -------------------------------- | ---- | ----------- | -------- | ---------- |
| month_end_timing                 | 32   | Timing      | Weak     | 0.10       |
| round_dollar_amount              | 31   | Transaction | Weak     | 0.15       |
| vague_description                | 20   | Document    | Weak     | 0.15       |
| after_hours_posting              | 18   | Timing      | Weak     | 0.15       |
| repeat_amount_pattern            | 15   | Transaction | Weak     | 0.18       |
| benford_first_digit_deviation    | 12   | Transaction | Weak     | 0.12       |
| weekend_transaction              | 12   | Timing      | Weak     | 0.12       |
| unusual_account_combination      | 11   | Account     | Weak     | 0.20       |
| invoice_without_purchase_order   | 11   | Document    | Moderate | 0.30       |
| employee_vacation_fraud_pattern  | 10   | Employee    | Moderate | 0.45       |
| amount_just_below_threshold      | 10   | Transaction | Moderate | 0.35       |
| missing_supporting_documentation | 9    | Document    | Moderate | 0.30       |
| dormant_vendor_reactivation      | 7    | Vendor      | Moderate | 0.35       |
| new_vendor_large_first_payment   | 5    | Vendor      | Moderate | 0.40       |
| unusual_vendor_payment_pattern   | 4    | Vendor      | Moderate | 0.30       |
| vendor_no_physical_address       | 2    | Vendor      | Strong   | 0.15       |
| po_box_only_vendor               | 2    | Vendor      | Strong   | —          |

---

## 관련 문서

- [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) — 법규·기준서·도메인 지식 근거
- [completed/raw-plan/05-detection.md](../archive/completed/raw-plan/05-detection.md) — detection 구현 가이드
- [completed/raw-plan/05a-detection-ml.md](../archive/completed/raw-plan/05a-detection-ml.md) — Phase 2b ML 탐지기 설계
- [debugging.md](../debugging.md) — engine.py rules 버그 기록
- [E2E 테스트 결과](../../tests/modules/test_detection/test-results/e2e-detection-datasynth.md)

---

## 부록 E: RuleExplanation 표준 스키마 (2026-05-17)

Sprint B3-meta에서 UI 표시 영역을 변경하지 않고, 후속 UI/export 통합이 사용할 설명 메타데이터만 추가했다. 표준 스키마는 `src/detection/explanation_schema.py`의 frozen `RuleExplanation`이며, 조회 진입점은 `src/detection/explanation_registry.py`다.

| field               | 타입  | 의미                              |
| ------------------- | ----- | --------------------------------- |
| `principle`         | `str` | 감사 원칙 또는 통제 기대사항      |
| `violation_reason`  | `str` | 룰이 검토 대상으로 올린 이유      |
| `audit_next_action` | `str` | 감사인이 다음에 수행할 확인 절차  |
| `reference`         | `str` | PCAOB AS / ISA / 분석적 절차 근거 |

JSON 예시:

```json
{
  "principle": "Journal entries should preserve debit and credit balance by document.",
  "violation_reason": "The document-level debit and credit totals differ beyond the configured rounding tolerance.",
  "audit_next_action": "Recalculate the entry, inspect correction or reversal evidence, and confirm whether the imbalance is a posting error or permitted rounding difference.",
  "reference": "PCAOB AS 1105; ISA 240"
}
```

활성 RuleExplanation 메타데이터 위치:

| 룰 ID      | 위치                                                             | 인스턴스       |
| ---------- | ---------------------------------------------------------------- | -------------- |
| `D01`      | `src/detection/variance_layer.py::VARIANCE_RULE_EXPLANATIONS`    | `D01` key      |
| `D02`      | `src/detection/variance_layer.py::VARIANCE_RULE_EXPLANATIONS`    | `D02` key      |
| `L1-01`    | `src/detection/integrity_layer.py::INTEGRITY_RULE_EXPLANATIONS`  | `L1-01` key    |
| `L1-02`    | `src/detection/integrity_layer.py::INTEGRITY_RULE_EXPLANATIONS`  | `L1-02` key    |
| `L1-03`    | `src/detection/integrity_layer.py::INTEGRITY_RULE_EXPLANATIONS`  | `L1-03` key    |
| `L1-04`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L1-04` key    |
| `L1-05`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L1-05` key    |
| `L1-06`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L1-06` key    |
| `L1-07`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L1-07` key    |
| `L1-07-02` | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L1-07-02` key |
| `L1-08`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L1-08` key    |
| `L2-01`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L2-01` key    |
| `L2-02`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L2-02` key    |
| `L2-03`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L2-03` key    |
| `L2-04`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L2-04` key    |
| `L2-05`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L2-05` key    |
| `L3-02`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L3-02` key    |
| `L3-03`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L3-03` key    |
| `L3-04`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L3-04` key    |
| `L3-05`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L3-05` key    |
| `L3-06`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L3-06` key    |
| `L3-07`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L3-07` key    |
| `L3-08`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L3-08` key    |
| `L3-09`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L3-09` key    |
| `L3-10`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L3-10` key    |
| `L3-11`    | `src/detection/evidence_detector.py::EVIDENCE_RULE_EXPLANATIONS` | `L3-11` key    |
| `L3-12`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L3-12` key    |
| `L4-01`    | `src/detection/fraud_layer.py::FRAUD_RULE_EXPLANATIONS`          | `L4-01` key    |
| `L4-02`    | `src/detection/benford_detector.py::BENFORD_RULE_EXPLANATIONS`   | `L4-02` key    |
| `L4-03`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L4-03` key    |
| `L4-04`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L4-04` key    |
| `L4-05`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L4-05` key    |
| `L4-06`    | `src/detection/anomaly_layer.py::ANOMALY_RULE_EXPLANATIONS`      | `L4-06` key    |
