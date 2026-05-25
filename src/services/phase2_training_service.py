"""Foundation helpers for the Phase 2 AutoML training pipeline.

Phase 2 standalone training contract
------------------------------------

Phase 2 학습은 **원본/featured 회계 DataFrame** 에서 family detector 와
unsupervised VAE 를 standalone 으로 학습한다. PHASE1 case ranking,
``composite_sort_score``, ``topic_score_*``, rule hit summary 는 학습
입력 feature 로 들어가지 않는다.

- primary input: ``df`` (= featured GL DataFrame).
- optional context: ``phase1_case_result`` — manifest metadata 산출용. case-level
  ML-safe feature (``PHASE2_CASE_FEATURE_COLUMNS``) 와 provenance fields 의
  존재 여부를 inference contract 에 기록할 뿐, row matrix 입력 또는 학습
  target 으로 사용하지 않는다. ``_build_phase1_case_contract_metadata`` 는
  feature firewall (``enforce_phase2_case_feature_firewall``) 검증을 거친 뒤
  manifest 만 반환한다.
- deny coverage: ``LEAKAGE_DENY_COLUMNS`` + ``LEAKAGE_DENY_RULES`` +
  ``_LEAKAGE_PATTERNS`` (label/target/fraud/anomaly/risk/rule/score/model/
  prediction/probability/export/dashboard 토큰) 으로 PHASE1 산출 컬럼과
  DataSynth shortcut 을 모두 차단한다 (``preprocessing.phase2_plan``).

따라서 PHASE1 결과는 "어떤 case 가 존재한다" 라는 메타데이터만 contract
에 남기며, "어떤 row 가 risky 한지" 학습을 유도하지 않는다.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

from config.settings import PROJECT_ROOT, get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.ensemble_detector import EnsembleDetector
from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.relational_detector import RelationalDetector
from src.detection.sequence_detector import SequenceDetector
from src.detection.supervised_detector import SupervisedDetector, SupervisedGateError
from src.detection.tabular_transformer import TransformerDetector
from src.detection.timeseries_detector import TimeseriesDetector
from src.detection.vae_detector import UnsupervisedDetector
from src.eda.profiler import profile_dataframe
from src.evaluation.phase2_report import build_hold_out_metrics
from src.preprocessing.constants import LEAKAGE_DENY_COLUMNS, LEAKAGE_DENY_RULES
from src.preprocessing.feature_groups import FeatureGroups, classify_features
from src.preprocessing.feature_quality import (
    FEATURE_FAMILIES,
    apply_feature_quality_policy,
)
from src.preprocessing.label_strategy import create_labels, create_labels_from_feedback
from src.preprocessing.model_registry import ModelRegistry
from src.preprocessing.phase2_matrix import Phase2AutoencoderMatrixBuilder
from src.preprocessing.phase2_plan import build_phase2_preprocessing_plan
from src.services._phase_timing import TimingBlock, log_timing
from src.services.phase2_case_contract import (
    PROVENANCE_ONLY_FIELDS,
    build_phase2_case_feature_frame,
)
from src.services.phase2_leaderboard import save_leaderboard_json
from src.services.phase2_promotion_policy import save_promotion_decision_json
from src.services.phase2_training_models import (
    Phase2LabelSummary,
    Phase2PromotedModel,
    Phase2TrainingReport,
    Phase2TrainingStatus,
    Phase2TrialResult,
)

_DEFAULT_PHASE2_TRAIN_DIR = PROJECT_ROOT / "data" / "phase2_train"
_DEFAULT_MODEL_FAMILIES = (
    "unsupervised",
    "timeseries",
    "relational",
    "duplicate",
    "intercompany",
)
DEFAULT_HOLD_OUT_SCENARIOS = (
    "unusual_timing_manipulation",
    "approval_sod_bypass",
)
_PHASE2_TRAINING_MODE = "unsupervised_autoencoder_mvp"
_PHASE2_RULE_INPUT_DIM = 22
_RULE_STYLE_FAMILIES = {"timeseries", "relational", "duplicate", "intercompany"}
_SEQUENCE_CONTEXT_COLUMNS = ("document_id", "created_by", "posting_date", "posting_time")
_RULE_STYLE_REQUIRED_COLUMNS = {
    "timeseries": ("posting_date", "auxiliary_account_number"),
    "relational": (
        "trading_partner",
        "posting_date",
        "debit_amount",
        "credit_amount",
        "gl_account",
        "is_intercompany",
        "document_id",
    ),
    "duplicate": (
        "gl_account",
        "posting_date",
        "debit_amount",
        "credit_amount",
        "line_text",
    ),
    "intercompany": (
        "is_intercompany",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "posting_date",
        "trading_partner",
    ),
}
# 학습 trial metadata 의 sub_detector_keys (training_report.json) 출처.
# 본 매핑은 phase2_subdetector_tiers.yaml 의 tier registry 와 의도적으로 다른
# 범위를 가진다 — 여기에는 **rule-style 학습 trial 의 식별자만** 등재하며,
# IC family 의 `ic_reciprocal_flow_prob` / `ic_amount_prob` / `ic_unmatched_prob` /
# `ic_timing_prob` (2026-05-25 옵션 2 로 tier registry 에 등록된 4개 internal
# probability column) 는 IntercompanyMatcher detector 내부에서 한 번에 산출되는
# probability surface 이지 독립 학습 대상이 아니므로 본 매핑에서 의도적으로 제외한다.
# tier registry 와 본 매핑의 정합 lock 은
# `tests/modules/test_services/test_phase2_training_service.py`
# ::TestRuleStyleSubDetectorRegistryContract 참조.
_RULE_STYLE_SUB_DETECTORS = {
    "timeseries": ("transaction_burst", "unusual_frequency"),
    "relational": (
        "new_counterparty",
        "dormant_account_activity",
        "transfer_pricing_anomaly",
        "missing_relationship",
        "rare_account_partner_edge",
        "user_account_degree_spike",
        "dormant_partner_reactivation",
    ),
    "duplicate": (
        "exact_duplicate_amount",
        "fuzzy_duplicate",
        "split_transaction",
        "time_shifted_duplicate",
    ),
    "intercompany": (
        "unmatched_intercompany",
        "amount_mismatch",
        "timing_gap",
    ),
}
_RULE_STYLE_METRIC_NAMES = {
    "timeseries": "burst_detection_rate",
    "relational": "new_counterparty_precision",
    "duplicate": "fuzzy_match_f1",
    "intercompany": "ic_match_completeness",
}
_DEFAULT_FAMILY_MIN_COMPLETED_TRIALS = {
    "unsupervised": 2,
    "supervised": 2,
    "transformer": 2,
    "sequence": 2,
    "timeseries": 2,
    "relational": 2,
    "duplicate": 2,
    "intercompany": 2,
    "stacking": 2,
}
_DEFAULT_FAMILY_MIN_METRIC = {
    "unsupervised": 0.05,
    "supervised": 0.10,
    "transformer": 0.10,
    "sequence": 0.10,
    "timeseries": 0.05,
    "relational": 0.05,
    "duplicate": 0.05,
    "intercompany": 0.05,
    "stacking": 0.10,
}
_SEVERE_UNSUPERVISED_RELIABILITY_WARNINGS = {
    "degenerate_score_distribution",
    "group_loss_dominated",
    "nan_score_distribution",
    "posterior_collapse_warning",
    "score_flat",
}
_DEFAULT_DETECTOR_FACTORIES = {
    "unsupervised": UnsupervisedDetector,
    "supervised": SupervisedDetector,
    "transformer": TransformerDetector,
    "sequence": SequenceDetector,
    "timeseries": TimeseriesDetector,
    "relational": RelationalDetector,
    "duplicate": DuplicateDetector,
    "intercompany": IntercompanyMatcher,
    "stacking": EnsembleDetector,
}
_PROMOTED_TRACK_MAP = {
    "supervised": "ml_supervised",
    "unsupervised": "ml_unsupervised",
    "ft_transformer": "ml_transformer",
    "bilstm_sequence": "ml_sequence",
    "timeseries": "timeseries",
    "relational": "relational",
    "duplicate": "duplicate",
    "intercompany": "intercompany",
    "stacking_meta": "ensemble",
}
logger = logging.getLogger(__name__)
_FAMILY_TO_CANONICAL_MODEL = {
    "unsupervised": "unsupervised",
    "supervised": "supervised",
    "transformer": "ft_transformer",
    "sequence": "bilstm_sequence",
    "timeseries": "timeseries",
    "relational": "relational",
    "duplicate": "duplicate",
    "intercompany": "intercompany",
    "stacking": "stacking_meta",
}
_DEFAULT_SEARCH_PRESETS = {
    # Why (2026-05-23): 100k 측정 결과 unsupervised_selection_score 가
    # ranking proxy 라 epoch/preset variant 별 차이가 noise 수준(±0.0003)이고,
    # baseline(3 preset × 7 variant = 21 trial, ~1150s) → balanced 1개 + epochs=20
    # (1 preset × 7 variant = 7 trial, ~280s) 로 학습 시간 -75% 절감.
    # search variant 다양성을 잃지 않도록 feature variant 7개는 유지.
    "unsupervised": (
        {
            "name": "balanced",
            "settings_updates": {
                "vae_hidden_dim": 64,
                "vae_latent_dim": 32,
                "vae_epochs": 20,
                "vae_batch_size": 256,
                "vae_lr": 1e-3,
                "vae_beta": 1.0,
                "if_contamination": 0.01,
                "phase2_review_capacity_ratio": 0.10,
            },
        },
    ),
    "supervised": (
        {
            "name": "baseline",
            "settings_updates": {},
            "detector_kwargs": {"use_smote": False},
        },
        {
            "name": "smote",
            "settings_updates": {},
            "detector_kwargs": {"use_smote": True},
        },
    ),
    "transformer": (
        {
            "name": "compact",
            "settings_updates": {
                "ft_d_token": 32,
                "ft_n_layers": 2,
                "ft_n_heads": 4,
                "ft_d_ff": 128,
            },
        },
        {
            "name": "wide",
            "settings_updates": {
                "ft_d_token": 64,
                "ft_n_layers": 3,
                "ft_n_heads": 8,
                "ft_d_ff": 256,
            },
        },
    ),
    "sequence": (
        {
            "name": "short_window",
            "settings_updates": {
                "bilstm_seq_len": 8,
                "bilstm_hidden_size": 64,
            },
        },
        {
            "name": "long_window",
            "settings_updates": {
                "bilstm_seq_len": 16,
                "bilstm_hidden_size": 128,
            },
        },
    ),
    "timeseries": (
        {
            "name": "balanced",
            "settings_updates": {
                "burst_window_days": 7,
                "burst_sigma": 3.0,
                "frequency_window_days": 7,
                "frequency_min_count": 5,
            },
        },
        {
            "name": "sensitive",
            "settings_updates": {
                "burst_window_days": 14,
                "burst_sigma": 2.0,
                "frequency_window_days": 10,
                "frequency_min_count": 4,
            },
        },
    ),
    "relational": (
        {
            "name": "balanced",
            "settings_updates": {
                "rel_new_cp_lookback_days": 90,
                "rel_new_cp_large_quantile": 0.90,
                "rel_dormant_inactive_days": 180,
            },
        },
        {
            "name": "strict",
            "settings_updates": {
                "rel_new_cp_lookback_days": 60,
                "rel_new_cp_large_quantile": 0.95,
                "rel_dormant_inactive_days": 240,
            },
        },
    ),
    "duplicate": (
        {
            "name": "balanced",
            "settings_updates": {
                "duplicate_fuzzy_threshold": 80,
                "duplicate_time_window_days": 7,
            },
        },
        {
            "name": "strict",
            "settings_updates": {
                "duplicate_fuzzy_threshold": 88,
                "duplicate_time_window_days": 3,
            },
        },
    ),
    "intercompany": (
        {
            "name": "balanced",
            "settings_updates": {
                "ic_amount_tolerance": 0.05,
                "ic_max_day_diff": 7,
            },
        },
        {
            "name": "strict",
            "settings_updates": {
                "ic_amount_tolerance": 0.05,
                "ic_max_day_diff": 3,
            },
        },
    ),
    "stacking": (
        {
            "name": "ridge_light",
            "settings_updates": {
                "stacking_alpha": 0.5,
            },
        },
        {
            "name": "ridge_strict",
            "settings_updates": {
                "stacking_alpha": 2.0,
            },
        },
    ),
}


@dataclass
class Phase2UnsupervisedSplit:
    train_df: pd.DataFrame
    calibration_df: pd.DataFrame
    metadata: dict[str, Any]


def resolve_phase2_training_dir(ctx=None, base_dir: Path | None = None) -> Path:
    """Return the root directory for Phase 2 training artifacts."""
    if base_dir is not None:
        return Path(base_dir)
    model_dir = getattr(ctx, "model_dir", None)
    if model_dir is not None:
        return Path(model_dir) / "phase2_train"
    return _DEFAULT_PHASE2_TRAIN_DIR


def build_phase2_training_paths(
    ctx=None,
    *,
    report_id: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Path]:
    """Build report/trial/promoted directories for one training run."""
    root = resolve_phase2_training_dir(ctx, base_dir=base_dir)
    training_id = report_id or uuid.uuid4().hex[:12]
    run_root = root / training_id
    return {
        "root": root,
        "run_root": run_root,
        "trials_dir": run_root / "trials",
        "reports_dir": run_root / "reports",
        "promoted_dir": run_root / "promoted",
        "report_path": run_root / "reports" / "training_report.json",
        "leaderboard_path": run_root / "reports" / "leaderboard.json",
        "promotion_decision_path": run_root / "reports" / "promotion_decision.json",
    }


def ensure_phase2_training_dirs(paths: dict[str, Path]) -> dict[str, Path]:
    """Create required artifact directories and return the same path map."""
    for key in ("trials_dir", "reports_dir", "promoted_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def save_phase2_training_report(
    report: Phase2TrainingReport,
    *,
    ctx=None,
    base_dir: Path | None = None,
) -> Path:
    """Persist a Phase 2 training report as JSON."""
    paths = ensure_phase2_training_dirs(
        build_phase2_training_paths(
            ctx,
            report_id=report.report_id,
            base_dir=base_dir,
        ),
    )
    report.status = (
        report.status
        if report.status != Phase2TrainingStatus.PENDING
        else Phase2TrainingStatus.COMPLETED
    )
    report_path = paths["report_path"]
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_leaderboard_json(report, paths["reports_dir"])
    save_promotion_decision_json(report, paths["reports_dir"])
    return report_path


def build_promoted_model_artifact_dir(ctx, *, family: str, version: int | str) -> Path:
    """Return the canonical promoted model artifact directory for a family/version."""
    model_dir = Path(getattr(ctx, "model_dir"))
    version_text = f"v{int(version):04d}" if isinstance(version, int) else str(version)
    return model_dir / f"phase2_{family}" / version_text


def initialize_phase2_training_report(
    *,
    ctx=None,
    report_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Phase2TrainingReport:
    """Create the minimal training report skeleton for a new AutoML run."""
    return Phase2TrainingReport(
        report_id=report_id or uuid.uuid4().hex[:12],
        company_id=getattr(ctx, "company_id", None),
        engagement_id=getattr(ctx, "engagement_id", None),
        status=Phase2TrainingStatus.PENDING,
        metadata=metadata or {},
    )


def build_phase2_label_summary(
    df,
    *,
    detection_scores=None,
    feedback_labels=None,
    strategy: str = "hybrid",
) -> tuple[Phase2LabelSummary, Any]:
    """Resolve the training label gate summary from feedback or dataset labels."""
    feedback_result = create_labels_from_feedback(df, feedback_labels)
    label_result = feedback_result or create_labels(
        df,
        detection_scores=detection_scores,
        strategy=strategy,
    )
    summary = Phase2LabelSummary(
        strategy=str(label_result.strategy),
        label_source=str(label_result.label_source),
        gate_status=str(label_result.gate_status),
        gate_reason=label_result.gate_reason,
        is_supervised_eligible=bool(label_result.is_supervised_eligible),
        positive_count=int(label_result.positive_count),
        positive_rate=float(label_result.positive_rate),
        gate_decision=str(getattr(label_result, "gate_decision", "unknown")),
    )
    return summary, label_result


def _build_supervised_gate_payload(
    label_summary: Phase2LabelSummary,
    settings,
) -> dict[str, Any]:
    return {
        "decision": str(label_summary.gate_decision),
        "reason": label_summary.gate_reason,
        "label_source": str(label_summary.label_source),
        "positive_count": int(label_summary.positive_count),
        "positive_rate": float(label_summary.positive_rate),
        "thresholds": {
            "min_positive_count": int(getattr(settings, "supervised_min_positive", 50)),
            "min_positive_rate": float(
                getattr(settings, "supervised_min_positive_rate", 0.01),
            ),
        },
        "eligible": bool(label_summary.is_supervised_eligible),
        "allowed_label_sources": list(
            getattr(settings, "supervised_allowed_label_sources", ["ground_truth"]),
        ),
    }


def prepare_phase2_feature_inputs(df, *, settings=None) -> tuple[Any, Any, dict[str, Any]]:
    """Build cleaned training features, groups, and quality metadata once."""
    logger.info(
        "Leakage deny applied: %s columns",
        len(LEAKAGE_DENY_COLUMNS | LEAKAGE_DENY_RULES),
    )
    active_settings = settings or get_settings()
    profile = profile_dataframe(
        df,
        max_rows=getattr(active_settings, "phase2_profile_max_rows", None),
        random_seed=int(getattr(active_settings, "phase2_random_seed", 42)),
    )
    preprocessing_plan = build_phase2_preprocessing_plan(
        profile,
        high_card_threshold=int(
            getattr(active_settings, "heuristic_high_cardinality_threshold", 50),
        ),
    )
    raw_groups = classify_features(profile)
    cleaned_df, adjusted_groups, feature_quality = apply_feature_quality_policy(
        df,
        raw_groups,
        for_training=False,
    )
    payload = {
        "raw_groups": _feature_groups_to_dict(raw_groups),
        "adjusted_groups": _feature_groups_to_dict(adjusted_groups),
        "feature_metadata": {
            "rule_input_dim": _PHASE2_RULE_INPUT_DIM,
            "rule_input_policy": "phase1_rule_results_excluding_leakage_deny_rules",
            "excluded_rule_columns": sorted(LEAKAGE_DENY_RULES),
        },
        "preprocessing_plan": preprocessing_plan.to_dict(),
        "feature_quality_profile": feature_quality.to_dict(),
        "feature_variants": build_phase2_feature_variants(cleaned_df, adjusted_groups),
    }
    return cleaned_df, adjusted_groups, payload


def _phase2_training_mode(settings) -> str:
    return str(
        getattr(settings, "phase2_training_mode", _PHASE2_TRAINING_MODE) or _PHASE2_TRAINING_MODE
    )


def _split_unsupervised_train_calibration(
    df,
    settings,
    *,
    hold_out_scenarios: tuple[str, ...] = DEFAULT_HOLD_OUT_SCENARIOS,
) -> Phase2UnsupervisedSplit:
    """Split Phase 2 unsupervised data with group split as the default path."""
    working_df, hold_out_df, hold_out_metadata = _extract_hold_out_frame(
        df,
        hold_out_scenarios=hold_out_scenarios,
    )
    train_ratio = getattr(settings, "phase2_unsup_train_ratio", None)
    if train_ratio is None:
        calibration_size = float(getattr(settings, "phase2_calibration_size", 0.20) or 0.20)
    else:
        train_ratio = min(max(float(train_ratio), 0.10), 1.0)
        calibration_size = 1.0 - train_ratio
    calibration_size = min(max(calibration_size, 0.0), 0.9)
    calibration_row_cap = int(getattr(settings, "phase2_unsup_calibration_rows", 0) or 0)
    seed = int(getattr(settings, "phase2_random_seed", 42))
    strategy = str(getattr(settings, "phase2_split_strategy", "group") or "group").lower()
    group_column = str(
        getattr(settings, "phase2_split_group_column", "document_id") or "document_id"
    )
    temporal_column = str(
        getattr(settings, "phase2_temporal_column", "posting_date") or "posting_date"
    )

    if len(working_df) <= 1 or calibration_size <= 0:
        split = Phase2UnsupervisedSplit(
            train_df=working_df.copy(),
            calibration_df=working_df.iloc[0:0].copy(),
            metadata={
                "split_strategy": "none",
                "train_row_count": int(len(working_df)),
                "calibration_row_count": 0,
                "calibration_size": calibration_size,
                "unsup_train_ratio": float(1.0 - calibration_size),
                "unsup_calibration_rows_cap": calibration_row_cap,
            },
        )
        return _append_hold_out_to_calibration(split, hold_out_df, hold_out_metadata)

    if strategy == "temporal" and temporal_column in working_df.columns:
        split = _temporal_unsupervised_split(working_df, temporal_column, calibration_size)
    elif group_column in working_df.columns:
        split = _group_unsupervised_split(working_df, group_column, calibration_size, seed)
    else:
        split = _random_unsupervised_split(working_df, calibration_size, seed)

    split = _append_hold_out_to_calibration(split, hold_out_df, hold_out_metadata)
    split.metadata.update(
        {
            "train_row_count": int(len(split.train_df)),
            "calibration_row_count": int(len(split.calibration_df)),
            "calibration_size": calibration_size,
            "unsup_train_ratio": float(1.0 - calibration_size),
            "unsup_calibration_rows_cap": calibration_row_cap,
            "random_seed": seed,
        }
    )
    return split


def _extract_hold_out_frame(
    df,
    *,
    hold_out_scenarios: tuple[str, ...],
) -> tuple[Any, Any, dict[str, Any]]:
    scenarios = tuple(str(value).strip().lower() for value in hold_out_scenarios if value)
    metadata: dict[str, Any] = {
        "hold_out_scenarios": list(hold_out_scenarios),
        "hold_out_scenario_column": "mutation_type",
        "hold_out_row_count": 0,
        "hold_out_doc_count": 0,
        "_hold_out_row_indices": [],
    }
    if not scenarios or "mutation_type" not in df.columns:
        metadata["hold_out_available"] = False
        return df.copy(), df.iloc[0:0].copy(), metadata
    scenario_values = df["mutation_type"].fillna("").astype(str).str.strip().str.lower()
    mask = scenario_values.isin(scenarios)
    hold_out_df = df.loc[mask].copy()
    trainable_df = df.loc[~mask].copy()
    metadata.update(
        {
            "hold_out_available": True,
            "hold_out_row_count": int(len(hold_out_df)),
            "hold_out_doc_count": (
                int(hold_out_df["document_id"].dropna().nunique())
                if "document_id" in hold_out_df.columns
                else int(len(hold_out_df))
            ),
            "hold_out_by_scenario": {
                scenario: int(scenario_values.loc[mask].eq(scenario).sum())
                for scenario in scenarios
            },
            "_hold_out_row_indices": hold_out_df.index.tolist(),
        }
    )
    return trainable_df, hold_out_df, metadata


def _append_hold_out_to_calibration(
    split: Phase2UnsupervisedSplit,
    hold_out_df,
    hold_out_metadata: dict[str, Any],
) -> Phase2UnsupervisedSplit:
    metadata = dict(split.metadata)
    metadata.update(hold_out_metadata)
    if hold_out_df.empty:
        return Phase2UnsupervisedSplit(
            train_df=split.train_df,
            calibration_df=split.calibration_df,
            metadata=metadata,
        )
    calibration_df = pd.concat([split.calibration_df, hold_out_df], axis=0).sort_index()
    metadata["hold_out_in_train_rows"] = int(split.train_df.index.isin(hold_out_df.index).sum())
    metadata["hold_out_in_calibration_rows"] = int(
        calibration_df.index.isin(hold_out_df.index).sum()
    )
    return Phase2UnsupervisedSplit(
        train_df=split.train_df,
        calibration_df=calibration_df,
        metadata=metadata,
    )


def _apply_unsupervised_split_row_caps(
    split: Phase2UnsupervisedSplit,
    settings,
) -> Phase2UnsupervisedSplit:
    """Apply deterministic train/calibration caps after split selection."""
    seed = int(getattr(settings, "phase2_random_seed", 42))
    train_cap = int(getattr(settings, "phase2_train_max_rows", 0) or 0)
    calibration_cap = int(getattr(settings, "phase2_unsup_calibration_rows", 0) or 0)
    group_column = str(
        getattr(settings, "phase2_split_group_column", "document_id") or "document_id"
    )
    prefer_group_cap = (
        split.metadata.get("split_strategy") == "group"
        and group_column in split.train_df.columns
        and group_column in split.calibration_df.columns
    )
    metadata = dict(split.metadata)

    capped_train, train_strategy = _cap_frame_deterministically(
        split.train_df,
        cap_rows=train_cap,
        seed=seed,
        group_column=group_column if prefer_group_cap else None,
    )
    hold_out_indices = set(metadata.get("_hold_out_row_indices") or [])
    if hold_out_indices:
        hold_out_mask = split.calibration_df.index.isin(hold_out_indices)
        calibration_for_cap = split.calibration_df.loc[~hold_out_mask]
        hold_out_calibration = split.calibration_df.loc[hold_out_mask]
    else:
        calibration_for_cap = split.calibration_df
        hold_out_calibration = split.calibration_df.iloc[0:0]

    capped_calibration_base, calibration_strategy = _cap_frame_deterministically(
        calibration_for_cap,
        cap_rows=calibration_cap,
        seed=seed + 1,
        group_column=group_column if prefer_group_cap else None,
    )
    if not hold_out_calibration.empty:
        capped_calibration = pd.concat(
            [capped_calibration_base, hold_out_calibration],
            axis=0,
        ).sort_index()
        calibration_strategy = f"{calibration_strategy}_plus_hold_out"
    else:
        capped_calibration = capped_calibration_base
    metadata.update(
        {
            "source_train_rows": int(len(split.train_df)),
            "source_calibration_rows": int(len(split.calibration_df)),
            "capped_train_rows": int(len(capped_train)),
            "capped_calibration_rows": int(len(capped_calibration)),
            "train_row_cap": train_cap,
            "calibration_row_cap": calibration_cap,
            "cap_strategy": {
                "train": train_strategy,
                "calibration": calibration_strategy,
            },
            "seed": seed,
        }
    )
    metadata["train_row_count"] = int(len(capped_train))
    metadata["calibration_row_count"] = int(len(capped_calibration))
    if metadata.get("hold_out_row_count"):
        hold_out_indices = set(metadata.get("_hold_out_row_indices") or [])
        metadata["hold_out_in_train_rows"] = int(capped_train.index.isin(hold_out_indices).sum())
        metadata["hold_out_in_calibration_rows"] = int(
            capped_calibration.index.isin(hold_out_indices).sum()
        )
    metadata.pop("_hold_out_row_indices", None)
    return Phase2UnsupervisedSplit(
        train_df=capped_train,
        calibration_df=capped_calibration,
        metadata=metadata,
    )


def _cap_frame_deterministically(
    df,
    *,
    cap_rows: int,
    seed: int,
    group_column: str | None = None,
) -> tuple[Any, str]:
    if cap_rows <= 0:
        return df.copy(), "uncapped"
    if len(df) <= cap_rows:
        return df.copy(), "not_needed"
    if group_column and group_column in df.columns:
        capped = _cap_frame_by_group(df, group_column=group_column, cap_rows=cap_rows, seed=seed)
        if not capped.empty:
            return capped, "document_group_cap"
    return df.sample(n=cap_rows, random_state=seed).sort_index().copy(), "row_sample_cap"


def _cap_frame_by_group(df, *, group_column: str, cap_rows: int, seed: int):
    group_sizes = pd.Series(df[group_column]).astype("string").value_counts(dropna=False)
    groups = group_sizes.index.tolist()
    rng = np.random.default_rng(seed)
    shuffled = list(groups)
    rng.shuffle(shuffled)
    selected: list[Any] = []
    selected_rows = 0
    for group in shuffled:
        group_rows = int(group_sizes.loc[group])
        if selected_rows > 0 and selected_rows + group_rows > cap_rows:
            continue
        selected.append(group)
        selected_rows += group_rows
        if selected_rows >= cap_rows:
            break
    if not selected:
        return df.iloc[0:0].copy()
    mask = pd.Series(df[group_column]).astype("string").isin(selected)
    return df.loc[mask].sort_index().copy()


def _group_unsupervised_split(
    df,
    group_column: str,
    calibration_size: float,
    seed: int,
) -> Phase2UnsupervisedSplit:
    groups = pd.Series(df[group_column]).dropna().astype("string").unique().tolist()
    if len(groups) < 2:
        split = _random_unsupervised_split(df, calibration_size, seed)
        split.metadata["fallback_reason"] = "insufficient_groups"
        return split
    rng = np.random.default_rng(seed)
    shuffled = list(groups)
    rng.shuffle(shuffled)
    target_groups = max(1, int(round(len(shuffled) * calibration_size)))
    calibration_groups = set(shuffled[:target_groups])
    calibration_mask = pd.Series(df[group_column]).astype("string").isin(calibration_groups)
    if calibration_mask.all() or not calibration_mask.any():
        split = _random_unsupervised_split(df, calibration_size, seed)
        split.metadata["fallback_reason"] = "empty_group_split"
        return split
    return Phase2UnsupervisedSplit(
        train_df=df.loc[~calibration_mask].copy(),
        calibration_df=df.loc[calibration_mask].copy(),
        metadata={
            "split_strategy": "group",
            "group_column": group_column,
            "calibration_group_count": len(calibration_groups),
        },
    )


def _temporal_unsupervised_split(
    df,
    temporal_column: str,
    calibration_size: float,
) -> Phase2UnsupervisedSplit:
    ordered = df.assign(
        __phase2_temporal_key=pd.to_datetime(df[temporal_column], errors="coerce"),
    ).sort_values("__phase2_temporal_key", kind="mergesort")
    if ordered["__phase2_temporal_key"].isna().all():
        return Phase2UnsupervisedSplit(
            train_df=df.copy(),
            calibration_df=df.iloc[0:0].copy(),
            metadata={
                "split_strategy": "temporal",
                "temporal_column": temporal_column,
                "fallback_reason": "all_temporal_values_missing",
            },
        )
    calibration_rows = max(1, int(round(len(ordered) * calibration_size)))
    train = ordered.iloc[:-calibration_rows].drop(columns=["__phase2_temporal_key"])
    calibration = ordered.iloc[-calibration_rows:].drop(columns=["__phase2_temporal_key"])
    if train.empty:
        train = ordered.iloc[:1].drop(columns=["__phase2_temporal_key"])
        calibration = ordered.iloc[1:].drop(columns=["__phase2_temporal_key"])
    return Phase2UnsupervisedSplit(
        train_df=train.copy(),
        calibration_df=calibration.copy(),
        metadata={"split_strategy": "temporal", "temporal_column": temporal_column},
    )


def _random_unsupervised_split(
    df,
    calibration_size: float,
    seed: int,
) -> Phase2UnsupervisedSplit:
    calibration_rows = max(1, int(round(len(df) * calibration_size)))
    calibration_rows = min(calibration_rows, len(df) - 1)
    rng = np.random.default_rng(seed)
    calibration_positions = set(rng.choice(len(df), size=calibration_rows, replace=False))
    mask = np.array([idx in calibration_positions for idx in range(len(df))])
    return Phase2UnsupervisedSplit(
        train_df=df.loc[~mask].copy(),
        calibration_df=df.loc[mask].copy(),
        metadata={"split_strategy": "random", "fallback": True},
    )


def build_phase2_feature_variants(df, groups) -> list[dict[str, Any]]:
    """Expand feature-family ablations into concrete variant column sets."""
    if groups is None:
        return []
    all_columns = [col for col in groups.all_features if col in df.columns]
    optional_columns = {
        family: [col for col in columns if col in all_columns]
        for family, columns in FEATURE_FAMILIES.items()
    }
    optional_active = {family: cols for family, cols in optional_columns.items() if cols}
    baseline_columns = [
        col for col in all_columns if not any(col in cols for cols in optional_active.values())
    ]

    variants: list[dict[str, Any]] = [
        {
            "variant": "baseline_core",
            "include_families": [],
            "feature_columns": baseline_columns,
            "feature_count": len(baseline_columns),
            "description": "Core stable features only",
        }
    ]
    for family, columns in optional_active.items():
        merged = _merge_feature_columns(baseline_columns, columns)
        variants.append(
            {
                "variant": f"plus_{family}",
                "include_families": [family],
                "feature_columns": merged,
                "feature_count": len(merged),
                "description": f"Baseline + {family} family",
            }
        )
    if optional_active:
        variants.append(
            {
                "variant": "full_active",
                "include_families": list(optional_active.keys()),
                "feature_columns": all_columns,
                "feature_count": len(all_columns),
                "description": "All currently active optional families",
            }
        )
    return variants


def build_phase2_training_report(
    df,
    *,
    ctx=None,
    report_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    detection_scores=None,
    feedback_labels=None,
    strategy: str = "hybrid",
    model_families: list[str] | tuple[str, ...] | None = None,
    phase1_case_result=None,
    hold_out_scenarios: tuple[str, ...] = DEFAULT_HOLD_OUT_SCENARIOS,
) -> Phase2TrainingReport:
    """Create the initial Phase 2 training orchestration report."""
    report = initialize_phase2_training_report(
        ctx=ctx,
        report_id=report_id,
        metadata=metadata,
    )
    settings = getattr(ctx, "settings", None) or get_settings()
    label_summary, _label_result = build_phase2_label_summary(
        df,
        detection_scores=detection_scores,
        feedback_labels=feedback_labels,
        strategy=strategy,
    )
    cleaned_df, _groups, feature_payload = prepare_phase2_feature_inputs(
        df,
        settings=settings,
    )
    phase1_case_contract = _build_phase1_case_contract_metadata(phase1_case_result)

    families = list(model_families or _DEFAULT_MODEL_FAMILIES)
    variants = feature_payload["feature_variants"]
    search_presets = build_phase2_search_presets(families)
    report.label_summary = label_summary
    report.supervised_gate = _build_supervised_gate_payload(label_summary, settings)
    report.status = Phase2TrainingStatus.RUNNING
    report.metadata.update(
        {
            "candidate_families": families,
            "phase2_training_mode": _phase2_training_mode(settings),
            "hold_out_scenarios": list(hold_out_scenarios),
            "feature_row_count": int(len(cleaned_df)),
            "feature_column_count": int(len(cleaned_df.columns)),
            "feature_variant_count": len(variants),
            "search_preset_count": sum(len(presets) for presets in search_presets.values()),
            "feature_metadata": feature_payload["feature_metadata"],
            "feature_quality_profile": feature_payload["feature_quality_profile"],
            "adjusted_feature_groups": feature_payload["adjusted_groups"],
            "preprocessing_plan": feature_payload["preprocessing_plan"],
            "phase1_case_contract": phase1_case_contract,
            "search_presets": search_presets,
        }
    )
    report.leaderboard.extend(
        _build_trial_queue(
            families=families,
            variants=variants,
            search_presets=search_presets,
        ),
    )
    return report


def run_phase2_training(
    df,
    *,
    ctx=None,
    report_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    detection_scores=None,
    feedback_labels=None,
    strategy: str = "hybrid",
    model_families: list[str] | tuple[str, ...] | None = None,
    detector_factories: dict[str, Any] | None = None,
    base_dir: Path | None = None,
    save_report: bool = True,
    phase1_case_result=None,
    hold_out_scenarios: tuple[str, ...] = DEFAULT_HOLD_OUT_SCENARIOS,
) -> Phase2TrainingReport:
    """Execute Phase 2 training trials and persist a training report."""
    report = initialize_phase2_training_report(
        ctx=ctx,
        report_id=report_id,
        metadata=metadata,
    )
    paths = ensure_phase2_training_dirs(
        build_phase2_training_paths(
            ctx=ctx,
            report_id=report.report_id,
            base_dir=base_dir,
        )
    )
    settings = getattr(ctx, "settings", None) or get_settings()
    registry_dir = getattr(ctx, "model_dir", None) or paths["promoted_dir"]
    registry = ModelRegistry(registry_dir=registry_dir)
    factories = dict(_DEFAULT_DETECTOR_FACTORIES)
    if detector_factories:
        factories.update(detector_factories)

    with TimingBlock("phase2.training.label_summary"):
        label_summary, label_result = build_phase2_label_summary(
            df,
            detection_scores=detection_scores,
            feedback_labels=feedback_labels,
            strategy=strategy,
        )
    with TimingBlock("phase2.training.prepare_feature_inputs"):
        cleaned_df, groups, feature_payload = prepare_phase2_feature_inputs(
            df,
            settings=settings,
        )
    with TimingBlock("phase2.training.split_context"):
        split_context_df = _with_unsupervised_split_context(cleaned_df, df, settings)
    phase1_case_contract = _build_phase1_case_contract_metadata(phase1_case_result)
    families = list(model_families or _DEFAULT_MODEL_FAMILIES)
    variants = feature_payload["feature_variants"]
    search_presets = build_phase2_search_presets(families)

    report.label_summary = label_summary
    report.supervised_gate = _build_supervised_gate_payload(label_summary, settings)
    report.status = Phase2TrainingStatus.RUNNING
    report.metadata.update(
        {
            "candidate_families": families,
            "phase2_training_mode": _phase2_training_mode(settings),
            "hold_out_scenarios": list(hold_out_scenarios),
            "feature_row_count": int(len(cleaned_df)),
            "feature_column_count": int(len(cleaned_df.columns)),
            "feature_variant_count": len(variants),
            "search_preset_count": sum(len(presets) for presets in search_presets.values()),
            "feature_metadata": feature_payload["feature_metadata"],
            "feature_quality_profile": feature_payload["feature_quality_profile"],
            "adjusted_feature_groups": feature_payload["adjusted_groups"],
            "preprocessing_plan": feature_payload["preprocessing_plan"],
            "phase1_case_contract": phase1_case_contract,
            "registry_dir": str(registry_dir),
            "search_presets": search_presets,
        }
    )
    with TimingBlock("phase2.training.build_trial_queue"):
        report.leaderboard = _build_trial_queue(
            families=families,
            variants=variants,
            search_presets=search_presets,
        )

    trained_results: dict[str, list[dict[str, Any]]] = {}
    label_series = (
        pd.Series(label_result.y, index=cleaned_df.index)
        if len(label_result.y) == len(cleaned_df)
        else pd.Series(dtype=int)
    )
    trials_total_block = TimingBlock("phase2.training.trials_total").__enter__()
    for trial in report.leaderboard:
        if trial.status != Phase2TrainingStatus.PENDING:
            _write_trial_artifact(paths["trials_dir"], trial)
            continue
        family = trial.model_family
        split_metadata = None
        calibration_df = None
        hold_out_eval_df = None
        eval_y = label_result.y
        if family == "unsupervised":
            split = _split_unsupervised_train_calibration(
                split_context_df,
                settings,
                hold_out_scenarios=hold_out_scenarios,
            )
            split = _apply_unsupervised_split_row_caps(split, settings)
            variant_df = _build_variant_frame(split.train_df, trial, family)
            hold_out_eval_df = split.calibration_df
            calibration_df = _build_variant_frame(split.calibration_df, trial, family)
            split_metadata = split.metadata
            if not label_series.empty and not calibration_df.empty:
                eval_y = label_series.loc[calibration_df.index].to_numpy()
            elif calibration_df.empty:
                eval_y = []
        else:
            variant_df = _build_variant_frame(cleaned_df, trial, family)
        variant_groups = _subset_feature_groups(groups, variant_df.columns)
        if family == "stacking":
            _execute_stacking_trial(
                trial=trial,
                trial_df=variant_df,
                label_result=label_result,
                groups=variant_groups,
                registry=registry,
                settings=settings,
                detector_factory=factories[family],
                trained_results=trained_results,
            )
        elif family in _RULE_STYLE_FAMILIES:
            _execute_rule_style_trial(
                trial=trial,
                trial_df=variant_df,
                label_result=label_result,
                registry=registry,
                settings=settings,
                detector_factory=factories[family],
                family=family,
                ctx=ctx,
                trained_results=trained_results,
            )
        else:
            _execute_model_trial(
                trial=trial,
                trial_df=variant_df,
                label_result=label_result,
                groups=variant_groups,
                registry=registry,
                settings=settings,
                detector_factory=factories[family],
                family=family,
                trained_results=trained_results,
                calibration_df=calibration_df,
                eval_y=eval_y,
                split_metadata=split_metadata,
                preprocessing_plan=feature_payload["preprocessing_plan"],
                hold_out_scenarios=hold_out_scenarios,
                hold_out_eval_df=hold_out_eval_df,
            )
        _write_trial_artifact(paths["trials_dir"], trial)
        log_timing(
            f"phase2.training.trial.{trial.model_family}.{trial.variant}.{trial.status.value}",
            float(trial.elapsed_sec or 0.0),
        )
    trials_total_block.__exit__(None, None, None)

    with TimingBlock("phase2.training.promote"):
        report.leaderboard = _sort_trials(report.leaderboard)
        promotion_policy = _build_promotion_policy(report.leaderboard)
        report.promoted_models = _select_promoted_models(
            report.leaderboard,
            policy=promotion_policy,
        )
        _write_rule_style_promoted_artifacts(
            ctx=ctx,
            promoted_models=report.promoted_models,
            trials=report.leaderboard,
            report_id=report.report_id,
        )
    if report.promoted_models:
        report.metadata["best_overall_model"] = report.promoted_models[0].to_dict()
    report.metadata.update(_build_trial_report_metadata(report.leaderboard))
    hold_out_summary = _build_hold_out_report_summary(report.leaderboard)
    if hold_out_summary:
        report.metadata["hold_out_evaluation"] = hold_out_summary
    report.metadata["promotion_policy"] = promotion_policy
    report.metadata["family_promotion_decisions"] = _build_family_promotion_decisions(
        report.leaderboard,
        promotion_policy,
    )
    report.metadata["inference_contract"] = _build_inference_contract(
        report_id=report.report_id,
        promoted_models=report.promoted_models,
        promotion_policy=promotion_policy,
        trials=report.leaderboard,
        phase1_case_contract=phase1_case_contract,
    )
    report.status = _finalize_report_status(report.leaderboard)
    if save_report:
        with TimingBlock("phase2.training.save_report"):
            save_phase2_training_report(report, ctx=ctx, base_dir=base_dir)
    return report


def run_phase2_training_analysis(
    state,
    *,
    training_runner=None,
    settings_factory=None,
) -> Phase2TrainingReport:
    """Execute Phase 2 training from dashboard/session state."""
    from dashboard._state import (
        KEY_COMPANY_CONTEXT,
        KEY_PHASE1_RESULT,
        KEY_PHASE2_TRAINING_REPORT_ID,
        KEY_PREP_RESULT,
        KEY_SETTINGS,
    )
    from src.services.analysis_service import make_phase_settings

    if training_runner is None:
        training_runner = run_phase2_training

    prep_result = state.get(KEY_PREP_RESULT)
    if prep_result is None:
        raise RuntimeError("Phase 2 training requires prepared data.")

    featured_df = (
        prep_result.featured_data
        if getattr(prep_result, "featured_data", None) is not None
        else prep_result.data
    )
    ctx = state.get(KEY_COMPANY_CONTEXT)
    settings = make_phase_settings(
        state.get(KEY_SETTINGS),
        phase="phase2",
        settings_factory=settings_factory,
    )
    if ctx is not None and hasattr(ctx, "clone_with_settings"):
        ctx = ctx.clone_with_settings(settings)

    # Why: KEY_PHASE1_RESULT는 PipelineResult 객체. run_phase2_training은 그 안의
    #      Phase1CaseResult(cases 속성)를 기대 — PipelineResult.phase1_case_result로 추출.
    phase1_pipeline = state.get(KEY_PHASE1_RESULT)
    phase1_case = (
        getattr(phase1_pipeline, "phase1_case_result", None)
        if phase1_pipeline is not None
        else None
    )

    report = training_runner(
        featured_df,
        ctx=ctx,
        metadata={"source": "streamlit", "file_name": getattr(prep_result, "file_name", "")},
        phase1_case_result=phase1_case,
    )
    state[KEY_PHASE2_TRAINING_REPORT_ID] = report.report_id
    return report


def _build_trial_queue(
    *,
    families: list[str],
    variants: list[dict[str, Any]],
    search_presets: dict[str, list[dict[str, Any]]],
) -> list[Phase2TrialResult]:
    queue: list[Phase2TrialResult] = []
    for family in families:
        family_variants = _trial_variants_for_family(family, variants)
        for variant in family_variants:
            for preset in search_presets.get(family, []):
                queue.append(
                    Phase2TrialResult(
                        model_family=family,
                        variant=f"{variant['variant']}__{preset['name']}",
                        status=Phase2TrainingStatus.PENDING,
                        params={
                            "feature_variant": str(variant["variant"]),
                            "search_name": str(preset["name"]),
                            "include_families": list(variant["include_families"]),
                            "feature_columns": list(variant["feature_columns"]),
                            "feature_count": int(variant["feature_count"]),
                            "settings_updates": dict(preset.get("settings_updates", {})),
                            "detector_kwargs": dict(preset.get("detector_kwargs", {})),
                        },
                        gate_reason=None,
                        metadata={
                            "description": variant["description"],
                            "family_role": (
                                "core"
                                if family == "unsupervised"
                                else "extended"
                                if family in _RULE_STYLE_FAMILIES
                                else "optional"
                            ),
                            "search_name": str(preset["name"]),
                            "sub_detector_keys": list(_RULE_STYLE_SUB_DETECTORS.get(family, ())),
                        },
                    )
                )
    return queue


def _trial_variants_for_family(
    family: str,
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return feature variants that produce distinct trials for this family."""
    if family not in _RULE_STYLE_FAMILIES:
        return variants
    for variant in variants:
        if str(variant.get("variant", "")) == "baseline_core":
            return [variant]
    return variants[:1]


def _execute_model_trial(
    *,
    trial: Phase2TrialResult,
    trial_df,
    label_result,
    groups,
    registry: ModelRegistry,
    settings,
    detector_factory,
    family: str,
    trained_results: dict[str, list[dict[str, Any]]],
    calibration_df=None,
    eval_y=None,
    split_metadata: dict[str, Any] | None = None,
    preprocessing_plan: dict[str, Any] | None = None,
    hold_out_scenarios: tuple[str, ...] = DEFAULT_HOLD_OUT_SCENARIOS,
    hold_out_eval_df=None,
) -> None:
    start = time.perf_counter()
    trial_settings = _build_trial_settings(settings, trial)
    detector = _build_detector(
        detector_factory,
        settings=trial_settings,
        registry=registry,
        detector_kwargs=trial.params.get("detector_kwargs", {}),
    )
    try:
        matrix_metadata = None
        detection_df = trial_df
        training_df = trial_df
        training_groups = groups
        train_y = _align_labels_to_index(label_result.y, trial_df.index)
        if family == "unsupervised":
            if preprocessing_plan is not None:
                matrix_builder = Phase2AutoencoderMatrixBuilder(
                    preprocessing_plan,
                    rare_min_count=int(
                        getattr(trial_settings, "phase2_low_card_rare_min_count", 2),
                    ),
                ).fit(trial_df)
                train_matrix = matrix_builder.transform(trial_df)
                calibration_matrix = (
                    matrix_builder.transform(calibration_df)
                    if calibration_df is not None and not calibration_df.empty
                    else pd.DataFrame(columns=train_matrix.columns)
                )
                train_matrix.attrs["phase2_matrix_prepared"] = True
                calibration_matrix.attrs["phase2_matrix_prepared"] = True
                feature_group_map = dict(matrix_builder.output_feature_groups_)
                train_matrix.attrs["phase2_feature_group_map"] = feature_group_map
                calibration_matrix.attrs["phase2_feature_group_map"] = feature_group_map
                training_df = train_matrix
                training_groups = _matrix_feature_groups(train_matrix)
                detection_df = calibration_matrix
                matrix_metadata = matrix_builder.to_metadata()
                matrix_metadata.update(
                    {
                        "train_matrix_shape": list(train_matrix.shape),
                        "calibration_matrix_shape": list(calibration_matrix.shape),
                    }
                )
            train_info = detector.train(training_df, training_groups, y=train_y)
            if matrix_metadata is not None and hasattr(detector, "set_phase2_matrix_state"):
                detector.set_phase2_matrix_state(matrix_builder, matrix_metadata)
            if (
                preprocessing_plan is None
                and calibration_df is not None
                and not calibration_df.empty
            ):
                detection_df = calibration_df
        else:
            train_info = detector.train(trial_df, label_result, groups)
        detect_result = detector.detect(detection_df)
        effective_y = eval_y if eval_y is not None else label_result.y
        if family == "unsupervised" and not _has_positive_labels(effective_y):
            metric_name, metric_value, unsupervised_metric = _compute_unsupervised_metric(
                detect_result,
                settings=trial_settings,
                train_scores=getattr(detector, "ensemble_train_scores_", None),
            )
        else:
            metric_name, metric_value = _compute_trial_metric(detect_result, effective_y)
            unsupervised_metric = None
        save_meta = detector.save_model(metric_value or 0.0)
        trial.status = Phase2TrainingStatus.COMPLETED
        trial.metric_name = metric_name
        trial.metric_value = metric_value
        trial.params.update(_compact_train_info(train_info))
        trial.metadata.update(
            {
                "settings_updates": dict(trial.params.get("settings_updates", {})),
                "saved_model_name": getattr(save_meta, "model_name", family),
                "registry_version": getattr(save_meta, "version", None),
                "registry_path": getattr(save_meta, "file_path", None),
            }
        )
        if isinstance(train_info, dict):
            for diagnostic_key in ("vae_diagnostics", "if_diagnostics"):
                if diagnostic_key in train_info:
                    trial.metadata[diagnostic_key] = train_info[diagnostic_key]
        if unsupervised_metric is not None:
            trial.metadata["unsupervised_metric"] = unsupervised_metric
        if family == "unsupervised" and hold_out_eval_df is not None:
            hold_out_metrics = build_hold_out_metrics(
                hold_out_eval_df,
                detect_result,
                hold_out_scenarios=hold_out_scenarios,
            )
            trial.metadata["hold_out_evaluation"] = hold_out_metrics
        if split_metadata is not None:
            trial.metadata["train_calibration_split"] = dict(split_metadata)
        if matrix_metadata is not None:
            trial.metadata["matrix_builder"] = matrix_metadata
        trained_results.setdefault(family, []).append(
            {
                "trial_variant": trial.variant,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "detector": detector,
                "detect_result": detect_result,
                "save_meta": save_meta,
                "train_info": train_info,
            }
        )
    except SupervisedGateError as exc:
        trial.status = Phase2TrainingStatus.SKIPPED
        trial.gate_reason = exc.reason
        trial.metadata["supervised_gate"] = dict(exc.snapshot)
        trial.warnings.append(str(exc))
    except Exception as exc:
        trial.status = Phase2TrainingStatus.FAILED
        trial.gate_reason = trial.gate_reason or type(exc).__name__
        trial.warnings.append(str(exc))
    finally:
        trial.elapsed_sec = time.perf_counter() - start


def _matrix_feature_groups(matrix: pd.DataFrame) -> FeatureGroups:
    """Treat a prepared Phase 2 autoencoder matrix as numeric model input."""
    return FeatureGroups(numeric=list(matrix.columns))


def _align_labels_to_index(y, index: pd.Index):
    """Align full-dataset labels to the split index used for unsupervised training."""
    if y is None:
        return None
    series = pd.Series(y)
    aligned = series.reindex(index)
    if aligned.isna().any():
        return None
    return aligned.to_numpy()


def _execute_stacking_trial(
    *,
    trial: Phase2TrialResult,
    trial_df,
    label_result,
    groups,
    registry: ModelRegistry,
    settings,
    detector_factory,
    trained_results: dict[str, list[dict[str, Any]]],
) -> None:
    start = time.perf_counter()
    required = ("unsupervised", "supervised", "transformer", "sequence")
    missing = [family for family in required if not trained_results.get(family)]
    if missing:
        trial.status = Phase2TrainingStatus.SKIPPED
        trial.gate_reason = "missing_base_models"
        trial.warnings.append("missing trained base models: " + ", ".join(missing))
        trial.elapsed_sec = time.perf_counter() - start
        return

    trial_settings = _build_trial_settings(settings, trial)
    detector = _build_detector(
        detector_factory,
        settings=trial_settings,
        registry=registry,
        detector_kwargs=trial.params.get("detector_kwargs", {}),
    )
    try:
        best_inputs = {
            family: _select_best_trained_entry(trained_results[family]) for family in required
        }
        oof_ready = (
            hasattr(detector, "train_oof")
            and groups is not None
            and "created_by" in trial_df.columns
            and trial_df["created_by"].nunique(dropna=True) >= 2
        )
        if oof_ready:
            base_results = [best_inputs["unsupervised"]["detect_result"]]
            created_by_user_ids = trial_df["created_by"].astype(str).to_numpy()
            assert np.array_equal(
                created_by_user_ids,
                trial_df["created_by"].astype(str).to_numpy(),
            ), "ensemble train_oof user_ids must be created_by"
            train_info = detector.train_oof(
                trial_df,
                label_result,
                user_ids=created_by_user_ids,
                df_index=trial_df.index,
                non_leakage_results=base_results,
                groups=groups,
            )
            inference_results = [
                best_inputs["unsupervised"]["detect_result"],
                best_inputs["supervised"]["detect_result"],
                best_inputs["transformer"]["detect_result"],
                best_inputs["sequence"]["detect_result"],
            ]
            detect_result = detector.detect_from_results(inference_results, trial_df.index)
        else:
            base_results = [
                best_inputs["unsupervised"]["detect_result"],
                best_inputs["supervised"]["detect_result"],
                best_inputs["transformer"]["detect_result"],
                best_inputs["sequence"]["detect_result"],
            ]
            train_info = detector.train_from_results(base_results, label_result.y, trial_df.index)
            detect_result = detector.detect_from_results(base_results, trial_df.index)
        metric_name, metric_value = _compute_trial_metric(detect_result, label_result.y)
        save_meta = detector.save_model(metric_value or 0.0)
        trial.status = Phase2TrainingStatus.COMPLETED
        trial.metric_name = metric_name
        trial.metric_value = metric_value
        trial.params.update(_compact_train_info(train_info))
        trial.metadata.update(
            {
                "settings_updates": dict(trial.params.get("settings_updates", {})),
                "stacking_mode": str(train_info.get("mode", "stacking")),
                "base_input_variants": (
                    {
                        "unsupervised": best_inputs["unsupervised"]["trial_variant"],
                        "supervised": trial.variant,
                        "transformer": trial.variant,
                        "sequence": trial.variant,
                    }
                    if oof_ready
                    else {family: best_inputs[family]["trial_variant"] for family in required}
                ),
                "saved_model_name": getattr(save_meta, "model_name", "stacking"),
                "registry_version": getattr(save_meta, "version", None),
                "registry_path": getattr(save_meta, "file_path", None),
            }
        )
    except Exception as exc:
        trial.status = Phase2TrainingStatus.FAILED
        trial.gate_reason = trial.gate_reason or type(exc).__name__
        trial.warnings.append(str(exc))
    finally:
        trial.elapsed_sec = time.perf_counter() - start


def _execute_rule_style_trial(
    *,
    trial: Phase2TrialResult,
    trial_df,
    label_result,
    registry: ModelRegistry,
    settings,
    detector_factory,
    family: str,
    ctx,
    trained_results: dict[str, list[dict[str, Any]]],
) -> None:
    start = time.perf_counter()
    trial_settings = _build_trial_settings(settings, trial)
    detector = _build_detector(
        detector_factory,
        settings=trial_settings,
        registry=registry,
        detector_kwargs=_build_rule_style_detector_kwargs(
            family,
            ctx=ctx,
            detector_kwargs=trial.params.get("detector_kwargs", {}),
        ),
    )
    try:
        detect_result = detector.detect(trial_df)
        metric_name, metric_value = _compute_rule_style_metric(
            family,
            detect_result,
            label_result.y,
        )
        trial.status = Phase2TrainingStatus.COMPLETED
        trial.metric_name = metric_name
        trial.metric_value = metric_value
        trial.metadata.update(
            {
                "settings_updates": dict(trial.params.get("settings_updates", {})),
                "saved_model_name": _canonical_phase2_model_name(family),
                "registry_version": None,
                "registry_path": None,
                "track_name": getattr(detector, "track_name", family),
                "sub_detector_keys": list(_RULE_STYLE_SUB_DETECTORS.get(family, ())),
                "rule_flag_ids": [flag.rule_id for flag in detect_result.rule_flags],
                "flagged_count": int(len(detect_result.flagged_indices)),
                "metric_interpretation": "rule_proxy_score",
            }
        )
        trained_results.setdefault(family, []).append(
            {
                "trial_variant": trial.variant,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "detector": detector,
                "detect_result": detect_result,
                "save_meta": None,
                "train_info": {"mode": "rule_style_detect_only"},
            }
        )
    except Exception as exc:
        trial.status = Phase2TrainingStatus.FAILED
        trial.gate_reason = trial.gate_reason or type(exc).__name__
        trial.warnings.append(str(exc))
    finally:
        trial.elapsed_sec = time.perf_counter() - start


def _compute_trial_metric(detect_result, y_true) -> tuple[str, float | None]:
    if len(y_true) == 0:
        flagged_ratio = float(
            len(detect_result.flagged_indices) / max(len(detect_result.scores), 1)
        )
        return "flagged_ratio", flagged_ratio
    positives = int((pd.Series(y_true) == 1).sum())
    if positives > 0:
        flagged = set(int(idx) for idx in detect_result.flagged_indices)
        y_pred = [1 if int(idx) in flagged else 0 for idx in detect_result.scores.index]
        return "f1_macro", float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    flagged_ratio = float(len(detect_result.flagged_indices) / max(len(detect_result.scores), 1))
    return "flagged_ratio", flagged_ratio


def _compute_unsupervised_metric(
    detect_result,
    *,
    settings=None,
    train_scores=None,
) -> tuple[str, float, dict[str, Any]]:
    """Compute a no-label ranking proxy for unsupervised Phase 2 selection."""
    scores = pd.Series(detect_result.scores).astype(float).replace([np.inf, -np.inf], np.nan)
    scores = scores.dropna()
    total_count = int(len(detect_result.scores))
    flagged_ratio = float(len(detect_result.flagged_indices) / max(total_count, 1))
    capacity_ratio = float(getattr(settings, "phase2_review_capacity_ratio", 0.10) or 0.10)
    capacity_ratio = min(max(capacity_ratio, 0.001), 0.50)

    warnings = [str(value) for value in getattr(detect_result, "warnings", [])]
    if scores.empty:
        components = {
            "score_tail_gap": 0.0,
            "topk_stability": 0.0,
            "capacity_penalty": 1.0,
            "score_degeneracy_penalty": 1.0,
            "flagged_ratio": flagged_ratio,
        }
        metadata = _build_unsupervised_metric_metadata(
            components=components,
            review_capacity_ratio=capacity_ratio,
            review_threshold=None,
            reliability_warnings=["nan_score_distribution", *warnings],
        )
        return "unsupervised_selection_score", 0.0, metadata

    review_threshold = float(scores.quantile(1.0 - capacity_ratio))
    capacity_mask = scores >= review_threshold
    capacity_flagged_ratio = float(capacity_mask.mean())
    tail_scores = scores[capacity_mask]
    body_scores = scores[~capacity_mask]
    score_range = max(float(scores.max() - scores.min()), 1e-12)
    tail_mean = float(tail_scores.mean()) if len(tail_scores) else float(scores.max())
    body_mean = float(body_scores.mean()) if len(body_scores) else float(scores.min())
    score_tail_gap = float(np.clip((tail_mean - body_mean) / score_range, 0.0, 1.0))

    topk_count = max(1, int(np.ceil(len(scores) * capacity_ratio)))
    topk_scores = scores.nlargest(topk_count)
    topk_stability = 1.0 - min(
        float(topk_scores.std(ddof=0) / max(scores.std(ddof=0), 1e-12)),
        1.0,
    )
    unique_ratio = float(scores.nunique(dropna=True) / max(len(scores), 1))
    score_std = float(scores.std(ddof=0))
    score_degeneracy_penalty = 1.0 if score_std <= 1e-12 or unique_ratio <= 0.2 else 0.0
    capacity_penalty = min(
        abs(capacity_flagged_ratio - capacity_ratio) / max(capacity_ratio, 1e-12),
        1.0,
    )
    drift = _train_calibration_score_drift(train_scores, scores)
    components = {
        "score_tail_gap": score_tail_gap,
        "topk_stability": float(np.clip(topk_stability, 0.0, 1.0)),
        "capacity_penalty": float(capacity_penalty),
        "score_degeneracy_penalty": float(score_degeneracy_penalty),
        "flagged_ratio": flagged_ratio,
        "capacity_flagged_ratio": capacity_flagged_ratio,
        "train_calibration_drift": float(drift) if drift is not None else None,
    }
    reliability_warnings = list(warnings)
    if score_std <= 1e-12:
        reliability_warnings.append("score_flat")
    if components["topk_stability"] <= 0.05:
        reliability_warnings.append("topk_unstable")
    if drift is not None and drift > 0.35:
        reliability_warnings.append("train_calibration_drift")
    if score_degeneracy_penalty >= 0.75:
        reliability_warnings.append("degenerate_score_distribution")
    severe_warnings = sorted(set(reliability_warnings) & _SEVERE_UNSUPERVISED_RELIABILITY_WARNINGS)
    score = (
        (0.55 * components["score_tail_gap"])
        + (0.30 * components["topk_stability"])
        - (0.10 * components["capacity_penalty"])
        - (0.35 * components["score_degeneracy_penalty"])
    )
    if severe_warnings:
        score = min(score, 0.0)
    metadata = _build_unsupervised_metric_metadata(
        components=components,
        review_capacity_ratio=capacity_ratio,
        review_threshold=review_threshold,
        reliability_warnings=reliability_warnings,
    )
    return "unsupervised_selection_score", float(np.clip(score, 0.0, 1.0)), metadata


def _build_unsupervised_metric_metadata(
    *,
    components: dict[str, float],
    review_capacity_ratio: float,
    review_threshold: float | None,
    reliability_warnings: list[str],
) -> dict[str, Any]:
    severe_warnings = sorted(set(reliability_warnings) & _SEVERE_UNSUPERVISED_RELIABILITY_WARNINGS)
    return {
        "metric_interpretation": "ranking_proxy_not_fraud_accuracy",
        "metric_name": "unsupervised_selection_score",
        "components": components,
        "review_capacity_ratio": review_capacity_ratio,
        "review_threshold": review_threshold,
        "reliability_warnings": sorted(set(reliability_warnings)),
        "severe_reliability_warnings": severe_warnings,
        "promotion_eligible": not severe_warnings,
    }


def _train_calibration_score_drift(train_scores, calibration_scores: pd.Series) -> float | None:
    if train_scores is None:
        return None
    train = pd.Series(train_scores).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    calibration = (
        pd.Series(calibration_scores).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    )
    if train.empty or calibration.empty:
        return None
    return abs(float(train.mean()) - float(calibration.mean()))


def _has_positive_labels(y_true) -> bool:
    if len(y_true) == 0:
        return False
    return int((pd.Series(y_true) == 1).sum()) > 0


def _compute_rule_style_metric(
    family: str,
    detect_result,
    y_true,
) -> tuple[str, float | None]:
    metric_name = _RULE_STYLE_METRIC_NAMES.get(str(family), "rule_proxy_score")
    if len(y_true) > 0 and int((pd.Series(y_true) == 1).sum()) > 0:
        _truth_metric_name, metric_value = _compute_trial_metric(detect_result, y_true)
        return metric_name, metric_value
    flagged_ratio = float(len(detect_result.flagged_indices) / max(len(detect_result.scores), 1))
    score_mean = float(pd.Series(detect_result.scores).fillna(0.0).mean())
    proxy_metric = min((flagged_ratio * 0.7) + (score_mean * 0.3), 1.0)
    return metric_name, proxy_metric


def _compact_train_info(train_info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in dict(train_info or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, (list, tuple)) and len(value) <= 10:
            compact[key] = list(value)
    return compact


def build_phase2_search_presets(
    families: list[str] | tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    return {
        family: [
            dict(preset) for preset in _DEFAULT_SEARCH_PRESETS.get(family, ({"name": "default"},))
        ]
        for family in families
    }


def _build_variant_frame(cleaned_df, trial: Phase2TrialResult, family: str):
    if family in _RULE_STYLE_FAMILIES:
        required = list(cleaned_df.columns)
        for col in _RULE_STYLE_REQUIRED_COLUMNS.get(family, ()):
            if col in cleaned_df.columns and col not in required:
                required.append(col)
        return cleaned_df.loc[:, [col for col in required if col in cleaned_df.columns]].copy()
    selected = list(trial.params.get("feature_columns", []))
    required = list(selected)
    if family in {"sequence", "stacking"}:
        for col in _SEQUENCE_CONTEXT_COLUMNS:
            if col in cleaned_df.columns and col not in required:
                required.append(col)
    return cleaned_df.loc[:, [col for col in required if col in cleaned_df.columns]].copy()


def _with_unsupervised_split_context(cleaned_df, source_df, settings):
    """Attach split-only keys without adding them to selected model features."""
    split_df = cleaned_df.copy()
    context_columns = {
        str(getattr(settings, "phase2_split_group_column", "document_id") or "document_id"),
        str(getattr(settings, "phase2_temporal_column", "posting_date") or "posting_date"),
        "mutation_type",
    }
    for col in context_columns:
        if col in split_df.columns or col not in source_df.columns:
            continue
        split_df[col] = source_df.loc[split_df.index, col]
    return split_df


def _build_trial_settings(settings, trial: Phase2TrialResult):
    updates = dict(trial.params.get("settings_updates", {}))
    if not updates:
        return settings
    if hasattr(settings, "model_copy"):
        return settings.model_copy(update=updates)
    cloned = dict(getattr(settings, "__dict__", {}))
    cloned.update(updates)
    return type(settings)(**cloned)


def _build_detector(detector_factory, *, settings, registry, detector_kwargs: dict[str, Any]):
    kwargs = dict(detector_kwargs or {})
    try:
        return detector_factory(settings=settings, model_registry=registry, **kwargs)
    except TypeError:
        try:
            return detector_factory(settings=settings, **kwargs)
        except TypeError:
            try:
                return detector_factory(settings=settings, model_registry=registry)
            except TypeError:
                return detector_factory(settings=settings)


def _build_rule_style_detector_kwargs(
    family: str,
    *,
    ctx,
    detector_kwargs: dict[str, Any],
) -> dict[str, Any]:
    kwargs = dict(detector_kwargs or {})
    if family in {"relational", "intercompany"}:
        audit_rules = getattr(ctx, "audit_rules", None)
        if audit_rules:
            kwargs.setdefault("audit_rules", audit_rules)
    return kwargs


def _subset_feature_groups(groups, columns) -> Any:
    if groups is None:
        return None
    selected = set(columns)
    return type(groups)(
        numeric=[col for col in groups.numeric if col in selected],
        categorical_high=[col for col in groups.categorical_high if col in selected],
        categorical_low=[col for col in groups.categorical_low if col in selected],
        boolean=[col for col in groups.boolean if col in selected],
        ordinal=[col for col in groups.ordinal if col in selected],
        excluded=[col for col in groups.excluded if col in selected],
    )


def _write_trial_artifact(trials_dir: Path, trial: Phase2TrialResult) -> Path:
    artifact_path = trials_dir / f"{trial.model_family}__{trial.variant}.json"
    artifact_path.write_text(
        json.dumps(trial.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trial.artifact_path = str(artifact_path)
    return artifact_path


def _finalize_report_status(trials: list[Phase2TrialResult]) -> Phase2TrainingStatus:
    statuses = {trial.status for trial in trials}
    if statuses and statuses <= {Phase2TrainingStatus.SKIPPED}:
        return Phase2TrainingStatus.SKIPPED
    if Phase2TrainingStatus.FAILED in statuses:
        completed = any(status == Phase2TrainingStatus.COMPLETED for status in statuses)
        return Phase2TrainingStatus.COMPLETED if completed else Phase2TrainingStatus.FAILED
    if any(status == Phase2TrainingStatus.COMPLETED for status in statuses):
        return Phase2TrainingStatus.COMPLETED
    return Phase2TrainingStatus.RUNNING


def _select_best_trained_entry(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        entries,
        key=lambda item: (
            item.get("metric_value") if item.get("metric_value") is not None else float("-inf"),
            item.get("trial_variant", ""),
        ),
    )


def _sort_trials(trials: list[Phase2TrialResult]) -> list[Phase2TrialResult]:
    status_rank = {
        Phase2TrainingStatus.COMPLETED: 0,
        Phase2TrainingStatus.RUNNING: 1,
        Phase2TrainingStatus.PENDING: 2,
        Phase2TrainingStatus.SKIPPED: 3,
        Phase2TrainingStatus.FAILED: 4,
    }
    return sorted(
        trials,
        key=lambda trial: (
            status_rank.get(trial.status, 99),
            -(trial.metric_value if trial.metric_value is not None else float("-inf")),
            trial.model_family,
            trial.variant,
        ),
    )


def _select_promoted_models(
    trials: list[Phase2TrialResult],
    *,
    policy: dict[str, Any] | None = None,
) -> list[Phase2PromotedModel]:
    winners: list[Phase2PromotedModel] = []
    promotion_policy = dict(policy or {})
    completed = _eligible_promotion_trials(trials, promotion_policy)
    by_family: dict[str, list[Phase2TrialResult]] = {}
    for trial in completed:
        by_family.setdefault(trial.model_family, []).append(trial)

    for family, family_trials in by_family.items():
        best = max(family_trials, key=_promotion_sort_key)
        winners.append(
            Phase2PromotedModel(
                model_name=_canonical_phase2_model_name(family),
                source_trial_variant=best.variant,
                metric_name=best.metric_name,
                metric_value=float(best.metric_value or 0.0),
                registry_version=best.metadata.get("registry_version"),
                registry_path=best.metadata.get("registry_path"),
            )
        )

    winners.sort(key=lambda item: item.metric_value, reverse=True)
    return winners


def _write_rule_style_promoted_artifacts(
    *,
    ctx,
    promoted_models: list[Phase2PromotedModel],
    trials: list[Phase2TrialResult],
    report_id: str,
) -> None:
    if ctx is None or getattr(ctx, "model_dir", None) is None:
        return
    by_family_variant = {(trial.model_family, trial.variant): trial for trial in trials}
    reverse_family_map = {
        canonical_name: family_name
        for family_name, canonical_name in _FAMILY_TO_CANONICAL_MODEL.items()
    }
    for model in promoted_models:
        family = reverse_family_map.get(model.model_name, model.model_name)
        if family not in _RULE_STYLE_FAMILIES:
            continue
        trial = by_family_variant.get((family, model.source_trial_variant))
        if trial is None:
            continue
        family_root = Path(getattr(ctx, "model_dir")) / f"phase2_{family}"
        version = _next_rule_style_artifact_version(family_root)
        artifact_dir = build_promoted_model_artifact_dir(ctx, family=family, version=version)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "calibration_metadata.json"
        payload = {
            "schema_version": 1,
            "report_id": report_id,
            "family": family,
            "model_name": model.model_name,
            "source_trial_variant": model.source_trial_variant,
            "metric_name": model.metric_name,
            "metric_value": model.metric_value,
            "metric_interpretation": trial.metadata.get(
                "metric_interpretation",
                "rule_proxy_score",
            ),
            "schema_hash": _trial_schema_hash(trial),
            "model_bundle": None,
            "calibration": {
                "mode": "stateless_rule_detector",
                "settings_updates": dict(trial.metadata.get("settings_updates", {})),
                "sub_detector_keys": list(trial.metadata.get("sub_detector_keys", [])),
                "flagged_count": int(trial.metadata.get("flagged_count", 0) or 0),
            },
        }
        artifact_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        trial.metadata["registry_path"] = str(artifact_path)
        model.registry_path = str(artifact_path)
        model.registry_version = None


def _next_rule_style_artifact_version(family_root: Path) -> int:
    if not family_root.exists():
        return 1
    versions: list[int] = []
    for child in family_root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if len(name) == 5 and name.startswith("v") and name[1:].isdigit():
            versions.append(int(name[1:]))
    return max(versions, default=0) + 1


def _build_trial_report_metadata(
    trials: list[Phase2TrialResult],
) -> dict[str, Any]:
    return {
        "trial_status_counts": _count_trial_statuses(trials),
        "family_summaries": _build_family_summaries(trials),
        "search_summaries": _build_search_summaries(trials),
        "feature_variant_summaries": _build_feature_variant_summaries(trials),
        "sub_detector_summaries": _build_sub_detector_summaries(trials),
    }


def _build_hold_out_report_summary(
    trials: list[Phase2TrialResult],
) -> dict[str, Any]:
    candidates = [
        trial
        for trial in trials
        if trial.status == Phase2TrainingStatus.COMPLETED
        and isinstance(trial.metadata.get("hold_out_evaluation"), dict)
        and trial.metadata["hold_out_evaluation"].get("available")
    ]
    if not candidates:
        return {}
    best = max(
        candidates,
        key=lambda trial: (
            trial.metadata["hold_out_evaluation"].get("hold_out_recall") or 0.0,
            trial.metric_value or 0.0,
        ),
    )
    payload = dict(best.metadata["hold_out_evaluation"])
    payload["source_trial_variant"] = best.variant
    payload["source_model_family"] = best.model_family
    return payload


def _build_promotion_policy(trials: list[Phase2TrialResult]) -> dict[str, Any]:
    completed = [trial for trial in trials if trial.status == Phase2TrainingStatus.COMPLETED]
    failed = [trial for trial in trials if trial.status == Phase2TrainingStatus.FAILED]
    family_completed_counts: dict[str, int] = {}
    for trial in completed:
        family_completed_counts[trial.model_family] = (
            family_completed_counts.get(trial.model_family, 0) + 1
        )
    family_failed_counts: dict[str, int] = {}
    for trial in failed:
        family_failed_counts[trial.model_family] = (
            family_failed_counts.get(trial.model_family, 0) + 1
        )
    family_search_diversity: dict[str, int] = {}
    for family in {trial.model_family for trial in completed}:
        search_names = {
            str(
                trial.metadata.get("search_name")
                or trial.params.get("search_name")
                or trial.variant
            )
            for trial in completed
            if trial.model_family == family
        }
        family_search_diversity[family] = len(search_names)
    metric_names = sorted({trial.metric_name for trial in completed if trial.metric_name})
    return {
        "selection_mode": "best_per_family",
        "eligible_model_families": [
            "unsupervised",
            "timeseries",
            "relational",
            "duplicate",
            "intercompany",
        ],
        "eligible_statuses": [Phase2TrainingStatus.COMPLETED.value],
        "requires_registry_version": True,
        "requires_metric_value": True,
        "min_completed_trials_per_family": 2,
        "family_min_completed_trials": dict(_DEFAULT_FAMILY_MIN_COMPLETED_TRIALS),
        "family_min_metric": dict(_DEFAULT_FAMILY_MIN_METRIC),
        "family_min_search_variants": {
            # Why (2026-05-23): unsupervised는 balanced preset 1개만 운영(75% 절감안)
            # 이라 search_variants 최소를 1로 완화. 다른 family는 preset 2개 유지.
            family: (1 if family == "unsupervised" else 2)
            for family in set(_DEFAULT_FAMILY_MIN_COMPLETED_TRIALS)
        },
        "family_max_failed_trial_ratio": {
            family: 0.5 for family in set(_DEFAULT_FAMILY_MIN_COMPLETED_TRIALS)
        },
        "artifactless_families": sorted(_RULE_STYLE_FAMILIES),
        "sort_priority": [
            "metric_value_desc",
            "elapsed_sec_asc",
            "variant_asc",
        ],
        "tie_break_policy": {
            "primary": "metric_value_desc",
            "secondary": "elapsed_sec_asc",
            "tertiary": "variant_asc",
        },
        "metric_names_seen": metric_names,
        "completed_trial_count": len(completed),
        "family_completed_counts": family_completed_counts,
        "family_failed_counts": family_failed_counts,
        "family_search_diversity": family_search_diversity,
        "rule_style_metric_policy": {
            "metric_name": "rule_proxy_score",
            "family_metric_names": dict(_RULE_STYLE_METRIC_NAMES),
            "interpretation": (
                "Family-specific rule metric names carry detector semantics; "
                "values are proxy scores for selection, not truth recall."
            ),
            "components": {
                "flagged_ratio": 0.7,
                "score_mean": 0.3,
            },
        },
        "unsupervised_metric_policy": {
            "metric_name": "unsupervised_selection_score",
            "interpretation": "ranking_proxy_not_fraud_accuracy",
            "components": [
                "score_tail_gap",
                "topk_stability",
                "capacity_penalty",
                "score_degeneracy_penalty",
            ],
            "flagged_ratio_role": "metadata_only",
            "promotion_contract_families": ["unsupervised"],
        },
    }


def _build_inference_contract(
    *,
    report_id: str,
    promoted_models: list[Phase2PromotedModel],
    promotion_policy: dict[str, Any],
    trials: list[Phase2TrialResult],
    phase1_case_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    promoted_versions = {
        model.model_name: model.registry_version
        for model in promoted_models
        if model.registry_version is not None
    }
    required_models = [model.model_name for model in promoted_models]
    contract = {
        "source_report_id": report_id,
        "selection_mode": promotion_policy.get("selection_mode", "best_per_family"),
        "required_models": required_models,
        "promoted_versions": promoted_versions,
        "model_versions": _build_model_version_contract(promoted_models, trials),
        "family_sub_detectors": _build_promoted_sub_detector_map(promoted_models, trials),
        "track_map": {
            model_name: track_name
            for model_name, track_name in _PROMOTED_TRACK_MAP.items()
            if model_name in required_models
        },
    }
    if phase1_case_contract is not None:
        contract["phase1_case_contract"] = phase1_case_contract
    return contract


def _build_model_version_contract(
    promoted_models: list[Phase2PromotedModel],
    trials: list[Phase2TrialResult],
) -> dict[str, dict[str, Any]]:
    by_family_variant = {(trial.model_family, trial.variant): trial for trial in trials}
    reverse_family_map = {
        canonical_name: family_name
        for family_name, canonical_name in _FAMILY_TO_CANONICAL_MODEL.items()
    }
    contract: dict[str, dict[str, Any]] = {}
    for model in promoted_models:
        family_name = reverse_family_map.get(model.model_name, model.model_name)
        trial = by_family_variant.get((family_name, model.source_trial_variant))
        contract[model.model_name] = {
            "model_version": model.registry_version,
            "source_trial_variant": model.source_trial_variant,
            "schema_hash": _trial_schema_hash(trial),
            "registry_path": model.registry_path,
            "fixture_contract": {
                "feature_index_name": "phase1_case_id",
                "requires_schema_match": True,
            },
        }
    return contract


def _trial_schema_hash(trial: Phase2TrialResult | None) -> str | None:
    if trial is None:
        return None
    matrix = trial.metadata.get("matrix_builder")
    if isinstance(matrix, dict) and matrix.get("schema_hash") is not None:
        return str(matrix["schema_hash"])
    feature_quality = trial.feature_quality_profile or trial.metadata.get(
        "feature_quality_profile",
    )
    if isinstance(feature_quality, dict) and feature_quality.get("schema_hash") is not None:
        return str(feature_quality["schema_hash"])
    return None


def _build_phase1_case_contract_metadata(phase1_case_result) -> dict[str, Any]:
    """PHASE1 case manifest — **overlay/debug metadata only, training/inference matrix forbidden**.

    Phase 2 standalone contract 하에서 본 함수의 반환값은 inference contract
    JSON 에 **overlay manifest 와 debug metadata** 로만 첨부된다. 절대 금지:

    - PHASE2 row matrix 의 join 입력으로 사용 금지.
    - PHASE2 supervised/unsupervised 모델의 학습 target / feature 로 사용 금지.
    - PHASE2 inference 시 case feature 로 모델에 주입 금지.

    ``feature_columns`` 는 "PHASE1 case 구조에서 ML-safe 형태로 만들 수 있는
    컬럼 이름의 목록" 일 뿐, 실제 학습/추론 입력 행렬에는 사용하지 않는다.
    list 자체는 ``build_phase2_case_feature_frame`` →
    ``enforce_phase2_case_feature_firewall`` 통과를 거쳐 PROVENANCE_ONLY_FIELDS
    가 섞이지 않음을 정적 검증한다.

    PHASE2 학습/추론 입력은 ``preprocessing.phase2_plan`` +
    ``preprocessing.phase2_matrix`` 가 산출하는 row matrix 뿐이며, 그 안에는
    PHASE1 case 메타가 들어가지 않는다.
    """
    if phase1_case_result is None:
        return {
            "available": False,
            "feature_index_name": "phase1_case_id",
            "feature_columns": [],
            "provenance_only_fields": list(PROVENANCE_ONLY_FIELDS),
        }

    feature_frame = build_phase2_case_feature_frame(phase1_case_result)
    return {
        "available": True,
        "case_count": int(len(feature_frame)),
        "feature_index_name": str(feature_frame.index.name or "phase1_case_id"),
        "feature_columns": list(feature_frame.columns),
        "feature_column_count": int(len(feature_frame.columns)),
        "provenance_only_fields": list(PROVENANCE_ONLY_FIELDS),
    }


def _count_trial_statuses(trials: list[Phase2TrialResult]) -> dict[str, int]:
    counts = {status.value: 0 for status in Phase2TrainingStatus}
    for trial in trials:
        counts[trial.status.value] = counts.get(trial.status.value, 0) + 1
    return counts


def _build_family_summaries(
    trials: list[Phase2TrialResult],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Phase2TrialResult]] = {}
    for trial in trials:
        grouped.setdefault(trial.model_family, []).append(trial)
    return {family: _build_group_summary(group_trials) for family, group_trials in grouped.items()}


def _build_search_summaries(
    trials: list[Phase2TrialResult],
) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, list[Phase2TrialResult]]] = {}
    for trial in trials:
        search_name = str(
            trial.metadata.get("search_name") or trial.params.get("search_name") or "-"
        )
        grouped.setdefault(trial.model_family, {}).setdefault(search_name, []).append(trial)
    return {
        family: {
            search_name: _build_group_summary(search_trials)
            for search_name, search_trials in search_groups.items()
        }
        for family, search_groups in grouped.items()
    }


def _build_feature_variant_summaries(
    trials: list[Phase2TrialResult],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Phase2TrialResult]] = {}
    for trial in trials:
        feature_variant = str(
            trial.params.get("feature_variant") or _split_trial_variant(trial.variant)[0]
        )
        grouped.setdefault(feature_variant, []).append(trial)
    return {
        feature_variant: _build_group_summary(variant_trials)
        for feature_variant, variant_trials in grouped.items()
    }


def _build_sub_detector_summaries(
    trials: list[Phase2TrialResult],
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for family in _RULE_STYLE_FAMILIES:
        family_trials = [trial for trial in trials if trial.model_family == family]
        if not family_trials:
            continue
        keys: list[str] = []
        for trial in family_trials:
            for key in trial.metadata.get("sub_detector_keys", []):
                text = str(key)
                if text not in keys:
                    keys.append(text)
        best = _select_best_metric_trial(family_trials)
        summaries[family] = {
            "sub_detector_keys": keys,
            "trial_count": len(family_trials),
            "best_variant": best.variant if best is not None else None,
            "best_metric_name": best.metric_name if best is not None else None,
            "best_metric_value": best.metric_value if best is not None else None,
        }
    return summaries


def _build_promoted_sub_detector_map(
    promoted_models: list[Phase2PromotedModel],
    trials: list[Phase2TrialResult],
) -> dict[str, list[str]]:
    by_family_variant = {(trial.model_family, trial.variant): trial for trial in trials}
    reverse_family_map = {
        canonical_name: family_name
        for family_name, canonical_name in _FAMILY_TO_CANONICAL_MODEL.items()
    }
    mapping: dict[str, list[str]] = {}
    for model in promoted_models:
        family_name = reverse_family_map.get(model.model_name, model.model_name)
        trial = by_family_variant.get((family_name, model.source_trial_variant))
        mapping[model.model_name] = [
            str(key)
            for key in (trial.metadata.get("sub_detector_keys", []) if trial is not None else [])
        ]
    return mapping


def _build_family_promotion_decisions(
    trials: list[Phase2TrialResult],
    policy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[Phase2TrialResult]] = {}
    for trial in trials:
        grouped.setdefault(trial.model_family, []).append(trial)
    family_min_completed = {
        str(key): int(value)
        for key, value in dict(policy.get("family_min_completed_trials", {})).items()
    }
    family_min_metric = {
        str(key): float(value) for key, value in dict(policy.get("family_min_metric", {})).items()
    }
    eligible = _eligible_promotion_trials(trials, policy)
    eligible_keys = {(trial.model_family, trial.variant) for trial in eligible}

    for family, family_trials in grouped.items():
        completed_trials = [
            trial for trial in family_trials if trial.status == Phase2TrainingStatus.COMPLETED
        ]
        best = _select_best_metric_trial(family_trials)
        min_completed = family_min_completed.get(
            family,
            int(policy.get("min_completed_trials_per_family", 1) or 1),
        )
        min_metric = family_min_metric.get(family)
        eligible_variants = [
            trial.variant
            for trial in completed_trials
            if (trial.model_family, trial.variant) in eligible_keys
        ]
        reasons: list[str] = []
        if len(completed_trials) < min_completed:
            reasons.append("insufficient_completed_trials")
        if best is None:
            reasons.append("no_completed_trial")
        elif min_metric is not None and (best.metric_value or 0.0) < min_metric:
            reasons.append("metric_below_family_threshold")
        if best is not None and not eligible_variants and not reasons:
            reasons.append("registry_or_metric_gate")
        decisions[family] = {
            "completed_trial_count": len(completed_trials),
            "required_completed_trials": min_completed,
            "family_min_metric": min_metric,
            "best_variant": best.variant if best is not None else None,
            "best_metric_name": best.metric_name if best is not None else None,
            "best_metric_value": best.metric_value if best is not None else None,
            "eligible_variants": eligible_variants,
            "eligible_for_promotion": bool(eligible_variants),
            "reasons": reasons,
        }
    return decisions


def _build_group_summary(trials: list[Phase2TrialResult]) -> dict[str, Any]:
    status_counts = _count_trial_statuses(trials)
    best = _select_best_metric_trial(trials)
    return {
        "trial_count": len(trials),
        "status_counts": status_counts,
        "best_variant": best.variant if best is not None else None,
        "best_metric_name": best.metric_name if best is not None else None,
        "best_metric_value": best.metric_value if best is not None else None,
        "best_search_name": (
            str(best.metadata.get("search_name") or best.params.get("search_name"))
            if best is not None
            else None
        ),
        "best_model_family": best.model_family if best is not None else None,
    }


def _select_best_metric_trial(
    trials: list[Phase2TrialResult],
) -> Phase2TrialResult | None:
    completed = [trial for trial in trials if trial.status == Phase2TrainingStatus.COMPLETED]
    if not completed:
        return None
    return max(
        completed,
        key=lambda trial: (
            trial.metric_value if trial.metric_value is not None else float("-inf"),
            trial.variant,
        ),
    )


def _eligible_promotion_trials(
    trials: list[Phase2TrialResult],
    policy: dict[str, Any],
) -> list[Phase2TrialResult]:
    eligible_statuses = {
        str(value)
        for value in policy.get("eligible_statuses", [Phase2TrainingStatus.COMPLETED.value])
    }
    eligible_model_families = {str(value) for value in policy.get("eligible_model_families", [])}
    requires_registry_version = bool(policy.get("requires_registry_version", True))
    requires_metric_value = bool(policy.get("requires_metric_value", True))
    artifactless_families = {str(value) for value in policy.get("artifactless_families", [])}
    min_completed_trials_per_family = int(policy.get("min_completed_trials_per_family", 1) or 1)
    family_min_completed_trials = {
        str(key): int(value)
        for key, value in dict(policy.get("family_min_completed_trials", {})).items()
    }
    family_min_metric = {
        str(key): float(value) for key, value in dict(policy.get("family_min_metric", {})).items()
    }
    family_min_search_variants = {
        str(key): int(value)
        for key, value in dict(policy.get("family_min_search_variants", {})).items()
    }
    family_max_failed_trial_ratio = {
        str(key): float(value)
        for key, value in dict(policy.get("family_max_failed_trial_ratio", {})).items()
    }
    completed_by_family: dict[str, int] = {}
    failed_by_family: dict[str, int] = {}
    search_variants_by_family: dict[str, set[str]] = {}
    for trial in trials:
        if trial.status == Phase2TrainingStatus.COMPLETED:
            completed_by_family[trial.model_family] = (
                completed_by_family.get(trial.model_family, 0) + 1
            )
            search_variants_by_family.setdefault(trial.model_family, set()).add(
                str(
                    trial.metadata.get("search_name")
                    or trial.params.get("search_name")
                    or trial.variant
                )
            )
        elif trial.status == Phase2TrainingStatus.FAILED:
            failed_by_family[trial.model_family] = failed_by_family.get(trial.model_family, 0) + 1
    eligible: list[Phase2TrialResult] = []
    for trial in trials:
        if eligible_model_families and trial.model_family not in eligible_model_families:
            continue
        if trial.status.value not in eligible_statuses:
            continue
        unsupervised_metric = dict(trial.metadata.get("unsupervised_metric", {}))
        severe_warnings = set(unsupervised_metric.get("severe_reliability_warnings") or [])
        severe_warnings.update(
            set(unsupervised_metric.get("reliability_warnings") or [])
            & _SEVERE_UNSUPERVISED_RELIABILITY_WARNINGS
        )
        if trial.model_family == "unsupervised" and severe_warnings:
            continue
        if (
            trial.model_family == "unsupervised"
            and unsupervised_metric
            and unsupervised_metric.get("promotion_eligible") is False
        ):
            continue
        family_min_completed = family_min_completed_trials.get(
            trial.model_family,
            min_completed_trials_per_family,
        )
        if completed_by_family.get(trial.model_family, 0) < family_min_completed:
            continue
        family_search_count = len(search_variants_by_family.get(trial.model_family, set()))
        if family_search_count < family_min_search_variants.get(trial.model_family, 1):
            continue
        failed_count = failed_by_family.get(trial.model_family, 0)
        total_attempts = completed_by_family.get(trial.model_family, 0) + failed_count
        if total_attempts > 0:
            failed_ratio = failed_count / total_attempts
            if failed_ratio > family_max_failed_trial_ratio.get(trial.model_family, 1.0):
                continue
        if requires_metric_value and trial.metric_value is None:
            continue
        if (
            (trial.metric_value is not None)
            and ((min_metric := family_min_metric.get(trial.model_family)) is not None)
            and trial.metric_value < min_metric
        ):
            continue
        if (
            requires_registry_version
            and trial.model_family not in artifactless_families
            and trial.metadata.get("registry_version") is None
        ):
            continue
        eligible.append(trial)
    return eligible


def _promotion_sort_key(trial: Phase2TrialResult) -> tuple[float, float, str]:
    metric_value = trial.metric_value if trial.metric_value is not None else float("-inf")
    elapsed_sec = float(trial.elapsed_sec or 0.0)
    return (
        metric_value,
        -elapsed_sec,
        trial.variant,
    )


def _canonical_phase2_model_name(family: str) -> str:
    return _FAMILY_TO_CANONICAL_MODEL.get(str(family), str(family))


def _split_trial_variant(variant: str) -> tuple[str, str]:
    feature_variant, _, search_name = str(variant).partition("__")
    return feature_variant or str(variant), search_name or "-"


def _feature_groups_to_dict(groups) -> dict[str, list[str]]:
    if groups is None:
        return {}
    return {
        "numeric": list(groups.numeric),
        "categorical_high": list(groups.categorical_high),
        "categorical_low": list(groups.categorical_low),
        "boolean": list(groups.boolean),
        "ordinal": list(groups.ordinal),
        "excluded": list(groups.excluded),
    }


def _merge_feature_columns(base: list[str], extras: list[str]) -> list[str]:
    merged: list[str] = []
    for col in list(base) + list(extras):
        if col not in merged:
            merged.append(col)
    return merged
