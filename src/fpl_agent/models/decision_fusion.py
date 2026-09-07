"""Decision Fusion - Model vs Football Intelligence vs My View (Pillar 4,
2026-08-22, continuing straight down the user's own spec section 26/27).
Real, explicit constraint taken from the spec itself: "Do not implement
arbitrary scoring" / "Do NOT simply average scores." This is a rule-based
comparison, not a weighted-sum fusion score - three real, independently-
sourced views are surfaced side by side, and a verdict label is only ever
picked by an explicit, documented rule, never a fabricated number.

Scoped tightly to the one concrete example the spec itself gives (section
26's captain comparison: "Model: Haaland / Football: Haaland / My view:
Isak / Final: undecided") rather than a generic multi-subject framework -
a real, disclosed scope decision, not an oversight. Extending to other
decision types (transfers, chips) is real future work once this pattern is
proven against at least one real disagreement.

Honesty note carried from every other "not yet outcome-verified" feature in
this project: as of this session, zero real matches have been through a
genuine `fpl match-analyze` run (GW1 is still the open first real test
case) - this module is schema/logic-verified against synthetic data, same
posture `fpl live-bonus`/`fpl live-rank` had before their first live match.
"""
from dataclasses import dataclass

from fpl_agent.models.player_intelligence import player_intelligence
from fpl_agent.optimization.captaincy import CaptainOption, evaluate_captaincy
from fpl_agent.optimization.transfers import TransferCandidate, best_transfer_for_player

# A qualitative "vote" for captain only counts from these real fpl_signal
# categories - the ones actually about goal threat/creative involvement,
# not e.g. a defensive-role observation that says nothing about captaincy.
_CAPTAINCY_RELEVANT_SIGNALS = {"GOAL_THREAT", "CREATION", "ROLE"}

VERDICTS = {"MODEL_WINS", "QUALITATIVE_WINS", "UNDECIDED", "INSUFFICIENT_EVIDENCE"}


@dataclass(frozen=True)
class CaptainViewComparison:
    model_pick: CaptainOption | None
    model_reason: str
    qualitative_pick_id: int | None
    qualitative_pick_name: str | None
    qualitative_reason: str | None
    user_pick_id: int | None
    user_pick_name: str | None
    user_reason: str | None
    verdict: str
    explanation: str


def _qualitative_captain_signal(conn, squad_ids: list[int]) -> tuple[int | None, str | None, bool, str | None]:
    """Returns (player_id, reason, is_persistent, signal) for the squad
    member with the most recent POSITIVE captaincy-relevant qualitative
    implication. `is_persistent` is True only when that player's own trend
    for the same signal is PERSISTENT_TREND (qualitative_trends.py) - a
    single good match is real evidence but not yet grounds to override a
    calibrated quant model on its own (spec section 16's own "not from tiny
    samples" rule, applied here to the fusion decision itself). `signal` is
    returned (2026-09-02, Phase 3 forensic audit) so the caller can look up
    whether - and by how much - `qualitative_feed.py` has ALREADY applied a
    real bounded adjustment for it, rather than the caller's own
    explanation text guessing at "the model doesn't yet capture this"."""
    if not squad_ids:
        return None, None, False, None
    placeholders = ",".join("?" * len(squad_ids))
    row = conn.execute(
        f"SELECT player_id, signal, reason, created_at FROM player_fpl_implications "
        f"WHERE player_id IN ({placeholders}) AND direction='POSITIVE' AND signal IN "
        f"({','.join('?' * len(_CAPTAINCY_RELEVANT_SIGNALS))}) AND phase='FULL_TIME' "
        f"ORDER BY created_at DESC LIMIT 1",
        [*squad_ids, *_CAPTAINCY_RELEVANT_SIGNALS],
    ).fetchone()
    if row is None:
        return None, None, False, None

    is_persistent = False
    pi = player_intelligence(conn, row["player_id"])
    for t in pi.trends:
        if t.signal == row["signal"] and t.label == "PERSISTENT_TREND" and t.current_direction == "POSITIVE":
            is_persistent = True
            break
    from fpl_agent.models.text_cleanup import clean_display_text

    return row["player_id"], clean_display_text(row["reason"]), is_persistent, row["signal"]


def _quantify_qualitative_gap(conn, qual_id: int, qual_signal: str | None, qual_reason: str | None) -> str:
    """Real fix (2026-09-02, Phase 3 forensic audit, direct user report:
    the FOOTBALL_CONFLICT text "the quant model's projection doesn't yet
    fully capture" is a generic phrase that never says whether -or by how
    much- `qualitative_feed.py` has ALREADY applied a real bounded
    adjustment). Reads the SAME `compute_qualitative_adjustment` the live
    projection path already calls for this player, so the conflict
    explanation reports a real, already-computed number instead of
    implying total blindness. `qual_signal` with no component mapping
    (ROLE/MINUTES - handled inside `expected_minutes()` itself, not this
    interface) is reported honestly as such, never guessed at."""
    from fpl_agent.models.expected_points import expected_points
    from fpl_agent.models.qualitative_feed import (
        _COMPONENT_SIGNAL_MAP,
        MAX_ADJUSTMENT_FRACTION,
        compute_qualitative_adjustment,
    )

    if qual_signal not in _COMPONENT_SIGNAL_MAP:
        return (
            f"real qualitative signal for this player ({qual_reason}) - '{qual_signal}' has no direct "
            "xP component mapping in this project's qualitative->quantitative interface, so it cannot "
            "move the quant model's own number at all yet"
        )
    ep = expected_points(conn, qual_id, n_gw=1)
    if ep.components is None:
        return f"real qualitative signal for this player ({qual_reason}) - no component breakdown available to quantify against"
    adjustment = compute_qualitative_adjustment(conn, qual_id, ep.components)
    if adjustment is None:
        return (
            f"real qualitative signal for this player ({qual_reason}) but it hasn't yet cleared this "
            "interface's own PERSISTENT_TREND bar, so zero adjustment has been applied to the quant model"
        )
    component_base = getattr(ep.components, adjustment.component)
    return (
        f"already added {adjustment.delta:+.2f} xP to this player's own {adjustment.component} component "
        f"(bounded to {MAX_ADJUSTMENT_FRACTION:.0%} of that component's real {component_base:.2f}pt value) - "
        f"real, but not enough on its own to move the model's overall pick"
    )


def _user_captain_signal(conn, squad_ids: list[int]) -> tuple[int | None, str | None]:
    if not squad_ids:
        return None, None
    placeholders = ",".join("?" * len(squad_ids))
    row = conn.execute(
        f"SELECT subject_id, note FROM user_observations "
        f"WHERE subject_type='player' AND subject_id IN ({placeholders}) AND sentiment='positive' "
        f"ORDER BY created_at DESC LIMIT 1",
        squad_ids,
    ).fetchone()
    if row is None:
        return None, None
    return row["subject_id"], row["note"]


def compare_captain_views(conn, squad_ids: list[int], options: list | None = None) -> CaptainViewComparison:
    """`options` (2026-08-27, Part 25 perf pass) - an optional, already-
    computed real `evaluate_captaincy` ranking to skip this function's own
    internal scan. See `compare_transfer_views`'s own docstring for the
    identical real-duplicate-work finding this mirrors."""
    if options is None:
        options = evaluate_captaincy(conn, sorted(squad_ids))
    model_pick = options[0] if options else None
    model_reason = (
        f"highest median projection ({model_pick.median} pts)" if model_pick else "no real captaincy data for this squad"
    )

    qual_id, qual_reason, qual_persistent, qual_signal = _qualitative_captain_signal(conn, squad_ids)
    qual_name = None
    if qual_id is not None:
        row = conn.execute("SELECT web_name FROM players WHERE id=?", (qual_id,)).fetchone()
        qual_name = row["web_name"] if row else None

    user_id, user_reason = _user_captain_signal(conn, squad_ids)
    user_name = None
    if user_id is not None:
        row = conn.execute("SELECT web_name FROM players WHERE id=?", (user_id,)).fetchone()
        user_name = row["web_name"] if row else None

    model_id = model_pick.player_id if model_pick else None

    if model_id is None:
        verdict, explanation = "INSUFFICIENT_EVIDENCE", "no real captaincy projection exists for this squad"
    elif user_id is not None and user_id != model_id:
        # The user's own explicit, real recorded observation disagrees -
        # never auto-resolved (spec section 83: recommend only). Surfaced
        # as UNDECIDED, not overridden either direction.
        verdict = "UNDECIDED"
        explanation = f"you've noted a preference for {user_name} over the model's {model_pick.web_name} - your call"
    elif qual_id is not None and qual_id != model_id and qual_persistent:
        verdict = "QUALITATIVE_WINS"
        gap = _quantify_qualitative_gap(conn, qual_id, qual_signal, qual_reason)
        explanation = f"{qual_name}'s real qualitative trend is a PERSISTENT positive signal - {gap}"
    elif qual_id is not None and qual_id != model_id and not qual_persistent:
        verdict = "MODEL_WINS"
        explanation = (
            f"a qualitative signal exists for {qual_name} ({qual_reason}) but it's only NEW_SIGNAL/not yet "
            f"a persistent trend - not enough real evidence to override the model's {model_pick.web_name} pick"
        )
    else:
        verdict = "MODEL_WINS"
        explanation = "no real disagreement between the model, the qualitative read, and your own recorded view"

    return CaptainViewComparison(
        model_pick=model_pick, model_reason=model_reason,
        qualitative_pick_id=qual_id, qualitative_pick_name=qual_name, qualitative_reason=qual_reason,
        user_pick_id=user_id, user_pick_name=user_name, user_reason=user_reason,
        verdict=verdict, explanation=explanation,
    )


# Real gap this closes (found 2026-08-26, matches this project's own disclosed
# gap in CLAUDE.md's "Post-match consistency pass" section): captain had real
# Decision Fusion, transfers did not - "Transfer Watch still recommended
# 'Tzolis -> Anderson' immediately after Tzolis's own real positive post-match
# signal... without any fusion between the two." Same rule-based comparison as
# captain (never a weighted-sum score), applied to the model's own proposed
# transfer-OUT player specifically - the real question a transfer decision
# needs fused evidence for is "should we actually sell this player", not "who
# should we buy" (the model's replacement pick isn't itself in dispute).
@dataclass(frozen=True)
class TransferViewComparison:
    model_candidate: TransferCandidate | None
    model_reason: str
    qualitative_direction: str | None
    qualitative_reason: str | None
    qualitative_persistent: bool
    user_sentiment: str | None
    user_reason: str | None
    verdict: str
    explanation: str


def _qualitative_signal_for_outgoing_player(conn, player_id: int) -> tuple[str | None, str | None, bool]:
    """Returns (direction, reason, is_persistent) for the most recent real
    FULL_TIME qualitative signal about the player the model wants to sell -
    any direction, not captaincy-scoped signals only (a transfer decision
    cares about ROLE/MINUTES/FIXTURES signals just as much as GOAL_THREAT).
    `is_persistent` uses the same qualitative_trends.py PERSISTENT_TREND
    check captain's own comparison uses - a single match is real evidence,
    not yet grounds to override the model on its own (spec's own "must earn
    the override through evidence" line)."""
    row = conn.execute(
        "SELECT direction, signal, reason FROM player_fpl_implications "
        "WHERE player_id=? AND phase='FULL_TIME' ORDER BY created_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    if row is None or row["direction"] is None:
        return None, None, False
    is_persistent = False
    pi = player_intelligence(conn, player_id)
    for t in pi.trends:
        if t.signal == row["signal"] and t.label == "PERSISTENT_TREND" and t.current_direction == row["direction"]:
            is_persistent = True
            break
    from fpl_agent.models.text_cleanup import clean_display_text

    return row["direction"], clean_display_text(row["reason"]), is_persistent


def _user_signal_for_player(conn, player_id: int) -> tuple[str | None, str | None]:
    row = conn.execute(
        "SELECT sentiment, note FROM user_observations WHERE subject_type='player' AND subject_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row["sentiment"], row["note"]


def compare_transfer_views(
    conn, squad_ids: list[int], bank_tenths: int | None, n_gw: int = 3,
    best_candidate: TransferCandidate | None = None, is_hit: bool = False,
) -> TransferViewComparison:
    """`best_candidate` (2026-08-27, Part 25 perf pass) - an optional,
    already-computed top-ranked `TransferCandidate` a caller can pass in to
    skip this function's own internal full-squad scan entirely. Real,
    measured duplicate work found live: `analyze_transfer_decision` already
    ranks every squad member's best replacement before ever calling this
    function (for its own `qualitative_note`), so its own top candidate is
    the identical answer this function would otherwise re-derive from
    scratch with a second full `best_transfer_for_player` scan per squad
    member. `is_hit` only applies to the internal scan (ignored when
    `best_candidate` is supplied - the caller's own candidate already
    reflects the real FT state it was computed with). Every existing caller
    that doesn't pass `best_candidate` keeps its exact prior behavior."""
    if bank_tenths is None:
        return TransferViewComparison(
            None, "no real bank figure known yet", None, None, False, None, None,
            "INSUFFICIENT_EVIDENCE", "no real bank figure known yet - a transfer comparison needs a real budget",
        )

    squad_ids = sorted(squad_ids)
    key = {1: "net_ev_1gw", 3: "net_ev_3gw", 5: "net_ev_5gw"}[n_gw]
    if best_candidate is None:
        for player_out_id in squad_ids:
            for candidate in best_transfer_for_player(conn, player_out_id, squad_ids, bank_tenths, is_hit=is_hit, n_gw=n_gw, top_n=1):
                if best_candidate is None or getattr(candidate, key) > getattr(best_candidate, key):
                    best_candidate = candidate

    if best_candidate is None:
        return TransferViewComparison(
            None, "no real positive-EV transfer found for this squad", None, None, False, None, None,
            "INSUFFICIENT_EVIDENCE", "no real transfer candidate exists to compare views on",
        )

    model_reason = f"{best_candidate.player_out_name} -> {best_candidate.player_in_name} (+{getattr(best_candidate, key)} net EV over {n_gw}GW)"

    qual_dir, qual_reason, qual_persistent = _qualitative_signal_for_outgoing_player(conn, best_candidate.player_out_id)
    user_sentiment, user_reason = _user_signal_for_player(conn, best_candidate.player_out_id)

    if user_sentiment == "positive":
        verdict = "UNDECIDED"
        explanation = (
            f"you've noted a bullish view on {best_candidate.player_out_name} - the model "
            f"suggests selling ({model_reason}), your call"
        )
    elif qual_dir == "POSITIVE" and qual_persistent:
        verdict = "QUALITATIVE_WINS"
        explanation = (
            f"{best_candidate.player_out_name}'s real qualitative trend is a PERSISTENT positive signal "
            f"({qual_reason}) - real evidence against selling, earns an override of the model's raw suggestion"
        )
    elif qual_dir == "POSITIVE" and not qual_persistent:
        verdict = "MODEL_WINS"
        explanation = (
            f"a real positive qualitative signal exists for {best_candidate.player_out_name} ({qual_reason}) but "
            f"it's only NEW_SIGNAL from one match, not yet a persistent trend - HOLD/REVIEW before acting on "
            f"{model_reason}, rather than an earned override"
        )
    else:
        verdict = "MODEL_WINS"
        explanation = f"no real disagreement - {model_reason}"

    return TransferViewComparison(
        model_candidate=best_candidate, model_reason=model_reason,
        qualitative_direction=qual_dir, qualitative_reason=qual_reason, qualitative_persistent=qual_persistent,
        user_sentiment=user_sentiment, user_reason=user_reason,
        verdict=verdict, explanation=explanation,
    )


# Real gap this closes (fpl.page-parity pass, direct spec: "For every major
# decision: OUR MODEL / SOLIO / MARKET / FOOTBALL / TEMPLATE. Do NOT average
# them. Show AGREE or MODEL OUTLIER or FOOTBALL CONFLICT or MARKET CONFLICT
# or TEMPLATE DIVERGENCE. Then WHY."). Every axis below already existed as
# ITS OWN separate panel (football: `compare_captain_views` above; market:
# `external_benchmark.compare_captain_pick` against Solio; template: the
# fpl.page-parity Template Team panel) - never cross-referenced in one
# place before, so answering "is the model an outlier" required opening
# three different Advanced-drawer panels. This is a pure synthesis/labeling
# layer over those three ALREADY-COMPUTED results - zero new modelling, no
# second scan of any of them (every input is optional and accepted
# pre-computed; a missing one degrades that one axis to
# INSUFFICIENT_EVIDENCE, never silently dropped from the row).
@dataclass(frozen=True)
class CrossCheckAxis:
    axis: str  # "FOOTBALL" | "MARKET" | "TEMPLATE"
    verdict: str  # "AGREE" | "FOOTBALL_CONFLICT" | "MARKET_CONFLICT" | "TEMPLATE_DIVERGENCE" | "INSUFFICIENT_EVIDENCE"
    why: str


@dataclass(frozen=True)
class CaptainCrossCheck:
    captain_id: int | None
    captain_name: str | None
    axes: tuple[CrossCheckAxis, ...]
    all_agree: bool


def captain_cross_check(
    conn, squad_ids: list[int], ca=None, solio_comparison=None, template_players: list | None = None,
) -> CaptainCrossCheck:
    """`ca` - the already-computed real `CaptainDecisionAnalysis` (the
    dashboard's own `ca`, `decision_analysis.analyze_captain_decision`'s
    output) - our model's REAL current pick (`ca.suggested or ca.current`),
    never re-derived via a second `evaluate_captaincy` call the way
    `compare_captain_views` above does on its own when no options are
    passed. `solio_comparison`/`template_players` are likewise optional
    already-computed results (`external_benchmark.compare_captain_pick`,
    `models.template.get_template`) - `None` when that source genuinely
    isn't available yet (no Solio sync, no ownership data), which degrades
    only that one axis to INSUFFICIENT_EVIDENCE rather than fabricating a
    verdict."""
    model_pick = None
    if ca is not None:
        model_pick = ca.suggested or ca.current
    captain_id = model_pick.player_id if model_pick else None
    captain_name = model_pick.web_name if model_pick else None

    axes = []

    # FOOTBALL axis - reuses the same real, cheap qualitative-signal read
    # `compare_captain_views` uses, not that function's own full comparison
    # (which would re-run `evaluate_captaincy`).
    qual_id, qual_reason, qual_persistent, qual_signal = _qualitative_captain_signal(conn, squad_ids)
    if captain_id is None:
        axes.append(CrossCheckAxis("FOOTBALL", "INSUFFICIENT_EVIDENCE", "no real model captain pick to compare against"))
    elif qual_id is not None and qual_id != captain_id and qual_persistent:
        qual_row = conn.execute("SELECT web_name FROM players WHERE id=?", (qual_id,)).fetchone()
        qual_name = qual_row["web_name"] if qual_row else "another player"
        gap = _quantify_qualitative_gap(conn, qual_id, qual_signal, qual_reason)
        axes.append(CrossCheckAxis(
            "FOOTBALL", "FOOTBALL_CONFLICT",
            f"a real persistent positive qualitative trend favors {qual_name} over {captain_name} - {gap}",
        ))
    else:
        axes.append(CrossCheckAxis("FOOTBALL", "AGREE", "no real persistent qualitative signal contradicts this pick"))

    # MARKET axis - Solio's own real top-captain pick, already computed by
    # `external_benchmark.compare_captain_pick` (comparison layer only,
    # never a projection input - see that module's own docstring).
    if solio_comparison is None or solio_comparison.verdict == "INSUFFICIENT_EVIDENCE":
        why = solio_comparison.why if solio_comparison is not None else "no Solio benchmark run yet this session"
        axes.append(CrossCheckAxis("MARKET", "INSUFFICIENT_EVIDENCE", why))
    elif solio_comparison.verdict == "DIVERGENCE":
        axes.append(CrossCheckAxis("MARKET", "MARKET_CONFLICT", solio_comparison.why))
    else:
        axes.append(CrossCheckAxis("MARKET", "AGREE", solio_comparison.why))

    # TEMPLATE axis - real, honest, narrow scope: does the highest-owned
    # (sampled-EO where available, else raw) real player pool at the
    # captain's own position even include the captain pick. This project has
    # no real "captain popularity" data source (fpl.page's own real EO
    # sample doesn't carry per-player captaincy share) - divergence here
    # means "the wider template doesn't even own this player", a real,
    # narrower, honestly-scoped signal, not a fabricated captaincy-rate
    # comparison.
    if captain_id is None or not template_players:
        axes.append(CrossCheckAxis("TEMPLATE", "INSUFFICIENT_EVIDENCE", "no real template ownership data available"))
    else:
        position = None
        for tp in template_players:
            if tp.player_id == captain_id:
                position = tp.position
                break
        if position is not None:
            axes.append(CrossCheckAxis("TEMPLATE", "AGREE", f"{captain_name} is in the real highest-owned {position} pool"))
        else:
            axes.append(CrossCheckAxis(
                "TEMPLATE", "TEMPLATE_DIVERGENCE",
                f"{captain_name} does not appear in the real highest-owned pool for their position - a genuine differential captain pick",
            ))

    return CaptainCrossCheck(
        captain_id=captain_id, captain_name=captain_name, axes=tuple(axes),
        all_agree=all(a.verdict in ("AGREE", "INSUFFICIENT_EVIDENCE") for a in axes),
    )
