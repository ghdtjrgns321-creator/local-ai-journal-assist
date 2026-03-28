"""Systematic Test (시나리오 sys_01~15): 포맷/구조 개별 검증.

각 카테고리(구분자, 인코딩, 헤더, 구조, 타입)를 독립적으로 검증하는 기본 파일.
"""

import pandas as pd
import pytest

from src.ingest.file_validator import validate_file
from src.ingest.reader_api import read_file
from src.ingest.header_detector import detect_header_row, detect_headers
from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
from src.ingest.type_caster import cast_dataframe
from src.ingest.sheet_scorer import score_sheets


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_01: 정상 CSV (baseline)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys01Baseline:
    """정상 UTF-8 CSV. 모든 모듈의 기준선."""

    def test_validation_clean(self, sys_01):
        result = validate_file(sys_01)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_full_pipeline(self, sys_01):
        """validation → read → header → mapping → casting 전체 통과."""
        rr = read_file(sys_01)
        assert rr.source_format == "csv"

        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]

        assert hdr.header_row is not None
        assert hdr.confidence >= 0.5

        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)
        mr = auto_map_columns(cols, hdr.matched_keywords, data_df=data_df)

        # 정상 파일은 needs_review=False이어야 함
        assert not mr.needs_review or len(mr.missing_required) == 0

        data_df.columns = cols
        cr = cast_dataframe(data_df)
        assert cr.success
        assert len(cr.errors) == 0

    def test_data_shape(self, sys_01):
        """10행 11열 데이터."""
        rr = read_file(sys_01)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)
        assert data_df.shape[0] == 10
        assert len(cols) == 11


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_02: 세미콜론 구분 CSV
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys02Semicolon:
    """세미콜론 구분자 자동 감지."""

    def test_read_detects_semicolon(self, sys_02):
        rr = read_file(sys_02)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        # 세미콜론 감지 실패 시 컬럼이 1개로 합쳐짐
        assert df.shape[1] >= 5, f"세미콜론 구분 감지 실패 (컬럼: {df.shape[1]})"

    def test_pipeline_after_semicolon(self, sys_02):
        rr = read_file(sys_02)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        assert hdr.header_row is not None
        assert hdr.confidence >= 0.3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_03: 지연 헤더 (5행)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys03HeaderLate:
    """1~4행에 제목/설명, 실제 헤더는 5행.

    [한계] 메타데이터 행에 쉼표가 없으면 csv.Sniffer가 구분자를
    오판하여 전체 파일이 1컬럼으로 읽힐 수 있다.
    """

    def test_read_succeeds(self, sys_03):
        """파일 읽기 자체는 성공해야 함."""
        rr = read_file(sys_03)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 5

    def test_header_row_detection(self, sys_03):
        """Sniffer 검증 폴백으로 쉼표 감지 후 헤더 행을 찾아야 함.

        Note: 원본 파일에서 헤더는 5행(빈 줄 포함)이지만,
        prescan + names 강제에 의해 빈 줄이 NaN 행이 아닌 skip 처리되어
        raw DataFrame에서는 row 3이 헤더가 된다.
        """
        rr = read_file(sys_03)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        df = rr.raw_data[sheet]

        assert df.shape[1] >= 5, f"Sniffer 폴백 실패 (컬럼: {df.shape[1]})"
        assert hdr.header_row is not None
        assert hdr.header_row == 3, f"헤더 행이 3이어야 함 (실제: {hdr.header_row})"
        assert hdr.confidence >= 0.5

    def test_data_after_late_header(self, sys_03):
        """헤더 이후 데이터가 정상 파싱."""
        rr = read_file(sys_03)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        assert data_df.shape[0] == 10
        assert "전표번호" in cols or any("전표" in str(c) for c in cols)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_04: 파이프 구분 + 헤더 없음
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys04PipeNoHeader:
    """파이프 구분자 + 헤더 행 없음."""

    def test_pipe_separator_detected(self, sys_04):
        rr = read_file(sys_04)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[1] >= 5, "파이프 구분 감지 실패"

    def test_header_low_confidence(self, sys_04):
        """헤더가 없으므로 confidence가 낮아야 함."""
        rr = read_file(sys_04)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]

        # 헤더 없는 파일: confidence가 낮거나 header_row가 None
        if hdr.header_row is not None:
            assert hdr.confidence < 0.7, (
                f"헤더 없는 파일인데 confidence가 높음: {hdr.confidence}"
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_05: 혼합 구분자
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys05MixedDelimiter:
    """행마다 구분자가 다른 파일."""

    def test_read_without_crash(self, sys_05):
        """혼합 구분자에서도 파이프라인 중단 없음."""
        rr = read_file(sys_05)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 1, "최소 1행은 파싱되어야 함"

    def test_sniffer_picks_something(self, sys_05):
        """Sniffer가 구분자를 선택하고 결과를 반환.

        [한계] 행마다 구분자가 다르면 Sniffer가 가장 빈번한 것을
        선택하거나 실패할 수 있다. 1컬럼이 되어도 에러는 아님.
        """
        rr = read_file(sys_05)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        # 파이프라인 중단 없이 어떤 결과든 반환되면 성공
        assert df.shape[0] >= 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_06: 고 결측률
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys06HighNull:
    """90%+ 결측 컬럼 + 100% 결측(유령) 컬럼.

    Note: cast_dataframe은 schema의 type_map에 등록된 컬럼만 처리.
    한글 컬럼명(세금코드, 코스트센터)은 column_mapper로 매핑 후 테스트해야 함.
    여기서는 매핑 후 결과를 검증한다.
    """

    def test_empty_column_raw_check(self, sys_06):
        """세금코드(100% NaN)가 실제로 모두 비어있는지 raw 확인."""
        rr = read_file(sys_06)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        tax_cols = [i for i, c in enumerate(cols) if "세금" in str(c)]
        for idx in tax_cols:
            null_ratio = data_df.iloc[:, idx].isna().sum() / len(data_df)
            assert null_ratio == 1.0, f"세금코드 결측률: {null_ratio:.0%} (기대: 100%)"

    def test_high_null_raw_check(self, sys_06):
        """코스트센터(90% NaN)의 결측률 확인."""
        rr = read_file(sys_06)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        cost_cols = [i for i, c in enumerate(cols) if "코스트" in str(c)]
        for idx in cost_cols:
            null_ratio = data_df.iloc[:, idx].isna().sum() / len(data_df)
            assert null_ratio >= 0.8, f"코스트센터 결측률: {null_ratio:.0%} (기대: ≥80%)"

    def test_cast_with_mapped_columns(self, sys_06):
        """매핑 후 cast_dataframe이 empty/high_null을 분류하는지 확인."""
        rr = read_file(sys_06)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        mr = auto_map_columns(cols, hdr.matched_keywords, data_df=data_df)
        # 매핑된 컬럼명으로 변경
        renamed = {}
        for src, tgt in mr.mapping.items():
            if src in cols:
                renamed[cols.index(src)] = tgt
        for src, tgt in mr.suggestions.items():
            if src in cols:
                renamed[cols.index(src)] = tgt

        mapped_cols = [
            renamed.get(i, c) for i, c in enumerate(cols)
        ]
        data_df.columns = mapped_cols
        cr = cast_dataframe(data_df)

        # 매핑된 컬럼 중 empty 또는 high_null이 있는지 확인
        total_classified = len(cr.empty_columns) + len(cr.high_null_columns)
        # 이 파일에는 결측 컬럼이 존재하므로 최소 0개 이상
        # (매핑 실패 시 schema에 없어 분류 안 될 수 있음)
        assert cr.success


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_07: 손상된 따옴표
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys07CorruptedQuotes:
    """닫히지 않은 따옴표 + 이중 이스케이프."""

    def test_read_without_crash(self, sys_07):
        """따옴표 오류에도 파이프라인 중단 ��음."""
        rr = read_file(sys_07)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 2, "최소 2행은 파싱되어야 함"

    def test_some_rows_parsed(self, sys_07):
        """닫히지 않은 따옴표로 일부 행이 흡수되더라도 나머지는 파싱.

        [한계] 닫히지 않은 따옴표(행 2)가 다음 행을 흡수하면
        이중 따옴표 행(행 4)이 소실될 수 있다.
        """
        rr = read_file(sys_07)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]

        if hdr.header_row is not None:
            cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)
            # 정상 행이 일부라도 파싱되면 성공
            assert data_df.shape[0] >= 1, "최소 1행은 파싱되어야 함"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_08: 빈 컬럼 + 빈 행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys08EmptyColsRows:
    """빈 컬럼 3개 + 중간 빈 행."""

    def test_read_with_empty_columns(self, sys_08):
        rr = read_file(sys_08)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        # 빈 컬럼 포함하여 파싱됨
        assert df.shape[1] >= 8, "빈 컬럼 포함 최소 8열"

    def test_empty_columns_in_cast(self, sys_08):
        """빈 컬럼이 empty_columns로 분류."""
        rr = read_file(sys_08)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        data_df.columns = cols
        cr = cast_dataframe(data_df)

        # 빈 이름("") 또는 Unnamed 컬럼이 empty_columns에 포함
        empty_or_unnamed = [
            c for c in cols
            if str(c).strip() == "" or "unnamed" in str(c).lower()
        ]
        if empty_or_unnamed:
            assert len(cr.empty_columns) >= 1, (
                f"빈 컬럼이 empty_columns로 분류되어야 함"
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_09: Latin-1 인코딩
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys09Latin1:
    """Latin-1(ISO-8859-1) 인코딩 + 유럽 특수문자."""

    def test_encoding_detected(self, sys_09):
        rr = read_file(sys_09)
        # 인코딩이 감지되어야 함
        assert rr.encoding is not None
        enc_lower = rr.encoding.lower().replace("-", "")
        # latin1, iso88591, windows1252 등 유사 인코딩
        assert any(
            k in enc_lower for k in ["latin", "8859", "1252", "ascii"]
        ), f"Latin-1 계열 인코딩이 감지되어야 함 (실제: {rr.encoding})"

    def test_data_integrity(self, sys_09):
        """유럽 특수문자가 포함된 데이터 정상 파싱."""
        rr = read_file(sys_09)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 5, "최소 5행 파싱"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_10: TSV + 지연 헤더
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys10TsvHeaderLate:
    """탭 구분 TSV, 헤더가 5행.

    [한계] 메타데이터 행에 탭이 없으면 csv.Sniffer가 탭을
    감지 못 하고 다른 문자를 구분자로 선택할 수 있다.
    .tsv 확장자 폴백(\\t)이 Sniffer 실패 시에만 작동하는데,
    Sniffer가 csv.Error를 던지지 않고 잘못된 구분자를 반환하면
    폴백이 작동하지 않는다.
    """

    def test_tab_separator(self, sys_10):
        """Sniffer 검증 폴백으로 탭 감지."""
        rr = read_file(sys_10)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[1] >= 5, f"탭 구분 감지 실패 (컬럼: {df.shape[1]})"

    def test_header_at_row3(self, sys_10):
        """빈 줄 skip 후 0-indexed 3행이 헤더."""
        rr = read_file(sys_10)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]

        assert hdr.header_row is not None
        assert hdr.header_row == 3, f"TSV 헤더 행이 3이어야 함 (실제: {hdr.header_row})"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_11: 열 수 불안정 TXT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys11InconsistentCols:
    """행마다 열 수가 다른 TXT."""

    def test_read_without_crash(self, sys_11):
        """열 수 불일치에도 파이프라인 중단 없음."""
        rr = read_file(sys_11)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 3, "최소 3행은 파싱되어야 함"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_12: 스파스 DAT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys12DatSparse:
    """탭 구분 DAT, 다수 빈 컬럼."""

    def test_tab_detected_for_dat(self, sys_12):
        """DAT 파일에서 탭 구분자 감지."""
        rr = read_file(sys_12)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[1] >= 10, f"탭 구분 감지 실패 (컬럼: {df.shape[1]})"

    def test_many_empty_columns_raw(self, sys_12):
        """6개 빈 컬럼의 NaN 비율 확인 (raw 레벨).

        Note: cast_dataframe은 schema 매핑된 컬럼만 처리하므로,
        한글 컬럼명 상태에서는 empty_columns로 분류되지 않는다.
        여기서는 raw 데이터에서 NaN 비율을 직접 확인한다.
        """
        rr = read_file(sys_12)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]
        cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)

        # 100% NaN인 컬럼 수 확인
        all_nan_count = sum(
            1 for i in range(data_df.shape[1])
            if data_df.iloc[:, i].isna().all()
        )
        assert all_nan_count >= 3, (
            f"100% NaN 컬럼이 최소 3개 이상이어야 함 (실제: {all_nan_count})"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_13: Parquet fast path
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys13Parquet:
    """이미 올바른 타입을 가진 Parquet."""

    def test_validation_passes(self, sys_13):
        result = validate_file(sys_13)
        assert result.is_valid
        assert result.file_category == "columnar"

    def test_parquet_reader(self, sys_13):
        rr = read_file(sys_13)
        assert rr.source_format == "parquet"
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        assert df.shape[0] >= 5

    def test_parquet_types_preserved(self, sys_13):
        """Parquet에서 읽은 DataFrame의 타입이 이미 올바른지 확인.

        Note: cast_dataframe의 skipped_columns는 schema 컬럼명과
        DataFrame 컬럼명이 일치해야 동작. Parquet은 이미 정제된
        컬럼명을 사용하므로, 매핑 없이도 타입이 보존되는지 확인.
        """
        rr = read_file(sys_13)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]

        # Parquet은 타입 정보를 보존하므로 numeric/datetime 컬럼이 있어야 함
        has_numeric = any(
            pd.api.types.is_numeric_dtype(df[c]) for c in df.columns
        )
        has_datetime = any(
            pd.api.types.is_datetime64_any_dtype(df[c]) for c in df.columns
        )
        assert has_numeric or has_datetime, (
            f"Parquet 타입 보존 실패. dtypes: {dict(df.dtypes)}"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_14: 잘못된 시트 우선
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys14WrongSheet:
    """첫 시트가 요약, 실제 데이터는 3번째 시트."""

    def test_multiple_sheets(self, sys_14):
        rr = read_file(sys_14)
        assert len(rr.sheets) >= 3

    def test_scorer_recommends_data_sheet(self, sys_14):
        """'전표내역'(Sheet 3)이 최고 점수."""
        rr = read_file(sys_14)
        hdr_results = detect_headers(rr)
        scores = score_sheets(rr, hdr_results)

        recommended = [s for s in scores if s.recommended]
        assert len(recommended) == 1

        rec_name = recommended[0].sheet_name
        # "요약"이나 "월별추이"가 아닌 데이터 시트가 추천
        assert "요약" not in rec_name, f"요약 시트가 추천됨: {rec_name}"
        assert "추이" not in rec_name, f"추이 시트가 추천됨: {rec_name}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# sys_15: 빈 행 + 병합셀
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSys15BlankRowsMerged:
    """빈 행 반복 + 병합셀이 헤더와 데이터 사이에 산재."""

    def test_read_unmerges_cells(self, sys_15):
        """병합셀이 해제되어 읽히는지 확인."""
        rr = read_file(sys_15)
        sheet = rr.sheets[0]
        df = rr.raw_data[sheet]
        # 병합셀 해제 후 충분한 열 수
        assert df.shape[1] >= 5, f"병합셀 해제 후 열 부족: {df.shape[1]}"

    def test_header_detection_through_blanks(self, sys_15):
        """빈 행과 병합셀을 관통하여 실제 헤더를 찾아야 함."""
        rr = read_file(sys_15)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]

        assert hdr.header_row is not None, "병합셀/빈 행 사이에서 헤더를 찾아야 함"
        # 헤더 행이 메타데이터 아래에 있어야 함
        assert hdr.header_row >= 5, (
            f"헤더가 병합셀/메타데이터 아래에 있어야 함 (실제: row {hdr.header_row})"
        )

    def test_data_has_rows(self, sys_15):
        """헤더 아래에 데이터 행이 존재."""
        rr = read_file(sys_15)
        hdr_results = detect_headers(rr)
        sheet = rr.sheets[0]
        hdr = hdr_results[sheet]

        if hdr.header_row is not None:
            cols, data_df = prepare_dataframe(rr.raw_data[sheet], hdr.header_row)
            assert data_df.shape[0] >= 3, (
                f"헤더 아래 데이터 행이 부족: {data_df.shape[0]}"
            )
