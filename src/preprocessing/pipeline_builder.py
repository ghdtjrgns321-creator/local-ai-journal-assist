"""Pipeline 조립 — 지도학습 4종(LR/RF/XGB/LGBM) + 비지도 2종(VAE/IF).

Why: 모델 특성에 따라 전처리가 달라진다.
지도학습은 스케일링 불필요+TargetEncoder, VAE/IF는 StandardScaler+고카디널리티 DROP.
"""

from __future__ import annotations

import logging

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder, StandardScaler

from src.preprocessing.feature_quality import apply_feature_quality_policy
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.transformers import SafePowerTransformer
from src.preprocessing.vae_wrapper import VAEDetector

logger = logging.getLogger(__name__)

try:
    from sklearn.preprocessing import TargetEncoder
except ImportError:  # sklearn < 1.3
    TargetEncoder = None  # type: ignore[assignment,misc]

try:
    from xgboost import XGBClassifier
except ImportError:
    XGBClassifier = None  # type: ignore[assignment,misc]

try:
    from lightgbm import LGBMClassifier
except ImportError:
    LGBMClassifier = None  # type: ignore[assignment,misc]


def drop_label_columns(df):
    """Drop DataSynth label columns and normalize inference-time persona values."""
    cleaned, _, _ = apply_feature_quality_policy(df, for_training=False)
    return cleaned


def prepare_training_features(
    df,
    groups: FeatureGroups,
):
    """Normalize unstable features and exclude sparse training-only columns."""
    return apply_feature_quality_policy(df, groups, for_training=True)


def _build_supervised_preprocessor(groups: FeatureGroups) -> ColumnTransformer:
    """XGB/LightGBM/LR/RF 공용 전처리기 — 스케일링 불필요, TargetEncoder 사용."""
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
    if hasattr(preprocessor, "set_output"):
        preprocessor.set_output(transform="default")
    return preprocessor


def build_xgb_pipeline(groups: FeatureGroups) -> Pipeline:
    """XGBoost 지도학습 Pipeline 조립."""
    return Pipeline([
        ("preprocessor", _build_supervised_preprocessor(groups)),
        ("classifier", XGBClassifier(eval_metric="logloss")),
    ])


def build_lgbm_pipeline(groups: FeatureGroups) -> Pipeline:
    """LightGBM 지도학습 Pipeline 조립."""
    if LGBMClassifier is None:
        raise ImportError("lightgbm 미설치. pip install lightgbm")
    return Pipeline([
        ("preprocessor", _build_supervised_preprocessor(groups)),
        ("classifier", LGBMClassifier(is_unbalance=True, verbosity=-1, random_state=42)),
    ])


def build_supervised_pipelines(
    groups: FeatureGroups, use_smote: bool = False,
) -> dict[str, Pipeline]:
    """지도학습 4개 Pipeline: lr, rf, xgb, lgbm.

    Why: cv_selector.compare_pipelines()로 자동 비교하여 최적 모델 선택.
    use_smote=True이면 imblearn Pipeline으로 감싸서 CV 내부 train fold에만 SMOTE-ENN 적용.
    """
    classifiers = {
        "lr": LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42),
        "rf": RandomForestClassifier(
            class_weight="balanced", n_estimators=100, random_state=42,
        ),
    }
    if XGBClassifier is not None:
        classifiers["xgb"] = XGBClassifier(eval_metric="logloss", random_state=42)
    if LGBMClassifier is not None:
        classifiers["lgbm"] = LGBMClassifier(
            is_unbalance=True, verbosity=-1, random_state=42,
        )

    # Why: 각 파이프라인에 독립적인 preprocessor 인스턴스 — fit 상태 교차 오염 방지
    pipelines: dict[str, Pipeline] = {}
    for name, clf in classifiers.items():
        pipelines[name] = _wrap_pipeline(
            _build_supervised_preprocessor(groups), clf, use_smote,
        )
    return pipelines


def _wrap_pipeline(preprocessor: ColumnTransformer, clf, use_smote: bool) -> Pipeline:
    """use_smote 여부에 따라 sklearn 또는 imblearn Pipeline 반환."""
    if not use_smote:
        return Pipeline([("preprocessor", preprocessor), ("classifier", clf)])
    try:
        from imblearn.combine import SMOTEENN
        from imblearn.pipeline import Pipeline as ImbPipeline
    except ImportError:
        logger.warning("imbalanced-learn 미설치. SMOTE 없이 진행.")
        return Pipeline([("preprocessor", preprocessor), ("classifier", clf)])
    return ImbPipeline([
        ("preprocessor", preprocessor),
        ("smote", SMOTEENN(random_state=42)),
        ("classifier", clf),
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


def build_ft_pipeline(groups: FeatureGroups) -> Pipeline:
    """FT-Transformer 지도학습 Pipeline 조립.

    Why: self-attention으로 피처 간 상호작용을 학습하는 지도학습 모델.
    lazy import로 torch 미설치 환경에서 다른 파이프라인에 영향 없음.
    """
    from src.preprocessing.ft_wrapper import FTTransformerClassifier

    preprocessor = _build_supervised_preprocessor(groups)
    return Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", FTTransformerClassifier()),
    ])


def build_all_pipelines(groups: FeatureGroups) -> dict[str, Pipeline]:
    """xgb/vae/if Pipeline 일괄 생성. FT-Transformer는 별도 build_ft_pipeline() 사용."""
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


# Why: SequenceDetector가 2D 전처리기를 직접 호출하기 위한 public alias
build_supervised_preprocessor = _build_supervised_preprocessor


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

    preprocessor = ColumnTransformer(transformers, remainder="drop")
    if hasattr(preprocessor, "set_output"):
        preprocessor.set_output(transform="default")
    return preprocessor
