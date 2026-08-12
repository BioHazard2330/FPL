import sys

import click

# Windows consoles default to a legacy codepage that can't encode player
# names/news text pulled straight from the FPL API — force UTF-8 output.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fpl_agent.database.connection import get_connection
from fpl_agent.database.migrate import run_migrations
from fpl_agent.ingestion.fpl_api import SourceFetchError
from fpl_agent.ingestion.history_sync import sync_player_season_history
from fpl_agent.ingestion.sync import ValidationError, run_sync
from fpl_agent.logging_setup import setup_logging
from fpl_agent.models.availability import list_availability
from fpl_agent.models.expected_points import MODEL_VERSION, expected_points
from fpl_agent.monitoring.doctor import run_checks
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.monitoring.storage import measure_storage


@click.group()
def cli():
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
def storage():
    """Show DB/cache/log/temp footprint vs configured budget."""
    report = measure_storage()
    click.echo(f"database   {report.db_mb:>8.2f} MB")
    click.echo(f"cache      {report.cache_mb:>8.2f} MB")
    click.echo(f"logs       {report.logs_mb:>8.2f} MB")
    click.echo(f"temp       {report.temp_mb:>8.2f} MB")
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


@cli.command()
@click.option("--limit", default=20, help="max players to show")
@click.option("--position", default=None, help="filter by GKP/DEF/MID/FWD")
@click.option("--gw-window", default=1, help="fixture window size for clean-sheet calc")
def projections(limit: int, position: str | None, gw_window: int):
    """Top players by expected points. Preseason-prior model - see CLAUDE.md for
    the exact heuristics/assumptions behind these numbers."""
    conn = get_connection()
    results = []
    for r in conn.execute("SELECT id, web_name FROM players WHERE removed=0").fetchall():
        ep = expected_points(conn, r["id"], n_gw=gw_window)
        if position and ep.position != position.upper():
            continue
        results.append((r["web_name"], ep))
    conn.close()

    results.sort(key=lambda x: x[1].median, reverse=True)
    click.echo(f"model_version={MODEL_VERSION} (preseason prior, uncalibrated - see CLAUDE.md)")
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
def changes(limit: int):
    """Show recent change events (new/removed players, club changes, status changes, set pieces)."""
    conn = get_connection()
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


if __name__ == "__main__":
    cli()
