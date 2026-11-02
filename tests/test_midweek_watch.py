from datetime import datetime, timedelta, timezone

from fpl_agent.config import PowerConfig
from fpl_agent.ingestion import midweek_watch as mw
from fpl_agent.models import match_intelligence as mi
from fpl_agent.scheduler import power_window as pw

from test_news_source_matching import _seed_two_players_two_teams

KICK = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)


def _cup_fixture(conn, match_id="900", team_id=1, kick=KICK):
    conn.execute(
        "INSERT INTO team_other_competition_fixtures (team_id, fotmob_match_id, competition, opponent_name, is_home, kickoff_utc, "
        "finished, source, retrieved_at) VALUES (?, ?, 'Champions League', 'Leipzig', 0, ?, 0, 'test', 't0')",
        (team_id, match_id, kick.strftime("%Y-%m-%dT%H:%M:%S.000Z")),
    )
    conn.commit()


def _state(name, started, minutes, off=None, on=None, team="RB Leipzig"):
    return mi.PlayerMatchState(
        fotmob_player_id=name, team_name=team, name_raw=name, started=started, minutes=minutes, position=None, rating=None,
        goals=0, assists=0, shots=None, key_passes=None, xg=None, xa=None, touches_box=None,
        substituted_on_minute=on, substituted_off_minute=off, penalty_shots=None, penalty_goals=None,
    )


def _fake_payload(monkeypatch, ours="Man City", states=(), unavailable=()):
    match = mi.Match(
        fotmob_match_id="900", competition="Champions League", kickoff_utc=KICK.isoformat(), home_team_name="RB Leipzig",
        away_team_name=ours, status="FULL_TIME", home_score=1, away_score=2, live_minute=None, lineup_type="standard",
    )
    monkeypatch.setattr(mi, "parse_match", lambda payload: match)
    monkeypatch.setattr(mi, "parse_player_states", lambda payload: list(states))
    monkeypatch.setattr(mi, "parse_unavailable", lambda payload: list(unavailable))


def test_a_starter_off_early_in_europe_raises_one_high_event_for_a_squad_player(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    _cup_fixture(db_conn)
    team = db_conn.execute("SELECT name FROM teams WHERE id = 1").fetchone()["name"]
    _fake_payload(monkeypatch, ours=team, states=[_state("Haaland", True, 24, off=24, team=team), _state("Leipzig Nine", True, 90)])

    result = mw.sync_midweek(db_conn, {1}, {1}, now=KICK + timedelta(hours=3), fetch=lambda mid: {})
    again = mw.sync_midweek(db_conn, {1}, {1}, now=KICK + timedelta(hours=3), fetch=lambda mid: {})

    assert (result["matches"], result["players"], result["events"]) == (1, 1, 1)
    assert again["events"] == 0
    ev = db_conn.execute("SELECT severity, fpl_impact FROM change_events WHERE event_type = 'cup_withdrawal'").fetchone()
    assert ev["severity"] == "HIGH" and "minute 24" in ev["fpl_impact"]


def test_a_match_read_at_full_time_is_not_fetched_again(db_conn, monkeypatch):
    _seed_two_players_two_teams(db_conn)
    _cup_fixture(db_conn)
    _fake_payload(monkeypatch)
    calls = []
    mw.sync_midweek(db_conn, set(), set(), now=KICK + timedelta(hours=3), fetch=lambda mid: calls.append(mid) or {})
    mw.sync_midweek(db_conn, set(), set(), now=KICK + timedelta(hours=4), fetch=lambda mid: calls.append(mid) or {})
    assert calls == ["900"]


def test_a_european_night_opens_the_power_window(db_conn):
    _seed_two_players_two_teams(db_conn)
    _cup_fixture(db_conn)
    cfg = PowerConfig(window_lead_hours=24, post_deadline_grace_hours=3)
    kick = int(KICK.timestamp())

    assert pw.compute_window(db_conn, kick + 3600, cfg).active
    assert not pw.compute_window(db_conn, kick - 6 * 3600, cfg).active
