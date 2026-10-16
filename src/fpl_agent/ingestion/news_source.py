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
import functools
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from fpl_agent.ingestion.sync import update_source_health

BBC_PL_RSS_URL = "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml"
SKY_SPORTS_PL_RSS_URL = "https://www.skysports.com/rss/11095"
# General BBC football feed (all competitions - Champions League, Europa
# League, Carabao Cup, internationals, not just the Premier League) - added
# 2026-08-20 per the user's explicit ask that injuries/news from cup and
# European competitions get tracked too, not just league fixtures. Confirmed
# live and genuinely distinct from the PL-specific feed (real dated content,
# e.g. a live Champions League article the PL-only feed didn't carry) before
# adding, not assumed. Kept as a THIRD source alongside the two PL-specific
# ones rather than replacing either - broader competition coverage without
# diluting the PL-specific corroboration signal manager_change.py depends on.
BBC_FOOTBALL_ALL_RSS_URL = "https://feeds.bbci.co.uk/sport/football/rss.xml"
GUARDIAN_PL_RSS_URL = "https://www.theguardian.com/football/premierleague/rss"
_TIMEOUT_SECONDS = 15
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) fpl-agent/personal"}
_GUARDIAN_SOURCE_NAME = "guardian_pl_rss"
_SOURCE_NAME = "bbc_sport_rss"
_SOURCE_TIER = "strong_reporter"
_SKY_SPORTS_SOURCE_NAME = "sky_sports_rss"
_BBC_FOOTBALL_ALL_SOURCE_NAME = "bbc_sport_football_all_rss"

# (source_name, feed_url, source_tier) - all strong_reporter tier (established
# sports journalism outlets, same trust level, see CLAUDE.md's precedence policy).
NEWS_SOURCES = (
    (_SOURCE_NAME, BBC_PL_RSS_URL, _SOURCE_TIER),
    (_SKY_SPORTS_SOURCE_NAME, SKY_SPORTS_PL_RSS_URL, _SOURCE_TIER),
    (_BBC_FOOTBALL_ALL_SOURCE_NAME, BBC_FOOTBALL_ALL_RSS_URL, _SOURCE_TIER),
    (_GUARDIAN_SOURCE_NAME, GUARDIAN_PL_RSS_URL, _SOURCE_TIER),
)


class NewsFetchError(Exception):
    pass


def fetch_rss(url: str) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise NewsFetchError(f"failed to fetch {url}: {exc}") from exc
    return resp.text


def _text_or_none(item: ET.Element, tag: str) -> str | None:
    el = item.find(tag)
    if el is None or not el.text:
        return None
    return el.text.strip()


def _image_url(item: ET.Element) -> str | None:
    """The widest picture the item offers: a media:thumbnail/media:content with
    an url, or an image enclosure. Feeds disagree on which they use, and several
    give the same picture at five sizes."""
    best_url, best_width = None, -1
    for child in item:
        tag = child.tag.rsplit("}", 1)[-1]
        url = child.get("url")
        if not url:
            continue
        is_image = (
            tag == "thumbnail"
            or (tag == "content" and (child.get("medium") == "image" or (child.get("type") or "").startswith("image")))
            or (tag == "enclosure" and (child.get("type") or "").startswith("image"))
        )
        if not is_image:
            continue
        try:
            width = int(child.get("width") or 0)
        except ValueError:
            width = 0
        if width > best_width:
            best_url, best_width = url, width
    return best_url


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
            "image_url": _image_url(item),
        })
    return items


_MIN_NAME_LENGTH = 4


@functools.lru_cache(maxsize=4096)
def _fold_name(name: str) -> str:
    from fpl_agent.ingestion.predicted_lineups_source import _fold

    return _fold(name)


def _mentions(folded_text: str, folded_name: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(folded_name)}(?![a-z0-9])", folded_text) is not None


def _is_someone_else(text: str, row) -> bool:
    """A player known by a first name or nickname ("Enzo", "Rayan") is another
    person when the text gives that word a capitalised surname the player does
    not have - "Enzo Maresca" is City's manager, not Chelsea's midfielder."""
    web, second = _fold_name(row["web_name"]), _fold_name(row["second_name"] or "")
    if not web or web == second or web in second.split():
        return False
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    own = set(second.split()) | set(_fold_name(row["first_name"] or "").split())
    for m in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(row['web_name'])}\s+([A-Z][\w'-]+)", plain, flags=re.I):
        follower = m.group(1)
        if follower[0].isupper() and follower.lower() not in own:
            return True
    return False


def match_players(conn, text: str) -> list[int]:
    """Whole-word, accent-folded match against players.web_name, falling back to
    second_name only if web_name matched nothing. Heuristic, documented in the
    design doc as best-effort indexing only - never treat this as a confirmed
    identification.

    Two things this used to get wrong. A bare substring test linked "King" to
    every headline containing "making" or "looking" (721 articles, filed under
    both Kings), and a surname two players share was linked to both of them, so a
    story about Ipswich's goalkeeper Palmer reached Cole Palmer's file. A name is
    now a whole word, and a surname shared by several players is attributed only
    to those whose club the same text names; if it names none, nobody gets it."""
    folded_text = _fold_name(text)
    rows = conn.execute("SELECT id, web_name, first_name, second_name, team_id FROM players WHERE removed = 0").fetchall()

    def pick(field: str) -> set[int]:
        by_name: dict[str, list] = {}
        for row in rows:
            name = row[field]
            if (
                name and len(name) >= _MIN_NAME_LENGTH and _mentions(folded_text, _fold_name(name))
                and not (field == "web_name" and _is_someone_else(text, row))
            ):
                by_name.setdefault(_fold_name(name), []).append(row)
        chosen: set[int] = set()
        mentioned_teams: set[int] | None = None
        for candidates in by_name.values():
            if len(candidates) == 1:
                chosen.add(candidates[0]["id"])
                continue
            if mentioned_teams is None:
                mentioned_teams = set(match_teams(conn, text))
            chosen.update(c["id"] for c in candidates if c["team_id"] in mentioned_teams)
        return chosen

    matched = pick("web_name")
    if matched:
        return sorted(matched)
    return sorted(pick("second_name"))


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
            if item.get("image_url"):
                conn.execute(
                    "UPDATE news_items SET image_url=? WHERE id=? AND image_url IS NULL", (item["image_url"], existing["id"]),
                )
            continue

        cur = conn.execute(
            "INSERT INTO news_items (source, source_tier, external_id, title, link, summary, published_at, retrieved_at, "
            "image_url) VALUES (?,?,?,?,?,?,?,?,?)",
            (source_name, source_tier, item["external_id"], item["title"], item["link"],
             item["summary"], item["published_at"], now, item.get("image_url")),
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
