"""Unit tests for access-control rules L1-05, L1-06, L1-07, L3-03."""

from __future__ import annotations

import pandas as pd

from src.detection.fraud_rules_access import (
    b06_self_approval,
    b07_segregation_of_duties,
    b09_skipped_approval,
    b10_intercompany_review_signal,
    b12_missing_approval_date,
    b13_high_risk_account_use,
)


class TestL1_09:
    def test_approver_present_but_approval_date_missing_flagged(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR1", "APR2", "", "APR4"],
            "approval_date": [None, "2025-01-02", None, ""],
        })
        assert b12_missing_approval_date(df).tolist() == [True, False, False, True]

    def test_missing_columns_returns_false(self) -> None:
        df = pd.DataFrame({"approved_by": ["APR1"]})
        assert not b12_missing_approval_date(df).any()


class TestL3_10:
    def test_high_risk_account_exact_and_prefix_flagged(self) -> None:
        df = pd.DataFrame({"gl_account": ["1190", "1115", "5100", None]})
        rules = {
            "patterns": {
                "high_risk_account_use": {
                    "accounts": ["1190"],
                    "account_prefixes": ["111"],
                }
            }
        }
        assert b13_high_risk_account_use(df, audit_rules=rules).tolist() == [
            True,
            True,
            False,
            False,
        ]

    def test_high_risk_account_includes_match_annotations(self) -> None:
        df = pd.DataFrame({"gl_account": ["1190", "1115", "5100"]}, index=[10, 11, 12])
        rules = {
            "patterns": {
                "high_risk_account_use": {
                    "accounts": ["1190"],
                    "account_prefixes": ["111"],
                    "sensitive_account_groups": {
                        "cash_equivalent": {"accounts": [], "account_prefixes": ["111"]},
                        "suspense_clearing": {"accounts": ["1190"], "account_prefixes": []},
                    },
                }
            }
        }

        result = b13_high_risk_account_use(df, audit_rules=rules)

        assert result.attrs["breakdown"]["reason_counts"] == {
            "exact": 1,
            "prefix": 1,
            "category_counts": {"raw_signal": 2},
        }
        assert result.attrs["row_annotations"] == {
            10: {
                "match_type": "exact",
                "matched_value": "1190",
                "matched_group": "suspense_clearing",
                "signal_category": "raw_signal",
                "category_reason": "sensitive_account_touch",
            },
            11: {
                "match_type": "prefix",
                "matched_value": "111",
                "matched_group": "cash_equivalent",
                "signal_category": "raw_signal",
                "category_reason": "sensitive_account_touch",
            },
        }

    def test_high_risk_account_splits_signal_categories(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": ["1190", "1190", "1190"],
                "source": ["manual", "automated", "recurring"],
                "exceeds_threshold": [False, False, True],
            },
            index=[1, 2, 3],
        )
        rules = {
            "patterns": {
                "high_risk_account_use": {
                    "accounts": ["1190"],
                    "account_prefixes": [],
                }
            }
        }

        result = b13_high_risk_account_use(df, audit_rules=rules)
        annotations = result.attrs["row_annotations"]

        assert annotations[1]["signal_category"] == "priority_case"
        assert annotations[1]["category_reason"] == "manual_or_adjustment"
        assert annotations[2]["signal_category"] == "normal_control_candidate"
        assert annotations[2]["category_reason"] == "routine_source"
        assert annotations[3]["signal_category"] == "priority_case"
        assert annotations[3]["category_reason"] == "high_amount"

    def test_missing_gl_account_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [1.0]})
        assert not b13_high_risk_account_use(df).any()


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

    def test_observed_summary_groups_results_for_queue_review(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "created_by": ["Kim", "Kim", "Lee"],
            "approved_by": ["Kim", "Kim", "Lee"],
            "business_process": ["P2P", "P2P", "R2R"],
            "posting_date": ["2024-09-01", "2024-09-15", "2024-12-28"],
            "source": ["manual", "manual", "manual"],
            "debit_amount": [100_000.0, 200_000.0, 300_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
        })
        result = b06_self_approval(df)
        summary = result.attrs["breakdown"]["observed_summary"]

        assert summary["group_key"] == ["created_by", "business_process", "posting_month"]
        assert summary["queue_counts"]["operational_immediate"] == 2
        assert summary["queue_counts"]["closing_review"] == 1
        top_group = summary["top_groups"][0]
        assert top_group["created_by"] == "Kim"
        assert top_group["business_process"] == "P2P"
        assert top_group["posting_month"] == "2024-09"
        assert top_group["total_docs"] == 2

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

    def test_r2r_pair_is_review_required_for_non_mitigating_role(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert result.all()
        assert result.attrs["score_series"].eq(0.4).all()

    def test_review_promoted_to_immediate_by_self_approval(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "approved_by": ["C1"] * 2,
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert result.all()
        assert result.attrs["score_series"].eq(0.8).all()
        assert result.attrs["breakdown"]["corroborated_review_rows"] == 2
        assert result.attrs["breakdown"]["self_approval_rows"] == 2

    def test_review_promoted_to_immediate_by_skipped_approval(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "source": ["manual", "manual"],
            "approved_by": ["", ""],
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert result.all()
        assert result.attrs["score_series"].eq(0.8).all()
        assert result.attrs["breakdown"]["corroborated_review_rows"] == 2
        assert result.attrs["breakdown"]["skipped_approval_rows"] == 2

    def test_manual_override_promotes_review_when_circumvention_signal_exists(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "approved_by": ["", ""],
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "is_manual_je": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert result.all()
        assert result.attrs["score_series"].eq(0.8).all()
        assert result.attrs["breakdown"]["corroborated_review_rows"] == 2
        assert result.attrs["breakdown"]["manual_override_rows"] == 2

    def test_manual_entry_without_circumvention_signal_does_not_promote_review(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "approved_by": ["APR1", "APR1"],
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "is_manual_je": [True, True],
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert result.all()
        assert result.attrs["score_series"].eq(0.4).all()
        assert result.attrs["breakdown"]["corroborated_review_rows"] == 0
        assert result.attrs["breakdown"]["manual_override_rows"] == 0

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

    def test_automated_source_excluded_from_sod(self) -> None:
        df = pd.DataFrame({
            "created_by": ["BATCH_USER", "BATCH_USER"],
            "business_process": ["TRE", "P2P"],
            "source": ["automated", "automated"],
            "user_persona": ["senior_accountant", "senior_accountant"],
            "debit_amount": [100.0, 100.0],
            "credit_amount": [0.0, 0.0],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

    def test_review_requires_exceeds_threshold(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1", "C1"],
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant", "senior_accountant"],
            "exceeds_threshold": [False, False],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

    def test_mitigating_role_suppresses_r2r_review(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1", "C1"],
            "business_process": ["R2R", "P2P"],
            "user_persona": ["controller", "controller"],
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

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
    def test_manual_missing_approval_with_extra_evidence_is_immediate(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True],
            "source": ["Manual"],
            "approved_by": [""],
            "approval_date": [None],
        })
        result = b09_skipped_approval(df)
        assert result[0]
        assert result.attrs["score_series"].iloc[0] == 0.8
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0

    def test_recurring_missing_approval_is_review_required(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True],
            "source": ["recurring"],
            "approved_by": [""],
            "approval_date": [None],
        })
        result = b09_skipped_approval(df)
        assert result[0]
        assert result.attrs["score_series"].iloc[0] == 0.4
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 1

    def test_manual_without_extra_evidence_stays_review_required(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True],
            "source": ["Manual"],
            "approved_by": [""],
        })
        result = b09_skipped_approval(df)
        assert result[0]
        assert result.attrs["score_series"].iloc[0] == 0.4
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 1

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b09_skipped_approval(df).any()


class TestL3_03:
    def test_intercompany_account_flagged_for_review(self) -> None:
        df = pd.DataFrame({
            "is_intercompany": [True, True, False],
            "company_code": ["A", "B", "A"],
        })
        result = b10_intercompany_review_signal(df)
        assert result[0]
        assert result[1]
        assert not result[2]

    def test_single_company_intercompany_account_still_flagged(self) -> None:
        df = pd.DataFrame({
            "is_intercompany": [True, False],
            "company_code": ["A", "A"],
        })
        result = b10_intercompany_review_signal(df)
        assert result[0]
        assert not result[1]

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b10_intercompany_review_signal(df).any()
