"""Unit tests for the new HOME/PLAN/SQUAD/INTELLIGENCE workspace modules
(2026-08-27/28, frontend redesign Phase 1+2) - direct, focused tests of the
new presentation-only functions, separate from the existing end-to-end
`generate_dashboard_html` coverage in test_dashboard.py/test_dashboard_state.py."""
from types import SimpleNamespace

from fpl_agent.monitoring.dashboard import data_payload, home, injuries, intelligence, market, plan, player_data, squad
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
    assert home._action_word(current_rec, None) == ("PLAY CHIP", "chip")


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

    assert set(result["decision"].keys()) == {"verdict", "action_kind", "label", "path_total", "evidence_confidence"}
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


def test_projected_shirt_tile_marks_the_incoming_player():
    p = _fake_player(1, "Rice")
    result = squad._projected_shirt_tile(p, is_in=True)
    assert "projected-tile-in" in result
    assert "Rice" in result
    assert "shirt_3-66.webp" in result

    not_in = squad._projected_shirt_tile(p, is_in=False)
    assert "projected-tile-in" not in not_in


def test_projected_squad_html_shows_transfer_and_grouped_tiles():
    lookup = {
        1: _fake_player(1, "Raya", position="GKP"),
        2: _fake_player(2, "Gabriel", position="DEF"),
        3: _fake_player(3, "Saka", position="MID"),
    }
    step = {"event": 3, "player_out_id": 2, "player_in_id": 3, "action": "Gabriel -> Saka", "uses_hit": False}

    result = squad._projected_squad_html(lookup, {1, 3}, step, {})

    assert "OUT Gabriel" in result and "IN Saka" in result
    assert "GKP" in result and "MID" in result
    assert "Raya" in result and "Saka" in result
    assert result.count("Gabriel") == 1  # sold player named only in the transfer line, not a tile (not in squad_here)


def test_projected_squad_html_roll_step_has_no_transfer_line():
    lookup = {1: _fake_player(1, "Raya", position="GKP")}
    step = {"event": 3, "player_out_id": None, "player_in_id": None, "action": "ROLL"}

    result = squad._projected_squad_html(lookup, {1}, step, {})

    assert "ROLL - no transfer this GW" in result


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
