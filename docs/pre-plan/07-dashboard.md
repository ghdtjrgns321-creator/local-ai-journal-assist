# 07. Streamlit 대시보드 [Phase 1c — 의존: 06]

## 목적
DuckDB에 적재된 감사 분석 결과를 5개 탭으로 시각화한다.
파일 업로드 → 분석 실행 → 결과 탐색까지 원스톱 워크플로우 제공.

## 데이터 컨텍스트

> 참조: [generation_principles.md](../../data/journal/primary/datasynth/generation_principles.md), [PREVIEW.md](../../data/journal/primary/datasynth/PREVIEW.md)

DataSynth v1.2.0 기준. K-IFRS 적용 한국 중견 제조 그룹사(3법인) 시뮬레이션.

| 항목             | 값                                               |
|:-----------------|:-------------------------------------------------|
| 전표(document)   | 106,489건                                        |
| 라인아이템(line) | 1,106,356건                                      |
| 컬럼             | 39개 (header 24 + line 15)                       |
| 회사코드         | C001(본사, 서울), C002(울산공장), C003(천안공장)  |
| 통화             | KRW (단일)                                       |
| 회계연도         | 2022 (1~12월)                                    |
| GL 계정          | 430개 (K-IFRS / SAP 한국 표준)                   |
| 사용자           | 152명 (5개 페르소나)                              |

### 핵심 차원 → 대시보드 활용 매핑

| 차원               | 값                                                                | 대시보드 활용           |
|:-------------------|:------------------------------------------------------------------|:------------------------|
| `business_process` | P2P(23.3%), O2C(25.9%), R2R(26.5%), H2R(8.9%), TRE(8.5%), A2R(6.9%) | 필터, 히트맵, 프로세스별 뷰 |
| `company_code`     | C001(본사), C002(울산), C003(천안)                                | 필터, 법인별 KPI 비교   |
| `user_persona`     | automated_system(68%), junior(12.8%), senior(9.6%), controller(4.9%), manager(4.8%) | 필터, 페르소나×위험 교차표 |
| `source`           | Automated(61.8%), Manual(29.4%), Recurring(6.2%), Adjustment(2.6%)| 필터, 수기 전표 하이라이트 |
| `document_type`    | SA, KR, KZ, DR, DZ, WE, WL, AA, HR, IC (10종)                   | 필터, 전표유형별 집계    |
| `risk_level`       | High(>0.7), Medium(>0.4), Low(>0.2), Normal(≤0.2)               | KPI, 색상 코딩          |

### 이상/부정/통제 분포

| 지표              | 건수    | 비율   | 대시보드 활용                   |
|:------------------|:--------|:-------|:--------------------------------|
| 이상징후 전표     | 7,959   | 7.5%   | Summary KPI, Explorer 필터      |
| 부정 전표         | 2,008   | 1.9%   | Summary KPI, 부정유형 Treemap   |
| SoD 위반          | 1,080   | 1.0%   | SoD 분석 뷰                     |
| 차대변 균형 불일치 | 44     | 0.04%  | A01 룰 위반 카운트              |

### 부정 유형 Top 5 (13종 중)

| 유형                   | 건수 | 대응 탐지 룰         |
|:-----------------------|:-----|:---------------------|
| DuplicatePayment       | 385  | B04 중복 지급        |
| FictitiousTransaction  | 370  | B03 가공 거래        |
| RevenueManipulation    | 314  | B01 수익 조작        |
| SplitTransaction       | 282  | B02 분할 승인회피    |
| TimingAnomaly          | 173  | C04 소급 전기        |

### 시간 패턴 (탐지 연계)

```
시간대              비율      탐지 연계
late_night(0~6)     0.8%     C03 심야 전기
morning_spike       36.8%    정상 업무 피크
eod_rush(16~18:30)  22.1%    마감 전 러시
overtime(18:30~22)   8.1%    야근 (주의)
midnight(22~24)      0.8%    C03 심야 (고위험)

주말 전표            9.5%    C02 주말 전기
12월(연말 결산)     11,830건  C01 기말 대규모 (최대 ×1.4)
```

## 관련 파일
```
dashboard/
├── app.py                 # 메인 엔트리포인트
├── tab_summary.py         # Tab 1: Executive Summary (MVP)
├── tab_benford.py         # Tab 2: Benford Analysis (MVP)
├── tab_explorer.py        # Tab 3: Anomaly Explorer (MVP)
├── tab_chat.py            # Tab 4: Text-to-SQL Chat (Phase 3)
├── tab_export.py          # Tab 5: Export (Phase 3)
└── components/
    ├── data_uploader.py       # 파일 업로드 위젯
    ├── charts.py              # Plotly 차트 래퍼
    ├── filters.py             # 공통 필터 사이드바
    ├── threshold_sidebar.py   # 실시간 임계값 튜닝 슬라이더 (UX 4단계 A)
    └── preset_selector.py     # 산업별/시즌별 프리셋 드롭다운 (UX 4단계 C)
```

## 핵심 클래스/함수

### `app.py` — 메인 엔트리
```python
def main():
    """Streamlit 메인 앱.
    1. 사이드바: 파일 업로드 + 공통 필터
    2. 메인: 탭 전환 (Summary | Benford | Explorer | Chat | Export)
    3. session_state로 파이프라인 결과 캐싱
    """
    st.set_page_config(page_title="AI Audit Assistant", layout="wide")

    # 사이드바
    with st.sidebar:
        uploaded_file = data_uploader.render()
        if uploaded_file:
            result = run_pipeline(uploaded_file)  # session_state 캐싱
        filters.render(result)

    # 탭
    tabs = st.tabs(["Summary", "Benford", "Explorer", "Chat", "Export"])
    with tabs[0]: tab_summary.render(result)
    with tabs[1]: tab_benford.render(result)
    with tabs[2]: tab_explorer.render(result)
    # tabs[3], tabs[4]: Phase 3
```

### `components/data_uploader.py`
```python
def render() -> UploadedFile | None:
    """파일 업로드 위젯.
    - st.file_uploader (xlsx/xls/csv)
    - 업로드 후 자동으로 AuditPipeline.run() 트리거
    - 진행 상태 표시 (st.progress)
    """
```

### `components/charts.py` — Plotly 차트 래퍼 (11종)
```python
# ── 기존 5종 (구체화) ──

def risk_heatmap(df: DataFrame) -> go.Figure:
    """fiscal_period(1~12) × business_process(6종) 위험 히트맵.
    색상=평균 anomaly_score. pivot_table로 생성."""

def risk_donut(summary: DataFrame) -> go.Figure:
    """High/Medium/Low/Normal 분포 도넛 차트.
    groupby(risk_level).count()."""

def benford_overlay(digits_df: DataFrame) -> go.Figure:
    """Benford 관측 vs 기대 빈도 오버레이 바+라인 차트.
    X=digit(1~9). 바=observed_freq, 라인=expected_freq.
    편차 > MAD 기준인 digit 강조."""

def anomaly_scatter(df: DataFrame) -> go.Figure:
    """debit_amount vs anomaly_score 산점도. 색상=risk_level.
    hover: document_id, business_process, flagged_rules."""

def monthly_trend(df: DataFrame) -> go.Figure:
    """월별 추이 라인 차트. X=fiscal_period(1~12).
    2개 시리즈: 전체 건수 / 이상 건수."""

# ── 신규 6종 ──

def process_distribution_bar(df: DataFrame) -> go.Figure:
    """business_process별 전표 건수 + 이상 비율 이중축 바 차트.
    X=business_process(6종). 좌축=건수(바), 우축=이상비율(라인)."""

def persona_risk_matrix(df: DataFrame) -> go.Figure:
    """user_persona(5종) × risk_level(4등급) 교차표 히트맵.
    색상=건수. 대각선 패턴으로 controller/manager의 R2R 집중도 확인."""

def company_comparison(df: DataFrame) -> go.Figure:
    """company_code(3법인)별 KPI 비교 그룹 바 차트.
    그룹: 전표수, 이상 전표수, 평균 anomaly_score."""

def hourly_heatmap(df: DataFrame) -> go.Figure:
    """X=요일(월~일), Y=시간(0~23), 색상=전표 건수.
    posting_date에서 hour, weekday 추출.
    심야(0~6)/주말 영역에 점선 박스 오버레이 → C02/C03 탐지 연계."""

def fraud_type_treemap(df: DataFrame) -> go.Figure:
    """fraud_type별 건수 Treemap (13종).
    개발 모드에서만 표시. 색상=대응 탐지 룰 레이어."""

def layer_score_radar(scores: dict) -> go.Figure:
    """선택 전표의 Layer A/B/C/Benford 점수 방사형 차트.
    Explorer 탭 행 선택 시 상세 패널에 표시."""
```

### `components/filters.py` — 공통 필터
```python
def render(result: PipelineResult) -> dict:
    """사이드바 공통 필터.

    기본 필터 (항상 노출):
    - 날짜 범위 (date_input): posting_date 기준
    - risk_level 선택 (multiselect): High / Medium / Low / Normal
    - 금액 범위 (slider): debit_amount + credit_amount
    - 위반 룰 선택 (multiselect): A01~A03, B01~B11, C01~C10 (24개 룰)

    차원 필터 (st.expander "상세 필터" 내부, 점진적 공개):
    - business_process (multiselect): P2P, O2C, R2R, H2R, TRE, A2R
    - company_code (multiselect): C001, C002, C003
    - user_persona (multiselect): automated_system, junior, senior, controller, manager
    - source (multiselect): Automated, Manual, Recurring, Adjustment
    - document_type (multiselect): SA, KR, KZ, DR, DZ, WE, WL, AA, HR, IC
    - gl_account (multiselect): 계정과목 검색

    개발 모드 전용 (st.sidebar.checkbox "개발 모드" 활성 시):
    - fraud_type (multiselect): 13종 부정 유형
    - anomaly_type (multiselect): 10종 이상징후 유형

    필터 옵션값은 DuckDB batch_ledger의 DISTINCT에서 동적 추출.
    session_state에 필터 상태 dict 저장 → 모든 탭에 동기 적용.
    """
```

### `components/threshold_sidebar.py` — 실시간 임계값 튜닝 (UX 4단계 A)
```python
def render(settings: AuditSettings) -> AuditSettings:
    """탐지 기준 슬라이더 패널.
    - st.expander("⚙️ 탐지 기준 상세 설정") 안에 배치 (점진적 공개)
    - AuditSettings의 threshold 필드를 슬라이더/입력 위젯으로 노출
    - 값 변경 시 AuditSettings 복사본을 오버라이드하여 반환
    - session_state에 캐싱하여 탭 전환 시 유지
    """
```

### `components/preset_selector.py` — 산업별/시즌별 프리셋 (UX 4단계 C)
```python
def render() -> AuditSettings | None:
    """환경 프리셋 드롭다운.
    - st.selectbox: 평시 모드 / 결산기 모드 / 건설업 모드 / 커스텀
    - 프리셋 선택 시 config/presets/{name}.yaml 로드 → AuditSettings 반환
    - threshold_sidebar 슬라이더 값을 일괄 갱신
    - 커스텀 프리셋 저장/로드 (프로파일 재사용 원칙)
    """
```

### `tab_summary.py` — Tab 1: Executive Summary
```python
def render(result: PipelineResult):
    """경영진 요약 대시보드.

    ── KPI 메트릭 카드 (st.metric × 6, st.columns(6)) ──
    1. 총 전표수       COUNT DISTINCT(document_id)
    2. 총 라인아이템수  COUNT(*)
    3. 이상 전표수      risk_level != 'Normal'
    4. 이상 비율(%)     이상 전표수 / 총 전표수
    5. 이상 금액 합계   SUM(debit_amount) WHERE risk_level IN ('High','Medium')
    6. 부정 의심 건수   flagged_rules에 B 레이어 룰 포함 건수

    ── Row 1: 전체 현황 (st.columns([2, 1])) ──
    좌: 24개 룰(A/B/C 3레이어) 위반 건수 가로 바 차트
        X=flagged_count, Y=rule_code (A01~A03, B01~B11, C01~C10)
        색상: Layer A=파랑, Layer B=빨강, Layer C=노랑
        데이터: anomaly_flag_summary VIEW
    우: 위험 등급 도넛 차트
        High/Medium/Low/Normal 4분류
        데이터: batch_ledger → groupby(risk_level)

    ── Row 2: 시계열 + 히트맵 (st.columns(2)) ──
    좌: 월별 이상 전표 추이 라인 차트
        X=fiscal_period(1~12), 2개 시리즈(전체 건수 / 이상 건수)
        12월 피크(×1.4) 시각 확인
        데이터: batch_ledger → groupby(fiscal_period)
    우: 위험 히트맵 (fiscal_period × business_process)
        X=fiscal_period(1~12), Y=business_process(6종)
        색상=셀 내 평균 anomaly_score
        데이터: batch_ledger → pivot_table

    ── Row 3: 차원별 분석 (st.columns(3)) ──
    좌: 프로세스별 전표 건수 + 이상 비율 이중축 바 차트
        X=business_process(6종)
    중: 페르소나 × 위험등급 교차표 히트맵
        X=user_persona(5종), Y=risk_level(4등급), 색상=건수
    우: 법인별 KPI 비교 그룹 바 차트
        X=company_code(3법인), 그룹=전표수/이상수/이상비율

    ── Row 4: 데이터 품질 ──
    전처리 리포트 요약 (데이터 품질 점수, 결측률, 타입 매칭률)
    """
```

### `tab_benford.py` — Tab 2: Benford Analysis
```python
def render(result: PipelineResult):
    """Benford 분석 전용 탭.

    ── 데이터 소스 ──
    전체 통계: benford_summary 테이블 (배치당 1행)
              → sample_size, mad, mad_conformity, chi2_statistic,
                chi2_p_value, ks_statistic, ks_p_value, is_conforming
    자릿수 분포: benford_digits 테이블 (배치당 9행, digit 1~9)
              → digit, observed_freq, expected_freq, deviation
    원본 전표: general_ledger 테이블의 first_digit 피처 컬럼
              (batch_ledger SELECT에 미포함 → Benford 드릴다운 전용 쿼리 필요)

    ── Row 1: 전체 Benford 결과 ──
    좌: 첫째 자릿수 오버레이 바+라인 차트
        X=digit(1~9), Y=frequency
        바=observed_freq, 라인=expected_freq (Benford 이론값)
        편차 > MAD 기준: 해당 바 강조 표시
    우: MAD/KS 검정 결과 카드 (st.metric × 4)
        MAD 값 + 적합성 판정 (Nigrini 기준: Close/Acceptable/Marginal/Nonconformity)
        Chi-square p-value + KS p-value
        참고: Benford 적합 기준 MAD < 0.012 (settings.benford_mad_threshold)

    ── Row 2: 분리 분석 ──
    Spike Drill: digit 바 클릭 시 해당 first_digit 전표 AgGrid 필터링
    분리 기준 (st.selectbox):
      - business_process별 (6종): P2P, O2C, R2R, H2R, TRE, A2R
      - company_code별 (3종): C001, C002, C003
      - source별 (4종): Automated, Manual, Recurring, Adjustment
    분리 시 batch_ledger에서 first_digit 재집계 → 소형 다중 바 차트 (facet)
    주의: recurring, payroll(H2R) 소스는 Benford 제외 대상 → UI에 경고 표시
    """
```

### `tab_explorer.py` — Tab 3: Anomaly Explorer
```python
def render(result: PipelineResult):
    """이상 전표 상세 탐색.

    ── AgGrid 컬럼 구성 ──
    고정 컬럼 (pinned left):
      document_id, risk_level, anomaly_score

    기본 표시 컬럼:
      company_code, posting_date, document_type, business_process,
      gl_account, debit_amount, credit_amount, created_by,
      user_persona, source, flagged_rules

    숨김 컬럼 (Column Chooser로 토글):
      fiscal_year, fiscal_period, document_date, line_number,
      header_text, line_text, reference, approved_by,
      is_fraud, fraud_type, is_anomaly, anomaly_type,
      sod_violation, sod_conflict_type
    주의: fiscal_period, line_number, line_text 등은 현재 batch_ledger SELECT에
          미포함. Phase 1c 구현 시 batch_ledger 확장 또는 별도 쿼리 필요.

    ── 조건부 서식 ──
    risk_level 셀:    High=빨강(#FF4B4B), Medium=주황(#FFA500),
                      Low=노랑(#FFD700), Normal=초록(#00CC96)
    anomaly_score:    그라디언트 바 (0.0~1.0, 투명→빨강)
    source='Manual':  행 배경 하이라이트 (#FFF3CD)
    sod_violation:    true일 때 아이콘 표시

    ── 정렬·페이지네이션 ──
    기본 정렬: anomaly_score DESC (위험 전표 우선)
    page_size=100 (1,106,356 라인 직접 로드 방지)

    ── 행 선택 시 상세 패널 ──
    document_rule_detail 쿼리 → track_name, rule_code, score 표시
    룰별 점수 breakdown 가로 바 차트 (A/B/C 레이어 색상 구분)
    원본 데이터 전문 표시 (해당 document_id의 전체 라인아이템)

    ── HITL 예외 처리 (UX 4단계 B) ──
    "예외 처리" 체크박스 컬럼 + [예외 저장] 버튼
    → DuckDB whitelist 테이블에 INSERT (batch_id, document_id, rule_code, reason)
    → 다음 탐지 시 ANTI JOIN으로 제외

    ── Phase 2 확장 ──
    SHAP waterfall plot: 선택 전표의 ML 피처 기여도 시각화
    잠재 공간 시각화 (t-SNE/UMAP): 정상/이상 클러스터 분포
    """
```

### `tab_chat.py` — Tab 4: Text-to-SQL (Phase 3)
```python
def render(result: PipelineResult):
    """자연어 질의 탭.
    - st.chat_input으로 질문 입력
    - Vanna AI → SQL 생성 → 실행 → 결과 표시
    - 자동 Plotly 차트 생성
    - 감사 프리셋 질문 6종 버튼
    """
```

### `tab_export.py` — Tab 5: Export (Phase 3)
```python
def render(result: PipelineResult):
    """감사조서 내보내기 탭.
    - Excel 다운로드 (이상 전표 + 분석 결과)
    - PDF 감사조서 다운로드
    - Audit Trail 로그 다운로드
    - 내보내기 범위 선택 (전체/필터링/선택)
    """
```

## 데이터 흐름
```
[사용자]
   ↓ 파일 업로드
data_uploader → AuditPipeline.run(file)
                      ↓
               PipelineResult (session_state에 캐싱)
                      ↓
         ┌────────────┼────────────┐
         ▼            ▼            ▼
   tab_summary   tab_benford   tab_explorer
   (DuckDB 쿼리)  (Benford 결과)  (AgGrid 테이블)
         │            │            │
         └────────────┴────────────┘
                      ↓
              charts.py (Plotly 시각화)
```

## DuckDB 쿼리 매핑

> 참조: [06-db.md](06-db.md) — PRESET_QUERIES, general_ledger DDL

### 기존 PRESET_QUERIES → 대시보드 컴포넌트 매핑

| 대시보드 컴포넌트        | 프리셋 쿼리            | 후처리 (pandas)                                |
|:------------------------|:----------------------|:-----------------------------------------------|
| KPI 카드 (6종)          | `batch_ledger`        | groupby(risk_level) → count, sum(debit_amount) |
| 24개 룰 위반 바 차트     | `rule_violation_stats`| 직접 표시 (flagged_count, avg_score)           |
| 위험 히트맵             | `batch_ledger`        | pivot_table(fiscal_period × business_process)   |
| Benford 오버레이        | `benford_digits`      | 직접 표시 (digit, observed_freq, expected_freq) |
| Benford 통계 카드       | `benford_summary`     | 직접 표시 (mad, chi2, ks, is_conforming)        |
| AgGrid 테이블           | `batch_ledger`        | 필터 적용 후 page_size=100 표시                |
| 행 상세 패널            | `document_rule_detail`| 직접 표시 (track_name, rule_code, score)        |
| 플래그 집계             | `batch_flags`         | groupby(rule_code) → count, avg_score          |

### 대시보드 전용 추가 쿼리 (Phase 1c 구현 시 queries.py에 추가)

> 이 쿼리는 [06-db.md](06-db.md)에 미등록 상태. Phase 1c 구현 시 06-db.md PRESET_QUERIES에 추가 필요.
> batch_ledger SELECT에 `fiscal_period` 컬럼 추가도 필요 (현재 미포함).

```sql
-- process_summary: 프로세스별 집계
SELECT business_process,
       COUNT(DISTINCT document_id) AS doc_count,
       COUNT(DISTINCT CASE WHEN risk_level != 'Normal' THEN document_id END) AS anomaly_count,
       ROUND(AVG(anomaly_score), 4) AS avg_score
FROM general_ledger
WHERE upload_batch_id = ?
GROUP BY business_process;

-- persona_risk_cross: 페르소나 × 위험등급 교차표
SELECT user_persona, risk_level, COUNT(DISTINCT document_id) AS doc_count
FROM general_ledger
WHERE upload_batch_id = ?
GROUP BY user_persona, risk_level;

-- company_kpi: 법인별 KPI
SELECT company_code,
       COUNT(DISTINCT document_id) AS doc_count,
       COUNT(DISTINCT CASE WHEN risk_level != 'Normal' THEN document_id END) AS anomaly_count,
       SUM(debit_amount) AS total_debit
FROM general_ledger
WHERE upload_batch_id = ?
GROUP BY company_code;

-- hourly_pattern: 시간대별 패턴 (posting_date에서 시간/요일 추출)
SELECT EXTRACT(DOW FROM posting_date) AS weekday,
       EXTRACT(HOUR FROM posting_date) AS hour,
       COUNT(*) AS line_count
FROM general_ledger
WHERE upload_batch_id = ?
GROUP BY weekday, hour;

-- sod_summary: SoD 위반 요약
SELECT sod_conflict_type, user_persona,
       COUNT(DISTINCT document_id) AS violation_count
FROM general_ledger
WHERE upload_batch_id = ? AND sod_violation = true
GROUP BY sod_conflict_type, user_persona;
```

---

## 분석 뷰 (탭 내부 서브뷰)

### 시간 패턴 차트 — Summary 탭 Row 확장 또는 별도 서브탭

대시보드에서 시계열 이상 패턴을 시각적으로 탐지하는 3종 차트.

| 차트               | 유형         | X축          | Y축         | 색상         | 데이터 소스      |
|:-------------------|:------------|:-------------|:------------|:-------------|:----------------|
| 시간대별 히트맵    | Heatmap     | 요일(월~일)  | 시간(0~23)  | 전표 건수    | hourly_pattern   |
| 월별 추이          | Line        | fiscal_period| 건수        | 전체/이상    | batch_ledger     |
| 일별 달력 히트맵   | Heatmap     | 주(1~52)     | 요일(월~일) | 일별 이상 건수| batch_ledger    |

- 시간대별 히트맵에 심야(0~6)/주말 영역 점선 박스 → C02/C03 탐지 영역 표시
- 월별 추이에서 분기말(3,6,9,12월) 수직 참조선 + 12월 피크(×1.4) 주석
- 일별 달력은 GitHub contribution 스타일 (1년 전체 조감)

### SoD 분석 뷰 — Explorer 탭 서브뷰 또는 별도 서브탭

직무분리(Segregation of Duties) 위반 현황 분석.

| 요소               | 내용                                                              |
|:-------------------|:-----------------------------------------------------------------|
| KPI 카드           | SoD 위반 건수(1,080), 위반 비율(1.0%), 위반 사용자 수             |
| 충돌 유형 바 차트  | sod_conflict_type × 건수 (preparer_approver 49%, requester_approver 15% 등) |
| 교차표 히트맵      | user_persona(5종) × sod_conflict_type(6종), 색상=건수            |
| 드릴다운           | 바/셀 클릭 시 Explorer AgGrid에 해당 조건 필터 적용              |

- 데이터 소스: sod_summary 쿼리 + batch_ledger WHERE sod_violation = true
- SoD 충돌 유형: preparer_approver, requester_approver, payment_releaser, reconciler_poster, journal_entry_poster, master_data_maintainer

### 프로세스별 뷰 — Phase 2c (별도 탐지기 필요)

비즈니스 프로세스별 거래 흐름과 핵심 탐지 룰을 연결하는 전문가용 뷰.

| 프로세스 | 핵심 document_type | 핵심 탐지 룰                  | 시각화                          |
|:---------|:-------------------|:------------------------------|:--------------------------------|
| P2P      | KR, KZ, WE         | B04(중복지급), B02/B03(승인한도), B08(수기) | Sankey (KR→WE→KZ), 벤더 집중도 |
| O2C      | DR, DZ, WL         | B01(매출이상), C01(기말대규모), C08(고액)   | 매출 월별 추이, 고객 집중도    |
| R2R      | SA, IC              | C06(위험적요), C09(비정상 계정조합), A01     | 결산 수정 히트맵, 계정 네트워크 |
| H2R      | HR                  | B07(SoD), C02/C03(주말/심야)                | 급여 변동 추이                 |
| TRE      | KZ, SA              | B06(자기승인), B09(승인생략)                 | 자금 이동 흐름                 |
| A2R      | AA                  | C08(이상고액), Phase 2 ML(ImproperCapitalization) | 자산 취득/처분 타임라인   |

### IC 거래 뷰 — Phase 2c (별도 탐지기 필요)

내부거래(Intercompany) 매칭 및 이상 탐지.

| 요소                | 내용                                                          |
|:--------------------|:-------------------------------------------------------------|
| 법인 간 거래 Chord  | 3개 노드(C001/C002/C003), 양방향 링크, 두께=거래금액         |
| IC 유형별 비중      | GoodsSale(35%), ServiceProvided(20%), ManagementFee(15%) 등  |
| 매칭/불일치 표      | lettrage 컬럼 기반 매칭 쌍 식별 → 미매칭 건수 표시           |
| 탐지 연계           | B10(관계사 순환거래) 플래그 드릴다운                         |

- 데이터 소스: batch_ledger WHERE is_intercompany = true, trading_partner 컬럼
- IC 매칭 쌍: 98쌍 (매수/매도 양측 전표 동시 생성, 월별 네팅)
- 이전가격: Cost-Plus 5% 마크업 → 정상가격 범위 이탈 시 TransferPricingAnomaly 표시

---

## 구현 순서
1. `components/data_uploader.py` — 파일 업로드 + 파이프라인 트리거
2. `components/charts.py` — Plotly 차트 래퍼 11종
3. `components/filters.py` — 사이드바 공통 필터 (기본 4 + 차원 6 + 개발 2)
4. `components/preset_selector.py` — 환경 프리셋 드롭다운 (UX 4단계 C)
5. `components/threshold_sidebar.py` — 실시간 임계값 튜닝 슬라이더 (UX 4단계 A)
6. `tab_summary.py` — KPI 6개 + 차트 7종 조합
7. `tab_benford.py` — Benford 시각화 + BP/법인/소스별 드릴다운
8. `tab_explorer.py` — AgGrid(27컬럼) + 상세 패널 + HITL 예외 처리 (UX 4단계 B)
9. `app.py` — 3탭 통합 + session_state 관리 + 개발 모드 토글
10. (Phase 3) `tab_chat.py`, `tab_export.py`

## 의존성
- **선행:** `06-db` (DuckDB 쿼리), `05-detection` (PipelineResult)
- **외부 패키지:** `streamlit`, `plotly`, `streamlit-aggrid`
- **후행:** `08-llm` (tab_chat에서 Vanna 연동), `09-export` (tab_export에서 내보내기)

## 테스트 전략
- **수동 테스트:** `uv run streamlit run dashboard/app.py` → 3탭 정상 렌더링 확인
- **차트 테스트:** 각 차트 함수에 샘플 DataFrame → Figure 객체 반환 확인
- **필터 연동:** 필터 변경 시 모든 탭 데이터 갱신 확인
- **빈 데이터:** 업로드 전 / 필터 결과 0건 시 에러 없이 빈 상태 표시
- **임계값 튜닝:** 슬라이더 변경 → 탐지 재실행 → 결과 건수 변동 확인
- **프리셋 전환:** 프리셋 선택 → 슬라이더 값 일괄 변경 확인
- **HITL 예외 처리:** 전표 체크 → 예외 저장 → 재탐지 시 해당 전표 제외 확인

## Phase 구분
| 항목                                              | Phase          |
|:--------------------------------------------------|:---------------|
| data_uploader, charts(11종), filters(12개 차원)   | MVP (Phase 1c) |
| threshold_sidebar, preset_selector (UX 4단계)     | MVP (Phase 1c) |
| Tab 1: Summary (KPI 6개 + 차트 7종)               | MVP (Phase 1c) |
| Tab 2: Benford (오버레이 + BP/법인/소스 드릴다운) | MVP (Phase 1c) |
| Tab 3: Explorer (AgGrid 27컬럼 + HITL 예외 처리)  | MVP (Phase 1c) |
| 시간 패턴 차트 (시간대/월별/일별 히트맵)          | MVP (Phase 1c) |
| SoD 분석 뷰 (충돌유형 바 차트 + 교차표)           | MVP (Phase 1c) |
| Tab 3: SHAP waterfall + 잠재 공간 시각화          | Phase 2        |
| 프로세스별 뷰 (P2P/O2C/R2R Sankey + 탐지 연계)   | Phase 2c       |
| IC 거래 뷰 (법인 간 Chord + 매칭/불일치)          | Phase 2c       |
| Tab 4: Chat (Vanna Text-to-SQL)                   | Phase 3        |
| Tab 5: Export (Excel/PDF 감사조서)                 | Phase 3        |

## UX 디자인 원칙 (Phase 1c 필수 적용)

> 상세: [ux-flow.md → 3가지 UX 디자인 원칙](ux-flow.md#3가지-ux-디자인-원칙)

대시보드 구현 시 **감사 도구의 두 가지 상충 요구**(통제 요구 vs 간결성 요구)를 충족하는 3원칙:

| 원칙                                    | 대시보드 적용                                                                |
|:----------------------------------------|:----------------------------------------------------------------------------|
| **1. 스마트 디폴트 (Smart Defaults)**   | 모든 설정에 업계 표준 기본값 → [다음]만 눌러도 분석 가능                     |
| **2. 점진적 공개 (Progressive Disclosure)** | 기본 모드(업로드+시트+매핑) / 전문가 모드(⚙️ 접이식 Accordion)          |
| **3. 프로파일 재사용 (One-Time Setup)**  | 고객사별 설정 프로파일 저장 → 이후 감사 시 자동 로드                         |

**구현 가이드:**
- `data_uploader.py`: confidence ≥ 0.7이면 인코딩 드롭다운 숨김 (점진적 공개)
- `filters.py`: 감사 기준 상세 설정은 `st.expander("⚙️ 감사 기준 상세 설정", expanded=False)` 안에 배치
- `app.py`: 화면 상단에 프로파일 저장/로드 UI 노출 (mapping_profile + audit_rules)

---

## 미해결 이슈 (Phase 1c에서 해결 — 발견 위치 교차 참조)

Phase 1a ingest/feature에서 발견되었으나 UI가 필요하여 Phase 1c로 이관된 항목.

| 과제                            | 현상                                               | 해결 방향                                    | 발견 위치                                                    |
|:--------------------------------|:---------------------------------------------------|:---------------------------------------------|:-------------------------------------------------------------|
| Parquet 헤더 탐지 스킵          | 불필요한 헤더 탐지 시도                            | 오케스트레이터 `source_format` 분기          | [02-ingest §미해결](02-ingest.md#미해결-이슈-발견--해결-교차-참조) |
| 멀티시트 UI 선택                | active_sheet가 데이터 양 무관                      | 시트 목록 + 행 수 → 사용자 선택              | [02-ingest §미해결](02-ingest.md#미해결-이슈-발견--해결-교차-참조) |
| Fuzzy 추천 부정확               | monat→debit_amount 등 오추천                       | ReviewItem UI 확인/변경 → 프로파일 저장      | [02-ingest §미해결](02-ingest.md#미해결-이슈-발견--해결-교차-참조) |
| 매핑 프로파일 학습              | 반복 업로드 시 매번 매핑                           | 프로파일 우선 적용                           | [02-ingest §미해결](02-ingest.md#미해결-이슈-발견--해결-교차-참조) |
| ReviewItem UI 노출              | 판단 근거 데이터 준비됨, UI 미구현                 | 3-tier 시각 피드백(초록/노랑/빨강)           | [02-ingest §미해결](02-ingest.md#미해결-이슈-발견--해결-교차-참조) |
| 차단 vs unmapped 미구분         | 타입 차단 사유 미표시                              | ReviewItem.reason 세분화                     | [02-ingest §미해결](02-ingest.md#미해결-이슈-발견--해결-교차-참조) |
| ~~is_after_hours 날짜 경계~~    | ✅ **버그 아님** — `dt.hour` 기반 자정 걸침 정확 처리 확인 | —                                            | [03-feature §G](03-feature.md#g-미해결-이슈-발견--해결-교차-참조) |
| 업종별 영업일 차이              | 단일 bdate_range 기준 (공휴일 미반영)              | 업종 선택 UI + holidays 패키지 연동          | [04-validation §5](../../tests/test_validation/test-results/validation-all-results.md) |
| fiscal_period_mismatch NaN(SAP) | sap-merged에서 전체 NaN                            | 매핑 리뷰 UI에서 원인 규명                   | [e2e-sap-merged.md §3](../../tests/test_feature/test-results/e2e-sap-merged.md) |
| sap-merged debit/credit 미매핑  | amount 카테고리 전체 스킵 (5개 피처 미생성)        | 수동 매핑 조정                               | [e2e-sap-merged.md §3](../../tests/test_feature/test-results/e2e-sap-merged.md) |
| schreyer-fraud gl_account 오매핑 | 캐스팅 후 결측률 100%                             | 타입 호환성 재확인                           | [ingest-validation-datasets.md](../../tests/test_ingest/test-results/ingest-validation-datasets.md) |
| datetime `.values`→`.array`      | 타임존 정보 손실 (`.values`가 ndarray 반환)       | `.array` 전환으로 타임존 보존               | [eda-profiling.md §코드리뷰](../../tests/test_eda/test-results/eda-profiling.md)                    |
| `top_values` 반환 타입 계약      | tuple 반환이지만 대시보드 JSON 직렬화 시 list 기대 | 인터페이스 문서 + 타입 통일                 | [eda-profiling.md §코드리뷰](../../tests/test_eda/test-results/eda-profiling.md)                    |

---

## 감사인 친화적 지표 표시

### ML 지표 비전문가 설명 (Phase 2 대시보드 반영)

감사인은 ML 지표에 익숙하지 않을 수 있다. 각 지표 옆에 tooltip/info icon으로 한글 설명 표시.

| 지표         | tooltip 설명                                                          |
|:-------------|:----------------------------------------------------------------------|
| AUPRC        | "모델이 부정 전표를 얼마나 정확하게 골라내는지를 나타내는 종합 점수 (0~1)" |
| F2-score     | "부정을 놓치지 않는 능력에 가중치를 둔 정확도 (0~1)"                    |
| DR@FAR=5%    | "오탐 5건을 허용할 때 실제 부정을 몇 건 잡는지"                         |
| risk_level   | 위험 등급 기준: High(>0.7), Medium(>0.4), Low(>0.2), Normal(≤0.2)     |

잠재 공간 시각화(t-SNE/UMAP)도 Tab에 포함하여 모델 학습 결과를 시각적으로 확인 가능하게 한다.

---

## 구현 시 주의사항
- **session_state:** 파이프라인 결과를 `st.session_state`에 캐싱 → 탭 전환 시 재실행 방지
- **layout="wide":** 데이터 분석 대시보드는 와이드 레이아웃 필수
- **AgGrid 설정:** 행 선택 모드, 컬럼 고정(document_id/risk_level/anomaly_score), 조건부 서식(risk_level별 색상) 적용
- **차트 한글:** Plotly 한글 폰트 설정 (Noto Sans KR 등)
- **반응형:** `st.columns`로 레이아웃 구성, 모바일 대비는 불필요 (데스크톱 전용)
- **에러 핸들링:** 업로드 실패, 파이프라인 에러 시 사용자에게 명확한 메시지 표시
- **대용량 대응:** 1,106,356 라인아이템을 AgGrid에 직접 로드하지 않음. batch_ledger 쿼리가 anomaly_score DESC 정렬이므로 상위 N건만 초기 표시. AgGrid pagination(page_size=100) 적용.
- **필터 연쇄:** 사이드바 필터 변경 시 모든 탭의 DataFrame을 동일 조건으로 필터. session_state에 필터 상태 dict 저장, 각 탭 render() 진입 시 적용.
- **개발 모드 토글:** DataSynth 라벨 컬럼(is_fraud, fraud_type, is_anomaly, anomaly_type)은 개발/검증 모드에서만 표시. `st.sidebar.checkbox("개발 모드")` 토글로 제어. 프로덕션 모드에서는 숨김 처리.
- **DuckDB 쿼리 캐싱:** 동일 batch_id + 동일 필터 조건의 쿼리 결과를 `@st.cache_data`로 캐싱. 필터 변경 시에만 재쿼리.
