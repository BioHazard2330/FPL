"""Shot-level per-match player stats (xG/xA/shots/key passes) scraped from
Understat's public match pages. No official API exists; Understat embeds the
data as `var NAME = JSON.parse('...')` inside a <script> tag on each page -
this is the same technique documented by several open-source Understat
readers (e.g. understatapi, soccerdata). The embedded string is JSON, further
escaped as a JS string literal with \\xHH byte escapes for non-ASCII names -
the unicode_escape/latin1/utf-8 round-trip below reverses that."""
import json
import re


class UnderstatFetchError(Exception):
    pass


class UnderstatParseError(Exception):
    pass


def extract_json_var(html: str, var_name: str):
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*JSON\.parse\('(.*?)'\);"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        raise UnderstatParseError(f"could not find variable {var_name!r} in page")

    raw = match.group(1)
    try:
        decoded = raw.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
    except UnicodeDecodeError:
        decoded = raw  # payload had no byte-escapes to unwind (fine for ASCII-only fixtures)
    return json.loads(decoded)


def _row_from_entry(entry: dict, match_id: str, match_date: str, season: str) -> dict:
    return {
        "understat_match_id": match_id,
        "understat_player_id": entry["id"],
        "player_name": entry["player"],
        "team_name": entry["team"],
        "season": season,
        "match_date": match_date,
        "minutes": int(entry["minutes"]),
        "goals": int(entry["goals"]),
        "assists": int(entry["assists"]),
        "shots": int(entry["shots"]),
        "xg": float(entry["xG"]),
        "xa": float(entry["xA"]),
        "key_passes": int(entry["key_passes"]),
        "yellow_cards": int(entry["yellow_card"]),
        "red_cards": int(entry["red_card"]),
    }


def parse_understat_match_players(rosters_data: dict, match_id: str, match_date: str, season: str) -> list[dict]:
    rows = []
    for side in ("h", "a"):
        for entry in rosters_data.get(side, {}).values():
            rows.append(_row_from_entry(entry, match_id, match_date, season))
    return rows
