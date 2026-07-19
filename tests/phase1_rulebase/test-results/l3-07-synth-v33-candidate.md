# L3-07 DataSynth v33 Candidate Retest

대상 데이터: `data/journal/primary/datasynth_v33_candidate`

분석일: 2026-04-25

## 기준

- 탐지 룰: `abs(posting_date - document_date) > 30`
- 정답 라벨: `BackdatedEntry`, `LatePosting`
- 비교 단위: `document_id`
- 분석 범위: `journal_entries_2022.csv`, `journal_entries_2023.csv`, `journal_entries_2024.csv`

## 결과

| year | docs | label docs | flagged docs | TP | FP | FN | precision | recall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 106,675 | 28 | 28 | 28 | 0 | 0 | 100.0% | 100.0% |
| 2023 | 105,525 | 38 | 38 | 38 | 0 | 0 | 100.0% | 100.0% |
| 2024 | 106,992 | 90 | 90 | 90 | 0 | 0 | 100.0% | 100.0% |
| ALL | 319,192 | 156 | 156 | 156 | 0 | 0 | 100.0% | 100.0% |

## 라벨별 분포

| year | anomaly_type | detected | docs | diff min | diff max | diff median |
|---:|---|---|---:|---:|---:|---:|
| 2022 | BackdatedEntry | yes | 8 | 33 | 86 | 47.0 |
| 2022 | LatePosting | yes | 20 | 32 | 60 | 45.0 |
| 2023 | BackdatedEntry | yes | 15 | 32 | 89 | 64.0 |
| 2023 | LatePosting | yes | 23 | 31 | 60 | 45.0 |
| 2024 | BackdatedEntry | yes | 17 | 31 | 90 | 56.0 |
| 2024 | LatePosting | yes | 73 | 31 | 60 | 45.0 |

## 패치 검증

`labels/lateposting_patch_cases.csv`를 확인했다.

- patch rows: `40`
- columns: `document_id`, `fiscal_year`, `previous_posting_date`, `previous_document_date`, `patched_document_date`, `intended_delay_days`, `applied_delay_days`, `previous_actual_diff_days`, `actual_diff_days`, `patch_reason`
- `actual_diff_days` range: `32`~`60`
- `actual_diff_days` median: `48`

v23에서 보였던 문제, 즉 `LatePosting` 라벨은 있는데 실제 `posting_date - document_date <= 30`이던 케이스는 v33 candidate에서 재현되지 않는다.

## 판단

v33 candidate의 L3-07 라벨 정합성은 통과다.

- FN: `0`
- FP: `0`
- `BackdatedEntry`: 전부 `abs(diff) > 30`
- `LatePosting`: 전부 `posting_date - document_date > 30`
- patch sidecar도 `actual_diff_days > 30`을 만족한다.

운영본으로 승격하려면 L3-07 단독 기준으로는 문제 없다. 다만 전체 DataSynth 승격은 다른 룰의 라벨 정합성과 품질 게이트 결과를 별도로 봐야 한다.
