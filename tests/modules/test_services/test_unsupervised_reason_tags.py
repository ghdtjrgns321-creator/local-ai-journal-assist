"""Unit tests for PHASE2 unsupervised reason tag loader.

Lock: 본 매핑은 표시 전용. score / threshold / ranking 에 사용 금지.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.services.unsupervised_reason_tags import (
    EVIDENCE_TYPE,
    FALLBACK_LABEL_KO,
    FALLBACK_TAG,
    ReasonTagIndex,
    load_reason_tags,
    resolve_tag,
)


def test_load_reason_tags_from_default_config_returns_seven_mappings_plus_fallback():
    index = load_reason_tags()
    assert isinstance(index, ReasonTagIndex)
    assert len(index.mappings) == 7
    assert index.fallback.tag == FALLBACK_TAG
    assert index.fallback.label_ko == FALLBACK_LABEL_KO
    assert index.fallback.evidence_type == EVIDENCE_TYPE
    # 모든 매핑이 statistical_outlier evidence_type 고정.
    assert all(entry.evidence_type == EVIDENCE_TYPE for entry in index.mappings)


def test_exact_match_returns_specific_tag():
    # config 의 round_amount 매핑 정확 일치.
    tag = resolve_tag("round_amount")
    assert tag.tag == "round_amount_deviation"
    assert tag.label_ko == "금액 패턴 이상"
    assert tag.evidence_type == EVIDENCE_TYPE


def test_prefix_match_after_normalizing_columntransformer_prefix():
    # ColumnTransformer 산출 prefix `num__` 제거 후 매칭.
    tag = resolve_tag("num__posting_lag_days")
    assert tag.tag == "posting_lag_anomaly"
    assert tag.label_ko == "전기 지연 패턴 이상"


def test_prefix_match_when_feature_has_additional_suffix():
    # `amount_z_score` 는 `amount_z` 로 시작 → prefix 매칭.
    tag = resolve_tag("amount_z_score")
    assert tag.tag == "amount_outlier"


def test_contains_match_when_feature_embeds_key_token():
    # `posting_date_weekend` 는 `flag_posting_date_weekend_indicator` 에 contains 됨.
    tag = resolve_tag("flag_posting_date_weekend_indicator")
    assert tag.tag == "unusual_timing"
    assert tag.label_ko == "비정상 거래시점"


def test_unknown_feature_falls_back_to_feature_pattern_outlier():
    tag = resolve_tag("some_unmapped_feature_name")
    assert tag.tag == FALLBACK_TAG
    assert tag.label_ko == FALLBACK_LABEL_KO


def test_empty_feature_name_returns_fallback():
    tag = resolve_tag("")
    assert tag.tag == FALLBACK_TAG


def test_load_reason_tags_rejects_empty_mappings(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.safe_dump({"mappings": [], "fallback": {"tag": "x", "label_ko": "y"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mappings"):
        load_reason_tags(bad)


def test_load_reason_tags_rejects_duplicate_feature_key(tmp_path: Path):
    bad = tmp_path / "dup.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "mappings": [
                    {"feature_key": "x", "tag": "a", "label_ko": "A"},
                    {"feature_key": "x", "tag": "b", "label_ko": "B"},
                ],
                "fallback": {"tag": "z", "label_ko": "Z"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_reason_tags(bad)


def test_load_reason_tags_rejects_missing_required_field(tmp_path: Path):
    bad = tmp_path / "missing.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "mappings": [{"feature_key": "x", "tag": "a"}],  # label_ko 누락
                "fallback": {"tag": "z", "label_ko": "Z"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="label_ko"):
        load_reason_tags(bad)


def test_case_insensitive_feature_key_normalization(tmp_path: Path):
    """yaml feature_key 는 lower-case 로 저장되며, 대소문자 다른 feature 도 매칭."""
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "mappings": [
                    {
                        "feature_key": "Amount_Z",  # loader 가 lower 로 정규화
                        "tag": "amount_outlier",
                        "label_ko": "금액 규모 이상",
                    }
                ],
                "fallback": {"tag": "feature_pattern_outlier", "label_ko": "피처 패턴 이상"},
            }
        ),
        encoding="utf-8",
    )
    index = load_reason_tags(cfg)
    tag = index.resolve("AMOUNT_Z")  # upper-case 도 매칭
    assert tag.tag == "amount_outlier"
