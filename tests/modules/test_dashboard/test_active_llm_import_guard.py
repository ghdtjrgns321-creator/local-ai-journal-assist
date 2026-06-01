from __future__ import annotations

from pathlib import Path

ACTIVE_DASHBOARD_FILES = [
    Path("dashboard/app.py"),
    Path("dashboard/tab_chat.py"),
    Path("dashboard/tab_phase1.py"),
    Path("dashboard/tab_phase2.py"),
    Path("dashboard/tab_review_queue.py"),
    Path("dashboard/tab_overview.py"),
    Path("dashboard/components/phase1_local_evidence_brief.py"),
    Path("dashboard/components/review_queue_workflow.py"),
    Path("dashboard/components/rule_feedback_panel.py"),
]


def test_active_dashboard_path_has_no_llm_review_imports() -> None:
    forbidden = [
        "src.llm.phase1_case_brief",
        "get_chat_client",
        "OpenAIClient",
        "create_text_to_sql",
        "src.llm.text_to_sql",
        "src.llm.review_narrator",
        "src.llm.rule_feedback",
        "review_narrator",
        "AI 검토 메모",
    ]

    hits: list[str] = []
    for path in ACTIVE_DASHBOARD_FILES:
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            if term in text:
                hits.append(f"{path}:{term}")

    assert hits == []
