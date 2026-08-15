-- migrations/0010_transfer_momentum.sql
-- Pillar 1 Plan 1a (spec: 2026-08-15-market-rivaling-architecture-design.md, Pillar 1
-- section): bootstrap-static already returns transfers_in_event/transfers_out_event/
-- transfers_in/transfers_out per element - fetched today but never persisted (only
-- now_cost is captured). No new external source, just new persistence of an
-- already-fetched field, same valid_from/valid_until change-tracking pattern as
-- player_price_history/player_ownership_history.

CREATE TABLE player_transfer_momentum_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    transfers_in_event INTEGER NOT NULL,
    transfers_out_event INTEGER NOT NULL,
    transfers_in INTEGER NOT NULL,
    transfers_out INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT
);
CREATE INDEX idx_transfer_momentum_player ON player_transfer_momentum_history(player_id, valid_from);
