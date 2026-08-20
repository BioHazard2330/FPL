import logging
import subprocess
import sys
import time
from datetime import datetime, timezone

import click
import numpy as np

# Windows consoles default to a legacy codepage that can't encode player
# names/news text pulled straight from the FPL API — force UTF-8 output.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fpl_agent.alerts.engine import Alert, TerminalNotifier, configured_notifiers, deliver_pending_alerts, pending_alerts
from fpl_agent.backtesting.harness import run_backtest, save_backtest_run, score_bonus_regression, score_differentials
from fpl_agent.config import DATA_DIR, load_dotenv
from fpl_agent.database.backup import BACKUP_DIR, create_backup, list_backups, restore_backup, verify_backup
from fpl_agent.database.connection import get_connection
from fpl_agent.database.decisions import get_decision, list_decisions, log_decision
from fpl_agent.database.migrate import run_migrations
from fpl_agent.ingestion.eo_sample import _DEFAULT_SAMPLE_SIZE, sample_effective_ownership
from fpl_agent.ingestion.cross_league_source import backfill_cross_league_priors
from fpl_agent.ingestion.football_data_source import backfill_football_data
from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.history_sync import sync_player_season_history
from fpl_agent.ingestion.news_source import NewsFetchError, list_recent_news, sync_all_news_sources
from fpl_agent.ingestion.odds_live_source import OddsLiveFetchError, sync_live_odds
from fpl_agent.ingestion.sync import ValidationError, run_sync, update_source_health
from fpl_agent.ingestion.understat_source import backfill_understat
from fpl_agent.logging_setup import setup_logging
from fpl_agent.scheduler.adaptive import maybe_retighten_scheduler
from fpl_agent.scheduler.cadence import recommended_cadence
from fpl_agent.scheduler.resources import check_resources
from fpl_agent.scheduler.status import check_scheduler_registered
from fpl_agent.models.availability import list_availability
from fpl_agent.models.expected_points import MODEL_VERSION, expected_points, expected_points_window
from fpl_agent.models.fixtures import _reference_event, detect_blank_double_gws
from fpl_agent.models.live_bonus import LiveBonusRow, compute_live_bonus, diff_live_rows
from fpl_agent.models.scenario_engine import sample_season_scenarios
from fpl_agent.monitoring.cleanup import run_cleanup
from fpl_agent.monitoring.dashboard import generate_dashboard_html
from fpl_agent.monitoring.doctor import run_checks
from fpl_agent.monitoring.readiness import run_readiness_checks
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.monitoring.storage import measure_storage
from fpl_agent.optimization.build_team import generate_build_team_report
from fpl_agent.optimization.captaincy import captaincy_report
from fpl_agent.optimization.chips import (
    _cached_optimise_squad,
    _squad_ids_by_event,
    bench_boost_value,
    eligible_chips,
    freehit_value,
    schedule_chips,
    triple_captain_value,
    wildcard_value,
)
from fpl_agent.optimization.squad import build_player_pool, optimise_squad, pick_starting_xi
from fpl_agent.optimization.transfers import best_transfer_for_player, recommend as recommend_transfer, search_transfer_sequences
from fpl_agent.optimization.rate_team import rate_team


@click.group()
def cli():
    load_dotenv()
    setup_logging()
    conn = get_connection()
    run_migrations(conn)
    conn.close()


@cli.command()
def doctor():
    """Run health checks: database, migrations, disk, config."""
    results = run_checks()
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        click.echo(f"{r.name:<12} {mark:<5} {r.detail}")
    if not all(r.ok for r in results):
        raise SystemExit(1)


@cli.command()
def readiness():
    """Section 108 readiness gate - every check reflects live system state."""
    conn = get_connection()
    checks = run_readiness_checks(conn)
    conn.close()
    for c in checks:
        mark = "✓" if c.status == "OK" else c.status
        click.echo(f"{c.name:<24} {mark:<10} {c.detail}")


@cli.command()
def status():
    """Quick dashboard: last sync, next deadline, pending alerts, decision history."""
    conn = get_connection()

    sources = get_source_health(conn)
    last_sync = next((s.last_success for s in sources if s.source_name == "fpl_api_bootstrap"), None)

    event = conn.execute(
        "SELECT name, deadline_time_epoch FROM events WHERE deadline_time_epoch > strftime('%s','now') "
        "ORDER BY deadline_time_epoch LIMIT 1"
    ).fetchone()

    pending = len(pending_alerts(conn))
    doctor_results = run_checks()
    doctor_ok = all(c.ok for c in doctor_results)

    latest_decision = list_decisions(conn, limit=1)
    conn.close()

    click.echo(f"last sync:        {last_sync or 'never'}")
    if event:
        click.echo(f"next deadline:    {event['name']}")
    else:
        click.echo("next deadline:    none found")
    click.echo(f"pending alerts:   {pending}")
    click.echo(f"system health:    {'OK' if doctor_ok else 'ISSUES - run `fpl doctor`'}")
    if latest_decision:
        d = latest_decision[0]
        click.echo(f"latest decision:  #{d.id} ({d.decision_type}) {d.summary}")
    else:
        click.echo("latest decision:  none yet - run `fpl build-team`")


@cli.command()
def storage():
    """Show DB/cache/log/temp footprint vs configured budget."""
    report = measure_storage()
    click.echo(f"database   {report.db_mb:>8.2f} MB")
    click.echo(f"cache      {report.cache_mb:>8.2f} MB")
    click.echo(f"logs       {report.logs_mb:>8.2f} MB")
    click.echo(f"temp       {report.temp_mb:>8.2f} MB")
    click.echo(f"backups    {report.backups_mb:>8.2f} MB")
    click.echo("-" * 30)
    click.echo(f"total      {report.total_mb:>8.2f} MB")
    click.echo(f"target     {report.target_mb:>8.2f} MB")
    click.echo(f"max        {report.max_mb:>8.2f} MB")
    click.echo(f"status     {report.status}")


@cli.command()
def sync():
    """Fetch current FPL data (Tier 1 official API only) and persist it."""
    try:
        summary = run_sync()
    except (SourceFetchError, ValidationError) as e:
        click.echo(f"sync failed: {e}", err=True)
        raise SystemExit(1)
    click.echo(f"season          {summary['season']}")
    click.echo(f"teams           {summary['teams']}")
    click.echo(f"players         {summary['players']}")
    click.echo(f"fixtures        {summary['fixtures']}")
    click.echo(f"events          {summary['events']}")
    click.echo(f"price changes   {summary['price_changes']}")
    click.echo(f"ownership chg   {summary['ownership_changes']}")
    click.echo(f"stats snapshots {summary['stats_snapshots_inserted']}")
    click.echo(f"setpiece chg    {summary['setpiece_changes']}")
    click.echo(f"strength chg    {summary['strength_changes']}")
    click.echo(f"lifecycle evts  {summary['lifecycle_events']}")
    click.echo(f"setpiece evts   {summary['setpiece_events']}")
    click.echo(f"rules changed   {summary['rules_changed']}")
    click.echo(f"raw pruned      {summary['raw_files_pruned']}")
    click.echo(f"retrieved_at    {summary['retrieved_at']}")


@cli.command("sync-history")
@click.option("--limit", default=None, type=int, help="max players to fetch this run (omit for all)")
@click.option("--force", is_flag=True, help="refetch even players who already have season history")
def sync_history(limit: int | None, force: bool):
    """Fetch per-player career history (element-summary). Slow (~1 req/0.15-0.4s per
    player) and heavy on the API - separate from `fpl sync`, safe to interrupt/resume."""
    result = sync_player_season_history(limit=limit, force=force)
    click.echo(f"fetched              {result['fetched']}")
    click.echo(f"already had history  {result['already_had_history']}")
    click.echo(f"skipped (limit)      {result['limit_skipped']}")
    click.echo(f"failed               {len(result['failed'])}")
    if result["failed"]:
        click.echo(f"failed player ids: {result['failed']}")


@cli.command("sync-eo")
@click.option("--event", required=True, type=int, help="gameweek to sample (must have already locked)")
@click.option("--sample-size", default=_DEFAULT_SAMPLE_SIZE, type=int, help="target number of managers to sample")
@click.option("--force", is_flag=True, help="re-sample even if this event already has EO data")
def sync_eo(event: int, sample_size: int, force: bool):
    """Sample effective ownership (captain/triple-captain-weighted) from a bounded,
    rank-stratified slice of the top-10k Overall league for one locked gameweek.
    Heaviest network pattern in this project - separate from `fpl sync`, throttled."""
    conn = get_connection()
    try:
        result = sample_effective_ownership(conn, event=event, target_sample_size=sample_size, force=force)
    except ValueError as e:
        click.echo(f"sync-eo failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()

    if result["skipped"]:
        click.echo(f"event {event} already sampled - use --force to re-sample")
        return
    click.echo(f"event            {result['event']}")
    click.echo(f"sample size      {result['sample_size']}")
    click.echo(f"players sampled  {result['players_sampled']}")
    click.echo(f"managers failed  {result['managers_failed']}")


@cli.command("sync-news")
@click.option("--limit", default=None, type=int, help="max new items to process this run (omit for all)")
def sync_news_cmd(limit: int | None):
    """Ingest BBC Sport + Sky Sports Premier League RSS (strong-reporter tier
    journalism, two independent sources) - real articles matched to
    players/teams by name, never auto-classified into a status change.
    Separate from `fpl sync`, opt-in."""
    conn = get_connection()
    try:
        result = sync_all_news_sources(conn, limit=limit)
    finally:
        conn.close()
    click.echo(f"fetched         {result['fetched']}")
    click.echo(f"new items       {result['new_items']}")
    click.echo(f"players linked  {result['players_linked']}")
    click.echo(f"teams linked    {result['teams_linked']}")
    for source, error in result["errors"].items():
        click.echo(f"WARNING: {source} failed: {error}", err=True)
    if result["errors"] and result["fetched"] == 0:
        raise SystemExit(1)


@cli.command("sync-live-odds")
def sync_live_odds_cmd():
    """Fetch live pre-match odds for upcoming fixtures (the-odds-api.com, free
    tier, requires ODDS_API_KEY - see .env.example) and match them to FPL
    fixtures. Separate from `fpl sync`, opt-in."""
    conn = get_connection()
    try:
        result = sync_live_odds(conn)
    except OddsLiveFetchError as e:
        click.echo(f"sync-live-odds failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()
    click.echo(f"fetched          {result['fetched']}")
    click.echo(f"matched          {result['matched']}")
    click.echo(f"unmatched        {result['unmatched']}")
    click.echo(f"failed           {result['failed']}")


@cli.command("team-news")
@click.option("--limit", default=20, type=int, help="max articles to show")
def team_news_cmd(limit: int):
    """Recent Tier 2-4 journalism (strong-reporter tier), matched to players/teams by
    name. Filter with grep for a specific player/team - matching is a best-effort
    heuristic, not a confirmed identification."""
    conn = get_connection()
    try:
        items = list_recent_news(conn, limit=limit)
    finally:
        conn.close()
    if not items:
        click.echo("no news items synced yet - run `fpl sync-news` first")
        return
    for item in items:
        players = item["players"] or "-"
        teams = item["teams"] or "-"
        published = item["published_at"] or "unknown date"
        click.echo(f"{published:25} [{item['source_tier']}] players={players} teams={teams}")
        click.echo(f"  {item['title']}")
        click.echo(f"  {item['link']}")


@cli.command("manager-changes")
@click.option("--days", default=7, type=int, help="lookback window in days")
def manager_changes_cmd(days: int):
    """Heuristic manager-change signal: teams with a manager-change-keyword
    article from 2+ INDEPENDENT journalism sources within the lookback
    window (requires `fpl sync-news` to have run first). A real, computed
    corroboration signal for a human/Claude to read and judge - never an
    asserted fact, never written to `teams`/`players.status`."""
    from fpl_agent.models.manager_change import detect_manager_change_signals

    conn = get_connection()
    try:
        signals = detect_manager_change_signals(conn, days_lookback=days)
    finally:
        conn.close()
    if not signals:
        click.echo(f"no corroborated manager-change signals in the last {days} day(s)")
        return
    for s in signals:
        click.echo(f"{s.team_name} - corroborated by: {', '.join(s.sources)}")
        for title in s.matched_titles:
            click.echo(f"  {title}")


@cli.command("backfill-odds")
@click.option("--season", required=True, help="e.g. 2024-25")
def backfill_odds(season: str):
    """One-time historical (or current-season refresh) match results + odds
    backfill from football-data.co.uk - safe to re-run, upserts idempotently."""
    conn = get_connection()
    try:
        summary = backfill_football_data(conn, season)
    finally:
        conn.close()
    click.echo(f"matches inserted/updated  {summary['matches_inserted']}")
    click.echo(f"odds rows inserted/updated {summary['odds_inserted']}")


@cli.command("backfill-xg")
@click.option("--season", required=True, help="e.g. 2024-25")
def backfill_xg(season: str):
    """One-time historical (or current-season refresh) shot-level xG/xA
    backfill from Understat - polite per-match delay, safe to re-run."""
    conn = get_connection()
    try:
        summary = backfill_understat(conn, season)
    finally:
        conn.close()
    click.echo(f"matches processed   {summary['matches_processed']}")
    click.echo(f"player rows upserted {summary['player_rows_inserted']}")


@cli.command("backfill-cross-league")
@click.option("--season", default=None, help="defaults to the current season - the players checked are always this season's genuinely-new-to-the-English-top-flight signings")
def backfill_cross_league(season: str | None):
    """One-time (or refresh) cross-league prior for players with zero PL
    history at all - searches Understat's other 5 top-league player lists
    for a name match, real per-90 rates scaled by a real league-quality
    factor. See docs/superpowers/specs/2026-08-20-preseason-calibration-
    design.md. Safe to re-run, upserts idempotently."""
    from fpl_agent.models.rules import current_season as _current_season

    conn = get_connection()
    try:
        resolved_season = season or _current_season(conn)
        if resolved_season is None:
            raise click.ClickException("no season available - run `fpl sync` first or pass --season explicitly")
        summary = backfill_cross_league_priors(conn, resolved_season)
    finally:
        conn.close()
    click.echo(f"candidates checked (zero PL history)  {summary['candidates_checked']}")
    click.echo(f"cross-league matches found            {summary['matched']}")


@cli.command("backtest")
@click.option("--season", required=True, help="e.g. 2024-25 - must already be backfilled via backfill-odds/backfill-xg")
@click.option("--model-version", default=None, help="defaults to the current MODEL_VERSION")
@click.option("--differentials", is_flag=True, default=False, help="also score the differential heuristic vs template pick")
@click.option("--bonus", is_flag=True, default=False, help="also score the bonus-regression shrinkage vs naive baseline")
def backtest(season: str, model_version: str | None, differentials: bool, bonus: bool):
    """Walk-forward backtest of the calibrated model against a historical
    season - no future leakage, scores against Understat-reconstructed
    actual points (core components only; bonus/BPS unavailable in that source)."""
    conn = get_connection()
    try:
        result = run_backtest(conn, season, model_version or MODEL_VERSION)
        run_id = save_backtest_run(conn, result)
        diff_result = None
        if differentials:
            diff_result = score_differentials(conn, season, model_version or MODEL_VERSION)
            log_decision(
                conn, "differential_backtest",
                summary=f"{diff_result.differentials_scored} differentials scored, season {season}",
                detail={
                    "season": diff_result.season, "rounds_evaluated": diff_result.rounds_evaluated,
                    "rounds_scored": diff_result.rounds_scored, "differentials_scored": diff_result.differentials_scored,
                    "mean_delta_vs_template": diff_result.mean_delta_vs_template,
                    "insufficient_ownership_data": diff_result.insufficient_ownership_data,
                },
                confidence="low",
            )
        bonus_result = None
        if bonus:
            bonus_result = score_bonus_regression(conn)
            log_decision(
                conn, "bonus_regression_backtest",
                summary=f"{bonus_result.players_evaluated} players evaluated (season-independent holdout)",
                detail={
                    "players_evaluated": bonus_result.players_evaluated,
                    "shrunk_mae": bonus_result.shrunk_mae, "naive_mae": bonus_result.naive_mae,
                    "shrunk_win_rate": bonus_result.shrunk_win_rate,
                    "insufficient_data": bonus_result.insufficient_data,
                },
                confidence="low",
            )
    finally:
        conn.close()

    click.echo(f"model version       {result.model_version}")
    click.echo(f"season               {result.season}")
    click.echo(f"rounds evaluated     {result.rounds_evaluated}")
    click.echo(f"predictions scored   {result.predictions_scored}")
    click.echo(f"MAE                  {result.mae}")
    click.echo(f"RMSE                 {result.rmse}")
    click.echo(f"baseline MAE         {result.baseline_mae}")
    click.echo(f"{'beats' if result.mae < result.baseline_mae else 'DOES NOT beat'} naive baseline")
    click.echo(f"saved as run #{run_id}")
    if diff_result is not None:
        if diff_result.insufficient_ownership_data:
            click.echo("differentials: insufficient historical ownership data to score")
        else:
            click.echo(f"differentials scored {diff_result.differentials_scored}, mean delta vs template {diff_result.mean_delta_vs_template}")
    if bonus_result is not None:
        if bonus_result.insufficient_data:
            click.echo("bonus regression: insufficient season-history data to score (need >=2 seasons per player)")
        else:
            click.echo(
                f"bonus regression: {bonus_result.players_evaluated} players, "
                f"shrunk MAE {bonus_result.shrunk_mae} vs naive MAE {bonus_result.naive_mae}, "
                f"shrunk wins {bonus_result.shrunk_win_rate * 100:.1f}%"
            )


@cli.command("run-scheduled")
def run_scheduled():
    """The actual entrypoint the OS scheduler invokes (section 19) - not `fpl sync`
    directly. Checks resources first (defers if constrained), syncs, then delivers
    any newly-pending HIGH+ alerts. Logs to the rotating log file, not just stdout,
    since this runs unattended."""
    logger = logging.getLogger("fpl_agent.scheduler")

    resources = check_resources()
    if resources.defer:
        logger.info("run-scheduled deferred: %s", resources.defer_reason)
        click.echo(f"deferred: {resources.defer_reason}")
        return

    try:
        summary = run_sync()
    except (SourceFetchError, ValidationError) as e:
        logger.error("run-scheduled sync failed: %s", e)
        click.echo(f"sync failed: {e}", err=True)
        raise SystemExit(1)

    logger.info(
        "run-scheduled sync ok: %d lifecycle events, %d setpiece events, retrieved_at=%s",
        summary["lifecycle_events"], summary["setpiece_events"], summary["retrieved_at"],
    )

    conn = get_connection()
    alerts = deliver_pending_alerts(conn, configured_notifiers(conn))
    cadence = recommended_cadence(conn)
    retighten_msg = maybe_retighten_scheduler(conn)
    conn.close()

    logger.info("run-scheduled delivered %d alert(s); next cadence: %s", len(alerts), cadence.reason)
    click.echo(f"sync ok - {len(alerts)} alert(s) delivered")
    click.echo(f"next recommended interval: {cadence.interval_minutes}min ({cadence.reason})")
    if retighten_msg:
        logger.info("run-scheduled: %s", retighten_msg)
        click.echo(retighten_msg)

    try:
        dashboard_path = _write_dashboard()
        logger.info("dashboard regenerated at %s", dashboard_path)
    except Exception:
        logger.exception("dashboard regeneration failed - not fatal to the sync itself")


def _dashboard_path():
    # Computed fresh per call, not as a module-level constant - the exact
    # same DATA_DIR-captured-at-import-time bug already caught once in this
    # project (monitoring/cleanup.py/storage.py) would otherwise silently
    # write to the real project data dir even when a test monkeypatches
    # DATA_DIR for isolation.
    return DATA_DIR / "dashboard.html"


def _maybe_fetch_live_payload(conn) -> dict | None:
    """Only issues a network call when a fixture is genuinely in progress -
    cheap and honest, matches this project's live-bonus CLI command's own
    fetch pattern. Returns None outside any live window (the common case,
    including all of preseason) with zero network traffic."""
    event_num = _reference_event(conn)
    if event_num is None:
        return None
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM fixtures WHERE event=? AND started=1 AND finished=0", (event_num,)
    ).fetchone()
    if not row or not row["n"]:
        return None
    try:
        payload = FPLApiAdapter().fetch_event_live(event_num).data
    except SourceFetchError as e:
        update_source_health(conn, f"fpl_api_event_live_{event_num}", success=False, error=str(e))
        return None
    update_source_health(conn, f"fpl_api_event_live_{event_num}", success=True)
    return payload


def _write_dashboard() -> None:
    conn = get_connection()
    try:
        live_payload = _maybe_fetch_live_payload(conn)
        html_content = generate_dashboard_html(conn, live_payload=live_payload)
    finally:
        conn.close()
    path = _dashboard_path()
    path.write_text(html_content, encoding="utf-8")
    return path


@cli.command()
def dashboard():
    """Generate (or regenerate) the local auto-refreshing HTML dashboard -
    the same one `fpl run-scheduled` regenerates every cycle. Open
    data/dashboard.html in a browser and leave the tab open; it reloads
    itself every 5 minutes to show whatever the last sync produced. A
    published, always-fresh, no-Claude-open public WEBSITE isn't reachable
    with this project's local, free-resources-only architecture (a
    published Artifact page can't read this local database or fetch
    external data on its own) - this is the honest, real equivalent: local,
    genuinely automatic once the scheduler is running, zero extra cost."""
    path = _write_dashboard()
    click.echo(f"wrote {path}")
    click.echo("open it in a browser and leave the tab open - it auto-reloads every 5 minutes")


@cli.command()
@click.option("--limit", default=20, help="max players to show")
@click.option("--position", default=None, help="filter by GKP/DEF/MID/FWD")
@click.option("--gw-window", default=1, help="fixtures averaged into the per-match estimate")
def projections(limit: int, position: str | None, gw_window: int):
    """Top players by expected points. Calibrated model (Dixon-Coles + devigged
    odds + shrinkage-regressed player rates) - see models/expected_points.py's
    docstring for what each component is and is not."""
    conn = get_connection()
    results = []
    for r in conn.execute("SELECT id, web_name FROM players WHERE removed=0").fetchall():
        ep = expected_points(conn, r["id"], n_gw=gw_window)
        if position and ep.position != position.upper():
            continue
        results.append((r["web_name"], ep))
    conn.close()

    results.sort(key=lambda x: x[1].median, reverse=True)
    click.echo(f"model_version={MODEL_VERSION} (see models/expected_points.py for component caveats)")
    for name, ep in results[:limit]:
        click.echo(
            f"{name:<20} {ep.position:<4} floor={ep.floor:>5} median={ep.median:>5} "
            f"ceiling={ep.ceiling:>5} conf={ep.confidence:<6} exp_min={ep.expected_minutes:>4}"
        )


@cli.command("source-status")
def source_status():
    """Show last success/failure per data source."""
    conn = get_connection()
    statuses = get_source_health(conn)
    conn.close()
    if not statuses:
        click.echo("no sources synced yet — run `fpl sync`")
        return
    for s in statuses:
        state = "OK" if s.failure_count == 0 and s.last_success else "DEGRADED"
        click.echo(f"{s.source_name:<20} {state:<9} last_success={s.last_success} failures={s.failure_count} latency={s.latency_ms}ms")


_SCHEDULER_TASK_NAME = "FPLAgentSync"  # must match scripts/setup_scheduler.ps1's default


@cli.command("scheduler-status")
def scheduler_status():
    """Check whether the Windows Task Scheduler entry exists and when it last/next ran."""
    if sys.platform != "win32":
        click.echo("scheduler-status only supports Windows Task Scheduler currently")
        return

    info = check_scheduler_registered(_SCHEDULER_TASK_NAME)
    if info is None:
        click.echo(f"task '{_SCHEDULER_TASK_NAME}' not registered")
        click.echo("register with: powershell -ExecutionPolicy Bypass -File scripts\\setup_scheduler.ps1")
        return

    click.echo(f"task '{_SCHEDULER_TASK_NAME}':")
    for key, value in info.items():
        click.echo(f"  {key}={value}")


@cli.command("live-bonus")
@click.option("--event", "event_num", default=None, type=int, help="gameweek number (default: current/next event)")
def live_bonus_cmd(event_num: int | None):
    """Real-time provisional bonus points from FPL's own official live-event
    endpoint (Tier 1, not a model) - the top 3 BPS scorers in each currently
    in-progress or just-finished fixture, real official 3-2-1 tie handling.
    Empty before kickoff and for any gameweek that hasn't started - that's
    the honest state, not a failure. Single-shot like every other command
    here; for a live-updating terminal view during an actual match, run this
    in your own shell loop (e.g. `while true; do fpl live-bonus; sleep 30; done`
    on bash, or the PowerShell equivalent)."""
    conn = get_connection()
    if event_num is None:
        event_num = _reference_event(conn)
        if event_num is None:
            click.echo("no reference gameweek found (no upcoming fixtures)", err=True)
            conn.close()
            raise SystemExit(1)

    adapter = FPLApiAdapter()
    try:
        payload = adapter.fetch_event_live(event_num).data
    except SourceFetchError as e:
        update_source_health(conn, f"fpl_api_event_live_{event_num}", success=False, error=str(e))
        click.echo(f"live-bonus failed: {e}", err=True)
        conn.close()
        raise SystemExit(1)
    update_source_health(conn, f"fpl_api_event_live_{event_num}", success=True)

    rows = compute_live_bonus(conn, payload)
    conn.close()

    if not rows:
        click.echo(f"no live data for event {event_num} yet - not kicked off, or the gameweek has no minutes played")
        return

    click.echo(f"{'Fixture':>7} {'Player':<20} {'BPS':>4} {'Bonus':>5} {'Confirmed':>9}  Min  G  A")
    current_fixture = None
    for r in rows:
        if r.fixture_id != current_fixture:
            if current_fixture is not None:
                click.echo()
            current_fixture = r.fixture_id
        confirmed = str(r.confirmed_bonus) if r.confirmed_bonus is not None else "-"
        click.echo(
            f"{r.fixture_id:>7} {r.web_name:<20} {r.bps:>4} {r.provisional_bonus:>5} {confirmed:>9}  "
            f"{r.minutes:>3}  {r.goals_scored}  {r.assists}"
        )


@cli.command("live-watch")
@click.option("--squad", "squad_arg", default=None,
              help="comma-separated player ids to track (default: the current recommended squad)")
@click.option("--interval", default=75, type=int, help="poll interval in seconds (default 75)")
@click.option("--max-hours", default=3.0, type=float, help="safety cap on total watch duration")
@click.option("--deliver/--no-deliver", default=True,
              help="push through configured notifiers (terminal always; Telegram/Discord if configured) - "
                   "--no-deliver prints to terminal only, bypassing config")
def live_watch_cmd(squad_arg: str | None, interval: int, max_hours: float, deliver: bool):
    """Fast-polling live-match watch: pushes a notification the moment a
    tracked squad player scores, assists, gains provisional bonus, or is
    sent off - diffed against FPL's own official live-event feed, real
    Tier 1 data, never fabricated. A deliberate, narrow exception to this
    project's 'single-shot command, no permanent background loop'
    convention (see `fpl live-bonus`'s own docstring): detecting a NEW
    goal needs a diff against the previous poll, and that diff state is
    far simpler to keep in one running process's memory across a ~75s
    cadence than to persist and reconcile across ~80 separate single-shot
    invocations over a ~2-hour match window. Run this yourself during a
    live gameweek (e.g. in its own terminal) - it is NOT registered with
    the Windows Task Scheduler, matching the same explicit-opt-in bar this
    project already applied to the regular sync scheduler. Stops
    automatically once every fixture in the reference gameweek is
    finished, hits --max-hours, or is interrupted with Ctrl+C."""
    conn = get_connection()

    if squad_arg:
        try:
            squad_ids = {int(x) for x in squad_arg.split(",") if x.strip()}
        except ValueError:
            click.echo("--squad must be a comma-separated list of player ids", err=True)
            conn.close()
            raise SystemExit(1)
    else:
        report = generate_build_team_report(conn)
        if not report.structures or not report.structures[0].result.squad:
            click.echo("no squad available - pass --squad explicitly or run fpl build-team first", err=True)
            conn.close()
            raise SystemExit(1)
        squad_ids = {c.player_id for c in report.structures[0].result.squad}
        click.echo(f"no --squad given - tracking the current recommended squad ({len(squad_ids)} players)")

    event_num = _reference_event(conn)
    if event_num is None:
        click.echo("no reference gameweek found (no upcoming fixtures)", err=True)
        conn.close()
        raise SystemExit(1)

    notifier = configured_notifiers(conn) if deliver else TerminalNotifier()
    adapter = FPLApiAdapter()
    poll_state: dict[int, LiveBonusRow] = {}
    stop_at = time.monotonic() + max_hours * 3600
    click.echo(
        f"watching event {event_num}, squad {sorted(squad_ids)}, every {interval}s "
        f"(max {max_hours}h) - Ctrl+C to stop"
    )

    try:
        while time.monotonic() < stop_at:
            totals = conn.execute(
                "SELECT COUNT(*) AS total, SUM(finished) AS done FROM fixtures WHERE event=?", (event_num,)
            ).fetchone()
            if totals and totals["total"] and totals["done"] == totals["total"]:
                click.echo("all fixtures finished for this gameweek - stopping")
                break

            try:
                payload = adapter.fetch_event_live(event_num).data
            except SourceFetchError as e:
                update_source_health(conn, f"fpl_api_event_live_{event_num}", success=False, error=str(e))
                click.echo(f"poll failed: {e} - retrying next cycle", err=True)
                time.sleep(interval)
                continue
            update_source_health(conn, f"fpl_api_event_live_{event_num}", success=True)

            rows = [r for r in compute_live_bonus(conn, payload) if r.player_id in squad_ids]
            events, poll_state = diff_live_rows(poll_state, rows)
            for ev in events:
                alert = Alert(
                    change_event_id=0, event_type=ev.kind, entity="player", entity_id=ev.player_id,
                    severity="HIGH", old_value=ev.web_name, new_value=ev.detail,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                )
                notifier.send(alert)

            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nstopped")
    finally:
        conn.close()


@cli.command()
def injuries():
    """List players not fully available (status/chance-of-playing derived, official source)."""
    conn = get_connection()
    players = list_availability(conn, unavailable_only=True)
    conn.close()
    if not players:
        click.echo("no availability concerns")
        return
    for p in players:
        chance = p.chance_of_playing_this_round
        chance_str = f"{chance}%" if chance is not None else "?"
        click.echo(f"{p.web_name:<20} {p.team:<4} {p.classification:<22} chance={chance_str:<5} {p.news or ''}")


@cli.command()
@click.option("--limit", default=20, help="max events to show")
@click.option("--type", "event_type", default=None, help="filter to one event_type, e.g. new_player")
def changes(limit: int, event_type: str | None):
    """Show recent change events (new/removed players, club changes, status changes, set pieces)."""
    conn = get_connection()
    if event_type:
        rows = conn.execute(
            "SELECT event_type, entity, entity_id, old_value, new_value, detected_at, severity "
            "FROM change_events WHERE event_type=? ORDER BY detected_at DESC, id DESC LIMIT ?",
            (event_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT event_type, entity, entity_id, old_value, new_value, detected_at, severity "
            "FROM change_events ORDER BY detected_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    if not rows:
        click.echo("no changes recorded yet — run `fpl sync`")
        return
    for r in rows:
        click.echo(
            f"{r['detected_at']}  {r['severity']:<8} {r['event_type']:<16} "
            f"{r['entity']}#{r['entity_id']}  {r['old_value']} -> {r['new_value']}"
        )


@cli.command()
@click.option("--deliver", is_flag=True, help="mark alerts as delivered so they won't show again")
def alerts(deliver: bool):
    """Show pending HIGH+ severity alerts (section 84-86). Terminal channel
    always fires; Telegram/Discord also fire if configured (.env.example)."""
    conn = get_connection()

    if deliver:
        sent = deliver_pending_alerts(conn, configured_notifiers(conn))  # notifier.send() does the printing
        if not sent:
            click.echo("no pending alerts")
    else:
        pending = pending_alerts(conn)
        if not pending:
            click.echo("no pending alerts")
        for a in pending:
            click.echo(
                f"[{a.severity}] {a.event_type} {a.entity}#{a.entity_id}: "
                f"{a.old_value} -> {a.new_value}  ({a.detected_at})"
            )

    conn.close()


def _parse_squad_option(squad: str | None) -> list[int] | None:
    if not squad:
        return None
    return [int(x) for x in squad.split(",")]


@cli.command("build-team")
@click.option("--sync/--no-sync", default=True, help="refresh data before building (default: yes)")
def build_team(sync: bool):
    """Section 92-94: full first-team workflow. Three structures (best EV / best
    flexibility / best upside), captain/vice, risks, narrowly-missed players,
    pre-GW1 watchlist. This is section 61's optimiser plus context - not a
    separate model, so it inherits every caveat of the calibrated-v2 xP model."""
    if sync:
        try:
            run_sync()
        except (SourceFetchError, ValidationError) as e:
            click.echo(f"sync failed: {e}", err=True)
            raise SystemExit(1)

    conn = get_connection()
    checks = run_checks()
    if not all(c.ok for c in checks):
        click.echo("WARNING: doctor checks not all OK - results may be degraded:", err=True)
        for c in checks:
            if not c.ok:
                click.echo(f"  {c.name}: {c.detail}", err=True)

    report = generate_build_team_report(conn)
    primary = report.structures[0]

    if not primary.result.squad:
        click.echo(f"could not build a squad: {primary.result.status}", err=True)
        conn.close()
        raise SystemExit(1)

    # NOT primary.result.total_xp - that sums the full 15-man squad at equal
    # weight (bench included, captain not doubled), which understates the real
    # projected GW score. The honest figure is the 11 starters plus one extra
    # copy of the captain's median (real FPL scoring doubles the armband).
    gw1_xp = round(
        sum(c.median for c in primary.xi.starting)
        + (primary.xi.captain.median if primary.xi.captain else 0.0),
        2,
    )
    five_gw_xp = sum(
        expected_points_window(conn, c.player_id, n_gw=5).total_median for c in primary.xi.starting
    )

    detail = {
        "structures": {
            s.label: {
                "cost": s.result.total_cost_tenths / 10, "total_xp": s.result.total_xp,
                "squad": [c.web_name for c in s.result.squad],
            }
            for s in report.structures
        },
        "captain": report.captain.web_name if report.captain else None,
        "vice": report.vice.web_name if report.vice else None,
        "risks": report.risks,
        "narrowly_missed": [c.web_name for c in report.narrowly_missed],
        "watchlist": report.watchlist,
    }
    decision_id = log_decision(
        conn, "build_team", f"first team: {primary.label}, total_xp={gw1_xp}",
        detail, model_version=MODEL_VERSION,
        confidence=report.captain.confidence if report.captain else None,
    )
    conn.close()

    click.echo(f"model_version={MODEL_VERSION} (see models/expected_points.py for component caveats)  decision_id={decision_id}")
    click.echo()
    click.echo(f"{'Pos':<4} {'Player':<20} {'Price':>7} {'Start%':>7} {'xP':>6}  Risk")
    for c in primary.xi.starting:
        start_pct = min(c.expected_minutes / 90 * 100, 100)
        tag = " (C)" if c is primary.xi.captain else " (VC)" if c is primary.xi.vice_captain else ""
        click.echo(f"{c.position:<4} {c.web_name:<20} £{c.price_tenths/10:>5.1f}m {start_pct:>6.0f}% {c.median:>6.2f}  {c.confidence}{tag}")
    click.echo("-- bench --")
    for c in primary.xi.bench:
        start_pct = min(c.expected_minutes / 90 * 100, 100)
        click.echo(f"{c.position:<4} {c.web_name:<20} £{c.price_tenths/10:>5.1f}m {start_pct:>6.0f}% {c.median:>6.2f}  {c.confidence}")

    click.echo()
    click.echo(f"Total Cost:            £{primary.result.total_cost_tenths/10:.1f}m")
    click.echo(f"GW1 expected points:   {gw1_xp}")
    click.echo(f"First 5-GW xP (XI):    {round(five_gw_xp, 2)}")
    click.echo(f"Captain:               {report.captain.web_name if report.captain else 'n/a'}")
    click.echo(f"Vice:                  {report.vice.web_name if report.vice else 'n/a'}")
    click.echo(f"Bench order:           {', '.join(c.web_name for c in primary.xi.bench)}")

    click.echo()
    for s in report.structures[1:]:
        click.echo(f"Alternative [{s.label}]: cost=£{s.result.total_cost_tenths/10:.1f}m total_xp={s.result.total_xp}")

    click.echo()
    click.echo("Major risks:" if report.risks else "Major risks: none flagged")
    for r in report.risks:
        click.echo(f"  - {r}")

    click.echo("Players narrowly missed:")
    for c in report.narrowly_missed:
        click.echo(f"  {c.position} {c.web_name} (xP={c.median})")

    click.echo("Pre-GW1 watchlist:" if report.watchlist else "Pre-GW1 watchlist: none")
    for w in report.watchlist:
        click.echo(f"  - {w}")

    click.echo()
    click.echo(f"Last verified: {report.retrieved_at}")


@cli.command("build-squad")
@click.option("--gw-window", default=1, help="xP window used to pick the squad")
def build_squad(gw_window: int):
    """Optimise a 15-man squad under budget/position/club-limit constraints (ILP)."""
    conn = get_connection()
    result = optimise_squad(conn, n_gw=gw_window)
    if result.status != "Optimal":
        click.echo(f"solver status: {result.status}", err=True)
        raise SystemExit(1)

    xi = pick_starting_xi(conn, result.squad)

    decision_id = log_decision(
        conn, "squad",
        summary=f"squad built: total_xp={result.total_xp}, cost=£{result.total_cost_tenths/10:.1f}m",
        detail={
            "squad": [{"player_id": c.player_id, "web_name": c.web_name, "position": c.position, "xp": c.xp} for c in result.squad],
            "captain": xi.captain.web_name if xi.captain else None,
            "vice_captain": xi.vice_captain.web_name if xi.vice_captain else None,
            "gw_window": gw_window,
        },
        model_version=MODEL_VERSION,
    )
    conn.close()

    click.echo(f"model_version={MODEL_VERSION} (see models/expected_points.py for component caveats)  decision_id={decision_id}")
    click.echo(f"total cost: £{result.total_cost_tenths / 10:.1f}m   total xP: {result.total_xp}")
    click.echo()
    click.echo("STARTING XI")
    for c in xi.starting:
        tag = " (C)" if c is xi.captain else " (VC)" if c is xi.vice_captain else ""
        click.echo(f"  {c.position:<4} {c.web_name:<20} {c.team_short:<4} £{c.price_tenths/10:>4.1f} xp={c.xp:>5.2f}{tag}")
    click.echo("BENCH")
    for c in xi.bench:
        click.echo(f"  {c.position:<4} {c.web_name:<20} {c.team_short:<4} £{c.price_tenths/10:>4.1f} xp={c.xp:>5.2f}")
    click.echo()
    click.echo(f"player ids for fpl captain/fpl chips: {','.join(str(c.player_id) for c in result.squad)}")


@cli.command()
@click.option("--squad", required=True, help="comma-separated player ids (from fpl build-squad)")
def captain(squad: str):
    """Rank a squad's captaincy options for the next fixture."""
    conn = get_connection()
    report = captaincy_report(conn, _parse_squad_option(squad))

    if report.best is None:
        conn.close()
        click.echo("no valid squad")
        return

    decision_id = log_decision(
        conn, "captain",
        summary=f"best={report.best.web_name} (median={report.best.median})",
        detail={
            "best": report.best.web_name, "second": report.second.web_name if report.second else None,
            "safe": report.safe.web_name if report.safe else None,
            "high_upside": report.high_upside.web_name if report.high_upside else None,
            "risks": report.risks,
        },
        confidence=report.best.confidence,
    )
    conn.close()
    click.echo(f"decision_id={decision_id}")

    def _line(label, o):
        if o is None:
            click.echo(f"{label:<12} none")
            return
        vs = f"vs {o.opponent_short}" if o.opponent_short else "no fixture"
        home = "(H)" if o.is_home else "(A)" if o.is_home is not None else ""
        click.echo(f"{label:<12} {o.web_name:<18} median={o.median:>5} ceiling={o.ceiling:>5} {vs}{home} conf={o.confidence}")

    _line("best", report.best)
    _line("second", report.second)
    _line("safe", report.safe)
    _line("high_upside", report.high_upside)
    if report.risks:
        click.echo("risks:")
        for r in report.risks:
            click.echo(f"  - {r}")


@cli.command()
@click.option("--squad", default=None, help="comma-separated player ids - omit to only show window eligibility")
def chips(squad: str | None):
    """Chip window eligibility + single-decision-point heuristic value. Not season-long
    chip scheduling - see optimization/chips.py docstring for why."""
    conn = get_connection()
    for w in eligible_chips(conn):
        mark = "ELIGIBLE" if w.eligible_now else "-"
        click.echo(f"{w.name:<10} #{w.number} GW{w.start_event}-{w.stop_event} {mark}")

    squad_ids = _parse_squad_option(squad)
    if squad_ids:
        bb = bench_boost_value(conn, squad_ids)
        tc = triple_captain_value(conn, squad_ids)
        wc = wildcard_value(conn, squad_ids, n_gw=5)
        fh = freehit_value(conn, squad_ids)
        click.echo()
        click.echo(f"bench boost value:    {bb} xP")
        click.echo(f"triple captain value: {tc} xP")
        click.echo(f"wildcard value (5gw): {wc} xP")
        click.echo(f"free hit value:       {fh} xP")
        decision_id = log_decision(
            conn, "chip",
            summary=f"bboost={bb} tc={tc} wildcard={wc} freehit={fh}",
            detail={"bench_boost": bb, "triple_captain": tc, "wildcard_5gw": wc, "free_hit": fh},
        )
        click.echo(f"decision_id={decision_id}")
    conn.close()


@cli.command()
@click.option("--squad", required=True, help="comma-separated player ids (from fpl build-squad)")
@click.option("--bank", default=0.0, help="bank in £m, e.g. 0.5")
@click.option("--free-transfers", default=1, type=int)
@click.option("--gw-window", default=3, type=int, help="EV window for the comparison")
@click.option("--search", is_flag=True, default=False, help="run the multi-GW beam search instead of the single-swap comparison")
@click.option("--horizon", default=5, type=int, help="beam search horizon in GWs (only with --search)")
@click.option("--beam-width", default=8, type=int, help="beam search width (only with --search)")
def transfers(squad: str, bank: float, free_transfers: int, gw_window: int, search: bool, horizon: int, beam_width: int):
    """Roll vs best transfer, compared on windowed net EV (not single-GW xP) - section 62.
    --search runs a multi-GW beam search instead (Pillar 1 Plan 1a)."""
    conn = get_connection()
    squad_ids = _parse_squad_option(squad)

    if search:
        sequences = search_transfer_sequences(
            conn, squad_ids, free_transfers=free_transfers, bank_tenths=round(bank * 10),
            horizon_gw=horizon, beam_width=beam_width,
        )
        best = sequences[0] if sequences else None
        detail = {
            "horizon_gw": horizon, "beam_width": beam_width,
            "sequences": [
                {
                    "total_net_ev": s.total_net_ev,
                    "tiebreak_adjustment": s.tiebreak_adjustment,
                    "steps": [
                        {"event": st.event, "out": st.player_out_name, "in": st.player_in_name, "uses_hit": st.uses_hit}
                        for st in s.steps
                    ],
                }
                for s in sequences
            ],
        }
        summary = f"best sequence net_ev={best.total_net_ev}" if best else "no sequence found"
        decision_id = log_decision(conn, "transfer_search", summary=summary, detail=detail, confidence="low")
        conn.close()

        click.echo(f"decision_id={decision_id}")
        if best is None:
            click.echo("no sequence found")
            return
        click.echo(f"best sequence total net EV: {best.total_net_ev} (tiebreak adjustment: {best.tiebreak_adjustment}, not included above)")
        for st in best.steps:
            if st.player_out_id is None:
                click.echo(f"  GW{st.event}: roll")
            else:
                hit = " (HIT)" if st.uses_hit else ""
                click.echo(f"  GW{st.event}: {st.player_out_name} -> {st.player_in_name}{hit}")
        return

    rec = recommend_transfer(conn, squad_ids, bank_tenths=round(bank * 10), free_transfers=free_transfers, n_gw=gw_window)

    detail = {"action": rec.action, "reason": rec.reason, "gw_window": gw_window}
    if rec.best_candidate:
        c = rec.best_candidate
        detail["candidate"] = {
            "out": c.player_out_name, "in": c.player_in_name,
            "net_ev_1gw": c.net_ev_1gw, "net_ev_3gw": c.net_ev_3gw, "net_ev_5gw": c.net_ev_5gw,
            "uses_hit": c.uses_hit,
        }
    decision_id = log_decision(conn, "transfer", summary=rec.reason, detail=detail)
    conn.close()

    click.echo(f"action: {rec.action}  decision_id={decision_id}")
    click.echo(f"reason: {rec.reason}")
    if rec.best_candidate:
        c = rec.best_candidate
        click.echo(
            f"{c.player_out_name} -> {c.player_in_name}  "
            f"1gw={c.net_ev_1gw:+.2f} 3gw={c.net_ev_3gw:+.2f} 5gw={c.net_ev_5gw:+.2f}  "
            f"price_delta=£{c.price_delta_tenths/10:+.1f}m  hit={c.uses_hit}"
        )


@cli.command("season-sim")
@click.option("--squad", required=True, help="comma-separated player ids")
@click.option("--trials", default=1000, type=int, help="number of Monte Carlo scenario trials")
@click.option("--horizon", default=5, type=int, help="horizon in GWs")
@click.option("--used-chips", default="", help="comma-separated chip names already used this season (e.g. wildcard,bboost) - excluded from scheduling")
def season_sim(squad: str, trials: int, horizon: int, used_chips: str):
    """Season-long risk bands (P10/P50/P90) and chip timing from real sampled
    scenarios, not a single point estimate (Pillar 1 Plan 1b)."""
    conn = get_connection()
    try:
        squad_ids = _parse_squad_option(squad)
        if not squad_ids:
            click.echo("no squad provided")
            return

        from_event = _reference_event(conn)
        sequences = search_transfer_sequences(conn, squad_ids, free_transfers=1, bank_tenths=0, horizon_gw=horizon)
        if not sequences:
            click.echo("no transfer sequence found")
            return
        trajectory = sequences[0]

        # The scenario draw must cover every player any downstream evaluation might
        # score, not just the starting squad - schedule_chips's wildcard/freehit
        # comparison scores a rebuilt squad from the full player pool, its
        # post-transfer squads (from the trajectory) can differ from squad_ids, and
        # advisory hit-candidates are players outside the squad by definition. A
        # player missing from the draw silently scores 0.0 on every trial via the
        # dict .get(..., 0.0) fallback used throughout - undercounting real value,
        # not just being conservative. Gather the full superset before sampling once.
        squad_by_event = _squad_ids_by_event(squad_ids, trajectory)
        superset_ids = set(squad_ids)
        for ids in squad_by_event.values():
            superset_ids.update(ids)
        # Both rebuild horizons: wildcard rebuilds over the full horizon, freehit
        # over a single GW, and they generally pick different players. Routed
        # through chips.py's memo so schedule_chips reuses these exact solves
        # instead of re-running the ILP.
        for rebuild_n_gw in (horizon, 1):
            superset_ids.update(c.player_id for c in _cached_optimise_squad(conn, rebuild_n_gw).squad)
        # Shared expected_points_window memo across all of these probes - keyed by
        # (player_id, n, from_event) inside evaluate_transfer, so it's safe to reuse
        # across events and keeps this scan from re-deriving the same player's window
        # EV once per candidate comparison.
        ev_cache: dict[tuple, float] = {}
        for event, ids in squad_by_event.items():
            for player_out_id in ids:
                for candidate in best_transfer_for_player(
                    conn, player_out_id, list(ids), bank_tenths=0, is_hit=True, n_gw=1, top_n=1,
                    from_event=event, cache=ev_cache,
                ):
                    superset_ids.add(candidate.player_in_id)

        scenario_draw = sample_season_scenarios(conn, list(superset_ids), from_event, horizon, n_trials=trials)
        events = range(from_event, from_event + horizon)
        season_totals = np.array([
            sum(o.points_by_event_player.get((e, pid), 0.0) for e in events for pid in squad_ids)
            for o in scenario_draw
        ])
        p10, p50, p90 = np.percentile(season_totals, [10, 50, 90])
        if season_totals.max() == 0.0:
            click.echo(
                "WARNING: every sampled trial scored exactly zero - the scenario draw likely has no usable "
                "player data for this squad/horizon (e.g. missing sync-history or backfill data), not a real "
                "zero-point forecast"
            )
        click.echo(f"P10={p10:.1f}  P50={p50:.1f}  P90={p90:.1f}  ({trials} trials, GW{from_event}-{from_event + horizon - 1})")

        squad_team_ids = {conn.execute("SELECT team_id FROM players WHERE id=?", (pid,)).fetchone()["team_id"] for pid in squad_ids}
        for a in detect_blank_double_gws(conn, from_event, horizon):
            if a.team_id in squad_team_ids:
                click.echo(f"GW{a.event}  {a.kind.upper()}  {a.team_short_name} (affects your squad)")

        windows = eligible_chips(conn, event=from_event)
        max_window_event = max((w.stop_event for w in windows), default=0)
        if from_event + horizon - 1 > max_window_event:
            click.echo(
                f"WARNING: horizon extends to GW{from_event + horizon - 1}, beyond the last known chip "
                f"window (GW{max_window_event}) - chip scheduling for GWs beyond that is not considered"
            )

        used_chip_names = {c.strip() for c in used_chips.split(",") if c.strip()}
        schedule = schedule_chips(conn, squad_ids, trajectory, windows, scenario_draw, used_chip_names=used_chip_names)
        for entry in schedule.baseline_schedule:
            click.echo(f"GW{entry.event}  {entry.chip_name}  median +{entry.expected_marginal_value:.1f}")
        for rec in schedule.advisory_hit_recommendations:
            click.echo(
                f"advisory: hit {rec.player_out_name}->{rec.player_in_name} before GW{rec.event} "
                f"{rec.chip_name} (+{rec.delta:.1f} over baseline)"
            )

        detail = {
            "squad_ids": squad_ids, "from_event": from_event, "horizon_gw": horizon, "trials": trials,
            "p10": float(p10), "p50": float(p50), "p90": float(p90),
            "chip_schedule": [
                {"event": e.event, "chip_name": e.chip_name, "expected_marginal_value": e.expected_marginal_value}
                for e in schedule.baseline_schedule
            ],
            "advisory_hit_recommendations": [
                {"event": r.event, "chip_name": r.chip_name, "player_out_id": r.player_out_id, "player_in_id": r.player_in_id, "delta": r.delta}
                for r in schedule.advisory_hit_recommendations
            ],
        }
        decision_id = log_decision(
            conn, "season_sim", summary=f"P50={p50:.1f} over GW{from_event}-{from_event + horizon - 1}",
            detail=detail, confidence="low",
        )
        click.echo(f"decision_id={decision_id}")
    finally:
        conn.close()


@cli.command()
@click.option("--limit", default=20, help="max changes to show")
def prices(limit: int):
    """Recent player price changes (transitions only, not each player's baseline)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT h.player_id, p.web_name, h.value_tenths AS new_value, h.valid_from, "
        "(SELECT value_tenths FROM player_price_history h2 "
        " WHERE h2.player_id = h.player_id AND h2.valid_until = h.valid_from) AS old_value "
        "FROM player_price_history h JOIN players p ON p.id = h.player_id "
        "WHERE EXISTS (SELECT 1 FROM player_price_history h3 "
        "              WHERE h3.player_id = h.player_id AND h3.valid_until = h.valid_from) "
        "ORDER BY h.valid_from DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    if not rows:
        click.echo("no price changes recorded yet")
        return
    for r in rows:
        direction = "up" if r["new_value"] > r["old_value"] else "down"
        click.echo(f"{r['valid_from']}  {r['web_name']:<20} £{r['old_value']/10:.1f}m -> £{r['new_value']/10:.1f}m ({direction})")


@cli.command("fixture-watch")
@click.option("--n-gw", default=5, help="window size to scan for blanks/doubles")
def fixture_watch(n_gw: int):
    """Blank/double gameweek detection per team over the next N gameweeks (sections 67-68)."""
    conn = get_connection()
    start = _reference_event(conn)
    for a in detect_blank_double_gws(conn, start, n_gw):
        if a.kind == "blank":
            click.echo(f"GW{a.event}  BLANK   {a.team_short_name}")
        else:
            click.echo(f"GW{a.event}  DOUBLE  {a.team_short_name} ({a.fixture_count} fixtures)")
    conn.close()


@cli.command()
def backup():
    """Snapshot the DB via sqlite3's backup API. Keeps a rolling set of at most
    5 backups - not hundreds of local copies (section 112)."""
    path = create_backup()
    result = verify_backup(path)
    click.echo(f"backup created: {path.name}")
    click.echo(f"verify: {'OK' if result.ok else 'FAILED'} - {result.detail}")


@cli.command("backups")
def list_backups_cmd():
    """List available backups."""
    paths = list_backups()
    if not paths:
        click.echo("no backups yet - run `fpl backup`")
        return
    for p in paths:
        size_mb = p.stat().st_size / (1024 * 1024)
        click.echo(f"{p.name}  {size_mb:.2f}MB")


@cli.command("verify-backup")
@click.argument("name")
def verify_backup_cmd(name: str):
    """Check a backup's integrity (PRAGMA integrity_check + migration count)."""
    result = verify_backup(BACKUP_DIR / name)
    click.echo(f"{'OK' if result.ok else 'FAILED'} - {result.detail}")
    if not result.ok:
        raise SystemExit(1)


@cli.command()
@click.argument("name")
@click.option("--yes", is_flag=True, help="required to actually perform the restore")
def restore(name: str, yes: bool):
    """Overwrite the live DB with a backup. Destructive - takes a safety backup of
    the pre-restore state first, but still requires --yes to actually run."""
    path = BACKUP_DIR / name
    if not yes:
        result = verify_backup(path)
        click.echo(f"would restore from {name} (verify: {'OK' if result.ok else 'FAILED'} - {result.detail})")
        click.echo("re-run with --yes to actually perform the restore")
        return

    safety_backup = restore_backup(path)
    click.echo(f"restored from {name}")
    click.echo(f"pre-restore state saved as {safety_backup.name}")


@cli.command()
def cleanup():
    """Prune expired raw payloads, clear temp files, reclaim DB free space (VACUUM).
    Never touches players/decisions/rules/user state (sections 15/111)."""
    conn = get_connection()
    report = run_cleanup(conn)
    conn.close()
    click.echo(f"raw files pruned:  {report.raw_files_pruned}")
    click.echo(f"temp files cleared: {report.temp_files_cleared}")
    click.echo(f"news items pruned: {report.news_items_pruned}")
    click.echo(f"DB space reclaimed: {report.vacuum_freed_mb}MB")


@cli.command()
@click.option("--limit", default=20, help="max decisions to show")
@click.option("--type", "decision_type", default=None, help="filter by decision_type: squad/captain/transfer/chip/transfer_search")
def decisions(limit: int, decision_type: str | None):
    """List the decision journal (section 71) - every recommendation ever generated."""
    conn = get_connection()
    all_decisions = list_decisions(conn, limit=limit * 3 if decision_type else limit)
    conn.close()
    if decision_type:
        all_decisions = [d for d in all_decisions if d.decision_type == decision_type][:limit]
    if not all_decisions:
        click.echo("no decisions recorded yet")
        return
    for d in all_decisions:
        click.echo(f"#{d.id:<4} {d.created_at}  {d.decision_type:<16} {d.summary}")


@cli.command()
@click.argument("decision_id", type=int)
def why(decision_id: int):
    """Section 72 decision trace, as far as stored data allows: Decision + Evidence
    + confidence. Full Alternatives/Risks/Trigger synthesis needs the transfer-analyst
    or decision-auditor subagent - this command surfaces facts, not fresh reasoning."""
    conn = get_connection()
    d = get_decision(conn, decision_id)
    conn.close()
    if d is None:
        click.echo(f"no decision #{decision_id}", err=True)
        raise SystemExit(1)

    click.echo(f"Decision   #{d.id} ({d.decision_type}) - {d.created_at}")
    click.echo(f"Summary    {d.summary}")
    click.echo(f"Model      {d.model_version or 'n/a'}")
    click.echo(f"Confidence {d.confidence or 'n/a'}")
    click.echo("Evidence:")
    for key, value in d.detail.items():
        click.echo(f"  {key}: {value}")
    click.echo()
    click.echo("(Alternatives/Risks/Trigger not stored - ask the transfer-analyst or")
    click.echo(" decision-auditor subagent for a full section-72 trace on this decision.)")


@cli.command("final-check")
@click.option("--squad", required=True, help="comma-separated player ids")
@click.option("--bank", default=0.0, help="bank in £m")
@click.option("--free-transfers", default=1, type=int)
@click.option("--sync/--no-sync", default=True, help="refresh data before checking (default: yes)")
def final_check(squad: str, bank: float, free_transfers: int, sync: bool):
    """Section 91's deadline-critical workflow: sync, injuries, changes, captain,
    transfers, chips - all against one squad, in one FINAL VERDICT."""
    if sync:
        try:
            run_sync()
        except (SourceFetchError, ValidationError) as e:
            click.echo(f"sync failed: {e}", err=True)
            raise SystemExit(1)

    squad_ids = _parse_squad_option(squad)
    conn = get_connection()

    pool = build_player_pool(conn, n_gw=1)
    squad_candidates = [c for c in pool if c.player_id in squad_ids]
    xi = pick_starting_xi(conn, squad_candidates) if squad_candidates else None

    squad_availability = [a for a in list_availability(conn, unavailable_only=True) if a.player_id in squad_ids]

    recent_changes = conn.execute(
        "SELECT event_type, entity, entity_id, old_value, new_value, detected_at, severity "
        "FROM change_events WHERE entity='player' AND entity_id IN ({}) "
        "ORDER BY detected_at DESC LIMIT 10".format(",".join("?" * len(squad_ids))),
        squad_ids,
    ).fetchall()

    cap_report = captaincy_report(conn, squad_ids)
    transfer_rec = recommend_transfer(conn, squad_ids, bank_tenths=round(bank * 10), free_transfers=free_transfers, n_gw=3)
    chip_windows = eligible_chips(conn)
    eligible_now = [w for w in chip_windows if w.eligible_now]
    bb_value = bench_boost_value(conn, squad_ids) if squad_ids else 0.0

    confidences = [c.confidence for c in squad_candidates]
    overall_confidence = "LOW" if "LOW" in confidences else ("MEDIUM" if "MEDIUM" in confidences else "HIGH")

    sources = get_source_health(conn)
    data_status = "OK" if all(s.failure_count == 0 for s in sources) else "DEGRADED"

    detail = {
        "squad_ids": squad_ids, "transfer_action": transfer_rec.action,
        "captain": cap_report.best.web_name if cap_report.best else None,
        "vice": cap_report.second.web_name if cap_report.second else None,
        "availability_flags": [a.web_name for a in squad_availability],
        "changes_count": len(recent_changes),
    }
    decision_id = log_decision(
        conn, "final_check", f"final check: {len(squad_ids)}-player squad, transfer={transfer_rec.action}",
        detail, confidence=overall_confidence,
    )
    conn.close()

    if squad_availability or recent_changes:
        click.echo("SQUAD-RELEVANT CHANGES (review before trusting the verdict below):")
        for a in squad_availability:
            click.echo(f"  - {a.web_name}: {a.classification} - {a.news or 'no detail'}")
        for r in recent_changes:
            click.echo(f"  - {r['detected_at']} {r['severity']} {r['event_type']} player#{r['entity_id']}: {r['old_value']} -> {r['new_value']}")
        click.echo()

    click.echo("FINAL VERDICT")
    click.echo()
    click.echo(f"Transfer:      {transfer_rec.action} - {transfer_rec.reason}")
    click.echo(f"Captain:       {cap_report.best.web_name if cap_report.best else 'n/a'}")
    click.echo(f"Vice:          {cap_report.second.web_name if cap_report.second else 'n/a'}")
    if xi:
        click.echo(f"Starting XI:   {', '.join(c.web_name for c in xi.starting)}")
        click.echo(f"Bench:         {', '.join(c.web_name for c in xi.bench)}")
    else:
        click.echo("Starting XI:   could not be determined (squad ids not found in current pool)")
    click.echo(f"Chip:          {', '.join(w.name for w in eligible_now) or 'none eligible'} "
               f"(bench boost value if used: {bb_value} xP)")
    click.echo(f"Confidence:    {overall_confidence}")
    click.echo(f"Data status:   {data_status}")
    click.echo(f"decision_id={decision_id}")


@cli.command("rate-team")
@click.option("--squad", required=True, help="comma-separated player ids (any 15, not necessarily one this project built)")
@click.option("--sync/--no-sync", default=True, help="refresh data before rating (default: yes)")
def rate_team_cmd(squad: str, sync: bool):
    """Rate My Team (section-adjacent, competitor-scope closure): score an
    EXISTING squad - your own real team, or one drafted anywhere else - the
    same way FPL Copilot/Fantasy Football Hub's "Rate My Team" tools do.
    efficiency_percent is real, not fabricated: this squad's GW1 xP as a
    percentage of the best achievable squad's xP under the same budget."""
    if sync:
        try:
            run_sync()
        except (SourceFetchError, ValidationError) as e:
            click.echo(f"sync failed: {e}", err=True)
            raise SystemExit(1)

    squad_ids = _parse_squad_option(squad)
    conn = get_connection()
    rating = rate_team(conn, squad_ids)

    if rating.duplicate_ids:
        click.echo(f"WARNING: duplicate id(s) in squad, a real squad can't own the same player twice - deduplicated: {rating.duplicate_ids}", err=True)
    if rating.invalid_ids:
        click.echo(f"WARNING: {len(rating.invalid_ids)} id(s) not found in the current player pool: {rating.invalid_ids}", err=True)
    if rating.rule_violations:
        click.echo("WARNING: this squad does not satisfy real FPL squad-construction rules:", err=True)
        for v in rating.rule_violations:
            click.echo(f"  - {v}", err=True)

    detail = {
        "squad_ids": rating.squad_ids, "gw1_xp": rating.gw1_xp, "optimal_gw1_xp": rating.optimal_gw1_xp,
        "efficiency_percent": rating.efficiency_percent, "template_count": rating.template_count,
        "differential_ids": rating.differential_ids, "trap_ids": rating.trap_ids,
        "rule_violations": rating.rule_violations,
    }
    decision_id = log_decision(
        conn, "rate_team", f"rate team: {rating.gw1_xp} xP, {rating.efficiency_percent}% of optimal",
        detail, model_version=MODEL_VERSION, confidence=rating.captain.confidence if rating.captain else None,
    )
    conn.close()

    click.echo(f"decision_id={decision_id}")
    click.echo()
    if rating.xi.starting:
        click.echo(f"{'Pos':<4} {'Player':<20} {'Price':>7} {'xP':>6}  Risk")
        for c in rating.xi.starting:
            tag = " (C)" if rating.captain and c.player_id == rating.captain.player_id else \
                  " (VC)" if rating.vice and c.player_id == rating.vice.player_id else ""
            click.echo(f"{c.position:<4} {c.web_name:<20} £{c.price_tenths/10:>5.1f}m {c.median:>6.2f}  {c.confidence}{tag}")
        click.echo("-- bench --")
        for c in rating.xi.bench:
            click.echo(f"{c.position:<4} {c.web_name:<20} £{c.price_tenths/10:>5.1f}m {c.median:>6.2f}  {c.confidence}")
    click.echo()
    click.echo(f"Cost / Bank:          £{rating.total_cost_tenths/10:.1f}m / £{rating.bank_tenths/10:.1f}m")
    click.echo(f"GW1 expected points:  {rating.gw1_xp}")
    click.echo(f"First 5-GW xP (XI):   {rating.five_gw_xp}")
    click.echo(f"Best possible (same budget): {rating.optimal_gw1_xp} xP")
    click.echo(f"Efficiency:           {rating.efficiency_percent}% of the best achievable squad this GW")
    click.echo(f"Captain:              {rating.captain.web_name if rating.captain else 'n/a'}")
    click.echo(f"Vice:                 {rating.vice.web_name if rating.vice else 'n/a'}")
    click.echo(f"Template picks:       {rating.template_count}/15")
    click.echo(f"Real differentials:   {rating.differential_ids or 'none flagged'}")
    click.echo(f"Trap risks:           {rating.trap_ids or 'none flagged'}")
    click.echo(f"Breakout picks owned: {rating.breakout_ids or 'none'}")
    click.echo("Availability risks:" if rating.risks else "Availability risks: none flagged")
    for r in rating.risks:
        click.echo(f"  - {r}")


if __name__ == "__main__":
    cli()
