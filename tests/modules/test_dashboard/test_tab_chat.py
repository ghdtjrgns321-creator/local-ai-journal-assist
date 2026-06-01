"""Legacy Chat/Text-to-SQL tests.

The feature is removed from the active product path; historical tests are kept
as an explicit skip marker instead of importing disabled UI code.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="legacy disabled: Chat/Text-to-SQL removed from active path"
)


def test_tab_chat_legacy_disabled() -> None:
    """Skip marker for the removed chat tab."""
