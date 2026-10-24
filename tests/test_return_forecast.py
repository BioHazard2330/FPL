"""An injured or suspended player is forecast match by match, not held at zero for the whole window."""
from datetime import datetime, timedelta, timezone

import pytest

from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.models import return_forecast as rf
from fpl_agent.models.expected_points import _returning_probs
from fpl_agent.models.minutes_distribution import MinutesBucketProbabilities
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def _seed(conn, status="i", news=""):
    b = make_bootstrap()
    b["elements"][0]["status"] = status
    b["elements"][0]["news"] = news
    _upsert_many(conn, "teams", normalize_teams(b), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(b), "t0")
    _upsert_many(conn, "players", normalize_players(b), "t0")
    conn.commit()


def _status_change(conn, pid, old, new, when):
    conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, sources, confidence, severity) "
        "VALUES ('status_change','player',?,?,?,?,'[]','CONFIRMED','LOW')",
        (pid, old, new, when.isoformat()),
    )


def test_news_date_is_read_and_unknown_return_date_is_not():
    assert rf.parse_news_date("Hamstring injury - Expected back 31 Oct", NOW).date().isoformat() == "2026-10-31"
    assert rf.parse_news_date("Suspended until 7 Nov", NOW).date().isoformat() == "2026-11-07"
    assert rf.parse_news_date("Knee injury - Unknown return date", NOW) is None
    assert rf.parse_news_date("Expected back 2 Jan", NOW).date().isoformat() == "2027-01-02"


def test_fotmob_phrases_become_dates():
    assert rf.parse_fotmob_return("About a week", NOW).date().isoformat() == "2026-10-31"
    assert rf.parse_fotmob_return("Early November 2026", NOW).date().isoformat() == "2026-11-05"
    assert rf.parse_fotmob_return("Mid January 2027", NOW).date().isoformat() == "2027-01-15"
    assert rf.parse_fotmob_return("Doubtful", NOW) is None


def test_a_fit_player_gets_no_forecast_and_an_unavailable_one_is_zero(db_conn):
    _seed(db_conn, status="a")
    assert rf.return_forecast(db_conn, 1, NOW + timedelta(days=7), NOW) is None
    db_conn.execute("UPDATE players SET status='u' WHERE id=1")
    assert rf.return_forecast(db_conn, 1, NOW + timedelta(days=7), NOW).probability == 0.0


def test_a_dated_injury_is_out_before_the_date_and_likely_back_after(db_conn):
    _seed(db_conn, news="Hamstring injury - Expected back 7 Nov")
    before = rf.return_forecast(db_conn, 1, datetime(2026, 11, 1, 14, tzinfo=timezone.utc), NOW)
    after = rf.return_forecast(db_conn, 1, datetime(2026, 11, 14, 14, tzinfo=timezone.utc), NOW)
    assert before.probability == rf.BEFORE_DATE_PROBABILITY
    assert after.probability == rf.ON_DATE_PROBABILITY
    assert after.basis == "fpl_date"


def test_fotmobs_phrase_is_used_when_fpl_gives_no_date_and_it_is_fresh(db_conn):
    _seed(db_conn, news="Knee injury - Unknown return date")
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, status, retrieved_at) VALUES (1,'9','PRE_MATCH','t0')"
    )
    db_conn.execute(
        "INSERT INTO match_unavailable (match_id, fotmob_player_id, player_id, kind, expected_return, retrieved_at) "
        "VALUES (1,'5',1,'injury','Early November 2026',?)",
        (NOW.isoformat(),),
    )
    db_conn.commit()
    early = rf.return_forecast(db_conn, 1, datetime(2026, 10, 27, 14, tzinfo=timezone.utc), NOW)
    late = rf.return_forecast(db_conn, 1, datetime(2026, 11, 21, 14, tzinfo=timezone.utc), NOW)
    assert early.probability == rf.BEFORE_DATE_PROBABILITY and early.basis == "fotmob_date"
    assert late.probability == rf.FOTMOB_ON_DATE_PROBABILITY

    db_conn.execute("UPDATE match_unavailable SET retrieved_at=?", ((NOW - timedelta(days=30)).isoformat(),))
    db_conn.commit()
    stale = rf.return_forecast(db_conn, 1, datetime(2026, 11, 21, 14, tzinfo=timezone.utc), NOW)
    assert stale is None or stale.basis == "spell_history"


def test_without_any_date_the_spell_history_sets_the_chance(db_conn):
    _seed(db_conn, news="Knee injury - Unknown return date")
    base = NOW - timedelta(days=70)
    for k, days in enumerate([2, 3, 4, 5, 6, 7, 8, 9, 14, 21, 28, 35, 42]):
        pid = 100 + k
        db_conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,1,'a',0,'t0')",
            (pid, pid, f"P{pid}"),
        )
        _status_change(db_conn, pid, "a", "i", base)
        _status_change(db_conn, pid, "i", "a", base + timedelta(days=days))
    _status_change(db_conn, 1, "a", "i", NOW - timedelta(days=2))
    db_conn.commit()

    soon = rf.return_forecast(db_conn, 1, NOW + timedelta(days=3), NOW)
    later = rf.return_forecast(db_conn, 1, NOW + timedelta(days=30), NOW)
    assert soon.basis == "spell_history"
    assert later.probability > soon.probability
    assert 0.02 <= soon.probability < later.probability <= 1.0


def test_the_forecast_scales_the_fit_distribution_for_one_fixture(db_conn):
    _seed(db_conn, news="Hamstring injury - Expected back 7 Nov")
    row = db_conn.execute("SELECT '2026-11-14T14:00:00Z' AS kickoff_time").fetchone()
    healthy = MinutesBucketProbabilities(0.1, 0.1, 0.8, "empirical")
    probs = _returning_probs(db_conn, 1, row, healthy)
    assert probs.p_full == pytest.approx(0.8 * rf.ON_DATE_PROBABILITY)
    assert probs.p_partial == pytest.approx(0.1 * rf.ON_DATE_PROBABILITY)
    assert probs.p_zero == pytest.approx(1 - probs.p_full - probs.p_partial)
