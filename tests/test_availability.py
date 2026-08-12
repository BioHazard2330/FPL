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
