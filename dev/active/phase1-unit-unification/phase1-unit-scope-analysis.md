# PHASE1 단위 통일(P2) 범위 분석

작성일: 2026-06-04
작업 범위: read-only 코드 탐색 + 리팩터 범위안 작성
기준 문서: `docs/spec/UNIT_MEASUREMENT_POLICY.md`
브랜치 확인: `git branch --show-current`는 로컬 정책에서 차단됨. `.git/HEAD` 기준 현재 브랜치는 `develop`.

## 0. 기준 정책 요약

`UNIT_MEASUREMENT_POLICY.md`의 목표 상태는 3층 모델이다.

| 층 | 정책 |
|---|---|
| 탐지 단위 | 정답과 측정이 붙는 1차 단위. `document`, `flow`만 허용 |
| 룰 분류 | 각 룰은 `document-rule` 또는 `flow-rule`. 구현용 태그이며 측정 분모가 아님 |
| 집계 뷰 | 기존 `case`의 위치. 속성 `GROUP BY` 표시 레이어이며 자체 정답, 분모, 독립 점수 없음 |

핵심 가드:

- `row`는 단위가 아니라 `document_id + row_index` 증거 포인터다.
- `flow`는 `flow_id + link_key`를 가진 1차 객체여야 한다.
- truth/측정은 `document XOR flow`에서만 수행하고 집계 뷰를 분모로 쓰지 않는다.

## 1. 현재 단위 사용 지도

### 1.1 파이프라인 단계별 실제 단위

| 단계 | 파일/계약 | 현재 실제 단위 | 관찰 |
|---|---|---|---|
| 탐지기 출력 | `src/detection/base.py::DetectionResult` | row-index matrix | `flagged_indices`, `scores`, `details`가 모두 입력 DataFrame index 기준이다. `RuleFlag.flagged_count/total_count`도 대부분 행 수 기준이다. |
| 탐지기 내부 그룹화 | `integrity_layer.py`, `fraud_rules_groupby.py`, `intercompany_matcher.py`, `graph_rules.py`, `variance_rules.py` | 혼합: document group, row score, pair/cycle/account metadata | document나 pair를 계산해도 최종 `details`는 row index로 다시 펼친다. pair/cycle/account 결과는 대부분 metadata/artifact로 남는다. |
| row score 집계 | `src/detection/score_aggregator.py::aggregate_scores` | row | `details`를 concat한 뒤 `L1/L2/L3/L4` family별 row score, `flagged_rules`, `review_rules`, `risk_level`을 만든다. |
| anomaly_flags 적재 | `src/db/loader.py::_build_anomaly_flags_df` | row/document pointer | `DetectionResult.details`를 melt하여 `anomaly_flags`에 적재한다. confirmed `details > 0` 중심이며 row 위치와 전표 식별자가 저장/복원된다. |
| PHASE1 case builder 입력 | `src/detection/phase1_case_builder.py::_collect_raw_hits` | row hit + document pointer | `details` 또는 `row_annotations`에서 `_RawHit(row_index, document_id, record_id, score...)`를 만든다. document는 원본 DataFrame에서 보강된다. |
| PHASE1 case grouping | `src/detection/phase1_case_builder.py::_build_cases` | 속성 bucket case | `(theme_id, case_key)`로 group한다. `case_key`는 사용자/월, 거래처/금액밴드/근접기간, 회사쌍/거래상대/월 등 표시용 bucket이다. |
| case scoring | `phase1_case_builder.py::_priority_score`, `_composite_sort_score` | case bucket score | `priority_score`, `composite_sort_score`, topic score가 `CaseGroupResult`에 직접 저장된다. 정책상 집계 뷰는 독립 점수가 없어야 하므로 목표 상태와 충돌한다. |
| dashboard/export queue | `dashboard/tab_phase1.py`, `src/export/phase1_case_view.py` | case queue | `CaseGroupResult`를 사용자 큐의 1차 객체처럼 렌더링한다. drill-down은 case 안의 documents/raw_rule_hits로 내려간다. |
| PHASE2 overlay/linker | `src/services/phase2_case_contract.py`, `phase2_case_phase1_linker.py` | PHASE1 case id 중심 + row/doc link | PHASE2 overlay는 `phase1_case_id`에 붙는다. linker는 PHASE1 `raw_rule_hits.row_index/document_id/doc_line/company_doc`를 역인덱스로 사용한다. |

### 1.2 row를 단위처럼 쓰는 곳

| 위치 | row 단위 사용 |
|---|---|
| `DetectionResult.flagged_indices/scores/details` | 모든 탐지 결과의 기본 계약이 row index다. |
| `score_aggregator.aggregate_scores()` | row-level `anomaly_score`, `risk_level`, `flagged_rules`, `review_rules`를 만든다. |
| `phase1_case_builder._collect_raw_hits()` | row별 raw hit를 수집하고 `row_index`가 raw evidence identity의 핵심이다. |
| `phase1_case_builder._build_cases()` | `theme_row_pairs`가 `(theme_id, row_index)`로 seed된다. case 그룹도 row hit에서 출발한다. |
| `src/db/loader.py::_build_anomaly_flags_df()` | `details` row matrix를 `anomaly_flags`로 변환한다. |
| `src/db/batch_reader.py` | `anomaly_flags`를 다시 pseudo `DetectionResult`로 복원하며 row mapping fallback을 가진다. |
| `src/services/phase2_case_phase1_linker.py` | position/doc/doc_line/company_doc 매칭 모두 PHASE1 `raw_rule_hits`의 row pointer를 사용한다. |
| dashboard low-signal queue | `flagged_rules/review_rules/anomaly_score` row 컬럼을 별도 후보 queue로 재집계한다. |

정책상 row는 유지 가능하지만, 단위가 아니라 document 내부 증거 포인터로 내려가야 한다. 현재는 score, flag, DB 적재, case seed의 중심 단위다.

### 1.3 flow가 case_key 문자열로만 암묵 존재하는 곳

| 흐름 후보 | 현재 암묵 처리 | 문제 |
|---|---|---|
| 중복 지급 `L2-02` | detector는 거래처/금액/기간/문서 reference로 후보를 잡고 row score로 펼친다. case key는 `counterparty / amount_band / near_period`다. | `flow_id`가 없고 링크된 문서 집합이 1차 객체가 아니다. |
| 중복 전표 `L2-03` | document signature, exact/fuzzy/split/serial pair를 계산하지만 `details["L2-03"]` row score와 optional pair artifact로 흩어진다. | 중복 pair/set이 flow로 승격되지 않는다. case key는 실제 pair identity보다 넓은 bucket이다. |
| 역분개/상계 `L2-05` | 원거래와 후속 전표 관계를 row score/annotation으로 표현한다. | 원거래-역분개 링크키와 `flow_id`가 없다. |
| 관계사 대사 `IC01~IC03` | `intercompany_matcher.py`가 pair artifact를 metadata에 제공하고 row score/floor로도 반영한다. | 회사쌍 양방향 대사 flow가 PHASE1 1차 객체가 아니라 sidecar다. |
| 순환거래 `GR01` | graph detector가 cycle 후보를 metadata/macro finding으로 제공하고 document ids를 붙인다. | 그래프 경로 `A->B->C->A`가 `flow_id` 단위로 저장되지 않는다. |
| 관계사 theme case | case key는 `company_pair / counterparty / period_month`다. | flow link가 아니라 표시 bucket이다. 서로 다른 IC pair/cycle이 한 case로 섞일 수 있다. |

## 2. 정책 대비 갭 진단

### 2.1 flow 1차 객체 부재

현재 모델에는 `FlowResult`, `FlowRef`, `flow_id`, `link_key`, `flow_type`, `member_documents` 같은 1차 flow 객체가 없다.

대신 흐름성 탐지는 다음 방식으로 암묵 처리된다.

| 유형 | 암묵 처리 위치 | 현재 산출 |
|---|---|---|
| 중복 | `fraud_rules_groupby.py`, PHASE2 duplicate case builders | row score, duplicate subtype annotation, pair artifact/diagnostic |
| 내부거래 | `intercompany_matcher.py`, `intercompany_rules.py` | row score, `ic_pair_artifact`, `row_sidecar`, IC01~IC03 |
| 순환 | `graph_rules.py`, `phase1_case_builder._build_graph_macro_findings` | GR01/GR03 metadata, candidate documents, macro finding |

정책상 이들은 집계 뷰가 아니라 Layer 1 `flow`다. 따라서 후속 구현에서 detector 출력과 case builder 사이에 `flow` 승격/정규화 단계가 필요하다.

### 2.2 case가 두 종류로 섞인 지점

`docs/spec/DETECTION_RULES.md §2.0.5`의 case key 표는 사실상 집계 뷰 기준이다.

| §2.0.5 case key | 정책상 분류 | 현재 위험 |
|---|---|---|
| 회사 / 전표유형 / 적재배치 | 집계 뷰 | 여러 document integrity hit가 한 bucket으로 묶여 독립 case 점수를 가진다. |
| 사용자 / 프로세스 / 월 | 집계 뷰 | control document들이 사용자월 bucket으로 합쳐지고 `priority_score`가 생긴다. |
| 거래처 / 금액밴드 / 근접기간 | 집계 뷰 또는 flow 후보 혼합 | 중복 flow의 링크키와 비슷하지만 금액밴드라 실제 flow identity가 아니다. |
| 사용자 / 계정군 / 월말 윈도우 | 집계 뷰 | timing document들을 표시 bucket으로 묶는다. |
| 계정군 / 문서유형 / 월 | 집계 뷰 | logic document들을 표시 bucket으로 묶는다. |
| 프로세스 / 계정군 / 월 | 집계 뷰 | statistical/account signal과 document hits가 섞인다. |
| 회사쌍 / 거래상대 / 월 | 집계 뷰 또는 flow 후보 혼합 | IC pair/cycle flow identity가 아니라 bucket이다. |

섞임의 핵심 지점은 `CaseGroupResult`다. 이 모델은 `case_key/case_key_parts`와 동시에 `documents`, `raw_rule_hits`, `priority_score`, `composite_sort_score`, `topic_scores`를 가진다. 즉 표시 bucket, 증거 묶음, 사용자 큐 점수가 한 객체에 결합되어 있다.

### 2.3 truth/분모 단위 혼합 가능 지점

코드 탐색 범위에서 PHASE1 운영 코드가 직접 truth 분모를 계산하는 단일 지점은 확인하지 않았다. 다만 다음 문서/테스트/진단 계약이 혼합 위험을 가진다.

| 위치 | 위험 |
|---|---|
| `docs/spec/DETECTION_RULES.md §2.0.6` | `Row-level anomaly score`를 개발자 검증/위험 등급 분류에 사용한다고 명시한다. 새 정책에서는 row score는 증거 포인터 속성으로 격하되어야 한다. |
| `docs/spec/DETECTION_RULES.md` D01/D02 | D01/D02는 계정 group truth/coverage를 별도로 말한다. 새 정책의 document/flow-only truth와 충돌하므로 macro coverage로 분리해야 한다. |
| `tests/modules/test_detection/test_phase1_case_builder*.py` | case priority와 composite sorting이 truth capture 성격의 회귀 가드로 쓰인다. 집계 뷰 독립 점수 금지와 충돌한다. |
| `tests/phase1_rulebase/test_rule_documents_amount.py` | `raw_rule_hits` 기반 document 복구 테스트는 새 정책과 잘 맞지만, stale `flagged_rules` row 컬럼과 병존한다. |
| Phase2 diagnostic tests | `phase1_case_result_documents`, `phase1_case_count`를 baseline으로 쓰는 테스트가 있다. 새 정책에서는 baseline이 document/flow set이어야 한다. |

## 3. 32룰 document/flow 분류표

이 표는 측정 분모가 아니라 구현 정보다. `flow-rule`은 탐지 전후에 전표 링크 단계와 `flow_id`가 필요하다는 뜻이다.

| Rule | 이름 | 현재 주 출력 | 정책 분류안 | 필요한 링크키/비고 |
|---|---|---|---|---|
| L1-01 | Unbalanced Entry | document group 계산 후 row flag | document-rule | `document_id`; row는 불균형 전표 내부 라인 포인터 |
| L1-02 | Missing Required Field | row flag | document-rule | `document_id`; 누락 라인을 evidence pointer로 유지 |
| L1-03 | Invalid Account | row flag | document-rule | `document_id`; 계정 라인 pointer |
| L1-04 | Exceeded Approval Limit | row/document amount flag | document-rule | `document_id`, approval policy |
| L1-05 | Self Approval | row/document approval flag | document-rule | `document_id`, created_by/approved_by |
| L1-06 | Segregation of Duties Violation | row/document control flag | document-rule | `document_id`, role/process policy |
| L1-07 | Skipped Approval | row/document approval flag | document-rule | `document_id`, approval required basis |
| L1-08 | Wrong Fiscal Period | row/document date flag | document-rule | `document_id`, fiscal calendar |
| L1-09 | Approval Date Missing | row/document approval metadata flag | document-rule | `document_id` |
| L2-01 | Just Below Approval Threshold | row/document amount band | document-rule | 단일 전표 금액과 승인한도. 반복/분할 패턴으로 확장하면 별도 flow 후보 |
| L2-02 | Duplicate Payment | row score from duplicate candidates | flow-rule | 거래처 + 금액 + 근접기간 + reference/payment doc; duplicate payment set |
| L2-03 | Duplicate Entry | document signature/pair 계산 후 row score | flow-rule | 문서 signature + reference/text/amount/date + linked duplicate documents |
| L2-04 | Expense Capitalization Signal | same-document account mix | document-rule | `document_id`; 자산/비용 라인 pointer |
| L2-05 | Reversal Pattern | row/review annotation | flow-rule | 원거래 + 역분개/상계 전표 링크, 금액/계정쌍/기간/reference |
| L3-01 | Misclassified Account | row semantic mismatch | document-rule | `document_id`, process/account semantic metadata |
| L3-02 | Manual Entry Override | row/source control signal | document-rule | `document_id`, source/approval context |
| L3-03 | Related Party Transaction Review Signal | row related-party/IC population signal | document-rule | 단일 전표의 related-party 표시. IC 대사/순환은 IC/GR flow로 분리 |
| L3-04 | Period-start/end Closing Review Candidate | row date window | document-rule | `document_id`, posting date/fiscal period |
| L3-05 | Weekend Posting | row calendar signal | document-rule | `document_id`, calendar |
| L3-06 | After-hours Posting | row timestamp signal | document-rule | `document_id`, created_at/timezone |
| L3-07 | Posting-Document Date Gap | row date gap | document-rule | `document_id`, posting/document date |
| L3-08 | Missing or Corrupted Description | row text quality | document-rule | `document_id`, line/header text pointer |
| L3-09 | Suspense Aging | row/account aging proxy | document-rule | 현재 JE row proxy. 진짜 open-item lifecycle이 도입되면 flow-like clearing link 검토 필요 |
| L3-10 | High-risk Account Use | row account list/context | document-rule | `document_id`, sensitive account list |
| L3-11 | Revenue Cutoff Mismatch | row/document evidence dates | document-rule | `document_id`, invoice/shipment/delivery evidence |
| L3-12 | Work Scope Excess Review | user/process aggregate review-only score | review-population (확정 2026-06-04) | 사용자 업무범위 모집단/무리 신호. truth 분모 금지. 후속 review-population coverage/집계 뷰에서 다룸 |
| L4-01 | Revenue Outlier | row/document amount distribution | document-rule | `document_id`; account/period distribution은 scoring context |
| L4-02 | Benford Violation | account/process macro finding | 결정 필요 | 현재는 group/population signal. 새 정책상 집계 뷰로 분리하거나, document pointer를 가진 document-rule 보조 evidence로 재정의해야 함 |
| L4-03 | High Amount Outlier | row/document amount outlier | document-rule | `document_id`, materiality/distribution context |
| L4-04 | Rare Debit-Credit Account Pair | document account-pair rarity | document-rule | `document_id`, debit/credit semantic pair |
| L4-05 | Abnormal Hours Cluster | user/time cluster row score | review-population (확정 2026-06-04) | 사용자/시간대 cluster 모집단 신호. truth 분모 금지. 후속 review-population coverage/집계 뷰에서 다룸 |
| L4-06 | Batch Posting Outlier | batch/user/source row score | review-population (확정 2026-06-04) | batch/user/source 무리 신호. truth 분모 금지. 후속 review-population coverage/집계 뷰에서 다룸 |

보조 surface:

| Rule | 정책상 위치 |
|---|---|
| IC01/IC02/IC03 | flow-rule 보조 finding. 회사쌍 양방향 대사 flow 필요 |
| GR01 | flow-rule 보조 finding. 그래프 경로 `A->B->C->A` flow 필요 |
| GR03 | flow-rule 또는 graph sidecar. transfer-pricing edge/link 필요 |
| D01/D02 | 집계 뷰/account-process macro coverage. document/flow truth 분모 금지 |

## 4. 리팩터 범위안

### 4.1 신규로 필요한 것

| 신규 요소 | 목적 | 후보 파일 |
|---|---|---|
| `DetectionUnitRef` | `unit_type=document|flow`, `unit_id`, evidence row pointers를 공통 표현 | `src/models/phase1_case.py` 또는 신규 `src/models/phase1_unit.py` |
| `Phase1DocumentUnitResult` | document 1차 탐지 결과와 점수/근거 | 신규 모델 |
| `Phase1FlowUnitResult` | flow 1차 탐지 결과. `flow_id`, `flow_type`, `link_key`, `member_document_ids`, `evidence_rows` | 신규 모델 |
| flow builder/linker | row/document raw hits와 detector artifacts를 flow로 승격 | 신규 `src/detection/phase1_flow_builder.py` 또는 case builder 앞 단계 |
| aggregate view 모델 | 기존 `CaseGroupResult`의 표시 bucket 역할을 명시 | `CaseGroupResult` 유지/개명/래핑 중 결정 필요 |
| unit-level scoring | `priority_score`를 document/flow unit에 귀속 | `phase1_case_builder.py`, `topic_scoring.py`, `score_aggregator.py` |

### 4.2 분리/개명할 것

| 현재 | 목표 |
|---|---|
| `CaseGroupResult` | 집계 뷰 모델로 내리거나, compatibility wrapper로 유지 |
| `case_key/case_key_parts` | `aggregate_view_key` 성격으로 개명 후보 |
| `priority_score/composite_sort_score/topic_scores` on case | document/flow unit score로 이동. 집계 뷰는 unit score의 max/count/sum 등 표시값만 보유 |
| `raw_rule_hits.row_index` | `evidence_rows` 안의 pointer로 유지 |
| `documents` in case | document unit refs 또는 flow member document refs로 분리 |
| `macro_findings` | 집계 뷰/account-process macro context로 분리. truth denominator 금지 명시 |

### 4.3 유지할 것

| 유지 대상 | 이유 |
|---|---|
| `RawRuleHitRef`의 row pointer 필드 | 정책상 row는 증거 포인터로 필요하다. PHASE2 linker도 의존한다. |
| `flagged_rules` / `review_rules` 분리 | confirmed vs review-only 계약은 정책과 부합한다. 단, row 컬럼 중심에서 document/flow evidence로 귀속해야 한다. |
| `anomaly_flags` row-level DB | drill-down과 감사 증거 pointer로 유지 가능. 다만 measurement source로 쓰면 안 된다. |
| `case_key` 기반 dashboard UX | 표시 layer로 유지 가능. 이름/문구와 score 의미만 바꿔야 한다. |
| PHASE2 linker의 doc_line/company_doc 매칭 | 새 unit 결과와 연결하는 compatibility path로 재사용 가능하다. |

### 4.4 서브단계와 위험/의존 순서

| 단계 | 목표 | 주요 파일 | 위험 |
|---|---|---|---|
| P2-0 문서/계약 정리 | `DETECTION_RULES.md §2.0`의 row/case 용어를 정책과 동기화. `case`를 aggregate view로 재정의 | `docs/spec/DETECTION_RULES.md`, `docs/spec/DECISION.md` | 중간. 문서가 구현보다 앞서가므로 호환 용어 필요 |
| P2-1 모델 추가 | 기존 모델은 유지하고 document/flow unit 모델을 additive로 추가 | `src/models/phase1_case.py` 또는 신규 모델, tests | 높음. schema/JSON artifact 변화 |
| P2-2 detector output adapter | 기존 row matrix를 유지하되 document unit으로 귀속하는 adapter 추가 | `phase1_case_builder.py`, `score_aggregator.py`, detector metadata | 높음. row score와 document score 중복 위험 |
| P2-3 flow builder | L2-02/L2-03/L2-05/IC/GR artifacts에서 flow unit 생성 | `fraud_rules_groupby.py`, `anomaly_rules_reversal.py`, `intercompany_matcher.py`, `graph_rules.py`, 신규 builder | 매우 높음. 링크키 안정성, dedup, truth coverage 영향 |
| P2-4 scoring 이동 | `priority_score/composite_sort_score/topic_scores`를 document/flow unit score로 이동하고 aggregate view는 derived summary만 노출 | `phase1_case_builder.py`, `topic_scoring.py`, `phase1_case_view.py`, dashboard | 매우 높음. 사용자 큐 정렬과 기존 tests 대규모 변경 |
| P2-5 compatibility artifacts | `CaseGroupResult` artifact를 읽는 dashboard/export/Phase2가 깨지지 않게 변환 layer 제공 | `phase1_case_artifacts.py`, `phase1_case_view.py`, `phase2_case_contract.py`, `phase2_case_phase1_linker.py` | 높음. 기존 저장 artifact backward compat |
| P2-6 DB/export 반영 | unit refs와 aggregate views를 DB/export에 반영. `anomaly_flags`는 evidence pointer로 유지 | `src/db/schema.py`, `loader.py`, `batch_reader.py`, `excel_exporter.py`, `pdf_exporter.py` | 높음. migration/복원 경로 |
| P2-7 테스트 재정렬 | row/case truth 테스트를 document/flow unit 테스트로 전환 | `tests/modules/test_detection/test_phase1_case_builder*.py`, phase1_rulebase, phase2 service tests | 높음. 기존 truth-capture wording 수정 필요 |

## 5. Ripple 영향

검색 키: `CaseGroupResult`, `composite_sort_score`, `priority_score`, `case_key`, `phase1_case`, `case_id`.

### 5.1 dashboard

| 파일 | 소비 |
|---|---|
| `dashboard/tab_phase1.py` | case queue, rule case master/detail, selected `case_id`, `priority_score`, `composite_sort_score`, drill-down, session state key |
| `dashboard/phase1_display.py` | priority band 표시 |
| `dashboard/tab_export.py` | PHASE1 case export 포함 여부 |

깨질 지점: `case_id` identity, case score/band 의미, master/detail 계층명, case drilldown payload.

### 5.2 exports/reports

| 파일 | 소비 |
|---|---|
| `src/export/phase1_case_view.py` | 핵심 projection. queue, summary, drilldown, rule docs/cases, low-signal rows 모두 `CaseGroupResult` 기반 |
| `src/export/phase1_case_label.py` | `case_key_parts` 자연어 라벨 |
| `src/export/excel_exporter.py`, `pdf_exporter.py` | top cases와 PHASE1 summary |
| `src/export/audit_evidence.py` | row `flagged_rules` 기반 evidence |

깨질 지점: `case_key` 개명, aggregate view score 제거, unit score 추가, macro finding 위치 변경.

### 5.3 Phase2/services

| 파일 | 소비 |
|---|---|
| `src/services/phase2_case_contract.py` | `CaseGroupResult`를 feature/provenance/overlay 입력으로 사용 |
| `src/services/phase2_case_phase1_linker.py` | PHASE1 `raw_rule_hits.row_index/document_id/hash`로 PHASE2 native case에 `phase1_case_refs` 부착 |
| `src/services/phase2_training_service.py` | PHASE1 case feature contract/report metadata |
| `src/services/phase2_*_case_builder.py` | native case id/row refs와 PHASE1 refs 계약 |
| `src/services/phase3_case_narrative_service.py`, `src/llm/*case*` | case narrative source |

깨질 지점: `phase1_case_id`가 aggregate view id인지 unit id인지 모호해진다. 새 정책에서는 PHASE2 overlay 기준을 document/flow unit id로 바꾸고 aggregate view refs는 표시 전용으로 두는 결정이 필요하다.

### 5.4 DB/config

| 파일 | 소비 |
|---|---|
| `src/db/loader.py`, `batch_reader.py`, `schema.py`, `queries.py`, `migration.py` | batch metadata에 phase1 case artifact path/count/schema 저장, anomaly_flags row evidence 저장 |
| `config/phase1_case.yaml` | grouping key, priority floors, topic scoring 설정 |
| `config/phase2_review_band.yaml` | PHASE1 단독 큐 정렬 설명에 `priority_band -> composite_sort_score -> priority_score` 명시 |

깨질 지점: artifact schema version, `phase1_case_count` 의미, config 이름(`phase1_case`)과 score 설정 의미.

### 5.5 tests

| 영역 | 영향 |
|---|---|
| `tests/modules/test_detection/test_phase1_case_builder*.py` | case priority, floors, composite_sort_score, artifact roundtrip를 직접 검증 |
| `tests/phase1_rulebase/*` | rule documents amount, stale flagged_rules, case natural label |
| `tests/modules/test_services/test_phase2_*` | PHASE1 case contract, linker refs, training report metadata |
| `tests/modules/test_llm/*` | case narrative priority_score/case_id fixtures |
| `tests/modules/test_detection/test_score_aggregator.py` | row score/flagged_rules/review_rules 계약 |

## 6. 사용자 결정 필요 지점

| 결정 | 옵션 A | 옵션 B | 트레이드오프 |
|---|---|---|---|
| `CaseGroupResult` 처리 | 유지하고 `AggregateViewResult` 역할로 문서화/compat 유지 | 모델을 재구성해 `DocumentUnit/FlowUnit/AggregateView` 분리 | A는 점진 구현이 쉽지만 이름 혼동 지속. B는 정책에 깨끗하지만 dashboard/export/Phase2 파급이 큼 |
| PHASE1 artifact schema | 기존 `Phase1CaseResult.cases` 유지 + 신규 `units` 추가 | 신규 artifact를 만들고 기존 artifact는 변환기로만 지원 | 전자는 backward compat 유리. 후자는 장기 명확성 유리 |
| score 위치 | `priority_score`를 unit에 추가하고 case에는 derived max/summary 유지 | case score를 제거하고 view에서 동적 계산 | 전자는 UI 안정성 유리. 후자는 정책 엄격하지만 dashboard 대수술 |
| flow builder 위치 | detector별로 flow metadata를 직접 산출 | detector 후 adapter가 row/details/artifact를 flow로 승격 | detector별 산출은 정확하지만 파일별 변경 큼. adapter는 빠르지만 링크 정보 누락 가능 |
| L4-02 처리 | 32룰 내 document-rule 보조 evidence로 재정의 | canonical 32에는 남기되 measurement에서는 macro aggregate view로만 분리 | 전자는 정책 일관성이 높지만 Benford 의미가 왜곡될 수 있음. 후자는 현재 의미 보존, 단 32룰 document/flow 표와 충돌 |
| D01/D02 | account/process aggregate view로 유지 | document/flow unit에 보조 context로만 연결 | 기존 문서와 맞추려면 aggregate 유지가 자연스럽지만, truth/분모 금지 가드가 필요 |
| PHASE2 overlay 기준 | 계속 `phase1_case_id`에 붙이고 내부적으로 unit refs 추가 | overlay 기준을 `unit_id`로 전환하고 aggregate view는 presentation only | 전자는 migration 쉬움. 후자는 정책 정합성이 높지만 Phase2 tests/contract 전면 수정 |
| row score 유지 | 개발/호환용 내부 score로 유지 | document/flow score만 남기고 row score 제거 | 유지가 현실적. 제거는 DB/export/대시보드/테스트 파급이 매우 큼 |

## 7. 권장 구현 방향 초안

1. `CaseGroupResult`를 즉시 제거하지 말고 aggregate view 호환 모델로 유지한다.
2. additive하게 `document_units`, `flow_units`를 artifact에 추가한다.
3. scoring은 먼저 unit에 산출하고, 기존 case score는 `max_unit_score`, `top_unit_score`, `unit_count` 기반 derived field로 전환한다.
4. flow는 `L2-02`, `L2-03`, `L2-05`, `IC01~IC03`, `GR01`부터 최소 링크키로 시작한다.
5. dashboard/export는 기존 화면을 유지하되 문구를 “Case Group”에서 “집계 뷰/검토 묶음”으로 바꾸고, drill-down의 첫 객체를 document/flow unit으로 바꾼다.
6. measurement/truth 코드는 집계 뷰와 row 컬럼을 분모로 쓰지 않도록 별도 가드를 둔다.

## 8. 멈춤 지점

이 문서는 범위 분석이다. 코드 리팩터는 수행하지 않았다.

후속 구현 전에 특히 다음 결정을 사용자 리뷰로 확정해야 한다.

- `CaseGroupResult`를 호환 aggregate view로 유지할지, 새 모델로 재구성할지.
- `priority_score/composite_sort_score`를 unit으로 이동한 뒤 aggregate view에 derived score를 남길지.
- `L4-02`를 document-rule 보조 evidence로 재정의할지, macro aggregate view로 분리할지.
- PHASE2 overlay 기준을 `phase1_case_id`에서 `unit_id`로 전환할지.
