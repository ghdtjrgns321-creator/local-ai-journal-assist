# 07. Streamlit 대시보드 [Phase 1c — 의존: 06]

## 목적
DuckDB에 적재된 감사 분석 결과를 5개 탭으로 시각화한다.
파일 업로드 → 분석 실행 → 결과 탐색까지 원스톱 워크플로우 제공.

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

### `components/charts.py` — Plotly 차트 래퍼
```python
def risk_heatmap(df: DataFrame) -> go.Figure:
    """월별 × 계정별 위험 히트맵."""

def risk_pie_chart(summary: DataFrame) -> go.Figure:
    """High/Medium/Low 분포 파이 차트."""

def benford_overlay(observed: list, expected: list) -> go.Figure:
    """Benford 관측 vs 기대 빈도 오버레이 바 차트."""

def anomaly_scatter(df: DataFrame) -> go.Figure:
    """금액 vs anomaly_score 산점도. 색상=risk_level."""

def monthly_trend(df: DataFrame) -> go.Figure:
    """월별 이상거래 추이 라인 차트."""
```

### `components/filters.py` — 공통 필터
```python
def render(result: PipelineResult) -> dict:
    """사이드바 공통 필터.
    - 날짜 범위 (date_input)
    - risk_level 선택 (multiselect)
    - 계정과목 선택 (multiselect)
    - 금액 범위 (slider)
    - 위반 룰 선택 (A01~C09) (multiselect)
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
    - 4개 KPI 메트릭 카드: 총 전표수, 이상 전표수, 이상 비율, 총 이상 금액
    - 위험 등급 파이 차트
    - 월별 이상 추이 라인 차트
    - 위험 히트맵 (월별 × 계정별)
    - 22개 룰(A/B/C 레이어) 위반 건수 바 차트
    - 전처리 리포트 요약 (데이터 품질 점수)
    """
```

### `tab_benford.py` — Tab 2: Benford Analysis
```python
def render(result: PipelineResult):
    """Benford 분석 전용 탭.
    - 첫째 자릿수 분포 오버레이 (관측 vs 기대)
    - MAD/KS 검정 결과 + 적합성 판정
    - Spike Drill: 특정 숫자 클릭 시 해당 전표 필터링
    - 계정별/기간별 Benford 분리 분석
    """
```

### `tab_explorer.py` — Tab 3: Anomaly Explorer
```python
def render(result: PipelineResult):
    """이상 전표 상세 탐색.
    - AgGrid 인터랙티브 테이블 (정렬, 필터, 검색)
    - 행 선택 시 상세 패널: 위반 룰(A01~C09), 점수 breakdown, 원본 데이터
    - risk_detail: 선택 전표의 이상 근거 상세 설명
    - HITL 예외 처리: "예외 처리" 체크박스 컬럼 + [예외 저장] 버튼 (UX 4단계 B)
      → DuckDB whitelist 테이블에 INSERT → 다음 탐지 시 ANTI JOIN으로 제외
    - SHAP waterfall plot (Phase 2)
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

## 구현 순서
1. `components/data_uploader.py` — 파일 업로드 + 파이프라인 트리거
2. `components/charts.py` — Plotly 차트 래퍼 5종
3. `components/filters.py` — 사이드바 공통 필터
4. `components/preset_selector.py` — 환경 프리셋 드롭다운 (UX 4단계 C)
5. `components/threshold_sidebar.py` — 실시간 임계값 튜닝 슬라이더 (UX 4단계 A)
6. `tab_summary.py` — KPI + 차트 조합
7. `tab_benford.py` — Benford 시각화 + 드릴다운
8. `tab_explorer.py` — AgGrid 테이블 + 상세 패널 + HITL 예외 처리 (UX 4단계 B)
9. `app.py` — 3탭 통합 + session_state 관리
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
| 항목                                          | Phase          |
|:----------------------------------------------|:---------------|
| data_uploader, charts, filters                | MVP (Phase 1c) |
| threshold_sidebar, preset_selector (UX 4단계) | MVP (Phase 1c) |
| Tab 1: Summary                                | MVP (Phase 1c) |
| Tab 2: Benford                                | MVP (Phase 1c) |
| Tab 3: Explorer (AgGrid + HITL 예외 처리)     | MVP (Phase 1c) |
| Tab 3: SHAP waterfall                         | Phase 2        |
| Tab 4: Chat (Vanna)                           | Phase 3        |
| Tab 5: Export                                  | Phase 3        |

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
- **AgGrid 설정:** 행 선택 모드, 컬럼 고정, 조건부 서식(risk_level별 색상) 적용
- **차트 한글:** Plotly 한글 폰트 설정 (Noto Sans KR 등)
- **반응형:** `st.columns`로 레이아웃 구성, 모바일 대비는 불필요 (데스크톱 전용)
- **에러 핸들링:** 업로드 실패, 파이프라인 에러 시 사용자에게 명확한 메시지 표시
