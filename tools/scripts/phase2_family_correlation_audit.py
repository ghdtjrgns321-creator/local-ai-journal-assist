"""Measure PHASE2 5-family score correlations for V7 fixed3.

This script intentionally does not load truth labels. It recomputes row-level
family scores from the existing PHASE2 model bundle and rule-style detectors,
then aggregates scores to document max for correlation analysis.
"""

# ruff: noqa: E402

from __future__ import annotations

import io
import json
import pickle
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.settings import get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.relational_detector import RelationalDetector
from src.detection.timeseries_detector import TimeseriesDetector
from src.preprocessing.feature_quality import apply_feature_quality_policy
from src.preprocessing.vae_model import AuditVAE

PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"
BUNDLE_PATH = (
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
AUDIT_RULES_PATH = ROOT / "config" / "audit_rules.yaml"
OUT_JSON = ROOT / "artifacts" / "phase2_family_correlation_matrix_20260519.json"
OUT_MD = ROOT / "artifacts" / "phase2_family_correlation_matrix_20260519.md"

YEARS = (2022, 2023, 2024)
FAMILIES = ("unsupervised", "timeseries", "relational", "duplicate", "intercompany")
RULE_STYLE_FAMILIES = ("timeseries", "relational", "duplicate", "intercompany")
DATA_SOURCE = (
    "recomputed from artifacts/phase1_manipulation_v7_fixed3_case_input.pkl, "
    "data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/v1/model_bundle.pt, "
    "and PHASE2 rule-style detectors because artifacts/phase2_inference_v7_fixed3_year_*.json "
    "contains summary statistics but no row-level family scores"
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _json_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f


def _fmt(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "undefined"
    return f"{value:.4f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.4f}%"


def load_case_input() -> pd.DataFrame:
    with PKL_PATH.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    df["fiscal_year"] = df["fiscal_year"].astype(int)
    return df


def load_model_bundle() -> dict[str, Any]:
    with BUNDLE_PATH.open("rb") as fh:
        return pickle.load(fh)


def load_audit_rules() -> dict[str, Any]:
    with AUDIT_RULES_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def score_unsupervised(df: pd.DataFrame, bundle: dict[str, Any]) -> pd.Series:
    builder = bundle["matrix_builder"]
    post_scaler = bundle["post_scaler"]
    ecdf_train_sorted = bundle["ecdf_train_sorted"]

    cleaned_df, _, _ = apply_feature_quality_policy(df, for_training=False)
    matrix = builder.transform(cleaned_df)
    arr_raw = np.nan_to_num(
        matrix.to_numpy(dtype=np.float32),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    arr = post_scaler.transform(arr_raw).astype(np.float32)
    arr = np.clip(
        np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0),
        -10.0,
        10.0,
    ).astype(np.float32)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AuditVAE(bundle["input_dim"], bundle["latent_dim"], bundle["hidden_dim"]).to(device)
    state = torch.load(io.BytesIO(bundle["model_state_dict"]), weights_only=True)
    model.load_state_dict(state)
    model.eval()

    raw_chunks: list[np.ndarray] = []
    with torch.no_grad():
        tensor = torch.from_numpy(arr)
        for start in range(0, len(tensor), 2048):
            chunk = tensor[start : start + 2048].to(device)
            recon, _, _ = model(chunk)
            raw_chunks.append(((recon - chunk) ** 2).mean(dim=1).cpu().numpy())
    raw_scores = np.concatenate(raw_chunks, axis=0)
    ecdf_scores = np.searchsorted(ecdf_train_sorted, raw_scores) / max(len(ecdf_train_sorted), 1)
    return pd.Series(ecdf_scores, index=cleaned_df.index, name="unsupervised")


def _base_amount(df: pd.DataFrame) -> pd.Series:
    return df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)


def _fast_time_shifted_duplicate(df: pd.DataFrame, *, window_days: int = 7) -> pd.Series:
    scores = pd.Series(0.0, index=df.index)
    required = {"gl_account", "posting_date", "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        return scores

    work = pd.DataFrame(
        {
            "gl_account": df["gl_account"].astype(str),
            "posting_date": pd.to_datetime(df["posting_date"], errors="coerce"),
            "amount_bucket": _base_amount(df).round(0).astype("Int64"),
        },
        index=df.index,
    ).dropna(subset=["posting_date", "amount_bucket"])

    for (_gl, _amount), grp in work.groupby(["gl_account", "amount_bucket"], sort=False):
        if len(grp) < 2:
            continue
        ordered = grp.sort_values("posting_date", kind="mergesort")
        idx = ordered.index.to_list()
        dates = ordered["posting_date"].to_numpy()
        n = len(idx)
        for i in range(n):
            j = i + 1
            while j < n:
                day_diff = abs((dates[j] - dates[i]) / np.timedelta64(1, "D"))
                if day_diff > window_days:
                    break
                if day_diff != 0:
                    pair_score = 1.0 - (day_diff / window_days)
                    if pair_score > scores.at[idx[i]]:
                        scores.at[idx[i]] = pair_score
                    if pair_score > scores.at[idx[j]]:
                        scores.at[idx[j]] = pair_score
                j += 1
    return scores


def score_rule_family(
    family: str,
    df: pd.DataFrame,
    settings: Any,
    audit_rules: dict[str, Any],
) -> pd.Series:
    if family == "timeseries":
        detector = TimeseriesDetector(settings)
    elif family == "relational":
        detector = RelationalDetector(settings, audit_rules=audit_rules)
    elif family == "duplicate":
        import src.detection.duplicate_detector as duplicate_detector_module

        duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
        detector = DuplicateDetector(settings)
    elif family == "intercompany":
        detector = IntercompanyMatcher(settings, audit_rules=audit_rules)
    else:
        raise ValueError(f"unknown family: {family}")
    result = detector.detect(df)
    return result.scores.reindex(df.index).fillna(0.0).astype(float).rename(family)


def score_all_families(df: pd.DataFrame) -> pd.DataFrame:
    bundle = load_model_bundle()
    settings = get_settings()
    audit_rules = load_audit_rules()
    pieces = [
        df[["document_id", "fiscal_year"]].copy(),
        score_unsupervised(df, bundle).reindex(df.index).fillna(0.0),
    ]
    for family in RULE_STYLE_FAMILIES:
        _print(f"scoring {family}")
        pieces.append(score_rule_family(family, df, settings, audit_rules))
    row_scores = pd.concat(pieces, axis=1)
    for family in FAMILIES:
        row_scores[family] = row_scores[family].fillna(0.0).astype(float)
    return row_scores


def doc_max_scores(row_scores: pd.DataFrame) -> pd.DataFrame:
    return (
        row_scores.groupby(["fiscal_year", "document_id"], as_index=False)[list(FAMILIES)]
        .max()
        .sort_values(["fiscal_year", "document_id"], kind="mergesort")
        .reset_index(drop=True)
    )


def dead_rankers(frame: pd.DataFrame) -> set[str]:
    dead: set[str] = set()
    for family in FAMILIES:
        values = frame[family].fillna(0.0).to_numpy(dtype=float)
        if len(values) == 0 or np.all(values == 0.0):
            dead.add(family)
    return dead


def corr_matrix(
    frame: pd.DataFrame,
    method: str,
    dead: set[str],
) -> dict[str, dict[str, float | None]]:
    active = [family for family in FAMILIES if family not in dead]
    corr = frame[active].corr(method=method) if active else pd.DataFrame()
    out: dict[str, dict[str, float | None]] = {}
    for left in FAMILIES:
        out[left] = {}
        for right in FAMILIES:
            if left in dead or right in dead:
                out[left][right] = None
            elif left == right:
                out[left][right] = 1.0
            else:
                out[left][right] = _json_float(corr.loc[left, right])
    return out


def quantile_stats(series: pd.Series) -> dict[str, float]:
    clean = series.fillna(0.0).astype(float)
    return {
        "q50": float(clean.quantile(0.50)),
        "q90": float(clean.quantile(0.90)),
        "q95": float(clean.quantile(0.95)),
        "q99": float(clean.quantile(0.99)),
    }


def family_meta(
    row_scores: pd.DataFrame,
    doc_scores: pd.DataFrame,
    dead: set[str],
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    row_count = len(row_scores)
    for family in FAMILIES:
        row_nonzero = int((row_scores[family].fillna(0.0) > 0).sum())
        doc_nonzero = int((doc_scores[family].fillna(0.0) > 0).sum())
        meta[family] = {
            "row_nonzero_rate": float(row_nonzero / max(row_count, 1)),
            "row_nonzero_count": row_nonzero,
            "doc_nonzero_count": doc_nonzero,
            "quantiles": quantile_stats(row_scores[family]),
            "is_dead_ranker": family in dead,
            "is_near_dormant_ranker": (
                family not in dead and row_nonzero / max(row_count, 1) < 0.001
            ),
        }
    return meta


def jaccard_matrix(
    frame: pd.DataFrame,
    *,
    q: float,
    dead: set[str],
) -> dict[str, dict[str, float | None]]:
    thresholds = {
        family: float(frame[family].fillna(0.0).quantile(q))
        for family in FAMILIES
        if family not in dead
    }
    masks = {
        family: frame[family].fillna(0.0) >= thresholds[family]
        for family in FAMILIES
        if family not in dead
    }
    out: dict[str, dict[str, float | None]] = {}
    for left in FAMILIES:
        out[left] = {}
        for right in FAMILIES:
            if left in dead or right in dead:
                out[left][right] = None
                continue
            union = int((masks[left] | masks[right]).sum())
            intersection = int((masks[left] & masks[right]).sum())
            out[left][right] = float(intersection / union) if union else None
    return out


def upper_triangle_values(
    matrix: dict[str, dict[str, float | None]],
    dead: set[str],
) -> list[float]:
    values: list[float] = []
    active = [family for family in FAMILIES if family not in dead]
    for i, left in enumerate(active):
        for right in active[i + 1 :]:
            value = matrix[left][right]
            if value is not None:
                values.append(abs(float(value)))
    return values


def markdown_table(matrix: dict[str, dict[str, float | None]]) -> str:
    lines = [
        "| family | " + " | ".join(FAMILIES) + " |",
        "|---|" + "|".join("---:" for _ in FAMILIES) + "|",
    ]
    for family in FAMILIES:
        cells = [_fmt(matrix[family][other]) for other in FAMILIES]
        lines.append(f"| {family} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def family_status_table(meta: dict[str, Any]) -> str:
    lines = [
        "| family | row nonzero | doc nonzero | q50 | q90 | q95 | q99 | status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for family in FAMILIES:
        item = meta[family]
        quantiles = item["quantiles"]
        if item["is_dead_ranker"]:
            status = "dead ranker"
        elif item["is_near_dormant_ranker"]:
            status = "near-dormant"
        else:
            status = "active"
        lines.append(
            f"| {family} | {_fmt_pct(item['row_nonzero_rate'])} "
            f"({item['row_nonzero_count']:,}) | {item['doc_nonzero_count']:,} | "
            f"{quantiles['q50']:.4f} | {quantiles['q90']:.4f} | "
            f"{quantiles['q95']:.4f} | {quantiles['q99']:.4f} | {status} |"
        )
    return "\n".join(lines)


def policy_judgment(max_corr: float) -> str:
    if max_corr < 0.3:
        return "(a) 모두 |ρ|<0.3 → 5-way RRF 그대로"
    if max_corr <= 0.6:
        return "(b) 0.3 ≤ |ρ| ≤ 0.6 → 5-way RRF 사용 가능, gain 제한"
    return "(c) |ρ|>0.6 다수 → PHASE2 내부 mean-of-ranks 사전 fusion 후 2-way RRF"


def build_markdown(payload: dict[str, Any]) -> str:
    spearman = payload["spearman_doc_max"]
    pearson = payload["pearson_doc_max"]
    dead = {
        family
        for family, meta in payload["family_meta"].items()
        if bool(meta["is_dead_ranker"])
    }
    near_dormant = {
        family
        for family, meta in payload["family_meta"].items()
        if bool(meta.get("is_near_dormant_ranker"))
    }
    values = upper_triangle_values(spearman, dead)
    avg_corr = float(np.mean(values)) if values else 0.0
    max_corr = float(np.max(values)) if values else 0.0
    judgment = policy_judgment(max_corr)
    dormant_note = (
        f"near-dormant family({', '.join(sorted(near_dormant))})는 "
        "운영 해석에서 별도 주석이 필요하다"
        if near_dormant
        else "dead/near-dormant family는 없다"
    )
    conclusion = (
        f"활성 family 기준 최대 Spearman |ρ|={max_corr:.4f}, 평균 |ρ|={avg_corr:.4f}로 "
        f"{judgment}; {dormant_note}."
    )
    payload["one_line_conclusion"] = conclusion

    lines = [
        "# PHASE2 5-family score correlation matrix",
        "",
        "## 0. 한 줄 결론 — RRF 5-way 적합 여부 1 sentence judgment",
        "",
        conclusion,
        "",
        "## 1. 측정 환경 (데이터 출처, row/doc 수, family 활성 상태)",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- data_source: `{payload['data_source']}`",
        f"- row_count: `{payload['row_count']:,}`",
        f"- document_count: `{payload['document_count']:,}`",
        "- truth label used: `false`",
        "",
        family_status_table(payload["family_meta"]),
        "",
        "## 2. Spearman 5×5 (3년 통합) — 표 형식",
        "",
        markdown_table(spearman),
        "",
        "## 3. Pearson 5×5 (보조) — 표",
        "",
        markdown_table(pearson),
        "",
        "## 4. 연도별 Spearman 표 3개",
        "",
    ]
    for year in YEARS:
        lines.extend(
            [
                f"### {year}",
                "",
                markdown_table(payload["spearman_by_year"][str(year)]),
                "",
            ]
        )
    lines.extend(
        [
            "## 5. q95/q99 Jaccard 5×5",
            "",
            "### q95",
            "",
            markdown_table(payload["top_quantile_jaccard"]["q95"]),
            "",
            "### q99",
            "",
            markdown_table(payload["top_quantile_jaccard"]["q99"]),
            "",
            "## 6. 해석",
            "",
            f"- 활성 family간 평균 Spearman |ρ|: `{avg_corr:.4f}`",
            f"- 활성 family간 최대 Spearman |ρ|: `{max_corr:.4f}`",
            f"- dead ranker: `{', '.join(sorted(dead)) if dead else 'none'}`",
            (
                "- near-dormant ranker: "
                f"`{', '.join(sorted(near_dormant)) if near_dormant else 'none'}`"
            ),
            f"- RRF 5-way 정책 권고: `{judgment}`",
            "",
            "## 7. fitting 가드 체크리스트 (truth 미사용 확증)",
            "",
            "- truth label file loaded: `false`",
            "- thresholds tuned with truth: `false`",
            "- q95/q99 thresholds: fixed distribution quantiles only",
            "- PHASE1 case_builder / score_aggregator / queue_fusion / RRF code changed: `false`",
            "- model_bundle.pt retrained: `false`",
            "",
            "## 8. 다음 단계 — RRF 정책 결정 입력",
            "",
            "본 산출물은 PHASE2 내부 family ranker 독립성 판단 입력이다. "
            "정책 코드 변경이나 family 가중치 조정은 수행하지 않았다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    start = time.perf_counter()
    _print("loading input")
    df = load_case_input()
    _print(f"rows={len(df):,} docs={df['document_id'].nunique():,}")
    row_scores = score_all_families(df)
    doc_scores = doc_max_scores(row_scores)
    dead = dead_rankers(doc_scores)
    row_count = len(row_scores)
    near_dormant = [
        family
        for family in FAMILIES
        if family not in dead
        and int((row_scores[family].fillna(0.0) > 0).sum()) / max(row_count, 1) < 0.001
    ]
    anomalies = [f"{family} dead ranker" for family in sorted(dead)]
    anomalies.extend(
        (
            f"{family} near-dormant ranker "
            f"(row_nonzero_count={int((row_scores[family].fillna(0.0) > 0).sum())}, "
            "row_nonzero_rate="
            f"{int((row_scores[family].fillna(0.0) > 0).sum()) / max(row_count, 1):.8f})"
        )
        for family in sorted(near_dormant)
    )

    spearman = corr_matrix(doc_scores, "spearman", dead)
    pearson = corr_matrix(doc_scores, "pearson", dead)
    spearman_by_year = {
        str(year): corr_matrix(doc_scores.loc[doc_scores["fiscal_year"] == year], "spearman", dead)
        for year in YEARS
    }

    payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "data_source": DATA_SOURCE,
        "row_count": int(len(row_scores)),
        "document_count": int(doc_scores["document_id"].nunique()),
        "family_meta": family_meta(row_scores, doc_scores, dead),
        "spearman_doc_max": spearman,
        "pearson_doc_max": pearson,
        "spearman_by_year": spearman_by_year,
        "top_quantile_jaccard": {
            "q95": jaccard_matrix(row_scores, q=0.95, dead=dead),
            "q99": jaccard_matrix(row_scores, q=0.99, dead=dead),
        },
        "anomalies": anomalies,
        "fitting_guard": {
            "truth_label_used": False,
            "thresholds_tuned_with_truth": False,
        },
    }
    md = build_markdown(payload)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    _print(f"wrote {OUT_MD.relative_to(ROOT)}")
    _print(f"done elapsed={time.perf_counter() - start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
