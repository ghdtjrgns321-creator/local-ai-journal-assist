# R03 / TS01 calibration — IC-style noise 정리 계획 (fitting guard)

> **목적**: IC02/IC01 calibration 과 동일한 정공법으로 R03_transfer_pricing_anomaly 와 TS01_transaction_burst 의 false-positive 를 줄여 PHASE2 단독 큐 / PHASE1+2 통합 큐 recall 을 회수한다.
>
> **작성일**: 2026-05-23
> **선행 분석**:
> - `artifacts/phase2_recall_uplift_options_fixed4_20260523.md` (3가지 옵션 비교 — 본 계획은 옵션 1)
> - `artifacts/phase2_family_rule_noise_fixed4_20260523.json` (sub-detector noise 측정)
> - `artifacts/phase2_ic_fix_before_after_fixed4_20260523.md` (IC fix 효과 — 같은 패턴 재현 시 기대치)
> - `docs/users/13_PHASE2_AGGREGATION_AUDIT.md` (PHASE2 합산식 ablation 결론)
>
> **fitting guard (최우선)**: 본 계획의 어떤 threshold/sigma 값도 **truth recall 보고 결정하지 않는다**. 결정 근거는 ① 정상 (truth-negative) 분포의 분위수 ② 회계 도메인 표준이다. recall 변화는 결과로만 기록한다. `feedback_phase1_truth_recall_guard` 메모리 룰 PHASE2 적용.

---

## 1. 변경 대상 — 진단

`artifacts/phase2_family_rule_noise_fixed4_20260523.json` 측정 결과:

| sub-detector | row hit | doc hit | row truth % | doc recall | 패턴 |
|---|---:|---:|---:|---:|---|
| **R03_transfer_pricing_anomaly** | 23,389 | 14,502 | **0.28%** | 5.48% | IC02 와 동일한 noise dominant 패턴 |
| **TS01_transaction_burst** | 52,787 | 13,838 | **0.04%** | 1.45% | 거의 작동 실패 — hit 의 99.96% 가 noise |

### 1.1 R03 — 현재 코드

`src/detection/relational_rules.py:144-186`:

```python
def r03_transfer_pricing_anomaly(
    df: pd.DataFrame,
    *,
    deviation_threshold: float = 0.15,   # ← 변경 후보
    min_ic_pairs: int = 3,               # ← 변경 후보
) -> pd.Series:
    ...
    deviation = (amount - group_mean).abs() / group_mean.clip(lower=1e-10)
    flagged = valid_group & (deviation > deviation_threshold)
```

문제: `deviation_threshold 0.15` 는 IC pair 의 자연 분산 (할인·환율·세금·반올림) 도 잡는다.
`min_ic_pairs 3` 은 통계적 의미 약함 — 3건만으로 평균 산출 후 편차 비교.

### 1.2 TS01 — 현재 코드

`src/detection/timeseries_rules.py:12-59`:

```python
def ts01_transaction_burst(
    df: pd.DataFrame,
    window_days: int = 7,
    sigma: float = 3.0,                  # ← 변경 후보
) -> pd.Series:
```

진단: 52,787 row hit 중 truth 19건 (row_truth% 0.04%). 통계적으로 random 수준.

**해석 가설** (조사 필요):
- (a) sigma 3.0 이 너무 낮아 정상 burst 도 잡힘 → sigma 상향으로 해결 가능
- (b) burst 자체가 fraud 신호와 정합 안 됨 → dormant 처리가 정공법

---

## 2. fitting guard 원칙

본 계획에서 **금지하는 결정 방식**:

```
❌ "recall 이 회복되는 threshold 값을 grid search 로 찾는다"
❌ "truth_ratio 가 N% 이상이 되는 threshold 를 채택한다"
❌ "PHASE2 / 통합 큐 TOP-N recall 곡선이 최대가 되는 값을 선정한다"
```

**허용하는 결정 방식**:

```
✓ 정상 (truth-negative) 분포의 q90 / q95 / q99 분위수를 새 threshold 로 채택
✓ 회계 실무 표준 (예: 분기당 IC 거래 최소 빈도, 정상 거래 변동성 한도) 인용
✓ ISA / PCAOB / K-IFRS 문헌 인용 근거
✓ truth/non-truth 분리 측정은 calibration 후 결과 검증용으로만 사용
```

---

## 3. 단계별 실행 계획

### Step 1 — 도메인 근거 분포 조사 (calibration 결정 전 필수)

`tools/scripts/r03_ts01_natural_distribution_audit.py` 신규 작성 — 정상 분포 분위수 측정.

#### 3.1 R03 — IC pair deviation 자연 분포

```python
# 의사 코드
for each (trading_partner, gl_account) group with n >= 3:
    deviation = abs(amount - group_mean) / group_mean
# 출력:
#   - all-rows deviation 분위수 (q50, q75, q90, q95, q99)
#   - truth-positive rows deviation 분위수
#   - truth-negative rows deviation 분위수
#   - group size 분포 (min_ic_pairs 결정 근거)
```

#### 3.2 R03 — group size 분포

```python
# IC trading_partner × gl_account 그룹의 거래 빈도 분포
# 출력:
#   - group_count 분위수 (q25, q50, q75, q90)
#   - n=3 / n=5 / n=10 미만 그룹 비율
```

#### 3.3 TS01 — 일별 거래 burst 자연 분포

```python
# 일별 거래 건수를 rolling 7d mean ± k*std 로 정규화
# 출력:
#   - daily count z-score 분위수 (q90, q95, q99)
#   - truth-positive 일자의 z-score 분포
#   - sigma=3 이면 q? 에 해당하는지
```

#### 3.4 산출물

- `artifacts/r03_ts01_natural_distribution_fixed4_<DATE>.json`
- `artifacts/r03_ts01_natural_distribution_fixed4_<DATE>.md` (요약)

---

### Step 2 — 도메인 근거 기반 새 값 결정

분포 조사 결과를 보고 다음 **두 후보 중 하나**를 선택:

#### 2.1 R03 후보

| 결정 항목 | 후보 A (보수적) | 후보 B (공격적) | 도메인 근거 |
|---|---|---|---|
| `deviation_threshold` | 정상 분포 **q95** | 정상 분포 **q99** | "이전가격 5% 변동은 정상 (할인·세금·환율). 95th percentile 초과 시 비정상 가설" |
| `min_ic_pairs` | **5** | **10** | "통계적 평균 산출 최소 표본 — 회계 실무 분기당 IC 거래 최소 빈도" |

선택 기준: 후보 A 가 표준 통계 임계. 후보 B 는 더 보수적 (false-positive 더 줄임).

#### 2.2 TS01 후보

| 결정 | 선택 조건 | 도메인 근거 |
|---|---|---|
| **TS01 dormant 처리** (default settings 에서 비활성) | Step 1 분포에서 truth-positive 와 truth-negative 의 z-score 분포가 분리 안 됨 | "TS01 burst signal 이 fraud 와 통계적 정합 없음. 활성화는 별도 도메인 근거 필요." |
| `sigma` 상향 (3.0 → q99 z-score) | 분포 분리됨 + q99 임계 합리적 | "정상 분포 99th percentile 만 burst 로 인정" |

**fitting guard 적용**: TS01 dormant 처리는 측정 결과 (truth/non-truth 분리 안 됨) **자체가 도메인 근거**다 — recall 보고 결정하는 게 아니다.

---

### Step 3 — 코드 변경

#### 3.1 R03 변경

`src/detection/relational_rules.py:144` — default 값 변경:

```python
def r03_transfer_pricing_anomaly(
    df: pd.DataFrame,
    *,
    deviation_threshold: float = <Step 2 에서 결정>,  # 0.15 → ?
    min_ic_pairs: int = <Step 2 에서 결정>,           # 3 → ?
) -> pd.Series:
```

또한 `config/settings.py` 에 별도 setting 으로 분리:

```python
relational_r03_deviation_threshold: float = <new>
relational_r03_min_ic_pairs: int = <new>
```

그리고 `src/detection/relational_matcher.py` (또는 RelationalDetector) 가 settings 에서 읽도록 연결. IC02 변경 패턴과 동일.

#### 3.2 TS01 변경 — 후보별

**dormant 처리 선택 시**:
- `src/services/phase2_training_service.py` 또는 settings 에서 TS01 active=False 설정
- 또는 `src/detection/timeseries_matcher.py` (TimeseriesDetector) 에서 TS01 등록 제외 옵션
- TS02 는 그대로 active 유지

**sigma 상향 선택 시**:
- `src/detection/timeseries_rules.py:14` default `sigma: float = <new>`
- `config/settings.py` 에 setting 추가
- Detector 가 settings 에서 읽도록 연결

---

### Step 4 — 캐시 무효화 + 재측정

#### 4.1 캐시 백업 + 무효화

```bash
cp artifacts/stage7_fixed4_phase2_family_by_doc.parquet artifacts/stage7_fixed4_phase2_family_by_doc.BEFORE_R03_TS01_FIX.parquet
cp artifacts/phase1_phase2_integration_report_fixed4_20260523.json artifacts/phase1_phase2_integration_report_fixed4_BEFORE_R03_TS01_FIX.json
cp artifacts/phase2_family_combination_audit_fixed4_20260523.json artifacts/phase2_family_combination_audit_fixed4_BEFORE_R03_TS01_FIX.json
cp artifacts/phase2_family_rule_noise_fixed4_20260523.json artifacts/phase2_family_rule_noise_fixed4_BEFORE_R03_TS01_FIX.json
rm artifacts/stage7_fixed4_phase2_family_by_doc.parquet
```

#### 4.2 재실행 명령

```bash
# 1. PHASE2 family score 재계산 + integration 재측정
uv run python tools/scripts/phase1_phase2_integration_fixed4.py

# 2. 31개 family combination ablation 재측정
uv run python tools/scripts/phase2_family_combination_audit_fixed4.py

# 3. sub-detector noise 비율 재측정 (변경 후 noise 패턴 확인용)
uv run python tools/scripts/analyze_family_rule_noise_fixed4.py
```

---

### Step 5 — 전후 비교 보고서 작성

`artifacts/phase2_r03_ts01_fix_before_after_fixed4_<DATE>.md` 신규 작성.

비교 항목:
1. R03 / TS01 hit 변화 (BEFORE → AFTER, IC fix BEFORE 와 같은 형식)
2. UTRDI 5-family 풀세트 recall 변화 (PHASE2 단독 / 통합 큐 모두)
3. fixed3 → fixed4 격차 추가 회수율
4. 31개 family combination 의 best subset 변화 (UTRDI 가 best 가 되는지 확인)
5. fitting guard 체크리스트

비교 형식 표준은 `artifacts/phase2_ic_fix_before_after_fixed4_20260523.md` 와 동일.

---

### Step 6 — 운영 문서 갱신

`docs/users/13_PHASE2_AGGREGATION_AUDIT.md` 에 R03/TS01 fix 결과 섹션 추가 (IC fix 갱신과 동일한 형식). §7 family weight 옵션 추가 검토 여부 결정.

`docs/debugging.md` 에 R03/TS01 calibration trouble-shooting 기록.

---

## 4. fitting guard 체크리스트 (Step 별)

```
Step 1 (분포 조사):
  □ 정상 + truth 분리 측정한 분포 q90/q95/q99 표를 산출했는가?
  □ 표가 informational 임을 명시했는가 (운영식 정당화 근거 아님)?

Step 2 (값 결정):
  □ 새 threshold 값을 recall 곡선이 아닌 분포 분위수로 결정했는가?
  □ 회계 도메인 근거 (ISA/PCAOB/K-IFRS 또는 실무 표준) 를 명시했는가?
  □ "후보 A vs B" 중 보수적 (q95) 채택 또는 더 보수적 (q99) 채택 사유를 적었는가?

Step 3 (코드 변경):
  □ default 값과 settings 값을 모두 변경했는가?
  □ Detector 호출 경로가 settings 를 읽도록 연결됐는가?
  □ 변경 전 git diff 를 보관했는가 (rollback 가능)?

Step 4 (재측정):
  □ 캐시 백업을 BEFORE 접미사로 보관했는가?
  □ 재실행 3개 스크립트가 모두 완료됐는가?
  □ 측정 결과를 informational 로만 기록하는가?

Step 5 (보고서):
  □ recall 회복이 미흡해도 threshold 재조정 금지를 명시했는가?
  □ "측정 결과를 보고 더 좋은 값으로 재조정" 유혹을 거절했는가?
  □ fixed4 한정 측정임을 명시했는가 (실데이터 재검증 필요)?

Step 6 (문서):
  □ 13번 §7 family weight 옵션 RFC 활성화 여부를 별도 결정했는가?
  □ 본 계획이 IC fix 패턴 재현임을 명시했는가?
```

---

## 5. 예상 효과 (참고용 — 결정 근거 아님)

`artifacts/phase2_recall_uplift_options_fixed4_20260523.md` §1.3 의 추정:

```
조치                  PHASE2 단독 T100 변화   통합 T100 변화   비고
R03 calibration       +1~2pp                 +0.5~1pp        IC fix 효과 추정에 의함
TS01 dormant          recall 거의 무변화      ranking 안정화   hit 52k 정리
R03 + TS01 합산       +1~2pp                 +0.5~1pp        통합 recall T500 격차 일부 해소 가능
```

**경고**: 위 추정치는 의사결정 근거 아님. 실제 효과는 Step 4 측정 결과로 결정한다.

---

## 6. Rollback 조건

다음 중 하나라도 발생하면 변경 rollback (BEFORE_R03_TS01_FIX 캐시 복원):

| 조건 | 임계 | 조치 |
|---|---|---|
| PHASE2 단독 큐 T100 recall **하락** | -1pp 이상 | rollback + 원인 분석 |
| 통합 큐 T100 recall **하락** | -1pp 이상 | rollback + 원인 분석 |
| 31-combo ablation 의 UTRDI 가 best 가 되지 못함 | (변경 전과 동일) | OK — 부분 개선만으로도 진행 가능 |
| 새 truth_ratio 가 변경 전보다 **낮아짐** | -10% 이상 | rollback (도메인 근거 재검토) |

---

## 7. 다른 프롬프트 진행용 self-contained 시작 가이드

다음 프롬프트에서 본 계획대로 작업할 때 사용할 첫 명령:

```
# 1. 작업 컨텍스트 확보
cat dev/active/r03-ts01-calibration/r03-ts01-calibration-plan.md
cat artifacts/phase2_family_rule_noise_fixed4_20260523.json
cat src/detection/relational_rules.py  # R03 정의 확인
cat src/detection/timeseries_rules.py  # TS01 정의 확인

# 2. Step 1: 자연 분포 조사 스크립트 작성
#    tools/scripts/r03_ts01_natural_distribution_audit.py
#    - 입력: artifacts/phase1_manipulation_v7_fixed4_case_input.pkl
#    - 출력: artifacts/r03_ts01_natural_distribution_fixed4_<DATE>.{json,md}

# 3. Step 2: 분위수 표 + 도메인 근거 명시 후 값 결정
# 4. Step 3: code 변경 (R03 default + settings + detector 연결, TS01 dormant or sigma)
# 5. Step 4: 캐시 백업 + 재측정 3종
# 6. Step 5: 전후 비교 보고서 작성
# 7. Step 6: 13번 + debugging.md 갱신
```

---

## 8. 산출물 목록 (예정)

| 위치 | 내용 | 단계 |
|---|---|---|
| `tools/scripts/r03_ts01_natural_distribution_audit.py` | 자연 분포 조사 스크립트 (신규) | Step 1 |
| `artifacts/r03_ts01_natural_distribution_fixed4_<DATE>.{json,md}` | 분포 조사 결과 | Step 1 |
| `src/detection/relational_rules.py` (R03 default 변경) | 코드 변경 | Step 3 |
| `src/detection/timeseries_rules.py` (TS01 sigma 또는 dormant) | 코드 변경 | Step 3 |
| `config/settings.py` (R03 / TS01 settings 추가) | 코드 변경 | Step 3 |
| `src/detection/relational_matcher.py` (settings 연결, 필요 시) | 코드 변경 | Step 3 |
| `artifacts/stage7_fixed4_phase2_family_by_doc.BEFORE_R03_TS01_FIX.parquet` | 캐시 백업 | Step 4 |
| `artifacts/phase1_phase2_integration_report_fixed4_BEFORE_R03_TS01_FIX.json` | 측정 백업 | Step 4 |
| `artifacts/phase2_family_combination_audit_fixed4_BEFORE_R03_TS01_FIX.json` | ablation 백업 | Step 4 |
| `artifacts/phase2_r03_ts01_fix_before_after_fixed4_<DATE>.md` | 전후 비교 보고서 | Step 5 |
| `docs/users/13_PHASE2_AGGREGATION_AUDIT.md` (§ 추가) | 운영 문서 갱신 | Step 6 |
| `docs/debugging.md` (calibration trouble-shooting) | 디버깅 기록 | Step 6 |

---

## 9. 비범위 (out-of-scope)

본 계획에서 다루지 **않는** 항목 (향후 별도 RFC):

- TS02_unusual_frequency calibration — 변경 시 recall 76.45% 손실 위험, 별도 분석 필요
- R02_dormant_account weight up — 13번 §7 family weight RFC 와 함께 다룰 후보
- R01_new_counterparty — 균형 양호, 변경 불요
- family weight (옵션 2-b) — 13번 §7 보류 항목 (별도 RFC)
- max_ecdf 결합식 변경 (옵션 2-c) — governance D8 재검토 필요
- family pruning (옵션 3) — 비권장으로 결론

---

## 10. 관련 메모리 / 거버넌스

- `feedback_phase1_truth_recall_guard` — PHASE2 동일 적용
- `feedback_ic_matching_traps` — IC02 calibration 사례 (선행 패턴)
- `docs/PHASE2_GOVERNANCE_DESIGN.md` 결정 8 — 5-family Noisy-OR lock (본 계획은 lock 유지)
- `docs/TROUBLESHOOT.md` TS-15 — Noisy-OR 채택 근거
- `docs/users/13_PHASE2_AGGREGATION_AUDIT.md` — 합산식 ablation 결론
- `AGENTS.md` "review-only signals must not become confirmed violations" (IC01 evidence_level 분리 근거)
