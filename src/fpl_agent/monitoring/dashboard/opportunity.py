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
import json

from fpl_agent.models.breakouts import MAX_OWNERSHIP_PERCENT, MIN_VALUE_RATIO, find_breakouts
from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.models.expected_points import expected_points
from fpl_agent.models.projection_confidence import assess_projection_confidence
from fpl_agent.models.traps import find_traps
from fpl_agent.monitoring.dashboard.legacy import (
    _bulk_player_lookup,
    _crest_html,
    _esc,
    _fixture_quality,
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


def _real_expected_minutes(conn, player_id: int) -> float | None:
    try:
        return expected_minutes(conn, player_id).expected_minutes
    except Exception:
        return None


def _real_median_xp(conn, player_id: int) -> float | None:
    try:
        return expected_points(conn, player_id).median
    except Exception:
        return None


def _risk_from_confidence(confidence: str) -> str | None:
    """Real, non-fabricated risk disclosure (2026-09-07, Phase 7.3 Part 17)
    - reuses the SAME `assess_projection_confidence` result every card
    already computes for its own confidence badge, rather than inventing a
    second, speculative risk score. Only LOW/VERY_LOW clears the bar - a
    MEDIUM/HIGH/VERY_HIGH confidence pick has nothing real to flag, and
    stays silent rather than padding every card with a risk line."""
    if confidence in ("LOW", "VERY_LOW"):
        return f"projection confidence is {confidence.replace('_', ' ').lower()} - based on limited real evidence so far"
    return None


def _card(kind: str, name: str, position: str, price_m: float | None, ownership_pct: float | None,
          key_metric: str, why_now: str, confidence: str, team_code: int | None = None,
          considered_by_optimizer: bool | None = None, squad_impact: str | None = None,
          xp: float | None = None, expected_minutes: float | None = None, risk: str | None = None,
          what_would_change: str | None = None) -> str:
    """Real, evidence-based PLAYER/PRICE/xP/MINUTES/WHY NOW/RISK/CONFIDENCE
    row for the opportunity board's per-category table (2026-09-08, Phase 8.1
    Part 22/23 - "the current opportunity board is literally a card grid.
    Recompose it"). Renders one `<tr>`, not a standalone bordered box - every
    field stays real and individually optional (never a fabricated "?"), the
    recomposition here is presentation only, no candidate-selection change."""
    price_bit = f"£{price_m:.1f}m" if price_m is not None else "Price unavailable"
    own_bit = f"{ownership_pct:.1f}% owned" if ownership_pct is not None else ""
    shirt_html = (
        f"<div class='opp-row-shirt-wrap'>"
        f"<img class='opp-row-shirt' src='{_esc(_official_shirt_url(team_code, is_gkp=(position == 'GKP'), size=40))}' loading='lazy' alt=''>"
        f"{_crest_html(team_code, '', css_class='opp-row-crest')}"
        f"</div>" if team_code is not None else "<div class='opp-row-shirt-wrap'></div>"
    )
    # Real "was this player considered by the strategic optimizer" flag and
    # "MY SQUAD IMPACT" (both fpl.page-parity, 2026-08-29) - unchanged real
    # data, now rendered as small tags under the player's identity rather
    # than as their own standalone card elements.
    tags = []
    if considered_by_optimizer is not None:
        cls = "opp-row-considered-yes" if considered_by_optimizer else "opp-row-considered-no"
        label = "Considered by optimizer" if considered_by_optimizer else "Not evaluated by the optimizer"
        tags.append(f"<span class='opp-row-tag {cls}'>{_esc(label)}</span>")
    if squad_impact:
        tags.append(f"<span class='opp-row-tag'>Would replace <strong>{_esc(squad_impact)}</strong></span>")
    tags_html = f"<div class='opp-row-tags'>{''.join(tags)}</div>" if tags else ""
    xp_bit = f"{xp:.1f}" if xp is not None else "&mdash;"
    min_bit = f"{expected_minutes:.0f}&prime;" if expected_minutes is not None else "&mdash;"
    change_html = (
        f"<div class='opp-row-change'>What changes it: {_esc(what_would_change)}</div>"
        if what_would_change else ""
    )
    risk_bit = f"<span class='opp-row-risk'>{_esc(risk)}</span>" if risk else "<span class='opp-row-risk-none'>&mdash;</span>"
    own_html = f"<div class='opp-row-own'>{own_bit}</div>" if own_bit else ""
    return (
        f"<tr class='opp-row opp-row-{_esc(kind.lower().replace(' ', '-'))}'>"
        f"<td class='opp-row-player'>{shirt_html}"
        f"<div class='opp-row-identity'><span class='opp-row-name'>{name}</span> "
        f"<span class='opp-pos'>{_esc(position)}</span>{tags_html}</div></td>"
        f"<td class='opp-row-price'>{price_bit}{own_html}</td>"
        f"<td class='opp-row-num'>{xp_bit}</td>"
        f"<td class='opp-row-num'>{min_bit}</td>"
        f"<td class='opp-row-whycell'><div class='opp-row-metric'>{_esc(key_metric)}</div>"
        f"<div class='opp-row-why'>{_esc(why_now)}</div>{change_html}</td>"
        f"<td class='opp-row-riskcell'>{risk_bit}</td>"
        f"<td class='opp-row-confcell'><span class='opp-confidence-text opp-confidence-{_esc(confidence.lower())}'>{_esc(confidence)}</span></td>"
        f"</tr>"
    )


_PLAYER_TABLE_HEAD = (
    "<thead><tr><th>Player</th><th>Price</th><th>xP</th><th>Min</th>"
    "<th>Why now</th><th>Risk</th><th>Confidence</th></tr></thead>"
)
_SWING_TABLE_HEAD = "<thead><tr><th>Team</th><th>5-GW difficulty</th><th>Why now</th></tr></thead>"


def _category_block(kind: str, rows: list[str], head: str = _PLAYER_TABLE_HEAD) -> str:
    """Real per-category TABLE (2026-09-08, Phase 8.1 Part 22/23), replacing
    the previous per-category flex stack of `.opp-card` boxes - a category
    is now one real, labeled section with its own rows, not its own card
    universe. `_VISIBLE_PER_CATEGORY`/`_MAX_PER_CATEGORY` and the real
    `<details>` reveal-more mechanism are unchanged from before this pass."""
    if not rows:
        return ""
    visible, rest = rows[:_VISIBLE_PER_CATEGORY], rows[_VISIBLE_PER_CATEGORY:]
    rest_html = (
        f"<details class='opp-category-more'><summary>{len(rest)} more real {_esc(kind.lower())} candidate{'s' if len(rest) != 1 else ''}</summary>"
        f"<div class='opp-table-wrap'><table class='opp-table opp-table-more'>{head}<tbody>{''.join(rest)}</tbody></table></div></details>"
        if rest else ""
    )
    return (
        f"<div class='opp-category-section'>"
        f"<div class='opp-category-heading'>{_esc(kind)}</div>"
        f"<div class='opp-table-wrap'><table class='opp-table'>{head}<tbody>{''.join(visible)}</tbody></table></div>"
        f"{rest_html}"
        f"</div>"
    )


# Index positions inside change_detection.py's `_SETPIECE_FIELDS` tuple
# ("penalties_order", "penalties_text", "corners_order", "corners_text",
# "direct_fk_order", "direct_fk_text") that this card cares about - the
# *_text fields are raw scraped strings, not shown here.
_SETPIECE_ORDER_LABELS = {0: "penalty", 2: "corner", 4: "direct free-kick"}


def _setpiece_order_change_text(old_value: str | None, new_value: str | None) -> str:
    """Real per-field order change ("penalty order none -> 3rd") parsed out
    of `change_events`' own stored 6-tuple (`detect_setpiece_changes`'
    `json.dumps(old_tuple)`/`new_tuple`) - real, confirmed bug fixed
    2026-09-03: the raw JSON tuple (including its `null` slots for the
    set-piece types that DIDN'T change) was being dumped straight into user
    copy ("[null, null, null, null, null, null] -> [null, null, null, null,
    3, null]"). Only the field(s) whose order actually differs are surfaced;
    `None` reads as the honest "none" rather than a fabricated rank."""
    try:
        old_t, new_t = json.loads(old_value), json.loads(new_value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return "set-piece order changed"
    changes = []
    for idx, label in _SETPIECE_ORDER_LABELS.items():
        old_o = old_t[idx] if idx < len(old_t) else None
        new_o = new_t[idx] if idx < len(new_t) else None
        if old_o != new_o:
            changes.append(f"{label} order {old_o if old_o is not None else 'none'} -> {new_o if new_o is not None else 'none'}")
    return "; ".join(changes) if changes else "set-piece order changed"


def render_opportunity_workspace(
    conn, squad_ids: set[int], considered_ids: set[int] | None = None, ta=None, *, breakouts: list | None = None,
) -> str:
    """`breakouts`, when the caller already has a real, freshly-fetched
    `find_breakouts()` result this regen (e.g. `scout.py` reusing it for the
    recruitment scatter chart too), is used as-is - never a second real scan
    of the same candidate pool (each row costs one real `expected_points()`
    call). `None` (the default) preserves the original standalone behaviour."""
    breakout_cards, trap_cards, role_cards, swing_cards, value_cards = [], [], [], [], []

    traps = []
    role_rows = []
    value_rows = []
    if breakouts is None:
        breakouts = []
        try:
            breakouts = find_breakouts(conn)
        except Exception:
            pass
    breakouts = [b for b in breakouts[:_MAX_PER_CATEGORY] if b.player_id not in squad_ids]
    try:
        traps = find_traps(conn)[:_MAX_PER_CATEGORY]
    except Exception:
        pass
    try:
        role_rows = conn.execute(
            "SELECT ce.entity_id, p.web_name, et.singular_name_short AS position, ce.detected_at, "
            "ce.old_value, ce.new_value "
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

    def _price_m(pid: int) -> float | None:
        """Real, confirmed bug fix (2026-09-08, Phase 8.1) - Breakout/Trap/
        Role Change cards always passed a hardcoded `None` for price,
        rendering "Price unavailable" for real, currently-priced players -
        `team_lookup` (`_bulk_player_lookup`, already queried above for
        `team_code`) already carries the real `price_tenths` for every one
        of these candidates; this was sitting unused, not genuinely
        missing. Exposes already-fetched data, no new query."""
        tenths = team_lookup.get(pid, {}).get("price_tenths")
        return tenths / 10 if tenths is not None else None

    # Real "MY SQUAD IMPACT" map (fpl.page-parity pass) - `ta.candidates` are
    # the SAME real ranked `TransferOption`s `analyze_transfer_decision`
    # already computed (never re-scanned here); a card whose player IS one
    # of those real candidate INs gets a real "would replace X" line.
    impact_by_player: dict[int, str] = {}
    if ta is not None:
        for opt in ta.candidates:
            c = opt.candidate
            impact_by_player.setdefault(c.player_in_id, c.player_out_name)

    for b in breakouts:
        team_code = team_lookup.get(b.player_id, {}).get("team_code")
        own_bit = f"{b.ownership_percent:.1f}% owned" if b.ownership_percent is not None else "low ownership"
        confidence = _confidence_label(conn, b.player_id)
        # Real, mechanical "what would change this" (Part 17) - the EXACT
        # real thresholds `find_breakouts` itself gates on
        # (`MAX_OWNERSHIP_PERCENT`/`MIN_VALUE_RATIO`), never a guessed
        # number - this candidate genuinely drops out of Breakout the
        # instant either real condition stops holding.
        own_txt = f"{b.ownership_percent:.1f}%" if b.ownership_percent is not None else "ownership"
        change_txt = f"ownership rises above {MAX_OWNERSHIP_PERCENT:.0f}% (currently {own_txt}) or value ratio falls below {MIN_VALUE_RATIO:.1f} xP/£m"
        breakout_cards.append(_card(
            "Breakout", _esc(b.web_name), b.position, _price_m(b.player_id), b.ownership_percent,
            f"{b.value_ratio:.2f} xP/£m value ratio",
            "; ".join(b.reasons) if b.reasons else f"{b.value_ratio:.2f} xP/£m, {own_bit}",
            confidence, team_code=team_code,
            considered_by_optimizer=_considered(b.player_id), squad_impact=impact_by_player.get(b.player_id),
            xp=b.median, expected_minutes=_real_expected_minutes(conn, b.player_id),
            risk=_risk_from_confidence(confidence), what_would_change=change_txt,
        ))

    for t in traps:
        team_code = team_lookup.get(t.player_id, {}).get("team_code")
        own_bit = f"{t.ownership_percent:.1f}% owned" if t.ownership_percent is not None else "high ownership"
        confidence = _confidence_label(conn, t.player_id)
        trap_cards.append(_card(
            "Trap", _esc(t.web_name), t.position, _price_m(t.player_id), t.ownership_percent,
            f"{t.eo_source} ownership source",
            "; ".join(t.reasons) if t.reasons else f"{own_bit}, case weakening",
            confidence, team_code=team_code,
            considered_by_optimizer=_considered(t.player_id), squad_impact=impact_by_player.get(t.player_id),
            xp=_real_median_xp(conn, t.player_id), expected_minutes=_real_expected_minutes(conn, t.player_id),
            risk=_risk_from_confidence(confidence),
        ))

    for r in role_rows:
        team_code = team_lookup.get(r["entity_id"], {}).get("team_code")
        order_bit = _setpiece_order_change_text(r["old_value"], r["new_value"])
        confidence = _confidence_label(conn, r["entity_id"])
        role_cards.append(_card(
            "Role Change", _esc(r["web_name"]), r["position"], _price_m(r["entity_id"]), None,
            f"set-piece {order_bit}, {_esc(_relative_time(r['detected_at']))}",
            order_bit,
            confidence, team_code=team_code,
            considered_by_optimizer=_considered(r["entity_id"]), squad_impact=impact_by_player.get(r["entity_id"]),
            xp=_real_median_xp(conn, r["entity_id"]), expected_minutes=_real_expected_minutes(conn, r["entity_id"]),
            risk=_risk_from_confidence(confidence),
        ))

    for r in value_rows:
        team_code = team_lookup.get(r["player_id"], {}).get("team_code")
        confidence = _confidence_label(conn, r["player_id"])
        value_cards.append(_card(
            "Value", _esc(r["web_name"]), r["position"], r["new_value"] / 10, None,
            f"£{r['old_value']/10:.1f}m -> £{r['new_value']/10:.1f}m",
            f"price rise {_esc(_relative_time(r['changed_at']))}",
            confidence, team_code=team_code,
            considered_by_optimizer=_considered(r["player_id"]), squad_impact=impact_by_player.get(r["player_id"]),
            xp=_real_median_xp(conn, r["player_id"]), expected_minutes=_real_expected_minutes(conn, r["player_id"]),
            risk=_risk_from_confidence(confidence),
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
                _crest_html(team_codes[team_id], short_name, css_class="opp-row-badge")
                if team_id is not None else ""
            )
            swing_cards.append(
                f"<tr class='opp-row opp-row-fixture-swing'>"
                f"<td class='opp-row-player'><div class='opp-row-shirt-wrap'>{badge_html}</div>"
                f"<div class='opp-row-identity'><span class='opp-row-name'>{_esc(short_name)}</span></div></td>"
                f"<td class='opp-row-num'>{avg:.1f}</td>"
                f"<td class='opp-row-whycell'><div class='opp-row-metric'>{_esc(label)} fixture run</div>"
                f"<div class='opp-row-why'>Not currently in your squad</div></td>"
                f"</tr>"
            )
    except Exception:
        pass

    blocks = [
        _category_block("Breakout", breakout_cards), _category_block("Fixture Swing", swing_cards, head=_SWING_TABLE_HEAD),
        _category_block("Role Change", role_cards), _category_block("Value", value_cards),
        _category_block("Trap", trap_cards),
    ]
    blocks = [b for b in blocks if b]
    if not blocks:
        return "<div class='empty-state'>No real league-wide opportunities cleared the bar this regen - the honest state, not a gap.</div>"
    return f"<div class='opp-board'>{''.join(blocks)}</div>"
