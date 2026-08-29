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
    # Real, verified-live 2026-08-26 (GW1-postmortem audit P1 "penalty-duty
    # extraction") - FotMob's real shotmap carries a genuine `situation`
    # field per shot; `situation == "Penalty"` was confirmed against 2 real
    # GW1 penalty shots before this was built (never assumed). Deliberately
    # NOT yet fed into any xP adjustment - see models/penalty_duty.py's own
    # module docstring for why (real data volume, not code, is the current
    # constraint).
    penalty_shots: int | None
    penalty_goals: int | None


@dataclass(frozen=True)
class TeamMatchState:
    team_name: str
    formation: str | None
    possession_pct: float | None
    shots: int | None
    shots_on_target: int | None
    xg: float | None
    corners: int | None
    big_chances: int | None
    big_chances_missed: int | None


@dataclass(frozen=True)
class MomentumPoint:
    """Real FotMob per-minute momentum sample (`content.momentum.main.data`,
    confirmed live 2026-08-29 against a real finished match: a -100..100
    value per minute, negative=away pressure/positive=home pressure - never
    interpolated beyond the real samples FotMob itself supplies)."""
    minute: int
    value: int


@dataclass(frozen=True)
class ShotEvent:
    """Real per-shot record (`content.shotmap.shots`, confirmed live
    2026-08-29 - 28 real shots with genuine x/y/xG on a finished GW2 match).
    `x`/`y` are FotMob's own real pitch-percentage coordinates (0-100,
    attacking direction toward x=100) - never a fabricated/guessed
    transform. `outcome` is FotMob's raw `eventType` (Goal/AttemptSaved/
    Miss/BlockedShot/Post)."""
    fotmob_shot_id: str
    team_fotmob_id: int | None
    fotmob_player_id: str | None
    player_name: str | None
    minute: int | None
    x: float | None
    y: float | None
    xg: float | None
    is_on_target: bool | None
    outcome: str | None
    shot_type: str | None
    situation: str | None
    period: str | None


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
        row = agg.setdefault(pid, {"shots": 0, "goals": 0, "xg": 0.0, "penalty_shots": 0, "penalty_goals": 0})
        row["shots"] += 1
        is_goal = shot.get("eventType") == "Goal"
        if is_goal:
            row["goals"] += 1
        xg = shot.get("expectedGoals")
        if xg is not None:
            row["xg"] += float(xg)
        if shot.get("situation") == "Penalty":
            row["penalty_shots"] += 1
            if is_goal:
                row["penalty_goals"] += 1
    return agg


def _player_stats_by_id(payload: dict) -> dict[str, dict]:
    """Real per-player detailed stats (`content.playerStats`, confirmed live
    2026-08-29 against a real finished match - keyed by FotMob player id,
    each carrying a "Top stats" group with real rating/minutes/goals/
    assists/xA/chances-created values). `None` (absent key) for a pre-match
    payload or a match this project hasn't confirmed the shape against -
    every caller treats a missing id here as "use the shot-aggregate
    fallback", never a crash."""
    player_stats = (payload.get("content") or {}).get("playerStats")
    if not isinstance(player_stats, dict):
        return {}
    out: dict[str, dict] = {}
    for pid, p in player_stats.items():
        top = next((g.get("stats") or {} for g in (p.get("stats") or []) if g.get("key") == "top_stats"), {})
        out[str(pid)] = {
            title: (v.get("stat") or {}).get("value")
            for title, v in top.items() if isinstance(v, dict)
        }
    return out


def _substitution_minutes(performance: dict | None) -> tuple[int | None, int | None]:
    """Real substitution timing off `performance.substitutionEvents`
    (confirmed live 2026-08-29 - a real subIn/subOut minute per event, on
    both a starter who was later subbed off and a bench player subbed on).
    Never guessed from minutes-played alone."""
    on_minute = off_minute = None
    for ev in (performance or {}).get("substitutionEvents") or []:
        if ev.get("type") == "subIn":
            on_minute = ev.get("time")
        elif ev.get("type") == "subOut":
            off_minute = ev.get("time")
    return on_minute, off_minute


def _player_match_state_from_entry(
    entry: dict, team_name: str, started: bool, shot_aggregates: dict, stats_by_id: dict,
) -> "PlayerMatchState":
    fotmob_id = str(entry.get("id"))
    performance = entry.get("performance") or {}
    # shotmap.shots is a real, always-present live feed (confirmed live
    # pre-match: an empty list, not an absent key) - a player missing from
    # it has genuinely taken zero shots so far, a real observed fact, not
    # missing data. Default to 0/0.0, not None.
    agg = shot_aggregates.get(fotmob_id, {"shots": 0, "goals": 0, "xg": 0.0, "penalty_shots": 0, "penalty_goals": 0})
    top = stats_by_id.get(fotmob_id, {})
    on_minute, off_minute = _substitution_minutes(performance)
    # Real "Chances created" (FotMob's own term - the closest real analog
    # this source publishes to "key passes", confirmed live; never a
    # fabricated second definition of key passes).
    key_passes = top.get("Chances created")
    return PlayerMatchState(
        fotmob_player_id=fotmob_id,
        team_name=team_name,
        name_raw=entry.get("name", ""),
        started=started,
        minutes=top.get("Minutes played"),
        position=None,
        rating=top.get("FotMob rating", performance.get("rating")),
        goals=int(top["Goals"]) if top.get("Goals") is not None else agg.get("goals", 0),
        assists=int(top["Assists"]) if top.get("Assists") is not None else None,
        shots=int(top["Total shots"]) if top.get("Total shots") is not None else agg.get("shots", 0),
        key_passes=int(key_passes) if key_passes is not None else None,
        xg=float(top["Expected goals (xG)"]) if top.get("Expected goals (xG)") is not None else agg.get("xg", 0.0),
        xa=float(top["Expected assists (xA)"]) if top.get("Expected assists (xA)") is not None else None,
        touches_box=top.get("Touches in opposition box"),
        substituted_on_minute=on_minute,
        substituted_off_minute=off_minute,
        penalty_shots=agg.get("penalty_shots", 0),
        penalty_goals=agg.get("penalty_goals", 0),
    )


def parse_player_states(payload: dict) -> list[PlayerMatchState]:
    """Starters + bench (2026-08-29 fix - a real bench/`subs` list IS
    published once a match has real lineup data; confirmed live against a
    finished match, `homeTeam.subs` carries the same shape as `starters`
    plus `performance.substitutionEvents`. The earlier "starters only, no
    bench key" finding was real but specific to a pre-match payload check -
    not re-checked against a live/finished match until now). Real minutes/
    rating/assists/xA/chances-created now come from `content.playerStats`
    (confirmed live - previously hardcoded to `None`/never extracted);
    shot-count/goals/xG/penalty fall back to the real shot-aggregate
    computation when `playerStats` doesn't cover a given id (e.g. a very
    early pre-match payload). `position` stays null - see this function's
    own prior reasoning, unchanged: FotMob's raw `positionId` mapping was
    never verified, and this project's own `players.element_type` already
    carries a real position once resolved."""
    content = payload.get("content") or {}
    lineup = content.get("lineup") or {}
    shot_aggregates = _shot_aggregates_by_player(payload)
    stats_by_id = _player_stats_by_id(payload)
    states: list[PlayerMatchState] = []

    for side_key in ("homeTeam", "awayTeam"):
        side = lineup.get(side_key) or {}
        team_name = side.get("name", "")
        for starter in side.get("starters") or []:
            states.append(_player_match_state_from_entry(starter, team_name, True, shot_aggregates, stats_by_id))
        for sub in side.get("subs") or []:
            states.append(_player_match_state_from_entry(sub, team_name, False, shot_aggregates, stats_by_id))
    return states


_TEAM_STATS_FIELDS = ("possession_pct", "shots", "shots_on_target", "xg", "corners", "big_chances", "big_chances_missed")


def _safe_team_stats(stats_block: dict | None, side_index: int) -> dict:
    """Confirmed live 2026-08-29 against a real finished match (this shape
    was previously best-effort/unverified per this function's own prior
    docstring note - the real payload matches exactly). Any lookup failure
    still returns all-None rather than raising."""
    result = {field: None for field in _TEAM_STATS_FIELDS}
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
            "Big chances": "big_chances",
            "Big chances missed": "big_chances_missed",
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
        return {field: None for field in _TEAM_STATS_FIELDS}
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
                big_chances=stats["big_chances"],
                big_chances_missed=stats["big_chances_missed"],
            )
        )
    return team_states


def parse_momentum(payload: dict) -> list[MomentumPoint]:
    """`content.momentum` is a real `False` (bool) pre-match (confirmed live
    on a real not-yet-kicked-off fixture) and a real `{"main": {"data": [...]}}`
    dict once a match has started (confirmed live on a finished match - a
    full 0-90+ minute series). Returns `[]` for the pre-match/absent case -
    never a fabricated flat line."""
    momentum = ((payload.get("content") or {}).get("momentum")) or {}
    if not isinstance(momentum, dict):
        return []
    data = ((momentum.get("main") or {}).get("data")) or []
    points = []
    for d in data:
        minute, value = d.get("minute"), d.get("value")
        if minute is None or value is None:
            continue
        points.append(MomentumPoint(minute=int(minute), value=int(value)))
    return points


def parse_shot_map(payload: dict) -> list[ShotEvent]:
    """`content.shotmap.shots` - confirmed live 2026-08-29 against a real
    finished match (28 real shots, genuine x/y/xG/outcome fields). Real
    empty list pre-match/no shots yet (confirmed live: `{"shots": [],
    "Periods": {"All": []}}`), never fabricated."""
    shots = ((payload.get("content") or {}).get("shotmap") or {}).get("shots") or []
    out = []
    for s in shots:
        shot_id = s.get("id")
        if shot_id is None:
            continue
        out.append(ShotEvent(
            fotmob_shot_id=str(shot_id),
            team_fotmob_id=s.get("teamId"),
            fotmob_player_id=str(s["playerId"]) if s.get("playerId") is not None else None,
            player_name=s.get("fullName") or s.get("playerName"),
            minute=s.get("min"),
            x=s.get("x"), y=s.get("y"), xg=s.get("expectedGoals"),
            is_on_target=s.get("isOnTarget"),
            outcome=s.get("eventType"),
            shot_type=s.get("shotType"),
            situation=s.get("situation"),
            period=s.get("period"),
        ))
    return out
