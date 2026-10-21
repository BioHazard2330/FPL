"""HOW MUCH TO TRUST A FOOTBALL SIGNAL - what repeats, measured.

Two reads, both computed from stored data and cached for ten minutes:
`reliability` (models/signal_reliability.py: how well each match-level metric
carries into the team's or player's next match) and `streaks`
(backtesting/streak_calibration.py: what a two-match hot or cold streak is
worth next match against a flat shrunk season rate, which is where the
qualitative adjustment sizes come from).
"""
import time

from fpl_agent.backtesting.streak_calibration import streak_table, suggested_fraction
from fpl_agent.models.qualitative_feed import CALIBRATED_FRACTIONS, MAX_ADJUSTMENT_FRACTION
from fpl_agent.models.signal_reliability import reliability

_TTL_SECONDS = 600
_cache: dict = {"at": 0.0, "payload": None}


def build_signals_payload(ctx=None) -> dict:
    now = time.time()
    if _cache["payload"] is not None and now - _cache["at"] < _TTL_SECONDS:
        return _cache["payload"]
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        rel = reliability(conn)
        table = streak_table(conn)
        stories = conn.execute("SELECT COUNT(*) AS n FROM match_story").fetchone()["n"]
    finally:
        conn.close()
    streaks = []
    for row in table["rows"]:
        streaks.append({
            **row,
            "applied_fraction": CALIBRATED_FRACTIONS.get((row["signal"], row["direction"]), MAX_ADJUSTMENT_FRACTION),
            "data_supported": suggested_fraction(row),
        })
    order = {"persistent": 0, "unclear": 1, "none": 2, "too few": 3}
    metrics = [{"key": key, **value} for key, value in rel["metrics"].items()]
    metrics.sort(key=lambda m: (order[m["verdict"]], -(m["r"] or -9)))
    payload = {
        "stories": stories,
        "metrics": metrics,
        "streaks": streaks,
        "streak_pairs": table["pairs"],
        "default_fraction": MAX_ADJUSTMENT_FRACTION,
        "method": (
            "Persistence is the correlation between a side's or player's average over its previous matches (at least three) and its next match, across every pair, "
            "with a 90% Fisher-z interval; the verdict is persistent when the interval's lower bound is above 0.10, none when its upper bound is below it. "
            "Streaks compare the next match's output with a flat empirical-Bayes season rate that already contains the streak; 1.00 means the baseline already knew."
        ),
    }
    _cache["at"], _cache["payload"] = now, payload
    return payload


build_signals_payload.needs_context = False  # type: ignore[attr-defined]
