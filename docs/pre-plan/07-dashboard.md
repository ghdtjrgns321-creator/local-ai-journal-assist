# 07. Streamlit 대시보드

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
    ├── data_uploader.py   # 파일 업로드 위젯
    ├── charts.py          # Plotly 차트 래퍼
    └── filters.py         # 공통 필터 사이드바
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
4. `tab_summary.py` — KPI + 차트 조합
5. `tab_benford.py` — Benford 시각화 + 드릴다운
6. `tab_explorer.py` — AgGrid 테이블 + 상세 패널
7. `app.py` — 3탭 통합 + session_state 관리
8. (Phase 3) `tab_chat.py`, `tab_export.py`

## 의존성
- **선행:** `06-db` (DuckDB 쿼리), `05-detection` (PipelineResult)
- **외부 패키지:** `streamlit`, `plotly`, `streamlit-aggrid`
- **후행:** `08-llm` (tab_chat에서 Vanna 연동), `09-export` (tab_export에서 내보내기)

## 테스트 전략
- **수동 테스트:** `uv run streamlit run dashboard/app.py` → 3탭 정상 렌더링 확인
- **차트 테스트:** 각 차트 함수에 샘플 DataFrame → Figure 객체 반환 확인
- **필터 연동:** 필터 변경 시 모든 탭 데이터 갱신 확인
- **빈 데이터:** 업로드 전 / 필터 결과 0건 시 에러 없이 빈 상태 표시

## Phase 구분
| 항목                           | Phase          |
|--------------------------------|----------------|
| data_uploader, charts, filters | MVP (Phase 1c) |
| Tab 1: Summary                 | MVP (Phase 1c) |
| Tab 2: Benford                 | MVP (Phase 1c) |
| Tab 3: Explorer (AgGrid)       | MVP (Phase 1c) |
| Tab 3: SHAP waterfall          | Phase 2        |
| Tab 4: Chat (Vanna)            | Phase 3        |
| Tab 5: Export                   | Phase 3        |

## 구현 시 주의사항
- **session_state:** 파이프라인 결과를 `st.session_state`에 캐싱 → 탭 전환 시 재실행 방지
- **layout="wide":** 데이터 분석 대시보드는 와이드 레이아웃 필수
- **AgGrid 설정:** 행 선택 모드, 컬럼 고정, 조건부 서식(risk_level별 색상) 적용
- **차트 한글:** Plotly 한글 폰트 설정 (Noto Sans KR 등)
- **반응형:** `st.columns`로 레이아웃 구성, 모바일 대비는 불필요 (데스크톱 전용)
- **에러 핸들링:** 업로드 실패, 파이프라인 에러 시 사용자에게 명확한 메시지 표시
