# HANDOFF — PHASE1-2 코드 재작업

작성 2026-06-30. 다음 세션 재개용. 상세 계획: `PLAN.md`(같은 폴더). 컨트랙트: `.claude/state/contracts/ad43d23a-...md`.

## 지금까지 (설계·문서 = 완료, 코딩 = 미착수)
PHASE1-2를 grill로 재설계 완료 → 문서 4종 동기화 완료(DETECTION_RULES_PHASE1-2.MD / DETECTION_RULES_PHASE2_ML.md / CONSTRAINTS.md / PHASE2_TIMESERIES_ROLE_LOCK.md). **이제 코딩만 남음.**

## 확정 설계 (PHASE1-2 = 분석적 검토 신호)
- **자기 큐**(별도 목록 화면, 고액/대량 정렬): Benford(L4-02)·D01·D02 + **라운드넘버 밀집도[신규]·첫등장/희소 거래처[신규]·시계열 당기내 집중[신규]**
- **배지**(PHASE1-1 전표 등급 줄 꼬리표, 점수 비병합): L4-05·L4-06·L3-12 + 라운드넘버 단건 + 첫등장/희소 전표
- **dual**: 라운드넘버(밀집도=자기큐/단건=배지), 첫등장/희소(거래처목록=자기큐/전표=배지)
- **완전 삭제**: IC01~03(단일법인 한계)·GR01/GR03(dead)·R02/R04/R06. 단 L3-03 관계사 꼬리표는 PHASE1-1 조합용 잔존
- **PHASE1-1로**: 중복지급=L2-03(매칭 "거래처+금액+근접기간" 확장, fuzzy·split 드롭)
- **PHASE2**: VAE/IF 단독(나머지 family 전부 이동/삭제)
- 단일 법인 확정: 3법인 통합 GL을 회사별로 스코프해야 함(현재 안 됨 = 버그)

## 핵심 코드 실측 (재조사 불필요)
- 활성 base(default scope): IntegrityDetector(L1-01~03)·FraudLayer·AnomalyDetector(11룰)·BenfordDetector(L4-02)·EvidenceDetector(L3-11) — `pipeline.py:1397-1415`. variance(D01/D02)는 optional.
- IC·relational·duplicate·timeseries = **phase2_only 블록에서만** 실행 `pipeline.py:1460-1491`. GR = dead(호출 0).
- 옛 PHASE2 rule-style 4종 끊을 지점 = `pipeline.py:1460-1491` 한 블록(소비처 전부 silent-skip, 안 깨짐).
- **자기 큐 백엔드 이미 존재, 화면만 없음**: `build_phase1_macro_finding_queue`(`phase1_case_view.py:2348`), macro_findings(`phase1_case_builder.py:832-1098`). `tab_phase1.py` 미import.
- **배지 토대 일부 존재**: time_severity(`phase1_case_builder.py:88-95`)+weak_evidence_tags(`:4843-4878`, is_round_number·희소). 통합 배지 컬럼 없음(unit 그리드 `tab_phase1.py:3418-3427`).
- macro 0기여 강제: `rule_scoring.py:38-43`·`score_aggregator.py:251-254`.

## 다음 = 코딩 (PLAN §3 순서)
0. **baseline 고정**: `uv run pytest tests/phase1_rulebase/` 통과수 + case/queue/band 분포 캡처 → `baseline.md`
1. **단일 회사 스코프** ★최우선: `_run_detection` company_code별 실행. 검증=C001 vs C002 분리 결과 다름
2. **레거시 정리**(저위험): phase2 rule-style 블록서 relational/duplicate/IC 제거(timeseries는 PHASE1-2로 재구현 예정), GR·IC 완전 삭제
3. **첫등장/희소** base 신규 구현(거래처 단위, first-seen=전기미등장+당기등장)
4. **배지 통합 필드** + L3-12/L4-06 표시 재분류
5. **자기 큐 UI**(백엔드 재사용) + 6. 한 화면 소분류 + 배지 컬럼
+ 신규 자기큐 구현: 라운드넘버 밀집도(round_amount_score 재활용)·시계열 당기내 집중(robust-z 재활용)

## 회귀 가드
각 Phase 종료 시 pytest 통과 + "알려진 실패 N, 신규 0". 3-surface 점수 비병합 유지. KPI 3-Layer(CONSTRAINTS.md) Layer A/B HARD 통과.
DataSynth 게이트: 시계열·라운드넘버가 정상 데이터 과탐 시 → Rust(DataSynth) 수정(검사기 드롭 아님).
