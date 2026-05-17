from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SECTION_RE = re.compile(
    r"6\. \*\*S5 Top-5 룰 LEAKAGE_DENY_RULES.*?(?=\n\n근거 audit:)",
    re.DOTALL,
)
TOP5_RE = re.compile(r"Top-5 deterministic 룰 \((.*?)\) 을", re.DOTALL)
RULE_ID_RE = re.compile(r"`(rule_L\d-\d{2})`")


def _read_constant_rules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "LEAKAGE_DENY_RULES" not in names:
                continue
            if not isinstance(node.value, ast.Call):
                break
            if not (
                isinstance(node.value.func, ast.Name)
                and node.value.func.id == "frozenset"
                and node.value.args
            ):
                break
            arg = node.value.args[0]
            if not isinstance(arg, ast.Set):
                break
            return [
                elt.value
                for elt in arg.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
    raise ValueError(f"Could not parse LEAKAGE_DENY_RULES from {path}")


def _read_constraints_rules(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = SECTION_RE.search(text)
    if match is None:
        raise ValueError("Could not find CONSTRAINTS.md section 6 LEAKAGE_DENY_RULES body")
    top5 = TOP5_RE.search(match.group(0))
    if top5 is None:
        raise ValueError("Could not find CONSTRAINTS.md section 6 Top-5 rule list")
    return RULE_ID_RE.findall(top5.group(1))


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    constant_rules = _read_constant_rules(repo / "src/preprocessing/constants.py")
    constraints_rules = _read_constraints_rules(repo / "docs/CONSTRAINTS.md")
    if constant_rules != constraints_rules:
        print("LEAKAGE_DENY_RULES mismatch between constants.py and CONSTRAINTS.md section 6")
        print(f"constants.py:     {constant_rules}")
        print(f"CONSTRAINTS.md section 6: {constraints_rules}")
        return 1
    print("LEAKAGE_DENY_RULES matches CONSTRAINTS.md section 6")
    return 0


if __name__ == "__main__":
    sys.exit(main())
