from __future__ import annotations

from pathlib import Path

from tools.scripts.feature_family_ablation import write_feature_family_report


def test_write_feature_family_report():
    profile = {
        "normalized_persona": True,
        "unknown_persona_count": 7,
        "sparse_dropped_columns": ["cost_center"],
        "family_statuses": {
            "persona": {
                "active": True,
                "available_columns": ["user_persona"],
                "dropped_columns": [],
            },
            "cost_center": {
                "active": False,
                "available_columns": [],
                "dropped_columns": ["cost_center"],
            },
        },
        "ablation_plan": [
            {"variant": "baseline_core", "include_families": [], "description": "Core stable features only"},
            {"variant": "plus_persona", "include_families": ["persona"], "description": "Baseline + persona family"},
        ],
    }

    output_dir = Path("tests/.tmp_feature_family_ablation")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "feature_family_report.md"
    try:
        write_feature_family_report(profile, output)

        text = output.read_text(encoding="utf-8")
        assert "Feature Family Ablation Plan" in text
        assert "Unknown persona count: **7**" in text
        assert "| persona | yes | user_persona | - |" in text
        assert "| plus_persona | persona | Baseline + persona family |" in text
    finally:
        if output.exists():
            output.unlink()
        if output_dir.exists():
            output_dir.rmdir()
