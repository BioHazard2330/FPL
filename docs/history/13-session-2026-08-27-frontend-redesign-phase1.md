# 2026-08-27: Frontend redesign Phase 1 — HOME/PLAN/SQUAD workspaces

Direct user instruction: stop patching the dashboard's CSS/copy and rebuild the frontend's
information architecture, interaction model, and visual composition, benchmarked against
fpl.page (product/UI quality) and FPL Copilot (strategic UX) — "genuinely different frontend
experience," not another analytics-dashboard skin. Backend/optimizer explicitly untouched;
this is presentation-layer only. Brainstormed (architectural path), user approved with four
corrections before implementation: (1) the embedded JSON payload carries one authoritative
decision snapshot, never a second competing computation; (2) payload minimal/purpose-built,
not a DB dump; (3) human-readable copy generated from structured reasoning facts, never
regex-cleaned prose (the existing `_humanize` pattern-substitution pass stays only for
legacy Advanced-drawer prose); (4) every visual affordance genuinely interactive or removed.
Spec doc: `docs/superpowers/specs/2026-08-27-frontend-redesign-design.md`.

Scoped into two phases (user's own choice from the phasing question): Phase 1 = HOME + PLAN +
SQUAD + nav shell + module split (this session). Phase 2 (not started) = INTELLIGENCE/
OPPORTUNITY/MARKET/FIXTURES workspaces properly re-skinned into the new IA; they currently
stay on their pre-existing legacy markup, reachable via secondary nav links, functionally
unchanged.

## Safety checkpoint before the redesign

Found substantial uncommitted work already in the working tree at session start (a prior
session's always-on LiveFPL live-rank source + dashboard decision-object consolidation,
1633-line diff on `dashboard.py` alone, never committed) — full suite green (990/990),
committed as a checkpoint (`eedbc4a`) before starting the restructure, excluding scratch/debug
files (`data/ffp_raw.html`, `perf_*.txt`) that weren't real source.

## Module split

`monitoring/dashboard.py` (6072 lines, single file, pure server-side string templating, zero
client interactivity beyond a few standalone scripts) became a package:
`monitoring/dashboard/legacy.py` (the file, renamed via `git mv`, unchanged content) +
`__init__.py` (re-exports only the real public API — `generate_dashboard_html`,
`_REFRESH_SECONDS` — the two names `cli/main.py` imports) + four new modules
(`data_payload.py`, `home.py`, `plan.py`, `squad.py`) + `assemble.py` (the new orchestrator,
`generate_dashboard_html` itself moved and rewritten here). This is a coarser split than the
originally-sketched `shared.py`/full per-concern breakdown — a pragmatic first cut given the
scale (retroactively re-homing ~40 existing helpers would have been a much larger, higher-risk
diff for no behavioral benefit this phase); new code lives in its own focused files, legacy
code stays together for now, real full decomposition is natural Phase 2 work alongside
Intelligence/Opportunity/Market/Fixtures.

Retired (not just left unused) since their whole job was superseded: `_strategic_plan_html`
(old Primary Decision panel), `_strategy_explorer_html` (old 5-tab explorer), and the old
`_squad_state_machine_html` composer — 435 lines deleted from `legacy.py`. Their real
low-level reusable pieces (`_squad_state_by_event`, `_bulk_player_lookup`,
`_squad_state_block_body_html`, `_compute_primary_verdict`, `_normalize_strategic_detail`)
were kept and are now called directly from the new modules. `_confidence_strip_html`/
`_model_football_conflict_html`/`_alternatives_html`/`_decision_comparison_html`/
`_decision_audit_html` (previously only reachable from the deleted Primary Decision panel)
were rewired into a new Advanced → "Decision Detail" drawer rather than left dead.

## New workspaces

**HOME** (`home.py`) — first viewport, six metrics only (Actual GW points when real,
Next-GW xP, Bank, Free Transfers, Captain, Rank), one structured-fact reason sentence, a
second structured-fact CAPTAIN KEEP/CHANGE/REVIEW line. The old hero's long "what would
change this" prose block, and the Vice/Squad-value/Risks/Next-kickoff/Optimizer-status strip,
were removed from Home (not deleted from the system — squad value/vice live in Squad's own
header now, risks/kickoff/optimizer detail were genuinely secondary and are recoverable from
Live/Advanced if ever needed again).

**PLAN** (`plan.py`) — 5 real strategy-choice boxes (score/delta-vs-roll/confidence/one-line
descriptor) above a GW-by-GW timeline with visually emphasized decision weeks
(`.timeline-node-decision`, bold/bordered) vs quiet roll weeks (`.timeline-node-roll`, small/
muted) — supersedes the old Strategy Explorer's plain path-tab-and-track. `confidence`
(`path_confidence`) reuses `models.projection_confidence.assess_projection_confidence` on the
path's own first real transfer pair — no new model. `descriptor` (`path_descriptor`) is plain
string composition over the already-computed step list (real path-diversity clustering stays
tracked separately in PROJECT_STATE.md's "next work," not built this session — this is just a
label, not a new backend capability). A real visual-QA finding fixed same-session: when paths
are flagged "statistically equivalent," the previously-selected path box got a solid brand-
green fill that visually read as "the answer" while its own subtitle said the opposite —
changed to a bordered "currently viewing" outline for any tied leader instead of a solid fill.

**SQUAD** (`squad.py`) — CURRENT/GW2..GWn pill switcher. CURRENT stays the real, full-detail
pitch (unchanged `_pitch_html_from_xi`/`_pitch_html`) — the only view with real per-player
floor/ceiling/confidence/live points, since it's the only one an optimizer/live-data pass has
actually run against. Selecting a future GW shows the real reconstructed 15-man squad for
that point in the plan (real transfer/chip replay, `_squad_state_by_event`) grouped by
position, with an explicit, honest disclosure that captain/vice/XI arrangement and per-GW
point projections aren't re-solved for a hypothetical future squad — re-solving a real XI/
points projection per projected GW per path on every dashboard regen would need real extra
optimizer calls this project's own performance budget (regen currently ~1 minute) doesn't
support; disclosed rather than faked.

**Data payload** (`data_payload.py`) — one `<script type="application/json">` blob per the
approved corrections: `decision` (a handful of fields straight off the single cached
`CurrentRecommendation`), `paths` (id/label/score/delta/confidence/descriptor/steps, from the
same cached `strategic_plan` paths every other panel reads), `players` (name/team/position/
price only, for every id referenced by a path step). Verified by test to carry exactly those
keys, nothing more. `<` is escaped to `<` before embedding so no payload value can ever
prematurely close the `<script>` tag.

**Nav** — HOME/PLAN/SQUAD/INTELLIGENCE/MARKET primary; OPPORTUNITIES/FIXTURES/ADVANCED
secondary (smaller, visually deprioritized). No more `#decision`/`#explore` backend-taxonomy
anchors.

## Real bug found and fixed same-session (visual QA, not a test failure)

`html { font-size: 18px }` — a root-level override the whole legacy stylesheet's `rem` values
were tuned against — is exactly the anti-pattern the user's own spec named ("do not use
html{font-size:18px} as the solution... create a real type hierarchy"). Removed; body text
now resolves to a real 16px (top of the spec's 14-16px band) and every other element's real,
already-varied rem value is restored to its own intended size — no rem values themselves
touched, the hierarchy was already real, just uniformly inflated by one hack.

## Testing

117 pre-existing dashboard tests: import paths updated to the real submodule
(`fpl_agent.monitoring.dashboard.legacy`/`.assemble`, not the package root, which now only
re-exports the two public names) — 4 top-level import blocks + ~15 inline per-test imports +
7 `monkeypatch.setattr(dash_mod, ...)` targets retargeted to whichever submodule the patched
function is actually resolved from at call time. 6 tests exercising the retired
`_strategic_plan_html`/`_strategy_explorer_html` rewritten against `plan.render_plan_workspace`
directly (same real assertions: tied-group detection, chip badges, empty states,
backward-compat with an older decision missing `path_total`). 2 tests asserting old exact
markup/ordering (`id="decision"`, Live-before-Squad reordering, a literal `<strong>CAPTAIN`
badge string) updated to the new real, deliberately-changed behavior (Squad is now a fixed
top-level workspace, not reordered by match state; the captain verdict is a structured-fact
sentence in Home, not a badge in the old Primary Decision panel). New file
`test_dashboard_workspaces.py` (18 tests): `home.py`'s copy-composition functions (roll/
transfer/chip/review cases, escaping of untrusted player names), `plan.py`'s
descriptor/confidence functions, `data_payload.py`'s payload-shape/minimality/script-escaping.
Full suite: 1008/1008 (990 pre-existing + 18 new), no test count inflation beyond the new
modules' own real coverage.

## Live verification

Real production DB (`fpl dashboard` regen, served over `python -m http.server` on `data/`,
inspected via the Claude Browser tool — read_page/get_page_text/console/computed-style checks
plus real screenshots once the pane's compositor came up, matching the exact blocker
PROJECT_STATE.md flagged on 2026-08-27 as unresolved in an earlier session): zero console
errors; real GW2 data end-to-end (PLAY CHIP headline, "Play Wildcard is the strongest move
over your horizon," captain change Haaland → Mbeumo +0.9xP, 5 real tied strategy paths at
+642.1 projected, real 8-GW timeline with real transfer/chip steps, real CURRENT pitch with
real per-player stats, real GW3 projected-squad click showing OUT Gabriel / IN Guéhi). Path-
selection/GW-selection click interactivity verified live (clicking a GW pill in Squad
correctly swapped CURRENT for the real projected 15). Mobile (375×812) reflow checked —
hero/metrics/plan-cards all reflow correctly; nav becomes a horizontally-scrolling strip
(same pattern fpl.page's own mobile nav uses), acceptable but no scroll-affordance fade yet
(noted as a future polish item, not a defect).

## Known gaps / deferred (disclosed, not hidden)

- Phase 2 (Intelligence/Opportunity/Market/Fixtures workspaces, full legacy module
  decomposition) not started.
- Squad's future-GW previews are text/row-grouped-by-position, not shirt tiles on a pitch
  graphic (spec asked for a pitch visualization; the honest-XI/points constraint above meant
  the achievable Phase-1 scope was the real-squad-composition view, not the full pitch
  chrome) — a real visual upgrade candidate for Phase 2, not a data-honesty issue.
- The chip-timeline badge on Plan can show a chip name (e.g. FREEHIT) different from the
  actual joint-search action at that node (e.g. PLAY WILDCARD) — this is the pre-existing
  `chip_schedule` independent-cross-check overlay, inherited unchanged from before the
  redesign (documented in its own code comment: "checked against the winning transfer path
  after it's chosen, not jointly searched with it"), not something the frontend swap
  introduced or was asked to fix.
- Path-diversity clustering (grouping near-identical top-N paths into real tiers) stays
  unbuilt, same as before this session — `descriptor`/`confidence` are presentation labels
  over the existing search output, not a new clustering model.
