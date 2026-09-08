"""FOOTBALL screen (2026-09-02/03, Phase 6 six-screen rebuild) - real
composition tests. `football.py` composes a real league-wide signal feed
(`squad_football_signals`) with real, already-tested reference renderers
(fixture ticker, fixture projections, team odds, team-signal cards, squad
changes, match evidence) - these tests prove the real composition renders
once, cleanly, and never crashes; the underlying computations are already
covered elsewhere."""
from types import SimpleNamespace

from fpl_agent.monitoring.dashboard.football import _signal_row_html, render_football_screen
from test_football_signal import _seed_match, _seed_observation, _seed_player
from test_optimization_squad import _seed


def _fake_signal(**overrides):
    base = dict(
        entity_id=1, entity_name="TestPlayer", direction="POSITIVE", category="GOAL_THREAT",
        evidence="3 shots, 0.5 xG", interpretation="supports goal threat", fpl_effect=None,
        confidence="medium", expires_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_football_screen_shows_the_squad_change_module_for_a_squad_players_own_signal(db_conn):
    """Real regression test, Phase 7.3 Part 16 ("WHAT CHANGED FOR MY
    SQUAD?"). A real ROLE_CHANGE signal for a squad-owned player must
    surface in the new dedicated module, ranked by real decision relevance
    - not buried only inside the general league-wide feed below."""
    _seed_player(db_conn, player_id=1, web_name="MyPlayer")
    mid = _seed_match(db_conn)
    _seed_observation(db_conn, mid, 1, "ROLE_CHANGE", "POSITIVE")

    result = render_football_screen(db_conn, {1})

    assert "WHAT CHANGED FOR MY SQUAD?" in result
    assert "fb-squad-changes" in result
    assert "MyPlayer" in result.split("fb-squad-changes")[1].split("fb-feed")[0]


def test_signal_row_renders_the_real_fpl_consequence_when_present():
    """Real regression test, Phase 8.1 Part 19 - `s.fpl_effect` (a real,
    already-computed field this project's own model produces) was never
    rendered anywhere on FOOTBALL before this phase. Must now appear as
    its own distinct element, and must be honestly omitted (not blanked)
    when a signal genuinely has none."""
    with_effect = _fake_signal(fpl_effect="+0.15 xP already applied to goals this GW")
    row = _signal_row_html(with_effect, {}, set())
    assert "fb-signal-consequence" in row
    assert "+0.15 xP already applied to goals this GW" in row

    without_effect = _fake_signal(fpl_effect=None)
    row2 = _signal_row_html(without_effect, {}, set())
    assert "fb-signal-consequence" not in row2


def test_squad_change_module_never_shows_the_redundant_my_squad_badge(db_conn):
    """Real regression test, Phase 8.0 Part 17 - every row in this module
    is already squad-scoped by definition, so the "MY SQUAD" text badge
    (real, useful in the general league-wide feed below, where it
    distinguishes a squad player from 500+ others) adds zero information
    here and must not render. The row's own subtle highlight styling
    (`fb-signal-row-mine`) is a separate, non-redundant visual cue and
    stays."""
    _seed_player(db_conn, player_id=1, web_name="MyPlayer")
    mid = _seed_match(db_conn)
    _seed_observation(db_conn, mid, 1, "ROLE_CHANGE", "POSITIVE")

    result = render_football_screen(db_conn, {1})

    squad_section = result.split("fb-squad-changes")[1].split("fb-feed")[0]
    assert "fb-signal-mine" not in squad_section
    # The module's own real heading ("WHAT CHANGED FOR MY SQUAD?") legitimately
    # contains this substring - only the per-row badge span is checked here.
    rows_only = squad_section.split("</div>", 1)[1]
    assert "MY SQUAD" not in rows_only


def test_squad_change_module_suppresses_a_redundant_positive_minutes_signal(db_conn):
    """Real regression test, Phase 7.6 Part 13 - a plain "90 minutes played"
    signal for the SAME real match a richer GOAL_THREAT signal already
    covers is near-content-free (the richer card's own evidence text
    already states the minutes) and must not render as its own separate
    row. The underlying `match_observations` rows are both still real and
    both still exist - only the presentation is deduplicated."""
    _seed_player(db_conn, player_id=1, web_name="MyPlayer")
    mid = _seed_match(db_conn)
    _seed_observation(db_conn, mid, 1, "GOAL_THREAT", "POSITIVE", observed="3 shots, 0.5 xG")
    _seed_observation(db_conn, mid, 1, "MINUTES", "POSITIVE", observed="90 minutes played", inferred="starting-role signal")

    result = render_football_screen(db_conn, {1})

    squad_section = result.split("fb-squad-changes")[1].split("fb-feed")[0]
    assert "3 shots, 0.5 xG" in squad_section
    assert "starting-role signal" not in squad_section


def test_squad_change_module_keeps_a_standalone_negative_minutes_signal(db_conn):
    """A real early-withdrawal signal ("rotation/injury risk") is NEVER
    restated by any other card - it must always render, even when no
    richer same-match signal exists."""
    _seed_player(db_conn, player_id=1, web_name="MyPlayer")
    mid = _seed_match(db_conn)
    _seed_observation(db_conn, mid, 1, "MINUTES", "NEGATIVE", observed="substituted at 30', started the match",
                       inferred="rotation/injury risk")

    result = render_football_screen(db_conn, {1})

    squad_section = result.split("fb-squad-changes")[1].split("fb-feed")[0]
    assert "rotation/injury risk" in squad_section


def test_football_screen_omits_the_squad_change_module_with_no_squad_signals(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_football_screen(db_conn, set())

    assert "WHAT CHANGED FOR MY SQUAD?" not in result


def test_football_screen_renders_without_crashing(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_football_screen(db_conn, set())

    assert 'id="screen-football"' in result
    assert "FOOTBALL INTELLIGENCE" in result


def test_football_screen_includes_every_real_section_exactly_once(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_football_screen(db_conn, set())

    for marker in ("TEAM STATE", "MANAGER / XI / AVAILABILITY", "FIXTURE TICKER", "Fixture Projections", "Team Odds", "MATCH EVIDENCE"):
        assert result.count(marker) == 1, f"{marker!r} did not render exactly once"


def test_football_screen_empty_state_when_no_signals_yet(db_conn):
    """Honest empty state, never a fabricated signal - matches every other
    real 'nothing cleared the bar yet' disclosure in this project."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = render_football_screen(db_conn, set())

    assert "No real match-analyzed signals yet" in result
