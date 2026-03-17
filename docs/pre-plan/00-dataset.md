# 00. 데이터셋 수집·선정·활용 전략

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
│   └── datasynth/                   # 메인: EY-ASU 합성 전표 (1,068K건, 232MB)
│       ├── journal_entries.csv
│       ├── chart_of_accounts.json   # 430개 계정과목
│       ├── master_data/             # 벤더·고객·사원
│       ├── document_flows/          # P2P/O2C 문서 흐름
│       ├── labels/                  # fraud 레이블 상세
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
| GL 계정             | O (gl_account, 430개)                  | O (racct, hkont)          |
| 날짜                | O (posting_date, document_date)        | O (budat, cpudt)          |
| 입력자              | O (created_by, 41명)                   | O (usnam)                 |
| **이상치 레이블**   | **O (fraud 1.3% + anomaly 2.5%)**     | 1%만 (IF/LOF)             |
| **fraud 시나리오**  | **8종 내장 (132종 확장 가능)**         | 없음                      |
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

companies:
  - code: "C001"  # US 본사, 100K/yr
  - code: "C002"  # EU 법인, 10K/yr

fraud:
  enabled: true
  fraud_rate: 0.02
```

### 생성 결과

| 항목         | 값                                                       |
|--------------|----------------------------------------------------------|
| 행수         | 1,068,119                                                |
| 컬럼수       | 29                                                       |
| 크기         | 232MB (CSV)                                              |
| fraud 비율   | 1.3%                                                     |
| anomaly 비율 | 2.5%                                                     |
| 프로세스     | P2P(26%), O2C(31%), R2R(24%), H2R(12%), A2R(6%)         |
| 입력자       | 41명 (SYSTEM + 사용자)                                   |
| GL 계정      | 386개 사용 / 430개 정의                                  |

### 핵심 컬럼 (29개)

> 상세 컬럼 사전: [data/journal/primary/datasynth/PREVIEW.md](../../data/journal/primary/datasynth/PREVIEW.md)

**필수 9개**: document_id, company_code, fiscal_year, posting_date, document_date, gl_account, debit_amount, credit_amount, document_type

**권장 10개**: created_by, source, business_process, line_number, local_amount, currency, cost_center, profit_center, line_text, header_text

**레이블 2개**: is_fraud, is_anomaly

## 검증용 데이터 (5종)

| 폴더              |   행수 | 검증 대상                                |
|-------------------|-------:|------------------------------------------|
| sap-merged        |   332K | DataSynth가 실제 SAP 구조와 일치하는지   |
| schreyer-fraud    |   533K | ML 모델 성능을 학술 벤치마크와 비교      |
| bpi2019           | 1,596K | 사용자 행동 패턴 (R005~R007 룰 검증)     |
| financial-anomaly |   217K | Benford 분석 함수 단위 테스트            |
| general-ledger    |    28K | Benford + R001/R003 로직 검증            |

> 각 데이터셋 상세: [data/journal/OVERVIEW.md](../../data/journal/OVERVIEW.md)

## Phase별 활용 전략

```
Phase 1 (룰 탐지)   → DataSynth journal_entries.csv (메인)
                      → validation/ 데이터로 룰 로직 교차 검증
Phase 2 (ML)         → DataSynth is_fraud/is_anomaly로 지도학습
                      → schreyer-fraud label로 학술 벤치마크 비교
Phase 3 (LLM)        → DataSynth line_text/header_text로 NLP 테스트
Benford 검증         → financial-anomaly, general-ledger로 로직 테스트
사용자 행동 분석     → bpi2019로 R005/R006/R007 룰 검증
```

## 스키마 확정 근거

- `config/schema.yaml`: DataSynth 29개 컬럼 기준 (ACDOCA 매핑 포함)
- `config/keywords.yaml`: DataSynth 컬럼명 + SAP 필드명 추가
- `config/risk_keywords.yaml`: DataSynth FraudType 참고 위험 키워드
- `docs/AUDIT_DOMAIN.md`: DataSynth anomaly.rs 132개 유형 기준

## 선행/후행 의존

- **선행**: 없음 (최초 태스크)
- **후행**: 01-project-setup (스키마 확정) → 02-ingest (CSV 로드)

## 다음 단계

1. ~~DataSynth 빌드~~ ✅
2. ~~메인 데이터 생성~~ ✅
3. 02-ingest 구현 시 DataSynth CSV 직접 로드 경로 반영
4. 05-detection 구현 시 is_fraud/is_anomaly 레이블을 벤치마크로 활용
