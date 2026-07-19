# 작업: repeat_score 무조건 medium 승급 제거 (이슈 #22)

> 한국어로 응답·보고할 것. 저장소: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist`, 브랜치 `develop`.

## 1. 목표

- priority 점수와 무관하게 `repeat_score ≥ 0.70`이면 케이스를 medium band로 승급시키는 분기를
  제거한다. 반복 신호는 topic 점수의 repeat 가중(이미 존재)으로만 기여하게 한다.
- 성공 기준: §6 검증 전부 통과 + "priority_score 0.5 + repeat_score 0.9 → band 'low'"를 단언하는
  테스트가 존재 + `repeat_score_promote` 참조가 코드·설정에서 0건.

## 2. 컨텍스트

- 읽어야 할 파일 (수정 전 반드시 읽을 것):
  - `src/detection/phase1_case_builder.py` — `_priority_band`(5642-5653행): 마지막 분기
    `if repeat_score >= promote_cutoff: return "medium"`이 제거 대상. 호출부 전수 확인 필요.
  - `config/phase1_case.yaml` 387행 — `repeat_score_promote: 0.70` (제거 대상)
  - `docs/spec/DETECTION_PARAMETERS.md` 94행 — 파라미터 표에서 `repeat_score_promote` 언급 (갱신 대상)
  - `tests/` 에서 `_priority_band`·`repeat_score_promote`를 참조하는 테스트 (grep으로 찾을 것)
- 배경 (모르면 잘못 판단할 사실):
  - 이 분기는 정상 월 반복 전표(임차료·경영수수료·관계사 수수료)를 점수 무관 medium으로 올려
    review queue 잡음을 만든다 (r24에서 IC01/02/03 122케이스 전건 medium의 유력 원인). 제거가
    사용자 승인된 결정이다.
  - 반복 신호 자체는 버리는 게 아니다 — topic 점수 합성에 repeat 가중이 이미 들어 있고(`topic_scoring.py`
    TOPIC_SCORE_WEIGHTS의 repeat 축), tie-break(`repeat_months_tiebreak`)도 별도로 존재한다.
    **이번 제거 대상은 band 직접 승급 분기 하나뿐이다.** tie-break·가중은 건드리지 않는다.
  - `_priority_band`의 `repeat_score` 파라미터가 제거 후 미사용이 되면 파라미터도 제거하고
    호출부를 갱신한다 (죽은 파라미터를 남기지 않는다).

## 3. 설계 (이대로 구현 — 임의 변경 금지)

1. `_priority_band`에서 repeat 승급 분기와 `promote_cutoff` 산출 줄을 제거:
   ```python
   def _priority_band(priority_score: float, config: dict[str, Any]) -> str:
       bands = config.get("priority_band", {})
       high = float(bands.get("high", 0.90))
       medium = float(bands.get("medium", 0.75))
       if priority_score >= high:
           return "high"
       if priority_score >= medium:
           return "medium"
       return "low"
   ```
2. 호출부에서 `repeat_score` 인자 제거 (grep `_priority_band(`으로 전수 확인 후 일괄 갱신).
3. `config/phase1_case.yaml`에서 `repeat_score_promote` 키 제거.
4. `docs/spec/DETECTION_PARAMETERS.md` 94행의 파라미터 표에서 `repeat_score_promote`만 제거
   (`rule_repeat_scale`·`repeat_months_tiebreak`·`evidence_type_cap`은 유지 — 이들은 살아있는 설정).
- 설계가 현장과 안 맞으면(예: repeat_score가 band 외 다른 곳에서도 이 분기를 전제, 호출부가
  동적이라 시그니처 변경이 위험): 임의 변경하지 말고 STATUS: NEEDS_CONTEXT로 멈출 것.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1: 호출부·참조 전수 확인 → 산출물: grep 결과 원문
      증거: `grep -rn "_priority_band(\|repeat_score_promote" src tests config docs --include="*.py" --include="*.yaml" --include="*.md"` 출력 원문
- [ ] Step 2 (TDD RED): 신규 테스트 — `_priority_band(0.5, config)`처럼 medium 미만 점수 +
      (구현 전 기준으로) repeat 0.9 상황에서 band가 "low"임을 단언. 기존 시그니처 기준으로
      작성하면 FAILED여야 한다
      증거: 해당 테스트 FAILED 원문 (RED)
- [ ] Step 3 (GREEN): §3 구현 → 같은 테스트 passed 원문
- [ ] Step 4 (ripple): 참조 잔존 0 확인
      증거: `grep -rn "repeat_score_promote" src tests config --include="*.py" --include="*.yaml"` 출력 0건 +
      `grep -rn "_priority_band(" src tests --include="*.py" | grep -v pycache` 전 호출부가 신규 시그니처
- [ ] Step 5(항상 마지막): 전체 검증(§6) 실행 후 출력 원문 확보
※ 각 단계의 증거는 완료 보고에 원문 그대로 포함한다. 증거가 없는 단계는 미수행으로 간주한다.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- 하드코딩: band 임계(0.90/0.75)를 함수에 추가 리터럴로 박지 말 것 — config 조회 구조 유지
  (기본값 인자는 기존 그대로 허용).
- 범위 확대 금지: `repeat_months_tiebreak`, `rule_repeat_scale`, topic repeat 가중,
  `repeat_score` **계산** 로직은 건드리지 말 것. 제거 대상은 band 승급 분기와 그 설정 키뿐.
- 테스트 약화 금지: 기존 테스트가 repeat 승급 동작을 단언해 깨지면 신규 스펙(승급 없음)을
  단언하도록 수정하고 내역 보고. assert 삭제로 때우지 말 것.
- 범위 밖 수정 금지: 수정 가능 파일 = `src/detection/phase1_case_builder.py`,
  `config/phase1_case.yaml`, `docs/spec/DETECTION_PARAMETERS.md`,
  `tests/` 하위 해당 테스트 파일. 이외 변경 금지.
- 체크리스트 항목 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)

- `uv run pytest tests/modules/test_detection/test_phase1_case_builder.py -q` → 기대: 전부 passed
  (파일명이 다르면 Step 1에서 확인한 실제 테스트 파일로 — 사전 베이스라인 전/후 비교)
- `uv run pytest tests/modules/test_detection/ tests/phase1_rulebase/ -q --ignore=tests/phase1_rulebase/nightly_kpi_guard.py`
  → 기대: 신규 실패 0 (전/후 failed 목록 비교 원문. nightly_kpi_guard는 측정 산출물 의존이라
  설계자가 라운드 마감 시 재측정과 함께 돌린다 — 이 작업에서 실행 불필요)
- `uv run python -c "from config.settings import get_phase1_case; print('repeat_score_promote' in str(get_phase1_case()))"`
  → 기대: False (config에 키 잔존 없음 확인)
- `uv run ruff check src/detection/phase1_case_builder.py` → 기대: All checks passed
※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED로 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 각 항목의 증거(명령 + 출력 원문 붙여넣기)
변경 파일: <경로 목록 — 변경하지 않은 파일을 포함하지 말 것>
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">

신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로이며 다음 지시로
이어진다. 거짓 DONE은 재검증에서 반드시 드러나고 작업 전체를 처음부터 재수행하게 된다.
