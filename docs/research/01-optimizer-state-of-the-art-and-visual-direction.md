# Optimizer state of the art, and where the visual layer goes next

Research pass, 2026-09-19. Two questions, asked directly: what would make
this project's optimizer genuinely state of the art, and what would make the
dashboard look outstanding rather than merely tidy.

Findings are separated into **measured** (something was run and produced a
number), **grounded** (traceable to a source or to this codebase), and
**proposed** (a design not yet built). That split matters more than usual
here, because both questions invite answers that sound authoritative and
aren't.

---

## Part 1 — The optimizer

### What the field actually does

The published formulation for FPL squad and transfer selection is a
**mixed-integer linear program over a rolling multi-week horizon**
(Bhattacharya et al., *A data-driven framework for team selection in Fantasy
Premier League*, arXiv:2505.02170). It chooses the starting eleven, bench and
captain under budget, formation and club-quota constraints, and extends to
chips, multi-week rolling-horizon transfer planning, and week-by-week dynamic
captaincy. The stronger public solvers use the same shape.

That paper's other finding is worth separating from the optimisation itself:
its best out-of-sample configuration came from **ARIMA point forecasts with a
constrained budget and a rolling window**, benchmarked against simple and
recency-weighted averages, exponential smoothing and Monte Carlo. The
optimiser is only ever as good as the per-player projection it maximises —
which this project already understands (`models/expected_points.py` is by far
its most developed component).

### What this project had

A genuine split:

| Problem | Method | Guarantee |
|---|---|---|
| Single-GW squad build | MILP, PuLP + CBC (`optimization/squad.py`) | exact |
| Multi-GW transfer plan | **beam search** (`optimization/transfers.py`) | **none** |

`search_transfer_sequences` keeps the `beam_width` best-looking partial paths
at each step and discards the rest. Production runs width 5, with a
continuation search at width 3. A beam search carries no optimality
guarantee: a sequence whose first move looks mediocre but whose third move is
decisive is pruned before that third move is ever enumerated.

### What was built and measured

`optimization/milp_planner.py` — the whole horizon as one MILP. Same
per-player, per-gameweek primitive the beam already uses
(`expected_points_window(..., from_event=t)`), so any difference between the
two is a difference in *search*, never in *valuation*.

**Measured, 2026-09-19, real production squad, GW6–GW10, chips disabled on
both planners, identical bench weight:**

| | net EV (5 GW) | wall time | optimality |
|---|---|---|---|
| Beam search (production settings) | 276.42 | 30.0s | none |
| **MILP** | **291.29** | **7.9s** | **proven optimal** |

**+14.87 points over five gameweeks, ~3x faster.** The MILP plan was then
independently re-verified against the real FPL rulebook — 15 players, exact
position quotas, ≤3 per club, every gameweek — from the returned solution
rather than from the solver's own constraint set.

One honest caveat on that comparison: the two planners build their candidate
pools differently, so part of the 14.87 is pool composition rather than
search quality alone. What is *not* caveated is that the MILP plan scores
higher **on the project's own value function** and is verifiably legal, which
is the claim that matters for acting on it.

### Deliberately not modelled in v1

Stated here so nobody later assumes otherwise:

- **Chips.** Wildcard and free hit restructure transfer accounting; bench
  boost and triple captain are products of two binaries. Each is
  linearisable, each is a place to hide a silent modelling bug. v1 solves the
  transfer problem only, and `MilpPlanResult.chips_modelled` says so.
- **Selling-price rules.** FPL sells at purchase price plus half the
  rounded-down profit. This project stores no purchase price in any migration
  — so the beam search already treats sell price as current price, and the
  MILP makes the identical approximation on purpose.
- **Price drift and anything stochastic.** Expected points only.

### Proposed next, in value order

1. **Model the chips inside the MILP.** Triple captain and bench boost need
   one auxiliary binary each (`z ≤ a`, `z ≤ b`, `z ≥ a + b − 1`). Wildcard is
   a per-gameweek waiver of the hit term. This turns chip timing from a
   separate DP cross-check into part of the same proven-optimal answer.
2. **Track purchase price.** A migration plus a field on `my_team_picks`
   removes the single largest approximation in *both* planners. It is cheap
   and it is currently the most load-bearing thing the model gets wrong about
   money.
3. **Robust / chance-constrained variant.** The paper's robust MILP maximises
   a worst-case objective over a projection-uncertainty set. This project
   already has the uncertainty (`models/scenario_sampling.py`,
   `projection_confidence.py`) and currently throws it away at the planning
   step by optimising the median only.
4. **Keep both planners and report the gap.** The MILP's objective is a real
   upper bound on what the beam can reach, so the difference is a standing
   measurement of heuristic loss — the same posture
   `models/external_benchmark.py` already takes toward Solio. Replacing the
   beam outright should follow that measurement, not precede it.

---

## Part 2 — The visual layer

### The one principle worth keeping

From the sports-dashboard design literature: the strongest dashboards **show
less, not more**, and are judged by how quickly a real operator can read one
and act during a live event. The pattern that recurs is a live spatial view
paired with an event timeline and role-specific alerts, answering three
questions at once — *where is it happening, is it getting worse, who acts
next*.

This project's `DESIGN.md` already encodes a stricter version of that, and
its honesty rules explicitly outrank aesthetics. Nothing below should be read
as a reason to loosen them.

### Where this dashboard actually stands

It is already past the generic-dark-SaaS stage: self-hosted Oswald + IBM Plex
Sans, a flat broadcast palette, real pitch geometry, real ApexCharts, honest
freshness labels. The gaps are not styling gaps.

### Proposed, in value order

Each of these adds **domain content**, which is the bar this project has set
for itself — layout alone has repeatedly been judged not to count.

1. **A planner-comparison panel.** Now that two independent planners exist,
   show the gap: MILP optimum vs beam result vs hold-and-roll, as three bars
   on one axis with the point difference called out. This is the rarest thing
   a dashboard can show — *how much the recommendation could still be wrong*
   — and it is now a real measured number rather than a vibe.
2. **A transfer-path Sankey.** The 8-GW plan is currently a list of rows.
   Its actual shape is flow: money and squad slots moving between players
   over time. A Sankey (or a slim alluvial band) makes "this whole plan hinges
   on one GW7 move" visible in a way an ordered list structurally cannot.
3. **Shot maps on the player cards, not just the match view.** The
   `match_shots` table now carries real per-shot `x`/`y`/`xg`/`situation` for
   every match, and this session's analyses proved how much signal sits in it
   (a team taking 10 of 16 shots from dead balls is invisible in any
   aggregate). A 60×40px sparkline-scale shot map per player is cheap and
   carries information no number on the card does.
4. **An xG-vs-actual divergence strip.** The project stores
   `prediction_outcomes` and never charts the residual. A small diverging
   band per squad player — where the model has been wrong, and in which
   direction — is the most honest possible thing to show a user, and it is
   already sitting in the database.
5. **Density pass on COMMAND.** The screen currently answers "what should I
   do" well and "what is happening right now" less well during a live
   gameweek. The live payload fix landed this session means `actual_points`
   is finally populated; the layout has not yet been revisited around the
   fact that it now has live numbers to show.

### What to resist

- Gradients, glows and depth for their own sake — `DESIGN.md` bans them, and
  the one deliberate exception (body grain, per-screen atmosphere washes) is
  already doing that job.
- Any chart that restates a number already on screen. The session that wrote
  this document also found production analysis text where the `inferred`
  field merely paraphrased the `observed` numbers; the chart equivalent is
  the same failure.
- Mobile layout work. A standing, repeated instruction: desktop-first,
  verified at 1440 and 1080.

---

## Sources

- Bhattacharya et al., *A data-driven framework for team selection in Fantasy
  Premier League* — https://arxiv.org/abs/2505.02170
- Fuselab Creative, *Sports analytics dashboard design* —
  https://fuselabcreative.com/stadium-analytics-dashboard-design/
- Sportmonks, *From Data to Dashboard: Visualising Football Stats* —
  https://www.sportmonks.com/blogs/from-data-to-dashboard-visualising-football-stats-for-better-insights/
