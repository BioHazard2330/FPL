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
from fpl_agent.models.fixtures import _reference_event
from fpl_agent.monitoring.doctor import run_checks
from fpl_agent.monitoring.source_status import get_source_health
from fpl_agent.monitoring.storage import measure_storage
from fpl_agent.optimization.captaincy import captaincy_report
from fpl_agent.optimization.chips import (
    bench_boost_value,
    eligible_chips,
    freehit_value,
    triple_captain_value,
    wildcard_value,
)
from fpl_agent.optimization.squad import optimise_squad, pick_starting_xi
from fpl_agent.optimization.transfers import recommend as recommend_transfer


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


def _parse_squad_option(squad: str | None) -> list[int] | None:
    if not squad:
        return None
    return [int(x) for x in squad.split(",")]


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
    conn.close()

    click.echo(f"model_version={MODEL_VERSION} (preseason prior, uncalibrated - see CLAUDE.md)")
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
    conn.close()

    if report.best is None:
        click.echo("no valid squad")
        return

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
        click.echo()
        click.echo(f"bench boost value:    {bench_boost_value(conn, squad_ids)} xP")
        click.echo(f"triple captain value: {triple_captain_value(conn, squad_ids)} xP")
        click.echo(f"wildcard value (5gw): {wildcard_value(conn, squad_ids, n_gw=5)} xP")
        click.echo(f"free hit value:       {freehit_value(conn, squad_ids)} xP")
    conn.close()


@cli.command()
@click.option("--squad", required=True, help="comma-separated player ids (from fpl build-squad)")
@click.option("--bank", default=0.0, help="bank in £m, e.g. 0.5")
@click.option("--free-transfers", default=1, type=int)
@click.option("--gw-window", default=3, type=int, help="EV window for the comparison")
def transfers(squad: str, bank: float, free_transfers: int, gw_window: int):
    """Roll vs best transfer, compared on windowed net EV (not single-GW xP) - section 62."""
    conn = get_connection()
    rec = recommend_transfer(
        conn, _parse_squad_option(squad), bank_tenths=round(bank * 10), free_transfers=free_transfers, n_gw=gw_window
    )
    conn.close()
    click.echo(f"action: {rec.action}")
    click.echo(f"reason: {rec.reason}")
    if rec.best_candidate:
        c = rec.best_candidate
        click.echo(
            f"{c.player_out_name} -> {c.player_in_name}  "
            f"1gw={c.net_ev_1gw:+.2f} 3gw={c.net_ev_3gw:+.2f} 5gw={c.net_ev_5gw:+.2f}  "
            f"price_delta=£{c.price_delta_tenths/10:+.1f}m  hit={c.uses_hit}"
        )


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
    teams = conn.execute("SELECT id, short_name FROM teams ORDER BY short_name").fetchall()

    for event in range(start, start + n_gw):
        for t in teams:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM fixtures WHERE (team_h=? OR team_a=?) AND event=?",
                (t["id"], t["id"], event),
            ).fetchone()["c"]
            if count == 0:
                click.echo(f"GW{event}  BLANK   {t['short_name']}")
            elif count >= 2:
                click.echo(f"GW{event}  DOUBLE  {t['short_name']} ({count} fixtures)")
    conn.close()


if __name__ == "__main__":
    cli()
