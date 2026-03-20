# Design Decisions

아키텍처·기술 선택 결정 로그. 새로운 결정 시 내용 추가.

---

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
- **anomaly 유형의 학술·산업 근거**:
  - **ACFE Fraud Tree**: 49개 부정 scheme → 디지털 전표 환경으로 확장
  - **PCAOB AS 2401 / ISA 240 / COSO 2013 / SOX 302·404**: 실무 감사기준 코드 구현
  - **Schreyer & Sattarov 연구** (arXiv 1709.05254, 1908.00734): 전표 이상치 분류 학술 표준
  - 이 세 프레임워크의 교차 설계로 132개 유형 정의, 우리 데이터에 52개 유형 · 3,103건 주입
- **도구 최신성**: DataSynth 레포 2025-01경 최종 활동(v1.2.0, 506커밋). 우리 데이터는 2026-03-17 직접 빌드·생성 → 최신 코드 기반 출력물 보장
- **대안 검토**: 실제 SAP 데이터(sap-merged 332K)는 이상치 레이블 1%뿐, Schreyer(533K)는 날짜 없음+전부 익명화, BPI 2019(1.6M)는 전표가 아닌 이벤트 로그
- **생성 설정**: `config/datasynth.yaml` (seed 2024, 12개월, 2회사, fraud 2%)
- **결과**: 1,068,119건, 29컬럼, fraud 1.3%, anomaly 2.5%

### D011: 22개 룰 3레이어 탐지 체계 확정 (R001~R008 → A/B/C 레이어)
- **결정**: 기존 R001~R008(8개 룰 + Benford) 체계를 폐기하고, DataSynth 52개 anomaly 유형에서 3축 평가(법규 근거 × FSS 실증 × 데이터 가용성)로 선별한 22개 룰 3레이어 체계로 전면 재설계
- **이유**:
  - 기존 R001~R008은 감사기준서 240호만 참조한 탐색적 설계. 법규 근거·실증 빈도·데이터 적합도의 체계적 평가 부재
  - FSS 감리지적사례 189건 전수 읽기 분석 → 6대 부정 패턴(가공전표 53%, 결산수정 29%, 횡령은폐 26% 등) 도출
  - 3축 평가로 Must(7~9점)/Should(4~6)/Could(2~3)/Drop(0~1) 판정 → Phase별 명확한 구현 범위
- **구조**:
  - Layer A (데이터 무결성 3개): A01 차대변 균형, A02 필수필드 누락, A03 무효 계정
  - Layer B (부정 탐지 10개): B01~B10 (매출이상, 승인한도, 중복, 자기승인, 직무분리, 수기전표, 승인생략, 관계사 등)
  - Layer C (이상 징후 9개): C01~C09 (기말대규모, 주말, 심야, 소급, 기간불일치, 위험적요, Benford, 이상고액, 비정상계정조합)
- **Phase별 확장**: Phase 1(22개 룰) → Phase 2(+16개 ML) → Phase 3(+5개 NLP/그래프) = 총 41개 유형
- **외부 검증**: CAQ 15개 시나리오 93% 커버, PCAOB AS 2401 §61 11개 특성 91% 커버

### D012: FSS 감리지적사례 189건 기반 실증 분석
- **결정**: 금감원 회계포탈 개별 사례 189건(2011~2025)의 본문(HWP/PDF)을 직접 수집·분석하여 전표 조작 패턴 6종 분류
- **이유**: 단순 건수 기반이 아닌 본문 내용 기반 분석으로 실질적 부정 패턴 도출. 제목만으로 6건이던 "횡령 은폐"가 본문 분석 시 24건(4배)으로 증가한 사례 등
- **결과**: 전표 관련 94건(50%), 6대 패턴(가공전표 50, 결산수정 27, 횡령은폐 24, 순환거래 10, 승인/SoD위반 5, 비정상시점 4)
- **활용**: 3축 평가의 "축2: 실증 빈도" 점수 산정 근거

### D013: 점수 체계 3레이어 가중치 설계
- **결정**: MVP 점수 = Layer_A(0.15) + Layer_B(0.45) + Layer_C(0.25) + Benford(0.15). 기존 rule(0.6)+benford(0.4) 폐기
- **이유**: Layer A 위반 시 다른 점수 신뢰도 자체가 하락, Layer B가 핵심 부정 탐지이므로 가중치 최대
- **위험등급**: High(>0.7 또는 A위반+B 2개+), Medium(>0.4), Low(>0.2), Normal(≤0.2)
- **참고**: 가중치·임계값은 근거 없는 초기 설계값. Phase 1 완료 후 back-testing으로 튜닝 예정

### D014: 파일 카테고리별 검증 전략 (file_validator 3분류)
- **결정**: 10개 확장자를 3개 카테고리(Excel/Text/Columnar)로 분류하여 각각 다른 크기 제한·검증 전략 적용. PDF/HWP는 프로젝트 범위 외로 거부
- **이유**:
  - Excel(.xlsx/.xls/.xlsb): 시트당 104만 행 물리 제한 → 100MB 충분. 각각 openpyxl/xlrd/pyxlsb로 손상 검증
  - Text(.csv/.tsv/.txt/.dat): 크기 제한 없는 포맷, 인코딩 다양(UTF-8/CP949/latin-1) → 800MB + charset_normalizer 자동 감지 + ascii→latin-1 폴백
  - Columnar(.parquet): 압축 효율 높아 1GB 허용. pyarrow 메타데이터만 읽어 검증
  - PDF/HWP: 비정형 문서 데이터 추출은 별도 프로젝트 범위 (CONSTRAINTS.md 참고)
- **구조**: `file_categories.py`(카테고리 정의) + `integrity_checkers.py`(확장자별 열기 검증) + `file_validator.py`(퍼사드) 3파일 분리 (SRP)
- **설정**: `settings.py`의 `allowed_extensions`/`max_file_size_mb`는 deprecated. 카테고리별 제한은 `file_categories.py` 상수로 관리 (파일 포맷 물리적 특성이므로 사용자 설정이 아님)

### D016: UX 1단계 — 데이터 수집 투명성 (Ingest v2)
- **정의**: 사용자가 데이터를 넣으면 AI가 헤더/컬럼을 자동 지정하고, 애매한 부분은 사용자에게 위임하며, 판단 근거(신뢰도, 매칭 방식)를 투명하게 노출하는 UX 모델
- **결정**: 헤더 탐지를 구조적 신호 기반으로 전환, fuzzy 매핑에 타입 검증 추가, 매핑 판단 근거를 ReviewItem으로 구조화
- **UX 원칙**:
  - **80/20 자동화**: 확신 높은 80%는 자동 처리(action="auto"), 나머지 20%는 사용자 검토(action="review")
  - **블랙박스 공포증 해소**: 모든 매핑에 reason(판단 근거) + confidence(신뢰도) + source_type/target_type 노출
  - **3-tier 시각 피드백**: 확정(초록) / 추천+확인 필요(노랑) / 차단됨(빨강)
- **구현 내용**:
  - A1. 구조적 헤더 탐지 — 키워드 없어도 데이터 구조(타입다양성/고유값/null밀도)로 헤더 판별
  - B1. 타입 호환성 검증 — fuzzy 후보의 소스↔스키마 타입 비교, 비호환 차단
  - B3. Null 3단계 분기 — 유령 컬럼 조용히 분리, 오매핑 의심 명시 경고
  - C. dc_indicator 표준 컬럼 등록
  - D. ReviewItem 모델 — action/confidence/reason/source_type/target_type 구조
  - E. ascii→latin-1 인코딩 폴백 — 대용량 CSV 오탐 근본 해결
- **결과**: 5종 실데이터셋 전체 올그린 (bpi2019 527MB 1.6M행 포함), 197 tests passed
- **Phase 1c 연계**: ReviewItem → Streamlit 매핑 확인 UI의 데이터 소스로 직접 사용

### D017: ascii→latin-1 인코딩 폴백
- **결정**: `text_reader._detect_encoding()`에서 charset_normalizer가 "ascii"로 감지하면 "latin-1"으로 폴백
- **이유**: charset_normalizer는 64KB 샘플 기반. bpi2019(527MB, latin-1)의 첫 특수문자(0x96)가 249KB 지점 → 샘플 범위 밖 → ascii 오탐 → 읽기 실패
- **근거**: ascii는 latin-1의 진부분집합(0x00~0x7F). latin-1은 0x00~0xFF 전체 매핑이므로 어떤 바이트든 에러 없이 읽힘. 순수 ascii 파일을 latin-1로 읽어도 결과 동일 → 부작용 없음
- **대안 검토**: 샘플 크기 확대(256KB~1MB)는 더 뒤에 특수문자가 나오면 또 실패 → 근본 해결 아님

### D015: 파일 읽기 4-리더 분리 + read_only=False 결정
- **결정**: pre-plan의 단일 `excel_reader.py`(WorkbookInfo) → 4개 리더 + 1개 퍼사드 + 1개 모델로 확장. xlsx는 `read_only=False`로 병합셀 처리 우선
- **이유**:
  - `read_only=True`와 `merged_cells.ranges`는 openpyxl에서 양립 불가. ERP 엑셀의 병합셀은 매우 흔함
  - xlsx/xls/xlsb/csv/tsv/txt/dat/parquet 10개 확장자가 모두 다른 라이브러리·API 사용 → 단일 파일로 불가 (SRP 위반, 100줄 초과)
  - DataSynth CSV(232MB)가 메인 데이터인데 openpyxl 경로를 타면 안 됨 → CSV fast path 필수
  - CSV/Parquet은 "시트" 개념이 없으므로 WorkbookInfo 대신 통합 `ReadResult` 타입 필요
- **구조**: `models.py`(ReadResult) + `excel_reader.py`(xlsx/xls/xlsb) + `text_reader.py`(csv/tsv) + `parquet_reader.py` + `reader_api.py`(퍼사드)
- **메모리 안전장치**: file_validator의 100MB 제한이 read_only=False의 메모리 위험을 상쇄 (16GB RAM)
