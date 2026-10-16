"""THE DESK - everything being said about football this week, ranked by what it
means for your squad and your plan.

Articles (BBC, Sky, The Guardian), the official FPL injury notes, video from the
Premier League, Sky Sports and two FPL channels, r/FantasyPL, and the price
board. Every item is a fact someone published; nothing here is generated.
Relevance is arithmetic over ids: an item is YOURS if it names a player in your
squad, a TARGET if it names a player the week plan buys or declined, and
otherwise plain news, newest first. The same story arriving from two feeds is
shown once.

Reads stored rows only (the scheduled cycle does the fetching), so it answers
in milliseconds and never waits on the dashboard context."""
import html
import re
from datetime import datetime, timedelta, timezone

from fpl_agent.monitoring.api.photos import attach_photo_codes
from fpl_agent.monitoring.dashboard.context import DashboardContext

_SOURCE_LABEL = {
    "bbc_sport_rss": "BBC Sport", "bbc_sport_football_all_rss": "BBC Sport", "sky_sports_rss": "Sky Sports",
    "guardian_pl_rss": "The Guardian",
}
_INJURY_WORDS = re.compile(
    r"\b(injur\w*|doubt\w*|ruled out|suspend\w*|sidelined|setback|fitness|returns? from|out for|miss(es)? the|knock|ban)\b", re.I,
)
_TAG = re.compile(r"<[^>]+>")
_WIRE_LIMIT = 36
_VIDEO_LIMIT = 12
_POST_LIMIT = 10
_NEWS_WINDOW_DAYS = 5
_INJURY_WINDOW_DAYS = 10


def _plain(text: str | None, limit: int = 240) -> str | None:
    if not text:
        return None
    cleaned = html.unescape(_TAG.sub(" ", text))
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rsplit(" ", 1)[0] + "…"


def _bigger_image(url: str | None) -> str | None:
    """BBC serves the same picture at any width through the path; the feed only
    advertises the smallest."""
    if not url:
        return None
    return re.sub(r"/ace/standard/\d+/", "/ace/standard/800/", url)


def _since(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _player_chips(conn, rows: dict[int, list[int]], mine: set[int], targets: set[int]) -> dict[int, list[dict]]:
    ids = {p for pids in rows.values() for p in pids}
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    info = {
        r["id"]: r for r in conn.execute(
            f"SELECT p.id, p.web_name, t.code AS team_code FROM players p JOIN teams t ON t.id = p.team_id WHERE p.id IN ({marks})",
            tuple(ids),
        )
    }
    return {
        key: [
            {"player_id": p, "name": info[p]["web_name"], "team_code": info[p]["team_code"], "mine": p in mine, "target": p in targets}
            for p in pids if p in info
        ]
        for key, pids in rows.items()
    }


def _relevance(chips: list[dict]) -> int:
    return (2 if any(c["mine"] for c in chips) else 0) + (1 if any(c["target"] for c in chips) else 0)


def _articles(conn, mine: set[int], targets: set[int]) -> list[dict]:
    rows = conn.execute(
        "SELECT id, source, title, link, summary, published_at, image_url FROM news_items "
        "WHERE published_at >= ? ORDER BY published_at DESC LIMIT 400", (_since(_NEWS_WINDOW_DAYS),),
    ).fetchall()
    seen: set[str] = set()
    unique = []
    for r in rows:
        key = re.sub(r"\W+", " ", r["title"].lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    links: dict[int, list[int]] = {r["id"]: [] for r in unique}
    if unique:
        marks = ",".join("?" * len(links))
        for link in conn.execute(
            f"SELECT news_item_id, player_id FROM news_item_players WHERE news_item_id IN ({marks})", tuple(links),
        ):
            links[link["news_item_id"]].append(link["player_id"])
    chips = _player_chips(conn, links, mine, targets)

    out = []
    for r in unique:
        chip_list = chips.get(r["id"], [])
        text = f"{r['title']} {r['summary'] or ''}"
        out.append({
            "id": r["id"], "source": _SOURCE_LABEL.get(r["source"], r["source"]), "title": r["title"], "link": r["link"],
            "summary": _plain(r["summary"]), "image": _bigger_image(r["image_url"]), "published_at": r["published_at"],
            "players": chip_list, "relevance": _relevance(chip_list), "injury": bool(_INJURY_WORDS.search(text)),
        })
    return out


def _injuries(conn, mine: set[int], targets: set[int]) -> list[dict]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, p.status, p.news, p.news_added, t.code AS team_code, t.short_name AS team_short, "
        "       (SELECT chance_of_playing_next_round FROM player_stats_snapshot WHERE player_id = p.id ORDER BY id DESC LIMIT 1) AS chance, "
        "       (SELECT selected_by_percent FROM player_ownership_history WHERE player_id = p.id AND valid_until IS NULL) AS owned "
        "FROM players p JOIN teams t ON t.id = p.team_id "
        "WHERE p.removed = 0 AND p.news IS NOT NULL AND p.news != '' AND p.news_added >= ?", (_since(_INJURY_WINDOW_DAYS),),
    ).fetchall()
    out = [
        {
            "player_id": r["id"], "name": r["web_name"], "team_code": r["team_code"], "team_short": r["team_short"],
            "status": r["status"], "news": r["news"], "added_at": r["news_added"], "chance": r["chance"],
            "owned": r["owned"], "mine": r["id"] in mine, "target": r["id"] in targets,
        }
        for r in rows
    ]
    out.sort(key=lambda x: (not x["mine"], not x["target"], -(x["owned"] or 0)))
    return out[:18]


def _videos(conn, mine: set[int], targets: set[int]) -> list[dict]:
    rows = conn.execute(
        "SELECT id, source, channel, title, link, thumbnail_url, published_at, description FROM media_items "
        "WHERE kind='video' ORDER BY published_at DESC LIMIT 60"
    ).fetchall()
    links: dict[int, list[int]] = {r["id"]: [] for r in rows}
    if rows:
        marks = ",".join("?" * len(links))
        for link in conn.execute(
            f"SELECT media_item_id, player_id FROM media_item_players WHERE media_item_id IN ({marks})", tuple(links),
        ):
            links[link["media_item_id"]].append(link["player_id"])
    chips = _player_chips(conn, links, mine, targets)
    videos = []
    for r in rows:
        video_id = r["link"].rsplit("v=", 1)[-1]
        chip_list = chips.get(r["id"], [])
        videos.append({
            "id": r["id"], "video_id": video_id, "channel": r["channel"], "title": html.unescape(r["title"]),
            "link": r["link"], "thumbnail": r["thumbnail_url"], "published_at": r["published_at"],
            "players": chip_list, "relevance": _relevance(chip_list),
        })
    videos.sort(key=lambda v: (-v["relevance"], v["published_at"] or ""), reverse=False)
    videos.sort(key=lambda v: (v["relevance"], v["published_at"] or ""), reverse=True)
    return videos[:_VIDEO_LIMIT]


def _posts(conn, mine: set[int], targets: set[int]) -> list[dict]:
    rows = conn.execute(
        "SELECT id, channel, title, link, author, thumbnail_url, published_at FROM media_items "
        "WHERE kind='post' ORDER BY published_at DESC LIMIT 40"
    ).fetchall()
    links: dict[int, list[int]] = {r["id"]: [] for r in rows}
    if rows:
        marks = ",".join("?" * len(links))
        for link in conn.execute(
            f"SELECT media_item_id, player_id FROM media_item_players WHERE media_item_id IN ({marks})", tuple(links),
        ):
            links[link["media_item_id"]].append(link["player_id"])
    chips = _player_chips(conn, links, mine, targets)
    posts = [
        {
            "id": r["id"], "title": html.unescape(r["title"]), "link": r["link"], "author": r["author"],
            "thumbnail": r["thumbnail_url"], "published_at": r["published_at"], "players": chips.get(r["id"], []),
        }
        for r in rows
    ]
    return posts[:_POST_LIMIT]


def _price_board(conn, mine: set[int], targets: set[int]) -> dict:
    """Moves in the last 36 hours, and who is likely to move at the next price
    change by the project's own transfer-momentum heuristic (uncalibrated, low
    confidence by its own docstring - labelled as a lean, not a forecast)."""
    from fpl_agent.models.price_forecast import RISE_THRESHOLD

    moved = conn.execute(
        "SELECT e.entity_id AS player_id, e.old_value, e.new_value, e.detected_at, p.web_name, t.code AS team_code, "
        "       (SELECT selected_by_percent FROM player_ownership_history WHERE player_id = p.id AND valid_until IS NULL) AS owned "
        "FROM change_events e JOIN players p ON p.id = e.entity_id JOIN teams t ON t.id = p.team_id "
        "WHERE e.event_type = 'price_change' AND e.entity = 'player' AND e.detected_at >= ? ORDER BY e.detected_at DESC",
        (_since(1.5),),
    ).fetchall()

    def row(r) -> dict:
        return {
            "player_id": r["player_id"], "name": r["web_name"], "team_code": r["team_code"], "old": r["old_value"],
            "new": r["new_value"], "at": r["detected_at"], "owned": r["owned"],
            "mine": r["player_id"] in mine, "target": r["player_id"] in targets,
        }

    rises = [row(r) for r in moved if float(r["new_value"]) > float(r["old_value"])]
    falls = [row(r) for r in moved if float(r["new_value"]) < float(r["old_value"])]

    total_row = conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    total_players = int(total_row["value"]) if total_row else 0
    leaning = []
    if total_players:
        for c in conn.execute(
            "SELECT p.id, p.web_name, t.code AS team_code, m.transfers_in_event - m.transfers_out_event AS net, "
            "       (SELECT selected_by_percent FROM player_ownership_history WHERE player_id = p.id AND valid_until IS NULL) AS owned "
            "FROM player_transfer_momentum_history m JOIN players p ON p.id = m.player_id JOIN teams t ON t.id = p.team_id "
            "WHERE m.valid_until IS NULL AND p.removed = 0"
        ):
            ratio = c["net"] / total_players
            if abs(ratio) <= RISE_THRESHOLD:
                continue
            if (c["owned"] or 0) < 3.0 and c["id"] not in mine and c["id"] not in targets:
                continue
            leaning.append({
                "player_id": c["id"], "name": c["web_name"], "team_code": c["team_code"],
                "direction": "RISE_LIKELY" if ratio > 0 else "FALL_LIKELY", "net_ratio": round(ratio, 6),
                "owned": c["owned"], "mine": c["id"] in mine, "target": c["id"] in targets,
            })
    leaning.sort(key=lambda x: (not (x["mine"] or x["target"]), -abs(x["net_ratio"])))
    return {"rises": rises[:10], "falls": falls[:10], "leaning": leaning[:16]}


def build_desk_payload(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.optimization.week_plan import latest_week_plan, light_squad_state

    conn = get_connection()
    try:
        state = light_squad_state(conn)
        mine = set(state["squad_ids"]) if state else set()
        stored = latest_week_plan(conn)
        targets: set[int] = set()
        if stored is not None:
            detail = stored[0]
            targets = {m["into"]["player_id"] for m in detail.get("moves", []) + detail.get("declined", [])}

        articles = _articles(conn, mine, targets)
        ranked = sorted(articles, key=lambda a: (a["relevance"], a["published_at"] or ""), reverse=True)
        lead = next((a for a in ranked if a["image"] and a["relevance"] > 0), None) or next(
            (a for a in articles if a["image"]), None
        )
        wire = [a for a in ranked if lead is None or a["id"] != lead["id"]][:_WIRE_LIMIT]

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lead": lead,
            "wire": wire,
            "injuries": _injuries(conn, mine, targets),
            "videos": _videos(conn, mine, targets),
            "posts": _posts(conn, mine, targets),
            "price": _price_board(conn, mine, targets),
            "counts": {
                "articles": len(articles), "yours": sum(1 for a in articles if a["relevance"] >= 2),
                "targets": sum(1 for a in articles if a["relevance"] == 1),
            },
        }
        return attach_photo_codes(conn, payload)
    finally:
        conn.close()


build_desk_payload.needs_context = False
