-- squad_select = required count of this position in a 15-man squad (e.g. 2 GKP, 5 DEF, 5 MID, 3 FWD).
-- Missed in the Phase 2 element_types migration; needed now for the squad optimiser's constraints.
ALTER TABLE element_types ADD COLUMN squad_select INTEGER;
