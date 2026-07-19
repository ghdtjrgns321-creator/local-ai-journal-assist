"""Build v74 candidate by fixing DataSynth CoA coverage, then rebuilding rule truth."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v73_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v74_candidate"
INVALID_TEST_ACCOUNTS = {"777777", "888888"}
_V73_PATH = ROOT / "tools" / "scripts" / "build_datasynth_v73_rule_truth.py"
_SPEC = importlib.util.spec_from_file_location("build_datasynth_v73_rule_truth", _V73_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot load {_V73_PATH}")
v73 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(v73)


def _account_template(code: str) -> dict:
    first = code[0] if code else "9"
    account_type = {
        "1": "asset",
        "2": "liability",
        "3": "equity",
        "4": "revenue",
        "5": "expense",
        "6": "expense",
        "7": "expense",
        "8": "expense",
        "9": "statistical",
    }.get(first, "expense")
    return {
        "account_number": code,
        "short_description": "",
        "long_description": "",
        "account_type": account_type,
        "sub_type": "other",
        "account_class": first,
        "account_group": "CONFIG_COA_BACKFILL",
        "is_control_account": False,
        # 가계정 플래그는 여기서 찍지 않는다. 계정의 성격은 그 계정을 만드는 곳
        # (datasynth coa_generator)이 정하고, 이 스크립트는 config CSV에 있는 이름만
        # backfill한다. 종전에는 1190/2190/9990을 여기서 가계정으로 찍었는데,
        # 9990 통계계정은 가계정이 아니고(원장 0행), 1190/2190은 coa_generator가
        # Suspense Receivable/Payable로 직접 생성하므로 이 경로로 올 일이 없다.
        "is_suspense_account": False,
        "parent_account": None,
        "hierarchy_level": 1,
        "normal_debit_balance": account_type in {"asset", "expense", "statistical"},
        "is_postable": True,
        "is_blocked": False,
        "allowed_doc_types": ["SA", "KR", "KZ", "DR", "DZ", "WE", "AA", "HR", "IC"],
        "requires_cost_center": account_type == "expense",
        "requires_profit_center": False,
        "industry_weights": {
            "manufacturing": 1.0,
            "retail": 1.0,
            "financial_services": 1.0,
            "healthcare": 1.0,
            "technology": 1.0,
            "professional_services": 1.0,
            "energy": 1.0,
            "transportation": 1.0,
            "real_estate": 1.0,
            "telecommunications": 1.0,
        },
        "typical_frequency": 100.0,
        "typical_amount_range": [100.0, 100000.0],
    }


def _patch_coa_from_config() -> dict[str, object]:
    coa_path = DEST / "chart_of_accounts.json"
    config_path = ROOT / "config" / "chart_of_accounts.csv"
    coa = json.loads(coa_path.read_text(encoding="utf-8"))
    config = pd.read_csv(config_path, dtype=str)
    config_names = dict(
        zip(config["gl_account"].astype(str), config["account_name_kr"].astype(str))
    )
    existing = {str(row.get("account_number", "")).strip() for row in coa.get("accounts", [])}

    journal_accounts: set[str] = set()
    for year in v73.YEARS:
        df = pd.read_csv(
            DEST / f"journal_entries_{year}.csv",
            dtype=str,
            usecols=["gl_account"],
            low_memory=False,
        )
        journal_accounts.update(df["gl_account"].dropna().astype(str).str.strip())

    added: list[str] = []
    for code in sorted(journal_accounts):
        if not code or code in existing or code in INVALID_TEST_ACCOUNTS:
            continue
        if code not in config_names:
            continue
        row = _account_template(code)
        row["short_description"] = config_names[code]
        row["long_description"] = config_names[code]
        coa["accounts"].append(row)
        existing.add(code)
        added.append(code)

    coa_path.write_text(json.dumps(coa, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "added_accounts": added,
        "added_count": len(added),
        "invalid_test_accounts_preserved": sorted(INVALID_TEST_ACCOUNTS),
    }


def main() -> None:
    os.environ["DATASYNTH_RULE_TRUTH_SOURCE"] = str(SOURCE)
    os.environ["DATASYNTH_RULE_TRUTH_DEST"] = str(DEST)
    v73.SRC = SOURCE
    v73.DEST = DEST
    v73.LABELS = DEST / "labels"
    v73._materialize_candidate()
    coa_summary = _patch_coa_from_config()
    rule_counts = v73.build_truth()

    summary = {
        "candidate_version": "v74",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "backfill DataSynth chart_of_accounts.json from config/chart_of_accounts.csv for normal recurring accounts, then rebuild rule_truth",
        "coa_patch": coa_summary,
        "rule_counts": rule_counts,
        "anti_fitting_note": "CoA backfill uses project CoA config, not detector output. Explicit invalid test accounts remain outside CoA.",
    }
    (DEST / "V74_COA_RULE_TRUTH_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V74_CANDIDATE.md").write_text(
        "# DataSynth v74 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: CoA coverage backfill plus rule-truth regeneration.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
