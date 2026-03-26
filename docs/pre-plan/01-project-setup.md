# 01. 프로젝트 초기화 및 설정 레이어 [Phase 0 — 사전 준비]

## 목적
프로젝트 뼈대(패키지 관리, 설정 시스템, YAML 외부 설정)를 구축하여 이후 모든 모듈이 일관된 설정을 참조할 수 있도록 한다.

## 무엇을 구현하는가

| 구현 대상               | 역할                                                    |
|------------------------|---------------------------------------------------------|
| `pyproject.toml`       | uv 패키지 관리 + dependency-groups로 Phase별 선택 설치    |
| `config/settings.py`   | Pydantic Settings 기반 전역 설정 (환경변수 > .env > YAML) |
| `config/schema.yaml`   | DataSynth 출력 기준 표준 컬럼 스키마 (39개 컬럼)           |
| `config/keywords.yaml` | ERP별 헤더 키워드 사전 (컬럼 자동 매핑용)                  |
| `config/risk_keywords.yaml` | 감사 위험 적요 키워드 사전 (C06 룰 판정용)            |
| `tools/datasynth/`     | EY-ASU DataSynth (Rust, 합성 전표 생성기)                |

## 왜 이렇게 설계했는가

### DataSynth 출력을 표준 스키마로 채택한 이유

32개 공개 데이터셋/도구를 검토한 결과, 대부분의 공개 데이터셋은
핵심 필드 누락(날짜 없음, 레이블 없음, 익명화)으로 프로젝트 요건을 충족하지 못했다.

DataSynth(EY Switzerland + ASU 공동 개발)를 선택한 이유:

1. **SAP ACDOCA 네이티브 구조**: 71개 필드를 정의한 `AcdocaEntry` 구조체가
   SAP S/4HANA Universal Journal과 동일한 필드명(`rbukrs`, `belnr`, `racct`, `budat`, `drcrk` 등)을 사용
2. **감사 기준 내장**: PCAOB, ISA, COSO 2013, SOX 302/404를 직접 구현.
   감사인이 정의한 fraud 시나리오가 코드 레벨에서 보장됨
3. **anomaly 유형 52개** (AUDIT_DOMAIN_FINAL.md §4 기준).
   → `is_fraud`, `is_anomaly` 컬럼으로 출력되어 지도학습에 바로 사용 가능
4. **복식부기 보장**: `JournalEntry`가 생성 시점에 차변 합 = 대변 합을 강제
5. **Benford 준수**: 금액 분포가 Benford's Law를 따르도록 생성
6. **재현성**: seed 고정(2024)으로 동일 데이터 재생성 가능

### 설정 시스템 설계 원칙

- `.env`에는 시크릿만 넣고, 일반 설정은 YAML 사용
- `AuditSettings`는 **싱글톤 패턴**으로 앱 전체에서 하나만 생성
- YAML 파일 경로는 상대경로 → 프로젝트 루트 기준
- `risk_keywords.yaml`은 사용자가 커스터마이징 가능하도록 외부 파일 유지
- `.env.example`에는 실제 값 대신 플레이스홀더만 기입
- DataSynth 재생성: `config/datasynth.yaml` + seed 변경으로 다른 데이터셋 생성 가능

## 데이터 흐름
```
DataSynth (tools/datasynth/)
  │  config/datasynth.yaml → seed 2024, 12개월, 3회사, fraud 2%
  ▼
data/journal/primary/datasynth/journal_entries.csv (1,106K rows)
  │
  ▼
.env / 환경변수
  │
  ▼
AuditSettings(BaseSettings) ← schema.yaml, keywords.yaml, risk_keywords.yaml
  │
  ▼
Ingest → Feature → Detection → DB → Dashboard
```

## 의존성

- **외부 패키지:** `pydantic-settings`, `pyyaml`
- **데이터 생성:** `tools/datasynth/` (Rust, 별도 빌드)
- **하위 의존:** 모든 모듈이 이 설정에 의존 → **가장 먼저 구현**

## 구현 순서
1. `pyproject.toml` 작성 (dependency-groups 포함)
2. `uv sync --group core --group dashboard --group dev`
3. `.gitignore`, `.env.example` 생성
4. `config/settings.py` — `AuditSettings` 클래스 구현
5. `config/schema.yaml` — DataSynth 출력 기준 스키마 확정
6. `config/keywords.yaml` — DataSynth + SAP + 더존 헤더 키워드
7. `config/risk_keywords.yaml` — DataSynth fraud type 참고 위험 키워드

## Phase 구분

| 항목                        | Phase              |
|-----------------------------|--------------------|
| pyproject.toml, .gitignore  | MVP (Phase 1a)     |
| settings.py, YAML 설정     | MVP (Phase 1a)     |
| DataSynth 빌드 + 데이터 생성| MVP (Phase 1a)     |
| LLM 관련 설정 필드          | Phase 3에서 활성화 |

## 테스트 전략
- `settings.py` 단위 테스트: 환경변수 오버라이드 동작, YAML 로드, 기본값 확인
- YAML 파일 스키마 유효성 검증 (필수 키 존재 여부)
- DataSynth 출력 CSV를 schema.yaml로 검증 (컬럼명·타입 일치)

## dependency-groups 설계
```toml
[dependency-groups]
core = ["pandas>=2.2", "openpyxl", "pandera", "rapidfuzz", "duckdb", "scipy", "numpy", "pyyaml", "pydantic-settings"]
ml = ["xgboost", "scikit-learn", "shap", "torch"]
nlp = ["kiwipiepy"]
llm = ["vanna[duckdb,ollama,chromadb]", "ollama"]
dashboard = ["streamlit", "plotly", "streamlit-aggrid"]
export = ["fpdf2"]
dev = ["pytest", "ruff", "mypy"]
```

**MVP 설치:** `uv sync --group core --group dashboard --group dev`

---

## 관련 파일
```
local-ai-assist/
├── pyproject.toml            # uv 패키지 관리 + dependency-groups
├── uv.lock                   # 자동 생성 lock 파일
├── .env.example              # 환경변수 템플릿
├── .gitignore                # data/, .env, __pycache__ 등 제외
├── config/
│   ├── settings.py           # Pydantic Settings (환경변수 + 기본값)
│   ├── datasynth.yaml        # DataSynth 생성 설정 (seed, 회사, fraud 비율)
│   ├── schema.yaml           # 표준 컬럼 스키마 (DataSynth 출력 기준)
│   ├── keywords.yaml         # ERP별 헤더 키워드 사전
│   └── risk_keywords.yaml    # 감사 위험 적요 키워드 사전
└── tools/
    └── datasynth/            # EY-ASU DataSynth (Rust, 합성 전표 생성기)
```

## 핵심 클래스/함수 레퍼런스

### `config/settings.py` — AuditSettings

> 현재 구현은 `config/settings.py` 참조. 아래는 초기 설계 스냅샷으로, 실제 코드에는
> 헤더 탐지, 타입 캐스팅, Detection Layer B/C, L3 통계 검증, 텍스트 피처 등 필드가 추가됨.

```python
class AuditSettings(BaseSettings):
    """프로젝트 전역 설정. 환경변수 > .env > 코드 기본값 순 우선."""

    # 파일 관련 (카테고리별 크기 제한은 src/ingest/file_categories.py에 정의)
    max_file_size_mb: int = 100
    allowed_extensions: list[str] = [".xlsx", ".xls", ".xlsb", ".csv", ".tsv", ".txt", ".dat", ".parquet"]

    # 매핑 관련
    fuzzy_threshold: int = 80              # rapidfuzz 매칭 임계값

    # 감사 룰 관련 — 한국 중견 제조업 전결규정 6단계 (DataSynth v1.2.0)
    approval_thresholds: list[int] = [
        10_000_000, 100_000_000, 1_000_000_000,
        5_000_000_000, 10_000_000_000, 50_000_000_000,
    ]
    near_threshold_ratio: float = 0.90     # 한도의 90% 이상이면 플래그

    # C03: 심야 전기 (AfterHoursPosting)
    midnight_start: int = 22               # 심야 시작
    midnight_end: int = 6                  # 심야 종료

    # C01: 기말 대규모 (RushedPeriodEnd)
    period_end_margin_days: int = 5        # 기말 판정 마진 (월말 전후 n일)

    # Benford
    benford_mad_threshold: float = 0.012   # MAD 부적합 기준

    # DB 관련
    duckdb_path: str = "data/audit.duckdb"

    # LLM 관련 (Phase 3)
    ollama_model: str = "qwen3:8b"
    ollama_base_url: str = "http://localhost:11434"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AUDIT_",
        extra="ignore",
    )
```

### `config/schema.yaml` — 표준 컬럼 스키마

DataSynth `journal_entries.csv` 출력 39개 컬럼 기준 (Header 24 + Line 15).
ACDOCA 필드명과의 매핑은 `docs/AUDIT_DOMAIN_FINAL.md` 참조.
현재 구현은 `config/schema.yaml` 참조.

```yaml
# DataSynth journal_entries.csv 출력 기준 (tools/datasynth/ v1.2.0)
# ACDOCA 매핑: crates/datasynth-core/src/models/acdoca.rs
# 컬럼 39개: Header 24 + Line 15
columns:
  # === Header fields — 전표 단위 (document_id별 동일) ===

  # --- 필수 (전표 식별 + 핵심 회계 정보) ---
  - name: document_id          # ACDOCA: belnr
    type: str
    required: true
  - name: company_code         # ACDOCA: rbukrs
    type: str
    required: true
  - name: fiscal_year          # ACDOCA: gjahr
    type: int
    required: true
  - name: fiscal_period        # ACDOCA: monat — 회계기간 (1~12)
    type: int
    required: true
  - name: posting_date         # ACDOCA: budat — 전기일시 (시분초 포함)
    type: datetime
    required: true
  - name: document_date        # ACDOCA: bldat — 증빙일
    type: date
    required: true
  - name: document_type        # ACDOCA: blart — SA/KR/KZ/DR/DZ/WE/AA/HR/IC
    type: str
    required: true
  - name: gl_account           # ACDOCA: racct
    type: str
    required: true
  - name: debit_amount         # ACDOCA: wsl (drcrk='S') — KRW 정수
    type: int
    required: true
  - name: credit_amount        # ACDOCA: wsl (drcrk='H') — KRW 정수
    type: int
    required: true

  # --- 권장 (감사 룰에 필요) ---
  - name: currency             # ACDOCA: rwcur — KRW 단일
    type: str
    required: false
  - name: exchange_rate        # 환율 (KRW 단일이므로 항상 1.0)
    type: float
    required: false
  - name: reference            # 참조번호 (PO/GR/Invoice 번호)
    type: str
    required: false
  - name: header_text          # ACDOCA: bktxt — 전표 헤더 적요
    type: str
    required: false
  - name: created_by           # ACDOCA: usnam — B06~B09(통제 위반) 판정용
    type: str
    required: false
  - name: user_persona         # automated_system/junior_accountant/senior_accountant/controller/manager
    type: str
    required: false
  - name: source               # Automated/Manual/Recurring/Adjustment — B08(수기전표) 판정용
    type: str
    required: false
  - name: business_process     # P2P/O2C/R2R/H2R/TRE/A2R
    type: str
    required: false
  - name: ledger               # 원장 (Leading Ledger: 0L)
    type: str
    required: false
  - name: approved_by          # 승인자 ID — B06(자기승인) 탐지용
    type: str
    required: false
  - name: approval_date        # 승인일
    type: date
    required: false

  # --- 레이블 (DataSynth 전용) ---
  - name: is_fraud             # 부정 전표 여부
    type: bool
    required: false
  - name: fraud_type           # 부정 유형 (nullable) — DuplicatePayment, SelfApproval 등
    type: str
    required: false
  - name: is_anomaly           # 이상징후 여부
    type: bool
    required: false
  - name: anomaly_type         # 이상징후 유형 (nullable) — NewCounterparty, CircularTransaction 등
    type: str
    required: false
  - name: sod_violation        # 직무분리 위반 여부 — B07 SoD 탐지용
    type: bool
    required: false
  - name: sod_conflict_type    # SoD 충돌 유형 (nullable) — preparer_approver 등
    type: str
    required: false

  # === Line fields — 라인아이템 단위 ===
  - name: line_number          # ACDOCA: docln — 라인 번호
    type: int
    required: false
  - name: local_amount         # ACDOCA: hsl — 현지 통화 금액
    type: int
    required: false
  - name: cost_center          # ACDOCA: rcntr (nullable)
    type: str
    required: false
  - name: profit_center        # ACDOCA: prctr
    type: str
    required: false
  - name: line_text            # ACDOCA: sgtxt — C06(위험 적요) 판정용
    type: str
    required: false
  - name: tax_code             # 세금코드 (nullable)
    type: str
    required: false
  - name: tax_amount           # 세금액 (nullable)
    type: float
    required: false
  - name: trading_partner      # 거래처 (IC 거래용, nullable) — B10 관계사 탐지용
    type: str
    required: false
  - name: auxiliary_account_number  # 보조원장 계정번호 (nullable)
    type: str
    required: false
  - name: auxiliary_account_label   # 보조원장 라벨 (nullable)
    type: str
    required: false
  - name: lettrage             # 대사 그룹 (nullable)
    type: str
    required: false
  - name: lettrage_date        # 대사일 (nullable)
    type: date
    required: false
```

### `config/keywords.yaml` — ERP별 헤더 키워드
```yaml
# DataSynth 컬럼명 + SAP/더존/Oracle 등 ERP별 다양한 표현
document_id:    ["전표번호", "전표No", "voucher_no", "JE Number", "Doc No", "document_id", "belnr"]
posting_date:   ["전표일자", "기표일", "posting_date", "Entry Date", "일자", "budat"]
gl_account:     ["계정코드", "계정CD", "account_cd", "GL Code", "gl_account", "racct", "hkont"]
debit_amount:   ["차변금액", "차변", "debit", "Debit Amount", "Dr", "debit_amount"]
credit_amount:  ["대변금액", "대변", "credit", "Credit Amount", "Cr", "credit_amount"]
line_text:      ["적요", "설명", "description", "Memo", "비고", "line_text", "sgtxt"]
created_by:     ["작성자", "입력자", "기표자", "user", "created_by", "usnam"]
source:         ["전표유형", "입력구분", "source_type", "source"]
company_code:   ["회사코드", "법인", "company", "company_code", "bukrs"]
```

### `config/risk_keywords.yaml` — 위험 적요 키워드
```yaml
# C06: 위험 적요 판정에 사용
# DataSynth ProcessIssueType::VagueDescription, FraudType::SuspenseAccountAbuse 참고
high_risk:
  - "상품권"
  - "가계정"
  - "가수금"         # DataSynth: suspense_account_abuse
  - "가지급"
  - "대여금"
  - "선급금"
  - "suspense"
  - "clearing"
medium_risk:
  - "잡손실"
  - "잡이익"
  - "기타"
  - "임시"
  - "adjustment"     # DataSynth: source='adjustment'
  - "manual"
```
