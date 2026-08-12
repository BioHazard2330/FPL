import click

from fpl_agent.database.connection import get_connection
from fpl_agent.database.migrate import run_migrations
from fpl_agent.logging_setup import setup_logging
from fpl_agent.monitoring.doctor import run_checks
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


if __name__ == "__main__":
    cli()
