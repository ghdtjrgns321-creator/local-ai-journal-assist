"""Layer A: 데이터 무결성 탐지 (L1-01~L1-03).

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

_INTEGERISH_ACCOUNT_RE = re.compile(r"^[+-]?\d+\.0+$")


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
                        _normalize_account_code(line)
                        for line in p.read_text().splitlines()
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
        for rule_id, flagged in rule_results.items():
            score = flagged * (SEVERITY_MAP[rule_id] / 5)
            details_dict[rule_id] = score

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
            metadata={"elapsed": round(time.monotonic() - t0, 6), "skipped_rules": skipped},
            warnings=warnings,
        )

    # ── L1-01: 차대변 균형 ──────────────────────────────────────

    def _a01_unbalanced_entry(self, df: pd.DataFrame) -> pd.Series | None:
        """document_id별 차대변 합 비교. 불일치 전표의 모든 행을 플래그."""
        if "document_id" not in df.columns:
            self._logger.info("document_id 컬럼 부재 — L1-01 건너뜀")
            return None

        diff = df["debit_amount"].fillna(0.0) - df["credit_amount"].fillna(0.0)

        # Why: groupby()는 NaN 키를 기본 drop → 해당 행 누락 방지
        #      NaN document_id는 고유 더미 키로 개별 행 취급
        safe_doc_id = df["document_id"].copy()
        nan_mask = safe_doc_id.isna()
        if nan_mask.any():
            safe_doc_id.loc[nan_mask] = "_nan_" + nan_mask[nan_mask].index.astype(str)

        doc_diff = diff.groupby(safe_doc_id).transform("sum")
        return (doc_diff.abs() > self._tolerance).astype(float)

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
                "document_id", "company_code", "fiscal_year",
                "posting_date", "document_date", "gl_account",
                "debit_amount", "credit_amount", "document_type",
            ]

        check_cols = [c for c in required_cols if c in df.columns]
        if not check_cols:
            return pd.Series(0.0, index=df.index)

        null_count = df[check_cols].isnull().sum(axis=1)
        return (null_count > 0).astype(float)

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
        return (has_account & ~normalized.isin(self._coa)).astype(float)

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

        denied_accounts = _process_account_match(
            process,
            normalized_account,
            cfg.get("process_denied_accounts", {}),
            default=False,
        )
        account_configured = _process_presence_match(
            process,
            cfg.get("process_denied_accounts", {}),
        )
        disallowed = _process_category_match(
            process,
            category,
            cfg.get("process_disallowed_categories", {}),
            default=False,
        )
        disallowed = denied_accounts | (~account_configured & disallowed)
        allowed_keywords = _process_keyword_match(
            process,
            _combine_text_columns(df, ("line_text", "header_text")),
            cfg.get("process_allowed_keywords", {}),
        )
        disallowed = disallowed & ~allowed_keywords

        if bool(cfg.get("strict_allowed_categories", False)):
            allowed = _process_category_match(
                process,
                category,
                cfg.get("process_allowed_categories", {}),
                default=True,
            )
            return (valid & (disallowed | ~allowed)).astype(float)

        return (valid & disallowed).astype(float)


def _has_any_column(df: pd.DataFrame, columns: tuple[str, ...]) -> bool:
    return any(col in df.columns for col in columns)


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
