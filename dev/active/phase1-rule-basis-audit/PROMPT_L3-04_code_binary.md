# 코드 작업 프롬프트 — L3-04 (기말/기초 결산) binary 재정의

## 0. 응답 규약
- **모든 보고·설명은 한국어로.**
- "STATUS: DONE/BLOCKED" + 단계별 증거(diff 요약·rg 출력·테스트 수치·toy 결과)를 그대로 붙여라. 출력 없는 PASS는 무효(hollow-PASS).

## 1. 배경 / 결정 (문서 SoT 이미 반영됨)
- `docs/spec/DETECTION_RULES.md` L3-04 카드: **월말 직전 5일 또는 월초 5일(기말/기초) 구간이면 flag `1.0`, 아니면 `0`** 단일 binary timing context 태그. 구간 폭은 `period_end_margin_days`(기본 5).
- **기말+기초 둘 다 잡는다**(한국 월차결산이 익월 초까지 이어짐). 정상 이월 노이즈는 통합점수체계가 거른다 — 룰에서 좁히지 않는다.
- **폐기**: 7버킷(`closing_base`/`closing_amount_p50~p95`/`closing_recurring_low_priority`/`none`), 금액 quantile(P50/P75/P90/P95) 점수 사다리 `0.20`/`0.35`/`0.55`/`0.70`, `period_end_sensitive_bonus`, recurring whitelist downgrade, 보강신호(high_amount/manual/abnormal_time...) 점수.
- 금액·수기·민감계정·승인·심야 등 정황 조합 가중은 **전부 통합점수체계 소관**. 룰은 기말/기초 여부만 본다.

## 2. 대상 함수
`src/detection/anomaly_rules_simple.py` → `c01_period_end_large()` (현재 :18~약 :210)

### 제거할 것
- 금액 quantile 계산 `_amount_quantiles(base, df, [0.50, quantile, 0.90, 0.95], ...)` 및 `q75`/p50/p90/p95 임계 (:37~:40 등) — **삭제**.
- `amount_p50/p75/p90/p95`, `whitelist_matched` 마스크 — **삭제**.
- `bucket` 7종 (:84~:90) — **삭제**.
- `score_series` 밴드 `0.20/0.35/0.55/0.70` + whitelist clip (:92~:97) — **삭제**.
- `period_end_sensitive_bonus`·민감계정 가중·보강신호(priority_reasons) 계산 — **삭제**.
- 함수 시그니처의 `quantile`/`min_group_size`/sensitive 관련 인자 — 미사용 시 제거(호출부 정합).

### 재작성 (binary)
- `period_end = bool_column(df, "is_period_end")` 유지. 반환 flagged = `period_end`.
- `score_series` = `period_end.astype(float)` (기말/기초 `1.0` / 아니면 `0`).
- **annotation `period_phase`**: 기말(월말 직전 구간)=`"end"`, 기초(월초 구간)=`"start"`. 구분 피처가 따로 없으면 `posting_date`의 일자로 판정(월말 근접=end, 월초=start). `is_period_start` 류 파생 컬럼이 있으면 그것을 우선 사용.
- `row_annotations`: `period_phase`, `posting_date`, `source`, `created_by`, `approved_by`, `business_process`, `account_group`, `gl_account` 중 존재 컬럼만(사실값). 버킷·score 밴드·priority_reasons **없음**.
- `breakdown`: `flagged_rows`, `period_end_rows`, `period_start_rows`, `source_counts`.

## 3. 다운스트림 + config 정리 (rg 전수)
- `rg -n "closing_amount_p|closing_base|closing_recurring|bucket_counts|period_end_sensitive_bonus|c01_period_end" src/` 로 소비자 확인 후 binary 계약에 맞게 정리. `closing_low_docs`/`closing_priority_docs`/`closing_high_docs` score band 소비자(평가·리포트·case builder)를 단순 flag 기준으로 교체.
- `config/audit_rules.yaml`/`config/settings.py`의 `period_end_amount_quantile`, `period_end_sensitive_bonus`, `c01_min_group_size`는 binary화로 **미사용**이 된다 — 제거하거나 폐기 주석. `period_end_margin_days`는 유지.

## 4. 검증 게이트 (전부 출력 첨부)
- **G1 (폐기물 0)**: `rg -n "closing_amount_p|closing_base|closing_recurring|0\.20|0\.35|0\.55|0\.70|sensitive_bonus|bucket" src/detection/anomaly_rules_simple.py` 중 c01 구간 0건(다른 함수의 무관 잔존은 분리 증명). 실패조건: c01 점수밴드/버킷 잔존.
- **G2 (binary toy, ripple — 3케이스)**: 직접 호출 —
  - ① 월말 직전 전표(`is_period_end=True`) → flag `True`, score `1.0`, annotation `period_phase="end"`
  - ② 월초 전표(기초 구간) → flag `True`, score `1.0`, `period_phase="start"`
  - ③ 월중 전표 → flag `False`, score `0.0`
  - 출력 첨부. 실패조건: 기대값/period_phase 불일치.
- **G3 (score 고유값)**: c01 결과 `score_series` 고유값 `{0.0, 1.0}`뿐. 실패조건: 0.20/0.35/0.55/0.70 등장.
- **G4 (전체 스위트)**: `uv run pytest tests/modules/test_detection/ -q -k "not composite_sort_score_v126_truth_capture_thresholds"` → 신규 실패 0(폐기 버킷/quantile 테스트 갱신은 정당, 다른 룰 테스트 가위질 금지).
- **G5 (조합 유지)**: 기말(L3-04)+고액/역분개 조합 case가 통합점수에서 여전히 상위 tier로 묶이는지 1케이스 확인(룰 binary화 후에도 조합 결과 유지).

## 5. 보고 형식
```
STATUS: DONE
G1: rg … c01 구간 점수밴드 0
G2: ①end 1.0 ②start 1.0 ③0.0
G3: 고유값 {0.0,1.0}
G4: pytest … 신규 fail 0
G5: 기말+고액 조합 case 유지
변경 파일/라인 + config 미사용 param 처리 + 다운스트림 정리 내역
```
