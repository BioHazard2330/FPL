"""The pundit's judgements: Claude's written calls on every club and manager (how they play, what it means for FPL, this
gameweek's matchup) and on the squad and its targets, made in a session from the Dugout's evidence and stored as
`data/judgements/gw{N}.json`. REASONING, not DERIVED: never a projection input; it shows on the Dugout, the previews and
the dossier as the pundit's voice, beside the numbers it was written from."""
import json
import re
import sqlite3
from pathlib import Path

DIR = Path(__file__).resolve().parents[3] / "data" / "judgements"


def latest(conn: sqlite3.Connection | None = None, directory: Path | None = None) -> dict | None:
    folder = directory or DIR
    if not folder.exists():
        return None
    files = sorted(folder.glob("gw*.json"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    if not files:
        return None
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    data["made_at"] = files[-1].stat().st_mtime
    return data


def for_club(data: dict | None, short: str) -> dict | None:
    return (data or {}).get("clubs", {}).get(short)


def for_player(data: dict | None, player_id: int) -> str | None:
    return (data or {}).get("players", {}).get(str(player_id))
