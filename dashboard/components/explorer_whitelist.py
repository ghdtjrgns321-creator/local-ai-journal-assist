"""HITL 예외 처리 UI — whitelist 저장/삭제/목록 + 메모리 동기화.

Why: 감사인이 오탐(False Positive)으로 판정한 전표를
     whitelist 테이블에 등록하여 반복 알람을 제거하는 워크플로우.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from dashboard._state import KEY_SELECTED_DOC

if TYPE_CHECKING:
    import duckdb


def render_whitelist(
    doc_id: str,
    conn: "duckdb.DuckDBPyConnection",
    batch_id: str,
    result_data: pd.DataFrame,
) -> bool:
    """HITL 예외 처리 UI 렌더링.

    Args:
        doc_id: 선택된 document_id.
        conn: DuckDB 연결.
        batch_id: 현재 배치 식별자.
        result_data: PipelineResult.data (메모리 동기화 대상).

    Returns:
        True이면 whitelist 변경됨 → 호출측에서 st.rerun() 필요.
    """
    from src.db.queries import execute_preset, execute_write

    modified = False

    st.divider()
    st.subheader("예외 처리 (HITL)")

    # ── 예외 저장 폼 ──
    reason = st.text_input(
        "예외 사유",
        placeholder="정상 거래로 확인됨 (예: 정기 결산 전표)",
        key=f"whitelist_reason_{doc_id}",
    )

    if st.button("예외 저장", key=f"whitelist_save_{doc_id}", type="primary"):
        # Why: 다중 라인아이템 전표에서 행마다 flagged_rules가 다를 수 있으므로
        #      전체 행에서 룰 코드를 합산. iloc[0]만 읽으면 첫 행이 비어있을 때 오탐.
        doc_mask = result_data["document_id"] == doc_id
        all_flagged = result_data.loc[doc_mask, "flagged_rules"].dropna()
        all_rules: set[str] = set()
        for entry in all_flagged:
            all_rules.update(r.strip() for r in str(entry).split(",") if r.strip())
        rule_codes = sorted(all_rules)

        if not rule_codes:
            st.warning("예외 처리할 탐지 룰이 없습니다.")
        else:
            saved_count = 0
            for rule_code in rule_codes:
                try:
                    execute_write(
                        conn,
                        "insert_whitelist",
                        (batch_id, doc_id, rule_code, reason, "auditor"),
                    )
                    saved_count += 1
                except Exception as exc:
                    st.error(f"저장 실패 ({rule_code}): {exc}")

            if saved_count > 0:
                # Why: DB 저장 후 인메모리 DataFrame도 동기화
                #      다른 탭(Summary 등) 집계에 즉시 반영
                _sync_memory(result_data, doc_id, rule_codes)
                st.session_state[KEY_SELECTED_DOC] = doc_id
                st.success(f"{saved_count}건 예외 처리 완료 ({', '.join(rule_codes)})")
                modified = True

    # ── 현재 배치 whitelist 목록 ──
    st.divider()
    st.subheader("예외 처리 목록")

    try:
        wl_df = execute_preset(conn, "batch_whitelist", batch_id=batch_id)
    except Exception:
        wl_df = pd.DataFrame()

    if wl_df.empty:
        st.info("등록된 예외 처리 항목이 없습니다.")
    else:
        # Why: 삭제 버튼을 각 행에 배치하기 위해 row-by-row 렌더링
        for _, row in wl_df.iterrows():
            col_info, col_del = st.columns([5, 1])
            with col_info:
                st.text(
                    f"[{row['document_id']}] {row['rule_code']} "
                    f"— {row.get('reason', '') or '사유 없음'} "
                    f"({str(row.get('created_at', ''))[:19]})"
                )
            with col_del:
                if st.button("삭제", key=f"wl_del_{row['id']}"):
                    try:
                        execute_write(conn, "delete_whitelist", (int(row["id"]),))
                        return True  # Why: 삭제 즉시 rerun하여 목록 불일치 방지
                    except Exception as exc:
                        st.error(f"삭제 실패: {exc}")

    return modified


def _sync_memory(
    result_data: pd.DataFrame,
    doc_id: str,
    rule_codes: list[str],
) -> None:
    """인메모리 DataFrame에서 예외 처리된 룰을 제거하고 점수 하향.

    Why: DB에만 반영하면 Tab 1 Summary 등의 집계에
         예외 처리된 전표가 여전히 위험 건으로 카운트됨.
    """
    mask = result_data["document_id"] == doc_id

    # flagged_rules에서 예외 처리된 rule_code 제거
    current_rules = str(result_data.loc[mask, "flagged_rules"].iloc[0])
    remaining = [
        r.strip() for r in current_rules.split(",")
        if r.strip() and r.strip() not in rule_codes
    ]
    result_data.loc[mask, "flagged_rules"] = ",".join(remaining)

    # Why: 남은 룰이 없으면 정상으로 하향 조정
    if not remaining:
        result_data.loc[mask, "risk_level"] = "Normal"
        result_data.loc[mask, "anomaly_score"] = 0.0
