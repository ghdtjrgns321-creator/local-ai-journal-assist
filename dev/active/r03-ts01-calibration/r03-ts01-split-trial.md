# R03 / TS01 분리 trial — 통합 T100 손실 원인 분리 (fitting guard)

> **목적**: 직전 R03+TS01 동시 trial 에서 PHASE2 단독 T100 은 +12.74pp 회복됐으나 통합 큐 T100 이 -1.29pp 손실되어 rollback 됐다. R03 alone / TS01 alone 으로 분리 측정해 **둘 중 어느 변경이 통합 T100 손실의 주범인지** 분리한다. 분리 결과에 따라 단독 적용 여부 또는 보조 보완 방안 (옵션 2-a weighted RRF / 옵션 2-b family weight) 결정 근거를 만든다.
>
> **작성일**: 2026-05-23
> **선행**:
> - 직전 동시 trial 결과: `artifacts/phase2_r03_ts01_fix_before_after_fixed4_20260523.md`
> - 자연 분포 조사: `artifacts/r03_ts01_natural_distribution_fixed4_20260523.{json,md}` (재사용 — 다시 측정 안 함)
> - 기존 계획: `dev/active/r03-ts01-calibration/r03-ts01-calibration-plan.md`
>
> **fitting guard (재인용)**: 본 분리 trial 의 어떤 결정도 truth recall 곡선 grid search 로 정당화하지 않는다. 사용 값은 직전 trial 의 정상 분포 분위수 기반 값을 **그대로 재사용**한다. 새 값을 찾지 않는다. recall 변화는 결과로만 기록.

---

## 1. 직전 동시 trial 에서 그대로 가져오는 값 (fitting 방지)

직전 trial 에서 정상 (truth-negative) 분포 q95 / q99 + 회계 도메인 근거로 결정한 값을 **변경 없이 재사용**한다:

```
R03 변경값 (Phase A 에서 사용):
  src/detection/relational_rules.py:144
    deviation_threshold:  0.15  → 1.0    (truth-negative q95 ≈ 0.9995 반올림)
    min_ic_pairs:         3     → 5      (그룹 통계 유의미 최소 표본)

TS01 변경 (Phase B 에서 사용):
  src/detection/timeseries_rules.py
    함수 default sigma:   3.0   → 3.30   (truth-negative q99)
  + detector 등록 레벨에서 TS01 dormant 처리
    (timeseries family max score 0.8 → 0.4, TS02 만 active)
```

직전 trial 의 적용 방식과 정확히 동일하게 (한 변경 씩만 적용하는 것만 다름).

---

## 2. 분리 trial 흐름

```
Phase A: R03 단독 적용
  ├─ R03 변경 (TS01 = 기존 active sigma=3.0 유지)
  ├─ 캐시 무효화 + 재측정
  ├─ rollback 조건 평가
  ├─ AFTER_R03_ONLY 접미사로 산출물 보존
  └─ R03 변경 rollback (TS01 비교를 위해 BEFORE 상태로 복귀)

Phase B: TS01 단독 적용
  ├─ TS01 dormant + sigma 3.30 적용 (R03 = 기존 0.15/3 유지)
  ├─ 캐시 무효화 + 재측정
  ├─ rollback 조건 평가
  ├─ AFTER_TS01_ONLY 접미사로 산출물 보존
  └─ TS01 변경 rollback (BEFORE 상태로 복귀)

Phase C: 결과 종합 + 결정
  ├─ R03 alone / TS01 alone / 동시 (직전 trial) 3종 비교 표
  ├─ 통합 T100 손실 주범 판정
  ├─ 단독 적용 여부 또는 보조 변경 (옵션 2-a/2-b) 권장
  └─ 보고서 작성
```

---

## 3. Phase A — R03 단독 trial

### 3.1 코드 변경

`src/detection/relational_rules.py:144` — default 값 변경:

```python
def r03_transfer_pricing_anomaly(
    df: pd.DataFrame,
    *,
    deviation_threshold: float = 1.0,   # was 0.15
    min_ic_pairs: int = 5,              # was 3
) -> pd.Series:
```

`config/settings.py` — 해당 키가 있으면 함께 변경 (직전 trial 에서 사용자가 추가한 키가 있을 수 있음. `grep -n "r03\|deviation_threshold\|min_ic_pairs" config/settings.py` 로 확인 후 동일하게 처리).

`src/detection/relational_matcher.py` (또는 RelationalDetector) — settings 에서 읽도록 연결됐는지 확인.

**TS01 은 손대지 않는다** (기존 sigma=3.0, detector active 유지).

### 3.2 캐시 무효화

```bash
cp artifacts/stage7_fixed4_phase2_family_by_doc.parquet artifacts/stage7_fixed4_phase2_family_by_doc.BEFORE_SPLIT_TRIAL.parquet
cp artifacts/phase1_phase2_integration_report_fixed4_20260523.json artifacts/phase1_phase2_integration_report_fixed4_BEFORE_SPLIT_TRIAL.json
cp artifacts/phase2_family_combination_audit_fixed4_20260523.json artifacts/phase2_family_combination_audit_fixed4_BEFORE_SPLIT_TRIAL.json
cp artifacts/phase2_family_rule_noise_fixed4_20260523.json artifacts/phase2_family_rule_noise_fixed4_BEFORE_SPLIT_TRIAL.json
rm artifacts/stage7_fixed4_phase2_family_by_doc.parquet
```

### 3.3 재측정 3종 + 1종

```bash
uv run python tools/scripts/phase1_phase2_integration_fixed4.py
uv run python tools/scripts/phase2_family_combination_audit_fixed4.py
uv run python tools/scripts/analyze_family_rule_noise_fixed4.py
```

### 3.4 rollback 조건 평가

| 지표 | BEFORE (IC fix 후 state) | rollback 조건 | 측정 결과 (Phase A) | 판정 |
|---|---|---|---|---|
| PHASE2 단독 T100 | 6.94% | 하락 -1pp 이상 | __% | __ |
| **통합 T100** | **20.16%** | **하락 -1pp 이상** | **__%** | **__** |
| R03 row truth ratio | 0.28% | 새 ratio < 이전 | __% | __ |

판정 룰:
- 통합 T100 ≥ 19.16% (= 20.16% - 1pp) → **R03 단독 통과**
- 통합 T100 < 19.16% → **R03 단독 rollback**

### 3.5 산출물 보존 + 코드 rollback

판정과 무관하게 **반드시 코드는 BEFORE 상태로 rollback** (Phase B 비교를 위해):

```bash
# 산출물 보존
cp artifacts/stage7_fixed4_phase2_family_by_doc.parquet artifacts/stage7_fixed4_phase2_family_by_doc.AFTER_R03_ONLY.parquet
cp artifacts/phase1_phase2_integration_report_fixed4_20260523.json artifacts/phase1_phase2_integration_report_fixed4_AFTER_R03_ONLY.json
cp artifacts/phase2_family_combination_audit_fixed4_20260523.json artifacts/phase2_family_combination_audit_fixed4_AFTER_R03_ONLY.json
cp artifacts/phase2_family_rule_noise_fixed4_20260523.json artifacts/phase2_family_rule_noise_fixed4_AFTER_R03_ONLY.json

# 코드 rollback (R03 default 와 settings 모두 0.15 / 3 으로 복원)
# active 캐시도 BEFORE_SPLIT_TRIAL 로 복원
cp artifacts/stage7_fixed4_phase2_family_by_doc.BEFORE_SPLIT_TRIAL.parquet artifacts/stage7_fixed4_phase2_family_by_doc.parquet
cp artifacts/phase1_phase2_integration_report_fixed4_BEFORE_SPLIT_TRIAL.json artifacts/phase1_phase2_integration_report_fixed4_20260523.json
cp artifacts/phase2_family_combination_audit_fixed4_BEFORE_SPLIT_TRIAL.json artifacts/phase2_family_combination_audit_fixed4_20260523.json
cp artifacts/phase2_family_rule_noise_fixed4_BEFORE_SPLIT_TRIAL.json artifacts/phase2_family_rule_noise_fixed4_20260523.json
```

### 3.6 SHA256 검증

```bash
PYTHONIOENCODING=utf-8 uv run python -c "
import hashlib, pathlib
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:16]
pairs = [
    ('artifacts/stage7_fixed4_phase2_family_by_doc.parquet', 'artifacts/stage7_fixed4_phase2_family_by_doc.BEFORE_SPLIT_TRIAL.parquet'),
    ('artifacts/phase1_phase2_integration_report_fixed4_20260523.json', 'artifacts/phase1_phase2_integration_report_fixed4_BEFORE_SPLIT_TRIAL.json'),
]
for a, b in pairs:
    print(f'{a.split(chr(47))[-1]:60s} {sha(a)} vs BEFORE {sha(b)} {\"=\" if sha(a)==sha(b) else \"!=\"}')"
```

→ 모두 `=` 확인. 다르면 Phase B 진행 금지.

---

## 4. Phase B — TS01 단독 trial

### 4.1 코드 변경

**R03 은 손대지 않는다** (기존 0.15 / 3 유지 — Phase A rollback 후 상태).

`src/detection/timeseries_rules.py:14` — default sigma:

```python
def ts01_transaction_burst(
    df: pd.DataFrame,
    window_days: int = 7,
    sigma: float = 3.30,                # was 3.0 (truth-negative q99)
) -> pd.Series:
```

Detector 등록 레벨에서 TS01 dormant 처리 — 직전 trial 에서 사용한 방식 그대로:
- timeseries detector 가 TS01 을 family score 에 포함하지 않도록 설정
- 또는 settings 에 `ts01_active = False` 같은 키가 있으면 그걸 사용
- (정확한 방법은 직전 trial git history 또는 `grep -n "ts01\|TS01\|timeseries" config/settings.py src/detection/timeseries_matcher.py` 로 확인)

### 4.2 캐시 무효화 + 재측정 + rollback 조건 평가

3.2 ~ 3.4 단계와 동일. 산출물 접미사만 `AFTER_TS01_ONLY` 로 변경.

판정 룰 (Phase A 와 동일):
- 통합 T100 ≥ 19.16% → **TS01 단독 통과**
- 통합 T100 < 19.16% → **TS01 단독 rollback**

### 4.3 산출물 보존 + 코드 rollback

3.5 와 동일. 산출물 접미사 `AFTER_TS01_ONLY`. 코드는 sigma 3.0 + TS01 detector active 로 복원.

### 4.4 SHA256 검증

3.6 와 동일. Phase C 진행 전 active 캐시가 BEFORE_SPLIT_TRIAL 과 일치 확인.

---

## 5. Phase C — 결과 종합 + 결정

### 5.1 비교 표 작성

`artifacts/phase2_r03_ts01_split_trial_fixed4_<DATE>.md` 신규 작성:

```
| 큐                    | BEFORE   | Phase A (R03 alone) | Phase B (TS01 alone) | 직전 동시 trial | 동시 trial Δ |
|---|---:|---:|---:|---:|---:|
| PHASE2 단독 T100      | 6.94%    |  __%                |  __%                 | 19.68%          | +12.74pp     |
| PHASE2 단독 T500      | 34.68%   |  __%                |  __%                 | 25.97%          | -8.71pp      |
| PHASE2 단독 T1000     | 40.65%   |  __%                |  __%                 | 54.35%          | +13.71pp     |
| PHASE2 단독 T2000     | 58.55%   |  __%                |  __%                 | 58.55%          | ±0.00pp      |
| 통합 T100             | 20.16%   |  __%                |  __%                 | 18.87%          | -1.29pp      |
| 통합 T500             | 42.10%   |  __%                |  __%                 | 45.00%          | +2.90pp      |
| 통합 T1000            | 49.84%   |  __%                |  __%                 | 52.74%          | +2.90pp      |
| 통합 T2000            | 58.87%   |  __%                |  __%                 | 60.97%          | +2.10pp      |
```

```
| sub-detector | BEFORE        | Phase A (R03 alone)  | Phase B (TS01 alone) |
| TS01 row hit | 52,787        | (변화 없음)           |  __                  |
| TS01 doc recall | 1.45%      | (변화 없음)           |  __%                 |
| R03 row hit  | 23,389        |  __                  | (변화 없음)           |
| R03 doc recall | 5.48%      |  __%                 | (변화 없음)           |
```

### 5.2 판정 매트릭스

```
                    Phase A (R03)            Phase B (TS01)         결론
─────────────────────────────────────────────────────────────────────────────────────
통과 + 통과         통합 T100 회복 가능?     R03+TS01 둘 다 OK?    동시 trial 의 -1.29pp 은 측정 변동 가능성. 동시 적용 재검토.
통과 + rollback     R03 단독 적용 추천       -                     R03 만 적용 → 효과 부분 회수.
rollback + 통과     -                        TS01 단독 적용 추천   TS01 만 적용 → 효과 부분 회수.
rollback + rollback 양쪽 모두 부정적          -                     PHASE2 ranking 변화가 RRF 합의 본질적 문제. 옵션 2-a (weighted RRF) 검토 필요.
```

### 5.3 후속 권장 (Phase C 결과에 따라)

| 판정 결과 | 다음 액션 |
|---|---|
| Phase A 통과 | R03 단독 적용 PR — `feat(detection): R03 deviation_threshold 1.0 + min_ic_pairs 5` |
| Phase B 통과 | TS01 단독 적용 PR — `feat(detection): TS01 dormant 처리` |
| 양쪽 통과 | 단일 단독 적용 우선 (PHASE2 단독 효과 큰 쪽). 동시 적용은 별도 RFC. |
| 양쪽 rollback | 옵션 2-a (PHASE1 weight 2x RRF) 별도 trial RFC 작성. R03/TS01 calibration 은 RRF 변경 후 재시도. |

### 5.4 운영 문서 갱신

판정 결과와 무관하게 다음 문서 갱신:

- `docs/guide/users/13_PHASE2_AGGREGATION_AUDIT.md`: 분리 trial 결과 §추가
- `docs/debugging.md`: split trial trouble-shooting 기록
- `dev/active/r03-ts01-calibration/`: 본 분기 trial 완료 + completed/ 이동 검토

---

## 6. fitting guard 체크리스트

```
Phase A:
  □ R03 변경값을 직전 trial 과 동일하게 1.0 / 5 로 사용 (새 값 grid search 금지)
  □ TS01 은 절대 손대지 않음
  □ rollback 조건 (통합 T100 -1pp 이상) 을 측정 전 명시
  □ 측정 후 "더 좋은 값으로 재조정" 유혹 거절

Phase B:
  □ TS01 변경 방식을 직전 trial 과 동일하게 (dormant + sigma 3.30)
  □ R03 은 절대 손대지 않음
  □ rollback 조건 동일
  □ "TS02 도 같이 손대면 더 좋지 않을까" 같은 비범위 작업 금지

Phase C:
  □ 비교 표는 informational 로만 기록
  □ 어느 phase 가 best recall 인지 보고 운영 변경 결정 X
  □ 도메인 정합성 + rollback 통과 여부 두 기준으로만 결정
  □ 양쪽 rollback 시 옵션 2-a 등 RRF 변경은 별도 RFC (이번에 강행 금지)
```

---

## 7. Rollback 조건 (각 Phase 동일)

| 조건 | 임계 | 조치 |
|---|---|---|
| PHASE2 단독 T100 recall 하락 | -1pp 이상 | 해당 phase rollback |
| **통합 큐 T100 recall 하락** | **-1pp 이상** | **해당 phase rollback** (직전 trial 과 동일 조건) |
| 새 row truth ratio 가 BEFORE 보다 낮아짐 | -10% 이상 (상대) | 해당 phase rollback + 원인 분석 |
| 코드 SHA256 검증 실패 (rollback 후 BEFORE 와 다름) | - | Phase 진행 중지, 수동 복원 |

---

## 8. 산출물 명세

| 위치 | 내용 | 단계 |
|---|---|---|
| `artifacts/stage7_fixed4_phase2_family_by_doc.BEFORE_SPLIT_TRIAL.parquet` | 분리 trial 시작 시점 baseline (= 현재 active = IC fix 후) | Phase A 시작 시 |
| `artifacts/phase1_phase2_integration_report_fixed4_BEFORE_SPLIT_TRIAL.json` | 동상 | 동상 |
| `artifacts/phase2_family_combination_audit_fixed4_BEFORE_SPLIT_TRIAL.json` | 동상 | 동상 |
| `artifacts/phase2_family_rule_noise_fixed4_BEFORE_SPLIT_TRIAL.json` | 동상 | 동상 |
| `artifacts/*_AFTER_R03_ONLY.{parquet,json}` | Phase A 측정 결과 | Phase A 끝 |
| `artifacts/*_AFTER_TS01_ONLY.{parquet,json}` | Phase B 측정 결과 | Phase B 끝 |
| `artifacts/phase2_r03_ts01_split_trial_fixed4_<DATE>.md` | Phase C 종합 비교 보고서 | Phase C |
| `docs/guide/users/13_PHASE2_AGGREGATION_AUDIT.md` (§ 추가) | 운영 문서 갱신 | Phase C |
| `docs/debugging.md` (분리 trial 기록) | 디버깅 기록 | Phase C |

---

## 9. 비범위 (out-of-scope)

- TS02 calibration
- R02 weight up
- family weight 도입 (옵션 2-b)
- weighted RRF / RRF k 변경 (옵션 2-a/c) — Phase C 에서 양쪽 rollback 시 별도 RFC 로 ↓ 분리
- family pruning (옵션 3)
- 새 값 탐색 (직전 trial 값 그대로 사용)

---

## 10. 다른 프롬프트 진행용 self-contained 시작 가이드

```
# 1. 컨텍스트 확보
cat dev/active/r03-ts01-calibration/r03-ts01-split-trial.md
cat artifacts/phase2_r03_ts01_fix_before_after_fixed4_20260523.md   # 직전 동시 trial
cat artifacts/r03_ts01_natural_distribution_fixed4_20260523.md       # 분포 근거 (재사용)
git log -5 src/detection/relational_rules.py src/detection/timeseries_rules.py  # 직전 trial 변경 위치 참고

# 2. Phase A: R03 단독 trial
#    §3 의 코드 변경 → 캐시 무효화 → 재측정 3종 → rollback 평가 → 산출물 보존 → 코드 rollback → SHA256 검증

# 3. Phase B: TS01 단독 trial
#    §4 동일 패턴

# 4. Phase C: §5 비교 표 + 판정 + 후속 권장 + 문서 갱신
```

---

## 11. 가설 (참고용 — 결정 근거 아님)

```
H1: R03 alone 은 통합 T100 변화 작음.
    근거: R03 hit 23k → 1.2k 로 줄어도 그 1.2k 가 truth-positive 비율 0.88% (3.1배 ↑).
          PHASE2 Noisy-OR 에 미세 영향만 줄 가능성.

H2: TS01 alone 이 통합 T100 손실 주범.
    근거: TS01 dormant 처리 → timeseries family max score 0.8 → 0.4 절반 감소.
          전체 case 의 95% 가 timeseries hit 이므로 PHASE2 ranking 이 크게 재배치.
          PHASE1 composite 와 합의 area 가 줄어 RRF 통합 점수 분산.

H1+H2 가 맞다면 R03 단독 적용이 가장 안전한 결론. 단 가설은 검증용이며
실제 결정은 §5 판정 매트릭스 결과로 한다.
```

---

## 12. 관련 메모리 / 거버넌스

- `feedback_phase1_truth_recall_guard` — PHASE2 동일 적용
- `feedback_ic_matching_traps` — IC02 calibration 사례
- `docs/spec/PHASE2_GOVERNANCE_DESIGN.md` 결정 8 — 5-family Noisy-OR lock (본 trial 은 lock 유지)
- `docs/guide/users/13_PHASE2_AGGREGATION_AUDIT.md` — 합산식 ablation 결론
- 직전 trial rollback 사례: `artifacts/phase2_r03_ts01_fix_before_after_fixed4_20260523.md`
