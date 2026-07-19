# datasynth_contract_v2 Phase1 비교 분석

## 1. 결론

`datasynth_contract_v2`는 A축 과탐/미탐 0, B축 master/flow coverage, 데이터 위생 체크 세 축을 모두 통과했다. 남은 검토 항목은 rule diff에서 detector_review_needed로 분류된 룰의 의미 해석과 큰 delta가 expected change인지 샘플 확인이다.

진행 방향은 큰 count delta rule의 의미 검토와 B축 가독성 검토다. `sidecar_truth_refresh_needed`는 해소됐고, 데이터 위생 체크는 promotion 동급 축이 아니라 blocker 조건만 보는 보조 안전장치로 둔다.

## 2. A/B + 위생 체크 요약

| 구분 | 판정 | 핵심 근거 | 조치 |
|---|---|---|---|
| A | PASS | 전수 34개 룰 과탐 0건, 미탐 0건. diff rule: 없음 | 추가 조치 없음 |
| B | PASS | 그룹별 case 구조와 L3-12 context-only 정책 유지. approval_matrix_gap_rows=184, document_flow_orphan_rows=0로 master/flow coverage 정리 완료. | 대표 case 의미 검토와 rule diff 해석 |
| 데이터 위생 체크 | OK | leakage 제거, year split, label id/year, semantic metadata를 보는 보조 안전장치. 기존 contract 대비 전체 sidecar 파일 수 동등성은 요구하지 않음 | BLOCKER 조건이 생길 때만 promotion 차단 |

## 3. Rule Diff Top Changes

| rule | 기존 | v2 | delta | severity | 해석 |
|---|---:|---:|---:|---|---|
| L3-04 | 141,375 | 8,203 | -133,172 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L3-02 | 86,808 | 39,762 | -47,046 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L3-03 | 30,377 | 315 | -30,062 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L4-04 | 4,091 | 21,798 | 17,707 | WARNING | A축 strict rule_truth 대조 기준 과탐/미탐 0. count 증가가 커서 detector/data 분리 검토 필요. |
| L3-05 | 24,318 | 6,780 | -17,538 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L4-05 | 4,964 | 13,684 | 8,720 | WARNING | A축 strict rule_truth 대조 기준 과탐/미탐 0. count 증가가 커서 detector/data 분리 검토 필요. |
| L3-06 | 7,507 | 12,467 | 4,960 | WARNING | A축 strict rule_truth 대조 기준 과탐/미탐 0. count 증가가 커서 detector/data 분리 검토 필요. |
| L3-12 | 0 | 3,769 | 3,769 | OK | A축 strict rule_truth 대조 기준 과탐/미탐 0. 기존 contract 기준 없음. |
| L3-01 | 2,419 | 1 | -2,418 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L4-03 | 4,015 | 2,101 | -1,914 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L3-10 | 1,601 | 12 | -1,589 | EXPECTED_CHANGE | A축 strict rule_truth 대조 기준 과탐/미탐 0. semantic-clean 생성으로 일부 쓰레기/계약 fixture 기반 hit 감소 가능. |
| L2-05 | 80 | 1,471 | 1,391 | WARNING | A축 strict rule_truth 대조 기준 과탐/미탐 0. count 증가가 커서 detector/data 분리 검토 필요. |

## 4. 문제 분류

| 분류 | 내용 | 대표 항목 |
|---|---|---|
| generator_fix_needed | master/flow provenance coverage 정상화. `document_flow_orphan_rows=0`, `approval_matrix_gap_rows=184`, `approval_limit_exceeded_rows=246` | `document_flow_orphan_rows=0`, `approval_matrix_gap_rows=184` |
| sidecar_truth_refresh_done | v2 journal 기준 독립 truth/sidecar/taxonomy 생성 완료 | `rule_truth_*`, `contract_rule_truth_taxonomy*`, `sidecar_manifest.csv` |
| detector_review_needed | count 증가 또는 strict A축 document-set 차이 때문에 detector/truth 기준 분리 검토 필요 | L4-04, L4-05, L3-06, L2-05, L2-03, L1-01, L1-04, L1-03 |
| expected_semantic_clean_change | semantic-clean/source-mix 변화로 기존 contract 대비 감소가 설명 가능한 후보 | L3-04, L3-02, L3-03, L3-05, L3-01, L4-03, L3-10, L3-09, L2-04, L4-01, L3-07, L1-08, L2-01, L3-08, L2-02, L4-06, L3-11, L1-05, L1-02, L1-09, L1-07, L1-06 |
| acceptable_no_action | leakage 제거, semantic columns, year-file row/doc 합계 | journal 구조 검증 항목 |

## 5. 다음 작업

- L2-02 duplicate payment, L3-05 weekend/holiday, L4-04 rare account pair는 v2 truth 생성 후 count 감소/증가가 expected change인지 샘플 검토한다.
- `document_flow_orphan_rows`와 `approval_matrix_gap_rows`의 원인이 generator master/flow coverage인지 detector 기준 변경인지 분리한다.
- normal accounting logic sample 300건을 v2에서 재검증하고, semantic hard gate 이후 남은 정합성 오류가 intentional fixture인지 확인한다.
