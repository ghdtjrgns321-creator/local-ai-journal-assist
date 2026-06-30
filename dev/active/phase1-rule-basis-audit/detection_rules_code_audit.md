# DETECTION_RULES.md 룰 설명 ↔ 코드 일치 전수 대조 (2026-06-21)

대상: DETECTION_RULES.md PHASE1-1 룰 카드 **26개**(L1 9 + L2 5 + L3 9 + L4 3). 멀티에이전트 4그룹(레이어별) 병렬 대조 후 핵심 2건 자체 재현.
대조 축: ①구현함수 존재 ②필요피처 코드사용 ③탐지로직 일치 ④severity=constants.SEVERITY_MAP ⑤파라미터 기본값=config/settings.

## 종합 집계

| 레이어 | 분모   | 완전일치 | 코드 기능 불일치 | 문서 서술 정합성 문제          |
| ------ | ------ | -------- | ---------------- | ------------------------------ |
| L1     | 9      | 7        | 0                | 2 (L1-06 메타·L1-07-02 함수명) |
| L2     | 5      | 5        | 0                | 0                              |
| L3     | 9      | 7        | 0                | 2 (L3-02 서술·L3-10 메모)      |
| L4     | 3      | 2        | **1 (L4-04)**    | 0                              |
| **계** | **26** | **21**   | **1**            | **4**                          |

- **코드가 문서와 다르게 동작(기능 불일치): L4-04 1건.**
- **코드 동작은 문서와 정합이나 문서/메타가 stale(서술 정합성): 4건.**
- severity 26/26 전부 SEVERITY_MAP 일치. 파라미터 기본값 L4-04 제외 전부 config/settings 일치.

## L1 (9): 일치 7 / 서술문제 2

| 룰       | 구현함수                                             | sev(문서=MAP) | 판정                                                                                                                  |
| -------- | ---------------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------- |
| L1-01    | integrity_layer.py `_a01_unbalanced_entry`           | 5=5           | 일치                                                                                                                  |
| L1-02    | integrity_layer.py `_a02_missing_required`           | 2=2           | 일치                                                                                                                  |
| L1-03    | integrity_layer.py `_a03_invalid_account`            | 3=3           | 일치                                                                                                                  |
| L1-04    | fraud_rules_feature.py `b03_exceeds_threshold`       | 3=3           | 일치                                                                                                                  |
| L1-05    | fraud_rules_access.py `b06_self_approval`            | 3=3           | 일치                                                                                                                  |
| L1-06    | fraud_rules_access.py `b07_segregation_of_duties`    | 4=4           | ⚠️서술: constants.py:521-522 used_columns에 폐기된 sod_violation·sod_conflict_type 잔존(탐지로직은 toxic쌍 방식 정상) |
| L1-07    | fraud_rules_access.py `b09_skipped_approval`         | 4=4           | 일치                                                                                                                  |
| L1-07-02 | fraud_rules_access.py `b09b_unknown_approver`        | 4=4           | ⚠️서술: 문서에 함수명 미명시(동작 일치)                                                                               |
| L1-08    | anomaly_rules_simple.py `c05_fiscal_period_mismatch` | 4=4           | 일치(공식 (month-fiscal_year_start)%12+1 일치)                                                                        |

## L2 (5): 일치 5 / 불일치 0

| 룰    | 구현함수                                                                              | sev | 판정                            |
| ----- | ------------------------------------------------------------------------------------- | --- | ------------------------------- |
| L2-01 | fraud_rules_feature.py `b02_near_threshold` + amount_features `add_is_near_threshold` | 3=3 | 일치(ratio 0.90)                |
| L2-02 | fraud_rules_groupby.py `b04_duplicate_payment`                                        | 3=3 | 일치(90일·2%·10만 cap·최소 1원) |
| L2-03 | fraud_rules_groupby.py `b05_duplicate_entry`                                          | 3=3 | 일치(near/split 폐기 반영)      |
| L2-04 | fraud_rules_groupby.py `b11_expense_capitalization`                                   | 4=4 | 일치(키워드 가감 폐기 반영)     |
| L2-05 | anomaly_rules_reversal.py `c11_reversal_entry`                                        | 4=4 | 일치(S2b/N:M 폐기 반영)         |

## L3 (9): 일치 7 / 서술문제 2

| 룰    | 구현함수                                               | sev | 판정                                                                                             |
| ----- | ------------------------------------------------------ | --- | ------------------------------------------------------------------------------------------------ |
| L3-02 | fraud_rules_feature.py `b08_manual_override`           | 4=4 | ⚠️서술: 문서가 lone_automated_mask를 L3-02가 잡는다 기술하나 실제 source_trust/case builder 소관 |
| L3-03 | fraud_rules_access.py `b10_intercompany_review_signal` | 4=4 | 일치                                                                                             |
| L3-04 | anomaly_rules_simple.py `c01_period_end_large`         | 3=3 | 일치(margin_days 5)                                                                              |
| L3-05 | anomaly_rules_simple.py `c02_weekend_entry`            | 2=2 | 일치                                                                                             |
| L3-06 | anomaly_rules_simple.py `c03_after_hours_entry`        | 2=2 | 일치(midnight 22~6)                                                                              |
| L3-07 | anomaly_rules_simple.py `c04_backdated_entry`          | 3=3 | 일치(gap>30)                                                                                     |
| L3-09 | anomaly_rules_simple.py `c10_suspense_account`         | 3=3 | 일치(aging 30, fallback 분기)                                                                    |
| L3-10 | fraud_rules_access.py `b13_estimate_account_use`       | 3=3 | ⚠️서술: 문서 rename 진행메모가 구식(코드는 이미 estimate_account_use rename 완료)                |
| L3-11 | evidence_rules.py `ev02_cutoff_violation`              | 3=3 | 일치(회계연도 경계, 일수임계 폐기)                                                               |

## L4 (3): 일치 2 / 불일치 1

| 룰    | 구현함수                                                                 | sev | 판정                         |
| ----- | ------------------------------------------------------------------------ | --- | ---------------------------- |
| L4-01 | fraud_rules_feature.py `b01_revenue_manipulation`                        | 5=5 | 일치(zscore 3.0, prefix 4)   |
| L4-03 | anomaly_rules_simple.py `c08_amount_outlier` + `_compute_pbt_thresholds` | 3=3 | 일치(pbt 5%·rev 0.5%·pm 75%) |
| L4-04 | anomaly_rules_statistical.py `c09_rare_account_pair`                     | 2=2 | ❌**기능 불일치**            |

### L4-04 기능 불일치 상세 (코드 재현 확정)
문서는 L4-04를 "cadence(분기 1회 미만) 기반 + binary(0/1) + 대형전표 자동희소 폐기 + percentile 폐기"로 **재설계**했다고 명시(DETECTION_RULES.md ~838·844·847·849·855)하나, 코드는 구버전 그대로:
- `percentile=0.01` 잔존: anomaly_rules_statistical.py:202·299(`quantile(percentile)`)·settings.py:179·anomaly_layer.py:231. cadence/분기 환산 코드 grep 0건.
- score bucket 0.25/0.35/0.45(single/multiple/large_doc) 잔존(:354-368) — 문서 binary(0/1) 약속 미반영.
- 대형전표 distinct pair 자동희소(:255-320 `_large_doc_pair`) 잔존 — 문서 "폐기" 미반영.
→ 문서가 "폐기"라 적은 3가지(percentile·score bucket·large-doc 자동희소)가 코드에 모두 살아있음. **문서 재설계가 코드 미반영 상태.**

## 결론
- DETECTION_RULES.md 26룰 중 **25룰은 코드 동작과 정합**(서술/메타 stale 4건 포함 — 동작은 맞음).
- **L4-04 1건만 코드 기능이 문서와 불일치**(문서 cadence/binary 재설계 vs 코드 percentile/bucket 구버전). → 문서대로 코드 수정 또는 코드대로 문서 되돌림 결정 필요.
- 서술 정합성 4건(L1-06 메타·L1-07-02 함수명·L3-02 서술·L3-10 메모)은 코드 무변경, 문서/constants 메타 정정 사안.
