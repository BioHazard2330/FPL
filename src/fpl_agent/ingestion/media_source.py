"""Video and community feeds for the news desk (2026-10-16).

Two kinds of item that an RSS article feed does not cover:

- **Videos**, from the public per-channel Atom feed YouTube serves without a
  key (`/feeds/videos.xml?channel_id=...`): the official Premier League channel
  (which publishes the FPL podcast), Sky Sports Premier League, and six FPL
  channels (FPL Harry, Let's Talk FPL, Fantasy Football Hub, FPL Focal, FPL Raptor, FPL Mate). Channel ids were resolved from each
  channel's own page and each feed was fetched before being listed - a handle
  that resolved to a different club's channel was found and dropped doing that.
- **Community posts**, from r/FantasyPL's Atom feed. Reddit's JSON endpoint
  answers 403 to a script; the Atom feed does not, and carries no score, so the
  posts are ordered by Reddit's own "hot" ranking and nothing here invents a
  number for them.

FACTS only, same posture as news_source.py: an item is "this was published".
Players are linked by whole-word match with the same disambiguation as news
(`news_source.match_players`), best-effort indexing and never an identification.
Throttled to one fetch per `MIN_INTERVAL_MINUTES`; every feed is independently
fallible, so one dead channel never costs the others."""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from fpl_agent.ingestion.sync import update_source_health

_logger = logging.getLogger("fpl_agent.media")

_TIMEOUT_SECONDS = 15
MIN_INTERVAL_MINUTES = 30
_META_KEY = "media_last_synced_at"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) fpl-agent/personal"}

_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

# (source_name, kind, feed_url, channel label)
VIDEO_CHANNELS = (
    ("youtube_premier_league", "Premier League", "UCG5qGWdu8nIRZqJ_GgDwQ-w"),
    ("youtube_sky_sports_pl", "Sky Sports Premier League", "UCNAf1k0yIjyGu3k9BwAg3lg"),
    ("youtube_fpl_harry", "FPL Harry", "UCcPWnCj5AKC19HaySZjb25g"),
    ("youtube_lets_talk_fpl", "Let's Talk FPL", "UCxeOc7eFxq37yW_Nc-69deA"),
    ("youtube_fantasy_football_hub", "Fantasy Football Hub", "UCcqEr3DfrRwtoF2a1yW8qgQ"),
    ("youtube_fpl_focal", "FPL Focal", "UC72QokPHXQ9r98ROfNZmaDw"),
    ("youtube_fpl_raptor", "FPL Raptor", "UC54QLWzsMifTRjNQ02z5pCw"),
    ("youtube_fpl_mate", "FPL Mate", "UCweDAlFm2LnVcOqaFU4_AGA"),
)
REDDIT_SOURCE = "reddit_fantasypl"
REDDIT_URL = "https://www.reddit.com/r/FantasyPL/hot.rss"
_MAX_PER_FEED = 15

_TRIVIAL_POST = re.compile(r"^(rate my team|daily discussion|gameweek \d+ (discussion|thread)|gw ?\d+ (discussion|thread))", re.I)


class MediaFetchError(Exception):
    pass


def _fetch(url: str) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise MediaFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _text(el: ET.Element | None, path: str) -> str | None:
    node = el.find(path, _NS) if el is not None else None
    if node is None or node.text is None:
        return None
    return node.text.strip() or None


def _attr(el: ET.Element, path: str, attr: str) -> str | None:
    node = el.find(path, _NS)
    return node.get(attr) if node is not None else None


def _iso(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def parse_youtube_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for entry in root.findall("a:entry", _NS):
        video_id = _text(entry, "yt:videoId")
        title = _text(entry, "a:title")
        if not video_id or not title:
            continue
        description = _text(entry, "media:group/media:description")
        out.append({
            "external_id": video_id,
            "title": title,
            "link": f"https://www.youtube.com/watch?v={video_id}",
            "author": _text(entry, "a:author/a:name"),
            "thumbnail_url": _attr(entry, "media:group/media:thumbnail", "url"),
            "description": (description or "")[:600] or None,
            "published_at": _iso(_text(entry, "a:published")),
        })
    return out[:_MAX_PER_FEED]


def parse_reddit_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for entry in root.findall("a:entry", _NS):
        external_id = _text(entry, "a:id")
        title = _text(entry, "a:title")
        link_el = entry.find("a:link", _NS)
        link = link_el.get("href") if link_el is not None else None
        if not external_id or not title or not link or _TRIVIAL_POST.match(title):
            continue
        out.append({
            "external_id": external_id,
            "title": title,
            "link": link,
            "author": (_text(entry, "a:author/a:name") or "").removeprefix("/u/") or None,
            "thumbnail_url": _attr(entry, "media:thumbnail", "url"),
            "description": None,
            "published_at": _iso(_text(entry, "a:updated")),
        })
    return out[:_MAX_PER_FEED]


def _store(conn, source: str, kind: str, channel: str, items: list[dict], now: str) -> tuple[int, int]:
    from fpl_agent.ingestion.news_source import match_players

    new = linked = 0
    for item in items:
        cur = conn.execute(
            "INSERT OR IGNORE INTO media_items (source, kind, external_id, title, link, author, channel, "
            "thumbnail_url, description, published_at, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (source, kind, item["external_id"], item["title"], item["link"], item["author"], channel,
             item["thumbnail_url"], item["description"], item["published_at"], now),
        )
        if cur.rowcount == 0:
            continue
        new += 1
        for player_id in match_players(conn, item["title"] + " " + (item["description"] or "")):
            conn.execute(
                "INSERT OR IGNORE INTO media_item_players (media_item_id, player_id) VALUES (?, ?)",
                (cur.lastrowid, player_id),
            )
            linked += 1
    return new, linked


def should_sync(conn, force: bool = False) -> bool:
    if force:
        return True
    row = conn.execute("SELECT value FROM app_meta WHERE key=?", (_META_KEY,)).fetchone()
    if row is None:
        return True
    try:
        last = datetime.fromisoformat(row["value"].replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(minutes=MIN_INTERVAL_MINUTES)


def sync_media(conn, force: bool = False) -> dict:
    """Every feed is independent: a failure is recorded against that source's
    health and the rest still run. Returns counts per source."""
    if not should_sync(conn, force):
        return {"skipped": True}
    now = datetime.now(timezone.utc).isoformat()
    feeds = [
        (name, "video", channel, f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", parse_youtube_feed)
        for name, channel, channel_id in VIDEO_CHANNELS
    ] + [(REDDIT_SOURCE, "post", "r/FantasyPL", REDDIT_URL, parse_reddit_feed)]

    result: dict = {"skipped": False, "sources": {}}
    for name, kind, channel, url, parser in feeds:
        try:
            items = parser(_fetch(url))
            new, linked = _store(conn, name, kind, channel, items, now)
            conn.commit()
            update_source_health(conn, name, success=True, error=None)
            result["sources"][name] = {"fetched": len(items), "new": new, "players_linked": linked}
        except (MediaFetchError, ET.ParseError) as exc:
            conn.rollback()
            update_source_health(conn, name, success=False, error=str(exc))
            result["sources"][name] = {"error": str(exc)}
            _logger.warning("media feed %s failed: %s", name, exc)
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (_META_KEY, now, now),
    )
    conn.commit()
    return result
