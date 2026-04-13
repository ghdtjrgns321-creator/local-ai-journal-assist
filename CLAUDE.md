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
| LLM (Phase 3) | OpenAI (gpt-5.4 / gpt-5.4-mini 2티어) |
| 테스트 | pytest (`uv run pytest tests/ -v`) |
| 실행 | `uv run streamlit run dashboard/app.py` |

## Phase 로드맵

- **RC (Restructure)**: Company-Centric 아키텍처 전면 재설계 — 41개 태스크
  - RC-0: Company 인프라 (CompanyContext + ContextFactory + CRUD)
  - RC-1: 파이프라인 Context 주입
  - RC-2: 싱글톤 직접 호출 제거
  - RC-3: DB 격리 (Engagement별 DuckDB) + ConnectionManager
  - RC-4: 대시보드 재설계 (회사 선택 → 분석 플로우)
  - RC-5: 매핑 프로파일 회사 연결 + 고급 기능
- **Phase 1 (MVP)** ✅ 1a/1b 완료, 1c는 RC-4에 통합
  - 1a: ingest + feature + validation + EDA ✅
  - 1b: detection (3레이어 24개 룰) + db + pipeline ✅
  - 1c: dashboard → RC-4에서 회사 선택 UI와 함께 구현
- **Phase 2**: ML/DL 전처리 + 탐지기 (회사별 모델 저장 구조 활용)
- **Phase 3**: OpenAI API(gpt-5.4 / gpt-5.4-mini 2티어), Text-to-SQL, NLP, Export

## 문서 가이드

- 관련있는 작업을 할 때 문서가이드를 참조하여 작업 후 업데이트 할 것

| 문서 | 경로 | 내용 |
|------|------|------|
| 프로젝트 개요 | [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | 기술 스택, 디렉토리 구조, 데이터 흐름도 |
| 설계 결정 로그 | [docs/DECISION.md](docs/DECISION.md) | 기술 선택 이유, 아키텍처 결정 |
| Phase별 태스크 | [docs/TASKS.md](docs/TASKS.md) | Phase 1a/1b/1c/2/3 상세 태스크 목록과 완료 기준 |
| RC 재설계 태스크 | [docs/NEW_TASKS.MD](docs/NEW_TASKS.MD) | Company-Centric 재설계 RC-0~5 태스크 (41개) |
| 탐지 룰 목록 | [docs/DETECTION_RULES.md](docs/DETECTION_RULES.md) | 전체 탐지 룰 목록 (Phase 1~3), 점수 체계, DataSynth 갭 현황, 컬럼 스키마 |
| 탐지 레퍼런스 | [docs/DETECTION_REFERENCE.md](docs/DETECTION_REFERENCE.md) | 법규 체계, 감사기준서 매핑, 금감원 189건 실증, 한국 실무 지식 |
| Git | [docs/GIT.md](docs/GIT.md) | 브랜치 구조, 네이밍, 워크플로우, 태그 규칙 |
| 디버깅 기록 | [docs/debugging.md](docs/debugging.md) | 트러블슈팅 히스토리 |
| DataSynth 품질 | [docs/datasynth.md](docs/datasynth.md) | 품질 게이트, 해결/미해결 이슈, 수정 수칙, 핵심 파일 경로 |
| 원본 계획서 | [docs/pre-plan/개요서.md](docs/pre-plan/개요서.md) | 최초 프로젝트 계획서 전문 |
| 전처리 전략 | [docs/pre-plan/03a-preprocessing.md](docs/pre-plan/03a-preprocessing.md) | EDA 프로파일링, ML Pipeline 전처리, LLM 제안 전략 |
| ML 탐지 설계 | [docs/pre-plan/05a-detection-ml.md](docs/pre-plan/05a-detection-ml.md) | Phase 2b ML 탐지기 설계 (VAE/XGBoost/평가지표/테스트) |
| 구현 가이드 | [docs/pre-plan/00~10-*.md](docs/pre-plan/) | 기능 영역별 상세 구현 레퍼런스 (13개 파일) |

> 작업 전 관련 docs를 먼저 읽고, 완료 후 변경사항 반영할 것.
> 구현 시 해당 영역의 `pre-plan/0X-*.md` 가이드를 참조할 것.

### ⚠️ 태스크 시작/종료 시 필수 체크리스트
1. **시작 시**: 올바른 브랜치에서 작업 중인지 확인 (`docs/GIT.md` 브랜치 전략 참고)
2. **종료 시**: `docs/NEW_TASKS.MD` (RC 태스크) 또는 `docs/TASKS.md` 완료 상태 업데이트 + `docs/debugging.md`에 트러블슈팅 기록 (있을 경우)
3. **종료 시**: 변경된 내용에 맞춰 관련 docs 문서 최신화

## 핵심 코딩 규칙

- **모듈**: 파일당 100줄 내외, SRP 준수
- **탐지 트랙 추가**: `BaseDetector(ABC)` 상속 → `detect() -> DetectionResult` 구현
- **DB**: Engagement별 격리 DuckDB (`data/companies/{id}/engagements/{year}/audit.duckdb`)
- **설정**: `CompanyContext` (3계층 해소) → 글로벌 폴백: `config/settings.py` (Pydantic Settings) + YAML
- **데이터 검증**: Pandera 스키마 기반 (L1 구조 → L2 회계 → L3 통계)
- **디버깅**: `systematic-debugging` 스킬의 4단계 프레임워크를 따른다

## DATASYNTH 생성 규칙

- 테스트에 데이터를 끼워 맞추지(fitting) 말고, 데이터 자체를 올바르게 생성하라.
- **정상 데이터**: 회계적으로 정상 (차대변 균형, 양수 금액, 기간 범위 내) + 자연적 노이즈 (MCAR 결측, 오타, 서식 변동)
- **비정상 데이터**: 의도적 이상 패턴 (fraud, error, process issue) + 라벨로 완전 추적
- **데이터 품질 (MCAR, typo, format)**: 정상/비정상 무관하게 **동일 비율** 적용. ML 지름길 학습·일반화 실패·허위 피처 중요도·합성 아티팩트 방지.
- RUST 로 근본부터 제대로 수정, PYTHON으로 덧대기 금지
- datasynth 재생성 작업 후 C:\Users\ghdtj\workspace\portfolio\local-ai-assist\docs\debugging.md 업데이트

## 이슈 추적 & 리포트 규칙

- **교차 참조 필수**: 미해결 이슈는 발견 문서(`pre-plan/0X-*.md`)와 해결 문서 **양쪽 모두** 기록. "해결 위치" 또는 "발견 위치" 컬럼으로 상호 링크.
- **test-results 리포트 3단 분류**: "문제점" 섹션에서 코드 버그 / Graceful Degradation(정상) / 데이터 특성을 구분. 의도된 미생성(필수 컬럼 부재 등)은 "문제점"이 아님.
- **리포트 중복 금지**: 동일 내용을 다른 섹션에 복붙하지 않음. (예: §3과 §5가 동일하면 §5 제거)

## Skill 활용 맵

| Phase | 활용 Skill |
|-------|-----------|
| 전 Phase 공통 | `tdd`, `verification-before-completion`, `systematic-debugging` |
| 파급 변경 시 | `ripple-search` |
| 서브에이전트 | `subagent-orchestration` |
| RC-0~3 (인프라/파이프라인/DB) | `python-code-quality`, `pytest-backend-testing`, `duckdb` |
| RC-4~5 (대시보드/매핑) | `developing-with-streamlit`, `python-code-quality` |
| 1a (ingest/feature) | `data-analysis`, `python-code-quality`, `python-packaging`, `pytest-backend-testing` |
| 1b (detection/db) | `duckdb`, `data-analysis`, `pytest-backend-testing` |
| 1c (dashboard) → RC-4 | `developing-with-streamlit`, `python-code-quality` |
| Phase 2 (ML) | `data-analysis`, `python-code-quality`, `mermaid` (아키텍처 다이어그램) |
| Phase 3 (LLM) | `langgraph-rag-guidelines`, `pdf` |

## Agent 활용 가이드

| Agent | 용도 | 비고 |
|-------|------|------|
| `planner` | 새 Phase/Sub-phase 시작 시 구현 계획 수립 | 커스텀 에이전트 |
| `code-reviewer` | 주요 모듈 구현 완료 후 코드 리뷰 | 커스텀 에이전트 |
| `error-resolver` | 빌드/런타임 에러 진단 | 커스텀 에이전트 |
| `documentation-architect` | 문서 작성/리뷰/품질 검증 | 커스텀 에이전트 |
| `Explore` | 코드베이스 탐색, 의존성 추적 | 내장 Agent tool |
| `Plan` | 아키텍처 설계, 리팩토링 전략 | 내장 Agent tool |

## dependency-groups

```
core = ["pandas>=2.2", "openpyxl", "pandera", "rapidfuzz", "duckdb", "scipy", "numpy", "pyyaml", "pydantic-settings"]
ml = ["xgboost", "scikit-learn", "shap", "torch"]
nlp = ["kiwipiepy"]
llm = ["vanna[duckdb,chromadb]", "openai"]
dashboard = ["streamlit", "plotly", "streamlit-aggrid"]
export = ["fpdf2"]
dev = ["pytest", "ruff", "mypy"]
```

MVP 설치: `uv sync --group core --group dashboard --group dev`
