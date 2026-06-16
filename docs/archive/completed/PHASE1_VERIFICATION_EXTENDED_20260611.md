# PHASE1 검증 신뢰성 확장 점검 (2026-06-11)

> 배경: PHASE1_NORMAL_FP_v31c / PHASE1_RECALL_FP_r23 / PHASE1_VERIFICATION_20260608 3개 검증의
> 신뢰성 평가에서 식별된 4개 잔여 사각(P0-1 위반 우선순위, P0-2 KPI 가드, P1-3 현실 부정 특성화,
> P1-4 룰 활성성)을 실측한 결과. 미해결 이슈 추적: [PHASE1_OPEN_ISSUES.md](PHASE1_OPEN_ISSUES.md).

## 요약

| # | 검사 | 결과 |
|---|------|------|
| P1-4a | 룰 활성성(침묵 비활성) 전수 감사 | ⚠️ 침묵 비활성 룰 11개 (경고 없이 0건) + **L3-11 스펙-구현 갭 발견** (IC/GR/EV 기본 제외는 의도로 확인) |
| P1-4b | L3-11 신규 발화 12,010행 표본 검토 | ✅ 재현 일치·도메인 타당 (검토모집단) |
| P0-1 | r23 위반 truth별 priority band/rank | ✅ 위반 60.3% high/medium 진입, D01/D02 사각 발견, 경계 직접 FP 0 |
| ripple | v32 정상 full 트랙 재측정 | ✅ high/medium case 0 유지 (이슈 8 입증) |
| P0-2 | KPI 가드 baseline 재정의 | ✅ v32-full/r23 기반 재정의, 15/15 PASS·skip 0 |
| P1-3 | r3g scheme별 PHASE1 surface 특성화 | ✅ 14/14 표면화, 8/14 Top500, 잔여 6 scheme = PHASE2 지도 |

---

## P1-4 (a) L3-11 스펙-구현 갭 — 최중요 발견 (재검증으로 정정, 2026-06-11)

> **정정**: 당초 "8룰(L3-11·IC01~03·GR01/03·EV01/03) 제품 미실행 버그"로 보고했으나, 사용자 지적으로
> 재검증한 결과 **IC/GR/EV의 기본 제외는 문서화된 의도**였다. 진짜 갭은 L3-11 하나다.

### 판정 근거

- **DETECTION_RULES.md:306-307 (스펙 SoT)**:
  - "`L3-11`은 구현 위치가 `EvidenceDetector`지만, **기본 실행에서는 `EvidenceDetector(rule_ids=("L3-11",))`로
    cutoff 룰만 실행한다.**"
  - "`DuplicateDetector`, `Intercompany`, `Timeseries`, `Evidence`의 EV01/EV03 확장 룰은 기본 PHASE1
    실행 경로에서 제외한다." → IC01~03·GR01/03·EV01/03 기본 제외는 **의도** (조건부 보조 신호:
    "IntercompanyMatcher 결과가 제공되면" floor 보정, `enable_*` 플래그 기본 False).
- **그러나 L3-11-only 배선(`rule_ids=("L3-11",)`)은 pipeline.py git 전 이력에 존재한 적이 없다.**
  유일한 사용처는 단위 테스트(`test_evidence_detector.py:68`). `config/settings.py:580` 주석도
  "L3-11 cutoff runs by default"라고 선언 — 스펙·주석·단위테스트 3곳이 선언하는 기본 실행이
  제품에 미구현.
- 결과: canonical 32 룰인 **L3-11(매출 컷오프)이 제품 기본 경로에서 한 번도 실행되지 않음.**
  스코어링·case builder·topic seeding(`_TIMING_SEED_RULES`)은 모두 L3-11을 소비할 준비가 돼 있고
  입구만 없다.
- 부수: `_try_evidence/graph/nlp_detection`(pipeline.py:1710/1741/1786)은 53f16ff(2026-04-28) 이후
  호출부가 없는 죽은 코드 — enable 플래그를 켜도 동작하지 않으므로 플래그 의미와 불일치(정리 대상).

### 왜 기존 검증이 못 잡았나 (검증 도구 ≠ 제품)

- r23 리콜 100%(39룰)는 `measure_phase1_detector_catch.py`가 **detector를 직접 인스턴스화**해 측정한
  것이다. 이 도구는 `_run_extra_detectors`로 evidence/graph/intercompany/variance를 보완 실행한다 —
  즉 **검증 도구가 제품보다 많은 룰을 돌렸고**, "룰 코드가 살아있다"는 증명이지 "제품이 그 룰을
  돌린다"는 증명이 아니었다.
- priority band 측정(`measure_phase1_current_p3_2.py`)은 반대로 4트랙만 돌려 **L3-11/IC/GR/D 케이스
  기여가 누락**된 채 측정됐다(아래 (c) 도구 수정).

### 영향

- 감사인이 보는 review queue에 L3-11(컷오프)·IC·GR 신호가 한 번도 표시된 적 없음 (4/28 이후).
- PHASE1_RECALL_FP_r23.md의 "39룰 100%"는 **룰 코드 검증으로는 유효**하나 제품 검증으로는 8룰
  (L3-11·IC01~03·GR01/03·EV01/03 트랙)이 과대표현.

### 처리 (결정 대기)

복원 범위 결정 필요 — (i) L3-11만 base 경로 재배선(설정 주석의 선언 충족), (ii) evidence+graph+
intercompany 전부 default scope 재배선(lock 문서의 sidecar 역할 충족, 실행시간 +α), (iii) 의도적
디스코프로 확정하고 lock/설정 주석/룰 카운트를 일괄 정정. → 사용자 결정 후 반영.

## P1-4 (b) 침묵 비활성(silent inactivity) 룰 전수 감사

전 39룰의 입력 컬럼/조건 의존성을 코드 라인 단위로 감사했다. **필수 입력 부재 시 경고 없이 0건을
반환하는("죽었는지 알 수 없는") 룰 11개**:

| 룰 | 침묵 조건 | 위치 |
|------|---------------------------------------|---------------------------|
| L2-01 | `is_near_threshold` 피처 부재 | fraud_rules_feature.py:97 |
| L3-05 | `is_weekend` 부재 | anomaly_rules_simple.py |
| L3-06 | `is_after_hours` 부재 | anomaly_rules_simple.py |
| L3-07 | `days_backdated` 부재 | anomaly_rules_simple.py |
| L3-08 | `description_quality` 부재 | anomaly_rules_simple.py |
| L3-09 | `is_suspense_account` 부재 | anomaly_rules_simple.py |
| L2-05 | 결측 행 dropna 자동 제외 | anomaly_rules_reversal.py |
| L4-03 | `amount_zscore` 부재 | anomaly_rules_simple.py |
| L4-04 | 표본 < 30 | anomaly_rules_statistical.py |
| L4-06 | `source` 부재 | anomaly_rules_batch.py |
| IC01~03 | 매칭 결과 빈 경우 | intercompany_rules.py |

- FraudLayer 계열(L1-04/05/06/07/09, L3-02/03/10/12, L4-01)·L3-04·L4-02·GR01/03은
  `_missing_inputs`/metadata로 경고함 (양호).
- L3-11도 같은 패턴(`evidence_rules.py:161` — delivery_date/posting_date 부재 시 침묵 0건).
  v29~v31c에서 delivery_date가 없는 동안 죽어 있었음을 아무 검사도 알리지 않은 전례가 바로 이 패턴.
- **권고**: 피처 의존 룰의 침묵 비활성을 detector metadata(`coverage_issues`)로 통일 노출 +
  대시보드에서 "이 데이터셋에서 미작동한 룰" 표시. (별도 과제)

## P1-4 (c) 측정 도구 수정 — full build 측정에 extra 트랙 합류

`measure_phase1_current_p3_2.py`가 4트랙(layer_a/b/c+benford)만 돌려 L3-11·IC·GR·D 룰이 case
priority 측정에서 통째로 빠져 있었다(도구 사각). detector_catch와 동일한 `_run_extra_detectors`
보완을 이식 — 이후 모든 full build 측정에 전 39룰이 반영된다.

- **ripple**: 기존 OPEN_ISSUES #1 "정상 v32 high/medium 0건 입증"은 4트랙 기준 측정이었다.
  full 트랙 재측정으로 재확인 필요(진행).

## P1-4 (d) L3-11 신규 발화 12,010행 표본 검토

- 룰 로직(매출 >5영업일 / 비용 >7영업일, ≤30일)을 v32 원본에 독립 재현 → **12,010행 정확 일치**.
- 내역: 전부 매출(O2C) 측, gap 6~10영업일(중앙값 7) — 임계 바로 위 좁은 꼬리. 비용 측 0건.
- 판단: 송장 지연 6~10영업일은 정상 실무 범위로, 결산기 가중(×1.5)·우선순위로 차등되는
  **검토모집단으로서 타당**. 과탐 아님. (단 위 (a)에 따라 제품에서는 이 룰 자체가 미실행 상태.)

---

## P0-1 — r23 위반 truth별 priority band/rank 분해 (위반측 우선순위 정량화)

측정: r23 full build (extra 트랙 포함, cases 19,689 / units 75,852 / raw hits 1,856,849) +
`analyze_truth_priority_band.py`. 산출물: `artifacts/phase1_priority_truth_r23/`.

### 표준 위반 1,080건의 행방 (3계층 surface)

```
case 레인:   high 214 (19.8%) │ medium 437 (40.5%) │ low 288 (26.7%) │ case 미매칭 141 (13.1%)
             → high+medium 651 (60.3%), Top100에 123 / Top500에 673 / Top1000에 810 (75.0%)
macro 레인:  L4-02 Benford 20/20 전건 macro finding으로 표면화 (GR01 43·GR03 37 finding 포함)
완전 미표면: D01/D02 40건 — case에도 macro에도 없음 (variance review 신호가 detector metadata에만 존재)
```

case 미매칭 141건의 전수 분해 (truth_unit_measurement 실측):

| 룰 | 건수 | detector 직접 발화 | unit 매칭 | case 매칭 | macro 등재 | 판정 |
|-------|----:|:----:|:----:|:----:|:----:|------|
| L4-02 | 20 | 0 (행점수 0 설계) | 0 | 0 | **20/20** | macro 레인으로 정상 표면화 |
| GR01  | 30 | 30 | 30 | 0 | 43건 | unit+macro 표면화 (case rank만 없음) |
| GR03  | 20 | 20 | 20 | 0 | 37건 | unit+macro 표면화 (case rank만 없음) |
| D01   | 20 | 0 (review 설계) | 0 | 0 | 0 | **미표면** (이슈 #9) |
| D02   | 20 | 0 (review 설계) | 0 | 0 | 0 | **미표면** (이슈 #9) |
| L4-06 | 30 | **30** | **0** | **0** | **0** | **직접 발화는 되나 unit/case/macro 어디에도 미부착** — 표면 경로 불명 (이슈 #12) |
| L3-08 | 1 | 20/20 발화 | 19 | 19 | — | 1건만 case 미매칭 (19건은 case까지 진입) |

- **위반의 60%가 high/medium으로 올라온다** — 감사인 우선 검토 범위(high 45 + medium 251 = 296 case,
  전체 19,689의 1.5%)에 표준 위반의 과반이 진입. 운영 부하도 합리적.
- **경계 대조군 직접 FP 0 유지** (detector direct hit 0/1,080). case "동승" 231건은 같은 룰이 다른
  문서에서 발화한 case에 경계 문서가 구성원으로 포함된 것 — detector 과탐 아님.
- **묻힘(low) 패턴**: L2-02/L2-03 중복 70건 전부 low(rank 4,664~14,360), L4-05 30건 전부 low,
  L3-04 30/40 low, L1-07 25/30 low, L3-05 24/40 low. 중복·시간대 클러스터·기말 위반은 detector가
  잡아도 우선순위에서 하위로 밀린다. (개선은 도메인 정합성 경로로만 — truth recall 튜닝 금지 원칙.)
- **D01/D02 사각 확정**: review 신호(점수 0)가 case 빌드·macro finding 어느 표면에도 합류하지 않음.
  OPEN_ISSUES #5(IC01 review 미집계)와 같은 계열 — variance review의 표면 정의 필요.
- IC01~03은 extra 트랙 합류 후 전건 medium(rank 216~231)으로 진입 — 트랙 누락 수정 효과 확인.

### 해석 주의

r23은 fixture(룰 조건에 맞춘 주입)이므로 이 band 분포는 "룰이 설계대로 우선순위에 반영되는가"의
검증이지 현실 부정의 우선순위 분포가 아니다. 측정 도구는 macro 레인을 caught로 크레딧하지 않으므로
완전 미스 60 = L4-02 20(macro 표면화됨) + D01/D02 40(진짜 미표면)으로 읽어야 한다.

## ripple — v32 정상 full 트랙 재측정 (이슈 8 해소)

기존 "정상 high/medium 0" 입증(OPEN_ISSUES #1)은 4트랙 측정이었다. extra 트랙(EV·IC·GR·D) 합류 후
재측정 결과:

```
v32 정상 992,764행, full 트랙: cases 37,486 (4트랙 34,853 대비 +2,633) / units 100,272 / raw hits 2,142,707
priority_band_cases: high 0 │ medium 0 │ low 37,486  → 결론 유지 ✅
priority_band_units: high 0 │ medium 13 │ low 100,259 (unit 레벨 medium 13건은 case 흡수 후 전부 low)
```

- **정상 데이터의 운영 과탐 0(high/medium case 0건) 결론은 full 트랙에서도 유지.** EV01이 89% 행에
  발화해도 case 우선순위는 오르지 않는다 — 검토모집단 차등이 트랙 추가에도 견고함을 2개 측정으로 확인.
- case builder 614.8s (r23 402.6s) — perf 수정 후 ~1M행 full 트랙 기준.

## P0-2 — KPI 가드 baseline 재정의 + 재작동

- 구 baseline(manipulation_v2/contract_v2, 2026-05-14)은 `kpi_baseline_legacy_20260514.json`으로 보존
  (unusual_timing 11/21 ceiling 등 도메인 지식 포함). 신 baseline: **normal_v32(full) + recall_r23**.
  → **같은 날 normal 베이스가 v41로 갱신**되어 baseline의 normal 데이터셋을 v41 재측정으로 교체
  (cases 37,614·high/medium 0 유지·가드 17/17 PASS). v41 상세: [PHASE1_NORMAL_FP.md](PHASE1_NORMAL_FP.md) §v41.
- 가드 구조 유지(Layer A/B HARD, C SOFT WARN, 원칙 가드): 주요 변경 —
  - A2: 정상 high/medium case = 0 (구 A2 contract HIGH 비율 대체)
  - A3: case-레인 룰 표준 미탐 0 + 경계 **direct hit** 0 (macro/review 레인 L4-02·D01/D02 제외, 사유 명시)
  - A6: enrichment 지표 ±10% (구 contract_v2 report 의존 제거, checkpoint 자동 추출)
  - B3: r23 band 형태 (high ≤2%, low ≥90%)
  - C1~C3: r23 포착률 ≥99% / high+medium truth 651×70% / Top500 truth 673×70%
  - 구 C4(시나리오)/C5(contract recall)는 데이터셋 퇴역으로 폐지 — 시나리오급 기준은 r3g 특성화(비가드)로 이관
- **실행 결과: 15/15 PASS, skip 0** (2026-06-11). 아티팩트 전부 당일 생성 — freshness HARD 통과.
  가드가 현재 코드에 대해 재작동함을 확인 (잔여 사각 1 해소).

## P1-3 — r3g scheme별 PHASE1 surface 특성화 (튜닝 금지 — 역할 경계 기록)

측정: r3g(현실 부정 FS01~14, 14 instance / 330 문서)에 PHASE1 full build (cases 37,591) +
`analyze_scheme_surface.py`. 산출물: `artifacts/phase1_scheme_surface_r3g/scheme_surface*.{json,md,csv}`.

> ⚠️ 이 결과로 PHASE1을 튜닝하지 않는다 (truth recall 직접 추구 금지 — PHASE2 이관 원칙).
> 목적은 PHASE1↔PHASE2 역할 경계의 실측 기록이다.

### 요약

```
14/14 scheme — 룰 hit 있음 + case 진입 (완전 미표면 0)
Top100 진입 5: FS01 가공매출(rank 17·high), FS05 순환거래(17·high), FS06 부채누락(80),
               FS09 컷오프조작(24), FS10 대손회피(82)
Top500 진입 8: + FS03 현금횡령(148), FS11 특수관계자남용(241), FS13 손상회피(242)
low 묻힘   6: FS02 진행률조작(2,943) FS04 횡령은폐(5,195) FS07 재고과대(3,592)
               FS08 부당자본화(2,346) FS12 충당부채누락(3,381) FS14 유령직원(9,126)
```

### 역할 경계 해석

- **PHASE1이 상위로 올리는 것**: 구조·시점·증빙 위반이 동반되는 scheme — 가공매출(L3-11 컷오프
  14건 + 결산기·주말 신호 결합), 순환거래(L3-01 계정-업무 불일치), 컷오프 조작(L3-11 15건),
  부채누락·대손회피(L3-01). extra 트랙 기여 확인: FS11/FS13에서 GR01·IC 신호(ic_unmatched 20건 등)
  가 작동해 Top500 진입.
- **PHASE2 몫으로 확인된 것**: 경제적 실질의 조작(진행률·재고금액·자본화 분류·충당부채 규모·유령
  직원 급여)은 개별 전표가 형식적으로 적법해 PHASE1 룰 신호가 약하고(EV01·결산기 등 광역 신호만)
  low band에 깔린다. 이 6개가 PHASE2 ML(가격·수량·추세·관계 학습)의 1차 타깃 지도다.
- PHASE1 역할 원칙과 정합: PHASE1은 fraud 확정이 아니라 "감사인이 봐야 할 항목"을 올리는 단계 —
  현실 부정의 57%(8/14)가 룰 기반만으로 Top500에 들어온다는 것은 보조 검토선으로 유의미하며,
  나머지는 설계대로 PHASE2가 담당한다.

## 종합 결론 (3개 데이터셋)

| 데이터셋 | 성격 | 핵심 결과 |
|----------|------|----------|
| v32 (정상 99만 행) | 운영 과탐 | full 트랙에서도 high/medium case **0** — 검토모집단 차등 견고 |
| r23 (39룰 위반 fixture) | 룰 계약+우선순위 | 리콜 유지 + 위반 60.3% high/medium 진입, 경계 직접 FP 0 |
| r3g (현실 부정 14 scheme) | 역할 경계 | 14/14 표면화, 8/14 Top500 — 잔여 6개는 PHASE2 타깃 |

PHASE1은 "정상을 올리지 않고(과탐 0), 위반·부정의 구조 신호를 상위로 올린다"는 임무를 3개 데이터셋
실측으로 입증했다. 잔여 신뢰 갭은 OPEN_ISSUES #5/6/7/9/10 — 특히 **#6(제품 파이프라인 트랙 누락)은
이 측정들이 가정한 full 트랙과 실제 제품의 차이이므로 최우선 결정 대상**이다.
