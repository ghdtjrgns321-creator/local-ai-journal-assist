"""Project package marker.

The package intentionally avoids eager cross-module imports so that individual
submodules can be imported in isolation without pulling unrelated dependencies.
"""

from __future__ import annotations

__all__: list[str] = []
