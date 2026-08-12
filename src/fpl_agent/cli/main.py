import click

from fpl_agent.database.connection import get_connection
from fpl_agent.database.migrate import run_migrations
from fpl_agent.ingestion.fpl_api import SourceFetchError
from fpl_agent.ingestion.sync import ValidationError, run_sync
from fpl_agent.logging_setup import setup_logging
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
    click.echo(f"rules changed   {summary['rules_changed']}")
    click.echo(f"raw pruned      {summary['raw_files_pruned']}")
    click.echo(f"retrieved_at    {summary['retrieved_at']}")


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


if __name__ == "__main__":
    cli()
