# Session 41 — 2026-09-02: Football Intelligence Engine, Phase 3 Finalization

Direct spec: finish the three explicitly deferred detector areas from Session
40 (ROLE_CHANGE, SET_PIECE_CHANGE, TACTICAL_CHANGE), formalize signal expiry,
run the complete suite, verify production behaviour, then stop — explicit
"do not pad this phase with extra features" instruction, explicit DO NOT
TOUCH list (dashboard/CSS/charts/Match Report/nav/ApexCharts/Strategic Plan
UI/projection math/scheduler/Phase 2 architecture).

**Real, disclosed data-availability finding, checked before writing any
detector**: `player_match_state.position` and `.touches_box` are 0/654
populated in the real dataset — FotMob's free per-player feed doesn't carry
them here at all, a total gap, not a per-player one. A literal position-label
change detector is not buildable from real data. `xg`/`shots` are 654/654
populated; `key_passes`/`xa` are partially populated (293/654, 204/654).

**New `models/role_signal_detectors.py`** — three deterministic, zero-LLM
detectors reusing the SAME `DetectedObservation` shape and cross-source dedup
pattern `statistical_evidence.py` established:
- `detect_role_changes`: real shots/xG attacking-output profile shift vs a
  player's own rolling baseline (the honest, available substitute for the
  missing `position` field — a real xG spike >= 2x baseline signals an
  advanced role; a real key-passes collapse signals a fading creative role).
- `detect_setpiece_changes`: real `player_setpiece_history` version-order
  changes (penalty/corner/direct-FK), anchored to the ONE real match where
  the change took effect.
- `detect_tactical_changes`: real formation departure from a team's own
  recent-match baseline, with a linked player-level ROLE_CHANGE tag when a
  same-match role shift co-occurs (never a second, competing detection pass —
  the SAME role observation is mutated in place, not duplicated).

Wired into the same two real trigger points `record_statistical_evidence`
already uses (`fotmob_source.py`'s live FULL_TIME transition,
`post_gw_pipeline.py`'s defensive backfill) — same non-fatal try/except
posture.

**Real bug found + fixed via production verification, not by unit tests**:
`detect_setpiece_changes` initially re-fired the SAME real order-change on
every later match the player played, not just the match where it took
effect — running the fixed-before-this-bug detector against
`data/fpl.db` produced 76 rows from a handful of real changes across only 20
real matches. Anchored to the player's own earliest real match with
`kickoff_utc >= ` the new version's `valid_from`; re-verified live, 33 real
rows, 0 duplicates on rerun. Also disclosed: the detector only ever compares
the two MOST RECENT setpiece-history versions, so an older transition
superseded by a newer one is never retroactively re-detected — a real,
accepted scope limit (mirrors `statistical_evidence.py`'s own
current-state-only posture), not a bug.

**Temporal fields formalized, not a second persistence system**:
`FootballSignal` gained `last_confirmed_at` and a real, category-aware
`expires_at`/`EXPIRED` status (`_CATEGORY_EXPIRY_WINDOW`: ROLE_CHANGE/
SET_PIECE_CHANGE = 5 real matches, TACTICAL_CHANGE = 3 — a real match-count
clock, never a calendar-day guess) computed at read-time in
`build_football_signal`, layered on top of — never replacing —
`qualitative_trends.py`'s own NEW_SIGNAL/PERSISTENT_TREND/REVERSAL/NOISE
label. `squad_football_signals` now excludes EXPIRED by default (the real
"active intelligence" surface), while `football_signals_for_entity` stays
the full, unfiltered history.

**Qualitative → quantitative wiring, existing interface only**:
`qualitative_feed.py::_COMPONENT_SIGNAL_MAP` gained `ROLE_CHANGE`/
`SET_PIECE_CHANGE` → `goals` (same honesty test as the existing GOAL_THREAT/
SET_PIECES mappings — both are genuinely about the player's own goal threat).
No second adjustment pathway.

**Real, disclosed architecture consequence found during testing**: because
`detect_setpiece_changes` now correctly anchors to exactly ONE real match per
transition, SET_PIECE_CHANGE signals from this detector alone are
structurally always NEW_SIGNAL (sample_size=1) under the existing classifier
— they cannot naturally reach PERSISTENT_TREND without a second, independent
real source (e.g. a later qualitative-skill reconfirmation) corroborating the
same fact for a different real match. This caps them at MONITOR for
decision-effect purposes and means they won't earn a quantitative adjustment
on their own. This is an honest interaction with reusing the existing
classifier unmodified (the explicit instruction), not a defect.

**Real production verification** (all 8 required checks run against
`data/fpl.db`, not mocked): SET_PIECE_CHANGE generates real signals (33 rows,
spot-checked — e.g. "Real corner order changed from 4 to 2"); ROLE_CHANGE/
TACTICAL_CHANGE correctly produce ZERO signals right now (confirmed live:
production has at most 2 real matches per player/team so far this season,
below the `_MIN_BASELINE_MATCHES=2`-prior-match bar both detectors require —
a genuine data-volume gap that will close as the season progresses, not a
bug); real `detected_at`/`last_confirmed_at` timestamps confirmed on live
`squad_football_signals` output; a real captain (B.Fernandes) reached
MATERIAL decision-effect with a real applied `+0.18 xP` through the actual
canonical `DecisionSnapshot`; EXPIRED-exclusion verified via unit test (no
real signal is old enough yet to demonstrate live); qualitative detectors
remain async/non-fatal, the optimizer's own decision path was not touched.

87 new tests (detection/persistence/dedup per category, temporal fields,
expiry/reconfirmation, qualitative→projection integration, decision-impact
integration, backfill+qualitative-rerun). Full suite: 1411 passed, 0 failed
(14m39s). Phase 3 closed — no dashboard/UI/scheduler/Phase-2 changes made.
