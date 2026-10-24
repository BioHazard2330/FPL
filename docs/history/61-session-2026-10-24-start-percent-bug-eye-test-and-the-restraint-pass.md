# Session 2026-10-24 — a start-percentage bug that skewed every projection, the eye test, a live analyst, and the restraint pass

User, verbatim: *"so can you not make some big upgrades for the live part? and also the optimizer smartness? like i see every model including this recommend saka when that guy has looked so fucking bad, something only the human eye can see"*, then: *"theres lots of areas on dashboard where it just looks cluttered and overall design reeks. not professional. not cool. just random jargon in a few areas. fix the optimizer problems as well. i dont want any shitty bugs ... work like a real experienced football ui engineer. but i dont want ai slop. and i dont want aimless data that dont tell me anything."*

## The optimizer bug (the one that mattered)

**The start-percentage feed was being read from the wrong column for at least seven weeks.** `ingestion/lineup_probability_source.py` took the third cell of each row of fantasyfootballpundit.com's lineup tables as "Start %". The site added a "GWn Mins" column ahead of it, so every player's "start percentage" became his minutes in the last gameweek: 0 for anyone who sat out, 24 or 29 for a cameo, 90 for a full match. `expected_minutes` discounts a nailed player's minutes by `start_percent_minutes_factor`, so a fit player who had missed one match was projected at a quarter of his minutes. Evidence: Gibbs-White (7 starts in 8, FPL status available, the site's own text 80%) was stored at 0% and was the plan's first transfer; Gvardiol was stored at 29%, which was his GW7 minutes; twelve `start_percent_change` events were "changes" from 90 to 0 or 24 that were minutes counts.

Fix: the "Start %" column is found by its header, a cell without a "%" sign is not a percentage, and a parse where more than a fifth of the values are off the five-point grid the site quotes is refused (`looks_like_percentages`). Real feed re-synced: Gibbs-White 80, Gvardiol 70, Saka 20 (thigh injury), 100 of 361 at 90. The twelve false events were deleted. The week plan moved from "Gibbs-White -> Rudoni and Gvardiol -> Gabriel, +5.1" to "Gibbs-White -> Rudoni, +2.2" with 'Lean, 58% to pay off'.

Found by setting the page's own text beside the database after "0% to start" looked wrong on a player who had played 90 minutes the day before. The lesson recorded here: a scraped table is checked by header, not by position, and a numeric column is checked for what it can plausibly be.

Forward-looking: `player_start_probability_history` (migration 0051) now keeps every figure that changes (or one a day), and `models/start_calibration.py` / `fpl start-calibration` set each reading against who then started, by band. The feed has never been calibrated because there was never a history; in a few weeks this says whether an 80% reading starts four times in five.

**The "next deadline" counted a deadline already gone.** `live_snapshot._deadline_block` took the earliest unfinished gameweek by deadline, and a gameweek stays unfinished for days after its deadline, so the header countdown ran to a time in the past during every gameweek in play. It now takes the earliest deadline in the future. Test added.

## The eye test and the live part (second wave, committed with this)

- **Form watch** (`models/form_watch.py`): last three matches' xG+xA per 90 against the rest of the season, shots, FotMob ratings, and the evidence table: across every stored season, what a midfielder or forward realised in the next match after a dip of each size against a shrunk full-season baseline (bootstrap interval). Result: ordinary dips realise 0.97-1.05x baseline, the baseline already knew; only a collapse below a quarter of earlier output has carried. So the eye test is shown with its evidence and not wired into the projection.
- **Move confidence** (`models/move_confidence.py`): each move replayed 4,000 times through the scenario engine with a lognormal talent factor (sigma from the player's xG+xA sample); wins, mean/sd, p10/p90. 'Solid' >= 65%, 'Lean' >= 55%, 'Thin' below.
- **My view** (`/api/viewplan`, `plan_with_view`): scale any player's projection 0.5x-1.1x over the horizon and the planner re-solves. An opinion applied to the same solver, labelled as one.
- **Live analyst** (`/api/livestory`, `analyse_live`, `LiveAnalyst`): the match analyst run on a match in play (provisional, nothing stored), including a probable-injury call for a starter taken off early. Measured on the stored stories: every starter taken off in play before minute 36 was injury-linked (7 of 7 when fitted); 36-60 about 6%. `early_withdrawal` events are HIGH only up to minute 35 and quote the count.

## The restraint pass (design)

The complaint was clutter, jargon and decoration, so the pass removed things rather than adding them.

- **One bar, not three.** `ContextHeader` now carries the page title, the live-match count (or "GW8 in progress" when none is on), the countdown to the next deadline, the live scores, freshness and Sync. `MatchdayBar` is gone; `Masthead` renders only a screen's own line of context.
- **Shared vocabulary** (`components/ui/kit.tsx`): `Panel`, `Disclosure`, `Pill`, `Fig`, `chipName`. Sentence-case titles at one size.
- **Command rebuilt** around the decision: `DecisionSheet` (transfers, armband, lineup side by side with free transfers, bank, chips below), `SquadPitch` (fixed row spacing, no wrapping), `MoveCard` (at most four plain-sentence notes per player), the eye test condensed, the armband ladder, a pre-deadline check list, three weeks beyond (indicative), the news. 6,700px became 3,700px. The "matches are live, nothing can be acted on" banner was wrong: transfers for the next gameweek open the moment the deadline passes, so the plan leads whenever a deadline is ahead and a one-line live strip sits above it.
- **Navigation regrouped and renamed** by question: This week (Command, My team, Plan, Live), The league (League, Team styles, Previews, My clubs, Shot map), Players (Market, Compare, Explorer, News), How I am doing (Versus the field, Luck check, Track record), System.
- **Removed:** the ghost watermark words, the angled verdict block, the 3D toys (podium, season helix, trophy shelf, xG mountains, win-probability orb, transfer flip, 3D pitch; `three` dropped from package.json), the MINE/MY SQUAD tags (now a quiet "yours"), the tracked-uppercase monospace label style across ~50 files (codemod: no uppercase, no tracking, minimum 12px), the Football screen's 900-signal board (what changed for your players, kept short), the Advanced screen's pipeline strip and raw source names, the Scout count boards.
- **Folded:** Previews (18 expanded matches, 17,000px) into one-line rows, open only where you own a player; match centre cards into players-first with the detail collapsed; the beam search second opinion, system checks, Solio differences and points revisions into disclosures.
- **Fixed on the way:** "bboost" shown raw as a chip name; "1 shots"; a header countdown to a past deadline; the early-minute live analyst card (now only from minute 15 or three shots).

## Assumptions to flag
- The new move-confidence talent sigma and the form bins are descriptive choices; the bins' realised ratios are measured, the 0.65/0.55 verdict cut-offs are not fitted.
- Start-percentage minutes discounting (`START_PERCENT_TRUST` 0.75) is still uncalibrated; the history table exists so it can be.
- The "beyond this week" columns are re-solved every week and are shown as indicative; each later move had to earn 1.5 points in the joint solve, not individually.
