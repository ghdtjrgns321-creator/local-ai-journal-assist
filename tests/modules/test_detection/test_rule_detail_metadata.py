from __future__ import annotations

from dataclasses import replace

from src.detection.rule_detail_metadata import (
    RULE_DETAIL_METADATA_REGISTRY,
    ColumnSources,
    PresenterSurface,
    RuleStatus,
    ScoringRole,
    can_generate_standalone_violation_copy,
    can_render_row_violation_detail,
    canonicalize_rule_id,
    get_canonical_transaction_rule_ids,
    get_rule_detail_metadata,
    include_in_l1_l4_transaction_count,
    validate_rule_detail_metadata_registry,
)

EXPECTED_RULE_IDS = {
    "L1-01",
    "L1-02",
    "L1-03",
    "L1-04",
    "L1-05",
    "L1-06",
    "L1-07",
    "L1-08",
    "L1-09",
    "L2-01",
    "L2-02",
    "L2-03",
    "L2-03a",
    "L2-03b",
    "L2-03c",
    "L2-03d",
    "L2-04",
    "L2-05",
    "L3-01",
    "L3-02",
    "L3-03",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-07",
    "L3-08",
    "L3-09",
    "L3-10",
    "L3-11",
    "L3-12",
    "L4-01",
    "L4-02",
    "L4-03",
    "L4-04",
    "L4-05",
    "L4-06",
    "Benford",
    "D01",
    "D02",
    "IC01",
    "IC02",
    "IC03",
    "GR01",
    "GR03",
}


def test_enum_contract_values_are_locked() -> None:
    assert {item.value for item in RuleStatus} == {
        "active",
        "macro",
        "sidecar",
        "alias",
        "internal_reason_code",
    }
    assert {item.value for item in PresenterSurface} == {
        "transaction_detail",
        "context_badge",
        "account_process_macro",
        "intercompany_sidecar",
        "graph_sidecar",
        "drilldown_reason",
    }
    assert {item.value for item in ScoringRole} == {
        "primary",
        "booster",
        "combo_only",
        "macro_only",
    }


def test_registry_coverage_and_required_v1_fields() -> None:
    assert set(RULE_DETAIL_METADATA_REGISTRY) == EXPECTED_RULE_IDS
    assert validate_rule_detail_metadata_registry() == []

    for rule_id, metadata in RULE_DETAIL_METADATA_REGISTRY.items():
        assert metadata.rule_id == rule_id
        assert metadata.canonical_rule_id
        assert metadata.status in RuleStatus
        assert metadata.presenter_surface in PresenterSurface
        assert metadata.scoring_role in ScoringRole
        assert metadata.display_copy.display_title
        assert isinstance(metadata.secondary_topics, tuple)
        assert isinstance(metadata.column_sources.required_ledger_columns, tuple)
        assert isinstance(metadata.column_sources.optional_ledger_columns, tuple)
        assert isinstance(metadata.column_sources.derived_columns, tuple)
        assert isinstance(metadata.column_sources.sidecar_output_columns, tuple)
        assert isinstance(metadata.column_sources.macro_output_columns, tuple)


def test_canonicalization_policy() -> None:
    for rule_id in ("L2-03a", "L2-03b", "L2-03c", "L2-03d"):
        assert canonicalize_rule_id(rule_id) == "L2-03"
        assert get_rule_detail_metadata(rule_id).canonical_rule_id == "L2-03"

    assert canonicalize_rule_id("Benford") == "L4-02"
    assert get_rule_detail_metadata("Benford").canonical_rule_id == "L4-02"
    assert canonicalize_rule_id("L1-01") == "L1-01"


def test_canonical_transaction_count_is_32() -> None:
    canonical_rule_ids = get_canonical_transaction_rule_ids()

    assert len(canonical_rule_ids) == 32
    assert len(set(canonical_rule_ids)) == 32


def test_row_detail_eligibility_is_surface_and_flag_gated() -> None:
    assert can_render_row_violation_detail("L1-01") is True
    assert can_render_row_violation_detail("L2-03") is True

    for rule_id, metadata in RULE_DETAIL_METADATA_REGISTRY.items():
        expected = (
            metadata.presenter_surface == PresenterSurface.TRANSACTION_DETAIL
            and metadata.allow_row_violation_detail
        )
        assert can_render_row_violation_detail(rule_id) is expected

    for surface_rule in (
        "L3-03",
        "L3-05",
        "L4-02",
        "IC01",
        "GR01",
        "L2-03a",
    ):
        assert can_render_row_violation_detail(surface_rule) is False


def test_standalone_violation_copy_is_forbidden_for_locked_context_rules() -> None:
    for rule_id in ("L3-05", "L3-06", "L3-08", "L3-10", "L3-12", "L4-05", "L4-06"):
        assert can_generate_standalone_violation_copy(rule_id) is False

    for rule_id in ("L1-01", "L2-02", "L4-03"):
        assert can_generate_standalone_violation_copy(rule_id) is True


def test_required_ledger_columns_validate_against_schema(monkeypatch) -> None:
    assert validate_rule_detail_metadata_registry() == []

    broken = replace(
        get_rule_detail_metadata("L1-01"),
        column_sources=ColumnSources(required_ledger_columns=("not_in_schema",)),
    )
    monkeypatch.setitem(RULE_DETAIL_METADATA_REGISTRY, "L1-01", broken)

    errors = validate_rule_detail_metadata_registry()

    assert any("not_in_schema" in error for error in errors)


def test_l402_counted_but_not_row_detail() -> None:
    assert include_in_l1_l4_transaction_count("L4-02") is True
    assert "L4-02" in get_canonical_transaction_rule_ids()
    assert can_render_row_violation_detail("L4-02") is False


def test_alias_reason_macro_and_sidecar_rules_do_not_increase_count() -> None:
    excluded_rule_ids = (
        "Benford",
        "L2-03a",
        "L2-03b",
        "L2-03c",
        "L2-03d",
        "D01",
        "D02",
        "IC01",
        "IC02",
        "IC03",
        "GR01",
        "GR03",
    )

    for rule_id in excluded_rule_ids:
        assert include_in_l1_l4_transaction_count(rule_id) is False

    canonical_rule_ids = get_canonical_transaction_rule_ids()
    assert "Benford" not in canonical_rule_ids
    assert all(rule_id not in canonical_rule_ids for rule_id in excluded_rule_ids)
