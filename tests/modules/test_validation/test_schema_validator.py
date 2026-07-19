"""L1 구조 검증 — schema_validator.validate_schema() 테스트.

커버리지:
  - 정상/최소/빈 DataFrame
  - 필수 컬럼 누락, dtype 불일치, NaN 존재
  - 금액 음수 (ge=0 위반) → 경고
  - 권장 컬럼 부재, dtype 불일치, 고null
  - 피처 컬럼 존재 시 무시
  - column_stats 수집 검증
  - Int64 nullable 호환성
"""

import pandas as pd

from src.validation.schema_validator import (
    DETECTOR_FORBIDDEN_COLUMNS,
    GeneralLedgerSchema,
    _load_column_sets,
    strip_detector_forbidden_columns,
    validate_schema,
)


class TestSchemaYamlSync:
    """schema.yaml ↔ GeneralLedgerSchema 컬럼 동기화 검증."""

    def test_schema_model_columns_match_yaml(self) -> None:
        """GeneralLedgerSchema 필드 목록이 schema.yaml 전체 컬럼과 일치."""
        # Why: 이중 관리(정적 클래스 + YAML) 불일치 자동 감지
        _, yaml_columns = _load_column_sets()
        model_fields = set(GeneralLedgerSchema.__fields__.keys())
        assert model_fields == yaml_columns, f"불일치 컬럼: {model_fields ^ yaml_columns}"


class TestValidateSchema:
    """validate_schema() 정상·경계·에러 케이스."""

    def test_valid_dataframe(self, sv_valid_df: pd.DataFrame) -> None:
        """정상 — is_valid=True, errors 빈 리스트."""
        result = validate_schema(sv_valid_df)

        assert result.is_valid is True
        assert result.errors == []
        assert isinstance(result.column_stats, dict)
        assert len(result.column_stats) > 0

    def test_minimal_dataframe(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 10개만 → is_valid=True, 권장 컬럼 없어도 통과."""
        result = validate_schema(sv_minimal_df)

        assert result.is_valid is True
        assert result.errors == []

    def test_missing_required_column(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 컬럼(document_id) 누락 → is_valid=False."""
        df = sv_minimal_df.drop(columns=["document_id"])
        result = validate_schema(df)

        assert result.is_valid is False
        assert any(e["column"] == "document_id" for e in result.errors)

    def test_multiple_required_missing(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 컬럼 2개 동시 누락 → errors에 2건."""
        df = sv_minimal_df.drop(columns=["document_id", "gl_account"])
        result = validate_schema(df)

        assert result.is_valid is False
        missing_cols = {e["column"] for e in result.errors}
        assert "document_id" in missing_cols
        assert "gl_account" in missing_cols

    def test_wrong_dtype_required(self, sv_minimal_df: pd.DataFrame) -> None:
        """posting_date가 str → dtype 불일치 → is_valid=False."""
        df = sv_minimal_df.copy()
        df["posting_date"] = ["not-a-date"] * len(df)
        result = validate_schema(df)

        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_negative_amount_warning(self, sv_minimal_df: pd.DataFrame) -> None:
        """debit_amount 음수 → warnings에 포함, is_valid=True."""
        df = sv_minimal_df.copy()
        df.loc[0, "debit_amount"] = -500.0
        result = validate_schema(df)

        # Why: 금액 음수는 경고이지 치명적 에러가 아님
        assert result.is_valid is True
        assert len(result.warnings) > 0

    def test_nullable_required_nan(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 컬럼(fiscal_year)에 NaN → is_valid=False."""
        df = sv_minimal_df.copy()
        df.loc[0, "fiscal_year"] = pd.NA
        result = validate_schema(df)

        assert result.is_valid is False
        assert any(e["column"] == "fiscal_year" for e in result.errors)

    def test_optional_column_missing(self, sv_minimal_df: pd.DataFrame) -> None:
        """권장 컬럼(line_text) 없음 → is_valid=True, 에러 없음."""
        # sv_minimal_df에는 이미 line_text가 없음
        assert "line_text" not in sv_minimal_df.columns
        result = validate_schema(sv_minimal_df)

        assert result.is_valid is True

    def test_extra_feature_columns(self, sv_valid_df: pd.DataFrame) -> None:
        """피처 18개 컬럼 존재 → strict=False이므로 에러 없음."""
        assert "is_weekend" in sv_valid_df.columns
        assert "amount_zscore" in sv_valid_df.columns

        result = validate_schema(sv_valid_df)

        assert result.is_valid is True
        assert result.errors == []

    def test_column_stats_collected(self, sv_valid_df: pd.DataFrame) -> None:
        """column_stats에 null_rate, unique_count 존재."""
        result = validate_schema(sv_valid_df)

        # Why: schema.yaml에 정의된 컬럼만 stats에 포함 (피처 컬럼 제외)
        assert "document_id" in result.column_stats
        assert "posting_date" in result.column_stats

        stats = result.column_stats["document_id"]
        assert "null_rate" in stats
        assert "unique_count" in stats
        assert "dtype" in stats
        assert "total_count" in stats
        assert stats["null_rate"] == 0.0

    def test_high_null_rate_warning(self, sv_valid_df: pd.DataFrame) -> None:
        """권장 컬럼 null 90%+ → warnings에 high_null_rate."""
        df = sv_valid_df.copy()
        # Why: 5행 중 5행을 NaN으로 → 100% null
        df["created_by"] = pd.array([None] * len(df))
        result = validate_schema(df)

        assert result.is_valid is True
        assert any(
            w["column"] == "created_by" and w["issue"] == "high_null_rate" for w in result.warnings
        )

    def test_empty_dataframe(self, sv_empty_df: pd.DataFrame) -> None:
        """행 0건 → is_valid=True (구조는 올바름)."""
        result = validate_schema(sv_empty_df)

        assert result.is_valid is True
        assert result.errors == []

    def test_int64_nullable_compat(self, sv_minimal_df: pd.DataFrame) -> None:
        """Int64/str dtype 호환성 확인."""
        # Why: type_caster는 fiscal_year/fiscal_period를 Int64, gl_account를 str로 변환
        assert sv_minimal_df["fiscal_year"].dtype == pd.Int64Dtype()
        assert sv_minimal_df["fiscal_period"].dtype == pd.Int64Dtype()
        assert sv_minimal_df["gl_account"].dtype == object  # str

        result = validate_schema(sv_minimal_df)
        assert result.is_valid is True
        assert result.errors == []  # dtype 수용 확인

    def test_feature_columns_excluded_from_stats(self, sv_valid_df: pd.DataFrame) -> None:
        """column_stats에 피처 컬럼(is_weekend 등)이 포함되지 않음."""
        result = validate_schema(sv_valid_df)

        assert "is_weekend" not in result.column_stats
        assert "amount_zscore" not in result.column_stats
        assert "has_risk_keyword" not in result.column_stats


class TestClearingSuspenseOptionalColumns:
    """S-2 회귀 가드 — v2 ledger의 clearing/suspense 메타 5개 컬럼 L1 optional 통과."""

    NEW_OPTIONAL_COLUMNS: tuple[str, ...] = (
        "counterparty_type",
        "is_suspense_account",
        "amount_open",
        "is_cleared",
        "settlement_status",
    )

    def test_columns_registered_in_schema_yaml(self) -> None:
        """schema.yaml 전체 컬럼 집합에 5개 신규 optional 포함."""
        _, yaml_cols = _load_column_sets()
        for col in self.NEW_OPTIONAL_COLUMNS:
            assert col in yaml_cols, f"schema.yaml 누락: {col}"

    def test_columns_registered_in_pandera_model(self) -> None:
        """GeneralLedgerSchema 필드에 5개 신규 optional 포함."""
        model_fields = set(GeneralLedgerSchema.__fields__.keys())
        for col in self.NEW_OPTIONAL_COLUMNS:
            assert col in model_fields, f"GeneralLedgerSchema 누락: {col}"

    def test_validate_passes_with_clearing_columns(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 10개 + clearing 5개 → is_valid=True, errors 없음."""
        n = len(sv_minimal_df)
        df = sv_minimal_df.copy()
        df["counterparty_type"] = pd.array(
            ["External", "IntercompanyAffiliate", None, "External", "Subsidiary"][:n],
            dtype="string",
        )
        df["is_suspense_account"] = pd.array([False, True, None, False, True][:n], dtype="boolean")
        df["amount_open"] = [0.0, 12_345.67, None, 0.0, 99.5][:n]
        df["is_cleared"] = pd.array([True, False, None, True, False][:n], dtype="boolean")
        df["settlement_status"] = pd.array(
            ["cleared", "open", None, "cleared", "partial"][:n], dtype="string"
        )

        result = validate_schema(df)

        assert result.is_valid is True, f"errors: {result.errors}"
        # column_stats에 5개 컬럼 모두 수집되었는지 확인
        for col in self.NEW_OPTIONAL_COLUMNS:
            assert col in result.column_stats, f"column_stats 누락: {col}"

    def test_validate_passes_when_clearing_columns_absent(
        self, sv_minimal_df: pd.DataFrame
    ) -> None:
        """clearing 컬럼이 전혀 없어도 optional이므로 통과."""
        for col in self.NEW_OPTIONAL_COLUMNS:
            assert col not in sv_minimal_df.columns

        result = validate_schema(sv_minimal_df)

        assert result.is_valid is True
        assert result.errors == []


class TestDetectorForbiddenColumns:
    """H-3 회귀 가드 — DataSynth 메타데이터 컬럼이 detection으로 흘러가지 못하게."""

    EXPECTED_FORBIDDEN: frozenset[str] = frozenset(
        {
            "semantic_scenario_id",
            "mutation_type",
            "mutation_base_event_type",
            "mutation_mutated_field",
            "mutation_original_value",
            "mutation_mutated_value",
            "mutation_reason",
            "detection_surface_hints",
        }
    )

    def test_deny_list_contents_locked(self) -> None:
        """deny-list 8개 컬럼 정확 일치 — 누군가 임의로 빼지 못하게 고정."""
        assert DETECTOR_FORBIDDEN_COLUMNS == self.EXPECTED_FORBIDDEN

    def test_validate_schema_warns_on_forbidden_columns(self, sv_minimal_df: pd.DataFrame) -> None:
        """forbidden 컬럼 발견 → warnings에 detector_forbidden_column issue 추가, is_valid 유지."""
        df = sv_minimal_df.copy()
        df["semantic_scenario_id"] = ["SC01"] * len(df)
        df["mutation_type"] = ["substitution"] * len(df)

        result = validate_schema(df)

        # Why: 무해(detection이 미참조) 상태이므로 차단하지 않고 warning만.
        assert result.is_valid is True
        forbidden_warnings = [
            w for w in result.warnings if w.get("issue") == "detector_forbidden_column"
        ]
        cols = {w["column"] for w in forbidden_warnings}
        assert cols == {"semantic_scenario_id", "mutation_type"}

    def test_strip_removes_only_deny_list(self, sv_minimal_df: pd.DataFrame) -> None:
        """strip_detector_forbidden_columns()는 deny-list만 제거하고 나머지는 유지."""
        df = sv_minimal_df.copy()
        df["semantic_scenario_id"] = ["SC01"] * len(df)
        df["mutation_type"] = ["substitution"] * len(df)
        df["mutation_reason"] = ["fitting"] * len(df)
        original_cols = set(df.columns)

        cleaned, stripped = strip_detector_forbidden_columns(df)

        assert set(stripped) == {"semantic_scenario_id", "mutation_type", "mutation_reason"}
        assert set(cleaned.columns) == original_cols - set(stripped)

    def test_strip_noop_when_absent(self, sv_minimal_df: pd.DataFrame) -> None:
        """forbidden 컬럼 없음 → stripped 빈 리스트, df 그대로."""
        cleaned, stripped = strip_detector_forbidden_columns(sv_minimal_df)

        assert stripped == []
        assert set(cleaned.columns) == set(sv_minimal_df.columns)

    def test_no_detection_module_references_forbidden_columns(self) -> None:
        """src/detection/*.py 안에서 forbidden 컬럼명 문자열을 참조하지 않음.

        Why: AST/소스 레벨 회귀 가드. 새 룰을 만들면서 누군가
             df["mutation_type"] 같은 코드를 추가하면 즉시 실패한다.
        """
        import re
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        detection_dir = repo_root / "src" / "detection"
        assert detection_dir.is_dir(), f"detection 디렉터리 누락: {detection_dir}"

        offenders: list[tuple[str, str, int]] = []
        for py_file in detection_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for col in DETECTOR_FORBIDDEN_COLUMNS:
                # Why: 식별자 경계 + 따옴표/속성 접근까지 잡는 보수적 매칭.
                pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(col)}(?![A-Za-z0-9_])")
                for m in pattern.finditer(text):
                    line_no = text.count("\n", 0, m.start()) + 1
                    offenders.append((py_file.name, col, line_no))

        assert offenders == [], (
            f"detection 모듈이 deny-list 컬럼을 참조하고 있음 (라벨 누설 위험): {offenders}"
        )
