"""Real, deterministic end-to-end test for the event bus + fast engine
(2026-08-29, "live architecture rebuild" pass, milestone 1, spec section
14: "test this before touching UI"). Feeds a real, mock-shaped (never
random/fabricated-field) FotMob payload sequence through the ACTUAL
production code path (`sync_match`) across three real match-state ticks
(LIVE with a goal, LIVE with a substitution, FULL_TIME) and asserts the
real event bus + fast engine react correctly at every step - no widget,
no dashboard, no UI involved.

Reuses `test_fotmob_source.py`'s own real `_seed`/team setup (Arsenal vs
Coventry City) rather than duplicating it."""
from datetime import date

import pytest

import fpl_agent.ingestion.fotmob_source as fotmob_mod
from fpl_agent.events.bus import Event, bus
from fpl_agent.events.types import EventType
from fpl_agent.ingestion.fotmob_source import sync_match
from fpl_agent.live import fast_engine
from test_fotmob_source import _seed
from test_live_snapshot import _seed_player


@pytest.fixture(autouse=True)
def _clean_bus():
    """The event bus is a real module-level singleton (one real process
    shares it in production) - tests must reset it so one test's
    subscribers never leak into another's assertions."""
    bus.reset()
    yield
    bus.reset()


def _seed_match_players(conn):
    _seed(conn)
    _seed_player(conn, 10, web_name="Scorer", team_id=1, element_type=4)
    _seed_player(conn, 11, web_name="Assister", team_id=1, element_type=3)
    _seed_player(conn, 12, web_name="SubOut", team_id=1, element_type=2)
    _seed_player(conn, 13, web_name="SubIn", team_id=1, element_type=2)


def _base_payload(started: bool, finished: bool, half_status: dict | None = None):
    return {
        "general": {
            "matchId": "999001", "leagueName": "Premier League",
            "matchTimeUTCDate": "2026-08-21T19:00:00.000Z",
            "homeTeam": {"name": "Arsenal", "id": 9825}, "awayTeam": {"name": "Coventry City", "id": 8669},
            "started": started, "finished": finished,
        },
        "header": {
            "teams": [{"name": "Arsenal", "id": 9825, "score": 1}, {"name": "Coventry City", "id": 8669, "score": 0}],
            "status": {"started": started, "finished": finished, **(half_status or {})},
        },
        "content": {
            "lineup": {
                "homeTeam": {
                    "id": 9825, "name": "Arsenal", "formation": "4-3-3",
                    "starters": [
                        {"id": 10, "name": "Scorer"}, {"id": 11, "name": "Assister"}, {"id": 12, "name": "SubOut"},
                    ],
                    "subs": [{"id": 13, "name": "SubIn", "performance": {"substitutionEvents": []}}],
                },
                "awayTeam": {"id": 8669, "name": "Coventry City", "formation": "4-4-2", "starters": []},
            },
            "stats": None,
            "shotmap": {"shots": [], "Periods": {"All": []}},
            "matchFacts": {"events": {"events": []}},
        },
    }


def _payload_tick1_goal():
    """Real tick 1: match goes PRE_MATCH -> LIVE, one real goal (Scorer,
    assisted by Assister) - both resolvable to real internal player ids."""
    payload = _base_payload(started=True, finished=False)
    payload["content"]["matchFacts"]["events"]["events"] = [{
        "reactKey": "g1", "eventId": 1, "type": "Goal", "time": 30, "isHome": True,
        "player": {"id": 10, "name": "Scorer"}, "assistPlayerId": 11, "assistStr": "assist by Assister",
    }]
    return payload


def _payload_tick2_substitution():
    """Real tick 2: same match, still LIVE, a real substitution
    (SubOut -> SubIn) added to the real event list alongside the earlier
    goal (a real re-sync always re-sends the full match-to-date event
    list, never just the newest one)."""
    payload = _payload_tick1_goal()
    payload["content"]["matchFacts"]["events"]["events"].append({
        "reactKey": "s1", "type": "Substitution", "time": 70, "isHome": True,
        "player": {"id": None}, "swap": [{"name": "SubIn", "id": 13}, {"name": "SubOut", "id": 12}],
    })
    return payload


def _payload_tick3_full_time():
    """Real tick 3: match transitions to FULL_TIME - same real events,
    no new incident this tick."""
    payload = _payload_tick2_substitution()
    payload["general"]["started"] = True
    payload["general"]["finished"] = True
    payload["header"]["status"]["finished"] = True
    return payload


def _sync(monkeypatch, conn, payload):
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "999001")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: payload)
    monkeypatch.setattr(fotmob_mod, "save_raw", lambda name, data: "raw/path.json")
    return sync_match(conn, "Arsenal", "Coventry", date(2026, 8, 21))


def test_full_pipeline_goal_substitution_full_time(monkeypatch, db_conn):
    """The real spec-14 chain: SHOT/GOAL -> player state -> event bus;
    SUBSTITUTION -> fast engine locks the real OUT player's minutes;
    MATCH_FINISHED -> fast engine locks minutes for every real player in
    the match. Verifies each event reaches a real subscriber exactly
    once, never refired on a re-sync of an already-known incident."""
    _seed_match_players(db_conn)
    fast_engine.register(db_conn, bus)

    received: list[Event] = []
    bus.subscribe_all(lambda e: received.append(e))

    # --- Tick 1: match starts, a real goal + assist ---
    _sync(monkeypatch, db_conn, _payload_tick1_goal())
    types_seen = [e.event_type for e in received]
    assert EventType.MATCH_STARTED in types_seen
    goal_events = [e for e in received if e.event_type == EventType.GOAL]
    assert len(goal_events) == 1
    assert goal_events[0].entity_id == 10  # Scorer's real internal player id
    assist_events = [e for e in received if e.event_type == EventType.ASSIST]
    assert len(assist_events) == 1
    assert assist_events[0].entity_id == 11  # Assister's real internal player id

    # Re-syncing the SAME tick 1 payload must NOT refire the already-known goal/assist.
    received.clear()
    _sync(monkeypatch, db_conn, _payload_tick1_goal())
    assert not any(e.event_type in (EventType.GOAL, EventType.ASSIST) for e in received)
    assert not any(e.event_type == EventType.MATCH_STARTED for e in received)  # already LIVE, not a new transition

    # --- Tick 2: a real substitution ---
    received.clear()
    _sync(monkeypatch, db_conn, _payload_tick2_substitution())
    sub_events = [e for e in received if e.event_type == EventType.SUBSTITUTION]
    assert len(sub_events) == 1
    assert sub_events[0].payload["player_out_id"] == 12  # SubOut's real internal id
    assert sub_events[0].payload["player_in_id"] == 13   # SubIn's real internal id

    # Real fast-engine effect: SubOut's minutes are now locked.
    state = fast_engine.get_live_player_state(db_conn, 12)
    assert state is not None
    assert state["minutes_locked"] == 1
    assert state["last_event_type"] == EventType.SUBSTITUTION.value
    # SubIn (still on the pitch) must NOT be locked.
    assert fast_engine.get_live_player_state(db_conn, 13) is None

    # --- Tick 3: full time ---
    received.clear()
    _sync(monkeypatch, db_conn, _payload_tick3_full_time())
    assert any(e.event_type == EventType.MATCH_FINISHED for e in received)
    # Real fast-engine effect: every real player who featured now has locked minutes.
    for pid in (10, 11, 12, 13):
        state = fast_engine.get_live_player_state(db_conn, pid)
        assert state is not None, f"player {pid} should have a locked live_player_state after FULL_TIME"
        assert state["minutes_locked"] == 1
    # SubOut's state_version must have incremented across two real updates
    # (the SUBSTITUTION lock, then the FULL_TIME lock) - a real, versioned
    # canonical fact, never silently overwritten without a version bump.
    assert fast_engine.get_live_player_state(db_conn, 12)["state_version"] == 2
