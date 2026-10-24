# Session 2026-10-25 — what the match-day sheets say, injured players by match, livelier charts

User, verbatim: *"For example rn, calafiori was benched during his game, joao pedro is not in the squad itself etc etc, so the dashboard and optimizer should scour for what manager reveals and actual true sources say and figure things out right, that's also a part of the football im talking about here. you could also spice up the prexisting template for graphs that exist rn."*

## What was wrong (both examples were real bugs)

- **A substitute read as a confirmed starter.** `lineup_state._confirmed_lineup_states` set "starting" from `EXISTS(player_match_state row)`. FotMob stores the bench too, so Calafiori (on the bench at Arsenal 2-0 Everton, on at 68') showed as Confirmed on My Team, and the `lineup_confirmed` alert said "confirmed starting".
- **A player the official sheet leaves out kept a stale starting row.** `sync_match` upserted rows and never deleted any: the predicted lineup had stored Joao Pedro as a starter, and the official Chelsea sheet lists him in neither the eleven nor the substitutes. The row stayed `started=1`.
- **Nothing in the optimizer reacted to either.** A flagged-injured player was zero minutes in every gameweek of the window whatever the news said (Saka, back "early December", and Bergvall, "expected back 31 Oct", both nine zeros), so the plan sold short injuries and priced returners at nothing.

## What now happens

- `sync_match` deletes any row the current FotMob lineup does not list, stores FotMob's `unavailable` list per match (`match_unavailable`: injury type, suspension, return phrase) and the head coach and formation (`match_coach`), migration 0052.
- `models/matchday_status.py::squad_matchday_status` reads STARTING / BENCH (minute he came on) / NOT_IN_SQUAD (with FotMob's reason) per player from his own team's rows, once the lineup is official. `lineup_state` gains `CONFIRMED_NOT_IN_SQUAD`; that state zeroes the fixture's minutes. Lineup-confirmed alerts cover the plan's targets as well as the squad and re-fire when a sheet corrects a status; 13 stored events that contradicted the stored sheets were corrected.
- `models/return_forecast.py`: an injured or suspended player is scaled by the chance he is available at each kickoff, from FPL's stated date, else FotMob's phrase, else the Kaplan-Meier survival of this database's own injury spells (60 finished, 48 open). Constants for the stated-date cases (0.8 after, 0.05 before) are assumptions: there is no history of news text to fit them against, so `match_unavailable` is stored from now on.
- `models/sheet_study.py` (`fpl sheet-study`): regulars on the bench last match reached 60+ minutes 43% (used) and 32% (unused) of the time next match against a model 57%; those left out while not flagged 36% (11 cases); starters 81% against 76%. The next match's chance of 60+ minutes is capped at 0.8x (the gap shrunk toward no effect) after a bench seat or omission, never stacked on the start-percentage discount (the lower is kept).
- `/api/squadnews` and the Squad news panel under the decision sheet on Command: one line per player with something to say, each with its source (Team sheet, FPL, FotMob, Return forecast, an outlet's headline as published). Nothing is generated; no statement is attributed to a manager who did not make it.
- The week plan's `calibration_id` includes `PROJECTION_REVISION`, so the plan rebuilt. Its transfers did not change (Gibbs-White -> Rudoni, +2.3); GW10 changes inside the road ahead moved.

## Charts

`lib/chartTheme.ts` rewritten: one-hue fade under lines (`areaFade`, `reversedAxis` for rank), rounded bars with a thinning fill (`barFill`), monotone curves and round caps, dashed horizontal grid, no axis border, dashed crosshair, tooltips in the app's own panel (index.css), `lastPoint()` marking and labelling the end of a series, `formatRank` (1.18m). Applied to the live points/rank, season rank/cumulative points, captain bars, the match xG race, price history and the xG bubbles; `EdgeDensity` became a smooth fade curve with the left of the zero rule in red and the share each side written on the rule. DESIGN.md section 8 revised (the flat-fill rule is gone).

## Assumptions to flag

- The 0.8 sheet cap rests on 92 bench cases from one season; the sample for "left out, not flagged" is 11. `fpl sheet-study` is the place to re-check as sheets accumulate.
- The return-date probabilities (80% / 60% / 5%) are not fitted. The undated case is the only one backed by this database's own spell durations.
- A doubtful (yellow-flag) player keeps the flat discount; only injured, suspended and unavailable players are forecast by match.
- 4 pending match analyses (Ipswich-Forest, Villa-City, Coventry-Fulham, Arsenal-Everton) were filed from the analyst's own drafts.
