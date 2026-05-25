from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dashboard import tab_phase2
from src.metrics.models import PerformanceReport, RuleMetric
from src.metrics.report_builder import build_markdown_report


def test_build_performance_cards_formats_values():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="operational_proxy",
        phase_scope="phase2_included",
        total_docs=10,
        flagged_docs=4,
        high_risk_docs=2,
        high_risk_ratio=0.2,
        whitelist_removed_docs=1,
    )

    cards = tab_phase2._build_performance_cards(report)

    assert cards[0][0] == "Flagged Docs"
    assert cards[0][1] == "4"
    assert cards[2][1] == "20.0%"


def test_build_performance_cards_hides_prf_without_ground_truth():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="operational_proxy",
        phase_scope="phase2_included",
        precision=0.8,
        recall=0.7,
        f1=0.75,
    )

    cards = tab_phase2._build_performance_cards(report)

    assert "Precision" not in {label for label, _ in cards}
    assert "Recall" not in {label for label, _ in cards}
    assert "F1" not in {label for label, _ in cards}


def test_build_performance_rule_frame_returns_dataframe():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        rule_metrics=[
            RuleMetric(
                track_name="layer_a",
                rule_code="L1-01",
                label_docs=3,
                flagged_docs=2,
                tp_docs=1,
                fp_docs=1,
                fn_docs=2,
                precision=0.5,
                recall=1 / 3,
                f1=0.4,
            )
        ],
    )

    df = tab_phase2._build_performance_rule_frame(report)

    assert list(df["rule_code"]) == ["L1-01"]
    assert list(df["rule_group"]) == ["L1"]
    assert list(df["precision"]) == ["50.0%"]


def test_markdown_report_includes_phase2_hold_out_caveat():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="ground_truth",
        phase_scope="phase2_included",
        hold_out_metrics={
            "hold_out_doc_count": 50,
            "hold_out_detected_docs": 25,
            "hold_out_recall": 0.5,
            "hold_out_pass": True,
            "ci95": {"half_width": 0.14},
            "caveat": (
                "n=50, 95% CI ≈ ±0.14, 시나리오 단위 hold-out (true zero-day fraud type 아님)"
            ),
        },
    )

    markdown = build_markdown_report(report)

    assert "## Phase 2 Hold-out" in markdown
    assert "n=50, 95% CI ≈ ±0.14" in markdown
    assert "| Hold-out pass | True |" in markdown


def test_build_phase2_provenance_cards_reports_mode_and_contract():
    result = type(
        "Result",
        (),
        {
            "phase2_training_report_id": "train_001",
            "phase2_inference_mode": "training_contract",
            "phase2_inference_contract": {
                "required_models": ["supervised", "unsupervised"],
                "promoted_versions": {"supervised": 3},
            },
        },
    )()

    cards = tab_phase2._build_phase2_provenance_cards(result)

    assert cards == [
        ("모델 기준", "train_001"),
        ("실행 방식", "저장된 기준 사용"),
        ("사용 후보", "2"),
        ("확정 모델", "1"),
    ]


def test_build_promoted_model_frame_summarizes_contract():
    snapshot = {
        "report_id": "train_001",
        "inference_contract": {
            "required_models": ["supervised", "timeseries"],
            "promoted_versions": {"supervised": 4},
            "family_sub_detectors": {
                "timeseries": ["transaction_burst", "unusual_frequency"],
            },
        },
        "promotion_policy": {"selection_mode": "best_per_family"},
    }

    df = tab_phase2._build_promoted_model_frame(snapshot)

    assert list(df["분석 기준"]) == ["supervised", "timeseries"]
    assert list(df["버전"]) == ["4", "-"]
    assert list(df["세부 점검"]) == ["-", "transaction_burst, unusual_frequency"]


def test_build_promoted_model_frame_exposes_unsupervised_metric_semantics():
    snapshot = {
        "report_id": "train_001",
        "inference_contract": {
            "required_models": ["unsupervised"],
            "promoted_versions": {"unsupervised": 4},
        },
        "promoted_models": [
            {
                "model_name": "unsupervised",
                "metric_name": "unsupervised_selection_score",
                "metric_value": 0.4321,
            }
        ],
        "promotion_policy": {
            "unsupervised_metric_policy": {
                "interpretation": "ranking_proxy_not_fraud_accuracy",
            },
        },
    }

    df = tab_phase2._build_promoted_model_frame(snapshot)

    assert list(df["metric_name"]) == ["unsupervised_selection_score"]
    assert list(df["metric_value"]) == ["0.4321"]
    assert list(df["evaluation_policy"]) == ["ranking_proxy_not_fraud_accuracy"]
    assert "ranking/calibration proxy" in tab_phase2._build_unsupervised_metric_caption(snapshot)


def test_build_phase2_training_diagnostics_and_preprocessing_summary():
    snapshot = {
        "metadata": {"schema_hash": "abc123"},
        "preprocessing_plan": {
            "row_count": 100,
            "profile_sampled": True,
            "profile_sample_size": 50,
            "metadata": {"decision_count": 3},
            "decisions": [
                {"column": "amount", "action": "include"},
                {"column": "is_fraud", "action": "exclude"},
            ],
        },
        "leaderboard": [
            {
                "metadata": {
                    "train_calibration_split": {"split_strategy": "group"},
                    "unsupervised_metric": {
                        "reliability_warnings": ["degenerate_score_distribution"]
                    },
                }
            }
        ],
    }

    summary = tab_phase2._build_preprocessing_plan_summary(snapshot)
    diagnostics = tab_phase2._build_phase2_training_diagnostics(snapshot)

    assert "profile=sampled(50)" in summary
    assert diagnostics.loc[0, "split_policy"] == "group"
    assert diagnostics.loc[0, "profile_cap"] == 50
    assert diagnostics.loc[0, "schema_hash"] == "abc123"
    assert diagnostics.loc[0, "reliability_warnings"] == "degenerate_score_distribution"


def test_determine_phase2_user_state_three_branches():
    result = type("Result", (), {"phase2_training_report_id": "train_001"})()

    assert tab_phase2._determine_phase2_user_state(None, None) == "not_trained"
    assert (
        tab_phase2._determine_phase2_user_state({"report_id": "train_001"}, None)
        == "training_report_available"
    )
    assert (
        tab_phase2._determine_phase2_user_state({"report_id": "train_001"}, result)
        == "inference_complete"
    )


def test_build_phase2_state_cards_describe_report_and_contract():
    cards = tab_phase2._build_phase2_state_cards(
        "inference_complete",
        {
            "report_id": "train_001",
            "inference_contract": {
                "required_models": ["unsupervised", "duplicate"],
                "family_sub_detectors": {"duplicate": ["exact_duplicate_amount"]},
            },
        },
        type(
            "Result",
            (),
            {
                "phase2_training_report_id": "train_001",
                "phase2_inference_mode": "training_contract",
                "phase2_inference_contract": {"source_report_id": "train_001"},
            },
        )(),
    )

    assert cards == [
        ("상태", "Inference complete"),
        ("학습 리포트", "train_001"),
        ("추론 방식", "저장된 기준 사용"),
        ("계약 분석 영역", "2"),
    ]


def test_apply_phase2_partition_filters_fiscal_year_only_when_selected():
    df = tab_phase2.pd.DataFrame(
        {
            "fiscal_year": [2022, 2023, 2024],
            "amount": [1, 2, 3],
        }
    )

    full = tab_phase2._apply_phase2_partition_filter(df, "전체")
    year_2024 = tab_phase2._apply_phase2_partition_filter(df, "2024")

    assert len(full) == 3
    assert list(year_2024["amount"]) == [3]


def test_merge_phase2_partition_summaries_accepts_list_subdetectors():
    merged = tab_phase2._merge_phase2_partition_summaries(
        [
            {
                "year": "2022",
                "families": {
                    "unsupervised": {
                        "family": "unsupervised",
                        "rows_scored": 10,
                        "high_count_q95": 1,
                        "score_distribution": {"nonzero_count": 2},
                        "sub_detectors": ["vae_reconstruction_ecdf"],
                    }
                },
            },
            {
                "year": "2023",
                "families": {
                    "unsupervised": {
                        "family": "unsupervised",
                        "rows_scored": 20,
                        "high_count_q95": 3,
                        "score_distribution": {"nonzero_count": 4},
                        "sub_detectors": ["vae_reconstruction_ecdf"],
                    }
                },
            },
        ]
    )

    family = merged["families"]["unsupervised"]
    assert family["rows_scored"] == 30
    assert family["high_count_q95"] == 4
    assert family["score_distribution"]["nonzero_count"] == 6
    assert family["sub_detectors"]["vae_reconstruction_ecdf"]["hit_count"] == 0


def test_family_overview_frame_centers_audit_family_meaning():
    partition_summary = {
        "families": {
            "duplicate": {
                "score_distribution": {"nonzero_count": 12},
                "sub_detectors": {
                    "exact_duplicate_amount": {"hit_count": 4},
                    "fuzzy_duplicate_near_amount": {"hit_count": 0},
                },
            },
            "unsupervised": {"high_count_q95": 3},
        }
    }

    frame = tab_phase2._build_family_overview_frame(None, partition_summary)

    assert "상태" in frame.columns
    assert "무엇을 잡나" in frame.columns
    assert "감사인이 확인할 것" in frame.columns
    assert set(frame["상태"]) == {"활성", "대기"}
    duplicate = frame.loc[frame["분석 영역"] == "중복 전표"].iloc[0]
    assert duplicate["이번 데이터 반응"] == "12건 신호"
    assert "중복 지급" in duplicate["무엇을 잡나"]
    supervised = frame.loc[frame["분석 영역"] == "지도 학습"].iloc[0]
    assert supervised["이번 데이터 반응"] == "조건 충족 전"
    assert "라벨" in supervised["활성 조건/비고"]


def test_family_signal_chart_frame_uses_relative_reaction_score():
    partition_summary = {
        "families": {
            "duplicate": {"score_distribution": {"nonzero_count": 200}},
            "timeseries": {"score_distribution": {"nonzero_count": 50}},
        }
    }

    frame = tab_phase2._build_family_signal_chart_frame(partition_summary)

    duplicate = frame.loc[frame["분석 영역"] == "중복 전표"].iloc[0]
    timeseries = frame.loc[frame["분석 영역"] == "시점 이상"].iloc[0]
    supervised = frame.loc[frame["분석 영역"] == "지도 학습"].iloc[0]
    assert duplicate["반응도"] == 100.0
    assert timeseries["반응도"] == 25.0
    assert supervised["반응도"] == 0.0


def test_phase12_priority_matrix_keeps_phase1_priority_band_and_ranks_phase2():
    case_lookup = {
        f"case_{idx:03d}": SimpleNamespace(
            case_id=f"case_{idx:03d}",
            priority_score=float(101 - idx),
            priority_band="high" if idx <= 4 else "medium" if idx <= 10 else "low",
        )
        for idx in range(1, 101)
    }
    overlays = [
        {
            "phase1_case_id": f"case_{idx:03d}",
            "phase2_review_band": "immediate",
            "family_contributions": [
                {"family": "unsupervised", "score": float(101 - idx), "ecdf": (101 - idx) / 100}
            ],
        }
        for idx in range(1, 101)
    ]

    p1_counts, p2_counts, integrated_counts, total_cases = (
        tab_phase2._phase12_rank_percentile_review_bands(case_lookup, overlays)
    )

    assert total_cases == 100
    # PHASE1 uses existing priority_band, PHASE2 uses rank percentile.
    # PHASE1+2 통합 = PHASE1 band ∩ PHASE2 band per case.
    #   immediate ∩ immediate: case_001~002 (both phase1 immediate ∩ phase2 top 1.25%) → 2
    #   review ∩ review: case_005 only (phase1 review=case_005~010, phase2 review=case_003~005) → 1
    #   candidate ∩ candidate: case_011~025 (phase1 candidate from 011, phase2 candidate to 025) → 15
    assert p1_counts == {"immediate": 4, "review": 6, "candidate": 90}
    assert p2_counts == {"immediate": 2, "review": 3, "candidate": 20}
    assert integrated_counts == {"immediate": 2, "review": 1, "candidate": 15}


def test_phase2_rank_percentile_uses_phase1_case_universe_denominator():
    case_lookup = {
        f"case_{idx:03d}": SimpleNamespace(case_id=f"case_{idx:03d}", priority_score=1.0)
        for idx in range(1, 101)
    }
    overlays = [
        {
            "phase1_case_id": f"case_{idx:03d}",
            "family_contributions": [{"family": "duplicate", "score": 1.0, "ecdf": 1.0}],
        }
        for idx in range(1, 11)
    ]

    _p1_counts, p2_counts, _integrated_counts, total_cases = (
        tab_phase2._phase12_rank_percentile_review_bands(case_lookup, overlays)
    )

    assert total_cases == 100
    assert p2_counts == {"immediate": 2, "review": 3, "candidate": 5}


def test_family_case_contribution_counts_ignore_explicit_zero_signal_entries():
    overlays = [
        {
            "phase1_case_id": "case_1",
            "family_contributions": [
                {"family": "duplicate", "score": 0.0, "ecdf": 0.0},
                {"family": "relational", "score": 0.4, "ecdf": 0.8},
            ],
        }
    ]

    counts = tab_phase2._family_case_contribution_counts(overlays)

    assert counts["duplicate"] == 0
    assert counts["relational"] == 1


def test_family_case_contribution_counts_include_review_only_candidates():
    overlays = [
        {
            "phase1_case_id": "case_1",
            "family_contributions": [
                {
                    "family": "intercompany",
                    "score": 0.0,
                    "ecdf": 0.0,
                    "review_only_count": 3,
                    "review_reasons": ["missing_partner"],
                }
            ],
        }
    ]

    counts = tab_phase2._family_case_contribution_counts(overlays)

    assert counts["intercompany"] == 1


def test_all_family_summary_uses_review_only_candidates_for_intercompany():
    overlays = [
        {
            "phase1_case_id": "case_1",
            "family_contributions": [
                {
                    "family": "intercompany",
                    "score": 0.0,
                    "ecdf": 0.0,
                    "review_only_count": 1,
                    "review_reasons": ["mapping_uncertain"],
                }
            ],
        }
    ]

    rows = tab_phase2._build_all_family_summary({"families": {}}, overlays=overlays)
    intercompany = next(row for row in rows if row["family"] == "intercompany")

    assert intercompany["signal_value"] == 1
    assert intercompany["이번 데이터 반응"] == "1건 신호"


def test_case_level_overlay_placeholder_does_not_render_as_zero_signal():
    overlays = [
        {
            "phase1_case_id": "case_1",
            "family_contributions": [],
            "top_family": None,
            "max_evidence_tier": None,
            "lane_membership": [],
        }
    ]

    assert not tab_phase2._has_case_level_phase2_details(overlays)

    scale_cards = tab_phase2._build_scale_kpi_cards(
        overlays,
        {"families": {}},
        overlay_status="placeholder",
    )
    evidence_cards = tab_phase2._build_evidence_tier_kpi_cards(
        overlays,
        overlay_status="placeholder",
    )

    assert "case-level overlay 미생성" in "".join(scale_cards)
    assert "case-level overlay 미생성" in "".join(evidence_cards)
    assert ">0<span" not in "".join(evidence_cards)


def test_summary_ribbon_valid_no_hit_shows_zero_with_explicit_label(monkeypatch):
    """P5-2: overlays 존재 + family hit 없음 → "0 + 추가 적중 없음" 표시.

    이전 정책 ("0 표시 금지, placeholder 안내") 은 D8 (valid_no_hit) 와 D5
    (overlay_missing) 을 구분하지 못해 사용자가 실패로 오해할 수 있었다. P5-2 정책은
    valid_no_hit 을 정상 결과로 명시 노출한다.
    """
    overlays = [
        {
            "phase1_case_id": "case_1",
            "family_contributions": [],
            "top_family": None,
            "max_evidence_tier": None,
            "lane_membership": [],
        }
    ]
    rendered: list[str] = []

    monkeypatch.setattr(tab_phase2, "_resolve_phase2_overlays_from_state", lambda: overlays)
    monkeypatch.setattr(tab_phase2, "_resolve_phase1_case_count_from_state", lambda: 1)
    monkeypatch.setattr(tab_phase2.st, "markdown", lambda html, **_: rendered.append(html))

    tab_phase2._render_phase2_summary_ribbon({"families": {}})

    html = "".join(rendered)
    assert "추가 적중 없음" in html
    assert "\n    <div" not in html
    # "실패" 같은 단어가 함께 노출되면 안 된다 (valid_no_hit 은 정상 결과).
    assert "실패" not in html


def test_review_lane_frame_marks_missing_phase1_priority_unknown():
    overlays = [
        {
            "phase1_case_id": "case_missing",
            "lane_membership": ["duplicate"],
            "top_family": "duplicate",
            "family_contributions": [
                {
                    "family": "duplicate",
                    "score": 0.7,
                    "ecdf": 0.99,
                    "evidence_tier": "strong",
                    "sub_detectors": [{"code": "L2-03a"}],
                }
            ],
        }
    ]

    frame = tab_phase2._build_review_lane_frame("duplicate", overlays)

    assert list(frame["Phase1 등급"]) == ["미확인"]
    assert list(frame["Phase1 점수"]) == ["-"]


def test_review_lane_frame_uses_phase2_result_phase1_fallback_for_priority():
    overlays = [
        {
            "phase1_case_id": "case_low",
            "lane_membership": ["duplicate"],
            "family_contributions": [
                {"family": "duplicate", "score": 0.7, "ecdf": 0.99, "sub_detectors": []}
            ],
        },
        {
            "phase1_case_id": "case_high",
            "lane_membership": ["duplicate"],
            "family_contributions": [
                {"family": "duplicate", "score": 0.2, "ecdf": 0.96, "sub_detectors": []}
            ],
        },
    ]
    phase2_result = SimpleNamespace(
        phase1_case_result=SimpleNamespace(
            cases=[
                SimpleNamespace(
                    case_id="case_low",
                    priority_band="low",
                    priority_score=0.1,
                ),
                SimpleNamespace(
                    case_id="case_high",
                    priority_band="high",
                    priority_score=0.9,
                ),
            ]
        )
    )

    frame = tab_phase2._build_review_lane_frame(
        "duplicate",
        overlays,
        phase2_result=phase2_result,
    )

    assert list(frame["case_id"]) == ["case_high", "case_low"]
    assert list(frame["Phase1 등급"]) == ["HIGH", "LOW"]
    assert list(frame["Phase1 점수"]) == [0.9, 0.1]


def test_phase1_result_ui_forbidden_files_are_not_imported():
    tab_phase1 = Path("dashboard/tab_phase1.py").read_text(encoding="utf-8")
    rule_panel = Path("dashboard/components/rule_panel.py").read_text(encoding="utf-8")

    assert "phase2_family_matrix" not in tab_phase1
    assert "phase2_family_matrix" not in rule_panel


def test_phase1_no_longer_imports_phase2_inference_action_directly():
    source = Path("dashboard/tab_phase1.py").read_text(encoding="utf-8")

    assert "from dashboard.tab_phase2 import _start_phase2_analysis" not in source
    assert "Phase 2 탭으로 이동" in source


# ── P2-4: status 별 메시지/short_text 분기 테스트 ─────────────────


def test_overlay_status_short_text_covers_all_p2_statuses():
    """9 store-level status + 4 in-memory status 모두 비어있지 않은 라벨을 가져야 한다."""
    statuses = [
        # in-memory 분기
        "available",
        "missing",
        "placeholder",
        "partition_mismatch",
        # overlay_store 진단
        "loaded",
        "schema_mismatch",
        "batch_id_mismatch",
        "training_report_mismatch",
        "invalid_payload",
        "parse_error",
        "unsafe_batch_id",
        "ctx_missing",
    ]
    for status in statuses:
        label = tab_phase2._overlay_status_short_text(status)
        assert label and label != "확인 필요", f"label missing for {status!r}"


def test_overlay_status_message_returns_korean_action_for_store_statuses():
    """각 store-level status 가 한국어 메시지 + next action 을 가져야 한다."""
    for status in (
        "missing",
        "schema_mismatch",
        "batch_id_mismatch",
        "training_report_mismatch",
        "invalid_payload",
        "parse_error",
        "unsafe_batch_id",
        "ctx_missing",
    ):
        message = tab_phase2._overlay_status_message(status, partition="2024")
        assert message, f"empty message for {status!r}"
        # missing/mismatch/parse_error 같은 분기는 next action 으로 "Phase 2" 또는
        # "회사" 같은 사용자 행동 키워드를 포함해야 한다.
        assert any(kw in message for kw in ("Phase 2", "회사", "관리자", "재추론")), (
            f"missing next action for {status!r}: {message}"
        )


def test_resolve_display_overlays_prefers_store_status_when_empty():
    """overlay 가 비어있고 result 에 store-level status 가 있으면 그 status 를 반환."""
    fake_result = SimpleNamespace(
        phase2_partition="전체",
        phase2_overlay_status="schema_mismatch",
        phase2_case_overlays=[],
    )

    # session_state mocking 없이 직접 테스트하기 위해 _resolve_phase2_overlays_from_state 패치 필요.
    import dashboard.tab_phase2 as mod

    original = mod._resolve_phase2_overlays_from_state
    mod._resolve_phase2_overlays_from_state = lambda: []
    try:
        overlays, status = mod._resolve_display_overlays(fake_result, partition="2024")
    finally:
        mod._resolve_phase2_overlays_from_state = original

    assert overlays == []
    assert status == "schema_mismatch"


def test_resolve_display_overlays_falls_back_to_missing_when_no_status():
    """store-level status 없으면 기존처럼 missing 반환."""
    fake_result = SimpleNamespace(phase2_partition="전체")

    import dashboard.tab_phase2 as mod

    original = mod._resolve_phase2_overlays_from_state
    mod._resolve_phase2_overlays_from_state = lambda: []
    try:
        overlays, status = mod._resolve_display_overlays(fake_result, partition="2024")
    finally:
        mod._resolve_phase2_overlays_from_state = original

    assert overlays == []
    assert status == "missing"


# ── P3: phase1 case basis caption 매핑 테스트 ───────────────────


def test_phase1_case_basis_captions_cover_all_statuses():
    """6 status 모두 _PHASE1_CASE_BASIS_CAPTIONS 에 매핑되어 있어야 한다."""
    statuses = (
        "canonical_in_memory",
        "canonical_artifact",
        "fallback_redetect",
        "metadata_only",
        "artifact_error",
        "unavailable",
    )
    for status in statuses:
        entry = tab_phase2._PHASE1_CASE_BASIS_CAPTIONS.get(status)
        assert entry is not None, f"missing caption for {status!r}"
        severity, message = entry
        assert severity in ("silent", "warning", "error")
        if severity == "silent":
            assert message == ""
        else:
            assert message


def test_phase1_case_basis_canonical_statuses_are_silent():
    """정상 연결 상태는 Phase 2 요약 화면에 진단 caption 으로 노출하지 않는다."""
    assert tab_phase2._PHASE1_CASE_BASIS_CAPTIONS["canonical_in_memory"] == ("silent", "")
    assert tab_phase2._PHASE1_CASE_BASIS_CAPTIONS["canonical_artifact"] == ("silent", "")


def test_phase1_case_basis_fallback_redetect_is_warning_with_next_action():
    """fallback_redetect 는 warning 톤 + Phase 1 분석 다시 실행 안내 포함."""
    severity, message = tab_phase2._PHASE1_CASE_BASIS_CAPTIONS["fallback_redetect"]
    assert severity == "warning"
    assert "Phase 1" in message
    assert "다시 실행" in message or "재실행" in message


def test_phase1_case_basis_unavailable_is_warning_pointing_to_phase1():
    """unavailable 은 Phase 2 문제로 보이지 않고 Phase 1 case basis 부재로 표시."""
    severity, message = tab_phase2._PHASE1_CASE_BASIS_CAPTIONS["unavailable"]
    assert severity == "warning"
    assert "Phase 1" in message
    # "Phase 2" 키워드는 있어도 되지만, 안내의 주체는 Phase 1 이어야 한다.
    assert "Phase 1 검토 케이스" in message


def test_phase1_case_basis_artifact_error_is_error_with_recovery():
    """artifact_error 는 error 톤 + 복구 액션 (재실행 / 파일 확인)."""
    severity, message = tab_phase2._PHASE1_CASE_BASIS_CAPTIONS["artifact_error"]
    assert severity == "error"
    assert any(kw in message for kw in ("다시 실행", "재실행", "artifact", "파일"))


# ── P4: 4 axis status caption 매핑 테스트 ─────────────────────


def test_phase2_db_load_captions_have_failed_warning_with_action():
    """failed 는 warning + 사용자 안내(새로고침 제한) 포함."""
    severity, message = tab_phase2._PHASE2_DB_LOAD_CAPTIONS["failed"]
    assert severity == "warning"
    assert "DB" in message
    assert any(kw in message for kw in ("새로고침", "복원", "세션"))


def test_phase2_db_load_captions_skipped_are_caption_level():
    """skipped 분기는 caption 톤 (warning 아님) — 정상 graceful."""
    for status in ("skipped_no_conn", "skipped_no_load_result"):
        severity, message = tab_phase2._PHASE2_DB_LOAD_CAPTIONS[status]
        assert severity in ("caption", "info")
        assert message


def test_phase2_inference_mode_untrained_is_warning_with_action():
    """untrained_contract_only 는 warning + 학습 권유."""
    severity, message = tab_phase2._PHASE2_INFERENCE_MODE_CAPTIONS["untrained_contract_only"]
    assert severity == "warning"
    assert "학습" in message


def test_phase2_partition_fallback_caption_named():
    """selected_year_zero_rows 매핑 존재 + 전체 fallback 안내."""
    text = tab_phase2._PHASE2_PARTITION_FALLBACK_CAPTIONS["selected_year_zero_rows"]
    assert "전체" in text or "전체 데이터" in text


def test_phase2_context_missing_is_warning_about_persistence():
    """missing_context 는 새로고침 복원 안 됨 안내."""
    severity, message = tab_phase2._PHASE2_CONTEXT_CAPTIONS["missing_context"]
    assert severity == "warning"
    assert "새로고침" in message or "복원" in message


# ── P5: Phase2EmptyState resolver + KPI/Chart 빈 상태 분리 테스트 ──


def test_resolve_empty_state_returns_phase2_not_run_when_result_none():
    state = tab_phase2._resolve_phase2_empty_state(
        phase2_result=None,
        overlays=[],
        phase1_basis_status="canonical_in_memory",
        overlay_status=None,
    )
    assert state.state_id == tab_phase2._PHASE2_STATE_NOT_RUN
    assert state.show_charts is False
    assert state.show_lanes is False


def test_resolve_empty_state_returns_phase1_basis_unavailable_when_no_cases():
    state = tab_phase2._resolve_phase2_empty_state(
        phase2_result=SimpleNamespace(batch_id="b"),
        overlays=[],
        phase1_basis_status="unavailable",
        overlay_status=None,
    )
    assert state.state_id == tab_phase2._PHASE2_STATE_PHASE1_BASIS_UNAVAILABLE
    assert "Phase 1" in state.title
    assert state.show_charts is False


def test_resolve_empty_state_returns_overlay_missing_for_store_problems():
    """overlay store 진단 status 들이 overlay_missing 으로 분류되어야 한다."""
    for status in (
        "missing",
        "schema_mismatch",
        "batch_id_mismatch",
        "training_report_mismatch",
        "parse_error",
        "unsafe_batch_id",
        "ctx_missing",
    ):
        state = tab_phase2._resolve_phase2_empty_state(
            phase2_result=SimpleNamespace(),
            overlays=[],
            phase1_basis_status="canonical_in_memory",
            overlay_status=status,
        )
        assert state.state_id == tab_phase2._PHASE2_STATE_OVERLAY_MISSING, status


def test_resolve_empty_state_returns_valid_no_hit_when_overlays_no_hit():
    """overlays 존재 + family hit 없음 → valid_no_hit (정상 결과)."""
    overlays = [
        {
            "phase1_case_id": "c1",
            "family_contributions": [],
            "top_family": None,
            "max_evidence_tier": None,
        }
    ]
    state = tab_phase2._resolve_phase2_empty_state(
        phase2_result=SimpleNamespace(),
        overlays=overlays,
        phase1_basis_status="canonical_in_memory",
        overlay_status="available",
    )
    assert state.state_id == tab_phase2._PHASE2_STATE_VALID_NO_HIT
    assert state.severity == "info"
    assert state.show_charts is True
    # R-M1: Phase 2 적중 case 가 없어 Phase 2 Lane 표시 안 함. Phase 1 결과 탭으로 안내.
    assert state.show_lanes is False
    assert state.next_action_label == "Phase 1 결과 탭에서 계속 검토"
    # valid_no_hit 은 정상 결과 — 재실행/재추론 유도 금지.
    assert "재추론" not in state.body
    assert "다시 실행" not in state.body


def test_resolve_empty_state_returns_available_when_hits_present():
    overlays = [
        {
            "phase1_case_id": "c1",
            "top_family": "duplicate",
            "max_evidence_tier": "strong",
            "family_contributions": [{"family": "duplicate"}],
        }
    ]
    state = tab_phase2._resolve_phase2_empty_state(
        phase2_result=SimpleNamespace(),
        overlays=overlays,
        phase1_basis_status="canonical_in_memory",
        overlay_status="available",
    )
    assert state.state_id == tab_phase2._PHASE2_STATE_AVAILABLE
    assert state.show_charts is True
    assert state.show_lanes is True


def test_build_kpi_value_and_sub_missing_returns_dash():
    """overlay_missing 분기는 value="-" + missing 라벨 sub."""
    state = tab_phase2.Phase2EmptyState(
        state_id=tab_phase2._PHASE2_STATE_OVERLAY_MISSING,
        severity="warning",
        title="t",
        body="b",
        next_action_label=None,
        show_charts=False,
        show_lanes=False,
    )
    value, sub = tab_phase2._build_kpi_value_and_sub(
        empty_state=state,
        value=0,
        denom=10,
        available_sub="<div>available</div>",
        no_hit_sub="<div>no-hit</div>",
        missing_sub_template="<div>missing:{label}</div>",
        sub_style="",
    )
    assert value == "-"
    assert "overlay" in sub or "미생성" in sub


def test_build_kpi_value_and_sub_valid_no_hit_returns_zero_with_no_hit_label():
    """valid_no_hit 분기는 value="0" + no-hit sub (정상 결과 표시)."""
    state = tab_phase2.Phase2EmptyState(
        state_id=tab_phase2._PHASE2_STATE_VALID_NO_HIT,
        severity="info",
        title="t",
        body="b",
        next_action_label=None,
        show_charts=True,
        show_lanes=True,
    )
    value, sub = tab_phase2._build_kpi_value_and_sub(
        empty_state=state,
        value=0,
        denom=10,
        available_sub="<div>available</div>",
        no_hit_sub="<div>no-hit-label</div>",
        missing_sub_template="<div>missing:{label}</div>",
        sub_style="",
    )
    assert value == "0"
    assert "no-hit-label" in sub


def test_build_kpi_value_and_sub_available_uses_real_value():
    state = tab_phase2.Phase2EmptyState(
        state_id=tab_phase2._PHASE2_STATE_AVAILABLE,
        severity="info",
        title="",
        body="",
        next_action_label=None,
        show_charts=True,
        show_lanes=True,
    )
    value, sub = tab_phase2._build_kpi_value_and_sub(
        empty_state=state,
        value=42,
        denom=100,
        available_sub="<div>available-sub</div>",
        no_hit_sub="",
        missing_sub_template="",
        sub_style="",
    )
    assert value == "42"
    assert "available-sub" in sub


# ── R-M2: placeholder 회귀 ────────────────────────────────────


def test_resolve_empty_state_placeholder_overlay_is_overlay_missing_not_valid_no_hit():
    """R-H1 회귀: overlays 존재 + overlay_status='placeholder' → overlay_missing.

    placeholder 는 case-level attribution 이 채워지지 않은 상태로, "0건 추가 적중 없음"
    같이 정상 결과로 표시하면 안 된다 (D8 valid_no_hit 와 다른 상태).
    """
    overlays = [
        {
            "phase1_case_id": "c1",
            "family_contributions": [],
            "top_family": None,
            "max_evidence_tier": None,
        }
    ]
    state = tab_phase2._resolve_phase2_empty_state(
        phase2_result=SimpleNamespace(),
        overlays=overlays,
        phase1_basis_status="canonical_in_memory",
        overlay_status="placeholder",
    )
    assert state.state_id == tab_phase2._PHASE2_STATE_OVERLAY_MISSING
    assert state.state_id != tab_phase2._PHASE2_STATE_VALID_NO_HIT
    assert state.severity == "warning"


def test_resolve_empty_state_phase1_basis_unavailable_priority_over_no_hit_overlays():
    """basis unavailable 이 valid_no_hit 보다 우선 분류되는지 (overview 통합 분류 보장)."""
    overlays = [
        {
            "phase1_case_id": "c1",
            "family_contributions": [],
            "top_family": None,
            "max_evidence_tier": None,
        }
    ]
    state = tab_phase2._resolve_phase2_empty_state(
        phase2_result=SimpleNamespace(),
        overlays=overlays,
        phase1_basis_status="unavailable",
        overlay_status="available",
    )
    assert state.state_id == tab_phase2._PHASE2_STATE_PHASE1_BASIS_UNAVAILABLE


# ── P6: 정적 reference artifact 격리 / 라벨링 ──────────────────


def test_phase2_signal_source_status_missing_when_summary_none():
    status, message = tab_phase2._resolve_phase2_signal_source_status(None)
    assert status == "missing_reference"
    assert message


def test_phase2_signal_source_status_static_reference_preview_for_year():
    summary = tab_phase2._load_phase2_partition_summary("2024")
    assert summary is not None
    status, message = tab_phase2._resolve_phase2_signal_source_status(summary)
    assert status == "static_reference_preview"
    assert "V7 fixed3" in message
    # source metadata 가 payload 안에 명시되어 있어야 한다.
    assert summary["_source"]["is_static_reference"] is True
    assert summary["_source"]["partition"] == "2024"


def test_phase2_signal_source_status_mixed_reference_when_year_missing(monkeypatch):
    """전체 merge 시 일부 연도 artifact 가 없으면 mixed_reference."""
    # 2022/2023 만 정상 load, 2024 는 None.
    real_loader = tab_phase2._load_phase2_partition_summary

    def _fake_loader(partition: str):
        if partition == "전체":
            return real_loader(partition)
        if partition == "2024":
            return None
        return real_loader(partition)

    monkeypatch.setattr(tab_phase2, "_load_phase2_partition_summary", _fake_loader)
    summary = _fake_loader("전체")
    assert summary is not None
    status, message = tab_phase2._resolve_phase2_signal_source_status(summary)
    assert status == "mixed_reference"
    assert "누락" in message
    assert summary["_source"]["missing_years"] == ["2024"]


def test_phase2_source_kpi_label_includes_reference_note():
    """KPI sub 라벨이 static/mixed 분기에서 "참고 기준" 명시."""
    static_label = tab_phase2._PHASE2_SOURCE_KPI_LABELS["static_reference_preview"]
    mixed_label = tab_phase2._PHASE2_SOURCE_KPI_LABELS["mixed_reference"]
    assert "참고 기준" in static_label
    assert "참고 기준" in mixed_label
    # 회사 scoped 분기는 빈 문자열이어야 한다 (silent).
    assert tab_phase2._PHASE2_SOURCE_KPI_LABELS["runtime_company_scoped"] == ""


def test_phase2_source_header_suffix_includes_reference_note():
    """차트/지도 헤더 suffix 도 같은 정책."""
    assert "참고 기준" in tab_phase2._PHASE2_SOURCE_HEADER_SUFFIX["static_reference_preview"]
    assert "참고 기준" in tab_phase2._PHASE2_SOURCE_HEADER_SUFFIX["mixed_reference"]
    assert tab_phase2._PHASE2_SOURCE_HEADER_SUFFIX["runtime_company_scoped"] == ""


def test_phase2_signal_source_suffix_helper_returns_runtime_for_unknown_status():
    """status 가 dict 에 없으면 빈 문자열 — 안전 fallback."""
    fake_summary = {"_source": {"status": "unknown_status_xyz", "message": ""}}
    assert tab_phase2._phase2_signal_source_suffix(fake_summary) == ""


def test_overlay_status_and_source_status_are_independent():
    """회사 scoped overlay 와 static preview source 는 다른 axis.

    overlay 가 정상 LOADED 이어도 partition_summary 가 static reference 면 source
    label 이 표시되어야 한다 — 두 status 가 서로 덮어쓰지 않는다.
    """
    summary = tab_phase2._load_phase2_partition_summary("2024")
    overlay_state = tab_phase2._resolve_phase2_empty_state(
        phase2_result=SimpleNamespace(),
        overlays=[{"phase1_case_id": "c1", "top_family": "duplicate"}],
        phase1_basis_status="canonical_in_memory",
        overlay_status="available",
    )
    source_status, _ = tab_phase2._resolve_phase2_signal_source_status(summary)
    # overlay 는 available, source 는 정적 reference — 충돌 없이 동시 존재.
    assert overlay_state.state_id == tab_phase2._PHASE2_STATE_AVAILABLE
    assert source_status == "static_reference_preview"
