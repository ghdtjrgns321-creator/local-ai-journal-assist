# 작업: 전표/흐름(unit) 단위 검토 큐 + 룰별 커버리지 표 신설

## 1. 목표
- PHASE1 검토 큐를 `phase1.units`(document/flow 단위) 기반으로 신설한다. tier ∈ {HIGH, MEDIUM}만,
  **1전표(unit) = 1줄**. LOW unit은 큐에서 빠지고 룰별 커버리지 표로만 surface.
- 근거 SoT: `docs/spec/UNIT_MEASUREMENT_POLICY.md` — tier(정답)는 document/flow에만 붙는다(Layer 1).
  case는 집계뷰(자기 점수 없음). 현 코드는 case.priority_band를 큐 축으로 써 정책 위반 → 단위로 통일.
- 성공 기준: §6 검증(단위테스트 + 정렬·필터 회귀)이 기대 출력으로 끝나고, "LOW unit이 transaction
  queue에 없고 / HIGH·MEDIUM unit은 있고 / 커버리지 표가 HIGH unit의 룰 발화도 전수 카운트"가 테스트로 증명된다.

## 2. 컨텍스트
- 읽어야 할 파일 (수정 전 반드시):
  - `docs/spec/UNIT_MEASUREMENT_POLICY.md` 전체(§1 단위3층·§5 집계뷰·§8 금지)
  - `docs/spec/HIGH_COMBO_GROUNDING.md` §5(LOW A안 = Coverage Queue)
  - `src/models/phase1_unit.py` (BasePhase1Unit·DocumentUnit·FlowUnit 필드)
  - `src/models/phase1_case.py` (CaseGroupResult: time_severity_score L54·priority_band·units 속성 L122)
  - `src/detection/phase1_case_builder.py`: `build_phase1_case_result`(L649~788), `_build_document_units`/
    `_build_flow_units`, `_score_phase1_units`(L716 부근), `_derive_case_scores_from_units`(L2408~2492),
    `compute_time_severity_score`(L83~94)
  - `src/export/phase1_case_view.py`: `build_phase1_case_queue`(L314~358) 정렬튜플, `_case_row`(L2291),
    `_band_rank`(L2890), `build_phase1_integrity_rule_view`(L448~534) = 커버리지 seed
  - `src/detection/rule_scoring.py` (RULE_SCORING_REGISTRY: scoring_role·standalone_rankable·final_topic)
- 따라야 할 기존 패턴: `build_phase1_case_queue`/`_case_row`/`_band_rank`와 **동일한 형식**으로 unit 버전을
  만든다. 자체 포맷 발명 금지. 정렬은 case 정렬튜플 구조를 unit 필드로 그대로 옮긴다.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

### 3-1. unit 모델에 정렬 필드 2개 추가 (`src/models/phase1_unit.py` BasePhase1Unit)
```
total_amount: float = 0.0          # 이 unit(전표/흐름)의 대표 금액(materiality proxy)
time_severity_score: int = 0       # OFF-TIME 보조축 — case와 동일 의미
```
case 모델의 동명 필드와 의미 동일. (case 필드는 제거하지 말 것 — case 집계뷰도 표시에 쓸 수 있음. stage3b 소관.)

### 3-2. unit 점수화 시 두 필드 채움 (`_score_phase1_units` 안)
- 각 unit의 발화 룰ID 집합 = `{ref.rule_id for ref in unit.evidence_rows}` (+ FlowUnit은 absorbed_rule_hits 포함).
- `time_severity_score = compute_time_severity_score(그 룰ID 집합)` (기존 함수 재사용 — 시각·연도 리터럴 금지).
- `total_amount` = 그 unit의 전표 금액 합. **금액 출처를 코드에서 확인할 것**: DocumentUnit이면 그 document의
  금액, FlowUnit이면 member_document 금액 합. case가 total_amount를 어디서 얻는지(`_build_cases` 또는
  projection) 추적해 **같은 출처**를 쓴다. 금액 출처가 unit 빌드 시점에 없으면 임의 추정 말고
  STATUS: NEEDS_CONTEXT로 그 지점을 보고하고 멈출 것.

### 3-3. unit 정렬 키 헬퍼 (`phase1_case_view.py`)
```
def _unit_band_rank(unit) -> int:   # _band_rank 재사용 가능하면 재사용
    return _band_rank(unit.priority_band)

def _unit_sort_key(unit) -> tuple:
    # case 정렬튜플(_band_rank, triage_rank_score, time_severity_score, total_amount, rule_count)을
    # unit 필드로 옮김. repeat_months는 unit에 없으므로 제외.
    return (
        _band_rank(unit.priority_band),
        unit.triage_rank_score,
        unit.time_severity_score,        # 금액보다 위 (anti-burying, stage2와 일관)
        unit.total_amount,
        len(unit.evidence_rows),
    )
```

### 3-4. transaction queue 빌더 신설 (`phase1_case_view.py`)
```
def build_phase1_transaction_queue(pr, *, topic_id=None, top_n=None) -> list[dict]:
    phase1 = resolve_phase1_case_result(pr)
    units = [u for u in phase1.units if _band_rank(u.priority_band) >= _band_rank("medium")]  # HIGH/MEDIUM만
    if topic_id:
        units = [u for u in units if topic_id in u.topic_scores]    # topic 필터(있을 때)
    units = sorted(units, key=_unit_sort_key, reverse=True)
    if top_n is not None:
        units = units[:top_n]
    return [_unit_row(u, phase1) for u in units]
```
- `_band_rank("medium")` 컷으로 LOW(=1)·CONTEXT 제외. band 문자 리터럴 분기 직접 박지 말 것 — `_band_rank` 경유.
- `_unit_row(unit, phase1)`: `_case_row`와 동형으로 unit→dict. unit_id, unit_type, priority_band,
  time_severity_score, total_amount, 발화 룰 목록(evidence_rows), topic_scores 등 기존 근거 필드 사용.

### 3-5. 룰별 커버리지 표 신설 (`phase1_case_view.py`)
```
def build_phase1_rule_coverage(pr) -> dict:
    # 전수: 모든 unit의 evidence_rows를 룰별로 집계(tier 무관 — HIGH/MEDIUM unit 발화도 카운트).
    # 행 대상 = standalone_rankable=True 인 primary 룰만(RULE_SCORING_REGISTRY 메타로 판별, 룰ID 나열 금지).
    # 룰ID별 distinct document_id 수(=전표 발화 수) + tier 분해(high/medium/low unit 수).
    # drill-down 정렬은 _unit_sort_key 재사용(공통 sort_key).
    return {"available": ..., "items": [{"rule_id":..., "documents":..., "high":.., "medium":.., "low":..}, ...]}
```
- 기존 `build_phase1_integrity_rule_view`(L448)의 집계 패턴 참고하되, **case 순회가 아니라 unit 순회**.
- standalone 판별: `meta = RULE_SCORING_REGISTRY.get(rule_id)` → `meta.scoring_role == "primary" and meta.standalone_rankable`. booster/macro/combo_only 제외.

## 4. 단계 체크리스트 (순서 고정)
- [ ] Step 1: §2 파일 읽기 + case의 total_amount 출처 추적 보고. 증거: 출처 파일:줄
- [ ] Step 2: unit 모델 필드 2개 추가(§3-1). 증거: diff
- [ ] Step 3: `_score_phase1_units`에서 두 필드 채움(§3-2). 증거: diff + 단위테스트(주말 unit time_severity=2, 금액 일치)
- [ ] Step 4: `_unit_sort_key`·`build_phase1_transaction_queue`·`_unit_row` 신설(§3-3·3-4). 증거: diff
- [ ] Step 5: `build_phase1_rule_coverage` 신설(§3-5). 증거: diff
- [ ] Step 6: 테스트 — LOW unit 큐 제외 / HIGH·MEDIUM 포함 / 커버리지가 HIGH unit 룰 발화 카운트 / standalone primary만 행. **기대값은 정책·§3 기준으로, 코드 출력 베끼지 말 것.**
- [ ] Step 7(마지막): §6 전체 검증
※ 증거 없는 단계는 미수행 간주.

## 5. 금지 사항 (1건이라도 위반 시 실패)
- 하드코딩 금지: band 문자("high"/"medium"/"low") 직접 비교 분기 금지 — `_band_rank` 경유. 룰ID 화이트리스트
  나열 금지(커버리지 행 대상은 메타데이터로 판별). 연도·금액 임계 리터럴 금지(금액은 데이터에서).
- case.priority_band를 새 unit 큐의 축으로 쓰지 말 것 — unit.priority_band가 축.
- 3-surface 비병합: PHASE1-2 family·PHASE2 점수와 합치지 말 것.
- 기존 case 큐 빌더 삭제·수정 금지(이 단계는 unit 큐 **신설**만 — case 전환은 stage3b).
  단 새 함수 추가만 허용, 기존 함수 시그니처 변경 금지.
- 테스트 약화 금지(skip/xfail/assert 완화/기대값 출력맞춤). 빈 큐·빈 커버리지를 PASS로 두지 말 것
  (hollow-PASS — 최소 1행 기대치 박기).
- 범위: `phase1_unit.py`, `phase1_case_builder.py`(_score_phase1_units만), `phase1_case_view.py`(신설 함수),
  관련 테스트. topic_scoring.py·dashboard는 건드리지 말 것.
- 체크리스트 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수)
- `uv run pytest tests/modules/test_detection/test_phase1_case_builder.py tests/modules/test_export -q`
  → 기대: 신규 0 failed (기존 알려진 실패 N 명시)
- 직접 재현(2+ 케이스, ripple-search):
  `uv run python -c "..."` 로 (a) priority_band가 low인 unit이 build_phase1_transaction_queue 결과에 없음,
  (b) high/medium unit은 있음, (c) build_phase1_rule_coverage items에 standalone primary 룰만, high unit의
  발화가 documents 카운트에 포함됨 — 3건 print로 확인. (지시 실행자가 명령 작성, 출력 원문 첨부)
- ripple grep: `grep -rn "build_phase1_transaction_queue\|build_phase1_rule_coverage" src/` → 신설 함수 출현
- 한글 깨짐(U+FFFD) 0건.
※ 기대와 다르면 DONE 금지. 금액 출처 등 불명이면 NEEDS_CONTEXT.

## 7. 완료 보고 양식 (그대로, 생략 금지)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령+출력 원문)
변경 파일: 경로 목록(변경 안 한 파일 포함 금지)
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려: 정직하게 전부. 없으면 "없음"

> 모든 보고·주석은 한국어로 작성한다.
