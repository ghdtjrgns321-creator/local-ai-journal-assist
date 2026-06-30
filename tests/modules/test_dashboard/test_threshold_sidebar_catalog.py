"""감사인/관리자 설정 노출 범위 테스트."""

from dashboard.components.threshold_sidebar import admin_field_names, auditor_field_names


def test_auditor_settings_expose_business_context_and_tuning_only():
    fields = auditor_field_names()

    assert "approval_thresholds" in fields
    assert "period_end_margin_days" in fields
    assert "normal_hours_start" in fields
    assert "normal_hours_end" in fields
    assert "near_threshold_ratio" in fields
    assert "duplicate_payment_window_days" in fields
    assert "benford_mad_threshold" in fields


def test_internal_statistics_are_admin_only():
    auditor_fields = auditor_field_names()
    admin_fields = admin_field_names()

    for field in {
        "zscore_threshold",
        "abnormal_sigma_threshold",
        "sod_process_threshold",
        "rare_account_pair_cadence_per_quarter",
        "min_abnormal_ratio",
        "min_user_entries",
        "reversal_score_threshold",
    }:
        assert field in admin_fields
        assert field not in auditor_fields


def test_auditor_and_admin_catalogs_do_not_overlap():
    assert auditor_field_names().isdisjoint(admin_field_names())
