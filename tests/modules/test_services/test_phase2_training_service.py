from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from config.settings import AuditSettings
from src.detection.base import DetectionResult
from src.evaluation.phase2_report import build_hold_out_metrics
from src.services.phase2_training_models import (
    Phase2LabelSummary,
    Phase2PromotedModel,
    Phase2TrainingReport,
    Phase2TrainingStatus,
    Phase2TrialResult,
)
from src.services.phase2_training_service import (
    DEFAULT_HOLD_OUT_SCENARIOS,
    _apply_unsupervised_split_row_caps,
    _compute_unsupervised_metric,
    _eligible_promotion_trials,
    _split_unsupervised_train_calibration,
    build_phase2_feature_variants,
    build_phase2_label_summary,
    build_phase2_search_presets,
    build_phase2_training_paths,
    build_phase2_training_report,
    build_promoted_model_artifact_dir,
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


def test_audit_settings_exposes_phase2_vae_mvp_defaults():
    settings = AuditSettings()

    assert settings.phase2_training_mode == "unsupervised_autoencoder_mvp"
    assert settings.phase2_train_max_rows == 50_000
    assert settings.phase2_review_capacity_ratio == 0.10
    assert settings.phase2_unsup_train_ratio == 0.80
    assert settings.phase2_unsup_calibration_rows == 50_000
    assert settings.phase2_reconstruction_group_weights["numeric"] == 1.0
    assert settings.phase2_reconstruction_group_weights["boolean"] == 1.0


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
        assert paths["leaderboard_path"].name == "leaderboard.json"
        assert paths["promotion_decision_path"].name == "promotion_decision.json"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_build_promoted_model_artifact_dir_uses_family_version_pattern():
    ctx = SimpleNamespace(model_dir=Path("data/companies/acme/engagements/2025/models"))

    path = build_promoted_model_artifact_dir(ctx, family="unsupervised", version=3)

    assert path.as_posix().endswith(
        "data/companies/acme/engagements/2025/models/phase2_unsupervised/v0003"
    )


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
        assert payload["supervised_gate"]["decision"] == "eligible"
        assert payload["supervised_gate"]["thresholds"] == {
            "min_positive_count": 50,
            "min_positive_rate": 0.01,
        }
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
    assert summary.is_supervised_eligible is False
    assert summary.gate_decision == "low_signal_fallback"
    assert label_result.positive_count == 2
    assert label_result.source_breakdown == {
        "confirmed_issue_docs": 1,
        "false_positive_docs": 1,
    }


def test_build_phase2_search_presets_returns_family_configs():
    presets = build_phase2_search_presets(["unsupervised", "supervised", "stacking"])

    # Why: 100k 측정(2026-05-23) 결과 unsup_selection_score 가 preset 별 noise(<0.001)
    # 라 unsupervised preset 1개(balanced)로 -75% 시간 단축. 다른 family는 2 preset 유지.
    assert len(presets["unsupervised"]) == 1
    assert len(presets["supervised"]) >= 2
    assert len(presets["stacking"]) >= 2
    assert all("name" in preset for preset in presets["supervised"])


def test_prepare_phase2_feature_inputs_returns_variant_payload(caplog):
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

    with caplog.at_level(logging.INFO, logger="src.services.phase2_training_service"):
        cleaned_df, groups, payload = prepare_phase2_feature_inputs(df)
    variants = build_phase2_feature_variants(cleaned_df, groups)

    assert "Leakage deny applied: 54 columns" in caplog.text
    assert "feature_quality_profile" in payload
    assert payload["feature_metadata"]["rule_input_dim"] == 22
    assert payload["feature_variants"]
    assert variants[0]["variant"] == "baseline_core"
    assert "user_persona" in cleaned_df.columns
    assert cleaned_df["user_persona"].iloc[1] == "manager"


def test_build_phase2_training_report_defaults_to_unsupervised_mvp_queue():
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
    trial_families = {trial.model_family for trial in report.leaderboard}

    assert report.status == Phase2TrainingStatus.RUNNING
    assert report.label_summary is not None
    assert report.label_summary.gate_reason == "missing_ground_truth_labels"
    assert report.supervised_gate["decision"] == "unavailable"
    assert report.to_dict()["supervised_gate"]["reason"] == "missing_ground_truth_labels"
    assert report.metadata["candidate_families"] == [
        "unsupervised",
        "timeseries",
        "relational",
        "duplicate",
        "intercompany",
    ]
    assert report.metadata["phase2_training_mode"] == "unsupervised_autoencoder_mvp"
    assert report.metadata["feature_metadata"]["rule_input_dim"] == 22
    assert report.metadata["search_preset_count"] >= 2
    assert unsupervised_trials
    assert all(trial.status == Phase2TrainingStatus.PENDING for trial in unsupervised_trials)
    assert trial_families == {
        "unsupervised",
        "timeseries",
        "relational",
        "duplicate",
        "intercompany",
    }


def test_unsupervised_search_presets_are_mvp_contract():
    presets = build_phase2_search_presets(["unsupervised"])["unsupervised"]
    required_keys = {
        "vae_hidden_dim",
        "vae_latent_dim",
        "vae_epochs",
        "vae_batch_size",
        "vae_lr",
        "vae_beta",
        "if_contamination",
        "phase2_review_capacity_ratio",
    }

    # Why: 100k 측정(2026-05-23) 결과 compact/balanced/strict_capacity 간 unsup metric
    # 차이가 noise 수준(±0.001). balanced(epochs=20) 단일 preset 으로 -75% 시간 절감.
    assert [preset["name"] for preset in presets] == ["balanced"]
    assert presets[0]["settings_updates"]["vae_epochs"] == 20
    assert all(required_keys <= set(preset["settings_updates"]) for preset in presets)
    assert "sensitive" not in {preset["name"] for preset in presets}


def test_build_phase2_training_report_uses_settings_training_mode():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 150.0, 80.0],
            "posting_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        }
    )
    ctx = SimpleNamespace(
        settings=SimpleNamespace(
            phase2_training_mode="custom_unsupervised_mvp",
            phase2_profile_max_rows=100_000,
            phase2_random_seed=42,
            heuristic_high_cardinality_threshold=50,
        )
    )

    report = build_phase2_training_report(df, ctx=ctx)

    assert report.metadata["phase2_training_mode"] == "custom_unsupervised_mvp"


def test_build_phase2_training_report_persists_preprocessing_plan_metadata():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d1", "d2", "d3", "d4", "d5"],
            "amount": [100.0, 100.0, 150.0, 80.0, 175.0, 60.0],
            "model_score": [0.9, 0.9, 0.1, 0.2, 0.4, 0.3],
            "risk_level": ["High", "High", "Low", "Low", "Medium", "Low"],
            "posting_date": pd.to_datetime(
                [
                    "2024-01-01",
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-04",
                    "2024-01-05",
                ]
            ),
        }
    )
    ctx = SimpleNamespace(
        settings=SimpleNamespace(
            phase2_profile_max_rows=3,
            phase2_random_seed=7,
            heuristic_high_cardinality_threshold=50,
        )
    )

    report = build_phase2_training_report(df, ctx=ctx)
    plan = report.metadata["preprocessing_plan"]
    decisions = {decision["column"]: decision for decision in plan["decisions"]}
    payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))

    assert plan["duplicate_rows_estimated"] is True
    assert plan["duplicate_sample_size"] == 3
    assert plan["duplicate_rate_estimate"] is not None
    assert decisions["model_score"]["action"] == "exclude"
    assert decisions["model_score"]["reason_code"] == "leakage_score"
    assert decisions["risk_level"]["reason_code"] == "leakage_risk"
    assert payload["metadata"]["preprocessing_plan"]["decisions"][0]["reason_code"]


def test_split_unsupervised_train_calibration_keeps_document_groups_disjoint():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d1", "d2", "d2", "d3", "d3", "d4", "d4"],
            "amount": [10, 11, 20, 21, 30, 31, 40, 41],
        }
    )
    settings = SimpleNamespace(
        phase2_calibration_size=0.25,
        phase2_random_seed=13,
        phase2_split_strategy="group",
        phase2_split_group_column="document_id",
        phase2_temporal_column="posting_date",
    )

    split = _split_unsupervised_train_calibration(df, settings)

    train_docs = set(split.train_df["document_id"])
    calibration_docs = set(split.calibration_df["document_id"])
    assert train_docs
    assert calibration_docs
    assert train_docs.isdisjoint(calibration_docs)
    assert split.metadata["split_strategy"] == "group"


def test_unsupervised_split_row_caps_are_deterministic_and_keep_groups_disjoint():
    df = pd.DataFrame(
        {
            "document_id": [f"d{i // 2:03d}" for i in range(80)],
            "amount": [float(i) for i in range(80)],
        }
    )
    settings = SimpleNamespace(
        phase2_unsup_train_ratio=0.5,
        phase2_unsup_calibration_rows=8,
        phase2_train_max_rows=10,
        phase2_random_seed=17,
        phase2_split_strategy="group",
        phase2_split_group_column="document_id",
        phase2_temporal_column="posting_date",
    )

    capped_a = _apply_unsupervised_split_row_caps(
        _split_unsupervised_train_calibration(df, settings),
        settings,
    )
    capped_b = _apply_unsupervised_split_row_caps(
        _split_unsupervised_train_calibration(df, settings),
        settings,
    )

    assert capped_a.train_df.index.tolist() == capped_b.train_df.index.tolist()
    assert capped_a.calibration_df.index.tolist() == capped_b.calibration_df.index.tolist()
    assert len(capped_a.train_df) <= 10
    assert len(capped_a.calibration_df) <= 8
    assert set(capped_a.train_df["document_id"]).isdisjoint(
        set(capped_a.calibration_df["document_id"])
    )
    assert capped_a.metadata["source_train_rows"] > capped_a.metadata["capped_train_rows"]
    assert (
        capped_a.metadata["source_calibration_rows"] > capped_a.metadata["capped_calibration_rows"]
    )
    assert capped_a.metadata["cap_strategy"]["train"] == "document_group_cap"
    assert capped_a.metadata["seed"] == 17


def test_hold_out_scenarios_are_removed_from_train_and_preserved_in_test_fold():
    hold_out_docs = [(f"timing-{i:02d}", "unusual_timing_manipulation") for i in range(21)] + [
        (f"sod-{i:02d}", "approval_sod_bypass") for i in range(29)
    ]
    normal_docs = [(f"normal-{i:02d}", "") for i in range(80)]
    df = pd.DataFrame(
        {
            "document_id": [doc_id for doc_id, _scenario in normal_docs + hold_out_docs],
            "mutation_type": [scenario for _doc_id, scenario in normal_docs + hold_out_docs],
            "amount": [float(i) for i in range(130)],
            "posting_date": pd.date_range("2024-01-01", periods=130, freq="D"),
        }
    )
    settings = SimpleNamespace(
        phase2_unsup_train_ratio=0.75,
        phase2_unsup_calibration_rows=5,
        phase2_train_max_rows=20,
        phase2_random_seed=19,
        phase2_split_strategy="group",
        phase2_split_group_column="document_id",
        phase2_temporal_column="posting_date",
    )

    split = _split_unsupervised_train_calibration(
        df,
        settings,
        hold_out_scenarios=DEFAULT_HOLD_OUT_SCENARIOS,
    )
    capped = _apply_unsupervised_split_row_caps(split, settings)

    hold_out_set = set(DEFAULT_HOLD_OUT_SCENARIOS)
    train_hold_out_docs = capped.train_df.loc[
        capped.train_df["mutation_type"].isin(hold_out_set),
        "document_id",
    ].nunique()
    test_hold_out_docs = capped.calibration_df.loc[
        capped.calibration_df["mutation_type"].isin(hold_out_set),
        "document_id",
    ].nunique()

    assert train_hold_out_docs == 0
    assert test_hold_out_docs == 50
    assert capped.metadata["hold_out_doc_count"] == 50
    assert capped.metadata["hold_out_in_train_rows"] == 0
    assert capped.metadata["hold_out_in_calibration_rows"] == 50
    assert capped.metadata["cap_strategy"]["calibration"].endswith("_plus_hold_out")


def test_hold_out_metrics_compute_doc_recall_ci_and_pass_flag():
    df = pd.DataFrame(
        {
            "document_id": [f"h{i:02d}" for i in range(50)],
            "mutation_type": (["unusual_timing_manipulation"] * 21 + ["approval_sod_bypass"] * 29),
            "amount": [float(i) for i in range(50)],
        }
    )
    result = _unsupervised_result([0.9 if i < 25 else 0.1 for i in range(50)])
    result.flagged_indices = list(range(25))

    metrics = build_hold_out_metrics(
        df,
        result,
        hold_out_scenarios=DEFAULT_HOLD_OUT_SCENARIOS,
    )

    assert metrics["hold_out_doc_count"] == 50
    assert metrics["hold_out_detected_docs"] == 25
    assert metrics["hold_out_recall"] == 0.5
    assert metrics["hold_out_pass"] is True
    assert round(metrics["ci95"]["half_width"], 2) == 0.14
    assert "true zero-day fraud type 아님" in metrics["caveat"]


def _unsupervised_result(scores, *, warnings=None):
    series = pd.Series(scores, name="ML02")
    threshold = series.quantile(0.80)
    flagged = series[series >= threshold].index.tolist()
    return DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=flagged,
        scores=series,
        rule_flags=[],
        details=pd.DataFrame({"ML02": series}, index=series.index),
        metadata={"elapsed": 0.01},
        warnings=list(warnings or []),
    )


def test_compute_unsupervised_metric_keeps_flagged_ratio_as_metadata_only():
    metric_name, metric_value, metadata = _compute_unsupervised_metric(
        _unsupervised_result([0.05, 0.10, 0.15, 0.80, 0.90]),
        settings=SimpleNamespace(phase2_review_capacity_ratio=0.2),
    )

    assert metric_name == "unsupervised_selection_score"
    assert metric_value > 0
    assert metadata["metric_interpretation"] == "ranking_proxy_not_fraud_accuracy"
    assert "flagged_ratio" in metadata["components"]
    assert metadata["components"]["flagged_ratio"] == 0.2


def test_compute_unsupervised_metric_uses_review_capacity_setting():
    result = _unsupervised_result([0.01, 0.10, 0.20, 0.40, 0.80, 0.95])

    _, _, narrow_metadata = _compute_unsupervised_metric(
        result,
        settings=SimpleNamespace(phase2_review_capacity_ratio=0.2),
    )
    _, _, broad_metadata = _compute_unsupervised_metric(
        result,
        settings=SimpleNamespace(phase2_review_capacity_ratio=0.5),
    )

    assert narrow_metadata["review_capacity_ratio"] == 0.2
    assert broad_metadata["review_capacity_ratio"] == 0.5
    assert narrow_metadata["review_threshold"] != broad_metadata["review_threshold"]
    assert (
        narrow_metadata["components"]["capacity_flagged_ratio"]
        != broad_metadata["components"]["capacity_flagged_ratio"]
    )


def test_compute_unsupervised_metric_does_not_reward_aggressive_flagging_only():
    aggressive_name, aggressive_value, aggressive_metadata = _compute_unsupervised_metric(
        _unsupervised_result([0.91, 0.91, 0.91, 0.91, 0.91]),
        settings=SimpleNamespace(phase2_review_capacity_ratio=0.2),
    )
    ranked_name, ranked_value, ranked_metadata = _compute_unsupervised_metric(
        _unsupervised_result([0.02, 0.05, 0.08, 0.70, 0.95]),
        settings=SimpleNamespace(phase2_review_capacity_ratio=0.2),
    )

    assert aggressive_name == ranked_name == "unsupervised_selection_score"
    assert aggressive_metadata["components"]["score_degeneracy_penalty"] > 0
    assert aggressive_metadata["components"]["flagged_ratio"] == 1.0
    assert ranked_metadata["components"]["flagged_ratio"] == 0.2
    assert ranked_value > aggressive_value


def test_degenerate_unsupervised_score_is_not_eligible_for_promotion():
    trial = Phase2TrialResult(
        model_family="unsupervised",
        variant="baseline_core__balanced",
        status=Phase2TrainingStatus.COMPLETED,
        metric_name="unsupervised_selection_score",
        metric_value=0.0,
        metadata={
            "registry_version": 1,
            "unsupervised_metric": {
                "components": {"score_degeneracy_penalty": 1.0},
                "reliability_warnings": ["degenerate_score_distribution"],
            },
        },
    )
    policy = {
        "eligible_statuses": [Phase2TrainingStatus.COMPLETED.value],
        "eligible_model_families": ["unsupervised"],
        "requires_registry_version": True,
        "requires_metric_value": True,
        "min_completed_trials_per_family": 1,
        "family_min_completed_trials": {"unsupervised": 1},
        "family_min_metric": {"unsupervised": 0.0},
        "family_min_search_variants": {"unsupervised": 1},
        "family_max_failed_trial_ratio": {"unsupervised": 1.0},
    }

    assert _eligible_promotion_trials([trial], policy) == []


def test_flat_unsupervised_scores_emit_severe_warning_and_zero_metric():
    metric_name, metric_value, metadata = _compute_unsupervised_metric(
        _unsupervised_result([0.5, 0.5, 0.5, 0.5]),
        settings=SimpleNamespace(phase2_review_capacity_ratio=0.25),
    )

    assert metric_name == "unsupervised_selection_score"
    assert metric_value == 0.0
    assert "score_flat" in metadata["severe_reliability_warnings"]
    assert metadata["promotion_eligible"] is False


def test_run_phase2_training_no_label_unsupervised_uses_selection_score():
    root = _make_local_temp_dir()
    try:
        df = pd.DataFrame(
            {
                "document_id": ["d1", "d2", "d3", "d4"],
                "amount": [100.0, 150.0, 80.0, 175.0],
                "gl_account": ["4000", "5000", "6000", "7000"],
                "user_persona": ["manager", "controller", "junior_accountant", "manager"],
                "posting_date": pd.to_datetime(
                    ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
                ),
            }
        )
        ctx = SimpleNamespace(
            model_dir=root / "models",
            settings=SimpleNamespace(
                phase2_calibration_size=0.5,
                phase2_training_mode="test_unsupervised_mvp",
                phase2_random_seed=1,
                phase2_split_strategy="group",
                phase2_split_group_column="document_id",
                phase2_temporal_column="posting_date",
                phase2_profile_max_rows=100_000,
                heuristic_high_cardinality_threshold=50,
                phase2_low_card_rare_min_count=2,
                phase2_review_capacity_ratio=0.2,
            ),
        )

        report = run_phase2_training(
            df,
            ctx=ctx,
            detector_factories={"unsupervised": _FakeUnsupervised},
            base_dir=root / "phase2_train",
        )

        completed = [
            trial for trial in report.leaderboard if trial.status == Phase2TrainingStatus.COMPLETED
        ]
        assert completed
        completed_unsupervised = [
            trial for trial in completed if trial.model_family == "unsupervised"
        ]
        assert completed_unsupervised
        assert {trial.metric_name for trial in completed_unsupervised} == {
            "unsupervised_selection_score"
        }
        assert all(
            "flagged_ratio" in trial.metadata["unsupervised_metric"]["components"]
            for trial in completed_unsupervised
        )
        assert all(
            trial.metadata["unsupervised_metric"]["metric_interpretation"]
            == "ranking_proxy_not_fraud_accuracy"
            for trial in completed_unsupervised
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_build_phase2_training_report_does_not_use_label_summary_to_gate_queue():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 150.0, 80.0],
            "gl_account": ["4000", "5000", "6000"],
            "user_persona": ["manager", "controller", "junior_accountant"],
            "posting_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        }
    )

    report = build_phase2_training_report(
        df,
        model_families=("unsupervised", "supervised"),
    )

    supervised_trials = [
        trial for trial in report.leaderboard if trial.model_family == "supervised"
    ]

    assert report.label_summary is not None
    assert report.label_summary.is_supervised_eligible is False
    assert supervised_trials
    assert all(trial.status == Phase2TrainingStatus.PENDING for trial in supervised_trials)
    assert all(trial.gate_reason is None for trial in supervised_trials)


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


def test_build_phase2_training_report_keeps_default_unsupervised_with_ground_truth():
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

    trial_families = {trial.model_family for trial in report.leaderboard}

    assert report.label_summary is not None
    assert report.label_summary.label_source == "ground_truth"
    assert report.label_summary.gate_decision == "low_signal_fallback"
    assert report.label_summary.is_supervised_eligible is False
    assert report.metadata["candidate_families"] == [
        "unsupervised",
        "timeseries",
        "relational",
        "duplicate",
        "intercompany",
    ]
    assert trial_families == {
        "unsupervised",
        "timeseries",
        "relational",
        "duplicate",
        "intercompany",
    }


def test_run_phase2_training_uses_prepared_matrix_for_unsupervised_train_and_detect():
    root = _make_local_temp_dir()
    _MatrixCaptureUnsupervised.train_frames = []
    _MatrixCaptureUnsupervised.detect_frames = []
    _MatrixCaptureUnsupervised.train_groups = []
    _MatrixCaptureUnsupervised.train_y_lengths = []
    _MatrixCaptureUnsupervised.matrix_schema_hashes = []
    _MatrixCaptureUnsupervised.matrix_feature_names = []
    try:
        df = pd.DataFrame(
            {
                "document_id": [f"d{i}" for i in range(1, 7)],
                "amount": [100.0, -50.0, 25.0, 40.0, 300.0, -10.0],
                "vendor_name": ["A", "B", "C", "D", "CAL_ONLY", "CAL_ONLY_2"],
                "tax_amount": [None, None, None, None, 12.5, None],
                "cost_center": [None, None, None, None, "CC-10", None],
                "posting_date": pd.to_datetime(
                    [
                        "2024-01-01",
                        "2024-01-02",
                        "2024-01-03",
                        "2024-01-04",
                        "2024-01-05",
                        "2024-01-06",
                    ]
                ),
                "is_fraud": [0, 0, 0, 0, 0, 0],
            }
        )
        settings = SimpleNamespace(
            phase2_split_strategy="temporal",
            phase2_calibration_size=0.33,
            phase2_temporal_column="posting_date",
            phase2_profile_max_rows=100_000,
            phase2_random_seed=42,
            heuristic_high_cardinality_threshold=3,
            phase2_low_card_rare_min_count=2,
        )
        ctx = SimpleNamespace(
            model_dir=root / "models",
            company_id="acme",
            engagement_id="acme_2025",
            settings=settings,
        )

        report = run_phase2_training(
            df,
            ctx=ctx,
            strategy="datasynth",
            model_families=("unsupervised",),
            detector_factories={"unsupervised": _MatrixCaptureUnsupervised},
            base_dir=root / "phase2_train",
        )

        assert report.status == Phase2TrainingStatus.COMPLETED
        assert _MatrixCaptureUnsupervised.train_frames
        assert _MatrixCaptureUnsupervised.detect_frames
        sparse_train_frames = [
            frame
            for frame in _MatrixCaptureUnsupervised.train_frames
            if "has_cost_center" in frame.columns
        ]
        assert sparse_train_frames
        assert all("cost_center" not in frame.columns for frame in sparse_train_frames)
        assert all("tax_amount" not in frame.columns for frame in sparse_train_frames)
        assert all("document_id" not in frame.columns for frame in sparse_train_frames)

        high_card_frames = [
            frame
            for frame in _MatrixCaptureUnsupervised.train_frames
            if "vendor_name__freq" in frame.columns
        ]
        assert high_card_frames
        assert all("vendor_name" not in frame.columns for frame in high_card_frames)
        assert all("vendor_name__count" in frame.columns for frame in high_card_frames)
        assert all(
            set(frame.columns) == set(group.numeric)
            for frame, group in zip(
                _MatrixCaptureUnsupervised.train_frames,
                _MatrixCaptureUnsupervised.train_groups,
            )
        )
        assert all(
            y_len == len(frame)
            for y_len, frame in zip(
                _MatrixCaptureUnsupervised.train_y_lengths,
                _MatrixCaptureUnsupervised.train_frames,
            )
            if y_len is not None
        )

        matching_detect_frames = [
            detect_frame
            for train_frame in _MatrixCaptureUnsupervised.train_frames
            for detect_frame in _MatrixCaptureUnsupervised.detect_frames
            if list(detect_frame.columns) == list(train_frame.columns)
        ]
        assert matching_detect_frames
        assert all("CAL_ONLY" not in frame.columns for frame in matching_detect_frames)
        assert _MatrixCaptureUnsupervised.matrix_schema_hashes
        assert all(_MatrixCaptureUnsupervised.matrix_schema_hashes)
        assert all(
            names == list(frame.columns)
            for names, frame in zip(
                _MatrixCaptureUnsupervised.matrix_feature_names,
                _MatrixCaptureUnsupervised.train_frames,
            )
        )

        completed = [
            trial
            for trial in report.leaderboard
            if trial.status == Phase2TrainingStatus.COMPLETED and "matrix_builder" in trial.metadata
        ]
        assert completed
        assert all(trial.metadata["matrix_builder"]["schema_hash"] for trial in completed)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_run_phase2_training_applies_post_split_row_caps_to_detector_inputs():
    root = _make_local_temp_dir()
    _MatrixCaptureUnsupervised.train_frames = []
    _MatrixCaptureUnsupervised.detect_frames = []
    _MatrixCaptureUnsupervised.train_groups = []
    _MatrixCaptureUnsupervised.train_y_lengths = []
    _MatrixCaptureUnsupervised.matrix_schema_hashes = []
    _MatrixCaptureUnsupervised.matrix_feature_names = []
    try:
        row_count = 80
        df = pd.DataFrame(
            {
                "document_id": [f"d{i // 2:03d}" for i in range(row_count)],
                "amount": [float(i) for i in range(row_count)],
                "gl_account": [f"{4000 + (i % 5)}" for i in range(row_count)],
                "posting_date": pd.date_range("2024-01-01", periods=row_count, freq="D"),
            }
        )
        settings = SimpleNamespace(
            phase2_unsup_train_ratio=0.5,
            phase2_unsup_calibration_rows=4,
            phase2_train_max_rows=4,
            phase2_random_seed=23,
            phase2_split_strategy="group",
            phase2_split_group_column="document_id",
            phase2_temporal_column="posting_date",
            phase2_profile_max_rows=100_000,
            heuristic_high_cardinality_threshold=50,
            phase2_low_card_rare_min_count=2,
        )
        ctx = SimpleNamespace(model_dir=root / "models", settings=settings)

        report = run_phase2_training(
            df,
            ctx=ctx,
            detector_factories={"unsupervised": _MatrixCaptureUnsupervised},
            base_dir=root / "phase2_train",
        )

        completed = [
            trial
            for trial in report.leaderboard
            if trial.model_family == "unsupervised"
            and trial.status == Phase2TrainingStatus.COMPLETED
        ]
        assert completed
        assert _MatrixCaptureUnsupervised.train_frames
        assert _MatrixCaptureUnsupervised.detect_frames
        assert all(len(frame) == 4 for frame in _MatrixCaptureUnsupervised.train_frames)
        assert all(len(frame) == 4 for frame in _MatrixCaptureUnsupervised.detect_frames)
        for trial in completed:
            split_meta = trial.metadata["train_calibration_split"]
            assert split_meta["source_train_rows"] > split_meta["capped_train_rows"]
            assert split_meta["source_calibration_rows"] > split_meta["capped_calibration_rows"]
            assert split_meta["capped_train_rows"] == 4
            assert split_meta["capped_calibration_rows"] == 4
            assert split_meta["cap_strategy"]["train"] == "document_group_cap"
            assert split_meta["seed"] == 23
            assert trial.metadata["matrix_builder"]["train_matrix_shape"][0] == 4
            assert trial.metadata["matrix_builder"]["calibration_matrix_shape"][0] == 4
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_run_phase2_training_50k_smoke_budget_path_uses_capped_matrix_inputs():
    def _run_once(root: Path):
        _MatrixCaptureUnsupervised.train_frames = []
        _MatrixCaptureUnsupervised.detect_frames = []
        _MatrixCaptureUnsupervised.train_groups = []
        _MatrixCaptureUnsupervised.train_y_lengths = []
        _MatrixCaptureUnsupervised.matrix_schema_hashes = []
        _MatrixCaptureUnsupervised.matrix_feature_names = []
        row_count = 50_000
        df = pd.DataFrame(
            {
                "document_id": [f"d{i // 2:05d}" for i in range(row_count)],
                "amount": [float((i % 200) - 100) for i in range(row_count)],
                "line_count": [float((i % 7) + 1) for i in range(row_count)],
                "gl_account": [f"{4000 + (i % 25)}" for i in range(row_count)],
                "posting_date": pd.date_range("2024-01-01", periods=row_count, freq="min"),
            }
        )
        settings = SimpleNamespace(
            phase2_unsup_train_ratio=0.5,
            phase2_unsup_calibration_rows=256,
            phase2_train_max_rows=512,
            phase2_random_seed=31,
            phase2_split_strategy="group",
            phase2_split_group_column="document_id",
            phase2_temporal_column="posting_date",
            phase2_profile_max_rows=1_000,
            heuristic_high_cardinality_threshold=10,
            phase2_low_card_rare_min_count=2,
        )
        report = run_phase2_training(
            df,
            ctx=SimpleNamespace(model_dir=root / "models", settings=settings),
            detector_factories={"unsupervised": _MatrixCaptureUnsupervised},
            base_dir=root / "phase2_train",
        )
        return (
            report,
            [frame.index.tolist() for frame in _MatrixCaptureUnsupervised.train_frames],
            [frame.index.tolist() for frame in _MatrixCaptureUnsupervised.detect_frames],
        )

    root = _make_local_temp_dir()
    try:
        report_a, train_indices_a, detect_indices_a = _run_once(root / "run_a")
        report_b, train_indices_b, detect_indices_b = _run_once(root / "run_b")

        completed = [
            trial
            for trial in report_a.leaderboard
            if trial.model_family == "unsupervised"
            and trial.status == Phase2TrainingStatus.COMPLETED
        ]
        assert completed
        assert train_indices_a == train_indices_b
        assert detect_indices_a == detect_indices_b
        assert all(len(indices) <= 512 for indices in train_indices_a)
        assert all(len(indices) <= 256 for indices in detect_indices_a)
        for trial in completed:
            split_meta = trial.metadata["train_calibration_split"]
            assert split_meta["source_train_rows"] + split_meta["source_calibration_rows"] == 50_000
            assert split_meta["capped_train_rows"] <= 512
            assert split_meta["capped_calibration_rows"] <= 256
            assert trial.metadata["matrix_builder"]["train_matrix_shape"][0] <= 512
            assert trial.metadata["matrix_builder"]["calibration_matrix_shape"][0] <= 256
            assert "numeric_transform_policies" in trial.metadata["matrix_builder"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


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
        pattern = [0.1, 0.9, 0.2, 0.8]
        return [pattern[idx % len(pattern)] for idx in range(n_rows)]


class _FakeUnsupervised(_FakeDetector):
    model_name = "unsupervised_fake"
    track_name = "ml_unsupervised"

    def _score_pattern(self, n_rows: int) -> list[float]:
        if getattr(self._settings, "vae_latent_dim", 0) >= 64:
            pattern = [0.05, 0.95, 0.1, 0.9]
        else:
            pattern = [0.2, 0.8, 0.25, 0.7]
        return [pattern[idx % len(pattern)] for idx in range(n_rows)]


class _MatrixCaptureUnsupervised(_FakeDetector):
    model_name = "unsupervised_matrix_capture"
    track_name = "ml_unsupervised"
    train_frames: list[pd.DataFrame] = []
    detect_frames: list[pd.DataFrame] = []
    train_groups: list[object] = []
    train_y_lengths: list[int | None] = []
    matrix_schema_hashes: list[int] = []
    matrix_feature_names: list[list[str]] = []

    def train(self, X, groups, y=None):
        type(self).train_frames.append(X.copy())
        type(self).train_groups.append(groups)
        type(self).train_y_lengths.append(None if y is None else len(y))
        return {"mean_f1": 0.75, "n_train": len(X), "n_features": X.shape[1]}

    def detect(self, df):
        type(self).detect_frames.append(df.copy())
        return super().detect(df)

    def set_phase2_matrix_state(self, builder, metadata=None):
        metadata = dict(metadata or builder.to_metadata())
        type(self).matrix_schema_hashes.append(metadata["schema_hash"])
        type(self).matrix_feature_names.append(list(metadata["feature_names"]))


class _FakeSupervised(_FakeDetector):
    model_name = "supervised_fake"
    track_name = "ml_supervised"

    def _score_pattern(self, n_rows: int) -> list[float]:
        if self._kwargs.get("use_smote"):
            pattern = [0.05, 0.95, 0.1, 0.9]
        else:
            pattern = [0.3, 0.7, 0.35, 0.65]
        return [pattern[idx % len(pattern)] for idx in range(n_rows)]


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
        ctx = SimpleNamespace(
            model_dir=root / "models",
            settings=SimpleNamespace(
                phase2_calibration_size=0.5,
                phase2_training_mode="test_unsupervised_mvp",
                phase2_random_seed=1,
                phase2_split_strategy="group",
                phase2_split_group_column="document_id",
                phase2_temporal_column="posting_date",
                phase2_profile_max_rows=100_000,
                heuristic_high_cardinality_threshold=50,
                phase2_low_card_rare_min_count=2,
            ),
        )

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
        assert report.metadata["candidate_families"] == [
            "unsupervised",
            "timeseries",
            "relational",
            "duplicate",
            "intercompany",
        ]
        assert report.metadata["phase2_training_mode"] == "test_unsupervised_mvp"
        assert {trial.model_family for trial in report.leaderboard} == {
            "unsupervised",
            "timeseries",
            "relational",
            "duplicate",
            "intercompany",
        }
        assert all(trial.artifact_path for trial in report.leaderboard)
        assert report.promoted_models
        assert "best_overall_model" in report.metadata
        assert report.metadata["promotion_policy"]["selection_mode"] == "best_per_family"
        assert report.metadata["promotion_policy"]["requires_registry_version"] is True
        assert report.metadata["promotion_policy"]["min_completed_trials_per_family"] == 2
        assert (
            report.metadata["promotion_policy"]["tie_break_policy"]["primary"]
            == "metric_value_desc"
        )
        assert report.metadata["inference_contract"]["promoted_versions"]["unsupervised"] >= 1
        assert (
            report.metadata["inference_contract"]["model_versions"]["unsupervised"]["model_version"]
            >= 1
        )
        assert (
            "schema_hash" in report.metadata["inference_contract"]["model_versions"]["unsupervised"]
        )
        assert (
            report.metadata["inference_contract"]["track_map"]["unsupervised"] == "ml_unsupervised"
        )
        assert report.metadata["trial_status_counts"]["completed"] > 0
        # Why: preset 단일화(balanced) 후 best_variant 는 무조건 balanced 종결.
        assert report.metadata["family_summaries"]["unsupervised"]["best_variant"].endswith(
            "balanced"
        )
        completed_unsupervised = [
            trial
            for trial in report.leaderboard
            if trial.model_family == "unsupervised"
            and trial.status == Phase2TrainingStatus.COMPLETED
        ]
        assert completed_unsupervised
        assert (
            completed_unsupervised[0].metadata["train_calibration_split"]["split_strategy"]
            == "group"
        )
        assert completed_unsupervised[0].metadata["matrix_builder"]["feature_count"] > 0
        assert completed_unsupervised[0].metadata["matrix_builder"]["train_matrix_shape"][0] == 2
        assert report.metadata["feature_variant_summaries"]["plus_persona"]["trial_count"] > 0
        assert (
            report.metadata["promotion_policy"]["rule_style_metric_policy"]["metric_name"]
            == "rule_proxy_score"
        )
        assert set(report.metadata["sub_detector_summaries"]) <= {
            "timeseries",
            "relational",
            "duplicate",
            "intercompany",
        }
        assert set(report.metadata["family_promotion_decisions"]) == {
            "unsupervised",
            "timeseries",
            "relational",
            "duplicate",
            "intercompany",
        }
        case_contract = report.metadata["inference_contract"]["phase1_case_contract"]
        assert case_contract["available"] is False
        assert "top_rule_ids" in case_contract["provenance_only_fields"]
        assert (
            root / "phase2_train" / report.report_id / "reports" / "training_report.json"
        ).exists()
        assert (root / "phase2_train" / report.report_id / "reports" / "leaderboard.json").exists()
        assert (
            root / "phase2_train" / report.report_id / "reports" / "promotion_decision.json"
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


# ──────────────────────────────────────────────────────────────────────────────
# _RULE_STYLE_SUB_DETECTORS ↔ phase2_subdetector_tiers.yaml 정합 lock
#
# tier registry (21 항목) 와 training metadata sub_detector_keys 는 의도적으로
# 다른 범위를 가진다. IC family 의 4개 internal probability column
# (ic_reciprocal_flow_prob / ic_amount_prob / ic_unmatched_prob / ic_timing_prob)
# 은 tier registry 에는 등록하되 training metadata 에서는 의도적으로 제외한다 —
# IntercompanyMatcher detector 내부에서 한 번에 산출되는 probability surface 이지
# 독립 학습 trial 대상이 아니기 때문이다. 본 lock 은 이 비대칭이 우연한 누락이
# 아니라 의도된 설계임을 코드 단에서 고정한다 (2026-05-25 옵션 2 결정).
# ──────────────────────────────────────────────────────────────────────────────


class TestRuleStyleSubDetectorRegistryContract:
    """training metadata 의 sub_detector_keys 가 tier registry 와 의도적으로
    다른 범위를 가짐을 lock 하는 회귀.
    """

    def test_intercompany_training_keys_only_canonical_labels(self):
        """IC training sub_detector_keys 는 IC01/02/03 의 label 3개만 보고한다.

        IC internal probability column (ic_reciprocal_flow_prob / ic_amount_prob /
        ic_unmatched_prob / ic_timing_prob) 는 detector 내부 surface 이므로
        training trial sub_detector_keys 에서 제외한다.
        """
        from src.services.phase2_training_service import _RULE_STYLE_SUB_DETECTORS

        intercompany_keys = _RULE_STYLE_SUB_DETECTORS["intercompany"]
        assert intercompany_keys == (
            "unmatched_intercompany",
            "amount_mismatch",
            "timing_gap",
        )

    def test_ic_internal_prob_codes_excluded_from_training_keys(self):
        """ic_* prefix internal probability column 은 training keys 에 등장하지 않는다."""
        from src.services.phase2_training_service import _RULE_STYLE_SUB_DETECTORS

        for family, keys in _RULE_STYLE_SUB_DETECTORS.items():
            leaked = [key for key in keys if key.startswith("ic_")]
            assert leaked == [], f"family {family} 에 IC internal prob key 누출: {leaked}"

    def test_ic_internal_prob_codes_registered_in_tier_registry(self):
        """tier registry 쪽은 4개 internal prob column 을 보유.

        training metadata 와의 비대칭이 의도된 설계임을 확인하는 회귀.
        """
        from src.services.subdetector_tiers import get_subdetector_tier_index

        tier_index = get_subdetector_tier_index()
        registry_ic_codes = {
            code for (family, code) in tier_index.keys() if family == "intercompany"
        }
        # IC01~03 canonical + 4 internal prob = 7
        expected_internal = {
            "ic_reciprocal_flow_prob",
            "ic_amount_prob",
            "ic_unmatched_prob",
            "ic_timing_prob",
        }
        assert expected_internal.issubset(registry_ic_codes), (
            f"tier registry 에 IC internal prob 4개 누락: {expected_internal - registry_ic_codes}"
        )
