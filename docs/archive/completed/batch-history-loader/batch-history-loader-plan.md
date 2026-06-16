# Batch History Loader - Strategic Plan

## Executive Summary

Streamlit 재시작 후 session_state가 소멸되어 이전 분석 결과를 볼 수 없는 문제를 해결한다.
DuckDB에 배치 메타데이터 테이블을 추가하고, 저장된 배치를 조회/로드하여 session_state를 복원하는 기능을 구현한다.

## Current State

- 파이프라인 결과는 `general_ledger`, `anomaly_flags`, `benford_summary`, `benford_digits` 4개 테이블에 `upload_batch_id` 기준으로 저장됨
- Streamlit 재시작 시 `session_state`(PipelineResult, featured_data 등)가 전부 소멸
- 배치 목록을 조회하는 기능 없음 (어떤 배치가 DB에 있는지 알 수 없음)
- DB에서 배치 데이터를 읽어 PipelineResult를 재구성하는 기능 없음

## Proposed Solution

### 아키텍처 접근

1. **upload_batches 메타 테이블** 신설 — 배치 ID, 업로드 시간, 파일명, 행 수, 경고 메시지를 기록
2. **src/db/batch_reader.py** 신설 — DB에서 배치 데이터를 읽어 PipelineResult를 재구성
3. **대시보드 진입점 변경** — engagement 선택 후 "기존 결과 불러오기" vs "새 파일 업로드" 분기

### 데이터 흐름 (목표)

```
[신규 업로드]  파일 → ingest → pipeline → DB 저장(4테이블 + upload_batches) + session_state
[기존 로드]    engagement 선택 → upload_batches 조회 → 배치 선택 → batch_reader → session_state 복원
```

## Implementation Phases

### Phase 1: DB 스키마 + 메타 적재 (1일)

**Goal**: 파이프라인 실행 시 upload_batches 테이블에 메타데이터가 자동 기록된다.

- [ ] Task 1-1: `src/db/schema.py`에 upload_batches DDL 추가 — Size: S
- [ ] Task 1-2: `src/db/loader.py`의 `load_all()`에서 upload_batches INSERT — Size: S
- [ ] Task 1-3: `src/db/queries.py`에 배치 조회 프리셋 쿼리 2종 추가 — Size: S
- [ ] Task 1-4: 메타 적재 단위 테스트 — Size: M

### Phase 2: Batch Reader (1일)

**Goal**: DB에 저장된 배치를 PipelineResult로 복원할 수 있다.

- [ ] Task 2-1: `src/db/batch_reader.py` 신설 — list_batches() + load_batch() — Size: M
- [ ] Task 2-2: load_batch() 단위 테스트 — Size: M

### Phase 3: 대시보드 통합 (1일)

**Goal**: engagement 선택 후 저장된 배치를 선택하여 이전 분석 결과를 볼 수 있다.

- [ ] Task 3-1: `dashboard/components/batch_selector.py` 신설 — 배치 목록 UI — Size: M
- [ ] Task 3-2: `dashboard/app.py` 분기 로직 수정 — 배치 존재 시 선택 화면 표시 — Size: M
- [ ] Task 3-3: `dashboard/_state.py`에 복원 관련 키 추가 — Size: S

## Detailed Design

### Phase 1 상세

#### Task 1-1: upload_batches DDL

`src/db/schema.py`의 `SCHEMA_DDL` dict에 추가:

```sql
CREATE TABLE IF NOT EXISTS upload_batches (
    upload_batch_id VARCHAR PRIMARY KEY NOT NULL,
    file_name       VARCHAR,
    row_count       INTEGER NOT NULL,
    anomaly_count   INTEGER DEFAULT 0,
    high_risk_count INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT current_timestamp,
    warnings        VARCHAR
)
```

`UPLOAD_BATCHES_COLUMNS` 상수도 추가.

검증: `initialize_schema()` 실행 후 `SHOW TABLES`에 upload_batches 포함 확인.

#### Task 1-2: load_all()에 메타 적재

`src/db/loader.py`의 `load_all()` 함수 시그니처에 `file_name: str = ""` 파라미터 추가.
트랜잭션 내부에서 `upload_batches` INSERT 실행.

```python
conn.execute(
    "INSERT INTO upload_batches (upload_batch_id, file_name, row_count, anomaly_count, high_risk_count, warnings) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    [batch_id, file_name, gl_rows, af_rows, high_count, ";".join(warnings)]
)
```

`high_risk_count`는 df에서 `risk_level == 'High'` 행 수를 계산.

검증: `load_all()` 호출 후 `SELECT * FROM upload_batches` 결과에 해당 batch_id 존재 확인.

**file_name 전달 전략 (리뷰 피드백 #3 반영)**: 파이프라인 메서드 시그니처를 연쇄 오염시키지 않기 위해 `PipelineResult` 데이터클래스에 `file_name: str = ""` 필드를 추가한다. 파일명은 Ingest 단계에서 설정되어 PipelineResult까지 자연스럽게 흘러간다.

접근법:
1. `PipelineResult`에 `file_name: str = ""` 필드 추가
2. `data_uploader.py`의 `_run_pipeline_from_mapped()`에서 `pipeline.run_from_dataframe()` 호출 전에 파일명을 설정하거나, 반환된 PipelineResult에 file_name 할당
3. `_load_db()`에서 `self._result.file_name`을 `load_all()`에 전달
4. `run(path)` 메서드에서는 `Path(path).name`을 PipelineResult에 설정

#### Task 1-3: 프리셋 쿼리 추가

`src/db/queries.py`의 `PRESET_QUERIES`에 추가:

```python
"list_batches": """
    SELECT upload_batch_id, file_name, row_count,
           anomaly_count, high_risk_count, created_at
    FROM upload_batches
    ORDER BY created_at DESC
""",
"batch_meta": """
    SELECT upload_batch_id, file_name, row_count,
           anomaly_count, high_risk_count, created_at, warnings
    FROM upload_batches
    WHERE upload_batch_id = ?
""",
```

검증: `execute_preset(conn, "list_batches", params=())` 호출 시 에러 없이 DataFrame 반환.

참고: `list_batches`는 파라미터 없이 전체 조회하므로, `execute_preset`의 `params` 검증 로직에 빈 튜플 허용이 필요한지 확인. 현재 `params=None, batch_id=None`이면 ValueError 발생. `params=()`를 명시적으로 전달하면 우회 가능.

#### Task 1-4: 단위 테스트

`tests/modules/db/test_batch_meta.py` 신설.

테스트 케이스:
1. `load_all()` 실행 후 `upload_batches` 테이블에 메타데이터가 정확히 삽입되었는지 확인
2. `file_name`, `row_count`, `anomaly_count`, `high_risk_count` 값이 실제 데이터와 일치하는지 검증
3. 동일 batch_id로 중복 삽입 시 PRIMARY KEY 위반 에러 발생 확인

검증: `uv run pytest tests/modules/db/test_batch_meta.py -v` 전체 통과.

### Phase 2 상세

#### Task 2-1: batch_reader.py 신설

`src/db/batch_reader.py` (약 80줄):

```python
def list_batches(conn: DuckDBPyConnection) -> pd.DataFrame:
    """upload_batches 테이블에서 배치 목록 조회."""
    return execute_preset(conn, "list_batches", params=())

def load_batch(conn: DuckDBPyConnection, batch_id: str) -> PipelineResult:
    """DB에서 배치 데이터를 읽어 PipelineResult를 재구성."""
    # 1. general_ledger에서 해당 배치 행 조회
    # 2. anomaly_flags에서 해당 배치 플래그 조회 → Pseudo DetectionResult 역산
    # 3. benford_summary/digits 조회
    # 4. risk_summary 계산 (risk_level value_counts)
    # 5. PipelineResult 생성 (results=pseudo_results, featured_data=None)

def _reconstruct_detection_results(
    conn: DuckDBPyConnection, batch_id: str
) -> list[DetectionResult]:
    """anomaly_flags 테이블에서 rule_code별 Pseudo DetectionResult를 역산."""
    # 1. anomaly_flags에서 rule_code별 GROUP BY 집계
    #    - flagged_count: score > 0인 건수
    #    - avg_score, max_score
    # 2. track_name으로 Layer 식별
    # 3. 각 룰마다 DetectionResult 껍데기 생성
    #    - details DataFrame은 anomaly_flags 원본 행으로 구성
    #    - flagged_ids는 score > 0인 document_id 리스트
```

핵심 설계 결정:
- `PipelineResult.results`(DetectionResult 리스트)는 anomaly_flags 테이블에서 **Pseudo DetectionResult를 역산하여 재구성**한다. anomaly_flags를 rule_code별 GROUP BY로 집계하고, 각 룰마다 DetectionResult 껍데기 객체를 생성하여 results 리스트에 추가. 이렇게 해야 대시보드의 룰별 위반 건수 차트, 위험 등급별 분포 차트가 정상 작동한다.
- `featured_data`는 detection 결과 컬럼 포함 전의 스냅샷인데, DB의 `general_ledger`에는 detection 결과가 포함된 상태로 저장됨. None으로 설정하고, "재탐지" 기능은 DB 로드 시 비활성화.
- `anomaly_score`, `risk_level`, `flagged_rules`는 `general_ledger` 테이블에 저장되어 있으므로 대시보드 표시에는 문제 없음.

검증: `list_batches()` 반환 DataFrame의 컬럼이 예상과 일치하는지 확인. `load_batch()` 반환 PipelineResult의 `data` 행 수가 `upload_batches.row_count`와 일치하는지 확인.

#### Task 2-2: load_batch() 단위 테스트

`tests/modules/db/test_batch_reader.py` 신설.

테스트 케이스:
1. 파이프라인 실행 → DB 적재 → `load_batch()`로 복원 → 원본과 행 수, risk_summary 일치
2. 존재하지 않는 batch_id로 `load_batch()` 호출 시 빈 PipelineResult 또는 에러 반환
3. `list_batches()` 결과에 적재한 배치가 포함되어 있는지 확인

검증: `uv run pytest tests/modules/db/test_batch_reader.py -v` 전체 통과.

### Phase 3 상세

#### Task 3-1: batch_selector.py 신설

`dashboard/components/batch_selector.py` (약 60줄):

```python
def render_batch_selector(conn, on_load_callback) -> None:
    """저장된 배치 목록을 카드로 표시하고 선택 시 로드."""
    batches = list_batches(conn)
    if batches.empty:
        return  # 배치 없으면 아무것도 표시하지 않음

    st.subheader("이전 분석 결과")
    for idx, row in batches.iterrows():
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{row['file_name'] or '(파일명 없음)'}**")
                st.caption(
                    f"{row['row_count']:,}행 · 이상 {row['anomaly_count']:,}건 · "
                    f"High {row['high_risk_count']}건 · {row['created_at']}"
                )
            with col2:
                if st.button("불러오기", key=f"load_{row['upload_batch_id']}"):
                    on_load_callback(row['upload_batch_id'])
```

검증: Streamlit 실행 후 배치가 있는 engagement에서 카드가 표시되고, "불러오기" 버튼 클릭 시 분석 결과 탭으로 전환되는지 확인.

#### Task 3-2: app.py 분기 로직 수정

현재 `app.py` 162~166행:

```python
# 4) 결과 없음 → 업로드
if result is None:
    from dashboard.components.data_uploader import render_uploader
    render_uploader()
    st.stop()
```

변경 후:

```python
# 4) 결과 없음 → 배치 선택 또는 업로드
if result is None:
    from dashboard.components.batch_selector import render_batch_selector
    from dashboard.components.data_uploader import render_uploader

    conn = _conn_mgr.get(ctx.db_path)
    # 배치 선택기 (저장된 결과가 있으면 표시)
    def _on_batch_load(batch_id: str) -> None:
        from src.db.batch_reader import load_batch
        loaded = load_batch(conn, batch_id)
        ss[KEY_PIPELINE_RESULT] = loaded
        ss[KEY_BATCH_ID] = batch_id
        # file_name을 upload_count에 설정 (사이드바 표시용)
        meta = execute_preset(conn, "batch_meta", params=(batch_id,))
        if not meta.empty:
            ss[KEY_UPLOAD_COUNT] = meta.iloc[0]["file_name"] or ""
        st.rerun()

    render_batch_selector(conn, _on_batch_load)

    st.divider()
    render_uploader()
    st.stop()
```

검증: 
1. 배치가 있는 engagement: 상단에 배치 카드 표시 + 하단에 업로드 위젯
2. 배치가 없는 engagement: 업로드 위젯만 표시
3. 배치 선택 후: 분석 결과 탭(5탭)이 정상 렌더링

#### Task 3-3: _state.py 키 추가

`dashboard/_state.py`에 추가:

```python
KEY_LOADED_FROM_DB = "audit_loaded_from_db"  # bool (DB에서 로드한 결과인지)
```

`_DEFAULTS`에 `KEY_LOADED_FROM_DB: False` 추가.

이 플래그의 용도:
- DB에서 로드한 결과는 `featured_data`가 None이므로 "재탐지" 버튼을 비활성화
- "다른 파일 분석" 버튼 클릭 시 리셋 대상에 포함
- **읽기 전용 모드 배지 표시**: `KEY_LOADED_FROM_DB == True`일 때 대시보드 상단에 `st.info("DB에서 불러온 과거 분석 결과입니다 (읽기 전용 모드)")` 배지 표시
- **사이드바 탐지 설정 비활성화**: 읽기 전용 모드에서는 사이드바의 "탐지 설정" Expander를 숨기거나, "설정을 변경하려면 원본 파일을 다시 업로드해주세요" 안내 표시

검증: `init_state()` 호출 후 `st.session_state[KEY_LOADED_FROM_DB]`가 `False`인지 확인. DB 로드 시 상단 info 배지가 표시되고, 탐지 설정 Expander가 비활성화되는지 확인.

## Risk Assessment

- **Medium Risk**: `load_all()` 시그니처 변경 시 기존 호출부(파이프라인, 테스트) 파급
  - Mitigation: `file_name` 파라미터에 기본값 `""` 설정하여 하위 호환 유지
- **Medium Risk → Mitigated**: PipelineResult 복원 시 DetectionResult 리스트 부재 → anomaly_flags에서 Pseudo DetectionResult를 역산하여 재구성 (리뷰 피드백 #1)
  - Mitigation: `_reconstruct_detection_results()`로 룰별 위반 건수/점수를 복원. 대시보드 차트 정상 작동 보장
- **Low Risk**: 기존 DB에 `upload_batches` 테이블이 없어 기존 배치를 조회할 수 없음
  - Mitigation: `CREATE TABLE IF NOT EXISTS`로 멱등 생성. 기존 배치는 목록에 나타나지 않지만, 새 업로드부터 메타가 기록됨

## Success Metrics

- Streamlit 재시작 후 이전 분석 결과를 3클릭 이내로 복원 가능
- DB 로드된 PipelineResult로 개요/이상항목/Benford/데이터품질 4개 탭 모두 정상 렌더링
- 신규 파이프라인 실행 시 upload_batches에 메타데이터 자동 기록

## Dependencies

- Code: Phase 1(스키마+적재) → Phase 2(리더) → Phase 3(대시보드)
- External: 없음 (DuckDB 내 완결)
