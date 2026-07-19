# L3-07 DataSynth v34 Candidate Retest

대상 데이터: `data/journal/primary/datasynth_v34_candidate`

분석일: 2026-04-25

## 기준

- 탐지 룰: `abs(posting_date - document_date) > 30`
- 라벨 기준 정답: `BackdatedEntry`, `LatePosting`
- negative control: `labels/lateposting_negative_controls.csv`
- 비교 단위: `document_id`
- 분석 범위: `journal_entries_2022.csv`, `journal_entries_2023.csv`, `journal_entries_2024.csv`

## 라벨 기준 결과

| year | docs | label docs | flagged docs | TP | FP | FP negctrl | FN | label-only precision | recall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 106,675 | 28 | 41 | 28 | 13 | 13 | 0 | 68.3% | 100.0% |
| 2023 | 105,525 | 38 | 56 | 38 | 18 | 18 | 0 | 67.9% | 100.0% |
| 2024 | 106,992 | 90 | 116 | 90 | 26 | 26 | 0 | 77.6% | 100.0% |
| ALL | 319,192 | 156 | 213 | 156 | 57 | 57 | 0 | 73.2% | 100.0% |

라벨만 정답으로 보면 FP 57건이 생긴다. 이 57건은 모두 v34에서 의도적으로 추가한 `business_delay` negative control이다.

## 라벨별 분포

| year | anomaly_type | detected | docs | diff min | diff max | diff median |
|---:|---|---|---:|---:|---:|---:|
| 2022 | BackdatedEntry | yes | 8 | 33 | 86 | 47.0 |
| 2022 | LatePosting | yes | 20 | 32 | 60 | 45.0 |
| 2023 | BackdatedEntry | yes | 15 | 32 | 89 | 64.0 |
| 2023 | LatePosting | yes | 23 | 31 | 60 | 45.0 |
| 2024 | BackdatedEntry | yes | 17 | 31 | 90 | 56.0 |
| 2024 | LatePosting | yes | 73 | 31 | 60 | 45.0 |

라벨 문서 기준 FN은 0이다. v33의 라벨-필드 정합성은 v34에서도 유지된다.

## Negative Control 분포

| type | docs | flagged by L3-07 | diff range | median |
|---|---:|---:|---:|---:|
| boundary | 70 | 0 | 20~30 | 24.5 |
| business_delay | 57 | 57 | 31~45 | 38.0 |

연도별 negative control:

| year | control docs | flagged | diff min | diff max | median |
|---:|---:|---:|---:|---:|---:|
| 2022 | 34 | 13 | 20 | 45 | 28.0 |
| 2023 | 42 | 18 | 20 | 45 | 29.0 |
| 2024 | 51 | 26 | 20 | 45 | 31.0 |

## 해석

v34는 v33의 완전 매칭 benchmark를 일부러 깨는 방향으로 정상 장기 지연 문서를 넣었다.

- `boundary` 70건은 diff 20~30이라 L3-07에 걸리지 않는다.
- `business_delay` 57건은 diff 31~45라 L3-07에 걸린다.
- 이 57건은 라벨 기준으로는 FP지만, 스크리닝 룰 관점에서는 정상 장기 지연도 검토 대상으로 올린 것이다.

따라서 v34의 L3-07 결과는 다음처럼 봐야 한다.

- label integrity: 통과, FN 0
- strict fraud-label precision: 73.2%
- 실무형 review population: 더 자연스러워짐
- L3-07 룰 자체 수정 필요: 없음

실무에서 `business_delay`를 과탐으로 낮추려면 L3-07 자체를 바꾸기보다 별도 suppress/triage 정책을 둔다.

- `normal_delay_reason`이 있으면 risk score 하향
- source/process/doc_type별 정상 장기 지연 whitelist
- 결산/세금계산서/검수/프로젝트 승인 지연 사유를 reviewer context로 노출
