"""DOES BEING LEFT ON THE BENCH, OR OUT OF THE SQUAD, CARRY TO THE NEXT MATCH?

The minutes model reads a player's last ten matches from Understat, so one benching in the middle of a run of starts barely
moves it. The squad sheets stored from FotMob say who was in the eleven, on the bench, or in neither list. For every regular
(two or more starts in the three team matches before), this sets his role in one match against what happened in the next, and
against the minutes model's own leak-free chance of 60+ minutes for that next match.

First read (2026-10-25, 75 sheets, this season only): regulars who started went on to 60+ minutes 81% of the time against a
model 76%; those on the bench and used 43%, unused 32%, against a model 57%; those left out of the squad while not flagged
injured 36% (11 cases). `SHEET_FACTOR` = 0.8 (that gap shrunk toward 1 with 30 pseudo-matches) was first applied after a bench
seat as well. Revised 2026-10-27 once the start percentage was blended into the minutes (`apply_start_probability`): on 216
pairs the blend already predicts 30% for players who were on the bench last match against 32% realised (74 cases), and the cap
made that worse (Brier 0.186 against 0.177); for players left out of the squad it predicts 41% against 20% realised (15 cases),
so the cap now applies to NOT_IN_SQUAD only, to the next gameweek's fixture, keeping the lower chance of 60+ minutes."""
import sqlite3
from collections import defaultdict

SHEET_FACTOR = 0.8
SHRINK_MATCHES = 30


def _status_timeline(conn: sqlite3.Connection) -> dict[int, list[tuple[str, str]]]:
    timeline: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT entity_id AS pid, new_value AS n, detected_at AS t FROM change_events "
        "WHERE event_type='status_change' AND entity='player' ORDER BY detected_at"
    ):
        timeline[r["pid"]].append((r["t"], r["n"]))
    return timeline


def _status_at(timeline: dict, pid: int, when: str) -> str | None:
    status = None
    for t, n in timeline.get(pid, []):
        if t > when:
            break
        status = n
    return status


def sheet_study(conn: sqlite3.Connection) -> dict:
    from fpl_agent.models.minutes_distribution import minutes_bucket_probabilities
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    timeline = _status_timeline(conn)
    rows = conn.execute(
        """
        SELECT p.id AS pid, mi.kickoff_utc AS k,
               (SELECT COUNT(*) FROM player_match_state t WHERE t.match_id = mi.id AND t.team_id = p.team_id) AS team_rows,
               s.started AS st, s.minutes AS mn
        FROM players p
        JOIN match_intelligence mi ON (mi.home_team_id = p.team_id OR mi.away_team_id = p.team_id)
        LEFT JOIN player_match_state s ON s.match_id = mi.id AND s.player_id = p.id
        WHERE mi.status = 'FULL_TIME' AND COALESCE(mi.lineup_type, '') != 'predicted' AND p.removed = 0
        ORDER BY p.id, mi.kickoff_utc
        """
    ).fetchall()
    sequences: dict[int, list] = defaultdict(list)
    for r in rows:
        if r["team_rows"] > 0:
            sequences[r["pid"]].append(r)

    groups: dict[str, list[tuple[bool, bool, float]]] = defaultdict(list)
    for pid, seq in sequences.items():
        for i in range(3, len(seq) - 1):
            if sum(1 for x in seq[i - 3:i] if x["st"] == 1) < 2:
                continue
            here, nxt = seq[i], seq[i + 1]
            if here["st"] == 1:
                role = "started"
            elif here["st"] is None:
                role = "left out, flagged" if _status_at(timeline, pid, here["k"]) in ("i", "s", "u") else "left out"
            else:
                role = "bench, used" if (here["mn"] or 0) > 0 else "bench, unused"
            model = minutes_bucket_probabilities(conn, pid, season, nxt["k"][:10]).p_full
            groups[role].append((nxt["st"] == 1, (nxt["mn"] or 0) >= 60, model))

    out = []
    for role in ("started", "bench, used", "bench, unused", "left out", "left out, flagged"):
        v = groups.get(role, [])
        n = len(v)
        if not n:
            continue
        real = sum(x[1] for x in v) / n
        model = sum(x[2] for x in v) / n
        shrunk = (n * real + SHRINK_MATCHES * model) / (n * model + SHRINK_MATCHES * model) if model else None
        out.append({
            "role": role, "n": n, "started": round(sum(x[0] for x in v) / n, 3), "played_60": round(real, 3),
            "model_60": round(model, 3), "shrunk_ratio": round(shrunk, 3) if shrunk is not None else None,
        })
    return {"groups": out, "factor_in_use": SHEET_FACTOR}
