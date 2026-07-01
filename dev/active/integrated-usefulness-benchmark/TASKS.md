# 구현 태스크 — 통합 쓸모 벤치마크 (감사 반영판)

설계 SoT: [DESIGN.md](DESIGN.md). 엔진 현황: [ENGINE_AUDIT.md](ENGINE_AUDIT.md). 경로: [GENERATOR_PATH.md](GENERATOR_PATH.md).
방침(2026-06-30 결정): **단계적 제대로신축** — state-aware 기전+2·3층 오라클을 지으되, 상태 안 타는 패턴부터.

## 감사 반영 — 재사용 vs 신축
- **재사용**: 주입 배관(process_entries→serialize) · provenance→header + 자가검증(위반필수) · firewall(라벨 누수 차단) · 1층 SemanticValidator.
- **신축**: 기전 생성(6대 패턴) · 상태 인지(⑥D) · 2·3층 정합 오라클(⑦) · schemes/ 폐기 또는 배선 신설.

## 단계 배정 (패턴 × 상태 의존도)
- **Phase 1 (상태 경량 — 먼저)**: 가공전표/수익통계, 계정분류, 비용자산화. 새 계정·매출·자산을 *만드는* 변이라 기존 잔액 참조 의존이 낮음.
- **Phase 2 (상태 중량 — 후순위)**: 횡령은폐/중복자금유출, 가수금은닉, 승인SoD. 열린 AR/AP·역분개 원전표·clearing 상태 참조 필요(2·3층 오라클 선행).

---

## T0 — 생성기 경로·엔진 감사 ✅ 완료
산출물: GENERATOR_PATH.md, ENGINE_AUDIT.md. (contract 6항목 [x])

## T1 — FSS 474 전수 in-scope + 패턴 spec (rule-blind, freeze) ✅ 완료
- 무엇: 474행 전수 → (a) in-scope 판정, (b) 6대 패턴 분류·빈도, (c) 패턴별 기전 spec, (d) 상태의존도 → Phase1/2 배정.
- 산출물: `INJECTION_POPULATION.md`(474행 대조표) ✅, `pattern_specs/01~06.md` + README ✅, 사람용 [docs/phase1-2realism/01·02] ✅.
- **모집단 동결(2026-06-30)**: in **227** / out **247** / N **474**. 판정=commission(주입 in)/omission(blind-spot out). weak-signal **27**(MEDIUM cutoff∪총액 전수 merge — 의도 라벨 분리 폐기, 음의공간 증명 완료). 경계 이상행 0. 패턴족 Phase1 119 / Phase2 108.
- **6 family spec**: 가공전표(181)·비용자산화(18)·계정분류(23)·횡령은폐(88)·승인SoD(24)·순환거래(13). 각 A/C/D/spec선언위반 + in-scope case ≥2 인용 + rule-blind. family 커버리지 227/227(기타 0).
- 판정원칙 권위화: [docs/spec/CONSTRAINTS.md](../../../docs/spec/CONSTRAINTS.md) §통합 쓸모 벤치마크.
- 완료조건: 474/474 판정 ✅. in 합 = 분해 합 ✅. freeze(탐지참조 0) ✅. spec 4절·인용·rule-blind ✅.

## T2 — 정상 base + 조건부추출 풀
- 무엇: 주입 base(realism 검증본) 확정 + 계정·거래처·승인자·페르소나 공동출현 테이블(B/C 조건부추출).
- 산출물: base 경로 + `cooccurrence_pools.parquet`.
- 완료조건: A값별 공동출현 집합 비어있지 않음(빈 집합이면 주입 불가 명시). FAIL=base에 없는 식별자 형식.

## T3 — 기전 생성 신축 (Phase 1 패턴부터) ✅ 완료 (datasynth 컨텍스트 + 독립검증)
- 무엇: 재사용 배관 위에 기전 기반 변이 신설. Phase1 패턴(가공전표·계정분류·비용자산화) 기전을 T1 spec대로 생성. truth sidecar 출력. Rust.
- **산출물(최종 수령)**: `data/journal/primary/datasynth_integrated_usefulness_phase1_20260701_v1g` + truth sidecar. profile `integrated-usefulness-phase1-overlay`.
- **결과**: Phase1 in-scope 119 × 5 seed = 595 doc(fabricated 415·expense 80·account 100). base=…v47_r7.
- **독립검증(56afde75-verify-phase1.md) 3라운드**: v1e 분포누수 2건(source·batch)→v1f_c 수정; v1f_c에서 내 정합오라클이 시점역전(approval<document 542/595) 적발→v1g 수정. **v1g 재현: 오라클 사고 0·분포누수 0·라벨firewall 0·건수 회귀 0 → ACCEPT.** 소프트 1건(approval-lag 분포)은 T7 전 정리.
- 완료조건: 595/119/패턴 ✅. 라벨 누수 0 ✅. 분포 누수 0 ✅. 정합 사고 0 ✅. ripple(source·batch·temporal) ✅.

## T4 — 정합 2·3층 오라클 신축 ✅ 오라클 완성 / v1f_c 결함 1건 회신
- 무엇: HARD 구조 불변식 7종(INV-BAL/POS/REV/ORIG/TEMPORAL/CLEAR/AR-EXISTS) 검사기. "부정은 substance만 조작, structure는 지킴 → 구조 break=사고".
- 산출물: [COHERENCE_ORACLE_SPEC.md](COHERENCE_ORACLE_SPEC.md), `tools/scripts/verify_injection_coherence.py`(--self-test 포함).
- 검증: self-test 7/7 발화+clean 0(비-hollow). Phase1 v1f_c baseline 실행.
- **발견(오라클이 잡음)**: v1f_c의 approval_date < document_date **542/595 문서**(92.7% fraud vs 1.7% normal) = 코히런스 사고 + 관계형 leak(단일컬럼 스캔이 못 봄). → datasynth 회신: approval≥document 수정 + 이 오라클을 게이트 편입.
- 완료조건: 오라클 self-test PASS ✅. baseline 사고 적시(은폐 없음) ✅.

## T5 — Phase 2 패턴 추가 (상태 중량)
- 무엇: T4 2·3층 오라클 확보 후 횡령/중복자금유출·가수금은닉·승인SoD 기전 추가(열린 AR/AP·역분개 원전표 상태 참조).
- 산출물: Phase2 기전 + truth sidecar.
- 완료조건: T4 통과 + 2+ 패턴 ripple-search. FAIL=상태 비인지 변이.

## T6 — 5벌 시드 생성 + LLM 보완 점검 + firewall 부채
- 무엇: in-scope 사건 전부 위치만 바꿔 5벌(희소 유지). LLM 표본 의미점검→결함 오라클 규칙화. firewall 비대칭 부채(truth 라벨 AST 가드) 보강.
- 산출물: 5개 데이터셋 + `llm_plausibility_sample.md` + AST 가드 테스트.
- 완료조건: 5벌 모두 T4 통과. LLM 발견 결함 규칙화 개수 명시. FAIL=LLM을 게이트로.

## T7 — 채점 harness (scheme×surface 매트릭스)
- 무엇: 5벌에 PHASE1-1·PHASE1-2·PHASE2 각각 실행, surface별 catch(§1⑤)로 매트릭스 + PHASE2 recall@1%(+곡선) + 벌간 안정성.
- 산출물: `benchmark_report.md`.
- 완료조건: 3 surface 비병합, 분모=in-scope scheme 수 명시. FAIL=병합 또는 분모 누락.

## T8 — 합격판정 + blind-spot
- 무엇: 진단 리포트 + 바닥선 게이트("범위 내 scheme ≥1 surface"). 0-surface 목록 + out-of-scope blind-spot 표.
- 산출물: `benchmark_report.md` 합격절 + `blind_spots.md`.
- 완료조건: 범위 내 0-surface=0이면 PASS, 1↑이면 결함 적시(은폐 금지). out-of-scope 게이트 면제.
