"""Real tests for the provider abstraction (2026-08-29, "live architecture
rebuild" pass, milestone 5, direct spec: "create the abstraction so the
provider can later be swapped without changing the rest of the
application"). Proves genuine swappability - not just that the interface
exists, but that a real alternative implementation actually gets used by
`sync_match` when injected."""
from datetime import date

from fpl_agent.ingestion.fpl_api import FPLApiAdapter
from fpl_agent.providers import FootballDataProvider, FotMobProvider, FplDataProvider, OfficialFplProvider
from test_fotmob_source import _DETAILS_PAYLOAD, _seed


def test_fotmob_provider_satisfies_the_real_protocol():
    assert isinstance(FotMobProvider(), FootballDataProvider)


def test_official_fpl_provider_satisfies_the_real_protocol():
    assert isinstance(OfficialFplProvider(), FplDataProvider)
    assert OfficialFplProvider is FPLApiAdapter  # real alias, not a reimplementation


def test_fotmob_provider_delegates_to_the_real_module_functions(monkeypatch):
    """`FotMobProvider` must look the real functions up dynamically through
    the module (never capture a bound reference at import time) - this is
    what keeps this project's own existing `monkeypatch.setattr(fotmob_mod,
    "find_match", ...)` test pattern working for any caller that goes
    through the provider instead of the bare module function."""
    import fpl_agent.ingestion.fotmob_source as fotmob_mod

    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "real-injected-id")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: {"real": mid})

    provider = FotMobProvider()
    assert provider.find_match(date(2026, 8, 21), "Arsenal", "Coventry") == "real-injected-id"
    assert provider.fetch_match_details("real-injected-id") == {"real": "real-injected-id"}


def test_sync_match_accepts_a_real_injected_fake_provider(db_conn):
    """The real proof of genuine swappability (not just an unused
    interface): a completely custom fake provider, injected via `sync_match`'s
    new `provider` parameter, is what actually gets called - the real
    FotMob module functions are never touched."""
    from fpl_agent.ingestion.fotmob_source import sync_match

    _seed(db_conn)

    class FakeProvider:
        def __init__(self):
            self.find_match_calls = []
            self.fetch_calls = []

        def find_match(self, day, home_team_name, away_team_name):
            self.find_match_calls.append((day, home_team_name, away_team_name))
            return "5795363"

        def fetch_match_details(self, match_id):
            self.fetch_calls.append(match_id)
            return _DETAILS_PAYLOAD

    fake = FakeProvider()
    result = sync_match(db_conn, "Arsenal", "Coventry", date(2026, 8, 21), provider=fake)

    assert result["fotmob_match_id"] == "5795363"
    assert fake.find_match_calls == [(date(2026, 8, 21), "Arsenal", "Coventry")]
    assert fake.fetch_calls == ["5795363"]


def test_sync_match_defaults_to_the_real_fotmob_provider_when_none_given(monkeypatch, db_conn):
    """Backward compatibility - every pre-existing call site that doesn't
    pass `provider=` must behave exactly as before (the real default
    `FotMobProvider()`, which delegates to the real module functions)."""
    import fpl_agent.ingestion.fotmob_source as fotmob_mod
    from fpl_agent.ingestion.fotmob_source import sync_match

    _seed(db_conn)
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "5795363")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: _DETAILS_PAYLOAD)
    monkeypatch.setattr(fotmob_mod, "save_raw", lambda name, data: "raw/path.json")

    result = sync_match(db_conn, "Arsenal", "Coventry", date(2026, 8, 21))
    assert result["fotmob_match_id"] == "5795363"
