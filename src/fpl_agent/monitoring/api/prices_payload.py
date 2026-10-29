"""TONIGHT'S PRICES - the fitted chance of a rise at the next overnight price update (`models/price_model.tonight`) for the
squad, the players the plan has lined up (this week and on the road ahead), and the league's likeliest risers. Falls are
left out while the fall model does not beat the base rate on held-out nights (`price_model.usable`)."""

RISERS = 8


def build_prices_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models import price_model
    from fpl_agent.models.price_forecast import LIKELY_PROBABILITY
    from fpl_agent.optimization.week_plan import latest_week_plan, light_squad_state

    conn = get_connection()
    try:
        m = price_model.model(conn)
        if m is None or not price_model.usable(m, "rise"):
            return {"status": "no_model"}
        chances = price_model.cached_tonight(conn)
        state = light_squad_state(conn)
        squad = set(state["squad_ids"]) if state else set()
        targets: dict[int, str] = {}
        stored = latest_week_plan(conn)
        if stored is not None:
            plan = stored[0]
            for mv in plan.get("moves", []):
                targets[mv["into"]["player_id"]] = f"GW{plan['event']}"
            for wk in (plan.get("road_ahead") or {}).get("weeks", []):
                for mv in wk.get("moves", []):
                    if mv.get("in_id"):
                        targets.setdefault(mv["in_id"], f"GW{wk['event']}")
        ids = squad | set(targets) | {pid for pid, c in chances.items() if (c.get("p_rise") or 0) >= 0.25}
        if not ids:
            return {"status": "ok", "squad": [], "targets": [], "risers": []}
        marks = ",".join("?" * len(ids))
        info = {
            r["id"]: dict(r) for r in conn.execute(
                "SELECT p.id, p.web_name AS name, p.code AS photo_code, t.short_name AS team_short, t.code AS team_code, "
                "et.singular_name_short AS position, (SELECT now_cost FROM player_stats_snapshot s WHERE s.player_id = p.id "
                "ORDER BY retrieved_at DESC LIMIT 1) AS cost, (SELECT selected_by_percent FROM player_ownership_history o "
                f"WHERE o.player_id = p.id AND o.valid_until IS NULL) AS owned FROM players p JOIN teams t ON t.id = p.team_id "
                f"JOIN element_types et ON et.id = p.element_type WHERE p.id IN ({marks})", list(ids),
            )
        }

        def row(pid: int, when: str | None = None) -> dict:
            i = info.get(pid, {})
            c = chances.get(pid, {})
            return {
                "player_id": pid, "name": i.get("name"), "photo_code": i.get("photo_code"), "team_short": i.get("team_short"),
                "team_code": i.get("team_code"), "position": i.get("position"),
                "price": (i["cost"] / 10) if i.get("cost") else None, "owned": i.get("owned"),
                "p_rise": round(c["p_rise"], 3) if c.get("p_rise") is not None else None, "when": when,
            }

        def by_chance(rows: list[dict]) -> list[dict]:
            return sorted(rows, key=lambda r: -(r["p_rise"] or 0))

        risers = by_chance([row(pid) for pid, c in chances.items() if (c.get("p_rise") or 0) >= 0.25 and pid not in squad])
        return {
            "status": "ok",
            "squad": by_chance([row(pid) for pid in squad]),
            "targets": by_chance([row(pid, w) for pid, w in targets.items() if pid not in squad]),
            "risers": risers[:RISERS],
            "likely": LIKELY_PROBABILITY,
            "model": {"fitted_at": m["fitted_at"], "auc": round(m["models"]["rise"]["holdout"]["auc"], 3),
                      "holdout_rises": m["models"]["rise"]["holdout"]["events"]},
        }
    finally:
        conn.close()


build_prices_payload.needs_context = False  # type: ignore[attr-defined]
