"""Tier 2-4 (strong-reporter) journalism ingestion: free Premier League RSS
feeds. FACTS only - see the module-level linkage functions below for why
player/team matching is a heuristic index, never a classified fact.

Two independent sources as of 2026-08-20 (BBC Sport + Sky Sports, both
confirmed live, free, no-key, real journalism) - added specifically to give
models/manager_change.py a genuine second source to require corroboration
from, per this project's own Tier 2-4 precedence policy (CLAUDE.md: "one
journalism source alone isn't enough to build a corroboration detector
around" - the reason the manager-change engine stayed deferred through
Pillar 2 Plan 2a)."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from fpl_agent.ingestion.sync import update_source_health

BBC_PL_RSS_URL = "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml"
SKY_SPORTS_PL_RSS_URL = "https://www.skysports.com/rss/11095"
_TIMEOUT_SECONDS = 15
_SOURCE_NAME = "bbc_sport_rss"
_SOURCE_TIER = "strong_reporter"
_SKY_SPORTS_SOURCE_NAME = "sky_sports_rss"

# (source_name, feed_url, source_tier) - both strong_reporter tier (established
# sports journalism outlets, same trust level, see CLAUDE.md's precedence policy).
NEWS_SOURCES = (
    (_SOURCE_NAME, BBC_PL_RSS_URL, _SOURCE_TIER),
    (_SKY_SPORTS_SOURCE_NAME, SKY_SPORTS_PL_RSS_URL, _SOURCE_TIER),
)


class NewsFetchError(Exception):
    pass


def fetch_rss(url: str) -> str:
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise NewsFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _text_or_none(item: ET.Element, tag: str) -> str | None:
    el = item.find(tag)
    if el is None or not el.text:
        return None
    return el.text.strip()


def parse_rss_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall("./channel/item"):
        title = _text_or_none(item, "title")
        link = _text_or_none(item, "link")
        if title is None or link is None:
            continue  # malformed item - skip, don't fail the whole feed

        external_id = _text_or_none(item, "guid") or link
        summary = _text_or_none(item, "description")

        published_at = None
        raw_pubdate = _text_or_none(item, "pubDate")
        if raw_pubdate is not None:
            try:
                published_at = parsedate_to_datetime(raw_pubdate).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                published_at = None  # unparseable date - keep the item, drop the date

        items.append({
            "external_id": external_id,
            "title": title,
            "link": link,
            "summary": summary,
            "published_at": published_at,
        })
    return items


_MIN_NAME_LENGTH = 4


def match_players(conn, text: str) -> list[int]:
    """Case-insensitive substring match against players.web_name, falling back to
    second_name only if web_name matched nothing. Heuristic, documented in the
    design doc as best-effort indexing only - never treat this as a confirmed
    identification."""
    text_lower = text.lower()
    rows = conn.execute("SELECT id, web_name, second_name FROM players WHERE removed = 0").fetchall()

    matched = {
        row["id"] for row in rows
        if row["web_name"] and len(row["web_name"]) >= _MIN_NAME_LENGTH and row["web_name"].lower() in text_lower
    }
    if matched:
        return sorted(matched)

    matched = {
        row["id"] for row in rows
        if row["second_name"] and len(row["second_name"]) >= _MIN_NAME_LENGTH
        and row["second_name"].lower() in text_lower
    }
    return sorted(matched)


def match_teams(conn, text: str) -> list[int]:
    """Full team name substring match first (long enough to be safe); falls back to
    short_name only with a word-boundary regex, since 3-letter codes are otherwise
    prone to matching inside unrelated words."""
    text_lower = text.lower()
    rows = conn.execute("SELECT id, name, short_name FROM teams").fetchall()

    matched = {row["id"] for row in rows if row["name"] and row["name"].lower() in text_lower}
    if matched:
        return sorted(matched)

    matched = {
        row["id"] for row in rows
        if row["short_name"] and re.search(rf"\b{re.escape(row['short_name'].lower())}\b", text_lower)
    }
    return sorted(matched)


def sync_news(
    conn,
    feed_url: str = BBC_PL_RSS_URL,
    limit: int | None = None,
    source_name: str = _SOURCE_NAME,
    source_tier: str = _SOURCE_TIER,
) -> dict:
    """`source_name`/`source_tier` default to BBC (unchanged prior behavior
    for any existing caller that doesn't pass them) - pass a different
    NEWS_SOURCES entry to sync Sky Sports or any future additional feed."""
    try:
        xml_text = fetch_rss(feed_url)
        items = parse_rss_items(xml_text)
    except (NewsFetchError, ET.ParseError) as exc:
        update_source_health(conn, source_name, success=False, error=str(exc))
        raise NewsFetchError(str(exc)) from exc

    now = datetime.now(timezone.utc).isoformat()
    new_items = players_linked = teams_linked = 0

    for item in items:
        if limit is not None and new_items >= limit:
            break

        existing = conn.execute(
            "SELECT id FROM news_items WHERE source=? AND external_id=?",
            (source_name, item["external_id"]),
        ).fetchone()
        if existing is not None:
            continue

        cur = conn.execute(
            "INSERT INTO news_items (source, source_tier, external_id, title, link, summary, published_at, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (source_name, source_tier, item["external_id"], item["title"], item["link"],
             item["summary"], item["published_at"], now),
        )
        news_item_id = cur.lastrowid
        new_items += 1

        match_text = item["title"] + " " + (item["summary"] or "")
        for player_id in match_players(conn, match_text):
            conn.execute(
                "INSERT OR IGNORE INTO news_item_players (news_item_id, player_id) VALUES (?, ?)",
                (news_item_id, player_id),
            )
            players_linked += 1
        for team_id in match_teams(conn, match_text):
            conn.execute(
                "INSERT OR IGNORE INTO news_item_teams (news_item_id, team_id) VALUES (?, ?)",
                (news_item_id, team_id),
            )
            teams_linked += 1

    conn.commit()
    update_source_health(conn, source_name, success=True, error=None)
    return {
        "fetched": len(items),
        "new_items": new_items,
        "players_linked": players_linked,
        "teams_linked": teams_linked,
    }


def sync_all_news_sources(conn, limit: int | None = None) -> dict:
    """Syncs every registered source (NEWS_SOURCES) in one call - what `fpl
    sync-news` actually runs. Aggregated totals; per-source failures don't
    abort the others (each already has its own source_health tracking via
    sync_news -> update_source_health)."""
    totals = {"fetched": 0, "new_items": 0, "players_linked": 0, "teams_linked": 0}
    errors = {}
    for name, url, tier in NEWS_SOURCES:
        try:
            result = sync_news(conn, feed_url=url, limit=limit, source_name=name, source_tier=tier)
            for key in totals:
                totals[key] += result[key]
        except NewsFetchError as exc:
            errors[name] = str(exc)
    return {**totals, "errors": errors}


def list_recent_news(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT n.id, n.title, n.link, n.source_tier, n.published_at, "
        "(SELECT GROUP_CONCAT(p.web_name, ', ') FROM news_item_players nip "
        " JOIN players p ON p.id = nip.player_id WHERE nip.news_item_id = n.id) AS players, "
        "(SELECT GROUP_CONCAT(t.short_name, ', ') FROM news_item_teams nit "
        " JOIN teams t ON t.id = nit.team_id WHERE nit.news_item_id = n.id) AS teams "
        "FROM news_items n ORDER BY n.published_at DESC, n.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
