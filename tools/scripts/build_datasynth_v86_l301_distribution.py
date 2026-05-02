"""Build v86 candidate by making L3-01 distribution less P2P-heavy.

v85 fixed the L3-01 truth contract, but most hits were P2P documents using
revenue accounts. This patch changes the journal fields, not only labels:

- reduce repeated P2P/revenue account hits by replacing selected denied accounts
  with valid P2P-compatible accounts;
- add valid-CoA process/account mismatch candidates to O2C, H2R, TRE, and A2R;
- rebuild L3-01 rule truth from the detector contract.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.integrity_layer import IntegrityDetector  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v85_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v86_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-01"

TARGET_DOCS = {
    "P2P": 1050,
    "O2C": 520,
    "H2R": 380,
    "TRE": 300,
    "A2R": 160,
}

DENIED_ACCOUNTS = {
    "O2C": [
        "500000",
        "500060",
        "500070",
        "500120",
        "500150",
        "500160",
        "500230",
        "500270",
        "500380",
        "500410",
        "500480",
        "500500",
        "500590",
        "500600",
        "500670",
        "500680",
        "500720",
        "500830",
        "500920",
        "500960",
        "6800",
    ],
    "P2P": [
        "400030",
        "400100",
        "400170",
        "400210",
        "400270",
        "400380",
        "400410",
        "400520",
        "400650",
        "400660",
        "400700",
        "400710",
        "400780",
        "4100",
    ],
    "H2R": ["400030", "400260", "400440", "400490", "400570", "400710", "400730"],
    "TRE": ["1200", "1290"],
    "A2R": ["6400"],
}

P2P_COMPATIBLE_ACCOUNTS = [
    "500000",
    "500060",
    "500120",
    "500150",
    "500230",
    "500270",
    "500380",
    "500410",
    "500480",
    "500590",
    "500680",
    "500720",
    "200000",
    "200050",
    "100310",
    "100320",
]

TEXT_HINTS = {
    "O2C": [
        "판매수수료 정산 계정 재분류",
        "고객 클레임 비용 임시 반영",
        "매출 관련 비용 대체 입력",
    ],
    "H2R": [
        "급여 정산 중 기타수익 계정 임시 사용",
        "복리후생 환급분 계정 재분류 대기",
        "인사비용 조정 중 수익계정 대체",
    ],
    "TRE": [
        "자금거래 투자자산 계정 임시 사용",
        "단기자금 운용 계정 대체 입력",
        "은행거래 비유동자산 계정 확인 필요",
    ],
    "A2R": [
        "자산 취득 관련 인건비성 계정 임시 사용",
        "고정자산 프로젝트 급여성 계정 대체",
        "자산화 검토 전 급여 계정 임시 반영",
    ],
    "P2P_NORMALIZED": [
        "매입 비용 계정 정정",
        "구매 정산 계정 보정",
        "매입채무 관련 계정 보정",
    ],
}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_year_rows() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        frame["_year_file"] = str(year)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def _write_year_rows(rows: pd.DataFrame) -> None:
    write_cols = [col for col in rows.columns if col != "_year_file"]
    for year in YEARS:
        year_rows = rows.loc[rows["_year_file"].astype(str).eq(str(year)), write_cols].copy()
        year_rows.to_csv(DEST / f"journal_entries_{year}.csv", index=False, encoding="utf-8")
    combined = rows[write_cols].copy()
    combined.to_csv(DEST / "journal_entries.csv", index=False, encoding="utf-8")


def _detect_l301(rows: pd.DataFrame) -> pd.Series:
    result = IntegrityDetector().detect(rows)
    if RULE_ID not in result.details:
        raise RuntimeError(f"{RULE_ID} missing from detector details")
    return pd.to_numeric(result.details[RULE_ID], errors="coerce").fillna(0.0).gt(0)


def _choose_docs(candidates: pd.DataFrame, count: int, salt: str) -> list[str]:
    if count <= 0 or candidates.empty:
        return []
    docs = candidates.drop_duplicates("document_id").copy()
    docs["_sort"] = (
        docs["company_code"].fillna("")
        + "|"
        + docs["source"].fillna("")
        + "|"
        + docs["document_number"].fillna("")
        + "|"
        + docs["document_id"].astype(str)
        + "|"
        + salt
    )
    docs["_source_rank"] = docs.groupby("source", dropna=False).cumcount()
    selected = docs.sort_values(["_source_rank", "_sort"]).head(count)
    return selected["document_id"].astype(str).tolist()


def _replace_accounts(rows: pd.DataFrame, doc_ids: list[str], process: str, account_cycle: list[str], text_key: str) -> pd.DataFrame:
    patched: list[dict[str, object]] = []
    if not doc_ids:
        return pd.DataFrame()
    doc_set = set(doc_ids)
    denied = set(DENIED_ACCOUNTS[process])
    for idx, doc_id in enumerate(doc_ids):
        doc_mask = rows["document_id"].astype(str).eq(doc_id)
        if process == "P2P":
            line_mask = doc_mask & rows["gl_account"].astype(str).isin(denied)
        else:
            nonempty = rows["gl_account"].fillna("").astype(str).str.strip().ne("")
            line_mask = doc_mask & nonempty
        line_indexes = rows.index[line_mask].tolist()
        if not line_indexes:
            continue
        line_idx = line_indexes[0]
        before = str(rows.at[line_idx, "gl_account"])
        after = account_cycle[idx % len(account_cycle)]
        rows.at[line_idx, "gl_account"] = after
        hint = TEXT_HINTS[text_key][idx % len(TEXT_HINTS[text_key])]
        current = "" if pd.isna(rows.at[line_idx, "line_text"]) else str(rows.at[line_idx, "line_text"])
        rows.at[line_idx, "line_text"] = f"{current[:120]} | {hint}"
        patched.append(
            {
                "document_id": doc_id,
                "fiscal_year": rows.loc[doc_mask, "fiscal_year"].iloc[0],
                "company_code": rows.loc[doc_mask, "company_code"].iloc[0],
                "document_number": rows.loc[doc_mask, "document_number"].iloc[0],
                "business_process": process,
                "line_number": rows.at[line_idx, "line_number"],
                "gl_account_before": before,
                "gl_account_after": after,
                "patch_action": "normalize_p2p" if process == "P2P" else "inject_distributed_l301",
                "text_hint": hint,
            }
        )
    return pd.DataFrame(patched)


def _unique_join(values: pd.Series) -> str:
    cleaned = values.dropna().astype(str).map(str.strip)
    cleaned = cleaned[cleaned.ne("")]
    return "|".join(sorted(cleaned.unique()))


def _doc_amount(rows: pd.DataFrame) -> pd.Series:
    debit = pd.to_numeric(rows["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(rows["credit_amount"], errors="coerce").fillna(0.0)
    return debit.where(debit.gt(0), credit)


def _build_truth(rows: pd.DataFrame, flags: pd.Series) -> pd.DataFrame:
    flagged = rows.loc[flags].copy()
    flagged["_line_amount"] = _doc_amount(flagged)
    flagged["_l301_score"] = 1.0
    truth = flagged.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        materiality_amount=("_line_amount", "sum"),
        l301_flagged_row_count=("line_number", "count"),
        l301_accounts=("gl_account", _unique_join),
        l301_max_score=("_l301_score", "max"),
        related_anomaly_types=("anomaly_type", _unique_join),
    )
    truth.insert(0, "rule_id", RULE_ID)
    truth["expected_hit"] = True
    truth["truth_basis"] = (
        "valid CoA account satisfies current L3-01 detector contract for "
        "process/account mismatch review"
    )
    truth["evidence_fields"] = (
        "business_process,gl_account,config/audit_rules.yaml:l3_01_misclassified_account"
    )
    truth["is_injected_issue"] = truth["related_anomaly_types"].str.contains("MisclassifiedAccount", regex=False, na=False)
    truth["is_audit_issue"] = False
    truth["truth_layer"] = "rule_truth"
    truth["evaluation_unit"] = "document"
    truth["truth_derivation"] = "src.detection.integrity_layer.IntegrityDetector.L3-01"
    return truth.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _write_l301_truth(truth: pd.DataFrame) -> None:
    truth.to_csv(LABELS / "rule_truth_L3_01.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth_L3_01.json", truth)
    population = truth.copy()
    population["population_type"] = "l301_account_process_mismatch_review_population"
    population.to_csv(LABELS / "l301_account_process_mismatch_review_population.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "l301_account_process_mismatch_review_population.json", population)
    for year in YEARS:
        year_truth = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_truth.to_csv(LABELS / f"rule_truth_L3_01_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"rule_truth_L3_01_{year}.json", year_truth)
        year_pop = population.loc[population["fiscal_year"].astype(str).eq(str(year))].copy()
        year_pop.to_csv(LABELS / f"l301_account_process_mismatch_review_population_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"l301_account_process_mismatch_review_population_{year}.json", year_pop)


def _rebuild_combined_rule_truth() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth.json", combined)
    return combined


def main() -> None:
    _copy_candidate_safely()
    rows = _read_year_rows()
    before_flags = _detect_l301(rows)
    before_docs = rows.loc[before_flags].drop_duplicates("document_id")

    patches: list[pd.DataFrame] = []
    p2p_current = before_docs.loc[before_docs["business_process"].eq("P2P")]
    p2p_remove_count = max(0, len(p2p_current) - TARGET_DOCS["P2P"])
    p2p_remove_docs = _choose_docs(p2p_current, p2p_remove_count, "reduce_p2p")
    patches.append(_replace_accounts(rows, p2p_remove_docs, "P2P", P2P_COMPATIBLE_ACCOUNTS, "P2P_NORMALIZED"))

    interim_flags = _detect_l301(rows)
    interim_docs = rows.loc[interim_flags].drop_duplicates("document_id")
    current_truth_docs = set(interim_docs["document_id"].astype(str))
    for process in ("O2C", "H2R", "TRE", "A2R"):
        current_count = int((interim_docs["business_process"] == process).sum())
        add_count = max(0, TARGET_DOCS[process] - current_count)
        candidates = rows.loc[
            rows["business_process"].eq(process)
            & ~rows["document_id"].astype(str).isin(current_truth_docs)
            & rows["source"].fillna("").str.lower().isin(["manual", "adjustment", "recurring"])
        ].copy()
        doc_ids = _choose_docs(candidates, add_count, f"add_{process}")
        patches.append(_replace_accounts(rows, doc_ids, process, DENIED_ACCOUNTS[process], process))
        current_truth_docs.update(doc_ids)

    patch_log = pd.concat([p for p in patches if not p.empty], ignore_index=True, sort=False)
    if not patch_log.empty:
        patch_log.to_csv(LABELS / "l301_distribution_patch_log.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / "l301_distribution_patch_log.json", patch_log)

    after_flags = _detect_l301(rows)
    truth = _build_truth(rows, after_flags)
    _write_l301_truth(truth)
    combined = _rebuild_combined_rule_truth()
    _write_year_rows(rows)

    by_process = truth["business_process"].value_counts().sort_index().to_dict()
    by_year = truth.groupby("fiscal_year")["document_id"].nunique().to_dict()
    summary = {
        "candidate": "v86",
        "source": str(SOURCE.relative_to(ROOT)),
        "destination": str(DEST.relative_to(ROOT)),
        "purpose": "reduce P2P-heavy L3-01 distribution and diversify process mismatch candidates",
        "l301_before_docs": int(before_docs["document_id"].nunique()),
        "l301_after_docs": int(truth["document_id"].nunique()),
        "l301_after_by_process": {str(k): int(v) for k, v in by_process.items()},
        "l301_after_by_year": {str(k): int(v) for k, v in by_year.items()},
        "patched_rows": int(len(patch_log)),
        "p2p_normalized_docs": int((patch_log["patch_action"].eq("normalize_p2p")).sum()) if not patch_log.empty else 0,
        "distributed_l301_injected_docs": int((patch_log["patch_action"].eq("inject_distributed_l301")).sum()) if not patch_log.empty else 0,
        "combined_rule_truth_counts": {str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()},
    }
    (DEST / "V86_L301_DISTRIBUTION_PATCH.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEST / "FREEZE_V86_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v86 Candidate",
                "",
                "Status: candidate, not promoted to production.",
                "",
                "Purpose: make L3-01 account/process mismatch distribution less P2P-heavy while keeping rule truth detector-contract based.",
                "",
                f"- L3-01 before: `{summary['l301_before_docs']}`",
                f"- L3-01 after: `{summary['l301_after_docs']}`",
                f"- By process: `{summary['l301_after_by_process']}`",
                f"- By year: `{summary['l301_after_by_year']}`",
                f"- Patched rows: `{summary['patched_rows']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
