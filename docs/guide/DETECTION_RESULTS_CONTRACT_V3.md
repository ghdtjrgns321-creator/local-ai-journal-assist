# Phase1 Detection 결과 - datasynth_contract_v2 CONTRACT_V3

> **PHASE1 역할 원칙**: PHASE1은 fraud 확정 단계가 아니라 감사인이 검토할 review queue를 만드는 단계다. 이 문서는 V2 산출물을 detector/case builder 재실행 없이 전표(document) 단위로 재집계한 CONTRACT_V3 보고서다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

## 요약

이 문서는 `docs/archive/completed/DETECTION_RESULTS_CONTRACT_V2.md`의 KPI 단위 혼재를 2026-05-18 TS-12 정책에 맞춰 정리한 별도 보고서다. V2 원문은 보존하고, V3는 `datasynth_contract_v2` 결과를 전표 단위 외부 KPI로 재집계한다.

핵심 변경은 다음과 같다.

- 외부 보고 KPI는 전표(document) 단위로 일원화한다.
- case 수는 PHASE1 UI 검토 효율 지표로만 유지하며 외부 KPI 분모로 쓰지 않는다.
- `Rule Diff Top Changes`는 기존 `v2_phase1_count`의 row/instance 성격을 분리하고, case builder candidate의 unique document 수로 재표시한다.
- detector 코드, threshold, case builder는 재실행하지 않았다. 기존 V2 산출물과 cache만 읽어 단위 변환했다.

## 단위 정책 (2026-05-18)

TS-12의 결정에 따라 외부 산출물의 recall, diff, coverage 계열 KPI는 전표(document) 단위로 보고한다. PHASE1 case는 감사인이 화면에서 검토하는 묶음 단위이므로 UI 운영 효율 지표로 남기되, 외부 보고 분모나 rule diff의 비교 단위로 쓰지 않는다.

근거는 감사 실무의 journal entry testing 단위와 맞춘 것이다. PCAOB AS 2401은 경영진 통제 우회 대응 절차에서 부적절하거나 승인되지 않은 journal entries와 other adjustments의 특성을 고려하도록 요구하며, 예시도 기말/사후 전표, unusual/seldom-used accounts, 작성자, 설명 부족 등 entry 중심으로 제시한다. MindBridge의 journal entry testing 자료도 full-population GL 분석, transaction/entry risk score, high-risk transactions sampling을 중심으로 설명한다. 따라서 외부 설명 단위는 PHASE1 내부 case가 아니라 전표/거래 단위가 더 표준적이다.

참고:

- PCAOB AS 2401: https://pcaobus.org/oversight/standards/auditing-standards/details/AS2401
- MindBridge Journal Entry Testing: https://www.mindbridge.ai/resources/mindbridge-for-journal-entry-testing/
- MindBridge transaction details: https://support.mindbridge.ai/hc/en-us/articles/1500001228061-Transaction-and-entry-details

## V2 대비 변경 사항

| V2 표 위치 | V2 단위 | V3 처리 | V3 표 위치 |
| --- | --- | --- | --- |
| Phase1 출력 - 생성된 case 수 | case | 유지. 단, 내부 UI 검토 단위임을 명시 | Phase1 출력 |
| Phase1 출력 - High/Medium/Low/Normal row | row | 유지 + unique document 행 추가 | Phase1 출력 |
| A축 - 룰 계약 검증 | document | 유지. 단위 명시 | A축 - 룰 계약 검증 |
| B축 - 그룹별 case 요약 | case | unique document 수와 case당 평균 document 수 추가 | 그룹별 case 요약 |
| review-only 신호 처리 | row/instance | L3-12 candidate label unique document 수 추가 | review-only 신호 처리 |
| Rule Diff Top Changes | v1 truth_docs vs v2 row/instance 혼재 | v1 truth_docs vs V3 case-builder candidate unique document로 통일 | Rule Diff Top Changes |
| 보조 데이터 위생 체크 | 단위 무관 | 변경 없음 | 보조 데이터 위생 체크 |
| 최종 결론 | 혼재 가능 | 모든 외부 KPI document 단위임을 명시 | 최종 결론 |

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
| High 전표 | 224 |
| Medium 전표 | 1,794 |
| Low 전표 | 5,336 |
| Normal 전표 | 312,167 |

참고: case는 PHASE1 UI 검토 단위이고 외부 KPI 분모가 아니다. 전표 수는 각 risk band에 속한 row의 `document_id` unique count다. 한 전표가 여러 row를 가지므로 row 수와 전표 수는 일치하지 않는다.

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

**판정: PASS.** 단위: document.

전수 34개 룰에서 `rule_truth_*`와 Phase1 rule-hit document set을 대조했고 과탐 0건, 미탐 0건이다. 이 결론은 V2와 동일하며, 이미 document 단위 truth_docs 대조로 산정되어 별도 단위 변환이 필요 없다.

## B축 - 사용자 가독성/설명 가능성

**판정: PASS.** case builder는 정상 실행되었고 그룹별 case 구조는 유지된다. V3에서는 외부 KPI와 혼동되지 않도록 그룹별 unique document 수와 case당 평균 document 수를 함께 표시한다.

전체 case 7,640개가 포함하는 unique document는 7,275개다. case/document 비율은 1.05배로, 한 전표가 여러 주제 case로 분리되는 현상은 제한적이다. 단, 그룹별 합계는 같은 전표가 여러 그룹에 들어갈 수 있으므로 전체 unique document 7,275개와 단순 합산되지 않는다.

### 그룹별 case 요약 (case 단위 / 전표 단위)

| 그룹 | case | High case | Medium case | Low case | unique document | case당 평균 document | Top case 예시 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| timing anomaly | 3,890 | 27 | 1,472 | 2,391 | 3,791 | 1.33 | case_timing_anomaly_02891, case_timing_anomaly_02723, case_timing_anomaly_02638 |
| control failure | 2,012 | 24 | 471 | 1,517 | 6,118 | 3.04 | case_control_failure_01895, case_control_failure_00712, case_control_failure_00833 |
| data integrity failure | 25 | 16 | 6 | 3 | 295 | 11.80 | case_data_integrity_failure_00004, case_data_integrity_failure_00005, case_data_integrity_failure_00019 |
| logic mismatch | 479 | 5 | 314 | 160 | 182 | 1.31 | case_logic_mismatch_00065, case_logic_mismatch_07402, case_logic_mismatch_00027 |
| statistical outlier | 885 | 4 | 98 | 783 | 1,328 | 1.69 | case_statistical_outlier_06542, case_statistical_outlier_06547, case_statistical_outlier_06381 |
| duplicate or outflow | 349 | 4 | 50 | 295 | 590 | 1.85 | case_duplicate_or_outflow_00304, case_duplicate_or_outflow_00342, case_duplicate_or_outflow_07516 |

### review-only 신호 처리

| 항목 | 값 |
| --- | ---: |
| L3-12 candidate label 수 | 3,769 |
| L3-12 candidate unique document | 1,502 |
| seed 후보(case 신규 생성) | 0 |
| context 후보(기존 case 보강) | 3,769 |
| context evidence 추가 수 | 3,769 |

L3-12는 review-only context 후보로만 작동한다. `rule_truth_L3_12.csv`의 넓은 review universe와는 별개로, case builder 후보로 실제 보강된 candidate label 3,769건은 1,502개 전표에 매핑된다.

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

V2의 `v2_phase1_count`는 `phase1_case_builder.collect_raw_hits.<rule>.candidate_labels`의 row/instance 수였고, `existing_contract_count`는 v1 `truth_docs`의 document 수였다. V3에서는 두 비교축을 모두 document 단위로 맞춘다.

- `existing_doc_count`: v1 `truth_docs` document 수. 기존 `existing_contract_count`와 동일.
- `v3_candidate_doc_count`: V2 case builder candidate labels의 `document_id` unique count.
- `delta_doc`: `v3_candidate_doc_count - existing_doc_count`.

| rule | existing_doc_count | V2 row/instance count | v3_candidate_doc_count | V2 delta | delta_doc | severity_v3 | 해석 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| L3-04 | 141,375 | 8,203 | 3,762 | -133,172 | -137,613 | EXPECTED_CHANGE | semantic-clean 생성으로 기말/기초 row fanout과 후보 전표가 모두 감소. A축 document truth 대조는 PASS. |
| L3-02 | 86,808 | 39,762 | 6,082 | -47,046 | -80,726 | EXPECTED_CHANGE | 수기/조정 후보는 case candidate doc 기준으로 더 보수적으로 집계됨. A축 document truth 대조는 PASS. |
| L3-03 | 30,377 | 315 | 272 | -30,062 | -30,105 | EXPECTED_CHANGE | 관계사 후보 감소는 semantic-clean 생성 차이. A축 document truth 대조는 PASS. |
| L4-04 | 4,091 | 21,798 | 156 | 17,707 | -3,935 | EXPECTED_CHANGE_v2_BACKGROUND | V2 WARNING은 row/instance fanout 영향. document 단위에서는 후보 전표가 v1 대비 감소. |
| L3-05 | 24,318 | 6,780 | 743 | -17,538 | -23,575 | EXPECTED_CHANGE | 주말/휴일 후보 감소. A축 document truth 대조는 PASS. |
| L4-05 | 4,964 | 13,684 | 3,646 | 8,720 | -1,318 | EXPECTED_CHANGE_v2_BACKGROUND | V2 abnormal-time row cluster가 row count를 부풀렸으나 candidate document 기준으로는 WARNING 아님. |
| L3-06 | 7,507 | 12,467 | 3,468 | 4,960 | -4,039 | EXPECTED_CHANGE_v2_BACKGROUND | automated 야간 batch context가 많아 row count가 컸다. candidate document 기준으로는 v1 대비 감소. |
| L3-12 | 0 | 3,769 | 1,502 | 3,769 | 1,502 | OK | 기존 contract 기준 없음. review-only context 후보이며 seed case를 만들지 않는다. |
| L3-01 | 2,419 | 1 | 1 | -2,418 | -2,418 | EXPECTED_CHANGE | 계정/프로세스 불일치 후보 감소. A축 document truth 대조는 PASS. |
| L4-03 | 4,015 | 2,101 | 1,328 | -1,914 | -2,687 | EXPECTED_CHANGE | 이상 고액 후보 감소. A축 document truth 대조는 PASS. |
| L3-10 | 1,601 | 12 | 12 | -1,589 | -1,589 | EXPECTED_CHANGE | 고위험 계정 후보 감소. A축 document truth 대조는 PASS. |
| L2-05 | 80 | 1,471 | 229 | 1,391 | 149 | EXPECTED_CHANGE_v2_BACKGROUND | V2 R2R_REVERSAL fixture 확대로 후보 전표가 80→229 증가. row fanout 1,471 대비 document delta는 크게 축소. |

### WARNING 재산정

V2 문서에서 별도 검토 대상이던 4개 WARNING은 단위 통일 후 모두 `EXPECTED_CHANGE_v2_BACKGROUND`로 정리된다.

| rule | V2 delta(row/instance 혼재) | V3 delta_doc | 절대 delta 감소율 | V3 판정 |
| --- | ---: | ---: | ---: | --- |
| L4-04 | 17,707 | -3,935 | 77.8% | EXPECTED_CHANGE_v2_BACKGROUND |
| L4-05 | 8,720 | -1,318 | 84.9% | EXPECTED_CHANGE_v2_BACKGROUND |
| L3-06 | 4,960 | -4,039 | 18.6% | EXPECTED_CHANGE_v2_BACKGROUND |
| L2-05 | 1,391 | 149 | 89.3% | EXPECTED_CHANGE_v2_BACKGROUND |

### WARNING 잔존

잔존 WARNING 없음.

L3-06은 절대 delta 감소율이 18.6%로 작지만, 부호가 V2의 증가(+4,960)에서 V3의 감소(-4,039)로 바뀌었다. 이는 기존 WARNING이 "row count 증가" 때문에 발생했다는 점을 확인한다. full detector document truth 기준에서는 L3-06 detector docs 14,844개와 v2 truth_docs 14,844개가 일치한다.

## 최종 결론

`datasynth_contract_v2`는 A축 과탐/미탐 0, B축 master/flow coverage, 데이터 위생 체크 세 축을 모두 통과했다. V2에서 추가 검토 항목이던 4개 WARNING(L4-04 / L4-05 / L3-06 / L2-05)은 V3 document 단위 재집계 결과 모두 **EXPECTED_CHANGE_v2_BACKGROUND**로 확정된다.

본 문서의 모든 외부 KPI는 전표(document) 단위로 재집계되었다. case 단위 V2 표는 `docs/archive/completed/DETECTION_RESULTS_CONTRACT_V2.md`에 보존한다.
