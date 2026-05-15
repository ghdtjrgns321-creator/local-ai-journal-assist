# Phase2 Detector Expansion - Context & Decisions

## Status
- Phase: Phase 5 - Contract Propagation and Policy Hardening
- Progress: 24 / 31 tasks complete
- Last Updated: 2026-04-21

## Key Files
**Modified**:
- `src/services/phase2_training_service.py` - 현재 5개 family 중심 orchestration
- `src/services/phase2_training_models.py` - trial/report contract
- `src/services/phase2_inference_service.py` - training contract 기반 Phase 2 infer
- `src/pipeline.py` - detector status, registry version, cold-start/bootstrap 정책
- `src/export/analysis_status.py` - phase2 provenance summary
- `docs/DETECTION_RULES.md` - 최신 Phase 2 설명

**Read-Only Inputs**:
- `src/detection/timeseries_detector.py` - TS01/TS02 전용 detector
- `src/detection/relational_detector.py` - R01/R02/R03/R04 전용 detector
- `src/detection/duplicate_detector.py` - Exact/Fuzzy/Split/Time-shift duplicate detector
- `src/detection/intercompany_matcher.py` - unmatched intercompany matching detector

**New**:
- `dev/active/phase2-detector-expansion/phase2-detector-expansion-plan.md` - 확장 전략 계획
- `dev/active/phase2-detector-expansion/phase2-detector-expansion-tasks.md` - 단계별 실행 체크리스트

## Completed So Far
- `timeseries`, `relational`, `duplicate`, `intercompany`를 Phase 2 기본 family에 편입했다.
- rule-style detector용 generic trial runner를 추가했다.
- rule-style family에 대한 preset 탐색 정책을 추가했다.
- trial metadata에 `sub_detector_keys`를 고정했다.
- training report metadata에 `sub_detector_summaries`를 추가했다.
- inference contract에 `family_sub_detectors`를 추가했다.
- rule-style family용 proxy metric 정책을 승격 정책 metadata에 추가했다.
- `tests/modules/test_services/test_phase2_training_service.py` 기준 회귀 테스트를 통과했다.
- 승격 정책에 family별 최소 완료 trial 수와 최소 metric 기준을 추가했다.
- `family_promotion_decisions`를 report metadata에 추가해 family별 승격/탈락 근거를 남긴다.
- phase2 inference snapshot 회귀와 dashboard/export provenance 회귀를 통과했다.

## Key Decisions
1. **확장 detector도 Phase 2 train contract 안으로 넣는다** (2026-04-21)
   - Rationale: 문서상 Phase 2 유형 중 시계열/novelty/duplicate/intercompany가 별도 detector로만 남아 있으면 leaderboard, promotion, provenance가 분리된다.
   - Alternatives: 기존처럼 pipeline의 별도 detect track으로만 유지
   - Trade-offs: train contract가 커지지만 포트폴리오 설명성과 exact provenance가 좋아진다.

2. **rule-style detector를 artifact-less family로 허용한다** (2026-04-21)
   - Rationale: timeseries/relational/duplicate/intercompany는 전통적 save/load model이 아니라 settings+rule registry 기반이다.
   - Alternatives: 이 계열을 train family에서 제외
   - Trade-offs: registry_version 개념은 약하지만, policy/version provenance로 관리할 수 있다.

3. **detector 세분화는 sub-detector metadata로 먼저 푼다** (2026-04-21)
   - Rationale: `TransactionBurst`, `UnusualFrequency` 등을 곧바로 새로운 top-level family로 쪼개면 contract가 과도하게 커진다.
   - Alternatives: 각 유형을 독립 family로 분리
   - Trade-offs: family 수는 안정적이고, 문서/포트폴리오 설명에는 충분하다.

4. **AutoML 고도화는 exhaustive search가 아니라 family policy 정교화로 간다** (2026-04-21)
   - Rationale: 포트폴리오 목적상 중요한 건 재현 가능한 선택 정책과 provenance이지, 무제한 탐색 시간이 아니다.
   - Alternatives: full search space 확대
   - Trade-offs: 탐색 폭은 제한되지만 실행 가능성과 설명 가능성이 높다.

5. **closing_timing / intercompany_cycle high band는 PHASE1 한계로 확정, PHASE2 이관** (2026-05-15)
   - Rationale: PHASE1 가중치 보강안(L3-04 weight 0.4→0.5, L3-03 cap 0.4→0.6)이 3가드(회계 도메인 정당성 + AB 손실 + noise FP) 모두 FAIL. ISA 240 ¶A44 (period-end corroboration 필요), ISA 550 ¶A28 (RPT 식별/평가 단계 분리) 가 단일 룰 가중치로 high band 결정을 만드는 것을 금지함.
   - 이관 범위:
     * `closing_timing:high` (period_end_adjustment_manipulation 92건의 high 진입 4건) → PHASE2 `supervised` family (XGBoost multi-feature: timing × counterparty × amount × manual × approval)
     * `intercompany_cycle:high` (circular_related_party 34건의 high 진입 0건) → PHASE2 `relational` family (graph cycle: NetworkX simple_cycles / Tarjan SCC)
   - PHASE1 잔존: closing_timing:medium, intercompany_cycle:medium 진입은 그대로 review queue 에 medium band 로 노출. PHASE2 high 가 medium band 위에 보강 신호를 얹는 구조.
   - Trade-offs: PHASE1 가중치 lock 유지 → period_end_adjustment / circular_related_party 의 high band ranking 은 PHASE2 가 가동될 때까지 medium band 잔류. 회계기준 정합성과 review queue 신뢰성을 우선.
   - 근거 문서: [`artifacts/closing_intercompany_high_band_decision.md`](../../../artifacts/closing_intercompany_high_band_decision.md), `docs/DETECTION_RESULTS_MANIPULATION_V2.md` §10.

## Known Issues
- `phase2_training_service.py`는 현재 ML family 중심 이름과 canonical model key를 전제로 작성되어 있어 rule-style family 추가 시 mapping을 재정리해야 한다.
- `duplicate`와 `intercompany`는 기존 DB score/model_id 컬럼과 Phase 2 promoted contract가 일부 중첩된다.
- `timeseries`와 `relational`은 현재 registry version을 남길 저장 모델이 없어 artifact-less provenance 기준을 새로 정의해야 한다.
- dashboard/UI는 현재 확장 family 요약까지는 노출하지 않으므로 이번 단계에서는 contract와 tests를 우선 고정한다.

## PHASE1 한계 → PHASE2 이관 책임 (2026-05-15)

본 family 확장 작업은 closing_timing / intercompany_cycle high band 의 truth recall 책임을 명시적으로 떠안는다.

```
PHASE1 한계 영역                            PHASE2 family / sub-detector       기대 작용                                          근거 문서
------------------------------------------- ---------------------------------- -------------------------------------------------- -------------------------------------------------------------------
closing_timing:high (period_end_adjustment) supervised / XGBoost               timing × counterparty × amount × manual ×          artifacts/closing_intercompany_high_band_decision.md §6-7
                                                                               approval feature 결합으로 정상 결산 vs.            docs/DETECTION_RESULTS_MANIPULATION_V2.md §10
                                                                               조작 결산 분리. ISA 240 ¶A44 'period-end +
                                                                               corroboration' 요구를 multi-feature 학습으로
                                                                               해소.
intercompany_cycle:high (circular_RPT)      relational / graph cycle           NetworkX simple_cycles / Tarjan SCC 로             artifacts/closing_intercompany_high_band_decision.md §6-7
                                            sub-detector                       circular pattern 식별. ISA 550 ¶A19-A21            docs/DETECTION_RESULTS_MANIPULATION_V2.md §10
                                                                               'transaction flow + economic substance'
                                                                               평가는 graph 영역.
```

PHASE1 가중치 lock 은 유지 — 본 family 가 PHASE1 의 회계 도메인 정합성 한계를 회수하는 형태. 정상 결산 야근·정상 RPT 거래 FP 폭증 위험은 PHASE2 학습 라벨(`is_fraud`)로 분리.
