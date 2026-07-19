from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from dashboard import tab_findings
from dashboard._state import KEY_SELECTED_DOC


def test_render_passes_selected_doc_to_detail(monkeypatch, sample_df) -> None:
    calls: dict = {}
    fake_state: dict = {}

    monkeypatch.setattr(tab_findings.st, "session_state", fake_state)
    monkeypatch.setattr(tab_findings.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_findings.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_findings.st, "rerun", lambda: None)
    monkeypatch.setattr(tab_findings, "_get_connection", lambda result: None)

    grid_response = SimpleNamespace(selected_rows=pd.DataFrame([{"document_id": "DOC0001"}]))
    monkeypatch.setattr(
        "dashboard.components.explorer_grid.build_grid",
        lambda df, dev_mode, selected_doc=None, whitelist_docs=None: grid_response,
    )

    def _capture_detail(doc_id, result_data, **kwargs):
        calls["doc_id"] = doc_id
        calls["results"] = kwargs.get("results")

    monkeypatch.setattr("dashboard.components.explorer_detail.render_detail", _capture_detail)

    result = SimpleNamespace(
        data=sample_df,
        results=[],
        batch_id="batch_001",
        load_result=None,
        shap_contributions=None,
        shap_base_value=None,
    )

    tab_findings.render(result)

    assert calls["doc_id"] == "DOC0001"
    assert calls["results"] == []
    assert fake_state[KEY_SELECTED_DOC] == "DOC0001"
