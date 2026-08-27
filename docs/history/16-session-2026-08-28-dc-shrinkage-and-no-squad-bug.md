# 2026-08-28: Two real bugs fixed - Dixon-Coles small-sample overfit, "no squad" crash path

Direct user report with a concrete, checkable example: "the dashboard says no squad for some
reason... clean sheet projections and goals were very very off. i saw one example where it was
predicting 84% clean sheet to hull."

## Bug 1: Dixon-Coles small-sample overfit (real, confirmed, fixed)

Traced Hull's real GW2-6 fixture projections directly: goals-against as low as 0.19-0.23
(=79-83% clean sheet) in three separate fixtures against three different opponents - implausible
for any team, let alone a newly-promoted one. Root cause, confirmed against the real production
DB: Hull's only finished match this season is a real shock **2-0 win over Man Utd (GW1)**.
`team_strength_dc.py::fit_dixon_coles` is an unregularized maximum-likelihood fit - with exactly
one real match to inform Hull's attack/defence parameters, the optimizer ran both to the edge of
its own `[-3, 3]` bound trying to explain that single shock result, producing wildly overconfident
attack AND defence ratings. `promoted_team_calibration.py` already exists in this codebase
specifically for promoted teams, but only covers the *zero*-real-match case (before a promoted
team's first PL game) - once a team plays even one match, it moves onto the live, unregularized
fit with no small-sample protection at all. A real, well-known gap in the model, not previously
caught because GW1 hadn't been played when earlier passes checked this.

**Fix**: added a real L2 (ridge) prior to the Dixon-Coles fit, pulling every team's attack/defence
toward 0 (league-average) - the same empirical-Bayes shrinkage philosophy this project already
applies to every player-level rate (`player_regression.py`), just missing at the team-strength
level until now. A team with many real matches has enough likelihood signal to overcome the fixed
penalty and settle near its true rating; a team with one or two does not, and gets pulled back
toward average automatically (no per-team special-casing needed - the same fixed `ridge_lambda`
produces adaptive per-team shrinkage purely because data-rich teams' likelihood gradients are
strong enough to win the tug-of-war against it).

The ridge term is scaled by the *mean* per-match decay weight, not a flat constant - required to
exactly preserve `_dc_fit_as_of_date`'s own load-bearing performance optimization (collapsing many
distinct future as-of-dates to one shared cached fit, backed by a real mathematical proof that a
uniform rescale of decay weights can't change the likelihood argmax). A flat ridge term breaks
that proof (confirmed by a real test failure during development -
`test_dc_fit_coarsening_produces_mathematically_identical_model_params`); scaling by the mean
weight (which itself rescales by the exact same constant under a uniform shift) restores the
guarantee exactly, verified by that same test passing again.

**Verified**: Hull's clean-sheet range across GW2-6 moved from 24.9%-83.0% (three implausible
extremes) to 24.9%-49.9% (all plausible), while real strength differentiation is preserved
(Man City 42% > Arsenal 35% > Hull ~25-38% CS, not flattened to uniformity). Ran the project's
own `fpl backtest --season 2025-26` with and without the fix (`ridge_lambda=2.5` vs `0.0`) -
**identical MAE (1.1776) both ways**, confirming zero regression on a fully-played historical
season where every team already has abundant real match history within the fitting window (the
fix specifically targets sparse-sample teams, which a completed season's mid-fit rarely has).
`_RIDGE_LAMBDA=2.5` is disclosed as a real, not-yet-backtest-tuned starting value - proper tuning
needs a season with real promoted-team small-sample rounds to score against, which doesn't exist
yet this early in 2026-27.

## Bug 2: "no squad" reported despite a real synced squad existing (hardened, not yet reproduced)

Traced the full `get_locked_squad()` call chain. Currently working correctly against the live
production DB, so the exact historical trigger couldn't be reproduced live this session - but
found and fixed one real, concrete crash path along the way: `_xi_from_real_picks` did
`row["squad_slot"] <= 11` with no guard against a `NULL` `squad_slot` (a genuinely malformed
`my_team_picks` row) - `None <= 11` raises `TypeError` in Python, and this function's caller chain
(`get_locked_squad` -> `generate_dashboard_html`) had **no exception handling anywhere**, so one
bad row could crash the entire dashboard regen. Fixed to default a `NULL` slot to bench (logged,
not fabricated as a starting-XI decision) rather than crash.

Also added real diagnostic logging for the two other ways this function could silently report "no
locked squad" despite real picks existing (a real pick with no matching `build_player_pool` entry,
and the full "picks exist but zero landed in the starting XI" case) - previously completely silent
with zero trace. Wrapped `assemble.py`'s `get_locked_squad(conn)` call in a try/except that logs
and degrades to the honest "no squad locked" empty state rather than failing the whole regen, for
any exception not already covered by the fixes above.

**Honest status**: the NULL-squad_slot crash is a real, fixed bug, covered by a new regression
test. Whether it was *the* specific historical cause of the user's "sometimes shows no squad"
report is unconfirmed - it could not be reproduced against the current live DB. The new logging
means the next real occurrence will leave a diagnostic trail instead of silence.

## Source research: is there a better free source than what this project already uses?

Direct WebSearch investigation (not assumed): **Understat remains the best free source of
shot-level xG data available** - confirmed by multiple independent sources ("one of the last free
sources of xG data for European football"; FBref lost its Opta license with nothing free
replacing it). This project already uses Understat for exactly this purpose
(`ingestion/understat_source.py`, real shot-level xG/xA backfill). No free clean-sheet-probability
*data feed* exists anywhere - every real tool (this project, GoalIQ, fpl.page via elevenify/
Spreadex) *derives* clean sheets from its own strength model; there's no third-party number to
switch to. **Conclusion: the user's instinct that the numbers were wrong was correct, but the
fix was a real calibration bug in this project's own model (Bug 1 above), not a wrong data
source** - this project is already using the same best-available free xG source the wider
industry uses.

## Testing

2 new regression tests: `test_ridge_shrinks_a_one_match_shock_result_toward_average`
(`test_team_strength_dc.py` - proves the fix works AND that an unregularized fit really would
have hit the bug, using the same real match shape as Hull's actual GW1 result) and
`test_null_squad_slot_defaults_to_bench_instead_of_crashing`
(`test_optimization_locked_squad.py`). Full suite: 1019/1019.
