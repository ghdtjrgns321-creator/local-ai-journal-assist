"""FS11(관계사 부당지원) 부정 문서가 검토 표면에 오르지 않는 지점을 추적한다.

실측 배경(2026-07-26): overlay r1 에서 FS11 표면화가 0/20 이다. 그런데 그 20문서는
전 행이 is_intercompany=true 이고 L3-03 은 is_intercompany 참이면 발화하는 단순
조건이다. 즉 "발화는 하는데 표면에 못 오른다"가 성립하는지, 성립하면 어느 단계에서
탈락하는지를 단계별 잔존 수로 확인한다.

단계: 탐지기 발화 → raw hit(rule_id × signal_status) → unit 진입

사용: uv run python tools/scripts/diag_fs11_surface_loss.py [<fraud_dir>] [<scheme_id>]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DIR = ROOT / "data/journal/primary/datasynth_semantic_v1_phase2_fraud_s10_20260718_r1"


def main() -> int:
    from src.detection.phase1_case_builder import _collect_raw_hits
    from src.export.phase1_case_view import resolve_phase1_case_result
    from src.pipeline import AuditPipeline

    fraud_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    scheme = sys.argv[2] if len(sys.argv) > 2 else "FS11"

    prov = pd.read_csv(fraud_dir / "labels/phase2_scheme_provenance.csv", dtype=str)
    target_docs = set(prov.loc[prov["scheme_id"] == scheme, "document_id"])
    print(f"{scheme} 부정 문서: {len(target_docs)}건")

    res = AuditPipeline(skip_db=True).run(str(fraud_dir / "journal_entries.csv"))
    df = res.data
    row_docs = df["document_id"].astype(str)
    print(f"원장 내 해당 행: {int(row_docs.isin(sorted(target_docs)).sum())}행")

    # 1단계 — 탐지기 발화 (flagged_indices 기준)
    print("\n[1] 탐지기 발화 (트랙별 대상 문서 수)")
    fired_docs: set[str] = set()
    for r in res.results:
        labels = [lbl for lbl in r.flagged_indices if lbl in row_docs.index]
        hit = set(row_docs.loc[labels]) & target_docs if labels else set()
        if hit:
            print(f"    {r.track_name:<30} {len(hit)}문서")
            fired_docs |= hit
    print(f"    -> 하나라도 발화: {len(fired_docs)}/{len(target_docs)}")

    # 2단계 — raw hit 의 rule_id × signal_status 분포
    print("\n[2] raw hit (rule_id × signal_status × 문서수)")
    raw_hits = _collect_raw_hits(df, res.results)
    per_rule: dict[tuple[str, str], set[str]] = {}
    for hit in raw_hits:
        doc = str(hit.document_id)
        if doc in target_docs:
            per_rule.setdefault((hit.rule_id, hit.signal_status), set()).add(doc)
    if not per_rule:
        print("    (대상 문서에 대한 raw hit 없음)")
    for (rule_id, status), docs in sorted(per_rule.items()):
        print(f"    {rule_id:<12} {status:<18} {len(docs)}문서")
    hit_docs = {d for docs in per_rule.values() for d in docs}
    print(f"    -> raw hit 보유 문서: {len(hit_docs)}/{len(target_docs)}")

    # 3단계 — unit 진입
    print("\n[3] unit 진입")
    phase1 = resolve_phase1_case_result(res)
    units = list(phase1.units) if phase1 else []
    unit_docs: set[str] = set()
    for unit in units:
        if unit.unit_type == "flow":
            unit_docs |= {str(d) for d in (getattr(unit, "member_document_ids", []) or [])}
        else:
            unit_docs.add(str(unit.unit_id))
    entered = unit_docs & target_docs
    print(f"    unit 총 {len(units)}개 / 대상 문서 진입 {len(entered)}건")

    # 4단계 — 구 위험도 게이트 영향 실측.
    #   게이트는 2026-07-26 제거했다(phase1_case_builder). 여기서는 같은 판정을 로컬로
    #   재현해, 제거 전이라면 몇 행이 잘렸을지를 회귀 확인용으로 계속 보고한다.
    print("\n[4] 구 위험도 게이트 (제거됨 — 영향 재현)")

    def _legacy_gate(frame: pd.DataFrame) -> set | None:
        if "risk_level" in frame.columns:
            risk = frame["risk_level"].astype(str)
            return set(risk[risk.ne("Normal")].index.tolist())
        if "anomaly_score" in frame.columns:
            score = pd.to_numeric(frame["anomaly_score"], errors="coerce").fillna(0.0)
            return set(score[score.gt(0)].index.tolist())
        return None

    candidates = _legacy_gate(df)
    is_target = row_docs.isin(sorted(target_docs))
    if "risk_level" in df.columns:
        print(f"    대상 행 risk_level: {df.loc[is_target, 'risk_level'].value_counts().to_dict()}")
    if candidates is None:
        print("    게이트 없음 (risk_level·anomaly_score 컬럼 부재)")
    else:
        target_pass = sum(1 for lbl in df.index[is_target] if lbl in candidates)
        print(f"    후보 통과 행: 전체 {len(candidates):,} / {len(df):,}")
        print(f"    대상 행 통과: {target_pass}/{int(is_target.sum())}")
        # 전역 — 탐지기가 발화했는데 게이트에서 잘린 행
        fired_labels: set = set()
        for r in res.results:
            fired_labels |= {lbl for lbl in r.flagged_indices if lbl in row_docs.index}
        blocked = fired_labels - candidates
        blocked_docs = set(row_docs.loc[sorted(blocked)]) if blocked else set()
        print(
            f"    전역: 발화 행 {len(fired_labels):,} 중 게이트 차단 {len(blocked):,}행"
            f" ({len(blocked_docs):,}문서)"
        )

    print("\n[판정]")
    print(f"    발화 {len(fired_docs)} → raw hit {len(hit_docs)} → unit {len(entered)}")
    lost = hit_docs - unit_docs
    if lost:
        lost_rules = Counter()
        for (rule_id, status), docs in per_rule.items():
            for d in docs & lost:
                lost_rules[(rule_id, status)] += 1
        print(f"    raw hit 은 있는데 unit 에 못 든 문서 {len(lost)}건 — 룰별:")
        for (rule_id, status), n in sorted(lost_rules.items(), key=lambda kv: -kv[1]):
            print(f"        {rule_id:<12} {status:<18} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
