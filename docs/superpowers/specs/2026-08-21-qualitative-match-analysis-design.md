# Qualitative Match Analysis + Post-Match Pipeline (Pillar 4, Slice A2) — design

Builds directly on Match Intelligence Core (Slice A, migration 0023, complete
and verified). Extends it — does not duplicate it. Reuses `match_intelligence`/
`player_match_state`/`team_match_state`/`match_observations`/
`player_fpl_implications` as-is; adds only what those tables genuinely lack.

## Scope boundary (unchanged from the user's brief)

No SofaScore/Understat/StatsBomb/API-Football. No optimizer/captain/transfer
changes. No Decision Fusion. No My Football View calibration. The qualitative
layer is stored and inspectable only — nothing here is read by
`optimization/*` or `models/expected_points.py`.

## 1. Data model — additive only

Migration `0024_qualitative_match_analysis.sql`:

- `match_observations` gains `phase` (`PRE_MATCH|LIVE|HALFTIME|FULL_TIME`,
  default `FULL_TIME`), `evidence_ref` (free text pointing at the source
  row/field, e.g. `"player_match_state.shots=3"`), `analysis_version`.
  `player_fpl_implications` gains the same three columns — this project's own
  "extend, don't duplicate" instruction applies to columns as much as tables.
  Team-level FPL implications reuse `match_observations` (`subject_type=
  'team'`, `fpl_direction`/`fpl_signal`/`fpl_reason` populated) — no new team
  implications table, since the columns already exist there regardless of
  subject type.
- `player_qualitative_state` — one row per `player_id` (PK), current-state
  upsert: `match_id` (last analyzed), `role`, `tactical_signal`,
  `fpl_outlook`, `confidence`, `evidence_ref`, `analysis_version`,
  `generated_at`. Written **only** on a `FULL_TIME`-phase analysis — a
  halftime read never touches this table (spec's own §14/§11 rule, enforced
  in code, not just by skill instruction).
- `team_qualitative_state` — same shape, one row per `team_id`, same
  FULL_TIME-only write rule.
- `match_analysis_summary` — `(match_id, phase)` composite PK, current-state
  upsert: `headline`, `uncertainties`, `analysis_version`, `generated_at`.
  This is what makes a `HALFTIME` read explicitly provisional and non-final:
  it lives at its own `phase` key, never overwrites the `FULL_TIME` row.
- `user_observations` — append-only: `id`, `match_id` (nullable),
  `subject_type` (`player|team`), `subject_id`, `phase` (free text, e.g.
  `"second half"`), `sentiment` (`positive|negative|neutral`, nullable),
  `note`, `created_at`. `source` is implicit (its own table) — never merged
  into `match_observations`.

## 2. Evidence separation — enforced in code, not just by skill discipline

Slice A's skill instructed "write OBSERVED only, never fabricate INFERRED."
This slice goes further: the LLM skill no longer writes SQL directly. It
writes a structured **JSON payload** to a file; a new deterministic function,
`ingestion/qualitative_analysis.py::apply_match_analysis(conn, match_id,
phase, payload)`, validates and persists it. This is a real, deliberate
upgrade over Slice A's original "skill writes SQL" plan (spelled out there as
acceptable but not ideal) — it means OBSERVED/INFERRED/FPL_IMPLICATION
separation, phase-gating, and duplicate-prevention are all schema/code
invariants, not just prose instructions an LLM could drift from.

Payload shape (documented in the skill file and validated by
`apply_match_analysis`):
```json
{
  "headline": "...",
  "uncertainties": "...",
  "observations": [
    {"subject_type": "player", "subject_id": 1, "observation_type": "ATTACKING_ROLE",
     "observed": "...", "inferred": "...", "fpl_direction": "POSITIVE",
     "fpl_signal": "ROLE", "fpl_reason": "...", "confidence": "medium",
     "evidence_ref": "player_match_state.shots=3"}
  ],
  "player_states": [
    {"player_id": 1, "role": "...", "tactical_signal": "...", "fpl_outlook": "...",
     "confidence": "medium", "evidence_ref": "..."}
  ],
  "team_states": [
    {"team_id": 1, "tactical_signal": "...", "attacking_signal": "...",
     "defensive_signal": "...", "key_observation": "...", "fpl_implication": "...",
     "confidence": "medium", "evidence_ref": "..."}
  ]
}
```
`player_fpl_implications` rows are derived automatically from `observations`
entries where `subject_type="player"` and `fpl_direction` is set — not a
separate list the skill has to keep in sync by hand.

## 3. Duplicate-analysis prevention

`apply_match_analysis` deletes existing `match_observations`/
`player_fpl_implications`/`match_analysis_summary` rows for the exact
`(match_id, phase)` key before inserting the new set — same "current-state,
delete+insert" pattern this project already uses for predicted lineups/start
percentages. Re-running an analysis for the same phase replaces it cleanly;
it never piles up duplicate rows. `FULL_TIME` writes additionally **refuse**
(raise `ValueError`) unless `match_intelligence.status == 'FULL_TIME'` for
that match — guards against fabricating a final verdict off a match that
hasn't actually finished.

## 4. Automatic post-match trigger — the honest version

Section 13 of the brief asks for full automation from `FINISHED` detection
through to a written report. Two genuinely different things are being asked
for, and only one of them can honestly be automatic given this project's own
established architecture (Slice A's design, endorsed already: the qualitative
LLM layer is a Claude Code **skill**, not a live Anthropic API call embedded
in Python — no second API key, Claude stays the reasoning layer per this
project's mission statement):

- **Evidence refresh + FINISHED detection: fully automatic.**
  `ingestion/fotmob_source.py::refresh_in_progress_matches(conn)` — queries
  `match_intelligence` for any row with `status != 'FULL_TIME'` whose
  `kickoff_utc` is within a bounded recent window (kickoff between 8h ago and
  1h from now — never endlessly re-polls stale or far-future rows), re-runs
  `sync_match` for it using the real team names already stored. Wired into
  `run-scheduled` (already running every 30min, real, registered), same
  non-fatal-per-step posture as every other block in that function. This is
  the "lightest reliable hook" the brief asks for — no new daemon, reuses the
  existing scheduler entirely.
- **Qualitative analysis (the LLM step): stays a deliberate, evidence-checked
  action inside a Claude Code session**, run via the
  `match-intelligence-analysis` skill once `fpl match-report <id>` shows
  `status=FULL_TIME`. This is not a gap — it's the same trust boundary this
  project draws everywhere else (recommend-only, Claude orchestrates,
  Python never silently invents football judgement). What tonight's build
  automates is everything *up to* "ready for analysis"; the analysis itself
  is one skill invocation away, not a cron job away.

## 5. Skill extension

`.claude/skills/match-intelligence-analysis/SKILL.md` rewritten to: read
`fpl match-report <id>` for real evidence, reason through WHAT HAPPENED / WHY
/ WHAT CHANGED / IS IT LIKELY TO PERSIST / DOES IT MATTER FOR FPL, write the
JSON payload (§2) to a file, then call `fpl match-analyze <id> --phase
<phase> --file <path>` to persist it. Explicitly instructed: say "insufficient
evidence" rather than guess; GW1 in particular gets an explicit
small-sample caveat (no persistent trend can be declared from one match).

## 6. CLI

- `fpl match-analyze <fotmob_match_id> --phase {pre_match,live,halftime,full_time} --file <path.json>`
  — the skill's write path (§2/§3).
- `fpl match-note {--player ID|--team ID} --sentiment {positive,negative,neutral} --note "..." [--match ID] [--phase TEXT]`
  — records a `USER_OBSERVATION`, never merged into AI analysis.
- `fpl match-report <id>` extended (existing command, not a new one): after
  the existing OBSERVATIONS/FPL IMPLICATIONS sections, prints
  `match_analysis_summary` per phase present (labeled `PROVISIONAL` for
  anything but `FULL_TIME`), `player_qualitative_state`/
  `team_qualitative_state` rows tied to this match, and a `USER OBSERVATIONS`
  section.

## 7. Dashboard

`_match_intelligence_html` (existing panel, Slice A) extended in place: when
a `match_analysis_summary` row exists, show its headline + a `PROVISIONAL`
badge when phase isn't `FULL_TIME` + top 3 player-implication chips already
rendered there. No new panel, no redesign.

## 8. Acceptance

Mirrors the user's A–L list exactly; verified against the real, still-live
Arsenal v Coventry match for the PRE_MATCH-still-works checks, and via unit
tests + synthetic FULL_TIME fixtures for everything phase-gated on a real
finish this session cannot yet observe (kickoff is ~3h out). A real
`fpl sync-match`-refreshed FULL_TIME run against the real match, and a real
skill-authored analysis, is follow-up work once the match actually finishes
tonight — flagged explicitly, not silently assumed complete.
