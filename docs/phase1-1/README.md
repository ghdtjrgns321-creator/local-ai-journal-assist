# PHASE1-1 최신 문서 묶음

작성일: 2026-06-17

이 폴더는 PHASE1-1 룰 기반 review queue를 이해하기 위한 최신 읽기 출발점이다. 기존 `docs/spec/**`, `docs/guide/**`, `dev/active/**`에 흩어진 내용을 코드 기준으로 다시 모았다. 과거 weighted score, 7-topic, intercompany_cycle, PHASE3, L4-02 row-rule 방식은 현재 설계가 아니므로 역사적 맥락으로만 다룬다.

## 읽는 순서

1. [rule-basis-and-catalog.md](rule-basis-and-catalog.md)  
   룰을 어떤 기준으로 만들었는지, 31개 canonical PHASE1-1 룰이 각각 무엇을 보는지, 어떤 룰이 단독 queue seed인지 정리한다.
2. [tier-scoring-and-firing.md](tier-scoring-and-firing.md)  
   현재 "통합점수"로 보이는 값이 실제로는 어떤 tier 트리거에서 발화되는지, HIGH/MEDIUM/LOW/CONTEXT가 어떻게 결정되는지 설명한다.
3. [surface-boundary.md](surface-boundary.md)  
   PHASE1-1, PHASE1-2, PHASE2가 무엇이 다르고 왜 한 점수로 합치지 않는지 정리한다.
4. [latest-redesign-notes.md](latest-redesign-notes.md)  
   2026-06 대규모 수정에서 무엇이 폐기되고 무엇이 최신 구현으로 남았는지, HIGH 10/MEDIUM 3 기준과 남은 탐지갭이 무엇인지 정리한다.

## 현재 PHASE1-1 한 줄 정의

PHASE1-1은 전표/행 단위에서 deterministic rule을 발화해 명명 가능한 위반, 정책 위반, 이상 징후를 만들고, 이를 감사인이 먼저 볼 review queue로 정렬하는 surface다. 부정 확정 단계가 아니며, DataSynth의 `is_fraud`/`is_anomaly` 라벨도 운영 판정 근거가 아니라 개발 검증 보조 지표다.

## 최신 기준점

현재 구현 기준은 아래 코드와 문서다.

| 영역 | 최신 기준 |
|------|-----------|
| 룰 메타데이터와 role | [`src/detection/rule_scoring.py`](../../src/detection/rule_scoring.py) |
| topic tier 발화 | [`src/detection/topic_scoring.py`](../../src/detection/topic_scoring.py) |
| case 생성, priority_score 호환값, 정렬 | [`src/detection/phase1_case_builder.py`](../../src/detection/phase1_case_builder.py) |
| 룰 설명과 근거 | [`docs/guide/룰원칙해설.md`](../guide/룰원칙해설.md), [`docs/spec/DETECTION_RULES.md`](../spec/DETECTION_RULES.md) |
| tier 근거 | [`docs/spec/PHASE1_TIER_SCORING_SPEC.md`](../spec/PHASE1_TIER_SCORING_SPEC.md), [`docs/spec/HIGH_COMBO_GROUNDING.md`](../spec/HIGH_COMBO_GROUNDING.md) |
| active 감사 메모 | [`dev/active/phase1-rule-basis-audit/`](../../dev/active/phase1-rule-basis-audit/) |

## 최신 상태 요약

- Canonical PHASE1-1 transaction rule은 31개다. `L4-02/Benford`, `D01`, `D02`는 registry에 남아 있지만 `macro_only`, `role_factor=0`, `standalone_rankable=False`로 중화되어 PHASE1-1 점수와 tier를 올리지 않는다.
- Topic은 6개다: `ledger_integrity`, `approval_control`, `closing_timing`, `account_logic`, `duplicate_outflow`, `revenue_statistical`.
- 최신 tier 근거는 "HIGH 조합 5개"가 아니라 HIGH 10개, MEDIUM 3개, LOW scheme 1개 분류다. 이 중 HIGH-6 가공거래처, HIGH-8 재고 과대평가, HIGH-10 topside/연결조정은 HIGH 자격은 있으나 현재 PHASE1-1 코드가 직접 잡지 못하는 탐지갭이다.
- 통합 weighted score는 현재 tier 결정 근거가 아니다. 현재 band는 `compute_topic_tiers()`의 ordinal tier가 결정한다.
- `priority_score`는 legacy 소비처(export, PHASE2 linker 등)와 UI threshold 호환을 위해 tier 대표값으로 남아 있다. 대표값은 HIGH `0.90`, MEDIUM `0.75`, LOW `0.40`, CONTEXT `0.0`이다.
- Case 정렬은 위험 확률이 아니라 `(tier_rank, independent_primary_count, rule_count, materiality_score)`를 packed scalar로 만든 정렬 전용 값이다.
- PHASE1-1, PHASE1-2, PHASE2는 독립 surface다. 단일 combined score, 단일 combined queue로 합치지 않는다.

## 쓰면 안 되는 해석

- "PHASE1-1이 fraud를 탐지했다"라고 쓰지 않는다. "review item", "검토 후보", "우선순위 승격"으로 표현한다.
- HIGH를 "부정 확정"으로 쓰지 않는다. HIGH는 감사인이 먼저 볼 항목이다.
- `priority_score=0.90`을 "90% 위험"으로 해석하지 않는다. 이는 HIGH tier를 기존 `[0,1]` 소비처에 전달하기 위한 대표값이다.
- L4-02/Benford, D01, D02를 PHASE1-1 전표 단위 룰로 설명하지 않는다. 이들은 PHASE1-2 family/macro 대상이다.
- PHASE1-1 코드가 아직 못 잡는 HIGH 자격 scheme을 LOW로 강등하지 않는다. 구현 부재는 탐지갭으로 분리한다.
