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


def _paths(event, action, chip_played=None):
    return [{"steps": [{"event": event, "action": action, "chip_played": chip_played}]}]


def test_none_when_no_real_complete_decision_exists(db_conn):
    assert stable_current_recommendation(db_conn) is None


def test_a_real_gameweek_advance_flips_immediately_with_no_hysteresis_bar(db_conn):
    """Real production bug (2026-09-12, direct user report: the Plan screen
    kept showing "PLAY FREE HIT" for GW4 as the stable recommendation even
    after the GW4 deadline passed and Free Hit had genuinely been played -
    the newer decision correctly starting fresh at GW5 never cleared the
    EV-advantage/persistence bar because that bar compares labels as if
    they were competing answers to the SAME question. "PLAY FREEHIT" (GW4)
    and "PLAY WILDCARD" (GW5) aren't competing at all - GW4's decision
    point is simply closed, so this must flip immediately regardless of EV
    advantage or confidence."""
    _log_plan(
        db_conn, current_recommendation=_rec("PLAY FREEHIT", 486.3, evidence_confidence="MEDIUM"),
        paths=_paths(4, "PLAY FREEHIT", "freehit"),
    )
    # A small, sub-threshold, low-confidence "advantage" - would normally be
    # held back by both the EV-advantage and confidence bars below.
    _log_plan(
        db_conn, current_recommendation=_rec("PLAY WILDCARD", 487.0, evidence_confidence="LOW"),
        paths=_paths(5, "PLAY WILDCARD", "wildcard"),
    )

    result = stable_current_recommendation(db_conn)

    assert result.detail["current_recommendation"]["label"] == "PLAY WILDCARD"


def test_hysteresis_still_applies_within_the_same_anchor_gameweek(db_conn):
    """The anchor-advance escape hatch must not swallow the real, original
    noise-suppression behavior when both decisions are still contesting
    the SAME gameweek - only a genuine advance to a later anchor event
    skips the bar."""
    _log_plan(
        db_conn, current_recommendation=_rec("ROLL", 100.0),
        paths=_paths(4, "ROLL"),
    )
    _log_plan(
        db_conn, current_recommendation=_rec("PLAY WILDCARD", 102.0),  # +2.0, below the real 5.0 bar
        paths=_paths(4, "PLAY WILDCARD", "wildcard"),
    )

    result = stable_current_recommendation(db_conn)

    assert result.detail["current_recommendation"]["label"] == "ROLL"
