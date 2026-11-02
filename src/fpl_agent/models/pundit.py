"""THE PUNDIT - the week plan argued the way a pundit would argue it, every line a number the system already holds.

The solver decides on expected points (with the evidence shrink, the eye gate and, for the armband, the rank review).
A pundit weighs more than one number, so this module lays each move and the armband out across every lens the app
measures, fixture by fixture first (the manager compares targets that way before stats), then the football read,
minutes, set pieces, the top-10k field's ownership, the market (Solio's projection), the price, the replays that test
the move, cards and midweek football, and grades how many of them point the same way.

It never recommends anything the plan does not: a lens that disagrees is printed as the case against, and a move graded
"marginal" or "doubtful" is the plan's own move with the reasons it might not be worth making. Lenses measured not to
predict points (form streaks, eye ratings) are shown as context and never counted in the grade.

Grade: one point for each lens that clearly favours the move (fixtures over the horizon by 0.4 of a difficulty step or
more, a football read that backs the buy or is against the sale, Solio agreeing by 0.5 xP or more, the move winning
60%+ of its replays, a projected gain of 3+), minus one for each that clearly opposes it (the reverse of each, an
incoming player under 70% to start). 3+ strong, 1-2 sound, 0 marginal, below 0 doubtful. The thresholds are judgement,
stated here; the grade is a summary of the lenses, not a separate model."""
import sqlite3
from datetime import datetime, timedelta, timezone

POSITION_WORD = {"GKP": "keeper", "DEF": "defender", "MID": "midfielder", "FWD": "forward"}
FIXTURE_STEP = 0.4
SOLIO_STEP = 0.5
WIN_SOLID = 0.6
WIN_THIN = 0.52
BIG_GAIN = 3.0
START_FLOOR = 70
RISE_LIKELY = 0.25
YELLOW_WATCH = 4
MIDWEEK_DAYS = 7


def _run(fixtures: dict, team_code) -> list[dict]:
    return list(fixtures.get(str(team_code)) or fixtures.get(team_code) or [])


def _fixture_text(run: list[dict]) -> str:
    return " ".join(f"{f['opponent_short']}({'H' if f['is_home'] else 'a'}){f['difficulty']}" for f in run)


def _mean_difficulty(run: list[dict], n: int | None = None) -> float | None:
    vals = [f["difficulty"] for f in run[:n] if f.get("difficulty") is not None]
    return sum(vals) / len(vals) if vals else None


def top10k_ownership(conn: sqlite3.Connection, event: int, ids: set[int]) -> dict[int, tuple[float, float]]:
    """(effective ownership, captain share) in the top-10k field for each player, aged for `event`."""
    from fpl_agent.models.rank_engine import build_field

    field_model = build_field(conn, "top10k", for_event=event)
    if field_model is None:
        return {}
    return {pid: (field_model.eo.get(pid, 0.0), field_model.captain_share.get(pid, 0.0)) for pid in ids}


def _yellows(conn: sqlite3.Connection, ids: set[int]) -> dict[int, int]:
    from fpl_agent.models.suspension_risk import _current_yellows

    out = {}
    for pid in ids:
        try:
            n = _current_yellows(conn, pid)
        except Exception:
            n = None
        if n is not None:
            out[pid] = n
    return out


def _midweek(conn: sqlite3.Connection, ids: set[int], now: datetime | None = None) -> dict[int, list[str]]:
    now = now or datetime.now(timezone.utc)
    if not ids:
        return {}
    team_of = {r["id"]: r["team_id"] for r in conn.execute(f"SELECT id, team_id FROM players WHERE id IN ({','.join('?' * len(ids))})", sorted(ids))}
    hi = (now + timedelta(days=MIDWEEK_DAYS)).isoformat()
    by_team: dict[int, list[str]] = {}
    for r in conn.execute(
        "SELECT team_id, competition, opponent_name, kickoff_utc FROM team_other_competition_fixtures "
        "WHERE finished = 0 AND replace(kickoff_utc, 'Z', '+00:00') BETWEEN ? AND ? ORDER BY kickoff_utc",
        (now.isoformat(), hi),
    ):
        by_team.setdefault(r["team_id"], []).append(f"{r['competition']} v {r['opponent_name']} {r['kickoff_utc'][5:10]}")
    return {pid: by_team[t] for pid, t in team_of.items() if t in by_team}


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _verdict(side: dict) -> str | None:
    read = side.get("football_read") or {}
    return (read.get("verdict") or {}).get("label")


def move_brief(move: dict, fixtures: dict, eo: dict, yellows: dict, midweek: dict, horizon: int) -> dict:
    """Every lens as a chip: a short `value`, a `lean` (+1 for the move, -1 against, 0 context), whether it is `counted`
    in the grade, and the full sentence as `detail` for the hover. `for`/`against`/`context` keep the sentences."""
    out, into = move["out"], move["into"]
    lenses: list[dict] = []

    def add(key: str, label: str, value: str, lean: int, detail: str, counted: bool = True) -> None:
        lenses.append({"key": key, "label": label, "value": value, "lean": lean, "counted": counted and lean != 0, "detail": detail})

    gain = move.get("gain") or 0.0
    add("proj", "Projection", f"{gain:+.1f}", 1 if gain >= BIG_GAIN else 0,
        f"+{gain:.1f} over {horizon} gameweeks: {into['name']} {' / '.join(f'{x:.1f}' for x in into.get('xp_by_gw') or [])}, "
        f"{out['name']} {' / '.join(f'{x:.1f}' for x in out.get('xp_by_gw') or [])}.")

    run_in, run_out = _run(fixtures, into.get("team_code")), _run(fixtures, out.get("team_code"))
    if run_in and into.get("team_code") == out.get("team_code"):
        add("fixtures", "Fixtures", "same club", 0, f"Same club, same fixtures: {_fixture_text(run_in)}.")
    elif run_in and run_out:
        d_in, d_out = _mean_difficulty(run_in), _mean_difficulty(run_out)
        lean = 1 if d_out - d_in >= FIXTURE_STEP else -1 if d_in - d_out >= FIXTURE_STEP else 0
        add("fixtures", "Fixtures", f"{d_in:.1f} v {d_out:.1f}", lean,
            f"{into['team_short']} {_fixture_text(run_in)} (average {d_in:.1f}); {out['team_short']} {_fixture_text(run_out)} (average {d_out:.1f}).")

    v_in, v_out = _verdict(into), _verdict(out)
    read_in = ((into.get("football_read") or {}).get("verdict") or {}).get("text") or ""
    read_out = ((out.get("football_read") or {}).get("verdict") or {}).get("text") or ""
    short = {"backs him": "backs", "against him": "against", "mixed": "mixed"}
    if v_in:
        add("read_in", f"Read: {into['name']}", short.get(v_in, v_in), 1 if v_in == "backs him" else -1 if v_in == "against him" else 0, read_in)
    if v_out:
        add("read_out", f"Read: {out['name']}", short.get(v_out, v_out), 1 if v_out == "against him" else -1 if v_out == "backs him" else 0, read_out)

    s_in, s_out = into.get("start_percent"), out.get("start_percent")
    if s_in is not None:
        lean = -1 if s_in < START_FLOOR else 1 if s_out is not None and s_out < START_FLOOR else 0
        add("start", "Start %", f"{s_in} v {s_out if s_out is not None else '—'}", lean,
            f"Lineup feed: {into['name']} {s_in}% to start, {out['name']} {s_out if s_out is not None else 'unknown'}%.")

    duties_in, duties_out = into.get("duties") or [], out.get("duties") or []
    if duties_in or duties_out:
        add("duties", "Set pieces", f"{len(duties_in)} v {len(duties_out)}", 0,
            f"{into['name']}: {', '.join(duties_in) or 'none'}. {out['name']}: {', '.join(duties_out) or 'none'}.", counted=False)

    so_in, so_out = into.get("solio_next"), out.get("solio_next")
    if so_in is not None and so_out is not None:
        diff = so_in - so_out
        ours = (into.get("xp_next") or 0) - (out.get("xp_next") or 0)
        add("solio", "Solio", f"{diff:+.1f}", 1 if diff >= SOLIO_STEP else -1 if diff <= -SOLIO_STEP else 0,
            f"Solio next gameweek: {into['name']} {so_in:.1f}, {out['name']} {so_out:.1f} ({diff:+.1f}; ours {ours:+.1f}).")

    conf = move.get("confidence") or {}
    win = conf.get("win_prob")
    if win is not None:
        add("replays", "Replays won", _pct(win), 1 if win >= WIN_SOLID else -1 if win < WIN_THIN else 0,
            f"Replayed {conf.get('trials', 4000):,} times with talent uncertainty: wins {_pct(win)}, by {conf.get('mean_diff', 0):+.1f} "
            f"on average (10-90%: {conf.get('p10', 0):+.0f} to {conf.get('p90', 0):+.0f}).")

    stress = move.get("stress") or {}
    if stress.get("survives_half") is True:
        add("stress", "Robust", "survives ½", 0, f"Still clears the bar with the edge halved ({stress.get('gain_if_half', 0):+.1f}).", counted=False)
    elif stress.get("survives_half") is False and stress.get("breakeven_drop_pct") is not None:
        add("stress", "Fragile", f"{stress['breakeven_drop_pct']:.0f}%", -1,
            f"Stops paying if {into['name']}'s projection is {stress['breakeven_drop_pct']:.0f}% too high.", counted=False)

    e_in, e_out = eo.get(into["player_id"]), eo.get(out["player_id"])
    if e_in is not None and e_out is not None:
        add("top10k", "Top-10k EO", f"{e_in[0]:.2f} v {e_out[0]:.2f}", 0,
            f"Effective ownership in the top 10k: {into['name']} {e_in[0]:.2f} ({'shield' if e_in[0] >= 0.5 else 'differential'}), "
            f"{out['name']} {e_out[0]:.2f}.", counted=False)

    p_rise = into.get("price_p_rise")
    if p_rise is not None and p_rise >= RISE_LIKELY:
        add("price", "Price rise", _pct(p_rise), 1, f"{into['name']} {_pct(p_rise)} to rise tonight: buy before it moves.", counted=False)
    for side, sign in ((into, -1), (out, 1)):
        n = yellows.get(side["player_id"])
        if n is not None and n >= YELLOW_WATCH:
            add(f"cards_{side['player_id']}", f"Cards: {side['name']}", f"{n} YC", sign,
                f"{side['name']} on {n} yellows; five by the club's 19th match is a ban.", counted=False)
    games = sorted({g.split(" v ")[0] for side in (into, out) for g in midweek.get(side["player_id"], [])})
    if games:
        add("midweek", "Midweek", ", ".join(games), 0,
            "; ".join(f"{side['name']}: {', '.join(midweek[side['player_id']])}" for side in (into, out) if midweek.get(side["player_id"]))
            + ". Measured: regulars' league minutes do not drop after a European tie.", counted=False)
    form_in = (into.get("form") or {}).get("label")
    if form_in in ("HOT", "COLD"):
        add("form", "Form", form_in.lower(), 0, f"{into['name']} {form_in.lower()} over his last three; such spells do not carry (measured).", counted=False)

    score = sum(lz["lean"] for lz in lenses if lz["counted"])
    for_ = [lz["detail"] for lz in lenses if lz["lean"] > 0]
    against = [lz["detail"] for lz in lenses if lz["lean"] < 0]
    context = [lz["detail"] for lz in lenses if lz["lean"] == 0]
    grade = "strong" if score >= 3 else "sound" if score >= 1 else "marginal" if score == 0 else "doubtful"
    return {
        "out_id": out["player_id"], "into_id": into["player_id"], "out": out["name"], "into": into["name"],
        "position": POSITION_WORD.get(into.get("position"), into.get("position")), "grade": grade, "score": score,
        "for": for_, "against": against, "context": context, "lenses": lenses,
        "runs": {"into": run_in[:5], "out": run_out[:5]}, "into_team": into.get("team_short"), "out_team": out.get("team_short"),
        "into_photo": into.get("photo_code"), "out_photo": out.get("photo_code"),
        "into_team_code": into.get("team_code"), "out_team_code": out.get("team_code"), "gain": move.get("gain"),
    }


def captain_brief(lineup: dict, rank: dict | None, fixtures: dict, names: dict[int, str]) -> dict | None:
    starters = {p["player_id"]: p for p in lineup.get("starting", [])}
    cap = starters.get(lineup.get("captain_id"))
    if cap is None:
        return None
    rows = {c["player_id"]: c for c in (rank or {}).get("captains", [])}
    options = []
    for p in sorted(starters.values(), key=lambda p: -p["xp"])[:4]:
        run = _run(fixtures, p.get("team_code"))
        nxt = run[0] if run else None
        r = rows.get(p["player_id"], {})
        options.append({
            "player_id": p["player_id"], "name": p["name"], "xp": p["xp"], "ceiling": p.get("ceiling"),
            "fixture": f"{nxt['opponent_short']} ({'H' if nxt['is_home'] else 'a'})" if nxt else None,
            "difficulty": nxt["difficulty"] if nxt else None, "start_percent": p.get("start_percent"),
            "field_captain_share": r.get("field_captain_share"), "field_eo": r.get("field_eo"),
            "chance": r.get("chance"), "week_sd": r.get("week_sd"), "chosen": p["player_id"] == cap["player_id"],
        })
    chosen = next(o for o in options if o["chosen"]) if any(o["chosen"] for o in options) else None
    if chosen is None:
        return None
    field_fav = max(options, key=lambda o: o["field_captain_share"] or 0.0)
    lines = [f"{chosen['name']}: {chosen['xp']:.2f} xP, {chosen['fixture'] or 'no fixture'}."]
    if field_fav["player_id"] != chosen["player_id"] and (field_fav["field_captain_share"] or 0) >= 0.3:
        gap = chosen["xp"] - field_fav["xp"]
        lines.append(
            f"The top 10k captain {field_fav['name']} ({_pct(field_fav['field_captain_share'])}). {chosen['name']} is the "
            f"differential: {gap:+.2f} xP on the projections, and the gameweek's spread against the field is wider "
            f"({chosen['week_sd'] or 0:.1f} points against {field_fav['week_sd'] or 0:.1f}) - a bigger swing either way."
        )
    elif (chosen["field_captain_share"] or 0) >= 0.3:
        lines.append(f"The same armband as {_pct(chosen['field_captain_share'])} of the top 10k: a shield, so his score barely moves your rank.")
    if chosen.get("chance") is not None and field_fav.get("chance") is not None and field_fav["player_id"] != chosen["player_id"]:
        lines.append(f"Chance of a top-10k finish: {_pct(chosen['chance'])} with {chosen['name']}, {_pct(field_fav['chance'])} with {field_fav['name']}.")
    if lineup.get("captain_note"):
        lines.append(lineup["captain_note"])
    return {"captain_id": chosen["player_id"], "lines": lines, "options": options}


def overview(rank: dict | None, payload: dict) -> list[str]:
    if not rank:
        return []
    opts = {o["key"]: o for o in rank.get("options", [])}
    plan, roll = opts.get("plan"), opts.get("roll")
    out = [f"{rank['gap']} points behind the 10,000th with {rank['weeks_left']} gameweeks left: "
           f"{rank['gap'] / max(rank['weeks_left'], 1):.1f} a week above the top-10k average closes it; "
           f"you have run at {rank['pace']['mean']:+.1f} a week over {rank['pace']['weeks']} measured gameweeks."]
    if plan and roll and plan is not roll:
        out.append(f"Chance of a top-10k finish: {_pct(plan['chance'])} with the plan, {_pct(roll['chance'])} rolling.")
    best = opts.get(rank.get("best_option") or "")
    if best and plan and best["key"] != "plan" and best["chance"] - plan["chance"] >= 0.005:
        out.append(f"On rank alone '{best['label']}' edges it ({_pct(best['chance'])}): within the plan's noise, so the plan stands.")
    return out


def pundit_brief(conn: sqlite3.Connection, payload: dict, rank: dict | None) -> dict:
    moves = payload.get("moves", [])
    fixtures = payload.get("fixtures") or {}
    lineup = payload.get("lineup_after") or {}
    ids = {p["player_id"] for p in lineup.get("starting", [])}
    for m in moves:
        ids |= {m["out"]["player_id"], m["into"]["player_id"]}
    try:
        eo = top10k_ownership(conn, payload["event"], ids)
    except Exception:
        eo = {}
    yellows = _yellows(conn, ids)
    midweek = _midweek(conn, ids)
    names = {p["player_id"]: p["name"] for p in lineup.get("starting", [])}
    briefs = [move_brief(m, fixtures, eo, yellows, midweek, payload.get("horizon") or 5) for m in moves]
    return {
        "overview": overview(rank, payload),
        "moves": briefs,
        "captain": captain_brief(lineup, rank, fixtures, names),
        "rank": rank,
    }
