"""THE VERDICT: every player judged on several lenses at once, the way a manager does, instead of on expected points alone.

Lenses, each a 0-100 percentile among players of his FPL position with 450+ league minutes (or among clubs, for fixtures):
- expected: the model's projection over the planning horizon (the plan's `xp_index`, else a fresh 5-gameweek window).
- returns: his real FPL points per 90 this season and over his last six gameweeks, averaged.
- value: real FPL points per £m.
- track: how far his real points have run above or below the model's frozen projections (`models/track_record.py`).
- fixtures: his club's next five, expected goals for an attacker, clean-sheet chance for a defender or keeper.
- security: the pre-flight checks (`models/move_checks.py`): clean 100, amber 60, red 15, capped at his start share over the last five gameweeks; boards that skip the full checks read the start checks from FPL's gameweek rows.
- crowd: FPL net transfers since the deadline (context only, weight 0).

Score = 0.30 expected + 0.20 returns + 0.10 value + 0.10 track + 0.15 fixtures + 0.15 security. The weights are a
judgement, set so no single lens decides: the model's projection is the best single forecast (returns and form were
measured not to beat it), but a player whose returns, value and track all point the other way is not protected
because the projection is fond of him. Where expected and returns differ by 35+ percentile points the verdict says so.

The plan reads it through `week_plan.eye_gates`: only a Strong verdict protects a player from being sold, and an
Avoid verdict (or a red flag) holds a purchase back."""
import sqlite3

WEIGHTS = {"expected": 0.30, "returns": 0.20, "value": 0.10, "track": 0.10, "fixtures": 0.15, "security": 0.15}
LABELS = ((80, "Strong"), (65, "Good"), (50, "Mixed"), (35, "Weak"), (0, "Avoid"))
MIN_MINUTES = 450


def _light_flags(hist: list[int] | None) -> list[dict]:
    """The start checks read from FPL's own gameweek rows, for boards that skip the full pre-flight run: a player who
    did not start his last gameweek, or started under four of his last five, is not shown as nailed."""
    if not hist or len(hist) < 3:
        return []
    flags = []
    if hist[-1] == 0:
        flags.append({"check": "benched_last", "level": "red", "text": "did not start his last gameweek"})
    last = hist[-5:]
    if sum(last) < 4:
        flags.append({"check": "starts", "level": "red" if sum(last) < 3 else "amber", "text": f"started {sum(last)} of his last {len(last)} gameweeks"})
    return flags


def _pct(values: dict[int, float], pid: int) -> float | None:
    if pid not in values or len(values) < 5:
        return None
    v = values[pid]
    below = sum(1 for x in values.values() if x < v)
    equal = sum(1 for x in values.values() if x == v) - 1
    return round(100 * (below + 0.5 * equal) / (len(values) - 1))


def _season_returns(conn: sqlite3.Connection, season: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    rows = conn.execute("SELECT player_id, event, minutes, total_points FROM player_gw_stats WHERE season = ? ORDER BY event", (season,)).fetchall()
    last_event = max((r["event"] for r in rows), default=0)
    for r in rows:
        d = out.setdefault(r["player_id"], {"m": 0, "p": 0, "lm": 0, "lp": 0, "series": []})
        d["m"] += r["minutes"] or 0
        d["p"] += r["total_points"] or 0
        d["series"].append((r["event"], r["total_points"] or 0, r["minutes"] or 0))
        if r["event"] > last_event - 6:
            d["lm"] += r["minutes"] or 0
            d["lp"] += r["total_points"] or 0
    return out


def build(conn: sqlite3.Connection, player_ids: list[int] | None = None, with_checks: bool = True) -> dict[int, dict]:
    """Verdicts for the given players (all with minutes when None), judged against their whole position."""
    from fpl_agent.models.fixture_outlook import team_fixture_outlook
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.models.rules import current_season
    from fpl_agent.models.track_record import records
    from fpl_agent.optimization.week_plan import latest_week_plan

    season = current_season(conn)
    event = _reference_event(conn)
    players = {r["id"]: r for r in conn.execute(
        "SELECT p.id, p.web_name, p.team_id, p.status, et.singular_name_short AS pos, t.short_name AS team, ph.value_tenths "
        "FROM players p JOIN element_types et ON et.id = p.element_type JOIN teams t ON t.id = p.team_id "
        "LEFT JOIN player_price_history ph ON ph.player_id = p.id AND ph.valid_until IS NULL WHERE p.removed = 0")}
    ret = _season_returns(conn, season)
    stored = latest_week_plan(conn)
    xp = {int(k): float(v) for k, v in ((stored[0].get("xp_index") or {}) if stored else {}).items()}
    track = records(conn)
    outlook = team_fixture_outlook(conn, event, 5)
    crowd = {r[0]: r[1] for r in conn.execute(
        "SELECT player_id, transfers_in_event - transfers_out_event FROM player_transfer_momentum_history WHERE valid_until IS NULL")}

    pool_by_pos: dict[str, list[int]] = {}
    for pid, p in players.items():
        if ret.get(pid, {}).get("m", 0) >= MIN_MINUTES:
            pool_by_pos.setdefault(p["pos"], []).append(pid)
    targets = player_ids if player_ids is not None else [p for lst in pool_by_pos.values() for p in lst]

    def lens(pos: str, fn) -> dict[int, float]:
        vals = {}
        for q in set(pool_by_pos.get(pos, [])) | {t for t in targets if t in players and players[t]["pos"] == pos}:
            v = fn(q)
            if v is not None:
                vals[q] = v
        return vals

    cache: dict[str, dict] = {}
    fix_attack = {tid: o["xg_for_total"] / max(o["fixtures"], 1) for tid, o in outlook.items()}
    fix_defence = {tid: o["cs_total"] / max(o["fixtures"], 1) for tid, o in outlook.items()}

    def returns_rate(q):
        d = ret.get(q)
        if not d or d["m"] < 90:
            return None
        season90 = d["p"] / d["m"] * 90
        last90 = d["lp"] / d["lm"] * 90 if d["lm"] >= 180 else season90
        return (season90 + last90) / 2

    def value_rate(q):
        d = ret.get(q)
        price = players[q]["value_tenths"]
        return d["p"] / (price / 10) if d and price else None

    from fpl_agent.models.track_record import start_shares

    start_share = start_shares(conn)
    starts_hist: dict[int, list[int]] = {}
    try:
        from fpl_agent.models.rules import current_season

        for q, st in conn.execute(
            "SELECT player_id, starts FROM player_gw_stats WHERE season = ? AND fixtures > 0 ORDER BY event", (current_season(conn),)
        ):
            starts_hist.setdefault(q, []).append(min(int(st or 0), 1))
    except Exception:
        pass

    weights = dict(WEIGHTS)
    try:
        from fpl_agent.models.self_tuning import sizes

        tuned = sizes(conn).get("verdict")
        if tuned and tuned.get("adopted"):
            weights = tuned["weights"]
    except Exception:
        pass
    out = {}
    for pid in targets:
        p = players.get(pid)
        if p is None:
            continue
        pos = p["pos"]
        if pos not in cache:
            cache[pos] = {
                "expected": lens(pos, lambda q: xp.get(q)),
                "returns": lens(pos, returns_rate),
                "value": lens(pos, value_rate),
                "track": lens(pos, lambda q: track.get(q, {}).get("mean_miss")),
            }
        c = cache[pos]
        fx_src = fix_attack if pos in ("MID", "FWD") else fix_defence
        lenses = {
            "expected": _pct(c["expected"], pid),
            "returns": _pct(c["returns"], pid),
            "value": _pct(c["value"], pid),
            "track": _pct(c["track"], pid),
            "fixtures": _pct(fx_src, p["team_id"]),
        }
        flags = []
        if with_checks:
            from fpl_agent.models.move_checks import check_player

            try:
                flags = check_player(conn, pid)
            except Exception:
                flags = []
        if not with_checks:
            flags = _light_flags(starts_hist.get(pid))
        share = start_share.get(pid)
        checked = 15 if any(f["level"] == "red" for f in flags) else 60 if flags else 100
        lenses["security"] = checked if share is None else min(checked, round(100 * share))
        have = {k: v for k, v in lenses.items() if v is not None}
        W = weights
        wsum = sum(W[k] for k in have)
        score = round(sum(W[k] * v for k, v in have.items()) / wsum) if wsum else None
        label = next(lab for cut, lab in LABELS if score is not None and score >= cut) if score is not None else "Unknown"
        d = ret.get(pid, {"m": 0, "p": 0, "lm": 0, "lp": 0, "series": []})
        notes = []
        e_, r_ = lenses["expected"], lenses["returns"]
        if e_ is not None and r_ is not None:
            if e_ - r_ >= 35:
                notes.append(f"the model rates him well above his returns ({e_} against {r_})")
            elif r_ - e_ >= 35:
                notes.append(f"his returns are well above what the model expects ({r_} against {e_})")
        tr = track.get(pid)
        if tr and abs(tr["mean_miss"]) >= 1:
            notes.append(f"{'beats' if tr['mean_miss'] > 0 else 'falls short of'} the model by {abs(tr['mean_miss']):.1f} a week over {tr['weeks']} weeks")
        out[pid] = {
            "player_id": pid, "name": p["web_name"], "team": p["team"], "position": pos,
            "price": (p["value_tenths"] or 0) / 10, "score": score, "label": label, "lenses": lenses,
            "facts": {
                "points": d["p"], "minutes": d["m"], "points_per_90": round(d["p"] / d["m"] * 90, 2) if d["m"] else None,
                "last6_points": d["lp"], "last6": [s[1] for s in d["series"][-6:]],
                "xp_horizon": round(xp[pid], 1) if pid in xp else None,
                "track_miss": tr["mean_miss"] if tr else None, "crowd_net": crowd.get(pid),
            },
            "flags": flags, "notes": notes,
        }
    return out
