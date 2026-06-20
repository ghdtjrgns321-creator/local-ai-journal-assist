"""L1 data-quality rule track (L1-01~L1-03).

Why: 후속 탐지(B·C 레이어)의 전제조건 검증.
     차대변 균형·필수필드 존재·계정 유효성을 행 단위 score로 산출.
     ISA 240 §32 / K-SOX §8①1호 근거.
"""

from __future__ import annotations

import re
import time

import pandas as pd

from config.settings import AuditSettings, get_schema
from src.detection.base import BaseDetector, DetectionResult, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.explanation_schema import RuleExplanation

_INTEGERISH_ACCOUNT_RE = re.compile(r"^[+-]?\d+\.0+$")

_L102_CAT1_FIELDS = frozenset(
    {"document_id", "gl_account", "debit_amount", "credit_amount", "posting_date"}
)
_L102_CAT2_FIELDS = frozenset(
    {"company_code", "fiscal_year", "fiscal_period", "document_date", "document_type"}
)

INTEGRITY_RULE_EXPLANATIONS: dict[str, RuleExplanation] = {
    "L1-01": RuleExplanation(
        principle="Journal entries should preserve debit and credit balance by document.",
        violation_reason=(
            "The document-level debit and credit totals differ beyond the configured "
            "rounding tolerance."
        ),
        audit_next_action=(
            "Recalculate the entry, inspect correction or reversal evidence, and confirm "
            "whether the imbalance is a posting error or permitted rounding difference."
        ),
        reference="PCAOB AS 1105; ISA 240",
    ),
    "L1-02": RuleExplanation(
        principle="Required ledger fields must be complete enough to support audit evidence.",
        violation_reason="One or more required source fields are null or blank on the row.",
        audit_next_action=(
            "Trace the missing field to source documentation or system logs and decide "
            "whether downstream rule results are evidence-limited."
        ),
        reference="PCAOB AS 1105; ISA 500",
    ),
    "L1-03": RuleExplanation(
        principle="Posted accounts should be valid under the chart of accounts.",
        violation_reason=(
            "The posted account is absent from, malformed against, or reserved in the CoA."
        ),
        audit_next_action=(
            "Confirm the account against the approved CoA, investigate mapping changes, "
            "and inspect high-amount or manual context first."
        ),
        reference="PCAOB AS 1105; ISA 315",
    ),
}


def _normalize_account_code(value: object) -> str:
    """Normalize account-code formatting artifacts before CoA checks."""
    if pd.isna(value):
        return ""

    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    if _INTEGERISH_ACCOUNT_RE.fullmatch(text):
        return text.split(".", 1)[0]
    return text


def _missing_required_mask(series: pd.Series) -> pd.Series:
    """Treat NULL and blank strings as missing required values."""
    missing = series.isna()
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        missing = missing | series.astype("string").str.strip().fillna("").eq("")
    return missing


# ── IntegrityDetector ──────────────────────────────────────────


class IntegrityDetector(BaseDetector):
    """L1-01~L1-03: 전표 데이터 자체의 신뢰성 확보.

    Args:
        settings: 감사 설정 (None이면 기본 싱글톤)
        tolerance: L1-01 차대변 불일치 허용 오차 (기본 1.0원)
        chart_of_accounts: L1-03 유효 계정 집합 (None이면 설정/데이터에서 자동 로드)
    """

    def __init__(
        self,
        settings: AuditSettings | None = None,
        tolerance: float | None = None,
        chart_of_accounts: set[str] | None = None,
        schema: dict | None = None,
        audit_rules: dict | None = None,
    ) -> None:
        super().__init__(settings)
        self._tolerance = tolerance if tolerance is not None else self._settings.balance_tolerance
        if chart_of_accounts is not None:
            self._coa = {
                normalized
                for normalized in (_normalize_account_code(code) for code in chart_of_accounts)
                if normalized
            }
        else:
            self._coa = self._load_coa()
        self._schema = schema or get_schema()
        self._audit_rules = audit_rules or self._load_audit_rules()

    def _load_audit_rules(self) -> dict:
        try:
            from config.settings import get_audit_rules

            return get_audit_rules()
        except Exception as exc:
            self._logger.warning("audit_rules.yaml 로드 실패: %s", exc)
            return {}

    def _load_coa(self) -> set[str] | None:
        """settings.chart_of_accounts_path에서 CoA 로드. 없으면 None."""
        path = self._settings.chart_of_accounts_path
        if not path:
            return None
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            self._logger.warning("CoA 파일 미존재: %s — L1-03 skip", path)
            return None
        # Why: 1열 텍스트 파일 또는 CSV (gl_account 컬럼) 지원
        try:
            if p.suffix == ".csv":
                coa_df = pd.read_csv(p, dtype=str)
                col = "gl_account" if "gl_account" in coa_df.columns else coa_df.columns[0]
                return {code for code in coa_df[col].map(_normalize_account_code) if code}
            else:
                return {
                    code
                    for code in (
                        _normalize_account_code(line) for line in p.read_text().splitlines()
                    )
                    if code
                }
        except Exception as e:
            self._logger.warning("CoA 로드 실패: %s — L1-03 skip", e)
            return None

    @property
    def track_name(self) -> str:
        return "layer_a"

    # ── 오케스트레이션 ─────────────────────────────────────────

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """L1-01~L1-03 순차 실행, 결과 통합."""
        t0 = time.monotonic()
        warnings: list[str] = []
        n = len(df)

        # Why: 빈 DF면 ValueError, 컬럼 누락은 경고만
        missing = validate_input(df, ["document_id", "debit_amount", "credit_amount"])
        if missing:
            warnings.append(f"컬럼 누락으로 일부 룰 제한: {missing}")

        # Why: 룰별 try/except 격리 — 한 룰 실패해도 나머지 계속
        rules = [
            ("L1-01", self._a01_unbalanced_entry),
            ("L1-02", self._a02_missing_required),
            ("L1-03", self._a03_invalid_account),
        ]
        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, method in rules:
            try:
                result = method(df)
                if result is not None:
                    rule_results[rule_id] = result
                else:
                    skipped.append(rule_id)
            except Exception as e:
                self._logger.warning("룰 %s 실행 실패: %s", rule_id, e)
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {e}")

        # Why: details DF — 행×룰 매트릭스, score = (severity/5) × flagged
        details_dict: dict[str, pd.Series] = {}
        rule_breakdowns: dict[str, object] = {}
        row_annotations: dict[str, object] = {}
        for rule_id, flagged in rule_results.items():
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            if score_series is not None:
                score = pd.Series(score_series, index=df.index).fillna(0.0).astype(float)
            else:
                score = flagged * (SEVERITY_MAP[rule_id] / 5)
            details_dict[rule_id] = score
            breakdown = flagged.attrs.get("breakdown") if hasattr(flagged, "attrs") else None
            if breakdown:
                rule_breakdowns[rule_id] = breakdown
            annotations = (
                flagged.attrs.get("row_annotations") if hasattr(flagged, "attrs") else None
            )
            if annotations:
                row_annotations[rule_id] = annotations

        details = pd.DataFrame(details_dict, index=df.index).fillna(0.0)

        # Why: 행별 종합 = max (무결성은 "가장 심각한 위반"이 위험도 결정)
        #      columns=0이면 모든 룰 skip → 전 행 0.0
        if details.shape[1] == 0:
            scores = pd.Series(0.0, index=df.index)
        else:
            scores = details.max(axis=1)

        # RuleFlag 생성
        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int(flagged.sum()),
                total_count=n,
            )
            for rule_id, flagged in rule_results.items()
        ]

        flagged_indices = scores[scores > 0].index.tolist()

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata={
                "elapsed": round(time.monotonic() - t0, 6),
                "skipped_rules": skipped,
                "rule_breakdowns": rule_breakdowns,
                "row_annotations": row_annotations,
            },
            warnings=warnings,
        )

    # ── L1-01: 차대변 균형 ──────────────────────────────────────

    def _a01_unbalanced_entry(self, df: pd.DataFrame) -> pd.Series | None:
        """document_id별 차대변 합 비교. 불일치 전표의 모든 행을 플래그."""
        if "document_id" not in df.columns:
            self._logger.info("document_id 컬럼 부재 — L1-01 건너뜀")
            return None

        debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
        credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
        diff = debit - credit

        # Why: groupby()는 NaN 키를 기본 drop → 해당 행 누락 방지
        #      NaN document_id는 고유 더미 키로 개별 행 취급
        safe_doc_id = df["document_id"].copy()
        nan_mask = safe_doc_id.isna()
        if nan_mask.any():
            safe_doc_id.loc[nan_mask] = "_nan_" + nan_mask[nan_mask].index.astype(str)

        doc_diff = diff.groupby(safe_doc_id).transform("sum")
        debit_sum = debit.groupby(safe_doc_id).transform("sum").abs()
        credit_sum = credit.groupby(safe_doc_id).transform("sum").abs()
        imbalance_amount = doc_diff.abs()
        flagged_mask = imbalance_amount > self._tolerance

        score_series = pd.Series(0.0, index=df.index, dtype="float64")
        score_series.loc[flagged_mask] = 1.0

        result = flagged_mask.astype(float)
        result.attrs["score_series"] = score_series
        result.attrs["breakdown"] = {
            "flagged_rows": int(flagged_mask.sum()),
            "flagged_docs": _nunique_documents(df, flagged_mask),
            "max_imbalance_amount": float(imbalance_amount.loc[flagged_mask].max())
            if flagged_mask.any()
            else 0.0,
        }
        row_annotations: dict[object, dict[str, object]] = {}
        for idx in df.index[flagged_mask]:
            row_annotations[idx] = {
                "imbalance_amount": float(imbalance_amount.loc[idx]),
                "debit_sum": float(debit_sum.loc[idx]),
                "credit_sum": float(credit_sum.loc[idx]),
            }
        result.attrs["row_annotations"] = row_annotations
        return result

    # ── L1-02: 필수필드 누락 ────────────────────────────────────

    def _a02_missing_required(self, df: pd.DataFrame) -> pd.Series:
        """schema.yaml required=true 컬럼 중 NULL 존재 시 플래그.

        Why: L1은 파이프라인 gate (컬럼 존재·타입), L1-02는 행 단위 NULL fallback.
             정상 흐름에서 L1-02 플래그 = 0이 기대값.
        """
        try:
            required_cols = [
                col["name"] for col in self._schema.get("columns", []) if col.get("required")
            ]
        except Exception as e:
            self._logger.warning("schema.yaml 로드 실패: %s — 기본 필수 컬럼 사용", e)
            required_cols = [
                "document_id",
                "company_code",
                "fiscal_year",
                "fiscal_period",
                "posting_date",
                "document_date",
                "gl_account",
                "debit_amount",
                "credit_amount",
                "document_type",
            ]

        category_by_field = {field: 1 for field in _L102_CAT1_FIELDS}
        category_by_field.update({field: 2 for field in _L102_CAT2_FIELDS})
        check_cols = [c for c in required_cols if c in df.columns and c in category_by_field]
        if not check_cols:
            return pd.Series(0.0, index=df.index)

        missing_matrix = pd.DataFrame(
            {col: _missing_required_mask(df[col]) for col in check_cols},
            index=df.index,
        )
        missing_count = missing_matrix.sum(axis=1)
        flagged_mask = missing_count > 0

        score_series = pd.Series(0.0, index=df.index, dtype="float64")
        score_series.loc[flagged_mask] = 1.0
        row_annotations: dict[object, dict[str, object]] = {}
        for idx in df.index[flagged_mask]:
            missing_fields = [col for col in check_cols if bool(missing_matrix.at[idx, col])]
            missing_category = min(category_by_field[col] for col in missing_fields)
            row_annotations[idx] = {
                "missing_fields": missing_fields,
                "missing_category": int(missing_category),
            }

        result = flagged_mask.astype(float)
        cat1_cols = [col for col in check_cols if category_by_field[col] == 1]
        cat2_cols = [col for col in check_cols if category_by_field[col] == 2]
        cat1_missing = (
            missing_matrix[cat1_cols].any(axis=1)
            if cat1_cols
            else pd.Series(False, index=df.index)
        )
        cat2_missing = (
            missing_matrix[cat2_cols].any(axis=1)
            if cat2_cols
            else pd.Series(False, index=df.index)
        )
        result.attrs["score_series"] = score_series
        result.attrs["breakdown"] = {
            "flagged_rows": int(flagged_mask.sum()),
            "missing_field_counts": {col: int(missing_matrix[col].sum()) for col in check_cols},
            "missing_category_counts": {
                "cat1": int((flagged_mask & cat1_missing).sum()),
                "cat2": int((flagged_mask & ~cat1_missing & cat2_missing).sum()),
            },
        }
        result.attrs["row_annotations"] = row_annotations
        return result

    # ── L1-03: 무효 계정 ────────────────────────────────────────

    def _a03_invalid_account(self, df: pd.DataFrame) -> pd.Series | None:
        """gl_account가 CoA에 없으면 플래그. CoA 미제공 시 skip."""
        if self._coa is None:
            self._logger.info("CoA 미제공 — L1-03 무효 계정 검사 건너뜀")
            return None

        if "gl_account" not in df.columns:
            self._logger.info("gl_account 컬럼 부재 — L1-03 건너뜀")
            return None

        # Why: astype(str)로 int/str 타입 통일 — schema는 int, CoA는 str일 수 있음
        normalized = df["gl_account"].map(_normalize_account_code)
        has_account = normalized.ne("")
        invalid_mask = has_account & ~normalized.isin(self._coa)
        result = invalid_mask.astype(float)

        if not invalid_mask.any():
            return result

        score_series = pd.Series(0.0, index=df.index, dtype="float64")
        score_series.loc[invalid_mask] = 1.0
        result.attrs["score_series"] = score_series
        result.attrs["breakdown"] = {
            "flagged_rows": int(invalid_mask.sum()),
            "flagged_docs": _nunique_documents(df, invalid_mask)
            if "document_id" in df.columns
            else 0,
        }

        row_annotations: dict[object, dict[str, object]] = {}
        for idx in df.index[invalid_mask]:
            row_annotations[idx] = {
                "gl_account": normalized.loc[idx],
            }
        result.attrs["row_annotations"] = row_annotations
        return result

def _nunique_documents(df: pd.DataFrame, mask: pd.Series) -> int:
    return int(df.loc[mask, "document_id"].dropna().nunique())
