"""v48 RBAC NORMAL 전량 검증 — approval_limit 해소 fix (employee_master_path) 확인.

세 가지를 대조한다:
1. attrs 기반(정식 ingest) 경로 해소율
2. employee_master_path 명시 전달 경로 해소율 + 1번과 컬럼별 일치 여부
3. attrs 없음(구버전 ad-hoc 재현) 경로 해소율 — 0%가 재현되어야 수정 전 버그가 맞았다는 증거
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.feature.amount_features import add_all_amount_features  # noqa: E402
from src.ingest.datasynth_labels import set_source_path  # noqa: E402


def check_dataset(csv_path: Path, master_path: Path) -> dict:
    settings = get_settings()
    audit_rules = get_audit_rules()

    raw = pd.read_csv(csv_path, low_memory=False)
    total_rows = len(raw)
    approved_rows = raw["approved_by"].fillna("").astype(str).str.strip().ne("").sum()

    # 1) attrs 기반 (정식 ingest 경로)
    df_attrs = raw.copy()
    df_attrs = set_source_path(df_attrs, csv_path)
    add_all_amount_features(df_attrs, settings=settings, audit_rules=audit_rules)
    resolved_attrs = int(df_attrs["approval_limit_resolved"].sum())

    # 2) employee_master_path 명시 전달 (신규 fix 경로)
    df_explicit = raw.copy()
    add_all_amount_features(
        df_explicit,
        settings=settings,
        audit_rules=audit_rules,
        employee_master_path=master_path,
    )
    resolved_explicit = int(df_explicit["approval_limit_resolved"].sum())

    # 3) attrs 없음 (구버전 ad-hoc 재현 — attrs를 아예 안 붙임)
    df_noattrs = raw.copy()
    add_all_amount_features(df_noattrs, settings=settings, audit_rules=audit_rules)
    resolved_noattrs = int(df_noattrs["approval_limit_resolved"].sum())

    compare_cols = ["approval_limit_resolved", "approver_limit_amount", "exceeds_threshold"]
    mismatch_count = 0
    for col in compare_cols:
        a = df_attrs[col]
        b = df_explicit[col]
        if a.dtype.kind == "f" or b.dtype.kind == "f":
            mism = (~((a == b) | (a.isna() & b.isna()))).sum()
        else:
            mism = (a.astype(object) != b.astype(object)).sum()
        mismatch_count += int(mism)

    bucket_counts = df_explicit["approval_excess_bucket"].value_counts().to_dict()
    exceeds_count = int(df_explicit["exceeds_threshold"].sum())

    return {
        "csv_path": str(csv_path),
        "total_rows": int(total_rows),
        "approved_by_nonblank_rows": int(approved_rows),
        "resolved_attrs_path": resolved_attrs,
        "resolved_explicit_path": resolved_explicit,
        "resolved_noattrs_reproduction": resolved_noattrs,
        "attrs_vs_explicit_mismatch_count": mismatch_count,
        "exceeds_threshold_count": exceeds_count,
        "approval_excess_bucket_counts": {str(k): int(v) for k, v in bucket_counts.items()},
        "unresolved_limit_bucket_count": int(bucket_counts.get("unresolved_limit", 0)),
    }


def main() -> None:
    datasets = [
        (
            PROJECT_ROOT
            / "data/journal/primary/datasynth_semantic_v1_normal_20260701_v48_rbac_r1/journal_entries.csv",
            PROJECT_ROOT
            / "data/journal/primary/datasynth_semantic_v1_normal_20260701_v48_rbac_r1/master_data/employees.json",
        ),
        (
            PROJECT_ROOT
            / "data/journal/primary/datasynth_integrated_usefulness_all_fraud_20260702_v1/journal_entries.csv",
            PROJECT_ROOT
            / "data/journal/primary/datasynth_integrated_usefulness_all_fraud_20260702_v1/master_data/employees.json",
        ),
    ]

    results = {}
    for csv_path, master_path in datasets:
        key = csv_path.parent.name
        print(f"checking {key} ...", file=sys.stderr)
        results[key] = check_dataset(csv_path, master_path)

    out_path = PROJECT_ROOT / "reports/v48_approval_limit_fix_check.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
