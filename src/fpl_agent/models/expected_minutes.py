import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.lineup_probability_source import get_start_percent
from fpl_agent.models.availability import classify
from fpl_agent.models.rules import current_season
from fpl_agent.models.team_news_risk import rotation_risk_snippet

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
# Real gap found 2026-08-21: a user-built real GW1 squad included Jacquet (a
# genuine Liverpool signing, real name-checked live), and this project gave him
# expected_minutes=0.0 (basis="no_data_available") despite
# ingestion/predicted_lineups_source.py independently confirming him as a real
# predicted STARTER that same week. Ownership-based market_conviction_override
# below never fires for a brand-new, low-profile signing (real ownership can't
# clear 10% before anyone's even seen him play) - exactly the case where a
# direct "a real site predicts he starts THIS match" signal is both stronger
# evidence and the one actually available. Takes precedence over the ownership
# check below (a specific per-fixture starting-XI prediction beats an indirect
# ownership proxy) but only within the same weak-evidence gate - never
# overrides a well-evidenced low estimate for the same reason
# market_conviction_override doesn't.
_PREDICTED_LINEUP_STARTER_MINUTES = 75.0
# Real gap found 2026-08-21 (forensic audit against real open-source FPL
# predictors, per the user's explicit ask - PlanFPL.com rated Maguire/
# Calafiori/Tonali roughly double this project's own numbers for the same
# real GW1 squad). Root cause traced to real data, not a fabricated
# discrepancy: all three have a genuine multi-season history of PARTIAL
# squad involvement (Maguire 19/38 starts, Calafiori 22/38, both '25/26) -
# real signal, correctly NOT in _WEAK_EVIDENCE_BASES. But minutes/38 conflates
# "how often was he selected" with "how long does he play once selected" -
# real per-start minutes for all three are 77-92 (confirmed via
# player_season_history: minutes/starts), a genuinely different number.
# `ingestion/predicted_lineups_source.py` already independently confirms
# whether a player is in THIS week's actual starting XI - when it does, "how
# often selected historically" stops being the open question and "how long
# does he play once selected" (his own real per-start rate) is the better
# estimate for the week we already know he starts. Gated on a minimum
# starts count so a single noisy match doesn't set the rate.
_MIN_STARTS_FOR_PER_START_RATE = 5
# Only overrides a base drawn from one of these already-weak-evidence
# branches - never a genuinely low but well-evidenced estimate (e.g. Havertz,
# a real, current-squad backup with real recent minutes data showing it -
# a low number there is a real signal, not a data gap, and must not be
# inflated just because of unrelated ownership noise).
_WEAK_EVIDENCE_BASES = {"no_data_available", "stale_prior_season", "cross_league_prior_new_signing"}

# Real gap found 2026-08-20 (a real, named player checked against a
# user-shared community squad screenshot - Isak): the most-recent-season-only
# prior collapsed a real, currently-FIT, established nailed starter to ~18
# expected minutes, because his single most recent season (694 minutes) was
# a genuine outlier (injury/transfer-saga disruption) against 3+ prior
# seasons of 1500-2800 minutes. `ORDER BY season_name DESC LIMIT 1` only
# ever sees that one anomalous season and has no way to know it was atypical.
# Blending the last 3 seasons with declining weights lets an established
# track record push back against one disrupted year, without ever ignoring
# the most recent season entirely (still weighted highest - a real, current
# rotation/form change is still respected, just not from one data point
# alone). Renormalised over however many seasons actually exist (1-3), so a
# player with only one real season is unaffected (same result as before).
_RECENT_SEASON_BLEND_WEIGHTS = (0.55, 0.30, 0.15)


def _blended_recent_seasons_per_gw(conn: sqlite3.Connection, player_id: int) -> float | None:
    """Real gap found 2026-08-21 (while checking the user's real "Gyokeres
    looks off" complaint by hand): FPL's own `history_past` can carry a row
    for a season years before a player ever reached English football
    (confirmed real - Gyokeres's only other row besides 2025/26 was 2018/19,
    0 minutes, a genuine data artifact not a real "quiet season"). The
    original version blended whatever `LIMIT 3` rows existed regardless of
    how far apart they actually were, so that one ancient zero-minute row
    dragged a real, established current player's blend down by ~35%
    (58.3->37.8 min/GW). Fixed by stopping the blend at the first genuine
    multi-season GAP between consecutive rows (season_name year jump > 1) -
    a discontinuity means "no trustworthy recent read beyond this point",
    same reasoning the single-row staleness check above already uses, just
    applied at the boundary where the actual gap is, not a fixed distance
    from "now" (which would have wrongly excluded the Isak case's real,
    perfectly consecutive 3-season blend - checked by hand before choosing
    this over a simpler absolute-threshold-per-row version)."""
    rows = conn.execute(
        "SELECT minutes, season_name FROM player_season_history WHERE player_id=? "
        "ORDER BY season_name DESC LIMIT ?",
        (player_id, len(_RECENT_SEASON_BLEND_WEIGHTS)),
    ).fetchall()
    usable: list[int] = []
    prev_year: int | None = None
    for r in rows:
        if r["minutes"] is None:
            continue
        year = _season_start_year(r["season_name"])
        if prev_year is not None and year is not None and prev_year - year > 1:
            break
        usable.append(r["minutes"])
        prev_year = year
    if not usable:
        return None
    weights = _RECENT_SEASON_BLEND_WEIGHTS[: len(usable)]
    total_weight = sum(weights)
    return sum(w * min(m / 38, 90) for w, m in zip(weights, usable)) / total_weight


@dataclass(frozen=True)
class ExpectedMinutes:
    player_id: int
    expected_minutes: float
    confidence: str  # LOW / MEDIUM / HIGH
    basis: str
    classification: str
    rotation_risk: str | None = None  # real quoted evidence from team_news_risk.py, else None


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
        "SELECT minutes, starts, season_name FROM player_season_history WHERE player_id=? ORDER BY season_name DESC LIMIT 1",
        (player_id,),
    ).fetchone()

    prior_is_stale = False
    if prior_row is not None:
        prior_year = _season_start_year(prior_row["season_name"])
        this_year = _season_start_year(current_season(conn))
        if prior_year is not None and this_year is not None and this_year - prior_year >= _STALE_SEASON_GAP_THRESHOLD:
            prior_is_stale = True

    if prior_row is not None and prior_row["minutes"] is not None and not prior_is_stale:
        # The most recent season is genuinely recent (not stale) - blend it
        # with up to 2 earlier seasons rather than trusting it alone, so one
        # anomalous year (injury, transfer-saga absence) doesn't fully
        # override an established track record. See _blended_recent_seasons_per_gw's
        # own docstring for the real case this closes (Isak).
        prior_per_gw = _blended_recent_seasons_per_gw(conn, player_id)
    elif prior_row is not None and prior_row["minutes"] is not None:
        # Stale case: every available row is old, so blending across them
        # doesn't address the real problem (no trustworthy recent read at
        # all) - keep using the single most-recent (still stale) row's own
        # value, unchanged, for the existing stale-discount branch below.
        prior_per_gw = min(prior_row["minutes"] / 38, 90)
    else:
        prior_per_gw = None

    if current_per_gw is not None and prior_per_gw is not None and not prior_is_stale:
        weight_current = min(finished_events / 10, 0.8)
        base = weight_current * current_per_gw + (1 - weight_current) * prior_per_gw
        confidence = "MEDIUM" if finished_events < 10 else "HIGH"
        basis = "blended_current_and_prior_season"
    elif current_per_gw is not None and prior_per_gw is not None and prior_is_stale:
        # Real gap found 2026-08-26 (Tzolis: real GW1 start, 75 real minutes,
        # projected forward at 15.2 expected minutes for GW2 - checked by hand
        # against the actual synced data, not assumed). The branch above
        # weights a stale, multi-season-old prior at up to 90% even once a
        # real, current-season appearance exists, because weight_current only
        # ramps on finished_events (1 early in a season) - it never accounts
        # for the PRIOR's own reliability, only the current sample's size.
        # A stale prior carries far less information than a genuinely recent
        # one (that's the entire reason prior_is_stale exists), so it should
        # lose the blend fast, not slow, once any real current evidence
        # exists - one real start is stronger evidence of an established role
        # than a cameo appearance from years/leagues ago. Ramps current-weight
        # from 0.5 (one real match) to 0.9 (3+), and keeps discounting the
        # stale prior itself (_NEW_SIGNING_MINUTES_DISCOUNT) rather than
        # trusting it at face value even for its shrinking share of the blend.
        weight_current = min(0.5 + 0.2 * finished_events, 0.9)
        base = weight_current * current_per_gw + (1 - weight_current) * (
            prior_per_gw * _NEW_SIGNING_MINUTES_DISCOUNT
        )
        confidence = "MEDIUM"
        basis = "blended_current_and_stale_prior"
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

    # Real gap found 2026-08-21 (the user pushed back directly on real GW1
    # picks - Osula/Gyokeres/Dorgu - checked by hand, confirmed real): the
    # predicted-lineup "starting" flag below is a binary classification that
    # doesn't cross-check the SAME scrape's own free-text team news, which
    # for these exact players plainly hedges ("two from three of Osula/
    # Wissa/Woltemade", "unless he displaces...Dorgu", "was only a
    # substitute"). See models/team_news_risk.py's module docstring for the
    # full real evidence. Computed once here and threaded through both
    # override branches below - a real rotation-risk hit BLOCKS the
    # "starting" flag from raising the estimate at all (falls back to the
    # season-average base, which already honestly reflects a partial role),
    # rather than silently trusting a structured flag its own source text
    # contradicts.
    rotation_risk = rotation_risk_snippet(conn, player_id)
    # Real gap found 2026-08-21 (continued user pushback: "why are you giving
    # me Madueke when... theres either journalist sites or fpl sites that do
    # this for free" - a genuine, better source, found and built the same
    # day: ingestion/lineup_probability_source.py, a real per-player start-
    # PERCENTAGE, not a binary starting/bench flag. Where it covers a player,
    # it REPLACES the binary predicted_lineup_players gate below with a
    # continuous scale - a player at 40% (Madueke's real number the day this
    # was built) gets raised 40% of the way toward the override target, not
    # silently treated the same as a 95%-certain starter. Falls back to the
    # binary gate + rotation_risk keyword heuristic exactly as before for any
    # player this newer, narrower-coverage source hasn't matched.
    start_percent = get_start_percent(conn, player_id)

    if basis in ("blended_current_and_prior_season", "current_season_only", "last_season_prior_no_current_data"):
        # Real, well-evidenced bases - only ever raises the estimate (never
        # overrides a low number that's a genuine signal, e.g. Havertz), and
        # only when the player's own real per-start rate is actually higher
        # than the season-average base already computed above.
        if prior_row is not None and prior_row["starts"] and prior_row["starts"] >= _MIN_STARTS_FOR_PER_START_RATE:
            per_start_minutes = min(prior_row["minutes"] / prior_row["starts"], 90)
            if start_percent is not None:
                if per_start_minutes > base:
                    base = base + (per_start_minutes - base) * (start_percent / 100)
                    basis = "predicted_lineup_confirmed_starting"
            else:
                predicted_starting = conn.execute(
                    "SELECT 1 FROM predicted_lineup_players WHERE player_id=? AND predicted_status='starting'",
                    (player_id,),
                ).fetchone()
                if predicted_starting is not None and rotation_risk is None and per_start_minutes > base:
                    base = per_start_minutes
                    basis = "predicted_lineup_confirmed_starting"

    if basis in _WEAK_EVIDENCE_BASES:
        if start_percent is not None:
            target = _PREDICTED_LINEUP_STARTER_MINUTES * (start_percent / 100)
            if target > base:
                base = target
                basis = "predicted_lineup_confirmed_starting"
        else:
            predicted_starting = conn.execute(
                "SELECT 1 FROM predicted_lineup_players WHERE player_id=? AND predicted_status='starting'",
                (player_id,),
            ).fetchone()
            if predicted_starting is not None and rotation_risk is None and base < _PREDICTED_LINEUP_STARTER_MINUTES:
                base = _PREDICTED_LINEUP_STARTER_MINUTES
                basis = "predicted_lineup_confirmed_starting"

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
        rotation_risk=rotation_risk,
    )
