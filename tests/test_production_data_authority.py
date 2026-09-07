"""Real, permanent regression guard (2026-09-07, Phase 7.6 Part 1) - the
free historical archive recovered in Phase 7.5 (`historical_gw_snapshot`/
`historical_player_roster`/`historical_team_strength`/
`historical_identity_crosswalk`) must never become a runtime source for
the LIVE decision path (models/optimization/dashboard/CLI's live commands).
It is real, but scoped to closed historical seasons only - `season_backtest.py`
(backtesting) and the manual `repair-understat-players` CLI command are its
only legitimate consumers, confirmed via a direct source audit (Phase 7.6
Part 1). This test makes that boundary a permanent, automated guarantee
rather than a one-time audit finding that could silently rot."""
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src" / "fpl_agent"

_FORBIDDEN_TABLES = (
    "historical_gw_snapshot",
    "historical_player_roster",
    "historical_team_strength",
    "historical_identity_crosswalk",
)

# The real, disclosed, legitimate consumers - see `historical_archive_source.
# py`'s own module docstring and Phase 7.6's Part 1 audit. Everything else
# under `models/`, `optimization/`, `monitoring/`, and the CLI entry point
# is the real live decision/dashboard path this guard protects.
_ALLOWED_CONSUMERS = {
    _SRC / "ingestion" / "historical_archive_source.py",
    _SRC / "backtesting" / "season_backtest.py",
}

_LIVE_PATH_DIRS = ("models", "optimization", "monitoring")


def _iter_live_path_files():
    for dirname in _LIVE_PATH_DIRS:
        yield from (_SRC / dirname).rglob("*.py")
    yield _SRC / "cli" / "main.py"


def test_historical_archive_tables_never_referenced_outside_their_real_consumers():
    violations = []
    for path in _iter_live_path_files():
        if path in _ALLOWED_CONSUMERS:
            continue
        text = path.read_text(encoding="utf-8")
        for table in _FORBIDDEN_TABLES:
            if table in text:
                violations.append(f"{path.relative_to(_REPO_ROOT)} references {table!r}")
    assert not violations, (
        "Historical-archive-only tables leaked into the live decision/dashboard path:\n"
        + "\n".join(violations)
    )


def test_repair_unresolved_player_ids_is_not_wired_into_the_automatic_scheduled_cycle():
    """Real, confirmed (Phase 7.6 Part 1): the archive-crosswalk fallback
    this repair function uses only ever fires on an explicit, manual
    `fpl repair-understat-players` invocation - never automatically from
    `run_scheduled`, so a human always chooses which season it touches."""
    run_scheduled_source = (_SRC / "cli" / "main.py").read_text(encoding="utf-8")
    start = run_scheduled_source.index("def run_scheduled(")
    # The next top-level `def ` marks the end of this function's body -
    # a real, simple, sufficient boundary for this specific source file's
    # own consistent 4-space top-level indentation style.
    end = run_scheduled_source.index("\ndef ", start + len("def run_scheduled("))
    run_scheduled_body = run_scheduled_source[start:end]
    assert "repair_unresolved_player_ids" not in run_scheduled_body
    assert "run_season_backtest" not in run_scheduled_body
