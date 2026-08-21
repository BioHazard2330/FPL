from fpl_agent.ingestion.sync import sync_rules
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.normalization.fpl_core import flatten_rules

from test_sync import make_bootstrap


def test_current_season_ignores_non_bootstrap_rows_even_with_a_higher_id(db_conn):
    """Regression guard: current_season() used to be a plain `ORDER BY id DESC`
    over the whole rules table - correct only as long as every row is inserted
    in live-sync chronological order. The moment anything else inserts a rules
    row for a different season (e.g. migrations/0017's real, sourced historical
    scoring rules for backtesting), that assumption breaks. Confirmed live on
    the real production DB: right after that migration ran, this returned
    '2025-26' instead of '2026-27', which would have silently corrupted every
    live command that reads budget/club-limit/free-transfer rules through it
    (fpl build-team/transfers/etc). Reproduced synthetically here: insert the
    real current-season row FIRST, then a later-id historical row from a
    different source - current_season() must still return the live season."""
    db_conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) "
        "VALUES ('scoring.assists', '2026-27', 1, 't0', 'fpl_api_bootstrap', '3')"
    )
    # Inserted AFTER the real row, so it has a higher autoincrement id - the
    # exact condition that broke the old `ORDER BY id DESC` implementation.
    db_conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) "
        "VALUES ('scoring.assists', '1999-00', 1, 't0', 'tier2_ffs_reconstructed', '3')"
    )
    db_conn.commit()

    assert current_season(db_conn) == "2026-27"


def test_current_season_returns_none_with_no_bootstrap_rows(db_conn):
    db_conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) "
        "VALUES ('scoring.assists', '1999-00', 1, 't0', 'tier2_ffs_reconstructed', '3')"
    )
    db_conn.commit()

    assert current_season(db_conn) is None


def test_get_rule_unaffected_by_source(db_conn):
    """get_rule() itself is source-agnostic by design (only current_season()
    needed the source scope) - a rule lookup for an explicit season must still
    find a row regardless of who sourced it."""
    db_conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) "
        "VALUES ('scoring.assists', '1999-00', 1, 't0', 'tier2_ffs_reconstructed', '3')"
    )
    db_conn.commit()

    assert get_rule(db_conn, "1999-00", "scoring.assists") == 3


def test_current_season_and_get_rule_see_a_real_sync_on_the_same_connection(db_conn):
    """Real gap checked before shipping the 2026-08-21 caching fix, not
    assumed safe: both functions now cache per-connection for performance
    (a real, measured squad-build bottleneck). If a real `fpl sync` runs on
    the SAME connection after an earlier read already populated the cache,
    the next read must see the fresh synced value, not a stale one - this
    would be a genuine, dangerous correctness bug (every budget/club-limit/
    scoring read in the app goes through these two functions)."""
    bootstrap = make_bootstrap(squad_total_spend=1000)
    sync_rules(db_conn, flatten_rules(bootstrap), "2026-27", "fpl_api_bootstrap", "t0")
    db_conn.commit()

    assert current_season(db_conn) == "2026-27"  # populates the cache
    assert get_rule(db_conn, "2026-27", "rules.squad_total_spend") == 1000  # populates the cache

    bootstrap2 = make_bootstrap(squad_total_spend=1050)
    sync_rules(db_conn, flatten_rules(bootstrap2), "2026-27", "fpl_api_bootstrap", "t1")
    db_conn.commit()

    assert get_rule(db_conn, "2026-27", "rules.squad_total_spend") == 1050
    assert current_season(db_conn) == "2026-27"
