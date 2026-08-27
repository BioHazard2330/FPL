from types import SimpleNamespace

import fpl_agent.optimization.adversarial_audit as aa_mod
from fpl_agent.models.expected_points import ComponentBreakdown
from fpl_agent.optimization.adversarial_audit import (
    ActionAuditRow,
    CausalChainStep,
    Falsifier,
    LeagueWideCheck,
    PlayerAudit,
    alternative_action_audit,
    audit_player,
    build_causal_chain,
    build_scorecard,
    classify_robustness,
    cold_start_audit,
    cross_check_against_strategic_plan,
    derive_falsifiers,
    league_wide_check,
    model_vs_football,
    qualitative_chain,
    run_stress_tests,
)


# --------------------------------------------------------------------------
# Stress tests / falsifiers - pure linear-perturbation math
# --------------------------------------------------------------------------

def _wep(total_appearance, goals, assists, bonus, clean_sheet=0.0, conceded=0.0):
    comp = ComponentBreakdown(
        appearance=total_appearance, goals=goals, assists=assists, bonus=bonus,
        clean_sheet=clean_sheet, cards=0.0, conceded=conceded, defcon=0.0,
    )
    return SimpleNamespace(total_median=comp.total, components=comp)


def _patch_wep(monkeypatch, by_player: dict):
    monkeypatch.setattr(aa_mod, "expected_points_window", lambda conn, pid, n_gw, from_event=None: by_player[pid])


def test_stress_test_adverse_direction_shrinks_the_gap(monkeypatch):
    # OUT (id=1): appearance=2, goals=1, assists=0.5, bonus=0.3 -> total 3.8
    # IN  (id=2): appearance=2, goals=5, assists=2.0, bonus=1.0 -> total 10.0
    # baseline delta = 10.0 - 3.8 - 0 (no hit) = 6.2
    _patch_wep(monkeypatch, {1: _wep(2, 1, 0.5, 0.3), 2: _wep(2, 5, 2.0, 1.0)})

    results = run_stress_tests(None, out_id=1, in_id=2, event=1, n_gw=1, uses_hit=False)

    attacking_15 = next(r for r in results if r.dimension == "ATTACKING_INVOLVEMENT" and r.magnitude == 0.15)
    assert attacking_15.baseline_delta == 6.2
    # OUT attacking group (1+0.5+0.3=1.8) up 15%, IN attacking group (5+2+1=8) down 15%.
    expected_stressed = round((10.0 - 8 * 0.15) - (3.8 + 1.8 * 0.15) - 0, 2)
    assert attacking_15.stressed_delta == expected_stressed
    assert attacking_15.decision_flips is False  # still well above the 1.0 xP bar


def test_stress_test_flags_a_real_flip(monkeypatch):
    # Baseline delta just barely above the 1.0 xP materiality bar - an adverse
    # attacking-involvement swing should push it back under the bar.
    _patch_wep(monkeypatch, {1: _wep(2, 0.5, 0.0, 0.0), 2: _wep(2, 1.5, 0.0, 0.0)})  # baseline delta = 1.0

    results = run_stress_tests(None, out_id=1, in_id=2, event=1, n_gw=1, uses_hit=False)

    attacking = [r for r in results if r.dimension == "ATTACKING_INVOLVEMENT"]
    assert any(r.decision_flips for r in attacking)


def test_classify_robustness_thresholds():
    fragile = [SimpleNamespace(magnitude=0.15, decision_flips=True)]
    moderate = [SimpleNamespace(magnitude=0.15, decision_flips=False), SimpleNamespace(magnitude=0.30, decision_flips=True)]
    robust = [SimpleNamespace(magnitude=0.15, decision_flips=False), SimpleNamespace(magnitude=0.30, decision_flips=False)]

    assert classify_robustness(fragile) == "FRAGILE"
    assert classify_robustness(moderate) == "MODERATE"
    assert classify_robustness(robust) == "ROBUST"


def test_derive_falsifiers_analytic_threshold_matches_hand_calc(monkeypatch):
    # ATTACKING group: OUT=1.8, IN=8.0 -> denom=9.8, baseline_delta=6.2
    # k* = (6.2 - 1.0) / 9.8 = 0.5306...
    _patch_wep(monkeypatch, {1: _wep(2, 1, 0.5, 0.3), 2: _wep(2, 5, 2.0, 1.0)})

    falsifiers = derive_falsifiers(None, out_id=1, in_id=2, event=1, n_gw=1, uses_hit=False, out_name="Out", in_name="In")

    attacking = next(f for f in falsifiers if "attacking involvement" in f.description)
    assert "~53%" in attacking.description
    assert "not derivable" not in attacking.threshold_note


def test_derive_falsifiers_reports_not_derivable_when_group_is_zero(monkeypatch):
    # Both players have zero goals/clean_sheet/conceded (all attacking value
    # comes from assists/bonus instead) - the TEAM_FIXTURE_CONTEXT group
    # (goals+clean_sheet+conceded) denominator is exactly 0.
    _patch_wep(monkeypatch, {1: _wep(2, 0, 1.0, 0.5, clean_sheet=0, conceded=0), 2: _wep(2, 0, 1.5, 0.5, clean_sheet=0, conceded=0)})

    falsifiers = derive_falsifiers(None, out_id=1, in_id=2, event=1, n_gw=1, uses_hit=False, out_name="Out", in_name="In")

    context = next(f for f in falsifiers if "Team Fixture Context" in f.description)
    assert "not derivable" in context.threshold_note


# --------------------------------------------------------------------------
# alternative_action_audit - merges independent per-horizon comparisons
# --------------------------------------------------------------------------

def _opt(label, kind, path_total, out_id=None, in_id=None):
    return SimpleNamespace(label=label, kind=kind, path_total=path_total, player_out_id=out_id, player_in_id=in_id, chip_name=None)


def test_alternative_action_audit_merges_by_label_across_horizons(monkeypatch):
    per_horizon = {
        3: [_opt("ROLL", "roll", 30.0), _opt("A -> B", "transfer", 28.0, 1, 2)],
        5: [_opt("ROLL", "roll", 55.0), _opt("A -> B", "transfer", 60.0, 1, 2)],
    }
    monkeypatch.setattr(aa_mod, "compare_starting_actions", lambda conn, *a, horizon_gw, **k: per_horizon[horizon_gw])
    monkeypatch.setattr(aa_mod, "search_transfer_sequences", lambda *a, **k: [])  # no known_paths -> no boost
    monkeypatch.setattr(aa_mod, "_safe_confidence", lambda conn, pid: None)

    rows = alternative_action_audit(None, [1, 2, 3], 1, 0, frozenset(), horizons=(3, 5), continuation_beam_width=1)

    by_label = {r.label: r for r in rows}
    assert by_label["A -> B"].horizon_results == {3: 28.0, 5: 60.0}
    assert by_label["ROLL"].horizon_results == {3: 30.0, 5: 55.0}
    # Ranked by the MAX horizon (5GW) path_total - "A -> B" (60.0) beats "ROLL" (55.0).
    assert rows[0].label == "A -> B"
    assert rows[0].main_reason_rejected is None
    assert "behind the winner" in rows[1].main_reason_rejected


# --------------------------------------------------------------------------
# _known_paths_boost / alternative_action_audit's real known_paths
# cross-reference - closing the search-space gap the audit found in itself
# --------------------------------------------------------------------------

def _real_option(label, kind, path_total, out_id=None, out_name=None, in_id=None, in_name=None):
    from fpl_agent.optimization.transfers import StartingActionOption

    return StartingActionOption(
        label=label, kind=kind, player_out_id=out_id, player_out_name=out_name,
        player_in_id=in_id, player_in_name=in_name, chip_name=None, uses_hit=False,
        path_total=path_total, best_continuation=None,
    )


def _real_seq(total_net_ev, out_id=None, out_name=None, in_id=None, in_name=None, chip=None):
    from fpl_agent.optimization.transfers import TransferSequence, TransferSequenceStep

    step = TransferSequenceStep(
        event=2, player_out_id=out_id, player_out_name=out_name, player_in_id=in_id,
        player_in_name=in_name, uses_hit=False, chip_played=chip,
    )
    return TransferSequence(
        steps=(step,), final_squad_ids=(1, 2, 3), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=total_net_ev, tiebreak_adjustment=0.0,
    )


def test_known_paths_boost_lifts_a_beam_limited_roll_option_to_the_wider_search_value():
    """Real regression test for the actual production bug: ROLL's own
    narrow continuation (611.55) undershot the wider search's real value
    (642.1) for the exact same opening action - the boost must lift it."""
    from fpl_agent.optimization.adversarial_audit import _known_paths_boost

    options = [_real_option("ROLL", "roll", 611.55), _real_option("PLAY WILDCARD", "chip", 638.3)]
    known_paths = [_real_seq(642.1)]  # ROLL (no transfer in the first step) at the wider beam width

    boosted = _known_paths_boost(options, known_paths)

    by_label = {o.label: o.path_total for o in boosted}
    assert by_label["ROLL"] == 642.1  # lifted to the real wider-search value
    assert by_label["PLAY WILDCARD"] == 638.3  # untouched - no matching real wider path for this label


def test_known_paths_boost_never_lowers_a_value():
    from fpl_agent.optimization.adversarial_audit import _known_paths_boost

    options = [_real_option("ROLL", "roll", 700.0)]
    known_paths = [_real_seq(642.1)]  # a real but WORSE wider-search value for the same label

    boosted = _known_paths_boost(options, known_paths)

    assert boosted[0].path_total == 700.0  # max() - never fabricates a lower real number


def test_known_paths_boost_is_a_noop_with_no_known_paths():
    from fpl_agent.optimization.adversarial_audit import _known_paths_boost

    options = [_real_option("ROLL", "roll", 611.55)]

    assert _known_paths_boost(options, []) == options


def test_alternative_action_audit_applies_known_paths_boost_only_at_the_max_horizon(monkeypatch):
    """Real, disclosed scope match with `fpl strategic-plan`'s own
    behavior (see alternative_action_audit's own docstring): the boost
    closes the search-space gap at the MAX horizon only, since that's the
    only horizon the authoritative planner itself cross-references a wider
    search for - shorter horizons stay exactly as narrow/unboosted on both
    sides, a genuine methodology match rather than a stricter standard
    invented only for this audit."""
    per_horizon = {
        3: [_real_option("ROLL", "roll", 30.0)],
        8: [_real_option("ROLL", "roll", 611.55), _real_option("PLAY WILDCARD", "chip", 638.3)],
    }
    monkeypatch.setattr(aa_mod, "compare_starting_actions", lambda conn, *a, horizon_gw, **k: per_horizon[horizon_gw])
    monkeypatch.setattr(aa_mod, "search_transfer_sequences", lambda *a, **k: [_real_seq(642.1)])
    monkeypatch.setattr(aa_mod, "_safe_confidence", lambda conn, pid: None)

    rows = alternative_action_audit(None, [1, 2, 3], 1, 0, frozenset(), horizons=(3, 8), continuation_beam_width=3)

    by_label = {r.label: r for r in rows}
    assert by_label["ROLL"].horizon_results[8] == 642.1  # boosted at the max horizon
    assert by_label["ROLL"].horizon_results[3] == 30.0  # unboosted at the shorter horizon
    # ROLL (642.1, boosted) now correctly beats PLAY WILDCARD (638.3) - the real
    # production disagreement this fix was built to close.
    assert rows[0].label == "ROLL"


# --------------------------------------------------------------------------
# league_wide_check
# --------------------------------------------------------------------------

def test_league_wide_check_flags_a_chosen_candidate_on_the_trap_list(monkeypatch):
    monkeypatch.setattr(aa_mod, "find_breakouts", lambda conn: [])
    monkeypatch.setattr(aa_mod, "find_differentials", lambda conn: [])
    monkeypatch.setattr(aa_mod, "find_traps", lambda conn: [SimpleNamespace(player_id=42)])

    result = league_wide_check(None, chosen_in_id=42)

    assert result.chosen_in_is_trap is True
    assert "not filtered by ownership" in result.candidate_pool_scope.lower()


def test_league_wide_check_no_flag_when_candidate_absent_from_traps(monkeypatch):
    monkeypatch.setattr(aa_mod, "find_breakouts", lambda conn: [])
    monkeypatch.setattr(aa_mod, "find_differentials", lambda conn: [])
    monkeypatch.setattr(aa_mod, "find_traps", lambda conn: [SimpleNamespace(player_id=99)])

    result = league_wide_check(None, chosen_in_id=42)

    assert result.chosen_in_is_trap is False


# --------------------------------------------------------------------------
# model_vs_football
# --------------------------------------------------------------------------

def _audit(player_id=1, web_name="X", total_xp_1gw=6.0, trends=None):
    return PlayerAudit(
        player_id=player_id, web_name=web_name, expected_minutes=85.0, p_zero=0.1, p_partial=0.1, p_full=0.8,
        total_xp_1gw=total_xp_1gw, components={}, data_confidence="MEDIUM", minutes_confidence="MEDIUM",
        overall_confidence="MEDIUM", understat_matches_played=2.0, minutes_basis="current_season_only",
        rotation_risk=None, prior_row_present=True, prior_is_stale=False, cross_league_prior_used=False,
        evidence_reasons=(), current_role=None, current_tactical_signal=None, current_fpl_outlook=None,
        persistent_trends=trends or [], ownership_percent=5.0, ownership_source="sampled", price_direction="STABLE",
        decision_contribution="squad member",
    )


def test_model_vs_football_no_signal():
    result = model_vs_football(None, _audit())
    assert result.agreement == "NO_FOOTBALL_SIGNAL"


def test_model_vs_football_agree_when_directions_match():
    trends = [{"signal": "GOAL_THREAT", "direction": "POSITIVE", "sample_size": 3}]
    result = model_vs_football(None, _audit(total_xp_1gw=6.0, trends=trends))
    assert result.agreement == "AGREE"


def test_model_vs_football_disagree_when_directions_diverge():
    trends = [{"signal": "GOAL_THREAT", "direction": "NEGATIVE", "sample_size": 3}]
    result = model_vs_football(None, _audit(total_xp_1gw=6.0, trends=trends))
    assert result.agreement == "DISAGREE"
    assert "under/overweighted" in result.decision_impact


# --------------------------------------------------------------------------
# build_causal_chain / build_scorecard - pure composition
# --------------------------------------------------------------------------

def _ta(decision_kind="transfer", chosen=True, qualitative_note=None, evidence_confidence="MEDIUM",
        robustness="ROBUST", decision_confidence="MEDIUM", information_value_note=None):
    candidate = SimpleNamespace(player_out_id=1, player_out_name="Out", player_in_id=2, player_in_name="In",
                                 net_ev_3gw=5.0, uses_hit=False) if chosen else None
    chosen_opt = SimpleNamespace(candidate=candidate) if chosen else None
    return SimpleNamespace(
        decision_kind=decision_kind, chosen=chosen_opt, candidates=[chosen_opt] if chosen_opt else [],
        reason="real reason text", qualitative_note=qualitative_note, evidence_confidence=evidence_confidence,
        robustness=robustness, decision_confidence=decision_confidence, information_value_note=information_value_note,
    )


def _ca(decision_kind="keep", qualitative_note=None):
    return SimpleNamespace(decision_kind=decision_kind, reason="captain reason", qualitative_note=qualitative_note,
                            current=None, suggested=None, delta=None)


def _locked(squad_ids=(1, 2, 3), free_transfers=1, source="synced_real"):
    return SimpleNamespace(squad_ids=frozenset(squad_ids), free_transfers=free_transfers, source=source)


def test_build_causal_chain_reports_the_real_winner():
    row = ActionAuditRow(label="Out -> In", kind="transfer", horizon_results={8: 100.0}, opportunity_cost="n/a",
                          confidence="MEDIUM", robustness="ROBUST", main_reason_rejected=None)
    chain = build_causal_chain(_locked(), _ta(), _ca(), [row])

    labels = [s.label for s in chain]
    assert labels[0] == "STARTING ACTION"
    assert chain[0].detail == "Out -> In"
    assert labels[-1] == "FINAL DECISION"
    assert "Out -> In" in chain[-1].detail


def test_build_causal_chain_handles_no_legal_action():
    chain = build_causal_chain(_locked(), _ta(decision_kind="review", chosen=False), _ca(), [])
    assert chain[0].detail == "no real legal starting action found"
    assert "REVIEW" in chain[-1].detail


def test_build_scorecard_low_confidence_on_fragile_stress_result():
    league = LeagueWideCheck("scope", 1, 1, 0, False, [], [], "note")
    action_audit = [
        ActionAuditRow("Out -> In", "transfer", {8: 100.0}, "n/a", "MEDIUM", "ROBUST", None),
        ActionAuditRow("ROLL", "roll", {8: 90.0}, "-10 vs winner", None, None, "behind"),
    ]
    sc = build_scorecard(_ta(), _ca(), "FRAGILE", league, [], action_audit)
    assert sc.confidence == "LOW"
    assert sc.decision_robustness == "FRAGILE"
    assert sc.final_decision == "ACT"


def test_build_scorecard_flags_trap_membership_in_why_not():
    league = LeagueWideCheck("scope", 0, 0, 1, True, [], [], "note")
    action_audit = [ActionAuditRow("Out -> In", "transfer", {8: 100.0}, "n/a", "MEDIUM", "ROBUST", None)]
    sc = build_scorecard(_ta(), _ca(), "ROBUST", league, [], action_audit)
    assert any("trap" in w.lower() for w in sc.why_might_not_trust)
    assert sc.confidence == "LOW"


def test_build_scorecard_roll_when_winner_is_roll():
    league = LeagueWideCheck("scope", 0, 0, 0, False, [], [], "note")
    action_audit = [ActionAuditRow("ROLL", "roll", {8: 100.0}, "n/a", None, None, None)]
    sc = build_scorecard(_ta(decision_kind="roll", chosen=False), _ca(), "ROBUST", league, [], action_audit)
    assert sc.final_decision == "ROLL"


def test_build_scorecard_forces_low_confidence_on_a_cross_check_disagreement():
    """Real regression test for the actual live production finding
    (2026-08-27): a real conflict with the cached, wider-beam `fpl
    strategic-plan` result must never be silently swallowed - it forces LOW
    confidence and appears in why_might_not_trust regardless of how strong
    every other real dimension looks."""
    league = LeagueWideCheck("scope", 0, 0, 0, False, [], [], "note")
    action_audit = [ActionAuditRow("PLAY WILDCARD", "chip", {8: 636.53}, "n/a", None, None, None)]
    sc = build_scorecard(
        _ta(), _ca(), "ROBUST", league, [], action_audit,
        cross_check_note="DISAGREES with the cached `fpl strategic-plan` result: ROLL wins there",
    )
    assert sc.confidence == "LOW"
    assert any("DISAGREES" in w for w in sc.why_might_not_trust)


# --------------------------------------------------------------------------
# cross_check_against_strategic_plan - the real self-check against the
# project's own wider-beam strategic_plan comparison
# --------------------------------------------------------------------------

def test_cross_check_returns_none_when_no_strategic_plan_logged(db_conn):
    row = ActionAuditRow("ROLL", "roll", {8: 100.0}, "n/a", None, None, None)
    assert cross_check_against_strategic_plan(db_conn, [row]) is None


def test_cross_check_flags_a_real_disagreement(db_conn):
    from fpl_agent.database.decisions import log_decision

    log_decision(
        db_conn, "strategic_plan", "ROLL wins",
        {"current_recommendation": {"label": "ROLL", "path_total": 642.1}},
    )
    db_conn.commit()
    row = ActionAuditRow("PLAY WILDCARD", "chip", {8: 636.53}, "n/a", None, None, None)

    note = cross_check_against_strategic_plan(db_conn, [row])

    assert note is not None
    assert "ROLL" in note and "PLAY WILDCARD" in note


def test_cross_check_returns_none_when_they_agree(db_conn):
    from fpl_agent.database.decisions import log_decision

    log_decision(
        db_conn, "strategic_plan", "ROLL wins",
        {"current_recommendation": {"label": "ROLL", "path_total": 642.1}},
    )
    db_conn.commit()
    row = ActionAuditRow("ROLL", "roll", {8: 642.1}, "n/a", None, None, None)

    assert cross_check_against_strategic_plan(db_conn, [row]) is None


# --------------------------------------------------------------------------
# DB-backed: audit_player / cold_start_audit / qualitative_chain
# --------------------------------------------------------------------------

def _seed_players(conn):
    now = "2026-01-01T00:00:00Z"
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','{now}')")
    conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, "
        f"squad_max_play, squad_select, updated_at) VALUES (1,'Forward','FWD','Forwards',1,3,3,'{now}')"
    )
    for pid, name in ((1, "Cold"), (2, "Warm")):
        conn.execute(
            f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
            f"VALUES ({pid},{pid},'{name}',1,1,'a',0,'{now}')"
        )
    conn.execute(
        f"INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        f"is_current, is_next, updated_at) VALUES (1,'GW1','{now}',0,1,0,0,1,'{now}')"
    )
    conn.commit()


def test_cold_start_audit_flags_a_player_with_no_prior_and_no_current_data(db_conn):
    _seed_players(db_conn)

    result = cold_start_audit(db_conn, [1, 2])

    assert len(result) == 2  # neither player has any real season history or Understat rows yet
    assert all(r.is_cold_start for r in result)
    assert "positional-average fallback" in result[0].note


def test_qualitative_chain_reads_a_real_observed_row(db_conn):
    _seed_players(db_conn)
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, "
        "status, source, retrieved_at, confidence) VALUES (1,'fm1','Premier League','t0',1,1,'FULL_TIME','fotmob','t0','high')"
    )
    db_conn.execute(
        "INSERT INTO player_fpl_implications (match_id, player_id, signal, direction, reason, confidence, "
        "created_at, phase) VALUES (1,1,'GOAL_THREAT','POSITIVE','real observed text','medium','t0','FULL_TIME')"
    )
    db_conn.commit()

    chain = qualitative_chain(db_conn, [1, 2])

    assert len(chain) == 1
    item = chain[0]
    assert item.player_id == 1
    assert item.observed == "real observed text"
    assert "GOAL_THREAT" in item.inferred
    assert "goals" in item.projection_component_affected
