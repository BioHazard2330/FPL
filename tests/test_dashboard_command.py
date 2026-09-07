"""Real regression coverage for the COMMAND screen (2026-09-07, Phase 7.1) -
this module previously had zero direct test coverage at all."""
from types import SimpleNamespace

from fpl_agent.models.decision_fusion import CaptainCrossCheck, CrossCheckAxis
from fpl_agent.monitoring.dashboard.command import _checkpoint_table_html, _contribution_layer_html, render_command_screen


def _ca(options=()):
    return SimpleNamespace(
        options=list(options), decision_kind="keep", suggested=None, current=None, robustness=None,
    )


def _render(conn, cross_check=None):
    return render_command_screen(
        conn=conn, gw_label_html="GW3", gw_label_plain="GW3", current_rec=None, ta=None, ca=_ca(),
        ft_value="1", ft_title="FREE TRANSFER", actual_points=None, next_xp=0.0, bank_m=0.0, squad_value_m=0.0,
        captain_name="Haaland", rank_tile_html="", chips_available=[], cross_check=cross_check,
    )


def test_command_screen_renders_a_real_cross_check_conflict(db_conn):
    """Real regression test: `render_command_screen` accepted a `cross_check`
    parameter since the Phase 6 COMMAND rebuild but never actually rendered
    it (confirmed live - `home.py`'s own superseded hero still did, via the
    same `_cross_check_html` reused here). A real FOOTBALL_CONFLICT axis
    must now appear in the rendered HTML, not be silently dropped."""
    cc = CaptainCrossCheck(
        captain_id=1, captain_name="Haaland",
        axes=(CrossCheckAxis(axis="FOOTBALL", verdict="FOOTBALL_CONFLICT", why="real disagreement text"),),
        all_agree=False,
    )
    html = _render(db_conn, cross_check=cc)
    assert "FOOTBALL" in html
    assert "CONFLICT" in html
    assert "real disagreement text" in html


def test_command_screen_renders_nothing_extra_when_cross_check_is_none(db_conn):
    html = _render(db_conn, cross_check=None)
    assert "cross-check-row" not in html


def _path(action, breakdown):
    return {"steps": [{"action": action}], "horizon_breakdown": breakdown}


def test_checkpoint_table_shows_chosen_vs_alternative_at_every_shared_horizon():
    """Real regression test for Phase 7.2 Part E: the CHOSEN vs STRONGEST
    ALTERNATIVE comparison must show simultaneously at every horizon both
    paths have real data for, with a real signed edge per horizon - reusing
    `sd["paths"]`'s own already-computed `horizon_breakdown`, never a
    second search."""
    paths = [
        _path("PLAY FREEHIT", {3: {"path_total": 200.0}, 5: {"path_total": 320.0}, 8: {"path_total": 492.0}}),
        _path("PLAY WILDCARD", {3: {"path_total": 192.0}, 5: {"path_total": 308.0}, 8: {"path_total": 480.0}}),
    ]
    html = _checkpoint_table_html(paths, "PLAY FREEHIT", "PLAY WILDCARD")
    assert "PLAY FREEHIT" in html and "PLAY WILDCARD" in html
    assert "200.0" in html and "192.0" in html
    assert "+8.0" in html  # 200.0 - 192.0 at 3GW
    assert "+12.0" in html  # 320.0 - 308.0 at 5GW


def test_checkpoint_table_empty_without_real_paths():
    assert _checkpoint_table_html(None, "ROLL", None) == ""
    assert _checkpoint_table_html([], "ROLL", None) == ""


def test_checkpoint_table_empty_when_only_one_path_exists():
    paths = [_path("ROLL", {3: {"path_total": 100.0}})]
    assert _checkpoint_table_html(paths, "ROLL", None) == ""


def _rank(median):
    return SimpleNamespace(option=SimpleNamespace(median=median))


def test_contribution_layer_shows_real_drivers_with_their_own_units():
    """Real regression test, Phase 7.3 Part 12 ('WHY THE MODEL PREFERS
    THIS') - each row must use its own real unit (pts vs a reachable-state
    count), never a fabricated shared scale."""
    auth = {"nominal_ev_advantage": 8.4, "optionality_delta": -2}
    ca = _ca(options=[_rank(6.2), _rank(4.8)])

    html = _contribution_layer_html(auth, ca)

    assert "WHY THE MODEL PREFERS THIS" in html
    assert "TRANSFER / CHIP EDGE" in html and "+8.4 pts" in html
    assert "CAPTAIN EDGE" in html and "+1.4 pts" in html
    assert "OPTIONALITY" in html and "-2 reachable states" in html


def test_contribution_layer_empty_without_authoritative_decision():
    assert _contribution_layer_html(None, _ca()) == ""


def test_contribution_layer_omits_rows_with_no_real_data_and_hides_entirely_below_two():
    """A single real driver (no captain alternative, no optionality data) is
    not enough to be worth a whole layer - real, honest omission rather than
    a one-row section."""
    auth = {"nominal_ev_advantage": 5.0, "optionality_delta": None}
    assert _contribution_layer_html(auth, _ca()) == ""
