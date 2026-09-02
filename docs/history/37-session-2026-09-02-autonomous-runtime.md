# Session 37 — 2026-09-02: Autonomous Runtime + Post-Gameweek + Decision Freshness Rebuild

Direct spec: make the system run without a Claude Code session required at
runtime, plus a direct bug report ("dashboard says I have 3 transfers but I
actually have 2 free transfers").

**Real free-transfer off-by-one bug found + fixed**: `models/free_transfers.py`
mis-accrued GW1 (a phantom FT). Added `count_pending_transfers`/
`compute_current_free_transfers`, a new `my_team_transfers` table (migration
`0037_my_team_transfers.sql`) fed by a new `ingestion/fpl_api.py::
fetch_entry_transfers` + `my_team.py::_upsert_transfers` — real transfer
history now backs the accrual calculation instead of inferring it purely from
GW summaries.

**Readiness/health checks de-fabricated**: `monitoring/readiness.py` used to
report hardcoded fake statuses for several subsystems — replaced with real,
live-exercised checks (`analyze_transfer_decision`/`analyze_captain_decision`/
`eligible_chips` actually called, `.pytest_cache` mtime actually read).
`scheduler/status.py` gained `assess_task_health`/`assess_all_task_health`
(real, not guessed, task-health assessment) and fixed two live-discovered
Windows Task Scheduler result-code misreadings (`2147946720` = LiveServer's
own IgnoreNew skip code, `267009`/`267008` = SCHED_S_TASK_RUNNING/QUEUED —
both were being reported as failures).

**Decision-freshness watching gap closed**: `models/decision_freshness.py`
only watched the current squad's own player ids for staleness-triggering
changes — a recommendation's own TARGET player (e.g. a transfer-in candidate
not yet in the squad) could change materially without the freshness check
noticing. New `_recommendation_target_ids` helper extends the watch list.

New tests: `test_free_transfers.py` (rewritten for the corrected FT rule),
`test_scheduler_status.py`, `test_readiness.py` (new), `test_decision_freshness.py`
(extended). Full suite green.
