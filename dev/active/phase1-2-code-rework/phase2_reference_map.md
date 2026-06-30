# Phase 2 레거시 정리 — 전 참조 지도 (3 Explore 에이전트 grep 실측)

작성 2026-06-30. PLAN §3 Phase 2 산출물. 삭제·정리의 SoT. 추정 아닌 grep 실측.

## 0. 최상위 제약 (먼저 읽을 것)

- **phase2 서비스 계층은 살아있고 VAE와 한 몸이다.** VAE/IF(`ml_unsupervised`)가 family-case와 동일한 orchestrator·contract·family_policy·aggregator·lane_sort·model·subdetector_tiers 인프라를 통과한다. → **통째 삭제 금지. family 가지만 외과적으로 제거, 공유 인프라 보존.**
- **graph는 완전 dead** — `_try_graph_detection`(pipeline.py:1717) 정의만 있고 호출부 0. phase2 소비처 없음. → 가장 안전한 1순위 삭제.
- **함정 1**: `intercompany_rules.py:49 extract_ic_prefixes`를 **잔존 대상** is_intercompany 생성기(`pattern_features.py:201,203`)가 import. IC 통삭제 전 이 함수를 잔존 위치로 **이전 필수**.
- **함정 2**: duplicate rule_id는 코드상 `L2-03a~d`(b05는 함수명 prefix). 현행 **L2-03 base는 duplicate_detector가 아니라 `fraud_layer.py:268 b05_duplicate_entry`** — 별개 구현, 잔존. duplicate_detector(L2-03a~d) 전체가 드롭 대상.

## 1. 공유 인프라 — 보존 (VAE backbone, 제거 금지)

| 파일                                           | 역할                       | 보존 사유                                      |
| ---------------------------------------------- | -------------------------- | ---------------------------------------------- |
| `services/phase2_case_contract.py`             | build_phase2_case_overlays | VAE overlay 부착 통과                          |
| `services/phase2_case_family_aggregator.py`    | overlay input 집계         | UnsupervisedCase(VAE-01) overlay 생성          |
| `services/phase2_family_policy.py`             | family 요약                | `build_unsupervised_policy_summary`(:153) 포함 |
| `services/phase2_lane_sort.py`                 | lane tier 정렬             | overlay 정렬 공유                              |
| `services/phase2_case_set_orchestrator.py`     | case 라우팅                | build_unsupervised_cases 디스패치              |
| `services/phase2_unsupervised_case_builder.py` | VAE case 조립              | VAE 본체                                       |
| `services/phase2_training_service.py`          | 학습                       | UnsupervisedDetector(VAE/IF) 백본              |
| `services/subdetector_tiers.py`                | tier 조회                  | contract/aggregator/lane_sort 공유             |
| `models/phase2_case.py`                        | 자료형                     | UnsupervisedCase·Phase2CaseSet 핵심            |

→ 위 파일들은 **삭제 안 함**. 단 내부의 relational/duplicate/intercompany **family 분기만 외과 제거**(분기는 깔끔히 분리돼 제거 가능).

## 2. 삭제 대상 파일 (family 가지 — 통삭제 가능)

| 파일                                           | family     | 비고                                                                             |
| ---------------------------------------------- | ---------- | -------------------------------------------------------------------------------- |
| `detection/graph_detector.py`                  | graph      | dead                                                                             |
| `detection/graph_rules.py`                     | graph      | GR01:174 GR03:261. 단 test_boolean_utils.py:7가 `_filter_edges` import           |
| `detection/intercompany_matcher.py`            | IC         | class:491                                                                        |
| `detection/intercompany_rules.py`              | IC         | ic01:410 ic02:520 ic03:553. ⚠️ `extract_ic_prefixes:49` 이전 후 삭제             |
| `detection/relational_detector.py`             | relational | class:232, _build_registry R01~R07:270-341                                       |
| `detection/relational_rules.py`                | relational | R01:40~R07:380. ⚠️ `:191-194` is_intercompany mask는 잔존 컬럼 읽음(파일째 삭제) |
| `detection/relational_graph_features.py`       | relational | 전체                                                                             |
| `detection/duplicate_detector.py`              | duplicate  | class:30, registry L2-03a~d:91-121                                               |
| `detection/duplicate_rules.py`                 | duplicate  | b05a:44 b05b:62 b05c:157 b05d:260                                                |
| `services/phase2_relational_case_builder.py`   | relational | build_relational_cases                                                           |
| `services/phase2_duplicate_case_builder.py`    | duplicate  | build_duplicate_cases                                                            |
| `services/phase2_intercompany_case_builder.py` | IC         | build_intercompany_cases                                                         |

**timeseries는 삭제 안 함** — 설계상 PHASE1-2 자기큐로 재설계 예정. `timeseries_detector.py`/`timeseries_rules.py`/`phase2_timeseries_case_builder.py` 잔류(당분간 phase2 lane).

## 3. pipeline.py 배선 (제거)

| 줄        | 내용                                    | 조치       |
| --------- | --------------------------------------- | ---------- |
| 1465      | family_funcs `("relational", ...)`      | 제거       |
| 1466      | family_funcs `("duplicate", ...)`       | 제거       |
| 1467      | family_funcs `("intercompany", ...)`    | 제거       |
| 1464      | family_funcs `("timeseries", ...)`      | **잔류**   |
| 1611-1652 | `_try_relational_detection`             | 제거       |
| 1654-1682 | `_try_duplicate_detection`              | 제거       |
| 1684-1715 | `_try_intercompany_detection`           | 제거       |
| 1717-1746 | `_try_graph_detection` (dead)           | 제거       |
| 1693      | `enable_intercompany_detection` getattr | 제거       |
| 1723      | `enable_graph_detection` getattr        | 제거       |
| 1002-1003 | relational_continuity overlay 입력      | 제거(연쇄) |

config 플래그: `config/settings.py:579 enable_graph_detection`, `services/analysis_service.py:45`, `dashboard/components/company_manager.py:118,144` UI 토글.

## 4. registry / metrics / export (해당 줄 제거)

| 파일                                | graph(GR01/GR03)                              | IC(IC01/02/03)                               | relational(R0x)                           | duplicate(L2-03a~d)  |
| ----------------------------------- | --------------------------------------------- | -------------------------------------------- | ----------------------------------------- | -------------------- |
| `detection/constants.py`            | 148-149,219-220                               | 123-125,194-196                              | 126-132,197-203,376 라벨/severity/profile | 95-98,166-169,367    |
| `detection/rule_detail_metadata.py` | 924-925,951-952                               | 784-785,815-816,840-841                      | — (별도 entry 없음)                       | 102-105,430-489      |
| `detection/rule_scoring.py`         | 408 주석                                      | 408 주석                                     | —                                         | 210/217/224/231(a~d) |
| `detection/score_aggregator.py`     | 146,683-687                                   | 146,683-687                                  | —                                         | —                    |
| `metrics/rule_mapping.py`           | 41-42,101-102,140-141,202-203,284-285,469-470 | 38-40,98-100,137-139,196,199,281-283,466-468 | —                                         | —                    |
| `metrics/ground_truth_evaluator.py` | 683                                           | 682                                          | —                                         | —                    |
| `export/phase1_case_view.py`        | 3240 (_MACRO_RULES)                           | 1768-1785                                    | —                                         | —                    |
| `detection/phase1_case_builder.py`  | 186-190 제외집합                              | 186-190,455-465,537-539                      | —                                         | —                    |

⚠️ **잔존(절대 건드리지 말 것)**: 위 파일들의 **L3-03 / is_intercompany** 항목.
- L3-03: constants.py:104,175,577-578 / rule_scoring.py:259-260 / rule_detail_metadata.py:525-526 / rule_mapping.py(다수) / phase1_case_builder.py:159,374,536 / export:1762-1766,42,3194,3241 / fraud_layer.py:160,296 / topic_scoring.py:43-48
- is_intercompany 컬럼: pattern_features.py:50-203 / engine.py:77,169 / preprocessing/constants.py:92 / db schema·queries / nlp_rules.py:259-267 / prompt_presets.py:199
- L2-03 base: fraud_layer.py:268, fraud_rules_groupby.py:872(+237-336,442-456). constants.py:94,165,554 / rule_scoring.py:203 / rule_detail_metadata.py:417-428.

## 5. 테스트 영향

**전용(파일째 삭제 후보)**: graph — test_graph_detector.py. IC — test_intercompany_matcher.py, test_intercompany_matcher_pair_artifact.py, test_intercompany_reciprocal_flow.py, test_intercompany_timing_domain.py, test_intercompany_v7_fixed3_smoke.py, test_phase2_intercompany_case_builder.py. relational — test_relational_rules/detector/graph_features/edge_artifact.py, test_phase2_relational_case_builder.py, test_relational_v31/v33*. duplicate — test_duplicate_detector/pair_artifact/performance.py, test_phase2_duplicate_case_builder.py, test_duplicate_pair_tier.py, test_duplicate_v31/v32/v33*.

**혼재(해당 줄 수정)**: test_boolean_utils.py:7, test_audit_coverage_contract.py:9,71,85,87, test_subdetector_tiers_schema.py:45-47, test_ground_truth_evaluator.py:708,712, test_phase1_case_view.py:488,1060-1062, test_score_aggregator.py:211,220, test_rule_detail_metadata.py:58-62,139-140,186-189, test_phase1_document_units.py:193-211, test_phase1_case_builder.py:601-608,919-925,1160-1221, test_phase1_flow_units.py:384-662, test_phase2_case_contract/family_aggregator/lane_sort/training_service/case_set_orchestrator/inference_service*, test_phase2_subdetector_grid.py, test_phase2_family_matrix.py, test_tab_review_queue_workflow.py:101, test_dashboard_services.py / test_phase2_inference_service.py(enable_graph_detection fixture).

**잔존 보존**: test_phase1_flow_units.py:538 `{"IC03","L3-03"}` 중 L3-03.

## 6. 권장 단계 순서 (위험 낮은 것 → 높은 것, 각 단계 pytest 회귀 확인)

- **Inc-B (graph 완전 삭제)** ★1순위 가장 안전: dead·VAE 무관·격리. graph_detector/rules 삭제 + _try_graph_detection + 플래그 + registry GR + test 정리.
- **Inc-A (실행 중단)**: pipeline family_funcs에서 relational/duplicate/intercompany 제거(timeseries 잔류). 탐지 레벨 차단. shared 인프라 미변경(orchestrator는 결과 없으면 graceful 가정 — 검증 필요).
- **Inc-IC (IC 완전 삭제)**: extract_ic_prefixes 이전 먼저 → intercompany_matcher/rules + phase2_intercompany_case_builder + orchestrator/aggregator/lane_sort/contract/training의 IC 분기 + registry IC + test.
- **Inc-REL (relational 삭제)**: R02/R04/R06 드롭 + R01/R05/R07은 옛코드 삭제(재구현은 Phase 3 별도) + phase2_relational_case_builder + shared 분기 + test.
- **Inc-DUP (duplicate 삭제)**: duplicate_detector/rules + phase2_duplicate_case_builder + shared 분기 + L2-03a~d registry + test. (L2-03 base 무변경)

각 increment = 1 논리 커밋. 회귀 가드: `uv run pytest` 신규 실패 0(전용 테스트 삭제분 제외).
