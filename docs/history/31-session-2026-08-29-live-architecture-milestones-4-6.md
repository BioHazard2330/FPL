# Session 2026-08-29: live architecture rebuild, milestones 4-6

Continuation of the "live architecture rebuild" spec (milestone 1: event
bus + fast engine; 2: SSE transport; 3: reactive materiality engine).
User said "continue everything left" after milestone 3's report offered
three remaining real candidates - all three closed in this single
continuation.

## Milestone 4: decision hysteresis (spec section 11)

Real gap: `strategic_planner.latest_strategic_plan_with_recommendation`
(the established single choke point for "the authoritative current
decision", built in an earlier session) returns the LATEST complete
`strategic_plan` decision unconditionally - and since milestone 3 made
recomputation reactive (fires the instant a materiality-gated event
lands, not just once per `run_scheduled` tick), a real recompute now
happens more often, with zero check for whether a nominal winner change
was actually meaningful versus real beam-search noise (this project's own
prior search-width experiment measured <1.2pt tail variation between
beam widths - real, quantified noise, not a hypothetical).

New `models/decision_hysteresis.py::stable_current_recommendation` -
requires ONE of: a real minimum EV advantage (5.0 full-horizon path_total
points, a disclosed hand-picked threshold, not statistically calibrated),
a real confidence floor (the new candidate's own `evidence_confidence`
must be MEDIUM+ - reusing `decision_analysis.py`'s existing bar, not a new
one), or real persistence (the new label must be the top real
recommendation across >=2 consecutive complete decisions) before
replacing an already-stable recommendation. Every real decision still
gets computed and logged exactly as before - full audit trail unchanged,
`fpl decision-changes`/`decision-audit` still see every real transition.

Wired into exactly ONE real call site:
`monitoring/dashboard/legacy.py::_compute_primary_verdict` (the Home
hero's single authoritative verdict - the actual place a flip-flopping
recommendation would be visibly annoying). Deliberately NOT wired into
`live_snapshot.py`'s freshness/change-explanation or `adversarial_audit.py`'s
cross-check - both legitimately want the raw, unfiltered latest decision
for their own real purposes (staleness detection, robustness testing).

8 new tests (`test_decision_hysteresis.py`) covering all three real gates
independently, persistence-eventually-flips, a sandwiched incomplete
(`--no-current-action`) run not corrupting the persistence count, and the
empty-history case. Confirmed via the full dashboard test suite that
wiring this into `_compute_primary_verdict` introduced zero regressions.

## Milestone 5: render the SSE live-changes feed

Milestone 2 built the `change_event`/`match_event` SSE channels but left
them unrendered (a disclosed follow-up, flagged specifically because of
double-counting risk against the existing poll-based feed). Resolved by
reusing the EXACT SAME real dedup key the poll-based `pushLiveChanges`
already uses for `change_event` (`'chg:'+entity_id+':'+detected_at`,
requiring the tailer's `_poll_change_events` to gain the same real
`LEFT JOIN players` the poll-based `_recent_changes_block` already has,
for a real player name instead of a bare id) - the SSE-delivered and
later poll-delivered versions of the SAME real row now genuinely dedupe
via the existing `seenFeedKeys` set. `match_event` (FotMob's own richer
per-incident description, e.g. "Goal — Erling Haaland (assist by Phil
Foden)") is genuinely additive information versus the FPL-live-bonus-
derived cumulative counts the poll feed already shows - keyed off the
real `match_events.id` (added to the tailer's broadcast payload) so a
later poll cycle can never reintroduce the same real row twice either.

## Milestone 6: provider abstraction (spec: "swappable provider")

Resolved earlier this session (a direct clarifying question): a real,
paid "authorized" provider conflicts with this project's own standing
free-resources-only rule - FotMob stays the sole real implementation,
wrapped behind a real interface.

New `providers/football.py` - `FootballDataProvider` (a `typing.Protocol`,
not an ABC - structural typing needs no inheritance, the lowest-friction
option for a project with no DI framework) and `FotMobProvider`, a real
class wrapping the existing `ingestion/fotmob_source.py` module functions.
Each method does a DYNAMIC module lookup (`from fpl_agent.ingestion import
fotmob_source; return fotmob_source.find_match(...)`) rather than
capturing a bound reference at import time - this is what keeps this
project's own existing `monkeypatch.setattr(fotmob_mod, "find_match",
...)` test pattern working unchanged for any caller that goes through the
provider instead of the bare function (confirmed empirically: all 24
pre-existing `fotmob_source`/match-intelligence tests still pass
unmodified after this wiring).

Real finding while building the FPL-side equivalent: `ingestion/
fpl_api.py::FPLApiAdapter` (built in an earlier session) ALREADY is a
genuine, well-shaped provider class - bootstrap/fixtures/live/entry-picks/
entry-info/entry-history, all real, no key needed. `providers/fpl.py`
does not reimplement it - `FplDataProvider` is a real `Protocol` stating
the contract it already satisfies, aliased as `OfficialFplProvider` with
zero new code.

`sync_match` gained an optional `provider: FootballDataProvider | None =
None` parameter (defaults to `FotMobProvider()` - 100% backward
compatible for every pre-existing call site). Real proof of genuine
swappability (not a decorative interface nobody uses): a completely
custom fake provider, injected via this new parameter, is empirically
confirmed to be what `sync_match` actually calls - the real FotMob module
functions are never touched when a fake is supplied.

5 new tests (`test_providers.py`): both concrete providers structurally
satisfy their real Protocols, `FotMobProvider`'s dynamic-lookup behavior
proven directly, a fake provider proven to be genuinely used by
`sync_match`, and the real default-provider backward-compatibility path
proven unchanged.

## Tests

Full suite green (exact count in this session's `PROJECT_STATE.md` entry) -
13 new this continuation (8 hysteresis + 5 providers), on top of the
dashboard/SSE regression suites re-run to confirm zero breakage from the
hysteresis wiring and the SSE feed-rendering payload changes (added `id`
to `match_event` broadcasts, added the `players` join + `web_name` to
`change_event` broadcasts).

## Genuinely still open (real, disclosed)

Real production verification against a genuinely live match with the
full pipeline (event bus -> fast engine -> materiality engine -> reactive
recompute -> hysteresis -> SSE -> browser) active end-to-end - no GW was
live this entire session (matches were scheduled for "this evening" per
the user's own note at the start of this whole thread). FPL_POINTS_CHANGED/
BONUS_CHANGED event types are defined in the milestone-1 vocabulary but
not actually published anywhere - FPL's own live endpoint remains the
authoritative, directly-read source for those fields (`live_snapshot.py`),
never re-derived as bus events this pass. End-to-end latency
instrumentation (spec section 15 - provider/ingestion/state/optimizer/
browser-receipt/browser-render timestamps) not built. The Task Scheduler
entry for `live-server` remains prepared, not registered.
