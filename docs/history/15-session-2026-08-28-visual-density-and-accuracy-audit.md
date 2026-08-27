# 2026-08-28: Visual density pass, real-source audit, projection accuracy spot-check

Direct user instruction, continuing the frontend redesign session: "finish the remaining," then
new asks - projections "fucked and inaccurate," check elevenify.com/Spreadex/"Solio" (fpl.page's
own cited sources), text/badges "too small," and "more football... more crests, player images."

## Finished the remaining Phase 3 item

Squad workspace's projected-GW previews (`squad.py`) rewritten from plain text rows to real
shirt tiles grouped by position (GKP/DEF/MID/FWD), reusing `_official_shirt_url` - the incoming
transfer gets a highlighted border + "IN" badge. `_bulk_player_lookup` (`legacy.py`) gained a
`team_code` column (needed for the shirt CDN URL) - purely additive, no existing caller broken.
The now-fully-superseded `_squad_state_block_body_html` (the old text-row renderer) deleted, not
left dead. `monitoring/dashboard/` module split (legacy.py fully decomposed) deliberately NOT
done this session - zero user-visible payoff, and this session's real asks were all visual/data,
not code organization; still tracked in PROJECT_STATE.md's next-work list.

## Real-source audit: elevenify.com and Spreadex

Researched directly (browser + WebFetch + WebSearch) rather than guessing, since building a
connector against the wrong assumption would be worse than not building one:

- **fpl.page's own "Gameweek Projections" panel is explicitly credited: "Projection data from
  elevenify.com."** Confirmed live on fpl.page itself.
- **elevenify.com is a single-person Substack newsletter** ("Free Premier League predictions,"
  11,000+ subscribers, run by one hobbyist - "5 years passionate about football analytics").
  Real predictions exist (goals/clean-sheets/simulated table/player trends), updated "every
  gameweek within hours of the final fixture" - but there is **no public API, no spreadsheet
  export, no downloadable feed** of any kind; most detail requires free subscription signup;
  methodology is only loosely disclosed. fpl.page's use of it is a direct licensing/embedding
  relationship a third party (this project) cannot replicate as an automated pipeline.
- **fpl.page's player goal/assist projections are separately inferred from Spreadex odds**
  (confirmed via WebSearch/fpl.page's own `/player-odds` page) - Spreadex is a real, established
  UK spread-betting operator with a genuine "FPL Season Points" spread market. Checked whether
  this project's existing `the-odds-api.com` connector (already live, already used for
  fixed-odds bookmakers) could substitute: **Spreadex is not in the-odds-api's UK bookmaker
  list** (confirmed against their own docs) - spread betting is a structurally different market
  type from the fixed-odds/totals markets the-odds-api aggregates, so this isn't a config
  change, it would need its own connector. Checked spreadex.com directly: the live per-player
  spread market pages are behind a dynamic, session/market-id-specific SPA with no stable public
  URL found, and Spreadex is a licensed gambling platform - scraping live pricing from it would
  need account creation (a prohibited action for this agent) and sits in real ToS/legal grey
  area for a regulated betting product, unlike public bookmaker odds aggregation.
- **"Solio" could not be identified** - no real service by that name surfaced in relation to FPL
  projections; may be a mishearing/typo of something else. Not guessed at or built against.

**Conclusion, reported honestly rather than silently dropped or faked**: neither of fpl.page's
own two credited sources is viable for this project to integrate as a free, automated, ToS-safe
live data feed. This project's existing Tier-1/2 pipeline (official FPL API, Understat
shot-level xG, the-odds-api's aggregated fixed-odds bookmakers, BBC/Sky RSS, FotMob) is the real,
disclosed, reproducible one available under the project's own "free resources only" /
"no fabrication" constraints - a genuinely different methodology from fpl.page's blogger-plus-
spread-betting blend, not an inferior substitute for it, and not something a documented backend
connector rewrite would fix.

## Projection accuracy spot-check

Investigated a concrete, current, real example rather than treating "inaccurate" as
unfalsifiable: the live production DB's GW2 captaincy pick is **Mbeumo (median 6.04 xP) over
Haaland (median 5.13 xP)** - surprising on its face given Haaland's real, dominant multi-season
record (27 goals/2953 mins in 2025/26 vs Mbeumo's 11 goals/2611 mins) and a real GW1 (2026-27)
match where Haaland's own underlying output (5 shots, 0.75 real xG) was actually *better* than
Mbeumo's (4 shots, 0.55 xG). Traced the real computation directly
(`models.expected_points.expected_points`/`_player_match_rates`): Haaland's real per-90 shrunk
goal rate IS correctly higher than Mbeumo's (0.2162 vs 0.1713) - the underlying player-quality
signal is right. The swing is the real, mechanically-correct combination of three genuine GW2
facts: (1) Man Utd's real GW2 fixture is officially rated *easier* than Man City's this specific
week (`team_h_difficulty=2` vs `team_a_difficulty=3`) and the Dixon-Coles model's own projected
team goals agree (Man Utd 2.61 vs Man City 1.96); (2) midfielders score 5 pts/goal under real FPL
rules vs 4 for forwards; (3) Mbeumo, as a midfielder, gets a real clean-sheet-bonus contribution
(0.385 pts) that a forward structurally never earns. **Verdict: this specific case is a real,
disclosed, fixture-driven single-gameweek signal, not a bug** - confirmed by checking the actual
component breakdown rather than accepting the headline number at face value. One real, separate
observation surfaced by the same investigation and not yet acted on: `ceiling` tracks `median`
closely enough that whichever player currently has the higher median also gets the higher
ceiling (Mbeumo 13.0 vs Haaland 10.0 here) - plausibly under-representing a genuinely elite
player's real score-distribution fat tail (hat-trick propensity) independent of this week's
fixture; flagged as a real follow-up candidate, not fixed this session (would need its own
investigation into how `floor`/`ceiling` are derived before touching it).

No specific other "wrong number" was named by the user to chase further; if the complaint
persists, the fastest path is a concrete example (a specific player/number that looks wrong) -
the investigation method above (trace real inputs, don't assume) is the one to repeat.

## Visual density / typography pass

Real measurements taken directly against fpl.page (`getComputedStyle` via the Claude Browser
tool), not assumed:

- fpl.page's own body font-size is 14px (root 16px, no scaling hack) - its real font-size
  histogram is dominated by 12px (668 elements) and 14px (117), with 10px used only for genuinely
  minor content (34 elements). This project's dashboard had **~100 CSS rules below that 12px
  floor** (many at 9.3-10.9px, mostly all-caps micro-labels) - a real, systemic undersizing bug,
  not a one-off. Fixed with a scoped floor-bump (every `font-size` below `0.75rem` raised to
  exactly `0.75rem`/12px, via a small script over the CSS text, not a root-level multiplier -
  values already at or above the floor were untouched, preserving the real existing hierarchy
  rather than repeating the earlier-rejected `html{font-size:18px}` anti-pattern).
- fpl.page's own crests are **40x40px** in a dense list context (its Price Changes table) and
  24x24px for small inline mentions. This project's `.fdr-badge`/`.outlook-badge` (used
  everywhere - Fixture Tool rows, Team Outlook, Intelligence cards) were **18x18px** - under
  half fpl.page's real size, a genuine, concrete match for the user's "badges too small" report.
  Bumped to 32px in dense table/ticker rows, 40px in the Intelligence workspace's own team-signal
  cards (which have more room, matching fpl.page's own denser-context size exactly); widened the
  Fixture Tool's sticky team-name column (74px -> 96px) to fit the bigger crest without crowding.
- Added real player shirt images to the Opportunity Board's Breakout/Trap/Role-Change/Value
  cards (44px, via `_official_shirt_url`) and a real club crest to the Fixture-Swing card (32px,
  via `_official_badge_url`) - these categories previously showed player/team names as plain
  text only. Combined with the Squad shirt-tile work above, this is the direct "more football...
  more crests, player images" ask.

## Testing

10 new direct unit tests: `squad._projected_shirt_tile`/`_projected_squad_html` (IN-player
badge, transfer line, ROLL state, position grouping, sold player not duplicated into the tile
grid). Full suite: 1024/1024 (1014 baseline + 10 new). Dashboard regen ~1m12s (in line with the
~1min baseline, no real regression).

## Live verification

Real production DB, `fpl dashboard` regen, Claude Browser tool. Confirmed via `getComputedStyle`
that the font-size floor and badge sizes took effect exactly as intended. Screenshots (desktop):
Squad's GW3 projected view now shows real shirt tiles grouped GKP/DEF/MID/FWD with the
transferred-in player highlighted; Intelligence workspace's team cards render real 40px crests
(Arsenal/Brighton/Brentford/Everton/Hull/Leeds, all with real match evidence text); confirmed via
`javascript_tool` (immune to a few compositor-timing screenshot flakes hit again this session,
same known quirk as prior sessions) that 13 real shirt/badge images render at the intended sizes
in the Opportunity Board. Zero console errors throughout.
