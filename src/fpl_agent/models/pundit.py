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
    out, into = move["out"], move["into"]
    for_, against, context = [], [], []
    score = 0

    gain = move.get("gain") or 0.0
    line = (f"+{gain:.1f} over {horizon} gameweeks on the projections: {into['name']} "
            f"{' / '.join(f'{x:.1f}' for x in into.get('xp_by_gw') or [])} against {out['name']} "
            f"{' / '.join(f'{x:.1f}' for x in out.get('xp_by_gw') or [])}.")
    (for_ if gain >= BIG_GAIN else context).append(line)
    score += 1 if gain >= BIG_GAIN else 0

    run_in, run_out = _run(fixtures, into.get("team_code")), _run(fixtures, out.get("team_code"))
    if run_in and into.get("team_code") == out.get("team_code"):
        context.append(f"Same club, same fixtures: {into['team_short']} {_fixture_text(run_in)}.")
    elif run_in and run_out:
        d_in, d_out = _mean_difficulty(run_in), _mean_difficulty(run_out)
        d3_in, d3_out = _mean_difficulty(run_in, 3), _mean_difficulty(run_out, 3)
        text = (f"Fixture by fixture: {into['team_short']} {_fixture_text(run_in)} (average {d_in:.1f}) against "
                f"{out['team_short']} {_fixture_text(run_out)} (average {d_out:.1f}); next three {d3_in:.1f} against {d3_out:.1f}.")
        if d_out - d_in >= FIXTURE_STEP:
            for_.append(text)
            score += 1
        elif d_in - d_out >= FIXTURE_STEP:
            against.append(text)
            score -= 1
        else:
            context.append(text)

    v_in, v_out = _verdict(into), _verdict(out)
    read_in = ((into.get("football_read") or {}).get("verdict") or {}).get("text")
    read_out = ((out.get("football_read") or {}).get("verdict") or {}).get("text")
    if v_in == "backs him":
        for_.append(f"The football read on {into['name']}: {read_in}")
        score += 1
    elif v_in == "against him":
        against.append(f"The football read on {into['name']}: {read_in}")
        score -= 1
    if v_out == "against him":
        for_.append(f"The football read on {out['name']}: {read_out}")
        score += 1
    elif v_out == "backs him":
        against.append(f"The football read on {out['name']} still backs him: {read_out}")
        score -= 1

    s_in, s_out = into.get("start_percent"), out.get("start_percent")
    if s_in is not None and s_in < START_FLOOR:
        against.append(f"{into['name']} is {s_in}% to start on the lineup feed.")
        score -= 1
    elif s_in is not None and s_out is not None and s_out < START_FLOOR:
        for_.append(f"{out['name']} is {s_out}% to start; {into['name']} {s_in}%.")

    duties_in, duties_out = into.get("duties") or [], out.get("duties") or []
    if duties_in or duties_out:
        context.append(f"Set pieces: {into['name']} {', '.join(duties_in) or 'none'}; {out['name']} {', '.join(duties_out) or 'none'}.")

    so_in, so_out = into.get("solio_next"), out.get("solio_next")
    if so_in is not None and so_out is not None:
        diff = so_in - so_out
        ours = (into.get("xp_next") or 0) - (out.get("xp_next") or 0)
        text = (f"Solio's model next gameweek: {into['name']} {so_in:.1f}, {out['name']} {so_out:.1f} ({diff:+.1f}; "
                f"ours {ours:+.1f}).")
        if diff >= SOLIO_STEP:
            for_.append(text)
            score += 1
        elif diff <= -SOLIO_STEP:
            against.append(text)
            score -= 1
        else:
            context.append(text)

    conf = move.get("confidence") or {}
    win = conf.get("win_prob")
    if win is not None:
        text = (f"Replayed {conf.get('trials', 4000):,} times with talent uncertainty: the move wins in {_pct(win)}, "
                f"by {conf.get('mean_diff', 0):+.1f} on average (10-90%: {conf.get('p10', 0):+.0f} to {conf.get('p90', 0):+.0f}).")
        if win >= WIN_SOLID:
            for_.append(text)
            score += 1
        elif win < WIN_THIN:
            against.append(text)
            score -= 1
        else:
            context.append(text)

    stress = move.get("stress") or {}
    if stress.get("survives_half") is True:
        context.append(f"Still clears the bar if {into['name']}'s edge over {out['name']} is halved ({stress.get('gain_if_half', 0):+.1f}).")
    elif stress.get("survives_half") is False and stress.get("breakeven_drop_pct") is not None:
        against.append(f"Fragile: the move stops paying if {into['name']}'s projection is {stress['breakeven_drop_pct']:.0f}% too high.")

    e_in, e_out = eo.get(into["player_id"]), eo.get(out["player_id"])
    if e_in is not None and e_out is not None:
        context.append(
            f"Top 10k: {into['name']} effective ownership {e_in[0]:.2f} ({'a shield' if e_in[0] >= 0.5 else 'a differential'}), "
            f"{out['name']} {e_out[0]:.2f}. Owning a player the top 10k hold protects rank; one they do not moves it."
        )

    p_rise = into.get("price_p_rise")
    if p_rise is not None and p_rise >= RISE_LIKELY:
        for_.append(f"{into['name']} has a {_pct(p_rise)} chance to rise tonight: make it before the price moves.")
    for side in (into, out):
        n = yellows.get(side["player_id"])
        if n is not None and n >= YELLOW_WATCH:
            (against if side is into else for_).append(f"{side['name']} is on {n} yellows (five by the 19th club match is a ban).")
    for side in (into, out):
        games = midweek.get(side["player_id"])
        if games:
            context.append(f"{side['name']}'s club plays midweek: {'; '.join(games)} (measured: regulars' league minutes do not drop after a European tie).")

    form_in = (into.get("form") or {}).get("label")
    if form_in in ("HOT", "COLD"):
        context.append(f"{into['name']} is {form_in.lower()} over his last three; streaks of that kind do not carry into the next match (measured), so it is not counted.")

    grade = "strong" if score >= 3 else "sound" if score >= 1 else "marginal" if score == 0 else "doubtful"
    return {
        "out_id": out["player_id"], "into_id": into["player_id"], "out": out["name"], "into": into["name"],
        "position": POSITION_WORD.get(into.get("position"), into.get("position")), "grade": grade, "score": score,
        "for": for_, "against": against, "context": context,
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
