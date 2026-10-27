# Session 2026-10-27 (evening): optimizer upgrades - yellow-card bans, the bench boost by week, and three football factors refused

User: *"now do what you have to to improve the optimizer by any means necessary. it cant just be dependant on data right? i seriously want huge upgrades cos you say youve been upgrading but it doesnt feel like it at all"*

## Where the model actually stands

- Against Solio on GW8 (56 players both projected): ours MAE 2.61, Spearman among contenders 0.174, top-20 realised 4.15; Solio 3.08, 0.122, 3.70; a 50/50 average 2.74, 0.198, 4.25. On GW7 only 10 players overlap. Solio publishes about 60 players a snapshot, so it cannot be an ensemble input across the pool, and on the evidence it would not improve ours.
- Goalkeeper and defender under-prediction in GW8 (+0.5, +0.6 a player) is a high clean-sheet week: keepers with 60+ minutes kept 40%, against a long-run ~24%.

## Football factors tested and refused (each the user's "not just data" kind of idea)

- **European-tie rotation.** Regulars (started all but one of their last five) started 84% of league matches within four days after a European tie this season (181/216), 81% with no tie (376/465), 80% next to a cup tie, 81% before a European tie. No effect. Matches the 2026-10-25 Champions League figure over five seasons.
- **Key attackers missing lowers team strength.** 3,238 Understat team-matches 2021-27: actual xG over a form baseline (team's last ten, against the opponent's last ten conceded) did not fall with the share of the team's xG carried by regulars who did not play (0-0.1 missing 0.97, 0.1-0.2 1.04, 0.2-0.3 0.89, 0.3-0.45 1.01; slope +0.02, bootstrap 95% -0.34 to +0.38).
- **Re-splitting a team's goals over the expected eleven.** Live projections allocate a team's goals by each player's historical share times his expected minutes, so the shares need not sum to one (Palace 0.71 because a departed Uche and a doubtful Mateta still hold theirs; Coventry 1.44). Walk-forward with shares from earlier matches and minutes from each player's last five: rescaling to the whole made player-match xG and goals worse in 2024-25 (xG SSE 884 to 905), 2025-26 (840 to 846) and 2026-27 (84.2 to 85.1), and every partial strength was in between; correcting only totals outside 0.8-1.2 was never better than leaving them alone. A first run that keyed players on FPL id, which Understat fills for some matches and not others, made the totals look much worse (p10 0.30); keyed on Understat's stable id the result held.

## Built

- **Yellow-card bans (`models/suspension_risk.py`).** Five bookings by a club's 19th league match is a one-match ban, ten by the 32nd two, fifteen by the 38th three. FPL flags a player suspended only once the ban is incurred. `ban_schedule` carries the distribution of his yellow count and ban matches owed through the club's fixtures in kickoff order; booking chance per match 1 - exp(-shrunk yellow rate x expected fraction of 90). The chance of serving a ban in a fixture moves that share of its minutes to zero (`expected_points._after_yellow_bans`, applied after the start blend and the return forecast, never to a confirmed sheet). Effect on 5-GW xP: Thiago (4 yellows) 21.96 to 19.12, McBurnie 17.85 to 15.85, Cash 13.48 to 11.62; Groß, Rogers, Tavernier, Bogle (3 yellows, in the user's squad) about -0.9 each. Squad news lists the chance for players on 3+ yellows (Bogle 23%, Tavernier 21%, Groß and Rogers 20% to serve one in GW9-13). The road ahead now sells Rogers in GW10. Booking rate check (in-sample, this season): 303.6 predicted against 311 actual yellows; the top fifth by rate 144 against 184, so ban chances for card-prone players read low.
- **The bench boost by week (`week_plan.build_chip_plan`).** The PLAN chips panel said a bench boost "waits for" a double gameweek; none is scheduled before the first-half chip expires after GW19, so that advice would have wasted it. The plan now prices each remaining bench boost / triple captain in every gameweek of its window along the road-ahead squads (the last planned squad beyond the eight-week horizon) with the projected eleven and bench of that week, and recommends the best. GW9 plan: best GW10, bench 15.4 (Rudoni, Bogle, Davis, Kinsky), this week 12.8, every week 12.8-15.4. Panel shows the ladder as bars; CLI prints it.
- **Refused: choosing the chip jointly with transfers.** The MILP can model the bench boost (`model_chips`); over the eleven gameweeks to GW19 it ran 64s (25 a position) and 90s (12 a position) and never proved optimality inside its limit, and its answer moved between runs. The along-the-plan reading is consistent with the plan of record and costs a few seconds.

## Assumptions and open items

- A ban is served in the next league match(es), never in a cup tie in between; reds are left to FPL's flag.
- Chip weeks beyond the road ahead's eight assume the last planned squad.
- `PROJECTION_REVISION` is `start-blend-returns-yellow-bans-3`, so stored plans rebuild.
- Next: fit the booking rate's tail; a provable joint chip solve (warm start from the road ahead, or a smaller horizon window around the candidate weeks); second-half chips from GW20.
