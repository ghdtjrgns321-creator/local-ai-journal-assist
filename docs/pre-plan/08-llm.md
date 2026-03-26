# 08. LLM 연동 (Ollama + Vanna AI) [Phase 3 — 의존: 06, 07]

## 목적

로컬 LLM(Ollama + Qwen3-8B)과 Vanna AI 2.0을 활용하여
자연어 질의 → SQL 생성 → 결과 해석까지 자동화한다.
또한 NLP & Transformer를 통해 **텍스트 데이터(적요, 참조번호 등)**에서
숫자만으로는 발견할 수 없는 부정 징후를 탐지한다.

---

## NLP & Transformer: 텍스트에서 부정을 읽는 기술

### 숫자 분석만으로는 부족한 이유

Phase 1b 룰 기반과 Phase 2b ML 탐지기는 **숫자 데이터**(금액, 날짜, 계정코드 등)를 분석한다.
그러나 숫자가 완벽하게 정상이어도 **텍스트에 단서가 남는** 케이스가 존재한다.

```
사례: header_text와 gl_account 불일치
  - 숫자 분석: 금액 정상, 날짜 정상, 계정 유효 → 룰/ML 미탐지
  - 텍스트 단서: header_text "Vendor Invoice INV-62393960" + gl_account 4000(매출)
  - NLP 분석: 매입 송장(Vendor Invoice)이 매출 계정에 전기 → 계정-적요 불일치 탐지
```

### Phase별 텍스트 분석 진화

| Phase | 방식                            | 기술                                                     | 탐지 범위                        | 한계                             |
|:------|:--------------------------------|:---------------------------------------------------------|:---------------------------------|:---------------------------------|
| 1b    | 키워드 정확 매칭                 | `if "suspense" in text` (audit_rules.yaml)               | 사전 등록 키워드만 탐지           | 은어·동의어·우회 표현 못 잡음     |
| 3     | 형태소 분석 + 임베딩 + LLM 추론 | kiwipiepy(한국어 ERP) + Ollama Qwen3-8B(의미 분석)       | 문맥 이해, 계정-적요 불일치 탐지  | GPU 의존, 환각(hallucination) 위험, 추론 속도 제약 |

### Transformer의 역할

Transformer는 NLP의 핵심 엔진이다. Qwen3 등 현대 LLM의 기반 아키텍처.

- **키워드 매칭**: `"Suspense"` 단어가 있으면 탐지. `"Temporary allocation"`, `"Unallocated deposit"` 등 우회 표현은 미탐지.
- **Transformer 기반 NLP**: `"Temporary allocation"`과 `"Suspense"` 의미 유사성 이해. 계정-적요 불일치, 비정상 거래 설명 패턴 탐지 가능.

본 프로젝트에서는 Ollama + Qwen3-8B(Transformer 기반 LLM)를 로컬에서 실행하여
적요 텍스트의 문맥을 분석한다. 구현 모듈: `src/detection/nlp_analyzer.py` ([05-detection.md](05-detection.md) Phase 3 탐지기 참조).

### NLP가 잡는 케이스 (키워드 매칭이 놓치는 것)

| 유형               | 키워드 매칭 결과 | NLP/Transformer 결과 | DataSynth 예시                                         |
|:-------------------|:----------------|:---------------------|:-------------------------------------------------------|
| 계정-적요 불일치   | ❌ 미탐지        | ✅ 탐지               | header `"Payroll Processing"` + gl_account `4000`(매출) |
| 우회 표현          | ❌ 미탐지        | ✅ 탐지               | `"Temporary allocation"` = suspense 계정 거래          |
| 프로세스-계정 불일치| ❌ 미탐지       | ✅ 탐지               | business_process `O2C` + gl_account `2000`(매입채무)   |
| 비정형 적요        | △ 길이만 판정   | ✅ 문맥 판정          | header_text `"Adjustment"` — 구체적 사유 없음          |
| IC 거래 이상       | ❌ 미탐지        | ✅ 탐지               | `"IC Management Fee"` + 비정상 금액                     |

> **한국어 ERP 적용 시**: DataSynth는 영문 적요이므로 위 예시 기반. 실제 한국 ERP(더존, 영림원 등)의 한국어 적요에는 kiwipiepy 형태소 분석 + 한국어 위험 키워드(가수금, 상품권, 유흥 등) 매칭이 활성화된다.

---

## DataSynth 텍스트 필드 현황

> DataSynth v1.2.0 실측 기준. NLP 분석 전략의 입력 데이터 정의.

### 텍스트 필드 3종

| 필드          | 레벨         | 채움률 | 언어 | 구조화 수준 | 용도                     |
|:--------------|:-------------|:-------|:-----|:-----------|:-------------------------|
| header_text   | 전표(Header) | ~100%  | 영문 | 높음        | 거래 유형 + 참조번호 + 거래처 |
| line_text     | 라인(Line)   | ~18%   | 영문 | 높음        | P2P/IC 거래 상세         |
| reference     | 전표(Header) | ~100%  | 영문 | 매우 높음   | PO/GR/INV/PAY 문서 번호  |

### header_text 프로세스별 패턴

```
P2P 입고:   "Goods Receipt GR-C001-0000000001 - V-000001"
P2P 송장:   "Vendor Invoice INV-62393960 - V-000001"
P2P 지급:   "Payment PAY-C001-0000000001 - V-000001"
O2C 매출:   "Customer Invoice CI-C001-0000000001 - K-000001"
O2C 수금:   "Customer Payment CR-C001-0000000001 - K-000001"
R2R 결산:   "Accruals" / "Deferred Expense" / "Year End Adjustment"
IC  거래:   (공백 — line_text에 상세 기재)
H2R 급여:   "Payroll Processing" / "Employee Benefits"
TRE 자금:   "Bank Transfer" / "Loan Repayment"
A2R 자산:   "Asset Acquisition" / "Depreciation"
```

### line_text 프로세스별 현황

| 프로세스 | null 비율 | 패턴                                              |
|:---------|:----------|:--------------------------------------------------|
| P2P      | ~0%       | header_text와 동일 또는 거래처 코드 (`V-000001`)  |
| IC       | ~0%       | `"IC {ExpenseType} from {Company}"` (예: `"IC Management Fee Expense from C001"`) |
| O2C      | 100%      | 미사용 → header_text로 대체                       |
| R2R      | 100%      | 미사용 → header_text로 대체                       |
| H2R      | 100%      | 미사용 → header_text로 대체                       |
| TRE      | 100%      | 미사용 → header_text로 대체                       |

### NLP 분석 텍스트 우선순위

```
1순위: header_text  (100% 채워짐, 구조화된 영문 — 프로세스/거래 유형 파싱 가능)
2순위: reference     (PO/GR/INV/PAY 번호 — 3-way matching 추적용)
3순위: line_text     (P2P/IC만 존재, ~18% 채움률 — 거래처/IC 상세)
```

**null 처리 전략**: `COALESCE(line_text, header_text, '')` — line_text null 시 header_text 폴백.

---

## 관련 파일

```
src/llm/
├── ollama_client.py       # Ollama API 클라이언트
├── text_to_sql.py         # 하이브리드 Text-to-SQL (Vanna + 템플릿 폴백)
├── sql_validator.py       # 생성 SQL 검증
├── prompt_presets.py      # 감사 프롬프트 프리셋 12종
└── insight_generator.py   # 결과 해석 자연어 생성
```

## 핵심 클래스/함수

### `ollama_client.py` — Ollama 연결

```python
class OllamaClient:
    """Ollama REST API 래퍼.

    - 모델 가용성 확인
    - 채팅 완료 호출
    - 스트리밍 응답 지원 (대시보드 Chat UI용)
    """

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url   # "http://localhost:11434"
        self.model = model         # "qwen3:8b"

    def is_available(self) -> bool:
        """Ollama 서버 + 모델 가용성 확인."""

    def chat(self, messages: list[dict], temperature: float = 0.1) -> str:
        """채팅 완료 호출. 감사 분석용이므로 낮은 temperature."""

    def stream_chat(self, messages: list[dict]) -> Iterator[str]:
        """스트리밍 응답. Streamlit chat UI에서 사용."""
```

### `text_to_sql.py` — Vanna AI 2.0 통합

```python
class AuditTextToSQL:
    """하이브리드 Text-to-SQL 엔진.

    1순위: Vanna AI 2.0 (DuckDB + Ollama + ChromaDB)
    2순위: 템플릿 매칭 폴백 (프리셋 쿼리)
    """

    def __init__(self, conn, ollama_client: OllamaClient):
        # Vanna 초기화
        self.vn = VannaDefault(model="qwen3:8b", config={"ollama_host": ...})
        self.vn.connect_to_duckdb(...)

    def train(self) -> None:
        """DDL + 도메인 용어 + 샘플 Q&A로 Vanna 학습.
        상세 학습 데이터는 §Vanna 학습 데이터 명세 참조.
        """

    def ask(self, question: str) -> SQLResult:
        """자연어 질문 → SQL 생성 → 실행 → 결과 반환.

        반환:
        - sql: 생성된 SQL
        - result: DataFrame 결과
        - chart: Plotly Figure (자동 생성)
        - source: 'vanna' | 'template' | 'failed'
        """

    def _template_fallback(self, question: str) -> str | None:
        """키워드 기반 프리셋 쿼리 매칭. Vanna 실패 시 폴백."""
```

### Vanna 학습 데이터 명세

`train()` 메서드에서 3가지 유형의 데이터를 ChromaDB에 학습시킨다.

#### (a) DDL 학습 — 4개 테이블 + 1 VIEW

`src/db/schema.py`의 `SCHEMA_DDL` 전문을 학습. 핵심 테이블:

```sql
-- general_ledger: 원본 39개 + approval_level + 파생변수 18종 + 탐지결과 3종
--   원본 Header: document_id, company_code, fiscal_year, fiscal_period,
--     posting_date, document_date, document_type, currency, exchange_rate,
--     reference, header_text, created_by, user_persona, source,
--     business_process, ledger, approved_by, approval_date,
--     is_fraud, fraud_type, is_anomaly, anomaly_type,
--     sod_violation, sod_conflict_type
--   원본 Line: line_number, gl_account, debit_amount, credit_amount,
--     local_amount, cost_center, profit_center, line_text, tax_code,
--     tax_amount, trading_partner, auxiliary_account_number,
--     auxiliary_account_label, lettrage, lettrage_date
--   파생변수: is_weekend, is_after_hours, is_period_end, days_backdated,
--     fiscal_period_mismatch, is_holiday, is_near_threshold, exceeds_threshold,
--     amount_zscore, amount_magnitude, is_round_number, is_manual_je,
--     is_intercompany, is_revenue_account, first_digit, is_suspense_account,
--     description_quality, has_risk_keyword
--   탐지결과: anomaly_score, risk_level, flagged_rules

-- anomaly_flags: document_id × rule_code 단위 상세 플래그
-- benford_summary: Benford 배치 요약 (배치당 1행)
-- benford_digits: Benford 자릿수별 분포 (배치당 9행)
-- anomaly_flag_summary: VIEW — 룰별 집계
```

#### (b) 도메인 용어 학습 — Vanna documentation

```python
# 비즈니스 프로세스 (6종)
vn.train(documentation="""
business_process 값과 의미:
  P2P (23.3%) = Procure-to-Pay, 매입. document_type: WE(입고), KR(매입송장), KZ(대금지급)
  O2C (25.9%) = Order-to-Cash, 매출. document_type: WL(출고), DR(매출송장), DZ(수금)
  R2R (26.5%) = Record-to-Report, 결산. document_type: SA(일반분개), IC(내부거래소거)
  H2R (8.9%)  = Hire-to-Retire, 인사/급여. document_type: HR(급여전표)
  TRE (8.5%)  = Treasury, 자금관리. document_type: KZ(이체), SA(이자인식)
  A2R (6.9%)  = Acquire-to-Retire, 자산관리. document_type: AA(자산전표)
""")

# 사용자 페르소나 (5종)
vn.train(documentation="""
user_persona 값:
  automated_system (68.0%) — ERP 자동 전기, 배치 처리
  junior_accountant (12.8%) — 일상 수기 전표, 경비 정산. TRE 접근 불가.
  senior_accountant (9.6%) — 결산 조정, 복합 전표
  controller (4.9%) — 결산 마감 주도 (R2R 87.2% 집중)
  manager (4.8%) — 승인, 대규모 조정 (R2R 76.0% 집중)
""")

# 부정 유형 (fraud_type, 13종)
vn.train(documentation="""
fraud_type 값 (총 2,008건, 1.9%):
  DuplicatePayment(385), FictitiousTransaction(370), RevenueManipulation(314),
  SplitTransaction(282), TimingAnomaly(173), UnauthorizedAccess(168),
  SuspenseAccountAbuse(102), ExpenseCapitalization(90),
  RoundDollarManipulation(26), ExceededApprovalLimit(23),
  JustBelowThreshold(22), SelfApproval(21), SegregationOfDutiesViolation(12)
""")

# 이상징후 유형 (anomaly_type, 상위 10종)
vn.train(documentation="""
anomaly_type 값 (총 7,959건, 7.5%):
  NewCounterparty(1,312), UnusualAccountPair(1,048), MissingRelationship(897),
  DormantAccountActivity(868), UnmatchedIntercompany(699),
  CircularTransaction(447), TransferPricingAnomaly(425),
  CentralityAnomaly(421), CircularIntercompany(211), UnusualTiming(200)
""")

# SoD 충돌 유형 (sod_conflict_type, 6종)
vn.train(documentation="""
sod_conflict_type 값 (총 1,080건, 1.0%):
  preparer_approver(531), requester_approver(165), payment_releaser(120),
  reconciler_poster(92), journal_entry_poster(86), master_data_maintainer(83)
""")

# GL 계정 체계
vn.train(documentation="""
gl_account 체계 (430개 GL 계정, K-IFRS):
  1xxx: 자산 — 1000~1030(현금), 1100~1160(채권), 1150(IC채권), 1200(재고), 1500~1600(유형자산)
  2xxx: 부채 — 2000~2050(채무), 2050(IC채무), 2100~2120(세금), 2200~2300(미지급), 2400~2700(차입), 2900(GR/IR정리)
  3xxx: 자본 — 3000(자본금), 3100(APIC), 3200~3300(이익잉여금)
  4xxx: 매출 — 4000~4020(매출/할인/반품), 4100(용역), 4500(IC매출)
  5xxx: 매출원가 — 5100(원재료), 5200(직접노무), 5300(제조간접)
  6xxx: 판관비 — 6000(감가상각), 6100~6200(급여/복리), 6300~6900(임차~대손)
  7xxx: 영업외 — 7100(이자비용), 7500(외환)
  8xxx: 세금 — 8000(법인세)
""")

# 3법인 구조
vn.train(documentation="""
company_code: C001(본사, 서울), C002(울산공장), C003(천안공장)
통화: KRW 단일. 회계연도: 2022년 1~12월.
전표 규모: 106,489건(document_id), 1,106,356건(라인아이템)
""")
```

#### (c) 샘플 Q&A 학습 — Vanna 정확도 핵심

```python
# 프로세스 분석
vn.train(question="P2P 프로세스에서 수기 전표 건수는?",
         sql="SELECT COUNT(DISTINCT document_id) FROM general_ledger "
             "WHERE business_process = 'P2P' AND source = 'Manual'")

# 부정 추이
vn.train(question="월별 부정 전표 추이",
         sql="SELECT fiscal_period, COUNT(DISTINCT document_id) AS fraud_cnt "
             "FROM general_ledger WHERE is_fraud = true "
             "GROUP BY fiscal_period ORDER BY fiscal_period")

# 법인별 이상징후
vn.train(question="C001 본사의 이상징후 유형별 건수",
         sql="SELECT anomaly_type, COUNT(DISTINCT document_id) AS cnt "
             "FROM general_ledger WHERE company_code = 'C001' AND is_anomaly = true "
             "GROUP BY anomaly_type ORDER BY cnt DESC")

# SoD 위반 분석
vn.train(question="SoD 위반 전표의 작성자와 승인자 목록",
         sql="SELECT DISTINCT created_by, approved_by, sod_conflict_type "
             "FROM general_ledger WHERE sod_violation = true "
             "ORDER BY sod_conflict_type")

# 임계값 직하
vn.train(question="승인한도 직하 전표 중 수기입력 비율",
         sql="SELECT source, COUNT(DISTINCT document_id) AS cnt, "
             "ROUND(COUNT(DISTINCT document_id) * 100.0 / "
             "SUM(COUNT(DISTINCT document_id)) OVER(), 1) AS pct "
             "FROM general_ledger WHERE is_near_threshold = true "
             "GROUP BY source")

# IC 거래 분석
vn.train(question="내부거래에서 법인 간 순잔액",
         sql="SELECT company_code, trading_partner, "
             "SUM(debit_amount) - SUM(credit_amount) AS net_balance "
             "FROM general_ledger WHERE is_intercompany = true "
             "AND trading_partner IS NOT NULL "
             "GROUP BY company_code, trading_partner")

# 고액 기말 전표
vn.train(question="12월 매출 5천만 이상 이상거래",
         sql="SELECT document_id, posting_date, gl_account, debit_amount, "
             "header_text, fraud_type, anomaly_type "
             "FROM general_ledger "
             "WHERE fiscal_period = 12 AND business_process = 'O2C' "
             "AND debit_amount >= 50000000 AND (is_fraud = true OR is_anomaly = true)")

# 심야/주말 전표
vn.train(question="심야에 처리된 수기 전표",
         sql="SELECT document_id, posting_date, created_by, user_persona, "
             "business_process, debit_amount "
             "FROM general_ledger "
             "WHERE is_after_hours = true AND source = 'Manual' "
             "ORDER BY posting_date")

# 위험 적요 전표
vn.train(question="위험 키워드가 포함된 전표 목록",
         sql="SELECT document_id, header_text, line_text, gl_account, "
             "debit_amount, has_risk_keyword, description_quality "
             "FROM general_ledger "
             "WHERE has_risk_keyword IS NOT NULL AND has_risk_keyword != 'none'")

# 룰별 탐지 현황
vn.train(question="탐지 룰별 플래그 건수",
         sql="SELECT rule_code, track_name, flagged_count, avg_score "
             "FROM anomaly_flag_summary "
             "ORDER BY flagged_count DESC")
```

### `sql_validator.py` — SQL 안전성 검증

```python
def validate_sql(sql: str) -> ValidationResult:
    """LLM이 생성한 SQL의 안전성 검증.

    1. DML 차단: INSERT, UPDATE, DELETE, DROP, ALTER 등 거부
    2. 서브쿼리 깊이 제한 (최대 3단계)
    3. DuckDB 문법 유효성 (EXPLAIN으로 파싱만 실행)
    4. 결과 행 수 제한 (LIMIT 없으면 자동 추가)
    """
```

### `prompt_presets.py` — 감사 프리셋 12종

```python
AUDIT_PRESETS = {
    # === 기본 분석 6종 ===
    "high_risk_overview": {
        "label": "고위험 전표 현황",
        "question": "risk_level이 HIGH 이상인 전표의 건수, 총 debit_amount 합계, fraud_type별 분포를 보여줘",
    },
    "weekend_midnight": {
        "label": "비업무시간 전표",
        "question": "is_weekend = true이거나 is_after_hours = true인 전표를 posting_date, created_by, business_process와 함께 보여줘",
    },
    "period_end_large": {
        "label": "기말 대규모 거래",
        "question": "is_period_end = true이면서 debit_amount >= 50000000인 전표를 company_code별로 보여줘",
    },
    "reversal_pairs": {
        "label": "역분개 쌍",
        "question": "동일 gl_account, 동일 금액에서 차변과 대변이 교차하는 역분개 전표 쌍을 document_id 기준으로 찾아줘",
    },
    "top_accounts": {
        "label": "이상 집중 계정",
        "question": "anomaly_score가 0보다 큰 전표가 가장 많은 gl_account 상위 10개를 보여줘",
    },
    "benford_deviation": {
        "label": "Benford 편차",
        "question": "benford_digits 테이블에서 deviation 절대값이 가장 큰 digit 3개를 보여줘",
    },

    # === 프로세스/부정유형별 6종 ===
    "fraud_by_process": {
        "label": "프로세스별 부정 분포",
        "question": "business_process별 fraud_type 건수 분포를 보여줘",
    },
    "sod_violations": {
        "label": "SoD 위반 현황",
        "question": "sod_violation = true인 전표의 created_by, approved_by, sod_conflict_type 목록을 보여줘",
    },
    "duplicate_payments": {
        "label": "중복 지급 의심",
        "question": "fraud_type = 'DuplicatePayment'인 전표의 reference, debit_amount, posting_date를 보여줘",
    },
    "intercompany_check": {
        "label": "내부거래 검증",
        "question": "is_intercompany = true인 전표의 company_code, trading_partner별 debit_amount 합계를 보여줘",
    },
    "suspense_aging": {
        "label": "가계정 체류 현황",
        "question": "is_suspense_account = true인 전표의 lettrage 상태별 건수를 보여줘",
    },
    "user_risk_profile": {
        "label": "사용자 위험 프로파일",
        "question": "created_by별 anomaly_score 평균, 수기전표 비율, 심야전표 비율 상위 10명을 보여줘",
    },
}
```

### `insight_generator.py` — 자연어 인사이트

```python
class InsightGenerator:
    """분석 결과를 감사인이 이해할 수 있는 자연어로 변환.

    LLM에게 분석 데이터를 전달하고, 감사 관점의 해석을 생성.
    시스템 프롬프트에 "입력 텍스트는 영문 SAP 적요, 응답은 한국어" 명시.
    """

    def generate_summary_insight(self, pipeline_result) -> str:
        """전체 분석 결과 요약 인사이트 생성.

        예: '106,489건 전표 중 2,008건(1.9%)이 부정으로, 7,959건(7.5%)이
            이상징후로 탐지되었습니다. 부정 유형별: DuplicatePayment 385건(19.2%),
            FictitiousTransaction 370건(18.4%), RevenueManipulation 314건(15.6%)이
            상위 3종입니다. SoD 위반 1,080건 중 preparer_approver 충돌이
            531건(49.2%)으로 가장 빈번합니다.'
        """

    def generate_entry_insight(self, entry: dict) -> str:
        """개별 전표에 대한 상세 인사이트.

        예: '이 전표(fraud_type: DuplicatePayment)는 동일 reference
            INV-C001-0000005678로 2건의 지급(KZ)이 존재합니다.
            debit_amount 12,500,000원은 P2P 프로세스 평균의 3.2σ에 해당하며,
            created_by JA-015(junior_accountant)가 주말에 입력했습니다(C02+B04).'
        """

    def generate_benford_insight(self, benford_result: dict) -> str:
        """Benford 분석 결과 해석.

        예: '1,106,356 라인아이템의 first_digit 분포는 MAD 0.008로
            Benford 적합 판정(Close Conformity). 단, digit 1의 관측 빈도 32.1%는
            기대값 30.1% 대비 +2.0%p 초과 — R2R(결산조정) 프로세스의
            round_number 비율(25%)이 기여 요인으로 추정됩니다.'
        """
```

## 데이터 흐름

```
[사용자 자연어 질문] (Tab 4 Chat UI)
       ↓
text_to_sql.ask(question)
       ↓
  ┌── Vanna AI 2.0 ──┐
  │ DDL + 도메인용어   │
  │ + 샘플 Q&A 학습   │
  │ question → SQL    │
  │ SQL → DuckDB 실행 │
  │ 결과 → Plotly     │
  └────────┬──────────┘
           │ (실패 시)
  ┌── 템플릿 폴백 ────┐
  │ 키워드 → 프리셋SQL │
  │ (12종 프리셋 매칭) │
  └────────┬──────────┘
           ↓
sql_validator.validate_sql(sql)
           ↓
[실행 결과 DataFrame + Plotly Figure]
           ↓
insight_generator → 자연어 해석 (한국어)
           ↓
[Chat UI에 SQL + 결과 + 차트 + 인사이트 표시]
```

## 구현 순서

1. `ollama_client.py` — Ollama 연결 + 모델 확인
2. `sql_validator.py` — SQL 안전성 검증 (LLM 독립적)
3. `prompt_presets.py` — 12종 프리셋 정의
4. `text_to_sql.py` — Vanna 초기화 + train(DDL/도메인용어/Q&A) + ask + 폴백
5. `insight_generator.py` — 자연어 인사이트 생성

## 의존성

- **선행:** `06-db` (DuckDB 스키마, 데이터), `01-project-setup` (Ollama 설정)
- **외부 패키지:** `vanna[duckdb,ollama,chromadb]`, `ollama`
- **후행:** `07-dashboard/tab_chat.py` (Chat UI), `09-export` (인사이트 포함 내보내기)

## 테스트 전략

- **ollama_client:** 서버 가용성 확인, mock 응답 테스트
- **sql_validator:** DML 차단 확인, 정상 SELECT 통과 확인
- **text_to_sql:** 프리셋 질문 12종에 대해 유효 SQL 생성 확인
- **insight_generator:** 결과 dict 입력 → 비어있지 않은 한국어 문자열 반환 확인
- **E2E 시나리오:**
  - `"12월 O2C 프로세스에서 debit_amount >= 50,000,000이고 is_fraud = true인 전표"` → SQL → DataFrame → 인사이트
  - `"C002 울산 법인의 월별 SoD 위반 추이"` → SQL → DataFrame → 차트
  - `"junior_accountant가 Manual 입력한 전표 중 fraud_type 분포"` → SQL → DataFrame
  - `"IC 거래에서 trading_partner별 순잔액"` → SQL → DataFrame → 인사이트

## Phase 구분

| 항목                  | Phase   |
|-----------------------|---------|
| ollama_client         | Phase 3 |
| text_to_sql (Vanna)   | Phase 3 |
| sql_validator         | Phase 3 |
| prompt_presets        | Phase 3 |
| insight_generator     | Phase 3 |

## LLM 모델 선택

| 우선순위 | 모델               | 용도                  | VRAM |
|----------|--------------------|-----------------------|------|
| 1순위    | Qwen3-8B (Q4_K_M)  | 범용 (인사이트, 해석) | ~6GB |
| 폴백     | Qwen2.5-Coder-7B   | Text-to-SQL 특화      | ~6GB |

**개발 환경:** RTX 3070 Ti (VRAM 8GB) → 위 모델 중 하나만 로드 가능

---

## C06 위험 적요 LLM 보완 (Phase 3 확장)

Phase 1에서는 `audit_rules.yaml`의 `suspense_keywords` + `suspense_account_codes`로 C06을 탐지한다.
Phase 3에서 LLM을 **보완 레이어**로 추가하여 키워드/GL 코드 매칭이 놓치는 케이스를 잡는다.

### Phase 1 키워드 매칭 현황

```yaml
# audit_rules.yaml 실측
suspense_keywords:      # 한글 + 영문 (DataSynth는 영문만 매칭)
  - "가수금", "가지급", "가계정", "미결산", "임시"
  - "[Ss]uspense", "[Cc]learing", "[Tt]emporary", "[Uu]nallocated", "[Mm]iscellaneous"

suspense_account_codes:  # GL 코드 기반 1순위 탐지
  - "1190"(가지급), "1290"(선급금 미정리), "2190"(가수금), "2900"(GR/IR 청산), "9990"(임시)
```

### DataSynth 적요 특성과 LLM 보완 필요성

DataSynth 텍스트는 **영문 + 구조화** → 정규식으로 프로세스/거래 유형 파싱 가능.
LLM이 필요한 케이스는 **구조화 패턴 미매칭 + 계정-적요 불일치** 건에 한정된다.

| 케이스                       | 정규식 처리 | LLM 필요 | DataSynth 예시                                  |
|:-----------------------------|:-----------|:---------|:------------------------------------------------|
| P2P/IC 정형 적요             | ✅          | ❌        | `"Goods Receipt GR-C001-... - V-000001"`        |
| 계정-적요 불일치             | ❌          | ✅        | header `"Vendor Invoice"` + gl `4000`(매출)     |
| 프로세스-문서유형 불일치     | ❌          | ✅        | bp `O2C` + document_type `KR`(매입송장)         |
| 비정형 결산조정 적요         | △           | ✅        | `"Adjustment"` — 구체적 사유 부재               |
| 한국어 적요 (실제 ERP)       | △           | ✅        | `"일시 보관금"` = 가수금 (은어)                  |

### 호출 조건

```python
# 구조화 패턴 미매칭 + 위험 신호 보유 건만 LLM 호출
if not matches_known_pattern(header_text) and has_other_risk_signals(entry):
    risk_assessment = llm_analyze_text(header_text, gl_account, amount, business_process)
```

- `matches_known_pattern()`: P2P/O2C/IC/H2R/TRE/A2R 정형 패턴 정규식 매칭
- `has_other_risk_signals()`: 고액(B02/B03), 심야(C03), 수기(B08) 등 다른 룰에서 플래그된 건
- **예상 LLM 호출 건수**: 전체의 ~2~5% (구조화 패턴 미매칭 + 위험 플래그 보유)

### 구현 위치

`insight_generator.py`의 `generate_entry_insight()`에 C06 LLM 분류 로직을 통합하거나,
별도 `risk_classifier.py` 모듈로 분리.

---

## 미해결 이슈 (Phase 3에서 해결 — 발견 위치 교차 참조)

Phase 1a ingest/feature에서 발견되었으나 LLM이 필요하여 Phase 3으로 이관된 항목.

### LLM 시맨틱 매핑

- **현상**: Fuzzy 문자열 유사도만으로 의미 파악 불가
- **해결 방향**: Ollama + Qwen3-8B 컬럼명 의미 추론
- **DataSynth 참고**: 39개 컬럼은 고정 → 실제 ERP 다양한 컬럼명에 적용
- **발견 위치**: [02-ingest §미해결](02-ingest.md#미해결-이슈-발견--해결-교차-참조)

### 은어/동의어 의미 유사도 매칭

- **현상**: pattern + text에서 정확 키워드만 반응
- **해결 방향**: NLP 임베딩 기반 유사도 매칭
- **DataSynth 참고**: 영문 구조화 적요에서는 필요성 낮음. 한국어 ERP 적용 시 활성화
- **발견 위치**: [03-feature §G](03-feature.md#g-미해결-이슈-발견--해결-교차-참조)

### semantic_similarity 구현

- **현상**: text_features에서 no-op stub
- **해결 방향**: Ollama 임베딩 API → 코사인 유사도
- **DataSynth 참고**: header_text 임베딩 → 프로세스별 클러스터링 → 이탈 건 탐지
- **발견 위치**: [03-feature §B](03-feature.md#b-새-피처-추가--phase-2-add_semantic_similarity)

### semantic_anomaly 구현

- **현상**: text_features에서 no-op stub
- **해결 방향**: 임베딩 공간 이상치 탐지
- **DataSynth 참고**: header_text 임베딩에 Isolation Forest 적용 → 비정형 적요 탐지
- **발견 위치**: [03-feature §C](03-feature.md#c-새-피처-추가--phase-3-add_semantic_anomaly)

현재 타입 호환성 검증(B1)과 매핑 프로파일(Phase 1c)로 대부분 커버되므로, Phase 3에서 추가 정확도가 필요한 경우에만 구현.

---

## Phase 3 확장 — LLM 고도화 기능

### XAI Narrative Report (전표 위험 사유서 자동 생성)

`insight_generator.py`의 `generate_entry_insight()`를 확장하여,
파생변수 조합을 LLM이 해석한 **자연어 위험 사유서(Narrative Report)**를 자동 생성한다.

**목적**: 감사인이 "이 전표가 왜 위험한가"를 즉시 파악할 수 있는 설명 제공

```
입력: 개별 전표의 파생변수 + DataSynth 레이블
  - 파생변수 18종: is_weekend, is_after_hours, is_period_end, days_backdated,
    fiscal_period_mismatch, is_holiday, is_near_threshold, exceeds_threshold,
    amount_zscore, amount_magnitude, is_round_number, is_manual_je,
    is_intercompany, is_revenue_account, first_digit, is_suspense_account,
    description_quality, has_risk_keyword
  - 탐지결과: anomaly_score, risk_level, flagged_rules
  - DataSynth 레이블: fraud_type, anomaly_type, sod_conflict_type

출력: 자연어 위험 사유서 (1~3문장)
  예: "이 전표(fraud_type: SplitTransaction)는 동일 거래처 V-000042에 대해
      동일 일자에 4,900만원 × 3건으로 분할 기표되었습니다(B02).
      합산 금액 14,700만원은 Level 3(10억) 미달이나, 개별 건이 Level 2(1억)
      직하에 집중되어 한도 회피가 의심됩니다."

구현 방향:
  1. 플래그 조합 패턴을 프롬프트 컨텍스트로 전달
  2. LLM이 감사 관점에서 위험 요소 간 상관관계를 해석
  3. 룰 ID(B02, C03 등)를 사유서에 인용 → 감사조서 추적성 확보

호출 조건:
  - anomaly_score > 0 AND risk_level IN ('HIGH', 'CRITICAL')인 전표만 대상
  - 예상 대상: 부정 2,008건 + 이상징후 7,959건 중 HIGH 이상 = ~3,000~5,000건
  - 배치 처리: 50건 단위로 LLM 호출
```

### Audit Rules 피드백 루프 (룰 세팅 자동 제안)

LLM이 새 데이터셋의 프로파일을 샘플링 분석하여,
`audit_rules.yaml`에 추가할 신규 룰/파라미터를 **자동 제안**한다.

**목적**: Data Flywheel([03-feature.md §D](03-feature.md)) 입구를 LLM으로 자동화하는 Assistant 기능

```
작동 흐름:
  1. 새 데이터 업로드 시, LLM이 무작위 N건(~200건) 샘플링
  2. 적요·계정·금액 패턴 분석 → 고객사 고유 패턴 발견
  3. 사용자에게 제안 형태로 표시:
     예: "이 고객사는 header_text에 'M_XXX' 패턴을 수기 전표 코드로 사용합니다.
          audit_rules.yaml에 manual_source_codes로 추가할까요?"
  4. 사용자 승인 시 → yaml 자동 업데이트

제안 카테고리:
  - manual_source_codes: 수기 전표 식별 소스 (현재: Manual, Adjustment)
  - suspense_keywords: 고객사 고유 가계정 키워드 (한글/영문)
  - suspense_account_codes: 가계정 GL 코드
  - revenue_account_prefixes: 매출 계정 접두사
  - intercompany_identifiers: IC 계정 식별 코드

안전장치:
  - LLM 제안은 항상 사용자 승인 필요 (자동 반영 금지)
  - 제안 근거(샘플 전표 3~5건)를 함께 표시 → 판단 투명성
  - 기존 룰과 충돌 시 경고 표시
```

---

## 구현 시 주의사항

- **Vanna train:** DDL, 도메인 용어, 샘플 Q&A를 학습시켜야 정확도 향상. 스키마 변경·audit_rules.yaml 변경·프리셋 Q&A 추가 시 ChromaDB 재학습 필요.
- **SQL 안전성:** LLM이 생성한 SQL은 반드시 `sql_validator`를 거쳐야 함 (DML 차단 필수)
- **Ollama 의존성:** LLM 없이도 앱이 동작해야 함 → Ollama 미실행 시 graceful degradation
- **ChromaDB 경로:** `data/chromadb/`에 저장, `.gitignore` 대상
- **스트리밍:** Chat UI는 `stream_chat()`으로 토큰 단위 출력 (UX 향상)
- **temperature:** 감사 분석은 정확성 우선 → 0.1 이하 권장
- **텍스트 필드 null 처리:** line_text null 비율 82% → `COALESCE(line_text, header_text, '')` 패턴 사용
- **영문 적요 프롬프트:** LLM 시스템 프롬프트에 "입력 텍스트는 영문 SAP 적요 형식, 응답은 한국어" 명시
- **법인별 컨텍스트:** C001(본사 ~6만건) vs C002/C003(지사 ~2만건)의 규모 차이를 인사이트에 반영

---

> Phase 1a 테스트에서 이관된 과제는 상단 [미해결 이슈](#미해결-이슈-phase-3에서-해결--발견-위치-교차-참조) 섹션에 통합하였다.

---

## 감사기준서 갭 분석 반영 (audit_domain_additional.md 기반)

### 경제적 실질 판단 (NLP)

- **근거**: 감사기준서 315호, 240호
- **입력**: `header_text`(1순위), `line_text`(P2P/IC만), `gl_account`, `auxiliary_account_number`
- **로직**: 적요 텍스트에서 거래 성격을 NLP로 추론하고, 계정 분류와 불일치 시 플래그
  - 예: header_text `"Bank Transfer"` + gl_account `6100`(급여) → 자금 이체가 급여 계정에 전기 → 실질 불일치 의심
  - 예: line_text `"IC Management Fee Expense from C001"` + 비정상 금액 → 이전가격 이상
- **한국 ERP 적용 시**: kiwipiepy 형태소 분석으로 한국어 적요 처리 활성화. DataSynth 영문 적요에서는 정규식 + LLM 조합으로 처리.

### 유의적 거래 합리성 평가 (LLM)

- **근거**: 감사기준서 240호 §32(c)
- **입력**: C08(이상고액) + B01(매출이상) 탐지 결과에서 플래그된 전표의 적요+계정+금액
- **로직**: LLM이 탐지된 이상 전표를 분석하여 "사업상 합리성" 보조 의견 제공
  - 프롬프트 예시:
    ```
    "이 전표를 분석하세요:
     company_code: C001, gl_account: 4100(용역매출), debit_amount: 85,000,000
     header_text: 'Revenue Adjustment - Year End'
     business_process: O2C, source: Adjustment, created_by: SA-005(senior_accountant)
     플래그: C08(이상고액) + B01(매출이상변동)
     이 전표의 사업상 합리성을 감사 관점에서 평가하세요."
    ```
- **주의**: LLM 의견은 보조 참고용. 최종 판단은 감사인
