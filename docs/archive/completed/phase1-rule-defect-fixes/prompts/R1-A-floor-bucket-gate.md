# 작업: PHASE1 floor 정책 버킷 게이트 — L1-04·L2-02 스펙 정합 (이슈 #17) [v2 재발행]

> 한국어로 응답·보고할 것. 저장소: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist`, 브랜치 `develop`.
> **v2 변경(NEEDS_CONTEXT 해소)**: `duplicate_outflow_high`는 `config/phase1_case.yaml:47`의
> `topic_floors` 오버라이드에도 존재한다 (`phase1_case_builder._topic_floor_policies`가 로드해
> `apply_topic_floors(floor_policies=...)`로 전달). **config의 해당 키도 함께
> `duplicate_reference_match: 0.45`로 교체하는 것이 허용·필수다.** 수정 가능 파일 목록에
> `config/phase1_case.yaml`이 추가되었다 (§5). v1에서 멈춘 판단은 옳았다.

## 1. 목표

- topic floor가 발화 세기(버킷) 불문 적용되는 결함을 고친다: floor 자격을 **버킷(display_label)
  단위**로 게이트하고, L1-04는 `critical`/`non_approver`만, L2-02는 `reference_match`만(0.45)
  floor를 받게 한다.
- 성공 기준: §6의 검증 명령이 전부 기대대로 통과하고, L1-04 `boundary` 발화 단독 케이스의
  topic 점수가 0.75 미만임을 단언하는 테스트가 존재한다.

## 2. 컨텍스트

- 읽어야 할 파일 (수정 전 반드시 읽을 것):
  - `src/detection/rule_scoring.py` — `RuleScoringMetadata`(123행~), `L104_BUCKET_SIGNAL_STRENGTH`(64행),
    `L202_DUPLICATE_PAYMENT_SIGNAL_STRENGTH`(115행), L1-04 registry(186-193행, `floor_policy_ids=("approval_control_high",)`),
    L2-02 registry(245행 부근, `floor_policy_ids=("duplicate_outflow_high",)`), `normalize_rule_evidence`(556-606행)
  - `src/detection/topic_scoring.py` — `DEFAULT_TOPIC_FLOORS`(23-41행), `apply_topic_floors`(225-255행)
  - `docs/spec/DETECTION_RULES.md` 455-464행(L1-04 버킷 계약), 795-801행(L2-02 floor 계약)
  - `tests/modules/test_detection/test_rule_scoring.py` — 기존 floor/게이트 테스트 패턴
    (특히 fraud_combo_rule_scope 게이트 테스트가 점수 단언을 포함하는 방식)
- 따라야 할 기존 패턴: registry 필드 추가는 `RuleScoringMetadata` dataclass 필드 +
  `normalize_rule_evidence`에서 소비하는 기존 구조를 따른다.
- 배경 (모르면 잘못 판단할 사실):
  - 스펙은 "L1-04는 critical/non_approver만 단독 High floor 대상, severe도 단독 floor 미적용"
    (DETECTION_RULES.md:464), "L2-02는 reference_match만 floor 0.45, fallback 계열은 단독 floor
    없음"(:799-800)으로 정의돼 있다. 구현이 스펙과 어긋난 상태다 — **스펙이 정답이다.**
  - floor 부착 지점은 `normalize_rule_evidence`(rule_scoring.py:603) **단일 초크포인트**다.
    `phase1_case_builder.py:1360`은 normalized 결과를 복사할 뿐이므로 여기만 게이트하면 전 경로에
    반영된다. 단, 이 사실을 grep으로 재확인할 것 (§4 Step 1).
  - L1-04의 display_label은 버킷명("boundary"/"moderate"/"severe"/"critical"/"non_approver"),
    L2-02의 display_label은 reason("reference_match"/"near_extra")이다 — `_rule_specific_signal_strength`
    (rule_scoring.py:616-621)가 label을 lower-strip해서 사전 조회하는 것과 동일한 정규화를 쓴다.
  - 과거 사고: 같은 계열 수정(fraud-combo 게이트)에서 점수 인상 경로와 기록 경로 중 한쪽만
    게이트해 효과가 0이었던 버그가 있었다. 부착/적용 지점 전수를 grep으로 확인하라.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

1. `RuleScoringMetadata`에 필드 추가:
   `floor_eligible_labels: frozenset[str] | None = None`
   (None = 모든 label에 floor 허용 — 기존 룰 동작 보존. frozenset = 해당 label만 허용.)
2. `normalize_rule_evidence`에서 floor 부착을 게이트:
   ```python
   label_key = str(display_label or "").strip().lower()
   eligible = (
       metadata.floor_eligible_labels is None
       or label_key in metadata.floor_eligible_labels
   )
   # NormalizedRuleEvidence 생성 시:
   floor_policy_ids=metadata.floor_policy_ids if eligible else (),
   ```
3. registry 변경:
   - L1-04: `floor_eligible_labels=frozenset({"critical", "non_approver"})` (floor_policy_ids는 유지)
   - L2-02: `floor_policy_ids=("duplicate_reference_match",)`,
     `floor_eligible_labels=frozenset({"reference_match"})`
4. `duplicate_outflow_high` → `duplicate_reference_match: 0.45` 교체를 **두 곳 동시에**:
   - `DEFAULT_TOPIC_FLOORS`(topic_scoring.py:25)
   - `config/phase1_case.yaml:47` (`topic_scoring.topic_floors` 오버라이드 — 코드 기본값과
     yaml 오버라이드가 어긋나면 yaml이 이겨서 게이트가 무효화된다)
   사용처가 이 두 곳 + rule_scoring registry 외에 더 나오면 STATUS: NEEDS_CONTEXT로 멈출 것.
5. `apply_topic_floors` 자체는 수정하지 않는다 (게이트는 부착 단계에서 끝난다).
- 설계가 현장과 안 맞으면(예: 초크포인트가 단일이 아님, label에 버킷이 안 들어옴): 구현을
  임의 변경하지 말고 즉시 멈추고 STATUS: NEEDS_CONTEXT로 보고할 것. 멈추는 것은 실패가 아니다.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1: 부착·적용 지점 전수 확인 → 산출물: grep 결과 원문
      증거: `grep -rn "floor_policy_ids" src/detection/ --include="*.py" | grep -v pycache` 출력에서
      부착 지점이 rule_scoring.py(정의·복사)와 phase1_case_builder.py(복사)뿐임을 확인한 원문
- [ ] Step 2 (TDD RED): 실패하는 테스트 먼저 작성 → 산출물: `tests/modules/test_detection/test_rule_scoring.py`에
      신규 테스트 4개 — ① L1-04 boundary 발화 evidence의 floor_policy_ids가 빈 튜플
      ② L1-04 critical은 ("approval_control_high",) 유지 ③ L2-02 near_extra는 빈 튜플
      ④ L2-02 reference_match 발화 단독 topic 점수에 floor 0.45 적용·0.75 미적용 (**점수 단언 필수** —
      apply_topic_floors 통과 결과 값으로 단언)
      증거: `uv run pytest tests/modules/test_detection/test_rule_scoring.py -q` 출력에 신규 테스트
      4개 FAILED가 보이는 원문 (RED 확인)
- [ ] Step 3 (GREEN): §3 설계 구현 → 산출물: rule_scoring.py·topic_scoring.py 수정
      증거: 같은 명령이 전부 passed로 끝나는 원문
- [ ] Step 4 (ripple): 구 정책 id 잔존 0 확인
      증거: `grep -rn "duplicate_outflow_high" src tests config --include="*.py" --include="*.yaml"` 출력 0건
      (docs/는 설계자가 라운드 마감 시 갱신하므로 건드리지 말 것)
- [ ] Step 5(항상 마지막): 전체 검증(§6) 실행 후 출력 원문 확보
※ 각 단계의 증거는 완료 보고에 원문 그대로 포함한다. 증거가 없는 단계는 미수행으로 간주한다.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- 하드코딩: floor 값(0.45/0.75)을 detector나 case builder에 리터럴로 박지 말 것 — 반드시
  `DEFAULT_TOPIC_FLOORS` 정책 사전 경유. 버킷명 비교를 정규화 없이(`==` 대소문자 그대로) 박지 말 것.
- 테스트 약화 금지: 기존 테스트의 skip/xfail 추가, assert 삭제·완화, 기대값을 출력에 맞춰 수정.
  단 기존 테스트가 "L1-04 전 버킷 floor 적용"을 단언하고 있어 깨지는 경우는 **신규 스펙(버킷 게이트)을
  단언하도록 수정**하는 것이 정답이며, 그 수정 내역을 보고에 명시할 것.
- 범위 밖 수정 금지: 수정 가능 파일 = `src/detection/rule_scoring.py`,
  `src/detection/topic_scoring.py`, `config/phase1_case.yaml`(`topic_floors`의
  duplicate 키 1줄만), `tests/modules/test_detection/test_rule_scoring.py`.
  이외(특히 phase1_case_builder.py, detector 본체, yaml의 다른 섹션, docs) 변경 금지.
- `apply_topic_floors`의 require_primary/적용 로직 변경 금지.
- 체크리스트 항목 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)

- `uv run pytest tests/modules/test_detection/test_rule_scoring.py -q` → 기대: 전부 passed (신규 4개 포함)
- `uv run pytest tests/modules/test_detection/ -q` → 기대: 신규 실패 0 (실행 전 동일 명령으로 사전
  베이스라인을 떠서 전/후 failed 목록 비교 원문 첨부)
- `uv run python -c "from config.settings import get_phase1_case; s=str(get_phase1_case()); print(('duplicate_outflow_high' in s, 'duplicate_reference_match' in s))"`
  → 기대: `(False, True)` (yaml 오버라이드 교체 확인)
- `uv run ruff check src/detection/rule_scoring.py src/detection/topic_scoring.py` → 기대: All checks passed
※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED로 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 각 항목의 증거(명령 + 출력 원문 붙여넣기)
변경 파일: <경로 목록 — 변경하지 않은 파일을 포함하지 말 것>
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">

신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로이며 다음 지시로
이어진다. 거짓 DONE은 재검증에서 반드시 드러나고 작업 전체를 처음부터 재수행하게 된다.
