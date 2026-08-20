from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.monitoring.dashboard import generate_dashboard_html
from test_optimization_squad import _seed


def test_generate_dashboard_html_composes_without_crashing(db_conn):
    """Plumbing test, same spirit as test_rate_team.py - real (unmocked)
    expected_points() over a small synthetic pool won't produce meaningful
    numbers, but every panel (pitch, live tracking, risks, news, health)
    must render without error."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "<html" in result
    assert "fpl-agent dashboard" in result
    assert "My Team" in result
    assert "Live Tracking" in result
    assert "Availability risks" in result
    assert "Transfer News" in result
    assert "System health" in result
    assert f'content="{300}"' in result  # meta-refresh tag present


def test_generate_dashboard_html_escapes_untrusted_text(db_conn):
    """web_name/news/team fields ultimately originate from an external API -
    must be HTML-escaped, not interpolated raw (a real XSS-shaped risk for
    a page opened in a real browser, even though it's local-only)."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "UPDATE players SET status='i', news=? WHERE id=1", ("<script>alert(1)</script>",)
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "<script>alert(1)</script>" not in result
    assert "&lt;script&gt;" in result


def test_dashboard_shows_pitch_layout_with_captain_armband(db_conn):
    """The 'My Team' panel is a visual pitch grouping by position with a
    captain armband badge - not the old plain squad table."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "player-card" in result
    assert "pitch-row" in result
    assert "armband cap" in result


def test_dashboard_live_tracking_honest_pre_kickoff_state(db_conn):
    """No fixtures have started yet (preseason/pre-kickoff) - the Live
    Tracking panel must say so plainly and show the schedule, never
    fabricate a live score."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (1,'Gameweek 1','2026-08-21T17:30:00Z',1, 0,0,0,1,?)", (now,),
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, ?)", (now,),
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "Live tracking activates automatically" in result
    assert "Next kickoff" in result
    live_panel = result.split("Live Tracking")[1].split("Availability")[0]
    assert "live-active" not in live_panel  # no fabricated live scoreboard pre-kickoff


def test_dashboard_live_tracking_shows_real_bonus_when_match_in_progress(db_conn):
    """When a squad fixture is genuinely live and a real live_payload is
    supplied, the panel shows real per-player BPS/provisional bonus for
    squad members - the honest opposite of the pre-kickoff state above."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (1,'Gameweek 1','2026-08-21T17:30:00Z',1, 0,0,0,1,?)", (now,),
    )
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 1, ?)", (now,),
    )
    db_conn.commit()

    live_payload = {
        "elements": [
            {"id": 1, "stats": {"minutes": 60, "bps": 40, "goals_scored": 1, "assists": 0, "bonus": 0},
             "explain": [{"fixture": 1}]},
            {"id": 2, "stats": {"minutes": 60, "bps": 20, "goals_scored": 0, "assists": 0, "bonus": 0},
             "explain": [{"fixture": 1}]},
        ]
    }

    result = generate_dashboard_html(db_conn, live_payload=live_payload)

    assert "live-active" in result
    assert "P1" in result
    assert "+3" in result or "+2" in result  # provisional bonus badge for the top BPS scorer


def test_dashboard_transfer_news_panel_renders_synced_items(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    now = "t0"
    db_conn.execute(
        "INSERT INTO news_items (source, source_tier, external_id, title, link, published_at, retrieved_at) "
        "VALUES ('bbc_sport_pl','strong_reporter','guid-1','Player X ruled out for weeks',"
        "'https://example.com/x','2026-08-19T12:00:00Z',?)", (now,),
    )
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "Player X ruled out for weeks" in result
    assert "strong_reporter" in result


def test_dashboard_cli_writes_to_the_patched_data_dir_not_the_real_one(db_conn, tmp_path, monkeypatch):
    """Regression guard against the exact DATA_DIR-captured-at-import-time
    bug already caught once in this project (cleanup.py/storage.py) -
    computing the path fresh per call must actually pick up a patched
    DATA_DIR, not silently write to the real project data/ directory."""
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_mod, "get_connection", lambda: db_conn)
    _seed(db_conn, budget_tenths=950, club_limit=4)

    path = main_mod._write_dashboard()

    assert path == tmp_path / "dashboard.html"
    assert path.exists()
    assert "fpl-agent dashboard" in path.read_text(encoding="utf-8")


def test_write_dashboard_does_not_fetch_live_data_outside_a_live_window(db_conn, tmp_path, monkeypatch):
    """No fixture is started in the synthetic pool - _write_dashboard must
    not attempt any network call (this project's own resource discipline:
    only fetch live data when a match is genuinely in progress)."""
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_mod, "get_connection", lambda: db_conn)
    _seed(db_conn, budget_tenths=950, club_limit=4)

    class _FailingAdapter:
        def fetch_event_live(self, event):
            raise AssertionError("should not fetch live data outside a live window")

    monkeypatch.setattr(main_mod, "FPLApiAdapter", _FailingAdapter)

    main_mod._write_dashboard()  # must not raise


def test_dashboard_cli_command_prints_the_real_written_path(monkeypatch, tmp_path):
    """Exercises the actual `fpl dashboard` click command body, not just the
    underlying _write_dashboard() function - would have caught the real bug
    this command shipped with: a leftover reference to a variable name from
    before a refactor (NameError: DASHBOARD_PATH not defined), invisible to
    the other tests here because they call _write_dashboard() directly and
    never execute the command's own click.echo line."""
    import fpl_agent.cli.main as main_mod

    fake_path = tmp_path / "dashboard.html"
    monkeypatch.setattr(main_mod, "_write_dashboard", lambda: fake_path)

    result = CliRunner().invoke(cli, ["dashboard"])

    assert result.exit_code == 0, result.output
    assert str(fake_path) in result.output
