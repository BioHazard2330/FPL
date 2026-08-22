from fpl_agent.monitoring.dashboard import (
    _compute_my_live_score,
    _dashboard_state,
    _squad_play_status_counts,
    generate_dashboard_html,
)
from fpl_agent.optimization.locked_squad import get_locked_squad
from test_optimization_locked_squad import _BENCH_4, _STARTING_11, _seed_real_picks
from test_optimization_squad import _seed


def test_dashboard_state_maps_squad_window_state():
    assert _dashboard_state("live") == "LIVE"
    assert _dashboard_state("post") == "POST_MATCH"
    assert _dashboard_state("pre") == "PRE_DEADLINE"
    assert _dashboard_state("unknown") == "PRE_DEADLINE"


def _seed_fixture_between(conn, event, team_h, team_a, started, finished):
    conn.execute(
        "INSERT OR IGNORE INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,1,0,0,1,0,'t0')",
        (event, f"GW{event}", "2026-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,'t0')",
        (100 + team_h * 10 + team_a, 1, event, "2026-08-21T19:00:00Z", team_h, team_a, finished, started),
    )
    conn.commit()


def test_squad_play_status_counts_classifies_live_and_yet_to_play(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=0)

    counts = _squad_play_status_counts(db_conn, _STARTING_11, event=1)

    # team1={1,10,11,20,21,30} (6), team2={12,13,22,31} (4) -> live; team3's 32 -> yet_to_play (no fixture)
    assert counts == {"played": 0, "live": 10, "yet_to_play": 1}


def test_squad_play_status_counts_all_finished_is_played(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=1)

    counts = _squad_play_status_counts(db_conn, [1, 10, 12], event=1)

    assert counts == {"played": 3, "live": 0, "yet_to_play": 0}


def test_squad_play_status_counts_no_fixture_at_all_is_yet_to_play(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    counts = _squad_play_status_counts(db_conn, [1, 10], event=1)

    assert counts == {"played": 0, "live": 0, "yet_to_play": 2}


def test_compute_my_live_score_none_without_a_lock(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    assert _compute_my_live_score(db_conn, None, {"elements": []}, 1) is None


def test_compute_my_live_score_none_without_a_live_payload(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    locked = get_locked_squad(db_conn)
    assert _compute_my_live_score(db_conn, locked, None, 1) is None


def test_compute_my_live_score_uses_real_synced_multipliers(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    locked = get_locked_squad(db_conn)
    live_payload = {"elements": [
        {"id": 30, "stats": {"total_points": 5}},  # captain, multiplier 2 -> 10
        {"id": 20, "stats": {"total_points": 3}},  # multiplier 1 -> 3
    ]}

    score = _compute_my_live_score(db_conn, locked, live_payload, 1)

    assert score is not None
    assert score.points == 13.0
    assert score.captain_points == 10.0
    assert score.captain_name == "P30"


def test_dashboard_keeps_original_panel_order_when_pre_deadline(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert result.index('id="squad"') < result.index('id="live"')
    assert "Optimizer Recommendation" in result or "My Locked Squad" in result


def test_dashboard_promotes_live_panel_when_a_squad_fixture_is_live(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=0)

    result = generate_dashboard_html(db_conn, live_payload={"elements": []})

    assert 'class="state-live"' in result
    assert result.index('id="live"') < result.index('id="squad"')
    assert "panel-live-emphasis" in result
    assert "GW1 &middot; LIVE" in result


# --- Match Intelligence / Team Outlook promotion (2026-08-22, tonight's-
# matches visual pass, spec section N) ---------------------------------


def test_match_intelligence_and_team_outlook_promoted_when_live(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=0)

    result = generate_dashboard_html(db_conn, live_payload={"elements": []})

    # Real, live promotion: both cards move up next to Live Tracking/AI
    # Decisions instead of sitting below the fixture ticker.
    assert result.index('id="match-centre"') < result.index('id="fixtures"')
    assert result.index('id="football-intelligence"') < result.index('id="fixtures"')
    # Never rendered twice.
    assert result.count('id="match-centre"') == 1
    assert result.count('id="football-intelligence"') == 1


def test_match_intelligence_and_team_outlook_stay_put_when_pre_deadline(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    # Original position: inside the fixed Intelligence grid, after fixtures.
    assert result.index('id="fixtures"') < result.index('id="match-centre"')
    assert result.index('id="fixtures"') < result.index('id="football-intelligence"')


def test_panels_carry_a_real_data_intelligence_decision_category(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert 'id="squad" data-cat="data"' in result
    assert 'id="decisions" data-cat="decision"' in result
    assert 'id="risks" data-cat="decision"' in result
    assert 'id="football-intelligence" data-cat="intelligence"' in result
    assert 'id="match-centre" data-cat="intelligence"' in result


def test_squad_live_window_treats_match_intelligence_full_time_as_finished(db_conn):
    """Real gap found live 2026-08-21 at the actual full-time of the actual
    Arsenal v Coventry match: FPL's own fixtures.finished only updates on
    the regular (15min-6h) scheduler cadence, well after the faster
    live-match-poller (FotMob via match_intelligence) already knows the
    match is genuinely over. Without this override, "My Live Score" stayed
    stuck reporting LIVE for real minutes after the match had actually
    ended."""
    from fpl_agent.monitoring.dashboard import _squad_live_window

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=0)
    fixture_id = db_conn.execute("SELECT id FROM fixtures WHERE team_h=1 AND team_a=2").fetchone()[0]
    db_conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, fpl_fixture_id, competition, kickoff_utc, "
        "home_team_id, away_team_id, status, home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('999', ?, 'Premier League', '2026-08-21T19:00:00Z', 1, 2, 'FULL_TIME', 3, 0, "
        "'fotmob', 't0', 'high')",
        (fixture_id,),
    )
    db_conn.commit()

    window = _squad_live_window(db_conn, set(_STARTING_11))

    # team1/team2 players now read as finished via the faster real source;
    # team3's player32 has no fixture at all this event ("unknown" input,
    # but the two real teams above ARE all-finished) - real mixed squad
    # spanning multiple teams, same as a real live gameweek.
    assert window.state in ("post", "pre")  # not "live" - the override must win over the stale started=1/finished=0


def test_squad_live_window_never_unfinishes_a_real_fpl_confirmed_fixture(db_conn):
    """The override only ever moves finished 0->1, never the reverse - a
    missing/stale match_intelligence row must never contradict FPL's own
    already-confirmed finished=1."""
    from fpl_agent.monitoring.dashboard import _squad_live_window

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=1)

    window = _squad_live_window(db_conn, {1, 10})

    assert window.state == "post"


def test_hero_label_matches_the_live_score_even_when_dash_state_is_pre_deadline(db_conn):
    """Real inconsistency found live: a squad spans many kickoff times
    across a gameweek, so dash_state can honestly read PRE_DEADLINE in the
    real gap between two of the squad's own matches (not everything's live,
    not everything's finished either) - but my_live_score stays populated
    and must not show a stale "Projected xP" label next to a real live
    point total."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    # Team1/team2 fixture already full-time (via match_intelligence, faster
    # than fixtures.finished) - team3's own fixture hasn't started yet, so
    # the squad-wide state is genuinely neither "live" nor "post".
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=0)
    fixture_id = db_conn.execute("SELECT id FROM fixtures WHERE team_h=1 AND team_a=2").fetchone()[0]
    db_conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, fpl_fixture_id, competition, kickoff_utc, "
        "home_team_id, away_team_id, status, home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('999', ?, 'Premier League', '2026-08-21T19:00:00Z', 1, 2, 'FULL_TIME', 3, 0, "
        "'fotmob', 't0', 'high')",
        (fixture_id,),
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn, live_payload={"elements": [{"id": 30, "stats": {"total_points": 5}}]})

    assert "GW1 &middot; LIVE" in result or "GW1 &middot; FINAL" in result
    assert "GW1 &middot; Projected xP" not in result
