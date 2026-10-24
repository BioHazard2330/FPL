"""When an unavailable player is likely to be back, by match.

Until 2026-10-25 a player flagged injured or suspended was projected at zero minutes for every gameweek in the window,
whatever the news said: a one-week knock sold the player for the whole horizon, and a returner a manager could buy for his
second gameweek back was worth nothing. The flag is a statement about the next match; the news text and FotMob's team sheets
say more, and the stored status history says how long spells like this one last.

Three sources, in order of authority:
1. FPL's own news: "Expected back 31 Oct", "Suspended until 7 Nov" (official, dated).
2. FotMob's `unavailable` list, which carries an expected-return phrase when FPL says "Unknown return date" ("About a
   week", "Early November 2026"). Month phrases are read as the 5th, 15th or 25th.
3. Neither gives a date: the Kaplan-Meier survival curve of this database's own injury spells (status changes in
   `change_events`; spells still open are censored), conditioned on how long the spell has already lasted.

Assumptions, none of them fitted (no history of news text exists to fit a stated-date hit rate against; this module's
inputs are stored from now on in `match_unavailable`):
- A stated date is met 80% of the time (`ON_DATE_PROBABILITY`), then the player's own returning-after-absence minutes
  distribution applies on top. Before the date he is 5% (`BEFORE_DATE_PROBABILITY`).
- A FotMob phrase is read less strictly: 60% from its midpoint plus a week, 5% more than a week before it.
- A player marked unavailable (loan, left the club) is zero throughout.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

ON_DATE_PROBABILITY = 0.8
BEFORE_DATE_PROBABILITY = 0.05
FOTMOB_ON_DATE_PROBABILITY = 0.6
FLOOR_PROBABILITY = 0.02
FOTMOB_FRESH_DAYS = 10

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_NEWS_DATE = re.compile(r"(?:expected back|suspended until|back on|return(?:ing)? on)\s+(\d{1,2})\s+([A-Za-z]{3})", re.I)
_FOTMOB_MONTH = re.compile(r"^(early|mid|late)\s+([A-Za-z]+)\s+(\d{4})$", re.I)
_FOTMOB_PART_DAY = {"early": 5, "mid": 15, "late": 25}


@dataclass(frozen=True)
class ReturnForecast:
    probability: float
    basis: str
    detail: str
    expected_date: str | None = None


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_news_date(news: str | None, now: datetime) -> datetime | None:
    """The date FPL's news line gives, in the next 12 months. "Unknown return date" gives None."""
    if not news:
        return None
    m = _NEWS_DATE.search(news)
    if m is None:
        return None
    month = _MONTHS.get(m.group(2)[:3].lower())
    if month is None:
        return None
    now = _aware(now)
    year = now.year
    try:
        date = datetime(year, month, int(m.group(1)), tzinfo=timezone.utc)
    except ValueError:
        return None
    if date < now - timedelta(days=60):
        date = date.replace(year=year + 1)
    return date


def parse_fotmob_return(text: str | None, now: datetime) -> datetime | None:
    """FotMob's expected-return phrase as a date; "Doubtful" and anything unrecognised give None."""
    if not text:
        return None
    now = _aware(now)
    t = text.strip()
    low = t.lower()
    if low == "about a week":
        return now + timedelta(days=7)
    if low == "back in training":
        return now + timedelta(days=5)
    if low.startswith("about "):
        m = re.match(r"about (\d+) (day|week|month)s?", low)
        if m:
            unit = {"day": 1, "week": 7, "month": 30}[m.group(2)]
            return now + timedelta(days=int(m.group(1)) * unit)
    m = _FOTMOB_MONTH.match(t)
    if m:
        month = _MONTHS.get(m.group(2)[:3].lower())
        if month:
            return datetime(int(m.group(3)), month, _FOTMOB_PART_DAY[m.group(1).lower()], tzinfo=timezone.utc)
    return None


_spell_cache: dict[int, tuple[sqlite3.Connection, int, dict]] = {}


def _spells(conn: sqlite3.Connection, now: datetime) -> dict:
    """Injury-spell durations in days from the stored status changes: {"done": [...], "open": [...]}, per start state."""
    key = id(conn)
    n = conn.execute("SELECT COUNT(*) AS n FROM change_events WHERE event_type='status_change'").fetchone()["n"]
    cached = _spell_cache.get(key)
    if cached is not None and cached[0] is conn and cached[1] == n:
        return cached[2]
    rows = conn.execute(
        "SELECT entity_id AS pid, old_value AS o, new_value AS n, detected_at AS t FROM change_events "
        "WHERE event_type='status_change' AND entity='player' ORDER BY entity_id, detected_at"
    ).fetchall()
    out = {"i": {"done": [], "open": []}, "s": {"done": [], "open": []}}
    now = _aware(now)
    by_player: dict[int, list] = {}
    for r in rows:
        by_player.setdefault(r["pid"], []).append(r)
    for events in by_player.values():
        state, start = None, None
        for e in events:
            t = _aware(datetime.fromisoformat(e["t"]))
            if e["n"] in ("i", "s") and state is None:
                state, start = e["n"], t
            elif state is not None and e["n"] in ("a", "d"):
                out[state]["done"].append(max((t - start).total_seconds() / 86400, 0.1))
                state, start = None, None
            elif state is not None and e["n"] in ("i", "s"):
                state = e["n"]
        if state is not None:
            out[state]["open"].append(max((now - start).total_seconds() / 86400, 0.1))
    _spell_cache[key] = (conn, n, out)
    return out


def _survival(done: list[float], open_: list[float], t: float) -> float:
    """Kaplan-Meier probability that a spell lasts beyond `t` days."""
    s = 1.0
    for d in sorted(set(done)):
        if d > t:
            break
        at_risk = sum(1 for x in done if x >= d) + sum(1 for x in open_ if x >= d)
        ended = sum(1 for x in done if x == d)
        if at_risk:
            s *= 1 - ended / at_risk
    return s


def spell_return_probability(conn: sqlite3.Connection, kind: str, elapsed_days: float, ahead_days: float, now: datetime) -> float | None:
    """Chance a spell of `kind` ('i' or 's') that has run `elapsed_days` has ended `ahead_days` from now; None when the
    database holds too few spells to say."""
    spells = _spells(conn, now)[kind if kind in ("i", "s") else "i"]
    if len(spells["done"]) < 8:
        return None
    s0 = _survival(spells["done"], spells["open"], elapsed_days)
    if s0 <= 0:
        return None
    s1 = _survival(spells["done"], spells["open"], elapsed_days + ahead_days)
    return max(0.0, min(1.0, 1 - s1 / s0))


def _elapsed_days(conn: sqlite3.Connection, player_id: int, now: datetime) -> float:
    row = conn.execute(
        "SELECT detected_at FROM change_events WHERE event_type='status_change' AND entity='player' AND entity_id=? "
        "AND new_value IN ('i','s') ORDER BY detected_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT MIN(detected_at) AS t FROM change_events WHERE event_type='status_change'").fetchone()
        if row is None or row["t"] is None:
            return 0.0
        started = _aware(datetime.fromisoformat(row["t"]))
    else:
        started = _aware(datetime.fromisoformat(row["detected_at"]))
    return max((_aware(now) - started).total_seconds() / 86400, 0.0)


def _fotmob_text(conn: sqlite3.Connection, player_id: int, now: datetime) -> str | None:
    try:
        row = conn.execute(
            "SELECT expected_return, retrieved_at FROM match_unavailable WHERE player_id=? "
            "ORDER BY retrieved_at DESC LIMIT 1",
            (player_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or not row["expected_return"]:
        return None
    age = _aware(now) - _aware(datetime.fromisoformat(row["retrieved_at"]))
    return row["expected_return"] if age <= timedelta(days=FOTMOB_FRESH_DAYS) else None


def return_forecast(
    conn: sqlite3.Connection, player_id: int, kickoff: datetime, now: datetime | None = None,
) -> ReturnForecast | None:
    """The chance this player is available for a match at `kickoff`, or None when his current status gives no reason to
    forecast (fit, or merely doubtful: those keep the flat availability discount)."""
    now = _aware(now or datetime.now(timezone.utc))
    kickoff = _aware(kickoff)
    player = conn.execute("SELECT status, news FROM players WHERE id=?", (player_id,)).fetchone()
    if player is None:
        return None
    status = player["status"]
    if status == "u":
        return ReturnForecast(0.0, "unavailable", "marked unavailable (left the club or on loan)")
    if status not in ("i", "s"):
        return None

    dated = parse_news_date(player["news"], now)
    if dated is not None:
        if kickoff < dated + timedelta(days=1):
            return ReturnForecast(BEFORE_DATE_PROBABILITY, "fpl_date", f"out until {dated:%d %b} per FPL", dated.date().isoformat())
        return ReturnForecast(ON_DATE_PROBABILITY, "fpl_date", f"due back {dated:%d %b} per FPL", dated.date().isoformat())

    phrase = _fotmob_text(conn, player_id, now)
    est = parse_fotmob_return(phrase, now)
    if est is not None:
        if kickoff < est - timedelta(days=7):
            return ReturnForecast(BEFORE_DATE_PROBABILITY, "fotmob_date", f"FotMob expects {phrase}", est.date().isoformat())
        if kickoff >= est + timedelta(days=7):
            return ReturnForecast(FOTMOB_ON_DATE_PROBABILITY, "fotmob_date", f"FotMob expects {phrase}", est.date().isoformat())
        frac = (kickoff - (est - timedelta(days=7))).total_seconds() / (14 * 86400)
        p = BEFORE_DATE_PROBABILITY + frac * (FOTMOB_ON_DATE_PROBABILITY - BEFORE_DATE_PROBABILITY)
        return ReturnForecast(p, "fotmob_date", f"FotMob expects {phrase}", est.date().isoformat())

    ahead = max((kickoff - now).total_seconds() / 86400, 0.0)
    km = spell_return_probability(conn, status, _elapsed_days(conn, player_id, now), ahead, now)
    if km is None:
        return None
    return ReturnForecast(max(km, FLOOR_PROBABILITY), "spell_history", f"{ahead:.0f} days ahead, from how long such spells have lasted")
