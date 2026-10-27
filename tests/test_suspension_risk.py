from fpl_agent.models.suspension_risk import ban_schedule


def _fixtures(played: int, total: int = 38):
    return [(100 + n, n, n <= played) for n in range(1, total + 1)]


def test_a_certain_booking_on_four_yellows_bans_him_for_the_following_match_only():
    out = ban_schedule(4, _fixtures(played=8), p_booked=1.0)
    assert out[109] == 0.0
    assert out[110] == 1.0
    assert out[111] == 0.0


def test_the_fifth_yellow_after_the_clubs_nineteenth_match_costs_nothing():
    out = ban_schedule(4, _fixtures(played=19), p_booked=0.5)
    # Six more bookings are needed for the next threshold (ten), so nothing can be served before match 26.
    assert max(out[f] for f in range(120, 126)) == 0.0
    assert out[127] > 0


def test_the_tenth_yellow_inside_thirty_two_matches_is_a_two_match_ban():
    out = ban_schedule(9, _fixtures(played=25), p_booked=1.0)
    assert (out[126], out[127], out[128], out[129]) == (0.0, 1.0, 1.0, 0.0)


def test_ban_probability_builds_up_over_the_window_and_never_exceeds_one():
    out = ban_schedule(3, _fixtures(played=8), p_booked=0.25)
    values = [out[f] for f in range(109, 120)]
    assert values[0] == 0.0 and values[1] == 0.0
    assert 0 < values[2] < 0.1
    assert all(0 <= v <= 1 for v in values)
    assert sum(values) < 1.0


def test_never_booked_never_banned():
    assert max(ban_schedule(4, _fixtures(played=8), p_booked=0.0).values()) == 0.0


def test_a_cup_tie_before_the_next_league_match_serves_the_ban():
    fixtures = _fixtures(played=8)
    out = ban_schedule(4, fixtures, p_booked=1.0, cups_before={110: 1})
    assert out[110] == 0.0
    assert out[111] == 0.0
