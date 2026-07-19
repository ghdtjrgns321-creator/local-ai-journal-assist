"""S2 분모 확정 — 탐지기 레지스트리에서 rule_id 전수를 스크립트로 추출해 파일로 고정.

Why: 문서의 "32룰"을 손으로 믿으면 탐지기 없는 유령 ID(L1-09·L3-01·L3-08 사례)가
     분모에 섞인다(S1에서 실측). 분모는 코드가 실제로 등록한 것만.
출력: reports/s2_unit_firing/rule_denominator.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.detection.access_audit_layer import AccessAuditDetector  # noqa: E402
from src.detection.anomaly_layer import AnomalyDetector  # noqa: E402
from src.detection.evidence_detector import EvidenceDetector  # noqa: E402
from src.detection.fraud_layer import FraudLayer  # noqa: E402
from src.detection.integrity_layer import IntegrityDetector  # noqa: E402
from src.detection.variance_layer import VarianceDetector  # noqa: E402

# variance(D01)는 PHASE1-2 자기 큐 소관이라 S2(PHASE1-1 룰 단위시험) 비대상 —
# 게다가 전년 집계(prior aggregates) 주입 없이는 레지스트리 자체가 안 만들어진다.
LAYERS = [
    ("integrity", IntegrityDetector),
    ("fraud", FraudLayer),
    ("anomaly", AnomalyDetector),
    ("access_audit", AccessAuditDetector),
    ("evidence", EvidenceDetector),
]

_ = VarianceDetector  # 명시 제외 기록용 import 유지


def main() -> int:
    rows = []
    for layer_name, cls in LAYERS:
        det = cls()  # 전 레이어 settings=None 기본 생성 지원 (BaseDetector 규약)
        if hasattr(det, "_build_registry"):
            entries = [(e[0], e[1]) for e in det._build_registry()]
        elif layer_name == "integrity":
            # IntegrityDetector는 detect() 안 인라인 목록 (integrity_layer.py:175-179)
            entries = [
                ("L1-01", det._a01_unbalanced_entry),
                ("L1-02", det._a02_missing_required),
                ("L1-03", det._a03_invalid_account),
            ]
        else:
            raise AttributeError(f"{layer_name}: registry 추출 경로 없음")
        for rule_id, func in entries:
            rows.append(
                {
                    "rule_id": rule_id,
                    "layer": layer_name,
                    "callable": getattr(func, "__name__", str(func)),
                }
            )

    # 활성 표면 판정 (2026-07-17): AA01~04는 enable_access_audit_detection(기본 False),
    # EV01/EV03은 enable_evidence_detection(기본 False) 게이트 뒤의 옵션 확장 —
    # config/settings.py:532-533. 제품 기본 표면이 아니므로 S2 발화시험 비대상.
    # AA02는 게이트와 무관하게 미구현 스켈레톤(access_audit_rules.py:81-93, 항상 0.0).
    INACTIVE_EXTENSIONS = {"AA01", "AA02", "AA03", "AA04", "EV01", "EV03"}
    UNIMPLEMENTED = {"AA02"}
    for r in rows:
        r["s2_scope"] = r["rule_id"] not in INACTIVE_EXTENSIONS
        if r["rule_id"] in UNIMPLEMENTED:
            r["status_note"] = "미구현 스켈레톤 — 어떤 데이터로도 발화 불가"
        elif r["rule_id"] in INACTIVE_EXTENSIONS:
            r["status_note"] = "설정 게이트 기본 off (옵션 확장)"

    ids = [r["rule_id"] for r in rows]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    out = {
        "registry_count": len(rows),
        "s2_denominator_count": sum(1 for r in rows if r["s2_scope"]),
        "rules": sorted(rows, key=lambda r: r["rule_id"]),
        "duplicate_rule_ids": dupes,
        "note": (
            "L4-02(Benford)는 PHASE1-2 자기 큐로 이관되어 레이어 레지스트리 비대상. "
            "PHASE2(VAE)는 룰 단위시험 비대상. AA/EV 확장은 s2_scope=false (기본 비활성)."
        ),
    }
    dest = ROOT / "reports" / "s2_unit_firing" / "rule_denominator.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"denominator = {len(rows)} rules -> {dest}")
    for r in out["rules"]:
        print(f"  {r['rule_id']:<10} {r['layer']:<13} {r['callable']}")
    if dupes:
        print("duplicates:", dupes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
