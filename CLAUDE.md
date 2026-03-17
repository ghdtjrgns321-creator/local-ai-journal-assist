# Local AI Audit Assistant v2.0

감사 실증절차 전표 테스트를 로컬 환경에서 자동화하는 Python 프로젝트.
PCAOB AS 2401, ISA 240 커버. MindBridge/KPMG Clara 핵심 로직을 오픈소스로 재현.

## Quick Reference

| 항목 | 값 |
|------|---|
| Python | 3.11+ |
| 패키지 관리 | uv + pyproject.toml (dependency-groups) |
| DB | DuckDB (OLAP) |
| 대시보드 | Streamlit + Plotly + AgGrid |
| LLM (Phase 3) | Ollama + Qwen3-8B (Q4_K_M) |
| 테스트 | pytest (`uv run pytest tests/ -v`) |
| 실행 | `uv run streamlit run dashboard/app.py` |

## Phase 로드맵

- **Phase 1 (MVP)**: Excel → 정제 → 룰탐지(R001~R008) → Benford → DuckDB → Streamlit 3탭
  - 1a: ingest + feature + validation
  - 1b: detection + db + pipeline
  - 1c: dashboard
- **Phase 2**: XGBoost+SHAP, VAE+IF 앙상블, 중복/분할 탐지
- **Phase 3**: Ollama LLM, Vanna Text-to-SQL, NLP, Export

## 문서 가이드

| 문서 | 경로 | 내용 |
|------|------|------|
| 프로젝트 개요 | [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | 기술 스택, 디렉토리 구조, 데이터 흐름도 |
| 설계 결정 로그 | [docs/DECISION.md](docs/DECISION.md) | 기술 선택 이유, 아키텍처 결정 |
| Phase별 태스크 | [docs/TASKS.md](docs/TASKS.md) | Phase 1a/1b/1c/2/3 상세 태스크 목록과 완료 기준 |
| 감사 도메인 | [docs/AUDIT_DOMAIN.md](docs/AUDIT_DOMAIN.md) | R001~R008 룰, Benford 판정 기준, 도메인 용어↔코드 변수명 |
| Git 브랜치 전략 | [docs/GIT.md](docs/GIT.md) | 브랜치 구조, 네이밍, 워크플로우, 태그 규칙 |
| 디버깅 기록 | [docs/debugging.md](docs/debugging.md) | 트러블슈팅 히스토리 |
| 원본 계획서 | [docs/pre-plan/개요서.md](docs/pre-plan/개요서.md) | 최초 프로젝트 계획서 전문 |
| 구현 가이드 | [docs/pre-plan/00~10-*.md](docs/pre-plan/) | 기능 영역별 상세 구현 레퍼런스 (11개 파일) |

> 작업 전 관련 docs를 먼저 읽고, 완료 후 변경사항 반영할 것.
> 구현 시 해당 영역의 `pre-plan/0X-*.md` 가이드를 참조할 것.

### ⚠️ 태스크 시작/종료 시 필수 체크리스트
1. **시작 시**: 올바른 브랜치에서 작업 중인지 확인 (`docs/GIT.md` 브랜치 전략 참고)
2. **종료 시**: `docs/TASKS.md` 완료 상태 업데이트 + `docs/debugging.md`에 트러블슈팅 기록 (있을 경우)
3. **종료 시**: 변경된 내용에 맞춰 관련 docs 문서 최신화

## 핵심 코딩 규칙

- **모듈**: 파일당 100줄 내외, SRP 준수
- **탐지 트랙 추가**: `BaseDetector(ABC)` 상속 → `detect() -> DetectionResult` 구현
- **DB 스키마**: `src/db/schema.py`에 DDL 정의, DuckDB
- **설정**: `config/settings.py` (Pydantic Settings) + YAML 외부 설정
- **데이터 검증**: Pandera 스키마 기반 (L1 구조 → L2 회계 → L3 통계)

## Skill 활용 맵

| Phase | 활용 Skill |
|-------|-----------|
| 1a (ingest/feature) | `data-analysis`, `python-code-quality`, `python-packaging`, `pytest-backend-testing` |
| 1b (detection/db) | `duckdb`, `data-analysis`, `pytest-backend-testing` |
| 1c (dashboard) | `developing-with-streamlit`, `python-code-quality` |
| Phase 2 (ML) | `data-analysis`, `python-code-quality`, `mermaid` (아키텍처 다이어그램) |
| Phase 3 (LLM) | `local-llm-ops`, `langgraph-rag-guidelines`, `pdf` |

## Agent 활용 가이드

| Agent | 용도 |
|-------|------|
| `planner` | 새 Phase/Sub-phase 시작 시 구현 계획 수립 |
| `Explore` | 코드베이스 탐색, 의존성 추적 |
| `code-reviewer` | 주요 모듈 구현 완료 후 코드 리뷰 |
| `error-resolver` | 빌드/런타임 에러 진단 |
| `Plan` | 아키텍처 설계, 리팩토링 전략 |

## dependency-groups

```
core = ["pandas>=2.2", "openpyxl", "pandera", "rapidfuzz", "duckdb", "scipy", "numpy", "pyyaml", "pydantic-settings"]
ml = ["xgboost", "scikit-learn", "shap", "torch"]
nlp = ["kiwipiepy"]
llm = ["vanna[duckdb,ollama,chromadb]", "ollama"]
dashboard = ["streamlit", "plotly", "streamlit-aggrid"]
export = ["fpdf2"]
dev = ["pytest", "ruff", "mypy"]
```

MVP 설치: `uv sync --group core --group dashboard --group dev`
