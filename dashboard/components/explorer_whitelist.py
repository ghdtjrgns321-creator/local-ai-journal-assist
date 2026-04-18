"""HITL 예외 처리 UI with whitelist CRUD and normalized feedback events."""

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
    """Render whitelist controls for a selected document."""
    from src.db.audit_log import record_event
    from src.db.queries import execute_preset, execute_write
    from src.hitl.feedback_store import build_feedback_event, record_feedback_event

    modified = False
    company_id, engagement_id = _load_engagement_identity(conn)

    st.divider()
    st.subheader("예외 처리 (HITL)")

    reason = st.text_input(
        "예외 사유",
        placeholder="정상 거래로 확인됨 (예: 정기 결산 전표)",
        key=f"whitelist_reason_{doc_id}",
    )

    if st.button("예외 저장", key=f"whitelist_save_{doc_id}", type="primary"):
        doc_mask = result_data["document_id"] == doc_id
        all_flagged = result_data.loc[doc_mask, "flagged_rules"].dropna()
        all_rules: set[str] = set()
        for entry in all_flagged:
            all_rules.update(rule.strip() for rule in str(entry).split(",") if rule.strip())
        rule_codes = sorted(all_rules)

        if not rule_codes:
            st.warning("예외 처리할 탐지 룰이 없습니다.")
        else:
            saved_rules: list[str] = []
            for rule_code in rule_codes:
                try:
                    execute_write(
                        conn,
                        "insert_whitelist",
                        (batch_id, doc_id, rule_code, reason, "auditor"),
                    )
                    saved_rules.append(rule_code)
                except Exception as exc:
                    st.error(f"저장 실패 ({rule_code}): {exc}")

            if saved_rules:
                record_event(
                    conn,
                    action="whitelist_add",
                    batch_id=batch_id,
                    target_id=doc_id,
                    details={"rule_codes": saved_rules, "reason": reason},
                )
                for rule_code in saved_rules:
                    record_feedback_event(
                        conn,
                        build_feedback_event(
                            event_type="document_feedback",
                            decision="false_positive",
                            company_id=company_id,
                            engagement_id=engagement_id,
                            batch_id=batch_id,
                            document_id=doc_id,
                            rule_code=rule_code,
                            reason=reason,
                            payload={"source": "whitelist_add"},
                        ),
                    )
                _sync_memory(result_data, doc_id, saved_rules)
                st.session_state[KEY_SELECTED_DOC] = doc_id
                st.success(f"{len(saved_rules)}건 예외 처리 완료 ({', '.join(saved_rules)})")
                modified = True

    st.divider()
    st.subheader("예외 처리 목록")

    try:
        whitelist_df = execute_preset(conn, "batch_whitelist", batch_id=batch_id)
    except Exception:
        whitelist_df = pd.DataFrame()

    if whitelist_df.empty:
        st.info("등록된 예외 처리 항목이 없습니다.")
        return modified

    for _, row in whitelist_df.iterrows():
        col_info, col_del = st.columns([5, 1])
        with col_info:
            st.text(
                f"[{row['document_id']}] {row['rule_code']} "
                f"- {row.get('reason', '') or '사유 없음'} "
                f"({str(row.get('created_at', ''))[:19]})"
            )
        with col_del:
            if st.button("삭제", key=f"wl_del_{row['id']}"):
                try:
                    execute_write(conn, "delete_whitelist", (int(row["id"]),))
                    record_event(
                        conn,
                        action="whitelist_remove",
                        batch_id=batch_id,
                        target_id=str(row["id"]),
                        details={
                            "document_id": row.get("document_id"),
                            "rule_code": row.get("rule_code"),
                        },
                    )
                    record_feedback_event(
                        conn,
                        build_feedback_event(
                            event_type="document_feedback",
                            decision="whitelist_revoked",
                            company_id=company_id,
                            engagement_id=engagement_id,
                            batch_id=batch_id,
                            document_id=str(row.get("document_id") or ""),
                            rule_code=str(row.get("rule_code") or ""),
                            reason="whitelist_removed",
                            payload={
                                "source": "whitelist_remove",
                                "whitelist_id": int(row["id"]),
                            },
                        ),
                    )
                    return True
                except Exception as exc:
                    st.error(f"삭제 실패: {exc}")

    return modified


def _sync_memory(result_data: pd.DataFrame, doc_id: str, rule_codes: list[str]) -> None:
    """Reflect whitelist changes into the in-memory dataframe."""
    mask = result_data["document_id"] == doc_id
    current_rules = str(result_data.loc[mask, "flagged_rules"].iloc[0])
    remaining = [
        rule.strip()
        for rule in current_rules.split(",")
        if rule.strip() and rule.strip() not in rule_codes
    ]
    result_data.loc[mask, "flagged_rules"] = ",".join(remaining)
    if not remaining:
        result_data.loc[mask, "risk_level"] = "Normal"
        result_data.loc[mask, "anomaly_score"] = 0.0


def _load_engagement_identity(conn: "duckdb.DuckDBPyConnection") -> tuple[str | None, str | None]:
    """Load company/engagement identity from the engagement DB."""
    try:
        row = conn.execute(
            """
            SELECT company_id, engagement_id
            FROM engagement_meta
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    except Exception:
        return None, None
    if row is None:
        return None, None
    return row[0], row[1]
