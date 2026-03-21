"""지도/비지도 Pipeline 조립.

Why: 모델 유형에 따라 전처리 전략이 달라야 한다.
- XGBoost(지도): TargetEncoder 사용, 스케일링 불필요
- VAE/IF(비지도): 고카디널리티 DROP, PowerTransformer + StandardScaler 필수

sklearn Pipeline으로 전처리+모델을 번들링하면
"어떤 전처리가 최적인가?"를 모델과 함께 실험할 수 있다 (닭-달걀 해결).
"""

from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder, StandardScaler

from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.transformers import SafePowerTransformer

# description_quality, has_risk_keyword 순서 정의
_ORDINAL_CATEGORIES = {
    "description_quality": ["missing", "poor", "normal"],
    "has_risk_keyword": ["none", "low", "medium", "high"],
}


def _build_ordinal_encoder(columns: list[str]) -> OrdinalEncoder:
    """ordinal 그룹용 OrdinalEncoder — 카테고리 순서 수동 지정."""
    categories = [
        _ORDINAL_CATEGORIES.get(col, "auto")
        for col in columns
    ]
    return OrdinalEncoder(
        categories=categories,
        handle_unknown="use_encoded_value",
        unknown_value=-1,
    )


def _build_cat_low_transformer() -> Pipeline:
    """저카디널리티 범주형 전처리 블록."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OrdinalEncoder(
            handle_unknown="use_encoded_value",
            unknown_value=-1,
        )),
    ])


def build_xgb_pipeline(groups: FeatureGroups, **xgb_params) -> Pipeline:
    """XGBoost Pipeline — 지도학습, TargetEncoder 사용.

    Why: 트리 모델은 스케일링 불필요. TargetEncoder로 gl_account(4000+종)
    고카디널리티를 효과적으로 인코딩한다.
    """
    from sklearn.preprocessing import TargetEncoder
    from xgboost import XGBClassifier

    transformers = [
        ("num", SimpleImputer(strategy="median"), groups.numeric),
        ("bool", "passthrough", groups.boolean),
    ]

    # 고카디널리티: TargetEncoder (지도학습 전용)
    if groups.categorical_high:
        transformers.append((
            "cat_high",
            Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", TargetEncoder(smooth="auto")),
            ]),
            groups.categorical_high,
        ))

    if groups.categorical_low:
        transformers.append((
            "cat_low", _build_cat_low_transformer(), groups.categorical_low,
        ))

    if groups.ordinal:
        transformers.append((
            "ordinal",
            Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", _build_ordinal_encoder(groups.ordinal)),
            ]),
            groups.ordinal,
        ))

    preprocessor = ColumnTransformer(transformers, remainder="drop")

    defaults = {
        "eval_metric": "logloss",
        "n_estimators": 100,
        "random_state": 42,
        "n_jobs": -1,
    }
    defaults.update(xgb_params)

    return Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", XGBClassifier(**defaults)),
    ])


def _build_unsupervised_preprocessor(groups: FeatureGroups) -> ColumnTransformer:
    """비지도 모델 공통 전처리 — 고카디널리티 DROP + PowerTransformer.

    Why: 비지도 모델은 y가 없어 TargetEncoder 사용 불가.
    고카디널리티(gl_account 4000+종)를 트리에 넣으면 깊이만 증가하고
    이상치를 못 잡으므로 제외한다. 금액 컬럼의 극단적 우측 꼬리 분포는
    PowerTransformer(Yeo-Johnson)로 정규화 후 StandardScaler를 적용한다.
    """
    transformers = [
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("power", SafePowerTransformer()),
            ("scaler", StandardScaler()),
        ]), groups.numeric),
        ("bool", "passthrough", groups.boolean),
        # categorical_high: 의도적 미포함 (DROP)
    ]

    if groups.categorical_low:
        transformers.append((
            "cat_low", _build_cat_low_transformer(), groups.categorical_low,
        ))

    if groups.ordinal:
        transformers.append((
            "ordinal",
            Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", _build_ordinal_encoder(groups.ordinal)),
            ]),
            groups.ordinal,
        ))

    return ColumnTransformer(transformers, remainder="drop")


def build_vae_pipeline(groups: FeatureGroups, **vae_params) -> Pipeline:
    """VAE Pipeline — 비지도, 고카디널리티 DROP."""
    from src.preprocessing.vae_wrapper import VAEDetector

    return Pipeline([
        ("preprocessor", _build_unsupervised_preprocessor(groups)),
        ("detector", VAEDetector(**vae_params)),
    ])


def build_if_pipeline(groups: FeatureGroups, **if_params) -> Pipeline:
    """Isolation Forest Pipeline — 비지도, 고카디널리티 DROP."""
    from sklearn.ensemble import IsolationForest

    defaults = {
        "contamination": 0.01,
        "random_state": 42,
        "n_jobs": -1,
    }
    defaults.update(if_params)

    return Pipeline([
        ("preprocessor", _build_unsupervised_preprocessor(groups)),
        ("detector", IsolationForest(**defaults)),
    ])


def build_all_pipelines(groups: FeatureGroups) -> dict[str, Pipeline]:
    """3개 Pipeline 일괄 생성."""
    return {
        "xgb": build_xgb_pipeline(groups),
        "vae": build_vae_pipeline(groups),
        "if": build_if_pipeline(groups),
    }
