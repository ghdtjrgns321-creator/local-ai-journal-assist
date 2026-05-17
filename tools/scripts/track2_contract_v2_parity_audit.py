"""Track 2 — contract_v2 PHASE1 enrichment parity audit and A4 remeasurement.

This script does not retrain PHASE2. It materializes the existing PHASE1
contract_v2 enrichment cache to parquet, then scores the first 10k rows with
the persisted V7 fixed3 model bundle.
"""

from __future__ import annotations

import io
import json
import pickle
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.preprocessing.vae_model import AuditVAE  # noqa: E402

EXPECTED_CACHE = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"
CONTRACT_PHASE1_CACHE = ROOT / "artifacts" / "phase1_contract_v2_case_input_20260514.pkl"
CONTRACT_RAW_CSV = (
    ROOT / "data" / "journal" / "primary" / "datasynth_contract_v2" / "journal_entries.csv"
)
CONTRACT_ENRICHED_PARQUET = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_contract_v2_enriched"
    / "journal_entries.parquet"
)
CONTRACT_ENRICHED_NORMAL_PARQUET = (
    CONTRACT_ENRICHED_PARQUET.parent.parent
    / "datasynth_contract_v2_enriched_normal"
    / "journal_entries.parquet"
)
MODEL_BUNDLE = (
    ROOT
    / "data"
    / "companies"
    / "_ci_baseline"
    / "engagements"
    / "2026"
    / "models"
    / "phase2_unsupervised"
    / "v1"
    / "model_bundle.pt"
)
TRAINING_REPORT = MODEL_BUNDLE.with_name("training_report.json")
OUT_JSON = ROOT / "artifacts" / "phase2_inference_report_v7_fixed3_recalibrated_2026-05-17.json"
OUT_MD = ROOT / "artifacts" / "track2_contract_v2_parity_audit_2026-05-17.md"

OPERATIONAL_HIGH_RATIO_THRESHOLD = 0.08
FIXTURE_ROWS = 10_000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _load_cache_df(path: Path) -> pd.DataFrame:
    with path.open("rb") as fh:
        payload = pickle.load(fh)
    if isinstance(payload, dict) and "df" in payload:
        return payload["df"]
    if isinstance(payload, pd.DataFrame):
        return payload
    raise TypeError(f"unsupported cache payload at {path}")


def _read_parquet_head(path: Path, nrows: int) -> pd.DataFrame:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    batches = parquet.iter_batches(batch_size=nrows)
    try:
        batch = next(batches)
    except StopIteration:
        return pd.DataFrame()
    return batch.to_pandas()


def _load_bundle() -> dict[str, Any]:
    with MODEL_BUNDLE.open("rb") as fh:
        return pickle.load(fh)


def _builder_source_columns(builder: Any) -> list[str]:
    return sorted(
        set(builder.amount_columns)
        | set(builder.general_numeric_columns)
        | set(builder.low_card_columns)
        | set(builder.high_card_columns)
        | set(builder.boolean_columns)
        | set(builder.sparse_dropped_columns)
    )


def _score_fixture(fixture_df: pd.DataFrame, bundle: dict[str, Any]) -> dict[str, Any]:
    builder = bundle["matrix_builder"]
    source_columns = _builder_source_columns(builder)
    missing_source_columns = sorted(set(source_columns) - set(fixture_df.columns))
    matrix = builder.transform(fixture_df)

    torch.manual_seed(42)
    model = AuditVAE(bundle["input_dim"], bundle["latent_dim"], bundle["hidden_dim"])
    state = torch.load(
        io.BytesIO(bundle["model_state_dict"]),
        map_location="cpu",
        weights_only=True,
    )
    model.load_state_dict(state)
    model.eval()

    arr_raw = np.nan_to_num(
        matrix.to_numpy(dtype=np.float32),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    arr = bundle["post_scaler"].transform(arr_raw).astype(np.float32)
    arr = np.clip(
        np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0),
        -10.0,
        10.0,
    ).astype(np.float32)

    scores: list[np.ndarray] = []
    with torch.no_grad():
        tensor = torch.from_numpy(arr)
        for start in range(0, len(tensor), 1024):
            chunk = tensor[start : start + 1024]
            recon, _, _ = model(chunk)
            scores.append(((recon - chunk) ** 2).mean(dim=1).cpu().numpy())
    raw_scores = np.concatenate(scores)
    train_sorted = bundle["ecdf_train_sorted"]
    ecdf_scores = np.searchsorted(train_sorted, raw_scores) / max(len(train_sorted), 1)
    high_mask = ecdf_scores >= 0.95
    return {
        "rows": int(len(fixture_df)),
        "raw_recon_mean": float(raw_scores.mean()),
        "raw_recon_std": float(raw_scores.std()),
        "ecdf_mean": float(ecdf_scores.mean()),
        "high_threshold": 0.95,
        "high_count": int(high_mask.sum()),
        "high_ratio": float(high_mask.mean()),
        "builder_source_column_count": len(source_columns),
        "missing_builder_source_column_count": len(missing_source_columns),
        "missing_builder_source_columns": missing_source_columns,
        "matrix_feature_count": int(matrix.shape[1]),
        "schema_hash": int(bundle["schema_hash"]),
    }


def _materialize_enriched_parquet(contract_df: pd.DataFrame) -> dict[str, Any]:
    CONTRACT_ENRICHED_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    contract_df.to_parquet(CONTRACT_ENRICHED_PARQUET, index=False)
    return {
        "path": _rel(CONTRACT_ENRICHED_PARQUET),
        "rows": int(len(contract_df)),
        "columns": int(len(contract_df.columns)),
        "size_mb": round(CONTRACT_ENRICHED_PARQUET.stat().st_size / 1024 / 1024, 3),
    }


def _materialize_normal_parquet(contract_df: pd.DataFrame) -> dict[str, Any]:
    CONTRACT_ENRICHED_NORMAL_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    if "mutation_type" in contract_df.columns:
        mutation = contract_df["mutation_type"]
        normal_mask = mutation.isna() | mutation.astype(str).str.strip().isin(
            {"", "None", "nan", "NaN"}
        )
    else:
        normal_mask = pd.Series(True, index=contract_df.index)
    normal_df = contract_df.loc[normal_mask].drop(
        columns=["mutation_type", "mutation_reason"], errors="ignore"
    )
    normal_df.to_parquet(CONTRACT_ENRICHED_NORMAL_PARQUET, index=False)
    return {
        "path": _rel(CONTRACT_ENRICHED_NORMAL_PARQUET),
        "rows": int(len(normal_df)),
        "columns": int(len(normal_df.columns)),
        "mutation_rows_excluded": int(len(contract_df) - len(normal_df)),
        "mutation_columns_removed": [
            col for col in ("mutation_type", "mutation_reason") if col in contract_df.columns
        ],
        "size_mb": round(CONTRACT_ENRICHED_NORMAL_PARQUET.stat().st_size / 1024 / 1024, 3),
    }


def main() -> int:
    generated_at = _now_iso()
    expected_df = _load_cache_df(EXPECTED_CACHE)
    contract_df = _load_cache_df(CONTRACT_PHASE1_CACHE)
    raw_header = pd.read_csv(CONTRACT_RAW_CSV, nrows=0)
    training_report = json.loads(TRAINING_REPORT.read_text(encoding="utf-8"))

    expected_columns = list(expected_df.columns)
    raw_columns = list(raw_header.columns)
    enriched_columns = list(contract_df.columns)
    missing_from_enriched = sorted(set(expected_columns) - set(enriched_columns))
    extra_in_enriched = sorted(set(enriched_columns) - set(expected_columns))
    missing_from_raw = sorted(set(expected_columns) - set(raw_columns))
    extra_in_raw = sorted(set(raw_columns) - set(expected_columns))

    parquet_info = _materialize_enriched_parquet(contract_df)
    normal_parquet_info = _materialize_normal_parquet(contract_df)
    fixture_df = _read_parquet_head(CONTRACT_ENRICHED_NORMAL_PARQUET, FIXTURE_ROWS)
    bundle = _load_bundle()
    a4 = _score_fixture(fixture_df, bundle)
    a4_pass = (
        a4["rows"] == FIXTURE_ROWS
        and a4["missing_builder_source_column_count"] == 0
        and a4["high_ratio"] <= OPERATIONAL_HIGH_RATIO_THRESHOLD
    )

    payload = {
        "generated_at": generated_at,
        "track": "Track 2 contract_v2 fixture parity",
        "strategy": {
            "selected": "Option A",
            "source": _rel(CONTRACT_PHASE1_CACHE),
            "output": parquet_info,
            "normal_output": normal_parquet_info,
            "note": (
                "Existing contract_v2 PHASE1 cache is materialized to parquet, then "
                "mutation rows are excluded into a normal-only fixture. The raw CSV, "
                "fixed3 manipulation data, and PHASE2 model artifacts are read-only."
            ),
        },
        "training_report": {
            "path": _rel(TRAINING_REPORT),
            "report_id": training_report.get("report_id"),
            "decision_count": training_report.get("preprocessing_plan_summary", {}).get(
                "decision_count"
            ),
            "schema_hash": training_report.get("schema_hash"),
        },
        "column_diff": {
            "expected_count": len(expected_columns),
            "raw_count": len(raw_columns),
            "enriched_count": len(enriched_columns),
            "enriched_equals_expected": (
                not missing_from_enriched and not extra_in_enriched
            ),
            "missing_from_raw_count": len(missing_from_raw),
            "missing_from_raw": missing_from_raw,
            "extra_in_raw": extra_in_raw,
            "missing_from_enriched_count": len(missing_from_enriched),
            "missing_from_enriched": missing_from_enriched,
            "extra_in_enriched": extra_in_enriched,
        },
        "a4_remeasurement": {
            "fixture": _rel(CONTRACT_ENRICHED_NORMAL_PARQUET),
            "fixture_rows_scored": FIXTURE_ROWS,
            "operational_threshold_high_ratio": OPERATIONAL_HIGH_RATIO_THRESHOLD,
            "status": "PASS" if a4_pass else "FAIL",
            "informational_for_first_training": False,
            **a4,
        },
        "immutability": {
            "model_bundle_changed": False,
            "ecdf_train_distribution_changed": False,
            "model_retrained": False,
        },
        "operational_verdict": "PASS" if a4_pass else "FAIL",
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Track 2 — contract_v2 fixture parity audit",
        "",
        f"- generated: `{generated_at}`",
        (
            "- strategy: **Option A** — materialize existing PHASE1-enriched "
            "contract_v2 cache to parquet"
        ),
        f"- source cache: `{_rel(CONTRACT_PHASE1_CACHE)}`",
        f"- enriched fixture: `{_rel(CONTRACT_ENRICHED_PARQUET)}`",
        f"- enriched normal fixture: `{_rel(CONTRACT_ENRICHED_NORMAL_PARQUET)}`",
        f"- training report: `{_rel(TRAINING_REPORT)}`",
        "",
        "## Column parity",
        "",
        f"- expected columns: `{len(expected_columns)}`",
        f"- raw CSV columns: `{len(raw_columns)}`",
        f"- enriched parquet columns: `{len(enriched_columns)}`",
        f"- raw missing expected columns: `{len(missing_from_raw)}`",
        f"- enriched missing expected columns: `{len(missing_from_enriched)}`",
        f"- enriched extra columns: `{len(extra_in_enriched)}`",
        (
            "- builder source columns missing at transform: "
            f"`{a4['missing_builder_source_column_count']}`"
        ),
        "",
        "## A4 remeasurement",
        "",
        f"- rows scored: `{FIXTURE_ROWS}`",
        f"- ecdf_mean: `{a4['ecdf_mean']:.6f}`",
        f"- high_count: `{a4['high_count']}`",
        f"- high_ratio: `{a4['high_ratio']:.6f}`",
        f"- operational threshold: `{OPERATIONAL_HIGH_RATIO_THRESHOLD:.4f}`",
        f"- status: **{'PASS' if a4_pass else 'FAIL'}**",
        f"- operational verdict: **{payload['operational_verdict']}**",
        "",
        "## Immutability",
        "",
        "- model_bundle.pt: unchanged/read-only",
        "- ecdf_train_distribution.npz: unchanged/read-only",
        "- model retraining: not performed",
    ]
    if missing_from_raw:
        lines.extend([
            "",
            "## Raw CSV missing columns",
            "",
            "`" + "`, `".join(missing_from_raw) + "`",
        ])
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out_json": _rel(OUT_JSON),
                "out_md": _rel(OUT_MD),
                "enriched_parquet": _rel(CONTRACT_ENRICHED_PARQUET),
                "enriched_normal_parquet": _rel(CONTRACT_ENRICHED_NORMAL_PARQUET),
                "enriched_columns": len(enriched_columns),
                "normal_rows": normal_parquet_info["rows"],
                "normal_columns": normal_parquet_info["columns"],
                "missing_builder_source_columns": a4["missing_builder_source_column_count"],
                "a4_high_ratio": a4["high_ratio"],
                "operational_verdict": payload["operational_verdict"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if a4_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
