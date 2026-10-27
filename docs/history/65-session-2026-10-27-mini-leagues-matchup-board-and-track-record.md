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
