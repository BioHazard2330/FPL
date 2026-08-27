from fpl_agent.monitoring.dashboard import generate_dashboard_html
from fpl_agent.monitoring.dashboard.legacy import (
    _compute_my_live_score,
    _dashboard_state,
    _squad_play_status_counts,
)
from fpl_agent.optimization.locked_squad import get_locked_squad
from test_optimization_locked_squad import _BENCH_4, _STARTING_11, _seed_real_picks
from test_optimization_squad import _seed


def test_dashboard_state_maps_lifecycle_state():
    # Rewired 2026-08-22 (automation-lifecycle pass) onto the real
    # models.gw_lifecycle state vocabulary, replacing the old squad-window
    # (`_squad_live_window`)-only 4-value mapping.
    assert _dashboard_state("LIVE") == "LIVE"
    assert _dashboard_state("GW_FINISHED") == "POST_MATCH"
    assert _dashboard_state("NEXT_GW_ANALYSIS") == "POST_MATCH"
    # READY_FOR_NEXT_DEADLINE reads as PRE_DEADLINE, not POST_MATCH
    # (2026-08-27, product design pass) - real bug found live: this state can
    # hold for DAYS, and POST_MATCH's panel order leads with live/match-recap
    # ahead of Primary Decision, which is only right in the narrow "what just
    # happened" window (GW_FINISHED/NEXT_GW_ANALYSIS) - once genuinely caught
    # up and waiting for the next deadline, "what should I do" belongs first.
    assert _dashboard_state("READY_FOR_NEXT_DEADLINE") == "PRE_DEADLINE"
    assert _dashboard_state("PRE_DEADLINE") == "PRE_DEADLINE"
    assert _dashboard_state("LOCKED") == "PRE_DEADLINE"
    assert _dashboard_state("UNKNOWN") == "PRE_DEADLINE"
    assert _dashboard_state(None) == "PRE_DEADLINE"


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
    """Squad is now a fixed top-level workspace (2026-08-27, frontend
    redesign - HOME/PLAN/SQUAD/INTELLIGENCE/MARKET, a stable task-oriented
    nav, not reordered by match state) - what genuinely still promotes on a
    live fixture is Live Tracking/Match Intelligence moving ahead of the
    OTHER secondary panels (intelligence-summary/opportunities/market), and
    the live-emphasis class/state on the page and hero."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=0)

    result = generate_dashboard_html(db_conn, live_payload={"elements": []})

    assert 'class="state-live"' in result
    assert result.index('id="live"') < result.index('id="intelligence-summary"')
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
    assert 'id="plan" data-cat="decision"' in result
    assert 'id="intelligence-summary" data-cat="intelligence"' in result
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
    from fpl_agent.monitoring.dashboard.legacy import _squad_live_window

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
    from fpl_agent.monitoring.dashboard.legacy import _squad_live_window

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


# --- Dashboard-overhaul pass (2026-08-22): real bug fixes ---

def test_any_in_progress_is_false_once_the_only_started_fixture_finished(db_conn):
    """Real, confirmed-live bug: `_squad_live_window.state` deliberately
    stays "live" for the whole gameweek window once any squad fixture has
    started (correct for hero-xp cumulative scoring) - but a caller that
    needs "is something happening RIGHT NOW" (the Next Kickoff strip item)
    needs `any_in_progress` instead, which must go back to False once the
    one started fixture is confirmed finished, even though `state` itself
    correctly stays "live"."""
    from fpl_agent.monitoring.dashboard.legacy import _squad_live_window

    _seed(db_conn, budget_tenths=950, club_limit=4)
    # Real, deliberate two-fixture scenario (matches the real production
    # case this bug was found against): team1 v team2 already finished (via
    # the fast match_intelligence override), team3 v team4 not yet
    # started - the squad's own whole-GW window correctly stays "live"
    # (some squad fixtures still ahead), but nothing is happening RIGHT NOW.
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=0)
    _seed_fixture_between(db_conn, event=1, team_h=3, team_a=4, started=0, finished=0)
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

    assert window.state == "live"  # whole-GW window correctly still live
    assert window.any_in_progress is False  # but nothing is happening right now


def test_any_in_progress_is_true_while_a_fixture_is_genuinely_live(db_conn):
    from fpl_agent.monitoring.dashboard.legacy import _squad_live_window

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture_between(db_conn, event=1, team_h=1, team_a=2, started=1, finished=0)

    window = _squad_live_window(db_conn, set(_STARTING_11))

    assert window.state == "live"
    assert window.any_in_progress is True


def test_player_shirt_has_a_real_onerror_fallback(db_conn):
    """Real bug fix: a shirt image load failure (ad-blocker, extension, CDN
    hiccup) must degrade to the existing `.shirt-fallback` styling instead
    of a blank/broken box - confirmed missing before this fix."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "onerror=" in result
    assert "shirt-fallback" in result


def test_compare_panel_shows_real_actual_points_once_a_match_has_played(db_conn):
    """Real bug fix: the Optimizer Delta panel's "Real xP" label was a
    stale-framed pre-match projection once real matches have played - now
    shows real accrued actual points (GW1 pts) alongside the projection."""
    from fpl_agent.monitoring.dashboard.legacy import _MyLiveScore, _compare_panel_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    my_live_score = _MyLiveScore(
        points=42.0, captain_points=10.0, captain_name="P30", captain_play_state="played",
        played=5, live=0, yet_to_play=6, bench=4,
    )

    result = _compare_panel_html(db_conn, 7378572, 50.0, 100.0, 0.0, "P30", set(_STARTING_11), my_live_score)

    assert "GW1 pts" in result
    assert "Projected xP" in result
    assert "Real xP" not in result  # the old, now-stale-framed label must be gone


def test_compare_panel_falls_back_to_projected_xp_before_any_match_played(db_conn):
    from fpl_agent.monitoring.dashboard.legacy import _compare_panel_html

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)

    result = _compare_panel_html(db_conn, 7378572, 50.0, 100.0, 0.0, "P30", set(_STARTING_11), None)

    assert "Projected xP" in result
    assert "GW1 pts" not in result
