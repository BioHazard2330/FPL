"""WHAT THE WATCHERS SAID - BBC Sport's player ratings for Premier League matches, read into the database.

For the week's big matches BBC Sport publishes "player ratings" (already in the news feed via its RSS): its reporter at
the ground scores every player out of ten with a one-line verdict, and the page's Player Rater carries the average score
of the fans who watched, with Player of the Match. That is the closest free record of how players looked to the people
watching, as opposed to what the event data counted.

Each article is fetched once (`watcher_article`), the reporter's and fans' scores are parsed, every name is matched to a
player of one of the two clubs (accents and initials ignored), and the match to the fixture between those clubs played
before the article was published. Rows go to `watcher_rating`."""
import html as htmllib
import logging
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

import requests

_logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-agent personal research)"}
TEAM_ALIASES = {
    "Man City": ["man city", "manchester city"], "Man Utd": ["man utd", "manchester united", "man united"],
    "Spurs": ["spurs", "tottenham"], "Nott'm Forest": ["nottm forest", "nottingham forest", "forest"],
    "Newcastle": ["newcastle"], "Brighton": ["brighton"], "Wolves": ["wolves"], "Leeds": ["leeds"],
    "Hull City": ["hull"], "Ipswich Town": ["ipswich"], "Coventry City": ["coventry"],
}


_TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "ß": "ss", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ı": "i"})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", htmllib.unescape(s).translate(_TRANSLIT)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", s.lower().replace("-", " ")).strip()


def _lines(page: str) -> list[str]:
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    txt = re.sub(r"<[^>]+>", "\n", txt)
    return [htmllib.unescape(x.strip()) for x in txt.split("\n") if x.strip()]


def parse_ratings(page: str) -> dict:
    """{reporter: [(name, score, note)], fans: [(name, average)], potm: name|None} from a ratings article."""
    lines = _lines(page)
    start = next((i for i, x in enumerate(lines) if "how i rated the players" in x.lower()), None)
    end = next((i for i, x in enumerate(lines) if x.lower().startswith("how did you rate the players")), len(lines))
    reporter: list[tuple[str, float, str | None]] = []
    if start is not None:
        block = lines[start + 1:end]
        i = 0
        while i < len(block):
            x = block[i]
            nxt = block[i + 1] if i + 1 < len(block) else ""
            trailing = re.match(r"^:\s*(.*?)\s*(\d+(?:\.\d)?)$", nxt)
            if trailing and not x.lower().startswith(("subs", "published")):
                name = re.sub(r"\s*\((?:on|off)[^)]*\)\s*:?$", "", x).strip()
                reporter.append((name, float(trailing.group(2)), trailing.group(1) or None))
                i += 2
                continue
            one = re.match(r"^(.+?)\s*\((?:on|off)[^)]*\)\s*(\d+(?:\.\d)?)$", x)
            if one:
                reporter.append((one.group(1).strip(), float(one.group(2)), None))
                i += 1
                continue
            head = re.match(r"^(.+?)(?::|\s*\((?:on|off)[^)]*\))$", x)
            if head and not x.lower().startswith(("subs", "published", "what do")):
                name, note, j = head.group(1).strip(), [], i + 1
                while j < len(block) and not re.fullmatch(r"\d+(?:\.\d)?", block[j]) and j - i < 6:
                    note.append(block[j])
                    j += 1
                if j < len(block) and re.fullmatch(r"\d+(?:\.\d)?", block[j]):
                    reporter.append((name, float(block[j]), " ".join(note) or None))
                    i = j + 1
                    continue
            i += 1
    fans: list[tuple[str, float]] = []
    potm = None
    tail = lines[end:]
    for i, x in enumerate(tail):
        if x == "Player of the match" and i + 3 < len(tail):
            potm = tail[i + 2] if tail[i + 1].startswith("Number") else None
        if x.startswith("Average Rating:") or x == "Average Rating:":
            val = x.split(":", 1)[1].strip() or (tail[i + 1] if i + 1 < len(tail) else "")
            name = tail[i - 1] if i >= 1 else ""
            if re.fullmatch(r"\d+(?:\.\d+)?", val) and name and not name.startswith("Number"):
                fans.append((name, float(val)))
    return {"reporter": reporter, "fans": list(dict.fromkeys(fans)), "potm": potm}


def _fixture_for(conn: sqlite3.Connection, title: str, published: str) -> tuple[int, list[int]] | None:
    padded = " " + re.sub(r"\s+", " ", _norm(title)) + " "
    found = []
    for r in conn.execute("SELECT id, name FROM teams"):
        names = [_norm(r["name"])] + [_norm(a) for a in TEAM_ALIASES.get(r["name"], [])]
        hits = [padded.find(" " + n + " ") for n in names]
        pos = min((h for h in hits if h >= 0), default=-1)
        if pos >= 0:
            found.append((pos, r["id"]))
    found.sort()
    if len(found) < 2:
        return None
    a, b = found[0][1], found[1][1]
    row = conn.execute(
        "SELECT id FROM fixtures WHERE ((team_h = ? AND team_a = ?) OR (team_h = ? AND team_a = ?)) AND kickoff_time <= ? "
        "ORDER BY kickoff_time DESC LIMIT 1", (a, b, b, a, published),
    ).fetchone()
    return (row["id"], [a, b]) if row else None


def _match_player(name: str, pool: list[sqlite3.Row]) -> int | None:
    n = _norm(name)
    parts = n.split()
    if not parts:
        return None
    surname = parts[-1]
    exact = [p for p in pool if _norm(f"{p['first_name'] or ''} {p['second_name'] or ''}") == n or _norm(p["web_name"]) == n]
    if len(exact) == 1:
        return exact[0]["id"]
    by_surname = [p for p in pool if surname in _norm(p["second_name"] or "").split() or _norm(p["web_name"]).endswith(surname)]
    if len(by_surname) == 1:
        return by_surname[0]["id"]
    if len(parts) > 1 and by_surname:
        initial = parts[0][0]
        narrowed = [p for p in by_surname if _norm(p["first_name"] or "").startswith(initial)]
        if len(narrowed) == 1:
            return narrowed[0]["id"]
    return None


def store_article(conn: sqlite3.Connection, link: str, title: str, published: str, page: str) -> int:
    at = datetime.now(timezone.utc).isoformat()
    fx = _fixture_for(conn, title, published)
    if fx is None:
        conn.execute("INSERT OR REPLACE INTO watcher_article (link, fixture_id, players, status, retrieved_at) VALUES (?, NULL, 0, 'no_fixture', ?)", (link, at))
        return 0
    fixture_id, teams = fx
    pool = conn.execute(
        f"SELECT id, web_name, first_name, second_name FROM players WHERE team_id IN ({','.join('?' * len(teams))})", teams,
    ).fetchall()
    parsed = parse_ratings(page)
    rows: dict[int, dict] = {}
    for name, score, note in parsed["reporter"]:
        pid = _match_player(name, pool)
        if pid:
            rows.setdefault(pid, {})["reporter"] = (score, note)
    potm_id = _match_player(parsed["potm"], pool) if parsed["potm"] else None
    for name, avg in parsed["fans"]:
        pid = _match_player(name, pool)
        if pid:
            rows.setdefault(pid, {})["fan"] = avg
    for pid, r in rows.items():
        rep = r.get("reporter")
        conn.execute(
            "INSERT INTO watcher_rating (fixture_id, player_id, reporter_rating, reporter_note, fan_rating, potm, source, link, published_at, retrieved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'bbc_sport', ?, ?, ?) ON CONFLICT(fixture_id, player_id) DO UPDATE SET reporter_rating=excluded.reporter_rating, "
            "reporter_note=excluded.reporter_note, fan_rating=excluded.fan_rating, potm=excluded.potm, retrieved_at=excluded.retrieved_at",
            (fixture_id, pid, rep[0] if rep else None, rep[1] if rep else None, r.get("fan"), int(pid == potm_id), link, published, at),
        )
    conn.execute("INSERT OR REPLACE INTO watcher_article (link, fixture_id, players, status, retrieved_at) VALUES (?, ?, ?, 'ok', ?)",
                 (link, fixture_id, len(rows), at))
    return len(rows)


def sync_watcher_ratings(conn: sqlite3.Connection, limit: int = 40, session: requests.Session | None = None) -> dict:
    """Fetch every BBC ratings article in the news feed not yet read (newest first, at most `limit` per call)."""
    seen = {r["link"] for r in conn.execute("SELECT link FROM watcher_article")}
    todo = []
    for r in conn.execute(
        "SELECT title, link, MIN(published_at) AS published FROM news_items WHERE source LIKE 'bbc_sport%' AND lower(title) LIKE '%player ratings%' "
        "GROUP BY substr(link, 1, CASE WHEN instr(link, '?') > 0 THEN instr(link, '?') - 1 ELSE length(link) END) ORDER BY published DESC"
    ):
        link = r["link"].split("?", 1)[0]
        if link not in seen and "england" not in r["title"].lower():
            todo.append((link, r["title"], r["published"]))
    http = session or requests.Session()
    done, players = 0, 0
    for link, title, published in todo[:limit]:
        try:
            page = http.get(link, headers=HEADERS, timeout=20)
            page.raise_for_status()
        except Exception as e:
            _logger.warning("watcher ratings: %s failed: %s", link, e)
            continue
        players += store_article(conn, link, title, published, page.text)
        done += 1
    conn.commit()
    return {"articles": done, "players": players, "pending": max(0, len(todo) - done)}


def watchers_for_player(conn: sqlite3.Connection, player_id: int, limit: int = 6) -> list[dict]:
    """The player's recent watcher ratings, newest first, with the fixture's gameweek and opponent."""
    out = []
    for r in conn.execute(
        "SELECT w.*, f.event, f.team_h, f.team_a, th.short_name AS h, ta.short_name AS a, p.team_id FROM watcher_rating w "
        "JOIN fixtures f ON f.id = w.fixture_id JOIN teams th ON th.id = f.team_h JOIN teams ta ON ta.id = f.team_a "
        "JOIN players p ON p.id = w.player_id WHERE w.player_id = ? ORDER BY f.kickoff_time DESC LIMIT ?", (player_id, limit),
    ):
        home = r["team_id"] == r["team_h"]
        out.append({
            "event": r["event"], "opponent": r["a"] if home else r["h"], "home": home,
            "reporter": r["reporter_rating"], "note": r["reporter_note"], "fans": r["fan_rating"], "potm": bool(r["potm"]),
            "link": r["link"],
        })
    return out
