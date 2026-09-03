---
name: fpl-football-intelligence
description: Use when writing, reviewing, or rendering any football-evidence text in this project - player/team signals, match observations, role/set-piece/tactical change detections, FPL interpretation of a football event, or any copy that will appear in the FOOTBALL or SCOUT dashboard screens. Applies to both generating new detector/observation text (Python) and auditing existing text for AI-filler language. Not for the optimizer's own decision math (see decision-engine rules in CLAUDE.md) or for general UI layout (see fpl-visualization).
---

# FPL Football Intelligence

This project's own real signal pipeline: `models/football_signal.py`
(`FootballSignal`, `squad_football_signals`), `models/role_signal_detectors.py`
(ROLE_CHANGE/SET_PIECE_CHANGE/TACTICAL_CHANGE), `models/statistical_evidence.py`
(GOAL_THREAT/CREATION/MINUTES, zero-LLM), `models/match_intelligence.py` +
`.claude/skills/match-intelligence-analysis` (LLM qualitative layer),
`models/team_outlook.py`, `models/decision_fusion.py` (MODEL vs FOOTBALL/MARKET
cross-check). This skill governs the STYLE and REASONING DISCIPLINE of what
those modules write and what the dashboard (`monitoring/dashboard/football.py`,
`scout.py`, `myteam.py`) renders from them - it does not replace any of them
with a new detector or a new data source.

## The rule this skill exists to enforce

Every piece of football-evidence text in this codebase was, before 2026-09-03,
riddled with a specific failure mode: hardcoded strings like `"a genuinely high
shot volume ... real attacking involvement"` or `"Real increase in
corner-taking priority"` that ADD ZERO INFORMATION over the number already
computed. This was found and partially fixed in `statistical_evidence.py`/
`role_signal_detectors.py`/`opportunity.py` (2026-09-03, Phase 6.5) - this
skill is what prevents it from creeping back in, in those files or new ones.

**Strictly prohibit** these words in user-facing football/FPL copy unless the
sentence they sit in also states the specific number that justifies them:
genuine, real (as an intensifier - "a real shot" is fine when `real` means
"actually happened", not when it means "trust me, this matters"), sustained,
trusted, meaningful, significant, high-quality, encouraging, impressive.

Prefer:
- `"5 shots, 0.89 xG"` over `"genuine attacking involvement"`
- `"corner order 3 -> 1"` over `"real increase in corner-taking priority"`
- `"started 4/4; 332 minutes"` over `"trusted starter"`
- `"0.85 xG this match vs 0.30 xG average over last 5"` over `"a real shift toward a more advanced role"`

The number is the evidence. The adjective is filler. If you can delete the
adjective and the sentence loses no information, delete it.

## EVENT -> EVIDENCE -> FPL EFFECT, not EVENT -> adjective

Every signal-level row in FOOTBALL/SCOUT should structurally separate three
things (`FootballSignal`'s own `evidence`/`interpretation`/`fpl_effect` fields
map onto this - see `football.py::_signal_row_html`, evidence leads,
interpretation is a short secondary tag, never the reverse):

1. **WHAT HAPPENED** (the observed fact - a number, a change, a real event)
2. **FPL EFFECT** (what it means for scoring/selection - also short and concrete: "supports goal threat", "promoted to corner taker #1", never a full sentence of prose)
3. **CONFIDENCE / PERSISTENCE** (already-computed fields: `confidence`, `persistence`, `times_observed`, `decision_effect` - state the real value, never invent a confidence level)

Different event types get different real fields, not the same template
stretched over every category:

| Category | Real fields to surface | Source |
|---|---|---|
| ROLE_CHANGE | old xG/KP baseline -> current, role shift direction | `role_signal_detectors.detect_role_changes` |
| SET_PIECE_CHANGE | `old_value -> new_value` order (penalties/corners/direct FK) | `role_signal_detectors.detect_setpiece_changes`, `player_setpiece_history` |
| TACTICAL_CHANGE | baseline formation vs current, real match count | `role_signal_detectors.detect_tactical_changes`, `team_match_state.formation` |
| GOAL_THREAT / CREATION | shots/xG, key passes/xA, this match only | `statistical_evidence._player_observations` |
| MINUTES | minutes played, or minute of substitution | `statistical_evidence._player_observations` |
| Team ATTACK/DEFENCE | real `team_match_state.xg`/`.shots` averaged over N recent matches, joined to the opponent's own row for the against-side | `football._team_recent_form` |

## Classify internally: FACT / MODEL / ASSUMPTION / FORECAST / SPECULATION

Before writing or approving a football-evidence sentence, know which of these
it is. The dashboard may simplify the label shown to the user, but the
underlying reasoning in code/comments/commit messages must preserve the
distinction:

- **FACT**: a directly observed number this match (shots, xG, minutes, a
  `player_setpiece_history` order value). Never disputable.
- **MODEL**: a computed projection (`expected_points`, Dixon-Coles CS%,
  `player_shrunk_rates`). Real, reproducible, but a model output, not an
  observation - never phrase it as if FPL or the club confirmed it.
- **ASSUMPTION**: a baseline/threshold choice the detector makes explicit
  (`_MIN_BASELINE_MATCHES`, `_ROLE_XG_RATIO_ADVANCE`) - these are disclosed,
  tunable, and already documented in each detector's own docstring; never
  present their output as if it were a FACT.
- **FORECAST**: a forward-looking number (next-GW xP, chip timing value) -
  always distinct from what already happened.
- **SPECULATION**: a stated guess about WHY something happened when the data
  doesn't directly show it (see "do not invent causality" below) - avoid
  writing this into persisted data at all; if a human analyst wants to
  speculate, that belongs in a qualitative-skill `inferred` field explicitly
  labeled as interpretation, never blended into `observed`.

## Do not invent causality

The data shows what happened, not why, unless a real, cited source (team news,
official confirmation, the qualitative-analysis skill's own sourced evidence)
says why.

- Shots went up: `"5 shots this match vs 2.1 average"` - a FACT.
  Do NOT write `"player is playing better"` - that's an unsupported causal
  claim the shot count alone can't carry (fitness, opponent weakness, a
  tactical change, and randomness are equally consistent with the same
  number).
- A player started: `"started, 90 minutes"` - a FACT.
  Do NOT write `"manager trusts the player"` - selection is not evidence of
  trust; it's evidence of selection. If the manager said something about
  trust (a real quoted source), attribute it to that source, not to the
  selection itself.
- A formation changed once: `"4-3-3 -> 4-2-3-1 this match"` - a FACT, and
  `role_signal_detectors.detect_tactical_changes` already correctly labels a
  single-match departure `"not yet confirmed as persistent"` rather than
  inventing a tactical explanation for WHY the manager changed it. Keep that
  discipline in any new detector: report the change, not a manufactured
  reason for the change, unless a real source states the reason.

## FPL interpretation checklist

Every football observation surfaced to the user should be able to answer,
using only real already-computed fields (never invented for the purpose of
answering the question):

1. What happened? -> `evidence` / `observed`
2. What evidence supports it? -> the same field, plus `confidence`
3. What changed? -> the before/after in the evidence string, or `direction`
4. Which player(s) benefit? -> `entity_name` + `fpl_effect` (POSITIVE direction)
5. Which player(s) are harmed? -> same fields (NEGATIVE/WATCH direction)
6. What does it mean for FPL? -> `fpl_effect` / `interpretation` (short, concrete)
7. How confident are we? -> `confidence` (low/medium/high, the row's real value)
8. Is this persistent enough to act on? -> `persistence` (NEW_SIGNAL /
   PERSISTENT_TREND / REVERSAL / NOISE) and `times_observed`, from
   `qualitative_trends.py`'s own classifier - never restate a NEW_SIGNAL as if
   it were a PERSISTENT_TREND to make a card feel more actionable.

If a real answer to one of these questions doesn't exist yet (e.g. no
`decision_snapshot` was available so `decision_effect` degraded to WATCH/
MONITOR), say so honestly (`football.py` already does this) rather than
omitting the question or fabricating an answer.

## Known, disclosed limits (do not silently "fix" by fabricating)

- `TACTICAL_CHANGE`/`ROLE_CHANGE` need >=2 real prior matches as a baseline
  (`_MIN_BASELINE_MATCHES`) - early season, this correctly produces zero
  signals. That is honest, not a bug.
- Editing a detector's OWN string templates (as this skill requires) does
  **not** retroactively rewrite text already persisted in
  `match_observations` - `record_role_signal_evidence`/
  `record_statistical_evidence` are additive/deduped, never UPDATE. A style
  fix lands on the NEXT real match analyzed, not on historical rows. Never
  attempt a blind mass-rewrite of that table to make old rows match new
  style; that's a real data-integrity risk out of proportion to a copy fix.
- `player_match_state.position`/`.touches_box` are ~0% populated in
  production (FotMob's free feed doesn't carry them) - `ROLE_CHANGE` uses a
  shots/xG profile-shift proxy instead, disclosed in the detector's own
  docstring. Don't write copy that implies literal positional tracking exists.

## Where this applies in the dashboard

`monitoring/dashboard/football.py` (the FOOTBALL screen's signal feed and
`_team_state_card_html`), `monitoring/dashboard/scout.py` and `opportunity.py`
(recruitment-board `why_now` text), `monitoring/dashboard/myteam.py`'s
`_weak_links_html`, and any future match-event/live-tracking copy. Also
applies when reviewing output from `.claude/skills/match-intelligence-analysis`
(the LLM qualitative layer) - that skill's own prompt should be checked against
this one's filler-word list when it's next revised, though its `inferred`
field is explicitly allowed to be genuine interpretation (labeled as such,
kept separate from `observed`) rather than a bare fact.
