"""Feature-family ablation planning helpers for Phase 2.

Why: sparse optional families should not silently become default features.
     This script turns the feature-quality profile into a compact ablation
     plan/report so experiments can follow a consistent variant set.
"""

from __future__ import annotations

from pathlib import Path

REPORT_PATH = Path("tests/datasynth_quality_gate/results/feature_family_ablation_report.md")


def write_feature_family_report(profile: dict, output_path: Path = REPORT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    family_statuses = profile.get("family_statuses", {})
    ablation_plan = profile.get("ablation_plan", [])
    lines = [
        "# Feature Family Ablation Plan",
        "",
        f"- Persona normalized: **{profile.get('normalized_persona', False)}**",
        f"- Unknown persona count: **{int(profile.get('unknown_persona_count', 0)):,}**",
        f"- Sparse dropped columns: `{', '.join(profile.get('sparse_dropped_columns', [])) or '-'}`",
        "",
        "## Family Status",
        "",
        "| family | active | available_columns | dropped_columns |",
        "| --- | --- | --- | --- |",
    ]
    for family, status in family_statuses.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    family,
                    "yes" if status.get("active") else "no",
                    ", ".join(status.get("available_columns", [])) or "-",
                    ", ".join(status.get("dropped_columns", [])) or "-",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Ablation Variants",
            "",
            "| variant | include_families | description |",
            "| --- | --- | --- |",
        ]
    )
    for item in ablation_plan:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("variant", "-")),
                    ", ".join(item.get("include_families", [])) or "-",
                    str(item.get("description", "-")),
                ]
            )
            + " |"
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")
