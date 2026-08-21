import sqlite3
from dataclasses import dataclass

# When FPL hasn't published attack/defence splits yet (common preseason - see teams
# table, all-zero at launch), fall back to strength_overall_* as a coarser proxy.
_FALLBACK_MIN = 1


def _team_strength(conn: sqlite3.Connection, team_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT strength_overall_home, strength_overall_away, "
        "strength_attack_home, strength_attack_away, "
        "strength_defence_home, strength_defence_away FROM teams WHERE id=?",
        (team_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown team_id: {team_id}")
    return row


def _venue_strength(team_row: sqlite3.Row, kind: str, venue: str) -> tuple[int, bool]:
    """kind: 'attack'|'defence'. venue: 'home'|'away'. Returns (value, used_fallback)."""
    specific = team_row[f"strength_{kind}_{venue}"]
    if specific is not None and specific >= _FALLBACK_MIN:
        return specific, False
    overall = team_row[f"strength_overall_{venue}"]
    return (overall if overall is not None else 3), True  # 3 = FPL's mid-scale default


@dataclass(frozen=True)
class FixtureDifficulty:
    fixture_id: int
    event: int | None
    team_h: int
    team_a: int
    team_h_attack_difficulty: float   # higher = harder for home team to score
    team_h_defence_difficulty: float  # higher = harder for home team to keep a clean sheet
    team_a_attack_difficulty: float
    team_a_defence_difficulty: float
    used_fallback: bool


def fixture_difficulty(conn: sqlite3.Connection, fixture_id: int) -> FixtureDifficulty:
    fx = conn.execute(
        "SELECT id, event, team_h, team_a FROM fixtures WHERE id=?", (fixture_id,)
    ).fetchone()
    if fx is None:
        raise ValueError(f"unknown fixture_id: {fixture_id}")

    team_h_row = _team_strength(conn, fx["team_h"])
    team_a_row = _team_strength(conn, fx["team_a"])

    h_attack, fb1 = _venue_strength(team_a_row, "defence", "away")  # home's attack difficulty = away team's away defence
    h_defence, fb2 = _venue_strength(team_a_row, "attack", "away")
    a_attack, fb3 = _venue_strength(team_h_row, "defence", "home")
    a_defence, fb4 = _venue_strength(team_h_row, "attack", "home")

    return FixtureDifficulty(
        fixture_id=fx["id"],
        event=fx["event"],
        team_h=fx["team_h"],
        team_a=fx["team_a"],
        team_h_attack_difficulty=h_attack,
        team_h_defence_difficulty=h_defence,
        team_a_attack_difficulty=a_attack,
        team_a_defence_difficulty=a_defence,
        used_fallback=any((fb1, fb2, fb3, fb4)),
    )


@dataclass(frozen=True)
class FixtureWindow:
    team_id: int
    n_gw: int
    fixture_count: int
    avg_attack_difficulty: float
    avg_defence_difficulty: float
    used_fallback: bool


@dataclass(frozen=True)
class TickerEntry:
    fixture_id: int
    event: int
    opponent_team_id: int
    opponent_short: str
    is_home: bool
    difficulty: int  # real FPL 1-5 FDR scale (see fixture_difficulty's own docstring)


def team_fixture_ticker(conn: sqlite3.Connection, team_id: int, n_gw: int = 5, from_event: int | None = None) -> list[TickerEntry]:
    """Real per-fixture difficulty ticker (2026-08-21, per direct user ask
    to build what FPL Copilot/Fantasy Football Scout's own FDR ticker shows -
    real research confirmed live: a colored 1-5 cell per upcoming fixture,
    never a single number blended across several matches). One entry per
    real fixture in the window - unlike `fixture_window_score` (which
    averages into one summary figure for transfer-planning comparisons),
    this returns the individual per-gameweek reads a ticker actually needs.
    `difficulty` is the OPPONENT's own overall strength in the venue they're
    playing at that fixture (`strength_overall_away` if they're visiting,
    `strength_overall_home` if we are) - real FPL's own official FDR
    convention (a single difficulty number per fixture, not split by
    attack/defence - that split only matters for `expected_points()`'s own
    goals model, not the ticker), confirmed against the real research this
    session did into FPL Copilot's ticker. A blank gameweek (no fixture)
    simply produces no entry for that event - callers that need to show the
    gap explicitly should cross-reference `detect_blank_double_gws`, not
    treat a short list as an error."""
    start = from_event if from_event is not None else _reference_event(conn)
    rows = conn.execute(
        "SELECT f.id, f.event, f.team_h, f.team_a, t.short_name AS opp_short, "
        "t.strength_overall_home AS opp_home_strength, t.strength_overall_away AS opp_away_strength "
        "FROM fixtures f JOIN teams t ON t.id = (CASE WHEN f.team_h=? THEN f.team_a ELSE f.team_h END) "
        "WHERE (f.team_h=? OR f.team_a=?) AND f.event >= ? AND f.event < ? ORDER BY f.event",
        (team_id, team_id, team_id, start, start + n_gw),
    ).fetchall()

    entries = []
    for r in rows:
        is_home = r["team_h"] == team_id
        opponent_id = r["team_a"] if is_home else r["team_h"]
        # If we're home, the opponent is travelling (their away strength);
        # if we're away, the opponent is at home (their home strength).
        difficulty = r["opp_away_strength"] if is_home else r["opp_home_strength"]
        entries.append(TickerEntry(
            fixture_id=r["id"], event=r["event"], opponent_team_id=opponent_id, opponent_short=r["opp_short"],
            is_home=is_home, difficulty=difficulty if difficulty else 3,
        ))
    return entries


def _reference_event(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM events WHERE is_next=1 LIMIT 1").fetchone()
    if row is not None:
        return row["id"]
    row = conn.execute("SELECT MIN(id) AS id FROM events WHERE finished=0").fetchone()
    if row is not None and row["id"] is not None:
        return row["id"]
    return 1


def current_live_event(conn: sqlite3.Connection) -> int | None:
    """The event id of a genuinely in-progress fixture right now
    (started=1, finished=0), or None if nothing is live. Deliberately
    independent of events.is_next/is_current - real FPL behavior flips
    is_next to the FOLLOWING gameweek the moment a deadline passes,
    regardless of whether that gameweek's own matches have kicked off or
    finished, since is_next/is_current answer "what's next to plan
    transfers/captaincy for", not "what's being played right now". Those
    coincide during preseason (nothing is live either way) but diverge for
    the entire real GW1 match window: the deadline passes at 17:30, the
    first kickoff isn't until ~19:00, and matches run through the weekend
    while the gameweek's own `finished` flag doesn't flip until bonus is
    confirmed days later - `_reference_event()` would report GW2 as
    "current" for that whole window even though GW1 is what's actually
    live. Live-tracking callers need this function, not `_reference_event`."""
    row = conn.execute(
        "SELECT DISTINCT event FROM fixtures WHERE started=1 AND finished=0 ORDER BY event LIMIT 1"
    ).fetchone()
    return row["event"] if row else None


def live_or_reference_event(conn: sqlite3.Connection) -> int | None:
    """Prefer a genuinely in-progress gameweek over the planning-oriented
    `_reference_event()` - use this for anything that needs "what's live
    right now" (live-bonus, live-watch, the dashboard's Live Tracking
    panel), never for transfer/captaincy/projection planning, which
    correctly wants the next actionable deadline instead."""
    live = current_live_event(conn)
    return live if live is not None else _reference_event(conn)


@dataclass(frozen=True)
class FixtureCountAnomaly:
    event: int
    team_id: int
    team_short_name: str
    kind: str  # "blank" or "double"
    fixture_count: int


def detect_blank_double_gws(conn: sqlite3.Connection, start_event: int, n_gw: int = 5) -> list[FixtureCountAnomaly]:
    """Per-team fixture-count anomalies over [start_event, start_event+n_gw). Extracted
    from the fixture-watch CLI command's inline loop so season-sim (Plan 1b) can reuse
    it without duplicating the query."""
    teams = conn.execute("SELECT id, short_name FROM teams ORDER BY short_name").fetchall()
    anomalies = []
    for event in range(start_event, start_event + n_gw):
        for t in teams:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM fixtures WHERE (team_h=? OR team_a=?) AND event=?",
                (t["id"], t["id"], event),
            ).fetchone()["c"]
            if count == 0:
                anomalies.append(FixtureCountAnomaly(event, t["id"], t["short_name"], "blank", count))
            elif count >= 2:
                anomalies.append(FixtureCountAnomaly(event, t["id"], t["short_name"], "double", count))
    return anomalies


def fixture_window_score(conn: sqlite3.Connection, team_id: int, n_gw: int, from_event: int | None = None) -> FixtureWindow:
    start = from_event if from_event is not None else _reference_event(conn)
    fixture_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM fixtures WHERE (team_h=? OR team_a=?) AND event >= ? AND event < ? ORDER BY event",
            (team_id, team_id, start, start + n_gw),
        ).fetchall()
    ]

    if not fixture_ids:
        return FixtureWindow(team_id, n_gw, 0, 0.0, 0.0, used_fallback=False)

    attack_scores, defence_scores, fallback_flags = [], [], []
    for fid in fixture_ids:
        fd = fixture_difficulty(conn, fid)
        if fd.team_h == team_id:
            attack_scores.append(fd.team_h_attack_difficulty)
            defence_scores.append(fd.team_h_defence_difficulty)
        else:
            attack_scores.append(fd.team_a_attack_difficulty)
            defence_scores.append(fd.team_a_defence_difficulty)
        fallback_flags.append(fd.used_fallback)

    return FixtureWindow(
        team_id=team_id,
        n_gw=n_gw,
        fixture_count=len(fixture_ids),
        avg_attack_difficulty=round(sum(attack_scores) / len(attack_scores), 2),
        avg_defence_difficulty=round(sum(defence_scores) / len(defence_scores), 2),
        used_fallback=any(fallback_flags),
    )
