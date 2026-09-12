from fpl_agent.models.availability import classify


def test_fit():
    assert classify("a", 100, 100) == "FIT"


def test_fit_but_monitored():
    assert classify("a", 75, 100) == "FIT BUT MONITORED"


def test_doubtful():
    assert classify("d", 75, None) == "DOUBTFUL"


def test_likely_unavailable():
    assert classify("d", 25, None) == "LIKELY UNAVAILABLE"
    assert classify("i", 50, None) == "LIKELY UNAVAILABLE"


def test_confirmed_unavailable_injured_no_chance():
    assert classify("i", None, None) == "CONFIRMED UNAVAILABLE"
    assert classify("i", 0, None) == "CONFIRMED UNAVAILABLE"


def test_confirmed_unavailable_suspended_or_unavailable():
    assert classify("s", None, None) == "CONFIRMED UNAVAILABLE"
    assert classify("u", None, None) == "CONFIRMED UNAVAILABLE"
    assert classify("n", None, None) == "CONFIRMED UNAVAILABLE"


def test_next_round_chance_takes_priority_over_this_round():
    """Real fix (2026-09-13, direct user complaint: a wildcard squad
    started a real concussion doubt). Every real caller of classify() is
    making a decision about an UPCOMING gameweek - a player cleared for the
    round that just locked (chance_this=100) but doubtful for the next one
    (chance_next=50, a fresh news update) must classify off the doubt that
    actually matters, not the now-irrelevant clearance."""
    assert classify("d", 100, 50) == "LIKELY UNAVAILABLE"
    assert classify("i", 100, 25) == "LIKELY UNAVAILABLE"


def test_this_round_chance_is_the_honest_fallback_when_next_is_unknown():
    """The pre-existing common case (no next-round estimate published yet)
    must still work exactly as before - this is a fallback, not a removal."""
    assert classify("d", 75, None) == "DOUBTFUL"
    assert classify("d", 25, None) == "LIKELY UNAVAILABLE"
