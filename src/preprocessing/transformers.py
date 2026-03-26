"""커스텀 sklearn Transformer — NullFlagTransformer, SafePowerTransformer.

Why: 감사 데이터의 결측치는 정보를 담는다 (예: days_backdated NaN = "소급 없음").
NullFlagTransformer로 결측 여부를 별도 피처로 보존한다.
SafePowerTransformer는 상수 컬럼(std=0)에서 PowerTransformer 에러를 방지한다.
"""

from __future__ import annotations

import numpy as np
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
