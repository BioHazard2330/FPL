# Session 2026-08-29: forensic visual/product redesign pass

Direct user instruction after the live-architecture rebuild closed out:
"the backend is now functionally complete. Do not add architecture. Perform
a forensic visual/product redesign of the rendered dashboard using
FPL.page as the primary reference... inspect screenshots before changing
anything and verify the resulting screenshots at all breakpoints." A pure
CSS/markup pass - no optimizer/decision-layer/architecture code touched.

## Baseline

Regenerated the real production dashboard, opened `https://fpl.page/` and
this project's own dashboard side by side at 1440x1000 via a real
localhost server (never `file://`, per this project's own standing rule).
fpl.page's real conventions: black rounded-corner cards on a lighter page
background, bold uppercase tracked headers, real data tables with
semantic-coloured pills and embedded progress bars, small crests, a
restrained one-accent-plus-semantic-colours palette. Diagnosed the single
biggest "generated engineering dashboard" tell as the System Live strip -
7-8 tiny grey telemetry fields crammed onto one line directly under the
nav bar, competing visually with the actual verdict below it.

## Changes

**System Live strip** (`monitoring/dashboard/home.py::_system_live_html`,
both the populated and the `snapshot is None` fallback branch) - collapsed
into a compact primary status line plus a `<details class="system-live-
more">` disclosure holding every previously-inline field (snapshot age,
next check, rank age/next, news/projection age, degraded-source health).
Every existing element id preserved exactly (`system-live-dot`,
`system-live-snapshot-age`, etc.) - the JS in `assemble.py` targets these
via `getElementById` regardless of DOM nesting, confirmed unaffected.
Corresponding CSS in `assemble.py` rewritten for the new primary-line +
collapsed-grid layout, including a `max-width:480px` mobile rule.

**Hero metrics / cross-check pills** (`assemble.py`) - `.home-hero-metrics`
gained a `border-top` divider and more breathing room; `.home-metric-value`
1.5rem->1.75rem, `.home-metric-value-muted` 1.05rem->1.15rem;
`.cross-check-tag` padding/font-size/radius bumped slightly for legibility.

**Type scale tokens** (`legacy.py` `:root`) - added `--fs-2xs` through
`--fs-xl` (0.68rem-2rem). A real, bounded fix for this file's own
confirmed problem (dozens of near-duplicate ad hoc rem values scattered
with no shared scale) - NOT a mechanical whole-file rename (too large a
blast radius to verify visually in one pass); applied to the panels
actively touched this pass (Match Centre). The remaining scattered
literals elsewhere in the file are a real, disclosed follow-up.

**Match Centre** (`legacy.py` CSS, `match_centre.py` markup unchanged) -
re-audited against fpl.page specifically via the project's own established
"temporarily flip a real finished match's status to LIVE, regenerate,
screenshot, revert" technique (match 5795429, Crystal Palace vs Man City).
Card gained a real border + header divider; badges changed from bordered
outline circles to real team-colour-filled circles (reads as a genuine
badge, not a stray initial); stat bars changed from opaque 4px-radius
blocks to pill-shaped, 0.65-opacity bars (the original full-opacity block
read as a game progress bar, not a professional stat comparison); row
spacing loosened slightly. Momentum chart and shot map (built in an
earlier session's "each and every fucking problem" pass) were re-verified
via real screenshot and confirmed already solid - proportional filled area
chart with real minute gridlines, full two-half pitch with real
outcome-coloured shot dots and a legend. No changes needed there.

**Real bug hunt during the Match Centre re-audit**: re-syncing match
5795429 (`fpl sync-match "Crystal Palace" "Man City" --date 2026-08-28`,
safe to re-run) to restore its real FULL_TIME status after the temporary
flip surfaced two things that looked like bugs but weren't:
1. Several Substitution rows' `description` still read as bare
   "Substitution" with no names - confirmed this is REAL data staleness
   (these `match_events` rows were inserted before the swap[0]/swap[1]
   name-parsing fix landed earlier this session and were never
   retroactively re-synced), not a live regression - the same class of
   issue as the already-disclosed Understat historical-repair backlog.
   The re-sync itself repaired most of them in place; one row at the 90th
   minute still shows bare "Substitution" - genuinely missing swap data
   in FotMob's own payload for that specific incident, not fabricatable.
2. Names like "J�rgen Strand Larsen" printing garbled in the terminal -
   verified via `repr()`/raw bytes that the actual stored string is
   correct UTF-8 (`\xc3\xb8` = "ø"); purely this Windows terminal's own
   codepage failing to render it, never a real storage or rendering bug
   (the browser renders it correctly as real UTF-8 HTML).

**Nav bar horizontal-scroll affordance** (`legacy.py` `.site-nav`) - the
sticky section nav is deliberately horizontally-scrollable below ~900px
(a real, intentional prior-session choice - fpl.page's own button-nav
serves a different structural role, not directly ported) but had zero
visual cue that more tabs exist off-screen. Added a right-edge
`mask-image` fade (with `-webkit-` prefix, degrades harmlessly with no
mask support) - confirmed live at 768px that the last visible tab now
fades rather than hard-clipping.

## Responsive sweep

Screenshotted the real localhost-served dashboard at 1440, 1024, 768, and
390px. 1440/1024 unchanged in structure, confirmed no regressions from the
CSS edits above. 768 was the one real finding (nav overflow with no fade,
fixed above). 390 (mobile) already reflows cleanly - hero metrics to a
2-column grid, Plan path cards and the GW-by-GW strategy timeline to a
single column with connector lines intact, no horizontal overflow
anywhere checked.

## Genuinely still open (real, disclosed)

The type-scale tokens were applied to Match Centre only this pass, not
mechanically across the whole ~4500-line `legacy.py` - the broader ad hoc
rem-value inconsistency across every other panel (Squad/Intelligence/
Market/Opportunities/Fixtures/Advanced) is real and unaddressed, a
legitimate larger follow-up, not attempted under this pass's scope. Live
Tracking rows and the squad pitch/player-card view were reviewed via
screenshot and judged already solid (two-tier row hierarchy, team-coloured
jerseys, clean line charts) from an earlier session's redesign pass - not
touched further this session since no real deficiency was found against
fpl.page specifically. No genuinely LIVE match existed at any point this
session (all real fixtures today are PRE_MATCH) - the Match Centre re-
audit used the disclosed temporary-flip technique on a finished match, the
same pattern used earlier this project for the same reason.
