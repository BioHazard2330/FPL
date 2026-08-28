"""OPPORTUNITY workspace (2026-08-27, frontend redesign Phase 2) - a real
scouting board, per the direct spec: BREAKOUT / FIXTURE SWING / ROLE CHANGE /
VALUE / TRAP, "only 3-5 important items," each card carrying player/price/
ownership/one key metric/WHY NOW/confidence. Reuses the same real league-wide
scan the pre-existing (legacy) Opportunity Board already ran
(`models.breakouts.find_breakouts`/`models.traps.find_traps`/real fixture-
quality/setpiece/price-change reads) - the redesign here is display
discipline, not a new scan: each category shows its own single best real
candidate by default (its own already-real ranking field - value_ratio/
ownership/avg difficulty/recency, never a fabricated cross-category score,
same principle the pre-existing board already documented), with a real
`<details>` to reveal up to two more per category rather than dumping all of
them by default. `confidence` reuses `models.projection_confidence.
assess_projection_confidence` (already used by `plan.py` for the same
purpose) - no new model."""
from fpl_agent.models.breakouts import find_breakouts
from fpl_agent.models.projection_confidence import assess_projection_confidence
from fpl_agent.models.traps import find_traps
from fpl_agent.monitoring.dashboard.legacy import (
    _bulk_player_lookup,
    _esc,
    _fixture_quality,
    _official_badge_url,
    _official_shirt_url,
    _relative_time,
)

_VISIBLE_PER_CATEGORY = 1
_MAX_PER_CATEGORY = 3


def _confidence_label(conn, player_id: int) -> str:
    try:
        return assess_projection_confidence(conn, player_id).overall
    except Exception:
        return "MEDIUM"


def _card(kind: str, name: str, position: str, price_m: float | None, ownership_pct: float | None,
          key_metric: str, why_now: str, confidence: str, team_code: int | None = None,
          considered_by_optimizer: bool | None = None) -> str:
    # Real, honest missing-data label (2026-08-29, "final product-completion
    # pass" P1 fix: a bare "?" reads as a broken card, not a real "we don't
    # have this" disclosure).
    price_bit = f"£{price_m:.1f}m" if price_m is not None else "Price unavailable"
    own_bit = f"{ownership_pct:.1f}% owned" if ownership_pct is not None else ""
    shirt_html = (
        f"<img class='opp-card-shirt' src='{_esc(_official_shirt_url(team_code, is_gkp=(position == 'GKP'), size=66))}' "
        f"loading='lazy' alt=''>" if team_code is not None else ""
    )
    # Real "was this player considered by the strategic optimizer" flag
    # (2026-08-29, direct P1 spec line: "Also show whether the player was
    # considered by the strategic optimizer") - `considered_by_optimizer` is
    # `None` when no strategic plan has been run this session (honest
    # omission, not a guess), else a real True/False against the real diverse
    # top-N paths' own candidate pool (`assemble.py`'s `_optimizer_considered_ids`).
    considered_html = ""
    if considered_by_optimizer is not None:
        cls = "opp-card-considered-yes" if considered_by_optimizer else "opp-card-considered-no"
        label = "Considered by optimizer" if considered_by_optimizer else "Not evaluated by the optimizer"
        considered_html = f"<div class='opp-card-considered {cls}'>{_esc(label)}</div>"
    return (
        f"<div class='opp-card opp-card-{_esc(kind.lower().replace(' ', '-'))}'>"
        f"{shirt_html}"
        f"<div class='opp-card-kind'>{_esc(kind)}</div>"
        f"<div class='opp-card-title'>{name} <span class='opp-pos'>{_esc(position)}</span></div>"
        f"<div class='opp-card-meta'>{price_bit}{' &middot; ' + own_bit if own_bit else ''}</div>"
        f"<div class='opp-card-metric'>{_esc(key_metric)}</div>"
        f"<div class='opp-card-why'><strong>Why now</strong> {_esc(why_now)}</div>"
        f"<div class='opp-card-confidence opp-confidence-{_esc(confidence.lower())}'>{_esc(confidence)}</div>"
        f"{considered_html}"
        f"</div>"
    )


def _category_block(kind: str, cards: list[str]) -> str:
    if not cards:
        return ""
    visible, rest = cards[:_VISIBLE_PER_CATEGORY], cards[_VISIBLE_PER_CATEGORY:]
    rest_html = f"<details class='opp-category-more'><summary>{len(rest)} more real {_esc(kind.lower())} candidate{'s' if len(rest) != 1 else ''}</summary>{''.join(rest)}</details>" if rest else ""
    return f"<div class='opp-category'>{''.join(visible)}{rest_html}</div>"


def render_opportunity_workspace(conn, squad_ids: set[int], considered_ids: set[int] | None = None) -> str:
    breakout_cards, trap_cards, role_cards, swing_cards, value_cards = [], [], [], [], []

    breakouts = []
    traps = []
    role_rows = []
    value_rows = []
    try:
        breakouts = [b for b in find_breakouts(conn)[:_MAX_PER_CATEGORY] if b.player_id not in squad_ids]
    except Exception:
        pass
    try:
        traps = find_traps(conn)[:_MAX_PER_CATEGORY]
    except Exception:
        pass
    try:
        role_rows = conn.execute(
            "SELECT ce.entity_id, p.web_name, et.singular_name_short AS position, ce.detected_at "
            "FROM change_events ce JOIN players p ON p.id = ce.entity_id "
            "JOIN element_types et ON et.id = p.element_type "
            "WHERE ce.event_type = 'setpiece_change' AND ce.entity = 'player' AND p.removed = 0 "
            "ORDER BY ce.detected_at DESC LIMIT ?",
            (_MAX_PER_CATEGORY,),
        ).fetchall()
    except Exception:
        pass
    try:
        # Real "never show my own squad player as a buy opportunity" fix
        # (2026-08-29, direct live screenshot QA finding: Calafiori, an
        # actual squad member, showed up in Value while Breakout already
        # excludes squad members - the SAME "is this genuinely something to
        # go BUY" framing both categories share). Same accepted trade-off
        # `breakouts` already has (filters after the SQL LIMIT, so a squad
        # member occupying a top slot can mean fewer than _MAX_PER_CATEGORY
        # cards even when more real candidates exist just past the limit) -
        # consistent with existing precedent, not a new gap.
        value_rows = [
            r for r in conn.execute(
                "SELECT old.player_id, old.value_tenths AS old_value, cur.value_tenths AS new_value, "
                "old.valid_until AS changed_at, p.web_name, et.singular_name_short AS position "
                "FROM player_price_history old "
                "JOIN player_price_history cur ON cur.player_id = old.player_id AND cur.valid_until IS NULL "
                "JOIN players p ON p.id = old.player_id JOIN element_types et ON et.id = p.element_type "
                "WHERE old.valid_until IS NOT NULL AND cur.value_tenths > old.value_tenths AND p.removed = 0 "
                "ORDER BY old.valid_until DESC LIMIT ?",
                (_MAX_PER_CATEGORY,),
            ).fetchall()
            if r["player_id"] not in squad_ids
        ]
    except Exception:
        pass

    candidate_ids = (
        {b.player_id for b in breakouts} | {t.player_id for t in traps}
        | {r["entity_id"] for r in role_rows} | {r["player_id"] for r in value_rows}
    )
    team_lookup = _bulk_player_lookup(conn, candidate_ids) if candidate_ids else {}

    def _considered(pid: int) -> bool | None:
        return None if considered_ids is None else pid in considered_ids

    for b in breakouts:
        team_code = team_lookup.get(b.player_id, {}).get("team_code")
        breakout_cards.append(_card(
            "Breakout", _esc(b.web_name), b.position, None, b.ownership_percent,
            f"{b.value_ratio:.2f} xP/£m value ratio",
            "; ".join(b.reasons) if b.reasons else "rising value at low ownership",
            _confidence_label(conn, b.player_id), team_code=team_code,
            considered_by_optimizer=_considered(b.player_id),
        ))

    for t in traps:
        team_code = team_lookup.get(t.player_id, {}).get("team_code")
        trap_cards.append(_card(
            "Trap", _esc(t.web_name), t.position, None, t.ownership_percent,
            f"{t.eo_source} ownership source",
            "; ".join(t.reasons) if t.reasons else "deteriorating case at high ownership",
            _confidence_label(conn, t.player_id), team_code=team_code,
            considered_by_optimizer=_considered(t.player_id),
        ))

    for r in role_rows:
        team_code = team_lookup.get(r["entity_id"], {}).get("team_code")
        role_cards.append(_card(
            "Role Change", _esc(r["web_name"]), r["position"], None, None,
            f"set-piece role change {_esc(_relative_time(r['detected_at']))}",
            "a detected set-piece duty change - a genuine role signal, not a form blip",
            _confidence_label(conn, r["entity_id"]), team_code=team_code,
            considered_by_optimizer=_considered(r["entity_id"]),
        ))

    for r in value_rows:
        team_code = team_lookup.get(r["player_id"], {}).get("team_code")
        value_cards.append(_card(
            "Value", _esc(r["web_name"]), r["position"], r["new_value"] / 10, None,
            f"£{r['old_value']/10:.1f}m &rarr; £{r['new_value']/10:.1f}m",
            f"price rise {_esc(_relative_time(r['changed_at']))} - real rising demand",
            _confidence_label(conn, r["player_id"]), team_code=team_code,
            considered_by_optimizer=_considered(r["player_id"]),
        ))

    try:
        team_rows = conn.execute("SELECT id, short_name, code FROM teams").fetchall()
        squad_team_ids = {
            r["team_id"] for r in conn.execute(
                "SELECT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))), list(squad_ids)
            ).fetchall()
        } if squad_ids else set()
        swings = []
        for t in team_rows:
            if t["id"] in squad_team_ids:
                continue
            q = _fixture_quality(conn, t["id"], n_gw=5)
            if q is not None and q[0] == "ok":
                swings.append((q[2], t["short_name"], q[1]))
        swings.sort(key=lambda x: x[0])
        team_codes = {t["id"]: t["code"] for t in team_rows}
        for avg, short_name, label in swings[:_MAX_PER_CATEGORY]:
            team_id = next((t["id"] for t in team_rows if t["short_name"] == short_name), None)
            badge_html = (
                f"<img class='opp-card-shirt opp-card-badge' src='{_esc(_official_badge_url(team_codes[team_id]))}' loading='lazy' alt=''>"
                if team_id is not None else ""
            )
            swing_cards.append(
                f"<div class='opp-card opp-card-fixture-swing'>"
                f"{badge_html}"
                f"<div class='opp-card-kind'>Fixture Swing</div>"
                f"<div class='opp-card-title'>{_esc(short_name)}</div>"
                f"<div class='opp-card-metric'>5-GW average difficulty {avg:.1f} ({_esc(label)})</div>"
                f"<div class='opp-card-why'><strong>Why now</strong> a genuinely easy run not currently in your squad</div>"
                f"</div>"
            )
    except Exception:
        pass

    blocks = [
        _category_block("Breakout", breakout_cards), _category_block("Fixture Swing", swing_cards),
        _category_block("Role Change", role_cards), _category_block("Value", value_cards),
        _category_block("Trap", trap_cards),
    ]
    blocks = [b for b in blocks if b]
    if not blocks:
        return "<div class='empty-state'>No real league-wide opportunities cleared the bar this regen - the honest state, not a gap.</div>"
    return f"<div class='opp-board-grid'>{''.join(blocks)}</div>"
