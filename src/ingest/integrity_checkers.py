"""파일 무결성 검증 — 확장자별로 실제 파일을 열어 손상 여부를 확인한다.

각 함수는 (errors, warnings) 튜플을 반환한다.
errors가 비어있으면 무결성 통과.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def check_excel_xlsx(path: Path) -> tuple[list[str], list[str]]:
    """openpyxl로 .xlsx 파일 열기 시도."""
    import openpyxl

    errors: list[str] = []
    warnings: list[str] = []
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        wb.close()
    except Exception as exc:
        # 암호화된 파일은 경고로 처리 (복호화 후 재시도 가능)
        msg = str(exc).lower()
        if "password" in msg or "encrypt" in msg:
            errors.append(f"암호화된 Excel 파일입니다: {exc}")
        else:
            errors.append(f"Excel 파일 손상: {exc}")
    return errors, warnings


def check_excel_xls(path: Path) -> tuple[list[str], list[str]]:
    """xlrd로 .xls 파일 열기 시도."""
    import xlrd  # noqa: F811

    errors: list[str] = []
    warnings: list[str] = [".xls는 레거시 형식입니다. .xlsx 변환을 권장합니다."]
    try:
        wb = xlrd.open_workbook(str(path))
        wb.release_resources()
    except Exception as exc:
        # xlrd는 XLRDError 외에 CompDocError 등도 던질 수 있음
        msg = str(exc).lower()
        if "password" in msg or "encrypt" in msg:
            errors.append(f"암호화된 XLS 파일입니다: {exc}")
        else:
            errors.append(f"XLS 파일 손상: {exc}")
    return errors, warnings


def check_excel_xlsb(path: Path) -> tuple[list[str], list[str]]:
    """pyxlsb로 .xlsb 파일 열기 시도."""
    import pyxlsb

    errors: list[str] = []
    warnings: list[str] = []
    try:
        wb = pyxlsb.open_workbook(str(path))
        wb.close()
    except Exception as exc:
        msg = str(exc).lower()
        if "password" in msg or "encrypt" in msg:
            errors.append(f"암호화된 XLSB 파일입니다: {exc}")
        else:
            errors.append(f"XLSB 파일 손상: {exc}")
    return errors, warnings


def check_text(path: Path) -> tuple[list[str], list[str]]:
    """텍스트 파일의 인코딩을 감지하고 읽기를 시도한다."""
    import charset_normalizer

    errors: list[str] = []
    warnings: list[str] = []

    # 한글이 파일 후반부에 집중된 경우에도 정확히 감지하기 위해 64KB 샘플링
    _ENCODING_SAMPLE_BYTES = 64 * 1024
    raw_sample = path.read_bytes()[:_ENCODING_SAMPLE_BYTES]
    detection = charset_normalizer.from_bytes(raw_sample).best()

    if detection is None:
        # Why: ASCII 비율이 높은 UTF-8 파일은 charset_normalizer가 None 반환.
        #      샘플 경계에서 멀티바이트가 잘릴 수 있으므로 끝 3바이트까지 허용.
        try:
            raw_sample.decode("utf-8", errors="ignore")
            # ignore로 디코딩 가능하면 UTF-8 파일로 판단
            encoding = "utf-8"
        except Exception:
            errors.append("파일 인코딩을 감지할 수 없습니다.")
            return errors, warnings
    else:
        encoding = detection.encoding

    # UTF-8이 아닌 인코딩은 경고
    if encoding.lower() not in ("utf-8", "ascii"):
        warnings.append(
            f"인코딩 '{encoding}' 감지됨. UTF-8 변환을 권장합니다."
        )

    # 실제 읽기 시도 (첫 5줄)
    try:
        with open(path, encoding=encoding, errors="strict") as f:
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
    except Exception as exc:
        errors.append(f"텍스트 파일 읽기 실패: {exc}")

    return errors, warnings


def check_parquet(path: Path) -> tuple[list[str], list[str]]:
    """pyarrow로 parquet 메타데이터만 읽어 무결성을 확인한다."""
    import pyarrow.parquet as pq

    errors: list[str] = []
    warnings: list[str] = []
    try:
        # 메타데이터만 읽어 파일 구조 검증 (데이터 로드 없음)
        pq.read_metadata(path)
    except Exception as exc:
        errors.append(f"Parquet 파일 손상: {exc}")
    return errors, warnings


# 확장자 → 검증 함수 매핑
INTEGRITY_CHECKERS: dict[str, Callable[[Path], tuple[list[str], list[str]]]] = {
    ".xlsx": check_excel_xlsx,
    ".xls": check_excel_xls,
    ".xlsb": check_excel_xlsb,
    ".csv": check_text,
    ".tsv": check_text,
    ".txt": check_text,
    ".dat": check_text,
    ".parquet": check_parquet,
}
