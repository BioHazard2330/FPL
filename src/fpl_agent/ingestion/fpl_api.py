import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from fpl_agent.ingestion.raw_store import save_raw

PARSER_VERSION = "1"
BASE_URL = "https://fantasy.premierleague.com/api"


class SourceFetchError(Exception):
    pass


@dataclass(frozen=True)
class RawFetch:
    source_name: str
    data: Any
    retrieved_at: str
    latency_ms: int
    parser_version: str


class FPLApiAdapter:
    """Tier 1 official source. See config/sources.yaml."""

    def __init__(self, timeout: float = 10.0, max_retries: int = 3, backoff_base: float = 1.0):
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    def _get(self, source_name: str, path: str) -> RawFetch:
        url = f"{BASE_URL}{path}"
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            start = time.monotonic()
            try:
                resp = requests.get(url, timeout=self._timeout, headers={"User-Agent": "fpl-agent/0.1"})
                resp.raise_for_status()
                data = resp.json()
                latency_ms = int((time.monotonic() - start) * 1000)
                retrieved_at = datetime.now(timezone.utc).isoformat()
                save_raw(source_name, data)
                return RawFetch(
                    source_name=source_name,
                    data=data,
                    retrieved_at=retrieved_at,
                    latency_ms=latency_ms,
                    parser_version=PARSER_VERSION,
                )
            except (requests.RequestException, ValueError) as e:
                last_error = e
                if attempt < self._max_retries:
                    time.sleep(self._backoff_base * (2 ** (attempt - 1)))

        raise SourceFetchError(f"{source_name} failed after {self._max_retries} attempts: {last_error}")

    def fetch_bootstrap(self) -> RawFetch:
        return self._get("fpl_api_bootstrap", "/bootstrap-static/")

    def fetch_fixtures(self) -> RawFetch:
        return self._get("fpl_api_fixtures", "/fixtures/")

    def fetch_element_summary(self, player_id: int) -> RawFetch:
        return self._get(f"fpl_api_element_summary_{player_id}", f"/element-summary/{player_id}/")

    def fetch_league_standings(self, league_id: int, page: int) -> RawFetch:
        return self._get(
            f"fpl_api_league_standings_{league_id}_p{page}",
            f"/leagues-classic/{league_id}/standings/?page_standings={page}",
        )

    def fetch_entry_picks(self, entry_id: int, event: int) -> RawFetch:
        return self._get(f"fpl_api_entry_picks_{entry_id}_{event}", f"/entry/{entry_id}/event/{event}/picks/")
