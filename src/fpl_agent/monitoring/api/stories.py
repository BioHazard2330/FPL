"""Stories about one player or one club, from the stored feeds.

Articles come from the news wire, videos and posts from the media feeds, each
linked to a player or club by the same whole-word matching the desk uses. Shared
by the player and club profiles so both show the same thing the same way. Every
item is something a publisher said, with a link back; nothing is summarised or
scored."""
import html
import re
import sqlite3

_TAG = re.compile(r"<[^>]+>")
_LABEL = {
    "bbc_sport_rss": "BBC Sport", "bbc_sport_football_all_rss": "BBC Sport", "sky_sports_rss": "Sky Sports",
    "guardian_pl_rss": "The Guardian",
}


def _plain(text: str | None, limit: int = 200) -> str | None:
    if not text:
        return None
    cleaned = " ".join(html.unescape(_TAG.sub(" ", text)).split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rsplit(" ", 1)[0] + "…"


def _bigger(url: str | None) -> str | None:
    return re.sub(r"/ace/standard/\d+/", "/ace/standard/800/", url) if url else None


def _shape(conn: sqlite3.Connection, news_ids: set[int], media_ids: set[int], limit: int) -> list[dict]:
    items: list[dict] = []
    if news_ids:
        marks = ",".join("?" * len(news_ids))
        for r in conn.execute(
            f"SELECT id, source, title, link, summary, published_at, image_url FROM news_items WHERE id IN ({marks}) "
            "ORDER BY published_at DESC LIMIT ?", (*news_ids, limit * 2),
        ):
            items.append({
                "kind": "article", "id": f"n{r['id']}", "source": _LABEL.get(r["source"], r["source"]), "title": r["title"],
                "link": r["link"], "summary": _plain(r["summary"]), "image": _bigger(r["image_url"]),
                "published_at": r["published_at"],
            })
    if media_ids:
        marks = ",".join("?" * len(media_ids))
        for r in conn.execute(
            f"SELECT id, kind, channel, title, link, author, thumbnail_url, published_at FROM media_items WHERE id IN ({marks}) "
            "ORDER BY published_at DESC LIMIT ?", (*media_ids, limit * 2),
        ):
            items.append({
                "kind": r["kind"], "id": f"m{r['id']}", "source": r["channel"], "title": html.unescape(r["title"]),
                "link": r["link"], "summary": None, "image": r["thumbnail_url"], "published_at": r["published_at"],
                "video_id": r["link"].rsplit("v=", 1)[-1] if r["kind"] == "video" else None, "author": r["author"],
            })
    seen: set[str] = set()
    unique = []
    for it in sorted(items, key=lambda i: i["published_at"] or "", reverse=True):
        key = re.sub(r"\W+", " ", it["title"].lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    return unique[:limit]


def stories_for_player(conn: sqlite3.Connection, player_id: int, limit: int = 12) -> list[dict]:
    news = {r[0] for r in conn.execute("SELECT news_item_id FROM news_item_players WHERE player_id = ?", (player_id,))}
    media = {r[0] for r in conn.execute("SELECT media_item_id FROM media_item_players WHERE player_id = ?", (player_id,))}
    return _shape(conn, news, media, limit)


def stories_for_team(conn: sqlite3.Connection, team_id: int, limit: int = 12) -> list[dict]:
    """Stories naming the club itself or any of its players."""
    squad = "SELECT id FROM players WHERE team_id = ? AND removed = 0"
    team = conn.execute("SELECT name, short_name FROM teams WHERE id = ?", (team_id,)).fetchone()
    # A roundup that lists every club ("Football Daily", a weekend preview) is
    # tagged with all of them, so a team-only tag counts only when the headline
    # itself names the club.
    names = [n.lower() for n in (team["name"], team["short_name"]) if n] if team else []
    tagged = [
        r[0] for r in conn.execute(
            "SELECT n.id FROM news_item_teams t JOIN news_items n ON n.id = t.news_item_id WHERE t.team_id = ? "
            "AND (" + " OR ".join("lower(n.title) LIKE ?" for _ in names) + ")",
            (team_id, *[f"%{n}%" for n in names]),
        )
    ] if names else []
    news = set(tagged) | {
        r[0] for r in conn.execute(f"SELECT news_item_id FROM news_item_players WHERE player_id IN ({squad})", (team_id,))
    }
    media = {r[0] for r in conn.execute(f"SELECT media_item_id FROM media_item_players WHERE player_id IN ({squad})", (team_id,))}
    return _shape(conn, news, media, limit)
