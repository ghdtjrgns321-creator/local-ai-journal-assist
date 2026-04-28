"""Feature cache tests."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd

from config.settings import AuditSettings
from src.feature.cache import (
    build_feature_cache_key,
    load_feature_cache,
    save_feature_cache,
)


def _cache_dir() -> Path:
    path = Path(".tmp_feature_cache_tests") / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def _df() -> pd.DataFrame:
    return pd.DataFrame({
        "document_id": ["D1", "D2"],
        "debit_amount": [100.0, 0.0],
        "credit_amount": [0.0, 100.0],
        "posting_date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
    })


def test_feature_cache_roundtrip():
    settings = AuditSettings(feature_cache_dir=str(_cache_dir()))
    df = _df()
    df.attrs["source_path"] = "source.csv"
    featured = df.assign(is_manual_je=[True, False])
    featured.attrs["source_path"] = "source.csv"

    cache_key = build_feature_cache_key(
        df,
        settings=settings,
        rules={"patterns": {"manual_source_codes": ["manual"]}},
        risk_keywords={"keywords": ["risk"]},
    )
    saved = save_feature_cache(featured, settings=settings, cache_key=cache_key)

    assert saved is not None
    loaded, loaded_key = load_feature_cache(
        df,
        settings=settings,
        rules={"patterns": {"manual_source_codes": ["manual"]}},
        risk_keywords={"keywords": ["risk"]},
    )

    assert loaded_key == cache_key
    assert loaded is not None
    assert list(loaded.columns) == list(featured.columns)
    assert loaded.attrs["source_path"] == "source.csv"


def test_feature_cache_key_changes_when_settings_change():
    df = _df()
    cache_dir = _cache_dir()
    settings_a = AuditSettings(feature_cache_dir=str(cache_dir), period_end_margin_days=5)
    settings_b = AuditSettings(feature_cache_dir=str(cache_dir), period_end_margin_days=10)

    key_a = build_feature_cache_key(df, settings=settings_a, rules={}, risk_keywords={})
    key_b = build_feature_cache_key(df, settings=settings_b, rules={}, risk_keywords={})

    assert key_a.key != key_b.key


def test_feature_cache_key_ignores_cache_directory():
    df = _df()
    cache_dir = _cache_dir()
    settings_a = AuditSettings(feature_cache_dir=str(cache_dir / "a"))
    settings_b = AuditSettings(feature_cache_dir=str(cache_dir / "b"))

    key_a = build_feature_cache_key(df, settings=settings_a, rules={}, risk_keywords={})
    key_b = build_feature_cache_key(df, settings=settings_b, rules={}, risk_keywords={})

    assert key_a.key == key_b.key
