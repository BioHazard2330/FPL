# Session 2026-09-19 (continuation) — THE RECEIPTS, chips in the MILP, and a poisoned accuracy record

Direct user brief: bigger aesthetic work, a stronger optimizer, and one
sentence that reframed both — **"i still dont use the optimizer to date for
my decisions."**

That is not a modelling complaint, and treating it as one would have been
the wrong response. An engine that never scores itself where the user
actually looks does not get trusted, and should not be.

## The accuracy record was poisoned

Before building anything on top of the decision ledger, it was worth
checking whether the ledger was true. It was not, in one specific and
damaging way.

`record_outcomes_for_finished_event` read `actual_points` and
`actual_minutes` from `player_stats_snapshot`. Its own docstring asserted
that both "only correctly reflect THIS event". That is true of
`event_points` and **false of `minutes`**, which is FPL's season-cumulative
total.

The damage was measurable rather than theoretical:

- 41 of 60 stored rows carried `actual_minutes` above 90 — impossible for a
  single gameweek — topping out at 360
- league-wide, `player_stats_snapshot.minutes` reached 3420 (a full season)
  five gameweeks into the season
- Calafiori's GW2 outcome was recorded as 170 minutes

Every minutes-model error ever computed against that column was garbage,
silently, while the points side looked fine and therefore raised no alarm.

Fixed by reading FPL's own per-event live endpoint, whose `stats.minutes`
is genuinely scoped to one gameweek (verified: 659 players, max 90, zero
above). The snapshot remains the fallback for points only; minutes are
recorded NULL rather than wrong, because every consumer of that column is
measuring model error and a cumulative value reads as a catastrophic miss
rather than as absent data.

Historical rows repaired from the same endpoint: **51 minutes values and 9
points values corrected**. The points corruption was the bigger surprise —
it happens when an outcome is recorded late enough that the next gameweek
has already overwritten the single-row-per-player snapshot.

Two bugs of mine were caught by the test suite during this, both worth
recording because both were the same class of mistake:

- the first version made the function proceed where it previously skipped,
  exposing a latent NULL-season path
- and it put a live network call into a unit-tested code path

The fetch is now lazy and happens only once a player genuinely has an
outcome to write, so a squad with nothing to record neither pays for nor
depends on the network. Three tests pin this: live-beats-snapshot,
NULL-rather-than-wrong, and no-network-when-nothing-to-record.

## Chips inside the MILP

Wildcard, bench boost and triple captain are now modelled directly. Bench
boost and triple captain are standard AND-linearisations against the
existing captain/bench variables; wildcard waives the gameweek's hit term
with a tight big-M (15, a full rebuild) rather than an arbitrary constant.

**Free hit is deliberately still not modelled**, and that is not laziness:
the squad reverts the following gameweek, so squad continuity stops being a
single chain and needs a parallel variable set plus a restore constraint.
Modelling it as "a wildcard that does not persist" would let the solver keep
a free-hit squad forever. `MilpPlanResult.chips_modelled` now names the
chips a given solve actually considered, so no caller can assume more than
was done.

### Two real bugs found by checking rather than trusting

**Wildcard was banking free transfers it had not earned.** FPL gives exactly
one free transfer the gameweek after a wildcard regardless of what was
saved. The rollover constraint was unbounded during a wildcard week — with
hits already waived, the solver had no reason to spend `fuse`, so it banked
the lot. Confirmed live: a GW6 wildcard making 10 transfers still reported
`ft=5` at GW7. Fixed with an explicit burn constraint; GW7 now reports
`ft=1`.

**CBC reports "Optimal" when it stopped on the time limit.** Caught by an
impossibility: adding the wildcard-burn constraint *raised* the reported
optimum (382.69 → 382.87), which cannot happen — a tighter feasible set
cannot increase a maximum. The earlier run had taken 247s against a 240s
limit and still reported `LpStatus == "Optimal"`. `proven_optimal` was
therefore capable of being false, which is the one thing this module must
never do. A solve that runs to the limit is now reported unproven, and the
guard is demonstrable: a 5s limit returns 369.14 labelled unproven where a
300s limit proves 382.87.

`fpl milp-plan` gained `--chips/--no-chips` and now reads real chip usage,
so it correctly offers only `bboost` this season.

## THE RECEIPTS

A new screen, and the answer to the sentence at the top of this file.

The ledger already existed — `decision_outcomes`, frozen at each deadline
against the best alternative rejected at that moment, settled with real
points once the gameweek finished, never recomputed with hindsight. It
already said something worth knowing: transfer calls 3 for 3 at +4.67 mean
advantage, captain calls 2 of 3, **+22.0 net points across six settled
calls**. The only way to see any of it was `fpl decision-backtest` in a
terminal.

`/api/receipts` + `screens/Receipts/ReceiptsScreen.tsx` put it where the
decisions are made, under the Decision nav group, because it is the evidence
for the recommendation rather than an operations readout.

The governing design rule: **a loss must be exactly as legible as a win.**
No collapsing losses behind a toggle, no softer colour for bad rows, no
rounding a negative toward zero. The GW2 captain call sits at the top of the
list at -20.0 in red, and the dip is visible in the cumulative line. A
screen that flatters the model stops being evidence.

Three honesty rules are enforced in the payload rather than left to the UI:
`n` travels with every rate; unsettled gameweeks are absent rather than
zero; and `sample_warning` is populated, not inferred — 83.3% off six calls
is not a win rate and the screen says so in gold.

## Open

- **Free hit in the MILP** (see above for why it is a different problem).
- **No purchase price is stored**, so both planners still treat sell price
  as current price.
- **The ledger only compares the optimizer against its own rejected
  runner-up**, never against what the user actually did. "Would following it
  have beaten me" needs the real transfer history joined in, and is the
  natural next step for this screen.
- **The MILP is still not wired into the live decision path** — CLI and
  cross-check only.
