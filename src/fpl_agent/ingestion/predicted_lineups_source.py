"""Tier 2-4 (strong-reporter) predicted-lineup ingestion.

Closes CLAUDE.md's long-documented gap: "predicted lineups (section 47) - no
reliable free, no-signup source found" (Phase 6/9, reaffirmed in Pillar 2
Plan 2a). Re-investigated 2026-08-21 after the user pushed back on squad
picks the model rated well but the crowd doesn't own - checked two named
sites the user surfaced first, both rejected for real reasons before
building anything: fpl.team/predicted-lineups is real but most lineups sit
behind a "Become a seasoned veteran" paywall (only 2 teams free) - scraping
around that is circumventing a paywall, not finding a free source. fplreview.com
returns HTTP 403. fantasyfootballscout.co.uk/team-news/ was checked and is
genuinely different: free, no login, robots.txt has zero disallow rules for
any user-agent, and the predicted-XI/injury data is present in the static
server-rendered HTML (confirmed live - no JS rendering/Playwright needed).

FACTS only, same posture as ingestion/news_source.py: a row is "this site's
predicted XI says this, as of this fetch" - never written into players.status
or change_events, never treated as confirmed. Player-name matching is a
best-effort heuristic (see match_player_in_team below), scoped to the team
the row was published under (much lower collision risk than a leaguewide
name match) - still never a confirmed identification.
"""
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from fpl_agent.ingestion.sync import update_source_health

TEAM_NEWS_URL = "https://www.fantasyfootballscout.co.uk/team-news/"
_TIMEOUT_SECONDS = 20
_SOURCE_NAME = "fantasyfootballscout_team_news"
_SOURCE_TIER = "strong_reporter"
# A single, honest, identifying User-Agent - not rotated to impersonate
# different visitors. robots.txt permits every user-agent equally, so this
# is politeness (many sites reject the bare python-requests default UA), not
# evasion of anything.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; fpl-agent research tool; +local, non-commercial)"}
_MIN_NAME_LENGTH = 3


class PredictedLineupFetchError(Exception):
    pass


def fetch_team_news_html(url: str = TEAM_NEWS_URL) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise PredictedLineupFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def parse_team_news_html(html: str) -> list[dict]:
    """One dict per team: {team_code, formation, next_match_text, latest_news,
    players: [{name_raw, status, lineup_row, doubt_percent}]}. team_code is the
    site's lowercase 3-letter code (e.g. "ars") - matches teams.short_name
    uppercased, confirmed live across all 20 real current teams. Skips a team
    block entirely (rather than emitting a partial/malformed one) if it has no
    data-team-code, matching news_source.py's own "malformed item - skip, don't
    fail the whole feed" discipline."""
    soup = BeautifulSoup(html, "html.parser")
    teams = []

    for item in soup.select("li.team-news-item[data-team-code]"):
        code = item.get("data-team-code")
        if not code:
            continue

        next_match_el = item.select_one("div.next-match")
        next_match_text = None
        if next_match_el:
            next_match_text = next_match_el.get_text(" ", strip=True).removeprefix("Next Match:").strip()

        formation_div = item.select_one("div.scout-picks")
        formation = None
        players: list[dict] = []
        if formation_div is not None:
            formation_classes = [c for c in formation_div.get("class", []) if c.startswith("formation-")]
            if formation_classes:
                formation = formation_classes[0].removeprefix("formation-")

            for row in formation_div.select("ul[class^=row-]"):
                row_class = next((c for c in row.get("class", []) if c.startswith("row-")), None)
                lineup_row = int(row_class.removeprefix("row-")) if row_class else None
                for li in row.select("li"):
                    name_el = li.select_one("span.player-name")
                    if name_el is None:
                        continue
                    players.append({
                        "name_raw": name_el.get_text(strip=True),
                        "status": "starting",
                        "lineup_row": lineup_row,
                        "doubt_percent": None,
                    })

        story_parts = item.select_one("ul.story-parts")
        latest_news = None
        if story_parts is not None:
            status_by_label = {"Out:": "out", "Doubts:": "doubt", "Banned:": "banned"}
            for header_li in story_parts.select("li.headers"):
                strong = header_li.select_one("strong")
                if strong is None:
                    continue  # a real, observed empty placeholder header - skip, don't crash
                status = status_by_label.get(strong.get_text(strip=True))
                if status is None:
                    continue
                for player_li in header_li.select("ul.players li"):
                    text = player_li.get_text(" ", strip=True)
                    doubt_percent = None
                    if status == "doubt":
                        # "Bruno Guimarães 75%" - the trailing percent is the
                        # site's own published fitness-doubt figure, real (not
                        # derived by this project), so it's kept but the name
                        # is separated out for matching.
                        parts = text.rsplit(" ", 1)
                        if len(parts) == 2 and parts[1].endswith("%") and parts[1][:-1].isdigit():
                            text, doubt_percent = parts[0], int(parts[1][:-1])
                    players.append({
                        "name_raw": text, "status": status,
                        "lineup_row": None, "doubt_percent": doubt_percent,
                    })

            for li in story_parts.select("li"):
                p = li.select_one("p")
                strong = p.select_one("strong") if p else None
                if strong and strong.get_text(strip=True).startswith("Latest News"):
                    latest_news = p.get_text(" ", strip=True).removeprefix(strong.get_text(strip=True)).strip()
                    break

        teams.append({
            "team_code": code, "formation": formation,
            "next_match_text": next_match_text, "latest_news": latest_news,
            "players": players,
        })

    return teams


_FOLD_TRANSLITERATION_MAP: dict[str, str] = {
    # Real, confirmed bug fixed 2026-09-07 (Phase 7.4 Part 1/2 forensic
    # audit): the NFKD-strip-combining-marks technique below only handles
    # TRUE diacritics (a base letter + a separately-encoded combining mark,
    # e.g. "é" = "e" + U+0301) - it does nothing for Latin-Extended letters
    # that are their own distinct Unicode code points with no combining-mark
    # decomposition, confirmed directly in Python: unicodedata.normalize(
    # "NFKD", "Ø") ("Ø") returns "Ø" unchanged, not "O" - so
    # `_fold("Ødegaard")` was silently returning "ødegaard" (still carrying
    # the real Ø shape, just lowercased), never "odegaard". This is the
    # REAL, confirmed reason a real, prominent, current squad player
    # (Ødegaard) has NEVER ONCE resolved in `player_match_stats_history`
    # in ANY season including the live one (found live via Phase 7.4's own
    # `data_fidelity.py` diagnostic, which flagged him "no_team_anchor" in
    # every one of 5 real backtestable seasons) - Understat's own raw name
    # text uses the plain "Odegaard" ASCII transliteration, which this
    # fold could never have matched against the real "Ødegaard" stored in
    # `players`, in EITHER direction, regardless of how many times a
    # historical re-fetch repair ran. A real, disclosed, non-exhaustive
    # table of the Latin-Extended letters this project has actually
    # encountered or reasonably expects in real European football names -
    # standard transliteration conventions, not invented ones.
    "ø": "o", "æ": "ae", "đ": "d", "ß": "ss", "œ": "oe", "ł": "l", "ı": "i", "þ": "th", "ð": "d",
}


def _fold(text: str) -> str:
    """Strip diacritics + lowercase - the site's raw text and our own DB disagree
    on accents often enough to matter ("Odegaard" vs "Ødegaard", "Gyokeres" vs
    "Gyökeres", "Muharemovic" vs "Muharemović" - all real, confirmed live misses
    before this was added). NFKD-strip-combining-marks alone only reaches TRUE
    diacritics (see `_FOLD_TRANSLITERATION_MAP`'s own docstring for the real,
    confirmed gap it closes) - applied first so a letter like "Ø" is already a
    plain "o" before the NFKD pass runs (order doesn't matter for the letters
    in the map today, none of them carry a real separate combining mark, but
    doing the table first keeps the two passes independent and each easy to
    reason about alone)."""
    lowered = text.lower()
    translit = "".join(_FOLD_TRANSLITERATION_MAP.get(c, c) for c in lowered)
    return "".join(
        c for c in unicodedata.normalize("NFKD", translit) if not unicodedata.combining(c)
    )


def _last_word_match(rows, name_folded: str) -> int | None:
    """Real, collision-safe surname signal - `rows`' own `second_name`
    whose LAST word matches the raw text's own last word. Returns the
    match only when EXACTLY ONE real teammate matches - two real teammates
    sharing a last-name word is a real, genuine ambiguity (a surname
    collision, same class of risk Part 2 explicitly names), honestly
    reported as `None` rather than guessed at by iteration order."""
    name_last_word = name_folded.split()[-1] if name_folded.split() else ""
    if not name_last_word:
        return None
    matches = [
        row["id"] for row in rows
        if row["second_name"] and _fold(row["second_name"]).split()[-1:] == [name_last_word]
    ]
    return matches[0] if len(matches) == 1 else None


def match_player_in_team(conn, team_id: int, name_raw: str) -> int | None:
    """Scoped to the one team this row was published under - far lower collision
    risk than news_source.py's leaguewide match_players (which is why this is a
    separate, simpler function rather than reusing that one). Three fallback
    passes, each only tried if the previous found nothing: (1) our web_name
    appearing in their text, (2) their text appearing in our second_name -
    both diacritic-folded, since the site's own name text varies in form
    ("Raya Martin", "White", "Gabriel Magalhães") and accents against our
    web_name/second_name, (3) their text's LAST word matching our second_name's
    last word - catches a site listing a full "Bruno Fernandes" against a
    second_name of "Borges Fernandes" (real, confirmed live miss otherwise)."""
    name_folded = _fold(name_raw)
    rows = conn.execute(
        "SELECT id, web_name, second_name FROM players WHERE team_id=? AND removed=0", (team_id,)
    ).fetchall()

    # Real, collision-safe surname signal, computed up front so pass 1 (below)
    # can cross-check against it - see `_last_word_match`'s own docstring.
    last_word_id = _last_word_match(rows, name_folded)

    # Real bug found 2026-08-21 (ingestion/lineup_probability_source.py's new
    # source exposed it): a short web_name can be a substring of a genuinely
    # DIFFERENT teammate's raw name - "Gabriel" (Magalhaes) is a substring of
    # the raw text "Gabriel Martinelli" (a separate real player) - so a
    # first-match-wins scan silently misattributed Martinelli's real data to
    # Gabriel. Fixed with "maximal munch": prefer the LONGEST matching
    # web_name/second_name across the whole pass, not whichever row the
    # iteration order happens to hit first - a more specific (longer) match
    # is never wrong to prefer over a shorter one that also happens to fit.
    best_id, best_len = None, -1
    for row in rows:
        if row["web_name"] and len(row["web_name"]) >= _MIN_NAME_LENGTH and _fold(row["web_name"]) in name_folded:
            if len(row["web_name"]) > best_len:
                best_id, best_len = row["id"], len(row["web_name"])
    if best_id is not None:
        # Real, confirmed bug fixed 2026-09-07 (Phase 7.4 Part 1/2 forensic
        # audit) - a SHORT web_name that is really just a common bare FIRST
        # name (e.g. "Gabriel") is a real substring of MANY different real
        # players' full names sharing that first name (e.g. "Gabriel Jesus",
        # a real, different teammate) - "maximal munch" alone doesn't catch
        # this when the TRUE player's own web_name has no textual overlap
        # with the raw text at all (e.g. "G.Jesus" vs "Gabriel Jesus"), so
        # the short, wrong match wins uncontested. Confirmed live: 63 real,
        # distinct Understat player ids across a single real historical
        # season had all been silently merged into Gabriel Magalhães'
        # player_id via exactly this path - including one real match
        # showing 4 goals/6 shots/2.16xG attributed to a centre-back, a
        # real, physically implausible tell. Cross-checked against the
        # independent, collision-safe surname signal above: only override
        # pass 1's own answer when that signal is unambiguous (exactly one
        # real teammate) AND disagrees with pass 1 - trusting the more
        # specific real surname match over a bare first-name coincidence.
        if last_word_id is not None and last_word_id != best_id:
            return last_word_id
        return best_id

    best_id, best_len = None, -1
    for row in rows:
        if row["second_name"] and len(row["second_name"]) >= _MIN_NAME_LENGTH and name_folded in _fold(row["second_name"]):
            if len(row["second_name"]) > best_len:
                best_id, best_len = row["id"], len(row["second_name"])
    if best_id is not None:
        return best_id

    return last_word_id


def sync_predicted_lineups(conn, url: str = TEAM_NEWS_URL) -> dict:
    """Delete+insert per sync (see migration 0019's docstring for why this is
    current-state, not append-only history). Parses the whole page fully into
    memory FIRST, only writes if parsing produced at least one team - guards
    against a malformed/empty fetch silently wiping a previously-good snapshot,
    same lesson eo_sample.py's real force=True bug already taught this project
    (CLAUDE.md, Pillar 1 Plan 1c: only issue the DELETE inside the same
    conditional block as the insert+commit)."""
    try:
        html = fetch_team_news_html(url)
        teams = parse_team_news_html(html)
    except PredictedLineupFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    if not teams:
        update_source_health(conn, _SOURCE_NAME, success=False, error="parsed zero team blocks")
        return {"teams": 0, "players": 0, "players_matched": 0, "unknown_team_codes": []}

    team_by_short = {
        row["short_name"].lower(): row["id"]
        for row in conn.execute("SELECT id, short_name FROM teams").fetchall()
    }

    now = datetime.now(timezone.utc).isoformat()
    players_written = players_matched = 0
    unknown_team_codes = []

    for team in teams:
        team_id = team_by_short.get(team["team_code"])
        if team_id is None:
            unknown_team_codes.append(team["team_code"])
            continue

        conn.execute("DELETE FROM predicted_lineup_players WHERE team_id=?", (team_id,))
        conn.execute(
            "INSERT INTO predicted_lineup_teams (team_id, formation, next_match_text, latest_news, "
            "source, source_tier, fetched_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(team_id) DO UPDATE SET formation=excluded.formation, "
            "next_match_text=excluded.next_match_text, latest_news=excluded.latest_news, "
            "source=excluded.source, source_tier=excluded.source_tier, fetched_at=excluded.fetched_at",
            (team_id, team["formation"], team["next_match_text"], team["latest_news"],
             _SOURCE_NAME, _SOURCE_TIER, now),
        )

        for p in team["players"]:
            player_id = match_player_in_team(conn, team_id, p["name_raw"])
            if player_id is not None:
                players_matched += 1
            conn.execute(
                "INSERT INTO predicted_lineup_players (team_id, player_id, player_name_raw, "
                "predicted_status, lineup_row, doubt_percent, fetched_at) VALUES (?,?,?,?,?,?,?)",
                (team_id, player_id, p["name_raw"], p["status"], p["lineup_row"], p["doubt_percent"], now),
            )
            players_written += 1

    conn.commit()
    update_source_health(conn, _SOURCE_NAME, success=True, error=None)
    return {
        "teams": len(teams) - len(unknown_team_codes), "players": players_written,
        "players_matched": players_matched, "unknown_team_codes": unknown_team_codes,
    }


def get_predicted_lineup_for_squad(conn, player_ids: list[int]) -> dict[int, dict]:
    """Latest predicted-lineup read for a specific set of squad player ids -
    what the dashboard/CLI actually want, not a leaguewide dump. Returns
    {player_id: {"status": ..., "team_short": ..., "doubt_percent": ...}} -
    a player id absent from the dict means no row from the latest sync
    matched them (unsynced, or the site simply didn't list them that run) -
    callers must treat that as "no signal," never as "confirmed out.\""""
    if not player_ids:
        return {}
    placeholders = ",".join("?" * len(player_ids))
    rows = conn.execute(
        f"SELECT plp.player_id, plp.predicted_status, plp.doubt_percent, t.short_name AS team_short "
        f"FROM predicted_lineup_players plp JOIN teams t ON t.id = plp.team_id "
        f"WHERE plp.player_id IN ({placeholders})",
        player_ids,
    ).fetchall()
    return {
        row["player_id"]: {
            "status": row["predicted_status"], "team_short": row["team_short"],
            "doubt_percent": row["doubt_percent"],
        }
        for row in rows
    }
