# Session 2026-09-19 (continuation) — the Atlas rebuilt, the player file, and the table

User, verbatim: *"this atlas shit is bugged too i cant even see the players
shots when i click it. and where are the aesthetics? i want you to blow my
mind away with creativity, aesthetics, peak football etc etc. this is not
enough."*

Two complaints, both fair. The first was a real defect: clicking a shooter
on THE ATLAS technically filtered to him, but his dots stayed the same size
and colour as everyone else's and were dimmed by the entrance transition,
so the isolation was invisible among 1,100 dimmed dots. The second was the
standing brief this whole day has been about.

## THE ATLAS, rebuilt

- **Hero mode.** Click a shooter and he is the only thing on the pitch:
  white dots at 1.55× with minute labels, a second ring on each goal, a
  dashed gold halo on his biggest chance. A hero band above with his shirt,
  name, shots / xG / goals / goals-minus-xG, biggest chance and coldest
  finish. Verified live for Haaland (16 shots, 3.2 xG, 4 goals, +0.8;
  biggest 0.49 at 75' saved; coldest 0.08 at 17').
- **Turf.** Striped grass, chalk at 16.5 / 5.5 / 11 / 9.15 m, a net.
- **Heat.** A gaussian shot-density field. Three attempts to get it
  readable, all recorded because each was a real lesson: (1) the canvas
  was drawn inside a `<foreignObject>` and Chrome placed it at the wrong
  scale once the viewBox had a non-zero origin — it rendered half a pitch
  off; now painted offscreen and placed as an SVG `<image>` in the same
  metre frame. (2) A linear colour ramp collapsed the whole field into one
  hot spot under the six-yard box; now square-root compressed. (3) Green
  heat on green turf was invisible; heat mode now drains the turf to slate
  so the field is the only green on the pitch, and dots step back to 0.22.
- **Story strip.** Biggest chances not taken and coldest finishes, league
  or your squad.
- **The request no longer blocks.** `/api/atlas` and `/api/receipts` had
  been queueing 30–130 s behind a `DashboardContext` rebuild they never
  read. Builders can now declare `needs_context = False` and are served
  from a light context (locked squad ids only); the cache also serves a
  stale context when inputs moved and lets the refresh loop rebuild.
  Cold `/api/atlas`: 4.4 s → now ~20 ms of work.

## THE PLAYER FILE — three sections that did not exist

Every one built from data the database already held and the app had never
drawn for one player.

- **WHERE HE SHOOTS.** His season's shots as Atlas hero dots over the
  league's density field ("does he shoot from where goals come from"),
  with per-situation and per-match breakdowns linking to the match page.
- **THE RACE.** Cumulative goals against cumulative xG — or assists v xA —
  across every match on record, up to six seasons of Understat rows. The
  gap between the step and the line is filled green while he runs above
  his chances and red below; season boundaries marked; hover reads the
  match. Haaland: 116 from 120.6 over five seasons (−4.6, below his
  chances). Bruno Fernandes: 48 from 53.6.
- **THE MARKET.** Official ownership as it moved, and the per-gameweek
  transfer in/out counters as sampled every sync, mirrored around zero so
  each gameweek is its own sawtooth, deadlines marked. Haaland: 73.3%
  owned, 8k in / 1k out so far this gameweek. Sampled, not continuous — a
  gap is a gap in this project's own sync and is never filled.

Player and club profiles also opt out of the full context: a player page
answers in ~10 ms instead of waiting behind a rebuild. The per-match xG/xA
ApexCharts bars were removed; the race supersedes them.

## THE TABLE — a new screen

`/table` under THE FOOTBALL. Top, **THE QUADRANT**: twenty crests by xG
created per match against xG allowed per match, the league average as a
dashed cross, the four corners labelled, a gold ring on any club you own
players from, hover for the card, click to the club file. It is the one
picture that says which attacks are real and which defences to target.
Below, the table with real goals beside the xG that produced them —
**FINISHING** (goals minus xG) and **KEEPING** (xG allowed minus conceded)
as diverging bars, sortable.

One honesty rule enforced in the payload and caught by its own test:
finishing and keeping compare goals over *the matches that carry an xG
row* against xG over those same matches. The first cut compared all-match
goals against xG-match xG — with one xG-less match the test read a
keeping of −0.5 where +0.5 was true. Today every one of the 40 finished
fixtures carries xG, so the live numbers were unaffected, but the
denominator is now the same on both sides by construction.

## Also this session

- Processed the queued Spurs 2–3 Villa full-time analysis (job 69): Villa
  3 from 1.16 xG on 36% possession with three fast-break shots; Spurs 20
  shots for 1.0 xG, 11 of them set pieces; Kudus' 60' "goal" at 0.95 xG
  treated as disallowed (VAR event at 60', player row 0 goals) and
  recorded as an uncertainty rather than credited.
- Restarting the live server with a PowerShell one-liner that filtered on
  `CommandLine -like '*live-server*'` killed the PowerShell process itself
  (its own command line matched). Filter on the image name too.

## Open

- Club file gained its two pitches after this entry was first written
  (WHERE THEY SHOOT / WHERE THEY CONCEDE, the conceded set drawn on the
  same half from the opponent's end; Arsenal: 55 shots for at 7.0 xG,
  42 faced at 3.2). A club-level xG race is not built — four matches per
  club is too short a line to mean anything yet.
- Crests on the quadrant overlap where four clubs sit near the average;
  hover dims the rest, but no de-overlap is attempted (a jitter would
  misplace real values).
- Everything listed as open in `54-…` still stands: n=3 ledger, generic
  "why" line under a ROLL hero, free hit in the MILP, purchase price, the
  MILP not yet in the live decision path.
