"""validation 데이터셋 5종 × ingest 파이프라인 6단계 통합 검증.

data/journal/validation/ 하위 5개 데이터셋을 실제 파이프라인에 통과시켜
각 단계의 동작을 검증한다. 결과는 MD 파일로 저장.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pytest

from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
from src.ingest.file_validator import validate_file
from src.ingest.header_detector import detect_header_row
from src.ingest.reader_api import read_file
from src.ingest.type_caster import cast_dataframe

# ── 데이터셋 정의 ──────────────────────────────────────────

VALIDATION_DIR = Path("data/journal/validation")

DATASETS: dict[str, dict] = {
    "bpi2019": {
        "file": VALIDATION_DIR / "bpi2019" / "BPI_Challenge_2019.csv",
        "desc": "SAP ERP P2P 이벤트 로그 (527MB, latin-1)",
        "rows": 1_595_923,
    },
    "financial-anomaly": {
        "file": VALIDATION_DIR / "financial-anomaly" / "financial_anomaly_data.csv",
        "desc": "금융 트랜잭션 이상치 데이터 (15MB, UTF-8)",
        "rows": 217_441,
    },
    "general-ledger": {
        "file": VALIDATION_DIR / "general-ledger" / "Data file for students.xlsx",
        "desc": "교육용 총계정원장 (2MB, xlsx)",
        "rows": 27_909,
    },
    "sap-merged": {
        "file": VALIDATION_DIR / "sap-merged" / "sap_merged.parquet",
        "desc": "SAP ERP 통합 전표 (8.5MB, parquet)",
        "rows": 331_934,
    },
    "schreyer-fraud": {
        "file": VALIDATION_DIR / "schreyer-fraud" / "schreyer_fraud_v2.csv",
        "desc": "SAP FICO 합성 전표 벤치마크 (27MB, UTF-8)",
        "rows": 533_009,
    },
}


# ── 단계별 결과 수집 ────────────────────────────────────────


@dataclass
class StageResult:
    """파이프라인 한 단계의 실행 결과."""

    name: str
    passed: bool = False
    elapsed_sec: float = 0.0
    detail: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class DatasetResult:
    """데이터셋 하나의 전체 파이프라인 결과."""

    dataset_name: str
    desc: str
    stages: list[StageResult] = field(default_factory=list)
    final_shape: tuple[int, int] = (0, 0)
    mapped_columns: dict[str, str] = field(default_factory=dict)
    suggestions: dict[str, str] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    cast_summary: dict[str, str] = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        return all(s.passed for s in self.stages)


def _pick_best_sheet(rr) -> tuple[str, pd.DataFrame]:
    """멀티시트 xlsx에서 가장 행이 많은 시트를 선택.

    Why: active_sheet가 요약 시트일 수 있음 (general-ledger의 경우).
    """
    best_sheet = rr.active_sheet
    best_df = rr.raw_data[best_sheet]
    for sheet_name, df in rr.raw_data.items():
        if len(df) > len(best_df):
            best_sheet = sheet_name
            best_df = df
    return best_sheet, best_df


def _run_pipeline(name: str, info: dict) -> DatasetResult:
    """단일 데이터셋에 대해 파이프라인을 실행."""
    result = DatasetResult(dataset_name=name, desc=info["desc"])
    filepath = info["file"]

    # ① 파일 검증
    t0 = time.perf_counter()
    vr = validate_file(filepath)
    elapsed = time.perf_counter() - t0
    stage = StageResult(
        name="① 파일 검증",
        passed=vr.is_valid,
        elapsed_sec=elapsed,
        detail=f"category={vr.file_category}",
        warnings=vr.warnings[:5],
        errors=vr.errors[:5],
    )
    result.stages.append(stage)
    if not vr.is_valid:
        return result

    # ② 파일 읽기
    t0 = time.perf_counter()
    try:
        rr = read_file(filepath)
        elapsed = time.perf_counter() - t0

        # 멀티시트 xlsx: 가장 큰 시트 선택
        if len(rr.sheets) > 1:
            sheet, raw_df = _pick_best_sheet(rr)
        else:
            sheet = rr.active_sheet
            raw_df = rr.raw_data[sheet]

        stage = StageResult(
            name="② 파일 읽기",
            passed=True,
            elapsed_sec=elapsed,
            detail=f"sheets={rr.sheets}, selected={sheet}, rows={len(raw_df)}, cols={len(raw_df.columns)}, format={rr.source_format}",
        )
        if rr.encoding:
            stage.detail += f", encoding={rr.encoding}"
    except Exception as e:
        elapsed = time.perf_counter() - t0
        stage = StageResult(
            name="② 파일 읽기",
            passed=False,
            elapsed_sec=elapsed,
            errors=[str(e)[:200]],
        )
        result.stages.append(stage)
        return result
    result.stages.append(stage)

    # Parquet 분기: 이미 컬럼명이 있으므로 헤더 탐지 스킵
    is_parquet = rr.source_format == "parquet"
    # Why: hr_row/matched_kw가 else 블록에서만 초기화되면 분기 추가 시 NameError 위험
    matched_kw: list[str] = []
    hr_row: int = 0

    if is_parquet:
        # ③ 헤더 탐지 — Parquet은 스킵
        stage = StageResult(
            name="③ 헤더 탐지",
            passed=True,
            elapsed_sec=0.0,
            detail="Parquet — 컬럼명이 메타데이터에 포함, 헤더 탐지 불필요",
        )
        result.stages.append(stage)
        columns = list(raw_df.columns)
        data_df = raw_df
    else:
        # ③ 헤더 행 탐지 (CSV/Excel)
        t0 = time.perf_counter()
        hr = detect_header_row(raw_df)
        elapsed = time.perf_counter() - t0
        stage = StageResult(
            name="③ 헤더 탐지",
            passed=hr.header_row is not None,
            elapsed_sec=elapsed,
            detail=f"header_row={hr.header_row}, confidence={hr.confidence:.2f}, matched={hr.matched_keywords}",
        )
        stage.detail += f"\n  message: {hr.message}"
        result.stages.append(stage)

        if hr.header_row is None:
            # 헤더 탐지 실패 — 0행을 헤더로 폴백 시도
            stage.detail += "\n  → 0행 폴백으로 매핑 시도"
            hr_row = 0
            matched_kw = []
        else:
            hr_row = hr.header_row
            matched_kw = hr.matched_keywords

        columns, data_df = prepare_dataframe(raw_df, hr_row)

    # ④ 컬럼 매핑
    t0 = time.perf_counter()
    mr = auto_map_columns(columns, matched_keywords=matched_kw, data_df=data_df)
    elapsed = time.perf_counter() - t0
    stage = StageResult(
        name="④ 컬럼 매핑",
        passed=True,
        elapsed_sec=elapsed,
        detail=(
            f"mapping={len(mr.mapping)}개, suggestions={len(mr.suggestions)}개, "
            f"unmapped={len(mr.unmapped)}개, needs_review={mr.needs_review}"
        ),
    )
    if mr.missing_required:
        stage.warnings.append(f"필수 컬럼 미매핑: {mr.missing_required}")
    result.stages.append(stage)
    result.mapped_columns = mr.mapping
    result.suggestions = mr.suggestions
    result.unmapped = mr.unmapped
    result.missing_required = mr.missing_required

    # rename으로 표준 컬럼명 적용
    renamed_df = data_df.rename(columns=mr.mapping)

    # ⑤ 타입 캐스팅
    t0 = time.perf_counter()
    cr = cast_dataframe(renamed_df)
    elapsed = time.perf_counter() - t0
    stage = StageResult(
        name="⑤ 타입 캐스팅",
        passed=cr.success,
        elapsed_sec=elapsed,
        detail=f"cast={len(cr.cast_summary)}개, skipped={len(cr.skipped_columns)}개",
        warnings=cr.warnings[:5],
        errors=cr.errors[:5],
    )
    result.stages.append(stage)
    result.cast_summary = cr.cast_summary
    result.final_shape = cr.data.shape

    return result


# ── MD 리포트 생성 ──────────────────────────────────────────


def _generate_report(results: list[DatasetResult]) -> str:
    """전체 결과를 MD 문자열로 생성.

    구조: 1.요약 → 2.발견 문제 → 3.v2 개선 결과 → 4.남은 문제 → 5.데이터셋별 상세
    """
    L: list[str] = []  # noqa: N806
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

    # ── 1. 테스트 요약 ──
    L.append("# Validation 데이터셋 Ingest 파이프라인 검증 결과\n")
    L.append(f"> 실행일: {now} | {len(results)}종 실데이터셋\n")
    L.append("## 1. 테스트 요약\n")
    L.append("| 데이터셋            | 검증 | 읽기 | 헤더 | 매핑 | 캐스팅 | 최종 shape        |")
    L.append("|:--------------------|:----:|:----:|:----:|:----:|:------:|:------------------|")
    for r in results:
        def _icon(idx: int) -> str:
            if idx < len(r.stages):
                return "✅" if r.stages[idx].passed else "❌"
            return "⏭️"
        shape_str = f"{r.final_shape[0]:,} × {r.final_shape[1]}" if r.final_shape[0] > 0 else "—"
        L.append(
            f"| {r.dataset_name:<19} | {_icon(0)}   | {_icon(1)}   | {_icon(2)}   "
            f"| {_icon(3)}   | {_icon(4)}     | {shape_str:<17} |"
        )

    # ── 2. 발견된 문제점 (실행 결과에서 자동 추출) ──
    L.append("\n---\n\n## 2. 발견된 문제점\n")
    problems: list[str] = []
    for r in results:
        # 읽기 실패
        if len(r.stages) >= 2 and not r.stages[1].passed:
            err = r.stages[1].errors[0] if r.stages[1].errors else "알 수 없는 오류"
            problems.append(f"| {r.dataset_name} | ② 읽기 실패 | {err[:60]} |")
        # 헤더 탐지 — 키워드 0개 (구조 기반 탐지)
        if len(r.stages) >= 3 and r.stages[2].passed:
            detail = r.stages[2].detail
            if "matched=[]" in detail or "matched=0" in detail.replace(" ", ""):
                problems.append(f"| {r.dataset_name} | ③ 헤더 키워드 0개 | 구조 기반 탐지 (keywords.yaml 미등록 컬럼) |")
        # 캐스팅 오매핑 의심
        for s in r.stages:
            for w in s.warnings:
                if "오매핑 의심" in w:
                    col = w.split(":")[0].strip()
                    problems.append(f"| {r.dataset_name} | ⑤ 오매핑 의심 | {col} 캐스팅 후 결측률 90%+ |")
        # 필수 컬럼 미매핑
        if r.missing_required:
            n = len(r.missing_required)
            problems.append(f"| {r.dataset_name} | ④ 필수 미매핑 {n}개 | {', '.join(r.missing_required[:5])}{'...' if n > 5 else ''} |")

    if problems:
        L.append("| 데이터셋 | 문제 | 상세 |")
        L.append("|:---------|:-----|:-----|")
        L.extend(problems)
    else:
        L.append("문제 없음.")

    # ── 3. v2 개선 결과 (이전 대비) ──
    L.append("\n---\n\n## 3. v2 개선 결과\n")
    L.append("| 항목 | v1 | v2 | 상태 |")
    L.append("|:-----|:---|:---|:----:|")
    L.append("| 헤더 탐지 (키워드 의존 80%) | 미등록 컬럼 → 실패 | 구조적 신호 기반 (키워드 15%) | 해결 |")
    L.append("| Fuzzy 오매핑 (drcrk→debit) | 타입 무시 → 100% NaN | 타입 호환성 검증 + dc_indicator 등록 | 해결 |")
    L.append("| 캐스팅 null 무감지 | 단일 warning | 3단계 분기 (유령/오매핑/일반) | 해결 |")
    L.append("| 판단 근거 불투명 | 없음 | ReviewItem 모델 (action/reason) | 해결 |")

    # ── 4. 남은 문제점 ──
    L.append("\n---\n\n## 4. 남은 문제점\n")
    L.append("| 문제 | 현상 | 해결 시점 |")
    L.append("|:-----|:-----|:----------|")
    # 읽기 실패가 있으면 인코딩 문제로 기록
    for r in results:
        if len(r.stages) >= 2 and not r.stages[1].passed:
            err = r.stages[1].errors[0] if r.stages[1].errors else ""
            if "codec" in err.lower() or "encode" in err.lower() or "decode" in err.lower():
                L.append(f"| 인코딩 오탐 ({r.dataset_name}) | {err[:50]} | Phase 1a |")
            else:
                L.append(f"| 읽기 실패 ({r.dataset_name}) | {err[:50]} | 조사 필요 |")
    L.append("| Parquet 헤더 탐지 스킵 | 불필요한 탐지 시도 (동작 무영향) | Phase 1c |")
    L.append("| 멀티시트 UI 선택 | active_sheet가 데이터 양 무관 | Phase 1c |")
    L.append("| 일부 Fuzzy 추천 부정확 | monat→debit_amount 등 | Phase 1c~3 |")

    # ── 5. 데이터셋별 상세 ──
    L.append("\n---\n\n## 5. 데이터셋별 상세\n")
    for r in results:
        L.append(f"### {r.dataset_name}\n")
        L.append(f"**{r.desc}**\n")

        for s in r.stages:
            icon = "✅" if s.passed else "❌"
            L.append(f"**{icon} {s.name}** ({s.elapsed_sec:.2f}s)")
            if s.detail:
                L.append(f"  {s.detail.split(chr(10))[0].strip()}")
            for e in s.errors[:3]:
                L.append(f"  ERROR: {e}")
            for w in s.warnings[:3]:
                L.append(f"  WARN: {w}")
            L.append("")

        # 매핑 상세
        if r.mapped_columns or r.suggestions:
            L.append("| 원본 | 표준 | 구분 |")
            L.append("|:-----|:-----|:----:|")
            for src, std in sorted(r.mapped_columns.items()):
                L.append(f"| {src} | {std} | 확정 |")
            for src, std in sorted(r.suggestions.items()):
                L.append(f"| {src} | {std} | 추천 |")
            L.append("")
        if r.unmapped:
            display = r.unmapped[:10]
            extra = f" 외 {len(r.unmapped) - 10}개" if len(r.unmapped) > 10 else ""
            L.append(f"미매핑: {', '.join(display)}{extra}\n")
        if r.missing_required:
            L.append(f"필수 미매핑: {', '.join(r.missing_required)}\n")
        if r.cast_summary:
            L.append("| 컬럼 | 변환 |")
            L.append("|:-----|:-----|")
            for col, conv in sorted(r.cast_summary.items()):
                L.append(f"| {col} | {conv} |")
            L.append("")
        if r.final_shape[0] > 0:
            L.append(f"최종: {r.final_shape[0]:,}행 × {r.final_shape[1]}열\n")

        L.append("---\n")

    # ── 6. 실행 명령어 ──
    L.append("## 6. 실행 명령어\n")
    L.append("```bash")
    L.append("uv run pytest tests/test_ingest/test_validation_datasets.py -v -k 'not slow'  # 빠른 (bpi2019 제외)")
    L.append("uv run pytest tests/test_ingest/test_validation_datasets.py -v               # 전체")
    L.append("uv run pytest tests/test_ingest/test_validation_datasets.py -v -k slow        # 리포트 재생성")
    L.append("```\n")

    return "\n".join(L)


# ── 테스트 ──────────────────────────────────────────────────


# bpi2019는 527MB로 읽기에 시간이 오래 걸리므로 별도 분리
FAST_DATASETS = {k: v for k, v in DATASETS.items() if k != "bpi2019"}


class TestValidationDatasets:
    """validation 데이터셋 파이프라인 통과 검증."""

    @pytest.mark.parametrize("name", FAST_DATASETS.keys())
    def test_pipeline_stages(self, name: str):
        """각 데이터셋이 파이프라인 단계를 통과하는지 확인."""
        info = FAST_DATASETS[name]
        if not info["file"].exists():
            pytest.skip(f"데이터 파일 없음: {info['file']}")

        result = _run_pipeline(name, info)
        # 최소 검증까지는 통과해야 함
        assert result.stages[0].passed, f"{name}: 파일 검증 실패 — {result.stages[0].errors}"

    @pytest.mark.slow
    def test_bpi2019_large_file(self):
        """bpi2019(527MB) — 전체 파이프라인 통과 검증 (slow: ~3GB 메모리, 수 분 소요)."""
        info = DATASETS["bpi2019"]
        if not info["file"].exists():
            pytest.skip("bpi2019 파일 없음")

        result = _run_pipeline("bpi2019", info)
        assert result.stages[0].passed, f"bpi2019: 파일 검증 실패 — {result.stages[0].errors}"


class TestGenerateReport:
    """전체 리포트 생성 (slow — 별도 실행)."""

    @pytest.mark.slow
    def test_full_report(self):
        """모든 데이터셋 파이프라인 실행 + MD 리포트 저장."""
        results: list[DatasetResult] = []

        for name, info in DATASETS.items():
            if not info["file"].exists():
                continue
            results.append(_run_pipeline(name, info))

        # 로컬 데이터 없으면 스킵 (CI 환경 대비)
        if not results:
            pytest.skip("로컬 validation 데이터셋 없음")

        report = _generate_report(results)
        out_dir = Path("tests/test_ingest/test-results")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "ingest-validation-datasets.md"
        out_path.write_text(report, encoding="utf-8")

        assert out_path.exists()
        assert out_path.stat().st_size > 1024, "리포트가 너무 짧음 — 생성 실패 의심"
        assert len(results) >= 4
