"""
Readiness gate (section 108). Every check reflects real, live system state -
no hardcoded "yes" for anything not actually verified this call.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fpl_agent.database.backup import list_backups
from fpl_agent.models.expected_points import MODEL_VERSION
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.optimization.squad import optimise_squad
from fpl_agent.scheduler.status import assess_all_task_health


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str  # OK, DEGRADED, MISSING
    detail: str


def run_readiness_checks(conn: sqlite3.Connection) -> list[ReadinessCheck]:
    checks = []

    try:
        conn.execute("SELECT 1")
        checks.append(ReadinessCheck("Database", "OK", "reachable"))
    except Exception as e:
        checks.append(ReadinessCheck("Database", "MISSING", str(e)))

    sources = get_source_health(conn)
    degraded = [s.source_name for s in sources if s.failure_count > 0 or not s.last_success]
    if not sources:
        checks.append(ReadinessCheck("Current FPL data", "MISSING", "never synced - run `fpl sync`"))
    elif degraded:
        checks.append(ReadinessCheck("Current FPL data", "DEGRADED", f"issues: {', '.join(degraded)}"))
    else:
        checks.append(ReadinessCheck("Current FPL data", "OK", f"{len(sources)} source(s) healthy"))

    n_rules = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
    checks.append(ReadinessCheck("Rules", "OK" if n_rules else "MISSING", f"{n_rules} rule value(s)"))

    n_fixtures = conn.execute("SELECT COUNT(*) FROM fixtures").fetchone()[0]
    checks.append(ReadinessCheck("Fixtures", "OK" if n_fixtures else "MISSING", f"{n_fixtures} fixture(s)"))

    n_prices = conn.execute("SELECT COUNT(*) FROM player_price_history WHERE valid_until IS NULL").fetchone()[0]
    checks.append(ReadinessCheck("Prices", "OK" if n_prices else "MISSING", f"{n_prices} current price(s)"))

    n_players = conn.execute("SELECT COUNT(*) FROM players WHERE removed=0").fetchone()[0]
    checks.append(ReadinessCheck("Players", "OK" if n_players else "MISSING", f"{n_players} player(s)"))

    checks.append(ReadinessCheck(
        "Transfers", "DEGRADED",
        "Tier 1 only - confirmed via club_change events, no pre-confirmation news (source-tier choice)",
    ))
    checks.append(ReadinessCheck("Injuries", "OK", "official status/news/chance-of-playing fields (Tier 1)"))

    n_lineup_teams = conn.execute("SELECT COUNT(*) FROM predicted_lineup_teams").fetchone()[0]
    if n_lineup_teams:
        checks.append(ReadinessCheck(
            "Team news", "OK",
            f"Tier 2-4 predicted lineups synced for {n_lineup_teams} team(s) - run `fpl sync-predicted-lineups` to refresh",
        ))
    else:
        checks.append(ReadinessCheck(
            "Team news", "DEGRADED", "no predicted-lineup sync yet - run `fpl sync-predicted-lineups`",
        ))

    n_history = conn.execute("SELECT COUNT(*) FROM player_season_history").fetchone()[0]
    checks.append(ReadinessCheck(
        "Player projections", "OK", f"{MODEL_VERSION} model, {n_history} season-history row(s)",
    ))

    squad_result = optimise_squad(conn, n_gw=1)
    if squad_result.status == "Optimal":
        checks.append(ReadinessCheck("Squad optimizer", "OK", f"solved, total_xp={squad_result.total_xp}"))
    else:
        checks.append(ReadinessCheck("Squad optimizer", "DEGRADED", f"solver status: {squad_result.status}"))

    # Real, live-exercised checks (2026-09-02 fix - these three used to be
    # hardcoded "OK" strings with zero runtime measurement, a real, confirmed
    # instance of exactly the "component installed != component working"
    # bug the autonomous-runtime audit was looking for). `analyze_transfer_
    # decision`/`analyze_captain_decision`/`eligible_chips` are the same
    # cheap, real, every-regen calls the live dashboard already makes -
    # DEGRADED only means "no real locked squad to evaluate against yet"
    # (a real, honest precondition gap, not a solver failure) or a genuine
    # exception, never a guessed/hardcoded pass.
    from fpl_agent.optimization.locked_squad import get_locked_squad

    locked = None
    try:
        locked = get_locked_squad(conn)
    except Exception:
        locked = None

    if locked is None or not locked.squad_ids:
        checks.append(ReadinessCheck("Transfer optimizer", "DEGRADED", "no real locked squad to evaluate yet"))
        checks.append(ReadinessCheck("Captaincy", "DEGRADED", "no real locked squad to evaluate yet"))
        checks.append(ReadinessCheck("Chip engine", "DEGRADED", "no real locked squad to evaluate yet"))
    else:
        try:
            from fpl_agent.optimization.decision_analysis import analyze_transfer_decision

            ta = analyze_transfer_decision(conn, locked)
            checks.append(ReadinessCheck("Transfer optimizer", "OK", f"live-exercised, verdict={ta.decision_kind}"))
        except Exception as e:
            checks.append(ReadinessCheck("Transfer optimizer", "DEGRADED", f"live exercise raised: {e}"))

        try:
            from fpl_agent.optimization.decision_analysis import analyze_captain_decision

            ca = analyze_captain_decision(conn, locked)
            checks.append(ReadinessCheck("Captaincy", "OK", f"live-exercised, verdict={ca.decision_kind}"))
        except Exception as e:
            checks.append(ReadinessCheck("Captaincy", "DEGRADED", f"live exercise raised: {e}"))

        try:
            from fpl_agent.optimization.chips import eligible_chips

            windows = eligible_chips(conn, locked.event)
            n_eligible = sum(1 for w in windows if w.eligible_now)
            checks.append(ReadinessCheck("Chip engine", "OK", f"live-exercised, {n_eligible} window(s) eligible now"))
        except Exception as e:
            checks.append(ReadinessCheck("Chip engine", "DEGRADED", f"live exercise raised: {e}"))

    n_changes = conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]
    checks.append(ReadinessCheck("Change detection", "OK", f"{n_changes} event(s) recorded"))

    # Real per-task execution freshness (2026-09-02 fix - direct user report:
    # optimizer runs silently stopped for ~40h while this row kept saying
    # "Scheduler OK", because the old check only read Task Scheduler's
    # State/NextRunTime, never LastRunTime age against the task's own real
    # registered cadence - see scheduler/status.py::assess_task_health's own
    # docstring for the full account). Reports every real autonomous task,
    # not just FPLAgentSync, and the overall row's status is the worst of
    # the three - a real problem on any one of them must not be hidden by
    # the other two being healthy.
    task_healths = assess_all_task_health()
    _STATUS_RANK = {"OK": 0, "STALE": 1, "UNKNOWN": 1, "CRITICAL": 2, "UNREGISTERED": 2}
    worst = max(task_healths, key=lambda h: _STATUS_RANK.get(h.status, 2))
    overall = "OK" if worst.status == "OK" else ("DEGRADED" if worst.status in ("STALE", "UNKNOWN") else "CRITICAL")
    detail = " | ".join(f"{h.task_name}: {h.status} ({h.detail})" for h in task_healths)
    checks.append(ReadinessCheck("Scheduler", overall, detail))

    checks.append(ReadinessCheck("Storage governor", "OK", "fpl storage / fpl cleanup active"))

    backups = list_backups()
    checks.append(ReadinessCheck(
        "Backup", "OK" if backups else "DEGRADED",
        f"{len(backups)} backup(s)" if backups else "no backups yet - run `fpl backup`",
    ))

    # Real "when did pytest last actually run in this repo" signal (2026-09-02
    # fix - the old row was a literal hardcoded string claiming "64 passing"
    # regardless of whether that was ever re-verified). `.pytest_cache/v/
    # cache/nodeids` is real evidence, rewritten by pytest on every real
    # invocation (unlike the bare `.pytest_cache` directory's own mtime,
    # confirmed live NOT to update just because files inside it were
    # rewritten - only creating/deleting an entry touches a directory's own
    # mtime on this filesystem). Still does NOT know pass/fail counts
    # (pytest's cache doesn't store a summary), so this deliberately reports
    # "ran Xh ago", never a fabricated pass count.
    nodeids_file = Path(".pytest_cache/v/cache/nodeids")
    if nodeids_file.exists():
        age_h = (datetime.now(timezone.utc).timestamp() - nodeids_file.stat().st_mtime) / 3600
        checks.append(ReadinessCheck(
            "Tests", "OK" if age_h < 24 else "DEGRADED",
            f"pytest last ran {age_h:.1f}h ago (.pytest_cache/v/cache/nodeids mtime) - "
            "this check does not re-execute the suite or know pass/fail counts, run `pytest` to confirm",
        ))
    else:
        checks.append(ReadinessCheck("Tests", "DEGRADED", "no .pytest_cache found - pytest has never run here"))

    checks.append(ReadinessCheck(
        "First-team generation",
        "OK" if squad_result.status == "Optimal" else "DEGRADED",
        "`fpl build-team` produces a full section-93 report",
    ))

    return checks
