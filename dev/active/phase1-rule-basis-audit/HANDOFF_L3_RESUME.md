# 핸드오프 — PHASE1-1 룰 binary 재설계 (L3-07부터 재개) (2026-06-20)

컴팩트 후 이 파일부터 읽고 **L3-07**부터 이어서 진행. 큰 목표: PHASE1-1 모든 룰을 **"binary flag(0/1) + tier는 통합점수체계 조합이 결정"** 으로 재설계. 룰은 멍청하게, 정황(기말·수기·관계사·source)은 통합점수체계 소관, 부정 확정 아닌 **검토 트리거**.

## 작업 방식 (사용자 확정·반복)
- 룰 1~2개씩: **쉬운말 설명 → 백지 재설계 토의(결정거리는 옵션 제시 후 사용자 선택, §8) → 문서는 내가 직접 수정, 코드는 프롬프트로 다른 Claude/Codex 핸드오프**.
- 받은 코드 산출물은 **내가 직접 재현 검수**(toy 직접 호출 + rg 폐기물 0 + 전체 스위트). 보고 무비판 수용 금지(§9). 특히 binary면 **score 고유값 {0.0,1.0}** + **자동 source도 발화하는지** 직접 toy.
- contract: `.claude/state/contracts/66ec48be-...md` 측정가능 항목 선언(Stop 게이트). [x]는 수치·실패조건 박아야 통과.
- 한글 문서: 부분 편집만, U+FFFD 0 확인. 포매터가 표 재정렬하므로 Edit 실패 시 재read.

## 핵심 설계 원칙 (반복)
- **binary flag only**: 조건 충족=1.0, 아니면 0. 점수밴드·가중합·floor·전용 정규화 전부 폐기.
- **source/수기 차원은 L3-02 + source_trust + 통합점수 단일 소관**. 다른 룰이 자동 source 제외하면 안 됨(룰이 정황 가로채는 안티패턴). **자동 전표도 룰은 발화**, "자동이라 정상" 다운웨이트는 통합점수가 L3-02 수기 leg로 한 번만. 위장(`lone_automated_mask`)도 L3-02/source_trust로 일원화.
  - **예외(intrinsic, 유지)**: L1-05 자기승인·L1-06 직무분리의 시스템 actor 제외 = "통제위반이 사람을 전제"하는 위반 정의 자체라 남김. (intrinsic vs context 구분: 신호가 기계에도 **존재**하면 context→통합점수 / 기계엔 신호 자체가 **성립 안 하면** intrinsic→룰)
- **정황은 통합점수**: 기말+고액, 수기+승인우회 등 조합 가중은 룰이 아니라 통합점수체계(HIGH_COMBO_GROUNDING).
- **PHASE1-1에 booster 신설 금지**. context 태그는 OK(L3-02/03/04/05/06은 tier 게이트 미참여 보조축).

## SoT 문서 (현행 우선순위)
- **점수/tier/조합 최우선 SoT = `docs/spec/HIGH_COMBO_GROUNDING.md`** (2026-06-17 전면재작성). TIER_EVIDENCE_BASIS·TIER_SCORING_SPEC(06-14)는 그보다 옛날 초안 — 충돌 시 HIGH_COMBO 우선(사용자 지적).
- 룰 카드 SoT = `docs/spec/DETECTION_RULES.md`. PHASE1-2 = `docs/spec/DETECTION_RULES_PHASE1-2.MD`.
- canonical L1~L4 룰 수 = **30** (`RULE_DETAIL_METADATA_V1_LOCK.md`, L3-01 폐기로 31→30).

## 완료 현황 (L1-01 ~ L3-06) — 문서+코드+검수 전부 ✅
| 구간                                                                    | 상태                         |
| ----------------------------------------------------------------------- | ---------------------------- |
| L1 전 구간(L1-01~08, L1-09 삭제, L1-07-02 신설)                         | 이전 세션 완료(handoff 기록) |
| L2-02·L2-03·L2-04                                                       | 이전 세션 완료               |
| L2-01·L2-05 (binary + 자동 source 제외 제거)                            | ✅ 이번 세션 검수            |
| **L3-01 폐기**(L4-04가 역할 대체, count 31→30)                          | ✅ 문서+코드 검수            |
| **L3-02 수기**(is_manual_je 1/0, source-trust 일원화 책임 보유)         | ✅                           |
| **L3-03 관계사**(IC prefix 1/0, IC01/02/03·GR는 PHASE1-2 §4.4/4.5 이관) | ✅                           |
| **L3-04 기말/기초**(±5일 1/0, period_phase end/start annotation)        | ✅                           |
| **L3-05 주말/공휴일**(1/0, 자동도 발화)                                 | ✅                           |
| **L3-06 심야**(is_after_hours 1/0, 자동도 발화)                         | ✅                           |

검수 방식 toy 패턴: 자동 source도 1.0 발화 확인 + 폐기물 rg 0 + 전체 스위트 1362 passed.

## 즉시 할 일 (재개 지점)
1. **L3-07(전기일-문서일 괴리)·L3-08(적요 부실) 설명부터.** `DETECTION_RULES.md` 카드: L3-07 = `c04_backdated_entry`(현재 days_backdated 버킷 0.45/0.60 — 미전환), L3-08 = `c06_missing_or_corrupted_description`(현재 manual_entry context 사용).
2. 그 뒤 L3-09~L3-12, L4-01~L4-06 순. **L4-05(c12 시간대집중)는 자동 source 제외 보유 — 도달 시 intrinsic/context 판단 필요**(_manual_user_mask).

## 미커밋 ⚠️
- **세션 전체 변경이 워크트리에 미커밋**(git diff 수천 줄, L1/L2/L3 재설계 누적). 사용자 요청 시 논리 단위 커밋.

## 검수 주의 (반복 패턴)
- **환경 flaky 3종**(전체 스위트에서만, 단독 재실행 시 통과): `composite_sort_score_v126 MemoryError` / `test_vae_detector::TestTrain`(torch) / `duplicate_detector_100k_under_1s`(성능 타이밍). 전부 재설계 무관 — baseline은 "1362 passed + 이들 환경 flaky".
- **테스트 가위질 감시**: 폐기 동작 테스트 삭제는 정당, 살아있는 다른 룰 테스트 삭제는 F1. rg로 확인.
- **거대 git diff는 세션 누적**(이번 턴 아님). 변경 파일 stat로 실제 범위 확인.
