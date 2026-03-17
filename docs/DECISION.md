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

### D010: EY-ASU DataSynth를 메인 데이터 소스로 채택
- **결정**: 32개 공개 데이터셋/도구 검토 후, EY-ASU DataSynth(tools/datasynth/)로 생성한 합성 전표를 메인 데이터로 채택. 기존 수집 데이터(sap-merged, schreyer-fraud 등 5종)는 검증용으로 전환
- **이유**:
  - SAP ACDOCA 71필드 네이티브 구조 (실제 SAP S/4HANA와 동일 필드명)
  - Fraud 레이블 132종 내장 (49 fraud + 28 error + 22 process + 18 statistical + 15 relational)
  - 복식부기 항등식(차=대) 보장, Benford 분포 준수
  - PCAOB/ISA/COSO/SOX 감사기준 코드 레벨 구현
  - seed 고정으로 동일 데이터 재현 가능
  - 포트폴리오에서 "EY+ASU 공동 개발 도구 기반"으로 어필
- **대안 검토**: 실제 SAP 데이터(sap-merged 332K)는 이상치 레이블 1%뿐, Schreyer(533K)는 날짜 없음+전부 익명화, BPI 2019(1.6M)는 전표가 아닌 이벤트 로그
- **생성 설정**: `config/datasynth.yaml` (seed 2024, 12개월, 2회사, fraud 2%)
- **결과**: 1,068,119건, 29컬럼, fraud 1.3%, anomaly 2.5%
