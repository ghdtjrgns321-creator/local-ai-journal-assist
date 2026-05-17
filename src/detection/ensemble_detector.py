"""EnsembleDetector — Stacking Meta-Learner 기반 앙상블 탐지기.

Why: 8개 base model(룰 4레이어 + ML 4종)의 DetectionResult를 수집하여
     Ridge(positive=True) meta-learner로 최종 anomaly_score를 산출한다.
     라벨 부족 시 Percentile Ranking 가중합으로 폴백한다.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.model_selection import GroupKFold

from config.settings import AuditSettings
from src.detection.base import BaseDetector, DetectionResult
from src.detection.constants import (
    STACKING_BASE_MODELS,
    STACKING_FALLBACK_WEIGHTS,
    Layer,
)
from src.preprocessing.label_strategy import LabelResult
from src.preprocessing.model_registry import ModelRegistry

# Why: y 라벨로 학습하는(=leakage 가능) base model의 track_name 집합.
#      OOF 절차에서 fold마다 재학습 대상이다. 룰 4종 + 비지도(VAE+IF)는 제외.
_LEAKAGE_PRONE_TRACKS: tuple[str, ...] = (
    Layer.ML_SUPERVISED,
    Layer.ML_TRANSFORMER,
    Layer.ML_SEQUENCE,
)


def _train_fold_worker(
    fold_idx: int,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    X: pd.DataFrame,
    y: np.ndarray,
    groups,
    settings,
) -> dict:
    """단일 fold에서 leakage-prone base 3개 모델을 학습 + val OOF 예측 반환.

    Why: joblib.Parallel(backend="loky")에서 별도 프로세스로 실행되도록 모듈
         최상위 함수로 분리. self/closure 없이 직렬화 가능한 인자만 받는다.

    Args:
        fold_idx: fold 번호 (로깅용).
        train_idx, val_idx: GroupKFold에서 산출된 행 인덱스.
        X: 전체 DataFrame (워커가 프로세스 경계로 직렬화).
        y: 전체 라벨.
        groups: FeatureGroups.
        settings: AuditSettings.

    Returns:
        {"fold_idx": int, "val_idx": ndarray, "scores": {track_name: ndarray}}
    """
    # Why: 워커 내부 import — 모듈 import 시 detection 패키지의 다른 무거운
    #      의존성을 부모 프로세스로 끌어오지 않기 위함.
    from src.detection.sequence_detector import SequenceDetector
    from src.detection.supervised_detector import SupervisedDetector
    from src.detection.tabular_transformer import TransformerDetector
    from src.preprocessing.label_strategy import LabelResult

    X_tr = X.iloc[train_idx]
    X_val = X.iloc[val_idx]
    y_tr = y[train_idx]

    # Why: fold 단위 LabelResult 재구성 — 양성 비율은 fold마다 다르다
    pos_rate = float(np.sum(y_tr == 1) / len(y_tr)) if len(y_tr) > 0 else 0.0
    label_tr = LabelResult(
        y=y_tr,
        strategy="oof_fold",
        label_source="train_oof",
        positive_rate=pos_rate,
    )

    fold_scores: dict[str, np.ndarray] = {}

    # 1) Supervised
    try:
        sup = SupervisedDetector(settings=settings)
        sup.train(X_tr, label_tr, groups)
        fold_scores[Layer.ML_SUPERVISED] = sup.detect(X_val).scores.values
    except Exception as exc:
        logger.warning("OOF fold %d ML_SUPERVISED 실패: %s", fold_idx, exc)
        fold_scores[Layer.ML_SUPERVISED] = np.zeros(len(val_idx), dtype=np.float64)

    # 2) FT-Transformer
    try:
        tfm = TransformerDetector(settings=settings)
        tfm.train(X_tr, label_tr, groups)
        fold_scores[Layer.ML_TRANSFORMER] = tfm.detect(X_val).scores.values
    except Exception as exc:
        logger.warning("OOF fold %d ML_TRANSFORMER 실패: %s", fold_idx, exc)
        fold_scores[Layer.ML_TRANSFORMER] = np.zeros(len(val_idx), dtype=np.float64)

    # 3) BiLSTM Sequence
    try:
        seq = SequenceDetector(settings=settings)
        seq.train(X_tr, label_tr, groups)
        fold_scores[Layer.ML_SEQUENCE] = seq.detect(X_val).scores.values
    except Exception as exc:
        logger.warning("OOF fold %d ML_SEQUENCE 실패: %s", fold_idx, exc)
        fold_scores[Layer.ML_SEQUENCE] = np.zeros(len(val_idx), dtype=np.float64)

    return {
        "fold_idx": fold_idx,
        "val_idx": val_idx,
        "scores": fold_scores,
    }

logger = logging.getLogger(__name__)


class EnsembleDetector(BaseDetector):
    """Stacking Meta-Learner 기반 앙상블 탐지기.

    두 가지 경로를 제공한다:
    - detect_from_results(): 이미 실행된 DetectionResult 리스트로 추론 (pipeline.py 메인 경로)
    - detect(): BaseDetector 계약 준수용 (단독 사용 불가, detect_from_results 위임)
    """

    def __init__(
        self,
        settings: AuditSettings | None = None,
        model_registry: ModelRegistry | None = None,
    ) -> None:
        super().__init__(settings)
        self._registry = model_registry
        self._meta = None  # StackingEnsemble (지연 임포트)
        self._is_fallback: bool = False
        self._fallback_ecdf: dict[str, np.ndarray] = {}  # fallback용 ECDF 학습 분포

    @property
    def track_name(self) -> str:
        return "ensemble"

    # ── 추론 경로 ─────────────────────────────────────────────

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """BaseDetector 계약 준수. 단독 호출 시 빈 결과 반환.

        Why: EnsembleDetector는 다른 탐지기의 결과가 필요하므로
             df만으로는 추론할 수 없다. detect_from_results()를 사용할 것.
        """
        self._logger.warning(
            "EnsembleDetector.detect()는 직접 호출 불가 — detect_from_results() 사용"
        )
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index, name="EN01"),
            rule_flags=[],
            details=pd.DataFrame({"EN01": 0.0}, index=df.index),
            metadata={"elapsed": 0.0, "mode": "empty"},
            warnings=["detect_from_results()를 사용하세요"],
        )

    def detect_from_results(
        self,
        results: list[DetectionResult],
        df_index: pd.Index,
    ) -> DetectionResult:
        """이미 실행된 DetectionResult 리스트 → meta-learner 추론.

        Args:
            results: 8개 base model의 DetectionResult 리스트.
            df_index: 원본 DataFrame의 인덱스 (행 정렬용).

        Returns:
            DetectionResult — scores는 meta-learner의 최종 anomaly_score.
        """
        t0 = time.perf_counter()

        score_matrix = self._build_score_matrix(results, df_index)

        if self._is_fallback or self._meta is None:
            # Why: meta-learner 미학습 → Percentile Ranking fallback
            scores = self._fallback_percentile_ranking(results, df_index)
            mode = "fallback"
        else:
            proba = self._meta.predict_proba(score_matrix)[:, 1]
            scores = pd.Series(proba, index=df_index, name="EN01")
            mode = "stacking"

        scores = scores.clip(0.0, 1.0)
        threshold = 0.5
        flagged_mask = scores > threshold
        flagged_indices = scores.index[flagged_mask].tolist()

        elapsed = time.perf_counter() - t0
        rule_flag = self._create_rule_flag(
            "EN01",
            flagged_count=len(flagged_indices),
            total_count=len(df_index),
            detail=f"mode={mode}",
        )

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=[rule_flag],
            details=pd.DataFrame({"EN01": scores}, index=df_index),
            metadata={"elapsed": elapsed, "mode": mode},
            warnings=[],
        )

    # ── 학습 경로 ─────────────────────────────────────────────

    def train_oof(
        self,
        X: pd.DataFrame,
        label_result: LabelResult,
        user_ids: np.ndarray,
        df_index: pd.Index,
        non_leakage_results: list[DetectionResult],
        groups,
    ) -> dict:
        """진정한 OOF Stacking 학습 — User-Leakage 방어 GroupKFold.

        Why: train_from_results()는 base 모델이 이미 전체 데이터에 fit된 상태에서
             동일 데이터 predict를 사용하므로 ML_SUPERVISED/ML_TRANSFORMER/ML_SEQUENCE
             3개 모델에 대해 leakage가 있다. 본 메서드는 이 3개 모델만 fold마다
             재학습하여 OOF 예측을 만들고, 룰 4종 + VAE는 fold 무관이므로
             non_leakage_results를 그대로 사용한다.

             User-Leakage 방어: GroupKFold(groups=user_ids)로 한 사용자의 전표가
             한 fold에만 속하도록 보장. 단순 random split은 "User A는 일단 이상"
             memorization 과적합을 유발한다.

        Args:
            X: (N, D) 원본 DataFrame — fold마다 X.iloc[train_idx]로 분리.
            label_result: 전체 라벨. fold마다 y[train_idx]로 LabelResult 재생성.
            user_ids: (N,) 사용자 ID — GroupKFold의 groups 인자.
            df_index: 원본 DataFrame 인덱스 (score_matrix 정렬용).
            non_leakage_results: 룰 4종 + VAE 등 fold 무관 base 모델 결과.
            groups: FeatureGroups — base 모델 train()에 전달.

        Returns:
            {"mode": "oof_stacking", "n_folds": int, "feature_weights": {...}}
        """
        y = np.asarray(label_result.y)
        user_ids = np.asarray(user_ids)
        if len(user_ids) != len(X):
            raise ValueError("train_oof user_ids length must match X rows")
        if "created_by" in X.columns:
            expected_user_ids = X["created_by"].astype(str).to_numpy()
            received_user_ids = pd.Series(user_ids).astype(str).to_numpy()
            if not np.array_equal(received_user_ids, expected_user_ids):
                raise ValueError("train_oof user_ids must match X['created_by']")

        if self._check_fallback_needed(y):
            self._is_fallback = True
            score_matrix = self._build_score_matrix_from_lists(
                non_leakage_results, [], df_index,
            )
            for col_idx, track_name in enumerate(STACKING_BASE_MODELS):
                raw = score_matrix[:, col_idx]
                if np.std(raw) >= 1e-12:
                    self._fallback_ecdf[track_name] = np.sort(raw)
            logger.info(
                "라벨 부족 — OOF 진입 거부, fallback 모드 활성화 (ECDF %d개)",
                len(self._fallback_ecdf),
            )
            return {
                "mode": "fallback",
                "n_folds": 0,
                "feature_weights": dict(STACKING_FALLBACK_WEIGHTS),
            }

        n_splits = int(self._settings.stacking_cv_folds)
        n_jobs = int(self._settings.stacking_oof_n_jobs)
        gkf = GroupKFold(n_splits=n_splits)

        # Why: fold split index를 미리 구해두어 _train_fold가 참조할 수 있도록 한다.
        fold_splits = list(gkf.split(X, y, groups=user_ids))
        for train_idx, val_idx in fold_splits:
            train_users = set(user_ids[train_idx].astype(str).tolist())
            val_users = set(user_ids[val_idx].astype(str).tolist())
            overlap = train_users & val_users
            if overlap:
                raise ValueError(
                    "GroupKFold user leakage detected in train_oof: "
                    f"{sorted(overlap)[:5]}",
                )

        # Why: 각 fold는 base 모델 3개의 OOF score를 (val_idx, track_name → ndarray) 형식으로 반환.
        #      joblib backend="loky"는 별도 프로세스로 fold를 격리 — torch/sklearn 안전.
        fold_outputs = Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(_train_fold_worker)(
                fold_idx,
                train_idx,
                val_idx,
                X,
                y,
                groups,
                self._settings,
            )
            for fold_idx, (train_idx, val_idx) in enumerate(fold_splits)
        )

        # Why: 각 leakage-prone track의 OOF score를 N행 벡터로 합침.
        #      val_idx로 흩뿌리면 자연스럽게 N개 행 모두 채워진다 (GroupKFold 전수 커버).
        oof_scores: dict[str, np.ndarray] = {
            track: np.zeros(len(df_index), dtype=np.float64)
            for track in _LEAKAGE_PRONE_TRACKS
        }
        for fold_out in fold_outputs:
            val_idx = fold_out["val_idx"]
            for track in _LEAKAGE_PRONE_TRACKS:
                oof_scores[track][val_idx] = fold_out["scores"].get(
                    track, np.zeros(len(val_idx), dtype=np.float64),
                )

        score_matrix = self._build_score_matrix_from_oof(
            non_leakage_results=non_leakage_results,
            oof_scores=oof_scores,
            df_index=df_index,
        )

        # Why: 순환 임포트 방지
        from src.preprocessing.stacking import StackingEnsemble
        self._meta = StackingEnsemble(alpha=self._settings.stacking_alpha)
        self._meta.fit(score_matrix, y)
        self._is_fallback = False

        # 드리프트 감지용 메타데이터 보존
        self._n_train = int(len(y))
        self._class_imbalance = float(np.sum(y == 1) / len(y)) if len(y) > 0 else 0.0

        return {
            "mode": "oof_stacking",
            "n_folds": n_splits,
            "feature_weights": self._meta.feature_weights,
        }

    def train_from_results(
        self,
        results: list[DetectionResult],
        y: np.ndarray,
        df_index: pd.Index,
    ) -> dict:
        """이미 탐지 완료된 DetectionResult에서 scores를 추출하여 meta-learner 학습.

        Why: 완전 OOF가 아닌 간소화 경로. base model이 이미 전체 데이터에
             대해 실행된 상태이므로 약간의 leakage 가능하나, 실무에서는
             라벨 수가 제한적일 때 이 경로를 사용한다.

        Args:
            results: 8개 base model의 DetectionResult 리스트.
            y: (N,) 이진 라벨.
            df_index: 원본 DataFrame 인덱스.

        Returns:
            {"mode": "stacking"|"fallback", "feature_weights": {...}, ...}
        """
        y = np.asarray(y)

        if self._check_fallback_needed(y):
            self._is_fallback = True
            # Why: fallback ECDF 분포 저장 — 추론 시 학습 분포 기준으로 정규화
            score_matrix = self._build_score_matrix(results, df_index)
            for col_idx, track_name in enumerate(STACKING_BASE_MODELS):
                raw = score_matrix[:, col_idx]
                if np.std(raw) >= 1e-12:
                    self._fallback_ecdf[track_name] = np.sort(raw)
            logger.info(
                "라벨 부족 — fallback 모드 활성화 (ECDF %d개 저장)",
                len(self._fallback_ecdf),
            )
            return {"mode": "fallback", "feature_weights": dict(STACKING_FALLBACK_WEIGHTS)}

        score_matrix = self._build_score_matrix(results, df_index)

        # Why: 순환 임포트 방지 — detection.__init__ → ensemble_detector → stacking → constants
        from src.preprocessing.stacking import StackingEnsemble
        self._meta = StackingEnsemble(
            alpha=self._settings.stacking_alpha,
        )
        self._meta.fit(score_matrix, y)
        self._is_fallback = False

        # Why: 드리프트 감지용 — score_matrix 차원의 메타데이터 보존
        self._n_train = int(len(y))
        self._class_imbalance = float(np.sum(y == 1) / len(y)) if len(y) > 0 else 0.0

        return {
            "mode": "stacking",
            "feature_weights": self._meta.feature_weights,
        }

    # ── 모델 영속화 ───────────────────────────────────────────

    def save_model(self, mean_f1: float = 0.0):
        """meta-learner를 ModelRegistry로 저장.

        Why: feature_count는 len(STACKING_BASE_MODELS). 학습 분포 메타는
             ensemble의 입력이 score_matrix(N×8)이므로 별도 컬럼 통계는 의미가 적어
             메타 등록만 수행한다.
        """
        if self._meta is None:
            raise ValueError("학습된 meta-learner가 없습니다.")
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        return self._registry.save(
            self._meta,
            "stacking_meta",
            mean_f1,
            feature_count=len(STACKING_BASE_MODELS),
            params={"is_fallback": self._is_fallback},
            n_train_samples=getattr(self, "_n_train", 0),
            class_imbalance_ratio=getattr(self, "_class_imbalance", 0.0),
        )

    def load_model(
        self, model_name: str = "stacking_meta", version: int | None = None,
    ) -> None:
        """ModelRegistry에서 meta-learner 로드."""
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        self._meta = self._registry.load(model_name, version)
        # Why: fallback 모드 정보 복원
        meta_list = self._registry.list_models()
        matched = [m for m in meta_list if m.model_name == model_name]
        if version is not None:
            matched = [m for m in matched if m.version == version]
        if matched:
            self._is_fallback = matched[-1].params.get("is_fallback", False)

    # ── 유틸리티 ──────────────────────────────────────────────

    @staticmethod
    def _build_score_matrix(
        results: list[DetectionResult],
        index: pd.Index,
    ) -> np.ndarray:
        """DetectionResult 리스트 → (N, len(STACKING_BASE_MODELS)) 점수 행렬.

        Why: STACKING_BASE_MODELS 순서로 열을 조립.
             누락 모델은 0.0으로 채워 Cold Start에 대응한다.
        """
        result_map = {r.track_name: r for r in results}
        n = len(index)
        matrix = np.zeros((n, len(STACKING_BASE_MODELS)), dtype=np.float64)

        for col_idx, track_name in enumerate(STACKING_BASE_MODELS):
            if track_name in result_map:
                scores = result_map[track_name].scores.reindex(index, fill_value=0.0)
                matrix[:, col_idx] = scores.values

        return matrix

    @staticmethod
    def _build_score_matrix_from_lists(
        non_leakage_results: list[DetectionResult],
        leakage_results: list[DetectionResult],
        index: pd.Index,
    ) -> np.ndarray:
        """OOF fallback 경로용 score_matrix 빌더.

        Why: train_oof()가 fallback으로 빠질 때도 동일한
             (N, len(STACKING_BASE_MODELS)) 형식이 필요하다.
             non_leakage_results만으로 채우고 나머지는 0.
        """
        return EnsembleDetector._build_score_matrix(
            list(non_leakage_results) + list(leakage_results), index,
        )

    @staticmethod
    def _build_score_matrix_from_oof(
        non_leakage_results: list[DetectionResult],
        oof_scores: dict[str, np.ndarray],
        df_index: pd.Index,
    ) -> np.ndarray:
        """non-leakage 결과 + leakage-prone 모델의 OOF score 행렬 조립.

        Why: STACKING_BASE_MODELS 순서를 그대로 따르되, leakage-prone 트랙은
             oof_scores 딕셔너리에서, 나머지는 non_leakage_results에서 가져온다.
        """
        result_map = {r.track_name: r for r in non_leakage_results}
        n = len(df_index)
        matrix = np.zeros((n, len(STACKING_BASE_MODELS)), dtype=np.float64)

        for col_idx, track_name in enumerate(STACKING_BASE_MODELS):
            if track_name in oof_scores:
                # Why: oof_scores는 이미 df_index 길이의 ndarray (val_idx로 직접 채워둠)
                matrix[:, col_idx] = oof_scores[track_name]
            elif track_name in result_map:
                scores = result_map[track_name].scores.reindex(df_index, fill_value=0.0)
                matrix[:, col_idx] = scores.values
        return matrix

    def _check_fallback_needed(self, y: np.ndarray) -> bool:
        """양성 샘플이 부족한지 판정.

        Why: 양성 < min_positive 또는 양성비율 < threshold → stacking 학습 불가능.
        """
        positive_count = int(np.sum(y == 1))
        positive_rate = positive_count / len(y) if len(y) > 0 else 0.0
        return (
            positive_count < self._settings.stacking_min_positive
            or positive_rate < self._settings.stacking_fallback_threshold
        )

    def _fallback_percentile_ranking(
        self,
        results: list[DetectionResult],
        index: pd.Index,
    ) -> pd.Series:
        """ECDF 기반 Percentile Ranking 가중합 (fallback 모드).

        Why: rankdata는 현재 배치 내 상대 순위 기준이라 모두 정상이어도
             최상위가 오탐되는 문제가 있다. 학습 시 저장한 ECDF 분포를
             기준으로 searchsorted 정규화하여 안정적인 백분위수를 산출한다.
        """
        result_map = {r.track_name: r for r in results}
        n = len(index)
        score_acc = np.zeros(n, dtype=np.float64)

        for track_name, weight in STACKING_FALLBACK_WEIGHTS.items():
            if track_name not in result_map:
                continue
            raw = result_map[track_name].scores.reindex(index, fill_value=0.0).values

            if track_name in self._fallback_ecdf:
                # Why: 학습 분포 기준 ECDF 정규화 — searchsorted로 백분위수 산출
                sorted_ref = self._fallback_ecdf[track_name]
                normalized = np.searchsorted(sorted_ref, raw) / len(sorted_ref)
            elif np.std(raw) >= 1e-12:
                # Why: 학습 분포 없으면 (Cold Start) 현재 배치 내 순위로 fallback
                from scipy.stats import rankdata
                ranked = rankdata(raw, method="average")
                normalized = (ranked - 1) / max(n - 1, 1)
            else:
                continue

            score_acc += normalized * weight

        return pd.Series(
            np.clip(score_acc, 0.0, 1.0),
            index=index,
            name="EN01",
        )
