"""
Sampled effective ownership (Pillar 1 Plan 1c). See design doc
docs/superpowers/specs/2026-08-16-decision-intelligence-plan1c-design.md.
"""
import math
import sqlite3
import time
from datetime import datetime, timezone

from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.sync import update_source_health

OVERALL_LEAGUE_ID = 314
_ENTRIES_PER_PAGE = 50
_MAX_RANK = 10000
_DEFAULT_SAMPLE_SIZE = 750
_DEFAULT_DELAY_SECONDS = 0.15  # same politeness delay as history_sync.py


def select_stratified_pages(
    target_sample_size: int, entries_per_page: int = _ENTRIES_PER_PAGE, max_rank: int = _MAX_RANK
) -> list[int]:
    """Evenly-spread standings page numbers across the full rank 1..max_rank range,
    rather than clustering at the top of the list - top-of-list ranks are extreme
    overperformers, not a representative top-10k sample."""
    max_page = max_rank // entries_per_page
    n_pages = min(max(1, math.ceil(target_sample_size / entries_per_page)), max_page)
    if n_pages == 1:
        return [1]
    step = (max_page - 1) / (n_pages - 1)
    return sorted({1 + round(k * step) for k in range(n_pages)})
