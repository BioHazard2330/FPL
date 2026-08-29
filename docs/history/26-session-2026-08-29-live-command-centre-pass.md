# Session 2026-08-29: live command centre pass

Direct user ask: eliminate real live-data-delay bugs, make charts genuinely
readable, improve live match tracking, clean up the "SYSTEM LIVE" strip's
raw technical output, fix a real flat-vs-gradient design contradiction on
the Home hero. Explicitly out of scope: the statistical optimizer's math,
transfer/chip/captain logic, automating qualitative LLM analysis.

## Real bug found + fixed: "Next check" could reach 0s and stay there

Root cause traced in `assemble.py`'s live-poll script: `nextPollAt` (the
absolute timestamp driving the countdown) was only ever advanced inside
`applySnapshot`, which returns immediately when a fetch fails or the file
doesn't exist - a genuinely common state outside an active live match (the
file simply isn't written yet). One failed poll therefore froze the
countdown at 0 forever, exactly the user's reported symptom. Fixed:
`nextPollAt` now resets on every poll *attempt*; a real regression (poll
was succeeding, now consistently isn't) shows "delayed - retrying" instead
of a stuck number. Added a defensive out-of-order/stale-snapshot-version
guard per the same spec's requirement, though this poll loop never has two
fetches in flight at once so it's a floor, not a fix for a reproduced race.

## Real UI fix: raw source-name dump replaced with a readable summary

`home.py`/`assemble.py` used to render `"4 source(s) degraded:
fpl_api_my_team, livefpl, odds_api, odds_api_player_props"` directly in
primary UI. Built a real source-name -> plain-English impact map (`_SOURCE_IMPACT`
in `home.py`, mirrored in JS) from the actual `update_source_health` call
catalog across the codebase (grepped every real call site, not guessed) -
now shows `"Data health · N issue(s)"` collapsed, with the readable label +
raw technical name only visible on click/expand. **Self-caught regression**:
the first version rebuilt that element's `innerHTML` unconditionally on
every 1s strip tick, destroying the `<details>` open state and any in-flight
click - found live-verifying in a real browser (a stale-ref click error),
fixed by only touching the DOM when the real underlying issue list changes.

## Real chart-legibility fix

`live_charts.py`'s rank/points SVGs use `viewBox` + `preserveAspectRatio="none"`
with CSS `height:auto` and a `260px`-minimum grid column - at a real narrow
column width this could render as small as ~70-90px tall, exactly the
user's "charts rendered so small they're difficult to interpret" complaint.
Raised the intrinsic viewBox height (160->220), widened the grid's minimum
column (260px->420px, "two good charts beat four unreadable ones"), and
added a real `min-height: 240px` floor that clears both the desktop and
mobile targets from one rule. Added one-line purpose subtitles to the two
cards that lacked one. Live-verified at desktop (1440px, real 2-column
layout) and mobile (375px emulated, real single-column) - genuinely taller,
readable charts at both.

## Real design-contradiction fix: Home hero gradient

Found a real, confirmed contradiction: the header's own CSS comment says
"flat rebuild - a plain dark bar, no gradient" (2026-08-27), but the Home
hero still used `linear-gradient(180deg, purple, ...)`. Replaced with the
same flat `--surface-2` token the rest of the design language already uses,
plus a narrow left accent bar for brand identity - no full-bleed wash.
Fixed `.home-action-btn`'s hardcoded `#fff`/`rgba(255,255,255,...)` (a
latent light-theme bug this change would otherwise have newly exposed) to
theme-aware `var(--fg)`/`var(--border)`.

## Real FotMob data surfaced (no new scraping)

`fotmob_source.py::sync_match` already fetches and stores real per-player
`xg`/`xa`/`shots`/`key_passes` (migration 0023) and real per-team
`possession_pct`/`shots`/`shots_on_target`/`xg`/`corners` - neither was ever
displayed. Added both to the Match Intelligence live-match card:
`_match_your_players_html` now shows a squad player's real football stats
(kept conceptually separate from FPL scoring numbers, matching this
project's own FOOTBALL/FANTASY split rule), and a new `_match_stats_html`
renders a compact real home-vs-away possession/shots/xG/corners row.
Verified directly against the real production DB (GW2's Crystal Palace 1-4
Man City, Haaland's real 2 goals / 5 shots / 0.40 xG row).

Investigated per the spec's own FotMob checklist: momentum, shot-map
coordinates, and player heatmaps are **not** present in the currently
parsed schema (`models/match_intelligence.py`'s parsers don't extract
them) - not built this pass, real and disclosed rather than fabricated
placeholder coordinates.

## Real, honest limitation

No GW was actually LIVE during this session (GW2's one tracked match was
already FULL_TIME; other GW2 fixtures hadn't kicked off) - the spec's own
"3 real live polling cycles, minute advancing" acceptance test could not be
run against genuinely live match state. Verified everything the current
state allows instead: real `live_snapshot.json` 200s over multiple polls,
countdown ticking correctly, no page reloads, no console errors, DOM
patch-in-place confirmed via the existing Live Tracking row for the one
real finished match in the locked squad's fixture set.

Also observed once (not caused by this session's changes - confirmed by
immediately re-running `fpl dashboard` and getting the correct squad/GW2
state back): a single `fpl dashboard` regen produced a transient
"NO SQUAD"/GW1-unavailable render, consistent with this project's own
documented torn-read race class against a concurrently-running scheduled
task. Not chased further this pass - a real, disclosed, pre-existing
reliability edge, not a regression from this session's edits (none of
which touch squad-loading or GW-lifecycle code).

## Tests / verification

1245 tests pass (full suite). Real dashboard regen ~55s (no regression
from the documented ~1 minute baseline). Live-verified via a real
localhost-served `dashboard.html` at desktop (1440px) and mobile (375px,
emulated) - screenshots, console (zero errors), and network tab (real
`live_snapshot.json` 200 OK responses) all checked directly, not inferred
from DOM text.

## Not attempted this pass (real, disclosed, out of scope for one session)

Section U/V's hero-adapts-during-LIVE-state restructuring (de-emphasizing
the recommendation banner while matches are live) - a genuine, larger
layout change that needs live-match verification to confirm it doesn't
regress the pre-deadline view, and no GW was live this session to check
against. Match momentum/shot-map/heatmap widgets - the underlying FotMob
data isn't parsed by this project yet (see above). A full light/dark theme
QA pass beyond the specific hardcoded-color bug this session's own hero
edit would otherwise have introduced.
