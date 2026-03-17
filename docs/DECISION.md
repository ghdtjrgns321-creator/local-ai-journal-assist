# Design Decisions

아키텍처·기술 선택 결정 로그. 새로운 결정 시 날짜와 함께 추가.

---

## 2026-03-16: 초기 기술 스택 확정

### D001: Qwen3-8B 1순위 (Qwen2.5-Coder 폴백)
- **이유**: Qwen3 Ollama 지원, reasoning 성능 향상. RTX 3070 Ti 8GB에 Q4_K_M 적합 (6~7GB VRAM)
- **폴백**: Qwen2.5-Coder-7B (Text-to-SQL 특화)

### D002: Vanna AI 2.0 채택 (직접 프롬프트 대신)
- **이유**: DuckDB+Ollama+ChromaDB 네이티브, agent-based API, 자동 Plotly, 개발시간 80% 절감
- **트레이드오프**: Vanna 의존성 증가, 커스터마이징 제한

### D003: kiwipiepy 단독 (konlpy 제거)
- **이유**: JVM 의존성 제거, 순수 Python, pip install 한 줄 완결

### D004: fpdf2 채택 (reportlab 대신)
- **이유**: 경량화, 간단한 감사조서에 충분

### D005: LangGraph 제거
- **이유**: Vanna+PandasAI로 충분. Phase 3에서 필요 시 재평가

### D006: BaseDetector 추상 클래스 패턴
- **이유**: 모든 탐지 트랙이 `detect() -> DetectionResult` 인터페이스 공유. 트랙 추가 시 score_aggregator 수정 최소화

### D007: LLM 없이 MVP 동작
- **이유**: Phase 1은 LLM 호출 0. 컬럼 매핑 실패 시 수동 UI 폴백. 점진적 복잡도 증가

### D008: dependency-groups 분리
- **이유**: `uv sync --group core,dashboard`로 MVP 최소 설치. ML/LLM은 필요 시에만

### D009: 개요서 → 기능별 구현 가이드 10개 분리
- **이유**: 하나의 개요서(380줄)에서 구현 시 참조가 어려움. 기능 영역별 분리로 각 모듈 구현 시 해당 가이드만 참조
- **구조**: `docs/pre-plan/01~10-*.md`, 공통 포맷(목적/관련 파일/핵심 클래스/데이터 흐름/구현 순서/의존성/테스트/Phase/주의사항)
- **원본 유지**: `개요서.md`는 전체 뷰 용도로 보존, 구현 가이드는 상세 레퍼런스
