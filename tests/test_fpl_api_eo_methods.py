from fpl_agent.ingestion.fpl_api import FPLApiAdapter


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json_data


def test_fetch_league_standings_calls_correct_url(monkeypatch, tmp_path):
    monkeypatch.setattr("fpl_agent.ingestion.raw_store.RAW_DIR", tmp_path)
    calls = []

    def fake_get(url, timeout, headers):
        calls.append(url)
        return _FakeResponse({"standings": {"page": 2, "results": [{"entry": 111, "player_name": "X"}]}})

    monkeypatch.setattr("fpl_agent.ingestion.fpl_api.requests.get", fake_get)

    adapter = FPLApiAdapter()
    fetch = adapter.fetch_league_standings(314, page=2)

    assert calls == ["https://fantasy.premierleague.com/api/leagues-classic/314/standings/?page_standings=2"]
    assert fetch.data["standings"]["results"][0]["entry"] == 111


def test_fetch_entry_picks_calls_correct_url(monkeypatch, tmp_path):
    monkeypatch.setattr("fpl_agent.ingestion.raw_store.RAW_DIR", tmp_path)
    calls = []

    def fake_get(url, timeout, headers):
        calls.append(url)
        return _FakeResponse({"active_chip": None, "picks": [{"element": 55, "multiplier": 2, "is_captain": True}]})

    monkeypatch.setattr("fpl_agent.ingestion.fpl_api.requests.get", fake_get)

    adapter = FPLApiAdapter()
    fetch = adapter.fetch_entry_picks(entry_id=42, event=1)

    assert calls == ["https://fantasy.premierleague.com/api/entry/42/event/1/picks/"]
    assert fetch.data["picks"][0]["multiplier"] == 2
