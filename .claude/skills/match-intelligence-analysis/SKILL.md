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
   current structured state, including its `status` field. Analyze at the
   phase the match is actually in — never assume from wall-clock time.
   - `PRE_MATCH`/`LIVE`/`HALFTIME`: thin evidence is expected. Say so
     plainly, analyze only what's genuinely there, and keep everything
     explicitly provisional (see step 5).
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
