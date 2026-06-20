# 코드 작업 프롬프트 — L3-05 (주말/공휴일 전기) binary 전환

## 0. 응답 규약
- **모든 보고·설명은 한국어로.**
- "STATUS: DONE/BLOCKED" + 단계별 증거(diff 요약·rg 출력·테스트 수치·toy 결과)를 그대로 붙여라. 출력 없는 PASS는 무효(hollow-PASS).

## 1. 배경 / 결정 (문서 SoT 이미 반영됨)
- `docs/spec/DETECTION_RULES.md` L3-05 카드: **주말(`weekday()>=5`) 또는 공휴일이면 flag `1.0`, 아니면 `0`** 단일 binary. **source는 보지 않는다.**
- 구 3단 점수(`weekday_holiday=0.35`/`weekend=0.40`/`weekend_holiday=0.45`)·PHASE1 signal_strength 변환(0.75/0.85/1.00) **폐기**.
- L3-05는 OFF-TIME context 태그(tier 게이트 미참여, severity 보조축). "자동/배치 주말 전표는 정상"의 다운웨이트는 룰이 아니라 통합점수체계가 `비근무일 + L3-02 수기 leg`로 한다. **룰은 비근무일 사실만 본다.**
- 참고: 현재 `c02_weekend_entry` 코드에는 source 기반 제외 로직이 **원래 없다**(밴드만 존재). 이번 작업은 **밴드 → binary** 전환이 본질이다.

## 2. 대상 함수
`src/detection/anomaly_rules_simple.py` → `c02_weekend_entry()` (현재 약 :212~:258)

### 제거
- `score_series` 밴드 `0.35`/`0.40`/`0.45` (현재 :212-215) 및 `weekday_holiday`/`weekend_only`/`weekend_holiday` 마스크 구분 점수 — **삭제**.
- breakdown의 `weekend_only_rows/docs`, `weekday_holiday_rows/docs`, `weekend_holiday_rows/docs`, `calendar_review_*` 세분화 — 단순화.
- annotation의 `reason_code`(weekend_holiday/weekend/weekday_holiday/holiday 4분류)·`score` 밴드값 — 사실값으로 단순화.

### 재작성 (binary)
- `flagged = weekend | holiday` (주말 또는 공휴일). 반환 = `flagged`.
- `score_series = flagged.astype(float)` (1.0 / 0.0).
- `row_annotations`: `is_weekend`, `is_holiday`, `source`, `posting_date` 등 사실값만(밴드 score·reason_code 분류 없음). `score`는 넣더라도 1.0 고정.
- `breakdown`: `flagged_rows`, `weekend_rows`, `holiday_rows`, `source_counts`.

## 3. 검증 게이트 (전부 출력 첨부)
- **G1 (밴드 제거)**: `c02_weekend_entry` 본문에 `0.35`/`0.40`/`0.45` 및 signal_strength 변환 0건. 실패조건: 밴드 잔존.
- **G2 (binary 고유값)**: `c02_weekend_entry` 결과 `score_series` 고유값 `{0.0, 1.0}`뿐. 실패조건: 0.35/0.40/0.45 등장.
- **G3 (toy, ripple — source 무관 발화 2케이스)**: 직접 호출 —
  - ① 토요일 전표 `is_weekend=[True, False]` → flags `[True, False]`, scores `[1.0, 0.0]`
  - ② **source가 자동이어도 주말이면 발화**: `is_weekend=[True,True]`, `source=['batch','manual']` → flags `[True, True]`, scores `[1.0, 1.0]`
  - ③ 공휴일 `is_holiday=[True]` → `[1.0]`
  - 출력 첨부. 실패조건: 자동 source가 0으로 빠지거나 밴드값 등장.
- **G4 (전체 스위트)**: `uv run pytest tests/modules/test_detection/ -q -k "not composite_sort_score_v126_truth_capture_thresholds"` → 신규 실패 0. 폐기 밴드 테스트 갱신은 정당, 다른 룰 테스트 가위질 금지.

## 4. 보고 형식
```
STATUS: DONE
G1: c02 밴드 0 (rg)
G2: 고유값 {0.0,1.0}
G3: ①[1.0,0.0] ②자동도[1.0,1.0] ③공휴일[1.0]
G4: pytest 신규 fail 0
변경 파일/라인 요약
```
