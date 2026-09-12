"""Real decision hysteresis (2026-08-29, "live architecture rebuild" pass,
milestone 4 - direct spec section 11: "do not alternate recommendations
every time the model moves by 0.05 xP... require a meaningful advantage
before replacing a current recommendation. Use: minimum EV advantage,
confidence threshold, persistence across multiple updates").

Real gap this closes: `strategic_planner.latest_strategic_plan_with_
recommendation` (the single real choke point every consumer already goes
through for "the authoritative current decision") returns the single
LATEST complete `strategic_plan` decision, unconditionally - every real
recompute (now materiality-gated and REACTIVE since milestone 3, so more
frequent than the old fixed `run_scheduled` cadence) immediately became
"the" displayed recommendation the instant it finished, with zero check
for whether the change was actually meaningful. A beam search re-run with
slightly different projection inputs (odds drift, a lineup-probability
wobble) can genuinely flip which starting action nominally scores highest
by a fraction of a point - real noise, not a real decision change.

Deliberately does NOT alter `synthesize_current_recommendation`'s own
math, nor the beam search, nor how a decision gets LOGGED - every real
`strategic_plan` decision is still computed and stored exactly as before
(full audit trail preserved, `fpl decision-changes`/`decision-audit`
still see every real transition, unfiltered - those tools exist
specifically to show raw reality, not a smoothed view). This module only
decides which of the recently-logged real decisions should be treated as
"the stable, currently-displayed recommendation" - wired into the ONE
real place spec section 11's concern actually lives (the dashboard's own
primary verdict, `monitoring/dashboard/legacy.py::_compute_primary_
verdict`), not into the audit/freshness tooling that deliberately wants
the raw, unfiltered latest decision."""
import sqlite3

_MIN_EV_ADVANTAGE = 5.0  # a real, disclosed, hand-picked threshold (full-horizon path_total points) - not derived from any statistical calibration; large enough to filter real beam-search noise (this project's own search-width experiment found <1.2pt tail variation between beam widths) without requiring an implausibly large swing
_MIN_PERSISTENCE_COUNT = 2  # the new candidate must be the top real recommendation in this many CONSECUTIVE complete decisions (including the latest) before it overrides an insufficient EV advantage
_MIN_CONFIDENCE_FOR_IMMEDIATE_FLIP = "MEDIUM"  # same real bar decision_analysis.py already uses for "well-evidenced enough to act on" - reused, not redefined

_HISTORY_SCAN = 10  # generous - real production strategic_plan cadence rarely logs more than a handful of decisions between two genuinely different stable recommendations


def _anchor_event(decision) -> int | None:
    """The real gameweek this decision's own leading path treats as the
    first still-open decision point - `paths[0].steps[0].event`. `None`
    (never guessed) when a decision genuinely has no paths/steps yet."""
    try:
        return decision.detail["paths"][0]["steps"][0]["event"]
    except (KeyError, IndexError, TypeError):
        return None


def stable_current_recommendation(conn: sqlite3.Connection, scan_limit: int = 30):
    """Returns the real, already-logged `Decision` row that should be
    treated as the CURRENT stable recommendation - either the latest real
    decision (if it clears the hysteresis bar) or an earlier one that's
    still the real stable answer. Never fabricates a decision, never
    averages two decisions together - always one real, already-computed,
    already-logged row, same contract `latest_strategic_plan_with_
    recommendation` already has (this function's own direct replacement
    at its one real display call site).

    `None` when no real complete decision exists yet - same honest
    empty case as the function it wraps."""
    from fpl_agent.models.projection_confidence import _LEVEL_RANK
    from fpl_agent.optimization.strategic_planner import strategic_plan_decisions_with_recommendation

    recent = strategic_plan_decisions_with_recommendation(conn, limit=_HISTORY_SCAN, scan_limit=scan_limit)
    if not recent:
        return None
    latest = recent[0]
    if len(recent) == 1:
        return latest  # the first real decision ever logged - trivially stable, nothing to compare against

    latest_rec = latest.detail["current_recommendation"]

    # Real gap found 2026-09-12 (direct user report: the Plan screen kept
    # showing "PLAY FREE HIT" as the stable recommendation for GW4 even
    # after the GW4 deadline passed and Free Hit had genuinely been played
    # for real - the newer decision correctly starting fresh at GW5 never
    # cleared the EV-advantage/persistence bar below, because that bar
    # compares two decisions' LABELS as if they were competing answers to
    # the SAME question. "PLAY FREEHIT" (GW4) vs "PLAY WILDCARD" (GW5)
    # aren't competing at all - GW4's decision point is simply closed. This
    # module's own docstring is explicit that its scope is model NOISE for
    # a still-open decision (a beam search re-run flipping ROLL vs TRANSFER
    # for the SAME upcoming gameweek by a fraction of a point) - it was
    # never meant to gate a real, discrete, irreversible advance to a new
    # gameweek, and comparing across that boundary produced exactly the
    # wrong answer. Skip the whole hysteresis bar (immediately trust
    # `latest`) whenever its own anchor event has genuinely moved past the
    # second-most-recent decision's - within the SAME anchor gameweek, the
    # bar below still applies unchanged.
    if len(recent) > 1:
        latest_anchor = _anchor_event(latest)
        previous_anchor = _anchor_event(recent[1])
        if latest_anchor is not None and previous_anchor is not None and latest_anchor > previous_anchor:
            return latest

    # Real persistence count - how many of the most-recent real decisions
    # (starting from latest, walking backward) already agree with it.
    consecutive = 0
    for d in recent:
        rec = d.detail.get("current_recommendation")
        if rec is not None and rec["label"] == latest_rec["label"]:
            consecutive += 1
        else:
            break
    if consecutive >= _MIN_PERSISTENCE_COUNT:
        # Already the real, repeated answer across enough consecutive
        # updates - genuinely stable, not a single noisy blip either way.
        return latest

    # Find the most recent decision whose label genuinely DIFFERS from
    # latest's - that's the real "previously stable" baseline being
    # considered for replacement.
    previous_stable = next(
        (d for d in recent[1:] if (d.detail.get("current_recommendation") or {}).get("label") != latest_rec["label"]),
        None,
    )
    if previous_stable is None:
        # Every real decision on record agrees with latest (just hasn't
        # hit the persistence count above yet, e.g. only 1 prior decision
        # exists and it already matches) - nothing to hold back.
        return latest

    prev_rec = previous_stable.detail["current_recommendation"]
    prev_total, new_total = prev_rec.get("path_total"), latest_rec.get("path_total")
    ev_advantage = (new_total - prev_total) if (prev_total is not None and new_total is not None) else None

    confidence = latest_rec.get("evidence_confidence")
    confidence_ok = confidence is None or _LEVEL_RANK.get(confidence, 0) >= _LEVEL_RANK[_MIN_CONFIDENCE_FOR_IMMEDIATE_FLIP]

    if ev_advantage is not None and ev_advantage >= _MIN_EV_ADVANTAGE and confidence_ok:
        return latest  # a real, meaningful, well-evidenced improvement - flip now, don't wait for persistence

    # Neither a big-enough real EV jump nor enough real persistence yet -
    # keep showing the previously stable recommendation. The new decision
    # stays fully logged (nothing here deletes or hides it - `fpl
    # decision-changes`/the audit tools still see it), it's just not yet
    # promoted to "the" displayed answer.
    return previous_stable
