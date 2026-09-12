---
name: match-intelligence-analysis
description: >
  Turns structured, real match-evidence rows (Match/PlayerMatchState/
  TeamMatchState from `fpl sync-match`) into qualitative tactical
  observations and FPL implications. Trigger: /match-report analysis,
  "analyze this match", "what does this mean for FPL".
---

# Match Intelligence Analysis

## Purpose

The ONLY place in this project's Match Intelligence Core (Pillar 4 Slice A)
that produces the INFERRED/FPL_IMPLICATION layer. Everything upstream
(`ingestion/fotmob_source.py`, `models/match_intelligence.py`) is
deterministic code and only ever writes OBSERVED facts (`player_match_state`/
`team_match_state`). This skill reads that structured evidence and writes
`match_observations`/`player_fpl_implications` - never the reverse. If you
find yourself writing a tactical claim without a specific evidence row behind
it, stop - that's fabrication, not analysis.

## Process

1. `.venv/Scripts/fpl.exe match-report <fotmob_match_id>` - read the real,
   current structured state, including its `status` field, its `SHOTS`
   section (real per-shot minute/type/situation/location/outcome) and its
   `EVENTS` section (real goal/card/substitution timeline). Analyze at the
   phase the match is actually in — never assume from wall-clock time.
   - `PRE_MATCH`/`LIVE`/`HALFTIME`: thin evidence is expected. Say so
     plainly, analyze only what's genuinely there, and keep everything
     explicitly provisional (see step 5).

### Shot & event detail is mandatory, not optional (2026-09-12, closes a real gap)

Direct user finding: production analysis was reading "1 goal, 2 shots, 0.72
xG" and writing an `inferred` field that just paraphrased the same three
numbers in words ("converted the match's single highest individual xG
shot") - restating OBSERVED as INFERRED, not analysis. That happened
because `match-report` didn't print shot-level detail at the time, so
`PLAYER STATES`' bare per-player aggregates were the only evidence on
screen. It now does (`SHOTS`/`EVENTS` sections) - use them. A real
`inferred` claim should be answerable from something in THOSE sections
that ISN'T already restated in `observed`:

- **Situation clustering**: do a team's/player's shots cluster in one
  `situation` (SetPiece/FromCorner/FreeKick/FastBreak/RegularPlay)? 3 of a
  team's first 4 shots all `SetPiece` inside the six-yard channel is a real,
  citable pattern - "converted a shot" is not.
- **Quality vs outcome mismatch**: a goal from a low `xg` shot (real
  finishing over-performance, or an error/deflection worth flagging as
  low-repeatability) vs a goal from a high `xg` shot (a genuinely created
  chance, more likely to recur) are different findings - `qual-v1`'s own
  example wrote "well above own recent baseline" for BOTH cases without
  distinguishing them.
- **Timing relative to game state/half**: a goal in the first 5 minutes of
  a half (kickoff momentum), right after a substitution, or in stoppage
  time under a chasing scoreline all mean something different for whether
  the underlying pattern repeats - `EVENTS`' minute column plus `period`
  tells you this for free.
- **Substitution reason**: `EVENTS`' real sub timing + which position came
  off tells you rotation (a 60' like-for-like swap with the game settled)
  vs a tactical change (two attacking subs at once while chasing a goal)
  vs an injury withdrawal (early, unplanned-looking minute) - never guess
  which without a real signal (scoreline at that minute, or a following
  formation/role change also in evidence), but don't skip the question.
- **Set-piece specialists**: a player with 2+ shots from `FromCorner`/
  `FreeKick`/`SetPiece` situations across the match is a real, citable
  set-piece role signal (delivery or attacking a specific ball), distinct
  from open-play threat.

If, after actually reading `SHOTS`/`EVENTS`, a match genuinely has nothing
beyond the aggregate (e.g. a 0-0 with 3 total speculative shots) - say that
plainly ("no real tactical pattern beyond low shot volume") rather than
inventing texture that isn't there. Thin evidence still gets an honest
"thin" verdict; it just has to be an HONEST verdict about the ACTUAL
shot/event detail, not one written without ever having looked at it.
   - `FULL_TIME`: the real, complete picture for this match. This is the
     only phase allowed to update `player_qualitative_state`/
     `team_qualitative_state` — `fpl match-analyze` enforces this itself
     (refuses a `full_time` write if the match isn't genuinely finished).
2. For each notable player/team row, reason through, in order:
   - **WHAT HAPPENED?** — restate the OBSERVED numbers only.
   - **WHY DID IT HAPPEN?** — a tactical read, grounded in the observed
     numbers (formation, minutes, goals/shots/xg, possession/team stats
     already in the row). This becomes INFERRED.
   - **WHAT CHANGED?** / **IS IT NEW?** — this slice has no history table
     (Tactical Memory is Slice B), so "new vs this player's normal" can only
     be answered if you have independent knowledge of their usual role;
     otherwise say "no baseline available yet."
   - **IS IT LIKELY TO PERSIST?** — a plain, hedged read (`"new signal"` /
     `"possible trend"` / `"insufficient sample"`), never a prediction
     dressed as certainty. GW1 specifically: never declare a persistent
     tactical trend from one match.
   - **DOES IT MATTER FOR FPL?** — direction (POSITIVE/NEUTRAL/NEGATIVE/WATCH)
     + signal (ROLE/MINUTES/CREATION/GOAL_THREAT/TEAM_ATTACK/FIXTURES/
     TACTICAL_CHANGE/SET_PIECES) + a one-line reason citing the evidence. If
     the evidence genuinely doesn't support a claim, write "insufficient
     evidence" as the observation and leave `fpl_direction` unset — never
     guess to fill the field.
3. Assign `confidence` honestly: `low` for anything from one match with thin
   stats, `medium`/`high` only when the evidence is genuinely unambiguous
   (e.g. a real goal, a real full 90 minutes started).
4. Write a JSON payload (schema below) to a scratch file, then persist it
   with `.venv/Scripts/fpl.exe match-analyze <fotmob_match_id> --phase
   {pre_match,live,halftime,full_time} --file <path>`. This is the ONLY
   write path — never write SQL directly. Re-running for the same
   `(match, phase)` cleanly replaces that phase's rows (no duplicates to
   manage by hand).

### Payload schema

```json
{
  "headline": "one-line tactical headline for this phase",
  "uncertainties": "what cannot yet be concluded - mandatory, even if short",
  "observations": [
    {"subject_type": "player", "subject_id": 123, "observation_type": "ATTACKING_ROLE",
     "observed": "...", "inferred": "...", "fpl_direction": "POSITIVE",
     "fpl_signal": "ROLE", "fpl_reason": "...", "confidence": "medium",
     "evidence_ref": "player_match_state.shots=3,xg=0.5"}
  ],
  "player_states": [
    {"player_id": 123, "role": "...", "tactical_signal": "...",
     "fpl_outlook": "...", "confidence": "medium", "evidence_ref": "..."}
  ],
  "team_states": [
    {"team_id": 1, "tactical_signal": "...", "attacking_signal": "...",
     "defensive_signal": "...", "key_observation": "...",
     "fpl_implication": "...", "confidence": "medium", "evidence_ref": "..."}
  ]
}
```
`observation_type` is one of: ATTACKING_ROLE, CREATION, PROGRESSION,
BOX_INVOLVEMENT, DEFENSIVE_ROLE, SET_PIECE, MINUTES, FORMATION,
TACTICAL_CHANGE, SUBSTITUTION_PATTERN, TEAM_PATTERN. `player_states`/
`team_states` are only meaningful (and only actually written) on a
`full_time` run — include them at other phases only if you want them
ignored, or simply omit them.

## Worked example: weak vs strong (real production data, 2026-09-12)

This is a REAL row this skill actually wrote for Arsenal 2-1 Chelsea
(match_id 20922, Kai Havertz, GW3) before the shot/event fix above existed -
kept here as the concrete failure mode to never repeat:

**Weak (what was actually stored):**
```
observed:  "1 goal, 3 shots, 0.27 xG, played 82 minutes, 3 key passes, 0.29 xA"
inferred:  "goal threat and creation both present in the same match"
```
`inferred` adds zero information over `observed` - it's the same four
numbers renamed "goal threat" and "creation." This is the exact pattern to
never repeat.

**Strong (same real player, same match, using `SHOTS`/`EVENTS`):**
```
observed:  "1 goal, 3 shots, 0.27 xG, played 82 minutes, 3 key passes, 0.29 xA"
inferred:  "goal (min 25, LeftFoot, RegularPlay, xg=0.02) scored well below
            its own chance quality - a finishing outcome, not a repeatable
            chance-creation pattern; his other 2 shots (min 15 Header 0.15xg
            saved, min 20 LeftFoot 0.10xg FastBreak saved) came from open
            play, not set pieces"
```
Same OBSERVED line, same evidence table - the difference is entirely
whether you actually opened `SHOTS` and used the real `minute`/`shot_type`/
`situation`/`xg` sitting right there instead of stopping at the aggregate.

## Language discipline (2026-09-03, closes a real gap)

Every `observed`/`inferred`/`fpl_reason` string you write here lands verbatim
in `match_observations` and is read straight through to the FOOTBALL/SCOUT
dashboard screens (`models/football_signal.py`'s `evidence` field). Apply
`fpl-football-intelligence`'s filler-word rule here too, not just in the
zero-LLM detectors it was written against:

**Never write** genuine, real (as an intensifier), sustained, trusted,
meaningful, significant, high-quality, encouraging, impressive **unless the
same sentence also states the specific number that justifies it** - and even
then, prefer just the number. If deleting the adjective loses no information,
delete it.

- Write `"3 goals, 8 shots, 1.95 xG, 90 minutes"`, not `"a real hat-trick
  built on match-high shot volume and chance quality - genuine, sustained
  central attacking involvement"`.
- Write `"2 goals from 0.69 xG"`, not `"significant finishing
  overperformance... genuinely elevated underlying shot quality"`.
- Don't restate a number as adjective-laden prose in the same breath you just
  stated it plainly - `"5 shots, 0.85 xG"` already IS the finding; a trailing
  clause repeating it in words ("a real, high-volume... involvement") adds a
  sentence without adding information.
- A tactical READ (the WHY DID IT HAPPEN step) can still be genuine
  interpretation - just write it as a plain claim tied to the observed
  number ("started centrally, 3 of 5 shots from inside the box"), not
  dressed up with an intensifier that substitutes for a number you don't
  have (e.g. don't write "against a deep, low-possession opponent" unless
  the row's own evidence actually carries the opponent's possession/shots
  numbers - state the number or drop the claim).

## Substitutions

For each real substitution in the evidence, note player off/on, minute
(where available), and score/game-state at that point — a tactical
interpretation only where the evidence actually supports one (minutes
security, rotation, role change). Don't overinterpret a single substitution.

## Output

A short MATCH INTELLIGENCE report, structured per the user's own template:
headline, "What happened?" (2-4 evidence-grounded observations), "Tactical
story" (2-4 interpretations), "Biggest player signals" (player / signal /
evidence / FPL relevance), "Manager signal" (only if real), "FPL
implications" (BUY/HOLD/WATCH/NEGATIVE, only where supported), and a
mandatory "What remains uncertain?" section.

## Known limitation

FotMob's free lineup payload for this project doesn't publish a bench list
before kickoff, and per-player rating/key-passes/touches-in-box/xA aren't
populated by anything this slice currently parses (team-level possession/
shots/xg are best-effort and unverified against a live match — see
`models/match_intelligence.py`'s own docstring). Say so rather than inventing
a number when a field is genuinely absent.
