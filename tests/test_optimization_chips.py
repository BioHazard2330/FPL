from fpl_agent.optimization.chips import eligible_chips

_ROWS = [
    (1, "wildcard", 1, 2, 19, "transfer"),
    (2, "wildcard", 1, 20, 38, "transfer"),
    (3, "freehit", 1, 2, 19, "transfer"),
    (4, "bboost", 1, 1, 19, "team"),
    (5, "3xc", 1, 1, 19, "team"),
]


def _seed(conn):
    now = "t0"
    conn.execute(
        "INSERT INTO rules (rule_key,season,version,effective_date,source,value) VALUES ('dummy','2026-27',1,?,?,?)",
        (now, "test", "1"),
    )
    for id_, name, number, start, stop, ctype in _ROWS:
        conn.execute(
            "INSERT INTO chip_windows (id,name,number,start_event,stop_event,chip_type,season,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (id_, name, number, start, stop, ctype, "2026-27", now),
        )
    conn.commit()


def test_eligible_chips_first_half(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=5)}

    assert windows[("wildcard", 2)] is True
    assert windows[("wildcard", 20)] is False
    assert windows[("bboost", 1)] is True


def test_eligible_chips_second_half(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=25)}

    assert windows[("wildcard", 20)] is True
    assert windows[("wildcard", 2)] is False
    assert windows[("bboost", 1)] is False


def test_eligible_chips_gw1_excludes_wildcard_and_freehit(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=1)}

    assert windows[("wildcard", 2)] is False
    assert windows[("freehit", 2)] is False
    assert windows[("bboost", 1)] is True
    assert windows[("3xc", 1)] is True


import numpy as np

from fpl_agent.models.scenario_engine import ScenarioOutcome
from fpl_agent.optimization.chips import (
    _bench_boost_trial_values,
    _triple_captain_trial_values,
)


def _seed_squad_for_bench_boost(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, updated_at) VALUES "
        "(1,'Goalkeeper','GKP','Goalkeepers',1,1,'t0'), (4,'Forward','FWD','Forwards',1,3,'t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,1,?,'a','t0')",
        [(1, 1, "GK1", 1), (2, 2, "FWD_starter", 4), (3, 3, "FWD_bench", 4)],
    )
    conn.commit()


def test_bench_boost_trial_values_sums_only_bench_points(db_conn, monkeypatch):
    _seed_squad_for_bench_boost(db_conn)
    import fpl_agent.optimization.chips as chips_mod

    # Force a known starting XI / bench split rather than depending on live xP -
    # keeps this a pure wiring test of the trial-summing logic.
    from fpl_agent.optimization.squad import PlayerCandidate, StartingXI

    def fake_pick_xi(conn, squad):
        starter = next(c for c in squad if c.player_id == 2)
        bench_player = next(c for c in squad if c.player_id == 3)
        gk = next(c for c in squad if c.player_id == 1)
        return StartingXI(starting=[gk, starter], bench=[bench_player], captain=starter, vice_captain=gk)

    monkeypatch.setattr(chips_mod, "pick_starting_xi", fake_pick_xi)

    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={(10, 1): 2.0, (10, 2): 6.0, (10, 3): 9.0}),
        ScenarioOutcome(trial_index=1, points_by_event_player={(10, 1): 2.0, (10, 2): 4.0, (10, 3): 1.0}),
    ]

    values = _bench_boost_trial_values(db_conn, [1, 2, 3], event=10, scenario_draw=scenario_draw)

    assert list(values) == [9.0, 1.0]  # bench is just player 3 in both trials


def test_triple_captain_trial_values_reads_best_captain_points(db_conn, monkeypatch):
    _seed_squad_for_bench_boost(db_conn)
    import fpl_agent.optimization.chips as chips_mod
    from fpl_agent.optimization.captaincy import CaptainOption

    monkeypatch.setattr(
        chips_mod, "evaluate_captaincy",
        lambda conn, squad_ids: [CaptainOption(player_id=2, web_name="FWD_starter", position="FWD", floor=1, median=5, ceiling=9, confidence="HIGH", expected_minutes=90, is_penalty_taker=False, opponent_short=None, is_home=None, selected_by_percent=None)],
    )

    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={(10, 2): 12.0}),
        ScenarioOutcome(trial_index=1, points_by_event_player={(10, 2): 3.0}),
    ]

    values = _triple_captain_trial_values(db_conn, [1, 2, 3], event=10, scenario_draw=scenario_draw)
    assert list(values) == [12.0, 3.0]
