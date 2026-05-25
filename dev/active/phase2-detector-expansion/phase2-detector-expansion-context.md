# Phase2 Detector Expansion - Context & Decisions

## Status
- Phase: Sprint A3 complete - PHASE2 rule-based family registration
- Progress: 29 / 31 tasks complete
- Last Updated: 2026-05-17

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

## A2 Handoff Entry (2026-05-17)

Sprint A3 진입 시 A2 leaderboard 진입점을 사용한다. Family registration은 `src/services/phase2_training_service.py`의 `_DEFAULT_DETECTOR_FACTORIES`, `_DEFAULT_SEARCH_PRESETS`, `_FAMILY_TO_CANONICAL_MODEL`, `_PROMOTED_TRACK_MAP`를 기준으로 확장하고, 산출 검증은 `src/services/phase2_leaderboard.py::build_leaderboard_payload()`와 `src/services/phase2_promotion_policy.py::build_promotion_decision_payload()`를 통과해야 한다. A2 handoff: `artifacts/sprint_phaseA_A2_handoff_2026-05-17.md`.

## Sprint A3 Results (2026-05-17)

Sprint A3는 A2 Entry Contract의 6개 family registration 진입점을 사용해 PHASE2 family를 5개 registry 중심에서 9개 registry로 정렬하고, 운영 기본 active track을 `unsupervised` 1개에서 `unsupervised`, `timeseries`, `relational`, `duplicate`, `intercompany` 5개로 확장했다. `supervised`, `transformer`, `sequence`, `stacking`은 dormant 상태를 유지한다.

4개 rule-style detector는 기존 `detect()` 로직을 변경하지 않고 train/inference contract에 편입했다. `leaderboard.json`에는 family별 metric(`burst_detection_rate`, `new_counterparty_precision`, `fuzzy_match_f1`, `ic_match_completeness`)과 `schema_hash: null`이 출력된다. `promotion_decision.json`에는 4개 family의 family_decisions가 남고, 승격된 rule-style family는 `model_bundle.pt` 대신 `{model_dir}/phase2_<family>/vNNNN/calibration_metadata.json`을 저장한다. `inference_contract.required_models`, `model_versions`, `family_sub_detectors`, `track_map`에도 4개 family가 반영된다.

검증:
- `uv run pytest tests/modules/test_services/test_phase2_training_service.py tests/modules/test_services/test_phase2_leaderboard.py tests/modules/test_services/test_phase2_promotion_policy.py tests/modules/test_services/test_phase2_inference_service.py tests/modules/test_services/test_phase2_detector_expansion.py -q` -> 47 passed.
- `uv run pytest tests/modules/test_preprocessing/test_label_strategy.py tests/modules/test_detection/test_supervised_detector.py tests/modules/test_services/test_phase2_training_service.py tests/modules/test_services/test_phase2_layer_a_guards.py tests/modules/test_services/test_phase2_case_contract.py tests/modules/test_services/test_phase2_leaderboard.py tests/modules/test_services/test_phase2_promotion_policy.py tests/modules/test_services/test_phase2_inference_service.py tests/modules/test_services/test_phase2_detector_expansion.py -q` -> 96 passed.

Handoff: `artifacts/sprint_phaseA_A3_handoff_2026-05-17.md`.

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

## Smoke validation V7 fixed3 by year (2026-05-18)

V7 fixed3 PHASE2 by-year smoke를 실행했다. 결과 문서는 `docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md`이며, 2022/2023/2024 partition 모두에서 active 5 family score가 산출되었다. 13 sub-detector hit 분포와 시나리오 x family detection matrix는 informational only로 기록했으며, PHASE1 priority/composite_sort 및 model bundle은 변경하지 않았다.

| Family | 2022 | 2023 | 2024 | Metric |
|---|---:|---:|---:|---|
| `unsupervised` | 22,689 | 26,172 | 30,374 | ECDF q95 high count |
| `timeseries` | 299,127 | 296,765 | 295,572 | score>0 nonzero count |
| `relational` | 15,718 | 15,324 | 15,752 | score>0 nonzero count |
| `duplicate` | 77,115 | 74,367 | 70,918 | score>0 nonzero count |
| `intercompany` | 0 | 0 | 0 | score>0 nonzero count |

## Diag-1 intercompany Results (2026-05-18)

V7 fixed3 `intercompany` family 0건 원인을 systematic-debugging 4단계로 재현/격리했다. IC 거래 자체는 존재하므로 data limitation skip이 아니라 input contract mismatch로 확정했다. 2024 기준 `counterparty_type=IntercompanyAffiliate` 15,709행, `is_intercompany=True` 17,813행이 존재했지만, PHASE2 IC01은 `ic_unmatched_reference` sidecar evidence를 사용하지 않아 0건이 됐다.

수정은 `src/detection/intercompany_rules.py::ic01_unmatched_intercompany()`에 한정했다. `is_intercompany=True AND ic_unmatched_reference=True`를 IC01 unmatched evidence로 반영하고, IC02/IC03은 matched-pair amount/date reference 부재 시 계속 0으로 둔다. V7 fixed3 source, `model_bundle.pt`, dashboard 파일은 변경하지 않았다.

| Year | Metric | Before | After |
|---:|---|---:|---:|
| 2022 | intercompany nonzero | 0 | 12 |
| 2022 | IC01 unmatched_intercompany | 0 | 12 |
| 2022 | IC02 amount_mismatch | 0 | 0 |
| 2022 | IC03 timing_gap | 0 | 0 |
| 2023 | intercompany nonzero | 0 | 6 |
| 2023 | IC01 unmatched_intercompany | 0 | 6 |
| 2023 | IC02 amount_mismatch | 0 | 0 |
| 2023 | IC03 timing_gap | 0 | 0 |
| 2024 | intercompany nonzero | 0 | 16 |
| 2024 | IC01 unmatched_intercompany | 0 | 16 |
| 2024 | IC02 amount_mismatch | 0 | 0 |
| 2024 | IC03 timing_gap | 0 | 0 |

UI sprint는 `artifacts/phase2_inference_v7_fixed3_year_2024_intercompany_rerun.json`의 `after.ui_meta`를 사용한다. 현재 meta는 `skipped=false`, `metric_confidence=sidecar_unmatched_reference_only`, `active_sub_detectors=["IC01"]`, `zero_hit_sub_detectors=["IC02","IC03"]`이다.

검증:
- `uv run pytest tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py tests/modules/test_detection/test_intercompany_matcher.py -q` -> 25 passed.
- A3 focused regression + 신규 smoke guard -> 98 passed.
- `uv run ruff check src/detection/intercompany_rules.py tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py` -> PASS.

Handoff: `artifacts/sprint_phaseA_diag1_intercompany_handoff_20260518.md`.


## Diag-2 duplicate optimization Results (2026-05-18)

Duplicate inference 병목을 `src/detection/duplicate_rules.py`에서 해결했다. 2024 partition 기준 Phase A smoke baseline 83.66s에서 2.744s 평균으로 감소했고, full V7 fixed3 1,032,864 rows 기준 3회 평균 4.533s를 기록했다.

| Sub-detector | Before 2024 | After 2024 | Diff |
|---|---:|---:|---:|
| `L2-03a` exact_duplicate_amount | 2,964 | 2,964 | 0.000% |
| `L2-03b` fuzzy_duplicate | 34,655 | 34,655 | 0.000% |
| `L2-03c` split_transaction | 16,784 | 16,784 | 0.000% |
| `L2-03d` time_shifted_duplicate | 28,590 | 28,590 | 0.000% |

적용 옵션: A(blocking key), B(RapidFuzz cdist 후보 축소), D(early guard), E(line_text normalization cache). Sampling(C)은 사용하지 않았다. 산출물은 `artifacts/sprint_phaseA_diag2_duplicate_optimization_handoff_20260518.md` 및 `artifacts/phase2_duplicate_perf_before_after_20260518.json`에 기록했다.
