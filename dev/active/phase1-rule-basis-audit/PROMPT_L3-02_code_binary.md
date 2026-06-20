# 코드 작업 프롬프트 — L3-02 (수기 전표) binary 재정의

## 0. 응답 규약
- **모든 보고·설명은 한국어로.**
- "STATUS: DONE/BLOCKED" + 단계별 증거(코드 diff 요약·rg 출력·테스트 수치·toy 결과)를 그대로 붙여라.
- 출력 없는 PASS는 무효(hollow-PASS). 검증 명령과 실제 출력을 함께 제출하라.

## 1. 배경 / 결정
- 문서 SoT(`docs/spec/DETECTION_RULES.md` L3-02 카드)에서 **L3-02는 단일 binary로 확정**(2026-06-20):
  - **수기 전표면 score `1.0`, 아니면 `0`.** 그 외 가공·점수 차등 없음.
  - 판정: `is_manual_je == True`. `is_manual_je` 없으면 `source`가 `manual_source_codes`에 포함되는지.
- **폐기**: 5버킷(`manual_population`/`adjustment_population`/`manual_priority`/`manual_control_bypass`/`none`), 점수 밴드 `0.35`/`0.60`/`0.75`, `review_score_series`, `priority`/`control_bypass` 분기, `priority_reasons`/`priority_reason_counts`, `bucket`/`bucket_counts`.
- **이유**: 수기전표는 정상적으로도 흔하다(결산조정 등). "수기+고액/기말/자기승인" 같은 정황 가중은 **전부 통합점수체계(topic_scoring/통합점수)가** 한다. 룰은 수기 여부만 본다(룰은 멍청하게).

## 2. 대상 함수
`src/detection/fraud_rules_feature.py` → `b08_manual_override()` (현재 :260~:478)

### 현재(폐기 전) 구조 — 제거할 것
- `self_approval`/`skipped_approval`/`approval_date_absent`/`abnormal_time`/`period_end`/`weak_description`/`high_risk_account` 계산 (:289~:373) — **전부 삭제** (정황은 통합점수 소관).
- `control_bypass`/`priority`/`immediate` 분기 (:375~:379) — **삭제**.
- `bucket` 5종 (:381~:385) — **삭제**.
- `score_series` 0.60/0.75 + `review_score_series` 0.35 (:387~:391) — **삭제**.
- `reason_masks`/`priority_reason_counts` (:393~:407) — **삭제**.
- annotation의 `bucket`/`score(밴드)`/`source_bucket`/`priority_reasons` (:451~:461) — 사실값만 남기고 재작성.
- breakdown의 `review_rows`/`priority_rows`/`control_bypass_rows`/`bucket_counts`/`priority_reason_counts` (:465~:476) — **삭제**.

### 재작성(binary) 명세
- `candidate` (수기 여부 Boolean) 계산은 유지(:266~:284).
- 반환 Series = `candidate` (수기=True). `attrs`:
  - `score_series`: 수기 `1.0` / 비수기 `0.0` (= `candidate.astype(float)`).
  - `row_annotations`: 수기 행에 **사실값만** — `document_id, source, created_by, approved_by, approval_date, business_process, gl_account, description_quality` 중 존재 컬럼. 버킷·점수밴드·우선순위 사유 **없음**.
  - `breakdown`: `flagged_rows`(=수기 행수), `manual_rows`, `adjustment_rows`(source=='adjustment'), `source_counts`.
- `review_score_series` attr는 제거(소비자가 참조하면 §3에서 함께 정리).

## 3. 다운스트림 소비자 정리 (필수 — rg로 전수)
아래 파일에서 L3-02의 폐기된 산출물(`manual_priority`/`manual_control_bypass`/`review_score_series`/bucket/priority_reason)을 참조하는 곳을 찾아 binary 계약에 맞게 정리:
`phase1_case_builder.py`, `fraud_layer.py`, `topic_scoring.py`, `rule_scoring.py`, `score_aggregator.py`(있으면), `rule_detail_metadata.py`, `explanations.py`, `phase1_rule_catalog.py`, `constants.py`
- 특히 "L3-02 confirmed hit는 priority/control_bypass만" 같은 **버킷 기반 게이팅 로직**을 "수기=flag" 단일 기준으로 교체.
- `review_rules` vs `flagged_rules` 이원화가 L3-02 버킷에 의존했다면 단순화(수기는 flag, 정황 가중은 통합점수).
- 통합점수체계(topic_scoring)가 L3-02를 어떻게 쓰는지 확인: L3-02는 **CONTEXT/조합 leg** 성격(수기 단독으로 큐 상단을 만들지 않음)이어야 한다. 단독 high floor를 만드는 코드가 있으면 제거.

## 4. 검증 게이트 (전부 출력 첨부)
- **G1 (폐기물 0)**: `rg -n "manual_priority|manual_control_bypass|review_score_series|priority_reason|bucket_counts" src/detection/` = **0건**(또는 잔존이 L3-02와 무관함을 증명). 실패조건: L3-02 관련 잔존.
- **G2 (binary 단일값)**: `b08_manual_override` 결과 `score_series`의 고유값이 `{0.0, 1.0}`뿐. 실패조건: 0.35/0.60/0.75 등장.
- **G3 (독립 toy, ripple — 3케이스)**: 직접 호출:
  - ① `is_manual_je=[True, False]` → flags `[True, False]`, scores `[1.0, 0.0]`
  - ② `source=['manual','auto']`(is_manual_je 컬럼 없음) → `[1.0, 0.0]`
  - ③ `source=['adjustment','system']` → `[1.0, 0.0]` + breakdown `adjustment_rows==1`
  - 출력 첨부. 실패조건: 기대값 불일치.
- **G4 (전체 스위트)**: `uv run pytest tests/modules/test_detection/ -q -k "not composite_sort_score_v126_truth_capture_thresholds"` → **신규 실패 0**. 폐기 버킷 테스트 삭제는 정당(테스트 가위질 금지 — 살아있는 다른 룰 테스트는 보존). baseline "1371 passed, 8 skipped" 기준 신규 fail/error 0.
- **G5 (회귀 가드)**: L3-02가 통합점수 조합에서 빠지지 않았는지 — 수기+승인우회 조합 case가 여전히 상위 tier로 묶이는지 1케이스 확인(통합점수체계가 가중하므로 룰 binary화 후에도 조합 결과는 유지돼야 함). 실패조건: 조합 case가 사라짐.

## 5. 보고 형식
```
STATUS: DONE
G1: rg 출력 … 0건
G2: score_series 고유값 {0.0, 1.0}
G3: toy ①[1.0,0.0] ②[1.0,0.0] ③[1.0,0.0]+adjustment_rows=1
G4: pytest … 신규 fail 0
G5: 조합 case 유지 확인 …
변경 파일/라인 요약 + 다운스트림 정리 내역
```
