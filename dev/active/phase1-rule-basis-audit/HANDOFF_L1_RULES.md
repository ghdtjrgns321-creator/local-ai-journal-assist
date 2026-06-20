# 핸드오프 — PHASE1-1 L1 룰 재설계 (2026-06-17)

컴팩트 후 이 파일부터 읽고 이어서 진행. 큰 목표: PHASE1-1 L1~L4 룰을 "binary flag + 통합점수체계에서 조합돼야 HIGH" 원칙으로 하나씩 재설계. 지금 L1 진행 중.

## 핵심 설계 원칙 (사용자 확정)
- **통합점수체계는 HIGH/MEDIUM/LOW로 심플하게.** 단독 룰로 HIGH 만들지 않음 — 조합돼야 HIGH.
- 각 룰은 조건 충족 시 **binary flag**(score 1.0). 점수 단계(bucket) 폐기.
- 가중합·floor·band컷은 이전 재설계에서 이미 폐기됨(tier=조합 발화로 결정).
- 발화 맵 SoT: `dev/active/phase1-rule-basis-audit/PHASE1_TIER_FIRING_MAP.md`
- tier 근거 SoT: `docs/spec/HIGH_COMBO_GROUNDING.md`

## 진행 상태

### ✅ L1-01/02/03 — 완료·승인 (코드+문서+테스트)
- 데이터정합성 트랙(부정 tier 아님, 별도 "데이터 품질" 집계). binary, 버킷 제거.
- L1-01 차대불일치, L1-02 필수필드누락(cat1 저널성립불가 / cat2 룰실행불가 / cat3 무방), L1-03 무효계정(CoA 밖).
- 검수 완료: 1431 passed 재현, 버킷 0, hollow-PASS 아님.

### ◐ L1-04/05/06 — 문서 완료, 코드 프롬프트 발행됨 (다른 Claude 실행 대기)
**문서는 내가 직접 수정 완료**(DETECTION_RULES.md 카드 3개 + SOD_TOXIC_COMBINATIONS_GROUNDING.md).
**코드는 직전 대화에 발행한 프롬프트로 다른 Claude가 진행 중.** 결과 오면 내가 검수.

확정 설계:
- **L1-04** 승인한도초과: binary. ①한도 존재 AND 총액>한도, ②비승인권자/한도없는사람 승인 — 둘 다 잡음. approved_by 공란→L1-07. 단독 HIGH floor `approval_control_high` 폐기. 구현=`fraud_rules_feature.py::b03_exceeds_threshold`.
- **L1-05** 자기승인: binary(사람 자기승인 created_by==approved_by). 점수분리(review/immediate/escalated) 폐기. 시스템 자동 제외하되 위장의심이면 제외 취소. 구현=`fraud_rules_access.py::b06_self_approval`.
  - **위장의심 재정의**(`source_trust.py::lone_automated_mask`): 자동계열 AND [(batch_id 또는 job_id 빈칸) OR (같은날 외톨이 ≤10)]. (구: AND 둘다빈칸 AND 외톨이) ⚠️공유함수 — L4-05·L4-06·L1-04도 영향.
- **L1-06** 직무분리: 주입라벨(sod_violation/sod_conflict_type) 폐기 → created_by/approved_by/business_process로 YAML toxic pair 데이터 도출. 구현=`fraud_rules_access.py::b07_segregation_of_duties`.
  - **RED → score 1.0(primary)**, 단독 LOW·조합 시 HIGH. **YELLOW → score 0.0 + row_annotation 노트**(큐 안 뜸). booster·새 rule_id·per-row role 만들지 않음(YELLOW score0이면 seeding 자연히 안 됨).
  - YAML `config/sod_toxic_combinations.yaml`에 `signal_class: red|yellow` 추가.

### RED/YELLOW 기준 (확정) — 빼돌리기+숨기기
- **RED = 한 사람이 빼돌리기(custody: 현금/자산 만짐) + 숨기기(recording/reconciliation: 장부에서 가림) 둘 다.**
- **YELLOW = 하나만**(자산 못 만짐 / 못 숨김 / 저유동).
- **RED 8**: TRE+P2P, TRE+R2R, TRE+O2C, O2C+R2R, H2R+TRE, A2R+R2R, P2P단독, TRE단독
- **YELLOW 4**: P2P+R2R, H2R+R2R, A2R+TRE, MFG+R2R
- 근거 SoT: `docs/spec/SOD_TOXIC_COMBINATIONS_GROUNDING.md` §4.1
- 7 프로세스: R2R(기표·결산) O2C(매출·수금) P2P(매입·지급) H2R(급여) A2R(자산) TRE(자금) MFG(제조)

## 다음 할 일 (순서)
1. **L1-04/05/06 코드 결과 검수** (다른 Claude 산출물): ①L1-06 데이터도출 확인 ②YELLOW score0 큐 미surface ③lone_automated_mask OR재정의 공유룰(L4-05/06) 영향 ④테스트 가위질 없는지 + 1431+ 통과 재현.
2. **L1-07/08/09 설명→재설계** (아직 안 함). L1-07 승인생략, L1-08 기간불일치, L1-09 승인일누락.
3. 이후 L2/L3/L4 순차 (같은 방식: 쉬운말 설명 3개씩 → binary 재설계 → 프롬프트/직접).

## 작업 방식 (사용자 선호)
- 룰 3개씩: 쉬운말 + 무엇 잡나 + 어떤 조건이면 RED flag로 흐르나 설명.
- 문서 수정은 내가 직접, 코드 수정은 프롬프트로 핸드오프(다른 Claude/Codex).
- 프롬프트는 work-prompt-authoring 규약(단계체크리스트·증거강제·검증명령).
- 받은 산출물은 내가 직접 재현 검수(테스트 재실행·grep·diff). 보고 무비판 수용 금지.
- 한글 문서: 부분 편집만, U+FFFD 0 확인.

## 주의/미해결
- L1-06 YELLOW "거들기(combo 2차정황 편입)"는 미배선 — 현재 노트까지만. SoD combo 설계 시 검토.
- DETECTION_RULES.md는 PHASE1-1만(L4-02/05·D01/02·GR→PHASE1_2, Phase2 ML→별도 문서로 이미 분리됨).
- 구 dirty(HIGH_COMBO_GROUNDING·topic_scoring 등)는 내 이번 세션 작업 — 정상.
