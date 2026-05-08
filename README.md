# Local AI Audit Assistant

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
감사 실증절차 전표 테스트를 로컬 환경에서 자동화하는 Python 프로젝트.
PCAOB AS 2401, ISA 240 기반. MindBridge/KPMG Clara 핵심 로직을 오픈소스로 재현.

## 주요 기능

- **32개 룰 기반 감사 검토 후보 선별**: L1(확정 오류/명시 위반 9개) + L2(강한 통제우회·자금유출 검토 신호 5개) + L3(검토 필요 이상징후 12개, L3-12 업무범위 집중 검토 포함) + L4(통계적 이상치 6개)
- **이중 ML 탐지 체계**: 이상치(XGBoost Classification) + 특이치(VAE+IF Novelty Detection)
- **Zero-day 이상 징후 후보화**: VAE가 정상 분포를 학습하여 기존 룰로 설명하기 어려운 신규 검토 후보를 보조 선별
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
| LLM (Phase 3) | 상용 API (Gemini, Claude 등)           |
| NLP (Phase 3) | kiwipiepy                              |
| 데이터 생성   | EY-ASU DataSynth (Rust) — K-IFRS 한국 중견 제조 3법인, 3년치 1,108K라인 / 319K전표 |

## 아키텍처

```
Excel/CSV -> ingest (자동 매핑) -> feature (18개 파생변수) -> validation (L1~L3)
  -> detection (32개 룰 + XGBoost + VAE+IF) -> score_aggregator -> DuckDB
    -> Streamlit 대시보드 (Summary / Benford / Explorer)
      -> 상용 LLM API (Text-to-SQL / 인사이트 / Export)
```

## 탐지 체계

### 룰 기반 (Phase 1b)
- **L1 확정 이슈**: 차대변 균형, 필수필드 누락, 무효 계정, 승인 통제 위반
- **L2 강한 통제우회·자금유출 검토 신호**: 승인한도 근접, 중복 지급/전표, 비용 자본화 등
- **L3 검토 필요 신호**: 수기전표, 관계사 거래, 기말/주말/심야/소급 전기, 위험 적요 등
- **L4 통계/분포 이상치**: Benford, 고액 outlier, 희소 계정쌍, 사용자 행동 집중 등

### ML 기반 (Phase 2)
- **이상치 탐지** (Classification): cv_selector가 LR/RF/XGBoost/LightGBM 자동 비교 후 최적 모델 선택
- **특이치 탐지** (Novelty): Basic FC VAE + Isolation Forest 앙상블
- **점수 통합**: Percentile Ranking으로 스케일 통일 후 전략 패턴 가중합으로 anomaly_score 산출

### 점수 체계
```text
anomaly_score =
  0.40 * L1 max rule-family score
+ 0.25 * L2 max rule-family score
+ 0.20 * L3 max rule-family score
+ 0.15 * L4 max rule-family score

위험 등급: High(>=0.7) / Medium(>=0.4) / Low(>=0.2) / Normal(<0.2)
```

`layer_a`, `layer_b`, `layer_c`, `benford`는 detector 실행/저장 호환용 이름이다. 기본 row-level `anomaly_score`는 더 이상 legacy layer 가중합이 아니라 L1/L2/L3/L4 룰 family 가중합으로 계산한다. Benford(`L4-02`)는 보통 개별 transaction flag가 아니라 account/process 단위 macro finding으로 분리한다.

PHASE1 사용자 큐는 위 row-level `anomaly_score`와 별도로 case-level `priority_score`를 사용한다. 룰별 `상/중/하`, `High/Medium/Low`, `검토 필요` 같은 표현은 직접 합산하지 않고 `src/detection/rule_scoring.py`에서 `signal_strength`, `evidence_strength`, `scoring_role`, `normalized_score`로 정규화한 뒤 evidence type별로 묶는다.

룰 참조는 확정 신호와 검토 후보를 분리한다. `flagged_rules`는 `details > 0`인 confirmed/immediate 룰만 담고, `review_rules`는 `details == 0`이지만 `row_annotations.review_score`가 있는 review-only 후보를 담는다. `anomaly_score`와 PHASE1 case priority는 두 신호를 모두 반영할 수 있지만, DB `anomaly_flags`, export, LLM narrative에서 확정 위반처럼 집계하는 기준은 `flagged_rules`다.

`L3-12` 업무범위 집중 검토는 review-only access/work-scope signal이다. 사용자-year 점수는 `review_score_series`와 `row_annotations.review_score`로만 PHASE1 점수체계에 약하게 유입되며, `details["L3-12"]`와 `flagged_rules`에는 확정 위반처럼 적재하지 않는다.

관계사 거래는 별도 보정 원칙을 둔다. `L3-03` 단독은 관계사 거래 모집단 신호라 row-level `anomaly_score`에 낮게만 반영한다. 별도 `IntercompanyMatcher` 결과로 `IC01/IC02/IC03` 대사 예외가 제공되면 `intercompany_exception_score`를 기록하고, `IC02` 또는 `IC03` 단독은 최소 Low, `IC01` 또는 2개 이상 IC 예외 결합은 최소 Medium floor를 적용한다.

Case priority 기본식:

```text
0.25 * control_score
+ 0.25 * amount_score
+ 0.15 * duplicate_or_outflow_score
+ 0.15 * logic_score
+ 0.10 * timing_score
+ 0.10 * behavior_score
```

`duplicate_or_outflow_score`는 L2-01/L2-02/L2-03/L2-05 같은 지급·중복·역분개 신호가 case priority에 직접 반영되도록 하는 축이다. `timing_score`는 L3-04/L3-07/L3-11 같은 결산·cutoff 신호가 case priority에 직접 반영되도록 하는 축이다. `L3-11`은 raw cutoff score `>=0.60`이면 Medium floor, raw score `>=0.30`이면서 `L4-01`과 결합하면 High floor를 적용한다.

그 뒤 `topside_bonus`, `batch_combo_bonus`, `work_scope_combo_score`, `weak_evidence_bonus` 같은 보정 신호를 적용한다. `L3-12` 단독은 High floor를 만들지 않지만, 독립 보강 evidence group이 2개 붙으면 Medium, 3개 이상 붙으면 High floor로 승격한다. `priority_floors`는 심각한 통제 위반이 보조 룰 부족 때문에 묻히지 않게 최소 priority를 보장한다. 기본 floor는 `L1-05` immediate/escalated 자기승인, `L1-04` 승인한도 초과, `L1-06` immediate SoD, `L1-07` immediate 승인 생략에 적용된다. `L4-02`, `D01`, `D02`는 전표 1건의 transaction queue 점수가 아니라 Account / Process Queue에서 다루는 macro finding으로 분리한다.

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
| 1b    | detection (32개 룰) + DuckDB + pipeline                   | 미착수 |
| 1c    | Streamlit 대시보드 3탭                                    | 미착수 |
| 2a    | ML 전처리 파이프라인 (pipeline_builder, cv_selector, VAE) | 미착수 |
| 2b    | ML 탐지기 (SupervisedDetector, VAEDetector, SHAP)         | 미착수 |
| 2c    | 추가 탐지기 (Duplicate, Timeseries, Intercompany)         | 미착수 |
| 3     | 상용 LLM API + Text-to-SQL + NLP + Graph + Export         | 미착수 |

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
seed 고정 재현 가능, 132종 anomaly 유형 내장, PCAOB/ISA/COSO/SOX 감사기준 코드 레벨 구현.
2026-04-14 재생성: 라벨-entry 동기화 + reference MCAR 근본 수정 반영.

- **법인**: C001 본사(서울) + C002 울산공장 + C003 천안공장, 전체 KRW
- **규모**: 319,204건 전표 / 1,107,720 라인아이템 (2022년 1월~2024년 12월, 3개년)
- **승인**: 한국 중견 제조업 6단계 전결규정 (자동 → 담당자 → 팀장 → 본부장 → CFO → 이사회)
- **사용자**: 1,365명 사용 / 1,422명 마스터 (5개 페르소나), SoD 위반 3.32%
- **이상 주입**: fraud 1.96% (15종) + anomaly 2.60% (46종) + anomaly_labels.csv 8,337건 (5 카테고리)
- **시간 패턴**: 한국 근무 문화 반영 (오전 피크 29.7%, 점심 감소, 퇴근 러시 21.4%, 심야 1.5%)

```
data/journal/
  primary/datasynth/    # 메인: 합성 전표 (fraud/anomaly 개발 검증 라벨 + labels.csv)
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
