# 10. 가상 GL 데이터 생성기 및 Excel 템플릿

## 목적
전체 파이프라인을 테스트할 수 있는 가상 GL(General Ledger) 데이터를 자동 생성한다.
정상 전표(80%)와 의도적 이상 전표(20%)를 혼합하여 탐지 검증에 활용.

## 관련 파일
```
data/sample/
├── generate_sample.py    # 가상 GL 데이터 자동 생성기
└── gl_template.xlsx      # 수동 작성 Excel 템플릿 (50건)
```

## 핵심 클래스/함수

### `generate_sample.py` — 데이터 생성기
```python
def generate_gl_data(
    n: int = 10_000,
    anomaly_ratio: float = 0.20,
    seed: int = 42
) -> DataFrame:
    """가상 GL 전표 데이터 생성.

    Args:
        n: 생성할 전표 수 (기본 10,000건)
        anomaly_ratio: 이상 전표 비율 (기본 20%)
        seed: 랜덤 시드 (재현성 보장)

    Returns:
        표준 스키마에 맞는 DataFrame (schema.yaml 컬럼 구조)
    """

def _generate_normal_entries(n: int) -> DataFrame:
    """정상 전표 생성 (80%).
    - 평일 09~18시
    - 일반 금액 범위 (10만~5,000만)
    - 자동 전표 (source_type='자동')
    - 일반 계정과목 (매출, 매입, 급여 등)
    - 의미 있는 적요
    """

def _generate_anomaly_entries(n: int) -> DataFrame:
    """이상 전표 생성 (20%). 8개 룰 + Benford 위반 포함.
    각 이상 유형별 균등 배분."""

def _generate_r001_entries(n: int) -> DataFrame:
    """R001: 승인한도 직하 금액 (4,900~4,999만원대).
    감사 관점: 5,000만원 승인 한도 회피 의도."""

def _generate_r002_entries(n: int) -> DataFrame:
    """R002: 주말(토/일) 전표.
    감사 관점: 비업무일 처리는 통제 우회 가능성."""

def _generate_r003_entries(n: int) -> DataFrame:
    """R003: 심야(22시~06시) 전표.
    감사 관점: 야간 처리는 승인 절차 우회."""

def _generate_r004_entries(n: int) -> DataFrame:
    """R004: 기말(월말 5일 이내) 대규모 매출.
    감사 관점: 실적 조정 목적의 기말 매출 집중."""

def _generate_r005_entries(n: int) -> DataFrame:
    """R005: 역분개 쌍 (동일 계정·금액, 차변↔대변).
    감사 관점: 부정 거래 은폐 수단."""

def _generate_r006_entries(n: int) -> DataFrame:
    """R006: 수기 전표 (source_type='수동').
    감사 관점: 자동화 통제 우회."""

def _generate_r007_entries(n: int) -> DataFrame:
    """R007: 위험 적요 키워드 포함 ('상품권', '가계정', '가수금' 등).
    감사 관점: 자금 유용 관련 계정."""

def _generate_r008_entries(n: int) -> DataFrame:
    """R008: 관계사/특수관계자 거래.
    감사 관점: 이전가격 조작 위험."""

def _generate_benford_violation(df: DataFrame) -> DataFrame:
    """Benford 위반 데이터 삽입.
    특정 첫째 자릿수(예: 1, 5)를 과도하게 집중시켜
    MAD > 0.015가 되도록 조정."""

def save_to_excel(df: DataFrame, output_path: Path) -> Path:
    """생성된 데이터를 Excel 파일로 저장."""
```

## 데이터 스키마

생성되는 DataFrame의 컬럼 구조 (schema.yaml 일치):

| 컬럼          | 타입     | 예시 값             |
|---------------|----------|---------------------|
| journal_id    | str      | "JE-2025-00001"     |
| entry_date    | datetime | 2025-01-15 09:30:00 |
| account_code  | str      | "411000"            |
| account_name  | str      | "매출"              |
| debit_amount  | float    | 15,000,000          |
| credit_amount | float    | 0                   |
| description   | str      | "1월 제품 매출"     |
| department    | str      | "영업부"            |
| created_by    | str      | "김영희"            |
| source_type   | str      | "자동" / "수동"     |
| counterparty  | str      | "ABC상사"           |

## 이상 전표 유형별 상세

| 룰   | 생성 비율 | 핵심 특성                | 검증 기대                      |
|------|-----------|--------------------------|--------------------------------|
| R001 | ~2.5%     | 금액 4,900~4,999만원     | `is_near_threshold=True`       |
| R002 | ~2.5%     | 토/일 일자               | `is_weekend=True`              |
| R003 | ~2.5%     | 22~06시 시간             | `is_midnight=True`             |
| R004 | ~2.5%     | 월말 5일 + 1억 이상 매출 | `is_period_end=True` + 고액    |
| R005 | ~2.5%     | 동일 금액 차대 쌍        | `is_reversal=True`             |
| R006 | ~2.5%     | source_type='수동'       | `is_manual_je=True`            |
| R007 | ~2.5%     | 적요에 '상품권' 등       | `has_risk_keyword!=none`       |
| R008 | ~2.5%     | 거래처='관계사'          | `is_intercompany=True`         |

**합계:** ~20% 이상 전표 (anomaly_ratio 파라미터로 조절)

## gl_template.xlsx — 수동 Excel 템플릿

50건의 수동 작성 전표:
- 정상 전표 40건 + 이상 전표 10건
- **실제 ERP 엑셀과 유사한 형태:**
  - 상단 3행에 회사명/기간 등 제목
  - 4행이 실제 헤더 (한글 컬럼명)
  - 일부 셀 병합
  - 차변/대변이 하나의 '금액' 컬럼 + '차대구분' 형태
- **용도:** header_detector, column_mapper의 실전 테스트

## 데이터 흐름
```
generate_gl_data(n=10000, anomaly_ratio=0.20)
       ↓
  ├── _generate_normal_entries(8000)
  └── _generate_anomaly_entries(2000)
       ├── _generate_r001_entries(250)
       ├── _generate_r002_entries(250)
       ├── ... (각 룰 균등)
       └── _generate_benford_violation()
       ↓
save_to_excel(df, "data/sample/sample_gl.xlsx")
       ↓
[sample_gl.xlsx] → ingest/ → feature/ → validation/ → detection/ → db/
```

## 구현 순서
1. `generate_sample.py` — 정상 전표 생성기
2. 각 룰별 이상 전표 생성 함수 (R001~R008)
3. Benford 위반 데이터 삽입
4. `save_to_excel()` — Excel 저장
5. `gl_template.xlsx` — 수동 작성 (openpyxl로 제목/병합셀 포함)

## 의존성
- **선행:** `01-project-setup` (settings — 임계값, 키워드 참조)
- **외부 패키지:** `pandas`, `numpy`, `openpyxl`
- **후행:** `02-ingest` (생성된 파일을 입력으로 사용)

## 테스트 전략
- **생성 건수 확인:** `len(df) == n`
- **이상 비율 확인:** 이상 전표가 `anomaly_ratio ± 1%` 범위
- **각 룰 커버리지:** R001~R008 모든 유형 최소 1건 이상 존재
- **대차일치:** 전표 단위 debit_amount + credit_amount 합이 쌍으로 일치
- **Benford 위반:** 생성 데이터의 첫째 자릿수 분포가 Benford와 유의미하게 다름 (MAD > 0.015)
- **재현성:** 동일 seed → 동일 데이터

## Phase 구분
| 항목                                     | Phase          |
|------------------------------------------|----------------|
| generate_sample.py                       | MVP (Phase 1a) |
| gl_template.xlsx                         | MVP (Phase 1a) |
| 생성기 파라미터 확장 (Phase 2 이상 유형) | Phase 2        |

## 구현 시 주의사항
- **재현성:** `seed` 파라미터로 동일 결과 재현 가능 → 테스트 안정성
- **현실성:** 정상 전표도 실제 패턴 반영 (금액 분포, 영업일 집중 등)
- **대차일치:** 각 전표의 차변/대변 합이 일치하도록 생성 (회계 기본 원칙)
- **계정과목 코드:** 실제 K-IFRS 계정 체계 참고하여 현실적 코드 사용
- **한글 데이터:** 적요, 부서, 작성자 등은 한글로 생성 (실제 환경 반영)
- **Benford 위반 삽입:** 기존 금액을 조정하는 방식(예: 첫 자리를 5로 변경)이 아니라,
  특정 첫 자리가 과도한 새 데이터를 삽입하는 방식 사용
- **gl_template.xlsx의 ERP 유사성:** 상단 제목, 병합셀, 한글 헤더, 차대 통합 컬럼 등
  실제 ERP 엑셀 형태를 최대한 모방 → ingest 모듈의 실전 테스트 가치 극대화
