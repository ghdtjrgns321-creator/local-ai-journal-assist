# 08. LLM 연동 (Ollama + Vanna AI) [Phase 3 — 의존: 06, 07]

## 목적
로컬 LLM(Ollama + Qwen3-8B)과 Vanna AI 2.0을 활용하여
자연어 질의 → SQL 생성 → 결과 해석까지 자동화한다.

## 관련 파일
```
src/llm/
├── __init__.py                # 퍼블릭 API (lazy import)
├── ollama_client.py           # ✅ Ollama API 래퍼 (format=JSON Schema 지원)
├── models.py                  # ✅ Pydantic 응답 스키마 (StrEnum + ModelGroupStrategy)
├── prompt_templates.py        # ✅ EDAProfile → 프롬프트 변환 (heuristic_* 참조)
├── preprocessing_advisor.py   # ✅ LLM 전처리 제안 오케스트레이터
├── text_to_sql.py             # ⬜ 하이브리드 Text-to-SQL (Vanna + 템플릿 폴백)
├── sql_validator.py           # ⬜ 생성 SQL 검증
├── prompt_presets.py          # ⬜ 감사 프롬프트 프리셋 6종
└── insight_generator.py       # ⬜ 결과 해석 자연어 생성
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

## 미해결 이슈 (Phase 3에서 해결 — 발견 위치 교차 참조)

Phase 1a ingest/feature에서 발견되었으나 LLM이 필요하여 Phase 3으로 이관된 항목.

| 과제                         | 현상                                          | 해결 방향                                      | 발견 위치                                                    |
|:-----------------------------|:----------------------------------------------|:-----------------------------------------------|:-------------------------------------------------------------|
| LLM 시맨틱 매핑              | Fuzzy 문자열 유사도만으로 의미 파악 불가       | Ollama + Qwen3-8B 컬럼명 의미 추론             | [02-ingest §미해결](02-ingest.md#미해결-이슈-발견--해결-교차-참조) |
| 은어/동의어 의미 유사도 매칭 | pattern + text에서 정확 키워드만 반응          | NLP 임베딩 기반 유사도 매칭                    | [03-feature §G](03-feature.md#g-미해결-이슈-발견--해결-교차-참조) |
| semantic_similarity 구현     | text_features에서 no-op stub                  | Ollama 임베딩 API → 코사인 유사도              | [03-feature §B](03-feature.md#b-새-피처-추가--phase-2-add_semantic_similarity) |
| semantic_anomaly 구현        | text_features에서 no-op stub                  | 임베딩 공간 이상치 탐지                        | [03-feature §C](03-feature.md#c-새-피처-추가--phase-3-add_semantic_anomaly) |

현재 타입 호환성 검증(B1)과 매핑 프로파일(Phase 1c)로 대부분 커버되므로, Phase 3에서 추가 정확도가 필요한 경우에만 구현.

---

## Phase 3 확장 — LLM 고도화 기능

### XAI Narrative Report (전표 위험 사유서 자동 생성)

`insight_generator.py`의 `generate_entry_insight()`를 확장하여,
파생변수 조합을 LLM이 해석한 **자연어 위험 사유서(Narrative Report)**를 자동 생성한다.

**목적**: 감사인이 "이 전표가 왜 위험한가"를 즉시 파악할 수 있는 설명 제공

```
입력: 개별 전표의 파생변수 프로파일
  - is_weekend, is_night, is_near_threshold, is_manual_je, is_round_number,
    description_quality, amount_zscore, is_period_end 등

출력: 자연어 위험 사유서 (1~3문장)
  예: "이 전표는 토요일 23시에 수기로 입력되었으며(B08+C03),
      금액 4,950만원은 승인한도(5,000만원)의 99%에 해당합니다(B02).
      적요 '잡손실'은 정보량이 부족하여 거래 실질 파악이 어렵습니다(C06)."

구현 방향:
  1. 플래그 조합 패턴을 프롬프트 컨텍스트로 전달
  2. LLM이 감사 관점에서 위험 요소 간 상관관계를 해석
  3. 룰 ID(B02, C03 등)를 사유서에 인용 → 감사조서 추적성 확보

호출 조건:
  - risk_score ≥ 임계값인 전표만 대상 (전체 대비 ~3~5%)
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
     "이 고객사는 'M_XXX' 패턴을 수기 전표 코드로 사용합니다.
      audit_rules.yaml에 manual_je_prefixes로 추가할까요?"
  4. 사용자 승인 시 → yaml 자동 업데이트

제안 카테고리:
  - manual_je_prefixes: 수기 전표 식별 접두사
  - risk_keywords: 고객사 고유 위험 적요 키워드
  - suspense_patterns: 가계정/임시계정 패턴
  - threshold_amounts: 승인 한도 금액 (고객사별 상이)

안전장치:
  - LLM 제안은 항상 사용자 승인 필요 (자동 반영 금지)
  - 제안 근거(샘플 전표 3~5건)를 함께 표시 → 판단 투명성
  - 기존 룰과 충돌 시 경고 표시
```

---

## 구현 시 주의사항
- **Vanna train:** DDL, 프리셋 쿼리, 도메인 용어를 학습시켜야 정확도 향상
- **SQL 안전성:** LLM이 생성한 SQL은 반드시 `sql_validator`를 거쳐야 함 (DML 차단 필수)
- **Ollama 의존성:** LLM 없이도 앱이 동작해야 함 → Ollama 미실행 시 graceful degradation
- **ChromaDB 경로:** `data/chromadb/`에 저장, `.gitignore` 대상
- **스트리밍:** Chat UI는 `stream_chat()`으로 토큰 단위 출력 (UX 향상)
- **temperature:** 감사 분석은 정확성 우선 → 0.1 이하 권장

---

> Phase 1a 테스트에서 이관된 과제는 상단 [미해결 이슈](#미해결-이슈-phase-3에서-해결--발견-위치-교차-참조) 테이블에 통합되었습니다.
