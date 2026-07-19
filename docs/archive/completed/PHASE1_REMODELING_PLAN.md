# PHASE1 리모델링 계획

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> 최신 운영 원칙: PHASE1 리모델링의 목적은 탐지 대상을 줄여 precision을 높이는 것이 아니라, 규칙에 어긋난 후보를 1차로 넓게 포착한 뒤 case/theme 구조에서 2차 분류하는 것이다. PHASE1은 정답 라벨 또는 부정 확정 판정기가 아니며, raw hit를 정상 예외, 감사인 리뷰 대상, 고위험 후보로 나누는 기준은 중요성, 증거 강도, 고객사 예외 정책, 조합 신호, case priority다.

갱신일: 2026-04-22
상태: Draft
목적: PHASE1을 `룰별 결과 나열` 구조에서 `케이스 중심 리뷰 큐` 구조로 리모델링하기 위한 고정 계획 문서

---

## 1. 배경

- 현재 PHASE1은 recall 우선 전수 탐지에는 강점이 있다.
- 반면 결과를 룰 단위로 직접 노출하면 같은 전표가 여러 룰에 중복 노출되고, 감사자가 실제로 검토해야 할 "이상 시나리오"가 보이지 않는다.
- 따라서 탐지 엔진은 유지하되, 출력 단위와 우선순위 체계를 `theme -> case group -> drill-down`으로 재설계한다.

## 2. 목표

### 2.1 최상위 목표

- PHASE1의 미탐 방지 성격은 유지한다.
- 사용자는 더 이상 룰 번호 중심으로 보지 않고, 연관된 이상 시나리오 중심으로 본다.
- 과탐은 룰 축소가 아니라 `grouping`, `priority`, `explanation`, `exposure control`로 다룬다.

### 2.2 완료 상태 정의

- PHASE1 결과를 theme queue와 case group 단위로 생성할 수 있다.
- primary theme / secondary tags / evidence types / case priority가 계산된다.
- drill-down에는 룰 번호 나열 대신 설명 가능한 evidence tag와 대표 설명문이 붙는다.
- 사용자 노출은 설정 가능한 상위 N개 case 중심으로 제한된다.

## 3. 범위

### 3.1 포함 범위

- PHASE1 결과 모델 리모델링
- rule -> evidence type -> theme 매핑 반영
- case key template 구현
- case priority scoring 구현
- explanation template 구현
- UI/리포트 노출 계약 정리
- 관련 설정 파일과 로더 정리

### 3.2 제외 범위

- 개별 룰의 탐지 로직 자체를 대규모로 줄이거나 제거하는 작업
- Phase 2/3 탐지기 재설계
- 전체 대시보드 UX 리디자인
- 새로운 ML 모델 도입

## 4. 고정 원칙

### 4.1 탐지 원칙

- PHASE1은 계속 recall 우선이다.
- 개별 룰은 삭제하지 않는다.
- 과탐 해소는 탐지 축소보다 출력 구조 변경을 우선한다.

### 4.2 결과 원칙

- 하나의 case에는 primary theme 1개만 둔다.
- secondary tag는 허용하되 메인 정렬과 집계는 primary 기준으로 한다.
- rule raw output은 기본 사용자 화면에서 숨긴다.

### 4.3 설정 원칙

- PHASE1 case 관련 전용 설정은 `config/phase1_case.yaml`을 기준으로 한다.
- 기존 공통 설정과 의미가 완전히 같은 값은 중복 신설하지 않고 기존 키를 재사용한다.

## 5. 현재 확정된 설계 입력

- 공식 원칙 문서: [DETECTION_RULES.md](../../spec/DETECTION_RULES.md)
- 하이퍼파라미터 문서: [DETECTION_PARAMETERS.md](../../spec/DETECTION_PARAMETERS.md)
- troubleshooting 기록: [TROUBLESHOOT.md](../../spec/TROUBLESHOOT.md)
- 전용 설정 파일: [config/phase1_case.yaml](../../../config/phase1_case.yaml)

## 6. 작업 스트림

### WS-1. 설정/로더 정리

- `config/phase1_case.yaml` 구조 확정
- `config/settings.py` 로더 유지
- company override 경로 확장: `data/companies/{company_id}/phase1_case.yaml`
- 컨텍스트 객체에 `phase1_case` 주입

### WS-2. 결과 모델 재정의

- rule output -> evidence type 변환 계층 정의
- primary theme / secondary tag 계산 경로 정의
- case group 스키마 정의
- case drill-down 스키마 정의
- 기존 detection metadata와 분리된 별도 result schema 정의
- 4층 구조 result schema 정의: `Phase1CaseResult > ThemeSummary / CaseGroupResult > CaseDocumentRef / RawRuleHitRef`
- Pydantic 모델 위치 확정: `src/models/phase1_case.py`

### WS-3. Case Grouping 구현

- theme별 case key template 반영
- 실제 스키마 컬럼 매핑 적용
- fallback 규칙 반영
- case aggregation 단위 고정

### WS-4. Case Priority 구현

- amount/control/logic/behavior/repeat score 계산
- evidence type cap 반영
- repeat promotion / tie-breaker 반영
- priority band 계산

### WS-5. 설명 가능성 계층 구현

- evidence tag 표준화
- 대표 설명문 템플릿 구현
- 대표 설명문 우선순위 구현
- raw rule id 숨김 정책 반영

### WS-6. 노출/리포트 구조 전환

- 내부 full output과 사용자 exposed output 분리
- top-N case, top-N per theme 적용
- summary -> case -> drill-down 구조 반영
- 개발자 모드 / 검증 모드에서 raw rule 확인 가능 여부 정리

### WS-6a. 저장/직렬화

- canonical 저장 형식은 JSON으로 둔다.
- 저장 경로 규칙을 확정한다.
- detection metadata에는 reference만 남긴다.

### WS-7. 검증

- 설정 로더 테스트
- case grouping 단위 테스트
- case priority 단위 테스트
- e2e 샘플 데이터 점검
- datasynth 기반 회귀 확인

## 7. 구현 순서 초안

1. 설정 파일/로더/컨텍스트 정리
2. 결과 스키마와 내부 계약 정의
3. evidence type / theme / case group 계산 구현
4. case priority 및 band 구현
5. explanation layer 구현
6. output exposure 구조 반영
7. 테스트 및 datasynth 회귀 확인

## 8. 결정 로그

### D-001

- 결정: PHASE1은 recall 우선 전수 탐지를 유지한다.
- 이유: 리모델링의 목표는 미탐 감소가 아니라 결과 소비 구조 개선이다.
- 상태: 확정

### D-002

- 결정: 결과 단위는 `theme queue -> case group -> drill-down` 구조로 바꾼다.
- 이유: 룰 번호 중심 출력은 실무 리뷰 큐로 쓰기 어렵다.
- 상태: 확정

### D-003

- 결정: PHASE1 case 전용 설정은 `config/phase1_case.yaml`에 둔다.
- 이유: 탐지 룰 설정과 결과 소비 설정을 분리하기 위함이다.
- 상태: 확정

### D-004

- 결정: company override는 `data/companies/{company_id}/phase1_case.yaml` 경로를 허용한다.
- 이유: 기존 `audit_rules.yaml`, `risk_keywords.yaml` override 패턴과 일관되게 가는 편이 가장 자연스럽다.
- 상태: 확정

### D-005

- 결정: `phase1_case` 설정은 컨텍스트 객체에 직접 싣는다.
- 이유: detection layer와 case aggregation layer가 같은 설정 스냅샷을 공유해야 하며, 회사별 override가 적용된 결과를 일관되게 참조해야 한다.
- 상태: 확정

### D-006

- 결정: case/theme 결과는 기존 detection metadata에 억지로 섞지 않고, 별도 result schema로 분리한다.
- 이유: case/theme는 row-level rule flag와 성격이 달라 metadata에 섞으면 구조가 빠르게 지저분해지고 계약이 불명확해진다.
- 상태: 확정

### D-007

- 결정: 별도 result schema는 `Theme 요약`, `Case 본체`, `문서 드릴다운`, `룰 원본 참조`의 4층 구조로 둔다.
- 이유: 사용자에게 보여줄 정보와 엔진 원본 참조를 분리해야 구조가 안정적이고, drill-down과 raw rule traceability를 동시에 만족할 수 있다.
- 상태: 확정

### D-008

- 결정: `CaseGroupResult`를 사용자 노출의 기본 단위로 둔다.
- 이유: 최종 정렬, 우선순위, 설명, 드릴다운 진입점이 모두 case 중심으로 설계되어야 룰 나열 구조로 되돌아가지 않는다.
- 상태: 확정

### D-009

- 결정: 별도 result schema 모델은 Pydantic으로 구현하고 위치는 `src/models/phase1_case.py`로 둔다.
- 이유: validation, dump/load, schema 진화, UI/API/저장 연계까지 고려하면 dataclass보다 Pydantic이 적합하다.
- 상태: 확정

### D-010

- 결정: 별도 result schema의 canonical 저장 형식은 1차적으로 JSON으로 둔다.
- 이유: 초기 구현, 디버깅, 수동 검토, schema 진화가 가장 쉽고 이후 DuckDB projection은 별도로 추가할 수 있다.
- 상태: 확정

### D-011

- 결정: raw rule result -> case result 변환은 개별 룰 직후가 아니라 Phase 1 detection이 모두 끝난 뒤 별도 builder 단계에서 한 번에 수행한다.
- 이유: evidence type, theme, grouping, scoring, explanation은 전체 rule output을 모아서 계산해야 구조가 안정적이다.
- 상태: 확정

### D-012

- 결정: 변환 모듈은 detection layer 내부가 아니라 별도 builder 모듈로 두고, 추천 위치는 `src/detection/phase1_case_builder.py`로 한다.
- 이유: 룰 탐지와 케이스 조합 책임을 분리해야 detection layer가 오염되지 않는다.
- 상태: 확정

### D-013

- 결정: 기존 detection metadata에는 상세 case/theme 구조를 넣지 않고 최소 참조만 남긴다.
- 이유: metadata 본문에 상세 구조를 싣기 시작하면 row-level 결과와 case-level 결과가 다시 섞인다.
- 상태: 확정

### D-014

- 결정: `run_id`는 `phase1case_{company_id}_{batch_id}_{utc_ts}` 규칙을 기본으로 생성한다.
- fallback:
  - `batch_id`가 없으면 `phase1case_{company_id}_{dataset_id}_{utc_ts}`
  - 그것도 없으면 `phase1case_default_{utc_ts}`
- 예: `phase1case_KR01_batch42_20260422T031522Z`
- 이유: 사람이 봐도 의미가 있고, 회사/배치 단위 추적과 정렬이 쉽다.
- 상태: 확정

### D-015

- 결정: JSON 저장 경로는 `artifacts/phase1_cases/{company_id}/{run_id}.json`을 기본 규칙으로 한다.
- 이유: 회사별 탐색성이 좋고, 기존 detection 산출물과 섞이지 않으며, phase1 case 결과를 별도 계층으로 분리할 수 있다.
- 상태: 확정

### D-016

- 결정: `schema_version`은 문자열 SemVer로 관리하고, 첫 고정 버전은 `"1.0.0"`으로 시작한다.
- 규칙:
  - 필드 추가 등 하위호환 유지: minor 증가
  - 하위호환 깨짐: major 증가
- 이유: schema 진화와 하위호환 판단 기준을 명확히 하기 위함이다.
- 상태: 확정

### D-017

- 결정: raw rule canonical reference는 `document_id + row_index`를 기본으로 사용한다.
- 보조 규칙:
  - `record_id`가 존재하면 optional 보조 참조키로 함께 저장한다.
- 이유:
  - `document_id`만으로는 line 구분이 어렵고
  - `row_index`만으로는 문맥이 부족하므로
  - 둘을 함께 써야 가장 현실적이고 안정적이다.
- 상태: 확정

## 9. 미결정 사항

- 대시보드에서 raw rule output을 어느 모드까지 노출할지
- artifacts 보존 정책과 정리 정책

## 10. 별도 Result Schema 초안

### 10.1 최상위 구조

- 별도 schema는 `Phase1CaseResult > ThemeSummary / CaseGroupResult > CaseDocumentRef / RawRuleHitRef` 4층 구조로 둔다.
- `CaseGroupResult`가 사용자 노출의 기본 단위다.
- 기존 detection metadata에는 case/theme 상세를 넣지 않고, 요약 id/reference만 남긴다.

### 10.2 Phase1CaseResult

- 역할: 최상위 실행 결과 객체
- 필드 초안:
  - `schema_version` (`"1.0.0"`부터 시작하는 SemVer)
  - `run_id`
  - `company_id`
  - `dataset_id` 또는 `batch_id`
  - `generated_at`
  - `top_n_cases`
  - `top_n_per_theme`
  - `theme_summaries: list[ThemeSummary]`
  - `cases: list[CaseGroupResult]`
  - `raw_rule_reference`
  - `metadata`

### 10.3 ThemeSummary

- 역할: queue 화면용 상위 요약
- 필드 초안:
  - `theme_id`
  - `theme_label`
  - `case_count`
  - `high_count`
  - `medium_count`
  - `low_count`
  - `total_amount`
  - `top_case_ids: list[str]`
  - `secondary_tag_case_count`

### 10.4 CaseGroupResult

- 역할: 실제 핵심 case 단위
- 필드 초안:
  - `case_id`
  - `primary_theme`
  - `secondary_tags: list[str]`
  - `evidence_types: list[str]`
  - `case_key`
  - `case_key_parts`
  - `priority_score`
  - `priority_band`
  - `amount_score`
  - `control_score`
  - `logic_score`
  - `behavior_score`
  - `repeat_score`
  - `rule_count`
  - `evidence_count`
  - `document_count`
  - `row_count`
  - `total_amount`
  - `first_posting_date`
  - `last_posting_date`
  - `repeat_months`
  - `representative_explanation`
  - `evidence_tags: list[str]`
  - `documents: list[CaseDocumentRef]`
  - `raw_rule_hits: list[RawRuleHitRef]`

- 운영 원칙:
  - `rule_count`는 보여주기용 보조지표다.
  - 정렬은 `priority_score`, `priority_band` 중심이다.
  - 설명의 대표값은 `representative_explanation`이다.

### 10.5 CaseDocumentRef

- 역할: drill-down 진입용 문서 참조
- 필드 초안:
  - `document_id`
  - `posting_date`
  - `created_by`
  - `business_process`
  - `gl_account`
  - `counterparty`
  - `amount`
  - `matched_rules: list[str]`
  - `evidence_tags: list[str]`

### 10.6 RawRuleHitRef

- 역할: 기존 룰 엔진과 연결되는 원본 참조
- 필드 초안:
  - `rule_id`
  - `severity`
  - `document_id`
  - `row_index`
  - `record_id` (optional)
  - `score`
  - `detail`
  - `evidence_type`

- 참조 원칙:
  - canonical reference는 `document_id + row_index`
  - `record_id`는 있을 때만 보조 참조키로 저장

### 10.7 권장 추가 필드

- `exposure_rank`
- `theme_rank`
- `is_top_case`
- `has_control_failure`
- `has_high_materiality`
- `has_repeat_pattern`

## 11. 구현 아키텍처 고정안

### 11.1 모델 표현 방식

- 모델은 Pydantic으로 구현한다.
- 구현 위치는 `src/models/phase1_case.py`를 기본값으로 둔다.
- 포함 모델:
  - `Phase1CaseResult`
  - `ThemeSummary`
  - `CaseGroupResult`
  - `CaseDocumentRef`
  - `RawRuleHitRef`

### 11.2 저장/직렬화 방식

- 1차 canonical 산출물은 JSON으로 저장한다.
- 기본 경로 규칙:
  - `artifacts/phase1_cases/{company_id}/{run_id}.json`
- 운영 원칙:
  - canonical source of truth는 JSON schema다.
  - DuckDB projection과 UI summary projection은 후속 단계에서 선택적으로 추가한다.

### 11.3 변환 시점

- 변환은 아래 순서를 따른다.
  1. raw detection 실행
  2. raw rule outputs 수집
  3. evidence type 계산
  4. primary / secondary theme 계산
  5. case grouping
  6. case scoring
  7. explanation 생성
  8. `Phase1CaseResult` 생성

- 즉, 변환은 detection layer 내부가 아니라 detection 완료 후 aggregation 성격의 builder 단계에서 수행한다.

### 11.4 builder 모듈 위치

- 추천 구현 위치: `src/detection/phase1_case_builder.py`
- 대안: `src/aggregation/phase1_cases.py`
- 현재 계획 기준 기본안은 `src/detection/phase1_case_builder.py`다.

### 11.5 detection metadata 연결 방식

- detection metadata에는 아래 수준의 최소 참조만 남긴다.
  - `phase1_case_run_id`
  - `phase1_case_path`
  - `phase1_case_count`
  - `top_theme_ids`
- case/theme 상세 본문은 metadata에 넣지 않는다.

## 12. 변경 이력

- 2026-04-22: 초안 생성
- 2026-04-27: PHASE1 통합 점수 계약 구현 반영. `src/detection/rule_scoring.py`를 추가해 raw rule label/score를 `signal_strength`와 `normalized_score`로 표준화하고, `phase1_case_builder`의 evidence type score 합산 기준을 `severity / 5` 단순 합산에서 `normalized_score` 합산으로 변경했다.

## 13. Current Implementation Addendum

PHASE1 case remodeling is now partially implemented, not only planned. The current authoritative implementation points are:

| 영역 | 구현 파일 |
|---|---|
| rule scoring registry / normalization | `src/detection/rule_scoring.py` |
| case grouping / priority aggregation | `src/detection/phase1_case_builder.py` |
| Pydantic result schema | `src/models/phase1_case.py` |
| dashboard/export drill-down view | `src/export/phase1_case_view.py` |
| case-level configurable parameters | `config/phase1_case.yaml` |

현재 통합 점수 흐름:

```text
raw rule output
  -> display_label
  -> signal_strength
  -> normalized_score
  -> evidence_type score
  -> case priority
```

`normalized_score`는 아래 공식으로 계산한다.

```text
signal_strength
* (severity / 5)
* evidence_strength_factor
* scoring_role_factor
```

Rule-specific 정규화가 필요한 detector bucket은 위 공식에 들어가기 전 `signal_strength`를 별도로 산정한다. `L3-09` suspense aging은 detector row score가 30/60/90일 aging 우선순위를 이미 담고 있으므로 `0.45/0.60/0.75/0.80` raw score 순서를 보존한다. PHASE1 contribution은 medium evidence factor를 곱한 `0.3375/0.45/0.5625/0.60`이며, 단독 High floor 없이 `logic_score`에만 반영한다.

`RawRuleHitRef`는 원천 룰 참조 외에 `display_label`, `signal_strength`, `normalized_score`, `evidence_strength`, `scoring_role`을 저장한다. `CaseGroupResult`는 `priority_score`, `base_priority_score`, `topside_bonus`, `batch_combo_bonus`, `weak_evidence_bonus`, `priority_adjustment_reasons`, `review_focus`, `risk_narrative`, `recommended_audit_actions`, `rule_evidence_summary`를 포함한다. Row-level aggregate output은 별도로 `work_scope_combo_score`와 `work_scope_combo_reasons`를 제공한다.

`L3-08`은 `booster`, `L3-12`는 `access_scope_review` evidence type의 weak/booster, `L4-06`은 `combo_only`, `L4-02/D01/D02`는 transaction queue 기준 `macro_only`로 본다. 따라서 룰별 `High/Medium/Low`, `상/중/하`, `검토 필요` 같은 표현값은 화면 설명용 `display_label`로 보존하되, PHASE1 합산에는 `normalized_score`만 사용한다. L3-08은 단독으로 `weak_evidence_bonus`를 만들지 않고, `l3_08_corroborating_rules`에 포함된 독립 보강 룰과 결합될 때만 `missing_or_corrupted_description` 보조 태그를 priority 보정에 사용한다. L3-12는 단독 High floor를 만들지 않고, `work_scope_combo_score`에서 독립 보강 evidence group 2개 이상일 때만 Medium/High 승격을 적용한다.
