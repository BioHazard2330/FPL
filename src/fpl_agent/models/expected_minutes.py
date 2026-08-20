import sqlite3
from dataclasses import dataclass

from fpl_agent.models.availability import classify
from fpl_agent.models.rules import current_season

# A season gap of 2+ (i.e. missing at least one full season between the most
# recent player_season_history row and now) means that row is NOT genuinely
# "last season" - treated as stale rather than a fresh, trustworthy prior.
_STALE_SEASON_GAP_THRESHOLD = 2


def _season_start_year(season_str: str | None) -> int | None:
    """Accepts player_season_history's "YYYY/YY" or rules.season's "YYYY-YY" -
    both start with a 4-digit year before the separator."""
    if not season_str:
        return None
    for sep in ("/", "-"):
        if sep in season_str:
            head = season_str.split(sep, 1)[0]
            if head.isdigit():
                return int(head)
    return None


_AVAILABILITY_DAMPING = {
    "FIT": 1.0,
    "FIT BUT MONITORED": 0.85,
    "DOUBTFUL": 0.5,
    "LIKELY UNAVAILABLE": 0.15,
    "CONFIRMED UNAVAILABLE": 0.0,
}

# Approximate round count used to convert a cross-league total-minutes figure
# into a per-GW rate (models/cross_league_source.py's CROSS_LEAGUE_CODES: La
# Liga/Serie A play 38 rounds, Bundesliga/Ligue 1 play 34, RFPL ~30 - 38 is a
# disclosed, deliberately simple approximation, not a per-league lookup table
# (getting a specific league's exact round count wrong would silently bias
# one nationality's signings without being any more honest about it - a
# single documented constant plus the discount below is the more defensible
# trade-off for a LOW-confidence estimate that already carries real
# uncertainty from the transfer itself).
_CROSS_LEAGUE_ROUNDS_APPROX = 38
# A real transfer doesn't guarantee immediate first-team minutes at the new
# club (squad depth, manager trust, an adaptation period) - this is a
# disclosed, uncalibrated heuristic, same honesty posture as
# squad_churn.py's _CHURN_SHRINK_CAP and promoted_team_calibration.py's
# additive shift. Revisit once real in-season minutes data exists for any
# of these signings to fit an actual rate against.
_NEW_SIGNING_MINUTES_DISCOUNT = 0.6

# Real gap found 2026-08-20: a user-provided screenshot of a competitor FPL
# prediction tool showed a real, non-trivial minutes estimate (82') for a
# player this project had zero statistical signal on (Tzolis) - their own UI
# has a "Default minutes" toggle, confirming this is a disclosed editorial
# ASSUMPTION for new-to-PL signings with no track record, not a hidden
# statistical trick this project is missing. This project had no equivalent
# fallback at all for that class of player - real managers voting with real
# squad selections (team news, transfer fee size, preseason form this
# project has no structured source for) is a real, freely-available signal
# this project already has in player_ownership_history and had never used
# for expected_minutes specifically. 10.0 matches traps.py's existing
# MIN_OWNERSHIP_PERCENT convention (a real, non-arbitrary "meaningful
# ownership" bar already established elsewhere in this codebase) - deliberately
# more conservative than the competitor's 82' default, since a broad
# ownership signal is weaker evidence than whatever informed theirs.
_MARKET_CONVICTION_OWNERSHIP_THRESHOLD = 10.0
_MARKET_CONVICTION_DEFAULT_MINUTES = 60.0
# Only overrides a base drawn from one of these already-weak-evidence
# branches - never a genuinely low but well-evidenced estimate (e.g. Havertz,
# a real, current-squad backup with real recent minutes data showing it -
# a low number there is a real signal, not a data gap, and must not be
# inflated just because of unrelated ownership noise).
_WEAK_EVIDENCE_BASES = {"no_data_available", "stale_prior_season", "cross_league_prior_new_signing"}


@dataclass(frozen=True)
class ExpectedMinutes:
    player_id: int
    expected_minutes: float
    confidence: str  # LOW / MEDIUM / HIGH
    basis: str
    classification: str


def expected_minutes(conn: sqlite3.Connection, player_id: int) -> ExpectedMinutes:
    player = conn.execute("SELECT status FROM players WHERE id=?", (player_id,)).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")

    snapshot = conn.execute(
        "SELECT minutes, chance_of_playing_this_round, chance_of_playing_next_round "
        "FROM player_stats_snapshot WHERE player_id=? ORDER BY retrieved_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    chance_this = snapshot["chance_of_playing_this_round"] if snapshot else None
    chance_next = snapshot["chance_of_playing_next_round"] if snapshot else None
    classification = classify(player["status"], chance_this, chance_next)

    finished_events = conn.execute("SELECT COUNT(*) AS n FROM events WHERE finished=1").fetchone()["n"]
    current_minutes = snapshot["minutes"] if snapshot else None

    current_per_gw = None
    if finished_events > 0 and current_minutes is not None:
        current_per_gw = min(current_minutes / finished_events, 90)

    prior_row = conn.execute(
        "SELECT minutes, season_name FROM player_season_history WHERE player_id=? ORDER BY season_name DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    prior_per_gw = min(prior_row["minutes"] / 38, 90) if prior_row and prior_row["minutes"] is not None else None

    prior_is_stale = False
    if prior_row is not None:
        prior_year = _season_start_year(prior_row["season_name"])
        this_year = _season_start_year(current_season(conn))
        if prior_year is not None and this_year is not None and this_year - prior_year >= _STALE_SEASON_GAP_THRESHOLD:
            prior_is_stale = True

    if current_per_gw is not None and prior_per_gw is not None:
        weight_current = min(finished_events / 10, 0.8)
        base = weight_current * current_per_gw + (1 - weight_current) * prior_per_gw
        confidence = "MEDIUM" if finished_events < 10 else "HIGH"
        basis = "blended_current_and_prior_season"
    elif current_per_gw is not None:
        base = current_per_gw
        confidence = "MEDIUM" if finished_events < 5 else "HIGH"
        basis = "current_season_only"
    elif prior_per_gw is not None and not prior_is_stale:
        base = prior_per_gw
        confidence = "LOW"
        basis = "last_season_prior_no_current_data"
    elif prior_per_gw is not None and prior_is_stale:
        # Real gap found 2026-08-20: `ORDER BY season_name DESC LIMIT 1` always
        # grabs the single most recent AVAILABLE row, regardless of how old it
        # actually is - silently treating a several-seasons-old cameo the same
        # as a genuine "last season" figure. Caught by hand-checking a real,
        # moderately-owned (~20%) player (Tzolis) whose only history_past row -
        # confirmed live against the real FPL API, not just this project's DB -
        # was from 2021/22: produced an absurd ~9min expected-minutes figure for
        # a player real managers clearly aren't treating as a bit-part squad
        # member. Same discount/confidence posture as a genuinely-new-to-the-
        # league cross-league signing below - a multi-season gap carries the
        # same "no trustworthy recent read on this player's real role"
        # uncertainty, whatever caused the gap (loan abroad in an untracked
        # league, injury absence, reserve-team years).
        base = prior_per_gw * _NEW_SIGNING_MINUTES_DISCOUNT
        confidence = "LOW"
        basis = "stale_prior_season"
    else:
        cross_league_row = conn.execute(
            "SELECT minutes FROM player_cross_league_prior WHERE player_id=?", (player_id,)
        ).fetchone()
        if cross_league_row is not None and cross_league_row["minutes"]:
            cross_league_per_gw = min(cross_league_row["minutes"] / _CROSS_LEAGUE_ROUNDS_APPROX, 90)
            base = cross_league_per_gw * _NEW_SIGNING_MINUTES_DISCOUNT
            confidence = "LOW"
            basis = "cross_league_prior_new_signing"
        else:
            base = 0.0
            confidence = "LOW"
            basis = "no_data_available"

    if basis in _WEAK_EVIDENCE_BASES and base < _MARKET_CONVICTION_DEFAULT_MINUTES:
        ownership_row = conn.execute(
            "SELECT selected_by_percent FROM player_ownership_history WHERE player_id=? AND valid_until IS NULL",
            (player_id,),
        ).fetchone()
        real_ownership = ownership_row["selected_by_percent"] if ownership_row and ownership_row["selected_by_percent"] is not None else 0.0
        if real_ownership >= _MARKET_CONVICTION_OWNERSHIP_THRESHOLD:
            base = _MARKET_CONVICTION_DEFAULT_MINUTES
            basis = "market_conviction_override"

    damped = min(base * _AVAILABILITY_DAMPING[classification], 90.0)

    return ExpectedMinutes(
        player_id=player_id,
        expected_minutes=round(damped, 1),
        confidence=confidence,
        basis=basis,
        classification=classification,
    )
