# 작업: source 신뢰 비대칭 해소 — detector 4곳에 위장 게이트 연결 (이슈 #18)

> 한국어로 응답·보고할 것. 저장소: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist`, 브랜치 `develop`.

## 1. 목표

- 전표 source를 "자동"으로 위조하면 점수 감면/모집단 제외를 받는 비대칭을 해소한다:
  detector 4곳의 **source 기반** 감면·제외 판정에서 위장 의심 행(`lone_automated_mask`)을 빼,
  위장 전표가 감면을 못 받게 한다.
- 성공 기준: §6 검증 전부 통과 + 4곳 각각 "위장 행은 감면 안 받음 / 무리 자동 행은 기존 감면
  유지 / batch_id·job_id 컬럼 부재 시 기존 동작 불변"을 단언하는 테스트 존재.

## 2. 컨텍스트

- 읽어야 할 파일 (수정 전 반드시 읽을 것):
  - `src/detection/source_trust.py` 전체 — `lone_automated_mask(df, *, lone_threshold=10, source_tokens=None)`:
    "자동 source ∧ batch_id/job_id 결측 ∧ 같은 날 동류 ≤10건" 행을 True로 반환. 필요한 컬럼
    (source/batch_id·job_id/posting_date)이 없으면 **전부 False**를 반환한다(graceful no-op).
  - 수정 대상 4곳:
    1. `src/detection/anomaly_rules_simple.py` `c03_after_hours_entry`(약 523-560행) — L3-06 심야:
       source가 시스템 계열이면 `normal_system_context`로 점수 0.45→0.20 감면 + confirmed 제외
    2. `src/detection/fraud_rules_access.py` L1-05 자기승인(약 1295-1311행) — `user_persona == 'automated_system'`
       또는 source 자동 계열이면 allowed_system으로 score 0 + 전 queue 제외
    3. `src/detection/anomaly_rules_simple.py` `_manual_user_mask`(약 1485-1509행) — L4-05:
       source/persona/created_by가 시스템 계열이면 행동통계·급속승인 모집단에서 제외
    4. `src/detection/fraud_rules_feature.py` L1-04(약 228-232행) — candidate인데 source가
       자동 계열이면 버킷 불문 review 0.40 강등
  - 기존 사용 예: `src/detection/anomaly_rules_batch.py`(L4-06)가 `lone_automated_mask(df, source_tokens={...})`를
    자체 토큰으로 호출하고 `.reindex(df.index, fill_value=False)`로 방어하는 패턴(63-66행)
  - 테스트 패턴: `tests/modules/test_detection/test_source_trust.py`(위장/무리/컬럼부재 픽스처),
    `test_anomaly_rules_batch.py`의 lone 테스트 2개
- 배경 (모르면 잘못 판단할 사실):
  - `lone_automated_mask`의 source 판정은 lower-strip 후 토큰 집합과 **완전 일치**다. 각 수정
    지점이 쓰는 source 집합이 서로 다르므로(예: L3-06은 {automated,batch,interface,system}),
    **그 지점의 토큰 집합을 lower-strip해서 `source_tokens=`로 전달**해야 판정 모집단이 일치한다.
  - persona(`user_persona`)·created_by 기반 제외 경로는 이 작업의 범위가 아니다 — **source 기반
    분기만** 게이트한다. persona 위조 대응은 별도 이슈로 관리 중.
  - 도메인 논리: 정상 자동 전표는 무리지어 다닌다(v41 실측: 자동 202,102 문서 중 단독 82건).
    단독 자동(=위장 의심)은 신뢰하지 않으므로 감면·제외 자격이 없다. 이 게이트는 이미 fraud-combo
    floor(`phase1_case_builder._fraud_combo_rule_scope`)와 L4-06에 적용돼 있고, 이번 작업은 그
    논리를 detector 내부 감면 경로로 확장하는 것이다.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

각 지점에서 공통 패턴:

```python
from src.detection.source_trust import lone_automated_mask
# 해당 지점이 source 비교에 쓰는 토큰 집합을 그대로 전달 (lower-strip 일치)
lone = lone_automated_mask(df, source_tokens=<그 지점의 source 토큰 집합>).reindex(
    df.index, fill_value=False
)
# source 기반 시스템 분류 마스크에서 위장 의심 행을 제외
system_source_mask = system_source_mask & ~lone
```

지점별 적용 위치:
1. **L3-06**: `normal_system_context` 분류 중 source-leg 마스크에 `& ~lone`. 결과적으로 위장 행은
   confirmed(0.45) 모집단에 남는다. persona/actor-leg는 그대로.
2. **L1-05**: allowed_system 판정의 source-leg(`source == 'automated'` 계열)에 `& ~lone`.
   persona-leg(`user_persona == 'automated_system'`)는 그대로.
3. **L4-05**: `_manual_user_mask`가 제외하는 source-leg에 `& ~lone` (위장 행은 manual로 취급되어
   행동통계에 포함). persona/created_by-leg는 그대로. 이 함수가 df가 아닌 부분 시리즈를 받는
   구조면 호출부에서 lone을 계산해 전달한다 — 시그니처 변경이 필요하면 최소로.
4. **L1-04**: review 강등 마스크(source 자동 계열)에 `& ~lone` (위장 행은 원래 버킷 유지 →
   critical 위장 시 immediate 경로 복원).

- 함수 내부에서 df 전체에 1회만 lone을 계산하고 재사용한다 (행별 호출 금지 — 성능).
- 설계가 현장과 안 맞으면(예: 해당 지점에 df 접근 불가, source-leg가 분리 불가능하게 얽힘):
  임의 변경하지 말고 STATUS: NEEDS_CONTEXT로 멈출 것.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1: 4개 지점의 현재 코드 정독 + 각 지점의 source 토큰 집합을 보고서에 기록
      증거: 지점별 "파일:라인 → 토큰 집합" 4줄 목록
- [ ] Step 2 (TDD RED): 지점별 신규 테스트 작성 — 각 지점에 최소 3케이스:
      ① 위장 행(source 자동 + batch_id/job_id 결측 + 같은 날 동류 1건) → 감면/제외/강등 **안 됨**
      (점수 또는 모집단 멤버십 단언) ② 무리 자동 행(같은 날 동류 ≥11건 또는 batch_id 있음) →
      기존 감면/제외 유지 ③ batch_id·job_id 컬럼 부재 → 기존 동작과 완전 동일
      증거: 해당 테스트 파일 pytest 실행에서 신규 테스트들 FAILED 원문 (RED)
- [ ] Step 3 (GREEN): §3 구현 → 같은 명령 전부 passed 원문
- [ ] Step 4 (ripple): source 기반 감면·제외가 남아있는 다른 detector가 있는지 전수 스캔 →
      산출물: 스캔 결과 목록 (수정하지 말고 목록만 — 설계자가 후속 라운드 판단)
      증거: `grep -rn "automated\|interface\|recurring" src/detection/*.py | grep -v pycache | grep -iv "test"` 중
      source 비교 분기 목록과 "이번 4곳 외 잔여" 판정 표
- [ ] Step 5(항상 마지막): 전체 검증(§6) 실행 후 출력 원문 확보
※ 각 단계의 증거는 완료 보고에 원문 그대로 포함한다. 증거가 없는 단계는 미수행으로 간주한다.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- 하드코딩: lone 임계(10)를 지점에 리터럴로 박지 말 것 — `lone_automated_mask` 기본값/파라미터
  사용. source 토큰을 새로 발명하지 말 것 — 그 지점이 이미 쓰는 집합을 전달.
- persona·created_by 기반 분기 수정 금지 (범위 밖).
- `source_trust.py` 자체 수정 금지 (소비만).
- 테스트 약화 금지: 기존 테스트 skip/xfail/assert 완화. 기존 테스트가 "자동이면 무조건 감면"을
  단언해 깨지면 신규 스펙(위장 제외)을 단언하도록 수정하고 내역 보고.
- 범위 밖 수정 금지: 수정 가능 파일 = `src/detection/anomaly_rules_simple.py`,
  `src/detection/fraud_rules_access.py`, `src/detection/fraud_rules_feature.py`,
  `tests/modules/test_detection/` 하위 해당 테스트 파일. 이외 변경 금지.
- 체크리스트 항목 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)

- `uv run pytest tests/modules/test_detection/test_anomaly_rules_simple.py tests/modules/test_detection/test_fraud_rules_access.py tests/modules/test_detection/test_fraud_rules_feature.py -q`
  → 기대: 전부 passed (해당 테스트 파일명이 다르면 실제 파일명으로 — 사전 베이스라인 떠서 전/후 비교)
- `uv run pytest tests/modules/test_detection/ -q` → 기대: 신규 실패 0 (전/후 failed 목록 비교 원문)
- `uv run ruff check src/detection/anomaly_rules_simple.py src/detection/fraud_rules_access.py src/detection/fraud_rules_feature.py`
  → 기대: All checks passed
※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED로 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 각 항목의 증거(명령 + 출력 원문 붙여넣기)
변경 파일: <경로 목록 — 변경하지 않은 파일을 포함하지 말 것>
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">

신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로이며 다음 지시로
이어진다. 거짓 DONE은 재검증에서 반드시 드러나고 작업 전체를 처음부터 재수행하게 된다.
