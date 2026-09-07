"""One authoritative decision snapshot, embedded into the dashboard page as
JSON for the Plan/Squad workspaces' client-side interactivity (2026-08-27,
frontend redesign). Deliberately minimal and purpose-built - not a database
dump: every field here is read straight off objects the rest of the
dashboard already computed this same regen (`sd` = the cached
`strategic_plan` decision detail, `ta`/`ca` = the real decision-analysis
objects, `locked` = the real locked squad) - no second query, no new
computation, no raw table export. If a workspace needs a field this module
doesn't carry, that's a signal to add the field here deliberately, not to
fall back to a bigger dump."""
import json

from fpl_agent.monitoring.dashboard.legacy import _bulk_player_lookup, _squad_state_by_event


def build_players_payload(conn, player_ids: set[int]) -> dict[str, dict]:
    """Minimal per-player lookup - name/team/position/price only (what a
    shirt tile or inspector needs to render), keyed by string id (JSON object
    keys are always strings - avoids a silent int/str mismatch on the client
    side)."""
    lookup = _bulk_player_lookup(conn, player_ids)
    return {
        str(pid): {
            "name": row["web_name"],
            "team": row["team_short"],
            "position": row["position"],
            "price": round(row["price_tenths"] / 10, 1) if row["price_tenths"] is not None else None,
        }
        for pid, row in lookup.items()
    }


def build_paths_payload(conn, sd: dict | None, locked, confidence_fn, descriptor_fn) -> list[dict]:
    """One entry per real strategic path (`sd['paths']`, already the top
    beam-width real paths from the single cached `strategic_plan` decision -
    never a fresh search). `confidence_fn(conn, path_dict) -> str | None` and
    `descriptor_fn(path_dict) -> str` are injected from `plan.py` (kept out of
    this module so the payload builder stays a pure data-shaping function,
    no evidence-tier computation of its own)."""
    if sd is None or not sd.get("paths") or locked is None:
        return []
    paths = sd["paths"]
    out = []
    for i, p in enumerate(paths, start=1):
        by_event = _squad_state_by_event(set(locked.squad_ids), p.get("steps") or [])
        steps_payload = []
        for step in p.get("steps") or []:
            steps_payload.append({
                "event": step["event"],
                "action": step.get("action", "ROLL"),
                "player_out_id": step.get("player_out_id"),
                "player_in_id": step.get("player_in_id"),
                "uses_hit": bool(step.get("uses_hit")),
                "chip": step.get("chip_played"),
                "squad_ids": sorted(by_event.get(step["event"], set(locked.squad_ids))),
            })
        out.append({
            "id": i,
            "label": f"Path {i}",
            "score": p.get("path_total"),
            "delta_vs_roll": p.get("delta_vs_roll"),
            "confidence": confidence_fn(conn, p),
            "descriptor": descriptor_fn(p),
            "is_leader": i == 1,
            "final_free_transfers": p.get("final_free_transfers"),
            "final_bank_tenths": p.get("final_bank_tenths"),
            "steps": steps_payload,
        })
    return out


def build_workspace_payload(conn, *, locked, sd: dict | None, current_rec: dict | None,
                             confidence_fn, descriptor_fn, freshness=None) -> dict:
    """The single JSON object embedded in the page - `decision` (the one
    authoritative current-recommendation snapshot, straight off `current_rec`/
    `sd` - never re-derived), `paths` (real top strategic paths), `players`
    (minimal lookup for every player id referenced anywhere in `paths`, so
    client-side rendering never needs a second data source).

    `freshness` (`models.decision_freshness.FreshnessResult` or `None`, added
    2026-08-29 P0 audit) supplies `decision.computed_at`/`decision_id`/
    `model_version`/`is_stale` - a client reading this JSON directly (or a
    future consumer) gets the same honest staleness signal the hero itself
    shows, never a bare recommendation with no provenance."""
    paths = build_paths_payload(conn, sd, locked, confidence_fn, descriptor_fn)
    all_ids: set[int] = set(locked.squad_ids) if locked is not None else set()
    for p in paths:
        for step in p["steps"]:
            all_ids |= set(step["squad_ids"])
            if step["player_out_id"] is not None:
                all_ids.add(step["player_out_id"])
            if step["player_in_id"] is not None:
                all_ids.add(step["player_in_id"])

    decision = None
    if current_rec is not None:
        decision = {
            "verdict": current_rec["verdict"],
            "action_kind": current_rec["action_kind"],
            "label": current_rec["label"],
            "path_total": current_rec["path_total"],
            "evidence_confidence": current_rec.get("evidence_confidence"),
            "computed_at": freshness.computed_at if freshness is not None else None,
            "decision_id": freshness.decision_id if freshness is not None else None,
            "model_version": freshness.model_version if freshness is not None else None,
            "is_stale": freshness.is_stale if freshness is not None else None,
            "stale_reason": freshness.stale_reason if freshness is not None else None,
        }

    return {
        "decision": decision,
        "horizon_gw": sd.get("horizon_gw") if sd else None,
        "paths": paths,
        "players": build_players_payload(conn, all_ids),
    }


def render_payload_script(payload: dict) -> str:
    """Embeds `payload` as a real JSON blob the client-side workspace script
    reads - `<` is escaped inside the JSON text so a literal `</script>`
    can never appear inside the payload and prematurely close the tag (the
    standard safe pattern for embedding JSON in HTML; values here are all
    real numeric/id/name data already escaped-safe as JSON, this guards the
    one remaining HTML-parsing edge case)."""
    raw = json.dumps(payload, default=str)
    safe = raw.replace("<", "\\u003c")
    return f'<script id="workspace-data" type="application/json">{safe}</script>'
