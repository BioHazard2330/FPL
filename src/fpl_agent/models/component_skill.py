"""HOW THE MODEL DID, BY PART - every frozen prediction's parts laid against FPL's own points for the same parts.

`calibration.record_predictions_for_locked_squad` freezes each relevant player's projection at the deadline with its
breakdown (`predicted_components`). Once the gameweek's per-player stats are in (`player_gw_stats`), each part's
realised points follow from FPL's scoring rules: appearance (1 below 60 minutes, 2 from 60), goals and assists at the
position's rate, clean sheets, goals conceded (the rule's points per two conceded on the pitch), saves (per three),
defensive contribution (the position's threshold), bonus and cards. Own goals and penalty saves or misses are not
projected and are left out of both sides.

Only single-fixture gameweeks are compared (a double gameweek's projection here is one match), and only the current
model version. A part that runs hot or cold for a position over several gameweeks is where to look next; one gameweek
is one scoring level (GW8 2026-27: 19 goals and 8 clean sheets in ten matches), so the report counts gameweeks too."""
import json
import sqlite3
from collections import defaultdict

PARTS = ("appearance", "goals", "assists", "bonus", "clean_sheet", "conceded", "saves", "defcon", "cards")
POSITIONS = ("GKP", "DEF", "MID", "FWD")
DEFCON_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}
CONTENDER_TOP = 150
# FPL 2026-27 scoring, used only where the rules table has no row for a key
_GOAL = {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}
_CS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
_GC = {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0}
_DC = {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2}


def _rules(conn: sqlite3.Connection, season: str | None) -> dict:
    from fpl_agent.models.rules import get_rule

    out = {"assists": get_rule(conn, season, "scoring.assists", 3) or 3, "yellow": get_rule(conn, season, "scoring.yellow_cards", -1) or -1,
           "red": get_rule(conn, season, "scoring.red_cards", -3) or -3, "saves": get_rule(conn, season, "scoring.saves", 1) or 1}
    for pos in POSITIONS:
        for key, rule, default in (("goal", "goals_scored", _GOAL), ("cs", "clean_sheets", _CS), ("gc", "goals_conceded", _GC),
                                   ("dc", "defensive_contribution", _DC)):
            value = get_rule(conn, season, f"scoring.{rule}.{pos}", None)
            out[f"{key}_{pos}"] = default[pos] if value is None else value
    return out


def realised_parts(row, pos: str, rules: dict) -> dict[str, float]:
    """FPL points for each projected part from one player-gameweek's stats."""
    m = row["minutes"] or 0
    return {
        "appearance": 0 if m == 0 else (2 if m >= 60 else 1),
        "goals": (row["goals"] or 0) * rules[f"goal_{pos}"],
        "assists": (row["assists"] or 0) * rules["assists"],
        "bonus": row["bonus"] or 0,
        "clean_sheet": (row["clean_sheets"] or 0) * rules[f"cs_{pos}"],
        "conceded": ((row["goals_conceded"] or 0) // 2) * rules[f"gc_{pos}"] if m > 0 else 0,
        "saves": ((row["saves"] or 0) // 3) * rules["saves"] if pos == "GKP" else 0,
        "defcon": rules[f"dc_{pos}"] if pos in DEFCON_THRESHOLD and (row["defensive_contribution"] or 0) >= DEFCON_THRESHOLD[pos] else 0,
        "cards": (row["yellow_cards"] or 0) * rules["yellow"] + (row["red_cards"] or 0) * rules["red"],
    }


def component_report(conn: sqlite3.Connection, event: int | None = None) -> dict:
    """Predicted against realised points per part and position, for all recorded players and for the contenders (the
    `CONTENDER_TOP` highest projections of each gameweek), with the gameweeks behind each figure."""
    from fpl_agent.models.expected_points import MODEL_VERSION
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    rules = _rules(conn, season)
    clause, params = ("AND po.event = ?", (event,)) if event is not None else ("", ())
    rows = conn.execute(
        "SELECT po.event, po.predicted_median, po.predicted_components, et.singular_name_short AS pos, g.* "
        "FROM prediction_outcomes po JOIN players p ON p.id = po.player_id JOIN element_types et ON et.id = p.element_type "
        "JOIN player_gw_stats g ON g.player_id = po.player_id AND g.event = po.event AND g.season = po.season "
        f"WHERE po.season = ? AND po.model_version = ? AND po.predicted_components IS NOT NULL AND g.fixtures = 1 {clause}",
        (season, MODEL_VERSION) + params,
    ).fetchall()
    by_event: dict[int, list] = defaultdict(list)
    for r in rows:
        by_event[r["event"]].append(r)
    contenders = set()
    for ev, rs in by_event.items():
        for r in sorted(rs, key=lambda x: -(x["predicted_median"] or 0))[:CONTENDER_TOP]:
            contenders.add((ev, r["player_id"]))

    def table(keep) -> list[dict]:
        acc: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
        events: dict[str, set[int]] = defaultdict(set)
        for r in rows:
            if not keep(r):
                continue
            pred = json.loads(r["predicted_components"])
            real = realised_parts(r, r["pos"], rules)
            events[r["pos"]].add(r["event"])
            for part in PARTS + ("total",):
                p = sum(pred.get(k, 0.0) for k in PARTS) if part == "total" else pred.get(part, 0.0)
                a = sum(real.values()) if part == "total" else real[part]
                s = acc[(r["pos"], part)]
                s[0] += 1
                s[1] += p
                s[2] += a
        out = []
        for pos in POSITIONS:
            for part in PARTS + ("total",):
                s = acc.get((pos, part))
                if not s or not s[0]:
                    continue
                out.append({
                    "position": pos, "part": part, "n": int(s[0]), "gameweeks": len(events[pos]),
                    "predicted": round(s[1] / s[0], 3), "actual": round(s[2] / s[0], 3), "gap": round((s[2] - s[1]) / s[0], 3),
                })
        return out

    return {
        "events": sorted(by_event),
        "players": len({(r["event"], r["player_id"]) for r in rows}),
        "all": table(lambda r: True),
        "contenders": table(lambda r: (r["event"], r["player_id"]) in contenders),
    }
