from fpl_agent.models.match_intelligence import (
    FULL_TIME,
    HALFTIME,
    LIVE,
    PRE_MATCH,
    derive_status,
    parse_match,
    parse_player_states,
    parse_team_states,
)

# Trimmed real fragments of FotMob's actual matchDetails payload shape
# (confirmed live 2026-08-21 against Arsenal v Coventry, matchId 5795363,
# pre-kickoff) - not invented field names.
_PAYLOAD = {
    "general": {
        "matchId": "5795363",
        "leagueName": "Premier League",
        "matchTimeUTCDate": "2026-08-21T19:00:00.000Z",
        "homeTeam": {"name": "Arsenal", "id": 9825},
        "awayTeam": {"name": "Coventry City", "id": 8669},
        "started": False,
        "finished": False,
    },
    "header": {
        "teams": [
            {"name": "Arsenal", "id": 9825, "score": 0},
            {"name": "Coventry City", "id": 8669, "score": 0},
        ],
        "status": {"started": False, "finished": False},
    },
    "content": {
        "lineup": {
            "homeTeam": {
                "id": 9825, "name": "Arsenal", "formation": "4-3-3",
                "starters": [
                    {"id": 562727, "name": "David Raya"},
                    {"id": 111111, "name": "Bukayo Saka"},
                ],
            },
            "awayTeam": {
                "id": 8669, "name": "Coventry City", "formation": "4-4-2",
                "starters": [{"id": 222222, "name": "Test Coventry Player"}],
            },
        },
        "stats": None,
        "shotmap": {"shots": [], "Periods": {"All": []}},
    },
}


def test_parse_match_reads_real_confirmed_fields():
    m = parse_match(_PAYLOAD)
    assert m.fotmob_match_id == "5795363"
    assert m.competition == "Premier League"
    assert m.kickoff_utc == "2026-08-21T19:00:00.000Z"
    assert m.home_team_name == "Arsenal"
    assert m.away_team_name == "Coventry City"
    assert m.status == PRE_MATCH
    assert m.home_score == 0
    assert m.away_score == 0


def test_derive_status_pre_match_live_halftime_full_time():
    assert derive_status({"started": False, "finished": False}) == PRE_MATCH
    assert derive_status({"started": True, "finished": False}) == LIVE
    assert derive_status({"started": True, "finished": False}, {"reason": {"short": "HT"}}) == HALFTIME
    assert derive_status({"started": True, "finished": True}) == FULL_TIME


def test_parse_player_states_extracts_starters_from_both_sides_no_fabricated_stats():
    states = parse_player_states(_PAYLOAD)
    assert len(states) == 3
    saka = next(s for s in states if s.name_raw == "Bukayo Saka")
    assert saka.started is True
    assert saka.team_name == "Arsenal"
    # No shots yet (empty shotmap) - real zero, not fabricated, and unrelated
    # fields genuinely unavailable pre-kickoff must stay null, not defaulted.
    assert saka.shots == 0
    assert saka.goals == 0
    assert saka.rating is None
    assert saka.position is None
    assert saka.minutes is None


def test_parse_player_states_sums_real_shot_events_per_player():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["shotmap"] = {
        "shots": [
            {"playerId": 111111, "eventType": "Goal", "expectedGoals": 0.42},
            {"playerId": 111111, "eventType": "AttemptSaved", "expectedGoals": 0.08},
        ],
        "Periods": {"All": []},
    }
    states = parse_player_states(payload)
    saka = next(s for s in states if s.fotmob_player_id == "111111")
    assert saka.shots == 2
    assert saka.goals == 1
    assert abs(saka.xg - 0.5) < 1e-9


def test_parse_player_states_handles_missing_lineup_entirely():
    payload = {"content": {}}
    assert parse_player_states(payload) == []


def test_parse_team_states_reads_formation_and_degrades_gracefully_on_null_stats():
    states = parse_team_states(_PAYLOAD)
    assert len(states) == 2
    home = next(s for s in states if s.team_name == "Arsenal")
    assert home.formation == "4-3-3"
    # content.stats was null (real, pre-kickoff) - every numeric stat field
    # must be None, never a fabricated 0.
    assert home.possession_pct is None
    assert home.shots is None
    assert home.xg is None


def test_parse_team_states_never_crashes_on_malformed_stats_shape():
    payload = dict(_PAYLOAD)
    payload["content"] = dict(_PAYLOAD["content"])
    payload["content"]["stats"] = {"totally": "unexpected shape"}
    states = parse_team_states(payload)
    assert len(states) == 2
    assert all(s.possession_pct is None for s in states)
