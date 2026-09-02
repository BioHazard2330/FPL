# Session 39 — 2026-09-02: Decision Engine Rebuild

Direct spec: build one coherent decision system — audit the existing
mathematical behaviour and architecture first, no implementation changes
until it's traced and reported.

**Real, critical bug found + fixed: `_squad_gw_ev` had no XI/captain
awareness.** `optimization/transfers.py::_squad_gw_ev` — the value function
used by EVERY multi-GW path/step in the beam search — summed flat per-player
EV across the WHOLE 15-man squad, uncaptained, bench included at full weight.
It never resolved a real formation-legal starting XI, never applied the
captain multiplier, never down-weighted the bench. This affected every real
multi-GW recommendation in the system. Fixed via a new
`resolve_gw_xi` (resolves a real formation-legal XI via
`optimization.squad.pick_starting_xi`) and a rewritten `_squad_gw_ev` that is
genuinely XI + captain + bench-weighted. `chips.py::wildcard_value`/
`freehit_value` were also using a flat uncaptained sum as their comparison
baseline — fixed to use the corrected `_squad_gw_ev`.

**New canonical `DecisionSnapshot`** (`optimization/decision_snapshot.py`) —
one authoritative, reproducible decision object (decision_id, state_version,
model_version, horizon, action, expected_points by horizon, confidence,
verdict, tie_classification, robustness, alternatives, reasons, reversal
conditions). Reads the SAME hysteresis-stable `stable_current_recommendation`
source the dashboard's own primary verdict uses (not raw latest), so the two
are guaranteed consistent — proven by a dedicated dashboard-consistency
regression test. `_tie_classification` (LIKELY_BEST/NEAR_TIE/HIGH_UNCERTAINTY)
and `_reversal_conditions` (real, computed "runner-up would need +X.XX xP to
overtake this action" margins) are the load-bearing pieces later reused by
Session 41's decision-effect classification.

New `evaluate_user_scenario` — lets a user ask "what if I do X instead" and
get a real, computed comparison against the actual current recommendation,
reusing the existing search/checkpoint machinery rather than a second
optimizer.

`optimization/squad.py::pick_starting_xi` hardened against NULL
`squad_min_play`/`squad_max_play` (minimal test fixtures could crash it).
`post_gw_pipeline.py` now passes pre-computed `ta`/`ca` into
`evaluate_locked_squad` to avoid a redundant re-scan.

3 pre-existing tests in `test_transfer_search.py` had encoded the OLD flat-sum
math — recomputed the correct captain-aware expected values by hand and
updated the assertions (the fix was correct, the old tests weren't). New
`test_decision_snapshot.py` (22 tests). Full suite green.
