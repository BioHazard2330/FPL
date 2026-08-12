import hashlib
import json
from typing import Any


def normalize_teams(bootstrap: dict) -> list[dict]:
    return [
        {
            "id": t["id"],
            "code": t["code"],
            "name": t["name"],
            "short_name": t["short_name"],
            "strength_overall_home": t.get("strength_overall_home"),
            "strength_overall_away": t.get("strength_overall_away"),
            "strength_attack_home": t.get("strength_attack_home"),
            "strength_attack_away": t.get("strength_attack_away"),
            "strength_defence_home": t.get("strength_defence_home"),
            "strength_defence_away": t.get("strength_defence_away"),
            "pulse_id": t.get("pulse_id"),
        }
        for t in bootstrap["teams"]
    ]


def normalize_element_types(bootstrap: dict) -> list[dict]:
    return [
        {
            "id": et["id"],
            "singular_name": et["singular_name"],
            "singular_name_short": et["singular_name_short"],
            "plural_name": et["plural_name"],
            "squad_min_play": et.get("squad_min_play"),
            "squad_max_play": et.get("squad_max_play"),
        }
        for et in bootstrap["element_types"]
    ]


def normalize_events(bootstrap: dict) -> list[dict]:
    return [
        {
            "id": e["id"],
            "name": e["name"],
            "deadline_time": e["deadline_time"],
            "deadline_time_epoch": e["deadline_time_epoch"],
            "finished": int(bool(e.get("finished"))),
            "is_previous": int(bool(e.get("is_previous"))),
            "is_current": int(bool(e.get("is_current"))),
            "is_next": int(bool(e.get("is_next"))),
            "average_entry_score": e.get("average_entry_score"),
            "highest_score": e.get("highest_score"),
        }
        for e in bootstrap["events"]
    ]


def normalize_players(bootstrap: dict) -> list[dict]:
    return [
        {
            "id": el["id"],
            "code": el["code"],
            "web_name": el["web_name"],
            "first_name": el.get("first_name"),
            "second_name": el.get("second_name"),
            "team_id": el["team"],
            "element_type": el["element_type"],
            "squad_number": el.get("squad_number"),
            "status": el["status"],
            "news": el.get("news") or None,
            "news_added": el.get("news_added"),
            "opta_code": el.get("opta_code"),
            "removed": int(bool(el.get("removed"))),
        }
        for el in bootstrap["elements"]
    ]


def normalize_player_prices(bootstrap: dict) -> list[dict]:
    return [{"player_id": el["id"], "value_tenths": el["now_cost"]} for el in bootstrap["elements"]]


def normalize_player_ownership(bootstrap: dict) -> list[dict]:
    return [
        {"player_id": el["id"], "selected_by_percent": float(el["selected_by_percent"])}
        for el in bootstrap["elements"]
    ]


_STATS_FIELDS = [
    "total_points",
    "event_points",
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "bonus",
    "bps",
    "starts",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "expected_goals_conceded",
    "defensive_contribution",
    "ict_index",
    "form",
    "points_per_game",
    "now_cost",
    "chance_of_playing_next_round",
    "chance_of_playing_this_round",
]

_FLOAT_FIELDS = {
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "expected_goals_conceded",
    "ict_index",
    "form",
    "points_per_game",
}


def _coerce_stat(field: str, value: Any) -> Any:
    if value is None:
        return None
    return float(value) if field in _FLOAT_FIELDS else int(value)


def normalize_player_stats(bootstrap: dict) -> list[dict]:
    rows = []
    for el in bootstrap["elements"]:
        row = {"player_id": el["id"]}
        for field in _STATS_FIELDS:
            row[field] = _coerce_stat(field, el.get(field))
        digest_source = json.dumps({k: row[k] for k in _STATS_FIELDS}, sort_keys=True)
        row["stats_hash"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
        rows.append(row)
    return rows


def normalize_fixtures(fixtures_raw: list) -> list[dict]:
    return [
        {
            "id": f["id"],
            "code": f["code"],
            "event": f.get("event"),
            "kickoff_time": f.get("kickoff_time"),
            "team_h": f["team_h"],
            "team_a": f["team_a"],
            "team_h_score": f.get("team_h_score"),
            "team_a_score": f.get("team_a_score"),
            "team_h_difficulty": f.get("team_h_difficulty"),
            "team_a_difficulty": f.get("team_a_difficulty"),
            "finished": int(bool(f.get("finished"))),
            "started": int(bool(f.get("started"))),
        }
        for f in fixtures_raw
    ]


def flatten_rules(bootstrap: dict) -> dict[str, Any]:
    """Flatten game_config.rules + game_config.scoring into dotted rule_key -> value."""
    game_config = bootstrap.get("game_config", {})
    flat: dict[str, Any] = {}

    def _walk(prefix: str, obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(f"{prefix}.{k}" if prefix else k, v)
        else:
            flat[prefix] = obj

    for section in ("rules", "scoring"):
        _walk(section, game_config.get(section, {}))

    return flat
