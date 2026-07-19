from dashboard._state import KEY_COMPANY_ID, KEY_ENGAGEMENT_ID
from dashboard._url_state import (
    hydrate_selection_from_query_params,
    sync_selection_to_query_params,
)


def test_hydrate_selection_from_query_params_restores_missing_state():
    state = {
        KEY_COMPANY_ID: None,
        KEY_ENGAGEMENT_ID: None,
    }

    hydrate_selection_from_query_params(
        state,
        {"company": "test", "engagement": "fy2022"},
    )

    assert state[KEY_COMPANY_ID] == "test"
    assert state[KEY_ENGAGEMENT_ID] == "fy2022"


def test_hydrate_selection_from_query_params_keeps_existing_state():
    state = {
        KEY_COMPANY_ID: "kept_company",
        KEY_ENGAGEMENT_ID: "kept_engagement",
    }

    hydrate_selection_from_query_params(
        state,
        {"company": "test", "engagement": "fy2022"},
    )

    assert state[KEY_COMPANY_ID] == "kept_company"
    assert state[KEY_ENGAGEMENT_ID] == "kept_engagement"


def test_sync_selection_to_query_params_updates_and_clears_values():
    state = {
        KEY_COMPANY_ID: "test",
        KEY_ENGAGEMENT_ID: "fy2022",
    }
    query_params = {"stale": "1"}

    sync_selection_to_query_params(state, query_params)

    assert query_params["company"] == "test"
    assert query_params["engagement"] == "fy2022"
    assert query_params["stale"] == "1"

    state[KEY_COMPANY_ID] = None
    state[KEY_ENGAGEMENT_ID] = None
    sync_selection_to_query_params(state, query_params)

    assert "company" not in query_params
    assert "engagement" not in query_params
