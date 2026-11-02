# Upgrade roadmap (2026-11-02)

The big list, written after the GW1-9 audit (`/versus`: the gap to the top 10k came from early chips and armband,
passive transfers and cash; the projection layer ranks contenders at least as well as Solio). Every item is grouped by
what it changes. `[built]` items shipped in this pass; the rest are ranked by expected value to the top-10k chase and
by wow.

Free sources confirmed live on 2026-11-02: FPL API (bootstrap, fixtures, live, entry history/picks, overall league),
FotMob match details (lineups, shots, momentum, **weather, stadium coordinates, referee, attacking zones, physical
stats per player (distance, top speed), heatmaps, h2h, team form**), FotMob team fixture lists (every competition),
Premier League Pulselive API (fixtures, text commentary), Open-Meteo (weather forecast, no key), the-odds-api (team
odds, 500 credits/month), Understat, BBC/Sky/Guardian RSS, YouTube/Reddit feeds. ClubElo's API returned 502.

## A. Decisions and the optimizer

1. **Get me X** - the cheapest route to any player: the plan re-solved with him forced in this week, every
   supporting sale and its cost against the plan of record, hits included. `[built]`
2. **What the 10k did this week** - the cohort's picks read right after each deadline: who they bought, sold and
   captained, set against your squad. `[built]`
3. **Second-half chip calendar** - WC2/FH2/BB2/TC2 from GW20 with blank and double gameweeks detected from the fixture
   list as FPL reschedules, the season's chip map in one view. `[built]`
4. **Workload** - FotMob's distance and minutes per player across league and cup matches, 7/14/28-day load, shown on
   the squad; measured against next-match minutes before it is ever allowed near a projection. `[built]` (display)
5. **Matchday conditions** - stadium, kickoff weather forecast (Open-Meteo at the stadium's coordinates), referee and
   his card rate from stored matches, on previews and the map. `[built]`
6. Team value - your squad value against the cohort's (`[built]` on Versus: 102.3 against 102.9 at GW8, so cash is not
   the gap). Timing transfers ahead of predicted rises inside the plan: not built.
7. **Box presence** - FotMob's touches in the opposition box carry to next-match xG beyond the xG rate (measured,
   leave-one-gameweek-out, 638 matches); on every football read (`[built]`), kept out of projections until tested
   against the model's own goal components.
8. Elite-crowd signal study - does top-10k ownership change predict points beyond our projection (once 4+ gameweeks of
   frozen projections exist; the plumbing is the cohort table).
9. Referee as a card/penalty input - only if a multi-season referee history becomes available (FotMob ids for past
   seasons are not stored).
10. Rank-aware armband - pick by chance of beating the top-10k field when two options are within a point.
11. Joint chip-and-transfer solve over the second half once doubles are announced (needs a faster formulation).

## B. Live football

11. **Matchday TV mode** (`/tv`) - a full-screen broadcast for a second monitor: live points odometer, rank ticker,
    every match on one board, your players' events as they happen with goal animations and the crowd. `[built]`
12. **The map** (`/map`) - every stadium on a dark football map, this gameweek's ties as arcs, weather at kickoff,
    live scores and your players pinned to their grounds. `[built]`
13. **Desktop notifications** - every HIGH event (cup withdrawals, injury headlines, manager changes, team news) already
    reaches Windows toasts through the alert engine; titles are now readable (`[built]`). A browser push/installable app
    was not built: the toasts already reach the desktop with the browser closed.
14. **Live commentary** - the Premier League's own text commentary in the match centre. `[built]`
15. Momentum river - the live momentum as a flowing ribbon behind the score. Not built.
16. Auto night mode - the floodlit palette switches on while your players are on the pitch. Not built: inverting the print palette breaks the ink shadows across ~30 screens; needs a palette pass of its own.

## C. The story of your season

17. **Season story** (`/story`) - a scroll-driven film of your season: rank river, chip moments, hauls and blanks,
    the gap to the 10k, each chapter animating in as you scroll. `[built]`
18. **The race** - you, the 10k cohort and every mini-league rival as an animated race by gameweek. `[built]`
19. Achievements (not built) - green-arrow streaks, armband hauls, differentials that came off, earned and shown in the album.
20. Counterfactual season (not built) - your season replayed as if you had followed every stored plan.

## D. Players

21. **Pizza charts** - the scouting percentiles as a radial pizza on player pages and Compare. `[built]`
22. Heatmaps per match from FotMob (not built).
23. Attacking zones - where each team attacks (left/centre/right) beside the full-backs and wingers who play there.
    `[built]` (previews)
24. Similar players (not built) - nearest neighbours in percentile space with price, for every player.

## E. Polish and trust

25. **Numbers that count** - key figures roll to their value. `[built]`
26. **QA sweep** - every route at 1440 and 1080: console errors, overflow, empty and stale states. `[built]`
27. Keyboard map (not built) (`?`) for every shortcut.
28. Per-panel freshness stamps everywhere (not built).
