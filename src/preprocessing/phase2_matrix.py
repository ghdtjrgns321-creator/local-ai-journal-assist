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

        self._signed_log = SignedLogTransformer()
        if self.amount_columns:
            self._signed_log.fit(df.loc[:, self.amount_columns])
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

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        blocks: list[pd.DataFrame] = []
        if self.amount_columns:
            values = self._signed_log.transform(
                df.reindex(columns=self.amount_columns).fillna(0.0),
            )
            names = self._signed_log.get_feature_names_out(self.amount_columns)
            blocks.append(pd.DataFrame(values, index=df.index, columns=names))
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
            values = df.reindex(columns=self.boolean_columns).fillna(False).astype(float)
            blocks.append(values)
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
        names.extend(f"has_{column}" for column in self.sparse_dropped_columns)
        return names

    def _build_output_feature_groups(self) -> dict[str, str]:
        groups: dict[str, str] = {}
        for column in self.amount_columns:
            group = "amount"
            for name in self._signed_log.get_feature_names_out([column]).tolist():
                groups[name] = group
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
            groups[f"{column}__count"] = "categorical"
        for column in self.boolean_columns:
            groups[column] = "boolean"
        for column in self.sparse_dropped_columns:
            groups[f"has_{column}"] = "indicator"
        return groups


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


def _is_amount_column(column: str) -> bool:
    name = str(column).lower()
    return "amount" in name or name.endswith("_amt") or name in {"debit", "credit"}
