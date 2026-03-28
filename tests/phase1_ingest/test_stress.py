"""Stress Test (시나리오 01~10): 실무 극단적 엣지 케이스 검증.

각 테스트 파일의 의도적 결함이 ingest 파이프라인에서
올바르게 처리(정상 통과 또는 적절한 에러/경고)되는지 검증한다.
"""

import pandas as pd
import pytest

from src.ingest.file_validator import validate_file
from src.ingest.reader_api import read_file
from src.ingest.header_detector import detect_header_row, detect_headers
from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
from src.ingest.type_caster import cast_amount, cast_date, cast_dataframe
from src.ingest.integrity_checkers import check_text, check_excel_xlsx
from src.ingest.sheet_scorer import score_sheets


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_01: K-기업 멀티시트 Excel (병합셀 + 메타데이터 노이즈)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress01KCorp:
    """멀티시트 Excel: 표지 시트, 병합셀, 특수문자 헤더."""

    def test_validation_passes(self, stress_01):
        result = validate_file(stress_01)
        assert result.is_valid
        assert result.file_category == "excel"

    def test_read_multiple_sheets(self, stress_01):
        rr = read_file(stress_01)
        assert len(rr.sheets) >= 2
        assert rr.source_format == "xlsx"

    def test_sheet_scorer_recommends_data_sheet(self, stress_01):
        """표지 시트가 아닌 '본 데이터' 시트를 최고 점수로 추천."""
        rr = read_file(stress_01)
        hdr_results = detect_headers(rr)
        scores = score_sheets(rr, hdr_results)

        recommended = [s for s in scores if s.recommended]
        assert len(recommended) == 1
        # 표지 시트가 아닌 데이터 시트가 추천되어야 함
        assert "표지" not in recommended[0].sheet_name

    def test_header_detection_skips_metadata(self, stress_01):
        """메타데이터 행(결재란 등)을 건너뛰고 실제 헤더 행을 찾아야 함."""
        rr = read_file(stress_01)
        hdr_results = detect_headers(rr)

        # 데이터 시트에서 헤더 탐지 확인
        data_sheets = [s for s in rr.sheets if "표지" not in s]
        assert len(data_sheets) > 0

        data_sheet = data_sheets[0]
        hdr = hdr_results[data_sheet]
        assert hdr.header_row is not None
        assert hdr.confidence >= 0.5

    def test_fuzzy_match_special_chars(self, stress_01):
        """'[필수] 전표번호' 같은 특수문자 접두사를 fuzzy match로 해결."""
        rr = read_file(stress_01)
        hdr_results = detect_headers(rr)
        data_sheets = [s for s in rr.sheets if "표지" not in s]
        data_sheet = data_sheets[0]
        hdr = hdr_results[data_sheet]

        raw_df = rr.raw_data[data_sheet]
        cols, data_df = prepare_dataframe(raw_df, hdr.header_row)
        mapping_result = auto_map_columns(
            cols, hdr.matched_keywords, data_df=data_df
        )

        # document_id가 매핑되어야 함 (exact 또는 fuzzy)
        all_mapped = {**mapping_result.mapping, **mapping_result.suggestions}
        mapped_targets = set(all_mapped.values())
        assert "document_id" in mapped_targets


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_02: CP949 인코딩 + 파이프 구분자
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress02AlienEncoding:
    """CP949 인코딩 + 파이프 구분자 + 확장 완성형 한글."""

    def test_integrity_check_warns_encoding(self, stress_02):
        """check_text가 비UTF-8 인코딩을 감지하고 경고."""
        errors, warnings = check_text(stress_02)
        assert len(errors) == 0
        # 인코딩 관련 경고가 있어야 함
        warning_text = " ".join(warnings).lower()
        assert "cp949" in warning_text or "utf" in warning_text or "인코딩" in warning_text

    def test_read_detects_pipe_separator(self, stress_02):
        """파이프 구분자를 감지하여 정상 파싱."""
        rr = read_file(stress_02)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        # 파이프 구분이 실패하면 컬럼이 1개로 합쳐짐
        assert df.shape[1] >= 5, f"컬럼 수 부족: {df.shape[1]} (파이프 구분 실패 의심)"

    def test_data_row_count(self, stress_02):
        """15행 데이터가 정상 파싱되어야 함."""
        rr = read_file(stress_02)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 10, f"행 수 부족: {df.shape[0]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_03: 혼합 날짜/금액 포맷 + 유령 컬럼
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress03TypeHell:
    """혼합 날짜/금액 포맷, BOM, 유령 컬럼 처리."""

    def test_cast_amount_various_formats(self, stress_03):
        """쉼표, 통화기호, 괄호음수, 비숫자 문자열 처리."""
        rr = read_file(stress_03)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        # 차변금액 컬럼 찾기
        debit_idx = None
        for i, c in enumerate(cols):
            if "차변" in str(c):
                debit_idx = i
                break
        assert debit_idx is not None, "차변금액 컬럼을 찾을 수 없음"

        series = data_df.iloc[:, debit_idx]
        result = cast_amount(series)

        # "1,234,567" → 1234567.0
        assert result.iloc[0] == pytest.approx(1234567.0, abs=1)
        # "(500,000)" → -500000.0
        assert result.iloc[2] == pytest.approx(-500000.0, abs=1)
        # "미정", "N/A" → NaN
        assert pd.isna(result.iloc[7]) or pd.isna(result.iloc[8])

    def test_cast_date_mixed_formats(self, stress_03):
        """ISO, 한국어, 8자리, Excel serial, 슬래시 등 혼합 날짜."""
        rr = read_file(stress_03)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        # 전표일자 컬럼 찾기
        date_idx = None
        for i, c in enumerate(cols):
            if "전표일자" in str(c) or "posting" in str(c).lower():
                date_idx = i
                break
        assert date_idx is not None, "전표일자 컬럼을 찾을 수 없음"

        series = data_df.iloc[:, date_idx]
        result = cast_date(series)

        # ISO 날짜(행 0)는 정상 변환
        assert pd.notna(result.iloc[0])
        # 빈 값 행은 NaT
        nan_count = result.isna().sum()
        assert nan_count >= 1, "빈 날짜가 NaT로 변환되어야 함"

    def test_cast_dataframe_empty_columns(self, stress_03):
        """세금코드(100% NaN) → empty_columns 분류."""
        rr = read_file(stress_03)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        # 컬럼명 설정
        data_df.columns = cols
        cr = cast_dataframe(data_df)

        # 세금코드가 empty_columns에 포함되거나, 100% NaN이어야 함
        tax_cols = [c for c in cols if "세금" in str(c) or "tax" in str(c).lower()]
        if tax_cols:
            assert (
                any(tc in cr.empty_columns for tc in tax_cols)
                or all(cr.data[tc].isna().all() for tc in tax_cols if tc in cr.data.columns)
            ), "세금코드가 empty_columns로 분류되어야 함"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_04: 필수 컬럼 누락 + 중복 컬럼 + fuzzy Yellow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress04MappingBreaker:
    """필수 컬럼 누락, 중복 컬럼명, 비표준 컬럼명."""

    def test_prepare_deduplicates_columns(self, stress_04):
        """'금액' 중복 → '금액', '금액_2'로 dedup."""
        rr = read_file(stress_04)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        # 중복된 '금액'이 dedup되어야 함
        amount_cols = [c for c in cols if "금액" in str(c)]
        assert len(amount_cols) >= 2
        assert len(set(amount_cols)) == len(amount_cols), "중복 컬럼명이 제거되지 않음"

    def test_missing_required_posting_date(self, stress_04):
        """posting_date 컬럼 부재 → missing_required 포함."""
        rr = read_file(stress_04)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        mr = auto_map_columns(cols, hdr.matched_keywords, data_df=data_df)

        # posting_date가 매핑되지 않았으므로 missing_required에 포함
        assert mr.needs_review
        assert len(mr.missing_required) > 0, "필수 컬럼 누락이 감지되어야 함"

    def test_fuzzy_yellow_zone(self, stress_04):
        """'항목코드_V2' → gl_account fuzzy 매칭 (Yellow 구간)."""
        rr = read_file(stress_04)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        mr = auto_map_columns(cols, hdr.matched_keywords, data_df=data_df)

        # '항목코드_V2'가 suggestions(Yellow)에 있거나 unmapped에 있어야 함
        all_mapped = set(mr.mapping.keys())
        all_suggested = set(mr.suggestions.keys())
        item_col = [c for c in cols if "항목코드" in str(c)]
        if item_col:
            col_name = item_col[0]
            assert (
                col_name in all_suggested or col_name in mr.unmapped
            ), f"'{col_name}'이 suggestions 또는 unmapped에 있어야 함"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_05a: 확장자 위조 Excel
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress05aFakeExcel:
    """CSV 내용을 .xlsx 확장자로 저장한 위조 파일."""

    def test_integrity_check_fails(self, stress_05a):
        errors, warnings = check_excel_xlsx(stress_05a)
        assert len(errors) > 0, "위조 Excel이 무결성 검사를 통과해서는 안 됨"

    def test_validation_rejects(self, stress_05a):
        result = validate_file(stress_05a)
        assert not result.is_valid
        assert len(result.errors) > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_05b: 빈 파일 (0 bytes)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress05bEmpty:
    """0 byte 빈 파일."""

    def test_validation_rejects_empty(self, stress_05b):
        result = validate_file(stress_05b)
        assert not result.is_valid
        error_text = " ".join(result.errors)
        assert "0" in error_text or "빈" in error_text or "empty" in error_text.lower()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_06: Excel 재저장 오염 (지수 표기법 + 잘린 행)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress06ExcelCurse:
    """SAP CSV를 Excel로 열었다가 재저장하여 오염된 파일."""

    def test_read_without_crash(self, stress_06):
        """잘린 행이 있어도 python 엔진 폴백으로 파이프라인이 중단되지 않아야 함."""
        rr = read_file(stress_06)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 10, "대부분의 행이 파싱되어야 함"

    def test_scientific_notation_amount(self, stress_06):
        """금액 지수 표기법 '1.5E+07' → 15000000.0 변환."""
        rr = read_file(stress_06)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        debit_idx = None
        for i, c in enumerate(cols):
            if "차변" in str(c):
                debit_idx = i
                break
        if debit_idx is None:
            pytest.skip("차변금액 컬럼을 찾을 수 없음")

        series = data_df.iloc[:, debit_idx]
        result = cast_amount(series)

        values = result.dropna().values
        assert any(
            v >= 10_000_000 for v in values
        ), "지수 표기법 금액이 올바르게 변환되어야 함"

    def test_scientific_amount_directly(self):
        """지수 표기법 금액을 cast_amount로 직접 테스트."""
        series = pd.Series(["15000000", "1.5E+07", "2.2E+07", "350000"])
        result = cast_amount(series)
        assert result.iloc[1] == pytest.approx(15_000_000, abs=1)
        assert result.iloc[2] == pytest.approx(22_000_000, abs=1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_07: 줄바꿈이 포함된 적요 필드
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress07MemoRebellion:
    """적요 필드의 멀티라인 줄바꿈 처리."""

    def test_read_without_crash(self, stress_07):
        """줄바꿈이 포함되어도 파이프라인이 중단되지 않아야 함."""
        rr = read_file(stress_07)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        # 완벽히 파싱되지 않더라도 최소한 일부 행이 파싱
        assert df.shape[0] >= 3, f"최소 3행 이상 파싱되어야 함 (실제: {df.shape[0]})"

    def test_quoted_multiline_preserved(self, stress_07):
        """큰따옴표로 감싼 멀티라인 적요가 하나의 필드로 유지."""
        rr = read_file(stress_07)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]

        if hdr.header_row is not None:
            cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)
            # 적요 컬럼 중 줄바꿈 포함 값 존재 확인
            memo_idx = None
            for i, c in enumerate(cols):
                if "적요" in str(c) or "memo" in str(c).lower():
                    memo_idx = i
                    break
            if memo_idx is not None:
                memo_vals = data_df.iloc[:, memo_idx].dropna().astype(str)
                has_newline = any("\n" in v for v in memo_vals)
                # 큰따옴표로 감싼 줄바꿈은 필드 내에 유지되어야 함
                assert has_newline, "큰따옴표로 감싼 멀티라인이 하나의 필드로 유지되어야 함"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_08: 다국가 날짜 포맷 혼재
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress08FrankensteinDate:
    """ISO, MM/DD/YYYY, DD.MM.YYYY, Excel serial, 한국어, 8자리 등 혼재."""

    def test_cast_date_multi_format(self, stress_08):
        """8가지 날짜 포맷이 혼재한 컬럼을 행 단위로 변환."""
        rr = read_file(stress_08)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        # 전표일자 컬럼
        date_idx = None
        for i, c in enumerate(cols):
            if "전표일자" in str(c):
                date_idx = i
                break
        assert date_idx is not None

        series = data_df.iloc[:, date_idx]
        result = cast_date(series)

        total = len(result)
        converted = result.notna().sum()

        # 최소 60% 이상 변환 성공 (일부 약식 포맷은 실패 가능)
        ratio = converted / total
        assert ratio >= 0.6, f"날짜 변환율 {ratio:.0%} (기대: ≥60%)"

    def test_iso_dates_correct(self, stress_08):
        """ISO 8601 날짜는 반드시 정확히 변환."""
        rr = read_file(stress_08)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        date_idx = None
        for i, c in enumerate(cols):
            if "전표일자" in str(c):
                date_idx = i
                break
        assert date_idx is not None

        series = data_df.iloc[:, date_idx]
        result = cast_date(series)

        # 첫 두 행은 ISO 포맷 → 반드시 변환 성공
        assert pd.notna(result.iloc[0]), "ISO 날짜가 NaT로 변환됨"
        assert pd.notna(result.iloc[1]), "ISO 날짜가 NaT로 변환됨"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_09: BOM + Zero-Width Space
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress09InvisibleAssassin:
    """UTF-8 BOM + ZWSP가 숨겨진 CSV."""

    def test_read_succeeds(self, stress_09):
        """BOM이 있어도 읽기 성공."""
        rr = read_file(stress_09)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 10

    def test_zwsp_in_amount_cleaned(self, stress_09):
        """ZWSP가 포함된 금액이 정제 후 정상 변환되는지 확인."""
        # 직접 테스트: "350\u200B000" → 350000.0
        series = pd.Series(["350\u200B000", "15000000", "0"])
        result = cast_amount(series)
        assert result.iloc[0] == pytest.approx(350_000, abs=1), (
            f"ZWSP 정제 후 350000이어야 함 (실제: {result.iloc[0]})"
        )

    def test_zwsp_in_file_amount(self, stress_09):
        """실제 파일에서 ZWSP 금액 처리 확인."""
        rr = read_file(stress_09)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        debit_idx = None
        for i, c in enumerate(cols):
            if "차변" in str(c):
                debit_idx = i
                break
        if debit_idx is None:
            pytest.skip("차변금액 컬럼을 찾을 수 없음")

        series = data_df.iloc[:, debit_idx]
        result = cast_amount(series)

        # ZWSP 정제 후 NaN이 아닌 정상 값이 더 많아야 함
        non_null = result.notna().sum()
        assert non_null >= len(result) * 0.8, (
            f"ZWSP 정제 후 NaN 비율이 높음 ({non_null}/{len(result)})"
        )

    def test_header_mapping_with_bom(self, stress_09):
        """BOM이 붙은 첫 컬럼명이 매핑되는지 확인."""
        rr = read_file(stress_09)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        mr = auto_map_columns(cols, hdr.matched_keywords, data_df=data_df)

        # document_id가 매핑되어야 함 (exact 또는 fuzzy)
        all_mapped = {**mr.mapping, **mr.suggestions}
        mapped_targets = set(all_mapped.values())
        assert "document_id" in mapped_targets, (
            f"BOM이 붙은 '전표번호'가 매핑 실패. "
            f"mapped: {mr.mapping}, suggestions: {mr.suggestions}"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stress_10: trailing delimiter (유령 컬럼)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStress10GhostPipeline:
    """모든 행 끝에 구분자가 하나 더 붙어 유령 컬럼이 생성."""

    def test_raw_data_has_trailing_column(self, stress_10):
        """raw_data에 trailing delimiter로 빈 컬럼이 생성됨을 확인."""
        rr = read_file(stress_10)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        # raw_data(header=None)에서 마지막 컬럼이 100% NaN이어야 함
        last_col = df.iloc[:, -1]
        null_ratio = last_col.isna().sum() / len(last_col)
        assert null_ratio >= 0.9, (
            f"trailing delimiter의 마지막 컬럼이 NaN이어야 함 (null: {null_ratio:.0%})"
        )

    def test_prepare_handles_ghost(self, stress_10):
        """prepare_dataframe 후 유령 컬럼이 처리되는지 확인."""
        rr = read_file(stress_10)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        # prepare_dataframe이 빈 컬럼명을 제거했거나, 남아 있다면 NaN 컬럼
        empty_named = [c for c in cols if str(c).strip() == "" or "unnamed" in str(c).lower()]
        if empty_named:
            for c_name in empty_named:
                idx = cols.index(c_name)
                assert data_df.iloc[:, idx].isna().all()
        else:
            # 빈 컬럼명이 이미 제거됨 → 정상 처리
            assert len(cols) >= 10, "유효 컬럼이 최소 10개"
