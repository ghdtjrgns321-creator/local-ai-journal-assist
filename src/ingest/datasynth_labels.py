"""Helpers for DataSynth ground-truth sidecar labels."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

SOURCE_PATH_ATTR = "source_path"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATASYNTH_DIR = _PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth"
_YEAR_FILE_RE = re.compile(r"^journal_entries_(\d{4})\.csv$", re.IGNORECASE)
_LABEL_COLUMNS = frozenset({
    "is_fraud",
    "fraud_type",
    "is_anomaly",
    "anomaly_type",
    "sod_violation",
    "sod_conflict_type",
    "label",
    "target",
})


def set_source_path(df: pd.DataFrame, source_path: str | Path) -> pd.DataFrame:
    """Store the original source path in dataframe attrs."""
    out = df.copy()
    resolved = resolve_datasynth_source_hint(source_path)
    out.attrs[SOURCE_PATH_ATTR] = str(resolved.resolve())
    return out


def get_source_path(df: pd.DataFrame) -> Path | None:
    """Return source path from dataframe attrs if present."""
    raw = df.attrs.get(SOURCE_PATH_ATTR)
    if not raw:
        return None
    return Path(raw)


def apply_datasynth_label_mode(
    df: pd.DataFrame,
    *,
    source_path: str | Path | None = None,
    mode: str = "hidden",
) -> pd.DataFrame:
    """Apply hidden/visible mode for DataSynth ground-truth columns."""
    normalized_mode = mode.lower()
    if normalized_mode not in {"hidden", "visible", "auto"}:
        raise ValueError(f"unsupported datasynth label mode: {mode}")

    resolved_source = resolve_datasynth_source_hint(source_path) if source_path else get_source_path(df)
    out = df.copy()
    if resolved_source is not None:
        out.attrs[SOURCE_PATH_ATTR] = str(resolved_source)
        try:
            from src.ingest.datasynth_metadata import ensure_validated_metadata_json

            ensure_validated_metadata_json(resolved_source)
        except (OSError, ValueError):
            # Why: validated metadata refresh failure should not block ingest.
            pass

    if normalized_mode in {"hidden", "auto"}:
        return _drop_label_columns(out)

    if _has_any_label_columns(out):
        return out

    if resolved_source is None:
        return out

    labels_df = load_document_labels(resolved_source)
    if labels_df is None:
        return out

    merged = out.merge(labels_df, on="document_id", how="left", validate="m:1")
    merged.attrs[SOURCE_PATH_ATTR] = str(resolved_source)
    return merged


def ensure_datasynth_ground_truth(df: pd.DataFrame) -> pd.DataFrame:
    """Attach sidecar labels when the dataframe currently has no GT columns."""
    if _has_any_label_columns(df):
        return df
    return apply_datasynth_label_mode(df, mode="visible")


def load_document_labels(source_path: str | Path) -> pd.DataFrame | None:
    """Load document-level labels from sidecar or embedded DataSynth columns."""
    src = resolve_datasynth_source_hint(source_path)
    label_csv = ensure_sidecar_label_csv(src)
    if label_csv is not None:
        return pd.read_csv(label_csv, low_memory=False)
    return _extract_document_labels_from_source(src)


def ensure_sidecar_label_csv(source_path: str | Path) -> Path | None:
    """Return a usable sidecar path, rebuilding it when DataSynth was refreshed."""
    src = resolve_datasynth_source_hint(source_path)
    existing = find_sidecar_label_csv(src)
    if existing is not None and not _sidecar_needs_refresh(existing, src):
        return existing

    if not _can_materialize_sidecar(src):
        return existing

    labels_df = _extract_document_labels_from_source(src)
    if labels_df is None:
        return existing

    label_csv = _preferred_sidecar_label_csv(src)
    label_csv.parent.mkdir(parents=True, exist_ok=True)
    labels_df.to_csv(label_csv, index=False, encoding="utf-8-sig")
    return label_csv


def find_sidecar_label_csv(source_path: str | Path) -> Path | None:
    """Find document-level label csv next to a DataSynth source CSV."""
    src = resolve_datasynth_source_hint(source_path)
    parent = src.parent
    basename = src.name
    year_match = _YEAR_FILE_RE.match(basename)
    candidates = (
        parent / "labels" / "document_labels.csv",
        parent / "labels" / f"document_labels_{year_match.group(1)}.csv" if year_match else parent / "__missing__",
        parent / "document_labels.csv",
        _DEFAULT_DATASYNTH_DIR / "labels" / "document_labels.csv",
        _DEFAULT_DATASYNTH_DIR / "labels" / f"document_labels_{year_match.group(1)}.csv" if year_match else _DEFAULT_DATASYNTH_DIR / "__missing__",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _drop_label_columns(df: pd.DataFrame) -> pd.DataFrame:
    label_cols = [col for col in df.columns if col.lower() in _LABEL_COLUMNS]
    if not label_cols:
        return df
    out = df.drop(columns=label_cols, errors="ignore").copy()
    out.attrs.update(df.attrs)
    return out


def _has_any_label_columns(df: pd.DataFrame) -> bool:
    return any(col.lower() in _LABEL_COLUMNS for col in df.columns)


def _extract_document_labels_from_source(source_path: str | Path) -> pd.DataFrame | None:
    from src.export.label_splitter import split_label_columns

    try:
        df = pd.read_csv(source_path, low_memory=False)
    except (FileNotFoundError, OSError, ValueError):
        return None

    body_df, labels_df = split_label_columns(df)
    if labels_df.empty:
        return None
    if list(body_df.columns) == list(df.columns):
        return None
    return labels_df


def _preferred_sidecar_label_csv(source_path: Path) -> Path:
    year_match = _YEAR_FILE_RE.match(source_path.name)
    if year_match:
        return source_path.parent / "labels" / f"document_labels_{year_match.group(1)}.csv"
    return source_path.parent / "labels" / "document_labels.csv"


def _sidecar_needs_refresh(label_csv: Path, source_csv: Path) -> bool:
    try:
        return source_csv.is_file() and label_csv.stat().st_mtime < source_csv.stat().st_mtime
    except OSError:
        return False


def _can_materialize_sidecar(source_path: Path) -> bool:
    if not source_path.is_file():
        return False
    try:
        source_path.relative_to(_DEFAULT_DATASYNTH_DIR)
        return True
    except ValueError:
        return False


def resolve_datasynth_source_hint(source_hint: str | Path) -> Path:
    """Resolve a source hint to a stable local DataSynth CSV path when possible."""
    path = Path(source_hint)
    if path.exists():
        return path.resolve()

    name = path.name
    default_candidate = _DEFAULT_DATASYNTH_DIR / name
    if default_candidate.exists():
        return default_candidate.resolve()

    return path.resolve()
