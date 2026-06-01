"""SequenceDetector — BiLSTM+Attention 시퀀스 기반 이상 탐지기.

Why: ISA 240 '경영진 override' 반복 패턴을 사용자-시간 윈도우 시퀀스로 포착.
단일 전표가 아닌 동일 입력자의 시간적 맥락에서 이상을 판단한다.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd
from sklearn.exceptions import NotFittedError
from sklearn.metrics import f1_score

from src.detection.base import BaseDetector, DetectionResult
from src.preprocessing.bilstm_wrapper import BiLSTMClassifier
from src.preprocessing.data_stats import (
    compute_class_imbalance,
    compute_feature_schema_version,
    compute_training_stats,
)
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.label_strategy import LabelResult
from src.preprocessing.model_registry import ModelRegistry
from src.preprocessing.pipeline_builder import (
    build_supervised_preprocessor,
    drop_label_columns,
    prepare_training_features,
)
from src.preprocessing.sequence_builder import build_sequences
from src.preprocessing.split_strategy import choose_train_validation_split

logger = logging.getLogger(__name__)

_RULE_ID = "ML04"
_MIN_POSITIVE_COUNT = 50
_MIN_POSITIVE_RATE = 0.01
_THRESHOLD_VAL_RATIO = 0.2

# 시퀀스 구성에 필요한 컬럼 (전처리 전 원본 DataFrame에서 추출)
_SEQ_USER_COL = "created_by"
_SEQ_TIME_COL = "posting_date"
# Why: posting_time(HH:MM:SS) 컬럼이 있으면 같은 날 거래의 시:분:초 정렬에 활용.
#      DataSynth가 csv_sink에 추가한 컬럼. 부재 시 기존 동작(date 단위 정렬) 유지.
_SEQ_TIME_OF_DAY_COL = "posting_time"


class SequenceDetector(BaseDetector):
    """BiLSTM+Attention 시퀀스 기반 이상 탐지기."""

    def __init__(
        self,
        settings=None,
        model_registry: ModelRegistry | None = None,
    ) -> None:
        super().__init__(settings)
        self._registry = model_registry

    @property
    def track_name(self) -> str:
        return "ml_sequence"

    # -- 학습 --

    def train(
        self,
        X: pd.DataFrame,
        label_result: LabelResult,
        groups: FeatureGroups,
    ) -> dict:
        """BiLSTM 학습: 전처리 → 시퀀스 변환 → 학습 + threshold 탐색."""
        X, groups, feature_quality = prepare_training_features(X, groups)
        warnings = self._validate_labels(label_result)
        if feature_quality.sparse_dropped_columns:
            warnings = warnings + [
                "sparse feature columns excluded: "
                + ", ".join(feature_quality.sparse_dropped_columns)
            ]
        y = label_result.y

        # 1. 시퀀스 메타데이터 추출 (전처리 전 원본에서)
        if _SEQ_USER_COL not in X.columns or _SEQ_TIME_COL not in X.columns:
            raise ValueError(f"시퀀스 구성에 {_SEQ_USER_COL}, {_SEQ_TIME_COL} 컬럼이 필요합니다.")
        user_ids = X[_SEQ_USER_COL].values
        timestamps = self._build_timestamps(X)

        # 2. GroupShuffleSplit — 입력자 단위 완전 분리 (시퀀스 누수 방지)
        # Why: 동일 사용자의 전표가 Train/Valid 양쪽에 걸리면
        #      윈도우 오버랩으로 데이터 누수 발생 → 낙관적 threshold
        split = choose_train_validation_split(
            X,
            group_column=_SEQ_USER_COL,
            test_size=_THRESHOLD_VAL_RATIO,
        )
        train_idx, val_idx = split.train_idx, split.test_idx

        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]
        uid_tr, uid_val = user_ids[train_idx], user_ids[val_idx]
        ts_tr, ts_val = timestamps[train_idx], timestamps[val_idx]

        # GroupShuffleSplit은 stratify 미지원 → 양성 비율 검증
        val_pos_rate = float(y_val.sum() / len(y_val)) if len(y_val) > 0 else 0.0
        if val_pos_rate == 0.0:
            msg = "검증셋에 양성 샘플이 없습니다. threshold 탐색 품질 저하 가능."
            logger.warning(msg)
            warnings.append(msg)

        # 3. 전처리 (2D)
        self.preprocessor_ = build_supervised_preprocessor(groups)
        X_tr_2d = self.preprocessor_.fit_transform(X_tr, y_tr)
        X_val_2d = self.preprocessor_.transform(X_val)

        # 4. 시퀀스 변환 (2D→3D)
        seq_len = self._settings.bilstm_seq_len
        stride = self._settings.bilstm_stride

        train_seq = build_sequences(
            X_tr_2d,
            y_tr,
            uid_tr,
            ts_tr,
            seq_len=seq_len,
            stride=stride,
        )
        val_seq = build_sequences(
            X_val_2d,
            y_val,
            uid_val,
            ts_val,
            seq_len=seq_len,
            stride=stride,
        )

        # 최소 윈도우 수 검증
        if len(train_seq.X_seq) == 0:
            raise ValueError(
                f"학습 시퀀스가 0개입니다. 데이터가 부족하거나 seq_len({seq_len})이 너무 큽니다."
            )
        if len(val_seq.X_seq) == 0:
            msg = "검증 시퀀스가 0개입니다. threshold를 기본값(0.5)으로 설정합니다."
            logger.warning(msg)
            warnings.append(msg)

        # 5. BiLSTM 학습
        self.classifier_ = BiLSTMClassifier(
            hidden_size=self._settings.bilstm_hidden_size,
            dropout=self._settings.bilstm_dropout,
            num_layers=self._settings.bilstm_num_layers,
            epochs=self._settings.bilstm_epochs,
            batch_size=self._settings.bilstm_batch_size,
            lr=self._settings.bilstm_lr,
        )
        self.classifier_.fit(train_seq.X_seq, train_seq.y_seq, train_seq.mask)

        # 6. 동적 threshold
        if len(val_seq.X_seq) > 0:
            self.optimal_threshold_ = self._find_optimal_threshold(val_seq)
        else:
            self.optimal_threshold_ = 0.5

        self.classes_ = np.array([0, 1])

        # Why: 드리프트 감지 베이스라인 — 학습 시점 분포를 메타데이터에 보존
        self._train_stats = compute_training_stats(X_tr)
        self._schema_version = compute_feature_schema_version(X_tr)
        self._class_imbalance = compute_class_imbalance(y_tr)
        self._n_train = int(len(X_tr))
        self._split_policy = split.policy
        self._train_years = split.train_years
        self._validation_years = split.test_years
        self._feature_quality_profile = feature_quality.to_dict()

        return {
            "optimal_threshold": self.optimal_threshold_,
            "n_train_sequences": len(train_seq.X_seq),
            "n_val_sequences": len(val_seq.X_seq),
            "n_train_rows": len(X_tr),
            "n_val_rows": len(X_val),
            "train_years": split.train_years,
            "validation_years": split.test_years,
            "split_policy": split.policy,
            "warnings": warnings,
            "feature_quality_profile": self._feature_quality_profile,
        }

    # -- 탐지 --

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """학습된 BiLSTM으로 시퀀스 기반 이상 탐지 수행."""
        self._check_fitted()
        start = time.perf_counter()

        # 1. 메타데이터 추출
        df = drop_label_columns(df)
        user_ids = df[_SEQ_USER_COL].values
        timestamps = self._build_timestamps(df)

        # 2. 전처리 (2D)
        X_2d = self.preprocessor_.transform(df)

        # 3. 시퀀스 변환 (detect 시 stride=1 고정 — 모든 행을 평가)
        seq_result = build_sequences(
            X_2d,
            y=None,
            user_ids=user_ids,
            timestamps=timestamps,
            seq_len=self._settings.bilstm_seq_len,
            stride=1,
        )

        # 4. 예측
        scores_full = pd.Series(0.0, index=df.index, name=_RULE_ID, dtype=float)

        if len(seq_result.X_seq) > 0:
            proba = self.classifier_.predict_proba(
                seq_result.X_seq,
                seq_result.mask,
            )[:, 1]

            # 5. 윈도우 → 원본 행 매핑 (max 집계)
            # Why: pos_idx는 preprocessor.transform(df) 기준 positional index (0-based).
            #      df.index.values[pos_idx]로 실제 DataFrame 레이블 인덱스를 역산.
            #      동일 행이 여러 윈도우의 마지막 항목일 수 있음 → 최대 확률 사용.
            df_index_array = df.index.values
            for window_idx, pos_idx in enumerate(seq_result.original_indices):
                actual_df_idx = df_index_array[pos_idx]
                current = scores_full.at[actual_df_idx]
                scores_full.at[actual_df_idx] = max(current, proba[window_idx])

        flagged_mask = scores_full > self.optimal_threshold_
        flagged_indices = scores_full[flagged_mask].index.tolist()

        details = pd.DataFrame({_RULE_ID: scores_full}, index=df.index)
        rule_flags = [
            self._create_rule_flag(
                rule_id=_RULE_ID,
                flagged_count=int(flagged_mask.sum()),
                total_count=len(df),
            ),
        ]
        elapsed = time.perf_counter() - start
        result = self._make_result(
            flagged_indices=flagged_indices,
            scores=scores_full,
            rule_flags=rule_flags,
            details=details,
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=[],
        )
        # Sequence windows are mapped back to source DataFrame labels above.
        # BaseDetector normalizes to positions for legacy detectors, but this
        # detector's public contract is label-preserving for filtered inputs.
        result.flagged_indices = flagged_indices
        return result

    # -- 모델 영속화 --

    def save_model(self, mean_f1: float):
        """preprocessor + classifier + threshold + 학습 분포 메타를 저장."""
        self._check_fitted()
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        bundle = {
            "preprocessor": self.preprocessor_,
            "classifier": self.classifier_,
        }
        return self._registry.save(
            bundle,
            "bilstm_sequence",
            mean_f1,
            params={"optimal_threshold": self.optimal_threshold_},
            training_data_stats=getattr(self, "_train_stats", {}),
            feature_schema_version=getattr(self, "_schema_version", 1),
            class_imbalance_ratio=getattr(self, "_class_imbalance", 0.0),
            n_train_samples=getattr(self, "_n_train", 0),
            evaluation_policy=getattr(self, "_split_policy", "unknown"),
            evaluation_confidence=_evaluation_confidence(getattr(self, "_split_policy", "unknown")),
            train_years=getattr(self, "_train_years", ()),
            test_years=getattr(self, "_validation_years", ()),
            feature_quality_profile=getattr(self, "_feature_quality_profile", {}),
        )

    def load_model(
        self,
        model_name: str = "bilstm_sequence",
        version: int | None = None,
    ) -> None:
        """ModelRegistry에서 모델 번들 로드 + threshold 복원."""
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        bundle = self._registry.load(model_name, version)
        self.preprocessor_ = bundle["preprocessor"]
        self.classifier_ = bundle["classifier"]
        meta = self._registry.list_models()
        matched = [m for m in meta if m.model_name == model_name]
        if version is not None:
            matched = [m for m in matched if m.version == version]
        self.optimal_threshold_ = (
            matched[-1].params.get("optimal_threshold", 0.5) if matched else 0.5
        )
        self.classes_ = np.array([0, 1])

    # -- private --

    def _check_fitted(self) -> None:
        if not hasattr(self, "preprocessor_") or not hasattr(self, "classifier_"):
            raise NotFittedError(
                f"{type(self).__name__}은 아직 학습되지 않았습니다. train()을 먼저 호출하세요.",
            )

    @staticmethod
    def _build_timestamps(X: pd.DataFrame) -> np.ndarray:
        """posting_date + posting_time → np.datetime64[ns] 배열.

        Why: 같은 날 거래의 시퀀스 정렬은 시:분:초가 있어야 의미가 있다.
             posting_time(HH:MM:SS) 컬럼이 있으면 posting_date에 더해 결정론적
             타임스탬프를 만든다. 부재 시 posting_date(date 단위)만 사용 → 기존 동작.
             ISA 240 "30분 내 연속 입력" 같은 패턴 감지가 가능해진다.
        """
        ts = pd.to_datetime(X[_SEQ_TIME_COL], errors="coerce")
        if _SEQ_TIME_OF_DAY_COL in X.columns:
            # Why: posting_time이 string("14:35:22")이거나 datetime.time일 수 있음.
            #      timedelta로 변환 후 더해 정상 타임스탬프 형성. NaT는 그대로 보존.
            tod = pd.to_timedelta(
                X[_SEQ_TIME_OF_DAY_COL].astype(str),
                errors="coerce",
            )
            ts = ts + tod.fillna(pd.Timedelta(0))
        return ts.values

    def _validate_labels(self, label_result: LabelResult) -> list[str]:
        """양성 건수/비율 최소 요건 검증."""
        pos_count = int(label_result.y.sum())
        if pos_count == 0:
            raise ValueError("양성 샘플이 0건입니다. 지도학습 불가.")
        warnings: list[str] = []
        if pos_count < _MIN_POSITIVE_COUNT:
            msg = f"양성 {pos_count}건 < 최소 {_MIN_POSITIVE_COUNT}건. 학습 품질 저하 가능."
            self._logger.warning(msg)
            warnings.append(msg)
        if label_result.positive_rate < _MIN_POSITIVE_RATE:
            msg = f"양성 비율 {label_result.positive_rate:.4f} < {_MIN_POSITIVE_RATE}. 극단 불균형."
            self._logger.warning(msg)
            warnings.append(msg)
        return warnings

    def _find_optimal_threshold(self, val_seq) -> float:
        """F1-macro 최대화 threshold 탐색 (validation 시퀀스 기반).

        주의: 시퀀스(윈도우) 단위 F1 — 마지막 항목 라벨 기준 (방식 A).
        전표 단위 재현율과 다를 수 있음.
        """
        proba = self.classifier_.predict_proba(
            val_seq.X_seq,
            val_seq.mask,
        )[:, 1]
        thresholds = np.linspace(0.1, 0.9, 81)
        best_t, best_f1 = 0.5, 0.0
        for t in thresholds:
            preds = (proba >= t).astype(int)
            if preds.sum() == 0 or preds.sum() == len(preds):
                continue
            score = f1_score(val_seq.y_seq, preds, average="macro", zero_division=0)
            if score > best_f1:
                best_f1, best_t = score, float(t)
        self._logger.info("최적 threshold: %.3f (F1-macro=%.4f)", best_t, best_f1)
        return best_t


def _evaluation_confidence(split_policy: str) -> str:
    if split_policy == "temporal_holdout":
        return "benchmark"
    if split_policy == "document_group_holdout":
        return "development_only"
    return "unknown"
