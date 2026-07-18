# PHASE1-2 백엔드 검증 리포트

측정 2026-07-15. 대상: 입구 가드 · 첫등장/희소 자기 큐 · 라운드넘버 밀집도(+ is_round_number 정의 교체).
UI(PLAN §3 Phase 5·6)는 사용자 지시로 범위 외. 계획 SoT: [PLAN.md](PLAN.md).

## 1. 데이터셋 (2케이스 — ripple-search)

| 데이터셋                                                | 행수(3개년 통합) | company_code            |
| ------------------------------------------------------- | ---------------: | ----------------------- |
| `datasynth_semantic_v1_normal_..._v53_..._r6`           |          376,727 | C001 단일               |
| `datasynth_contract_v3_rebuild_20260630_r1`             |   369,545 (2024) | C001·C002·C003 + 결측 6 |
| `datasynth_integrated_usefulness_all_fraud_20260702_v1` |          381,791 | C001 단일               |

> 전체 15개 데이터셋 중 다회사는 `contract_v3_rebuild_20260630_r1` **1개뿐**(14개는 C001 단일).
> 계획서 Phase 1(회사별 실행 후 병합)의 전제가 DataSynth 재생성으로 대부분 해소됨 → 입구 가드로 대체(2026-07-15 사용자 결정).

## 2. S1 입구 가드 — PASS

| 케이스                       | 회사 수 | 결측 행 | 경고 |
| ---------------------------- | ------: | ------: | ---: |
| contract_v3_rebuild (다회사) |       3 |       6 |    1 |
| v53_r6 (단일회사)            |       1 |       0 |    0 |

- 단위테스트 6/6 통과 (`tests/modules/test_pipeline/test_single_company_guard.py`).
- 결측 `company_code` 는 회사로 세지 않는다 — 세면 단일회사 원장이 다회사로 오판된다.
- 경고 문구에 오염 룰 7종을 명시: L4-01·L1-06·L2-03·L2-05·L4-05·L4-06·L3-09.

### 2.1 회사 오염 전수 조사 (근거)

통계성 룰 **17개 중 7개**가 회사를 가로질러 오염(조사 2026-07-15, 코드 줄 확인).

| 오염 룰 | 근거 (파일:줄)                               | groupby 키                                              |
| ------- | -------------------------------------------- | ------------------------------------------------------- |
| L4-01   | `feature/amount_features.py:183,201-203`     | `gl_account` 단독, 최종 fallback = **전체 df mean/std** |
| L1-06   | `fraud_rules_access.py:1343-1347`            | `created_by` 단독                                       |
| L2-03   | `fraud_rules_groupby.py:291-294,322-338`     | company 키 없음                                         |
| L2-05   | `anomaly_rules_reversal.py:289-290`          | `[gl_account,_amt_key]`                                 |
| L4-05   | `anomaly_rules_simple.py:1164,1234-1241`     | `created_by` + 전역 sigma                               |
| L4-06   | `anomaly_rules_batch.py:198,221-223,256-261` | 전역/`posting_date`                                     |
| L3-09   | `anomaly_rules_simple.py:810`                | 전역 `posting.max()`                                    |

안전(company_code 포함): L4-02·L4-03·L4-04·L2-02·D01·D02.

## 3. S2 첫등장/희소 거래처 자기 큐 — PASS

`compute_partner_signals()` 의 `.partner_summary` 가 계산 후 버려지고 있었다(배지 `.row_badges` 만 배선).

| 항목                           |      값 |
| ------------------------------ | ------: |
| 원장 거래처 총수               |   2,966 |
| first_seen                     |     568 |
| rare                           |     596 |
| dormant                        |      22 |
| **partner_summary (합집합) M** | **625** |
| **partner_findings N**         | **625** |
| M == N                         |    True |

- top_n=200 절단 동작 확인(625 → 200).
- first_seen 568/2,966 = 19% — PLAN §3 Phase 3 검증 기준("0도 전부도 아닌 중간값") 충족.
- 단위테스트 6/6 (`tests/modules/test_detection/test_partner_macro_queue.py`).
- **설계 변경**: `macro_findings` 가 아니라 신규 키 `partner_findings` 로 분리. 이유 — macro 정렬키는 `review_score`(0~1)인데 거래처 정렬키는 합계금액(~10^10)이라 한 리스트에 섞으면 거래처가 `top_n`(100) 을 독식해 Benford/D01/D02 finding 이 잘린다. 단위도 계정/프로세스가 아닌 거래처(UNIT_MEASUREMENT_POLICY).
- 접근자: `build_phase1_partner_finding_queue()` (`src/export/phase1_case_view.py`).

## 4. S3a is_round_number 정의 교체 — PASS

### 4.1 구 정의가 죽어 있던 근거 (실측)

| 지표                           |                                       값 |
| ------------------------------ | ---------------------------------------: |
| 거래 금액 중앙값               |                                295,135원 |
| p10 / max                      |              1,526원 / 205,725,640,520원 |
| **100만원 미만 거래 비율**     | **64.9%** (구조적으로 100만원 배수 불가) |
| 구 정의 round 비율(정상·fraud) |                 0.037% (38만행 중 141행) |

절대 단위 하나로는 8자릿수에 걸친 금액을 잴 수 없다 → 규모 대비 끝자리 0 개수(유효숫자)로 전환.

### 4.2 임계 선정 (실측 기반)

| 정의                        |       round 비율 |
| --------------------------- | ---------------: |
| 유효숫자 ≤1 & 자릿수 ≥3     |            2.46% |
| **유효숫자 ≤2 & 자릿수 ≥3** | **5.16%** ← 채택 |
| 유효숫자 ≤3 & 자릿수 ≥3     |           14.49% |

### 4.3 소비처 전환 M/N = 5/5

| 소비처                                               | 전환                                                             |
| ---------------------------------------------------- | ---------------------------------------------------------------- |
| `config/settings.py`                                 | `round_unit` → `round_max_significant_digits`·`round_min_digits` |
| `src/feature/amount_features.py`                     | `add_is_round_number` 재정의 + `significant_digit_stats` 신설    |
| `src/detection/timeseries_rules.py`                  | `round_amount_score` fallback 동일 기준으로                      |
| `tests/datasynth_quality_gate/checks/tier5_label.py` | T5-17 `%1M=0` → 유효숫자 SQL                                     |
| `config/presets/construction.yaml`                   | `round_unit: 10M` → `round_max_significant_digits: 1`            |
| `dashboard/components/threshold_sidebar.py`          | 선택박스 항목 교체                                               |

`round_unit` 실코드 잔존 grep 히트 = **0** (주석의 폐기 이력 4건 제외).

## 5. S3 라운드넘버 밀집도 자기 큐 — PASS

계정·월·작성자 **축별 독립** 이항검정(baseline = 원장 자체 round 비율).

| 데이터셋    |    행수 | baseline | finding |                                       내역 |
| ----------- | ------: | -------: | ------: | -----------------------------------------: |
| 정상 v53_r6 | 376,727 |    5.52% |   **1** |       created_by ARCLERK011 (n=100, 29.0%) |
| fraud v1    | 381,791 |    6.03% |   **3** | gl_account 9300·500860·500880 (11.8~14.0%) |

- 정상 37만 행에서 1건 = 과탐 아님. 단 ARCLERK011(29% vs 5.5%)은 DataSynth persona 아티팩트 가능성 — **미확인, 후속 점검 대상**.
- 정의 교체 전에는 정상·fraud 양쪽 모두 finding 0건(발화 불가)이었다.
- 단위테스트 7/7 (`tests/modules/test_detection/test_round_density_rules.py`).
- 임계는 전부 settings read — §3 리터럴 금지 준수.

## 6. S6 회귀 — PASS (신규 실패 0)

| 스위트                                                                                   |                                       결과 |
| ---------------------------------------------------------------------------------------- | -----------------------------------------: |
| `tests/phase1_rulebase/`                                                                 | **25 passed** (baseline.md 기준 25 = 동일) |
| `tests/modules/test_feature/ test_detection/` + phase1_rulebase                          |   1,473 passed / 19 skipped / **0 failed** |
| `test_pipeline/ test_export/ test_preprocessing/ test_validation/ test_db/ test_models/` |     671 passed / 21 skipped / **1 failed** |

**유일한 실패 = 기존 실패(제 변경과 무관).**
`tests/modules/test_db/test_batch_reader.py::TestDetectorStatuses::test_restored_core_tracks_default_to_executed` → `KeyError: 'duplicate'`.
HEAD 소스를 별도 worktree 에 체크아웃해 동일 테스트 실행 → **HEAD 에서도 동일하게 1 failed**. 원인은 앞선 커밋 `aaf0390`(duplicate 탐지기 제거) 의 잔재이며 본 작업 범위 밖.

## 7. S5 점수 비병합 — PASS (측정 완료)

`is_round_number` 는 `config/phase1_case.yaml` `weak_evidence.boolean_columns` 에 포함되어 있어
정의 교체가 case priority 를 밀 수 있다는 우려가 있었다. **동일 데이터셋·동일 탐지 결과로
case 빌드만 신/구 정의로 2회 수행해 직접 측정**했다(탐지 룰은 `is_round_number` 미참조 — PHASE2
timeseries lane 전용이라 탐지 결과가 두 정의에서 동일).

데이터: v53_r6 3개년 통합 376,727행 / 탐지기 5종 1회 실행 / case 28,455건.

| 지표                              |        구 정의 |           신 정의 |       차이 |
| --------------------------------- | -------------: | ----------------: | ---------: |
| `is_round_number`                 | 0.033% (126행) | 5.519% (20,793행) |  +20,667행 |
| case HIGH                         |          1,186 |             1,186 |     **+0** |
| case MEDIUM                       |         26,837 |            26,837 |     **+0** |
| case LOW                          |            432 |               432 |     **+0** |
| `priority_score` 합계             |      21346.350 |         21346.350 | **+0.000** |
| `weak_evidence_bonus` > 0 인 case |         13,391 |            19,255 |     +5,864 |

### 7.1 왜 보너스는 늘었는데 점수는 그대로인가 (코드 근거)

`phase1_case_builder.py:1820`:

```python
# band·정렬은 tier 가 결정(가중합 아님). priority_score 는 tier 대표값(소비처 [0,1] 호환).
case_tier_value = case_tier(topic_tiers)
priority_band = _TIER_TO_BAND.get(case_tier_value, "low")
priority_score = _TIER_TO_PRIORITY_SCORE.get(case_tier_value, 0.0)
```

`_apply_priority_adjustments`(:4844 `adjusted_priority += sum(bonuses.values())`)가 더한 값은
**1820 에서 tier 대표값으로 통째로 덮어써진다**. PHASE1 tier 재설계(가중합·floor·band컷 폐기)의
결과이며, `weak_evidence_bonus`·`topside_bonus` 는 계산·저장되지만 **등급에 기여하지 않는 사문화 경로**다.

tier 내부 tiebreak 인 `composite_sort_score` 도 입력이 `_tier_sort_score(case_tier_value, case_hits,
amount_score)` 뿐이라 `is_round_number` 와 무관하다.

### 7.2 남는 영향 (등급 무관)

- `weak_evidence_bonus` / `badge_tags` **필드 값**은 바뀐다(표시·진단용).
- PHASE2 timeseries `round_amount_score` context 신호는 바뀐다 — 별도 surface(3-surface 불변식상 비병합).

### 7.3 부수 발견 (미수정)

`weak_evidence_bonus`·`topside_bonus` 는 계산 후 tier 에 덮어써지는 dead path 다.
`config/phase1_case.yaml` 의 `weak_evidence.per_tag_bonus`·`max_bonus`·`topside.*_bonus` 도 같은 상태.
정리 여부는 별도 결정 대상(본 작업 범위 밖).

## 8. S4 시계열 당기내 집중 — 구현 완료, **정상 과탐으로 보류 (OPEN)**

구현: `src/detection/timeseries_concentration_rules.py` — 계정별 × 일/주/월 3축 독립,
계정·연도 자신의 median/MAD 대비 robust-z(`_robust_z` 재활용: MAD→IQR→Poisson 폴백). 단위테스트 9/9.

| 데이터셋    |    행수 | 계정 | finding |                             축별 |
| ----------- | ------: | ---: | ------: | -------------------------------: |
| 정상 v53_r6 | 376,727 |   57 | **864** |    day 497 · week 315 · month 52 |
| fraud v1    | 381,791 |  428 |   2,357 | day 611 · week 1,273 · month 473 |

### 8.1 정상 과탐 진단 — DataSynth 아티팩트 아님

정상 데이터 finding 864건의 **버킷 월 분포**:

| 월  |   1 |   2 |  **3** |   4 |   5 |   **6** |   7 |   8 |  **9** |  10 |  11 |  **12** |
| --- | --: | --: | -----: | --: | --: | ------: | --: | --: | -----: | --: | --: | ------: |
| 건  |  26 |  30 | **95** |  28 |  39 | **112** |  36 |  32 | **88** |  36 |  35 | **307** |

**분기말(3·6·9·12) = 602/864 = 70%.** 12월만 307건(35.5%).

PLAN §6 DataSynth 게이트("정상 과탐 시 생성 아티팩트인지 점검, 맞으면 Rust 수정")를 적용한 결과
**아티팩트가 아니다**. 분기·연말 결산 집중(결산조정·감가상각·충당금)은 실무상 정상이며,
DataSynth 를 고쳐 없애면 데이터가 오히려 비현실적이 된다.

원인은 **baseline 설계**다. 계정·연도 자신의 median 과 비교하면 "이 계정은 분기말에 바쁘다"를
계정마다 재발견한다. 이 신호는 감사인이 이미 알고 있고, PHASE1-1 `L3-04`(기말 전표)가 행 단위로
이미 커버한다. ACFE "결산 직전 이례적 집중"을 잡으려면 **기말이라는 사실**이 아니라
**기말치고도 이례적인지**를 봐야 하며, 그러려면 계절성 통제가 필요하다.

### 8.2 추가 결함 — macro 큐 top_n 독식

`macro_findings` 는 `macro_priority_score or review_score` 로 정렬 후 `top_n`(기본 100) 절단한다.

| finding 종류      | 정렬 점수 실측 |
| ----------------- | -------------: |
| TS 당기내 집중    |    0.85 ~ 0.91 |
| 라운드넘버 밀집도 |    0.06 ~ 0.23 |

현 배선대로면 TS 가 상위 100건을 독식해 Benford·D01·D02·밀집도 finding 이 큐에서 사라진다.
(같은 문제로 §3 거래처 finding 은 이미 별도 키로 분리했다.)

### 8.3 계절성 통제 시도 → 부분 개선에 그침

분기말(회계기수 % 3 == 0) / 평월 레인을 분리해 각 레인 안에서만 baseline 산출:

| 지표             | 통제 전 | 통제 후 |
| ---------------- | ------: | ------: |
| 정상 finding     |     864 |     595 |
| 분기말 버킷 비중 |   70.0% |   52.4% |
| 12월 버킷        |     307 |     185 |

여전히 12월이 최다다. 상위 finding `400370 / 2024-12 / 1,004건 vs 중앙값 357.5(z=34.9)` —
**연말 결산은 분기 결산과 무게가 다르다**(감가상각·충당금·법인세가 12월에만 얹힘). 같은 "분기말"
레인으로 묶어 3·6·9월과 비교해도 12월은 매번 튄다.

### 8.4 원리적 한계 — 당기 내 baseline 으로는 연말을 판정할 수 없다

**한 해에 연말은 한 번뿐**이라 "이번 연말이 연말치고도 이상한가"의 비교 대상이 당기 안에 없다.
판정하려면 전기 연말과 비교해야 하는데, 그것은 PLAN §6 이 못박은 "전기비교 아님 · 당기 내
baseline" 전제와 정면 충돌한다. **PLAN §6 의 전제가 데이터 앞에서 성립하지 않는다.**

### 8.5 D02 중복 — "작년 같은 달과 비교"는 이미 D02 소관

D02 명세(`DETECTION_RULES_PHASE1-2.MD`): JSD 로 **전기/당기 월별 분포 비교**, 단위
`[company_code, gl_account]`, 잡는 신호 "전기엔 고르게 발생하던 계정이 당기엔 **결산월·특정 분기·
특정 프로젝트 월에 몰리는 경우**". 같은 달 전년 대비 비교를 계정별로 요약한 것이 D02 다.
재구현하면 통계만 바꾼 중복이 된다. 또한 데이터가 3개년이라 같은 달 비교의 기준점이 1~2개뿐이라
median/MAD 가 성립하지 않고 D01 식 단순 변동률이 될 수밖에 없다 — 더욱 D01/D02 다.

### 8.6 결정 (2026-07-15 사용자)

**자기 큐 6종에서 제외하고 D02 드릴다운으로 재정의.** D02 가 "이 계정 월분포가 바뀌었다"를 띄우면,
그 계정의 어느 달이 작년 같은 달 대비 몇 배인지를 상세로 보여준다. 새 룰이 아니라 D02 상세정보.

- 코드: `timeseries_concentration_rules.py` + 테스트 9/9 **보존**(당기내 robust-z 자산),
  `phase1_case_builder` 배선 **제거**(`_build_ts_concentration_macro_findings` 삭제).
- 미구현: D02 드릴다운 자체. 다음 작업 단위.
- 문서 갱신 **완료**(2026-07-15) — 대조 결과 [doc_sync_verify.md](doc_sync_verify.md).

## 9. 큐 절단 제거 (2026-07-15 사용자 결정)

**PHASE1-2 는 신호를 만들 뿐 검토 목록을 소유하지 않는다.** 무엇을 몇 개 보여줄지는 화면 몫이다.

기존 코드(커밋 `18a5a47`)가 `macro_findings` 를 정렬 후 `findings[:100]` 으로 잘랐다. 백엔드가
미리 잘라내면 화면은 사라진 신호를 볼 수 없고, 신호 종류마다 점수 척도가 달라(Benford 0~1 vs
robust-z 무상한) 척도 큰 종류가 칸을 독식한다.

- `_build_macro_findings` top_n(100) 제거 — Benford·D01·D02·라운드넘버 밀집도 전부 해당.
- `_build_partner_findings` top_n(200) 제거.
- 회귀: phase1_rulebase + detection + export + pipeline + feature **1,703 passed / 0 failed**.
