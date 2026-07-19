"""Evaluate L2-04 on annual synthetic datasets and write a markdown report.

Run:
    .venv\Scripts\python.exe tools/scripts/eval_l204_synth.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_audit_rules, get_settings
from src.detection.fraud_rules_groupby import b11_expense_capitalization

DATA_DIR = PROJECT_ROOT / "tools" / "datasynth" / "out_v20"
OUTPUT_PATH = PROJECT_ROOT / "tests" / "phase1_rulebase" / "test-results" / "l2-04-synth-2022-2024.md"
YEARS = (2022, 2023, 2024)
FAMILY_LABELS = ("ExpenseCapitalization", "ImproperCapitalization")
STRICT_LABELS = ("ImproperCapitalization",)


@dataclass(frozen=True)
class Metric:
    tp_docs: int
    fp_docs: int
    fn_docs: int
    precision: float
    recall: float


def _safe_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("\r", " ").replace("\n", " ").strip()


def _metric(flagged_docs: set[str], label_docs: set[str]) -> Metric:
    tp_docs = len(flagged_docs & label_docs)
    fp_docs = len(flagged_docs - label_docs)
    fn_docs = len(label_docs - flagged_docs)
    precision = tp_docs / (tp_docs + fp_docs) if (tp_docs + fp_docs) > 0 else 0.0
    recall = tp_docs / len(label_docs) if label_docs else 0.0
    return Metric(tp_docs=tp_docs, fp_docs=fp_docs, fn_docs=fn_docs, precision=precision, recall=recall)


def _doc_label_set(df: pd.DataFrame, labels: tuple[str, ...]) -> set[str]:
    return set(df.loc[df["fraud_type"].isin(labels), "document_id"].dropna().unique())


def _doc_queue_counts(df: pd.DataFrame, annotations: dict[int, dict[str, object]]) -> dict[str, int]:
    per_doc: dict[str, str] = {}
    for row_idx, ann in annotations.items():
        document_id = str(df.at[row_idx, "document_id"])
        queue_label = str(ann.get("queue_label", "review"))
        existing = per_doc.get(document_id)
        if existing == "immediate":
            continue
        per_doc[document_id] = "immediate" if queue_label == "immediate" else "review"

    counts = {"immediate": 0, "review": 0}
    for queue_label in per_doc.values():
        counts[queue_label] += 1
    return counts


def _sample_doc_rows(
    df: pd.DataFrame,
    document_ids: list[str],
    annotations: dict[int, dict[str, object]],
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for document_id in document_ids:
        sub = df.loc[df["document_id"] == document_id]
        first = sub.iloc[0]
        annotation = {}
        for row_idx in sub.index:
            if int(row_idx) in annotations:
                annotation = annotations[int(row_idx)]
                break

        samples.append(
            {
                "document_id": document_id,
                "fraud_type": ", ".join(sorted(set(_safe_text(v) for v in sub["fraud_type"] if _safe_text(v)))) or "-",
                "document_type": ", ".join(sorted(set(_safe_text(v) for v in sub["document_type"] if _safe_text(v)))) or "-",
                "source": ", ".join(sorted(set(_safe_text(v) for v in sub["source"] if _safe_text(v)))) or "-",
                "business_process": ", ".join(sorted(set(_safe_text(v) for v in sub["business_process"] if _safe_text(v)))) or "-",
                "header_text": _safe_text(first.get("header_text", "")),
                "line_texts": " | ".join(_safe_text(v) for v in sub["line_text"].head(3).tolist() if _safe_text(v)) or "-",
                "reason_code": annotation.get("reason_code", "-"),
                "queue_label": annotation.get("queue_label", "-"),
                "confidence": annotation.get("confidence", "-"),
            }
        )
    return samples


def evaluate_year(year: int) -> dict[str, object]:
    path = DATA_DIR / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, low_memory=False)

    settings = get_settings()
    rules = get_audit_rules()
    flagged = b11_expense_capitalization(
        df,
        audit_rules=rules,
        amount_tolerance=settings.expense_capitalization_amount_tolerance,
        min_amount=settings.expense_capitalization_min_amount,
        review_threshold=settings.expense_capitalization_review_threshold,
        immediate_threshold=settings.expense_capitalization_immediate_threshold,
    )

    flagged_docs = set(df.loc[flagged, "document_id"].dropna().unique())
    family_docs = _doc_label_set(df, FAMILY_LABELS)
    strict_docs = _doc_label_set(df, STRICT_LABELS)
    annotations = flagged.attrs.get("row_annotations", {})

    fp_docs = sorted(flagged_docs - family_docs)
    fn_docs = sorted(family_docs - flagged_docs)

    return {
        "year": year,
        "rows": len(df),
        "flagged_docs": len(flagged_docs),
        "family_label_docs": len(family_docs),
        "strict_label_docs": len(strict_docs),
        "family_metric": _metric(flagged_docs, family_docs),
        "strict_metric": _metric(flagged_docs, strict_docs),
        "queue_counts": _doc_queue_counts(df, annotations),
        "breakdown": flagged.attrs.get("breakdown", {}),
        "fp_samples": _sample_doc_rows(df, fp_docs[:5], annotations),
        "fn_samples": _sample_doc_rows(df, fn_docs[:5], annotations),
    }


def render_report(results: list[dict[str, object]]) -> str:
    total_flagged = sum(int(item["flagged_docs"]) for item in results)
    total_family_labels = sum(int(item["family_label_docs"]) for item in results)
    total_strict_labels = sum(int(item["strict_label_docs"]) for item in results)

    family_tp = sum(int(item["family_metric"].tp_docs) for item in results)
    family_fp = sum(int(item["family_metric"].fp_docs) for item in results)
    family_fn = sum(int(item["family_metric"].fn_docs) for item in results)
    strict_tp = sum(int(item["strict_metric"].tp_docs) for item in results)
    strict_fp = sum(int(item["strict_metric"].fp_docs) for item in results)
    strict_fn = sum(int(item["strict_metric"].fn_docs) for item in results)

    family_precision = family_tp / (family_tp + family_fp) if (family_tp + family_fp) else 0.0
    family_recall = family_tp / total_family_labels if total_family_labels else 0.0
    strict_precision = strict_tp / (strict_tp + strict_fp) if (strict_tp + strict_fp) else 0.0
    strict_recall = strict_tp / total_strict_labels if total_strict_labels else 0.0

    lines = [
        "# L2-04 합성데이터 평가 (2022-2024)",
        "",
        "- 데이터: `tools/datasynth/out_v20/journal_entries_2022.csv`, `..._2023.csv`, `..._2024.csv`",
        "- 평가 대상 룰: `src/detection/fraud_rules_groupby.py::b11_expense_capitalization()`",
        "- 가족 라벨 기준: `ExpenseCapitalization + ImproperCapitalization`",
        "- 엄격 라벨 기준: 현재 프로젝트 매핑인 `ImproperCapitalization` 단독",
        "",
        "## 요약",
        "",
        f"- 가족 라벨 기준 전체: flagged {total_flagged} docs, label {total_family_labels} docs, TP {family_tp}, FP {family_fp}, FN {family_fn}, precision {family_precision:.1%}, recall {family_recall:.1%}",
        f"- 엄격 라벨 기준 전체: flagged {total_flagged} docs, label {total_strict_labels} docs, TP {strict_tp}, FP {strict_fp}, FN {strict_fn}, precision {strict_precision:.1%}, recall {strict_recall:.1%}",
        "- 해석: 현재 L2-04는 `비용 자산화 family`를 넓게 잡는 룰로는 성능이 좋지만, `ImproperCapitalization`만 정답으로 두면 의도적으로 넓게 잡는 특성 때문에 precision이 크게 낮아진다.",
        "",
        "## 연도별 결과",
        "",
        "| Year | Flagged Docs | Family Label Docs | TP | FP | FN | Precision | Recall | Immediate Docs | Review Docs |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for item in results:
        metric = item["family_metric"]
        queue = item["queue_counts"]
        lines.append(
            f"| {item['year']} | {item['flagged_docs']:,} | {item['family_label_docs']:,} | "
            f"{metric.tp_docs:,} | {metric.fp_docs:,} | {metric.fn_docs:,} | "
            f"{metric.precision:.1%} | {metric.recall:.1%} | {queue['immediate']:,} | {queue['review']:,} |"
        )

    lines.extend(
        [
            "",
            "## 엄격 라벨 기준 참고",
            "",
            "| Year | Strict Label Docs | TP | FP | FN | Precision | Recall |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for item in results:
        metric = item["strict_metric"]
        lines.append(
            f"| {item['year']} | {item['strict_label_docs']:,} | {metric.tp_docs:,} | "
            f"{metric.fp_docs:,} | {metric.fn_docs:,} | {metric.precision:.1%} | {metric.recall:.1%} |"
        )

    for item in results:
        breakdown = item["breakdown"]
        lines.extend(
            [
                "",
                f"## {item['year']} 샘플",
                "",
                f"- reason_counts: `{breakdown.get('reason_counts', {})}`",
                f"- immediate_rows: `{breakdown.get('immediate_rows', 0)}`, review_rows: `{breakdown.get('review_rows', 0)}`",
                "",
                "### FP 샘플",
                "",
                "| document_id | document_type | source | process | header_text | line_texts | reason | queue | confidence |",
                "|---|---|---|---|---|---|---|---|---:|",
            ]
        )
        for sample in item["fp_samples"]:
            lines.append(
                f"| {sample['document_id']} | {sample['document_type']} | {sample['source']} | "
                f"{sample['business_process']} | {sample['header_text']} | {sample['line_texts']} | "
                f"{sample['reason_code']} | {sample['queue_label']} | {sample['confidence']} |"
            )

        lines.extend(
            [
                "",
                "### FN 샘플",
                "",
                "| document_id | fraud_type | document_type | source | process | header_text | line_texts |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for sample in item["fn_samples"]:
            lines.append(
                f"| {sample['document_id']} | {sample['fraud_type']} | {sample['document_type']} | "
                f"{sample['source']} | {sample['business_process']} | {sample['header_text']} | {sample['line_texts']} |"
            )

    lines.extend(
        [
            "",
            "## 관찰",
            "",
            "- FP 샘플은 대부분 라벨이 비어 있는 정상 전표지만, `보증금 설정`, `선급비용 자산 계상`, `판관비 재분류`처럼 실제로 L2-04가 의심해야 할 계정 재분류 모양을 갖고 있다.",
            "- FN 샘플은 `AA/A2R`, `자본적 지출 프로젝트`, `건설중인자산` 같은 정상 자산화 맥락 문구가 강한 경우가 많다. 현재 구현이 실무 과탐을 줄이기 위해 이 맥락을 감점하기 때문에 일부 합성 라벨을 의도적으로 놓친다.",
            "- 따라서 L2-04는 합성 라벨의 `strict ImproperCapitalization` 적합도보다, `비용 자산화 family`를 넓게 포착하는 실무형 우선검토 룰로 해석하는 편이 맞다.",
        ]
    )

    return "\n".join(lines) + "\n"


def main() -> None:
    results = [evaluate_year(year) for year in YEARS]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render_report(results), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
