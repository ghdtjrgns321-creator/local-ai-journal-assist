"""Unit tests for access-control rules L1-05, L1-06, L1-07, L3-03."""

from __future__ import annotations

import pandas as pd

from src.detection.fraud_rules_access import (
    b06_self_approval,
    b07_segregation_of_duties,
    b09_skipped_approval,
    b10_circular_intercompany,
)


class TestL1_05:
    def test_human_self_approval_flagged_without_amount_filter(self) -> None:
        df = pd.DataFrame({
            "created_by": ["USR-JA-001"],
            "approved_by": ["USR-JA-001"],
            "user_persona": ["junior_accountant"],
            "debit_amount": [5_000_000.0],
            "credit_amount": [0.0],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0

    def test_default_allowed_system_persona_excluded(self) -> None:
        df = pd.DataFrame({
            "created_by": ["SYSTEM"],
            "approved_by": ["SYSTEM"],
            "user_persona": ["automated_system"],
        })
        result = b06_self_approval(df)
        assert not result[0]

    def test_default_allowed_system_source_excluded(self) -> None:
        df = pd.DataFrame({
            "created_by": ["BATCHUSER"],
            "approved_by": ["BATCHUSER"],
            "source": ["automated"],
        })
        result = b06_self_approval(df)
        assert not result[0]

    def test_r2r_self_approval_defaults_to_review(self) -> None:
        df = pd.DataFrame({
            "created_by": ["CTRL-001"],
            "approved_by": ["CTRL-001"],
            "user_persona": ["controller"],
            "document_type": ["SA"],
            "business_process": ["R2R"],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 1

    def test_r2r_large_manual_self_approval_escalates_to_immediate(self) -> None:
        df = pd.DataFrame({
            "created_by": ["CTRL-001"],
            "approved_by": ["CTRL-001"],
            "business_process": ["R2R"],
            "source": ["manual"],
            "debit_amount": [2_000_000_000.0],
            "credit_amount": [0.0],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["override_counts"]["materiality_rows"] == 1

    def test_r2r_after_hours_self_approval_escalates_to_immediate(self) -> None:
        df = pd.DataFrame({
            "created_by": ["CTRL-001"],
            "approved_by": ["CTRL-001"],
            "business_process": ["R2R"],
            "is_after_hours": [True],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["override_counts"]["abnormal_time_rows"] == 1

    def test_r2r_high_risk_account_self_approval_escalates_to_immediate(self) -> None:
        df = pd.DataFrame({
            "created_by": ["CTRL-001"],
            "approved_by": ["CTRL-001"],
            "business_process": ["R2R"],
            "gl_account": ["1190"],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["override_counts"]["high_risk_account_rows"] == 1

    def test_o2c_self_approval_defaults_to_immediate(self) -> None:
        df = pd.DataFrame({
            "created_by": ["CTRL-001"],
            "approved_by": ["CTRL-001"],
            "user_persona": ["controller"],
            "document_type": ["SA"],
            "business_process": ["O2C"],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0

    def test_review_processes_are_editable(self) -> None:
        df = pd.DataFrame({
            "created_by": ["CTRL-001"],
            "approved_by": ["CTRL-001"],
            "business_process": ["TRE"],
        })
        rules = {
            "patterns": {
                "self_approval_review": {
                    "business_processes": ["TRE"],
                }
            }
        }
        result = b06_self_approval(df, audit_rules=rules)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 1

    def test_missing_approved_by_is_not_l105(self) -> None:
        df = pd.DataFrame({
            "created_by": ["User1"],
            "source": ["Manual"],
        })
        assert not b06_self_approval(df).any()

    def test_no_created_by_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b06_self_approval(df).any()

    def test_null_persona_still_evaluated(self) -> None:
        df = pd.DataFrame({
            "created_by": ["User1"],
            "approved_by": ["User1"],
            "user_persona": [None],
            "debit_amount": [50_000_000.0],
            "credit_amount": [0.0],
        })
        result = b06_self_approval(df)
        assert result[0]


class TestL1_06:
    def test_toxic_pair_flagged(self) -> None:
        df = pd.DataFrame({
            "created_by": ["A", "A", "B"],
            "business_process": ["TRE", "P2P", "R2R"],
        })
        result = b07_segregation_of_duties(df)
        assert result[0]
        assert result[1]
        assert not result[2]
        assert result.attrs["score_series"].iloc[0] == 0.8
        assert result.attrs["breakdown"]["immediate_rows"] == 2

    def test_in_process_conflict_flagged(self) -> None:
        df = pd.DataFrame({
            "created_by": ["A", "A"],
            "business_process": ["R2R", "R2R"],
            "sod_conflict_type": ["preparer_approver", None],
        })
        result = b07_segregation_of_duties(df)
        assert result[0]
        assert not result[1]
        assert result.attrs["score_series"].iloc[0] == 0.8

    def test_junior_exceeds_role_threshold(self) -> None:
        df = pd.DataFrame({
            "created_by": ["J1", "J1"],
            "business_process": ["P2P", "O2C"],
            "user_persona": ["junior_accountant", "junior_accountant"],
        })
        result = b07_segregation_of_duties(df)
        assert result.all()
        assert result.attrs["score_series"].eq(0.4).all()
        assert result.attrs["breakdown"]["review_rows"] == 2

    def test_controller_toxic_pair_still_flagged(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 3,
            "business_process": ["R2R", "TRE", "P2P"],
            "user_persona": ["controller"] * 3,
        })
        result = b07_segregation_of_duties(df)
        assert result.all()
        assert result.attrs["score_series"].eq(0.8).all()

    def test_controller_safe_processes_pass(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 3,
            "business_process": ["R2R", "A2R", "H2R"],
            "user_persona": ["controller"] * 3,
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

    def test_r2r_pair_is_review_required(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "business_process": ["R2R", "P2P"],
            "user_persona": ["controller"] * 2,
        })
        result = b07_segregation_of_duties(df)
        assert result.all()
        assert result.attrs["score_series"].eq(0.4).all()

    def test_it_admin_transactional_posting_is_immediate(self) -> None:
        df = pd.DataFrame({
            "created_by": ["ADM1"],
            "business_process": ["TRE"],
            "user_persona": ["system admin"],
            "debit_amount": [10_000_000.0],
            "credit_amount": [0.0],
        })
        result = b07_segregation_of_duties(df)
        assert result[0]
        assert result.attrs["score_series"].iloc[0] == 0.8
        assert result.attrs["breakdown"]["it_admin_high_risk_rows"] == 1

    def test_it_admin_non_transactional_row_is_not_immediate(self) -> None:
        df = pd.DataFrame({
            "created_by": ["ADM1"],
            "business_process": ["TRE"],
            "user_persona": ["system admin"],
            "debit_amount": [0.0],
            "credit_amount": [0.0],
        })
        result = b07_segregation_of_duties(df)
        assert not result[0]
        assert result.attrs["breakdown"]["it_admin_high_risk_rows"] == 0

    def test_fallback_without_persona(self) -> None:
        df = pd.DataFrame({
            "created_by": ["A", "A", "A", "B"],
            "business_process": ["P2P", "O2C", "R2R", "R2R"],
        })
        result = b07_segregation_of_duties(df, sod_threshold=3)
        assert result[0]
        assert not result[3]

    def test_automated_system_excluded(self) -> None:
        df = pd.DataFrame({
            "created_by": ["SYS1", "SYS1", "SYS1"],
            "business_process": ["TRE", "P2P", "O2C"],
            "user_persona": ["automated_system"] * 3,
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"created_by": ["A"]})
        assert not b07_segregation_of_duties(df).any()


class TestL1_07:
    def test_exceeds_non_automated_flagged(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True, True, False],
            "source": ["Manual", "automated", "Manual"],
        })
        result = b09_skipped_approval(df)
        assert result[0]
        assert not result[1]
        assert not result[2]

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b09_skipped_approval(df).any()


class TestL3_03:
    def test_intercompany_flagged(self) -> None:
        df = pd.DataFrame({
            "is_intercompany": [True, True, False],
            "company_code": ["A", "B", "A"],
        })
        result = b10_circular_intercompany(df)
        assert result[0]
        assert result[1]
        assert not result[2]

    def test_single_company_still_flagged(self) -> None:
        df = pd.DataFrame({
            "is_intercompany": [True, False],
            "company_code": ["A", "A"],
        })
        result = b10_circular_intercompany(df)
        assert result[0]
        assert not result[1]

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b10_circular_intercompany(df).any()
