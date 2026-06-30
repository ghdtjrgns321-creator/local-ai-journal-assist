# PHASE1 Tier Scoring Spec — 구현 계약

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 review queue 기준으로 한다.

작성일: 2026-06-14
상태: 구현 계약 초안 (§4 within-tier 정렬 결정 대기)
근거 문서(SoT): [`PHASE1_TIER_EVIDENCE_BASIS.md`](PHASE1_TIER_EVIDENCE_BASIS.md)

## 1. 목적

이 문서는 `PHASE1_TIER_EVIDENCE_BASIS.md`(근거·역할, WHY/WHAT)의 **구현 계약**(HOW)이다. tier를 정확히 어떻게 계산하고, 기존 가중합/floor/composite를 무엇으로 대체하는지 코드가 따라갈 기계 명세다.

핵심 전환: **연속 점수의 정밀도(가중합 계수·floor 숫자값·band 컷)를 폐기**하고, 근거 있는 조건에서 **순서형 tier**로 직접 매핑한다. 트리거 조건 자체는 이미 코드에 있으므로(아래 §3) 새로 만들지 않고 재사용한다 — 바뀌는 것은 "조건 → 숫자 floor → 컷 비교"가 "조건 → tier"로 단축되는 것뿐이다.

## 2. tier 배정 cascade

tier는 토픽별로 평가하고, case tier는 토픽 중 최고 tier를 취한다.

```
토픽별 tier:
  HIGH    = 이 토픽의 HIGH 트리거가 1개라도 발화
  MEDIUM  = HIGH 없음 ∧ MEDIUM 트리거 발화
  LOW     = HIGH/MEDIUM 없음 ∧ standalone_rankable primary 룰이 유효 발화(normalized_score>0)
  CONTEXT = 위 모두 없음, booster/macro/combo_only 신호만 존재 (단독 큐 불가)

case tier = max(토픽별 tier)            # HIGH > MEDIUM > LOW > CONTEXT
primary_topic = 최고 tier 토픽 (동률 시 TOPIC_REGISTRY 순서)
```

규칙:
- **has_rankable_primary gate 유지**: booster/macro/combo_only만으로는 tier(LOW 이상)를 만들 수 없다. HIGH/MEDIUM 트리거도 해당 토픽에 standalone primary seed가 있을 때만 유효(기존 `require_primary` 의미 보존).
- tier는 **순서형**이다. 같은 tier 내 case 간 크기 비교 의미 없음(정렬은 §4).
- 행 단위 `risk_level`(RISK_THRESHOLDS)은 별개 축으로 유지(case tier와 다른 축, 모순 아님).

## 3. 트리거 = 기존 조건 재사용 (숫자만 폐기)

트리거 조건은 현재 `src/detection/topic_scoring.py`에 이미 구현되어 있다. floor 숫자값(0.75/0.60/0.45)만 버리고 조건을 tier 라벨로 매핑한다.

### 3.1 HIGH 트리거 (현재 floor 0.75 → HIGH)

`_fraud_combo_floor_results()`의 조건을 그대로 사용:

| 토픽                | 조건 (현재 코드)                                                                                                                                            | FSS 패턴         |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| revenue_statistical | `(L4-01 or L4-03) ∧ L3-02 ∧ 2차정황1개` <br>2차정황 = `L4-04 / L2-03 / L3-03 / L3-10 / L1-05 / L3-11` 중 하나 (A안 확장, L3-04·L1-09는 과탐 가드 제외 §3.5) | 가공전표         |
| closing_timing      | `시점seed(L3-04/07/11/L1-08) ∧ L4-03 ∧ (L3-10/L4-04)`                                                                                                       | 결산수정         |
| closing_timing      | `L3-11 ∧ (L4-01 or L4-03)`                                                                                                                                  | 결산수정(cutoff) |
| duplicate_outflow   | `자금유출(L2-02/03/05) ∧ [승인우회(L1-04/05/06/07) or (L2-05 ∧ L3-02)]` (A안 완화, §3.5)                                                                    | 횡령은폐         |
| approval_control    | `승인우회 ∧ 강한맥락(L4-03/L3-11/L3-04+L3-02/L3-06+L3-02)`                                                                                                  | 승인우회         |

단일 룰 HIGH (현재 `DEFAULT_TOPIC_FLOORS["approval_control_high"]=0.75`):
- `L1-04` (label ∈ {critical, non_approver}) → approval_control HIGH

### 3.2 MEDIUM 트리거 (현재 floor 0.45~0.60 → MEDIUM)

| 토픽                | 조건                                                                                                                              |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| revenue_statistical | `(L4-01 ∧ L3-04)` or `(L4-03 ∧ L4-06 ∧ L3-02)`                                                                                    |
| duplicate_outflow   | `L2-01 ∧ (L1-04 or L1-05)`                                                                                                        |
| approval_control    | `(L1-09 ∧ L4-03 ∧ L3-02)` or `(승인우회 ∧ L3-02)` or `(승인우회 ∧ L3-06)` or `(승인우회 ∧ L3-05)` or `(L3-12 ∧ (L1-05 or L1-07))` |

단일/combo MEDIUM:
- `L2-02` (label=reference_match) → duplicate_outflow MEDIUM (현재 `duplicate_reference_match=0.45`)
- `L4-06` + corroboration group ≥2 → revenue_statistical MEDIUM (현재 `batch_combo`)
- `L3-12` + corroboration group ≥2 → approval_control MEDIUM (현재 `work_scope_combo`)

### 3.3 데이터무결성 게이트 (fraud tier 아님)

- `L1-01`(차대불균형), `L1-02`(핵심필드 누락)은 fraud HIGH/MEDIUM이 아니라 **원장 신뢰성 품질 게이트**다. ledger_integrity 토픽의 blocker 표시로 유지하고, 다른 조작 combo의 concealment/context로만 fraud 해석에 참여(`PHASE1_TIER_EVIDENCE_BASIS.md` §5).

### 3.4 role/standalone gating 유지

- `SCORING_ROLE_FACTOR` 역할 구분(primary/booster/combo_only/macro_only) 유지.
- `standalone_rankable=False`(booster/macro) 룰은 단독 seed 불가.
- macro_only(L4-02/Benford/D01/D02)는 같은 계정/월 primary hit가 있을 때만 맥락 연결(CONTEXT). 단독 case 생성 금지.

### 3.5 A안 셋째 다리 확장 (2026-06-16 설계 → 2026-06-17 코드 반영·측정 완료)

FSS HIGH 17건 재감사(근거 SoT §4.5, `HIGH_COMBO_GROUNDING.md` §5b)에 따라 HIGH 트리거 2개를 넓혔다. **신규 조합·신규 floor 추가가 아니라 기존 조합의 2차정황 OR 풀 확장**이다.

| 트리거                                  | 기존                      | A안 확장(최종)                                                  |
| --------------------------------------- | ------------------------- | --------------------------------------------------------------- |
| revenue_statistical(가공전표) 셋째 다리 | `(L4-04 or L2-03)`        | `+ L3-03·L3-10·L1-05·L3-11` 추가 (L3-04·L1-09는 과탐 가드 제외) |
| duplicate_outflow(횡령은폐) 통제 분기   | `승인우회(L1-04~07)` 필수 | `or (L2-05 역분개 ∧ L3-02 수기 ∧ L4-03 고액)` 분기 추가         |

코드: `src/detection/topic_scoring.py::_FICTITIOUS_SECONDARY_RULES`(신설) = `{L4-04, L3-03, L3-10, L1-05, L3-11} | _DUPLICATE_ENTRY_RULES`; 조합2 `has_reversal_manual_concealment = {L2-05,L3-02,L4-03}.issubset`.

> **과탐 HARD 가드 (측정 완료)**: 정상 v42j 2022(14,070 case) 측정 — wide(6 신규 다리) **5.245% FAIL**(L3-04 기말 734·L1-09 승인일공백 334 과발화) → L3-04·L1-09 제외 narrowed **0.334% PASS**(≤2%). 횡령은폐 분기는 정상 reversal+manual clearing 오발화 방지를 위해 고액(L4-03)을 동반 요구(anti-fitting 가드). 측정: `tools/scripts/measure_a_an_high_ratio.py`.

## 4. within-tier 정렬 (확정: 단순 tiebreak, 2026-06-14)

같은 tier 내 case 정렬은 **연속 점수 없이 순서형 tiebreak**으로만 한다(option 1 확정). "숫자 정밀도 제거" 취지와 정합하고, 모든 키가 감사상 설명 가능한 축이다.

```
sort_key = (
    tier_rank                 desc,   # HIGH=3 > MEDIUM=2 > LOW=1 > CONTEXT=0
    independent_primary_count desc,   # 서로 다른 primary 신호(distinct rule_id) 수 = 수상한 정도
    rule_count                desc,   # 발화 룰 총수
    materiality_score         desc,   # 금액(중요성) — 최후 tiebreak
)
```

> **time_severity_score는 현행 sort_key에 미포함(2026-06-22 결정).** OFF-TIME(L3-05·L3-06·L4-05) 시점심각도는 **뱃지/UI 표시 전용**이며 within-tier 정렬에 반영하지 않는다. `compute_time_severity_score`는 계산되어 대시보드 "시점심각도" 컬럼으로 표시될 뿐 정렬 키에는 들어가지 않는다(코드 `phase1_case_builder.py::_tier_sort_score`는 위 4키와 일치, time_severity 인자 없음). **within-tier 정렬 반영은 PHASE1-2 구현 시 함께 구현 예정**(OFF-TIME의 L4-05가 PHASE1-2 family 작성자 집계 단위라 같이 묶어 구현). 시점심각도 등급 정의(표시용): 주말+공휴일(L3-05 weekend_holiday)·L4-05 작성자 집중 = 2(high), 주말·심야 단독 = 1(medium). tier 게이트 미참여(시간 신호만으로 tier 승격 불가)는 유지. 정의·근거 SoT: [`HIGH_COMBO_GROUNDING.md`](HIGH_COMBO_GROUNDING.md) OFF-TIME 보조축 절(§2(5)).

- **연속 가중합/보조점수 일절 없음.** 가까운 case 간 미세 해상도는 의도적으로 포기(false precision 회피).
- `independent_primary_count` = case의 `scoring_role=='primary'` distinct rule_id 수. "여러 각도로 수상한가"를 나타내는 1차 정렬축.
- `materiality_score`(금액) = **최후 tiebreak**. 앞 키들이 모두 같을 때만 금액으로 가른다. 이로써 고액 routine 이 신호 케이스를 위로 밀어내지 못한다 — `docs §9.3 audit anti-burying lock`(amount 를 1차에서 보조로 격하)과 호환. 결정: 2026-06-15(사용자).
- RELATIONSHIP_MAP §7 ~40조합 richness는 **badge 표시 전용**(정렬 키 미포함). 후속에 표시용으로만.

## 5. 폐기·대체 매핑표 (2026-06-17 실행 결과 반영)

> **실행 요약(2026-06-17)**: 가중합 topic 점수와 죽은 legacy band 경로는 제거 완료. 단 일부 legacy 함수는 활성 tier 경로에서도 case 보조필드(behavior_score·repeat_score·각종 bonus·사유)를 생산하고 그 필드가 export·PHASE2 feature로 흐르므로 **보존**했다. 그 보조필드 중 `behavior_score`(줄수/10)·`repeat_score`((월−1)/2) 등 근거 없는 magic number는 PHASE2 재설계 시 통합 제거 대상으로 이월한다(`PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md` §8 known-issue).

| 현재 (코드)                                                                                                            | 처리                   | 비고                                                                                                                                        |
| ---------------------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `topic_scoring.TOPIC_SCORE_WEIGHTS` (0.62/0.08…)                                                                       | **제거 완료**          | 정의·참조 0건                                                                                                                               |
| `topic_scoring.compute_topic_scores` base_score 가중합 + 7 컴포넌트 점수                                               | **제거 완료**          | floor/combo 적용값만 산출(가중합 아님)                                                                                                      |
| `TopicScoreBreakdown` 7 컴포넌트 필드                                                                                  | **제거 완료**          | 트리거 정보(policy_ids·has_rankable_primary)만 유지                                                                                         |
| `topic_scoring.DEFAULT_TOPIC_FLOORS` / `DEFAULT_COMBO_FLOORS` 숫자값                                                   | 숫자 **폐기**          | 조건은 tier 트리거로 재사용(§3). 값은 tier 컷 분류용                                                                                        |
| `_fraud_combo_floor_results` / `apply_topic_floors` / `apply_combo_floors`                                             | **재사용**             | 트리거 발화 평가기(policy_ids 산출)                                                                                                         |
| `use_topic_scoring` 플래그 + 죽은 legacy(False) 분기                                                                   | **제거 완료**          | tier 무조건 단일 경로                                                                                                                       |
| `_composite_sort_score` + `_COMPOSITE_SORT_WEIGHTS` + `_COMPOSITE_SORT_INDEPENDENT_EVIDENCE_CAP`                       | **제거 완료**          | §4 순서형 `_tier_sort_score`로 대체                                                                                                         |
| `_apply_macro_context_priority` + 죽은 audit_evidence 체인(`_case_audit_evidence_scores`·`_case_has_*`·`_any_context`) | **제거 완료**          | 가중합 audit_evidence 입력 전용이었음(호출처 0)                                                                                             |
| `_priority_score` (6축 가중합)                                                                                         | **보존(load-bearing)** | 활성 경로 priority_score 시드·tier floor 머지 입력. 산출 보조필드가 PHASE2 feature로 유입 → §8 known-issue로 PHASE2 이관                    |
| `_apply_priority_floors` / `_apply_priority_adjustments` / `_apply_timing_priority_adjustments`                        | **보존(load-bearing)** | behavior/repeat/bonus/사유 등 생존 보조필드 생산(export·PHASE2 소비). magic number는 PHASE2 재설계 시 이관                                  |
| `_priority_band` (0.90/0.75 컷)                                                                                        | **보존**               | `_derive_case_scores_from_units`가 tier 표현값(`_TIER_TO_PRIORITY_SCORE`)에 적용 → band는 tier에서 결정론적 산출(컷이 tier를 거스르지 않음) |
| `rule_scoring.normalize_rule_evidence` 곱셈                                                                            | **유지(역할 축소)**    | evidence 표시·발화 게이트(`normalized_score>0`)로만. band·생성 미구동. magic number는 별도 backlog(룰별 점수 미시분석)                      |

## 6. 자료구조

`TopicScoreBreakdown`(score 중심) → `TierBreakdown`(tier 중심)으로 교체:

```
TierBreakdown:
  topic_id: str
  tier: "HIGH" | "MEDIUM" | "LOW" | "CONTEXT"
  fired_triggers: tuple[str, ...]      # 발화한 트리거 id (설명/조서용)
  trigger_evidence: tuple[str, ...]    # 트리거를 구성한 rule_id
  has_rankable_primary: bool

case sort_key (§4 확정): (tier_rank, independent_primary_count, rule_count, materiality_score) 전부 desc — 코드 `_tier_sort_score`와 일치(time_severity 미포함, 뱃지 표시 전용)

case 레벨:
  case_tier, primary_topic, topic_tiers: dict[str, TierBreakdown]
  fraud_scenario_tags (유지)
```

호환 alias: `priority_band = case_tier`(HIGH/MEDIUM/LOW 매핑), `priority_score`는 deprecated(필요 시 tier ordinal 또는 sort_key 첫 요소로 대체 표기).

## 7. 소비처 영향 (ripple, 구현 시 점검)

`composite_sort_score`/`priority_band`/`priority_score` 소비처 22파일:
- `src/models/phase1_case.py`, `phase1_unit.py` — 필드 정의
- `src/export/pdf_exporter.py`, `excel_exporter.py`, `phase1_case_view.py` — band 표시
- `src/services/phase2_*` (linker/contract/inference) — PHASE1 band 입력
- dashboard 컴포넌트 — band 표시
- `db/schema.py` — 저장 컬럼

각 소비처에서 band은 tier 매핑으로 무손실 대체 가능(HIGH/MEDIUM/LOW 동일). composite_sort_score 의존처는 §4 sort_key로 교체.

## 8. 테스트·검증

- `tests/modules/test_detection/test_rule_scoring.py`, `test_phase1_case_builder.py` — tier cascade·트리거 매핑·gating 테스트로 갱신.
- 2+ 케이스 ripple: 소비처 정합 확인.
- baseline 재측정(no-save 패턴, OOM 주의): tier 분포(HIGH/MEDIUM/LOW 건수)가 기존 band 분포와 정합하는지 회귀 가드. truth recall 직접 추구 금지(도메인 정합으로만).

## 9. 미결

- C안 family(PHASE1-2)·VAE(PHASE2) surface 분리는 본 스펙(PHASE1-1 룰 점수) 범위 밖. 별도.
</content>
