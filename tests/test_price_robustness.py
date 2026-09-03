"""Regression tests for real future price-execution robustness (2026-09-02,
Phase 5C optimizer forensic rebuild, PART 3)."""
from types import SimpleNamespace

from fpl_agent.optimization.price_robustness import PRICE_SCENARIOS, assess_price_robustness


def _seed_pool(conn):
    now = "2026-01-01T00:00:00Z"
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','{now}')")
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'Team B','TMB','{now}')")
    conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, "
        f"squad_max_play, squad_select, updated_at) VALUES (1,'Forward','FWD','Forwards',1,3,3,'{now}')"
    )
    for pid, team_id, name, price in ((1, 1, 'Owned', 50), (2, 2, 'Target', 50)):
        conn.execute(f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES ({pid},{pid},'{name}',{team_id},1,'a',0,'{now}')")
        conn.execute(f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES ({pid}, {price}, '{now}', NULL)")
    conn.commit()


def _step(event, out_id, out_name, in_id, in_name):
    return SimpleNamespace(event=event, player_out_id=out_id, player_out_name=out_name, player_in_id=in_id, player_in_name=in_name)


def test_all_scenarios_covered():
    assert set(PRICE_SCENARIOS) == {"unchanged", "target_+0.1", "target_+0.2", "target_-0.1", "owned_-0.1", "owned_-0.2"}


def test_equal_prices_zero_bank_survives_every_real_scenario_except_target_rise(db_conn):
    """Owned=50, Target=50, bank=0 - today's margin is exactly 0. A real
    target price rise (+0.1 or +0.2) makes it genuinely unaffordable; an
    owned-player price FALL also breaks it (less real money raised on sale);
    target FALL and owned-unchanged scenarios stay fine."""
    _seed_pool(db_conn)
    path = SimpleNamespace(steps=[_step(3, 1, "Owned", 2, "Target")])

    result = assess_price_robustness(db_conn, path, starting_bank_tenths=0)

    dep = result.price_dependencies[0]
    assert dep.today_margin_tenths == 0
    assert "target_+0.1" in dep.failed_scenarios
    assert "target_+0.2" in dep.failed_scenarios
    assert "owned_-0.1" in dep.failed_scenarios
    assert "owned_-0.2" in dep.failed_scenarios
    assert "target_-0.1" not in dep.failed_scenarios
    assert "unchanged" not in dep.failed_scenarios
    assert result.price_robust is False
    assert result.number_of_failed_price_scenarios == 4


def test_comfortable_bank_survives_every_real_scenario(db_conn):
    _seed_pool(db_conn)
    path = SimpleNamespace(steps=[_step(3, 1, "Owned", 2, "Target")])

    result = assess_price_robustness(db_conn, path, starting_bank_tenths=50)

    assert result.price_robust is True
    assert result.number_of_failed_price_scenarios == 0
    assert result.critical_price_assumptions == ()


def test_running_bank_carries_forward_across_real_steps(db_conn):
    """Real, disclosed running-bank model - a real bank surplus from an
    EARLIER step (selling a 50-priced player for a 30-priced one) genuinely
    carries forward to fund a LATER, more expensive real target."""
    _seed_pool(db_conn)
    now = "2026-01-01T00:00:00Z"
    db_conn.execute(f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (3,3,'Cheap',2,1,'a',0,'{now}')")
    db_conn.execute(f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (3, 30, '{now}', NULL)")
    db_conn.commit()
    # Step 1: sell Owned(50) for Cheap(30) - real +20 bank surplus.
    # Step 2: sell Cheap(30) for Target(50) - needs the real step-1 surplus.
    path = SimpleNamespace(steps=[
        _step(3, 1, "Owned", 3, "Cheap"),
        _step(4, 3, "Cheap", 2, "Target"),
    ])

    result = assess_price_robustness(db_conn, path, starting_bank_tenths=0)

    step2 = result.price_dependencies[1]
    assert step2.today_margin_tenths == 0  # 0 starting bank + 20 real surplus - 20 real gap = 0
    assert result.price_robust is False  # zero margin still fails a real +0.1 rise
    assert "target_+0.1" in step2.failed_scenarios


def test_no_transfer_steps_returns_empty_and_robust(db_conn):
    path = SimpleNamespace(steps=[SimpleNamespace(event=3, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None)])

    result = assess_price_robustness(db_conn, path, starting_bank_tenths=0)

    assert result.price_dependencies == ()
    assert result.price_robust is True
