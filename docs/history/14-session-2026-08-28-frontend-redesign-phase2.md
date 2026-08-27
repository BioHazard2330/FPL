# 2026-08-28: Frontend redesign Phase 2 — Intelligence/Opportunity/Market/Fixtures

Direct continuation of Phase 1 (`docs/history/13-session-2026-08-27-frontend-redesign-phase1.md`),
user said "Continue now." Phase 2 scope per the original design doc: re-skin the remaining
Intelligence/Opportunity/Market/Fixtures panels into the new workspace IA, still reading from
already-built real data (no new backend analytics per the standing instruction).

## New modules

**`intelligence.py`** — real league-wide team-signal briefing, per the direct spec's card shape
(TEAM / SIGNAL ↑↓ / WHY / FPL IMPACT / CONFIDENCE + a "View details" expander). The one genuine
behavior change from the pre-redesign squad-scoped Team Outlook: calls `models.team_outlook.
team_outlook` across every real team in the `teams` table, not just the squad's own teams (same
already-built function, wider real call — no new model). Reused `TeamQualitativeIntelligence`'s
already-real `current_attacking_signal`/`current_key_observation`/`current_fpl_implication`/
`current_confidence` fields, which had never been surfaced in this exact card shape before —
genuinely closer to "already built, just never displayed this way" than "new work." Squad teams
sort first (still real league-wide coverage — relevance is the sort key, never a filter). The
pre-existing squad-scoped "what changed for me" content (squad changes/price moves/who-benefits/
risk-monitor/do-differently) stays as a secondary "My Squad Impact" `<details>` block underneath.

Real bug caught by writing the module's own test before it ever ran live: `_official_badge_url`
expects `teams.code` (the FPL CDN's own numeric club id), and the first draft passed
`outlook.team_id` (this project's internal DB id) instead — would have rendered a wrong/broken
crest for any team whose id happened to differ from its code. Fixed to fetch and thread through
the real `code` column, same pattern `legacy.py`'s own `_team_outlook_html` already used.

**`opportunity.py`** — real scouting board (Breakout / Fixture Swing / Role Change / Value /
Trap), reusing the same real `models.breakouts.find_breakouts`/`models.traps.find_traps`/
fixture-quality/setpiece-change/price-rise reads the pre-existing board already ran. Two real
changes: (1) each category shows its own single best real candidate by default with a
`<details>` revealing up to two more, honoring the direct spec's "only 3-5 important items"
(the pre-existing board showed up to 3 per category × 5 categories = up to 15 by default); (2)
added a real per-card confidence badge via `models.projection_confidence.
assess_projection_confidence` — the same function `plan.py` already reuses for path confidence,
no new model, just applied to opportunity-board candidates for the first time. Deliberately did
NOT invent a single cross-category ranking score to hit "3-5 total" more precisely — the
pre-existing board's own documented design principle ("never re-scored with an invented
board-specific weighting," since value_ratio/ownership%/avg-difficulty/price-delta are real but
incomparable units) still holds; capping to 1-visible-per-category is the honest way to get a
lean default view without fabricating a unified score.

**`market.py`** — thin workspace-framing wrapper over the pre-existing, already-correct
`_market_divergence_html`/`_price_predictions_html`/`_transfer_momentum_html` (MODEL vs MARKET
divergence, PRICE, OWNERSHIP/MOMENTUM) — no logic changes, just the new heading language.

**`fixtures.py`** — real Fixture Tool controls per the direct spec (range/metric/sort/filter,
benchmarked against fpl.page). Range (3/5/8 GW) and metric (Overall/Attack/Defence) are both
pure client-side reveals over one real 8-GW server render — every cell carries its own real
overall/attack/defence FDR class as data attributes, no second query path. The Attack/Defence
split reuses `models.fixtures.fixture_difficulty` (already built, real, not a new model) —
honestly discloses the current real gap: `strength_attack_*`/`strength_defence_*` are still
all-zero in the live production DB this preseason (FPL hasn't published the split yet), so all
three metrics currently coincide via the function's own already-existing overall-strength
fallback; a visible banner says so, and the toggle will start differentiating automatically the
moment FPL publishes real splits, no code change needed. Sort (already real, carried over) and a
new squad-only/all-teams filter round out the four required controls.

## Legacy cleanup

`_intelligence_summary_html`, `_opportunity_board_html`, `_opportunity_card`,
`_OPPORTUNITY_CARD_LIMIT`, `_market_summary_html`, `_fixture_ticker_html` deleted from
`legacy.py` (now fully superseded, not left as dead code) — same discipline as Phase 1's
retirement of the old Primary Decision panel/Strategy Explorer. `_market_divergence_html`/
`_transfer_momentum_html`/`_price_predictions_html`/`_who_benefits_html`/`_do_differently_html`/
`_bulk_player_lookup`/`_fixture_quality` kept (still real, still reused by the new modules).

## Testing

3 `test_dashboard_opportunity_board.py` tests rewired from `_opportunity_board_html` to
`opportunity.render_opportunity_workspace` (same real assertions - breakout/trap cards, squad
exclusion, empty state), monkeypatch targets moved to the `opportunity` module (where
`find_breakouts`/`find_traps` are now actually imported and called from). 8 new direct unit
tests added for `intelligence.py` (`_signal_arrow`, `_leading_trend`'s noise-skipping, the
skip-when-no-real-signal guard, real-field rendering including the arrow/confidence/squad-tag).
Full suite: 1014/1014 (1008 Phase-1 baseline + 6 net new).

## Live verification

Real production DB (`fpl dashboard` regen, ~1 minute wall-clock - unchanged from the Phase-1/
pre-redesign baseline despite the new league-wide `team_outlook` calls across all ~20 teams and
the extra per-fixture `fixture_difficulty` calls in the Fixture Tool). Screenshots via the
Claude Browser tool at desktop (1280px) and mobile (375px): Intelligence workspace showing real
per-team cards (Arsenal/Brighton/Brentford/Chelsea/... with real shot/xG evidence, real FPL
implications, color-coded HIGH/MEDIUM/LOW confidence, "YOUR SQUAD" tags); Opportunity board
showing all 5 categories with real candidates and "N more" expanders; Market showing a real
model-vs-consensus divergence table; Fixture Tool's Attack metric + 8-GW range buttons clicked
and verified to actually re-render the grid (columns went from 5 to 8, metric button state
updated) with the honest attack/defence-fallback banner visible. Zero console errors throughout.
Confirmed (again) that several "blank screenshot" results mid-session were a transient Browser
Pane compositor timing quirk, not real rendering bugs — `getBoundingClientRect`/`innerText`
checks via `javascript_tool` proved real content was present and correctly laid out each time,
and a retry/re-scroll always produced a correct screenshot.

## Known gaps / deferred

Same three items already listed as Phase 3 in `docs/PROJECT_STATE.md`: full `legacy.py` module
decomposition (still ~4500 lines - Advanced drawer, Live Tracking, Team Outlook's own richer
table, Match Intelligence), Squad's projected-GW previews are still text rows not shirt tiles,
and Fixture Tool's Attack/Defence metrics are honestly coincident with Overall until FPL
publishes the real split (mechanism is real and correct, data isn't available yet).
