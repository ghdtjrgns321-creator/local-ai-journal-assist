"""Standard audit explanation schema for detection rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

_REQUIRED_FIELDS = (
    "principle",
    "violation_reason",
    "audit_next_action",
    "reference",
)


@dataclass(frozen=True)
class RuleExplanation:
    """Frozen, JSON-serializable audit explanation for one detection rule."""

    principle: str
    violation_reason: str
    audit_next_action: str
    reference: str

    def __post_init__(self) -> None:
        for field_name in _REQUIRED_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation."""

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RuleExplanation:
        """Build an explanation from a JSON-like mapping."""

        missing = [field_name for field_name in _REQUIRED_FIELDS if field_name not in payload]
        if missing:
            raise ValueError(f"Missing RuleExplanation fields: {', '.join(missing)}")
        return cls(**{field_name: payload[field_name] for field_name in _REQUIRED_FIELDS})
