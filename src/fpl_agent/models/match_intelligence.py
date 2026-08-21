"""Normalized match-intelligence models + pure parsing of FotMob's
matchDetails payload (Pillar 4 Slice A - see docs/superpowers/specs/
2026-08-21-match-intelligence-core-design.md). Pure functions only - no DB
access, no network. Fields are `| None` wherever FotMob may not carry real
data for a given match state (pre-match, in particular) - never a fabricated
default standing in for missing evidence.

Team-level stats (possession/shots/xg/corners, `parse_team_states`) read a
nested `content.stats.Periods.All.stats` shape that is FotMob's well-known
public convention (used across the FotMob-scraping ecosystem) but was NOT
live-verified against a completed match this session - the real Arsenal v
Coventry match used to build this was still pre-kickoff, so `content.stats`
was `null` and this path was never actually exercised against real data.
Wrapped defensively (`_safe_team_stats`): any shape mismatch degrades to
`None` fields rather than crashing the sync. Per-player numbers instead read
`content.shotmap.shots` (confirmed live: the empty-payload shape
`{"shots": [], "Periods": {"All": []}}` was observed directly), the more
reliable of the two once a real shot has been taken.
"""
from dataclasses import dataclass

PRE_MATCH = "PRE_MATCH"
LIVE = "LIVE"
HALFTIME = "HALFTIME"
FULL_TIME = "FULL_TIME"


@dataclass(frozen=True)
class Match:
    fotmob_match_id: str
    competition: str | None
    kickoff_utc: str | None
    home_team_name: str
    away_team_name: str
    status: str
    home_score: int | None
    away_score: int | None


@dataclass(frozen=True)
class PlayerMatchState:
    fotmob_player_id: str
    team_name: str
    name_raw: str
    started: bool
    minutes: int | None
    position: str | None
    rating: float | None
    goals: int | None
    assists: int | None
    shots: int | None
    key_passes: int | None
    xg: float | None
    xa: float | None
    touches_box: int | None
    substituted_on_minute: int | None
    substituted_off_minute: int | None


@dataclass(frozen=True)
class TeamMatchState:
    team_name: str
    formation: str | None
    possession_pct: float | None
    shots: int | None
    shots_on_target: int | None
    xg: float | None
    corners: int | None


def derive_status(general: dict, header_status: dict | None = None) -> str:
    """`general.started`/`general.finished` are the two fields confirmed live
    against the real pre-match Arsenal v Coventry payload. Halftime detection
    additionally reads `header.status.reason.short == "HT"` when present -
    FotMob's documented convention elsewhere on the site, not live-verified
    this session (no real match was in progress to check against) - falls
    through to LIVE (started, not finished) when that field is absent or
    doesn't say HT, so an unrecognized live sub-state is never mis-reported
    as something more specific than the code can actually confirm."""
    if general.get("finished"):
        return FULL_TIME
    if not general.get("started"):
        return PRE_MATCH
    reason = ((header_status or {}).get("reason") or {}).get("short")
    if reason == "HT":
        return HALFTIME
    return LIVE


def parse_match(payload: dict) -> Match:
    general = payload.get("general", {}) or {}
    header = payload.get("header", {}) or {}
    header_status = header.get("status") or {}
    teams = header.get("teams") or []
    home_score = teams[0].get("score") if len(teams) > 0 else None
    away_score = teams[1].get("score") if len(teams) > 1 else None

    return Match(
        fotmob_match_id=str(general.get("matchId")),
        competition=general.get("leagueName"),
        kickoff_utc=general.get("matchTimeUTCDate"),
        home_team_name=(general.get("homeTeam") or {}).get("name", ""),
        away_team_name=(general.get("awayTeam") or {}).get("name", ""),
        status=derive_status(general, header_status),
        home_score=home_score,
        away_score=away_score,
    )


def _shot_aggregates_by_player(payload: dict) -> dict[str, dict]:
    """Confirmed-live shape: content.shotmap.shots is a flat list of real shot
    events (empty pre-match). Aggregates per fotmob player id - real observed
    counts, correctly zero when no shots have happened yet, never fabricated."""
    shots = ((payload.get("content") or {}).get("shotmap") or {}).get("shots") or []
    agg: dict[str, dict] = {}
    for shot in shots:
        pid = shot.get("playerId")
        if pid is None:
            continue
        pid = str(pid)
        row = agg.setdefault(pid, {"shots": 0, "goals": 0, "xg": 0.0})
        row["shots"] += 1
        if shot.get("eventType") == "Goal":
            row["goals"] += 1
        xg = shot.get("expectedGoals")
        if xg is not None:
            row["xg"] += float(xg)
    return agg


def parse_player_states(payload: dict) -> list[PlayerMatchState]:
    """Starters only - FotMob's free lineup payload does not publish a bench
    list for this match pre-kickoff (confirmed live: `lineup.homeTeam` keys
    are exactly `id/name/formation/starters/coach/unavailable/
    averageStarterAge/totalStarterMarketValue`, no `bench` key). A benched
    player who is later subbed on will appear once shot/stat data references
    them; substitution-pattern detection beyond that is Slice B's job, not
    this one's. `position` is deliberately left null: FotMob's raw
    `positionId` values were not confirmed against a verified mapping this
    session, and this project's own `players.element_type` already carries a
    real position once the player is resolved - guessing here would risk a
    silently wrong label for no real benefit."""
    content = payload.get("content") or {}
    lineup = content.get("lineup") or {}
    shot_aggregates = _shot_aggregates_by_player(payload)
    states: list[PlayerMatchState] = []

    for side_key in ("homeTeam", "awayTeam"):
        side = lineup.get(side_key) or {}
        team_name = side.get("name", "")
        for starter in side.get("starters") or []:
            fotmob_id = str(starter.get("id"))
            # shotmap.shots is a real, always-present live feed (confirmed
            # live pre-match: an empty list, not an absent key) - a player
            # missing from it has genuinely taken zero shots so far, a real
            # observed fact, not missing data. Default to 0/0.0, not None.
            agg = shot_aggregates.get(fotmob_id, {"shots": 0, "goals": 0, "xg": 0.0})
            states.append(
                PlayerMatchState(
                    fotmob_player_id=fotmob_id,
                    team_name=team_name,
                    name_raw=starter.get("name", ""),
                    started=True,
                    minutes=None,
                    position=None,
                    rating=None,
                    goals=agg.get("goals", 0),
                    assists=None,
                    shots=agg.get("shots", 0),
                    key_passes=None,
                    xg=agg.get("xg", 0.0),
                    xa=None,
                    touches_box=None,
                    substituted_on_minute=None,
                    substituted_off_minute=None,
                )
            )
    return states


def _safe_team_stats(stats_block: dict | None, side_index: int) -> dict:
    """See module docstring - this shape is best-effort/unverified. Any
    lookup failure returns all-None rather than raising."""
    result = {"possession_pct": None, "shots": None, "shots_on_target": None, "xg": None, "corners": None}
    if not stats_block:
        return result
    try:
        groups = ((stats_block.get("Periods") or {}).get("All") or {}).get("stats") or []
        wanted = {
            "Ball possession": "possession_pct",
            "Total shots": "shots",
            "Shots on target": "shots_on_target",
            "Expected goals (xG)": "xg",
            "Corners": "corners",
        }
        for group in groups:
            for item in group.get("stats", []):
                field = wanted.get(item.get("title"))
                if field is None:
                    continue
                values = item.get("stats")
                if not values or len(values) <= side_index:
                    continue
                raw = values[side_index]
                if raw in (None, ""):
                    continue
                cleaned = str(raw).replace("%", "").strip()
                result[field] = float(cleaned) if field in ("possession_pct", "xg") else int(float(cleaned))
    except (TypeError, ValueError, KeyError, IndexError):
        return {"possession_pct": None, "shots": None, "shots_on_target": None, "xg": None, "corners": None}
    return result


def parse_team_states(payload: dict) -> list[TeamMatchState]:
    content = payload.get("content") or {}
    lineup = content.get("lineup") or {}
    stats_block = content.get("stats")
    team_states: list[TeamMatchState] = []

    for side_index, side_key in enumerate(("homeTeam", "awayTeam")):
        side = lineup.get(side_key) or {}
        team_name = side.get("name", "")
        stats = _safe_team_stats(stats_block, side_index)
        team_states.append(
            TeamMatchState(
                team_name=team_name,
                formation=side.get("formation"),
                possession_pct=stats["possession_pct"],
                shots=stats["shots"],
                shots_on_target=stats["shots_on_target"],
                xg=stats["xg"],
                corners=stats["corners"],
            )
        )
    return team_states
