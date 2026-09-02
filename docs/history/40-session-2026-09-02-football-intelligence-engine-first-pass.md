# Session 40 — 2026-09-02: Football Intelligence Engine, First Pass

Direct spec: turn the qualitative layer into structured signals — audit the
existing qualitative data flow before modifying anything.

**Own assumption revised during the audit**: expected to find no real
persistence system for qualitative evidence; found one already existed and
was sound (`models/qualitative_trends.py::classify_direction_history` —
NEW_SIGNAL/PERSISTENT_TREND/REVERSAL/NOISE over an arbitrary string
sequence, generic enough to reuse for role/formation/setpiece-order values
too, not just POSITIVE/NEGATIVE — confirmed and reused rather than rebuilt in
Session 41).

**Real duplicate-signal bug found + fixed**: `models/statistical_evidence.py::
record_statistical_evidence`'s exists-check was scoped to its own
`analysis_version` — blind to a row the LLM `.claude/skills/
match-intelligence-analysis` skill already wrote for the identical
(match, subject, signal) under its own `qual-v1` tag. Whichever system ran
SECOND for a given match would re-add a redundant row. Fixed by checking
existence across ANY `analysis_version` — this became the standing dedup
pattern Session 41's new detectors also follow.

**Real stale-explanation bug found + fixed**: `models/decision_fusion.py`'s
captain cross-check reported a generic "qualitative view differs" note
without ever stating the actual applied number. New
`_quantify_qualitative_gap` computes the real applied adjustment via
`compute_qualitative_adjustment` and reports the actual `+X.XX xP`.

**New canonical `FootballSignal`** (`models/football_signal.py`) — a real
unifying VIEW (not a new storage layer) over `match_observations` +
`SignalTrend` + `compute_qualitative_adjustment`, with
OBSERVATION/INTERPRETATION/FPL_EFFECT/DECISION_EFFECT kept as explicit
separate fields. `classify_decision_effect` is the real bridge to Phase 2's
`DecisionSnapshot` — reads its already-computed alternatives/margins,
never re-runs the beam search; only reaches DECISION_CHANGING when the
signal's own applied xP effect is at least as large as the real,
already-computed runner-up margin.

19 new tests (`test_football_signal.py`). 3 deferred items (role-change,
set-piece, tactical-change detectors) explicitly carried to Session 41 due to
context budget.
