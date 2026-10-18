# Session 2026-10-16 (second part) — the studio: news desk, match previews, plan alternatives

User, verbatim: *"upgrade every single thing to the maximum ... my own insane fpl and football studio but insanely well developed, creative, impressive in accuracy and precision."*

## What was built

**The desk (`/desk`, `/api/desk`).** `ingestion/media_source.py` pulls four YouTube channels (Premier League, Sky Sports PL, FPL Harry, Let's Talk FPL) through their public Atom feeds and r/FantasyPL through its Atom feed (the JSON endpoint answers 403 to a script). Channel ids were resolved from each channel's own page and each feed fetched before it was listed - two ids written from memory belonged to other channels. News items now carry an image (`news_items.image_url`, migration 0046) and The Guardian's Premier League RSS joined the wire. `monitoring/api/desk_payload.py` reads stored rows only (about 0.1s): an item is *yours* if it names a squad player, a *plan target* if it names a player the stored week plan buys or declined, otherwise newest first; duplicate headlines across feeds are shown once. Also: official FPL injury notes, a price board (FPL's own changes plus the existing transfer-momentum lean, labelled uncalibrated), a video studio with click-to-load `youtube-nocookie` embeds (nothing loads from YouTube until clicked), community posts. COMMAND carries a small "from the desk" strip when a story touches the squad or the plan.

**Match previews (`/previews`, `/api/previews`).** Per next-gameweek fixture: the same odds-blended Dixon-Coles goals every projection uses, a Poisson score grid (0-8 goals) with the DC low-score correction at the fitted rho, win/draw/loss, clean sheets, most likely score, the de-vigged bookmaker 1X2 beside it (never blended), last five results, official FDR, the three highest-projected players per side with yours marked, flagged absentees. Built once per ten minutes in a refresh thread (one DC fit, about 160 player projections, 5-7s).

**Plan alternatives and captain ladder (`optimization/week_plan.py`).** For each recommended move the best two other ways to spend the same transfer if that player is unavailable: the planner re-solved with him removed from the pool, every other move forced, priced against the best plan that makes the other moves and never buys him (without that last clause the base plan still bought him next week and every alternative looked negative). An alternative worth nothing is not listed. The armband ladder is the top three projections per gameweek for the post-move squad. Adds about 15s to a plan build (45-50s total).

## Defects found on the way
- A first-name player matched another person's surname: "Enzo Maresca" tagged Chelsea's Enzo. `news_source._is_someone_else` now rejects a first-name or nickname web_name followed by a capitalised surname the player does not have. 83 recent articles/videos were relinked.
- The desk's price lean called `classify_price_change` for every player (1.9s); one SQL join does the same arithmetic in 0.1s.
- Vite's Tailwind scan does not see a screen file created after the dev server started: new classes silently do nothing until it is restarted.

## Assumptions and limits to keep disclosing
- Previews: probabilities assume the DC rho from the latest fit and a 0-8 goal grid; the market column is a cross-check on goals the blend already uses where odds exist, not an independent model. Key players are the top three by projection among each club's nine most regular starters.
- Alternatives are priced by the same horizon xP as the moves; their gains are small because the chosen target was the best option, which is the point.
- Ladder is ranked by projection alone; the armband rule can prefer a close second this week.
- Reddit posts carry no vote counts (feed has none), so none are shown.
- Guardian items have no pictures in the feed; they get a typographic tile.

## Later the same day: the odds fix, headshots, compare, stories, checklist

- **Market-implied goals were biased and the blend weight was wrong** (see the `CLAUDE.md` blockers entry for the numbers). Found by noticing Man City at 3.15 expected goals against a market that gave them 74%: the old split gave a heavy favourite 88% of the goals. Fixed with a joint Poisson fit, then the blend weight was measured instead of assumed. City's GW7 clean-sheet chance fell from 55% to 41%. The GW7 plan changed in one move (Gvardiol to Van Hecke instead of Guehi) and the gains of the other two fell by about a point and a quarter.
- **Headshots** (official PL CDN, keyed by player code) on transfers, the captain battle, injury notes, previews and the player file; shirts stay on the formation tiles.
- **Compare** (`/compare`), **projection band** on the player file, **stories** (articles, videos, posts) on player and club files, **deadline checklist** on COMMAND.
- Name matching: a name preceded by another player's first name ("Scott Allan") or a bare surname without the club ("Fernandez ... Rangers") no longer links to a squad player.
- **More channels**: Fantasy Football Hub, FPL Focal, FPL Raptor and FPL Mate joined the video feeds (found by resolving each channel page's canonical id and checking the feed's newest entry; Fantasy Football Scout's feed holds only 2010 uploads, FPL General's last upload was July, the official FPL channel's feed is empty, so those three were left out). The desk shelf caps each channel at five so the busiest cannot fill it, with channel tabs.
- **Run of fixtures** (on PREVIEWS): six gameweeks x twenty clubs from the team model, attack (expected goals) or defence (clean-sheet chance), coloured by rank across all cells rather than by the official difficulty number; a dot marks fixtures where stored odds fed the goals.
- **MY TEAM** uses headshots for the top-projected player and the player sheet.
- Checked and left alone: the clean-sheet probability exp(-opponent goals) is calibrated within a few points on 3,840 team-matches (0.262 predicted against 0.250 actual); it runs 9 points high above 50% (106 matches, about 2 standard errors), not enough to justify a correction yet.

## Evening: free transfers, team football in the optimizer, auto-update timing

- **Free transfers read 5, the app said 3.** The replay credited the gameweeks after a free hit and a wildcard with their +1. Fixed (the window after a chip gets no +1; saved transfers survive), confirmed against this manager's real history, which now gives 3. The plan went from three moves to two because three free transfers cannot fund a third move above the bar.
- **Team strength now reads chances created (xG) as well as goals.** Backtested before adoption (see CLAUDE.md). Red-card down-weighting tested and rejected.
- **Every planned player now carries his club's context**: attack and defence rank over six gameweeks and the first fixture's expected goals scored and conceded (`models/fixture_outlook.py`, stored in the plan as `team_outlook`), shown on the transfer cards. The same module feeds the run-of-fixtures heatmap.
- **Press reports** about your players or targets (injury words in a headline) now appear in the deadline checklist.
- **Odds and plan refresh tighten near the deadline** (see CLAUDE.md).

## Night: the three ideas (field, audit, live forecast)

- **The Field** (`/field`): the plan scored against the average manager over 4,000 correlated simulated gameweeks. For GW7 the plan's edge is +14.5 model points over everyone (91% of simulations ahead), of which setting the best eleven is +2.3 and the two transfers +3.0; Haaland is the best armband by edge on both fields. It also lists the players the field owns that you do not (De Cuyper, Palmer once sold, Raya) and where your edge comes from. Needed `fpl sync-eo --event 6` (750 managers, about 25 minutes of polite requests) because the sample table was empty; `run-scheduled` now starts it in the background for each gameweek after its deadline.
- **The Audit** (`/audit`): FPL's own per-gameweek xG, xA and xGC (new `player_gw_stats`, one request per gameweek) set against the goals, assists, clean sheets and goals-against that resulted. Your fifteen are +85 points on their chances; Gvardiol, João Pedro, Groß, Verbruggen and Palmer are the riders, and Chelsea's 5-1 at Bournemouth came from 1.09 xG (it goes the other way 74% of the time). Match rebuilds from the shots: cumulative xG against the clock and the deserved result.
- **Where GW7 ends** (LIVE screen): the rest of the gameweek simulated from each match's minute and score; your final and the average manager's over the same endings. Not testable against a real live gameweek yet (GW7 has not kicked off): the live path is unit-tested and was exercised on a synthetic mid-gameweek state built from GW6's finished matches, and the pre-gameweek path was checked against GW6 (forecast 63, interval 46-82, actual 73).
- **Measured, not fixed:** the projections run cool by about 1.1 points per player per gameweek (see CLAUDE.md). The live forecast adds it back; the projections themselves are unchanged.
- Luck tags on every transfer card (`+15 lucky` on Cherki, `+12 lucky` on Palmer) and a one-line field strip on COMMAND.

## 2026-10-18: live was off while GW7 was being played

- Report: live poll, live server and sync not running with matches live. Cause: the power-gating window (2026-10-13) was the 24h before a deadline until 3h after it, so it closed at 14:00 BST on Saturday while the gameweek ran to Monday night; `live_matchday_polling: false` made the live poll stop with it.
- Fix: `scheduler/power_window.py::compute_window` merges the deadline run-up with the matches (each fixture from 60 minutes before kickoff to 3 hours after; fixtures within 36 hours of each other joined; a fixture rescheduled weeks away does not join). `live_matchday_polling` removed; new keys `pre_kickoff_minutes`, `post_match_hours`, `matchday_bridge_hours`. GW7's window now runs to Mon 22:00 UTC. Tests in `tests/test_power_window.py`.

## 2026-10-18: the cool bias found, `calibrated-v3`

- Laid the model's per-component GW8 projection for every available player against FPL's actual component totals for GW1-6. Goalkeeper saves were absent from the model (11 points a gameweek league-wide); assists were low by position (forwards 6.6 predicted against 11.5 actual). Both fixed, plus save and defensive-contribution points added to the simulation. Details in CLAUDE.md.
- The live forecast now logs itself every ten minutes (`live_forecast_log`, migration 0048) and scores itself against the final points when the gameweek settles (`forecast_scorecard`). The first GW7 forecast was logged live at 69.6 (61 to 80) with 46 on the board.
- Five pending match analyses written (Everton-Chelsea, Fulham-Hull, Man City-Ipswich, Brentford-Liverpool, Newcastle-Villa).
- Visual rebuild begun: palette, type scale, framed screens, softer corners.
- Matchup Lab on previews, armband table on the audit, `/api/whatif` and the "Try your own moves" panel on PLAN (sandbox +8.9 for Palmer to Saka against the week plan's +2.5: the sandbox compares with never making the move, the plan with making it a week later).
- Speed: DC fit vectorised (5-15s to 0.01s), process-wide fit cache, opt-in projection memo, legacy HTML dashboard off the unattended cycles.
- Previews now list the unstarted fixtures of the current and next gameweek (they had listed all of GW7 including finished matches).
- Early-withdrawal detector (`change_detection.detect_early_withdrawals`, run from `sync_match`): a starter taken off inside the first hour raises a `change_events` row for any squad player or any player at 2%+ ownership, HIGH for the squad or by the 45th minute, hours before FPL's own status moves. Alerts and the toast now carry the player's name and the event's own sentence instead of `entity#id: old -> new`.
- The prediction ledger now covers about 470 players a gameweek (`calibration.ledger_player_ids`) and Receipts reads calibration by predicted tier for the current model version.
