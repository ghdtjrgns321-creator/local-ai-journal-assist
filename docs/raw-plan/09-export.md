# 09. 감사조서 내보내기 (Export) [Phase 3 — 의존: 06, 07, 08]

## 목적

분석 결과를 Excel/PDF 감사조서로 내보내고,
모든 분석 활동을 Audit Trail로 기록하여 감사 증적을 확보한다.

## 관련 파일

```
src/export/
├── excel_exporter.py    # Excel 감사조서 생성
├── pdf_exporter.py      # PDF 감사조서 생성
└── audit_trail.py       # 감사 활동 로그
```

---

## 데이터 소스

Export 모듈은 DuckDB 테이블에서 데이터를 조회한다.
원본 데이터 기준: DataSynth v1.2.0 (319,204건 전표, 1,107,720 라인아이템, 44컬럼, 2026-04-14 실측).

| DuckDB 테이블/VIEW          | 용도                           | 예상 행 수     |
|-----------------------------|-------------------------------|---------------|
| `general_ledger`            | 원본 39 + 파생 18 + 탐지 3 = 60컬럼 | ~1.1M (라인아이템) |
| `anomaly_flags`             | 룰별 플래그 상세 (행×룰)      | 가변           |
| `anomaly_flag_summary` VIEW | 룰별 집계 통계                | 최대 22행 (활성 룰 수) |
| `benford_summary`           | Benford 배치 요약             | 배치당 1행     |
| `benford_digits`            | Benford 자릿수별 분포         | 배치당 9행     |
| `audit_trail`               | 감사 활동 로그 **(DDL 미정의 — 구현 시 06-db에 추가)** | 가변 |

---

## 컬럼 매핑 정책

### 내보내기 대상 컬럼 (Excel Raw Data / PDF 상세 테이블)

39개 원본 컬럼 중 **내보내기 대상과 제외 대상**을 구분한다.

**Header fields (전표 단위)**

| 원본 컬럼            | 한글 헤더        | 포함 | 비고                          |
|----------------------|-----------------|------|-------------------------------|
| document_id          | 전표ID          | O    | UUID                          |
| company_code         | 회사코드        | O    | C001, C002, C003              |
| fiscal_year          | 회계연도        | O    |                               |
| fiscal_period        | 회계기간        | O    | 1~12                          |
| posting_date         | 전기일시        | O    | datetime (KST)                |
| document_date        | 증빙일          | O    |                               |
| document_type        | 전표유형        | O    | SA, KR, KZ, DR, DZ 등        |
| currency             | 통화            | O    |                               |
| exchange_rate        | 환율            | △    | KRW 단일이면 생략 가능        |
| reference            | 참조번호        | O    | PO/GR/Invoice 번호            |
| header_text          | 전표 적요       | O    |                               |
| created_by           | 작성자          | △    | **마스킹 대상** (옵션)        |
| user_persona         | 사용자 유형     | O    |                               |
| source               | 전표 소스       | O    | Automated/Manual/Recurring/Adjustment |
| business_process     | 비즈니스 프로세스 | O    | P2P/O2C/R2R/H2R/TRE/A2R      |
| ledger               | 원장            | △    | 단일 원장(0L)이면 생략 가능   |
| approved_by          | 승인자          | △    | **마스킹 대상** (옵션)        |
| approval_date        | 승인일          | O    |                               |

**SoD fields (Sheet 5 SoD 시트 전용)**

| 원본 컬럼          | 한글 헤더        | 포함 | 비고                          |
|--------------------|-----------------|------|-------------------------------|
| sod_violation      | SoD위반여부     | △    | SoD 시트 필터 조건 전용       |
| sod_conflict_type  | SoD충돌유형     | △    | SoD 시트 출력 전용 (6종)      |

**Label fields (DataSynth 전용 — 감사조서 제외)**

| 원본 컬럼          | 제외 사유                                         |
|--------------------|---------------------------------------------------|
| is_fraud           | 실무 감사조서에 정답 레이블 미포함 (학습/평가용)  |
| fraud_type         | 동일                                              |
| is_anomaly         | 동일                                              |
| anomaly_type       | 동일                                              |

> Label 4개 컬럼은 모델 학습·평가 전용이다. 감사조서에는 탐지 파이프라인이 산출한
> `anomaly_score`, `risk_level`, `flagged_rules` 3개 컬럼으로 대체한다.
> sod_violation/sod_conflict_type은 Sheet 5 SoD 시트에서만 사용한다.

**Line fields (라인아이템 단위)**

| 원본 컬럼                  | 한글 헤더        | 포함 | 비고                    |
|----------------------------|-----------------|------|-------------------------|
| line_number                | 라인번호        | O    |                         |
| gl_account                 | GL계정          | O    |                         |
| debit_amount               | 차변금액        | O    | KRW 정수                |
| credit_amount              | 대변금액        | O    | KRW 정수                |
| local_amount               | 현지통화금액    | △    | KRW 단일이면 생략 가능  |
| cost_center                | 코스트센터      | O    |                         |
| profit_center              | 프로핏센터      | O    |                         |
| line_text                  | 라인 적요       | O    |                         |
| tax_code                   | 세금코드        | O    |                         |
| tax_amount                 | 세금액          | O    |                         |
| trading_partner            | 거래처(IC)      | O    | 내부거래용              |
| auxiliary_account_number   | 보조원장번호    | △    | **마스킹 대상** (옵션)  |
| auxiliary_account_label    | 보조원장라벨    | △    | **마스킹 대상** (옵션)  |
| lettrage                   | 대사그룹        | O    |                         |
| lettrage_date              | 대사일          | O    |                         |

**탐지 결과 컬럼 (파이프라인 산출)**

| 컬럼           | 한글 헤더  | 설명                                      |
|----------------|----------|-------------------------------------------|
| anomaly_score  | 위험점수  | 0.0~1.0 (종합 이상 점수)                  |
| risk_level     | 위험등급  | High / Medium / Low / Normal              |
| flagged_rules  | 위반룰    | CSV 문자열 (예: "L4-01,L4-02")                |

### 마스킹 정책

내보내기 시 **마스킹 옵션**을 제공한다. 활성화하면 아래 컬럼을 해싱 처리한다.

| 마스킹 대상 컬럼            | 처리 방식                        |
|-----------------------------|----------------------------------|
| created_by                  | SHA-256 앞 8자리로 치환          |
| approved_by                 | SHA-256 앞 8자리로 치환          |
| auxiliary_account_number    | 뒤 4자리 `****` 치환             |
| auxiliary_account_label     | 뒤 4자리 `****` 치환             |

---

## 핵심 클래스/함수

### `excel_exporter.py` — Excel 감사조서

```python
class ExcelExporter:
    """openpyxl로 감사조서 Excel 생성.

    워크시트 구성 (6개 시트):
    1. Summary     — 분석 요약 KPI, 프로세스별/법인별 분포
    2. Anomalies   — 이상 전표 목록 (risk_level != Normal)
    3. Benford     — Benford 분석 결과 (요약 + 자릿수별 분포)
    4. Rules       — 24개 룰별 위반 통계
    5. SoD         — 직무분리 위반 상세
    6. Raw Data    — 전체 데이터 (전표 단위 집계)
    """

    def export(
        self,
        pipeline_result: PipelineResult,
        output_path: Path,
        filters: ExportFilter | None = None,
        mask_pii: bool = False,
    ) -> Path:
        """감사조서 Excel 파일 생성."""
```

#### 시트별 상세 설계

**Sheet 1: Summary**

| 섹션                | 데이터 소스                | 내용                                      |
|---------------------|--------------------------|--------------------------------------------|
| 분석 대상 요약      | `general_ledger` 집계    | 전표 건수, 라인아이템 수, 분석 기간, 법인 수 |
| 위험 분포 KPI       | `general_ledger` 집계    | High/Medium/Low/Normal 건수 및 비율        |
| 프로세스별 분포     | `general_ledger` GROUP BY | O2C(26.5%), R2R(25.3%), P2P(24.2%), TRE(9.4%), H2R(8.6%), A2R(6.0%) |
| 법인별 분포         | `general_ledger` GROUP BY | C001(본사), C002(울산공장), C003(천안공장)  |
| 이상징후 요약       | `anomaly_flag_summary`   | 이상 전표 2.60%, 부정 의심 1.96%, SoD 위반 3.32% |
| 차트 (임베디드)     | Plotly → openpyxl Image  | 위험등급 파이차트, 프로세스별 바차트        |

**Sheet 2: Anomalies** (예상 ~8,000행)

| 컬럼              | 소스                    | 서식                              |
|-------------------|------------------------|------------------------------------|
| document_id       | general_ledger         | 텍스트                             |
| company_code      | general_ledger         |                                    |
| posting_date      | general_ledger         | yyyy-mm-dd HH:MM                   |
| document_type     | general_ledger         |                                    |
| business_process  | general_ledger         |                                    |
| gl_account        | general_ledger         |                                    |
| debit_amount      | general_ledger         | #,##0 (천단위 쉼표)               |
| credit_amount     | general_ledger         | #,##0                              |
| created_by        | general_ledger         | 마스킹 옵션 적용                   |
| anomaly_score     | general_ledger         | 0.00 (소수 2자리)                  |
| risk_level        | general_ledger         | 조건부 서식: High=빨강, Medium=노랑, Low=초록 |
| flagged_rules     | general_ledger         | 텍스트 (CSV)                       |

- 필터: `WHERE risk_level != 'Normal'`
- 정렬: `anomaly_score DESC`
- 헤더 고정: `freeze_panes = 'A2'`

**Sheet 3: Benford**

| 섹션        | 데이터 소스         | 내용                           |
|-------------|--------------------|---------------------------------|
| 요약 테이블 | `benford_summary`  | sample_size, MAD, chi2, KS, 판정 |
| 자릿수 분포 | `benford_digits`   | digit(1~9), observed, expected, deviation |
| 차트        | Plotly → Image     | 관측 vs 기대 분포 막대 차트    |

**Sheet 4: Rules** (22행)

| 컬럼        | 데이터 소스                | 내용                         |
|-------------|---------------------------|-----------------------------|
| rule_code   | `anomaly_flag_summary`    | L1-01~L1-03, L4-01~L2-04, L3-04~L3-09  |
| rule_name   | config/audit_rules.yaml   | 한글 룰명                    |
| layer       | —                         | A(무결성) / B(부정) / C(징후) |
| flagged_count| `anomaly_flag_summary`   | 위반 건수                    |
| flagged_pct | 산출                      | 위반율 (%)                   |
| avg_score   | `anomaly_flag_summary`    | 평균 점수                    |

**Sheet 5: SoD** (예상 ~10,595행)

| 컬럼             | 소스              | 내용                          |
|------------------|-------------------|-----------------------------|
| document_id      | general_ledger    | 위반 전표 ID                 |
| posting_date     | general_ledger    | 전기일시                     |
| business_process | general_ledger    | 프로세스                     |
| created_by       | general_ledger    | 작성자 (마스킹 옵션)        |
| approved_by      | general_ledger    | 승인자 (마스킹 옵션)        |
| sod_conflict_type| general_ledger    | 충돌 유형 6종                |
| debit_amount     | general_ledger    | 차변금액                     |
| credit_amount    | general_ledger    | 대변금액                     |

- 필터: `WHERE sod_violation = true` (탐지 파이프라인 산출 기준)
- SoD 충돌 유형: preparer_approver, requester_approver, payment_releaser, reconciler_poster, journal_entry_poster, master_data_maintainer

**Sheet 6: Raw Data**

- 전표 단위 집계(document_id 기준) → 볼륨 대응 (§ 데이터 볼륨 대응 참조)
- Label 6개 컬럼 제외, 탐지 결과 3개 컬럼 포함
- 자동 열 너비 조정, 헤더 고정

---

### `pdf_exporter.py` — PDF 감사조서

```python
class PDFExporter:
    """fpdf2로 감사조서 PDF 생성.

    페이지 구성 (8개 섹션):
    1. 표지          — 프로젝트명, 분석 대상, 분석 일시
    2. 분석 요약     — KPI, 위험 분포
    3. 프로세스 분포 — 6개 프로세스별 전표/금액 비중
    4. Benford 분석  — 분포 차트 + 판정 결과
    5. 이상 전표 Top N — 고위험 전표 테이블
    6. 룰별 위반 통계 — 24개 룰 요약
    7. 부정/SoD 요약  — 부정 유형별 건수 + SoD 충돌 유형별 건수
    8. 감사 의견      — LLM 생성 인사이트 (Phase 3, 선택)
    """

    def export(
        self,
        pipeline_result: PipelineResult,
        output_path: Path,
        top_n: int = 50,
        include_insights: bool = False,
        mask_pii: bool = False,
    ) -> Path:
        """감사조서 PDF 파일 생성."""
```

#### 페이지별 상세 설계

**Page 1: 표지**

```
항목             내용
프로젝트명       Local AI Audit Assistant
분석 대상        {company_code} ({법인명})
분석 기간        {fiscal_year}.{min_period} ~ {fiscal_year}.{max_period}
전표 건수        {document_count:,}건 / 라인아이템 {line_count:,}건
분석 일시        {export_timestamp} (KST)
분석자           {사용자명 또는 마스킹}
```

**Page 2: 분석 요약**

- KPI 카드: 전표 건수, 이상 비율(2.60%), 부정 의심(1.96%), SoD 위반(3.32%)
- 위험등급 분포 파이차트 (High/Medium/Low/Normal)
- 월별 전표 건수 라인차트 (1~12월, 12월 최대 ×1.4 강조)

**Page 3: 프로세스 분포**

- 프로세스별 전표 비중 수평 바차트:

```
R2R  ████████████████████████████  26.5%
O2C  █████████████████████████     25.9%
P2P  ██████████████████████        23.3%
H2R  █████████                      8.9%
TRE  ████████                       8.5%
A2R  ███████                        6.9%
```

- 법인별 × 프로세스 크로스 테이블 (C001/C002/C003)
- 시간대별 분포 히트맵 (심야 1.5%, 오전피크 29.7%, 마감러시 21.4%)

**Page 4: Benford 분석**

- `benford_summary`: sample_size, MAD, chi2, KS 통계량, 적합성 판정
- `benford_digits`: 관측 vs 기대 분포 막대 차트 (digit 1~9)
- 판정 기준: MAD ≤ 0.006 적합 / ≤ 0.012 한계적합 / > 0.012 부적합

**Page 5: 이상 전표 Top N** (기본 50건)

| 컬럼           | 서식                            |
|----------------|--------------------------------|
| document_id    | 앞 8자리 축약                   |
| posting_date   | yyyy-mm-dd                      |
| business_process| 약어 (P2P, O2C 등)            |
| gl_account     |                                 |
| debit_amount   | #,##0                          |
| anomaly_score  | 0.00                           |
| risk_level     | 색상 강조                       |
| flagged_rules  |                                 |

- 정렬: anomaly_score DESC
- 테이블 자동 페이지 분할

**Page 6: 룰별 위반 통계**

- 24개 룰을 Layer별로 그룹화:

```
L1 — 데이터 무결성 (3개 룰)
  L1-01 차대변균형    L1-02 필수필드누락    L1-03 무효계정

L2 — 부정 탐지 (10개 룰)
  L4-01 매출이상변동  L2-01 승인한도직하    L1-04 승인한도초과
  L2-02 중복지급      L2-03 중복전표        L1-05 자기승인
  L1-06 직무분리위반  L3-02 수기전표        L1-07 승인생략
  L3-03 관계사순환

L3/L4 — 이상징후 탐지 (9개 룰)
  L3-04 기말대규모    L3-05 주말전기        L3-06 심야전기
  L3-07 소급전기      L1-08 기간불일치      L3-08 위험적요
  L4-02 Benford위반   L4-03 이상고액        L4-04 비정상계정조합
```

- 룰별 위반 건수, 비율, 평균 점수 테이블

**Page 7: 부정/SoD 요약**

- 부정 유형별 건수 (13개 유형):

| 유형                    | 예상 건수 | 대응 룰 |
|-------------------------|----------|---------|
| DuplicatePayment        | ~385     | L2-02     |
| FictitiousTransaction   | ~370     | L1-04     |
| RevenueManipulation     | ~314     | L4-01     |
| SplitTransaction        | ~282     | L2-01     |
| TimingAnomaly           | ~173     | L3-07     |
| UnauthorizedAccess      | ~168     | L1-05~L1-07 |
| SuspenseAccountAbuse    | ~102     | L3-09     |
| ExpenseCapitalization   | ~90      | L2-04     |
| 기타 5종               | ~124     | —       |

- SoD 충돌 유형별 건수 (6개 유형):

| 충돌 유형              | 예상 건수 |
|------------------------|----------|
| preparer_approver      | ~531     |
| requester_approver     | ~165     |
| payment_releaser       | ~120     |
| reconciler_poster      | ~92      |
| journal_entry_poster   | ~86      |
| master_data_maintainer | ~83      |

**Page 8: 감사 의견** (Phase 3 LLM, 선택)

- Ollama + Qwen3-8B가 생성한 분석 인사이트
- `include_insights=True`일 때만 포함

---

### `audit_trail.py` — 감사 활동 로그

```python
@dataclass
class AuditEvent:
    timestamp: datetime       # KST 기준
    event_type: str           # 아래 이벤트 타입 참조
    user_action: str          # 사용자 행동 설명
    details: dict             # 이벤트별 상세 정보
    batch_id: str             # 업로드 배치 ID

class AuditTrail:
    """감사 활동 추적 로거.

    모든 분석 활동을 DuckDB audit_trail 테이블에 기록하여 감사 증적 확보.
    """

    def log(self, event: AuditEvent) -> None:
        """이벤트를 DuckDB audit_trail 테이블에 기록."""

    def export_trail(self, batch_id: str, output_path: Path) -> Path:
        """특정 배치의 전체 감사 활동 로그를 CSV로 내보내기."""

    def get_trail(self, batch_id: str) -> DataFrame:
        """특정 배치의 감사 활동 로그 조회."""
```

#### 이벤트 타입 정의

| event_type  | 발생 시점               | details 예시                                          |
|-------------|------------------------|-------------------------------------------------------|
| `upload`    | 파일 업로드 완료       | `{filename, rows, columns, file_size_mb, companies: ["C001","C002","C003"]}` |
| `validate`  | 스키마 검증 완료       | `{l1_pass, l2_pass, l3_pass, error_count, warning_count}` |
| `analysis`  | 탐지 파이프라인 완료   | `{total_docs, flagged_count, high_count, elapsed_sec}` |
| `query`     | LLM 질의 실행 (Phase 3)| `{query_text, result_rows}`                           |
| `filter`    | 대시보드 필터 변경     | `{company_code, business_process, risk_level, date_range}` |
| `export`    | 감사조서 내보내기      | `{format: "xlsx"|"pdf"|"csv", rows_exported, mask_pii}` |

---

## 필터 옵션

대시보드(Tab 5)에서 설정한 필터를 Export에 그대로 적용한다.

```python
@dataclass
class ExportFilter:
    company_codes: list[str] | None = None      # ["C001", "C002"] 등
    business_processes: list[str] | None = None  # ["P2P", "O2C"] 등
    risk_levels: list[str] | None = None         # ["High", "Medium"] 등
    date_from: date | None = None                # posting_date >= date_from
    date_to: date | None = None                  # posting_date <= date_to
    document_types: list[str] | None = None      # ["SA", "KR"] 등
```

- 필터가 None이면 전체 데이터 내보내기
- 프로세스별 감사조서 분리 출력: `ExportFilter(business_processes=["P2P"])` 식으로 개별 호출

---

## 데이터 볼륨 대응

DataSynth 기준 1,107,720 라인아이템은 Excel 행 제한(1,048,576)을 초과할 수 있다.

| 전략           | 적용 시트       | 방법                                                  |
|----------------|----------------|-------------------------------------------------------|
| 전표 단위 집계 | Raw Data       | document_id 기준 1행으로 집계 (319,204행, 제한 이내)  |
| 필터 적용      | Raw Data       | ExportFilter로 범위 축소 후 라인아이템 단위 출력      |
| 시트 분할      | Raw Data       | 50만행 초과 시 Raw Data (1), Raw Data (2)로 자동 분할 |
| 이상만 출력    | Anomalies      | risk_level != Normal 필터 (예상 ~8,000행, 제한 이내)  |

### 전표 단위 집계 컬럼 (Raw Data 시트)

라인아이템을 document_id 기준으로 집계할 때 아래 규칙을 적용한다:

| 컬럼               | 집계 방식                              |
|--------------------|----------------------------------------|
| Header fields      | 그대로 유지 (document_id별 동일)       |
| line_count         | COUNT(line_number)                     |
| total_debit        | SUM(debit_amount)                      |
| total_credit       | SUM(credit_amount)                     |
| gl_accounts        | LISTAGG(DISTINCT gl_account, ', ')     |
| anomaly_score      | MAX(anomaly_score)                     |
| risk_level         | MAX(risk_level) — High > Medium > Low  |
| flagged_rules      | LISTAGG(DISTINCT flagged_rules, ', ')  |

---

## 데이터 흐름

```
[DuckDB 테이블]
  general_ledger ─────────┬──→ ExcelExporter.export() → 감사조서.xlsx
  anomaly_flags ──────────┤
  anomaly_flag_summary ───┤
  benford_summary ────────┤──→ PDFExporter.export()   → 감사조서.pdf
  benford_digits ─────────┘
  audit_trail ──────────────→ AuditTrail.export_trail() → audit_trail.csv

[대시보드 Tab 5: Export]
  ExportFilter 설정 → 포맷 선택 → 다운로드 버튼
  st.download_button(data=exported_bytes, file_name=...)

--- 별도 흐름 ---
[사용자 모든 활동] → AuditTrail.log(event) → [DuckDB audit_trail 테이블]
```

---

## 구현 순서

1. `audit_trail.py` — 이벤트 로깅 (다른 모듈에서 호출, DuckDB DDL 추가)
2. `excel_exporter.py` — Excel 감사조서 생성 (6개 시트)
3. `pdf_exporter.py` — PDF 감사조서 생성 (8개 섹션)

## 의존성

- **선행:** `06-db` (DuckDB 테이블/VIEW), `07-dashboard` (Plotly 차트 이미지 변환), `08-llm` (인사이트 텍스트)
- **외부 패키지:** `openpyxl` (Excel), `fpdf2` (PDF) — dependency-groups `export`에 포함
- **후행:** `07-dashboard/tab_export.py`에서 호출

## 테스트 전략

| 대상             | 테스트 내용                                          | 검증 방법                        |
|------------------|-----------------------------------------------------|----------------------------------|
| excel_exporter   | 샘플 데이터 → Excel 생성                            | openpyxl 재로드 → 시트 수(6), 행 수 확인 |
| excel_exporter   | 필터 적용 (company_code="C001")                     | 출력 행이 C001만 포함하는지 확인 |
| excel_exporter   | 마스킹 옵션 활성화                                  | created_by 값이 해싱되었는지 확인 |
| excel_exporter   | 볼륨 초과 시 시트 분할                              | 100만행+ 데이터 → 2개 시트 생성  |
| pdf_exporter     | 샘플 데이터 → PDF 생성                              | 파일 존재 + 페이지 수 ≥ 4 확인   |
| pdf_exporter     | 한글 출력                                           | NanumGothic 폰트 렌더링 확인     |
| pdf_exporter     | top_n 파라미터                                      | 이상 전표 테이블 행 수 ≤ top_n   |
| audit_trail      | 이벤트 6종 로그 → 조회                              | DuckDB 조회 → 기록 일치          |
| audit_trail      | export_trail CSV 출력                               | CSV 파싱 → 행/컬럼 수 확인       |
| 통합             | 업로드→분석→필터→내보내기 전체 흐름                  | audit_trail에 4개 이벤트 기록    |

## Phase 구분

| 항목                    | Phase   |
|-------------------------|---------|
| audit_trail (기본 로깅) | Phase 3 |
| excel_exporter          | Phase 3 |
| pdf_exporter            | Phase 3 |
| LLM 인사이트 포함 PDF  | Phase 3 |

## 구현 시 주의사항

- **한글 폰트:** fpdf2에서 `add_font()`로 TTF 등록 필수 (NanumGothic 권장)
- **차트 이미지:** Plotly `fig.to_image()` → kaleido 패키지 필요
- **Excel 행 제한:** 라인아이템 1.1M행은 Excel 제한(1,048,576) 초과 가능 → 전표 단위 집계 또는 시트 분할
- **audit_trail DDL:** `06-db/schema.py`에 audit_trail 테이블 DDL 추가 필요
- **마스킹:** 내보내기 시 `mask_pii=True` 옵션으로 개인 식별 정보 해싱
- **타임존:** 모든 timestamp는 KST(Asia/Seoul) 기준
- **Label 컬럼 제외:** §컬럼 매핑 정책 참조 (is_fraud, fraud_type, is_anomaly, anomaly_type 4개)
