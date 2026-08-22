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
