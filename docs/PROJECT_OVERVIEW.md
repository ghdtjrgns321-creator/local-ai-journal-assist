# Project Overview

## 프로젝트 정의

Local AI Audit Assistant v2.0 — 감사 실증절차 전표 테스트 자동화 도구.
MindBridge, KPMG Clara의 핵심 로직을 오픈소스(Python)로 재현하는 포트폴리오.

## 기술 스택

| 영역        | 기술                               | 비고                                        |
|-------------|------------------------------------|---------------------------------------------|
| 언어        | Python 3.11+                       |                                             |
| 패키지      | uv + pyproject.toml                | dependency-groups로 core/ml/llm/dashboard 분리 |
| 전처리      | openpyxl, pandas 2.x, pandera      | pandera: 스키마 기반 품질 게이트            |
| 컬럼 매핑   | rapidfuzz                          | fuzzy string matching                       |
| 설정        | pydantic-settings, pyyaml          | 환경변수 + YAML                             |
| 통계        | scipy.stats, numpy                 | Benford, KS 검정, Runs test                |
| 지도학습    | xgboost, lightgbm, scikit-learn, shap | 파이프라인 인프라 (고객사 실데이터 fine-tuning용, Phase 2) |
| 비지도학습  | pytorch (VAE), scikit-learn (IF)   | **핵심 탐지기** — 합성 데이터 적합도 높음 (Phase 2)  |
| 한국어 NLP  | kiwipiepy                          | JVM 의존성 없음 (Phase 3)                  |
| DB          | duckdb                             | OLAP 최적화                                 |
| LLM         | ollama + Qwen3-8B (Q4_K_M)        | Phase 3                                     |
| Text-to-SQL | Vanna AI 2.0                       | Phase 3                                     |
| 벡터 DB     | ChromaDB                           | Vanna 학습 스토리지 (Phase 3)              |
| 대시보드    | streamlit, plotly, streamlit-aggrid |                                             |
| PDF         | fpdf2                              | Phase 3                                     |

## 디렉토리 구조

```
local-ai-assist/
├── pyproject.toml
├── CLAUDE.md
├── config/                     # 설정 (Pydantic Settings + YAML)
│   ├── settings.py
│   ├── datasynth.yaml          # DataSynth 생성 설정 (seed, 회사, fraud 비율)
│   ├── schema.yaml             # 표준 컬럼 스키마 (DataSynth 출력 기준)
│   ├── keywords.yaml           # ERP별 헤더 키워드
│   ├── risk_keywords.yaml      # 감사 위험 적요 키워드
│   ├── cleaning.yaml           # 타입 캐스팅 전처리 규칙 (통화·null·불리언·날짜·DC 지시자)
│   └── presets/                # 환경 프리셋 (산업별/시즌별 임계값 세트)
│       ├── default.yaml        # 평시 모드
│       ├── closing.yaml        # 결산기 모드
│       └── construction.yaml   # 건설업 모드
├── src/
│   ├── pipeline.py             # 전체 오케스트레이터
│   ├── ingest/                 # 수집·평탄화
│   ├── feature/                # 감사 파생변수
│   ├── eda/                    # EDA 프로파일링 (품질·분포·이상치)
│   ├── validation/             # 계층적 검증 (L1~L3)
│   ├── preprocessing/          # ML 전처리 파이프라인 (Phase 2)
│   ├── detection/              # 3-Layer 이상탐지 (A무결성/B부정/C징후)
│   ├── db/                     # DuckDB
│   ├── llm/                    # LLM 연동 (Phase 3)
│   └── export/                 # 내보내기 (Phase 3)
├── dashboard/                  # Streamlit
│   ├── __init__.py
│   ├── _state.py               # session_state 키 상수 + FilterState + init_state()
│   ├── _kpi.py                 # KPI 6개 + 데이터 품질 계산 (순수 pandas)
│   ├── app.py                  # 메인 앱 (WU6) ✅
│   ├── tab_eda.py              # Tab 0: EDA 프로파일 (WU6) ✅
│   ├── tab_summary.py          # Tab 1: Executive Summary (WU2) ✅
│   ├── tab_benford.py          # Tab 2: Benford Analysis (WU3) ✅
│   ├── tab_explorer.py         # Tab 3: Anomaly Explorer (WU4) ✅
│   ├── tab_chat.py             # Tab 5: Text-to-SQL (Phase 3)
│   ├── tab_export.py           # Tab 6: Export (Phase 3)
│   └── components/
│       ├── data_uploader.py    # 파일 업로드 + 파이프라인 실행
│       ├── filters.py          # 사이드바 필터 12개 + apply_filters
│       ├── preset_selector.py  # 환경 프리셋 드롭다운 (WU5)
│       ├── threshold_sidebar.py # 임계값 튜닝 슬라이더 23개 (WU5)
│       ├── rule_panel.py       # 룰 컨트롤 패널 — 가중치/임계값/토글 (WU5)
│       ├── _redetect.py        # 설정 변경 후 재탐지 헬퍼 + 적용 버튼 (WU5)
│       ├── mapping_review.py   # 매핑 리뷰 3-tier UI (WU7) — UI-1~4 + 필수/권장 미매핑 안내
│       ├── explorer_grid.py    # AgGrid 27컬럼 + JsCode 조건부 서식
│       ├── explorer_detail.py  # 행 상세 패널 (룰 점수 차트 + 라인아이템)
│       ├── explorer_whitelist.py # HITL 예외 처리 (whitelist CRUD + 메모리 동기화)
│       └── charts/             # Plotly 차트 래퍼 17종 (8모듈)
├── .streamlit/
│   └── config.toml             # maxUploadSize/maxMessageSize 1GB
├── tests/
├── data/journal/               # 전표 데이터 (.gitignore)
│   ├── primary/datasynth/     # 메인: EY-ASU 합성 전표 (1,105K건)
│   └── validation/            # 검증: sap-merged, schreyer-fraud, bpi2019 등
├── tools/datasynth/            # EY-ASU DataSynth (Rust, 합성 전표 생성기)
└── docs/
    ├── pre-plan/              # 구현 가이드 (기능 영역별)
    └── *.md                   # 프로젝트 문서
```

## 구현 가이드 (docs/pre-plan/)

개요서를 기능 영역별로 분리한 구현 레퍼런스. 각 파일은 목적/관련 파일/핵심 클래스/데이터 흐름/구현 순서/테스트 전략을 포함.

| #  | 파일                                                     | 내용                                                          | Phase  |
|----|----------------------------------------------------------|---------------------------------------------------------------|--------|
| 0  | [00-dataset.md](pre-plan/00-dataset.md)                  | 데이터셋 수집·선정·적합도·Phase별 활용 전략                   | 사전   |
| 1  | [01-project-setup.md](pre-plan/01-project-setup.md)      | pyproject.toml, uv, AuditSettings, YAML 설정                 | MVP    |
| 2  | [02-ingest.md](pre-plan/02-ingest.md)                    | 파일 검증, Excel 읽기, 헤더 탐지, 컬럼 매핑, 타입 캐스팅     | MVP    |
| 3  | [03-feature.md](pre-plan/03-feature.md)                  | 감사 파생변수 11개 (time/amount/pattern/text)                 | MVP    |
| 3a | [03a-preprocessing.md](pre-plan/03a-preprocessing.md)    | ML 전처리 파이프라인, VAE 래퍼, 라벨 전략                     | P2     |
| 4  | [04-validation.md](pre-plan/04-validation.md)            | L1 Pandera + L2 회계 + L3 통계 검증 + 리포트                 | MVP+P2 |
| 5  | [05-detection.md](pre-plan/05-detection.md)              | BaseDetector, 3레이어 24개 룰(A/B/C), Benford(C07), ML 16개, NLP 5개 | MVP~P3 |
| 6  | [06-db.md](pre-plan/06-db.md)                            | DuckDB 커넥션, 스키마, 로더, 프리셋 쿼리                     | MVP    |
| 7  | [07-dashboard.md](pre-plan/07-dashboard.md)              | Streamlit 5탭, 컴포넌트, 차트, 필터                          | MVP+P3 |
| 8  | [08-llm.md](pre-plan/08-llm.md)                          | Ollama, Vanna AI 2.0, SQL 검증, 프리셋, 인사이트             | P3     |
| 9  | [09-export.md](pre-plan/09-export.md)                    | Excel/PDF 감사조서, Audit Trail                               | P3     |
| 10 | [10-sample-data.md](pre-plan/10-sample-data.md)          | 가상 GL 데이터 생성기 — DataSynth로 대체됨                    | MVP    |
| UX | [ux-flow.md](pre-plan/ux-flow.md)                        | UX 3단계 흐름도, 감사인 심리, 3가지 디자인 원칙               | 전체   |

**구현 의존 그래프:**
```
00-dataset → 01-project-setup → 10-sample-data → 02-ingest → 03-feature → 04-validation
                                                                    ↓
                                                              05-detection → 03a-preprocessing → ML 탐지
                                                                                                    ↓
                                                                                                  06-db
                                                                                                    ↓
                                                                                              07-dashboard
                                                                                                    ↓
                                                                                         08-llm → 09-export
```

## 합성 데이터 (DataSynth)

EY-ASU DataSynth(Rust)로 생성한 K-IFRS 적용 한국 중견 제조 그룹사 시뮬레이션.

| 항목           | 값                                                    |
|----------------|-------------------------------------------------------|
| 법인           | C001 본사(서울), C002 울산공장, C003 천안공장 — 전체 KRW |
| 회계연도       | 2022-01 ~ 2022-12                                     |
| 전표 규모      | 106,489건 / 1,104,914 라인아이템                      |
| 금액 분포      | LogNormal(14.0, 2.5) — 중앙값 ~120만원                |
| 승인 한도      | 6단계 전결규정 (자동→담당자→팀장→본부장→CFO→이사회)    |
| 사용자 풀      | 152명 (5개 페르소나), SoD 위반 11.7%                  |
| 시간 패턴      | 한국 근무 문화 반영 (심야 0.02, 오전 피크 1.8, 야근 0.3) |
| 이상 주입      | fraud 2% + error 2% + process 1%, 16가지 부정 유형    |
| Benford        | 첫째 자릿수 적합 (tolerance 5%, payroll/recurring 제외) |

## ML 학습 전략

비지도학습 중심 + 지도학습 파이프라인 인프라 구축.

| 접근법 | 모델 | 역할 | 합성 데이터 적합도 |
|:-------|:-----|:-----|:-----------------:|
| 비지도학습 | VAE + Isolation Forest | **핵심 탐지기** — 정상 분포 이탈 탐지 | 높음 |
| 지도학습 | XGBoost, FT-Transformer, BiLSTM | 파이프라인 인프라 — 고객사 실데이터 유입 시 활성화 | 중간 |
| 앙상블 | Stacking Meta-Learner (LR Ridge) | 6개 모델 출력 결합 | 높음 |

**배경**: DataSynth 합성 데이터의 이상치는 룰 기반으로 주입되므로, 지도학습 시 순환 학습(Circular Learning) 문제 발생.
비지도학습(VAE+IF)은 정상 분포를 학습하므로 합성 데이터에서도 유효.
지도학습 파이프라인(cv_selector, SMOTE-ENN, PR-AUC 평가)은 인프라로 구축하여,
향후 고객사별 실데이터 유입 시 fine-tuning으로 즉시 활성화 가능.

상세: [CONSTRAINTS.md §ML 학습 전략](CONSTRAINTS.md) | [TROUBLESHOOT.md §TS-3](TROUBLESHOOT.md)

## 데이터 흐름

```
DataSynth (tools/datasynth/) → config/datasynth.yaml → journal_entries.csv (1,105K건)
  ↓
Excel/CSV → file_validator → excel_reader → header_detector → column_mapper → type_caster(←cleaning.yaml)
  ↑ UX 1단계: 자동 헤더/매핑 + 애매한 부분 사용자 위임 + 판단 근거 투명 노출 (ReviewItem)
  → 표준 DataFrame → feature/engine (감사 파생변수 18개)
  → eda/profiler (EDAProfile JSON) → eda/report (대시보드 요약)
  ↑ UX 2단계: 감사 룰 조종석(Control Panel) + 파생변수 자동 생성 + audit_rules 프로파일 저장
  → validation (3-Level: L1 구조 게이트 + L2 회계 경고)
  → detection (3-Layer: A무결성 3개 + B부정 11개 + C징후 10개, 24개 룰)
  → score_aggregator (가중합 + risk_level 분류 + B19 Top-side JE)
  ↑ 오케스트레이터: src/pipeline.py — AuditPipeline.run(path) 단일 진입점
  → DuckDB (4테이블 + 1VIEW 원자적 적재)
  → preprocessing (Phase 2: pipeline_builder → cv_selector → 최적 모델 자동 선택)
    → ML 탐지 (XGBoost + VAE+IF + FT-Transformer + BiLSTM+Attention → Stacking 앙상블)
    → 프리셋 SQL / Text-to-SQL (Phase 3)
      → Streamlit 대시보드
  ↑ UX 3단계: EDA 프로파일링 + 전처리 투명성 (Phase 1a EDA + Phase 2 ML Pipeline)

> UX 전체 흐름 & 3가지 디자인 원칙: [ux-flow.md](pre-plan/ux-flow.md) 참조
```
