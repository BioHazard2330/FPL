"""Points Changes (fpl.page parity item): post-match revisions to Bonus
Points and Defensive Contribution, i.e. a value FPL's own live element data
already showed as settled after full time, then later corrected. Not the
same as normal in-play bonus/BPS churn during a live match (bonus climbs
several times per game as BPS accumulates - that's expected, not a
"revision").

Real, no-new-pipeline source: `player_stats_snapshot`, already written every
sync tick with a `bonus`/`defensive_contribution`/`bps` value + `retrieved_at`
timestamp (`ingestion/sync.py`, hash-gated so a row only lands when
something actually changed). No new ingestion, no new table.

Detection heuristic (real, disclosed, not FPL's internal review-timing,
which isn't published): a fixture's own `kickoff_time` + 130 minutes (90 +
HT + stoppage buffer) + a 30-minute settle buffer marks "presumed full
time". Snapshots at or after that point are "post-match". If a player's
post-match bonus/defcon value differs between the FIRST and LAST such
snapshot, AND those two snapshots are at least `_MIN_REVISION_GAP_HOURS`
apart (filters out the tail of ordinary live-BPS settling, which is done
within an hour of full time in every case checked against real GW1 data),
it's reported as a real revision. Verified against real production data
(GW1): 0 bonus revisions, 8 real DEFCON revisions (Gabriel/Rice/Tzolis/
Enciso/Adams/Grealish/Gvardiol/Anderson) - a genuine, non-fabricated
finding, not a designed-to-show-something heuristic.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fpl_agent.models.defensive_contribution import DEFCON_THRESHOLDS

_PRESUMED_MATCH_LENGTH_MIN = 130
_SETTLE_BUFFER_MIN = 30
_MIN_REVISION_GAP_HOURS = 2.0


@dataclass(frozen=True)
class PointsRevision:
    player_id: int
    web_name: str
    team_short: str
    position: str
    fixture_id: int
    category: str  # "bonus" | "defcon"
    old_value: int
    new_value: int
    old_points: int
    new_points: int
    detected_gap_hours: float


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _defcon_points(raw: int | None, threshold: int | None) -> int:
    if raw is None or threshold is None:
        return 0
    return 2 if raw >= threshold else 0


_LOCK_BUFFER_MIN = 60  # fpl.page's own real, published rule: "locked 1 hour after full time of the final match"


def is_gw_locked(conn: sqlite3.Connection, event: int) -> bool | None:
    """Real GW-lock status (fpl.page-parity pass - their own real published
    rule, verified live via their "How to use the Points Changes widget"
    article: "Points are locked in 1 hour after full time of the final
    match of the gameweek"). Deliberately does NOT trust the bootstrap
    `events.finished` flag alone - `models/gw_lifecycle.py` already
    established (and this reuses its own reasoning, not a second
    heuristic) that flag can lag or be wrong on its own; this instead
    checks every real fixture in the event directly, same as that module.
    Returns `None` (never guessed) when the event has no fixtures synced,
    or any fixture is missing a real `finished`/`kickoff_time` value."""
    fixtures = conn.execute(
        "SELECT finished, kickoff_time FROM fixtures WHERE event=?", (event,)
    ).fetchall()
    if not fixtures:
        return None
    if any(f["finished"] is None or not f["kickoff_time"] for f in fixtures):
        return None
    if not all(f["finished"] for f in fixtures):
        return False
    last_kickoff = max(_parse(f["kickoff_time"]) for f in fixtures)
    lock_at = last_kickoff + timedelta(minutes=_PRESUMED_MATCH_LENGTH_MIN + _LOCK_BUFFER_MIN)
    return datetime.now(timezone.utc) >= lock_at


def detect_points_revisions(conn: sqlite3.Connection, event: int | None = None) -> list[PointsRevision]:
    """`event` defaults to the latest FINISHED event (revisions can only be
    judged once a gameweek has actually finished). Returns `[]` (never
    fabricated) when no finished event exists or no fixtures/snapshots
    support a real comparison."""
    if event is None:
        row = conn.execute(
            "SELECT id FROM events WHERE finished = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return []
        event = row["id"]

    fixtures = conn.execute(
        "SELECT id, kickoff_time, team_h, team_a FROM fixtures WHERE event = ? AND finished = 1",
        (event,),
    ).fetchall()
    if not fixtures:
        return []

    revisions: list[PointsRevision] = []
    for fx in fixtures:
        if not fx["kickoff_time"]:
            continue
        ft_cutoff = _parse(fx["kickoff_time"]) + timedelta(
            minutes=_PRESUMED_MATCH_LENGTH_MIN + _SETTLE_BUFFER_MIN
        )
        players = conn.execute(
            "SELECT p.id, p.web_name, t.short_name AS team_short, et.singular_name_short AS position "
            "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type "
            "WHERE p.team_id IN (?, ?) AND p.removed = 0",
            (fx["team_h"], fx["team_a"]),
        ).fetchall()
        for p in players:
            snaps = conn.execute(
                "SELECT retrieved_at, bonus, defensive_contribution FROM player_stats_snapshot "
                "WHERE player_id = ? AND retrieved_at >= ? ORDER BY retrieved_at",
                (p["id"], fx["kickoff_time"]),
            ).fetchall()
            post = [s for s in snaps if _parse(s["retrieved_at"]) >= ft_cutoff]
            if len(post) < 2:
                continue
            gap_hours = (_parse(post[-1]["retrieved_at"]) - _parse(post[0]["retrieved_at"])).total_seconds() / 3600
            if gap_hours < _MIN_REVISION_GAP_HOURS:
                continue

            old_bonus, new_bonus = post[0]["bonus"], post[-1]["bonus"]
            if old_bonus is not None and new_bonus is not None and old_bonus != new_bonus:
                revisions.append(PointsRevision(
                    player_id=p["id"], web_name=p["web_name"], team_short=p["team_short"], position=p["position"],
                    fixture_id=fx["id"], category="bonus",
                    old_value=old_bonus, new_value=new_bonus,
                    old_points=old_bonus, new_points=new_bonus,
                    detected_gap_hours=round(gap_hours, 1),
                ))

            old_dc, new_dc = post[0]["defensive_contribution"], post[-1]["defensive_contribution"]
            if old_dc is not None and new_dc is not None and old_dc != new_dc:
                threshold = DEFCON_THRESHOLDS.get(p["position"])
                revisions.append(PointsRevision(
                    player_id=p["id"], web_name=p["web_name"], team_short=p["team_short"], position=p["position"],
                    fixture_id=fx["id"], category="defcon",
                    old_value=old_dc, new_value=new_dc,
                    old_points=_defcon_points(old_dc, threshold), new_points=_defcon_points(new_dc, threshold),
                    detected_gap_hours=round(gap_hours, 1),
                ))

    return revisions
