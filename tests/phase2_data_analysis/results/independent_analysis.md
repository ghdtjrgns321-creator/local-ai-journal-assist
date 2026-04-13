# Phase 2 독자 데이터 분석 리포트

> **분석 대상**: `data/journal/primary/datasynth/journal_entries.csv` (1,193,020 행)
> **분석 일시**: 2026-04-11
> **분석 축**: Phase 2 ML/시퀀스/드리프트 관점 8개 (quality_gate3와 별개)
> **분석자**: Claude Code (LLM 역할 — JSON 프로파일 정성·정량 해석)

---

## 🎯 종합 판정

| 항목 | 평가 | 근거 |
|------|------|------|
| Benford 적합성 | ⭐⭐⭐⭐⭐ | MAD = 0.00172 (Nigrini "매우 적합" 기준 0.015의 1/9) |
| 시퀀스 데이터 적합성 | ⭐⭐⭐⭐☆ | 전 사용자 seq_len=16 충족, 시:분:초 해상도 확보 |
| Stacking OOF 학습 적합성 | ⭐⭐☆☆☆ | **user-leakage 설계상 취약** (257명 중 256명 fraud 보유) |
| 드리프트 베이스라인 | ⭐⭐⭐⭐☆ | 연간 fraud_rate 안정 (±0.1%p), 월간 변동은 결산 효과로 정상 |
| 내부통제 신호 품질 | ⭐⭐⭐⭐☆ | manager/controller 중심 SOD 패턴 선명 |
| 데이터 구조 무결성 | ⭐⭐⭐⭐⭐ | 중복 0, line_number gap 0, 핵심 null < 2% |
| Fraud 시그니처 현실성 | ⭐⭐⭐☆☆ | 12월 집중 양호, 그러나 일부 금액 비현실적 |
| 실전 일반화 가능성 | ⭐⭐☆☆☆ | **합성 데이터 균질성 → 실전 1만+ 사용자 환경과 분포 차이** |

**한 줄 요약**: 합성 데이터 품질 자체는 상위권(Benford/구조/시간 해상도 완벽)이나, 사용자·라벨 분포가 너무 균질해 **학습된 모델이 실전 일반화에 취약**하다. 이는 TS-3에서 인지한 한계와 일치하며 Phase 2 ML의 설계 전제(비지도 중심 + 실전 fine-tuning)를 재확인한다.

---

## Axis 1: Temporal Granularity (BiLSTM 시퀀스 전제 조건)

### 정량 수치
- `midnight_rate = 0.000000` — posting_date가 00:00:00인 행 **0건**
- `second_is_zero_rate = 0.016393` — 초가 정확히 0인 행 1.64%
- `same_minute_multi_entries = 317,751` — 같은 사용자 × 같은 분 내 ≥2건 입력 케이스
- `after_hours_docs = 3,238` — 심야(22~05시) 전표 (전체의 약 0.27%)

### 시간 히스토그램 해석
```
09시: 142K  10시: 146K  16시: 120K  17시: 128K  15시: 101K
→ 업무시간 9~17시 집중 (총 ~72%), 정상적 K-중견기업 패턴
→ 점심 12시: 25K (-72% dip) — 점심 효과 명확
→ 심야 0~5시: 합계 ~6.5K (0.54%) — 대부분 SYSTEM 계정
```

### Top 심야 사용자
- `SYSTEM-C001-0001`: 535건 / `SYSTEM-C002-0001`: 272건 / `SYSTEM-C003-0001`: 263건
  → 3개 회사 주 시스템 배치 **1,070건** (심야 33%)
- `AGI015`: 64건 — **유일한 실사용자 심야 패턴** (ISA 240 §33 "비정상 시간 override" 의심)

### 정성 해석
BiLSTM 시퀀스 정렬 전제조건이 **완벽히 충족**. `posting_date`의 시:분:초 해상도가 실제로 사용되고 있으며, same_minute 케이스 31만건은 배치 처리(시스템 or 수기 일괄 입력)로 "같은 분 내 여러 건"이 흔하다는 것을 증명. 이는 묶음 1에서 추가한 `sequence_builder`의 tie-break 보강(`document_id`, `line_number`)이 **실제로 필요한 상황**이었음을 확인.

**AGI015 사용자 발견 의의**: 시스템이 아닌 실사용자가 심야 64건을 처리한 것은 룰 C03(심야 전기) + C12(비정상 시간 집중 입력)의 **타겟 케이스**. 이 사용자의 다른 지표(SOD, 금액, fraud 라벨)를 추가 조사 필요.

---

## Axis 2: User-Sequence Structure (BiLSTM seq_len 적합성)

### 정량 수치
- `total_unique_users = 257` — 전체 고유 사용자
- `docs_per_user_percentiles`:
  - min=112, P50=584, P99=5,152, max=9,802
- `users_with_seq_len_16_pct = 1.00` — **100% 사용자가 seq_len=16 충족**
- `singleton_users = 0` — 1건만 있는 사용자 없음

### 정성 해석
**모든 사용자가 시퀀스 모델의 전제(최소 윈도우 길이)를 충족**하므로 `SequenceDetector`의 zero-padding 경로가 거의 쓰이지 않는다. 이는 BiLSTM 학습에 이상적이나, **실전에서는 1회성 임시 사용자(외부 컨설턴트, 인턴)가 존재**하므로 padding 경로도 검증이 필요함.

### 페르소나별 평균 전표
| Persona | 평균 전표 수 | 해석 |
|---------|------------|------|
| automated_system | 3,202.8 | 가장 많음 — 시스템 배치가 주력 |
| controller | 2,201.7 | 2순위 — 상위 승인자 역할 많음 |
| senior_accountant | 1,157.2 | 중간 — 복잡 전표 담당 |
| junior_accountant | 397.1 | 낮음 — 작업 범위 제한 |
| manager | 302.2 | **가장 적음** — 승인 집중, 작성 비중 적음 |

**중요 발견**: 사용자 수 257명은 **매우 적음**. 일반 대기업이 1만+ 사용자를 갖는 것과 비교하면 100배 이상 차이. BiLSTM은 "사용자별 패턴 학습"이 핵심인데, 257명만으로 학습한 모델이 **실전 1만+ 사용자 환경으로 일반화될지는 검증 불가**. 이는 DataSynth의 구조적 한계이며, Phase 3 실데이터 fine-tuning이 반드시 필요함을 재확인.

---

## Axis 3: Label Quality for Stacking (GroupKFold 전제)

### 정량 수치 (핵심)
- `fraud_or_anomaly_doc_count = 33,375` / `rate = 10.46%` → 충분한 양성
- `user_positive_rate_bins = {"2_med_<=25%": 257}` — **257명 전원이 5~25% fraud 보유**
- `fraud_contamination_per_user = 256` / 257 → **99.6%의 사용자가 fraud 이력 보유**

### 🚨 Critical 발견
**합성 데이터의 라벨이 너무 균질하게 뿌려져 있다**. 실전 감사 데이터의 현실은:
- 횡령범 1~5명이 양성 80~100% 차지
- 나머지 99%+ 사용자는 양성 0건

반면 DataSynth v21은:
- 전원이 5~25% 양성 보유
- 99.6% 사용자가 최소 1건 이상 fraud

### Phase 2 OOF Stacking에 미치는 영향
- `train_oof(GroupKFold(n_splits=3, groups=user_ids))` 실행 시
- 어느 fold로 나눠도 train/val 양쪽에 fraud 사용자 대거 존재 → **User-leakage 방어 효과가 약함**
- 즉 묶음 1에서 설계한 GroupKFold의 이점이 이 데이터셋에서는 실증 불가
- 모델이 "사용자 ID memorization" 과적합을 하지 않는지 검증은 **실전 데이터가 있어야 가능**

### 권장 후속 조치
1. **단기**: 기존 OOF 구조를 유지하되, ablation으로 "User-shuffled labels" vs "정상" F1 비교 → 라벨 구조 이슈 정량화
2. **장기**: DataSynth 개선 — fraud_rate를 사용자 집중형으로 재생성 (예: 5% 사용자가 90% fraud)
3. **Phase 3**: 실데이터 유입 시 User-leakage 방어가 실제로 작동하는지 재검증

---

## Axis 4: Amount Distribution Geometry (Benford + ML 피처)

### Benford 제1자리 법칙
| 자리 | 실제 비율 | 기대 비율 | 편차 |
|------|---------|---------|------|
| 1 | 30.16% | 30.10% | +0.06%p |
| 2 | 17.21% | 17.61% | -0.40%p |
| 3 | 12.27% | 12.49% | -0.22%p |
| 4 | 9.36% | 9.69% | -0.33%p |
| 5 | 7.64% | 7.92% | -0.28%p |
| 6 | 6.45% | 6.69% | -0.24%p |
| 7 | 5.54% | 5.80% | -0.26%p |
| 8 | 4.89% | 5.12% | -0.23%p |
| 9 | 4.32% | 4.58% | -0.26%p |
| **MAD** | **0.00172** | | **매우 적합** (Nigrini 기준 < 0.015) |

### 로그 금액 분포
- 10^5 (10만원대): 32.7% — 최빈
- 10^6 (100만원대): 22.8%
- 10^4 (1만원대): 19.2%
- 10^7 이상: 12.6% → 꼬리 분포 확보
- 10^8+ (1억+): 2.6% — 고액 전표 충분

### Round number bias
- `round_number_rate = 15.71%` — 1만 단위 반올림 금액
- 한국 ERP 실무에서 결재 한도(예: 100만원, 500만원)를 "딱 맞추는" 전표가 실제로 많음 → 현실적 수치

### 양성 vs 음성 금액 분리
- positive median = 472,008 / negative median = 294,180 → **양성이 1.6배 큰 금액**
- ML 분리가능성(separability) 확보 — XGBoost/VAE의 `amount_zscore` 피처가 의미 있는 신호 제공 가능

### 정성 해석
**Benford 적합성 최상위**. Phase 1 룰 C07(Benford 위반) recall이 낮게 나오는 것이 정상이며, 이는 "데이터 자체가 Benford를 준수한다 = 대량 조작이 없다"는 의미. VAE는 Benford 외 다차원 이상을 학습하므로 영향 없음.

---

## Axis 5: Drift Baseline Fit (PSI 안정성)

### 월별 평균 금액 (원)
```
1월: 49.4M (최대)    7월: 18.5M
2월: 17.6M (최소)    8월: 20.7M
3월: 26.8M           9월: 32.3M
4월: 40.2M           10월: 32.7M
5월: 16.3M           11월: 44.3M
6월: 29.6M           12월: 46.7M
```

### 월별 표준편차 CoV
- 1월 std = **4.95B** (mean 49.4M 대비 100배) → 극단치 영향 대규모
- 11월 std = 4.79B → 동일 패턴
- 5월 std = 292M → 안정적

### 정성 해석
1월/11월/12월이 **결산·법인세 정산·배당 시즌**으로 극단치가 대량 유입 — 합성 데이터가 한국 회계 연간 주기를 **정확히 모사**. 이는 C01(기말 대규모) 룰의 타겟 데이터가 현실적이라는 증거.

### 연간 fraud_rate
- 2022: 1.30% / 2023: 1.21% / 2024: 1.29% → **연간 변동 ±0.1%p 이내**
- PSI 계산 시 베이스라인으로 사용하면 `max_psi < 0.01` (stable) 예상
- 즉 `drift_banner`는 이 데이터셋에서 항상 ✅ 녹색 표시

### 회사별 document_type 일관성
- C001/C002/C003 모두 `SA > DR > KR > ...` 순서 동일
- **스키마 수준 드리프트 0** → `feature_schema_version` 해시 변경 불필요

### Phase 2 드리프트 감지 관점
- 현재 데이터셋은 PSI 감지를 **시험할 대상이 없음** (너무 안정)
- **권장 후속 테스트**: 고의로 1개월(예: 12월)을 2배 증폭해 "유도 드리프트" 시나리오를 생성하고 `compute_drift_report` critical 전환 실험

---

## Axis 6: SOD × Persona Matrix (내부통제 탐지 신호)

### 핵심 수치
- `sod_violation_count = 6,463` (전체 전표의 2.03%)
- `self_approval_with_sod = 2,473` → SOD 위반의 **38%가 자기승인**
- `top3_approver_share = 11.15%` → 승인 집중도 낮음 (현실적 분산 체계)

### Persona × SOD Type 교차표 (상위)
| Persona | 주요 SOD 패턴 | 건수 |
|---------|--------------|------|
| controller | preparer_approver | **1,307** |
| manager | preparer_approver | 1,252 |
| manager | system_access_conflict | 772 |
| automated_system | preparer_approver | 972 |
| automated_system | requester_approver | 395 |
| senior_accountant | preparer_approver | 227 |
| junior_accountant | preparer_approver | 224 |

### 정성 해석
- **controller + manager**가 SOD 위반의 주력: `preparer_approver`(자기 작성 + 자기 승인) 패턴
  → ISA 240 §33 "경영진 override" 시나리오의 직접 시뮬레이션
- `manager`의 `system_access_conflict` 772건은 권한 오남용(시스템 접근 직무 충돌) — 대시보드 드리프트 배너에서 별도 알림 가치 있음
- `junior_accountant`는 224건만 preparer_approver → 직급 제약이 작동하는 현실적 모델링
- **top3_approver_share = 11.15%**는 "승인자 편중이 없다"는 의미. 일반적으로 중견기업에서는 Top 3 승인자가 30~50%를 처리하는 경향이 있어, 이 데이터셋은 **승인 체계가 지나치게 평평**함 — 실전과의 차이점

### 탐지 룰 영향
- `B06`(자기 승인): 2,473건 타겟 확보
- `B07`(직무분리 위반): 4,000건+ 타겟 확보
- `controller`와 `manager` persona에 집중 학습 기회 존재

---

## Axis 7: Data Quality Fingerprint

### 핵심 결측률
| 컬럼 | null_rate | 해석 |
|------|-----------|------|
| document_id | 0.00% | ✅ 완전 |
| posting_date | 0.00% | ✅ 완전 |
| fiscal_year | 0.00% | ✅ 완전 |
| created_by | 0.00% | ✅ 완전 |
| business_process | 0.00% | ✅ 완전 |
| user_persona | 0.00% | ✅ 완전 |
| source | 0.00% | ✅ 완전 |
| debit_amount / credit_amount | 0.00% | ✅ 완전 |
| gl_account | 2.03% | ⚠️ 극소수 결측 (종속 전표) |
| document_type | 2.03% | ⚠️ 동일 원인 |
| approved_by | **71.49%** | ℹ️ 설계 의도 (자동 전표 + 미승인 = null) |

### 구조 무결성
- `full_duplicate_rows = 0` — 완전 중복 0건
- `docs_with_gap_in_line_number = 0` — 전표 내 line 번호 연속성 100%
- GL 자릿수: 4자리(16.3%) + 6자리(81.6%) — **한국 중견기업 혼합 체계 (K-IFRS 간이 + 상세 병행)**

### 정성 해석
데이터 구조 품질은 **상위 5%** 수준. `approved_by` 71% null은 "자동 전표 + 승인 미이행 전표"로 설명되며 한국 ERP 실무와 일치. `gl_account` 2% null은 정리 전표의 미완성 단계(월말 반제 전 상태)로 의도된 것.

**드리프트 감지 관점**: 이 구조를 베이스라인으로 저장하면, 실전 환경에서 `gl_account` null_rate가 5%+로 급증하거나 자릿수 분포에 새 bin(예: 8자리 SAP)이 등장할 때 즉시 감지 가능.

---

## Axis 8: Fraud Signature Profile (탐지 룰 vs 라벨 정합성)

### 월별 fraud 집중도 (12월 1순위 여부)
**모든 fraud_type이 12월 1순위** — 예외 없음.

| fraud_type | 12월 건수 | 12월 비율 | 순위 |
|-----------|----------|---------|------|
| DuplicatePayment | 156 | 21.2% | 1위 |
| FictitiousTransaction | 142 | 17.2% | 1위 |
| SplitTransaction | 102 | 15.8% | 1위 |
| RevenueManipulation | 95 | 17.9% | 1위 |
| UnauthorizedAccess | 79 | 19.4% | 1위 |
| TimingAnomaly | 75 | 21.9% | 1위 |
| SuspenseAccountAbuse | 37 | 18.5% | 1위 |
| ExpenseCapitalization | 36 | 19.4% | 1위 |
| ExceededApprovalLimit | 26 | 32.9% | 1위 |

**해석**: C01(기말 대규모) 룰의 완벽한 타겟 — 기말 시점 효과가 **과도하게 강조**된 합성. 실전에서는 이렇게 일관된 12월 집중이 드뭐 Phase 1 룰 C01의 recall이 과도하게 높게 나올 위험. ML 모델이 이 편향을 학습하면 실전 일반화 실패 가능성.

### fraud_type별 중앙값 금액
| fraud_type | median (원) | 현실성 |
|-----------|------------|--------|
| ExceededApprovalLimit | **2,861,055,505** (28.6억) | ❌ 비현실적 — 중견기업 일회성 승인한도 초과가 28억 |
| JustBelowThreshold | 999,499,985 (10억) | ❌ 동일 — 승인한도 직하 패턴이 10억대 |
| SelfApproval | 13,441,878 (1,340만) | ✅ 합리적 |
| FictitiousVendor | 2,838,881 | ✅ |
| FictitiousTransaction | 656,000 | ✅ |
| DuplicatePayment | 70,999 | ✅ 소액 중복 |
| RoundDollarManipulation | **227** | ❌ 극소액 (의미 없음) |

### 심야 집중도
- fraud_by_hour 대부분이 **9~18시 업무시간 집중**
- C03(심야 전기) 룰 타겟은 실제로 극소수 — `DuplicatePayment` 22시 1건, `TimingAnomaly` 0시 1건 등
- **C03 룰은 이 데이터셋에서 recall이 0에 수렴할 것**

### 승인 경로 × fraud 상관
- `skipped_approval_fraud_rate = 0.36%` (전체 fraud_rate 1.05%보다 **낮음**)
- `self_approval_fraud_rate = 2.75%` (baseline의 2.6배) → 유의미한 시그널

### 정성 해석
- **강점**: 12월 집중 + self_approval 시그널 명확 → 룰 기반 탐지가 쉬움
- **약점**:
  1. 일부 fraud_type의 금액이 비현실적 (28억 승인한도 초과, 227원 round dollar)
  2. 심야 집중이 없음 → 시퀀스 기반 "30분 내 3건 연속" 같은 ISA 240 패턴 탐지 실증 불가
  3. 모든 fraud가 12월 집중 → 실전에서 월별 변동이 더 완만하면 모델이 "12월 = fraud" 과적합 위험

---

## 📌 Phase 2 ML 관점 액션 아이템

### 즉시 조치 (이 데이터셋 기반)
1. **BiLSTM 시퀀스 검증** ✅ 가능 — `posting_date` 시:분:초 해상도 확인됨. `_build_timestamps()` 정상 작동 실증 가능
2. **GroupKFold OOF 구조적 검증** ✅ 가능 — fold 분리 로직 자체는 검증 가능
3. **드리프트 감지 안정 케이스 검증** ✅ 가능 — PSI < 0.01 baseline 확보

### 제한 조건 (데이터 한계로 검증 불가)
1. **User-leakage 실증**: 257명 전원이 fraud 보유 → GroupKFold 이점 측정 불가. **실데이터 대기**
2. **심야/시퀀스 패턴 탐지**: after_hours 0.27%는 너무 적음 → C03 + BiLSTM 시퀀스 모델의 실효성 검증 불가
3. **드리프트 감지 alarm 시나리오**: 데이터가 너무 안정 → 유도 드리프트 실험 필요

### 권장 후속 작업
1. **Fraud_user_concentration 재설계**: DataSynth config에 "횡령범 상위 1% = 양성 80%" 파라미터 추가
2. **심야 사용자 시나리오 추가**: `AGI015`처럼 24시간 활성 사용자 1~3명을 의도적 삽입
3. **드리프트 시나리오 테스트**: 기존 데이터의 12월만 2배 증폭한 "유도 드리프트" 데이터셋 생성 → `compute_drift_report` critical 전환 실측
4. **ExceededApprovalLimit 금액 캘리브레이션**: 중앙값 28억 → 3천만~3억 범위로 조정 (한국 중견기업 실무 기준)

---

## 🔎 재생성 판단 결과

**재생성 불필요 — 기존 데이터가 이미 필요한 품질을 갖추고 있음**

- `posting_date`는 이미 `2022-01-01 18:21:13` datetime 포맷 (production `output_writer.rs:211`가 `created_at.time()` 합성)
- 내가 수정한 `csv_sink.rs`는 테스트/streaming 경로일 뿐 production CSV 출력과 무관
- 1.19M 행, 257 사용자, 33,375 fraud 전표로 Phase 2 ML 학습에 충분
- **실질적 개선 여지는 "데이터 재생성"이 아닌 "데이터 재설계"**: DataSynth config의 라벨 분포 수정이 진짜 필요한 조치

---

## 📂 산출물 경로

| 파일 | 용도 |
|------|------|
| `tests/phase2_data_analysis/extract_independent.py` | 8축 프로파일 추출 스크립트 (재실행 가능) |
| `tests/phase2_data_analysis/results/independent_profile.json` | 전수 데이터 원시 프로파일 |
| `tests/phase2_data_analysis/results/independent_analysis.md` | 본 리포트 (정성·정량 해석) |

**실행 커맨드**:
```bash
uv run python -m tests.phase2_data_analysis.extract_independent
```

**로딩 시간**: 1.19M 행 × 8축 집계 = **3.3초** (DuckDB 전수 스캔)
