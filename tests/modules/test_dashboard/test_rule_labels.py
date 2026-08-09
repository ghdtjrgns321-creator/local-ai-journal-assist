"""룰 한국어 이름의 표면 간 일치 계약.

Why(2026-08-04): 종전에는 같은 룰이 화면마다 다른 이름으로 표시됐다 — 대시보드 사전,
`phase1_case_builder` 테마별 사전, `config/combo_builder.yaml` label 이 전수 대조 29/29
불일치였다(예: L2-03 = "중복 분개" / "근접일자 중복 전표" / "중복 전표"). 감사인이 한 룰을
세 이름으로 보게 되므로 README·조합 빌더 어휘로 통일했고, 다시 갈라지지 않도록 계약으로 박는다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from dashboard.components.rule_labels import RULE_NAMES_KR, rule_label
from src.detection.phase1_case_builder import _rule_label

ROOT = Path(__file__).resolve().parents[3]


def _vocab_labels() -> dict[str, str]:
    raw = yaml.safe_load((ROOT / "config/combo_builder.yaml").read_text(encoding="utf-8"))
    return {item["rule_id"]: item["label"] for item in raw["bodies"] + raw["features"]}


def test_dashboard_labels_match_combo_builder_vocabulary():
    """빌더 어휘 22종은 대시보드 라벨과 글자까지 같아야 한다."""
    mismatched = {
        rule_id: (label, RULE_NAMES_KR.get(rule_id))
        for rule_id, label in _vocab_labels().items()
        if RULE_NAMES_KR.get(rule_id) != label
    }
    assert not mismatched, f"빌더 어휘와 다른 대시보드 라벨: {mismatched}"


def test_case_builder_labels_match_dashboard_labels():
    """케이스 빌더 테마 라벨도 같은 이름을 쓴다(내부 reason code 는 대상 외)."""
    mismatched = {
        rule_id: (name, _rule_label(rule_id))
        for rule_id, name in RULE_NAMES_KR.items()
        if _rule_label(rule_id) != rule_id and _rule_label(rule_id) != name
    }
    assert not mismatched, f"케이스 빌더와 다른 라벨: {mismatched}"


def test_cutoff_rule_has_a_label():
    """L3-11 컷오프는 종전 대시보드 사전에 아예 없어 코드로만 표시됐다."""
    assert RULE_NAMES_KR["L3-11"] == "컷오프"
    assert rule_label("L3-11") == "L3-11 · 컷오프"
