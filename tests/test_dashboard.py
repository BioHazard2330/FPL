from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.monitoring.dashboard import generate_dashboard_html
from test_optimization_squad import _seed


def test_generate_dashboard_html_composes_without_crashing(db_conn):
    """Plumbing test, same spirit as test_rate_team.py - real (unmocked)
    expected_points() over a small synthetic pool won't produce meaningful
    numbers, but every section (squad, risks, readiness, sources) must
    render without error."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = generate_dashboard_html(db_conn)

    assert "<html" in result
    assert "fpl-agent dashboard" in result
    assert "Recommended squad" in result
    assert "Availability risks" in result
    assert "System readiness" in result
    assert "Data sources" in result
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
