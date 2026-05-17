"""Layer A 8가드 단위 테스트 — Stage 5 학습 산출물(training_report.json) 검증.

PHASE2 Layer A 가드는 unsupervised autoencoder 학습이 다음 8개 조건을 모두 만족하는지 확인한다:
    A1 dataset_version pin
    A2 deny_list_applied + excluded_columns 누적 >= 76
    A3 split_strategy == group_by_document_id
    A4 fit_split == train (val/test transform-only)
    A5 no document_id leakage cross-check
    A6 epoch_count 존재 (fit 흐름 정상)
    A7 target_used == false (unsupervised)
    A8 reconstruction-only loss signature, 금지 label loss 키 부재

본 모듈은 학습을 재실행하지 않고 baseline training_report.json 을 fixture 로 로드한다
(빠른 단위 테스트). 실 학습 회귀는 Stage 5/6 산출물 (artifacts/phase2_layer_*.{md,json})
및 audit-testing 워크플로우에서 별도 검증된다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TRAINING_REPORT_PATH = (
    ROOT
    / "data"
    / "companies"
    / "_ci_baseline"
    / "engagements"
    / "2026"
    / "models"
    / "phase2_unsupervised"
    / "v1"
    / "training_report.json"
)

# Layer A 가드 기준 상수 (artifacts/phase2_layer_a_audit_*.json 과 동일 출처)
EXPECTED_DATASET_VERSION = "datasynth_manipulation_v7_candidate_fixed3"
EXPECTED_SPLIT_STRATEGY = "group_by_document_id"
EXPECTED_TRAINING_MODE = "unsupervised_autoencoder_mvp"
EXPECTED_LOSS_SIGNATURE = "reconstruction_only_mse_plus_kl"
MIN_EXCLUDED_COLUMNS = 76  # row-level exclude + raw-header deny-list 누적 하한
FORBIDDEN_LOSS_KEYS = (
    "bce_loss",
    "cross_entropy_loss",
    "label_loss",
    "supervised_loss",
)


@pytest.fixture(scope="module")
def training_report() -> dict:
    if not TRAINING_REPORT_PATH.exists():
        pytest.skip(
            "Stage 5 학습 산출물(training_report.json) 부재. CI baseline 미커밋 환경에서는 스킵."
        )
    return json.loads(TRAINING_REPORT_PATH.read_text(encoding="utf-8"))


def test_training_report_required_keys(training_report: dict) -> None:
    """training_report.json 에 Layer A 검증에 필요한 8개 필수 키가 존재한다."""
    required = {
        "dataset_version",
        "split_strategy",
        "training_mode",
        "target_used",
        "deny_list_applied",
        "epoch_history",
        "split_metadata",
        "layer_a_gates",
    }
    missing = required - set(training_report.keys())
    assert not missing, f"Layer A 가드용 필수 키 누락: {sorted(missing)}"


def test_layer_a1_dataset_version_pinned(training_report: dict) -> None:
    """A1: dataset_version 이 v7 fixed3 baseline 으로 pin 되어 있다."""
    assert training_report["dataset_version"] == EXPECTED_DATASET_VERSION


def test_layer_a2_deny_list_applied(training_report: dict) -> None:
    """A2: deny_list_applied=True 이고 누적 거부 컬럼 수 >= MIN_EXCLUDED_COLUMNS."""
    assert training_report["deny_list_applied"] is True
    plan_summary = training_report["preprocessing_plan_summary"]
    action_counts = plan_summary["action_counts"]
    reason_counts = plan_summary["reason_code_counts"]

    row_level_excluded = int(action_counts.get("exclude", 0))
    raw_header_excluded = int(
        training_report["layer_a_gates"]["A1"].get("excluded_from_raw_count", 0)
    )
    total_excluded = row_level_excluded + raw_header_excluded

    assert total_excluded >= MIN_EXCLUDED_COLUMNS, (
        f"누적 거부 컬럼 {total_excluded} < {MIN_EXCLUDED_COLUMNS}. "
        f"row_level={row_level_excluded}, raw_header={raw_header_excluded}"
    )
    # leakage_deny_column reason 이 36 이상으로 raw header deny-list 가 실제 적용됐는지 교차 검증
    assert reason_counts.get("leakage_deny_column", 0) >= 36


def test_layer_a3_split_strategy_group_by_document_id(training_report: dict) -> None:
    """A3: split_strategy == group_by_document_id (document 단위 분리)."""
    assert training_report["split_strategy"] == EXPECTED_SPLIT_STRATEGY
    assert training_report["split_metadata"]["split_strategy"] == EXPECTED_SPLIT_STRATEGY
    assert training_report["split_metadata"]["group_column"] == "document_id"


def test_layer_a4_fit_only_on_train(training_report: dict) -> None:
    """A4: fit_split == train (val/test transform-only) — A6 gate detail 활용."""
    a6 = training_report["layer_a_gates"]["A6"]
    assert a6["fit_split"] == "train"
    assert int(a6["train_rows_used_for_fit"]) > 0
    assert int(a6["val_rows_transform_only"]) > 0
    assert int(a6["test_rows_transform_only"]) > 0


def test_layer_a5_no_document_id_leakage(training_report: dict) -> None:
    """A5: train/val/test document_id leak 없음 (cross-check pass)."""
    split_meta = training_report["split_metadata"]
    assert split_meta["leakage_cross_check_passed"] is True
    # docs counts 양수 (실제 분리 발생)
    assert int(split_meta["train_docs_after_cap"]) > 0
    assert int(split_meta["val_docs_after_cap"]) > 0
    assert int(split_meta["test_docs_after_cap"]) > 0


def test_layer_a6_epoch_count_present(training_report: dict) -> None:
    """A6: epoch_history 존재 + epochs_run > 0 (fit 흐름이 실제로 돌았다)."""
    epoch_history = training_report["epoch_history"]
    assert isinstance(epoch_history, list)
    assert len(epoch_history) > 0
    epochs_run = int(training_report["training_hyperparams"]["epochs_run"])
    assert epochs_run == len(epoch_history)


def test_layer_a7_target_used_false(training_report: dict) -> None:
    """A7: target_used == False, training_mode == unsupervised_autoencoder_mvp."""
    assert training_report["target_used"] is False
    assert training_report["training_mode"] == EXPECTED_TRAINING_MODE
    # gate detail 도 함께 검증
    a7 = training_report["layer_a_gates"]["A7"]
    assert a7["target_used"] is False
    assert a7["loss"] == EXPECTED_LOSS_SIGNATURE


def test_layer_a8_reconstruction_loss_only(training_report: dict) -> None:
    """A8: reconstruction/KL loss만 존재, 금지 label loss 키 부재.

    training_report.json A8 gate detail 은 schema_hash 일치 검증을 담당하고,
    loss 시그니처 검증은 A7 gate 의 ``loss`` 필드 + epoch_history 키 교차로 수행한다.
    """
    a7 = training_report["layer_a_gates"]["A7"]
    assert a7["loss"] == EXPECTED_LOSS_SIGNATURE

    # epoch_history 키 자체에서 reconstruction/KL 만 존재하고 금지 키 부재 확인
    sample_epoch = training_report["epoch_history"][0]
    epoch_keys = set(sample_epoch.keys())
    assert any("reconstruction_loss" in key for key in epoch_keys), (
        f"reconstruction loss 키 부재. epoch_keys={sorted(epoch_keys)}"
    )
    assert any("kl_loss" in key for key in epoch_keys), (
        f"KL loss 키 부재. epoch_keys={sorted(epoch_keys)}"
    )
    forbidden_present = [key for key in FORBIDDEN_LOSS_KEYS if key in epoch_keys]
    assert not forbidden_present, (
        f"epoch_history 에 금지된 label-based loss 키 발견: {forbidden_present}"
    )

    # A8 gate detail 검증 (schema_hash bundle vs report match)
    a8 = training_report["layer_a_gates"]["A8"]
    assert a8.get("status") == "PASS"
    assert a8.get("match") is True
    assert a8.get("schema_hash_in_bundle") == a8.get("schema_hash_in_report")


def test_layer_a_all_hard_gates_pass(training_report: dict) -> None:
    """8 가드 종합: 모든 Layer A 가드가 운영 기준 PASS."""
    statuses = training_report["layer_a_gates_status"]
    for gate_id in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"):
        assert statuses.get(gate_id) == "PASS", (
            f"Layer A gate {gate_id} 상태 {statuses.get(gate_id)} — PASS 필요"
        )
    assert training_report.get("all_layer_a_hard_pass") is True
    assert training_report.get("layer_a_strict_all_pass") is True


def test_layer_a_a3_a4_operational_threshold_calibrated(training_report: dict) -> None:
    """A3/A4: ECDF q95 운영 임계는 정상 발생률을 반영한 8%."""
    for gate_id in ("A3", "A4"):
        gate = training_report["layer_a_gates"][gate_id]
        assert gate["operational_threshold"] == pytest.approx(0.08)
        assert gate["high_ratio"] <= gate["operational_threshold"]
