"""Solio Analytics independent-model benchmark (public, no-auth JSON,
https://fpl.solioanalytics.com/api/data/latest.json - live-verified this
session: real HTTP 200, ~27KB, one payload per current gameweek).

Real, disclosed schema (confirmed live, not assumed): a single JSON object
keyed by `generatedAt`/`gameweek`/`deadlineIso`/`source` plus eleven top-N
lists (`topProjected`, `topCaptains`, `topDifferentials`, `topGoals`,
`topAssists`, `bestCleanSheets`, `topBonus`, `topDefCon`,
`bestAttackingFixtures`, `topTransfersIn`, `topTransfersOut`) - Solio
publishes overlapping top-N slices, not one flat per-player table, so the
same player can appear in several lists with different fields populated.
No player id is published, only a free-text display name (e.g.
"B.Fernandes") and a 3-letter team code for the player lists, or a full
team display name for the two team-level lists - resolved against this
project's own `players`/`teams` tables below, same crosswalk primitives
`predicted_lineups_source.py`/`market_identity.py` already use for other
free-text sources.

Cadence: Solio states a ~4h refresh; `should_sync` gates on `app_meta`'s own
`solio_last_synced_at` marker (same pattern `_maybe_trigger_strategic_plan_recompute`
uses for its own overlap guard) rather than polling every scheduled cycle -
this project's own standing "respect a source's stated cadence" rule.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from fpl_agent.config import load_freshness
from fpl_agent.ingestion.raw_store import save_raw

_URL = "https://fpl.solioanalytics.com/api/data/latest.json"
_TIMEOUT_SECONDS = 15
_HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-agent personal decision-support tool)"}
SOURCE_NAME = "solio"

# Player-list category -> which of its own fields map onto solio_player_projection's
# columns. Every category shares name/team/position/price/ownership/prPoints where
# present; only the category-specific extra fields differ.
_PLAYER_LIST_KEYS = (
    "topProjected", "topCaptains", "topDifferentials", "topGoals",
    "topAssists", "topBonus", "topDefCon", "topTransfersIn", "topTransfersOut",
)
_TEAM_LIST_KEYS = ("bestCleanSheets", "bestAttackingFixtures")


class SolioFetchError(Exception):
    pass


@dataclass(frozen=True)
class SolioPlayerRow:
    source_name: str
    team_short: str | None
    position: str | None
    price: int | None
    ownership: float | None
    pr_points: float | None
    captain_proj_points: float | None
    leverage: float | None
    pr_goals: float | None
    pr_points_from_goals: float | None
    pr_assists: float | None
    pr_points_from_assists: float | None
    pr_bonus_points: float | None
    pr_defcon_prob: float | None
    pr_defcon_points: float | None
    transfers_in: int | None
    transfers_out: int | None
    categories: tuple[str, ...]


@dataclass(frozen=True)
class SolioTeamRow:
    team_name: str
    pr_goals_for: float | None
    pr_goals_against: float | None
    cs_prob: float | None
    categories: tuple[str, ...]


def fetch_solio_payload() -> dict:
    """Real HTTP GET, no key, no login - raises `SolioFetchError` on any
    network/HTTP/parse/shape failure so callers decide how to log it, same
    fail-soft-past-this-module convention `livefpl_source.py` uses."""
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        status = f"HTTP {response.status_code}" if response is not None else "request error"
        raise SolioFetchError(f"solio request failed: {status} ({_URL})") from exc
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SolioFetchError(f"solio returned non-JSON response ({_URL})") from exc
    if not isinstance(payload, dict) or "gameweek" not in payload:
        raise SolioFetchError(f"solio response missing expected 'gameweek' field ({_URL})")
    return payload


def parse_player_rows(payload: dict) -> dict[str, SolioPlayerRow]:
    """Merges every player-list category into one row per distinct
    `source_name` - later categories only fill fields the earlier ones left
    None, never overwrite an already-populated field (every category that
    shares a field, e.g. `prPoints`, publishes the identical value for the
    same player - confirmed against the real payload - so first-wins is
    equivalent to last-wins here, just simpler)."""
    merged: dict[str, dict] = {}
    for category in _PLAYER_LIST_KEYS:
        for item in payload.get(category, []):
            name = item.get("name")
            if not name:
                continue
            row = merged.setdefault(name, {"categories": []})
            row["categories"].append(category)
            row.setdefault("team_short", item.get("team"))
            row.setdefault("position", item.get("position"))
            row.setdefault("price", item.get("price"))
            row.setdefault("ownership", item.get("ownership"))
            row.setdefault("pr_points", item.get("prPoints"))
            if "captainProjPoints" in item:
                row.setdefault("captain_proj_points", item.get("captainProjPoints"))
            if "leverage" in item:
                row.setdefault("leverage", item.get("leverage"))
            if "prGoals" in item:
                row.setdefault("pr_goals", item.get("prGoals"))
                row.setdefault("pr_points_from_goals", item.get("prPointsFromGoals"))
            if "prAssists" in item:
                row.setdefault("pr_assists", item.get("prAssists"))
                row.setdefault("pr_points_from_assists", item.get("prPointsFromAssists"))
            if "prBonusPoints" in item:
                row.setdefault("pr_bonus_points", item.get("prBonusPoints"))
            if "prDefConProb" in item:
                row.setdefault("pr_defcon_prob", item.get("prDefConProb"))
                row.setdefault("pr_defcon_points", item.get("prDefConPoints"))
            if "transfers" in item:
                if category == "topTransfersIn":
                    row.setdefault("transfers_in", item.get("transfers"))
                else:
                    row.setdefault("transfers_out", item.get("transfers"))

    result = {}
    for name, row in merged.items():
        result[name] = SolioPlayerRow(
            source_name=name,
            team_short=row.get("team_short"),
            position=row.get("position"),
            price=row.get("price"),
            ownership=row.get("ownership"),
            pr_points=row.get("pr_points"),
            captain_proj_points=row.get("captain_proj_points"),
            leverage=row.get("leverage"),
            pr_goals=row.get("pr_goals"),
            pr_points_from_goals=row.get("pr_points_from_goals"),
            pr_assists=row.get("pr_assists"),
            pr_points_from_assists=row.get("pr_points_from_assists"),
            pr_bonus_points=row.get("pr_bonus_points"),
            pr_defcon_prob=row.get("pr_defcon_prob"),
            pr_defcon_points=row.get("pr_defcon_points"),
            transfers_in=row.get("transfers_in"),
            transfers_out=row.get("transfers_out"),
            categories=tuple(row["categories"]),
        )
    return result


def parse_team_rows(payload: dict) -> dict[str, SolioTeamRow]:
    merged: dict[str, dict] = {}
    for category in _TEAM_LIST_KEYS:
        for item in payload.get(category, []):
            name = item.get("team")
            if not name:
                continue
            row = merged.setdefault(name, {"categories": []})
            row["categories"].append(category)
            row.setdefault("pr_goals_for", item.get("prGoalsFor"))
            row.setdefault("pr_goals_against", item.get("prGoalsAgainst"))
            row.setdefault("cs_prob", item.get("csProb"))

    return {
        name: SolioTeamRow(
            team_name=name,
            pr_goals_for=row.get("pr_goals_for"),
            pr_goals_against=row.get("pr_goals_against"),
            cs_prob=row.get("cs_prob"),
            categories=tuple(row["categories"]),
        )
        for name, row in merged.items()
    }


def _resolve_team_id_by_short_code(conn, team_short: str | None) -> int | None:
    if not team_short:
        return None
    row = conn.execute("SELECT id FROM teams WHERE short_name=?", (team_short,)).fetchone()
    return row["id"] if row else None


def _resolve_team_id_by_display_name(conn, team_name: str) -> int | None:
    from fpl_agent.ingestion.market_identity import normalize_common_team_name

    canonical = normalize_common_team_name(team_name)
    row = conn.execute("SELECT id FROM teams WHERE name=?", (canonical,)).fetchone()
    return row["id"] if row else None


def _resolve_player_id(conn, source_name: str, team_id: int | None) -> int | None:
    from fpl_agent.ingestion.market_identity import resolve_player_id

    return resolve_player_id(conn, SOURCE_NAME, source_name, team_id=team_id)


def store_snapshot(conn, payload: dict, retrieved_at: str | None = None, raw_path: str | None = None) -> dict:
    """Parses + upserts one full snapshot. Idempotent per (gameweek,
    generated_at): re-running against the same Solio model run replaces that
    snapshot's own rows rather than accumulating duplicates (Solio's
    `generatedAt` only advances when its own model actually re-runs, so
    calling this more often than that is a harmless no-op re-store, not
    spurious history)."""
    retrieved_at = retrieved_at or datetime.now(timezone.utc).isoformat()
    gameweek = payload["gameweek"]
    generated_at = payload.get("generatedAt", retrieved_at)

    existing = conn.execute(
        "SELECT id FROM solio_snapshot WHERE gameweek=? AND generated_at=?", (gameweek, generated_at)
    ).fetchone()
    if existing:
        snapshot_id = existing["id"]
        conn.execute("DELETE FROM solio_player_projection WHERE snapshot_id=?", (snapshot_id,))
        conn.execute("DELETE FROM solio_team_projection WHERE snapshot_id=?", (snapshot_id,))
    else:
        cur = conn.execute(
            "INSERT INTO solio_snapshot (gameweek, generated_at, deadline_iso, source_url, retrieved_at, raw_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (gameweek, generated_at, payload.get("deadlineIso"), payload.get("source", _URL), retrieved_at, raw_path),
        )
        snapshot_id = cur.lastrowid

    player_rows = parse_player_rows(payload)
    matched = 0
    for row in player_rows.values():
        team_id = _resolve_team_id_by_short_code(conn, row.team_short)
        player_id = _resolve_player_id(conn, row.source_name, team_id)
        if player_id is not None:
            matched += 1
        conn.execute(
            "INSERT INTO solio_player_projection ("
            "snapshot_id, player_id, source_name, team_short, position, price, ownership, pr_points, "
            "captain_proj_points, leverage, pr_goals, pr_points_from_goals, pr_assists, pr_points_from_assists, "
            "pr_bonus_points, pr_defcon_prob, pr_defcon_points, transfers_in, transfers_out, categories"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot_id, player_id, row.source_name, row.team_short, row.position, row.price, row.ownership,
                row.pr_points, row.captain_proj_points, row.leverage, row.pr_goals, row.pr_points_from_goals,
                row.pr_assists, row.pr_points_from_assists, row.pr_bonus_points, row.pr_defcon_prob,
                row.pr_defcon_points, row.transfers_in, row.transfers_out, ",".join(row.categories),
            ),
        )

    team_rows = parse_team_rows(payload)
    for row in team_rows.values():
        team_id = _resolve_team_id_by_display_name(conn, row.team_name)
        conn.execute(
            "INSERT INTO solio_team_projection (snapshot_id, team_id, team_name, pr_goals_for, pr_goals_against, "
            "cs_prob, categories) VALUES (?,?,?,?,?,?,?)",
            (snapshot_id, team_id, row.team_name, row.pr_goals_for, row.pr_goals_against, row.cs_prob,
             ",".join(row.categories)),
        )

    conn.commit()
    return {
        "snapshot_id": snapshot_id,
        "gameweek": gameweek,
        "generated_at": generated_at,
        "players_total": len(player_rows),
        "players_matched": matched,
        "players_unmatched": len(player_rows) - matched,
        "teams_total": len(team_rows),
    }


def _solio_cadence_minutes() -> float:
    freshness = load_freshness()
    return float(freshness.get("solio", 240))


def should_sync(conn, force: bool = False) -> tuple[bool, str]:
    """Cadence gate on `app_meta['solio_last_synced_at']` - Solio itself
    states a ~4h refresh, so anything tighter than that is polling a source
    that hasn't actually re-run its model yet."""
    if force:
        return True, "forced"
    row = conn.execute("SELECT value FROM app_meta WHERE key='solio_last_synced_at'").fetchone()
    if row is None:
        return True, "never synced"
    last = datetime.fromisoformat(row["value"])
    age_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
    cadence = _solio_cadence_minutes()
    if age_minutes >= cadence:
        return True, f"stale ({age_minutes:.0f}min >= {cadence:.0f}min cadence)"
    return False, f"fresh ({age_minutes:.0f}min old, cadence {cadence:.0f}min)"


def sync_solio(conn, force: bool = False) -> dict:
    """The one real entrypoint (CLI + `run_scheduled`) - cadence-gates,
    fetches, stores, and marks `solio_last_synced_at`. Never raises past
    this function on a real fetch failure (mirrors every other opt-in
    source's `run_scheduled` posture) - returns `skipped`/`error` in the
    result dict instead."""
    do_sync, reason = should_sync(conn, force=force)
    if not do_sync:
        return {"skipped": True, "reason": reason}

    try:
        payload = fetch_solio_payload()
    except SolioFetchError as exc:
        return {"skipped": False, "error": str(exc)}

    raw_path = save_raw(SOURCE_NAME, payload)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    result = store_snapshot(conn, payload, retrieved_at=retrieved_at, raw_path=str(raw_path))
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('solio_last_synced_at', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (retrieved_at, retrieved_at),
    )
    conn.commit()
    result["skipped"] = False
    result["reason"] = reason
    return result
