"""Ingest 패키지 — 외부 전표 파일을 표준 DataFrame으로 변환."""

from src.ingest.datasynth_metadata import (
    DATASYNTH_METADATA_CRITICAL_ATTR,
    DATASYNTH_METADATA_PATH_ATTR,
    DATASYNTH_METADATA_STATUS_ATTR,
    DATASYNTH_METADATA_WARNING_ATTR,
    MetadataReconciliation,
    ObservedMetadata,
    apply_validated_metadata_attrs,
    build_validated_metadata,
    build_validated_metadata_messages,
    default_validated_metadata_path,
    ensure_validated_metadata_json,
    load_validated_metadata_json,
    reconcile_reported_metadata,
    summarize_observed_metadata,
    write_validated_metadata,
)
from src.ingest.file_validator import ValidationResult, validate_file
from src.ingest.mapping_profile import (
    delete_profile,
    list_profiles,
    load_profile,
    save_profile,
)
from src.ingest.models import CastingResult, ReadResult, SheetScore
from src.ingest.reader_api import read_file
from src.ingest.sheet_scorer import score_sheets
from src.ingest.type_caster import cast_dataframe

__all__ = [
    "CastingResult",
    "DATASYNTH_METADATA_CRITICAL_ATTR",
    "DATASYNTH_METADATA_PATH_ATTR",
    "DATASYNTH_METADATA_STATUS_ATTR",
    "DATASYNTH_METADATA_WARNING_ATTR",
    "MetadataReconciliation",
    "ObservedMetadata",
    "ReadResult",
    "SheetScore",
    "ValidationResult",
    "apply_validated_metadata_attrs",
    "build_validated_metadata",
    "build_validated_metadata_messages",
    "cast_dataframe",
    "delete_profile",
    "default_validated_metadata_path",
    "ensure_validated_metadata_json",
    "list_profiles",
    "load_validated_metadata_json",
    "load_profile",
    "read_file",
    "reconcile_reported_metadata",
    "save_profile",
    "score_sheets",
    "summarize_observed_metadata",
    "validate_file",
    "write_validated_metadata",
]
