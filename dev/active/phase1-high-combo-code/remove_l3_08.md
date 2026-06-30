# 작업: L3-08(적요부실/missing-description) 룰 코드 전수 제거

## 1. 목표
- L3-08 **탐지 룰**을 코드에서 전수 제거한다(룰 등록·점수·카탈로그·설정·메타데이터·설명·테스트 + c06 detector).
- 근거: 부실 적요는 신뢰 탐지가 불가(빈칸만 잡힘) — 룰 폐기 결정.
- **절대 보존(공유 피처)**: `description_quality`·`description_*` 컬럼과 `has_risk_keyword`/위험키워드 인프라는
  L3-08 전용이 아니라 **다른 룰·인프라가 소비**한다. 제거 금지.
- 성공 기준: §6 검증 — L3-08 룰 grep=0(지정 경로), 공유 피처 잔존, 전체 테스트 신규 실패 0.

## 2. 컨텍스트
- 읽어야 할 파일(수정 전):
  - detector: `src/detection/anomaly_rules_simple.py`(c06_missing_or_corrupted_description L611~),
    `src/detection/anomaly_layer.py`(L3-08 등록/배선)
  - 등록·메타: `src/detection/rule_scoring.py`(L317 L3-08 entry), `src/detection/phase1_rule_catalog.py`
    (L83·96·117), `src/detection/constants.py`(L112·184·610·765·772), `src/detection/rule_detail_metadata.py`,
    `src/metrics/rule_mapping.py`
  - 소비: `src/detection/phase1_case_builder.py`, `src/export/phase1_case_view.py`,
    `src/detection/topic_scoring.py`, `src/detection/variance_layer.py`, `src/metrics/ground_truth_evaluator.py`
  - dashboard: `dashboard/tab_phase1.py`, `dashboard/components/mapping_review.py`,
    `dashboard/components/rule_labels.py`
  - config: `config/audit_rules.yaml`, `config/phase1_case.yaml`, `config/schema.yaml`,
    `config/risk_keywords.yaml`, `config/datasynth.yaml`
  - 문서: `docs/spec/HIGH_COMBO_GROUNDING.md`(적요부실/L3-08 보조축 절만)
- 배경: stage1에서 topic_scoring 의 combo 게이트에서는 L3-08 이미 빠짐(_PERIOD_END_CORROBORANT_RULES에
  L3-08 없음). 남은 건 룰 자체 등록·detector·메타·설정·테스트.

## 3. 설계 (이대로 — 임의 변경 금지)

### 3-1. 제거 대상 (L3-08 룰)
1. **detector 함수**: `c06_missing_or_corrupted_description`(anomaly_rules_simple.py) 함수 정의 + anomaly_layer.py
   의 그 함수 등록/호출/룰ID 배선 제거.
2. **rule_scoring.py**: `"L3-08": RuleScoringMetadata(...)` entry 제거.
3. **phase1_rule_catalog.py**: L3-08 을 리스트·`ledger_integrity` set·기타 집합에서 제거.
4. **constants.py**: 라벨(L112)·layer 맵(L184)·`RuleExplanation`(L610)·alias/reason 맵(L765·772)에서 L3-08 제거.
5. **rule_detail_metadata.py·metrics/rule_mapping.py**: L3-08 항목 제거.
6. **config**: audit_rules.yaml·phase1_case.yaml·schema.yaml·risk_keywords.yaml·datasynth.yaml 에서
   **L3-08 룰 정의/매핑 항목**만 제거(아래 보존 항목 건드리지 말 것).
7. **소비처**: phase1_case_builder·phase1_case_view·topic_scoring·variance_layer·ground_truth_evaluator·
   dashboard 3파일에서 L3-08 룰ID 참조 제거(데이터품질 리스트·라벨·표시 등). 제거로 빈 구조가 되면 안전하게 정리.
8. **테스트**: L3-08 을 단정하는 테스트는 **제거 또는 L3-08 부재 단정으로 전환**(약화 아님 — 룰이 없어진 게 정답).
9. **HIGH_COMBO_GROUNDING.md**: 적요부실(L3-08) 보조축 절(§2 (6) 부근) 제거. 제거 후 보조축 카탈로그는
   OFF-TIME·라운드넘버 2종. §8 등 본문의 L3-08 언급도 정리. **이 문서 1개만** — 다른 .md 건드리지 말 것.

### 3-2. 절대 보존 (L3-08 아님 — 제거 시 다른 룰 깨짐)
- `description_quality`·`description_line_missing`·`description_header_missing`·`description_both_missing`
  컬럼 생성(`src/feature/text_features.py`·`src/feature/engine.py`·`src/db/schema.py`) — **유지**.
  소비처 `src/detection/fraud_rules_access.py`(L1424 description_quality.isin)·`fraud_rules_feature.py`·
  `metrics/ground_truth_evaluator.py` — **건드리지 말 것**.
- `has_risk_keyword`·`risk_keywords.yaml` 인프라(`src/company/*`·`src/context.py`·`src/db/schema.py`) — **유지**.
- text_features.py 의 주석이 description_quality 를 "L3-08"이라 칭하면 주석만 정리 가능하나, **컬럼 생성 로직은
  보존**(다른 소비처 있음).

### 3-3. tools/scripts (데이터 생성 무변경)
- `tools/scripts/*`·`dev/active/*`·`scripts/*` 의 L3-08 참조는 **데이터 생성·truth 라벨 로직을 바꾸지 말 것**
  (과거 데이터셋 재현성). 단순 룰-리스트 참조만 안전하면 제거. 손대지 않은 파일·이유는 보고에 [~]로 명시.

설계가 현장과 안 맞으면(보존 피처 제거 없이 룰 제거가 불가한 결합 등) 임의 변경 말고 STATUS: NEEDS_CONTEXT.

## 4. 단계 체크리스트 (순서 고정)
- [ ] Step 1: §2 파일 읽기 + L3-08 전체 grep 재확인. 증거: 파일·줄 목록
- [ ] Step 2: detector(c06) + anomaly_layer 등록 제거. 증거: diff + `grep c06_missing_or_corrupted_description src/`=0
- [ ] Step 3: 등록·메타·config 제거(§3-1 2~6). 증거: diff
- [ ] Step 4: 소비처·dashboard 제거(§3-1 7). 증거: diff
- [ ] Step 5: 테스트 정리(§3-1 8). 증거: 변경 테스트명 + 사유
- [ ] Step 6: HIGH_COMBO_GROUNDING.md 적요부실 절 제거(§3-1 9). 증거: diff
- [ ] Step 7(마지막): §6 전체 검증
※ 증거 없는 단계는 미수행 간주.

## 5. 금지 사항 (1건이라도 위반 시 실패)
- 공유 피처 제거 금지: description_quality·description_*·has_risk_keyword·risk_keywords 컬럼/인프라 삭제 금지.
- fraud_rules_access·fraud_rules_feature·company config·DB schema 의 description_quality/risk_keyword 소비 건드리지 말 것.
- 데이터 생성 로직(tools/scripts datasynth) 변경 금지.
- 문서는 HIGH_COMBO_GROUNDING.md 1개만. 다른 .md 건드리지 말 것.
- 테스트 약화 금지(skip/xfail/assert 완화). 단, L3-08 룰 제거에 따른 기대 변경은 "L3-08 부재"를 단정하는 정상 갱신.
- 한글 깨짐(U+FFFD) 금지 — 최소 patch 편집, 전체 재작성 금지(Korean encoding guard).
- 체크리스트 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수)
- L3-08 룰 grep=0: `grep -rn "L3-08\|L3_08" src/detection src/export src/metrics dashboard config/audit_rules.yaml config/phase1_case.yaml` → 0건
- detector 제거: `grep -rn "c06_missing_or_corrupted_description" src/` → 0건
- 공유피처 보존: `grep -rn "description_quality" src/feature/engine.py src/detection/fraud_rules_access.py` → ≥1건(잔존)
- has_risk_keyword 보존: `grep -rcn "risk_keyword" src/db/schema.py src/context.py` → 변경 전과 동일
- import 스모크: `uv run python -c "import src.detection.fraud_rules_access, dashboard.tab_phase1; print('OK')"` → OK
- 전체 회귀: `uv run pytest tests/ -q` → 신규 failed=0. **변경 전 git stash 로 baseline 실패 집합 구해 comm 으로 신규 0 확인**(알려진 실패 N 명시).
- HIGH_COMBO: `grep -c "L3-08\|적요부실" docs/spec/HIGH_COMBO_GROUNDING.md` → 0
- U+FFFD: 변경 파일에 replacement char 0건.
※ 하나라도 기대와 다르면 DONE 금지.

## 7. 완료 보고 양식 (그대로, 생략 금지)
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령+출력 원문)
변경 파일: 경로 목록(변경 안 한 파일 포함 금지)
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려: 정직하게 전부(특히 tools/scripts 남긴 것 [~]사유, fraud_rules_access 가 description_quality 계속 쓰는 점). 없으면 "없음"

> 모든 보고·주석은 한국어로 작성한다.
