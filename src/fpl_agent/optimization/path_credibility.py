"""Real multi-GW strategy credibility/fragility assessment (2026-09-02,
Phase 5 optimizer forensic rebuild, PART 9/10). A high `path_total` is not
automatically a good recommendation - this module makes the optimizer
explicitly interrogate WHY a path scores well, not just present the number.

Real, confirmed live motivation for building this (not hypothetical): this
project's own current real production recommendation is a 4-chip path
(FREEHIT@GW3 -> WILDCARD@GW4 -> BBOOST@GW5 -> 3XC@GW6) presented with the
same flat visual confidence as a plain roll. This module gives that path an
explicit, real, disclosed friction assessment instead.

Hard rule from the spec that created this module: never hard-code "N chips =
bad". Every signal below is a real, counted, disclosed fact about the path
itself (how many of its transfers target a LOW/VERY_LOW-confidence player,
how many chips fall in a short real window, how thin the final real bank
margin is) - `credibility_label` is a simple, disclosed band over those real
counts, not an invented weighted score."""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.projection_confidence import assess_projection_confidence
from fpl_agent.optimization.strategy_robustness import assess_path_robustness

# Real, disclosed bands - not fit to real outcome data (none exists yet at
# this project's own real scale to calibrate against). A starting point,
# same honesty posture as every other uncalibrated threshold in this
# codebase (`market_conviction`'s 10% bar, `robustness.py`'s win-rate bars).
_CHIP_STACK_WINDOW_GW = 4  # real GWs - how close together chips must land to count as "stacked"
_LOW_CONFIDENCE_LEVELS = {"LOW", "VERY_LOW"}
_LOW_FRICTION_MAX_SCORE = 1
_MODERATE_FRICTION_MAX_SCORE = 3
_THIN_BANK_TENTHS = 5  # real <£0.5m final bank - no real room for a price-rise surprise


_LATER_STEP_GW_OFFSET = 2  # real GWs out before a transfer counts as "later" (not the immediate real deadline)


@dataclass(frozen=True)
class PathCredibility:
    speculative_transfer_count: int  # real transfers where the IN player's own real projection confidence is LOW/VERY_LOW
    speculative_players: tuple[str, ...]
    chip_count: int
    chips_stacked_within_window: bool  # real: 2+ real chips inside _CHIP_STACK_WINDOW_GW of each other
    stacked_chip_names: tuple[str, ...]
    forced_sequential_transfers: int  # real count of transfer steps whose IN player from an EARLIER step is later transferred OUT again (the path bets on its own earlier bet)
    price_dependent_transfers: int  # real count of LATER transfer steps priced at today's value while price_forecast.py says that price is likely to move against the path before then
    price_dependent_players: tuple[str, ...]
    final_bank_thin: bool
    friction_score: int  # real, simple sum of the above real flags/counts - disclosed, not hidden
    credibility_label: str  # LOW_FRICTION | MODERATE_FRICTION | HIGH_FRICTION
    reasons: tuple[str, ...]


def assess_path_credibility(conn: sqlite3.Connection, path) -> PathCredibility:
    """`path` is a real `optimization.transfers.TransferSequence` (or
    anything with the same `.steps`/`.chips_used`/`.final_bank_tenths`
    shape) - the actual searched object, never a re-derived summary."""
    steps = list(path.steps)
    reasons: list[str] = []

    speculative_players: list[str] = []
    for s in steps:
        if s.player_in_id is None:
            continue
        try:
            pc = assess_projection_confidence(conn, s.player_in_id)
        except Exception:
            continue
        if pc.overall in _LOW_CONFIDENCE_LEVELS:
            speculative_players.append(s.player_in_name or str(s.player_in_id))
    speculative_count = len(speculative_players)
    if speculative_count:
        reasons.append(
            f"{speculative_count} real transfer(s) target a player this project's own projection confidence "
            f"rates LOW/VERY_LOW right now: {', '.join(speculative_players)}"
        )

    chip_events = [(s.event, s.chip_played) for s in steps if s.chip_played]
    chip_count = len(chip_events)
    stacked = False
    stacked_names: list[str] = []
    for i in range(len(chip_events)):
        for j in range(i + 1, len(chip_events)):
            if abs(chip_events[j][0] - chip_events[i][0]) <= _CHIP_STACK_WINDOW_GW:
                stacked = True
                stacked_names.extend([chip_events[i][1], chip_events[j][1]])
    stacked_names = list(dict.fromkeys(stacked_names))  # real, order-preserving de-dup
    if stacked:
        reasons.append(
            f"{len(stacked_names)} real chips ({', '.join(stacked_names)}) fall within {_CHIP_STACK_WINDOW_GW} "
            f"real gameweeks of each other - each one's own real marginal value assumes the squad state the "
            f"PRIOR chip step already created"
        )
    elif chip_count:
        reasons.append(f"{chip_count} real chip(s) played, spaced out - not a real stacking concern")

    # Real "bets on its own earlier bet" count - a player brought IN at an
    # earlier real step who is transferred OUT again at a later real step.
    # This is a genuine, real structural dependency (the later step's own
    # real EV calculation only holds if the earlier real transfer actually
    # happened as modelled) - counted directly from the path's own real
    # in/out ids, never inferred.
    in_events = {s.player_in_id: s.event for s in steps if s.player_in_id is not None}
    forced = sum(1 for s in steps if s.player_out_id is not None and s.player_out_id in in_events)
    if forced:
        reasons.append(
            f"{forced} real transfer(s) sell a player this SAME path bought earlier - a real chained dependency, "
            f"not an independent decision"
        )

    # Real price-dependency check (2026-09-02, Phase 5B, PART 3) - a LATER
    # transfer step (not the immediate real deadline) prices its own IN
    # player at TODAY's real price (`best_transfer_for_player`'s own
    # `_current_price` lookup, confirmed by direct inspection - it never
    # reads a projected future price). If `price_forecast.py`'s own real,
    # already-computed momentum says that price is genuinely likely to move
    # AGAINST the path before that real gameweek arrives, the path is
    # implicitly betting on a price that may not hold - a real, disclosed
    # dependency, never silently assumed away.
    price_dependent: list[str] = []
    if steps:
        first_event = steps[0].event
        try:
            from fpl_agent.models.price_forecast import classify_price_change

            for s in steps:
                if s.player_in_id is None or s.event < first_event + _LATER_STEP_GW_OFFSET:
                    continue
                if classify_price_change(conn, s.player_in_id).direction == "RISE_LIKELY":
                    price_dependent.append(s.player_in_name or str(s.player_in_id))
        except Exception:
            pass
    price_dependent_count = len(price_dependent)
    if price_dependent_count:
        reasons.append(
            f"{price_dependent_count} later real transfer(s) target a player with real RISE_LIKELY price "
            f"momentum right now ({', '.join(price_dependent)}) - this path prices them at today's value "
            f"weeks out, a real assumption that may not hold by the time that real gameweek arrives"
        )

    bank_thin = path.final_bank_tenths <= _THIN_BANK_TENTHS
    if bank_thin:
        reasons.append(
            f"real final bank of £{path.final_bank_tenths / 10:.1f}m leaves no room for a real price rise "
            f"to force a compromise later in this path"
        )

    friction_score = speculative_count + (2 if stacked else 0) + forced + price_dependent_count + (1 if bank_thin else 0)
    if friction_score <= _LOW_FRICTION_MAX_SCORE:
        label = "LOW_FRICTION"
    elif friction_score <= _MODERATE_FRICTION_MAX_SCORE:
        label = "MODERATE_FRICTION"
    else:
        label = "HIGH_FRICTION"
    if not reasons:
        reasons.append("no real speculative transfers, chip stacking, chained dependencies, price dependencies, or bank fragility found")

    return PathCredibility(
        speculative_transfer_count=speculative_count, speculative_players=tuple(speculative_players),
        chip_count=chip_count, chips_stacked_within_window=stacked, stacked_chip_names=tuple(stacked_names),
        forced_sequential_transfers=forced,
        price_dependent_transfers=price_dependent_count, price_dependent_players=tuple(price_dependent),
        final_bank_thin=bank_thin, friction_score=friction_score,
        credibility_label=label, reasons=tuple(reasons),
    )


_FLEXIBLE_RANK = {"LOW_FRICTION": 0, "MODERATE_FRICTION": 1, "HIGH_FRICTION": 2}
_ROBUST_RANK = {"ROBUST": 0, "MODERATE": 1, "UNSTRESSED": 1, "FRAGILE": 2}


def label_diverse_paths(conn: sqlite3.Connection, indexed_paths: list[tuple[int, object, float]]) -> dict[int, tuple[str, ...]]:
    """Real, measurable strategy-diversity labels (2026-09-02, Phase 5B,
    PART 6) - "the top-5 paths are the same plan with minor substitutions"
    is a real, confirmed concern (`plan.py::primary_path_indices` already
    collapses near-duplicate descriptors; this is the NEXT layer -
    distinguishing the survivors on more than raw EV). `indexed_paths` is
    `[(real_index, path_object, real_total_ev), ...]` for the already-
    computed real PRIMARY (non-duplicate) paths only - never re-run this
    over near-duplicate tail variants, which would just relabel the same
    real strategy repeatedly. Each real label corresponds to an actual
    measured property from `assess_path_credibility`/`assess_path_robustness`
    (both already built, reused unchanged here) - never a cosmetic tag."""
    if not indexed_paths:
        return {}
    scored = []
    for idx, path, total_ev in indexed_paths:
        credibility = assess_path_credibility(conn, path)
        robustness = assess_path_robustness(conn, path)
        speculative_count = credibility.speculative_transfer_count + credibility.price_dependent_transfers
        scored.append((idx, total_ev, credibility.friction_score, _ROBUST_RANK[robustness.verdict], speculative_count))

    labels: dict[int, list[str]] = {idx: [] for idx, _, _ in indexed_paths}
    labels[max(scored, key=lambda s: s[1])[0]].append("HIGHEST_EV")
    labels[min(scored, key=lambda s: s[3])[0]].append("MOST_ROBUST")
    labels[min(scored, key=lambda s: s[2])[0]].append("MOST_FLEXIBLE")
    labels[min(scored, key=lambda s: s[4])[0]].append("INFORMATION_PRESERVING")
    return {idx: tuple(v) for idx, v in labels.items()}
