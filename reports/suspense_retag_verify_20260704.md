# 가계정(is_suspense_account) 오태깅 근본 수정 검증 — 2026-07-04

## 배경

L3-09(가수금 장기체류)에 '대여금' 계정을 추가하려던 중, 가계정 판별
(`is_suspense_account`)이 stale 키워드/코드 prefix 휴리스틱으로 계산되어 대량
오태깅됨을 발견. 정답(권위)은 datasynth CoA(`chart_of_accounts.json`)의 계정별
`is_suspense_account` 플래그다. 원래 '대여금' 요청은 이 권위 방식으로 superseded.

- 부수 확인: config `chart_of_accounts.csv`는 `1150`=단기대여금으로 표기하나,
  실제 datasynth CoA에선 `1150`=Intercompany AR Clearing. 이 CoA엔 단기대여금
  전용 계정이 없다. `startswith("1150")`는 `115001~3`(IC Receivable)까지 오포함.

## 수정 내용 (코드)

- `src/feature/pattern_features.py`
  - `_load_coa_suspense_codes(source_path)`: 원장 파일 옆 `chart_of_accounts.json`의
    `is_suspense_account=True` 계정 코드 집합 반환. 파일없음/빈집합이면 None.
  - `add_is_suspense_account(..., coa_suspense_codes=None)`: 권위 집합이 있으면
    `gl_account` 정확 매칭만 사용(키워드/prefix 미사용), 없으면 기존 휴리스틱 폴백.
  - `add_all_pattern_features(..., source_path=None)`: 권위 해소 후 주입.
- `src/feature/engine.py`: thin-copy가 df.attrs를 버리기 전에 source_path를
  1회 확정해 순차·병렬 경로 모두에 스레딩.

## 측정 (권위 대조)

기준 데이터셋: `datasynth_semantic_v1_normal_20260703_v53_account_determination_r6`
전 행 N = 376,727. CoA 권위 가계정 코드 = 13개
(`1030, 1190, 199000, 199100, 199200, 199300, 2190, 2900, 9000, 9100, 9200, 9300, 9990`).

| 항목                        | 수정 전(휴리스틱) | 수정 후(권위) | 판정 |
| --------------------------- | ----------------: | ------------: | ---- |
| is_suspense True 행         |             2,652 |       **801** | —    |
| CoA 권위 기준 True 행       |               801 |           801 | 기준 |
| feature == 권위 전 행 일치  |                 — |      **True** | PASS |
| 누락(권위 True인데 미태깅)  |                 0 |             0 | PASS |
| 오태깅(권위 False인데 태깅) |             1,851 |         **0** | PASS |

오태깅 주범 코드 소거 확인(수정 후 suspense_true):

| 코드   |   행수 | 수정 후 True | 비고                           |
| ------ | -----: | -----------: | ------------------------------ |
| 1290   |    306 |            0 | 기타비유동자산 (권위 False)    |
| 1020   |  5,562 |            0 | 현금성, 적요 'Clearing' 오매칭 |
| 2500   |  4,402 |            0 | 권위 False                     |
| 100030 | 86,694 |            0 | 권위 False                     |

## 회귀·폴백 검증

- 순차/병렬 모두 True=801 동일(engine source_path 스레딩 확인).
- source_path 없는 synthetic df → 휴리스틱 폴백 동작(단위테스트).
- `chart_of_accounts.json` 없음/빈 suspense set → None 반환 → 휴리스틱 폴백.
- `tests/modules/test_feature/` + `tests/modules/test_detection/`: 1,426 passed, 19 skipped.
- `test_pattern_features.py` 신규 CoA 권위 테스트 7건 PASS.

## 한계·후속

- config `chart_of_accounts.csv`의 `1150=단기대여금` 표기와 datasynth CoA의
  `1150=IC AR Clearing` 불일치는 별도 이슈(본 수정은 datasynth CoA json을 권위로
  사용하므로 영향 없음). 표기 정합화는 후속 과제.
- 실무 CoA에 `is_suspense_account` 플래그가 없으면 자동으로 키워드/코드 휴리스틱
  폴백(하위호환 유지).
- normal 현실성 게이트(수동)의 가계정 관련 지표는 태깅 축소로 값이 이동할 수 있음.
