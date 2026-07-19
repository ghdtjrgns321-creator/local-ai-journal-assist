# Phase2 Family Ranking - Context & Decisions

## Status
- Phase: A·B·C(reject)·C-격리·D·E·F 모두 완료 + post-review bug fix 4건 적용 ✅
- Progress: 31 / 31 sprint scope tasks (100%) — **단, production overlay wiring 은 P1 follow-up 으로 남음 (Handoff §8.0)**
- Last Updated: 2026-05-19
- Handoff: `artifacts/sprint_phase2_family_ranking_handoff_20260519.md`

## Post-review fix 요약 (2026-05-19)
내부 리뷰 4건 모두 적용:
- **#4** sub-detector 레벨 evidence_tier 부착 + count 정확화
- **#3** coverage_breadth near-dormant 제외 + threshold≤0 positive guard
- **#2** lane_membership ECDF q95 임계 명시 (≥0.95)
- **#1** production overlay wiring 미완료 명시 (inference_service / pipeline 두 호출 site 에 [PENDING] docstring + Handoff §8.0 explicit incomplete scope)

검증: `uv run pytest tests/modules/test_services/test_phase2_case_contract.py -q` → 20 passed (15 + 신규 5건 bug fix 회귀).

## Pivot Decision (2026-05-19)

**최종 승인 문장 (사용자 확정)**:
> Proceed with design pivot: keep primary PHASE1+VAE 2-way RRF, reject PHASE2 internal hierarchical RRF for production, preserve family diagnostics as lane/evidence overlays, and update governance/docs/tests accordingly.

### Pivot 사유
- Phase C V7 fixed3 측정: hierarchical RRF (active=unsupervised+duplicate / booster=timeseries+relational / near-dormant=intercompany) 가 2-way baseline 대비 TOP 100~5000 평균 **-6.45pp 손실**.
- 본질: RRF 는 ranker 가 "어느 정도 동등한 검색기" 일 때 강함. PHASE2 5 family 는 역할·분포가 본질적으로 다름(연속 vs 이산 vs 희소). voter 형식 통일 시 unsupervised 의 연속 분해능이 dilute 됨.
- governance: -6.45pp 손실을 "tuning 으로 살리기" 보다 "역할을 바꿔 살리기"가 안전. truth-recall 으로 임계값 조정하면 fitting 위험.

### Pivot 후 구조
- **Primary global queue**: PHASE1 composite ↔ VAE ECDF 2-way RRF k=60 (현 운영 그대로, 변경 0)
- **Per-case overlay**: family_contributions + top_family + coverage_breadth + max_family_ecdf + max_evidence_tier + lane_membership + coverage_gap_families
- **Tie-break ladder 6단**: primary RRF 동률 또는 near-tie(1e-9) 한정 적용. weighted score 아님.
- **Family lanes**: dashboard 보조 큐. 각 lane 내부 정렬은 evidence_tier desc → family ECDF desc. near-dormant 는 "데이터 미보유" 배지.
- **Narrator input**: family_contributions + lane_membership + evidence_tier badge

### Tie-break 가드 (governance lock)
> Tie-break ladder는 primary RRF의 동률 또는 near-tie 보조 정렬에만 사용하며, primary queue의 기본 순위를 뒤집는 별도 weighted score로 사용하지 않는다.

이 가드가 없으면 6단 ladder가 새 ranking model로 변질될 수 있음. 구현 가드:
- 동률 정의: primary RRF score 차이 ≤ 1e-9
- ladder 적용은 lexicographic 비교만, weight 가중합 금지
- regression test 가 near-tie 외 영역에서 primary 순위 보존 검증

## Phase C Reject 산출물 (격리 보관)
- `src/services/queue_fusion.py::compute_phase2_internal_rrf` — experimental docstring + V7 fixed3 reject 사유 명시
- `tests/modules/test_services/test_queue_fusion_hierarchical.py` — `@pytest.mark.experimental_phase2_internal_rrf` marker 부착
- `artifacts/phase2_family_ranking_measurement_20260519.md` — TOP 100~5000 측정 + reject 결정 박스
- `tools/scripts/phase2_family_ranking_dry_run.py` — 재평가용 보존 (supervised/transformer 활성화 시)

재평가 조건: supervised 또는 transformer family 가 활성화되어 모든 active family 가 연속·전역 ranker 가 될 때.

## Phase B Results (2026-05-19)
L0 family 분포 진단 metric 3종 + training_report metadata pin helper 완료. 31 unit tests + V7 fixed3 분포 pattern 검증 통과.
- `src/services/phase2_family_diagnostics.py`: 3 metric (`row_nonzero_rate`, `rank_resolution`, `top_tail_resolution`) + dataclass `FamilyDiagnostics` + role classifier (`classify_family_role`) + metadata helper (`attach_family_diagnostics_to_metadata`, `read_family_diagnostics_from_metadata`).
- `top_tail_resolution` 은 q95 tail 내부 largest tie block / top_tail_count 의 보수로 계산. 분모를 전체 n 이 아닌 tail count 로 잡아 희소 family 의 작은 tail 변별력도 정확히 평가.
- role 임계값: row_nonzero_rate<0.001 → near-dormant, top_tail_resolution<0.2 → tail-only-fallback, rank_resolution<0.01 또는 top_tail_resolution<0.5 → coarse-booster, else active-ranker.
- training_report metadata 슬롯: 별도 typed field 추가 없이 `metadata["family_diagnostics"]` 활용 → 기존 회귀 영향 0. 실제 training service 호출 site 는 Phase E 에서 row-level family score aggregator 와 함께 wire.
- 검증: `uv run pytest tests/modules/test_services/test_phase2_family_diagnostics.py tests/phase2_rulebase/test_subdetector_tiers_schema.py -q` → 45 passed (0.87s).

## Phase A Results (2026-05-19)
14 sub-detector evidence_tier YAML 단일 출처 lock 완료. schema test 14건 통과.
- `config/phase2_subdetector_tiers.yaml`: strong 4건(L2-03a, R01, R02, IC01), moderate 6건(TS01, R03, L2-03b, L2-03c, IC02, VAE-01[ml_quantile]), weak 4건(TS02, R04, L2-03d, IC03).
- VAE-01은 `ml_quantile` 특수 tier — tie-break ladder #5에서는 분기하지 않고 #4 max_family_ecdf 단계에서 처리.
- D044 PR 템플릿에 tier 변경 fitting-risk check 추가.
- 검증: `uv run pytest tests/phase2_rulebase/test_subdetector_tiers_schema.py -v` → 14 passed (1.02s).

## Key Files
**To Create**:
- `config/phase2_subdetector_tiers.yaml` — 14 sub-detector evidence_tier 단일 출처 (Phase A)
- `src/services/subdetector_tiers.py` — tier loader + 검증 (Phase A)
- `tests/phase2_rulebase/test_subdetector_tiers_schema.py` — tier schema 강제 테스트 (Phase A)
- `src/services/phase2_family_diagnostics.py` — L0 분포 진단 3 metric (Phase B)
- `tools/scripts/phase2_family_ranking_dry_run.py` — V7 fixed3 measurement (Phase C)
- `artifacts/phase2_family_ranking_measurement_<date>.md` — Phase C 산출
- `artifacts/phase2_family_ranking_production_<date>.md` — Phase E 산출
- `artifacts/sprint_phase2_family_ranking_handoff_<date>.md` — Phase F handoff

**To Modify**:
- `src/services/queue_fusion.py` — hierarchical RRF helper 추가 (Phase C)
- `src/services/phase2_case_contract.py` — Phase2CaseOverlay 확장, 6단 tie-break (Phase D)
- `src/services/phase2_training_service.py` — family_diagnostics 측정·pin (Phase B)
- `src/services/phase2_training_models.py` — Phase2TrainingReport 필드 추가 (Phase B)
- `src/services/phase2_inference_service.py` — family score 집계, role 자동 적용 (Phase D/E)
- `src/pipeline.py` — production queue 반영 (Phase E)
- `src/llm/phase3_case_prompt.py` — family_contributions 인용 (Phase D)
- `dashboard/components/phase2_family_matrix.py` — family_contributions 노출 (Phase D)
- `docs/spec/PHASE2_GOVERNANCE_DESIGN.md` — 결정 8 추가 (Phase F)
- `docs/spec/PHASE2_INTERFACE_DESIGN.md` — §4.4 보강 (Phase F)
- `docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md` — §6 보강 (Phase F)
- `docs/spec/DECISION.md` — D044 PR 템플릿 tier 변경 fitting-risk check (Phase A)
- `tests/phase2_rulebase/kpi_baseline.json` — Layer C rank stability metric (Phase F)

**Read-Only Inputs**:
- `artifacts/phase2_family_correlation_matrix_20260519.md` — Spearman·Jaccard 측정 (보완성 근거)
- `artifacts/phase1_manipulation_v7_fixed3_case_input.pkl` — V7 fixed3 row 입력
- `docs/spec/PHASE2_GOVERNANCE_DESIGN.md` 결정 4~7 — 기존 lock 정합 확인
- `docs/spec/PHASE2_INTERFACE_DESIGN.md` 결정 3 옵션 Z — independent queue 원칙
- `docs/spec/DETECTION_RULES.md` §3.3 A3 Family Matrix — family·sub-detector 목록 진본
- `dashboard/components/phase2_subdetector_grid.py` — 13 sub-detector enumeration (TS01/TS02/R01-R04/L2-03a-d/IC01-IC03)

## Sub-Detector Inventory (14개, Phase A 진본)

```
family         sub-detector code  label                          기준서 후보
─────────────────────────────────────────────────────────────────────────────
unsupervised   VAE-01            audit_vae_reconstruction       (분포 metric만)
timeseries     TS01              transaction_burst              ISA 240 ¶A41
timeseries     TS02              unusual_frequency              ISA 240 ¶A41 (보조)
relational     R01               new_counterparty               ISA 550 ¶A19
relational     R02               dormant_account_activity       PCAOB AS 2401 §B7
relational     R03               transfer_pricing_anomaly       ISA 550 ¶A21
relational     R04               missing_relationship           ISA 550 ¶A19 (보조)
duplicate      L2-03a            exact_duplicate_amount         PCAOB AS 2401 §B7 (직접)
duplicate      L2-03b            fuzzy_duplicate                PCAOB AS 2401 §B7 (보조)
duplicate      L2-03c            split_transaction              PCAOB AS 2401 §B7 (보조)
duplicate      L2-03d            time_shifted_duplicate         PCAOB AS 2401 §B7 (보조)
intercompany   IC01              unmatched_intercompany         ISA 550 ¶A20
intercompany   IC02              amount_mismatch                ISA 550 ¶A20 (보조)
intercompany   IC03              timing_gap                     ISA 550 ¶A20 (보조)
```

unsupervised의 VAE는 단일 sub-detector. ML model이므로 evidence_tier는 model 자체가 아닌 score quantile 기반 평가.

## Key Decisions

1. **family ranking은 분포 진단 기반 gated hierarchical RRF로 정의한다** (2026-05-19)
   - Rationale: 5 family hit rate가 10^4 배 차이남(intercompany 0.003% ~ unsupervised 99.99%). 등가 5-way RRF는 timeseries(87% hit, 이산값 0.4/0.8 tie 블록) noise mass가 큐 상단을 오염시킴. 상관 max\|ρ\|=0.21은 보완성 근거이지 등가 voting 근거 아님.
   - Alternatives: 5-way equal RRF / mean / max / weighted sum
   - Trade-offs: 구조가 복잡해지지만 family 역할 명시화 + fitting parameter 0으로 truth-recall-guard 정합.

2. **family role classification은 training 시점에 pin한다** (2026-05-19)
   - Rationale: inference마다 metric으로 재분류하면 분기 경계 family(예: IC02/IC03 enrichment 진행 중)가 active ↔ near-dormant 진동. 재현성·Layer C5 cross-engagement 안정성 위반.
   - Alternatives: 매 inference 재분류 / hysteresis 임계값
   - Trade-offs: 재학습 trigger를 기다려야 분류 변경 반영. 단 PHASE2 governance §6.2 trigger matrix와 일관.

3. **corroboration booster default + tail-only fallback** (2026-05-19)
   - Rationale: timeseries 단독 ranker 시 noisy mass 위험. 완전 제외 시 period_end·unusual_timing 보강력 손실.
   - Booster 수식: `eligible(doc)`이 active-ranker 또는 PHASE1 q95+ 진입 시에만 `1/(60 + rank_f_tail(doc))` 가산. parameter 0개.
   - Tail-only fallback: q95 threshold가 의미 없을 정도로 score가 이산값일 때.
   - Alternatives: 가중치 booster (weight × score) — fitting 위험.
   - Trade-offs: V7 §6에서 timeseries가 강한 unusual_timing(100%)은 unsupervised·relational도 100%이므로 booster 모드에서도 회수 가능.

4. **evidence_tier는 truth 성능으로 조정 금지, 기준서 또는 분포 metric 출처 강제** (2026-05-19)
   - Rationale: strong_subdetector_count·max_subdetector_evidence_tier가 새 truth-recall 튜닝 손잡이가 될 위험.
   - 강제: 각 tier에 PCAOB AS 2401·ISA 240·ISA 550 인용 또는 분포 metric 측정값 출처 필수. schema test로 누락 차단.
   - Alternatives: 사후 튜닝 허용
   - Trade-offs: tier 변경이 PR 비용 증가. D044 fitting-risk check 통과 필수.

5. **ECDF는 RRF 입력이 아닌 confidence·tie-break·LLM citation 보조 점수** (2026-05-19)
   - Rationale: RRF는 rank 기반이라 ECDF가 필수 아님. ECDF는 [0,1] 표준 점수가 필요한 곳(dashboard, tie-break, narrator) 전용.
   - Alternatives: ECDF를 RRF 입력으로 강제
   - Trade-offs: 4 rule-style family ECDF artifact 생성·저장 비용. 단 family별 quantile만 저장하면 됨(분포 자체 아님).

6. **PHASE2 internal hierarchical RRF + PHASE1↔PHASE2 final RRF 2단 구조** (2026-05-19)
   - Rationale: PHASE2 family 수 변동(IC02/IC03 활성화 등)이 PHASE1 voting weight를 흔들지 않도록 hierarchy 분리.
   - 구조: `phase2_internal_rrf` → 1 voter로 묶어 final RRF에서 phase1_composite와 2-way k=60.
   - Alternatives: 6-way flat RRF (phase1 + 5 family)
   - Trade-offs: hierarchy 1단 추가. 단 final RRF는 기존 `compute_rrf_score` 호출 변경 없음.

## Known Issues
- intercompany family는 V7 fixed3 기준 IC01만 부분 활성(34행), IC02/IC03 carry-over. Phase A에서 tier 부여는 하되, Phase B/C/E에서 `row_nonzero_rate < 0.001`로 near-dormant 자동 분류 → global ranker 제외.
- duplicate L2-03b/c/d는 hit count는 많으나(2024 기준 80,029 / 16,784 / 28,590) score 분해능이 낮을 가능성. Phase B 측정에서 `top_tail_resolution` 확인 필요.
- timeseries TS02 86% hit는 Diag-1 후에도 미해결. coarse-booster 강제 사유로 명시.

## V7 fixed3 측정 baseline (Phase C 비교 대상)
TOP 100/500/1,000 case recall (기존 2-way RRF, document 단위):
- TOP 100 → 16.61% (103 docs)
- TOP 500 → 43.23% (268 docs)
- TOP 1,000 → 52.26% (324 docs)

Phase C measurement는 hierarchical RRF + booster 적용 결과를 같은 표 위에 추가하고, 차이의 도메인 정합성을 §6 시나리오 coverage로 설명한다.

## Reference Artifacts (read-only)
- `docs/spec/PHASE2_GOVERNANCE_DESIGN.md` 결정 4~7, kpi_baseline.json 패턴
- `docs/spec/PHASE2_INTERFACE_DESIGN.md` 결정 3 옵션 Z
- `docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md` §3·§4·§6
- `artifacts/phase2_family_correlation_matrix_20260519.md` Spearman·Jaccard
- `docs/spec/CONSTRAINTS.md` PHASE1 truth-recall-guard 3-Layer 정책

## 메모리 정합 체크
- `feedback_phase1_truth_recall_guard` — tier·booster 파라미터 0개 정합
- `feedback_ecdf_ensemble` — ECDF 사용 정합 (보조 점수로 분리)
- `feedback_subagent_korean` — 본 문서 한국어 정합
- `feedback_preserve_history` — Phase C·E 측정 결과를 매 회차 별도 파일로 누적
- `feedback_cross_reference_issues` — V7_FIXED3_PHASE2와 본 plan 양쪽에 교차 참조
