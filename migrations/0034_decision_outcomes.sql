-- migrations/0034_decision_outcomes.sql
-- Decision-outcome backtest storage (2026-08-28, direct user P1 ask: "was
-- the optimizer actually useful?"). Same two-moment capture/reveal pattern
-- prediction_outcomes (migration 0029) already established for player-level
-- projections, applied to the DECISION layer instead: what did we actually
-- recommend at the real deadline freeze, what was the best real rejected
-- alternative, and (once the gameweek finishes) what did each side's real
-- players actually score. One row per (event, season, decision_kind) -
-- 'transfer' unifies ROLL-vs-best-available-transfer and
-- recommended-transfer-vs-best-rejected-transfer into the same comparison
-- shape (chosen_out_id/chosen_in_id are both NULL for a real ROLL decision,
-- alt_out_id/alt_in_id are always the single best-ranked transfer candidate
-- whether or not it was the one chosen); 'captain' compares the recommended
-- captain against the next-best real alternative the same way.
-- Raw actual points are stored per player (not pre-computed deltas) so the
-- real net comparison (captain doubling, hit cost) is computed at report
-- time, not baked into storage - matches this project's own "derived value
-- computed from facts, never stored as if it were a fact" layering rule.
CREATE TABLE decision_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event INTEGER NOT NULL,
    season TEXT NOT NULL,
    decision_kind TEXT NOT NULL,               -- 'transfer' | 'captain'
    chosen_action TEXT NOT NULL,                -- 'roll' | 'transfer' | 'keep' | 'change'
    chosen_out_id INTEGER REFERENCES players(id),
    chosen_in_id INTEGER REFERENCES players(id),
    chosen_hit_cost INTEGER NOT NULL DEFAULT 0,
    chosen_projected_net_ev REAL,
    alt_out_id INTEGER REFERENCES players(id),
    alt_in_id INTEGER REFERENCES players(id),
    alt_hit_cost INTEGER NOT NULL DEFAULT 0,
    alt_projected_net_ev REAL,
    evidence_confidence TEXT,
    robustness TEXT,
    decided_at TEXT NOT NULL,
    chosen_out_actual_points REAL,
    chosen_in_actual_points REAL,
    alt_out_actual_points REAL,
    alt_in_actual_points REAL,
    outcome_recorded_at TEXT,
    UNIQUE(event, season, decision_kind)
);
CREATE INDEX idx_decision_outcomes_event ON decision_outcomes(event, season);
