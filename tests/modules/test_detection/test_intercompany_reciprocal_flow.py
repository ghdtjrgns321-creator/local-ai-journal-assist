"""IntercompanyMatcher reciprocal flow internal column 테스트.

target: single-document reciprocal IC flow scoring (ic_reciprocal_flow_prob).

핵심 가설 (raw 진단 결과 docs/완료 산출 ic_design_diagnostic_20260524.md):
- 정상 IC 는 receivable 또는 payable 한 쪽 GL 만 한 doc 에 기록
  (single_doc_reciprocal_gl_ratio = 0%).
- circular truth 는 한 doc 안에 receivable + payable 동시 + amount symmetry (= 100%).
- 따라서 single-doc reciprocal + amount symmetry 가 structural minimum.
- context (period_end / after_hours / round_amount) 는 boost only — 단독 strong 금지.
- IC01/IC02/IC03/sidecar/RuleFlag 계약은 변경 없음.
"""

from __future__ import annotations

import pandas as pd

from config.settings import AuditSettings
from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.intercompany_rules import compute_reciprocal_flow_scores

AUDIT_RULES = {
    "patterns": {
        "intercompany": {
            "pairs": [
                {"receivable": "1150", "payable": "2050"},
                {"receivable": "4500", "payable": "2700"},
            ],
            "partner_format": {
                "ic_partner_regex": r"^IC-[A-Z]\d{3}$|^[A-Za-z]\d{3}$|^[A-Za-z]$",
            },
        },
    },
}


def _settings(**overrides) -> AuditSettings:
    base = {"ic_min_ic_rows": 1}
    base.update(overrides)
    return AuditSettings(**base)


def _make_doc(
    doc_id: str,
    *,
    rec_gl: str,
    pay_gl: str | None,
    rec_amt: float,
    pay_amt: float | None,
    company: str = "C001",
    partner: str = "IC-C002",
    posting_date: str = "2024-06-15 10:00:00",
) -> list[dict]:
    """단일 또는 양쪽 line 으로 doc 구성."""
    rows = [
        {
            "document_id": doc_id,
            "gl_account": rec_gl,
            "debit_amount": rec_amt,
            "credit_amount": 0.0,
            "company_code": company,
            "trading_partner": partner,
            "posting_date": posting_date,
            "reference": f"REF-{doc_id}",
        }
    ]
    if pay_gl is not None and pay_amt is not None:
        rows.append(
            {
                "document_id": doc_id,
                "gl_account": pay_gl,
                "debit_amount": 0.0,
                "credit_amount": pay_amt,
                "company_code": company,
                "trading_partner": partner,
                "posting_date": posting_date,
                "reference": f"REF-{doc_id}",
            }
        )
    return rows


def _wrap_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["posting_date"] = pd.to_datetime(df["posting_date"])
    df["is_intercompany"] = (
        df["gl_account"].astype(str).str.startswith(("1150", "2050", "4500", "2700"))
    )
    if "currency" not in df.columns:
        df["currency"] = "KRW"
    return df


# ── helper 단위 테스트 ────────────────────────────────────────────


class TestComputeReciprocalFlowScores:
    """compute_reciprocal_flow_scores 단위 — raw 도메인 분리 검증."""

    def test_reciprocal_balanced_with_context_yields_high(self):
        """#1: single-doc receivable+payable + amount symmetry + period-end → high score."""
        rows = _make_doc(
            "D001",
            rec_gl="1150",
            pay_gl="2050",
            rec_amt=250_000_000,
            pay_amt=250_000_000,
            posting_date="2024-06-30 10:00:00",  # period-end
        )
        df = _wrap_df(rows)
        scores, summary = compute_reciprocal_flow_scores(
            df,
            pair_map={"1150": "2050", "2050": "1150", "4500": "2700", "2700": "4500"},
            settings=_settings(),
            audit_rules=AUDIT_RULES,
        )
        col = scores["ic_reciprocal_flow_prob"]
        assert (col > 0.5).all(), f"reciprocal+balanced+period-end 점수가 약함: {col.tolist()}"
        assert summary["structural_candidate_docs"] == 1
        assert summary["score_max"] > 0.5

    def test_period_end_only_without_reciprocal_is_zero(self):
        """#2: receivable 만 있고 reciprocal 없음 + period-end → score 0 (structural 미달)."""
        rows = _make_doc(
            "D002",
            rec_gl="1150",
            pay_gl=None,
            rec_amt=250_000_000,
            pay_amt=None,
            posting_date="2024-06-30 10:00:00",
        )
        df = _wrap_df(rows)
        scores, summary = compute_reciprocal_flow_scores(
            df,
            pair_map={"1150": "2050", "2050": "1150"},
            settings=_settings(),
            audit_rules=AUDIT_RULES,
        )
        assert (scores["ic_reciprocal_flow_prob"] == 0).all()
        assert summary["structural_candidate_docs"] == 0

    def test_after_hours_only_without_reciprocal_is_zero(self):
        """#3: after-hours only (구조 신호 없음) → score 0."""
        rows = _make_doc(
            "D003",
            rec_gl="2050",
            pay_gl=None,
            rec_amt=100_000_000,
            pay_amt=None,
            posting_date="2024-06-15 23:30:00",  # after-hours
        )
        df = _wrap_df(rows)
        scores, _ = compute_reciprocal_flow_scores(
            df,
            pair_map={"1150": "2050", "2050": "1150"},
            settings=_settings(),
            audit_rules=AUDIT_RULES,
        )
        assert (scores["ic_reciprocal_flow_prob"] == 0).all()

    def test_ic_gl_only_no_reciprocal_structure_low(self):
        """#4: IC GL pair (1150) 한쪽만 다수 → low (양측 동시 doc 없음)."""
        rows: list[dict] = []
        for i in range(5):
            rows.extend(
                _make_doc(
                    f"D-only-{i}",
                    rec_gl="1150",
                    pay_gl=None,
                    rec_amt=100_000_000,
                    pay_amt=None,
                )
            )
        df = _wrap_df(rows)
        scores, _ = compute_reciprocal_flow_scores(
            df,
            pair_map={"1150": "2050", "2050": "1150"},
            settings=_settings(),
            audit_rules=AUDIT_RULES,
        )
        assert (scores["ic_reciprocal_flow_prob"] == 0).all()

    def test_normal_split_doc_ic_pair_is_low(self):
        """#5: 정상 IC = receivable doc 1 + payable doc 1 (양측 별도) → 둘 다 low."""
        rows = []
        rows.extend(
            _make_doc("D-rec", rec_gl="1150", pay_gl=None, rec_amt=200_000_000, pay_amt=None)
        )
        rows.extend(
            _make_doc("D-pay", rec_gl="2050", pay_gl=None, rec_amt=200_000_000, pay_amt=None)
        )
        df = _wrap_df(rows)
        scores, _ = compute_reciprocal_flow_scores(
            df,
            pair_map={"1150": "2050", "2050": "1150"},
            settings=_settings(),
            audit_rules=AUDIT_RULES,
        )
        assert (scores["ic_reciprocal_flow_prob"] == 0).all(), "정상 split-doc IC 가 score 받음"

    def test_amount_mismatch_in_same_doc_not_reciprocal_high(self):
        """#6: 같은 doc 안 receivable+payable 이지만 amount 비대칭 → reciprocal score 낮음.

        amount mismatch 는 probabilistic columns 의 ic_amount_prob 가 담당. reciprocal_flow 는
        대칭일 때만 trigger.
        """
        rows = _make_doc(
            "D-asym",
            rec_gl="1150",
            pay_gl="2050",
            rec_amt=200_000_000,
            pay_amt=80_000_000,  # 60% mismatch
        )
        df = _wrap_df(rows)
        scores, summary = compute_reciprocal_flow_scores(
            df,
            pair_map={"1150": "2050", "2050": "1150"},
            settings=_settings(ic_reciprocal_amount_similarity_min=0.95),
            audit_rules=AUDIT_RULES,
        )
        assert (scores["ic_reciprocal_flow_prob"] == 0).all()
        assert summary["structural_candidate_docs"] == 0

    def test_missing_trading_partner_graceful(self):
        """#7: trading_partner 없어도 graceful (raw 도메인 시그널만으로 점수)."""
        rows = _make_doc(
            "D-no-tp",
            rec_gl="1150",
            pay_gl="2050",
            rec_amt=100_000_000,
            pay_amt=100_000_000,
            partner="",
        )
        df = _wrap_df(rows)
        scores, summary = compute_reciprocal_flow_scores(
            df,
            pair_map={"1150": "2050", "2050": "1150"},
            settings=_settings(),
            audit_rules=AUDIT_RULES,
        )
        # trading_partner 없어도 reciprocal GL + amount symmetry 만으로 structural pass
        assert summary["structural_candidate_docs"] == 1
        assert "missing_required_columns" not in " ".join(summary["warnings"])

    def test_empty_pair_map_returns_zero(self):
        """#8: pair_map 비면 graceful 0 + warning."""
        rows = _make_doc(
            "D-x", rec_gl="1150", pay_gl="2050", rec_amt=100_000_000, pay_amt=100_000_000
        )
        df = _wrap_df(rows)
        scores, summary = compute_reciprocal_flow_scores(
            df, pair_map={}, settings=_settings(), audit_rules={}
        )
        assert (scores["ic_reciprocal_flow_prob"] == 0).all()
        assert "empty_pair_map" in summary["warnings"]

    def test_phase1_columns_do_not_affect_score(self):
        """#9: flagged_rules / priority_score / review_rules 등 주입해도 결과 동일."""
        rows = _make_doc(
            "D-p1",
            rec_gl="1150",
            pay_gl="2050",
            rec_amt=100_000_000,
            pay_amt=100_000_000,
            posting_date="2024-06-30 10:00:00",
        )
        df_base = _wrap_df(rows)
        df_inj = df_base.copy()
        df_inj["flagged_rules"] = "L3-03,L4-05"
        df_inj["priority_score"] = 0.85
        df_inj["priority_band"] = "high"
        df_inj["review_rules"] = "IC01"

        pair = {"1150": "2050", "2050": "1150"}
        s_base, _ = compute_reciprocal_flow_scores(
            df_base, pair_map=pair, settings=_settings(), audit_rules=AUDIT_RULES
        )
        s_inj, _ = compute_reciprocal_flow_scores(
            df_inj, pair_map=pair, settings=_settings(), audit_rules=AUDIT_RULES
        )
        pd.testing.assert_series_equal(
            s_base["ic_reciprocal_flow_prob"], s_inj["ic_reciprocal_flow_prob"]
        )

    def test_synthetic_label_columns_do_not_affect_score(self):
        """#10: is_fraud / is_anomaly / mutation_* / manipulation_scenario 주입해도 결과 동일."""
        rows = _make_doc(
            "D-syn",
            rec_gl="1150",
            pay_gl="2050",
            rec_amt=100_000_000,
            pay_amt=100_000_000,
            posting_date="2024-06-30 10:00:00",
        )
        df_base = _wrap_df(rows)
        df_inj = df_base.copy()
        df_inj["is_fraud"] = True
        df_inj["is_anomaly"] = True
        df_inj["mutation_type"] = "circular_round_trip"
        df_inj["mutation_mutated_field"] = "amount"
        df_inj["manipulation_scenario"] = "circular_related_party_transaction"
        df_inj["manipulated_entry_truth"] = 1

        pair = {"1150": "2050", "2050": "1150"}
        s_base, _ = compute_reciprocal_flow_scores(
            df_base, pair_map=pair, settings=_settings(), audit_rules=AUDIT_RULES
        )
        s_inj, _ = compute_reciprocal_flow_scores(
            df_inj, pair_map=pair, settings=_settings(), audit_rules=AUDIT_RULES
        )
        pd.testing.assert_series_equal(
            s_base["ic_reciprocal_flow_prob"], s_inj["ic_reciprocal_flow_prob"]
        )


# ── matcher 통합 ────────────────────────────────────────────────


class TestMatcherIntegration:
    """IntercompanyMatcher 통합 — RuleFlag/sidecar/metadata 계약 보존."""

    def test_ic01_sidecar_preserved(self):
        """#11: 신규 internal column 추가해도 IC01 evidence_level/review_reason sidecar 그대로."""
        rows = []
        # IC01 trigger: receivable 만 + partner 있음 + master에 없음 → high
        rows.append(
            {
                "document_id": "D-ic01",
                "gl_account": "1150",
                "debit_amount": 100_000_000,
                "credit_amount": 0.0,
                "company_code": "C001",
                "trading_partner": "X999",  # ic_partner_regex 통과, master 부재
                "posting_date": "2024-06-15 10:00:00",
                "reference": "REF-ic01",
            }
        )
        # circular: single-doc reciprocal + balanced
        rows.extend(
            _make_doc(
                "D-recip",
                rec_gl="1150",
                pay_gl="2050",
                rec_amt=200_000_000,
                pay_amt=200_000_000,
                posting_date="2024-06-30 10:00:00",
            )
        )
        df = _wrap_df(rows)
        det = IntercompanyMatcher(settings=_settings(), audit_rules=AUDIT_RULES)
        result = det.detect(df)

        sidecar = result.metadata.get("row_sidecar", {})
        assert "ic01_evidence_level" in sidecar
        assert "ic01_review_reason" in sidecar
        # IC01 sidecar 값이 비어있지 않은 row 가 최소 1개
        assert (sidecar["ic01_evidence_level"].astype(str) != "").any()

    def test_reciprocal_column_not_in_rule_flags(self):
        """#12: ic_reciprocal_flow_prob 는 RuleFlag 에 포함되지 않음 (canonical IC01~03 만)."""
        rows = _make_doc(
            "D-recip-only",
            rec_gl="1150",
            pay_gl="2050",
            rec_amt=200_000_000,
            pay_amt=200_000_000,
            posting_date="2024-06-30 10:00:00",
        )
        df = _wrap_df(rows)
        det = IntercompanyMatcher(settings=_settings(), audit_rules=AUDIT_RULES)
        result = det.detect(df)

        rule_ids = {rf.rule_id for rf in result.rule_flags}
        assert rule_ids.issubset({"IC01", "IC02", "IC03"}), f"신규 internal id 누출: {rule_ids}"
        assert "ic_reciprocal_flow_prob" not in rule_ids
        # details 에는 internal column 으로 존재
        assert "ic_reciprocal_flow_prob" in result.details.columns
        # metadata 에 reciprocal_flow summary 존재
        assert "reciprocal_flow" in result.metadata
        rs = result.metadata["reciprocal_flow"]
        assert "structural_candidate_docs" in rs
        assert "evaluated_ic_rows" in rs

    def test_missing_is_intercompany_column_infers_from_configured_gl_prefixes(self):
        """#13: journal-visible shortcut 컬럼 없이도 IC GL prefix 로 reciprocal case 산출."""
        rows = _make_doc(
            "D-no-shortcut",
            rec_gl="1150",
            pay_gl="2050",
            rec_amt=200_000_000,
            pay_amt=200_000_000,
            posting_date="2024-06-30 10:00:00",
        )
        df = pd.DataFrame(rows)
        # v33d regression shape: no is_intercompany column and posting_date remains string.
        det = IntercompanyMatcher(settings=_settings(), audit_rules=AUDIT_RULES)
        result = det.detect(df)

        assert "ic_reciprocal_flow_prob" in result.details.columns
        assert result.metadata["reciprocal_flow"]["structural_candidate_docs"] == 1
        assert result.details["ic_reciprocal_flow_prob"].gt(0).all()
        reciprocal = result.metadata["ic_pair_artifact"]["reciprocal_pairs"]
        assert len(reciprocal) == 1
