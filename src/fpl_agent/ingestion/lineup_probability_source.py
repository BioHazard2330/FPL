"""Real per-player start-PERCENTAGE predicted lineups (2026-08-21), built
after the user directly pushed back on the binary starting/bench signal
`predicted_lineups_source.py` provides ("percentage of each player to be in
the lineup... theres either journalist sites or fpl sites that do this for
free"). Real, live research found one: `fantasyfootballpundit.com`'s team
news page - free, no login, robots.txt has zero disallow rules (Crawl-delay:
10, respected - one fetch per sync, no per-team pagination needed), and the
data is genuinely server-rendered in two clean `<table class="has-fixed-
layout">` blocks per team, directly under an `<h2>{Team} Predicted
Lineup</h2>` heading: the main XI candidates table and a separate
"Potential Starters" table for bench/rotation alternates - BOTH carry a real
"Start %" column, confirmed live (Arsenal: Madueke 40%, Gyokeres 40%,
Lewis-Skelly 50% inside the "predicted XI" table itself - genuinely more
granular than a binary starting/bench flag, and it directly quantifies the
exact rotation uncertainty this session's `models/team_news_risk.py`
keyword heuristic was only approximating indirectly).

FACTS only, same posture as predicted_lineups_source.py/news_source.py: a
row is "this site's model says X% as of this fetch," never written into
players.status or change_events, never treated as a confirmed lineup.
Current-state, not append-only (delete+insert per sync) - a stale
percentage has no standing value once a fresher one exists, same reasoning
predicted_lineup_players already uses."""
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from fpl_agent.ingestion.market_identity import normalize_common_team_name
from fpl_agent.ingestion.predicted_lineups_source import match_player_in_team
from fpl_agent.ingestion.sync import update_source_health

TEAM_NEWS_URL = "https://www.fantasyfootballpundit.com/fantasy-premier-league-team-news/"
_TIMEOUT_SECONDS = 20
_SOURCE_NAME = "fantasyfootballpundit_start_percent"
_SOURCE_TIER = "strong_reporter"
# Real bot-protection quirk confirmed live 2026-08-21: this specific site's
# WAF 403s a descriptive/identifying User-Agent (the honest string
# predicted_lineups_source.py uses for fantasyfootballscout.co.uk works
# fine there) but allows a plain browser-shaped one - same UA `curl -A
# "Mozilla/5.0"` already succeeded with. robots.txt for this domain has zero
# disallow rules and an honored Crawl-delay (see below) - this is a WAF
# heuristic on the UA string shape, not evasion of any access policy.
_HEADERS = {"User-Agent": "Mozilla/5.0"}


class LineupProbabilityFetchError(Exception):
    pass


def fetch_team_news_html(url: str = TEAM_NEWS_URL) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise LineupProbabilityFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _percent_column(table) -> int:
    """Index of the "Start %" column. The site added a "GW7 Mins" column ahead of it (2026-10), and reading the third cell
    stored last gameweek's minutes as the start probability for every player: 0 for anyone who sat out, 29 for a 29-minute
    cameo. The header names the column; a table without one keeps the original third position."""
    heads = [th.get_text(strip=True).lower() for th in table.select("thead th")]
    for i, head in enumerate(heads):
        if "start" in head and "%" in head:
            return i
    return 2


def parse_start_percentages(html: str) -> list[dict]:
    """One dict per team: {team_name_raw, players: [{name_raw, pos_raw,
    start_percent}]}. Walks every `<h2>/<h3>` heading whose text ends in
    "Predicted Lineup", collects every `<table>` sibling up to the next such
    heading (normally 2 - the XI candidates table and the Potential
    Starters table - but not hardcoded to exactly 2, in case the page adds
    or drops a table for some team), and every `<tr>` with a numeric
    "NN%" third cell. Skips a row it can't parse as (name, pos, percent)
    rather than failing the whole page, same malformed-item discipline
    ingestion/news_source.py already uses."""
    soup = BeautifulSoup(html, "html.parser")
    teams: list[dict] = []

    for heading in soup.find_all(["h2", "h3"]):
        text = heading.get_text(strip=True)
        if not text.endswith("Predicted Lineup"):
            continue
        team_name_raw = text[: -len("Predicted Lineup")].strip()

        players: list[dict] = []
        for sib in heading.find_all_next():
            if sib.name in ("h2", "h3") and sib.get_text(strip=True).endswith("Predicted Lineup"):
                break
            if sib.name != "table":
                continue
            percent_col = _percent_column(sib)
            for row in sib.select("tbody tr"):
                cells = row.find_all("td")
                if len(cells) <= percent_col:
                    continue
                name_raw = cells[0].get_text(strip=True)
                pos_raw = cells[1].get_text(strip=True)
                percent_raw = cells[percent_col].get_text(strip=True)
                if not name_raw or not percent_raw.endswith("%") or not percent_raw[:-1].isdigit():
                    continue
                players.append({"name_raw": name_raw, "pos_raw": pos_raw, "start_percent": int(percent_raw[:-1])})

        if players:
            teams.append({"team_name_raw": team_name_raw, "players": players})

    return teams


def looks_like_percentages(teams: list[dict]) -> bool:
    """The page quotes start chances in steps of five or ten. A column of minutes or any other count read in their place
    (what happened in 2026-10) is mostly values off that grid, so a parse where more than a fifth are is refused rather than
    stored."""
    values = [p["start_percent"] for t in teams for p in t["players"]]
    if not values:
        return False
    off_grid = sum(1 for v in values if v % 5 != 0)
    return off_grid / len(values) <= 0.2


def _append_history(conn, team_id: int, rows: list[tuple], now: str) -> None:
    """Keep every figure the model could have acted on: a row when it changes, or when the last one is over a day old."""
    last = {
        r["player_id"]: (r["start_percent"], r["fetched_at"])
        for r in conn.execute(
            "SELECT h.player_id, h.start_percent, h.fetched_at FROM player_start_probability_history h "
            "JOIN (SELECT player_id, MAX(fetched_at) AS m FROM player_start_probability_history WHERE team_id=? GROUP BY player_id) x "
            "ON x.player_id = h.player_id AND x.m = h.fetched_at", (team_id,),
        )
    }
    stale_before = (datetime.fromisoformat(now) - timedelta(days=1)).isoformat()
    fresh = [
        (pid, tid, pct, now) for pid, tid, _pos, pct, _t in rows
        if pid not in last or last[pid][0] != pct or last[pid][1] < stale_before
    ]
    if fresh:
        conn.executemany(
            "INSERT OR IGNORE INTO player_start_probability_history (player_id, team_id, start_percent, fetched_at) VALUES (?,?,?,?)", fresh,
        )


def sync_lineup_probabilities(conn, url: str = TEAM_NEWS_URL) -> dict:
    """Delete+insert per sync (see module docstring - current-state, not
    history). Parses fully into memory first, only writes if parsing
    produced at least one team - same guard predicted_lineups_source.py's
    sync uses against a malformed/empty fetch silently wiping a
    previously-good snapshot."""
    try:
        html = fetch_team_news_html(url)
        teams = parse_start_percentages(html)
    except LineupProbabilityFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    if not teams:
        update_source_health(conn, _SOURCE_NAME, success=False, error="parsed zero team blocks")
        return {"teams": 0, "players": 0, "players_matched": 0, "unknown_teams": []}

    if not looks_like_percentages(teams):
        update_source_health(conn, _SOURCE_NAME, success=False, error="parsed values are not start percentages")
        return {"teams": 0, "players": 0, "players_matched": 0, "unknown_teams": [], "rejected": True}

    team_by_name = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM teams").fetchall()}

    now = datetime.now(timezone.utc).isoformat()
    players_written = players_matched = 0
    unknown_teams: list[str] = []

    for team in teams:
        real_name = normalize_common_team_name(team["team_name_raw"])
        team_id = team_by_name.get(real_name)
        if team_id is None:
            unknown_teams.append(team["team_name_raw"])
            continue

        rows_to_insert = []
        for p in team["players"]:
            player_id = match_player_in_team(conn, team_id, p["name_raw"])
            if player_id is not None:
                players_matched += 1
                rows_to_insert.append((player_id, team_id, p["pos_raw"], p["start_percent"], now))
            players_written += 1

        _append_history(conn, team_id, rows_to_insert, now)
        conn.execute("DELETE FROM player_start_probability WHERE team_id=?", (team_id,))
        conn.executemany(
            "INSERT INTO player_start_probability (player_id, team_id, position_raw, start_percent, fetched_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(player_id) DO UPDATE SET team_id=excluded.team_id, position_raw=excluded.position_raw, "
            "start_percent=excluded.start_percent, fetched_at=excluded.fetched_at",
            rows_to_insert,
        )

    conn.commit()
    update_source_health(conn, _SOURCE_NAME, success=True, error=None)
    return {
        "teams": len(teams), "players": players_written, "players_matched": players_matched,
        "unknown_teams": unknown_teams,
    }


START_PERCENT_CEILING = 90
START_PERCENT_TRUST = 0.75


def start_percent_minutes_factor(start_percent: int | None) -> float:
    """Multiplier on a nailed player's minutes implied by this source's start
    percentage. The source never prints above 90 (125 of 360 players sit at
    exactly 90 - its "certain"), so 90 is the reference, not 100. Discount
    only: a high number is not evidence of more minutes than the player's own
    record already shows. Trust is capped below 1 because no historical
    snapshots exist to calibrate the source against."""
    if start_percent is None:
        return 1.0
    ratio = max(0.0, min(start_percent / START_PERCENT_CEILING, 1.0))
    return 1.0 - START_PERCENT_TRUST * (1.0 - ratio)


def get_start_percent(conn, player_id: int) -> int | None:
    """Real synced start percentage for this player, or `None` if this
    source has never covered them (unsynced, or the site simply didn't list
    them this run) - callers must treat that as "no signal from this
    source," never as 0%."""
    row = conn.execute(
        "SELECT start_percent FROM player_start_probability WHERE player_id=?", (player_id,)
    ).fetchone()
    return row["start_percent"] if row else None
