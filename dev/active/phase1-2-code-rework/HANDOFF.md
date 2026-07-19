# HANDOFF — PHASE1-2 코드 재작업

갱신 2026-07-15(구 2026-06-30 "코딩 미착수" 판은 폐기). 계획: [PLAN.md](PLAN.md). 실측 근거 전량: [backend_verify.md](backend_verify.md).
설계 SoT: [DETECTION_RULES_PHASE1-2.MD](../../../docs/spec/DETECTION_RULES_PHASE1-2.MD).

## 현황 한 줄

**백엔드 완료, UI 미착수.** 자기 큐 6종 → **5종**(시계열 폐기), 배지 통합·거래처 자기 큐·라운드넘버 밀집도 배선 완료. 화면(PLAN §3 Phase 5·6)은 사용자 지시로 범위 외.

## 완료

| 항목                     | 구현                                                                   | 실측                                                 |
| ------------------------ | ---------------------------------------------------------------------- | ---------------------------------------------------- |
| Phase 0 baseline         | [baseline.md](baseline.md)                                             | phase1_rulebase 25 passed                            |
| Phase 1 단일 회사 스코프 | **입구 가드로 대체** `pipeline.py::single_company_scope_warnings`      | 다회사 3사 → 경고 1건 / 단일회사 → 0건               |
| Phase 2 레거시 정리      | relational(R01~R09)·IC01~03·duplicate·graph 삭제(커밋 5d16525·aaf0390) | —                                                    |
| Phase 3 첫등장/희소      | `partner_signals.py` + `_build_partner_findings` → `partner_findings`  | 거래처 2,966 → 신호 625(첫등장 568·희소 596·휴면 22) |
| Phase 4 배지 통합        | `_compose_badge_tags` → `badge_tags`(`phase1_case.py:56`)              | —                                                    |
| 라운드넘버 밀집도        | `round_density_rules.py`(축별 이항검정) → `macro_findings`             | 정상 finding 1건 vs fraud 3건                        |
| is_round_number 정의교체 | 절대 `round_unit` → 상대(유효숫자 ≤2·자릿수 ≥3)                        | 0.037% → 5.52%, 소비처 5/5, **등급 영향 0**          |
| 큐 절단 제거             | `macro_findings`·`partner_findings` top_n 제거                         | 회귀 1,703 passed / 0 failed                         |

## 폐기 (실측 근거 있음)

- **시계열 당기내 집중 자기 큐** — 당기 내 baseline 이 결산 캘린더를 재발견(정상 864건·분기말 70% → 레인 분리 후 595건·52.4%). 연말은 한 해 1회라 당기 내 판정 원리적 불가. "작년 같은 달 비교"는 D02 중복. → **D02 드릴다운으로 재정의(미구현)**. 코드·테스트 9건 보존, 배선 제거. DataSynth 아티팩트 **아님**(Rust 수정 대상 아님).
- **Phase 1 회사별 실행 후 병합** — 데이터 14/15 가 이미 단일 회사 → 입구 가드로 대체.

## 다음 (우선순위 순)

1. **D02 드릴다운 구현** — D02 가 "이 계정 월분포가 바뀌었다"를 띄우면 어느 달이 작년 같은 달 대비 몇 배인지 상세 표시. 새 룰 아님(D02 상세정보). `timeseries_concentration_rules.py` 의 robust-z 자산 재사용 가능.
2. **UI**(PLAN §3 Phase 5·6) — 자기 큐 5종 화면 + 배지 컬럼. 백엔드는 준비됨(`build_phase1_macro_finding_queue`·`build_phase1_partner_finding_queue`, `badge_tags`).

## 미해결 (본 작업 범위 밖, 기록만)

- `fraud_rules_groupby.py:355 _flag_o2c_offset_duplicate_entries` — L2-03 헬퍼 중 유일하게 `company_code` 를 groupby 키에 포함하나 호출처 0건인 죽은 코드.
- `tests/datasynth_quality_gate/checks/tier5_label.py:105` — 기존 인코딩 손상(U+FFFD 6개, HEAD 에도 존재).
- `tests/modules/test_db/test_batch_reader.py::TestDetectorStatuses::test_restored_core_tracks_default_to_executed` — `KeyError: 'duplicate'` 기존 실패(HEAD worktree 재현 확인). 커밋 aaf0390 duplicate 제거 잔재.
- `weak_evidence_bonus`·`topside_bonus` — 계산·저장되나 `phase1_case_builder:1820` 에서 tier 대표값이 덮어써 등급 무기여(dead path). `config/phase1_case.yaml` 의 `per_tag_bonus`·`max_bonus`·`topside.*_bonus` 동일.
- `PHASE2_TIMESERIES_ROLE_LOCK.md` 위치 — CLAUDE.md 는 `docs/spec/` 를 가리키나 실제는 `docs/archive/completed/`(링크 깨짐, 활성 문서 5곳이 spec 경로 참조). supersede 취소로 lock 은 유효 존속 → 위치 결정 필요(docs-reorg MAPPING §경계 미확정 항목).

## 회귀 가드

각 단계 종료 시 pytest 통과 + "알려진 실패 N, 신규 0". 3-surface 점수 비병합 유지. KPI 3-Layer(CONSTRAINTS.md) Layer A/B HARD 통과.
