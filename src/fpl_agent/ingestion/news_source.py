"""Tier 2-4 (strong-reporter) journalism ingestion: BBC Sport's free Premier
League RSS feed. FACTS only - see the module-level linkage functions below for
why player/team matching is a heuristic index, never a classified fact."""
import re
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime

import requests

BBC_PL_RSS_URL = "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml"
_TIMEOUT_SECONDS = 15


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
    rows = conn.execute("SELECT id, web_name, second_name FROM players").fetchall()

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
