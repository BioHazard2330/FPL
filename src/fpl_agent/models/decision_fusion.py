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


def _qualitative_captain_signal(conn, squad_ids: list[int]) -> tuple[int | None, str | None, bool]:
    """Returns (player_id, reason, is_persistent) for the squad member with
    the most recent POSITIVE captaincy-relevant qualitative implication.
    `is_persistent` is True only when that player's own trend for the same
    signal is PERSISTENT_TREND (qualitative_trends.py) - a single good
    match is real evidence but not yet grounds to override a calibrated
    quant model on its own (spec section 16's own "not from tiny samples"
    rule, applied here to the fusion decision itself)."""
    if not squad_ids:
        return None, None, False
    placeholders = ",".join("?" * len(squad_ids))
    row = conn.execute(
        f"SELECT player_id, signal, reason, created_at FROM player_fpl_implications "
        f"WHERE player_id IN ({placeholders}) AND direction='POSITIVE' AND signal IN "
        f"({','.join('?' * len(_CAPTAINCY_RELEVANT_SIGNALS))}) AND phase='FULL_TIME' "
        f"ORDER BY created_at DESC LIMIT 1",
        [*squad_ids, *_CAPTAINCY_RELEVANT_SIGNALS],
    ).fetchone()
    if row is None:
        return None, None, False

    is_persistent = False
    pi = player_intelligence(conn, row["player_id"])
    for t in pi.trends:
        if t.signal == row["signal"] and t.label == "PERSISTENT_TREND" and t.current_direction == "POSITIVE":
            is_persistent = True
            break
    return row["player_id"], row["reason"], is_persistent


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


def compare_captain_views(conn, squad_ids: list[int]) -> CaptainViewComparison:
    options = evaluate_captaincy(conn, sorted(squad_ids))
    model_pick = options[0] if options else None
    model_reason = (
        f"highest median projection ({model_pick.median} pts)" if model_pick else "no real captaincy data for this squad"
    )

    qual_id, qual_reason, qual_persistent = _qualitative_captain_signal(conn, squad_ids)
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
        explanation = (
            f"{qual_name}'s real qualitative trend is a PERSISTENT positive signal ({qual_reason}) "
            f"the quant model's projection doesn't yet fully capture"
        )
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
    return row["direction"], row["reason"], is_persistent


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
) -> TransferViewComparison:
    if bank_tenths is None:
        return TransferViewComparison(
            None, "no real bank figure known yet", None, None, False, None, None,
            "INSUFFICIENT_EVIDENCE", "no real bank figure known yet - a transfer comparison needs a real budget",
        )

    squad_ids = sorted(squad_ids)
    best_candidate: TransferCandidate | None = None
    key = {1: "net_ev_1gw", 3: "net_ev_3gw", 5: "net_ev_5gw"}[n_gw]
    for player_out_id in squad_ids:
        for candidate in best_transfer_for_player(conn, player_out_id, squad_ids, bank_tenths, is_hit=False, n_gw=n_gw, top_n=1):
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
