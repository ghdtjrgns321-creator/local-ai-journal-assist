# 작업: L2-02 중복지급 fallback 3종 구현 — 스펙 계약 이행 (이슈 #24)

> 한국어로 응답·보고할 것. 저장소: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist`, 브랜치 `develop`.
> grep이 없으면 rg로 대체 가능 (동일 범위 검색 + 출력 원문 첨부).

## 1. 목표

- 스펙(DETECTION_RULES.md L2-02)이 정의했지만 미구현 상태인 fallback 탐지 3종
  (`mixed_reference_fallback` / `amount_partner_fallback` / `blank_reference_fallback`)을
  `b04_duplicate_payment()`에 구현한다 — "reference 없는 일회성 거래처 이중지급"이 잡히게 된다.
- 성공 기준: §6 검증 전부 통과 + breakdown의 fallback 카운터 3종이 실제 발화를 세고(상시 0
  해제), 기존 `reference_match`/`near_extra` 경로의 기존 테스트가 전부 불변 통과.

## 2. 컨텍스트

- 읽어야 할 파일 (수정 전 반드시 읽을 것):
  - `docs/spec/DETECTION_RULES.md` 763-811행 — L2-02 계약 전문. **이 스펙이 정답이다.**
    탐지 순서 5-6항(fallback 정의·recurring 억제), 점수 기준(0.70/0.65/0.60), 해석 기준
    ("blank fallback은 exact match만"), 출력 방식(row_annotations·breakdown 키 목록)을 그대로 따른다.
  - `src/detection/fraud_rules_groupby.py` — `b04_duplicate_payment()`(999행~):
    전처리(1020-1060행: P2P/KZ 범위·partner key·`_base_amt`·`_reference`), reference_match 경로
    (1131행 부근), recurring profile(`_l202_recurring_profile`, 75행~)과 near_extra 경로
    (1168-1235행), reason_counts/breakdown(1252-1280행 — fallback 카운터 키가 이미 있고 상시 0).
  - `src/detection/rule_scoring.py` 115-120행 — `L202_DUPLICATE_PAYMENT_SIGNAL_STRENGTH`에
    fallback 3종의 신호 강도(0.70/0.65/0.60)가 **이미 등록**돼 있다. 점수 사전 신설 금지.
  - `tests/modules/test_detection/` 에서 b04 기존 테스트 파일 (grep으로 찾을 것) — 기존 패턴 준수.
- 배경 (모르면 잘못 판단할 사실):
  - 현재 구현은 reason_code가 `reference_match`와 `near_extra` 둘뿐이다. near_extra는 정기 시리즈
    중 off-cycle 추가 지급 탐지로 **스펙 외 구현 자산** — 건드리지 말 것. 신규 fallback은
    near_extra가 못 보는 "비정기 거래처" 영역을 채운다.
  - floor 정책: 직전 라운드에서 L2-02 floor는 `reference_match` label에만 붙도록 게이트됐다
    (`rule_scoring.py` registry `floor_eligible_labels=frozenset({"reference_match"})`).
    **fallback은 floor를 만들지 않는 게 스펙이고, registry 게이트가 이미 보장한다 — registry를
    수정하지 말 것.**
  - 이 룰은 review queue 후보 생성이다. fallback은 "중복 확정"이 아니라 "검토 후보"이며
    confidence가 그 등급을 표현한다.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

reference_match에 안 잡힌 문서들에 대해, 같은 (company_code, `_partner_key`) 안에서
`document_id`가 다른 문서쌍 중 **day_gap ≤ 45일**인 쌍을 평가한다 (문서 단위 — 기존 doc 요약
구조 재사용):

| reason_code | 조건 (reference 상태) | 금액 조건 | confidence |
|-------------|----------------------|-----------|------------|
| `mixed_reference_fallback` | 선행 문서 reference 있음 ∧ 후행 문서 reference 공백 | `min(금액의 2%, 100,000원)` 허용오차 (최소 1원) | 0.70 |
| `amount_partner_fallback` | 두 문서 reference가 서로 다름 (둘 다 있거나 일부만) | 동일 허용오차 | 0.65 |
| `blank_reference_fallback` | 두 문서 모두 reference 공백 | **정확히 같은 금액만** (허용오차 없음 — 스펙 5항) | 0.60 |

공통 규칙:
1. **recurring 억제 (스펙 6항)**: 같은 거래처·같은 금액이 월 단위 규칙으로 3회 이상 반복되는
   시리즈는 fallback 후보에서 제외하고 `recurring_suppressed`로 센다. 기존
   `_l202_recurring_profile` 헬퍼를 재사용한다 (새 판정 로직 발명 금지).
2. 플래그는 **후행 문서**에 단다 (기존 reference_match 경로와 동일). `row_annotations`에
   `reason_code`, `confidence`, `confidence_band`, `matched_document_id`, `partner_key`,
   `reference_norm`, `amount`, `matched_amount`, `day_gap` 기록 (스펙 출력 방식 — 기존 annotation
   dict 구조 재사용).
3. 한 문서가 여러 경로에 걸리면 **우선순위 높은 reason 하나만** 부여:
   reference_match > mixed > amount_partner > blank (스펙 점수 흐름의 순서).
4. `score_series`는 confidence를 그대로 쓴다 (기존 경로와 동일 방식). display_label=reason_code로
   흘러가면 `L202_DUPLICATE_PAYMENT_SIGNAL_STRENGTH`가 자동 적용된다 — 별도 점수 매핑 금지.
5. breakdown: 기존 키(`mixed_reference_fallback_docs` 등 3종 + `recurring_suppressed_docs`)에
   실측 카운트를 채운다. 새 키 발명 금지.
6. **성능**: 전 문서쌍 O(n²) 전조합 금지. (company, partner) 그룹 내에서 날짜 정렬 후
   45일 슬라이딩 윈도우로만 비교하고, blank/exact 경로는 (company, partner, 금액) 동치 그룹으로
   먼저 좁힌다. 기존 b04 루프 구조(파트너 그룹 단위)를 따른다.
- 설계가 현장과 안 맞으면(예: doc 요약 구조가 reference 상태를 보존하지 않음, recurring profile이
  fallback 경로에서 재사용 불가): 임의 변경하지 말고 STATUS: NEEDS_CONTEXT로 멈출 것.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1: b04 현재 구조 정독 + fallback 카운터가 상시 0임을 확인
      증거: `rg -n "mixed_reference_fallback|blank_reference_fallback|amount_partner_fallback" src/detection/fraud_rules_groupby.py`
      출력 원문 (set하는 곳이 없음을 보인다)
- [ ] Step 2 (TDD RED): 신규 테스트 작성 — 최소 7케이스:
      ① 무reference 동일금액 30일 간격 2건 → 후행 문서 `blank_reference_fallback` 발화, confidence 0.60
      ② 선행 ref 있음+후행 공백, 금액 1.5% 차이 → `mixed_reference_fallback` 0.70
      ③ 서로 다른 ref 2건, 유사 금액 → `amount_partner_fallback` 0.65
      ④ blank 경로에서 금액 1% 차이 → **미발화** (exact only)
      ⑤ 46일 간격 → 미발화
      ⑥ 월 정기 3회+ 동일금액 시리즈 → 미발화 + `recurring_suppressed_docs` ≥ 1
      ⑦ breakdown 카운터가 ①~③ 발화 수와 일치
      증거: pytest 실행에서 신규 테스트 FAILED 원문 (RED)
- [ ] Step 3 (GREEN): §3 구현 → 같은 명령 전부 passed 원문
- [ ] Step 4 (회귀): 기존 reference_match·near_extra 테스트 불변 통과 + L2-02 floor 게이트 테스트
      (test_rule_scoring.py의 l202 테스트) 불변 통과
      증거: `uv run pytest tests/modules/test_detection/test_rule_scoring.py -q` 전부 passed 원문
- [ ] Step 5(항상 마지막): 전체 검증(§6) 실행 후 출력 원문 확보
※ 각 단계의 증거는 완료 보고에 원문 그대로 포함한다. 증거가 없는 단계는 미수행으로 간주한다.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- 하드코딩: 45일 윈도우·2%/10만원 허용오차를 함수 본문 매직넘버로 중복 정의하지 말 것 — 기존
  reference_match 경로가 쓰는 상수/설정(`AuditSettings` 또는 모듈 상수)을 재사용하거나, 없으면
  모듈 상단 명명 상수로 1회 정의. confidence 값(0.70/0.65/0.60)을 b04 안에 점수 사전으로 재정의
  금지 — annotation confidence와 `L202_DUPLICATE_PAYMENT_SIGNAL_STRENGTH`가 SoT.
- `near_extra`·`reference_match` 기존 경로 로직 변경 금지. `rule_scoring.py` registry 변경 금지.
- 테스트 약화 금지: skip/xfail 추가, assert 삭제·완화, 기대값을 출력에 맞춰 수정.
- 범위 밖 수정 금지: 수정 가능 파일 = `src/detection/fraud_rules_groupby.py`,
  `tests/modules/test_detection/` 하위 b04 테스트 파일. 이외(특히 rule_scoring.py,
  topic_scoring.py, config, docs) 변경 금지.
- 체크리스트 항목 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)

- b04 테스트 파일 + `tests/modules/test_detection/test_rule_scoring.py` → 전부 passed
- `uv run pytest tests/modules/test_detection/ -q` → 신규 실패 0 (사전 베이스라인 전/후 failed
  목록 비교 원문. 참고: `test_duplicate_performance.py`의 100k 1초 임계는 환경 부하에 민감한
  것으로 확인된 상태 — **이 perf 테스트가 1.0~1.5s 사이로 실패하면 3회 재실행 결과를 첨부**하고,
  3회 모두 1.5s를 넘으면 fallback 구현의 성능 회귀이므로 BLOCKED로 보고)
- `uv run ruff check src/detection/fraud_rules_groupby.py` → All checks passed
※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED로 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 각 항목의 증거(명령 + 출력 원문 붙여넣기)
변경 파일: <경로 목록 — 변경하지 않은 파일을 포함하지 말 것>
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">

신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로이며 다음 지시로
이어진다. 거짓 DONE은 재검증에서 반드시 드러나고 작업 전체를 처음부터 재수행하게 된다.
