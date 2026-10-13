# Session 2026-10-13 — catching up: 19 unanalysed matches, a result-visibility gap, unresolved players

User, verbatim: *"see what all qualitative analysis youve missed to date.
update everything. i still think the optimizer is garbage btw but it is what
is focus on updating everything till todays date"*

The last session ended 2026-09-19. Twenty-four days of football had landed
without anyone running the one manual step in the pipeline: the qualitative
match-analysis reasoning (`fpl match-analyze`), which by design only happens
inside a Claude Code session.

## What had been missed

`fpl analysis-queue` listed 18 pending FULL_TIME jobs (8 from GW5, 10 from
GW6). A sweep of finished fixtures against `match_intelligence` found a 19th
that was not in the queue at all: **Brentford 3-0 Chelsea (GW5, 2026-09-18)**
had no `match_intelligence` row, so no job, no detector evidence, no analysis.
`discover_and_register_matches` only looks inside a rolling window around
"now"; a match that kicks off while the sync daemon is down never re-enters
that window. Registered by hand (`fpl sync-match Brentford Chelsea --date
2026-09-18`), which created job 106. All 19 are now analysed; 60 jobs done, 0
pending (46 HALFTIME jobs skipped by design).

Written against the `SHOTS`/`EVENTS` sections and the player table, per the
`match-intelligence-analysis` skill's 2026-09-12 rule that an `inferred` field
must say something `observed` does not. Each payload went through the same
validated write path as `fpl match-analyze` (`apply_match_analysis` +
`mark_job_done_for_match_phase`), batched so the ~8-minute dashboard regen and
strategic-plan trigger that `match-analyze` runs per match happened once at the
end instead of 19 times.

## What the batch turned up (all from the feeds, none from memory)

**Suspensions and injuries, matched against FPL's own status field today:**
Struijk (BHA) carded at 57' v Sunderland (team red_cards=1), suspended until 25 Oct; Gravenberch
(LIV) second yellow at 62' v Man City, suspended until 25 Oct; Bentancur (TOT)
dismissed at 78' v Man Utd, suspended until 7 Nov. Substitutions at 35', 46'
and 52' with no card and no scoreline reason all lined up with injury flags:
Meunier (SUN) groin 75%, Schuster (BRE) ankle 75%, Schade (BRE) shoulder 75%,
Ruggeri (AVL) hamstring 25%. Brobbey (SUN), who scored a hat-trick from 2.91
xG at Man City, is now listed hamstring, back 25 Oct. Szoboszlai (LIV) is
listed hamstring 75% and appears in the Man City match as a starter with no
stats and no rating — his minutes are not established.

**Finishing against chance quality, the pattern that decided the weekend.**
Chelsea 5-1 Bournemouth came from 1.08 xG (5 of 6 on-target shots scored).
Man City 5-3 Sunderland: Sunderland created 4.32 xG and lost. Forest had 2.97
xG, 24 shots and 8 big chances (7 missed) and lost 3-1 at Palace. Everton
missed 6 of 8 big chances, including a 0.91 xG miss from Barry, and drew 2-2
at Hull. Coventry beat Newcastle 4-1 from 1.47 xG including a 0.79 penalty
on 33% possession.

**Four VAR-disallowed goals** recorded as uncertainties instead of credited:
Barry 58' (EVE-IPS), Igor Jesus 86' (NFO-COV), Mitchell 52' (LEE-CRY) and
Johnson 34' (HUL-EVE). The shot feed logs
each as `outcome=Goal` with the VAR event beside it; the player row's goals
count is the tie-breaker.

**Your squad in this batch.** Calafiori scored from a 0.67 xG six-yard chance
(ARS 2-1 LEE) after Arsenal lost 0-3 at Brighton; Haaland 1.09 xG in GW5 and a
goal from 0.05 xG at Anfield; João Pedro two goals from 0.58 xG; Palmer an
assist inside 2 minutes; Gvardiol assists in both City matches while
conceding 3 in one; Gibbs-White 0.32 xA with no return in a match his team
missed 7 of 8 big chances; Verbruggen two clean sheets (against 1.47 xG and
0.64 xG, the second with Brighton down to 10 men).

## Feed inconsistencies worth knowing about

- **`player_match_state.minutes` was NULL for every starter** in 9 of 60
  FULL_TIME matches (TOT-EVE, MUN-MCI, NFO-COV, AVL-BRE, CHE-BOU, IPS-FUL,
  MUN-TOT, HUL-EVE, LIV-MCI). A FULL_TIME match is captured the moment the
  whistle goes, FotMob has no per-player minutes yet, and nothing ever
  re-fetches a FULL_TIME match, so the NULLs were permanent. The analyses for
  the affected matches say so and used substitution events for minutes; the
  minutes have since been backfilled by re-syncing (see below).
- **Player-row totals can lag the shot table.** Saka's 90' shot (0.37 xG),
  Mbeumo's 85' shot, Ndiaye's 50' shot (0.74 xG) and Barnes' 63' shot are in
  `match_shots` but not in the player row or the team xG. Barry's row says 5
  shots / 0.90 xG; the shot table lists 6 summing to 1.81.
- Own goals are logged as a shot by the scorer (Lisandro Martínez, Man Utd,
  at pitch x=7 with `xg=NULL`), with the goal credited on the other side only
  in the event feed.

## Not what it looked like — three fixes along the way

**GW6 was missing from the new TABLE, club results and Matchweek standings.**
FPL's own API reports `finished: false, finished_provisional: true` for GW6
fixtures three days after kickoff — it keeps `finished = 0` until bonus is
confirmed. Every payload built last session on `fixtures.finished = 1`
silently dropped a whole gameweek of final scores (40 matches shown where 60
had been played). New `models/fixtures.py::PLAYED_FIXTURE_SQL` counts a
fixture as played when FPL says finished **or** FotMob says FULL_TIME — the
same two-signal rule `finished_fixture_ids_fast` already used per event. The
table now reads "through GW6, 60 matches, 60 with xG". Test added (a fixture
FPL has not finished only counts once FotMob confirms).

**Unresolved FotMob players.** 49 `player_match_state` rows had no FPL player
(24 distinct feed ids), including real contributors: Pino (Palace, 311
minutes), Nilson Angulo (Sunderland), Jacob Murphy and Nico González
(Newcastle), Bruno Guimarães (Arsenal, 2 goals in 79 minutes). They all exist
in FPL's data; `match_player_in_team` failed because the feed's first name is
spelled differently (Yéremi/Yéremy), the surname is the first word of
`second_name`, or two teammates share a surname so the last-word pass is
(correctly) ambiguous. New last-resort pass
`_initial_and_surname_match`: surname word in `second_name` and the same first
initial, accepted only when exactly one teammate fits. Backfilled by
re-syncing the 30 affected matches: 49 → 12 unresolved rows; the 12 left are
players whose FPL record is at a different club from the one FotMob listed
(Ndiaye at Everton, Daniel Muñoz at Palace), none above 90 minutes.
Existing behaviour not changed: a bare surname shared by two teammates still
resolves to the first row in pass 2 (feeds always send full names).

**My own batch used the filler words the skill forbids** — "genuine", "real"
as an intensifier, "sustained" — in six `fpl_reason`/`inferred` strings, and
invented "a 20-second phase" with no evidence for the duration. Caught by
grepping the table after writing, fixed in the payloads and re-submitted for
the five matches (idempotent per match and phase).

**Two pipeline gaps closed in `run-scheduled`** (tests added):
`discover_and_register_matches` now also registers a *played* fixture (FPL
started it or carries a score) from the last 14 days that has no
`match_intelligence` row; and new `resync_unsettled_full_time_matches`
re-fetches a FULL_TIME match from the last 10 days whose starters have no
minutes (capped at 5 per cycle; a FULL_TIME to FULL_TIME re-sync publishes no
event and enqueues no job). The nine affected matches were backfilled by hand:
starters missing minutes 23-25 per match down to 0-3.

## Open

- **27 of the 60 analyses contain the banned filler words** (148 of 386
  observations, every one for a match played on or before 2026-09-12) and 24
  matches carry 5 or fewer observations. They are the GW1-GW4 analyses written
  before the shot/event-detail rule existed; they feed the FOOTBALL and SCOUT evidence
  text. Not rewritten this session.
- Twelve unresolved FotMob rows from mid-season club moves.
- The ledger and the optimizer items listed as open in `54-…` are unchanged.
