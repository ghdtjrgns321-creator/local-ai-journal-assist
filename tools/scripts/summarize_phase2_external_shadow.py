"""Summarize DataSynth V7 PHASE2 and Tritscher external shadow evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _datasynth_vae_summary(artifact_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for year in (2022, 2023, 2024):
        path = artifact_dir / f"phase2_inference_v7_fixed3_year_{year}.json"
        payload = _load_json(path)
        unsupervised = payload["families"]["unsupervised"]
        rows.append(
            {
                "year": year,
                "documents": payload["documents"],
                "truth_docs": payload["truth"]["truth_docs"],
                "vae_auroc": unsupervised["informational_truth_join"]["auroc"],
                "high_q95_truth_count": unsupervised["informational_truth_join"][
                    "high_q95_truth_count"
                ],
                "high_q99_truth_count": unsupervised["informational_truth_join"][
                    "high_q99_truth_count"
                ],
            }
        )
    return {
        "source": "datasynth_manipulation_v7_fixed3",
        "rows": rows,
        "mean_vae_auroc": mean(item["vae_auroc"] for item in rows),
        "total_documents": sum(item["documents"] for item in rows),
        "total_truth_docs": sum(item["truth_docs"] for item in rows),
    }


def _tritscher_summary(external_dir: Path) -> dict[str, Any]:
    comparison = _load_json(external_dir / "tritscher_shadow_benchmark_comparison.json")
    vae = _load_json(external_dir / "tritscher_vae_shadow_benchmark_summary.json")
    return {
        "source": "tritscher_erp_fraud_external_simulation",
        "rows": vae["rows"],
        "documents": vae["documents"],
        "fraud_rows": vae["fraud_rows"],
        "positive_holdout_count": comparison["positive_holdout_count"],
        "mean_row_auroc_vae": comparison["means"]["vae_row_level_auroc"],
        "mean_document_auroc_vae": comparison["means"]["vae_document_level_auroc"],
        "mean_document_recall_at_100_vae": comparison["means"][
            "vae_document_level_recall_at_100"
        ],
        "mean_row_auroc_isolation_forest": comparison["means"]["iso_row_level_auroc"],
        "mean_document_auroc_isolation_forest": comparison["means"][
            "iso_document_level_auroc"
        ],
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    datasynth = payload["datasynth_v7_fixed3"]
    tritscher = payload["tritscher"]
    lines = [
        "# PHASE2 External Shadow Evidence Summary",
        "",
        f"- Created at: {payload['created_at']}",
        "- Scope: active unsupervised PHASE2 evidence only",
        "- Promotion impact: none",
        "",
        "## DataSynth V7 Fixed3 Reference",
        "",
        f"- Documents: {datasynth['total_documents']:,}",
        f"- Truth docs: {datasynth['total_truth_docs']:,}",
        f"- Mean VAE AUROC: {datasynth['mean_vae_auroc']:.4f}",
        "",
        "| year | documents | truth_docs | VAE AUROC | q95 truth rows | q99 truth rows |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in datasynth["rows"]:
        lines.append(
            f"| {row['year']} | {row['documents']:,} | {row['truth_docs']:,} | "
            f"{row['vae_auroc']:.4f} | {row['high_q95_truth_count']:,} | "
            f"{row['high_q99_truth_count']:,} |"
        )
    lines.extend(
        [
            "",
            "## Tritscher External Shadow",
            "",
            f"- Rows: {tritscher['rows']:,}",
            f"- Documents: {tritscher['documents']:,}",
            f"- Fraud rows: {tritscher['fraud_rows']:,}",
            f"- Positive holdouts: {tritscher['positive_holdout_count']}",
            f"- Mean row AUROC, VAE: {tritscher['mean_row_auroc_vae']:.4f}",
            f"- Mean document AUROC, VAE: {tritscher['mean_document_auroc_vae']:.4f}",
            f"- Mean document recall@100, VAE: "
            f"{tritscher['mean_document_recall_at_100_vae']:.4f}",
            "",
            "## Interpretation",
            "",
            "The external Tritscher result is directionally supportive for document-level "
            "unsupervised ranking, but it is weaker and more uneven than DataSynth V7 fixed3. "
            "That is the desired kind of evidence: it reduces DataSynth-only confidence while "
            "keeping the system honest about cross-simulation limits.",
            "",
            "Decision: keep PHASE2 active as unsupervised VAE/document-prioritized evidence. "
            "Do not activate supervised, transformer, sequence, or stacking from this result.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", default="artifacts")
    parser.add_argument(
        "--external-dir",
        default="artifacts/external_validation/tritscher_erp_fraud_20260519",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact_dir = Path(args.artifact_dir)
    external_dir = Path(args.external_dir)
    payload = {
        "created_at": _now_iso(),
        "datasynth_v7_fixed3": _datasynth_vae_summary(artifact_dir),
        "tritscher": _tritscher_summary(external_dir),
        "decision": "keep_unsupervised_active_keep_dormant_families_dormant",
    }
    output_json = external_dir / "phase2_external_shadow_summary.json"
    output_md = external_dir / "phase2_external_shadow_summary.md"
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(output_md, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
