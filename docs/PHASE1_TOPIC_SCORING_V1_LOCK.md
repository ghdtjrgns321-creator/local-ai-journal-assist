# PHASE1 Topic Scoring V1 Lock

Updated: 2026-05-08
Status: Locked for v1 implementation

Completion record: `docs/PHASE1_TOPIC_SCORING_V1_COMPLETION.md`

## Decision Summary

PHASE1 result ranking is locked to seven auditor-facing topics. Legacy queue/status labels such as `Audit Risk`, `조작 후보`, `맥락 검토대상`, `추가검토사항`, `우선 위험신호`, and `저우선 위험신호` must not be used as ranking topics.

The seven official topics are:

1. 원장기록·데이터정합성
2. 승인·권한·업무분장 통제
3. 결산·기간귀속·입력시점
4. 계정분류·거래실질 불일치
5. 중복·상계·자금유출
6. 관계사·내부거래·순환구조
7. 수익·금액·모집단 통계 이상

`조작 후보` is not a queue. Fraud/manipulation interpretation is represented only through `fraud_scenario_tags`.

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

Bands:

```text
high >= 0.75
medium >= 0.45
low >= 0.20
context_only < 0.20
```

Implementation note: because the formula gives primary evidence a 0.62 base contribution, most `high` cases should be created by explicit floor/combo/materiality logic. That is intentional for v1 unless later calibration proves the high band is too sparse.

### Fraud Combo Scoring Policy

PHASE1 v1은 8번째 `조작 후보` topic 또는 tab을 만들지 않는다. 금감원 감리 사례, ISA 240, PCAOB AS 2401, ISA 550, K-SOX 기반의 강한 조작 의심은 기존 7개 topic 안에서 `fraud_combo_bonus`, `fraud_combo_floor`, `fraud_scenario_tags`로만 표현한다.

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
| 순환거래 의심 | 금감원 감리 순환거래 10건, 특수관계자 거래 중점심사. ISA 550은 특수관계자 거래의 사업상 합리성, 조건, 승인, intercompany balance 대사를 요구한다. | L3-03, IC01, IC02, IC03, L4-03, L3-04, L3-11, L4-04, D01, D02 | `L3-03 + L4-04`, 또는 `IC01 or IC02 or IC03`이면 최소 `0.45` | `(L3-03 or IC01 or IC02 or IC03) + (L4-03 or L3-04 or L3-11) + (반복 거래 or 동일 counterparty cycle)`이면 `0.75` | `순환거래 의심` | 관계사·내부거래·순환구조 |
| 승인우회 조작 의심 | 금감원 감리 승인/SoD 위반 5건과 횡령 은폐의 전제 조건. K-SOX와 내부회계관리제도 운영 효과성 관점에서 승인권한·업무분장 실패를 본다. | L1-04, L1-05, L1-06, L1-07, L1-09, L3-02, L3-05, L3-06, L4-03, L3-12 | `L1-09 + L4-03 + L3-02`, 또는 `L3-12 + (L1-05 or L1-07)`이면 `0.45~0.70` | `(L1-04 or L1-05 or L1-06 or L1-07) + (L4-03 or L3-02 or L3-05 or L3-06)`이면 `0.75` | `승인우회 조작 의심` | 승인·권한·업무분장 통제 |

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
| 관계사·내부거래·순환구조 | IC01, IC02, IC03 | L3-03, L4-04 | none | D01, D02 | L3-03, D01, D02 |
| 수익·금액·모집단 통계 이상 | L4-01, L4-03 | L3-10, L4-02/Benford only as conditional row booster | L4-06 | L4-02/Benford, D01, D02 | L4-02, Benford, L4-06, D01, D02 |

## Anti-fitting calibration notes

2026-05-08 이후 policy lock은 `datasynth_manipulation` truth 분포를 맞추기 위해 약한 rule 조합을 floor로 추가하지 않는다. 금감원/ISA/PCAOB 근거로 인정되는 조합만 fraud combo floor를 적용하고, datasynth truth 분포 때문에 발견된 약한 조합은 badge, context, tie-break 후보로만 취급한다.

| Weak combination | Floor policy | Allowed handling |
|---|---|---|
| `L3-02 + L3-04 + L3-12` | 가공전표/결산수정 Medium floor 금지 | 수기 + 결산 + 업무범위 집중 context. `L4-03`, `L3-08`, `L3-10`, `L4-04`, `L3-11`, 수익/금액/희소/중복 근거가 붙을 때만 floor 검토 |
| `(L1-04 or L1-05 or L1-06 or L1-07) + L3-02 + L3-12` | 횡령은폐 Medium floor 금지 | 승인통제 topic의 보조 context. 중복/상계/자금유출(`L2-02`, `L2-03`, `L2-05`) 근거가 붙을 때만 횡령은폐 floor |
| `L3-03 + L3-05 + (L3-02 or L3-12)` | 순환거래 High floor 금지 | 관계사 + 휴일/수기/업무범위 context. repeat/cycle/IC exception과 금액·시점·불일치 근거가 붙을 때만 High |
| `approval_bypass + L3-02` 또는 `approval_bypass + L3-05` | 승인우회 High floor 금지 | 승인통제 Medium. High는 `L4-03`, `L3-11`, `L3-04 + L3-02`, `L3-06 + L3-02` 같은 강한 근거 필요 |

`L3-12`는 fraud floor의 핵심 조건이 아니라 booster/context다. `fraud_scenario_tags`는 정렬 key가 아니며, floor가 적용되는 경우에만 `topic_score_breakdown.fraud_combo_policy_ids`에 policy reason을 남긴다.

## Ranking Rules

- Topic pages rank by `topic_score` descending.
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
