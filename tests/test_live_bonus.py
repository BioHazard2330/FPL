from fpl_agent.models.live_bonus import _assign_bonus, compute_live_bonus


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
