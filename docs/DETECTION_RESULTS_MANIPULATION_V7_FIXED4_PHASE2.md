# Phase2 native case 결과 — V7 fixed5_normalcal5 재측정

> **문서 상태 (2026-05-30)**: 파일명은 과거 fixed4 문서명을 유지하지만, 본문은 `fixed5_normalcal5` 데이터와 S7 PHASE2 native case 구현 이후 재측정한 결과로 갱신했다. 2026-05-26 이전의 PHASE1 case-level family overlay 수치는 본문 기준선으로 사용하지 않는다.

> **역할 원칙**: PHASE1/PHASE2는 fraud 확정기가 아니다. 본 문서의 truth 기반 recall은 DataSynth 합성 데이터에 대한 개발 검증용 지표이며, 실제 운영 부정 탐지 성능으로 주장하지 않는다.

> **측정 단위 변경**: 이전 문서는 `PHASE1 case + PHASE2 family overlay` 기준이었다. 본 문서는 PHASE2가 실제로 만든 native case 단위(pair / edge / row / window)를 family별로 정렬해 측정한다.

> **측정 계약 고정**: 제품형 비교는 action tier 기준이다. PHASE1은 `즉시검토(high) / 검토대상(medium) / 후보(low)` 3단계로 보고, PHASE2 rule/evidence family는 `strong / moderate / weak` evidence tier로 본다. 단, VAE/unsupervised는 도메인 rule tier가 아니라 정상 패턴에서 멀어진 정도를 보는 통계 lane이므로 예외적으로 anomaly-distance TOP-N을 유지한다. recall은 각 tier 또는 TOP-N에 포함된 `document_id` 기준 unique synthetic truth document 수로 계산한다.

> **재현성 메모**: `intercompany`, `relational`, `duplicate`, `timeseries` rule-style lane은 fixed5 재측정에서 exact aggregate가 재현된다. `unsupervised` Stage7 측정 경로는 q95 boundary 부근 ML score row가 소폭 흔들릴 수 있어 smoke test는 exact value가 아니라 bounded measurement band와 scenario 구성 계약을 검증한다. 본문 수치는 현재 체크인된 aggregate artifact snapshot 기준이다.

---

## 1. 입력과 산출물

| 항목 | 값 |
|---|---:|
| 데이터셋 | `datasynth_manipulation_v7_candidate_fixed5_normalcal5` |
| 전체 row | 1,034,269 |
| 전체 document | 318,653 |
| synthetic truth document | 620 |
| PHASE2 native family | unsupervised, timeseries, relational, duplicate, intercompany |
| 공식 평가 범위 | PHASE2 native case 단독 lane |

주요 산출물:

- `artifacts/phase2_native_case_remeasure_fixed5_20260528.json`
- `artifacts/action_tier_phase1_phase2_fixed5_20260530.json`
- `artifacts/phase2_family_responsibility_recall_fixed5_20260530.json`
- `artifacts/phase2_family_responsibility_recall_v21_fixed5_20260530.json`
- `artifacts/phase2_family_responsibility_recall_v21_fixed5_dupmeta_20260530.json`
- `artifacts/phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.json`
- `artifacts/phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json`
- `artifacts/phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.json`
- `artifacts/relational_v32_companion_contribution_20260531.json`
- `artifacts/relational_v31_owned_improvement_fixed5_20260531.json`
- `artifacts/unsupervised_v31_improvement_next_fixed5_20260531.json`
- `artifacts/duplicate_v31_improvement_next_fixed5_dupmeta_20260531.json`
- `artifacts/duplicate_v32_companion_sidecar_burden_20260531.json`
- `tools/scripts/measure_phase2_native_cases_fixed5_20260528.py`
- `tools/scripts/measure_phase2_family_responsibility_recall_fixed5_20260530.py`
- `tools/scripts/measure_phase2_family_responsibility_recall_v21_fixed5_20260530.py`
- `tools/scripts/measure_phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.py`
- `tools/scripts/measure_phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.py`
- `tools/scripts/measure_phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.py`

현재 제품 해석은 단일 score가 아니라 family별 독립 native review case lane이다.

---

## 1.1 Responsibility-map recall v3.3d — canonical candidate owner policy

2026-06-01에 `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d` 기준 responsibility map을 새로 생성했고, v3.3d = current canonical responsibility map candidate로 둔다. v3.3b/v3.2d는 historical responsibility map으로 보존한다. 공식 family target recall 후보는 v3.3d의 `primary` denominator를 사용하고, `companion/context`는 evidence contribution으로 분리한다. 모든 산출물은 diagnostic-only이며 PHASE1/PHASE2 production ranking, gate, fusion, detector threshold를 변경하지 않는다.

핵심 구분:

- 620 전체 recall은 **portfolio contribution**이다.
- V1 expected owner set은 **inclusive baseline**이다.
- V3는 DataSynth owner stamp를 traceability artifact로 옮긴 historical iteration이다.
- V3.3d primary owner recall은 rule/evidence families의 **diagnostic candidate target performance**다.
- VAE/unsupervised의 v3.3d `primary 40`은 **debug-only statistical denominator**이며 fraud primary recall family 목표가 아니다.
- V3.3d companion/context는 **evidence contribution**이다.
- Owner assignment는 detector-blind / score-blind / rank-blind / matched-result-blind로 수행한다.
- Raw `document_id`, `row_id`, `index_label`, `phase2_case_id` 계열 식별자는 responsibility artifact에 저장하지 않는다.

Canonical status:

- `v3.3d = current canonical responsibility map candidate`
- `v3.3b = historical responsibility map`
- `v3.2d = historical responsibility map`
- `v1/v2/v2.1/v3/v3.1 = historical iterations`
- `v3 = traceability experiment, not final policy`
- `policy_model = audit_rule_first_v33d_owner_metadata_with_suspense_override`
- interpretation = `family-specific owner metadata with evaluator-enforced rule-ownability override`

V3.3d primary target recall, current available product surface 기준:

| Owner | Primary docs | Matching family matched | Recall |
|---|---:|---:|---:|
| `phase1` | 483 | 429 | 88.82% |
| `intercompany` | 34 | 34 | 100.00% |
| `relational` | 23 | 0 | 0.00% |
| `duplicate` | 19 | 8 | 42.11% |
| `timeseries product/default` | 21 | 21 | 100.00% |
| `unsupervised / VAE debug statistical denominator` | 40 | 0 | 0.00%; debug only |

Timeseries 공식 product/default 결과는 `ts_specific_top100_stabilized_surface`
기준 21 / 21이다. 이전 ordering의 0 / 21은 사용자-facing 결과가 아니라
internal debug baseline으로만 보존한다. Detector/gate/threshold, PHASE1 ranking,
PHASE2 fusion은 변경하지 않았다.

Companion lifecycle recall:

| Metric | Truth docs | Matched | Recall |
|---|---:|---:|---:|
| relational companion | 116 | 4 | 3.45% |
| duplicate companion | 71 | 4 | 5.63% |
| timeseries context | 92 | 0 | 0.00% |
| statistical companion | 404 | 6 | 1.49% |

이 수치는 primary target recall이 아니라 evidence companion lifecycle metric이며, product default 채택 근거로 단독 사용하지 않는다.

Relational companion adopted-surface diagnostic:

| Relational surface | TOP100 companion / 139 | TOP500 companion / 139 | TOP1000 companion / 139 | Notes |
|---|---:|---:|---:|---|
| native/current baseline | 5 | 17 | n/a | older native evidence-tier order; TOP1000 scenario breakdown unavailable |
| adopted audit-then-business surface | 7 | 33 | 81 | R03/R07 structural + R01/R02 moderate, R05/R06 TOP500 share 0.0 |

TOP500 adopted companion split is approval/SOD 7, IC circular 9, embezzlement 17. Under v3.3b, relationship-primary denominator is available separately, so this companion table is evidence contribution only and is not used as a substitute for primary recall.

Relational v3.3b primary TOP100 diagnostic:

| Relational surface | TOP100 primary / 20 | TOP500 primary / 20 | TOP1000 primary / 20 | Product status |
|---|---:|---:|---:|---|
| current native order | 0 | 0 | 0 | debug baseline |
| adopted audit-then-business | 0 | 13 | 20 | current product review surface |
| employee-vendor observable profile | 20 | 20 | 20 | diagnostic only; not adopted |

The employee-vendor profile candidate uses observable GL context only, but it is not a product-default proposal yet. It depends on recognizable fixed5 v3.3b employee-vendor reference/counterparty tokens and brings high R05 context pressure into TOP500. It is useful as a proof that TOP100 lift is possible without truth labels, not as a stable product policy.

Relational v3.3d shortcut-free follow-up:

| Relational surface | TOP100 primary / 23 | TOP500 primary / 23 | TOP1000 primary / 23 | TOP500 sub-rule pressure | Product status |
|---|---:|---:|---:|---|---|
| current native order | 0 | 0 | 0 | R05 260, R06 160, R07 80 | debug baseline |
| adopted audit-then-business | 0 | 15 | 23 | R01 248, R02 2, R07 250 | current product review surface |
| employee-vendor observable profile | 23 | 23 | 23 | R01 94, R05 373, R07 33 | diagnostic proof; standalone product adoption still blocked |

The v3.3d profile surface remains shortcut-free with respect to owner metadata in journal
columns, and its selector inputs are GL-observable reference/counterparty text,
business process, account class, document support, sub-rule, evidence tier, and
family score. However, TOP500 includes 373 R05 cases, so the profile is still a
high-pressure context surface. It can justify a bounded annotated prefix only if
kept behind no-fitting metadata and monitoring; it should not replace the
audit-then-business surface as a standalone recall-optimized product policy.

해석 변경:

- IC result is 34 / 34 on the v3.3d full run. Intercompany is fully surfaced in TOP500 with 246 case objects.
- Relational primary 23은 `employee_vendor_hidden_relationship` owner metadata로 정의한 current candidate denominator다. Circular related-party 34건은 IC primary + relationship companion이며 relational primary로 세지 않는다. v3.3d native/current order는 TOP500 0 / 23이다.
- Duplicate primary 19는 `time_shifted_duplicate` / natural expense reference pair evidence로 정의한 current candidate denominator다. Native TOP500은 8 / 19이며, duplicate companion 71은 primary recall과 섞지 않는다.
- Timeseries는 113 전체가 primary가 아니다. `period_end_adjustment_manipulation` 92건은 `PHASE2_TIMESERIES_ROLE_LOCK.md`와 정합되게 companion_context이고, primary는 timing-only 21건이다. Product/default는 `ts_specific_top100_stabilized_surface` 기준 TOP100/TOP500 21 / 21이다. 이전 ordering 0 / 21은 internal debug baseline이다.
- suspense는 rule-first로 lock한다. `suspense_account_abuse` 100건은 PHASE1 primary + statistical companion이다.
- VAE debug denominator 40은 `fictitious_existence_statistical` statistical subtype의 feature-space 진단용이다. Statistical companion 404가 제품 역할의 중심이며, 두 수치를 fraud primary recall 또는 필수 포착 목표로 섞지 않는다.
- Fictitious split은 data-derived truth subtype이다. v3.3b subtype lock은 `fictitious_existence_statistical` 40, `fictitious_account_policy` 50, `fictitious_period_end_like` 41, `fictitious_duplicate_like` 37이다.
- VAE `0 / 40`은 exact matched-document join으로 남기는 debug-only feature-space diagnostic이다. 제품 판단은 broad statistical review contribution, repeated-normal pressure, PHASE1 밖 보완, evidence explainability로 한다.
- PHASE1 primary 483은 responsibility taxonomy의 책임 분모이고, portfolio cumulative recall은 detector 성과다. 두 수치는 의미가 다르다.
- Circular related-party 34건은 v3.3d owner map에서 IC primary이며 relationship companion이다. Relational primary는 `employee_vendor_hidden_relationship` 23건이다.
- Primary overlap count는 0이며 IC/relational primary overlap도 0이다.
- `no_clear_owner=0`은 ambiguity 부재 증거가 아니라 rule-only structure 결과다.
- v3.3d는 318,653-document shortcut-free journal에서 PHASE2 native cases를 재실행하고 exact doc-id join으로 측정한다. 620 truth docs는 모두 journal에 존재한다.
- Family failure mode는 분리한다. IC = `fully_surfaced_top500`; relational / timeseries / VAE = `cases_produced_not_surfaced_top500`; duplicate = `partially_surfaced_top500`.
- Recall 하락은 shortcut removal과 realistic 318k scale이 함께 드러낸 honest measurement 결과다. Shortcut 재도입, DataSynth를 VAE score에 맞추는 수정, truth/owner/scenario feature 주입, threshold/weight recall fitting으로 해결할 문제가 아니다.

Duplicate metadata follow-up:

`datasynth_manipulation_v7_candidate_fixed5_dupmeta` 후보는 거래 데이터를 바꾸지 않고 Duplicate 평가용 metadata와 `duplicate_pair_truth` sidecar만 추가한다. 이 metadata를 optional truth input으로 읽으면 Duplicate primary denominator는 76문서/38 pair group으로 산출된다. Primary target은 `embezzlement_concealment` duplicate-like pair metadata이며, `period_end_adjustment_manipulation` 92건은 Duplicate primary로 승격하지 않는다. 현재 native Duplicate TOP500은 이 primary target 76건을 포함하지 못하고, 기존 22건은 period-end companion context contribution으로 남는다. 이 측정은 denominator-only diagnostic이며 detector score, threshold, PHASE1 ranking, PHASE2 fusion에는 사용하지 않는다.

Duplicate primary-target attrition:

`artifacts/duplicate_primary_target_fixed5_dupmeta_20260530.json` 기준, Duplicate primary 76문서 중 28문서만 duplicate row score를 갖고 48문서는 row score가 없다. Row score가 있는 28문서도 모두 `L2-03d` time-shifted evidence로 score가 `0.42857142857142855`이며, large-input artifact candidate subset의 retained minimum score `0.5989857631894374`보다 낮다. 따라서 candidate subset primary docs, generated pair primary docs, top_pairs primary docs, DuplicateCase primary docs가 모두 0이다. Retention cap을 50,000까지 늘려도 primary target은 회수되지 않는다. 병목은 first-review ranking이 아니라 row-score coverage와 bounded candidate subset 진입 전 단계다.

`artifacts/duplicate_v31_primary_readiness_fixed5_dupmeta_20260531.json`은 이 결론을 compact readiness contract로 다시 고정한다. Primary pair group은 38개이고, row-score primary rows는 54개다. Retention sizes 500/2,000/10,000/50,000 모두 primary docs 0이므로 `top_pairs` cap은 v3.1 primary miss의 병목이 아니다. 다음 개선 class는 `row_score_feature_coverage_or_observable_lower_score_pair_path`이며, row-score threshold 완화, top_pairs cap 확대, weak pair 승격, truth metadata selector 사용은 모두 금지한다.

Candidate sidecar sampling:

`artifacts/duplicate_candidate_sidecar_fixed5_dupmeta_20260530.json`은 main 50k candidate subset을 유지한 채 별도 diagnostic sidecar를 비교한다. `l2_03d_stratified_low_score_sample`과 `rule_balanced_duplicate_candidate_sample`은 각각 10,000 candidate docs를 만들었지만 Duplicate primary docs는 0건이었다. `duplicate_primary_metadata_probe_sample`은 oracle feasibility probe로만 76 primary docs를 모두 pair evidence까지 보냈고, case-grade primary docs도 76건이었지만 weak pair ratio가 97.76%다. 따라서 non-oracle sidecar는 아직 product candidate가 아니며, metadata probe 결과를 main selector/ranking에 사용할 수 없다. Current first-review surface와 DuplicateCase ordering은 유지한다.

V3.2d duplicate companion burden reduction:

`artifacts/duplicate_v32_companion_sidecar_burden_20260531.json`은 v3.2d `duplicate_companion=111` 기준으로 current path와 observable guard 후보를 다시 읽는다. Duplicate primary denominator는 0이므로 이 표는 primary recall이 아니라 companion evidence lifecycle 진단이다.

| Candidate | Candidate docs | Companion docs entering | Non-target docs | Companion candidate recall | Read |
|---|---:|---:|---:|---:|---|
| current duplicate path | n/a | 0 | n/a | 0.00% | v3.2d responsibility artifact estimate |
| observable profile top 10k | 10,000 | 76 | 9,924 | 68.47% | high burden |
| observable profile top 5k | 5,000 | 76 | 4,924 | 68.47% | same coverage, lower burden |
| observable profile top 2k | 2,000 | 76 | 1,924 | 68.47% | best broad-profile burden reduction |
| strict time-shift/reference guard | 2,239 | 28 | 2,211 | 25.23% | audit-stable but loses too much coverage |

Selector inputs are observable GL fields only: document row count, business process, trading partner, reference similarity, posting-date distance, and amount proximity. Truth label, owner metadata, pair-group truth, PHASE1 rank, and matched result are not selector inputs. Product first-review ranking, row-score threshold, `top_pairs` cap, weak-pair gate, PHASE1 ranking, and PHASE2 fusion remain unchanged. The result is not product adoption; the next step is bounded 2k pair-artifact generation and case-grade ratio validation.

V3.3b duplicate exact sidecar follow-up:

`artifacts/duplicate_v33_exact_sidecar_fixed5_20260531.json`은 v3.3b owner map 기준 Duplicate primary 22건과 companion 71건을 exact sidecar 평가로 다시 측정한다. 2026-06-01 follow-up에서 production duplicate path는 bounded observable-profile supplement와 rule-balanced pair selection, document-profile pair builder를 적용했다. Row score, weak-pair gate, `top_pairs` cap, PHASE1 ranking, PHASE2 fusion은 변경하지 않았다.

| Candidate | Candidate docs | Primary case-grade / 22 | Companion case-grade / 71 | Non-target docs | Product status |
|---|---:|---:|---:|---:|---|
| current duplicate path | 27,635 subset docs | 10 | 4 | 27,579 | production path after bounded supplement |
| observable profile top 2k | 2,000 | 22 | 34 | 1,944 | broad bounded baseline |
| observable profile top 1k | 1,000 | 22 | 34 | 944 | diagnostic-only |
| observable profile top 500 | 500 | 22 | 34 | 444 | bounded export/drilldown candidate |
| strict time-shift/reference guard | 36 | 10 | 4 | 22 | low burden, low coverage |

`observable_profile_top_500`은 top2k 대비 primary/companion coverage를 유지하면서 non-target burden을 1,944에서 444로 낮춘다. 다만 이는 sidecar/export/drilldown 후보이며 current product path는 그중 엄격한 observable pair evidence가 실제 생성되는 10 / 22 primary docs만 회수한다. 남은 12 primary docs는 candidate subset에는 들어오지만 현재 GL observable pair builder 조건에서 case-grade pair evidence가 생성되지 않는다.

Historical v3.2d pending / refinement trigger condition:

- Relational primary는 v3.2d에서 `no_primary_denominator`다. Relationship-only primary product spec이 별도 잠기기 전까지 relational은 companion contribution으로 추적한다.
- Duplicate primary는 v3.2d에서 `no_primary_denominator`다. Duplicate-like evidence는 duplicate companion 111건으로 추적하고, pair evidence validation 전까지 primary recall로 확정하지 않는다.
- Unsupervised는 v3.2d에서 `fictitious_existence_statistical` 49건을 debug statistical denominator로만 둔다. Suspense/expense 등 companion set은 primary recall 목표로 승격하지 않는다.
- Timeseries primary는 현재 timing-only 21 유지. period_end 92는 companion_context.

Relational relmeta follow-up:

Historical relmeta note: `datasynth_manipulation_v7_candidate_fixed5_relmeta` 후보는 거래 데이터를 바꾸지 않고 Relational 평가용 `relationship_edge_truth.csv/json` sidecar만 추가했다. 이 v2.2 sidecar는 historical denominator experiment이며, v3.2d policy의 `pending_relationship_primary_metadata` 상태도 historical로 보존한다. v3.3b는 `employee_vendor_hidden_relationship` 20건을 relationship primary candidate로 다시 분리했다. Sidecar는 detector/ranker/fusion/UI scoring input이 아니라 evaluation denominator다.

- Historical v2.2에서는 primary owner를 exclusive로 두지 않았고 `circular_related_party_transaction` 34건을 IC와 relational co-primary로 두었다.
- Current v3.3b는 circular related-party 34건을 IC primary + relationship companion으로 두며 relational primary에는 포함하지 않는다.
- `multi_primary=0` 원칙은 current v3.3b responsibility map에서 다시 유지된다.
- R05/R06는 계속 context/diagnostic-only lane이다.
- Production ranking/gate/fusion은 변경하지 않았다.

Historical V2.2 relmeta 결과 (v3.1 canonical 이전):

| Metric | Value |
|---|---:|
| relational primary truth docs | 63 |
| relational primary matched docs | 9 |
| relational primary recall | 14.29% |
| relational primary TOP100 matched docs | 4 |
| relational primary TOP500 matched docs | 9 |
| relational secondary truth docs | 76 |
| relational secondary matched docs | 8 |
| co-primary overlap count | 34 |
| IC primary recall | 34 / 34 |

Historical V3 fixed5_ownermeta_ic consolidation (traceability experiment, not final policy):

`datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic`는 IC/relational/duplicate/timeseries/unsupervised owner metadata를 한 truth file에 포함한다. v3 relocated owner policy into DataSynth metadata for traceability. v3/v3.1 are diagnostic responsibility maps, not production detector changes. `truth_owner_primary`는 legacy representative summary이며 exclusive owner가 아니다.

| Owner | Primary docs | Native TOP500 matched | Recall | Source |
|---|---:|---:|---:|---|
| phase1 | 192 | 184 | 95.83% | legacy `truth_owner_primary == "phase1"` fallback |
| intercompany | 34 | 34 | 100.00% | `injected_intercompany_primary` |
| relational | 63 | 9 | 14.29% | `injected_relationship_edge_primary` |
| duplicate | 76 | 0 | 0.00% | `duplicate_primary_target` / `injected_duplicate_like` |
| timeseries | 21 | 0 | 0.00% | `injected_timing_primary` |
| unsupervised | 268 | 20 | 7.46% | `broad_statistical_only_owner` |

V3 co-primary overlap:

- `intercompany ∩ relational = 34`
- circular 34건은 IC primary이면서 relational primary다.
- Family table에는 overlap을 표시하지만 portfolio total에는 중복 합산하지 않는다.

V3 context / companion:

| Metric | Truth docs | Matched | Recall |
|---|---:|---:|---:|
| relational secondary | 76 | 8 | 10.53% |
| timeseries context | 92 | 0 | 0.00% |
| unsupervised companion | 239 | 17 | 7.11% |

V3 checks: truth docs 620, anomaly label docs 620, expected primary counts match, non-circular IC primary 0, circular IC primary 34, raw identifier leak 0, forbidden identifier key 0. Owner assignment does not use detector output, score, rank, TOP-N matched result, or production ordering.

V3.1 audit-rule-first reconciliation:

v3.1 reconciles the DataSynth metadata with audit-rule-first responsibility policy. v3.1은 v3 traceability artifact를 보존하면서 일부 scenario-wide owner stamp를 보수적으로 재해석한다. DataSynth family metadata는 owner 후보 신호이며, 감사 의미와 충돌하는 경우 audit-rule-first policy가 override한다.

Canonical status:

- v3.3d = current canonical responsibility map candidate
- v3.3b = historical responsibility map
- v3.2d = historical responsibility map
- v1/v2/v2.1/v3/v3.1 = historical iterations
- v3 = traceability experiment, not final policy
- policy_model = `audit_rule_first_reconciled_with_datasynth_family_flags`
- interpretation = `audit-rule-first scenario policy with DataSynth family flags as candidate signals`

| Owner | V3.1 primary docs | Native TOP500 matched | Recall | Policy |
|---|---:|---:|---:|---|
| phase1 | 397 | 350 | 88.16% | audit-rule-first derived policy |
| intercompany | 34 | 34 | 100.00% | IC primary 유지 |
| relational | 34 | 9 | 26.47% | circular related-party co-primary only |
| duplicate | 0 | 0 | pending | pending pair evidence validation |
| timeseries | 21 | 0 | 0.00% | timing primary 유지 |
| unsupervised | 168 | 20 | 11.90% | historical debug statistical denominator |

V3.1 context / companion:

| Lane | Truth docs | Matched | Recall |
|---|---:|---:|---:|
| relational secondary | 105 | 8 | 7.62% |
| duplicate companion | 76 | 0 | 0.00% |
| timeseries context | 92 | 0 | 0.00% |
| unsupervised companion | 339 | 17 | 5.01% |

V3.1 policy diff:

- `approval_sod_bypass`: PHASE1 primary, relational secondary.
- `embezzlement_concealment`: PHASE1 primary, duplicate/relational/unsupervised companion.
- `suspense_account_abuse`: PHASE1 primary, unsupervised companion.
- `fictitious_entry`: v2.1에서는 expense와 함께 PHASE1 primary로 통일했지만, v3.1은 existence assertion과 classification error를 분리했다. 이 구분은 현재 historical/debug denominator이며 VAE product primary recall 목표가 아니다.
- `expense_capitalization`: 실재 거래는 존재하지만 계정분류가 잘못된 classification error이므로 PHASE1 primary 유지.
- `circular_related_party_transaction`: IC + relational co-primary 유지.

Duplicate metadata backlog:

- `injected_duplicate_like` boolean 필요
- `duplicate_pair_semantic_group` 필요
- reference / amount / text similarity injection source 필요

Leakage guard 결과는 raw identifier leak 0, forbidden identifier key 0, PHASE2 case-id-like token 0이며,
owner assignment artifact와 recall result artifact는 독립 산출물로 기록한다.

세부 기록은 `docs/debugging/PHASE2_FAMILY_RESPONSIBILITY_RECALL_20260530.md`와
`docs/users/16_PHASE2_RESPONSIBILITY_MAP_DECISION.md`를 따른다.

---

## 2. 한눈에 보는 결론 — action tier + responsibility-map 기준

PHASE2 native case 기준 결과는 과거 PHASE1 case-level overlay 결과보다 훨씬 엄격하다. 다만 제품 판단은 단순 TOP100보다 action tier가 더 적절하다. PHASE1은 `즉시검토 / 검토대상 / 후보`, PHASE2 rule/evidence family는 `strong / moderate / weak`로 본다. VAE/unsupervised는 fraud primary recall family가 아니므로 anomaly distance TOP-N은 broad statistical review contribution과 pressure를 읽는 보조 지표로만 유지한다.

판단:

1. PHASE1 action-tier 기준 `즉시검토(high)`는 264 / 620 truth document(42.58%)를 포함한다. `즉시검토+검토대상(high+medium)`은 354 / 620(57.10%)다. Responsibility-map v3.3b 기준 PHASE1 primary target은 483건이고, 이 중 PHASE1 candidate-or-higher가 429건(88.82%)을 포함한다.
2. `intercompany`는 v3.3b primary target 34 / 34를 모두 잡는다. PHASE1 즉시검토 밖 truth 32건을 IC strong evidence로 끌어올리므로 IC locked 결론을 유지한다.
3. `relational`은 v3.3b에서 `employee_vendor_hidden_relationship` 20건을 primary candidate로 다시 분리했고, circular related-party 34건은 IC primary + relationship companion으로 둔다. Exact doc join 전까지 relational primary recall은 estimated proration으로 표시한다.
4. `duplicate`는 v3.3b에서 `time_shifted_duplicate` 22건을 primary candidate로 다시 분리했고, duplicate companion 71건은 sidecar/export evidence로 별도 추적한다. Primary recall과 companion recall을 섞지 않는다.
5. `timeseries`는 timing-only 21건을 primary target으로 본다. Product/default ordering은 `ts_specific_top100_stabilized_surface`이며 TOP100/TOP500 21 / 21이다. 이전 ordering 0 / 21은 internal debug baseline이다. Period-end 92건은 primary가 아니라 companion context다. Detector/gate/threshold/PHASE1 ranking/PHASE2 fusion은 변경하지 않는다.
6. `unsupervised`는 v3.3b evaluator에서 suspense를 제외한 40건을 debug statistical denominator로만 측정한다. Adopted soft guard exact matched-doc join 기준 TOP500 10 / 40은 debug-only feature-space signal이며, statistical companion 404건과 broader TOP500 contribution을 제품 판단의 중심으로 둔다. q95 gate, VAE score/threshold, case generation, PHASE1 ranking, PHASE2 fusion은 변경하지 않는다.

2026-05-31 follow-up:

- Relational owned recall은 product default ordering을 바꿔도 기존 surface 안에서는 거의 개선되지 않는다. Adopted surface는 9 / 34이고, best observed circular-primary TOP500 surface도 10 / 34에 그친다. 다음은 ordering 튜닝이 아니라 IC reciprocal evidence와 relational R03/R07 edge evidence 사이의 aggregate bridge gap을 봐야 한다.
- VAE는 adopted soft guard를 broad statistical review companion surface로 유지한다. v3.2d exact 기준 `soft_guard_context_top100_probe`는 TOP100/TOP500 추가 lift가 없고, `soft_guard_with_row_count_context`도 debug-denominator lift 없이 repeated-normal pressure만 0.244 -> 0.284로 올린다. Upper-bound는 TOP100 7 / 49까지 가지만 pressure 0.746이라 product default로 부적합하다.
- Duplicate는 top_pairs/retention 문제가 아니라 candidate generation before pair evidence 문제다. 다음 실험은 bounded L2-03d lower-score pair path와 same-account relaxation diagnostic이다. Truth/owner metadata selector, global threshold 완화, weak-pair 승격은 금지한다.

2026-05-31 v3.2d exact VAE follow-up:

- Suspense는 PHASE1 primary로 lock됐고, VAE debug statistical denominator는 `fictitious_existence_statistical` 49건이다.
- VAE debug measurement는 scenario-level proration이 아니라 exact matched-document join으로 본다.
- v3.2d journal 직접 입력 기준 exact debug-denominator TOP500은 native 0 / 49에서 adopted soft guard 10 / 49로 오른다.
- `soft_guard_context_top100_probe`는 TOP100/TOP500을 추가 개선하지 못하므로 diagnostic-only로 유지한다.
- `soft_guard_with_row_count_context`도 debug-denominator TOP500은 10 / 49로 동일하고 repeated-normal pressure가 0.244 -> 0.284로 올라 default replacement가 아니다.

2026-06-01 v3.3b exact VAE follow-up:

- VAE debug statistical denominator는 v3.3b evaluator policy 기준 40건이다.
- Adopted soft guard는 TOP100 2 / 40, TOP500 10 / 40, TOP1000 16 / 40, TOP10000 16 / 40이며 TOP500 repeated-normal pressure는 0.242다.
- `soft_guard_context_top100_probe`와 `soft_guard_with_row_count_context`는 추가 lift가 없다.
- 새 selector-safe `v33_statistical_signal_probe`는 TOP500 0 / 40, pressure 0.586으로 reject한다.
- `v33_pressure_capped_signal_probe`는 pressure 0.218로 낮지만 TOP500 1 / 40이라 coverage 손실이 크다.
- Upper-bound hybrid는 TOP100 7 / 40, TOP500 16 / 40까지 오르지만 pressure 0.740이라 product default 후보가 아니다.
- Soft guard TOP500이 잡는 debug-denominator 문서는 10건, 놓치는 문서는 30건이다. 놓친 30건 중 24건은 current VAE case surface 밖이므로 pure ordering re-rank만으로는 해결되지 않는다.

---

## 3. PHASE1 action tier recall

PHASE1은 `priority_band`를 제품 언어로 매핑한다.

| PHASE1 action tier | priority_band | case 수 | document 수 | truth docs | recall |
|---|---|---:|---:|---:|---:|
| 즉시검토 | high | 230 | 4,960 | 264 / 620 | 42.58% |
| 검토대상 | medium | 503 | 2,662 | 194 / 620 | 31.29% |
| 후보 | low | 22,433 | 21,975 | 456 / 620 | 73.55% |

누적 기준:

| PHASE1 cumulative tier | 포함 band | case 수 | document 수 | truth docs | recall |
|---|---|---:|---:|---:|---:|
| 즉시검토 이상 | high | 230 | 4,960 | 264 / 620 | 42.58% |
| 검토대상 이상 | high+medium | 733 | 6,857 | 354 / 620 | 57.10% |
| 후보 이상 | high+medium+low | 23,166 | 24,790 | 544 / 620 | 87.74% |

`후보 이상` 544 / 620은 broad inclusion metric이다. PHASE1이 의도된 오류를 정확한 scenario/evidence로 설명했다는 뜻이 아니며, PHASE2 value 판단의 단독 기준으로 쓰지 않는다.

### 3.1 PHASE1 owned 미포착 사유

Responsibility-map v3.1 기준 PHASE1 primary owner target은 397건이고, 이 중 PHASE1 후보 이상(high+medium+low)에 포함된 문서는 350건이다. 미포착 47건은 PHASE1 case priority에서 낮게 밀린 건이 아니라, 현재 PHASE1 룰 표면에서 raw rule hit가 생성되지 않은 문서다. 따라서 owned 점수제나 priority band 조정만으로는 회수되지 않는다.

| Scenario | 미포착 | PHASE1 primary 내 miss rate | 미포착 사유 |
|---|---:|---:|---|
| `embezzlement_concealment` | 39 | 39 / 76 = 51.32% | 직원 정산/카드 사적사용 의미는 truth metadata에 있지만, 현재 PHASE1은 이를 독립 employee-outflow/private-use 룰로 잡지 않는다. 승인/승인일/SoD가 정상이고 duplicate/outflow/approval-bypass 증거로 환산되지 않아 raw hit가 없다. |
| `period_end_adjustment_manipulation` | 8 | 8 / 92 = 8.70% | 기말 전표이고 SoD marker가 있지만 `source=automated`라 L1-06 human/source 필터에서 제외된다. 현재 정책상 automated SoD는 PHASE1 direct human 권한남용 hit로 보지 않는다. |

공통 특성:

- 47 / 47 모두 PHASE1 raw rule hit가 없다.
- 전부 2-line document이며 금액은 작지 않다. 39건은 `>=10m`, 8건은 `>=1m` bucket이다.
- 모든 미포착 문서에 `approved_by`와 `approval_date`가 있어 승인누락 계열 룰로 올라오지 않는다.
- 계정 조합은 두 가지로 수렴한다: embezzlement `1000,1200`, period-end adjustment `2200,6700`.

해석: 현재 룰 정의를 유지하면 이 47건은 PHASE1이 잡을 수 없는 coverage gap이다. PHASE1 primary recall을 올리려면 새 rule surface가 필요하고, 현 정책을 유지한다면 해당 문서는 PHASE2 companion/context 또는 DataSynth metadata 보강 대상으로 분리해야 한다.

---

## 4. PHASE2 action tier recall

PHASE2 rule/evidence family는 `strong`, `strong+moderate`, `all tiers`를 본다. VAE/unsupervised는 도메인 evidence tier가 아니라 거리 기반 statistical lane이므로 다음 절의 TOP-N 표를 따른다.

| Family | strong truth docs | strong recall | strong case 수 | strong+moderate truth docs | strong+moderate recall | strong+moderate case 수 | 상태 |
|---|---:|---:|---:|---:|---:|---:|---|
| `intercompany` | 34 / 620 | 5.48% | 34 | 34 / 620 | 5.48% | 246 | 정책 잠김 |
| `relational` | 190 / 620 | 30.65% | 56,989 | 244 / 620 | 39.35% | 57,640 | secondary evidence companion, adopted ordering 별도 |
| `duplicate` | 9 / 620 | 1.45% | 25 | 22 / 620 | 3.55% | 198 | primary denominator pending |
| `timeseries` | 8 / 620 | 1.29% | 861 | 8 / 620 | 1.29% | 861 | primary target recall 별도 실패 |

해석:

- `intercompany` strong은 case 수가 작고 evidence 의미가 선명하다. TOP100 circular 34 / circular scenario 34/34 coverage와 정합한다.
- `relational` strong은 raw tier만 보면 넓다. Responsibility-map v3.1에서는 circular 34건만 relational primary이며, 제품 default는 raw strong 전체가 아니라 `structural_moderate_audit_then_business_lane_split_surface` secondary evidence ordering으로 해석한다.
- `duplicate`는 embezzlement duplicate-like 76건을 pair-evidence validation 대기 대상으로 보존한다. Current v3.2d 책임맵에서는 companion evidence로 추적하며, primary target recall은 pending이다.
- `timeseries`는 timing-only primary target 21건 기준 product/default ordering에서 TOP100/TOP500 21 / 21이다. Period-end companion 92건과 섞어 "113건 target 실패"로 쓰지 않는다. 이전 ordering 0 / 21은 internal debug baseline이다.

---

## 5. PHASE1 action tier 밖을 PHASE2가 얼마나 보완하는가

아래 첫 표는 v3.2d primary denominator 기준으로 “PHASE1 즉시검토/검토대상에서 놓친 것을 PHASE2 family가 얼마나 다시 올렸는가”를 본다. Family별 primary set은 co-primary overlap을 허용하지만 portfolio total에는 중복 합산하지 않는다.

| PHASE2 family | v3.2d primary docs | family matched primary docs | PHASE1 즉시검토 밖 추가 | PHASE1 검토대상 이상 밖 추가 | PHASE1 후보 이상 밖 추가 | 해석 |
|---|---:|---:|---:|---:|---:|---|
| IC | 34 | 34 | 32 | 30 | 1 | IC-specific primary evidence. |
| Relational | 0 | 0 | 0 | 0 | 0 | primary denominator 없음. Companion 139건은 별도 evidence contribution으로 본다. |
| Duplicate | 0 | 0 | 0 | 0 | 0 | primary denominator 없음. Companion 111건은 별도 진단 대상이다. |
| Timeseries product/default | 21 | 21 | 21 | 19 | 0 | `ts_specific_top100_stabilized_surface` 기준. |
| Timeseries internal debug baseline | 21 | 0 | 0 | 0 | 0 | 사용자-facing 결과가 아닌 regression debug용. |
| Unsupervised native | 49 | 0 | 0 | 0 | 0 | v3.2d exact debug baseline. |
| Unsupervised soft guard default | 49 | 10 | 10 | 8 | 8 | VAE family list 기본 표시 ordering. q95 gate와 case generation은 불변. |

아래 표는 PHASE2 raw tier surface 기준이다. Responsibility-map primary recall과 다르며, review burden과 evidence surface 폭을 함께 해석해야 한다.

| PHASE2 family/surface | matched truth docs | PHASE1 즉시검토 밖 | PHASE1 검토대상 이상 밖 | PHASE1 후보 이상 밖 | 해석 |
|---|---:|---:|---:|---:|---|
| IC strong | 34 | 32 | 30 | 1 | IC-specific strong evidence 가치가 높다. |
| IC strong+moderate | 34 | 32 | 30 | 1 | moderate를 더해도 truth coverage는 strong과 동일하다. |
| Relational strong | 190 | 117 | 92 | 42 | broad structural evidence surface. review burden이 크다. |
| Relational strong+moderate | 244 | 149 | 122 | 45 | 넓은 edge evidence. product ordering은 adopted surface로 제한한다. |
| Duplicate strong | 9 | 3 | 2 | 0 | 진행 중. pair evidence 강한 subset만 보면 작다. |
| Duplicate strong+moderate | 22 | 11 | 5 | 0 | 진행 중. 현재는 period-end pair evidence 중심이다. |
| Timeseries product default | 21 | 21 | 19 | 0 | timing-primary product ordering. Period-end 92건은 context다. |

잠긴 family 기준:

- `intercompany`: PHASE1 즉시검토 밖 circular truth 32건을 strong IC evidence로 끌어올린다. 제품 역할은 `ic_specific_evidence_strengthening`.
- `relational`: v3.1/v3.2d 사이에서 owner denominator가 재정의됐기 때문에 과거 primary 수치를 product 포기 근거로 쓰지 않는다. Adopted product surface는 계속 `structural_moderate_audit_then_business_lane_split_surface`이며, DataSynth가 relationship-primary/co-primary denominator를 제공하면 primary recall을 다시 측정한다. 현재 companion metric은 interim evidence-placement 지표다.
- `timeseries`: product/default path는 `ts_specific_top100_stabilized_surface`이며 primary target TOP100/TOP500 21 / 21이다. 이전 ordering 0 / 21은 internal debug baseline이다. Period-end 92건은 primary denominator에 넣지 않는다.

---

## 6. VAE/unsupervised 예외 — distance TOP-N

VAE/unsupervised는 `strong/moderate/weak` rule tier가 아니라 정상 패턴에서 멀어진 정도를 보는 statistical lane이다. 따라서 예외적으로 TOP-N을 유지한다. 이 TOP-N은 fraud 확정 순위가 아니라 “모델이 정상 패턴에서 멀다고 본 순서”다.

| VAE distance surface | case 수 | document 수 | truth docs | recall | PHASE1 즉시검토 밖 | PHASE1 검토대상 이상 밖 | PHASE1 후보 이상 밖 |
|---|---:|---:|---:|---:|---:|---:|---:|
| TOP100 | 100 | 85 | 5 / 620 | 0.81% | 2 | 1 | 0 |
| TOP500 | 500 | 352 | 39 / 620 | 6.29% | 13 | 8 | 1 |
| TOP1000 | 1,000 | 692 | 90 / 620 | 14.52% | 36 | 23 | 4 |
| TOP10000 | 10,000 | 5,327 | 289 / 620 | 46.61% | 135 | 83 | 8 |

해석:

- `unsupervised`는 TOP100 즉시-hit family는 아니다.
- TOP500 이후에는 PHASE1 즉시검토 밖 truth를 점진적으로 끌어올리므로 broad expansion 가치가 있다.
- Historical V3.1 primary 기준으로는 `hybrid_with_soft_repeated_normal_guard`가 TOP500 23 / 168을 110 / 168로 끌어올려 family list 기본 표시 ordering이 됐다.
- 이 변경은 document-level review priority ordering 변경이다. q95 gate, VAE score/threshold, case generation, PHASE1 ranking, PHASE2 fusion은 바꾸지 않는다.

Historical V3.1 owner-role 기준:

| Diagnostic role | Surface | TOP100 | TOP500 | TOP10000 | 해석 |
|---|---|---:|---:|---:|---|
| debug denominator | native row queue | 12 | 23 | 111 | historical row-score baseline |
| debug denominator | soft guard default | 24 | 110 | 140 | broad statistical review priority diagnostic |
| companion | native row queue | 0 | 34 | 225 | companion context baseline |
| companion | soft guard default | 1 | 33 | 275 | companion TOP500 개선 없음 |

V3.2d exact owner-role 기준:

| Diagnostic role | Surface | TOP100 | TOP500 | TOP1000 | TOP10000 | TOP500 pressure | 해석 |
|---|---|---:|---:|---:|---:|---:|---|
| debug denominator | native row queue | 0 / 49 | 0 / 49 | 0 / 49 | 1 / 49 | 1.000 | exact v3.2d journal baseline |
| debug denominator | soft guard default | 2 / 49 | 10 / 49 | 13 / 49 | 13 / 49 | 0.244 | current single-list default |
| debug denominator | soft guard context TOP100 probe | 2 / 49 | 10 / 49 | 13 / 49 | 13 / 49 | 0.244 | diagnostic-only, default 변경 없음 |
| debug denominator | soft guard with row-count context | 2 / 49 | 10 / 49 | 13 / 49 | 13 / 49 | 0.284 | no diagnostic lift, pressure worsens |
| companion | native row queue | 3 / 395 | 4 / 395 | 7 / 395 | 91 / 395 | 0.992 | companion baseline |
| companion | soft guard default | 16 / 395 | 55 / 395 | 90 / 395 | 277 / 395 | 0.182 | companion context improves, debug denominator와 분리 |

V3.2d에서는 `suspense_account_abuse`를 PHASE1 primary로 lock하고, VAE debug denominator는 data-derived
`fictitious_existence_statistical` 49건만 본다. 따라서 v3.1의 168건 denominator와 직접 비교하지
않는다. v3.2d recall은 exact matched-document join 기준이며, 기존 scenario-level proration은 공식
수치가 아니다.

V3.3b exact owner-role 기준:

| Diagnostic role | Surface | TOP100 | TOP500 | TOP1000 | TOP10000 | TOP500 pressure | 해석 |
|---|---|---:|---:|---:|---:|---:|---|
| debug denominator | native row queue | 0 / 40 | 0 / 40 | 0 / 40 | 0 / 40 | 1.000 | exact v3.3b journal baseline |
| debug denominator | soft guard default | 2 / 40 | 10 / 40 | 16 / 40 | 16 / 40 | 0.242 | current single-list default |
| debug denominator | soft guard context TOP100 probe | 2 / 40 | 10 / 40 | 16 / 40 | 16 / 40 | 0.242 | diagnostic-only, default 변경 없음 |
| debug denominator | soft guard with row-count context | 2 / 40 | 10 / 40 | 16 / 40 | 16 / 40 | 0.280 | no diagnostic lift, pressure worsens |
| debug denominator | statistical signal probe | 0 / 40 | 0 / 40 | 1 / 40 | 16 / 40 | 0.586 | selector-safe but rejected |
| debug denominator | pressure-capped signal probe | 0 / 40 | 1 / 40 | 2 / 40 | 16 / 40 | 0.218 | lower pressure but coverage collapses |
| debug denominator | upper-bound hybrid | 7 / 40 | 16 / 40 | 16 / 40 | 16 / 40 | 0.740 | coverage upper-bound, not adoptable |
| companion | native row queue | 0 / 404 | 3 / 404 | 9 / 404 | 81 / 404 | 0.994 | companion baseline |
| companion | soft guard default | 16 / 404 | 53 / 404 | 87 / 404 | 265 / 404 | 0.184 | companion context improves, debug denominator와 분리 |

V3.3b follow-up은 soft guard가 잡는 debug-denominator 10건과 놓치는 30건을 selector-observable feature로 분해했다.
놓친 30건 중 24건은 current VAE case surface 밖이므로 pure ordering re-rank만으로는 TOP100/TOP500을
크게 회복하기 어렵다. 새 selector-safe 후보들도 default를 넘지 못했기 때문에 다음 개선은 ranking이
아니라 VAE feature representation / signal separation 쪽이다.

---

## 7. 참고용 native TOP-N 결과

아래 표는 과거 비교와 디버깅을 위한 참고 지표다. 제품 판단의 1차 기준은 위 action-tier 표다.

| Family | TOP100 | TOP500 | TOP1000 | TOP2000 | TOP5000 | TOP10000 |
|---|---:|---:|---:|---:|---:|---:|
| unsupervised | 5 / 0.81% | 39 / 6.29% | 90 / 14.52% | 130 / 20.97% | 198 / 31.94% | 289 / 46.61% |
| timeseries | 0 / 0.00% | 0 / 0.00% | 8 / 1.29% | 8 / 1.29% | 8 / 1.29% | 8 / 1.29% |
| relational current native order | 5 / 0.81% | 19 / 3.06% | 19 / 3.06% | 22 / 3.55% | 27 / 4.35% | 35 / 5.65% |
| relational adopted audit_then_business | 51 / 8.23% | 92 / 14.84% | 141 / 22.74% | — | — | 172 / 27.74% |
| duplicate | 22 / 3.55% | 22 / 3.55% | 22 / 3.55% | 22 / 3.55% | 22 / 3.55% | 22 / 3.55% |
| intercompany | 34 / 5.48% | 34 / 5.48% | 34 / 5.48% | 34 / 5.48% | 34 / 5.48% | 34 / 5.48% |

`relational adopted audit_then_business`는 product default ordering이며, raw `evidence_tier` 전체 strong surface와 다르다. `intercompany`와 `relational`은 product ordering/policy가 잠긴 상태다. `unsupervised`는 `hybrid_with_soft_repeated_normal_guard`를 family list 기본 표시 ordering으로 사용한다. `timeseries`는 native ordering이 product/default이며, `ts_specific_top100_stabilized_surface`는 diagnostic candidate다. `duplicate`는 primary pair evidence path 개선이 계속 진행 중이다.

---

## 8. Relational native edge 진단

2026-05-28 relational diagnostic smoke는 `artifacts/phase2_relational_native_case_diagnostic_fixed5_20260528.json`에 aggregate-only로 기록한다. 출력은 sub_rule별 case_count, TOP100/TOP500 구성, row score hit와 case-grade artifact 사이의 gap reason만 포함하며 raw document identifier는 쓰지 않는다.

| 항목 | 값 | 해석 |
|---|---:|---|
| detector row score hit | 196,187 | relational row score는 충분히 많다. |
| edge artifact | 58,046 | row hit가 edge identity로 축약된다. |
| native case | 57,640 | strong edge 또는 moderate `positive_metric_count>=20 AND q95+` edge만 review candidate가 된다. |
| R05 case | 44,404 | rare account-partner edge가 case explosion의 1차 원인이다. |
| R06 case | 11,874 | user-account degree spike가 case explosion의 2차 원인이다. |
| TOP100 구성 | R03 72, R07 28 | 상단은 이전가격/휴면거래처 edge가 차지한다. |
| TOP500 구성 | R03 211, R05 45, R06 160, R07 84 | R05/R06은 전체 case 수 대비 상단 점유율이 낮다. |

row score hit가 있어도 case-grade artifact가 없는 원인은 rule별로 분리된다.

- `R01`: row hit 8,033개가 1,037개 edge로 축약되고, q95 gate 후 646개 case가 된다. `edge_gate_filtered_or_below_tail=800`.
- `R02`: row hit 120개가 20개 edge로 축약되고, q95 gate 후 5개 case가 된다. `edge_gate_filtered_or_below_tail=115`.
- `R03/R05/R06/R07`: strong edge 정책으로 edge artifact가 모두 case-grade review candidate가 된다. row hit without edge identity는 0이다.

판단:

1. 현재 edge identity `(edge_a, edge_b, sub_rule)`는 row score hit를 감사인이 확인 가능한 edge evidence unit으로 축약한다. fixed5에서 row hit without edge identity는 0이다.
2. case explosion은 artifact 생성 실패가 아니라 R05/R06 strong edge volume에서 온다.
3. R01/R02 moderate gate는 이제 실제로 작동한다. builder가 edge artifact의 positive `metric_value` 분포로 family-native ECDF를 계산하고, positive edge 표본이 20개 이상일 때만 q95+ moderate edge를 case-grade review candidate로 올린다. 소표본 engagement에서 단일 moderate edge가 자동 승격되는 것을 막기 위한 audit-defensible guard다.
4. TOP100/TOP500 recall이 낮은 이유는 case-grade artifact 부재보다 R05/R06 대량 edge와 lane 내부 sort placement다.
5. truth scenario를 보고 R-rule tier를 올리거나 내리지 않았다. PHASE1 score와 PHASE2 family fusion도 변경하지 않았다.

`evidence_signature` 는 계속 `sub_rule`, `edge_a`, `edge_b`만 사용하며 raw amount, score, threshold는 포함하지 않는다.

### 8.1 R05/R06 ranking candidate 비교

2026-05-29 relational 진단은 `artifacts/phase2_relational_native_case_diagnostic_fixed5_20260528.json`와 `artifacts/relational_ranking_candidates_fixed5_20260529.json`에 aggregate-only로 기록했다. 이 결과를 바탕으로 relational product default review surface를 `structural_moderate_audit_then_business_lane_split_surface` (`structural_moderate_audit_then_business_lane_split_v1`)로 고정했다. PHASE1 `priority_score` / `composite_sort_score` / ranking, PHASE2 family fusion, relational detector threshold/gate는 변경하지 않는다. truth label은 후보 정렬 뒤 aggregate 평가에만 사용하며, raw document id / raw row id / raw edge id는 출력하지 않는다.

R05/R06 decomposition:

| Rule | case_count | matched truth all cases | matched / 1000 cases | top subject share | top account share | rows_per_edge p95 | docs_per_edge p95 | high-volume nontruth share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| R05 | 44,404 | 126 | 2.84 | 0.12% | 1.50% | 2.0 | 2.0 | 32.52% |
| R06 | 11,874 | 70 | 5.90 | 1.89% | 1.36% | 42.0 | 24.0 | 9.90% |

해석:

- R05는 한두 edge가 반복 점유한다기보다 매우 넓은 rare account-partner edge surface가 case_count를 키운다. max cases per edge는 1이고 top edge share는 0.003% 미만이다.
- R06은 rows/documents per edge가 훨씬 크다. 사용자-계정 context는 한 evidence unit이 많은 rows/documents를 대표하므로 surface 표시에서 support/context 설명이 중요하다.
- case_count 전체로 보면 R05/R06가 각각 126건, 70건의 synthetic truth document를 포함하지만, matched / 1000 cases가 낮아 review burden이 크다.
- R01/R02 moderate gate는 `positive_metric_count >= 20 AND family_ecdf >= 0.95` 조건으로만 case-grade review candidate를 만든다. current artifact의 leak self-report는 두 diagnostic artifact 모두 `doc_like_token_count=0`, `forbidden_identifier_key_count=0`, `phase2_case_id_like_token_count=0`, `raw_edge_like_token_count=0`이다.

후보별 TOP surface 비교:

| Candidate | first truth rank | TOP100 | TOP500 | TOP1000 | TOP10000 | TOP500 R05/R06 share | TOP500 high-volume nontruth share |
|---|---:|---:|---:|---:|---:|---:|---:|
| current | 51 | 5 | 19 | 19 | 35 | 41.0% | 9.8% |
| edge_support_penalty | 876 | 0 | 0 | 1 | 16 | 67.2% | 100.0% |
| document_diversity_penalty | 30 | 4 | 8 | 9 | 24 | 65.4% | 98.4% |
| rare_edge_balanced_sampling_per_sub_rule | 7 | 6 | 27 | 57 | 179 | 39.6% | 10.8% |
| r03_r07_priority_first_surface | 51 | 5 | 33 | 35 | 50 | 0.0% | 10.0% |
| r05_r06_volume_capped_by_edge_support | 51 | 5 | 19 | 19 | 35 | 41.0% | 9.8% |
| moderate_tail_only_surface_q95 | 2 | 8 | 98 | 143 | 157 | 0.0% | 9.4% |
| moderate_tail_only_surface_q99 | 2 | 8 | 98 | 143 | 157 | 0.0% | 9.4% |
| sub_rule_balanced_review_surface | 32 | 3 | 19 | 36 | 60 | 50.0% | 10.0% |
| edge_novelty_with_tier_guard | 51 | 5 | 19 | 19 | 35 | 41.0% | 9.8% |
| account_partner_context_surface | 16 | 2 | 12 | 12 | 37 | 57.8% | 9.8% |
| structural_moderate_tail_lane_split_surface | 4 | 7 | 41 | 131 | 172 | 0.0% | 10.4% |
| three_lane_structural_moderate_context_surface | 4 | 6 | 38 | 65 | 172 | 20.0% | 11.4% |
| structural_moderate_business_balanced_lane_split_surface | 10 | 12 | 92 | 141 | 172 | 0.0% | 10.2% |
| structural_moderate_audit_then_business_lane_split_surface | 2 | 51 | 92 | 141 | 172 | 0.0% | 10.2% |
| structural_moderate_capped_context_lane_split_surface | 2 | 51 | 92 | 141 | 172 | 0.0% | 10.2% |
| structural_anchor_moderate_1_to_4_surface | 2 | 59 | 100 | 141 | 172 | 0.0% | 10.0% |

PHASE1 incremental coverage 진단:

PHASE1 baseline은 PHASE1 detector flagged row가 참조한 `document_id` aggregate로 만들었다. TOP-N baseline은 PHASE1 detector score를 read-only proxy로 정렬해 만든 진단용 set이며, PHASE1 `priority_score`, `composite_sort_score`, ranking은 변경하지 않았다. raw document id는 artifact에 저장하지 않는다.

| Baseline | review docs | matched truth docs |
|---|---:|---:|
| PHASE1 all flagged docs | 124,710 | 620 |
| PHASE1 TOP100 score-proxy docs | 65 | 3 |
| PHASE1 TOP500 score-proxy docs | 325 | 15 |
| PHASE1 TOP1000 score-proxy docs | 639 | 41 |
| PHASE1 TOP10000 score-proxy docs | 5,463 | 429 |

Relational surface의 standalone TOP-N recall, PHASE1 broad inclusion, PHASE1 TOP-N uplift, relational evidence incremental은 분리해서 해석한다. PHASE1 all flagged document set의 620/620은 broad review universe 안에 truth document가 들어 있다는 뜻일 뿐, PHASE1이 relationship evidence나 scenario explanation을 직접 제공했다는 뜻이 아니다.

| Surface | TOP500 matched | PHASE2 TOP500 truth not in PHASE1 TOP500 | net uplift vs PHASE1 TOP500 | structural evidence truth docs | moderate-tail evidence truth docs | role interpretation |
|---|---:|---:|---:|---:|---:|---|
| current | 19 | 19 | 4 | 17 | 0 | weak uplift, structural reinforcement |
| R03/R07 structural-only | 33 | 33 | 18 | 33 | 0 | structural evidence companion |
| R01/R02 moderate-tail | 98 | 95 | 83 | 0 | 98 | strong TOP-N uplift, high moderate concentration |
| R05/R06 context lane | 2 | 2 | -13 | 0 | 0 | context-only lane has low TOP500 value |
| structural_moderate_audit_then_business_lane_split_surface | 92 | 89 | 77 | 16 | 76 | TOP-N uplift + structural/moderate evidence companion |
| structural_anchor_moderate_1_to_4_surface | 100 | 97 | 85 | 5 | 95 | diagnostic upper-bound only |

Decision payload는 `document_inclusion_incremental_value=broad_inclusion_only_not_decision_basis`, `topn_uplift_value=high`, `evidence_incremental_value=high`, `explanation_incremental_value=high`, `primary_product_role=relationship_evidence_review_surface`, `primary_denominator_status=pending_relationship_primary_metadata`, `recommended_default_surface_if_datasynth_incomplete=structural_moderate_audit_then_business_lane_split_surface`, `adopted_default_allowed=true`로 기록한다. 이 판단은 "blind spot 대량 발굴"이나 relational primary recall 개선이 아니라 `audit_then_business`가 relationship review surface를 유지하면서 R03/R07 structural evidence와 R01/R02 moderate relationship evidence를 노출한다는 진단 결과다. `1:4 anchor`는 TOP500 100으로 더 높지만 fixed5 metric-selection smell이 있어 diagnostic upper-bound로만 남긴다.

판단:

1. `edge_support_penalty`와 `document_diversity_penalty`는 단순 패널티가 R05 single/low-support edge를 과도하게 올려 high-volume nontruth proxy가 급등한다. 감사적으로 방어 가능한 surface 축소 후보로 부적합하다.
2. `rare_edge_balanced_sampling_per_sub_rule`은 TOP1000/TOP10000 coverage가 넓지만 R01/R02를 동일 슬롯으로 올린다. production ranking이 아니라 exploratory diagnostic surface 후보로만 적합하다.
3. `r03_r07_priority_first_surface`는 current 상단의 강한 구조 신호를 유지하면서 TOP500 matched가 19에서 33으로 증가한다. 다만 R05/R06 coverage를 상단에서 거의 제거하므로 account-partner/user-account review surface와 분리 운영할 semantic 검증이 필요하다.
4. `moderate_tail_only_surface_q95/q99`는 fixed5에서 TOP500 matched가 98까지 증가하지만 R01/R02 moderate edge가 상단을 사실상 독점한다. q95와 q99 결과가 거의 동일해 tail cutoff 자체보다 current moderate candidate pool의 정렬/표본 구조를 추가 분해해야 한다. q95 tail 651개 중 TOP500은 R01 496, R02 4이고, TOP500 review burden은 truth-case 48개 대비 nontruth-case 452개다.
5. `structural_moderate_tail_lane_split_surface`는 R03/R07 strong structural lane과 R01/R02 moderate tail lane을 1:1로 섞는 diagnostic surface다. TOP500 matched는 current 19에서 41로 증가하고, moderate-only의 R01/R02 독점은 TOP500 기준 R01 249, R02 1로 낮아진다. TOP1000은 131로 moderate-only 143보다 낮지만, review burden과 structural signal 보존 사이 tradeoff가 더 설명 가능하다.
6. `structural_moderate_business_balanced_lane_split_surface`는 R03/R07 strong lane을 유지하면서 R01/R02 moderate tail을 `business_process` bucket별 round-robin으로 노출한다. fixed5 TOP500 matched는 current 19에서 92로 증가하고, TOP500 구성은 R01 247, R02 3, R03 181, R07 69다.
7. `structural_moderate_audit_then_business_lane_split_surface`는 product default review surface다. 상단 prefix는 audit-context bucket(`new_counterparty_age`, `dormant_gap`, account class, document burden)으로 균형화하고, 이후는 business 균형으로 전환한다. fixed5에서 TOP100은 12 → 51로 개선되고 TOP500/TOP1000은 business-balanced와 같은 92/141을 유지한다. 1:1 lane split은 recall maximization이 아니라 audit review surface policy다.
8. `structural_anchor_moderate_1_to_4_surface`는 R03/R07 structural evidence를 TOP500의 약 20% 수준으로 anchor로 남기고 R01/R02 moderate audit/business tail 노출을 늘린다. fixed5 TOP500은 92 → 100, fixed4 TOP500은 89 → 105로 증가했다. TOP500 구성은 fixed5 기준 R01 395, R02 5, R03 72, R07 28이다. fixed5/fixed4 공통으로 가장 높은 diagnostic surface지만, structural 비중이 줄어드는 semantic tradeoff가 있다.
9. `structural_moderate_capped_context_lane_split_surface`는 business/process bucket과 document_count bucket에 review burden cap을 추가한 stress-test 후보이며, fixed5/fixed4에서 audit-then-business 후보와 동일한 TOP-N 결과를 냈다. 이는 현재 후보가 cap 안에서 이미 동작한다는 안정성 근거이지 추가 성능 개선은 아니다.
10. `three_lane_structural_moderate_context_surface`는 R03/R07, R01/R02 moderate tail, R05/R06 context를 2:2:1로 섞는다. TOP500 matched는 38이고 R05/R06 share는 20.0%다. R05/R06 context를 살리지만 TOP1000 coverage는 65로 lane split보다 낮다.
11. `account_partner_context_surface`는 partner-account와 user-account context를 분리 비교하기 위한 후보지만 current 대비 TOP500 matched가 낮고 R05/R06 share가 커진다.
12. 위 비교는 recall 최적화가 아니라 R05/R06 대량 edge의 상단 점유, R01/R02 moderate tail의 review burden, R03/R07 strong structural signal의 surface placement를 감사인이 해석 가능한 evidence unit 기준으로 비교한 결과다. Product default는 1:1 audit-then-business surface이고, 1:4 anchor는 diagnostic-only upper-bound다.

Fixed4 cross-batch aggregate snapshot:

| Candidate | TOP100 | TOP500 | TOP1000 | TOP500 sub_rule 구성 |
|---|---:|---:|---:|---|
| current | 6 | 17 | 17 | R03 310, R06 105, R07 85 |
| r03_r07_priority_first_surface | 6 | 17 | 33 | R03 332, R07 168 |
| moderate_tail_only_surface_q95 | 18 | 107 | 140 | R01 496, R02 4 |
| structural_moderate_tail_lane_split_surface | 11 | 42 | 124 | R01 248, R02 2, R03 197, R07 53 |
| three_lane_structural_moderate_context_surface | 10 | 40 | 116 | R01 198, R02 2, R03 157, R06 100, R07 43 |
| structural_moderate_business_balanced_lane_split_surface | 17 | 90 | 124 | R01 247, R02 3, R03 197, R07 53 |
| structural_moderate_audit_then_business_lane_split_surface | 51 | 89 | 124 | R01 245, R02 5, R03 197, R07 53 |
| structural_moderate_capped_context_lane_split_surface | 51 | 89 | 124 | R01 245, R02 5, R03 197, R07 53 |
| structural_anchor_moderate_1_to_4_surface | 58 | 105 | 140 | R01 395, R02 5, R03 78, R07 22 |

Fixed4에서도 moderate-only와 structural/moderate business-balanced lane split의 방향성은 유지된다. moderate-only는 여전히 R01/R02가 TOP500을 거의 독점한다. audit-then-business lane split은 R03/R07 structural evidence를 TOP500에 보존하면서 current 대비 TOP100을 6 → 51, TOP500을 17 → 89로 올린다. 이 결과는 R01/R02 moderate tail을 audit/business context로 균형 노출하는 product review surface의 cross-batch sanity check로 해석한다.

연도 split validation:

| Dataset | Year | current TOP100 | candidate TOP100 | current TOP500 | candidate TOP500 |
|---|---:|---:|---:|---:|---:|
| fixed5 | 2022 | 2 | 52 | 2 | 80 |
| fixed5 | 2023 | 2 | 20 | 3 | 29 |
| fixed5 | 2024 | 8 | 18 | 11 | 31 |
| fixed4 | 2022 | 2 | 51 | 2 | 79 |
| fixed4 | 2023 | 2 | 20 | 2 | 29 |
| fixed4 | 2024 | 6 | 16 | 8 | 29 |

`structural_moderate_audit_then_business_lane_split_surface`는 fixed5/fixed4 전체뿐 아니라 연도별 split에서도 TOP100과 TOP500이 current 이상이다. Product default case ordering에는 적용하지만, threshold/gate/fusion 정책은 승격하지 않는다.

Review burden cap stress test:

- `max_per_business_process=90`, `max_per_document_bucket=220` cap을 R01/R02 moderate tail에 적용해도 fixed5/fixed4 TOP-N은 audit-then-business 후보와 동일했다.
- fixed5 capped TOP100/TOP500/TOP1000: 51 / 92 / 141.
- fixed4 capped TOP100/TOP500/TOP1000: 51 / 89 / 124.
- 따라서 현재 iteration에서는 cap 기반 추가 개선은 없고, 기존 후보가 cap 제약 안에서 안정적이라는 근거만 추가한다.

Structural anchor ratio stress:

- 1:2 and 1:3 structural-anchor variants improved over strict 1:1 lane split.
- 1:4 reached fixed5 TOP100/TOP500/TOP1000 = 59 / 100 / 141 and fixed4 = 58 / 105 / 140.
- R03/R07 remains present in TOP500, but drops to about 20% of the surface. This is the current highest diagnostic result, with a clear semantic tradeoff.
- 1:4 is not adopted as product default because the ratio has fixed5 metric-selection smell and weakens the structural lane share.

No-fitting contract:

- `truth_label_used_for_scoring=false`
- `truth_label_used_only_for_aggregate_evaluation=true`
- `production_ranking_changed=false`
- `threshold_changed=false`
- `phase1_ranking_changed=false`
- `phase2_fusion_changed=false`
- `relational_case_gate_changed=false`

다음 검증 필요:

1. `moderate_tail_only_surface_q95/q99`가 fixed5에서 좋아지는 이유를 R01/R02별 row/document concentration, scenario mix, business context로 분해한다.
2. R03/R07 priority-first와 R05/R06 context surface를 하나의 ranking으로 섞지 않고 lane split로 비교한다.
3. fixed4/fixed5 연도 split 외 추가 fixture 또는 운영형 synthetic sample에서 `structural_moderate_audit_then_business_lane_split_surface` 방향성이 유지되는지 검증한다.
4. R05/R06는 raw edge value 없이 account/partner/user context bucket 수준의 audit-observable feature를 추가 정의한다.

---

## 9. Intercompany native case 회귀 가드

2026-05-28 IC 점검 결과, 현 구현은 `reciprocal_flow` 와 `amount_mismatch` 만 native pair review candidate 로 생성한다. `unmatched_rows` 와 timing-only candidate 는 weak signal 로 남기며 case 생성 대상에서 제외한다. 이 정책은 recall 목적의 승격이 아니라 감사인이 확인 가능한 pair evidence unit 기준을 유지하기 위한 것이다.

회귀 가드는 다음 계약을 잠근다.

- reciprocal pair case 는 receivable/payable 양쪽 row_ref 를 모두 포함한다.
- amount mismatch pair case 는 `amount_a`, `amount_b`, `amount_symmetry` 를 evidence payload 로 보존한다.
- MultiIndex 입력에서는 artifact 의 문자열화된 label 이 아니라 `df.index[position]` 을 canonical identity 로 사용한다.
- fixed5 aggregate smoke 는 intercompany native `case_count=246`, TOP100 circular coverage `34/34` 를 확인한다.

`evidence_signature` 는 계속 `ic_role` 만 사용하며 raw amount, score, threshold 는 포함하지 않는다.

---

## 9.1 Intercompany incremental value 진단

2026-05-29 IC 전용 incremental 진단은 `artifacts/intercompany_incremental_value_fixed5_20260529.json`에 aggregate-only로 기록한다. 이 산출물은 production gate/ranking/fusion을 바꾸지 않는 diagnostic-only 측정이다. PHASE1 `priority_score`, `composite_sort_score`, ranking은 변경하지 않았고, truth/scenario label은 IC native case ordering 이후 aggregate evaluation에만 사용했다. raw document id, row id, phase2 case id, counterparty raw id는 출력하지 않는다.

측정 기준은 기존 broad inclusion 해석과 분리했다.

| 항목 | 값 | 해석 |
|---|---:|---|
| PHASE1 all truth document coverage | 544 / 620 | PHASE1 broad review universe 기준 포함률이다. 이것만으로 IC value를 낮게 평가하지 않는다. |
| PHASE1 TOP100 truth coverage | 0 | PHASE1 상단에는 circular IC truth가 올라오지 않았다. |
| PHASE1 TOP500 truth coverage | 50 | PHASE1 전체 TOP500 truth count는 IC 단독 34보다 많지만 scenario/evidence 성격이 다르다. |
| PHASE1 TOP1000 truth coverage | 87 | broad generic review ordering과 IC evidence lane은 역할이 다르다. |
| IC TOP100 truth not in PHASE1 TOP100 | 34 | IC native surface가 PHASE1 TOP100 밖 circular truth를 TOP100 안으로 올린다. |
| IC TOP500 truth not in PHASE1 TOP500 | 34 | IC TOP500 34건은 PHASE1 TOP500에 없던 circular truth다. |
| IC TOP1000 truth not in PHASE1 TOP1000 | 32 | TOP1000 기준 32건이 PHASE1 상단 밖에서 올라온다. |
| net uplift vs PHASE1 TOP100 / TOP500 / TOP1000 | +34 / -16 / -53 | IC는 전체 truth recall을 넓히는 broad lane이 아니라 circular IC evidence-specialized lane이다. |

IC evidence incremental:

| Metric | TOP100 | TOP500 | TOP1000 |
|---|---:|---:|---:|
| ic_evidence_added_truth_docs | 34 | 34 | 34 |
| ic_evidence_added_case_count | 34 | 34 | 34 |
| reciprocal_flow_evidence_added_truth_docs | 34 | 34 | 34 |
| amount_mismatch_evidence_added_truth_docs | 0 | 0 | 0 |
| paired_row_ref_truth_docs | 34 | 34 | 34 |
| counterparty_pair_truth_docs | 34 | 34 | 34 |
| amount_symmetry_truth_docs | 34 | 34 | 34 |
| phase2_specific_ic_reason_truth_docs | 34 | 34 | 34 |
| phase1_only_generic_reason_truth_docs | 0 | 50 | 85 |

설명 gap:

- IC TOP100/TOP500은 모두 `circular_related_party_transaction` 34건이다.
- PHASE1 all에는 IC truth 34건 중 33건이 IC/related-party 설명 범주를 일부 보유하고, 1건은 generic/amount/date 성격으로 분류된다.
- IC native case는 같은 document가 PHASE1 broad universe에 이미 있더라도 receivable/payable paired row_refs, counterparty pair, amount symmetry, reciprocal flow evidence를 감사인이 확인 가능한 별도 evidence unit으로 제공한다.
- 따라서 IC는 standalone recall만 좋은 lane이 아니라, PHASE1 generic review reason을 IC-specific reciprocal evidence로 보강하는 lane이다.

Decision payload:

| Field | Value |
|---|---|
| document_inclusion_incremental_value | reported_separately_not_decision_basis |
| topn_uplift_value | medium |
| evidence_incremental_value | high |
| explanation_incremental_value | high |
| primary_product_role | ic_specific_evidence_strengthening |
| adopted_default_allowed | false |
| production_ranking_changed | false |
| new_policy_adopted | false |

판단: IC의 primary role은 `ic_specific_evidence_strengthening`이다. TOP100 uplift는 강하지만 TOP500/TOP1000의 net truth uplift는 PHASE1 전체 TOP-N보다 낮으므로, broad recall expansion family로 해석하지 않는다. `adopted_default_allowed=false`, `production_ranking_changed=false`, `new_policy_adopted=false`는 새 ranking/gate 정책을 도입하지 않았다는 뜻이며 IC family 비활성화를 뜻하지 않는다. 기존 native success lock(`case_count=246`, TOP100 circular 34, circular scenario 34/34 coverage)은 유지한다.

Streamlit/dashboard 연결은 새 UI가 아니라 기존 PHASE2 native case surface를 사용한다. `run_phase2_inference`는 `PipelineResult.phase2_case_set`에 `IntercompanyCase`를 포함하고, dashboard는 기존 `phase2_native_case_panel`과 native case metrics helper에서 이 case_set을 읽는다. 추가로 `PipelineResult.phase2_family_policy_summary["intercompany"]`는 aggregate-only role metadata(`primary_product_role=ic_specific_evidence_strengthening`, `production_ranking_changed=false`, `new_policy_adopted=false`)를 optional로 보관한다. 이 metadata는 표시/문맥용이며 detector scoring, PHASE1 ranking, PHASE2 fusion에는 사용하지 않는다.

---

## 10. Family별 분산 지표

| Family | TOP500 matched | 잡은 유형 수 | 1위 유형 비중 | HHI | 유효 유형 수 | 해석 |
|---|---:|---:|---:|---:|---:|---|
| `unsupervised` | 39 | 3 | 51.3% | 0.456 | 2.19 | expense/fictitious 중심의 row anomaly lane |
| `timeseries` | 0 | 0 | 0.0% | 0.000 | 0.00 | native window는 생성되지만 TOP500 truth coverage 없음 |
| `relational` | 19 | 3 | 47.4% | 0.413 | 2.42 | circular/embezzlement 중심의 구조 edge lane |
| `duplicate` | 22 | 1 | 100.0% | 1.000 | 1.00 | period-end truth를 포함한 exact pair evidence lane |
| `intercompany` | 34 | 1 | 100.0% | 1.000 | 1.00 | circular 전용에 가까운 reconciliation pair lane |

`유효 유형 수`는 scenario 비중의 HHI 역수 기준이다. 값이 클수록 한 유형에 덜 쏠린다.

---

## 11. Legacy overlay 수치와의 차이

2026-05-26 문서의 기존 수치는 `PHASE1 case`를 family score로 정렬한 값이었다. 즉, PHASE2가 독립적으로 만든 pair / edge / row / window case가 아니라 PHASE1 case 위에 family signal을 overlay한 결과였다.

이번 native case 재측정에서 수치가 크게 낮아진 이유는 다음과 같다.

1. native case는 family artifact가 실제 evidence 단위로 존재해야 생성된다.
2. row score hit가 많아도 case-grade artifact가 없으면 native case 수는 0일 수 있다.
3. TOP-N의 N은 PHASE1 case 수가 아니라 PHASE2 native evidence unit 수다.
4. duplicate처럼 row score와 pair artifact가 분리된 family는 legacy score lane과 native evidence lane 결과가 크게 달라질 수 있다.

따라서 과거 overlay 수치와 본 native 수치는 서로 다른 질문에 답한다.

- Legacy overlay: "PHASE1 case를 family score로 다시 보면 truth document가 얼마나 들어오는가?"
- Native case: "PHASE2가 감사인이 확인 가능한 evidence unit으로 만든 case 안에 truth document가 얼마나 들어오는가?"

보존용 legacy baseline (5 active family 전체):

아래 수치는 `artifacts/stage7_fixed5_current_family_review_20260525_report.json`의
`family_single_current.*.phase2` 값이며, 당시 active family 5개
(`unsupervised`, `timeseries`, `relational`, `duplicate`, `intercompany`)를 모두 포함한다.
PHASE1 case-level / document-level family score overlay 기준이므로 native case recall과 직접 비교하지
않는다. 단, native case 전환 전 포트폴리오 기준선이 사라지지 않도록 아카이브한다.

| Family | TOP100 | TOP500 | TOP1000 | TOP2000 | TOP5000 | TOP10000 |
|---|---:|---:|---:|---:|---:|---:|
| unsupervised | 79 / 12.74% | 216 / 34.84% | 295 / 47.58% | 363 / 58.55% | 455 / 73.39% | 507 / 81.77% |
| timeseries | 12 / 1.94% | 53 / 8.55% | 53 / 8.55% | 397 / 64.03% | 468 / 75.48% | 509 / 82.10% |
| relational | 24 / 3.87% | 289 / 46.61% | 295 / 47.58% | 298 / 48.06% | 334 / 53.87% | 514 / 82.90% |
| duplicate | 221 / 35.65% | 255 / 41.13% | 273 / 44.03% | 277 / 44.68% | 294 / 47.42% | 386 / 62.26% |
| intercompany | 26 / 4.19% | 60 / 9.68% | 136 / 21.94% | 417 / 67.26% | 487 / 78.55% | 525 / 84.68% |

이 표는 "기존 PHASE2 family score가 PHASE1 case/doc overlay 위에서 보였던 ranking recall"을 보존한다.
현재 native case 표는 "family가 독립 evidence unit을 실제 생성했을 때의 recall"이므로, 두 표의 차이는
성능 회귀만이 아니라 측정 단위 변경 효과를 포함한다.

---

## 12. Timeseries native window 진단

2026-05-29 재측정 스크립트는 `family_diagnostics.timeseries`를 baseline-aware 진단으로 확장했다. 이 값은 TS lane의 TOP-N 낮은 이유를 artifact 생성 부족, baseline 산출 여부, period-end context, ranking placement로 분리하기 위한 진단이다. TS lane은 계속 primary detector가 아니라 결산·시점 timing context lane이며, 결과는 review candidate evidence unit으로 해석한다.

| 항목 | 값 | 해석 |
|---|---:|---|
| raw flagged row | 40,257 | detector row score hit는 충분히 존재한다. |
| artifact window | 1,000 | artifact cap 기준으로 TS01 500, TS02 500이 생성된다. |
| native case | 861 | `sub_signal_high=True` gate 통과 window만 review candidate case가 된다. |
| builder excluded window | 139 | 전부 `sub_signal_high=False`이며 case-grade evidence unit에서 제외된다. |
| expected_count state | `provided=999`, `none=1` | 대부분 subject trailing baseline 산출 가능. baseline 부족 시 `None` 유지. |
| expected_count None ratio | window 0.10%, case 0.12% | 0.0 fallback 없이 baseline unavailable을 분리한다. |
| first truth-covering case rank | 762 | TOP100/500 낮은 주원인은 artifact 부재가 아니라 ranking placement다. |
| truth rank buckets | TOP100 0, TOP500 0, TOP1000 1 | truth-covering TS case는 TOP1000 구간에만 1건 존재한다. |

분포:

- `TS01`: artifact window 500개, native case 361개. 모두 `single_day` window다.
- `TS02`: artifact window 500개, native case 500개. 모두 `trailing_window` window다.
- subject 상위는 `1100.0`, `100230.0`, `100120.0` 등 계정/프로세스 단위로 분산된다.
- baseline 산출 가능 window는 999개, native case는 860개다.

truth-covering TS case context:

| rank | rule | window kind | subject | count | expected | robust_z | period_end_lift | context_evidence_count | period_end_context | top500 miss reason |
|---:|---|---|---|---:|---:|---:|---:|---:|---|---|
| 762 | TS01 | single_day | `15110.0` | 11 | 3.0 | 2.70 | 5.50 | 4 | true | `period_end_normalized_downrank` |

TOP500 period-end context case와의 비교:

| 비교 항목 | TOP500 period-end case | truth-covering TS case | 해석 |
|---|---:|---:|---|
| period_end_context case 수 | 119 | 1 | TOP500 안에도 결산 시점 후보가 충분히 존재한다. |
| robust_z p50 / truth | 0.06 | 2.70 | truth case의 robust_z는 TOP500 period-end 중앙값보다 높다. |
| period_end_lift p50 / truth | 6.00 | 5.50 | truth case의 period-end lift는 TOP500 period-end 중앙값보다 낮다. |
| context_evidence_count p50 / truth | 2.00 | 4 | truth case의 보조 context evidence는 부족하지 않다. |
| subject_activity_rank p50 / truth | 63 | 119 | rank 값은 낮을수록 더 활동이 많은 subject다. truth subject는 TOP500 period-end 중앙값보다 활동 배경이 약하다. |
| lower-rank reason | — | `mixed_period_end_context` | period_end_lift는 상단 중앙값보다 낮지만 robust_z/context evidence는 강한 엇갈린 신호다. |

판단:

1. TS lane은 row-level signal이 없어서 실패한 것이 아니다. 40,257개 flagged row가 1,000개 window artifact로 축약되고, 그중 861개가 case-grade review candidate가 된다.
2. TOP100/TOP500 recall 0의 직접 원인은 `sub_signal_high` gate 부족이 아니라 ranking placement다. 첫 truth-covering native case는 762위에 위치한다.
3. TS01 single-day burst와 TS02 trailing window는 감사적으로 해석 가능한 evidence unit이다. 이제 `expected_count`, `baseline_method`, `baseline_window_days`, `baseline_observation_count`, `robust_z`, `period_end_context`, `subject_activity_rank`가 함께 제공된다.
4. truth-covering TS case는 baseline 대비 증가(`daily_count=11`, `expected_count=3.0`, `robust_z=2.70`)가 있으나 period-end context가 true인 결산 시점 후보라 TOP500 안으로 들어오지 않았다. 이는 threshold 튜닝 문제가 아니라 timing context lane의 정상 결산 spike와 unusual spike 분리 한계로 해석한다.
5. TOP500 truth miss reason은 truth-covering case 기준으로만 `top500_truth_miss_reasons.period_end_normalized_downrank=1`에 기록된다. 전체 window gate 제외 사유는 별도 필드 `builder_excluded_window_reasons.sub_signal_high_false=139`에만 기록한다. 이 139개 window를 truth-covering miss로 해석하지 않는다.
6. period-end disambiguation feature 진단 결과, truth case는 `context_evidence_count=4`로 보조 context가 부족하지 않고 `robust_z=2.70`도 TOP500 period-end 중앙값보다 높다. 다만 `period_end_lift=5.50`은 TOP500 period-end 중앙값 6.00보다 낮다. 따라서 정상 결산 spike로 단정하지 않고 `mixed_period_end_context`로 분류한다. 이 결과는 period-end lift와 보조 context를 결합한 ranker 후보를 추가 batch/fixture에서 비교해야 함을 뜻하며, 지금 바로 ranker를 바꾸기에는 아직 근거가 부족하다.

baseline 정책:

- TS01 single-day는 같은 subject의 과거 active day daily count median을 baseline으로 둔다.
- TS02 trailing window는 같은 subject의 과거 trailing window count median을 baseline으로 둔다.
- 최소 관측 수가 부족하면 `expected_count=None`, `baseline_method=None`, `robust_z=None`으로 유지한다. 0.0 fallback은 사용하지 않는다.
- `period_end_context`는 정상 결산 spike와 unusual spike를 분리해 설명하기 위한 별도 context flag다. 현재 Phase 1에서는 ranking 결합에 사용하지 않는다.
- Phase 2 period-end disambiguation context는 `period_end_day_offset`, `subject_period_end_historical_ratio`, `subject_non_period_end_baseline_count`, `period_end_expected_count`, `period_end_lift`, `amount_tail_context`, `manual_or_adjustment_context`, `after_hours_or_weekend_context`, `round_amount_context`, `rarity_context_count`, `context_evidence_count`를 artifact와 native case detail에 보존한다. 현재 단계에서는 ranking 결합에 사용하지 않는다.
- `subject_activity_rank`는 값이 낮을수록 전체 population에서 더 활동이 많은 subject라는 뜻이다. 이 방향성은 `subject_activity_rank_distribution` 해석 시 함께 확인한다.

Phase 3 diagnostic-only ranker 후보 비교:

`artifacts/timeseries_ranking_candidates_fixed5_20260529.json`은 제품 TS ordering을 변경하지 않고 후보 점수만 사후 비교한다. truth label은 detector/ranker 입력으로 사용하지 않고, aggregate 평가에만 사용한다. 후보 가중치는 `fixed5 exploratory diagnostic weights`이며 `not calibrated`, `not production ranking policy` 상태다. 제품 반영 전에는 cross-batch/fixture validation이 필요하다.

| 후보 | TOP100 | TOP500 | TOP1000 | TOP10000 | first truth rank | FP pressure proxy | TOP500 TS01/TS02 | current 대비 신규 TOP500 |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| current native TS ordering | 0 | 0 | 8 | 8 | 762 | 0.0860 | 75 / 425 | 0 |
| robust_z + context_evidence_count | 0 | 8 | 8 | 8 | 300 | 0.0331 | 259 / 241 | 229 |
| period_end_lift + robust_z balanced | 0 | 8 | 8 | 8 | 359 | 0.0358 | 226 / 274 | 199 |
| period_end-normalized mixed signal | 0 | 8 | 8 | 8 | 328 | 0.0358 | 243 / 257 | 213 |
| subject_activity_rank adjusted | 0 | 8 | 8 | 8 | 323 | 0.0304 | 254 / 246 | 223 |
| robust_context_baseline_sufficiency | 0 | 8 | 8 | 8 | 295 | 0.0331 | 260 / 240 | 230 |
| mixed_signal_period_end_demoted | 0 | 8 | 8 | 8 | 381 | 0.0137 | 260 / 240 | 229 |
| non_period_end_surprise_priority | 0 | 8 | 8 | 8 | 445 | 0.0133 | 251 / 249 | 219 |
| ts01_ts02_balanced_surface | 0 | 8 | 8 | 8 | 335 | 0.0332 | 250 / 250 | 221 |
| review_burden_penalized_context | 8 | 8 | 8 | 8 | 76 | 0.0338 | 291 / 209 | 250 |
| review_burden_closing_demoted_context | 8 | 8 | 8 | 8 | 98 | 0.0233 | 286 / 214 | 248 |

TOP500 context 비교:

| 후보 | period_end true | mixed period-end | normal closing proxy | subject top1 share | baseline sufficient ratio |
|---|---:|---:|---:|---:|---:|
| current native TS ordering | 119 | 14 | 91 | 2.2% | 99.6% |
| robust_context_baseline_sufficiency | 41 | 32 | 31 | 1.6% | 98.6% |
| mixed_signal_period_end_demoted | 19 | 14 | 9 | 1.6% | 98.4% |
| non_period_end_surprise_priority | 11 | 9 | 9 | 1.6% | 98.6% |
| ts01_ts02_balanced_surface | 41 | 33 | 32 | 1.6% | 99.0% |
| review_burden_penalized_context | 40 | 30 | 28 | 1.2% | 96.6% |
| review_burden_closing_demoted_context | 25 | 25 | 16 | 1.2% | 96.6% |

판단:

- `review_burden_penalized_context`는 fixed5에서 TOP100 8건, first truth rank 76을 만든 유일한 후보다. 반복 subject/window_kind 과점을 낮추는 audit-observable penalty가 placement 병목을 크게 완화했다.
- `review_burden_closing_demoted_context`는 TOP100 8건을 유지하면서 false-positive pressure proxy를 0.0338에서 0.0233으로 낮춘다. first truth rank는 76에서 98로 늦어지지만 여전히 TOP100 안이다.
- 이 개선은 truth label을 점수 입력으로 쓰지 않은 사후 diagnostic 결과다. artifact는 `truth_label_used_for_scoring=false`, `truth_label_used_only_for_aggregate_evaluation=true`, `production_ranking_changed=false`, `threshold_changed=false`, `phase1_ranking_changed=false`, `phase2_fusion_changed=false`를 후보별로 기록한다.
- raw identifier leak self-report는 `doc_like_token_count=0`, `forbidden_identifier_key_count=0`, `phase2_case_id_like_token_count=0`이다.
- `mixed_signal_period_end_demoted`와 `non_period_end_surprise_priority`는 false-positive pressure proxy를 가장 낮추지만 first truth rank는 각각 381, 445로 밀린다. 정상 결산 spike를 강하게 낮추면 review burden은 줄지만 placement 개선폭은 작아진다.
- `ts01_ts02_balanced_surface`는 TS01/TS02를 250/250으로 맞춘 diagnostic-only 비교다. quota 방식은 production ranking policy가 아니며, 과점 원인 분석용으로만 본다.
- 현재 iteration 결과는 `review_burden_penalized_context`를 production adoption candidate로 보게 하지만, fixed5 단일 batch만으로는 제품 반영 근거가 부족하다. 다음 검증 필요 항목은 다른 fixed batch/fixture에서 subject repetition penalty가 정상 반복 결산 문서를 과소/과대 노출하지 않는지 확인하는 것이다.

Cross-batch diagnostic:

`artifacts/timeseries_ranking_crossbatch_20260529.json`은 fixed3, fixed4, fixed5_normalcal5에 같은 후보를 적용한 diagnostic-only 산출물이다.

| batch | current TOP100/TOP500 | review_burden_closing_demoted TOP100/TOP500 | first rank current → candidate | primary gap |
|---|---:|---:|---:|---|
| fixed3 | 0 / 0 | 0 / 0 | — → — | artifact truth coverage gap |
| fixed4 | 0 / 0 | 0 / 0 | — → — | artifact truth coverage gap |
| fixed5_normalcal5 | 0 / 0 | 8 / 8 | 762 → 98 | ranking gap |

Truth coverage flow:

| batch | flagged truth docs | artifact window truth docs | native case truth docs | ranking can improve |
|---|---:|---:|---:|---|
| fixed3 | 13 | 0 | 0 | false |
| fixed4 | 13 | 0 | 0 | false |
| fixed5_normalcal5 | 13 | 8 | 8 | true |

해석:

- fixed3/fixed4에서는 TS detector row flag 단계에는 truth document 13건이 있지만 artifact window/native case에 남지 않는다. 따라서 ranking 후보만으로는 TOP-N coverage를 개선할 수 없다.
- fixed5에서는 native case가 truth document 8건을 포함하므로 ranking placement 개선 여지가 있고, `review_burden_closing_demoted_context`가 TOP100/TOP500 8건을 유지한다.
- cross-batch raw leak self-report도 `doc_like_token_count=0`, `forbidden_identifier_key_count=0`, `phase2_case_id_like_token_count=0`이다.
- production 적용은 계속 보류한다. fixed3/fixed4의 병목은 artifact retention/generation 쪽이며, 이 축은 detector threshold나 native case gate 변경 없이 설명 가능한 진단 feature를 추가로 봐야 한다.

Artifact retention diagnostic:

| batch | TS01 candidate windows | TS01 truth candidate windows | current cap500 truth windows | score-desc cap500 truth windows | period-end+score cap500 truth windows |
|---|---:|---:|---:|---:|---:|
| fixed3 | 4,761 | 3 | 0 | 3 | 3 |
| fixed4 | 4,761 | 3 | 0 | 3 | 3 |
| fixed5_normalcal5 | 1,593 | 3 | 1 | 0 | 3 |

Unique truth document count under the same retention surfaces:

| batch | current cap500 truth docs | score-desc cap500 truth docs | period-end+score cap500 truth docs |
|---|---:|---:|---:|
| fixed3 | 0 | 13 | 13 |
| fixed4 | 0 | 13 | 13 |
| fixed5_normalcal5 | 8 | 0 | 13 |

Review burden proxy under TS01 cap500 retention surfaces:

| batch | current burden | period-end+score burden | period-end+score low-support-demoted burden | low-support-demoted TOP100/TOP500 truth docs |
|---|---:|---:|---:|---:|
| fixed3 | 0.4379 | 0.4857 | 0.4521 | 0 / 13 |
| fixed4 | 0.4379 | 0.4857 | 0.4521 | 0 / 13 |
| fixed5_normalcal5 | 0.1959 | 0.4949 | 0.4528 | 13 / 13 |

해석:

- fixed3/fixed4의 TS01 truth candidate window는 존재하지만 원본순 artifact cap 500 밖에 있다. ordinal 분포는 705~2,284다.
- score-desc cap500 또는 period-end+score cap500 diagnostic retention이면 fixed3/fixed4의 TS01 truth candidate window 3개, unique truth document 13개가 들어온다. 이는 artifact 부족이 아니라 retention placement 후보가 있음을 뜻한다.
- fixed5에서는 단순 score-desc cap500은 TS01 truth candidate window를 놓치지만 period-end+score cap500은 3개를 포함한다. 따라서 단순 score 정렬은 cross-batch에서 안정적인 후보가 아니고, period-end context와 score의 결합 retention이 다음 diagnostic 후보가 된다.
- `period-end+score low-support-demoted`는 세 batch 모두 TOP500 truth document 13개를 유지하면서 low-row-support share를 0으로 낮춘다. fixed5에서는 TOP100 truth document 13개도 포함한다. fixed3/fixed4 TOP100은 여전히 0이다.
- fixed3/fixed4 TOP100까지 올리는 score-band/ordinal 중심 후보는 fixed3 단일 값에 맞출 위험이 있어 제외했다. 현재 audit-observable retention 후보의 개선 한계는 TOP500이다.
- 이 결과는 production artifact cap 정책 변경이 아니라 diagnostic-only retention policy 후보 근거다.
- artifact에는 `retention_no_fitting_assertions.truth_label_used_for_retention_order=false`, `production_artifact_retention_changed=false`, `detector_artifact_cap_changed=false`, `ts01_candidate_generation_changed=false`를 기록한다.
- readiness 상태는 `production_application_hold`다. 세 batch 모두 TOP500은 개선되지만, 실제 적용 전에는 fixture/DataSynth 추가 검증과 UI/report review burden 검토가 필요하다.
- deterministic fixture에서는 `period_end_score_low_support_demoted_cap500`가 truth label 없이 `supported_unusual_period_end_window`를 `one_row_period_end_noise_high_score`보다 앞에 둔다. 또한 period-end context window를 non-period-end high-score window보다 앞에 둔다. 이 결과는 policy intent 검증이며 production 적용 결정은 아니다.

Row-score window surface diagnostic:

current native TS에서 TOP100과 TOP500 truth coverage가 같았던 이유는 current native case pool이 truth document를 거의 더 담지 못했기 때문이다. fixed5에서는 최종 TS row score가 truth document를 훨씬 넓게 포함하지만, TS01/TS02 detail flag와 native case 생성 단계에서 대부분 빠진다.

| fixed5 stage | truth docs |
|---|---:|
| row_score > 0 | 557 |
| row_score > 0.5 | 502 |
| TS01 detail flag | 13 |
| TS02 detail flag | 0 |
| current native case | 8 |
| retention candidate native surface | 13 |

Diagnostic native-like row-score window 결과:

| batch / surface | policy | TOP100 | TOP500 | TOP1000 | TOP2000 | TOP5000 |
|---|---|---:|---:|---:|---:|---:|
| fixed3 row_score >= 0.5 | period-end+score low-support-demoted | 0 | 43 | 43 | 56 | 109 |
| fixed4 row_score >= 0.5 | period-end+score low-support-demoted | 0 | 43 | 43 | 56 | 109 |
| fixed5 row_score >= 0.5 | period-end+score low-support-demoted | 0 | 0 | 13 | 275 | 373 |
| fixed5 row_score >= 0.8 | period-end+score low-support-demoted | 0 | 8 | 13 | 270 | 290 |
| fixed3 row_score >= 0.5 | period-end support bucket + score | 43 | 51 | 51 | 143 | 363 |
| fixed4 row_score >= 0.5 | period-end support bucket + score | 43 | 51 | 51 | 143 | 363 |
| fixed5 row_score >= 0.5 | period-end support bucket + score | 0 | 264 | 269 | 348 | 376 |
| fixed5 row_score >= 0.8 | period-end support bucket + score | 0 | 191 | 210 | 272 | 290 |
| fixed3 row_score >= 0.5 | period-end support + amount | 162 | 300 | 339 | 356 | 429 |
| fixed4 row_score >= 0.5 | period-end support + amount | 162 | 300 | 339 | 356 | 429 |
| fixed5 row_score >= 0.5 | period-end support + amount | 213 | 314 | 361 | 365 | 381 |
| fixed3 row_score >= 0.5 | period-end support + amount z-score | 161 | 258 | 338 | 356 | 429 |
| fixed4 row_score >= 0.5 | period-end support + amount z-score | 161 | 258 | 338 | 356 | 429 |
| fixed5 row_score >= 0.5 | period-end support + amount z-score | 219 | 309 | 358 | 361 | 380 |
| fixed3 row_score >= 0.5 | period-end support + context count | 59 | 234 | 259 | 355 | 425 |
| fixed4 row_score >= 0.5 | period-end support + context count | 59 | 234 | 259 | 355 | 425 |
| fixed5 row_score >= 0.5 | period-end support + context count | 222 | 324 | 355 | 365 | 381 |
| fixed3 row_score >= 0.5 | period-end support hybrid | 158 | 290 | 301 | 323 | 422 |
| fixed4 row_score >= 0.5 | period-end support hybrid | 158 | 290 | 301 | 323 | 422 |
| fixed5 row_score >= 0.5 | period-end support hybrid | 222 | 340 | 362 | 365 | 381 |

Year-split check for `period-end support hybrid`:

| batch | 2022 TOP100/TOP500 | 2023 TOP100/TOP500 | 2024 TOP100/TOP500 | TOP500 period-end share | TOP500 high amount z-score share |
|---|---:|---:|---:|---:|---:|
| fixed3 | 59 / 68 | 86 / 126 | 107 / 107 | 100.0% | 45.8% |
| fixed4 | 59 / 68 | 86 / 126 | 107 / 107 | 100.0% | 45.8% |
| fixed5_normalcal5 | 58 / 94 | 122 / 135 | 105 / 136 | 100.0% | 10.4% |

해석:

- 더 큰 복구 방향은 있다. 다만 current native case ranker가 아니라 final TS row_score를 subject/day window evidence unit으로 surfacing하는 방향이다.
- fixed3/fixed4는 row-score context window hybrid에서 TOP100 158, TOP500 290까지 회복된다.
- fixed5는 row-score context window hybrid에서 TOP100 222, TOP500 340까지 회복된다.
- 이 결과는 `period_end_context`, row support bucket (`row_count < 3`, `row_count < 10`), row_score, amount tail, manual/after-hours/weekend/round/suspense/risk-keyword context만 사용한다. truth label은 surface order에 쓰지 않는다.
- false-positive pressure proxy는 support-bucket-only보다 높지만 fixed3/fixed4 `0.4801`, fixed5 `0.4675`로 좁은 범위에 있다. production 적용 전 review burden cap과 UI/export 표면 분리가 필요하다.
- year-split floor가 세 batch 모두 양수이므로 fixed5 한 구간에 맞춘 결과로 보기는 어렵다.
- low-row-support share는 `0.0`이라 한 줄짜리 window 과점은 줄었지만, TOP500 period-end share가 100%라 review burden control은 여전히 필요하다.
- 따라서 다음 product 후보는 TS01/TS02 rule detail flag와 분리된 `TS context window evidence unit` surface다. production 적용 전 UI/report burden control이 필요하다.

Burden-control 후보도 diagnostic-only로 비교했다. 모두 `period_end_support_hybrid` order에서 파생했고 새 truth-fitted weight를 추가하지 않았다.

| batch | policy | TOP100 | TOP500 | TOP500 burden | period-end share | subject top1 share | high amount z-score share |
|---|---|---:|---:|---:|---:|---:|---:|
| fixed3 | hybrid baseline | 158 | 290 | 0.4801 | 100.0% | 8.6% | 45.8% |
| fixed3 | period-end 80% cap | 158 | 254 | 0.3929 | 80.0% | 9.4% | 58.6% |
| fixed3 | subject cap10 | 159 | 245 | 0.4570 | 100.0% | 2.0% | 40.6% |
| fixed3 | high amount z-score 25% cap | 158 | 296 | 0.4759 | 100.0% | 7.4% | 25.0% |
| fixed4 | hybrid baseline | 158 | 290 | 0.4801 | 100.0% | 8.6% | 45.8% |
| fixed4 | period-end 80% cap | 158 | 254 | 0.3929 | 80.0% | 9.4% | 58.6% |
| fixed4 | subject cap10 | 159 | 245 | 0.4570 | 100.0% | 2.0% | 40.6% |
| fixed4 | high amount z-score 25% cap | 158 | 296 | 0.4759 | 100.0% | 7.4% | 25.0% |
| fixed5 | hybrid baseline | 222 | 340 | 0.4675 | 100.0% | 5.0% | 10.4% |
| fixed5 | period-end 80% cap | 222 | 264 | 0.3796 | 80.0% | 5.6% | 26.4% |
| fixed5 | subject cap10 | 222 | 340 | 0.4570 | 100.0% | 2.0% | 10.2% |
| fixed5 | high amount z-score 25% cap | 222 | 340 | 0.4675 | 100.0% | 5.0% | 10.4% |

해석: period-end cap은 burden은 낮추지만 TOP500 손실이 크다. subject cap10은 fixed5에는 거의 비용 없이 subject concentration을 낮추지만 fixed3/fixed4 TOP500 손실이 있다. high amount z-score cap은 fixed3/fixed4에서 TOP500을 `290 -> 296`으로 유지/개선하면서 high amount concentration을 낮춘다. 따라서 다음 product-shaped 후보는 단일 cap 강제가 아니라 `TS context window evidence unit`에 subject/high-amount burden control을 optional diagnostic control로 붙이는 방향이다.

추가로 방향성 평가축을 PHASE2 본질에 맞게 조정했다. 단순 TOP-N recall이 아니라 PHASE1 TOP100 밖의 incremental evidence와 TS-aligned incremental evidence를 별도 측정한다. 이 평가는 policy ordering 뒤 aggregate로만 수행하며, PHASE1 ranking과 PHASE2 fusion은 변경하지 않는다.

| batch | policy | TOP100 truth | TOP100 not in PHASE1 TOP100 | TOP100 TS-aligned not in PHASE1 TOP100 | TOP500 truth | TOP500 not in PHASE1 TOP100 | TOP500 TS-aligned not in PHASE1 TOP100 |
|---|---|---:|---:|---:|---:|---:|---:|
| fixed4 | period-end support hybrid | 158 | 123 | 0 | 290 | 252 | 59 |
| fixed4 | high amount z-score 25% cap | 158 | 123 | 0 | 296 | 258 | 65 |
| fixed4 | timing primary support + round amount demoted | 0 | 0 | 0 | 5 | 5 | 0 |
| fixed5 | period-end support hybrid | 222 | 108 | 2 | 340 | 170 | 32 |
| fixed5 | high amount z-score 25% cap | 222 | 108 | 2 | 340 | 170 | 32 |
| fixed5 | timing primary support + round amount demoted | 13 | 13 | 13 | 33 | 32 | 32 |

이 결과는 기존 broad hybrid가 PHASE1 밖 문서를 많이 올리지만 TOP100 TS-aligned uplift가 약하다는 점을 보여준다. fixed5에서는 timing-primary 후보가 TOP100 TS-aligned incremental을 `2 -> 13`으로 올리지만 fixed4에서 재현되지 않는다. 따라서 현 방향은 broad companion/export surface와 TS primary timing/period-end surface를 분리하는 쪽으로 수정한다. broad surface를 TS family-primary 후보로 해석하지 않는다.

### 8.1 TS Phase 5 primary surface 진단

`artifacts/timeseries_primary_surface_crossbatch_20260530.json`은 fixed5_normalcal5를 primary validation source로 사용한다. fixed4는 known-broken DataSynth baseline이므로 product 판단 근거에서 제외한다.

| Field | Value |
|---|---|
| primary_validation_dataset | `fixed5_normalcal5` |
| excluded_validation_datasets | `["fixed4"]` |
| exclusion_reason | `known-broken DataSynth baseline; not used for product adoption` |

Fixed5 전체 결과:

| Surface | TOP100 TS-aligned outside PHASE1 TOP100 | TOP500 TS-aligned outside PHASE1 TOP100 | TOP100 truth outside PHASE1 TOP100 | TOP500 truth outside PHASE1 TOP100 | TOP500 burden | low support ratio |
|---|---:|---:|---:|---:|---:|---:|
| current native TS order | 0 | 0 | 0 | 0 | 0.2584 | 0.876 |
| broad companion reference | 2 | 32 | 108 | 170 | 0.4675 | 0.118 |
| timing primary context | 0 | 32 | 0 | 32 | 0.4689 | 0.000 |
| supported period-end anomaly | 0 | 32 | 0 | 32 | 0.4689 | 0.000 |
| TS primary conservative | 13 | 32 | 13 | 32 | 0.4689 | 0.000 |

Fixed5 year split for `ts_primary_conservative_surface`:

| Year | TOP100 TS-aligned outside PHASE1 TOP100 | TOP500 TS-aligned outside PHASE1 TOP100 |
|---|---:|---:|
| 2022 | 6 | 9 |
| 2023 | 18 | 18 |
| 2024 | 0 | 8 |

해석:

- fixed4는 더 이상 adoption blocker도 supporting evidence도 아니다.
- fixed5 current native TS order는 PHASE1 밖 TS-aligned evidence를 TOP100/TOP500에 올리지 못한다.
- `ts_primary_conservative_surface`는 fixed5 전체 TOP100에서 TS-aligned incremental `13`, TOP500에서 `32`를 제공한다.
- 이 판단은 v3.1 owner metadata와 TOP100 rank-band gap 진단 이전의 historical decision이다.
- 이후 v3.1/v3.3b/v3.3d 진단에서 `ts_specific_top100_stabilized_surface`가 TS primary `21 / 21`을 TOP100/TOP500에 올렸고, 2026-06-01 기준 TS product/default ordering으로 채택한다.
- broad companion은 recall이 높아도 TS-primary default로 쓰지 않는다.
- 현재 v3.3d responsibility read에서는 `production_adoption=true`, `product_default_ordering_strategy=ts_specific_top100_stabilized_surface`다. 이전 ordering은 internal debug baseline이다.

### 8.2 TS Phase 6 TOP100 failure 진단

`artifacts/timeseries_top100_failure_diagnostic_fixed5_20260530.json`은 fixed5에서 TS truth가 TOP100에 못 드는 원인을 구현, feature, DataSynth label alignment 관점에서 분해한다. fixed4는 product 판단에서 제외한다.

Truth attribution:

| Metric | Count |
|---|---:|
| total truth docs | 620 |
| TS-primary label aligned truth docs | 32 |
| mixed / non-TS truth docs | 588 |
| truth docs in TS candidate pool | 502 |
| truth docs missing from TS candidate pool | 118 |
| candidate-pool truth docs outside TOP100 | 489 |

Alignment:

| Class | Count |
|---|---:|
| `ts_primary_label_aligned` | 32 |
| `mixed_but_ts_relevant` | 400 |
| `non_ts_primary_but_ts_context_present` | 144 |
| `not_ts_family_target` | 44 |

Candidate comparison:

| Surface | TOP100 TS-specific | TOP500 TS-specific | TOP100 mixed TS-relevant | TOP500 mixed TS-relevant |
|---|---:|---:|---:|---:|
| current native TS order | 0 | 0 | 0 | 0 |
| TS primary conservative | 13 | 32 | 0 | 0 |
| TS-specific severity | 0 | 32 | 0 | 0 |
| mixed TS-relevant | 2 | 32 | 236 | 275 |

해석:

- TOP100 실패의 1차 원인은 `mixed_scenario_not_ts_primary`와 DataSynth label alignment 문제다.
- aggregate 구현 검증에서는 `implementation_bug_suspected=false`다.
- TS-specific truth는 32건으로 작다. 따라서 전체 620 truth를 TS TOP100 목표로 두는 것은 family 역할과 맞지 않는다.
- `ts_primary_conservative_surface`는 TS-specific truth 13건을 TOP100에 올리고 TOP500에서 32건 전부를 커버한다.
- `mixed_ts_relevant_surface`는 TOP100 mixed context를 많이 올리지만 TS-primary라고 보기 어렵다.
- `top500_companion_only_rejected_as_final_goal=true`다. 단, production adoption은 여전히 false이며 다음 단계는 TS-primary-aligned truth target 재정의와 ranking separation 개선이다.

### 8.3 TS Phase 7 TOP100 rank-band gap 진단

`artifacts/timeseries_top100_rankband_gap_fixed5_20260530.json`은 TS-specific 32건만 denominator로 두고, `ts_primary_conservative_surface`에서 TOP100에 들어온 13건과 TOP101-500에 남은 19건을 비교한다. fixed4는 사용하지 않았고, truth/scenario/raw identifier/PHASE1 rank는 selector 입력으로 쓰지 않았다.

13 vs 19 aggregate 비교:

| Feature | TOP100 13 | TOP101-500 19 | 해석 |
|---|---:|---:|---|
| robust_z median | 3.3725 | 1.5738 | delayed 쪽이 약함 |
| period_end_lift median | 7.0 | 5.5 | delayed 쪽이 약함 |
| baseline observations median | 243 | 167 | delayed 쪽 baseline support 낮음 |
| context evidence median | 2 | 1 | delayed 쪽 context evidence 낮음 |
| supported window ratio | 1.000 | 1.000 | one-row/low-support 문제는 아님 |
| period-end context ratio | 1.000 | 1.000 | period-end 자체는 차별 feature 아님 |
| after-hours/weekend ratio | 1.000 | 0.421 | timing-context gap이 뚜렷함 |
| subject activity rank median | 61 | 4 | delayed 쪽은 high-activity background 과점 |
| business process | TRE 13 | R2R 11, TRE 8 | aggregate-only 진단 |
| source | manual 13 | manual 15, adjustment 4 | aggregate-only 진단 |

Delayed 19 reason:

| Reason | Count |
|---|---:|
| score_tie_or_rank_band_collision | 19 |
| lower_robust_z | 11 |
| low_context_evidence | 11 |
| low_baseline_support | 11 |
| high_subject_activity_background | 11 |
| normal_period_end_competition | 11 |
| weak_after_hours_weekend_signal | 11 |
| one_row_or_low_support_window | 0 |
| no_clear_audit_observable_difference | 0 |

Diagnostic-only 후보:

| Surface | TOP100 TS-specific | TOP500 TS-specific | TOP100 mixed TS-relevant | TOP500 mixed TS-relevant | TOP500 burden |
|---|---:|---:|---:|---:|---:|
| TS primary conservative | 13 | 32 | 0 | 0 | 0.4689 |
| TS-specific TOP100 stabilized | 21 | 32 | 0 | 0 | 0.4689 |

해석:

- fitting 없이 쓸 수 있는 audit-observable feature gap은 있다. `after_hours_weekend_priority`와 `subject_activity_background_adjustment`가 TOP100 placement 개선 후보로 남았다.
- 새 후보는 amount-tail / business_process / source / fiscal_year를 selector feature로 쓰지 않는다. 이 값들은 aggregate 진단용으로만 기록했다.
- `ts_specific_top100_stabilized_surface`는 TS-specific TOP100을 `13 -> 21`로 올리고 TOP500 `32/32`를 유지한다. TOP100 mixed TS-relevant는 `0`이라 broad companion inflation은 아니다.
- `build_timeseries_cases`와 `build_phase2_case_set`의 TS product/default read는 `ts_specific_top100_stabilized_surface`로 해석한다. 이전 ordering은 internal debug baseline으로만 보존한다.
- `artifacts/timeseries_v31_primary_fixed5_ownermeta_ic_20260531.json`은 adoption 이전 diagnostic readiness를 보존한다. v3.3d responsibility artifact는 `product_default_ordering_strategy_ts_specific_top100_stabilized_surface`, `product_default_adoption_allowed=true`로 읽는다.
- selector input은 truth/scenario/owner metadata/PHASE1 rank/matched result/raw identifier를 쓰지 않는다. Owner metadata는 denominator/evaluation에만 사용한다.
- production adoption은 TS primary review ordering 범위에서 true다. Detector/gate/threshold, PHASE1 ranking, PHASE2 fusion은 변경하지 않는다.

---

## 13. 포트폴리오용 해석

현재 가장 방어 가능한 설명은 다음과 같다.

1. PHASE1은 deterministic rule/evidence 기반의 1차 review queue다.
2. PHASE2는 PHASE1 결과 CSV에 의존하지 않고 원본 CSV에서 독립적으로 family detector를 실행한다.
3. PHASE2 native case는 family별 evidence 단위(pair / edge / row / window)를 감사인이 확인 가능한 객체로 노출한다.
4. native case 기준으로는 `intercompany`가 가장 명확한 circular-related-party evidence lane이다.
5. `unsupervised`는 많은 row anomaly 후보를 만들며, 깊은 검토 범위에서 coverage가 확장된다.
6. `duplicate`는 pair evidence unit 생성 복구와 artifact-only document diversity retention 후 period-end truth 일부를 TOP-N에 포함한다. 이는 truth threshold 튜닝이 아니라 감사인이 확인 가능한 pair evidence unit 보존 방식 개선이다.
7. DataSynth truth 기반 recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.

금지 표현:

- “부정을 탐지했다”
- “실무 운영 성능 검증 완료”
- “Phase2 단독 fraud detector”
- “recall이 높으므로 실제 감사 적용 가능”

권장 표현:

- “synthetic anomaly review queue 농축”
- “family별 독립 native review case lane”
- “review-worthy candidate 우선순위화”
- “PHASE1 deterministic evidence와 PHASE2 statistical/structural evidence의 분리 운영”
- “PHASE2 native case는 감사인이 확인 가능한 evidence unit을 제공한다”

---

## 14. Agent U — Unsupervised native case 점검

### 14.1 현재 구현 판정

`build_unsupervised_cases` 는 `DetectionResult.scores` 에 대해 zero-preserving ECDF 를 계산하고,
`family_ecdf >= 0.95` 인 row 만 `UnsupervisedCase(unit_type="row")` 로 만든다.
즉 q95 gate 는 DataSynth truth recall 에 맞춘 임계가 아니라 native row evidence unit 생성을 위한
분포 기반 gate 다.

fixed5 측정 정렬은 `evidence_tier(strong > moderate > ml_quantile > weak)`,
`family_score desc`, `phase2_case_id` 순이다. unsupervised case 의 `evidence_tier` 는 모두
`ml_quantile` 이므로 실제 tie-break 는 `family_score desc` 가 맡는다.

### 14.2 family_score / family_ecdf 의미

`family_score` 는 builder 입력 `DetectionResult.scores` 값을 그대로 보존한다. production
`UnsupervisedDetector.detect()` 에서 이 값은 학습 분포 기준 VAE reconstruction ECDF score 다.
fixed5 Stage7 measurement path 의 `score_unsupervised()` 도 저장된 학습 분포
`ecdf_train_sorted` 로 변환한 ECDF score 를 반환한다. 따라서 현재 fixed5 native measurement 에서
`family_score` 는 raw reconstruction error 가 아니라 train-distribution ECDF score 에 가깝다.

`family_ecdf` 는 builder 가 현재 score series 안에서 다시 계산한 zero-preserving queue ECDF 다.
역할은 q95 gate 통과 여부와 native queue 내 상대 위치 설명이다. `family_score` 와
`family_ecdf` 는 같은 의미가 아니며, 둘을 모두 보존하는 것이 맞다.

### 14.3 top_features 경로 분리

production detector runtime 은 `src/detection/vae_detector.py::UnsupervisedDetector.detect()` 에서
`ML02_top_feature_1~3` 과 `ML02_top_feature_1~3_contrib` 를 `details` 에 첨부한다. 이 경로에서는
native unsupervised case 가 `top_features` evidence payload 를 만들 수 있다.

반면 `tools/scripts/measure_phase2_native_cases_fixed5_20260528.py::_build_unsupervised_result()` 는
저장된 score bundle 로 row score 만 재계산하고, feature contribution 행렬은 복원하지 않는다.
그래서 dummy details (`_stage7_native_measurement`) 를 넣어 q95 gate 와 row evidence unit 만 측정한다.
이 경로에서 `top_features == ()` 인 것은 production detector 설명력 부재가 아니라 Stage7 측정 artifact 의
한계다.

### 14.4 recall 급락 원인

native unsupervised case 는 많이 생성되지만(51,717건), case 단위는 PHASE1 overlay 가 아니라
row evidence unit 이다. TOP100 5건 / TOP10000 289건이라는 결과는 다음의 결합 효과로 해석한다.

1. legacy overlay 는 PHASE1 case 위에 PHASE2 score 를 얹은 측정이었고, native 는 row evidence unit 자체를
   정렬한다.
2. unsupervised 는 구조적 pair/edge evidence 가 아니라 row anomaly lane 이라 document-level truth 가
   여러 row candidate 사이에 분산될 수 있다.
3. fixed5 measurement path 는 top_features payload 없이 score/gate 만 측정하므로, 감사인이 확인할
   feature-level reason payload 품질은 production detector 경로와 분리해서 봐야 한다.

legacy overlay baseline은 같은 family score를 PHASE1 case/document 위에 얹은 값이라 훨씬 높았다.
보존용 baseline은 TOP100 79건 / 12.74%, TOP500 216건 / 34.84%, TOP10000 507건 / 81.77%다.
이는 native row evidence unit queue와 직접 비교할 수 없고, row-to-document aggregation 효과가 포함된
기준선으로만 본다.

### 14.5 row-to-document attrition 진단

2026-05-29 fixed5 artifact는 `family_diagnostics.unsupervised`에 aggregate-only 진단을 기록한다.
truth label은 native case 생성 이후의 개발 검증 집계에만 사용했고, detector/ranker 입력에는 사용하지 않았다.
raw document identifier는 JSON에 쓰지 않는다.

| 항목 | 값 | 해석 |
|---|---:|---|
| total unsupervised row cases | 51,717 | q95 gate 통과 row evidence unit 수 |
| unique docs covered by cases | 20,471 | row case가 document 단위로 접히면 후보 문서 수가 크게 줄어든다. |
| truth docs covered by all cases | 483 / 620 | q95 전체 deep queue에는 truth document 다수가 들어온다. |
| TOP100 / TOP500 / TOP10000 truth docs | 5 / 39 / 289 | 상단 row rank에서 document coverage가 약하다. |
| first truth-covering row case rank | 1 | score 최상단에도 truth-covering row는 존재한다. |
| truth row case rank p50 / p90 / max | 6,845 / 39,063 / 51,639 | truth-covering row case가 queue 깊은 곳까지 넓게 퍼져 있다. |
| truth doc best-rank p50 / p90 / max | 6,239 / 39,242 / 51,570 | document별 최고 row rank도 중앙값이 TOP500 밖이다. |
| cases per document p50 / p90 / max | 2 / 3 / 998 | 일부 nontruth 반복 문서가 row evidence unit을 많이 점유한다. |
| truth cases per document p50 / p90 / max | 2 / 2 / 4 | truth 문서는 row case 수가 많지 않다. |
| nontruth cases per document p50 / p90 / max | 2 / 3 / 998 | row-count skew는 주로 nontruth 문서에서 발생한다. |

score/rank 분포는 score 자체가 완전히 무관하지 않음을 보여준다.

| 비교 | truth-covering row cases | nontruth row cases | 해석 |
|---|---:|---:|---|
| family_score p50 / p90 | 0.9935 / 0.9993 | 0.9751 / 0.9945 | truth-covering row가 평균적으로 더 높은 tail에 있다. |
| row amount p50 / p90 | 250,000,000 / 2,205,000,000 | 323,100 / 25,000,000 | 금액 크기 차이가 강하다. |
| period-end proximity p50 / p90 | 3 / 14 days | 13 / 27 days | truth-covering row가 결산일에 더 가깝다. |

따라서 병목은 “unsupervised score가 truth와 전혀 연결되지 않음”이라기보다,
row-level score가 document-level review candidate로 접히지 않아 상단 TOP-N에서 coverage가 희석되는
문제에 가깝다.

### 14.6 document-level aggregation 후보 실험

다음 값은 offline diagnostic이다. PHASE1 priority/composite/ranking, PHASE2 family fusion, Noisy-OR,
RRF, native row case queue 정렬은 변경하지 않았다.

| 후보 document ranking | TOP100 | TOP500 | TOP1000 | TOP10000 | 해석 |
|---|---:|---:|---:|---:|---|
| document_max_score | 11 | 62 | 107 | 376 | row max만 써도 native row queue보다 상단 coverage가 오른다. |
| document_ecdf_max | 11 | 62 | 107 | 376 | 현재 score가 ECDF라 max score와 사실상 같다. |
| document_top_k_mean_score k=3 | 18 | 82 | 101 | 369 | 상단 문서 coverage가 개선되지만 TOP10000은 낮아진다. |
| document_top_k_mean_score k=5 | 18 | 82 | 101 | 368 | k=3과 유사하다. |
| document_case_count_weighted_score | 0 | 0 | 1 | 428 | row-count skew를 강화해 상단 품질이 나빠진다. |
| document_score_with_row_count_penalty | 22 | 100 | 141 | 408 | 가장 강한 후보. 반복 row 문서 독점을 줄인다. |
| document_score_with_diversity_penalty | 0 | 0 | 0 | 206 | diversity penalty 정의가 현재 데이터에는 부적합하다. |

판단:

1. `document_score_with_row_count_penalty`는 TOP100/TOP500/TOP10000 모두 native row queue보다 높다.
2. `document_top_k_mean_score`도 TOP100/TOP500에서는 개선되지만 deep coverage는 max/penalty보다 낮다.
3. `document_case_count_weighted_score`와 `document_score_with_diversity_penalty`는 상단 review candidate
   농축에 부적합하다.
4. 개선 후보는 존재하지만, 이는 document-level queue 후보일 뿐 native row evidence unit 정렬 변경 근거는 아니다.
   실제 적용 전에는 정상 문서 반복 거래, 고액 정상 결산 문서, account/process concentration을 별도 검토해야 한다.

### 14.7 Phase 3 document-level companion lane 진단

2026-05-29 추가 진단 산출물은
`artifacts/unsupervised_document_aggregation_diagnostic_fixed5_20260529.json` 이다. 이 산출물은
diagnostic-only이며, q95 gate, VAE score/threshold, PHASE1 priority/composite/ranking, PHASE2 family
fusion, Noisy-OR/RRF, native row case queue 정렬을 변경하지 않는다. truth label은 후보별 aggregate
coverage 계산에만 사용했고, scoring 입력에는 사용하지 않았다. raw document identifier나 raw row/index
label은 JSON에 저장하지 않는다. 또한 artifact는 `raw_identifier_leak_check`를 self-report하며,
현재 값은 `doc_like_token_count=0`, `forbidden_identifier_key_count=0`,
`phase2_case_id_like_token_count=0`이다.

coverage/quality matrix:

| 후보 ranking | TOP100 | TOP500 | TOP10000 | 판단 |
|---|---:|---:|---:|---|
| native row queue | 5 | 39 | 289 | 현재 제품 row evidence unit queue 기준선 |
| document_max_score | 11 | 62 | 376 | max row score만으로도 일부 attrition 완화 |
| document_top_k_mean_score_k3 | 18 | 82 | 369 | 상단 개선은 있으나 deep coverage는 penalty/hybrid보다 낮음 |
| document_score_with_row_count_penalty | 22 | 100 | 408 | fixed5 기준 더 보수적인 document companion 후보 |
| hybrid_max_score_amount_tail_period_end | 50 | 209 | 483 | fixed5 coverage best지만 정상 반복 문서 집중 위험도 함께 큼 |

현재 iteration에서 추가한 diagnostic-only 후보:

| 후보 ranking | TOP100 | TOP500 | TOP10000 | first truth rank | TOP100 repeated normal ratio | 해석 |
|---|---:|---:|---:|---:|---:|---|
| hybrid_with_repeated_normal_penalty | 3 | 22 | 476 | 2 | 0.00 | pressure는 낮지만 상단 coverage 손실이 큼 |
| hybrid_with_account_process_concentration_guard | 3 | 65 | 483 | 2 | 0.00 | account/process 과점 완화 proxy는 강하지만 TOP100 coverage가 낮음 |
| row_count_penalty_with_amount_tail_floor | 22 | 100 | 408 | 4 | 0.46 | 기존 row-count penalty와 같은 fixed5 ordering으로 관측됨 |
| top_k_mean_with_context | 3 | 22 | 476 | 2 | 0.00 | context 보정은 deep coverage를 유지하지만 상단 농축이 약함 |
| document_companion_balanced_surface | 3 | 117 | 480 | 2 | 0.00 | TOP500은 개선되나 TOP100 review candidate 농축은 부족 |
| hybrid_with_soft_repeated_normal_guard | 25 | 151 | 483 | 2 | 0.15 | native보다 pressure가 낮고 TOP100/TOP500 coverage가 크게 개선됨 |
| soft_guard_with_row_count_context | 32 | 174 | 483 | 2 | 0.24 | coverage는 추가 개선되지만 일부 batch에서 pressure가 native 근처까지 상승 |
| phase1_prior_companion_surface | 51 | 273 | 482 | 1 | 0.25 | legacy overlay가 쓰던 PHASE1 document prior를 diagnostic-only로 복원 |
| hybrid_row_count_blended_surface | 61 | 263 | 483 | 4 | 0.38 | coverage best지만 pressure가 여전히 높음 |

balanced surface의 TOP100 union/intersection 비교는 union 55건 / 177 documents, intersection 17건 / 23
documents다. union은 coverage를 넓히지만 review burden이 커지고, intersection은 부담은 낮지만 coverage가
낮다. 모든 신규 후보의 `candidate_weight_provenance`는 `fixed5 exploratory diagnostic weights`,
`calibrated=false`, `production_ranking_policy=false`, `requires cross-batch/fixture validation before
adoption`로 기록한다.

false-positive risk profile aggregate:

| 후보 ranking | TOP100 single-row high-amount ratio | TOP100 repeated normal ratio | 해석 |
|---|---:|---:|---|
| document_top_k_mean_score_k3 | 0.00 | 0.24 | 반복 정상 문서 집중은 상대적으로 낮지만 coverage 개선폭도 제한적 |
| document_score_with_row_count_penalty | 0.00 | 0.46 | fixed5 coverage는 좋지만 반복 정상 문서 검증이 필요 |
| hybrid_max_score_amount_tail_period_end | 0.00 | 0.49 | period-end/amount tail 신호가 강하나 정상 반복 문서 동반 위험이 큼 |

decision payload는 `best_coverage_candidate=hybrid_row_count_blended_surface`,
`best_pressure_adjusted_candidate=hybrid_with_soft_repeated_normal_guard`,
`most_stable_candidate=hybrid_with_soft_repeated_normal_guard`,
`baseline_conservative_candidate=document_score_with_row_count_penalty`,
`production_adoption=pending_cross_batch_validation`로 기록한다. 결론은 `diagnostic 유지, 추가 batch 필요`
이다. blend는 fixed5 TOP100/TOP500 coverage가 가장 높지만 pressure가 아직 높아 바로 product ranking에
적용하지 않는다. soft repeated-normal guard는 native row queue보다 TOP100/TOP500 coverage가 높고
TOP100 false-positive pressure가 낮아 현재 가장 설명 가능한 document companion surface 후보로 본다.
다음 단계는 product ranking 변경이 아니라 cross-batch validation이며, 정상 단일-row 고액 문서, 반복
정상 문서, account/process concentration을 batch별로 검증해야 한다.

### 14.8 cross-batch companion surface 점검

`artifacts/unsupervised_document_aggregation_crossbatch_20260529.json`은 fixed3, fixed4,
fixed5_normalcal4, fixed5_normalcal5를 같은 diagnostic-only scorer로 비교한다. q95 gate, VAE
score/threshold, PHASE1 ranking, PHASE2 fusion, native row case ordering은 변경하지 않았다.
raw identifier self-report는
`doc_like_token_count=0`, `forbidden_identifier_key_count=0`, `phase2_case_id_like_token_count=0`이다.

| 후보 ranking | TOP100 range | TOP500 range | TOP100 pressure range | 해석 |
|---|---:|---:|---:|---|
| native row queue | 5-5 | 34-39 | 0.166-0.190 | current row evidence unit baseline |
| document_score_with_row_count_penalty | 19-22 | 97-100 | 0.244-0.258 | coverage는 안정적이나 pressure가 native보다 높음 |
| hybrid_max_score_amount_tail_period_end | 44-50 | 161-209 | 0.311-0.333 | coverage 우위는 재현되지만 pressure도 높음 |
| hybrid_with_soft_repeated_normal_guard | 15-27 | 103-151 | 0.100-0.147 | coverage와 pressure의 균형이 가장 좋음 |
| soft_guard_with_row_count_context | 20-32 | 126-174 | 0.145-0.192 | coverage는 더 높지만 fixed5 pressure가 native 근처까지 상승 |
| phase1_prior_companion_surface | 25-51 | 143-273 | 0.154-0.229 | legacy recall 회복력이 가장 큼. PHASE1 ranking은 변경하지 않음 |
| hybrid_row_count_blended_surface | 54-61 | 196-263 | 0.296-0.319 | coverage best지만 review burden과 pressure가 큼 |

현재 iteration 결과는 soft repeated-normal guard가 diagnostic product companion 후보로 볼 수 있는
surface라는 것이다. 다만 이 표현은 적용 결정을 뜻하지 않는다. 2022/2023/2024 year-split slice에서도 soft guard는
각 batch마다 aggregate coverage를 유지하지만, fixed3/fixed4의 TOP100 uplift는 fixed5보다 작다. 다음
iteration은 fixed3/fixed4에서 TOP100 soft guard가 낮아지는 원인을 period-end background, amount tail,
account/process concentration drift로 분해해야 한다.

soft guard drift decomposition 결과:

| batch | TOP100 | TOP500 | TOP100 pressure | repeated normal proxy | period-end normal background proxy | year-slice TOP100 min-max | 해석 |
|---|---:|---:|---:|---:|---:|---:|---|
| fixed3 | 16 | 107 | 0.102 | 0.11 | 0.81 | 3-9 | fixed5보다 낮지만 native row queue보다 높음 |
| fixed4 | 15 | 103 | 0.100 | 0.11 | 0.82 | 3-9 | 낮은 TOP100은 pressure 증가보다 slice floor 약화와 연결됨 |
| fixed5_normalcal4 | 27 | 134 | 0.147 | 0.15 | 0.69 | 6-11 | coverage와 pressure 균형 유지 |
| fixed5_normalcal5 | 25 | 151 | 0.143 | 0.15 | 0.72 | 5-11 | coverage와 pressure 균형 유지 |

이 분해는 fixed3/fixed4의 낮은 TOP100이 false-positive pressure 증가 때문이라는 해석을 지지하지 않는다.
오히려 pressure는 fixed3/fixed4에서 더 낮고, year-split TOP100 floor가 낮다. 따라서 다음 개선 방향은
repeated-normal penalty를 더 강하게 만드는 것이 아니라, fixed3/fixed4에서 상단으로 올라오지 못한
year-slice review candidate의 amount tail / period-end context / account-process context 차이를 더
분해하는 것이다.

rank-band decomposition은 soft guard TOP500 안에서 TOP100 밖에 남아 있는 truth-covering document
candidate가 많음을 보여준다. fixed4 기준 TOP500 안 TOP100 밖에는 88건이 있고, rank101-250에 39건,
rank251-500에 49건이 있다. 이를 바탕으로 `soft_guard_with_row_count_context`를 diagnostic-only 후보로
추가했다. 이 후보는 cross-batch TOP100 20-32, TOP500 126-174로 soft guard보다 coverage가 높지만,
TOP100 pressure range가 0.145-0.192로 일부 fixed5 slice에서 native row queue 근처까지 올라온다. 따라서
현재 가장 균형 잡힌 후보는 여전히 `hybrid_with_soft_repeated_normal_guard`이고,
`soft_guard_with_row_count_context`는 review-burden을 더 허용하는 companion surface 후보로만 둔다.
추가 weight sweep은 fixed5 TOP-N fitting 위험이 있으므로, 다음 단계는 새 가중치 탐색이 아니라 auditor가
감당 가능한 review burden cap과 batch별 pressure ceiling을 먼저 정하는 것이다.

PHASE1-prior companion surface는 legacy overlay와 가장 가까운 회복력을 보인다. fixed5_normalcal5 기준
TOP100은 51건 / 8.23%, TOP500은 273건 / 44.03%, TOP10000은 482건 / 77.74%다. 이는 legacy overlay
unsupervised TOP100 79건 / 12.74%에는 아직 못 미치지만, TOP500은 legacy 216건 / 34.84%를 넘는다.
이 surface는 PHASE1 `priority_score`, `composite_sort_score`, ranking을 변경하지 않고, row의
audit-observable PHASE1 risk/rule context를 document companion diagnostic prior로만 재사용한다.
따라서 product ranking 적용은 보류하지만, legacy recall 회복 목적의 가장 강한 후보로 기록한다.

추가로 PHASE1-prior lane과 aggressive lane을 합집합으로 보는 expanded review surface를 계산했다. fixed5
기준 TOP100 lane별 100개 합집합은 127개 review document burden에서 64건 / 10.32%를 커버한다. 이는
PHASE1-prior 단독 51건보다 높지만 legacy overlay TOP100 79건에는 아직 못 미친다. TOP500에서는 네 개
diagnostic lane 합집합이 792개 review document burden에서 288건 / 46.45%를 커버한다. 따라서 TOP500은
legacy를 넘어섰지만, TOP100 legacy 회복은 현재 audit-observable native companion features만으로는
부족하다. 여기서 더 TOP100을 밀려면 fixed5 TOP-N 결과를 보고 새 가중치를 조합하는 fitting 위험이 커진다.

### 14.8.1 PHASE1 대비 incremental value 재정의

`incremental_coverage_diagnostic`의 PHASE1 all document inclusion은 broad inclusion metric으로만 남긴다.
PHASE1 case-result가 어떤 document를 포함했다는 사실은 그 document의 intended issue를 정확히
설명하거나 상단에 우선순위화했다는 뜻이 아니다. 따라서 새 판단은
`unsupervised_incremental_value_diagnostic`에서 PHASE1 TOP-N uplift, ML/statistical evidence incremental,
scenario/explanation gap, blind-spot attrition을 분리해 기록한다. raw document identifier는 artifact에
저장하지 않는다.

fixed5 PHASE1 baseline:

| baseline | count |
|---|---:|
| PHASE1 all review documents | 24,790 |
| PHASE1 all truth-covering documents | 544 / 620 |
| PHASE1 TOP100 truth-covering documents | 0 |
| PHASE1 TOP500 truth-covering documents | 50 |
| PHASE1 TOP1000 truth-covering documents | 87 |

PHASE1 TOP-N uplift, fixed5:

| surface | TOP100 net uplift | TOP500 net uplift | TOP1000 net uplift | 해석 |
|---|---:|---:|---:|---|
| native_row_queue | +5 | -11 | +2 | row evidence unit queue 단독으로는 TOP500 uplift 부족 |
| hybrid_with_soft_repeated_normal_guard | +25 | +101 | +220 | pressure-adjusted ML/statistical companion 후보 |
| soft_guard_with_row_count_context | +32 | +124 | +228 | coverage는 더 높지만 pressure ceiling 검토 필요 |
| hybrid_row_count_blended_surface | +61 | +213 | +247 | recall은 높지만 fixed5 exploratory weight smell 때문에 default 금지 |
| phase1_prior_companion_surface | +51 | +223 | +252 | PHASE1-informed surface이며 pure unsupervised로 해석 금지 |
| frontier_all_four_lanes_union | +64 | +238 | +277 | expanded review burden을 감수할 때 가장 큰 uplift |
| balanced_unsupervised_companion_v1 | +64 | +44 | +104 | 2:1 audit role policy interleave. ratio sweep 없음 |

evidence incremental, fixed5:

| metric | count |
|---|---:|
| unsupervised_evidence_added_truth_docs | 483 |
| unsupervised_evidence_added_case_count | 930 |
| ml_score_evidence_added_truth_docs | 483 |
| top_feature_evidence_added_truth_docs | 0 |
| document_level_context_added_truth_docs | 483 |
| amount_tail_context_added_truth_docs | 189 |
| period_end_context_added_truth_docs | 483 |
| row_count_repeated_guard_context_added_truth_docs | 442 |
| phase2_specific_ml_reason_truth_docs | 47 |

`top_feature_evidence_added_truth_docs=0`은 Stage7 measurement path의 한계다. production detector path의
`ML02_top_feature_*` 연결 회귀 가드는 별도 unit test로 유지한다. 이 수치를 production top_features 품질로
과장하지 않는다.

scenario/explanation gap aggregate는 PHASE1 scenario-aligned truth docs 404건, PHASE1 scenario-gap truth
docs 140건, unsupervised explanation incremental truth docs 47건으로 기록한다. unsupervised evidence는
scenario-specific rule finding이 아니라 ML/statistical review context다.

blind-spot attrition은 PHASE1 TOP1000 밖 truth docs와 PHASE1 generic-only truth docs를 대상으로 본다.
fixed5 target truth docs는 533건이며, 이 중 raw unsupervised score 대상은 533건, q95 pass/native
case/document candidate는 409건이다. balanced companion 기준 candidate pool에 있으나 TOP500 밖인
truth docs는 389건, candidate pool에 없는 truth docs는 124건이다. aggregate reason은
`candidate_but_ranked_below_top500=389`, `q95_gate_miss=124`로 기록한다.

새 decision payload는 `document_inclusion_incremental_value=broad_inclusion_metric_only`,
`topn_uplift_value=medium`, `evidence_incremental_value=high`,
`explanation_incremental_value=medium`, `primary_product_role=broad_expansion`,
`recommended_default_surface_if_datasynth_incomplete=hybrid_with_soft_repeated_normal_guard`,
`adopted_default_allowed=false`로 기록한다. adopted 가능성이 있더라도 이유는
“PHASE1 blind spot 대량 발굴”이 아니라 “PHASE1 TOP-N uplift + ML/statistical evidence incremental +
broad expansion”이다. product default, q95 gate, VAE score/threshold, PHASE1 priority/composite/ranking,
PHASE2 fusion, native row case ordering은 변경하지 않는다.

### 14.8.2 TOP500 밖 ranking attrition 개선 후보

`unsupervised_attrition_improvement_diagnostic`은 가장 큰 병목인
`candidate_but_ranked_below_top500`을 줄일 수 있는지 diagnostic-only로 본다. fixed5 기준 baseline target은
PHASE1 TOP1000 밖 또는 PHASE1 generic-only truth docs이며, balanced companion 기준 TOP500 밖 candidate가
389건이다. rank band는 501-1000 97건, 1001-2000 181건, 2001-5000 67건, 5001+ 44건이다. reason category는
`repeated_normal_competition=269`, `audit_policy_interleave_suppression=90`,
`phase1_topn_gap_low_surface_priority=29`, `weak_amount_period_end_context=1`이다.

q95 gate miss 124건은 product case로 승격하지 않는다. 단, diagnostic aggregate로 보면 near-q95 band는
54건이고, q95 miss but strong document context 후보는 5건이다. 이는 q95 gate를 바꿀 근거가 아니라 future
candidate validation backlog다.

top_features 경로는 분리해서 기록한다. production `UnsupervisedDetector`는 `ML02_top_feature_*` details를
생성하고 builder는 이를 `UnsupervisedCase.top_features`로 보존한다. fixed5 Stage7 measurement path는
dummy details를 쓰므로 `top_feature_evidence_added_truth_docs=0`이다. top_features는 ranking score가
아니라 evidence quality metric으로만 유지한다.

새 diagnostic-only surface 결과, fixed5:

| surface | TOP100 | TOP500 | TOP500 uplift vs PHASE1 | below-TOP500 reduction | TOP500 repeated-normal ratio | 해석 |
|---|---:|---:|---:|---:|---:|---|
| hybrid_with_soft_repeated_normal_guard | 25 | 151 | +101 | 86 | 0.256 | current recommended diagnostic surface |
| soft_guard_rank_band_rescue_surface | 25 | 150 | +100 | 88 | 0.256 | attrition은 2건 더 줄지만 coverage가 1건 낮아 default 근거 부족 |
| soft_guard_context_diversity_surface | 25 | 131 | +81 | 73 | 0.336 | diversity cap이 coverage를 낮추고 pressure도 높음 |
| ml_evidence_quality_surface | 25 | 151 | +101 | 86 | 0.256 | Stage7 top_features 부재로 disabled |
| phase1_topn_gap_companion_surface | 48 | 135 | +85 | 65 | 0.298 | TOP100은 높지만 TOP500/evidence balance가 soft guard보다 약함 |
| hybrid_row_count_blended_surface upper bound | 61 | 263 | +213 | 178 | 0.382 | coverage upper-bound이며 pressure가 높아 adopted 금지 |

cross-batch에서도 같은 schema를 생성한다. exact PHASE1 case-result가 있는 fixed3/fixed4/fixed5_normalcal5에서
soft rescue의 TOP500 matched는 101-150, TOP500 uplift는 54-100, below-TOP500 reduction은 34-88이다.
fixed5_normalcal4는 PHASE1 case-result artifact가 없어 review-context fallback으로 분리한다. 현재 판단은
product default 변경이 아니라 diagnostic 유지다. soft rescue는 구조적으로 볼 가치가 있지만, fixed5에서
soft guard보다 TOP500 coverage가 낮고 cross-batch validation도 아직 adoption 근거로 충분하지 않다.

### 9.8.3 Phase 5 production evidence quality

2026-05-30 Phase 5 산출물은
`artifacts/unsupervised_evidence_quality_fixed5_20260530.json` 및
`docs/debugging/UNSUPERVISED_NATIVE_CASE_EVIDENCE_20260530.md`이다. fixed5 measurement path에서
Stage7 dummy details 대신 deterministic VAE reconstruction top-k를 `ML02_top_feature_*` details로 만들어
`UnsupervisedCase.top_features`까지 전달했다. top_features는 ranking score가 아니라 evidence quality
metric으로만 사용한다.

top_features 연결 결과:

| metric | count |
|---|---:|
| top_features_available_case_count | 51,717 |
| top_features_available_truth_docs | 483 |
| top_feature_evidence_added_truth_docs | 483 |
| top_features_available_top100_truth_docs | 5 |
| top_features_available_top500_truth_docs | 39 |

document companion 재측정, fixed5:

| surface | TOP100 | TOP500 | TOP10000 | TOP500 repeated-normal pressure | top_features availability |
|---|---:|---:|---:|---:|---:|
| native_row_queue | 5 | 39 | 289 | 0.716 | 1.000 |
| document_score_with_row_count_penalty | 22 | 100 | 408 | 0.462 | 1.000 |
| hybrid_with_soft_repeated_normal_guard | 25 | 151 | 483 | 0.256 | 1.000 |
| soft_guard_with_row_count_context | 32 | 174 | 483 | 0.282 | 1.000 |
| hybrid_row_count_blended_surface_upper_bound | 61 | 263 | 483 | 0.382 | 1.000 |
| soft_guard_pressure_guard_surface | 3 | 22 | 365 | 0.000 | 1.000 |

soft guard pressure decomposition은 repeated normal proxy 0.256, high row-count normal proxy 0.020,
period-end normal background 0.496, single-row high-amount normal proxy 0.000이다. pressure guard는
repeated-normal pressure를 0으로 낮추지만 TOP500 coverage가 22로 크게 떨어져 adoption 후보가 아니다.
q95 miss truth docs는 137건, near-q95는 64건, strong document context backlog는 25건이다. q95 miss는
future validation backlog로만 남기고 case로 승격하지 않는다.

Phase 5 historical decision은 `production_top_features_connected=true`, `evidence_quality_improved=true`,
`best_defensive_companion_surface=hybrid_with_soft_repeated_normal_guard`,
`best_upper_bound_surface=hybrid_row_count_blended_surface_upper_bound`,
`production_adoption=false`, `q95_gate_change_recommended=false`였다. 이 단계에서는 product default 변경을 하지 않았다.

### 9.8.4 Phase 6 fixed5-compatible slice stability

`artifacts/unsupervised_soft_guard_stability_fixed5_20260530.json`은 fixed5_normalcal5를 primary validation
dataset으로 두고 year/quarter/month/business-process bucket/GL-account bucket slice 74개에서 soft guard
계열의 pressure와 review burden을 점검한다. fixed4는 known-broken DataSynth이므로 validation 기준에서
제외한다.

| surface | slice count | current-or-better TOP500 | pressure below native | pressure <= 0.30 | best TOP500 | worst pressure |
|---|---:|---:|---:|---:|---:|---:|
| native_row_queue | 74 | 74 | 74 | 2 | 110 | 1.000 |
| hybrid_with_soft_repeated_normal_guard | 74 | 74 | 65 | 3 | 150 | 1.000 |
| soft_guard_with_row_count_context | 74 | 74 | 63 | 3 | 200 | 1.000 |
| hybrid_row_count_blended_surface_upper_bound | 74 | 74 | 48 | 0 | 246 | 1.000 |
| pressure_guard_surface | 74 | 54 | 74 | 31 | 91 | 1.000 |

soft guard는 fixed5-compatible slice 전부에서 native row queue보다 TOP500이 같거나 높고, 65/74 slice에서
native보다 pressure가 낮다. 따라서 review-surface adoption candidate로 볼 수 있다. 다만 pressure <= 0.30
slice가 3/74뿐이고 worst pressure가 1.0이므로 repeated-normal pressure는 아직 product default 수준으로
안정적이라고 보기 어렵다. `soft_guard_with_row_count_context`는 recall이 더 높지만 pressure 안정성이
soft guard보다 약해 secondary surface로 둔다. upper-bound hybrid는 계속 product default 금지다.
pressure_guard는 pressure는 낮추지만 recall 손실이 커 reject한다.

q95 backlog는 fixed5 slice에 과도하게 한 곳에 몰려 있지는 않다. q95 backlog concentration은 0.1314,
slice max q95 miss는 90, near-q95 max는 33, strong-context max는 14다. q95 gate change는 계속 권고하지
않는다. Phase 6 historical decision은 `adoption_candidate=true`, `production_adoption=false`,
`recommended_product_role=document_companion_review_surface`였다. v3.1 이후 product decision은 아래 Phase 8
owner-role 재해석과 기본 표시 ordering 전환으로 대체한다.

### 9.8.5 Phase 7 optional companion policy descriptor

Phase 7은 historical step이다. 당시에는 `hybrid_with_soft_repeated_normal_guard`를 production default ranking으로 채택하지 않고,
optional document companion review surface의 data path metadata만 고정했다. `PipelineResult`의
`phase2_family_policy_summary["unsupervised"]`에는 aggregate-only policy summary가 붙는다. 이 summary는
downstream/export/docs가 정책 상태를 알 수 있게 하는 descriptor이며, detector scoring, q95 gate, VAE
score/threshold, PHASE1 ranking, PHASE2 fusion, native row case ordering에 쓰지 않는다.

Policy summary 핵심 상태:

| field | value |
|---|---|
| evidence_quality_improved | true |
| top_features_connected | true |
| best defensive surface | `hybrid_with_soft_repeated_normal_guard` |
| adoption_candidate | historical true |
| production_adoption | historical false |
| recommended role | historical `document_companion_review_surface` |
| native TOP500 | 39 |
| soft guard TOP500 | 151 |
| native repeated-normal pressure | 0.716 |
| soft guard repeated-normal pressure | 0.256 |
| fixed5 slice TOP500 >= native | 74/74 |
| fixed5 slice pressure < native | 65/74 |
| blocker | fixed5-only slice validation + repeated-normal pressure instability |

Historical optional companion descriptor는 `policy_id=unsupervised_document_companion_soft_guard_v1`,
`surface_name=hybrid_with_soft_repeated_normal_guard`,
`artifact_path=artifacts/unsupervised_soft_guard_stability_fixed5_20260530.json`,
당시에는 candidate-not-default adoption state와 replaces-native-ordering=false를 기록했다.
이 값은 v3.1 default 표시 ordering 전환 이전의 historical descriptor다.

사용자용 설명 문서는 `docs/users/UNSUPERVISED_DOCUMENT_COMPANION_SURFACE.md`에 둔다. 문서 언어는
review candidate / anomaly evidence / companion surface로 제한한다.

### 9.8.6 Phase 8 action-tier incremental readiness

Phase 8은 추가 recall 튜닝 없이 optional companion surface readiness를 검증한다.
`artifacts/unsupervised_soft_guard_stability_fixed5_20260530.json`에
`soft_guard_action_tier_incremental_metrics`를 추가해 PHASE1 action-tier 밖 보완 수치를 고정했다.

| soft guard TOP-N | truth docs | PHASE1 즉시검토 밖 | PHASE1 검토대상 이상 밖 | PHASE1 후보 이상 밖 |
|---|---:|---:|---:|---:|
| TOP100 | 25 | 13 | 9 | 5 |
| TOP500 | 151 | 95 | 64 | 11 |
| TOP10000 | 483 | 270 | 188 | 47 |

PHASE1 action-tier baseline은 즉시검토 264, 검토대상 이상 354, 후보 이상 544 truth document다. Soft guard는
TOP500에서 native row queue 39보다 높은 151 truth document를 포함하고, 그중 PHASE1 즉시검토 밖 95건,
검토대상 이상 밖 64건, 후보 이상 밖 11건을 companion review surface로 보완한다.

Downstream smoke는 `phase2_family_policy_summary["unsupervised"]`가 존재해도 dashboard/export helper가
case set을 안전하게 읽는지 확인한다. V3.1 이후 product default는 soft guard family-list display ordering이며,
q95 gate와 VAE score/threshold, PHASE1 ranking, PHASE2 fusion, case generation은 변경하지 않는다.

Phase 8 결론은 v3.1 responsibility-map 이전의 all-truth broad surface baseline으로 보존한다.

| 항목 | TOP100 | TOP500 | TOP10000 |
|---|---:|---:|---:|
| soft guard truth docs | 25 | 151 | 483 |
| PHASE1 즉시검토 밖 truth docs | 13 | 95 | 270 |
| PHASE1 검토대상 이상 밖 truth docs | 9 | 64 | 188 |
| PHASE1 후보 이상 밖 truth docs | 5 | 11 | 47 |

Historical Phase 8 all-truth policy state는 `product_default=false`, `adoption_candidate=true`,
`role=document_companion_review_surface`였다. V3.1 owner-role 기준에서는 primary target 중심 UX 판단을
반영해 soft guard를 VAE family list 기본 표시 ordering으로 채택한다.

V3.2d responsibility-map 이후에는 `artifacts/unsupervised_v32_exact_owner_surface_fixed5_20260531.json`으로
debug statistical denominator / companion을 분리해 다시 읽는다. Debug denominator는 `fictitious_existence_statistical` 49건이고,
statistical companion은 395건이다. 이 측정은 v3.2d journal 직접 입력과 owner metadata exact join을
사용한다. V3.1의 `fictitious_entry` 168건 기준 수치와 scenario-level proration estimate는 historical
iteration으로만 보존한다.

| V3.2d role | Surface | TOP100 | TOP500 | TOP1000 | TOP10000 | TOP500 PHASE1 즉시검토 밖 | TOP500 PHASE1 검토대상 이상 밖 | TOP500 PHASE1 후보 이상 밖 | TOP500 pressure |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| debug denominator 49 | native row queue | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1.000 |
| debug denominator 49 | soft guard | 2 | 10 | 13 | 13 | 10 | 8 | 8 | 0.244 |
| debug denominator 49 | soft guard TOP100 context probe | 2 | 10 | 13 | 13 | 10 | 8 | 8 | 0.244 |
| debug denominator 49 | row-count context | 2 | 10 | 13 | 13 | 10 | 8 | 8 | 0.284 |
| debug denominator 49 | upper-bound hybrid | 7 | 13 | 13 | 13 | 13 | 11 | 11 | 0.746 |
| companion 395 | native row queue | 3 | 4 | n/a | 91 | 4 | n/a | n/a | n/a |
| companion 395 | soft guard | 16 | 55 | n/a | 277 | 55 | n/a | n/a | 0.182 |

따라서 VAE/unsupervised의 현재 debug-denominator 개선 의미는 제한적이다. Soft guard는 native row queue보다 낫지만,
v3.2d debug denominator 기준 TOP100 2 / 49, TOP500 10 / 49에 그친다. 이는 확정 finding 부재가 아니라 GL
row/document feature space에서 `fictitious_existence_statistical` subset이 정상 rare transaction과 강하게
분리되지 않는 feature representation / candidate separation 문제다.

`soft_guard_context_top100_probe`는 v3.2d exact 기준에서 추가 lift가 없다. `row-count context`도 recall
lift 없이 pressure만 0.244에서 0.284로 높인다. Upper-bound hybrid는 TOP100/TOP500을 조금 올리지만
pressure가 0.746으로 높아 product default 후보가 아니다.

Adoption-readiness는 `default native ordering changed`, `soft guard =
v3.2d exact-owner default document review priority`, `product default adoption=true`로 유지한다.
다만 default adoption의 근거는 단일 VAE family list UX와 native 대비 제한적 회복이며, 강한 primary
recall로 해석하지 않는다. 제품 판단은 broad statistical review contribution, repeated-normal pressure,
PHASE1 밖 보완, evidence explainability로 한다.

앞으로 VAE/unsupervised에서 모니터링할 pressure guardrail은 repeated-normal pressure, period-end normal
background, account/process concentration, single-row high-amount normal proxy다. q95 near-miss는 case로
승격하지 않고 backlog로만 추적한다. Hybrid upper-bound default adoption, q95 gate 완화, top_features의
ranking score 사용, PHASE1 prior를 VAE처럼 포장하는 해석, DataSynth를 VAE score에 맞추는 수정,
truth/owner/scenario/shortcut feature 사용, threshold/weight recall fitting은 금지한다.

### 14.9 sort 개선 제안

truth recall 을 이유로 q95 gate 를 바꾸지 않는다. PHASE2 family ranking 결합 정책도 변경하지 않는다.

감사 방어성 측면에서 추가 검토할 수 있는 선택지는 native unsupervised lane 내부 tie-break 를
`family_ecdf` 우선으로 문서화하거나, `family_score` 가 train-distribution ECDF 임을 필드명/도움말에
명확히 표시하는 것이다. 다만 fixed5 기준으로 `family_score` 자체가 이미 ECDF score 이므로 native row
case 정렬을 바로 바꿀 필요성은 낮다고 봤다. 이후 v3.1 owner-role 검증의 debug-denominator TOP500 23 / 168 -> 110 / 168
수치는 historical/debug 진단으로만 보존한다. 현재 채택 근거는 primary recall이 아니라 document-level
review contribution과 pressure 감소다. 이 변경은 ordering 변경이며 q95 gate, VAE score/threshold,
PHASE1 ranking, PHASE2 fusion은 그대로다.

---

## 15. Agent D — Duplicate native case artifact 복구

### 15.1 root cause

fixed5 입력 1,034,269행은 `duplicate_pair_artifact_max_rows=50,000`을 초과했다. 기존 구현은 이 경우
row score path는 계속 실행해 152,043개 duplicate review candidate hit를 냈지만, pair artifact path는
`input_too_large`로 전체 skip하여 `metadata["pair_artifact"]["top_pairs"] == []`가 되었다. 따라서
감사인이 확인할 수 있는 left/right pair evidence unit이 없어 native DuplicateCase가 생성되지 않았다.

### 15.2 변경 원칙

- PHASE1 `priority_score`, `composite_sort_score`, ranking은 변경하지 않았다.
- PHASE2 family ranking 결합 정책도 변경하지 않았다.
- row score hit를 case로 직접 변환하지 않는다. 대용량 입력에서는 row-score review candidate subset을
  bounded input으로 삼고, 기존 pair generator가 left/right evidence unit을 실제 생성한 경우만
  DuplicateCase 후보가 된다.
- `evidence_signature`는 계속 `sub_rule`만 사용하며 raw amount, score, threshold를 넣지 않는다.
- case-grade pair가 없으면 builder diagnostics metadata에 `weak_pair_evidence_tier`,
  `pair_index_not_joinable_to_df`, `empty_pair_artifact_top_pairs` 같은 원인을 남긴다.

### 15.3 fixed5 smoke 결과

`tools/scripts/measure_phase2_native_cases_fixed5_20260528.py` 재측정 결과
`artifacts/phase2_native_case_remeasure_fixed5_20260528.json` 기준 duplicate native `case_count=198`,
`docs_covered=145`다. TOP100/TOP500 synthetic truth coverage는 각각 22건이며, 모두
`period_end_adjustment_manipulation` scenario에 속한다. 이 결과는 truth label에 맞춘 threshold 튜닝이 아니라
case-grade pair evidence unit 복구와 artifact-only document diversity retention 결과로 해석한다.

### 15.4 2026-05-29 품질 진단

`artifacts/duplicate_native_case_quality_diagnosis_fixed5_20260529.json` 기준, duplicate row score hit
152,043건 중 truth row hit는 562건이고, duplicate score가 0보다 큰 truth document는 285건이다. 즉
truth document가 row score 단계에서 완전히 빠진 것은 아니다.

기존 TOP500 recall 0의 직접 원인은 score-only `top_pairs=500` retention 이었다. expanded retention에서는
truth-covering pair가 존재했지만, score 1.0 exact duplicate 동률 구간에서 소수 비truth 반복 문서쌍이
metadata top-N을 독점했다.

수정 후 artifact-only document diversity retention을 적용했다. row score, threshold, PHASE1 priority,
PHASE2 family ranking 결합 정책은 변경하지 않았다. 동일 진단 기준 현재 `top_pairs=500`은 209개 문서를
커버하고 그중 truth document 24개를 포함한다. native DuplicateCase는 198개이며, 145개 문서를 커버하고
truth document 22개를 포함한다.

### 15.5 Candidate-to-case attrition

2026-05-29 attrition diagnostic 기준 duplicate truth document 흐름은 다음과 같다.

| Stage | Truth documents | Prior-stage loss |
|---|---:|---:|
| row score hit | 285 | — |
| bounded candidate subset | 241 | 44 |
| generated/capped pair evidence | 217 | 24 |
| retained `top_pairs@500` | 24 | 193 |
| case-grade top pairs | 22 | 2 |
| native DuplicateCase | 22 | 0 |

주요 병목은 generated/capped pair evidence에서 metadata `top_pairs@500`으로 좁히는 retention 단계다.
weak tier 제외는 2건 수준이고, strong/moderate pair의 index join 실패, document_id 누락, case-id collapse는
관찰되지 않았다. retention cap을 진단 목적으로만 늘리면 truth document coverage는 `top_pairs@2k=76`,
`top_pairs@10k=105`, `top_pairs@50k=217`까지 증가한다. 이는 threshold 조정 근거가 아니라 top-N review
surface가 dense duplicate evidence를 얼마나 압축하는지 보여주는 aggregate 진단이다.

### 15.6 Retention candidate comparison

`artifacts/duplicate_retention_candidates_fixed5_20260529.json`은 production 정책 변경 없이 retention/ranking
후보를 diagnostic-only로 비교한다. detector threshold, row score, PHASE1 priority/ranking, PHASE2 family
fusion은 변경하지 않았다.

| Candidate | Pair truth docs | Expected DuplicateCase | Case truth docs | Weak pair ratio | Dense repeat concentration |
|---|---:|---:|---:|---:|---|
| current document diversity @500 | 24 | 198 | 22 | 60.4% | max 5 pairs/document |
| document-first @500 | 74 | 176 | 30 | 64.8% | max 1 pair/document |
| case-grade-first @500 | 24 | 500 | 24 | 0.0% | max 3 pairs/document |
| pair-diversity-score @500 | 36 | 500 | 36 | 0.0% | max 1 pair/document |
| evidence-diversity @500 | 36 | 500 | 36 | 0.0% | max 1 pair/document |
| evidence-diversity @1k | 46 | 1,000 | 46 | 0.0% | max 1 pair/document |
| evidence-diversity @2k | 46 | 2,000 | 46 | 0.0% | max 225 pairs/document |
| evidence-diversity @5k | 46 | 5,000 | 46 | 0.0% | max 1,121 pairs/document |
| tier-then-score-then-diversity @500 | 3 | 500 | 3 | 0.0% | max 3 pairs/document |
| two-stage score100/diversity500 | 28 | 455 | 28 | 9.0% | max 6 pairs/document |
| hybrid score-diversity balanced @500 | 34 | 500 | 34 | 0.0% | max 1 pair/document |
| case-grade with score floor @500 | 24 | 500 | 24 | 0.0% | max 3 pairs/document |
| document-pair cap with fill @500 | 24 | 198 | 22 | 60.4% | max 5 pairs/document |
| rule-balanced duplicate surface @500 | 24 | 169 | 22 | 66.2% | max 5 pairs/document |

해석: top-N retention 병목은 확인됐지만, 바로 production ranking을 바꾸기에는 아직 이르다. document-first는
coverage를 넓히지만 weak pair 비중이 높고, case-grade-first와 pair/evidence-diversity는 weak attrition을
줄이지만 review surface 성격이 달라진다. evidence-diversity @500은 fixed5에서 36 / 620 (5.81%)까지
오르지만, @2k/@5k에서는 case_count와 반복 정상 문서 집중이 커져 review burden 신호가 뚜렷하다.
tier-first 후보는 strong/moderate nontruth evidence가 상위권을 점유해 truth-covering pair가 밀렸고,
two-stage 후보는 pair TOP100 보존만으로 case TOP100을 보존하지 못했다. case builder 이후 evidence tier /
family score sort가 별도 병목으로 남아 있다.

Duplicate family는 production ranker 변경 없이 diagnostic baseline으로 유지한다. 병목은 generated/capped
pair evidence에서 `top_pairs` retention으로 좁히는 단계이며, evidence-diversity @500은 fixed5에서 가장 좋은
total-coverage 후보지만 audit semantics와 cross-batch validation 전까지 production 적용을 보류한다. 다음
개선은 product ranking 변경이 아니라 case-order-aware companion surface와 cross-batch diagnostic validation이다.

Case-order companion surface 진단에서는 `current TOP100 anchor + diversity fill`이 TOP100 case truth 21을
유지하면서 TOP500을 41, total case truth를 48까지 늘렸지만 case_count가 682로 커졌다. `split UI100 current /
export500 evidence`는 UI TOP100 21과 export TOP500 36을 분리해 early review surface 안정성과 broader
evidence surface를 동시에 볼 수 있게 한다. 두 후보 모두 diagnostic-only이며 production default selector,
threshold, PHASE1 ranking, PHASE2 family fusion은 변경하지 않는다.

Cross-batch companion surface check(`artifacts/duplicate_case_order_crossbatch_20260529.json`)에서도 fixed4와
fixed5_normalcal5 모두 같은 방향이다. split surface는 fixed4 UI TOP100 56을 유지하면서 export TOP500을
81→100으로, fixed5 UI TOP100 21을 유지하면서 export TOP500을 22→36으로 올린다. anchor-fill은 fixed4
TOP500 101, fixed5 TOP500 45까지 올라가지만 case_count가 각각 662/682로 커져 review burden이 더 크다.

`sidecar_contract_candidate`는 이 split surface를 schema 후보로 기록한다. UI surface는 current duplicate
case order TOP100이고, export sidecar는 evidence-diversity case-grade evidence units TOP500이다. artifact는
raw document_id, row_id, index_label, phase2_case_id를 저장하지 않고, tier/rule 분포와 coverage count만
저장한다. fixed4/fixed5 모두 export sidecar는 case-grade only지만 nontruth document coverage가 각각
894/964로 높아, 적용 전 sidecar filter 또는 grouped export summary 진단이 필요하다.

추가 export burden 진단에서는 개별 evidence unit 필터가 nontruth document coverage를 줄이지 못했다.
evidence-diversity @500 자체가 이미 문서쌍 단위로 거의 고유하고 case-grade이기 때문이다. 대신 grouped
summary sidecar는 동일 underlying evidence coverage를 유지하면서 export review unit을 fixed4 500→4~5개,
fixed5 500→4개 aggregate group으로 줄인다. 따라서 다음 후보는 개별 case filter가 아니라 grouped summary
우선 + 요청 시 bounded representative drilldown 구조다.

Bounded representative drilldown은 fixed4와 fixed5에서 방향이 갈린다. rule/tier/similarity group별 top20
대표 evidence unit은 fixed4에서 81개 pair로 70개 truth document를 커버하지만, fixed5에서는 53개 pair로
2개 truth document만 커버한다. 따라서 representative ordering은 아직 adoption 후보가 아니며, grouped
summary 자체를 primary export sidecar로 두고 drilldown은 partial sample로 표시하는 방향이 더 안전하다.

Full-evidence manifest 후보는 raw identifier 없이 group ordinal, group key, evidence ordinal range, aggregate
coverage만 저장한다. high-volume summary-first 정책(threshold 100)은 fixed4에서 122개 drilldown pair로
98개 truth document를 커버하지만, fixed5에서는 truth-covering evidence가 high-volume summary-only group에
몰려 full-drilldown truth가 0이다. 이 결과는 grouped summary가 primary evidence coverage 단위이고,
representative drilldown은 partial sample이라는 계약을 강화한다.

현재 diagnostic contract 후보는 `grouped_summary_primary_with_full_manifest`다. 이는 export review의 1차
단위를 500개 case row가 아니라 4~5개 rule/tier/similarity group으로 낮추고, full evidence population은
raw id 없이 group ordinal/evidence ordinal range로 표현한다. Production default selector와 case order에는
아직 연결하지 않는다.

### 15.7 PHASE1 TOP-N uplift 기준 재해석

2026-05-29 추가 진단은 duplicate 개선 방향을 broad recall이 아니라 PHASE1 상단 보완성으로 다시 측정했다.
산출물은 `artifacts/duplicate_phase1_uplift_fixed5_20260529.json`이며, stored PHASE1 case order에서
document별 최소 case rank를 aggregate bucket으로만 사용한다. raw document id, row id, phase2 case id는
artifact에 저장하지 않는다.

fixed5 PHASE1 기준선:

| PHASE1 bucket | truth documents |
|---|---:|
| TOP100 | 246 |
| 101-500 | 84 |
| 501-1000 | 52 |
| 1001+ | 162 |
| Not in PHASE1 cases | 76 |

Duplicate native surface를 PHASE1 TOP100 uplift 기준으로 보면 이전 total-coverage 판단과 결론이 달라진다.

| Duplicate surface | TOP100 truth docs | TOP100 truth outside PHASE1 TOP100 | TOP500 truth docs | TOP500 truth outside PHASE1 TOP100 | 해석 |
|---|---:|---:|---:|---:|---|
| current document-diversity | 22 | 19 | 22 | 19 | 초기 review surface 보완성은 가장 좋다. |
| evidence-diversity | 8 | 3 | 36 | 8 | total coverage는 늘지만 PHASE1 상단에 이미 있던 문서 보강이 많다. |
| current TOP100 anchor + diversity fill | 22 | 19 | 42 | 19 | TOP100 보완성은 유지하지만 TOP500 증분은 PHASE1 TOP100 reinforcement 성격이 강하다. |
| phase1-gap case-grade diagnostic | 0 | 0 | 2 | 2 | PHASE1 rank gap만으로 올리면 duplicate evidence surface 품질이 무너진다. |

따라서 duplicate는 지금 상태에서 production default를 evidence-diversity로 바꾸면 안 된다.
evidence-diversity는 export/sidecar coverage 후보로 남기되, auditor first-review TOP100은 current
document-diversity order가 PHASE1 TOP100 밖 duplicate-like review candidate를 더 잘 보완한다. 다음
iteration은 recall을 더 키우는 것이 아니라 current TOP100의 PHASE1-uplift 장점을 보존하면서 weak pair
pressure와 export burden을 낮출 수 있는 duplicate-specific evidence feature를 cross-batch로 검증하는
방향이다.

Cross-batch PHASE1-uplift 진단(`artifacts/duplicate_phase1_uplift_crossbatch_20260530.json`)에서는
fixed4와 fixed5가 서로 다른 tradeoff를 보인다. fixed4에서는 evidence-diversity TOP500이 PHASE1 TOP100
밖 truth 90건을 포함해 current TOP500의 74건보다 높지만, fixed5에서는 evidence-diversity TOP500이 8건에
그쳐 current TOP100/500의 19건보다 낮다. PHASE1-gap case-grade 후보는 fixed4 TOP500 88건으로 좋아
보이지만 fixed5 TOP500 2건으로 붕괴한다. 따라서 PHASE1 rank gap을 직접 selector로 쓰는 방향은 batch
안정성이 부족하다. 현재 판단은 first-review TOP100은 current document-diversity를 유지하고,
evidence-diversity는 grouped export/sidecar 후보로만 유지하는 것이다.

### 10.8 Remaining generated potential

Phase 5 진단(`artifacts/duplicate_remaining_potential_fixed5_20260530.json`)은 current first-review surface가
놓친 remaining generated potential을 aggregate-only로 분해했다. fixed5에서 generated/capped pair evidence
안에 있는 PHASE1 TOP100 밖 truth potential은 24건이고, current Duplicate TOP100이 이미 19건을 포함한다.
남은 headroom은 5건이다. PHASE1 TOP500 밖 기준으로는 generated potential 8건 중 current가 5건을 포함해
missed headroom은 3건이다.

Missed 5건의 진단 분류는 `weak_pair_only=3`, `artifact_cap_boundary=2`다. captured set은 related pair
661개 중 case-grade ratio 0.861, same-partner ratio 0.861인 반면, missed set은 related pair 113개 중
case-grade ratio 0.009, same-partner ratio 0.009다. 두 그룹 모두 period-end context가 강하므로
period-end feature만으로 올리는 것은 duplicate-specific ordering 근거가 되지 않는다.

후보는 2개만 비교했다. `current_plus_case_grade_sidecar`는 first-review TOP100을 바꾸지 않아 PHASE1 TOP100
밖 truth 19건을 유지하고, 별도 sidecar에서 case-grade-only evidence TOP500 truth 36건을 제공한다.
`current_with_missed_potential_tiebreak`는 weak pair를 제거하지만 current captured 19건을 유지하지 못하고
TOP100/TOP500 truth가 0으로 무너져 rejection 처리했다. fixed4 sanity에서도 같은 tiebreak는 current
captured set을 잃는다.

판단: duplicate first-review ranking 변경은 하지 않는다. 남은 fixed5 headroom은 작고 대부분 weak/boundary
제약이므로 weight tuning 대상이 아니다. 개선 여지는 product ranking이 아니라 current first-review 유지 +
case-grade export/sidecar 품질 개선, grouped summary, full-evidence manifest 쪽이다.

### 10.9 Product policy summary and sidecar descriptor

Phase 6에서는 위 결정을 `PipelineResult.phase2_family_policy_summary["duplicate"]`에 aggregate-only metadata로
붙인다. 이 metadata는 detector/scoring/fusion/UI layout 입력이 아니며, `case_set.duplicate_cases` 순서를
대체하지 않는다.

Policy summary:

| Field | Value |
|---|---|
| primary_product_role | pair_evidence_first_review_with_case_grade_sidecar |
| production_first_review_ranking_changed | false |
| native_ordering_changed | false |
| production_adoption | true, current first-review policy only |
| recommended_first_review_surface | current_document_diversity_top_500 |
| recommended_sidecar_surface | current_plus_case_grade_sidecar |
| weak_pair_promotion_allowed | false |

Sidecar descriptor:

| Field | Value |
|---|---:|
| sidecar_surface_id | duplicate_case_grade_sidecar_v1 |
| sidecar_case_grade_only | true |
| sidecar_weak_pair_ratio | 0.0 |
| sidecar_top500_truth_docs | 36 |
| first_review_top100_captured_outside_phase1_top100 | 19 |
| missed_potential_count | 5 |
| weak_pair_only_missed_count | 3 |
| artifact_cap_boundary_missed_count | 2 |
| raw_identifier_leak_check | 0 |

사용자 설명 문서는 `docs/users/DUPLICATE_PAIR_EVIDENCE_SURFACE.md`에 추가했다. 표현은 duplicate review
candidate / pair evidence / sidecar surface 기준이며 확정 표현을 쓰지 않는다.

### 10.10 V3.1 duplicate-primary readiness 심화

Responsibility-map v3.1과 `fixed5_dupmeta` 기준 Duplicate primary 후보는 76건 / 38 pair group이다.
다만 native `DuplicateCase` primary는 0건이며, 현재 결론은 primary recall 0%가 아니라
`pending_pair_evidence_validation`이다. 관련 artifact는
`artifacts/duplicate_v31_primary_readiness_fixed5_dupmeta_20260531.json`이다.

고정된 attrition:

| Stage | Primary docs |
|---|---:|
| duplicate primary candidate | 76 |
| duplicate row score > 0 | 28 |
| no row score | 48 |
| bounded candidate subset | 0 |
| generated pair evidence | 0 |
| retained top_pairs | 0 |
| case-grade top_pairs | 0 |
| DuplicateCase | 0 |

심화 원인 분해:

| Gap | Docs | Pair groups | Aggregate profile |
|---|---:|---:|---|
| no observable row score | 48 | 24 | 1-3 day shift, near amount, exact reference, medium text, partner match 1.0, same account 0.0, P2P |
| low-score `L2-03d` below candidate floor | 28 | 14 | same profile, row score 0.428571, candidate floor 0.598986, floor gap 0.170414 |

Non-oracle sidecar probes still do not reach the primary docs:

| Probe | Candidate docs | Primary docs entering | Primary pair docs | Case-grade primary docs | Read |
|---|---:|---:|---:|---:|---|
| `l2_03d_stratified_low_score_sample` | 10,000 | 0 | 0 | 0 | current observable sample misses primary docs |
| `rule_balanced_duplicate_candidate_sample` | 10,000 | 0 | 0 | 0 | rule-balanced sample still misses primary docs |
| `duplicate_primary_metadata_probe_sample` | 76 | 76 | 76 | 76 | oracle feasibility only, not product selector |

따라서 다음 개선 방향은 product first-review ranking, row-score threshold, `top_pairs` cap, weak-pair
promotion이 아니다. 올바른 다음 작업은 48건 no-row-score primary docs의 observable feature coverage와,
28건 lower-score `L2-03d` docs가 truth metadata 없이 pair evidence path에 들어갈 수 있는지를 진단하는
것이다. PHASE1 ranking, PHASE2 fusion, Duplicate default ordering은 유지한다.

### 10.11 2026-05-31 병렬 성능개선 진단

세 family에 대해 diagnostic-only 개선 옵션을 분리했다. Production detector/gate/ranking/fusion,
PHASE1 ranking, weak-pair gate는 변경하지 않았다.

| Family | Artifact | 핵심 결과 | 판단 |
|---|---|---|---|
| Relational | `artifacts/relational_v31_improvement_options_20260531.json` | adopted surface TOP500 92, 1:4 upper-bound TOP500 100 | 1:4는 recall 상한이지만 review-surface policy 냄새가 강해 기본값 변경 없음 |
| VAE / Unsupervised | `artifacts/unsupervised_v31_improvement_options_20260531.json` | soft guard TOP500 110, soft+row-count context TOP500 114, upper-bound TOP100 59 | 현 soft guard 유지. 추가 +4는 pressure 악화가 있어 diagnostic-only |
| Duplicate | `artifacts/duplicate_v31_feature_gap_experiment_20260531.json` | lower-score L2-03d sample 0, observable document-profile sample primary pair 75 / case-grade 74 | top_pairs가 아니라 candidate feature path 문제. 단 review burden 10,000 docs라 product 적용 전 guard 필요 |

Duplicate 신규 실험은 truth/owner metadata를 selector에 쓰지 않고, observable document profile
(`P2P`, reference 존재, trading partner 존재, 2-3 line document, amount rank)만으로 bounded sidecar를
만든다. 이 후보는 76 primary candidate 중 75건을 pair evidence까지, 74건을 case-grade primary evidence까지
올렸다. 다만 `10,000` candidate docs 중 non-primary가 `9,924`건이라 바로 default case ordering으로
승격하지 않는다. 다음 단계는 이 observable document-profile sidecar를 더 낮은 burden으로 줄이는 guard
검증이다.
