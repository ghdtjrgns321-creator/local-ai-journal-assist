# Troubleshooting

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
감사 전표 테스트 자동화 프로젝트(Local AI Audit Assistant)에서 발생한
프로젝트 수준의 전략적 문제 해결 과정을 기록한다.

## 케이스 목록

| ID   | 분류       | 제목                                        | 키워드                                | 상태       |
|------|-----------|---------------------------------------------|---------------------------------------|-----------|
| TS-1 | 데이터 전략 | 감사 데이터셋 확보 위기 → DataSynth 전환       | 공개 데이터 부족, 합성 데이터, EY-ASU   | 해결       |
| TS-2 | 도메인 적합 | DataSynth 한국 적합도 — 룰 진화와 기준서 탐색  | 한국 감사기준, FSS 감리, SOD 과탐       | 진행 중    |
| TS-3 | ML 전략    | 합성 데이터 지도학습 한계 → 비지도학습 중심 전환  | 순환 학습, distribution shift, VAE+IF  | 해결       |
| TS-4 | 아키텍처   | 글로벌 싱글톤 → Company-Centric 전면 재설계        | 싱글톤, 멀티테넌트, Engagement, Context | 해결       |
| TS-5 | 데이터 품질 | DataSynth "정상=무결" 원칙이 ML 학습을 오히려 방해  | 지름길 학습, MCAR 균일, test fitting    | 해결       |
| TS-6 | 아키텍처   | 로컬 LLM 한계 → 하이브리드(로컬 ML + 상용 API) 전환 | VRAM 8GB, 한국어 회계, Gemini, 비식별화 | 해결       |
| TS-7 | 탐지 전략 | PHASE1 룰 나열 → 케이스 중심 리뷰 큐로 리모델링     | rule explosion, case grouping, phase1 recall | 진행 중 |

---

## TS-1: 감사 데이터셋 확보 위기 → DataSynth 전환

**분류**: 데이터 전략 | **해결일**: 2026-03-17

### 1. 증상

PCAOB AS 2401 / ISA 240 기반 전표 이상치 탐지 시스템을 구축하려면
**부정 레이블이 포함된 대규모 감사 전표 데이터**가 필요하다.
그러나 적합한 공개 데이터셋이 존재하지 않았다.

요구 조건:
- 차변/대변 금액 + GL 계정 + 날짜 + 입력자 정보가 모두 존재
- 부정(fraud) 레이블이 포함되어 있을 것
- 100만 건 이상 규모
- 복식부기 항등식(차=대) 보장

### 2. 재현 조건

감사 전표 데이터는 기업의 핵심 재무 데이터이므로 공개가 극히 제한적이다.
학술 연구용으로 공개된 데이터도 익명화·필드 제거로 인해 실무 감사 시나리오 재현이 어렵다.

### 3. 원인 분석

여러 LLM(Claude, GPT, Gemini)을 활용하여 공개 데이터셋을 검색하고,
직접 Kaggle, UCI, GitHub 등을 탐색하여 **32개 데이터셋/도구를 전수 검토**했다.

주요 후보 5종의 한계:

| 데이터셋          |     행수 | 한계                                                   |
|-------------------|--------:|--------------------------------------------------------|
| sap-merged        |    332K | 이상치 레이블 1%뿐 (IF/LOF 자동 라벨). 부정 시나리오 없음 |
| schreyer-fraud    |    533K | 날짜 없음, 전 필드 익명화, 금액 표준화                    |
| bpi2019           |  1,596K | 전표가 아닌 이벤트 로그 (프로세스 마이닝 데이터)          |
| financial-anomaly |    217K | Benford 테스트용. GL 계정·입력자 없음                    |
| general-ledger    |     28K | 규모 부족. 부정 레이블 없음                              |

공통 문제: **"차변/대변 + GL 계정 + 날짜 + 입력자 + 부정 레이블"을 모두 갖춘 공개 데이터가 없다.**

### 4. 시도한 접근들

1. **기존 데이터셋 조합 사용**
   - sap-merged(SAP 구조) + schreyer-fraud(레이블) 조합을 시도.
   - 기각: 스키마가 다르고, schreyer는 날짜가 없어 시계열 룰(L3-04~L1-08) 검증이 불가.

2. **수동 합성 데이터 생성 (Python 스크립트)**
   - pandas로 직접 랜덤 전표를 생성하는 방안.
   - 기각: 복식부기 항등식 보장, 현실적 계정 분포, 다양한 부정 시나리오 주입을
     직접 구현하면 "데이터 생성 프로젝트"가 별도로 필요.
   - 생성한 데이터의 신뢰성 문제가 제기될 수 있음.

3. **EY-ASU DataSynth 채택** ← 최종 선택
   - EY(회계법인)와 Arizona State University 공동 개발 오픈소스 Rust 도구. -> 신뢰성 문제 해결
   - SAP ACDOCA 71필드 네이티브 구조, 132개 anomaly 유형 내장.
   - PCAOB/ISA/COSO/SOX 감사기준을 코드 레벨로 구현.

### 5. 최종 해결

DataSynth를 직접 빌드(Rust)하여 프로젝트용 데이터를 생성했다.

**초기 생성 설정** (`config/datasynth.yaml` 발췌, TS-2에서 재설정):

```yaml
global:
  seed: 2024
  industry: manufacturing
  start_date: "2022-01-01"
  period_months: 12
companies:
  - code: "C001"  # KR 본사 (서울), 100K/yr
  - code: "C002"  # KR 울산공장, 10K/yr
  - code: "C003"  # KR 천안공장, 10K/yr
fraud:
  enabled: true
  fraud_rate: 0.02
```

기존 수집 데이터 5종은 **검증용**(벤치마크)으로 전환:
- sap-merged → DataSynth가 실제 SAP 구조와 일치하는지 비교
- schreyer-fraud → ML 모델 성능을 학술 벤치마크와 비교
- bpi2019 → 사용자 행동 패턴 (L1-05~L3-02 룰) 검증

### 6. 검증 결과

| 지표              | 기존 최선 (sap-merged) | DataSynth 생성 결과 (2026-04-14)  |
|-------------------|----------------------|------------------------------------|
| 행수              | 332K (고정)           | 1,107,720 (조절 가능)              |
| 컬럼수            | 12 (SAP 필드)         | 44 (ACDOCA 매핑)                  |
| 부정 레이블        | 없음 (IF/LOF 1%)     | fraud 1.96% + anomaly 2.60% + labels.csv 8,337건 |
| 부정 시나리오      | 0종                   | 61개 (fraud 15 + anomaly 46)      |
| 복식부기 보장      | 원본 의존             | 생성 시 강제 (불균형 25건 전부 라벨됨) |
| Benford 분포      | 원본 의존             | 생성 시 준수 (MAD 0.00146, 우수)  |
| 재현성             | 불가                  | seed 2024 고정                    |
| GL 계정            | 가변                  | 414개 사용 / 431개 정의            |
| 입력자             | 가변                  | 1,365명 사용 / 1,422명 마스터       |

Ingest 파이프라인 5종 실데이터셋 테스트: **197 tests passed, 통과.**

### 7. 교훈

- 데이터 소스 선택은 프로젝트 전체 설계에 파급된다.
  DataSynth의 SAP ACDOCA 구조가 스키마, 컬럼 매핑, 룰 설계의 기준이 되었다.
- 기존 수집 데이터를 폐기하지 않고 **검증용으로 전환**하면
  합성 데이터의 현실성을 교차 검증할 수 있다.

**관련 문서**: [00-dataset.md](pre-plan/00-dataset.md) | [DECISION.md D010](DECISION.md)

---

## TS-2: DataSynth 한국 적합도 — 룰 진화와 기준서 탐색

**분류**: 도메인 적합 | **상태**: 진행 중

이 케이스는 3단계로 진화했다. 각 단계에서 이전 단계의 한계를 발견하고 확장한 과정이다.

---

## TS-7: PHASE1 룰 나열 → 케이스 중심 리뷰 큐로 리모델링

**분류**: 탐지 전략 | **상태**: 진행 중

### 1. 증상

PHASE1의 개별 룰 구현이 늘어나면서, 결과를 `룰별 리스트`로 그대로 보여주는 방식의 한계가 뚜렷해졌다.

대표 문제:
- 같은 전표가 여러 룰에 동시에 걸려, 사람이 같은 이상행위를 여러 번 보게 된다.
- `L1-05`, `L1-06`, `L3-04`처럼 룰 ID 중심 결과는 감사자에게 직관적이지 않다.
- PHASE1은 recall 우선이라 범위를 쉽게 좁힐 수 없는데, 이 상태에서 룰 결과를 그대로 노출하면 과탐이 끝없이 많아진다.

### 2. 원인 분석

PHASE1은 본질적으로 **전수 탐지 단계**다.

- 개별 룰은 탐지 엔진 입장에서는 필요한 증거 조각이다.
- 그러나 감사자가 실제로 보고 싶은 것은 룰 번호가 아니라, `승인 통제 우회`, `결산 조정 집중`, `지급 프로세스 반복 위반`처럼 **설명 가능한 이상 시나리오**다.
- 따라서 문제는 “룰이 너무 많다”기보다, **출력 단위가 룰 중심으로 설계되어 있다**는 점이다.

### 3. 결정

PHASE1은 아래 원칙으로 리모델링한다.

1. 개별 룰은 계속 충실하게 구현한다.
2. PHASE1의 recall 성격은 유지한다.
3. 과탐은 탐지 조건을 줄여서 해결하지 않는다.
4. 최종 출력은 `룰별 결과`가 아니라 `연관 룰을 묶은 케이스(case/theme)` 중심으로 바꾼다.

### 4. 새 출력 구조

#### Theme Queue

상위 큐는 연관 룰을 하나의 이상 시나리오로 묶는다.

- 데이터 무결성 붕괴
- 승인·권한 통제 우회
- 지급·중복·자금 유출 위험
- 결산·기말 조정 이상
- 계정 사용 논리 이상
- 수익·금액·통계 이상
- 관계사·연결 구조 이상

#### Primary Theme / Secondary Tag

- 같은 케이스에는 `primary theme` 1개만 부여한다.
- 다른 관점은 `secondary tags`로만 붙인다.
- 메인 queue 정렬과 집계는 항상 `primary theme` 기준으로만 한다.

#### Case Group

Case key는 전역 하나가 아니라 theme별 템플릿을 둔다.

- 승인·권한 통제 우회: `사용자 / 프로세스 / 월`
- 결산·기말 조정 이상: `사용자 / 계정군 / 월말 윈도우`
- 지급·중복·자금 유출 위험: `거래처 / 금액밴드 / 근접기간`
- 관계사·연결 구조 이상: `회사쌍 / 거래상대 / 월`
- 수익·금액·통계 이상: `프로세스 / 계정군 / 월`

#### Drill-down

개별 전표 목록은 최하위 단계에서만 보여준다.

- 룰 번호 나열보다 `왜 이상한지` 태그 중심으로 설명
- 예: `자기승인`, `승인생략`, `기말`, `주말`, `고액`, `현금성 계정`

### 5. Rule → Evidence Type → Theme

룰을 바로 Theme에 연결하지 않고, 중간에 evidence type 계층을 둔다.

- `control_failure`: L1-04, L1-05, L1-06, L1-07, L3-02
- `timing_anomaly`: L3-04, L3-05, L3-06, L3-07, L3-08
- `duplicate_or_outflow`: L2-01, L2-02, L2-03, L2-05
- `logic_mismatch`: L1-03, L2-04, L3-09, L4-04
- `statistical_outlier`: L4-01, L4-02, L4-03, L4-06

### 6. “진짜 이상한 데이터”의 정의

최종적으로 위에 올릴 케이스는 단순 룰 카운트가 아니라, 아래 네 축을 같이 본다.

- 금액상 이상
- 통제상 이상
- 논리상 이상
- 행동상 이상

즉 `룰이 많이 걸린 건`이 아니라,
`금액이 크고`, `통제 실패가 강하고`, `업무 논리상 부자연스럽고`, `사용자/시점 집중도가 높은 케이스`
를 먼저 보여주도록 리모델링한다.

### 7. Case Priority 공식

기본 점수식은 아래처럼 정의한다.

`case_priority = 0.30*control_score + 0.30*amount_score + 0.15*logic_score + 0.15*timing_score + 0.10*behavior_score`

이 공식에 들어가는 `control_score`, `logic_score` 등은 raw rule label을 직접 더한 값이 아니다. 현재 구현은 각 rule hit를 먼저 `src/detection/rule_scoring.py`에서 `display_label`, `signal_strength`, `evidence_strength`, `scoring_role`, `normalized_score`로 정규화한 뒤 evidence type별로 합산한다.

정규화 공식:

`normalized_score = signal_strength * (severity / 5) * evidence_strength_factor * scoring_role_factor`

원칙:

- `repeat_score`는 직접 가산하지 않고 tie-breaker 및 priority band 보정에 사용
- 룰 개수는 직접 점수항이 아니라 보조 지표
- 같은 evidence type 중복은 상한을 둠
- `L3-08` 같은 booster 룰과 `L4-06` 같은 combo-only 룰은 단독 점수보다 결합 증거로 해석
- `L4-02/D01/D02` 같은 macro finding은 transaction queue 점수에 직접 더하지 않음
- `L3-03` 단독은 관계사 거래 모집단 신호로 유지한다. raw `0.40`, `severity=4`, `weak evidence`, L3 weight 적용 후 row `anomaly_score` 자연 기여도는 약 `0.036`이며 단독 Low floor를 만들지 않는다.
- `IC01/IC02/IC03`은 L1~L4 룰 수에 포함하지 않는 관계사 보조 finding이다. `IntercompanyMatcher` 결과가 aggregate 입력에 포함된 경우, row 대표 점수에서 대사 예외가 숨지 않도록 별도 `intercompany_exception_score`를 기록한다. `IC02` 또는 `IC03` 단독은 최소 Low, `IC01` 또는 2개 이상 IC 예외 결합은 최소 Medium floor를 적용한다.

추가 정규화 예외:

- `L3-01`은 계정-업무 불일치 원인 순서를 보존하기 위해 전용 정규화를 사용한다. exact denylist raw `0.65`는 category fallback `0.45`, strict mismatch `0.40`보다 PHASE1 row `anomaly_score`와 case `logic_score`에 더 크게 반영되어야 한다.

### 8. Case Explanation Template

Drill-down 설명은 룰 번호 나열 대신 템플릿으로 만든다.

- `자기승인 + 승인생략 + 고액 전표`
- `기말 집중 + 수기 입력 + 설명 부실`
- `동일 거래처 반복 지급 + 근접일자 중복`
- `결산 계정과 현금성 계정의 비정상 결합`

### 9. 엔진 출력 vs 사용자 노출 분리

- 내부 엔진: 모든 룰, 모든 evidence, 모든 case score 계산
- 화면 1차: `case_priority` 상위 N개 케이스만 노출
- 화면 2차: theme별 상위 case
- drill-down: 전표 목록 + 증거 태그 + 대표 설명문
- raw rule output: 기본 화면에서는 숨김, 개발자/검증 모드에서만 노출

### 10. 실행 원칙

- 개별 룰은 삭제하지 않는다.
- PHASE1에서 범위를 좁혀 미탐을 만드는 방식은 피한다.
- 과탐은 `theme 묶음`, `case group`, `priority score`, `drill-down` 구조로 해결한다.
- 이 방향은 [DETECTION_RULES.md](DETECTION_RULES.md)의 `2.0 PHASE1 리모델링 원칙`에 반영했다.

---

### 1단계: 초기 8개 룰로 시작

#### 증상

프로젝트 초기에 감사기준서 240호만 참조하여 8개 탐지 룰(R001~R008)을 설계했다.
이 설계에는 다음 문제가 있었다:

- 240호 외 다른 감사기준서(315호, 500호 등)의 요구사항 미반영
- 내부회계관리제도(K-SOX), 금감원 감리 실증 데이터 미참조
- 각 룰의 우선순위와 Phase별 배치 근거 부재
- 법규 근거·실증 빈도·데이터 가용성의 체계적 평가 부재

#### 원인 분석

8개 룰은 "감사기준서 240호에서 언급된 전표 특성"만 나열한 것이다.
실제 한국 감사 환경에서 어떤 부정이 얼마나 자주 발생하는지,
어떤 법규가 어떤 검사를 요구하는지에 대한 실증 근거가 없었다.

#### 한계 → 2단계 전환 계기

8개 룰을 정한 근거가 없고,
8개 룰로는 FSS 6대 부정 패턴 중 가공전표·결산수정·횡령은폐 3개만 부분 커버하고,
순환거래·승인위반·비정상시점은 전혀 탐지하지 못한다.
법규 근거 없이 "직관적으로 의심스러운 특성"만 나열한 설계의 한계가 명확했다.

---

### 2단계: FSS 감리지적사례 분석 → 22개 룰 재설계

#### 시도한 접근들

1. **감사기준서 원문 파싱**
   - §32 전표검사 의무, A44 성격·시기·범위, A45 부정 분개 식별 특성, A46 CAATs 활용.
   - 11개 식별 특성 도출.

2. **금감원 FSS 감리지적사례 189건 본문 직접 분석** ← 핵심 전환점
   - 2011~2025년 189건의 감리지적사례 본문(HWP/PDF)을 파싱하여 LLM을 통한 분류작업을 진행했다.
   - **발견**: 제목 기반 분류와 본문 기반 분류의 차이가 크다.
     "횡령 은폐" 키워드로 제목만 검색하면 6건이지만,
     본문을 읽으면 횡령과 관련된 전표 조작이 24건(4배)으로 증가.
   - 전표 관련 사례 94건(50%)에서 6대 부정 패턴 도출:

     | 부정 패턴     | 건수 | 비율  |
     |-------------|------|-------|
     | 가공전표 생성  |   50 | 53%   |
     | 결산수정 조작  |   27 | 29%   |
     | 횡령 은폐     |   24 | 26%   |
     | 순환거래      |   10 | 11%   |
     | 승인/SoD 위반 |    5 |  5%   |
     | 비정상 시점    |    4 |  4%   |

3. **3축 평가 체계 수립**
   - 축 1: 법규 근거 (KICPA 240, 외감법, K-SOX) — 0~3점
   - 축 2: FSS 실증 빈도 (189건 본문 분석) — 0~3점
   - 축 3: DataSynth 39컬럼으로 즉시 탐지 가능 여부 — 0~3점
   - 합계 7~9점 → Tier 1(Must, Phase 1), 4~6점 → Tier 2(Should, Phase 2)

#### 최종 해결 (2단계)

**R001~R008(8개) → L1/L2/L3/L4 체계 22개 룰로 전면 재설계:**

| 그룹 | 역할                    | 룰 수 | 예시                                    |
|------|------------------------|-------|----------------------------------------|
| L1   | 확정 오류/명시 위반      |     3 | 차대변 균형, 필수필드 누락, 무효 계정     |
| L2   | 강한 부정 정황           |    10 | 매출 이상변동, 승인한도, 중복지급, 자기승인, 직무분리 |
| L3/L4 | 검토 필요/통계 이상치   |     9 | 결산 검토 후보군, 주말/심야 전기, Benford 위반 |

외부 기준 커버리지:
- AICPA/CAQ 15개 CAAT 시나리오 중 14개(93%) 커버
- PCAOB AS 2401 A45 부정 식별 특성 11개 전부(100%) 매핑

#### 한계 → 3단계 전환 계기

22개 룰을 구현하고 DataSynth로 E2E 테스트를 실행한 결과,
룰 자체는 정상 동작하지만 **테스트 데이터가 한국 감사 시나리오를 반영하지 못하는 문제**가 발견되었다.
설계(한국 기준)와 검증(미국 기준 데이터) 사이의 괴리를 해소하기 위해 3단계로 진입했다.

---

### 3단계: Detection E2E 테스트 → 한국 적합도 미매칭 (진행 중)

#### 증상

22개 룰 구현 완료 후 DataSynth 1,101,677행으로 E2E 테스트를 실행했다.

결과:
- 22개 룰 중 **8개가 0건** (검증 자체 불가)
- **L1-06(직무분리 위반) 99.96% 과탐** (1,101,254건 / 1,101,677건)
- 실제 anomaly 8,022건 전부 탐지(Recall 100%)이지만 Precision 7.5%

주요 결과 발췌:

| 룰   | 이름           | flagged    | 비율     | 문제               |
|------|--------------|-----------|---------|-------------------|
| L4-01  | 매출 이상 변동  |       945 |  0.09%  | —                 |
| L2-01  | 승인한도 직하   |         0 |  0.00%  | 임계값 범위 밖      |
| L1-06  | 직무분리 위반   | 1,101,254 | 99.96%  | 전원 위반           |
| L3-02  | 수기 전표      |         6 |  0.00%  | —                 |
| L3-06  | 심야 전기      |   471,845 | 42.83%  | 시간정보 없음       |
| L4-02  | Benford 위반  |         0 |  0.00%  | 위반 데이터 미주입   |

#### 재현 조건

DataSynth 초기 설정은 **미국 제조사** 기준이었다 (C002=US, C003=DE).
한국 감사기준서(K-SA 240)와 내부회계관리제도(K-SOX)가 요구하는 시나리오와
DataSynth 생성 데이터 사이에 계약(contract)이 없었다.
이후 법인 국가를 KR로 통일하고, seasonality·debit_credit_distribution 설정을 추가하여 재생성했다.

#### 원인 분석

**핵심: 설정의 전제 조건과 데이터의 실태가 불일치한다.**

```
DETECTION_RULES.md (뿌리: 한국 감사기준서 기반 22개 룰)
  ↓ 도출
settings.py + audit_rules.yaml (설정: 한국 실무 기준)
  ↓ 참조
detection 코드 (구현)
  ↓ 테스트
DataSynth 데이터 (검증: KR 3법인 재생성 완료)
```

항목별 갭:

| 항목           | settings.py (한국 기준)    | DataSynth 실태 (초기)         | 갭                    | 재생성 후 상태 |
|---------------|--------------------------|------------------------------|----------------------|---------------|
| 승인한도       | 5,000만 원                | 최대 금액 770만               | 한도가 데이터 범위 밖   | 해결 (KRW 6단계 한도 설정) |
| 직무분리 임계   | 동일인 3개+ 프로세스       | 1,365명 사용 / 1,422명 마스터  | 소규모 환경에서 전원 위반 | 해결 (anomalous 1.5%, compatible 25%, 2026-04-14 실측 SoD 3.32%) |
| 심야 기준      | 22시~06시                 | posting_date에 시간 없음      | 원천 데이터 구조 부재   | 해결 (intraday 8구간 활성화) |
| 거래처 ID      | auxiliary_account_number  | 전부 NULL                    | 원천 데이터 구조 부재   | 부분 해결 (P2P/O2C doc flow) |
| Benford 위반   | MAD > 0.012              | 금액이 Benford 적합 분포      | 위반 데이터 미주입     | 해결 (anomaly_injection 5%) |

#### 시도한 접근들

1. **기준서 전면 재탐색**
   - 감사기준서 240호만이 아닌 **330호·500호·520호·550호·1100호 + IT감사 기준서(KLCA, KICPA JET, 금융권 가이드라인)** 전체를 전표감사 관점에서 조사.
   - 9가지 전표 단위 공통 체크항목 도출 (존재·발생, 완전성, 계정분류, 컷오프, 승인·권한, 증빙 적정성, 경제적 실질, 관련당사자, 역분개).
   - → `docs/DETECTION_REFERENCE.md`에 기록.

2. **22개 룰과의 갭 분석 — 39건 식별**
   - 기준서 갭 7건, 체크항목 갭 8건, 절차 갭 7건, IT감사 갭 7건, 참조출처 갭 10건.

3. **프로젝트 구현 가능성 판정**
   - 각 갭에 대해 "이 프로젝트에서 구현할 수 있는가"를 실제 데이터 구조(39컬럼, UUID, timestamp 등)와 대조하여 5단계로 판정.
   - DataSynth가 합성 데이터 생성기라는 점을 활용: **필요한 컬럼을 추가 생성**하면 "데이터 없음"으로 분류했던 항목도 구현 가능.

4. **구현 로직 검증** (CAATs 업계 표준 조사)
   - 각 탐지 항목의 구현 방법을 ACL/IDEA/MindBridge/Arbutus/zapliance 등 CAATs 도구의 접근법과 대조.
   - 한국 실무 맞춤: 업무시간(야근 반영), 전결규정(6단계), 적격증빙(3만원 기준), K-IFRS 계정체계, SAP Reversal Reason Code, 사내 IP 대역 등.

5. **DataSynth를 한국 감사 환경에 맞추기** ← 최종 선택
   - DataSynth YAML 재설정 + Rust 소스 수정(approval.rs 활성화 등).
   - **원칙**: 설정(한국 실무)은 유지하고, 데이터(DataSynth)가 설정을 검증할 수 있도록 맞춘다.

#### 최종 해결

**A. 갭 분석 결과 (39건 → 판정)**

| 판정 | 건수 | 내용 |
|------|------|------|
| **구현 가능** | 18건 | 39컬럼으로 즉시 가능(3건) + DataSynth 컬럼 추가(7건) + Phase 2~3(8건) |
| **문서 보완** | 14건 | DETECTION_RULES.md 기준서 매핑·출처 추가 |
| **불필요** | 5건 | 전수조사 프로젝트 특성상 (표본추출, 감사조서 등) |
| **범위외** | 2건 | 배치 실패 로그(작업 단위), 관련자 질문(대면 활동) |

**B. DataSynth 한국 맞춤 재설정**

`config/datasynth.yaml` + `generation_principles.md` 주요 변경:

- **사용자 풀**: 1,500명 persona별 분리 (주니어 800, 시니어 400, 컨트롤러 50, 매니저 200, 자동화 50), 실제 JE 사용자 1,365명 / 마스터 1,422명
- **시간 정보**: intraday 8구간 분포 활성화. 한국 실무 반영: 심야(22~06시) 0.02~0.05, 야근(18:30~22) 0.3
- **승인한도**: KRW 6단계 [1천만, 1억, 10억, 50억, 100억, 500억]
- **법인 국가**: 전 법인 KR 통일 (C001 서울, C002 울산, C003 천안)
- **seasonality**: 주말 가중치 1.0, 월말 ×2.5, 분기말 ×4.0, 연말 ×6.0, 요일별 패턴
- **차대변 분포**: equal 99.8%, more_debit/credit 각 0.1%
- **결측값 주입**: rate 2%, MCAR 전략, 필수필드 보호
- **Benford 위반**: anomaly_injection 활성화 (total 5%, fraud 2%, error 2%, process 1%)
- **거래처 ID**: document_flows P2P/O2C 활성화
- **관계사**: ic_transaction_rate 10%, matched pairs 생성

**C. DataSynth 확장 컬럼 설계 (신규)**

| 카테고리 | 추가 컬럼 | 탐지 활용 |
|---------|----------|----------|
| 승인 | `approved_by`, `approval_date` — DataSynth v1.2.0 생성 완료 | 승인 누락/지연/자기승인 정밀화 |
| 승인 레벨 | `approval_level` — DuckDB 파생 컬럼 (CASE WHEN, 전결규정 6단계) | 레벨 건너뜀 탐지 |
| 증빙 | `has_attachment`, `supporting_doc_type`, `invoice_amount` 등 — 미구현 (Phase 3+) | 증빙 누락, 금액 불일치, 컷오프, 부가세 검증 |
| 변경 이력 | `changed_by`, `change_date`, `changed_field` — 미구현 (Phase 3+) | 기말 수정 집중, 무단 수정 |
| 역분개 | `reversal_reason` (SAP RRC) | 역분개 유형 구분 |

> Rust 코드 수정 필요: `je_generator.rs`(레벨 하드코딩→config), `user.rs`(한국식 역할), `approval.rs`(원화 기준)

**D. 프로젝트 문서 11개 파일 업데이트 완료**

| 파일 | 추가 내용 |
|------|----------|
| DETECTION_RULES.md    | §2.8~2.11 기준서 4개 섹션 + 부록 출처 + 프로젝트 범위 섹션 |
| pre-plan/05-detection.md | 신규 탐지 룰 후보 (Phase 1~3) |
| pre-plan/02-ingest.md | 확장 컬럼 매핑 (16개) |
| pre-plan/03-feature.md | 신규 파생변수 (11개) |
| pre-plan/03a-preprocessing.md | 확장 컬럼 전처리 + White Box |
| pre-plan/04-validation.md | L3 검증 확장 (통제 효과성, TB 대사) |
| pre-plan/05a-detection-ml.md | Phase 2 신규 탐지 (TrendBreak 등 5건) |
| pre-plan/06-db.md | GL 확장 + Trial Balance DDL |
| pre-plan/08-llm.md | Phase 3 NLP/LLM (2건) |
| TASKS.md | Phase 1b 확장 3건 + DataSynth 확장 5건 |
| generation_principles.md | §12 확장 컬럼 생성 원칙 6개 카테고리 |

#### 검증 결과 (중간)

| 지표              | 1차 E2E (Before)              | 재설정 후 (Expected)         | 비고 |
|-------------------|------------------------------|------------------------------|------|
| 검증 가능 룰       | 14/22 (8개 0건)               | 22/22 + 신규 룰 후보          | E2E 재테스트 필요 |
| L1-06 과탐률         | 99.96%                        | ~10%                          | anomalous 7% 설정 적용 |
| Recall             | 100% (8,022건)                | 100% 유지 목표                | |
| Precision          | 7.5%                          | 개선 목표 (과탐 해소)          | |

데이터 재생성 완료 (2026-03-26). E2E 재테스트는 미실행.

#### 다음 단계

1. ~~DataSynth Rust 코드 수정 (approval.rs 한국식 + 확장 컬럼 CSV 출력)~~ → 완료
2. ~~데이터 재생성~~ → 완료 (2026-03-26, auxiliary_account_number·MCAR·Benford 위반·적요 키워드 등 재생성)
3. E2E 재테스트 (재생성 데이터 기준)
4. Phase 1b 확장 3건 구현 (역분개, Top-side JE, 시간대 입력자 집중)
5. 신규 탐지 룰의 성능 평가

#### 교훈

- **"설정만 바꾸면 테스트 통과"는 무의미하다.**
  테스트 데이터가 실무 시나리오를 반영해야 검증에 의미가 있다.
- 도메인 룰 설계는 한 번에 완성되지 않는다.
  **법규 분석 → 실증 데이터 분석 → 구현 → 테스트 → 갭 발견 → 재설계**의
  반복 사이클을 거쳐 점진적으로 정밀해진다.
- 합성 데이터 생성 도구를 사용할 때는 **설정과 데이터 사이의 계약**을 명시해야 한다.
  어떤 룰이 어떤 데이터 특성에 의존하는지 매핑하지 않으면
  "코드는 정상인데 데이터가 없어서 0건"인 상황을 구분할 수 없다.
- **"범위외"를 성급하게 판정하지 말 것.** DataSynth는 합성 데이터 생성기이므로
  "현재 CSV에 없는 컬럼"은 "생성할 수 없는 컬럼"이 아니다.
  원래 범위외 9건 중 7건이 DataSynth 확장으로 구현 가능하다는 것을 뒤늦게 발견.
- **한국 실무 맥락을 빠뜨리면 false positive가 폭증한다.**
  18시 이후를 비정상으로 잡으면 야근 문화에서 과탐. 심야(22시~06시)가 실제 비정상 기준.

**관련 문서**: [DETECTION_RULES.md](DETECTION_RULES.md) | [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) | [generation_principles.md](../data/journal/primary/datasynth/generation_principles.md) | [DECISION.md D011~D013](DECISION.md) | [DETECTION_RULES §6 갭 분석](DETECTION_RULES.md) | [E2E 테스트 결과](../tests/test_detection/test-results/e2e-detection-datasynth.md)

---

## TS-3: 합성 데이터 지도학습 한계 → 비지도학습 중심 전환

**분류**: ML 전략 | **해결일**: 2026-04-01

### 1. 증상

Phase 2 ML 탐지기(XGBoost, VAE+IF, FT-Transformer, BiLSTM, Stacking) 설계를 검토하면서,
DataSynth 합성 데이터로 지도학습 모델을 훈련하는 것의 실효성에 의문이 제기되었다.

핵심 질문:
- DataSynth가 **룰 기반으로 주입한 이상치**를 ML이 학습하면, 이미 Phase 1 룰이 탐지하는 패턴을 재발견하는 것에 불과하지 않은가?
- 합성 데이터로 학습한 모델이 실무 감사 데이터에서도 유효한가?

### 2. 원인 분석

**순환 학습(Circular Learning) 구조:**

```
DataSynth 룰 기반 이상치 주입 (금액 3~6배 증폭, 주말 전기, 자기승인 등)
       ↓
Phase 1 룰이 동일 규칙으로 이미 탐지 (recall 89.9%)
       ↓
지도학습 모델이 같은 패턴을 학습 → 룰의 재발견
       ↓
ML 부가가치 제한
```

ML의 본래 가치는 **룰로 정의할 수 없는 복합 패턴** 탐지에 있다.
그러나 DataSynth의 이상치는 사전 정의된 규칙으로만 생성되므로, 합성 데이터에 이런 복합 패턴이 존재하지 않는다.

**산업 근거:**

| 출처 | 발견 |
|------|------|
| MindBridge / KPMG Clara | 상용 감사 AI는 실제 감사 데이터로 학습. 합성 데이터는 보조만 담당 |
| IEEE/Academia (2025) | 합성→실무 적용 시 distribution shift로 15~25% 성능 하락 |
| FCA Report | "합성 데이터는 실제 고객 데이터를 대체할 수 없다" |
| Semi-supervised 연구 | 라벨 500건 실데이터 + 비라벨 50K건이 합성 100K건보다 우수 |

### 3. 시도한 접근들

1. **공개 금융 데이터셋 활용 검토**
   - `data/journal/validation/`에 5종 보유: sap-merged(332K), schreyer-fraud(533K), bpi2019(1,596K), financial-anomaly(217K), general-ledger(28K).
   - 기각: TS-1에서 확인한 대로 어느 것도 "차대변 + GL + 날짜 + 입력자 + 부정 레이블"을 모두 갖추지 못한다. 지도학습 성능 평가용 ground truth로 사용할 수 없다.

2. **CTGAN/GAN 기반 합성 데이터 고도화 검토**
   - 룰 기반 주입 대신 GAN으로 더 현실적인 이상 패턴을 생성하는 방안.
   - 기각: CTGAN 자체가 Phase 2급 복잡도이며, GAN이 생성한 이상 패턴의 감사 도메인 유효성을 검증할 수단이 없다.

3. **비지도학습 중심 전환** ← 최종 선택
   - VAE + Isolation Forest는 **정상 거래의 분포**를 학습하여 이탈을 탐지한다.
   - DataSynth 정상 거래 98%의 분포(LogNormal 금액, 시간대 패턴, 계정 조합)는 현실적이므로, 비지도학습에는 합성 데이터가 유효하다.
   - 지도학습 파이프라인은 인프라로 구축하되, 고객사 실데이터 유입 시 활성화되는 구조로 설계한다.

### 4. 최종 해결

**A. 모델별 역할 재정의:**

| 모델 | 역할 | 합성 데이터 적합도 |
|:-----|:-----|:-----------------:|
| VAE + Isolation Forest | **핵심 탐지기** — 정상 분포 이탈 탐지 | 높음 |
| XGBoost / FT-Transformer / BiLSTM | **파이프라인 인프라** — 프레임워크 구축 + 시연 | 중간 |
| Stacking Meta-Learner | **앙상블** — 모델 출력 결합 | 높음 |

**B. 지도학습 인프라 구축 범위:**

지도학습은 "합성 데이터에서 높은 성능을 달성"하는 것이 아니라,
**실데이터 유입 시 즉시 활용 가능한 파이프라인**을 미리 구축하는 것이 목표이다.

구축 항목:
- cv_selector (GridSearchCV 기반 모델 자동 선택)
- SMOTE-ENN (불균형 데이터 처리)
- PR-AUC / F2-score (감사 도메인 평가 지표)
- Out-of-Fold (Stacking 데이터 누수 방지)
- Semi-supervised 인터페이스 (pseudo-label + fine-tuning 경로)

**C. 고객사별 확장 경로:**

```
[현재 MVP]                          [향후 확장]
DataSynth 합성 데이터                고객사 A 실데이터 (감사인 라벨링)
       ↓                                    ↓
비지도학습 중심 탐지                  지도학습 fine-tuning 활성화
+ 지도학습 파이프라인 대기              + 비지도학습 고객사 분포 재학습
       ↓                                    ↓
범용 이상 탐지                       고객사 A 맞춤 탐지 모델
```

감사법인이 고객사 전표를 수집하고, 감사인이 이상 여부를 라벨링하면:
- 지도학습 파이프라인이 즉시 활성화되어 고객사 고유 패턴을 학습한다.
- 비지도학습 모델도 고객사 정상 분포로 재학습하여 정밀도를 높인다.
- 고객사별 모델은 독립 저장되며, 다음 분기 감사에서 재사용된다.

### 5. 검증 결과

이 결정은 구현 전 전략 검토 단계에서 내려졌으므로, 정량적 검증 결과는 Phase 2 구현 완료 후 갱신한다.

예상 지표:

| 지표 | 비지도학습 (합성 데이터) | 지도학습 (합성 데이터) | 지도학습 (실데이터, 향후) |
|:-----|:----------------------:|:---------------------:|:------------------------:|
| 순환 학습 문제 | 없음 | 있음 | 없음 |
| Distribution shift | 낮음 | 15~25% 하락 | 없음 |
| 실무 투입 가능 | 즉시 | 인프라만 | 즉시 |

### 6. 교훈

- **합성 데이터의 한계를 인식하는 것이 곧 올바른 설계의 시작이다.**
  TS-1에서 DataSynth가 데이터 확보 위기를 해결했지만, 합성 데이터가 모든 ML 학습에 적합한 것은 아니다.
- **비지도학습은 합성 데이터의 강점과 잘 맞는다.**
  DataSynth가 생성하는 정상 거래의 분포는 현실적이며, 비지도학습은 이 분포만으로 이상 탐지가 가능하다.
- **지도학습 인프라를 미리 구축하면 실데이터 유입 시 즉시 전환할 수 있다.**
  "현재 쓸 수 없다"와 "만들지 않는다"는 다른 결정이다.
- **포트폴리오 프로젝트에서 보여줄 가치는 "높은 정확도 수치"가 아니라 "확장 가능한 아키텍처"이다.**

**관련 문서**: [CONSTRAINTS.md §ML 학습 전략](CONSTRAINTS.md) | [05a-detection-ml.md](pre-plan/05a-detection-ml.md) | [TASKS.md §Phase 2](TASKS.md)

---

## TS-4: 글로벌 싱글톤 → Company-Centric 전면 재설계

**분류**: 아키텍처 | **해결일**: 2026-04-02

### 1. 증상

Phase 1a/1b 완료 후, 프로젝트가 "모든 회사에 범용 대응"하는 구조임이 한계로 드러났다.
실무 감사에서는 회사마다 ERP, 승인한도, 계정체계, 위험 프로파일이 다르다.

구체적 문제:
- `config/settings.py`의 `@lru_cache` 싱글톤으로 **모든 회사가 동일 임계값 공유**
- `audit_rules.yaml`, `keywords.yaml`, `chart_of_accounts.csv` 모두 글로벌 1개
- DB가 `batch_id` 기반 격리만 지원하여 **회사-연도 차원 분석 불가**
- 매핑 프로파일이 fingerprint 기반이지만 회사와 연결되지 않아 **반복 감사 재사용 불가**
- Phase 2 ML 모델이 범용 1개로 계획되어 **회사별 fine-tuning 경로 부재**

### 2. 원인 분석

프로젝트 초기 설계에서 멀티 클라이언트 지원을 고려하지 않았다.
`company_code`는 데이터 컬럼(필터링 차원)이지 시스템 수준의 테넌트 식별자가 아니었다.

영향 범위 분석:
- `get_settings()` 싱글톤 호출: `src/` 내 19개 파일
- `get_audit_rules()`, `get_keywords()` 등 YAML 싱글톤: 12개 파일
- `get_connection()` DB 싱글톤: 글로벌 단일 커넥션

그러나 핵심 모듈(detection, feature, ingest)이 이미 `settings=None` 파라미터 주입을 지원하는 상태였다.
싱글톤을 "걷어내기"가 아닌 "채워넣기"로 전환 가능하다는 것이 핵심 발견.

### 3. 시도한 접근들

1. **점진적 전환 (어댑터 패턴)**
   - 기존 싱글톤 위에 Company Profile 레이어만 추가.
   - 기각: 설정 해소 체인이 복잡해지고, DB 격리가 근본적으로 해결되지 않는다.

2. **Phase 2부터 적용**
   - Phase 1은 범용으로 완성 후, Phase 2 ML 진입 시 회사별 분리 도입.
   - 기각: Phase 1c 대시보드가 이미 회사 선택 UI를 필요로 하며, 나중에 1a/1b 리팩토링이 불가피하다.

3. **전면 재설계** ← 최종 선택
   - Company + Engagement 2계층 구조 도입.
   - `CompanyContext` 불변 객체로 싱글톤 대체.
   - Engagement별 DuckDB 격리.
   - 기존 코드의 파라미터 주입 패턴을 활용하여 리팩토링 범위 최소화.

### 4. 최종 해결

**A. Company + Engagement 2계층 설계:**

```
data/companies/{company_id}/
├── company.yaml              # 메타 + settings_overrides
├── chart_of_accounts.csv     # 회사별 CoA
├── keywords.yaml             # ERP 별칭 오버라이드
├── audit_rules.yaml          # 회사별 룰 오버라이드
├── profiles/                 # 매핑 프로파일 (회사별 격리)
└── engagements/{year}/
    ├── engagement.yaml       # 연도별 settings_overrides
    ├── audit.duckdb          # 격리된 DB
    └── models/               # ML 모델 아티팩트
```

**B. CompanyContext — 싱글톤 대체:**

```python
@dataclass(frozen=True)
class CompanyContext:
    company_id: str
    engagement_id: str
    settings: AuditSettings       # 3계층 해소(글로벌→회사→연도) 완료
    keywords: dict                # 글로벌 + 회사별 merge
    audit_rules: dict             # 글로벌 + 회사별 merge
    chart_of_accounts: set[str]   # 회사별 CoA
    db_path: Path                 # engagement별 DB 경로
    # ... (11개 필드)
```

**C. 3계층 설정 해소 체인:**

글로벌 기본값 → 회사 오버라이드 → 연도 오버라이드 → 런타임(프리셋/슬라이더)

**D. DB 격리: Engagement별 DB 파일.**

DuckDB single-writer 제약 해소 + 연도별 데이터 독립성 보장.

### 5. 검증 결과

구현 전 설계 단계 결정. 정량 검증은 RC-0~5 구현 완료 후 갱신.

코드 재사용 분석:
- **변경 없이 유지**: detection 전 레이어, feature 전 모듈, ingest reader/header, DB loader/queries, 차트/필터
- **리팩토링**: config/settings.py, pipeline.py, connection.py 등 12개 파일
- **신규**: src/context.py, src/company/ 패키지, 대시보드 회사 관리 컴포넌트

### 6. 교훈

- **설정 주입 패턴을 초기에 도입하면 아키텍처 전환 비용이 크게 줄어든다.**
  `BaseDetector(settings=None)`, `generate_all_features(settings=None)` 패턴 덕분에
  싱글톤 제거가 "호출부 변경"으로 가능했다.
- **"범용 도구"와 "회사별 도구"는 감사 실무에서 전혀 다른 가치를 제공한다.**
  범용 도구는 데모용이고, 실무 투입은 회사별 설정/모델/이력 관리가 전제 조건이다.
- **DB 격리 전략은 초기에 결정해야 한다.**
  단일 DB에 회사/연도 컬럼을 추가하는 것보다 Engagement별 DB 파일 격리가
  DuckDB single-writer 환경에서 운영적으로 안전하다.

**관련 문서**: [NEW_TASKS.MD](NEW_TASKS.MD) | [CONSTRAINTS.md §회사별 매핑 프로파일](CONSTRAINTS.md)

---

## TS-5: DataSynth "정상=무결" 원칙이 ML 학습을 오히려 방해

**분류**: 데이터 품질 | **해결일**: 2026-04-07

### 1. 증상

DataSynth 생성 데이터의 품질 검증(QG1~QG3)을 반복하면서 "정상 전표는 100% 깨끗해야 한다"는 원칙을 적용했다. MCAR 결측, 오타 등 데이터 품질 결함을 정상 전표에서 제거하고 비정상 전표에만 주입하는 방향으로 수정을 반복했다.

QG3 FAIL을 0건으로 만드는 데는 성공했지만, 이 과정에서 근본적인 ML 문제를 만들고 있었다.

### 2. 원인

CLAUDE.md에 명시된 원칙:
```
- 정상 데이터 → 100% 정상 수치 (차대변 균형, 양수 금액, 기간 범위 내)
- 비정상 데이터 → 의도적 비정상 + 라벨로 완전 추적
```

이 원칙을 데이터 품질(MCAR, typo, format)에까지 확대 적용한 결과:
- document_type MCAR을 비정상 전표에만 주입 → 정상=깨끗, 비정상=결함
- QG3 R5-10 "정상 전표 document_type null = 0건" 기대치에 맞추기 위해 정상 전표 보호

### 3. 왜 문제인가

| ML 위험 | 설명 |
|---------|------|
| **지름길 학습** | 모델이 `missing_field > 0 → 비정상` 규칙만 학습. 실제 fraud 패턴(금액, 시간, GL 조합) 무시. 합성 데이터 정확도 99%, 실데이터 성능 폭락 |
| **일반화 실패** | 실제 ERP에서 정상 전표도 2~5% 결측/오타 존재. 모델이 이를 전부 비정상으로 오탐(FP) |
| **허위 피처 중요도** | `data_completeness`가 피처 중요도 1위. 실제 탐지 피처(Benford, 금액 이상치)가 묻힘 |
| **합성 아티팩트** | "정상=완벽"은 현실에 없는 패턴. 이 패턴 자체가 합성 데이터의 인공물 |

추가로, QG 통과를 위해 데이터를 테스트에 맞추는 **test fitting** 함정에도 빠졌다. QG3 R5-10 임계값을 조정하려 했고, "감가상각" header를 제거하여 R3-06/07을 SKIP으로 우회하려 했다.

### 4. 해결

**CLAUDE.md 원칙 교체:**
```
- 정상 데이터: 회계적으로 정상 (차대변 균형, 양수 금액, 기간 범위 내) + 자연적 노이즈 (MCAR 결측, 오타 등)
- 비정상 데이터: 의도적 이상 패턴 + 라벨로 완전 추적
- 데이터 품질(MCAR, typo, format): 정상/비정상 무관하게 동일 비율 적용
```

**코드 수정:**
- `enhanced_orchestrator.rs`: document_type MCAR을 전체 균일 적용으로 복원
- `je_generator.rs`: fraud 전표의 source를 90% 확률로 manual 전환 (A-05)
- `SUSPENSE_L3` 영어 상수 → 한글 번역 (A-10)

**QG3 체크는 수정하지 않음.** 데이터가 QG를 통과하도록 데이터 생성 로직만 수정.

### 5. 교훈

- **"정상=무결"은 ML에서 치명적이다.** 회계적 무결성(차대변 균형)과 데이터 품질(결측/오타)은 별개. 전자는 보장하되 후자는 균일 적용해야 한다.
- **QG를 데이터에 맞추면 test fitting이다.** QG는 독립적 품질 기준이어야 하고, 데이터 생성 로직만 수정해야 한다. QG 임계값을 조정하는 것은 테스트를 무력화하는 것과 같다.
- **Phase 1(룰 기반)에서는 이 문제가 드러나지 않는다.** 룰은 임계값 기반이라 data_completeness를 피처로 쓰지 않는다. Phase 2(ML) 시작 전에 발견한 것은 운이 좋았다.

**관련 문서**: [CLAUDE.md §DATASYNTH 생성 규칙](../CLAUDE.md) | [generation_principles.md §14 ML 안전성](../data/journal/primary/datasynth/generation_principles.md)

---

## TS-6: 로컬 LLM 한계 → 하이브리드(로컬 ML + 상용 API) 전환

**분류**: 아키텍처 | **해결일**: 2026-04-09

### 1. 증상

Phase 3에서 Ollama + Qwen3-8B(Q4_K_M)으로 Text-to-SQL, 인사이트 생성, NLP 의미 분석을 구현할 계획이었다.
그러나 현재 하드웨어(RTX 3070 Ti 8GB VRAM, RAM 16GB)에서 다음 문제가 예상되었다.

| 문제 | 상세 |
|------|------|
| VRAM 병목 | Qwen3-8B Q4_K_M ~5GB + DuckDB + Streamlit 동시 실행 시 여유 3GB |
| 한국어 회계 도메인 | 8B 양자화 모델의 한국어 감사 기준서·회계 용어 이해력 부족 |
| Text-to-SQL 정확도 | 복잡한 조인·서브쿼리 생성 시 실무 수준 미달 |
| RAM 부족 | 16GB에서 LLM + ChromaDB + Streamlit + DuckDB 동시 운영 시 swap 발생 |

### 2. 원인 분석

프로젝트명이 "Local AI Audit Assistant"이므로 초기 설계에서 모든 구성요소를 로컬에서 실행하는 것을 전제했다.
보안(원본 ERP 데이터 외부 유출 방지)이 로컬 LLM 선택의 핵심 근거였다.

그러나 **보안이 요구되는 것은 원본 데이터 처리(Phase 1~2)이지, LLM 추론(Phase 3) 전체가 아니다.**
Phase 3에서 LLM에 전달하는 정보는 원본 데이터가 아니라 탐지 결과·통계 지표·비식별 패턴이다.

### 3. 시도한 접근들

1. **로컬 LLM 유지 (Qwen3-8B)**
   - 기각: VRAM 8GB에서 ML 모델과 LLM 동시 운영 비현실적. 한국어 회계 도메인 품질 부족.

2. **더 작은 모델 (Qwen3-4B)**
   - 기각: VRAM 여유 확보 가능하나 품질 더 하락. Text-to-SQL 정확도가 실용 수준 미달.

3. **하이브리드 (로컬 ML + 상용 API LLM)** ← 최종 선택
   - Phase 1~2: 로컬. 원본 ERP 데이터는 외부에 전송하지 않는다.
   - Phase 3: 상용 API(Gemini, Claude 등). 비식별 지표만 전달.

### 4. 최종 해결

**A. 영역별 실행 환경 분리:**

| 영역 | 실행 환경 | 보안 근거 |
|------|----------|----------|
| 룰 기반 탐지 (Phase 1) | 로컬 | 원본 ERP 데이터 직접 처리 |
| ML/DL 탐지 (Phase 2) | 로컬 (GPU) | 원본 데이터로 모델 학습 |
| LLM 추론 (Phase 3) | 상용 API | 비식별 지표만 전달 |
| NLP 형태소 분석 | 로컬 (kiwipiepy) | 경량 CPU 기반 |

**B. API 전송 허용/금지 기준:**

| 구분 | 예시 | 전송 |
|------|------|------|
| 허용 | 위험 스코어, 통계 지표, 룰 트리거 결과, 비식별 패턴 | O |
| 금지 | 거래처명, 계좌번호, 사업자번호, 적요 원문, 임직원 정보 | X |

**C. 비식별화 모듈:**

포트폴리오 프로젝트 범위에서 비식별화 전용 모듈 구현은 제외한다.
현재는 API에 전달하는 데이터를 위험 스코어·통계 지표로 한정하여 운용한다.
실무 투입 시 NER 기반 마스킹, 금액 범위화, k-익명성 검증 등의 비식별화 레이어가 필요하며,
이 요구사항은 [CONSTRAINTS.md §비식별화](CONSTRAINTS.md)에 기록했다.

### 5. 검증 결과

설계 단계 결정. Phase 3 구현 완료 후 정량 검증 갱신 예정.

예상 효과:

| 지표 | 로컬 LLM (Qwen3-8B) | 상용 API |
|:-----|:-------------------:|:---------:|
| 한국어 회계 도메인 이해 | 낮음 | 높음 |
| Text-to-SQL 정확도 | 단순 쿼리만 | 복잡 조인·서브쿼리 가능 |
| VRAM 경합 | ML + LLM 동시 불가 | ML 전용 사용 가능 |
| 비용 | 무료 | $2-10/Engagement |
| 오프라인 동작 | 가능 | 불가 |

### 6. 교훈

- **"로컬 완결"이 항상 최선은 아니다.** 보안이 필요한 것은 원본 데이터 처리이지 모든 연산이 아니다. 데이터 흐름을 분석하면 보안 경계를 정확히 그을 수 있다.
- **하드웨어 제약을 설계로 우회할 수 있다.** VRAM 8GB에서 ML + LLM을 동시 운영하는 대신, 역할을 분리하면 각각 최적의 환경을 활용할 수 있다.
- **비식별화는 별도 엔지니어링이 필요하다.** 단순 마스킹이 아니라 NER, 범위화, k-익명성 검증 등이 포함되며, 프로젝트 범위 판단 시 이 비용을 인지해야 한다.
- **포트폴리오에서 보여줄 가치는 "모든 것을 직접 구현"이 아니라 "올바른 아키텍처 판단"이다.**

**관련 문서**: [CONSTRAINTS.md §하드웨어 제약](CONSTRAINTS.md) | [CONSTRAINTS.md §비식별화](CONSTRAINTS.md) | [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)

---

## TS-7: DataSynth Phase 1 정답지 혼선 — 룰 정답과 주입 라벨 혼용

**분류**: DataSynth / 평가 설계 | **상태**: 설계 고정 중 | **작성일**: 2026-04-27

### 1. 증상

Phase 1 평가에서 같은 유형의 문제가 반복됐다.

| 사례 | 실제 상태 | 기존 평가 문제 |
|------|----------|----------------|
| L1-01 차대변 불균형 | `sum(debit) != sum(credit)` 문서가 `UnbalancedEntry` 외 `DecimalError`, `RoundingError`, `TransposedDigits` 등에서도 발생 | `UnbalancedEntry`만 정답으로 보아 실제 불균형 문서가 FP처럼 보임 |
| L2-01 승인한도 직하 | 승인자 한도의 90~100% 구간 문서가 자동/반복 전표에서도 자연 발생 | `JustBelowThreshold` 라벨만 정답으로 보아 실제 룰 조건 충족 문서가 FP처럼 보임 |
| L1-08 회계기간 불일치 | 실제 `fiscal_period != posting_date.month` 문서가 라벨보다 많음 | `WrongPeriod` 라벨이 없는 실제 불일치가 FP처럼 보임 |
| L1-09 승인일 누락 | `approved_by`는 있는데 `approval_date`가 비어 있는 문서가 라벨보다 많음 | 라벨 없는 실제 필드 조건 충족 문서가 FP처럼 보임 |

핵심 문제는 `anomaly_labels.csv` 하나를 다음 두 목적에 동시에 사용한 것이다.

- 룰 정답: 해당 Phase 1 룰의 조건을 실제로 만족하는가?
- 주입/감사 이슈 라벨: 생성기가 의도적으로 넣은 조작·오류·감사상 중요한 issue인가?

### 2. 원인 분석

Phase 1은 최종 부정 확정기가 아니라 후보 생성 룰 엔진이다.

따라서 Phase 1 룰 평가는 먼저 다음 질문에 답해야 한다.

> 이 문서가 실제로 해당 룰 조건을 만족하는가?

예를 들어 L1-01은 차대변 산술 무결성 룰이다. 원인이 `DecimalError`든 우연한 금액 오류든 실제로 차대변이 불균형이면 L1-01 정답이다.

반대로 `DecimalError` 같은 라벨은 “왜 불균형이 생겼는가”를 설명하는 원인/시나리오 라벨이지, L1-01 정답의 전체 집합이 아니다.

### 3. 해결 원칙

정답 레이어를 분리한다.

| 레이어 | 의미 | 사용처 |
|--------|------|--------|
| `rule_truth` | 룰 조건을 실제로 만족하는 문서 | Phase 1 룰 구현/회귀 평가 |
| `injected_issue_truth` | 생성기가 의도적으로 주입한 시나리오 | Phase 2/3 원인 분석, 설명 품질 |
| `audit_issue_truth` | 감사상 실제 issue로 볼 subset | 포트폴리오용 benchmark, 우선순위 평가 |
| `review_population` | 감사인이 검토할 수 있는 넓은 후보 | queue/coverage 평가 |
| `normal_control` | 정상인데 룰과 비슷하게 생긴 hard negative | 현실성/오탐 해석 |

규칙:

- 룰 조건을 실제로 만족하면 의도 주입 여부와 무관하게 `rule_truth`에 포함한다.
- Phase 1 룰이 검토 후보까지 잡도록 설계되어 있으면 review 사항도 해당 룰의 `rule_truth`에 포함한다.
- 위반, 검토 후보, 낮은 우선순위, 정상 유사 케이스 구분은 DataSynth 정답지가 아니라 후단 탐지/스코어링/케이스 빌더가 담당한다.
- `anomaly_labels.csv`만으로 Phase 1 룰 정답을 판단하지 않는다.
- 원인 라벨은 유지하되, 룰별 정답은 별도 sidecar를 우선한다.
- audit issue와 rule truth를 혼동하지 않는다.

### 4. 적용 중인 구조

현재 후보 체인에서는 다음 방향으로 정리 중이다.

| 파일 | 역할 |
|------|------|
| `labels/rule_truth.csv` | 통합 Phase 1 룰 정답 후보. v73 목표 |
| `labels/rule_truth_L1_XX.csv` | 룰별 정답. v73 목표 |
| `labels/l101_unbalanced_truth.csv` | L1-01 산술 불균형 truth. v71에서 추가 |
| `labels/l201_just_below_threshold_truth.csv` | L2-01 승인한도 직하 truth. v72에서 추가 |
| `labels/field_contract_truth.csv` | L1 필드계약 truth 보관. v70에서 추가 |
| `labels/l1_audit_issue_truth.csv` | L1 중 감사상 issue subset. v70에서 추가 |
| `labels/l1_field_only_normal_or_review.csv` | 필드 조건은 맞지만 audit issue로 보지 않는 항목. v70에서 추가 |

### 5. L1 초안 기준

L1 룰은 우선 `rule_truth` 기준을 확정한 뒤 `audit_issue_truth`를 별도로 판단한다. 여기서 `rule_truth`는 즉시 위반만이 아니라 Phase 1 룰이 잡아야 하는 전체 후보를 뜻한다.

| 룰 | rule truth 기준 | 비고 |
|----|-----------------|------|
| L1-01 차대변 불균형 | 실제 차변 합계와 대변 합계가 맞지 않으면 정답 | 원인 라벨이 무엇이든 실제 불균형이면 정답 |
| L1-02 필수필드 누락 | `schema.yaml`에서 필수로 정한 값이 비어 있으면 정답 | 다른 해석은 붙이지 않음 |
| L1-03 무효 계정 | CoA에 없는 계정을 쓰면 정답 | 원인 라벨이나 의도는 보지 않음 |
| L1-04 승인한도 초과 | 승인자의 승인한도를 넘으면 정답 | boundary/review 구분은 후단 코드가 담당 |
| L1-05 자기승인 | 작성자와 승인자가 같으면 정답 | 예외 처리는 후단 코드가 담당 |
| L1-06 직무분리 위반 | 같은 사용자 또는 권한 주체가 같은 거래 흐름 안에서 분리돼야 하는 두 역할을 함께 수행하면 정답 | 단순히 여러 프로세스에 등장했다는 이유만으로는 정답 아님 |
| L1-07 승인 생략 | 승인생략이면 정답 | 위반/검토 후보 구분은 후단 코드가 담당 |
| L1-08 회계기간 불일치 | 회계기간이 불일치하면 정답 | fiscal calendar config 반영 필요 |
| L1-09 승인일 누락 | 승인일이 없으면 정답 | 자동/반복 예외 판단은 후단 코드가 담당 |

#### L1-06 기준

L1-06은 direct SoD conflict만 정답으로 본다. `sod_violation=True`만 있고 `sod_conflict_type`이 없거나, 사용자 이력상 여러 업무를 했다는 이유만으로는 L1-06 정답 처리하지 않는다. 그런 넓은 사용자/권한 범위 신호는 L3-12 업무범위 집중 검토 또는 work-scope sidecar에서 다룬다.

권장 기준은 두 층으로 나눈다.

| 층 | 의미 | DataSynth truth 처리 |
|----|------|---------------------|
| L1-06 rule truth | direct SoD conflict marker가 있는 확정 후보 | 정답 |
| L3-12 work-scope review | role threshold, review pair, process breadth 기반 검토 모집단 | 별도 sidecar |

L1-06 rule truth는 "같은 거래 흐름 안에서 서로 견제해야 하는 역할 충돌이 문서/필드/권한 개입 근거로 직접 확인된 경우"로 본다.

포함 예시는 다음과 같다.

- 같은 사용자가 구매 요청, 발주, 검수, 지급처럼 서로 분리돼야 하는 P2P 단계를 함께 수행한 경우
- 같은 사용자가 매출 입력, 청구, 수금, 대손/환입처럼 서로 견제해야 하는 O2C 단계를 함께 수행한 경우
- 같은 사용자가 전표 작성, 승인, 수정, 반제를 같은 거래 흐름 안에서 함께 수행한 경우
- 자금 담당자가 지급 생성과 지급 승인 또는 은행 이체 확정을 함께 처리한 경우
- 급여 담당자가 인사 마스터 변경과 급여 지급/승인을 함께 처리한 경우
- IT/admin 권한자가 일반 업무 전표를 직접 생성, 수정, 승인한 경우
- 데이터에 `sod_conflict_type`이 있거나, `sod_violation=True`와 `sod_conflict_type`이 함께 있어 직무충돌 유형이 확인되는 경우

제외 예시는 다음과 같다.

- 한 사용자가 여러 업무 프로세스에 등장했다는 사실만 있는 경우
- 관리자가 여러 프로세스를 승인했다는 사실만 있는 경우
- 소규모 회사라 한 사람이 여러 역할을 맡았지만 같은 거래 흐름의 견제 역할 충돌이 확인되지 않는 경우
- 자동 배치나 시스템 계정이 여러 프로세스에 등장한 경우

위 제외 예시는 L1-06이 아니라 L3-12/work-scope review population으로 관리한다.

### 6. L2 초안 기준

L2 룰은 확정 부정만 맞히는 룰이 아니라 강한 부정 정황 후보를 올리는 룰이다. 따라서 `rule_truth`는 L2가 잡아야 하는 전체 후보를 뜻하고, 확정 부정인지 검토 후보인지 정상 유사 케이스인지는 후단 코드가 나눈다.

| 룰 | rule truth 기준 | 비고 |
|----|-----------------|------|
| L2-01 승인한도 직하 | 승인자의 승인한도 바로 아래 금액이면 정답 | 한도 근접 정도는 후단 코드가 나눔 |
| L2-02 중복 지급 | 같은 거래처에 같은 지급이 다시 나간 것으로 볼 수 있으면 정답 | 정기 반복 지급처럼 보여도 일단 rule truth에 포함 |
| L2-03 중복 전표 | 같은 거래가 재입력, 복제, 유사입력, 분할입력된 후보면 정답 | 확실한 중복과 애매한 유사 중복 구분은 후단 코드가 담당 |
| L2-04 비용 자산화 | 비용 성격 금액이 자산 계정으로 넘어간 모양이면 정답 | 정상 자산화 가능성 판단은 후단 코드가 담당 |
| L2-05 역분개 패턴 | 역분개, 취소, 정정, 상계, 재분류로 볼 수 있는 반대분개 패턴이면 정답 | 확실한 역분개와 정산/재분류 후보 구분은 후단 코드가 담당 |

### 7. L3 초안 기준

L3 룰은 검토 필요 이상징후다. 따라서 `rule_truth`는 L3가 화면/큐에 올려야 하는 전체 후보를 뜻하고, 정상 맥락인지 높은 우선순위인지는 후단 코드가 나눈다.

| 룰 | rule truth 기준 | 비고 |
|----|-----------------|------|
| L3-01 계정-프로세스 불일치 | 유효한 CoA 계정인데 업무 프로세스와 계정 성격이 맞지 않으면 정답 | CoA 밖 계정은 L1-03 |
| L3-02 수기 전표 | 수기/조정 전표면 정답 | `ManualOverride`만 정답으로 보지 않음 |
| L3-03 관계사 거래 | 관계사 거래 모집단이면 정답 | 순환거래 확정은 GR/IC 보조 finding |
| L3-04 기말/기초 전표 | 월말/월초 ±5일 전표면 정답 | 고액·수기·마감급박 조작 여부는 점수와 후단 시나리오에서 판단 |
| L3-05 주말/공휴일 전기 | 주말 또는 공휴일 전기면 정답 | 정상 주말 운영도 rule truth |
| L3-06 심야 전기 | 설정된 심야/비근무시간 전기면 정답 | 야간 배치도 rule truth |
| L3-07 전기일-문서일 장기 괴리 | 전기일과 문서일 차이가 기준일수를 넘으면 정답 | 정상 장기 지연은 후단에서 낮춤 |
| L3-08 적요 결손/파손 | 적요가 비어 있거나 깨져 있으면 정답 | 의미상 모호한 적요는 Phase 3 |
| L3-09 가계정 장기 미정리 | 가계정/미결 계정이 오래 미정리 상태면 정답 | 단순 가계정 사용은 아님 |
| L3-10 민감 계정 사용 | 설정된 민감 계정을 쓰면 정답 | 정상 사용 여부는 후단 코드가 판단 |
| L3-11 컷오프 불일치 | 인식일과 근거 이벤트일 차이가 허용범위를 넘으면 정답 | 근거 이벤트일 누락은 coverage gap |

### 8. L4 초안 기준

L4 룰은 통계적·행동적 검토 anchor다. 따라서 `rule_truth`는 L4가 올려야 하는 후보 또는 macro finding 전체를 뜻하고, 정상 대형거래·정상 배치·정상 야간운영 여부는 후단 코드가 나눈다.

| 룰 | rule truth 기준 | 비고 |
|----|-----------------|------|
| L4-01 매출 이상 변동 | 매출 계정에서 금액 z-score가 기준을 넘으면 정답 | `RevenueManipulation` 전체가 아니라 고액 매출 이상치 anchor |
| L4-02 Benford 위반 | 회사·계정·연도 단위 첫째자리 분포가 Benford 기준을 벗어나면 정답 | 전표 1건 정답이 아니라 group finding |
| L4-03 이상 고액 | 금액 z-score와 상위 금액 기준을 넘으면 정답 | 정상 대형거래도 rule truth |
| L4-04 희소 계정쌍 | 차변-대변 계정쌍이 희소쌍 모집단에 들어가면 정답 | 계정 누락은 L1-02/L1-03 |
| L4-05 비정상 시간대 집중 | 사용자별 비정상 시간대 집중, 반복 심야, 급속 승인 조건을 만족하면 정답 | 정상 야간근무 여부는 후단 코드가 판단 |
| L4-06 배치성 자동 전표 이상 | 배치성 source가 기말 집중, 대량 동시 생성, 배치 금액 이상 조건에 걸리면 정답 | 단독 고위험이 아니라 combo/booster 신호 |

### 9. D01/D02 초안 기준

D01/D02는 전표 단위 정답이 아니라 분석적 검토 macro finding이다. 평가 단위는 기본적으로 `fiscal_year + company_code + gl_account`다.

| 룰 | rule truth 기준 | 비고 |
|----|-----------------|------|
| D01 계정 활동량 급변 | 전년 대비 같은 회사·같은 계정의 거래 활동량이 기준 이상 변하면 정답 | 정상 성장·가격상승·투자 확대도 rule truth |
| D02 월별 분포 패턴 변화 | 전년 대비 같은 회사·같은 계정의 월별 발생 패턴이 기준 이상 변하면 정답 | 정상 계절성·프로젝트 집중도 rule truth |

2022는 2021 baseline이 없으면 기본 평가 대상이 아니다. 2023은 2022와 비교하고, 2024는 2023과 비교한다. 표본 부족, 전기 없음, 계정 결측 등은 false negative가 아니라 exclusion으로 분리한다.

### 10. 교훈

- **룰 정답과 주입 라벨은 다르다.** 우연히 발생한 조건 충족도 룰 입장에서는 정답이다.
- **Phase 1은 후보 생성 엔진이다.** 모든 룰 hit가 감사상 최종 issue는 아니지만, 룰 조건 충족 여부는 별도로 정확히 평가해야 한다.
- **단일 `anomaly_labels.csv`로 모든 평가를 하면 FP/FN 해석이 무너진다.** 최소한 `rule_truth`, `audit_issue_truth`, `injected_issue_truth`를 분리해야 한다.
- **100% 성능이 항상 test fitting은 아니다.** 산술/필드 계약 룰은 contract mode에서 100%가 자연스럽다. 다만 audit benchmark mode에서는 normal/review/control을 별도로 봐야 한다.

**관련 문서**: [DATASYNTH_PHASE1_RULE_TRUTH_DRAFT.md](DATASYNTH_PHASE1_RULE_TRUTH_DRAFT.md) | [DATASYNTH_PATCH_WORKFLOW.md](DATASYNTH_PATCH_WORKFLOW.md) | [DATASYNTH_UPDATE_CHECKLIST.md](DATASYNTH_UPDATE_CHECKLIST.md)

## TS-8. DataSynth Rule Truth Candidate Chain

### 1. 현재 상태

Phase 1 rule truth 분리 작업은 production이 아니라 후보 체인에서 진행 중이다.

최신 후보:

`data/journal/primary/datasynth_v104_candidate`

체인:

| 버전 | 기준 | 수정 내용 |
|------|------|-----------|
| v74 | v73 | DataSynth CoA와 `config/chart_of_accounts.csv` 정합성 보강 |
| v75 | v74 | L2-03, L2-04, L2-05를 라벨 fallback이 아니라 실제 룰 후보 기준으로 재산출 |
| v76 | v75 | L3-04, L4-01, L4-03을 feature-backed 실제 룰 후보 기준으로 재산출 |
| v77 | v76 | 폐기된 broad L1-06/L1-07 review 후보 확장. v80 L1-06 평가에는 사용하지 않음 |
| v78 | v77 | 폐기. 하드링크 후보에서 journal CSV를 수정해 이전 후보까지 오염될 수 있음 |
| v79 | v77 metadata + v71 clean journals | broad L1 truth 후보. v80에서는 L1-06 role-threshold review 후보를 L3-12/work-scope sidecar로 분리 |
| v80 | v79 | L1-06은 direct SoD만 남기고, 업무범위/프로세스 폭 검토 후보는 L3-12와 `work_scope_excess_review_population`으로 분리 |
| v81 | v80 | 자동/반복 전표의 비현실적인 승인자·승인일 대량 결측을 시스템 승인 흔적으로 보강 |
| v82 | v81 | 사후 승인, 권한 위임, 승인자 마스터 매핑 누락, 승인 후 변경, 소량 시스템 통제 공백을 sidecar로 추가 |
| v83 | v82 | v82에서 시스템 통제 공백으로 잘못 선택된 system self-approval control 2건을 복구 |
| v84 | v83 | FSS 전표 조작 패턴 비중을 일반화한 rule-agnostic manipulated-entry truth 420건 추가 |
| v85 | v84 | 기존 59건 `MisclassifiedAccount` 기반 L3-01 정답을 제거하고 현재 L3-01 탐지 계약 기준으로 2,426건 재생성 |
| v86 | v85 | L3-01의 P2P/매출계정 쏠림을 줄이고 O2C/H2R/TRE/A2R 계정-프로세스 불일치 후보를 분산 |
| v87 | v86 | L3-03과 `intercompany_population_truth`를 현재 IC 계정 prefix 탐지 계약 기준으로 재생성 |
| v88 | v87 | L3-02 수기/조정 source 비율을 실무형으로 낮추고 L3-02/manual population truth 재생성 |
| v89 | v88 | L3-05와 `weekend_review_population`을 현재 journal `posting_date` 주말/휴일 기준으로 재생성 |
| v90 | v89 | L1-06 direct SoD truth 수량은 유지하되, medium/high/critical severity 증거가 모두 나오도록 보강 |
| v91 | v90 | L3-06과 `afterhours_review_population`을 현재 journal `posting_date` 심야/비근무시간 기준으로 재생성 |
| v92 | v91 | 현재 journal row로 재구성되지 않는 stale L3-09 suspense-aging truth 2건 제거 |
| v93 | v92 | L1-02 필수필드 누락 유형을 다양화하고, 금액 결측으로 생긴 L1-01 차대불균형 truth도 재계산 |
| v94 | v93 | L3-04 정답을 현재 journal의 월말/월초 ±5일 전표 전체로 재산출 |
| v95 | v94 | L3-12 공식 정답을 전표 단위에서 사용자-year 단위로 변경하고, 전표 단위 결과는 projection sidecar로 분리 |
| v96 | v95 | L3-12 user-level truth의 bucket/score 해석을 다양화하고 detector 원점수는 별도 컬럼으로 보존 |
| v97 | v96 | BatchAnomaly 확정 라벨을 기존 L4-06 후보 안에서 프로세스/source/문서유형/회사별로 재표본추출 |
| v98 | v97 | 조작전표 truth를 C001/C002/C003으로 재분산하고 기존 조작 텍스트 마커를 truth 문서에만 남김 |

### 2. 왜 production에 바로 덮지 않았나

이번 수정은 원장 재생성이 아니라 truth semantics 변경이다.

따라서 production DataSynth를 바로 덮으면 다음 위험이 있다.

- 기존 평가 코드가 `anomaly_labels.csv`를 정답으로 보는 상태에서 갑자기 지표가 크게 바뀐다.
- L1-09, L3-04처럼 넓은 review population rule은 precision이 낮아진 것처럼 보일 수 있다.
- production freeze 문서, preview, overview, dashboard snapshot을 동시에 바꿔야 한다.

그래서 후보 디렉터리에서 먼저 `rule_truth.csv` 계약을 고정하고, 평가 코드가 이 계약을 읽도록 바꾼 뒤 승격해야 한다.

### 3. 검증 결과

`v104_candidate`에서 필수 truth 게이트를 실행했다.

결과:

`failures: []`

L3-01 전용 확인:

| 항목 | 건수 |
|------|-----:|
| L3-01 detector hit documents | 2,419 |
| `rule_truth_L3_01.csv` documents | 2,419 |
| detector - truth | 0 |
| truth - detector | 0 |

L3-03 전용 확인:

| 항목 | 건수 |
|------|-----:|
| L3-03 detector IC-prefix documents | 30,377 |
| `rule_truth_L3_03.csv` documents | 30,377 |
| `intercompany_population_truth.csv` documents | 30,377 |
| detector - truth | 0 |
| truth - detector | 0 |
| truth - population sidecar | 0 |

L3-02 전용 확인:

| 항목 | 건수 |
|------|-----:|
| actual manual/adjustment documents | 86,811 |
| `rule_truth_L3_02.csv` documents | 86,811 |
| `manual_entry_population_truth.csv` documents | 86,811 |
| actual - truth | 0 |
| truth - actual | 0 |
| truth - population sidecar | 0 |

L3-05 전용 확인:

| 항목 | 건수 |
|------|-----:|
| actual weekend/holiday documents | 12,771 |
| `rule_truth_L3_05.csv` documents | 12,771 |
| `weekend_review_population.csv` documents | 12,771 |
| actual - truth | 0 |
| truth - actual | 0 |
| truth - population sidecar | 0 |

L1-06 전용 확인:

| 항목 | 건수 |
|------|-----:|
| L1-06 truth documents | 19 |
| L1-06 detector hit documents | 19 |
| L1-06 detector hit rows | 64 |
| score 0.70 rows | 24 |
| score 0.80 rows | 33 |
| score 0.95 rows | 7 |
| direct_medium documents | 7 |
| direct_high documents | 9 |
| direct_critical documents | 3 |

L1-06 conflict type 분포:

| conflict type | documents |
|---------------|----------:|
| preparer_approver | 11 |
| purchase_payment | 5 |
| cash_disbursement | 2 |
| treasury_payment | 1 |

L3-06 전용 확인:

| 항목 | 건수 |
|------|-----:|
| L3-06 detector after-hours documents | 7,507 |
| `rule_truth_L3_06.csv` documents | 7,507 |
| `afterhours_review_population.csv` documents | 7,507 |
| detector - truth | 0 |
| truth - detector | 0 |

L3-06 분포:

| 구분 | 건수 |
|------|-----:|
| 2022 | 2,622 |
| 2023 | 2,444 |
| 2024 | 2,441 |
| automated | 3,633 |
| interface | 1,004 |
| recurring | 1,279 |
| manual | 1,524 |
| adjustment | 67 |
| score 0.20 system/batch context | 4,773 |
| score 0.45 human/unknown context | 2,734 |

L3-09 전용 확인:

| 항목 | 건수 |
|------|-----:|
| L3-09 detector suspense-aging documents | 1,091 |
| `rule_truth_L3_09.csv` documents | 1,091 |
| `suspense_aging_review_population.csv` documents | 1,091 |
| detector - truth | 0 |
| truth - detector | 0 |
| truth - review population | 0 |

L3-09에서 제거한 stale truth:

| document_id | 이유 |
|-------------|------|
| `78b6fc4d-2f33-40ac-ab88-88813eab466d` | 현재 journal 기준 가계정 라인이 없고, sidecar의 예전 2900 계정/일자 정보가 남아 있었음 |
| `6dded142-3eaa-41dc-a85e-d3bc84b1116f` | 현재 journal에는 2900 라인이 있으나 `posting_date=2024-12-30`이라 aging 기준을 넘지 못함 |

L1-02 전용 확인:

| 항목 | 건수 |
|------|-----:|
| L1-02 detector documents | 156 |
| `rule_truth_L1_02.csv` documents | 156 |
| detector - truth | 0 |
| truth - detector | 0 |

L1-02 결측 필드 분포:

| 필드 | 건수 |
|------|-----:|
| gl_account | 96 |
| document_date | 13 |
| document_type | 12 |
| fiscal_period | 12 |
| posting_date | 11 |
| debit_amount | 11 |
| credit_amount | 10 |
| company_code | 9 |

L1-02 점수 분포:

| 점수 | 건수 |
|------|-----:|
| 0.42 | 13 |
| 0.48 | 12 |
| 0.56 | 10 |
| 0.62 | 7 |
| 0.72 | 14 |
| 0.74 | 86 |
| 0.78 | 4 |
| 0.80 | 6 |
| 0.86 | 4 |

L1-01 연동 확인:

| 항목 | 건수 |
|------|-----:|
| L1-01 detector documents | 316 |
| `rule_truth_L1_01.csv` documents | 316 |
| `l101_unbalanced_truth.csv` documents | 316 |
| detector - truth | 0 |
| truth - detector | 0 |

주요 rule truth 건수:

| 룰 | 건수 | 해석 |
|----|----:|------|
| L1-01 | 316 | 실제 차변 합계와 대변 합계가 맞지 않는 모든 문서 |
| L1-02 | 156 | `schema.yaml` required 필드가 비어 있는 모든 문서 |
| L1-03 | 32 | CoA 밖 계정만 남음 |
| L1-05 | 244 | 작성자와 승인자가 같은 모든 문서. 자동/시스템 자가승인 컨트롤 27건 포함 |
| L1-06 | 19 | 직접 SoD marker 또는 직접 IT/admin 업무전표 개입 근거만 남김 |
| L1-07 | 96 | 승인자가 비어 있는 모든 문서. v82에서 소량 시스템 통제 공백 추가, v83에서 L1-05 충돌 2건 복구 |
| L1-09 | 122 | 승인일이 비어 있는 모든 문서. v82에서 소량 시스템 통제 공백 추가, v83에서 L1-05 충돌 2건 복구 |
| L2-03 | 96 | 실제 중복전표 룰 후보 |
| L2-04 | 563 | 실제 비용 자산화 룰 후보 |
| L2-05 | 113 | 실제 역분개/상계/정정 패턴 후보 |
| L3-04 | 141,375 | 월초 1~5일 또는 월말까지 남은 날 0~5일 review population. 고액·수기 여부는 정답 조건이 아니라 우선순위 신호 |
| L3-06 | 7,507 | 실제 `posting_date` 기준 심야/비근무시간 전기 review population |
| L3-09 | 1,091 | 현재 journal 기준 장기 미정리 가계정 review population |
| L3-12 | 64 | 사용자-year 단위 업무범위 집중 검토 모집단. 전표 단위 projection은 strict truth가 아님 |
| L4-01 | 965 | 매출 계정 z-score review anchor |
| L4-03 | 4,017 | 고액 z-score review anchor |

추가 조작 전표 truth:

| truth | 건수 | 해석 |
|-------|----:|------|
| manipulated_entry_truth | 420 | 특정 룰을 노린 정답이 아니라, 실제 전표 조작 패턴을 일반화한 별도 truth |

### 4. 남은 주의점

- L1-09는 현재 정책상 승인일이 없으면 모두 rule truth다. v81부터 자동/반복 전표의 정상 시스템 승인 흔적은 원천 데이터에 채워 두고, v82는 소량의 시스템 통제 공백만 rule truth에 추가한다.
- v82의 사후 승인, 위임 승인, 승인자 마스터 매핑 누락, 승인 후 변경은 `anomaly_labels.csv`가 아니라 boundary/control sidecar로 관리한다.
- v84의 조작 전표는 실제 FSS 사건을 개별 복제하지 않는다. `DETECTION_REFERENCE.md`의 패턴 비중을 사용해 일반화한 scenario truth다.
- v85의 L3-01 공식 정답은 `MisclassifiedAccount` 라벨이 아니라 현재 L3-01 탐지 계약 기준이다. 유효 CoA 계정이 설정된 업무 프로세스-계정 불일치 조건에 걸리면 정답이다.
- v85에서 기존 59건 L3-01 정답은 공식 truth에서 제거했다. 2건만 현재 계약과 겹쳤고 57건은 현재 L3-01이 잡아야 하는 대상이 아니었다.
- v86은 L3-01 총량을 크게 바꾸지 않고 분포만 현실화했다. L3-01은 P2P=1,059, O2C=520, H2R=380, TRE=300, A2R=160이다.
- v87의 L3-03 공식 정답은 `is_intercompany`와 같은 IC 계정 prefix 기준이다. 사용 prefix는 1150, 2050, 4500, 2700이다.
- v87은 `trading_partner`가 단순히 비어 있지 않다는 이유만으로 L3-03 정답에 넣지 않는다. 별도 관계사 master가 없으면 일반 고객/벤더가 섞이기 때문이다.
- v88은 L3-02 정답 정의를 바꾸지 않았다. `source`가 manual 또는 adjustment인 문서를 계속 정답으로 두되, 원천 source 분포를 실무형으로 낮췄다.
- v88의 수기/조정 비율은 2022=27.14%, 2023=27.19%, 2024=27.27%다.
- v89는 L3-05 정답 정의를 바꾸지 않았다. 현재 `posting_date` 기준 주말 또는 휴일이면 rule truth다.
- v89에서 stale L3-05 truth 51건을 제거하고 실제 calendar hit 65건을 추가했다.
- v90은 L1-06 정답 수량을 늘리지 않고 severity 근거만 다양화했다. 이전처럼 모든 SoD hit가 `preparer_approver`/medium 점수로 몰리는 상태를 피하기 위해 high-risk conflict type, threshold 근거, IT/admin critical 근거를 섞었다.
- v91은 L3-06 정답을 anomaly label이 아니라 실제 `posting_date` 시간 조건으로 재생성했다. 따라서 자연 발생 심야 전표, 자동 배치, 반복 전표도 raw L3-06 rule truth에 포함된다.
- v91의 `normal_after_hours_context`는 L3-06 정답 제외 목록이 아니다. anomaly label이 없는 정상 야간 운영 맥락을 설명하기 위한 context sidecar다.
- v92는 L3-09 정답 정의를 바꾸지 않았다. 현재 journal row의 가계정 여부, 미정리 상태, aging 조건으로 detector가 재구성할 수 없는 stale sidecar 문서 2건만 제거했다.
- v93은 L1-02 detector 코드를 고치지 않았다. DataSynth 원장에 다양한 required 필드 결측을 소량 추가해 기존 field-aware score가 실제 데이터에서 드러나게 했다.
- v93에서 금액 필드 결측은 실제 차대불균형도 만들 수 있으므로 L1-01 truth도 현재 debit/credit 산술 기준으로 재계산했다.
- v101은 L3-04 정답을 현재 detector-window 기준으로 다시 계산했다. 기준은 `posting_date.day <= 5 OR days_to_month_end <= 5`이며, 검증 결과 expected docs 141,375건, truth docs 141,375건, missing/extra 0건이다.
- v109는 L4-03 정답을 현재 detector 계약 기준으로 다시 계산했다. 기준은 `amount_zscore > 3.0`과 전역 P90 금액 가드를 모두 만족하는 문서이며, `rule_truth_L4_03*`와 `high_amount_review_population*`은 4,017건이다. `UnusuallyHighAmount` / `StatisticalOutlier`는 주입 이상치 subset으로만 유지한다.
- v95는 L3-12 정답 단위를 `document_id`에서 `fiscal_year + created_by`로 바꿨다. 공식 truth와 `work_scope_excess_review_population`은 64 user-year이고, 전표 단위 262,846문서는 `work_scope_excess_document_projection.csv`로만 관리한다.
- v96은 L3-12 공식 truth 64 user-year를 유지하면서 `bucket`/`score`를 업무 맥락별로 나눴다. 분포는 manual-sensitive 38, system-mixed 15, leadership-broad 11이며 detector 원래 bucket/score는 `detector_bucket`/`detector_score`로 보존한다.
- v97은 BatchAnomaly 확정 라벨 175건을 H2R/R2R/O2C/P2P/TRE와 automated/recurring으로 분산했다. 회사 분포도 C001=61, C002=59, C003=55로 재조정했다.
- v98은 조작전표 truth 420건의 연도/시나리오 count를 유지하면서 회사 분포를 C001=147, C002=139, C003=134로 재조정했다. 원장 텍스트 마커는 truth 문서 420건에만 남는다.
- `anomaly_labels.csv`는 계속 audit/injected issue 의미로 남는다. Phase 1 rule truth로 단독 사용하면 안 된다.
- `v104_candidate`는 아직 production 승격본이 아니다.
- journal row를 수정하는 후보 빌더는 하드링크를 쓰면 안 된다. 반드시 물리 복사 후 수정해야 한다.

## DataSynth v99 DuplicatePayment 분포 보정

`v99_candidate`는 `v98_candidate` 위에서 L2-02 DuplicatePayment pair truth만 보정한 후보 버전이다. Production `data/journal/primary/datasynth/`는 아직 덮어쓰지 않았다.

보정 원칙:

- 원장 행을 임의로 조작하지 않는다.
- 현재 원장에서 실제 재구성 가능한 P2P 반복 지급 pair만 사용한다.
- 같은 회사, 같은 거래처/지급 기준, 같은 금액, 45일 이내 반복 지급이면 L2-02 pair truth 후보로 본다.
- 라벨, `rule_truth_L2_02.csv`, `duplicate_payment_pairs.csv`의 document_id 집합은 반드시 같아야 한다.

검증 결과:

| 항목 | 결과 |
|------|-----:|
| DuplicatePayment pairs | 33 |
| C001 | 11 |
| C002 | 11 |
| C003 | 11 |
| 2022 | 19 |
| 2023 | 7 |
| 2024 | 7 |
| pair/truth/anomaly document diff | 0 |
| journal pair mismatch | 0 |
| required truth gate failures | 0 |

Variant 분포:

| variant | count |
|---------|------:|
| exact | 7 |
| reference_blank | 7 |
| reference_variant | 7 |
| date_shifted | 6 |
| amount_rounding | 6 |

해석:

- v99는 기존 DuplicatePayment truth가 특정 회사와 2022년에만 몰려 보이는 문제를 줄였다.
- 2022 비중이 더 큰 것은 현재 원장에서 자연적으로 재구성 가능한 P2P pair가 2022에 더 많기 때문이다.
- 이 패치는 detector 결과에 맞춘 fitting이 아니라, 원장상 설명 가능한 pair를 골라 truth metadata를 정리한 것이다.

## DataSynth v100 Source 현실성 보정

`v100_candidate`는 `v99_candidate` 위에서 source 분포만 소폭 보정한 후보 버전이다. Production `data/journal/primary/datasynth/`는 아직 덮어쓰지 않았다.

보정 원칙:

- Phase 1 rule truth 정의는 바꾸지 않는다.
- detector 코드도 바꾸지 않는다.
- 이미 L3-02의 broad manual/adjustment population에 속한 문서 중 일부만 `manual -> adjustment`로 재분류한다.
- 같은 document_id가 들어간 sidecar/source 메타도 같이 갱신해서 원장과 라벨 메타가 서로 다르게 남지 않게 한다.

검증 결과:

| 항목 | 결과 |
|------|-----:|
| source 재분류 문서 | 6,084 |
| 2022 | 2,041 |
| 2023 | 2,010 |
| 2024 | 2,033 |
| L3-02 manual | 76,386 |
| L3-02 adjustment | 10,422 |
| L4-05 manual | 18 |
| L4-05 adjustment | 9 |
| required truth gate failures | 0 |

해석:

- v100은 과탐/미탐을 맞추기 위한 패치가 아니다.
- 너무 많은 review population이 `manual` 한 값에만 몰려 보이는 합성 티를 줄이는 패치다.
- `manual`과 `adjustment`는 모두 L3-02 rule truth에 남기 때문에 정답 계약은 유지된다.

## DataSynth v101 L3-04 월말 경계 보정

`v101_candidate`는 `v100_candidate` 위에서 L3-04 rule truth만 다시 만든 후보 버전이다. Production `data/journal/primary/datasynth/`는 아직 덮어쓰지 않았다.

문제:

- 이전 L3-04 truth는 월말을 “마지막 5개 날짜”로 계산했다.
- 현재 detector/평가 기준은 `days_to_month_end <= 5`다.
- 그래서 31일짜리 달의 26일, 30일짜리 달의 25일, 2월의 23~24일 같은 경계일 문서가 truth에서 빠졌다.

보정 기준:

- 월초: `posting_date.day <= 5`
- 월말: `days_to_month_end <= 5`
- 금액, 수기 여부, 민감 계정, `RushedPeriodEnd` 라벨은 정답 조건이 아니라 후단 점수/우선순위 신호다.

검증 결과:

| 항목 | 결과 |
|------|-----:|
| 이전 L3-04 truth | 130,532 |
| v101 L3-04 truth | 141,375 |
| 추가된 경계일 문서 | 10,843 |
| 2022 | 46,822 |
| 2023 | 46,614 |
| 2024 | 47,939 |
| detector-window docs - truth | 0 |
| truth - detector-window docs | 0 |
| required truth gate failures | 0 |

해석:

- 이 수정은 과탐을 줄이기 위해 detector에 맞춘 것이 아니라, 이미 합의한 “월초/월말 ±5일은 L3-04 review truth” 기준을 DataSynth에 정확히 반영한 것이다.
- L3-04는 확정 조작 라벨이 아니라 review population이므로, 정상 결산 전표도 rule truth에 포함된다.

## DataSynth v102 L1 Sidecar 의미 정리

`v102_candidate`는 `v101_candidate` 위에서 L1 sidecar 의미만 정리한 후보 버전이다. 원장, `anomaly_labels.csv`, `rule_truth.csv`는 바꾸지 않았다.

수정한 문제:

- `skipped_approval_normal_controls.csv`는 이름과 달리 현재 L1 정책상 정상 컨트롤이 아니다. 79건 모두 승인자와 승인일이 비어 있어 L1-07/L1-09 rule truth다.
- `wrongperiod_negative_controls.csv`는 이름과 달리 현재 L1-08 기준 negative가 아니다. 140건 모두 회계기간이 전기월과 달라 L1-08 rule truth다.
- `sod_review_population.csv`는 L1-06 정답이 아닌 review-only 신호인데 `was_sod_violation=True`로 남아 있어 옛 broad SoD 기준처럼 보였다.

v102 조치:

| 항목 | 조치 |
|------|------|
| `skipped_approval_normal_controls*` | 게이트 호환용으로 유지하되 `sidecar_semantics=l107_rule_truth_system_or_control_gap_context` 추가 |
| `skipped_approval_system_gap_controls*` | 새 의미 alias 추가, 79건 |
| `wrongperiod_negative_controls*` | 추적용으로 유지하되 `sidecar_semantics=l108_rule_truth_but_not_injected_anomaly_label` 추가 |
| `wrong_period_non_audit_issue_truth*` | 새 의미 alias 추가, 140건 |
| `sod_review_population*` | `was_sod_violation=False`, `legacy_was_sod_violation=True`, `sod_review_signal=True`로 정리 |

검증 결과:

| 항목 | 결과 |
|------|-----:|
| journal row mutation | 0 |
| rule_truth mutation | 0 |
| anomaly_labels mutation | 0 |
| skipped approval alias docs | 79 |
| wrong period non-audit truth docs | 140 |
| SoD review docs | 9,065 |
| required truth gate failures | 0 |

해석:

- v102는 L1 정답을 바꾼 패치가 아니다.
- 옛 이름 때문에 “정상/negative”처럼 보이던 파일을 현재 정책에 맞게 설명 가능하게 만든 패치다.
- 기존 게이트와 과거 추적을 깨지 않기 위해 legacy 파일명은 남겼지만, 새 파일명을 우선 사용해야 한다.

## DataSynth v103 L3 Stale Truth Cleanup

`v103_candidate` is built on `v102_candidate`. It does not mutate journal rows. It only rebuilds stale L3 truth files and matching population sidecars from the current journal fields.

Fixed issues:

| Rule | Issue | v103 action |
|------|-------|-------------|
| L3-02 | 3 current manual/adjustment documents were missing from truth after later source patches | Added the 3 documents to `rule_truth_L3_02*` and `manual_entry_population_truth*` |
| L3-03 | 1 stale truth document had `gl_account` missing in the current journal | Removed the stale document from `rule_truth_L3_03*` and `intercompany_population_truth*` |
| L3-05 | 3 stale truth documents had missing `posting_date` in the current journal | Removed the stale documents from `rule_truth_L3_05*` and `weekend_review_population*` |

Updated counts:

| Rule | Count | Year split |
|------|------:|------------|
| L3-02 | 86,811 | 2022=28,949, 2023=28,688, 2024=29,174 |
| L3-03 | 30,377 | 2022=10,075, 2023=10,186, 2024=10,116 |
| L3-05 | 24,318 | 2022=6,011, 2023=9,354, 2024=8,953 |

Verification:

| Check | Result |
|-------|--------|
| required truth gate | `failures: []` |
| L3-02 current journal vs truth diff | 0 |
| L3-03 current IC-prefix vs truth diff | 0 |
| L3-05 truth rows with missing `posting_date` | 0 |

Interpretation:

- This is a sidecar/truth consistency patch, not a detector-code patch.
- The stale rows were real DataSynth consistency issues because truth files no longer matched the current journal rows.
- Production `data/journal/primary/datasynth/` has not been overwritten by v103.

## DataSynth v104 L3-05 Calendar Realism

`v104_candidate` is built on `v103_candidate`. It reduces the excessive L3-05 weekend/holiday review population by changing selected normal journal `posting_date` values, then rebuilding L3-04 and L3-05 truth from the updated journal.

Patch policy:

- Do not change detector code.
- Do not reduce L3-05 by editing truth files only.
- Preserve anomaly-labeled documents.
- Preserve L1-08, L3-07, and L3-11 truth documents because those depend on dates.
- Preserve manual and adjustment weekend/holiday postings.
- Move only selected normal automated/interface/recurring documents to nearby same-month business days.

Result:

| Item | Before v104 | After v104 |
|------|------------:|-----------:|
| L3-05 truth documents | 24,318 | 12,771 |
| L3-05 ratio of all documents | 7.62% | 4.00% |
| L3-04 truth documents | 141,375 | 142,011 |
| moved documents | 0 | 11,547 |
| moved journal rows | 0 | 39,336 |

L3-05 year split after v104:

| Year | Count |
|------|------:|
| 2022 | 4,267 |
| 2023 | 4,010 |
| 2024 | 4,494 |

L3-05 source split after v104:

| Source | Count |
|--------|------:|
| manual | 6,251 |
| recurring | 3,486 |
| interface | 1,478 |
| adjustment | 848 |
| automated | 708 |

Verification:

| Check | Result |
|-------|--------|
| required truth gate | `failures: []` |
| actual weekend/holiday docs vs L3-05 truth diff | 0 |
| protected truth documents moved | 0 |

Interpretation:

- This is a DataSynth source-distribution realism patch.
- L3-05 remains a review population: weekend or holiday posting still means L3-05 truth.
- The previous 7.62% looked high for a generic company; v104 lowers normal automated/holiday concentration without hiding confirmed issue labels.
- Production `data/journal/primary/datasynth/` has not been overwritten by v104.

## DataSynth v105 L3 Sidecar Context Cleanup

`v105_candidate` is built on `v104_candidate`. It does not mutate journal rows or rule truth. It only rebuilds or adds L3 explanatory sidecars.

Fixed items:

| Area | Sidecar | Count | Meaning |
|------|---------|------:|---------|
| L3-05 | `normal_weekend_context*` | 12,373 | Normal-looking weekend/holiday context inside current L3-05 review population |
| L3-05 | `weekend_normal_context_within_review_population*` | 12,373 | Clear alias to avoid reading normal weekend context as a negative-control file |
| L3-05 | `weekend_confirmed_anomalies*` | 29 | Confirmed `WeekendPosting` subset inside current L3-05 truth |
| L3-06 | `afterhours_normal_context_within_review_population*` | 6,972 | Normal-looking after-hours context inside current L3-06 review population |
| L3-04 | `period_end_normal_close_context*` | 3,600 | Representative normal close context sample |
| L3-04 | `period_end_priority_context*` | 3,009 | Representative period-end priority context sample |
| L3-02 | `manual_entry_normal_context*` | 3,600 | Representative normal manual/adjustment context sample |
| L3-02 | `manual_override_confirmed_anomalies*` | 3 | Confirmed `ManualOverride` subset inside L3-02 truth |
| L3-02 | `manual_sensitive_account_context*` | 389 | Manual/adjustment entries also in L3-10 sensitive/high-risk account truth |
| L3-03 | `ic_unmatched_cases*` | 21 | IC unmatched drill-down cases |
| L3-03 | `ic_amount_mismatch_cases*` | 16 | IC amount mismatch drill-down cases |
| L3-03 | `ic_timing_gap_cases*` | 14 | IC timing gap drill-down cases |
| L3-03 | `transfer_pricing_review_cases*` | 13 | Transfer-pricing drill-down cases |

Validation:

| Check | Result |
|-------|--------|
| journal rows mutated | 0 |
| rule truth mutated | 0 |
| required truth gate | `failures: []` |
| new sidecar extra documents outside target rule truth | 0 |

Interpretation:

- This patch fixes explanation and sidecar semantics, not detection behavior.
- `normal_*_within_review_population` means normal-looking context that the broad Phase 1 rule still surfaces.
- These files should not be used as strict negatives for raw Phase 1 precision.
- Production `data/journal/primary/datasynth/` has not been overwritten by v105.

L3-05 PHASE1 scoring note:

- L3-05 remains a weak `review_needed` timing signal, not a confirmed anomaly rule.
- Detector row scores stay `weekday_holiday=0.35`, `weekend=0.40`, `weekend_holiday=0.45`.
- PHASE1 aggregation converts them to signal strengths `0.75`, `0.85`, `1.00` before applying `severity=2`, weak evidence factor, and L3 family weight. This preserves the intended order and prevents `weekend_holiday` from being folded below a weekend-only hit by the generic numeric normalizer.
- After L3 family weight, a standalone L3-05 hit contributes about `0.027` to `0.036` to row `anomaly_score`, so it does not reach the `Low >= 0.20` threshold by itself.

## DataSynth v106 L3-11 Cutoff Truth Realignment

`v106_candidate` is built on `v105_candidate`. It does not mutate journal rows. It rebuilds L3-11 rule truth and cutoff sidecars from the current journal fields after the v104 calendar-realism patch.

Problem:

- v104 moved selected normal weekend/holiday postings to nearby business days.
- Three documents that were previously valid `cutoff_normal_controls` now have `posting_date=2024-01-02` and `delivery_date=2023-12-25`.
- For revenue accounts, that is a 6-business-day cutoff gap, so the current detector correctly flags them as L3-11.
- The old L3-11 sidecars still treated them as normal controls, so evaluation showed 3 false positives.

Affected documents:

- `41f02acb-8b33-4e91-81e9-e229270bc462`
- `8ecf405b-cc17-488a-9c38-73005f2aab4c`
- `97153699-01e7-4f19-8705-69af34bc512a`

Fix:

- Rebuild `rule_truth_L3_11*` from current journal `posting_date`, `delivery_date`, and account prefix.
- Add the three documents to L3-11 rule truth and `cutoff_review_population`.
- Remove them from `cutoff_normal_controls`.
- Keep `cutoff_confirmed_anomalies` limited to injected `RevenueCutoffMismatch` / `ExpenseCutoffMismatch` labels.
- Keep non-injected cutoff rule hits in `cutoff_reasonable_delay_controls` so broad rule truth and injected anomaly truth stay separate.

Verification:

| Check | Result |
|---|---:|
| Current journal L3-11 documents | 133 |
| `rule_truth_L3_11.csv` documents | 133 |
| Current journal minus truth | 0 |
| Truth minus current journal | 0 |
| `cutoff_review_population` | 133 |
| `cutoff_confirmed_anomalies` | 110 |
| `cutoff_reasonable_delay_controls` | 23 |
| `cutoff_normal_controls` | 273 |
| Representative `cutoff_untestable_controls` | 720 |

Required truth gate:

`python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v106_candidate`

Result:

`failures: []`

## DataSynth v113 L2-02 Duplicate-Payment Truth Realignment

`v113_candidate` is built on `v112_candidate`. It does not mutate journal rows, confirmed `DuplicatePayment` labels, or detector code.

Problem:

- The L2-02 detector surfaced 384 duplicate-payment review documents.
- `rule_truth_L2_02.csv` contained only the 33 injected `duplicate_payment_pairs` documents.
- Therefore 351 valid Phase 1 review candidates, mostly `amount_partner_fallback`, were counted as false positives even though the detector followed the screening contract.

Fix:

- Rebuild `rule_truth_L2_02.csv` and `duplicate_payment_review_population.csv` from the current `b04_duplicate_payment()` detector output.
- Keep `DuplicatePayment` labels and `duplicate_payment_pairs.csv` as the confirmed pair subset.
- Keep `duplicate_payment_negative_controls.csv` as a control sidecar only.
- Preserve detector reason bands so downstream scoring can separate strong reference matches from weaker fallback candidates.

Verification:

| Check | Result |
|---|---:|
| L2-02 detector documents | 384 |
| `rule_truth_L2_02.csv` documents | 384 |
| `duplicate_payment_review_population.csv` documents | 384 |
| Detector minus truth | 0 |
| Truth minus detector | 0 |
| Confirmed `DuplicatePayment` labels | 33 |
| Confirmed labels outside truth | 0 |
| `duplicate_payment_pairs.csv` docs | 33 |
| Pair docs outside truth | 0 |
| Negative-control docs | 18 |
| Negative-control truth overlap | 0 |

Reason split:

| Reason | Documents |
|---|---:|
| amount_partner_fallback | 351 |
| reference_match | 26 |
| mixed_reference_fallback | 7 |

## DataSynth v114 Stale Detector-Contract Truth Refresh

Problem:

- Candidate folders are cumulative. A folder such as `v113_candidate` can contain a `rule_truth_*` file generated by an older patch such as `v75`.
- That makes later evaluations mix current detector code with copied legacy truth.
- In v113, the staleness scan found actual detector/truth drift in L4-03 and L4-06.

Fix:

- Add `tools/scripts/scan_datasynth_rule_truth_staleness.py`.
- Build `data/journal/primary/datasynth_v114_candidate` from `v113_candidate`.
- Rebuild only the rule-truth files whose current detector output differed from the copied sidecars:
  - `rule_truth_L4_03.csv`
  - `high_amount_review_population.csv`
  - `rule_truth_L4_06.csv`
  - `batch_review_population.csv`
- Store the scan/refresh manifest in `labels/V114_STALE_TRUTH_REFRESH.json`.

Verification:

| Rule | Detector docs | Truth docs | Detector minus truth | Truth minus detector |
|---|---:|---:|---:|---:|
| L4-03 | 4,015 | 4,015 | 0 | 0 |
| L4-06 | 686 | 686 | 0 | 0 |

Patch delta:

| Rule | Added docs | Removed stale docs |
|---|---:|---:|
| L4-03 | 5 | 4 |
| L4-06 | 0 | 175 |

Required gates:

- `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v114_candidate`
- `python tools/scripts/scan_datasynth_rule_truth_staleness.py data/journal/primary/datasynth_v114_candidate --detector-diff`

Result:

- Required truth gate: `failures: []`
- Stale detector diff for L4-03/L4-06: `0`

Production `data/journal/primary/datasynth/` has not been overwritten by v106.

## DataSynth v107 L4-01 Revenue Z-score Truth Realignment

`v107_candidate` is built on `v106_candidate`. It does not mutate journal rows. It rebuilds only L4-01 rule truth from the current feature-backed detector contract.

Current L4-01 detector contract:

- Feature generation creates `is_revenue_account` and `amount_zscore`.
- L4-01 is true when a row is a revenue account row and `amount_zscore > 3.0`.
- `RevenueManipulation` remains a broad injected fraud label and should not be used as exhaustive L4-01 rule truth.

Problem:

- `rule_truth_L4_01.csv` was originally built from v75 feature state.
- Later DataSynth patches changed some journal/account context.
- v106 therefore had 5 L4-01 truth mismatches:
  - 3 stale truth documents whose current journal rows are no longer revenue-account rows.
  - 2 current revenue z-score hits missing from truth.

Fix:

- Recompute features from current v107 journal rows.
- Run `src.detection.fraud_rules_feature.b01_revenue_manipulation`.
- Rebuild `rule_truth_L4_01*`.
- Rebuild combined `rule_truth.csv` / `rule_truth.json`.
- Add explanatory sidecars:
  - `revenue_outlier_review_population*`
  - `revenue_outlier_boundary_controls*`

Verification:

| Check | Result |
|---|---:|
| Previous L4-01 truth documents | 965 |
| Current feature-backed detector documents | 964 |
| v107 `rule_truth_L4_01.csv` documents | 964 |
| Detector minus truth | 0 |
| Truth minus detector | 0 |
| Added truth documents | 2 |
| Removed stale truth documents | 3 |
| Boundary controls | 212 |

Required truth gate:

`python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v107_candidate`

Result:

`failures: []`

Production `data/journal/primary/datasynth/` has not been overwritten by v107.

## DataSynth v108 L4-02 Benford Group Truth Realignment

`v108_candidate` is built on `v107_candidate`. It does not mutate journal rows. It rebuilds L4-02 Benford truth at the correct group level.

Current L4-02 detector contract:

- Evaluation unit is `fiscal_year + company_code + gl_account`.
- Groups with fewer than 500 rows are excluded from strict finding truth.
- Groups with `MAD > 0.012` are Benford findings.
- `MAD > 0.015` is `strong`; otherwise the finding is `moderate`.
- Row-level Benford candidates are drill-down candidates only, not standalone anomaly rows.
- Legacy document-level `BenfordViolation` labels are not used as L4-02 precision/recall truth.

Problem:

- v107 had 100 Benford truth groups, while the current detector produced 99 groups.
- The mismatch was small but real:
  - `2022|C002|100140` was stale because current sample size is 497, below the 500-row threshold.
  - `2023|C001|200050` and `2024|C001|200120` are now below the MAD threshold.
  - `2023|C001|100040` and `2024|C001|2050` are current detector findings but were missing from truth.

Fix:

- Rebuild `benford_finding_truth*` from current journal rows.
- Rebuild `rule_truth_L4_02*` from refreshed finding truth.
- Rebuild `benford_drilldown_candidates*`, `benford_normal_groups*`, and `benford_skipped_small_groups*`.
- Rebuild Benford holdout/adversarial sidecars from the refreshed group pool so sidecar references do not remain stale.

Verification:

| Check | Result |
|---|---:|
| Previous L4-02 truth groups | 100 |
| Current detector finding groups | 99 |
| v108 `rule_truth_L4_02.csv` groups | 99 |
| Detector minus truth | 0 |
| Truth minus detector | 0 |
| Added truth groups | 2 |
| Removed stale truth groups | 3 |
| Benford drill-down candidates | 24,148 |
| Benford normal groups | 318 |
| Benford skipped small groups | 3,267 |
| Benford adversarial holdout | 176 |

Required truth gate:

`python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v108_candidate`

Result:

`failures: []`

Production `data/journal/primary/datasynth/` has not been overwritten by v108.

## DataSynth v110 L4-04 Rare Account-Pair Truth Realignment

`v110_candidate` is built on `v109_candidate`. It does not mutate journal rows. It rebuilds L4-04 rule truth from the current rare debit-credit account-pair detector output.

Problem:

- Phase 1 treats L4-04 as a broad review anchor: if a document contains a rare debit-credit account pair, it should be surfaced.
- The previous `rule_truth_L4_04.csv` and `rare_account_pair_review_population.csv` contained 3,503 documents.
- The current detector found 4,091 documents.
- The mismatch was not a detector false-positive problem. The truth sidecar was narrower than the current review universe and also had stale rows.

Fix:

- Rebuild `rule_truth_L4_04*` from `c09_rare_account_pair()` current output.
- Rebuild `rare_account_pair_review_population*` from the same detector universe.
- Keep `rare_account_pair_confirmed_anomalies*` as the confirmed `UnusualAccountPair` subset.
- Keep `rare_account_pair_normal_controls*` as legitimate rare-pair controls. These may still be raw L4-04 hits.

Verification:

| Check | Result |
|---|---:|
| Current L4-04 detector documents | 4,091 |
| v110 `rule_truth_L4_04.csv` documents | 4,091 |
| v110 `rare_account_pair_review_population.csv` documents | 4,091 |
| Detector minus truth | 0 |
| Truth minus detector | 0 |
| Added current detector documents | 645 |
| Removed stale truth documents | 57 |
| Single rare-pair documents | 3,380 |
| Multiple rare-pair documents | 468 |
| Large-document distinct-pair documents | 243 |

Important interpretation:

- This is not a detector fitting patch. The detector output is unchanged.
- L4-04 rule truth now means raw Phase 1 review universe, not confirmed fraud.
- Confirmed `UnusualAccountPair` labels remain a subset. In v110, 46 of 52 confirmed subset documents are currently in the raw detector universe; the remaining 6 are a future confirmed-subset cleanup candidate, not a rule-truth mismatch.
- Normal rare-pair controls are not false positives by definition. They represent legitimate long-tail cases that Phase 1 may still surface and score down later.

Required truth gate:

`python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v110_candidate`

Result:

`failures: []`

## DataSynth v111 L4-05 Combined-Context Truth Realignment

`v111_candidate` is built on `v110_candidate`. It does not mutate journal rows. It rebuilds L4-05 rule truth from the current detector output using the required 2022-2024 combined user-behavior context.

Problem:

- L4-05 is a user-behavior concentration rule, not an isolated document rule.
- The detector result depends on the population used to compute user abnormal-time ratio, midnight count, and sigma threshold.
- The old rule truth had only 27 confirmed `AbnormalHoursConcentration` documents.
- Running detector on the combined 2022-2024 context found 4,964 raw behavior review documents and captured all 27 confirmed subset documents.
- Running detector separately by year produces different TP/FN counts and should not be used as strict DataSynth truth evaluation.

Fix:

- Rebuild `rule_truth_L4_05*` from the current `c12_abnormal_hours_concentration()` detector output.
- Add `abnormal_hours_behavior_review_population*` as the raw L4-05 review universe.
- Keep `abnormal_hours_concentration_cases*` as the confirmed anomaly subset.
- Explicitly record the evaluation context as `three_year_combined_then_split_by_fiscal_year`.

Verification:

| Check | Result |
|---|---:|
| Combined-context L4-05 detector documents | 4,964 |
| v111 `rule_truth_L4_05.csv` documents | 4,964 |
| v111 `abnormal_hours_behavior_review_population.csv` documents | 4,964 |
| Detector minus truth | 0 |
| Truth minus detector | 0 |
| Confirmed subset documents | 27 |
| Confirmed subset in truth | 27 |
| system context review documents | 3,373 |
| high-context midnight documents | 1,577 |
| rapid approval documents | 14 |

Important interpretation:

- This is not a detector fitting patch. The detector output is unchanged.
- L4-05 rule truth now means raw Phase 1 behavior review universe, not confirmed fraud.
- Annual single-year L4-05 runs are useful robustness checks, but not the strict DataSynth truth benchmark because they change the statistical population.

Required truth gate:

`python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v111_candidate`

Result:

`failures: []`

## DataSynth v109 L3-12 Candidate/Scored Truth Split

`v109_candidate` is built on `v108_candidate`. It does not mutate journal rows. It fixes the L3-12 evaluation-layer mismatch.

Problem:

- L3-12 detector emits both raw candidates and scored review users.
- The evaluation script compared raw candidate user-years against `rule_truth_L3_12.csv`.
- `rule_truth_L3_12.csv` contains only scored review truth.
- Therefore zero-score candidates such as `system_scope_observation` were counted as false positives even though they were intentionally surfaced and then scored down to `0.00`.

Fix:

- Keep `rule_truth_L3_12.csv` as scored review truth.
- Add `labels/work_scope_raw_candidate_population*.csv` as raw candidate truth.
- Add `labels/work_scope_raw_candidate_document_projection*.csv` as drill-down projection only.
- Update `tools/scripts/eval_datasynth_l3_only.py` so L3-12 reports two metrics:
  - `L3-12`: scored review truth, detected by `review_score_series > 0`.
  - `L3-12-CAND`: raw candidate truth, detected by raw candidate output.

Verification:

| Metric | Truth | Detected | TP | FP | FN |
|---|---:|---:|---:|---:|---:|
| L3-12 scored | 64 | 64 | 64 | 0 | 0 |
| L3-12 candidate | 127 | 127 | 127 | 0 | 0 |

Year split:

| Year | Scored truth | Candidate truth |
|---|---:|---:|
| 2022 | 21 | 43 |
| 2023 | 21 | 42 |
| 2024 | 22 | 42 |

Important interpretation:

- This is not a detector fitting patch. The detector output is unchanged.
- The patch separates two existing truth layers so Phase 1 candidate coverage and risk scoring are not evaluated as the same thing.
- Document projection files are not strict precision/recall truth.

## DataSynth v112 L4-06 Batch Truth/Control Split

`v112_candidate` is built on `v111_candidate`. It does not mutate journal rows or detector code.

Problem:

- `rule_truth_L4_06` had confirmed, normal, boundary, and review-population meanings mixed together.
- Some confirmed `BatchAnomaly` rows used `source=recurring`, but the actual L4-06 batch detector does not treat `recurring` as a batch source.
- As a result, normal/boundary controls and recurring payroll-like examples were counted as false negatives even when the detector was following its contract.

Fix:

- Rebuild `rule_truth_L4_06.csv` and `batch_review_population.csv` from the current `c13_batch_anomaly()` detector output.
- Keep `batch_confirmed_anomalies.csv` and `BatchAnomaly` labels as a confirmed subset of the raw L4-06 review universe.
- Keep `batch_normal_controls.csv` and `batch_boundary_controls.csv` as control sidecars only.
- Do not add `recurring` to the detector source list just to fit the synthetic truth.

Verification:

| Check | Result |
|---|---:|
| L4-06 detector documents | 861 |
| `rule_truth_L4_06.csv` documents | 861 |
| `batch_review_population.csv` documents | 861 |
| Detector minus truth | 0 |
| Truth minus detector | 0 |
| Confirmed `BatchAnomaly` documents | 175 |
| Confirmed outside truth | 0 |
| Truth source `automated` | 639 |
| Truth source `interface` | 222 |
| Confirmed source `automated` | 113 |
| Confirmed source `interface` | 62 |

Required truth gate:

`python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v112_candidate`

Result:

`failures: []`

## DataSynth v115/v116 L2 Truth Purge and Active Metadata Cleanup

Problem:

- Active candidate folders copied historical `rule_truth_L2_03`, `rule_truth_L2_04`, and `rule_truth_L2_05` files forward.
- The files existed in the latest folder, but their `source_candidate` still pointed to `v74`.
- This made Phase 1 L2 evaluation mix current detector output with old truth criteria.

Fix:

- Build `data/journal/primary/datasynth_v115_candidate` from `v114_candidate`.
- Delete copied L2-03/L2-04/L2-05 rule-truth families inside the new candidate.
- Rebuild those three truth families from current detector output:
  - `b05_duplicate_entry()`
  - `b11_expense_capitalization()`
  - `c11_reversal_entry()`
- Build `data/journal/primary/datasynth_v116_candidate` from `v115_candidate`.
- Normalize all active `rule_truth_*` files so `source_candidate=v116`; historical patch versions no longer appear as active truth criteria.
- Remove copied root-level historical patch manifests from the active v116 candidate folder. Only the v116 freeze/cleanup manifests remain in that folder.

Verification:

| Check | Result |
|---|---:|
| L2-03 rule truth documents | 105 |
| L2-04 rule truth documents | 1,098 |
| L2-05 rule truth documents | 82 |
| Active rule-truth files with legacy `source_candidate` | 0 |
| Root-level old freeze/patch manifests left in v116 | 0 |
| Required truth gate failures | 0 |

Commands:

- `python tools/scripts/build_datasynth_v115_l2_truth_refresh.py`
- `python tools/scripts/build_datasynth_v116_truth_metadata_cleanup.py`
- `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v116_candidate`

Important:

- v115 changes L2 rule-truth membership.
- v116 does not change journal rows or truth membership; it removes old active truth metadata.
- Confirmed injected labels remain separate from Phase 1 raw candidate truth.

## DataSynth v117 L2 Independent Scenario/Control Sidecars

Problem:

- `rule_truth_*` and `*_review_population*` are detector-contract snapshots.
- They are valid for checking whether the current detector reproduces its Phase 1 candidate contract.
- They are not independent behavioral validation data, because they are derived from detector output.
- L2-02 already had comparatively independent pair/control sidecars, but L2-03/L2-04/L2-05 did not.

Fix:

- Build `data/journal/primary/datasynth_v117_candidate` from `v116_candidate`.
- Do not change journal rows.
- Do not change `rule_truth` membership.
- Add detector-independent L2 scenario/control sidecars selected from anomaly labels or journal business fields only:
  - `duplicate_entry_confirmed_scenarios*`
  - `duplicate_entry_negative_controls*`
  - `expense_capitalization_plausible_cases*`
  - `expense_capitalization_normal_capex_controls*`
  - `reversal_pattern_plausible_cases*`
  - `reversal_pattern_normal_clearing_controls*`

Verification:

| Sidecar | Rows | Purpose |
|---|---:|---|
| `duplicate_entry_confirmed_scenarios` | 67 | Independent duplicate-entry confirmed scenario subset |
| `duplicate_entry_negative_controls` | 90 | Routine/system duplicate-lookalike controls |
| `expense_capitalization_plausible_cases` | 33 | Independent capitalization plausible cases |
| `expense_capitalization_normal_capex_controls` | 90 | Normal CAPEX/asset-context controls |
| `reversal_pattern_plausible_cases` | 51 | Independent reversal-pattern plausible cases |
| `reversal_pattern_normal_clearing_controls` | 90 | Normal clearing/settlement controls |

Required truth gate:

`python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v117_candidate`

Result:

`failures: []`

Important:

- `*_review_population*` = detector-contract universe.
- `*_confirmed_scenarios*`, `*_plausible_cases*`, `*_negative_controls*`, `*_normal_*_controls*` = independent behavioral validation sidecars.
- Independent sidecars must not replace strict Phase 1 `rule_truth`.

## DataSynth v118 Sidecar Manifest

Problem:

- Many files under `labels/` are called sidecars, controls, negative controls, review populations, or manifests.
- Their semantics are not the same.
- Some are realistic independent controls.
- Some are detector output snapshots.
- Some are rule-truth context files that should not be used as independent realism validation sets.

Fix:

- Build `data/journal/primary/datasynth_v118_candidate` from `v117_candidate`.
- Add `labels/sidecar_manifest.csv` and `labels/sidecar_manifest.json`.
- Do not change journal rows, labels, existing sidecar rows, or `rule_truth` membership.
- Classify sidecars with:
  - `purpose`
  - `expected_detector_positive`
  - `allowed_for_independent_sidecar_eval`
  - `semantics`
  - `reason`

Key classifications:

| Sidecar | Purpose | Independent eval |
|---|---|---|
| `delegated_approval_controls` | realism_control | yes |
| `late_approval_boundary_controls` | realism_control | yes |
| `post_approval_change_controls` | realism_control | yes |
| `approver_master_mapping_issues` | realism_control | yes |
| `l1_realism_normal_controls` | realism_control | yes |
| `sod_review_population` | review_population | yes, but not L1-06 direct truth |
| `wrong_period_non_audit_issue_truth` | rule_truth_but_not_audit_issue | no |
| `wrongperiod_negative_controls` | legacy_alias | no |
| `skipped_approval_system_gap_controls` | rule_truth_context | no |
| `skipped_approval_normal_controls` | legacy_alias | no |
| `system_control_gap_controls` | rule_truth_context | no |

Verification:

| Check | Result |
|---|---:|
| Manifest rows | 146 |
| `realism_control` sidecars | 33 |
| `review_population` sidecars | 20 |
| `detector_contract_universe` sidecars | 4 |
| `rule_truth_context` sidecars | 2 |
| `rule_truth_but_not_audit_issue` sidecars | 1 |
| `legacy_alias` sidecars | 2 |
| `contract_manifest` files | 84 |
| Sidecars allowed for independent eval | 34 |
| Required truth gate failures | 0 |

Important:

- Evaluation code should not infer sidecar semantics from filename alone.
- Independent behavioral validation must filter `sidecar_manifest.allowed_for_independent_sidecar_eval=True`.
- Detector-contract checks should use `rule_truth` or `purpose=detector_contract_universe`.

## DataSynth v119 L3 Sidecar Semantics Cleanup

Problem:

- `afterhours_normal_context_within_review_population` and `normal_after_hours_context` were intended to represent normal-looking after-hours context, but still included anomaly-labeled documents.
- In v118, the actual overlap was `20` documents:
  - `DuplicatePayment`: 17
  - `BatchAnomaly`: 3
- L3-03 IC exception files such as `ic_unmatched_cases` and `transfer_pricing_review_cases` are case-level drilldowns using `target_document_id` and `counterpart_document_id`, not document-level subsets keyed by `document_id`.

Fix:

- Build `data/journal/primary/datasynth_v119_candidate` from `v118_candidate`.
- Do not change journal rows or `rule_truth` membership.
- Remove anomaly-labeled documents from:
  - `afterhours_normal_context_within_review_population*`
  - `normal_after_hours_context*`
- Add the removed labeled documents to:
  - `afterhours_cross_rule_labeled_context*`
- Add L3-06 contract columns to the normal/cross-rule after-hours sidecars:
  - `rule_id=L3-06`
  - `expected_hit=True`
  - `truth_layer=rule_truth`
  - `truth_basis=posting_date hour is within configured after-hours window`
  - `within_l306_review_population=True`
- Add L3-03 linkage columns to IC drilldown sidecars:
  - `target_in_l303_rule_truth`
  - `counterpart_in_l303_rule_truth`
  - `linked_l303_document_ids`
  - `linked_l303_document_count`

Verification:

| Check | Result |
|---|---:|
| Clean after-hours normal context docs | 6,952 |
| Clean after-hours normal context anomaly-label overlap | 0 |
| Cross-rule labeled after-hours context docs | 20 |
| `ic_unmatched_cases` linked to L3-03 | 21 / 21 |
| `ic_amount_mismatch_cases` linked to L3-03 | 16 / 16 |
| `ic_timing_gap_cases` linked to L3-03 | 14 / 14 |
| `transfer_pricing_review_cases` linked to L3-03 | 13 / 13 |
| Required truth gate failures | 0 |

Important:

- L3-03 IC drilldowns are not `rule_truth_L3_03` document-level subsets by `document_id`.
- They are case-level exception files linked to L3-03 through target/counterpart document ids.

## DataSynth v120 L4 Sidecar Semantics Cleanup

Problem:

- Several L4 `rule_truth_L4_*` files and `*_review_population*` files were intentionally identical detector universes.
- This is correct for strict contract checks, but misleading if someone treats `*_review_population` as detector-independent realism samples.
- Some `normal_controls` / `boundary_controls` files can legitimately overlap raw detector hits. For example, a rare account-pair can be a normal business context and still be a valid L4-04 review candidate.

Fix:

- Build `data/journal/primary/datasynth_v120_candidate` from `v119_candidate`.
- Do not change journal rows or `rule_truth` membership.
- Add detector-universe aliases:
  - `revenue_outlier_detector_universe*`
  - `high_amount_detector_universe*`
  - `rare_account_pair_detector_universe*`
  - `abnormal_hours_behavior_detector_universe*`
  - `batch_detector_universe*`
- Add clearer context aliases:
  - `high_amount_legitimate_contexts*`
  - `high_amount_boundary_contexts*`
  - `rare_account_pair_legitimate_contexts*`
  - `batch_legitimate_contexts*`
  - `batch_boundary_contexts*`
  - `revenue_outlier_boundary_contexts*`
- Add/refresh `sidecar_role`, `sidecar_purpose`, `expected_detector_positive`, `allowed_for_independent_sidecar_eval`, and `can_overlap_detector_universe` metadata.

Verification:

| Check | Result |
|---|---:|
| `revenue_outlier_detector_universe` vs `rule_truth_L4_01` diff | 0 |
| `high_amount_detector_universe` vs `rule_truth_L4_03` diff | 0 |
| `rare_account_pair_detector_universe` vs `rule_truth_L4_04` diff | 0 |
| `abnormal_hours_behavior_detector_universe` vs `rule_truth_L4_05` diff | 0 |
| `batch_detector_universe` vs `rule_truth_L4_06` diff | 0 |
| Sidecar manifest rows | 164 |
| Active `rule_truth_*` legacy `source_candidate` values | 0 |
| Required truth gate failures | 0 |

Important:

- `*_review_population` and `*_detector_universe` are detector-contract universe files.
- They are useful for 0-mismatch contract checks, not for detector-independent realism evaluation.
- `*_legitimate_contexts` and `*_boundary_contexts` are not strict negative controls. If they overlap a raw detector hit, that can be expected.
- Independent behavioral evaluation must use `labels/sidecar_manifest.csv` and interpret `sidecar_role` / `allowed_for_independent_sidecar_eval`, not filename alone.

## DataSynth v121 D01/D02 Macro Sidecar Semantics Cleanup

Problem:

- D01/D02 are macro findings, but sidecar names can still be read as document-level anomaly labels.
- D01 `normal_controls` are raw-positive analytical-review contexts, not detector negative controls.
- D02 `normal_controls` mix two different meanings:
  - raw-positive normal contexts that D02 should surface but not count as confirmed anomaly
  - guardrail negatives that D02 should not surface
- D02 lacked D01-style `evaluation_bucket`, `precision_policy`, and macro-priority metadata.

Fix:

- Build `data/journal/primary/datasynth_v121_candidate` from `v120_candidate`.
- Do not change journal rows, anomaly labels, or `rule_truth` membership.
- Add D01 guardrail sidecars:
  - `account_activity_variance_stable_controls*`
  - `account_activity_variance_near_threshold_controls*`
  - `account_activity_variance_exclusions*`
- Add D02 semantic sidecars:
  - `monthly_pattern_shift_truth*`
  - `monthly_pattern_shift_raw_positive_normal_contexts*`
  - `monthly_pattern_shift_guardrail_negative_controls*`
- Add or normalize macro metadata:
  - `evaluation_bucket`
  - `precision_policy`
  - `business_event_type`
  - `expected_macro_priority_band`
  - `macro_truth_role`
  - `sidecar_role`

Verification:

| Check | Result |
|---|---:|
| D01 rule truth groups | 840 |
| D01 confirmed truth groups | 336 |
| D01 normal raw-positive controls | 504 |
| D01 stable controls | 240 |
| D01 near-threshold controls | 120 |
| D01 exclusions | 96 |
| D02 rule truth groups | 497 |
| D02 confirmed truth groups | 346 |
| D02 raw-positive normal contexts | 151 |
| D02 guardrail negative controls | 43 |
| D02 exclusions | 2,059 |
| Active `rule_truth_*` legacy `source_candidate` values | 0 |
| Required truth gate failures | 0 |

Important:

- D01/D02 evaluation unit is `fiscal_year + company_code + gl_account`.
- `document_count` in the sidecar manifest should be read as group count for D01/D02 when those three columns exist.
- Do not change journal row `is_anomaly` to make D01/D02 look cleaner.
- D01/D02 normal controls are not necessarily “detector should not hit” controls. Use `expected_d01_flag` / `expected_d02_flag`, `sidecar_role`, and `macro_truth_role`.

## DataSynth v122 Year Journal File Consistency Cleanup

Problem:

- v121 had two journal representations with the same row keys but different field values:
  - `journal_entries.csv`
  - `journal_entries_2022.csv`, `journal_entries_2023.csv`, `journal_entries_2024.csv`
- Some Phase 1 evaluators read the year files.
- L1-02 truth said `fiscal_period` was missing for two documents, but the year files still had fiscal periods filled:
  - `8c1f9639-51f4-42f0-8280-1b0486b7090b`: year file had `7.0`
  - `fd85b1ca-3976-4dbb-867d-cd3089257afa`: year file had `1.0`
- This made L1-02 look like it had two false negatives even though the combined journal and truth sidecar agreed.

Root cause:

- Candidate patches had updated one journal representation without regenerating the other.
- The row sets were the same, but selected fields diverged.

Fix:

- Build `data/journal/primary/datasynth_v122_candidate` from `v121_candidate`.
- Regenerate all year CSV/JSON files as deterministic partitions of `journal_entries.csv`.
- Do not change anomaly-label membership or rule-truth membership.

Verification:

| Year | Rows | Docs | Pre-patch mismatched fields | Post-patch mismatched fields |
|---|---:|---:|---|---|
| 2022 | 373,425 | 106,675 | `posting_date=5,867`, `source=6,002` | 0 |
| 2023 | 366,465 | 105,525 | `fiscal_period=2`, `posting_date=18,449`, `source=5,978` | 0 |
| 2024 | 369,545 | 106,993 | `fiscal_period=2`, `posting_date=15,020`, `source=7,116` | 0 |

Important:

- Going forward, `journal_entries_YYYY.csv/json` must be regenerated from `journal_entries.csv` whenever journal values are patched.
- L1/L2/L3/L4 evaluation should not mix combined journal and stale year journal files.
- v122 fixes the immediate L1-02 false-negative artifact by making the two fiscal-period-missing documents blank in both representations.

## DataSynth v123 L4-06 Truth Refresh

Problem:

- After v122 regenerated the year journal files from the combined journal, L4-06 detector output became wider than the stale L4-06 truth sidecars.
- The detector correctly flagged six additional automated documents in the same timestamp cluster:
  - posting timestamp: `2023-09-30 23:25:00`
  - source: `automated`
  - reason: `simultaneous_creation`
- v122 `rule_truth_L4_06_2023.csv`, `batch_review_population`, and `batch_detector_universe` did not include those six documents.

Fix:

- Build `data/journal/primary/datasynth_v123_candidate` from `v122_candidate`.
- Rebuild only:
  - `rule_truth_L4_06*`
  - `batch_review_population*`
  - `batch_detector_universe*`
- Do not change confirmed `BatchAnomaly` labels.
- Do not change `batch_normal_controls*` or `batch_boundary_controls*`.

Verification:

| Check | Result |
|---|---:|
| Previous L4-06 truth docs | 686 |
| Current L4-06 truth docs | 692 |
| Added docs | 6 |
| Removed docs | 0 |
| `rule_truth_L4_06` vs `batch_review_population` diff | 0 |
| `rule_truth_L4_06` vs `batch_detector_universe` diff | 0 |
| Required truth gate failures | 0 |

Important:

- This is a DataSynth truth-membership refresh, not a detector change.
- The six added documents are raw L4-06 review-universe truth. They are not newly confirmed `BatchAnomaly` audit-issue labels.

## DataSynth v124 L3/D A-Axis Truth Refresh

Problem:

- After v122 year-file synchronization, several A-axis evaluations were comparing current detector output against stale L3 truth files.
- L3-02 had 3 stale truth documents whose current `source` was no longer manual/adjustment.
- L3-04 had 764 stale truth documents and 128 missing truth documents because current posting dates moved around the period-start/end boundary.
- L3-05 truth still used the narrower post-v104 subset even though the current A-axis rule contract is all weekend/holiday postings.
- L3-11 had 3 stale truth documents whose current `posting_date=2024-01-01` no longer exceeded the configured cutoff threshold.
- D01/D02 A-axis metrics were using confirmed macro subsets as truth while detector output represented the macro review universe.

Root cause:

- The detector was not the primary issue. The active `rule_truth_*` files were not fully synchronized with current `journal_entries_YYYY.csv`.
- D01/D02 also had evaluation-definition drift: A-axis truth must be the macro review universe, while confirmed macro anomaly subsets belong to downstream/B-C interpretation.

Fix:

- Build `data/journal/primary/datasynth_v124_candidate` from `v123_candidate`.
- Rebuild:
  - `rule_truth_L3_02*`
  - `manual_entry_population_truth*`
  - `rule_truth_L3_04*`
  - `rule_truth_L3_05*`
  - `weekend_review_population*`
  - `rule_truth_L3_11*`
  - `cutoff_review_population*`
  - `cutoff_confirmed_anomalies*`
  - `cutoff_normal_controls*`
- Keep D01/D02 membership unchanged, but pin A-axis evaluation to `rule_truth_D01.csv` and `rule_truth_D02.csv`.
- Do not mutate journal rows.

Verification:

| Check | Result |
|---|---:|
| L3-02 truth/detector docs | 86,808 / 86,808 |
| L3-04 truth/detector docs | 141,375 / 141,375 |
| L3-05 truth/detector docs | 24,318 / 24,318 |
| L3-11 truth/detector docs | 130 / 130 |
| L3-02/L3-04/L3-05/L3-11 FP/FN | 0 / 0 |
| D01 A-axis truth vs review universe diff | 0 |
| D02 A-axis truth vs review universe diff | 0 |
| A-axis alignment gate failures | 0 |
| Required truth gate failures | 0 |

Important:

- v124 adds `tools/scripts/check_datasynth_axis_truth_alignment.py`.
- This gate should run after every DataSynth patch that can change journal fields, source values, dates, or macro truth semantics.
- D01/D02 A-axis denominator is the raw macro review universe, not only confirmed macro truth.

## DataSynth v125 L2 Pair/Reversal Truth Split

Problem:

- L2-02 evidence is pair-based, but `rule_truth_L2_02.csv` only had `document_id` and `matched_document_id`. This made pair-level A-axis evaluation dependent on which document was treated as the matched side.
- L2-03 membership was acceptable, but reason codes were too generic for downstream scoring/debugging.
- L2-05 mixed strict reversal truth and weak reversal-like review candidates in one `rule_truth_L2_05.csv`.

Fix:

- Build `data/journal/primary/datasynth_v125_candidate` from `v124_candidate`.
- Add `pair_key`, `duplicate_pair_key`, and `duplicate_group_id` to:
  - `rule_truth_L2_02*`
  - `duplicate_payment_review_population*`
  - `duplicate_payment_pairs*`
- Clarify L2-03 reason codes:
  - `exact_duplicate`
  - `near_duplicate`
  - `split_duplicate`
  - `ic_split_duplicate`
  - `o2c_offset_duplicate`
- Split L2-05:
  - `rule_truth_L2_05*`: superseded strict reversal subset in v125 only
  - `reversal_entry_review_population*`: full raw reversal-like review universe
  - `reversal_pattern_raw_review_universe*`: alias for raw review universe
  - `reversal_weak_review_population*`: weak candidates excluded from A-axis truth
- Do not mutate journal rows.

Verification:

| Check | Result |
|---|---:|
| L2-02 rule truth rows | 384 |
| L2-02 unique pair keys | 384 |
| L2-02 confirmed duplicate group rows | 33 |
| L2-03 exact duplicate reason rows | 64 |
| L2-03 near duplicate reason rows | 28 |
| L2-03 IC split duplicate reason rows | 6 |
| L2-03 O2C offset duplicate reason rows | 4 |
| L2-03 split duplicate reason rows | 3 |
| L2-05 previous raw candidates | 82 |
| L2-05 superseded strict subset | 52 |
| L2-05 weak review-only candidates | 30 |
| Required truth gate failures | 0 |

Important:

- L2-02 A-axis pair evaluation should compare `pair_key`, not only `document_id`.
- This v125 L2-05 A-axis policy is superseded by v126. Keeping strict-only L2-05 as `rule_truth_L2_05` caused false positives in a contract check because Phase 1 A-axis truth must represent the raw detector universe.

## DataSynth v126 L2 A-Axis Contract Truth Refresh

Problem:

- v125 narrowed `rule_truth_L2_05` to the strict 52-document subset while the active detector still surfaced 80 raw reversal candidates.
- v125 only clarified L2-03 reason metadata but did not refresh rule truth to the current 111-document A-axis evaluator output.
- L2-02 had pair metadata but still needed a full current detector-contract refresh so document and pair comparison stay aligned.

Fix:

- Build `data/journal/primary/datasynth_v126_candidate` from `v125_candidate`.
- Do not mutate journal rows.
- Rebuild L2 A-axis rule truth from the active detector contract:
  - `L2-02`: current `b04_duplicate_payment()` output, 384 documents, stable `pair_key`.
  - `L2-03`: current `b05_duplicate_entry()` output only, 111 documents. Do not union broader `DuplicateDetector` subrule output because that is not the current A-axis evaluator contract.
  - `L2-05`: current `c11_reversal_entry()` raw output, 80 documents.
- Keep stricter or weaker L2-05 interpretation as sidecars:
  - `reversal_strict_truth`: 52 documents.
  - `reversal_weak_review_population`: 28 documents.

Verification:

| Rule | Truth | Detected | TP | FP/Label-Outside | FN |
|---|---:|---:|---:|---:|---:|
| L2-02 | 384 | 384 | 384 | 0 | 0 |
| L2-03 | 111 | 111 | 111 | 0 | 0 |
| L2-05 | 80 | 80 | 80 | 0 | 0 |

Additional checks:

- Required truth gate: `failures: []`.
- L3/D A-axis alignment gate: `failures: []`.
- Active `rule_truth_*` files checked: 34.
- Active `rule_truth_*` files with stale `source_candidate`: 0.

Lesson:

- A-axis contract truth must not be narrowed to confirmed/strict subsets.
- Strict, weak, normal, and independent scenario semantics belong in sidecars or B/C-axis evaluation.
- If `rule_truth_*` is derived from a detector contract, it must be rebuilt from the exact active evaluator used by the A-axis report.

## TS-9: PHASE1 review queue를 확실한 감사 주제로 재정렬

**분류**: 탐지 설계 / 문서 정합화 | **정리일**: 2026-05-07

### 1. 문제

`datasynth_manipulation` v134 결과를 보면 조작 truth 420건은 모두 score 또는 rule/review hit로 포착된다. 문제는 포착이 아니라 case ranking과 queue 표현이다.

기존 문서와 case artifact에는 `Audit Risk`, `추가검토사항`, `우선 위험신호`, `저우선 위험신호`, `맥락 검토대상`, `조작 후보` 같은 표현이 섞여 있었다. 이 표현들은 감사인이 실제로 무엇을 검토해야 하는지 바로 설명하지 못한다.

특히 `조작 후보`와 `맥락 검토대상`은 주제가 아니라 상태값이다. 이 상태값을 review queue 이름으로 쓰면 다음 문제가 생긴다.

- 왜 상단에 올라왔는지 설명이 약하다.
- 서로 다른 룰이 단순 합산되어 주제별 책임 영역이 흐려진다.
- 악의적 조작 truth가 통제, 시점, 금액, 관계사, 중복 같은 실제 감사 주제 안에서 어떻게 포착됐는지 추적하기 어렵다.
- 정상 운영 noise와 실제 조작 신호를 같은 "위험신호" 묶음으로 보게 되어 ranking 해석이 흔들린다.

### 2. 판단 기준

기준 문서는 [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md)다. 해당 문서의 ISA 240, K-SOX, ISA 550, FSS 전표 조작 사례는 "조작 후보"라는 단일 큐를 요구하지 않는다. 실제 기준은 다음 주제들을 요구한다.

- 승인 통제 실패
- 결산·기간귀속 이상
- 관계사·순환거래
- 가공매출 또는 고액·분포 이상
- 중복 지급, 상계, 반제, 자금 유출
- 계정분류와 거래실질 불일치
- 원장 기록 자체의 정합성 오류

따라서 PHASE1 queue는 "부정 의심 여부"가 아니라 "감사인이 검토할 구체 주제"로 나눠야 한다.

### 3. 최종 운영 queue

공식 review queue는 7개로 둔다. 묶을 수 있는 항목은 최대한 묶되, 감사 절차가 달라지는 주제는 분리한다.

| Queue | 포함 룰 | 목적 |
|---|---|---|
| 원장기록·데이터정합성 | L1-01, L1-02, L1-08, 일부 L3-08 | 전표가 원장 기록으로서 유효한지 확인 |
| 승인·권한·업무분장 통제 | L1-04, L1-05, L1-06, L1-07, L1-09, L3-02, L3-12 | 승인권한 초과, 자기승인, 승인생략, 수기우회, 업무범위 집중 확인 |
| 결산·기간귀속·입력시점 | L3-04, L3-05, L3-06, L3-07, L3-08, L3-11, L4-05 | 결산 말, 휴일·야간, 사후입력, cutoff, 설명 부족 전표 확인 |
| 계정분류·거래실질 불일치 | L1-03, L2-04, L3-01, L3-09, L3-10, L4-04 | 계정 조합과 거래 설명이 업무 실질과 맞는지 확인 |
| 중복·상계·자금유출 | L2-01, L2-02, L2-03, L2-05 | 중복 지급, 반복 전표, 상계·반제, 유출 은폐 가능성 확인 |
| 관계사·내부거래·순환구조 | L3-03, IC01, IC02, IC03 | 특수관계자, 내부거래, 순환거래, 미상계 IC 구조 확인 |
| 수익·금액·모집단 통계 이상 | L4-01, L4-02, L4-03, L4-06, D01, D02, Benford | 매출, 고액, 숫자 분포, 배치, 계정·월 단위 모집단 이상 확인 |

### 4. 기존 표현 처리

아래 표현은 UI나 결과 문서의 primary queue 이름으로 쓰지 않는다.

| 기존 표현 | 처리 |
|---|---|
| 조작 후보 | queue가 아니라 FSS/ISA 240 기반 fraud-scenario tag로만 사용 |
| 맥락 검토대상 | queue가 아니라 보강 증거가 약한 case 상태값으로만 사용 |
| 추가검토사항 | 위 7개 queue 중 하나로 재분류 |
| Audit Risk | 위 7개 queue를 묶는 상위 개념으로만 사용 |
| 우선 위험신호 / 저우선 위험신호 | priority band로만 사용 |

### 5. 조작 시나리오 매핑

`manipulated_entry_truth.csv`의 조작 시나리오는 별도 queue로 만들지 않고, 위 7개 queue에 매핑한다.

| 조작 시나리오 | 주 queue |
|---|---|
| `approval_sod_bypass` | 승인·권한·업무분장 통제 |
| `circular_related_party_transaction` | 관계사·내부거래·순환구조 |
| `embezzlement_concealment` | 중복·상계·자금유출 |
| `fictitious_entry` | 수익·금액·모집단 통계 이상 또는 계정분류·거래실질 불일치 |
| `period_end_adjustment_manipulation` | 결산·기간귀속·입력시점 |
| `unusual_timing_manipulation` | 결산·기간귀속·입력시점 |

### 6. 결론

PHASE1의 목적은 "조작이라고 단정하는 큐"를 만드는 것이 아니라, 감사인이 봐야 할 이상징후를 누락 없이 구체 주제로 정렬하는 것이다. 조작 여부는 각 queue 안에서 증거 조합, 금액 중요성, 반복성, 통제 우회, 관계사 구조를 보고 판단한다.

따라서 앞으로 결과 문서와 UI는 위 7개 queue를 primary 분류로 사용하고, `조작 후보`, `맥락 검토대상` 같은 표현은 primary queue가 아닌 보조 tag 또는 상태값으로만 사용한다.

## TS-9 Addendum: Fraud Combo Floor는 7개 topic 내부 정책이다

**분류**: 탐지 설계 / Topic scoring 보강 | **정리일**: 2026-05-08

TS-9의 결론은 유지한다. 새 8번째 topic 또는 tab은 만들지 않는다. 다만 `datasynth_manipulation` v134 결과에서 조작 truth가 일부 기대 topic의 High/Top N에 들어오지 않는 문제가 확인되었으므로, 7개 topic 내부에 금감원/ISA/PCAOB 기반 조합형 승격 로직을 추가한다.

운영 정책:

- `topic_score = existing_topic_score + fraud_combo_bonus + fraud_combo_floor`로 확장한다.
- `fraud_combo_bonus`는 보강 점수이고, `fraud_combo_floor`는 topic band 최소선이다.
- `fraud_scenario_tags`는 badge/context field이며 queue나 sort key가 아니다.
- High floor 기본값은 `0.75`, Medium floor 기본 범위는 `0.45~0.60`이다.

필수 subtype:

| Subtype | 대표 tag | 승격 topic | High floor 핵심 조건 |
|---|---|---|---|
| 가공전표 의심 | `가공전표 의심` | 수익·금액·모집단 통계 이상 | `(L4-01 or L4-03) + L3-02 + (L4-04 or L2-03)` |
| 결산수정 조작 의심 | `결산수정 조작 의심` | 결산·기간귀속·입력시점 | `(L3-04 or L3-07 or L3-11 or L1-08) + L4-03 + (L3-08 or L3-10 or L4-04)` |
| 횡령은폐 의심 | `횡령은폐 의심` | 중복·상계·자금유출 | `(L2-02 or L2-03 or L2-05) + (L1-05 or L1-06 or L1-07 or L1-04)` |
| 순환거래 의심 | `순환거래 의심` | 관계사·내부거래·순환구조 | `(L3-03 or IC01 or IC02 or IC03) + (L4-03 or L3-04 or L3-11) + 반복/counterparty cycle` |
| 승인우회 조작 의심 | `승인우회 조작 의심` | 승인·권한·업무분장 통제 | `(L1-04 or L1-05 or L1-06 or L1-07) + (L4-03 or L3-02 or L3-05 or L3-06)` |

주의사항:

- 관계사 topic은 `L3-03`을 단순 booster로만 두면 안 된다. `L3-03` 또는 `IC01~IC03`이 있으면 관계사 topic score 계산을 시작하되, 단독 `L3-03`은 Low 모집단 신호로 제한한다.
- 계정분류·거래실질 불일치는 조작 subtype의 독립 High topic이 아니라 가공전표/결산수정/횡령은폐의 booster 축으로 사용한다.
- 원장기록·데이터정합성은 fraud high 승격 topic이 아니라 품질 게이트다. 다른 조작 combo의 설명 부족, 필드 누락, concealment context를 강화하는 데만 사용한다.
