# Preseason calibration: cross-league signings + squad churn (design)

Date: 2026-08-20. Not a roadmap pillar — a direct accuracy hardening on top of
Pillar 0, prompted by the user asking explicitly how this project handles the
still-open 2026-27 transfer window: new signings arriving with no PL history,
and squad churn shifting a team's real strength before real matches exist to
show it.

## Research first (not guessed)

Looked at how real practitioners handle this (arxiv: "An Adaptive Glicko-2
Rating Framework for Probabilistic Football Forecasting and Season
Simulation", 2607.01722; "Transfer Portal: Accurately Forecasting the Impact
of a Player Transfer in Soccer", 2201.11533; general FPL-community xPoints
methodology writeups). Two patterns recur:

1. **Structural shocks at season/transfer-window boundaries** — inject extra
   rating uncertainty at a season transition rather than trusting a smoothly
   time-decayed fit, so early real matches can move the rating fast. Not
   "recompute from scratch," but "don't over-trust last season's number
   before real evidence exists this season."
2. **Cross-league priors with Bayesian updating** — a transferred player's
   new-league output starts from a translated version of their old-league
   output (adjusted for league quality/style), then updates fast as real
   minutes accrue in the new league.

Checked whether a bookmaker market signal could do the team-strength side for
free (the-odds-api.com already integrated, live-verified working for
match-level h2h/totals) — queried `/v4/sports` for real: EPL has
`has_outrights: false`, and no `soccer_epl_winner`-style market exists at any
tier for this API (checked the full 175-sport list; the only outright markets
offered at all are NFL/NBA/MLB/NHL/NCAA/golf/politics/World Cup — not EPL).
Ruled out cleanly, not silently skipped.

## What this project can actually build for free, right now

- **Understat's scraper (fixed 2026-08-20) already talks to the exact same
  JSON endpoints for 5 other top European leagues**, not just EPL —
  `getLeagueData/{league}/{year}` takes a league code (`La_liga`,
  `Bundesliga`, `Serie_A`, `Ligue_1`, `RFPL`), currently hardcoded to `EPL`
  only in `understat_source.py`. Genericizing this is a small change, not a
  new integration, and gives real shot-level (xG/xA) data for a genuine
  cross-league new signing's most recent season — the closest thing to a
  ground-truth ability signal this project can get without a paid source.
- **`player_season_history` + current `players.team_id` already let us
  measure real squad churn** — no new source needed. For a given team,
  compare last season's minutes-weighted contributing squad against this
  season's roster; the departed-minutes fraction is a real, computable
  signal for "how much should I trust this team's historical Dixon-Coles
  fit right now."
- **Championship-level (or other EFL) data for promoted teams is a real
  gap that stays open.** football-data.co.uk does carry English second-tier
  results (division code `E1`), which could seed a promoted team's
  Dixon-Coles attack/defence via an empirically-fit Championship→PL scaling
  factor (comparing past promoted teams' final-Championship-season fit
  against their actual first-PL-season fit, both computable from data this
  project already ingests one division at a time). That is real, valuable,
  and **out of scope for this pass** — it needs a multi-season historical
  promoted-team analysis to fit the scaling factor honestly rather than
  guess it, which is its own piece of work. Documented as a follow-up, not
  silently dropped (same pattern as Plan 2b being split out).

## Scope for this pass

**Component A — squad-churn-aware team strength.** New
`models/squad_churn.py::team_churn_ratio()`: minutes-weighted fraction of a
team's meaningful contributors (>=450 minutes, i.e. ~5 full matches, last
season) who are no longer at that club this season, using
`player_season_history` + current `players`/`teams`. Wired into
`_blended_fixture_goals` in `expected_points.py`: a team's fitted
attack/defence rating is shrunk toward 0 (this model's own
identifiability-neutral point — see `team_strength_dc.py`'s reference-team
docstring) proportional to churn, capped, documented as an explicit
uncalibrated heuristic (same honesty pattern as `price_forecast.py` — no
in-season data yet to fit the shrink constant against). This does **not**
touch a team that is completely absent from the Dixon-Coles fit (genuinely
promoted teams with zero PL match history at all, e.g. Coventry/Hull/Ipswich
in the current pool) — those still degrade to the existing flat-average
fallback; that's Component B's job, deferred.

**Component B — deferred, documented above.** Championship-level promoted-
team calibration.

**Component C — cross-league new-signing player prior.**
`fetch_understat_season_page`/`backfill_understat` genericized to take a
`league` parameter. New `models/cross_league.py::find_cross_league_prior()`:
for a player with zero `player_season_history` AND zero
`player_match_stats_history` rows for the current club (i.e. genuinely new
to the English top flight, not just new to Understat), search the other 5
Understat leagues' most recent season for a name match (reusing
`market_identity.resolve_player_id`-style matching), and if found, return
their per-90 goals/xG/xA there scaled by a **league-quality factor** — the
ratio of the two leagues' average goals-per-match in that same season, both
computed from real fetched data (not a fixed constant). This is honestly a
crude single-number quality adjustment, not a trained cross-league model
(the arxiv "Transfer Portal" paper's neural approach is real but far beyond
this project's free-resource, from-scratch scope) — documented as such.
Wired as a new fallback tier in `player_regression.py`, tried before
`season_position_average_per90()` (the pure positional-average fallback),
since a translated real signal beats a positional-average guess about a
specific player. Players truly new to first-team football anywhere (no
matching row in any of the 6 leagues) still fall through to the existing
positional-average prior — correctly, since there's nothing better to use.

## Non-goals for this pass

- No new external data source beyond leagues Understat already serves.
- No attempt to auto-detect *which* league a new signing came from via
  journalism text parsing — the cross-league name search across all 5 other
  leagues does this mechanically and for free, without needing that.
- No change to the existing Understat-empty-for-current-season fallback
  chain (`season_shrunk_rate`) — this adds a *new* tier that sits before the
  positional-average fallback, doesn't touch the existing ones.
