"""DOES THE START-PERCENTAGE FEED MEAN WHAT IT SAYS, AND WHAT IS IT WORTH NEXT TO THE PLAYER'S OWN RECORD?

Each stored reading is paired with his team's next finished match whose official squad sheet is stored, and the realised start
rate is reported by the band the reading fell in. A player in neither the eleven nor the bench counts as not having started: a
pairing that kept only players with a lineup row (the first version) dropped exactly the players the feed gets wrong and read
too kind. Each player-match pair is counted once, by the last reading before kickoff: the figure the projections would have
acted on.

`rules` scores four ways of predicting 60+ minutes on the same pairs (Brier, lower is better): the player's own record as of
the match date, the reading alone, the blend the projections use (`START_BLEND_WEIGHT`), and the discount-only rule they used
before 2026-10-27. First read (216 pairs, 2026-10-27): 0.179, 0.179, 0.168, 0.186."""
import sqlite3

BANDS = ((0, 10), (10, 30), (30, 50), (50, 70), (70, 85), (85, 101))


def _pairs(conn: sqlite3.Connection) -> dict[tuple[int, int], tuple[int, str, int, int]]:
    """{(player_id, match_id): (reading, kickoff day, started, minutes)}, last reading before kickoff."""
    readings = conn.execute(
        "SELECT h.player_id, h.start_percent, h.fetched_at, p.team_id FROM player_start_probability_history h "
        "JOIN players p ON p.id = h.player_id ORDER BY h.fetched_at"
    ).fetchall()
    matches = conn.execute(
        "SELECT m.id, m.kickoff_utc, m.home_team_id, m.away_team_id FROM match_intelligence m "
        "WHERE m.status = 'FULL_TIME' AND COALESCE(m.lineup_type, '') != 'predicted' AND m.kickoff_utc IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM player_match_state s WHERE s.match_id = m.id) ORDER BY m.kickoff_utc"
    ).fetchall()
    by_team: dict[int, list] = {}
    for m in matches:
        by_team.setdefault(m["home_team_id"], []).append(m)
        by_team.setdefault(m["away_team_id"], []).append(m)
    last: dict[tuple[int, int], tuple[int, str, int, int]] = {}
    for r in readings:
        nxt = next((m for m in by_team.get(r["team_id"], []) if m["kickoff_utc"] > r["fetched_at"]), None)
        if nxt is None:
            continue
        row = conn.execute(
            "SELECT started, minutes FROM player_match_state WHERE match_id = ? AND player_id = ?", (nxt["id"], r["player_id"])
        ).fetchone()
        started = int(row["started"] or 0) if row else 0
        minutes = int(row["minutes"] or 0) if row else 0
        last[(r["player_id"], nxt["id"])] = (r["start_percent"], nxt["kickoff_utc"][:10], started, minutes)
    return last


def _rule_scores(conn: sqlite3.Connection, pairs: dict) -> dict | None:
    from fpl_agent.ingestion.lineup_probability_source import START_BLEND_WEIGHT, START_PERCENT_CEILING, start_percent_minutes_factor
    from fpl_agent.models.minutes_distribution import minutes_bucket_probabilities
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    if season is None or not pairs:
        return None
    totals = {"record": 0.0, "reading": 0.0, "blend": 0.0, "old_discount": 0.0}
    realised = 0
    n = 0
    for (pid, _mid), (pct, day, _started, minutes) in pairs.items():
        try:
            base = minutes_bucket_probabilities(conn, pid, season, day).p_full
        except Exception:
            continue
        y = 1.0 if minutes >= 60 else 0.0
        reading = pct / 100.0
        preds = {
            "record": base, "reading": reading, "blend": START_BLEND_WEIGHT * reading + (1 - START_BLEND_WEIGHT) * base,
            "old_discount": base * start_percent_minutes_factor(pct),
        }
        for k, p in preds.items():
            totals[k] += (p - y) ** 2
        realised += y
        n += 1
    if n == 0:
        return None
    return {"n": n, "played_60": round(realised / n, 3), **{k: round(v / n, 4) for k, v in totals.items()}}


def calibration(conn: sqlite3.Connection) -> dict:
    last = _pairs(conn)
    counts = {b: [0, 0] for b in BANDS}
    for pct, _day, started, _minutes in last.values():
        for lo, hi in BANDS:
            if lo <= pct < hi:
                counts[(lo, hi)][0] += 1
                counts[(lo, hi)][1] += started
                break
    bands = [
        {"band": f"{lo}-{min(hi, 100)}%", "n": n, "started": k, "rate": round(k / n, 3) if n else None}
        for (lo, hi), (n, k) in counts.items()
    ]
    return {"bands": bands, "pairs": len(last), "rules": _rule_scores(conn, last)}
