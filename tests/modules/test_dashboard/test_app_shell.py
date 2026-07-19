from __future__ import annotations

from dashboard.components.app_shell import build_batch_status_caption


def test_build_batch_status_caption_for_live_batch():
    text = build_batch_status_caption("journal.csv", 1234, elapsed=4.2, loaded_from_db=False)

    assert "현재 배치" in text
    assert "journal.csv" in text
    assert "1,234행" in text
    assert "4.2초" in text


def test_build_batch_status_caption_for_restored_batch():
    text = build_batch_status_caption("restored.db", 88, loaded_from_db=True)

    assert "복원 배치" in text
    assert "restored.db" in text
    assert "88행" in text
