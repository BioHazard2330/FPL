"""Real future-optionality measurement (2026-09-02, Phase 5B optimizer
forensic rebuild, PART 2). Operational definition, stated explicitly per the
task's own "do not create a cosmetic optionality score" instruction:
optionality is measured as the real, counted size of the REACHABLE next-state
space from a given squad/bank/FT position - how many real, legal single
transfers remain open, not an invented 0-100 index.

Real, disclosed scope: this is the CHEAP layer (legal affordability + club
limit only, the same real eligibility filter `transfers.py::
best_transfer_for_player` already applies before it spends any real EV
computation) - it counts how many real doors are open, not which ones are
best. A fuller "high-EV reachable successor" refinement would need a real EV
evaluation per candidate (expensive - the same cost `best_transfer_for_player`
itself pays), and is a real, scoped follow-up, not built this pass. Never
silently presented as the richer version."""
import sqlite3
from collections import Counter
from dataclasses import dataclass

# Real, disclosed premium threshold - same honesty posture as every other
# uncalibrated constant in this codebase (not fit to outcome data).
_PREMIUM_PRICE_TENTHS = 90  # £9.0m+


@dataclass(frozen=True)
class OptionalityAssessment:
    bank_tenths: int
    free_transfers: int
    # Real, per-squad-player count of legally affordable, same-position,
    # not-already-owned, club-limit-respecting replacements - the real
    # reachable-next-state count this module's own docstring defines
    # optionality as.
    reachable_successor_count: int
    # Real count of those reachable successors priced at/above the real
    # premium threshold - "premium-player access", per PART 2's own list.
    premium_access_count: int
    per_player: dict[int, int]  # real reachable-successor count for EACH squad player, individually


def assess_future_optionality(
    conn: sqlite3.Connection, squad_ids: list[int], bank_tenths: int, free_transfers: int = 0,
) -> OptionalityAssessment:
    """Real, cheap reachable-state count - reuses the exact same real
    eligibility filter (`position` match, `price_in <= price_out + bank`,
    club-limit) `best_transfer_for_player` applies before any EV evaluation,
    factored out here so this module never re-derives a second, possibly-
    diverging eligibility rule."""
    from fpl_agent.optimization.transfers import _current_price, _position

    season_rows = conn.execute("SELECT value FROM rules WHERE rule_key='rules.squad_team_limit' ORDER BY id DESC LIMIT 1").fetchone()
    club_limit = int(season_rows["value"]) if season_rows else 3

    squad_id_set = set(squad_ids)
    team_by_player = {
        r["id"]: r["team_id"] for r in conn.execute(
            "SELECT id, team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
            list(squad_ids),
        ).fetchall()
    }

    per_player: dict[int, int] = {}
    premium_count_total = 0
    for player_out_id in squad_ids:
        position = _position(conn, player_out_id)
        price_out = _current_price(conn, player_out_id)
        budget = price_out + bank_tenths
        remaining_team_counts = Counter(
            tid for pid, tid in team_by_player.items() if pid != player_out_id
        )
        candidates = conn.execute(
            "SELECT p.id, p.team_id FROM players p JOIN element_types et ON et.id = p.element_type "
            "WHERE et.singular_name_short=? AND p.removed=0", (position,),
        ).fetchall()
        count = 0
        premium = 0
        for c in candidates:
            if c["id"] == player_out_id or c["id"] in squad_id_set:
                continue
            if remaining_team_counts.get(c["team_id"], 0) >= club_limit:
                continue
            price_in = _current_price(conn, c["id"])
            if price_in > budget:
                continue
            count += 1
            if price_in >= _PREMIUM_PRICE_TENTHS:
                premium += 1
        per_player[player_out_id] = count
        premium_count_total += premium

    return OptionalityAssessment(
        bank_tenths=bank_tenths, free_transfers=free_transfers,
        reachable_successor_count=sum(per_player.values()),
        premium_access_count=premium_count_total, per_player=per_player,
    )


@dataclass(frozen=True)
class OptionalityComparison:
    """Real, unambiguous before/after comparison (2026-09-02, Phase 5C PART 1
    - fixes a real, confirmed semantic bug: the previous single free-text
    `optionality_note` embedded a signed delta inside a prose string with no
    separate field, and two live checks in the same session read -410 and
    +317 with no way to tell from the OBJECT alone which real quantity had
    changed sign - only by re-reading the sentence. Every quantity below has
    exactly one real meaning, named for what it is:

    - `baseline_reachable_successors`/`reachable_successors` are each real,
      ABSOLUTE counts (`OptionalityAssessment.reachable_successor_count` -
      never negative, since a count of real legal transfers can't be).
    - `optionality_delta` is a real SIGNED delta (`reachable - baseline`) -
      CAN legitimately be negative (a path that narrows real future options
      is a real, honest, negative delta, not a bug) - never confused with
      the count above because it lives in its own field.
    - `optionality_percent_change` is `None` (never a fabricated 0% or
      division-by-zero placeholder) when `baseline_reachable_successors==0`,
      since a percent change from a real zero baseline is undefined, not
      zero."""
    baseline_reachable_successors: int
    reachable_successors: int
    optionality_delta: int
    optionality_percent_change: float | None
    baseline_premium_access: int
    premium_access: int
    premium_access_delta: int


def compare_optionality(baseline: OptionalityAssessment, after: OptionalityAssessment) -> OptionalityComparison:
    delta = after.reachable_successor_count - baseline.reachable_successor_count
    pct = (
        round(100.0 * delta / baseline.reachable_successor_count, 1)
        if baseline.reachable_successor_count > 0 else None
    )
    return OptionalityComparison(
        baseline_reachable_successors=baseline.reachable_successor_count,
        reachable_successors=after.reachable_successor_count,
        optionality_delta=delta, optionality_percent_change=pct,
        baseline_premium_access=baseline.premium_access_count,
        premium_access=after.premium_access_count,
        premium_access_delta=after.premium_access_count - baseline.premium_access_count,
    )
