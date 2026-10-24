"""DOES THE START-PERCENTAGE FEED MEAN WHAT IT SAYS?

The projections discount a player's minutes by the feed's "Start %" (`expected_minutes`), and until the history table existed
nobody could check the figure against what then happened. Each stored reading is paired with the player's next match after it
was fetched, and the realised start rate is reported by the band the reading fell in. A feed that is honest has 80% readings
starting about four times in five; a band that does not is the evidence for or against trusting it.

Only matches that have finished and carry a lineup row count, and each player-match pair is counted once, by the last reading
before kickoff: the figure the projections would have acted on."""
import sqlite3

BANDS = ((0, 10), (10, 30), (30, 50), (50, 70), (70, 85), (85, 101))


def calibration(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT h.player_id, h.start_percent, h.fetched_at, "
        "(SELECT s.started FROM player_match_state s JOIN match_intelligence m ON m.id = s.match_id "
        " WHERE s.player_id = h.player_id AND m.kickoff_utc > h.fetched_at AND m.status = 'FULL_TIME' "
        " ORDER BY m.kickoff_utc LIMIT 1) AS started, "
        "(SELECT s.match_id FROM player_match_state s JOIN match_intelligence m ON m.id = s.match_id "
        " WHERE s.player_id = h.player_id AND m.kickoff_utc > h.fetched_at AND m.status = 'FULL_TIME' "
        " ORDER BY m.kickoff_utc LIMIT 1) AS match_id "
        "FROM player_start_probability_history h ORDER BY h.fetched_at"
    ).fetchall()
    last: dict[tuple, tuple] = {}
    for r in rows:
        if r["started"] is not None:
            last[(r["player_id"], r["match_id"])] = (r["start_percent"], bool(r["started"]))
    counts = {b: [0, 0] for b in BANDS}
    for pct, started in last.values():
        for lo, hi in BANDS:
            if lo <= pct < hi:
                counts[(lo, hi)][0] += 1
                counts[(lo, hi)][1] += int(started)
                break
    bands = [
        {"band": f"{lo}-{min(hi, 100)}%", "n": n, "started": k, "rate": round(k / n, 3) if n else None}
        for (lo, hi), (n, k) in counts.items()
    ]
    return {"bands": bands, "pairs": len(last)}
