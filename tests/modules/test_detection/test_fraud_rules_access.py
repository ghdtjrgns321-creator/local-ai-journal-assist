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
    b14_work_scope_excess_review,
)


class TestL1_09:
    def test_approver_present_but_approval_date_missing_flagged(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR1", "APR2", "", "APR4"],
            "approval_date": [None, "2025-01-02", None, ""],
        })
        result = b12_missing_approval_date(df)
        assert result.tolist() == [True, False, True, True]
        assert result.attrs["breakdown"]["candidate_rows"] == 3
        assert result.attrs["breakdown"]["missing_approver_rows"] == 1
        assert result.attrs["review_score_series"].iloc[2] == 0.1
        assert result.attrs["row_annotations"][2]["queue_label"] == "low_priority"
        assert result.attrs["row_annotations"][2]["source_category"] == "missing_approver"

    def test_system_source_missing_approval_date_stays_review_required(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR1", "APR2"],
            "approval_date": [None, None],
            "source": ["recurring", "automated"],
        })

        result = b12_missing_approval_date(df)

        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [0.0, 0.0]
        assert result.attrs["review_score_series"].tolist() == [0.25, 0.25]
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 2
        assert result.attrs["row_annotations"][0]["queue_label"] == "review"
        assert result.attrs["row_annotations"][0]["bucket"] == "system_review"

    def test_manual_missing_approval_date_is_immediate(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR1"],
            "approval_date": [None],
            "source": ["Manual"],
        })

        result = b12_missing_approval_date(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].iloc[0] == 0.55
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["row_annotations"][0]["bucket"] == "single_control_gap"

    def test_manual_high_amount_missing_approval_date_is_material(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR1"],
            "approval_date": [None],
            "source": ["Manual"],
            "exceeds_threshold": [True],
        })

        result = b12_missing_approval_date(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].iloc[0] == 0.70
        assert result.attrs["row_annotations"][0]["bucket"] == "material_control_gap"
        assert set(result.attrs["row_annotations"][0]["evidence_reasons"]) == {
            "manual_source",
            "high_amount",
        }

    def test_material_missing_approval_date_with_timing_or_account_is_strong(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR1"],
            "approval_date": [None],
            "source": ["Manual"],
            "exceeds_threshold": [True],
            "is_period_end": [True],
        })

        result = b12_missing_approval_date(df)

        assert result.attrs["score_series"].iloc[0] == 0.80
        assert result.attrs["row_annotations"][0]["bucket"] == "corroborated_material"

    def test_nat_approval_date_is_missing(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR1"],
            "approval_date": pd.to_datetime([None]),
            "source": ["Manual"],
        })

        result = b12_missing_approval_date(df)

        assert result.tolist() == [True]
        assert result.attrs["breakdown"]["immediate_rows"] == 1

    def test_missing_approval_date_without_approver_is_low_priority(self) -> None:
        df = pd.DataFrame({
            "approved_by": [""],
            "approval_date": [None],
            "source": ["Manual"],
        })

        result = b12_missing_approval_date(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["review_score_series"].iloc[0] == 0.1
        assert result.attrs["breakdown"]["low_priority_rows"] == 1
        assert result.attrs["row_annotations"][0]["queue_label"] == "low_priority"

    def test_missing_columns_returns_false(self) -> None:
        df = pd.DataFrame({"approved_by": ["APR1"]})
        assert not b12_missing_approval_date(df).any()

    def test_approval_contract_degraded_suppresses_l109_control_failure(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR1"],
            "approval_date": [None],
            "source": ["Manual"],
            "approval_contract_degraded": [True],
        })

        result = b12_missing_approval_date(df)

        assert not result.any()
        assert result.attrs["breakdown"]["suppression_reason"] == "approval_contract_degraded"
        assert result.attrs["breakdown"]["rule_id"] == "L1-09"


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

    def test_high_risk_account_score_series_and_category_breakdown(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": ["1190", "1190", "1190", "5100"],
                "source": ["manual", "automated", "other", "manual"],
                "exceeds_threshold": [False, False, False, False],
            }
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

        assert result.attrs["score_series"].tolist() == [0.65, 0.20, 0.35, 0.0]
        assert result.attrs["breakdown"]["priority_case_rows"] == 1
        assert result.attrs["breakdown"]["normal_control_candidate_rows"] == 1
        assert result.attrs["breakdown"]["raw_signal_rows"] == 1
        assert result.attrs["breakdown"]["category_counts"] == {
            "priority_case": 1,
            "normal_control_candidate": 1,
            "raw_signal": 1,
        }

    def test_missing_gl_account_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [1.0]})
        assert not b13_high_risk_account_use(df).any()


class TestL3_12:
    def test_multi_process_only_is_low_score_observation(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["u1", "u1", "u1", "u2"],
                "user_persona": ["staff", "staff", "staff", "staff"],
                "business_process": ["P2P", "O2C", "R2R", "P2P"],
                "company_code": ["1000", "1000", "1000", "1000"],
                "source": ["manual", "manual", "manual", "manual"],
            }
        )

        result = b14_work_scope_excess_review(df)

        assert result.tolist() == [True, True, True, False]
        assert result.attrs["score_series"].tolist() == [0.0, 0.0, 0.0, 0.0]
        assert result.attrs["review_score_series"].tolist() == [0.45, 0.45, 0.45, 0.0]
        assert result.attrs["breakdown"]["candidate_users"] == 1
        assert result.attrs["row_annotations"][0]["bucket"] == "manual_scope_concentration"
        assert result.attrs["row_annotations"][0]["review_score"] == 0.45
        assert result.attrs["row_annotations"][0]["rule_boundary"].startswith("L1-06")

    def test_process_company_breadth_scores_without_sod_violation(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["u1", "u1", "u1", "u1"],
                "user_persona": ["senior_accountant"] * 4,
                "business_process": ["P2P", "O2C", "R2R", "TRE"],
                "company_code": ["1000", "2000", "3000", "3000"],
                "source": ["automated", "automated", "automated", "automated"],
            }
        )

        result = b14_work_scope_excess_review(df)

        assert result.tolist() == [True, True, True, True]
        assert result.attrs["score_series"].tolist() == [0.0, 0.0, 0.0, 0.0]
        assert result.attrs["breakdown"]["zero_score_system_rows"] == 4
        assert result.attrs["row_annotations"][0]["bucket"] == "system_scope_observation"

    def test_work_scope_is_evaluated_per_fiscal_year_when_available(self) -> None:
        df = pd.DataFrame(
            {
                "fiscal_year": [2022, 2022, 2023, 2023, 2023],
                "created_by": ["u1", "u1", "u1", "u1", "u1"],
                "user_persona": ["accountant"] * 5,
                "business_process": ["P2P", "O2C", "P2P", "O2C", "R2R"],
                "company_code": ["1000", "1000", "1000", "2000", "3000"],
                "source": ["manual"] * 5,
            }
        )

        result = b14_work_scope_excess_review(df)

        assert result.tolist() == [False, False, True, True, True]
        assert result.attrs["score_series"].tolist() == [0.0, 0.0, 0.0, 0.0, 0.0]
        assert result.attrs["review_score_series"].tolist() == [0.0, 0.0, 0.45, 0.45, 0.45]
        assert result.attrs["breakdown"]["scoring_unit"] == "user_year"
        assert result.attrs["breakdown"]["candidate_users"] == 1
        assert result.attrs["row_annotations"][2]["fiscal_year"] == "2023"

    def test_compound_context_caps_l3_12_at_review_score(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["u1", "u1", "u1", "u1"],
                "user_persona": ["accountant"] * 4,
                "business_process": ["P2P", "O2C", "R2R", "TRE"],
                "company_code": ["1000", "2000", "3000", "3000"],
                "source": ["manual", "automated", "automated", "automated"],
                "gl_account": ["1190", "5100", "4100", "1100"],
                "is_period_end": [True, False, False, False],
                "exceeds_threshold": [False, False, False, False],
            }
        )

        result = b14_work_scope_excess_review(df)

        assert result.attrs["score_series"].tolist() == [0.0, 0.0, 0.0, 0.0]
        assert result.attrs["review_score_series"].tolist() == [0.65, 0.65, 0.65, 0.65]
        assert result.attrs["row_annotations"][0]["bucket"] == "compound_scope_concentration"
        assert set(result.attrs["row_annotations"][0]["reasons"]) >= {
            "manual_source",
            "sensitive_account",
            "period_end",
        }

    def test_admin_simple_breadth_is_excluded(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["admin1", "admin1", "admin1", "admin1"],
                "user_persona": ["superuser"] * 4,
                "business_process": ["P2P", "O2C", "R2R", "TRE"],
                "company_code": ["1000", "2000", "3000", "4000"],
            }
        )

        result = b14_work_scope_excess_review(df)

        assert result.tolist() == [True, True, True, True]
        assert result.attrs["score_series"].tolist() == [0.0, 0.0, 0.0, 0.0]
        assert result.attrs["breakdown"]["zero_score_admin_rows"] == 4


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
        assert result.attrs["score_series"].iloc[0] == 0.8
        assert result.attrs["row_annotations"][0]["bucket"] == "immediate"

    def test_default_allowed_system_persona_excluded(self) -> None:
        df = pd.DataFrame({
            "created_by": ["SYSTEM"],
            "approved_by": ["SYSTEM"],
            "user_persona": ["automated_system"],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["candidate_rows"] == 1
        assert result.attrs["breakdown"]["actionable_rows"] == 0
        assert result.attrs["breakdown"]["allowed_system_rows"] == 1
        assert result.attrs["breakdown"]["bucket_counts"] == {"allowed_system": 1}
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["review_score_series"].iloc[0] == 0.0
        assert result.attrs["row_annotations"][0]["bucket"] == "allowed_system"

    def test_default_allowed_system_source_excluded(self) -> None:
        df = pd.DataFrame({
            "created_by": ["BATCHUSER"],
            "approved_by": ["BATCHUSER"],
            "source": ["automated"],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["candidate_rows"] == 1
        assert result.attrs["breakdown"]["actionable_rows"] == 0
        assert result.attrs["breakdown"]["allowed_system_rows"] == 1
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["row_annotations"][0]["bucket"] == "allowed_system"

    def test_lone_automated_source_self_approval_is_not_allowed_system(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1"],
            "created_by": ["BATCHUSER"],
            "approved_by": ["BATCHUSER"],
            "source": ["automated"],
            "posting_date": pd.to_datetime(["2025-01-02"]),
            "batch_id": [None],
            "job_id": [None],
        })

        result = b06_self_approval(df)

        assert result[0]
        assert result.attrs["breakdown"]["actionable_rows"] == 1
        assert result.attrs["breakdown"]["allowed_system_rows"] == 0
        assert result.attrs["score_series"].iloc[0] == 0.8
        assert result.attrs["row_annotations"][0]["bucket"] == "immediate"

    def test_batched_automated_source_self_approval_remains_allowed_system(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1"],
            "created_by": ["BATCHUSER"],
            "approved_by": ["BATCHUSER"],
            "source": ["automated"],
            "posting_date": pd.to_datetime(["2025-01-02"]),
            "batch_id": ["BATCH-1"],
            "job_id": [None],
        })

        result = b06_self_approval(df)

        assert result[0]
        assert result.attrs["breakdown"]["actionable_rows"] == 0
        assert result.attrs["breakdown"]["allowed_system_rows"] == 1
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["row_annotations"][0]["bucket"] == "allowed_system"

    def test_missing_identity_columns_keep_self_approval_source_allowance_unchanged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1"],
            "created_by": ["BATCHUSER"],
            "approved_by": ["BATCHUSER"],
            "source": ["automated"],
            "posting_date": pd.to_datetime(["2025-01-02"]),
        })

        result = b06_self_approval(df)

        assert result[0]
        assert result.attrs["breakdown"]["actionable_rows"] == 0
        assert result.attrs["breakdown"]["allowed_system_rows"] == 1
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["row_annotations"][0]["bucket"] == "allowed_system"

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
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["review_score_series"].iloc[0] == 0.4
        assert result.attrs["row_annotations"][0]["bucket"] == "review"

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
        assert result.attrs["score_series"].iloc[0] == 0.8
        assert result.attrs["row_annotations"][0]["bucket"] == "escalated_materiality"
        assert result.attrs["row_annotations"][0]["override_reasons"] == ["materiality"]

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
        assert result.attrs["row_annotations"][0]["bucket"] == "escalated_abnormal_time"

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
        assert result.attrs["row_annotations"][0]["bucket"] == "escalated_high_risk_account"

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
        assert result.attrs["score_series"].iloc[0] == 0.8

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
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["review_score_series"].iloc[0] == 0.4

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
    def test_toxic_pair_is_work_scope_review_not_l106_score(self) -> None:
        df = pd.DataFrame({
            "created_by": ["A", "A", "B"],
            "business_process": ["TRE", "P2P", "R2R"],
            "exceeds_threshold": [True, True, True],
        })
        result = b07_segregation_of_duties(df)
        assert not result[0]
        assert not result[1]
        assert not result[2]
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["review_score_series"].iloc[0] == 0.0
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["work_scope_review_rows_excluded"] == 2
        assert result.attrs["breakdown"]["toxic_pair_review_users"] == 1

    def test_direct_sod_violation_is_immediate(self) -> None:
        df = pd.DataFrame({
            "created_by": ["A", "A"],
            "business_process": ["TRE", "P2P"],
            "sod_violation": [True, False],
            "sod_conflict_type": ["purchase_payment", ""],
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert result[0]
        assert not result[1]
        assert result.attrs["score_series"].iloc[0] == 0.8
        assert result.attrs["score_series"].iloc[1] == 0.0
        assert result.attrs["review_score_series"].iloc[1] == 0.0
        assert result.attrs["breakdown"]["direct_sod_violation_rows"] == 1

    def test_direct_sod_scores_use_evidence_bands(self) -> None:
        df = pd.DataFrame({
            "created_by": ["A", "B", "C", "ADM1"],
            "business_process": ["A2R", "P2P", "TRE", "TRE"],
            "sod_violation": [False, True, True, False],
            "sod_conflict_type": [
                "generic_conflict",
                "preparer_approver",
                "cash_disbursement",
                "",
            ],
            "exceeds_threshold": [False, False, True, False],
            "user_persona": [
                "senior_accountant",
                "senior_accountant",
                "senior_accountant",
                "system admin",
            ],
            "debit_amount": [0.0, 10_000.0, 50_000_000.0, 10_000_000.0],
            "credit_amount": [0.0, 0.0, 0.0, 0.0],
        })

        result = b07_segregation_of_duties(df)

        assert result.attrs["score_series"].tolist() == [0.5, 0.7, 0.8, 0.95]
        annotations = result.attrs["row_annotations"]
        assert annotations[0]["bucket"] == "direct_low"
        assert annotations[1]["bucket"] == "direct_medium"
        assert annotations[2]["bucket"] == "direct_high"
        assert annotations[3]["bucket"] == "direct_critical"
        assert result.attrs["review_score_series"].eq(0.0).all()

    def test_sod_violation_without_conflict_type_is_not_l106_when_both_fields_exist(self) -> None:
        df = pd.DataFrame({
            "created_by": ["A"],
            "business_process": ["TRE"],
            "sod_violation": [True],
            "sod_conflict_type": [""],
            "exceeds_threshold": [True],
        })
        result = b07_segregation_of_duties(df)
        assert not result[0]
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["direct_sod_violation_rows"] == 1
        assert result.attrs["breakdown"]["within_process_conflict_rows"] == 0

    def test_in_process_conflict_flagged(self) -> None:
        df = pd.DataFrame({
            "created_by": ["A", "A"],
            "business_process": ["R2R", "R2R"],
            "sod_conflict_type": ["preparer_approver", None],
        })
        result = b07_segregation_of_duties(df)
        assert result[0]
        assert not result[1]
        assert result.attrs["score_series"].iloc[0] == 0.7

    def test_junior_exceeds_role_threshold_is_excluded_from_l106_score(self) -> None:
        df = pd.DataFrame({
            "created_by": ["J1", "J1"],
            "business_process": ["P2P", "O2C"],
            "user_persona": ["junior_accountant", "junior_accountant"],
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["review_score_series"].eq(0.0).all()
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["work_scope_review_rows_excluded"] == 2

    def test_controller_toxic_pair_review_is_mitigated(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 3,
            "business_process": ["R2R", "TRE", "P2P"],
            "user_persona": ["controller"] * 3,
            "exceeds_threshold": [True] * 3,
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

    def test_controller_safe_processes_pass(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 3,
            "business_process": ["R2R", "A2R", "H2R"],
            "user_persona": ["controller"] * 3,
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

    def test_r2r_pair_is_excluded_from_l106_score(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["review_score_series"].eq(0.0).all()
        assert result.attrs["breakdown"]["work_scope_review_rows_excluded"] == 2

    def test_self_approval_does_not_promote_l106_review(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "approved_by": ["C1"] * 2,
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["review_score_series"].eq(0.0).all()
        assert result.attrs["breakdown"]["corroborated_review_rows"] == 0
        assert result.attrs["breakdown"]["self_approval_rows"] == 0

    def test_skipped_approval_does_not_promote_l106_review(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "source": ["manual", "manual"],
            "approved_by": ["", ""],
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["review_score_series"].eq(0.0).all()
        assert result.attrs["breakdown"]["corroborated_review_rows"] == 0
        assert result.attrs["breakdown"]["skipped_approval_rows"] == 0

    def test_manual_override_does_not_promote_l106_review(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"] * 2,
            "approved_by": ["", ""],
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant"] * 2,
            "is_manual_je": [True, True],
            "exceeds_threshold": [True, True],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["review_score_series"].eq(0.0).all()
        assert result.attrs["breakdown"]["corroborated_review_rows"] == 0
        assert result.attrs["breakdown"]["manual_override_rows"] == 0

    def test_self_approval_alone_is_not_l106(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1"],
            "approved_by": ["C1"],
            "business_process": ["R2R"],
            "user_persona": ["senior_accountant"],
            "exceeds_threshold": [True],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 0

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
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["review_score_series"].eq(0.0).all()
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
        assert result.attrs["score_series"].iloc[0] == 0.95
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
            "exceeds_threshold": [True, True, True, True],
        })
        result = b07_segregation_of_duties(df, sod_threshold=3)
        assert not result[0]
        assert not result[3]
        assert result.attrs["review_score_series"].iloc[0] == 0.0
        assert result.attrs["breakdown"]["work_scope_review_rows_excluded"] == 3

    def test_review_without_exceeds_threshold_column_is_suppressed(self) -> None:
        df = pd.DataFrame({
            "created_by": ["C1", "C1"],
            "business_process": ["R2R", "P2P"],
            "user_persona": ["senior_accountant", "senior_accountant"],
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["breakdown"]["review_rows"] == 0

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
    def test_unknown_approver_in_master_is_flagged_with_fixed_score(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR-GHOST"],
            "approver_in_master": pd.Series([False], dtype="boolean"),
            "source": ["Manual"],
            "exceeds_threshold": [False],
        })

        result = b09_skipped_approval(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [0.55]
        assert result.attrs["review_score_series"].tolist() == [0.0]
        assert result.attrs["breakdown"]["unknown_approver_rows"] == 1
        assert result.attrs["breakdown"]["candidate_rows"] == 1
        assert result.attrs["row_annotations"][0]["queue_label"] == "unknown_approver"
        assert result.attrs["row_annotations"][0]["reason_code"] == "unknown_approver"
        assert result.attrs["row_annotations"][0]["bucket"] == "unknown_approver"
        assert result.attrs["row_annotations"][0]["approved_by"] == "APR-GHOST"

    def test_known_approver_in_master_does_not_trigger_unknown_subpattern(self) -> None:
        df = pd.DataFrame({
            "approved_by": ["APR-001"],
            "approver_in_master": pd.Series([True], dtype="boolean"),
            "source": ["Manual"],
            "exceeds_threshold": [True],
        })

        result = b09_skipped_approval(df)

        assert not result.any()
        assert result.attrs["score_series"].tolist() == [0.0]
        assert result.attrs["breakdown"]["unknown_approver_rows"] == 0
        assert result.attrs["breakdown"]["candidate_rows"] == 0

    def test_blank_approver_with_membership_na_keeps_existing_l107_path(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True],
            "source": ["Manual"],
            "approved_by": [""],
            "approver_in_master": pd.Series([pd.NA], dtype="boolean"),
            "approval_date": [None],
        })

        result = b09_skipped_approval(df)

        assert result.tolist() == [True]
        assert result.attrs["breakdown"]["unknown_approver_rows"] == 0
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["row_annotations"][0]["queue_label"] == "immediate"
        assert "unknown_approver" not in result.attrs["row_annotations"][0]["evidence_reasons"]

    def test_missing_approver_membership_column_preserves_existing_output_shape(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [False],
            "source": ["Manual"],
            "approved_by": ["APR-001"],
        })

        result = b09_skipped_approval(df)

        assert not result.any()
        assert result.attrs["score_series"].tolist() == [0.0]
        assert result.attrs["review_score_series"].tolist() == [0.0]
        assert result.attrs["row_annotations"] == {}
        assert "unknown_approver_rows" not in result.attrs["breakdown"]
        assert result.attrs["breakdown"]["candidate_rows"] == 0

    def test_manual_missing_approval_with_extra_evidence_is_immediate(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True],
            "source": ["Manual"],
            "approved_by": [""],
            "approval_date": [None],
        })
        result = b09_skipped_approval(df)
        assert result[0]
        assert result.attrs["score_series"].iloc[0] >= 0.70
        assert result.attrs["score_series"].iloc[0] < 0.85
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["evidence_count_bands"] == {"2": 1}
        assert result.attrs["row_annotations"][0]["queue_label"] == "immediate"
        assert "score_components" in result.attrs["row_annotations"][0]
        assert result.attrs["row_annotations"][0]["evidence_reasons"] == [
            "manual_source",
            "no_approval_date",
        ]

    def test_recurring_missing_approval_is_review_required(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True],
            "source": ["recurring"],
            "approved_by": [""],
            "approval_date": [None],
        })
        result = b09_skipped_approval(df)
        assert result[0]
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert 0.45 <= result.attrs["review_score_series"].iloc[0] < 0.70
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 1
        assert result.attrs["row_annotations"][0]["queue_label"] == "review"
        assert result.attrs["row_annotations"][0]["source_category"] == "non_system_review"

    def test_manual_without_extra_evidence_stays_review_required(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True],
            "source": ["Manual"],
            "approved_by": [""],
        })
        result = b09_skipped_approval(df)
        assert result[0]
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert 0.45 <= result.attrs["review_score_series"].iloc[0] < 0.70
        assert result.attrs["breakdown"]["immediate_rows"] == 0
        assert result.attrs["breakdown"]["review_rows"] == 1
        assert result.attrs["row_annotations"][0]["evidence_count"] == 1

    def test_approval_level_with_manual_evidence_is_confirmed_when_l104_suppressed(
        self,
    ) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [False],
            "approval_level": [1],
            "source": ["Manual"],
            "approved_by": [""],
            "approval_date": [None],
        })

        result = b09_skipped_approval(df)

        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["approval_level_review_rows"] == 1

    def test_system_source_missing_approver_is_low_priority(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True, True],
            "source": ["batch", "interface"],
            "approved_by": ["", ""],
            "approval_date": [None, None],
        })
        result = b09_skipped_approval(df)
        assert result.all()
        assert result.attrs["breakdown"]["allowed_system_rows"] == 2
        assert result.attrs["breakdown"]["low_priority_rows"] == 2
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["review_score_series"].between(0.1, 0.44).all()
        assert result.attrs["row_annotations"][0]["queue_label"] == "low_priority"
        assert result.attrs["row_annotations"][0]["source_category"] == "system_exception"

    def test_missing_approver_without_approval_required_is_low_priority(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [False],
            "source": ["Manual"],
            "approved_by": [""],
            "approval_date": [None],
        })
        result = b09_skipped_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["low_priority_rows"] == 1
        assert result.attrs["breakdown"]["no_approval_required_rows"] == 1
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["review_score_series"].iloc[0] == 0.1
        assert result.attrs["row_annotations"][0]["source_category"] == "not_approval_required"

    def test_repeated_material_manual_missing_approval_scores_as_critical(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "debit_amount": [1_200_000_000.0, 1_100_000_000.0, 1_300_000_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "exceeds_threshold": [True, True, True],
            "approval_level": [3, 3, 3],
            "source": ["Manual", "Manual", "Manual"],
            "approved_by": ["", "", ""],
            "approval_date": [None, None, None],
            "is_manual_je": [True, True, True],
            "business_process": ["TRE", "TRE", "TRE"],
            "created_by": ["user1", "user1", "user1"],
        })

        result = b09_skipped_approval(df)

        assert result.all()
        assert result.attrs["score_series"].ge(0.85).all()
        assert result.attrs["breakdown"]["score_bands"]["critical"] == 3

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b09_skipped_approval(df).any()

    def test_missing_approved_by_column_skip_even_with_other_inputs(self) -> None:
        df = pd.DataFrame({"exceeds_threshold": [True], "source": ["Manual"]})
        assert not b09_skipped_approval(df).any()

    def test_approval_contract_degraded_suppresses_l107_control_failure(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True],
            "source": ["Manual"],
            "approved_by": [""],
            "approval_date": [None],
            "approval_contract_degraded": [True],
        })

        result = b09_skipped_approval(df)

        assert not result.any()
        assert result.attrs["breakdown"]["suppression_reason"] == "approval_contract_degraded"
        assert result.attrs["breakdown"]["rule_id"] == "L1-07"


class TestL3_03:
    def test_intercompany_account_flagged_for_review(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "is_intercompany": [True, True, False],
            "company_code": ["A", "B", "A"],
            "trading_partner": ["B", "", ""],
        })
        result = b10_intercompany_review_signal(df)
        assert result[0]
        assert result[1]
        assert not result[2]
        assert result.attrs["score_series"].tolist() == [0.4, 0.4, 0.0]
        assert result.attrs["breakdown"]["ic_population_rows"] == 2
        assert result.attrs["breakdown"]["ic_population_docs"] == 2
        assert result.attrs["breakdown"]["ic_company_count"] == 2
        assert result.attrs["breakdown"]["trading_partner_coverage_ratio"] == 0.5
        assert result.attrs["row_annotations"][0]["signal_category"] == "ic_population"

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
