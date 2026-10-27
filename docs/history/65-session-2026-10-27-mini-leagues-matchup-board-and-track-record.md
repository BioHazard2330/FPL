# Session 2026-10-27 (night): mini-leagues, the fixture matchup board, the plan's record

User: *"i just want the dashboard to look amazing, the site as a whole with tons of features that blow my mind and offer really good insight, along with looking spectacular and connecting me to fpl. also any upgrades to the daemon auto package reader thingy? and the optimizer as a whole."*

## Built

- **Mini-leagues (`/leagues`).** `ingestion/leagues.py` reads `/entry/{id}/` for the entry's classic leagues; private leagues up to 300 managers are tracked (live: Pending Moderation 8, Delft FPL 16, Nammer's Cup 271; the system and YouTube leagues are not), standings stored (page 1 and the page with the manager's rank), and each followed rival's latest locked picks fetched once per gameweek (all rivals in leagues up to 60, else top 3 and 3 either side; 29 rivals on the first run). In `run-scheduled` every 3h and `fpl sync-leagues`. Migration 0053. The page: league switcher with rank and movement, a hero (rank, gap to the leader and the place above, how many followed rivals you outscore next gameweek), the table with captain faces, last gameweek, chip and hits, next-gameweek projection against yours with a swing bar and a shared-players ring, a head-to-head (only you / both / only him, with faces and xP sums), "what could beat you" (players the rivals start that you will not own) and "where you can pull away". Links into FPL for the league and each rival. Rival projections are their last locked eleven unchanged; the page says the swing reads in your favour until their new teams lock.
- **Fixture-by-fixture board on every transfer card.** `models/fixture_matchups.py`: the club's expected goals (clean-sheet chance for defenders and keepers) in each of the next five fixtures from the same odds-blended goals the projections use, the opponent's xG let in / made over its last four, and the Matchup Lab tilt; in `/api/weekplan` as `matchups` (0.4s), drawn in `MoveCard`. It shows the user's point plainly: Chelsea's next five (1.83, 1.49, 1.62, 1.48, 1.88 team goals) beat Everton's (1.32, 1.74, 1.16, 1.23, 1.15).
- **The plan's record on Command.** Counterfactual ledger: over GW7-8 the plan (its own eleven and armband) 124, last week's team untouched 105, the user as played 129.
- **Yellow bans and cup ties.** A League Cup or FA Cup tie before the next league match serves an owed ban match (BBC on Palmer's red card falling on the League Cup tie, not the United game).
- **Solver measured.** HiGHS (`highspy`) against CBC on the real squad: five-gameweek solve 4.0s against 1.1s (same proven optimum); eleven gameweeks with the bench boost hit 120s on both (HiGHS incumbent 664.9 against 657.3). CBC stays the default (`milp_planner.make_solver`, `FPL_MILP_SOLVER=highs`).

## Open

- A leakage-free replay of the week plan over past seasons (the plan has a record only from GW7).
- Precomputed screen payloads written by `run-scheduled` so no screen waits on a cold build.
- Rival projections assume an unchanged team; once picks lock after the deadline the next sync replaces them.

## Later: the scouting report and the plan replay

User: *"i expect greatness. many optimizers use numbers and stats. i want the football eye. every player and how they play and how good they're at their craft."*

- **Scouting report (`models/scouting.py`).** Every player ranked within his FPL position (270+ minutes) on quality measures and described by style, with profile labels that are rules over the percentiles (e.g. Barry: penalty-box finisher, goal threat, aerial threat; 0.80 non-penalty xG per 90, 100th percentile; 52% of shots headers; 2.1 goals under his xG; xG+xA down 31% over his last five). Keepers get goals prevented from on-target xG faced (Kinsky -2.2, 23rd percentile). On player pages, both sides of every transfer card, and side by side on Compare.
- **Plan replay (`backtesting/plan_replay.py`, `fpl plan-replay`).** The week plan's MILP policy (5-gameweek horizon, banking to 5, hits allowed, 1.5-point bar per transfer) against one swap per decision over a 2.0 bar and never transferring, from the same round-0 squad, on `season_backtest`'s leakage-free inputs (walk-forward core projections, historical prices and clubs). Rounds are 10 match dates (about three gameweeks), one free transfer per round. First run flawed: players with no in-season record kept last season's rate (Maddison, Gabriel Jesus bought while injured); after four rounds such players are now out of the pool and squad members who drop out are valued at zero, for every policy. Result: plan 1039/1208/1435/1194/882 against swap 1006/969/1236/1118/790 and hold 963/969/1179/1068/737 (2021-22 to 2025-26), ahead in all five, +639 over the swap and +842 over hold, hits included. Limits: core points only (no fixtures, clean sheets, bonus, defensive points), no chips, no auto-subs.

## Later still: snapshots and style against opponent

- **Snapshots (`live/payload_snapshots.py`, migration 0054).** First loads measured cold: System 27s (53s while the context built alongside), Market 12s, Football 9s, Track record 6-46s, Command/My team/Plan behind a 6s shared context. Each heavy screen now answers from its last JSON (memory, then `payload_snapshot`) and rebuilds once in the background when the copy is over 90s old; after a restart System answered in 6ms, Market, Football and Command under 10ms. Served copies carry `_snapshot_age_seconds`.
- **Style against opponent.** `scouting.source_mix` (share of a player's non-penalty shot xG from open play, corners, set pieces, breaks) weighed by each opponent's shrunk concession ratio by source (`matchup_lab`) per fixture on the transfer card: "suits him" at x1.1 or more, "bad fit" at x0.9 or less. Untested as a predictor (one season of FotMob shots, about 2,250 non-penalty shots); a lens only.

## 2026-10-28: fixtures in the plan replay

The replay valued every round as one match at the player's projection, so it tested how many transfers and when, never fixture planning. Changes:

- `harness.predict_player_round_parts` splits the walk-forward core projection into (appearance + cards, goals + assists, P(60+)); `predict_player_round_points` is their sum, unchanged.
- `plan_replay` maps historical club codes to `match_results_history` ids by name (`market_identity` gained "Sheffield Utd"), lists each round's matches, and at every decision fits Dixon-Coles on results before the round. Each match: attack x (club's expected goals / its own average against this season's clubs), clean sheet exp(-opponent expected goals). Values are divided by the season's mean matches per club per round so the 1.5-point bar means the same in every variant.
- Clean sheets added to the projection (P(60+) x 4 for GKP/DEF, 1 for MID x chance) and to the scoring (60+ minutes, club conceded none). Saliba 2023-24: 18, his FPL count.
- Three plan variants run side by side: blind, match count, match count + opponent.

Results (five seasons, horizon 5 rounds): blind 6,333; count 6,753; fixtures 6,811; swap 5,810; hold 5,528. Without clean sheets in the replay the opponent added nothing on top of the count (-11), which is why they were added: a defender's fixture is mostly his clean-sheet chance. Horizons 1/2/3 rounds: fixtures 6,588/6,658/6,688, opponent over count +76/+97/+164. Live `HORIZON_GW` kept at 5 (see CLAUDE.md blocker entry). Command's track record leads with the fixture-reading plan; the System screen's ledger carries both findings.
