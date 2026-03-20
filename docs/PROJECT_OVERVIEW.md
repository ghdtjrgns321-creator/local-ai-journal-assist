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
| 지도학습    | xgboost, scikit-learn, shap        | Phase 2                                     |
| 비지도학습  | pytorch (VAE), scikit-learn (IF)   | Phase 2                                     |
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
│   └── risk_keywords.yaml      # 감사 위험 적요 키워드
├── src/
│   ├── pipeline.py             # 전체 오케스트레이터
│   ├── ingest/                 # 수집·평탄화
│   ├── feature/                # 감사 파생변수
│   ├── validation/             # 계층적 검증 (L1~L3)
│   ├── detection/              # 3-Layer 이상탐지 (A무결성/B부정/C징후)
│   ├── db/                     # DuckDB
│   ├── llm/                    # LLM 연동 (Phase 3)
│   └── export/                 # 내보내기 (Phase 3)
├── dashboard/                  # Streamlit
│   ├── app.py
│   ├── tab_summary.py          # Tab 1: Executive Summary
│   ├── tab_benford.py          # Tab 2: Benford Analysis
│   ├── tab_explorer.py         # Tab 3: Anomaly Explorer
│   ├── tab_chat.py             # Tab 4: Text-to-SQL (Phase 3)
│   ├── tab_export.py           # Tab 5: Export (Phase 3)
│   └── components/
├── tests/
├── data/journal/               # 전표 데이터 (.gitignore)
│   ├── primary/datasynth/     # 메인: EY-ASU 합성 전표 (1,068K건)
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
| 4  | [04-validation.md](pre-plan/04-validation.md)            | L1 Pandera + L2 회계 + L3 통계 검증 + 리포트                 | MVP+P2 |
| 5  | [05-detection.md](pre-plan/05-detection.md)              | BaseDetector, 3레이어 22개 룰(A/B/C), Benford(C07), ML 16개, NLP 5개 | MVP~P3 |
| 6  | [06-db.md](pre-plan/06-db.md)                            | DuckDB 커넥션, 스키마, 로더, 프리셋 쿼리                     | MVP    |
| 7  | [07-dashboard.md](pre-plan/07-dashboard.md)              | Streamlit 5탭, 컴포넌트, 차트, 필터                          | MVP+P3 |
| 8  | [08-llm.md](pre-plan/08-llm.md)                          | Ollama, Vanna AI 2.0, SQL 검증, 프리셋, 인사이트             | P3     |
| 9  | [09-export.md](pre-plan/09-export.md)                    | Excel/PDF 감사조서, Audit Trail                               | P3     |
| 10 | [10-sample-data.md](pre-plan/10-sample-data.md)          | 가상 GL 데이터 생성기 — DataSynth로 대체됨                    | MVP    |

**구현 의존 그래프:**
```
00-dataset → 01-project-setup → 10-sample-data → 02-ingest → 03-feature → 04-validation
                                                                    ↓
                                                              05-detection → 06-db
                                                                               ↓
                                                                         07-dashboard
                                                                               ↓
                                                                    08-llm → 09-export
```

## 데이터 흐름

```
DataSynth (tools/datasynth/) → config/datasynth.yaml → journal_entries.csv (1,068K건)
  ↓
Excel/CSV → file_validator → excel_reader → header_detector → column_mapper → type_caster
  ↑ UX 1단계: 자동 헤더/매핑 + 애매한 부분 사용자 위임 + 판단 근거 투명 노출 (ReviewItem)
  → 표준 DataFrame → feature/engine (감사 파생변수) → validation (3-Level)
    → detection (3-Layer: A무결성 3개 + B부정 10개 + C징후 9개, 22개 룰) → score_aggregator
      → DuckDB → 프리셋 SQL / Text-to-SQL (Phase 3)
        → Streamlit 대시보드
```
