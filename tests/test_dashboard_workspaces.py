"""Unit tests for the new HOME/PLAN/SQUAD workspace modules (2026-08-27,
frontend redesign) - direct, focused tests of the new presentation-only
functions, separate from the existing end-to-end `generate_dashboard_html`
coverage in test_dashboard.py/test_dashboard_state.py."""
from fpl_agent.monitoring.dashboard import data_payload, home, plan
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
