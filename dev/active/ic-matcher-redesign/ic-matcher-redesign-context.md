# IC Matcher Redesign — Context & Decisions

## Status

- Phase: Completed (P0 ~ P6 전체 완료 + post-completion finding 수정 3건 반영. T-P4-3 / T-P5-5 는 deferred — 사유 §6 결정 11·12)
- Progress: 23 / 23 tasks complete + post-completion finding 수정 3건 (K-06 / K-07 / K-08, 결정 13)
- Last Updated: 2026-05-23 (finding 수정 + sidecar 위치 보정 반영)
- Branch: develop
- Baseline: `develop` HEAD `3b119b0` (2026-05-23 시점)

## 1. 현재 IC01/IC02/IC03 구현 요약

### 1.1 책임 분리

| Rule    | 책임                                                   | 핵심 시그니처                                                                                  |
|---------|--------------------------------------------------------|------------------------------------------------------------------------------------------------|
| IC01    | 미매칭 IC + 명시적 회사 상대방 + master 미대사         | `ic01_unmatched_intercompany(df, *, match_df) -> pd.Series`                                    |
| IC02    | 매칭됐으나 합계 차이 > tolerance + cross_currency 억제 | `ic02_amount_mismatch(df, *, match_df, amount_tolerance, max_diff_ratio) -> pd.Series`         |
| IC03    | 매칭됐으나 전기일 차이 > window                        | `ic03_timing_gap(df, *, match_df, date_window_days, max_day_diff) -> pd.Series`                |

### 1.2 공유 매칭 엔진

`match_ic_groups()` (`src/detection/intercompany_rules.py:80~217`) 은 3 개 서브룰이 사전 계산된 `match_df` 를 재사용. group_cols 우선순위:

1. `reference` (있는 경우)
2. `company_code` (multi)
3. `trading_partner` (있는 경우)
4. `currency` (있는 경우)

match_level:
- `exact` — multi company_code + trading_partner 모두 보유
- `aggregate` — multi company_code + trading_partner 없음
- `fallback` — 그룹 키 0개

### 1.3 점수 통합 (`score_aggregator.py:1001~1063`)

`_apply_intercompany_exception_corroboration()` 에서:

- IC01/IC02/IC03 어느 하나 hit → Low floor 0.20
- IC01 hit 또는 exception_count >= 2 → Medium floor 0.40
- 결과는 `intercompany_exception_score`, `intercompany_exception_reasons` 컬럼으로 별도 추적

### 1.4 IC pair 설정 SoT

`config/audit_rules.yaml::patterns.intercompany.pairs` (line 309 근방) 가 SoT 다. `load_ic_pairs()` 가 이 위치를 읽는다. `config/phase1_case.yaml` 에는 `patterns.intercompany.pairs` 가 존재하지 않는다 (case-level 정책만 보유).

### 1.5 SEVERITY_MAP 현황 (`src/detection/constants.py:195`)

`IC01=3, IC02=2, IC03=2`. 본 plan 에서는 보존한다 (보정 #3, 사용자 결정).

## 2. 발견된 Fitting / Leakage 증거 (file:line 인용)

### F-01: `-UNMATCHED` endswith fitting

`src/detection/intercompany_rules.py:354`

```python
looks_like_company_partner = partner.str.endswith(
    "-UNMATCHED",
) | ~partner.str.contains("-", regex=False)
```

이 코드 라인은 DataSynth 의 `build_datasynth_v38_ic_exception_labels.py:316` 가 만드는 patch signature (`f"C{n}-UNMATCHED"`) 를 직접 매칭한다. 메모리 `feedback_phase1_truth_recall_guard` 의 "PHASE1 변경은 도메인 정합성으로만 정당화. truth recall 직접 추구 금지" 정면 위반.

### F-02: DataSynth label patch fitting

`tools/scripts/build_datasynth_v38_ic_exception_labels.py:314~319`

```python
if anomaly_type == "UnmatchedIntercompany":
    current_company = str(je.loc[mask, "company_code"].iloc[0])
    unmatched_partner = f"C{(int(current_company[-1]) % 3) + 1:03d}-UNMATCHED"
    je.loc[mask, "trading_partner"] = unmatched_partner
    case["patched_trading_partner"] = unmatched_partner
    case["field_patch"] = "trading_partner_changed_to_unmatched_company"
```

탐지기 코드의 fitting 휴리스틱과 라벨 생성기의 patch signature 가 서로를 짝맞춤. 도메인 근거 없이 label-detector 쌍을 만들어 score 를 보존하는 패턴.

### L-01: sidecar 직접 의존

`src/detection/intercompany_rules.py:332~340`

```python
if "ic_unmatched_reference" in df.columns:
    sidecar_unmatched = (
        df["ic_unmatched_reference"].fillna(False).astype(bool) & ic_rows
    )
...
if match_df.empty or "has_counterpart" not in match_df.columns:
    return sidecar_unmatched.map({True: 1.0, False: 0.0}).fillna(0.0)
```

`ic_unmatched_reference` sidecar 가 IC01 score 의 fallback 경로로 직접 사용됨. 단순히 reference prefix 기반 sidecar 인 점 자체는 문제가 아니지만, label 주입 흐름과 결합 운영되어 leakage 위험이 있음.

### L-02: 파이프라인 결합도

`tools/scripts/profile_phase1_v126.py:198`

```python
df["ic_unmatched_reference"] = has_ic_reference & ~df["ic_matched_pair_found"]
```

`profile_phase1_v126` 가 row 단위로 부착하고 `phase1_case_builder.py:2609` 가 직접 소비. detector 외부의 파이프라인 단계에서 IC01 의 영향을 받는 구조.

## 3. 관련 문서 Lock 현황

### 3.1 `RULE_DETAIL_METADATA_V1_LOCK.md`

- v1 canonical L1~L4 rule count = 32 (절대 변경 불가).
- IC01/IC02/IC03 은 canonical 외부, `intercompany_sidecar` surface 로 별도 관리.
- 본 plan 은 외부 rule id 를 `IC01` 단일 유지 (보정 #2). canonical count 영향 없음.
- 변경 사항은 evidence level sidecar (`ic01_evidence_level`, `ic01_review_reason`) 정책 절 추가에 한정.

### 3.2 `PHASE1_TOPIC_SCORING_V1_LOCK.md`

- `관계사·내부거래·순환구조` topic 의 Primary rules: `IC01, IC02, IC03` (현재 그대로 유지).
- floor 차별이 evidence level 기반임을 보조 절에 명시. Primary rules 본문은 변경 없음.

### 3.3 `DETECTION_RULES.md:1085~1132`

- L3-03 본문 + IC01/IC02/IC03 정책 + DataSynth 계약이 한 절에 통합되어 있음.
- IC01 실무 기준 (`:1119`): "고객/벤더 코드(C-000123, V-000123) 는 IC01 에서 제외" 라는 표현이 이미 명시됨. 본 plan 의 IC01 제외 분류는 이 정책의 코드화.
- evidence level sidecar (`high` / `review`) 정책 절을 신규 추가.

### 3.4 `PHASE1_RULE_RELATIONSHIP_MAP.md`

- intercompany_structure evidence type 표 (mermaid `:80`): `L3-03 IC01 IC02 IC03`. 외부 rule id 단일 유지이므로 mermaid 변경 없음. 보조 주석으로 evidence level sidecar 명시.

### 3.5 `DECISION.md` D055 (2026-05-18) — 본 plan 으로 supersede

`docs/DECISION.md:514` D055 는 `ic_unmatched_reference=True` 를 IC01 high-confidence unmatched IC evidence 로 수용한다고 명시. 본 plan 의 P0 (sidecar 의존 제거) 와 P1 (IC01 재정의) 은 D055 를 정면으로 뒤집는다. 따라서 P3-6 에서 명시적 supersede 결정문 (`D0xx`) 을 신규 추가하고, D055 본문 상단에 "Superseded by D0xx (YYYY-MM-DD)" 라인을 부착한다.

## 4. 의존 모듈 / 호출 경로

```
config/audit_rules.yaml::patterns.intercompany (line 309)   # IC pair SoT
  └─ src/detection/intercompany_rules.py: load_ic_pairs()

config/settings.py
  └─ AuditSettings.ic_amount_tolerance / ic_max_diff_ratio / ic_date_window_days / ic_max_day_diff / ic_min_ic_rows
       └─ src/detection/intercompany_matcher.py
            ├─ src/detection/intercompany_rules.py (load_ic_pairs, match_ic_groups, ic01/02/03)
            └─ src/detection/base.py (BaseDetector, DetectionResult)

src/detection/score_aggregator.py
  └─ _apply_intercompany_exception_corroboration()
       └─ combined[exception_rules] 에서 IC01/IC02/IC03 detail 읽음
       └─ (변경 후) combined["ic01_evidence_level"] 추가 read

src/detection/phase1_case_builder.py:2609
  └─ ic_unmatched_reference 직접 소비 → intercompany_cycle topic floor 0.60 결정

tools/scripts/profile_phase1_v126.py:198
  └─ ic_unmatched_reference sidecar 생성 (IC reference prefix 기반)

tools/scripts/build_datasynth_v38_ic_exception_labels.py:316
  └─ UnmatchedIntercompany label patch — trading_partner 를 "-UNMATCHED" 로 변경

tests/modules/test_detection/test_intercompany_matcher.py
  └─ 23 개 테스트. TestIC01Unmatched 6 개가 본 plan 으로 expectation 변경 필요.
```

## 5. 현재 테스트 통과 상태

- `tests/modules/test_detection/test_intercompany_matcher.py` — 23 개 (실제 클래스 수 카운트: Basic 3 + IC01 6 + IC01Practical 1 + IC02 4 + IC03 3 + Graceful 4 + YAML 2 = 23)
- 마지막 측정: 사용자 보고 `23 passed` (시점 미명시, plan 시작 시 재확인 필요)
- `tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py` — 별도 smoke 테스트. v7_fixed3 데이터셋 대상.

## 6. 주요 결정 사항

### 결정 1: 도메인 근거 재정렬 (2026-05-23)

- 결정: IC 양측 대사 룰의 1차 근거를 IFRS 10 §B86 / K-IFRS 1110 / 1024 / KICPA Issue Paper 46 / ISA 600 으로 재정렬. ISA 550 §23 은 보조 근거로만 유지.
- 합의: 사용자와 합의 완료 (요청서 §2).
- 근거: IC 양측 대사는 "연결 내부거래 제거" 의 필수 절차. ISA 550 §23 은 특수관계자 거래의 "사업상 합리성" 평가로 범위가 다름. 현재 매핑은 부정 단정 톤이 강하고 IC 대사의 회계적 필연성을 약하게 표현.

### 결정 2: IC01 외부 rule id 단일 유지 + 내부 evidence level sidecar (2026-05-23, 보정 #2 반영)

- 결정: 외부 rule id 는 `IC01` 단일 유지. evidence level 은 detector 결과의 sidecar column (`ic01_evidence_level` ∈ {`"high"`, `"review"`, `""`}, `ic01_review_reason` ∈ {`missing_partner`, `nonstandard_format`, `mapping_uncertain`, ...}) 으로만 분리.
- 합의: 사용자 결정 채택. 파급이 가장 작은 안.
- 근거: 외부 rule id 분리 (IC01_A / IC01_B 등) 는 `RULE_CODES`, `SEVERITY_MAP`, `RULE_DETAIL_METADATA_REGISTRY`, `metrics/rule_mapping.py`, `phase2_subdetector_tiers.yaml`, dashboard/export 표시 맵 등 광범위한 영향. evidence level sidecar 만으로도 score floor 차별 / reason code 명시 가능.

### 결정 3: SEVERITY_MAP 보존 (2026-05-23, 보정 #3 반영)

- 결정: `src/detection/constants.py:195` 의 `IC01=3, IC02=2, IC03=2` 보존. 본 plan 에서 severity 재조정 없음.
- 합의: 사용자 결정 채택.
- 근거: severity 변경은 anti-fitting 과 별개의 점수 세기 변경. score floor 차별은 `score_aggregator` 에서만 처리하므로 severity 보존과 양립함. 점수 세기 변경이 필요하다면 별도 plan 으로 분리.

### 결정 4: `score_aggregator` floor 정책 변경 (2026-05-23)

- 결정: `IC01 hit + ic01_evidence_level == "high"` 단독 = Medium 0.40, `IC01 hit + ic01_evidence_level == "review"` 단독 = Low 0.20, IC02 / IC03 단독 = Low 0.20 (기존 그대로), IC01 + IC02 / IC03 또는 IC02 + IC03 (2개 이상 IC 예외 결합) = Medium 0.40 (기존 유지).
- 합의: plan 단계 제안. 사용자 확인 후 확정.
- 근거: IC01 evidence=`high` 만 도메인적으로 미대사 확정 가능. evidence=`review` 단독은 review signal 수준.

### 결정 5: DataSynth label 옵션 A 권장 (2026-05-23)

- 결정: `f"C{n}-UNMATCHED"` patch 를 그룹 외부의 실재 형식 회사 코드(`C9XX`) 로 교체.
- 합의: plan 단계 제안. 사용자 확인 후 확정.
- 트레이드오프: detector 코드 변경 최소 옵션 B 도 가능하나, scenario truth 의 field 일관성 측면에서 A 가 우수. Rust 재생성 불필요 (Python 후처리 스크립트만 수정).

### 결정 6: PHASE1 truth recall 직접 추구 금지 — Layer C SOFT WARN 시 사용자 확인 (2026-05-23)

- 결정: 본 plan 이 PHASE1 코드 변경이므로 `feedback_phase1_truth_recall_guard` 3 계층 KPI guard 를 따른다.
- 합의: 메모리 룰 자동 적용.
- 근거: Layer A/B HARD 위반 시 plan 즉시 중단. Layer C SOFT WARN 은 측정 후 사용자 확인.

### 결정 7: IC pair SoT 정정 (2026-05-23, 보정 #1 반영)

- 결정: IC pair 설정은 `config/audit_rules.yaml::patterns.intercompany` (line 309 근방) 가 SoT. 신규 키 (`related_party_master`, `partner_format`) 도 동일 위치에 둔다.
- 합의: 사용자 보정 확인.
- 근거: `load_ic_pairs()` 가 `audit_rules.yaml` 구조를 읽는다. `config/phase1_case.yaml` 에는 `patterns.intercompany.pairs` 가 존재하지 않는다. 초기 plan 의 SoT 표기 오류 정정.

### 결정 8: D055 supersede (2026-05-23, 보정 #4 반영)

- 결정: `docs/DECISION.md` 에 D0xx 신규 결정문 추가. D055 본문 상단에 "Superseded by D0xx (YYYY-MM-DD)" 라인 부착. D055 본문 자체는 그대로 둠.
- 합의: 사용자 보정 확인.
- 근거: P0/P1 이 D055 의 "`ic_unmatched_reference=True` 를 IC01 high-confidence evidence 로 수용" 정책을 정면으로 뒤집는다. DECISION 로그 추적성을 위해 명시적 supersede 결정문 필수.

### 결정 9: ripple-search acceptance 의미적 fitting 한정 (2026-05-23, 보정 #5 반영)

- 결정: P5 ripple-search acceptance 는 의미적 fitting 코드만 0건. IC01 literal 자체는 RULE_CODES/SEVERITY_MAP/registry/dashboard/metrics 에 그대로 유지.
- 합의: 사용자 결정 채택.
- 근거: IC01 literal 은 외부 rule id 로 정상 사용되는 표기. 0건 acceptance 는 fitting 코드 (`endswith("-UNMATCHED")`, `ic_unmatched_reference` detector 직접 의존, `partner.str.contains("-")` 휴리스틱) 에만 적용한다. `src/export/phase1_case_view.py`, `src/metrics/rule_mapping.py`, `src/detection/constants.py`, `config/phase2_subdetector_tiers.yaml`, dashboard mappings 등은 조사만, 휴리스틱 외 변경 없음.

### 결정 10: IC02 noise calibration 은 본 plan 비범위 + 별도 plan 분리 (2026-05-23)

- 결정: 본 plan (P0~P6) 의 IC01 fitting 제거와 IC02 noise calibration 은 분리하여 별도 plan (`dev/active/ic02-calibration/`, 생성 deferred) 에서 다룬다.
- 합의: 사용자 보고 (v7_fixed4 baseline 검증) 후 분리 결정 채택.
- 근거:
  - 사용자가 `datasynth_manipulation_v7_candidate_fixed4` baseline 에서 intercompany family hit 24,716건 중 truth 34건 (0.14%) 만 양성이고 24,682건이 정상 IC pair 에서 IC02 (금액 불일치) 룰 hit 으로 확인.
  - TOP 100/500 recall -3~-4pp 감소 — ranking 재배치 영향 확인.
  - IC02 family 정의 자체는 도메인 정합 (IFRS 10 §B86, KICPA JET 완전성). 운영 calibration 미스매치 (`ic_amount_tolerance=0.02`, `ic_max_diff_ratio=0.10`, cross-currency 100x 임계) 및 DataSynth fixed4 의 정상 IC pair 양측 금액 정합성 가능성.
  - 본 plan 의 IC01 evidence_level 분류 (high/review) 는 IC02 hit 분포에 직접 영향을 주지 않으므로 IC01 fitting 제거와 IC02 calibration 은 독립적으로 처리 가능.
- 후속: F-01 (`dev/active/ic02-calibration/`) 신규 plan 으로 분리하여 calibration tolerance·max_diff_ratio·cross-currency 가드 + DataSynth Rust 측 정상 IC pair 정합성 검증.

### 결정 11: T-P4-3 deprecated — 운영 baseline v7_fixed4 이동 (2026-05-23)

- 결정: T-P4-3 (재생성 산출물 검증) 은 deprecated. T-P4-1 / T-P4-2 (스크립트 fitting 패턴 제거) 만 완료한다.
- 합의: 운영 baseline 이동 확인 후 결정.
- 근거:
  - 운영 baseline 이 `data/journal/primary/datasynth_manipulation_v7_candidate_fixed4` 로 이동.
  - `build_datasynth_v38_ic_exception_labels.py` 가 만드는 `intercompany_exception_cases.csv` / `intercompany_normal_controls.csv` 는 v7_fixed4 라벨 디렉토리에 부재.
  - v7_fixed4 의 `journal_entries.csv` 에 `-UNMATCHED` 문자열 0건, `ic_unmatched_reference` 컬럼 부재 — P0 fitting 제거가 운영 데이터 흐름에 영향 없음.
  - 스크립트 자체의 fitting 패턴 제거 (T-P4-1, T-P4-2) 는 완료. 추후 v37 계열 라벨이 다시 필요할 경우 본 commit 의 변경이 그대로 적용된다.
- 영향: tasks.md T-P4-3 본문은 deferred 사유로 갱신됨. Deployment Checklist 의 "DataSynth v38 candidate 재생성 산출물 검증" 항목은 v7_fixed4 의 `-UNMATCHED` grep 0건 확인으로 대체.

### 결정 12: T-P5-5 KPI guard 측정 deferred — IC02 calibration plan 으로 통합 측정 (2026-05-23)

- 결정: T-P5-5 (PHASE1 KPI guard 측정) 은 deferred. `dev/active/ic02-calibration/` 신규 plan 에서 IC02 noise 측정과 통합 수행한다.
- 합의: 운영 baseline 이동·CLI 시그니처 불일치 확인 후 결정.
- 근거:
  - `tools/scripts/profile_phase1_v126.py` 가 `--output` 인자를 지원하지 않음 — plan tasks.md 의 KPI 측정 명령 (`profile_phase1_v126.py --output kpi_*.json`) 시그니처 불일치.
  - 운영 baseline 이 v7_fixed4 로 이동 — v126 profiler 의 baseline 과 측정 대상이 다름.
  - IC02 noise 이슈 (결정 10) 와 IC01 fitting 제거가 동시에 ranking 분포에 영향. 분리 측정 시 신호 혼선 발생. IC02 calibration 적용 후 통합 측정이 효율적.
- 후속: IC02 calibration plan 에서 (a) profiler CLI 시그니처 정합 (b) v7_fixed4 baseline 으로 측정 (c) Layer A/B HARD + Layer C SOFT WARN 결과 동시 보고.

### 결정 13: IC01 review-level confirmed 격상 방지 + sidecar metadata 이동 (2026-05-23)

- 결정:
  - **review-level score = 0**: `intercompany_rules.ic01_unmatched_intercompany` 의 review 분기는 `score = 0.0` 반환. high 만 `score = 1.0`. evidence_level / review_reason 은 두 분기 모두 그대로 채워진다.
  - **Sidecar metadata 이동**: `ic01_evidence_level`, `ic01_review_reason` 두 sidecar 컬럼은 `DetectionResult.metadata["row_sidecar"]: dict[str, pd.Series]` 로 저장한다. `DetectionResult.details` 는 numeric rule-score (IC01/IC02/IC03 `float64`) matrix 계약을 유지한다.
  - **score_aggregator read 경로**: `_extract_ic01_evidence_level()` 는 `metadata["row_sidecar"]` 에서 우선 read 하고, 구버전 호환을 위해 `details` fallback 도 지원한다.
- 합의: 사용자 코드 리뷰 (2026-05-23) 에서 finding 3 건 보고 후 즉시 채택.
- 근거: `AGENTS.md` "review-only signals must not become confirmed violations". 추가로 문자열 sidecar 가 `details` 에 섞이면 `metrics/ground_truth_evaluator.py:1152, 1537` 및 `score_aggregator._collect_flagged_rules` 의 `details > 0` 비교에서 TypeError 발생.
- 영향 범위:
  - `src/detection/intercompany_rules.py::ic01_unmatched_intercompany` (review 분기 `score = 0.0`)
  - `src/detection/intercompany_matcher.py::_build_result` (sidecar → `metadata["row_sidecar"]`, details 는 numeric only)
  - `src/detection/score_aggregator.py::_extract_ic01_evidence_level` (metadata read + details fallback)
  - `tests/modules/test_detection/test_intercompany_matcher.py` (review 테스트 4 건 assert 갱신 — `details["IC01"] == 0.0`, sidecar 는 `metadata["row_sidecar"][col]`)
  - `tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py` (smoke 테스트 2 건 동일 형식 갱신)
- 검증:
  - `uv run pytest tests/modules/test_detection/ -q` → 1130 passed, 3 skipped, 0 failed
  - 런타임: `result.details.columns = ['IC01', 'IC02', 'IC03']`, dtypes 전부 `float64`, `(result.details > 0).any().any()` TypeError 없음
  - review 행: `details["IC01"] == 0.0`, `metadata["row_sidecar"]["ic01_evidence_level"] == "review"`
- D065 정합: 본 결정으로 D065 결정문의 "정책" 절에 "Sidecar 저장 위치" / "Review-only 신호의 confirmed 격상 방지" 두 조항 추가 (`docs/DECISION.md` D065).

## 7. Known Issues (마감 상태)

### 7.1 본 plan 내 처리 완료

| ID   | 이슈                                                                                                            | 처리 결과                                                                                   |
|------|-----------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| K-01 | `RuleDetailMetadata` 의 rule_id 정규식이 sidecar column 명 (`ic01_evidence_level`) 을 enum 검증에 포함하는지 확인 필요 | 확인 완료. sidecar column 은 rule_id enum 외 별도 관리 (canonical 32 count 영향 없음).      |
| K-02 | `intercompany_exception_cases` schema 에 `master_unmatched_company_code` 필드 부재                              | T-P4-3 deprecated 처리 (결정 11). v7_fixed4 운영 baseline 은 본 schema 비사용.              |
| K-03 | `phase1_case_builder.py:2609` 의 `ic_unmatched_reference` 소비 정책                                              | D065 결정문에서 read-only 허용 범위로 명시. `_case_has_any_true` 가 boolean read 만 수행.    |
| K-04 | `test_intercompany_v7_fixed3_smoke.py` 의 baseline expectation 이 fitting 휴리스틱 결과에 의존하는지            | 2건 smoke 테스트 D065 정합으로 갱신 완료. 통과 확인.                                        |
| K-05 | dashboard rule selector 에서 evidence level 표시 — sidecar column 으로 노출할지 단일 IC01 label 유지할지         | 외부 rule id `IC01` 단일 유지 (결정 2). sidecar column (`ic01_evidence_level`) 으로 표시.   |
| K-06 | **(High)** IC01 review-level 이 `details["IC01"]` 양수 score 로 들어가 `flagged_rules` / case seed / GT 평가에서 confirmed violation 으로 격상 (`AGENTS.md` "review-only signals must not become confirmed violations" 위반) | 결정 13 적용. `intercompany_rules.ic01_unmatched_intercompany` review 분기 `score = 0.0` 으로 수정. high 만 `score = 1.0`. |
| K-07 | **(High)** 문자열 sidecar (`ic01_evidence_level`, `ic01_review_reason`) 가 `DetectionResult.details` 에 섞여 `metrics/ground_truth_evaluator.py:1152, 1537` 의 `details > 0` 비교에서 TypeError 위험 | 결정 13 적용. sidecar 를 `DetectionResult.metadata["row_sidecar"]: dict[str, pd.Series]` 로 이동. `details` 는 numeric only matrix 계약 유지. `score_aggregator._extract_ic01_evidence_level` 가 metadata 우선 + details fallback read. |
| K-08 | **(Medium)** review-level IC01 이 ground-truth IC01 검증 (rule score > 0 = 탐지 hit) 에서 false positive 발생 | 결정 13 적용. review row 의 `details["IC01"] == 0.0` 으로 유지되어 GT 평가 hit 조건 (`> 0`) 에서 자연 제외. |

### 7.2 후속 plan 으로 이관 (Follow-up)

| ID   | 이슈                                                              | 이관 위치                                                                                       |
|------|-------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| F-01 | IC02 family 의 운영 calibration (tolerance / max_diff_ratio / cross-currency 가드) | `dev/active/ic02-calibration/` (생성 deferred) — 결정 10                                       |
| F-02 | PHASE1 KPI guard 측정 자동화 (`profile_phase1_v126.py --output` 시그니처 정합)      | IC02 calibration plan 에서 통합 측정 — 결정 12                                                  |
| F-03 | DataSynth Rust 측 정상 IC pair 양측 금액 정합성 검증                              | IC02 calibration plan 에서 함께 수행 — 결정 10                                                  |

## 8. 검증 명령 & 결과 (Reference)

### 8.1 단위 테스트 결과 (2026-05-23 마감)

| 명령                                                                              | 결과                                          |
|-----------------------------------------------------------------------------------|-----------------------------------------------|
| `uv run pytest tests/modules/test_detection/test_intercompany_matcher.py -v`     | 30 passed (기존 23 + 신규 7)                  |
| `uv run pytest tests/modules/test_detection/test_score_aggregator.py -v`         | 97 passed (기존 92 + 신규 5 floor 테스트)     |
| `uv run pytest tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py -v` | 2 passed (D065 정합으로 expectation 갱신) |
| `uv run pytest tests/modules/test_detection/ -q`                                  | 1130 passed, 3 skipped, 0 failed              |
| `uv run python -c "import dashboard.app"`                                         | ImportError 없음 (Streamlit ScriptRunContext 경고는 bare 모드 정상) |

### 8.2 Ripple-search 결과 (P5-4, 2026-05-23)

상세: [ripple_search_after.md](./ripple_search_after.md)

| 패턴                                              | acceptance | 결과                                                          |
|---------------------------------------------------|------------|---------------------------------------------------------------|
| `endswith("-UNMATCHED")` (production code)        | 0건        | 0건 (문서 인용만 잔존)                                        |
| `partner.str.contains("-")` (production code)     | 0건        | 0건 (문서 인용만 잔존)                                        |
| `ic_unmatched_reference` detector 직접 의존       | 0건        | 0건 (`phase1_case_builder.py:2609` 의 case-level read 만 잔존, D065 read-only 범위) |
| `"IC01"` literal                                  | 조사만     | RULE_CODES / SEVERITY_MAP / registry / dashboard / metrics 정상 유지 |

### 8.3 PHASE1 KPI guard — deferred

결정 12 에 따라 `dev/active/ic02-calibration/` 신규 plan 에서 통합 측정. `profile_phase1_v126.py --output` 시그니처 정합 + v7_fixed4 baseline 측정 + Layer A/B/C 동시 보고 예정.

### 8.4 재현용 명령 (참고)

```bash
# 단위 테스트 (재현)
uv run pytest tests/modules/test_detection/test_intercompany_matcher.py -v
uv run pytest tests/modules/test_detection/test_score_aggregator.py -v
uv run pytest tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py -v
uv run pytest tests/modules/test_detection/ -q

# Ripple-search (재현)
grep -rn 'endswith("-UNMATCHED")' src/ tools/
grep -rn 'partner.str.contains("-")' src/ tools/
grep -rn 'ic_unmatched_reference' src/detection/

# Dashboard import smoke
uv run python -c "import dashboard.app"
```

## 9. Reference Links

- `config/audit_rules.yaml::patterns.intercompany` (line 309 근방) — IC pair SoT
- `docs/DETECTION_RULES.md:1085~1132` — L3-03 + IC01/IC02/IC03 정책 (T-P3-1 갱신 완료)
- `docs/DETECTION_REFERENCE.md:153~241` — 감사기준서 매핑 (IFRS 10 / K-IFRS 1110·1024 / ISA 600 신규 절, T-P3-2 갱신 완료)
- `docs/RULE_DETAIL_METADATA_V1_LOCK.md` — canonical rule count + evidence level sidecar 정책 (T-P3-3 갱신 완료)
- `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md` — floor 차별 정책 보조 절 (T-P3-4 갱신 완료)
- `docs/PHASE1_RULE_RELATIONSHIP_MAP.md` — intercompany_structure evidence type + evidence level sidecar 주석 (T-P3-5 갱신 완료)
- `docs/DECISION.md:514` — D055 (2026-05-18) — Superseded by D065 (2026-05-23)
- `docs/DECISION.md:565~` — D065 (2026-05-23) — 본 plan 의 supersede 결정문 (T-P3-6 추가 완료)
- [ripple_search_after.md](./ripple_search_after.md) — T-P5-4 ripple-search 의미 검토 결과
- `CLAUDE.md` — PHASE1 역할 원칙, DataSynth 생성 규칙
- 메모리 `feedback_phase1_truth_recall_guard.md` — 3 계층 KPI guard
- 메모리 `feedback_ic_matching_traps.md` — IC 매칭 함정 (N:M 집계, 이종 통화)
