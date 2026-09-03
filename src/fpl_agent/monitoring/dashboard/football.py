"""FOOTBALL screen (2026-09-02, Phase 6 - complete product rebuild). Answers:
what happened in real matches that should change my FPL thinking. Real
football-intelligence feed, not a news list - organized by real signal
category (`models/football_signal.py::squad_football_signals`, called
league-wide here rather than squad-scoped - the same real detector output
Intelligence's old "Who Benefits" panel already used, just widened, never a
second signal engine). Strength does the sorting: `decision_effect`/
`confidence` (both already-computed real fields) put a genuine role/set-piece
change ahead of routine minutes noise - never a fabricated "importance"
score.

Real, disclosed scope: MINUTES-category signals are the largest real bucket
(215 of 387 in a live check) and the least individually decision-relevant -
collapsed by default rather than given equal visual weight to the rarer,
higher-value SET_PIECE_CHANGE/CREATION/GOAL_THREAT categories."""
from fpl_agent.monitoring.dashboard.legacy import (
    _PROJECTION_GWS,
    _crest_html,
    _esc,
    _fixture_projections_html,
    _match_report_strip_html,
    _relative_time,
    _squad_changes_html,
)

_CATEGORY_LABEL = {
    "SET_PIECE_CHANGE": "SET PIECES", "ROLE_CHANGE": "ROLE CHANGE", "TACTICAL_CHANGE": "TACTICAL",
    "SET_PIECES": "SET PIECES", "GOAL_THREAT": "GOAL THREAT", "CREATION": "CREATION", "MINUTES": "MINUTES",
}
_CATEGORY_ICON = {
    "SET_PIECE_CHANGE": "⛳", "ROLE_CHANGE": "⇄", "TACTICAL_CHANGE": "⚙",
    "SET_PIECES": "⛳", "GOAL_THREAT": "⚽", "CREATION": "✦", "MINUTES": "⏱",
}
_CATEGORY_PRIORITY = ["SET_PIECE_CHANGE", "ROLE_CHANGE", "TACTICAL_CHANGE", "GOAL_THREAT", "CREATION", "SET_PIECES", "MINUTES"]
_DIRECTION_DOT = {"POSITIVE": "ok", "NEGATIVE": "bad", "NEUTRAL": "muted", "WATCH": "warn"}
_DEFAULT_VISIBLE_PER_CATEGORY = 6


def _signal_row_html(s, crest_by_team: dict, squad_ids: set[int]) -> str:
    """Real EVENT -> EVIDENCE -> FPL EFFECT row (Part 2/3 of the visual
    rebuild): `s.evidence` (the concrete stat fact - "5 shots, 0.89 xG",
    "corner order 3 -> 1") leads, `s.interpretation` (now a short, concrete
    FPL-consequence clause - never flowery prose, see `statistical_evidence.
    py`/`role_signal_detectors.py`) sits as a small tag next to it - never
    the other way round."""
    dot = _DIRECTION_DOT.get(s.direction, "muted")
    crest = crest_by_team.get(s.entity_id, "")
    icon = _CATEGORY_ICON.get(s.category, "•")
    expiry = f"<span class='fb-signal-expiry'>expires {_esc(_relative_time(s.expires_at))}</span>" if s.expires_at else ""
    mine = "<span class='fb-signal-mine'>MY SQUAD</span>" if s.entity_id in squad_ids else ""
    effect = f"<span class='fb-signal-effect'>{_esc(s.interpretation)}</span>" if s.interpretation else ""
    return f"""<div class="fb-signal-row{' fb-signal-row-mine' if s.entity_id in squad_ids else ''}">
    <span class="fb-signal-icon fb-signal-dot-{dot}">{icon}</span>
    {crest}<span class="fb-signal-entity">{_esc(s.entity_name or '')}</span>{mine}
    <span class="fb-signal-evidence">{_esc(s.evidence or '')}</span>
    {effect}
    <span class="fb-signal-confidence">{_esc(s.confidence.upper())}</span>
    {expiry}
  </div>"""


def _category_block_html(conn, category: str, signals: list, crest_by_team: dict, squad_ids: set[int]) -> str:
    if not signals:
        return ""
    label = _CATEGORY_LABEL.get(category, category.replace("_", " "))
    strong = category in ("SET_PIECE_CHANGE", "ROLE_CHANGE", "TACTICAL_CHANGE")
    # Real, deliberate category-by-role color (Part 13) - tactical change
    # gets the purple accent, role/set-piece changes keep the cyan
    # "structural decision" accent already established elsewhere - never
    # one flat color for every "strong" category.
    tactical_cls = " fb-category-tactical" if category == "TACTICAL_CHANGE" else ""
    # Real personalization (Part 23) - a squad-owned player's own signal
    # surfaces first within its category, never buried under league noise.
    ordered = sorted(signals, key=lambda s: s.entity_id not in squad_ids)
    visible_n = _DEFAULT_VISIBLE_PER_CATEGORY
    rows_html = "".join(_signal_row_html(s, crest_by_team, squad_ids) for s in ordered[:visible_n])
    rest = ordered[visible_n:]
    more = (
        f"<details class='fb-category-more'><summary>+{len(rest)} more</summary>"
        f"{''.join(_signal_row_html(s, crest_by_team, squad_ids) for s in rest)}</details>"
        if rest else ""
    )
    if category == "MINUTES":
        # Real de-emphasis - the largest, least individually decisive real
        # bucket collapses behind a disclosure rather than competing
        # visually with genuine role/set-piece/creation signals.
        return f"""<details class="fb-category fb-category-quiet">
    <summary>{_esc(label)} <span class="fb-category-count">{len(signals)}</span></summary>
    {rows_html}{more}
  </details>"""
    return f"""<div class="fb-category{' fb-category-strong' if strong else ''}{tactical_cls}">
    <div class="fb-category-label">{_esc(label)} <span class="fb-category-count">{len(signals)}</span></div>
    {rows_html}{more}
  </div>"""


def _team_recent_form(conn, team_id: int, n: int = 3) -> dict | None:
    """Real recent attack/defence numbers (Part 4) - `team_match_state`'s
    own real per-match xG/shots for this team, joined to the SAME match's
    opponent row (the table's PK is (match_id, team_id), always exactly 2
    rows per real match) for the real xG-conceded/shots-conceded half - no
    new ingestion, no projection, just an average over the real last N
    played matches. Returns `None` when nothing has been analyzed yet."""
    rows = conn.execute(
        "SELECT tms.xg AS xg_for, tms.shots AS shots_for, opp.xg AS xg_against, opp.shots AS shots_against "
        "FROM team_match_state tms JOIN match_intelligence mi ON mi.id = tms.match_id "
        "LEFT JOIN team_match_state opp ON opp.match_id = tms.match_id AND opp.team_id != tms.team_id "
        "WHERE tms.team_id=? AND mi.status='FULL_TIME' ORDER BY mi.kickoff_utc DESC LIMIT ?",
        (team_id, n),
    ).fetchall()
    rows = [r for r in rows if r["xg_for"] is not None]
    if not rows:
        return None
    xg_for = [r["xg_for"] for r in rows]
    shots_for = [r["shots_for"] for r in rows if r["shots_for"] is not None]
    xg_against = [r["xg_against"] for r in rows if r["xg_against"] is not None]
    shots_against = [r["shots_against"] for r in rows if r["shots_against"] is not None]
    return {
        "n": len(rows),
        "xg_for": sum(xg_for) / len(xg_for),
        "shots_for": (sum(shots_for) / len(shots_for)) if shots_for else None,
        "xg_against": (sum(xg_against) / len(xg_against)) if xg_against else None,
        "shots_against": (sum(shots_against) / len(shots_against)) if shots_against else None,
    }


def _team_state_card_html(conn, outlook, *, in_squad: bool, team_code: int) -> str | None:
    """Real ATTACK / DEFENCE / TACTICAL / FPL EFFECT card (Part 4/5 - "TEAM
    STATE must actually say something", never a bare 'Arsenal up-arrow').
    ATTACK/DEFENCE come from real `team_match_state` numbers
    (`_team_recent_form`); TACTICAL/FPL EFFECT reuse the real qualitative
    read `team_outlook` already computed (LLM-authored `current_*_signal`/
    `current_fpl_implication`) - never a second text-generation pass. A
    card with neither real numeric form NOR real qualitative text is
    skipped outright, never rendered empty."""
    form = _team_recent_form(conn, outlook.team_id, n=3)
    q = outlook.qualitative
    tactical_text = q.current_tactical_signal if q else None
    impact = q.current_fpl_implication if q else None
    if form is None and tactical_text is None and impact is None and outlook.formation is None:
        return None

    stat_tiles = []
    if form is not None:
        stat_tiles.append(("XG / MATCH", f"{form['xg_for']:.2f}"))
        if form["shots_for"] is not None:
            stat_tiles.append(("SHOTS / MATCH", f"{form['shots_for']:.1f}"))
        if form["xg_against"] is not None:
            stat_tiles.append(("XGA / MATCH", f"{form['xg_against']:.2f}"))
        if form["shots_against"] is not None:
            stat_tiles.append(("SHOTS CONCEDED", f"{form['shots_against']:.1f}"))
    stats_grid_html = (
        "<div class='fb-team-stat-grid'>" + "".join(
            f"<div class='fb-team-stat-tile'><span class='fb-team-stat-value'>{_esc(v)}</span>"
            f"<span class='fb-team-stat-label'>{_esc(k)}</span></div>"
            for k, v in stat_tiles
        ) + "</div>"
    ) if stat_tiles else ""
    tactical_html = ""
    if outlook.formation or tactical_text:
        bits = [b for b in (outlook.formation, tactical_text) if b]
        tactical_html = f"<div class='fb-team-row'><span class='fb-team-row-label'>TACTICAL</span><span class='fb-team-row-value'>{_esc(' - '.join(bits))}</span></div>"
    effect_html = f"<div class='fb-team-effect'>{_esc(impact)}</div>" if impact else ""
    risk_html = (
        f"<div class='fb-team-risk'>small sample - only {form['n']} match{'es' if form['n'] != 1 else ''} analyzed</div>"
        if form is not None and form["n"] < 3 else ""
    )
    squad_tag = "<span class='fb-team-squad-tag'>MY SQUAD</span>" if in_squad else ""
    crest_html = _crest_html(team_code, outlook.team_name, css_class="fb-team-crest")

    return f"""<div class="fb-team-card{' fb-team-card-mine' if in_squad else ''}">
  <div class="fb-team-head">{crest_html}<span class="fb-team-name">{_esc(outlook.team_name.upper())}</span>{squad_tag}</div>
  {stats_grid_html}
  {tactical_html}
  {effect_html}
  {risk_html}
</div>"""


def render_football_screen(conn, squad_ids: set[int], ca=None) -> str:
    from fpl_agent.models.football_signal import squad_football_signals
    from fpl_agent.monitoring.dashboard import fixtures as fixtures_mod
    from fpl_agent.monitoring.dashboard import market as market_mod
    from fpl_agent.optimization.decision_snapshot import build_decision_snapshot

    team_rows = conn.execute("SELECT id, code, short_name FROM teams ORDER BY short_name").fetchall()
    crest_by_team = {r["id"]: _crest_html(r["code"], r["short_name"], css_class="fb-signal-crest") for r in team_rows}

    player_ids = [r["id"] for r in conn.execute("SELECT id FROM players WHERE status != 'u'").fetchall()]
    # Real decision context (Part 23 personalization) - reuses the SAME
    # cached decision every other screen reads, never a second beam search;
    # `ca` is threaded in from `assemble.py`'s own already-computed captain
    # analysis so this never re-runs `analyze_captain_decision` a second
    # time per regen.
    try:
        decision_snapshot = build_decision_snapshot(conn, ca=ca)
    except Exception:
        decision_snapshot = None
    signals = squad_football_signals(conn, player_ids, lookback=5, decision_snapshot=decision_snapshot) if player_ids else []
    # `entity_id` on a player-scoped signal is the player id, not team - the
    # crest lookup below needs each signal's real team, resolved once.
    team_by_player = {
        r["id"]: r["team_id"] for r in conn.execute(
            "SELECT id, team_id FROM players WHERE id IN ({})".format(",".join("?" * len(player_ids)))
            , player_ids,
        ).fetchall()
    } if player_ids else {}
    crest_by_player = {pid: crest_by_team.get(team_by_player.get(pid), "") for pid in player_ids}

    by_category: dict[str, list] = {}
    for s in signals:
        by_category.setdefault(s.category, []).append(s)

    category_blocks = "".join(
        _category_block_html(conn, cat, by_category.get(cat, []), crest_by_player, squad_ids)
        for cat in _CATEGORY_PRIORITY
    )
    if not category_blocks:
        category_blocks = "<div class='empty-state'>No real match-analyzed signals yet - run <code>fpl match-analyze</code> once matches have been played.</div>"

    # Team-level cards - real ATTACK/DEFENCE/TACTICAL/FPL-EFFECT state
    # (`_team_state_card_html`, Part 4/5), squad teams surfaced first.
    squad_team_ids: set[int] = set()
    if squad_ids:
        squad_team_ids = {
            r["team_id"] for r in conn.execute(
                "SELECT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
                list(squad_ids),
            ).fetchall()
        }
    from fpl_agent.models.team_outlook import team_outlook
    team_cards = []
    for r in team_rows:
        outlook = team_outlook(conn, r["id"])
        card = _team_state_card_html(conn, outlook, in_squad=r["id"] in squad_team_ids, team_code=r["code"])
        if card is not None:
            team_cards.append((r["id"] not in squad_team_ids, card))
    team_cards.sort(key=lambda c: c[0])
    team_grid = f"<div class='fb-team-grid'>{''.join(c for _, c in team_cards)}</div>" if team_cards else \
        "<div class='empty-state'>No real team-level signals yet.</div>"

    changes_html = _squad_changes_html(conn, limit=12)
    evidence_html = _match_report_strip_html(conn, squad_ids)

    # Real fixture difficulty (2026-09-03, Phase 6 consolidation) - the
    # ticker/projections/team-odds views all read the SAME real Dixon-
    # Coles/odds-blended fixture-quality numbers `market.py`/`fixtures.py`
    # already computed; folded in here rather than left as three separate
    # legacy panels answering the same "how do the fixtures look" question.
    fixture_ticker_html = fixtures_mod.render_fixture_tool_html(conn, squad_ids)
    fixture_projections_html = _fixture_projections_html(conn, squad_ids)
    team_odds_html = market_mod.render_team_odds_html(conn)

    squad_signal_count = sum(1 for s in signals if s.entity_id in squad_ids)
    squad_bit = f"<span class='fb-status-item fb-status-mine'>{squad_signal_count} affect your squad</span>" if squad_signal_count else ""

    return f"""<section class="fb-screen" id="screen-football" data-screen="football">
  <div class="fb-status-line">
    <span class="fb-status-heading">FOOTBALL INTELLIGENCE</span>
    <span class="fb-status-item">{len(signals)} signals tracked</span>
    {squad_bit}
  </div>

  <div class="fb-feed">{category_blocks}</div>

  <div class="fb-section-label">TEAM STATE</div>
  {team_grid}

  <div class="fb-section-label">MANAGER / XI / AVAILABILITY</div>
  <div class="fb-changes">{changes_html}</div>

  <div class="fb-section-label">FIXTURE TICKER <span class="panel-subtitle">green easy, red hard, real FPL strength ratings</span></div>
  <div class="fb-fixture-ticker">{fixture_ticker_html}</div>

  <div class="fb-grid-2">
    <div class="fb-block">
      <h3>Fixture Projections <span class="panel-subtitle">real projected goals + clean sheet %, next {_PROJECTION_GWS} GWs</span></h3>
      {fixture_projections_html}
    </div>
    <div class="fb-block">
      <h3>Team Odds <span class="panel-subtitle">league-wide next-fixture clean sheet % / projected goals, ranked</span></h3>
      {team_odds_html}
    </div>
  </div>

  <details class="fb-evidence">
    <summary class="fb-section-label" style="display:inline-block">MATCH EVIDENCE</summary>
    <div class="outlook-grid">{evidence_html}</div>
  </details>
</section>"""
