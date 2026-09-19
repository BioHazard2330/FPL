"""What your squad actually scored, against what the optimizer's squad would
have scored (2026-09-19).

This replaces the question `models/decision_calibration.py` answers. That
module compares the optimizer's chosen action against **its own rejected
runner-up** - two hypotheticals scoring each other. It is a legitimate
measure of internal consistency and a useless measure of usefulness, because
neither side is what the user did. Asked directly whether following the
optimizer would have beaten their own decisions, it cannot answer.

This module answers that, in points, per gameweek, against three columns:

- **YOURS** - your real squad and your real multipliers, which is simply
  your real score. Validated against `my_team_gw_summary.points`, FPL's own
  recorded total, for every finished gameweek before this module was
  trusted: GW1-5 matched exactly (51/100/56/82/4), including a triple
  captain at x3 and a free hit.
- **OPTIMIZER** - your PREVIOUS gameweek's squad with the transfer the
  optimizer actually recommended at that deadline applied, scored at this
  gameweek.
- **ROLL** - your previous gameweek's squad carried forward untouched. The
  "do nothing" baseline, included because a recommendation engine that
  cannot tell you when to do nothing is not giving advice.

## The honest caveats, stated here rather than buried

The optimizer column holds your PREVIOUS gameweek's starting eleven and
captain, because that is the only eleven its recommendation was ever
expressed against - it proposed a transfer, never a lineup. So this
isolates the TRANSFER decision and deliberately does not credit or blame it
for your own XI and captaincy changes.

Where you played a chip the optimizer never recommended, the comparison is
genuinely lopsided, and that is the finding rather than a flaw in the
method: a single-swap recommendation measured against a nine-transfer free
hit is exactly the mismatch that makes the advice unusable. The row records
the chip so the gap is never read as a like-for-like loss.

A gameweek with no recommendation on file produces `None`, not zero. There
is no recommendation at all for a gameweek where the pipeline never logged
one (GW5, where a wildcard was played), and that absence is itself reported.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.rules import current_season


@dataclass(frozen=True)
class LedgerRow:
    event: int
    your_points: int
    your_chip: str | None
    your_transfers: int
    your_transfer_cost: int
    optimizer_points: int | None
    optimizer_action: str | None
    roll_points: int | None
    # optimizer - yours. Positive means following it would have scored more.
    delta_vs_you: int | None
    # Did your real squad end up matching what it proposed?
    followed: bool | None
    note: str | None = None


def _squad_points(live: dict, picks: list[tuple[int, int]]) -> int:
    """(player_id, multiplier) pairs scored against one gameweek's real live
    stats. A player absent from the payload scores 0 rather than raising -
    an unmatched id is a data gap, and silently dropping the whole gameweek
    would hide it."""
    total = 0
    for player_id, multiplier in picks:
        stats = live.get(player_id) or {}
        total += (stats.get("total_points") or 0) * multiplier
    return total


def build_counterfactual_ledger(
    conn: sqlite3.Connection,
    season: str | None = None,
    live_stats_fn=None,
) -> list[LedgerRow]:
    """One row per finished gameweek that has both a real synced squad and a
    previous gameweek to have transferred from.

    `live_stats_fn` is injectable so tests never reach the network; it
    defaults to the same per-event endpoint `calibration.py` uses, which is
    the only source in this project with genuinely per-gameweek points for
    every player (not just the ones in your squad).
    """
    from fpl_agent.models.calibration import _event_live_stats

    live_stats_fn = live_stats_fn if live_stats_fn is not None else _event_live_stats
    season = season if season is not None else current_season(conn)

    events = [r["event"] for r in conn.execute(
        "SELECT DISTINCT event FROM my_team_picks ORDER BY event"
    )]
    if len(events) < 2:
        return []

    picks_by_event: dict[int, list[sqlite3.Row]] = {}
    for event in events:
        picks_by_event[event] = conn.execute(
            "SELECT player_id, multiplier, is_captain, active_chip FROM my_team_picks WHERE event=?",
            (event,),
        ).fetchall()

    summary_by_event = {
        r["event"]: r for r in conn.execute(
            "SELECT event, points, event_transfers, event_transfers_cost FROM my_team_gw_summary"
        )
    }

    recs = {
        r["event"]: r for r in conn.execute(
            "SELECT event, chosen_action, chosen_out_id, chosen_in_id FROM decision_outcomes "
            "WHERE season=? AND decision_kind='transfer'",
            (season,),
        )
    }

    live_cache: dict[int, dict] = {}

    def live_for(event: int) -> dict:
        if event not in live_cache:
            live_cache[event] = live_stats_fn(event)
        return live_cache[event]

    rows: list[LedgerRow] = []
    for event in events:
        prev_event = event - 1
        if prev_event not in picks_by_event:
            continue
        summary = summary_by_event.get(event)
        if summary is None:
            continue

        live = live_for(event)
        if not live:
            continue

        prev_picks = [(p["player_id"], p["multiplier"]) for p in picks_by_event[prev_event]]
        prev_ids = {p["player_id"] for p in picks_by_event[prev_event]}
        chip = next((p["active_chip"] for p in picks_by_event[event]), None)

        # ROLL: last week's squad, untouched, scored this week.
        roll_points = _squad_points(live, prev_picks)

        rec = recs.get(event)
        optimizer_points = None
        optimizer_action = None
        followed = None
        note = None

        if rec is None:
            note = "no recommendation was logged for this gameweek"
        elif rec["chosen_in_id"] is None or rec["chosen_action"] == "roll":
            optimizer_action = "ROLL"
            optimizer_points = roll_points
            followed = (summary["event_transfers"] or 0) == 0
        else:
            out_id, in_id = rec["chosen_out_id"], rec["chosen_in_id"]
            optimizer_action = f"{out_id} -> {in_id}"
            if out_id not in prev_ids:
                # It proposed selling someone who was not in the squad it was
                # supposedly advising on - a stale-squad recommendation. Not
                # scoreable, and worth surfacing rather than quietly skipping.
                note = "recommended selling a player who was not in the squad"
            else:
                swapped = [
                    (in_id if pid == out_id else pid, mult)
                    for pid, mult in prev_picks
                ]
                optimizer_points = _squad_points(live, swapped)
                current_ids = {p["player_id"] for p in picks_by_event[event]}
                followed = in_id in current_ids and out_id not in current_ids

        rows.append(LedgerRow(
            event=event,
            your_points=summary["points"],
            your_chip=chip,
            your_transfers=summary["event_transfers"] or 0,
            your_transfer_cost=summary["event_transfers_cost"] or 0,
            optimizer_points=optimizer_points,
            optimizer_action=optimizer_action,
            roll_points=roll_points,
            delta_vs_you=(optimizer_points - summary["points"]) if optimizer_points is not None else None,
            followed=followed,
            note=note,
        ))
    return rows


@dataclass(frozen=True)
class LedgerTotals:
    events: int
    # Your score across EVERY gameweek in the ledger - the real season
    # number, reported separately because it is the one you recognise.
    your_total_all_events: int
    # The three comparison totals all span exactly the same gameweeks: those
    # where the optimizer produced a scoreable recommendation. Summing your
    # score over four gameweeks against its score over three would flatter
    # you by a whole gameweek, which is the same apples-to-oranges error
    # this module was written to replace.
    your_total: int | None
    optimizer_total: int | None
    roll_total: int | None
    comparable_events: int
    delta: int | None
    followed_count: int
    recommendations_logged: int


def ledger_totals(rows: list[LedgerRow]) -> LedgerTotals:
    comparable = [r for r in rows if r.optimizer_points is not None]
    return LedgerTotals(
        events=len(rows),
        your_total_all_events=sum(r.your_points for r in rows),
        your_total=sum(r.your_points for r in comparable) if comparable else None,
        optimizer_total=sum(r.optimizer_points for r in comparable) if comparable else None,
        roll_total=sum(r.roll_points for r in comparable if r.roll_points is not None) if comparable else None,
        comparable_events=len(comparable),
        delta=sum(r.delta_vs_you for r in comparable) if comparable else None,
        followed_count=sum(1 for r in rows if r.followed),
        recommendations_logged=sum(1 for r in rows if r.optimizer_action is not None),
    )
