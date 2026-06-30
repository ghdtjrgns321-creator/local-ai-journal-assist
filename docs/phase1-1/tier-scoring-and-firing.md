# PHASE1-1 tier scoring과 발화 흐름

작성일: 2026-06-17

이 문서는 사용자가 "통합점수"라고 부르는 PHASE1-1 우선순위 체계의 최신 상태를 설명한다. 결론부터 말하면, 현재 PHASE1-1의 band는 weighted score가 아니라 ordinal tier가 결정한다.

## 핵심 결론

- 현재 HIGH/MEDIUM/LOW는 가중합 점수의 크기로 결정되지 않는다.
- `compute_topic_tiers()`가 topic별 HIGH/MEDIUM/LOW/CONTEXT를 만들고, case는 그중 최고 tier를 따른다.
- `priority_score`는 남아 있지만 위험 확률이나 실제 연속 점수가 아니다. legacy 소비처를 위해 tier를 `[0,1]` 값으로 표현한 호환 shim이다.
- `composite_sort_score`도 위험도 점수가 아니라 within-tier 정렬 전용 packed scalar다.

## 왜 예전 통합점수를 폐기했나

과거에는 `0.62 * max_primary + 0.08 * secondary + ...` 같은 weighted score와 floor 숫자, band cut으로 priority를 만들었다. 2026-06 대규모 수정에서 이 방식은 폐기됐다.

| 폐기 대상                  | 문제                                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------- |
| weighted score 계수        | 0.62, 0.08 같은 계수가 감사기준이나 실증 근거에서 나온 값이 아니었다.                    |
| floor 숫자를 점수처럼 해석 | 실제 HIGH/MEDIUM은 대부분 조합/floor가 만들었고 weighted score 단독으로 설명되지 않았다. |
| band cut                   | high≥0.90, medium≥0.75 같은 숫자는 queue 라벨 호환값일 뿐 위험 확률이 아니다.            |
| 단일 combined score        | PHASE1-1, PHASE1-2, PHASE2의 출력 단위와 신뢰도가 달라 하나로 합치면 의미가 깨진다.      |

최신 체계는 "어떤 근거 있는 트리거가 발화했는가"를 먼저 보고, 그 결과를 tier로 직접 매핑한다.

최신 근거 문서인 [`HIGH_COMBO_GROUNDING.md`](../spec/HIGH_COMBO_GROUNDING.md)는 "HIGH 조합 5개" 프레이밍을 폐기하고 HIGH 10개, MEDIUM 3개, LOW scheme 1개로 재분류한다. 코드가 아직 못 잡는 HIGH 자격 scheme은 LOW가 아니라 탐지갭이다.

## 발화 파이프라인

```text
raw rule result
  -> normalize_rule_evidence()
  -> RuleScoringMetadata로 role/topic/floor/combo tag 부여
  -> compute_topic_tiers()
  -> topic별 HIGH/MEDIUM/LOW/CONTEXT
  -> case_tier()가 최고 tier 선택
  -> priority_band와 priority_score 호환값으로 표시/export
  -> _tier_sort_score()로 같은 tier 내부 정렬
```

구현 기준:

- 룰 evidence 정규화: [`src/detection/rule_scoring.py`](../../src/detection/rule_scoring.py)
- topic tier 발화: [`src/detection/topic_scoring.py`](../../src/detection/topic_scoring.py)
- case priority와 정렬: [`src/detection/phase1_case_builder.py`](../../src/detection/phase1_case_builder.py)
- UI band 호환: [`dashboard/phase1_display.py`](../../dashboard/phase1_display.py)

## Topic tier 결정 규칙

`compute_topic_tiers()`의 현재 cascade는 다음과 같다.

| tier    | 조건                                                                 | 의미                              |
| ------- | -------------------------------------------------------------------- | --------------------------------- |
| HIGH    | HIGH trigger가 발화하고, 해당 topic에 `has_rankable_primary`가 있음  | 감사인이 가장 먼저 볼 review item |
| MEDIUM  | HIGH가 없고 MEDIUM trigger가 발화하며, `has_rankable_primary`가 있음 | 다음 우선순위 review item         |
| LOW     | 조합/floor 없이 standalone primary seed만 있음                       | 단일 룰 발화                      |
| CONTEXT | booster, combo_only, macro_only만 있음                               | 단독 queue 불가. 다른 신호의 맥락 |

`has_rankable_primary` gate가 중요하다. `L3-03`, `L3-05`, `L3-06`, `L3-10`, `L3-12`, `L4-05`, `L4-06`, `L4-02`, `D01`, `D02` 같은 보강/거시 신호만으로는 HIGH/MEDIUM/LOW queue를 만들 수 없다.

## Case tier와 primary topic

Case에는 여러 topic tier가 생길 수 있다. 최종 case tier는 그중 가장 높은 tier다.

```text
HIGH > MEDIUM > LOW > CONTEXT
```

Primary topic도 최고 tier topic에서 고른다. 동률이면 `TOPIC_REGISTRY` 순서를 따른다.

## priority_score 호환값

현재 `phase1_case_builder.py`에는 다음 mapping이 있다.

| tier    | priority_band | priority_score |
| ------- | ------------- | -------------- |
| HIGH    | high          | 0.90           |
| MEDIUM  | medium        | 0.75           |
| LOW     | low           | 0.40           |
| CONTEXT | low           | 0.0            |

이 값은 legacy export, PHASE2 linker, UI threshold처럼 `[0,1]` 숫자를 기대하는 소비처를 깨지 않기 위한 호환값이다. `0.90`은 "90% 위험"이 아니라 "HIGH tier를 기존 숫자 칸에 실어 보낸 값"이다.

## within-tier 정렬

같은 HIGH끼리, 같은 MEDIUM끼리의 순서는 `_tier_sort_score()`가 만든다.

```text
(tier_rank, independent_primary_count, rule_count, materiality_score)
```

이 순서를 단일 scalar로 packing한다.

| 정렬 요소                   | 의미                                                        |
| --------------------------- | ----------------------------------------------------------- |
| `tier_rank`                 | HIGH, MEDIUM, LOW, CONTEXT 순서                             |
| `independent_primary_count` | 독립 primary 룰 수. 여러 독립 신호가 겹친 case를 먼저 본다. |
| `rule_count`                | 발화한 고유 룰 수. 근거 밀도를 본다.                        |
| `materiality_score`         | 금액 중요성. 마지막 tie-breaker다.                          |

금액은 마지막 tie-breaker다. 고액 routine case가 복수 신호 case를 묻지 않게 하기 위한 결정이다.

## 현재 HIGH trigger

아래는 코드 기준(`topic_scoring.py::_fraud_combo_floor_results`, 2026-06-22 동기화)의 HIGH 발화다. `HIGH_COMBO_GROUNDING.md`의 HIGH 10개 중 코드에 구현된 것은 **6개**이며(HIGH-7 역분개+관계사는 §8(4)로 MEDIUM 이관), 가공거래처·재고 과대평가·topside/연결조정은 HIGH 자격은 유지하되 **GL-only 범위 외**(마스터·보조원장·연결 산출물 비보유)로 PHASE1-1 primary 룰을 신설하지 않는다([CONSTRAINTS.md](../spec/CONSTRAINTS.md)).

> 약어: `bypass` = `(L1-04|L1-05|L1-06|L1-07|L1-07-02)` 승인우회 · `outflow` = `(L2-02|L2-03|L2-05)` 자금유출.

| trigger                         | topic               | 조건(코드 실제)                                | 해석                                                                                                                 |
| ------------------------------- | ------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `fictitious_entry_high`         | revenue_statistical | `(L4-01 or L4-03) + L3-02 + 2차정황`           | 가공전표/수익 조작. 2차정황 = `L4-04`·`L2-03`·`L3-03`·`L1-05`·`L3-11`(§8(5) `L3-10` 헛다리 삭제).                    |
| `period_end_adjustment_high`    | closing_timing      | `(L3-04 or L3-11) + (L3-10 or L4-04 or L4-03)` | 결산/충당금·손상 조작. §8(5) `L3-07`·`L1-08` 삭제, §8(1) 고액 `L4-03` 복원. 정상 기말 과발화는 L3-10 임계 조정 대상. |
| `embezzlement_concealment_high` | duplicate_outflow   | `outflow + (bypass or (L3-02 + L4-03))`        | 횡령은폐. 승인흔적 없는 수기+고액 분기 포함(§8(6) 자금유출+수기+고액 일반형).                                        |
| `suspense_concealment_high`     | duplicate_outflow   | `L3-09 + outflow + L4-03`                      | 가수금/미결제 계정 은폐.                                                                                             |
| `expense_capitalization_high`   | account_logic       | `L2-04 + L3-02 + (L4-03 or L3-04 or L1-06)`    | 비용자산화 조작. §8(6) 셋째다리에 직무분리 `L1-06` 추가.                                                             |
| `approval_bypass_high`          | approval_control    | `bypass + (L4-03 or L2-02 or L2-03)`           | 승인우회 + 고액/중복(§8(6) corroborant 확장). 구 `L3-11`/`L3-04+L3-02`/`L3-06+L3-02` 게이트 폐기.                    |

미구현 HIGH 자격 scheme은 다음과 같이 별도 관리한다.

| scheme                      | 상태                                                                                                                                               |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 가공거래처(페이퍼·차명회사) | **GL-only 범위 외** — 거래처 마스터 비보유, PHASE1-1 primary 룰 신설 안 함([CONSTRAINTS.md](../spec/CONSTRAINTS.md)). HIGH 등급 유지.              |
| 재고 과대평가(조작형)       | **GL-only 범위 외** — 재고 보조원장(수량·단가·NRV) 비보유, 룰 신설 안 함([CONSTRAINTS.md](../spec/CONSTRAINTS.md) §재고). HIGH 등급 유지.          |
| topside/연결조정 전표       | **GL-only 범위 외** — 연결 산출물(eliminations) PHASE1 입력 밖, 룰 신설 안 함([CONSTRAINTS.md](../spec/CONSTRAINTS.md) §연결조정). HIGH 등급 유지. |

## 현재 MEDIUM trigger

| trigger                           | topic               | 조건(코드 실제)                                 | 해석                                                                                |
| --------------------------------- | ------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------- |
| `fictitious_entry_medium`         | revenue_statistical | `(L4-01 or L4-03) + L3-02` (2차정황 없음)       | 약화형 가공전표(HIGH-1 약화, §4b-1).                                                |
| `embezzlement_concealment_medium` | duplicate_outflow   | `L2-01 + (L1-05 or L1-06 or L1-07 or L1-07-02)` | 한도직하 분할(§4a-2). §8(7) 한도초과 `L1-04` 제외.                                  |
| `suspense_concealment_medium`     | duplicate_outflow   | `L3-09 + outflow` (고액 없음)                   | 약화형 가수금(HIGH-3 약화, §4b-2).                                                  |
| `related_party_reversal_medium`   | duplicate_outflow   | `L2-05 + L3-03`                                 | 관계사 역분개(§4a-4, §8(4) HIGH-7 MEDIUM 이관). host=duplicate_outflow(L2-05 seed). |
| `expense_capitalization_medium`   | account_logic       | `L2-04 + L3-02` (셋째다리 없음)                 | 약화형 비용자산화(HIGH-9 약화, §4b-3).                                              |
| `rare_account_bypass_medium`      | account_logic       | `L4-04 + bypass`                                | 희소계정쌍+승인우회(§4a-1, §8(7) bypass 전체).                                      |

> 폐기(§8(5), LOW 강등): `batch_combo`·`work_scope_combo`·`duplicate_reference_match`·`approval_bypass_medium`. 근거 없어 MEDIUM에서 제거됐고 코드에도 없다.

`HIGH_COMBO_GROUNDING.md`의 독립 MEDIUM scheme(§4a)은 다음과 같이 코드에 반영돼 있다.

| scheme                | 현재 상태                                                                                                                                        |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 희소계정쌍 + 승인우회 | `rare_account_bypass_medium` = `L4-04 & bypass`(§8(7) bypass 전체). 독립 MEDIUM이며 HIGH-1 2차정황으로 흡수되지 않는다(HIGH-1 풀에 bypass 없음). |
| 한도직하 분할         | `embezzlement_concealment_medium` = `L2-01 & (L1-05\|L1-06\|L1-07\|L1-07-02)`(§8(7) 한도초과 L1-04 제외). 구 "+기말" 라벨은 근거 없어 삭제.      |
| 관계사역분개          | `related_party_reversal_medium` = `L2-05 & L3-03`(§8(4) HIGH-7 MEDIUM 이관).                                                                     |
| split-invoice         | 전용 룰 없음. L2-01 한도직하와 구분되는 거래레벨 행동탐지 gap(미구현).                                                                           |

## LOW와 CONTEXT 발화

LOW는 조합이 없더라도 primary 룰이 단독 발화하면 만들어진다. 예를 들어 `L3-01`, `L4-04`, `L2-05` 등이 단독으로만 있으면 보통 LOW seed다.

CONTEXT는 booster/combo_only/macro_only만 있을 때다. 예를 들어 관계사 맥락 `L3-03`만 있거나 Benford macro만 있으면 PHASE1-1 case priority를 올리지 않는다.

## 고액 L4-03 정책

2026-06-17 최신 근거는 고액을 일반적인 부정전표 필수조건으로 쓰지 않는다. PCAOB AS 2401 §61은 round number 등 특성을 말하지만 금액 크기 자체를 모든 combo의 필수 red flag로 두지 않는다. 따라서 고액은 주로 중요성, 이상치, tier 내부 정렬 렌즈로 둔다.

예외적으로 고액이 combo에 남는 곳은 두 곳이다.

- 수익통계 anchor: `L4-01 or L4-03`이 가공전표 HIGH의 주제 신호다.
- 가수금 은폐: FSS 실측상 `L3-09` HIGH 사례에서 L4-03 동반성이 강해 `suspense_concealment_high`에 남긴다.

결산조작, 횡령은폐, 승인우회, 관련자 역분개, 비용자산화 combo에서는 고액 필수 게이트를 제거했다.

## UI와 export에서 어떻게 보이나

- UI의 `display_priority_band_from_score()`는 stale artifact의 band 문자열보다 `priority_score`를 우선한다.
- `priority_score`가 0.90 이상이면 high, 0.75 이상이면 medium, 그 외는 low로 표시된다.
- 최신 case builder가 `priority_score`를 tier 대표값으로 덮어쓰기 때문에, UI threshold는 사실상 tier label을 다시 읽는 호환 layer다.
- Export와 PHASE2 연결부도 숫자 필드를 소비할 수 있지만, 의미는 "tier 대표값"이다.

## legacy가 남아 있는 이유

`phase1_case_builder.py`에는 `_priority_score()`, `_apply_priority_floors()`, `_apply_priority_adjustments()` 같은 legacy 함수가 남아 있다. 최신 tier 결정에서는 최종 `priority_score`가 tier 대표값으로 덮인다. 다만 export, macro context, PHASE2 feature/linker, 과거 artifact 호환 때문에 함수와 config 일부가 아직 load-bearing이다. 새 문서나 UI 문구에서는 이 값을 연속 위험 점수로 설명하지 않는다.
