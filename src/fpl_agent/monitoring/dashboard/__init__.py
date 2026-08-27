"""Dashboard package (2026-08-27, frontend redesign). Public API only -
`cli/main.py` needs `generate_dashboard_html`/`_REFRESH_SECONDS`; everything
else (workspace renderers, shared helpers, legacy panel functions) lives in
this package's own submodules and is imported directly from them (see
`legacy.py`, `home.py`, `plan.py`, `squad.py`, `data_payload.py`, `assemble.py`)."""
from fpl_agent.monitoring.dashboard.assemble import _REFRESH_SECONDS, generate_dashboard_html

__all__ = ["generate_dashboard_html", "_REFRESH_SECONDS"]
