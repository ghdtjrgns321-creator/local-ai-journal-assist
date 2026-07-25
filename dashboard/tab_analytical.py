"""분석적 검토(PHASE1-2) 결과 탭 — 모집단 단위 신호 표면.

3-surface 불변식: 룰 기반(PHASE1-1) / 분석적 검토(PHASE1-2) / VAE(PHASE2) 는 비병합이다.
이 탭은 "전표 한 장으론 안 보이고 계정·거래처를 모아야 드러나는" 신호(ISA 520)만 소유한다.

점수 비병합: 여기 finding 은 룰 case 의 priority_score 에 참여하지 않는다. 룰 결과 화면에는
배지(badge_tags)로만 오버레이되고, 검토 목록의 절단은 이 탭이 소유하지 않는다(신호만 생성).

데이터는 phase1_result(PipelineResult)에 이미 산출된 것을 읽는다(별도 실행 없음):
  - macro_findings   : Benford(L4-02) · 라운드넘버 밀집도(ROUND-DENSITY)
  - partner_findings : 첫등장 / 희소 / 휴면재활성 거래처

여기 남은 세 신호는 전기 없이 당기 모집단만으로 판정된다. 반대로 전기를 붙여야 계산되는
계정활동변동(D01)·월별비율변동(D02)은 전제와 질문이 전기 비교와 같아 그 탭에서 표시한다
(dashboard/tab_comparison.py). 신호 자체는 PHASE1-2 소유 그대로이며 표시 위치만 다르다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

from dashboard.components.charts.round_density_charts import (
    SCOPE_LABELS,
    SEVERITY_LABELS,
    round_density_bar,
    scope_label,
)
from src.export.phase1_case_view import (
    build_phase1_macro_finding_queue,
    build_phase1_partner_finding_queue,
    resolve_phase1_case_result,
)

# 차트에 그릴 최대 finding 수 — 초과분은 표로만. 세로 무한 확장 방지.
_ROUND_DENSITY_TOP_N = 20

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
    round_density = build_phase1_macro_finding_queue(pr, rule_id="ROUND-DENSITY")

    sub_tabs = st.tabs(["Benford 분포", "Round Number 밀집", "거래처 신호"])
    with sub_tabs[0]:
        _render_benford(pr)
    with sub_tabs[1]:
        _render_round_density(round_density)
    with sub_tabs[2]:
        _render_partners(pr)


# ── Benford ─────────────────────────────────────────────────


def _render_benford(pr: PipelineResult) -> None:
    """전체 첫자리 분포 차트 + 계정별 분리 분석 (orphan tab_benford 재사용)."""
    from dashboard import tab_benford

    tab_benford.render(pr)


# ── 라운드넘버 밀집도 ──────────────────────────────────────────


def _render_round_density(findings: list[dict[str, Any]]) -> None:
    """둥근 금액이 모집단에서 baseline 대비 과집중한 그룹 — 차트가 본문, 표는 부록."""
    st.markdown("##### Round Number 밀집")
    st.caption(
        "계정·월·작성자 등 그룹에서 Round Number 비율이 원장 기준선보다 5%p 이상 "
        "높은 지점(표본 100건 이상 그룹만 검정)"
    )
    if not findings:
        st.info("Round Number 밀집 finding 이 없습니다.")
        return

    selected = _select_round_density_scope(findings)
    shown = [f for f in findings if not selected or str(f.get("scope")) == selected]
    if not shown:
        st.info("선택한 축에는 finding 이 없습니다.")
        return

    st.plotly_chart(
        round_density_bar(shown, top_n=_ROUND_DENSITY_TOP_N),
        width="stretch",
        key=f"round_density_bar_{selected or 'all'}",
    )
    if len(shown) > _ROUND_DENSITY_TOP_N:
        st.caption(
            f"기준선 초과분 상위 {_ROUND_DENSITY_TOP_N}개만 그렸습니다 "
            f"(선택 축 finding {len(shown):,}개). 전체는 아래 표에서 확인하세요."
        )

    with st.expander(f"finding 상세 표 ({len(shown):,}건)"):
        st.dataframe(
            _round_density_table(shown),
            width="stretch",
            hide_index=True,
            column_config={
                "둥근비율": st.column_config.NumberColumn(format="percent"),
                "기준선": st.column_config.NumberColumn(format="percent"),
                "기준선 초과": st.column_config.NumberColumn(format="percent"),
                "p-value": st.column_config.NumberColumn(format="%.4f"),
            },
        )


def _select_round_density_scope(findings: list[dict[str, Any]]) -> str | None:
    """축 라디오 — finding 이 실제로 있는 축만 노출. 반환값 None 은 전체."""
    present = {str(f.get("scope") or "") for f in findings if f.get("scope")}
    # Why: 등장 순에 맡기면 데이터마다 버튼 위치가 바뀐다 — 축 정의 순서로 고정.
    scopes = [s for s in SCOPE_LABELS if s in present] + sorted(present - set(SCOPE_LABELS))
    if len(scopes) < 2:
        return None
    labels = ["전체"] + [scope_label(s) for s in scopes]
    choice = st.radio(
        "축",
        options=labels,
        horizontal=True,
        key="analytical_round_density_scope",
    )
    if choice in (None, "전체"):
        return None
    return next((s for s in scopes if scope_label(s) == choice), None)


def _round_density_table(findings: list[dict[str, Any]]) -> pd.DataFrame:
    """상세 표 — 차트와 같은 정렬(기준선 초과분 내림차순)."""
    rows = []
    for item in findings:
        metrics = item.get("metrics") or {}
        rows.append(
            {
                "축": scope_label(str(item.get("scope") or "")),
                "그룹": item.get("group_key"),
                "표본": item.get("sample_size"),
                "둥근건수": item.get("candidate_rows"),
                "둥근비율": metrics.get("round_ratio"),
                "기준선": metrics.get("baseline_ratio"),
                "기준선 초과": metrics.get("excess"),
                "p-value": metrics.get("p_value"),
                "신호": SEVERITY_LABELS.get(
                    str(item.get("finding_severity") or ""),
                    item.get("finding_severity"),
                ),
            }
        )
    table = pd.DataFrame(rows)
    if "기준선 초과" in table.columns:
        table = table.sort_values("기준선 초과", ascending=False)
    return table


# ── 거래처 신호 ────────────────────────────────────────────────


def _render_partners(pr: PipelineResult) -> None:
    """첫등장/희소/휴면재활성 거래처 — 신호 필터 연동."""
    st.markdown("##### 거래처 단위 신호")
    st.caption("첫 등장·희소·휴면 후 재활성 거래처 — 적발이 아닌 검토 신호")
    st.markdown(
        "<div class='signal-legend'>"
        "<div class='signal-legend__item'>"
        "<span class='signal-legend__term'>첫 등장</span>"
        "당기에 처음 등장한 거래처</div>"
        "<div class='signal-legend__item'>"
        "<span class='signal-legend__term'>희소</span>"
        "당기 거래건수가 하위 10% 이하</div>"
        "<div class='signal-legend__item'>"
        "<span class='signal-legend__term'>휴면 후 재활성</span>"
        "과거 거래 有, 직전 회계연도 거래 無, 당기에 다시 거래한 거래처</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    label = st.segmented_control(
        "신호 필터",
        options=list(_PARTNER_SIGNAL_LABELS.keys()),
        default="전체",
        key="analytical_partner_signal_filter",
    )
    signal = _PARTNER_SIGNAL_LABELS.get(label or "전체")
    findings = build_phase1_partner_finding_queue(pr, signal=signal)
    diagnostics = _partner_diagnostics(pr)
    _render_partner_coverage(diagnostics)
    if not findings:
        st.info(_empty_partner_message(signal, diagnostics))
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
            "총금액": st.column_config.NumberColumn(format="localized"),
        },
    )


def _partner_diagnostics(pr: PipelineResult) -> dict[str, Any]:
    """거래처 신호 판정 가능 여부 — PHASE1 아티팩트 metadata 에서 읽는다."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {}
    value = phase1.metadata.get("partner_signal_diagnostics") or {}
    return value if isinstance(value, dict) else {}


def _render_partner_coverage(diagnostics: dict[str, Any]) -> None:
    """비교에 쓰인 회계연도와 미판정 신호를 먼저 밝힌다 — 빈 목록의 오독 방지."""
    years = [int(y) for y in (diagnostics.get("observed_years") or [])]
    if not years:
        return
    span = str(years[0]) if len(years) == 1 else f"{years[0]}~{years[-1]}"
    unevaluated = [
        label
        for key, label in (("first_seen_evaluated", "첫 등장"), ("dormant_evaluated", "휴면재활성"))
        if not diagnostics.get(key)
    ]
    text = f"비교 기준 회계연도: {span} ({len(years)}개 연도)"
    if unevaluated:
        text += f" · {'·'.join(unevaluated)}은 비교할 과거 연도가 부족해 판정하지 않았습니다"
    st.caption(text)


_PARTNER_UNEVALUATED_REASON: dict[str, tuple[str, str, str]] = {
    # signal → (판정 가능 여부 키, 한글 라벨, 미판정 사유)
    "first_seen": ("first_seen_evaluated", "첫 등장", "비교할 과거 연도 데이터가 없습니다"),
    "dormant": (
        "dormant_evaluated",
        "휴면재활성",
        "직전 연도와 그 이전 연도가 모두 있어야 판정할 수 있습니다",
    ),
    "rare": ("rare_evaluated", "희소", "당기 거래처 수가 최소 모집단에 못 미칩니다"),
}


def _empty_partner_message(signal: str | None, diagnostics: dict[str, Any]) -> str:
    """빈 목록의 의미를 '0건'과 '미판정'으로 갈라 문장으로 만든다."""
    if not diagnostics:
        return "해당 조건의 거래처 신호가 없습니다."

    if signal:
        entry = _PARTNER_UNEVALUATED_REASON.get(signal)
        if entry and not diagnostics.get(entry[0]):
            return f"{entry[1]}은 판정하지 않았습니다 — {entry[2]}. (신호 0건이라는 뜻이 아닙니다)"
        return "판정 결과 해당 신호에 걸린 거래처가 없습니다. (0건)"

    unevaluated = [
        label
        for _, (key, label, _reason) in _PARTNER_UNEVALUATED_REASON.items()
        if not diagnostics.get(key)
    ]
    if unevaluated:
        return (
            f"{'·'.join(unevaluated)}은 비교 데이터가 부족해 판정하지 않았고, "
            "나머지 신호는 0건입니다."
        )
    return "판정 결과 신호에 걸린 거래처가 없습니다. (0건)"
