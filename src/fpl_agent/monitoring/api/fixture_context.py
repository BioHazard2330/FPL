"""Real per-team upcoming-fixture context, keyed by `teams.code`.

2026-09-09, "more football" pass. The COMMAND and MY TEAM payloads carried a
squad but no football around it - every player tile showed a projection with
no opponent, no venue and no difficulty, which is the first thing any FPL
manager actually looks at. `myteam_payload.py`'s own module docstring already
disclosed "next-fixture difficulty" as a scoped-out gap; this closes it.

Nothing here is new intelligence. It reuses `models/fixtures.py::
team_fixture_ticker` unchanged - the same real FPL 1-5 FDR convention the
FOOTBALL screen's own ticker already renders - so a fixture's difficulty can
never disagree between two screens.

Keyed by `teams.code` (not `teams.id`) because that is the identifier every
player row in those payloads already carries, and the identifier the browser
already uses to resolve a crest. A team with no upcoming fixture in the
window simply has no entry; a blank gameweek produces no entry for that
event. Neither is padded into a fabricated fixture.

Deliberately NOT wired into `run_scheduled` or any scheduled task - this is
read-only payload shaping on the HTTP path, called when a browser asks for a
screen. It cannot affect the automation cycle.
"""
import sqlite3

_DEFAULT_WINDOW_GW = 5


def fixture_context_by_team_code(
    conn: sqlite3.Connection, team_ids: set[int] | list[int], n_gw: int = _DEFAULT_WINDOW_GW
) -> dict[str, list[dict]]:
    """One indexed ticker read per distinct team (at most 20, in practice the
    handful of clubs a real squad spans). Returns `{team_code: [entry, ...]}`
    with string keys, since JSON object keys are strings and a client that
    round-trips this must not have to guess the key type."""
    from fpl_agent.models.fixtures import team_fixture_ticker

    ids = {int(t) for t in team_ids if t is not None}
    if not ids:
        return {}

    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, code, short_name FROM teams WHERE id IN ({placeholders})", tuple(ids)
    ).fetchall()
    code_by_id = {r["id"]: r["code"] for r in rows}

    out: dict[str, list[dict]] = {}
    for r in rows:
        entries = team_fixture_ticker(conn, r["id"], n_gw=n_gw)
        if not entries:
            continue
        out[str(r["code"])] = [
            {
                "event": e.event,
                "opponent_short": e.opponent_short,
                "opponent_code": code_by_id.get(e.opponent_team_id),
                "is_home": e.is_home,
                "difficulty": e.difficulty,
            }
            for e in entries
        ]

    # `opponent_code` needs the opponent's own code, which is usually a team
    # OUTSIDE the requested set - resolve those in one extra query rather than
    # leaving a real opponent crest unrenderable.
    missing = {
        e["opponent_short"]
        for entries in out.values()
        for e in entries
        if e["opponent_code"] is None
    }
    if missing:
        ph = ",".join("?" * len(missing))
        code_by_short = {
            r["short_name"]: r["code"]
            for r in conn.execute(f"SELECT short_name, code FROM teams WHERE short_name IN ({ph})", tuple(missing))
        }
        for entries in out.values():
            for e in entries:
                if e["opponent_code"] is None:
                    e["opponent_code"] = code_by_short.get(e["opponent_short"])
    return out


def squad_team_ids(conn: sqlite3.Connection, squad_ids: set[int]) -> set[int]:
    """The real clubs a squad spans. Empty set for an empty squad - never a
    fallback to "all teams", which would silently make a squad-scoped ticker
    league-wide."""
    if not squad_ids:
        return set()
    placeholders = ",".join("?" * len(squad_ids))
    return {
        r["team_id"]
        for r in conn.execute(
            f"SELECT DISTINCT team_id FROM players WHERE id IN ({placeholders})", tuple(squad_ids)
        ).fetchall()
        if r["team_id"] is not None
    }
