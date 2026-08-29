"""Real football-data provider abstraction (2026-08-29, "live architecture
rebuild" pass, milestone 5 - direct spec: "create a provider abstraction...
so the provider can later be swapped without changing the rest of the
application"). Resolved earlier in this same pass (user's own answer to a
direct clarifying question): a real, paid, "authorized" provider (Opta,
Stats Perform, an official league feed) needs a paid contract, which
conflicts with this project's own standing "free resources only, no paid
APIs" rule - FotMob's real public JSON endpoint stays the sole provider
IMPLEMENTATION, wrapped behind this real interface. This satisfies the
"swappable provider" architecture goal honestly, without pretending to
integrate a provider this project has no access to.

`FootballDataProvider` is a `typing.Protocol` (structural typing, PEP 544) -
deliberately NOT an ABC requiring subclassing. This means `FotMobProvider`
below is real and concrete, but a FUTURE provider never has to inherit
from anything to satisfy this contract, just implement the same real
method shapes - the lowest-friction way to keep a provider genuinely
swappable in a project that already has zero dependency-injection
framework."""
from datetime import date as date_cls
from typing import Protocol, runtime_checkable


@runtime_checkable
class FootballDataProvider(Protocol):
    """The real capabilities this project's own FotMob client already has
    (confirmed live, this same pass): fixtures for a date, full match
    detail (score/minute/events/team-stats/player-stats/momentum/shot
    map), and real match-id discovery by team name + date (never a
    hardcoded id)."""

    def fetch_matches_for_date(self, day: date_cls) -> dict: ...

    def find_match(self, day: date_cls, home_team_name: str, away_team_name: str) -> str | None: ...

    def fetch_match_details(self, match_id: str) -> dict: ...


class FotMobProvider:
    """Real, concrete `FootballDataProvider` - a thin class wrapper around
    the existing `ingestion/fotmob_source.py` module-level functions
    (`fetch_matches_for_date`/`find_match`/`fetch_match_details`), not a
    reimplementation. Deliberately looks the real functions up through the
    MODULE (`fpl_agent.ingestion.fotmob_source`) at call time rather than
    capturing bound references at import time - this project's own
    existing tests monkeypatch those exact module attributes
    (`monkeypatch.setattr(fotmob_mod, "find_match", ...)`), and a dynamic
    lookup is what keeps that real, already-established test pattern
    working unchanged for any code that goes through this provider too."""

    def fetch_matches_for_date(self, day: date_cls) -> dict:
        from fpl_agent.ingestion import fotmob_source

        return fotmob_source.fetch_matches_for_date(day)

    def find_match(self, day: date_cls, home_team_name: str, away_team_name: str) -> str | None:
        from fpl_agent.ingestion import fotmob_source

        return fotmob_source.find_match(day, home_team_name, away_team_name)

    def fetch_match_details(self, match_id: str) -> dict:
        from fpl_agent.ingestion import fotmob_source

        return fotmob_source.fetch_match_details(match_id)
