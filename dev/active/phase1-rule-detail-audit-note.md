# PHASE1 Rule Detail Audit Note

## Observed L1-01 UI Defect

Dataset checked:

- `data/journal/primary/datasynth_contract/journal_entries_2022.csv`

Example:

- `74bda121-4d0c-4389-9433-cd48b238b2ca`
- Fiscal year `2022`, period `4`, company `C002`
- Debit total `35,690,001`
- Credit total `35,690,001`
- Difference `0`

This document is not an L1-01 debit/credit imbalance. It is a data-integrity issue because one `gl_account` value is missing.

## Why The UI Is Wrong

The L1-01 detector itself computes document-level imbalance correctly in `IntegrityDetector._a01_unbalanced_entry()` by grouping on `document_id` and comparing `sum(debit_amount)` vs `sum(credit_amount)`.

The defect is in the PHASE1 rule detail view assembly:

1. Rule hit documents and case member documents are mixed.
   - `build_phase1_rule_case_doc_map()` currently maps a rule-bearing case to all `case.documents`.
   - If one document in a case has L1-01, other documents in the same case can appear under the L1-01 document master.

2. Master table amount columns use a representative row, not document totals.
   - `build_phase1_rule_documents()` stores `debit_amount`, `credit_amount`, and `amount` from the first relevant row selected for the document.
   - For document-level rules such as L1-01, this makes the master table show line-level amounts while the evidence summary is document-level.

3. Cached/stored analysis results can keep stale `flagged_rules`/case membership visible until the analysis is rerun or reset.

## Initial Fix Direction

1. For document-level rule detail views, derive displayed documents from rule-specific raw hits or validated rule-specific predicates, not from all documents in a case.
2. Change `build_phase1_rule_case_doc_map()` so it returns only documents with a raw hit for the requested rule, unless the rule explicitly declares case-level display semantics.
3. For L1-01, compute master-table debit, credit, difference, and evidence amount from full `doc_rows`, not the representative row.
4. Audit other rules for the same two risks:
   - case document leakage into rule-specific document lists
   - row-level representative values shown as document-level evidence
5. After code fixes, reset or rerun existing analysis batches before judging the UI.

## Full Rule Detail Audit Snapshot

### Shared Defect Surfaces

1. `src.export.phase1_case_view.build_phase1_rule_documents()`
   - Selects rows by parsing `featured_data.flagged_rules` and `featured_data.review_rules`.
   - Uses the first relevant row per `document_id` as the master row.
   - This is unsafe for document-level, pair-level, macro-level, and case-level rules unless the rule evidence is recomputed from all document rows or sidecar/raw-hit metadata.

2. `src.export.phase1_case_view.build_phase1_rule_case_doc_map()`
   - Includes all `case.documents` for any case that has the requested rule in `raw_rule_hits`.
   - In the current render path it mostly filters an already-built rule row list, but it can still widen selection semantics and should be restricted to documents with a requested-rule raw hit.

3. `src.db.batch_reader._reconstruct_detection_results()`
   - Reconstructs persisted `anomaly_flags` by mapping each `document_id` to the first row index.
   - It ignores persisted `line_number`, so restored DetectionResult details lose row-level location.
   - This can distort row-level displays and can move line-specific rule evidence to the first line of a document.

4. `src.db.loader._build_anomaly_flags_df()`
   - Persists only positive `DetectionResult.details` values.
   - `review_rules` are not persisted as rule-detail evidence in the same way unless they also produced positive details.

### Highest Risk Rules

These rules need rule-specific document-level or pair-level evidence instead of representative-row values:

- `L1-01`: document-level debit/credit imbalance. Must recompute debit total, credit total, and difference from all document rows.
- `L1-04`: approval limit excess. Needs document economic amount, approval threshold, and approver context, not arbitrary line amount.
- `L2-01`: just-below-threshold. Needs document amount/threshold ratio, not a first line amount.
- `L2-02`: duplicate payment. Needs duplicate-group/pair metadata, counterparty, reference, amount, and matched document.
- `L2-03`: duplicate journal and aliases `L2-03a~d`. Needs duplicate signature/group metadata; aliases should remain drilldown reason codes, not separate row-detail headings.
- `L2-05`: reversal pattern. Needs matched reversal document/pair metadata, not one selected row.
- `IC01`, `IC02`, `IC03`: intercompany sidecars. They are sidecar/pair rules and should not use generic transaction row detail.
- `D01`, `D02`, `L4-02/Benford`: macro rules. They correctly have row detail disabled, but topic/case displays must not imply single-row transaction evidence.

### Medium Risk Rules

These are transaction-detail rules, but master columns can be misleading if the chosen representative row is not the actual violating row or if restored batches moved the flag to the first document row:

- `L1-02`: missing required field. Should display missing fields from row annotations or direct null scan on the displayed row.
- `L1-03`: invalid account. Should display the invalid account row, not first row after DB restore.
- `L1-05`: self approval. Usually document-level; representative row is acceptable only if created/approved fields are document-level stable.
- `L1-06`: SoD. User/process evidence may be case/user-level; document row display should be treated as context.
- `L1-07`: missing approval. Usually document-level; representative row is acceptable if approval fields are stable across document rows.
- `L1-08`: fiscal period mismatch. Usually document-level; expected/actual should be recomputed from posting date and fiscal period.
- `L1-09`: approval date missing. Usually document-level; representative row is acceptable if approval fields are stable.
- `L2-04`: expense capitalization. Needs specific asset/expense account rows in the same document; representative `gl_account` alone is weak.
- `L3-01`: process/account mismatch. Row-specific, but restored batches can move the evidence to first row.
- `L3-04`, `L3-07`, `L3-11`: timing rules. Mostly document-level date fields; representative row is acceptable if dates are document-level stable.
- `L3-09`, `L3-10`: sensitive/unsettled accounts. Row-specific; must keep the actual account row.
- `L4-01`, `L4-03`, `L4-04`: statistical/rare-account transaction details. Need the actual scored row/account or derived score metadata, not a generic first row.

### Lower Risk / Context-Only Rules

These are intentionally not standalone transaction-detail rules in metadata, or should be displayed as context badges:

- `L3-03`, `L3-05`, `L3-06`, `L3-08`, `L3-12`, `L4-05`, `L4-06`
- `GR01`, `GR03`

Risk remains if the topic UI presents them through the generic rule master/detail path despite `allow_row_violation_detail=False`.

### Fix Order

1. Add tests for L1-01 balanced/non-balanced documents:
   - A balanced document with `L1-02` in the same case must not appear in L1-01 document master.
   - L1-01 master columns must show document debit total, credit total, and difference.
2. Fix `build_phase1_rule_case_doc_map()` to map case IDs to raw-hit documents for the requested canonical rule.
3. Add a document evidence aggregation path in `build_phase1_rule_documents()`:
   - For document-level rules, compute display fields from `doc_rows`.
   - For row-level rules, keep the actual hit row.
   - For pair/sidecar/macro rules, use sidecar/raw-hit metadata or keep row detail disabled.
4. Fix DB restored batch reconstruction to use `(document_id, line_number)` when available, falling back to first row only if line number is missing.
5. Re-run/reload batches after the view and restore fixes.

## H-2 / P-6: L3-11 absent from v2 stats artifact

Reported: `artifacts/phase1_rule_case_gap_stats_after_case_builder_fix.json` 에 `L3-11` 키가 없다. 카드 `DETECTION_RULES.md`, `src/detection/rule_scoring.py`, `src/detection/rule_detail_metadata.py` 에는 모두 정의되어 있다.

### 진단 결과: 코드 alive, 카드 valid, 원인은 active dataset coverage 결정

1. Detector 코드는 정상 동작한다.
   - `EvidenceDetector` registry (`src/detection/evidence_detector.py:78-93`) 에 `L3-11` → `ev02_cutoff_violation` 매핑 유지.
   - `src/services/analysis_service.py:48` 가 PHASE1 phase settings 에서 `enable_evidence_detection=True` 로 강제하므로 `_try_evidence_detection` (pipeline.py:1558) 경로에서 항상 실행된다.
   - `tests/modules/test_detection/test_evidence_detector.py` 7 케이스 모두 통과 (`uv run pytest tests/modules/test_detection/test_evidence_detector.py` confirmed). `test_l311_metadata_is_propagated` 가 L3-11 행 점수 출력을 잠근다.

2. Active dataset 에 L3-11 truth/cutoff 신호가 0 건이다.
   - `data/journal/primary/datasynth_contract_v2/labels/rule_truth_L3_11*.csv` 는 헤더만 있고 truth row 0 건.
   - `data/journal/primary/datasynth_contract_v2/labels/` 에 cutoff sidecar 부재 (`cutoff_confirmed_anomalies` 등은 `data/journal/archive/primary_legacy_20260514/datasynth/labels/` 로만 존재).
   - `journal_entries_2022.csv` 에서 `delivery_date` 유효값 12 / 360,345 (0.00%). 매출/비용 prefix 매칭 row 는 사실상 0. L3-11 의 cutoff 입력 자체가 없다.
   - `tests/datasynth_quality_gate3/results/contract_v2_rule_volume_review.csv` 에도 `L3-11, truth_docs=0, doc_ratio_pct=0.0, fp_docs=0, fn_docs=0` 으로 명시되어 있다.

3. v2 stats artifact 누락은 의도된 결과다.
   - `artifacts/phase1_rule_case_gap_stats*.json` 은 gitignore 대상 (artifacts/* 전체 ignore) 의 one-off audit 출력으로, 활성 detection 결과 기준으로 hit 이 있는 rule 만 키로 남긴다.
   - active dataset 에서 L3-11 hit 이 0 이므로 stats artifact 에서 빠지는 게 정합. 카드/탐지기 결손이 아니다.

4. `dev/active/datasynth-journal-realism-rebuild/phase1-rule-testability-matrix.md:47` 에서 L3-11 은 이미 Class B (`semantic-clean required`) 로 분류되어 있다. 현재 contract v2 가 O2C invoice/cutoff scenario 를 보유하지 않아 cutoff 신호 자체를 합성하지 않은 상태다.

### 결론

- 코드 미실행 아님 → `활성화 + 회귀 test` 불필요. 이미 active 실행 + 회귀 잠금 완료.
- Docs lag 아님 → `카드 archive` 불필요. 카드는 정확하다.
- 실제 후속 작업은 `datasynth-journal-realism-rebuild` Class B 시나리오 (`O2C invoice / shipment / delivery_date semantic-clean`) 가 완료되어 contract v2 / manipulation v3 가 cutoff truth 와 `delivery_date` 분포를 합성한 뒤 PHASE1 을 재실행하여 L3-11 hit/truth 가 stats artifact 에 다시 잡히는지 확인하는 것이다. 이 항목은 DataSynth track 으로 위임한다.

### 별도 미세 정합

- `docs/DETECTION_RULES.md` §2.0.9 (라인 301~303) 는 "기본 실행에서는 `EvidenceDetector(rule_ids=("L3-11",))` 로 cutoff 룰만 실행한다" 라고 적었지만, 실제 `src/pipeline.py:1573` 호출은 `rule_ids` 를 전달하지 않으므로 `EV01 / L3-11 / EV03` 세 룰이 모두 등록 후 실행되며 컬럼 부재 시 graceful skip 된다. cutoff-only 가 아니라 `enable_evidence_detection=True` 시 evidence 세 룰 모두 실행이라는 표현이 정확하다. 단, `EV01 / EV03` 입력 컬럼 (`has_attachment`, `invoice_amount` 등) 이 active dataset 에 없어 실질적으로 cutoff 만 결과를 만든다. 카드 archive 사안은 아니고 §2.0.9 문구 보정 정도의 별도 후속 항목으로 둔다.

## PHASE2 overlay 반영 노트 (2026-05-17)

Stage 7 에서 Phase2CaseOverlay 가 PHASE1 case 41,129 건에 PHASE2 unsupervised autoencoder 스코어를 결합한 review queue 를 산출했다. 본 절은 rule detail / case priority 표현 계층에 PHASE2 overlay 가 미치는 영향과 lock 정책을 기록한다.

### composite_sort_score V1 lock 유지

- sort keys: `phase1_composite_sort_score`, `phase1_triage_rank_score`, `total_amount`, `rule_count`.
- `phase2_score` 는 sort key 가 아니다. review queue 와 rule detail 표현 계층에서 보조 컬럼으로만 노출하며, 정렬 기준에서 제외된다.
- V1 lock 준수 검증: `composite_sort_v1_lock_compliant=True`, `rank_mismatch_count=0` (Stage 7 통합 리포트).

### 옵션 Z lock — PHASE1 priority_score 비파괴

- PHASE2 overlay 가 추가된 후에도 PHASE1 priority_score / risk_level / topside_score / intercompany_exception_score 컬럼은 원본을 유지한다.
- 검증: `priority_score_preserved=True`, mismatch 0 / 41,129 (Stage 7 통합 리포트).
- rule detail master 표시에 사용되는 case priority 값은 PHASE1 산출본 그대로 사용한다. PHASE2 overlay 가 PHASE1 우선순위를 덮어쓰지 않는다.

### Narrator 입력 계약 표시

- top-100 candidate 모두 narrator 필수 6 필드 (`candidate_id`, `journal_ref`, `rule_hits`, `ml_scores`, `journal_meta`, `peer_context`) 결측 0 으로 산출.
- 본 문서의 H-2 / P-6 (L3-11) 처럼 active dataset coverage 결정으로 rule hit 가 0 인 룰은 narrator candidate 후보에 포함되지 않는다. PHASE2 overlay 도 PHASE1 rule hit 가 0 인 룰의 우선순위를 끌어올리지 않는다.

### truth recall 가드 적용

- Stage 6 Layer C 의 `top500 truth count=115`, `top100 truth count=27`, `total truth docs=795` 는 `feedback_phase1_truth_recall_guard` 에 따라 informational only.
- rule detail 표현 계층 변경의 정당화 사유로 truth recall 을 사용하지 않는다. master/detail 표 정정은 도메인 정합성 (document-level vs row-level evidence, 케이스 멤버 누설) 으로만 정당화한다.

### 교차 참조

- DECISION.md D050 (Layer A/B/C 가드 체계)
- debugging.md 2026-05-17 entry (PHASE2 첫 학습 + Stage 5/6/7 결과)
- phase2-unsupervised-autoencoder-context.md Stage 5/6/7 Results
- artifacts/phase1_phase2_integration_report_2026-05-17.md (Stage 7 통합 리포트)
