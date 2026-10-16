# Session 2026-10-16 — the week plan: why the optimizer said so little, and what replaced it

User, verbatim: *"look at my team and look at the optimizer result and see how
bad it is. and figure out why and how to fix it ... visual enhancements,
creativity, not random numbers and random statistics and ai garbage language
spewed everywhere."*

The squad (GW6 picks, five free transfers, £0.3m, bench boost the only chip
left) and the standing recommendation were laid side by side the evening before
the GW7 deadline.

## What was wrong, in order of how much it cost

**1. The planner could only make one transfer.** `search_transfer_sequences`
takes at most one transfer or chip per gameweek. The squad held **five** free
transfers (the cap, so rolling also throws one away). The answer on screen was
a single swap worth +0.3 points "inside the ±7.5 noise band", REVIEW. The exact
MILP, run on the same squad, found 13.6 more points over five gameweeks than
the beam (transfer-only, same pool), 29.2 on the dashboard's own cross-check
panel. The PLAN screen was already displaying that gap and nothing acted on it.

**2. The same screen disagreed with itself.** COMMAND said Gibbs-White → Cherki
was inside the noise band; PLAN said +43.1 over rolling for a 7-transfer plan;
`fpl transfer-analysis` said Palmer → Saka. Three surfaces, three answers. The
+43.1 compared against *never transferring again*, which nobody does.

**3. A projection ignored a rotation call.** `models/expected_minutes.py` only
ever *raised* minutes from the predicted-start feed, and the xP actually used
(`minutes_bucket_probabilities`) never read it at all. Gvardiol: predicted
start 24%, projected 90 minutes and 5.52 xP, with the HIGH change event sitting
in `change_events`. Now 2.96. Applied per fixture, in full to the next
gameweek and halved for each after (`_START_PERCENT_DECAY_PER_EVENT`), because
a one-week rotation call says nothing about a five-week horizon. The feed's
ceiling is 90 (125 of 360 players sit there), so 90 means certain, not risk.

**4. The lineup was nobody's job.** The squad on screen was last week's eleven.
Davis (1.7 xP) started over Bogle (4.6); Calvert-Lewin sat on the bench; the
vice-captain was Palmer. Setting the same fifteen properly is worth +3.7 xP in
GW7 and costs nothing. No surface said so.

**5. Smaller, all real:**
- `get_used_chips` counted "ever played" as spent, so from GW20 (when every chip
  resets) no chip would have been offered. Now read from `chip_windows`.
- The MILP paired simultaneous transfers by player id, so a plan could read
  "Kinsky → Rudoni" (a goalkeeper sold for a midfielder). Now by position.
- The LIVE screen showed RECOMPUTING for twelve hours: a status baked into a
  snapshot file that had gone stale.
- ADVANCED led with a 39-day-old audit of players long since sold, chip values
  of "-34.7" and "timing edge +459.8", odds quotes 41-54 days old, and a
  standing DEGRADED because the dashboard server is *meant* to be down outside
  the pre-deadline window.
- The 4 refresh threads in `live/sse_server.py` raced into a circular import on
  start (`_DeadlockError`, flagged in PROJECT_STATE since 2026-09-08). Eager
  import on the starting thread; the race no longer exists.
- `/api/weekplan` first took 6s: its staleness check called `get_locked_squad`,
  which projects all fifteen players and refits the team-strength model on a
  fresh connection. Plain reads now; 4ms.

## What replaced it

`optimization/week_plan.py` — the decision of record. It asks what a manager
with five free transfers is actually deciding: how many to use, and on whom.

1. Price rolling this gameweek and re-planning optimally from the next.
2. Add the single best first-gameweek transfer (MILP, `max_first_gw_transfers=1`).
   Force it, and add the best second on top. Repeat while a move still adds at
   least `MIN_MOVE_GAIN` = 1.5 points over five gameweeks.

Each move's value is therefore its marginal value against the best plan that
already contains the moves above it; the list is nested, so stopping early
never changes what is above. GW7: Gibbs-White → Cherki **+4.8**, Palmer → Saka
**+2.2**, Gvardiol → Guéhi **+1.7**, then Calvert-Lewin → Barry +0.5 left out.
**+8.6** over five gameweeks against rolling and re-planning next week; three of
five free transfers used, three banked.

It also picks the eleven (the current one is kept wherever a better player at
the same position is ahead by under 0.4 xP: a tool that says "swap Kinsky for
Verbruggen, +0.1" is not credible about the swaps that matter), the armband
(ties inside 0.5 xP go to the player whose points come from goals and assists:
Haaland over Cherki), an eight-gameweek road ahead (each later transfer charged
the same 1.5 bar in the objective, so later weeks are not padded), the chip
outlook (available chips, whether a double gameweek is scheduled, what a bench
boost would add), a stress test per move, and whether the plan fits under the
strictest reading of selling prices.

Stored in the decision journal as `week_plan`; rebuilt inside `run-scheduled`
when missing, stale (`week_plan_staleness`: squad, bank, free transfers,
gameweek, or a HIGH change event for anyone owned or targeted), or 12h old.
~35s, inline.

### Surfaces

- **COMMAND** leads with the moves: shirts, fixture runs, rotation/price/Solio
  tags, the marginal-value chart ("what each extra transfer buys", with the bar
  drawn as a line), the lineup fix, the squad it produces, the captain battle,
  the road ahead. The beam hero is the fallback only when no plan exists.
- **PLAN** opens with the solver's plan; the beam search is demoted to a
  labelled second opinion.
- **MY TEAM** flags that the pitch is last week's lineup and ghosts the planned XI.
- **LIVE** states plan freshness from a live endpoint, not a snapshot field,
  and warns when the snapshot is old.
- **ADVANCED** opens with the plan checked: solver status, each move at full
  and at half projection, the drop that takes it to the bar (interpolated and
  labelled so), Solio beside it, the assumptions. Stale panels removed.
- **RECEIPTS** scores the plan's own eleven, armband and moves from GW7.
- Header **Sync now**: `POST /api/refresh` runs one `fpl run-scheduled`
  (detached, below-normal priority, one at a time, custom header required).

## What is honest about it

- **1.5 points is a judgement, not a fitted value.** The model's measured error
  is 2.8 points per player per gameweek; a +4.8 over five gameweeks is not
  distinguishable from luck on any one result. It is positive expected value,
  and the stress test says how thin: Cherki's move stops clearing the bar if he
  returns 17% less than projected, Saka's at 8%, Guéhi's at 2%.
- Cherki is the linchpin and the model is 2.4 above Solio on him (6.7 vs 4.3).
  Even at Solio's number he beats the 3.2 he replaces. Shown on the card.
- Sell prices are current prices. FPL pays purchase price plus half the rise;
  purchase prices cannot be read reliably (the reconstruction came out £1.3m
  under FPL's own reported team value). `affordability` states the worst case.
- No leakage-free backtest of the plan exists. The model's rank correlation with
  outcomes on 69 settled squad predictions is 0.54. The ledger will score the
  plan from GW7 against what actually happens.
- Chips are outside the decision. Free hit is never modelled.

## Not done

- Selling-price reconstruction (needs the FPL "my team" endpoint, which needs a
  login this project does not hold).
- Backtesting multi-transfer MILP policies against single-swap ones over past
  seasons (`backtesting/season_backtest.py` replays single swaps only).
- Scout and Football screens were surveyed, not reworked.
