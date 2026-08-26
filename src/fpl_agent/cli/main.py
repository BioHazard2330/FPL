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
from fpl_agent.config import DATA_DIR, load_dotenv, load_storage_budget
from fpl_agent.database.backup import BACKUP_DIR, create_backup, list_backups, restore_backup, verify_backup
from fpl_agent.database.connection import get_connection
from fpl_agent.database.decisions import get_decision, list_decisions, log_decision
from fpl_agent.database.migrate import run_migrations
from fpl_agent.ingestion.eo_sample import _DEFAULT_SAMPLE_SIZE, sample_effective_ownership
from fpl_agent.ingestion.change_detection import (
    detect_predicted_lineup_status_changes,
    detect_start_percent_changes,
    detect_upcoming_kickoffs,
)
from fpl_agent.ingestion.cross_league_source import backfill_cross_league_priors
from fpl_agent.ingestion.football_data_source import backfill_football_data
from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.history_sync import sync_player_season_history
from fpl_agent.ingestion.live_rank_sample import get_live_rank_reference, sample_live_rank_reference
from fpl_agent.ingestion.my_team import (
    get_latest_squad,
    get_my_team_entry_id,
    get_used_chips,
    resolve_tracked_squad_ids,
    set_my_team_entry_id,
    set_tracked_squad_ids,
    sync_my_team,
)
from fpl_agent.ingestion.raw_store import prune_raw
from fpl_agent.ingestion.news_source import NewsFetchError, list_recent_news, sync_all_news_sources
from fpl_agent.ingestion.predicted_lineups_source import (
    PredictedLineupFetchError,
    get_predicted_lineup_for_squad,
    sync_predicted_lineups,
)
from fpl_agent.ingestion.lineup_probability_source import (
    LineupProbabilityFetchError,
    get_start_percent,
    sync_lineup_probabilities,
)
from fpl_agent.models.team_outlook import squad_team_outlooks
from fpl_agent.ingestion.fotmob_source import (
    FotMobFetchError,
    refresh_in_progress_matches,
    sync_match,
)
from fpl_agent.ingestion.qualitative_analysis import (
    QualitativeAnalysisError,
    apply_match_analysis,
    record_user_observation,
)
from fpl_agent.ingestion.analysis_queue import list_pending_jobs, mark_job_done_for_match_phase
from fpl_agent.models.match_discovery import discover_and_register_matches
from fpl_agent.optimization.post_gw_pipeline import maybe_run_post_gw_pipeline
from fpl_agent.ingestion.odds_live_source import OddsLiveFetchError, sync_live_odds
from fpl_agent.ingestion.player_odds_source import PlayerOddsFetchError, sync_player_odds
from fpl_agent.ingestion.sync import ValidationError, run_sync, update_source_health
from fpl_agent.ingestion.understat_source import backfill_understat
from fpl_agent.logging_setup import setup_logging
from fpl_agent.scheduler.adaptive import maybe_retighten_scheduler
from fpl_agent.scheduler.cadence import recommended_cadence
from fpl_agent.scheduler.resources import check_resources
from fpl_agent.scheduler.status import check_scheduler_registered
from fpl_agent.models.availability import list_availability
from fpl_agent.models.expected_points import MODEL_VERSION, expected_points, expected_points_window
from fpl_agent.models.fixtures import _reference_event, detect_blank_double_gws, live_or_reference_event
from fpl_agent.models.live_bonus import LiveBonusRow, compute_live_bonus, diff_live_rows
from fpl_agent.models.live_rank import estimate_live_rank, estimate_squad_live_points
from fpl_agent.models.scenario_engine import sample_season_scenarios
from fpl_agent.monitoring.cleanup import run_cleanup
from fpl_agent.monitoring.dashboard import _REFRESH_SECONDS, generate_dashboard_html
from fpl_agent.monitoring.doctor import run_checks
from fpl_agent.monitoring.readiness import run_readiness_checks
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.monitoring.storage import measure_storage
from fpl_agent.optimization.build_team import (
    LockedDecisionIncomplete,
    generate_build_team_report,
    resolve_locked_constraints,
)
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


@cli.command("sync-elite-panel")
@click.option("--season", required=True, help="e.g. 2026-27 - the season whose CURRENT standings to snapshot")
@click.option("--target-size", default=1000, type=int, help="real top-N finishers to capture")
@click.option("--force", is_flag=True, help="re-snapshot even if this season already has a panel")
def sync_elite_panel(season: str, target_size: int, force: bool):
    """Historical, skill-selected Elite-manager panel (2026-08-26,
    GW1-postmortem audit P1). Real, confirmed constraint: FPL's own
    standings endpoint is season-scoped to whatever is CURRENTLY live -
    there is no way to fetch a PAST season's final standings once a new one
    has started. Only genuinely meaningful as a real skill signal when run
    near a season's real END (a full season of performance), for use as
    the FOLLOWING season's panel - running it mid-season captures a
    live-standings cross-section, not yet a historically-earned one. See
    ingestion/elite_panel.py's own module docstring for the full account."""
    from fpl_agent.ingestion.elite_panel import snapshot_elite_panel

    conn = get_connection()
    try:
        result = snapshot_elite_panel(conn, season=season, target_size=target_size, force=force)
    finally:
        conn.close()

    if result["skipped"]:
        click.echo(f"season {season} already has a panel - use --force to re-snapshot")
        return
    click.echo(f"season       {result['season']}")
    click.echo(f"panel size   {result['panel_size']}")


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


@cli.command("sync-player-odds")
def sync_player_odds_cmd():
    """Fetch real per-player anytime-goalscorer odds for the tracked squad's own
    teams' upcoming fixtures (the-odds-api.com, free tier, requires ODDS_API_KEY).
    Real, per-fixture throttled (4h freshness gate) - already wired into `fpl
    run-scheduled` automatically; this command is for manual/debug use."""
    conn = get_connection()
    tracked_squad_ids = resolve_tracked_squad_ids(conn)
    try:
        result = sync_player_odds(conn, tracked_squad_ids)
    except PlayerOddsFetchError as e:
        click.echo(f"sync-player-odds failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()
    click.echo(f"fetched (fresh)  {result['fetched']}")
    click.echo(f"skipped (fresh)  {result['skipped']}")
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


@cli.command("sync-predicted-lineups")
def sync_predicted_lineups_cmd():
    """Ingest fantasyfootballscout.co.uk/team-news/ (strong-reporter tier,
    free, no login, robots.txt-permitted, verified live 2026-08-21) - real
    predicted starting XIs + out/doubt/banned status per team, matched to
    players by name within their own team, never auto-classified into a
    status change. Separate from `fpl sync`, opt-in."""
    conn = get_connection()
    try:
        result = sync_predicted_lineups(conn)
    except PredictedLineupFetchError as e:
        click.echo(f"sync-predicted-lineups failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()
    click.echo(f"teams            {result['teams']}")
    click.echo(f"players          {result['players']}")
    click.echo(f"players matched  {result['players_matched']}")
    if result["unknown_team_codes"]:
        click.echo(f"WARNING: unrecognized team codes: {result['unknown_team_codes']}", err=True)


@cli.command("sync-lineup-probability")
def sync_lineup_probability_cmd():
    """Ingest fantasyfootballpundit.com's real per-player start-PERCENTAGE
    predicted lineups (strong-reporter tier, free, no login, robots.txt-
    permitted, verified live 2026-08-21) - a richer signal than
    `sync-predicted-lineups`'s binary starting/bench flag. Feeds
    `models/expected_minutes.py` directly where it covers a player.
    Separate from `fpl sync`, opt-in."""
    conn = get_connection()
    try:
        result = sync_lineup_probabilities(conn)
    except LineupProbabilityFetchError as e:
        click.echo(f"sync-lineup-probability failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()
    click.echo(f"teams            {result['teams']}")
    click.echo(f"players          {result['players']}")
    click.echo(f"players matched  {result['players_matched']}")
    if result["unknown_teams"]:
        click.echo(f"WARNING: unrecognized team names: {result['unknown_teams']}", err=True)


@cli.command("sync-match")
@click.option("--date", "date_str", default=None, help="YYYY-MM-DD, default today (UTC)")
@click.argument("home_team")
@click.argument("away_team")
def sync_match_cmd(home_team: str, away_team: str, date_str: str | None):
    """Match Intelligence Core (Pillar 4 Slice A): resolve a real FotMob match
    id for HOME_TEAM vs AWAY_TEAM (never hardcoded - looked up via FotMob's
    date-scoped fixture list), fetch its full match payload, normalize, and
    upsert Match/PlayerMatchState/TeamMatchState. Safe to re-run - the
    intended way to refresh a LIVE match's state."""
    day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now(timezone.utc).date()
    conn = get_connection()
    try:
        result = sync_match(conn, home_team, away_team, day)
    except FotMobFetchError as e:
        click.echo(f"sync-match failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()
    click.echo(f"fotmob match id   {result['fotmob_match_id']}")
    click.echo(f"status            {result['status']}")
    click.echo(f"kickoff (UTC)     {result['kickoff_utc']}")
    click.echo(f"fixture           {result['home_team']} vs {result['away_team']}")
    click.echo(f"players ingested  {result['players_ingested']} ({result['players_resolved']} resolved to FPL ids)")
    click.echo(f"team states       {result['team_states_ingested']}")


@cli.command("match-report")
@click.argument("fotmob_match_id")
def match_report_cmd(fotmob_match_id: str):
    """Print the currently-persisted structured Match Intelligence state for a
    match already synced via `fpl sync-match`. Read-only - does not fetch or
    invoke the qualitative-analysis skill (see .claude/skills/
    match-intelligence-analysis/) itself."""
    conn = get_connection()
    match = conn.execute(
        "SELECT * FROM match_intelligence WHERE fotmob_match_id=?", (fotmob_match_id,)
    ).fetchone()
    if match is None:
        click.echo(f"no match intelligence found for fotmob match id {fotmob_match_id} - run `fpl sync-match` first", err=True)
        conn.close()
        raise SystemExit(1)

    click.echo(f"MATCH  {match['competition']}  status={match['status']}  kickoff={match['kickoff_utc']}")
    click.echo(f"       home_team_id={match['home_team_id']} away_team_id={match['away_team_id']}  "
               f"score={match['home_score']}-{match['away_score']}")
    click.echo(f"       source={match['source']} retrieved_at={match['retrieved_at']}")

    team_states = conn.execute("SELECT * FROM team_match_state WHERE match_id=?", (match["id"],)).fetchall()
    click.echo(f"\nTEAM STATES ({len(team_states)})")
    for t in team_states:
        click.echo(f"  team_id={t['team_id']} formation={t['formation']} possession={t['possession_pct']} "
                   f"shots={t['shots']} xg={t['xg']}")

    player_states = conn.execute(
        "SELECT * FROM player_match_state WHERE match_id=? ORDER BY started DESC, team_id", (match["id"],)
    ).fetchall()
    click.echo(f"\nPLAYER STATES ({len(player_states)})")
    for p in player_states:
        resolved = f"player_id={p['player_id']}" if p["player_id"] else "UNRESOLVED"
        click.echo(f"  {resolved:<18} fotmob_id={p['fotmob_player_id']:<10} team_id={p['team_id']} "
                   f"started={bool(p['started'])} goals={p['goals']} shots={p['shots']} xg={p['xg']}")

    observations = conn.execute("SELECT * FROM match_observations WHERE match_id=?", (match["id"],)).fetchall()
    click.echo(f"\nOBSERVATIONS ({len(observations)})")
    for o in observations:
        click.echo(f"  [{o['observation_type']}] OBSERVED: {o['observed']}")
        if o["inferred"]:
            click.echo(f"    INFERRED: {o['inferred']}")
        if o["fpl_direction"]:
            click.echo(f"    FPL: {o['fpl_direction']} / {o['fpl_signal']} - {o['fpl_reason']}")
    if not observations:
        click.echo("  (none yet - run the match-intelligence-analysis skill)")

    implications = conn.execute("SELECT * FROM player_fpl_implications WHERE match_id=?", (match["id"],)).fetchall()
    click.echo(f"\nFPL IMPLICATIONS ({len(implications)})")
    for i in implications:
        click.echo(f"  player_id={i['player_id']} {i['direction']}/{i['signal']} - {i['reason']} [{i['phase']}]")

    summaries = conn.execute(
        "SELECT * FROM match_analysis_summary WHERE match_id=? ORDER BY phase", (match["id"],)
    ).fetchall()
    click.echo(f"\nANALYSIS SUMMARY ({len(summaries)})")
    for s in summaries:
        tag = "" if s["phase"] == "FULL_TIME" else "  [PROVISIONAL]"
        click.echo(f"  [{s['phase']}]{tag} {s['headline']}")
        if s["uncertainties"]:
            click.echo(f"    uncertain: {s['uncertainties']}")

    player_states = conn.execute(
        "SELECT * FROM player_qualitative_state WHERE match_id=?", (match["id"],)
    ).fetchall()
    click.echo(f"\nPLAYER QUALITATIVE STATE ({len(player_states)})")
    for p in player_states:
        click.echo(f"  player_id={p['player_id']} role={p['role']} signal={p['tactical_signal']} outlook={p['fpl_outlook']} confidence={p['confidence']}")

    team_states = conn.execute(
        "SELECT * FROM team_qualitative_state WHERE match_id=?", (match["id"],)
    ).fetchall()
    click.echo(f"\nTEAM QUALITATIVE STATE ({len(team_states)})")
    for t in team_states:
        click.echo(f"  team_id={t['team_id']} tactical={t['tactical_signal']} attack={t['attacking_signal']} defence={t['defensive_signal']}")
        if t["key_observation"]:
            click.echo(f"    key observation: {t['key_observation']}")

    user_obs = conn.execute(
        "SELECT * FROM user_observations WHERE match_id=? ORDER BY created_at", (match["id"],)
    ).fetchall()
    click.echo(f"\nUSER OBSERVATIONS ({len(user_obs)})")
    for u in user_obs:
        click.echo(f"  [{u['subject_type']}:{u['subject_id']}] {u['sentiment'] or ''} {u['note']}")

    conn.close()


@cli.command("analysis-queue")
@click.option("--pending/--all", default=True, help="show only pending/processing jobs (default) or every job ever created")
def analysis_queue_cmd(pending: bool):
    """List qualitative-analysis jobs (matchday-autonomy pass, 2026-08-22) -
    the zero-cost queue FULL_TIME/HALFTIME detection writes to automatically
    (see `fpl live-match-poll`/`fpl run-scheduled`). No LLM call happens
    here or anywhere in this project's own Python runtime - this command
    only surfaces what's waiting for the next real Claude Code session's
    qualitative-analysis skill + `fpl match-analyze` to actually process.
    Also run automatically at the start of every Claude Code session for
    this project (`.claude/hooks/queue_check.py`) so a pending job is never
    silently missed."""
    conn = get_connection()
    from fpl_agent.ingestion.analysis_queue import supersede_stale_halftime_jobs
    supersede_stale_halftime_jobs(conn)
    if pending:
        jobs = list_pending_jobs(conn)
    else:
        rows = conn.execute(
            "SELECT j.id, j.match_id, j.phase, j.status, j.evidence_summary, j.created_at, "
            "mi.fotmob_match_id, mi.kickoff_utc, ht.name AS home_name, at.name AS away_name "
            "FROM qualitative_analysis_jobs j "
            "JOIN match_intelligence mi ON mi.id = j.match_id "
            "JOIN teams ht ON ht.id = mi.home_team_id JOIN teams at ON at.id = mi.away_team_id "
            "ORDER BY j.created_at"
        ).fetchall()
        from fpl_agent.ingestion.analysis_queue import AnalysisJob
        jobs = [
            AnalysisJob(
                id=r["id"], match_id=r["match_id"], fotmob_match_id=r["fotmob_match_id"], phase=r["phase"],
                status=r["status"], evidence_summary=r["evidence_summary"], created_at=r["created_at"],
                home_name=r["home_name"], away_name=r["away_name"], kickoff_utc=r["kickoff_utc"],
            )
            for r in rows
        ]
    conn.close()
    if not jobs:
        click.echo("no pending qualitative-analysis jobs" if pending else "no qualitative-analysis jobs recorded yet")
        return
    for j in jobs:
        click.echo(
            f"job={j.id:<4} [{j.status:<10}] {j.phase:<10} {j.home_name} v {j.away_name} "
            f"(fotmob={j.fotmob_match_id})  {j.evidence_summary or ''}"
        )
        click.echo(
            f"           -> fpl match-report {j.fotmob_match_id}   "
            f"then write the skill's JSON and run: fpl match-analyze {j.fotmob_match_id} "
            f"--phase {j.phase.lower()} --file <path.json>"
        )


@cli.command("post-gw-pipeline")
def post_gw_pipeline_cmd():
    """Manually trigger the deterministic post-GW pipeline check
    (automation-lifecycle pass, 2026-08-22) - the exact same
    `maybe_run_post_gw_pipeline` call `fpl run-scheduled`/`fpl
    live-match-poll` already fire automatically once a real gameweek
    finishes (see `models/gw_lifecycle.py` for the real guard against
    declaring one finished on incomplete/degraded data). No network sync
    happens here - this is a real, network-free entry point into the
    pipeline itself, useful for manual/scripted invocation and for testing
    the pipeline in isolation from the regular sync cycle."""
    conn = get_connection()
    try:
        result = maybe_run_post_gw_pipeline(conn)
    finally:
        conn.close()
    if result is None:
        click.echo("no-op - the real lifecycle state doesn't currently need the post-GW pipeline")
        return
    click.echo(f"ran={result.ran} event={result.event} reason={result.reason} decision_id={result.decision_id}")
    if result.ran:
        try:
            _write_dashboard()
            click.echo("dashboard regenerated")
        except Exception as e:
            click.echo(f"dashboard regen failed: {e}", err=True)


@cli.command("match-analyze")
@click.argument("fotmob_match_id")
@click.option("--phase", required=True, type=click.Choice(["pre_match", "live", "halftime", "full_time"], case_sensitive=False))
@click.option("--file", "payload_path", required=True, type=click.Path(exists=True), help="JSON payload written by the match-intelligence-analysis skill")
def match_analyze_cmd(fotmob_match_id: str, phase: str, payload_path: str):
    """Persist a qualitative analysis payload (Pillar 4 Slice A2). The single
    validated write path the LLM skill uses - never raw SQL from the skill
    itself. Idempotent per (match, phase); a full_time write is refused
    unless the match has genuinely finished. Marks the matching
    analysis-queue job (if one exists - matchday-autonomy pass, 2026-08-22)
    'done', closing the loop that job's automatic creation started."""
    import json

    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)

    conn = get_connection()
    match = conn.execute("SELECT id FROM match_intelligence WHERE fotmob_match_id=?", (fotmob_match_id,)).fetchone()
    if match is None:
        click.echo(f"match-analyze failed: no match intelligence found for fotmob match id {fotmob_match_id}", err=True)
        conn.close()
        raise SystemExit(1)
    try:
        result = apply_match_analysis(conn, match["id"], phase.upper(), payload)
    except QualitativeAnalysisError as e:
        click.echo(f"match-analyze failed: {e}", err=True)
        conn.close()
        raise SystemExit(1)
    mark_job_done_for_match_phase(conn, match["id"], phase.upper())
    conn.close()
    click.echo(f"phase                  {result['phase']}")
    click.echo(f"observations written   {result['observations_written']}")
    click.echo(f"implications written   {result['implications_written']}")
    click.echo(f"player states written  {result['player_states_written']}")
    click.echo(f"team states written    {result['team_states_written']}")


@cli.command("match-note")
@click.option("--player", "player_id", type=int, default=None, help="player id (mutually exclusive with --team)")
@click.option("--team", "team_id", type=int, default=None, help="team id (mutually exclusive with --player)")
@click.option("--sentiment", type=click.Choice(["positive", "negative", "neutral"]), default=None)
@click.option("--note", required=True, help="free-text observation")
@click.option("--match", "fotmob_match_id", default=None, help="fotmob match id, if this note is about a specific match")
@click.option("--phase", "phase_label", default=None, help="free-text phase label, e.g. 'second half'")
def match_note_cmd(player_id: int | None, team_id: int | None, sentiment: str | None, note: str, fotmob_match_id: str | None, phase_label: str | None):
    """Record a real USER_OBSERVATION - never merged into AI-authored
    analysis (Pillar 4 Slice A2, the seed of the future My Football View)."""
    if (player_id is None) == (team_id is None):
        click.echo("match-note failed: pass exactly one of --player or --team", err=True)
        raise SystemExit(1)
    subject_type, subject_id = ("player", player_id) if player_id is not None else ("team", team_id)

    conn = get_connection()
    match_id = None
    if fotmob_match_id is not None:
        match = conn.execute("SELECT id FROM match_intelligence WHERE fotmob_match_id=?", (fotmob_match_id,)).fetchone()
        if match is None:
            click.echo(f"match-note failed: no match intelligence found for fotmob match id {fotmob_match_id}", err=True)
            conn.close()
            raise SystemExit(1)
        match_id = match["id"]

    try:
        obs_id = record_user_observation(conn, subject_type, subject_id, note, sentiment=sentiment, match_id=match_id, phase=phase_label)
    except QualitativeAnalysisError as e:
        click.echo(f"match-note failed: {e}", err=True)
        conn.close()
        raise SystemExit(1)
    conn.close()
    click.echo(f"recorded USER_OBSERVATION #{obs_id}")


@cli.command("predicted-lineups")
@click.option("--squad", required=True, help="comma-separated player ids (from fpl build-squad)")
def predicted_lineups_cmd(squad: str):
    """Latest predicted-XI/injury-doubt read for a specific squad, from
    `fpl sync-predicted-lineups`'s last run. A player id absent below means
    no signal, not confirmed anything - see the module docstring."""
    player_ids = [int(x) for x in squad.split(",")]
    conn = get_connection()
    try:
        lineup = get_predicted_lineup_for_squad(conn, player_ids)
        names = {
            row["id"]: row["web_name"]
            for row in conn.execute(
                f"SELECT id, web_name FROM players WHERE id IN ({','.join('?' * len(player_ids))})", player_ids
            ).fetchall()
        }
    finally:
        conn.close()
    if not lineup:
        click.echo("no predicted-lineup data synced yet - run `fpl sync-predicted-lineups` first")
        return
    for pid in player_ids:
        name = names.get(pid, f"id={pid}")
        info = lineup.get(pid)
        if info is None:
            click.echo(f"{name:20} no signal (not matched in latest sync)")
            continue
        doubt = f" ({info['doubt_percent']}%)" if info["doubt_percent"] is not None else ""
        click.echo(f"{name:20} {info['team_short']:4} {info['status']}{doubt}")


@cli.command("team-outlook")
@click.option("--squad", required=True, help="comma-separated player ids (from fpl build-squad)")
def team_outlook_cmd(squad: str):
    """Real per-team qualitative read for every club your squad touches - real
    squad-turnover ratio (who actually left, minutes-weighted), recent Tier 2-4
    news, and the predicted-lineup source's own latest team-news paragraph.
    "Be an automatic football pundit" (2026-08-21) - every field here traces to
    a DB row already synced, nothing generated."""
    player_ids = [int(x) for x in squad.split(",")]
    conn = get_connection()
    try:
        outlooks = squad_team_outlooks(conn, player_ids)
    finally:
        conn.close()
    for o in outlooks:
        click.echo(f"{o.team_name}")
        click.echo(f"  squad churn: {o.churn_label}")
        if o.formation:
            click.echo(f"  predicted formation: {o.formation}")
        if o.manager_change:
            click.echo(f"  {o.manager_change}")
        if o.lineup_news:
            click.echo(f"  latest: {o.lineup_news}")
        for n in o.recent_news:
            click.echo(f"  news [{n['source_tier']}] {n['title']}")
        if o.tactics.note:
            click.echo(f"  tactical pattern: {o.tactics.note}")
        else:
            click.echo(
                f"  tactical pattern: {o.tactics.matches_observed} real matches, "
                f"formation {o.tactics.most_common_formation or '?'}, "
                f"rotation rate {o.tactics.starting_xi_rotation_rate}, "
                f"avg first sub {o.tactics.avg_first_substitution_minute}'"
            )
        if o.qualitative:
            if o.qualitative.current_tactical_signal:
                click.echo(f"  post-match read: {o.qualitative.current_tactical_signal}")
            for t in o.qualitative.trends:
                click.echo(f"    [{t.signal}] {t.label} (currently {t.current_direction}, n={t.sample_size})")
        click.echo()


@cli.command("player-intelligence")
@click.argument("player_id", type=int)
def player_intelligence_cmd(player_id: int):
    """Persistent Player Intelligence (2026-08-22) - the current post-match
    qualitative snapshot (Slice A2) plus a real per-signal trend
    (NEW_SIGNAL/PERSISTENT_TREND/REVERSAL/NOISE) computed over that
    player's own match_observations history. Empty output means no
    qualitative analysis has been run for this player yet - run
    `fpl match-analyze` for a real finished match first."""
    from fpl_agent.models.player_intelligence import player_intelligence

    conn = get_connection()
    try:
        pi = player_intelligence(conn, player_id)
    except ValueError as e:
        click.echo(f"player-intelligence failed: {e}", err=True)
        conn.close()
        raise SystemExit(1)
    conn.close()

    click.echo(f"{pi.web_name} (player_id={pi.player_id})")
    if pi.current_role:
        click.echo(f"  role: {pi.current_role}")
        click.echo(f"  tactical signal: {pi.current_tactical_signal}")
        click.echo(f"  FPL outlook: {pi.current_fpl_outlook} (confidence={pi.current_confidence})")
        click.echo(f"  as of match_id={pi.last_match_id}, generated {pi.generated_at}")
    else:
        click.echo("  no qualitative analysis recorded yet")
    if pi.trends:
        click.echo("  trends:")
        for t in pi.trends:
            click.echo(f"    [{t.signal}] {t.label} - currently {t.current_direction} (n={t.sample_size}, history={t.history})")


@cli.command("manager-intelligence")
@click.argument("team_id", type=int)
def manager_intelligence_cmd(team_id: int):
    """Real, evidence-based team-level tactical-pattern profile (2026-08-22) -
    formation frequency, starting-XI rotation rate, average first-substitution
    minute, aggregated across that team's own real match history. Not a named
    manager profile (no source gives manager identity separate from the team) -
    see the module docstring for why. A real manager change (`fpl
    manager-changes`) invalidates this profile's historical continuity."""
    from fpl_agent.models.manager_intelligence import manager_intelligence

    conn = get_connection()
    try:
        mi = manager_intelligence(conn, team_id)
    except ValueError as e:
        click.echo(f"manager-intelligence failed: {e}", err=True)
        conn.close()
        raise SystemExit(1)
    conn.close()

    click.echo(f"{mi.team_name} (team_id={mi.team_id}) - {mi.matches_observed} real FULL_TIME match(es) observed")
    if mi.note:
        click.echo(f"  {mi.note}")
        return
    click.echo(f"  most common formation: {mi.most_common_formation}")
    for formation, count in sorted(mi.formation_frequency.items(), key=lambda kv: -kv[1]):
        click.echo(f"    {formation}: {count}")
    click.echo(f"  starting XI rotation rate: {mi.starting_xi_rotation_rate} (0.0=never changes, 1.0=fully different every match)")
    click.echo(f"  avg first substitution minute: {mi.avg_first_substitution_minute}")


@cli.command("decision-fusion")
@click.option("--squad", required=True, help="comma-separated player ids (from fpl build-squad)")
@click.option("--bank", default=None, type=int, help="bank in tenths of a million (for transfer fusion; omitted = transfer fusion skipped)")
def decision_fusion_cmd(squad: str, bank: int | None):
    """Model vs Football Intelligence vs My View - captain AND transfer
    decisions (2026-08-22 captain, 2026-08-26 transfer). Rule-based, never
    an arbitrary score: shows the quant model's pick, the qualitative read's
    pick (only when a real PERSISTENT trend exists, not a one-match blip),
    and your own recorded observation (`fpl match-note`), then a verdict -
    MODEL_WINS / QUALITATIVE_WINS / UNDECIDED / INSUFFICIENT_EVIDENCE - with
    a real, disclosed reason. Never auto-resolves a genuine disagreement with
    your own recorded view (recommend only, per this project's standing rule)."""
    from fpl_agent.models.decision_fusion import compare_captain_views, compare_transfer_views

    player_ids = [int(x) for x in squad.split(",")]
    conn = get_connection()
    try:
        comparison = compare_captain_views(conn, player_ids)
        transfer_comparison = compare_transfer_views(conn, player_ids, bank) if bank is not None else None
    finally:
        conn.close()

    click.echo("CAPTAIN - Model vs Football Intelligence vs My View")
    if comparison.model_pick:
        click.echo(f"  Model:       {comparison.model_pick.web_name} - {comparison.model_reason}")
    else:
        click.echo(f"  Model:       (none) - {comparison.model_reason}")
    click.echo(f"  Football:    {comparison.qualitative_pick_name or '(no qualitative signal)'}"
               + (f" - {comparison.qualitative_reason}" if comparison.qualitative_reason else ""))
    click.echo(f"  My view:     {comparison.user_pick_name or '(no recorded observation)'}"
               + (f" - {comparison.user_reason}" if comparison.user_reason else ""))
    click.echo(f"  Verdict:     {comparison.verdict}")
    click.echo(f"  Why:         {comparison.explanation}")

    click.echo()
    click.echo("TRANSFER - Model vs Football Intelligence vs My View")
    if transfer_comparison is None:
        click.echo("  (pass --bank <tenths> to evaluate transfer fusion)")
        return
    if transfer_comparison.model_candidate:
        click.echo(f"  Model:       {transfer_comparison.model_reason}")
    else:
        click.echo(f"  Model:       (none) - {transfer_comparison.model_reason}")
    click.echo(f"  Football:    {transfer_comparison.qualitative_direction or '(no qualitative signal)'}"
               + (f" - {transfer_comparison.qualitative_reason}" if transfer_comparison.qualitative_reason else ""))
    click.echo(f"  My view:     {transfer_comparison.user_sentiment or '(no recorded observation)'}"
               + (f" - {transfer_comparison.user_reason}" if transfer_comparison.user_reason else ""))
    click.echo(f"  Verdict:     {transfer_comparison.verdict}")
    click.echo(f"  Why:         {transfer_comparison.explanation}")


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


@cli.command("calibration-report")
@click.option("--season", default=None, help="defaults to the live season")
@click.option("--min-samples", default=3, type=int, help="omit a cohort with fewer real rows than this")
def calibration_report(season: str | None, min_samples: int):
    """Real, automatic segmented accuracy over real in-season
    prediction_outcomes rows (2026-08-26, GW1-postmortem audit P0 item 4) -
    distinct from `fpl backtest` (historical, Understat-reconstructed
    seasons): this measures the live model against real GW-by-GW outcomes as
    they accumulate. Position/nailed-vs-rotation/new-transfer-cold-start/
    returning-injury cohorts, each only reported once it has real evidence
    behind it - never a misleadingly precise number off 1-2 rows."""
    from fpl_agent.models.calibration import segmented_accuracy

    conn = get_connection()
    try:
        rows = segmented_accuracy(conn, season=season, min_samples=min_samples)
    finally:
        conn.close()

    if not rows:
        click.echo(
            "no cohort has enough real prediction-vs-outcome data yet "
            f"(need >= {min_samples} rows per cohort) - this is expected until multiple real "
            "gameweeks have both a captured prediction and a real outcome; see CLAUDE.md"
        )
        return
    click.echo(f"{'cohort':<38} {'n':>5} {'mae':>8}")
    for r in rows:
        click.echo(f"{r.cohort:<38} {r.n:>5} {r.mae:>8}")


@cli.command("run-scheduled")
def run_scheduled():
    """The actual entrypoint the OS scheduler invokes (section 19) - not `fpl sync`
    directly. Checks resources first (defers if constrained), syncs, then delivers
    any newly-pending HIGH+ alerts. Logs to the rotating log file, not just stdout,
    since this runs unattended.

    Alert delivery moved to the END of this function (2026-08-21, live-
    gameweek layer) - it used to fire right after run_sync(), before the
    news/predicted-lineup/lineup-probability/kickoff steps below had a
    chance to write anything, so any change_events those steps produced sat
    undelivered until the NEXT scheduled cycle. One delivery pass at the end
    now covers everything this single cycle detected."""
    logger = logging.getLogger("fpl_agent.scheduler")

    resources = check_resources()
    if resources.defer:
        logger.info("run-scheduled deferred: %s", resources.defer_reason)
        click.echo(f"deferred: {resources.defer_reason}")
        return

    # Real, cheap squad scoping for every live-alert step below - see
    # ingestion/my_team.py::resolve_tracked_squad_ids' own docstring for why
    # this project's push notifications are deliberately narrowed to a real
    # tracked squad rather than firing on every one of the ~380-390 players
    # this project's Tier 2-4 sources cover. A short-lived connection, closed
    # immediately - run_sync() opens its own.
    scope_conn = get_connection()
    tracked_squad_ids = resolve_tracked_squad_ids(scope_conn)
    scope_conn.close()

    try:
        summary = run_sync(tracked_squad_ids=tracked_squad_ids)
    except (SourceFetchError, ValidationError) as e:
        logger.error("run-scheduled sync failed: %s", e)
        click.echo(f"sync failed: {e}", err=True)
        raise SystemExit(1)

    logger.info(
        "run-scheduled sync ok: %d lifecycle events, %d setpiece events, %d price events, retrieved_at=%s",
        summary["lifecycle_events"], summary["setpiece_events"], summary.get("price_events", 0),
        summary["retrieved_at"],
    )

    conn = get_connection()
    cadence = recommended_cadence(conn)
    retighten_msg = maybe_retighten_scheduler(conn)

    # Wired into the regular cycle 2026-08-20 (was opt-in-only, same mold as
    # sync-history/sync-eo) - direct user finding: a real, notable BBC-covered
    # story (a new signing's Community Shield debut) had already aged out of
    # the RSS feeds' limited retention window by the time it was checked,
    # because nothing had been polling news on a live cadence. Non-fatal on
    # any failure - sync_all_news_sources already isolates per-source
    # failures internally (NewsFetchError never escapes it), this is just the
    # same defensive posture as the dashboard regen below for anything else.
    news_result = None
    try:
        news_result = sync_all_news_sources(conn)
    except Exception:
        logger.exception("run-scheduled news sync failed - not fatal to the sync itself")

    # Real gap found 2026-08-26 (GW1-postmortem audit): backfill-odds/
    # backfill-xg were built and proven for historical seasons, but NEVER
    # wired into the regular cycle for the LIVE season - confirmed live,
    # zero 2026-27 rows existed in either match_results_history or
    # player_match_stats_history five real days after GW1 finished. That
    # means the Dixon-Coles team-strength fit never incorporated a single
    # real 2026-27 result, and every player's goals/assists rate ran through
    # the season-fallback path instead of the richer shot-level primary one,
    # for the entire live season so far. football-data.co.uk publishes one
    # small CSV per season that's cheap to re-fetch every cycle (its own
    # upsert is already idempotent). Understat needed a real fix first (see
    # backfill_understat's own docstring) - it had no skip-already-backfilled
    # guard at all, unsafe to call on a cadence without it; now idempotent,
    # so a normal cycle only ever fetches genuinely NEW finished matches.
    # Both keyed off the live current_season() - never a hardcoded year.
    season_for_backfill = None
    try:
        from fpl_agent.models.rules import current_season as _current_season_for_backfill

        season_for_backfill = _current_season_for_backfill(conn)
    except Exception:
        logger.exception("run-scheduled could not resolve the live season - skipping match/xg backfill this cycle")
    if season_for_backfill is not None:
        try:
            odds_backfill = backfill_football_data(conn, season_for_backfill)
            logger.info("run-scheduled odds backfill: %d match(es) upserted", odds_backfill["matches_inserted"])
        except Exception:
            logger.exception("run-scheduled odds backfill failed - not fatal to the sync itself")
        try:
            xg_backfill = backfill_understat(conn, season_for_backfill)
            logger.info(
                "run-scheduled xg backfill: %d new match(es) processed, %d player row(s)",
                xg_backfill["matches_processed"], xg_backfill["player_rows_inserted"],
            )
        except Exception:
            logger.exception("run-scheduled xg backfill failed - not fatal to the sync itself")

    # Predicted-lineup + start-percent CHANGE detection (2026-08-21, live-
    # gameweek layer) - both sources were already synced by this project
    # (2026-08-21, same day, earlier) but only as current-state snapshots,
    # never diffed against their own prior sync to detect a real change and
    # alert on it. Snapshot BEFORE each sync call (both tables are
    # delete+insert current-state, no history underneath to diff after the
    # fact - see each detector's own docstring), then diff after. Non-fatal
    # on any failure, same posture as news/my-team below - a scrape failing
    # must never abort the whole scheduled cycle.
    try:
        prev_lineup_state = {
            r["player_id"]: r["predicted_status"]
            for r in conn.execute(
                "SELECT player_id, predicted_status FROM predicted_lineup_players WHERE player_id IS NOT NULL"
            ).fetchall()
        }
        sync_predicted_lineups(conn)
        lineup_events = detect_predicted_lineup_status_changes(
            conn, prev_lineup_state, tracked_squad_ids, datetime.now(timezone.utc).isoformat(),
            "fantasyfootballscout_team_news",
        )
        conn.commit()
        logger.info("run-scheduled predicted-lineup sync: %d change event(s)", lineup_events)
    except Exception:
        logger.exception("run-scheduled predicted-lineup sync failed - not fatal to the sync itself")

    try:
        from fpl_agent.ingestion.change_detection import snapshot_start_percent_state

        prev_start_percent_state = snapshot_start_percent_state(conn, tracked_squad_ids)
        sync_lineup_probabilities(conn)
        start_percent_events = detect_start_percent_changes(
            conn, prev_start_percent_state, tracked_squad_ids, datetime.now(timezone.utc).isoformat(),
            "fantasyfootballpundit_start_percent",
        )
        conn.commit()
        logger.info("run-scheduled lineup-probability sync: %d change event(s)", start_percent_events)
    except Exception:
        logger.exception("run-scheduled lineup-probability sync failed - not fatal to the sync itself")

    # Kickoff reminders (2026-08-21) - no network call, pure DB read/write,
    # so failure here would only ever be a real local bug, not a flaky
    # external source - still non-fatal, matching every other step's
    # posture in this function.
    try:
        kickoff_events = detect_upcoming_kickoffs(conn, tracked_squad_ids, datetime.now(timezone.utc))
        conn.commit()
        if kickoff_events:
            logger.info("run-scheduled kickoff reminders: %d fixture(s)", kickoff_events)
    except Exception:
        logger.exception("run-scheduled kickoff reminder detection failed - not fatal to the sync itself")

    # Live pre-match odds (dashboard-overhaul pass, 2026-08-22) - was a
    # standalone/manual-only command (`fpl sync-live-odds`) despite feeding
    # the real Team Odds panel; wired in here so that panel updates itself
    # automatically, same "no manual command required" bar every other
    # source in this project already meets. One bulk call covers every
    # upcoming fixture (2 real credits per CLAUDE.md's own documented cost)
    # - cheap enough for the regular ~30min cadence, unlike the per-event
    # player-odds sync below. Non-fatal (no key configured, or a real
    # network failure, must never abort the sync).
    try:
        odds_result = sync_live_odds(conn)
        logger.info(
            "run-scheduled live-odds sync: %d matched, %d unmatched, %d failed",
            odds_result["matched"], odds_result["unmatched"], odds_result["failed"],
        )
    except Exception:
        logger.exception("run-scheduled live-odds sync failed - not fatal to the sync itself")

    # Real per-event anytime-goalscorer odds (dashboard-overhaul pass,
    # 2026-08-22) - unlike the bulk match-odds call above, this needs one
    # real network request PER FIXTURE (live-verified: 1 credit/event) -
    # syncing every ~30min tick for even a handful of squad-relevant
    # fixtures would burn a free-tier 500-credit/month budget in about a
    # day. `sync_player_odds` throttles itself internally (a real
    # retrieved_at freshness gate per fixture, checked before any network
    # call), so it's safe to call every tick - most ticks it's a real no-op.
    try:
        player_odds_result = sync_player_odds(conn, tracked_squad_ids)
        if player_odds_result["fetched"]:
            logger.info(
                "run-scheduled player-odds sync: %d fetched, %d skipped (fresh), %d failed",
                player_odds_result["fetched"], player_odds_result["skipped"], player_odds_result["failed"],
            )
    except Exception:
        logger.exception("run-scheduled player-odds sync failed - not fatal to the sync itself")

    # Match Intelligence Core auto-refresh (Slice A2, spec section 4) - the
    # real PRE_MATCH -> LIVE -> HALFTIME -> FULL_TIME detection hook. No new
    # "tracked match" registry: re-syncs any not-yet-FULL_TIME match_intelligence
    # row within a bounded recent window, using the team names already
    # stored. Non-fatal on failure, same posture as every other step here.
    try:
        mi_result = refresh_in_progress_matches(conn, tracked_squad_ids)
        if mi_result["refreshed"]:
            logger.info(
                "run-scheduled match-intelligence refresh: %d refreshed, %d skipped, %d failed",
                mi_result["refreshed"], mi_result["skipped"], mi_result["failed"],
            )
        from fpl_agent.ingestion.analysis_queue import supersede_stale_halftime_jobs
        supersede_stale_halftime_jobs(conn)
    except Exception:
        logger.exception("run-scheduled match-intelligence refresh failed - not fatal to the sync itself")

    # Auto-discovery (matchday-autonomy pass, 2026-08-22) - the real,
    # always-on backbone for section 3/40's "no manual fpl sync-match"
    # requirement. This step runs on the ALREADY-REGISTERED Windows Task
    # Scheduler cadence (survives reboots, no manual restart needed, unlike
    # `fpl live-match-poll` which is an optional fast-cadence booster a user
    # starts by hand for a snappier live view - see that command's own
    # docstring). Cheap once a fixture is already registered (pure local DB
    # read), only a real network call for a genuinely new fixture.
    try:
        discovery_result = discover_and_register_matches(conn)
        if discovery_result["registered"]:
            logger.info(
                "run-scheduled match discovery: %d newly registered, %d already tracked, %d failed",
                discovery_result["registered"], discovery_result["skipped"], discovery_result["failed"],
            )
    except Exception:
        logger.exception("run-scheduled match discovery failed - not fatal to the sync itself")

    # Post-GW pipeline (automation-lifecycle pass, 2026-08-22) - a cheap,
    # idempotent no-op unless the real lifecycle state says a gameweek has
    # genuinely finished (all real fixtures resolved AND the fixtures source
    # itself is healthy - see models/gw_lifecycle.py's own guard) and the
    # pipeline hasn't already completed for it. Never fatal to the sync.
    try:
        pipeline_result = maybe_run_post_gw_pipeline(conn)
        if pipeline_result is not None and pipeline_result.ran:
            logger.info(
                "run-scheduled post-GW pipeline: event=%s decision_id=%s",
                pipeline_result.event, pipeline_result.decision_id,
            )
    except Exception:
        logger.exception("run-scheduled post-GW pipeline failed - not fatal to the sync itself")

    conn.close()

    if retighten_msg:
        logger.info("run-scheduled: %s", retighten_msg)
        click.echo(retighten_msg)
    if news_result is not None:
        logger.info("run-scheduled news sync: %d fetched, %d new item(s)", news_result["fetched"], news_result["new_items"])
        click.echo(f"news: {news_result['new_items']} new item(s) synced")

    # Real gap found 2026-08-21 - the user asked directly for "my real team"
    # to auto-update once their real gameweek deadline passes, and
    # sync_my_team() was never actually wired into the regular unattended
    # cycle (it was a standalone opt-in command, same mold as sync-history/
    # sync-eo before the news sync above got wired in). Only runs when a
    # real entry id has been saved (`fpl my-team --entry-id` at least once);
    # non-fatal on failure - the most common failure mode this session is
    # entirely expected (event hasn't locked yet), sync_my_team() already
    # handles that internally rather than raising, but a real network
    # failure on the entry-info fetch itself is still caught here rather
    # than aborting the whole scheduled run over one opt-in extra.
    try:
        conn2 = get_connection()
        my_team_entry_id = get_my_team_entry_id(conn2)
        if my_team_entry_id is not None:
            my_team_result = sync_my_team(conn2, my_team_entry_id)
            logger.info(
                "run-scheduled my-team sync: entry=%s picks_fetched=%s",
                my_team_entry_id, my_team_result["picks"]["fetched"],
            )
        conn2.close()
    except Exception:
        logger.exception("run-scheduled my-team sync failed - not fatal to the sync itself")

    # Real gap found 2026-08-26 (section R of a GW1-postmortem ask): no
    # persistent record of "what did the model predict" existed anywhere -
    # once a gameweek's real results land, that prediction can never be
    # honestly reconstructed again. Captures the locked squad's real
    # expected_points() once, right when the lifecycle genuinely reaches
    # LOCKED (deadline passed, kickoff not yet) - idempotent per (player,
    # event), so a real prediction is written exactly once, never
    # overwritten with a later, hindsight-influenced number. Non-fatal.
    try:
        from fpl_agent.models.calibration import record_predictions_for_locked_squad
        from fpl_agent.models.gw_lifecycle import compute_gw_lifecycle_state as _gw_state
        from fpl_agent.optimization.locked_squad import get_locked_squad as _get_locked

        conn6 = get_connection()
        lifecycle = _gw_state(conn6)
        if lifecycle is not None and lifecycle.state == "LOCKED":
            locked_for_pred = _get_locked(conn6)
            if locked_for_pred is not None:
                n_written = record_predictions_for_locked_squad(
                    conn6, lifecycle.event, sorted(locked_for_pred.squad_ids)
                )
                if n_written:
                    logger.info("run-scheduled prediction capture: %d player(s) recorded for event %s",
                                n_written, lifecycle.event)
        conn6.close()
    except Exception:
        logger.exception("run-scheduled prediction capture failed - not fatal to the sync itself")

    # Real gap found 2026-08-26 (section K of a GW1-postmortem ask): `fpl
    # live-rank` was opt-in only, so it never refreshed unless a human
    # remembered to run it by hand - confirmed live, the last real sample
    # was 4 days stale by the time this was checked. Auto-refreshes here,
    # but ONLY while a squad fixture is genuinely live-or-just-finished
    # (the same cheap started=1 gate `_maybe_fetch_live_payload` already
    # uses - zero network cost the rest of the time, which is most of a
    # season) AND at most once per _LIVE_RANK_MIN_REFRESH_MINUTES, so a
    # short scheduler interval can't turn this into the heaviest network
    # pattern in the project running every single cycle. Non-fatal on
    # failure, same posture as every other step here.
    try:
        conn5 = get_connection()
        refreshed = _maybe_refresh_live_rank(conn5)
        if refreshed is not None:
            logger.info("run-scheduled live-rank refresh: decision_id=%s rank=~%s",
                        refreshed["decision_id"], refreshed["estimated_rank"])
        conn5.close()
    except Exception:
        logger.exception("run-scheduled live-rank refresh failed - not fatal to the sync itself")

    # Delivered last, after every detection step above has had a chance to
    # write a real change_events row this cycle - see this function's own
    # docstring for why this moved from right after run_sync().
    conn3 = get_connection()
    alerts = deliver_pending_alerts(conn3, configured_notifiers(conn3))
    conn3.close()
    logger.info("run-scheduled delivered %d alert(s); next cadence: %s", len(alerts), cadence.reason)
    click.echo(f"sync ok - {len(alerts)} alert(s) delivered")
    click.echo(f"next recommended interval: {cadence.interval_minutes}min ({cadence.reason})")

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
    """Only issues a network call when a fixture is genuinely in progress OR
    has just finished (dashboard-state pass, 2026-08-21) - cheap and honest,
    matches this project's live-bonus CLI command's own fetch pattern.
    Returns None outside any relevant window (the common case, including
    all of preseason) with zero network traffic. Dropped the `finished=0`
    filter deliberately: the real "My Live Score" POST_MATCH state needs
    this same payload to show final points immediately after full-time,
    before official gameweek stats are computed - FPL's live endpoint keeps
    serving the final per-player stats for a just-finished match. Uses
    live_or_reference_event(), not _reference_event() directly - the latter
    would report the FOLLOWING gameweek for the entire real GW1 match
    window (is_next flips at the deadline, not at kickoff or full-time),
    which would silently never detect the live fixture at all."""
    event_num = live_or_reference_event(conn)
    if event_num is None:
        return None
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM fixtures WHERE event=? AND started=1", (event_num,)
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


_LIVE_RANK_MIN_REFRESH_MINUTES = 20
_LIVE_RANK_AUTO_SAMPLE_SIZE = 200  # smaller than the manual CLI default (300) - this path can fire repeatedly across a live day


def _maybe_refresh_live_rank(conn) -> dict | None:
    """The automatic half of `fpl live-rank` (section K's real gap: it was
    opt-in only, so it never refreshed unless a human ran it by hand - see
    the call site in run_scheduled for the full real story). Deliberately
    inlines the CLI command's own core logic rather than importing/calling
    `live_rank_cmd` directly - that command's error paths are `click.echo`
    + `SystemExit`, appropriate for an interactive command, wrong for a
    scheduled background step that must stay non-fatal. Returns None on any
    real reason not to run (no entry id, not genuinely live, too soon since
    the last refresh, no real picks/points yet, sample came back empty) -
    every one of those is a legitimate, expected state, not an error."""
    entry_id = get_my_team_entry_id(conn)
    if entry_id is None:
        return None
    event_num = live_or_reference_event(conn)
    if event_num is None:
        return None
    started_row = conn.execute(
        "SELECT COUNT(*) AS n FROM fixtures WHERE event=? AND started=1", (event_num,)
    ).fetchone()
    if not started_row or not started_row["n"]:
        return None

    last = conn.execute(
        "SELECT created_at FROM decisions WHERE decision_type='live_rank' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last is not None and last["created_at"]:
        from datetime import datetime, timezone
        try:
            last_ts = datetime.fromisoformat(last["created_at"].replace("Z", "+00:00"))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60
            if age_minutes < _LIVE_RANK_MIN_REFRESH_MINUTES:
                return None
        except ValueError:
            pass

    try:
        sync_my_team(conn, entry_id, event=event_num)
    except SourceFetchError:
        return None

    my_picks = [
        (r["player_id"], r["multiplier"])
        for r in conn.execute(
            "SELECT player_id, multiplier FROM my_team_picks WHERE entry_id=? AND event=?",
            (entry_id, event_num),
        ).fetchall()
    ]
    gw_summary = conn.execute(
        "SELECT total_points, points FROM my_team_gw_summary WHERE entry_id=? AND event=?",
        (entry_id, event_num),
    ).fetchone()
    if not my_picks or gw_summary is None or gw_summary["total_points"] is None:
        return None

    try:
        live_payload = FPLApiAdapter().fetch_event_live(event_num).data
    except SourceFetchError as e:
        update_source_health(conn, f"fpl_api_event_live_{event_num}", success=False, error=str(e))
        return None
    update_source_health(conn, f"fpl_api_event_live_{event_num}", success=True)

    pre_gw_total = gw_summary["total_points"] - (gw_summary["points"] or 0)
    my_live_points = estimate_squad_live_points(my_picks, live_payload)
    my_current_total = pre_gw_total + my_live_points

    try:
        sample_live_rank_reference(
            conn, event_num, live_payload, target_sample_size=_LIVE_RANK_AUTO_SAMPLE_SIZE, force=True,
        )
    except ValueError:
        return None
    reference = get_live_rank_reference(conn, event_num)
    if not reference:
        return None

    total_players_row = conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    total_players = int(total_players_row["value"]) if total_players_row else 11_000_000
    estimate = estimate_live_rank(reference, my_current_total, total_players)

    decision_id = log_decision(
        conn, "live_rank",
        summary=f"estimated live rank ~{estimate.estimated_rank:,} (event {event_num}, {my_current_total:.0f} pts)",
        detail={
            "entry_id": entry_id, "event": event_num, "pre_gw_total": pre_gw_total,
            "live_points": my_live_points, "current_total": my_current_total,
            "estimated_rank": estimate.estimated_rank, "rank_lower_bound": estimate.rank_lower_bound,
            "rank_upper_bound": estimate.rank_upper_bound, "sample_size": estimate.sample_size,
            "bracketed": estimate.bracketed,
        },
        confidence="low",
    )
    return {"decision_id": decision_id, "estimated_rank": estimate.estimated_rank}


def _write_dashboard(
    gw_window: int = 1, must_include_ids: set[int] | None = None, must_start_ids: set[int] | None = None,
    exclude_ids: set[int] | None = None,
) -> None:
    conn = get_connection()
    try:
        # Real fix, 2026-08-21 (superseded same day by the locked-squad
        # product architecture pass - see generate_dashboard_html's own
        # docstring): this function used to pre-resolve the locked
        # `build_team` decision itself and pass it down as explicit
        # override args. That now DOUBLE-resolves against
        # generate_dashboard_html's own, strictly better lock check
        # (optimization.locked_squad.get_locked_squad, which also checks
        # the real synced FPL squad first) - passing pre-resolved args down
        # made generate_dashboard_html treat a genuine bare call as if it
        # were a deliberate Mode-A override, which is exactly backwards
        # (confirmed live: it rendered "Optimizer Recommendation" instead
        # of "My Locked Squad" for an already-locked, already-synced real
        # squad). generate_dashboard_html is now the single place that
        # decides "bare call -> check the lock" - this function just passes
        # whatever the caller gave it straight through, unchanged.
        live_payload = _maybe_fetch_live_payload(conn)
        html_content = generate_dashboard_html(
            conn, live_payload=live_payload, gw_window=gw_window,
            must_include_ids=must_include_ids, must_start_ids=must_start_ids, exclude_ids=exclude_ids,
        )
    finally:
        conn.close()
    path = _dashboard_path()
    path.write_text(html_content, encoding="utf-8")
    return path


@cli.command()
@click.option("--gw-window", default=1, type=int, help="fixtures to sum for the Recommended Squad panel, same as `fpl build-team --gw-window`")
@click.option("--must-include", default=None, help="comma-separated player ids to force into the Recommended Squad panel")
@click.option("--must-start", default=None, help="comma-separated player ids to force into the starting XI specifically")
@click.option("--exclude", default=None, help="comma-separated player ids to bar from selection entirely")
def dashboard(gw_window: int, must_include: str | None, must_start: str | None, exclude: str | None):
    """Generate (or regenerate) the local auto-refreshing HTML dashboard -
    the same one `fpl run-scheduled` regenerates every cycle (which always
    uses the defaults - GW1, no forced picks - `--gw-window`/`--must-include`
    are for an explicit manual regen only). Open
    data/dashboard.html in a browser and leave the tab open; it reloads
    itself on its own to show whatever the last sync produced (see
    monitoring.dashboard._REFRESH_SECONDS for the real, current interval -
    referenced here rather than hardcoded a second time, after this exact
    string drifted out of sync with a real refresh-interval change once
    already). A published, always-fresh, no-Claude-open public WEBSITE
    isn't reachable with this project's local, free-resources-only
    architecture (a published Artifact page can't read this local database
    or fetch external data on its own) - this is the honest, real
    equivalent: local, genuinely automatic once the scheduler is running,
    zero extra cost."""
    parsed_must_include = _parse_squad_option(must_include)
    must_include_ids = set(parsed_must_include) if parsed_must_include else None
    parsed_must_start = _parse_squad_option(must_start)
    must_start_ids = set(parsed_must_start) if parsed_must_start else None
    if must_start_ids:
        must_include_ids = (must_include_ids or set()) | must_start_ids
    parsed_exclude = _parse_squad_option(exclude)
    exclude_ids = set(parsed_exclude) if parsed_exclude else None
    path = _write_dashboard(
        gw_window=gw_window, must_include_ids=must_include_ids, must_start_ids=must_start_ids,
        exclude_ids=exclude_ids,
    )
    click.echo(f"wrote {path}")
    click.echo(f"open it in a browser and leave the tab open - it auto-reloads every {_REFRESH_SECONDS // 60}min")


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
        # live_or_reference_event(), not _reference_event() - during the
        # entire real GW1 match window is_next has already flipped to GW2
        # (it tracks the deadline, not kickoff/full-time), which would make
        # the default here silently check the wrong, not-yet-started event.
        event_num = live_or_reference_event(conn)
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

    click.echo(f"{'Fixture':>7} {'Player':<20} {'BPS':>4} {'Bonus':>5} {'Confirmed':>9}  Min  G  A  DefCon")
    current_fixture = None
    for r in rows:
        if r.fixture_id != current_fixture:
            if current_fixture is not None:
                click.echo()
            current_fixture = r.fixture_id
        confirmed = str(r.confirmed_bonus) if r.confirmed_bonus is not None else "-"
        # DEFCON (2026-08-21) - "-" for a position the rule doesn't apply to
        # (GKP), never a fabricated "0/None".
        if r.defcon_threshold is None:
            defcon_col = "-"
        else:
            defcon_col = f"{r.defensive_contribution}/{r.defcon_threshold}" + (" (+2)" if r.defcon_reached else "")
        click.echo(
            f"{r.fixture_id:>7} {r.web_name:<20} {r.bps:>4} {r.provisional_bonus:>5} {confirmed:>9}  "
            f"{r.minutes:>3}  {r.goals_scored}  {r.assists}  {defcon_col}"
        )


@cli.command("live-rank")
@click.option("--entry-id", "entry_id_opt", default=None, type=int, help="FPL entry id (default: the saved my-team entry id)")
@click.option("--event", "event_num", default=None, type=int, help="gameweek number (default: current/next event)")
@click.option("--sample-size", default=300, type=int, help="reference managers to sample (heaviest network call in this project - see the command's own warning)")
@click.option("--force", is_flag=True, help="resample even if a reference sample already exists for this event")
def live_rank_cmd(entry_id_opt: int | None, event_num: int | None, sample_size: int, force: bool):
    """Estimate your real live overall rank during an in-progress gameweek -
    FPL's own API never publishes this (confirmed by real research, see
    models/live_rank.py's own module docstring), so this samples a real,
    rank-stratified set of managers across the FULL 1..total_players range
    (not just the competitive top 10k `fpl sync-eo` samples - a real,
    deliberate difference, since a typical manager's own real rank can sit
    anywhere in that range) and interpolates where your own real live
    points total falls among them. Real, disclosed limitations, not
    oversold: uncalibrated (no real live-gameweek results exist yet to fit
    against), doesn't model autosubs (a non-appearing starter simply
    contributes 0, not a fabricated substitution), and the underlying
    sample is the heaviest network call in this project - opt-in only,
    idempotent per event unless --force, same posture `fpl sync-eo`
    already established for the same reason."""
    conn = get_connection()
    entry_id = entry_id_opt if entry_id_opt is not None else get_my_team_entry_id(conn)
    if entry_id is None:
        click.echo("no entry id - pass --entry-id or run `fpl my-team --entry-id <id>` first", err=True)
        conn.close()
        raise SystemExit(1)

    if event_num is None:
        event_num = live_or_reference_event(conn)
        if event_num is None:
            click.echo("no reference gameweek found (no upcoming fixtures)", err=True)
            conn.close()
            raise SystemExit(1)

    try:
        sync_my_team(conn, entry_id, event=event_num)
    except SourceFetchError as e:
        click.echo(f"my-team sync failed: {e}", err=True)
        conn.close()
        raise SystemExit(1)

    my_picks = [
        (r["player_id"], r["multiplier"])
        for r in conn.execute(
            "SELECT player_id, multiplier FROM my_team_picks WHERE entry_id=? AND event=?",
            (entry_id, event_num),
        ).fetchall()
    ]
    gw_summary = conn.execute(
        "SELECT total_points, points FROM my_team_gw_summary WHERE entry_id=? AND event=?",
        (entry_id, event_num),
    ).fetchone()
    if not my_picks or gw_summary is None or gw_summary["total_points"] is None:
        click.echo(
            f"no real picks/points synced for entry {entry_id} event {event_num} yet - "
            "event may not have locked, or `fpl my-team` hasn't been run against it", err=True,
        )
        conn.close()
        raise SystemExit(1)

    adapter = FPLApiAdapter()
    try:
        live_payload = adapter.fetch_event_live(event_num).data
    except SourceFetchError as e:
        update_source_health(conn, f"fpl_api_event_live_{event_num}", success=False, error=str(e))
        click.echo(f"live-rank failed: {e}", err=True)
        conn.close()
        raise SystemExit(1)
    update_source_health(conn, f"fpl_api_event_live_{event_num}", success=True)

    pre_gw_total = gw_summary["total_points"] - (gw_summary["points"] or 0)
    my_live_points = estimate_squad_live_points(my_picks, live_payload)
    my_current_total = pre_gw_total + my_live_points

    reference = get_live_rank_reference(conn, event_num)
    if not reference or force:
        click.echo(f"sampling {sample_size} reference managers across the full rank range - this can take a while...")
        try:
            sample_result = sample_live_rank_reference(
                conn, event_num, live_payload, target_sample_size=sample_size, force=force,
            )
        except ValueError as e:
            click.echo(f"live-rank failed: {e}", err=True)
            conn.close()
            raise SystemExit(1)
        click.echo(
            f"reference sample: {sample_result['sample_size']} managers "
            f"({sample_result['managers_failed']} failed" +
            (", aborted early)" if sample_result["aborted_early"] else ")")
        )
        reference = get_live_rank_reference(conn, event_num)

    if not reference:
        click.echo("reference sample produced zero usable managers - cannot estimate a rank this cycle", err=True)
        conn.close()
        raise SystemExit(1)

    total_players_row = conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    total_players = int(total_players_row["value"]) if total_players_row else 11_000_000
    estimate = estimate_live_rank(reference, my_current_total, total_players)

    decision_id = log_decision(
        conn, "live_rank",
        summary=f"estimated live rank ~{estimate.estimated_rank:,} (event {event_num}, {my_current_total:.0f} pts)",
        detail={
            "entry_id": entry_id, "event": event_num, "pre_gw_total": pre_gw_total,
            "live_points": my_live_points, "current_total": my_current_total,
            "estimated_rank": estimate.estimated_rank, "rank_lower_bound": estimate.rank_lower_bound,
            "rank_upper_bound": estimate.rank_upper_bound, "sample_size": estimate.sample_size,
            "bracketed": estimate.bracketed,
        },
        confidence="low",
    )
    conn.close()

    click.echo(f"decision_id={decision_id}")
    click.echo(f"pre-GW total: {pre_gw_total}   live points this GW: {my_live_points:.0f}   current total: {my_current_total:.0f}")
    click.echo(f"estimated live rank: ~{estimate.estimated_rank:,}  (real bracket {estimate.rank_lower_bound:,}-{estimate.rank_upper_bound:,}, {estimate.sample_size} sampled managers)")
    if not estimate.bracketed:
        click.echo("NOTE: your total fell outside the sampled range - this is a much cruder bound, not a precise interpolation.")
    click.echo(
        "Uncalibrated estimate (real research-backed method, no fitted results yet - see "
        "models/live_rank.py) - does not model autosubs, a non-appearing starter counts as 0."
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
        # Same real gap as the scheduled-dashboard squad mismatch (see
        # optimization/build_team.py::resolve_locked_constraints) - a bare
        # unconstrained generate_build_team_report() call here would watch a
        # fresh, different squad from whatever the user actually locked via
        # `fpl build-team --must-include ...`, exactly the failure caught
        # live 2026-08-21: live-watch started tracking 15 different players
        # for the wrong reasons minutes before a real kickoff.
        try:
            locked = resolve_locked_constraints(conn)
        except LockedDecisionIncomplete as exc:
            logging.getLogger("fpl_agent.cli").warning(
                "live-watch: %s - falling back to the unconstrained default", exc
            )
            locked = None
        if locked is not None:
            report = generate_build_team_report(
                conn, gw_window=locked.gw_window, must_include_ids=set(locked.must_include_ids) or None,
                must_start_ids=set(locked.must_start_ids) or None, exclude_ids=set(locked.exclude_ids) or None,
            )
        else:
            report = generate_build_team_report(conn)
        if not report.structures or not report.structures[0].result.squad:
            click.echo("no squad available - pass --squad explicitly or run fpl build-team first", err=True)
            conn.close()
            raise SystemExit(1)
        squad_ids = {c.player_id for c in report.structures[0].result.squad}
        click.echo(f"no --squad given - tracking the current recommended squad ({len(squad_ids)} players)")

    # live_or_reference_event(), not _reference_event() - is_next flips to
    # the FOLLOWING gameweek the moment a deadline passes, well before that
    # gameweek's own matches kick off (and it stays flipped through the
    # whole live weekend, since events.finished only flips once bonus is
    # confirmed days later) - defaulting to _reference_event() here would
    # make live-watch silently watch the wrong, not-yet-started gameweek
    # for the entire real GW1 window.
    event_num = live_or_reference_event(conn)
    if event_num is None:
        click.echo("no reference gameweek found (no upcoming fixtures)", err=True)
        conn.close()
        raise SystemExit(1)

    notifier = configured_notifiers(conn) if deliver else TerminalNotifier()
    adapter = FPLApiAdapter()
    poll_state: dict[int, LiveBonusRow] = {}
    stop_at = time.monotonic() + max_hours * 3600
    # Each poll's fetch_event_live() call writes a fresh timestamped raw file
    # (save_raw() never overwrites, same pattern every adapter call uses for
    # its audit trail) - fine for a single fpl live-bonus call, but at a 75s
    # default interval over up to --max-hours this loop can poll ~150 times,
    # and the regular scheduler's own prune_raw() cycle (15-60min, see
    # scheduler/adaptive.py) isn't guaranteed to run inside a single watch
    # session. Pruning here too keeps this session self-contained rather than
    # silently relying on a concurrent process to clean up after it.
    next_prune_at = time.monotonic()
    _PRUNE_INTERVAL_SECONDS = 900
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

            if time.monotonic() >= next_prune_at:
                try:
                    prune_raw(load_storage_budget().raw_retention_hours)
                except Exception:
                    pass  # storage housekeeping must never interrupt live tracking
                next_prune_at = time.monotonic() + _PRUNE_INTERVAL_SECONDS

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


@cli.command("live-match-poll")
@click.option("--interval", default=25, type=int,
              help="poll interval in seconds while a match is genuinely LIVE/HALFTIME (default 25)")
@click.option("--max-hours", default=3.0, type=float, help="safety cap on total watch duration")
def live_match_poll_cmd(interval: int, max_hours: float):
    """Fast, real live-match polling for Match Intelligence Core (2026-08-21,
    live-match-feed pass) - a deliberate, narrow exception to this project's
    single-shot-command convention, same shape as `fpl live-watch` (which
    this is NOT a duplicate of - see ownership split below). Separate from:
    - the regular `fpl run-scheduled` cadence (15min-6h, deadline-aware) -
      unchanged, still handles FPL sync/lineups/news/my-team/alerts;
    - `fpl live-watch` (~75s) - FPL FANTASY events (goals/assists/bonus/
      DEFCON for YOUR squad specifically, pushed as notifications).
    This command owns RAW FOOTBALL EVENTS (real match incidents/commentary
    evidence - goals/cards/subs/shots, straight from FotMob, never LLM-
    authored) - refreshing match_intelligence/player_match_state/
    team_match_state/match_events, the real data the dashboard's Match
    Centre reads. Only polls fast while a tracked match is genuinely LIVE/
    HALFTIME - backs off to a slow pre-kickoff cadence (never hammers
    FotMob for a match that hasn't started) and stops entirely once nothing
    tracked remains not-FULL_TIME (a real FULL_TIME triggers one final sync
    - the qualitative Slice A2 analysis itself stays a separate, deliberate
    skill invocation once `fpl match-report` shows FULL_TIME, unchanged)."""
    conn = get_connection()
    # Resolved once, not re-resolved every tick - matches run_scheduled's own
    # pattern (2026-08-22, automation-lifecycle pass). Threaded into every
    # sync_match call below so a real lineup-confirmation transition fires
    # its change_events row within this loop's own fast cadence, not only on
    # the slower run-scheduled tick.
    tracked_squad_ids = resolve_tracked_squad_ids(conn)
    stop_at = time.monotonic() + max_hours * 3600
    consecutive_failures = 0
    pre_kickoff_interval = max(interval * 4, 60)
    max_backoff_seconds = 120

    click.echo(
        f"live-match-poll: {interval}s while LIVE/HALFTIME, {pre_kickoff_interval}s pre-kickoff - Ctrl+C to stop"
    )

    try:
        while time.monotonic() < stop_at:
            # Auto-discovery (matchday-autonomy pass, 2026-08-22) - closes
            # the real remaining manual step: this used to require a human
            # to have already run `fpl sync-match <home> <away>` by hand for
            # every fixture before this loop would ever see it. Cheap once
            # today's fixtures are already registered (a local DB read, no
            # network) - only issues a real request for a genuinely new,
            # not-yet-tracked fixture. Non-fatal: a discovery hiccup must
            # never stop an otherwise-healthy poll of already-tracked matches.
            try:
                discover_and_register_matches(conn)
            except Exception as e:
                click.echo(f"live-match-poll: auto-discovery failed this tick ({e}) - continuing", err=True)

            rows = conn.execute(
                "SELECT mi.id, mi.fotmob_match_id, mi.status AS prior_status, mi.kickoff_utc, "
                "ht.name AS home_name, at.name AS away_name "
                "FROM match_intelligence mi "
                "JOIN teams ht ON ht.id = mi.home_team_id JOIN teams at ON at.id = mi.away_team_id "
                "WHERE mi.status != 'FULL_TIME'"
            ).fetchall()
            if not rows:
                click.echo("no tracked match left to poll (none active, or all finished) - stopping")
                break

            any_live = False
            any_failure = False
            any_full_time_transition = False
            for row in rows:
                if not row["kickoff_utc"]:
                    continue
                try:
                    kickoff = datetime.fromisoformat(row["kickoff_utc"].replace("Z", "+00:00"))
                except ValueError:
                    continue
                try:
                    result = sync_match(conn, row["home_name"], row["away_name"], kickoff.date(), tracked_squad_ids)
                except FotMobFetchError as e:
                    any_failure = True
                    last_success_row = conn.execute(
                        "SELECT last_success FROM source_health WHERE source_name='fotmob'"
                    ).fetchone()
                    last_success = last_success_row["last_success"] if last_success_row else None
                    click.echo(
                        f"live-match-poll: {row['home_name']} v {row['away_name']} - Live data delayed "
                        f"({e}) - last known state kept, last real update {last_success or 'unknown'}", err=True,
                    )
                    continue
                if result["status"] in ("LIVE", "HALFTIME"):
                    any_live = True
                elif result["status"] == "FULL_TIME" and row["prior_status"] != "FULL_TIME":
                    any_full_time_transition = True
                    from fpl_agent.ingestion.analysis_queue import supersede_stale_halftime_jobs
                    supersede_stale_halftime_jobs(conn)
                    click.echo(
                        f"{row['home_name']} v {row['away_name']}: FULL_TIME - final sync done, "
                        "stopping fast polling for this match. Qualitative analysis job queued - "
                        "run `fpl analysis-queue` next time Claude Code opens."
                    )

            # Real gap found + fixed 2026-08-22, tonight's-matches pass: this
            # loop already re-syncs live match data every `interval` seconds,
            # but the actual `dashboard.html` file the user has open only got
            # regenerated by the separate 30-min `run-scheduled` cadence -
            # the browser's own 60s auto-refresh was reloading the SAME stale
            # Post-GW pipeline (automation-lifecycle pass, 2026-08-22) - only
            # worth checking right after a real FULL_TIME transition (the one
            # moment the real lifecycle state could have just become eligible
            # for it); a cheap, idempotent no-op otherwise (e.g. this match
            # finished but others in the same gameweek haven't yet). Runs
            # BEFORE the dashboard regen below so a completed post-GW plan
            # shows up in the very same regen, not one tick later.
            if any_full_time_transition:
                try:
                    pipeline_result = maybe_run_post_gw_pipeline(conn)
                    if pipeline_result is not None and pipeline_result.ran:
                        click.echo(
                            f"live-match-poll: post-GW pipeline complete for event {pipeline_result.event} "
                            f"(decision_id={pipeline_result.decision_id})"
                        )
                except Exception as e:
                    click.echo(f"live-match-poll: post-GW pipeline failed this tick ({e}) - continuing", err=True)

            # file most of the time during a live match. Regenerate here too,
            # but only when something actually changed (a match genuinely
            # live, or a real FULL_TIME transition this tick) - never on a
            # quiet pre-kickoff idle tick, where nothing on the dashboard
            # would look any different anyway. Non-fatal: a dashboard-write
            # failure must never stop the underlying live poll.
            if any_live or any_full_time_transition:
                try:
                    _write_dashboard()
                except Exception as e:
                    click.echo(f"live-match-poll: dashboard regen failed this tick ({e}) - continuing", err=True)

            consecutive_failures = consecutive_failures + 1 if any_failure else 0
            if consecutive_failures:
                sleep_for = min(interval * (2 ** min(consecutive_failures, 4)), max_backoff_seconds)
            elif any_live:
                sleep_for = interval
            else:
                sleep_for = pre_kickoff_interval
            time.sleep(sleep_for)
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
@click.option("--gw-window", default=1, type=int, help="fixtures to sum for structures A/B (real user ask 2026-08-21: build with a multi-GW fixture window in mind, e.g. 5)")
@click.option("--must-include", default=None, help="comma-separated player ids to force into the squad regardless of cost-efficiency or the start-confidence gate")
@click.option("--must-start", default=None, help="comma-separated player ids to force into the STARTING XI specifically (must-include only guarantees the 15-man squad, not a starting spot)")
@click.option("--exclude", default=None, help="comma-separated player ids to bar from selection entirely - real use: \"downgrade X to Y\" needs both must-include Y and exclude X, must-include alone can add Y without removing X")
def build_team(sync: bool, gw_window: int, must_include: str | None, must_start: str | None, exclude: str | None):
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

    parsed_must_include = _parse_squad_option(must_include)
    must_include_ids = set(parsed_must_include) if parsed_must_include else None
    parsed_must_start = _parse_squad_option(must_start)
    must_start_ids = set(parsed_must_start) if parsed_must_start else None
    if must_start_ids:
        must_include_ids = (must_include_ids or set()) | must_start_ids  # a forced starter must also be in the squad
    parsed_exclude = _parse_squad_option(exclude)
    exclude_ids = set(parsed_exclude) if parsed_exclude else None
    report = generate_build_team_report(
        conn, gw_window=gw_window, must_include_ids=must_include_ids, must_start_ids=must_start_ids,
        exclude_ids=exclude_ids,
    )
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
        # Real ids, not just the web_names above - the actual persistence
        # gap behind the scheduled-dashboard squad mismatch (2026-08-21):
        # without these, a later scheduled dashboard regen has no reliable
        # way to reconstruct which real squad this decision locked in, and
        # a web_name is not a safe substitute (this project has hit real
        # name collisions before - Gabriel/Martinelli, Raya/Martin).
        "must_include_ids": sorted(must_include_ids) if must_include_ids else [],
        "must_start_ids": sorted(must_start_ids) if must_start_ids else [],
        "exclude_ids": sorted(exclude_ids) if exclude_ids else [],
        "gw_window": gw_window,
    }
    decision_id = log_decision(
        conn, "build_team", f"first team: {primary.label}, total_xp={gw1_xp}",
        detail, model_version=MODEL_VERSION,
        confidence=report.captain.confidence if report.captain else None,
    )
    # Real, cheap fallback for the live-alert layer's squad scoping
    # (ingestion/my_team.py::resolve_tracked_squad_ids, 2026-08-21) - the
    # "build_team" decision detail above stores web_names only, not ids
    # (see that dict's own "squad": [c.web_name for c in ...] line), so this
    # is the one place real ids from this exact build get persisted anywhere
    # cheap to read back.
    set_tracked_squad_ids(conn, [c.player_id for c in primary.result.squad])
    # Real synced start percentages (ingestion/lineup_probability_source.py),
    # where they exist, straight from the same source `optimise_squad` used
    # to decide who's even eligible - fetched before conn.close() so the
    # printed "Start%" column matches the real number that decided squad
    # membership, not only the older expected_minutes-derived proxy (real
    # gap found 2026-08-21: a synced 50% real percentage vs a derived 42%
    # for the same player was genuinely confusing shown side by side).
    real_start_percents = {
        c.player_id: get_start_percent(conn, c.player_id)
        for c in primary.xi.starting + primary.xi.bench
    }
    conn.close()

    click.echo(f"model_version={MODEL_VERSION} (see models/expected_points.py for component caveats)  decision_id={decision_id}")
    click.echo()
    xp_col = "xP" if gw_window == 1 else f"{gw_window}gw-xP"
    click.echo(f"{'Pos':<4} {'Player':<20} {'Price':>7} {'Start%':>7} {xp_col:>6}  Risk")
    for c in primary.xi.starting:
        start_pct = real_start_percents.get(c.player_id)
        if start_pct is None:
            start_pct = min(c.expected_minutes / 90 * 100, 100)
        tag = " (C)" if c is primary.xi.captain else " (VC)" if c is primary.xi.vice_captain else ""
        click.echo(f"{c.position:<4} {c.web_name:<20} £{c.price_tenths/10:>5.1f}m {start_pct:>6.0f}% {c.median:>6.2f}  {c.confidence}{tag}")
    click.echo("-- bench --")
    for c in primary.xi.bench:
        start_pct = real_start_percents.get(c.player_id)
        if start_pct is None:
            start_pct = min(c.expected_minutes / 90 * 100, 100)
        click.echo(f"{c.position:<4} {c.web_name:<20} £{c.price_tenths/10:>5.1f}m {start_pct:>6.0f}% {c.median:>6.2f}  {c.confidence}")

    # Real bug caught 2026-08-21 while wiring --gw-window through: this label
    # used to always say "GW1" - once gw_window>1, `gw1_xp` is a real summed
    # multi-GW total (via optimise_squad's own n_gw), not a single match, and
    # the old fixed label would have silently lied about what the number
    # means. Dynamic now - "GW1" only when the window genuinely is 1.
    xp_label = "GW1 expected points" if gw_window == 1 else f"{gw_window}-GW expected points"
    click.echo()
    click.echo(f"Total Cost:            £{primary.result.total_cost_tenths/10:.1f}m")
    click.echo(f"{xp_label}:   {gw1_xp}")
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
    set_tracked_squad_ids(conn, [c.player_id for c in result.squad])
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


@cli.command("transfer-analysis")
@click.option("--squad", default=None, help="comma-separated player ids (default: the real locked squad, if one exists)")
@click.option("--bank", default=None, type=float, help="bank in £m - required when --squad is given explicitly")
def transfer_analysis_cmd(squad: str | None, bank: float | None):
    """Real ROLL vs TRANSFER counterfactual, plus the captaincy equivalent
    (2026-08-26, optimizer-precision + auditability pass) - real GW1/3/5
    squad totals for rolling, ranked real alternative candidates with
    rejection reasons, robustness (ROBUST/MODERATE/FRAGILE from shared
    Monte Carlo trials), and a qualitative-evidence note when one genuinely
    applies. Defaults to the real locked squad if no --squad is given."""
    from fpl_agent.optimization.decision_analysis import analyze_captain_decision, analyze_transfer_decision
    from fpl_agent.optimization.decision_sensitivity import stress_test_transfer
    from fpl_agent.optimization.locked_squad import LockedSquadState, get_locked_squad

    conn = get_connection()
    try:
        if squad is not None:
            if bank is None:
                click.echo("--bank is required when --squad is given explicitly", err=True)
                raise SystemExit(1)
            squad_ids = _parse_squad_option(squad)
            locked = LockedSquadState(
                source="manual", event=0, squad_ids=frozenset(squad_ids), xi=None,
                bank_tenths=round(bank * 10), squad_value_tenths=0, decision_id=None,
            )
        else:
            locked = get_locked_squad(conn)
            if locked is None:
                click.echo("no real locked squad found - pass --squad and --bank explicitly", err=True)
                raise SystemExit(1)

        a = analyze_transfer_decision(conn, locked)
        c = analyze_captain_decision(conn, locked)
        stress_report = None
        minutes_dist = None
        if a.chosen is not None:
            stress_report = stress_test_transfer(
                conn, a.chosen.candidate.player_out_id, a.chosen.candidate.player_in_id,
                from_event=a.event, is_hit=a.chosen.candidate.uses_hit,
            )
            from fpl_agent.models.minutes_distribution import minutes_bucket_probabilities
            from fpl_agent.models.rules import current_season

            season = current_season(conn)
            minutes_dist = {
                "out": minutes_bucket_probabilities(conn, a.chosen.candidate.player_out_id, season),
                "in": minutes_bucket_probabilities(conn, a.chosen.candidate.player_in_id, season),
            }
    finally:
        conn.close()

    click.echo(f"DECISION: {a.decision_kind.upper()}")
    click.echo(f"reason: {a.reason}")
    if a.robustness:
        click.echo(f"robustness (Monte Carlo stability): {a.robustness}")
    if a.evidence_confidence:
        click.echo(f"evidence confidence (real data sufficiency): {a.evidence_confidence}")
    if a.decision_confidence:
        click.echo(
            f"DATA_CONFIDENCE={a.data_confidence}  MODEL_CONFIDENCE={a.model_confidence}  "
            f"DECISION_CONFIDENCE={a.decision_confidence}  (margin={a.margin_ratio}x the real materiality bar)"
        )
    if a.qualitative_note:
        click.echo(f"football intelligence: {a.qualitative_note}")
    click.echo()
    if a.roll is not None:
        click.echo(f"ROLL  GW{a.event}: {a.roll.per_gw.get(a.event)}  "
                    f"1gw={a.roll.horizon_totals[1]}  3gw={a.roll.horizon_totals[3]}  5gw={a.roll.horizon_totals[5]}")
    for opt in a.candidates:
        cand = opt.candidate
        marker = " <- CHOSEN" if a.chosen is not None and opt.rank == a.chosen.rank else ""
        click.echo(
            f"#{opt.rank}  {cand.player_out_name} -> {cand.player_in_name}  "
            f"1gw={opt.horizon_advantage[1]:+.2f}  3gw={opt.horizon_advantage[3]:+.2f}  5gw={opt.horizon_advantage[5]:+.2f}{marker}  "
            f"[OUT={opt.player_out_confidence} IN={opt.player_in_confidence}]"
        )
        if opt.rejected_reason:
            click.echo(f"     rejected: {opt.rejected_reason}")
    if a.evidence_reasons:
        click.echo()
        click.echo("evidence trail:")
        for r in a.evidence_reasons:
            click.echo(f"  - {r}")
    click.echo()
    click.echo(a.future_ft_note)

    if minutes_dist is not None:
        click.echo()
        click.echo(f"MINUTES DISTRIBUTION (real, empirical where enough current-season matches exist):")
        mo, mi = minutes_dist["out"], minutes_dist["in"]
        click.echo(
            f"  OUT {a.chosen.candidate.player_out_name:15s} p(0min)={mo.p_zero:.2f}  p(1-59min)={mo.p_partial:.2f}  "
            f"p(60+min)={mo.p_full:.2f}  source={mo.source}"
        )
        click.echo(
            f"  IN  {a.chosen.candidate.player_in_name:15s} p(0min)={mi.p_zero:.2f}  p(1-59min)={mi.p_partial:.2f}  "
            f"p(60+min)={mi.p_full:.2f}  source={mi.source}"
        )

    if stress_report is not None:
        click.echo()
        click.echo(f"STRESS TEST ({a.chosen.candidate.player_out_name} -> {a.chosen.candidate.player_in_name}):")
        click.echo(f"  baseline: net_3gw={stress_report.baseline_net_ev_3gw:+.2f}  decision={stress_report.baseline_decision.upper()}")
        any_flip = False
        for s in stress_report.scenarios:
            flip = s.decision_under_scenario != stress_report.baseline_decision
            any_flip = any_flip or flip
            marker = "  <-- FLIPS" if flip else ""
            click.echo(f"  {s.name:32s} net_3gw={s.net_ev_3gw:+.2f}  {s.decision_under_scenario.upper()}{marker}   ({s.description})")
        if not any_flip:
            click.echo("  no tested scenario (+/-15-30% minutes assumptions) flips the decision")

    click.echo()
    click.echo(f"CAPTAIN: {c.decision_kind.upper()}")
    click.echo(f"reason: {c.reason}")
    if c.robustness:
        click.echo(f"robustness (Monte Carlo stability): {c.robustness}")
    if c.evidence_confidence:
        click.echo(f"evidence confidence (real data sufficiency): {c.evidence_confidence}")
    if c.qualitative_note:
        click.echo(f"football intelligence: {c.qualitative_note}")
    for ranked in c.options:
        o = ranked.option
        marker = " <- CURRENT/SUGGESTED" if c.suggested is not None and o.player_id == c.suggested.player_id else ""
        click.echo(
            f"#{ranked.rank}  {o.web_name}  median={o.median}  floor={o.floor}  ceiling={o.ceiling}  "
            f"model_confidence={o.confidence}  evidence_confidence={ranked.confidence}{marker}"
        )
        if ranked.rejected_reason:
            click.echo(f"     rejected: {ranked.rejected_reason}")


@cli.command("season-sim")
@click.option("--squad", required=True, help="comma-separated player ids")
@click.option("--trials", default=1000, type=int, help="number of Monte Carlo scenario trials")
@click.option("--horizon", default=5, type=int, help="horizon in GWs")
@click.option("--used-chips", default=None, help="comma-separated chip names already used this season (e.g. wildcard,bboost) - excluded from scheduling. Omit to auto-detect from a synced `fpl my-team` entry, if one exists.")
def season_sim(squad: str, trials: int, horizon: int, used_chips: str | None):
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
        elif from_event + horizon - 1 < max_window_event:
            # Real gap found 2026-08-20 (the user caught this live, not this project's
            # own review): a short horizon starves schedule_chips' DP of visibility
            # into most of a real chip window (e.g. bboost/3xc/wildcard eligible
            # through GW19, horizon=5 only shows it GW1-5) - it still finds the best
            # placement WITHIN what it can see, but that's an artifact of the
            # simulated window, not genuine season-long chip timing (it can't know
            # whether a real double gameweek exists later, the actual reason bench
            # boost/triple captain have value). The chip schedule below should not
            # be treated as trustworthy season-long advice when this fires.
            click.echo(
                f"WARNING: horizon only covers GW{from_event}-{from_event + horizon - 1}, but the "
                f"nearest chip window stays open through GW{max_window_event} - any chip placement "
                f"below is only optimal within this short window, not a genuine season-long "
                f"recommendation (it has no visibility into later fixture swings or double gameweeks, "
                f"the real reason bench boost/triple captain have value). Standard real FPL strategy - "
                f"hold chips barring an obvious, visible reason - is usually the safer read this early."
            )

        if used_chips is not None:
            used_chip_names = {c.strip() for c in used_chips.split(",") if c.strip()}
        else:
            # Real gap closed 2026-08-21: previously always had to be typed in
            # by hand (no live FPL account integration existed). Now reads
            # real played chips off a synced `fpl my-team` entry when one is
            # saved - explicit --used-chips always wins over this, never
            # silently overridden.
            my_team_entry_id = get_my_team_entry_id(conn)
            used_chip_names = get_used_chips(conn, my_team_entry_id) if my_team_entry_id is not None else set()
            if used_chip_names:
                click.echo(f"(auto-detected used chips from your real team: {', '.join(sorted(used_chip_names))})")
        schedule = schedule_chips(conn, squad_ids, trajectory, windows, scenario_draw, used_chip_names=used_chip_names)
        explanations_by_key = {(e.event, e.chip_name): e for e in schedule.explanations}
        for entry in schedule.baseline_schedule:
            click.echo(f"GW{entry.event}  {entry.chip_name}  median +{entry.expected_marginal_value:.1f}")
            # Real "why now / why not later" narrative (2026-08-26,
            # GW1-postmortem audit P1) - built from the DP's own real
            # per-event trial medians, never a new heuristic.
            exp = explanations_by_key.get((entry.event, entry.chip_name))
            if exp is not None:
                if exp.best_alternative_event is not None:
                    click.echo(
                        f"  why now: GW{entry.event} (+{exp.expected_value:.1f}) beats the next-best real "
                        f"eligible GW{exp.best_alternative_event} (+{exp.best_alternative_value:.1f}) by "
                        f"{exp.opportunity_cost:.1f} - {exp.confidence} confidence"
                    )
                else:
                    click.echo(f"  why now: only real eligible GW for this chip in the sampled horizon - {exp.confidence} confidence")
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
            "chip_explanations": [
                {
                    "event": e.event, "chip_name": e.chip_name, "expected_value": e.expected_value,
                    "best_alternative_event": e.best_alternative_event, "best_alternative_value": e.best_alternative_value,
                    "opportunity_cost": e.opportunity_cost, "confidence": e.confidence,
                }
                for e in schedule.explanations
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


@cli.command("my-team")
@click.option("--entry-id", default=None, type=int, help="real FPL entry id (saved for future runs)")
@click.option("--event", default=None, type=int, help="gameweek to fetch picks for (default: latest locked)")
@click.option("--force", is_flag=True, help="re-fetch picks even if already synced for this event")
def my_team_cmd(entry_id: int | None, event: int | None, force: bool):
    """Sync and show your REAL FPL team - entry info, real past-season rank
    history, and (once a gameweek has locked) your real squad, rated the same
    way `fpl rate-team` rates any squad. Public FPL API, no login needed."""
    conn = get_connection()
    resolved_id = entry_id if entry_id is not None else get_my_team_entry_id(conn)
    if resolved_id is None:
        click.echo("no entry id saved yet - pass --entry-id <your real FPL team id> once", err=True)
        conn.close()
        raise SystemExit(1)
    if entry_id is not None:
        set_my_team_entry_id(conn, entry_id)

    try:
        result = sync_my_team(conn, resolved_id, event=event, force=force)
    except SourceFetchError as e:
        click.echo(f"my-team failed: {e}", err=True)
        conn.close()
        raise SystemExit(1)

    click.echo(f"entry_id       {resolved_id}")
    click.echo(f"manager        {result['manager_name']}")
    if result["history_error"]:
        click.echo(f"WARNING: season history fetch failed: {result['history_error']}", err=True)

    for row in conn.execute(
        "SELECT season_name, total_points, rank, rank_percentage FROM my_team_season_history "
        "WHERE entry_id=? ORDER BY season_name", (resolved_id,),
    ).fetchall():
        click.echo(f"  {row['season_name']}: {row['total_points']} pts, rank {row['rank']:,} (top {row['rank_percentage']}%)")

    picks = result["picks"]
    if not picks["fetched"]:
        click.echo(f"real squad: not available yet - {picks['reason']}")
        conn.close()
        return

    click.echo(f"\nreal squad, GW{picks['event']} ({picks['picks_count']} players):")
    latest = get_latest_squad(conn, resolved_id)
    if latest is None:
        conn.close()
        return
    real_event, real_ids = latest
    rating = rate_team(conn, real_ids)
    conn.close()

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
    click.echo(f"GW{real_event} expected points:  {rating.gw1_xp}")
    click.echo(f"Best possible (same budget): {rating.optimal_gw1_xp} xP")
    click.echo(f"Efficiency:                  {rating.efficiency_percent}% of the best achievable squad this GW")
    if rating.rule_violations:
        click.echo("WARNING: real squad does not satisfy real FPL rules (mid-GW transfer state?):", err=True)
        for v in rating.rule_violations:
            click.echo(f"  - {v}", err=True)


if __name__ == "__main__":
    cli()
