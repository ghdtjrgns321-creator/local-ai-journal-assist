# 코드 작업 프롬프트 — 자동 source 내재제외 제거 (L2-01·L2-05)

> 범위: **L2-01·L2-05만**. L3-05/L3-06은 별도 binary 전환 프롬프트(`PROMPT_L3-05_code_binary.md`/`PROMPT_L3-06_code_binary.md`)에서 처리한다.

## 0. 응답 규약
- **모든 보고·설명은 한국어로.**
- "STATUS: DONE/BLOCKED" + 단계별 증거(diff 요약·rg 출력·테스트 수치·toy 결과)를 그대로 붙여라. 출력 없는 PASS는 무효(hollow-PASS).

## 1. 배경 / 결정 (문서 SoT 이미 반영됨)
- **원칙**: 전표가 "자동/배치냐 사람 수기냐"의 판단은 **L3-02(수기 전용 룰) + `source_trust` + 통합점수체계**가 하는 단일 차원이다. 개별 룰이 자기 안에서 자동 source를 제외하면 = 다른 룰(L3-02)의 차원을 끌어들이는 중복이자 "룰이 정황을 가로채는" 안티패턴(L2-04/L3-01에서 제거한 것과 동일).
- **변경**: L2-01·L2-05에서 **자동/배치 source 제외 로직 제거**. 자동 전표도 신호 충족 시 **flag 1.0으로 발화**. "자동이라 정상" 다운웨이트는 통합점수가 `신호 + L3-02 수기 leg`로 한 번만 처리한다.
- **유지(건드리지 말 것)**: L1-05(자기승인)·L1-06(직무분리)의 시스템 actor/source 제외는 "통제위반이 사람을 전제"하는 위반 정의라 intrinsic. L4-05(c12)는 별도(이번 범위 아님).

## 2. 대상별 변경

### (1) L2-01 — `src/detection/fraud_rules_feature.py` `b02_near_threshold` + 헬퍼
- `_score_l201_near_threshold`(약 :124~)의 `routine_source = source.isin({"automated","recurring","batch","interface","system"})` 및 그로 인한 **score 0(제외) 분기 제거**. 한도 직하면 source 무관 flag 1.0.
- `_l201_queue_label`(약 :151~)에서 source 기반 라벨 분기 제거(있으면).
- breakdown의 `excluded_auto_source_rows`(또는 유사) 키 제거.
- **유지**: 한도 조회 실패 행은 hit 아님(데이터 품질, 그대로).

### (2) L2-05 — `src/detection/anomaly_rules_reversal.py` `_s1_one_to_one_match`
- `& ~work["source_norm"].isin(_AUTOMATED_SOURCES)` (현재 :172) **제거**. 자동 source 역분개도 거울 쌍이면 발화.
- `_AUTOMATED_SOURCES` 상수(:23)가 다른 곳에서 안 쓰이면 제거(S0 ERP 경로는 무관).
- **유지(intrinsic)**: 같은 `gl_account`·반대 방향·다른 `document_id` 조건은 역분개 정의라 그대로.

## 3. 검증 게이트 (전부 출력 첨부)
- **G1 (자동제외 제거)**:
  - `rg -n "isin(_AUTOMATED_SOURCES)" src/detection/anomaly_rules_reversal.py` = 0
  - `_score_l201_near_threshold` 본문에 `routine_source|isin.*automated` = 0
- **G2 (binary 고유값)**: b02·c11 결과 `score_series` 고유값 `{0.0, 1.0}`뿐.
- **G3 (toy, ripple — 자동도 발화 2케이스)**:
  - L2-01: 자동 source 한도 직하 전표 → flag `1.0` (이전엔 0 제외)
  - L2-05: 자동 source 같은계정 거울 쌍 → flags `[1.0, 1.0]` (이전엔 제외)
  - 출력 첨부. 실패조건: 자동 source가 0으로 빠지면 FAIL(이번 변경 핵심).
- **G4 (전체 스위트)**: `uv run pytest tests/modules/test_detection/ -q -k "not composite_sort_score_v126_truth_capture_thresholds"` → 신규 실패 0. 폐기 자동제외 테스트 갱신은 정당, 다른 룰 테스트 가위질 금지.
- **G5 (L1-05/L1-06·L4-05 무변경)**: `_human_sod_mask`·b06·c12의 source 제외가 그대로인지 rg 확인.

## 4. 보고 형식
```
STATUS: DONE
G1: L2-01 routine_source 0 / L2-05 _AUTOMATED_SOURCES isin 0 (rg)
G2: 고유값 {0.0,1.0} ×2
G3: L2-01 자동 1.0 / L2-05 자동 [1.0,1.0]
G4: pytest 신규 fail 0
G5: L1-05/L1-06/L4-05 무변경 확인
변경 파일/라인 요약
```
