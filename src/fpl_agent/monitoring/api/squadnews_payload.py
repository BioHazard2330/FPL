"""SQUAD NEWS - what the team sheets, the clubs and the press say about the players you own or the plan buys.

One line per player who has something to say, each carrying where it came from:
- the matchday squad sheet (FotMob): in the eleven, on the bench and when he came on, or in neither list, with FotMob's
  reason and return phrase when it gives one;
- FPL's own news line and status;
- the chance he is available for the next gameweek's first match and the gameweek he is likely back, from
  `models/return_forecast.py` (stated dates, FotMob's phrase, or how long such spells have lasted);
- what the last sheet says about the next match, where `models/sheet_study.py` has measured it;
- headlines from BBC, Sky and The Guardian in the last five days that name him and are about availability or selection.

Nothing here is generated. A headline is quoted as published with its outlet; a statement nobody made is never written. Reads
stored rows only."""
import re
from datetime import datetime, timedelta, timezone

from fpl_agent.monitoring.api.photos import attach_photo_codes

_SOURCE_LABEL = {
    "bbc_sport_rss": "BBC Sport", "bbc_sport_football_all_rss": "BBC Sport", "sky_sports_rss": "Sky Sports",
    "guardian_pl_rss": "The Guardian",
}
_SELECTION_WORDS = re.compile(
    r"\b(injur\w*|doubt\w*|ruled out|suspend\w*|sidelined|setback|fitness|returns? (?:from|after|to training)|out for|miss(es)?|knock|"
    r"bench\w*|dropped|rested|rotat\w*|left out|omitted|unavailable|recover\w*|surgery|scan|ban)\b",
    re.I,
)
_HEADLINE_DAYS = 5
_HEADLINES_PER_PLAYER = 2
_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _event_context(conn) -> tuple[int | None, int | None]:
    cur = conn.execute("SELECT id FROM events WHERE is_current=1 ORDER BY id DESC LIMIT 1").fetchone()
    nxt = conn.execute("SELECT id FROM events WHERE is_next=1 ORDER BY id LIMIT 1").fetchone()
    return (cur["id"] if cur else None, nxt["id"] if nxt else None)


def _fixture_label(conn, match_id: int, team_id: int) -> str:
    row = conn.execute(
        "SELECT mi.status, mi.home_score hs, mi.away_score aws, th.short_name hn, ta.short_name an "
        "FROM match_intelligence mi JOIN teams th ON th.id = mi.home_team_id JOIN teams ta ON ta.id = mi.away_team_id "
        "WHERE mi.id=?", (match_id,),
    ).fetchone()
    if row is None:
        return ""
    if row["status"] in ("FULL_TIME", "LIVE", "HALFTIME") and row["hs"] is not None:
        return f"{row['hn']} {row['hs']}-{row['aws']} {row['an']}"
    return f"{row['hn']} v {row['an']}"


def _next_kickoff(conn, team_id: int, event: int | None) -> datetime | None:
    if event is None:
        return None
    row = conn.execute(
        "SELECT kickoff_time FROM fixtures WHERE event=? AND (team_h=? OR team_a=?) AND kickoff_time IS NOT NULL "
        "ORDER BY kickoff_time LIMIT 1", (event, team_id, team_id),
    ).fetchone()
    if row is None:
        return None
    return datetime.fromisoformat(row["kickoff_time"].replace("Z", "+00:00"))


def _back_gameweek(conn, player_id: int, team_id: int, from_event: int | None, now: datetime) -> tuple[int | None, float | None]:
    """First gameweek in the next eight whose first match he is at least 50% to be available for, and that chance there."""
    from fpl_agent.models.return_forecast import return_forecast

    if from_event is None:
        return None, None
    for event in range(from_event, from_event + 8):
        when = _next_kickoff(conn, team_id, event)
        if when is None:
            continue
        f = return_forecast(conn, player_id, when, now)
        if f is None:
            return None, None
        if f.probability >= 0.5:
            return event, f.probability
    return None, None


def _headlines(conn, player_ids: list[int]) -> dict[int, list[dict]]:
    if not player_ids:
        return {}
    since = (datetime.now(timezone.utc) - timedelta(days=_HEADLINE_DAYS)).isoformat()
    marks = ",".join("?" * len(player_ids))
    names = {r["id"]: r["web_name"] for r in conn.execute(f"SELECT id, web_name FROM players WHERE id IN ({marks})", player_ids)}
    rows = conn.execute(
        f"SELECT nip.player_id, ni.title, ni.source, ni.source_tier, ni.published_at, ni.link "
        f"FROM news_item_players nip JOIN news_items ni ON ni.id = nip.news_item_id "
        f"WHERE nip.player_id IN ({marks}) AND ni.published_at >= ? ORDER BY ni.published_at DESC",
        (*player_ids, since),
    ).fetchall()
    out: dict[int, list[dict]] = {}
    seen: set[tuple[int, str]] = set()
    for r in rows:
        title = r["title"] or ""
        # The headline itself must name him and be about availability or selection: a matching summary alone is how an
        # article on a whole league round ends up under one player.
        if names.get(r["player_id"], "").lower() not in title.lower() or not _SELECTION_WORDS.search(title):
            continue
        key = (r["player_id"], title.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        bucket = out.setdefault(r["player_id"], [])
        if len(bucket) < _HEADLINES_PER_PLAYER:
            bucket.append({
                "title": title, "outlet": _SOURCE_LABEL.get(r["source"], r["source"]), "tier": r["source_tier"],
                "published_at": r["published_at"], "link": r["link"],
            })
    return out


def build_squad_news(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.matchday_status import BENCH, NOT_IN_SQUAD, latest_sheet_roles, squad_matchday_status
    from fpl_agent.models.return_forecast import return_forecast
    from fpl_agent.optimization.week_plan import light_squad_state, plan_target_ids

    conn = get_connection()
    try:
        state = light_squad_state(conn)
        if state is None:
            return {"status": "none", "items": []}
        squad = list(state["squad_ids"])
        targets = sorted(plan_target_ids(conn) - set(squad))
        ids = squad + targets
        current, upcoming = _event_context(conn)
        now = datetime.now(timezone.utc)
        sheet_event = current if current is not None else upcoming
        sheets = squad_matchday_status(conn, ids, sheet_event) if sheet_event is not None else {}
        roles = latest_sheet_roles(conn)
        headlines = _headlines(conn, ids)

        marks = ",".join("?" * len(ids))
        players = {
            r["id"]: r for r in conn.execute(
                f"SELECT p.id, p.web_name, p.team_id, p.element_type, p.status, p.news, p.news_added, t.code AS team_code, "
                f"t.short_name AS team, (SELECT s.chance_of_playing_next_round FROM player_stats_snapshot s "
                f"WHERE s.player_id = p.id ORDER BY s.retrieved_at DESC LIMIT 1) AS chance_next "
                f"FROM players p JOIN teams t ON t.id = p.team_id WHERE p.id IN ({marks})", ids,
            )
        }
        unavailable = {
            r["player_id"]: r for r in conn.execute(
                f"SELECT player_id, kind, expected_return, MAX(retrieved_at) AS at FROM match_unavailable "
                f"WHERE player_id IN ({marks}) GROUP BY player_id", ids,
            )
        }

        items = []
        for pid in ids:
            p = players.get(pid)
            if p is None:
                continue
            sheet = sheets.get(pid)
            facts: list[dict] = []
            severity = 0

            if sheet is not None and sheet.role in (BENCH, NOT_IN_SQUAD):
                label = _fixture_label(conn, sheet.match_id, p["team_id"])
                if sheet.role == NOT_IN_SQUAD:
                    severity = max(severity, 3)
                    facts.append({"source": "Team sheet", "text": f"{sheet.detail} ({label})."})
                else:
                    severity = max(severity, 2)
                    facts.append({"source": "Team sheet", "text": f"{sheet.detail[0].upper()}{sheet.detail[1:]} ({label})."})

            last = roles.get(pid)
            if last is not None and last[0] in (BENCH, NOT_IN_SQUAD) and not (sheet is not None and sheet.role in (BENCH, NOT_IN_SQUAD)):
                severity = max(severity, 1)
                facts.append({"source": "Last team sheet", "text": "Was not in the starting eleven last match."})

            un = unavailable.get(pid)
            news = (p["news"] or "").strip()
            if p["status"] in ("i", "s", "u", "d") or news:
                facts.append({"source": "FPL", "text": news or f"Flagged {p['status']}"})
                if p["status"] in ("i", "s", "u"):
                    severity = max(severity, 3 if pid in squad else 2)
                elif p["status"] == "d":
                    severity = max(severity, 2)
            if un is not None and un["expected_return"]:
                facts.append({"source": "FotMob", "text": f"{un['kind'].capitalize() if un['kind'] else 'Out'}: {un['expected_return']}."})

            prob = None
            back = None
            if upcoming is not None and p["status"] in ("i", "s", "u"):
                when = _next_kickoff(conn, p["team_id"], upcoming)
                if when is not None:
                    f = return_forecast(conn, pid, when, now)
                    if f is not None:
                        prob = round(f.probability, 2)
                        gw, _ = _back_gameweek(conn, pid, p["team_id"], upcoming, now)
                        back = gw
                        facts.append({
                            "source": "Return forecast",
                            "text": f"{round(f.probability * 100)}% to be available for GW{upcoming}"
                                    + (f"; likely back by GW{gw}" if gw and gw > upcoming else "")
                                    + f" ({f.detail}).",
                        })

            heads = headlines.get(pid, [])
            if heads:
                severity = max(severity, 1)

            if severity == 0 and not heads:
                continue
            items.append({
                "player_id": pid, "name": p["web_name"], "team_code": p["team_code"], "team": p["team"],
                "position": _POSITION.get(p["element_type"]), "owned": pid in squad,
                "severity": severity, "facts": facts, "headlines": heads,
                "next_gw_probability": prob, "back_gameweek": back,
                "sheet_role": sheet.role if sheet else None,
                "sheet_detail": sheet.detail if sheet else None,
                "fpl_status": p["status"], "fpl_chance": p["chance_next"],
            })
        items.sort(key=lambda i: (-i["severity"], not i["owned"], i["name"]))
        payload = {"status": "ready", "event": sheet_event, "next_event": upcoming, "items": items}
        return attach_photo_codes(conn, payload)
    finally:
        conn.close()


build_squad_news.needs_context = False
