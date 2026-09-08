"""Real regression coverage for the COMMAND JSON payload builder (2026-09-08,
Phase 8.2 Stage 2 - the React frontend's own data source). Same DB-shape
testing convention `data_payload.py`'s own tests already use: seed a real DB
state, call the builder, assert on the real fields - no browser needed for
this layer."""
import json

from fpl_agent.ingestion.my_team import set_my_team_entry_id
from fpl_agent.monitoring.api.command_payload import build_command_payload
from fpl_agent.monitoring.dashboard.context import build_dashboard_context
from test_optimization_locked_squad import _seed_real_picks
from test_optimization_squad import _seed


def test_command_payload_is_json_serializable_with_no_squad_locked(db_conn):
    """The honest empty case - no squad locked, no strategic plan run yet.
    Every field must degrade to `None`/an empty list, never raise and never
    fabricate a value."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    ctx = build_dashboard_context(db_conn)
    payload = build_command_payload(ctx)

    json.dumps(payload)  # must be real, plain JSON - no stray objects/dataclasses
    assert payload["captain"] is None
    assert payload["edge"] is None
    assert payload["contribution"] == []
    assert payload["monitor"] == []
    assert payload["action_squad"] is None


def test_command_payload_reads_the_same_real_squad_the_html_screen_shows(db_conn):
    """With a real locked squad, the payload's captain block must reflect
    the SAME real captain `command.py::render_command_screen` would show -
    this is a reshaping pass over `ctx.ca`, never a second computation."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    db_conn.commit()

    ctx = build_dashboard_context(db_conn)
    payload = build_command_payload(ctx)

    json.dumps(payload)
    assert payload["bar"]["squad_value_m"] == round(ctx.squad_value_m, 1)
    assert payload["bar"]["bank_m"] == round(ctx.bank_m, 1)
    if ctx.ca is not None and ctx.ca.options:
        assert payload["captain"] is not None
        assert payload["captain"]["best"]["player_id"] == ctx.ca.options[0].option.player_id


def test_command_payload_captain_carries_real_team_code_for_shirt_art(db_conn):
    """Real regression (2026-09-08, art-direction pass v3, direct user
    follow-up: "more football"). `CaptainBlock.best`/`.second` used to carry
    no team identity at all, forcing the frontend to cross-reference a
    DIFFERENT payload block (`action_squad`) that may not even contain the
    captain option in question (e.g. a candidate who isn't part of the
    currently-recommended action's own resulting squad - a real, confirmed
    gap this fixes). `CaptainOption.team_id` (new field, `captaincy.py`) now
    resolves through the SAME `ctx.team_codes` map `myteam_payload.py`
    already uses - never a second, independently-derived team lookup."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    db_conn.commit()

    ctx = build_dashboard_context(db_conn)
    payload = build_command_payload(ctx)
    json.dumps(payload)

    assert payload["captain"] is not None
    best = payload["captain"]["best"]
    real_team_id = next(o.option.team_id for o in ctx.ca.options if o.option.player_id == best["player_id"])
    assert best["team_code"] == ctx.team_codes.get(real_team_id)
    assert best["team_code"] is not None
    assert best["position"] is not None
