"""Disk-backed cache for feature-generated DataFrames."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import PROJECT_ROOT, AuditSettings
from src.ingest.datasynth_labels import get_source_path

CACHE_SCHEMA_VERSION = "feature-cache-v1"
_CACHE_SETTING_EXCLUDES = {"enable_feature_cache", "feature_cache_dir"}


@dataclass(frozen=True)
class FeatureCacheKey:
    key: str
    input_fingerprint: str
    config_fingerprint: str
    source_kind: str


def build_feature_cache_key(
    df: pd.DataFrame,
    *,
    settings: AuditSettings,
    rules: dict | None,
    risk_keywords: dict | None,
) -> FeatureCacheKey:
    """Build a deterministic cache key for the current feature inputs."""

    input_fingerprint, source_kind = _input_fingerprint(df)
    config_fingerprint = _config_fingerprint(
        settings=settings,
        rules=rules,
        risk_keywords=risk_keywords,
    )
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "input": input_fingerprint,
        "config": config_fingerprint,
    }
    key = _json_hash(payload)
    return FeatureCacheKey(
        key=key,
        input_fingerprint=input_fingerprint,
        config_fingerprint=config_fingerprint,
        source_kind=source_kind,
    )


def feature_cache_path(settings: AuditSettings, cache_key: FeatureCacheKey) -> Path:
    """Return the parquet artifact path for a feature cache key."""

    cache_dir = Path(settings.feature_cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir
    return cache_dir / f"{cache_key.key}.parquet"


def load_feature_cache(
    df: pd.DataFrame,
    *,
    settings: AuditSettings,
    rules: dict | None,
    risk_keywords: dict | None,
) -> tuple[pd.DataFrame | None, FeatureCacheKey]:
    """Load a feature cache entry if it exists and can be read."""

    cache_key = build_feature_cache_key(
        df,
        settings=settings,
        rules=rules,
        risk_keywords=risk_keywords,
    )
    path = feature_cache_path(settings, cache_key)
    if not path.exists():
        return None, cache_key

    try:
        cached = pd.read_parquet(path)
    except Exception:
        return None, cache_key

    if "morpheme_tokens" in cached.columns:
        cached["morpheme_tokens"] = cached["morpheme_tokens"].map(_list_like_to_list)
    cached.attrs.clear()
    cached.attrs.update(df.attrs)
    return cached, cache_key


def save_feature_cache(
    df: pd.DataFrame,
    *,
    settings: AuditSettings,
    cache_key: FeatureCacheKey,
) -> Path | None:
    """Persist a feature-generated DataFrame as parquet."""

    path = feature_cache_path(settings, cache_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=True)
    except Exception:
        return None
    return path


def _input_fingerprint(df: pd.DataFrame) -> tuple[str, str]:
    source_path = get_source_path(df)
    if source_path is not None and source_path.exists():
        stat = source_path.stat()
        payload = {
            "kind": "source_path",
            "path": str(source_path.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "columns": list(df.columns),
            "dtypes": {column: str(dtype) for column, dtype in df.dtypes.items()},
            "shape": list(df.shape),
        }
        return _json_hash(payload), "source_path"

    payload = {
        "kind": "dataframe",
        "columns": list(df.columns),
        "dtypes": {column: str(dtype) for column, dtype in df.dtypes.items()},
        "shape": list(df.shape),
        "index": _series_digest(pd.Series(df.index.astype(str), index=df.index)),
        "values": _series_digest(pd.util.hash_pandas_object(df, index=True, categorize=True)),
    }
    return _json_hash(payload), "dataframe"


def _config_fingerprint(
    *,
    settings: AuditSettings,
    rules: dict | None,
    risk_keywords: dict | None,
) -> str:
    settings_payload = {
        key: value
        for key, value in settings.model_dump(mode="json").items()
        if key not in _CACHE_SETTING_EXCLUDES
    }
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "settings": settings_payload,
        "rules": rules or {},
        "risk_keywords": risk_keywords or {},
    }
    return _json_hash(payload)


def _series_digest(series: pd.Series) -> str:
    values = pd.util.hash_pandas_object(series, index=True, categorize=True).to_numpy("uint64")
    h = hashlib.sha256()
    h.update(values.tobytes())
    return h.hexdigest()


def _list_like_to_list(value: object) -> object:
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        return value.tolist()
    return value


def _json_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
