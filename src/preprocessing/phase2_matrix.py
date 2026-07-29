"""Reusable Phase 2 autoencoder matrix builder.

The builder fits all preprocessing state on the train split and reuses that
state for calibration/inference transforms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.preprocessing.data_stats import compute_feature_schema_version
from src.preprocessing.feature_quality import get_sparse_feature_thresholds
from src.preprocessing.phase2_plan import _validate_single_use_deny_columns
from src.preprocessing.transformers import (
    FrequencyCountEncoder,
    NumericPolicyTransformer,
    RareCategoryOneHotEncoder,
    SignedLogTransformer,
)


@dataclass
class Phase2AutoencoderMatrixBuilder:
    preprocessing_plan: Any
    rare_min_count: int = 2
    numeric_columns: list[str] = field(default_factory=list)
    amount_columns: list[str] = field(default_factory=list)
    general_numeric_columns: list[str] = field(default_factory=list)
    low_card_columns: list[str] = field(default_factory=list)
    high_card_columns: list[str] = field(default_factory=list)
    boolean_columns: list[str] = field(default_factory=list)
    boolean_missing_columns: list[str] = field(default_factory=list)
    numeric_missing_columns: list[str] = field(default_factory=list)
    sparse_dropped_columns: list[str] = field(default_factory=list)
    feature_names_: list[str] = field(default_factory=list)
    output_feature_groups_: dict[str, str] = field(default_factory=dict)
    schema_hash_: int = 0

    def fit(self, df: pd.DataFrame):
        decisions = _plan_decisions(self.preprocessing_plan)
        include = [
            decision
            for decision in decisions
            if decision.get("action") == "include" and decision.get("column") in df.columns
        ]
        _validate_single_use_deny_columns([decision["column"] for decision in include])
        sparse_columns = _detect_sparse_columns(df)
        self.sparse_dropped_columns = [
            decision["column"] for decision in include if decision["column"] in sparse_columns
        ]
        active = [
            decision
            for decision in include
            if decision["column"] not in self.sparse_dropped_columns
        ]
        self.numeric_columns = [d["column"] for d in active if d.get("role") == "numeric"]
        self.amount_columns = [
            column for column in self.numeric_columns if _is_amount_column(column)
        ]
        self.general_numeric_columns = [
            column for column in self.numeric_columns if column not in self.amount_columns
        ]
        self.low_card_columns = [d["column"] for d in active if d.get("role") == "categorical_low"]
        self.high_card_columns = [
            d["column"] for d in active if d.get("role") == "categorical_high"
        ]
        self.boolean_columns = [d["column"] for d in active if d.get("role") == "boolean"]
        # Why: 감사 데이터의 결측은 정보다. `approver_in_master` 는 승인자가 아예 없는
        #      전표에서 비는데(실측 r9: 결측 71.97% = approved_by 공란 72.08%),
        #      `fillna(False)` 만 하면 "승인 절차 없음"과 "승인자가 마스터에 없음"이
        #      같은 0 으로 뭉개진다. 감사에서 이 둘은 정반대 성격이다.
        #
        #      수치형도 같다. `p2_days_approval_minus_posting` 은 승인이 없으면 비는데
        #      `fillna(0.0)` 하면 "승인 없음"과 "당일 승인"이 같은 0 이 된다.
        #      `p2_approver_limit_amount` 는 "승인 불요"와 "한도 0원"이 같아진다.
        #      2026-07-29 이전에는 불리언에만 표식을 세워 반쪽이었다.
        #
        #      단, 결측을 뺀 값이 한 종류뿐이면 값 칸 자체가 이미 결측 여부를 담는다.
        #      그때 표식을 붙이면 완전히 같은 정보가 2칸이 되어 그 신호만 손실에서
        #      두 배 무거워진다. 실제로 값이 갈릴 때만 세운다.
        self.boolean_missing_columns = _columns_needing_missing_flag(df, self.boolean_columns)
        self.numeric_missing_columns = _columns_needing_missing_flag(df, self.numeric_columns)

        self._signed_log = SignedLogTransformer()
        # Why: 로그만 씌우면 스케일이 남는다. 100만원 → 13.8, 10억원 → 20.7 이라
        #      금액 칸 하나의 std 가 2 안팎(실측 lognormal σ=2 에서 1.97)이 되고,
        #      표준화된 수치형(std 1)·원-핫(std ≤ 0.5)과 같은 재구성 손실에 섞이면
        #      분산 기준 4배 이상을 혼자 먹는다.
        #      **평균은 빼지 않는다** — 부호 유지 로그에서 0 은 "금액 없음"이라는
        #      기준점이고 차변(+)/대변(-) 방향이 부호에 실려 있다. 중심을 옮기면
        #      둘 다 잃는다. 크기만 std 로 나눈다.
        self._amount_scales: dict[str, float] = {}
        if self.amount_columns:
            self._signed_log.fit(df.loc[:, self.amount_columns])
            spread = self._logged_amounts(df).std(ddof=0)
            self._amount_scales = {
                str(column): (float(value) if float(value) > 0 else 1.0)
                for column, value in spread.items()
            }
        self._numeric_policy = NumericPolicyTransformer()
        if self.general_numeric_columns:
            self._numeric_policy.fit(df.loc[:, self.general_numeric_columns])
        self._low_card_encoder = RareCategoryOneHotEncoder(min_count=self.rare_min_count)
        if self.low_card_columns:
            self._low_card_encoder.fit(df.loc[:, self.low_card_columns])
        self._high_card_encoder = FrequencyCountEncoder()
        if self.high_card_columns:
            self._high_card_encoder.fit(df.loc[:, self.high_card_columns])

        self.feature_names_ = list(self._build_feature_names())
        self.output_feature_groups_ = self._build_output_feature_groups()
        self.schema_hash_ = compute_feature_schema_version(
            pd.DataFrame(columns=self.feature_names_)
        )
        return self

    def _logged_amounts(self, df: pd.DataFrame) -> pd.DataFrame:
        """금액 칸을 부호 유지 로그로 변환한 프레임 (스케일 전 단계)."""
        values = self._signed_log.transform(
            df.reindex(columns=self.amount_columns).fillna(0.0),
        )
        names = self._signed_log.get_feature_names_out(self.amount_columns)
        return pd.DataFrame(values, index=df.index, columns=names)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        blocks: list[pd.DataFrame] = []
        if self.amount_columns:
            logged = self._logged_amounts(df)
            blocks.append(logged.div(pd.Series(self._amount_scales), axis=1))
        if self.general_numeric_columns:
            values = self._numeric_policy.transform(
                df.reindex(columns=self.general_numeric_columns).fillna(0.0),
            )
            names = self._numeric_policy.get_feature_names_out(self.general_numeric_columns)
            blocks.append(pd.DataFrame(values, index=df.index, columns=names))
        if self.low_card_columns:
            values = self._low_card_encoder.transform(df.reindex(columns=self.low_card_columns))
            names = self._low_card_encoder.get_feature_names_out()
            blocks.append(pd.DataFrame(values, index=df.index, columns=names))
        if self.high_card_columns:
            values = self._high_card_encoder.transform(df.reindex(columns=self.high_card_columns))
            names = self._high_card_encoder.get_feature_names_out()
            blocks.append(pd.DataFrame(values, index=df.index, columns=names))
        if self.boolean_columns:
            frame = df.reindex(columns=self.boolean_columns)
            blocks.append(frame.fillna(False).astype(float))
        missing_flag_columns = self.boolean_missing_columns + self.numeric_missing_columns
        if missing_flag_columns:
            flags = df.reindex(columns=missing_flag_columns).isna().astype(float)
            flags.columns = [f"{column}__missing" for column in missing_flag_columns]
            blocks.append(flags)
        for column in self.sparse_dropped_columns:
            present = (
                _not_empty(df[column]) if column in df.columns else pd.Series(False, index=df.index)
            )
            blocks.append(
                pd.DataFrame(
                    {f"has_{column}": present.astype(float).to_numpy()},
                    index=df.index,
                )
            )
        if not blocks:
            matrix = pd.DataFrame(index=df.index)
        else:
            matrix = pd.concat(blocks, axis=1)
        return matrix.reindex(columns=self.feature_names_, fill_value=0.0)

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(df).transform(df)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "numeric_columns": list(self.numeric_columns),
            "amount_columns": list(self.amount_columns),
            "general_numeric_columns": list(self.general_numeric_columns),
            "numeric_transform_policies": {
                key: dict(value)
                for key, value in getattr(self._numeric_policy, "policies_", {}).items()
            },
            "low_card_columns": list(self.low_card_columns),
            "high_card_columns": list(self.high_card_columns),
            "boolean_columns": list(self.boolean_columns),
            "boolean_missing_columns": list(self.boolean_missing_columns),
            "numeric_missing_columns": list(self.numeric_missing_columns),
            "amount_log_scales": dict(getattr(self, "_amount_scales", {})),
            "sparse_dropped_columns": list(self.sparse_dropped_columns),
            "feature_names": list(self.feature_names_),
            "feature_count": len(self.feature_names_),
            "output_feature_groups": dict(self.output_feature_groups_),
            "low_card_categories": {
                key: list(value)
                for key, value in getattr(self._low_card_encoder, "categories_", {}).items()
            },
            "high_card_encoder_columns": list(self.high_card_columns),
            "schema_hash": self.schema_hash_,
        }

    def _build_feature_names(self) -> list[str]:
        names: list[str] = []
        if self.amount_columns:
            names.extend(self._signed_log.get_feature_names_out(self.amount_columns).tolist())
        if self.general_numeric_columns:
            names.extend(
                self._numeric_policy.get_feature_names_out(self.general_numeric_columns).tolist()
            )
        if self.low_card_columns:
            names.extend(self._low_card_encoder.get_feature_names_out().tolist())
        if self.high_card_columns:
            names.extend(self._high_card_encoder.get_feature_names_out().tolist())
        names.extend(self.boolean_columns)
        names.extend(
            f"{column}__missing"
            for column in self.boolean_missing_columns + self.numeric_missing_columns
        )
        names.extend(f"has_{column}" for column in self.sparse_dropped_columns)
        return names

    def _build_output_feature_groups(self) -> dict[str, str]:
        groups: dict[str, str] = {}
        if self.amount_columns:
            for name in self._signed_log.get_feature_names_out(self.amount_columns).tolist():
                groups[name] = "amount"
        for column in self.general_numeric_columns:
            policy = getattr(self._numeric_policy, "policies_", {}).get(column, {})
            if policy.get("policy") == "exclude":
                continue
            for name in self._numeric_policy.get_feature_names_out([column]).tolist():
                groups[name] = "numeric"
        for name in self._low_card_encoder.get_feature_names_out().tolist():
            groups[name] = "categorical"
        for column in self.high_card_columns:
            groups[f"{column}__freq"] = "categorical"
        for column in self.boolean_columns:
            groups[column] = "boolean"
        for column in self.boolean_missing_columns + self.numeric_missing_columns:
            groups[f"{column}__missing"] = "indicator"
        for column in self.sparse_dropped_columns:
            groups[f"has_{column}"] = "indicator"
        return groups


def _columns_needing_missing_flag(df: pd.DataFrame, columns: list[str]) -> list[str]:
    """결측이 있고 값이 실제로 갈리는 칸 — 결측 표식이 정보를 더하는 경우만."""
    return [
        column
        for column in columns
        if column in df.columns
        and bool(df[column].isna().any())
        and int(df[column].nunique(dropna=True)) >= 2
    ]


def _plan_decisions(plan: Any) -> list[dict[str, Any]]:
    if hasattr(plan, "to_dict"):
        return list(plan.to_dict().get("decisions", []))
    return list(dict(plan).get("decisions", []))


def _detect_sparse_columns(df: pd.DataFrame) -> set[str]:
    sparse = set()
    for column, min_coverage in get_sparse_feature_thresholds().items():
        if column not in df.columns:
            continue
        if float(_not_empty(df[column]).mean()) < min_coverage:
            sparse.add(column)
    return sparse


def _not_empty(series: pd.Series) -> pd.Series:
    mask = series.notna()
    if pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
        mask = mask & series.astype("string").str.strip().ne("")
    return mask


# 이름에 amount 가 들어가도 통화 금액이 아닌 파생 지표들.
# Why: `_is_amount_column` 은 금액 칸에 부호 유지 로그를 씌우려고 있는데, z 점수·자릿수는
#      이미 변환된 값이라 로그를 또 씌우면 의미가 깨진다. 2026-07-29 실측에서
#      `amount_zscore__signed_log` · `amount_magnitude__signed_log` 로 잡혔다.
#
#      같은 날 PHASE2 입력이 허용 목록으로 바뀌면서 그 칸들은 입력에서 빠졌고, 현재
#      이 목록에 걸리는 칸은 0 건이다. 유지하는 것은 미래 파생 방어용이다 — 통화
#      금액인 `p2_approver_limit_amount` 는 정상적으로 금액으로 잡힌다.
_NON_CURRENCY_AMOUNT_TOKENS = (
    "zscore",
    "magnitude",
    "ratio",
    "bucket",
    "level",
    "count",
    "flag",
    # 금액의 자릿수 구조. `p2_amount_trailing_zeros` 는 0 의 개수(0~7)이지 금액이 아니다.
    "zeros",
    "digit",
)


def _is_amount_column(column: str) -> bool:
    name = str(column).lower()
    if any(token in name for token in _NON_CURRENCY_AMOUNT_TOKENS):
        return False
    return "amount" in name or name.endswith("_amt") or name in {"debit", "credit"}
