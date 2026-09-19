"""THE RECEIPTS - the optimizer measured against YOUR decisions, in points.

Direct user statement: "i still dont use the optimizer to date for my
decisions", followed by the right instruction - measure what it suggested
against what you actually did.

**The first version of this screen measured the wrong thing.** It reported
the optimizer's chosen action against *its own rejected runner-up*
(`models/decision_calibration.py`), and on that basis showed +22.0 net,
5-1, 83.3%. Neither side of that comparison is what the user did, so it
could not answer the only question that matters, and it pointed the
opposite way from the truth. Run properly against the real squads
(`models/counterfactual_ledger.py`), the optimizer is **behind** over the
same period.

So the headline here is the counterfactual ledger: your real score, its
recommended squad's score, and the do-nothing baseline, gameweek by
gameweek. The old internal-consistency numbers are still carried, clearly
labelled for what they actually are, because "did it beat its own second
choice" is a real question - just not this one.

Honesty rules enforced here rather than left to the UI:

- **A gameweek with no logged recommendation is absent, not zero.** GW5 has
  none at all (a wildcard was played and the pipeline recorded nothing), and
  the payload says so.
- **Totals only span comparable gameweeks.** Summing across gaps would
  flatter whichever side happened to have fewer of them.
- **A chip you played that it never suggested is recorded on the row**, so a
  lopsided gap is never read as a like-for-like loss.
- **ROLL is always shown.** A recommendation that scores exactly what doing
  nothing scored is the single most useful thing this screen can surface,
  and it has already happened once.
"""
from fpl_agent.models.counterfactual_ledger import build_counterfactual_ledger, ledger_totals
from fpl_agent.models.decision_calibration import decision_backtest_summary
from fpl_agent.monitoring.dashboard.context import DashboardContext

_MIN_MEANINGFUL_SAMPLE = 8

_CHIP_LABEL = {
    "3xc": "Triple Captain",
    "freehit": "Free Hit",
    "wildcard": "Wildcard",
    "bboost": "Bench Boost",
}


def build_receipts_payload(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        rows = build_counterfactual_ledger(conn)
        if not rows:
            return {
                "has_record": False,
                "reason": (
                    "Not enough synced history yet. This fills in once there are two "
                    "consecutive gameweeks of real squads to compare."
                ),
            }

        totals = ledger_totals(rows)
        names = {r[0]: r[1] for r in conn.execute("SELECT id, web_name FROM players")}

        def action_label(row) -> str | None:
            if row.optimizer_action in (None, "ROLL"):
                return row.optimizer_action
            try:
                out_id, in_id = (int(x) for x in row.optimizer_action.split(" -> "))
            except (ValueError, AttributeError):
                return row.optimizer_action
            return f"{names.get(out_id, out_id)} → {names.get(in_id, in_id)}"

        ledger = [{
            "event": r.event,
            "your_points": r.your_points,
            "your_chip": r.your_chip,
            "your_chip_label": _CHIP_LABEL.get(r.your_chip or "", r.your_chip),
            "your_transfers": r.your_transfers,
            "optimizer_points": r.optimizer_points,
            "optimizer_action": action_label(r),
            "roll_points": r.roll_points,
            "delta_vs_you": r.delta_vs_you,
            "followed": r.followed,
            "note": r.note,
            # A recommendation worth exactly what doing nothing was worth.
            # Called out explicitly because it is invisible in any
            # win/loss framing and is the clearest possible evidence that
            # the engine does not know when to roll.
            "worthless_vs_roll": (
                r.optimizer_points is not None
                and r.roll_points is not None
                and r.optimizer_points <= r.roll_points
            ),
        } for r in rows]

        internal = [{
            "kind": s.decision_kind,
            "n": s.n,
            "win_rate_pct": round((s.win_rate or 0.0) * 100, 1),
            "mean_advantage": s.mean_advantage,
            "thin": s.n < _MIN_MEANINGFUL_SAMPLE,
        } for s in decision_backtest_summary(conn)]

        never_rolled = all(
            r.optimizer_action not in (None, "ROLL") for r in rows if r.optimizer_action is not None
        )

        return {
            "has_record": True,
            "headline": {
                "your_total": totals.your_total,
                "your_total_all_events": totals.your_total_all_events,
                "optimizer_total": totals.optimizer_total,
                "roll_total": totals.roll_total,
                "delta": totals.delta,
                "comparable_events": totals.comparable_events,
                "events": totals.events,
                "followed_count": totals.followed_count,
                "recommendations_logged": totals.recommendations_logged,
                # Signed from the optimizer's point of view: negative means
                # your own decisions scored more.
                "optimizer_ahead": (totals.delta or 0) > 0,
            },
            "ledger": ledger,
            "flags": {
                "never_recommended_roll": never_rolled,
                "missing_recommendations": totals.events - totals.recommendations_logged,
                "followed_none": totals.followed_count == 0,
            },
            "internal_consistency": internal,
            "method": (
                "YOURS is your real score, validated against FPL's own recorded total for every "
                "finished gameweek. OPTIMIZER is your previous gameweek's squad with the transfer it "
                "actually recommended at that deadline, scored this gameweek. ROLL is that squad "
                "carried forward untouched. The optimizer column holds your previous starting eleven "
                "and captain, because it only ever proposed a transfer, never a lineup - so this "
                "isolates the transfer decision and does not credit or blame it for your own XI and "
                "captaincy changes."
            ),
            "correction": (
                "An earlier version of this screen compared the optimizer against its own rejected "
                "runner-up and reported it winning. Both sides of that comparison were hypothetical. "
                "This measures against what you actually did."
            ),
        }
    finally:
        conn.close()
