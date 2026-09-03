"""Regression tests for real whole-path credibility/fragility assessment
(2026-09-02, Phase 5 optimizer forensic rebuild)."""
from types import SimpleNamespace

import fpl_agent.optimization.path_credibility as pc_mod
from fpl_agent.optimization.path_credibility import assess_path_credibility, label_diverse_paths


def _step(event, out_id=None, out_name=None, in_id=None, in_name=None, chip=None, hit=False):
    return SimpleNamespace(
        event=event, player_out_id=out_id, player_out_name=out_name, player_in_id=in_id, player_in_name=in_name,
        chip_played=chip, uses_hit=hit,
    )


def _path(steps, final_bank_tenths=50):
    return SimpleNamespace(steps=steps, final_bank_tenths=final_bank_tenths)


def _fake_confidence(overall):
    from fpl_agent.models.projection_confidence import ProjectionConfidence

    return ProjectionConfidence(
        player_id=0, data_confidence=overall, minutes_confidence=overall, overall=overall,
        understat_matches_played=0.0, minutes_basis="no_data_available", rotation_risk=None,
        prior_row_present=False, prior_is_stale=False, finished_events=1, reasons=("fake",),
    )


def test_low_friction_for_a_clean_single_transfer_path(db_conn, monkeypatch):
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
    path = _path([_step(3, out_id=1, out_name="A", in_id=2, in_name="B")], final_bank_tenths=50)

    result = assess_path_credibility(db_conn, path)

    assert result.credibility_label == "LOW_FRICTION"
    assert result.speculative_transfer_count == 0
    assert result.chips_stacked_within_window is False
    assert result.forced_sequential_transfers == 0
    assert result.final_bank_thin is False


def test_speculative_transfer_counted_for_low_confidence_in_player(db_conn, monkeypatch):
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("LOW"))
    path = _path([_step(3, out_id=1, out_name="A", in_id=2, in_name="B")])

    result = assess_path_credibility(db_conn, path)

    assert result.speculative_transfer_count == 1
    assert "B" in result.speculative_players


def test_chip_stacking_detected_within_the_real_window(db_conn, monkeypatch):
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
    path = _path([
        _step(3, chip="freehit"), _step(4, chip="wildcard"), _step(5, chip="bboost"), _step(6, chip="3xc"),
    ])

    result = assess_path_credibility(db_conn, path)

    assert result.chip_count == 4
    assert result.chips_stacked_within_window is True
    # Real friction score here is exactly the stacking flag (+2, no
    # speculative transfers/forced sequences/thin bank in this fixture) -
    # MODERATE, not HIGH, under the module's own real, disclosed bands
    # (HIGH needs friction_score > 3). A real production path combining
    # stacking WITH a speculative transfer or thin bank reaches HIGH - see
    # the live production case in this module's own docstring.
    assert result.credibility_label == "MODERATE_FRICTION"


def test_no_stacking_flag_when_chips_are_real_spaced_out(db_conn, monkeypatch):
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
    path = _path([_step(3, chip="wildcard"), _step(10, chip="bboost")])

    result = assess_path_credibility(db_conn, path)

    assert result.chip_count == 2
    assert result.chips_stacked_within_window is False


def test_forced_sequential_transfer_detected_when_path_sells_what_it_bought(db_conn, monkeypatch):
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
    path = _path([
        _step(3, out_id=1, out_name="A", in_id=2, in_name="B"),
        _step(6, out_id=2, out_name="B", in_id=3, in_name="C"),  # sells B, bought at GW3
    ])

    result = assess_path_credibility(db_conn, path)

    assert result.forced_sequential_transfers == 1


def test_thin_bank_flagged(db_conn, monkeypatch):
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
    path = _path([_step(3, out_id=1, out_name="A", in_id=2, in_name="B")], final_bank_tenths=2)

    result = assess_path_credibility(db_conn, path)

    assert result.final_bank_thin is True


def test_roll_only_path_is_low_friction(db_conn, monkeypatch):
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
    path = _path([_step(3), _step(4)], final_bank_tenths=50)

    result = assess_path_credibility(db_conn, path)

    assert result.credibility_label == "LOW_FRICTION"
    assert result.chip_count == 0


def test_price_dependent_later_transfer_is_flagged(db_conn, monkeypatch):
    """PART 3 (2026-09-02, Phase 5B) - a LATER transfer step targeting a
    player with real RISE_LIKELY price momentum is flagged as a real,
    disclosed dependency - the path implicitly assumes today's price holds
    weeks out."""
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
    from fpl_agent.models.price_forecast import PriceForecast

    monkeypatch.setattr(
        "fpl_agent.models.price_forecast.classify_price_change",
        lambda conn, pid: PriceForecast(player_id=pid, direction="RISE_LIKELY", momentum_ratio=0.01, confidence="low"),
    )
    path = _path([
        _step(3, out_id=1, out_name="A", in_id=2, in_name="Immediate"),
        _step(6, out_id=3, out_name="C", in_id=4, in_name="LaterTarget"),
    ])

    result = assess_path_credibility(db_conn, path)

    assert result.price_dependent_transfers == 1
    assert "LaterTarget" in result.price_dependent_players
    # The IMMEDIATE (first-event) transfer is never flagged as price-
    # dependent - it's priced at today's real value for today, a real fact,
    # not an assumption about the future.
    assert "Immediate" not in result.price_dependent_players


def test_immediate_transfer_never_flagged_price_dependent_even_if_rising(db_conn, monkeypatch):
    monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
    from fpl_agent.models.price_forecast import PriceForecast

    monkeypatch.setattr(
        "fpl_agent.models.price_forecast.classify_price_change",
        lambda conn, pid: PriceForecast(player_id=pid, direction="RISE_LIKELY", momentum_ratio=0.01, confidence="low"),
    )
    path = _path([_step(3, out_id=1, out_name="A", in_id=2, in_name="B")])

    result = assess_path_credibility(db_conn, path)

    assert result.price_dependent_transfers == 0


class TestLabelDiversePaths:
    def test_labels_correspond_to_real_measured_properties(self, db_conn, monkeypatch):
        monkeypatch.setattr(pc_mod, "assess_projection_confidence", lambda conn, pid: _fake_confidence("HIGH"))
        from fpl_agent.optimization.strategy_robustness import PathRobustness

        verdicts = {1: "ROBUST", 2: "FRAGILE"}
        monkeypatch.setattr(
            pc_mod, "assess_path_robustness",
            lambda conn, path: PathRobustness(step_results=(), verdict=verdicts[path.marker], weakest_step=None, reason="r"),
        )

        path_a = _path([_step(3, out_id=1, out_name="A", in_id=2, in_name="B")])
        path_a.marker = 1
        path_b = _path([
            _step(3, chip="freehit"), _step(4, chip="wildcard"), _step(5, chip="bboost"), _step(6, chip="3xc"),
        ])
        path_b.marker = 2

        labels = label_diverse_paths(db_conn, [(1, path_a, 100.0), (2, path_b, 150.0)])

        assert "HIGHEST_EV" in labels[2]  # real higher total_ev
        assert "MOST_ROBUST" in labels[1]  # real ROBUST verdict vs FRAGILE
        assert "MOST_FLEXIBLE" in labels[1]  # real lower friction (no chip stacking)
