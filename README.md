# Local AI Audit Assistant

감사 실증절차 전표 테스트를 로컬 환경에서 자동화하는 Python 프로젝트.
PCAOB AS 2401, ISA 240 기반. MindBridge/KPMG Clara 핵심 로직을 오픈소스로 재현.

## 주요 기능

- **3레이어 24개 룰 기반 탐지**: Layer A(데이터 무결성 3개) + Layer B(부정 탐지 11개) + Layer C(이상 징후 10개)
- **이중 ML 탐지 체계**: 이상치(XGBoost Classification) + 특이치(VAE+IF Novelty Detection)
- **Zero-day 부정 탐지**: VAE가 정상 분포를 학습하여 미지의 부정 패턴도 탐지
- **Benford's Law 분석**: MAD + Chi-square + KS 검정 기반 첫째 자릿수 적합성 판정
- **자동 컬럼 매핑**: fuzzy matching + 구조적 헤더 탐지 + 타입 검증 (UX 1단계)
- **EDA 프로파일링**: 7개 모듈 (품질/분포/이상치/시계열/상관/텍스트/리포트)
- **3단계 검증**: L1 스키마(Pandera) + L2 회계(복식부기/기간) + L3 통계(Phase 2)
- **전처리 투명성**: White Box 전처리 -- 전후 비교 대시보드 (UX 3단계)

## 기술 스택

| 영역          | 기술                                    |
|:--------------|:----------------------------------------|
| 언어          | Python 3.11+                            |
| 패키지 관리   | uv + pyproject.toml (dependency-groups) |
| 데이터 처리   | pandas 2.x, openpyxl, pandera          |
| 통계          | scipy.stats, numpy                      |
| 지도학습      | XGBoost, LightGBM, scikit-learn, SHAP   |
| 비지도학습    | PyTorch (VAE), scikit-learn (IF)        |
| DB            | DuckDB (OLAP)                           |
| 대시보드      | Streamlit + Plotly + AgGrid             |
| LLM (Phase 3) | Ollama + Qwen3-8B (Q4_K_M)            |
| NLP (Phase 3) | kiwipiepy                              |
| 데이터 생성   | EY-ASU DataSynth (Rust) — K-IFRS 한국 중견 제조 3법인, 1,105K건 |

## 아키텍처

```
Excel/CSV -> ingest (자동 매핑) -> feature (18개 파생변수) -> validation (L1~L3)
  -> detection (24개 룰 + XGBoost + VAE+IF) -> score_aggregator -> DuckDB
    -> Streamlit 대시보드 (Summary / Benford / Explorer)
```

## 탐지 체계

### 룰 기반 (Phase 1b)
- **Layer A** (무결성): 차대변 균형, 필수필드 누락, 무효 계정
- **Layer B** (부정): 매출 이상, 승인한도, 중복 지급, 자기승인, 수기전표 등 10개
- **Layer C** (징후): 기말 대규모, 주말/심야 전기, Benford 위반, 이상 고액 등 9개

### ML 기반 (Phase 2)
- **이상치 탐지** (Classification): cv_selector가 LR/RF/XGBoost/LightGBM 자동 비교 후 최적 모델 선택
- **특이치 탐지** (Novelty): Basic FC VAE + Isolation Forest 앙상블
- **점수 통합**: Percentile Ranking으로 스케일 통일 후 전략 패턴 가중합으로 anomaly_score 산출

### 점수 체계
```
anomaly_score = Layer_A(0.15) + Layer_B(0.45) + Layer_C(0.25) + Benford(0.15)
위험 등급: High(>0.7) / Medium(>0.4) / Low(>0.2) / Normal(<=0.2)
```

## UX 설계

감사 도구는 **통제 요구(판단 근거 투명성)**와 **간결성 요구(초기 설정 최소화)**가 상충하는 환경이다.
3가지 설계 원칙으로 이 상충을 해결한다.

### 3가지 UX 원칙

| 원칙                  | 내용                                                     |
|:----------------------|:---------------------------------------------------------|
| 스마트 디폴트          | 모든 설정에 업계 표준 기본값 사전 적용. [다음] 버튼만으로 분석 시작 가능 |
| 점진적 공개            | 기본/전문가 2계층 UI. 초기 인지 부하를 줄이고 고급 설정은 접이식 패널   |
| 프로파일 재사용        | 컬럼 매핑 + 감사 룰 설정을 프로파일로 저장. 반복 감사 시 자동 로드      |

### UX 3단계 흐름

```
UX 1단계: 데이터 수집 투명성 (Ingest)                          [Phase 1a 완료]
  파일 업로드 → AI 자동 매핑 → 3-tier 시각 피드백(초록/노랑/빨강)
  → 저신뢰 항목만 사용자 확인 (Human-in-the-Loop)
  → ReviewItem(판단 근거 + 신뢰도) 투명 노출

UX 2단계: 감사 룰 세팅 & 파생변수 (Feature)                    [엔진 완료, UI 예정]
  감사 룰 조종석(Control Panel) → 시간/금액/패턴/키워드 기준 설정
  → 18개 파생변수 자동 생성 → audit_rules 프로파일 저장 (Data Flywheel)

UX 3단계: 전처리 투명성 & EDA (Preprocessing)                  [Phase 2]
  EDA 프로파일링(품질/분포/이상치) → sklearn Pipeline 설정 UI
  → Pipeline 성능 비교(F1/AUC) → White Box 전처리 전후 비교
```

> 상세: [docs/pre-plan/ux-flow.md](docs/pre-plan/ux-flow.md)

## Phase 로드맵

| Phase | 범위                                                     | 상태   |
|:------|:---------------------------------------------------------|:-------|
| 1a    | ingest + feature + validation + EDA 프로파일링            | 완료   |
| 1b    | detection (24개 룰 3레이어) + DuckDB + pipeline           | 미착수 |
| 1c    | Streamlit 대시보드 3탭                                    | 미착수 |
| 2a    | ML 전처리 파이프라인 (pipeline_builder, cv_selector, VAE) | 미착수 |
| 2b    | ML 탐지기 (SupervisedDetector, VAEDetector, SHAP)         | 미착수 |
| 2c    | 추가 탐지기 (Duplicate, Timeseries, Intercompany)         | 미착수 |
| 3     | Ollama LLM + Vanna Text-to-SQL + NLP + Graph + Export     | 미착수 |

## 설치 및 실행

```bash
# 의존성 설치 (MVP)
uv sync --group core --group dashboard --group dev

# 테스트 실행
uv run pytest tests/ -v

# 대시보드 실행 (Phase 1c 완료 후)
uv run streamlit run dashboard/app.py
```

## 데이터

EY-ASU DataSynth(Rust)로 생성한 K-IFRS 적용 한국 중견 제조 그룹사(3법인) 합성 전표.
seed 고정 재현 가능, 132종 anomaly 유형, PCAOB/ISA/COSO/SOX 감사기준 코드 레벨 구현.

- **법인**: C001 본사(서울) + C002 울산공장 + C003 천안공장, 전체 KRW
- **규모**: 106,489건 전표 / 1,104,914 라인아이템 (2022년 1월~12월)
- **승인**: 한국 중견 제조업 6단계 전결규정 (자동 → 담당자 → 팀장 → 본부장 → CFO → 이사회)
- **사용자**: 152명 (5개 페르소나), SoD 위반 11.7%, 프로세스 겸직 7%
- **이상 주입**: fraud 2% + error 2% + process 1%, 16가지 부정 유형
- **시간 패턴**: 한국 근무 문화 반영 (오전 피크, 점심 감소, 퇴근 러시, 심야 극소)

```
data/journal/
  primary/datasynth/    # 메인: 합성 전표 (fraud 2%, 16가지 유형)
  validation/           # 검증: sap-merged, schreyer-fraud, bpi2019 등
```

## 프로젝트 문서

| 문서                         | 내용                                    |
|:-----------------------------|:----------------------------------------|
| docs/TASKS.md                | Phase별 태스크 목록 + 완료 상태         |
| docs/DECISION.md             | 아키텍처/기술 선택 결정 로그 (D001~D027) |
| docs/pre-plan/               | 기능 영역별 구현 가이드 (12개 파일)     |
| docs/DETECTION_RULES.md      | 전체 탐지 룰 목록, 점수 체계, 컬럼 스키마 |

## 라이선스

Private (Portfolio Project)
