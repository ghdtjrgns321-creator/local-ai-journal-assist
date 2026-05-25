"""Pre-analysis company settings editor for Phase 1/2/3 hyperparameters."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from config.settings import get_audit_rules
from dashboard._state import (
    KEY_ACTIVE_RESULT_TAB,
    KEY_COMPANY_CONTEXT,
    KEY_PENDING_RESULT_TAB,
    KEY_PRE_ANALYSIS_SETTINGS_OPEN,
    KEY_SETTINGS,
    KEY_SETTINGS_DIRTY,
    PAGE_OVERVIEW,
)
from dashboard.components.scroll_anchor import render_scroll_anchor
from src.company.merger import deep_merge

_APPROVAL_LEVEL_LABELS = [
    "automated_system",
    "junior_accountant",
    "senior_accountant",
    "controller",
    "manager",
    "cfo_board",
]


def render_pre_analysis_settings() -> bool:
    """Render company-level hyperparameter editor.

    Returns True when the caller should immediately run Phase 1.
    """
    ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
    repo = st.session_state.get("_company_repo")
    factory = st.session_state.get("_context_factory")
    if ctx is None or getattr(ctx, "is_anonymous", True) or repo is None:
        st.warning("회사와 감사연도를 선택한 상태에서만 회사별 설정을 저장할 수 있습니다.")
        return False

    settings = st.session_state.get(KEY_SETTINGS) or ctx.settings
    audit_rules = ctx.audit_rules or get_audit_rules()
    profile = repo.get_company(ctx.company_id)
    engagement = repo.get_engagement(ctx.company_id, ctx.engagement_id)
    holiday_key = f"pre_analysis_custom_holidays_{ctx.company_id}_{ctx.engagement_id}"
    if holiday_key not in st.session_state:
        st.session_state[holiday_key] = _normalize_date_list(settings.custom_holidays)

    # 휴일 카드는 form 밖 — 추가/삭제 시 즉시 디스크 저장(부분 rerun).
    _render_holiday_card(holiday_key, profile, repo, factory, ctx)

    with st.form("pre_analysis_company_settings_form"):
        settings_updates: dict[str, Any] = {}
        audit_rule_updates: dict[str, Any] = {}
        phase1_case_updates: dict[str, Any] = {}
        # form 안 다른 카드와 함께 저장될 수 있도록 현재 휴일 list 도 동기화.
        settings_updates["custom_holidays"] = list(st.session_state.get(holiday_key, []))
        st.caption(
            "고객사 회계정책, ERP source 코드, 계정체계와 다르면 오탐·누락이 커집니다. "
            "4개 영역으로 나눠 입력합니다."
        )
        engagement_updates = _render_engagement_policy(engagement, audit_rules)

        _render_company_policy(
            settings,
            audit_rules,
            settings_updates,
            audit_rule_updates,
        )

        st.divider()
        render_scroll_anchor("pre_analysis_phase1_actions")
        col_back, col_save, col_run = st.columns(3)
        with col_back:
            close_clicked = st.form_submit_button(
                "개요로 돌아가기",
                width="stretch",
            )
        with col_save:
            save_clicked = st.form_submit_button(
                "변경사항 저장",
                width="stretch",
            )
        with col_run:
            run_clicked = st.form_submit_button(
                "저장 후 Phase 1 분석",
                type="primary",
                width="stretch",
            )

    if close_clicked:
        st.session_state[KEY_PRE_ANALYSIS_SETTINGS_OPEN] = False
        st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_OVERVIEW
        st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_OVERVIEW
        st.rerun()

    if not (save_clicked or run_clicked):
        return False

    _save_company_settings(
        repo=repo,
        factory=factory,
        ctx=ctx,
        profile=profile,
        engagement=engagement,
        engagement_updates=engagement_updates,
        settings_updates=settings_updates,
        audit_rule_updates=audit_rule_updates,
        phase1_case_updates=phase1_case_updates,
    )
    st.success("회사별 설정을 저장했습니다. 이후 Phase 1/2/3 분석은 이 값을 사용합니다.")
    return bool(run_clicked)


def _render_engagement_policy(engagement, audit_rules: dict[str, Any]) -> dict[str, Any]:
    default_materiality = _default_materiality_amount(audit_rules)
    current_materiality = int(getattr(engagement, "materiality_amount", 0) or 0)
    display_materiality = current_materiality or default_materiality

    with st.container(border=True):
        st.markdown("**① 중요성 금액**")
        st.caption("감사연도별로 달라지는 중요성 금액입니다.")
        materiality_text = st.text_input(
            "중요성 금액",
            value=_format_krw(display_materiality),
            help=(
                f"현재 기본 제안값은 {default_materiality:,}원입니다. "
                "감사팀이 확정한 수행중요성 금액으로 바꿔 저장하세요."
            ),
        )

    return {"materiality_amount": _parse_krw(materiality_text)}


def _default_materiality_amount(audit_rules: dict[str, Any]) -> int:
    patterns = audit_rules.get("patterns", {})
    override = patterns.get("self_approval_immediate_override", {})
    return int(override.get("materiality_amount", 1_000_000_000) or 1_000_000_000)


def _holiday_add_cb(
    holiday_key: str,
    picker_key: str,
    profile,
    repo,
    factory,
    ctx,
) -> None:
    """on_click callback — 휴일 추가.

    Why: 토스트는 streamlit 기본 위치(우상단) 라 카드 내 시각 피드백과 어긋나
         사용자에게 어색하게 보인다. ss 에 inline message 를 적재해 카드
         내부에서 직접 표시한다.
    """
    flash_key = f"{holiday_key}_flash"
    picked = st.session_state.get(picker_key)
    new_holiday = _format_date(picked) if picked else ""
    if not new_holiday:
        st.session_state[flash_key] = ("warning", "날짜를 먼저 선택해 주세요.")
        return
    current = list(st.session_state.get(holiday_key, []))
    if new_holiday in current:
        st.session_state[flash_key] = ("info", f"이미 등록됨: {new_holiday}")
        return
    new_list = sorted([*current, new_holiday])
    st.session_state[holiday_key] = new_list
    _persist_holidays(profile, repo, factory, ctx, new_list)
    st.session_state[flash_key] = ("success", f"추가됨: {new_holiday}")


def _holiday_remove_cb(
    holiday_key: str,
    hday: str,
    profile,
    repo,
    factory,
    ctx,
) -> None:
    """on_click callback — 휴일 삭제."""
    flash_key = f"{holiday_key}_flash"
    current = list(st.session_state.get(holiday_key, []))
    new_list = [h for h in current if h != hday]
    st.session_state[holiday_key] = new_list
    _persist_holidays(profile, repo, factory, ctx, new_list)
    st.session_state[flash_key] = ("success", f"삭제됨: {hday}")


def _render_holiday_flash(holiday_key: str) -> None:
    """직전 add/remove 결과를 카드 내부에 inline 메시지로 표시 후 소비."""
    flash_key = f"{holiday_key}_flash"
    flash = st.session_state.pop(flash_key, None)
    if not flash:
        return
    level, message = flash
    color_map = {
        "success": ("#137333", "#E6F4EA"),
        "info": ("#1A56DB", "#E0E7FF"),
        "warning": ("#B45309", "#FEF3C7"),
    }
    fg, bg = color_map.get(level, ("#374151", "#F3F4F6"))
    st.markdown(
        f"<div style='margin:0.3rem 0; padding:6px 10px; background:{bg}; "
        f"color:{fg}; border-radius:6px; font-size:0.82rem; "
        f"font-weight:500;'>{message}</div>",
        unsafe_allow_html=True,
    )


@st.fragment
def _render_holiday_card(holiday_key: str, profile, repo, factory, ctx) -> None:
    """form 밖에서 즉시 저장되는 회사 지정 휴일 카드.

    Why: 일반 st.button + st.rerun() 이라도 페이지 전체가 다시 그려지면 4개 탭
         panel(개요/회사별 설정/Phase1/Phase2)이 모두 재렌더돼 매우 느렸다.
         @st.fragment 로 휴일 카드 영역만 부분 rerun 시켜 페이지 전체 재렌더
         비용을 제거한다. 디스크 저장은 즉시 일어나므로 사용자가 별도
         [변경사항 저장] 을 누르지 않아도 영구 보존된다.

         on_click callback 패턴: button 클릭 시 callback 이 ss 를 변경한 뒤
         streamlit 이 fragment 를 자동 rerun 하므로 명시적 st.rerun 불필요.
         이 패턴이 streamlit 1.55 에서 fragment 와 가장 안정적으로 동작.
    """
    selected_holidays: list[str] = list(st.session_state.get(holiday_key, []))
    picker_key = f"{holiday_key}_picker"

    with st.container(border=True):
        st.markdown("**회사 지정 휴일**")
        st.caption("추가·삭제 즉시 저장됩니다. 정상 시간 외/주말 위험 신호와 함께 사용됩니다.")

        _render_holiday_flash(holiday_key)

        c_date, c_add = st.columns([3, 1])
        with c_date:
            st.date_input(
                "추가할 휴일",
                value=date.today(),
                key=picker_key,
                label_visibility="collapsed",
            )
        with c_add:
            st.button(
                "휴일 추가",
                key=f"{holiday_key}_add",
                width="stretch",
                on_click=_holiday_add_cb,
                args=(holiday_key, picker_key, profile, repo, factory, ctx),
            )

        if not selected_holidays:
            st.caption("아직 추가된 휴일이 없습니다.")
            return

        st.markdown(
            "<div style='margin:0.4rem 0 0.2rem; color:#6B7280; font-size:0.8rem;'>"
            f"등록된 휴일 {len(selected_holidays):,}건"
            "</div>",
            unsafe_allow_html=True,
        )
        for hday in selected_holidays:
            c_label, c_x, _spacer = st.columns([2, 1, 9])
            with c_label:
                st.markdown(
                    "<div style='padding:6px 12px; background:#F1F3F5; "
                    "border:1px solid #E2E5E9; border-radius:6px; "
                    "color:#374151; font-size:0.88rem; "
                    "display:flex; align-items:center; justify-content:center; "
                    f"margin:2px 0;'>📅 {hday}</div>",
                    unsafe_allow_html=True,
                )
            with c_x:
                st.button(
                    "✕",
                    key=f"{holiday_key}_rm_{hday}",
                    width="stretch",
                    help=f"{hday} 삭제",
                    on_click=_holiday_remove_cb,
                    args=(holiday_key, hday, profile, repo, factory, ctx),
                )


def _persist_holidays(profile, repo, factory, ctx, holidays: list[str]) -> None:
    """회사 지정 휴일만 즉시 디스크 저장. settings_overrides.custom_holidays 갱신.

    Why: ctx/settings 동기화는 비용이 크고 fragment 안에서 외부 ss 를 흔들면
         streamlit 이 fragment rerun 을 무시하는 경우가 있다. 디스크 저장만
         수행하고, ss 의 KEY_SETTINGS·KEY_COMPANY_CONTEXT 갱신은 사용자가
         메인 form 의 [변경사항 저장] 을 누를 때 _save_company_settings 에서
         일괄 처리한다. ss[holiday_key] 는 fragment 가 직접 갱신하므로 UI
         즉시 반영에는 영향 없다.
    """
    overrides = dict(profile.settings_overrides or {})
    overrides["custom_holidays"] = holidays
    try:
        repo.update_company(profile.model_copy(update={"settings_overrides": overrides}))
    except Exception as exc:  # noqa: BLE001 — 사용자에게 디스크 오류만 표시
        st.warning(f"휴일 디스크 저장 실패: {exc}")


def _render_company_policy(
    settings,
    audit_rules,
    settings_updates,
    audit_rule_updates,
) -> None:
    # 카드 2 — 회계 일정
    with st.container(border=True):
        st.markdown("**② 회계 일정**")
        st.caption("결산 기준일과 이상 거래 검토 시점을 정합니다.")
        c1, c2 = st.columns(2)
        with c1:
            settings_updates["fiscal_year_start"] = st.number_input(
                "회계연도 시작월",
                min_value=1,
                max_value=12,
                value=int(settings.fiscal_year_start),
                step=1,
            )
        with c2:
            settings_updates["period_end_margin_days"] = st.slider(
                "월말/연말 전표로 보는 기간(일)",
                1,
                15,
                int(settings.period_end_margin_days),
                help=("월말 또는 연말 기준일 앞뒤 며칠까지를 결산 전표로 볼지 정합니다."),
            )

    # 카드 3 — 근무 시간 정책
    with st.container(border=True):
        st.markdown("**③ 근무 시간 정책**")
        st.caption("정상 시간 외 승인·전표를 위험 신호로 다루기 위한 기준입니다.")
        c1, c2 = st.columns(2)
        with c1:
            settings_updates["normal_hours_start"] = _time_to_hour(
                st.time_input(
                    "정상 업무 시작 시간",
                    value=_hour_to_time(settings.normal_hours_start),
                    step=timedelta(minutes=30),
                )
            )
            settings_updates["midnight_start"] = _time_to_hour(
                st.time_input(
                    "심야 시간 시작",
                    value=_hour_to_time(settings.midnight_start),
                    step=timedelta(minutes=30),
                )
            )
        with c2:
            settings_updates["normal_hours_end"] = _time_to_hour(
                st.time_input(
                    "정상 업무 종료 시간",
                    value=_hour_to_time(settings.normal_hours_end),
                    step=timedelta(minutes=30),
                )
            )
            settings_updates["midnight_end"] = _time_to_hour(
                st.time_input(
                    "심야 시간 종료",
                    value=_hour_to_time(settings.midnight_end),
                    step=timedelta(minutes=30),
                )
            )

    # 카드 4 — 승인권한 단계
    with st.container(border=True):
        st.markdown("**④ 승인권한 단계 (KRW)**")
        st.caption("Level 번호가 클수록 큰 금액 결재권. 금액 0 또는 빈 값은 저장 시 제거됩니다.")
        threshold_df = pd.DataFrame(
            {
                "승인권한": _approval_level_labels(len(settings.approval_thresholds)),
                "금액": [_format_krw(value) for value in settings.approval_thresholds],
            }
        )
        edited = st.data_editor(
            threshold_df,
            hide_index=True,
            num_rows="fixed",
            width="stretch",
            column_config={
                "승인권한": st.column_config.TextColumn(
                    "승인권한",
                    help="승인권한 역할",
                    width="small",
                    disabled=True,
                ),
                "금액": st.column_config.TextColumn(
                    "금액(₩)",
                    help="천 단위 콤마를 포함해 입력할 수 있습니다.",
                ),
            },
        )
        settings_updates["approval_thresholds"] = [
            _parse_krw(value) for value in edited["금액"].tolist()
        ]

    # 카드 5 — 패턴/식별어
    with st.container(border=True):
        st.markdown("**⑤ 패턴 · 계정 식별어**")
        st.caption("ERP source 코드와 계정 prefix를 회사 실제 값에 맞춰야 룰 정확도가 올라갑니다.")
        patterns = audit_rules.get("patterns", {})
        evidence = audit_rules.get("evidence", {})
        col_a, col_b = st.columns(2)
        with col_a:
            manual_sources = _parse_list(
                st.text_input(
                    "수기/조정 source 코드",
                    value=_join_list(patterns.get("manual_source_codes", [])),
                )
            )
            auto_sources = _parse_list(
                st.text_input(
                    "자동/시스템 source 코드",
                    value=_join_list(settings.auto_entry_sources),
                    help=(
                        "자동 전표로 보아 급속 승인·심야 사용자 행동 검토에서 제외할 source입니다."
                    ),
                )
            )
            revenue_prefixes = _parse_list(
                st.text_input(
                    "매출 계정 prefix",
                    value=_join_list(patterns.get("revenue_account_prefixes", [])),
                )
            )
            intercompany_ids = _parse_list(
                st.text_input(
                    "관계사 식별어",
                    value=_join_list(patterns.get("intercompany_identifiers", [])),
                )
            )
        with col_b:
            batch_sources = _parse_list(
                st.text_input(
                    "배치/인터페이스 source 코드",
                    value=_join_list(settings.batch_source_values),
                    help="대량 자동 입력 전표를 식별하는 source입니다.",
                )
            )
            expense_prefixes = _parse_list(
                st.text_input(
                    "비용 계정 prefix",
                    value=_join_list(evidence.get("expense_account_prefixes", [])),
                )
            )
            suspense_codes = _parse_list(
                st.text_input(
                    "가계정 계정코드",
                    value=_join_list(patterns.get("suspense_account_codes", [])),
                )
            )
            suspense_keywords = _parse_list(
                st.text_input(
                    "가계정/미정리 키워드",
                    value=_join_list(patterns.get("suspense_keywords", [])),
                )
            )
            high_risk_prefixes = _parse_list(
                st.text_input(
                    "민감 계정 prefix",
                    value=_join_list(
                        patterns.get("high_risk_account_use", {}).get("account_prefixes", [])
                    ),
                )
            )

        audit_rule_updates.update(
            {
                "patterns": {
                    "manual_source_codes": manual_sources,
                    "revenue_account_prefixes": revenue_prefixes,
                    "intercompany_identifiers": intercompany_ids,
                    "suspense_account_codes": suspense_codes,
                    "suspense_keywords": suspense_keywords,
                    "high_risk_account_use": {"account_prefixes": high_risk_prefixes},
                },
                "evidence": {"expense_account_prefixes": expense_prefixes},
            }
        )
        settings_updates["auto_entry_sources"] = auto_sources
        settings_updates["batch_source_values"] = batch_sources


def _save_company_settings(
    *,
    repo,
    factory,
    ctx,
    profile,
    engagement,
    engagement_updates: dict[str, Any],
    settings_updates: dict[str, Any],
    audit_rule_updates: dict[str, Any],
    phase1_case_updates: dict[str, Any],
) -> None:
    compact_settings = {
        key: value
        for key, value in settings_updates.items()
        if getattr(ctx.settings, key, None) != value
    }
    merged_settings = deep_merge(profile.settings_overrides or {}, compact_settings)
    repo.update_company(profile.model_copy(update={"settings_overrides": merged_settings}))

    compact_engagement = {
        key: value
        for key, value in engagement_updates.items()
        if getattr(engagement, key, None) != value
    }
    if compact_engagement:
        repo.update_engagement(
            ctx.company_id,
            engagement.model_copy(update=compact_engagement),
        )

    if audit_rule_updates:
        existing_rules = repo.load_company_audit_rules(ctx.company_id) or {}
        repo.save_company_yaml(
            ctx.company_id,
            "audit_rules.yaml",
            deep_merge(existing_rules, audit_rule_updates),
        )

    if phase1_case_updates:
        existing_phase1 = repo.load_company_phase1_case(ctx.company_id) or {}
        repo.save_company_yaml(
            ctx.company_id,
            "phase1_case.yaml",
            deep_merge(existing_phase1, phase1_case_updates),
        )

    if factory is not None:
        factory.invalidate(ctx.company_id, ctx.engagement_id)
        new_ctx = factory.create(ctx.company_id, ctx.engagement_id)
        st.session_state[KEY_COMPANY_CONTEXT] = new_ctx
        st.session_state[KEY_SETTINGS] = new_ctx.settings
    else:
        st.session_state[KEY_SETTINGS] = ctx.settings.model_copy(update=compact_settings)

    st.session_state[KEY_SETTINGS_DIRTY] = False


def _join_list(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, str):
        return values
    return ", ".join(str(v) for v in values)


def _approval_level_labels(count: int) -> list[str]:
    labels = _APPROVAL_LEVEL_LABELS[:count]
    if len(labels) < count:
        labels.extend(f"level_{index}" for index in range(len(labels) + 1, count + 1))
    return labels


def _format_krw(value: Any) -> str:
    return f"{int(value):,}"


def _parse_krw(value: Any) -> int:
    text = str(value or "0").replace(",", "").strip()
    return int(float(text)) if text else 0


def _parse_list(text: str) -> list[str]:
    return [item.strip() for item in text.replace("\n", ",").split(",") if item.strip()]


def _format_date(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _normalize_date_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = _parse_list(values)
    else:
        raw_values = list(values)
    return sorted({_format_date(value) for value in raw_values if str(value).strip()})


def _hour_to_time(value: Any) -> time:
    hour_float = float(value or 0) % 24
    hour = int(hour_float)
    minute = int(round((hour_float - hour) * 60)) % 60
    return time(hour=hour, minute=minute)


def _time_to_hour(value: time) -> float:
    return round(value.hour + value.minute / 60.0, 4)
