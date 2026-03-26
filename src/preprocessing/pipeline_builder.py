"""Pipeline 조립 — XGB / VAE / IF 3개 Pipeline 생성.

Why: 모델 특성에 따라 전처리가 달라진다.
XGBoost는 스케일링 불필요+TargetEncoder, VAE/IF는 StandardScaler+고카디널리티 DROP.
"""

from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder, StandardScaler

from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.transformers import SafePowerTransformer
from src.preprocessing.vae_wrapper import VAEDetector

try:
    from sklearn.preprocessing import TargetEncoder
except ImportError:  # sklearn < 1.3
    TargetEncoder = None  # type: ignore[assignment,misc]

try:
    from xgboost import XGBClassifier
except ImportError:
    XGBClassifier = None  # type: ignore[assignment,misc]


def build_xgb_pipeline(groups: FeatureGroups) -> Pipeline:
    """XGBoost 지도학습 Pipeline 조립."""
    transformers = []
    if groups.numeric:
        transformers.append(("num", SimpleImputer(strategy="median"), groups.numeric))
    if groups.categorical_high and TargetEncoder is not None:
        transformers.append((
            "cat_high",
            Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", TargetEncoder()),
            ]),
            groups.categorical_high,
        ))
    if groups.categorical_low:
        transformers.append(("cat_low", _build_cat_low_transformer(), groups.categorical_low))
    if groups.boolean:
        transformers.append(("bool", "passthrough", groups.boolean))
    if groups.ordinal:
        transformers.append(("ord", _build_ordinal_encoder(groups.ordinal), groups.ordinal))

    preprocessor = ColumnTransformer(transformers, remainder="drop")
    return Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", XGBClassifier(use_label_encoder=False, eval_metric="logloss")),
    ])


def build_vae_pipeline(groups: FeatureGroups) -> Pipeline:
    """VAE 비지도 Pipeline 조립. 고카디널리티 범주형은 DROP."""
    preprocessor = _build_unsupervised_preprocessor(groups)
    return Pipeline([("preprocessor", preprocessor), ("detector", VAEDetector())])


def build_if_pipeline(groups: FeatureGroups) -> Pipeline:
    """Isolation Forest 비지도 Pipeline 조립."""
    preprocessor = _build_unsupervised_preprocessor(groups)
    return Pipeline([
        ("preprocessor", preprocessor),
        ("detector", IsolationForest(contamination=0.01, random_state=42)),
    ])


def build_all_pipelines(groups: FeatureGroups) -> dict[str, Pipeline]:
    """3개 Pipeline 일괄 생성."""
    return {
        "xgb": build_xgb_pipeline(groups),
        "vae": build_vae_pipeline(groups),
        "if": build_if_pipeline(groups),
    }


def _build_ordinal_encoder(columns: list[str]) -> OrdinalEncoder:
    """OrdinalEncoder with auto categories."""
    return OrdinalEncoder(
        categories="auto",
        handle_unknown="use_encoded_value",
        unknown_value=-1,
    )


def _build_cat_low_transformer() -> Pipeline:
    """저카디널리티 범주형: SimpleImputer + OrdinalEncoder."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OrdinalEncoder(
            categories="auto",
            handle_unknown="use_encoded_value",
            unknown_value=-1,
        )),
    ])


def _build_unsupervised_preprocessor(groups: FeatureGroups) -> ColumnTransformer:
    """VAE/IF 공용 전처리: 수치형 스케일링 + 고카디널리티 DROP."""
    transformers = []
    if groups.numeric:
        transformers.append((
            "num",
            Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("power", SafePowerTransformer()),
                ("scaler", StandardScaler()),
            ]),
            groups.numeric,
        ))
    # 고카디널리티 범주형: TargetEncoder 없이(y 불필요) → DROP
    if groups.categorical_low:
        transformers.append(("cat_low", _build_cat_low_transformer(), groups.categorical_low))
    if groups.boolean:
        transformers.append(("bool", "passthrough", groups.boolean))
    if groups.ordinal:
        transformers.append(("ord", _build_ordinal_encoder(groups.ordinal), groups.ordinal))

    return ColumnTransformer(transformers, remainder="drop")
