"""D062 PHASE2 / PHASE1+2 통합 3등급 분류 분포 측정.

옵션 B 측정: Stage7 cache/parquet 위에서 새 review_band 컬럼 분포를 산출한다.
전체 재추론이 아닌 wiring 검증이 목적이다.

측정 항목 (D062 사용자 요청, 2026-05-21):
1. phase2_review_band 분포
2. phase12_review_band 분포
3. phase2_review_band 별 max_evidence_tier 분포
4. phase2_review_band 별 coverage_breadth_q95 분포
5. phase2_review_band 별 max_family_ecdf 요약 (min/median/max)
6. phase12_review_band 별 P1/P2 band 교차표
7. none/candidate/review/immediate 각각 top family 분포

Stage7 측정 한계 (반드시 결과에 명시):
    Stage7 측정은 family_top_subdetectors_by_case 가 비어 있어 max_evidence_tier 가
    None 일 수 있다. 따라서 PHASE2 strong/moderate 기반 immediate/review 는 실제 운영보다
    과소 측정된다. 본 측정은 ECDF/coverage 기반 경로와 통합 band 컬럼 wiring 검증용이다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

BANDS = ("immediate", "review", "candidate", "none")


def _band_counter(series: pd.Series) -> dict[str, int]:
    counter: Counter = Counter()
    for value in series.fillna("none").astype(str):
        counter[value] = counter.get(value, 0) + 1
    return {band: counter.get(band, 0) for band in BANDS}


def _facet_by_band(
    df: pd.DataFrame,
    band_col: str,
    facet_col: str,
    is_numeric: bool = False,
) -> dict[str, Any]:
    if facet_col not in df.columns or band_col not in df.columns:
        return {"warning": f"missing column: {band_col} or {facet_col}"}
    result: dict[str, Any] = {}
    for band in BANDS:
        sub = df[df[band_col].astype(str) == band]
        if sub.empty:
            result[band] = {"count": 0}
            continue
        if is_numeric:
            values = pd.to_numeric(sub[facet_col], errors="coerce").dropna()
            if values.empty:
                result[band] = {"count": int(len(sub)), "non_null": 0}
            else:
                result[band] = {
                    "count": int(len(sub)),
                    "non_null": int(len(values)),
                    "min": float(values.min()),
                    "median": float(values.median()),
                    "max": float(values.max()),
                    "mean": float(values.mean()),
                }
        else:
            sub_counter: Counter = Counter()
            for value in sub[facet_col].fillna("<none>").astype(str):
                sub_counter[value] = sub_counter.get(value, 0) + 1
            result[band] = dict(sub_counter)
    return result


def _crosstab_phase12(df: pd.DataFrame) -> dict[str, Any]:
    if "phase1_review_band" not in df.columns or "phase2_review_band" not in df.columns:
        return {"warning": "missing phase1_review_band or phase2_review_band column"}
    if "phase12_review_band" not in df.columns:
        return {"warning": "missing phase12_review_band column"}
    table: dict[str, dict[str, int]] = {}
    for p12 in BANDS:
        sub = df[df["phase12_review_band"].astype(str) == p12]
        cross: dict[str, int] = {}
        for p1 in BANDS:
            for p2 in BANDS:
                count = int(
                    len(
                        sub[
                            (sub["phase1_review_band"].astype(str) == p1)
                            & (sub["phase2_review_band"].astype(str) == p2)
                        ]
                    )
                )
                if count:
                    cross[f"P1={p1} / P2={p2}"] = count
        table[p12] = cross
    return table


def _top_family_by_band(df: pd.DataFrame, band_col: str) -> dict[str, dict[str, int]]:
    """band 별 top_family 컬럼 (overlay) 분포. top_family 가 없으면 None."""

    if "top_family" not in df.columns:
        return {"warning": "top_family column not present in this parquet"}
    result: dict[str, dict[str, int]] = {}
    for band in BANDS:
        sub = df[df[band_col].astype(str) == band]
        counter: Counter = Counter()
        for value in sub["top_family"].fillna("<none>").astype(str):
            counter[value] = counter.get(value, 0) + 1
        result[band] = dict(counter)
    return result


def _audit(parquet_path: Path) -> dict[str, Any]:
    df = pd.read_parquet(parquet_path)
    report: dict[str, Any] = {
        "artifact": str(parquet_path),
        "total_cases": int(len(df)),
        "columns_present": list(df.columns),
        "phase2_review_band_distribution": _band_counter(
            df.get("phase2_review_band", pd.Series(dtype=str))
        ),
        "phase12_review_band_distribution": _band_counter(
            df.get("phase12_review_band", pd.Series(dtype=str))
        ),
        "phase1_review_band_distribution": _band_counter(
            df.get("phase1_review_band", pd.Series(dtype=str))
        ),
    }

    # Wiring check — 필수 컬럼이 비어있지 않은지
    wiring: dict[str, Any] = {}
    for col in (
        "phase1_review_band",
        "phase2_review_band",
        "phase12_review_band",
    ):
        if col in df.columns:
            non_null = int(df[col].astype(str).ne("").sum())
            wiring[col] = {"present": True, "non_null": non_null}
        else:
            wiring[col] = {"present": False}
    report["wiring_check"] = wiring

    # Facet 분석은 base_df / overlay 컬럼이 있을 때만
    if "max_evidence_tier" in df.columns:
        report["phase2_band_x_max_evidence_tier"] = _facet_by_band(
            df, "phase2_review_band", "max_evidence_tier"
        )
    if "coverage_breadth_q95" in df.columns:
        report["phase2_band_x_coverage_breadth"] = _facet_by_band(
            df, "phase2_review_band", "coverage_breadth_q95", is_numeric=True
        )
    if "max_family_ecdf" in df.columns:
        report["phase2_band_x_max_family_ecdf"] = _facet_by_band(
            df, "phase2_review_band", "max_family_ecdf", is_numeric=True
        )

    report["phase12_crosstab"] = _crosstab_phase12(df)
    report["phase2_band_x_top_family"] = _top_family_by_band(df, "phase2_review_band")

    return report


def _format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"## PHASE2 review_band 분포 측정 — `{report['artifact']}`")
    lines.append("")
    lines.append(f"- total cases: {report['total_cases']}")
    lines.append("")
    lines.append(
        "> **Stage7 측정 한계 (D062, 2026-05-21)**: family_top_subdetectors_by_case 가 "
        "비어 있어 max_evidence_tier 가 None 일 수 있다. PHASE2 strong/moderate 기반 "
        "immediate/review 는 실제 운영보다 과소 측정된다. 본 측정은 ECDF/coverage 기반 "
        "경로와 통합 band 컬럼 wiring 검증용이며 운영 count 확정이 아니다."
    )
    lines.append("")

    lines.append("### Wiring 체크 — 컬럼 존재/채움")
    lines.append("")
    lines.append("| Column | Present | Non-empty count |")
    lines.append("|--------|---------|-----------------|")
    for col, info in report["wiring_check"].items():
        present = "✓" if info.get("present") else "✗"
        non_null = info.get("non_null", "—")
        lines.append(f"| {col} | {present} | {non_null} |")
    lines.append("")

    lines.append("### 1. phase2_review_band 분포")
    lines.append("")
    lines.append("| Band | Count |")
    lines.append("|------|-------|")
    for band, count in report["phase2_review_band_distribution"].items():
        lines.append(f"| {band} | {count} |")
    lines.append("")

    lines.append("### 2. phase12_review_band 분포")
    lines.append("")
    lines.append("| Band | Count |")
    lines.append("|------|-------|")
    for band, count in report["phase12_review_band_distribution"].items():
        lines.append(f"| {band} | {count} |")
    lines.append("")

    lines.append("### phase1_review_band 분포 (reference)")
    lines.append("")
    lines.append("| Band | Count |")
    lines.append("|------|-------|")
    for band, count in report["phase1_review_band_distribution"].items():
        lines.append(f"| {band} | {count} |")
    lines.append("")

    if "phase2_band_x_max_evidence_tier" in report:
        lines.append("### 3. phase2_review_band 별 max_evidence_tier 분포")
        lines.append("")
        for band, dist in report["phase2_band_x_max_evidence_tier"].items():
            lines.append(
                f"**{band}** (cases: {dist.get('count', sum(v for k, v in dist.items() if isinstance(v, int)))})"
            )
            lines.append("")
            for tier, count in dist.items():
                if tier == "count":
                    continue
                lines.append(f"- {tier}: {count}")
            lines.append("")

    if "phase2_band_x_coverage_breadth" in report:
        lines.append("### 4. phase2_review_band 별 coverage_breadth_q95 요약")
        lines.append("")
        lines.append("| Band | count | non_null | min | median | mean | max |")
        lines.append("|------|-------|----------|-----|--------|------|-----|")
        for band, summary in report["phase2_band_x_coverage_breadth"].items():
            count = summary.get("count", 0)
            non_null = summary.get("non_null", "—")
            mn = summary.get("min", "—")
            med = summary.get("median", "—")
            mean = summary.get("mean", "—")
            mx = summary.get("max", "—")
            lines.append(f"| {band} | {count} | {non_null} | {mn} | {med} | {mean} | {mx} |")
        lines.append("")

    if "phase2_band_x_max_family_ecdf" in report:
        lines.append("### 5. phase2_review_band 별 max_family_ecdf 요약")
        lines.append("")
        lines.append("| Band | count | non_null | min | median | mean | max |")
        lines.append("|------|-------|----------|-----|--------|------|-----|")
        for band, summary in report["phase2_band_x_max_family_ecdf"].items():
            count = summary.get("count", 0)
            non_null = summary.get("non_null", "—")
            mn = summary.get("min", "—")
            med = summary.get("median", "—")
            mean = summary.get("mean", "—")
            mx = summary.get("max", "—")
            lines.append(f"| {band} | {count} | {non_null} | {mn} | {med} | {mean} | {mx} |")
        lines.append("")

    lines.append("### 6. phase12_review_band 별 P1/P2 교차표")
    lines.append("")
    crosstab = report.get("phase12_crosstab") or {}
    if isinstance(crosstab, dict) and "warning" not in crosstab:
        for p12_band, cross in crosstab.items():
            lines.append(f"**phase12 = {p12_band}**")
            lines.append("")
            if not cross:
                lines.append("- (empty)")
            else:
                for combo, count in cross.items():
                    lines.append(f"- {combo}: {count}")
            lines.append("")
    else:
        lines.append(f"(skipped: {crosstab})")
        lines.append("")

    lines.append("### 7. phase2_review_band 별 top_family 분포")
    lines.append("")
    top_family = report.get("phase2_band_x_top_family") or {}
    if isinstance(top_family, dict) and "warning" not in top_family:
        for band, dist in top_family.items():
            lines.append(f"**{band}**")
            lines.append("")
            if not dist:
                lines.append("- (empty)")
            else:
                for family, count in sorted(dist.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"- {family}: {count}")
            lines.append("")
    else:
        lines.append(f"(skipped: {top_family})")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True, help="queue parquet 경로")
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact.exists():
        print(f"error: artifact not found: {args.artifact}", file=sys.stderr)
        return 2

    report = _audit(args.artifact)
    md = _format_markdown(report)
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md + "\n", encoding="utf-8")
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
