# 작업: time_severity_score(OFF-TIME 보조축) 신설 + PHASE1 case sort_key 삽입

## 1. 목표
- OFF-TIME 보조축(주말·심야·작성자집중)을 `time_severity_score`로 계량해 PHASE1 case 모델에
  싣고, **모든 PHASE1 case 정렬 튜플의 정해진 위치**(금액보다 위)에 삽입한다.
- OFF-TIME은 **tier 게이트에 미참여**(stage1에서 제외 확인). 이 단계는 **정렬·UI 보조축만**.
- 성공 기준: §6 검증(단위테스트 + 정렬 회귀)이 기대 출력으로 끝나고, OFF-TIME 신호가 같은 tier
  안에서 더 위로 정렬되는 테스트가 통과한다.

## 2. 컨텍스트
- 읽어야 할 파일 (수정 전 반드시):
  - `docs/spec/PHASE1_TIER_SCORING_SPEC.md` §4 sort_key (time_severity_score 삽입 위치 권위 정의)
  - `docs/spec/HIGH_COMBO_GROUNDING.md` §2 (5)OFF-TIME 보조축 절(L77~83)
  - `src/export/phase1_case_view.py` 정렬 튜플들: L344~354, L1989, L2022, L2058, L2607 (전부)
  - `src/models/phase1_case.py` (case 모델 필드 — rule_count L53 등)
  - `src/detection/phase1_case_builder.py` (case 조립 — 룰 발화 집합이 case로 모이는 지점)
- 따라야 할 기존 패턴: 기존 정렬 튜플 `(_case_topic_score, triage_rank_score, repeat_months,
  total_amount, rule_count)` 형식. 새 필드는 case 모델 dataclass 필드로 추가(rule_count와 동일 방식).

## 3. 설계 (이대로 구현 — 임의 변경 금지)

### 3-1. OFF_TIME_SET 정의 (상수 1곳, 예: phase1_case_builder.py 상단)
```
OFF_TIME_SET = {"L3-05", "L3-06", "L4-05"}   # 주말·공휴일 | 심야 | 작성자 비정상시간 집중
```
※ 기간귀속(L3-04 기말·L3-11 컷오프)은 OFF-TIME 아님 — 절대 넣지 말 것(stage1 게이트 소관).

### 3-2. time_severity_score 산식 (case 단위, 정수)
```
high(2점): "L3-05"(주말·공휴일) 발화  또는  "L4-05"(작성자 집중) 발화
med(1점) : "L3-06"(심야) 발화
합산(상한 없음, 두 축 동시면 3). case에 발화한 룰ID 집합 기준으로 계산.
time_severity_score = (2 if L3-05) + (2 if L4-05) + (1 if L3-06)
```
- case 모델에 `time_severity_score: int = 0` 필드 추가.
- case_builder가 case 조립 시 위 산식으로 채운다. **금액·연도 리터럴 사용 금지** — 룰ID 발화 여부만.

### 3-3. 정렬 튜플 삽입 (PHASE1 case 정렬 전부)
- 현재 `(..., total_amount, rule_count)`로 끝나는 **모든 PHASE1 case-list 정렬**에서
  `total_amount` **바로 앞**에 `case.time_severity_score`를 삽입한다(금액보다 위 = anti-burying).
- 즉 `(_case_topic_score, triage_rank_score, repeat_months, time_severity_score, total_amount, rule_count)`.
- §4 스펙이 "independent_primary 다음, 금액 앞"이라 코드의 triage/repeat(=tier·primary 변별자) 다음,
  total_amount(=materiality proxy) 앞이 정합. 스펙 §4 문구와 코드 튜플이 충돌하면 임의 판단 말고
  STATUS: NEEDS_CONTEXT로 보고.
- 적용 대상: §2에 나열한 case-object 정렬 전부(L344·1989·2022·2058·2607 및 같은 형태 추가 발견 시).
  row-dict 정렬(L428·517·799·976·2456)은 case 객체가 아니면 **건드리지 말 것** — 발견 즉시 목록 보고.

### 3-4. UI 표기 (있는 화면에만, 신규 화면 만들지 말 것)
- review queue 행에 OFF-TIME 배지/컬럼이 이미 있으면 time_severity_score>0을 노출. 없으면 이 단계에서
  신규 UI 만들지 말고 "노출 지점 없음"으로 보고(stage3/대시보드와 중복 방지).

## 4. 단계 체크리스트 (순서 고정)
- [ ] Step 1: §2 파일 읽기 + 정렬 튜플 전 위치 grep. 증거: `grep -n "total_amount,\s*$\|rule_count,\s*$" src/export/phase1_case_view.py` 결과 + case-object 정렬 사이트 목록
- [ ] Step 2: OFF_TIME_SET 상수 + time_severity_score 필드(case 모델) 추가. 증거: 두 diff
- [ ] Step 3: case_builder에서 산식 계산 채움. 증거: diff + 단위테스트(주말 case=2, 심야=1, 집중=2, 무신호=0)
- [ ] Step 4: 정렬 튜플 전부에 삽입(§3-3). 증거: 변경한 각 줄 diff + 변경 사이트 수
- [ ] Step 5: 정렬 회귀 테스트 — 같은 tier 두 case 중 OFF-TIME 있는 쪽이 위로. 증거: 테스트 함수명 + 통과
- [ ] Step 6(마지막): §6 전체 검증
※ 증거 없는 단계는 미수행 간주.

## 5. 금지 사항 (1건이라도 위반 시 실패)
- 하드코딩 금지: 연도·시각 임계(예: "심야=22시")를 case_builder에 박지 말 것 — 시각 판정은 이미 L3-05/06/L4-05
  룰 발화에서 끝남. 여기선 룰ID 발화 여부만 본다.
- OFF-TIME을 tier 게이트(`_fraud_combo_floor_results`)에 넣지 말 것 — 정렬·UI 전용.
- L3-04·L3-11을 OFF_TIME_SET에 넣지 말 것(기간귀속 ≠ off-time).
- 테스트 약화 금지(skip/xfail/assert 완화/기대값 출력맞춤).
- 범위 밖 수정 금지: 수정 가능 = `phase1_case_builder.py`, `models/phase1_case.py`,
  `export/phase1_case_view.py`, 관련 테스트. topic_scoring.py(stage1)·dashboard(stage3)는 건드리지 말 것.
- 체크리스트 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수)
- `uv run pytest tests/modules/test_detection/test_phase1_case_builder.py -q` → 기대: 0 failed
- `uv run pytest tests/modules/ -q -k "case or sort or topic"` → 기대: 신규 0 failed (기존 알려진 실패 N 명시)
- ripple grep: `grep -rn "time_severity_score" src/` → 기대: 모델·builder·모든 정렬 사이트에 출현
- 한글 깨짐(U+FFFD) 0건.
※ 기대와 다르면 DONE 금지. 원인 미상 BLOCKED.

## 7. 완료 보고 양식 (그대로, 생략 금지)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령+출력 원문)
변경 파일: 경로 목록(변경 안 한 파일 포함 금지)
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려: 정직하게 전부. 없으면 "없음"

> 모든 보고·주석은 한국어로 작성한다.
