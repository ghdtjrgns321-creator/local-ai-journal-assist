"""RelationalDetector.metadata['relational_edge_artifact'] 계약 검증 (v7-plan S6 Phase A).

Why: relational family R01~R07 의 row score 결과를 edge 단위로 그룹핑한 sanitized
projection (relational_edge_artifact) 이 detection metadata 에 부착됨을 보장한다.
기존 row 단위 출력 (scores / details / rule_flags / graph_entity_summary) 은 변경
0건 — invariant #61.

도메인 정당화:
    - PCAOB AS 2401 §B7 — journal entries reflecting unusual relationships.
    - ISA 240 §32 — management override via unusual relationships.
"""

from __future__ import annotations

import pandas as pd

from src.detection.relational_detector import (
    RelationalDetector,
    build_relational_edge_artifact,
)

# ── 공용 헬퍼 ────────────────────────────────────────────────


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """relational rule 친화 df. posting_date / amount 컬럼 보정."""
    df = pd.DataFrame(rows)
    if "posting_date" in df.columns:
        df["posting_date"] = pd.to_datetime(df["posting_date"])
    for col in ("debit_amount", "credit_amount"):
        if col not in df.columns:
            df[col] = 0.0
    return df


def _full_df() -> pd.DataFrame:
    """R01 + R02 + R03 트리거 mixed fixture (기존 detector 테스트와 동일 의도)."""
    return _make_df(
        [
            # 기존 거래처 정상
            {
                "trading_partner": "V01",
                "gl_account": "5100",
                "posting_date": "2023-01-15",
                "debit_amount": 1_000_000,
                "credit_amount": 0,
                "is_intercompany": False,
            },
            {
                "trading_partner": "V01",
                "gl_account": "5100",
                "posting_date": "2023-06-15",
                "debit_amount": 1_000_000,
                "credit_amount": 0,
                "is_intercompany": False,
            },
            # 신규 거래처 대액 (R01)
            {
                "trading_partner": "V99",
                "gl_account": "5200",
                "posting_date": "2023-06-20",
                "debit_amount": 50_000_000,
                "credit_amount": 0,
                "is_intercompany": False,
            },
            # 휴면 계정 재활성 (R02)
            {
                "trading_partner": "V01",
                "gl_account": "5100",
                "posting_date": "2024-01-01",
                "debit_amount": 5_000_000,
                "credit_amount": 0,
                "is_intercompany": False,
            },
            # IC 거래 정상 — R03 baseline
            {
                "trading_partner": "SUB01",
                "gl_account": "4500",
                "posting_date": "2024-01-05",
                "debit_amount": 10_000_000,
                "credit_amount": 0,
                "is_intercompany": True,
            },
            {
                "trading_partner": "SUB01",
                "gl_account": "4500",
                "posting_date": "2024-01-10",
                "debit_amount": 10_000_000,
                "credit_amount": 0,
                "is_intercompany": True,
            },
            {
                "trading_partner": "SUB01",
                "gl_account": "4500",
                "posting_date": "2024-01-15",
                "debit_amount": 10_000_000,
                "credit_amount": 0,
                "is_intercompany": True,
            },
            # R03 이전가격 outlier
            {
                "trading_partner": "SUB01",
                "gl_account": "4500",
                "posting_date": "2024-01-20",
                "debit_amount": 50_000_000,
                "credit_amount": 0,
                "is_intercompany": True,
            },
        ]
    )


def _rare_pair_df(n_population: int = 60) -> pd.DataFrame:
    """R05 positive — common 60 pair + rare 1 pair (test_relational_detector 패턴 동일)."""
    rows: list[dict] = []
    for i in range(n_population):
        for _ in range(10):
            rows.append(
                {
                    "trading_partner": f"V{i:03d}",
                    "gl_account": f"5{i:03d}",
                    "posting_date": "2024-03-15",
                    "debit_amount": 1_000,
                    "credit_amount": 0,
                    "is_intercompany": False,
                    "created_by": "U00",
                }
            )
    rows.append(
        {
            "trading_partner": "RARE_V",
            "gl_account": "9999",
            "posting_date": "2024-03-15",
            "debit_amount": 50_000_000,
            "credit_amount": 0,
            "is_intercompany": False,
            "created_by": "U00",
        }
    )
    return _make_df(rows)


def _user_spike_df() -> pd.DataFrame:
    """R06 positive — 12 user × 5 month baseline + U00 spike."""
    rows: list[dict] = []
    months = ["2024-01-15", "2024-02-15", "2024-03-15", "2024-04-15", "2024-05-15"]
    for i in range(12):
        for m in months:
            for acc in ("5100", "5200"):
                rows.append(
                    {
                        "trading_partner": "V01",
                        "gl_account": acc,
                        "posting_date": m,
                        "debit_amount": 1_000,
                        "credit_amount": 0,
                        "is_intercompany": False,
                        "created_by": f"U{i:02d}",
                    }
                )
    for j in range(20):
        rows.append(
            {
                "trading_partner": "V01",
                "gl_account": f"9{j:03d}",
                "posting_date": "2024-06-15",
                "debit_amount": 1_000,
                "credit_amount": 0,
                "is_intercompany": False,
                "created_by": "U00",
            }
        )
    return _make_df(rows)


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "trading_partner",
            "gl_account",
            "posting_date",
            "debit_amount",
            "credit_amount",
            "is_intercompany",
        ]
    )


# ── 1. artifact 기본 구조 ────────────────────────────────────


def test_artifact_contains_edges_and_coverage():
    """relational_edge_artifact 가 metadata 에 부착되고 edges + coverage 키 보유."""
    detector = RelationalDetector()
    result = detector.detect(_full_df())
    assert "relational_edge_artifact" in result.metadata
    artifact = result.metadata["relational_edge_artifact"]
    assert artifact["schema_version"] == 1
    assert "edges" in artifact
    assert "coverage" in artifact
    assert isinstance(artifact["edges"], list)
    assert isinstance(artifact["coverage"], dict)


# ── 2. 빈 결과 graceful ─────────────────────────────────────


def test_artifact_empty_when_no_relational_rules_fired():
    """rule 결과 0 또는 df empty → edges 빈 리스트, coverage 모두 0."""
    detector = RelationalDetector()
    result = detector.detect(_empty_df())
    artifact = result.metadata["relational_edge_artifact"]
    assert artifact["edges"] == []
    # coverage 는 rule 등록 여부 무관, 0 또는 미등록 graceful.
    assert all(v == 0 for v in artifact["coverage"].values())


# ── 3. R05 edge 추출 정합 ───────────────────────────────────


def test_r05_edge_extracted_with_edge_a_edge_b_and_metric():
    """R05 row > 0 → edge_a=trading_partner, edge_b=gl_account, metric_value>0."""
    detector = RelationalDetector()
    result = detector.detect(_rare_pair_df(n_population=60))
    artifact = result.metadata["relational_edge_artifact"]
    r05_edges = [e for e in artifact["edges"] if e["rule_id"] == "R05"]
    assert r05_edges, "R05 edge 미생성"
    # rare pair 는 V=RARE_V, account=9999.
    rare = next((e for e in r05_edges if e["edge_a"] == "RARE_V"), None)
    assert rare is not None
    assert rare["edge_b"] == "9999"
    assert rare["metric_value"] > 0
    # R05 default tier — strong (composite score q95+ 의미)
    assert rare["evidence_tier"] == "strong"


# ── 4. R06 user-account edge ───────────────────────────────


def test_r06_user_account_degree_spike_edge():
    """R06 row > 0 → edge_a=created_by(user), edge_b=gl_account."""
    detector = RelationalDetector()
    df = _user_spike_df()
    result = detector.detect(df)
    artifact = result.metadata["relational_edge_artifact"]
    r06_edges = [e for e in artifact["edges"] if e["rule_id"] == "R06"]
    assert r06_edges, "R06 edge 미생성 (spike user U00)"
    # spike user U00 의 edge 가 최소 1개 이상.
    u00_edges = [e for e in r06_edges if e["edge_a"] == "U00"]
    assert u00_edges, f"U00 edge 없음. 전체 edge_a={[e['edge_a'] for e in r06_edges]}"


# ── 5. row_positions ↔ row_indices ─────────────────────────


def test_edge_row_positions_match_indices():
    """edge entry 의 row_positions 와 row_indices 길이 동일 + df 범위 내."""
    detector = RelationalDetector()
    df = _rare_pair_df(n_population=60)
    result = detector.detect(df)
    artifact = result.metadata["relational_edge_artifact"]
    assert artifact["edges"], "edges 비어있어 검증 불가"
    for entry in artifact["edges"]:
        assert len(entry["row_positions"]) == len(entry["row_indices"])
        for pos in entry["row_positions"]:
            assert isinstance(pos, int)
            assert 0 <= pos < len(df)


# ── 6. schema_version pin ───────────────────────────────────


def test_artifact_schema_version_pinned_to_1():
    """schema_version 1 pin — 변경 시 store/builder 동시 마이그레이션 필요."""
    detector = RelationalDetector()
    result = detector.detect(_full_df())
    assert result.metadata["relational_edge_artifact"]["schema_version"] == 1


# ── 7. 기존 row 단위 출력 회귀 보호 ─────────────────────────


def test_existing_row_scores_and_details_unchanged():
    """artifact 추가 후에도 scores / details / graph_entity_summary 회귀 0."""
    detector = RelationalDetector()
    result = detector.detect(_full_df())
    # scores 범위
    assert result.scores.between(0.0, 1.0).all()
    # R01~R03 details 컬럼 존재 + MAX 패턴
    for rule_id in ("R01", "R02", "R03"):
        assert rule_id in result.details.columns
    expected_max = result.details.max(axis=1).fillna(0.0)
    pd.testing.assert_series_equal(result.scores, expected_max, check_names=False)
    # 기존 metadata key 보존
    assert "graph_entity_summary" in result.metadata
    assert "elapsed" in result.metadata


# ── 8. evidence_tier 룰별 분배 ─────────────────────────────


def test_edge_evidence_tier_assigned_per_rule_severity():
    """R05/R06/R07/R03 → strong, R01/R02/R04 → moderate (룰별 default tier).

    Why (D044): precision/recall 튜닝 압력으로 tier 조정 금지. 룰별 의미상
    severity 차원에서만 부여한다.
    """
    detector = RelationalDetector()
    # R05 positive — strong
    artifact_rare = detector.detect(_rare_pair_df(n_population=60)).metadata[
        "relational_edge_artifact"
    ]
    r05_edges = [e for e in artifact_rare["edges"] if e["rule_id"] == "R05"]
    assert all(e["evidence_tier"] == "strong" for e in r05_edges)

    # R01 / R02 fixture — moderate
    artifact_full = detector.detect(_full_df()).metadata["relational_edge_artifact"]
    r01_edges = [e for e in artifact_full["edges"] if e["rule_id"] == "R01"]
    r02_edges = [e for e in artifact_full["edges"] if e["rule_id"] == "R02"]
    if r01_edges:
        assert all(e["evidence_tier"] == "moderate" for e in r01_edges)
    if r02_edges:
        assert all(e["evidence_tier"] == "moderate" for e in r02_edges)
    # R03 — strong (이전가격 outlier)
    r03_edges = [e for e in artifact_full["edges"] if e["rule_id"] == "R03"]
    if r03_edges:
        assert all(e["evidence_tier"] == "strong" for e in r03_edges)


# ── 9. helper 직접 호출 — coverage 계약 ────────────────────


def test_build_relational_edge_artifact_helper_returns_dict_shape():
    """build_relational_edge_artifact(...).to_dict() 직접 호출 — settings/audit_rules
    누락 시도 graceful."""
    detector = RelationalDetector()
    df = _rare_pair_df(n_population=60)
    # detector 내부 호출 결과와 helper 직접 호출 결과 동일 구조.
    result = detector.detect(df)
    artifact_via_detector = result.metadata["relational_edge_artifact"]

    rule_results = {col: result.details[col] for col in result.details.columns}
    artifact_direct = build_relational_edge_artifact(df, rule_results, detector._settings)
    direct_dict = artifact_direct.to_dict()
    assert direct_dict["schema_version"] == 1
    # detector 가 severity-normalized 점수를 넘기지만 helper 의 edge 구조 자체는
    # 동일 schema 를 유지한다.
    assert set(direct_dict.keys()) == set(artifact_via_detector.keys())
