"""Real FPL-data provider abstraction (2026-08-29, "live architecture
rebuild" pass, milestone 5). Real finding while building this: this
project ALREADY has a genuine, well-shaped provider class for the
official FPL API - `ingestion/fpl_api.py::FPLApiAdapter` (players/prices/
fixtures/live-points/my-team/bonus, all real, no key needed) - built in
an earlier session, long before this "provider abstraction" spec existed.
This module does NOT reimplement or wrap it a second time; it just states
the real, already-satisfied contract as a `Protocol` so future code (and
this project's own live pipeline) can depend on the ABSTRACTION rather
than importing the concrete adapter directly, per the spec's own
"swappable provider" goal - zero behavior change to `FPLApiAdapter`
itself."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class FplDataProvider(Protocol):
    """The real capabilities `FPLApiAdapter` already has. Named generically
    (not `FPLApiAdapter`-specific) so a future alternative FPL-data source
    could satisfy this same shape - though, per this project's own
    standing rule, the official `fantasy.premierleague.com` API is the
    only real, free, authoritative source for this data and isn't
    expected to need swapping."""

    def fetch_bootstrap(self): ...

    def fetch_fixtures(self): ...

    def fetch_event_live(self, event: int): ...

    def fetch_entry_picks(self, entry_id: int, event: int): ...

    def fetch_entry_info(self, entry_id: int): ...

    def fetch_entry_history(self, entry_id: int): ...


# Real alias, not a new class (2026-08-29) - `FPLApiAdapter` already IS the
# real, concrete `FplDataProvider` implementation; this name lets calling
# code express "I depend on the provider abstraction" without reaching
# into `ingestion.fpl_api` directly, with zero duplicated logic.
from fpl_agent.ingestion.fpl_api import FPLApiAdapter as OfficialFplProvider  # noqa: E402
