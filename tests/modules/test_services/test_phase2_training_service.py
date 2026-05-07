from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.detection.base import DetectionResult
from src.services.phase2_training_models import (
    Phase2LabelSummary,
    Phase2PromotedModel,
    Phase2TrainingReport,
    Phase2TrainingStatus,
    Phase2TrialResult,
)
from src.services.phase2_training_service import (
    _eligible_promotion_trials,
    build_phase2_feature_variants,
    build_phase2_label_summary,
    build_phase2_search_presets,
    build_phase2_training_paths,
    build_phase2_training_report,
    ensure_phase2_training_dirs,
    initialize_phase2_training_report,
    prepare_phase2_feature_inputs,
    resolve_phase2_training_dir,
    run_phase2_training,
    run_phase2_training_analysis,
    save_phase2_training_report,
)
from tests.modules.test_services.test_phase2_case_contract import _phase1_result


def _make_local_temp_dir() -> Path:
    root = Path("tests") / ".tmp_phase2_training"
    root.mkdir(parents=True, exist_ok=True)
    target = root / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=True)
    return target


def test_initialize_phase2_training_report_uses_context_metadata():
    ctx = SimpleNamespace(company_id="acme", engagement_id="acme_2025")

    report = initialize_phase2_training_report(ctx=ctx, metadata={"mode": "manual"})

    assert report.company_id == "acme"
    assert report.engagement_id == "acme_2025"
    assert report.status == Phase2TrainingStatus.PENDING
    assert report.metadata["mode"] == "manual"


def test_resolve_phase2_training_dir_prefers_context_model_dir():
    root = _make_local_temp_dir()
    try:
        ctx = SimpleNamespace(model_dir=root / "models")

        target = resolve_phase2_training_dir(ctx)

        assert target == ctx.model_dir / "phase2_train"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_run_phase2_training_analysis_uses_featured_data_and_persists_state(monkeypatch):
    class _FakeSettings:
        def model_copy(self, update):
            copied = _FakeSettings()
            for key, value in update.items():
                setattr(copied, key, value)
            return copied

    featured = pd.DataFrame({"document_id": ["d1"], "amount": [100.0]})
    raw = pd.DataFrame({"document_id": ["raw"], "amount": [1.0]})
    prep = SimpleNamespace(
        data=raw,
        featured_data=featured,
        file_name="journal.csv",
    )
    ctx = SimpleNamespace(
        company_id="acme",
        engagement_id="acme_2025",
        settings=object(),
        clone_with_settings=lambda settings: SimpleNamespace(
            company_id="acme",
            engagement_id="acme_2025",
            settings=settings,
        ),
    )
    state = {
        "audit_prep_result": prep,
        "audit_company_context": ctx,
        "audit_settings": None,
    }
    seen: dict[str, object] = {}

    def _fake_run(df, **kwargs):
        seen["df"] = df
        seen["ctx"] = kwargs.get("ctx")
        return Phase2TrainingReport(
            report_id="train_state",
            company_id="acme",
            engagement_id="acme_2025",
            status=Phase2TrainingStatus.COMPLETED,
        )

    monkeypatch.setattr(
        "src.services.phase2_training_service.run_phase2_training",
        _fake_run,
    )

    report = run_phase2_training_analysis(state, settings_factory=_FakeSettings)

    assert report.report_id == "train_state"
    assert seen["df"] is featured
    assert getattr(seen["ctx"], "company_id") == "acme"
    assert state["audit_phase2_training_report_id"] == "train_state"


def test_build_phase2_training_paths_separates_artifact_folders():
    root = _make_local_temp_dir()
    try:
        ctx = SimpleNamespace(model_dir=root / "models")

        paths = build_phase2_training_paths(ctx, report_id="train_001")

        assert paths["run_root"] == ctx.model_dir / "phase2_train" / "train_001"
        assert paths["trials_dir"].name == "trials"
        assert paths["reports_dir"].name == "reports"
        assert paths["promoted_dir"].name == "promoted"
        assert paths["report_path"].name == "training_report.json"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ensure_phase2_training_dirs_creates_artifact_directories():
    root = _make_local_temp_dir()
    try:
        paths = build_phase2_training_paths(base_dir=root, report_id="train_001")

        ensure_phase2_training_dirs(paths)

        assert paths["trials_dir"].is_dir()
        assert paths["reports_dir"].is_dir()
        assert paths["promoted_dir"].is_dir()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_save_phase2_training_report_serializes_nested_types():
    root = _make_local_temp_dir()
    try:
        report = Phase2TrainingReport(
            report_id="train_001",
            company_id="acme",
            engagement_id="acme_2025",
            status=Phase2TrainingStatus.RUNNING,
            label_summary=Phase2LabelSummary(
                strategy="hybrid",
                label_source="ground_truth",
                gate_status="eligible",
                gate_reason=None,
                is_supervised_eligible=True,
                positive_count=80,
                positive_rate=0.2,
            ),
            leaderboard=[
                Phase2TrialResult(
                    model_family="supervised",
                    variant="baseline_core",
                    status=Phase2TrainingStatus.COMPLETED,
                    metric_value=0.81,
                    params={"pipeline": "xgb"},
                )
            ],
            promoted_models=[
                Phase2PromotedModel(
                    model_name="supervised",
                    source_trial_variant="baseline_core",
                    metric_name="f1_macro",
                    metric_value=0.81,
                    registry_version=1,
                )
            ],
        )

        path = save_phase2_training_report(report, base_dir=root)
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert path.exists()
        assert payload["status"] == "running"
        assert payload["label_summary"]["label_source"] == "ground_truth"
        assert payload["leaderboard"][0]["status"] == "completed"
        assert payload["promoted_models"][0]["model_name"] == "supervised"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_build_phase2_label_summary_prefers_feedback_labels():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d1", "d2"],
            "amount": [100, 120, 90],
        }
    )
    feedback = pd.DataFrame(
        {
            "document_id": ["d1", "d2"],
            "decision": ["confirmed_issue", "false_positive"],
        }
    )

    summary, label_result = build_phase2_label_summary(df, feedback_labels=feedback)

    assert summary.strategy == "feedback"
    assert summary.label_source == "ground_truth"
    assert summary.is_supervised_eligible is True
    assert label_result.positive_count == 2
    assert label_result.source_breakdown == {
        "confirmed_issue_docs": 1,
        "false_positive_docs": 1,
    }


def test_build_phase2_search_presets_returns_family_configs():
    presets = build_phase2_search_presets(["unsupervised", "supervised", "stacking"])

    assert len(presets["unsupervised"]) >= 2
    assert len(presets["supervised"]) >= 2
    assert len(presets["stacking"]) >= 2
    assert all("name" in preset for preset in presets["supervised"])


def test_prepare_phase2_feature_inputs_returns_variant_payload():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 150.0, 80.0],
            "gl_account": ["4000", "5000", "6000"],
            "user_persona": ["Manager", "maanger", "junior accountant"],
            "cost_center": ["CC1", None, None],
            "posting_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        }
    )

    cleaned_df, groups, payload = prepare_phase2_feature_inputs(df)
    variants = build_phase2_feature_variants(cleaned_df, groups)

    assert "feature_quality_profile" in payload
    assert payload["feature_variants"]
    assert variants[0]["variant"] == "baseline_core"
    assert "user_persona" in cleaned_df.columns
    assert cleaned_df["user_persona"].iloc[1] == "manager"


def test_build_phase2_training_report_skips_supervised_families_without_labels():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 150.0, 80.0],
            "gl_account": ["4000", "5000", "6000"],
            "user_persona": ["manager", "controller", "junior_accountant"],
            "posting_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        }
    )

    report = build_phase2_training_report(df)

    unsupervised_trials = [
        trial for trial in report.leaderboard if trial.model_family == "unsupervised"
    ]
    supervised_trials = [
        trial for trial in report.leaderboard if trial.model_family == "supervised"
    ]

    assert report.status == Phase2TrainingStatus.RUNNING
    assert report.label_summary is not None
    assert report.label_summary.gate_reason == "missing_ground_truth_labels"
    assert report.metadata["search_preset_count"] >= 2
    assert unsupervised_trials
    assert all(trial.status == Phase2TrainingStatus.PENDING for trial in unsupervised_trials)
    assert supervised_trials
    assert all(trial.status == Phase2TrainingStatus.SKIPPED for trial in supervised_trials)
    assert any(trial.model_family == "timeseries" for trial in report.leaderboard)
    assert any(trial.model_family == "relational" for trial in report.leaderboard)
    assert any(trial.model_family == "duplicate" for trial in report.leaderboard)
    assert any(trial.model_family == "intercompany" for trial in report.leaderboard)


def test_build_phase2_training_report_records_phase1_case_contract():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 150.0, 80.0],
            "gl_account": ["4000", "5000", "6000"],
            "user_persona": ["manager", "controller", "junior_accountant"],
            "posting_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        }
    )

    report = build_phase2_training_report(df, phase1_case_result=_phase1_result())

    contract = report.metadata["phase1_case_contract"]
    feature_columns = set(contract["feature_columns"])

    assert contract["available"] is True
    assert contract["case_count"] == 1
    assert contract["feature_index_name"] == "phase1_case_id"
    assert "rule_diversity_count" in feature_columns
    assert "top_rule_ids" not in feature_columns
    assert "primary_theme" not in feature_columns
    assert "raw_rule_hits" not in feature_columns
    assert "phase1_case_id" not in feature_columns
    assert "top_rule_ids" in contract["provenance_only_fields"]


def test_build_phase2_training_report_enables_supervised_families_with_ground_truth():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3", "d4"],
            "amount": [100.0, 150.0, 80.0, 175.0],
            "gl_account": ["4000", "5000", "6000", "7000"],
            "user_persona": ["manager", "controller", "junior_accountant", "manager"],
            "posting_date": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
            ),
            "is_fraud": [0, 1, 0, 0],
            "is_anomaly": [0, 0, 1, 0],
        }
    )

    report = build_phase2_training_report(df, strategy="datasynth")

    supervised_trials = [
        trial for trial in report.leaderboard if trial.model_family == "supervised"
    ]

    assert report.label_summary is not None
    assert report.label_summary.label_source == "ground_truth"
    assert report.label_summary.is_supervised_eligible is True
    assert supervised_trials
    assert all(trial.status == Phase2TrainingStatus.PENDING for trial in supervised_trials)


class _FakeDetector:
    model_name = "fake_model"
    track_name = "fake"

    def __init__(self, *, settings=None, model_registry=None, **kwargs):
        self._registry = model_registry
        self._settings = settings
        self._kwargs = kwargs

    def train(self, *args, **kwargs):
        return {"mean_f1": 0.75, "n_train": 4}

    def detect(self, df):
        scores = pd.Series(self._score_pattern(len(df)), index=df.index, name="ML")
        flagged = scores[scores >= 0.5].index.tolist()
        return DetectionResult(
            track_name=self.track_name,
            flagged_indices=flagged,
            scores=scores,
            rule_flags=[],
            details=pd.DataFrame({"ML": scores}, index=df.index),
            metadata={"elapsed": 0.01},
            warnings=[],
        )

    def save_model(self, metric_value):
        return self._registry.save(
            {"metric": metric_value},
            self.model_name,
            metric_value or 0.0,
        )

    def _score_pattern(self, n_rows: int) -> list[float]:
        return [0.1, 0.9, 0.2, 0.8][:n_rows]


class _FakeUnsupervised(_FakeDetector):
    model_name = "unsupervised_fake"
    track_name = "ml_unsupervised"

    def _score_pattern(self, n_rows: int) -> list[float]:
        if getattr(self._settings, "vae_latent_dim", 0) >= 64:
            return [0.05, 0.95, 0.1, 0.9][:n_rows]
        return [0.2, 0.8, 0.25, 0.7][:n_rows]


class _FakeSupervised(_FakeDetector):
    model_name = "supervised_fake"
    track_name = "ml_supervised"

    def _score_pattern(self, n_rows: int) -> list[float]:
        if self._kwargs.get("use_smote"):
            return [0.05, 0.95, 0.1, 0.9][:n_rows]
        return [0.3, 0.7, 0.35, 0.65][:n_rows]


class _FakeTransformer(_FakeDetector):
    model_name = "transformer_fake"
    track_name = "ml_transformer"

    def _score_pattern(self, n_rows: int) -> list[float]:
        if getattr(self._settings, "ft_d_token", 0) >= 64:
            return [0.05, 0.95, 0.1, 0.9][:n_rows]
        return [0.25, 0.75, 0.3, 0.7][:n_rows]


class _FakeSequence(_FakeDetector):
    model_name = "sequence_fake"
    track_name = "ml_sequence"

    def _score_pattern(self, n_rows: int) -> list[float]:
        if getattr(self._settings, "bilstm_seq_len", 0) >= 16:
            return [0.1, 0.95, 0.85, 0.2][:n_rows]
        return [0.3, 0.7, 0.35, 0.65][:n_rows]


class _FakeStacking:
    def __init__(self, *, settings=None, model_registry=None, **kwargs):
        self._registry = model_registry

    def train_oof(self, X, label_result, user_ids, df_index, non_leakage_results, groups):
        return {"mode": "oof_stacking", "n_folds": 2}

    def train_from_results(self, results, y, index):
        return {"mode": "stacking", "n_folds": 1}

    def detect_from_results(self, results, index):
        scores = pd.Series([0.2, 0.95, 0.1, 0.85][: len(index)], index=index, name="EN01")
        flagged = scores[scores >= 0.5].index.tolist()
        return DetectionResult(
            track_name="ensemble",
            flagged_indices=flagged,
            scores=scores,
            rule_flags=[],
            details=pd.DataFrame({"EN01": scores}, index=index),
            metadata={"elapsed": 0.01},
            warnings=[],
        )

    def save_model(self, metric_value):
        return self._registry.save(
            {"metric": metric_value},
            "stacking_fake",
            metric_value or 0.0,
        )


def test_run_phase2_training_executes_trials_with_injected_detectors():
    root = _make_local_temp_dir()
    try:
        df = pd.DataFrame(
            {
                "document_id": ["d1", "d2", "d3", "d4"],
                "created_by": ["u1", "u2", "u1", "u2"],
                "amount": [100.0, 150.0, 80.0, 175.0],
                "gl_account": ["4000", "5000", "6000", "7000"],
                "user_persona": ["manager", "controller", "junior_accountant", "manager"],
                "posting_date": pd.to_datetime(
                    ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
                ),
                "is_fraud": [0, 1, 0, 0],
                "is_anomaly": [0, 0, 1, 0],
            }
        )
        ctx = SimpleNamespace(model_dir=root / "models")

        report = run_phase2_training(
            df,
            ctx=ctx,
            strategy="datasynth",
            detector_factories={
                "unsupervised": _FakeUnsupervised,
                "supervised": _FakeSupervised,
                "transformer": _FakeTransformer,
                "sequence": _FakeSequence,
                "stacking": _FakeStacking,
            },
            base_dir=root / "phase2_train",
        )

        assert report.status == Phase2TrainingStatus.COMPLETED
        assert report.label_summary is not None
        assert all(trial.artifact_path for trial in report.leaderboard)
        assert report.promoted_models
        assert "best_overall_model" in report.metadata
        assert report.metadata["promotion_policy"]["selection_mode"] == "best_per_family"
        assert report.metadata["promotion_policy"]["requires_registry_version"] is True
        assert report.metadata["promotion_policy"]["min_completed_trials_per_family"] == 2
        assert report.metadata["promotion_policy"]["family_min_completed_trials"]["timeseries"] == 2
        assert report.metadata["promotion_policy"]["family_min_metric"]["timeseries"] == 0.05
        assert report.metadata["promotion_policy"]["family_min_search_variants"]["timeseries"] == 2
        assert (
            report.metadata["promotion_policy"]["family_max_failed_trial_ratio"]["timeseries"]
            == 0.5
        )
        assert (
            report.metadata["promotion_policy"]["tie_break_policy"]["primary"]
            == "metric_value_desc"
        )
        assert (
            report.metadata["inference_contract"]["promoted_versions"]["unsupervised"] >= 1
        )
        assert (
            report.metadata["inference_contract"]["track_map"]["unsupervised"]
            == "ml_unsupervised"
        )
        assert report.metadata["trial_status_counts"]["completed"] > 0
        assert report.metadata["family_summaries"]["unsupervised"]["best_variant"].endswith(
            "sensitive"
        )
        assert (
            report.metadata["search_summaries"]["supervised"]["smote"]["best_metric_value"]
            is not None
        )
        assert (
            report.metadata["feature_variant_summaries"]["plus_persona"]["trial_count"] > 0
        )
        assert (
            report.metadata["sub_detector_summaries"]["timeseries"]["sub_detector_keys"]
            == ["transaction_burst", "unusual_frequency"]
        )
        assert (
            report.metadata["promotion_policy"]["rule_style_metric_policy"]["metric_name"]
            == "rule_proxy_score"
        )
        assert (
            report.metadata["family_promotion_decisions"]["timeseries"]["eligible_for_promotion"]
            is True
        )
        assert (
            report.metadata["family_promotion_decisions"]["timeseries"]["required_completed_trials"]
            == 2
        )
        assert (
            report.metadata["sub_detector_summaries"]["duplicate"]["sub_detector_keys"][0]
            == "exact_duplicate_amount"
        )
        assert (
            report.metadata["inference_contract"]["family_sub_detectors"]["timeseries"]
            == ["transaction_burst", "unusual_frequency"]
        )
        case_contract = report.metadata["inference_contract"]["phase1_case_contract"]
        assert case_contract["available"] is False
        assert "top_rule_ids" in case_contract["provenance_only_fields"]
        stacking_trials = [
            trial for trial in report.leaderboard if trial.model_family == "stacking"
        ]
        assert any(trial.status == Phase2TrainingStatus.COMPLETED for trial in stacking_trials)
        completed_stacking = next(
            trial for trial in stacking_trials if trial.status == Phase2TrainingStatus.COMPLETED
        )
        assert completed_stacking.metadata["stacking_mode"] == "oof_stacking"
        assert completed_stacking.metadata["base_input_variants"]["unsupervised"].endswith(
            "sensitive"
        )
        assert (
            completed_stacking.metadata["base_input_variants"]["supervised"]
            == completed_stacking.variant
        )
        assert (
            completed_stacking.metadata["base_input_variants"]["transformer"]
            == completed_stacking.variant
        )
        assert (
            completed_stacking.metadata["base_input_variants"]["sequence"]
            == completed_stacking.variant
        )
        assert (
            root / "phase2_train" / report.report_id / "reports" / "training_report.json"
        ).exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_run_phase2_training_propagates_phase1_case_contract_to_inference_contract():
    root = _make_local_temp_dir()
    try:
        df = pd.DataFrame(
            {
                "document_id": ["d1", "d2", "d3", "d4"],
                "created_by": ["u1", "u2", "u1", "u2"],
                "amount": [100.0, 150.0, 80.0, 175.0],
                "gl_account": ["4000", "5000", "6000", "7000"],
                "user_persona": ["manager", "controller", "junior_accountant", "manager"],
                "posting_date": pd.to_datetime(
                    ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
                ),
                "is_fraud": [0, 1, 0, 0],
                "is_anomaly": [0, 0, 1, 0],
            }
        )
        ctx = SimpleNamespace(model_dir=root / "models")

        report = run_phase2_training(
            df,
            ctx=ctx,
            strategy="datasynth",
            detector_factories={
                "unsupervised": _FakeUnsupervised,
                "supervised": _FakeSupervised,
                "transformer": _FakeTransformer,
                "sequence": _FakeSequence,
                "stacking": _FakeStacking,
            },
            base_dir=root / "phase2_train",
            phase1_case_result=_phase1_result(),
        )

        metadata_contract = report.metadata["phase1_case_contract"]
        inference_contract = report.metadata["inference_contract"]["phase1_case_contract"]

        assert metadata_contract["available"] is True
        assert inference_contract == metadata_contract
        assert "rule_diversity_count" in inference_contract["feature_columns"]
        assert "top_rule_ids" not in inference_contract["feature_columns"]
        assert "top_rule_ids" in inference_contract["provenance_only_fields"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_eligible_promotion_trials_require_search_diversity_and_control_failure_ratio():
    policy = {
        "eligible_statuses": [Phase2TrainingStatus.COMPLETED.value],
        "requires_registry_version": False,
        "requires_metric_value": True,
        "min_completed_trials_per_family": 2,
        "family_min_completed_trials": {"timeseries": 2},
        "family_min_metric": {"timeseries": 0.05},
        "family_min_search_variants": {"timeseries": 2},
        "family_max_failed_trial_ratio": {"timeseries": 0.5},
        "artifactless_families": ["timeseries"],
    }

    one_search_trials = [
        Phase2TrialResult(
            model_family="timeseries",
            variant="baseline_core__balanced",
            status=Phase2TrainingStatus.COMPLETED,
            metric_name="rule_proxy_score",
            metric_value=0.2,
            metadata={"search_name": "balanced"},
        ),
        Phase2TrialResult(
            model_family="timeseries",
            variant="plus_persona__balanced",
            status=Phase2TrainingStatus.COMPLETED,
            metric_name="rule_proxy_score",
            metric_value=0.21,
            metadata={"search_name": "balanced"},
        ),
    ]
    assert _eligible_promotion_trials(one_search_trials, policy) == []

    high_failure_trials = [
        Phase2TrialResult(
            model_family="timeseries",
            variant="baseline_core__balanced",
            status=Phase2TrainingStatus.COMPLETED,
            metric_name="rule_proxy_score",
            metric_value=0.2,
            metadata={"search_name": "balanced"},
        ),
        Phase2TrialResult(
            model_family="timeseries",
            variant="baseline_core__sensitive",
            status=Phase2TrainingStatus.COMPLETED,
            metric_name="rule_proxy_score",
            metric_value=0.21,
            metadata={"search_name": "sensitive"},
        ),
        Phase2TrialResult(
            model_family="timeseries",
            variant="plus_persona__strict",
            status=Phase2TrainingStatus.FAILED,
            metric_name="rule_proxy_score",
            metadata={"search_name": "strict"},
        ),
        Phase2TrialResult(
            model_family="timeseries",
            variant="baseline_core__strict",
            status=Phase2TrainingStatus.FAILED,
            metric_name="rule_proxy_score",
            metadata={"search_name": "strict"},
        ),
        Phase2TrialResult(
            model_family="timeseries",
            variant="plus_persona__balanced",
            status=Phase2TrainingStatus.FAILED,
            metric_name="rule_proxy_score",
            metadata={"search_name": "balanced"},
        ),
    ]
    assert _eligible_promotion_trials(high_failure_trials, policy) == []
