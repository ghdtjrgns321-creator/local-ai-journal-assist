"""L1/L3 data-quality rule track (L1-01~L1-03, L3-01).

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

_L102_FIELD_SCORES: dict[str, float] = {
    "document_id": 0.80,
    "gl_account": 0.74,
    "posting_date": 0.72,
    "debit_amount": 0.72,
    "credit_amount": 0.72,
    "company_code": 0.62,
    "fiscal_year": 0.56,
    "fiscal_period": 0.56,
    "document_type": 0.48,
    "document_date": 0.42,
}
_L102_DEFAULT_FIELD_SCORE = 0.40
_L102_MULTI_MISSING_STEP = 0.06
_L102_MAX_SCORE = 0.90

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
    "L3-01": RuleExplanation(
        principle="Account use should be consistent with the business process being recorded.",
        violation_reason=(
            "The account family or configured account rule does not match the recorded "
            "business process."
        ),
        audit_next_action=(
            "Review the process/account mapping, inspect supporting text and source "
            "evidence, and confirm whether classification is appropriate."
        ),
        reference="PCAOB AS 1105; ISA 240",
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
            self._logger.warning("audit_rules.yaml 로드 실패: %s — L3-01 skip 가능", exc)
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
            ("L3-01", self._l301_misclassified_account),
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
        base_amount = pd.concat([debit_sum, credit_sum], axis=1).max(axis=1).clip(lower=1.0)
        imbalance_amount = doc_diff.abs()
        imbalance_ratio = (imbalance_amount / base_amount).fillna(0.0).clip(lower=0.0)
        flagged_mask = imbalance_amount > self._tolerance

        score_series = pd.Series(0.0, index=df.index, dtype="float64")
        score_series.loc[flagged_mask] = imbalance_ratio.loc[flagged_mask].map(
            _l101_imbalance_score
        )

        result = flagged_mask.astype(float)
        band_series = imbalance_ratio.map(_l101_imbalance_band)
        result.attrs["score_series"] = score_series
        result.attrs["breakdown"] = {
            "flagged_rows": int(flagged_mask.sum()),
            "flagged_docs": _nunique_documents(df, flagged_mask),
            "score_bands": {
                band: int((flagged_mask & band_series.eq(band)).sum())
                for band in ("rounding_scale", "minor", "material", "severe")
            },
            "max_imbalance_ratio": float(imbalance_ratio.loc[flagged_mask].max())
            if flagged_mask.any()
            else 0.0,
        }
        row_annotations: dict[object, dict[str, object]] = {}
        for idx in df.index[flagged_mask]:
            row_annotations[idx] = {
                "bucket": str(band_series.loc[idx]),
                "score": float(score_series.loc[idx]),
                "imbalance_amount": float(imbalance_amount.loc[idx]),
                "imbalance_ratio": float(imbalance_ratio.loc[idx]),
                "debit_sum": float(debit_sum.loc[idx]),
                "credit_sum": float(credit_sum.loc[idx]),
                "base_amount": float(base_amount.loc[idx]),
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

        check_cols = [c for c in required_cols if c in df.columns]
        if not check_cols:
            return pd.Series(0.0, index=df.index)

        missing_matrix = pd.DataFrame(
            {col: _missing_required_mask(df[col]) for col in check_cols},
            index=df.index,
        )
        missing_count = missing_matrix.sum(axis=1)
        flagged_mask = missing_count > 0

        score_series = pd.Series(0.0, index=df.index, dtype="float64")
        row_annotations: dict[object, dict[str, object]] = {}
        for idx in df.index[flagged_mask]:
            missing_fields = [col for col in check_cols if bool(missing_matrix.at[idx, col])]
            field_scores = [
                _L102_FIELD_SCORES.get(col, _L102_DEFAULT_FIELD_SCORE) for col in missing_fields
            ]
            base_score = max(field_scores)
            score = min(
                _L102_MAX_SCORE,
                base_score + _L102_MULTI_MISSING_STEP * (len(missing_fields) - 1),
            )
            score_series.loc[idx] = score
            row_annotations[idx] = {
                "missing_fields": missing_fields,
                "missing_count": len(missing_fields),
                "max_field_score": float(base_score),
                "score": float(score),
            }

        result = flagged_mask.astype(float)
        result.attrs["score_series"] = score_series
        result.attrs["breakdown"] = {
            "flagged_rows": int(flagged_mask.sum()),
            "missing_field_counts": {col: int(missing_matrix[col].sum()) for col in check_cols},
            "score_bands": {
                "low": int((score_series.gt(0.0) & score_series.lt(0.50)).sum()),
                "medium": int((score_series.ge(0.50) & score_series.lt(0.70)).sum()),
                "high": int((score_series.ge(0.70) & score_series.lt(0.85)).sum()),
                "critical": int(score_series.ge(0.85).sum()),
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

        account_bucket = _l103_account_bucket(normalized, self._coa)
        score_series = account_bucket.map(_l103_base_score).astype(float)
        score_series = score_series.where(invalid_mask, 0.0)
        context_boost, context_reasons, document_amount = _l103_context_boost(
            df,
            invalid_mask,
        )
        score_series = (score_series + context_boost).clip(upper=0.90)

        score_bands = {
            bucket: int((invalid_mask & account_bucket.eq(bucket)).sum())
            for bucket in (
                "unknown_account",
                "unknown_account_family",
                "malformed_account",
                "placeholder_or_reserved",
            )
        }
        result.attrs["score_series"] = score_series
        result.attrs["breakdown"] = {
            "flagged_rows": int(invalid_mask.sum()),
            "flagged_docs": _nunique_documents(df, invalid_mask)
            if "document_id" in df.columns
            else 0,
            "score_bands": score_bands,
            "context_boosted_rows": int((invalid_mask & context_boost.gt(0)).sum()),
        }

        row_annotations: dict[object, dict[str, object]] = {}
        for idx in df.index[invalid_mask]:
            bucket = str(account_bucket.loc[idx])
            row_annotations[idx] = {
                "bucket": bucket,
                "reason_code": bucket,
                "score": float(score_series.loc[idx]),
                "base_score": float(_l103_base_score(bucket)),
                "context_boost": float(context_boost.loc[idx]),
                "context_reasons": context_reasons.get(idx, []),
                "gl_account": normalized.loc[idx],
                "document_amount": float(document_amount.loc[idx]),
            }
        result.attrs["row_annotations"] = row_annotations
        return result

    def _l301_misclassified_account(self, df: pd.DataFrame) -> pd.Series | None:
        """L3-01 계정-업무 프로세스 불일치 검토 신호."""
        if "business_process" not in df.columns:
            self._logger.info("business_process 컬럼 부재 — L3-01 건너뜀")
            return None
        if "gl_account" not in df.columns and not _has_any_column(
            df, ("account_category", "account_group")
        ):
            self._logger.info("계정 분류 컬럼 부재 — L3-01 건너뜀")
            return None

        cfg = _l301_config(self._audit_rules)
        if not cfg.get("enabled", True):
            return None

        process = df["business_process"].map(_normalize_key)
        category = _resolve_account_category(df, cfg, self._audit_rules)
        valid = process.ne("") & category.ne("")
        normalized_account = pd.Series("", index=df.index, dtype="object")

        if "gl_account" in df.columns:
            normalized_account = df["gl_account"].map(_normalize_account_code)
            valid = valid & normalized_account.ne("")
            if self._coa is not None:
                valid = valid & normalized_account.isin(self._coa)
        missing_context = process.eq("") | category.eq("") | normalized_account.eq("")
        invalid_account_excluded = pd.Series(False, index=df.index)
        if "gl_account" in df.columns and self._coa is not None:
            invalid_account_excluded = (
                process.ne("")
                & category.ne("")
                & normalized_account.ne("")
                & ~normalized_account.isin(self._coa)
            )

        denied_accounts = _process_account_match(
            process,
            normalized_account,
            cfg.get("process_denied_accounts", {}),
            default=False,
        )
        disallowed = _process_category_match(
            process,
            category,
            cfg.get("process_disallowed_categories", {}),
            default=False,
        )
        # Why: exact denied-account 목록과 disallowed-category는 같은 정책을 두 계정
        #      코드체계로 표현한 것(예: O2C에 expense 불허). 데이터가 exact 목록과 다른
        #      자리수(4자리 6300 등)를 쓰면 exact는 놓치므로 category도 함께 적용한다.
        #      exact가 score 우선(0.65>0.45)이라 중복 점수 없음. 과거 ~account_configured
        #      억제는 denied 목록이 설정됐다는 이유만으로 category를 봉쇄해 L3-01을 전
        #      프로세스 no-op(emitted 0)으로 만들었다. 정상 v29 5개 프로세스 모두
        #      disallowed-category 위반 0건 측정 → category 활성화 시 과탐 0.
        category_mismatch = disallowed
        allowed_keywords = _process_keyword_match(
            process,
            _combine_text_columns(df, ("line_text", "header_text")),
            cfg.get("process_allowed_keywords", {}),
        )
        strict_mismatch = pd.Series(False, index=df.index)

        if bool(cfg.get("strict_allowed_categories", False)):
            allowed = _process_category_match(
                process,
                category,
                cfg.get("process_allowed_categories", {}),
                default=True,
            )
            strict_mismatch = ~allowed

        raw_disallowed = denied_accounts | category_mismatch | strict_mismatch
        keyword_suppressed = valid & raw_disallowed & allowed_keywords
        flagged_mask = valid & raw_disallowed & ~allowed_keywords
        score_series = pd.Series(0.0, index=df.index)
        exact_mask = flagged_mask & denied_accounts
        category_mask = flagged_mask & ~denied_accounts & category_mismatch
        strict_mask = flagged_mask & ~denied_accounts & ~category_mismatch & strict_mismatch
        score_series.loc[exact_mask] = 0.65
        score_series.loc[category_mask] = 0.45
        score_series.loc[strict_mask] = 0.40

        reason_counts = {
            "exact_denied_account": int(exact_mask.sum()),
            "category_mismatch": int(category_mask.sum()),
            "strict_allowed_category_mismatch": int(strict_mask.sum()),
        }
        reason_counts = {key: value for key, value in reason_counts.items() if value > 0}
        result = flagged_mask.astype(float)
        breakdown = {
            "flagged_rows": int(flagged_mask.sum()),
            "exact_denied_rows": int(exact_mask.sum()),
            "category_mismatch_rows": int(category_mask.sum()),
            "strict_allowed_mismatch_rows": int(strict_mask.sum()),
            "keyword_suppressed_rows": int(keyword_suppressed.sum()),
            "invalid_account_excluded_rows": int(invalid_account_excluded.sum()),
            "missing_context_rows": int(missing_context.sum()),
            "reason_counts": reason_counts,
        }
        if "document_id" in df.columns:
            breakdown.update(
                {
                    "exact_denied_docs": _nunique_documents(df, exact_mask),
                    "category_mismatch_docs": _nunique_documents(df, category_mask),
                    "strict_allowed_mismatch_docs": _nunique_documents(df, strict_mask),
                    "keyword_suppressed_docs": _nunique_documents(df, keyword_suppressed),
                }
            )

        row_annotations: dict[int, dict[str, object]] = {}
        for idx in df.index[flagged_mask]:
            matched_reasons: list[str] = []
            if bool(denied_accounts.loc[idx]):
                matched_reasons.append("exact_denied_account")
            if bool(category_mismatch.loc[idx]):
                matched_reasons.append("category_mismatch")
            if bool(strict_mismatch.loc[idx]):
                matched_reasons.append("strict_allowed_category_mismatch")
            reason_code = matched_reasons[0] if matched_reasons else "category_mismatch"
            row_annotations[int(idx)] = {
                "reason_code": reason_code,
                "matched_reason_codes": matched_reasons,
                "score": float(score_series.loc[idx]),
                "business_process": process.loc[idx],
                "gl_account": normalized_account.loc[idx],
                "account_category": category.loc[idx],
                "keyword_suppressed": False,
            }
        result.attrs["score_series"] = score_series
        result.attrs["breakdown"] = breakdown
        result.attrs["row_annotations"] = row_annotations
        return result


def _l101_imbalance_score(ratio: float) -> float:
    """Map document imbalance ratio to a PHASE1 signal score."""
    if ratio <= 0.001:
        return 0.15
    if ratio <= 0.01:
        return 0.30
    if ratio <= 0.05:
        return 0.65
    return 0.90


def _l101_imbalance_band(ratio: float) -> str:
    if ratio <= 0.001:
        return "rounding_scale"
    if ratio <= 0.01:
        return "minor"
    if ratio <= 0.05:
        return "material"
    return "severe"


def _l103_account_bucket(accounts: pd.Series, coa: set[str]) -> pd.Series:
    coa_values = [code for code in coa if code]
    coa_first_digits = {code[0] for code in coa_values if code[:1].isdigit()}
    numeric_coa_count = sum(1 for code in coa_values if code.isdigit())
    numeric_coa_share = numeric_coa_count / max(len(coa_values), 1)
    numeric_coa = numeric_coa_share >= 0.80

    bucket = pd.Series("unknown_account", index=accounts.index, dtype="object")
    placeholder = accounts.map(_l103_is_placeholder_account)
    bucket.loc[placeholder] = "placeholder_or_reserved"

    if numeric_coa:
        malformed = accounts.ne("") & ~accounts.str.fullmatch(r"\d+")
        bucket.loc[malformed & ~placeholder] = "malformed_account"

    if coa_first_digits:
        family_unknown = (
            accounts.ne("")
            & accounts.str[:1].str.isdigit()
            & ~accounts.str[:1].isin(coa_first_digits)
        )
        bucket.loc[family_unknown & ~placeholder] = "unknown_account_family"
    return bucket


def _l103_is_placeholder_account(account: object) -> bool:
    text = str(account).strip()
    if not text:
        return False
    if text in {"0000", "000000", "777777", "888888", "9999", "999999"}:
        return True
    return text.isdigit() and len(text) >= 4 and len(set(text)) == 1


def _l103_base_score(bucket: str) -> float:
    if bucket == "placeholder_or_reserved":
        return 0.80
    if bucket == "malformed_account":
        return 0.75
    if bucket == "unknown_account_family":
        return 0.70
    return 0.60


def _l103_context_boost(
    df: pd.DataFrame,
    invalid_mask: pd.Series,
) -> tuple[pd.Series, dict[object, list[str]], pd.Series]:
    boost = pd.Series(0.0, index=df.index, dtype="float64")
    reasons: dict[object, list[str]] = {idx: [] for idx in df.index[invalid_mask]}
    document_amount = _document_amount(df)

    if invalid_mask.any():
        nonzero_amount = document_amount[document_amount > 0]
        if len(nonzero_amount) >= 10:
            high_cutoff = float(nonzero_amount.quantile(0.90))
            extreme_cutoff = float(nonzero_amount.quantile(0.99))
            high_amount = invalid_mask & document_amount.ge(high_cutoff)
            extreme_amount = invalid_mask & document_amount.ge(extreme_cutoff)
            boost.loc[high_amount] += 0.05
            boost.loc[extreme_amount] += 0.05
            for idx in df.index[high_amount]:
                reasons[idx].append("high_document_amount")
            for idx in df.index[extreme_amount]:
                reasons[idx].append("extreme_document_amount")

    manual = _manual_context(df) & invalid_mask
    period_end = _period_end_context(df) & invalid_mask
    boost.loc[manual] += 0.05
    boost.loc[period_end] += 0.05
    for idx in df.index[manual]:
        reasons[idx].append("manual_or_adjustment_context")
    for idx in df.index[period_end]:
        reasons[idx].append("period_end_context")
    return boost.clip(upper=0.20), reasons, document_amount


def _document_amount(df: pd.DataFrame) -> pd.Series:
    zero = pd.Series(0.0, index=df.index)
    debit = pd.to_numeric(df.get("debit_amount", zero), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df.get("credit_amount", zero), errors="coerce").fillna(0.0).abs()
    line_amount = pd.concat([debit, credit], axis=1).max(axis=1)
    if "document_id" not in df.columns:
        return line_amount

    safe_doc_id = df["document_id"].copy()
    nan_mask = safe_doc_id.isna()
    if nan_mask.any():
        safe_doc_id.loc[nan_mask] = "_nan_" + nan_mask[nan_mask].index.astype(str)
    debit_sum = debit.groupby(safe_doc_id).transform("sum")
    credit_sum = credit.groupby(safe_doc_id).transform("sum")
    return pd.concat([debit_sum, credit_sum, line_amount], axis=1).max(axis=1)


def _manual_context(df: pd.DataFrame) -> pd.Series:
    combined = pd.Series("", index=df.index, dtype="object")
    for column in ("source", "document_type", "entry_type"):
        if column in df.columns:
            combined = (combined + " " + df[column].map(_normalize_text)).str.strip()
    pattern = r"\b(?:manual|adjust|adjustment|je|mnl|수기|조정)\b"
    return combined.str.contains(pattern, regex=True, na=False)


def _period_end_context(df: pd.DataFrame) -> pd.Series:
    if "posting_date" not in df.columns:
        return pd.Series(False, index=df.index)
    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    return dates.notna() & ((dates.dt.days_in_month - dates.dt.day) <= 2)


def _has_any_column(df: pd.DataFrame, columns: tuple[str, ...]) -> bool:
    return any(col in df.columns for col in columns)


def _nunique_documents(df: pd.DataFrame, mask: pd.Series) -> int:
    return int(df.loc[mask, "document_id"].dropna().nunique())


def _l301_config(audit_rules: dict | None) -> dict:
    rules = audit_rules or {}
    patterns = rules.get("patterns", {}) if isinstance(rules.get("patterns"), dict) else {}
    cfg = rules.get("l3_01_misclassified_account")
    if cfg is None:
        cfg = patterns.get("l3_01_misclassified_account", {})
    return cfg if isinstance(cfg, dict) else {}


def _normalize_key(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    return re.sub(r"\s+", " ", text)


def _resolve_account_category(
    df: pd.DataFrame,
    cfg: dict,
    audit_rules: dict | None,
) -> pd.Series:
    category = pd.Series("", index=df.index, dtype="object")
    for col in ("account_category", "account_group"):
        if col not in df.columns:
            continue
        normalized = df[col].map(_normalize_key)
        category = category.where(category.ne(""), normalized)

    if "gl_account" not in df.columns:
        return category

    prefixes = cfg.get("account_category_prefixes")
    if not isinstance(prefixes, dict):
        prefixes = (audit_rules or {}).get("coa_category_prefixes", {})
    inferred = _infer_category_from_prefix(df["gl_account"], prefixes)
    return category.where(category.ne(""), inferred)


def _infer_category_from_prefix(accounts: pd.Series, prefixes: object) -> pd.Series:
    if not isinstance(prefixes, dict) or not prefixes:
        return pd.Series("", index=accounts.index, dtype="object")

    normalized_prefixes = [
        (_normalize_key(category), str(prefix))
        for category, values in prefixes.items()
        for prefix in _as_list(values)
        if str(prefix)
    ]
    normalized_prefixes.sort(key=lambda item: len(item[1]), reverse=True)

    def _match(value: object) -> str:
        account = _normalize_account_code(value)
        if not account:
            return ""
        for category, prefix in normalized_prefixes:
            if account.startswith(prefix):
                return category
        return ""

    return accounts.map(_match)


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _process_category_match(
    process: pd.Series,
    category: pd.Series,
    mapping: object,
    *,
    default: bool,
) -> pd.Series:
    result = pd.Series(default, index=process.index)
    if not isinstance(mapping, dict):
        return result

    normalized_mapping = {
        _normalize_key(proc): {_normalize_key(cat) for cat in _as_list(categories)}
        for proc, categories in mapping.items()
    }
    for proc, categories in normalized_mapping.items():
        if not proc or not categories:
            continue
        mask = process.eq(proc)
        result.loc[mask] = category.loc[mask].isin(categories)
    return result


def _process_account_match(
    process: pd.Series,
    account: pd.Series,
    mapping: object,
    *,
    default: bool,
) -> pd.Series:
    result = pd.Series(default, index=process.index)
    if not isinstance(mapping, dict):
        return result

    normalized_mapping = {
        _normalize_key(proc): {_normalize_account_code(value) for value in _as_list(accounts)}
        for proc, accounts in mapping.items()
    }
    for proc, accounts in normalized_mapping.items():
        if not proc or not accounts:
            continue
        mask = process.eq(proc)
        result.loc[mask] = account.loc[mask].isin(accounts)
    return result


def _process_presence_match(process: pd.Series, mapping: object) -> pd.Series:
    result = pd.Series(False, index=process.index)
    if not isinstance(mapping, dict):
        return result

    configured_processes = {
        _normalize_key(proc)
        for proc, accounts in mapping.items()
        if _normalize_key(proc) and _as_list(accounts)
    }
    if not configured_processes:
        return result
    return process.isin(configured_processes)


def _combine_text_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    combined = pd.Series("", index=df.index, dtype="object")
    for column in columns:
        if column not in df.columns:
            continue
        normalized = df[column].map(_normalize_text)
        combined = (combined + " " + normalized).str.strip()
    return combined


def _process_keyword_match(
    process: pd.Series,
    text: pd.Series,
    mapping: object,
) -> pd.Series:
    result = pd.Series(False, index=process.index)
    if not isinstance(mapping, dict):
        return result

    normalized_mapping = {
        _normalize_key(proc): [_normalize_text(keyword) for keyword in _as_list(keywords)]
        for proc, keywords in mapping.items()
    }
    for proc, keywords in normalized_mapping.items():
        keywords = [keyword for keyword in keywords if keyword]
        if not proc or not keywords:
            continue
        mask = process.eq(proc)
        if not mask.any():
            continue
        proc_text = text.loc[mask]
        result.loc[mask] = proc_text.map(
            lambda value: any(keyword in value for keyword in keywords),
        )
    return result
