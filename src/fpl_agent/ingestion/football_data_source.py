"""Historical + live-season match results and odds from football-data.co.uk
(free CSV, no auth, updated through the live season as well as historical
archives - one source covers both backfill and in-season refresh)."""
from datetime import datetime


class FootballDataFetchError(Exception):
    pass


def _parse_date(raw: str) -> str:
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def _float_or_none(row: dict, key: str) -> float | None:
    val = row.get(key, "").strip() if row.get(key) else ""
    return float(val) if val else None


def parse_football_data_row(row: dict) -> dict | None:
    if not row.get("FTHG") or not row.get("FTAG"):
        return None  # unplayed/postponed fixture row

    odds = None
    for prefix, label in (("Avg", "avg"), ("B365", "bet365")):
        home_win = _float_or_none(row, f"{prefix}H")
        draw = _float_or_none(row, f"{prefix}D")
        away_win = _float_or_none(row, f"{prefix}A")
        if home_win and draw and away_win:
            odds = {
                "bookmaker": label,
                "home_win": home_win, "draw": draw, "away_win": away_win,
                "over_2_5": _float_or_none(row, f"{prefix}>2.5"),
                "under_2_5": _float_or_none(row, f"{prefix}<2.5"),
            }
            break

    return {
        "match_date": _parse_date(row["Date"]),
        "home_team_name": row["HomeTeam"],
        "away_team_name": row["AwayTeam"],
        "home_goals": int(row["FTHG"]),
        "away_goals": int(row["FTAG"]),
        "odds": odds,
    }
