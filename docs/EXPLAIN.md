# Local AI Audit Assistant — 시스템 동작 설명

> 목적: Phase 1~2 구현 상태에서 전체 시스템이 어떻게 돌아가는지, LLM/ML/규칙의 역할 분담, 라벨 전략, 앙상블 가중치, HITL 피드백 현황을 정리한 설명 문서.
> 작성 기준일: 2026-04-10

---

## 1. LLM과 ML/DL의 역할 분담

세 가지가 완전히 **별개 역할**이다. "Local LLM으로 머신러닝을 한다"는 구조가 아니다.

| 구분 | 역할 | 기술 스택 | 현재 상태 |
|------|------|----------|----------|
| **규칙 기반 (Phase 1)** | 24개 감사 룰로 알려진 부정 패턴 탐지 | Python + 통계 | 완료 |
| **ML/DL (Phase 2)** | 미지 패턴 탐지 (VAE, XGBoost 등) | PyTorch + scikit-learn | 기본 구현 |
| **LLM (Phase 3)** | 적요 의미 분석, Text-to-SQL | 상용 API (Gemini/Claude) — 하이브리드 | 거의 미착수 |

### LLM이 현재 실제로 하는 일

1. **컬럼 매핑 보조** (`src/ingest/llm_mapper.py`)
   - fuzzy match 실패 시 표준 컬럼명 추천
2. **전처리 전략 조언** (`src/llm/preprocessing_advisor.py`)
   - EDA 프로파일 → "이 컬럼은 robust scaler" 같은 추천 (Structured Output)

둘 다 LLM 서버 미실행 시 **규칙 기반 폴백**으로 자동 전환된다. 즉 LLM 없어도 시스템은 동작한다.

### LLM이 현재 하지 않는 것

- 부정 탐지 직접 수행 (Phase 3 예정)
- 적요 NLP 의미 분석 (Phase 3 예정)
- 순환거래 그래프 분석 (Phase 3 예정)

---

## 2. 전체 파이프라인 흐름 (6단계)

```
Excel/CSV 업로드
    │
    ▼
┌─────────────────────────────────────┐
│ 1. INGEST (자동)                     │
│  • 헤더 위치 자동 탐지 (1~20행 스캔) │
│  • 컬럼명 자동 매핑 (3단계 매칭)     │
│  • 타입 캐스팅 (날짜, 금액, 계정코드)│
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 2. VALIDATION (자동)                 │
│  • L1: 필수 컬럼 존재? 타입 맞음?   │
│  • L2: 차변=대변? 중복 전표?        │
│  • L3: GL↔TB 교차검증               │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 3. FEATURE (자동, 18개 파생변수)     │
│  • 시간: 주말? 심야? 기말?          │
│  • 금액: Z-score, 둥근수, 임계값    │
│  • 패턴: 수기전표, 벤포드 첫자릿수  │
│  • 텍스트: 적요 품질, 위험 키워드   │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 4. DETECTION (자동, 다층 앙상블)     │
│                                      │
│  [Phase 1] 규칙 24개 — 항상 실행    │
│   ├ Layer A: 무결성 (차대변, 계정)  │
│   ├ Layer B: 부정 (자기승인, 중복)  │
│   ├ Layer C: 이상 (기말대규모, 심야)│
│   └ Benford: 첫째 자릿수 분포       │
│                                      │
│  [Phase 2] ML — 모델 있으면 실행    │
│   ├ VAE+IF: 비지도 (정상 패턴 학습) │
│   └ XGBoost: 지도 (라벨 있을 때)    │
│                                      │
│  [조건부] — 데이터 있으면 실행      │
│   ├ Layer D: 전기 대비 변동         │
│   ├ 문서흐름, 접근제어, 증빙 검증   │
│   └ 회계추정치 편의 (3개년)         │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 5. SCORE AGGREGATION                 │
│  • 각 레이어 점수 × 가중치 → 합산  │
│  • 위험 등급: High/Medium/Low/Normal│
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 6. DB 적재 + 대시보드 시각화         │
│  • DuckDB (회사/연도별 격리)         │
│  • Streamlit 4탭 (개요/탐색/위반/ML)│
└─────────────────────────────────────┘
```

### 진입점 파일

| 단계 | 파일 |
|------|------|
| 오케스트레이터 | `src/pipeline.py` |
| Ingest | `src/ingest/{reader_api, header_detector, column_mapper, type_caster}.py` |
| Validation | `src/validation/{schema, accounting, tb_reconciliation}_validator.py` |
| Feature | `src/feature/engine.py` (+ `{amount,time,pattern,text}_features.py`) |
| Detection | `src/detection/{integrity,fraud,anomaly,benford,duplicate}_*.py` |
| Score | `src/detection/score_aggregator.py` |
| DB | `src/db/loader.py` |

---

## 3. 전처리는 어떻게 동작하나

두 가지 의미의 "전처리"가 있다.

### 3.1 감사 탐지용 전처리 (항상 자동, LLM 개입 없음)

- **Ingest 단계**: 타입 캐스팅 (통화기호 제거, 날짜 파싱, 차/대변 분리)
- **Feature 단계**: 18개 파생변수 자동 생성
- 설정값은 `config/settings.py` + YAML로 관리, 임계값만 회사별로 다름

### 3.2 ML 학습용 전처리 (모델 학습 시에만, LLM 보조)

```
EDA 프로파일링 (profiler.py)
    ↓
LLM 전처리 조언 (preprocessing_advisor.py)
  - Structured Output으로 전략 추천
  - 실패 시 규칙 기반 폴백
    ↓
pipeline_builder.py → sklearn Pipeline 구성
  Imputer → Encoder → Scaler → Model
    ↓
cv_selector.py → 4개 모델 (LR/RF/XGB/LightGBM) 자동 비교
    ↓
best model 선택 → GridSearchCV로 하이퍼파라미터 튜닝
```

**중요**: ML 학습용 전처리는 일반 탐지 시엔 동작하지 않는다. VAE/XGBoost를 학습시킬 때만 실행된다.

---

## 4. Phase 2 ML/DL의 실제 역할

### 4.1 핵심 탐지기: VAE + Isolation Forest (비지도)

**VAE (Variational Autoencoder)** — `src/preprocessing/vae_model.py`

```
Input(42차원) → FC(32) → [mu, logvar](latent_dim=8)
                             ↓ reparameterize
                             z
                             ↓ FC(32)
                         Reconstruction(42차원)

손실 = MSE(원본, 재구성) + KL divergence
```

**동작 원리**:
1. 정상 전표 데이터로 "정상 분포" 학습
2. 새 전표 입력 → 재구성 시도 → 오차 측정
3. 오차 큼 = 정상 패턴에서 벗어남 = 이상 플래그

**규칙 기반과의 차이**: 규칙은 "주말 전표" 같은 **알려진 패턴**만 잡지만, VAE는 **뭔지 모르지만 이상한 것**도 잡는다 (zero-day).

**ECDF 정규화**: 학습 데이터 오차 분포를 저장해두고, 추론 시 `searchsorted`로 percentile 계산. 배치 크기 무관하게 "학습 데이터 기준 상위 N%"를 일정하게 유지.

### 4.2 지도학습 탐지기 (인프라 대기 상태)

`src/detection/supervised_detector.py` — XGBoost/RF/LR/LightGBM 4개 모델을 `cv_selector`가 자동 비교해 최적 선택. **현재는 파이프라인만 준비**되어 있고, 합성 데이터로 돌리면 순환 학습 문제가 생긴다 (아래 §5 참조).

### 4.3 고급 모델 (부분 구현)

| 모델 | 파일 | 상태 |
|------|------|------|
| FT-Transformer | `src/detection/tabular_transformer.py` | 구현, 미통합 |
| BiLSTM+Attention | `src/detection/sequence_detector.py` | 구현, 미통합 |
| Stacking Meta-Learner | `src/preprocessing/stacking.py` | 부분 구현 |

---

## 5. 라벨 없는 감사 현실 vs 지도학습의 모순

### 5.1 문제 제기

실무 감사 데이터에는 라벨이 없다. 그럼 `supervised_detector.py`는 뭐하는 물건인가?

### 5.2 Pseudo-Labeling이라는 순진한 해법

```
X1년: VAE + 룰이 이상 건 탐지 → 그걸 라벨로 간주
  ↓
X1년 라벨 + 피처로 XGBoost 학습
  ↓
X2년: XGBoost로 탐지
```

`src/preprocessing/label_strategy.py:72` 의 `_from_pseudo()` 함수로 실제 구현되어 있다.

### 5.3 순환 학습 함정 (왜 위 방식을 권장하지 않는가)

```
1. 룰이 "주말 전표"를 이상으로 잡음
2. 그 라벨로 XGBoost 학습
3. XGBoost는 "주말 전표"를 학습함
4. 결과: 룰이 이미 잡은 거 또 잡음
    → ML을 쓰는 의미가 없음
```

**VAE 출력을 라벨로 써도 마찬가지**:
- X1년 VAE가 "정상 분포에서 벗어난 것" = A 패턴
- 그걸 라벨로 XGBoost 학습
- X2년 XGBoost가 A 패턴 탐지 → VAE가 이미 잡는 걸 복제할 뿐

ML의 가치는 "룰이 못 잡는 걸 잡는 것"인데, 룰/VAE 출력을 라벨로 쓰면 **복제품만 양산**된다. 이건 `docs/pre-plan/05a-detection-ml.md:8-14` 에 명시된 TS-3 결정사항이다.

### 5.4 프로젝트의 실제 전략: HITL (Human-in-the-Loop)

```
┌────────────────────────────────────────────────────────┐
│ 현재 (합성 데이터 단계)                                 │
│  ├─ 룰 기반 24개        ← 실전 탐지기                  │
│  ├─ VAE + IF           ← 실전 탐지기 (핵심)            │
│  └─ XGBoost 등 지도학습 ← "파이프라인 인프라만" 준비  │
│                           성능 검증용 (F1/AUROC 측정)  │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│ 고객사 1회차 감사 투입                                  │
│  ├─ 룰 + VAE가 의심 건 1,000개 플래그                  │
│  ├─ 감사인이 직접 리뷰 → "진짜 부정 80건" 확정         │
│  └─ 이 80건이 "진짜 라벨" (사람의 판단)                │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│ 고객사 2회차 감사부터                                   │
│  └─ XGBoost/FT-Transformer 활성화                      │
│     → 감사인의 판단 패턴을 학습                        │
│     → 그 회사 맞춤 모델로 진화                         │
└────────────────────────────────────────────────────────┘
```

**왜 감사인 라벨이 가치 있는가**:
- "주말 전표지만 합법 결산작업이니 OK"
- "이건 금액 작지만 거래처 자체가 수상해"

이런 **룰로 인코딩 안 되는 맥락 지식**을 담고 있기 때문. ML이 진짜 학습 가치를 얻는다.

### 5.5 자동 모드 전환 로직

`src/preprocessing/label_strategy.py`:

```python
if positive_count >= 50 and positive_rate >= 0.01:
    return "supervised"   # 라벨 충분 → cv_selector로 모델 자동 선택
else:
    return "unsupervised" # 라벨 없음 → VAE + IF만
```

| 시나리오 | 라벨 소스 | 동작 모드 |
|----------|----------|----------|
| 합성 데이터 (개발) | DataSynth `is_fraud` GT | supervised (성능 검증용) |
| 실전 1회차 | 없음 | unsupervised (VAE+룰만) |
| 실전 2회차~ | 감사인 확정 라벨 50건+ | supervised (자동 활성화) |

### 5.6 3가지 라벨 전략 요약

`label_strategy.py`의 `create_labels()`:

| 전략 | 라벨 출처 | 언제 사용 |
|------|----------|----------|
| `datasynth` | 합성데이터 GT | 개발/검증 |
| `pseudo` | 룰+VAE 점수 (순환 위험) | 비상시 폴백 |
| `hybrid` | datasynth → pseudo → 비지도 | 기본값 |

---

## 6. 앙상블 가중치는 어떻게 결정하나

### 6.1 현재: 고정 가중치 전략 패턴

`src/detection/constants.py:147~206` 에 6가지 가중치 세트가 하드코딩되어 있고, **데이터 상태에 따라 자동 선택**된다.

```python
# 기본 (신규 회사, ML 없음)
LAYER_WEIGHTS = {
    LAYER_A: 0.15,  # 무결성
    LAYER_B: 0.45,  # 부정 ← 최고 비중
    LAYER_C: 0.25,  # 이상
    BENFORD: 0.15,
}

# ML 모델 있을 때
LAYER_WEIGHTS_WITH_ML = {
    LAYER_A: 0.10,
    LAYER_B: 0.30,
    LAYER_C: 0.18,
    BENFORD: 0.10,
    ML_SUPERVISED: 0.15,
    ML_UNSUPERVISED: 0.17,  # 비지도 > 지도 (순환학습 회피)
}

# 기존 회사 (전기 비교 가능)
LAYER_WEIGHTS_WITH_PRIOR = { ..., LAYER_D: 0.18 }

# TrendBreak 추가
LAYER_WEIGHTS_WITH_TRENDBREAK = { ..., TRENDBREAK: 0.15 }

# Layer D + TrendBreak 공존
LAYER_WEIGHTS_WITH_PRIOR_AND_TRENDBREAK = { ..., LAYER_D: 0.15, TRENDBREAK: 0.15 }
```

### 6.2 자동 선택 로직

`src/detection/score_aggregator.py _select_weights()`:

```
ML 모델 존재? → LAYER_WEIGHTS_WITH_ML
├─ Layer D + TrendBreak? → WITH_PRIOR_AND_TRENDBREAK
├─ TrendBreak만?         → WITH_TRENDBREAK
├─ Layer D만?            → WITH_PRIOR
└─ 기본                  → LAYER_WEIGHTS
```

### 6.3 가중치 설계 근거

- **Layer B(부정)가 항상 최대 비중**: 감사의 궁극 목표
- **비지도(0.17) > 지도(0.15)**: 합성 데이터에서 지도학습은 순환 학습 문제 → 비지도에 더 신뢰
- **Layer A(무결성)는 낮음**: 이미 validation에서 1차 필터링됨, 탐지 단계에선 보조

### 6.4 미래: Stacking Meta-Learner (WU-03)

`src/preprocessing/stacking.py` + `src/detection/ensemble_detector.py`:

```
[8개 base model 점수 행렬] (N, 8)
        ↓
Ridge(positive=True) meta-learner 학습
  - 5-fold Out-of-Fold prediction (leakage 방지)
  - positive=True: 음수 계수 금지 (단조성 보장)
        ↓
데이터 기반 최적 가중치 자동 학습
```

**`positive=True`의 이유**: "ML이 이상이라고 확신할수록 최종 점수가 오히려 낮아지는" 역설 방지. 모든 base model 점수가 높으면 최종도 높아야 감사 도메인에서 납득 가능.

**Fallback**: `positive_count < 50` → stacking 학습 불가 → 기존 고정 가중치로 자동 폴백.

### 6.5 결정 흐름 요약

```
라벨 충분 (≥50건) → Stacking meta-learner (데이터 기반 자동)
라벨 부족 (<50건) → 고정 가중치 (도메인 지식 기반 수동)
데이터 특성별 분기 → _select_weights()가 6개 세트 중 자동 선택
```

---

## 7. 감사인 피드백 UI (HITL) 현황

### 7.1 이미 구현된 것: Whitelist (오탐 제거)

`dashboard/components/explorer_whitelist.py` + `src/db/schema.py:162`:

```sql
CREATE TABLE whitelist (
    id INTEGER PRIMARY KEY,
    batch_id VARCHAR,
    document_id VARCHAR,
    rule_code VARCHAR,
    reason VARCHAR,
    created_by VARCHAR DEFAULT 'auditor',
    created_at TIMESTAMP
)
```

**워크플로우**: 감사인이 "이건 오탐이다" 판정 → whitelist 등록 → 다음 탐지부터 제외.

### 7.2 빠진 것: Confirmed-Label 수집 UI

현재 whitelist는 **"정상으로 확인됨" (negative 라벨)** 만 받는다. 지도학습 활성화에 필요한 것:

| 필요한 라벨 | 현재 UI | 비고 |
|------------|--------|-----|
| confirmed_normal (오탐) | whitelist (있음) | 이미 구현 |
| **confirmed_fraud (진짜 부정)** | **없음** | **추가 필요** |
| confirmed_error (단순 오류) | 없음 | 카테고리 세분화 |
| 감사인 메모/증거 | 없음 | 맥락 보존 |

### 7.3 향후 확장 방향

1. **라벨 테이블 추가**: `auditor_labels` (document_id, label_type, reason, evidence_path, auditor_id, created_at)
2. **대시보드 UI**: Findings 탭에서 각 의심 건마다 "부정 확정 / 오탐 / 단순오류 / 추가조사" 버튼
3. **자동 재학습 트리거**: `positive_count >= 50` 도달 시 `label_strategy`가 supervised 모드로 전환
4. **모델 레지스트리 연동**: 회사별 fine-tuned 모델 저장 (`~/.audit_models/{company_id}/`)

이게 완성되면 Phase 2 지도학습 인프라가 처음으로 **실제 가치**를 갖는다.

---

## 8. 핵심 요약

| 질문 | 답 |
|------|---|
| Local LLM이 ML/DL을 하나? | 아니다. LLM은 컬럼매핑+전처리 조언만, ML/DL은 별도 PyTorch/sklearn |
| 전처리는 자동인가? | 감사 탐지용은 완전 자동, ML 학습용은 LLM 보조 + 자동 파이프라인 |
| Phase 2에서 "AI"가 뭐 하나? | VAE가 정상 분포 학습 → 미지 패턴 탐지 (핵심), 지도학습은 인프라만 |
| 라벨 없는데 지도학습이 쓸모 있나? | 현재는 파이프라인 인프라, 실전에선 HITL 라벨 쌓여야 활성화 |
| VAE 출력을 라벨로 쓰면? | 순환 학습 → 복제품만 양산, 권장 안 함 |
| 실전 주력 탐지기는? | 룰 24개 + VAE + IF (라벨 없이 동작) |
| 앙상블 가중치는? | 현재 6개 고정 세트 자동 선택, 미래 Stacking으로 데이터 기반 학습 |
| 감사인 피드백 UI는? | Whitelist(오탐)만 있음, 부정 확정 라벨 UI는 추가 필요 |

---

## 9. 참조 문서

- `docs/PROJECT_OVERVIEW.md` — 프로젝트 개요, 디렉토리 구조
- `docs/TASKS.md` — Phase별 태스크 현황
- `docs/DETECTION_RULES.md` — 전체 탐지 룰 목록
- `docs/pre-plan/03a-preprocessing.md` — 전처리 전략
- `docs/pre-plan/05a-detection-ml.md` — ML 탐지 설계 (비지도중심 전략 근거)
