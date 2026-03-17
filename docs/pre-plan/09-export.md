# 09. 감사조서 내보내기 (Export)

## 목적
분석 결과를 Excel/PDF 감사조서로 내보내고,
모든 분석 활동을 Audit Trail로 기록하여 감사 증적을 확보한다.

## 관련 파일
```
src/export/
├── excel_exporter.py    # Excel 감사조서 생성
├── pdf_exporter.py      # PDF 감사조서 생성
└── audit_trail.py       # 감사 활동 로그
```

## 핵심 클래스/함수

### `excel_exporter.py` — Excel 감사조서
```python
class ExcelExporter:
    """openpyxl로 감사조서 Excel 생성.

    워크시트 구성:
    1. Summary: 분석 요약 (KPI, 위험 분포)
    2. Anomalies: 이상 전표 목록 (위험도 색상 서식)
    3. Benford: Benford 분석 결과
    4. Rules: 룰별 위반 통계
    5. Raw Data: 전체 데이터 (피처 포함)
    """

    def export(
        self,
        pipeline_result: PipelineResult,
        output_path: Path,
        filters: dict | None = None    # 대시보드 필터 적용
    ) -> Path:
        """감사조서 Excel 파일 생성.

        - 위험도별 행 색상 (High=빨강, Medium=노랑, Low=초록)
        - 자동 열 너비 조정
        - 헤더 고정 (freeze_panes)
        - 요약 시트에 차트 삽입
        """
```

### `pdf_exporter.py` — PDF 감사조서
```python
class PDFExporter:
    """fpdf2로 감사조서 PDF 생성.

    페이지 구성:
    1. 표지: 프로젝트명, 분석 일시, 분석 대상
    2. 분석 요약: KPI, 위험 분포 차트 (이미지)
    3. Benford 분석: 분포 차트 + 판정 결과
    4. 이상 전표 상위 N건: 테이블
    5. 룰별 위반 통계: 테이블
    6. 감사 의견/인사이트: LLM 생성 텍스트 (있을 경우)
    """

    def export(
        self,
        pipeline_result: PipelineResult,
        output_path: Path,
        top_n: int = 50,
        include_insights: bool = False   # Phase 3 LLM 인사이트
    ) -> Path:
        """감사조서 PDF 파일 생성.

        - 한글 폰트 지원 (NanumGothic 등)
        - Plotly 차트 → 이미지 → PDF 삽입
        - 테이블 자동 페이지 분할
        """
```

### `audit_trail.py` — 감사 활동 로그
```python
@dataclass
class AuditEvent:
    timestamp: datetime
    event_type: str       # 'upload' | 'analysis' | 'query' | 'export' | 'filter'
    user_action: str      # 사용자 행동 설명
    details: dict         # 이벤트별 상세 정보
    batch_id: str         # 업로드 배치 ID

class AuditTrail:
    """감사 활동 추적 로거.

    모든 분석 활동을 기록하여 감사 증적 확보:
    - 파일 업로드 시점/파일명
    - 분석 실행 시점/결과 요약
    - 사용자 쿼리 내용/결과
    - 필터 조건 변경
    - 내보내기 시점/범위
    """

    def log(self, event: AuditEvent) -> None:
        """이벤트를 DuckDB audit_trail 테이블에 기록."""

    def export_trail(self, batch_id: str, output_path: Path) -> Path:
        """특정 배치의 전체 감사 활동 로그를 CSV로 내보내기."""

    def get_trail(self, batch_id: str) -> DataFrame:
        """특정 배치의 감사 활동 로그 조회."""
```

## 데이터 흐름
```
[PipelineResult + DuckDB 데이터]
       ↓
  ┌────────────────────────┐
  │ excel_exporter.export()│ → 감사조서.xlsx
  │ pdf_exporter.export()  │ → 감사조서.pdf
  │ audit_trail.export()   │ → audit_trail.csv
  └────────────────────────┘
       ↓
[Tab 5: Export에서 다운로드 제공]

--- 별도 흐름 ---
[사용자 모든 활동]
       ↓
audit_trail.log(event)
       ↓
[DuckDB audit_trail 테이블]
```

## 구현 순서
1. `audit_trail.py` — 이벤트 로깅 (다른 모듈에서 호출)
2. `excel_exporter.py` — Excel 감사조서 생성
3. `pdf_exporter.py` — PDF 감사조서 생성

## 의존성
- **선행:** `06-db` (DuckDB 데이터), `07-dashboard` (Plotly 차트 이미지 변환), `08-llm` (인사이트 텍스트)
- **외부 패키지:** `openpyxl` (Excel), `fpdf2` (PDF)
- **후행:** `07-dashboard/tab_export.py`에서 호출

## 테스트 전략
- **excel_exporter:** 샘플 데이터 → Excel 생성 → openpyxl로 재로드 → 시트/행 수 확인
- **pdf_exporter:** 샘플 데이터 → PDF 생성 → 파일 존재 + 페이지 수 확인
- **audit_trail:** 이벤트 로그 → DuckDB 조회 → 기록 일치 확인
- **한글:** Excel/PDF에 한글 데이터 정상 출력 확인

## Phase 구분
| 항목                   | Phase   |
|------------------------|---------|
| audit_trail (기본 로깅) | Phase 3 |
| excel_exporter          | Phase 3 |
| pdf_exporter            | Phase 3 |
| LLM 인사이트 포함 PDF  | Phase 3 |

## 구현 시 주의사항
- **한글 폰트:** fpdf2에서 한글 출력 시 `add_font()`로 TTF 폰트 등록 필수 (NanumGothic 추천)
- **차트 이미지 변환:** Plotly → `fig.to_image()` (kaleido 패키지 필요할 수 있음)
- **파일 크기:** 대용량 데이터(10만건+)는 Excel 시트 행 제한(104만행) 고려
- **audit_trail 테이블:** `06-db/schema.py`에 DDL 추가 필요
- **개인정보:** 내보내기 시 민감 정보(작성자 등) 마스킹 옵션 제공
- **타임존:** 모든 timestamp는 KST(Asia/Seoul) 기준
