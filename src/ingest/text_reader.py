"""텍스트 리더 — CSV/TSV/TXT/DAT 파일을 ReadResult로 변환.

DataSynth CSV(319MB)가 메인 데이터이므로 이 경로가 가장 빈번하게 사용된다.
인코딩 자동 감지(charset_normalizer) + 구분자 자동 감지(csv.Sniffer)를 수행하고,
모든 컬럼을 dtype=str로 읽어 type_caster에 타입 변환을 위임한다.
"""

from __future__ import annotations

import codecs
import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src.ingest.models import ReadResult

logger = logging.getLogger(__name__)

_DEFAULT_SHEET = "Sheet1"

# 인코딩 감지용 샘플 크기 (한글이 후반부에 집중될 수 있으므로 64KB)
_ENCODING_SAMPLE_BYTES = 64 * 1024

# 구분자 감지용 샘플 크기
_SNIFFER_SAMPLE_BYTES = 8 * 1024

# prescan 전용 샘플 크기 (메타데이터 행이 길어도 데이터 행에 도달해야 함)
_PRESCAN_SAMPLE_BYTES = 64 * 1024

# 청크 읽기 임계값 — 이 크기 이상일 때 청크 단위로 읽어 진행률 보고
_CHUNK_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10MB
_CHUNK_SIZE_ROWS = 50_000

# 확장자 기반 구분자 폴백
_FALLBACK_SEPARATORS: dict[str, str] = {
    ".csv": ",",
    ".tsv": "\t",
    ".txt": ",",
    ".dat": ",",
}


def _detect_encoding(path: Path) -> tuple[str, float | None]:
    """charset_normalizer로 파일 인코딩을 감지한다.

    Returns:
        (encoding, confidence) — confidence는 1.0 - chaos (0.0~1.0).
        감지 실패 시 ("utf-8", None).

    Why: confidence를 ReadResult에 노출하여 UI에서 낮은 신뢰도(<0.7) 시
    수동 인코딩 선택을 유도한다.
    """
    import charset_normalizer

    raw = path.read_bytes()[:_ENCODING_SAMPLE_BYTES]

    # Why: Korean-heavy UTF-8 CSVs can be misclassified as legacy Cyrillic
    # encodings (for example ptcp154), which silently corrupts Hangul text.
    # A strict UTF-8 decode is deterministic, so prefer it when it succeeds.
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", 1.0
    try:
        codecs.getincrementaldecoder("utf-8")().decode(raw, final=False)
    except UnicodeDecodeError:
        pass
    else:
        return "utf-8", 1.0

    detection = charset_normalizer.from_bytes(raw).best()

    if detection is None:
        logger.warning(
            "인코딩 감지 실패, utf-8로 폴백합니다: %s",
            path.name,
        )
        return "utf-8", None

    detected = detection.encoding
    # chaos: 0.0(완벽) ~ 1.0(혼돈) → confidence = 1.0 - chaos
    confidence = max(0.0, 1.0 - detection.chaos)

    # ascii → latin-1 폴백: ascii는 latin-1의 진부분집합(0x00~0x7F)이므로
    # 샘플에 0x80+ 바이트가 없으면 ascii로 오탐할 수 있다.
    # latin-1은 0x00~0xFF 전체 매핑이라 어떤 바이트든 에러 없이 읽힘.
    if detected == "ascii":
        return "latin-1", confidence

    return detected, confidence


def _count_cols_csv(text_lines: list[str], sep: str) -> int:
    """csv.reader 기반 최대 컬럼 수 — 따옴표 내 구분자를 무시한다."""
    max_count = 1
    for line in text_lines:
        try:
            row = next(csv.reader(io.StringIO(line), delimiter=sep))
            max_count = max(max_count, len(row))
        except (StopIteration, csv.Error):
            pass
    return max_count


def _detect_separator(path: Path, encoding: str) -> str:
    """csv.Sniffer로 실제 구분자를 감지한다.

    감지 실패 시 확장자 기반 폴백을 사용한다.

    Why: (1) 메타데이터 행(제목, 작성일 등)이 파일 앞부분에 있으면
    Sniffer가 줄바꿈(\\r)이나 비데이터 문자를 구분자로 오판한다.
    (2) 감지된 구분자와 확장자 폴백을 비교하여 더 많은 컬럼을
    생성하는 쪽을 선택한다.
    """
    ext = path.suffix.lower()
    fallback = _FALLBACK_SEPARATORS.get(ext, ",")

    try:
        raw = path.read_bytes()[:_SNIFFER_SAMPLE_BYTES]
        text = raw.decode(encoding, errors="replace")
        dialect = csv.Sniffer().sniff(text)
        detected = dialect.delimiter

        # 줄바꿈 문자는 구분자가 될 수 없음
        if detected in ("\r", "\n"):
            logger.info(
                "Sniffer가 줄바꿈 '%s'를 구분자로 감지 — 확장자 폴백 '%s' 사용: %s",
                repr(detected),
                fallback,
                path.name,
            )
            return fallback

        # 폴백과 다른 구분자를 감지했으면, 둘을 비교하여 더 나은 쪽 선택
        if detected != fallback:
            lines = text.strip().splitlines()[:20]
            non_empty = [ln.rstrip("\r") for ln in lines if ln.strip()]

            det_max = _count_cols_csv(non_empty, detected)
            fb_max = _count_cols_csv(non_empty, fallback)

            if fb_max > det_max:
                logger.info(
                    "Sniffer '%s'(최대 %d컬럼) < 폴백 '%s'(최대 %d컬럼) — 폴백 사용: %s",
                    repr(detected),
                    det_max,
                    fallback,
                    fb_max,
                    path.name,
                )
                return fallback

        return detected
    except csv.Error:
        return fallback


def _prescan_max_columns(path: Path, encoding: str, separator: str) -> int:
    """파일의 처음 50줄에서 최대 컬럼 수를 파악한다.

    Why: 메타데이터 행(제목 등)이 1컬럼이고 데이터 행이 11컬럼이면
    pd.read_csv(header=None)가 1컬럼 기준으로 나머지를 skip한다.
    최대 컬럼 수를 names 파라미터로 전달하면 모든 행이 파싱된다.
    """
    try:
        raw = path.read_bytes()[:_PRESCAN_SAMPLE_BYTES]
        text = raw.decode(encoding, errors="replace")
        lines = text.splitlines()[:50]
        non_empty = [ln.rstrip("\r") for ln in lines if ln.strip()]
        return _count_cols_csv(non_empty, separator)
    except Exception as exc:
        logger.warning(
            "prescan 실패, names 파라미터 없이 진행: %s (%s)",
            path.name,
            exc,
        )
        return 0


# ── 인크리멘탈 진단 (청크 단위) ─────────────────────────


@dataclass
class _DiagAccumulator:
    """청크 단위 인크리멘탈 진단 누적 상태.

    Why: 1.1M행 전체 df.isna()는 33초 소요 (object dtype 22M셀).
    50K행 청크 단위로 isna를 수행하면 0.3초/청크로,
    읽기 루프에 흡수되어 별도 전체 스캔이 불필요해진다.
    """

    empty_row_count: int = 0
    # 컬럼별 "값이 한 번이라도 존재" 플래그 — False인 컬럼이 빈 열
    col_has_value: np.ndarray | None = None
    # {non_null_count: 행 수} 히스토그램 — 열 수 불일치 판정용
    non_null_histogram: dict[int, int] = field(default_factory=dict)
    mixed_delim_count: int = 0
    total_rows: int = 0
    separator: str = ","
    n_cols: int = 0


def _accumulate_diagnostics(
    chunk: pd.DataFrame,
    accum: _DiagAccumulator,
) -> None:
    """청크 1개의 진단 결과를 누적기에 반영한다.

    50K행 × 20열 기준 ~0.3초. 읽기 루프에서 매 청크마다 호출.
    """
    is_na = chunk.isna()

    # 1) 빈 행: 모든 컬럼이 NaN인 행 수
    accum.empty_row_count += int(is_na.all(axis=1).sum())

    # 2) 빈 열: 컬럼별 "값 존재" OR 누적
    chunk_has_value = chunk.notna().any(axis=0).values
    if accum.col_has_value is None:
        accum.col_has_value = chunk_has_value
    else:
        accum.col_has_value |= chunk_has_value

    # 3) 열 수 불일치: 행별 non-null 카운트 히스토그램 누적
    non_null_counts = (~is_na).sum(axis=1)
    for cnt, freq in non_null_counts.value_counts().items():
        accum.non_null_histogram[int(cnt)] = accum.non_null_histogram.get(int(cnt), 0) + int(freq)

    # 4) 혼합 구분자: "첫 열만 값" 패턴 후보 검사
    if chunk.shape[1] >= 2:
        first_not_na = ~is_na.iloc[:, 0]
        rest_all_na = is_na.iloc[:, 1:].all(axis=1)
        candidates = chunk[first_not_na & rest_all_na]
        if len(candidates) > 0:
            alts = [d for d in _ALT_DELIMITERS if d != accum.separator]
            min_parts = chunk.shape[1] * 0.5
            for _, row in candidates.iterrows():
                cell = str(row.iloc[0])
                for alt in alts:
                    parts = list(csv.reader(io.StringIO(cell), delimiter=alt))[0]
                    if len(parts) >= min_parts:
                        accum.mixed_delim_count += 1
                        break

    accum.total_rows += len(chunk)


def _finalize_diagnostics(
    accum: _DiagAccumulator,
    path: Path,
    csv_kwargs: dict,
) -> list[str]:
    """누적된 진단 결과를 경고 문자열 리스트로 변환한다."""
    warnings: list[str] = []

    # 1) 빈 행
    if accum.empty_row_count > 0:
        warnings.append(f"빈 행 {accum.empty_row_count}개 감지")

    # 2) 빈 열: 한 번도 값이 나타나지 않은 컬럼
    if accum.col_has_value is not None:
        empty_cols = int((~accum.col_has_value).sum())
        if empty_cols > 0:
            warnings.append(f"빈 열 {empty_cols}개 감지")

    # 3) 열 수 불일치: 히스토그램에서 mode 산출
    hist = accum.non_null_histogram
    # 빈 행(count=0) 제외
    hist_no_zero = {k: v for k, v in hist.items() if k > 0}
    if len(hist_no_zero) > 1:
        mode_cols = max(hist_no_zero, key=hist_no_zero.get)
        mismatch_rows = sum(v for k, v in hist_no_zero.items() if k != mode_cols)
        if mismatch_rows > 0:
            warnings.append(
                f"열 수 불일치 (기준 {mode_cols}열) — "
                f"{mismatch_rows}행이 기준과 다름, 원본 파일 확인 필요"
            )

    # 4) 혼합 구분자
    if accum.mixed_delim_count > 0:
        warnings.append(
            f"혼합 구분자 {accum.mixed_delim_count}행 감지 "
            f"(주 구분자 '{accum.separator}' 외 다른 구분자 사용)",
        )

    # 5) 미닫힌 따옴표 (바이트 기반, 즉시)
    _check_unclosed_quotes(warnings, path, csv_kwargs, accum.total_rows)

    return warnings


# ── 소형 파일용 전체 스캔 진단 ────────────────────────


def _diagnose_issues(
    df: pd.DataFrame,
    path: Path,
    separator: str,
    csv_kwargs: dict,
) -> list[str]:
    """소형 파일(10만행 미만) 전용 전체 스캔 진단.

    대용량 파일은 _accumulate_diagnostics + _finalize_diagnostics를
    청크 읽기 루프에서 사용하므로 이 함수를 호출하지 않는다.
    """
    warnings: list[str] = []
    is_na = df.isna()

    # 1) 빈 행
    row_all_na = is_na.all(axis=1)
    empty_rows = int(row_all_na.sum())
    if empty_rows > 0:
        warnings.append(f"빈 행 {empty_rows}개 감지")

    # 2) 빈 열
    empty_cols = int(is_na.all(axis=0).sum())
    if empty_cols > 0:
        warnings.append(f"빈 열 {empty_cols}개 감지")

    # 3) 열 수 불일치
    if df.shape[0] > 1:
        non_null_counts = (~is_na).sum(axis=1)
        non_empty = non_null_counts[~row_all_na]
        if len(non_empty) > 1:
            mode_cols = int(non_empty.mode().iloc[0])
            short_mask = non_empty < mode_cols
            long_mask = non_empty > mode_cols
            if short_mask.any() or long_mask.any():
                lines = [f"열 수 불일치 (기준 {mode_cols}열) — 원본 파일 확인 필요"]
                problem_idxs = non_null_counts.index[short_mask | long_mask]
                for row_idx in problem_idxs:
                    cnt = int(non_null_counts.loc[row_idx])
                    row_id = df.iloc[row_idx, 0]
                    if cnt < mode_cols:
                        missing = mode_cols - cnt
                        lines.append(
                            f"  행 {row_idx + 1} ({row_id}): {cnt}열만 존재 → {missing}열 누락(NaN)"
                        )
                    elif cnt > mode_cols:
                        extra_vals = [str(v) for v in df.iloc[row_idx, mode_cols:].dropna()]
                        lines.append(
                            f"  행 {row_idx + 1} ({row_id}): "
                            f"{cnt}열 → 초과 값 [{', '.join(extra_vals)}] 버려짐"
                        )
                warnings.append("\n".join(lines))

    # 4) 혼합 구분자
    if df.shape[1] >= 2:
        first_not_na = ~is_na.iloc[:, 0]
        rest_all_na = is_na.iloc[:, 1:].all(axis=1)
        candidate_mask = first_not_na & rest_all_na
        candidates = df[candidate_mask]
        mixed_count = 0
        alts = [d for d in _ALT_DELIMITERS if d != separator]
        min_parts = df.shape[1] * 0.5
        for _, row in candidates.iterrows():
            cell = str(row.iloc[0])
            for alt in alts:
                parts = list(csv.reader(io.StringIO(cell), delimiter=alt))[0]
                if len(parts) >= min_parts:
                    mixed_count += 1
                    break
        if mixed_count > 0:
            warnings.append(
                f"혼합 구분자 {mixed_count}행 감지 (주 구분자 '{separator}' 외 다른 구분자 사용)",
            )

    # 5) 미닫힌 따옴표
    _check_unclosed_quotes(warnings, path, csv_kwargs, len(df))

    return warnings


def _check_unclosed_quotes(
    warnings: list[str],
    path: Path,
    csv_kwargs: dict,
    total_rows: int,
) -> None:
    """미닫힌 따옴표를 파일 앞부분 바이트 기반으로 감지한다."""
    try:
        raw = path.read_bytes()[:_PRESCAN_SAMPLE_BYTES]
        text = raw.decode(csv_kwargs.get("encoding", "utf-8"), errors="replace")
        expected_lines = len([ln for ln in text.splitlines() if ln.strip()])
        if total_rows < expected_lines * 0.8:
            missing = expected_lines - 1 - total_rows
            warnings.append(
                f"미닫힌 따옴표로 {missing}행 누락 추정 "
                f"(파일 {expected_lines - 1}행 중 {total_rows}행만 파싱)",
            )
    except Exception:
        pass


def repair_dataframe(
    df: pd.DataFrame,
    read_result: ReadResult,
    path: Path | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """진단된 문제를 자동 복구한다. UI에서 사용자 확인 후 호출.

    Returns: (복구된 DataFrame, 복구 내역 메시지 리스트)
    """
    repairs: list[str] = []
    sep = ","
    if read_result.source_format in ("csv", "txt", "dat", "tsv"):
        ext = f".{read_result.source_format}"
        sep = _FALLBACK_SEPARATORS.get(ext, ",")

    # 1) 미닫힌 따옴표 복구 (빈 행 제거 전에 실행해야 행 수 비교가 정확)
    if path is not None and path.exists():
        encoding = read_result.encoding or "utf-8"
        csv_kwargs = {
            "sep": sep,
            "encoding": encoding,
            "header": None,
            "dtype": str,
            "on_bad_lines": "warn",
        }
        raw_repaired = _repair_unclosed_quotes(df, path, csv_kwargs)
        if len(raw_repaired) > len(df):
            from src.ingest.column_mapper import prepare_dataframe
            from src.ingest.header_detector import detect_header_row

            hdr = detect_header_row(raw_repaired)
            if hdr.header_row is not None:
                _, data_only = prepare_dataframe(raw_repaired, hdr.header_row)
                added = len(data_only) - len(df)
                if added > 0:
                    repairs.append(f"미닫힌 따옴표 복구 ({added}행 복원)")
                    df = data_only
            else:
                added = len(raw_repaired) - len(df)
                if added > 0:
                    repairs.append(f"미닫힌 따옴표 복구 ({added}행 복원)")
                    df = raw_repaired

    # 2) 혼합 구분자 복구 (줄바꿈 병합보다 먼저 실행)
    # Why: 혼합 구분자 행도 "1열만 값, 나머지 NaN" 형태이므로
    # 줄바꿈 병합이 먼저 실행되면 세미콜론/탭 행을 오인하여 병합한다.
    repaired_df = _repair_mixed_delimiters(df.copy(), sep)
    mixed_fixed = repaired_df.isna().sum().sum() < df.isna().sum().sum()
    if mixed_fixed:
        df = repaired_df
        repairs.append("혼합 구분자 행 복구")

    # 3) 깨진 줄바꿈 행 병합 (혼합 구분자 복구 후 남은 broken 행 대상)
    # Why: 이스케이프 없이 줄바꿈이 삽입된 적요 필드는 다음 줄이
    # 별도 행으로 파싱된다. 1열만 값이 있고 나머지 NaN인 행을
    # 이전 행의 마지막 텍스트 컬럼에 병합하여 복구한다.
    df, merged_count = _repair_broken_multiline(df)
    if merged_count > 0:
        repairs.append(f"깨진 줄바꿈 {merged_count}행 병합")

    # 4) 빈 행/열 제거 (마지막에 실행)
    before = df.shape
    df = _drop_empty_rows_cols(df)
    after = df.shape
    if before[0] != after[0]:
        repairs.append(f"빈 행 {before[0] - after[0]}개 제거")
    if before[1] != after[1]:
        repairs.append(f"빈 열 {before[1] - after[1]}개 제거")

    return df, repairs


def _repair_broken_multiline(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """1열만 값이 있고 나머지 NaN인 행을 이전 행에 병합한다.

    Why: CSV에서 따옴표 없이 줄바꿈이 삽입되면 다음 줄이 별도 행으로
    파싱된다. 이런 행은 1열에만 텍스트가 있고 나머지가 전부 NaN이므로
    식별 가능하다. 이전 행의 마지막 텍스트 컬럼에 개행 + 값을 붙인다.
    """
    if df.shape[1] < 2 or df.shape[0] < 2:
        return df, 0

    # 1열만 값이 있고 나머지 전부 NaN인 행 식별
    broken_mask = df.iloc[:, 0].notna() & df.iloc[:, 1:].isna().all(axis=1)
    if not broken_mask.any():
        return df, 0

    df = df.copy()
    rows_to_drop: list[int] = []

    for idx in df.index[broken_mask]:
        if idx == 0:
            continue
        continuation = str(df.at[idx, df.columns[0]])

        # 이전 유효 행 찾기 (연속 broken 행 대응)
        prev_idx = idx - 1
        while prev_idx in rows_to_drop and prev_idx > 0:
            prev_idx -= 1

        # 이전 행의 마지막 비NaN 텍스트 컬럼에 병합
        prev_row = df.loc[prev_idx]
        for col_idx in range(len(prev_row) - 1, -1, -1):
            val = prev_row.iloc[col_idx]
            if pd.notna(val):
                df.iat[prev_idx, col_idx] = f"{val}\n{continuation}"
                break

        rows_to_drop.append(idx)

    if rows_to_drop:
        df = df.drop(rows_to_drop).reset_index(drop=True)

    return df, len(rows_to_drop)


def _drop_empty_rows_cols(df: pd.DataFrame) -> pd.DataFrame:
    """모든 값이 NaN인 행과 열을 제거한다.

    Why: ERP 덤프에서 빈 구분 행이나 빈 컬럼이 포함되는 경우가 흔하다.
    헤더 탐지·매핑 전에 제거해야 컬럼 수가 맞는다.
    """
    before = df.shape
    df = df.dropna(how="all")  # 빈 행 제거
    df = df.dropna(axis=1, how="all")  # 빈 열 제거
    df = df.reset_index(drop=True)
    after = df.shape
    if before != after:
        dropped_rows = before[0] - after[0]
        dropped_cols = before[1] - after[1]
        parts = []
        if dropped_rows:
            parts.append(f"빈 행 {dropped_rows}개")
        if dropped_cols:
            parts.append(f"빈 열 {dropped_cols}개")
        logger.info("제거: %s", ", ".join(parts))
    return df


def _repair_unclosed_quotes(
    df: pd.DataFrame,
    path: Path,
    csv_kwargs: dict,
) -> pd.DataFrame:
    """미닫힌 따옴표로 인해 행이 병합된 경우 quoting=NONE으로 재파싱.

    Why: "닫히지 않은 적요\\nJE2025-0003,..." 처럼 따옴표가 안 닫히면
    다음 행이 현재 셀에 먹힌다. 파일의 줄 수 대비 DataFrame 행 수가
    크게 적으면 따옴표 문제로 판단하고 quoting=NONE으로 재시도한다.
    """
    try:
        raw = path.read_bytes()[:_PRESCAN_SAMPLE_BYTES]
        text = raw.decode(csv_kwargs.get("encoding", "utf-8"), errors="replace")
        expected_lines = len([ln for ln in text.splitlines() if ln.strip()])
    except Exception:
        return df

    # 헤더 1행 제외한 데이터 행 수 비교
    actual_rows = len(df)
    # 20% 이상 행이 누락되었으면 따옴표 문제로 판단
    if actual_rows >= expected_lines * 0.8:
        return df

    logger.warning(
        "미닫힌 따옴표 감지 (기대 %d행, 실제 %d행) — quoting=NONE으로 재파싱: %s",
        expected_lines - 1,
        actual_rows,
        path.name,
    )
    retry_kwargs = {**csv_kwargs, "quoting": csv.QUOTE_NONE}
    try:
        df_retry = pd.read_csv(path, **retry_kwargs)
        if len(df_retry) > actual_rows:
            # Why: 정상 멀티라인 필드가 있는 파일에서는 QUOTE_NONE이
            # 오히려 정상 행을 깨뜨린다. NaN 비율로 품질을 비교하여
            # 재파싱이 원본보다 나빠지면 사용하지 않는다.
            orig_nan = df.isna().sum().sum() / max(df.size, 1)
            retry_nan = df_retry.isna().sum().sum() / max(df_retry.size, 1)
            if retry_nan > orig_nan:
                logger.info("QUOTE_NONE 재파싱 결과가 원본보다 나빠짐 — 원본 유지")
                return df

            # QUOTE_NONE은 따옴표를 데이터로 취급하므로 잔류 따옴표 정리
            for col in df_retry.columns:
                if df_retry[col].dtype == object:
                    df_retry[col] = df_retry[col].str.strip('"').str.replace('""', '"', regex=False)
            return df_retry
    except Exception:
        pass

    return df


_ALT_DELIMITERS = [";", "\t", "|"]


def _repair_mixed_delimiters(df: pd.DataFrame, primary_sep: str) -> pd.DataFrame:
    """혼합 구분자 행을 감지하고 대체 구분자로 재파싱한다.

    Why: 실무 ERP 덤프에서 복사-붙여넣기로 구분자가 섞이는 경우가 있다.
    1열에만 값이 있고 나머지가 전부 NaN인 행은 구분자가 다른 것으로 추정.
    해당 행의 1열 값을 대체 구분자(; \\t |)로 분할하여 복구한다.
    """
    if df.shape[1] < 2:
        return df

    total_cols = df.shape[1]
    alts = [d for d in _ALT_DELIMITERS if d != primary_sep]
    repaired = 0

    for row_idx in range(len(df)):
        row = df.iloc[row_idx]
        # 1열만 값이 있고 나머지 전부 NaN → 구분자 이상 의심
        if pd.notna(row.iloc[0]) and row.iloc[1:].isna().all():
            cell = str(row.iloc[0])
            for alt in alts:
                parts = list(csv.reader(io.StringIO(cell), delimiter=alt))[0]
                if len(parts) >= total_cols * 0.5:
                    # 복구: 분할된 값으로 행 교체
                    for col_idx, val in enumerate(parts[:total_cols]):
                        df.iat[row_idx, col_idx] = val.strip()
                    repaired += 1
                    break

    if repaired > 0:
        logger.warning(
            "혼합 구분자 %d행 복구 (주 구분자: '%s', 대체 구분자로 재파싱)",
            repaired,
            primary_sep,
        )

    return df


def _count_lines_fast(path: Path) -> int:
    """바이트 스캔으로 줄 수를 빠르게 추정한다.

    Why: 321MB CSV도 바이트 단위 개행 카운트는 1초 미만.
    pd.read_csv 청크 진행률 계산의 분모로 사용한다.
    """
    count = 0
    with open(path, "rb") as f:
        while buf := f.read(1 << 20):  # 1MB 단위
            count += buf.count(b"\n")
    return max(count, 1)


def _read_csv_chunked(
    path: Path,
    csv_kwargs: dict,
    total_lines: int,
    progress_cb: Callable[[float, str], None],
    separator: str = ",",
) -> tuple[pd.DataFrame, list[str]]:
    """청크 단위로 CSV를 읽으며 진행률 보고 + 인크리멘탈 진단을 수행한다.

    Why: pd.read_csv는 대용량 파일에서 블로킹 호출이라 UI가 멈춘다.
    chunksize로 분할 읽기하면서 동시에 진단을 수행하면:
    - 별도 전체 df.isna() 불필요 (33초 → 0초)
    - 50K행 단위 isna는 ~0.3초로 읽기 시간에 자연스럽게 흡수
    - 모든 행 검사하므로 정확도 100%

    Returns:
        (DataFrame, 경고 리스트) 튜플.
    """
    chunks: list[pd.DataFrame] = []
    rows_read = 0
    accum = _DiagAccumulator(separator=separator)

    def _process_chunk(chunk: pd.DataFrame) -> None:
        nonlocal rows_read
        chunks.append(chunk)
        _accumulate_diagnostics(chunk, accum)
        rows_read += len(chunk)
        pct = min(rows_read / total_lines, 0.99)
        progress_cb(pct, f"파일 읽는 중... ({rows_read:,}/{total_lines:,}행)")

    try:
        reader = pd.read_csv(path, chunksize=_CHUNK_SIZE_ROWS, **csv_kwargs)
        for chunk in reader:
            _process_chunk(chunk)
    except pd.errors.ParserError:
        logger.warning("C 파서 실패(청크), python 엔진으로 재시도: %s", path.name)
        chunks.clear()
        rows_read = 0
        accum = _DiagAccumulator(separator=separator)
        csv_kwargs_py = {**csv_kwargs, "engine": "python"}
        try:
            reader = pd.read_csv(
                path,
                chunksize=_CHUNK_SIZE_ROWS,
                **csv_kwargs_py,
            )
            for chunk in reader:
                _process_chunk(chunk)
        except pd.errors.ParserError as exc:
            raise OSError(f"C/python 파서 모두 실패: {path.name}") from exc

    if not chunks:
        return pd.DataFrame(), []

    progress_cb(0.99, f"데이터 병합 중... ({rows_read:,}행)")
    df = pd.concat(chunks, ignore_index=True)

    warnings = _finalize_diagnostics(accum, path, csv_kwargs)
    return df, warnings


def read_text(
    path: Path,
    *,
    encoding_override: str | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
) -> ReadResult:
    """텍스트 파일을 DataFrame으로 읽어 ReadResult를 반환한다.

    Args:
        path: 읽을 파일 경로.
        encoding_override: 수동 인코딩 지정. 지정하면 자동 감지 스킵.
            Why: CP949/EUC-KR 오인 등 실무 ERP 덤프에서 자동 감지가
            틀릴 때 사용자가 직접 교정할 수 있게 한다.
        progress_cb: (pct, msg) 형태의 진행률 콜백. 대용량 파일에서
            청크 단위 읽기 진행률을 UI에 보고한다.

    Raises:
        OSError: 파일 읽기 실패 시, 또는 C/python 파서 모두 실패 시.
        LookupError: encoding_override가 잘못된 인코딩명일 때.
    """
    if encoding_override is not None:
        encoding = encoding_override
        encoding_confidence = None
    else:
        encoding, encoding_confidence = _detect_encoding(path)

    separator = _detect_separator(path, encoding)
    ext = path.suffix.lower()

    max_cols = _prescan_max_columns(path, encoding, separator)
    names = list(range(max_cols)) if max_cols > 0 else None

    csv_kwargs: dict = dict(
        sep=separator,
        encoding=encoding,
        header=None,
        dtype=str,
        on_bad_lines="warn",
    )
    if names is not None:
        csv_kwargs["names"] = names

    # Why: 10MB 이상 + progress_cb → 청크 읽기 + 인크리멘탈 진단 (33초 → 0초)
    file_size = path.stat().st_size
    use_chunked = progress_cb is not None and file_size >= _CHUNK_THRESHOLD_BYTES

    if use_chunked:
        # ── 대용량: 청크 읽기 + 동시 진단 (정확도 100%, 별도 전체 스캔 불필요) ──
        total_lines = _count_lines_fast(path)
        progress_cb(0.0, f"파일 읽는 중... (0/{total_lines:,}행)")
        df, data_warnings = _read_csv_chunked(
            path,
            csv_kwargs,
            total_lines,
            progress_cb,
            separator=separator,
        )
    else:
        # ── 소형: 한 번에 읽기 + 전체 스캔 진단 ──
        try:
            df = pd.read_csv(path, **csv_kwargs)
        except pd.errors.ParserError:
            logger.warning(
                "C 파서 실패, python 엔진으로 재시도: %s",
                path.name,
            )
            csv_kwargs["engine"] = "python"
            try:
                df = pd.read_csv(path, **csv_kwargs)
            except pd.errors.ParserError as exc:
                raise OSError(
                    f"C/python 파서 모두 실패: {path.name}",
                ) from exc
        data_warnings = _diagnose_issues(df, path, separator, csv_kwargs)

    return ReadResult(
        sheets=[_DEFAULT_SHEET],
        active_sheet=_DEFAULT_SHEET,
        raw_data={_DEFAULT_SHEET: df},
        encoding=encoding,
        encoding_confidence=encoding_confidence,
        source_format=ext.lstrip("."),
        data_warnings=data_warnings,
    )
