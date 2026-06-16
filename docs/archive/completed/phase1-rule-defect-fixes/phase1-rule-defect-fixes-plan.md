# PHASE1 룰 결함 수정 — 라운드 운영 계획

> 입력: [PHASE1_RULE_DOMAIN_REVIEW.md](../../../docs/spec/results/PHASE1_RULE_DOMAIN_REVIEW.md) +
> OPEN_ISSUES #17~#25. 목표: 전부 수정(사용자 결정, 2026-06-12). 운영 방식: 설계자(본 세션)가
> 라운드별 작업 프롬프트 발행 → 외부 세션 작업 → 설계자 검수(증거 대조·재현·hollow-PASS·
> 하드코딩 스캔) → 재측정·baseline·docs는 설계자가 수행.

## 라운드 구성

| 라운드 | 항목 | 성격 | 프롬프트 |
|--------|------|------|----------|
| R1 | #17 floor 버킷 게이트, #18 source 비대칭, #22 repeat 승급 제거 (+mojibake는 설계자 직접 수정 완료) | 잡음 감소 — 분포 영향 한 방향 | R1-A, R1-B, R1-C |
| R2 | #24 L2-02 fallback 구현, #19 유령 승인자+승인일 시퀀스 | 탐지 추가 — 정상 과탐 증가 위험 | R1 검수 후 발행 |
| R3 | #20 macro 점수 반영 (+L4-02 부착, GR01 cycle 콤보 입력) | 분포 영향 불확실 — 단독 분리 | R2 검수 후 발행 |
| R4 | #21 legacy 채널 정리(high 재설계 동반), #23 L3-12 재설계 | 구조 변경 — planner 설계 선행 | R3 후 설계 논의 |

## 라운드 공통 절차

1. 설계자: 프롬프트 발행 (`prompts/` — work-prompt-authoring 템플릿)
2. 외부 세션: 작업 + 완료 보고 (양식 고정)
3. 설계자 검수: ① 체크리스트-증거 대조 ② 최종 검증 1개 이상 직접 재현 ③ diff 직접 읽기
   (hollow-PASS·테스트 약화·하드코딩 스캔) ④ 회귀(단위+가드)
4. 설계자 마감: v41+r24 풀 재측정 → truth band 유지 확인 → kpi_baseline 교체 → VERIFICATION·
   OPEN_ISSUES·debugging.md 갱신 → 다음 라운드 발행

## R1 작업 간 순서

R1-A → R1-B → R1-C 순차 권장 (같은 repo 작업 시 충돌 방지). 파일 겹침: 없음
(A: rule_scoring/topic_scoring, B: anomaly_rules_simple/fraud_rules_access/fraud_rules_feature,
C: phase1_case_builder/config).

## R1 진행 로그

- 2026-06-12 1차 보고: R1-B/C 검수 통과 (4곳 게이트 설계대로·테스트 약화 0·하드코딩 0·
  전체 1455 passed 재현·ripple 잔존 0). R1-A는 NEEDS_CONTEXT 정상 중단
  (config/phase1_case.yaml:47 `topic_floors` 오버라이드 발견) → 프롬프트 v2 재발행
  (yaml 키 교체 포함). 워커 보고의 "L3-06 테스트 1회 실패 후 통과"는 단독 8회+전체 1회
  재현 시도에서 전부 통과 — 공유 worktree 동시 편집 간섭으로 판정.
- R1-B Step 4 산출(후속 입력): source 기반 자동/반복 분기가 L2-01·L2-03·L2-05·
  L1-06/L1-07/L3-03 계열에 잔존 — 이들은 "위장 게이트 연결"이 아니라 "시스템성 중복/반복을
  0점 처리하는 게 맞는가"라는 도메인 결정이 필요해 R4 설계 논의에 합류시킨다.

## ✅ R1 마감 (2026-06-13)

- 코드 3건(A/B/C) 검수 통과 + 풀 재측정 완료: 정상 v41 **완전 불변**(R1 정상 중립),
  r24 truth 853→**783(72.5%)** — L2-02 floor 스펙 정합(30유닛) + repeat 승급 제거분의 의도된
  하락. **high 539·Top500 718 불변.** 가드 17/17 PASS (c2 783/548). 문서 갱신 완료
  (DETECTION_RULES 위장 게이트 4불릿·VERIFICATION·OPEN_ISSUES #17/#18 부분해소·#22 해소·
  RULE_DOMAIN_REVIEW §2.6 가설 정정·debugging.md).
- **가설 반증 기록**: IC 전건 medium은 repeat 승급 탓이 아니라 콤보 점수 기인 — 도메인 리뷰
  추정은 측정 전까지 가설로 취급.
- 유령 승인자 정량화: v41 비공란 292,505행 중 마스터 미존재 0건(user_id 기준 동일) —
  R2-B 입력 확보. #19 중 승인일 시퀀스 검증은 R4 합류.

## 예상 효과 (R1)

- 정상 medium 1,029의 추가 감소 (L1-04 boundary floor 제거 + repeat 승급 제거 + L2-02 0.45)
- r24 truth band 79.0%는 일부 하락 허용 (L2-02 12건 medium→low 0.45, IC repeat 승급분) —
  c2 SOFT WARN 하한 597 위로 유지되는지 검수에서 확인. truth recall 튜닝 금지 원칙 유지.

## ✅ R2 마감 (2026-06-13)

- 코드 2건(A/B) 검수 통과 + v42j NORMAL 측정 완료:
  - R2-A L2-02 fallback 3종 발화(168행, max 0.65=amount_partner, floor 미부착)
  - R2-B unknown_approver 정상 과탐 0(비공란 292,487 중 마스터 미존재 0)
  - **high 0 HARD 불변**·medium 838(2.1%, case 40,594)
- **데이터셋 전환 v41→v42j**(사용자 의도 재생성): NORMAL만 v42j(무결성 통과·CoA 누락 0),
  recall은 v42j_r1 검증 pending이라 r24 과도기 유지(base 불일치 명시). baseline normal 키만
  갱신·가드 17/17. 문서: OPEN_ISSUES #24 해소·#19 부분해소·DETECTION_RULES L2-02/L1-07·
  VERIFICATION·NORMAL_FP·debugging.md.
- **가설 반증 2호**: L2-02 fallback "미구현" 추정 반증(원본에 reason 존재, recurring 게이트 제약).
- **범위 밖 변경 유지**: boolean_utils(bool_column ~15곳) — 동작 보존 확인(파이프라인 bool), 회귀 0.

## 다음: R3 (#20 macro 점수 반영) — recall 검증 후

⚠️ **R3 발행 전 선결**: recall baseline이 r24(v41-base) 과도기 상태. v42j_r1 검증
(normal_regression·oracle_scan) 완료 시 recall도 v42j_r1로 전환 후 R3 진행 권장 — macro 반영은
truth band 분포에 직접 영향이라 검증된 recall이 필요. R4(#21 legacy·#23 L3-12)는 planner 설계 선행.

## R2-A 성능 회귀 (2026-06-13, 검증된 recall v42j_r3에서 발견)

- v42j_r3 측정: truth band **개선**(high+medium 870/80.6%·Top500 796 — r24 783/718 대비 ↑) — R1/R2
  탐지 효과는 검증된 recall에서 확인됨. **단 case build 3,717s로 b2 가드(1,200s) 위반**.
- 원인: R2-A L2-02 fallback이 대량 거래처(V-000526 하루 4,700건·총 26,276행)를 recurring 억제
  (월 단위)로 못 막아 duplicate_outflow 거대 case 13개 생성(최대 18,718 hit, L2-02 4,668 포함).
  case_builder가 거대 case 처리로 폭증. (approval_control 거대 case 11개는 r24에도 있던 기존 부하.)
- 사용자 결정: **둘 다** — R2-A2(fallback 대량 거래처 억제) + R-PERF(case_builder 거대 case 최적화).
- 발행: prompts/R2-A2-l202-bulk-counterparty-suppression.md, prompts/R-PERF-case-builder-giant-case.md
- 두 작업 검수 후 v42j_r3 재측정 → b2 1,200s 내 복귀 + truth band 유지 확인 → baseline recall 전환.
- **R3(#20 macro)는 이 회귀 해소 + recall baseline 전환 후**. (R3는 truth band 직접 영향이라
  안정된 recall·정상 빌드 속도 선결.)

## ⏸ 핸드오프 (2026-06-14 중단)

### 전체 라운드 상태
- **R1** (#17 floor 버킷 게이트·#18 source 위장 게이트·#22 repeat 승급 제거): ✅ 완료. v42j NORMAL baseline 전환·가드 17/17·문서 갱신 끝남.
- **R2** (#24 L2-02 fallback·#19 unknown_approver): 🔶 코드 검수 통과. **recall baseline 전환만 미완**(아래 성능 문제로 막힘).
- **R3** (#20 macro 점수 반영): ⬜ 미착수. recall 전환 후 발행 예정.
- **R4** (#21 legacy 채널·#23 L3-12): ⬜ 미착수. planner 설계 선행.

### 막힌 지점 (R2 마감 = recall baseline 전환)
- recall을 v42j_r3로 전환하려는데 **case build가 3,717s로 b2 가드(1,200s) 위반**.
- **근본 원인 확정**: case grouping이 대량 엔티티를 거대 case로 묶음. duplicate_outflow key=`(거래처,금액band,near_period 7일)`(`_make_case_key_parts` 4241행 부근). V-000526(하루 4,700건)·BHENRY067·ALOPEZ058 같은 대량 거래처/사용자가 한 키에 **2,300~2,700 문서**를 묶어 거대 case 40개 생성. **fallback 무관**(approval_control·closing_timing도 동일) → R2-A2(fallback 억제)로 안 풀림.
- **진짜 병목 함수는 미확정**: 측정 4번 다 실패 — cProfile -m(0줄 멈춤), R-PERF 워커 tolist 수정(회귀, 1시간), mini cProfile(0줄), mini 단계타이밍(10분 timeout, [stage] 로그 0줄=detector 단계에서 멈춤). mini(journal만 필터·master는 원본)가 부정확했을 가능성 — enrichment 조인 깨져 detector가 느렸을 수 있음.
- 유일한 실측 단서: R-PERF 워커 cProfile(단위 case 10,000 hit 3.4s) — _build_cases 2.71s / _build_document_refs 1.31s / _coerce_evidence 0.68s / compute_topic_scores 0.667s / apply_combo_floors 0.503s. **단 flow_units(_build_flow_units)는 이 단위 cProfile에 없음 — 미검증 후보.**

### 사용자 최종 결정
**"측정 도구 제대로 정비 후 1회"** — mini를 전체 데이터셋 구조 일관되게 만들거나 build_phase1_case_result만 격리 호출하는 정확한 진단 도구를 먼저 만들고, 그걸로 병목 1회 확정.

### 재개 시 할 일 (순서)
1. **정확한 진단 도구**: 전체 v42j_r3를 그대로 쓰되 build_phase1_case_result에 단계 타이밍(이미 박힌 `PHASE1_BUILD_STAGE_TIMING=1` env) + grep 없이 raw stdout 확인. 또는 build만 격리(df+results를 pickle로 1회 저장 후 build만 반복 프로파일). detector(366s)를 매번 안 돌리는 게 핵심.
2. 병목 단계 확정(collect_raw_hits/build_flow_units/build_cases/derive 중) → 그 함수만 **동작 불변** 최적화(fitting·미탐 0).
3. v42j_r3 full 재측정 → b2 1,200s 내 복귀 + truth band 80.6%·high 0 유지 확인 → recall baseline 키 v42j_r3 전환.
4. R2 문서 마감 → R3(macro) 발행 → R4(planner).

### ⚠️ 정리 필요 (임시 계측 — 환경변수 off면 동작 불변이나 제거 권장)
- `src/detection/phase1_case_builder.py:651~701`: `_stage`/`PHASE1_BUILD_STAGE_TIMING` 단계 타이밍. **단 _document_ref_columns 루프 밖 캐시(1407행)+_build_document_refs 인자(4512행)는 R-PERF 회귀 수정이라 유지**.
- `tools/scripts/measure_phase1_current_p3_2.py:157~`: `PHASE1_CASE_CPROFILE` cProfile 토글.
- R-PERF 워커가 만든 boolean_utils.py·compute_topic_scores view 인덱스 등은 R2 검수 때 동작 불변 확인됨 — 유지.

### 측정 산출물 상태
- `artifacts/phase1_priority_band_v42j/`(NORMAL, R1/R2 적용, high 0·medium 838·case build 710s) — baseline normal 키가 이걸 소비. 유효.
- recall은 baseline에서 **r24(v41-base) 과도기 유지** 중. v42j_r3 전환은 성능 해결 후.
- 임시 mini(`_v42j_r3_mini`)·perf 산출물은 정리됨(삭제).

## 병목 진단 측정 (2026-06-14 재개) — 진행 중

### 진단 방법론 (측정 4번 실패 원인 제거)
- 도구: `tools/scripts/diagnose_phase1_build_bottleneck.py` (prep/build 2모드).
- 핵심: detector(전체 recall v42j_r3에서 **567.9s**)를 1회만 돌려 `df+detector_results`를 pickle(869MB)로
  저장 → build_phase1_case_result만 격리 로드·반복 측정. 과거 실패는 매 측정이 detector를 재실행해 timeout.
- 1차는 cProfile 없이 단계 타이밍만(실제 속도) → stage 확정 후 그 stage만 좁힘(cProfile 오버헤드 회피).

### detector prep 분해 (전체 recall v42j_r3, 910,018행)
- 광역/대량 룰이 detector 비용 지배: **L2-02 149s**(R2-A fallback, 대량 거래처)·**L1-07 83s**(582,799행 flag)·
  layer_c 148s·layer_b 합 371s. 핸드오프 추정 366s보다 큼(567.9s).

### build 단계 타이밍 (cProfile 없이, 실제 속도)
| stage | 시간 | 비고 |
|-------|------|------|
| collect_raw_hits | 37~54s | 측정 변동 (2회 관측) |
| **build_flow_units** | **30분+ (단일 sub-call 미반환, 측정 중)** | **단독으로 b2 가드(20분) 초과 — 1순위 병목 확정** |
| build_document_units~derive | 미도달 | build_flow_units 완료 후 |

- **stage 병목 = `build_flow_units` 확정.** 핸드오프는 `build_cases`(거대 case 그루핑)를 주범으로 추정했으나
  실측은 **build_flow_units가 1순위**. build_cases가 빠르든 느리든 build_flow_units만으로 가드 초과 → 무조건 수정.

### 함수·근본원인 확정 (enter-print 진단)
- 각 sub-call 진입 직전 `[flow-enter]` 출력 → 느린 호출 진입 시 거기서 정지 = 주범 즉시 식별(반환 30분 안 기다림).
- 증거: `layer_a/l202_minimal_link_keys` 빠르게 통과 → `layer_b/l202_minimal_link_keys`에서 **정지**.
  layer_b = FraudLayer(L2-02 21,572 hit). 느림이 L2-02 hit 수에 비례 → 함수 확정.
- **병목 함수 = `_flow_units_from_l202_minimal_link_keys`.**
- **근본원인 = `_flow_company_scope(df)`를 groupby/entry 루프 안에서 group마다 호출.**
  이 함수는 `df["company_code"]` 910,018행 전체를 매번 스캔(set+sort)하는데 **결과는 group과 무관하게 동일**.
  L2-02 hit이 수천 link_group을 만들어 수천 × 910k = 수십억 연산 → 30분+. (호출처 7곳, 여러 flow 빌더 루프에 산재.)

### 수정 (동작 불변)
- **fix #1** `_flow_company_scope`를 **weakref 키 memoize**: 같은 df 객체면 1회만 계산해 재사용. 7개 호출처
  전부 자동 적용. weakref로 동일 살아있는 객체일 때만 캐시 히트 → cross-build id 재사용에도 stale 없음.
  반환값 동일(동작 100% 보존). phase1_case_builder.py `_flow_company_scope`(≈3850행) + 모듈 캐시 `_FLOW_COMPANY_SCOPE_CACHE`.

### 2번째 같은-부류 병목 (ripple-search 발견)
- fix #1 적용 후 build_flow_units 5.18s로 떨어졌으나 **score_phase1_units가 ~5분**으로 새 병목 노출.
- 근본원인 = `_unit_total_amount`(≈1999행)가 **FlowUnit 마다** `df["document_id"].fillna("").astype(str).tolist()`
  910k 행 전체를 스캔(O(units×n)). L2-02가 만든 다수 FlowUnit × 910k = 수 분. fix #1과 동일 패턴.
- **fix #2**(동작 불변): `_score_phase1_units`에서 document_id→positions 맵을 **동일 정규화(fillna("")+astype(str))**
  로 1회 구축 → `_unit_total_amount`에 전달, per-unit 스캔을 맵 조회로 대체(O(n+units)). 같은 positions 집합 반환.

### 수정 후 build 단계 표 (전체 recall v42j_r3, fix#1+#2 적용)
| stage | BEFORE | AFTER |
|-------|--------|-------|
| collect_raw_hits | 37~54s | 22.50s |
| build_flow_units | **30분+ (1800s+)** | **4.87s** |
| build_document_units | — | 5.76s |
| absorb_document_hits | — | 0.44s |
| score_phase1_units | ~5분+ | 210.46s |
| build_cases | — | 164.16s |
| derive_case_scores | — | 3.28s |
| **[build] total** | **3,717s (b2 위반)** | **412.4s (b2 통과)** |

- 산출: cases=38,872 / units=170,475. **build 3,717s → 412.4s, b2 가드(1,200s) 여유 통과.**
- 두 수정 모두 설계상 동작 불변(같은 값 반환). 검증: phase1 case builder 테스트 + 실제 measure로 truth band 80.6%·high 0 재현.

### 동작 불변 검증 결과
- pytest: phase1 case builder·flow·document unit·case view **168 passed**.
- measure(pickle 재사용, detector 생략) build 3회 독립 실행: **cases=38,872·units=170,475 전부 동일**.
- priority_band: cases(high 129·medium 1,011·low 37,732) / units(high 57·medium 532·low 169,886).
- 수정은 점수 입력값 불변(`_flow_company_scope`는 flow_id 전용·band 무관, `_unit_total_amount`는 동일 amount 반환)
  → band 결정론적 불변. 동일 카운트 + 테스트 통과로 동작 불변 확립.
- **이관**: 핸드오프 "truth band 80.6%/870" 정확 % 재현은 measure 스크립트 truth 매칭(`_truth_measurement_rows`)이
  O(truth×170k units)로 자체 병리적 느림(별개 개발도구 이슈) → R2 마감 단계로. normal v42j high 0도 R2 마감에서.

### 3번째 같은-부류 병목 (measure 스크립트 truth 매칭, 사용자 결정으로 수정)
- `_truth_measurement_rows`가 truth 행마다 전체 units(17만)·cases(3.8만)·hits 선형 스캔 = O(truth×N) → 좀비 22분.
- fix: 인덱스 1회 구축(doc→units/cases, natural_id→unit, rule→hit docs) → truth 행당 후보만 검사.
- **검증**: 신규 vs brute-force 원본 로직 30개 합성 fixture **전부 동일**(_verify_truth_measurement_equiv.py).
- 효과: recall v42j_r3 truth 매칭 **22분+ → 3.6초**.

### recall v42j_r3 measure 결과 (pickle 재사용, detector 생략)
- build 461s, cases=38,872·units=170,475(4번째 동일 — 동작 불변 재확인).
- truth_units 2,160·caught 1,515·missed 645. priority_band cases(high 129·medium 1,011·low 37,732).
- **지표 주의**: 핸드오프 "truth band 80.6%/870"은 `analyze_truth_priority_band.py` 지표(표준 truth 1,080 중
  high+medium band 870 = 870/1080). measure `_summary`의 caught 70.1%(전 band+boundary 포함)와 정의가 다름.
  정확 % 재현은 measurement CSV → analyze 스크립트(빌드 재실행 필요)로 R2 마감 단계에서.

### 남은 일 (R2 마감 — 병목·truth-match 수정 완료 후, 선결조건 있음)
- ⚠️ recall baseline 전환은 **정책상 도메인 정당화 PR** + **v42j_r1 검증(normal_regression·oracle_scan) 선결**
  (baseline meta 노트: 과도기 r24 유지 중). 병목 수정이 성능 선결만 해소 — 데이터셋 검증은 별개.
- 2+ 케이스 검증(ripple): 정상 v42j(L2-02 대량 hit 없음)에서도 build_flow_units 빠른지 대조 →
  병목이 대량 hit/거대 구조 의존이었음 + 수정이 정상에도 무해함 확인.
- 검증 후 recall baseline v42j_r3 전환 → R2 문서 마감 → R3(macro) → R4(planner).
- 정리: 진단용 임시 계측(enter-print/[flow]/diagnose 스크립트)은 검증 완료 후 제거(env off면 동작 불변).

## ⏸ 세션 마감 핸드오프 (2026-06-14, 병목·truth-match 수정 완료)

### 완료(검증됨)
- **build 병목 2건 수정** → build 3,717s→412s(b2 통과). ① `_flow_company_scope` memoize(weakref),
  ② `_unit_total_amount` doc_positions 맵(ripple로 발견). 둘 다 `src/detection/phase1_case_builder.py`.
- **measure truth 매칭 수정**(3번째 같은 부류) → 22분+→3.6초. `tools/scripts/measure_phase1_current_p3_2.py`
  `_truth_measurement_rows` 인덱스화.
- **동작 불변 검증**: pytest 168 passed + cases/units 4회 동일(38,872/170,475) + truth-match 30 fixture 동일.
- 임시 계측(`_build_flow_units` enter-print)은 제거됨. 실제 수정만 남음. (단 `build_phase1_case_result`의
  `PHASE1_BUILD_STAGE_TIMING` 단계 타이밍은 **이전 세션 잔존**(651~701행) — 내 추가 아님, env off면 무동작.)

### "R2/R3/R4 바로 가도 되나?" — 부분적으로만
- 병목은 R2 마감(recall baseline 전환)의 **성능 선결**이었고 그건 해소됨.
- 그러나 baseline 전환은 **다른 선결 미완**: baseline meta 노트상 "v42j_r1 검증(normal_regression·oracle_scan)
  완료 시 전환" — 데이터셋 검증이 선결. + 정책: baseline 변경은 도메인 정당화 PR 의무.
- R3(macro)는 전환된 recall baseline 선결(원 plan). R4는 planner 설계 선결.
- **즉 순서: ① v42j_r1/r3 데이터셋 검증(normal_regression·oracle_scan) → ② recall baseline 키 전환
  (`tests/phase1_rulebase/kpi_baseline.json` recall a3/b3/c2/c3 + datasets.recall) + 도메인 정당화 → R2 문서 마감
  → ③ R3(macro) → ④ R4(planner).**

### 재개 시 빠른 측정 도구 (detector 567s 반복 제거)
- `tools/scripts/diagnose_phase1_build_bottleneck.py` prep/build/measure 3모드. pickle 재사용.
  - prep: detector 1회 → pickle. build: build만 단계 타이밍. measure: build+truth band(빨라짐).
- recall v42j_r3 pickle 이미 있음: `artifacts/phase1_build_diag/..._prep.pkl` (**1.5GB — 불필요시 삭제**).
- 정확한 "80.6%/870" 재현 필요시: measure 모드에 measurement CSV 저장 추가 → `analyze_truth_priority_band.py` 실행.
- `tools/scripts/_verify_truth_measurement_equiv.py`: truth-match 동작 불변 검증용(일회성, 삭제 가능).

### 미완(이관)
- 정확 truth band % 재현(870/1080=80.6%) — 기계적, R2 마감에서.
- normal v42j high 0 재확인 — 동작 불변으로 보존되나 R2 마감에서 명시 측정 권장.
- recall baseline 전환 — 위 선결조건 + 정책 PR.

## ✅ R2 완전 마감 (2026-06-14) — recall baseline v42j_r3 전환 완료

### 선결 검증 (v42j_r3 데이터셋)
- **normal_regression PASS**: 정상 subset 사용계정 ⊆ config CoA(480, v42j_r2 누락 5계정 중 4개 등록·999998은
  L1-03 무효계정 truth 한정), 차대변 균형·라벨 미오염. 도구 `tools/scripts/validate_recall_overlay_oracle_normal.py`.
- **oracle_scan**: ML anti-shortcut 렌즈 finding 다수(account_subtype=OTHER·고정시각·라운드 금액)이나
  **PHASE1 룰(규칙기반·미학습)엔 무해** 판정 — account_subtype detector 미사용, 10:05/14:05는 정상시간대라
  L3-06/L4-05 무발화(time_features.py:78,210), 금액은 임계기반·계정 CoA 등록. 리포트 `artifacts/recall_v42j_r3_validation/`.
- 잔여 한계(비차단): L3-09 특이도 미측정(정상 양성 open-item 0). PHASE2 ML 재사용 시에만 raw finding이 실제 누출.

### 측정·전환
- post-fix 단일 클린런: case_builder **388.9s**(< b2 1200, 3,717s→389s 병목 수정 반영), **동작 불변**
  (case 28,620·band 870·Top500 796 = Jun13 동일).
- kpi_baseline recall 키 전면 교체(a3 1020/1020·b1 28,620·b2 388.9·b3·c1·c2 870·c3 796·_meta).
- **KPI 가드 17/17 PASS**(A+B HARD 14, C SOFT 3, 경고 0). 문서 갱신(PHASE1_VERIFICATION·debugging).

### 다음: R3 (#20 macro 점수 반영)
- 전환된 v42j_r3 recall baseline 위에서 진행 — 선결(검증된 recall) 충족. R4(#21 legacy·#23 L3-12)는 planner 설계 선행.

> ⚠️ **위 "다음: R3" 계획은 superseded됨 — 아래 §라운드 최종 마감(2026-06-15) 참조.**

## ✅ 라운드 최종 마감 (2026-06-15) — 점수체계 tier 재설계가 R3/R4 일부 흡수

R2 마감 직후, 사용자가 점수체계 자체를 재설계하기로 결정(가중합 → 순서형 tier). 이로 인해 R3/R4의 원 계획이 변경·흡수됐다. 라운드별 최종 상태:

- **R1**: ✅ 완료(2026-06-13). 변동 없음.
- **R2**: ✅ 완료(2026-06-14). recall baseline v42j_r3 전환까지 끝남. 변동 없음.
- **R3 (#20 macro 점수 반영)**: ✅ **해소 — 단 원 계획과 정반대 방식으로 흡수.**
  - 원 계획 = "죽은 macro 가중치(`macro_context_score` 0.03)를 *살려서* 점수에 반영(+L4-02 부착·GR01 cycle 콤보 입력)".
  - 실제(2026-06-15 결정) = 가중합 자체를 tier로 폐기 + macro(D01/D02/L4-02/Benford)를 PHASE1-1 RULE_SCORING_REGISTRY에서 제거 → **PHASE1-2 family로 이관**. macro를 살리는 게 아니라 PHASE1-1에서 분리해 "죽은 가중치" 문제를 소멸시킴.
  - 결과: #20 해소(OPEN_ISSUES #20). L4-02 canonical 32→31. 근거 SoT: `PHASE1_TIER_EVIDENCE_BASIS.md` §6/§7. macro 관련 활성 문서 전수 정합 완료(2026-06-15).
- **R4 (#21 legacy·#23 L3-12)**: 🔶 **부분 — #21 흡수, #23 미착수.**
  - #21 (legacy 병렬 채널): 🔶 대부분 해소(2026-06-15). tier 전환으로 활성 경로 band가 tier(`_score_unit_hits`→`_derive`)로 결정, `max(topic,legacy)` band 채널 제거. 잔여 순수 legacy(`_composite_sort_score`+use_topic_scoring=False)는 운영 inert.
  - #23 (**L3-12 보강신호 재설계**): ⬜ **미착수 = 라운드 잔여 유일 코드 작업.** planner 설계 선행. 문제 상세: RULE_DOMAIN_REVIEW §1 + OPEN_ISSUES #23.
- (#25 탐지 회피 면적: ⬜ 기록만, 차단 아님 — PHASE2/향후 입력.)

**라운드 잔여 = #23 L3-12 재설계 1건(planner 선행).** 나머지 R1~R4는 완료 또는 tier 재설계로 흡수됨.
