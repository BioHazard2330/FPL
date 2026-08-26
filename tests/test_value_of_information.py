from types import SimpleNamespace

import fpl_agent.models.value_of_information as voi_mod
from fpl_agent.models.value_of_information import assess_information_value


def _fake_pc(matches_played, minutes_confidence, minutes_basis, rotation_risk=None, data_confidence="MEDIUM"):
    return SimpleNamespace(
        player_id=1, data_confidence=data_confidence, minutes_confidence=minutes_confidence,
        understat_matches_played=matches_played, minutes_basis=minutes_basis, rotation_risk=rotation_risk,
    )


def test_data_confidence_does_not_upgrade_when_one_more_match_stays_below_the_next_tier(monkeypatch):
    monkeypatch.setattr(voi_mod, "assess_projection_confidence", lambda conn, pid: _fake_pc(0.87, "MEDIUM", "predicted_lineup_confirmed_starting"))

    result = assess_information_value(None, 1)

    assert result.current_data_confidence == "MEDIUM"
    assert result.projected_data_confidence_next_gw == "MEDIUM"
    assert result.data_confidence_would_upgrade is False


def test_data_confidence_upgrades_when_one_more_match_crosses_the_high_threshold(monkeypatch):
    monkeypatch.setattr(voi_mod, "assess_projection_confidence", lambda conn, pid: _fake_pc(3.2, "MEDIUM", "predicted_lineup_confirmed_starting"))

    result = assess_information_value(None, 1)

    assert result.projected_data_confidence_next_gw == "HIGH"
    assert result.data_confidence_would_upgrade is True


def test_rotation_risk_means_waiting_does_not_help_minutes_confidence(monkeypatch):
    monkeypatch.setattr(
        voi_mod, "assess_projection_confidence",
        lambda conn, pid: _fake_pc(0.87, "MEDIUM", "blended_current_and_stale_prior", rotation_risk="real hedge quote"),
    )

    result = assess_information_value(None, 1)

    assert result.minutes_would_likely_improve_by_waiting is False
    assert "rotation-risk" in result.minutes_confidence_reason


def test_sample_size_driven_minutes_basis_would_improve_by_waiting(monkeypatch):
    monkeypatch.setattr(voi_mod, "assess_projection_confidence", lambda conn, pid: _fake_pc(0.87, "MEDIUM", "current_season_only"))

    result = assess_information_value(None, 1)

    assert result.minutes_would_likely_improve_by_waiting is True


def test_summary_states_no_material_value_when_neither_dimension_improves(monkeypatch):
    monkeypatch.setattr(
        voi_mod, "assess_projection_confidence",
        lambda conn, pid: _fake_pc(0.87, "HIGH", "blended_current_and_prior_season"),
    )

    result = assess_information_value(None, 1)

    assert "NOT materially improve" in result.summary
