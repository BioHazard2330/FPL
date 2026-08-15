from types import SimpleNamespace

from fpl_agent.optimization import transfers as transfers_mod

_WINDOW_VALUES = {
    (1, 1): 3.0, (1, 3): 9.0, (1, 5): 15.0,
    (2, 1): 4.0, (2, 3): 13.0, (2, 5): 22.0,
}


def _seed_two_players(conn):
    now = "t0"
    conn.execute(
        "INSERT INTO teams (id,code,name,short_name,strength_overall_home,strength_overall_away,"
        "strength_attack_home,strength_attack_away,strength_defence_home,strength_defence_away,pulse_id,updated_at) "
        "VALUES (1,1,'T1','T1',3,3,0,0,0,0,1,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,squad_min_play,"
        "squad_max_play,squad_select,updated_at) VALUES (1,'Midfielder','MID','Midfielders',2,5,5,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO players (id,code,web_name,team_id,element_type,status,removed,updated_at) "
        "VALUES (1,1,'Out',1,1,'a',0,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO players (id,code,web_name,team_id,element_type,status,removed,updated_at) "
        "VALUES (2,2,'In',1,1,'a',0,?)",
        (now,),
    )
    conn.execute("INSERT INTO player_price_history (player_id,value_tenths,valid_from,valid_until) VALUES (1,50,?,NULL)", (now,))
    conn.execute("INSERT INTO player_price_history (player_id,value_tenths,valid_from,valid_until) VALUES (2,55,?,NULL)", (now,))
    conn.commit()


def _patch_window(monkeypatch):
    def fake(conn, player_id, n_gw):
        return SimpleNamespace(total_median=_WINDOW_VALUES[(player_id, n_gw)])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def test_evaluate_transfer_ev_deltas_without_hit(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    _patch_window(monkeypatch)

    result = transfers_mod.evaluate_transfer(db_conn, player_out_id=1, player_in_id=2, is_hit=False)

    assert result.ev_1gw == 1.0   # 4 - 3
    assert result.ev_3gw == 4.0   # 13 - 9
    assert result.ev_5gw == 7.0   # 22 - 15
    assert result.net_ev_3gw == result.ev_3gw  # no hit cost
    assert result.price_delta_tenths == 5  # 55 - 50


def test_evaluate_transfer_hit_cost_breakeven(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    _patch_window(monkeypatch)

    result = transfers_mod.evaluate_transfer(db_conn, player_out_id=1, player_in_id=2, is_hit=True)

    assert result.net_ev_1gw == 1.0 - transfers_mod.HIT_COST   # -3.0, a hit isn't worth it over 1 GW
    assert result.net_ev_3gw == 4.0 - transfers_mod.HIT_COST   # 0.0, exact breakeven
    assert result.net_ev_5gw == 7.0 - transfers_mod.HIT_COST   # 3.0, worth it over 5 GW


def _patch_window_from_event_aware(monkeypatch):
    """A second, separate fake from _patch_window above - deliberately not
    reused, since this one's signature includes from_event and the existing
    tests' fake must stay exactly as it is (see this task's note on why)."""
    # evaluate_transfer always computes total_median for n in (1, 3, 5), even
    # though only ev_1gw is asserted below - n=3/5 entries exist purely so
    # that dict lookup doesn't KeyError before reaching the n=1 assertions.
    values = {
        (1, 1, None): 3.0, (1, 3, None): 3.0, (1, 5, None): 3.0,
        (1, 1, 20): 1.0, (1, 3, 20): 1.0, (1, 5, 20): 1.0,
        (2, 1, None): 4.0, (2, 3, None): 4.0, (2, 5, None): 4.0,
        (2, 1, 20): 9.0, (2, 3, 20): 9.0, (2, 5, 20): 9.0,
    }

    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=values[(player_id, n_gw, from_event)])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def test_evaluate_transfer_from_event_reaches_expected_points_window(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    _patch_window_from_event_aware(monkeypatch)

    at_default = transfers_mod.evaluate_transfer(db_conn, player_out_id=1, player_in_id=2, is_hit=False)
    at_future = transfers_mod.evaluate_transfer(db_conn, player_out_id=1, player_in_id=2, is_hit=False, from_event=20)

    assert at_default.ev_1gw == 1.0   # 4 - 3, from_event omitted entirely
    assert at_future.ev_1gw == 8.0    # 9 - 1, from_event=20 reached the call - proves the threading works


def test_best_transfer_for_player_accepts_from_event(db_conn, monkeypatch):
    _seed_two_players(db_conn)
    _patch_window_from_event_aware(monkeypatch)

    results = transfers_mod.best_transfer_for_player(
        db_conn, player_out_id=1, squad_ids=[1], bank_tenths=100, is_hit=False,
        n_gw=1, top_n=3, from_event=20,
    )
    assert len(results) == 1
    assert results[0].ev_1gw == 8.0
