from datetime import datetime, timedelta, timezone

from fpl_agent.models import news_warning as nw

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_the_rate_counts_only_fresh_headlines_and_a_flag_inside_the_window(monkeypatch):
    flags = {1: [T0 + timedelta(hours=10)], 2: [T0 - timedelta(days=2)], 3: [T0 + timedelta(hours=100)]}
    heads = [(1, T0, "hamstring", "BBC"), (2, T0, "injury", "BBC"), (3, T0, "knock", "BBC")]
    heads += [(10 + i, T0, "scan", "BBC") for i in range(30)]
    flags[0] = [T0 - timedelta(days=30)]
    monkeypatch.setattr(nw, "_flags", lambda conn: flags)
    monkeypatch.setattr(nw, "_headlines", lambda conn, *a, **k: heads)
    monkeypatch.setattr(nw, "_cache", {})

    class _Conn:
        def execute(self, sql):
            class _R:
                def fetchone(self):
                    return (0, "main", ":memory:test")
            return _R()

    rate = nw.warning_rate(_Conn())
    assert rate["fresh"] == 32 and rate["followed"] == 1
    assert round(rate["median_lead_hours"]) == 10


def test_injury_words_match_and_suspension_wording_does_not():
    assert nw.INJURY.search("Saka hamstring scan") and nw.INJURY.search("Forest sweat on Wood knock")
    assert not nw.INJURY.search("Which game will Palmer miss after red card?")
    assert not nw.INJURY.search("Isak a doubt for the weekend")


def test_a_player_already_flagged_gets_no_warning(db_conn, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(nw, "warning_rate", lambda conn: {"followed": 52, "fresh": 80, "rate": 0.65, "median_lead_hours": 11})
    monkeypatch.setattr(nw, "_headlines", lambda conn, ids=None, since=None: [(1, now, "Haaland knock", "BBC"), (2, now, "Saka injury", "BBC")])
    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t')")
    db_conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, squad_max_play, squad_select, updated_at) VALUES (4,'F','FWD','Fs',1,3,3,'t')")
    for pid, status in ((1, "a"), (2, "i")):
        db_conn.execute(f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES ({pid},{pid},'P{pid}',1,4,'{status}',0,'t')")
    out = nw.fresh_warnings(db_conn, [1, 2], now)
    assert set(out) == {1}
    assert "65% of the time (52 of 80)" in nw.warning_sentence(out[1])


def test_an_injury_headline_for_a_squad_player_raises_one_high_event(db_conn, monkeypatch):
    from fpl_agent.ingestion.change_detection import detect_injury_headlines

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(nw, "fresh_warnings", lambda conn, ids, now=None: {
        1: {"title": "Haaland knock", "source": "BBC", "published_at": "2026-10-28T10:00:00+00:00",
            "rate": {"followed": 52, "fresh": 80, "rate": 0.65, "median_lead_hours": 11}},
        2: {"title": "Saka injury", "source": "BBC", "published_at": "2026-10-28T11:00:00+00:00",
            "rate": {"followed": 52, "fresh": 80, "rate": 0.65, "median_lead_hours": 11}},
    })
    assert detect_injury_headlines(db_conn, {1, 2}, {1}, now.isoformat()) == 2
    assert detect_injury_headlines(db_conn, {1, 2}, {1}, now.isoformat()) == 0
    rows = {r["entity_id"]: r["severity"] for r in db_conn.execute("SELECT entity_id, severity FROM change_events WHERE event_type='injury_headline'")}
    assert rows == {1: "HIGH", 2: "MEDIUM"}
