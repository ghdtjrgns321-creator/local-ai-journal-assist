# 00. 데이터셋 수집·선정·활용 전략 [Phase 0 — 사전 준비]

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> **🔄 Phase 3 v2 Rescope (2026-05-14) ✅ 구현 완료 (Sprint A~G, 2026-05-15)**: Phase 3 단일 목표는 [Review Queue Narrator](../PHASE3_REVIEW_NARRATOR_SPEC.md), 완료 리포트 [completed/phase3_review_narrator_completion.md](../completed/phase3_review_narrator_completion.md). 본 문서 내 Text-to-SQL / Vanna / Ollama / Export / Chat / fpdf2 / ChromaDB / 감사조서 언급은 historical v1 기록 (구현 보존, 신규 작업 없음). [DECISION.md §D041](../DECISION.md) / [PHASE3_REWORK_PLAN.md](../PHASE3_REWORK_PLAN.md) 참조.

## 목적

감사 이상치 탐지 시스템의 입력 데이터를 확보하고 Phase별 활용 전략을 수립한다.

## 결론: DataSynth 메인 + 수집 데이터 검증용

32개 공개 데이터셋/도구를 검토한 결과, **EY-ASU DataSynth**를 메인 데이터 소스로 채택했다.
기존 수집 데이터셋 5종은 검증용으로 보관한다.

> 상세 검토 기록: [data/journal/OVERVIEW.md](../../data/journal/OVERVIEW.md)

## 디렉토리 구조

```
data/journal/
├── OVERVIEW.md                      # 전체 개요 + 32개 검토 기록
├── primary/
│   └── datasynth/                   # 메인: EY-ASU 합성 전표 (1,105K건, 319MB)
│       ├── journal_entries.csv
│       ├── chart_of_accounts.json   # 431개 계정과목 정의 (414개 사용)
│       ├── master_data/             # 벤더·고객·사원
│       ├── document_flows/          # P2P/O2C 문서 흐름
│       ├── labels/                  # fraud 레이블 상세
│       ├── generation_principles.md # 생성 원칙·비즈니스 프로세스·페르소나
│       └── PREVIEW.md              # 컬럼 사전 + head(5)
└── validation/
    ├── sap-merged/                  # 실제 SAP 전표 구조 비교 (332K)
    ├── schreyer-fraud/              # ML 학술 벤치마크 (533K)
    ├── bpi2019/                     # 사용자 행동 패턴 (1,596K)
    ├── financial-anomaly/           # Benford 테스트 (217K)
    └── general-ledger/              # Benford 검증 (28K)
```

## DataSynth 선택 근거

| 요건                | DataSynth                              | 기존 최선 (sap-merged)    |
|---------------------|----------------------------------------|---------------------------|
| 차변/대변           | O (debit_amount/credit_amount)         | O (drcrk, shkzg)          |
| 금액                | O (debit/credit/local_amount)          | O (hsl, dmbtr, wrbtr)     |
| GL 계정             | O (gl_account, 414개 사용/431개 정의)  | O (racct, hkont)          |
| 날짜                | O (posting_date, document_date)        | O (budat, cpudt)          |
| 입력자              | O (created_by, 1,365명 사용)            | O (usnam)                 |
| **이상치 레이블**   | **O (fraud 1.96% + anomaly 2.60% + labels.csv 8,337건)** | 1%만 (IF/LOF) |
| **fraud 시나리오**  | **46개 anomaly 유형 + 15개 fraud 유형 (2026-04-14 실측)** | 없음             |
| 복식부기 보장       | O (생성 시 강제)                       | 원본 의존                 |
| Benford 분포        | O (생성 시 준수)                       | 원본 의존                 |
| 규모 조절           | 1만~1억건 파라미터                     | 고정 332K                 |
| 재현성              | seed 2024                              | 불가                      |

## 메인 데이터: DataSynth 출력

### 생성 설정

```yaml
# config/datasynth.yaml
global:
  seed: 2024
  industry: manufacturing
  start_date: "2022-01-01"
  period_months: 12
  group_currency: KRW

companies:
  - code: "C001"  # KR 본사(서울), 100K/yr
  - code: "C002"  # KR 울산공장, 10K/yr
  - code: "C003"  # KR 천안공장, 10K/yr

fraud:
  enabled: true
  fraud_rate: 0.02
```

### 생성 결과

| 항목         | 값 (2026-04-14 실측)                                                  |
|--------------|-----------------------------------------------------------------------|
| 라인아이템   | 1,107,720                                                             |
| 전표 건수    | 319,204 (3년)                                                         |
| 컬럼수       | 44                                                                    |
| 크기         | 389MB (통합 CSV)                                                      |
| fraud 비율   | 1.96% (6,262건)                                                       |
| anomaly 비율 | 2.60% (8,294건) + anomaly_labels.csv 8,337건 별도                      |
| SoD 위반     | 3.32% (10,595건)                                                      |
| 프로세스     | R2R(38.9%), O2C(19.9%), P2P(19.6%), H2R(7.7%), TRE(7.1%), A2R(6.8%) |
| 입력자       | 1,365명 사용 / 1,422명 마스터 (5개 페르소나)                          |
| GL 계정      | 414개 사용 / 431개 정의                                                |

### 핵심 컬럼 (39개)

> 상세 컬럼 사전: [data/journal/primary/datasynth/PREVIEW.md](../../data/journal/primary/datasynth/PREVIEW.md)
> 생성 원칙: [data/journal/primary/datasynth/generation_principles.md](../../data/journal/primary/datasynth/generation_principles.md)

**Header — 전표 단위 (23개)**:
document_id, company_code, fiscal_year, fiscal_period, posting_date, document_date,
document_type, currency, exchange_rate, reference, header_text, created_by,
user_persona, source, business_process, ledger, is_fraud, fraud_type, is_anomaly,
anomaly_type, approved_by, approval_date, sod_violation, sod_conflict_type

**Line — 라인아이템 단위 (15개)**:
line_number, gl_account, debit_amount, credit_amount, local_amount,
cost_center, profit_center, line_text, tax_code, tax_amount,
trading_partner, auxiliary_account_number, auxiliary_account_label,
lettrage, lettrage_date

## 검증용 데이터 (5종)

| 폴더              |   행수 | 검증 대상                                |
|-------------------|-------:|------------------------------------------|
| sap-merged        |   332K | DataSynth가 실제 SAP 구조와 일치하는지   |
| schreyer-fraud    |   533K | ML 모델 성능을 학술 벤치마크와 비교      |
| bpi2019           | 1,596K | 사용자 행동 패턴 (L1-05~L3-02 룰 검증)       |
| financial-anomaly |   217K | Benford 분석 함수 단위 테스트            |
| general-ledger    |    28K | Benford + L2-01/L3-06 로직 검증              |

> 각 데이터셋 상세: [data/journal/OVERVIEW.md](../../data/journal/OVERVIEW.md)

## Phase별 활용 전략

```
Phase 1 (룰 탐지)   → DataSynth journal_entries.csv (메인)
                      → 24개 룰(L1-01~L3-09) L1/L2/L3/L4 탐지
                      → validation/ 데이터로 룰 로직 교차 검증
Phase 2 (ML)         → DataSynth is_fraud/is_anomaly로 지도학습
                      → +16개 유형 ML 확장 (총 36개)
                      → schreyer-fraud label로 학술 벤치마크 비교
Phase 3 (LLM/그래프) → DataSynth line_text/header_text로 NLP 테스트
                      → +5개 유형 NLP/그래프 확장 (총 41개)
Benford 검증         → financial-anomaly, general-ledger로 L4-02 로직 테스트
사용자 행동 분석     → bpi2019로 L1-05/L1-06/L3-02 룰 검증
```

## 스키마 확정 근거

- `config/schema.yaml`: DataSynth 39개 컬럼 기준 (ACDOCA 매핑 포함)
- `config/keywords.yaml`: DataSynth 컬럼명 + SAP 필드명 추가
- `config/risk_keywords.yaml`: DataSynth FraudType 참고 위험 키워드
- `docs/DETECTION_RULES.md`: DataSynth **52개** anomaly 유형 기준

## 선행/후행 의존

- **선행**: 없음 (최초 태스크)
- **후행**: 01-project-setup (스키마 확정) → 02-ingest (CSV 로드)