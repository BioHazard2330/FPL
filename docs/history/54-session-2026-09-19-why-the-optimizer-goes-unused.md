# Session 2026-09-19 (continuation) — why the optimizer goes unused, measured, and fixed

User instruction, verbatim: *"measure what the optimizer suggested, what i
did over the past 5 gameweeks and then youll get the answer to why i barely
use this for my decisions."*

That was the right instruction, and it should have been the first thing done
rather than the last. THE RECEIPTS as shipped earlier the same day compared
the optimizer against its own rejected runner-up and reported it winning
(+22.0, 5–1). Both sides of that comparison were hypothetical. Measured
against what the user actually did, the optimizer was behind.

## The measurement

`models/counterfactual_ledger.py`. YOURS is the real score, validated
against `my_team_gw_summary.points` (FPL's own recorded total) for GW1–5
exactly, including a triple captain at x3 and a free hit. OPTIMIZER is the
previous gameweek's squad with the transfer it recommended at that deadline.
ROLL is that squad untouched.

| GW | yours | optimizer | roll | note |
|---|---|---|---|---|
| 2 | 100 | 102 | 99 | |
| 3 | 56 | **59** | **59** | its transfer scored exactly what rolling did |
| 4 | 82 | — | 61 | it recommended selling a player already free-hit out |
| 5 | 4 | — | 6 | no recommendation logged at all |

Over the three comparable gameweeks: **yours 238, optimizer 222, doing
nothing 219.** Zero recommendations followed. Not once did it say roll.

Two things went wrong in my own first cut of this and are recorded because
both are the same class of error the screen exists to catch: `your_total`
summed four gameweeks against the optimizer's three (a whole gameweek of
flattery, the wrong way), and the first chart drew the three absolute
scores as zero-anchored bars — 100/102/99 render at 98%/100%/97% of the
track, visually identical, while the entire question is the three-point
difference. Totals now span identical gameweeks on every side, and the chart
draws each choice minus the roll baseline on a zero-centred axis, so a
recommendation worth nothing sits exactly on the zero line.

## Why it never said roll — three defects

**The materiality bar was an order of magnitude below the model's own
error.** `decision_analysis.py` used a hardcoded 1.0 xP over three
gameweeks. Measured from 54 settled predictions (after the `actual_minutes`
repair): MAE 2.79 per player per gameweek, error stdev 3.89. A swap is a
difference of two projections over three gameweeks — noise ≈ 9.5 points.
`models/materiality.py` now derives the bar from recorded error (half the
swap-noise estimate, floored at 2.0, conservative 4.0 fallback below n=30).
Today: 4.76 over 3 GW, 6.15 over 5.

**Transfers were valued as if bench players score.** `evaluate_transfer`
computes `ev_in − ev_out` with no XI awareness. It valued selling squad slot
15 — the deepest bench player, multiplier 0 — at +8.73, in two consecutive
gameweeks. `_squad_gw_ev` in the same file had been XI-aware since
2026-09-02; the function feeding the actual recommendation was never fixed.
The shortlist is now rescored by the change in the squad's XI-aware EV.
Same real swap: raw +8.73, XI-aware +2.58, realised 0. With the measured
bar, that gameweek now resolves to ROLL.

**ROLL was never a real outcome of the strategic selection.**
`build_authoritative_decision` walks ranked transfer paths; doing nothing
sat off to the side as a baseline number and could never win. A transfer
inside noise was reported as "REVIEW: transfer X → Y". It now resolves to
ROLL when the strongest transfer's edge over roll is below the measured bar
(scaled to the horizon), unless a candidate earned a ROBUST class.

## Getting ROLL onto the screen — three more places that assumed a transfer

- **Hysteresis could never accept ROLL.** It flips on persistence or an EV
  advantage; ROLL is resolved precisely when the transfer leads on paper, so
  its total is always lower. A noisy transfer could displace a ROLL
  immediately while a ROLL could only displace a transfer by waiting. ROLL is
  now accepted immediately — it changes nothing about the squad, so there is
  no churn to guard against. The bar still applies one way.
- **The action squad and checkpoint fell back to a transfer path.** Both
  searched the beam's paths for one starting "ROLL", found none, and used
  `paths[0]`. COMMAND showed a ROLL hero over "THE PALMER → MBEUMO SQUAD".
- **Which "roll" matters.** Never-transfer-for-five-gameweeks scores 258.5;
  roll-this-week-then-keep-planning scores 277.8. The decision is the
  second. Against it the best transfer leads by 3.1, inside the 6.15 band.
  My first attempt used the never-transfer line and made rolling look 25
  points worse than the actual choice.

Live on COMMAND at 1440: **ROLL** over the real locked squad; ROLL 277.8
vs Konsa → Ajayi 280.9, −3.1 over 5 GW, drawn inside the ±6.2 noise band;
and a track-record strip under the verdict reading 238 yours / 222 its /
−16 over 3 GW.

## Also this session

- `actual_minutes` in `prediction_outcomes` was FPL's season-cumulative
  total recorded as a per-gameweek outcome (41 of 60 rows above 90). Fixed
  to the per-event live endpoint; 51 minutes and 9 points values repaired.
- Wildcard/bench boost/triple captain modelled inside the MILP. Two bugs
  found by checking: a wildcard banked free transfers it hadn't earned, and
  CBC reports "Optimal" when it stops on the time limit — caught because
  adding a constraint raised the reported optimum, which is impossible.
- Free hit deliberately not modelled (the squad reverts; continuity needs a
  parallel variable set).

## Open

- **The ledger has n=3.** Every number above is real and the direction is
  unambiguous, but three gameweeks is three gameweeks.
- **The `why` line under a ROLL hero** still reads the generic
  robustness tag ("FRAGILE — the margin carries this pick"), which describes
  the rejected transfer, not the roll. Cosmetic; the graphic beside it
  carries the real reason.
- **Free hit in the MILP**, **purchase price** (both planners still treat
  sell price as current price), and **the MILP is not in the live decision
  path** — CLI and cross-check only.
- One `test_sse_server` timing test failed once under a 21-minute full-suite
  run and passed 3/3 in isolation. Untouched.
