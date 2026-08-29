"""Real, typed event vocabulary (2026-08-29, "live architecture rebuild"
pass, milestone 1). Every downstream engine in this project subscribes to
these exact types, never a free-text string it has to parse - the single
real event taxonomy the whole live pipeline shares.

Deliberately NOT every type here is currently emitted by a real producer -
`BIG_CHANCE` is defined for a future source that publishes a genuine
per-event big-chance flag (FotMob's own real shotmap has no such field,
only an aggregate team-level count - checked directly, not assumed - so
this project never fabricates a per-shot big-chance heuristic). Each
producer module's own docstring says exactly which of these it emits."""
from enum import Enum


class EventType(str, Enum):
    # Match lifecycle
    MATCH_STARTED = "MATCH_STARTED"
    MATCH_HALFTIME = "MATCH_HALFTIME"
    MATCH_RESUMED = "MATCH_RESUMED"
    MATCH_FINISHED = "MATCH_FINISHED"
    # Real per-incident football events (FotMob matchFacts/shotmap)
    GOAL = "GOAL"
    ASSIST = "ASSIST"
    SHOT = "SHOT"
    BIG_CHANCE = "BIG_CHANCE"  # defined, not currently emitted - see module docstring
    CARD = "CARD"
    SUBSTITUTION = "SUBSTITUTION"
    LINEUP_CONFIRMED = "LINEUP_CONFIRMED"
    # Derived/state-change events
    PLAYER_STATE_CHANGED = "PLAYER_STATE_CHANGED"
    TEAM_STATE_CHANGED = "TEAM_STATE_CHANGED"
    FPL_POINTS_CHANGED = "FPL_POINTS_CHANGED"
    BONUS_CHANGED = "BONUS_CHANGED"
    PRICE_CHANGED = "PRICE_CHANGED"
    AVAILABILITY_CHANGED = "AVAILABILITY_CHANGED"
    FIXTURE_CHANGED = "FIXTURE_CHANGED"
