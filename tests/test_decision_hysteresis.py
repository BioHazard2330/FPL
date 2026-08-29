"""Real tests for decision hysteresis (2026-08-29, "live architecture
rebuild" pass, milestone 4, spec section 11: "do not alternate
recommendations every time the model moves by 0.05 xP"). Reuses
`test_strategic_planner.py`'s own `_log_plan` fixture helper - same real
`log_decision(..., "strategic_plan", ...)` shape every real consumer of
"the current strategic plan" already reads."""
from fpl_agent.models.decision_hysteresis import stable_current_recommendation
from test_strategic_planner import _log_plan


def _rec(label, path_total, verdict="ACT", evidence_confidence="HIGH"):
    return {"label": label, "verdict": verdict, "path_total": path_total, "evidence_confidence": evidence_confidence}


def test_first_ever_decision_is_trivially_stable(db_conn):
    _log_plan(db_conn, current_recommendation=_rec("ROLL", 100.0))
    result = stable_current_recommendation(db_conn)
    assert result.detail["current_recommendation"]["label"] == "ROLL"


def test_repeated_same_label_stays_stable(db_conn):
    _log_plan(db_conn, current_recommendation=_rec("ROLL", 100.0))
    _log_plan(db_conn, current_recommendation=_rec("ROLL", 100.3))  # real noise-level drift, same real winner
    result = stable_current_recommendation(db_conn)
    assert result.detail["current_recommendation"]["label"] == "ROLL"


def test_small_ev_advantage_alone_does_not_flip_the_stable_recommendation(db_conn):
    """The real spec-11 case: a tiny model-noise swing must not replace the
    currently-stable answer with a different one after just one update."""
    _log_plan(db_conn, current_recommendation=_rec("ROLL", 100.0))
    _log_plan(db_conn, current_recommendation=_rec("PLAY WILDCARD", 102.0))  # +2.0, below the real 5.0 bar, first occurrence
    result = stable_current_recommendation(db_conn)
    assert result.detail["current_recommendation"]["label"] == "ROLL"


def test_large_ev_advantage_with_good_confidence_flips_immediately(db_conn):
    _log_plan(db_conn, current_recommendation=_rec("ROLL", 100.0))
    _log_plan(db_conn, current_recommendation=_rec("PLAY WILDCARD", 110.0, evidence_confidence="HIGH"))
    result = stable_current_recommendation(db_conn)
    assert result.detail["current_recommendation"]["label"] == "PLAY WILDCARD"


def test_large_ev_advantage_with_low_confidence_does_not_flip_immediately(db_conn):
    """Real spec-11 "confidence threshold" criterion - a big EV number
    behind a LOW-evidence transfer must not override the stable answer on
    its own, only real persistence should."""
    _log_plan(db_conn, current_recommendation=_rec("ROLL", 100.0))
    _log_plan(db_conn, current_recommendation=_rec("PLAY WILDCARD", 110.0, evidence_confidence="LOW"))
    result = stable_current_recommendation(db_conn)
    assert result.detail["current_recommendation"]["label"] == "ROLL"


def test_persistence_across_updates_eventually_flips_a_small_ev_advantage(db_conn):
    """Real spec-11 "persistence across multiple updates" criterion - a
    small (sub-threshold) EV advantage that keeps showing up across
    several real consecutive decisions is trusted even without a single
    big jump."""
    _log_plan(db_conn, current_recommendation=_rec("ROLL", 100.0))
    _log_plan(db_conn, current_recommendation=_rec("PLAY WILDCARD", 102.0))  # 1st occurrence, blocked
    _log_plan(db_conn, current_recommendation=_rec("PLAY WILDCARD", 102.5))  # 2nd consecutive occurrence - now trusted
    result = stable_current_recommendation(db_conn)
    assert result.detail["current_recommendation"]["label"] == "PLAY WILDCARD"


def test_a_diagnostic_run_sandwiched_in_is_skipped_not_counted(db_conn):
    """`strategic_plan_decisions_with_recommendation` already filters out
    incomplete (`--no-current-action`) runs - hysteresis must see the same
    real, complete-only sequence, never let a diagnostic run break the
    persistence count."""
    _log_plan(db_conn, current_recommendation=_rec("ROLL", 100.0))
    _log_plan(db_conn, current_recommendation=_rec("PLAY WILDCARD", 102.0))
    _log_plan(db_conn, current_recommendation=None)  # diagnostic run - must not count as "not PLAY WILDCARD"
    _log_plan(db_conn, current_recommendation=_rec("PLAY WILDCARD", 102.5))
    result = stable_current_recommendation(db_conn)
    assert result.detail["current_recommendation"]["label"] == "PLAY WILDCARD"


def test_none_when_no_real_complete_decision_exists(db_conn):
    assert stable_current_recommendation(db_conn) is None
