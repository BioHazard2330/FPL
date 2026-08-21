# Match Intelligence Core (Pillar 4, Slice A) — design

## 1. Objective and scope

First real football-intelligence layer underneath the existing FPL-statistics
optimizer. Builds a thin, genuinely extensible vertical slice — not a "match
report generator" — proving the pipeline:

```
FotMob -> source-aware ingestion -> normalized match data
       -> structured observations (OBSERVED/INFERRED/FPL_IMPLICATION)
       -> player/team match state -> FPL implication
       -> (future) optimizer consumption
```

Scope this cycle: one source (FotMob), one match lifecycle (manual/CLI
triggered, not scheduled), structured data first, prose second. Test case:
Arsenal v Coventry, 2026-08-21. Architecture must generalize to any PL match —
the match id is *resolved*, never hardcoded.

## 2. FotMob source: endpoints and provenance

Live-verified 2026-08-21, no auth/anti-bot token required today:

- `GET https://www.fotmob.com/api/data/matches?date=YYYYMMDD` — a day's
  fixtures across every league FotMob covers. Used to resolve `(home_name,
  away_name, date)` -> FotMob match id. Confirmed: Arsenal v Coventry,
  2026-08-21 -> matchId `5795363`, `leagueId=47` (Premier League), kickoff
  `2026-08-21T19:00:00Z` — matches the FPL-side synced kickoff exactly.
- `GET https://www.fotmob.com/api/data/matchDetails?matchId=N` — full match
  payload: `general` (status/started/finished), `header.status`,
  `content.matchFacts/stats/playerStats/shotmap/lineup/momentum/liveticker/
  superlive`.

`source="fotmob"` throughout. Every ingested row carries `source`,
`source_match_id`, `retrieved_at`. Raw payloads saved via the existing
`ingestion/raw_store.py` (same 24-72h retention as every other source), health
tracked via the existing `ingestion/sync.py::update_source_health`
(`source_name="fotmob"`). No new team/player identity table — FotMob's team
names for this fixture ("Arsenal", "Coventry") already equal FPL's own short
form, resolved through the existing `market_identity.py` crosswalk with zero
new aliases; if a future match needs one, add it there, the established
pattern (do not build a second crosswalk).

Failure handling: any FotMob request failure records `source_health(success=
False)` and raises a typed `FotMobFetchError` — never returns `[]`/fabricated
data pretending to be live (project's standing rule).

## 3. Normalized models

Pure Python dataclasses in `models/match_intelligence.py`, all fields
`| None` where evidence may not exist — never a fabricated default.

- `Match` — id, fotmob_match_id, competition, kickoff, home_team_id,
  away_team_id (resolved FPL team ids), status
  (`PRE_MATCH|LIVE|HALFTIME|FULL_TIME`), home_score, away_score.
- `PlayerMatchState` — match_id, player_id (resolved FPL id, nullable if
  unresolved), team_id, started, minutes, position, rating, goals, assists,
  shots, key_passes, xg, xa, touches_box (nullable — FotMob's shotmap/stats
  don't always carry this), substituted_on/off.
- `TeamMatchState` — match_id, team_id, formation, possession_pct, shots,
  shots_on_target, xg, corners.

These are the row shapes for the DB tables in §5 — the dataclasses are what
ingestion/derivation code passes around; the DB is the persisted form.

## 4. OBSERVED / INFERRED / FPL_IMPLICATION separation

Mandatory three-field split, enforced by schema (§5's `match_observations`
table has all three as separate non-nullable-together columns):

- **OBSERVED** — a plain restatement of real ingested data ("8 touches in the
  box", "started, 90 minutes"). Never absent when a row exists.
- **INFERRED** — a tactical read of the observed data. Produced by the LLM
  skill (§8), not by deterministic code — this project has no tactical model,
  so a machine "inference" here would be fabrication. May be null until the
  skill runs.
- **FPL_IMPLICATION** — direction (`POSITIVE|NEUTRAL|NEGATIVE|WATCH`) + signal
  (`ROLE|MINUTES|CREATION|GOAL_THREAT|TEAM_ATTACK|FIXTURES|TACTICAL_CHANGE|
  SET_PIECES`) + reason text. Also skill-produced, references the INFERRED
  field it follows from.

Every `match_observations` row is stamped `confidence` (`low|medium|high`,
skill-assigned, never fabricated as `high` by default) and `observation_type`
from the fixed category list in the user's spec (ATTACKING_ROLE, CREATION,
PROGRESSION, BOX_INVOLVEMENT, DEFENSIVE_ROLE, SET_PIECE, MINUTES, FORMATION,
TACTICAL_CHANGE, SUBSTITUTION_PATTERN, TEAM_PATTERN).

## 5. Database tables

Migration `0023_match_intelligence.sql`, same `sqlite3`/idempotent-upsert
conventions as every existing migration:

- `match_intelligence` — one row per match. `id INTEGER PRIMARY KEY`,
  `fotmob_match_id TEXT UNIQUE NOT NULL`, `fpl_fixture_id INTEGER REFERENCES
  fixtures(id)` (nullable — resolved on a best-effort basis via kickoff+team
  match, never blocks ingestion if it can't resolve), `competition`,
  `kickoff_utc`, `home_team_id`, `away_team_id`, `status`, `home_score`,
  `away_score`, `source`, `retrieved_at`, `confidence`, `data_quality`,
  `raw_source_reference`.
- `player_match_state` — `match_id REFERENCES match_intelligence(id)`,
  `player_id REFERENCES players(id)` (nullable — unresolved FotMob player),
  `fotmob_player_id`, `team_id`, `started`, `minutes`, `position`, `rating`,
  `goals`, `assists`, `shots`, `key_passes`, `xg`, `xa`, `touches_box`,
  `substituted_on_minute`, `substituted_off_minute`, `source`, `retrieved_at`,
  `confidence`. `UNIQUE(match_id, player_id, fotmob_player_id)`.
- `team_match_state` — `match_id`, `team_id`, `formation`, `possession_pct`,
  `shots`, `shots_on_target`, `xg`, `corners`, `source`, `retrieved_at`,
  `confidence`. `UNIQUE(match_id, team_id)`.
- `match_observations` — `match_id`, `subject_type` (`player|team`),
  `subject_id`, `observation_type`, `observed`, `inferred` (nullable),
  `fpl_direction` (nullable), `fpl_signal` (nullable), `fpl_reason`
  (nullable), `confidence`, `created_at`.
- `player_fpl_implications` — `match_id`, `player_id`, `signal`, `direction`,
  `reason`, `confidence`, `created_at`. Denormalized from
  `match_observations` specifically so `fpl rate-team`/future optimizer
  consumers (B/C) can read one flat table instead of joining observations —
  the "clean output interface" §9/§12 of the user's spec asks for.

All five tables: `source`/`retrieved_at`/`confidence` on every row (§ Data
governance requirement), nulls allowed everywhere evidence doesn't exist,
never a default standing in for missing data.

## 6. latest_match_state / previous_match_state boundary

No history table this cycle (that's Tactical Memory, Slice B). Persistence
model: `player_match_state`/`team_match_state` are **upserted per match**,
keyed on `(match_id, player_id)`/`(match_id, team_id)` — one row per player
per match, overwritten as the match progresses through its lifecycle
(PRE_MATCH -> LIVE -> HT -> FT), never appended. "Latest" is simply "the row
for the most recent `match_id` involving this player," read by joining
`match_intelligence` ordered by `kickoff_utc DESC LIMIT 1`. No separate
`latest_match_state`/`previous_match_state` columns or tables — B's job is to
turn "the last N matches, queryable" into real tactical history/trend
detection; this slice deliberately stops at "the most recent match is
queryable," which is exactly what an unindexed-by-recency upsert table
already gives for free. Nothing here blocks B from adding a proper history
table alongside it later.

## 7. CLI commands

Under the existing `fpl` group (`cli/main.py`), not a separate `python -m`:

- `fpl sync-match <home_team> <away_team> [--date YYYY-MM-DD]` (default:
  today) — resolves the FotMob match id via the date-scoped fixture list,
  fetches matchDetails, normalizes, upserts `match_intelligence`/
  `player_match_state`/`team_match_state`. Idempotent — re-running updates
  the same rows (this is expected: a LIVE match's state is meant to be
  re-synced as it progresses).
- `fpl match-report <match_id>` — prints the current structured state
  (Match/PlayerMatchState/TeamMatchState) and any `match_observations`/
  `player_fpl_implications` rows already present. Does not itself invoke the
  LLM skill (§8) — it's a read of whatever's been persisted.

## 8. LLM Skill boundary

A new `.claude/skills/match-intelligence-analysis/` skill — thin instruction
layer, same shape as the 15 existing skills (`injury-monitor`,
`transfer-analyst`, etc.), not a live Anthropic API call embedded in Python.
Reads the structured `player_match_state`/`team_match_state` for a given
`match_id` (via `fpl match-report <id> --json` or direct DB read), applies the
WHAT HAPPENED / WHY / IS IT NEW / IS IT SUSTAINABLE / DOES IT MATTER framework
from the user's spec, and writes `match_observations`/
`player_fpl_implications` rows back — this is the only thing in the whole
slice that produces the INFERRED/FPL_IMPLICATION text. Every conclusion must
cite the OBSERVED evidence it's drawn from (enforced by the skill's own
instructions, not by code — same trust boundary this project's other
LLM-facing skills already use). Out of scope for the *code* half of this
cycle to fully wire an automated write-back path if it proves fiddly under
tonight's time pressure — acceptable minimum is the skill can be run
interactively and the report command can display whatever it wrote.

## 9. Dashboard integration boundary

One new, small panel — `dashboard.py::_match_intelligence_html()` — shown only
when a `match_intelligence` row exists for a squad-relevant match. Sections:
MATCH/STATUS, TACTICAL VERDICT (from `match_observations` if any exist, else
"not yet analyzed"), KEY OBSERVATIONS, FPL IMPACT, PLAYERS TO WATCH, DATA
FRESHNESS (`retrieved_at` age). Reuses existing panel/card CSS classes, no new
design system. Not a redesign of anything else on the dashboard.

## 10. Explicitly deferred (not this cycle)

SofaScore, Understat expansion, StatsBomb, API-Football. Full Tactical
Memory / player role-trend classification (NEW/PERSISTENT/REVERSAL/NOISE).
Manager profiles. "My Football View" qualitative user-judgement schema.
Decision Fusion Engine. Model-vs-user-view surface. Calibration/learning
pipeline. Full Player/Team Intelligence UI surfaces. Automated/scheduled live
polling (manual `fpl sync-match` re-run only, this cycle). Optimizer
consumption of `player_fpl_implications` (the table is built so B/C can read
it later; `optimize_squad`/`expected_points` are NOT modified this cycle).

## 11. Data-quality / source-failure behavior

- FotMob unreachable or non-200: `source_health(source_name="fotmob",
  success=False, error=<safe HTTP-status-only message>)`, raise
  `FotMobFetchError`, existing `match_intelligence` row (if any) left
  untouched — never overwritten with a blank/degraded state.
- Match id cannot be resolved from the date-scoped fixture list (wrong date,
  name mismatch): raise a clear `ValueError` naming what was searched for —
  never silently fall back to a guessed id.
- A field FotMob doesn't provide for this match (e.g. no `xg` yet
  pre-kickoff): stored as `NULL`, never `0` or fabricated.
- Two-source cross-check (FotMob vs SofaScore) does not exist this cycle —
  N/A, deferred with SofaScore itself.

## 12. Acceptance criteria — Arsenal v Coventry

1. `fpl sync-match Arsenal Coventry --date 2026-08-21` resolves the real
   FotMob match id `5795363` without hardcoding it in source.
2. Stored `kickoff_utc = 2026-08-21T19:00:00Z`.
3. Real `matchDetails` fetched and saved via `raw_store` with `source=
   "fotmob"` provenance.
4. Normalization produces real `Match`/`PlayerMatchState`/`TeamMatchState`
   rows — reflecting the match's *actual* status at run time (PRE_MATCH,
   LIVE, or FULL_TIME — never assumed from wall-clock time, always read from
   FotMob's own `general.started`/`finished`).
5. `fpl match-report 5795363` (or the resolved internal id) prints the real
   structured state.
6. Full existing test suite passes unmodified; new tests cover FotMob
   parsing, normalization, missing-field handling, provenance, lifecycle
   status derivation, the two upsert tables, and the CLI commands.
7. No existing optimizer/dashboard command's output changes as a result of
   this slice landing (additive only).
