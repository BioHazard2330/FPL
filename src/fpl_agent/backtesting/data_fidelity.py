"""Real forensic trace of the historical data pipeline (2026-09-07, Phase
7.4 Part 1/Part 12) - Phase 7.3's decision-regret work found DATA_ERROR
dominates historical regret (6/8 pooled regretful transfers, 86% of pooled
regret points), traced to the Understat player-id resolution backlog. This
module formalizes that finding into a real, queryable per-(player, season)
diagnostic and a small, composable data-confidence contract, instead of
leaving "the backlog is bad" as a single aggregate percentage.

The pipeline this traces (raw source -> identity resolver -> stored
identifier -> historical match lookup -> aggregation -> projection/backtest
input -> regret calculation):

1. Player identity: `players` (id, first_name/second_name/web_name,
   team_id, removed) - a LIVE roster snapshot, not a historical archive.
   `team_id` is CURRENT only - there is no historical team-affiliation
   table anywhere in this project's schema (confirmed: `player_season_
   history` has no team_id column either) - a real, structural gap this
   module works around (see `_best_effort_historical_team`) rather than
   pretends doesn't exist.
2. Understat player ids: NOT a persistent (understat_id -> player_id)
   table - `player_match_stats_history.understat_player_id` is stored per
   row, and resolution happens by NAME every time via `market_identity.
   resolve_player_id`, which caches into `player_name_aliases` keyed by
   (source, source_name) - a text string, not the numeric understat id.
3. Match-level rows: `player_match_stats_history`, one row per
   (understat_match_id, understat_player_id), `player_id` nullable.
4. Player-level aggregations: every real consumer (`player_regression.py`,
   `minutes_distribution.py`, `season_backtest.py`, `decision_regret.py`)
   filters `WHERE player_id=?` directly - an unresolved row is invisible
   to every one of them, indistinguishable in that query from "this real
   player genuinely had zero involvement."
5/6. Minutes/goals/assists/shots/xG/xA: same table, same rows.
7. Historical price: `player_price_history` has NO season column and
   (confirmed live against the real production DB) contains zero rows
   before 2026-08-12 - no historical weekly price data exists anywhere in
   this project. See `PRICE_DATA_LIMITATION` below.
8. Fixture/team context: `match_results_history`/`market_teams`, a
   separate, much smaller (20-40 entities) identity space - real, but not
   this module's focus (Part 1 scopes to player identity specifically,
   where the confirmed regret sits).
"""
import sqlite3
from dataclasses import dataclass

# Real, confirmed structural limitation (Phase 7.4 Part 3) - `player_price_
# history` has no `season` column and, checked live against the real
# production DB on 2026-09-07, its earliest real row is 2026-08-12T19:15 -
# the start of the LIVE 2026-27 season. No historical weekly price snapshot
# exists anywhere in this project for any prior season. `season_backtest.py`
# already disclosed this in its own module docstring (using the season's own
# PRESEASON price via `player_season_history.start_cost` for every round's
# budget check, not that player's real price at that point in the season) -
# this constant is the single source of truth for that disclosure, read by
# both `season_backtest.py` and this module's own report so the two never
# drift into disagreement about what the real limitation is.
PRICE_DATA_LIMITATION = (
    "No historical weekly price data exists anywhere in this project "
    "(player_price_history has no season column and zero real rows before "
    "the live 2026-27 season) - every historical-season transfer's budget "
    "check uses that season's own PRESEASON price (player_season_history."
    "start_cost), never the player's real price at that specific point in "
    "the season. Applied identically to every candidate every round, so it "
    "does not favour one side of a real comparison over another - but a "
    "transfer that would genuinely have been unaffordable after a real "
    "mid-season price rise (or affordable after a real fall) can be "
    "modelled incorrectly. Not fabricatable from any real source this "
    "project has access to."
)

# The 5 real states Part 1 requires. Ordered so a caller can compare
# severity with a plain index if it ever needs to (VALID_ZERO is the only
# genuinely trustworthy "nothing happened" reading).
VALID_ZERO = "VALID_ZERO"
MISSING_DATA = "MISSING_DATA"
UNRESOLVED_ID = "UNRESOLVED_ID"
SOURCE_FAILURE = "SOURCE_FAILURE"
NOT_APPLICABLE = "NOT_APPLICABLE"

# Part 12's own small, composable data-confidence contract - the 5 forensic
# states above are the right granularity for DIAGNOSING a data problem, but
# every real downstream consumer (regret classification, componentwise
# validation, minutes-segment validation) only ever needs to ask one
# coarser question: "can this player-season's data be trusted at all?" This
# is a direct, disclosed, non-overlapping mapping of the 5 states above -
# never a second, independently-judged classification.
CONFIDENCE_VALID = "VALID"
CONFIDENCE_PARTIAL = "PARTIAL"
CONFIDENCE_UNRESOLVED = "UNRESOLVED"
CONFIDENCE_INVALID = "INVALID"

_STATUS_TO_CONFIDENCE = {
    VALID_ZERO: CONFIDENCE_VALID,
    # A real, official record shows this player didn't feature (or the
    # season predates this project's own official coverage) - nothing is
    # being claimed about match-level detail, so there is nothing to
    # distrust.
    NOT_APPLICABLE: CONFIDENCE_VALID,
    # A real official season record exists but match-level detail is
    # honestly absent/incomplete for a source-coverage reason, not a known
    # resolver bug - partially trustworthy (the season-level total is real,
    # the round-by-round breakdown is not).
    MISSING_DATA: CONFIDENCE_PARTIAL,
    # A real, KNOWN, in-principle-fixable identity-resolution gap (this
    # player's own team has other real unresolved rows this season) -
    # distinct from PARTIAL because a future repair pass can genuinely
    # close this one, not just a disclosed source limitation.
    UNRESOLVED_ID: CONFIDENCE_UNRESOLVED,
    # Reserved for a confirmed-corrupted/contradictory read (never
    # currently produced by `diagnose_player_season` - no such case has
    # been found in this project's real data) - included so a future
    # diagnostic can plug into this same contract without inventing a
    # second one.
    SOURCE_FAILURE: CONFIDENCE_INVALID,
}


def confidence_for_status(derived_status: str) -> str:
    return _STATUS_TO_CONFIDENCE[derived_status]


def player_season_confidence(conn: sqlite3.Connection, player_id: int, season_dash: str) -> str:
    """The real, single-call convenience form of the contract above - what
    every non-bulk consumer (e.g. `decision_regret.py`, one specific
    in/out player per transfer) actually wants."""
    return confidence_for_status(diagnose_player_season(conn, player_id, season_dash).derived_status)


def low_confidence_player_season_count(conn: sqlite3.Connection, season_dash: str) -> int:
    """Real count of this season's player-seasons whose data-confidence is
    below VALID - the real, disclosed scope limit every walk-forward
    validator in this project structurally carries (a genuinely UNRESOLVED
    player-season contributes zero rows to `player_match_stats_history`, so
    is invisible to a query that only ever reads resolved rows - this is
    the one real way to surface how many are missing rather than silently
    validating over a shrunken, self-selected pool)."""
    return sum(
        1 for status in diagnose_season(conn, season_dash)
        if confidence_for_status(status.derived_status) != CONFIDENCE_VALID
    )

# A resolved row's own minutes rarely sum to the EXACT official total (cup
# matches/replays Understat doesn't cover, rare data entry gaps at the
# source) - a real, disclosed, non-fabricated tolerance rather than
# demanding a byte-exact match before trusting a real resolved season.
_COVERAGE_TOLERANCE_MINUTES = 180  # ~2 full matches of real, honest slack


def _season_slash(season_dash: str) -> str:
    start, end = season_dash.split("-")
    return f"{start}/{end}"


@dataclass(frozen=True)
class PlayerSeasonDataStatus:
    """One row of the real diagnostic table Part 1 asks for."""
    player_id: int
    web_name: str
    season: str  # dash form, e.g. "2023-24"
    expected_match_presence: int | None  # real official minutes from player_season_history; None = no official row at all
    resolved_match_rows: int  # real COUNT(*) of player_match_stats_history rows with player_id resolved to this player
    resolved_minutes: int  # real SUM(minutes) over those resolved rows
    identity_status: str  # "resolved" | "never_resolved_any_season" | "no_official_record"
    understat_ids_seen: tuple[str, ...]  # real understat_player_id values already tied to this player, any season
    fpl_id: int
    source_status: str  # "covered" | "team_has_unresolved_rows" | "team_fully_resolved" | "no_official_season"
    derived_status: str  # one of the 5 real states above


def _best_effort_historical_team(conn: sqlite3.Connection, player_id: int, season_dash: str) -> int | None:
    """Real, disclosed best-effort historical team_id (Phase 7.4 Part 1 -
    "transferred players break season matching" is a real, structural gap:
    neither `players` nor `player_season_history` stores a historical team
    affiliation anywhere in this project's schema). Prefers this player's
    OWN resolved `market_team_id` from THIS exact season if any row already
    resolved (the real, correct answer when available); falls back to the
    closest resolved season (adjacent seasons first) as a real, imperfect
    proxy - disclosed as a proxy, never presented as certain. `None` when
    no real anchor exists at all (this player has never once resolved in
    this table)."""
    row = conn.execute(
        "SELECT market_team_id FROM player_match_stats_history WHERE player_id=? AND season=? LIMIT 1",
        (player_id, season_dash),
    ).fetchone()
    if row is not None:
        return row["market_team_id"]
    row = conn.execute(
        "SELECT market_team_id, season FROM player_match_stats_history WHERE player_id=? "
        "ORDER BY ABS(CAST(SUBSTR(season,1,4) AS INTEGER) - CAST(SUBSTR(?,1,4) AS INTEGER)) LIMIT 1",
        (player_id, season_dash),
    ).fetchone()
    return row["market_team_id"] if row is not None else None


def diagnose_player_season(conn: sqlite3.Connection, player_id: int, season_dash: str) -> PlayerSeasonDataStatus:
    player = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
    web_name = player["web_name"] if player is not None else f"#{player_id}"

    season_row = conn.execute(
        "SELECT minutes, starts FROM player_season_history WHERE player_id=? AND season_name=?",
        (player_id, _season_slash(season_dash)),
    ).fetchone()
    expected_minutes = season_row["minutes"] if season_row is not None else None

    agg = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(minutes),0) m FROM player_match_stats_history "
        "WHERE player_id=? AND season=?", (player_id, season_dash),
    ).fetchone()
    resolved_rows, resolved_minutes = agg["c"], agg["m"]

    understat_ids = tuple(
        r["understat_player_id"] for r in conn.execute(
            "SELECT DISTINCT understat_player_id FROM player_match_stats_history WHERE player_id=?", (player_id,)
        ).fetchall()
    )
    identity_status = (
        "resolved" if resolved_rows > 0 else
        ("never_resolved_any_season" if not understat_ids else "resolved")
    )
    # (understat_ids can be non-empty even with resolved_rows==0 for THIS
    # season specifically - the player resolved in a DIFFERENT season.)
    if resolved_rows == 0 and understat_ids:
        identity_status = "resolved_other_season_only"
    elif resolved_rows == 0 and not understat_ids:
        identity_status = "never_resolved_any_season"

    # NOT_APPLICABLE: no real official record this player featured this
    # season at all (never played, or wasn't a real top-flight player that
    # season under this id) - the honest "there is nothing to explain" case.
    if season_row is None or not expected_minutes:
        return PlayerSeasonDataStatus(
            player_id=player_id, web_name=web_name, season=season_dash,
            expected_match_presence=expected_minutes, resolved_match_rows=resolved_rows,
            resolved_minutes=resolved_minutes, identity_status=identity_status, understat_ids_seen=understat_ids,
            fpl_id=player_id, source_status="no_official_season" if season_row is None else "covered",
            derived_status=NOT_APPLICABLE,
        )

    # A real official record exists and shows real minutes - Understat
    # should have SOME coverage. Real, resolved, roughly-matching coverage
    # is trustworthy regardless of whether the resolved stats are zero.
    if resolved_rows > 0 and abs(resolved_minutes - expected_minutes) <= _COVERAGE_TOLERANCE_MINUTES:
        return PlayerSeasonDataStatus(
            player_id=player_id, web_name=web_name, season=season_dash,
            expected_match_presence=expected_minutes, resolved_match_rows=resolved_rows,
            resolved_minutes=resolved_minutes, identity_status=identity_status, understat_ids_seen=understat_ids,
            fpl_id=player_id, source_status="covered", derived_status=VALID_ZERO,
        )

    # Real official minutes exist but resolved coverage is absent or
    # materially short - MISSING_DATA vs UNRESOLVED_ID, distinguished by a
    # real, disclosed proxy: does this player's best-effort historical team
    # have ANY genuinely unresolved rows this season at all? If the team's
    # own Understat coverage is otherwise complete (zero unresolved rows for
    # that team+season), a real resolution failure specific to this player
    # is unlikely - more likely Understat itself never covered this exact
    # player/fixture (a real, disclosed source gap, not a resolver bug).
    team_id = _best_effort_historical_team(conn, player_id, season_dash)
    team_has_unresolved = False
    if team_id is not None:
        team_has_unresolved = conn.execute(
            "SELECT 1 FROM player_match_stats_history WHERE market_team_id=? AND season=? AND player_id IS NULL LIMIT 1",
            (team_id, season_dash),
        ).fetchone() is not None

    if team_id is None:
        # No real team anchor at all (this player has never once resolved,
        # in any season) - can't even form the proxy above. Honest
        # "can't classify further than: data is missing" state.
        return PlayerSeasonDataStatus(
            player_id=player_id, web_name=web_name, season=season_dash,
            expected_match_presence=expected_minutes, resolved_match_rows=resolved_rows,
            resolved_minutes=resolved_minutes, identity_status=identity_status, understat_ids_seen=understat_ids,
            fpl_id=player_id, source_status="no_team_anchor", derived_status=MISSING_DATA,
        )
    if team_has_unresolved:
        return PlayerSeasonDataStatus(
            player_id=player_id, web_name=web_name, season=season_dash,
            expected_match_presence=expected_minutes, resolved_match_rows=resolved_rows,
            resolved_minutes=resolved_minutes, identity_status=identity_status, understat_ids_seen=understat_ids,
            fpl_id=player_id, source_status="team_has_unresolved_rows", derived_status=UNRESOLVED_ID,
        )
    return PlayerSeasonDataStatus(
        player_id=player_id, web_name=web_name, season=season_dash,
        expected_match_presence=expected_minutes, resolved_match_rows=resolved_rows,
        resolved_minutes=resolved_minutes, identity_status=identity_status, understat_ids_seen=understat_ids,
        fpl_id=player_id, source_status="team_fully_resolved", derived_status=MISSING_DATA,
    )


def diagnose_season(conn: sqlite3.Connection, season_dash: str) -> list[PlayerSeasonDataStatus]:
    """Real, bulk diagnostic over every player with a real official
    `player_season_history` row for this season (the authoritative,
    Understat-independent "did this player really feature" source) - never
    scans `player_match_stats_history` first, which would only ever see
    players Understat already covers, silently excluding the exact players
    this diagnostic exists to find."""
    player_ids = [
        r["player_id"] for r in conn.execute(
            "SELECT player_id FROM player_season_history WHERE season_name=?", (_season_slash(season_dash),)
        ).fetchall()
    ]
    return [diagnose_player_season(conn, pid, season_dash) for pid in player_ids]
