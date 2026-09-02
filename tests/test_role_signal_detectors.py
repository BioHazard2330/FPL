"""Regression tests for the deterministic ROLE_CHANGE/SET_PIECE_CHANGE/
TACTICAL_CHANGE detectors (2026-09-02, Phase 3 finalization)."""
from fpl_agent.models.role_signal_detectors import (
    detect_role_changes,
    detect_setpiece_changes,
    detect_tactical_changes,
    record_role_signal_evidence,
)


def _seed_team(conn, team_id):
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        (team_id, team_id, f"Team{team_id}", f"T{team_id}"),
    )


def _seed_player(conn, player_id=1, web_name="TestPlayer", team_id=1, element_type=3):
    _seed_team(conn, team_id)
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (?, 'Midfielder', 'MID', 'Midfielders', 't0')", (element_type,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,?,'a',0,'t0')", (player_id, player_id, web_name, team_id, element_type),
    )
    conn.commit()


def _seed_match(conn, fotmob_id, home=1, away=2, kickoff="2026-08-01T15:00:00Z", status="FULL_TIME"):
    _seed_team(conn, home)
    _seed_team(conn, away)
    cur = conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, "
        "status, home_score, away_score, source, retrieved_at, confidence) "
        "VALUES (?, 'PL', ?, ?, ?, ?, 1, 0, 'fotmob', 't0', 'high')",
        (fotmob_id, kickoff, home, away, status),
    )
    conn.commit()
    return cur.lastrowid


def _seed_player_match_state(conn, match_id, player_id, team_id=1, shots=0, xg=0.0, key_passes=None, xa=None, minutes=90):
    conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, minutes, "
        "shots, xg, key_passes, xa, source, retrieved_at, confidence) "
        "VALUES (?,?,?,?,1,?,?,?,?,?,'fotmob','t0','medium')",
        (match_id, player_id, f"fm{player_id}_{match_id}", team_id, minutes, shots, xg, key_passes, xa),
    )
    conn.commit()


def _seed_team_match_state(conn, match_id, team_id, formation):
    conn.execute(
        "INSERT INTO team_match_state (match_id, team_id, formation, source, retrieved_at, confidence) "
        "VALUES (?,?,?,'fotmob','t0','medium')",
        (match_id, team_id, formation),
    )
    conn.commit()


def _seed_setpiece_version(conn, player_id, valid_from, penalties_order=None, corners_order=None, direct_fk_order=None, valid_until=None):
    conn.execute(
        "INSERT INTO player_setpiece_history (player_id, penalties_order, corners_order, direct_fk_order, valid_from, valid_until) "
        "VALUES (?,?,?,?,?,?)",
        (player_id, penalties_order, corners_order, direct_fk_order, valid_from, valid_until),
    )
    conn.commit()


class TestRoleChangeDetection:
    def test_no_signal_without_enough_baseline_history(self, db_conn):
        _seed_player(db_conn, 1)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-01T15:00:00Z")
        _seed_player_match_state(db_conn, m1, 1, shots=5, xg=0.9)

        assert detect_role_changes(db_conn, m1) == []

    def test_advanced_role_signal_from_real_xg_spike_vs_own_baseline(self, db_conn):
        _seed_player(db_conn, 1)
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", kickoff=k)
            _seed_player_match_state(db_conn, m, 1, shots=1, xg=0.1)
        m_current = _seed_match(db_conn, "current", kickoff=kickoffs[2])
        _seed_player_match_state(db_conn, m_current, 1, shots=4, xg=0.6)

        obs = detect_role_changes(db_conn, m_current)

        signals = {(o.subject_id, o.fpl_signal, o.fpl_direction) for o in obs}
        assert (1, "ROLE_CHANGE", "POSITIVE") in signals

    def test_no_advance_signal_when_xg_in_line_with_baseline(self, db_conn):
        _seed_player(db_conn, 1)
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", kickoff=k)
            _seed_player_match_state(db_conn, m, 1, shots=2, xg=0.3)
        m_current = _seed_match(db_conn, "current", kickoff=kickoffs[2])
        _seed_player_match_state(db_conn, m_current, 1, shots=2, xg=0.32)

        assert detect_role_changes(db_conn, m_current) == []

    def test_creative_role_fade_signal_from_real_key_pass_collapse(self, db_conn):
        _seed_player(db_conn, 1)
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", kickoff=k)
            _seed_player_match_state(db_conn, m, 1, shots=1, xg=0.05, key_passes=3, xa=0.2)
        m_current = _seed_match(db_conn, "current", kickoff=kickoffs[2])
        _seed_player_match_state(db_conn, m_current, 1, shots=1, xg=0.05, key_passes=0, xa=0.0)

        obs = detect_role_changes(db_conn, m_current)

        signals = {(o.subject_id, o.fpl_signal, o.fpl_direction) for o in obs}
        assert (1, "ROLE_CHANGE", "WATCH") in signals

    def test_role_change_persistence_via_existing_trend_classifier(self, db_conn):
        """Two consecutive real matches with the same detected direction must
        classify PERSISTENT_TREND via the EXISTING `qualitative_trends.py`
        classifier - this module never re-implements persistence itself."""
        from fpl_agent.models.qualitative_trends import signal_trends_for_subject

        _seed_player(db_conn, 1)
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z", "2026-08-22T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", kickoff=k)
            _seed_player_match_state(db_conn, m, 1, shots=1, xg=0.1)
        m1 = _seed_match(db_conn, "m1", kickoff=kickoffs[2])
        _seed_player_match_state(db_conn, m1, 1, shots=4, xg=0.6)
        m2 = _seed_match(db_conn, "m2", kickoff=kickoffs[3])
        _seed_player_match_state(db_conn, m2, 1, shots=5, xg=0.7)

        record_role_signal_evidence(db_conn, m1)
        record_role_signal_evidence(db_conn, m2)

        trends = signal_trends_for_subject(db_conn, "player", 1)
        role_trend = next(t for t in trends if t.signal == "ROLE_CHANGE")
        assert role_trend.label == "PERSISTENT_TREND"
        assert role_trend.sample_size == 2


class TestSetPieceChangeDetection:
    def test_no_signal_with_only_one_real_version(self, db_conn):
        _seed_player(db_conn, 1)
        m1 = _seed_match(db_conn, "m1")
        _seed_player_match_state(db_conn, m1, 1)
        _seed_setpiece_version(db_conn, 1, "2026-08-01", penalties_order=1)

        assert detect_setpiece_changes(db_conn, 1, m1) == []

    def test_real_penalty_order_promotion_detected(self, db_conn):
        _seed_player(db_conn, 1)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-08T15:00:00Z")
        _seed_player_match_state(db_conn, m1, 1)
        _seed_setpiece_version(db_conn, 1, "2026-07-01", penalties_order=2, valid_until="2026-08-01")
        _seed_setpiece_version(db_conn, 1, "2026-08-01", penalties_order=1)

        obs = detect_setpiece_changes(db_conn, 1, m1)

        signals = {(o.subject_id, o.fpl_signal, o.fpl_direction) for o in obs}
        assert (1, "SET_PIECE_CHANGE", "POSITIVE") in signals

    def test_real_corner_order_demotion_is_watch_direction(self, db_conn):
        _seed_player(db_conn, 1)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-08T15:00:00Z")
        _seed_player_match_state(db_conn, m1, 1)
        _seed_setpiece_version(db_conn, 1, "2026-07-01", corners_order=1, valid_until="2026-08-01")
        _seed_setpiece_version(db_conn, 1, "2026-08-01", corners_order=2)

        obs = detect_setpiece_changes(db_conn, 1, m1)
        signals = {(o.subject_id, o.fpl_signal, o.fpl_direction) for o in obs}
        assert (1, "SET_PIECE_CHANGE", "WATCH") in signals

    def test_no_signal_when_player_did_not_play_the_anchor_match(self, db_conn):
        _seed_player(db_conn, 1)
        m1 = _seed_match(db_conn, "m1")
        _seed_setpiece_version(db_conn, 1, "2026-07-01", penalties_order=2, valid_until="2026-08-01")
        _seed_setpiece_version(db_conn, 1, "2026-08-01", penalties_order=1)

        assert detect_setpiece_changes(db_conn, 1, m1) == []

    def test_setpiece_change_only_fires_once_on_its_real_anchor_match(self, db_conn):
        """A real order change is a discrete, one-time structural event -
        the detector must anchor it to the single real match where it first
        took effect, never re-fire it on every later match the player
        plays (a real bug this production-verification pass found live:
        76 rows from a handful of real changes across 20 real matches)."""
        _seed_player(db_conn, 1)
        _seed_setpiece_version(db_conn, 1, "2026-07-01", penalties_order=2, valid_until="2026-08-01")
        _seed_setpiece_version(db_conn, 1, "2026-08-01", penalties_order=1)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-08T15:00:00Z")
        _seed_player_match_state(db_conn, m1, 1)
        m2 = _seed_match(db_conn, "m2", kickoff="2026-08-15T15:00:00Z")
        _seed_player_match_state(db_conn, m2, 1)

        assert detect_setpiece_changes(db_conn, 1, m1) != []
        assert detect_setpiece_changes(db_conn, 1, m2) == []

    def test_setpiece_change_persistence_via_existing_trend_classifier_across_sources(self, db_conn):
        """SET_PIECE_CHANGE's real persistence path: the deterministic
        detector's own single anchor-match observation, PLUS a real,
        independent reconfirmation from a different real source (the
        `match-intelligence-analysis` skill, a later real match) for the
        SAME signal/direction - the SAME, unmodified `qualitative_trends.py`
        classifier turns that real cross-source pair into PERSISTENT_TREND,
        never a second, bespoke persistence system for this category."""
        from fpl_agent.models.qualitative_trends import signal_trends_for_subject

        _seed_player(db_conn, 1)
        _seed_setpiece_version(db_conn, 1, "2026-07-01", penalties_order=2, valid_until="2026-08-01")
        _seed_setpiece_version(db_conn, 1, "2026-08-01", penalties_order=1)
        m1 = _seed_match(db_conn, "m1", kickoff="2026-08-08T15:00:00Z")
        _seed_player_match_state(db_conn, m1, 1)
        record_role_signal_evidence(db_conn, m1)

        m2 = _seed_match(db_conn, "m2", kickoff="2026-08-15T15:00:00Z")
        db_conn.execute(
            "INSERT INTO match_observations (match_id, subject_type, subject_id, observation_type, observed, "
            "inferred, fpl_direction, fpl_signal, fpl_reason, confidence, created_at, phase, evidence_ref, analysis_version) "
            "VALUES (?, 'player', 1, 'SET_PIECE', 'confirmed still on penalties', 'stays primary taker', 'POSITIVE', "
            "'SET_PIECE_CHANGE', 'reconfirmed', 'high', 't0', 'FULL_TIME', NULL, 'qual-v1')",
            (m2,),
        )
        db_conn.commit()

        trends = signal_trends_for_subject(db_conn, "player", 1)
        sp_trend = next(t for t in trends if t.signal == "SET_PIECE_CHANGE")
        assert sp_trend.label == "PERSISTENT_TREND"
        assert sp_trend.sample_size == 2


class TestTacticalChangeDetection:
    def test_no_signal_without_enough_baseline_matches(self, db_conn):
        m1 = _seed_match(db_conn, "m1", home=1, away=2, kickoff="2026-08-01T15:00:00Z")
        _seed_team_match_state(db_conn, m1, 1, "4-3-3")

        assert detect_tactical_changes(db_conn, 1, m1) == []

    def test_real_formation_departure_from_baseline_detected(self, db_conn):
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", home=1, away=2, kickoff=k)
            _seed_team_match_state(db_conn, m, 1, "4-3-3")
        m_current = _seed_match(db_conn, "current", home=1, away=2, kickoff=kickoffs[2])
        _seed_team_match_state(db_conn, m_current, 1, "3-4-3")

        obs = detect_tactical_changes(db_conn, 1, m_current)
        signals = {(o.subject_id, o.fpl_signal) for o in obs}
        assert (1, "TACTICAL_CHANGE") in signals

    def test_no_signal_when_formation_matches_baseline(self, db_conn):
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", home=1, away=2, kickoff=k)
            _seed_team_match_state(db_conn, m, 1, "4-3-3")
        m_current = _seed_match(db_conn, "current", home=1, away=2, kickoff=kickoffs[2])
        _seed_team_match_state(db_conn, m_current, 1, "4-3-3")

        assert detect_tactical_changes(db_conn, 1, m_current) == []

    def test_tactical_change_links_to_player_level_role_signal(self, db_conn):
        """PART 3: a tactical change must produce a linked PLAYER-level
        consequence when one is real, not just a team-level fact."""
        _seed_player(db_conn, 1, team_id=1)
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", home=1, away=2, kickoff=k)
            _seed_team_match_state(db_conn, m, 1, "4-3-3")
            _seed_player_match_state(db_conn, m, 1, team_id=1, shots=1, xg=0.1)
        m_current = _seed_match(db_conn, "current", home=1, away=2, kickoff=kickoffs[2])
        _seed_team_match_state(db_conn, m_current, 1, "3-4-3")
        _seed_player_match_state(db_conn, m_current, 1, team_id=1, shots=4, xg=0.6)

        written = record_role_signal_evidence(db_conn, m_current)
        assert written > 0

        rows = db_conn.execute(
            "SELECT subject_type, subject_id, fpl_signal, fpl_reason FROM match_observations WHERE match_id=?",
            (m_current,),
        ).fetchall()
        assert any(r["subject_type"] == "team" and r["fpl_signal"] == "TACTICAL_CHANGE" for r in rows)
        linked_player_rows = [r for r in rows if r["subject_type"] == "player" and r["fpl_signal"] == "ROLE_CHANGE"]
        assert linked_player_rows
        assert "TACTICAL_CHANGE" in linked_player_rows[0]["fpl_reason"]

    def test_tactical_change_persistence_via_existing_trend_classifier(self, db_conn):
        from fpl_agent.models.qualitative_trends import signal_trends_for_subject

        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z", "2026-08-22T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", home=1, away=2, kickoff=k)
            _seed_team_match_state(db_conn, m, 1, "4-3-3")
        m1 = _seed_match(db_conn, "m1", home=1, away=2, kickoff=kickoffs[2])
        _seed_team_match_state(db_conn, m1, 1, "3-4-3")
        m2 = _seed_match(db_conn, "m2", home=1, away=2, kickoff=kickoffs[3])
        _seed_team_match_state(db_conn, m2, 1, "3-4-3")

        record_role_signal_evidence(db_conn, m1)
        record_role_signal_evidence(db_conn, m2)

        trends = signal_trends_for_subject(db_conn, "team", 1)
        tac_trend = next(t for t in trends if t.signal == "TACTICAL_CHANGE")
        assert tac_trend.label == "PERSISTENT_TREND"
        assert tac_trend.sample_size == 2


class TestDeduplication:
    def test_backfill_plus_qualitative_rerun_never_duplicates(self, db_conn):
        """PART 7: real order this bug actually manifested in -
        `.claude/skills/match-intelligence-analysis` analyzes the match FIRST
        (its own `qual-v1` row), and a LATER automatic backfill run of this
        deterministic detector must never add a redundant second row for the
        same (match, subject, signal) - dedup must check across ANY
        analysis_version, never scoped to this detector's own tag."""
        _seed_player(db_conn, 1)
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", kickoff=k)
            _seed_player_match_state(db_conn, m, 1, shots=1, xg=0.1)
        m_current = _seed_match(db_conn, "current", kickoff=kickoffs[2])
        _seed_player_match_state(db_conn, m_current, 1, shots=4, xg=0.6)

        # The qualitative skill already analyzed this match and wrote its
        # own row for the identical real evidence, tagged 'qual-v1'.
        db_conn.execute(
            "INSERT INTO match_observations (match_id, subject_type, subject_id, observation_type, observed, "
            "inferred, fpl_direction, fpl_signal, fpl_reason, confidence, created_at, phase, evidence_ref, analysis_version) "
            "VALUES (?, 'player', 1, 'ATTACKING_ROLE', 'qual obs', 'qual inf', 'POSITIVE', 'ROLE_CHANGE', 'qual reason', "
            "'high', 't0', 'FULL_TIME', NULL, 'qual-v1')",
            (m_current,),
        )
        db_conn.commit()

        # A later, normal automatic backfill run of this deterministic
        # detector must see the skill's row as "already covered" and add
        # nothing for the same real evidence.
        backfill = record_role_signal_evidence(db_conn, m_current)
        assert backfill == 0

        count = db_conn.execute(
            "SELECT COUNT(*) AS n FROM match_observations WHERE match_id=? AND subject_type='player' AND subject_id=1 AND fpl_signal='ROLE_CHANGE'",
            (m_current,),
        ).fetchone()["n"]
        assert count == 1

    def test_repeated_run_of_the_same_match_never_duplicates(self, db_conn):
        _seed_player(db_conn, 1)
        kickoffs = ["2026-08-01T15:00:00Z", "2026-08-08T15:00:00Z", "2026-08-15T15:00:00Z"]
        for i, k in enumerate(kickoffs[:2]):
            m = _seed_match(db_conn, f"base{i}", kickoff=k)
            _seed_player_match_state(db_conn, m, 1, shots=1, xg=0.1)
        m_current = _seed_match(db_conn, "current", kickoff=kickoffs[2])
        _seed_player_match_state(db_conn, m_current, 1, shots=4, xg=0.6)

        first = record_role_signal_evidence(db_conn, m_current)
        second = record_role_signal_evidence(db_conn, m_current)

        assert first > 0
        assert second == 0
