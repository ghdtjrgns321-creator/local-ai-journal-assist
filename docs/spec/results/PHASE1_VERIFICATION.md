# PHASE1 검증 종합 (단일 SoT)

> PHASE1 검증 축 전체의 **현행 상태**를 이 문서 하나로 관리한다. 데이터셋이 갱신되면 본 문서의
> 수치와 KPI baseline(`tests/phase1_rulebase/kpi_baseline.json`)을 함께 갱신한다 (§9 절차).
> 시점별 상세 리포트(이력)는 `docs/archive/completed/`에 보존:
> [PHASE1_RECALL_FP_r23.md](../../archive/completed/PHASE1_RECALL_FP_r23.md) ·
> [PHASE1_VERIFICATION_20260608.md](../../archive/completed/PHASE1_VERIFICATION_20260608.md) ·
> [PHASE1_VERIFICATION_EXTENDED_20260611.md](../../archive/completed/PHASE1_VERIFICATION_EXTENDED_20260611.md).
> 정상 과탐 상세: [PHASE1_NORMAL_FP.md](PHASE1_NORMAL_FP.md). 미해결 이슈: [PHASE1_OPEN_ISSUES.md](PHASE1_OPEN_ISSUES.md).

## 현행 측정 기준 (2026-06-11)

| 역할 | 데이터셋 | 산출물 |
|------|----------|--------|
| 정상 (과탐 베이스라인) | `normal_20260613_v42j` (993,176행, 무결성 통과·CoA 누락 0) | `artifacts/phase1_priority_band_v42j/` |
| recall fixture (룰 계약) | `recall_20260613_v42j_r3` (v42j 기반, truth 2,160) — 2026-06-14 r24 과도기 종료·전환 완료(normal_regression PASS·oracle_scan PHASE1 무해, NORMAL/recall base 정합 회복) | `artifacts/phase1_priority_truth_v42j_r3/` |
| 현실 부정 (역할 경계) | r3g 측정 보존 (데이터셋 퇴역, 현행 r4e 재측정은 별도 과제) | `artifacts/phase1_scheme_surface_r3g/` |

측정 도구: `measure_phase1_detector_catch.py`(detector-only) → `measure_phase1_current_p3_2.py`
(full build, extra 트랙 포함) → `analyze_truth_priority_band.py`(band/rank 분해) →
`analyze_scheme_surface.py`(scheme 특성화). KPI 가드: `tests/phase1_rulebase/nightly_kpi_guard.py`.

> **2026-06-14 recall 전환 (R2 마감):** recall fixture가 r24(v41 기반) → **v42j_r3**(v42j 기반)로
> 전환되어 NORMAL/recall base 정합이 회복됐다. 선결 검증: normal_regression PASS(정상 subset 사용계정
> ⊆ config CoA 480·999998은 L1-03 무효계정 truth 한정·차대변 균형·라벨 미오염), oracle_scan은 ML
> anti-shortcut 렌즈 finding이나 PHASE1 규칙기반 detector엔 무해(검증 도구
> `tools/scripts/validate_recall_overlay_oracle_normal.py`, 리포트 `artifacts/recall_v42j_r3_validation/`).
> 현행 수치(요약 표 기준): 표준 1,020/1,020 미탐 0·경계 직접 FP 0, band high+medium **870(80.6%)**·
> Top500 **796**, case 28,620, case_builder **388.9s**(병목 2건 수정으로 3,717s→389s, 동작 불변). KPI
> 가드 17/17 PASS. **아래 §1/§3 상세 분해 수치(539·718·72.5% 등)는 r24 시점 기록으로, 현행 v42j_r3
> 값은 본 요약·baseline을 따른다.**

## 검증 축 요약

| # | 축 | 현행 결과 | 상세 |
|---|----|----------|------|
| 1 | 룰 계약 (리콜·경계) | case-레인 39룰 표준 1,020/1,020 + macro 레인 L4-02 전건, 경계 직접 FP 0 (v42j_r3) | §1 |
| 2 | 정상 과탐 | **high 0 · medium 838 (2.1%)** — v42j 실측(R1·R2 적용). high 0 HARD 불변. unknown_approver 정상 과탐 0 | §2 |
| 3 | 위반 우선순위 | 표준 위반 **80.6% high/medium** 진입(870/1,080 — high 650·medium 220·Top500 796) (v42j_r3) | §3 |
| 4 | surface 레인 | case/macro/review 3레인 분해 — D01/D02·L4-06 사각 식별 | §4 |
| 5 | 단위 정합 | document XOR flow disjoint 전수 PASS (reversal 중복 수정 후) | §5 |
| 6 | 회귀·perf | 신규 실패 0, case build 선형화(~10분/1M행) | §6 |
| 7 | KPI 가드 | 17/17 PASS·skip 0 (normal v42j / recall v42j_r3, R1·R2 baseline) | §7 |
| 8 | 룰 활성성·제품 배선 | L3-11 배선 완료, 침묵 비활성 11룰 목록화 | §8 |
| 9 | 현실 부정 특성화 | 14/14 scheme 표면화, 8/14 Top500 (r3g — legacy 경로 측정, topic ON 재측정은 r4e 과제) | §10 |
| 10 | 룰 도메인 의미 검토 | 41룰+스코어링층 전수 3축 리뷰(구멍/과승격/저승격) — 횡단 결함 7건, 이슈 #17~#25 | [RULE_DOMAIN_REVIEW](PHASE1_RULE_DOMAIN_REVIEW.md) |

---

## §1 룰 계약 — 리콜·경계 FP (recall fixture)

### 이 수치를 읽는 법 (필독)

이 결과는 "PHASE1이 현실 부정을 얼마나 잡느냐"가 아니라 **"룰이 제대로 구동하는지"**를 측정한
것이다. 위반을 각 룰의 detector 트리거 조건에 맞춰 만들었고 그 데이터로 그 룰을 테스트한
**설계상 순환 구조**다. 100% 리콜은 ① 룰이 죽지 않았고 ② 주입이 진짜 위반이며(shortcut scan 0)
③ 측정이 맞다는 것까지만 증명한다. 현실 부정 탐지 성능은 §10(scheme 특성화)이 별도로 본다.
정상발화%가 높은 검토모집단 룰(L3-12·L1-07/09 등)의 100%는 그물이 넓어 잡힌 trivial이고,
정상발화% 0% 룰의 100%만 정밀 catch로 의미가 있다.

### 측정 방식 3분류 (룰마다 "잡혔다"의 의미가 다름)

1. **row-catch** (대부분 룰): 주입 전표에 detector score>0. 리콜 = 잡힌 전표/주입 전표.
2. **finding** (집계/모집단): 그룹·모집단이 finding으로 잡혔는지로 측정. L4-02 Benford는
   `company×계정` 그룹(n≥500)의 첫자리 분포 MAD>0.012 → "조작된 그룹이 finding으로 잡혔나"
   (행 점수는 설계상 0). L4-01/03/04/05/06, L3-09도 그룹/모집단 단위.
3. **review** (score 0): L3-12, IC01, D01, D02 — evidence_level/review_score/variance metadata로
   측정. 확정 위반이 아닌 검토 신호 (D065 정책).

### 현행 결과 (r24, 39룰 × 표준 1,080 + 경계 대조군 1,080)

```
detector 레벨 (detector-catch):  표준 1,080/1,080 catch · 경계 대조군 발화 0 · shortcut scan 0
case 레인  (full build):         표준 1,020/1,020 catch (제외 3룰 외 전부) · 경계 direct hit 0
제외 룰:   L4-02(macro finding 레인으로 전건 표면화) · D01/D02(review 신호 미표면 — 이슈 #9)
경계 동승: 231건 — 같은 룰이 다른 문서에서 발화한 case에 경계 문서가 구성원 포함된 것 (과탐 아님)
```

룰별 표준 리콜·경계 FP·정상발화% 전수 표는 r23 이력 리포트(archive)와
`artifacts/phase1_priority_truth_r24/rule_summary.csv` 참조. r23(v29 기반) → r24(v41 기반)
재생성에도 룰 계약 결과는 동일했다 — 데이터 버전에 휘둘리지 않음을 2개 fixture로 확인.

## §2 정상 과탐 — [PHASE1_NORMAL_FP.md](PHASE1_NORMAL_FP.md)

- **현행 (2026-06-13, v42j + R1/R2)**: 정상 993,176행 → **high 0 · medium 838 (2.1%) · low 39,756**
  (case 40,594). 데이터셋 v41→v42j 전환(사용자 의도 재생성, v41 폐기). v42j 무결성 통과
  (CoA 누락 0·날짜 NaT 0·라벨 0). R1·R2 결함 수정 적용 후에도 **high 0 HARD 불변**.
  R2 unknown_approver는 정상 과탐 0(비공란 292,487 중 마스터 미존재 0), L2-02 fallback은 168행
  발화하나 floor 미부착이라 band 영향 없음. v41 직전값(medium 1,029)과는 데이터셋이 달라 직접
  비교 무의미 — high 0 유지가 핵심 불변식.
- v41 정상 993,152행 (직전 baseline, topic ON + 게이트): high 0 · medium 1,029 (2.7%).
- **정정 (2026-06-12)**: 종전 "정상 high/medium 0" 결론은 측정 하니스가 빈 설정으로
  use_topic_scoring=False(legacy 경로)였던 결함의 착시였다. 제품 경로에서는 광역 검토모집단 룰
  (L1-09·L1-07·L3-04·L3-12 등)의 결합이 topic floor를 넘겨 정상 케이스가 medium에 오른다.
  high 0은 양 경로 모두 유지 — 최우선 검토는 깨끗하다.
- **이슈 #14 해소 (2026-06-12, 1+2 세트)**: 게이트 전 medium 3,516(9.3%)의 표본 검토 결과
  대부분이 자동 결산 배치 전표(승인란 공백+결산기+고액의 정상 조합)를 fraud-combo floor가
  강제 승격한 것이었다. 두 변경을 한 세트로 적용:
  1. **fraud-combo floor 신뢰 자동전표 게이트** (`src/detection/source_trust.py` +
     `topic_scoring.py` `fraud_combo_rule_scope`): 신뢰 자동전표(자동 source ∧ 단독성 없음)에서만
     발화한 룰은 combo floor 결합에서 제외. 점수 인상 경로(`apply_combo_floors`)와 breakdown
     기록 경로 양쪽 모두 게이트.
  2. **L4-06 `lone_batch_identity` 확장**: "자동이라는데 batch 정체성(batch_id/job_id)이 없고
     같은 날 동류 ≤10건"인 위장 의심 전표는 게이트 면제를 못 받고 L4-06 4번째 서브패턴으로
     별도 플래그 (단독 0.45, multi-signal 0.65). 진짜 자동은 조용해지고 자동인 척은 더 잘 보임.
  - 효과 실측: 정상 medium **3,516 → 1,029 (-71%)**, high 0 유지. r24 truth band(79.0%·Top500
    718)는 게이트 전후 동일 — 위반 탐지력 손실 0.
- 잔여 medium 1,029(2.7%)는 게이트 비대상(수동 전표) 결합 신호 — 운영 수용 범위로 판단,
  가드는 high 0 HARD + medium baseline ±20% drift로 잠금.
- 행 발화율(정상발화%)을 과탐으로 읽지 말 것 — 운영 부담은 priority band가 결정한다.

## §3 위반 우선순위 — truth band 분해 (r24)

```
표준 위반 1,080건의 case 레인 행방 (topic scoring ON + R1, 2026-06-13):
  high 539 (49.9%) │ medium 244 (22.6%) │ low 156 (14.4%) │ case 미매칭 141 (13.1%)
  → high+medium 783 (72.5%), Top100에 123 / Top500에 718 / Top1000에 777
운영 부하: high 97 + medium 1,268 (전체 28,822의 4.7%)
경계 대조군: detector 직접 발화 0 유지. 경계 동승 분포 불변 — detector 과탐 아님.
```

- **R1 결함 수정 후 변화 (2026-06-13)**: high+medium 853(79.0%) → 783(72.5%)은 의도된 하락이다.
  ① L2-02 중복지급 floor를 스펙값 0.45로 정합(이슈 #17) — 표준 30유닛이 medium에서 이탈
  (스펙: "fallback 계열은 단독 floor 없음, reference_match는 0.45"). ② 미문서 repeat 무조건
  medium 승급 제거(이슈 #22). **high 539·Top100 123·Top500 718은 불변** — 최우선 검토 범위의
  위반 노출은 그대로다. 정상(v41)은 완전 불변(R1 정상 중립). IC01~03 전건 medium은 repeat
  승급이 아니라 콤보 점수 기인으로 확인(도메인 리뷰 §2.6 가설 정정).

- 위반의 약 8할이 감사인 우선 검토 범위로 올라온다.
- 참고: legacy 경로(하니스 결함 수정 전) 측정값은 61.7%/Top500 674였다 — topic floor가 위반
  결합을 medium 이상으로 끌어올리는 효과가 +17.3%p.
- **묻힘(low) 패턴 (topic ON 기준 대폭 축소)**: low 86건 — legacy 측정의 273건에서 줄었다.
  L2-02 중복결제는 `duplicate_outflow_high` floor(0.75)로 medium 도달 확인. 잔여 low는
  검토모집단 룰 단독 발화 등 결합 신호가 없는 최소 위반. (truth recall 튜닝 금지 — 이슈 #10).

## §4 surface 레인 분해 (finding/review형 룰의 행방)

case 미매칭 141건의 전수 분해 (r24에서도 r23과 동일 구조):

| 룰 | 건수 | detector 발화 | unit | case | macro | 판정 |
|-------|----:|:----:|:----:|:----:|:----:|------|
| L4-02 | 20 | 0 (행점수 0 설계) | 0 | 0 | 전건 | macro finding 레인으로 정상 표면화 |
| GR01/GR03 | 50 | 50 | 50 | 0 | 등재 | unit+macro 표면화 (case rank만 없음) |
| D01/D02 | 40 | 0 (review 설계) | 0 | 0 | 0 | **미표면** — 이슈 #9 (+대시보드 "스킵됨" 오표시 #13) |
| L4-06 | 30 | 30 | 0 | 0 | 0 | **발화는 되나 어느 표면에도 미부착** — 이슈 #12 |
| L3-08 | 1 | 발화 | 19/20 | 19/20 | — | 1건만 case 미매칭 |

## §5 단위 정합 (document XOR flow)

- 불변식: 각 문서는 최대 하나의 자연 단위, flow 구성 문서는 흐름으로 흡수(R1), 중복 카운트 금지.
- 단위 테스트 + **전수 실측**(`check_unit_disjoint.py`)으로 검증. 전수에서 reversal flow 중복
  소속 8건(0.0087%) 발견 → `seen_documents` 문서 단위 dedup으로 수정, 재빌드 8→0
  `disjoint_pass=true`. 단위 테스트가 못 잡은 사각을 전수 실측이 잡은 사례.

## §6 회귀·perf

- 전체 테스트: 신규 실패 0 유지 (pre-existing 실패는 데이터 부재·진행 중 dashboard 리팩터 분류).
- case builder O(cases×units) 준-이차 → (rule_id,row_index) 역인덱스로 선형화. ~1M행 full 트랙
  기준 case build ~10분(583~617s), 16GB RAM 완주. B2 가드(max 1,200s)가 회귀 차단.
- 측정 도구 정합 (하니스 결함 2건 발견·수정):
  1. full build 측정에 extra 트랙(evidence/IC/graph/variance) 누락 → `_run_extra_detectors` 이식.
     메타 가드(extra detector error 검사)로 재발 차단.
  2. 빈 `phase1_case_config`로 use_topic_scoring=False — **모든 band 측정이 legacy 점수 경로**였음
     (전 case의 74%에서 topic 점수 > priority). `get_phase1_case()` 로드로 수정, 제품 경로와 일치.
     이 결함이 "정상 high/medium 0"(실제 medium 3,516)과 "L2-02 구조적 도달 불가"(실제 floor로
     medium 도달)라는 두 개의 잘못된 결론을 만들었다 — 검증 도구 자체의 검증이 필요한 이유.

### 룰별 band 도달성 전수 (39룰, `analyze_rule_band_reachability.py`)

topic ON 기준: case-레인 룰 전부 결합 시 medium+ 도달 실증 (L2-02 포함 — floor 0.75).
IC01~03은 설계 의도대로 medium 상한(D065 floor). 구조적 도달 불가 룰 = **0개**.
산출물: `artifacts/phase1_priority_truth_r24/rule_band_reachability.csv`.

## §7 KPI 가드 (회귀 게이트)

- 구조: Layer A(도메인 정합 HARD) / B(운영 부하 HARD) / C(truth 회귀 방지선 SOFT WARN) + Meta
  (freshness·원칙·fixture 무결성·extra detector 오류). **truth recall 향상 강제 가드 금지** 원칙을
  메타 테스트로 강제.
- baseline: `kpi_baseline.json` — datasets 키는 버전 중립(`normal`/`recall`), 현행 v41/r24.
  갱신 시 PR에 사유 + 도메인 정당성 명시. 구 baseline은 `kpi_baseline_legacy_20260514.json` 보존.
- 현행: **17/17 PASS, skip 0** (2026-06-13, topic ON + R1 결함 수정 baseline — c2 783/548).

## §8 룰 활성성·제품 배선

- **L3-11 스펙-구현 갭 해결**: DETECTION_RULES.md §306이 선언한 기본 경로
  `EvidenceDetector(rule_ids=("L3-11",))` 배선이 제품에 부재했던 것을 발견, base 경로에 배선 +
  회귀 테스트 잠금. IC01~03·GR01/03·EV01/03의 기본 제외는 문서화된 의도(§307)로 확인.
- **침묵 비활성 룰 11개** (필수 입력 부재 시 경고 없이 0건): L2-01(is_near_threshold),
  L3-05/06/07/08/09(시간·적요·가수금 피처), L2-05(dropna), L4-03(amount_zscore), L4-04(표본<30),
  L4-06(source), IC01~03(매칭 결과 빈 경우). L3-11도 같은 패턴(delivery_date 부재 시 침묵) —
  v29~v31c 동안 죽어 있던 전례. 개선 권고: coverage_issues metadata 통일 노출 (이슈 #7).
- 같은 패턴 재발 사례 (2026-06-12): L4-06 `lone_batch_identity` 신설 직후 측정 스크립트
  `PHASE1_USECOLS`에 batch_id/job_id가 없어 신규 서브패턴이 측정에서 침묵 0건 — 발화 수 불변을
  의심해 발견, USECOLS 추가로 해결. 신규 입력 컬럼 추가 시 측정 도구 USECOLS 동기화 필수.
- 죽은 코드: `_try_evidence/graph/nlp_detection`은 enable 플래그를 켜도 호출부 없음 (이슈 #11).

## §9 데이터 갱신 시 재측정 절차 (표준)

1. **사전 점검**: realism gate 통과 확인 + 라벨 오염 0 + 날짜 파싱 NaT 0 + **글로벌 CoA 누락
   사용계정 0** (v31c 17계정·v41 110010 두 차례 재발한 ripple — 데이터셋 CoA 확장 시 필수).
2. detector-catch 측정 → 직전 버전과 룰별 발화율 대조 (유의 변화 |Δ|≥0.1%p 규명).
3. full build 측정 → priority band (정상: high 0 + medium baseline 대조 / recall: truth band 분해).
   측정 도구가 `config/phase1_case.yaml`을 로드하는지(topic scoring ON) 확인 — 빈 설정이면
   legacy 경로를 측정하게 된다 (2026-06-12 하니스 결함 사례).
4. `kpi_baseline.json` 수치 교체 (datasets 경로·a6·b1/b2/b3·c2/c3) → 가드 전건 PASS 확인.
5. 본 문서·[PHASE1_NORMAL_FP.md](PHASE1_NORMAL_FP.md)·debugging.md 갱신.

## §10 현실 부정 scheme 특성화 (역할 경계 — 튜닝 금지)

PHASE2용 현실 부정 14 scheme(FS01~14)에 PHASE1을 돌린 특성화 (r3g 측정, 데이터셋은 이후 r4e로
재생성되어 퇴역 — 현행 r4e 재측정은 별도 과제):

```
14/14 scheme 룰 hit + case 진입 (완전 미표면 0)
Top100: 가공매출·순환거래·부채누락·컷오프조작·대손회피 (5)
Top500: + 현금횡령·특수관계자남용·손상회피 (8)
low 묻힘 (6): 진행률조작·횡령은폐·재고과대·부당자본화·충당부채누락·유령직원
```

- PHASE1은 구조·시점·증빙 신호가 동반되는 scheme을 상위로 올리고, 경제적 실질 조작(개별 전표가
  형식상 적법)은 low에 깔린다 — **이 6개가 PHASE2 ML의 1차 타깃 지도**다.
- PHASE1 역할 원칙 정합: fraud 확정이 아니라 "감사인이 봐야 할 항목"을 올리는 단계. 이 결과로
  PHASE1을 튜닝하지 않는다 (truth recall 직접 추구 금지 — PHASE2 이관).

## 종합 판정

PHASE1은 3개 축 모두 실측으로 입증됐다: **정상을 거의 올리지 않고**(v41 high 0 · medium 2.7%),
**위반을 올리며**(r24 79.0% high/medium), **현실 부정의 구조 신호형 절반을 룰만으로 상위
노출**(r3g 8/14 Top500)한다. 회귀는 KPI 가드(17/17)가 지킨다. 잔여 갭은 surface 정의
(D01/D02·L4-06 부착, 이슈 #9/#12/#13)와 관측성(#7)·코드 위생(#11)으로, 완성 차단 요소가 아닌
개선 거리다.
