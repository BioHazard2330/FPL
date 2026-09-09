"""Real regression coverage for the club, player and match-report payloads
(2026-09-09). These are the app's first parameterised endpoints, so the
behaviour worth pinning is as much about a BAD id as a good one: a profile
that does not exist must raise `LookupError` (which the HTTP layer turns into
a real 404), never return an empty-but-successful payload the browser would
render as a real page full of blanks."""
import json

import pytest

from fpl_agent.monitoring.api.match_payload import build_match_report
from fpl_agent.monitoring.api.profile_payload import build_club_profile, build_player_profile
from test_optimization_squad import _PLAYERS, _seed


class _Ctx:
    """Only `squad_ids` is read by these builders."""

    def __init__(self, squad_ids=frozenset()):
        self.squad_ids = set(squad_ids)


def _event(conn, event=1):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (?,?,?,?,0,0,1,0,?)",
        (event, f"Gameweek {event}", "2026-09-10T11:00:00+00:00", 1789038000, "t0"),
    )


def _fixture(conn, fid, event, h, a, hs=None, a_s=None, finished=0):
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, team_h_score, "
        "team_a_score, finished, started, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (fid, 8000 + fid, event, "2026-09-05T14:00:00Z", h, a, hs, a_s, finished, finished, "t0"),
    )


# ------------------------------------------------------------------ bad ids


@pytest.mark.parametrize(
    "builder",
    [build_club_profile, build_player_profile, build_match_report],
    ids=["club", "player", "match"],
)
@pytest.mark.parametrize("params", [None, {}, {"id": ""}, {"id": "abc"}], ids=["none", "empty", "blank", "nan"])
def test_every_profile_rejects_a_missing_or_non_numeric_id(db_conn, builder, params):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    with pytest.raises(LookupError):
        builder(_Ctx(), params)


@pytest.mark.parametrize(
    "builder",
    [build_club_profile, build_player_profile, build_match_report],
    ids=["club", "player", "match"],
)
def test_every_profile_raises_for_an_id_that_does_not_exist(db_conn, builder):
    """A 404, never an empty page that reads as a real one."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    with pytest.raises(LookupError):
        builder(_Ctx(), {"id": "999999"})


# -------------------------------------------------------------------- club


def test_club_profile_reports_results_from_the_clubs_own_point_of_view(db_conn):
    """Home and away are not symmetric: the same fixture is a 2-1 win for one
    club and a 1-2 defeat for the other, and the result letter must follow."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _event(db_conn)
    _fixture(db_conn, 1, 1, 1, 2, hs=2, a_s=1, finished=1)
    db_conn.commit()

    home = build_club_profile(_Ctx(), {"id": "1"})
    away = build_club_profile(_Ctx(), {"id": "2"})
    json.dumps(home)

    hr = home["results"][0]
    ar = away["results"][0]
    assert hr["is_home"] is True and hr["gf"] == 2 and hr["ga"] == 1 and hr["result"] == "W"
    assert ar["is_home"] is False and ar["gf"] == 1 and ar["ga"] == 2 and ar["result"] == "L"
    assert hr["opponent_short"] == away["club"]["short"]


def test_club_profile_marks_and_counts_the_users_own_players(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    mine = next(pid for pid, _et, team_id, _p, _x in _PLAYERS if team_id == 1)
    out = build_club_profile(_Ctx({mine}), {"id": "1"})
    assert out["owned_count"] == 1
    assert [p["player_id"] for p in out["squad"] if p["is_mine"]] == [mine]


def test_club_profile_has_no_results_before_a_ball_is_kicked(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    out = build_club_profile(_Ctx(), {"id": "1"})
    assert out["results"] == []
    assert out["club"]["team_id"] == 1


# ------------------------------------------------------------------ player


def test_player_profile_returns_the_real_match_log_most_recent_first(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    pid = _PLAYERS[0][0]
    mt = db_conn.execute(
        "INSERT INTO market_teams (canonical_name, fpl_team_id) VALUES ('Team1', 1)"
    ).lastrowid
    for date, goals, xg in (("2026-08-21", 0, 0.11), ("2026-08-28", 2, 1.40), ("2026-09-04", 1, 0.62)):
        db_conn.execute(
            "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
            "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
            "yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"m{date}", "u1", pid, mt, "2026-27", date, 90, goals, 0, 3, xg, 0.1, 1, 0, 0, "t0"),
        )
    db_conn.commit()

    out = build_player_profile(_Ctx({pid}), {"id": str(pid)})
    json.dumps(out)
    assert out["player"]["is_mine"] is True
    assert [m["match_date"] for m in out["match_log"]] == ["2026-09-04", "2026-08-28", "2026-08-21"]
    assert out["match_log"][1]["goals"] == 2
    assert out["match_log"][0]["xg"] == pytest.approx(0.62)


def test_player_profile_price_history_runs_oldest_first_for_a_chart(db_conn):
    """The match log reads most-recent-first; a price chart has to read left
    to right in time. They are deliberately opposite orders."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    pid = _PLAYERS[0][0]
    out = build_player_profile(_Ctx(), {"id": str(pid)})
    dates = [r["valid_from"] for r in out["price_history"]]
    assert dates == sorted(dates)


def test_player_profile_survives_a_player_with_no_resolved_match_history(db_conn):
    """A real gap in the underlying match data is an empty log, never a
    failure and never a fabricated row."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    out = build_player_profile(_Ctx(), {"id": str(_PLAYERS[1][0])})
    assert out["match_log"] == []
    assert out["player"]["name"]


# ------------------------------------------------------------------- match


def _match(conn, match_id=1, home=1, away=2, hs=2, a_s=1):
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, competition, kickoff_utc, home_team_id, "
        "away_team_id, status, home_score, away_score, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (match_id, f"fm{match_id}", "Premier League", "2026-09-05T14:00:00Z", home, away,
         "FULL_TIME", hs, a_s, "fotmob", "t0"),
    )


def test_match_report_builds_end_to_end_for_a_real_match(db_conn):
    """The regression this file was missing. Every other match test passes a
    bad id and bails inside the first few lines, so a NameError on a module
    constant used further down (`_TIMELINE_TYPES`) shipped a real 500 with a
    fully green suite. This test walks the whole builder."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _match(db_conn)
    scorer = _PLAYERS[0][0]
    db_conn.execute(
        "INSERT INTO match_events (match_id, source, source_event_id, minute, event_type, team_id, "
        "player_id, description, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (1, "fotmob", "e1", 15, "Goal", 1, scorer, "Goal - a real scorer", "t0"),
    )
    db_conn.execute(
        "INSERT INTO match_events (match_id, source, source_event_id, minute, event_type, team_id, "
        "player_id, description, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (1, "fotmob", "e2", 62, "Substitution", 1, None, "Substitution", "t0"),
    )
    db_conn.execute(
        "INSERT INTO team_match_state (match_id, team_id, formation, possession_pct, shots, "
        "shots_on_target, xg, corners, source, retrieved_at, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (1, 1, "4-3-3", 61.0, 14, 6, 1.94, 7, "fotmob", "t0", "medium"),
    )
    db_conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, rating, "
        "goals, assists, shots, xg, source, retrieved_at, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (1, scorer, 1, 1, 90, 8.1, 1, 0, 4, 0.81, "fotmob", "t0", "medium"),
    )
    db_conn.commit()

    out = build_match_report(_Ctx({scorer}), {"id": "1"})
    json.dumps(out)

    assert out["match"]["home"]["score"] == 2 and out["match"]["away"]["score"] == 1
    assert out["match"]["is_squad_match"] is True
    # a substitution row that names nobody is not reportable and must be
    # excluded - only the goal survives
    assert [e["event_type"] for e in out["timeline"]] == ["Goal"]
    assert out["timeline"][0]["is_home"] is True and out["timeline"][0]["is_mine"] is True
    assert out["team_stats"]["home"]["formation"] == "4-3-3"
    assert out["team_stats"]["away"] is None
    home_players = out["lineups"]["home"]
    assert [p["player_id"] for p in home_players] == [scorer]
    assert home_players[0]["rating"] == 8.1 and home_players[0]["minutes"] == 90


def test_match_report_never_invents_a_lineup_or_stats_it_does_not_have(db_conn):
    """A match with no per-player rows is a real state (FotMob detail was
    never fetched). It must come back empty, not padded."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _match(db_conn, match_id=2)
    db_conn.commit()

    out = build_match_report(_Ctx(), {"id": "2"})
    assert out["lineups"] == {"home": [], "away": []}
    assert out["timeline"] == []
    assert out["team_stats"] == {"home": None, "away": None}
    assert out["match"]["is_squad_match"] is False
