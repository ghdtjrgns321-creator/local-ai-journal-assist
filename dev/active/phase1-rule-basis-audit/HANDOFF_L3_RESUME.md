# 핸드오프 — PHASE1-1 룰 binary 재설계 (L3-10부터 재개) (2026-06-20)

컴팩트 후 이 파일부터 읽고 **L3-10**부터 이어서 진행. 큰 목표: PHASE1-1 모든 룰을 **"binary flag(0/1) + 정황·강도·역할은 통합점수체계 소관"** 으로 재설계. 룰은 멍청하게, 부정 확정 아닌 검토 트리거.

## ⛔ 최우선 교훈 — 통합점수체계(rule_scoring.py)까지 ripple 안 하면 찐빠
binary 전환은 **룰 함수(score_series)만 바꾸면 미완**이다. `src/detection/rule_scoring.py`가 룰의 annotation/raw_value를 받아 signal_strength·normalized_score·scoring_role을 재계산하는데, 여기에 **bucket 정규화가 박혀 있다**. 룰을 binary로 바꾸면서 이걸 안 고치면 룰은 0/1인데 점수체계는 옛 bucket을 읽으려다 fallback으로 빠진다 = 통합점수 오계산.

**현재 미해결 결함 (L3-07·L3-09)**: 룰 함수는 binary로 바꿨으나 rule_scoring 미반영:
- `rule_scoring.py` L72-73 `L307_BUCKET_SIGNAL_STRENGTH = {moderate_gap:0.55, large_gap:0.75, extreme_gap:1.0}` — 죽은 상수
- `rule_scoring.py` L87~ `L309_AGING_BUCKET_SIGNAL_STRENGTH = {aging_30_60:0.75, ...}` — 죽은 상수
- `_rule_specific_signal_strength()` L625-628(L3-07 `label.endswith("_moderate_gap")`), L565-577(L3-09 `label in L309_AGING_BUCKET`) — binary annotation엔 bucket label 없음 → 매칭 실패 → L632 fallback
- → **L3-07/L3-09 binary를 진짜 완성하려면 이 분기·상수를 제거하고, signal_strength가 binary(발화=1.0)로 흐르게 해야 한다.** 코드 일괄 작업에 포함.

## 코드 work prompt 작성 시 필수 (work-prompt-authoring 스킬)
binary 전환 룰의 **소비자 전부를 ripple 범위에 넣어라**. 빠뜨리면 찐빠:
1. 룰 함수 `anomaly_rules_simple.py`(또는 evidence_rules.py) — score_series binary, bucket/방향/차등 제거, breakdown·row_annotations 사실값만
2. **`rule_scoring.py`** — 해당 룰의 `_rule_specific_signal_strength` 분기 + bucket 상수 제거(이게 통합점수 연결, 절대 빠뜨리지 말 것)
3. `anomaly_layer.py` — `_format_rule_detail`/룰별 detail 메서드(L3-07 때 `_l307_detail` 제거 후 `test_anomaly_layer` 깨졌음)
4. `ground_truth_evaluator.py` — 해당 룰 평가 분기(score band → flagged_docs 단순화)
5. `topic_scoring.py` — 조합 로직은 통합점수 정상(건드리지 말 것), 단 bucket 의존하면 확인
6. 테스트 — `test_anomaly_rules_simple.py`(룰), `test_anomaly_layer.py`(detail), `test_rule_scoring.py`(점수), `test_ground_truth_evaluator.py`. **모두 ripple 범위에 명시.** 폐기 동작 검증 assert는 binary 기대로 *교체*(삭제 금지).
- prompt는 §6 검증에 `pytest tests/modules/test_detection -q` 전체 + toy(score {0.0,1.0}) + 폐기물 grep 0 박기. 한국어 보고 지시.

## 작업 방식 (사용자 확정·반복)
- 룰 1~2개씩: **쉬운말 설명 → 백지 재설계 토의(결정거리 옵션 제시 후 사용자 선택, §8) → 문서는 내가 직접 수정, 코드는 work prompt로 다른 Claude/Codex 핸드오프 → 받은 산출물 직접 재현 검수**.
- 검수: toy 직접 호출(score 고유값 {0.0,1.0}) + 폐기물 rg 0 + 전체 스위트 + **rule_scoring 연결 확인**. 보고 무비판 수용 금지(§9). 하청의 DONE_WITH_CONCERNS는 정상 — 내 prompt 결함 직접 수정.
- **룰 카드에 "booster/게이트 미참여/단독 queue 불가/primary" 등 점수체계 역할 박지 말 것.** 그건 `rule_scoring.py`의 `RuleScoringMetadata`(scoring_role/evidence_strength/standalone_rankable)가 SoT. 카드는 "무엇을 발화하는가"만.
- 코드 반영·외부 count 정합은 **룰 재설계 다 끝낸 뒤 한꺼번에**(사용자 지시).
- 한글 문서: 부분 Edit만, U+FFFD 0. 포매터가 표 재정렬하므로 substring 매칭 권장.

## 핵심 설계 원칙 (반복)
- **binary flag only**: 조건 충족=1.0, 아니면 0. 점수밴드·가중합·bucket·전용 정규화 폐기.
- **정황은 통합점수체계**: 기말+고액 조합, "자동이라 정상" 다운웨이트(→L3-02 수기 leg/source_trust), 강도(폭/금액) 가중 전부 룰 밖. 룰이 정황 가로채면 안티패턴.
- **분석 구동 값은 입력에서**(§3): 계정 목록·임계·연도를 코드 리터럴로 박아 발화 구동 금지. 근거 없는 starter가 발화를 구동하면 버그.

## 완료 현황
| 룰                                                                  | 문서                         | 코드                                                                             |
| ------------------------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------- |
| L1-01~L3-06 (이전 세션)                                             | ✅                           | ✅                                                                               |
| **L3-08 폐기**(적요 의미정합성은 결정론 밖)                         | ✅ 활성문서 L3-08 활성참조 0 | [>] 일괄(c06+description_quality feature 제거, fraud_rules_access 보조신호 제거) |
| **L3-07 binary**(폭·방향·재정규화 폐기)                             | ✅                           | ✅ 룰함수 검수완료(1387 passed) / ⚠️ **rule_scoring 미반영(위 결함)**            |
| **L3-09 binary**(aging·금액 bucket 폐기, 미정리판정·threshold 유지) | ✅                           | ✅ 룰함수 검수완료(60 passed) / ⚠️ **rule_scoring 미반영(위 결함)**              |

## 재개 지점 — L3-10, L3-11 (설명·토의까지 끝, 코드 미착수)
- **L3-10 고위험 계정**: binary 합의(`민감계정∈입력목록`이면 1). **단 "민감계정" 정의가 코드 하드코딩(`audit_rules.yaml` 1190/2190/111* starter)이라 근거 없음 = §3 위반.** 재설계: 민감계정 목록을 engagement 설정 **입력**으로만 받고, 미지정이면 발화 0건(전 계정 정상 아님=미검증). starter 리터럴이 발화 구동하면 안 됨. priority_case/raw_signal/normal_control 3-tier 차등은 폐기(조합·자동다운웨이트는 통합점수/source_trust). 구현 `fraud_rules_access.py::b13_high_risk_account_use`.
- **L3-11 매출 컷오프**: binary 합의. `abs(posting-delivery) > 허용일수`면 1. **period_end 가중(1.5) 폐기 확정**(L3-04 조합은 통합점수). 허용일수는 `settings` 입력 유지(매출 5일/비용 7일, K-IFRS 관행 추정치 — 감사인 조정값). **미결정 1건: day_diff 강도를 L3-09식 보존 vs L3-07식 완전폐기.** 구현 위치 특이 = `EvidenceDetector`(evidence_rules.py::ev02_cutoff_violation), anomaly_rules_simple 아님.
- 그 뒤 L4-01~L4-06. (L4-03 z-score bucket, L4-04 rare-pair bucket 등도 rule_scoring에 L403_ZSCORE_BUCKET 등 박혀 있음 — 같은 ripple 주의)

## SoT·제외
- 점수/tier/조합 최우선 SoT = `docs/spec/HIGH_COMBO_GROUNDING.md` (**수정 금지** — 사용자 지시, 코드/문서 정리 모두 제외).
- 룰 카드 SoT = `docs/spec/DETECTION_RULES.md`. canonical count = **29**(L3-01·L3-08 폐기, SoT `RULE_DETAIL_METADATA_V1_LOCK.md`).
- 외부 참조 문서 ~16곳 count "31/30" stale(L3-01 미반영) → 룰 재설계 후 일괄 29 정합(사용자 "싹 다 한꺼번에").
- rule-basis-and-catalog.md는 사용자가 직접 L3-08 행 정리함(L3-10/L3-11 행은 "booster/게이트" 표현 남아있음 — 카드 역할표현 정리 시 같이).

## contract
`.claude/state/contracts/cb81035a-2f76-41e5-8cb0-6bcf8684228b.md` — 측정가능 항목. [>]=코드 일괄 대기(L3-08 룰제거, L3-07/L3-09 rule_scoring 정리, 외부 count 정합).

## 환경 flaky (baseline = 1387 passed + 이들)
`composite_sort_score_v126 MemoryError` / `test_vae_detector::TestTrain`(torch) / `duplicate_detector_100k_under_1s`(성능타이밍) — 전부 재설계 무관.
