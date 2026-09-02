-- migrations/0037_my_team_transfers.sql
-- Real transfer LOG for the tracked entry, 2026-09-02 - closes a confirmed
-- production bug (dashboard showed "3" free transfers, the real FPL app
-- showed 2). `my_team_gw_summary.event_transfers` (migration 0020) only ever
-- reflects LOCKED gameweeks, so `models/free_transfers.py`'s official-history
-- replay correctly computes the bank walking INTO the upcoming gameweek but
-- has no way to see a transfer the user already made inside that gameweek's
-- still-open pre-deadline window. `/entry/{id}/transfers/` is a real, public,
-- no-login Tier 1 endpoint that is NOT a locked-squad snapshot (unlike
-- /event/{gw}/picks/) - it is an append-only log of every transfer ever made,
-- including ones made toward a gameweek that hasn't locked yet.

CREATE TABLE my_team_transfers (
    entry_id INTEGER NOT NULL,
    event INTEGER NOT NULL,           -- the gameweek this transfer counts toward
    element_in INTEGER NOT NULL,
    element_in_cost INTEGER,          -- tenths of a million, as sold by the API
    element_out INTEGER NOT NULL,
    element_out_cost INTEGER,
    transfer_time TEXT NOT NULL,      -- FPL's own ISO timestamp for this transfer
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, event, element_in, element_out, transfer_time)
);
CREATE INDEX idx_my_team_transfers_event ON my_team_transfers(entry_id, event);
