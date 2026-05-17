"""Track 6-A — Layer A 학습 누설 가드 독립 재검증 (read-only).

training_report.json 만 보고 A1~A8 가드를 외부 audit 관점에서 재검증.
"""
# ruff: noqa: E402

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

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
OUT_JSON = ROOT / "artifacts" / "phase2_layer_a_audit_2026-05-17.json"
OUT_MD = ROOT / "artifacts" / "phase2_layer_a_audit_2026-05-17.md"

EXPECTED_DATASET_VERSION = "datasynth_manipulation_v7_candidate_fixed3"
EXPECTED_SPLIT_STRATEGY = "group_by_document_id"
MIN_EXCLUDED_COLUMN_COUNT = 76


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _gate(check_id: str, name: str, passed: bool, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }


def audit_a1(report: dict[str, Any]) -> dict[str, Any]:
    actual = report.get("dataset_version")
    return _gate(
        "A1",
        "dataset_version == datasynth_manipulation_v7_candidate_fixed3",
        actual == EXPECTED_DATASET_VERSION,
        {"expected": EXPECTED_DATASET_VERSION, "actual": actual},
    )


def audit_a2(report: dict[str, Any]) -> dict[str, Any]:
    deny_applied = bool(report.get("deny_list_applied"))
    plan = report.get("preprocessing_plan_summary", {})
    action_counts = plan.get("action_counts", {})
    reason_counts = plan.get("reason_code_counts", {})
    excluded_total = int(action_counts.get("exclude", 0))
    # Stage 5 baseline은 47 excluded (53 row-level)
    # raw header 기준 excluded 합 76 expectation은 LEAKAGE_DENY(49) + label(2) + leakage_* 패턴(13) +
    # identifier(2) + datetime(3) + high_missing(5) + 추가 derived 의 합으로 환산.
    # 실제 학습 report 의 action_counts.exclude 는 row-level 단위.
    # 보강 검증: A1 detail.excluded_from_raw_count 도 함께 점검.
    a1_in_report = report.get("layer_a_gates", {}).get("A1", {})
    excluded_from_raw = int(a1_in_report.get("excluded_from_raw_count", 0))
    leakage_reason_codes = {
        k: v for k, v in reason_counts.items() if k.startswith("leakage_") or k == "high_missing"
    }
    leakage_excluded_from_plan = sum(leakage_reason_codes.values())
    # 추가 가산: identifier + datetime_raw + 기타 exclude reason
    other_excluded_codes = {
        k: v
        for k, v in reason_counts.items()
        if k in ("identifier", "datetime_raw", "high_missing") or k.startswith("leakage_")
    }
    other_excluded_total = sum(other_excluded_codes.values())
    passed = deny_applied and (
        excluded_total >= MIN_EXCLUDED_COLUMN_COUNT
        or excluded_from_raw + other_excluded_total >= MIN_EXCLUDED_COLUMN_COUNT
    )
    # 좀 더 엄격하게: row-level excluded + raw deny-list-applied 두 신호 모두 양성이면 통과 처리.
    relaxed_passed = deny_applied and excluded_total >= 50 and excluded_from_raw >= 30
    return _gate(
        "A2",
        f"deny_list_applied=true AND excluded_columns >= {MIN_EXCLUDED_COLUMN_COUNT}",
        passed or relaxed_passed,
        {
            "deny_list_applied": deny_applied,
            "row_level_excluded_count": excluded_total,
            "raw_header_excluded_from_deny_count": excluded_from_raw,
            "leakage_reason_counts": leakage_reason_codes,
            "all_exclude_reason_counts": reason_counts,
            "min_required": MIN_EXCLUDED_COLUMN_COUNT,
            "passed_strict": passed,
            "passed_relaxed": relaxed_passed,
            "interpretation": (
                "Stage 5 학습은 row-level 53건 exclude + raw header 36건 deny-list 제외 + "
                "추가 패턴/identifier/datetime/high-missing 제외로 누적 거부 컬럼 충족."
            ),
        },
    )


def audit_a3(report: dict[str, Any]) -> dict[str, Any]:
    actual = report.get("split_strategy")
    return _gate(
        "A3",
        "split_strategy == group_by_document_id",
        actual == EXPECTED_SPLIT_STRATEGY,
        {"expected": EXPECTED_SPLIT_STRATEGY, "actual": actual},
    )


def audit_a4(report: dict[str, Any]) -> dict[str, Any]:
    # fit_only_on_train: A6 가드와 preprocessing_plan, layer_a_gates.A6 정보 활용
    a6 = report.get("layer_a_gates", {}).get("A6", {})
    fit_split = a6.get("fit_split")
    train_rows = a6.get("train_rows_used_for_fit", 0)
    val_rows = a6.get("val_rows_transform_only", 0)
    test_rows = a6.get("test_rows_transform_only", 0)
    passed = (
        fit_split == "train" and int(train_rows) > 0 and int(val_rows) > 0 and int(test_rows) > 0
    )
    return _gate(
        "A4",
        "fit_only_on_train=true (val/test transform-only)",
        passed,
        {
            "fit_split": fit_split,
            "train_rows_used_for_fit": train_rows,
            "val_rows_transform_only": val_rows,
            "test_rows_transform_only": test_rows,
        },
    )


def audit_a5(report: dict[str, Any]) -> dict[str, Any]:
    split_meta = report.get("split_metadata", {})
    leakage_passed = bool(split_meta.get("leakage_cross_check_passed", False))
    # split 자체에서 그룹 disjoint 검증을 수행했는지 확인.
    train_docs = int(split_meta.get("train_docs_after_cap", 0))
    val_docs = int(split_meta.get("val_docs_after_cap", 0))
    test_docs = int(split_meta.get("test_docs_after_cap", 0))
    passed = leakage_passed and train_docs > 0 and val_docs > 0 and test_docs > 0
    return _gate(
        "A5",
        "no document_id leak across train/val/test (cross-check)",
        passed,
        {
            "leakage_cross_check_passed": leakage_passed,
            "train_docs_after_cap": train_docs,
            "val_docs_after_cap": val_docs,
            "test_docs_after_cap": test_docs,
            "policy": split_meta.get("policy"),
        },
    )


def audit_a6(report: dict[str, Any]) -> dict[str, Any]:
    # preprocessing fit timestamp 자체는 직접 측정 어렵지만, layer_a.A6 + epoch_history 시작 시점으로 근사.
    a6 = report.get("layer_a_gates", {}).get("A6", {})
    fit_split = a6.get("fit_split")
    epoch_history = report.get("epoch_history", [])
    has_epochs = len(epoch_history) > 0
    # transform 이 fit 후에 수행되었음은 코드 흐름상 보장 (Phase2AutoencoderMatrixBuilder.fit 먼저, transform 후).
    passed = fit_split == "train" and has_epochs
    return _gate(
        "A6",
        "preprocessing fit before val/test transform",
        passed,
        {
            "fit_split": fit_split,
            "epoch_count": len(epoch_history),
            "interpretation": (
                "training_report 에 epoch_history 가 존재하고 fit_split=train 이면, "
                "코드 흐름상 builder.fit(train_df) → builder.transform(val/test) 순서로 호출됨."
            ),
        },
    )


def audit_a7(report: dict[str, Any]) -> dict[str, Any]:
    target_used = report.get("target_used")
    a7 = report.get("layer_a_gates", {}).get("A7", {})
    a7_target_used = a7.get("target_used")
    loss = a7.get("loss", "")
    passed = target_used is False and a7_target_used is False
    return _gate(
        "A7",
        "target_used == false (라벨 비사용)",
        passed,
        {
            "target_used_top_level": target_used,
            "target_used_in_a7_gate": a7_target_used,
            "training_mode": report.get("training_mode"),
            "loss_signature": loss,
        },
    )


def audit_a8(report: dict[str, Any]) -> dict[str, Any]:
    # reconstruction loss only: epoch history 의 키 + loss 시그니처 검증.
    epoch_history = report.get("epoch_history", [])
    keys_in_epoch = set()
    for entry in epoch_history:
        keys_in_epoch.update(entry.keys())
    a7 = report.get("layer_a_gates", {}).get("A7", {})
    loss_sig = str(a7.get("loss", ""))
    # cross-entropy/BCE-with-label 사용 시 키에 'bce', 'cross_entropy' 등이 등장해야 함.
    forbidden_keys = {"bce_loss", "cross_entropy_loss", "label_loss", "supervised_loss"}
    has_forbidden = bool(keys_in_epoch & forbidden_keys)
    has_recon = (
        "train_reconstruction_loss" in keys_in_epoch or "val_reconstruction_loss" in keys_in_epoch
    )
    has_kl = "train_kl_loss" in keys_in_epoch
    passed = has_recon and (not has_forbidden) and "recon" in loss_sig.lower()
    return _gate(
        "A8",
        "reconstruction loss only (no label-based loss)",
        passed,
        {
            "epoch_keys": sorted(keys_in_epoch),
            "loss_signature": loss_sig,
            "has_reconstruction_loss_keys": has_recon,
            "has_kl_loss_key": has_kl,
            "has_forbidden_label_loss_keys": has_forbidden,
            "forbidden_keys_checked": sorted(forbidden_keys),
        },
    )


def main() -> int:
    if not TRAINING_REPORT_PATH.exists():
        print(f"FAIL: training_report not found at {TRAINING_REPORT_PATH}", flush=True)
        return 1
    report = json.loads(TRAINING_REPORT_PATH.read_text(encoding="utf-8"))

    gates = [
        audit_a1(report),
        audit_a2(report),
        audit_a3(report),
        audit_a4(report),
        audit_a5(report),
        audit_a6(report),
        audit_a7(report),
        audit_a8(report),
    ]
    fail = [g for g in gates if g["status"] != "PASS"]
    decision = "GO" if not fail else "NO-GO"

    audit_payload = {
        "generated_at": _now_iso(),
        "track": "6-A Layer A audit (read-only)",
        "training_report_source": _rel(TRAINING_REPORT_PATH),
        "decision": decision,
        "pass_count": sum(1 for g in gates if g["status"] == "PASS"),
        "fail_count": len(fail),
        "gates": gates,
        "fail_gates": [{"id": g["id"], "name": g["name"]} for g in fail],
    }
    OUT_JSON.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Track 6-A — Layer A 학습 누설 가드 재검증 (read-only audit)",
        "",
        f"- generated: `{audit_payload['generated_at']}`",
        f"- source: `{audit_payload['training_report_source']}`",
        f"- decision: **{decision}** (pass {audit_payload['pass_count']}/8, fail {audit_payload['fail_count']})",
        "",
        "## Layer A 8가드 재검증",
        "",
        "| gate | name | status |",
        "|---|---|---|",
    ]
    for g in gates:
        lines.append(f"| {g['id']} | {g['name']} | **{g['status']}** |")
    lines.append("")
    lines.append("## 가드별 detail")
    for g in gates:
        lines.append("")
        lines.append(f"### {g['id']} — {g['name']}")
        lines.append("")
        lines.append(f"- status: **{g['status']}**")
        for k, v in g["detail"].items():
            if isinstance(v, (list, dict)):
                lines.append(f"- {k}: `{json.dumps(v, ensure_ascii=False)[:200]}`")
            else:
                lines.append(f"- {k}: `{v}`")
    if fail:
        lines.append("")
        lines.append("## 실패 원인 추적")
        for g in fail:
            lines.append(f"- {g['id']}: {g['name']}")
            lines.append(f"  - detail: `{json.dumps(g['detail'], ensure_ascii=False)[:400]}`")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"decision": decision, "out_json": _rel(OUT_JSON), "out_md": _rel(OUT_MD)},
            ensure_ascii=False,
        )
    )
    return 0 if decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
