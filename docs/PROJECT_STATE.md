# Project State

Last updated: 2026-08-29. Read this before resuming work — it's the current, load-bearing snapshot,
kept lean on purpose. **Don't add session narrative here** — a new capability/architecture change gets
one short factual entry; the story of how it was built, bugs found, and live-verification detail goes
in `docs/history/` (one new dated file per session, indexed in `docs/history/README.md`).

## Where things stand (updated 2026-08-29)

Dashboard: chip rendering (Plan timeline, Squad preview) is now single-sourced from each path's
own `steps[].chip_played` - never the separate `schedule_chips` DP cross-check, which could
(and did) disagree on GW/chip. Home hero discloses the cached strategic-plan decision's real age
(`Computed Xh ago · decision #N`) and shows an explicit RECOMPUTING banner when a real HIGH-
severity `change_events` row postdates it (`models/decision_freshness.py`). Squad workspace's
projected future-GW squads now resolve a real starting XI/bench order/captain/vice per specific
GW (`optimization/squad.py::resolve_projected_xi`), not carried over from the current squad.
Plan's top-N paths are now built from `compare_starting_actions`' real per-starting-action options
(`optimization/transfers.py::build_diverse_paths`), not the raw beam's own top-N (which provably
converged to near-duplicate variants of one dominant opening move) - each displayed path now has a
genuinely different first action, plus a real 3/5/8GW `horizon_breakdown` (total/delta-vs-roll/
delta-vs-next-best per checkpoint, `checkpoint_breakdown`). Opportunity Board cards show a real
"considered by optimizer" flag (against the same diverse-paths candidate pool) and Value no longer
shows a card for a player already in the squad (matches Breakout's existing exclusion). Fixed a
real intermittent "dashboard shows no squad" bug - a torn read in `ingestion/my_team.py::get_latest_squad`
racing against the project's own scheduled sync writer (`docs/history/20-...md`).


**Season**: 2026-27, GW1 finished (all 10 fixtures analyzed, real qualitative evidence recorded for Arsenal-Coventry and league-wide via the zero-LLM statistical detector), GW2 not yet locked (real fixtures scheduled ~Aug 29-Sep 1). Real locked squad synced (entry 7378572, `fpl my-team`).

**System capability**: full pipeline from raw data → calibrated projections → multi-GW strategic planning → dashboard, running autonomously via the Windows Task Scheduler. Real free-transfer state, real chip-usage detection, real qualitative evidence (LLM + zero-LLM), real confidence/robustness/uncertainty reporting, real 1/3/5/8-GW path search with joint chip+transfer optimization (chips compete inside the beam, not a post-hoc overlay), a real full-squad starting-action comparison producing one authoritative CURRENT RECOMMENDED ACTION, a real Squad workspace (per-path/per-GW squad reconstruction, CURRENT/GW pill switcher), real Model-vs-Football-vs-User-view fusion, a real Adversarial Decision Audit (`fpl decision-audit`) that tries to disprove the current recommendation - causal trace, named-player MODEL-vs-FOOTBALL comparison, analytic counterfactual-stress falsifiers, multi-horizon (3/5/8GW) alternative-action audit, league-wide breakout/differential/trap check, cold-start coverage, qualitative-evidence chain, and a final trust/no-trust scorecard - cached in the decisions journal and surfaced as a compact "WHAT CHANGES IT" line + collapsed full trace under Advanced -> Decision Detail.

## Strategic planner status

`optimization/strategic_planner.py` + `optimization/transfers.py::search_transfer_sequences` — real beam search (default beam width 5, horizon 8 GW), scores full-squad EV summed across the horizon, jointly chip-aware (wildcard/freehit/bboost/3xc compete against ROLL/TRANSFER on the same ranking key at every step, `optimization/chips.py::chip_gw_marginal_value`). `chips.py::schedule_chips`'s Monte Carlo DP (`--with-chips`) is an independent cross-check/opportunity-cost narrative, not the path-selection mechanism. `search_transfer_sequences`/`best_transfer_for_player` price hit cost using the real FT state (`models/free_transfers.py`).

`optimization/transfers.py::compare_starting_actions` + `optimization/strategic_planner.py::synthesize_current_recommendation` compare every real starting action (ROLL, each squad player's best replacement, each legal chip) against its own best full-horizon future and produce one authoritative `CurrentRecommendation` (ACT/REVIEW, same evidence-confidence gate `decision_analysis.py` uses). Surfaced via `fpl strategic-plan --current-action` (default on) and the dashboard's Home hero + Plan workspace. Real production run (locked squad, 8GW horizon): ROLL wins over the immediate 1-GW pick and over PLAY WILDCARD/FREEHIT, consistent with the main search's own top path.

## Decision-object architecture

`optimization.decision_analysis.analyze_transfer_decision`/`analyze_captain_decision` are the single real source of truth for "what should I do." `optimization.decision_engine.evaluate_locked_squad` is a thin KEEP/CHANGE wrapper that derives its answer from an already-computed `ta`/`ca` rather than re-scanning. The dashboard's Home hero (`#home`) and Plan workspace (`#plan`) are the only two places a recommendation renders (frontend redesign, 2026-08-27 - `monitoring/dashboard/home.py`/`plan.py`, replacing the old Primary Decision panel/Strategy Explorer); every other panel either reads from these or is explicitly labeled as answering a different question (Optimizer Delta = from-scratch rebuild comparison, collapsed under Advanced).

## Free-transfer tracking

`models/free_transfers.py::compute_real_free_transfers` replays the real, public FPL accrual rule over already-ingested `my_team_gw_summary.event_transfers` + `my_team_picks.active_chip` history. Returns `None` (never a guess) on a genuine gap in synced history. Wired into `LockedSquadState.free_transfers`, consumed by `analyze_transfer_decision`/`_evaluate_transfer`.

## Known gaps (see CLAUDE.md's "Current known blockers" for the full, current list)

Summarized: Dixon-Coles team-strength ridge (`_RIDGE_LAMBDA=2.5`, fixes a real small-sample-promoted-team overfit) not yet backtest-tuned; bonus/BPS season-grain only; single predicted-lineups source; sampled-EO margin of error computed but not surfaced; cross-league coverage partial (~5 leagues); manager-change signal not wired into prior-shrink speed; team-level qualitative signal deliberately not fed into Dixon-Coles (leakage-safety); Elite-manager panel needs a season to end; penalty-duty adjustment gated on sample size (2 of 20 needed); dashboard regen ~1 minute; `fpl strategic-plan --current-action` (default on) adds real extra cost on top of that (~2-10+ min depending on horizon/beam-width) — a manual command's cost, never re-run live by the dashboard.

## Next recommended work (real candidates, not started)

1. **Path-diversity - done 2026-08-29** (see `docs/history/19-session-2026-08-29-path-diversity-and-p1-audit.md`): `build_diverse_paths` replaces the raw beam's near-duplicate top-N with `compare_starting_actions`' real per-starting-action options - live-verified against a fresh production run (decision #102): 5 genuinely distinct opening moves (PLAY WILDCARD/PLAY FREEHIT/3 different named-player transfers), not the old single dominant-strategy cluster.
11. **Per-path 3/5/8-GW breakdown - done 2026-08-29**: `checkpoint_breakdown` (bounded to the selected top-N paths only, reuses the shared EV cache) - live-verified real signed `delta_vs_next_best` per checkpoint (positive for whichever path actually leads AT that horizon, not assumed to match the full-horizon leader).
2. **Value-of-information folded into `compare_starting_actions`' own ranking**, not just the single-swap decision's separate `information_value_note`.
3. **Team-level qualitative → projection propagation**, done safely (an xG-regression supplement on `team_match_state`, not touching the Dixon-Coles fit itself).
4. **Manager-change → prior-shrink wiring** — a real, scoped, previously-deferred fix.
5. **Surface sampled-EO margin of error** in the dashboard/CLI (currently derived, never printed).
6. **Decision-outcome calibration** — capture recommended-action-taken vs rejected-alternative's real outcome per completed GW (`models/calibration.py`/`prediction_outcomes` exist for projected-vs-actual already); needs a season with completed GWs to have real observations.
7. **Frontend redesign Phase 2 - done 2026-08-28** (see `docs/history/14-session-2026-08-28-frontend-redesign-phase2.md`): Intelligence workspace now a real league-wide team-signal briefing (`intelligence.py`, calls `team_outlook` across every real team, not just the squad's), Opportunity workspace redesigned into a real scouting board with real confidence per card and a 1-visible-plus-details-for-more cap per category (`opportunity.py`), Market workspace re-framed (`market.py`), Fixture Tool gets real range/metric(overall-attack-defence)/sort/filter controls (`fixtures.py`, reuses the already-built `models.fixtures.fixture_difficulty` - honestly discloses the current preseason attack/defence-strength-not-yet-published fallback). `legacy.py`'s now-fully-superseded orchestrators (`_intelligence_summary_html`/`_opportunity_board_html`/`_market_summary_html`/`_fixture_ticker_html`) deleted, not left dead.
8. **Frontend redesign Phase 3, partially done 2026-08-28**: Squad's projected-GW previews now use real shirt tiles grouped by position (was plain text rows) - see `docs/history/15-session-2026-08-28-visual-density-and-accuracy-audit.md`. Still not done: the `monitoring/dashboard/` module split (legacy.py is still ~4500 lines, mostly Advanced-drawer/Live/Team-Outlook/Match-Intelligence renderers). Fixture Tool's Attack/Defence metrics will start genuinely differentiating from Overall automatically once FPL publishes real attack/defence strength ratings (no code change needed, just currently coincide via an honest, disclosed fallback).
9. **Data sourcing investigation, done 2026-08-28** (see same history file): elevenify.com and Spreadex - the two sources fpl.page itself credits for its projections - are both confirmed NOT viable as automated backend sources for this project (elevenify: single-person Substack, no API/feed, subscription-gated; Spreadex: licensed spread-betting operator, no stable public market data without an account). This project's own Tier-1/2 pipeline (official FPL API, Understat, the-odds-api, BBC/Sky RSS, FotMob) remains the real, disclosed, automatable one - genuinely different methodology from fpl.page's, not a lesser one.
10. **Four new league-wide dashboard panels, done 2026-08-28** (direct fpl.page screenshot comparison - see `docs/history/17-session-2026-08-28-new-panels.md`): Injuries (`injuries.py`, reuses `models.availability.list_availability`), Expected Data (`player_data.py`, real current-season xG/xA/xGI from `player_match_stats_history`), Team Odds and Top Transfers In/Out (`market.py`, league-wide rankings from already-real data). Still not built: Price Changes' rich filterable/searchable UI with a per-hour-trend progress bar, and a real historical Odds Tracker line chart - both need real UI/infra work beyond what already-available data supports (the Odds Tracker specifically needs periodic odds snapshotting into a history table, which doesn't exist yet).
9. **Dashboard visual/typography QA at more breakpoints** (1440/1024/768/360px) — Phase 1+2 verified live at desktop (1280) and mobile (375) with real screenshots via the Claude Browser tool; the remaining widths are real follow-up, not blocked.
12. **Opportunity Board "considered by optimizer" flag + Value squad-member exclusion - done 2026-08-29** (see `docs/history/19-session-2026-08-29-path-diversity-and-p1-audit.md`): every card now shows a real yes/no against the diverse-paths candidate pool (never rendered when no strategic plan has run); Value no longer shows an already-owned player as a buy opportunity (real live-screenshot QA finding, matches Breakout's existing exclusion).
13. **P1 product-gap audit, done 2026-08-29**: direct source audit against the full fpl.page/FPL Copilot benchmark list found the dashboard's copy layer (`_HUMANIZE_RULES`, the redesigned Home/Plan/Squad workspaces' structured-fact composition instead of raw backend prose) and visual-component diversity (12+ real distinct CSS component families already in active use - shirt tiles, timeline nodes, opportunity cards, data tables, team-signal cards, horizon-breakdown cells, momentum rows - never a single universal card container) already substantially satisfy those two P1 asks from prior sessions' work; no data-quality bugs found on a real spot-check (max clean-sheet probability across every team's next fixture: 49%, no extreme ceilings). **Genuinely still unbuilt** (each real, scoped, comparable in size to a full prior pillar session, not attempted): fpl.page-style live/context features (Points Changes, Template Team, Top 10K context, article feed), a full unified single-view Market redesign beyond the current section-grouped layout, Fixture Tool interaction-model parity with fpl.page (5/6/8GW+custom, Overall/Attack/Defence, Easiest/Hardest/A-Z, rotation view), Player Inspector click-through redesign (WHY BUY/HOLD/SELL), and decision-outcome calibration (blocked on a season with completed GWs).

## Verification procedure (run before trusting any change to the decision layer)

```bash
# 1. Full test suite - must be green
./.venv/Scripts/python.exe -m pytest tests/ -q

# 2. Real strategic plan against the real production DB
./.venv/Scripts/fpl.exe strategic-plan

# 3. Real dashboard regen - confirm it completes and note the wall-clock time
./.venv/Scripts/fpl.exe dashboard

# 4. Serve it over localhost (NOT file://) and inspect visually in a real browser
python -m http.server 8899 --directory data
# open http://localhost:8899/dashboard.html, screenshot at 1440/1024/768/390/375/360px

# 5. Real production acceptance check: does `fpl transfer-analysis` / the
#    dashboard's Home hero agree, and can you answer "what
#    should I do for GW2, and why" within 5 seconds of opening the page?
./.venv/Scripts/fpl.exe transfer-analysis
```
