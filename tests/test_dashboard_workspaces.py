"""Unit tests for the new HOME/PLAN/SQUAD/INTELLIGENCE workspace modules
(2026-08-27/28, frontend redesign Phase 1+2) - direct, focused tests of the
new presentation-only functions, separate from the existing end-to-end
`generate_dashboard_html` coverage in test_dashboard.py/test_dashboard_state.py."""
from types import SimpleNamespace

from fpl_agent.monitoring.dashboard import (
    data_payload, fixtures, home, injuries, intelligence, market, plan, player_data, points_changes, price_history,
    squad, template_team,
)
from test_dashboard import _locked_and_decision, _seed
from test_optimization_squad import _seed as _seed_squad


# --- home.py: structured-fact copy composition -----------------------------

class _FakeCandidate:
    def __init__(self, player_out_name, player_in_name):
        self.player_out_name = player_out_name
        self.player_in_name = player_in_name


class _FakeChosen:
    def __init__(self, candidate):
        self.candidate = candidate


class _FakeTA:
    def __init__(self, decision_kind, chosen=None):
        self.decision_kind = decision_kind
        self.chosen = chosen


def test_home_reason_roll_from_current_rec():
    current_rec = {"verdict": "ACT", "action_kind": "roll", "label": "ROLL", "path_total": 5.0}
    assert home._action_reason(current_rec, None) == "No transfer clears the bar this week - hold your transfer."
    assert home._action_word(current_rec, None) == ("ROLL", "roll")


def test_home_reason_transfer_from_current_rec_splits_label_into_names():
    current_rec = {"verdict": "ACT", "action_kind": "transfer", "label": "Tzolis -> Tavernier", "path_total": 12.0}
    reason = home._action_reason(current_rec, None)
    assert "Tavernier in for Tzolis" in reason
    assert home._action_word(current_rec, None) == ("TRANSFER", "transfer")


def test_home_reason_chip_from_current_rec():
    current_rec = {"verdict": "ACT", "action_kind": "chip", "label": "PLAY WILDCARD", "path_total": 20.0}
    reason = home._action_reason(current_rec, None)
    assert "wildcard" in reason.lower()
    assert home._action_word(current_rec, None) == ("PLAY WILDCARD", "chip")


def test_home_reason_review_never_claims_confidence():
    current_rec = {"verdict": "REVIEW", "action_kind": "transfer", "label": "A -> B", "path_total": 1.0}
    reason = home._action_reason(current_rec, None)
    assert "thin" in reason
    assert home._action_word(current_rec, None) == ("REVIEW", "review")


def test_home_reason_falls_back_to_ta_when_no_strategic_plan_logged():
    ta = _FakeTA("transfer", chosen=_FakeChosen(_FakeCandidate("Tzolis", "Tavernier")))
    reason = home._action_reason(None, ta)
    assert "Tavernier in for Tzolis" in reason


def test_home_reason_no_squad():
    assert home._action_reason(None, None) == "Lock a real squad to see your recommendation."
    assert home._action_word(None, None) == ("NO SQUAD", "review")


class _FakeFreshness:
    def __init__(self, is_stale, computed_at="2026-08-29T10:00:00+00:00", decision_id=7,
                 model_version="calibrated-v2", stale_reason=None, age_relative="3h ago"):
        self.is_stale = is_stale
        self.computed_at = computed_at
        self.decision_id = decision_id
        self.model_version = model_version
        self.stale_reason = stale_reason
        self.age_relative = age_relative


def test_freshness_html_none_when_no_decision_yet():
    assert home._freshness_html(None) == ""


def test_freshness_html_shows_age_and_no_banner_when_fresh():
    result = home._freshness_html(_FakeFreshness(is_stale=False))
    assert "3h ago" in result
    assert "decision #7" in result
    assert "calibrated-v2" in result
    assert "RECOMPUTING" not in result


def test_freshness_html_shows_stale_banner_with_reason():
    result = home._freshness_html(_FakeFreshness(is_stale=True, stale_reason="Haaland: status_change (a -> i)"))
    assert "RECOMPUTING" in result
    assert "Haaland: status_change" in result  # `->` is HTML-escaped by _esc(), checked separately below
    assert "-&gt; i" in result


def test_render_hero_forces_recomputing_word_when_stale():
    """The real P0-audit fix: a stale cached decision must never render as
    if it were the current word (ROLL/TRANSFER/PLAY CHIP) - it must visibly
    say RECOMPUTING, not just add a caption nobody reads."""
    current_rec = {"verdict": "ACT", "action_kind": "transfer", "label": "A -> B", "path_total": 20.0}
    result = home.render_hero(
        gw_label_html="GW3", current_rec=current_rec, ta=None, ca=None, ft_value="1", ft_title="",
        actual_points=None, next_xp=50.0, bank_m=0.5, captain_name="Test", rank_tile_html="",
        freshness=_FakeFreshness(is_stale=True, stale_reason="Test Player: status_change (a -> i)"),
    )
    assert "RECOMPUTING" in result
    assert "home-hero-review" in result  # reuses the existing amber review styling
    assert ">TRANSFER<" not in result


def test_render_hero_includes_the_system_live_strip_shell():
    """No `live_snapshot` passed (e.g. `build_live_snapshot` itself failed) -
    real hook ids still exist for the client JS poll to find, and the strip
    honestly shows "not polled yet" rather than a fabricated value."""
    result = home.render_hero(
        gw_label_html="GW3", current_rec=None, ta=None, ca=None, ft_value="1", ft_title="",
        actual_points=None, next_xp=50.0, bank_m=0.5, captain_name="Test", rank_tile_html="",
    )
    for expected_id in (
        "system-live-strip", "system-live-snapshot-age", "system-live-next-check",
        "system-live-rank-age", "system-live-rank-next",
        "system-live-decision-age", "system-live-decision-status", "system-live-degraded",
    ):
        assert f'id="{expected_id}"' in result, f"missing {expected_id}"
    assert 'data-live-state="unknown"' in result


def test_render_hero_system_live_strip_uses_real_server_rendered_values_when_snapshot_given():
    """Real fix (2026-08-28, direct user report: a dashboard opened via
    `file://` - downloaded/copied out of `data/` - showed this strip stuck
    at "not yet polled"/"unavailable" forever, since `fetch()` is blocked
    under the `file://` origin). When `assemble.py` passes the same
    snapshot `write_live_snapshot` already computes, the strip must render
    real values server-side instead of the placeholder shell - the client
    poll (when it can reach a real server) then layers faster updates on
    top unchanged."""
    snapshot = {
        "generated_at": "2026-08-28T12:00:00+00:00",
        "recommendation": {"computed_at": "2026-08-28T06:00:00+00:00", "status": "CURRENT"},
        "rank": {"retrieved_at": "2026-08-28T11:30:00+00:00"},
        "cadence": {
            "system": {"last_sync_at": "2026-08-28T11:50:00+00:00"},
            "rank": {"next_due_floor_minutes": 15},
        },
        "source_freshness": [
            {"source": "bbc_sport_rss", "last_success": "2026-08-28T11:00:00+00:00", "degraded": False},
            {"source": "odds_api", "last_success": "2026-08-27T00:00:00+00:00", "degraded": True},
        ],
    }
    result = home.render_hero(
        gw_label_html="GW3", current_rec=None, ta=None, ca=None, ft_value="1", ft_title="",
        actual_points=None, next_xp=50.0, bank_m=0.5, captain_name="Test", rank_tile_html="",
        live_snapshot=snapshot,
    )
    assert 'data-live-state="live"' in result
    assert "not yet polled" not in result
    # Real status-first wording (2026-08-28, direct user requirement: never
    # show a bare "CURRENT" without context) - "Current" title-case label +
    # an explicit "computed Xh ago" detail, not just the raw status word.
    assert ">Current<" in result
    assert "computed" in result
    assert "1 source(s) degraded: odds_api" in result


def test_render_hero_shows_real_live_captain_points_when_available():
    """Real "live browser patch coverage" gap closed (2026-08-28, direct
    user requirement) - the snapshot already carries `points.captain_points`
    but the Captain tile only ever showed the captain's NAME, never their
    real live score. Must render it server-side when available, and stay
    honestly empty (never a fabricated 0) when it isn't."""
    snapshot_with_points = {"points": {"points": 42.0, "captain_points": 16.0}}
    result = home.render_hero(
        gw_label_html="GW3", current_rec=None, ta=None, ca=None, ft_value="1", ft_title="",
        actual_points=None, next_xp=50.0, bank_m=0.5, captain_name="Haaland", rank_tile_html="",
        live_snapshot=snapshot_with_points,
    )
    assert "id='live-captain-points'" in result
    assert "16 pts" in result

    result_no_live_data = home.render_hero(
        gw_label_html="GW3", current_rec=None, ta=None, ca=None, ft_value="1", ft_title="",
        actual_points=None, next_xp=50.0, bank_m=0.5, captain_name="Haaland", rank_tile_html="",
    )
    assert "id='live-captain-points'></span>" in result_no_live_data  # honestly empty, no fabricated points


class _FakePlayer:
    def __init__(self, web_name, median):
        self.web_name = web_name
        self.median = median


class _FakeCaptainAnalysis:
    def __init__(self, decision_kind, current=None, suggested=None, delta=None, reason=None):
        self.decision_kind = decision_kind
        self.current = current
        self.suggested = suggested
        self.delta = delta
        self.reason = reason


def test_captain_verdict_keep_is_a_plain_structured_sentence():
    ca = _FakeCaptainAnalysis("keep", current=_FakePlayer("Haaland", 8.2))
    result = home._captain_verdict_html(ca)
    assert result == "Captain: keep Haaland (median 8.2 xP)."


def test_captain_verdict_change_names_both_players():
    ca = _FakeCaptainAnalysis("change", current=_FakePlayer("Haaland", 6.0), suggested=_FakePlayer("Salah", 7.5), delta=1.5)
    result = home._captain_verdict_html(ca)
    assert "Haaland" in result and "Salah" in result and "+1.5" in result


def test_captain_verdict_escapes_untrusted_names():
    ca = _FakeCaptainAnalysis("keep", current=_FakePlayer("<script>alert(1)</script>", 5.0))
    result = home._captain_verdict_html(ca)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_captain_verdict_none_is_empty():
    assert home._captain_verdict_html(None) == ""


class _FakeCrossCheckAxis:
    def __init__(self, axis, verdict, why):
        self.axis = axis
        self.verdict = verdict
        self.why = why


class _FakeCrossCheck:
    def __init__(self, axes, all_agree):
        self.axes = axes
        self.all_agree = all_agree


def test_cross_check_html_none_renders_nothing():
    assert home._cross_check_html(None) == ""


def test_cross_check_html_all_agree_shows_no_conflict_line():
    cc = _FakeCrossCheck(
        axes=[
            _FakeCrossCheckAxis("FOOTBALL", "AGREE", "no conflict"),
            _FakeCrossCheckAxis("MARKET", "AGREE", "both models pick Haaland"),
            _FakeCrossCheckAxis("TEMPLATE", "AGREE", "in the pool"),
        ],
        all_agree=True,
    )
    result = home._cross_check_html(cc)
    assert "FOOTBALL AGREE" in result
    assert "No real conflicts" in result


def test_cross_check_html_surfaces_a_real_conflict_reason():
    cc = _FakeCrossCheck(
        axes=[
            _FakeCrossCheckAxis("FOOTBALL", "AGREE", "no conflict"),
            _FakeCrossCheckAxis("MARKET", "MARKET_CONFLICT", "our model picks Haaland, Solio picks Salah"),
            _FakeCrossCheckAxis("TEMPLATE", "AGREE", "in the pool"),
        ],
        all_agree=False,
    )
    result = home._cross_check_html(cc)
    assert "MARKET CONFLICT" in result
    assert "Solio picks Salah" in result


# --- plan.py: path descriptor / confidence ----------------------------------

def test_path_descriptor_pure_roll():
    path = {"steps": [{"event": 2, "action": "ROLL"}, {"event": 3, "action": "ROLL"}]}
    assert plan.path_descriptor(path) == "Roll every week"


def test_path_descriptor_single_transfer():
    path = {"steps": [{"event": 2, "action": "A -> B", "player_out_id": 1, "player_in_id": 2}]}
    assert plan.path_descriptor(path) == "1 transfer at GW2"


def test_path_descriptor_multiple_transfers():
    path = {"steps": [
        {"event": 2, "action": "A -> B", "player_out_id": 1, "player_in_id": 2},
        {"event": 4, "action": "C -> D", "player_out_id": 3, "player_in_id": 4},
    ]}
    assert plan.path_descriptor(path) == "2 transfers across the horizon"


def test_path_descriptor_chip_with_transfers():
    path = {"steps": [
        {"event": 3, "action": "PLAY WILDCARD", "chip_played": "wildcard"},
        {"event": 5, "action": "A -> B", "player_out_id": 1, "player_in_id": 2},
    ]}
    assert plan.path_descriptor(path) == "Wildcard at GW3 + 1 transfer"


def test_path_confidence_none_for_pure_roll():
    path = {"steps": [{"event": 2, "action": "ROLL"}]}
    assert plan.path_confidence(None, path) is None


# --- data_payload.py: minimal, purpose-built, single snapshot ---------------

def test_workspace_payload_has_no_locked_squad_shape(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    result = data_payload.build_workspace_payload(
        db_conn, locked=None, sd=None, current_rec=None,
        confidence_fn=plan.path_confidence, descriptor_fn=plan.path_descriptor,
    )

    assert result["decision"] is None
    assert result["paths"] == []
    assert result["players"] == {}


def test_workspace_payload_is_minimal_not_a_db_dump(db_conn):
    """The payload must carry only the fields workspaces actually render -
    never every column a raw players/strategic_plan-detail table has (direct
    spec: "payload is minimal and purpose-built, not a database dump")."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, decision = _locked_and_decision(db_conn)
    sd = {
        "horizon_gw": 8,
        "paths": [{
            "path_total": 10.0, "delta_vs_roll": 2.0, "final_free_transfers": 1, "final_bank_tenths": 5,
            "steps": [{"event": 2, "action": "ROLL", "player_out_id": None, "player_in_id": None, "uses_hit": False}],
        }],
    }
    current_rec = {"verdict": "ACT", "action_kind": "roll", "label": "ROLL", "path_total": 10.0, "evidence_confidence": None}

    result = data_payload.build_workspace_payload(
        db_conn, locked=locked, sd=sd, current_rec=current_rec,
        confidence_fn=plan.path_confidence, descriptor_fn=plan.path_descriptor,
    )

    assert set(result["decision"].keys()) == {
        "verdict", "action_kind", "label", "path_total", "evidence_confidence",
        "computed_at", "decision_id", "model_version", "is_stale", "stale_reason",
    }
    assert set(result["paths"][0].keys()) == {
        "id", "label", "score", "delta_vs_roll", "confidence", "descriptor", "is_leader",
        "final_free_transfers", "final_bank_tenths", "steps",
    }
    for player in result["players"].values():
        assert set(player.keys()) == {"name", "team", "position", "price"}


def test_render_payload_script_escapes_script_close_tag():
    html = data_payload.render_payload_script({"note": "</script><script>alert(1)</script>"})
    assert "</script><script>" not in html
    assert html.startswith('<script id="workspace-data" type="application/json">')


# --- intelligence.py: league-wide team-signal cards -------------------------

def _fake_trend(direction, label="PERSISTENT_TREND"):
    return SimpleNamespace(signal="TEAM_ATTACK", label=label, current_direction=direction, sample_size=2, history=[direction])


def _fake_qualitative(**kwargs):
    defaults = dict(
        current_tactical_signal=None, current_attacking_signal=None, current_defensive_signal=None,
        current_key_observation=None, current_fpl_implication=None, current_confidence=None, trends=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _fake_outlook(team_id=1, team_name="Arsenal", qualitative=None, churn_label="squad largely retained (5% turnover)",
                   formation=None, manager_change=None, lineup_news=None):
    return SimpleNamespace(
        team_id=team_id, team_name=team_name, qualitative=qualitative, churn_label=churn_label,
        formation=formation, manager_change=manager_change, lineup_news=lineup_news,
    )


def test_signal_arrow_maps_direction_to_real_arrow():
    assert intelligence._signal_arrow("POSITIVE") == " &uarr;"
    assert intelligence._signal_arrow("NEGATIVE") == " &darr;"
    assert intelligence._signal_arrow(None) == ""
    assert intelligence._signal_arrow("NEUTRAL") == ""


def test_leading_trend_skips_noise():
    trends = [_fake_trend("POSITIVE", label="NOISE"), _fake_trend("NEGATIVE", label="PERSISTENT_TREND")]
    trend = intelligence._leading_trend(trends)
    assert trend.current_direction == "NEGATIVE"


def test_leading_trend_none_when_every_real_trend_is_noise():
    trends = [_fake_trend("POSITIVE", label="NOISE")]
    assert intelligence._leading_trend(trends) is None


def test_team_signal_card_skipped_when_no_real_qualitative_data(db_conn):
    outlook = _fake_outlook(qualitative=None)
    assert intelligence._team_signal_card(db_conn, outlook, in_squad=False) is None

    outlook_empty = _fake_outlook(qualitative=_fake_qualitative())
    assert intelligence._team_signal_card(db_conn, outlook_empty, in_squad=False) is None


def test_team_signal_card_renders_real_fields_and_arrow(db_conn):
    q = _fake_qualitative(
        current_attacking_signal="Strong attacking environment",
        current_key_observation="1.88 xG · 20 shots",
        current_fpl_implication="Tzolis / Calafiori benefit",
        current_confidence="MEDIUM",
        trends=[_fake_trend("POSITIVE")],
    )
    outlook = _fake_outlook(qualitative=q)

    result = intelligence._team_signal_card(db_conn, outlook, in_squad=True)

    assert "ARSENAL" in result and "&uarr;" in result
    assert "Strong attacking environment" in result
    assert "Tzolis / Calafiori benefit" in result
    assert "MEDIUM" in result
    assert "your squad" in result


def test_render_what_changed_html_empty_state(db_conn):
    result = intelligence.render_what_changed_html(db_conn, set())
    assert "No real match-analyzed team signals yet" in result


# --- squad.py: projected-GW real shirt tiles --------------------------------

def _fake_player(pid, name, team_short="ARS", team_code=3, position="MID"):
    return {"id": pid, "web_name": name, "team_short": team_short, "team_code": team_code, "position": position, "price_tenths": 55}


def _fake_candidate(pid, name, position="MID", median=5.0):
    from fpl_agent.optimization.squad import PlayerCandidate
    return PlayerCandidate(
        player_id=pid, web_name=name, position=position, team_id=1, team_short="ARS",
        price_tenths=55, xp=median, median=median, floor=median * 0.5, ceiling=median * 1.5,
        confidence="MEDIUM", expected_minutes=90.0,
    )


def _fake_xi(starting, bench=()):
    from fpl_agent.optimization.squad import StartingXI
    starting = list(starting)
    return StartingXI(
        starting=starting, bench=list(bench),
        captain=starting[0] if starting else None,
        vice_captain=starting[1] if len(starting) > 1 else None,
    )


def test_projected_shirt_tile_marks_the_incoming_player():
    p = _fake_player(1, "Rice")
    result = squad._projected_shirt_tile(p, is_in=True)
    assert "projected-tile-in" in result
    assert "Rice" in result
    assert "shirt_3-66.webp" in result

    not_in = squad._projected_shirt_tile(p, is_in=False)
    assert "projected-tile-in" not in not_in


def test_projected_shirt_tile_shows_real_player_xp():
    p = _fake_player(1, "Rice")
    with_xp = squad._projected_shirt_tile(p, is_in=False, xp=7.3)
    assert "7.3 xP" in with_xp

    without_xp = squad._projected_shirt_tile(p, is_in=False)
    assert "&mdash; xP" in without_xp  # honest, never a fabricated number


def test_projected_squad_html_shows_transfer_and_grouped_tiles():
    lookup = {
        1: _fake_player(1, "Raya", position="GKP"),
        2: _fake_player(2, "Gabriel", position="DEF"),
        3: _fake_player(3, "Saka", position="MID"),
    }
    step = {"event": 3, "player_out_id": 2, "player_in_id": 3, "action": "Gabriel -> Saka", "uses_hit": False}
    xi = _fake_xi([_fake_candidate(1, "Raya", "GKP"), _fake_candidate(3, "Saka", "MID")])

    result = squad._projected_squad_html(lookup, xi, step)

    assert "OUT Gabriel" in result and "IN Saka" in result
    assert "GKP" in result and "MID" in result
    assert "Raya" in result and "Saka" in result
    assert result.count("Gabriel") == 1  # sold player named only in the transfer line, not a tile (not in squad_here)


def test_projected_squad_html_roll_step_has_no_transfer_line():
    lookup = {1: _fake_player(1, "Raya", position="GKP")}
    step = {"event": 3, "player_out_id": None, "player_in_id": None, "action": "ROLL"}
    xi = _fake_xi([_fake_candidate(1, "Raya", "GKP")])

    result = squad._projected_squad_html(lookup, xi, step)

    assert "ROLL - no transfer this GW" in result


def test_projected_squad_html_marks_captain_and_vice_and_shows_bench():
    """Real regression for the P0 audit fix - captain/vice are resolved PER
    PROJECTED SQUAD STATE (via `xi`), not the current squad's fixed pick,
    and the bench renders as its own separate group."""
    lookup = {
        1: _fake_player(1, "Raya", position="GKP"),
        2: _fake_player(2, "Saka", position="MID"),
        3: _fake_player(3, "Rice", position="MID"),
        4: _fake_player(4, "Havertz", position="FWD"),
    }
    step = {"event": 3, "player_out_id": None, "player_in_id": None, "action": "ROLL"}
    xi = _fake_xi(
        [_fake_candidate(2, "Saka", "MID", median=9.0), _fake_candidate(3, "Rice", "MID", median=6.0)],
        bench=[_fake_candidate(1, "Raya", "GKP", median=3.0), _fake_candidate(4, "Havertz", "FWD", median=2.0)],
    )

    result = squad._projected_squad_html(lookup, xi, step)

    assert "projected-tile-cap-badge" in result
    assert "projected-tile-vice-badge" in result
    assert "projected-bench-row" in result
    assert "projected-gw-score" in result
    assert "24.0 projected pts" in result  # (9.0 + 6.0) + captain (Saka) doubled: +9.0


# --- injuries.py / player_data.py / market.py's new league-wide panels -----
# (2026-08-28, direct fpl.page screenshot comparison - "the screenshots
# should show everything... whats missing")

def test_injuries_panel_honest_empty_state(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    result = injuries.render_injuries_html(db_conn)
    assert "No real injury" in result


def test_injuries_panel_shows_a_real_flagged_player(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute("UPDATE players SET status='i', news='Hamstring injury - 6 weeks' WHERE id=1")
    db_conn.commit()

    result = injuries.render_injuries_html(db_conn)

    assert "P1" in result  # _seed's own web_name for player 1
    assert "Hamstring injury" in result


def test_expected_data_panel_honest_empty_state_before_any_backfill(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    result = player_data.render_expected_data_html(db_conn)
    assert "No real current-season Understat data synced yet" in result


def test_team_odds_panel_honest_empty_state_with_no_fixtures(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    result = market.render_team_odds_html(db_conn)
    assert "No real upcoming fixtures" in result


def test_top_transfers_panel_honest_empty_state(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    result = market.render_top_transfers_html(db_conn, "in")
    assert "No real transfer-momentum data synced yet" in result


# --- Template Team / Points Changes / Price History (fpl.page-parity pass) ---

def test_template_team_panel_renders_real_positions(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    for pid, in db_conn.execute("SELECT id FROM players").fetchall():
        db_conn.execute(
            "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
            "VALUES (?, 10.0, 't0', NULL)",
            (pid,),
        )
    db_conn.commit()
    result = template_team.render_template_team_html(db_conn)
    assert "empty-state" not in result
    assert "projected-tile" in result


def test_template_team_panel_shows_real_overlap_and_differential(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    for pid, in db_conn.execute("SELECT id FROM players").fetchall():
        db_conn.execute(
            "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
            "VALUES (?, 10.0, 't0', NULL)",
            (pid,),
        )
    # Player 1 (GKP, top_n=3 default so it's in the template pool) gets a
    # very low real ownership - the squad's own honest differential pick.
    db_conn.execute("UPDATE player_ownership_history SET selected_by_percent=0.5 WHERE player_id=1")
    db_conn.commit()

    squad_ids = {r[0] for r in db_conn.execute("SELECT id FROM players").fetchall()}
    result = template_team.render_template_team_html(db_conn, squad_ids)

    assert "template-overlap-stat" in result
    assert "P1" in result  # lowest-owned squad player (_seed's own web_name for player 1)


def test_points_changes_panel_honest_empty_state_no_finished_gw(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,0,0,1,0,'t0')"
    )
    db_conn.commit()
    result = points_changes.render_points_changes_html(db_conn, set())
    assert "No finished gameweek yet" in result


def test_points_changes_panel_no_revisions_state(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,1,0,0,1,'t0')"
    )
    db_conn.commit()
    result = points_changes.render_points_changes_html(db_conn, set())
    assert "No bonus revisions observed" in result
    assert "No defensive contribution revisions observed" in result


def test_price_history_panel_renders_without_crashing(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    result = price_history.render_price_history_html(db_conn, set())
    assert "Predicted Price Changes" in result
    assert "Price Changes History" in result


# --- Fixture Tool: real Rotation (blank/double-GW) sort (fpl.page-parity pass) ---

def test_fixture_tool_flags_real_blank_and_double_gameweeks(db_conn):
    from test_fixtures_model import _seed_teams_and_fixtures

    _seed_teams_and_fixtures(db_conn)
    db_conn.execute("UPDATE events SET is_current=1 WHERE id=10")
    db_conn.commit()

    result = fixtures.render_fixture_tool_html(db_conn, set())

    assert "fdr-rotation-btn" not in result  # sanity: no stray leftover class name
    assert "data-rotation=\"double\"" in result
    assert "data-rotation=\"blank\"" in result
    assert "DGW" in result
    assert "BGW" in result
    assert "Rotation (DGW/BGW)" in result
    assert "fdr-reset-btn" in result
