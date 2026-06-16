# 작업: L2-02 fallback 대량 거래처 억제 — case_builder 폭증 회귀 수정

> 한국어로 응답·보고할 것. 저장소: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist`, 브랜치 `develop`.
> grep 없으면 rg 대체 + 출력 원문 첨부.

## 1. 목표

- R2-A에서 추가한 L2-02 fallback이 **대량 거래처**(같은 거래처에 하루 수천 건 거래 — 자금이체·은행·
  배치성)에서 폭발적으로 매칭해 거대 case(단일 case 1.8만 hit)를 만들고, case_builder를 3,717초로
  폭증시킨 회귀를 수정한다. fallback이 일중/그룹 대량 거래처를 "정기·배치성"으로 간주해 억제하게 한다.
- 성공 기준: §6 검증 전부 통과 + "같은 (회사·거래처·금액버킷) 그룹이 임계 이상이면 fallback
  스킵"을 단언하는 테스트 존재 + truth(진짜 중복지급) 미손실.

## 2. 컨텍스트

- 읽어야 할 파일 (수정 전 반드시 읽을 것):
  - `src/detection/fraud_rules_groupby.py` — `b04_duplicate_payment()`:
    - R2-A 통합 fallback 루프(`amount_target.groupby(amount_cols)` 루프, `_fallback_reason` 헬퍼).
    - 기존 recurring 억제: `_l202_recurring_profile`(월 단위 3회+ 규칙적 시리즈 → suppress). 이것이
      **일중 대량은 못 막는다**(월 단위만 봄) — 이번 작업이 그 공백을 메운다.
    - `recurring_suppressed_doc_ids` 집합과 그 사용처.
  - `config/settings.py` — `AuditSettings`의 `duplicate_*` 설정들(recurring 억제 파라미터 위치).
    신규 임계도 여기에 추가.
  - `tests/modules/test_detection/test_fraud_rules_groupby.py` — TestL2_02 (b04 테스트 패턴).
- 배경 (모르면 잘못 판단할 사실):
  - 실측: 거래처 `V-000526`이 하루 4,700건 거래(총 26,276행). fallback이 이 거래처의
    동일 금액버킷을 서로 매칭해 case당 L2-02 hit 4,668건 생성 → 거대 case → case_builder 폭증.
    (`artifacts/phase1_priority_truth_v42j_r3` 측정 case build 3,717s vs r24 674s).
  - 도메인 의미: 하루 수천 건 거래하는 거래처는 자금이체·수금·배치 정산 등 **정기·대량 처리**라
    중복지급(이중지급)으로 보기 부적절하다. 진짜 이중지급은 소수 거래처의 소수 재지급이다.
    truth L2-02는 30건(소규모).
  - L2-02 fallback은 floor 미부착(R1-A)이라 band(우선순위)엔 영향 없다. 문제는 **case_builder
    부하**(hit 과다 생성). 억제는 "과탐 제거"이자 "성능 회복"이다.
  - reference_match(강한 신호) 경로는 건드리지 말 것 — 대량 억제는 fallback 경로에만.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

1. `AuditSettings`에 신규 설정 추가(기본값 명시, 하드코딩 금지):
   `duplicate_fallback_bulk_group_max: int = 50` (같은 (회사·거래처·금액버킷) 그룹의 문서 수가
   이 값 초과면 대량 거래처로 보고 fallback 스킵). 기본 50은 "하루 정상 재지급이 50건을 넘기
   어렵다"는 보수적 도메인 가정 — 실측 V-000526(수천)은 확실히 걸리고 truth 소규모는 안 걸림.
2. fallback 루프(`amount_target.groupby(amount_cols)`)에서 각 그룹 처리 시작 시:
   - 그룹 크기(문서 수)가 `duplicate_fallback_bulk_group_max` 초과면 그 그룹 전체를
     `bulk_suppressed`로 분류하고 fallback 매칭을 **스킵**(reference_match는 별도 루프라 영향 없음).
   - breakdown에 `bulk_suppressed_docs` 카운트 추가.
   - 이미 있는 `recurring_suppressed`와 별개 카운터.
3. reference_match 경로·near_extra·recurring 억제 기존 로직은 변경 금지.
- 설계가 현장과 안 맞으면(예: amount_cols 그룹이 금액버킷이 아니라 정확금액이라 대량 그룹이 안
  생김): 임의 변경하지 말고 STATUS: NEEDS_CONTEXT로 멈출 것 — 그룹 키 구조를 보고에 적고 멈춰라.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1: fallback 루프의 그룹 키(amount_cols) 구조 + 그룹 크기 분포 확인 → 산출물:
      "amount_cols = [...], V-000526류 대량 그룹이 이 키로 묶이는지" 메모
      증거: 관련 코드 인용 + `rg -n "amount_cols|groupby" src/detection/fraud_rules_groupby.py`
- [ ] Step 2 (TDD RED): 신규 테스트 — ① 같은 거래처·금액버킷 60문서(>50) → fallback 미발화 +
      `bulk_suppressed_docs` ≥ 1 ② 같은 거래처 5문서(소규모) → 기존대로 fallback 발화
      ③ reference_match는 대량 그룹에서도 발화(억제 대상 아님)
      증거: pytest FAILED 원문 (RED)
- [ ] Step 3 (GREEN): §3 구현 → passed 원문
- [ ] Step 4 (회귀): 기존 TestL2_02 전부 통과 + rule_scoring l202 테스트 불변
      증거: `uv run pytest tests/modules/test_detection/test_fraud_rules_groupby.py tests/modules/test_detection/test_rule_scoring.py -q` passed
- [ ] Step 5(항상 마지막): 전체 검증(§6)
※ 증거 없는 단계는 미수행 간주.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- 하드코딩: 임계 50을 함수에 리터럴로 박지 말 것 — `AuditSettings` 설정 경유.
- reference_match·near_extra·recurring 억제 기존 로직 변경 금지. rule_scoring/topic_scoring/config
  yaml 변경 금지(settings.py의 신규 설정 1개만).
- 테스트 약화 금지(skip/xfail/assert 완화).
- 범위 밖 수정 금지: 수정 가능 = `src/detection/fraud_rules_groupby.py`, `config/settings.py`,
  `tests/modules/test_detection/test_fraud_rules_groupby.py`.
- 체크리스트 생략·순서 변경 금지. 실패·미완 완료 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)

- `uv run pytest tests/modules/test_detection/test_fraud_rules_groupby.py tests/modules/test_detection/test_rule_scoring.py -q` → 전부 passed
- `uv run pytest tests/modules/test_detection/ -q` → 신규 실패 0 (사전 베이스라인 전/후 비교.
  `test_duplicate_performance.py`가 1.0~1.5s로 실패하면 3회 재실행 첨부, 3회 모두 1.5s 초과 시만 BLOCKED)
- `uv run ruff check src/detection/fraud_rules_groupby.py config/settings.py` → All checks passed
※ 하나라도 기대와 다르면 DONE 금지.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령 + 출력 원문)
변경 파일: <경로 목록>
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">

신뢰 규칙: 정직한 부분 실패 보고는 정상 경로다. 거짓 DONE은 재검증에서 드러나 전체 재수행이 된다.
