"""docs/DECISION.md 의 ``### D{n}:`` 헤더 unique 회귀 가드.

2026-05-15 D040/D041/D042 ID 충돌 정정 이후 동일 사고가 재발하지 않도록
CI 에서 강제한다. DECISION.md 를 파싱해 모든 ``### D<digits>:`` 헤더를
추출하고, 중복 ID 가 1 건이라도 발견되면 ``ValueError`` 와 non-zero exit
code 로 GitHub Actions 를 fail 시킨다.

사용:
    uv run python tools/scripts/audit_decision_ids.py
    uv run python tools/scripts/audit_decision_ids.py docs/DECISION.md
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

# ``### D<digits>:`` 형태만 받는다. ``###`` 다음 공백 1개, D + 숫자, 콜론.
HEADER_PATTERN = re.compile(r"^### (D\d+):")

DEFAULT_DECISION_PATH = Path(__file__).resolve().parents[2] / "docs" / "DECISION.md"


def collect_decision_ids(path: Path) -> list[tuple[int, str]]:
    """``[(line_no, decision_id), ...]`` 형태로 모든 헤더를 반환한다."""
    # mojibake 영역이 섞여 있어 encoding 오류는 surrogate-escape 로 흡수한다.
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    hits: list[tuple[int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = HEADER_PATTERN.match(line)
        if match is not None:
            hits.append((line_no, match.group(1)))
    return hits


def audit(path: Path = DEFAULT_DECISION_PATH) -> None:
    """중복 ID 발견 시 ``ValueError`` 발생, 없으면 silent return."""
    if not path.exists():
        raise FileNotFoundError(f"DECISION.md not found: {path}")

    hits = collect_decision_ids(path)
    if not hits:
        raise ValueError(
            f"No '### D<n>:' headers found in {path}. "
            "파서 정규식과 문서 형식이 어긋났을 가능성이 있다."
        )

    counter = Counter(decision_id for _, decision_id in hits)
    duplicates = {did: count for did, count in counter.items() if count > 1}
    if not duplicates:
        return

    lines_by_id: dict[str, list[int]] = {}
    for line_no, decision_id in hits:
        if decision_id in duplicates:
            lines_by_id.setdefault(decision_id, []).append(line_no)

    detail = "\n".join(
        f"  - {did}: {counter[did]} occurrences at lines {lines_by_id[did]}"
        for did in sorted(duplicates)
    )
    raise ValueError(
        f"Duplicate decision IDs detected in {path}:\n{detail}\n"
        "각 ### D<n>: 헤더는 unique 해야 한다. 중복을 해소하려면 충돌 ID "
        "중 하나를 다음 free ID (현재 D050+) 로 재발번하고, DECISION.md "
        "머리의 '결정 ID 발번 규칙' 안내를 갱신한다."
    )


def main(argv: list[str]) -> int:
    target = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_DECISION_PATH
    try:
        audit(target)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"OK: {target} has unique D<n> headers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
