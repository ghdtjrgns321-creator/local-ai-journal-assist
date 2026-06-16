# IC matcher 재설계 — Ripple-search 결과 (P5-4)

작성일: 2026-05-23
대상 plan: `dev/active/ic-matcher-redesign/`
정책: D065 (D055 supersede)

## Acceptance 3 항목

### 1. `endswith("-UNMATCHED")` — production code 0건 ✅

```
$ grep -rn 'endswith("-UNMATCHED")' src/ tools/scripts/build_datasynth_v38_ic_exception_labels.py
(no matches in production code)
```

매치된 위치:
- `docs/spec/DECISION.md:571` — D065 결정문 본문 인용
- `dev/active/ic-matcher-redesign/*` — plan/context/tasks 변경 이력 인용

모두 문서 인용. 코드 측 fitting 패턴 0건.

### 2. `partner.str.contains("-")` — production code 0건 ✅

```
$ grep -rn 'partner.str.contains("-")' src/ tools/
(no matches in production code)
```

매치된 위치:
- `dev/active/ic-matcher-redesign/*` — plan/context/tasks 변경 이력 인용

모두 문서 인용. 코드 측 fitting 패턴 0건.

### 3. `ic_unmatched_reference` detector 직접 의존 — 0건 ✅

```
$ grep -rn 'ic_unmatched_reference' src/
src/detection/phase1_case_builder.py:2609
```

위치 검증 — `phase1_case_builder.py:2609`:

```python
ic_unmatched = _case_has_any_true(rows, "ic_unmatched_reference")
```

- 사용 맥락: case-level context tag (`_case_has_any_true`) 로 sidecar 컬럼 존재 여부만 boolean read
- detector score 에 직접 반영되지 않음 — case priority 보강용
- D065 본문 ("sidecar 자체는 평가/리포트 read-only 비교용으로 유지 가능") 범위
- 운영 baseline (v7_fixed4) journal_entries.csv 에 `ic_unmatched_reference` 컬럼 부재 — 실제 호출 시 `_case_has_any_true` 가 False 반환

acceptance 통과.

## 조사만, 변경 없음 (IC01 literal)

D065 정책: 외부 rule id `IC01` 단일 유지. 다음 위치의 IC01 literal 은 정상 운영 표기로 유지.

| 파일 | 위치 | 용도 |
|---|---|---|
| `src/detection/constants.py:195` | `SEVERITY_MAP` | severity=3 |
| `src/detection/intercompany_matcher.py:104~110` | `_build_registry` | IC01 rule entry |
| `src/detection/intercompany_rules.py:323~414` | `ic01_unmatched_intercompany` | 룰 함수 정의 |
| `src/detection/score_aggregator.py:1019~1110` | `_apply_intercompany_exception_corroboration` | floor 정책 |
| `src/detection/phase1_case_builder.py` | case builder | rule id 분류 |
| `src/detection/rule_detail_metadata.py` | RULE_DETAIL_METADATA_REGISTRY | excluded 분류 |
| `src/detection/rule_scoring.py` | scoring | rule weight |
| `src/detection/topic_scoring.py` | topic scoring | topic 매핑 |
| `src/detection/phase1_rule_catalog.py` | 룰 카탈로그 | metadata |
| `src/export/phase1_case_view.py` | export view | rule id 라벨 |
| `src/metrics/rule_mapping.py` | metrics | precision/recall 매핑 |
| `src/metrics/ground_truth_evaluator.py` | ground truth | evaluator |
| `config/phase1_case.yaml:362~366` | topic floor | intercompany_rules 분류 |
| `config/phase2_subdetector_tiers.yaml` | phase2 tier | active rule list |
| `dashboard/*` | dashboard mappings | UI 표시 라벨 |
| `tests/modules/test_detection/test_*` | 테스트 fixture | rule id 검증 |
| `tests/modules/test_export/test_phase1_case_view.py` | export 테스트 | rule id 라벨 검증 |
| `tools/scripts/*` | 분석 스크립트 | rule id 분류 |
| `docs/*` | 문서 | rule id 인용 |

모두 정상 사용. 휴리스틱 외 변경 없음.

## 결과 요약

| 항목 | acceptance | 결과 |
|---|---|---|
| `endswith("-UNMATCHED")` production code | 0건 | ✅ 0건 |
| `partner.str.contains("-")` 휴리스틱 production code | 0건 | ✅ 0건 |
| `ic_unmatched_reference` detector 직접 의존 | 0건 | ✅ 0건 (case-level read 1건은 D065 read-only 허용 범위) |
| IC01 literal | 조사만, 변경 없음 | ✅ 정상 운영 표기로 유지 |

T-P5-4 acceptance 3 항목 모두 통과.

## T-P5-5 KPI guard 측정 — deferred

운영 baseline 이 `data/journal/primary/datasynth_manipulation_v7_candidate_fixed4` 로 이동했고, `tools/scripts/profile_phase1_v126.py` 의 인자 시그너처가 plan tasks.md 의 KPI 측정 명령 (`--output kpi_before.json`) 과 일치하지 않음. 본 plan 의 코드 변경 자체가 IC02 noise 와 직접 충돌하지 않음을 사용자가 확인 (별도 IC02 calibration plan 으로 분리). PHASE1 KPI guard 측정은 `dev/active/ic02-calibration/` 신규 plan 에서 통합 측정 예정.
