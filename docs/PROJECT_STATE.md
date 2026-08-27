# Project State

Last updated: 2026-08-27. Read this before resuming work — it's the current, load-bearing snapshot,
kept lean on purpose. **Don't add session narrative here** — a new capability/architecture change gets
one short factual entry; the story of how it was built, bugs found, and live-verification detail goes
in `docs/history/` (one new dated file per session, indexed in `docs/history/README.md`).

## Where things stand

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

Summarized: bonus/BPS season-grain only; single predicted-lineups source; sampled-EO margin of error computed but not surfaced; cross-league coverage partial (~5 leagues); manager-change signal not wired into prior-shrink speed; team-level qualitative signal deliberately not fed into Dixon-Coles (leakage-safety); Elite-manager panel needs a season to end; penalty-duty adjustment gated on sample size (2 of 20 needed); dashboard regen ~1 minute; `fpl strategic-plan --current-action` (default on) adds real extra cost on top of that (~2-10+ min depending on horizon/beam-width) — a manual command's cost, never re-run live by the dashboard.

## Next recommended work (real candidates, not started)

1. **Path-diversity clustering** — group near-identical top-N strategic paths into real tiers (roll-heavy/transfer-heavy/fixture-led/chip-led) rather than listing near-duplicates, only where those structures genuinely emerge from the search.
2. **Value-of-information folded into `compare_starting_actions`' own ranking**, not just the single-swap decision's separate `information_value_note`.
3. **Team-level qualitative → projection propagation**, done safely (an xG-regression supplement on `team_match_state`, not touching the Dixon-Coles fit itself).
4. **Manager-change → prior-shrink wiring** — a real, scoped, previously-deferred fix.
5. **Surface sampled-EO margin of error** in the dashboard/CLI (currently derived, never printed).
6. **Decision-outcome calibration** — capture recommended-action-taken vs rejected-alternative's real outcome per completed GW (`models/calibration.py`/`prediction_outcomes` exist for projected-vs-actual already); needs a season with completed GWs to have real observations.
7. **Frontend redesign Phase 2** — Intelligence/Opportunity/Market/Fixtures workspaces properly re-skinned into the new HOME/PLAN/SQUAD information architecture (Phase 1, done 2026-08-27 - see `docs/history/13-session-2026-08-27-frontend-redesign-phase1.md`); they currently still render via their pre-existing `legacy.py` markup, reachable but visually unmigrated. Also: finish the `monitoring/dashboard/` module split (legacy.py's remaining ~4600 lines are still one file), and give Squad's projected-GW previews real shirt tiles instead of the current text/row-grouped-by-position view.
8. **Dashboard visual/typography QA at more breakpoints** (1440/1024/768/360px) — Phase 1 verified live at desktop (1280) and mobile (375) with real screenshots via the Claude Browser tool (the compositor-unavailable blocker noted earlier in 2026-08-27 was transient in that session, not a real dashboard bug - screenshots worked once retried); the remaining widths are real follow-up, not blocked.

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
