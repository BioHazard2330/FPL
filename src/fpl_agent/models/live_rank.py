"""Live overall-rank estimation (2026-08-21, live-gameweek layer item 3) -
real research done first, per the standing instruction ("research how
LiveFPL/other real tools solve it before assuming an approach, don't
guess"), not assumed.

Real research finding, honestly reported: FPL's official API never
publishes a live overall rank during a gameweek - confirmed via multiple
web searches (LiveFPL's/FPLForm's own marketing/blog pages, an academic
paper on FPL skill identification, several GitHub topic searches). The
exact proprietary algorithms LiveFPL/FPLForm actually run were NOT found
publicly documented anywhere in this research - a real, disclosed gap in
what's knowable from outside those services, not something skipped or
glossed over. What WAS found and IS real, load-bearing evidence: fplform.com's
own "FPL Live Rank" feature page states it "compares your score vs the top
10k managers" - confirming that at least one established real tool anchors
its live estimate on a sampled/known reference set of managers, not a
closed-form formula with no real data behind it.

This project already has exactly that building block, shipped and tested
for a different purpose (Pillar 1 Plan 1c, `ingestion/eo_sample.py`):
`select_stratified_pages` samples the public Overall league (id 314)
standings, stratified across an arbitrary rank range, and
`FPLApiAdapter.fetch_entry_picks` fetches a real manager's picks for a
locked event - the exact same public, no-login endpoints
`ingestion/my_team.py` already uses for the user's own real team.
`ingestion/live_rank_sample.py` reuses both, extended to sample the FULL
rank range (1..total_players) rather than EO sampling's top-10k cap - a
real, deliberate difference: the user's own real 2025/26 season rank was
~1,000,697 (see CLAUDE.md's my-team section), so a top-10k-only sample
would never bracket where a typical manager - this project's own user
included - actually sits.

**The general method used here** (a legitimate, standard statistical
technique - build an empirical inverse CDF from a stratified sample and
interpolate it - not FPL insider knowledge): each sampled manager's real
PRE-GW rank (their position on the standings page, exact and already
known, no estimation needed) anchors one point on the true population
curve. Compute each sampled manager's real CURRENT total (pre-GW
cumulative total + this project's own live-points estimate for the
in-progress event, `estimate_squad_live_points`), sort the sample by
current total, and linearly interpolate between the two sampled managers
that bracket the TARGET's own current total to estimate the target's live
rank.

**Real, disclosed limitations - not glossed over:**
- Uses each sampled manager's PRE-GW rank as the interpolation anchor, not
  their true CURRENT rank (the exact unknown quantity this module exists
  to estimate) - an approximation that assumes the sample is large/spread
  enough that sorting by CURRENT total approximates the true population
  order well. Uncalibrated - same honesty posture as every other
  uncalibrated heuristic this project ships (`price_forecast.py`,
  `squad_churn.py`), not yet fit against real live-gameweek results
  because none exist yet this season.
- `estimate_squad_live_points` does NOT model autosubs (a non-appearing
  starter being replaced by a bench player) - real research surfaced this
  as something LiveFPL itself specifically calls out as a genuinely hard
  part of live scoring. A non-appearing starter contributes 0 here, not a
  fabricated substitution - a real, disclosed undercount versus the true
  live score for any squad (sampled or the user's own) with a non-playing
  starter, until a future pass adds real autosub logic.
- The heaviest network pattern in this project, heavier than `fpl sync-eo`
  (whose sampling primitive this reuses) since it samples a wider rank
  range for the same reason described above - opt-in only, never part of
  the regular scheduled cycle, same posture `eo_sample.py` already
  established.
- Cannot be live-verified against a real in-progress gameweek yet (GW1
  hasn't kicked off as this was built) - built and tested against the
  real, well-documented endpoint schema instead, same honest, disclosed
  posture `models/live_bonus.py` already used for bonus/DEFCON.

Interpolation upgraded 2026-08-21 from plain linear bracket-interpolation
to a monotonic cubic Hermite spline (`scipy.interpolate.PchipInterpolator`,
already a project dependency via scipy - no new one added), per direct
user request after independently verifying the "wobble" problem a naive
cubic/linear fit has: a plain cubic spline can overshoot BETWEEN two real
anchor points and produce a locally non-monotonic curve (a higher score
mapping to a numerically WORSE rank than a slightly lower score nearby) -
nonsensical for a rank curve, where "more points = same-or-better rank" is
a hard real constraint, not just a preference. PCHIP is shape-preserving:
it never overshoots past the data's own local monotonic trend. That
guarantee is conditional on the INPUT itself being monotonic, though - real
sampled data isn't, because each anchor's `pre_gw_rank` is a PRE-gameweek
proxy (see limitation above), so two anchors can legitimately swap relative
order once live points are added (a manager who started at a worse pre-GW
rank can out-score one who started better). `_enforce_monotonic_ranks`
corrects this with a real, standard, simple technique (a running-max pass
from the best-score end down - equivalent to a one-sided pool-adjacent-
violators correction) BEFORE the data ever reaches PCHIP, documented
plainly as smoothing over real sample noise, not silently hidden."""
from dataclasses import dataclass

from scipy.interpolate import PchipInterpolator


def estimate_squad_live_points(picks: list[tuple[int, int]], live_payload: dict) -> float:
    """`picks`: real [(element_id, multiplier)] pairs, straight off the FPL
    API's own picks schema - multiplier is 0 for an unused bench player (a
    real value FPL's own API returns, not inferred), so a bench player
    correctly contributes nothing, matching the real rule that only the
    starting 11 (plus any real autosub - NOT modeled here, see this
    module's own docstring) score. Reads each element's own live
    `total_points` stat - FPL's own already-computed live per-player score
    (includes provisional bonus) - not reimplemented scoring rules, the
    same trust-FPL's-own-live-computation posture this project's
    `defensive_contribution`/`bps` live reads already use."""
    stats_by_id = {e["id"]: e.get("stats", {}) for e in live_payload.get("elements", []) if "id" in e}
    total = 0.0
    for element_id, multiplier in picks:
        if multiplier <= 0:
            continue
        stats = stats_by_id.get(element_id, {})
        total += stats.get("total_points", 0) * multiplier
    return total


@dataclass(frozen=True)
class LiveRankEstimate:
    estimated_rank: int
    rank_lower_bound: int
    rank_upper_bound: int
    my_current_total: float
    sample_size: int
    bracketed: bool  # False when my_current_total fell outside the sampled range entirely


def _enforce_monotonic_ranks(scores_desc: list[float], ranks_desc: list[float]) -> list[float]:
    """`scores_desc`/`ranks_desc` are already sorted by score DESCENDING
    (best score first). Real sampled `pre_gw_rank` values aren't guaranteed
    monotonic against the NEW live-total ordering (see module docstring) -
    this is a one-sided running-max correction (a simplified pool-adjacent-
    violators pass): walking from the best score downward, a rank is never
    allowed to be BETTER (numerically lower) than every rank already seen
    at a higher score, since that would claim a worse-scoring manager
    somehow ranks better - clipped up to the running maximum instead.
    Ties in score keep their own individual (now-corrected) ranks, not
    collapsed - deduplication happens separately in estimate_live_rank
    before this is called."""
    corrected = []
    running_max = float("-inf")
    for rank in ranks_desc:
        running_max = max(running_max, rank)
        corrected.append(running_max)
    return corrected


def estimate_live_rank(
    reference: list[tuple[int, float]], my_current_total: float, total_players: int,
) -> LiveRankEstimate:
    """`reference`: real [(pre_gw_rank, current_total)] pairs from a
    stratified sample (`ingestion/live_rank_sample.py::get_live_rank_reference`).

    Pipeline: sort by current_total descending -> collapse any exact-tied
    scores to their mean rank (PchipInterpolator requires a strictly
    increasing x-axis, and real integer live-points totals can genuinely
    tie across different sampled managers) -> enforce rank monotonicity
    against the new live ordering (`_enforce_monotonic_ranks`, see its own
    docstring for why real sample noise needs this) -> fit a monotonic
    cubic Hermite spline (PCHIP) over the corrected (score, rank) anchor
    points and evaluate it at the target's own current_total.

    Falling outside the whole sampled range (better than the best sample,
    or worse than the worst) reports an honest wide bound instead of
    trusting spline extrapolation past real data - PCHIP's shape-
    preservation guarantee only holds BETWEEN real anchor points, not
    beyond them. `bracketed=False` tells the caller this is a much cruder
    estimate. See this module's own docstring for the real limitations of
    any estimate this returns."""
    if not reference:
        raise ValueError("reference sample is empty - run live-rank-sample first")

    ordered = sorted(reference, key=lambda pair: pair[1], reverse=True)

    # Collapse exact score ties to their mean rank - a strictly increasing
    # x-axis is a hard PchipInterpolator requirement, and this is the
    # honest way to represent "several real managers landed on the exact
    # same live total" rather than arbitrarily picking one of them.
    totals_desc: list[float] = []
    ranks_desc: list[float] = []
    for total, group in _group_by_score(ordered):
        totals_desc.append(total)
        ranks_desc.append(sum(group) / len(group))

    n = len(reference)  # real sample size, before tie-collapsing, for honest reporting
    best_total, worst_total = totals_desc[0], totals_desc[-1]
    best_rank, worst_rank = ranks_desc[0], ranks_desc[-1]

    if my_current_total >= best_total:
        return LiveRankEstimate(
            estimated_rank=max(1, round(best_rank) // 2), rank_lower_bound=1,
            rank_upper_bound=round(best_rank), my_current_total=my_current_total,
            sample_size=n, bracketed=False,
        )
    if my_current_total <= worst_total:
        return LiveRankEstimate(
            estimated_rank=(round(worst_rank) + total_players) // 2, rank_lower_bound=round(worst_rank),
            rank_upper_bound=total_players, my_current_total=my_current_total,
            sample_size=n, bracketed=False,
        )

    corrected_ranks_desc = _enforce_monotonic_ranks(totals_desc, ranks_desc)

    # PCHIP needs x strictly ascending - flip both lists (they were built
    # descending-by-score above) before fitting.
    scores_asc = list(reversed(totals_desc))
    ranks_asc = list(reversed(corrected_ranks_desc))
    spline = PchipInterpolator(scores_asc, ranks_asc, extrapolate=False)
    interpolated = float(spline(my_current_total))

    # Real, disclosed edge case: extrapolate=False means a value exactly at
    # a boundary can legitimately return nan from floating-point edge
    # effects - fall back to the nearest real anchor's own rank rather than
    # ever surfacing a NaN rank to a caller.
    if interpolated != interpolated:  # NaN check, no extra import needed
        interpolated = ranks_asc[0] if my_current_total <= scores_asc[0] else ranks_asc[-1]

    lower, upper = min(best_rank, worst_rank), max(best_rank, worst_rank)
    return LiveRankEstimate(
        estimated_rank=max(1, round(interpolated)), rank_lower_bound=round(lower),
        rank_upper_bound=round(upper), my_current_total=my_current_total,
        sample_size=n, bracketed=True,
    )


def _group_by_score(ordered_desc: list[tuple[int, float]]):
    """`ordered_desc`: [(rank, score)] sorted score-descending. Yields
    (score, [ranks]) per distinct score, preserving descending order -
    a plain groupby needs pre-sorted input by the grouping key, which the
    caller already guarantees."""
    groups: list[tuple[float, list[float]]] = []
    for rank, score in ordered_desc:
        if groups and groups[-1][0] == score:
            groups[-1][1].append(rank)
        else:
            groups.append((score, [rank]))
    return groups
