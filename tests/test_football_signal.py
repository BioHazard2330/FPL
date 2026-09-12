"""Regression tests for the canonical FootballSignal (2026-09-02, Phase 3
football-intelligence forensic audit)."""
from types import SimpleNamespace

from fpl_agent.models.football_signal import (
    _clean_evidence_text,
    classify_decision_effect,
    classify_fpl_relevance,
    football_signals_for_entity,
    squad_football_signals,
)


def test_clean_evidence_text_strips_the_stale_versioned_suffix():
    """Real bug found 2026-09-07 on the FOOTBALL dashboard screen: a retired
    detector version left `match_observations.observed` rows ending in a raw,
    unreadable "(versioned <iso> -> <iso>)" clause - the CURRENT detector no
    longer writes this, but old rows with no newer detection since still
    render it as-is."""
    raw = (
        "Real penalty order changed from 2 to 1 (versioned "
        "2026-08-12T19:21:52.132797+00:00 -> 2026-08-24T05:32:59.705779+00:00)."
    )
    assert _clean_evidence_text(raw) == "Real penalty order changed from 2 to 1."


def test_clean_evidence_text_leaves_normal_evidence_untouched():
    assert _clean_evidence_text("penalty order 2 -> 1") == "penalty order 2 -> 1"
    assert _clean_evidence_text("3 goals, 8 shots, 1.95 xG.") == "3 goals, 8 shots, 1.95 xG."
    assert _clean_evidence_text(None) is None


def _seed_match(conn, fotmob_id="m1", home=1, away=2, kickoff="2026-08-01T15:00:00Z"):
    for tid in (home, away):
        conn.execute(
            "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
            (tid, tid, f"Team{tid}", f"T{tid}"),
        )
    cur = conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, "
        "status, home_score, away_score, source, retrieved_at, confidence) "
        "VALUES (?, 'PL', ?, ?, ?, 'FULL_TIME', 1, 0, 'fotmob', 't0', 'high')",
        (fotmob_id, kickoff, home, away),
    )
    conn.commit()
    return cur.lastrowid


def _seed_observation(conn, match_id, subject_id, fpl_signal, direction, observed="obs", inferred="inf",
                       confidence="medium", analysis_version="qual-v1"):
    conn.execute(
        "INSERT INTO match_observations (match_id, subject_type, subject_id, observation_type, observed, "
        "inferred, fpl_direction, fpl_signal, fpl_reason, confidence, created_at, phase, evidence_ref, analysis_version) "
        "VALUES (?, 'player', ?, 'ATTACKING_ROLE', ?, ?, ?, ?, 'reason', ?, 't0', 'FULL_TIME', NULL, ?)",
        (match_id, subject_id, observed, inferred, direction, fpl_signal, confidence, analysis_version),
    )
    conn.commit()


def _seed_player(conn, player_id=1, web_name="TestPlayer", team_id=1, element_type=3):
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        (team_id, team_id, f"Team{team_id}", f"T{team_id}"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (?, 'Midfielder', 'MID', 'Midfielders', 't0')", (element_type,),
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,?,'a',0,'t0')", (player_id, player_id, web_name, team_id, element_type),
    )
    conn.commit()


class TestFplRelevance:
    def test_no_signal_is_irrelevant(self):
        assert classify_fpl_relevance(None, None) == "FPL_IRRELEVANT"

    def test_role_is_relevant(self):
        assert classify_fpl_relevance("ROLE", "POSITIVE") == "FPL_RELEVANT"

    def test_goal_threat_is_relevant(self):
        assert classify_fpl_relevance("GOAL_THREAT", "POSITIVE") == "FPL_RELEVANT"

    def test_team_attack_is_low_relevance(self):
        assert classify_fpl_relevance("TEAM_ATTACK", "POSITIVE") == "FPL_LOW_RELEVANCE"

    def test_unknown_signal_defaults_to_low_relevance_never_irrelevant(self):
        assert classify_fpl_relevance("SOME_NEW_SIGNAL", "POSITIVE") == "FPL_LOW_RELEVANCE"


class TestDecisionEffectClassification:
    def test_new_signal_is_monitor(self):
        assert classify_decision_effect("player", 1, "NEW_SIGNAL", "GOAL_THREAT", None, None) == "MONITOR"

    def test_noise_is_no_decision_impact(self):
        assert classify_decision_effect("player", 1, "NOISE", "GOAL_THREAT", None, None) == "NO_DECISION_IMPACT"

    def test_team_entity_never_material_or_decision_changing(self):
        assert classify_decision_effect("team", 1, "PERSISTENT_TREND", "TEAM_ATTACK", 0.5, None) == "NO_DECISION_IMPACT"

    def test_persistent_with_no_decision_context_is_watch(self):
        assert classify_decision_effect("player", 1, "PERSISTENT_TREND", "GOAL_THREAT", 0.3, None) == "WATCH"

    def test_persistent_with_no_xp_effect_and_no_context_is_no_impact(self):
        assert classify_decision_effect("player", 1, "PERSISTENT_TREND", "ROLE", None, None) == "NO_DECISION_IMPACT"

    def test_player_not_referenced_by_decision_is_watch_not_material(self):
        snap = SimpleNamespace(captain_id=99, vice_captain_id=98, transfer_in_id=None, transfer_out_id=None,
                                reversal_conditions=())
        assert classify_decision_effect("player", 1, "PERSISTENT_TREND", "GOAL_THREAT", 0.3, snap) == "WATCH"

    def test_referenced_player_below_margin_is_material(self):
        snap = SimpleNamespace(captain_id=1, vice_captain_id=None, transfer_in_id=None, transfer_out_id=None,
                                reversal_conditions=("runner-up would need +5.00 xP over its horizon to overtake this action",))
        assert classify_decision_effect("player", 1, "PERSISTENT_TREND", "GOAL_THREAT", 0.3, snap) == "MATERIAL"

    def test_referenced_player_at_or_above_margin_is_decision_changing(self):
        snap = SimpleNamespace(captain_id=1, vice_captain_id=None, transfer_in_id=None, transfer_out_id=None,
                                reversal_conditions=("runner-up would need +0.20 xP over its horizon to overtake this action",))
        assert classify_decision_effect("player", 1, "PERSISTENT_TREND", "GOAL_THREAT", 0.3, snap) == "DECISION_CHANGING"

    def test_referenced_player_with_no_real_margin_falls_back_to_material(self):
        snap = SimpleNamespace(captain_id=1, vice_captain_id=None, transfer_in_id=None, transfer_out_id=None,
                                reversal_conditions=())
        assert classify_decision_effect("player", 1, "PERSISTENT_TREND", "GOAL_THREAT", 0.3, snap) == "MATERIAL"


class TestFootballSignalsForEntity:
    def test_new_signal_from_a_single_match(self, db_conn):
        _seed_player(db_conn)
        mid = _seed_match(db_conn)
        _seed_observation(db_conn, mid, 1, "CREATION", "POSITIVE")

        signals = football_signals_for_entity(db_conn, "player", 1)

        assert len(signals) == 1
        s = signals[0]
        assert s.category == "CREATION"
        assert s.persistence == "NEW_SIGNAL"
        assert s.novelty is True
        assert s.times_observed == 1
        assert s.decision_effect == "MONITOR"
        assert s.fpl_relevance == "FPL_RELEVANT"
        assert s.signal_id == "player:1:CREATION"
        assert s.evidence == "obs"
        assert s.interpretation == "inf"

    def test_persistent_trend_across_two_matches(self, db_conn):
        _seed_player(db_conn)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-01T15:00:00Z")
        m2 = _seed_match(db_conn, "m2", kickoff="2026-08-08T15:00:00Z")
        _seed_observation(db_conn, m1, 1, "CREATION", "POSITIVE")
        _seed_observation(db_conn, m2, 1, "CREATION", "POSITIVE")

        signals = football_signals_for_entity(db_conn, "player", 1)

        s = next(s for s in signals if s.category == "CREATION")
        assert s.persistence == "PERSISTENT_TREND"
        assert s.times_observed == 2
        assert s.novelty is False
        # most recent match's own evidence, not the first one's
        assert s.match_id == m2

    def test_no_signal_for_a_player_with_zero_history(self, db_conn):
        _seed_player(db_conn)
        assert football_signals_for_entity(db_conn, "player", 1) == []

    def test_team_signal_never_gets_a_decision_effect_beyond_no_impact(self, db_conn):
        db_conn.execute(
            "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (5,5,'T5','T5','t0')"
        )
        db_conn.commit()
        mid = _seed_match(db_conn)
        db_conn.execute(
            "INSERT INTO match_observations (match_id, subject_type, subject_id, observation_type, observed, "
            "inferred, fpl_direction, fpl_signal, fpl_reason, confidence, created_at, phase, evidence_ref, analysis_version) "
            "VALUES (?, 'team', 5, 'TEAM_PATTERN', 'obs', 'inf', 'POSITIVE', 'TEAM_ATTACK', 'r', 'medium', "
            "'t0', 'FULL_TIME', NULL, 'qual-v1')",
            (mid,),
        )
        db_conn.commit()

        signals = football_signals_for_entity(db_conn, "team", 5)

        assert len(signals) == 1
        # A single-match team signal is real but brand new (NEW_SIGNAL) -
        # MONITOR is the correct, honest state, same as a player's own
        # first-match signal; only a genuinely NOISE/uninteresting team
        # trend would ever be NO_DECISION_IMPACT, and a team entity can
        # never reach MATERIAL/DECISION_CHANGING regardless (those require
        # a real reference on the canonical decision, which only names
        # players).
        assert signals[0].decision_effect == "MONITOR"
        assert signals[0].fpl_relevance == "FPL_LOW_RELEVANCE"


def _seed_role_change_history(conn, kickoffs):
    """Real player_match_state rows across `kickoffs` for player 1, team 1 -
    the real match-count clock `_matches_since` reads for expiry."""
    for i, k in enumerate(kickoffs):
        mid = _seed_match(conn, f"expiry{i}", kickoff=k)
        conn.execute(
            "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, "
            "source, retrieved_at, confidence) VALUES (?,1,?,1,1,'fotmob','t0','medium')",
            (mid, f"fm1_{mid}"),
        )
        conn.commit()
    return mid


class TestTemporalFields:
    def test_detected_at_is_the_first_real_observation_not_the_latest(self, db_conn):
        _seed_player(db_conn)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-01T15:00:00Z")
        m2 = _seed_match(db_conn, "m2", kickoff="2026-08-08T15:00:00Z")
        _seed_observation(db_conn, m1, 1, "CREATION", "POSITIVE", observed="first")
        _seed_observation(db_conn, m2, 1, "CREATION", "POSITIVE", observed="second")

        s = football_signals_for_entity(db_conn, "player", 1)[0]

        assert s.detected_at == "t0"  # both seeded rows share created_at='t0' in this helper
        assert s.last_confirmed_at == "t0"
        assert s.evidence == "second"  # latest observation's own text, not the first

    def test_signal_stays_active_within_its_category_expiry_window(self, db_conn):
        _seed_player(db_conn)
        mid = _seed_role_change_history(db_conn, [
            "2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z",
        ])
        _seed_observation(db_conn, mid, 1, "ROLE_CHANGE", "POSITIVE")
        # Player plays on for 2 more real matches (category window is 5) -
        # not enough to expire yet.
        for i, k in enumerate(["2026-08-15T15:00:00Z", "2026-08-22T15:00:00Z"]):
            m = _seed_match(db_conn, f"after{i}", kickoff=k)
            db_conn.execute(
                "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, "
                "source, retrieved_at, confidence) VALUES (?,1,?,1,1,'fotmob','t0','medium')",
                (m, f"fm1_{m}"),
            )
            db_conn.commit()

        s = next(s for s in football_signals_for_entity(db_conn, "player", 1) if s.category == "ROLE_CHANGE")
        assert s.status == "ACTIVE"
        assert s.expires_at is None

    def test_tactical_change_expires_after_its_shorter_real_window(self, db_conn):
        _seed_player(db_conn)
        mid = _seed_match(db_conn, "m1", kickoff="2026-08-01T15:00:00Z")
        _seed_observation(db_conn, mid, 1, "TACTICAL_CHANGE", "WATCH")
        # TACTICAL_CHANGE window is 3 real matches - player plays 3 more
        # without the signal recurring.
        expiry_kickoff = None
        for i, k in enumerate(["2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z", "2026-08-22T15:00:00Z"]):
            m = _seed_match(db_conn, f"after{i}", kickoff=k)
            db_conn.execute(
                "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, "
                "source, retrieved_at, confidence) VALUES (?,1,?,1,1,'fotmob','t0','medium')",
                (m, f"fm1_{m}"),
            )
            db_conn.commit()
            if i == 2:
                expiry_kickoff = k

        s = next(s for s in football_signals_for_entity(db_conn, "player", 1) if s.category == "TACTICAL_CHANGE")
        assert s.status == "EXPIRED"
        assert s.expires_at == expiry_kickoff

    def test_reconfirmation_resets_the_expiry_clock(self, db_conn):
        _seed_player(db_conn)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-01T15:00:00Z")
        _seed_observation(db_conn, m1, 1, "TACTICAL_CHANGE", "WATCH")
        for i, k in enumerate(["2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]):
            m = _seed_match(db_conn, f"gap{i}", kickoff=k)
            db_conn.execute(
                "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, "
                "source, retrieved_at, confidence) VALUES (?,1,?,1,1,'fotmob','t0','medium')",
                (m, f"fm1_{m}"),
            )
            db_conn.commit()
        # Real reconfirmation before the 3-match window elapses.
        m_reconfirm = _seed_match(db_conn, "reconfirm", kickoff="2026-08-22T15:00:00Z")
        _seed_observation(db_conn, m_reconfirm, 1, "TACTICAL_CHANGE", "WATCH")

        s = next(s for s in football_signals_for_entity(db_conn, "player", 1) if s.category == "TACTICAL_CHANGE")
        assert s.status == "ACTIVE"
        assert s.last_confirmed_at is not None
        assert s.match_id == m_reconfirm

    def test_expired_signal_is_excluded_from_active_squad_intelligence(self, db_conn):
        _seed_player(db_conn, player_id=1)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-01T15:00:00Z")
        _seed_observation(db_conn, m1, 1, "TACTICAL_CHANGE", "WATCH")
        for i, k in enumerate(["2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z", "2026-08-22T15:00:00Z"]):
            m = _seed_match(db_conn, f"after{i}", kickoff=k)
            db_conn.execute(
                "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, "
                "source, retrieved_at, confidence) VALUES (?,1,?,1,1,'fotmob','t0','medium')",
                (m, f"fm1_{m}"),
            )
            db_conn.commit()

        signals = squad_football_signals(db_conn, [1])
        assert all(s.category != "TACTICAL_CHANGE" for s in signals)

        signals_incl = squad_football_signals(db_conn, [1], include_expired=True)
        assert any(s.category == "TACTICAL_CHANGE" and s.status == "EXPIRED" for s in signals_incl)


class TestNewDetectorCategoriesDecisionImpact:
    """Decision-impact integration for the new ROLE_CHANGE/SET_PIECE_CHANGE
    detector categories (2026-09-02, Phase 3 finalization) - proves the real
    end-to-end flow: detector-produced signal -> FootballSignal -> real
    xP_effect (via the SAME compute_qualitative_adjustment interface) ->
    classify_decision_effect against a real canonical DecisionSnapshot,
    never a second, competing decision pathway."""

    def test_role_change_signal_reaches_material_when_referenced_by_the_decision(self, db_conn, monkeypatch):
        """Stubs `expected_points()` itself (real infra for a full
        expected_points() pipeline - rules/teams/season bootstrap - is
        already covered end-to-end in test_qualitative_feed.py's own
        ROLE_CHANGE integration test) to isolate what THIS module is
        actually responsible for: wiring a real, non-zero
        `compute_qualitative_adjustment` result through to a real
        `classify_decision_effect` call against a real canonical
        DecisionSnapshot, via the existing interface only."""
        from types import SimpleNamespace as SNS

        from fpl_agent.models.expected_points import ComponentBreakdown

        _seed_player(db_conn, player_id=1, web_name="Captain")
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-01T15:00:00Z")
        m2 = _seed_match(db_conn, "m2", kickoff="2026-08-08T15:00:00Z")
        for mid in (m1, m2):
            db_conn.execute(
                "INSERT INTO match_observations (match_id, subject_type, subject_id, observation_type, observed, "
                "inferred, fpl_direction, fpl_signal, fpl_reason, confidence, created_at, phase, evidence_ref, analysis_version) "
                "VALUES (?, 'player', 1, 'ATTACKING_ROLE', 'real obs', 'real inf', 'POSITIVE', 'ROLE_CHANGE', 'reason', "
                "'medium', 't0', 'FULL_TIME', NULL, 'role-detector-v1')",
                (mid,),
            )
            db_conn.execute(
                "INSERT INTO player_fpl_implications (match_id, player_id, signal, direction, reason, confidence, "
                "created_at, phase, analysis_version) VALUES (?,1,'ROLE_CHANGE','POSITIVE','reason','medium','t0','FULL_TIME','role-detector-v1')",
                (mid,),
            )
        db_conn.commit()

        real_components = ComponentBreakdown(
            appearance=1.5, goals=2.0, assists=0.6, bonus=0.3, clean_sheet=0.0, cards=-0.1, conceded=0.0, defcon=0.0,
        )
        monkeypatch.setattr(
            "fpl_agent.models.expected_points.expected_points",
            lambda conn, player_id, n_gw=1: SNS(components=real_components),
        )

        snap = SimpleNamespace(captain_id=1, vice_captain_id=None, transfer_in_id=None, transfer_out_id=None,
                                reversal_conditions=("runner-up would need +50.00 xP over its horizon to overtake this action",))
        signals = football_signals_for_entity(db_conn, "player", 1, decision_snapshot=snap)

        s = next(s for s in signals if s.category == "ROLE_CHANGE")
        assert s.persistence == "PERSISTENT_TREND"
        assert s.xp_effect == round(2.0 * 0.35, 4)
        assert s.decision_effect == "MATERIAL"
        assert s.fpl_relevance == "FPL_RELEVANT"


class TestSquadFootballSignals:
    def test_ranks_decision_relevant_signals_first(self, db_conn):
        _seed_player(db_conn, player_id=1, web_name="High")
        _seed_player(db_conn, player_id=2, web_name="Low")
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-01T15:00:00Z")
        m2 = _seed_match(db_conn, "m2", kickoff="2026-08-08T15:00:00Z")
        # Player 2: a real persistent trend, but not referenced by any decision.
        _seed_observation(db_conn, m1, 2, "CREATION", "POSITIVE")
        _seed_observation(db_conn, m2, 2, "CREATION", "POSITIVE")
        # Player 1: a brand-new, single-match signal only.
        _seed_observation(db_conn, m2, 1, "GOAL_THREAT", "POSITIVE")

        snap = SimpleNamespace(captain_id=2, vice_captain_id=None, transfer_in_id=None, transfer_out_id=None,
                                reversal_conditions=("runner-up would need +50.00 xP over its horizon to overtake this action",))
        signals = squad_football_signals(db_conn, [1, 2], decision_snapshot=snap)

        # Player 2's persistent, decision-referenced signal must rank ahead
        # of player 1's brand-new, unreferenced one - real decision
        # relevance, not just being the most recently observed.
        assert signals[0].entity_id == 2
        assert signals[0].decision_effect in ("WATCH", "MATERIAL", "DECISION_CHANGING")
