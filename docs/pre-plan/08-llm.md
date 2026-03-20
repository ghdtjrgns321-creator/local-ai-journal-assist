# 08. LLM 연동 (Ollama + Vanna AI)

## 목적
로컬 LLM(Ollama + Qwen3-8B)과 Vanna AI 2.0을 활용하여
자연어 질의 → SQL 생성 → 결과 해석까지 자동화한다.

## 관련 파일
```
src/llm/
├── ollama_client.py       # Ollama API 클라이언트
├── text_to_sql.py         # 하이브리드 Text-to-SQL (Vanna + 템플릿 폴백)
├── sql_validator.py       # 생성 SQL 검증
├── prompt_presets.py      # 감사 프롬프트 프리셋 6종
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
        """DDL + 문서 + 샘플 Q&A로 Vanna 학습.
        - schema.py DDL 학습
        - 프리셋 쿼리 학습
        - 감사 도메인 용어 학습
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

### `prompt_presets.py` — 감사 프리셋 6종
```python
AUDIT_PRESETS = {
    "high_risk_overview": {
        "label": "고위험 전표 현황",
        "question": "위험도가 높은 전표의 총 건수와 금액은?",
    },
    "weekend_midnight": {
        "label": "비업무시간 전표",
        "question": "주말이나 심야에 처리된 전표를 보여줘",
    },
    "period_end_large": {
        "label": "기말 대규모 거래",
        "question": "월말 5일 이내에 5천만원 이상인 전표는?",
    },
    "reversal_pairs": {
        "label": "역분개 쌍",
        "question": "동일 계정, 동일 금액의 역분개 전표 쌍을 찾아줘",
    },
    "top_accounts": {
        "label": "이상 집중 계정",
        "question": "이상 전표가 가장 많이 집중된 계정과목 상위 10개는?",
    },
    "benford_deviation": {
        "label": "Benford 편차",
        "question": "Benford 법칙에서 가장 크게 벗어난 숫자는?",
    },
}
```

### `insight_generator.py` — 자연어 인사이트
```python
class InsightGenerator:
    """분석 결과를 감사인이 이해할 수 있는 자연어로 변환.

    LLM에게 분석 데이터를 전달하고, 감사 관점의 해석을 생성.
    """

    def generate_summary_insight(self, pipeline_result) -> str:
        """전체 분석 결과 요약 인사이트 생성.
        예: '총 10,000건 중 382건(3.8%)이 이상 전표로 탐지되었으며,
            특히 B02(승인한도 직하) 위반이 45%로 가장 높은 비중을 차지합니다.'
        """

    def generate_entry_insight(self, entry: dict) -> str:
        """개별 전표에 대한 상세 인사이트.
        예: '이 전표는 주말(토요일) 23시에 수기로 입력되었으며,
            금액 4,950만원은 승인한도(5,000만원)의 99%에 해당합니다.'
        """

    def generate_benford_insight(self, benford_result: dict) -> str:
        """Benford 분석 결과 해석."""
```

## 데이터 흐름
```
[사용자 자연어 질문] (Tab 4 Chat UI)
       ↓
text_to_sql.ask(question)
       ↓
  ┌── Vanna AI 2.0 ──┐
  │ DDL train 완료     │
  │ question → SQL    │
  │ SQL → 실행        │
  │ 결과 → Plotly     │
  └────────┬──────────┘
           │ (실패 시)
  ┌── 템플릿 폴백 ────┐
  │ 키워드 → 프리셋SQL │
  └────────┬──────────┘
           ↓
sql_validator.validate_sql(sql)
           ↓
[실행 결과 DataFrame + Plotly Figure]
           ↓
insight_generator → 자연어 해석
           ↓
[Chat UI에 SQL + 결과 + 차트 + 인사이트 표시]
```

## 구현 순서
1. `ollama_client.py` — Ollama 연결 + 모델 확인
2. `sql_validator.py` — SQL 안전성 검증 (LLM 독립적)
3. `prompt_presets.py` — 6종 프리셋 정의
4. `text_to_sql.py` — Vanna 초기화 + train + ask + 폴백
5. `insight_generator.py` — 자연어 인사이트 생성

## 의존성
- **선행:** `06-db` (DuckDB 스키마, 데이터), `01-project-setup` (Ollama 설정)
- **외부 패키지:** `vanna[duckdb,ollama,chromadb]`, `ollama`
- **후행:** `07-dashboard/tab_chat.py` (Chat UI), `09-export` (인사이트 포함 내보내기)

## 테스트 전략
- **ollama_client:** 서버 가용성 확인, mock 응답 테스트
- **sql_validator:** DML 차단 확인, 정상 SELECT 통과 확인
- **text_to_sql:** 프리셋 질문 6종에 대해 유효 SQL 생성 확인
- **insight_generator:** 결과 dict 입력 → 비어있지 않은 문자열 반환 확인
- **E2E:** "12월 매출 5천만 이상 이상거래" → SQL → DataFrame → 인사이트

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

## C06 위험 적요 LLM 보완 (Phase 3 확장)

Phase 1에서는 `risk_keywords.yaml` 딕셔너리 exact/partial match로 C06을 탐지한다.
Phase 3에서 LLM을 **보완 레이어**로 추가하여 딕셔너리가 놓치는 케이스를 잡는다.

### 딕셔너리 한계 → LLM이 보완하는 케이스
- 동의어: "기프트카드" (상품권), "일시 보관금" (가수금)
- 우회 표현: "임직원 선물비", "경조사 지원"
- 영문 혼재: "gift card", "suspense clearing"

### 설계 원칙
1. **106만건 전체에 LLM 호출하지 않음** — 비현실적 (비용·시간)
2. 딕셔너리 미매칭 + **다른 위험 징후가 있는 건만** LLM에 전달
3. Phase 1 딕셔너리 결과가 **baseline(비교 기준)** 역할

### 호출 조건 (AND)
```python
# 딕셔너리 미매칭이면서, 다른 위험 신호가 있는 건만 LLM 분류
if not C06_flag and has_other_risk_signals(entry):
    C06_llm = llm_classify_risk(line_text)
```

`has_other_risk_signals` 예시: 고액(B02/B03), 심야(C03), 수기(B08) 등 다른 룰에서 이미 플래그된 건.

### 구현 위치
`insight_generator.py`의 `generate_entry_insight()`에 C06 LLM 분류 로직을 통합하거나,
별도 `risk_classifier.py` 모듈로 분리.

## Phase 1a에서 넘어온 미해결 과제 (UX 1단계 잔여)

Phase 1a ingest 개선(D016) 시 발견되었으나 LLM이 필요하여 Phase 3으로 이관된 항목.

| 과제              | 현상                                            | 해결 방향                                    |
|:------------------|:------------------------------------------------|:---------------------------------------------|
| LLM 시맨틱 매핑   | Fuzzy 문자열 유사도만으로는 의미 파악 불가       | Ollama + Qwen3-8B로 컬럼명 의미 추론 후 매핑 |

현재 타입 호환성 검증(B1)과 매핑 프로파일(Phase 1c)로 대부분 커버되므로, Phase 3에서 추가 정확도가 필요한 경우에만 구현.

> 상세: [02-ingest.md → UX 1단계](02-ingest.md#ux-1단계-데이터-수집-투명성-phase-1a-구현-완료)

---

## 구현 시 주의사항
- **Vanna train:** DDL, 프리셋 쿼리, 도메인 용어를 학습시켜야 정확도 향상
- **SQL 안전성:** LLM이 생성한 SQL은 반드시 `sql_validator`를 거쳐야 함 (DML 차단 필수)
- **Ollama 의존성:** LLM 없이도 앱이 동작해야 함 → Ollama 미실행 시 graceful degradation
- **ChromaDB 경로:** `data/chromadb/`에 저장, `.gitignore` 대상
- **스트리밍:** Chat UI는 `stream_chat()`으로 토큰 단위 출력 (UX 향상)
- **temperature:** 감사 분석은 정확성 우선 → 0.1 이하 권장
