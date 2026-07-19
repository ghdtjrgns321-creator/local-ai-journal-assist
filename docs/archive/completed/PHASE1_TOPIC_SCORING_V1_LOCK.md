# PHASE1 Topic Scoring V1 Lock

> **[ARCHIVED 2026-06-16]** docs/spec/ → docs/archive/completed/ 로 이관됨. 현행 점수체계 단일 출처(SoT)는 `docs/spec/PHASE1_TIER_EVIDENCE_BASIS.md`(근거)·`docs/spec/PHASE1_TIER_SCORING_SPEC.md`(구현 계약)·`docs/spec/HIGH_COMBO_GROUNDING.md`(조합 근거)다. 본 문서는 구 가중합 v1 lock의 역사 기록으로만 보존한다.

> Superseded by docs/spec/PHASE1_TIER_EVIDENCE_BASIS.md (tier 체계, 2026-06-14). 본 v1 lock의 가중합·floor 숫자값·band 컷(high≥0.90/med≥0.75)은 근거 없는 숫자 정밀도로 폐기됐고, band는 명명된 tier(순서형 HIGH/MEDIUM/LOW/CONTEXT)로 직접 결정한다. 주제는 7개→6개(intercompany_cycle 삭제→PHASE1-2 family 이관). 본 문서는 조합 근거(Fraud Combo Scoring Policy)의 역사적 출처로만 참조한다.

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

Updated: 2026-05-08
Status: Locked for v1 implementation

Completion record: `docs/archive/completed/PHASE1_TOPIC_SCORING_V1_COMPLETION.md`

## Decision Summary

PHASE1 result ranking is locked to six auditor-facing topics (7→6, intercompany_cycle 삭제→PHASE1-2 family 이관, SoT §1·§7.3). Legacy queue/status labels such as `Audit Risk`, `조작 후보`, `맥락 검토대상`, `추가검토사항`, `우선 위험신호`, and `저우선 위험신호` must not be used as ranking topics.

The six official topics are:

1. 원장기록·데이터정합성
2. 승인·권한·업무분장 통제
3. 결산·기간귀속·입력시점
4. 계정분류·거래실질 불일치
5. 중복·상계·자금유출
6. 수익·금액·모집단 통계 이상

> 관계사·내부거래·순환구조 topic은 삭제됨. 관계사·내부거래·순환거래는 PHASE1-2 family(graph/relational)로 이관됨(SoT §7.3). PHASE1-1 점수경로에서 IC01~IC03·GR01/GR03 제거, L3-03만 account_logic booster로 잔존.

`조작 후보` is not a queue (8번째 topic/tab을 만들지 않으며, 위 6주제 기준으로 한다). Fraud/manipulation interpretation is represented only through `fraud_scenario_tags`.

## Locked Corrections

The A/B/C/D synthesis is accepted as the v1 implementation basis with these corrections:

- `L2-01`
  - `final_topic`: `중복·상계·자금유출`
  - `secondary_topic`: `승인·권한·업무분장 통제`
  - Rationale: threshold gaming is an approval-control question, but the rule belongs in the duplicate/outflow review topic for PHASE1 topic ranking consistency.
- `L1-08`
  - `final_topic`: `결산·기간귀속·입력시점`
  - `secondary_topic`: `원장기록·데이터정합성`
  - Rationale: period mismatch is primarily reviewed as cutoff/period attribution in v1, while preserving the ledger-integrity meaning as secondary context.
- `L3-05` and `L3-06`
  - v1 role: `booster`
  - standalone review queue: not created in v1
  - Rationale: weekend/holiday and after-hours signals are broad operational populations and should not seed standalone full-review queues in v1.
- `macro_only` rules
  - standalone row score: `0`
  - transaction ranking contribution: only through `macro_context_score` when a case already has a primary row-level hit
  - Applies to: `L4-02`, `Benford`, `D01`, `D02`, and other macro-only findings.

## Scoring Contract

> → tier로 대체 (상단 supersede 참조). 아래 가중합 계수(0.62 등)·floor 숫자값·band 컷(high≥0.90/medium≥0.75)은 근거 없는 임의 숫자로 폐기됐다. band는 SoT §4~§6의 명명된 tier(순서형 HIGH/MEDIUM/LOW/CONTEXT)로 직접 결정하며, 연속점수는 tier 내부 정렬 tiebreak 전용이다. 아래 식은 역사 기록으로만 남긴다.

Rule score:

```text
rule_score =
  signal_strength
  * (severity / 5)
  * evidence_factor
  * role_factor
```

Evidence factors:

```text
strong = 1.00
medium = 0.75
weak = 0.45
info = 0.25
```

Role factors:

```text
primary = 1.00
booster = 0.65
combo_only = 0.35
macro_only = 0.00
```

Topic score:

```text
topic_score =
max(applicable_floor,
  min(topic_cap,
      0.62 * max_primary_rule_score
    + 0.12 * secondary_evidence_score
    + 0.10 * corroboration_score
    + 0.08 * materiality_score
    + 0.05 * repeat_score
    + 0.03 * macro_context_score
  )
)
```

Bands (→ tier로 대체, 상단 supersede 참조 — 아래 band 컷은 근거 없는 임의 숫자로 폐기, 역사 기록):

```text
high >= 0.90
medium >= 0.75
low >= 0.20
context_only < 0.20
```

Implementation note (역사 기록): because the formula gives primary evidence a 0.62 base contribution, most `high` cases should be created by explicit floor/combo/materiality logic. That is intentional for v1 unless later calibration proves the high band is too sparse. → SoT가 자인한 사실(band는 가중합이 아니라 floor/combo가 만든다)이며, tier 체계는 이 숫자 우회를 제거하고 조건→tier 직접 매핑으로 대체했다(상단 supersede 참조).

### Fraud Combo Scoring Policy

PHASE1 v1은 별도 `조작 후보` topic 또는 tab을 만들지 않는다. 금감원 감리 사례, ISA 240, PCAOB AS 2401, ISA 550, K-SOX 기반의 강한 조작 의심은 기존 6개 topic 안에서 표현한다. (역사 기록: 아래 floor/bonus 숫자값은 tier로 대체됨 — 상단 supersede 참조. 조합 조건은 SoT §4~§6 tier 트리거의 근거 출처로 남는다.)

```text
topic_score =
  existing_topic_score
+ fraud_combo_bonus
+ fraud_combo_floor
```

`fraud_combo_bonus`는 보강 신호이며, `fraud_combo_floor`는 최소 band 보장 장치다. 단순 bonus만으로는 주제별 Top N 또는 High band에 진입하지 못하는 조작 조합이 생기므로, 아래 정책을 만족하면 해당 topic score에 명시적 floor를 적용한다. Floor는 fraud 확정 판정이 아니라 감사 검토 우선순위 승격이다.

| Subtype | 감사/금감원 근거 | 관련 룰 | Medium floor 조건 | High floor 조건 | `fraud_scenario_tags` | 승격 topic |
|---|---|---|---|---|---|---|
| 가공전표 의심 | 금감원 감리 189건 중 가공 전표 50건으로 최다 패턴. ISA 240 A45와 PCAOB AS 2401은 수기/조정 전표, 희소 계정, 비정상 계정, 설명 부족, 금액·분포 이상을 journal entry risk 특성으로 본다. | L4-01, L4-03, L3-02, L4-04, L2-03, L4-06, 보조 L3-04 | `L4-01 + L3-04`, 또는 `L4-03 + L4-06 + L3-02`이면 `0.45~0.60` | `(L4-01 or L4-03) + L3-02 + (L4-04 or L2-03)`이면 `0.75` | `가공전표 의심` | 수익·금액·모집단 통계 이상 |
| 결산수정 조작 의심 | 금감원 감리 결산 수정 조작 27건. ISA 240 §32/A45와 PCAOB AS 2401은 기말/마감후 전표, 설명 부족, 비정상·희소 계정, 사후 조정을 management override 위험으로 본다. | L3-04, L3-07, L3-11, L1-08, L4-03, L3-08, L3-10, L4-04, 보조 L3-02 | `L3-04 + L3-02 + L3-08`이면 `0.45~0.60` | `(L3-04 or L3-07 or L3-11 or L1-08) + L4-03 + (L3-08 or L3-10 or L4-04)`이면 `0.75`; `L3-11 + (L4-01 or L4-03)`도 `0.75` | `결산수정 조작 의심` | 결산·기간귀속·입력시점 |
| 횡령은폐 의심 | 금감원 감리 횡령 은폐 24건과 대형 횡령 사례. K-SOX 통제 우회, 승인·업무분장 실패, 자산 유용 은폐 위험에 대응한다. | L2-02, L2-03, L2-05, L2-01, L1-05, L1-06, L1-07, L1-04, L3-12, 보조 L3-02 | `L2-05 + L3-12 + L3-02`, 또는 `L2-01 + (L1-04 or L1-05)`이면 `0.45~0.70` | `(L2-02 or L2-03 or L2-05) + (L1-05 or L1-06 or L1-07 or L1-04)`이면 `0.75` | `횡령은폐 의심` | 중복·상계·자금유출 |
| ~~순환거래 의심~~ (PHASE1-1 제거) | 금감원 감리 순환거래 10건, 특수관계자 거래 중점심사. ISA 550은 특수관계자 거래의 사업상 합리성, 조건, 승인, intercompany balance 대사를 요구한다. | ~~L3-03, IC01, IC02, IC03, L4-03, L3-04, L3-11, L4-04, D01, D02~~ | (역사 기록, PHASE1-1 운영 기준 아님) | (역사 기록) | `순환거래 의심` | → PHASE1-2 family 이관 |
| 승인우회 조작 의심 | 금감원 감리 승인/SoD 위반 5건과 횡령 은폐의 전제 조건. K-SOX와 내부회계관리제도 운영 효과성 관점에서 승인권한·업무분장 실패를 본다. | L1-04, L1-05, L1-06, L1-07, L1-09, L3-02, L3-05, L3-06, L4-03, L3-12 | `approval_bypass + (L3-02 or L3-05 or L3-06)`, `L1-09 + L4-03 + L3-02`, 또는 `L3-12 + (L1-05 or L1-07)`이면 `0.60` 전후 Medium | `(L1-04 or L1-05 or L1-06 or L1-07) + (L4-03 or L3-11 or (L3-04 + L3-02) or (L3-06 + L3-02))`이면 `0.75` | `승인우회 조작 의심` | 승인·권한·업무분장 통제 |

계정분류·거래실질 불일치 topic은 단독 조작 subtype을 남발하지 않는다. `L1-03`, `L2-04`, `L3-01`, `L3-09`, `L3-10`, `L4-04`는 다른 조작 combo에 붙을 때 해당 topic의 floor를 높이는 booster 축으로 사용한다. 예를 들어 결산시점 + `L3-10`은 결산수정 조작 의심을 강화하고, 수익/금액 이상 + `L4-04`는 가공전표 의심을 강화하며, 자금유출 + `L3-09`는 횡령은폐 의심을 강화한다.

원장기록·데이터정합성 topic은 fraud high 승격 topic이 아니라 품질 게이트다. `L1-01`, `L1-02`, `L1-08`, 일부 `L3-08`은 다른 조작 combo의 concealment/context booster로만 fraud 해석에 참여한다. 원장기록 topic 자체는 차대변 불균형, 필수필드 누락, 기간/설명 누락의 처리 가능성과 원장 신뢰성을 우선 표시한다.

## Topic Policy

| Topic | Primary rules | Booster rules | Combo-only | Macro-only | Standalone-excluded rules |
|---|---|---|---|---|---|
| 원장기록·데이터정합성 | L1-01, L1-02 | L3-08, L1-08 | none | L4-02/Benford | L3-08, L4-02, Benford |
| 승인·권한·업무분장 통제 | L1-04, L1-05, L1-06, L1-07, L1-09, L3-02 | L3-05, L3-06, L4-05, L3-10, L2-01 | L3-12 | none | L3-05, L3-06, L3-10, L3-12, L4-05 |
| 결산·기간귀속·입력시점 | L1-08, L3-04, L3-07, L3-11 | L3-05, L3-06, L3-08, L4-05 | none | D02 | L3-05, L3-06, L3-08, L4-05, D02 |
| 계정분류·거래실질 불일치 | L1-03, L2-04, L3-01, L3-09, L4-04 | L3-10, L3-03 | none | D01 | L3-03, L3-10, D01 |
| 중복·상계·자금유출 | L2-01, L2-02, L2-03, L2-05 | L1-05, L1-07, L3-12 | none | none | routine L2-01, L3-12 standalone |
| ~~관계사·내부거래·순환구조~~ (PHASE1-1 제거 → PHASE1-2 family 이관, SoT §7.3) | ~~IC01, IC02, IC03~~ → family | ~~L3-03~~ (L3-03만 계정분류 topic의 account_logic booster로 잔존), L4-04 | none | D01, D02 | — |
| 수익·금액·모집단 통계 이상 | L4-01, L4-03 | L3-10, L4-02/Benford only as conditional row booster | L4-06 | L4-02/Benford, D01, D02 | L4-02, Benford, L4-06, D01, D02 |

### 관계사·내부거래·순환구조 topic — IC01 evidence level floor 차별 (2026-05-23, D065)

> 이관 (2026-06-14): intercompany_cycle topic은 삭제됨. 관계사·내부거래·순환거래는 PHASE1-2 family(graph/relational)로 이관됐다(SoT §7.3). IC01~IC03은 PHASE1-1 점수경로에서 제거됐고, L3-03만 account_logic booster로 잔존한다. 아래 IC01 evidence level floor 차별 수치는 **역사 기록**이며 PHASE1-1 운영 기준이 아니다. IC sidecar 정책의 구현 정합은 family 이관 시 별도 처리한다.

Primary rules `IC01, IC02, IC03` 본문은 변경하지 않는다. 외부 rule id 는 `IC01` 단일 유지. floor 차별은 `score_aggregator._apply_intercompany_exception_corroboration()` 가 IC01 hit row 의 `ic01_evidence_level` sidecar 를 `DetectionResult.metadata["row_sidecar"]` 에서 read 하여 처리한다 (저장 위치 상세: `docs/spec/RULE_DETAIL_METADATA_V1_LOCK.md` §IC01 Evidence Level Sidecar Policy — Sidecar 저장 위치 절).

```
조합                                                  floor             비고
────────────────────────────────────────────────────────────────────────────────────────────
IC01 hit + ic01_evidence_level == "high", 단독        Medium 0.40       명시적 미대사 근거 (master 부재)
IC01 hit + ic01_evidence_level == "review", 단독      Low 0.20          review-only data quality signal
IC02 단독                                              Low 0.20          기존 유지
IC03 단독                                              Low 0.20          기존 유지
IC02 + IC03 (IC01 없음)                                Medium 0.40       2 개 이상 IC 예외 결합 (기존 유지)
IC01(high) + IC02 / IC03                               Medium 0.40       2 개 이상 IC 예외 결합 (기존 유지)
IC01(review) + IC02 / IC03                             Medium 0.40       2 개 이상 IC 예외 결합 (기존 유지)
```

Review-level confirmed 격상 방지 (2026-05-23 보정):

- IC01 review-level 은 `details["IC01"]` score 가 `0.0` 으로 유지된다 (`intercompany_rules.ic01_unmatched_intercompany` 의 review 분기). high 만 `score = 1.0`.
- `score_aggregator._extract_ic01_evidence_level()` 가 `metadata["row_sidecar"]["ic01_evidence_level"]` 에서 evidence level 을 read 하여 Low floor (0.20) 만 부여한다. `details["IC01"] = 0` 이므로 `flagged_rules` / case seed / ground-truth 평가의 `> 0` 비교에서 confirmed violation 으로 격상되지 않는다.
- 근거: `AGENTS.md` "review-only signals must not become confirmed violations".

정책 정합 지점:

- `src/detection/score_aggregator.py::_apply_intercompany_exception_corroboration()` (D065 갱신, line 1001~1110)
- `src/detection/score_aggregator.py::_extract_ic01_evidence_level()` — `metadata["row_sidecar"]` read + 구버전 `details` fallback
- `src/detection/intercompany_matcher.py::_build_result()` — `details` 는 numeric only, sidecar 는 `metadata["row_sidecar"]` 로 부착
- `src/detection/constants.py::RISK_THRESHOLDS` (`MEDIUM=0.40`, `LOW=0.20`) — 변경 없음
- `src/detection/constants.py::SEVERITY_MAP` (`IC01=3`, `IC02=2`, `IC03=2`) — 변경 없음
- `intercompany_exception_reasons` 문자열의 IC01 hit 표기는 `IC01[high]` / `IC01[review]` qualifier 부착. base rule id `IC01` 단일 유지.

본 floor 차별은 PHASE1 truth recall 직접 추구가 아니라 도메인 정합성 보강이다 (`feedback_phase1_truth_recall_guard`). evidence=`high` 만 IFRS 10 §B86 / K-IFRS 1110 / ISA 600 의 "그룹 내부거래 양측 대사 실패" 회계 evidence 로 인정하고, evidence=`review` 는 review queue 진입 가능한 data quality 수준으로 분류한다.

## Anti-fitting calibration notes

2026-05-08 이후 policy lock은 `datasynth_manipulation` truth 분포를 맞추기 위해 약한 rule 조합을 floor로 추가하지 않는다. 금감원/ISA/PCAOB 근거로 인정되는 조합만 fraud combo floor를 적용하고, datasynth truth 분포 때문에 발견된 약한 조합은 badge, context, tie-break 후보로만 취급한다.

| Weak combination | Floor policy | Allowed handling |
|---|---|---|
| `L3-02 + L3-04 + L3-12` | 가공전표/결산수정 Medium floor 금지 | 수기 + 결산 + 업무범위 집중 context. `L4-03`, `L3-08`, `L3-10`, `L4-04`, `L3-11`, 수익/금액/희소/중복 근거가 붙을 때만 floor 검토 |
| `(L1-04 or L1-05 or L1-06 or L1-07) + L3-02 + L3-12` | 횡령은폐 Medium floor 금지 | 승인통제 topic의 보조 context. 중복/상계/자금유출(`L2-02`, `L2-03`, `L2-05`) 근거가 붙을 때만 횡령은폐 floor |
| `L3-03 + L3-05 + (L3-02 or L3-12)` | 순환거래 High floor 금지 | 관계사 + 휴일/수기/업무범위 context. repeat/cycle/IC exception과 금액·시점·불일치 근거가 붙을 때만 High |
| `approval_bypass + L3-02`, `approval_bypass + L3-05`, `approval_bypass + L3-06` | 승인우회 High floor 금지 | 승인통제 Medium. High는 `L4-03`, `L3-11`, `L3-04 + L3-02`, `L3-06 + L3-02` 같은 강한 근거 필요 |

Weak/FSS-supported floor classification:

| Classification | Allowed floor behavior | Examples |
|---|---|---|
| FSS/ISA/PCAOB-supported High | Keep High floor | revenue/amount outlier + manual + rare/duplicate; timing seed + high amount + weak description/sensitive/rare; outflow/duplicate + approval bypass; related-party/IC + amount/timing + repeat/cycle |
| Domain-supported Medium | Keep Medium floor only | approval bypass + manual context; approval bypass + non-business-day context; approval bypass + after-hours context; related-party/IC + amount/timing without repeat/cycle |
| Weak auxiliary context | No fraud floor; badge/tie-break/context only | `L3-02 + L3-04 + L3-12`; approval bypass + `L3-02 + L3-12` without outflow; `L3-03 + L3-05 + (L3-02 or L3-12)` |

`L3-12`는 fraud floor의 핵심 조건이 아니라 booster/context다. `fraud_scenario_tags`는 정렬 key가 아니며, floor가 적용되는 경우에만 `topic_score_breakdown.fraud_combo_policy_ids`에 policy reason을 남긴다.

## Ranking Rules

- 1차 정렬은 `composite_sort_score` 내림차순 (§9.3 audit 2026-05-14, lock 문서 `artifacts/archive/tier_superseded_20260615/phase1_sort_composite_lock.md`).
- `composite_sort_score` 정의:

  ```text
  composite_sort_score =
      1.0 * topic_score
    + 0.3 * max_primary_rule_score
    + 0.3 * audit_evidence_score
    + 0.3 * corroboration_score
    + 0.1 * min(independent_evidence_count / 5.0, 1.0)
  ```

  - `topic_score` 는 case 의 `primary_topic` 점수.
  - `max_primary_rule_score`, `audit_evidence_score`, `corroboration_score` 는 `topic_score_breakdown[primary_topic]` 의 동명 필드.
  - `independent_evidence_count` 는 case 의 `rule_evidence_summary` 안에서 `scoring_role=='primary'` 인 distinct rule_id 수.
- 보조 tiebreak: `triage_rank_score desc → total_amount desc → rule_count desc`. `total_amount` 는 1차 결정자에서 보조 결정자로 격하한다 (§9.2 audit §2.1 — approval high band 에서 nontruth 평균 amount 가 truth 보다 1.8x 큼).

### Multi-Dataset 검증 (2026-05-14, T4)

> 본 절은 7개 topic 시점(2026-05-14)의 역사적 측정 기록이다. 측정 수치는 당시 조건의 사실이므로 보존한다. 현행 주제는 6개(intercompany_cycle 삭제→PHASE1-2 family 이관).

- 검증 데이터셋: `v126_profiled` (lock baseline, 14342 cases), `v133_archive datasynth_manipulation` (4861 cases),
  `datasynth_manipulation_v2` (11116 cases). truth 각 420건. `datasynth_v122_profiled` 는 active primary 부재로
  defer.
- 산출물: [`artifacts/archive/tier_superseded_20260615/phase1_sort_composite_multi_dataset_lock.md`](../../artifacts/archive/tier_superseded_20260615/phase1_sort_composite_multi_dataset_lock.md)
  / [`artifacts/archive/tier_superseded_20260615/phase1_sort_composite_multi_dataset_lock.json`](../../artifacts/archive/tier_superseded_20260615/phase1_sort_composite_multi_dataset_lock.json).
- 결과 요약 — `max_primary_rule_score` universal positive 는 다중 데이터셋에서 재확인 (3개 dataset / 7개 topic
  에서 -방향 0건). 단, `manipulation_v2` 의 `closing_timing` 도메인에서 AB_C3 - AB_C0 = -34 로 도메인 충돌 가드
  (≤ 5/topic) 를 위반. PHASE1 평탄 가중치가 substantive mutation 데이터 (DR/CR 패턴 부여, IC GL prefix 강제) 에서
  closing_timing truth 를 baseline 대비 손해보는 것이 실증됨.
- 종합 판정: **DEFER**. composite_sort_score 가중치는 변경하지 않으며 (truth recall 직접 추구 금지 정책,
  `feedback_phase1_truth_recall_guard`), v126_profiled 단일 lock 을 유지한다. closing_timing 도메인 ranking 은
  PHASE2 ML 학습 영역으로 이관 (도메인별 가중치 학습).
- 회귀 가드 갱신: `approval_control:high` 가드는 절대치 12 (v126 단일 측정) → 비율 기반 **Top200 truth_doc /
  high_cases ≥ 2.0%** 로 lock. v126_profiled 측정 2.45%, v133_archive 46.30%, manipulation_v2 61.77% 모두 통과.
  본 가드는 Layer C SOFT WARN (baseline 회귀 방지선) 이며 가중치 조정의 근거로 사용 금지.
- `topic_score` 단독 정렬은 보조 토글로만 유지 (legacy compatibility).
- 2026-05-15 Decision #3 선택 A(`closing_timing` 전용 `audit_evidence_score` weight 0.0) 는 측정 후 롤백했다.
  `manipulation_v2`의 `closing_timing` AB_C3 - AB_C0 손실이 -34로 유지되어 도메인 충돌 해소 가드(≤5)를
  통과하지 못했다. 세부 측정은
  [`artifacts/archive/tier_superseded_20260615/phase1_sort_composite_domain_override_lock.md`](../../artifacts/archive/tier_superseded_20260615/phase1_sort_composite_domain_override_lock.md)
  에 남기고, Decision #3은 선택 C로 전환한다.
- A case with no primary hit for the topic must not enter the topic Top N when all signals are `booster`, `combo_only`, or `macro_only`.
- `standalone_rankable=False` rules cannot seed a case by themselves.
- The same document/case may appear in more than one topic. Each topic gets its own rank, and UI should show cross-topic links rather than merging topics into one queue.
- `fraud_scenario_tags`, `review_state`, and `signal_status` are display/context fields, not sort keys.

## Implementation Order

1. `src/detection/rule_scoring.py`
   - Extend `RuleScoringMetadata` with `final_topic`, `secondary_topics`, `standalone_rankable`, `floor_policy_ids`, `combo_policy_ids`, and `fraud_scenario_tags`.
   - Add a seven-topic registry.
   - Include topic fields in `NormalizedRuleEvidence`.
   - Preserve existing `evidence_type`, `normalized_score`, and `scoring_role` behavior.
2. Add `src/detection/topic_scoring.py`
   - `compute_topic_scores()`
   - `apply_topic_floors()`
   - `apply_combo_floors()`
   - `compute_fraud_scenario_tags()`
   - `pick_primary_topic()`
3. `src/detection/score_aggregator.py`
   - Keep existing `anomaly_score` and `risk_level`.
   - Ensure `macro_only` remains row score 0.
   - Ensure `standalone_rankable=False` rules do not trigger standalone row/case escalation.
   - Keep `L4-06` and `L3-12` escalation only through evidence-group conditions.
   - 행 `RISK_THRESHOLDS`(HIGH=0.50 / MEDIUM=0.25 / LOW=0.10, `src/detection/constants.py`)는 case `priority_band`(High=0.90 / Medium=0.75)와 다른 축이다. 행 risk_level은 `anomaly_score` 정규화 합산 기준이며, case priority_band는 topic score 기준이다. 동일 case 내에서 두 값이 달라도 모순이 아니다 (`artifacts/archive/tier_superseded_20260615/phase1_score_band_audit.md` §4-2, `artifacts/archive/tier_superseded_20260615/phase1_score_band_audit_after.md`).
4. `src/detection/phase1_case_builder.py`
   - Replace hard-coded queue/theme maps with registry-based topic mapping.
   - Use `compute_topic_scores()` for case ranking.
   - Keep legacy queue aliases only for compatibility.
   - Remove generation of manipulation/additional-review/low-signal style primary queues.
   - Store `fraud_scenario_tags` separately.
5. `src/models/phase1_case.py`
   - Add `primary_topic`, `primary_topic_label`, `topic_scores`, `topic_score_breakdown`, `secondary_topics`, and `fraud_scenario_tags`.
   - Keep compatibility aliases: `primary_theme = primary_topic`, `primary_queue = primary_topic`, `priority_score = max(topic_scores)`.
6. `config/phase1_case.yaml`
   - Add `topic_scoring` with weights, topic caps, solo caps, combo floors, macro context bonus, review states, and fraud scenario tag ordering.
   - Keep existing `priority_weights`, `priority_floors`, and `priority_adjustments` as deprecated fallback for the first release.
7. Dashboard and export
   - Display only the seven topic labels as tabs/sections.
   - Show `fraud_scenario_tags` as badges, not queues.
   - Remove banned labels from tab/queue/ranking display.
8. Tests
   - Rule-topic mapping coverage.
   - Macro-only standalone exclusion.
   - Combo-only promotion for `L4-06` and `L3-12`.
   - Standalone exclusion for `L3-08`, `L3-03`, and `L3-10`.
   - Seven-topic Top N generation.
   - Legacy artifact/dashboard/export compatibility.
