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
    live_minute: str | None  # FotMob's own real display string ("17'", "HT", "45+2'") - stored raw, never parsed into a number that could silently misrepresent added time


@dataclass(frozen=True)
class MatchEvent:
    """A real, structured incident - never LLM-authored, never a free-text
    commentary sentence (FotMob's own minute-by-minute text ticker lives
    behind a JS-rendered Opta widget with no plain JSON endpoint - checked
    live 2026-08-21, not scrapeable without a browser dependency this
    project doesn't take on). Two real FotMob sources feed this, merged by
    the parser below: `content.matchFacts.events.events` (Goal/Card/Sub/VAR/
    Injury - the same list FotMob's own match-centre "Match" tab uses) and
    `content.shotmap.shots` (every shot attempt, Goal-type shots excluded
    here since matchFacts already covers goals with richer assist data)."""
    source_event_id: str
    minute: int | None
    event_type: str
    is_home: bool | None
    fotmob_player_id: str | None
    player_name: str | None
    description: str


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
    reads `header.status.liveTime.short == "HT"` - corrected 2026-08-21
    against the REAL halftime state of that same live match: the original
    guess (`header.status.reason.short`) was never live-verified (this
    project's own docstring admitted as much - "no real match was in
    progress to check against") and turned out wrong - `reason` doesn't
    exist in the real payload at all during halftime; `liveTime.short`
    (already used elsewhere for the real live-minute display) is the actual
    field, confirmed directly against the live payload. Falls through to
    LIVE (started, not finished) when that field is absent or doesn't say
    HT, so an unrecognized live sub-state is never mis-reported as
    something more specific than the code can actually confirm."""
    if general.get("finished"):
        return FULL_TIME
    if not general.get("started"):
        return PRE_MATCH
    live_short = ((header_status or {}).get("liveTime") or {}).get("short")
    if live_short == "HT":
        return HALFTIME
    return LIVE


def parse_match(payload: dict) -> Match:
    general = payload.get("general", {}) or {}
    header = payload.get("header", {}) or {}
    header_status = header.get("status") or {}
    teams = header.get("teams") or []
    home_score = teams[0].get("score") if len(teams) > 0 else None
    away_score = teams[1].get("score") if len(teams) > 1 else None
    # Real FotMob display string, confirmed live 2026-08-21 against the real
    # Arsenal v Coventry match - carries embedded LRM/RLM direction marks
    # (U+200E) around the apostrophe (e.g. "17‎’‎") that
    # render invisibly in a browser but would show as odd characters in a
    # plain terminal - stripped here, not parsed into an int (added time
    # like "45+2'" has no single honest numeric form).
    raw_minute = ((header_status or {}).get("liveTime") or {}).get("short")
    live_minute = raw_minute.replace("‎", "") if raw_minute else None

    return Match(
        fotmob_match_id=str(general.get("matchId")),
        competition=general.get("leagueName"),
        kickoff_utc=general.get("matchTimeUTCDate"),
        home_team_name=(general.get("homeTeam") or {}).get("name", ""),
        away_team_name=(general.get("awayTeam") or {}).get("name", ""),
        status=derive_status(general, header_status),
        home_score=home_score,
        away_score=away_score,
        live_minute=live_minute,
    )


_SHOT_TYPE_LABEL = {
    "Miss": "Shot off target", "AttemptSaved": "Shot saved", "Post": "Shot hit the post",
    "BlockedShot": "Shot blocked",
}


def parse_match_events(payload: dict) -> list["MatchEvent"]:
    """Real, chronologically-mergeable incidents from two real FotMob
    sources - never invented, never LLM-authored. Corners/VAR-review-in-
    progress/free-text play-by-play are NOT available here (that data lives
    behind FotMob's JS-rendered Opta widget, not a plain JSON endpoint) -
    disclosed honestly rather than fabricated to fill the gap."""
    general = payload.get("general", {}) or {}
    home_fotmob_id = (general.get("homeTeam") or {}).get("id")
    events: list[MatchEvent] = []

    facts = ((payload.get("content") or {}).get("matchFacts") or {}).get("events") or {}
    for e in facts.get("events") or []:
        event_type = e.get("type") or "Event"
        player = e.get("player") or {}
        player_name = e.get("fullName") or player.get("name")
        # Real administrative markers FotMob's own event list carries
        # alongside player incidents - genuinely useful (real added-time
        # amount), not just noise, given real descriptions rather than the
        # generic "AddedTime — AddedTime" fallback.
        if event_type == "Half":
            desc = "Half-time" if e.get("halfStrShort") == "HT" else "End of match"
        elif event_type == "AddedTime":
            desc = e.get("minutesAddedStr") or "Added time announced"
        elif player_name:
            desc = f"{event_type} — {player_name}"
        else:
            desc = event_type
        if e.get("assistStr"):
            desc = f"{desc} ({e['assistStr']})"
        raw_id = e.get("eventId") or e.get("reactKey")
        if raw_id is None:
            continue
        events.append(MatchEvent(
            source_event_id=f"fact-{raw_id}", minute=e.get("time"), event_type=event_type,
            is_home=e.get("isHome"), fotmob_player_id=str(player["id"]) if player.get("id") is not None else None,
            player_name=player_name, description=desc,
        ))

    shots = ((payload.get("content") or {}).get("shotmap") or {}).get("shots") or []
    for shot in shots:
        if shot.get("eventType") == "Goal":
            continue  # already covered by the richer matchFacts Goal event (with assist)
        shot_id = shot.get("id")
        if shot_id is None:
            continue
        label = _SHOT_TYPE_LABEL.get(shot.get("eventType"), "Shot")
        player_name = shot.get("fullName") or shot.get("playerName")
        desc = f"{label} — {player_name}" if player_name else label
        is_home = (shot.get("teamId") == home_fotmob_id) if home_fotmob_id is not None else None
        events.append(MatchEvent(
            source_event_id=f"shot-{shot_id}", minute=shot.get("min"), event_type="Shot",
            is_home=is_home, fotmob_player_id=str(shot["playerId"]) if shot.get("playerId") is not None else None,
            player_name=player_name, description=desc,
        ))

    return events


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
