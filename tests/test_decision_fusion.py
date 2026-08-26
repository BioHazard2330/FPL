import fpl_agent.models.decision_fusion as decision_fusion_mod
from fpl_agent.models.decision_fusion import compare_captain_views, compare_transfer_views
from fpl_agent.optimization import captaincy as captaincy_mod
from fpl_agent.optimization.transfers import TransferCandidate

from test_optimization_captaincy import _EP, _patch, _seed


def _candidate(player_out_id=3, player_in_id=99, net_ev_3gw=2.0):
    return TransferCandidate(
        player_out_id=player_out_id, player_out_name="Punt", player_in_id=player_in_id, player_in_name="Replacement",
        price_delta_tenths=0, ev_1gw=1.0, ev_3gw=net_ev_3gw, ev_5gw=net_ev_3gw,
        net_ev_1gw=net_ev_3gw, net_ev_3gw=net_ev_3gw, net_ev_5gw=net_ev_3gw, uses_hit=False,
    )


def _seed_implication(conn, player_id: int, match_id: int, signal: str, direction: str, reason: str, created_at: str) -> None:
    conn.execute(
        "INSERT INTO match_intelligence "
        "(id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "source, retrieved_at, confidence) VALUES (?,?,?,?,1,2,'FULL_TIME','fotmob','t0','high') "
        "ON CONFLICT(fotmob_match_id) DO NOTHING",
        (match_id, f"fm{match_id}", "Premier League", created_at),
    )
    conn.execute(
        "INSERT INTO player_fpl_implications (match_id, player_id, signal, direction, reason, confidence, "
        "created_at, phase) VALUES (?,?,?,?,?,?,?,'FULL_TIME')",
        (match_id, player_id, signal, direction, reason, "medium", created_at),
    )
    conn.execute(
        "INSERT INTO match_observations (match_id, subject_type, subject_id, observation_type, observed, "
        "fpl_direction, fpl_signal, confidence, created_at, phase) "
        "VALUES (?,?,?,?,?,?,?,?,?,'FULL_TIME')",
        (match_id, "player", player_id, "GOAL_THREAT", "real observed text", direction, signal, "medium", created_at),
    )
    conn.commit()


def test_no_disagreement_means_model_wins(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    result = compare_captain_views(db_conn, [1, 2, 3])

    assert result.model_pick.player_id == 1
    assert result.qualitative_pick_id is None
    assert result.user_pick_id is None
    assert result.verdict == "MODEL_WINS"


def test_a_new_signal_alone_does_not_override_the_model(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)
    _seed_implication(db_conn, player_id=2, match_id=1, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored a real goal", created_at="2026-08-08T15:00:00Z")

    result = compare_captain_views(db_conn, [1, 2, 3])

    assert result.qualitative_pick_id == 2
    assert result.verdict == "MODEL_WINS"
    assert "NEW_SIGNAL" in result.explanation or "not yet" in result.explanation


def test_a_real_persistent_trend_wins_over_the_model(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)
    _seed_implication(db_conn, player_id=2, match_id=1, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored", created_at="2026-08-01T15:00:00Z")
    _seed_implication(db_conn, player_id=2, match_id=2, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored again", created_at="2026-08-08T15:00:00Z")

    result = compare_captain_views(db_conn, [1, 2, 3])

    assert result.qualitative_pick_id == 2
    assert result.verdict == "QUALITATIVE_WINS"


def test_a_real_user_observation_is_never_auto_resolved(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)
    db_conn.execute(
        "INSERT INTO user_observations (subject_type, subject_id, sentiment, note, created_at) "
        "VALUES ('player', 3, 'positive', 'I trust Punt this week', 't0')"
    )
    db_conn.commit()

    result = compare_captain_views(db_conn, [1, 2, 3])

    assert result.user_pick_id == 3
    assert result.verdict == "UNDECIDED"


def test_insufficient_evidence_for_an_empty_squad(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    result = compare_captain_views(db_conn, [])

    assert result.model_pick is None
    assert result.verdict == "INSUFFICIENT_EVIDENCE"


def _patch_transfer(monkeypatch, candidate):
    monkeypatch.setattr(
        decision_fusion_mod, "best_transfer_for_player",
        lambda conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw, top_n: (
            [candidate] if player_out_id == candidate.player_out_id else []
        ),
    )


def test_transfer_no_disagreement_means_model_wins(db_conn, monkeypatch):
    _seed(db_conn)
    _patch_transfer(monkeypatch, _candidate())

    result = compare_transfer_views(db_conn, [1, 2, 3], bank_tenths=0)

    assert result.model_candidate.player_out_id == 3
    assert result.qualitative_direction is None
    assert result.verdict == "MODEL_WINS"


def test_transfer_new_signal_alone_does_not_override_the_model(db_conn, monkeypatch):
    _seed(db_conn)
    _patch_transfer(monkeypatch, _candidate())
    _seed_implication(db_conn, player_id=3, match_id=1, signal="ROLE", direction="POSITIVE",
                       reason="started and played well", created_at="2026-08-22T15:00:00Z")

    result = compare_transfer_views(db_conn, [1, 2, 3], bank_tenths=0)

    assert result.qualitative_direction == "POSITIVE"
    assert result.verdict == "MODEL_WINS"
    assert "NEW_SIGNAL" in result.explanation or "not yet" in result.explanation


def test_transfer_persistent_trend_earns_the_override(db_conn, monkeypatch):
    _seed(db_conn)
    _patch_transfer(monkeypatch, _candidate())
    _seed_implication(db_conn, player_id=3, match_id=1, signal="ROLE", direction="POSITIVE",
                       reason="started and played well", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=3, match_id=2, signal="ROLE", direction="POSITIVE",
                       reason="started again and scored", created_at="2026-08-22T15:00:00Z")

    result = compare_transfer_views(db_conn, [1, 2, 3], bank_tenths=0)

    assert result.verdict == "QUALITATIVE_WINS"


def test_transfer_user_bullish_view_is_never_auto_resolved(db_conn, monkeypatch):
    _seed(db_conn)
    _patch_transfer(monkeypatch, _candidate())
    db_conn.execute(
        "INSERT INTO user_observations (subject_type, subject_id, sentiment, note, created_at) "
        "VALUES ('player', 3, 'positive', 'bullish on Punt', 't0')"
    )
    db_conn.commit()

    result = compare_transfer_views(db_conn, [1, 2, 3], bank_tenths=0)

    assert result.user_sentiment == "positive"
    assert result.verdict == "UNDECIDED"


def test_transfer_insufficient_evidence_without_a_known_bank(db_conn, monkeypatch):
    _seed(db_conn)
    _patch_transfer(monkeypatch, _candidate())

    result = compare_transfer_views(db_conn, [1, 2, 3], bank_tenths=None)

    assert result.model_candidate is None
    assert result.verdict == "INSUFFICIENT_EVIDENCE"


def test_transfer_insufficient_evidence_when_no_real_candidate_exists(db_conn, monkeypatch):
    _seed(db_conn)
    monkeypatch.setattr(
        decision_fusion_mod, "best_transfer_for_player",
        lambda conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw, top_n: [],
    )

    result = compare_transfer_views(db_conn, [1, 2, 3], bank_tenths=0)

    assert result.model_candidate is None
    assert result.verdict == "INSUFFICIENT_EVIDENCE"
