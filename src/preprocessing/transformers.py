"""커스텀 sklearn Transformer — NullFlagTransformer, SafePowerTransformer.

Why: 감사 데이터의 결측치는 정보를 담는다 (예: days_backdated NaN = "소급 없음").
NullFlagTransformer로 결측 여부를 별도 피처로 보존한다.
SafePowerTransformer는 상수 컬럼(std=0)에서 PowerTransformer 에러를 방지한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import PowerTransformer


class NullFlagTransformer(BaseEstimator, TransformerMixin):
    """각 컬럼의 NaN 여부를 플래그 컬럼으로 추가 + fill_value 대체."""

    def __init__(self, fill_value: float = -99.0):
        self.fill_value = fill_value

    def fit(self, X, y=None):  # noqa: ARG002
        return self

    def transform(self, X):
        X = np.array(X, dtype=float)
        flags = np.isnan(X).astype(float)
        filled = np.where(np.isnan(X), self.fill_value, X)
        return np.hstack([filled, flags])

    def get_feature_names_out(self, input_features=None):
        if input_features is None:
            input_features = [f"x{i}" for i in range(self.n_features_in_)]
        flag_names = [f"{name}_is_null" for name in input_features]
        return np.array(list(input_features) + flag_names)


class SafePowerTransformer(BaseEstimator, TransformerMixin):
    """Yeo-Johnson PowerTransformer + 상수 컬럼 방어.

    Why: std=0인 컬럼에 PowerTransformer 적용 시 에러 발생.
    상수 컬럼은 변환하지 않고 원본을 유지한다.
    """

    def __init__(self):
        self._pt = PowerTransformer(method="yeo-johnson", standardize=True)
        self._constant_mask: np.ndarray | None = None

    def fit(self, X, y=None):  # noqa: ARG002
        X = np.array(X, dtype=float)
        stds = np.nanstd(X, axis=0)
        self._constant_mask = stds == 0

        non_const_cols = ~self._constant_mask
        if non_const_cols.any():
            self._pt.fit(X[:, non_const_cols])
        return self

    def transform(self, X):
        X = np.array(X, dtype=float)
        result = X.copy()
        non_const_cols = ~self._constant_mask
        if non_const_cols.any():
            result[:, non_const_cols] = self._pt.transform(X[:, non_const_cols])
        return result

    def get_feature_names_out(self, input_features=None):
        if input_features is None:
            input_features = [f"x{i}" for i in range(self.n_features_in_)]
        return np.array(list(input_features))


class SignedLogTransformer(BaseEstimator, TransformerMixin):
    """Apply sign(x) * log1p(abs(x)) to amount-like numeric features."""

    def fit(self, X, y=None):  # noqa: ARG002
        return self

    def transform(self, X):
        values = np.asarray(X, dtype=float)
        return np.sign(values) * np.log1p(np.abs(values))

    def get_feature_names_out(self, input_features=None):
        if input_features is None:
            input_features = [f"x{i}" for i in range(self.n_features_in_)]
        return np.array([f"{name}__signed_log" for name in input_features])


class NumericPolicyTransformer(BaseEstimator, TransformerMixin):
    """Deterministically choose standard or robust scaling per numeric column."""

    def __init__(
        self,
        skew_threshold: float = 2.0,
        outlier_ratio_threshold: float = 0.05,
        tail_ratio_threshold: float = 20.0,
        near_constant_epsilon: float = 1e-12,
    ):
        self.skew_threshold = skew_threshold
        self.outlier_ratio_threshold = outlier_ratio_threshold
        self.tail_ratio_threshold = tail_ratio_threshold
        self.near_constant_epsilon = near_constant_epsilon

    def fit(self, X, y=None):  # noqa: ARG002
        frame = _as_frame(X)
        self.input_features_ = list(frame.columns)
        self.policies_: dict[str, dict[str, float | str]] = {}
        for column in self.input_features_:
            values = pd.to_numeric(frame[column], errors="coerce").astype(float)
            policy = _select_numeric_policy(
                values,
                skew_threshold=float(self.skew_threshold),
                outlier_ratio_threshold=float(self.outlier_ratio_threshold),
                tail_ratio_threshold=float(self.tail_ratio_threshold),
                near_constant_epsilon=float(self.near_constant_epsilon),
            )
            self.policies_[column] = policy
        return self

    def transform(self, X):
        frame = _as_frame(X, columns=getattr(self, "input_features_", None))
        blocks = []
        for column in self.input_features_:
            policy = self.policies_[column]
            if policy["policy"] == "exclude":
                continue
            values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0).to_numpy(float)
            if policy["policy"] == "robust":
                center = float(policy["median"])
                scale = max(float(policy["iqr"]), float(self.near_constant_epsilon))
            else:
                center = float(policy["mean"])
                scale = max(float(policy["std"]), float(self.near_constant_epsilon))
            blocks.append((values - center) / scale)
        if not blocks:
            return np.empty((len(frame), 0), dtype=float)
        return np.vstack(blocks).T

    def get_feature_names_out(self, input_features=None):
        features = getattr(self, "input_features_", input_features or [])
        names = [
            f"{column}__{self.policies_[column]['policy']}_scaled"
            for column in features
            if self.policies_[column]["policy"] != "exclude"
        ]
        return np.array(names)


def _select_numeric_policy(
    values: pd.Series,
    *,
    skew_threshold: float,
    outlier_ratio_threshold: float,
    tail_ratio_threshold: float,
    near_constant_epsilon: float,
) -> dict[str, float | str]:
    clean = values.dropna().astype(float)
    if clean.empty:
        return {"policy": "exclude", "reason": "all_missing"}

    mean = float(clean.mean())
    std = float(clean.std(ddof=0))
    median = float(clean.median())
    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = float(q3 - q1)
    unique_count = int(clean.nunique(dropna=True))
    if unique_count <= 1 or std <= near_constant_epsilon:
        return {
            "policy": "exclude",
            "reason": "near_constant",
            "mean": mean,
            "std": std,
            "median": median,
            "iqr": iqr,
        }

    skew = float(clean.skew()) if len(clean) > 2 else 0.0
    lower = q1 - (1.5 * iqr)
    upper = q3 + (1.5 * iqr)
    outlier_ratio = float(((clean < lower) | (clean > upper)).mean()) if iqr > 0 else 0.0
    p95 = float(clean.quantile(0.95))
    p50_abs = max(abs(float(clean.quantile(0.50))), near_constant_epsilon)
    tail_ratio = abs(p95) / p50_abs
    use_robust = (
        abs(skew) >= skew_threshold
        or outlier_ratio >= outlier_ratio_threshold
        or tail_ratio >= tail_ratio_threshold
    )
    return {
        "policy": "robust" if use_robust else "standard",
        "reason": ("skew_or_outlier_tail" if use_robust else "approximately_symmetric"),
        "mean": mean,
        "std": std,
        "median": median,
        "iqr": iqr,
        "skew": skew,
        "outlier_ratio": outlier_ratio,
        "tail_ratio": tail_ratio,
    }


class RareCategoryOneHotEncoder(BaseEstimator, TransformerMixin):
    """One-hot encode train-fitted low-cardinality categories with rare grouping."""

    def __init__(self, min_count: int = 2):
        self.min_count = min_count

    def fit(self, X, y=None):  # noqa: ARG002
        frame = _as_frame(X)
        self.input_features_ = list(frame.columns)
        self.categories_: dict[str, list[str]] = {}
        for column in self.input_features_:
            counts = frame[column].astype("string").fillna("__MISSING__").value_counts()
            kept = sorted(str(value) for value, count in counts.items() if count >= self.min_count)
            self.categories_[column] = kept + ["__RARE__"]
        return self

    def transform(self, X):
        frame = _as_frame(X, columns=getattr(self, "input_features_", None))
        encoded = []
        for column in self.input_features_:
            values = frame[column].astype("string").fillna("__MISSING__")
            known = set(self.categories_[column]) - {"__RARE__"}
            values = values.where(values.isin(known), "__RARE__")
            for category in self.categories_[column]:
                encoded.append((values == category).astype(float).to_numpy())
        if not encoded:
            return np.empty((len(frame), 0), dtype=float)
        return np.vstack(encoded).T

    def get_feature_names_out(self, input_features=None):
        names = []
        for column in getattr(self, "input_features_", input_features or []):
            for category in self.categories_.get(column, []):
                names.append(f"{column}__{category}")
        return np.array(names)


class FrequencyCountEncoder(BaseEstimator, TransformerMixin):
    """Encode high-cardinality categoricals from train-fitted frequency/count maps."""

    def fit(self, X, y=None):  # noqa: ARG002
        frame = _as_frame(X)
        self.input_features_ = list(frame.columns)
        self.maps_: dict[str, dict[str, dict[str, float]]] = {}
        row_count = max(len(frame), 1)
        for column in self.input_features_:
            values = frame[column].astype("string").fillna("__MISSING__")
            counts = values.value_counts()
            self.maps_[column] = {
                "count": {str(key): float(value) for key, value in counts.items()},
                "freq": {str(key): float(value / row_count) for key, value in counts.items()},
            }
        return self

    def transform(self, X):
        frame = _as_frame(X, columns=getattr(self, "input_features_", None))
        encoded = []
        for column in self.input_features_:
            values = frame[column].astype("string").fillna("__MISSING__")
            count_map = self.maps_[column]["count"]
            freq_map = self.maps_[column]["freq"]
            encoded.append(values.map(freq_map).fillna(0.0).astype(float).to_numpy())
            encoded.append(values.map(count_map).fillna(0.0).astype(float).to_numpy())
        if not encoded:
            return np.empty((len(frame), 0), dtype=float)
        return np.vstack(encoded).T

    def get_feature_names_out(self, input_features=None):
        features = getattr(self, "input_features_", input_features or [])
        names = []
        for column in features:
            names.extend([f"{column}__freq", f"{column}__count"])
        return np.array(names)


def _as_frame(X, columns=None) -> pd.DataFrame:
    if isinstance(X, pd.DataFrame):
        frame = X.copy()
    else:
        frame = pd.DataFrame(X, columns=columns)
    if columns is not None:
        frame = frame.loc[:, list(columns)]
    return frame
