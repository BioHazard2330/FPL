"""THE FOOTBALL READ: what a scout would tell you about a player before you buy or sell him, from stored evidence only,
each line marked by whether that kind of evidence has carried into the next match.

Lines, each stating the numbers behind it:
- craft: profile labels and the measures where he ranks in the top or bottom quarter of his position (`scouting`);
- chances: shots and non-penalty xG per 90 against his position. These carry: between a player's prior average and his
  next match, shots per 90 r 0.56 and xG per 90 r 0.48 over 18,387 Understat player-matches (`signal_reliability`);
- creation and defensive work: xA, key passes, defensive actions against his position;
- finishing: goals against non-penalty xG. This does not carry (goals minus xG r 0.03 over 3,600 team-matches), so
  returns follow the chances, not the goals;
- duties: penalty, corner and free-kick order from FPL's notes and penalties taken this season;
- recent spell: the last three matches against the rest of his season and what followed such spells in history
  (`form_watch`): only a collapse below a quarter of earlier output has carried;
- minutes: FPL's flag, the lineup feed's start chance, his place on the last official team sheet;
- discipline: yellows and the chance of serving a ban in the next five gameweeks (`suspension_risk`);
- fixtures: the next five against the league for his club's expected goals (attackers) or clean-sheet chance (keepers
  and defenders), and where his chances come from against what each opponent concedes (a lens, unmeasured).

`weight` is "carries" (measured to persist), "context" (true now, persistence not measured) or "noise" (measured not to
persist); `lean` is +1 toward owning him, -1 against, 0 neither. The verdict counts a carrying lean as 1 and a context
lean as a half. This is an interpretation laid beside the projection, never an input to it."""
import sqlite3

CARRIES = "carries"
CONTEXT = "context"
NOISE = "noise"
TOP = 75
BOTTOM = 25
FINISHING_GAP = 1.0
FIXTURE_XG_EDGE = 0.12
FIXTURE_CS_EDGE = 0.04
FIT_GOOD = 1.1
FIT_BAD = 0.9
START_DOUBT = 60
WINDOW = 5
_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_POSITION_PLURAL = {"GKP": "keepers", "DEF": "defenders", "MID": "midfielders", "FWD": "forwards"}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _lc(label: str) -> str:
    return label[0].lower() + label[1:]


def _line(topic: str, text: str, weight: str, lean: int = 0) -> dict:
    return {"topic": topic, "text": text, "weight": weight, "lean": lean}


def _measure(report: dict, key: str) -> dict | None:
    return next((m for m in report["measures"] if m["key"] == key), None)


def _pct_text(m: dict) -> str:
    return f"{m['display']} {m['unit']}" + (f" ({_ordinal(m['percentile'])} percentile)" if m.get("percentile") is not None else "")


def _craft(report: dict) -> list[dict]:
    if not report["ranked"]:
        return [_line("Craft", f"{report['minutes']} minutes this season: too few to rank him against his position.", CONTEXT)]
    parts = []
    if report["profile"]:
        parts.append(", ".join(report["profile"]))
    if report["strengths"]:
        parts.append("best at " + "; ".join(f"{_lc(m['label'])} {_pct_text(m)}" for m in report["strengths"][:3]))
    if report["weaknesses"]:
        parts.append("weakest at " + "; ".join(f"{_lc(m['label'])} {_pct_text(m)}" for m in report["weaknesses"][:2]))
    if not parts:
        return []
    return [_line("Craft", ". ".join(p[0].upper() + p[1:] for p in parts) + f" (against {_POSITION_PLURAL[report['position']]}, {report['minutes']} minutes).", CONTEXT)]


def _chances(report: dict) -> list[dict]:
    if report["position"] == "GKP" or not report["ranked"]:
        return []
    shots, npxg = _measure(report, "shots90"), _measure(report, "npxg90")
    known = [m for m in (shots, npxg) if m and m.get("percentile") is not None]
    if not known:
        return []
    best = max(m["percentile"] for m in known)
    lean = 1 if best >= TOP else -1 if best <= BOTTOM and report["position"] in ("MID", "FWD") else 0
    text = " and ".join(f"{m['display']} {_lc(m['label'])} per 90 ({_ordinal(m['percentile'])} percentile)" for m in known)
    return [_line("Chances", f"{text[0].upper()}{text[1:]}. Chance volume carries from match to match (shots r 0.56, xG r 0.48).", CARRIES, lean)]


def _creation_and_defence(report: dict) -> list[dict]:
    out = []
    xa, kp = _measure(report, "xa90"), _measure(report, "key_passes90")
    known = [m for m in (xa, kp) if m and m.get("percentile") is not None]
    if known and report["position"] in ("MID", "FWD", "DEF"):
        top = max(m["percentile"] for m in known)
        if top >= TOP or (report["position"] in ("MID", "FWD") and top <= BOTTOM):
            text = " and ".join(f"{m['display']} {_lc(m['label'])} per 90 ({_ordinal(m['percentile'])} percentile)" for m in known)
            out.append(_line("Creation", f"{text[0].upper()}{text[1:]}.", CONTEXT, 1 if top >= TOP else -1))
    dc = _measure(report, "defcon90")
    if dc and dc.get("percentile") is not None and report["position"] in ("DEF", "MID") and (dc["percentile"] >= TOP or dc["percentile"] <= BOTTOM):
        out.append(_line(
            "Defensive work", f"{dc['display']} defensive actions per 90 ({_ordinal(dc['percentile'])} percentile): "
            + ("the volume that earns defensive-contribution points." if dc["percentile"] >= TOP else "rarely near the defensive-contribution threshold."),
            CONTEXT, 1 if dc["percentile"] >= TOP else 0,
        ))
    prevented = _measure(report, "prevented90")
    if prevented and prevented.get("percentile") is not None:
        out.append(_line("Shot-stopping", f"{prevented['display']} goals prevented per 90 ({_ordinal(prevented['percentile'])} percentile).", CONTEXT,
                         1 if prevented["percentile"] >= TOP else -1 if prevented["percentile"] <= BOTTOM else 0))
    return out


def _finishing(report: dict) -> list[dict]:
    f = report.get("finishing")
    if not f or abs(f["difference"]) < FINISHING_GAP:
        return []
    over = f["difference"] > 0
    return [_line(
        "Finishing", f"{f['np_goals']} non-penalty goals from {f['npxg']:.2f} xG ({f['difference']:+.1f}). Scoring "
        + ("above" if over else "below") + " the chances does not carry (r 0.03), so expect returns to follow the chances"
        + (": the goals flatter him." if over else ": the goals undersell him."),
        NOISE,
    )]


def _duties(conn: sqlite3.Connection, player_id: int, report: dict | None) -> list[dict]:
    row = conn.execute(
        "SELECT penalties_order, corners_order, direct_fk_order FROM player_setpiece_history WHERE player_id=? AND valid_until IS NULL "
        "ORDER BY rowid DESC LIMIT 1", (player_id,),
    ).fetchone()
    if row is None:
        return []
    parts = []
    lean = 0
    if row["penalties_order"] == 1:
        parts.append("first on penalties")
        lean = 1
    elif row["penalties_order"] == 2:
        parts.append("second on penalties")
    if row["corners_order"] == 1:
        parts.append("first on corners")
    if row["direct_fk_order"] == 1:
        parts.append("first on direct free kicks")
    if not parts:
        return []
    taken = report.get("penalties") if report else None
    tail = f"; {taken} penalt{'y' if taken == 1 else 'ies'} taken this season" if taken else ""
    return [_line("Duties", f"{', '.join(parts).capitalize()} per FPL's set-piece notes{tail}.", CONTEXT, lean)]


def _spell(form: dict | None) -> list[dict]:
    if not form or form.get("recent_xgi90") is None or form.get("ratio") is None:
        return []
    ev = form.get("evidence") or {}
    lo, hi = (ev.get("ci") or (None, None))
    collapse = hi is not None and hi < 1.0
    text = (f"Last three matches {form['recent_xgi90']:.2f} xG+xA per 90 against {form['before_xgi90']:.2f} before "
            f"({form['ratio']:.2f}x), shots {form['recent_shots90']:.1f} against {form['before_shots90']:.1f}.")
    if ev.get("ratio") is not None:
        text += (f" Spells like this were followed by {ev['ratio']:.2f}x the baseline next match "
                 f"(90% {lo:.2f} to {hi:.2f}, {ev['n']:,} cases)" + (": this kind of drop has carried." if collapse else ": no signal."))
    return [_line("Recent spell", text, CARRIES if collapse else NOISE, -1 if collapse else 0)]


def _minutes(conn: sqlite3.Connection, player_id: int) -> list[dict]:
    from fpl_agent.ingestion.lineup_probability_source import get_start_percent
    from fpl_agent.models.matchday_status import latest_sheet_roles

    p = conn.execute("SELECT status, news, team_id FROM players WHERE id=?", (player_id,)).fetchone()
    if p is None:
        return []
    parts = []
    lean = 0
    if p["status"] in ("i", "s", "u", "n"):
        parts.append(f"flagged unavailable ({p['news'] or p['status']})")
        lean = -1
    elif p["status"] == "d":
        parts.append(f"flagged doubtful ({p['news'] or 'no detail'})")
        lean = -1
    start = get_start_percent(conn, player_id)
    if start is not None:
        parts.append(f"{start}% to start on the lineup feed")
        if start < START_DOUBT:
            lean = -1
    role = latest_sheet_roles(conn).get(player_id)
    if role:
        parts.append({"STARTING": "started his last match", "BENCH": "on the bench last match",
                      "NOT_IN_SQUAD": "left out of the last matchday squad"}.get(role[0], role[0].lower()))
        if role[0] == "NOT_IN_SQUAD":
            lean = -1
    from fpl_agent.models.news_warning import fresh_warnings

    warning = fresh_warnings(conn, [player_id]).get(player_id)
    if warning is not None:
        rate = warning.get("rate") or {}
        parts.append(f"an injury headline in the last three days (\"{warning['title']}\")"
                     + (f", followed by an FPL flag {rate['rate']:.0%} of the time" if rate.get("rate") else ""))
        lean = -1
    rows = conn.execute(
        "SELECT event, SUM(minutes) AS m FROM player_gw_stats WHERE player_id=? GROUP BY event ORDER BY event DESC LIMIT 3", (player_id,),
    ).fetchall()
    if rows:
        parts.append("minutes in his last three gameweeks " + ", ".join(str(int(r["m"] or 0)) for r in reversed(rows)))
    if not parts:
        return []
    text = "; ".join(parts)
    return [_line("Minutes", text[0].upper() + text[1:] + ".", CARRIES, lean)]


def _discipline(conn: sqlite3.Connection, player_id: int, event: int | None) -> list[dict]:
    from fpl_agent.monitoring.api.squadnews_payload import BAN_RISK_FLAG, _yellow_ban_risk

    risk = _yellow_ban_risk(conn, player_id, event)
    if risk is None:
        return []
    yellows, chance, last = risk
    return [_line("Discipline", f"{yellows} yellow cards; {chance:.0%} chance he serves a one-match ban by GW{last}.", CONTEXT,
                  -1 if chance >= BAN_RISK_FLAG else 0)]


def _fixtures(conn: sqlite3.Connection, team_id: int, position: str, event: int, mix: dict | None) -> list[dict]:
    from fpl_agent.models.fixture_matchups import matchup_board
    from fpl_agent.models.fixture_outlook import team_fixture_outlook

    outlook = team_fixture_outlook(conn, event, WINDOW)
    mine = outlook.get(team_id)
    if mine is None:
        return []
    all_fx = [f for row in outlook.values() for fs in row["events"].values() for f in fs]
    if not all_fx:
        return []
    league_xg = sum(f["xg_for"] for f in all_fx) / len(all_fx)
    league_cs = sum(f["cs"] for f in all_fx) / len(all_fx)
    board = matchup_board(conn, {team_id}, event, WINDOW)["teams"].get(str(team_id))
    fixtures = board["fixtures"] if board else []
    if not fixtures:
        return [_line("Fixtures", f"No fixtures in GW{event}-{event + WINDOW - 1}.", CONTEXT, -1)]
    names = ", ".join(f"{f['opponent']} {'H' if f['home'] else 'A'}" for f in fixtures)
    defensive = position in ("GKP", "DEF")
    if defensive:
        cs = sum(f["cs"] for f in fixtures) / len(fixtures)
        lean = 1 if cs - league_cs >= FIXTURE_CS_EDGE else -1 if league_cs - cs >= FIXTURE_CS_EDGE else 0
        text = (f"Next {len(fixtures)}: {names}. Clean-sheet chance averages {cs:.0%} against a league {league_cs:.0%} "
                f"(defence ranked {_ordinal(mine['defence_rank'])} of {mine['clubs_ranked']} for these weeks).")
    else:
        xg = sum(f["xg_for"] for f in fixtures) / len(fixtures)
        lean = 1 if xg - league_xg >= FIXTURE_XG_EDGE else -1 if league_xg - xg >= FIXTURE_XG_EDGE else 0
        text = (f"Next {len(fixtures)}: {names}. His club expects {xg:.2f} goals a match against a league {league_xg:.2f} "
                f"(attack ranked {_ordinal(mine['attack_rank'])} of {mine['clubs_ranked']} for these weeks).")
    out = [_line("Fixtures", text, CARRIES, lean)]
    if mix and not defensive:
        fits = []
        for f in fixtures:
            oc = f.get("opp_concede") or {}
            weight = sum(v for k, v in mix.items() if k in oc)
            if weight >= 0.5:
                fits.append((f, sum(v * oc[k] for k, v in mix.items() if k in oc) / weight))
        good = [f"{f['opponent']} x{v:.2f}" for f, v in fits if v >= FIT_GOOD]
        bad = [f"{f['opponent']} x{v:.2f}" for f, v in fits if v <= FIT_BAD]
        if good or bad:
            main = ", ".join(f"{round(v * 100)}% {k}" for k, v in sorted(mix.items(), key=lambda kv: -kv[1])[:2])
            text = f"His chances: {main}." + (f" Opponents that give that kind away: {', '.join(good)}." if good else "") + (
                f" Opponents that shut it out: {', '.join(bad)}." if bad else "")
            out.append(_line("Style against opponents", text, CONTEXT, 0))
    return out


def _verdict(lines: list[dict]) -> dict:
    score = sum(line["lean"] * (1.0 if line["weight"] == CARRIES else 0.5 if line["weight"] == CONTEXT else 0.0) for line in lines)
    pros = [line["topic"].lower() for line in lines if line["lean"] > 0 and line["weight"] != NOISE]
    cons = [line["topic"].lower() for line in lines if line["lean"] < 0 and line["weight"] != NOISE]
    label = "backs him" if score >= 1.5 else "against him" if score <= -1.5 else "mixed"
    if label == "backs him" and any(line["topic"] == "Minutes" and line["lean"] < 0 for line in lines):
        label = "mixed"
    text = {"backs him": "The football backs him", "against him": "The football is against him", "mixed": "The football is mixed"}[label]
    if pros:
        text += f": for him, {', '.join(pros)}"
    if cons:
        text += ("; " if pros else ": ") + f"against, {', '.join(cons)}"
    return {"label": label, "score": round(score, 1), "text": text + "."}


WATCHERS_UP = 7.5
WATCHERS_DOWN = 5.5


def _watchers(conn: sqlite3.Connection, player_id: int) -> list[dict]:
    """What people who watched him said (`ingestion/watcher_ratings`): the BBC reporter's score and verdict and the fans'
    average over his last rated matches. Measured 2026-10-29 on 203 rated player-matches: neither score predicted the
    next gameweek's points beyond his points and chances so far, so the line is context and never a projection input;
    it leans the verdict (and through it the plan's eye gate) when the watchers were clearly impressed or not."""
    try:
        from fpl_agent.ingestion.watcher_ratings import watchers_for_player

        rated = watchers_for_player(conn, player_id, limit=3)
    except Exception:
        return []
    if not rated:
        return []
    latest = rated[0]
    scores = [x for r in rated for x in (r["reporter"], r["fans"]) if x is not None]
    mean = sum(scores) / len(scores) if scores else None
    bits = []
    if latest["reporter"] is not None:
        bits.append(f"BBC reporter {latest['reporter']:g}/10" + (f" (\"{latest['note']}\")" if latest["note"] else ""))
    if latest["fans"] is not None:
        bits.append(f"fans {latest['fans']:.2f}")
    if latest["potm"]:
        bits.append("fans' player of the match")
    text = f"GW{latest['event']} {'v' if latest['home'] else 'at'} {latest['opponent']}: " + ", ".join(bits)
    if len(rated) > 1 and mean is not None:
        text += f". Average over his last {len(rated)} rated matches {mean:.1f}"
    lean = 1 if mean is not None and mean >= WATCHERS_UP else -1 if mean is not None and mean <= WATCHERS_DOWN else 0
    return [_line("Watchers", text + ".", "context", lean)]


def football_read(conn: sqlite3.Connection, player_id: int, event: int | None = None) -> dict | None:
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.models.form_watch import form_watch
    from fpl_agent.models.scouting import scouting_report

    p = conn.execute("SELECT web_name, team_id, element_type FROM players WHERE id=?", (player_id,)).fetchone()
    if p is None:
        return None
    event = event or _reference_event(conn)
    position = _POSITION.get(p["element_type"], "MID")
    report = scouting_report(conn, player_id)
    lines: list[dict] = []
    if report:
        lines += _craft(report) + _chances(report) + _creation_and_defence(report) + _finishing(report)
    lines += _duties(conn, player_id, report)
    if position in ("MID", "FWD"):
        lines += _spell(form_watch(conn, [player_id]).get(player_id))
    lines += _watchers(conn, player_id)
    lines += _minutes(conn, player_id) + _discipline(conn, player_id, event)
    lines += _fixtures(conn, p["team_id"], position, event, report.get("source_mix") if report else None)
    return {"player_id": player_id, "name": p["web_name"], "position": position, "event": event,
            "verdict": _verdict(lines), "lines": lines}
