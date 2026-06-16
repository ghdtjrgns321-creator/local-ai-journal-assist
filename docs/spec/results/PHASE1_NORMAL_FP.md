# 정상 데이터 PHASE1 과탐 베이스라인 (현행: v42j, 갱신 2026-06-13)

> 버전 이력: v29 → v31c → v32 → v41 → v42j (각 절 참조). 데이터 갱신 시 본 문서 상단에 최신 절을
> 추가하고 [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md) §9 절차를 따른다.

## v42j 전환 (2026-06-13) — 현행 NORMAL 베이스

NORMAL v41 → v42j(993,176행, 6/13 생성) 전환(사용자 의도 재생성, v41 폐기). 무결성 통과:
**글로벌 CoA 누락 0**(v31c·v41 두 차례 재발한 ripple이 v42j에선 깨끗), 날짜 NaT 0, fraud/anomaly
라벨 0. full build(R1·R2 적용): **high 0 · medium 838 (2.1%) · low 39,756** (case 40,594).

- R1(floor 버킷 게이트·source 위장 게이트·repeat 승급 제거)·R2(L2-02 fallback·unknown_approver)
  적용 후에도 **high 0 HARD 불변**. unknown_approver 정상 과탐 0(비공란 292,487 중 마스터 미존재
  0건 — 합성데이터 한정). L2-02 fallback 168행 발화하나 floor 미부착이라 band 영향 0.
- KPI baseline normal 키만 v42j로 갱신(a2/a6/b1/b2). recall(r24)은 v42j_r1 검증 pending이라
  과도기 유지(base 불일치). 산출물: `artifacts/phase1_priority_band_v42j/`.
- 직전 v41(medium 1,029)과는 데이터셋이 달라 직접 비교 무의미 — high 0 유지가 핵심 불변식.

> 측정: `tools/scripts/measure_phase1_detector_catch.py` (detector-only, case/unit build 제외).
> v31c(992,764행)와 v29(983,028행)를 **동일 도구**로 측정해 직접 대조. truth 없음(순수 정상).
> 결과 산출물: `artifacts/phase1_normal_fp_v31c/`, `artifacts/phase1_normal_fp_v29_sametool/`, `artifacts/phase1_normal_fp_v32/`, `artifacts/phase1_normal_fp_v41/`.

## v41 재측정 갱신 (2026-06-11) — 현행 NORMAL 베이스

v41(=v36 계보 + 최신 normal 프로파일 재생성, trial balance 재계산 수정 포함. 993,152행/325,374문서,
realism gate 34 PASS/0 FAIL)에 동일 도구로 재측정. **v32 대비 유의 변화(|Δ|≥0.1%p)는 L1-02 단 1건**:

| 룰 | v32 | v41 | 해석 |
|----|----:|----:|------|
| L1-02 필수필드 | 9,736행 (0.98%) | **0** | v32 아티팩트는 날짜 파싱 견고화(ISO8601) **이전** 측정값 — 수정 후 0 예측(아래 §L1-02)이 v41 전수 측정으로 실증 확정 |
| L1-03 무효계정 | 0 | **0 유지** | v41 신규 계정 `110010`(매출채권 상세)이 글로벌 CoA에 누락돼 있던 것을 사전 점검에서 발견, `config/chart_of_accounts.csv`에 추가(475→476계정)하여 과탐 재발 차단. **v31c 사건(17계정 누락)과 동일한 ripple 패턴 — 데이터셋 CoA 확장 시 글로벌 CoA 동기화 체크 필수** |
| L3-11 매출 cutoff | 12,010 (1.21%) | **12,010 동일** | delivery_date 84,063행 동일 — 검토모집단 불변 |
| 나머지 36룰 | — | |Δ|<0.1%p | 본질 동일 |

- v41 사전 점검: `is_fraud/is_anomaly` true 0, document_date/posting_date NaT 0, realism gate
  (M01~M07 balance 정합·O01/O02 라벨 가드·J04/J07 reversal 링크) 34 PASS — `reports/normal_realism_gate_v41.{json,md}`.
- full build(priority band) 측정: `artifacts/phase1_priority_band_v41_full/` — KPI 가드 baseline이
  이 산출물을 소비한다 (`tests/phase1_rulebase/kpi_baseline.json`).
- priority band (topic ON + fraud-combo 신뢰 자동전표 게이트, 2026-06-12): **high 0 · medium 1,029
  (2.7%) · low 36,585** (cases 37,614). 게이트 전 medium 3,516(9.3%)은 자동 결산 배치 전표 오인
  승격 — 해소 경위는 [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md) §2,
  [PHASE1_OPEN_ISSUES.md](PHASE1_OPEN_ISSUES.md) #14/#16 참조.

## v32 재측정 갱신 (2026-06-11)

v32(=v31c + delivery_date 백필 + CoA 17계정 수정 반영)에 동일 도구로 재측정. **35개 룰은 v31c와 완전 동일**,
변화는 3건뿐:

| 룰 | v31c% | v32% | 해석 |
|----|------:|-----:|------|
| L1-03 무효계정 | 0.62 (6,178행) | **0.00** | 글로벌 CoA 17계정 추가로 무효계정 과탐 **완전 해소 확정**(재측정으로 입증) |
| L3-11 매출 cutoff | 0.00 | **1.21** (12,010행) | v32가 delivery_date를 84,063행 백필 → `posting_date+delivery_date` 둘 다 있어야 검사하는 cutoff 룰이 **비로소 작동**. 과탐이 아니라 "이전엔 미검증이던 cutoff가 검증 가능해진" 것(검토모집단) |
| L1-02 필수필드 누락 | 0.98 (9,736행) | 0.98 → **0** (파이프라인 수정 후) | document_date 형식 비일관을 날짜 파싱이 NaT화한 **거짓 발화** — 파싱 견고화로 해소(아래) |

- v32 검증: orphan 0, fraud/anomaly label 0, **글로벌 CoA 누락 사용계정 0**(CoA 수정 ripple 완전 반영).
- 산출물: `artifacts/phase1_normal_fp_v32/rule_summary.csv` (L1-02는 파이프라인 수정 전 측정값 9,736 — 수정 후 features 재현으로 0 확정).

### L1-02 9,736 → 0: 날짜 파싱 견고화 (datasynth 탓 아님)

- **원인:** `document_date`가 행마다 형식이 달랐다 — 983,028행은 `2024-12-31`(날짜만), 9,736행은
  `2024-12-31 18:10:00`(시각 포함). `posting_date`는 전부 시각 포함으로 일관. 한 컬럼에 두 형식이
  섞이면 `pd.to_datetime`(format 미지정)이 다수 형식으로 추론해 **소수(시각 포함) 9,736행을 NaT**로
  만든다 → IntegrityDetector가 "필수필드(전표일자) 누락"으로 **거짓 발화**. 값 자체는 정상(시각 포함
  9,736행만 단독 파싱하면 NaT 0).
- **판단:** 이는 datasynth 한정 문제가 아니라 **파이프라인의 날짜 파싱이 혼합 형식에 취약**한 것이다.
  실무에서 회사마다 날짜 형식이 제각각 들어오므로, 어떤 형식이든 견고하게 처리해야 한다.
- **수정:** type_caster(정식 ingest)는 이미 `format="ISO8601"`로 견고(시각 유무 모두 파싱). type_caster를
  우회하는 직접 파싱 3곳을 `format="ISO8601"`로 견고화 — `tools/scripts/profile_phase1_v126.py`,
  `tools/scripts/measure_phase1_detector_catch.py`, `src/db/loader.py`. 비ISO 외부 형식(한국어·Excel
  serial 등)은 type_caster 관문이 담당(역할 분리).
- **검증:** features 경로 재현 → L1-02 **9,736 → 0**(document_date datetime64, NaT 0). 형식별
  (date_only/datetime/혼합) 모두 NaT 0. 회귀 438 passed, 신규 실패 0.

## 요약

- **v31c 정상 과탐은 v29와 본질적으로 동일**하다. 신규 14계정 도입으로 인한 실제 변화는 3개 룰뿐.
- **recall fixture 구표(archive: PHASE1_RECALL_FP_r23.md)의 정상발화%(v29) 0%들은 측정도구 차이였다.** 그 표는 measure
  도구가 review_score/benford/variance 집계 기능을 갖추기 전 측정이라, L3-12·L1-07·L1-09·L4-02·
  D01 등이 0으로 찍혀 있었다. 동일 도구로 재측정하면 v29에서도 이미 높다(L3-12 81%, L1-07/09 71%).
- **실제 v29→v31c 변화(동일 도구):** L3-12 +15.95%p(review-only), L1-02/L1-03 신규 출현.
  L1-03은 **신규 계정이 글로벌 CoA에 미등록되어 발생한 과탐**으로 확정 — 조치 필요(§조치).

## 동일 도구 대조표 (주요 룰, 발화율 %)

```
rule     v29%    v31c%   Δ%p     측정성격
─────────────────────────────────────────────────────────────────
L3-12    81.10   97.05   +15.95  업무범위 검토 (review-only, score 0)
EV01     89.17   89.27   +0.10   증빙 보조신호 (canonical 외)
L1-09    71.27   71.56   +0.29   승인일 누락 (review population)
L1-07    71.27   70.58   -0.69   승인 생략 (review population)
EV03     57.74   57.18   -0.56   증빙 보조신호
L3-02    24.13   24.23   +0.10   수기 분개
L3-04    22.65   22.60   -0.05   결산기 입력
L3-06    10.44   10.33   -0.11   심야 입력
L3-05     9.07    9.29   +0.22   주말 입력
L4-02     4.93    4.92   -0.01   Benford (group finding)
L1-02     0.00    0.98   +0.98   필수필드 누락 (신규 출현)
L1-03     0.00    0.62   +0.62   무효 계정 (신규 출현) ← 조치 필요
나머지 룰  변화 |Δ|<0.3 또는 절대수 동일 (분모 증가분만 반영)
─────────────────────────────────────────────────────────────────
```

> 음수 Δ(L1-07 -0.69 등)는 v31c 분모(행수)가 9,736행 늘어 비율만 내려간 것으로, 발화 절대수는
> 동일/유사하다. 의미 있는 과탐 증가가 아니다.

## 광역 발화 룰은 과탐이 아니다 (재확인)

L3-12(97%)·L1-07/L1-09(71%)는 **설계상 review 모집단**이다. 승인자/승인일이 없는 자동·배치
전표(R2R_ACCRUAL이 최대 archetype, 30만행)는 원래 승인 흔적이 없으며, 이 룰들은 "우선 전부
후보로 잡고 점수로 분리"한다. emitted_rows(발화 행 수)로 세면 광역이 정상이고, 실제 과탐 부담은
high/medium priority band에서 봐야 한다(case/unit build 별도 필요). PHASE1_VERIFICATION.md §2의
경고와 동일.

## 실제 변화 분석

### L3-12 +15.95%p (review-only)
업무범위 집중 검토. 신규 14계정이 추가되면서 한 사용자(created_by)가 관여하는 계정군·프로세스
폭이 넓어져 work-scope 점수가 상승. score_series는 0이며 확정 위반이 아닌 review 신호다. 신규
계정 도입의 자연스러운 결과로, 데이터 결함이 아니다.

### L1-03 무효 계정 0→6,178행 — **근본 원인 확정 (조치 필요)**

- **현상:** v29 0 → v31c 6,178행 신규 발화. detector(IntegrityDetector)로 직접 재현.
- **내역:** 신규 14계정 라인 5,122개 **전부(100%)** + 부속계정(139100·169100·412100) 1,056행.
- **근본 원인:** `IntegrityDetector._load_coa()`는 `settings.chart_of_accounts_path`
  (= `config/chart_of_accounts.csv`, 458계정)에서만 CoA를 로드한다. **데이터셋의
  `chart_of_accounts.json`(454계정, 신규 포함)을 쓰지 않는다.** CoA 확장 작업에서 데이터셋 CoA만
  갱신하고 detector가 참조하는 글로벌 config CoA를 누락한 **ripple 누락**이다.
- **글로벌 CoA 누락 계정 17개** (journal에서 쓰이는데 `config/chart_of_accounts.csv`에 없음):
  `106100 116100 117100 117900 119100 123100 131100 139100 151900 160100 169100 231100 237100 412100 469100 681100 682100`
  (모두 데이터셋 CoA에는 존재.)
- **영향:** 정상 신규계정 거래가 전부 L1-03 무효계정으로 과탐. fraud overlay를 얹으면 신규계정
  악용 scheme(FS08/10/13)이 "무효계정"으로 잡혀 **L1-03이 신규계정 판별자가 되는 shortcut**으로
  번진다. **PHASE2 진행 전 필수 수정.**

### L1-02 필수필드 누락 0→9,736행 (CoA 무관 — 추정 정정)
raw 데이터의 required 컬럼 결측은 0이고, IntegrityDetector 단독 실행으로는 L1-02 발화가 0이다.
measure 도구(features 파이프라인 경유)에서만 9,736행 발화한다.

> **정정·해소(2026-06-11):** 당초 "무효계정(L1-03)의 2차 효과 → CoA 수정으로 해소 예상"이라 추정했으나
> v32 재측정에서 L1-03만 해소되고 L1-02는 불변이었다(CoA 무관). 추가 규명 결과 **원인은 document_date
> 형식 비일관을 날짜 파싱이 NaT화한 거짓 발화**였고, 파이프라인 날짜 파싱을 `format="ISO8601"`로
> 견고화하여 **9,736 → 0 해소**했다(위 §"L1-02 9,736 → 0" 참조). features 단계가 아니라 read 단계의
> `pd.to_datetime`이 원인이었다.

## 조치 (완료)

글로벌 CoA(`config/chart_of_accounts.csv`)에 누락 17계정을 추가했다(458→475계정). 결정: 글로벌
CoA를 detector SoT로 유지하는 최소 변경(데이터셋 CoA 우선참조로 detector 로직을 바꾸지 않음).

- 추가 계정(gl_account, account_name_kr): 106100 단기투자자산 / 116100 계약자산 / 117100 단기대여금 /
  117900 가지급금 / 119100 대손충당금 / 123100 재공품 / 131100 개발비 / 139100 무형자산상각누계액 /
  151900 건설중인자산 / 160100 투자자산 / 169100 투자자산평가충당금 / 231100 계약부채 / 237100 충당부채 /
  412100 공사수익 / 469100 대손충당금환입 / 681100 무형자산상각비 / 682100 손상차손.
- **검증:** IntegrityDetector 재실행 → L1-03 발화 **6,178 → 0**(신규 17계정 0). 글로벌 CSV 재로드
  475계정·17계정 존재·기존행 보존·mojibake 0. CoA 파일 멤버십을 참조하는 detector는 IntegrityDetector
  하나뿐(variance_layer의 valid_accounts는 빈값 체크라 무관). **v32 전체 measure 재측정에서도 L1-03=0
  확정**(글로벌 CoA 누락 사용계정 0).
- **L1-02 9,736:** CoA 무관(v32에서도 9,736 불변). 진짜 원인은 document_date 형식 비일관을 날짜 파싱이
  NaT화한 거짓 발화 → 날짜 파싱 `format="ISO8601"` 견고화로 **0 해소**(위 §"L1-02 9,736 → 0").

> 데이터(v31c)는 글로벌 CoA와 무관하므로 재생성 불필요. 수정은 config/detector 측만.
