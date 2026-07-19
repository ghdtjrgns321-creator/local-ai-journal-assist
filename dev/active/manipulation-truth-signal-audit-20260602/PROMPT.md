# Manipulation Truth 신호 유효성 전수 검사 프롬프트

작성: 2026-06-02
배경: IC `circular_related_party_transaction` truth(34건)가 "라벨은 이상인데 실제
탐지 신호가 없는" 무신호 데이터임이 측정으로 밝혀졌다. 같은 결함이 다른
manipulation scenario / family truth 에도 있는지 **전수**로 검증한다.

---

## 0. 목적과 판정 기준

각 manipulation scenario / PHASE2 family primary truth 가 **의도한 detector 의 신호로
진짜 잡히는지** 검증하고, 다음 4종으로 판정한다.

| 판정 | 의미 | 후속 |
|---|---|---|
| **HEALTHY** | 의도 detector 의 sub-signal 이 truth 를 높은 lift 로 잡고, truth 가 의도한 이상 구조를 실제로 보유 | 유지 |
| **SHORTCUT** | 잡히긴 하나 컨닝(구조 마커·생성 흔적·단일전표 self-balanced 등) 또는 우연(다른 목적 룰과 겹침) | 생성 구조 재현실화 |
| **MISLABELED** | 의도 family 가 아닌 다른 family/detector 가 잡음. 책임 배정 오류 | family 재배정 |
| **NOSIGNAL** | 의도한 이상 구조 자체가 데이터에 없음(circular 인데 순환 아님 등). 어느 detector 도 우연 외엔 못 잡음 | truth 재생성 |

판정 임계(가이드):
- `lift = truth_rate / normal_rate`. lift ≥ 2 AND truth_rate ≥ 0.5 → 신호 후보.
- lift ≈ 1 (0.7~1.5) → 구분력 없음(SHORTCUT 또는 NOSIGNAL 의심).
- truth_rate = 0 → 의도 신호가 truth 를 전혀 못 잡음(NOSIGNAL 또는 MISLABELED).
- 잡는 신호가 "구조 마커"(예: 단일전표 self-balanced, 고정 시각, 고정 계정)면 SHORTCUT.

---

## 1. 검사 대상 (8 scenario / family)

데이터셋: `data/journal/primary/datasynth_manipulation_v7_independent_semanticfix8d_familyfix_20260602`
(또는 최신 후보). truth: `labels/manipulated_entry_truth.csv` (620 docs).

| # | scenario | n | 의도 owner family | 의도 detector / 핵심 신호 | "진짜 이상 구조"의 정의 |
|---|---|---|---|---|---|
| 1 | circular_related_party_transaction | 34 | intercompany→**relational 재검토** | GR01(Johnson N-hop cycle) 로직을 relational(=graph/entity anomaly family)에 편입 / IC01-03 대사 | A→B→C→A 3-hop+ 순환 엣지, 1천만+ |
| 2 | unusual_timing_manipulation | 21 | timeseries | TimeseriesDetector TS01/TS02, backdating | 시점 이상(주말·야간·backdating·기간귀속) |
| 3 | embezzlement_concealment | 76 | relational 24 + duplicate 28 | RelationalDetector R01-07 / DuplicateDetector | 은닉 관계(공유 bank/addr) · 중복 결제 |
| 4 | fictitious_entry | 168 | phase1 | 가공 분개 룰(L-시리즈) | 실재성 결여 분개 |
| 5 | expense_capitalization | 100 | phase1 | 비용 자본화 룰 | 비용→자산 오분류 |
| 6 | suspense_account_abuse | 100 | phase1 | 가계정 남용 룰 | 미결산 가계정 잔류 |
| 7 | approval_sod_bypass | 29 | phase1 | 승인·SoD 룰(L1-06 등) | 승인한도·직무분리 위반 |
| 8 | (statistical broad) | 139 | unsupervised | VAE/ECDF 이상점수 | 다변량 통계 이상 |

추가: period_end_adjustment_manipulation(92)은 timeseries context. duplicate/relational
companion 도 함께 점검.

---

## 2. 검증 5단계 (family 단위로 분할 실행 가능)

각 family/scenario 에 대해 아래 5단계를 수행한다. **family 하나씩 독립 실행 가능**하므로
시간이 오래 걸리면 분할한다(예: 1회차 intercompany+graph, 2회차 timeseries,
3회차 relational+duplicate, 4회차 unsupervised, 5회차 phase1 4종).

### Step 1 — 의도 매핑 확인
해당 scenario truth 의 owner 컬럼(`injected_*_primary`, `*_primary_target`,
`truth_owner_primary`, `statistical_anomaly_role`)과 §1 표의 의도 detector 를 대조.
감사기준 근거를 `docs/spec/DETECTION_REFERENCE.md` 에서 확인(예: circular=ISA 550 위상,
IC 대사=ISA 600).

### Step 2 — 신호 discrimination 측정 (핵심)
의도 detector 를 전체 journal 에 돌려 `DetectionResult.details` 의 각 sub-signal 컬럼별로
doc 단위 max score 를 구하고:
- `truth_rate` = truth doc 중 score>0 비율
- `normal_rate` = 동일 모집단의 비-truth doc 중 score>0 비율
- `lift = truth_rate / normal_rate`

템플릿: `tools/scripts/ic_signal_discrimination_probe_20260602.py` 를 family 별로 복제·수정
(detector·truth 컬럼·모집단만 교체). 출력은 `artifacts/<family>_signal_discrimination_*.json`.

### Step 3 — truth 구조 검증
truth 가 §1 표의 "진짜 이상 구조"를 **데이터로 실제 보유**하는지 확인. detector 와
독립적으로 raw 데이터에서 직접 측정한다. 예:
- circular: doc별 (company_code→trading_partner) 엣지를 모아 networkx 로 cycle 탐지.
  2-cycle 만 있고 3-hop+ 없으면 NOSIGNAL.
- duplicate: truth 쌍이 실제 (vendor·amount·date 근접) 중복 구조인지. drift 후에도 유효한지.
- timing: truth 의 posting hour·weekday·backdating(posting_date < document_date) 분포가
  정상과 분리되는지.
- IC reconciliation: counterparty pair 단위 rec_sum vs pay_sum 불일치가 실제 존재하는지.
  self-balanced(단일doc rec+pay 균형)면 대사 신호 없음.

### Step 4 — cross-family / 컨닝 검출
- truth 를 **다른 family detector** 도 잡는지 측정(책임 혼선 → MISLABELED 후보).
  예: circular 을 relational R06 이 18/34 잡았으나 R06 은 user-account degree 룰(우연).
- 잡는 신호가 "생성 흔적·구조 마커"인지 점검: 단일전표 self-balanced, 고정 시각(예: 21:00),
  고정 계정 prefix, `-UNMATCHED` 류 접미사, 동일 reference 패턴. 이런 것이면 SHORTCUT.
  (참고: `docs/spec/PHASE2_FITTING_AUDIT.md` §9 IC structural tier separability 사례.)

### Step 5 — 판정 + 권고
§0 표 기준으로 HEALTHY / SHORTCUT / MISLABELED / NOSIGNAL 판정하고, 각 판정에 대해
DataSynth 수정 권고(재생성/재배정/구조 현실화)를 1~2줄로 기술.

---

## 3. 산출물

`artifacts/manipulation_truth_signal_audit_20260602.json` (또는 family 분할 파일):

```
{
  "<scenario_or_family>": {
    "n": <truth docs>,
    "intended_owner": "...",
    "intended_detector_signals": {"<col>": {"truth_rate":, "normal_rate":, "lift":}},
    "structure_check": {"expected": "...", "observed": "...", "valid": true/false},
    "cross_family_catch": {"<other_family>": "<recall>"},
    "shortcut_markers": ["..."],
    "verdict": "HEALTHY|SHORTCUT|MISLABELED|NOSIGNAL",
    "datasynth_recommendation": "..."
  }
}
```

마지막에 요약표(scenario × verdict) + DataSynth 수정 우선순위 목록.

---

## 4. 기존 측정 자산 (재사용)

이미 IC 에 대해 수행된 측정 — 다른 family 검사의 템플릿:
- `tools/scripts/ic_signal_discrimination_probe_20260602.py` — Step 2 신호 lift
- `tools/scripts/ic_truth_strength_probe_20260601.py` — tier separability / review_cost
- `tools/scripts/circular_ownership_probe_20260602.py` — Step 4 cross-family (graph/relational)
- IC 판정 결과(참고 사례): **circular = NOSIGNAL** (순환 구조 부재, 회사 3개·2-cycle만,
  GR01 0/34·IC대사 0/34·reciprocal 22 컨닝·R06 18 우연). 권고: 진짜 3-hop+ 순환 재생성 →
  **relational(=graph/entity anomaly family) 재배정** (GR01 Johnson 순환 로직을 relational 에
  편입 또는 신규 순환 룰 추가; graph 는 독립 PHASE2 family 가 아니라 PHASE1 corroboration
  detector 임 — phase2_reorgani.md:147 active family 5개에 graph 없음, relational 이 graph/
  entity anomaly 담당), IC primary 는 대사 불일치 truth 신규.

---

## 5. 주의 (이 프로젝트 규칙)

- truth/scenario 라벨을 detector 입력으로 쓰지 않는다(평가 전용). 측정은 detector 출력과
  라벨을 사후 join.
- recall 만 보지 말 것. precision / FP / lift / 구조 유효성을 함께 본다(IC 100% 가 컨닝이었던
  교훈).
- 한국어 적요 컬럼 round-trip 금지(인코딩 가드). 읽기 전용 측정만.
- detector 코드·데이터는 변경하지 않는다. 검사는 in-memory 측정.
- 결과는 `docs/spec/PHASE2_FITTING_AUDIT.md` 와 `docs/debugging.md` 에 기록.
