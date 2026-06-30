"""Unit tests for access-control rules L1-05, L1-06, L1-07, L3-03."""

from __future__ import annotations

import pandas as pd

from src.detection.fraud_rules_access import (
    b06_self_approval,
    b07_segregation_of_duties,
    b09_skipped_approval,
    b09b_unknown_approver,
    b10_intercompany_review_signal,
    b13_estimate_account_use,
    b14_work_scope_excess_review,
)


class TestL3_10:
    def test_estimate_account_keyword_and_code_flagged(self) -> None:
        # account_name 키워드(1차) + 코드(2차) 매칭. 현금·매출은 비발화.
        df = pd.DataFrame(
            {
                "gl_account": ["109", "1190", "5100", None],
                "account_name": ["대손충당금", "", "상품매출", "현금"],
            }
        )
        rules = {
            "patterns": {
                "estimate_account_use": {
                    "account_name_keywords": ["대손충당금", "충당부채"],
                    "accounts": ["1190"],
                    "account_prefixes": [],
                }
            }
        }
        assert b13_estimate_account_use(df, audit_rules=rules).tolist() == [
            True,
            True,
            False,
            False,
        ]

    def test_estimate_account_prefix_code_flagged(self) -> None:
        df = pd.DataFrame({"gl_account": ["1115", "5100"]})
        rules = {
            "patterns": {
                "estimate_account_use": {
                    "account_name_keywords": [],
                    "accounts": [],
                    "account_prefixes": ["111"],
                }
            }
        }
        assert b13_estimate_account_use(df, audit_rules=rules).tolist() == [True, False]

    def test_estimate_account_match_annotations_factual_only(self) -> None:
        # binary 전환: signal_category/category_reason 폐기, 사실값(match_type/value/group)만.
        df = pd.DataFrame(
            {
                "gl_account": ["109", "1190"],
                "account_name": ["대손충당금", ""],
            },
            index=[10, 11],
        )
        rules = {
            "patterns": {
                "estimate_account_use": {
                    "account_name_keywords": ["대손충당금"],
                    "accounts": ["1190"],
                    "account_prefixes": [],
                    "estimate_account_groups": {
                        "allowance_impairment": {"keywords": ["대손충당금"]},
                    },
                }
            }
        }

        result = b13_estimate_account_use(df, audit_rules=rules)

        assert result.attrs["row_annotations"] == {
            10: {
                "match_type": "keyword",
                "matched_value": "대손충당금",
                "matched_group": "allowance_impairment",
            },
            11: {
                "match_type": "exact",
                "matched_value": "1190",
                "matched_group": "",
            },
        }

    def test_estimate_account_binary_score_series_and_breakdown(self) -> None:
        # 정황 차등(0.65/0.35/0.20) 폐기 → 발화 전부 1.0.
        df = pd.DataFrame(
            {
                "gl_account": ["109", "109", "5100"],
                "account_name": ["대손충당금", "대손충당금", "상품매출"],
                "source": ["manual", "automated", "manual"],
            }
        )
        rules = {"patterns": {"estimate_account_use": {"account_name_keywords": ["대손충당금"]}}}

        result = b13_estimate_account_use(df, audit_rules=rules)

        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 0.0]
        assert result.attrs["breakdown"] == {
            "flagged_rows": 2,
            "reason_counts": {"keyword": 2, "exact": 0, "prefix": 0},
        }

    def test_missing_gl_account_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [1.0]})
        assert not b13_estimate_account_use(df).any()


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
                "gl_account": ["109", "5100", "4100", "1100"],
                # L3-12 sensitive_account reason은 추정계정(L3-10과 공유 정의)에서 발화한다.
                "account_name": ["대손충당금", "상품매출", "매출원가", "현금"],
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
        df = pd.DataFrame(
            {
                "created_by": ["USR-JA-001"],
                "approved_by": ["USR-JA-001"],
                "user_persona": ["junior_accountant"],
                "debit_amount": [5_000_000.0],
                "credit_amount": [0.0],
            }
        )
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["score_series"].iloc[0] == 1.0
        assert result.attrs["row_annotations"][0]["bucket"] == "binary_flag"

    def test_default_allowed_system_persona_excluded(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["SYSTEM"],
                "approved_by": ["SYSTEM"],
                "user_persona": ["automated_system"],
            }
        )
        result = b06_self_approval(df)
        assert not result[0]
        assert result.attrs["breakdown"]["candidate_rows"] == 0
        assert result.attrs["breakdown"]["actionable_rows"] == 0
        assert result.attrs["breakdown"]["allowed_system_rows"] == 1
        assert result.attrs["breakdown"]["bucket_counts"] == {"trusted_system_excluded": 1}
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["review_score_series"].iloc[0] == 0.0
        assert result.attrs["row_annotations"][0]["bucket"] == "trusted_system_excluded"

    def test_default_allowed_system_source_excluded(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["BATCHUSER"],
                "approved_by": ["BATCHUSER"],
                "source": ["automated"],
            }
        )
        result = b06_self_approval(df)
        assert not result[0]
        assert result.attrs["breakdown"]["candidate_rows"] == 0
        assert result.attrs["breakdown"]["actionable_rows"] == 0
        assert result.attrs["breakdown"]["allowed_system_rows"] == 1
        assert result.attrs["score_series"].iloc[0] == 0.0
        assert result.attrs["row_annotations"][0]["bucket"] == "trusted_system_excluded"

    def test_lone_automated_source_self_approval_is_not_allowed_system(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1"],
                "created_by": ["BATCHUSER"],
                "approved_by": ["BATCHUSER"],
                "source": ["automated"],
                "posting_date": pd.to_datetime(["2025-01-02"]),
                "batch_id": [None],
                "job_id": [None],
            }
        )

        result = b06_self_approval(df)

        assert result[0]
        assert result.attrs["breakdown"]["actionable_rows"] == 1
        assert result.attrs["breakdown"]["allowed_system_rows"] == 0
        assert result.attrs["score_series"].iloc[0] == 1.0
        assert result.attrs["row_annotations"][0]["bucket"] == "binary_flag"

    def test_partial_identity_automated_source_self_approval_is_lone(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1"],
                "created_by": ["BATCHUSER"],
                "approved_by": ["BATCHUSER"],
                "source": ["automated"],
                "posting_date": pd.to_datetime(["2025-01-02"]),
                "batch_id": ["BATCH-1"],
                "job_id": [None],
            }
        )

        result = b06_self_approval(df)

        assert result[0]
        assert result.attrs["breakdown"]["actionable_rows"] == 1
        assert result.attrs["breakdown"]["allowed_system_rows"] == 0
        assert result.attrs["score_series"].iloc[0] == 1.0
        assert result.attrs["row_annotations"][0]["bucket"] == "binary_flag"

    def test_missing_identity_columns_use_lone_branch_for_self_approval(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1"],
                "created_by": ["BATCHUSER"],
                "approved_by": ["BATCHUSER"],
                "source": ["automated"],
                "posting_date": pd.to_datetime(["2025-01-02"]),
            }
        )

        result = b06_self_approval(df)

        assert result[0]
        assert result.attrs["breakdown"]["actionable_rows"] == 1
        assert result.attrs["breakdown"]["allowed_system_rows"] == 0
        assert result.attrs["score_series"].iloc[0] == 1.0
        assert result.attrs["row_annotations"][0]["bucket"] == "binary_flag"

    def test_r2r_self_approval_is_binary_flag(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["CTRL-001"],
                "approved_by": ["CTRL-001"],
                "user_persona": ["controller"],
                "document_type": ["SA"],
                "business_process": ["R2R"],
            }
        )
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["score_series"].iloc[0] == 1.0
        assert result.attrs["review_score_series"].iloc[0] == 0.0
        assert result.attrs["row_annotations"][0]["bucket"] == "binary_flag"

    def test_r2r_large_manual_self_approval_is_binary_flag(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["CTRL-001"],
                "approved_by": ["CTRL-001"],
                "business_process": ["R2R"],
                "source": ["manual"],
                "debit_amount": [2_000_000_000.0],
                "credit_amount": [0.0],
            }
        )
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["override_counts"] == {}
        assert result.attrs["score_series"].iloc[0] == 1.0
        assert result.attrs["row_annotations"][0]["bucket"] == "binary_flag"

    def test_r2r_after_hours_self_approval_is_binary_flag(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["CTRL-001"],
                "approved_by": ["CTRL-001"],
                "business_process": ["R2R"],
                "is_after_hours": [True],
            }
        )
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["override_counts"] == {}
        assert result.attrs["row_annotations"][0]["bucket"] == "binary_flag"

    def test_r2r_high_risk_account_self_approval_is_binary_flag(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["CTRL-001"],
                "approved_by": ["CTRL-001"],
                "business_process": ["R2R"],
                "gl_account": ["1190"],
            }
        )
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["breakdown"]["override_counts"] == {}
        assert result.attrs["row_annotations"][0]["bucket"] == "binary_flag"

    def test_o2c_self_approval_defaults_to_immediate(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["CTRL-001"],
                "approved_by": ["CTRL-001"],
                "user_persona": ["controller"],
                "document_type": ["SA"],
                "business_process": ["O2C"],
            }
        )
        result = b06_self_approval(df)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["score_series"].iloc[0] == 1.0

    def test_review_process_config_no_longer_changes_binary_score(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["CTRL-001"],
                "approved_by": ["CTRL-001"],
                "business_process": ["TRE"],
            }
        )
        rules = {
            "patterns": {
                "self_approval_review": {
                    "business_processes": ["TRE"],
                }
            }
        }
        result = b06_self_approval(df, audit_rules=rules)
        assert result[0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["score_series"].iloc[0] == 1.0
        assert result.attrs["review_score_series"].iloc[0] == 0.0

    def test_observed_summary_groups_results_for_queue_review(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "created_by": ["Kim", "Kim", "Lee"],
                "approved_by": ["Kim", "Kim", "Lee"],
                "business_process": ["P2P", "P2P", "R2R"],
                "posting_date": ["2024-09-01", "2024-09-15", "2024-12-28"],
                "source": ["manual", "manual", "manual"],
                "debit_amount": [100_000.0, 200_000.0, 300_000.0],
                "credit_amount": [0.0, 0.0, 0.0],
            }
        )
        result = b06_self_approval(df)
        summary = result.attrs["breakdown"]["observed_summary"]

        assert summary["group_key"] == ["created_by", "business_process", "posting_month"]
        assert summary["queue_counts"]["operational_immediate"] == 2
        assert summary["queue_counts"]["general_immediate"] == 1
        top_group = summary["top_groups"][0]
        assert top_group["created_by"] == "Kim"
        assert top_group["business_process"] == "P2P"
        assert top_group["posting_month"] == "2024-09"
        assert top_group["total_docs"] == 2

    def test_missing_approved_by_is_not_l105(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["User1"],
                "source": ["Manual"],
            }
        )
        assert not b06_self_approval(df).any()

    def test_no_created_by_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b06_self_approval(df).any()

    def test_null_persona_still_evaluated(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["User1"],
                "approved_by": ["User1"],
                "user_persona": [None],
                "debit_amount": [50_000_000.0],
                "credit_amount": [0.0],
            }
        )
        result = b06_self_approval(df)
        assert result[0]


class TestL1_06:
    def test_red_toxic_pair_scores_binary(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["A", "A", "B", "B"],
                "business_process": ["TRE", "P2P", "P2P", "O2C"],
            }
        )
        result = b07_segregation_of_duties(df)
        assert result.tolist() == [True, True, False, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 0.0, 0.0]
        assert result.attrs["breakdown"]["red_rows"] == 2
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["row_annotations"][0]["signal_class"] == "red"
        assert result.attrs["row_annotations"][0]["toxic_pair"] == ["P2P", "TRE"]

    def test_yellow_toxic_pair_is_annotation_only(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["C1"] * 2,
                "business_process": ["R2R", "P2P"],
            }
        )
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["review_score_series"].eq(0.0).all()
        assert result.attrs["breakdown"]["yellow_rows"] == 2
        assert result.attrs["row_annotations"][0]["signal_class"] == "yellow"
        assert result.attrs["row_annotations"][0]["toxic_pair"] == ["P2P", "R2R"]

    def test_within_process_p2p_and_tre_single_process_are_red(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["P_USER", "T_USER", "R_USER"],
                "approved_by": ["P_USER", "T_USER", "R_USER"],
                "business_process": ["P2P", "TRE", "R2R"],
            }
        )
        result = b07_segregation_of_duties(df)
        assert result.tolist() == [True, True, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 0.0]
        assert result.attrs["row_annotations"][0]["toxic_pair"] == ["P2P"]
        assert result.attrs["row_annotations"][1]["toxic_pair"] == ["TRE"]

    def test_injected_label_columns_are_ignored(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["A", "B"],
                "business_process": ["R2R", "O2C"],
                "sod_violation": [True, True],
                "sod_conflict_type": ["cash_disbursement", "preparer_approver"],
            }
        )
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()

    def test_automated_source_excluded_from_sod(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["AUTOUSER"] * 8,
                "business_process": ["TRE", "P2P"] * 4,
                "source": ["automated", "batch", "system", "interface"] * 2,
            }
        )
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["breakdown"]["excluded_system_rows"] == 8

    def test_automated_persona_and_system_actor_excluded_from_sod(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": [
                    "HUMAN_AUTO_PERSONA",
                    "HUMAN_AUTO_PERSONA",
                    "SVC_BATCH",
                    "SVC_BATCH",
                ],
                "business_process": ["TRE", "P2P", "TRE", "P2P"],
                "user_persona": [
                    "automated_system",
                    "automated_system",
                    "senior_accountant",
                    "senior_accountant",
                ],
            }
        )
        result = b07_segregation_of_duties(df)
        assert not result.any()
        assert result.attrs["score_series"].eq(0.0).all()
        assert result.attrs["breakdown"]["excluded_system_rows"] == 4

    def test_human_toxic_pair_still_scores_red(self) -> None:
        df = pd.DataFrame(
            {
                "created_by": ["HUMAN_USER", "HUMAN_USER"],
                "business_process": ["TRE", "P2P"],
                "user_persona": ["senior_accountant", "senior_accountant"],
                "source": ["manual", "manual"],
            }
        )
        result = b07_segregation_of_duties(df)
        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0]
        assert result.attrs["breakdown"]["excluded_system_rows"] == 0

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"created_by": ["A"]})
        assert not b07_segregation_of_duties(df).any()


class TestL1_07:
    def test_blank_approver_scores_binary_one(self) -> None:
        df = pd.DataFrame(
            {
                "approved_by": [""],
                "approver_in_master": pd.Series([pd.NA], dtype="boolean"),
                "source": ["Manual"],
                "exceeds_threshold": [False],
            }
        )

        result = b09_skipped_approval(df)
        ghost = b09b_unknown_approver(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [1.0]
        assert result.attrs["review_score_series"].tolist() == [0.0]
        assert result.attrs["breakdown"]["blank_approved_by_rows"] == 1
        assert result.attrs["row_annotations"][0]["reason_code"] == "blank_approved_by"
        assert ghost.tolist() == [False]
        assert ghost.attrs["score_series"].tolist() == [0.0]

    def test_unknown_approver_moved_to_l10702_binary(self) -> None:
        df = pd.DataFrame(
            {
                "approved_by": ["APR-GHOST"],
                "approver_in_master": pd.Series([False], dtype="boolean"),
                "source": ["Manual"],
                "exceeds_threshold": [False],
            }
        )

        skipped = b09_skipped_approval(df)
        result = b09b_unknown_approver(df)

        assert skipped.tolist() == [False]
        assert skipped.attrs["score_series"].tolist() == [0.0]
        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [1.0]
        assert result.attrs["review_score_series"].tolist() == [0.0]
        assert result.attrs["breakdown"]["unknown_approver_rows"] == 1
        assert result.attrs["row_annotations"][0]["approved_by"] == "APR-GHOST"

    def test_known_approver_in_master_does_not_trigger_l107_or_l10702(self) -> None:
        df = pd.DataFrame(
            {
                "approved_by": ["APR-001"],
                "approver_in_master": pd.Series([True], dtype="boolean"),
                "source": ["Manual"],
                "exceeds_threshold": [True],
            }
        )

        skipped = b09_skipped_approval(df)
        ghost = b09b_unknown_approver(df)

        assert not skipped.any()
        assert skipped.attrs["score_series"].tolist() == [0.0]
        assert not ghost.any()
        assert ghost.attrs["score_series"].tolist() == [0.0]
        assert ghost.attrs["breakdown"]["unknown_approver_rows"] == 0

    def test_missing_approver_membership_column_gracefully_false_for_l10702(self) -> None:
        df = pd.DataFrame(
            {
                "approved_by": ["APR-001"],
                "source": ["Manual"],
            }
        )

        result = b09b_unknown_approver(df)

        assert not result.any()
        assert result.attrs["score_series"].tolist() == [0.0]
        assert result.attrs["breakdown"]["coverage_degraded"] == "approver_in_master_missing"

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b09_skipped_approval(df).any()
        assert not b09b_unknown_approver(df).any()

    def test_approval_contract_degraded_suppresses_l107_and_l10702(self) -> None:
        df = pd.DataFrame(
            {
                "approved_by": ["", "APR-GHOST"],
                "approver_in_master": pd.Series([pd.NA, False], dtype="boolean"),
                "approval_contract_degraded": [True, True],
            }
        )

        skipped = b09_skipped_approval(df)
        ghost = b09b_unknown_approver(df)

        assert not skipped.any()
        assert skipped.attrs["breakdown"]["rule_id"] == "L1-07"
        assert not ghost.any()
        assert ghost.attrs["breakdown"]["rule_id"] == "L1-07-02"


class TestL3_03:
    def test_intercompany_account_flagged_for_review(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "is_intercompany": [True, True, False],
                "company_code": ["A", "B", "A"],
                "trading_partner": ["B", "", ""],
            }
        )
        result = b10_intercompany_review_signal(df)
        assert result[0]
        assert result[1]
        assert not result[2]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 0.0]
        assert set(result.attrs["score_series"].unique()) == {0.0, 1.0}
        assert result.attrs["breakdown"]["ic_population_rows"] == 2
        assert result.attrs["breakdown"]["ic_population_docs"] == 2
        assert result.attrs["breakdown"]["ic_company_count"] == 2
        assert result.attrs["breakdown"]["trading_partner_coverage_ratio"] == 0.5
        assert result.attrs["row_annotations"][0]["signal_category"] == "ic_population"
        assert result.attrs["row_annotations"][0]["score"] == 1.0

    def test_intercompany_prefix_derives_binary_review_signal(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "gl_account": ["1150-001", "4100"],
                "company_code": ["A", "A"],
            }
        )

        result = b10_intercompany_review_signal(df)

        assert result.tolist() == [True, False]
        assert result.attrs["score_series"].tolist() == [1.0, 0.0]
        assert set(result.attrs["score_series"].unique()) == {0.0, 1.0}

    def test_single_company_intercompany_account_still_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "is_intercompany": [True, False],
                "company_code": ["A", "A"],
            }
        )
        result = b10_intercompany_review_signal(df)
        assert result[0]
        assert not result[1]

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b10_intercompany_review_signal(df).any()
