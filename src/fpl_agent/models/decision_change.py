"""Real "why did the recommendation change" explanation (2026-08-28, direct
user P4 ask). Compares the two most recent real `strategic_plan` decisions'
own `current_recommendation` label - never re-derives a decision, only
diffs two already-computed ones - and, when they differ, attributes it to
the real triggering `change_events` row via
`decision_freshness.has_material_change_since` (the same real change-log
this project's own staleness banner already reads, not a second
change-detection mechanism).

Real, disclosed limit: this can only explain a change to the CURRENT
RECOMMENDED ACTION (`strategic_plan`'s own `synthesize_current_recommendation`
output) - the specific field the dashboard's Home hero surfaces. A change in
some other displayed number (e.g. a captain-only KEEP/CHANGE flip from
`analyze_captain_decision`, which runs live every regen and has no cached
"previous decision" to diff against) isn't covered by this function."""
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionChangeExplanation:
    old_label: str
    new_label: str
    old_verdict: str
    new_verdict: str
    changed_at: str  # the NEW decision's created_at
    trigger: str | None  # a real change_events summary, or None if no single HIGH-severity event explains it
    explanation: str  # one concise, human-composed line - never backend prose


def latest_recommendation_change(
    conn: sqlite3.Connection, squad_ids: set[int] | None = None,
) -> DecisionChangeExplanation | None:
    """`None` when fewer than two real `strategic_plan` decisions exist yet,
    either is missing a real `current_recommendation` (an older decision
    logged before that field existed, or a genuine no-data REVIEW state), or
    the two labels are actually identical (nothing to explain - the common
    case on most regens)."""
    from fpl_agent.database.decisions import list_decisions_of_type
    from fpl_agent.models.decision_freshness import has_material_change_since

    recent = list_decisions_of_type(conn, "strategic_plan", limit=2)
    if len(recent) < 2:
        return None
    newest, previous = recent[0], recent[1]
    new_rec = newest.detail.get("current_recommendation")
    old_rec = previous.detail.get("current_recommendation")
    if new_rec is None or old_rec is None:
        return None
    if new_rec["label"] == old_rec["label"] and new_rec["verdict"] == old_rec["verdict"]:
        return None

    change = has_material_change_since(conn, previous.created_at, squad_ids)
    if change is not None:
        if change["entity"] == "player":
            row = conn.execute("SELECT web_name FROM players WHERE id=?", (change["entity_id"],)).fetchone()
            name = row["web_name"] if row is not None else f"player {change['entity_id']}"
            trigger = f"{name}: {change['event_type']} ({change['old_value']} -> {change['new_value']})"
        else:
            trigger = f"{change['entity']} {change['entity_id']}: {change['event_type']}"
        explanation = f"{old_rec['label']} -> {new_rec['label']} because {trigger}"
    else:
        # A real change happened (the labels differ), but no single
        # HIGH-severity change_events row explains it - could be a real
        # projection drift (odds/lineup-probability movement, none of which
        # individually crosses the HIGH bar) or a manual re-run. Honest,
        # not fabricated: never invent a specific cause the log doesn't support.
        trigger = None
        explanation = f"{old_rec['label']} -> {new_rec['label']} (real projection/candidate-pool change since the last run, no single HIGH-severity trigger recorded)"

    return DecisionChangeExplanation(
        old_label=old_rec["label"], new_label=new_rec["label"],
        old_verdict=old_rec["verdict"], new_verdict=new_rec["verdict"],
        changed_at=newest.created_at, trigger=trigger, explanation=explanation,
    )
