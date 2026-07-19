import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "scripts" / "audit_overlay_injection.py"
SPEC = importlib.util.spec_from_file_location("audit_overlay_injection", SCRIPT)
assert SPEC is not None
audit_overlay_injection = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit_overlay_injection)


def _write_fixture(tmp_path: Path, *, include_suspense: bool) -> tuple[Path, Path]:
    data_dir = tmp_path / "dataset"
    labels = data_dir / "labels"
    labels.mkdir(parents=True)
    accounts = [{"gl_account": "1000", "account_name": "cash"}]
    config_accounts = [{"gl_account": "1000", "account_name_kr": "cash"}]
    if include_suspense:
        accounts.append({"gl_account": "25110", "account_name": "suspense liability"})
        config_accounts.append({"gl_account": "25110", "account_name_kr": "suspense liability"})

    (data_dir / "chart_of_accounts.json").write_text(
        pd.Series(accounts).to_json(force_ascii=False),
        encoding="utf-8",
    )
    pd.DataFrame(config_accounts).to_csv(tmp_path / "chart_of_accounts.csv", index=False)
    pd.DataFrame(
        [
            {"document_id": "DOC-L309", "gl_account": "25110"},
            {"document_id": "DOC-L103", "gl_account": "999998"},
            {"document_id": "DOC-CASH", "gl_account": "1000"},
        ]
    ).to_csv(data_dir / "journal_entries.csv", index=False)
    pd.DataFrame(
        [
            {
                "rule_id": "L1-03",
                "case_kind": "standard",
                "member_document_ids": '["DOC-L103"]',
            }
        ]
    ).to_csv(labels / "p3_2_rule_truth.csv", index=False)
    return data_dir, tmp_path / "chart_of_accounts.csv"


def test_coa_gate_fails_missing_account_outside_l103_exception(tmp_path: Path) -> None:
    data_dir, config_coa = _write_fixture(tmp_path, include_suspense=False)

    report = audit_overlay_injection.audit_coa_coverage(data_dir, config_coa)

    assert report["status"] == "FAIL"
    forbidden = {
        row["gl_account"]: row for row in report["forbidden_missing_accounts"]
    }
    assert set(forbidden) == {"25110"}
    assert forbidden["25110"]["forbidden_docs"] == 1
    all_findings = {row["gl_account"]: row for row in report["missing_account_findings"]}
    assert all_findings["999998"]["allowed_l103_docs"] == 1
    assert all_findings["999998"]["forbidden_docs"] == 0


def test_coa_gate_allows_l103_invalid_account_only(tmp_path: Path) -> None:
    data_dir, config_coa = _write_fixture(tmp_path, include_suspense=True)

    report = audit_overlay_injection.audit_coa_coverage(data_dir, config_coa)

    assert report["status"] == "PASS"
    assert report["forbidden_missing_accounts"] == []
    findings = {row["gl_account"]: row for row in report["missing_account_findings"]}
    assert set(findings) == {"999998"}
    assert findings["999998"]["allowed_l103_docs"] == 1
