# 코드 작업 프롬프트 — L3-03 (관계사 거래) binary 재정의

## 0. 응답 규약
- **모든 보고·설명은 한국어로.**
- "STATUS: DONE/BLOCKED" + 단계별 증거(diff 요약·rg 출력·테스트 수치·toy 결과)를 그대로 붙여라. 출력 없는 PASS는 무효(hollow-PASS).

## 1. 배경 / 결정 (문서 SoT 이미 반영됨)
- `docs/spec/DETECTION_RULES.md` L3-03 카드: **관계사 전용 계정(IC prefix) 사용이면 flag `1.0`, 아니면 `0`** 단일 binary context 태그. 구 `score_series=0.40` 모집단 점수 폐기.
- L3-03은 "이 전표가 관계사 계정을 썼다"는 사실만 표시한다(부정·순환 확정 아님). 관계사+역분개·관계사+미대사 등 **조합 가중은 통합점수체계 소관**. 룰은 관계사 계정 사용 여부만 본다.
- IC01/IC02/IC03 대사 예외·GR01/GR03 그래프는 **PHASE1-2 family**(`DETECTION_RULES_PHASE1-2.MD` §4.4/§4.5)로 L3-03과 별개다 — 본 작업에서 건드리지 않는다.

## 2. 대상 함수
`src/detection/fraud_rules_access.py` → `b10_intercompany_review_signal()` (현재 :1975~:2029)

### 변경 (binary)
- `score_series.loc[ic_mask] = 0.4` (:2007) → **`1.0`**.
- row_annotation `"score": 0.4` (:2013) → **`1.0`**.
- `is_intercompany` 모집단 판정·breakdown(`ic_population_rows/docs`, `ic_company_count`, `trading_partner_coverage_ratio`)·annotation(`signal_category=ic_population`, `company_code`, `trading_partner`)은 **유지**.
- 함수 끝의 `ic_companies < 2` 분기(:2024-2027)는 동작 변화 없음(그대로 둠) — 단 binary flag/score에는 영향 없어야 한다.

## 3. 다운스트림 정리 (rg 전수)
- L3-03 raw `0.40` 전용 정규화/기여도(약 `0.036`)에 의존하는 코드가 있으면 binary 1/0 기준으로 정합화. `rg -n "L3-03|b10_intercompany|intercompany_review" src/detection/ src/metrics/` 로 소비자 확인.
- `score_aggregator.py`/`rule_scoring.py`에서 L3-03을 `weak/booster`/`standalone_rankable=False`로 다루는 로직은 유지(단독 tier 미생성). 0.40 특정 숫자에 박힌 분기만 1.0으로.

## 4. 검증 게이트 (전부 출력 첨부)
- **G1 (구 점수 0)**: `b10_intercompany_review_signal` 함수 본문에 `0.4` 잔존 0. `rg -n "0\.4\b" src/detection/fraud_rules_access.py` 결과 중 b10 구간 0건. 실패조건: 0.4 잔존.
- **G2 (binary toy, ripple — 2케이스)**: 직접 호출 —
  - ① `is_intercompany=[True, False]` → flags `[True, False]`, `score_series` `[1.0, 0.0]`
  - ② 관계사 prefix 계정(`gl_account` 1150 등)으로 `is_intercompany` 파생되는 입력 → 해당 행 score `1.0`
  - 출력 첨부. 실패조건: 기대값 불일치.
- **G3 (score 고유값)**: b10 결과 `score_series` 고유값이 `{0.0, 1.0}`뿐. 실패조건: 0.4 등장.
- **G4 (전체 스위트)**: `uv run pytest tests/modules/test_detection/ -q -k "not composite_sort_score_v126_truth_capture_thresholds"` → 신규 실패 0(폐기 0.40 테스트 갱신은 정당, 다른 룰 테스트 가위질 금지). baseline 직전 통과수 기준 신규 fail/error 0.
- **G5 (조합 유지)**: L3-03+다른신호 조합 case가 통합점수에서 여전히 묶이는지 1케이스 확인(룰 binary화 후에도 조합 결과 유지).

## 5. 보고 형식
```
STATUS: DONE
G1: rg … b10 구간 0.4 = 0
G2: ①[1.0,0.0] ②prefix→1.0
G3: 고유값 {0.0,1.0}
G4: pytest … 신규 fail 0
G5: 조합 case 유지
변경 파일/라인 + 다운스트림 정리 내역
```
