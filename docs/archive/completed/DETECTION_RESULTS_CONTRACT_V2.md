# Phase1 Detection 결과 - datasynth_contract_v2

> **PHASE1 역할 원칙**: PHASE1은 fraud 확정 단계가 아니라 감사인이 검토할 review queue를 만드는 단계다. v2 결과는 detector 출력과 sidecar/truth 계약 검증을 분리해서 해석한다.

## 요약

이 문서는 `data/journal/primary/datasynth_contract_v2/`를 2026-05-14에 Phase1로 실행한 결과다. 기존 `docs/archive/completed/DETECTION_RESULTS_CONTRACT.md`는 덮어쓰지 않았다.

v2는 semantic-clean generator의 `--contract-sidecar` 출력이며, 현재 `labels/`에 rule truth와 sidecar taxonomy를 포함한다. Phase1 detector/case builder 출력과 독립 truth surface는 분리해서 해석한다.

## 입력과 산출물

| 항목 | 값 |
| --- | ---: |
| 원장 row | 1,077,767 |
| document | 317,997 |
| journal CSV columns | 53 |
| label 파일 수 | 427 |
| 기존 대비 누락 label/sidecar 파일 | 0 |
| direct label leakage 컬럼 | 없음 |
| semantic metadata 누락 컬럼 | 없음 |

### Phase1 출력

| 항목 | 값 |
| --- | ---: |
| 전체 소요 시간 | 474.394초 |
| 생성된 case 수 | 7,640 |
| macro finding 수 | 18 |
| High row | 436 |
| Medium row | 4,537 |
| Low row | 36,887 |
| Normal row | 1,035,907 |

### 산출 파일

- checkpoint: `artifacts/phase1_contract_v2_profile_20260514.json`
- case input cache: `artifacts/phase1_contract_v2_case_input_20260514.pkl`
- case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260515T000351Z.json`
- rule diff: `tests/datasynth_quality_gate3/results/contract_v2_rule_diff.csv`
- sidecar consistency: `tests/datasynth_quality_gate3/results/contract_v2_sidecar_consistency.json`
- issue samples: `tests/datasynth_quality_gate3/results/contract_v2_issue_samples.csv`

## 실행 시간 분포

| 단계 | 소요 시간 |
| --- | ---: |
| CSV load | 9.171초 |
| independent evidence enrichment | 4.717초 |
| feature.time | 1.571초 |
| feature.amount | 4.194초 |
| feature.pattern | 4.653초 |
| feature.text | 7.544초 |
| detector.layer_a | 16.076초 |
| detector.layer_b | 121.784초 |
| detector.layer_c | 178.736초 |
| detector.benford | 4.088초 |
| aggregate | 29.455초 |
| Phase1 case builder | 81.413초 |
| **합계** | **474.394초** |

## A축 - 룰 계약 검증

**판정: PASS.** 전수 34개 룰에서 `rule_truth_*`와 Phase1 rule-hit document set을 대조했고 과탐 0건, 미탐 0건이다.

## B축 - 사용자 가독성/설명 가능성

**판정: PASS.** case builder는 정상 실행되었고 그룹별 case 구조는 유지된다. v2에서 `approval_matrix_gap_rows`가 184, `document_flow_orphan_rows`가 0로 master/flow coverage가 contract 수준으로 정리되어 control/timing 설명이 안정적이다.

### 그룹별 case 요약

| 그룹 | case | High | Medium | Low | Top case 예시 |
| --- | --- | --- | --- | --- | --- |
| timing anomaly | 3890 | 27 | 1472 | 2391 | case_timing_anomaly_02891, case_timing_anomaly_02723, case_timing_anomaly_02638 |
| control failure | 2012 | 24 | 471 | 1517 | case_control_failure_01895, case_control_failure_00712, case_control_failure_00833 |
| data integrity failure | 25 | 16 | 6 | 3 | case_data_integrity_failure_00004, case_data_integrity_failure_00005, case_data_integrity_failure_00019 |
| logic mismatch | 479 | 5 | 314 | 160 | case_logic_mismatch_00065, case_logic_mismatch_07402, case_logic_mismatch_00027 |
| statistical outlier | 885 | 4 | 98 | 783 | case_statistical_outlier_06542, case_statistical_outlier_06547, case_statistical_outlier_06381 |
| duplicate or outflow | 349 | 4 | 50 | 295 | case_duplicate_or_outflow_00304, case_duplicate_or_outflow_00342, case_duplicate_or_outflow_07516 |

### review-only 신호 처리

| 항목 | 값 |
| --- | ---: |
| L3-12 candidate label 수 | 3,769 |
| seed 후보(case 신규 생성) | 0 |
| context 후보(기존 case 보강) | 3,769 |
| context evidence 추가 수 | 3,769 |

## 보조 데이터 위생 체크

**상태: OK.** 위생 체크 blocker는 없다. 이 체크는 기존 contract 문서와 동등한 C축 검증이 아니라, v2 후보가 깨진 CSV/ID/metadata 상태인지 보는 보조 안전장치다. 기존 contract 대비 sidecar 파일 수 차이는 promotion blocker로 보지 않는다.

T8 원인분리 결과(`artifacts/contract_v2_master_flow_gap_analysis.md`):

- `document_flow_orphan_rows=0` 이므로 document-flow coverage는 blocker가 아니다.
- `approval_matrix_gap_rows=184`는 67개 문서이며, 20개 문서는 provenance가 있는 control fixture, 47개 문서는 provenance 없는 자기승인/background control-gap 성격이다.
- `approval_limit_exceeded_rows=246`은 61개 문서이며, 모두 `LIMIT_REVIEWER` 계열 limit fixture로 분류된다. master join 실패라기보다 manifest/provenance 설명 보강 대상이다.
- 따라서 즉시 detector threshold나 DataSynth 정상 배경을 맞추는 수정은 하지 않는다.

| 항목 | 결과 |
| --- | --- |
| journal/year row 합계 | 통과 |
| journal/year document 합계 | 통과 |
| direct label leakage 제거 | 통과 |
| semantic metadata 컬럼 | 통과 |
| anomaly_labels document_id 존재 | 0 missing |
| anomaly_labels fiscal_year 검증 | 0 mismatch rows |
| 필수 rule_truth 파일 | 통과 |
| 필수 taxonomy/manifest | 통과 |
| 기존 대비 누락 sidecar/label | 참고: 0 files. 기존 보조 sidecar 전체 복제는 필수 동등성 요구가 아님 |

## Rule Diff Top Changes

`v2_phase1_count` 는 `phase1_case_builder.candidate_labels` (row/instance 단위) 이고 `existing_contract_count` 는 v1 `truth_docs` (document 단위) 라서 두 컬럼은 단위가 다르다. WARNING 으로 분류된 L4-04 / L4-05 / L3-06 / L2-05 는 v2 truth_docs 와 detector docs 가 정확히 일치하며(§A축 PASS), 본 단위 차이 때문에 row 카운트만 부풀려진 결과다. 자세한 sample 검증은 `artifacts/contract_v2_warning_rule_sample_audit.md` 참조.

| rule | 기존 | v2 | delta | severity | 해석 |
| --- | ---: | ---: | ---: | --- | --- |
| L3-04 | 141,375 | 8,203 | -133,172 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L3-02 | 86,808 | 39,762 | -47,046 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L3-03 | 30,377 | 315 | -30,062 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L4-04 | 4,091 | 21,798 | 17,707 | EXPECTED_CHANGE_v2_BACKGROUND | v2 truth_docs=386, detector_docs=386 (A축 FP=FN=0). v2_phase1_count 21,798 은 case_builder candidate_labels 이며 large_doc (≥100 line) 215건의 line fanout 113,483 이 주된 row 증가 원인. 자세한 sample 검증은 artifacts/contract_v2_warning_rule_sample_audit.md §3.1 참조. |
| L3-05 | 24,318 | 6,780 | -17,538 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L4-05 | 4,964 | 13,684 | 8,720 | EXPECTED_CHANGE_v2_BACKGROUND | v2 truth_docs=10,828, detector_docs=10,828 (A축 FP=FN=0). v2 generator 가 R2R_REVERSAL/R2R_ACCRUAL 영역의 abnormal-time cluster 를 의도적으로 두텁게 구성. 정상 모집단 FP rate=0%. 샘플 검증 §3.2 참조. |
| L3-06 | 7,507 | 12,467 | 4,960 | EXPECTED_CHANGE_v2_BACKGROUND | v2 truth_docs=14,844, detector_docs=14,844 (A축 FP=FN=0). source=automated 야간 배치 entry (A2R_DEPRECIATION, O2C_CUSTOMER_INVOICE 등) 가 정상 batch 거동으로 normal_system_context (score 0.20) 에 분류. 샘플 검증 §3.3 참조. |
| L3-12 | 0 | 3,769 | 3,769 | OK | A축 strict rule_truth 대조 기준 과탐/미탐 0. 기존 contract 기준 없음. |
| L3-01 | 2,419 | 1 | -2,418 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L4-03 | 4,015 | 2,101 | -1,914 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L3-10 | 1,601 | 12 | -1,589 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L2-05 | 80 | 1,471 | 1,391 | EXPECTED_CHANGE_v2_BACKGROUND | v2 truth_docs=267, detector_docs=267 (A축 FP=FN=0). v2 R2R_REVERSAL fixture 확대로 doc 단위 80→267. detector queue 분류 (high_confidence 106 / mid 672 / low 1,002 / normal_reclass 166) 정상 작동. 샘플 검증 §3.4 참조. |

## 최종 결론

`datasynth_contract_v2`는 A축 과탐/미탐 0, B축 master/flow coverage, 데이터 위생 체크 세 축을 모두 통과했고, 추가 검토 항목이던 4개 WARNING (L4-04 / L4-05 / L3-06 / L2-05) 도 sample 검증 결과 모두 **EXPECTED_CHANGE_v2_BACKGROUND** 로 확정됐다 (`artifacts/contract_v2_warning_rule_sample_audit.md`). detector 측 추가 수정은 불필요하며, 후속은 rule_diff 의 severity 산식을 단위 일치로 보강하는 작업(선택, 별도 PR) 뿐이다.
