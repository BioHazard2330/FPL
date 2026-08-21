from fpl_agent.models.live_bonus import LiveBonusRow, _assign_bonus, compute_live_bonus, diff_live_rows


def test_assign_bonus_clear_ranking():
    assert _assign_bonus([30, 25, 20, 10]) == [3, 2, 1, 0]


def test_assign_bonus_two_way_tie_for_first_skips_the_two_slot():
    """Real official FPL rule: two players tied for the highest BPS in a
    match both get 3 bonus, and the next-best player gets 1 (not 2) - the
    '2' slot is skipped entirely, not given to a third player."""
    assert _assign_bonus([30, 30, 25, 10]) == [3, 3, 1, 0]


def test_assign_bonus_three_way_tie_for_first_awards_nothing_else():
    assert _assign_bonus([30, 30, 30, 10]) == [3, 3, 3, 0]


def test_assign_bonus_tie_for_second_skips_the_one_slot():
    assert _assign_bonus([30, 25, 25, 10]) == [3, 2, 2, 0]


def test_assign_bonus_fewer_than_three_players():
    assert _assign_bonus([30, 25]) == [3, 2]


def _seed_players(conn, ids_and_names):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'T1','T1','t0')")
    for pid, name in ids_and_names:
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, pid, name),
        )
    conn.commit()


def test_compute_live_bonus_groups_by_fixture_and_ranks_within_it(db_conn):
    """Real documented schema shape: elements[].stats.bps + explain[].fixture.
    Two separate fixtures must be scored independently - a high-BPS player
    in fixture 2 must never affect fixture 1's bonus ranking."""
    _seed_players(db_conn, [(1, "Alpha"), (2, "Beta"), (3, "Gamma"), (4, "Delta")])
    payload = {
        "elements": [
            {"id": 1, "stats": {"minutes": 90, "bps": 40, "goals_scored": 1, "assists": 0},
             "explain": [{"fixture": 100}]},
            {"id": 2, "stats": {"minutes": 90, "bps": 20, "goals_scored": 0, "assists": 0},
             "explain": [{"fixture": 100}]},
            {"id": 3, "stats": {"minutes": 90, "bps": 99, "goals_scored": 2, "assists": 1},
             "explain": [{"fixture": 200}]},
            {"id": 4, "stats": {"minutes": 0, "bps": 0, "goals_scored": 0, "assists": 0},
             "explain": [{"fixture": 200}]},  # never played - must be excluded
        ]
    }

    rows = compute_live_bonus(db_conn, payload)

    assert len(rows) == 3  # player 4 excluded (0 minutes)
    fixture_100 = [r for r in rows if r.fixture_id == 100]
    fixture_200 = [r for r in rows if r.fixture_id == 200]
    assert [r.web_name for r in fixture_100] == ["Alpha", "Beta"]
    assert fixture_100[0].provisional_bonus == 3
    assert fixture_100[1].provisional_bonus == 2
    assert fixture_200[0].web_name == "Gamma"
    assert fixture_200[0].provisional_bonus == 3


def test_compute_live_bonus_confirmed_bonus_is_none_until_finalized(db_conn):
    _seed_players(db_conn, [(1, "Alpha")])
    payload = {"elements": [
        {"id": 1, "stats": {"minutes": 90, "bps": 40, "bonus": 0, "goals_scored": 0, "assists": 0},
         "explain": [{"fixture": 100}]},
    ]}

    rows = compute_live_bonus(db_conn, payload)

    assert rows[0].confirmed_bonus is None  # bonus=0 mid-match means "not finalized yet", not "zero bonus"


def test_compute_live_bonus_double_gameweek_player_scored_independently_per_fixture(db_conn):
    """A player with two fixtures this event (double gameweek) must be
    scored separately for each - real FPL rule, not summed/averaged."""
    _seed_players(db_conn, [(1, "Alpha"), (2, "Beta")])
    payload = {"elements": [
        {"id": 1, "stats": {"minutes": 90, "bps": 50, "goals_scored": 0, "assists": 0},
         "explain": [{"fixture": 100}, {"fixture": 101}]},
        {"id": 2, "stats": {"minutes": 90, "bps": 10, "goals_scored": 0, "assists": 0},
         "explain": [{"fixture": 100}]},
    ]}

    rows = compute_live_bonus(db_conn, payload)

    alpha_rows = [r for r in rows if r.player_id == 1]
    assert {r.fixture_id for r in alpha_rows} == {100, 101}
    assert all(r.provisional_bonus == 3 for r in alpha_rows)  # top BPS in both fixtures


def _row(player_id, web_name="X", fixture_id=100, bps=0, provisional_bonus=0,
         minutes=90, goals_scored=0, assists=0, red_cards=0):
    return LiveBonusRow(
        player_id=player_id, web_name=web_name, fixture_id=fixture_id, bps=bps,
        provisional_bonus=provisional_bonus, confirmed_bonus=None, minutes=minutes,
        goals_scored=goals_scored, assists=assists, red_cards=red_cards,
    )


def test_diff_live_rows_first_observation_seeds_baseline_with_no_events():
    """A live-watch that starts mid-match must not fire a false 'just
    scored!' alert for goals a player already had before the watch began -
    the empty-previous-dict case is a seed, not a diff."""
    current = [_row(1, goals_scored=2, assists=1, provisional_bonus=3)]

    events, state = diff_live_rows({}, current)

    assert events == []
    assert state[1].goals_scored == 2


def test_diff_live_rows_fires_a_goal_event_on_real_increase():
    previous = {1: _row(1, goals_scored=0)}
    current = [_row(1, goals_scored=1)]

    events, state = diff_live_rows(previous, current)

    assert len(events) == 1
    assert events[0].kind == "goal"
    assert state[1].goals_scored == 1


def test_diff_live_rows_fires_assist_and_bonus_independently():
    previous = {1: _row(1, goals_scored=0, assists=0, provisional_bonus=0)}
    current = [_row(1, goals_scored=0, assists=1, provisional_bonus=2, bps=30)]

    events, _ = diff_live_rows(previous, current)

    kinds = {e.kind for e in events}
    assert kinds == {"assist", "bonus"}


def test_diff_live_rows_bonus_decreasing_never_fires_an_event():
    """Provisional bonus can legitimately drop mid-match as BPS swings -
    that's not a moment worth a push notification."""
    previous = {1: _row(1, provisional_bonus=3)}
    current = [_row(1, provisional_bonus=1)]

    events, _ = diff_live_rows(previous, current)

    assert events == []


def test_diff_live_rows_red_card_fires_once():
    previous = {1: _row(1, red_cards=0)}
    current = [_row(1, red_cards=1)]

    events, _ = diff_live_rows(previous, current)

    assert len(events) == 1
    assert events[0].kind == "red_card"


def test_diff_live_rows_no_change_fires_nothing():
    previous = {1: _row(1, goals_scored=1, assists=1, provisional_bonus=2)}
    current = [_row(1, goals_scored=1, assists=1, provisional_bonus=2)]

    events, _ = diff_live_rows(previous, current)

    assert events == []


def test_diff_live_rows_double_gameweek_player_does_not_fire_the_same_goal_twice():
    """Real bug found 2026-08-20: compute_live_bonus emits one LiveBonusRow
    per fixture for a double-gameweek player, but goals_scored/assists in
    FPL's own live stats are whole-gameweek totals - identical on both
    rows. Diffing each row independently against the same previous snapshot
    used to fire the same real goal twice in one poll."""
    previous = {1: _row(1, fixture_id=100, goals_scored=0)}
    # Same real goal (0->1), reported identically on both of this DGW player's fixture rows.
    current = [
        _row(1, fixture_id=100, goals_scored=1, provisional_bonus=0, bps=10),
        _row(1, fixture_id=200, goals_scored=1, provisional_bonus=2, bps=30),
    ]

    events, new_state = diff_live_rows(previous, current)

    goal_events = [e for e in events if e.kind == "goal"]
    assert len(goal_events) == 1
    assert new_state[1].goals_scored == 1


def test_diff_live_rows_double_gameweek_bonus_takes_the_higher_fixture_value():
    previous = {1: _row(1, fixture_id=100, provisional_bonus=0)}
    current = [
        _row(1, fixture_id=100, provisional_bonus=1, bps=15),
        _row(1, fixture_id=200, provisional_bonus=3, bps=40),
    ]

    events, new_state = diff_live_rows(previous, current)

    bonus_events = [e for e in events if e.kind == "bonus"]
    assert len(bonus_events) == 1
    assert "+3" in bonus_events[0].detail
    assert new_state[1].provisional_bonus == 3


# --- DEFCON live progress (2026-08-21, live-gameweek layer item 2/4) ------


def _seed_players_with_positions(conn, entries):
    """entries: [(player_id, web_name, position_short)]. Same shape as
    _seed_players but lets each player carry a real, distinct position -
    needed to prove DEFCON_THRESHOLDS resolves per-player, not just the
    single hardcoded MID every other test in this file uses."""
    positions = sorted({pos for _, _, pos in entries})
    names = {"GKP": "Goalkeeper", "DEF": "Defender", "MID": "Midfielder", "FWD": "Forward"}
    for i, pos in enumerate(positions, start=1):
        conn.execute(
            "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
            "VALUES (?,?,?,?, 't0')",
            (i, names[pos], pos, names[pos] + "s"),
        )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'T1','T1','t0')")
    pos_to_type_id = {pos: i for i, pos in enumerate(positions, start=1)}
    for pid, name, pos in entries:
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,?,'a','t0')",
            (pid, pid, name, pos_to_type_id[pos]),
        )
    conn.commit()


def test_compute_live_bonus_flags_defcon_reached_for_a_def_hitting_the_real_threshold(db_conn):
    _seed_players_with_positions(db_conn, [(1, "Defender1", "DEF")])
    payload = {"elements": [
        {"id": 1, "stats": {"minutes": 90, "bps": 20, "goals_scored": 0, "assists": 0,
                             "defensive_contribution": 10},
         "explain": [{"fixture": 100}]},
    ]}

    rows = compute_live_bonus(db_conn, payload)

    assert rows[0].position == "DEF"
    assert rows[0].defcon_threshold == 10
    assert rows[0].defensive_contribution == 10
    assert rows[0].defcon_reached is True


def test_compute_live_bonus_def_below_threshold_is_not_reached(db_conn):
    _seed_players_with_positions(db_conn, [(1, "Defender1", "DEF")])
    payload = {"elements": [
        {"id": 1, "stats": {"minutes": 90, "bps": 20, "goals_scored": 0, "assists": 0,
                             "defensive_contribution": 9},
         "explain": [{"fixture": 100}]},
    ]}

    rows = compute_live_bonus(db_conn, payload)
    assert rows[0].defcon_reached is False


def test_compute_live_bonus_mid_needs_the_real_higher_threshold(db_conn):
    """Real rule: MID/FWD threshold is 12 (CBIRT, recoveries included), not
    10 like DEF - the exact same defensive_contribution count that would
    reach it for a DEF must NOT be flagged reached for a MID."""
    _seed_players_with_positions(db_conn, [(1, "Mid1", "MID")])
    payload = {"elements": [
        {"id": 1, "stats": {"minutes": 90, "bps": 20, "goals_scored": 0, "assists": 0,
                             "defensive_contribution": 10},
         "explain": [{"fixture": 100}]},
    ]}

    rows = compute_live_bonus(db_conn, payload)
    assert rows[0].defcon_threshold == 12
    assert rows[0].defcon_reached is False


def test_compute_live_bonus_gkp_is_never_defcon_eligible(db_conn):
    """Real rule: scoring.defensive_contribution.GKP is 0 - GKP is not
    eligible regardless of how high a raw count they somehow rack up."""
    _seed_players_with_positions(db_conn, [(1, "Keeper1", "GKP")])
    payload = {"elements": [
        {"id": 1, "stats": {"minutes": 90, "bps": 20, "goals_scored": 0, "assists": 0,
                             "defensive_contribution": 99},
         "explain": [{"fixture": 100}]},
    ]}

    rows = compute_live_bonus(db_conn, payload)
    assert rows[0].defcon_threshold is None
    assert rows[0].defcon_reached is False


def _defcon_row(player_id, defcon_reached, defensive_contribution=0, defcon_threshold=10):
    return LiveBonusRow(
        player_id=player_id, web_name="X", fixture_id=100, bps=0, provisional_bonus=0,
        confirmed_bonus=None, minutes=90, goals_scored=0, assists=0,
        defensive_contribution=defensive_contribution, defcon_threshold=defcon_threshold,
        defcon_reached=defcon_reached,
    )


def test_diff_live_rows_fires_defcon_event_once_on_the_true_flip():
    previous = {1: _defcon_row(1, defcon_reached=False, defensive_contribution=8)}
    current = [_defcon_row(1, defcon_reached=True, defensive_contribution=10)]

    events, new_state = diff_live_rows(previous, current)

    defcon_events = [e for e in events if e.kind == "defcon"]
    assert len(defcon_events) == 1
    assert "10/10" in defcon_events[0].detail
    assert new_state[1].defcon_reached is True


def test_diff_live_rows_does_not_refire_defcon_once_already_reached():
    previous = {1: _defcon_row(1, defcon_reached=True, defensive_contribution=10)}
    current = [_defcon_row(1, defcon_reached=True, defensive_contribution=13)]  # still climbing, already reached

    events, _ = diff_live_rows(previous, current)

    assert [e for e in events if e.kind == "defcon"] == []
