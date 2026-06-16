# HANDOFF (2026-06-07) — 다음 컨텍스트용

## 지금 당장 할 일 (최우선)
**P3-2 overlay의 `backfill_headers` 버그 수정 → v12 재생성 → detector-only 측정(~4분).**

### 범인 (확정, 코드에서 직접 확인)
`tools/datasynth/crates/datasynth-cli/src/p3_2_overlay.rs:1696` `backfill_headers()`가 **전체 행(98만)**에:
- `is_period_end = (전기일 day >= 25)` → 약 23%가 True
- `approval_required = "true"`, `approval_limit = "50000000"` 광역 주입

→ v29에선 이 입력들이 없어 L3-04/L1-04/L1-07이 **skip**(그래서 detector 248초)인데, overlay가 켜버려서
**정상 행에서 대량 발화(L3-04 132k행, 44%)** → downstream(evidence enrichment/scoring)이 폭발 → 측정이 안 끝남.
**느린 건 detector도 unit빌드도 아니라 overlay가 정상 행에 트리거를 깐 것.**

### 고칠 것
`backfill_headers`가 **정상 행엔 트리거 안 되는 값**을 주게. 트리거는 truth 행(712~717 주입 경로)에서만.
- `is_period_end`: `day>=25`(7일=23%) 금지. 정상=False(또는 진짜 좁은 결산 1~2일). 트리거는 truth만.
- `approval_required/approval_limit`도 정상(발화 유발 X) 값.

### 검증
- v12에서 `tools/scripts/measure_phase1_detector_catch.py`(detector-only, unit빌드 안 함)로 1회.
- 정상 행 룰 발화율이 v29 수준(낮음), L3-04 대량 flag 없음, ~4분 완주.
- 룰별 caught/missed + evasion(→PHASE2). 2케이스(v11/v29) ripple. baseline 37 신규 0.

## 절대 하지 말 것 (2시간 날린 함정들)
- ❌ `profile_phase1_v126.py` 사용 금지(옛 v126 datasynth용, profiler — 측정 도구 아님).
- ❌ `run_phase_analysis()` (Streamlit 서비스 래퍼) — full에서 hang.
- ❌ units 포함 `build_phase1_case_result()` full 실행 — **15분+/9.8GB**(새 unit/flow 빌드가 튜닝 안 됨). catch/miss엔 불필요.
- ❌ full(98만행) 무한 실행. 고친 뒤 detector-only ~4분 1회만.
- ❌ 한글 파일 PowerShell round-trip(인코딩 훅이 차단) — apply_patch 또는 ASCII-only 신규 파일만.
- ❌ raw data dir 직접 read(훅 차단) — 코드/리포트/metadata로 진단.

## 측정 방식 (확정)
- **catch/miss는 detector-only**(`measure_phase1_detector_catch.py`, ~4분). units/case빌드 안 거침.
- **등수(ranking)는 이번 범위 제외**(units/scoring 필요, 느린 빌드). 나중에 unit빌드 perf 잡고.
- catch = 룰 detector가 truth 전표/흐름에 details>0 발화. miss = 안 함 → PHASE2 타깃.

## 데이터셋
- **정상 baseline (최종): `data/journal/primary/datasynth_semantic_v1_normal_20260607_v29`** — 완료.
  회계·재무제표(TB/roll-forward/subledger)·IC·순환·역분개링크·semantic·참조고유·노이즈·SoD제거까지 clean. realism gate 29 PASS.
- overlay: `..._p3_2_overlay_20260607_v11` — **backfill 버그로 깨짐.** v12로 고쳐 재생성 필요.
- evasion 주입 설계도: `dev/active/phase1-evasion-injection-spec.md` (39룰 표준+evasion, 7 suppress 정조준).

## 전체 진행 지도
```
P0 문서폴더(guide/spec/archive)     ✅
P1 단위측정정책(docs/spec/UNIT_MEASUREMENT_POLICY.md) ✅  전표/흐름=정답, row=증거, case=표시뷰, disjoint
P2 phase1 단위통일                   진행
  P2-1 unit 모델                     ✅
  P2-2 document adapter (confirmed-only) ✅  (L3-12/L4-05/L4-06→review-population)
  P2-3 flow 빌더 (L2-02/03/05·IC·GR, R1흡수, unmatched-IC→review) ✅
  P2-4 점수→unit (case=derived, L2-05 low cap) ✅ (full v29 derived 0)
  P2-5/6/7 (compat/UI/test)          ⬜
P3-1 정상데이터 v29                  ✅
P3-2 룰위반 주입→phase1 검증          진행 ← overlay backfill 버그 고치는 중
P3-3 실제 감리 false→phase1→PHASE2 타깃 ⬜
P4 PHASE2 재설계                     ⬜ (최종 목적지)
```

## 핵심 lock/결정 (dev/active/phase1-unit-unification/phase1-unit-unification-plan.md)
- D1~D8, R1(라벨프리 흡수+측정시점 catalog), R2(cap→complete), 점수=triage(부정확률 아님)·corroboration per-unit.
- 전역 §9에 hollow-PASS차단·검사강화·회귀baseline 추가됨. §10 전수측정.
- 방법론 문서: docs/guide/개발방법론.md (포트폴리오용 6단계).

## FN(2종오류) 핵심 — 사용자가 강조
- 우리가 FP만 줄였다(suppress/drop). **부정이 그걸 흉내내면 미탐.** evasion spec이 그걸 측정하게 설계됨.
- P3-2 측정 = 표준위반 catch + evasion miss(→PHASE2). 이게 FN 실측.

## 추적(낮은 우선순위)
- unit/flow 빌드 perf(15분+/9.8GB) — 측정 끝나고 따로 profile해서 O(n²)/메모리 잡기.
- stale 테스트 2개(rule count 67→70, priority_band 0.75→0.90) SoT 갱신.
- L2-05 정상역분개 구조링크(P3-3 전), O2 스캔확장, R2R_CLOSING taxonomy.
- baseline 37 known-fail(전부 옛 truth CSV 부재 등, 우리 변경 무관).
