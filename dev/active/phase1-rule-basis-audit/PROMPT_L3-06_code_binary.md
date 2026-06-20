# 코드 작업 프롬프트 — L3-06 (심야 전기) binary 전환 + source 로직 제거

## 0. 응답 규약
- **모든 보고·설명은 한국어로.**
- "STATUS: DONE/BLOCKED" + 단계별 증거(diff 요약·rg 출력·테스트 수치·toy 결과)를 그대로 붙여라. 출력 없는 PASS는 무효(hollow-PASS).

## 1. 배경 / 결정 (문서 SoT 이미 반영됨)
- `docs/spec/DETECTION_RULES.md` L3-06 카드: **심야(`is_after_hours`)이면 flag `1.0`, 아니면 `0`** 단일 binary. **source는 보지 않는다.**
- 구 2단 점수(`confirmed_after_hours=0.45` / `normal_system_context=0.20`) **폐기**, **`lone_automated_mask`·system_source/persona/actor 분기 전부 제거**.
- L3-06은 OFF-TIME context 태그(tier 게이트 미참여, severity 보조축). "자동/배치 심야는 정상"의 다운웨이트, 자동인 척 위장(`lone_automated`) 판별은 **전부 L3-02/source_trust + 통합점수체계 소관**으로 일원화. **룰은 심야 사실만 본다.**

## 2. 대상 함수
`src/detection/anomaly_rules_simple.py` → `c03_after_hours_entry()` (현재 약 :261~:350)

### 제거
- `source_norm`/`persona_norm`/`actor_norm` 산출 및 `system_source_tokens`, `lone_automated`(`lone_automated_mask` 호출), `system_source`, `system_persona`, `system_actor`, `normal_system_context`, `confirmed_after_hours` (현재 :275-301) — **전부 삭제**.
- `score_series` 밴드 `0.20`/`0.45` (현재 :303-305) — **삭제**.
- annotation의 `bucket`(normal_system_context/confirmed_after_hours)·`source_category`(system_or_batch/human_or_unknown)·밴드 `score` — **삭제**.
- breakdown의 `confirmed_after_hours_rows`/`normal_system_context_rows` — **삭제**.

### 재작성 (binary)
- `result = bool_column(df, "is_after_hours")`. 반환 = `result`.
- `score_series = result.astype(float)` (1.0 / 0.0).
- `row_annotations`: `source`, `created_by`, `posting_date`, `time_bucket`(midnight_00_05/late_evening_22_23 유지 가능) 등 사실값만. `score` 넣더라도 1.0 고정.
- `breakdown`: `flagged_rows`, `after_hours_rows`, `source_counts`, `time_bucket_counts`.

## 3. 다운스트림 / import 정리
- `c03` 내 `from ... import lone_automated_mask` 사용이 사라지면, 해당 import가 **다른 함수(c12 L4-05 등)에서도 쓰이는지** rg로 확인 후 c03 전용이면 정리(공유면 import 유지). `rg -n "lone_automated_mask" src/detection/anomaly_rules_simple.py`.
- `normal_system_context`/`confirmed_after_hours` 문자열을 소비하는 평가·리포트·case builder 정리.

## 4. 검증 게이트 (전부 출력 첨부)
- **G1 (밴드·source 분기 제거)**: `c03_after_hours_entry` 본문에 `0.20`/`0.45`/`lone_automated`/`normal_system_context`/`system_source` 0건. 실패조건: 잔존.
- **G2 (binary 고유값)**: c03 결과 `score_series` 고유값 `{0.0, 1.0}`뿐. 실패조건: 0.20/0.45 등장.
- **G3 (toy, ripple — source 무관 발화 2케이스)**: 직접 호출 —
  - ① `is_after_hours=[True, False]` → flags `[True, False]`, scores `[1.0, 0.0]`
  - ② **source가 자동/배치여도 심야면 발화**: `is_after_hours=[True,True]`, `source=['automated','manual']` → flags `[True, True]`, scores `[1.0, 1.0]`
  - 출력 첨부. 실패조건: 자동 source가 0/0.20으로 빠지면 FAIL(이번 변경 핵심 — 이전엔 자동이 0.20 감면받았음).
- **G4 (전체 스위트)**: `uv run pytest tests/modules/test_detection/ -q -k "not composite_sort_score_v126_truth_capture_thresholds"` → 신규 실패 0. 폐기 2단/위장게이트 테스트 갱신은 정당, 다른 룰 테스트 가위질 금지.
- **G5 (L1-05/L1-06 무변경)**: `_human_sod_mask`(L1-06)·b06 self-approval(L1-05)의 source/actor/lone_automated 제외가 그대로인지 rg 확인(이번 변경에 안 딸려갔는지).

## 5. 보고 형식
```
STATUS: DONE
G1: c03 밴드·source분기 0 (rg)
G2: 고유값 {0.0,1.0}
G3: ①[1.0,0.0] ②자동도[1.0,1.0]
G4: pytest 신규 fail 0
G5: L1-05/L1-06 무변경 확인
변경 파일/라인 + import/다운스트림 정리
```
