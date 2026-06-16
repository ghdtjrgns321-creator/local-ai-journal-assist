"""Compare V7 fixed3 vs fixed4 PHASE2 by-year inference artifacts."""
# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"
OUT_MD = ARTIFACTS / "phase2_v7_fixed3_vs_fixed4_comparison.md"
OUT_JSON = ARTIFACTS / "phase2_v7_fixed3_vs_fixed4_comparison.json"

YEARS = (2022, 2023, 2024)
FAMILIES = ("unsupervised", "timeseries", "relational", "duplicate", "intercompany")
IC_SUBS = ("IC01", "IC02", "IC03")
SCENARIO = "circular_related_party_transaction"


def load(prefix: str, year: int) -> dict[str, Any]:
    path = ARTIFACTS / f"{prefix}_year_{year}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def delta(new: int | float, old: int | float) -> int | float:
    return new - old


def family_nonzero(payload: dict[str, Any], family: str) -> int:
    family_payload = payload["families"][family]
    if "score_distribution" in family_payload:
        return int(family_payload["score_distribution"]["nonzero_count"])
    if family == "unsupervised":
        return int(family_payload["high_count_q95"])
    return 0


def main() -> int:
    payload: dict[str, Any] = {
        "source": {
            "fixed3_doc": "docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md",
            "fixed4_doc": "docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2.md",
            "fixed3_prefix": "phase2_inference_v7_fixed3",
            "fixed4_prefix": "phase2_inference_v7_fixed4",
        },
        "years": {},
        "totals": {
            "rows_fixed3": 0,
            "rows_fixed4": 0,
            "docs_fixed3": 0,
            "docs_fixed4": 0,
            "family_nonzero": {
                family: {"fixed3": 0, "fixed4": 0, "delta": 0}
                for family in FAMILIES
            },
            "ic_subdetectors": {
                sub: {"fixed3": 0, "fixed4": 0, "delta": 0}
                for sub in IC_SUBS
            },
        },
    }

    for year in YEARS:
        old = load("phase2_inference_v7_fixed3", year)
        new = load("phase2_inference_v7_fixed4", year)
        year_row: dict[str, Any] = {
            "rows": {
                "fixed3": old["rows"],
                "fixed4": new["rows"],
                "delta": delta(new["rows"], old["rows"]),
            },
            "documents": {
                "fixed3": old["documents"],
                "fixed4": new["documents"],
                "delta": delta(new["documents"], old["documents"]),
            },
            "family_nonzero": {},
            "ic_subdetectors": {},
            "circular_related_party_transaction": {},
        }
        payload["totals"]["rows_fixed3"] += old["rows"]
        payload["totals"]["rows_fixed4"] += new["rows"]
        payload["totals"]["docs_fixed3"] += old["documents"]
        payload["totals"]["docs_fixed4"] += new["documents"]

        for family in FAMILIES:
            old_nonzero = family_nonzero(old, family)
            new_nonzero = family_nonzero(new, family)
            year_row["family_nonzero"][family] = {
                "fixed3": old_nonzero,
                "fixed4": new_nonzero,
                "delta": delta(new_nonzero, old_nonzero),
            }
            total = payload["totals"]["family_nonzero"][family]
            total["fixed3"] += old_nonzero
            total["fixed4"] += new_nonzero
            total["delta"] += new_nonzero - old_nonzero

        for sub in IC_SUBS:
            old_hit = old["families"]["intercompany"]["sub_detectors"][sub]["hit_count"]
            new_hit = new["families"]["intercompany"]["sub_detectors"][sub]["hit_count"]
            year_row["ic_subdetectors"][sub] = {
                "fixed3": old_hit,
                "fixed4": new_hit,
                "delta": delta(new_hit, old_hit),
            }
            total = payload["totals"]["ic_subdetectors"][sub]
            total["fixed3"] += old_hit
            total["fixed4"] += new_hit
            total["delta"] += new_hit - old_hit

        old_s = old["scenario_family_matrix"][SCENARIO]["intercompany"]
        new_s = new["scenario_family_matrix"][SCENARIO]["intercompany"]
        year_row["circular_related_party_transaction"] = {
            "truth_docs": new["scenario_family_matrix"][SCENARIO]["truth_docs"],
            "fixed3_detected_docs": old_s["detected_docs"],
            "fixed3_detection_rate": old_s["detection_rate"],
            "fixed4_detected_docs": new_s["detected_docs"],
            "fixed4_detection_rate": new_s["detection_rate"],
            "delta_detected_docs": new_s["detected_docs"] - old_s["detected_docs"],
        }
        payload["years"][str(year)] = year_row

    payload["totals"]["rows_delta"] = (
        payload["totals"]["rows_fixed4"] - payload["totals"]["rows_fixed3"]
    )
    payload["totals"]["docs_delta"] = (
        payload["totals"]["docs_fixed4"] - payload["totals"]["docs_fixed3"]
    )

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_markdown(payload), encoding="utf-8")
    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_JSON}")
    return 0


def render_markdown(payload: dict[str, Any]) -> str:
    ic_total = payload["totals"]["family_nonzero"]["intercompany"]
    ic02_total = payload["totals"]["ic_subdetectors"]["IC02"]
    fixed3_circular = sum(
        row["circular_related_party_transaction"]["fixed3_detected_docs"]
        for row in payload["years"].values()
    )
    fixed4_circular = sum(
        row["circular_related_party_transaction"]["fixed4_detected_docs"]
        for row in payload["years"].values()
    )
    truth_circular = sum(
        row["circular_related_party_transaction"]["truth_docs"]
        for row in payload["years"].values()
    )
    lines: list[str] = [
        "# V7 fixed3 vs fixed4 PHASE2 비교",
        "",
        "## 결론",
        "",
        "fixed4는 DataSynth main `journal_entries.csv`에 IC seller/buyer 전표를 포함한 재생성본이다. "
        "그 결과 PHASE2 `intercompany` family가 fixed3의 0건 상태에서 IC01 unmatched reference와 IC02 금액 불일치까지 산출하는 상태로 회복됐다.",
        "",
        "기존 fixed3 문서: `docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md`",
        "fixed4 문서: `docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2.md`",
        "",
        "## 전체 크기 변화",
        "",
        "| 항목 | fixed3 | fixed4 | delta |",
        "|---|---:|---:|---:|",
        f"| rows | {payload['totals']['rows_fixed3']:,} | {payload['totals']['rows_fixed4']:,} | {payload['totals']['rows_delta']:+,} |",
        f"| documents | {payload['totals']['docs_fixed3']:,} | {payload['totals']['docs_fixed4']:,} | {payload['totals']['docs_delta']:+,} |",
        "",
        "## Family nonzero rows 합계",
        "",
        "| family | fixed3 | fixed4 | delta |",
        "|---|---:|---:|---:|",
    ]
    for family, row in payload["totals"]["family_nonzero"].items():
        lines.append(
            f"| {family} | {row['fixed3']:,} | {row['fixed4']:,} | {row['delta']:+,} |"
        )
    lines.extend([
        "",
        "## Intercompany sub-detector 합계",
        "",
        "| sub-detector | fixed3 | fixed4 | delta |",
        "|---|---:|---:|---:|",
    ])
    for sub, row in payload["totals"]["ic_subdetectors"].items():
        lines.append(
            f"| {sub} | {row['fixed3']:,} | {row['fixed4']:,} | {row['delta']:+,} |"
        )
    lines.extend([
        "",
        "## 연도별 intercompany family",
        "",
        "| year | rows delta | docs delta | intercompany fixed3 | intercompany fixed4 | IC01 delta | IC02 delta | IC03 delta | circular IC fixed3 | circular IC fixed4 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for year, row in payload["years"].items():
        ic = row["family_nonzero"]["intercompany"]
        subs = row["ic_subdetectors"]
        circ = row["circular_related_party_transaction"]
        lines.append(
            "| "
            f"{year} | {row['rows']['delta']:+,} | {row['documents']['delta']:+,} | "
            f"{ic['fixed3']:,} | {ic['fixed4']:,} | "
            f"{subs['IC01']['delta']:+,} | {subs['IC02']['delta']:+,} | {subs['IC03']['delta']:+,} | "
            f"{circ['fixed3_detected_docs']}/{circ['truth_docs']} ({pct(circ['fixed3_detection_rate'])}) | "
            f"{circ['fixed4_detected_docs']}/{circ['truth_docs']} ({pct(circ['fixed4_detection_rate'])}) |"
        )
    lines.extend([
        "",
        "## 해석",
        "",
        "- fixed4의 row/document 증가는 IC sidecar 전표가 main ledger에 들어오면서 생긴 구조적 변화다.",
        f"- `intercompany` family nonzero rows는 fixed3 합계 {ic_total['fixed3']:,}건에서 fixed4 합계 {ic_total['fixed4']:,}건으로 증가했다.",
        f"- IC02는 fixed3 {ic02_total['fixed3']:,}건에서 fixed4 {ic02_total['fixed4']:,}건으로 회복됐다. 이는 seller/buyer pair가 같은 main ledger와 같은 IC reference를 공유하게 된 효과다.",
        "- IC03은 여전히 0건이다. 현재 IC pair의 posting date가 대부분 같은 날이어서 timing gap 조건을 만족하지 않는 것으로 해석된다.",
        f"- circular related-party truth의 intercompany family 포착은 fixed3 {fixed3_circular}/{truth_circular}에서 fixed4 {fixed4_circular}/{truth_circular}로 회복됐다.",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
