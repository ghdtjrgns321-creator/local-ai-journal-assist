"""S2-3 판정 — 단위시험 데이터에 실제 파이프라인을 돌려 룰별 표적 발화를 M/N으로 판정.

기준: 각 룰이 자기 정답 문서(labels/s2_expected.csv) **전부**에서 발화해야 PASS.
"다른 전표에서 발화"는 인정하지 않는다(표적 적중 기준). exit 0 = 전수 PASS.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATASET = ROOT / "data/journal/unit/s2_unit_firing_20260717"
OUT = ROOT / "reports/s2_unit_firing/adjudication.json"


def main() -> int:
    from src.pipeline import AuditPipeline

    expected = pd.read_csv(DATASET / "labels" / "s2_expected.csv", dtype=str)
    res = AuditPipeline(skip_db=True).run(str(DATASET / "journal_entries.csv"))
    df = res.data
    doc_series = df["document_id"].astype(str)

    # 룰별 발화 문서 집합 수집 — 두 채널:
    #   (1) DetectionResult.details 양수 점수 (통상 룰)
    #   (2) metadata["review_score_series"] 양수 — L3-12처럼 점수 비병합·검토 신호 전용 룰은
    #       설계상 details가 항상 0이고 review 채널로만 나간다(fraud_layer.py:421-423, 467).
    fired: dict[str, set[str]] = {}
    channel: dict[str, set[str]] = {}

    def _collect(frame, tag):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return
        for rule_id in frame.columns:
            scores = pd.to_numeric(frame[rule_id], errors="coerce").fillna(0.0)
            pos_idx = scores[scores > 0].index
            docs = set(doc_series.reindex(pos_idx).dropna())
            if docs:
                fired.setdefault(str(rule_id), set()).update(docs)
                channel.setdefault(str(rule_id), set()).add(tag)

    for result in res.results:
        _collect(getattr(result, "details", None), "details")
        meta = getattr(result, "metadata", None) or {}
        _collect(meta.get("review_score_series"), "review")

    rows = []
    for rule_id, grp in expected.groupby("rule_id"):
        want = set(grp["document_id"])
        got = fired.get(rule_id, set())
        hit = want & got
        rows.append(
            {
                "rule_id": rule_id,
                "expected_docs": sorted(want),
                "hit_docs": sorted(hit),
                "missed_docs": sorted(want - hit),
                "fired_docs_total": len(got),
                "channels": sorted(channel.get(rule_id, set())),
                "verdict": "PASS" if want <= got else "FAIL",
            }
        )
    rows.sort(key=lambda r: r["rule_id"])
    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    report = {
        "dataset": str(DATASET),
        "rows_total": int(len(df)),
        "rules_judged": len(rows),
        "pass": n_pass,
        "fail": len(rows) - n_pass,
        "results": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for r in rows:
        mark = "PASS" if r["verdict"] == "PASS" else f"FAIL missed={r['missed_docs']}"
        print(f"{r['rule_id']:<10} {mark}")
    print(f"\nS2 판정: {n_pass}/{len(rows)} PASS -> {OUT}")
    return 0 if n_pass == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
