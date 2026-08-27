"""FIXTURE TOOL (2026-08-27, frontend redesign Phase 2) - real range/metric/
sort/filter controls, per the direct spec benchmarked against fpl.page's own
ticker (not just a colored table). Range and metric are both progressive-
enhancement over one real 8-GW server render (no second query path): every
cell carries its own real overall/attack/defence FDR class as data
attributes, and range/metric/filter are pure client-side reveals over
already-rendered real data - only sort was already like this pre-redesign.

Attack/defence split reuses `models.fixtures.fixture_difficulty` (already
built, already real - not a new model) - honest about FPL's own current gap:
`strength_attack_*`/`strength_defence_*` are still all-zero this preseason
(FPL hasn't published the split yet), so `fixture_difficulty` correctly
falls back to the same overall strength for all three metrics right now
(`used_fallback=True`, disclosed via a banner) - the toggle is real and will
start differentiating the moment FPL publishes real attack/defence ratings,
no code change needed."""
from fpl_agent.models.blend import clean_sheet_probability
from fpl_agent.models.fixtures import fixture_difficulty, team_fixture_ticker
from fpl_agent.monitoring.dashboard.legacy import (
    _FIXTURE_QUALITY_LABEL,
    _cached_fixture_goals_for,
    _esc,
    _fdr_class,
    _official_badge_url,
)

_RANGE_MAX_GW = 8


def _team_perspective_attack_defence(conn, fixture_id: int, team_id: int, is_home: bool) -> tuple[int, int, bool]:
    fd = fixture_difficulty(conn, fixture_id)
    if is_home:
        return fd.team_h_attack_difficulty, fd.team_h_defence_difficulty, fd.used_fallback
    return fd.team_a_attack_difficulty, fd.team_a_defence_difficulty, fd.used_fallback


def render_fixture_tool_html(conn, squad_ids: set[int]) -> str:
    goals_cache: dict[int, tuple[float, float]] = {}
    team_rows = conn.execute("SELECT id, short_name, code FROM teams ORDER BY short_name").fetchall()
    if not team_rows:
        return "<div class='empty-state'>No team data synced yet.</div>"
    squad_team_ids = set()
    if squad_ids:
        squad_team_ids = {
            r["team_id"] for r in conn.execute(
                "SELECT DISTINCT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
                tuple(squad_ids),
            ).fetchall()
        }

    any_fallback = False
    rows_html = []
    for r in team_rows:
        entries = team_fixture_ticker(conn, r["id"], n_gw=_RANGE_MAX_GW)
        cells = []
        for e in entries:
            fixture_row = conn.execute("SELECT * FROM fixtures WHERE id=?", (e.fixture_id,)).fetchone()
            goals_for, goals_against = _cached_fixture_goals_for(conn, fixture_row, r["id"], goals_cache)
            cs_pct = round(clean_sheet_probability(goals_against) * 100)
            overall_cls = _fdr_class(e.difficulty)
            attack_diff, defence_diff, used_fallback = _team_perspective_attack_defence(conn, e.fixture_id, r["id"], e.is_home)
            any_fallback = any_fallback or used_fallback
            attack_cls = _fdr_class(round(attack_diff))
            defence_cls = _fdr_class(round(defence_diff))
            venue_word = "at home" if e.is_home else "away"
            cells.append(
                f"<div class='fdr-cell fdr-{overall_cls}' data-event='{e.event}' "
                f"data-fdr-overall='{overall_cls}' data-fdr-attack='{attack_cls}' data-fdr-defence='{defence_cls}' "
                f"title='GW{e.event}: {_esc(r['short_name'])} vs {_esc(e.opponent_short)} {venue_word} - "
                f"{_esc(_FIXTURE_QUALITY_LABEL[overall_cls])} (xGF {goals_for:.1f}, CS {cs_pct}%)'>"
                f"<div class='fdr-opp'>{_esc(e.opponent_short)}{'(H)' if e.is_home else '(A)'}</div>"
                f"</div>"
            )
        blanks = _RANGE_MAX_GW - len(entries)
        cells.append(f"<div class='fdr-cell fdr-blank' data-event='' data-fdr-overall='blank' data-fdr-attack='blank' data-fdr-defence='blank'>-</div>" * blanks)
        row_cls = "fdr-row fdr-row-squad" if r["id"] in squad_team_ids else "fdr-row"
        avg_fdr = sum(e.difficulty for e in entries) / len(entries) if entries else 5.0
        badge_url = _official_badge_url(r["code"])
        rows_html.append(f"""<div class="{row_cls}" data-avg-fdr="{avg_fdr:.2f}" data-team-name="{_esc(r['short_name'])}" data-in-squad="{'1' if r['id'] in squad_team_ids else '0'}">
  <div class="fdr-team"><img class="fdr-badge" src="{_esc(badge_url)}" loading="lazy" alt="">{_esc(r['short_name'])}</div>
  <div class="fdr-cells">{''.join(cells)}</div>
</div>""")

    fallback_note = (
        "<div class='panel-subtitle fixture-tool-fallback-note'>Attack/Defence splits: FPL hasn't published "
        "separate attack/defence strength ratings yet this preseason - showing overall strength for all three "
        "metrics until real splits are available.</div>" if any_fallback else ""
    )

    controls = f"""<div class="fixture-tool-controls">
  <div class="fixture-tool-control-group" role="group" aria-label="Gameweek range">
    <span class="fdr-sort-label">Range</span>
    <button type="button" class="fdr-range-btn" data-range="3">3 GW</button>
    <button type="button" class="fdr-range-btn is-active" data-range="5">5 GW</button>
    <button type="button" class="fdr-range-btn" data-range="8">8 GW</button>
  </div>
  <div class="fixture-tool-control-group" role="group" aria-label="Difficulty metric">
    <span class="fdr-sort-label">Metric</span>
    <button type="button" class="fdr-metric-btn is-active" data-metric="overall">Overall</button>
    <button type="button" class="fdr-metric-btn" data-metric="attack">Attack</button>
    <button type="button" class="fdr-metric-btn" data-metric="defence">Defence</button>
  </div>
  <div class="fixture-tool-control-group" role="group" aria-label="Sort">
    <span class="fdr-sort-label">Sort</span>
    <button type="button" class="fdr-sort-btn is-active" data-sort="fdr">Easiest first</button>
    <button type="button" class="fdr-sort-btn" data-sort="fdr-desc">Hardest first</button>
    <button type="button" class="fdr-sort-btn" data-sort="squad">My squad first</button>
    <button type="button" class="fdr-sort-btn" data-sort="az">A&ndash;Z</button>
  </div>
  <div class="fixture-tool-control-group" role="group" aria-label="Filter">
    <span class="fdr-sort-label">Filter</span>
    <button type="button" class="fdr-filter-btn is-active" data-filter="all">All teams</button>
    <button type="button" class="fdr-filter-btn" data-filter="squad">My squad only</button>
  </div>
</div>"""

    return f"""{controls}
{fallback_note}
<div class="fdr-grid" id="fdr-grid">
{''.join(rows_html)}
</div>"""
