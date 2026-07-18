# PHASE2 Timeseries Family Role Lock

> **🔄 2026-07-15 갱신 (구현 후 실측 → supersede 취소)**: 아래 2026-06-30 노트가 예고한 "시계열 = PHASE1-2 자기 큐(당기 내 거래 집중)"는 **구현 후 실측에서 폐기**됐다. 당기 내 baseline 은 결산 캘린더를 재발견할 뿐이고(정상 데이터 finding 864건 중 분기말 70%, 레인 분리 후에도 595건·52.4%), 한 해에 연말은 한 번뿐이라 "연말치고도 이상한가"를 당기 내에서 판정할 방법이 원리적으로 없다. "작년 같은 달과 비교"로 가면 D02 중복이다. 근거 SoT: [DETECTION_RULES_PHASE1-2.MD §시계열 당기내 집중](../../spec/DETECTION_RULES_PHASE1-2.MD) · 실측 `dev/active/phase1-2-code-rework/backend_verify.md` §8.
>
> **따라서 본 LOCK 은 supersede 되지 않는다.** 아래 "결산·시점·빈도 컨텍스트 lane" 역할 고정(결정 9, 2026-05-25)은 **유효하게 존속**하며, 코드도 `timeseries` 를 PHASE2 lane 에서 계속 실행한다(`pipeline.py` phase2_only family 블록). 시계열은 자기 큐가 아니라 **D02 드릴다운**으로 재정의됐다(미구현).

> **🔄 2026-06-30 (역사 기록 — 위 2026-07-15 노트로 폐기됨)**: 본 문서의 "TS = PHASE1-2 귀속" 결론은 유효하며, 그 구체 설계가 확정됐다 — **시계열 = PHASE1-2 "자기 큐"(당기 내 거래 집중)**. D01/D02의 전기비교가 못 보는 "특정 연도 안에서 특정 시점에 거래 몰림"을 본다. 실패한 TS01 burst/TS02 frequency 구현은 통계(robust-z)만 재활용하고 **당기 내 집중으로 신규 설계**한다.

> **C안 3-surface 정합 + TS 귀속 판단 (2026-06-14, SoT [PHASE1_TIER_EVIDENCE_BASIS.md §7](PHASE1_TIER_EVIDENCE_BASIS.md))**:
> SoT §7은 시계열을 PHASE1-2 family(family = graph·relational·시계열)에 포함한다. 따라서 시계열 탐지기 자체(TS01 transaction_burst / TS02 unusual_frequency = 결정론·근거·명명된 구조 단위 탐지)는 **PHASE1-2 family 로 귀속**한다. PHASE2 단독 surface 는 VAE(비지도) 하나뿐이며, TS 는 PHASE2 surface 가 아니다.
> 다만 본 LOCK(결정 9, 2026-05-25)이 고정한 "결산·시점·빈도 컨텍스트 lane" 역할은 **다른 층위**다. 이 lane 역할은 단독 ranker 가 아니라 다른 family 후보·전표를 보강하는 컨텍스트 제공이며, **이 결산·시점 lane 컨텍스트 제공 역할은 PHASE1-1 룰 정렬에도 booster 로 잔존**한다(SoT §6 CONTEXT booster / 결산·시점 흡수와 정합). 정리: **TS 탐지기 = PHASE1-2 family(시계열) 귀속, 결산·시점 lane 컨텍스트 제공 역할 = PHASE1-1 룰 정렬에 잔존** — 두 층위를 분리해 기록한다.
> 3 surface(PHASE1-1 룰 / PHASE1-2 family / PHASE2 VAE)는 절대 비병합. 본 문서 §2.1 표의 "primary 2-way RRF voter / Noisy-OR 5-family" 결합 서술은 결정 8과 동일하게 과거 통합 queue 기록이며 현재 공식 계약(family lane 독립, 점수 미병합)이 아니다.

> **상태**: lock (2026-05-25 발효). 본 문서는 `timeseries` family (TS01, TS02) 의 운영 역할을 결산·시점·빈도 컨텍스트 lane 으로 고정하기 위한 단일 출처 lock 이다. (surface 귀속: 시계열 탐지기는 PHASE1-2 family — 상단 C안 정합 노트 참조.)
>
> **거버넌스 연결**: [docs/spec/PHASE2_GOVERNANCE_DESIGN.md §결정 9](PHASE2_GOVERNANCE_DESIGN.md) · [config/phase2_subdetector_tiers.yaml](../../config/phase2_subdetector_tiers.yaml) (TS01/TS02 항목)
>
> **PHASE1 정합**: [docs/spec/CONSTRAINTS.md PHASE1 truth-recall-guard](CONSTRAINTS.md) 의 PHASE2 분야별 (family-scoped) 적용.

---

## 1. 결정 요지

PHASE2 `timeseries` family 는 **결산/시점/빈도 컨텍스트 lane** 으로 역할 고정한다. 다음 4가지는 거버넌스로 차단한다.

| 차단 항목                                   | 사유                                                                                                                   |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| TOP100/500 단독 ranker recall 튜닝          | TS lane 단독 precision ranker 부적합 (정상 결산 이벤트와 분포 겹침). truth recall 직접 추구는 PHASE1 가드 위반과 동치. |
| `period_end`/`manual`/`amount_tail` fitting | DataSynth `is_anomaly` sidecar 의 형태에 맞춰 학습되는 attractor — 운영 데이터에 일반화 안 됨.                         |
| inference batch ECDF q-cap 튜닝             | 정상 routine close 와 조작 close 이벤트가 batch 분포상 겹침 — q-cap 조정으로는 분리 불가.                              |
| primary 2-way RRF 순위 침범                 | TS lane 은 attribution view 한정. primary queue 영향 없음 (`phase2_lane_sort.sort_lane`).                              |

---

## 2. 락 대상 정책

### 2.1 단독 ranker 금지

TS01 (transaction_burst) / TS02 (unusual_frequency) 단독으로 review queue 의 TOP recall metric 을 직접 목표로 삼지 않는다.

| 운영 사용 영역                                              | 허용 여부                              |
| ----------------------------------------------------------- | -------------------------------------- |
| primary 2-way RRF voter 입력 (Noisy-OR 의 5-family 중 하나) | ✅ 허용 (결정 8 voter 형식)            |
| lane view 보조 정렬 (evidence_tier desc → ECDF desc)        | ✅ 허용 (`phase2_lane_sort.sort_lane`) |
| narrator citation 입력 (`phase2_family_contributions`)      | ✅ 허용 (결정 8 narrator attribution)  |
| **TS lane 단독 precision/recall metric 튜닝 대상**          | ❌ **금지**                            |
| **`is_fraud`/`is_anomaly` truth recall 향상 직접 목표**     | ❌ **금지**                            |

### 2.2 ranker_use = top2000_plus_context

ranker 의미는 **TOP2000+ 보조 coverage** 로 한정한다.

| 깊이 구간    | TS lane 운영 의미                                                                                    |
| ------------ | ---------------------------------------------------------------------------------------------------- |
| TOP 1~100    | TS lane 단독 진입 기대 안 함. primary 다른 family 가 끌어올린 케이스의 결산/시점 컨텍스트 보조 역할. |
| TOP 100~500  | TS lane 약함. 단독 진입 시 false positive (정상 결산) 위험 — caption 으로 한계 명시.                 |
| TOP 500~2000 | TS lane coverage 점진 회복. context 보조 lane 으로 의미.                                             |
| TOP 2000+    | TS lane 보조 coverage 회복. 결산/시점 컨텍스트 후보 검토 lane.                                       |

### 2.3 batch_local_ecdf_caveat

현 ECDF 는 inference batch 분포 기준이다. 회사별 routine closing calendar / batch 시각대 baseline 은 **미적용**.

| 한계                                                                          | 영향                                                                                  |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 정상 결산 이벤트 (월말·분기말·연말) 와 조작 결산 이벤트 가 batch 분포상 겹침  | TOP100/500 단독 분리 불가능 — caption 으로 사용자에게 명시                            |
| 회사별 batch 일괄기표 시각대 (예: 매월 1일 새벽 일괄 posting) baseline 미반영 | TS02 unusual_frequency 의 false positive 가능 — 정상 batch 도 빈도 이상으로 분류 가능 |

후속 과제 (별도 PR):
- `routine_closing_calendar_profile` company 단위 baseline (CompanyContext.engagement_profile 확장)
- `routine_batch_timeslot_profile` user/account 단위 baseline

본 락은 후속 과제 도입 **전까지** 의 운영 한계를 명시만 한다.

---

## 3. yaml 메타 (단일 출처)

`config/phase2_subdetector_tiers.yaml` TS01/TS02 항목.

```yaml
- family: timeseries
  code: TS01
  label: transaction_burst
  tier: moderate
  ...
  # ── role lock (결정 9, 2026-05-25) ──
  role_lock: context_lane
  ranker_use: top2000_plus_context
  do_not_tune_for_top_recall: true
  coverage_profile: "TOP100~500 단독 약함, TOP2000+ 보조 coverage 회복 (결산/시점 컨텍스트 lane)"
  batch_local_ecdf_caveat: "현 ECDF 는 inference batch 분포 기준. 회사별 routine closing calendar baseline 미적용 — ..."

- family: timeseries
  code: TS02
  label: unusual_frequency
  tier: weak
  ...
  role_lock: context_lane
  ranker_use: top2000_plus_context
  do_not_tune_for_top_recall: true
  coverage_profile: "TOP100~500 단독 약함, TOP2000+ 보조 coverage 회복 (빈도 컨텍스트 lane)"
  batch_local_ecdf_caveat: "현 ECDF 는 inference batch 분포 기준. 회사별 routine batch 시각대 baseline 미적용 — ..."
```

다른 family (`relational`/`duplicate`/`intercompany`/`unsupervised`) 는 본 메타 5필드 미설정. 락 범위는 timeseries 한정 (`TestTimeseriesRoleLock::test_non_timeseries_families_have_no_role_lock` 가드).

---

## 4. 가드 위치

| ID  | 가드                                                                       | 위치                                                                                                                  |
| --- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| TL1 | TS01 `role_lock == "context_lane"`                                         | `tests/phase2_rulebase/test_subdetector_tiers_schema.py::TestTimeseriesRoleLock::test_ts01_role_lock_is_context_lane` |
| TL2 | TS02 `role_lock == "context_lane"`                                         | 동 `::test_ts02_role_lock_is_context_lane`                                                                            |
| TL3 | TS01 `do_not_tune_for_top_recall == True`                                  | 동 `::test_ts01_do_not_tune_for_top_recall`                                                                           |
| TL4 | TS02 `do_not_tune_for_top_recall == True`                                  | 동 `::test_ts02_do_not_tune_for_top_recall`                                                                           |
| TL5 | TS01/TS02 `ranker_use == "top2000_plus_context"`                           | 동 `::test_ts_ranker_use_top2000_plus`                                                                                |
| TL6 | TS01/TS02 `coverage_profile` 비어있지 않음                                 | 동 `::test_ts_coverage_profile_present`                                                                               |
| TL7 | TS01/TS02 `batch_local_ecdf_caveat` 비어있지 않음 + "baseline" 키워드 포함 | 동 `::test_ts_batch_local_ecdf_caveat_present`                                                                        |
| TL8 | 다른 family 에 role_lock 설정 금지                                         | 동 `::test_non_timeseries_families_have_no_role_lock`                                                                 |

`uv run pytest tests/phase2_rulebase/test_subdetector_tiers_schema.py -k TimeseriesRoleLock` 로 8 케이스 검증.

---

## 5. UI 표현 정합

| 경로                                                                     | 변경                                                                                          |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `dashboard/components/phase2_family_lanes.py::LANE_LABELS["timeseries"]` | `"Timing (시계열)"` → `"Timing Context (결산·시점 보조)"`                                     |
| 동 `render_lane_view` caption                                            | "단독 ranker 아님. 결산/시점 보조 lane. primary queue 영향 없음."                             |
| 동 timeseries lane 진입 시 한계 안내                                     | "TOP100~500 단독 약함. TOP2000+ 보조 coverage. routine closing calendar baseline 후속."       |
| `dashboard/tab_phase2.py::_LANE_LABELS_KR["timeseries"]`                 | `"시점 이상"` → `"결산·시점 컨텍스트"`                                                        |
| 동 `_LANE_HINTS["timeseries"]`                                           | "거래 빈도·집중 등 시계열 이상" → "결산/시점/빈도 컨텍스트. 단독 ranker 아님 (TOP2000+ 보조)" |

---

## 6. 변경 절차

본 락의 yaml 값 (특히 `role_lock` / `do_not_tune_for_top_recall` / `ranker_use`) 또는 본 문서의 §2 정책을 변경하려면 모두 통과해야 한다.

1. **사유 검증** — 변경 사유에 다음이 **단독으로** 포함되면 안 됨:
   - DataSynth `is_fraud` / `is_anomaly` truth recall 향상
   - "TOP100/500 단독 precision 개선"
   - "lane 단독 ranker metric 향상"

2. **허용 사유 (단독 또는 조합)**:
   - 기준서 변경 (ISA 240 / PCAOB AS 2401 / ISA 550 신규 인용)
   - 운영 도메인 변경 (회사별 routine closing calendar profile 활성화 등)
   - 분포 baseline 변경 (POST-MIGRATION REMEASUREMENT 완료 후 distribution_metric 갱신)
   - PHASE2 family ranking 정책 변경 (결정 8 갱신과 동반)

3. **PR 절차**:
   - `docs/spec/DECISION.md` D044 PR 템플릿의 "PHASE2 sub-detector tier 변경" fitting-risk check 통과
   - `TestTimeseriesRoleLock` 가드 갱신 + 회귀 통과
   - 본 문서 §변경 이력 표 갱신

---

## 7. 변경 이력

| 일자       | 변경                                               | 사유                                                                                                                                                  | PR        |
| ---------- | -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| 2026-05-25 | 결정 9 도입, TS01/TS02 role_lock=context_lane 설정 | TOP100/500 단독 precision 추격에 의한 fitting attractor (period_end/manual/amount_tail) 차단. PHASE1 truth-recall-guard 의 PHASE2 family-scoped 적용. | (본 변경) |

---

## 8. 관련 문서

- [docs/spec/PHASE2_GOVERNANCE_DESIGN.md §결정 9](PHASE2_GOVERNANCE_DESIGN.md) — 거버넌스 결정 본문
- [docs/spec/PHASE2_GOVERNANCE_DESIGN.md §결정 8](PHASE2_GOVERNANCE_DESIGN.md) — Noisy-OR voter 형식 (TS family 가 voter 의 하나로 결합)
- [docs/spec/PHASE2_FITTING_AUDIT.md](PHASE2_FITTING_AUDIT.md) — fitting attractor 정의 + 검증 단계
- [docs/spec/CONSTRAINTS.md PHASE1 CI KPI 가드](CONSTRAINTS.md) — truth-recall-guard 원칙
- [config/phase2_subdetector_tiers.yaml](../../config/phase2_subdetector_tiers.yaml) — TS01/TS02 메타 단일 출처
