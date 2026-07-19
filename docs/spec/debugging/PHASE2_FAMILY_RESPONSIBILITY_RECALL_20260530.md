# PHASE2 family responsibility-map recall — 2026-05-30

## 목적

`fixed5_normalcal5`의 620개 synthetic truth document를 detector 결과가 아니라 DataSynth truth semantics 기준으로 먼저 owner family set에 배정한 뒤, 기존 PHASE1/PHASE2 recall을 owner-set denominator로 다시 읽는 diagnostic-only 측정이다.

이 작업은 production ranking, gate, fusion, detector threshold를 변경하지 않는다.

## 산출물

- Script: `tools/scripts/measure_phase2_family_responsibility_recall_fixed5_20260530.py`
- Artifact: `artifacts/phase2_family_responsibility_recall_fixed5_20260530.json`
- Test: `tests/modules/test_services/test_phase2_family_responsibility_recall.py`

## Owner assignment policy

Owner는 단일 primary owner가 아니다. 한 truth case는 0개, 1개, 또는 여러 owner를 가질 수 있다. 명확한 owner가 없으면 `no_clear_owner`를 허용한다.

Owner assignment 입력은 sanitized truth summary로 제한했다.

- allowed: DataSynth scenario/category, injected pattern, sanitized account/process/category-level attributes, semantic context flags
- forbidden: detector output, PHASE1/PHASE2 score, rank, matched result, raw document identifier, row identifier, index label, PHASE2 case identifier

기본 산출물은 deterministic/rule-only mode로 생성했다. LLM-assisted path는 strict Pydantic structured output schema를 사용하도록 구현했지만 기본 실행과 unit test에서는 live network call을 하지 않는다.

## Owner distribution

| Owner | Truth docs |
|---|---:|
| phase1 | 586 |
| intercompany | 34 |
| relational | 139 |
| duplicate | 92 |
| timeseries | 113 |
| unsupervised | 289 |
| no_clear_owner | 0 |

Multi-owner truth docs: 520  
No-clear-owner truth docs: 0  
Owner confidence: high 155, medium 465, low 0

## Portfolio recall vs owner-set recall

620 전체 denominator recall은 portfolio contribution이다. Owner-set denominator recall은 family target performance다.

Portfolio contribution, native TOP500 기준:

| Family | Matched / 620 | Recall |
|---|---:|---:|
| PHASE1 immediate | 264 / 620 | 42.58% |
| PHASE1 review or higher | 354 / 620 | 57.10% |
| PHASE1 candidate or higher | 544 / 620 | 87.74% |
| intercompany | 34 / 620 | 5.48% |
| relational | 19 / 620 | 3.06% |
| duplicate | 22 / 620 | 3.55% |
| timeseries | 0 / 620 | 0.00% |
| unsupervised | 39 / 620 | 6.29% |

Owner-set target recall:

| Owner set | Matching family matched / owner docs | Recall |
|---|---:|---:|
| intercompany | 34 / 34 | 100.00% |
| relational | 17 / 139 | 12.23% |
| duplicate | 22 / 92 | 23.91% |
| timeseries | 0 / 113 | 0.00% |
| unsupervised | 39 / 289 | 13.49% |

PHASE1 candidate-or-higher owner-set recall:

| Owner set | PHASE1 matched / owner docs | Recall |
|---|---:|---:|
| phase1 | 511 / 586 | 87.20% |
| intercompany | 33 / 34 | 97.06% |
| relational | 99 / 139 | 71.22% |
| duplicate | 84 / 92 | 91.30% |
| timeseries | 105 / 113 | 92.92% |
| unsupervised | 261 / 289 | 90.31% |

## Cross-owner evidence contribution

| Family | Expected-owner matches | Secondary evidence matches | no_clear_owner matches |
|---|---:|---:|---:|
| intercompany | 34 | 0 | 0 |
| relational | 17 | 2 | 0 |
| duplicate | 22 | 0 | 0 |
| timeseries | 0 | 0 | 0 |
| unsupervised | 39 | 0 | 0 |

## PHASE1 action-tier outside complement

The outside action-tier counts are retained from the existing aggregate action-tier artifact. The owner-set matched count is measured separately from the detector-blind owner map.

| Family | Owner docs | Matched owner docs | Outside PHASE1 immediate | Outside PHASE1 review+ | Outside PHASE1 candidate+ |
|---|---:|---:|---:|---:|---:|
| intercompany | 34 | 34 | 32 | 30 | 1 |
| relational | 139 | 17 | 149 | 122 | 45 |
| duplicate | 92 | 22 | 11 | 5 | 0 |
| timeseries | 113 | 0 | 0 | 0 | 0 |
| unsupervised | 289 | 39 | 13 | 8 | 1 |

## Family interpretation

- IC locked conclusion remains: on intercompany-owned target, IC covers 34 / 34. This is IC-specific evidence strengthening, not broad 620 recall expansion.
- Relational locked conclusion remains but is now split: relationship-owned target recall is 17 / 139, while PHASE1 uplift and structural evidence companion value remain separate product arguments.
- Duplicate should be read against 92 duplicate-owned period-end/similarity targets. Current native TOP500 captures 22 / 92; next improvement remains sidecar/export evidence quality, not production rank tuning.
- Timeseries should be read against 113 timing-window targets. Native TOP500 target recall is 0 / 113, so TOP100 failure is a target-surface ranking/role issue, not a full-portfolio conclusion.
- Unsupervised should be read against 289 broad-statistical targets. Native TOP500 captures 39 / 289; document companion role remains separate from native row queue adoption.

## Leakage guard result

Artifact self-check:

- raw identifier leak count: 0
- forbidden raw identifier key count: 0
- PHASE2 case-id-like token count: 0
- owner assignment detector output inspection: not used by construction
- owner assignment score/rank inspection: not used by construction
- owner assignment matched-result inspection: not used by construction
- owner assignment artifact independent of recall artifact: true

## Verification

Commands run:

```powershell
uv run python tools/scripts/measure_phase2_family_responsibility_recall_fixed5_20260530.py
uv run pytest tests/modules/test_services/test_phase2_family_responsibility_recall.py -q
```

---

## V2 owner_role revision

2026-05-30 v2는 v1 inclusive owner set을 폐기하지 않고, `owner_roles`를 추가해 `primary` target recall과
`secondary` / `companion_context` contribution을 분리한다. 산출물은 별도 파일로 유지한다.

- Script: `tools/scripts/measure_phase2_family_responsibility_recall_v2_fixed5_20260530.py`
- Artifact: `artifacts/phase2_family_responsibility_recall_v2_fixed5_20260530.json`
- Test: `tests/modules/test_services/test_phase2_family_responsibility_recall_v2.py`

V2 role enum:

- `primary`
- `secondary`
- `companion_context`
- `baseline_review`
- `no_clear_owner`

### V1 대비 role distribution

| Owner | V1 inclusive | V2 primary | V2 secondary | V2 companion | V2 baseline |
|---|---:|---:|---:|---:|---:|
| phase1 | 586 | 397 | 0 | 0 | 223 |
| intercompany | 34 | 34 | 0 | 0 | 0 |
| relational | 139 | 29 | 110 | 0 | 0 |
| duplicate | 92 | 0 | 0 | 92 | 0 |
| timeseries | 113 | 21 | 0 | 92 | 0 |
| unsupervised | 289 | 168 | 0 | 121 | 0 |
| no_clear_owner | 0 | 0 | 0 | 0 | 0 |

V2 ambiguity metrics:

| Metric | Count |
|---|---:|
| no_clear_owner | 0 |
| review_needed | 92 |
| low_confidence | 92 |
| multi_primary | 29 |
| context_only | 0 |

`no_clear_owner=0`은 여전히 ambiguity 부재 증거가 아니다. V2에서는 duplicate primary metadata gap 때문에
92건을 `review_needed`와 `low_confidence`로 따로 표시한다.

### Primary owner target recall

| Owner | Primary docs | Matched primary docs | Recall |
|---|---:|---:|---:|
| phase1 | 397 | 350 | 88.16% |
| intercompany | 34 | 34 | 100.00% |
| relational | 29 | 0 | 0.00% |
| duplicate | 0 | 0 | n/a |
| timeseries | 21 | 0 | 0.00% |
| unsupervised | 168 | 20 | 11.90% |

Inclusive owner recall은 v1 호환 관점으로 유지한다.

| Owner | Inclusive docs | Matched inclusive docs | Recall |
|---|---:|---:|---:|
| phase1 | 620 | 544 | 87.74% |
| intercompany | 34 | 34 | 100.00% |
| relational | 139 | 17 | 12.23% |
| duplicate | 92 | 22 | 23.91% |
| timeseries | 113 | 0 | 0.00% |
| unsupervised | 289 | 39 | 13.49% |

### Evidence contribution

| Family | Primary matched | Secondary matched | Companion matched |
|---|---:|---:|---:|
| intercompany | 34 | 0 | 0 |
| relational | 0 | 17 | 0 |
| duplicate | 0 | 0 | 22 |
| timeseries | 0 | 0 | 0 |
| unsupervised | 20 | 0 | 19 |

PHASE1 action-tier outside primary target estimate:

| Family | Matched primary | Outside PHASE1 immediate | Outside PHASE1 review+ | Outside PHASE1 candidate+ |
|---|---:|---:|---:|---:|
| intercompany | 34 | 32 | 30 | 1 |
| relational | 0 | 0 | 0 | 0 |
| duplicate | 0 | 0 | 0 | 0 |
| timeseries | 0 | 0 | 0 | 0 |
| unsupervised | 20 | 7 | 4 | 1 |

위 outside 수치는 aggregate-only estimate다. Owner assignment에는 detector output, score, rank, matched result를
사용하지 않는다.

### Duplicate metadata gap

V2는 `period_end_adjustment_manipulation` 92건을 duplicate primary denominator로 두지 않는다. 현재 truth
metadata에는 explicit duplicate-like injected metadata가 부족하다.

`duplicate_primary_denominator_status = "metadata_insufficient"`

DataSynth backlog:

- `injected_duplicate_like` boolean 필요
- `duplicate_pair_semantic_group` 필요
- reference / amount / text similarity injection source 필요

따라서 duplicate는 현재 primary target recall이 아니라 companion/context evidence contribution으로 읽는다.

### Timeseries role lock alignment

`docs/spec/PHASE2_TIMESERIES_ROLE_LOCK.md`와 정합되게 period-end adjustment 92건은 timeseries primary가 아니다.

- `period_end_adjustment_timeseries_primary_count = 0`
- `timeseries primary = 21` timing-only / after-hours window target
- `period_end_adjustment role = companion_context`

### V2 interpretation

- IC locked 결론은 유지된다. Primary intercompany target 34 / 34다.
- Relational은 v1의 139 denominator 중 primary 29, secondary 110으로 분리된다. Native TOP500은 relational primary target을 잡지 못했고, 기존 17건은 secondary evidence contribution이다.
- Duplicate는 primary denominator pending이다. 지금 22건은 duplicate companion/context contribution으로만 해석한다.
- Timeseries denominator는 113에서 primary 21로 정정된다. Period-end 92건은 TS context lane이다.
- Unsupervised는 primary 168, companion 121로 분리된다. VAE 다음 방향은 primary broad-statistical target과 companion surface를 따로 검증하는 것이다.

---

## V2.1 policy cleanup — audit-rule-first / evidence-companion

2026-05-30 v2.1은 v2 `owner_roles` schema를 유지하되, 남은 정책 비대칭을 정리한다. V1/V2 artifact는 보존하고 v2.1 artifact를 별도로 생성한다.

- Script: `tools/scripts/measure_phase2_family_responsibility_recall_v21_fixed5_20260530.py`
- Artifact: `artifacts/phase2_family_responsibility_recall_v21_fixed5_20260530.json`
- Test: `tests/modules/test_services/test_phase2_family_responsibility_recall_v2.py`

정책 정정:

- `fictitious_entry`: `phase1=primary`, `unsupervised=companion_context`
- `expense_capitalization`: `phase1=primary`, `unsupervised=companion_context` 유지
- `unsupervised primary`: explicit broad-statistical-only owner metadata가 있을 때만 부여. 현재 fixed5에는 없어 pending.
- `approval_sod_bypass`: `phase1=primary`, `relational=secondary`
- `period_end_adjustment_manipulation`: `timeseries=companion_context`, `duplicate=companion_context/review_needed`

V2 대비 V2.1 role distribution:

| Owner | V2 primary | V2.1 primary | V2.1 secondary | V2.1 companion | V2.1 baseline |
|---|---:|---:|---:|---:|---:|
| phase1 | 397 | 565 | 0 | 0 | 55 |
| intercompany | 34 | 34 | 0 | 0 | 0 |
| relational | 29 | 0 | 139 | 0 | 0 |
| duplicate | 0 | 0 | 0 | 92 | 0 |
| timeseries | 21 | 21 | 0 | 92 | 0 |
| unsupervised | 168 | 0 | 0 | 289 | 0 |

V2.1 primary owner target recall:

| Owner | Primary docs | Matched | Recall |
|---|---:|---:|---:|
| phase1 | 565 | 490 | 86.73% |
| intercompany | 34 | 34 | 100.00% |
| relational | 0 | 0 | n/a |
| duplicate | 0 | 0 | n/a |
| timeseries | 21 | 0 | 0.00% |
| unsupervised | 0 | 0 | n/a |

V2.1 companion lifecycle recall:

| Metric | Truth docs | Matched | Recall |
|---|---:|---:|---:|
| relational secondary | 139 | 17 | 12.23% |
| duplicate companion | 92 | 22 | 23.91% |
| timeseries companion | 92 | 0 | 0.00% |
| unsupervised companion | 289 | 39 | 13.49% |

이 companion lifecycle metric은 primary target recall이 아니며, product default 채택 근거로 단독 사용하지 않는다.

PHASE1 confidence split:

- `phase1_primary_truth_docs = 565`
- `phase1_primary_high_medium_confidence_truth_docs = 473`
- `phase1_primary_low_confidence_truth_docs = 92`
- `phase1_primary_low_confidence_reason = period_end_adjustment companion/metadata uncertainty`

phase1 primary 565는 responsibility taxonomy의 책임 정의이고, portfolio cumulative recall 544/620은 detector 성과다. 두 수치는 의미가 다르다.

V2.1 ambiguity / metadata:

- `multi_primary = 0`, `multi_primary_overlap_cases = []`
- `review_needed = 92`, `low_confidence = 92`
- `no_clear_owner = 0`은 ambiguity 부재가 아니라 rule structure 결과다.
- `relational_primary_denominator_status = pending_relationship_primary_metadata`
- `duplicate_primary_denominator_status = metadata_insufficient`
- `unsupervised_primary_denominator_status = pending_explicit_broad_statistical_only_metadata`

Pending 해제 조건:

- Relational primary pending 해제: explicit relationship-primary injected semantics 또는 R-family detector spec이 primary target으로 정의될 때.
- Duplicate primary pending 해제: DataSynth truth metadata에 `injected_duplicate_like`, `duplicate_pair_semantic_group`, similarity injection source가 추가될 때.
- Unsupervised primary pending 해제: `broad_statistical_only owner metadata`가 추가될 때.
- Timeseries primary: 현재 timing-only 21 유지. period_end 92는 companion_context.

V2.1 해석:

- IC locked 결론은 유지된다.
- Relational은 primary target family를 포기하지 않는다. 다만 이 iteration에서는 explicit relationship-primary denominator가 없어 approval/user edge evidence를 interim relationship review-surface metric으로만 분리한다.
- Duplicate는 primary denominator가 계속 pending이다. DataSynth duplicate-like metadata 보강 전에는 primary recall을 산출하지 않는다.
- Timeseries primary denominator는 21로 유지하고, period-end 92건은 TS companion context로 유지한다.
- VAE/unsupervised는 현재 fixed5에서 primary target이 아니라 broad statistical companion role이다.

---

## V3 fixed5_ownermeta_ic — family-specific primary flags

2026-05-30 v3는 `datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic`의 family-specific primary flags를 owner denominator traceability artifact로 사용한다. v3 relocated owner policy into DataSynth metadata for traceability. v3/v3.1 are diagnostic responsibility maps, not production detector changes.

- Script: `tools/scripts/measure_phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.py`
- Artifact: `artifacts/phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.json`
- Test: `tests/modules/test_services/test_phase2_family_responsibility_recall_v3.py`

`truth_owner_primary`는 legacy representative summary이며 exclusive owner가 아니다. v3 denominator는 family-specific primary flags를 사용한다.

Primary denominator:

| Owner | Primary docs | Source |
|---|---:|---|
| phase1 | 192 | `truth_owner_primary == "phase1"` fallback |
| intercompany | 34 | `injected_intercompany_primary` |
| relational | 63 | `injected_relationship_edge_primary` |
| duplicate | 76 | `duplicate_primary_target` / `injected_duplicate_like` |
| timeseries | 21 | `injected_timing_primary` |
| unsupervised | 268 | `broad_statistical_only_owner` |

Co-primary overlap:

- `intercompany ∩ relational = 34`
- circular related-party 34건은 IC primary이면서 relational primary다.
- Portfolio total에서는 overlap을 deduplicate해야 하며, family table에서는 overlap을 표시한다.

Native TOP500 primary recall:

| Owner | Primary docs | Matched | Recall |
|---|---:|---:|---:|
| phase1 | 192 | 184 | 95.83% |
| intercompany | 34 | 34 | 100.00% |
| relational | 63 | 9 | 14.29% |
| duplicate | 76 | 0 | 0.00% |
| timeseries | 21 | 0 | 0.00% |
| unsupervised | 268 | 20 | 7.46% |

Context / companion contribution:

| Metric | Truth docs | Matched | Recall |
|---|---:|---:|---:|
| relational secondary | 76 | 8 | 10.53% |
| duplicate context | 0 | 0 | n/a |
| timeseries context | 92 | 0 | 0.00% |
| unsupervised companion | 239 | 17 | 7.11% |

Data quality / policy checks:

- truth docs = 620
- anomaly label docs = 620
- expected primary counts match
- non-circular injected_intercompany_primary count = 0
- circular injected_intercompany_primary count = 34
- raw identifier leak count = 0
- forbidden identifier key count = 0
- detector output / score / rank / TOP-N matched result는 owner assignment에 사용하지 않는다.

Decision summary:

- IC primary denominator is available, co-primary with relational for circular 34.
- Relational primary denominator is available via relationship edge metadata.
- Duplicate primary denominator is available via duplicate metadata.
- TS primary denominator is available via timing metadata; period-end 92 remains context.
- VAE primary denominator is available via `broad_statistical_only_owner`; companion remains separate.
- Phase1 uses legacy summary fallback and needs future explicit `phase1_primary_owner` flag.

## V3.1 policy cleanup — audit-rule-first reconciliation

v3.1 reconciles the DataSynth metadata with audit-rule-first responsibility policy. v3 artifact는 보존하고 v3.1 artifact를 별도로 생성한다. DataSynth family metadata는 owner 후보 신호이며, 감사 의미와 충돌하는 scenario-wide stamp는 audit-rule-first policy가 override한다.

Canonical status:

- v3.3d = current canonical responsibility map candidate
- v3.3b = historical responsibility map
- v3.2d = historical responsibility map
- v1/v2/v2.1/v3/v3.1 = historical iterations
- v3 = traceability experiment, not final policy
- policy_model = `audit_rule_first_reconciled_with_datasynth_family_flags`
- interpretation = `audit-rule-first scenario policy with DataSynth family flags as candidate signals`

- Script: `tools/scripts/measure_phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.py`
- Artifact: `artifacts/phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json`
- Test: `tests/modules/test_services/test_phase2_family_responsibility_recall_v31.py`

V3.1 primary denominator:

| Owner | Primary docs | Policy |
|---|---:|---|
| phase1 | 397 | audit-rule-first derived policy |
| intercompany | 34 | IC metadata 유지 |
| relational | 34 | circular related-party co-primary only |
| duplicate | 0 | pending pair evidence validation |
| timeseries | 21 | timing primary metadata 유지 |
| unsupervised | 168 | fictitious-entry broad statistical primary |

V3.1 companion/context denominator:

| Lane | Truth docs | Role |
|---|---:|---|
| relational secondary | 105 | approval 29 + embezzlement 76 |
| duplicate companion | 76 | embezzlement duplicate-like evidence companion |
| timeseries context | 92 | period-end context |
| unsupervised companion | 339 | statistical companion/context after suspense reconciliation |

V3.1 native TOP500 primary recall:

| Owner | Primary docs | Matched | Recall |
|---|---:|---:|---:|
| phase1 | 397 | 350 | 88.16% |
| intercompany | 34 | 34 | 100.00% |
| relational | 34 | 9 | 26.47% |
| duplicate | 0 | 0 | pending |
| timeseries | 21 | 0 | 0.00% |
| unsupervised | 168 | 20 | 11.90% |

Policy diff:

- `approval_sod_bypass`: phase1 primary + relational secondary. Relational primary는 approval-edge product spec이 잠긴 뒤에만 허용한다.
- `embezzlement_concealment`: phase1 primary + duplicate/relational/unsupervised companion.
- `suspense_account_abuse`: phase1 primary + unsupervised companion.
- `fictitious_entry`: unsupervised primary 유지. v2.1에서는 expense와 함께 PHASE1 primary로 통일했지만, v3.1은 existence assertion과 classification error를 분리한다. `fictitious_entry`는 거래 실재성 자체가 불명확한 outlier/existence assertion 문제이므로 VAE primary가 audit-defensible하다.
- `expense_capitalization`: phase1 primary 유지. 실재 거래는 존재하지만 계정분류가 잘못된 classification error이므로 PHASE1 rule/policy review가 primary다.
- `circular_related_party_transaction`: intercompany + relational co-primary 유지.
- `period_end_adjustment_manipulation`: phase1 primary, timeseries context 유지.

---

## V3.2d fixed5_ownermeta_v32d — historical responsibility map

2026-05-31 v3.2d는 `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d`의 owner metadata taxonomy를 사용하고 suspense override와 VAE 49 exact join을 반영한 historical responsibility map이다. v3.3b가 current canonical responsibility map candidate가 되면서 v3.2d는 보존용 baseline으로 남긴다. 이 산출물은 denominator / owner-role 정합성 재정의이고 production ranking, gate, fusion, PHASE1 ranking, PHASE2 family ordering을 변경하지 않는다.

Policy cleanup:

- suspense는 rule-first로 lock한다. `suspense_account_abuse` 100건은 PHASE1 primary + statistical companion이다.
- Fictitious split은 data-derived truth subtype이다.
- within-scenario split recall은 exact join 없으면 estimate로만 표시한다.
- VAE 49 exact TOP500 recall = 5 / 49.

- Script: `tools/scripts/measure_phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.py`
- Artifact: `artifacts/phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.json`
- Test: `tests/modules/test_services/test_phase2_family_responsibility_recall_v32.py`

V3.2d primary denominator:

| Owner | Primary docs | Source / status |
|---|---:|---|
| phase1 | 516 | `truth_owner_primary == "phase1"` + suspense policy override |
| intercompany | 34 | `injected_intercompany_primary == true` |
| relational | 0 | `relationship_primary_target == true`; no primary denominator |
| duplicate | 0 | `duplicate_primary_target == true`; no primary denominator |
| timeseries | 21 | `injected_timing_primary == true` |
| unsupervised / VAE | 49 | `fictitious_existence_statistical`; suspense excluded |

V3.2d companion/context denominator:

| Lane | Truth docs | Role |
|---|---:|---|
| relational companion | 139 | relationship evidence companion |
| duplicate companion | 111 | duplicate-like evidence companion |
| timeseries context | 92 | period-end timing context |
| statistical companion | 395 | statistical evidence companion, including suspense 100 |

Native TOP500 primary recall:

| Owner | Primary docs | Matched | Recall / status |
|---|---:|---:|---|
| phase1 candidate-or-higher | 516 | 450 | 87.21% |
| intercompany | 34 | 34 | 100.00% |
| relational | 0 | 0 | pending / no primary denominator |
| duplicate | 0 | 0 | pending / no primary denominator |
| timeseries | 21 | 0 | 0.00% |
| unsupervised / VAE | 49 | 5 | 10.20% |

Companion/context contribution, native TOP500 기준:

| Lane | Truth docs | Matched | Recall |
|---|---:|---:|---:|
| relational companion | 139 | 17 | 12.23% |
| duplicate companion | 111 | 0 | 0.00% |
| timeseries context | 92 | 0 | 0.00% |
| statistical companion | 395 | n/a | scenario-level companion estimate only |

PHASE1 action-tier outside estimate:

| Lane | Denominator | Family TOP500 matched | Outside immediate add | Outside review+ add | Outside candidate+ add |
|---|---:|---:|---:|---:|---:|
| intercompany primary | 34 | 34 | 32 | 30 | 1 |
| relational primary | 0 | 0 | 0 | 0 | 0 |
| duplicate primary | 0 | 0 | 0 | 0 | 0 |
| timeseries primary | 21 | 0 | 0 | 0 | 0 |
| unsupervised primary | 49 | 6 estimated | 2 | 1 | 0 |
| relational companion | 139 | 17 | 10 | 8 | 3 |
| duplicate companion | 111 | 0 | 0 | 0 | 0 |
| timeseries context | 92 | 0 | 0 | 0 | 0 |
| statistical companion | 395 | 31 estimated | 10 | 6 | 1 |

Policy interpretation:

- relational primary 0은 성능 실패도 product 역할 포기도 아니다. fixed5 v3.2d에는 relationship-primary/co-primary denominator가 없어 owned recall을 산출하지 않는 상태이며, relational product surface는 유지한다.
- duplicate primary 0은 failure가 아니다. fixed5 v3.2d에는 duplicate-primary scenario가 없고, duplicate-like evidence는 companion 111로 추적한다.
- Circular related-party 34건은 IC primary이며 relationship companion이다. v3.2d에서는 relational co-primary로 세지 않는다.
- Approval/SOD 29건은 PHASE1 primary + relationship companion이다.
- Embezzlement 76건은 PHASE1 primary + relationship/duplicate/statistical companion이다.
- Suspense 100건은 PHASE1 primary + statistical companion으로 override한다. long-aged suspense balance는 명시적 statistical-only subtype이 없으면 rule/account-policy primary다.
- VAE primary 49는 `fictitious_existence_statistical`만 포함한다. Statistical companion 395는 primary target recall과 분리한다.
- VAE 49 exact TOP500 recall = 5 / 49. 기존 6/49는 `fictitious_entry` scenario count를 49/168로 나눈 estimated proration이었고 공식 수치에서 제외한다.
- Fictitious taxonomy는 `fictitious_existence_statistical` 49건만 VAE primary이고, `fictitious_account_policy` 44건, `fictitious_period_end_like` 40건, `fictitious_duplicate_like` 35건은 PHASE1 primary + companion evidence다.
- PHASE1 primary 516은 responsibility taxonomy의 책임 분모이고, portfolio cumulative recall 544/620은 detector 성과다. 두 수치는 의미가 다르다.

Leakage / data-quality guard:

- truth docs = 620, anomaly label docs = 620
- journal rows = 1,034,269, journal docs = 318,653, journal columns = 53
- owner/truth flags are not present in journal input columns
- primary overlap count = 0, including IC/relational primary overlap 0
- raw identifier leak count = 0
- forbidden identifier key count = 0
- detector output / score / rank / TOP-N matched result는 owner assignment에 사용하지 않는다.

---

## V3.3b fixed5_ownermeta_v33b — current canonical candidate

2026-05-31 v3.3b는 `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33b`의 family-specific owner metadata를 사용한 current canonical responsibility map candidate다. v3.2d = historical responsibility map으로 보존한다. 이 작업은 owner denominator / role 정합성 재정의이며 production ranking, gate, fusion, PHASE1 ranking, PHASE2 family ordering을 변경하지 않는다.

- Script: `tools/scripts/measure_phase2_family_responsibility_recall_v33_fixed5_ownermeta_v33b_20260531.py`
- Artifact: `artifacts/phase2_family_responsibility_recall_v33_fixed5_ownermeta_v33b_20260531.json`
- Test: `tests/modules/test_services/test_phase2_family_responsibility_recall_v33.py`

V3.3b primary denominator:

| Owner | Primary docs | Source / status |
|---|---:|---|
| phase1 | 483 | `truth_owner_primary == "phase1"` + suspense rule-ownability override |
| intercompany | 34 | `injected_intercompany_primary == true` |
| relational | 20 | `employee_vendor_hidden_relationship` |
| duplicate | 22 | `time_shifted_duplicate` / row-score path |
| timeseries | 21 | `injected_timing_primary == true` |
| unsupervised / VAE | 40 | `fictitious_existence_statistical`; suspense excluded |

V3.3b companion/context denominator:

| Lane | Truth docs | Role |
|---|---:|---|
| relational companion | 119 | relationship evidence companion |
| duplicate companion | 71 | sidecar/export evidence companion |
| timeseries context | 92 | period-end timing context |
| statistical companion | 404 | statistical evidence companion, including suspense 100 |

Primary recall, current available surfaces:

| Owner | Primary docs | Matched | Recall / status |
|---|---:|---:|---|
| phase1 candidate-or-higher | 483 | 429 | 88.82% |
| intercompany TOP500 | 34 | 34 | 100.00% |
| relational TOP500 | 20 | 13 | 65.00% exact matched-doc join |
| relational TOP1000 | 20 | 20 | 100.00% exact matched-doc join |
| duplicate TOP500 | 22 | n/a | estimated proration 0 / 22 |
| timeseries product/default TOP500 | 21 | 21 | 100.00% |
| unsupervised / VAE TOP500 | 40 | 7 | 17.50% exact native join |

Companion/context contribution:

| Lane | Truth docs | Matched | Recall / status |
|---|---:|---:|---|
| relational companion TOP500 | 119 | 21 | 17.65% exact matched-doc join |
| relational companion TOP1000 | 119 | 52 | 43.70% exact matched-doc join |
| duplicate companion | 71 | n/a | estimated proration 0 / 71 |
| timeseries context | 92 | 0 | 0.00% |
| statistical companion | 404 | n/a | estimated proration 32 / 404 |

Policy notes:

- relational primary 20은 `employee_vendor_hidden_relationship`이다. Circular related-party 34건은 IC primary이며 relationship companion이고 relational primary로 세지 않는다.
- Relational exact artifact는 `artifacts/relational_v33_exact_primary_measurement_20260531.json`이다. Adopted `structural_moderate_audit_then_business_lane_split_surface`는 TOP500 13 / 20, TOP1000 20 / 20을 exact join으로 올린다. Native/current order는 TOP500 0 / 20이다.
- duplicate primary 22는 `time_shifted_duplicate` / row-score path로 정의한다. Duplicate companion 71은 sidecar/export evidence다.
- Suspense 100건은 PHASE1 primary + statistical companion으로 evaluator override한다. Generator metadata의 statistical primary stamp가 있어도 `long_aged_suspense_balance`는 rule/account-policy primary다.
- VAE primary 40은 `fictitious_existence_statistical` statistical primary이며 feature-space check가 붙어 있다. v3.2d VAE 49는 historical로만 둔다.
- TS product/default는 `ts_specific_top100_stabilized_surface` 기준 21 / 21이다. 이전 ordering 0 / 21은 internal debug baseline으로만 보존한다.
- Owner assignment는 detector output, score, rank, TOP-N matched result를 사용하지 않는다. Raw identifier leak count는 0이다.

---

## V3.3d fixed5_ownermeta_v33d — current canonical candidate

2026-06-01 v3.3d는 `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d`의 shortcut-free owner metadata를 사용한 current canonical responsibility map candidate다. v3.3b = historical responsibility map으로 보존한다. journal owner/leak columns = 0이고 shortcut token hits in journal = 0이다.

V3.3d primary denominator:

| Owner | Primary docs | Source / status |
|---|---:|---|
| phase1 | 483 | truth owner + suspense rule-ownability override |
| intercompany | 34 | circular related-party |
| relational | 23 | employee-vendor hidden relationship, shortcut-free |
| duplicate | 19 | time-shifted duplicate, natural expense reference evidence |
| timeseries | 21 | timing primary |
| unsupervised / VAE | 40 | fictitious existence statistical; suspense excluded |

V3.3d companion/context denominator:

| Lane | Truth docs | Role |
|---|---:|---|
| relational companion | 116 | relationship evidence companion |
| duplicate companion | 71 | duplicate-like evidence companion |
| timeseries context | 92 | period-end timing context |
| statistical companion | 404 | statistical evidence companion, including suspense 100 |

V3.3d native TOP500 recall:

| Family | Target docs | Matched | Recall |
|---|---:|---:|---:|
| intercompany | 34 | 0 | 0.00% |
| relational | 23 | 0 | 0.00% |
| duplicate | 19 | 8 | 42.11% |
| timeseries product/default | 21 | 21 | 100.00% |
| unsupervised / VAE | 40 | 0 | 0.00% |

Notes:

- v3.3d reruns current PHASE2 native cases on the v3.3d journal input. The low relational/VAE results are not hidden; they indicate detector surface work after shortcut removal.
- All 620 truth docs are present in the 318,653-document journal. The measurement uses exact doc-id joins, not scenario proration.
- Family failure modes are separated: IC = `fully_surfaced_top500`; relational / timeseries / VAE = `cases_produced_not_surfaced_top500`; duplicate = `partially_surfaced_top500`.
- IC is fully surfaced in TOP500 on the v3.3d full run.
- The recall drop reflects both shortcut removal and realistic 318k scale. Neither should be solved by reintroducing journal-visible shortcut tokens.
- TS product/default is `ts_specific_top100_stabilized_surface` with 21 / 21. The previous ordering is retained only as an internal debug baseline.
- Owner assignment remains detector-blind / score-blind / rank-blind / matched-result-blind. Raw identifier leak counts are 0.

---

## V2.2 relational relmeta integration — fixed5_relmeta

`datasynth_manipulation_v7_candidate_fixed5_relmeta`는 journal 거래 데이터를 바꾸지 않고 relational 평가용 `relationship_edge_truth.csv/json` sidecar를 추가한 후보 데이터셋이다. Python v2.2 measurement는 이 sidecar가 있을 때만 relational primary denominator pending을 해제한다.

- Script: `tools/scripts/measure_phase2_family_responsibility_recall_v22_fixed5_relmeta_20260530.py`
- Artifact: `artifacts/phase2_family_responsibility_recall_v22_fixed5_relmeta_20260530.json`
- Test: `tests/modules/test_services/test_phase2_family_responsibility_recall_v22.py`

Policy:

- Primary owner는 exclusive하지 않다.
- `circular_related_party_transaction` 34건은 IC와 relational co-primary다.
- Co-primary는 family target performance 평가용이며 portfolio recall에는 중복 합산하지 않는다.
- `relationship_edge_truth` sidecar는 evaluation denominator이며 detector, ranking, fusion, UI scoring input이 아니다.
- R05/R06는 계속 context/diagnostic-only lane이다.
- Production ranking, gate, fusion은 변경하지 않았다.

V2.2 target recall:

| Owner | Primary docs | Matched | Recall |
|---|---:|---:|---:|
| intercompany | 34 | 34 | 100.00% |
| relational | 63 | 9 | 14.29% |
| duplicate | 76 | 0 | 0.00% |
| timeseries | 21 | 0 | 0.00% |
| unsupervised | 0 | 0 | n/a |

Relational detail:

| Metric | Value |
|---|---:|
| relational primary truth docs | 63 |
| relational primary matched docs | 9 |
| relational primary TOP100 matched docs | 4 |
| relational primary TOP500 matched docs | 9 |
| outside PHASE1 immediate | 57 |
| outside PHASE1 review-or-higher | 47 |
| outside PHASE1 candidate-or-higher | 1 |
| relational secondary truth docs | 76 |
| relational secondary matched docs | 8 |
| co-primary overlap count | 34 |

Sidecar metadata:

- `relationship_edge_truth_rows = 139`
- `primary_semantic_group_counts = approval_sod_bypass 29, related_party_loop 34`
- `secondary_semantic_group_counts = employee_payment_relationship 76`
- Historical v2.2 only: `relational_primary_denominator_status = available_from_datasynth_relationship_edge_truth`
- `co_primary_overlap_group = circular_related_party_transaction 34`

V2.1 remains the fallback when the relationship sidecar is absent.

---

## V2.1 duplicate metadata follow-up — fixed5_dupmeta

`datasynth_manipulation_v7_candidate_fixed5_dupmeta`는 journal 거래 데이터를 바꾸지 않고 Duplicate 평가용 truth metadata와 `duplicate_pair_truth` sidecar만 추가한 후보 데이터셋이다. Python measurement는 기존 `fixed5_normalcal5` baseline artifact를 유지하면서, optional `--truth-csv` 입력으로 이 metadata를 읽어 Duplicate primary denominator를 별도 산출한다.

산출물:

- Artifact: `artifacts/phase2_family_responsibility_recall_v21_fixed5_dupmeta_20260530.json`
- Script path: `tools/scripts/measure_phase2_family_responsibility_recall_v21_fixed5_20260530.py --truth-csv ...fixed5_dupmeta...`

DataSynth metadata contract:

| Metric | Count |
|---|---:|
| truth docs | 620 |
| injected duplicate-like docs | 76 |
| duplicate primary target docs | 76 |
| duplicate companion target docs | 0 |
| duplicate pair groups | 38 |
| period-end duplicate primary docs | 0 |

Responsibility-map result with dupmeta:

| Owner | Primary docs | Matched | Recall |
|---|---:|---:|---:|
| duplicate | 76 | 0 | 0.00% |
| duplicate companion context | 92 | 22 | 23.91% |

해석:

- Duplicate primary denominator pending은 `fixed5_dupmeta`에서는 해제된다.
- Primary denominator는 `embezzlement_concealment`의 generator-intended duplicate-like pair metadata 76문서다.
- `period_end_adjustment_manipulation` 92건은 Duplicate primary로 승격하지 않고 companion context로 남긴다.
- 현재 native Duplicate TOP500 22건은 여전히 period-end companion context에 있으며, 새 Duplicate primary target 76건은 포함하지 못한다.
- 이 결과는 detector/ranker 입력을 바꾸지 않는 denominator-only diagnostic이다. Truth metadata는 scoring, ranking, threshold, PHASE1 priority, PHASE2 fusion에 사용하지 않는다.
