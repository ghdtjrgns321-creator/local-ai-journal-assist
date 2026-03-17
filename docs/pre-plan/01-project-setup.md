# 01. 프로젝트 초기화 및 설정 레이어

## 목적
프로젝트 뼈대(패키지 관리, 설정 시스템, YAML 외부 설정)를 구축하여 이후 모든 모듈이 일관된 설정을 참조할 수 있도록 한다.

## 관련 파일
```
local-ai-assist/
├── pyproject.toml            # uv 패키지 관리 + dependency-groups
├── uv.lock                   # 자동 생성 lock 파일
├── .env.example              # 환경변수 템플릿
├── .gitignore                # data/, .env, __pycache__ 등 제외
└── config/
    ├── settings.py           # Pydantic Settings (환경변수 + 기본값)
    ├── schema.yaml           # 표준 컬럼 스키마 (⚠️ 예시 — 실제 전표 확인 후 확정)
    ├── keywords.yaml         # ERP별 헤더 키워드 사전 (⚠️ 예시 — 실제 ERP 확인 후 추가)
    └── risk_keywords.yaml    # 감사 위험 적요 키워드 사전 (⚠️ 예시 — 감사 매뉴얼 참고 후 보강)
```

## 핵심 클래스/함수

### `config/settings.py`
```python
class AuditSettings(BaseSettings):
    """프로젝트 전역 설정. 환경변수 > .env > YAML 기본값 순 우선."""

    # 파일 관련 (⚠️ 예시값 — 실제 전표 파일 크기·형식에 따라 조정 필요)
    max_file_size_mb: int = 100
    allowed_extensions: list[str] = [".xlsx", ".xls", ".csv"]

    # 매핑 관련 (⚠️ 예시값 — 실제 ERP 헤더 매칭 정확도를 보며 튜닝 필요)
    fuzzy_threshold: int = 80          # rapidfuzz 매칭 임계값

    # 감사 룰 관련 (⚠️ 예시값 — 실제 감사 기준에 맞춰 조정 필요)
    approval_threshold: float = 50_000_000  # R001: 승인 한도 (5천만원)
    near_threshold_ratio: float = 0.98      # 한도의 98% 이상이면 플래그
    midnight_start: int = 22                # R003: 심야 시작 시간
    midnight_end: int = 6                   # R003: 심야 종료 시간
    period_end_days: int = 5                # R004: 기말 n일

    # DB 관련
    duckdb_path: str = "data/audit.duckdb"

    # LLM 관련 (Phase 3)
    ollama_model: str = "qwen3:8b"
    ollama_base_url: str = "http://localhost:11434"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AUDIT_",
        yaml_file="config/settings.yaml",  # 선택적 YAML 오버라이드
    )
```

### `config/schema.yaml` — 표준 컬럼 스키마
```yaml
# ⚠️ 예시 스키마 — 실제 전표 데이터를 확인한 뒤 컬럼 구성·타입·필수 여부를 재정의할 것
columns:
  - name: journal_id        # 전표번호
    type: str
    required: true
  - name: entry_date        # 전표일자
    type: datetime
    required: true
  - name: account_code      # 계정코드
    type: str
    required: true
  - name: account_name      # 계정과목명
    type: str
    required: true
  - name: debit_amount      # 차변금액
    type: float
    required: true
  - name: credit_amount     # 대변금액
    type: float
    required: true
  - name: description       # 적요
    type: str
    required: false
  - name: department        # 부서
    type: str
    required: false
  - name: created_by        # 작성자
    type: str
    required: false
  - name: source_type       # 전표유형 (자동/수동)
    type: str
    required: false
  - name: counterparty      # 거래처
    type: str
    required: false
```

### `config/keywords.yaml` — ERP별 헤더 키워드
```yaml
# ⚠️ 예시 키워드 — 실제 ERP(더존, SAP, Oracle 등) 엑셀 헤더를 확인하며 추가할 것
# key: 표준 컬럼명, values: ERP별 다양한 표현
journal_id: ["전표번호", "전표No", "voucher_no", "JE Number", "Doc No"]
entry_date: ["전표일자", "기표일", "posting_date", "Entry Date", "일자"]
account_code: ["계정코드", "계정CD", "account_cd", "GL Code"]
debit_amount: ["차변금액", "차변", "debit", "Debit Amount", "Dr"]
credit_amount: ["대변금액", "대변", "credit", "Credit Amount", "Cr"]
description: ["적요", "설명", "description", "Memo", "비고"]
# ... 기타 컬럼
```

### `config/risk_keywords.yaml` — 위험 적요 키워드
```yaml
# ⚠️ 예시 키워드 — 실제 감사 매뉴얼·과거 감사조서를 참고하여 보강할 것
# R007: has_risk_keyword 판정에 사용
high_risk:
  - "상품권"
  - "가계정"
  - "가수금"
  - "가지급"
  - "대여금"
  - "선급금"
medium_risk:
  - "잡손실"
  - "잡이익"
  - "기타"
  - "임시"
```

## 데이터 흐름
```
.env / 환경변수
       ↓
AuditSettings(BaseSettings) ← schema.yaml, keywords.yaml, risk_keywords.yaml
       ↓
모든 모듈에서 settings 인스턴스 참조
```

## 구현 순서
1. `pyproject.toml` 작성 (dependency-groups 포함)
2. `uv sync --group core --group dashboard --group dev`
3. `.gitignore`, `.env.example` 생성
4. `config/settings.py` — `AuditSettings` 클래스 구현
5. `config/schema.yaml` — 표준 컬럼 정의 (⚠️ 실제 전표 데이터 확인 후 확정)
6. `config/keywords.yaml` — ERP별 헤더 키워드 (⚠️ 실제 ERP 엑셀 확인 후 추가)
7. `config/risk_keywords.yaml` — 위험 적요 키워드 (⚠️ 감사 매뉴얼 참고 후 보강)

## 의존성
- **외부 패키지:** `pydantic-settings`, `pyyaml`
- **하위 의존:** 모든 모듈이 이 설정에 의존 → **가장 먼저 구현**

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

## 테스트 전략
- `settings.py` 단위 테스트: 환경변수 오버라이드 동작, YAML 로드, 기본값 확인
- YAML 파일 스키마 유효성 검증 (필수 키 존재 여부)

## Phase 구분
| 항목 | Phase |
|------|-------|
| pyproject.toml, .gitignore | MVP (Phase 1a) |
| settings.py, YAML 설정 | MVP (Phase 1a) |
| LLM 관련 설정 필드 | Phase 3에서 활성화 |

## 구현 시 주의사항
- `.env`에는 시크릿만 넣고, 일반 설정은 YAML 사용
- `AuditSettings`는 **싱글톤 패턴**으로 앱 전체에서 하나만 생성
- YAML 파일 경로는 상대경로 → 프로젝트 루트 기준
- `risk_keywords.yaml`은 사용자가 커스터마이징 가능하도록 외부 파일 유지
- `.env.example`에는 실제 값 대신 플레이스홀더만 기입
