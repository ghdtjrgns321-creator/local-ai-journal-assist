"""분석적 검토(PHASE1-2) 결과 탭 — 모집단 단위 신호 표면.

3-surface 불변식: 룰 기반(PHASE1-1) / 분석적 검토(PHASE1-2) / VAE(PHASE2) 는 비병합이다.
이 탭은 "전표 한 장으론 안 보이고 계정·거래처를 모아야 드러나는" 신호(ISA 520)만 소유한다.

점수 비병합: 여기 finding 은 룰 case 의 priority_score 에 참여하지 않는다. 룰 결과 화면에는
배지(badge_tags)로만 오버레이되고, 검토 목록의 절단은 이 탭이 소유하지 않는다(신호만 생성).

데이터는 phase1_result(PipelineResult)에 이미 산출된 것을 읽는다(별도 실행 없음):
  - macro_findings   : Benford(L4-02) · 계정활동변동(D01) · 월별비율변동(D02) · 라운드넘버 밀집도(ROUND-DENSITY)
  - partner_findings : 첫등장 / 희소 / 휴면재활성 거래처
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

from src.export.phase1_case_view import (
    build_phase1_macro_finding_queue,
    build_phase1_partner_finding_queue,
    resolve_phase1_case_result,
)

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

# 거래처 신호 필터 라벨 → build_phase1_partner_finding_queue signal 문자열.
_PARTNER_SIGNAL_LABELS: dict[str, str | None] = {
    "전체": None,
    "첫 등장": "first_seen",
    "희소": "rare",
    "휴면재활성": "dormant",
}
_PARTNER_SIGNAL_KR: dict[str, str] = {
    "first_seen": "첫 등장",
    "rare": "희소",
    "dormant": "휴면재활성",
}


def render(prep_result, phase1_result: PipelineResult | None) -> None:
    """분석적 검토 탭 진입점 — 룰 실행과 동시에 산출된 모집단 신호를 표면화."""
    st.subheader("분석적 검토")
    st.caption("계정·거래처를 모아야 드러나는 모집단 단위 신호, 감사인이 봐야 할 검토 후보")

    if phase1_result is None or resolve_phase1_case_result(phase1_result) is None:
        st.info("룰 기반 분석을 먼저 실행하면 분석적 검토 신호가 함께 산출됩니다.")
        if prep_result is None:
            st.caption("준비 데이터가 없습니다. 먼저 데이터 업로드/매핑을 완료하세요.")
        return

    pr = phase1_result
    benford = build_phase1_macro_finding_queue(pr, rule_id="L4-02")
    round_density = build_phase1_macro_finding_queue(pr, rule_id="ROUND-DENSITY")
    d01 = build_phase1_macro_finding_queue(pr, rule_id="D01")
    d02 = build_phase1_macro_finding_queue(pr, rule_id="D02")

    sub_tabs = st.tabs(["Benford 분포", "둥근 금액 밀집", "거래처 신호", "계정·비율 변동"])
    with sub_tabs[0]:
        _render_benford(pr, benford)
    with sub_tabs[1]:
        _render_round_density(round_density)
    with sub_tabs[2]:
        _render_partners(pr)
    with sub_tabs[3]:
        _render_variance(d01, d02)


# ── Benford ─────────────────────────────────────────────────


def _render_benford(pr: PipelineResult, benford: list[dict[str, Any]]) -> None:
    """전체 첫자리 분포 차트(orphan tab_benford 재사용) + 계정별 이상 finding 표."""
    from dashboard import tab_benford

    tab_benford.render(pr)

    st.divider()
    st.markdown("##### 계정 단위 Benford 이상 (L4-02)")
    if not benford:
        st.caption("계정 단위 Benford 이상 finding 이 없습니다.")
        return
    rows = [
        {
            "계정": item.get("gl_account"),
            "표본": item.get("sample_size"),
            "신호강도": item.get("review_score"),
            "심각도": item.get("finding_severity"),
            "후보행": item.get("candidate_rows"),
            "이상자리": ", ".join(str(d) for d in (item.get("flagged_digits") or [])),
            "MAD": (item.get("metrics") or {}).get("mad"),
            "chi2 p": (item.get("metrics") or {}).get("chi2_p_value"),
        }
        for item in benford
    ]
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "신호강도": st.column_config.NumberColumn(format="%.3f"),
            "MAD": st.column_config.NumberColumn(format="%.4f"),
            "chi2 p": st.column_config.NumberColumn(format="%.4f"),
        },
    )


# ── 라운드넘버 밀집도 ──────────────────────────────────────────


def _render_round_density(findings: list[dict[str, Any]]) -> None:
    """둥근 금액이 모집단에서 baseline 대비 과집중한 그룹."""
    st.markdown("##### 둥근 금액 모집단 밀집 (ROUND-DENSITY)")
    st.caption(
        "계정·월·작성자 등 그룹에서 둥근 금액 비율이 기준선보다 높은 지점입니다. "
        "예산·계약 금액도 둥글 수 있어 확정 예외가 아닙니다."
    )
    if not findings:
        st.info("둥근 금액 밀집 finding 이 없습니다.")
        return
    rows = [
        {
            "축": item.get("scope"),
            "그룹": item.get("group_key"),
            "표본": item.get("sample_size"),
            "둥근건수": item.get("candidate_rows"),
            "둥근비율": (item.get("metrics") or {}).get("round_ratio"),
            "기준선": (item.get("metrics") or {}).get("baseline_ratio"),
            "초과분": (item.get("metrics") or {}).get("excess"),
            "p-value": (item.get("metrics") or {}).get("p_value"),
            "심각도": item.get("finding_severity"),
        }
        for item in findings
    ]
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "둥근비율": st.column_config.NumberColumn(format="%.3f"),
            "기준선": st.column_config.NumberColumn(format="%.3f"),
            "초과분": st.column_config.NumberColumn(format="%.3f"),
            "p-value": st.column_config.NumberColumn(format="%.4f"),
        },
    )


# ── 거래처 신호 ────────────────────────────────────────────────


def _render_partners(pr: PipelineResult) -> None:
    """첫등장/희소/휴면재활성 거래처 — 신호 필터 연동."""
    st.markdown("##### 거래처 단위 신호")
    st.caption(
        "원장 첫 등장·희소·휴면 후 재활성 거래처입니다. 정상 신규 공급처도 첫 등장이므로 "
        "적발이 아니라 검토 신호입니다."
    )
    label = st.segmented_control(
        "신호 필터",
        options=list(_PARTNER_SIGNAL_LABELS.keys()),
        default="전체",
        key="analytical_partner_signal_filter",
    )
    signal = _PARTNER_SIGNAL_LABELS.get(label or "전체")
    findings = build_phase1_partner_finding_queue(pr, signal=signal)
    if not findings:
        st.info("해당 조건의 거래처 신호가 없습니다. (첫등장/휴면은 다년 데이터 필요)")
        return
    rows = [
        {
            "거래처": item.get("trading_partner"),
            "신호": " · ".join(
                _PARTNER_SIGNAL_KR.get(str(s), str(s)) for s in (item.get("signals") or [])
            ),
            "거래건수": item.get("txn_count"),
            "총금액": item.get("total_amount"),
        }
        for item in findings
    ]
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "총금액": st.column_config.NumberColumn(format="%.0f"),
        },
    )


# ── 계정·비율 변동 (D01/D02) ──────────────────────────────────


def _render_variance(d01: list[dict[str, Any]], d02: list[dict[str, Any]]) -> None:
    """전기 대비 계정 활동(D01) / 월별 비율 분포(D02) 변동."""
    st.markdown("##### 계정 활동 변동 (D01)")
    st.caption("전기 대비 계정별 금액·건수·평균 활동이 크게 바뀐 계정입니다.")
    if d01:
        rows = [
            {
                "계정": item.get("gl_account"),
                "당기": item.get("fiscal_year"),
                "전기": item.get("prior_fiscal_year"),
                "검토행": item.get("review_row_count"),
                "가중변동": item.get("review_score"),
                "우선순위": item.get("macro_priority_score"),
                "버킷": item.get("queue_bucket"),
            }
            for item in d01
        ]
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "가중변동": st.column_config.NumberColumn(format="%.3f"),
                "우선순위": st.column_config.NumberColumn(format="%.3f"),
            },
        )
    else:
        st.info("계정 활동 변동 finding 이 없습니다. (전기 데이터 필요)")

    st.divider()
    st.markdown("##### 월별 비율 분포 변동 (D02)")
    st.caption("전기 대비 계정의 월별 금액 분포 모양이 바뀐 지점입니다(JSD 기준).")
    if d02:
        rows = [
            {
                "계정": item.get("gl_account"),
                "당기": item.get("fiscal_year"),
                "전기": item.get("prior_fiscal_year"),
                "JSD": item.get("review_score"),
                "우선순위": item.get("macro_priority_score"),
                "시나리오": item.get("scenario_type"),
                "버킷": item.get("queue_bucket"),
            }
            for item in d02
        ]
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "JSD": st.column_config.NumberColumn(format="%.4f"),
                "우선순위": st.column_config.NumberColumn(format="%.3f"),
            },
        )
    else:
        st.info("월별 비율 분포 변동 finding 이 없습니다. (전기 데이터 필요)")
