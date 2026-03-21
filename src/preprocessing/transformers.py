"""커스텀 sklearn Transformer.

Why: 비지도 Pipeline에서 회계 금액의 극단적 우측 꼬리 분포를 정규분포에
가깝게 변환해야 StandardScaler가 정상 작동한다.
NullFlagTransformer는 의미있는 결측(days_backdated 등)을 보존하면서
모델 입력으로 변환한다.
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin


class NullFlagTransformer(BaseEstimator, TransformerMixin):
    """결측 여부를 0/1 플래그 컬럼으로 추가하고, NaN을 fill_value로 대체.

    Why: days_backdated, first_digit 등 '의미있는 결측'은 결측 자체가
    정보이므로 플래그로 보존한다. SimpleImputer만 쓰면 이 정보가 소실됨.
    """

    def __init__(self, fill_value: float = -1.0):
        self.fill_value = fill_value

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        X = np.array(X, dtype=float)
        # 결측 플래그: 각 컬럼에 대해 NaN 여부 (n_samples, n_features)
        flags = np.isnan(X).astype(float)
        # NaN 대체
        filled = np.where(np.isnan(X), self.fill_value, X)
        # 원본 + 플래그 결합 (컬럼 수 2배)
        return np.hstack([filled, flags])

    def get_feature_names_out(self, input_features=None):
        if input_features is None:
            return None
        originals = list(input_features)
        flags = [f"{f}_is_null" for f in input_features]
        return np.array(originals + flags)


class SafePowerTransformer(BaseEstimator, TransformerMixin):
    """PowerTransformer(Yeo-Johnson) 래퍼 — 상수 컬럼/NaN에 안전.

    Why: 회계 금액(1만원~100억원) 극단적 우측 꼬리 분포를 정규분포에
    가깝게 변환한 후 StandardScaler를 적용해야 100억짜리 데이터가
    나머지를 0으로 압축하는 문제를 방지할 수 있다.
    Yeo-Johnson은 음수값(credit_amount)도 처리 가능.
    """

    def __init__(self):
        self._transformer = None
        self._constant_mask = None  # 상수 컬럼 마스크

    def fit(self, X, y=None):
        from sklearn.preprocessing import PowerTransformer

        X = np.array(X, dtype=float)
        n_features = X.shape[1] if X.ndim == 2 else 1
        if X.ndim == 1:
            X = X.reshape(-1, 1)

        # 상수 컬럼 감지: std == 0이면 PowerTransformer가 에러 발생
        self._constant_mask = np.nanstd(X, axis=0) == 0

        if not self._constant_mask.all():
            self._transformer = PowerTransformer(method="yeo-johnson")
            # 상수가 아닌 컬럼만 fit
            non_const = X[:, ~self._constant_mask]
            if non_const.shape[1] > 0:
                self._transformer.fit(non_const)

        self._n_features = n_features
        return self

    def transform(self, X):
        X = np.array(X, dtype=float)
        if X.ndim == 1:
            X = X.reshape(-1, 1)

        result = X.copy()
        if self._transformer is not None and not self._constant_mask.all():
            non_const = X[:, ~self._constant_mask]
            if non_const.shape[1] > 0:
                result[:, ~self._constant_mask] = self._transformer.transform(
                    non_const,
                )
        return result

    def get_feature_names_out(self, input_features=None):
        if input_features is not None:
            return np.array(input_features)
        return None
