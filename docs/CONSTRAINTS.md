# 프로젝트 제약사항 및 범위 정의

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> **PHASE1/PHASE2 경계 원칙**: PHASE1은 rule-based audit exception queue이고 PHASE2 MVP는 **VAE 기반 비지도 anomaly ranking**이다. PHASE2 MVP는 라벨 없는 전체 모집단에서 재현 가능한 이상 점수와 검토 우선순위를 산출하며, supervised fraud probability나 hybrid/sequence benchmark를 기본 promotion surface에 포함하지 않는다.

> **🔄 PHASE3 v2 경계 원칙 (2026-05-14) ✅ 구현 완료 (Sprint A~G, 2026-05-15)**: PHASE3 단일 목표는 **Review Queue Narrator** — PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타를 LLM이 읽고 (a) 후보 Top-N 재정렬, (b) 의심 근거 서술(rule_id/feature_id/journal_id 인용 필수), (c) 감사인 다음 행동 제안. **새 fraud 패턴 발견·자유 가설 생성·룰 자동 추가는 비범위**. Text-to-SQL/Vanna/Export/Chat UI/룰 피드백 루프 등은 구현 보존, 신규 작업 없음. 단일 출처: [PHASE3_REVIEW_NARRATOR_SPEC.md](PHASE3_REVIEW_NARRATOR_SPEC.md), [DECISION.md §D041](DECISION.md), 완료 리포트 [completed/phase3_review_narrator_completion.md](completed/phase3_review_narrator_completion.md).

이 문서는 프로젝트에서 **의도적으로 구현하지 않는 영역**과 그 사유를 기록한다.

---

> 최신 PHASE1 운영 기준: PHASE1은 정답 라벨을 맞히거나 부정을 확정하는 단계가 아니라, 규칙 위반·정책 위반·이상 징후 후보를 전수로 올리는 1차 스크리닝 계층이다. PHASE1 raw hit는 정상 예외와 약한 신호를 포함할 수 있으며, 중요성·증거 강도·case priority·고객사 예외 정책·조합 신호를 기준으로 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보로 2차 분류한다. 현행 L1~L4 구현 룰 수는 32개이며, L3-12 업무범위 집중 검토는 L1-06 direct SoD와 분리된 review signal이다.

---

## PHASE1의 명시적 한계

PHASE1은 전체 전표 모집단을 빠르게 스크리닝하는 rule-based audit exception queue다. 따라서 PHASE1 결과는 부정 확정, 악의적 조작 정답 맞히기, 전체 Top ranking 보장을 목적으로 해석하지 않는다.

| 구분 | 명확한 한계 | 운영 기준 |
|---|---|---|
| 부정 확정 | PHASE1 점수는 `fraud` 여부를 확정하지 않는다. | 감사인이 먼저 볼 후보와 우선순위로만 해석한다. |
| 악의적 조작 ranking | 악의적 조작 문서가 전체 Top100 또는 High risk에 반드시 들어온다는 보장은 없다. | 강한 독립 증거가 없으면 조작 truth도 Low/Medium에 남을 수 있다. |
| 약한 context 신호 | 수기 입력, 결산말, 휴일, 업무범위 집중, 관계사, 문서흐름 누락, 승인 matrix gap은 정상 업무에서도 자주 발생한다. | 단독 High floor 또는 fraud floor로 쓰지 않고 다른 증거와 조합될 때만 승격한다. |
| rule hit 해석 | rule hit는 오류나 부정의 직접 증거가 아니다. | 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 분리해서 본다. |
| 전체 Top 지표 | 전체 Top100 truth 비율만으로 PHASE1 품질을 판단하지 않는다. | topic별 High/Top, 전체 coverage, contract noise cap, 미포착 사유를 함께 본다. |
| DataSynth truth | synthetic manipulation truth는 개발 검증 보조값이다. | label, scenario, id, 특정 생성 패턴에 맞춰 점수를 튜닝하지 않는다. |
| 독립 evidence | master data, document flows, intercompany matched pairs, approval matrix 조인도 신호가 넓으면 ranking 개선에 실패할 수 있다. | High 승격 전 정상 업무 맥락과 contract noise 증가 여부를 확인한다. |

### PHASE1과 PHASE2의 경계

현재 구현에서 PHASE2 inference는 PHASE1에서 걸린 case subset이 아니라 `featured_df` 전체에 대해 `phase2_only` ML detection을 수행한다. PHASE1은 PHASE2 입력을 잘라내는 gate가 아니며, PHASE1 case는 PHASE2 overlay와 감사 검토 화면의 문맥으로 사용한다. Phase2 MVP는 VAE 기반 비지도 anomaly ranking으로 제한하며, 이 점수는 부정 확률이나 지도학습 검증 지표가 아니라 감사 검토 우선순위 산출용 이상 점수로 해석한다.

따라서 악의적 조작 우선순위는 PHASE1 topic score에 억지로 fitting하지 않고, 전체 모집단 기반 PHASE2 ML/통계 이상탐지와 PHASE3 감사 판단에서 보강한다.

---

## PHASE1 CI KPI 가드 정책 (3-Layer 구조)

PHASE1 회귀를 자동 감시하는 CI 게이트는 **3계층**으로 분리한다. 단일 출처: [tests/phase1_rulebase/kpi_baseline.json](../tests/phase1_rulebase/kpi_baseline.json), [tests/phase1_rulebase/nightly_kpi_guard.py](../tests/phase1_rulebase/nightly_kpi_guard.py), [.github/workflows/phase1-kpi-guard.yml](../.github/workflows/phase1-kpi-guard.yml).

### 계층 정의

| Layer | 의미 | 모드 | PR 차단 | baseline 기반 |
|-------|------|------|---------|---------------|
| A 도메인 정합성 | 회계 실무·감사기준서·룰 계약 정합 | HARD FAIL | ✅ 차단 | 절대값 또는 0 |
| B 운영 부하 | review queue 운영 가능 규모·실행 시간·band 분포 | HARD FAIL | ✅ 차단 | 절대값 또는 ±50% |
| C truth 회귀 방지선 | manipulation·contract truth recall 회귀 감지 | SOFT WARN | ❌ 알림만 | baseline × 70% 비율 |

### Layer A (도메인 정합성, HARD FAIL)

- **A1**: `light_seeder` 표식 케이스 = 0 (rule_detail_metadata.py §9.1 light_seeder audit 2026-05-14)
- **A2**: contract_v2 HIGH 행 비율 ≤ 1% (semantic-clean noise 폭증 = fitting 의심)
- **A3**: contract_v2 strict rule_truth 과탐 = 0 AND 미탐 = 0 (DETECTION_RESULTS_CONTRACT_V2 A축)
- **A4**: normal accounting 300건 sample false positive ≤ 5% (fixture 준비 후 활성화)
- **A5**: 정책 floor 충돌 없음 (RISK_THRESHOLDS vs `_apply_policy_risk_floors` 정합)
- **A6**: contract_v2 master/flow gap baseline ± 10% (approval_matrix_gap_rows / document_flow_orphan_rows)

### A4 normal sample fixture 정책

- `data/journal/test_normal_sample/normal_sample_300.csv`는 정상 운영 false positive 가드용 고정 샘플이다.
- fixture 갱신은 `datasynth_contract_v2` generator 변경 시에만 수행하며, `random_state=20260515`를 고정한다.
- 샘플은 모든 contract_v2 `rule_truth_*.csv`, sidecar manifest의 intentional fixture 문서, manipulation_v2 `manipulated_entry_truth.csv`의 `document_id`와 disjoint여야 한다.
- `business_process`와 `fiscal_year` 분포는 eligible 모집단 비율에 맞춰 stratified sampling 하며, PHASE1 detector 실행 결과인 `risk_level`을 포함한다.
- fixture 추출 절차는 A4 활성화 작업의 단계 1~4, 즉 truth/sidecar 제외 집합 구성, stratified sampling, PHASE1 detector 실행, 300행·truth disjoint·HIGH 비율·random_state 재현성 검증을 재현할 수 있어야 한다.

### Layer B (운영 부하, HARD FAIL)

- **B1**: case 수 ≤ 13,000 (현행 manipulation_v2 11,116 / contract_v2 7,640)
- **B2**: case builder 실행 시간 ≤ 600초 (현행 manipulation_v2 99.7s / contract_v2 68.2s)
- **B3**: priority_band 분포 high ≤ 5% / medium 20~40% / low 55~75%
- **B4**: 정책 floor 적용 행 비율 baseline ± 50% (baseline 측정 후 활성화)

### Layer C (truth 회귀 방지선, SOFT WARN — 절대 차단 안 함)

- **C1**: manipulation 포착률 ≥ 99% (절대값 회귀만, 향상 강제 안 함)
- **C2**: priority_band high truth ≥ baseline × 70% (=193, baseline 276)
- **C3**: Top500 truth ≥ baseline × 70% (=213, baseline 305)
- **C4**: 시나리오 expected topic 100% 진입 ≥ baseline - 1 (=4 / 5 baseline)
- **C5**: contract_v2 truth row Medium+ recall ≥ baseline × 70% (=11.025%, baseline 15.75%)

### Layer C SOFT WARN 누적 대응 절차

Layer C는 PR을 차단하지 않는다. 다만 같은 회귀가 누적되면 PHASE1 review queue의 미탐 위험이 방치될 수 있으므로 다음 절차를 따른다.

| 누적 상태 | 처리 |
|---|---|
| SOFT WARN 1회 | PR에서는 코멘트만 남기고 자동 처리한다. 머지는 차단하지 않는다. |
| SOFT WARN 3회 누적 (3주 연속) | GitHub issue를 자동 생성한다. label은 `kpi-guard`, `phase1`, `soft-warn`을 사용한다. |
| SOFT WARN 6회 누적 (6주 연속) | baseline 갱신 PR을 의무화하거나, 회귀 원인 분석 문서를 `docs/debugging.md` 또는 별도 debugging artifact로 남긴다. |
| 회귀 원인 분석에서 fitting 위험 발견 | 해당 변경은 롤백하거나 scoring/rule 변경을 제거한다. truth recall 개선만을 목적으로 한 baseline 갱신은 금지한다. |

누적 카운터는 CI에서 `artifacts/_kpi_guard_softwarn_history.json`에 기록한다. PR 실행은 "1회 코멘트" 경로로만 다루고, 3회/6회 누적 issue는 `main` push, weekly cron, 수동 dispatch처럼 기준 브랜치 상태를 검증하는 실행에서 생성한다.

#### milestones 초기화 정책 (streak-reset)

누적 카운터는 **streak 기반**으로 동작한다. 정상 run(SOFT WARN 0건) 1회로 streak가 끊기면 `consecutive_count`와 함께 `milestones_opened` lineage도 초기화한다. 따라서 다음 누적 streak에서 다시 3회/6회에 도달하면 milestone 3/6 issue가 **재발화**된다.

| 상태 전이 | `consecutive_count` | `milestones_opened` | 결과 |
|---|---|---|---|
| SOFT WARN 누적 1·2회 | 1·2 | `[]` | issue 생성 안 함 |
| SOFT WARN 3회 도달 | 3 | `[3]` | milestone 3 issue 생성 |
| 4·5회 연속 | 4·5 | `[3]` | 이미 열린 milestone, issue 미생성 |
| 6회 도달 | 6 | `[3, 6]` | milestone 6 issue 생성 |
| 정상 run 1회 발생 | 0 | `[]` (초기화) | streak 종료 |
| 다시 SOFT WARN 누적 3회 | 3 | `[3]` | milestone 3 issue **재발화** |

근거: 회귀 감시는 "현재 진행 중인 streak가 의무 대응 임계에 도달했는가"를 기준으로 한다. 라이프타임 1회 정책으로 두면 한 번 close된 후 같은 회귀가 재발해도 재발화 trigger가 없어 사각이 발생한다. 정상 run으로 streak가 끊긴 사실은 직전 회귀가 완화되었다는 신호이므로, 그 이후의 재누적은 별개 사건으로 본다.

단일 출처: `.github/workflows/phase1-kpi-guard.yml` "Update Layer C soft warn history" step의 `milestonesOpened` 분기.

### baseline 갱신 절차

1. `tests/phase1_rulebase/kpi_baseline.json` 직접 편집 PR 생성.
2. PR description에 **변경 사유 + 도메인 정당성**(회계 실무 / 감사기준서 매핑) 명시 의무.
3. **금지 사유**: "truth recall 향상을 위해", "Top10 truth 늘리기 위해", "high band truth 회복을 위해" — truth recall을 직접 사유로 baseline 갱신 금지.
4. Layer A/B baseline 갱신은 reviewer 1명 이상 검토 의무. Layer C baseline 갱신은 도메인 사유 PR 머지의 부수효과로만 자연 갱신.
5. baseline 갱신 후 회귀 테스트: `uv run pytest tests/phase1_rulebase/nightly_kpi_guard.py -v`.

### CI 트리거

- **PR (main / develop)**: Layer A/B HARD = 머지 차단, Layer C SOFT WARN = PR 코멘트만.
- **main push (post-merge)**: 회귀 발생 시 GitHub issue 자동 생성 (label: `kpi-guard`, `regression`, `phase1`).
- **weekly cron** (월요일 09:00 UTC): fixture freshness 7일 초과 시 회귀 감시.

### 금지 가드 (추가 시도 시 즉시 반려)

- ❌ "truth recall ≥ X" 형태 절대값 임계 (예: "Top10 truth ≥ 50", "high truth ≥ 200")
- ❌ "expected_topic_docs ≥ baseline + Δ" 형태 향상 강제
- ❌ "PHASE1 score 가중치 조정으로 truth recall 회복" PR — PHASE2 이관

> **원칙**: PHASE1 향상은 도메인 정합성을 통해 자연 발생시키고, truth recall은 부수효과(회귀 방지선)로만 측정한다. CLAUDE.md PHASE1 역할 원칙과 정합.

---

## PDF / HWP 파일 데이터 추출 미지원

### 결정
PDF, HWP 파일로부터 전표 데이터를 추출하는 기능은 이 프로젝트 범위에 포함하지 않는다.
`file_validator`에서 해당 확장자를 감지하면 사유와 함께 거부한다.

### 사유

1. **프로젝트 목표와 불일치**
   - 이 프로젝트의 목표는 **구조화된 전표 데이터의 이상탐지** + **LLM 기반 추론(상용 API)**이다.
   - PDF/HWP에서 테이블을 추출하는 것은 문서 AI(OCR, 레이아웃 분석) 영역으로, 감사 이상탐지와는 별개 기술 스택이다.

2. **로컬 AI 시스템의 한계**
   - 이 시스템은 로컬 환경(RTX 3070 Ti 8GB, RAM 16GB)에서 동작한다.
   - PDF/HWP 파싱 + OCR은 추가 모델과 상당한 리소스를 요구하며, 로컬 LLM과 동시 운영이 비현실적이다.

3. **별도 프로젝트로 분리가 적절**
   - 데이터 추출(ETL)과 데이터 분석(이상탐지)은 관심사가 다르다.
   - PDF/HWP → 구조화 데이터 변환은 별도 ETL 파이프라인이나 외부 도구(예: tabula, pdfplumber, 한글 라이브러리)로 선행 처리 후, 그 결과물(CSV/Excel)을 이 시스템에 입력하는 것이 올바른 워크플로우다.

### 지원하는 입력 형식

| 카테고리   | 확장자                         | 비고                   |
|-----------|-------------------------------|------------------------|
| Excel     | `.xlsx`, `.xls`, `.xlsb`      | ERP 내보내기 표준       |
| Text      | `.csv`, `.tsv`, `.txt`, `.dat` | DB 덤프, 구분자 기반    |
| Columnar  | `.parquet`                     | 데이터 엔지니어링 표준  |

---

## Streamlit 대시보드 보안

### 현황
모든 구성 요소(LLM, DB, 대시보드)가 로컬에서 실행되므로 외부 클라우드 의존성이 없다.
Streamlit도 `localhost`에서 구동하며, 데이터가 외부로 전송되지 않는다.

### 취약점
- Streamlit은 기본적으로 인증 없이 HTTP 서버를 열기 때문에, **포트 번호만 알면 같은 네트워크의 누구나 접속 가능**하다.
- 공유 네트워크(사내망, 공용 Wi-Fi 등) 환경에서는 민감한 감사 데이터가 무인가 사용자에게 노출될 수 있다.

### 대응 계획
- **단기**: 방화벽 규칙으로 해당 포트의 외부 접근을 차단하여 운용
- **중장기**: Streamlit 로그인 기능 구현 (Phase 1c 이후)
  - `streamlit-authenticator` 또는 자체 세션 기반 인증 도입
  - 사용자별 접근 권한 분리 (읽기 전용 / 관리자)

---

## 하드웨어 제약과 확장 가능성

### 현재 환경

| 항목 | 사양                          |
|------|-------------------------------|
| GPU  | NVIDIA RTX 3070 Ti (VRAM 8GB) |
| RAM  | 16GB                          |
| OS   | Windows 11 Pro                |

### 현재 제약
- VRAM 8GB 기준으로 ML 모델(VAE, XGBoost 등)은 충분히 동작하나, 로컬 LLM과 동시 운영은 비현실적이다.
- 8B 양자화 로컬 LLM은 한국어 회계 도메인 이해력이 부족하여, Text-to-SQL 정확도가 실무 수준에 미달한다.
- 대규모 전표 데이터(수백만 건) 처리 시 RAM 병목이 발생할 수 있다.

### 하이브리드 아키텍처 결정 (2026-04-09)

로컬 LLM(Ollama + Qwen3-8B)의 한계를 인지하고, **로컬 ML + 상용 API LLM 하이브리드** 구조로 전환했다.

| 영역 | 실행 환경 | 근거 |
|------|----------|------|
| 룰 기반 탐지 (Phase 1) | 로컬 | 원본 ERP 데이터 보안 |
| ML/DL 탐지 (Phase 2) | 로컬 (GPU) | VAE ~1-2GB VRAM, XGBoost CPU 기반. 현재 환경으로 충분 |
| LLM 추론 (Phase 3) | 상용 API (OpenAI gpt-5.4 / gpt-5.4-mini 2티어) | Review Queue Narrator 한정. Text-to-SQL은 v2 비범위 (historical 사유 유지). |
| NLP 형태소 분석 | 로컬 (kiwipiepy) | 경량, CPU 기반 |

PHASE1 로컬 실행의 의미는 원본 ERP 데이터를 외부로 내보내지 않고, 전체 모집단에서 규칙 위반 후보를 먼저 넓게 확보한다는 것이다. 이 단계의 결과는 최종 부정 판정이 아니며, PHASE2/PHASE3 또는 감사인 검토에서 중요성·예외 정책·업무 맥락으로 재분류한다.

### 고사양 서버 전환 시 개선 사항

| 영역             | 현재 (RTX 3070 Ti / 16GB)        | 서버 전환 시                                      |
|-----------------|----------------------------------|--------------------------------------------------|
| ML 모델         | VAE(~2GB) + XGBoost(CPU)        | 대형 모델, 배치 병렬 학습                          |
| 동시 처리       | ML 학습 중 대시보드 응답 지연     | GPU/CPU 분리로 병렬 처리 원활                      |
| 데이터 규모     | 수십만 건                         | 수백만~수천만 건 처리 가능                          |
| LLM             | 상용 API                         | 자체 호스팅 LLM으로 전환 가능 (프라이빗 엔드포인트) |

### 설계 원칙
- LLM 백엔드는 `config/settings.py`에서 설정값으로 관리하므로, API 제공자 교체 시 설정 변경만으로 적용 가능하다.
- 하드웨어 의존적 로직을 코드에 하드코딩하지 않는다.

---

## 데이터 비식별화 (Anonymization)

### 결정
비식별화 모듈은 현재 프로젝트 범위에 포함하지 않는다. 단, 상용 API 연동 시 필수적인 요소로 인지하고 있다.

### 배경
하이브리드 아키텍처에서 상용 API로 전송하는 데이터에 대한 비식별화가 필요하다.
현재 프로젝트는 포트폴리오 목적이므로, API에 전달하는 데이터는 **위험 스코어·통계 지표·룰 트리거 결과** 등 비식별 지표로 한정한다.

### 실무 투입 시 필요한 비식별화 레이어

| 항목 | 내용 |
|------|------|
| 고유명사 제거 | 적요 텍스트에서 거래처명·임직원명 등 NER 기반 마스킹 |
| 금액 범위화 | 실제 금액 → 범위 변환 (5.2억 → "5억대") |
| 식별자 해싱 | 계좌번호, 사업자번호 등 단방향 해시 처리 |
| k-익명성 검증 | 조합으로 역추적 불가능한지 검증 |

### API 전송 허용/금지 기준

| 구분 | 예시 | 전송 가부 |
|------|------|----------|
| 허용 | 위험 스코어(0.73), 통계 지표, 룰 트리거 결과, 비식별 패턴 | O |
| 금지 | 거래처명, 계좌번호, 사업자번호, 적요 원문, 임직원 정보 | X |

### 교차 참조
- 하이브리드 아키텍처: 본 문서 §하드웨어 제약과 확장 가능성
- 대시보드 보안: 본 문서 §Streamlit 대시보드 보안

---

## 전처리-탐지 갭 대응 전략

### 배경

전처리(preprocessing)와 탐지(detection/ML)는 상호 의존적이다.
모델이 필요로 하는 전처리가 아직 구현되지 않았거나,
사용자 데이터가 기존 파이프라인에 없는 새로운 전처리/피처를 요구할 수 있다.

### 해결 전략: 하이브리드 (범용 피처 + 모델 전용 변환)

| 갭 유형              | 해결 위치                                 | 판단 기준                                  | 예시                                  |
|:---------------------|:-----------------------------------------|:------------------------------------------|:--------------------------------------|
| **범용 피처**        | `src/feature/` 모듈 추가                  | DataFrame에 컬럼으로 존재해야 하는 값      | 시퀀스 임베딩, 계정 유사도             |
| **모델 전용 변환**   | `src/preprocessing/transformers.py`       | 특정 Pipeline 내부에서만 필요한 변환        | StandardScaler, SafePowerTransformer  |
| **모델별 인코딩 분기** | `src/preprocessing/pipeline_builder.py` | 동일 컬럼이 모델마다 다른 인코딩 필요       | TargetEncoder(XGB) vs OrdinalEncoder(VAE) |

**경계 기준**: "이 값이 DataFrame에 컬럼으로 존재해야 하는가?"
→ Yes면 `src/feature/`, No면 `src/preprocessing/transformers.py`.

### 사용자 데이터 특성에서 갭 발생 시 대응

사용자 데이터가 기존 18개 피처로 커버되지 않는 특성을 가질 때의 대응 단계:

| 단계   | 전략                       | 메커니즘                                                                 | 구현 시점      |
|:-------|:--------------------------|:-------------------------------------------------------------------------|:--------------|
| **즉시** | Graceful Degradation    | 필수 컬럼 없으면 해당 피처 카테고리 스킵 + warning 반환                    | Phase 1a ✅   |
| **즉시** | EDA 프로파일링            | 데이터 특성(분포, 카디널리티, 결측률 등) 자동 탐지 → 리포트                | Phase 1a ✅   |
| **중기** | EDA warning 구체화        | "이 컬럼이 존재하지만 파이프라인에서 활용되지 않음" 대시보드 알림          | Phase 1c      |
| **중기** | audit_rules.yaml 확장    | 커스텀 룰/피처 등록을 위한 설정 인터페이스                                | Phase 2       |
| **장기** | LLM 전처리 옵션 추천     | EDAProfile(JSON) → LLM → 기존 전처리 옵션 중 최적 조합 추천 (Phase 3 v2 **비범위**, WU-29 구현물 보존) | historical    |
| **장기** | LLM 룰 파라미터 제안     | 새 데이터 샘플링 → 고객사 고유 패턴 발견 → audit_rules.yaml 추가 제안 (Phase 3 v2 **비범위**, WU-30 구현물 보존) | historical    |

### 범위 외 명시

LLM 전처리 제안(historical Phase 3 v1)은 **기존 옵션 중 선택을 추천**하는 수준이다. Phase 3 v2 rescope 후 이 기능은 **비범위(구현 보존)**다. Phase 3 v2 목표는 [Review Queue Narrator](PHASE3_REVIEW_NARRATOR_SPEC.md) 단일이다.
"미지의 데이터 특성에 대한 새로운 전처리 Pipeline 로직 자체를 LLM이 생성"하는 것은
코드 생성 영역으로, 본 프로젝트 범위에 포함하지 않는다.

새로운 데이터 특성(다통화, 계정 계층구조, 다국어 텍스트 등)에 대한 피처/전처리 추가는
**개발자가 모듈을 확장**하는 방식으로 대응하며, 확장 구조는 다음과 같이 표준화되어 있다:

- 피처 추가: `src/feature/`에 새 모듈 작성 → `engine.py`에 카테고리 등록
- 전처리 추가: `transformers.py`에 sklearn-compatible Transformer 작성
- 탐지 룰 추가: `BaseDetector(ABC)` 상속 → `detect() -> DetectionResult` 구현

### 교차 참조

- 전처리 전략 상세: [03a-preprocessing.md](pre-plan/03a-preprocessing.md) §닭-달걀 해결
- LLM 전처리 추천: [03a-preprocessing.md](pre-plan/03a-preprocessing.md) §③ LLM 전처리 제안
- LLM 룰 피드백 루프: [08-llm.md](pre-plan/08-llm.md) §Audit Rules 피드백 루프

---

## 감사기준서 갭 분석: 불필요 항목 (5건)

전수 검사 프로젝트 특성상 구현이 불필요한 항목.
출처: [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) §4

| #   | 항목                              | 제외 사유                                                                     |
|:----|:---------------------------------|:-----------------------------------------------------------------------------|
| 1-3 | 감사기준서 530호 (표본추출)         | 전수 검사 프로젝트이므로 표본추출 자체가 불필요                                  |
| 3-2 | 위험기반 표본 선정                  | 전수 검사. 단, 대시보드에서 증빙 대조 대상 우선순위 제공 (Phase 1c)               |
| 3-7 | 감사조서 문서화                     | 감사인 산출물 영역. CAATs 역할은 탐지 결과 제공까지                              |
| 5-3 | 530호 참조 출처                    | 전수조사이므로 해당 없음                                                       |
| 5-10| 내회관 Q&A 실무자료                | 통제테스트 표본수 관련 → 전수조사이므로 해당 없음                                |

---

## 실무 경험 부재에 따른 파라미터 한계

### 현황

이 프로젝트는 감사 실무 경험 없이, 감사기준서(PCAOB AS 2401, ISA 240)와 공개 자료를 기반으로 설계되었다.
따라서 다음 항목들의 구체적인 수치가 실제 감사 현장과 다를 수 있다.

| 영역                | 예시                                                    | 현재 근거                       |
|:--------------------|:-------------------------------------------------------|:-------------------------------|
| 탐지 룰 가중치       | 금액 이상 vs 시간 이상의 상대적 중요도                    | 감사기준서 위험 분류 + 학술 문헌  |
| 임계값(threshold)    | 심야시간 정의(22:00~06:00), 금액 편차 배수(3σ)           | 통계적 관례 + 참고 논문          |
| PHASE1 case priority 기준 | 복합 점수와 증거 조합을 어떤 경우에 "고위험 후보"로 올릴 것인지. 최종 부정 판정 기준이 아니라 감사 검토 우선순위 기준 | MindBridge/KPMG Clara 공개 사례 |
| 배정 알고리즘 로직   | 승인한도 초과·분할 입력·주말 전표 등의 위험 등급 배정       | 도메인 문헌 + 합리적 추정        |

### 설계 대응

모든 파라미터는 **외부 설정 파일(`config/audit_rules.yaml`, `config/settings.py`)에서 관리**한다.
코드에 매직 넘버를 하드코딩하지 않으므로, 실무 투입 시 설정값 조정만으로 현장에 맞출 수 있다.

- 가중치·임계값: `audit_rules.yaml`의 룰별 `weight`, `threshold` 필드
- 시간대 정의: `settings.py`의 `NIGHT_START`, `NIGHT_END`
- 점수 등급 구간: `audit_rules.yaml`의 `risk_levels` 섹션

실무 데이터로 검증한 뒤 파라미터를 튜닝하면, 코드 수정 없이 탐지 정밀도를 현장 수준으로 조정할 수 있다.

---

## 컬럼 매핑 정확도와 회사별 프로파일 전략

### 현황

`keywords.yaml`에 SAP ACDOCA, 더존 iCUBE, Oracle EBS, 한국 일반 회계 용어 등
주요 ERP 별칭을 등록하여 exact match → fuzzy match 2단계로 자동 매핑한다.
그러나 실무에서는 동일 ERP라도 회사마다 커스텀 컬럼명을 사용하는 경우가 많다.

### 한계

| 상황                                  | 현재 대응                              |
|:--------------------------------------|:--------------------------------------|
| keywords.yaml에 등록된 별칭           | exact match → 자동 매핑                |
| 유사한 별칭 (fuzzy 40%+)              | fuzzy match → 사용자 확인              |
| 완전히 생소한 컬럼명 (fuzzy 40% 미만) | 수동 매핑 필요                         |
| 동일 ERP, 동일 회사의 반복 업로드      | 프로파일 자동 재사용                   |

### 회사별 매핑 프로파일 (Company-Centric 재설계로 구현 예정)

> **상태 변경 (2026-04-02)**: "향후 개선"에서 **RC-5 태스크로 확정**. [NEW_TASKS.MD](NEW_TASKS.MD) 참조.

현재 매핑 프로파일은 원본 컬럼명 집합의 SHA-256 해시로 식별된다.
Company-Centric 재설계에서 이 프로파일을 **회사별 디렉토리(`data/companies/{id}/profiles/`)**로 격리한다.

- 감사법인이 고객사 A의 SAP 파일을 처음 매핑하면 회사 프로파일 디렉토리에 저장
- 다음 분기 동일 고객사 파일 업로드 시 자동 적용 (수동 매핑 0건)
- 사용자가 수동 매핑한 컬럼-별칭 쌍은 회사 `keywords.yaml`에 자동 학습
- 회사 설정 export/import (ZIP)로 팀 간 공유 지원

---

## 실제 회사 데이터 부재

### 현황

이 프로젝트의 모든 개발·검증은 **DataSynth(Rust 기반 합성 데이터 생성기)로 생성한 데이터만으로 수행**되었다.
실제 기업의 회계 원장 데이터를 확보하지 못했으며, 확보 가능한 시점도 미정이다.

### 현재까지 한 것

DataSynth로 가능한 범위 내에서 최대한 현실적인 검증 환경을 구축했다.

| 영역                | 구현 현황                                                         |
|:--------------------|:----------------------------------------------------------------|
| 탐지 룰             | L1/L2/L3/L4 32개 룰 구현 + DataSynth rule truth/sidecar 데이터로 coverage, precision/recall, review population 분리 측정 |
| 컬럼 매핑           | 3단계 파이프라인(exact → fuzzy → pattern) + keywords.yaml 536개 별칭 |
| 변환 레이어         | 차변/대변 3가지 형식(Case A/B/C) 처리                             |
| 매핑 프로파일       | 회사별 저장/재사용/키워드 자동 학습 메커니즘                       |
| ML 파이프라인       | VAE 비지도 경로 중심, IF/XGBoost는 Phase2 기본 밖의 기존/확장 후보 |
| 데이터 품질         | Pandera 3단계 검증(구조 → 회계 → 통계)                           |

### 검증되지 않은 영역

실제 회사 데이터가 없어 다음 항목은 **설계만 완료, 실전 검증 미수행** 상태이다.

| 영역                              | 미검증 내용                                                      |
|:----------------------------------|:----------------------------------------------------------------|
| 컬럼 매핑 실효성                   | 실제 ERP 내보내기 파일의 컬럼명이 fuzzy 매칭으로 잡히는지         |
| 변환 레이어 Case B/C               | amount + dc_indicator 분리, 양수/음수 단일 금액 분리 실동작       |
| 탐지 룰 임계값                     | 실제 거래 분포에서 false positive/negative 비율                  |
| ML 모델 일반화                     | 합성 분포 → 실제 분포 전이 시 성능 하락 정도                     |
| 대규모 데이터 성능                  | 수백만 건 원장에서의 파이프라인 처리 시간                         |
| 회사별 프로파일 재사용              | 동일 ERP 다른 회사 간 프로파일 호환성                            |

### 설계 대응

실제 데이터 투입 시 코드 변경 없이 대응할 수 있도록 다음을 사전 확보했다.

- **파라미터 외부화**: 임계값·가중치·키워드는 전부 YAML 설정 파일에서 관리
- **Graceful Degradation**: 필수 컬럼 부재 시 해당 룰 skip + warning 반환
- **회사별 격리**: `data/companies/{id}/` 구조로 매핑 프로파일·모델·DB 독립 관리
- **키워드 학습**: 사용자 수동 매핑 → 회사 keywords.yaml 자동 반영 → 재업로드 시 자동 매핑

### 향후 계획

실제 데이터 확보 시 다음 순서로 검증한다.

1. 컬럼 매핑 테스트 — 실제 ERP 파일로 매핑 성공률 측정, keywords.yaml 보강
2. 탐지 룰 파라미터 튜닝 — 실제 분포 기반 임계값 조정
3. ML 모델 재학습 — 비지도학습 모델을 실제 정상 분포로 재학습
4. 지도학습 활성화 — 감사인 라벨링 데이터 확보 시 fine-tuning

### 교차 참조

- 컬럼 매핑 전략: 본 문서 §컬럼 매핑 정확도와 회사별 프로파일 전략
- ML 학습 전략: 본 문서 §ML 학습 전략: 비지도학습 중심 + 지도학습 프레임워크
- 실무 경험 부재: 본 문서 §실무 경험 부재에 따른 파라미터 한계
- DataSynth 품질: [datasynth.md](datasynth.md)

---

## ML 학습 전략: 비지도학습 중심 + 지도학습 프레임워크

### 배경

이 프로젝트의 학습 데이터는 DataSynth(Rust 기반 합성 데이터 생성기)가 룰 기반으로 생성한 1.1M건 전표이다.
합성 데이터의 이상치는 사전 정의된 규칙(금액 증폭, 주말 전기, 자기승인 등)으로 주입되며,
이는 지도학습에서 **순환 학습(Circular Learning)** 문제를 야기한다.

### 순환 학습 문제

```
DataSynth 룰 기반 이상치 주입 → 지도학습 모델이 해당 패턴 학습
→ 학습 결과가 Phase 1 룰의 재발견에 그침 → ML 부가가치 제한
```

- DataSynth의 이상치는 Phase 1 룰과 동일한 규칙으로 생성된다.
- 지도학습 모델(XGBoost, FT-Transformer 등)이 이 데이터로 학습하면, 이미 룰이 탐지하는 패턴을 재학습한다.
- **ML의 본래 가치**(룰로 정의할 수 없는 복합 패턴 탐지)는 합성 데이터에 해당 패턴이 부재하므로 발현되기 어렵다.

산업 근거:
- MindBridge, KPMG Clara 등 상용 감사 AI는 **실제 감사 데이터**로 학습한다.
- 합성 데이터로 학습한 모델을 실무 데이터에 적용하면 15~25% 성능 하락이 보고되었다 (distribution shift).
- PCAOB는 AI 도구의 감사 가능성(auditability)을 요구하며, 합성 데이터만으로 감사 결론을 내릴 수 없다.

### 현재 전략: 비지도학습 중심

| 접근법 | 모델 | 합성 데이터 적합도 | 근거 |
|:-------|:-----|:-----------------:|:-----|
| **비지도학습** | VAE 기반 오토인코더 | 제한적 유효 | 라벨 없이 정상 분포 이탈을 학습할 수 있으나, DataSynth 분포가 실데이터 일반화를 보장하지는 않음 |
| **지도학습** | XGBoost, FT-Transformer, BiLSTM | 중간 | 파이프라인 구축 + 프레임워크 시연 목적. 실탐지 성능은 제한적 |

비지도학습(VAE 기반 오토인코더)은 **정상 거래의 분포**를 학습하여 이탈을 탐지한다.
DataSynth의 정상 거래 98%가 현실적인 분포(LogNormal 금액, 시간대 패턴, 계정 조합)를 따르므로,
개발 단계의 smoke test와 contract 검증에는 유용하다. 다만 합성 데이터 기반 결과는 실데이터 일반화 근거가 아니며,
고객사 데이터나 감사인 라벨이 들어오기 전까지는 anomaly ranking proxy로만 해석한다.

### Phase2 기본 모델 제약: VAE + 비지도 우선

2026-05-08 기준 Phase2 기본 학습·추론·promotion surface는 **VAE 기반 비지도 오토인코더**로 제한한다.
이는 Hybrid 모델의 연구적 가치를 부정하는 결정이 아니라, 현재 입력 데이터와 검증 조건에서 운영 가능한 기본값을 좁히는 제약이다.

구현상 기존 `UnsupervisedDetector` 내부에 IsolationForest 경로가 남아 있을 수 있으나, Phase2 기본 promoted model은 VAE 기반 오토인코더 1개로 정의한다.
IsolationForest, ECOD, COPOD 등은 기본 promotion 또는 inference contract에 포함하지 않으며, 필요 시 off-by-default diagnostic으로만 다룬다.

기본 경로에서 제외하는 항목:

| 항목 | 기본 제외 사유 | 허용 조건 |
|:-----|:---------------|:----------|
| VAE + XGBoost | `is_fraud`/`is_anomaly` ground truth가 없으면 supervised target이 없다. | 감사인 라벨 또는 신뢰 가능한 ground truth 확보, group/temporal holdout 검증 |
| VAE + Transformer | 전표 데이터의 sequence contract가 아직 고정되어 있지 않다. | document/user/account/time window 단위 sequence 정의와 leakage-safe temporal validation |
| VAE + BiLSTM + Attention | 높은 accuracy 논문 수치는 class prevalence, split 방식, leakage 통제 없이는 현재 데이터 성능 근거가 아니다. | 충분한 라벨, sequence 길이, external/temporal validation, runtime budget 확보 |
| Stacking/앙상블 promotion | 라벨 없는 proxy score로 복잡한 모델을 승격하면 false confidence가 커진다. | 검증 라벨과 out-of-fold 또는 temporal validation 결과가 있는 benchmark 단계 |

현재 Phase2 CSV에는 `is_fraud`, `is_anomaly`가 없으므로 supervised/sequence/hybrid 계열은 의미 있는 학습·검증을 할 수 없다.
따라서 기본 promoted Phase2 model은 VAE 기반 비지도 오토인코더 1개로 둔다.

Hybrid 계열은 코드 전체에서 삭제하지 않는다. 단, 기본 Phase2 queue, training, inference contract, promotion에는 포함하지 않는다.
향후 라벨·sequence contract·외부 검증셋이 준비되면 다음과 같은 **off-by-default diagnostic benchmark**로만 추가한다:

- `vae_xgboost_benchmark`
- `vae_sequence_benchmark`
- `vae_transformer_benchmark`

이 benchmark 결과는 기본 promotion에 직접 반영하지 않는다.
ground truth가 있는 holdout 또는 temporal external validation에서 PR-AUC, average precision, precision@k, recall@k, false positive budget을 통과할 때만 승격 후보로 검토한다.

### Phase2 ML 기본 원칙

- split 전 oversampling/undersampling/SMOTE를 금지한다. calibration/test 분포는 실제 운영 prevalence를 유지한다.
- preprocessing fit은 train split에서만 수행한다. frequency encoding, rare grouping, scaler, imputer가 calibration/inference 정보를 보지 않게 한다.
- row random split보다 `document_id` group split을 우선한다. 날짜·회계연도가 충분하면 temporal holdout을 우선 검토한다.
- 라벨이 있을 때도 accuracy 단독 지표를 기본 품질 근거로 쓰지 않는다. PR-AUC, average precision, precision@k, recall@k, review capacity를 함께 본다.
- 비지도 오토인코더는 contaminated train에 취약하므로, high reconstruction error tail trimming 또는 self-paced weighting은 MVP 이후 optional robust setting으로 둔다.
- Phase1 룰 결과를 ML 입력으로 사용 시 Top-5 deterministic 룰(`LEAKAGE_DENY_RULES`)은 자동 제외한다.
- 현재 MVP는 train split에서 fit한 Phase2 matrix builder의 column order, frequency encoding, `has_*` indicator, output feature group mapping, schema hash를 모델 bundle에 저장하고 inference에서 재사용한다. VAE reconstruction loss는 feature group별 평균 loss와 group weight를 적용하며, group별 reconstruction score와 reliability warning은 진단 metadata로 기록한다.

### 지도학습: 파이프라인 구축 + 고객사별 확장 경로

지도학습 모델은 현재 합성 데이터의 한계를 인지한 상태에서 **Phase2 기본 경로 밖의 향후 확장 후보**로 둔다.

향후 고객사 라벨 또는 신뢰 가능한 ground truth가 확보된 뒤 검토할 항목:
- cv_selector: GridSearchCV 기반 모델 자동 선택 (LR → RF → XGBoost → LightGBM)
- SMOTE-ENN: 불균형 데이터 처리 파이프라인
- PR-AUC / F2-score: 감사 도메인에 적합한 평가 지표
- Out-of-Fold: Stacking 앙상블의 데이터 누수 방지
- Semi-supervised 인터페이스: pseudo-label + fine-tuning 경로

이 인프라는 Phase2 VAE MVP의 구현 대상이 아니며, 고객사별 라벨·holdout·temporal validation이 준비된 뒤 별도 benchmark 단계에서 검토한다.

### 고객사별 개별 학습 (Company-Centric 재설계로 인프라 확보)

> **상태 변경 (2026-04-02)**: Company-Centric 아키텍처 도입으로 모델 저장 경로 확보.
> 모델 아티팩트: `data/companies/{id}/engagements/{year}/models/`

```
[현재 MVP]                        [Company-Centric 확장]
DataSynth 합성 데이터              고객사 A 실데이터 (감사인 라벨링)
       ↓                                  ↓
비지도학습 (VAE)                   지도학습 fine-tuning 검토
지도학습은 Phase2 밖 대기          + 비지도학습 고객사 분포 재학습
       ↓                                  ↓
범용 이상 탐지                     고객사 A 맞춤 탐지 모델
                                   (engagement별 독립 저장·재사용)
```

- CompanyContext가 `model_dir` 경로를 제공하여 모델 저장/로드 자동화
- 감사법인이 고객사 전표를 수집 → 감사인 라벨링 → 지도학습 fine-tuning
- 비지도학습 모델도 고객사 정상 분포로 재학습
- 고객사별 모델은 engagement 디렉토리에 독립 저장, 다음 분기 재사용

### 교차 참조

- ML 탐지기 설계: [05a-detection-ml.md](pre-plan/05a-detection-ml.md)
- Phase 2 태스크: [TASKS.md](TASKS.md) §Phase 2
- 하드웨어 제약: 본 문서 §하드웨어 제약과 확장 가능성

### Phase 2 ML 학습 전 강제 사전 조건 (Stage 10 Audit, 2026-05-15)

PHASE2 ML 학습 sprint 시작은 다음 6 항목 모두 통과를 전제로 한다.
미통과 시 PHASE2 진행 보류 + 본 audit 재발행.

1. **deny-list (S0/S1)**: `phase2_training_service` 가 13 컬럼 deny-list 강제
   (`detection_surface_hints`, `document_id`, `document_number`, `header_text`,
   `ip_address`, `mutation_base_event_type`, `mutation_mutated_field`,
   `mutation_mutated_value`, `mutation_original_value`, `mutation_reason`,
   `mutation_type`, `reference`, `semantic_scenario_id`).
   잔여 단일 컬럼 AUROC ≥ 0.99 자동 deny (round 한도 3회).
2. **split 전략 (S2)**: 기본 = `GroupKFold(groups=document_id, n_splits=5)`.
   row-level random KFold 호출 시 ValueError. user-aware feature 도입 시
   `GroupKFold(groups=created_by)` 자동 전환. 시계열 일반화 평가 시
   `split_user_year_holdout(train=2022-2023, test=2024)` 적용.
3. **VAE contamination (S6)**: `vae_detector.train()` 입력 X 의 contamination
   비율 측정 + 학습 metadata 기록. 0.5% 초과 시 빌드 경고.
4. **BiLSTM 트랙 보류 (S7)**: `split_user_year_holdout` 적용 후 cross-user
   temporal overlap (정확 날짜 매칭 < 5%, ±7일 인접 < 20%) 통과까지 PHASE2
   본 평가에서 제외.
5. **Stacking OOF 정책 (S8)**: `_LEAKAGE_PRONE_TRACKS` =
   (ML_SUPERVISED, ML_TRANSFORMER, ML_SEQUENCE) 유지. 룰/VAE 1회 학습 +
   leakage-prone 트랙만 fold-wise OOF.
6. **S5 Top-5 룰 LEAKAGE_DENY_RULES (S5 §5)**: Phase 2 ML 42-dim 입력에서
   Top-5 deterministic 룰 (`rule_L3-02`, `rule_L3-09`, `rule_L1-03`,
   `rule_L2-03`, `rule_L1-05`) 을
   `LEAKAGE_DENY_RULES` 로 분리한다. 본 5 룰은 PHASE1 → PHASE3 narrator
   입력으로만 노출하고, Phase 2 ML 입력 행렬에서는 제거한다. Stage 5 v4
   재측정 결과 24-dim AUPRC 0.397 → Top-5 deny 후 0.056 (잔존 14.0%,
   drop ratio 0.86) 으로, 미적용 시 ML 이 사실상 deterministic Top-5 룰만
   학습하는 shortcut 위험. v3 에서 강했던 `rule_L1-09`, `rule_L2-02` 는
   v4 shortcut noise 로 약화되어 deny 에서 제외한다.

근거 audit: `docs/PHASE2_FITTING_AUDIT.md`,
`tests/datasynth_quality_gate/results/phase2_fitting_audit/SUMMARY.md`,
`artifacts/S5_phase2_input_redesign.md`.

### Phase 2 ML 평가 protocol 강제 항목 (Stage 10 Audit, 2026-05-15)

PHASE2 ML 평가 보고서는 다음 5 + 1 항목 모두 만족 시에만 머지 가능.
위반 시 평가 결과는 PHASE2 promotion gate 를 통과할 수 없다.

1. **CI 동봉 (S4 P1)**: 모든 recall/precision/F2 보고에 bootstrap 95% CI 동봉
   (`n_bootstrap=1000`, seed 명시). CI 폭 > 0.15 시 `[insignificant]` 마커 +
   점추정 비교 금지.
2. **시나리오별 truth count matrix (S4 P5)**: fold × scenario truth count
   matrix 첨부. 어떤 시나리오라도 fold 의 truth count < 5 시 fold-level
   통계 금지, 통합값만 보고. `unusual_timing_manipulation` (n=21) 은
   fold-level 보고 금지 (S4 P2).
3. **Trivial baseline 동시 보고 (S4 P4)**: 10 trivial binary feature 합산
   (`f_weekend`, `f_offhour`, `f_manual`, `f_no_approver`, `f_self_approval`,
   `f_sod_violation`, `f_no_attachment`, `f_quarter_end`, `f_year_end`,
   `f_amount_high`) 동시 측정. 시나리오별 Δrecall < 0.05 시 'fitting 의심'
   마킹.
4. **Phase 2 ML 부가가치 5 게이트 (S9)**:
   - macro AUPRC ≥ 0.4898 (S5 27룰 LR + 0.05)
   - macro F2 @ top-1% ≥ 0.118
   - embezzlement_concealment recall @ top-1% ≥ 0.495
   - circular_related_party recall @ top-1% ≥ 0.276
   - 다른 4 시나리오 recall 손실 |Δ| < 0.05
5. **macro-F2 prevalence 가중 동시 (S4 P3)**: unweighted + prevalence-weighted
   두 값 동시 보고. 격차 ≥ 0.05 시 prevalence skew 경고.
6. **Anti-shortcut cap (S5 §5 → S9 6번째 게이트)**: BLOCK 조건은
   `ensemble macro AUPRC / trivial_10feature macro AUPRC ≤ 4.0` 단일이다
   (코드 구현: `src/services/phase2_evaluation.py::evaluate_anti_shortcut_cap`,
   `ANTI_SHORTCUT_RATIO_CAP = 4.0`). 4 배 초과 시 synthetic shortcut 의심
   으로 마킹한다. **DataSynth manipulation v4 (active 2026-05-16)** 에서
   trivial floor 가 0.1292(v3) → 0.0237(v4) 로 81.7% 감소하여 cap 강도가
   약 6 배 상승했고, 현 Phase2 ensemble (`S8 A_current_policy`) 의 macro AP
   0.9369 ÷ 0.0237 ≈ 39.6 → BLOCK 유지. 잔존 RED 는 데이터 측이 아닌
   Phase2 supervised raw feature leak (모델 설계 문제) 이며, 재검증 trace 는
   `artifacts/manipulation_v4_audit_rerun_summary_20260516.md`. 보조 측정값
   (보강 진단, BLOCK 아님) 으로 Top-5 LEAKAGE_DENY_RULES (v4 재측정 결과
   `L3-02`, `L3-09`, `L1-03`, `L2-03`, `L1-05`) 제거 후 재학습한 ML 앙상블의
   macro AUPRC 잔존율 ≥ 30% AND 절대값 ≥ 0.30 을 보고한다 (v4: 24-dim
   AUPRC 0.397 → Top-5 deny 후 0.056, 잔존 14.0%, drop ratio 0.86, S5 §5
   재측정). 본 보조 측정값을 BLOCK 으로 격상하려면 `phase2_evaluation.py`
   에 Top-5 deny 후 재학습 ML 의 잔존율/절대값 산출 함수 신설이 선행되어야
   하며, 현 코드에는 미구현 상태다. ratio cap 미통과 시 ML 이 사실상
   deterministic 5 룰 또는 raw feature 만 학습한 shortcut 으로 판정, 5 게이트
   통과와 무관하게 ML 부가가치 인정 불가.

근거 audit: `docs/PHASE2_FITTING_AUDIT.md`,
`artifacts/S4_evaluation_protocol.md`, `docs/S9_phase2_value_baseline.md`,
`artifacts/S5_phase2_input_redesign.md`.

---

## 감사기준서 갭 분석: 범위외 항목 (2건)

데이터 구조 또는 활동 특성상 프로젝트에서 대응할 수 없는 항목.
출처: [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) §5

| #   | 항목                    | 제외 사유                                                                                              |
|:----|:-----------------------|:------------------------------------------------------------------------------------------------------|
| 4-7 | 배치 실패 로그 재처리    | 운영 로그는 전표 단위가 아닌 배치 작업 단위. 전표 CSV 구조와 다름                                         |
| 3-5 | 관련자 질문 절차         | 감사인의 대면 활동으로 데이터 대체 불가. 단, "이상 전표 집중 사용자 Top-N" 리포트로 질문 대상 추천 가능     |
